import asyncio
import base64
import io
import json
import logging
import os
import secrets
import sqlite3
import string
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from array import array
from decimal import Decimal
from pathlib import Path
from dataclasses import dataclass, field
from contextlib import closing

import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv
import webrtcvad

from voicely_audio import SpeechDetector
from voicely_billing import token_cost_microusd
from voicely_localization import BALANCE_LABELS, USAGE_LABELS
from voicely_languages import validate_translation_response
from voicely_runtime import BackgroundTasks, configure_logging
from voicely_storage import (
    apply_payment_event as storage_apply_payment_event,
    get_or_create_topup_code as storage_get_or_create_topup_code,
    record_api_usage as storage_record_api_usage,
)


configure_logging()
logger = logging.getLogger("voicely")


# ============================================================
# Configuration
# ============================================================

load_dotenv()
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GUILD_ID = int(os.environ["GUILD_ID"])

TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
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

# Voice worker recovery behavior.
VOICE_WORKER_RECOVERY_TIMEOUT = 15.0
VOICE_WORKER_RESTART_DELAY = 1.0

# Per-server idle voice timeout.
# Values are stored in seconds. Default: 30 seconds.
DEFAULT_IDLE_TIMEOUT_SECONDS = 30

# Shared local database for per-server settings, trial credit, paid credit,
# purchases, and API usage.
DATABASE_FILE = Path(__file__).resolve().with_name("voicely-translate.db")

# 100 Voicely Credits = $1.00 USD.
MICRO_USD_PER_CREDIT = 10_000
DEFAULT_TRIAL_CREDITS = 50
DEFAULT_TRIAL_MICRO_USD = DEFAULT_TRIAL_CREDITS * MICRO_USD_PER_CREDIT

UNLIMITED_CREDIT_GUILD_IDS = {
    1102582171207741480,
}

# Current OpenAI list prices used for usage accounting.
# Costs are stored as integer micro-dollars to avoid floating-point drift.
TRANSCRIPTION_INPUT_USD_PER_MILLION = Decimal("1.25")
TRANSCRIPTION_OUTPUT_USD_PER_MILLION = Decimal("5.00")
TRANSLATION_INPUT_USD_PER_MILLION = Decimal("0.15")
TRANSLATION_OUTPUT_USD_PER_MILLION = Decimal("0.60")

# Optional multiplier for operating/payment-processing overhead.
# 1.0 means users are charged only the calculated API token cost.
USAGE_COST_MULTIPLIER = Decimal("1.5")

# Protect the event loop from malformed or runaway worker payloads.
MAX_WORKER_MESSAGE_BYTES = 2_000_000
MAX_PCM_PACKET_BYTES = 1_500_000
MAX_CONCURRENT_API_REQUESTS_PER_SESSION = 3
MEMBER_CACHE_TTL_SECONDS = 3600.0

# Ko-fi / Cloudflare Worker integration.
KOFI_URL = os.environ.get("KOFI_URL", "").strip()
KOFI_WORKER_URL = os.environ.get("KOFI_WORKER_URL", "").rstrip("/")
KOFI_BOT_API_SECRET = os.environ.get("KOFI_BOT_API_SECRET", "")


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

speech_detector = SpeechDetector(
    sample_rate=PCM_SAMPLE_RATE,
    sample_width=PCM_SAMPLE_WIDTH,
    frame_ms=VAD_FRAME_MS,
    aggressiveness=VAD_AGGRESSIVENESS,
    minimum_ratio=VAD_MIN_SPEECH_RATIO,
    minimum_consecutive=VAD_MIN_CONSECUTIVE_SPEECH_FRAMES,
)


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
    return speech_detector.contains_speech(pcm)


def initialize_database() -> None:
    """
    Create and migrate the shared per-server database.

    The same guild_settings row stores voice timeout configuration and the
    server's local credit/accounting state.
    """
    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                idle_timeout_seconds INTEGER
            )
            """
        )

        existing_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(guild_settings)"
            ).fetchall()
        }

        migrations = {
            "topup_code": "TEXT",
            "trial_balance_microusd": (
                f"INTEGER NOT NULL DEFAULT {DEFAULT_TRIAL_MICRO_USD}"
            ),
            "paid_balance_microusd": "INTEGER NOT NULL DEFAULT 0",
            "total_purchased_microusd": "INTEGER NOT NULL DEFAULT 0",
            "total_used_microusd": "INTEGER NOT NULL DEFAULT 0",
            "transcription_used_microusd": "INTEGER NOT NULL DEFAULT 0",
            "translation_used_microusd": "INTEGER NOT NULL DEFAULT 0",
            "default_languages": "TEXT",
            "trial_notice_shown": "INTEGER NOT NULL DEFAULT 0",
        }

        for column_name, definition in migrations.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE guild_settings "
                    f"ADD COLUMN {column_name} {definition}"
                )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_guild_settings_topup_code
            ON guild_settings(topup_code)
            WHERE topup_code IS NOT NULL
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_events (
                message_id TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                amount_microusd INTEGER NOT NULL,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.commit()


def ensure_guild_account(guild_id: int) -> None:
    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO guild_settings (
                guild_id,
                idle_timeout_seconds
            )
            VALUES (?, ?)
            """,
            (guild_id, DEFAULT_IDLE_TIMEOUT_SECONDS),
        )
        connection.commit()

