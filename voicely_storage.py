"""Atomic SQLite operations for guild billing state."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path


def get_or_create_topup_code(
    database_file: Path,
    guild_id: int,
    generate_code: Callable[[], str],
) -> str:
    with closing(sqlite3.connect(database_file, timeout=30)) as connection:
        while True:
            code = generate_code()
            try:
                connection.execute(
                    """UPDATE guild_settings SET topup_code = ?
                    WHERE guild_id = ? AND topup_code IS NULL""",
                    (code, guild_id),
                )
                connection.commit()
                row = connection.execute(
                    "SELECT topup_code FROM guild_settings WHERE guild_id = ?",
                    (guild_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Guild account disappeared")
                if row[0]:
                    return str(row[0])
            except sqlite3.IntegrityError:
                continue


def apply_payment_event(
    database_file: Path,
    guild_id: int,
    message_id: str,
    amount_microusd: int,
) -> bool:
    with closing(sqlite3.connect(database_file, timeout=30)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """INSERT OR IGNORE INTO payment_events
            (message_id, guild_id, amount_microusd) VALUES (?, ?, ?)""",
            (message_id, guild_id, amount_microusd),
        )
        if cursor.rowcount == 0:
            connection.rollback()
            return False
        connection.execute(
            """UPDATE guild_settings
            SET paid_balance_microusd = paid_balance_microusd + ?,
                total_purchased_microusd = total_purchased_microusd + ?
            WHERE guild_id = ?""",
            (amount_microusd, amount_microusd, guild_id),
        )
        connection.commit()
        return True


def record_api_usage(
    database_file: Path,
    guild_id: int,
    transcription_cost: int,
    translation_cost: int,
    unlimited: bool = False,
) -> None:
    """Atomically record usage and prevent concurrent negative balances."""
    transcription_cost = max(0, int(transcription_cost))
    translation_cost = max(0, int(translation_cost))
    total_cost = transcription_cost + translation_cost
    if total_cost == 0:
        return
    with closing(sqlite3.connect(database_file, timeout=30)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT trial_balance_microusd, paid_balance_microusd
            FROM guild_settings WHERE guild_id = ?""",
            (guild_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise RuntimeError("Guild account disappeared")
        trial_spend = paid_spend = 0
        if not unlimited:
            trial_spend = min(max(0, int(row[0])), total_cost)
            paid_spend = min(max(0, int(row[1])), total_cost - trial_spend)
        connection.execute(
            """UPDATE guild_settings SET
            trial_balance_microusd = trial_balance_microusd - ?,
            paid_balance_microusd = paid_balance_microusd - ?,
            total_used_microusd = total_used_microusd + ?,
            transcription_used_microusd = transcription_used_microusd + ?,
            translation_used_microusd = translation_used_microusd + ?
            WHERE guild_id = ?""",
            (trial_spend, paid_spend, total_cost, transcription_cost,
             translation_cost, guild_id),
        )
        connection.commit()
