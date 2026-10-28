"""Durable webhook inbox: independent chats run concurrently, each chat stays ordered."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from contextlib import suppress
from contextvars import ContextVar

from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Update

logger = logging.getLogger("uvicorn.error.skinsavo.bot")
logger.setLevel(logging.INFO)
reply_context = ContextVar("bot_reply_context", default=None)


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

    def __init__(self, connect, dispatcher, bot, *, execute_one=None, postgres=False):
        self.connect, self.dispatcher, self.bot = connect, dispatcher, bot
        self.execute_one = execute_one or self.transaction_statement
        self.postgres = postgres
        self.wake = asyncio.Event()
        self.task = None
        self.received = {}
        self.reply_count = 0
        self.last_reply_timing = None
        if bot and isinstance(bot.session, BaseSession):
            bot.session.middleware(self.measure_request)

    def transaction_statement(self, query, values=()):
        with self.connect() as conn:
            result = conn.execute(query, values)
            try:
                return result.fetchall() if result.cursor.description else []
            finally:
                result.cursor.close()

    async def accept(self, payload):
        started = time.monotonic()
        update_id = payload["update_id"]
        # Diagnostics must stay bounded even if a handler reaches its retry limit.
        if len(self.received) >= 10000:
            self.received.pop(next(iter(self.received)))
        timing = self.received.setdefault(update_id, {"received": started})
        try:
            inserted = await asyncio.to_thread(self.enqueue, payload)
        except BaseException:
            self.received.pop(update_id, None)
            raise
        if inserted:
            timing["enqueue_ms"] = round((time.monotonic() - started) * 1000)
        else:
            self.received.pop(update_id, None)
        self.wake.set()
        return inserted

    async def measure_request(self, make_request, bot, method):
        started = time.monotonic()
        result = await make_request(bot, method)
        timing = reply_context.get()
        if timing is not None and not timing.get("replied") and getattr(method, "chat_id", None) == timing.get("chat_id") and method.__api_method__ in (
            "sendMessage", "editMessageText", "sendPhoto",
        ):
            timing["replied"] = True
            now = time.monotonic()
            sample = {
                "handler_ms": round((now - timing["dispatched"]) * 1000),
                "telegram_api_ms": round((now - started) * 1000),
            }
            if "received" in timing:
                sample["webhook_to_reply_ms"] = round((now - timing["received"]) * 1000)
            if "enqueue_ms" in timing:
                sample["enqueue_ms"] = timing["enqueue_ms"]
            self.reply_count += 1
            self.last_reply_timing = sample
            # Durations only: no chat IDs, message bodies, tokens or URLs.
            logger.info("Bot first reply timing %s", json.dumps(sample, sort_keys=True))
        return result

    def enqueue(self, payload):
        event = payload.get("callback_query") or payload.get("message") or {}
        owner = str(
            event.get("from", {}).get("id", "update:" + str(payload["update_id"]))
        )
        rows = self.execute_one(
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
        if rows:
            return True
        # A duplicate still succeeds when the queue is full. Only new
        # updates are rejected so Telegram can redeliver them later.
        if self.execute_one("SELECT 1 FROM telegram_updates WHERE update_id=?", (payload["update_id"],)):
            return False
        raise OverflowError("Inbox full")

    def claim(self):
        now = time.time()
        if self.postgres:
            # Claim in one server statement. The earlier-message check and
            # row locks prevent two workers from processing the same chat.
            rows = self.execute_one(
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
            )
            return dict(rows[0]) if rows else None
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
        # Retain only deduplication metadata after success, not chat payloads.
        self.execute_one(
            "UPDATE telegram_updates SET status='done',payload='',owner_id='',last_error='',processed_at=CURRENT_TIMESTAMP WHERE update_id=?",
            (update_id,),
        )

    def retry(self, row, error):
        delay = (
            max(1, error.retry_after)
            if isinstance(error, TelegramRetryAfter)
            else min(60, 2 ** row["attempts"])
        )
        self.execute_one(
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
        timing = self.received.get(row["update_id"], {}).copy()
        timing["dispatched"] = time.monotonic()
        token = reply_context.set(timing)
        try:
            update = Update.model_validate(
                json.loads(row["payload"]), context={"bot": self.bot}
            )
            message = update.message or (update.callback_query.message if update.callback_query else None)
            timing["chat_id"] = message.chat.id if message else None
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
        finally:
            reply_context.reset(token)
            self.received.pop(row["update_id"], None)

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
