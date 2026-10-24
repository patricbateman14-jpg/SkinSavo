import asyncio
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import User

import main
from bot_delivery import TelegramDelivery, webhook_secret


class BotDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        main.DB_PATH = str(Path(self.temp.name) / "delivery.db")
        main.BOT_TOKEN = "123456789:delivery-test-only"
        main.WEBAPP_URL = "https://skinsavo.example/"
        main.TELEGRAM_WEBHOOK_SECRET = ""
        main.init_db()
        self.bot = AsyncMock()
        self.dp = AsyncMock()
        self.delivery = TelegramDelivery(main.db, self.dp, self.bot)
        main.app.state.telegram_delivery = self.delivery
        main.app.state.telegram_webhook_ready = True
        self.client = TestClient(main.app)
        self.headers = {
            "X-Telegram-Bot-Api-Secret-Token": webhook_secret(main.BOT_TOKEN)
        }
        self.payload = {
            "update_id": 123,
            "message": {
                "message_id": 1,
                "date": int(time.time()),
                "chat": {"id": 101, "type": "private"},
                "from": {"id": 101, "first_name": "Aziz", "is_bot": False},
                "text": "/start",
            },
        }

    async def asyncTearDown(self):
        self.client.close()
        await self.delivery.close()
        main.app.state.telegram_delivery = None
        main.app.state.telegram_webhook_ready = False
        self.temp.cleanup()

    def post(self, payload=None, headers=None):
        return self.client.post(
            "/telegram/webhook",
            json=self.payload if payload is None else payload,
            headers=self.headers if headers is None else headers,
        )

    def row(self):
        with main.db() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_updates ORDER BY update_id LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    async def test_webhook_requires_secret_before_accepting_any_identity(self):
        self.assertEqual(self.post(headers={}).status_code, 403)
        self.assertEqual(
            self.post(headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code,
            403,
        )
        self.assertEqual(
            self.post(
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": webhook_secret("other-token")
                }
            ).status_code,
            403,
        )
        self.assertIsNone(self.row())
        self.assertEqual(self.client.get("/api/users/101").status_code, 401)
        self.assertNotIn(
            webhook_secret(main.BOT_TOKEN), self.client.get("/api/health").text
        )

    async def test_webhook_validates_size_json_and_delivery_readiness(self):
        for payload in (
            [],
            {},
            {"update_id": True},
            {"update_id": -1},
            {"update_id": 2**63},
            {"update_id": 1, "message": {}},
        ):
            self.assertEqual(self.post(payload).status_code, 400)
        self.assertEqual(
            self.client.post(
                "/telegram/webhook",
                content=b"x" * (1024 * 1024 + 1),
                headers=self.headers,
            ).status_code,
            413,
        )
        main.app.state.telegram_webhook_ready = False
        self.assertEqual(self.post().status_code, 503)
        self.assertIsNone(self.row())

    async def test_duplicate_updates_commit_once_and_clear_payload_after_processing(
        self,
    ):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 200)
        await self.delivery.process_once()
        self.dp.feed_update.assert_awaited_once()
        self.assertEqual(self.row()["status"], "done")
        self.assertEqual(self.row()["payload"], "")
        self.assertEqual(self.post().status_code, 200)
        self.assertFalse(await self.delivery.process_once())
        self.dp.feed_update.assert_awaited_once()

    async def test_concurrent_duplicate_intake_has_one_queue_entry(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            inserted = list(
                executor.map(lambda _: self.delivery.enqueue(self.payload), range(8))
            )
        self.assertEqual(sum(inserted), 1)
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM telegram_updates").fetchone()[0], 1
            )

    async def test_network_retries_are_bounded_and_do_not_log_credentials(self):
        self.delivery.enqueue(self.payload)
        self.dp.feed_update.side_effect = RuntimeError(
            "private token must never be persisted"
        )
        for _ in range(5):
            await self.delivery.process_once()
            with main.db() as conn:
                conn.execute("UPDATE telegram_updates SET available_at=0")
        self.assertEqual(self.row()["attempts"], 5)
        self.assertEqual(self.row()["status"], "failed")
        self.assertEqual(self.row()["last_error"], "RuntimeError")
        self.assertFalse(await self.delivery.process_once())
        self.assertEqual(self.dp.feed_update.await_count, 5)

    async def test_retry_after_and_blocked_user(self):
        self.delivery.enqueue(self.payload)
        self.dp.feed_update.side_effect = TelegramRetryAfter(
            method=SendMessage(chat_id=101, text="test"),
            message="retry",
            retry_after=20,
        )
        await self.delivery.process_once()
        self.assertGreater(self.row()["available_at"], time.time() + 18)
        self.assertFalse(await self.delivery.process_once())
        with main.db() as conn:
            conn.execute("UPDATE telegram_updates SET available_at=0")
        self.dp.feed_update.side_effect = TelegramForbiddenError(
            method=SendMessage(chat_id=101, text="test"), message="blocked"
        )
        await self.delivery.process_once()
        self.assertEqual(self.row()["status"], "done")

    async def test_restart_recovers_pending_and_expired_processing_lease(self):
        self.delivery.enqueue(self.payload)
        restarted = TelegramDelivery(main.db, self.dp, self.bot)
        claimed = restarted.claim()
        self.assertEqual(claimed["update_id"], 123)
        self.assertIsNone(self.delivery.claim())
        with main.db() as conn:
            conn.execute(
                "UPDATE telegram_updates SET claimed_at=?", (time.time() - 121,)
            )
        await self.delivery.process_once()
        self.assertEqual(self.row()["attempts"], 2)
        self.assertEqual(self.row()["status"], "done")

    async def test_final_interrupted_attempt_is_not_left_processing_forever(self):
        self.delivery.enqueue(self.payload)
        with main.db() as conn:
            conn.execute(
                "UPDATE telegram_updates SET status='processing',attempts=5,claimed_at=?",
                (time.time() - 121,),
            )
        self.assertIsNone(self.delivery.claim())
        self.assertEqual(self.row()["status"], "failed")

    async def test_retry_keeps_each_chat_in_order_without_blocking_other_users(self):
        self.delivery.enqueue(self.payload)
        second = json.loads(json.dumps(self.payload))
        second["update_id"] = 124
        self.delivery.enqueue(second)
        other = json.loads(json.dumps(self.payload))
        other["update_id"] = 125
        other["message"]["from"]["id"] = 202
        other["message"]["chat"]["id"] = 202
        self.delivery.enqueue(other)
        with main.db() as conn:
            conn.execute(
                "UPDATE telegram_updates SET available_at=? WHERE update_id=123",
                (time.time() + 60,),
            )
        claimed = self.delivery.claim()
        self.assertEqual(claimed["update_id"], 125)
        self.assertIsNone(self.delivery.claim())
        self.delivery.finish(125)
        with main.db() as conn:
            conn.execute(
                "UPDATE telegram_updates SET available_at=0 WHERE update_id=123"
            )
        self.assertEqual(self.delivery.claim()["update_id"], 123)
        self.delivery.finish(123)
        self.assertEqual(self.delivery.claim()["update_id"], 124)

    async def test_startup_installs_commands_and_webhook_without_dropping_pending_updates(
        self,
    ):
        bot = AsyncMock()
        bot.__aenter__.return_value = bot
        bot.get_me.return_value = User(
            id=123456789, first_name="SkinSavo", username="SkinSavoTestBot", is_bot=True
        )
        with patch("main.Bot", return_value=bot), patch.object(
            TelegramDelivery, "start"
        ):
            await main.configure_telegram(main.app)
        bot.set_my_commands.assert_awaited_once()
        self.assertEqual(len(bot.set_my_commands.call_args.args[0]), 12)
        arguments = bot.set_webhook.call_args.kwargs
        self.assertEqual(arguments["url"], "https://skinsavo.example/telegram/webhook")
        self.assertFalse(arguments["drop_pending_updates"])
        self.assertEqual(arguments["allowed_updates"], ["message", "callback_query"])
        self.assertEqual(arguments["secret_token"], webhook_secret(main.BOT_TOKEN))
        self.assertTrue(main.app.state.telegram_webhook_ready)

    async def test_webhook_registration_failure_does_not_claim_chat_is_ready(self):
        bot = AsyncMock()
        bot.__aenter__.return_value = bot
        bot.get_me.return_value = User(
            id=123456789, first_name="SkinSavo", username="SkinSavoTestBot", is_bot=True
        )
        bot.set_webhook.side_effect = RuntimeError(
            "token in remote error must never be logged"
        )
        with patch("main.Bot", return_value=bot):
            await main.configure_telegram(main.app)
        self.assertFalse(main.app.state.telegram_webhook_ready)
        self.assertIsNone(main.app.state.telegram_delivery)

    async def test_cosmetic_menu_failure_does_not_disable_chat_delivery(self):
        bot = AsyncMock()
        bot.__aenter__.return_value = bot
        bot.get_me.return_value = User(
            id=123456789, first_name="SkinSavo", username="SkinSavoTestBot", is_bot=True
        )
        bot.set_chat_menu_button.side_effect = RuntimeError("temporary menu error")
        bot.set_my_commands.side_effect = RuntimeError("temporary commands error")
        with patch("main.Bot", return_value=bot), patch.object(
            TelegramDelivery, "start"
        ):
            await main.configure_telegram(main.app)
        bot.set_webhook.assert_awaited_once()
        self.assertTrue(main.app.state.telegram_webhook_ready)

    async def test_end_to_end_signed_webhook_to_real_dispatcher_and_reply(self):
        from aiogram import Bot, Dispatcher
        from bot_chat import BotChat, BotServices
        from test_bot_chat import RecordingSession

        session = RecordingSession()
        bot = Bot("123456789:delivery-test-only", session=session)
        dispatcher = Dispatcher()
        chat = BotChat(
            BotServices(
                main.db,
                main.sync_telegram_profile,
                main.mini_app_launch_url,
                lambda: main.ADMIN_TELEGRAM_ID,
                lambda: True,
            )
        )
        dispatcher.include_router(chat.router)
        self.delivery.bot = bot
        self.delivery.dispatcher = dispatcher
        self.assertEqual(self.post().status_code, 200)
        self.assertTrue(await self.delivery.process_once())
        replies = [
            call for call in session.calls if call.__api_method__ == "sendMessage"
        ]
        self.assertEqual(len(replies), 2)
        self.assertIn("Aziz", replies[-1].text)
        self.assertTrue(replies[-1].reply_markup.inline_keyboard[0][0].web_app)
        with main.db() as conn:
            user = dict(
                conn.execute("SELECT * FROM users WHERE telegram_id='101'").fetchone()
            )
        self.assertEqual(user["balance"], 0)
        self.assertEqual(self.row()["status"], "done")


if __name__ == "__main__":
    unittest.main()
