"""Durability and binding checks for the inbox's single-operation transaction."""

import os
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import storage
from storage import Database, StorageUnavailable


class StatementTests(unittest.TestCase):
    def test_sqlite_rows_are_committed_and_statements_without_rows_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "statement.db")
            database = Database(lambda: path, lambda: "", lambda: "sqlite")
            self.assertEqual(database.execute_one("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)"), [])
            value = "O‘tkir's ? % skin"
            rows = database.execute_one("INSERT INTO sample VALUES (?, ?) RETURNING *", (1, value))
            self.assertEqual(rows[0]["value"], value)
            with closing(sqlite3.connect(path)) as independent:
                self.assertEqual(independent.execute("SELECT value FROM sample").fetchone()[0], value)
            self.assertEqual(database.execute_one("DELETE FROM sample WHERE id=?", (1,)), [])

    def test_uncertain_pipeline_commit_is_not_replayed_or_reused(self):
        database = Database(lambda: "unused", lambda: "unused", lambda: "postgres")
        raw = MagicMock()
        raw.pipeline.return_value.__exit__.side_effect = OSError("private connection detail")
        pool = MagicMock()
        pool.acquire.return_value = raw
        with patch.object(database, "pool", return_value=pool), patch.object(storage, "native_postgres", object()):
            with self.assertRaises(StorageUnavailable) as failure:
                database.execute_one("INSERT INTO sample VALUES (?)", (7,))
        self.assertNotIn("private", str(failure.exception))
        pool.acquire.assert_called_once()
        pool.release.assert_called_once_with(raw, True)
        raw.pipeline.assert_called_once()


TEST_URL = os.getenv("TEST_POSTGRES_URL", "")


@unittest.skipUnless(TEST_URL, "TEST_POSTGRES_URL is not configured")
class PostgresStatementTests(unittest.TestCase):
    def setUp(self):
        url = urlsplit(TEST_URL)
        if url.hostname not in ("localhost", "127.0.0.1", "::1") or url.path != "/skinsavo_test":
            raise RuntimeError("Statement integration tests require the dedicated localhost skinsavo_test database")
        self.database = Database(lambda: "unused", lambda: TEST_URL, lambda: "postgres")
        self.table = "statement_test_" + uuid.uuid4().hex
        with self.database.postgres_connection() as conn:
            conn.execute("CREATE SCHEMA IF NOT EXISTS skinsavo")
            conn.execute(f"CREATE TABLE {self.table}(id INTEGER PRIMARY KEY, value TEXT NOT NULL CHECK(value <> 'invalid'))")

    def tearDown(self):
        try:
            with self.database.postgres_connection() as conn:
                conn.execute(f"DROP TABLE {self.table}")
        finally:
            self.database.close()

    def test_returning_is_committed_and_parameters_remain_data(self):
        value = "'); DROP TABLE skinsavo.users; -- ? % O‘tkir"
        rows = self.database.execute_one(
            f"INSERT INTO {self.table} VALUES (?, ?) RETURNING *, '?' AS literal_question",
            (1, value),
        )
        self.assertEqual(rows[0]["value"], value)
        self.assertEqual(rows[0]["literal_question"], "?")
        independent = Database(lambda: "unused", lambda: TEST_URL, lambda: "postgres")
        try:
            self.assertEqual(independent.execute_one(f"SELECT value FROM {self.table}")[0][0], value)
        finally:
            independent.close()
        self.assertEqual(self.database.execute_one(f"DELETE FROM {self.table} WHERE id=?", (1,)), [])
        self.assertEqual(self.database.execute_one(f"SELECT * FROM {self.table}"), [])

    def test_failed_statement_rolls_back_all_rows_and_next_borrow_recovers(self):
        with self.assertRaises(StorageUnavailable):
            self.database.execute_one(f"INSERT INTO {self.table} VALUES (1, ?), (2, ?)", ("valid", "invalid"))
        self.assertEqual(self.database.execute_one(f"SELECT COUNT(*) FROM {self.table}")[0][0], 0)
        self.assertEqual(self.database.execute_one(f"INSERT INTO {self.table} VALUES (3, ?) RETURNING id", ("next",))[0][0], 3)

    def test_transaction_settings_apply_to_statement_without_leaking(self):
        pool = self.database.pool()
        raw = pool.acquire()
        cursor = raw.cursor()
        cursor.execute("SET SESSION extra_float_digits=0")
        cursor.close()
        pool.release(raw)
        stamp = 1792912401.1234567
        row = self.database.execute_one(
            "SELECT current_schema() AS schema, current_setting('TimeZone') AS timezone, "
            "current_setting('extra_float_digits') AS digits, CAST(? AS double precision) AS stamp",
            (stamp,),
        )[0]
        self.assertEqual(row["schema"], "skinsavo")
        self.assertEqual(row["timezone"], "UTC")
        self.assertEqual(row["digits"], "3")
        self.assertEqual(row["stamp"], stamp)
        raw = pool.acquire()
        try:
            cursor = raw.cursor()
            cursor.execute("SHOW extra_float_digits")
            self.assertEqual(cursor.fetchone()[0], "0")
            cursor.close()
        finally:
            pool.release(raw)

    @unittest.skipUnless(storage.native_postgres, "Native PostgreSQL pipeline is Linux-only")
    def test_pipeline_has_one_protocol_sync_for_the_complete_transaction(self):
        pool = self.database.pool()
        raw = pool.acquire()
        with tempfile.TemporaryFile() as trace:
            raw.pgconn.trace(trace.fileno())
            pool.release(raw)
            try:
                rows = self.database.execute_one(
                    f"INSERT INTO {self.table} VALUES (?, ?) RETURNING id", (11, "single round trip")
                )
                self.assertEqual(rows[0][0], 11)
            finally:
                raw = pool.acquire()
                raw.pgconn.untrace()
                pool.release(raw)
            trace.seek(0)
            protocol = trace.read().decode("utf-8")
        self.assertEqual(sum(line.endswith("\tSync") for line in protocol.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
