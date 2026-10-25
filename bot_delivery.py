"""Durable webhook inbox: acknowledge only after SQLite commits the update."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from contextlib import suppress

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Update

logger = logging.getLogger("skinsavo.bot")


def webhook_secret(token: str, configured: str = "") -> str:
    return (
        configured
        or hmac.new(
            token.encode(), b"SkinSavo Telegram webhook v1", hashlib.sha256
        ).hexdigest()
    )


def init_delivery_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS telegram_updates (
        update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        owner_id TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
        claimed_at REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, processed_at TEXT)""")
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(telegram_updates)")
    }
    if "owner_id" not in columns:
        conn.execute(
            "ALTER TABLE telegram_updates ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS telegram_pending ON telegram_updates(status, available_at, update_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS telegram_owner ON telegram_updates(owner_id, update_id, status)"
    )


class TelegramDelivery:
    def __init__(self, connect, dispatcher, bot):
        self.connect, self.dispatcher, self.bot = connect, dispatcher, bot
        self.wake = asyncio.Event()
        self.task = None

    def enqueue(self, payload):
        with self.connect() as conn:
            # Duplicates, including completed updates, never re-enter the inbox.
            if conn.execute(
                "SELECT 1 FROM telegram_updates WHERE update_id=?",
                (payload["update_id"],),
            ).fetchone():
                return False
            pending = conn.execute(
                "SELECT COUNT(*) FROM telegram_updates WHERE status IN ('pending','processing')"
            ).fetchone()[0]
            if pending >= 10000:
                raise OverflowError("Inbox full")
            event = payload.get("callback_query") or payload.get("message") or {}
            owner = str(
                event.get("from", {}).get("id", "update:" + str(payload["update_id"]))
            )
            result = conn.execute(
                "INSERT INTO telegram_updates(update_id,payload,owner_id) VALUES (?,?,?) ON CONFLICT(update_id) DO NOTHING",
                (
                    payload["update_id"],
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    owner,
                ),
            )
            return result.rowcount == 1

    def claim(self):
        now = time.time()
        with self.connect() as conn:
            conn.begin_write()
            conn.execute(
                "UPDATE telegram_updates SET status='failed' WHERE status='processing' AND claimed_at<? AND attempts>=5",
                (now - 120,),
            )
            # Recover interrupted processing after a process restart/expired lease.
            row = conn.select_for_update(
                """SELECT * FROM telegram_updates AS current WHERE attempts < 5 AND
                ((status='pending' AND available_at<=?) OR (status='processing' AND claimed_at<?))
                AND NOT EXISTS (SELECT 1 FROM telegram_updates AS earlier WHERE earlier.owner_id=current.owner_id
                    AND earlier.update_id<current.update_id AND earlier.status IN ('pending','processing'))
                ORDER BY update_id LIMIT 1""",
                (now, now - 120), skip_locked=True, of="current",
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE telegram_updates SET status='processing', attempts=attempts+1, claimed_at=? WHERE update_id=?",
                (now, row["update_id"]),
            )
            return {**dict(row), "attempts": row["attempts"] + 1}

    def finish(self, update_id):
        with self.connect() as conn:
            # Retain only deduplication metadata after success, not chat payloads.
            conn.execute(
                "UPDATE telegram_updates SET status='done',payload='',owner_id='',last_error='',processed_at=CURRENT_TIMESTAMP WHERE update_id=?",
                (update_id,),
            )

    def retry(self, row, error):
        delay = (
            max(1, error.retry_after)
            if isinstance(error, TelegramRetryAfter)
            else min(60, 2 ** row["attempts"])
        )
        with self.connect() as conn:
            conn.execute(
                "UPDATE telegram_updates SET status=?,available_at=?,last_error=? WHERE update_id=?",
                (
                    "failed" if row["attempts"] >= 5 else "pending",
                    time.time() + delay,
                    type(error).__name__,
                    row["update_id"],
                ),
            )
        logger.warning("Bot update processing deferred (%s)", type(error).__name__)

    async def process_once(self):
        row = await asyncio.to_thread(self.claim)
        if row is None:
            return False
        try:
            update = Update.model_validate(
                json.loads(row["payload"]), context={"bot": self.bot}
            )
            await asyncio.wait_for(
                self.dispatcher.feed_update(self.bot, update), timeout=45
            )
        except TelegramForbiddenError:
            # A user who blocked the bot must not cause an endless send retry.
            await asyncio.to_thread(self.finish, row["update_id"])
        except Exception as error:
            await asyncio.to_thread(self.retry, row, error)
        else:
            await asyncio.to_thread(self.finish, row["update_id"])
        return True

    async def run(self):
        while True:
            self.wake.clear()
            try:
                processed = await self.process_once()
            except Exception as error:
                logger.warning(
                    "Bot inbox temporarily unavailable (%s)", type(error).__name__
                )
                processed = False
            if processed:
                await asyncio.sleep(0.1)
            else:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), timeout=1)

    def start(self):
        self.task = asyncio.create_task(self.run(), name="skinsavo-bot-inbox")

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        await self.bot.session.close()
