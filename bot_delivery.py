"""Durable webhook inbox: independent chats run concurrently, each chat stays ordered."""

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
    MAX_IN_FLIGHT = 4

    def __init__(self, connect, dispatcher, bot):
        self.connect, self.dispatcher, self.bot = connect, dispatcher, bot
        self.wake = asyncio.Event()
        self.task = None

    def enqueue(self, payload):
        with self.connect() as conn:
            event = payload.get("callback_query") or payload.get("message") or {}
            owner = str(
                event.get("from", {}).get("id", "update:" + str(payload["update_id"]))
            )
            result = conn.execute(
                "INSERT INTO telegram_updates(update_id,payload,owner_id) "
                "SELECT ?,?,? WHERE (SELECT COUNT(*) FROM telegram_updates "
                "WHERE status IN ('pending','processing')) < 10000 "
                "ON CONFLICT(update_id) DO NOTHING RETURNING update_id",
                (
                    payload["update_id"],
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    owner,
                ),
            )
            if result.fetchone():
                return True
            # A duplicate still succeeds when the queue is full. Only new
            # updates are rejected so Telegram can redeliver them later.
            if conn.execute("SELECT 1 FROM telegram_updates WHERE update_id=?", (payload["update_id"],)).fetchone():
                return False
            raise OverflowError("Inbox full")

    def claim(self):
        now = time.time()
        with self.connect() as conn:
            if conn.postgres:
                # Claim in one server statement. The earlier-message check and
                # row locks prevent two workers from processing the same chat.
                row = conn.execute(
                    """WITH expired AS (
                        UPDATE telegram_updates SET status='failed'
                        WHERE status='processing' AND claimed_at<? AND attempts>=5
                        RETURNING update_id
                    ), candidate AS (
                        SELECT current.update_id FROM telegram_updates AS current
                        WHERE attempts<5 AND ((status='pending' AND available_at<=?)
                            OR (status='processing' AND claimed_at<?))
                        AND NOT EXISTS (
                            SELECT 1 FROM telegram_updates AS earlier
                            WHERE earlier.owner_id=current.owner_id AND earlier.update_id<current.update_id
                            AND earlier.status IN ('pending','processing')
                            AND earlier.update_id NOT IN (SELECT update_id FROM expired)
                        )
                        ORDER BY update_id LIMIT 1 FOR UPDATE OF current SKIP LOCKED
                    ) UPDATE telegram_updates AS claimed SET status='processing',
                        attempts=claimed.attempts+1, claimed_at=?
                    FROM candidate WHERE claimed.update_id=candidate.update_id RETURNING claimed.*""",
                    (now - 120, now, now - 120, now),
                ).fetchone()
                return dict(row) if row else None
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
        await self.process_claimed(row)
        return True

    async def process_claimed(self, row):
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

    async def handle_claimed(self, row):
        try:
            await self.process_claimed(row)
        except Exception as error:
            logger.warning("Bot inbox temporarily unavailable (%s)", type(error).__name__)
        finally:
            self.wake.set()

    async def run(self):
        pending = set()
        try:
            while True:
                self.wake.clear()
                pending = {task for task in pending if not task.done()}
                if len(pending) < self.MAX_IN_FLIGHT:
                    try:
                        row = await asyncio.to_thread(self.claim)
                    except Exception as error:
                        logger.warning("Bot inbox temporarily unavailable (%s)", type(error).__name__)
                        row = None
                    if row:
                        pending.add(asyncio.create_task(self.handle_claimed(row)))
                        continue
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), timeout=1)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    def start(self):
        self.task = asyncio.create_task(self.run(), name="skinsavo-bot-inbox")

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        await self.bot.session.close()
