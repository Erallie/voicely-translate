import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from voicely_storage import (
    apply_payment_event,
    get_or_create_topup_code,
    record_api_usage,
)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "test.db"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """CREATE TABLE guild_settings (
                guild_id INTEGER PRIMARY KEY, topup_code TEXT UNIQUE,
                paid_balance_microusd INTEGER NOT NULL DEFAULT 0,
                trial_balance_microusd INTEGER NOT NULL DEFAULT 100,
                total_purchased_microusd INTEGER NOT NULL DEFAULT 0,
                total_used_microusd INTEGER NOT NULL DEFAULT 0,
                transcription_used_microusd INTEGER NOT NULL DEFAULT 0,
                translation_used_microusd INTEGER NOT NULL DEFAULT 0)"""
            )
            connection.execute(
                """CREATE TABLE payment_events (
                message_id TEXT PRIMARY KEY, guild_id INTEGER NOT NULL,
                amount_microusd INTEGER NOT NULL)"""
            )
            connection.execute("INSERT INTO guild_settings (guild_id) VALUES (1)")
            connection.commit()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_duplicate_payment_is_applied_once(self):
        self.assertTrue(apply_payment_event(self.database, 1, "payment", 100))
        self.assertFalse(apply_payment_event(self.database, 1, "payment", 100))
        with closing(sqlite3.connect(self.database)) as connection:
            balance = connection.execute(
                "SELECT paid_balance_microusd FROM guild_settings WHERE guild_id=1"
            ).fetchone()[0]
        self.assertEqual(balance, 100)

    def test_concurrent_topup_creation_returns_one_canonical_code(self):
        counter = iter(range(100))
        def generate():
            return f"VT-{next(counter):06d}"
        with ThreadPoolExecutor(max_workers=8) as executor:
            codes = list(executor.map(
                lambda _: get_or_create_topup_code(self.database, 1, generate),
                range(16),
            ))
        self.assertEqual(len(set(codes)), 1)

    def test_concurrent_balance_depletion_never_goes_negative(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(
                lambda _: record_api_usage(self.database, 1, 30, 0),
                range(8),
            ))
        with closing(sqlite3.connect(self.database)) as connection:
            trial, paid, used = connection.execute(
                """SELECT trial_balance_microusd, paid_balance_microusd,
                total_used_microusd FROM guild_settings WHERE guild_id=1"""
            ).fetchone()
        self.assertEqual((trial, paid), (0, 0))
        self.assertEqual(used, 240)
