"""Shared transactions for the API, bot and migration. Never falls back between stores."""

from __future__ import annotations

import hashlib
import queue
import re
import sqlite3
import ssl
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import pg8000.dbapi as postgres

if sys.platform == "win32":
    native_postgres = None  # Keep the 32-bit Windows development environment usable.
else:
    import psycopg as native_postgres

POSTGRES_DRIVER = "psycopg" if native_postgres else "pg8000"
POSTGRES_ERRORS = (postgres.Error,) + ((native_postgres.Error,) if native_postgres else ())

# pg8000 supports DB-API qmark bindings natively. This project is its only caller.
postgres.paramstyle = "qmark"


class StorageUnavailable(RuntimeError):
    pass


class StorageFrozen(StorageUnavailable):
    pass


class Record(dict):
    def __getitem__(self, key):
        return (
            list(self.values())[key]
            if isinstance(key, int)
            else super().__getitem__(key)
        )


class Result:
    def __init__(self, cursor, pg=False):
        self.cursor, self.postgres = cursor, pg

    def wrap(self, row):
        if self.postgres and row is not None:
            return Record(zip((column[0] for column in self.cursor.description), row))
        return row

    def fetchone(self):
        return self.wrap(self.cursor.fetchone())

    def fetchall(self):
        return [self.wrap(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (self.wrap(row) for row in self.cursor)

    @property
    def rowcount(self):
        return self.cursor.rowcount


class Connection:
    def __init__(self, raw, pg=False):
        self.raw, self.postgres = raw, pg

    def execute(self, query, values=()):
        if self.postgres:
            cursor = self.raw.cursor()
            if native_postgres and isinstance(self.raw, native_postgres.Connection):
                if values:
                    query, values = postgres.convert_paramstyle("qmark", query, values)
                    cursor.execute(query, values)
                else:
                    cursor.execute(query)
            else:
                cursor.execute(query, values)
        else:
            values = tuple(
                str(value) if isinstance(value, Decimal) else value for value in values
            )
            cursor = self.raw.execute(query, values)
        return Result(cursor, self.postgres)

    def begin_write(self):
        if not self.postgres and not self.raw.in_transaction:
            self.raw.execute("BEGIN IMMEDIATE")

    def select_for_update(self, query, values=(), *, skip_locked=False, of=None):
        if self.postgres:
            query += " FOR UPDATE"
            if of:
                if not re.fullmatch(r"[a-z_]+", of):
                    raise ValueError("Invalid lock target")
                query += " OF " + of
            if skip_locked:
                query += " SKIP LOCKED"
        return self.execute(query, values)


def prepare_sqlite_metadata(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS storage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO storage_meta(key,value) VALUES ('source_id',?) ON CONFLICT(key) DO NOTHING",
        (str(uuid.uuid4()),),
    )
    conn.execute(
        "INSERT INTO storage_meta(key,value) VALUES ('adapter_version','1') ON CONFLICT(key) DO NOTHING"
    )


@contextmanager
def sqlite_connection(path, *, allow_frozen=False):
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if (
            not allow_frozen
            and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='storage_meta'"
            ).fetchone()
        ):
            frozen = conn.execute(
                "SELECT value FROM storage_meta WHERE key='frozen'"
            ).fetchone()
            if frozen and frozen["value"] == "1":
                raise StorageFrozen("Database migration is in progress")
        yield Connection(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def connection_settings(value):
    try:
        url = urlsplit(value)
        if (
            url.scheme not in ("postgres", "postgresql")
            or not url.hostname
            or not url.username
        ):
            raise ValueError()
        query = dict(parse_qsl(url.query))
        mode = query.pop("sslmode", "require")
        timeout = max(1, min(60, int(query.pop("connect_timeout", "15"))))
        if query:
            raise ValueError()
        local = url.hostname in ("localhost", "127.0.0.1", "::1")
        if mode == "disable" and local:
            context = False
        elif mode in ("require", "verify-ca", "verify-full"):
            context = ssl.create_default_context()
            if mode == "require":
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
        else:
            raise ValueError()
        return dict(
            user=unquote(url.username),
            password=unquote(url.password or ""),
            host=url.hostname,
            port=url.port or 5432,
            database=unquote(url.path.lstrip("/")) or "postgres",
            ssl_context=context,
            timeout=timeout,
            application_name="skinsavo",
        )
    except Exception:
        raise StorageUnavailable(
            "Invalid PostgreSQL settings; external connections require TLS"
        ) from None


class PostgresPool:
    """Bounded, thread-safe pool with transaction cleanup and stale-socket checks."""

    def __init__(self, settings, size=5):
        self.settings, self.maximum = settings, size
        self.idle = queue.LifoQueue()
        self.lock = threading.Lock()
        self.count = 0
        self.closed = False

    def discard(self, conn):
        try:
            conn.close()
        except Exception:
            pass
        with self.lock:
            self.count -= 1

    def acquire(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.closed:
                raise StorageUnavailable("PostgreSQL pool is closed")
            try:
                idle_since, conn = self.idle.get_nowait()
            except queue.Empty:
                with self.lock:
                    create = self.count < self.maximum
                    if create:
                        self.count += 1
                if create:
                    try:
                        if native_postgres:
                            settings = dict(self.settings)
                            tls = settings.pop("ssl_context")
                            settings["dbname"] = settings.pop("database")
                            settings["connect_timeout"] = settings.pop("timeout")
                            settings["sslmode"] = (
                                "disable" if tls is False else "require" if tls.verify_mode == ssl.CERT_NONE
                                else "verify-full" if tls.check_hostname else "verify-ca"
                            )
                            if settings["sslmode"].startswith("verify-"):
                                settings["sslrootcert"] = "system"
                            conn = native_postgres.connect(
                                **settings, autocommit=True, prepare_threshold=None,
                                cursor_factory=native_postgres.RawCursor,
                            )
                        else:
                            conn = postgres.connect(**self.settings)
                        # Database opens each transaction explicitly together
                        # with its settings, avoiding a separate implicit BEGIN.
                        conn.autocommit = True
                        return conn
                    except Exception:
                        with self.lock:
                            self.count -= 1
                        raise StorageUnavailable(
                            "PostgreSQL connection is unavailable"
                        ) from None
                try:
                    idle_since, conn = self.idle.get(timeout=0.2)
                except queue.Empty:
                    continue
            # Recently used sockets were already checked by a completed
            # transaction. A ping on every borrow costs a remote round trip.
            if time.monotonic() - idle_since < 30:
                return conn
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                conn.rollback()
                cursor.close()
                return conn
            except Exception:
                self.discard(conn)
        raise StorageUnavailable("PostgreSQL connection pool is busy")

    def release(self, conn, broken=False):
        if broken or self.closed:
            self.discard(conn)
        else:
            self.idle.put((time.monotonic(), conn))

    def close(self):
        self.closed = True
        while True:
            try:
                _, conn = self.idle.get_nowait()
                self.discard(conn)
            except queue.Empty:
                break


class Database:
    def __init__(self, path, url, backend):
        self.path, self.url, self.backend = path, url, backend
        self._pool = None
        self._pool_url = None
        self._lock = threading.Lock()

    @property
    def is_postgres(self):
        name = self.backend()
        if name not in ("sqlite", "postgres"):
            raise StorageUnavailable("DATABASE_BACKEND must be sqlite or postgres")
        return name == "postgres"

    def pool(self):
        value = self.url()
        if not value:
            raise StorageUnavailable("DATABASE_URL is required for PostgreSQL")
        with self._lock:
            if self._pool is None or self._pool_url != value:
                if self._pool:
                    self._pool.close()
                self._pool = PostgresPool(connection_settings(value))
                self._pool_url = value
            return self._pool

    @contextmanager
    def postgres_connection(self):
        pool = self.pool()
        # Retry only setup on a stale pooled socket, before the caller can run
        # any business statement. Never replay purchases or other writes.
        for attempt in range(2):
            raw = pool.acquire()
            conn = Connection(raw, True)
            try:
                conn.execute(
                    "BEGIN; SET LOCAL search_path TO skinsavo, pg_catalog; "
                    "SET LOCAL TIME ZONE 'UTC'; SET LOCAL extra_float_digits=3; "
                    "SET LOCAL statement_timeout='60s'; SET LOCAL lock_timeout='10s'"
                )
                break
            except POSTGRES_ERRORS + (OSError, TimeoutError):
                pool.release(raw, broken=True)
                if attempt:
                    raise StorageUnavailable("PostgreSQL transaction is unavailable") from None
        broken = False
        try:
            yield conn
            conn.execute("COMMIT")
        except POSTGRES_ERRORS + (OSError, TimeoutError):
            broken = True
            raise StorageUnavailable("PostgreSQL transaction is unavailable") from None
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                broken = True
            raise
        finally:
            pool.release(raw, broken)

    def connection(self):
        return (
            self.postgres_connection()
            if self.is_postgres
            else sqlite_connection(self.path())
        )

    def close(self):
        with self._lock:
            if self._pool:
                self._pool.close()
            self._pool, self._pool_url = None, None

    def fingerprint(self):
        url = urlsplit(self.url())
        return hashlib.sha256(
            f"{url.username}@{url.hostname}:{url.port or 5432}/{url.path}".encode()
        ).hexdigest()

    def init_postgres_schema(self):
        script = (
            Path(__file__).parent / "supabase" / "migrations" / "20261025_storage.sql"
        ).read_text(encoding="utf-8")
        with self.postgres_connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(?)", (8246173921,))
            conn.execute(script)
