import asyncio
import base64
import io
import json
import os
import time
import wave
from array import array
from pathlib import Path
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv
import webrtcvad


# ============================================================
# Configuration
# ============================================================

load_dotenv()
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GUILD_ID = int(os.environ["GUILD_ID"])

TRANSCRIPTION_MODEL = "gpt-4o-transcribe"
TRANSLATION_MODEL = "gpt-4o-mini"

# Discord's decoded PCM audio is 48 kHz, stereo, signed 16-bit PCM.
PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 2
PCM_SAMPLE_WIDTH = 2

# An utterance is considered finished after this much packet silence.
UTTERANCE_SILENCE_SECONDS = 0.75

# Ignore extremely short bursts/clicks.
MIN_UTTERANCE_SECONDS = 0.30

# Flush very long uninterrupted speech periodically.
MAX_UTTERANCE_SECONDS = 25.0

# WebRTC voice activity detection. 0 is least aggressive, 3 is most aggressive.
VAD_AGGRESSIVENESS = 3
VAD_FRAME_MS = 30
VAD_MIN_SPEECH_RATIO = 0.4
VAD_MIN_CONSECUTIVE_SPEECH_FRAMES = 6

# How frequently the bot checks whether an utterance has ended.
BUFFER_CHECK_INTERVAL = 0.10

VOICE_WORKER_HOST = "127.0.0.1"
VOICE_WORKER_PORT = int(os.environ.get("VOICE_WORKER_PORT", "8765"))
VOICE_WORKER_START_TIMEOUT = 20.0
VOICE_WORKER_JOIN_TIMEOUT = 20.0


# Broad reference list of language tags users can enter with /join, /add,
# and /remove. This is intentionally not used as a validation whitelist:
# other valid BCP 47 tags may still be accepted by the bot.
LANGUAGE_TAGS = {
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "as": "Assamese",
    "az": "Azerbaijani",
    "ba": "Bashkir",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "bo": "Tibetan",
    "br": "Breton",
    "bs": "Bosnian",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "eu": "Basque",
    "fa": "Persian",
    "fi": "Finnish",
    "fo": "Faroese",
    "fr": "French",
    "gl": "Galician",
    "gu": "Gujarati",
    "ha": "Hausa",
    "haw": "Hawaiian",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "ht": "Haitian Creole",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "jv": "Javanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "la": "Latin",
    "lb": "Luxembourgish",
    "ln": "Lingala",
    "lo": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mg": "Malagasy",
    "mi": "Māori",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "mt": "Maltese",
    "my": "Burmese",
    "ne": "Nepali",
    "nl": "Dutch",
    "nn": "Norwegian Nynorsk",
    "no": "Norwegian",
    "oc": "Occitan",
    "pa": "Punjabi",
    "pl": "Polish",
    "ps": "Pashto",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sa": "Sanskrit",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sn": "Shona",
    "so": "Somali",
    "sq": "Albanian",
    "sr": "Serbian",
    "su": "Sundanese",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "tg": "Tajik",
    "th": "Thai",
    "tk": "Turkmen",
    "tl": "Tagalog",
    "tr": "Turkish",
    "tt": "Tatar",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zh": "Chinese",
}

REGIONAL_LANGUAGE_TAGS = {
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
    "es-ES": "Spanish (Spain)",
    "es-MX": "Spanish (Mexico)",
    "fr-FR": "French (France)",
    "fr-CA": "French (Canada)",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "zh-CN": "Chinese (Simplified, China)",
    "zh-TW": "Chinese (Traditional, Taiwan)",
    "zh-Hans": "Chinese (Simplified script)",
    "zh-Hant": "Chinese (Traditional script)",
}


openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)


# ============================================================
# Helpers
# ============================================================

def normalize_language_tag(tag: str) -> str:
    """
    Normalize the casing of a BCP 47-style language tag without restricting
    it to a hard-coded list of languages.

    Examples:
        EN          -> en
        pt-br       -> pt-BR
        zh-hant-tw  -> zh-Hant-TW
    """
    parts = [part for part in tag.strip().replace("_", "-").split("-") if part]

    if not parts:
        return ""

    normalized = [parts[0].lower()]

    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (
            (len(part) == 2 and part.isalpha())
            or (len(part) == 3 and part.isdigit())
        ):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())

    return "-".join(normalized)


