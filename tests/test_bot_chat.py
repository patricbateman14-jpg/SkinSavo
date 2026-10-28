import asyncio
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, Update, User

import main
from bot_chat import BotChat, BotServices


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.failure = None

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if self.failure:
            error = self.failure(method)
            if error:
                raise error
        if method.__api_method__ == "getMe":
            return User(
                id=123456789,
                is_bot=True,
                first_name="SkinSavo",
                username="SkinSavoTestBot",
            )
        if method.__api_method__ in ("sendMessage", "editMessageText"):
            return Message.model_validate(
                {
                    "message_id": 900,
                    "date": int(time.time()),
                    "chat": {"id": method.chat_id, "type": "private"},
                    "text": method.text,
                },
                context={"bot": bot},
            )
        return True

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""


class BotChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main.DATABASE_BACKEND = 'sqlite'
        main.DATABASE_URL = ''
        self.temp = tempfile.TemporaryDirectory()
        main.DB_PATH = str(Path(self.temp.name) / "chat.db")
        main.WEBAPP_URL = "https://skinsavo.example/"
        main.ADMIN_TELEGRAM_ID = "777"
        main.init_db()
        self.chat = BotChat(
            BotServices(
                main.db,
                main.sync_telegram_profile,
                main.mini_app_launch_url,
                lambda: main.ADMIN_TELEGRAM_ID,
                lambda: main.WEBAPP_URL.startswith("https://"),
            )
        )
        self.dp = Dispatcher()
        self.dp.include_router(self.chat.router)
        self.session = RecordingSession()
        self.bot = Bot("123456789:test-only-chat-secret", session=self.session)
        self.seq = 0

    async def asyncTearDown(self):
        await self.bot.session.close()
        self.temp.cleanup()

    async def message(
        self, text, uid=101, chat_type="private", first_name="Aziz <b>", message_id=None
    ):
        self.seq += 1
        await self.dp.feed_update(
            self.bot,
            Update.model_validate(
                {
                    "update_id": self.seq,
                    "message": {
                        "message_id": message_id or self.seq,
                        "date": int(time.time()),
                        "chat": {"id": uid, "type": chat_type},
                        "from": {"id": uid, "first_name": first_name, "is_bot": False},
                        "text": text,
                    },
                }
            ),
        )

    async def callback(self, data, uid=101, chat_id=None, chat_type="private"):
        self.seq += 1
        await self.dp.feed_update(
            self.bot,
            Update.model_validate(
                {
                    "update_id": self.seq,
                    "callback_query": {
                        "id": str(self.seq),
                        "chat_instance": "test",
                        "from": {"id": uid, "first_name": "Aziz", "is_bot": False},
                        "data": data,
                        "message": {
                            "message_id": 900,
                            "date": int(time.time()),
                            "chat": {"id": chat_id or uid, "type": chat_type},
                            "text": "Old menu",
                        },
                    },
                }
            ),
        )

    def messages(self):
        return [
            call
            for call in self.session.calls
            if call.__api_method__ in ("sendMessage", "editMessageText")
        ]

    def last(self):
        return self.messages()[-1]

    def seed_skins(self):
        with main.db() as conn:
            for i in range(8):
                name = ("AWP" if i < 2 else "AK-47") + f" | Model {i}"
                conn.execute(
                    "INSERT INTO skins(name,weapon,skin,rarity,condition,price,stock,image,description) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        name,
                        name.split(" | ")[0],
                        f"Model {i}",
                        "Covert",
                        "Factory New",
                        10 + i,
                        3,
                        "https://example.com/image.png",
                        "Test skin",
                    ),
                )

    async def test_start_menu_signed_deep_links_and_preserved_balance(self):
        main.sync_telegram_profile({"id": 101, "first_name": "Old"})
        with main.db() as conn:
            conn.execute("UPDATE users SET balance=42 WHERE telegram_id='101'")
        await self.message("/start")
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("Aziz &lt;b&gt;", self.last().text)
        self.assertIn("Demo", self.last().text)
        self.assertEqual(len(self.last().reply_markup.inline_keyboard), 1)
        self.assertEqual(
            self.last().reply_markup.inline_keyboard[0][0].web_app.url,
            main.mini_app_launch_url(),
        )
        self.assertFalse(
            any(
                call.__api_method__ == "setChatMenuButton"
                for call in self.session.calls
            )
        )
        await self.callback("ss:profile")
        self.assertIn("$42.00", self.last().text)
        self.assertIn(
            "/profile?", self.last().reply_markup.inline_keyboard[0][0].web_app.url
        )

    async def test_start_shows_usable_menu_before_slow_profile_write_finishes(self):
        release_profile = asyncio.Event()
        menu_sent = asyncio.Event()
        original = self.chat.user

        async def delayed_profile(user):
            await release_profile.wait()
            return await original(user)

        def observe(method):
            if method.__api_method__ == 'sendMessage' and getattr(method.reply_markup, 'inline_keyboard', None):
                menu_sent.set()
            return None

        self.session.failure = observe
        with patch.object(self.chat, 'user', side_effect=delayed_profile):
            task = asyncio.create_task(self.message('/start'))
            try:
                await asyncio.wait_for(menu_sent.wait(), timeout=2)
                self.assertFalse(task.done())
                self.assertIn('Aziz &lt;b&gt;', self.last().text)
                self.assertTrue(self.last().reply_markup.inline_keyboard[0][0].web_app)
            finally:
                release_profile.set()
                await task
        with main.db() as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM users WHERE telegram_id='101'").fetchone())

    async def test_menu_replies_before_writes_but_waits_for_both_before_returning(self):
        for callback in (False, True):
            with self.subTest(callback=callback):
                release_profile = asyncio.Event()
                profile_finished = asyncio.Event()
                release_clear = threading.Event()
                menu_sent = asyncio.Event()
                original_user, original_clear = self.chat.user, self.chat.clear_mode
                self.chat.set_mode(101, "support")

                async def delayed_profile(user):
                    await release_profile.wait()
                    result = await original_user(user)
                    profile_finished.set()
                    return result

                def delayed_clear(uid):
                    if not release_clear.wait(timeout=5):
                        raise TimeoutError("Test did not release session write")
                    return original_clear(uid)

                def observe(method):
                    if method.__api_method__ in ("sendMessage", "editMessageText"):
                        menu_sent.set()

                self.session.failure = observe
                with patch.object(self.chat, "user", side_effect=delayed_profile), patch.object(
                    self.chat, "clear_mode", side_effect=delayed_clear
                ):
                    task = asyncio.create_task(
                        self.callback("ss:menu") if callback else self.message("/menu")
                    )
                    try:
                        await asyncio.wait_for(menu_sent.wait(), timeout=2)
                        self.assertTrue(self.last().reply_markup.inline_keyboard[0][0].web_app)
                        self.assertFalse(task.done())
                        release_profile.set()
                        await asyncio.wait_for(profile_finished.wait(), timeout=2)
                        self.assertFalse(task.done(), "Session persistence must still hold chat order")
                    finally:
                        release_profile.set()
                        release_clear.set()
                        await task
                self.assertEqual(self.chat.mode(101), {})

    async def test_text_reuses_profile_and_state_without_changing_support_greeting(self):
        with patch.object(self.chat, "user", wraps=self.chat.user) as sync, patch.object(
            self.chat, "mode", wraps=self.chat.mode
        ) as mode:
            await self.message("salom")
            sync.assert_awaited_once()
            mode.assert_called_once()
            self.assertIn("Ilovani oching", self.last().text)
        await self.message("/support")
        await self.message("salom")
        self.assertIn("Murojaat #1 saqlandi", self.last().text)
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT body FROM support_tickets").fetchone()[0], "salom")

    async def test_private_ownership_for_balance_inventory_history(self):
        self.seed_skins()
        for uid in (101, 202):
            main.sync_telegram_profile({"id": uid, "first_name": "User"})
        with main.db() as conn:
            conn.execute("UPDATE users SET balance=12 WHERE telegram_id='101'")
            conn.execute("UPDATE users SET balance=9999 WHERE telegram_id='202'")
            for uid, name in ((101, "My skin"), (202, "OTHER PRIVATE SKIN")):
                conn.execute(
                    "INSERT INTO inventory(telegram_id,skin_id,name,price) VALUES (?,?,?,?)",
                    (str(uid), 1, name, 25),
                )
                conn.execute(
                    "INSERT INTO balance_events(telegram_id,amount,event_type,note) VALUES (?,?,?,?)",
                    (str(uid), 25, "demo_topup", name),
                )
        await self.message("/balance")
        self.assertIn("$12.00", self.last().text)
        self.assertNotIn("9,999", self.last().text)
        for command in ("/inventory", "/history"):
            await self.message(command)
            self.assertIn("My skin", self.last().text)
            self.assertNotIn("OTHER PRIVATE", self.last().text)

    async def test_catalog_search_literal_filters_pagination_and_skin_links(self):
        self.seed_skins()
        await self.message("/skins")
        self.assertEqual(
            len(
                [
                    r
                    for r in self.last().reply_markup.inline_keyboard
                    if r[0].callback_data and r[0].callback_data.startswith("ss:item:")
                ]
            ),
            5,
        )
        await self.callback("ss:catalog:1")
        self.assertIn("Model 0", self.last().text)
        self.assertNotIn("Model 7", self.last().text)
        await self.message("/search AWP")
        self.assertIn("AWP", self.last().text)
        self.assertNotIn("AK-47", self.last().text)
        await self.callback("ss:item:1")
        self.assertIn(
            "/skins/1?", self.last().reply_markup.inline_keyboard[0][0].web_app.url
        )
        await self.message("/search %")
        self.assertIn("topilmadi", self.last().text)
        await self.callback("ss:item:99999")
        self.assertIn("katalogda yo‘q", self.last().text)

    async def test_natural_text_help_and_persistent_search(self):
        self.seed_skins()
        await self.message("salom")
        self.assertIn("SkinSavo", self.last().text)
        await self.message("Telegramda oching deyapti login")
        self.assertIn("Profil avtomatik", self.last().text)
        await self.message("Redline <test>")
        self.assertIn("Redline &lt;test&gt;", self.last().text)
        fresh = BotChat(self.chat.s)
        self.assertEqual(fresh.mode(101)["value"], "Redline <test>")
        await self.message("/help")
        self.assertIn("Yordam", self.last().text)

    async def test_support_persistence_validation_cancellation_and_duplicate_ticket(
        self,
    ):
        await self.message("/support")
        await self.message("abc")
        self.assertEqual(self.chat.mode(101)["mode"], "support")
        await self.message("Login ishlamayapti <script>", message_id=99)
        self.assertIn("#1", self.last().text)
        self.assertEqual(self.chat.save_ticket(101, 99, "Duplicate"), 1)
        await self.message("/tickets")
        self.assertIn("&lt;script&gt;", self.last().text)
        await self.message("/support")
        await self.message("/profile")
        self.assertEqual(self.chat.mode(101), {})
        await self.message("/support")
        await self.message("bekor")
        self.assertEqual(self.chat.mode(101), {})
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0], 1
            )

    async def test_support_ticket_private_and_admin_reply(self):
        await self.message("/support")
        await self.message("MY PRIVATE SUPPORT REQUEST")
        await self.callback("ss:ticket:1", uid=202)
        self.assertNotIn("MY PRIVATE", self.last().text)
        await self.message("/reply 1 Stolen reply", uid=202)
        self.assertIn("administrator", self.last().text)
        await self.message("/admin", uid=777)
        self.assertIn("Ochiq murojaatlar: 1", self.last().text)
        await self.message("/reply 1 Tekshirildi <ok>", uid=777)
        sent = [c for c in self.messages() if c.chat_id == 101 and "— javob" in c.text]
        self.assertEqual(len(sent), 1)
        self.assertIn("&lt;ok&gt;", sent[0].text)
        await self.message("/reply 1 Again", uid=777)
        self.assertIn("allaqachon", self.last().text)
        await self.callback("ss:ticket:1")
        self.assertIn("Tekshirildi &lt;ok&gt;", self.last().text)

    async def test_support_redelivery_after_receipt_failure_keeps_original_ticket(self):
        await self.message("/support")
        self.session.failure = lambda method: (
            RuntimeError("temporary send failure")
            if method.__api_method__ == "sendMessage" and "saqlandi" in method.text
            else None
        )
        with self.assertRaises(RuntimeError):
            await self.message("Login muammosini tekshiring", message_id=99)
        self.assertEqual(self.chat.mode(101), {})
        self.session.failure = None
        await self.message("Login muammosini tekshiring", message_id=99)
        self.assertIn("Murojaat #1 saqlandi", self.last().text)
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0], 1
            )

    async def test_blocked_customer_keeps_support_ticket_open(self):
        await self.message("/support")
        await self.message("Please check my profile")
        self.session.failure = lambda method: (
            TelegramForbiddenError(method=method, message="blocked")
            if method.__api_method__ == "sendMessage" and method.chat_id == 101
            else None
        )
        await self.message("/reply 1 Answer", uid=777)
        self.assertIn("ochiq qoldi", self.last().text)
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT status FROM support_tickets").fetchone()[0], "open"
            )

    async def test_groups_and_cross_chat_callbacks_do_not_reveal_accounts(self):
        await self.message("/start", uid=101, chat_type="group")
        self.assertEqual(self.messages(), [])
        await self.callback("ss:profile", uid=101, chat_id=202)
        self.assertEqual(self.messages(), [])
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0
            )

    async def test_old_and_expired_callbacks_and_missing_webapp(self):
        await self.callback("legacy-open")
        self.assertEqual(self.session.calls[-1].__api_method__, "answerCallbackQuery")
        self.session.failure = lambda method: (
            TelegramBadRequest(method=method, message="query is too old")
            if method.__api_method__ == "answerCallbackQuery"
            else None
        )
        await self.callback("ss:balance")
        self.assertIn("Demo balans", self.last().text)
        main.WEBAPP_URL = ""
        await self.message("/menu")
        self.assertTrue(
            all(
                not button.web_app
                for row in self.last().reply_markup.inline_keyboard
                for button in row
            )
        )

    async def test_flood_is_bounded_and_no_chat_payment_side_effects(self):
        for _ in range(20):
            await self.message("profil")
        self.assertLessEqual(len(self.messages()), 13)
        self.assertIn("tez kelyapti", self.last().text)
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT balance FROM users").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM balance_events").fetchone()[0], 0
            )


if __name__ == "__main__":
    unittest.main()
