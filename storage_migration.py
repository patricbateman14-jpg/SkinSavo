"""Verified, resumable SQLite -> PostgreSQL cutover without replacing source data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import os
import tempfile
import uuid
from datetime import datetime, timezone
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from storage import StorageUnavailable, sqlite_connection

TABLES = (
    "users",
    "skins",
    "balance_events",
    "inventory",
    "bot_sessions",
    "support_tickets",
    "telegram_updates",
)
KEYS = {name: "id" for name in TABLES} | {
    "users": "telegram_id",
    "bot_sessions": "telegram_id",
    "telegram_updates": "update_id",
}
MONEY = {
    "users": {"balance"},
    "skins": {"price"},
    "balance_events": {"amount"},
    "inventory": {"price"},
}
DATES = {"created_at", "last_login_at", "answered_at", "processed_at"}


class MigrationError(StorageUnavailable):
    pass


def converted(column, value, table):
    if value is None:
        return None
    if column in MONEY.get(table, ()):
        result = Decimal(str(value))
        if not result.is_finite():
            raise MigrationError("Source contains an invalid money value")
        return result
    if column in DATES:
        try:
            result = (
                value if isinstance(value, datetime) else datetime.fromisoformat(value)
            )
        except (ValueError, TypeError):
            raise MigrationError("Source contains an invalid timestamp") from None
        return (
            result.replace(tzinfo=timezone.utc)
            if result.tzinfo is None
            else result.astimezone(timezone.utc)
        )
    return value


def canonical(row, table):
    result = {}
    for column in sorted(row.keys()):
        value = converted(column, row[column], table)
        if isinstance(value, Decimal):
            value = format(value.normalize(), "f") if value else "0"
        elif isinstance(value, datetime):
            value = value.astimezone(timezone.utc).isoformat(timespec="microseconds")
        result[column] = value
    return json.dumps(
        result, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()


def digest(rows, table):
    total, checksum = 0, hashlib.sha256()
    for row in rows:
        encoded = canonical(dict(row), table)
        checksum.update(len(encoded).to_bytes(8, "big"))
        checksum.update(encoded)
        total += 1
    return total, checksum.hexdigest()


def source_metadata(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise MigrationError(
            "Existing SQLite source is missing; refusing an empty cutover"
        )
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        try:
            metadata = dict(source.execute("SELECT key,value FROM storage_meta"))
        except sqlite3.OperationalError:
            raise MigrationError(
                "Deploy the SQLite compatibility version before switching DATABASE_BACKEND"
            ) from None
    if metadata.get("adapter_version") != "1" or not metadata.get("source_id"):
        raise MigrationError("SQLite compatibility preparation has not completed")
    uuid.UUID(metadata["source_id"])
    return metadata


def freeze_and_backup(path, target):
    path = Path(path).resolve()
    metadata = source_metadata(path)
    fingerprint = target.fingerprint()
    with sqlite_connection(path, allow_frozen=True) as source:
        current = {
            row["key"]: row["value"]
            for row in source.execute("SELECT key,value FROM storage_meta")
        }
        existing = source.execute(
            "SELECT value FROM storage_meta WHERE key='target'"
        ).fetchone()
        if existing and existing["value"] != fingerprint:
            raise MigrationError("Source is reserved for another migration target")
        source.execute(
            "INSERT INTO storage_meta(key,value) VALUES ('target',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (fingerprint,),
        )
        source.execute(
            "INSERT INTO storage_meta(key,value) VALUES ('frozen','1') ON CONFLICT(key) DO UPDATE SET value='1'"
        )
        generation = (
            current.get("snapshot_id") if current.get("frozen") == "1" else None
        )
        generation = str(uuid.UUID(generation)) if generation else str(uuid.uuid4())
        source.execute(
            "INSERT INTO storage_meta(key,value) VALUES ('snapshot_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (generation,),
        )
    backup = path.with_name(path.stem + ".pre-supabase-" + generation + ".db")
    if not backup.exists():
        # A same-volume backup is retained independently of the target transaction.
        # The source is frozen before snapshotting, including already-open writers.
        with tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".migration-tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with closing(
                sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            ) as source:
                with closing(sqlite3.connect(temporary_path)) as destination:
                    source.backup(destination)
            os.replace(temporary_path, backup)
        finally:
            temporary_path.unlink(missing_ok=True)
    with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as snapshot:
        if (
            snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or snapshot.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise MigrationError("SQLite snapshot integrity verification failed")
        snapshot_meta = dict(snapshot.execute("SELECT key,value FROM storage_meta"))
        if (
            snapshot_meta.get("source_id") != metadata["source_id"]
            or snapshot_meta.get("frozen") != "1"
            or snapshot_meta.get("snapshot_id") != generation
        ):
            raise MigrationError("Snapshot metadata does not match the frozen source")
    return backup, metadata["source_id"]


def target_order(table):
    key = KEYS[table]
    return key + ' COLLATE "C"' if key == "telegram_id" else key


def import_snapshot(snapshot_path, target):
    counts, checksums = {}, {}
    with closing(
        sqlite3.connect(Path(snapshot_path).as_uri() + "?mode=ro", uri=True)
    ) as source:
        source.row_factory = sqlite3.Row
        for table in TABLES:
            columns = [
                row["name"] for row in source.execute(f"PRAGMA table_info({table})")
            ]
            expected = {
                row["column_name"]
                for row in target.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?",
                    ("skinsavo", table),
                )
            }
            if not columns or set(columns) != expected:
                raise MigrationError(
                    f"Schema mismatch in {table}; refusing to omit columns"
                )
            cursor = source.execute(f"SELECT * FROM {table} ORDER BY {KEYS[table]}")
            while batch := cursor.fetchmany(200):
                group = "(" + ",".join("?" for _ in columns) + ")"
                query = f'INSERT INTO {table} ({",".join(columns)}) VALUES ' + ",".join(
                    group for _ in batch
                )
                values = tuple(
                    converted(column, row[column], table)
                    for row in batch
                    for column in columns
                )
                target.execute(query, values)
            original = digest(
                source.execute(f"SELECT * FROM {table} ORDER BY {KEYS[table]}"), table
            )
            copied = digest(
                target.execute(f"SELECT * FROM {table} ORDER BY {target_order(table)}"),
                table,
            )
            if original != copied:
                raise MigrationError(f"Copy verification failed in {table}")
            counts[table], checksums[table] = original
            if KEYS[table] == "id":
                previous = source.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name=?", (table,)
                ).fetchone()
                maximum = (
                    target.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0] or 0
                )
                sequence = max(maximum, previous[0] if previous else 0)
                target.execute(
                    "SELECT setval(pg_get_serial_sequence(?,'id'),?,?)",
                    (f"skinsavo.{table}", max(sequence, 1), sequence > 0),
                )
    checksum = hashlib.sha256(
        json.dumps(checksums, sort_keys=True).encode()
    ).hexdigest()
    return counts, checksum


def migrate_to_postgres(database, source_path=None):
    database.init_postgres_schema()
    with database.postgres_connection() as target:
        target.execute("SELECT pg_advisory_xact_lock(?)", (8246173922,))
        existing = target.execute("SELECT * FROM storage_migrations LIMIT 1").fetchone()
        if existing:
            return {
                "already_migrated": True,
                "counts": json.loads(existing["row_counts"]),
            }
        for table in TABLES:
            if target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                raise MigrationError(
                    "Target contains data without a completed migration; refusing to merge accounts"
                )
        backup, source_id = freeze_and_backup(source_path or database.path(), database)
        counts, checksum = import_snapshot(backup, target)
        target.execute(
            "INSERT INTO storage_migrations(source_id,fingerprint,row_counts) VALUES (?,?,?)",
            (source_id, checksum, json.dumps(counts, sort_keys=True)),
        )
    return {"already_migrated": False, "counts": counts}


def abort_uncommitted_migration(database, source_path=None):
    # Never thaw SQLite if PostgreSQL may already have accepted new application writes.
    with database.postgres_connection() as target:
        target.execute("SELECT pg_advisory_xact_lock(?)", (8246173922,))
        if target.execute("SELECT 1 FROM storage_migrations LIMIT 1").fetchone():
            raise MigrationError(
                "Cutover already committed; SQLite cannot be re-enabled"
            )
        if any(
            target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        ):
            raise MigrationError("Target is not empty; cannot safely abort")
        path = source_path or database.path()
        metadata = source_metadata(path)
        if metadata.get("target") not in (None, database.fingerprint()):
            raise MigrationError("Source belongs to another target")
        with sqlite_connection(path, allow_frozen=True) as source:
            source.execute(
                "DELETE FROM storage_meta WHERE key IN ('frozen','target','snapshot_id')"
            )