def parse_languages(value: str) -> list[str]:
    """
    Parse a comma-separated list of BCP 47-style language tags.

    Examples:
        en, ja, es
        en,ja,pt-BR,zh-Hant-TW

    There is deliberately no hard-coded list of allowed languages.
    """
    languages = []

    for part in value.split(","):
        language_tag = normalize_language_tag(part)

        if not language_tag:
            continue

        if not any(
            existing.casefold() == language_tag.casefold()
            for existing in languages
        ):
            languages.append(language_tag)

    return languages


def make_wav_bytes(pcm: bytes) -> bytes:
    output = io.BytesIO()

    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(PCM_CHANNELS)
        wav_file.setsampwidth(PCM_SAMPLE_WIDTH)
        wav_file.setframerate(PCM_SAMPLE_RATE)
        wav_file.writeframes(pcm)

    output.seek(0)
    return output.read()


def pcm_duration_seconds(pcm: bytes) -> float:
    bytes_per_second = PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH

    if bytes_per_second == 0:
        return 0.0

    return len(pcm) / bytes_per_second


def stereo_pcm_to_mono(pcm: bytes) -> bytes:
    """Convert 16-bit little-endian stereo PCM to 16-bit mono PCM."""
    samples = array("h")
    samples.frombytes(pcm)

    if len(samples) < 2:
        return b""

    if os.sys.byteorder != "little":
        samples.byteswap()

    mono = array("h")
    mono.extend(
        (int(samples[index]) + int(samples[index + 1])) // 2
        for index in range(0, len(samples) - 1, 2)
    )

    if os.sys.byteorder != "little":
        mono.byteswap()

    return mono.tobytes()


def contains_speech(pcm: bytes) -> tuple[bool, float, int]:
    """Return whether an utterance contains enough human speech for STT."""
    mono_pcm = stereo_pcm_to_mono(pcm)
    frame_bytes = PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH * VAD_FRAME_MS // 1000

    if frame_bytes <= 0 or len(mono_pcm) < frame_bytes:
        return False, 0.0, 0

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    speech_frames = 0
    total_frames = 0
    consecutive = 0
    max_consecutive = 0

    for start in range(0, len(mono_pcm) - frame_bytes + 1, frame_bytes):
        frame = mono_pcm[start:start + frame_bytes]
        total_frames += 1

        if vad.is_speech(frame, PCM_SAMPLE_RATE):
            speech_frames += 1
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    if total_frames == 0:
        return False, 0.0, 0

    speech_ratio = speech_frames / total_frames
    is_speech = (
        speech_ratio >= VAD_MIN_SPEECH_RATIO
        and max_consecutive >= VAD_MIN_CONSECUTIVE_SPEECH_FRAMES
    )

    return is_speech, speech_ratio, max_consecutive


