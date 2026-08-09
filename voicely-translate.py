import asyncio
import io
import json
import os
import time
import wave
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands, voice_recv
from openai import AsyncOpenAI
from dotenv import load_dotenv


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

# How frequently the bot checks whether an utterance has ended.
BUFFER_CHECK_INTERVAL = 0.10


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
        voice_client: voice_recv.VoiceRecvClient,
        languages: list[str],
    ):
        self.bot = bot
        self.voice_channel = voice_channel
        self.voice_client = voice_client
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

                        if pcm_duration_seconds(pcm) >= MIN_UTTERANCE_SECONDS:
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
                transcript = await self._transcribe(pcm)

                if not transcript:
                    return

                # Take a snapshot so /add or /remove can safely change the
                # live session while this particular utterance is translating.
                target_languages = self.languages.copy()

                if not target_languages:
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

    async def _transcribe(self, pcm: bytes) -> str:
        wav_bytes = make_wav_bytes(pcm)

        response = await openai_client.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=("speech.wav", wav_bytes, "audio/wav"),
        )

        text = response.text.strip()

        return text

    async def _translate(
        self,
        transcript: str,
        target_languages: list[str],
    ) -> dict:
        """
        Detect the transcript's original language and translate it into every
        requested language in a single model request.
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
                        "Determine the language of the supplied transcript and "
                        "identify it using the most appropriate BCP 47 language tag, "
                        "such as en, ja, es, pt-BR, or zh-Hant-TW. "
                        "Translate the transcript accurately and naturally into each "
                        "requested BCP 47 target language tag. Preserve names, tone, "
                        "slang, questions, and meaning. Do not censor or add commentary. "
                        "Do not replace requested tags with language names. "
                        "If a requested target tag represents the same language/locale "
                        "as the original speech, omit it from translations because "
                        "the original transcript will already be displayed. "
                        "Return JSON only in this exact shape: "
                        '{"original_language":"BCP 47 tag",'
                        '"translations":{"Requested BCP 47 tag":"Translated text"}}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Transcript:\n{transcript}\n\n"
                        f"Requested languages:\n{language_list}"
                    ),
                },
            ],
        )

        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)

        original_language = normalize_language_tag(
            str(data.get("original_language", "und"))
        ) or "und"

        raw_translations = data.get("translations", {})

        if not isinstance(raw_translations, dict):
            raw_translations = {}

        translations = {}

        # Only accept languages the session actually requested.
        for requested in target_languages:
            for returned_language, translated_text in raw_translations.items():
                if returned_language.casefold() == requested.casefold():
                    translations[requested] = str(translated_text).strip()
                    break

        return {
            "original_language": original_language or "Unknown",
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
        display_name = member.display_name

        sections = [
            f"🗣️ **{display_name}**",
            f"**Original · {original_language}**\n{transcript}",
        ]

        for language in target_languages:
            translated_text = translations.get(language)

            if translated_text:
                sections.append(
                    f"**{language}**\n{translated_text}"
                )

        message = "\n\n".join(sections)

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

        if self.voice_client.is_listening():
            self.voice_client.stop_listening()

        if self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)

        self.buffers.clear()


# ============================================================
# Voice sink
# ============================================================

class TranslationSink(voice_recv.AudioSink):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        session: TranslationSession,
    ):
        super().__init__()
        self.loop = loop
        self.session = session

    def wants_opus(self) -> bool:
        # False means discord-ext-voice-recv decodes Opus and gives us PCM.
        return False

    def write(
        self,
        user: discord.Member | discord.User | None,
        data: voice_recv.VoiceData,
    ) -> None:
        if user is None or not isinstance(user, discord.Member):
            return

        pcm = data.pcm

        if not pcm:
            return

        # AudioSink.write() is called from the receiver thread, so pass the
        # PCM safely back to Discord.py's asyncio event loop.
        self.loop.call_soon_threadsafe(
            self.session.receive_pcm,
            user,
            pcm,
        )

    def cleanup(self) -> None:
        pass


# ============================================================
# Discord bot
# ============================================================

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True


class TranslationBot(commands.Bot):
    async def setup_hook(self) -> None:
        await self.add_cog(TranslationCommands(self))

        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


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
                    "Use `/add`, `/remove`, `/languages`, or `/leave`."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            voice_client = await voice_channel.connect(
                cls=voice_recv.VoiceRecvClient
            )

            session = TranslationSession(
                bot=self.bot,
                voice_channel=voice_channel,
                voice_client=voice_client,
                languages=requested_languages,
            )

            sink = TranslationSink(
                loop=asyncio.get_running_loop(),
                session=session,
            )

            voice_client.listen(sink)
            sessions[interaction.guild_id] = session

            languages_text = ", ".join(requested_languages)

            await interaction.followup.send(
                (
                    f"Joined **{voice_channel.name}**.\n"
                    f"Translating into: **{languages_text}**\n"
                    "Transcriptions and translations will be posted in this "
                    "voice channel's side chat."
                ),
                ephemeral=True,
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
            ephemeral=True,
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
            ephemeral=True,
        )

    @app_commands.command(
        name="languages",
        description="Show the currently enabled translation language tags.",
    )
    async def languages(
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