def get_idle_timeout_seconds(guild_id: int) -> int:
    ensure_guild_account(guild_id)

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        row = connection.execute(
            """
            SELECT idle_timeout_seconds
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

    if row is None or row[0] is None:
        return DEFAULT_IDLE_TIMEOUT_SECONDS

    return int(row[0])


def set_idle_timeout_seconds(
    guild_id: int,
    timeout_seconds: int,
) -> None:
    ensure_guild_account(guild_id)

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        connection.execute(
            """
            UPDATE guild_settings
            SET idle_timeout_seconds = ?
            WHERE guild_id = ?
            """,
            (int(timeout_seconds), guild_id),
        )
        connection.commit()

def get_default_languages(guild_id: int) -> list[str]:
    ensure_guild_account(guild_id)

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        row = connection.execute(
            """
            SELECT default_languages
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

    if row is None or not row[0]:
        return []

    try:
        stored_languages = json.loads(str(row[0]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(stored_languages, list):
        return []

    languages = []

    for value in stored_languages:
        language = normalize_language_tag(str(value))

        if (
            language
            and not any(
                existing.casefold() == language.casefold()
                for existing in languages
            )
        ):
            languages.append(language)

    return languages


def set_default_languages(
    guild_id: int,
    languages: list[str],
) -> None:
    ensure_guild_account(guild_id)

    normalized_languages = []

    for value in languages:
        language = normalize_language_tag(value)

        if (
            language
            and not any(
                existing.casefold() == language.casefold()
                for existing in normalized_languages
            )
        ):
            normalized_languages.append(language)

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        connection.execute(
            """
            UPDATE guild_settings
            SET default_languages = ?
            WHERE guild_id = ?
            """,
            (
                json.dumps(normalized_languages, ensure_ascii=False),
                guild_id,
            ),
        )
        connection.commit()


def _generate_topup_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"VT-{suffix}"


def get_or_create_topup_code(guild_id: int) -> str:
    ensure_guild_account(guild_id)
    return storage_get_or_create_topup_code(
        DATABASE_FILE, guild_id, _generate_topup_code
    )


def get_credit_state(guild_id: int) -> dict[str, int | str | None]:
    ensure_guild_account(guild_id)

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        row = connection.execute(
            """
            SELECT
                topup_code,
                trial_balance_microusd,
                paid_balance_microusd,
                total_purchased_microusd,
                total_used_microusd,
                transcription_used_microusd,
                translation_used_microusd
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Could not load guild credit state.")

    return {
        "topup_code": row[0],
        "trial_balance_microusd": int(row[1]),
        "paid_balance_microusd": int(row[2]),
        "total_purchased_microusd": int(row[3]),
        "total_used_microusd": int(row[4]),
        "transcription_used_microusd": int(row[5]),
        "translation_used_microusd": int(row[6]),
    }


def get_available_credit_microusd(guild_id: int) -> int:
    state = get_credit_state(guild_id)
    return max(
        0,
        int(state["trial_balance_microusd"])
        + int(state["paid_balance_microusd"]),
    )


def has_ever_purchased_credit(guild_id: int) -> bool:
    state = get_credit_state(guild_id)
    return int(state["total_purchased_microusd"]) > 0


def should_show_trial_notice(guild_id: int) -> bool:
    if guild_id in UNLIMITED_CREDIT_GUILD_IDS:
        return False

    state = get_credit_state(guild_id)

    if int(state["total_purchased_microusd"]) > 0:
        return False

    if int(state["trial_balance_microusd"]) <= 0:
        return False

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        row = connection.execute(
            """
            SELECT trial_notice_shown
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

    return row is not None and int(row[0] or 0) == 0


def mark_trial_notice_shown(guild_id: int) -> None:
    ensure_guild_account(guild_id)

    with closing(sqlite3.connect(DATABASE_FILE)) as connection:
        connection.execute(
            """
            UPDATE guild_settings
            SET trial_notice_shown = 1
            WHERE guild_id = ?
            """,
            (guild_id,),
        )
        connection.commit()


def has_available_credit(guild_id: int) -> bool:
    if guild_id in UNLIMITED_CREDIT_GUILD_IDS:
        return True

    return get_available_credit_microusd(guild_id) > 0


def format_credits(micro_usd: int) -> str:
    credits = max(0, micro_usd) / MICRO_USD_PER_CREDIT
    return f"{credits:,.2f}"


def calculate_token_cost_microusd(
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: Decimal,
    output_usd_per_million: Decimal,
) -> int:
    return token_cost_microusd(
        input_tokens,
        output_tokens,
        input_usd_per_million,
        output_usd_per_million,
        USAGE_COST_MULTIPLIER,
    )


def record_api_usage(
    guild_id: int,
    transcription_microusd: int = 0,
    translation_microusd: int = 0,
) -> None:
    ensure_guild_account(guild_id)
    storage_record_api_usage(
        DATABASE_FILE,
        guild_id,
        transcription_microusd,
        translation_microusd,
        guild_id in UNLIMITED_CREDIT_GUILD_IDS,
    )


def apply_payment_event(
    guild_id: int,
    message_id: str,
    amount_microusd: int,
) -> bool:
    """
    Apply one Ko-fi payment exactly once.

    Returns True when the payment was newly applied and False when this
    message_id had already been recorded locally.
    """
    ensure_guild_account(guild_id)

    return storage_apply_payment_event(
        DATABASE_FILE, guild_id, message_id, amount_microusd
    )


def _worker_request_sync(
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    if not KOFI_WORKER_URL or not KOFI_BOT_API_SECRET:
        raise RuntimeError(
            "Ko-fi Worker integration is not configured."
        )

    url = f"{KOFI_WORKER_URL}{path}"
    body = None

    headers = {
        "Authorization": f"Bearer {KOFI_BOT_API_SECRET}",
        "Accept": "application/json",
        "User-Agent": "Voicely-Translate/1.0",
    }

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ko-fi Worker returned HTTP {error.code}: {detail}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not reach the Ko-fi Worker: {error.reason}"
        ) from error

    if not response_body:
        return {}

    data = json.loads(response_body)

    if not isinstance(data, dict):
        raise RuntimeError("Ko-fi Worker returned an invalid response.")

    return data


async def worker_request(
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    return await asyncio.to_thread(
        _worker_request_sync,
        method,
        path,
        payload,
    )


async def register_topup_code(guild_id: int, code: str) -> None:
    await worker_request(
        "POST",
        "/register",
        {
            "guild_id": str(guild_id),
            "topup_code": code,
        },
    )


async def sync_kofi_topups(guild_id: int) -> int:
    """
    Pull unclaimed Ko-fi payments for this server from Cloudflare.

    The local payment_events table makes this idempotent even if claiming the
    event on Cloudflare fails after the local balance has already been updated.
    """
    if not KOFI_WORKER_URL or not KOFI_BOT_API_SECRET:
        return 0

    code = await asyncio.to_thread(get_or_create_topup_code, guild_id)

    await register_topup_code(guild_id, code)

    data = await worker_request(
        "GET",
        f"/pending?guild_id={urllib.parse.quote(str(guild_id))}",
    )

    raw_topups = data.get("topups", [])

    if not isinstance(raw_topups, list):
        return 0

    applied_count = 0
    claim_ids: list[str] = []

    for topup in raw_topups:
        if not isinstance(topup, dict):
            continue

        message_id = str(topup.get("message_id", "")).strip()

        try:
            amount_microusd = int(topup.get("amount_microusd", 0))
        except (TypeError, ValueError):
            continue

        if not message_id or amount_microusd <= 0:
            continue

        if await asyncio.to_thread(
            apply_payment_event,
            guild_id,
            message_id,
            amount_microusd,
        ):
            applied_count += 1

        claim_ids.append(message_id)

    if claim_ids:
        try:
            await worker_request(
                "POST",
                "/claim",
                {
                    "guild_id": str(guild_id),
                    "message_ids": claim_ids,
                },
            )
        except Exception as error:
            logger.exception(
                f"[KOFI] Payment(s) applied locally but could not be "
                f"marked claimed remotely: {error!r}"
            )

    if applied_count:
        logger.info(
            f"[KOFI] Applied {applied_count} new top-up payment(s) "
            f"for guild {guild_id}."
        )

    return applied_count


async def sync_kofi_topups_safely(guild_id: int, context: str) -> int:
    """Sync payments consistently for commands where failure is non-fatal."""
    try:
        return await sync_kofi_topups(guild_id)
    except Exception:
        logger.exception(
            "Ko-fi synchronization failed context=%s guild=%s",
            context,
            guild_id,
        )
        return 0


def count_human_members(channel: discord.VoiceChannel) -> int:
    return sum(1 for member in channel.members if not member.bot)


initialize_database()


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
        self.api_semaphore = asyncio.Semaphore(
            MAX_CONCURRENT_API_REQUESTS_PER_SESSION
        )
        self.billing_lock = asyncio.Lock()
        self.processing_tasks = BackgroundTasks(logger)

        self.closed = False
        self.buffer_task = asyncio.create_task(self._buffer_loop())
        self.idle_timeout_task: asyncio.Task | None = None
        self.credit_exhausted_notified = False

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

    def cancel_idle_timeout(self) -> None:
        if self.idle_timeout_task is not None:
            self.idle_timeout_task.cancel()
            self.idle_timeout_task = None

    def update_idle_timeout(self) -> None:
        if self.closed:
            return

        if count_human_members(self.voice_channel) > 0:
            self.cancel_idle_timeout()
            return

        timeout_seconds = get_idle_timeout_seconds(
            self.voice_channel.guild.id
        )

        if (
            self.idle_timeout_task is None
            or self.idle_timeout_task.done()
        ):
            logger.info(
                f"[VOICE TIMEOUT] {self.voice_channel.guild.name} has no "
                f"human users in {self.voice_channel.name}; leaving in "
                f"{timeout_seconds} second(s)."
            )

            self.idle_timeout_task = asyncio.create_task(
                self._idle_timeout_loop(timeout_seconds)
            )

    async def _idle_timeout_loop(self, timeout_seconds: int) -> None:
        try:
            await asyncio.sleep(timeout_seconds)

            if self.closed:
                return

            if count_human_members(self.voice_channel) > 0:
                return

            guild_id = self.voice_channel.guild.id

            logger.info(
                f"[VOICE TIMEOUT] Idle timeout reached in "
                f"{self.voice_channel.name}; leaving voice."
            )

            await self.close()
            sessions.pop(guild_id, None)

        except asyncio.CancelledError:
            logger.info(
                f"[VOICE TIMEOUT] Idle timeout cancelled for "
                f"{self.voice_channel.guild.name}."
            )
        finally:
            if self.idle_timeout_task is asyncio.current_task():
                self.idle_timeout_task = None

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
                            logger.info(
                                f"[VOICE] Utterance ready from {member} "
                                f"({member.id}); duration={duration:.2f}s"
                            )
                            ready.append((user_id, member, pcm))

                # Do not await these here. Each completed utterance gets its own
                # task so different users can be transcribed simultaneously.
                for user_id, member, pcm in ready:
                    self.processing_tasks.create(
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

        # The billing lock makes the balance check, API calls, and deductions
        # one transaction from the guild's perspective. The semaphore remains
        # explicit so this can later be relaxed to reserved-credit accounting.
        async with lock, self.api_semaphore, self.billing_lock:
            if self.closed:
                return

            try:
                has_speech, speech_ratio, max_consecutive = contains_speech(pcm)

                if not has_speech:
                    logger.info(
                        f"[VAD] Ignoring non-speech audio from {member} ({member.id}); "
                        f"speech={speech_ratio:.0%}, "
                        f"max_consecutive={max_consecutive} frames"
                    )
                    return

                logger.info(
                    f"[VAD] Speech detected from {member} ({member.id}); "
                    f"speech={speech_ratio:.0%}, "
                    f"max_consecutive={max_consecutive} frames"
                )

                target_languages = self.languages.copy()

                if not target_languages:
                    return

                guild_id = self.voice_channel.guild.id

                if not await asyncio.to_thread(has_available_credit, guild_id):
                    logger.info(
                        f"[CREDITS] Ignoring speech in guild {guild_id}; "
                        "no trial or paid credit remains."
                    )
                    await self._handle_credit_exhausted()
                    return

                transcript, transcription_cost = await self._transcribe(
                    pcm,
                    target_languages,
                )

                # Always charge the transcription request as soon as OpenAI
                # returns its usage, even when the resulting transcript is empty
                # or [NONVERBAL]. The audio and output tokens were still billed.
                await asyncio.to_thread(
                    record_api_usage,
                    guild_id,
                    transcription_cost,
                )

                if guild_id not in UNLIMITED_CREDIT_GUILD_IDS:
                    remaining_credit = await asyncio.to_thread(
                        get_available_credit_microusd, guild_id
                    )
                    logger.info(
                        f"[CREDITS] Transcription charged "
                        f"{format_credits(transcription_cost)} credits; "
                        f"remaining={format_credits(remaining_credit)} credits."
                    )

                    # Do not start another paid API request after transcription
                    # has consumed the server's final credit.
                    if remaining_credit <= 0:
                        await self._handle_credit_exhausted()
                        return

                if not transcript:
                    return

                if transcript.strip().casefold() == "[nonverbal]":
                    logger.info(
                        f"[VOICE] Ignoring nonverbal vocalization from {member} ({member.id}). "
                        "Transcription usage was still charged."
                    )
                    return

                if len(target_languages) == 1:
                    result = {
                        "original_language": target_languages[0],
                        "translations": {},
                    }
                    translation_cost = 0
                else:
                    result, translation_cost = await self._translate(
                        transcript,
                        target_languages,
                    )

                await asyncio.to_thread(
                    record_api_usage,
                    guild_id,
                    0,
                    translation_cost,
                )

                if guild_id not in UNLIMITED_CREDIT_GUILD_IDS:
                    remaining_credit = await asyncio.to_thread(
                        get_available_credit_microusd, guild_id
                    )
                    logger.info(
                        f"[CREDITS] Translation charged "
                        f"{format_credits(translation_cost)} credits; "
                        f"remaining={format_credits(remaining_credit)} credits."
                    )

                if self.closed:
                    return

                await self._post_translation(
                    member=member,
                    transcript=transcript,
                    original_language=result["original_language"],
                    translations=result["translations"],
                    target_languages=target_languages,
                )

                if not await asyncio.to_thread(has_available_credit, guild_id):
                    await self._handle_credit_exhausted()

            except Exception as error:
                logger.exception(
                    f"Error processing speech from "
                    f"{member} ({member.id}): {error!r}"
                )

    async def _handle_credit_exhausted(self) -> None:
        if self.credit_exhausted_notified or self.closed:
            return

        self.credit_exhausted_notified = True
        guild_id = self.voice_channel.guild.id

        logger.info(
            f"[CREDITS] Guild {guild_id} has exhausted all trial and "
            "paid Voicely Translate credit."
        )

        try:
            guild_locale = getattr(self.voice_channel.guild, "preferred_locale", "en-US")
            message_key = (
                "credit_exhausted"
                if await asyncio.to_thread(has_ever_purchased_credit, guild_id)
                else "trial_exhausted"
            )

            await self.voice_channel.send(
                tr_locale(guild_locale, message_key),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as error:
            logger.exception(
                f"[CREDITS] Could not post exhausted-credit notice in "
                f"guild {guild_id}: {error!r}"
            )

        await self.close()
        sessions.pop(guild_id, None)

    async def _transcribe(
        self,
        pcm: bytes,
        languages: list[str],
    ) -> tuple[str, int]:
        wav_bytes = make_wav_bytes(pcm)

        logger.info(
            f"[OPENAI] Sending {pcm_duration_seconds(pcm):.2f}s "
            f"of audio for transcription..."
        )

        language_list = ", ".join(languages)

        response = await openai_client.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=("speech.wav", wav_bytes, "audio/wav"),
            prompt=(
                f"The speaker is speaking one of these languages: {language_list}. "
                "Transcribe exactly what is spoken, in the language actually spoken. "
                "Do not translate the speech. "
                "Preserve names and other proper nouns as spoken, such as usernames, personal names, "
                "character names, titles, places, organizations, and brands. "
                "Names may have unusual spellings, capitalization, numbers, abbreviations, or foreign-language words; "
                "do not translate, localize, normalize, or replace them with similar-sounding ordinary words. "
                "Preserve the speaker's actual words, fillers, hesitation sounds, repetitions, and incomplete phrases. "
                "Use the surrounding speech for context when deciding between similar-sounding words, "
                "and prefer the interpretation that forms a coherent, natural utterance when the audio is ambiguous, "
                "but do not invent words that are not clearly spoken. "
                "If the entire audio contains no spoken words and consists only of nonverbal sounds, "
                "such as laughter, grunting, sighing, humming, or hesitation sounds like hmm, uh, or um, "
                "including equivalent sounds in other languages, return exactly [NONVERBAL]. "
                "A hesitation sound by itself is [NONVERBAL], even if it could be interpreted as a word or expression. "
                "If a hesitation or filler occurs with actual speech, transcribe the entire utterance, including it."
            ),
        )

        text = response.text.strip()

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        cost_microusd = calculate_token_cost_microusd(
            input_tokens,
            output_tokens,
            TRANSCRIPTION_INPUT_USD_PER_MILLION,
            TRANSCRIPTION_OUTPUT_USD_PER_MILLION,
        )

        logger.info(
            f"[OPENAI] Transcript: {text!r} "
            f"(input={input_tokens}, output={output_tokens}, "
            f"cost=${cost_microusd / 1_000_000:.6f})"
        )

        return text, cost_microusd

    async def _translate(
    self,
    transcript: str,
    target_languages: list[str],
) -> tuple[dict, int]:
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

        parsed = validate_translation_response(data, target_languages)
        original_language = str(parsed["original_language"])
        translations = dict(parsed["translations"])

        usage = response.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        cost_microusd = calculate_token_cost_microusd(
            input_tokens,
            output_tokens,
            TRANSLATION_INPUT_USD_PER_MILLION,
            TRANSLATION_OUTPUT_USD_PER_MILLION,
        )

        logger.info(
            f"[OPENAI] Translation usage: input={input_tokens}, "
            f"output={output_tokens}, "
            f"cost=${cost_microusd / 1_000_000:.6f}"
        )

        return (
            {
                "original_language": original_language,
                "translations": translations,
            },
            cost_microusd,
        )

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
        guild_locale = getattr(self.voice_channel.guild, "preferred_locale", "en-US")
        original_label = tr_locale(guild_locale, "original_label")

        sections = [
            f"### 🗣️ {user_mention}",
            f"**{original_label} · `{original_language}`:** {transcript}",
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

        current_task = asyncio.current_task()

        if (
            self.idle_timeout_task is not None
            and self.idle_timeout_task is not current_task
        ):
            self.idle_timeout_task.cancel()

        self.idle_timeout_task = None

        if self.buffer_task:
            self.buffer_task.cancel()

        await self.processing_tasks.cancel_all()

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
        self.member_cache: dict[
            tuple[int, int], tuple[discord.Member, float]
        ] = {}

        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._worker_watch_task: asyncio.Task | None = None
        self._restart_lock = asyncio.Lock()
        self._stopping = False
        self._worker_path: Path | None = None

    async def start(self) -> None:
        self._stopping = False

        self.server = await asyncio.start_server(
            self._handle_connection,
            VOICE_WORKER_HOST,
            VOICE_WORKER_PORT,
        )

        self._worker_path = Path(__file__).resolve().with_name("voice-worker.mjs")

        if not self._worker_path.exists():
            raise RuntimeError(
                f"Voice worker not found: {self._worker_path}. "
                "Place voice-worker.mjs beside this Python file."
            )

        logger.info(
            f"[VOICE BRIDGE] Listening for Node worker on "
            f"{VOICE_WORKER_HOST}:{VOICE_WORKER_PORT}."
        )

        await self._start_worker_process(reason="initial startup")

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

        logger.info("[VOICE BRIDGE] Node voice worker is ready.")

    async def _start_worker_process(self, reason: str) -> None:
        if self._stopping:
            return

        async with self._restart_lock:
            if self._stopping:
                return

            if (
                self.worker_process is not None
                and self.worker_process.returncode is None
            ):
                return

            if self._worker_path is None:
                self._worker_path = Path(__file__).resolve().with_name(
                    "voice-worker.mjs"
                )

            env = os.environ.copy()
            env["VOICE_WORKER_HOST"] = VOICE_WORKER_HOST
            env["VOICE_WORKER_PORT"] = str(VOICE_WORKER_PORT)

            self.connected.clear()
            self.worker_ready.clear()

            logger.info(
                f"[VOICE BRIDGE] Starting Node voice worker "
                f"({reason})..."
            )

            try:
                process = await asyncio.create_subprocess_exec(
                    "node",
                    str(self._worker_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except FileNotFoundError as error:
                raise RuntimeError(
                    "Node.js was not found. Install Node.js 22.12.0 or newer "
                    "and make sure `node` is on PATH."
                ) from error

            self.worker_process = process

            logger.info(
                f"[VOICE BRIDGE] Node voice worker started with PID "
                f"{process.pid}."
            )

            self._stdout_task = asyncio.create_task(
                self._pipe_worker_output(process.stdout, "NODE")
            )
            self._stderr_task = asyncio.create_task(
                self._pipe_worker_output(process.stderr, "NODE ERROR")
            )
            self._worker_watch_task = asyncio.create_task(
                self._watch_worker_process(process)
            )

    async def _watch_worker_process(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        return_code = await process.wait()

        if self.worker_process is process:
            self.worker_process = None

        if self._stopping:
            logger.info(
                f"[VOICE BRIDGE] Node voice worker exited during shutdown "
                f"with code {return_code}."
            )
            return

        logger.info(
            f"[VOICE BRIDGE ERROR] Node voice worker exited unexpectedly "
            f"with code {return_code}."
        )

        self.connected.clear()
        self.worker_ready.clear()

        await asyncio.sleep(VOICE_WORKER_RESTART_DELAY)

        if self._stopping:
            return

        try:
            await self._start_worker_process(
                reason=f"automatic recovery after exit code {return_code}"
            )
        except Exception as error:
            logger.exception(
                f"[VOICE BRIDGE ERROR] Failed to restart Node voice worker: "
                f"{error!r}"
            )

    async def _ensure_worker_ready(self) -> None:
        if self._stopping:
            raise RuntimeError("The voice worker is shutting down.")

        if (
            self.worker_process is None
            or self.worker_process.returncode is not None
        ):
            logger.info(
                "[VOICE BRIDGE] Worker process is not running; "
                "starting recovery."
            )
            await self._start_worker_process(
                reason="recovery requested by voice operation"
            )

        if self.writer is not None and self.worker_ready.is_set():
            return

        logger.info(
            "[VOICE BRIDGE] Voice worker is not currently ready; "
            "waiting for recovery..."
        )

        try:
            await asyncio.wait_for(
                self.worker_ready.wait(),
                timeout=VOICE_WORKER_RECOVERY_TIMEOUT,
            )
        except TimeoutError as error:
            process_state = "not running"

            if self.worker_process is not None:
                if self.worker_process.returncode is None:
                    process_state = (
                        f"running (PID {self.worker_process.pid}) "
                        "but not connected"
                    )
                else:
                    process_state = (
                        f"exited with code {self.worker_process.returncode}"
                    )

            logger.info(
                f"[VOICE BRIDGE ERROR] Worker recovery timed out; "
                f"process state: {process_state}."
            )

            raise RuntimeError(
                "The voice worker could not recover in time."
            ) from error

        if self.writer is None:
            raise RuntimeError(
                "The voice worker reported ready but its bridge connection "
                "is unavailable."
            )

        logger.info("[VOICE BRIDGE] Voice worker recovery completed.")

    async def stop(self) -> None:
        if self._stopping:
            return

        self._stopping = True
        logger.info("[VOICE BRIDGE] Shutting down Node voice worker...")

        # Prevent pending join operations from hanging during shutdown.
        for future in self.pending_joins.values():
            if not future.done():
                future.set_exception(
                    RuntimeError("The voice worker is shutting down.")
                )

        if self.writer is not None:
            try:
                await self.send({"type": "shutdown"})
                logger.info("[VOICE BRIDGE] Sent shutdown command to Node worker.")
            except Exception as error:
                logger.exception(
                    f"[VOICE BRIDGE] Could not send worker shutdown command: "
                    f"{error!r}"
                )

        process = self.worker_process

        if process is not None and process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except TimeoutError:
                logger.info(
                    "[VOICE BRIDGE] Node worker did not exit after shutdown "
                    "command; terminating it."
                )
                process.terminate()

                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except TimeoutError:
                    logger.info(
                        "[VOICE BRIDGE] Node worker did not terminate; "
                        "killing it."
                    )
                    process.kill()
                    await process.wait()

        if self.writer is not None:
            writer = self.writer
            self.reader = None
            self.writer = None
            self.connected.clear()
            self.worker_ready.clear()

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

        # The watcher checks _stopping and therefore will not restart the worker.
        if (
            self._worker_watch_task is not None
            and not self._worker_watch_task.done()
            and self._worker_watch_task is not asyncio.current_task()
        ):
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._worker_watch_task),
                    timeout=1.0,
                )
            except (TimeoutError, asyncio.CancelledError):
                pass

        logger.info("[VOICE BRIDGE] Node voice worker shutdown complete.")

    async def join(self, guild_id: int, channel_id: int) -> None:
        logger.info(
            f"[VOICE BRIDGE] Join requested for guild {guild_id}, "
            f"channel {channel_id}."
        )

        await self._ensure_worker_ready()

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_joins[guild_id] = future

        try:
            await self.send({
                "type": "join",
                "guild_id": str(guild_id),
                "channel_id": str(channel_id),
            })

            logger.info(
                f"[VOICE BRIDGE] Join command sent for guild {guild_id}, "
                f"channel {channel_id}."
            )

            await asyncio.wait_for(
                future,
                timeout=VOICE_WORKER_JOIN_TIMEOUT,
            )

        except Exception as error:
            logger.exception(
                f"[VOICE BRIDGE ERROR] Join failed for guild {guild_id}, "
                f"channel {channel_id}: {error!r}"
            )
            raise
        finally:
            self.pending_joins.pop(guild_id, None)

    async def leave(self, guild_id: int) -> None:
        if self._stopping:
            return

        if self.writer is None or not self.worker_ready.is_set():
            logger.info(
                f"[VOICE BRIDGE] Leave requested for guild {guild_id}, "
                "but the worker is not connected; nothing to send."
            )
            return

        logger.info(f"[VOICE BRIDGE] Sending leave command for guild {guild_id}.")

        try:
            await self.send({
                "type": "leave",
                "guild_id": str(guild_id),
            })
        except Exception as error:
            logger.exception(
                f"[VOICE BRIDGE ERROR] Failed to send leave for guild "
                f"{guild_id}: {error!r}"
            )

    async def send(self, payload: dict) -> None:
        if self.writer is None:
            raise RuntimeError("The voice worker is not connected.")

        self.writer.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
        )
        await self.writer.drain()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")

        if self._stopping:
            logger.info(
                f"[VOICE BRIDGE] Rejecting worker connection from {peer} "
                "because shutdown is in progress."
            )
            writer.close()
            await writer.wait_closed()
            return

        if self.writer is not None:
            logger.info(
                f"[VOICE BRIDGE] Rejecting duplicate Node worker "
                f"connection from {peer}."
            )
            writer.close()
            await writer.wait_closed()
            return

        self.reader = reader
        self.writer = writer
        self.connected.set()

        logger.info(
            f"[VOICE BRIDGE] Node worker connected to Python"
            f"{f' from {peer}' if peer else ''}."
        )

        try:
            while True:
                try:
                    line = await reader.readuntil(b"\n")
                except asyncio.LimitOverrunError:
                    logger.warning("Dropping oversized voice-worker message")
                    break

                if not line:
                    logger.info(
                        "[VOICE BRIDGE] Node worker bridge socket reached EOF."
                    )
                    break

                if len(line) > MAX_WORKER_MESSAGE_BYTES:
                    logger.warning(
                        "Dropping voice-worker message larger than %d bytes",
                        MAX_WORKER_MESSAGE_BYTES,
                    )
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    logger.info(
                        f"[VOICE BRIDGE ERROR] Invalid worker message: {error}"
                    )
                    continue

                await self._handle_message(message)

        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception(
                f"[VOICE BRIDGE ERROR] Worker connection error: {error!r}"
            )
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

            if self._stopping:
                logger.info(
                    "[VOICE BRIDGE] Node worker disconnected during shutdown."
                )
            else:
                logger.info(
                    "[VOICE BRIDGE ERROR] Node worker disconnected from "
                    "Python unexpectedly."
                )

                # If the process is still alive, it may reconnect itself.
                # If not, the watcher will restart it. Either way, log the state.
                if (
                    self.worker_process is not None
                    and self.worker_process.returncode is None
                ):
                    logger.info(
                        f"[VOICE BRIDGE] Node worker process is still running "
                        f"(PID {self.worker_process.pid}); waiting for it to "
                        "reconnect."
                    )
                else:
                    logger.info(
                        "[VOICE BRIDGE] Node worker process is not running; "
                        "automatic restart will be attempted."
                    )

    async def _handle_message(self, message: dict) -> None:
        message_type = message.get("type")

        if message_type == "ready":
            was_ready = self.worker_ready.is_set()
            self.worker_ready.set()

            if was_ready:
                logger.info("[VOICE BRIDGE] Node worker reported ready again.")
            else:
                logger.info("[VOICE BRIDGE] Node worker reported ready.")

            return

        if message_type == "log":
            logger.info(f"[VOICE WORKER] {message.get('message', '')}")
            return

        if message_type == "joined":
            guild_id = int(message["guild_id"])
            future = self.pending_joins.get(guild_id)

            if future is not None and not future.done():
                future.set_result(True)

            logger.info(
                f"[VOICE] Worker joined channel {message.get('channel_id')} "
                f"in guild {guild_id}."
            )
            return

        if message_type == "left":
            logger.info(
                f"[VOICE] Worker left voice in guild "
                f"{message.get('guild_id')}."
            )
            return

        if message_type == "join_error":
            guild_id = int(message["guild_id"])
            future = self.pending_joins.get(guild_id)
            error = RuntimeError(
                message.get("message", "Voice join failed.")
            )

            logger.info(
                f"[VOICE WORKER ERROR] Join error for guild {guild_id}: "
                f"{error}"
            )

            if future is not None and not future.done():
                future.set_exception(error)

            return

        if message_type == "audio":
            await self._handle_audio(message)
            return

        if message_type == "voice_error":
            logger.info(
                f"[VOICE WORKER ERROR] Guild {message.get('guild_id')}: "
                f"{message.get('message', 'Unknown voice error')}"
            )
            return

        logger.info(
            f"[VOICE BRIDGE] Unknown worker message type: "
            f"{message_type!r}"
        )

    async def _handle_audio(self, message: dict) -> None:
        guild_id = int(message["guild_id"])
        user_id = int(message["user_id"])
        session = sessions.get(guild_id)

        if session is None or session.closed:
            return

        member_key = (guild_id, user_id)
        cached = self.member_cache.get(member_key)
        now = time.monotonic()
        member = None

        if cached is not None:
            cached_member, cached_at = cached
            if now - cached_at <= MEMBER_CACHE_TTL_SECONDS:
                member = cached_member
            else:
                self.member_cache.pop(member_key, None)

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

            self.member_cache[member_key] = (member, now)
            logger.info(
                f"[VOICE] First PCM packet received from "
                f"{member} ({member.id}) via Node worker."
            )

        try:
            pcm = base64.b64decode(message["pcm"], validate=True)
        except (ValueError, TypeError):
            return

        if len(pcm) > MAX_PCM_PACKET_BYTES:
            logger.warning(
                "Dropping oversized PCM packet for guild=%s user=%s bytes=%s",
                guild_id,
                user_id,
                len(pcm),
            )
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

            logger.info(
                f"[{label}] "
                f"{line.decode('utf-8', errors='replace').rstrip()}"
            )



# ============================================================
# User-facing localization
# ============================================================

# Discord selects interaction.locale from the user's client language. English is
# the fallback. Arabic is included for explicit/manual use, although Discord
# currently does not expose Arabic as an application-command localization locale.
UI_LANG_ALIASES = {
    "en": "en", "es": "es", "pt": "pt", "fr": "fr", "de": "de", "ja": "ja",
    "ko": "ko", "zh": "zh", "ru": "ru", "ar": "ar", "hi": "hi", "id": "id",
}

UI = {
    "server_only": {
        "en":"This command can only be used in a server.","es":"Este comando solo se puede usar en un servidor.","pt":"Este comando só pode ser usado em um servidor.","fr":"Cette commande ne peut être utilisée que dans un serveur.","de":"Dieser Befehl kann nur auf einem Server verwendet werden.","ja":"このコマンドはサーバー内でのみ使用できます。","ko":"이 명령어는 서버에서만 사용할 수 있습니다.","zh":"此命令只能在服务器中使用。","ru":"Эту команду можно использовать только на сервере.","ar":"لا يمكن استخدام هذا الأمر إلا داخل خادم.","hi":"इस कमांड का उपयोग केवल सर्वर में किया जा सकता है।","id":"Perintah ini hanya dapat digunakan di server."},
    "no_session": {
        "en":"I'm not currently translating a voice channel in this server.","es":"Actualmente no estoy traduciendo ningún canal de voz en este servidor.","pt":"No momento, não estou traduzindo nenhum canal de voz neste servidor.","fr":"Je ne traduis actuellement aucun salon vocal sur ce serveur.","de":"Ich übersetze derzeit keinen Sprachkanal auf diesem Server.","ja":"現在、このサーバーではボイスチャンネルを翻訳していません。","ko":"현재 이 서버에서 음성 채널을 번역하고 있지 않습니다.","zh":"我目前没有在此服务器中翻译任何语音频道。","ru":"Сейчас я не перевожу голосовой канал на этом сервере.","ar":"لا أقوم حاليًا بترجمة أي قناة صوتية في هذا الخادم.","hi":"मैं इस सर्वर में अभी किसी वॉइस चैनल का अनुवाद नहीं कर रहा हूँ।","id":"Saat ini saya tidak sedang menerjemahkan kanal suara di server ini."},
    "unknown_voice": {
        "en":"I couldn't determine your voice channel.","es":"No pude determinar tu canal de voz.","pt":"Não consegui determinar seu canal de voz.","fr":"Je n'ai pas pu déterminer votre salon vocal.","de":"Ich konnte deinen Sprachkanal nicht bestimmen.","ja":"あなたのボイスチャンネルを確認できませんでした。","ko":"사용자의 음성 채널을 확인할 수 없습니다.","zh":"无法确定你所在的语音频道。","ru":"Не удалось определить ваш голосовой канал.","ar":"تعذر تحديد قناتك الصوتية.","hi":"आपका वॉइस चैनल निर्धारित नहीं किया जा सका।","id":"Saya tidak dapat menentukan kanal suara Anda."},
    "need_voice": {
        "en":"You need to be in a voice channel first.","es":"Primero debes estar en un canal de voz.","pt":"Você precisa estar em um canal de voz primeiro.","fr":"Vous devez d'abord être dans un salon vocal.","de":"Du musst zuerst in einem Sprachkanal sein.","ja":"先にボイスチャンネルに参加してください。","ko":"먼저 음성 채널에 들어가 있어야 합니다.","zh":"你需要先加入一个语音频道。","ru":"Сначала нужно войти в голосовой канал.","ar":"يجب أن تكون في قناة صوتية أولًا.","hi":"आपको पहले किसी वॉइस चैनल में होना होगा।","id":"Anda harus berada di kanal suara terlebih dahulu."},
    "normal_voice": {
        "en":"Please use this from a normal voice channel.","es":"Usa este comando desde un canal de voz normal.","pt":"Use este comando em um canal de voz normal.","fr":"Veuillez utiliser cette commande depuis un salon vocal normal.","de":"Bitte verwende diesen Befehl in einem normalen Sprachkanal.","ja":"通常のボイスチャンネルから使用してください。","ko":"일반 음성 채널에서 사용해 주세요.","zh":"请在普通语音频道中使用此命令。","ru":"Используйте эту команду в обычном голосовом канале.","ar":"يرجى استخدام هذا الأمر من قناة صوتية عادية.","hi":"कृपया इसे सामान्य वॉइस चैनल से उपयोग करें।","id":"Gunakan perintah ini dari kanal suara biasa."},
    "no_credit": {
        "en":"This server has no Voicely Translate credit remaining.\nUse `/topup` to add more credit through Ko-fi.","es":"A este servidor no le quedan créditos de Voicely Translate.\nUsa `/topup` para añadir más créditos mediante Ko-fi.","pt":"Este servidor não tem mais créditos do Voicely Translate.\nUse `/topup` para adicionar créditos pelo Ko-fi.","fr":"Ce serveur n'a plus de crédits Voicely Translate.\nUtilisez `/topup` pour ajouter des crédits via Ko-fi.","de":"Dieser Server hat keine Voicely-Translate-Credits mehr.\nVerwende `/topup`, um über Ko-fi weitere Credits hinzuzufügen.","ja":"このサーバーにはVoicely Translateクレジットが残っていません。\n`/topup` でKo-fiからクレジットを追加できます。","ko":"이 서버에는 Voicely Translate 크레딧이 남아 있지 않습니다.\n`/topup`을 사용해 Ko-fi에서 크레딧을 추가하세요.","zh":"此服务器已没有剩余的 Voicely Translate 点数。\n使用 `/topup` 通过 Ko-fi 添加更多点数。","ru":"На этом сервере не осталось кредитов Voicely Translate.\nИспользуйте `/topup`, чтобы добавить кредиты через Ko-fi.","ar":"لم يتبقَّ لهذا الخادم أي رصيد Voicely Translate.\nاستخدم `/topup` لإضافة رصيد عبر Ko-fi.","hi":"इस सर्वर में कोई Voicely Translate क्रेडिट शेष नहीं है।\nKo-fi के माध्यम से और क्रेडिट जोड़ने के लिए `/topup` का उपयोग करें।","id":"Server ini tidak memiliki kredit Voicely Translate yang tersisa.\nGunakan `/topup` untuk menambah kredit melalui Ko-fi."},
    "provide_language": {
        "en":"Please provide at least one language tag, separated by commas.","es":"Indica al menos una etiqueta de idioma, separada por comas.","pt":"Informe pelo menos uma tag de idioma, separada por vírgulas.","fr":"Indiquez au moins une balise de langue, séparée par des virgules.","de":"Gib mindestens ein Sprach-Tag an, durch Kommas getrennt.","ja":"カンマ区切りで少なくとも1つの言語タグを指定してください。","ko":"쉼표로 구분하여 언어 태그를 하나 이상 입력해 주세요.","zh":"请提供至少一个语言标签，并用逗号分隔。","ru":"Укажите хотя бы один языковой тег, разделяя их запятыми.","ar":"يرجى إدخال وسم لغة واحد على الأقل، مع الفصل بفواصل.","hi":"कम-से-कम एक भाषा टैग दें और कई टैग को कॉमा से अलग करें।","id":"Berikan setidaknya satu tag bahasa, dipisahkan dengan koma."},
    "already_enabled": {
        "en":"Those languages are already enabled.","es":"Esos idiomas ya están habilitados.","pt":"Esses idiomas já estão ativados.","fr":"Ces langues sont déjà activées.","de":"Diese Sprachen sind bereits aktiviert.","ja":"これらの言語はすでに有効です。","ko":"해당 언어는 이미 활성화되어 있습니다.","zh":"这些语言已启用。","ru":"Эти языки уже включены.","ar":"هذه اللغات مفعّلة بالفعل.","hi":"ये भाषाएँ पहले से सक्षम हैं।","id":"Bahasa tersebut sudah diaktifkan."},
    "none_requested_enabled": {
        "en":"None of those languages are currently enabled.","es":"Ninguno de esos idiomas está habilitado actualmente.","pt":"Nenhum desses idiomas está ativado no momento.","fr":"Aucune de ces langues n'est actuellement activée.","de":"Keine dieser Sprachen ist derzeit aktiviert.","ja":"指定された言語は現在どれも有効ではありません。","ko":"해당 언어 중 현재 활성화된 언어가 없습니다.","zh":"这些语言目前都未启用。","ru":"Ни один из этих языков сейчас не включён.","ar":"لا توجد أي من هذه اللغات مفعّلة حاليًا.","hi":"इनमें से कोई भी भाषा अभी सक्षम नहीं है।","id":"Tidak satu pun dari bahasa tersebut sedang aktif."},
    "none_enabled": {
        "en":"No translation languages are currently enabled.","es":"Actualmente no hay idiomas de traducción habilitados.","pt":"Nenhum idioma de tradução está ativado no momento.","fr":"Aucune langue de traduction n'est actuellement activée.","de":"Derzeit sind keine Übersetzungssprachen aktiviert.","ja":"現在、有効な翻訳言語はありません。","ko":"현재 활성화된 번역 언어가 없습니다.","zh":"当前没有启用任何翻译语言。","ru":"Сейчас ни один язык перевода не включён.","ar":"لا توجد لغات ترجمة مفعّلة حاليًا.","hi":"अभी कोई अनुवाद भाषा सक्षम नहीं है।","id":"Saat ini tidak ada bahasa terjemahan yang diaktifkan."},
    "added": {"en":"Added: **{languages}**","es":"Añadidos: **{languages}**","pt":"Adicionados: **{languages}**","fr":"Ajoutées : **{languages}**","de":"Hinzugefügt: **{languages}**","ja":"追加しました: **{languages}**","ko":"추가됨: **{languages}**","zh":"已添加：**{languages}**","ru":"Добавлено: **{languages}**","ar":"تمت الإضافة: **{languages}**","hi":"जोड़ा गया: **{languages}**","id":"Ditambahkan: **{languages}**"},
    "removed": {"en":"Removed: **{languages}**","es":"Eliminados: **{languages}**","pt":"Removidos: **{languages}**","fr":"Retirées : **{languages}**","de":"Entfernt: **{languages}**","ja":"削除しました: **{languages}**","ko":"제거됨: **{languages}**","zh":"已移除：**{languages}**","ru":"Удалено: **{languages}**","ar":"تمت الإزالة: **{languages}**","hi":"हटाया गया: **{languages}**","id":"Dihapus: **{languages}**"},
    "still_enabled": {"en":"Still enabled: **{languages}**","es":"Aún habilitados: **{languages}**","pt":"Ainda ativados: **{languages}**","fr":"Toujours activées : **{languages}**","de":"Weiterhin aktiviert: **{languages}**","ja":"引き続き有効: **{languages}**","ko":"계속 활성화됨: **{languages}**","zh":"仍启用：**{languages}**","ru":"Остаются включёнными: **{languages}**","ar":"لا تزال مفعّلة: **{languages}**","hi":"अभी भी सक्षम: **{languages}**","id":"Masih aktif: **{languages}**"},
    "active": {"en":"Currently translating into: **{languages}**","es":"Traduciendo actualmente a: **{languages}**","pt":"Traduzindo atualmente para: **{languages}**","fr":"Traduction actuelle vers : **{languages}**","de":"Aktuelle Übersetzung in: **{languages}**","ja":"現在の翻訳先: **{languages}**","ko":"현재 번역 언어: **{languages}**","zh":"当前翻译为：**{languages}**","ru":"Сейчас переводится на: **{languages}**","ar":"الترجمة حاليًا إلى: **{languages}**","hi":"अभी इन भाषाओं में अनुवाद: **{languages}**","id":"Saat ini menerjemahkan ke: **{languages}**"},
    "already_translating": {"en":"I'm already translating **{channel}**. Use `/add`, `/remove`, `/active`, `/languages`, or `/leave`.","es":"Ya estoy traduciendo **{channel}**. Usa `/add`, `/remove`, `/active`, `/languages` o `/leave`.","pt":"Já estou traduzindo **{channel}**. Use `/add`, `/remove`, `/active`, `/languages` ou `/leave`.","fr":"Je traduis déjà **{channel}**. Utilisez `/add`, `/remove`, `/active`, `/languages` ou `/leave`.","de":"Ich übersetze bereits **{channel}**. Verwende `/add`, `/remove`, `/active`, `/languages` oder `/leave`.","ja":"すでに **{channel}** を翻訳しています。`/add`、`/remove`、`/active`、`/languages`、`/leave` を使用してください。","ko":"이미 **{channel}**을 번역하고 있습니다. `/add`, `/remove`, `/active`, `/languages`, `/leave`를 사용하세요.","zh":"我已经在翻译 **{channel}**。请使用 `/add`、`/remove`、`/active`、`/languages` 或 `/leave`。","ru":"Я уже перевожу **{channel}**. Используйте `/add`, `/remove`, `/active`, `/languages` или `/leave`.","ar":"أقوم بالفعل بترجمة **{channel}**. استخدم `/add` أو `/remove` أو `/active` أو `/languages` أو `/leave`.","hi":"मैं पहले से **{channel}** का अनुवाद कर रहा हूँ। `/add`, `/remove`, `/active`, `/languages` या `/leave` का उपयोग करें।","id":"Saya sudah menerjemahkan **{channel}**. Gunakan `/add`, `/remove`, `/active`, `/languages`, atau `/leave`."},
    "join": {"en":"Joined **{channel}**.\nTranslating into: **{languages}**\n\nTranscriptions and translations will be posted in this voice channel's side chat.","es":"Me uní a **{channel}**.\nTraduciendo a: **{languages}**\n\nLas transcripciones y traducciones se publicarán en el chat lateral de este canal de voz.","pt":"Entrei em **{channel}**.\nTraduzindo para: **{languages}**\n\nAs transcrições e traduções serão publicadas no chat lateral deste canal de voz.","fr":"J'ai rejoint **{channel}**.\nTraduction vers : **{languages}**\n\nLes transcriptions et traductions seront publiées dans le chat latéral de ce salon vocal.","de":"**{channel}** beigetreten.\nÜbersetzung in: **{languages}**\n\nTranskriptionen und Übersetzungen werden im Seitenchat dieses Sprachkanals veröffentlicht.","ja":"**{channel}** に参加しました。\n翻訳先: **{languages}**\n\n文字起こしと翻訳はこのボイスチャンネルのサイドチャットに投稿されます。","ko":"**{channel}**에 참가했습니다.\n번역 언어: **{languages}**\n\n받아쓰기와 번역은 이 음성 채널의 사이드 채팅에 게시됩니다.","zh":"已加入 **{channel}**。\n翻译为：**{languages}**\n\n转录和翻译将发布到此语音频道的侧边聊天中。","ru":"Подключился к **{channel}**.\nПеревод на: **{languages}**\n\nТранскрипции и переводы будут публиковаться в боковом чате этого голосового канала.","ar":"تم الانضمام إلى **{channel}**.\nالترجمة إلى: **{languages}**\n\nسيتم نشر النصوص والترجمات في الدردشة الجانبية لهذه القناة الصوتية.","hi":"**{channel}** में जुड़ गया।\nइन भाषाओं में अनुवाद: **{languages}**\n\nट्रांसक्रिप्शन और अनुवाद इस वॉइस चैनल की साइड चैट में पोस्ट होंगे।","id":"Bergabung ke **{channel}**.\nMenerjemahkan ke: **{languages}**\n\nTranskripsi dan terjemahan akan diposting di chat samping kanal suara ini."},
    "voicely_text": {"en":"To read translations out loud, use [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","es":"Para leer las traducciones en voz alta, usa [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","pt":"Para ler as traduções em voz alta, use [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","fr":"Pour lire les traductions à voix haute, utilisez [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","de":"Zum Vorlesen der Übersetzungen verwende [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","ja":"翻訳を読み上げるには [**Voicely Text**](https://discord.com/application-directory/1290741552158609419) を使用してください。","ko":"번역을 소리 내어 읽으려면 [**Voicely Text**](https://discord.com/application-directory/1290741552158609419)를 사용하세요.","zh":"如需朗读翻译，请使用 [**Voicely Text**](https://discord.com/application-directory/1290741552158609419)。","ru":"Чтобы озвучивать переводы, используйте [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","ar":"لقراءة الترجمات بصوت عالٍ، استخدم [**Voicely Text**](https://discord.com/application-directory/1290741552158609419).","hi":"अनुवाद को आवाज़ में पढ़ने के लिए [**Voicely Text**](https://discord.com/application-directory/1290741552158609419) का उपयोग करें।","id":"Untuk membacakan terjemahan, gunakan [**Voicely Text**](https://discord.com/application-directory/1290741552158609419)."},
    "join_failed": {"en":"I couldn't join that voice channel: `{error}`","es":"No pude unirme a ese canal de voz: `{error}`","pt":"Não consegui entrar nesse canal de voz: `{error}`","fr":"Je n'ai pas pu rejoindre ce salon vocal : `{error}`","de":"Ich konnte diesem Sprachkanal nicht beitreten: `{error}`","ja":"そのボイスチャンネルに参加できませんでした: `{error}`","ko":"해당 음성 채널에 참가할 수 없습니다: `{error}`","zh":"无法加入该语音频道：`{error}`","ru":"Не удалось войти в этот голосовой канал: `{error}`","ar":"تعذر الانضمام إلى تلك القناة الصوتية: `{error}`","hi":"उस वॉइस चैनल में शामिल नहीं हो सका: `{error}`","id":"Tidak dapat bergabung ke kanal suara tersebut: `{error}`"},
    "left": {"en":"Stopped translating and left the voice channel.","es":"Se detuvo la traducción y salí del canal de voz.","pt":"A tradução foi interrompida e saí do canal de voz.","fr":"La traduction a été arrêtée et j'ai quitté le salon vocal.","de":"Die Übersetzung wurde beendet und ich habe den Sprachkanal verlassen.","ja":"翻訳を停止し、ボイスチャンネルから退出しました。","ko":"번역을 중지하고 음성 채널에서 나갔습니다.","zh":"已停止翻译并离开语音频道。","ru":"Перевод остановлен, я вышел из голосового канала.","ar":"تم إيقاف الترجمة ومغادرة القناة الصوتية.","hi":"अनुवाद बंद कर दिया गया और वॉइस चैनल छोड़ दिया गया।","id":"Penerjemahan dihentikan dan saya keluar dari kanal suara."},
    "timeout_set": {"en":"Empty-channel timeout set to **{seconds} seconds**.","es":"El tiempo de espera del canal vacío se estableció en **{seconds} segundos**.","pt":"O tempo limite do canal vazio foi definido como **{seconds} segundos**.","fr":"Le délai du salon vide est défini sur **{seconds} secondes**.","de":"Die Wartezeit für einen leeren Kanal wurde auf **{seconds} Sekunden** gesetzt.","ja":"空チャンネルのタイムアウトを **{seconds}秒** に設定しました。","ko":"빈 채널 대기 시간을 **{seconds}초**로 설정했습니다.","zh":"空频道超时已设为 **{seconds} 秒**。","ru":"Таймаут пустого канала установлен на **{seconds} секунд**.","ar":"تم ضبط مهلة القناة الفارغة على **{seconds} ثانية**.","hi":"खाली चैनल की समयसीमा **{seconds} सेकंड** पर सेट की गई।","id":"Batas waktu kanal kosong diatur ke **{seconds} detik**."},
    "credit_exhausted": {"en":"### Voicely Translate credit exhausted\nThis server has used all of its available translation credit, so I'm leaving the voice channel.\nAn administrator can use `/topup` to add more credit through Ko-fi.","es":"### Créditos de Voicely Translate agotados\nEste servidor ha usado todos sus créditos de traducción disponibles, así que saldré del canal de voz.\nUn administrador puede usar `/topup` para añadir más créditos mediante Ko-fi.","pt":"### Créditos do Voicely Translate esgotados\nEste servidor usou todos os créditos de tradução disponíveis, então vou sair do canal de voz.\nUm administrador pode usar `/topup` para adicionar créditos pelo Ko-fi.","fr":"### Crédits Voicely Translate épuisés\nCe serveur a utilisé tous ses crédits de traduction disponibles, je quitte donc le salon vocal.\nUn administrateur peut utiliser `/topup` pour ajouter des crédits via Ko-fi.","de":"### Voicely-Translate-Credits aufgebraucht\nDieser Server hat sein gesamtes Übersetzungsguthaben verbraucht, daher verlasse ich den Sprachkanal.\nEin Administrator kann mit `/topup` über Ko-fi weitere Credits hinzufügen.","ja":"### Voicely Translateクレジットを使い切りました\nこのサーバーの利用可能な翻訳クレジットがなくなったため、ボイスチャンネルから退出します。\n管理者は `/topup` でKo-fiからクレジットを追加できます。","ko":"### Voicely Translate 크레딧 소진\n이 서버의 사용 가능한 번역 크레딧을 모두 사용했으므로 음성 채널에서 나갑니다.\n관리자는 `/topup`을 사용해 Ko-fi에서 크레딧을 추가할 수 있습니다.","zh":"### Voicely Translate 点数已用尽\n此服务器已用完所有可用翻译点数，因此我将离开语音频道。\n管理员可以使用 `/topup` 通过 Ko-fi 添加更多点数。","ru":"### Кредиты Voicely Translate закончились\nСервер израсходовал все доступные кредиты перевода, поэтому я выхожу из голосового канала.\nАдминистратор может использовать `/topup`, чтобы добавить кредиты через Ko-fi.","ar":"### نفد رصيد Voicely Translate\nاستخدم هذا الخادم كل رصيد الترجمة المتاح، لذلك سأغادر القناة الصوتية.\nيمكن للمسؤول استخدام `/topup` لإضافة رصيد عبر Ko-fi.","hi":"### Voicely Translate क्रेडिट समाप्त\nइस सर्वर ने उपलब्ध सभी अनुवाद क्रेडिट इस्तेमाल कर लिए हैं, इसलिए मैं वॉइस चैनल छोड़ रहा हूँ।\nएडमिन `/topup` से Ko-fi के माध्यम से और क्रेडिट जोड़ सकता है।","id":"### Kredit Voicely Translate habis\nServer ini telah menggunakan seluruh kredit terjemahan yang tersedia, jadi saya akan keluar dari kanal suara.\nAdministrator dapat menggunakan `/topup` untuk menambah kredit melalui Ko-fi."},
    "trial_notice": {
        "en":"**Free trial:** This server includes **50 free Voicely Credits** to get started.",
        "es":"**Prueba gratuita:** Este servidor incluye **50 créditos Voicely gratis** para comenzar.",
        "pt":"**Teste gratuito:** Este servidor inclui **50 Voicely Credits grátis** para começar.",
        "fr":"**Essai gratuit :** Ce serveur comprend **50 crédits Voicely gratuits** pour commencer.",
        "de":"**Kostenlose Testversion:** Dieser Server erhält zum Start **50 kostenlose Voicely Credits**.",
        "ja":"**無料トライアル:** このサーバーには開始時に **50 Voicely Credits** が無料で付与されます。",
        "ko":"**무료 체험:** 이 서버에는 시작할 수 있도록 **50개의 무료 Voicely Credits**가 포함됩니다.",
        "zh":"**免费试用：** 此服务器初始包含 **50 个免费 Voicely Credits**。",
        "ru":"**Бесплатный пробный период:** Для начала этот сервер получает **50 бесплатных Voicely Credits**.",
        "ar":"**تجربة مجانية:** يحصل هذا الخادم على **50 رصيد Voicely مجانيًا** للبدء.",
        "hi":"**मुफ़्त ट्रायल:** इस सर्वर को शुरुआत के लिए **50 मुफ़्त Voicely Credits** मिलते हैं।",
        "id":"**Uji coba gratis:** Server ini mendapat **50 Voicely Credits gratis** untuk memulai.",
    },
    "trial_notice_once": {
        'en':"This notice will not be displayed again.",
        'es':"Este aviso no se volverá a mostrar.",
        'pt':"Este aviso não será exibido novamente.",
        'fr':"Cet avis ne sera plus affiché.",
        'de':"Dieser Hinweis wird nicht erneut angezeigt.",
        'ja':"このお知らせは今後表示されません。",
        'ko':"이 안내는 다시 표시되지 않습니다.",
        'zh':"此通知将不会再次显示。",
        'ru':"Это уведомление больше не будет отображаться.",
        'ar':"لن يتم عرض هذا التنبيه مرة أخرى.",
        'hi':"यह सूचना दोबारा प्रदर्शित नहीं की जाएगी।",
        'id':"Pemberitahuan ini tidak akan ditampilkan lagi.",
    },
    "trial_exhausted": {
        "en":"### Free trial ended\nThis server has used all **50 free Voicely Credits** included with its trial, so I'm leaving the voice channel.\nTo continue using Voicely Translate, an administrator can use `/topup` to purchase additional credits through Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "es":"### Prueba gratuita finalizada\nEste servidor ha usado los **50 créditos Voicely gratis** incluidos con la prueba, así que saldré del canal de voz.\nPara seguir usando Voicely Translate, un administrador puede usar `/topup` para comprar créditos adicionales mediante Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "pt":"### Teste gratuito encerrado\nEste servidor usou todos os **50 Voicely Credits grátis** incluídos no teste, então vou sair do canal de voz.\nPara continuar usando o Voicely Translate, um administrador pode usar `/topup` para comprar créditos adicionais pelo Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "fr":"### Essai gratuit terminé\nCe serveur a utilisé les **50 crédits Voicely gratuits** inclus dans son essai, je quitte donc le salon vocal.\nPour continuer à utiliser Voicely Translate, un administrateur peut utiliser `/topup` pour acheter des crédits supplémentaires via Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "de":"### Kostenlose Testversion beendet\nDieser Server hat alle **50 kostenlosen Voicely Credits** aus der Testversion verbraucht, daher verlasse ich den Sprachkanal.\nUm Voicely Translate weiter zu verwenden, kann ein Administrator mit `/topup` zusätzliche Credits über Ko-fi kaufen.\n\n**100 Voicely Credits = $1.00 USD.**",
        "ja":"### 無料トライアル終了\nこのサーバーはトライアルに含まれる **50 Voicely Credits** をすべて使い切ったため、ボイスチャンネルから退出します。\nVoicely Translateを引き続き使用するには、管理者が `/topup` からKo-fiで追加クレジットを購入できます。\n\n**100 Voicely Credits = $1.00 USD.**",
        "ko":"### 무료 체험 종료\n이 서버는 체험에 포함된 **50개의 무료 Voicely Credits**를 모두 사용했으므로 음성 채널에서 나갑니다.\nVoicely Translate를 계속 사용하려면 관리자가 `/topup`으로 Ko-fi에서 추가 크레딧을 구매할 수 있습니다.\n\n**100 Voicely Credits = $1.00 USD.**",
        "zh":"### 免费试用已结束\n此服务器已用完试用包含的 **50 个免费 Voicely Credits**，因此我将离开语音频道。\n要继续使用 Voicely Translate，管理员可以使用 `/topup` 通过 Ko-fi 购买更多点数。\n\n**100 Voicely Credits = $1.00 USD.**",
        "ru":"### Бесплатный пробный период завершён\nСервер использовал все **50 бесплатных Voicely Credits**, включённых в пробный период, поэтому я выхожу из голосового канала.\nЧтобы продолжить использовать Voicely Translate, администратор может использовать `/topup` для покупки дополнительных кредитов через Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "ar":"### انتهت التجربة المجانية\nاستخدم هذا الخادم جميع **أرصدة Voicely المجانية البالغ عددها 50** والمشمولة في التجربة، لذلك سأغادر القناة الصوتية.\nلمواصلة استخدام Voicely Translate، يمكن للمسؤول استخدام `/topup` لشراء أرصدة إضافية عبر Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "hi":"### मुफ़्त ट्रायल समाप्त\nइस सर्वर ने ट्रायल में शामिल सभी **50 मुफ़्त Voicely Credits** इस्तेमाल कर लिए हैं, इसलिए मैं वॉइस चैनल छोड़ रहा हूँ।\nVoicely Translate का उपयोग जारी रखने के लिए एडमिन `/topup` से Ko-fi के माध्यम से अतिरिक्त क्रेडिट खरीद सकता है।\n\n**100 Voicely Credits = $1.00 USD.**",
        "id":"### Uji coba gratis berakhir\nServer ini telah menggunakan semua **50 Voicely Credits gratis** yang disertakan dalam uji coba, jadi saya akan keluar dari kanal suara.\nUntuk terus menggunakan Voicely Translate, administrator dapat menggunakan `/topup` untuk membeli kredit tambahan melalui Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
    },
    "trial_exhausted_join": {
        "en":"### Free trial ended\nThis server has used all **50 free Voicely Credits** included with its trial.\nTo continue using Voicely Translate, an administrator can use `/topup` to purchase additional credits through Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "es":"### Prueba gratuita finalizada\nEste servidor ha usado los **50 créditos Voicely gratis** incluidos con la prueba.\nPara seguir usando Voicely Translate, un administrador puede usar `/topup` para comprar créditos adicionales mediante Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "pt":"### Teste gratuito encerrado\nEste servidor usou todos os **50 Voicely Credits grátis** incluídos no teste.\nPara continuar usando o Voicely Translate, um administrador pode usar `/topup` para comprar créditos adicionais pelo Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "fr":"### Essai gratuit terminé\nCe serveur a utilisé les **50 crédits Voicely gratuits** inclus dans son essai.\nPour continuer à utiliser Voicely Translate, un administrateur peut utiliser `/topup` pour acheter des crédits supplémentaires via Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "de":"### Kostenlose Testversion beendet\nDieser Server hat alle **50 kostenlosen Voicely Credits** aus der Testversion verbraucht.\nUm Voicely Translate weiter zu verwenden, kann ein Administrator mit `/topup` zusätzliche Credits über Ko-fi kaufen.\n\n**100 Voicely Credits = $1.00 USD.**",
        "ja":"### 無料トライアル終了\nこのサーバーはトライアルに含まれる **50 Voicely Credits** をすべて使い切りました。\nVoicely Translateを引き続き使用するには、管理者が `/topup` からKo-fiで追加クレジットを購入できます。\n\n**100 Voicely Credits = $1.00 USD.**",
        "ko":"### 무료 체험 종료\n이 서버는 체험에 포함된 **50개의 무료 Voicely Credits**를 모두 사용했습니다.\nVoicely Translate를 계속 사용하려면 관리자가 `/topup`으로 Ko-fi에서 추가 크레딧을 구매할 수 있습니다.\n\n**100 Voicely Credits = $1.00 USD.**",
        "zh":"### 免费试用已结束\n此服务器已用完试用包含的 **50 个免费 Voicely Credits**。\n要继续使用 Voicely Translate，管理员可以使用 `/topup` 通过 Ko-fi 购买更多点数。\n\n**100 Voicely Credits = $1.00 USD.**",
        "ru":"### Бесплатный пробный период завершён\nСервер использовал все **50 бесплатных Voicely Credits**, включённых в пробный период.\nЧтобы продолжить использовать Voicely Translate, администратор может использовать `/topup` для покупки дополнительных кредитов через Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "ar":"### انتهت التجربة المجانية\nاستخدم هذا الخادم جميع **أرصدة Voicely المجانية البالغ عددها 50** والمشمولة في التجربة.\nلمواصلة استخدام Voicely Translate، يمكن للمسؤول استخدام `/topup` لشراء أرصدة إضافية عبر Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
        "hi":"### मुफ़्त ट्रायल समाप्त\nइस सर्वर ने ट्रायल में शामिल सभी **50 मुफ़्त Voicely Credits** इस्तेमाल कर लिए हैं।\nVoicely Translate का उपयोग जारी रखने के लिए एडमिन `/topup` से Ko-fi के माध्यम से अतिरिक्त क्रेडिट खरीद सकता है।\n\n**100 Voicely Credits = $1.00 USD.**",
        "id":"### Uji coba gratis berakhir\nServer ini telah menggunakan semua **50 Voicely Credits gratis** yang disertakan dalam uji coba.\nUntuk terus menggunakan Voicely Translate, administrator dapat menggunakan `/topup` untuk membeli kredit tambahan melalui Ko-fi.\n\n**100 Voicely Credits = $1.00 USD.**",
    },

    "no_default_languages": {
        "en":"No default languages have been set for this server. Specify languages with `/join`, or ask a server administrator to set them with `/defaultlanguages`.",
        "es":"No se han establecido idiomas predeterminados para este servidor. Especifica idiomas con `/join` o pide a un administrador del servidor que los establezca con `/defaultlanguages`.",
        "pt":"Nenhum idioma padrão foi definido para este servidor. Especifique idiomas com `/join` ou peça a um administrador do servidor para defini-los com `/defaultlanguages`.",
        "fr":"Aucune langue par défaut n'a été définie pour ce serveur. Indiquez des langues avec `/join` ou demandez à un administrateur du serveur de les définir avec `/defaultlanguages`.",
        "de":"Für diesen Server wurden keine Standardsprachen festgelegt. Gib bei `/join` Sprachen an oder bitte einen Serveradministrator, sie mit `/defaultlanguages` festzulegen.",
        "ja":"このサーバーにはデフォルト言語が設定されていません。`/join` で言語を指定するか、サーバー管理者に `/defaultlanguages` で設定してもらってください。",
        "ko":"이 서버에는 기본 언어가 설정되어 있지 않습니다. `/join`에서 언어를 지정하거나 서버 관리자에게 `/defaultlanguages`로 설정해 달라고 요청하세요.",
        "zh":"此服务器尚未设置默认语言。请使用 `/join` 指定语言，或请服务器管理员使用 `/defaultlanguages` 进行设置。",
        "ru":"Для этого сервера не заданы языки по умолчанию. Укажите языки в `/join` или попросите администратора сервера задать их с помощью `/defaultlanguages`.",
        "ar":"لم يتم تعيين لغات افتراضية لهذا الخادم. حدّد اللغات باستخدام `/join`، أو اطلب من مسؤول الخادم تعيينها باستخدام `/defaultlanguages`.",
        "hi":"इस सर्वर के लिए कोई डिफ़ॉल्ट भाषा सेट नहीं की गई है। `/join` में भाषाएँ दें, या सर्वर एडमिन से `/defaultlanguages` के साथ उन्हें सेट करने के लिए कहें।",
        "id":"Belum ada bahasa default yang ditetapkan untuk server ini. Tentukan bahasa dengan `/join`, atau minta administrator server mengaturnya dengan `/defaultlanguages`.",
    },
    "default_languages_set": {
        "en":"Default translation languages set to: **{languages}**.",
        "es":"Idiomas de traducción predeterminados establecidos en: **{languages}**.",
        "pt":"Idiomas de tradução padrão definidos como: **{languages}**.",
        "fr":"Langues de traduction par défaut définies sur : **{languages}**.",
        "de":"Standard-Übersetzungssprachen festgelegt auf: **{languages}**.",
        "ja":"デフォルトの翻訳言語を **{languages}** に設定しました。",
        "ko":"기본 번역 언어를 **{languages}**(으)로 설정했습니다.",
        "zh":"默认翻译语言已设置为：**{languages}**。",
        "ru":"Языки перевода по умолчанию установлены: **{languages}**.",
        "ar":"تم تعيين لغات الترجمة الافتراضية إلى: **{languages}**.",
        "hi":"डिफ़ॉल्ट अनुवाद भाषाएँ सेट की गईं: **{languages}**।",
        "id":"Bahasa terjemahan default ditetapkan ke: **{languages}**.",
    },
    "languages_heading": {
        "en":"**Common language tags**","es":"**Etiquetas de idioma comunes**","pt":"**Tags de idioma comuns**","fr":"**Balises de langue courantes**","de":"**Häufige Sprach-Tags**","ja":"**一般的な言語タグ**","ko":"**일반적인 언어 태그**","zh":"**常用语言标签**","ru":"**Распространённые языковые теги**","ar":"**وسوم اللغات الشائعة**","hi":"**सामान्य भाषा टैग**","id":"**Tag bahasa umum**",
    },
    "languages_intro": {
        "en":"These are common language tags you can use with `/join`, `/add`, and `/remove`.","es":"Estas son etiquetas de idioma comunes que puedes usar con `/join`, `/add` y `/remove`.","pt":"Estas são tags de idioma comuns que você pode usar com `/join`, `/add` e `/remove`.","fr":"Voici des balises de langue courantes que vous pouvez utiliser avec `/join`, `/add` et `/remove`.","de":"Dies sind häufige Sprach-Tags, die du mit `/join`, `/add` und `/remove` verwenden kannst.","ja":"これらは `/join`、`/add`、`/remove` で使用できる一般的な言語タグです。","ko":"다음은 `/join`, `/add`, `/remove`에서 사용할 수 있는 일반적인 언어 태그입니다.","zh":"以下是可用于 `/join`、`/add` 和 `/remove` 的常用语言标签。","ru":"Это распространённые языковые теги, которые можно использовать с `/join`, `/add` и `/remove`.","ar":"هذه وسوم لغات شائعة يمكنك استخدامها مع `/join` و`/add` و`/remove`.","hi":"ये सामान्य भाषा टैग हैं जिन्हें आप `/join`, `/add`, और `/remove` के साथ उपयोग कर सकते हैं।","id":"Berikut adalah tag bahasa umum yang dapat digunakan dengan `/join`, `/add`, dan `/remove`.",
    },
    "languages_not_limited": {
        "en":"Voicely Translate is not limited to this list—you can enter other valid BCP 47 language tags as well.","es":"Voicely Translate no se limita a esta lista; también puedes introducir otras etiquetas de idioma BCP 47 válidas.","pt":"O Voicely Translate não se limita a esta lista; você também pode inserir outras tags de idioma BCP 47 válidas.","fr":"Voicely Translate ne se limite pas à cette liste : vous pouvez également saisir d'autres balises de langue BCP 47 valides.","de":"Voicely Translate ist nicht auf diese Liste beschränkt – du kannst auch andere gültige BCP-47-Sprach-Tags eingeben.","ja":"Voicely Translate はこの一覧に限定されません。他の有効な BCP 47 言語タグも入力できます。","ko":"Voicely Translate는 이 목록에만 제한되지 않습니다. 다른 유효한 BCP 47 언어 태그도 입력할 수 있습니다.","zh":"Voicely Translate 不限于此列表；你也可以输入其他有效的 BCP 47 语言标签。","ru":"Voicely Translate не ограничивается этим списком — можно вводить и другие допустимые языковые теги BCP 47.","ar":"لا يقتصر Voicely Translate على هذه القائمة؛ يمكنك أيضًا إدخال وسوم لغات BCP 47 صالحة أخرى.","hi":"Voicely Translate केवल इस सूची तक सीमित नहीं है—आप अन्य मान्य BCP 47 भाषा टैग भी दर्ज कर सकते हैं।","id":"Voicely Translate tidak terbatas pada daftar ini—Anda juga dapat memasukkan tag bahasa BCP 47 lain yang valid.",
    },
    "regional_tags_heading": {
        "en":"**Common regional/script tags**","es":"**Etiquetas regionales/de escritura comunes**","pt":"**Tags regionais/de escrita comuns**","fr":"**Balises régionales/de script courantes**","de":"**Häufige Regions-/Schrift-Tags**","ja":"**一般的な地域・文字体系タグ**","ko":"**일반적인 지역/문자 태그**","zh":"**常用地区/文字标签**","ru":"**Распространённые региональные теги/теги письменности**","ar":"**وسوم المناطق/أنظمة الكتابة الشائعة**","hi":"**सामान्य क्षेत्रीय/लिपि टैग**","id":"**Tag wilayah/aksara umum**",
    },
    "languages_try_other": {
        "en":"If a language is not listed above, you can still try its BCP 47 language tag.","es":"Si un idioma no aparece arriba, puedes probar igualmente su etiqueta de idioma BCP 47.","pt":"Se um idioma não estiver listado acima, você ainda pode tentar usar sua tag de idioma BCP 47.","fr":"Si une langue ne figure pas ci-dessus, vous pouvez tout de même essayer sa balise de langue BCP 47.","de":"Wenn eine Sprache oben nicht aufgeführt ist, kannst du trotzdem ihr BCP-47-Sprach-Tag ausprobieren.","ja":"上記にない言語でも、その BCP 47 言語タグを試すことができます。","ko":"위 목록에 없는 언어도 해당 BCP 47 언어 태그를 사용해 볼 수 있습니다.","zh":"如果某种语言未列在上方，你仍可以尝试使用其 BCP 47 语言标签。","ru":"Если языка нет в списке выше, всё равно можно попробовать его языковой тег BCP 47.","ar":"إذا لم تكن اللغة مدرجة أعلاه، فلا يزال بإمكانك تجربة وسم BCP 47 الخاص بها.","hi":"यदि कोई भाषा ऊपर सूचीबद्ध नहीं है, तब भी आप उसका BCP 47 भाषा टैग आज़मा सकते हैं।","id":"Jika suatu bahasa tidak tercantum di atas, Anda tetap dapat mencoba tag bahasa BCP 47-nya.",
    },
    "topup_not_configured": {
        "en":"Ko-fi top-ups have not been configured by the bot owner yet. This server's persistent top-up code is **`{code}`**.","es":"El propietario del bot aún no ha configurado las recargas de Ko-fi. El código de recarga permanente de este servidor es **`{code}`**.","pt":"As recargas pelo Ko-fi ainda não foram configuradas pelo proprietário do bot. O código permanente de recarga deste servidor é **`{code}`**.","fr":"Les recharges Ko-fi n'ont pas encore été configurées par le propriétaire du bot. Le code de recharge permanent de ce serveur est **`{code}`**.","de":"Ko-fi-Aufladungen wurden vom Bot-Betreiber noch nicht konfiguriert. Der dauerhafte Aufladecode dieses Servers lautet **`{code}`**.","ja":"Botの所有者がKo-fiチャージをまだ設定していません。このサーバーの固定チャージコードは **`{code}`** です。","ko":"봇 소유자가 아직 Ko-fi 충전을 설정하지 않았습니다. 이 서버의 영구 충전 코드는 **`{code}`**입니다.","zh":"机器人所有者尚未配置 Ko-fi 充值。此服务器的固定充值代码为 **`{code}`**。","ru":"Владелец бота ещё не настроил пополнение через Ko-fi. Постоянный код пополнения этого сервера: **`{code}`**.","ar":"لم يقم مالك البوت بإعداد عمليات الشحن عبر Ko-fi بعد. رمز الشحن الدائم لهذا الخادم هو **`{code}`**.","hi":"बॉट के मालिक ने अभी तक Ko-fi टॉप-अप कॉन्फ़िगर नहीं किए हैं। इस सर्वर का स्थायी टॉप-अप कोड **`{code}`** है।","id":"Top-up Ko-fi belum dikonfigurasi oleh pemilik bot. Kode top-up permanen server ini adalah **`{code}`**.",
    },
    "topup_service_error": {
        "en":"I couldn't reach the Ko-fi payment service right now. Please try again shortly.","es":"No pude comunicarme con el servicio de pagos de Ko-fi en este momento. Inténtalo de nuevo en breve.","pt":"Não consegui acessar o serviço de pagamento do Ko-fi agora. Tente novamente em instantes.","fr":"Je n'ai pas pu joindre le service de paiement Ko-fi pour le moment. Veuillez réessayer dans quelques instants.","de":"Ich konnte den Ko-fi-Zahlungsdienst gerade nicht erreichen. Bitte versuche es in Kürze erneut.","ja":"現在Ko-fiの決済サービスに接続できませんでした。しばらくしてからもう一度お試しください。","ko":"현재 Ko-fi 결제 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.","zh":"目前无法连接 Ko-fi 支付服务。请稍后重试。","ru":"Сейчас не удалось связаться с платёжным сервисом Ko-fi. Повторите попытку немного позже.","ar":"تعذر الوصول إلى خدمة الدفع Ko-fi حاليًا. يرجى المحاولة مرة أخرى بعد قليل.","hi":"अभी Ko-fi भुगतान सेवा से संपर्क नहीं हो सका। कृपया थोड़ी देर बाद फिर प्रयास करें।","id":"Saat ini saya tidak dapat menghubungi layanan pembayaran Ko-fi. Silakan coba lagi sebentar lagi.",
    },
    "topup_heading": {
        "en":"### Add Voicely Translate credit","es":"### Añadir créditos de Voicely Translate","pt":"### Adicionar créditos do Voicely Translate","fr":"### Ajouter des crédits Voicely Translate","de":"### Voicely-Translate-Credits hinzufügen","ja":"### Voicely Translateクレジットを追加","ko":"### Voicely Translate 크레딧 추가","zh":"### 添加 Voicely Translate 点数","ru":"### Добавить кредиты Voicely Translate","ar":"### إضافة رصيد Voicely Translate","hi":"### Voicely Translate क्रेडिट जोड़ें","id":"### Tambahkan kredit Voicely Translate",
    },
    "topup_code": {
        "en":"Your server's top-up code is **`{code}`**.","es":"El código de recarga de tu servidor es **`{code}`**.","pt":"O código de recarga do seu servidor é **`{code}`**.","fr":"Le code de recharge de votre serveur est **`{code}`**.","de":"Der Aufladecode deines Servers lautet **`{code}`**.","ja":"このサーバーのチャージコードは **`{code}`** です。","ko":"이 서버의 충전 코드는 **`{code}`**입니다.","zh":"你的服务器充值代码为 **`{code}`**。","ru":"Код пополнения вашего сервера: **`{code}`**.","ar":"رمز شحن خادمك هو **`{code}`**.","hi":"आपके सर्वर का टॉप-अप कोड **`{code}`** है।","id":"Kode top-up server Anda adalah **`{code}`**.",
    },
    "topup_include_code": {
        "en":"Include that exact code in the message with your Ko-fi payment.","es":"Incluye ese código exacto en el mensaje de tu pago de Ko-fi.","pt":"Inclua exatamente esse código na mensagem do seu pagamento pelo Ko-fi.","fr":"Incluez exactement ce code dans le message accompagnant votre paiement Ko-fi.","de":"Gib genau diesen Code in der Nachricht zu deiner Ko-fi-Zahlung an.","ja":"Ko-fiで支払う際のメッセージに、このコードを正確に入力してください。","ko":"Ko-fi 결제 메시지에 이 코드를 정확히 입력하세요.","zh":"请在 Ko-fi 付款附带的消息中填写完全相同的代码。","ru":"Укажите этот код без изменений в сообщении к платежу Ko-fi.","ar":"أدرج هذا الرمز كما هو تمامًا في الرسالة المرفقة بدفعتك عبر Ko-fi.","hi":"अपने Ko-fi भुगतान के साथ संदेश में यही कोड ठीक उसी तरह शामिल करें।","id":"Sertakan kode tersebut persis seperti itu dalam pesan pembayaran Ko-fi Anda.",
    },
    "topup_rate": {
        "en":"Every **$1.00 USD adds 100 Voicely Credits** to this server.","es":"Cada **$1.00 USD añade 100 créditos de Voicely** a este servidor.","pt":"Cada **$1.00 USD adiciona 100 Créditos Voicely** a este servidor.","fr":"Chaque **1,00 $ USD ajoute 100 crédits Voicely** à ce serveur.","de":"Je **1,00 $ USD werden diesem Server 100 Voicely-Credits** hinzugefügt.","ja":"**$1.00 USDごとに100 Voicelyクレジット**がこのサーバーに追加されます。","ko":"**$1.00 USD마다 100 Voicely 크레딧**이 이 서버에 추가됩니다.","zh":"每 **$1.00 USD 可为此服务器添加 100 Voicely 点数**。","ru":"Каждый **$1.00 USD добавляет на этот сервер 100 кредитов Voicely**.","ar":"كل **$1.00 USD يضيف 100 رصيد Voicely** إلى هذا الخادم.","hi":"हर **$1.00 USD से इस सर्वर में 100 Voicely क्रेडिट** जुड़ते हैं।","id":"Setiap **$1.00 USD menambahkan 100 Kredit Voicely** ke server ini.",
    },
    "topup_after_payment": {
        "en":"After payment, use `/balance` (or `/join`) and the bot will automatically pull in the new credit.","es":"Después del pago, usa `/balance` (o `/join`) y el bot añadirá automáticamente los nuevos créditos.","pt":"Após o pagamento, use `/balance` (ou `/join`) e o bot obterá automaticamente os novos créditos.","fr":"Après le paiement, utilisez `/balance` (ou `/join`) et le bot récupérera automatiquement les nouveaux crédits.","de":"Verwende nach der Zahlung `/balance` (oder `/join`), und der Bot übernimmt die neuen Credits automatisch.","ja":"支払い後に `/balance`（または `/join`）を使用すると、Botが新しいクレジットを自動的に反映します。","ko":"결제 후 `/balance`(또는 `/join`)을 사용하면 봇이 새 크레딧을 자동으로 반영합니다.","zh":"付款后使用 `/balance`（或 `/join`），机器人会自动获取新增点数。","ru":"После оплаты используйте `/balance` (или `/join`), и бот автоматически добавит новые кредиты.","ar":"بعد الدفع، استخدم `/balance` (أو `/join`) وسيقوم البوت تلقائيًا بإضافة الرصيد الجديد.","hi":"भुगतान के बाद `/balance` (या `/join`) का उपयोग करें और बॉट नए क्रेडिट को अपने आप जोड़ देगा।","id":"Setelah pembayaran, gunakan `/balance` (atau `/join`) dan bot akan otomatis mengambil kredit baru.",
    },
    "original_label": {
        "en":"Original","es":"Original","pt":"Original","fr":"Original","de":"Original","ja":"原文","ko":"원문","zh":"原文","ru":"Оригинал","ar":"الأصل","hi":"मूल","id":"Asli",
    },

    "topup_separate_order": {
        "en":"**Important:** Please purchase Voicely Translate Credits separately from other items in the same order.",
        "es":"**Importante:** Compra los créditos de Voicely Translate por separado de otros artículos en el mismo pedido.",
        "pt":"**Importante:** Compre os créditos do Voicely Translate separadamente de outros itens no mesmo pedido.",
        "fr":"**Important :** Veuillez acheter les crédits Voicely Translate séparément des autres articles de la même commande.",
        "de":"**Wichtig:** Bitte kaufe Voicely Translate Credits getrennt von anderen Artikeln in derselben Bestellung.",
        "ja":"**重要:** Voicely Translate Creditsは、同じ注文内の他の商品とは別に購入してください。",
        "ko":"**중요:** Voicely Translate Credits는 같은 주문의 다른 상품과 별도로 구매해 주세요.",
        "zh":"**重要：** 请将 Voicely Translate Credits 与同一订单中的其他商品分开购买。",
        "ru":"**Важно:** Покупайте Voicely Translate Credits отдельно от других товаров в том же заказе.",
        "ar":"**مهم:** يرجى شراء أرصدة Voicely Translate بشكل منفصل عن أي عناصر أخرى في الطلب نفسه.",
        "hi":"**महत्वपूर्ण:** कृपया Voicely Translate Credits को उसी ऑर्डर में अन्य वस्तुओं से अलग खरीदें।",
        "id":"**Penting:** Harap beli Voicely Translate Credits secara terpisah dari item lain dalam pesanan yang sama.",
    },
}

def ui_language_from_locale(locale) -> str:
    value = str(locale or "en-US").replace("_", "-").lower()
    primary = value.split("-", 1)[0]
    return UI_LANG_ALIASES.get(primary, "en")

def tr_locale(locale, key: str, **values) -> str:
    language = ui_language_from_locale(locale)
    table = UI.get(key, {})
    template = table.get(language, table.get("en", key))
    return template.format(**values)

def tr(interaction: discord.Interaction, key: str, **values) -> str:
    return tr_locale(getattr(interaction, "locale", "en-US"), key, **values)

COMMAND_LOCALIZATIONS = {
    "join":{"es":("unirse","Únete a tu canal de voz y comienza a traducir."),"pt-BR":("entrar","Entre no seu canal de voz e comece a traduzir."),"fr":("rejoindre","Rejoignez votre salon vocal et commencez à traduire."),"de":("beitreten","Tritt deinem Sprachkanal bei und starte die Übersetzung."),"ja":("参加","ボイスチャンネルに参加して翻訳を開始します。"),"ko":("참가","음성 채널에 참가하고 번역을 시작합니다."),"zh-CN":("加入","加入你的语音频道并开始翻译。"),"ru":("войти","Войти в голосовой канал и начать перевод."),"hi":("जुड़ें","अपने वॉइस चैनल में जुड़ें और अनुवाद शुरू करें।"),"id":("gabung","Gabung ke kanal suara Anda dan mulai menerjemahkan。")},
    "add":{"es":("agregar","Añade idiomas de traducción a la sesión activa."),"pt-BR":("adicionar","Adicione idiomas de tradução à sessão ativa."),"fr":("ajouter","Ajoutez des langues de traduction à la session active."),"de":("hinzufügen","Füge der aktiven Sitzung Übersetzungssprachen hinzu."),"ja":("追加","現在のセッションに翻訳言語を追加します。"),"ko":("추가","활성 세션에 번역 언어를 추가합니다."),"zh-CN":("添加","向当前会话添加翻译语言。"),"ru":("добавить","Добавить языки перевода в активный сеанс."),"hi":("जोड़ें","सक्रिय सत्र में अनुवाद भाषाएँ जोड़ें।"),"id":("tambah","Tambahkan bahasa terjemahan ke sesi aktif.")},
    "remove":{"es":("quitar","Quita idiomas de traducción de la sesión activa."),"pt-BR":("remover","Remova idiomas de tradução da sessão ativa."),"fr":("retirer","Retirez des langues de traduction de la session active."),"de":("entfernen","Entferne Übersetzungssprachen aus der aktiven Sitzung."),"ja":("削除","現在のセッションから翻訳言語を削除します。"),"ko":("제거","활성 세션에서 번역 언어를 제거합니다."),"zh-CN":("移除","从当前会话移除翻译语言。"),"ru":("удалить","Удалить языки перевода из активного сеанса."),"hi":("हटाएँ","सक्रिय सत्र से अनुवाद भाषाएँ हटाएँ।"),"id":("hapus","Hapus bahasa terjemahan dari sesi aktif.")},
    "active":{"es":("activos","Muestra los idiomas de traducción habilitados."),"pt-BR":("ativos","Mostra os idiomas de tradução ativados."),"fr":("actifs","Affiche les langues de traduction activées."),"de":("aktiv","Zeigt die aktuell aktivierten Übersetzungssprachen."),"ja":("有効","現在有効な翻訳言語を表示します。"),"ko":("활성","현재 활성화된 번역 언어를 표시합니다."),"zh-CN":("当前","显示当前启用的翻译语言。"),"ru":("активные","Показать включённые языки перевода."),"hi":("सक्रिय","वर्तमान में सक्षम अनुवाद भाषाएँ दिखाएँ।"),"id":("aktif","Tampilkan bahasa terjemahan yang sedang aktif.")},
    "languages":{"es":("idiomas","Muestra etiquetas de idioma comunes."),"pt-BR":("idiomas","Lista tags de idioma comuns."),"fr":("langues","Affiche les balises de langue courantes."),"de":("sprachen","Listet häufige Sprach-Tags auf."),"ja":("言語","よく使われる言語タグを表示します。"),"ko":("언어","일반적인 언어 태그를 표시합니다."),"zh-CN":("语言","列出常用语言标签。"),"ru":("языки","Показать распространённые языковые теги."),"hi":("भाषाएँ","सामान्य भाषा टैग दिखाएँ।"),"id":("bahasa","Tampilkan tag bahasa yang umum.")},
    "topup":{"es":("recargar","Muestra cómo añadir créditos a este servidor."),"pt-BR":("recarregar","Mostra como adicionar créditos a este servidor."),"fr":("recharger","Affiche comment ajouter des crédits à ce serveur."),"de":("aufladen","Zeigt, wie Credits zu diesem Server hinzugefügt werden."),"ja":("チャージ","このサーバーにクレジットを追加する方法を表示します。"),"ko":("충전","이 서버에 크레딧을 추가하는 방법을 표시합니다."),"zh-CN":("充值","显示如何为此服务器添加点数。"),"ru":("пополнить","Показать, как добавить кредиты на сервер."),"hi":("रीचार्ज","इस सर्वर में क्रेडिट जोड़ने का तरीका दिखाएँ।"),"id":("isiulang","Tampilkan cara menambah kredit ke server ini.")},
    "balance":{"es":("saldo","Muestra los créditos restantes del servidor."),"pt-BR":("saldo","Mostra os créditos restantes do servidor."),"fr":("solde","Affiche les crédits restants du serveur."),"de":("guthaben","Zeigt die verbleibenden Credits des Servers."),"ja":("残高","サーバーの残りクレジットを表示します。"),"ko":("잔액","서버의 남은 크레딧을 표시합니다."),"zh-CN":("余额","显示服务器剩余点数。"),"ru":("баланс","Показать оставшиеся кредиты сервера."),"hi":("शेष","सर्वर के शेष क्रेडिट दिखाएँ।"),"id":("saldo","Tampilkan sisa kredit server.")},
    "usage":{"es":("uso","Muestra el uso de Voicely Translate del servidor."),"pt-BR":("uso","Mostra o uso do Voicely Translate no servidor."),"fr":("utilisation","Affiche l'utilisation de Voicely Translate du serveur."),"de":("nutzung","Zeigt die Voicely-Translate-Nutzung des Servers."),"ja":("使用量","サーバーのVoicely Translate使用量を表示します。"),"ko":("사용량","서버의 Voicely Translate 사용량을 표시합니다."),"zh-CN":("用量","显示服务器的 Voicely Translate 使用量。"),"ru":("расход","Показать использование Voicely Translate на сервере."),"hi":("उपयोग","सर्वर का Voicely Translate उपयोग दिखाएँ।"),"id":("penggunaan","Tampilkan penggunaan Voicely Translate server.")},
    "timeout":{"es":("espera","Configura cuánto espera el bot antes de salir de un canal vacío."),"pt-BR":("espera","Define quanto o bot espera antes de sair de um canal vazio."),"fr":("délai","Définit le délai avant de quitter un salon vocal vide."),"de":("wartezeit","Legt fest, wie lange der Bot in einem leeren Kanal wartet."),"ja":("待機時間","空のボイスチャンネルから退出するまでの秒数を設定します。"),"ko":("대기시간","빈 음성 채널에서 나가기 전 대기 시간을 설정합니다."),"zh-CN":("超时","设置机器人离开空语音频道前的等待时间。"),"ru":("таймаут","Задать ожидание перед выходом из пустого канала."),"hi":("समयसीमा","खाली वॉइस चैनल छोड़ने से पहले प्रतीक्षा समय सेट करें।"),"id":("bataswaktu","Atur waktu tunggu sebelum bot keluar dari kanal kosong.")},
    "leave":{"es":("salir","Detén la traducción y sal del canal de voz."),"pt-BR":("sair","Pare de traduzir e saia do canal de voz."),"fr":("quitter","Arrêtez la traduction et quittez le salon vocal."),"de":("verlassen","Beendet die Übersetzung und verlässt den Sprachkanal."),"ja":("退出","翻訳を停止してボイスチャンネルから退出します。"),"ko":("나가기","번역을 중지하고 음성 채널에서 나갑니다."),"zh-CN":("离开","停止翻译并离开语音频道。"),"ru":("выйти","Остановить перевод и выйти из голосового канала."),"hi":("छोड़ें","अनुवाद रोकें और वॉइस चैनल छोड़ें।"),"id":("keluar","Hentikan penerjemahan dan keluar dari kanal suara.")},
}

def apply_command_localizations(tree: app_commands.CommandTree) -> None:
    locale_map = {
        "es": discord.Locale.spain_spanish, "pt-BR": discord.Locale.brazil_portuguese,
        "fr": discord.Locale.french, "de": discord.Locale.german,
        "ja": discord.Locale.japanese, "ko": discord.Locale.korean,
        "zh-CN": discord.Locale.chinese, "ru": discord.Locale.russian,
        "hi": discord.Locale.hindi, "id": discord.Locale.indonesian,
    }
    for command in tree.get_commands():
        data = COMMAND_LOCALIZATIONS.get(command.name)
        if data:
            command.name_localizations = {locale_map[k]: v[0] for k, v in data.items() if k in locale_map}
            command.description_localizations = {locale_map[k]: v[1] for k, v in data.items() if k in locale_map}

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
        apply_command_localizations(self.tree)

        synced_commands = await self.tree.sync()
        logger.info(
            f"[COMMANDS] Synced {len(synced_commands)} global slash command(s)."
        )

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
            tr(interaction, "server_only"),
            ephemeral=True,
        )
        return None

    session = sessions.get(interaction.guild_id)

    if session is None or session.closed:
        await interaction.response.send_message(
            tr(interaction, "no_session"),
            ephemeral=True,
        )
        return None

    return session


@bot.event
async def on_ready() -> None:
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")
    logger.info("------")



def localized_balance(interaction, available, trial, paid) -> str:
    l = BALANCE_LABELS[ui_language_from_locale(interaction.locale)]
    return f"**{l[0]}:** {format_credits(available)} {l[3]}\n**{l[1]}:** {format_credits(trial)} {l[3]}\n**{l[2]}:** {format_credits(paid)} {l[3]}\n*(100 {l[3]} = $1.00 USD)*"

def localized_usage(interaction, state) -> str:
    l = USAGE_LABELS[ui_language_from_locale(interaction.locale)]
    vals = [int(state["total_used_microusd"]), int(state["transcription_used_microusd"]), int(state["translation_used_microusd"]), int(state["total_purchased_microusd"])]
    return "\n".join([f"**{l[i]}:** {format_credits(vals[i])} {l[4]}" for i in range(4)]) + f"\n*(100 {l[4]} = $1.00 USD)*"

class TranslationCommands(commands.Cog):
    def __init__(self, bot_instance: commands.Bot):
        self.bot = bot_instance

    @app_commands.command(
        name="join",
        description="Join your voice channel and start translating.",
    )
    @app_commands.describe(
        languages=(
            "Optional comma-separated language tags; "
            "uses the server defaults when omitted"
        )
    )
    async def join(
        self,
        interaction: discord.Interaction,
        languages: str | None = None,
    ) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message(
                tr(interaction, "server_only"),
                ephemeral=True,
            )
            return

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                tr(interaction, "unknown_voice"),
                ephemeral=True,
            )
            return

        if member.voice is None or member.voice.channel is None:
            await interaction.response.send_message(
                tr(interaction, "need_voice"),
                ephemeral=True,
            )
            return

        voice_channel = member.voice.channel

        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.response.send_message(
                tr(interaction, "normal_voice"),
                ephemeral=True,
            )
            return

        await sync_kofi_topups_safely(interaction.guild_id, "join")

        if not await asyncio.to_thread(
            has_available_credit, interaction.guild_id
        ):
            message_key = (
                "no_credit"
                if has_ever_purchased_credit(interaction.guild_id)
                else "trial_exhausted_join"
            )

            await interaction.response.send_message(
                tr(interaction, message_key),
                ephemeral=True,
            )
            return

        if languages is None or not languages.strip():
            requested_languages = await asyncio.to_thread(
                get_default_languages, interaction.guild_id
            )

            if not requested_languages:
                await interaction.response.send_message(
                    tr(interaction, "no_default_languages"),
                    ephemeral=True,
                )
                return
        else:
            requested_languages = parse_languages(languages)

            if not requested_languages:
                await interaction.response.send_message(
                    tr(interaction, "provide_language"),
                    ephemeral=True,
                )
                return

        existing = sessions.get(interaction.guild_id)

        if existing is not None and not existing.closed:
            await interaction.response.send_message(
                tr(interaction, "already_translating", channel=existing.voice_channel.name),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

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

            logger.info(
                f"[VOICE] Translation session active in {voice_channel.name} "
                f"({voice_channel.id})."
            )

            session.update_idle_timeout()

            languages_text = "`, `".join(requested_languages)

            join_message = tr(
                interaction,
                "join",
                channel=voice_channel.name,
                languages=f"`{languages_text}`",
            )

            show_trial_notice = await asyncio.to_thread(
                should_show_trial_notice, interaction.guild_id
            )

            if show_trial_notice:
                join_message += (
                    "\n\n"
                    + tr(interaction, "trial_notice")
                    + "\n-# "
                    + tr(interaction, "trial_notice_once")
                )

            voicely_text_bot_id = 1290741552158609419
            voicely_text_member = interaction.guild.get_member(
                voicely_text_bot_id
            )

            # get_member() only checks discord.py's local member cache.
            # If Voicely Text is not cached, confirm through Discord's API
            # before deciding that the bot is not installed.
            if voicely_text_member is None:
                try:
                    voicely_text_member = await interaction.guild.fetch_member(
                        voicely_text_bot_id
                    )
                except discord.NotFound:
                    voicely_text_member = None
                except discord.HTTPException as error:
                    # If Discord cannot complete the lookup, avoid incorrectly
                    # advertising Voicely Text as missing.
                    logger.info(
                        f"[VOICE] Could not verify whether Voicely Text is "
                        f"installed in guild {interaction.guild_id}: {error!r}"
                    )
                    voicely_text_member = None

            if voicely_text_member is None:
                join_message += "\n\n" + tr(interaction, "voicely_text")

            await interaction.followup.send(
                join_message,
                ephemeral=False,
            )

            if show_trial_notice:
                await asyncio.to_thread(
                    mark_trial_notice_shown, interaction.guild_id
                )

        except Exception as error:
            logger.exception(
                f"[VOICE COMMAND ERROR] /join failed in guild "
                f"{interaction.guild_id}, channel {voice_channel.id}: "
                f"{error!r}"
            )

            await interaction.followup.send(
                tr(interaction, "join_failed", error=error),
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
                tr(interaction, "provide_language"),
                ephemeral=True,
            )
            return

        added = session.add_languages(requested)

        if not added:
            await interaction.response.send_message(
                tr(interaction, "already_enabled"),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            tr(interaction, "added", languages=", ".join(added)),
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
                tr(interaction, "provide_language"),
                ephemeral=True,
            )
            return

        removed = session.remove_languages(requested)

        if not removed:
            await interaction.response.send_message(
                tr(interaction, "none_requested_enabled"),
                ephemeral=True,
            )
            return

        if session.languages:
            remaining = ", ".join(session.languages)
            extra = "\n" + tr(interaction, "still_enabled", languages=remaining)
        else:
            extra = "\n" + tr(interaction, "none_enabled")

        await interaction.response.send_message(
            tr(interaction, "removed", languages=", ".join(removed)) + extra,
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
            text = tr(interaction, "none_enabled")
        else:
            text = tr(interaction, "active", languages=", ".join(session.languages))

        await interaction.response.send_message(
            text,
            ephemeral=False,
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
            tr(interaction, "languages_heading"),
            tr(interaction, "languages_intro"),
            tr(interaction, "languages_not_limited"),
            "",
        ]

        for tag, name in LANGUAGE_TAGS.items():
            lines.append(f"`{tag}` — {name}")

        lines.extend([
            "",
            tr(interaction, "regional_tags_heading"),
        ])

        for tag, name in REGIONAL_LANGUAGE_TAGS.items():
            lines.append(f"`{tag}` — {name}")

        lines.extend([
            "",
            tr(interaction, "languages_try_other"),
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
        name="topup",
        description="Show how to add Voicely Translate credit to this server.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def topup(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                tr(interaction, "server_only"),
                ephemeral=True,
            )
            return

        code = await asyncio.to_thread(
            get_or_create_topup_code, interaction.guild_id
        )

        if not KOFI_WORKER_URL or not KOFI_BOT_API_SECRET:
            await interaction.response.send_message(
                tr(interaction, "topup_not_configured", code=code),
                ephemeral=True,
            )
            return

        try:
            await register_topup_code(interaction.guild_id, code)
            await sync_kofi_topups(interaction.guild_id)
        except Exception as error:
            logger.exception(
                f"[KOFI] /topup registration/sync failed for guild "
                f"{interaction.guild_id}: {error!r}"
            )

            await interaction.response.send_message(
                tr(interaction, "topup_service_error"),
                ephemeral=True,
            )
            return

        lines = [
            tr(interaction, "topup_heading"),
            tr(interaction, "topup_code", code=code),
            "",
            tr(interaction, "topup_include_code"),
            tr(interaction, "topup_rate"),
            "",
            tr(interaction, "topup_separate_order"),
        ]

        if KOFI_URL:
            lines.extend([
                "",
                f"Ko-fi: {KOFI_URL}",
            ])

        lines.extend([
            "",
            tr(interaction, "topup_after_payment"),
        ])

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
        )

    @app_commands.command(
        name="balance",
        description="Show this server's remaining Voicely Translate credit.",
    )
    async def balance(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                tr(interaction, "server_only"),
                ephemeral=True,
            )
            return

        await sync_kofi_topups_safely(interaction.guild_id, "balance")

        state = await asyncio.to_thread(
            get_credit_state, interaction.guild_id
        )
        trial = int(state["trial_balance_microusd"])
        paid = int(state["paid_balance_microusd"])
        available = max(0, trial + paid)

        await interaction.response.send_message(
            localized_balance(interaction, available, trial, paid),
            ephemeral=True,
        )

    @app_commands.command(
        name="usage",
        description="Show this server's Voicely Translate usage.",
    )
    async def usage(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                tr(interaction, "server_only"),
                ephemeral=True,
            )
            return

        await sync_kofi_topups_safely(interaction.guild_id, "usage")

        state = await asyncio.to_thread(
            get_credit_state, interaction.guild_id
        )

        await interaction.response.send_message(
            localized_usage(interaction, state),
            ephemeral=True,
        )

    @app_commands.command(
        name="defaultlanguages",
        description="Set the languages used by /join when none are specified.",
    )
    @app_commands.describe(
        languages="Comma-separated language tags, e.g. en, ja, es, pt-BR"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def defaultlanguages(
        self,
        interaction: discord.Interaction,
        languages: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                tr(interaction, "server_only"),
                ephemeral=True,
            )
            return

        requested_languages = parse_languages(languages)

        if not requested_languages:
            await interaction.response.send_message(
                tr(interaction, "provide_language"),
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            set_default_languages,
            interaction.guild_id,
            requested_languages,
        )

        await interaction.response.send_message(
            tr(
                interaction,
                "default_languages_set",
                languages=", ".join(requested_languages),
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="timeout",
        description="Set how many seconds the bot waits before leaving an empty voice channel.",
    )
    @app_commands.describe(
        seconds="Seconds to wait before leaving an empty voice channel"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def timeout(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 1, 86400],
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                tr(interaction, "server_only"),
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            set_idle_timeout_seconds,
            interaction.guild_id,
            int(seconds),
        )

        session = sessions.get(interaction.guild_id)

        if session is not None and not session.closed:
            session.cancel_idle_timeout()
            session.update_idle_timeout()

        await interaction.response.send_message(
            tr(interaction, "timeout_set", seconds=seconds),
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

        await interaction.response.defer(ephemeral=False)

        guild_id = interaction.guild_id

        await session.close()

        if guild_id is not None:
            sessions.pop(guild_id, None)

        await interaction.followup.send(
            tr(interaction, "left"),
            ephemeral=False,
        )


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    guild_id = member.guild.id
    session = sessions.get(guild_id)

    if bot.user is not None and member.id == bot.user.id:
        if before.channel is not None and after.channel is None:
            logger.info(
                f"[VOICE ERROR] Bot was disconnected from voice in guild "
                f"{member.guild.id} ({member.guild.name}); previous channel="
                f"{before.channel.id} ({before.channel.name})."
            )

            session = sessions.pop(guild_id, None)

            if session is not None and not session.closed:
                session.closed = True
                session.cancel_idle_timeout()

                if session.buffer_task:
                    session.buffer_task.cancel()

                logger.info(
                    f"[VOICE] Translation session for guild {guild_id} "
                    "was cleaned up after the unexpected voice disconnect."
                )

        return

    if session is None or session.closed:
        return

    translated_channel_id = session.voice_channel.id

    touched_translated_channel = (
        (
            before.channel is not None
            and before.channel.id == translated_channel_id
        )
        or (
            after.channel is not None
            and after.channel.id == translated_channel_id
        )
    )

    if touched_translated_channel:
        session.update_idle_timeout()


async def main() -> None:
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())