def split_discord_message(text: str, limit: int = 1900) -> list[str]:
    """
    Split long translation output without exceeding Discord's 2,000
    character message limit.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(paragraph) > limit:
            split_at = paragraph.rfind("\n", 0, limit)

            if split_at <= 0:
                split_at = paragraph.rfind(" ", 0, limit)

            if split_at <= 0:
                split_at = limit

            chunks.append(paragraph[:split_at].rstrip())
            paragraph = paragraph[split_at:].lstrip()

        current = paragraph

    if current:
        chunks.append(current)

    return chunks


# ============================================================
# Per-speaker audio buffering
# ============================================================

@dataclass
class SpeakerBuffer:
    member: discord.Member
    pcm: bytearray = field(default_factory=bytearray)
    first_packet_time: float = field(default_factory=time.monotonic)
    last_packet_time: float = field(default_factory=time.monotonic)

    def append(self, pcm: bytes) -> None:
        now = time.monotonic()

        if not self.pcm:
            self.first_packet_time = now

        self.pcm.extend(pcm)
        self.last_packet_time = now


# ============================================================
# Translation session
# ============================================================

class TranslationSession:
    def __init__(
        self,
        bot: commands.Bot,
        voice_channel: discord.VoiceChannel,
        languages: list[str],
    ):
        self.bot = bot
        self.voice_channel = voice_channel
        self.languages = languages

        self.buffers: dict[int, SpeakerBuffer] = {}
        self.user_locks: dict[int, asyncio.Lock] = {}

        self.closed = False
        self.buffer_task = asyncio.create_task(self._buffer_loop())

    def add_languages(self, languages: list[str]) -> list[str]:
        added = []

        for language in languages:
            if not any(
                existing.casefold() == language.casefold()
                for existing in self.languages
            ):
                self.languages.append(language)
                added.append(language)

        return added

    def remove_languages(self, languages: list[str]) -> list[str]:
        removed = []

        for requested in languages:
            for existing in self.languages.copy():
                if existing.casefold() == requested.casefold():
                    self.languages.remove(existing)
                    removed.append(existing)
                    break

        return removed

    def receive_pcm(self, member: discord.Member, pcm: bytes) -> None:
        """
        Runs on the Discord asyncio event loop.

        Each Discord member gets an independent buffer. This is what allows
        multiple people to speak over one another without their audio being
        mixed together before transcription.
        """
        if self.closed or member.bot or not pcm:
            return

        buffer = self.buffers.get(member.id)

        if buffer is None:
            buffer = SpeakerBuffer(member=member)
            self.buffers[member.id] = buffer

        buffer.append(pcm)

    async def _buffer_loop(self) -> None:
        try:
            while not self.closed:
                await asyncio.sleep(BUFFER_CHECK_INTERVAL)

                now = time.monotonic()
                ready: list[tuple[int, discord.Member, bytes]] = []

                for user_id, buffer in list(self.buffers.items()):
                    silence_length = now - buffer.last_packet_time
                    utterance_length = now - buffer.first_packet_time

                    if (
                        silence_length >= UTTERANCE_SILENCE_SECONDS
                        or utterance_length >= MAX_UTTERANCE_SECONDS
                    ):
                        pcm = bytes(buffer.pcm)
                        member = buffer.member
                        del self.buffers[user_id]

                        duration = pcm_duration_seconds(pcm)

                        if duration >= MIN_UTTERANCE_SECONDS:
                            print(
                                f"[VOICE] Utterance ready from {member} "
                                f"({member.id}); duration={duration:.2f}s"
                            )
                            ready.append((user_id, member, pcm))

                # Do not await these here. Each completed utterance gets its own
                # task so different users can be transcribed simultaneously.
                for user_id, member, pcm in ready:
                    asyncio.create_task(
                        self._process_utterance(user_id, member, pcm)
                    )

        except asyncio.CancelledError:
            pass

    async def _process_utterance(
        self,
        user_id: int,
        member: discord.Member,
        pcm: bytes,
    ) -> None:
        """
        Keep one user's utterances in order, while allowing different users
        to process concurrently.
        """
        lock = self.user_locks.setdefault(user_id, asyncio.Lock())

        async with lock:
            if self.closed:
                return

            try:
                has_speech, speech_ratio, max_consecutive = contains_speech(pcm)

                if not has_speech:
                    print(
                        f"[VAD] Ignoring non-speech audio from {member} ({member.id}); "
                        f"speech={speech_ratio:.0%}, "
                        f"max_consecutive={max_consecutive} frames"
                    )
                    return

                print(
                    f"[VAD] Speech detected from {member} ({member.id}); "
                    f"speech={speech_ratio:.0%}, "
                    f"max_consecutive={max_consecutive} frames"
                )

                target_languages = self.languages.copy()

                if not target_languages:
                    return

                transcript = await self._transcribe(pcm, target_languages)

                if not transcript:
                    return

                result = await self._translate(transcript, target_languages)

                if self.closed:
                    return

                await self._post_translation(
                    member=member,
                    transcript=transcript,
                    original_language=result["original_language"],
                    translations=result["translations"],
                    target_languages=target_languages,
                )

            except Exception as error:
                print(
                    f"Error processing speech from "
                    f"{member} ({member.id}): {error!r}"
                )

    async def _transcribe(
        self,
        pcm: bytes,
        languages: list[str],
    ) -> str:
        wav_bytes = make_wav_bytes(pcm)

        print(
            f"[OPENAI] Sending {pcm_duration_seconds(pcm):.2f}s "
            f"of audio for transcription..."
        )

        language_list = ", ".join(languages)

        response = await openai_client.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=("speech.wav", wav_bytes, "audio/wav"),
            prompt=(
                f"The speaker is speaking one of these languages: {language_list}. "
                "Transcribe the speech in the language actually spoken. "
                "Do not transcribe the speech into any other languages than those listed. "
                "Favor sentences and phrases that make more sense as something someone would naturally say."
            ),
        )

        text = response.text.strip()

        print(f"[OPENAI] Transcript: {text!r}")

        return text

    async def _translate(
    self,
    transcript: str,
    target_languages: list[str],
) -> dict:
        """
        Detect the transcript's original language from the enabled languages only,
        and translate it into every other enabled language.
        """
        language_list = json.dumps(target_languages, ensure_ascii=False)

        response = await openai_client.chat.completions.create(
            model=TRANSLATION_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a live voice-chat translator. "
                        f"The supplied transcript is in one of these languages: "
                        f"{language_list}. "
                        "Choose the language that best matches the transcript. "
                        "Translate the transcript accurately and naturally into each of the other "
                        f"languages in {language_list}. "
                        "Preserve names, tone, slang, questions, and meaning. "
                        "Do not censor or add commentary. "
                        "Do not include a translation for the language selected as the "
                        "original language because the original transcript will already "
                        "be displayed. "
                        "Return JSON only in this exact shape: "
                        '{"original_language":"BCP 47 tag",'
                        '"translations":{"BCP 47 tag":"Translated text"}}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Transcript:\n{transcript}\n\n"
                        f"Allowed languages:\n{language_list}"
                    ),
                },
            ],
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        returned_original = normalize_language_tag(
            str(data.get("original_language", ""))
        )

        original_language = next(
            (
                language
                for language in target_languages
                if language.casefold() == returned_original.casefold()
            ),
            target_languages[0],
        )

        raw_translations = data.get("translations", {})

        if not isinstance(raw_translations, dict):
            raw_translations = {}

        translations = {}

        for requested in target_languages:
            if requested.casefold() == original_language.casefold():
                continue

            for returned_language, translated_text in raw_translations.items():
                if returned_language.casefold() == requested.casefold():
                    translations[requested] = str(translated_text).strip()
                    break

        return {
            "original_language": original_language,
            "translations": translations,
        }

    async def _post_translation(
        self,
        member: discord.Member,
        transcript: str,
        original_language: str,
        translations: dict[str, str],
        target_languages: list[str],
    ) -> None:
        """
        VoiceChannel.send() posts directly into the text chat attached to that
        voice channel.
        """
        user_mention = member.mention

        sections = [
            f"### 🗣️ {user_mention}",
            f"**Original · `{original_language}`:** {transcript}",
        ]

        for language in target_languages:
            translated_text = translations.get(language)

            if translated_text:
                sections.append(
                    f"**`{language}`:** {translated_text}"
                )

        message = "\n".join(sections)

        for chunk in split_discord_message(message):
            await self.voice_channel.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def close(self) -> None:
        if self.closed:
            return

        self.closed = True

        if self.buffer_task:
            self.buffer_task.cancel()

        bridge = getattr(self.bot, "voice_bridge", None)

        if bridge is not None:
            await bridge.leave(self.voice_channel.guild.id)

        self.buffers.clear()


# ============================================================
# Node voice worker bridge
# ============================================================

class VoiceWorkerBridge:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.server: asyncio.AbstractServer | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.worker_process: asyncio.subprocess.Process | None = None
        self.connected = asyncio.Event()
        self.worker_ready = asyncio.Event()
        self.pending_joins: dict[int, asyncio.Future] = {}
        self.member_cache: dict[tuple[int, int], discord.Member] = {}
        self._read_task: asyncio.Task | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_connection,
            VOICE_WORKER_HOST,
            VOICE_WORKER_PORT,
        )

        worker_path = Path(__file__).resolve().with_name("voice-worker.mjs")

        if not worker_path.exists():
            raise RuntimeError(
                f"Voice worker not found: {worker_path}. "
                "Place voice-worker.mjs beside this Python file."
            )

        env = os.environ.copy()
        env["VOICE_WORKER_HOST"] = VOICE_WORKER_HOST
        env["VOICE_WORKER_PORT"] = str(VOICE_WORKER_PORT)

        try:
            self.worker_process = await asyncio.create_subprocess_exec(
                "node",
                str(worker_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "Node.js was not found. Install Node.js 22.12.0 or newer "
                "and make sure `node` is on PATH."
            ) from error

        self._stdout_task = asyncio.create_task(
            self._pipe_worker_output(self.worker_process.stdout, "NODE")
        )
        self._stderr_task = asyncio.create_task(
            self._pipe_worker_output(self.worker_process.stderr, "NODE ERROR")
        )

        try:
            await asyncio.wait_for(
                self.worker_ready.wait(),
                timeout=VOICE_WORKER_START_TIMEOUT,
            )
        except TimeoutError as error:
            raise RuntimeError(
                "The Node voice worker did not become ready in time. "
                "Check the Node worker output above."
            ) from error

        print("[VOICE BRIDGE] Node voice worker is ready.")

    async def stop(self) -> None:
        if self.writer is not None:
            try:
                await self.send({"type": "shutdown"})
            except Exception:
                pass

            self.writer.close()

            try:
                await self.writer.wait_closed()
            except Exception:
                pass

        if self.worker_process is not None and self.worker_process.returncode is None:
            try:
                await asyncio.wait_for(self.worker_process.wait(), timeout=3.0)
            except TimeoutError:
                self.worker_process.terminate()
                await self.worker_process.wait()

        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def join(self, guild_id: int, channel_id: int) -> None:
        if not self.worker_ready.is_set() or self.writer is None:
            raise RuntimeError("The voice worker is not connected.")

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_joins[guild_id] = future

        await self.send({
            "type": "join",
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
        })

        try:
            await asyncio.wait_for(future, timeout=VOICE_WORKER_JOIN_TIMEOUT)
        finally:
            self.pending_joins.pop(guild_id, None)

    async def leave(self, guild_id: int) -> None:
        if self.writer is None:
            return

        await self.send({
            "type": "leave",
            "guild_id": str(guild_id),
        })

    async def send(self, payload: dict) -> None:
        if self.writer is None:
            raise RuntimeError("The voice worker is not connected.")

        self.writer.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        )
        await self.writer.drain()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if self.writer is not None:
            writer.close()
            await writer.wait_closed()
            return

        self.reader = reader
        self.writer = writer
        self.connected.set()
        print("[VOICE BRIDGE] Node worker connected to Python.")

        try:
            while True:
                line = await reader.readline()

                if not line:
                    break

                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    print(f"[VOICE BRIDGE] Invalid worker message: {error}")
                    continue

                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[VOICE BRIDGE] Worker connection error: {error!r}")
        finally:
            if self.writer is writer:
                self.reader = None
                self.writer = None
                self.connected.clear()
                self.worker_ready.clear()

            for future in self.pending_joins.values():
                if not future.done():
                    future.set_exception(
                        RuntimeError("The voice worker disconnected.")
                    )

            print("[VOICE BRIDGE] Node worker disconnected.")

    async def _handle_message(self, message: dict) -> None:
        message_type = message.get("type")

        if message_type == "ready":
            self.worker_ready.set()
            return

        if message_type == "log":
            print(f"[VOICE WORKER] {message.get('message', '')}")
            return

        if message_type == "joined":
            guild_id = int(message["guild_id"])
            future = self.pending_joins.get(guild_id)

            if future is not None and not future.done():
                future.set_result(True)

            print(
                f"[VOICE] Worker joined channel {message.get('channel_id')} "
                f"in guild {guild_id}."
            )
            return

        if message_type == "join_error":
            guild_id = int(message["guild_id"])
            future = self.pending_joins.get(guild_id)
            error = RuntimeError(message.get("message", "Voice join failed."))

            if future is not None and not future.done():
                future.set_exception(error)
            else:
                print(f"[VOICE] Join error for guild {guild_id}: {error}")

            return

        if message_type == "audio":
            await self._handle_audio(message)
            return

        if message_type == "voice_error":
            print(
                f"[VOICE WORKER ERROR] Guild {message.get('guild_id')}: "
                f"{message.get('message', 'Unknown voice error')}"
            )
            return

    async def _handle_audio(self, message: dict) -> None:
        guild_id = int(message["guild_id"])
        user_id = int(message["user_id"])
        session = sessions.get(guild_id)

        if session is None or session.closed:
            return

        member_key = (guild_id, user_id)
        member = self.member_cache.get(member_key)

        if member is None:
            guild = self.bot.get_guild(guild_id)

            if guild is None:
                return

            member = guild.get_member(user_id)

            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.HTTPException:
                    return

            self.member_cache[member_key] = member
            print(
                f"[VOICE] First PCM packet received from "
                f"{member} ({member.id}) via Node worker."
            )

        try:
            pcm = base64.b64decode(message["pcm"], validate=True)
        except (ValueError, TypeError):
            return

        session.receive_pcm(member, pcm)

    async def _pipe_worker_output(
        self,
        stream: asyncio.StreamReader | None,
        label: str,
    ) -> None:
        if stream is None:
            return

        while True:
            line = await stream.readline()

            if not line:
                break

            print(f"[{label}] {line.decode('utf-8', errors='replace').rstrip()}")


# ============================================================
# Discord bot
# ============================================================

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True


class TranslationBot(commands.Bot):
    voice_bridge: VoiceWorkerBridge

    async def setup_hook(self) -> None:
        self.voice_bridge = VoiceWorkerBridge(self)
        await self.voice_bridge.start()

        await self.add_cog(TranslationCommands(self))

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def close(self) -> None:
        if hasattr(self, "voice_bridge"):
            await self.voice_bridge.stop()

        await super().close()


bot = TranslationBot(
    command_prefix=commands.when_mentioned,
    intents=intents,
)

sessions: dict[int, TranslationSession] = {}


async def get_session(
    interaction: discord.Interaction,
) -> TranslationSession | None:
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )
        return None

    session = sessions.get(interaction.guild_id)

    if session is None or session.closed:
        await interaction.response.send_message(
            "I'm not currently translating a voice channel in this server.",
            ephemeral=True,
        )
        return None

    return session


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("------")


class TranslationCommands(commands.Cog):
    def __init__(self, bot_instance: commands.Bot):
        self.bot = bot_instance

    @app_commands.command(
        name="join",
        description="Join your voice channel and start translating.",
    )
    @app_commands.describe(
        languages="Comma-separated language tags, e.g. en, ja, es, pt-BR"
    )
    async def join(
        self,
        interaction: discord.Interaction,
        languages: str,
    ) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "I couldn't determine your voice channel.",
                ephemeral=True,
            )
            return

        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message(
                "You need to be in a voice channel first.",
                ephemeral=True,
            )
            return

        voice_channel = member.voice.channel

        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "Please use this from a normal voice channel.",
                ephemeral=True,
            )
            return

        requested_languages = parse_languages(languages)

        if not requested_languages:
            await interaction.response.send_message(
                "Please provide at least one language tag, separated by commas.",
                ephemeral=True,
            )
            return

        existing = sessions.get(interaction.guild_id)

        if existing is not None and not existing.closed:
            await interaction.response.send_message(
                (
                    f"I'm already translating **{existing.voice_channel.name}**. "
                    "Use `/add`, `/remove`, `/active`, `/languages`, or `/leave`."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            session = TranslationSession(
                bot=self.bot,
                voice_channel=voice_channel,
                languages=requested_languages,
            )
            sessions[interaction.guild_id] = session

            try:
                await self.bot.voice_bridge.join(
                    interaction.guild_id,
                    voice_channel.id,
                )
            except Exception:
                sessions.pop(interaction.guild_id, None)
                session.closed = True

                if session.buffer_task:
                    session.buffer_task.cancel()

                raise

            print(
                f"[VOICE] Translation session active in {voice_channel.name} "
                f"({voice_channel.id})."
            )

            languages_text = ", ".join(requested_languages)

            await interaction.followup.send(
                (
                    f"Joined **{voice_channel.name}**.\n"
                    f"Translating into: **{languages_text}**\n"
                    "Transcriptions and translations will be posted in this "
                    "voice channel's side chat."
                ),
                ephemeral=False,
            )

        except Exception as error:
            print(f"Could not join voice: {error!r}")

            await interaction.followup.send(
                f"I couldn't join that voice channel: `{error}`",
                ephemeral=True,
            )

    @app_commands.command(
        name="add",
        description="Add translation language tags to the active voice session.",
    )
    @app_commands.describe(
        languages="Comma-separated language tags to add, e.g. fr, ko, zh-TW"
    )
    async def add(
        self,
        interaction: discord.Interaction,
        languages: str,
    ) -> None:
        session = await get_session(interaction)

        if session is None:
            return

        requested = parse_languages(languages)

        if not requested:
            await interaction.response.send_message(
                "Please provide at least one language tag.",
                ephemeral=True,
            )
            return

        added = session.add_languages(requested)

        if not added:
            await interaction.response.send_message(
                "Those languages are already enabled.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Added: **{', '.join(added)}**",
            ephemeral=False,
        )

    @app_commands.command(
        name="remove",
        description="Remove translation language tags from the active voice session.",
    )
    @app_commands.describe(
        languages="Comma-separated language tags to remove"
    )
    async def remove(
        self,
        interaction: discord.Interaction,
        languages: str,
    ) -> None:
        session = await get_session(interaction)

        if session is None:
            return

        requested = parse_languages(languages)

        if not requested:
            await interaction.response.send_message(
                "Please provide at least one language tag.",
                ephemeral=True,
            )
            return

        removed = session.remove_languages(requested)

        if not removed:
            await interaction.response.send_message(
                "None of those languages are currently enabled.",
                ephemeral=True,
            )
            return

        if session.languages:
            remaining = ", ".join(session.languages)
            extra = f"\nStill enabled: **{remaining}**"
        else:
            extra = "\nNo translation languages are currently enabled."

        await interaction.response.send_message(
            f"Removed: **{', '.join(removed)}**{extra}",
            ephemeral=False,
        )

    @app_commands.command(
        name="active",
        description="Show the currently enabled translation language tags.",
    )
    async def active(
        self,
        interaction: discord.Interaction,
    ) -> None:
        session = await get_session(interaction)

        if session is None:
            return

        if not session.languages:
            text = "No translation languages are currently enabled."
        else:
            text = (
                f"Currently translating into: "
                f"**{', '.join(session.languages)}**"
            )

        await interaction.response.send_message(
            text,
            ephemeral=True,
        )

    @app_commands.command(
        name="languages",
        description="List language tags you can use with the translation commands.",
    )
    async def languages(
        self,
        interaction: discord.Interaction,
    ) -> None:
        lines = [
            "**Common language tags**",
            "These are common language tags you can use with `/join`, `/add`, and `/remove`.",
            "Voicely Translate is not limited to this list—you can enter other valid BCP 47 language tags as well.",
            "",
        ]

        for tag, name in LANGUAGE_TAGS.items():
            lines.append(f"`{tag}` — {name}")

        lines.extend([
            "",
            "**Common regional/script tags**",
        ])

        for tag, name in REGIONAL_LANGUAGE_TAGS.items():
            lines.append(f"`{tag}` — {name}")

        lines.extend([
            "",
            "If a language is not listed above, you can still try its BCP 47 language tag.",
        ])

        chunks = split_discord_message("\n".join(lines))

        await interaction.response.send_message(
            chunks[0],
            ephemeral=True,
        )

        for chunk in chunks[1:]:
            await interaction.followup.send(
                chunk,
                ephemeral=True,
            )

    @app_commands.command(
        name="leave",
        description="Stop translating and leave the voice channel.",
    )
    async def leave(
        self,
        interaction: discord.Interaction,
    ) -> None:
        session = await get_session(interaction)

        if session is None:
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id

        await session.close()

        if guild_id is not None:
            sessions.pop(guild_id, None)

        await interaction.followup.send(
            "Stopped translating and left the voice channel.",
            ephemeral=True,
        )


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    """
    If Discord disconnects the bot from voice externally, clean up the
    corresponding translation session.
    """
    if bot.user is None or member.id != bot.user.id:
        return

    if before.channel is not None and after.channel is None:
        session = sessions.pop(member.guild.id, None)

        if session is not None and not session.closed:
            session.closed = True

            if session.buffer_task:
                session.buffer_task.cancel()


async def main() -> None:
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
