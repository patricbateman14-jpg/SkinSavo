"""Private-chat UI. Telegram identity is supplied only by the trusted update transport."""

from __future__ import annotations

import asyncio
import html
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton as Button,
    InlineKeyboardMarkup as Keyboard,
)
from aiogram.types import (
    LinkPreviewOptions,
    Message,
    ReplyKeyboardRemove,
    WebAppInfo,
)


def init_chat_tables(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bot_sessions (
        telegram_id TEXT PRIMARY KEY, mode TEXT NOT NULL, value TEXT NOT NULL DEFAULT '', expires_at REAL NOT NULL)"""
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT NOT NULL REFERENCES users(telegram_id),
        message_id INTEGER NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        reply TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        answered_at TEXT, UNIQUE(telegram_id, message_id))""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS support_owner ON support_tickets(telegram_id, id)"
    )


@dataclass
class BotServices:
    connect: Callable
    sync_profile: Callable
    launch_url: Callable
    admin_id: Callable
    web_ready: Callable


FAQ = {
    "login": (
        "🔑 Telegram orqali kirish",
        "Pastki <b>SkinSavo</b> menyusi yoki shu chatdagi <b>Ilovani ochish</b> tugmasini bosing. Profil avtomatik yaratiladi. Oddiy sayt havolasi loginni ishga tushirmaydi.",
    ),
    "demo": (
        "🧪 Demo rejim",
        "Balans, xarid va sotuv — sinov uchun. Haqiqiy pul olinmaydi, Steam orqali skin yuborilmaydi.",
    ),
    "buy": (
        "🛍 Skin olish",
        "Katalogdan skin tanlang, demo balansingizni to‘ldiring va ilovada xaridni tasdiqlang. Olingan skin inventaringizda ko‘rinadi.",
    ),
    "sell": (
        "🎒 Skin sotish",
        "Ilovadagi inventarni oching va o‘zingizga tegishli demo skinni tanlang. Demo sotuv uning xarid narxini balansga qaytaradi.",
    ),
}
COMMANDS = [
    ("start", "Bosh menyu"),
    ("skins", "Skinlar katalogi"),
    ("search", "Skin qidirish"),
    ("profile", "Mening profilim"),
    ("balance", "Demo balansim"),
    ("topup", "Balans to‘ldirish"),
    ("inventory", "Mening inventarim"),
    ("history", "Amallar tarixi"),
    ("support", "Murojaat yuborish"),
    ("tickets", "Mening murojaatlarim"),
    ("help", "Yordam"),
    ("cancel", "Amalni bekor qilish"),
]


class ChatThrottle(BaseMiddleware):
    def __init__(self):
        self.recent = OrderedDict()
        self.warned = {}

    async def __call__(self, handler, event, data):
        user = event.from_user
        if user:
            now = time.monotonic()
            times = self.recent.setdefault(user.id, deque())
            self.recent.move_to_end(user.id)
            while times and times[0] < now - 5:
                times.popleft()
            if len(self.recent) > 2000:
                old, _ = self.recent.popitem(last=False)
                self.warned.pop(old, None)
            if len(times) >= 12:
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("Bir oz kuting, so‘ng qayta bosing.")
                    except TelegramBadRequest:
                        pass
                elif now - self.warned.get(user.id, 0) >= 3:
                    self.warned[user.id] = now
                    await event.answer(
                        "Xabarlar juda tez kelyapti. Bir oz kutib qayta yuboring."
                    )
                return
            times.append(now)
        return await handler(event, data)


class BotChat:
    PAGE_SIZE = 5

    def __init__(self, services: BotServices):
        self.s = services
        self.router = Router(name="skinsavo-chat")
        self.router.message.filter(F.chat.type == "private")
        throttle = ChatThrottle()
        self.router.message.outer_middleware(throttle)
        self.router.callback_query.outer_middleware(throttle)
        self.router.message.register(self.start, CommandStart())
        for names, handler in [
            (("menu",), self.menu),
            (("profile",), self.profile),
            (("balance",), self.balance),
            (("inventory",), self.inventory),
            (("history",), self.history),
            (("skins", "catalog", "search"), self.search),
            (("help", "faq"), self.help),
            (("topup",), self.topup),
            (("support",), self.support),
            (("tickets",), self.tickets),
            (("cancel",), self.cancel),
            (("admin",), self.admin),
            (("reply",), self.reply),
        ]:
            self.router.message.register(handler, Command(*names))
        self.router.callback_query.register(self.callback, F.data.startswith("ss:"))
        # Old buttons get a useful response instead of an endless Telegram spinner.
        self.router.callback_query.register(self.old_callback)
        self.router.message.register(self.text)

    @staticmethod
    def private(message: Message) -> bool:
        return bool(
            message.chat.type == "private"
            and message.from_user
            and not message.from_user.is_bot
            and message.chat.id == message.from_user.id
        )

    def is_admin(self, uid) -> bool:
        return bool(self.s.admin_id() and str(uid) == self.s.admin_id())

    @staticmethod
    def cb(label, action):
        return Button(text=label, callback_data="ss:" + action)

    def web(self, label, path=None, params=None):
        if not self.s.web_ready():
            return self.cb(label, "unavailable")
        return Button(
            text=label, web_app=WebAppInfo(url=self.s.launch_url(path, params))
        )

    def keyboard(self, rows):
        return Keyboard(inline_keyboard=rows)

    def menu_keyboard(self, uid):
        rows = [
            [self.web("🎮 Ilovani ochish")],
        ]
        if self.is_admin(uid):
            rows.append([self.cb("⚙️ Administrator", "admin")])
        return self.keyboard(rows)

    def back_keyboard(self, *rows):
        return self.keyboard([*rows, [self.cb("🏠 Bosh menyu", "menu")]])

    async def show(self, target, text, keyboard):
        options = dict(
            reply_markup=keyboard,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        if isinstance(target, CallbackQuery):
            try:
                await target.message.edit_text(text, **options)
            except TelegramBadRequest as error:
                if "message is not modified" not in error.message.lower():
                    await target.message.answer(text, **options)
        else:
            await target.answer(text, **options)

    def set_mode(self, uid, mode, value=""):
        with self.s.connect() as conn:
            conn.execute(
                """INSERT INTO bot_sessions VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET mode=excluded.mode, value=excluded.value, expires_at=excluded.expires_at""",
                (str(uid), mode, value, time.time() + 1800),
            )

    def mode(self, uid):
        with self.s.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bot_sessions WHERE telegram_id=? AND expires_at>?",
                (str(uid), time.time()),
            ).fetchone()
        return dict(row) if row else {}

    def clear_mode(self, uid):
        with self.s.connect() as conn:
            conn.execute("DELETE FROM bot_sessions WHERE telegram_id=?", (str(uid),))

    async def user(self, user):
        return await asyncio.to_thread(
            self.s.sync_profile, user.model_dump(exclude_none=True), mini_app=False
        )

    async def start(self, message: Message, bot: Bot):
        if not self.private(message):
            return
        # The update transport already authenticated this name. Show the reply
        # before profile/session writes; the global Web App menu is set at startup.
        await message.answer("🎮 SkinSavo", reply_markup=ReplyKeyboardRemove())
        name = html.escape(message.from_user.first_name or "do‘stim")
        await self.show(
            message,
            f"<b>Salom, {name}!</b>\nCS2 skinlaringiz — ilovada.\n\n<i>Demo rejim · haqiqiy to‘lov yo‘q.</i>",
            self.menu_keyboard(message.from_user.id),
        )
        # Finish both before releasing this chat's queue position, so subsequent
        # commands see a persisted profile and the cleared conversation state.
        await asyncio.gather(
            self.user(message.from_user),
            asyncio.to_thread(self.clear_mode, message.from_user.id),
        )

    async def menu(self, message: Message, bot: Bot = None):
        if not self.private(message):
            return
        await self.user(message.from_user)
        await asyncio.to_thread(self.clear_mode, message.from_user.id)
        await self.show(
            message,
            "🎮 <b>SkinSavo</b>\nIlovani oching.",
            self.menu_keyboard(message.from_user.id),
        )

    async def view(self, target, user, section, page=0, *, profile=None):
        if profile is None:
            profile = await self.user(user)
        uid = str(user.id)
        if section not in ("support", "search"):
            mode = await asyncio.to_thread(self.mode, uid)
            if mode.get("mode") in ("support", "search"):
                await asyncio.to_thread(self.clear_mode, uid)
        if section == "menu":
            await asyncio.to_thread(self.clear_mode, uid)
            return await self.show(
                target,
                "🎮 <b>SkinSavo</b>\nIlovani oching.",
                self.menu_keyboard(uid),
            )
        if section == "profile":
            name = html.escape(
                " ".join(filter(None, [profile["first_name"], profile["last_name"]]))
                or "Foydalanuvchi"
            )
            handle = (
                "\n@" + html.escape(profile["username"]) if profile["username"] else ""
            )
            text = f"👤 <b>{name}</b>{handle}\nID: <code>{uid}</code>\nDemo balans: <b>${profile['balance']:,.2f}</b>"
            rows = [
                [self.web("👤 Profilni ochish", "/profile")],
                [
                    self.cb("🎒 Inventar", "inventory:0"),
                    self.cb("💰 Balans", "balance"),
                ],
            ]
        elif section in ("balance", "topup"):
            text = f"💰 <b>Demo balans: ${profile['balance']:,.2f}</b>\n\nSinov mablag‘i. Haqiqiy pul olinmaydi."
            rows = [
                [self.web("➕ Balans to‘ldirish", "/balance/topup")],
                [self.cb("🔄 Yangilash", "balance"), self.cb("📜 Tarix", "history:0")],
            ]
        elif section in ("inventory", "history", "tickets", "catalog"):
            return await self.list_view(target, user, section, page)
        elif section == "help":
            text = "❓ <b>Yordam</b>\nSkin nomini yozing yoki bo‘limni tanlang.\n\n/search AK-47 — qidirish\n/cancel — amalni bekor qilish"
            rows = [[self.cb(title, "faq:" + key)] for key, (title, _) in FAQ.items()]
            rows.append(
                [
                    self.cb("💬 Murojaat yuborish", "support"),
                    self.cb("📨 Murojaatlarim", "tickets:0"),
                ]
            )
        elif section == "support":
            await asyncio.to_thread(self.set_mode, uid, "support")
            text = "💬 <b>Murojaat</b>\nMuammoni bitta matnli xabarda yozing (5–1500 belgi).\n\nParol, bot tokeni yoki karta ma’lumotini yubormang."
            rows = [
                [
                    self.cb("📨 Murojaatlarim", "tickets:0"),
                    self.cb("Bekor qilish", "cancel"),
                ]
            ]
        elif section == "search":
            await asyncio.to_thread(self.set_mode, uid, "search")
            text = "🔎 <b>Qaysi skinni qidiramiz?</b>\nMasalan: <code>AK-47</code>, <code>AWP</code>, <code>Redline</code>."
            rows = [
                [
                    self.cb("Barcha skinlar", "catalog:0"),
                    self.cb("Bekor qilish", "cancel"),
                ]
            ]
        elif section == "admin":
            if not self.is_admin(uid):
                return await self.show(
                    target, "Bu bo‘lim faqat administrator uchun.", self.back_keyboard()
                )
            stats, tickets = await asyncio.to_thread(self.admin_data)
            text = f"⚙️ <b>Administrator</b>\nFoydalanuvchilar: {stats[0]}\nFaol skinlar: {stats[1]}\nOchiq murojaatlar: {stats[2]}"
            rows = [
                [
                    self.cb(
                        f"📨 #{item['id']} · {item['body'][:30]}",
                        f"ticket:{item['id']}",
                    )
                ]
                for item in tickets
            ]
            rows.append(
                [self.web("Skin joylash", "/admin"), self.cb("🔄 Yangilash", "admin")]
            )
        else:
            return await self.show(
                target,
                "Ilova hozircha ochilmadi. Keyinroq qayta urinib ko‘ring.",
                self.back_keyboard(),
            )
        await self.show(target, text, self.back_keyboard(*rows))

    def admin_data(self):
        with self.s.connect() as conn:
            stats = [
                conn.execute(sql).fetchone()[0]
                for sql in (
                    "SELECT COUNT(*) FROM users",
                    "SELECT COUNT(*) FROM skins WHERE active=1",
                    "SELECT COUNT(*) FROM support_tickets WHERE status='open'",
                )
            ]
            tickets = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, body FROM support_tickets WHERE status='open' ORDER BY id LIMIT 8"
                )
            ]
        return stats, tickets

    def list_data(self, uid, section, page):
        mode = self.mode(uid)
        query = mode.get("value", "") if mode.get("mode") == "catalog" else ""
        if section == "catalog":
            needle = (
                query.lower()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            table = "skins"
            where, args = (
                "active=1 AND LOWER(name || ' ' || weapon || ' ' || skin) LIKE ? ESCAPE '\\'",
                ("%" + needle + "%",),
            )
        elif section == "inventory":
            table, where, args = (
                "inventory",
                "telegram_id=? AND status='owned'",
                (str(uid),),
            )
        elif section == "history":
            table, where, args = "balance_events", "telegram_id=?", (str(uid),)
        else:
            table, where, args = "support_tickets", "telegram_id=?", (str(uid),)
        with self.s.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}", args
            ).fetchone()[0]
            page = min(max(page, 0), max(0, (total - 1) // self.PAGE_SIZE))
            rows = [
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM {table} WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                    (*args, self.PAGE_SIZE, page * self.PAGE_SIZE),
                )
            ]
        return rows, total, page, query

    async def list_view(self, target, user, section, page):
        rows, total, page, query = await asyncio.to_thread(
            self.list_data, user.id, section, page
        )
        titles = {
            "catalog": "🛍 Skinlar",
            "inventory": "🎒 Inventar",
            "history": "📜 Amallar tarixi",
            "tickets": "📨 Murojaatlarim",
        }
        text = f"<b>{titles[section]}</b> · {total}"
        buttons = []
        if section == "catalog" and query:
            text += "\nQidiruv: " + html.escape(query)
        if not rows:
            text += "\n\n" + (
                "Skinlar topilmadi. Boshqa nom bilan qidiring."
                if section == "catalog"
                else "Hozircha bu bo‘lim bo‘sh."
            )
        for item in rows:
            if section in ("catalog", "inventory"):
                text += f"\n\n<b>{html.escape(item['name'])}</b>\n${item['price']:,.2f}"
                if section == "catalog":
                    text += (
                        f" · {html.escape(item['condition'])} · {item['stock']} dona"
                    )
                    buttons.append([self.cb(item["name"][:45], f"item:{item['id']}")])
            elif section == "history":
                names = {
                    "demo_topup": "Demo balans qo‘shish",
                    "demo_purchase": "Demo xarid",
                    "demo_sale": "Demo sotuv",
                }
                label = names.get(item["event_type"], "Demo amal")
                text += f"\n\n{label} · <b>{item['amount']:+,.2f} USD</b>\n{html.escape(item['note'][:100])}\n<i>{item['created_at']}</i>"
            else:
                status = "Javob berilgan" if item["status"] == "answered" else "Ochiq"
                text += f"\n\n<b>#{item['id']}</b> · {status}\n{html.escape(item['body'][:100])}"
                buttons.append(
                    [self.cb(f"#{item['id']} · {status}", f"ticket:{item['id']}")]
                )
        pager = []
        if page > 0:
            pager.append(self.cb("← Oldingi", f"{section}:{page-1}"))
        if (page + 1) * self.PAGE_SIZE < total:
            pager.append(self.cb("Keyingi →", f"{section}:{page+1}"))
        if pager:
            buttons.append(pager)
        path = {
            "catalog": "/skins",
            "inventory": "/inventory",
            "history": "/history",
            "tickets": "/faq",
        }[section]
        buttons.append(
            [
                self.web(
                    "Ilovada ochish ↗",
                    path,
                    {"q": query} if query and section == "catalog" else None,
                )
            ]
        )
        if section == "catalog":
            buttons.append(
                [self.cb("🔎 Qidirish", "search"), self.cb("Barchasi", "all")]
            )
        if section == "tickets":
            buttons.append([self.cb("💬 Yangi murojaat", "support")])
        await self.show(target, text, self.back_keyboard(*buttons))

    async def item(self, target, uid, item_id):
        def fetch():
            with self.s.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM skins WHERE id=? AND active=1", (item_id,)
                ).fetchone()
                return dict(row) if row else None

        item = await asyncio.to_thread(fetch)
        if not item:
            return await self.show(
                target,
                "Bu skin hozir katalogda yo‘q.",
                self.back_keyboard([self.cb("🛍 Katalog", "catalog:0")]),
            )
        text = f"🛍 <b>{html.escape(item['name'])}</b>\n{html.escape(item['condition'])} · {html.escape(item['rarity'])}\n\nDemo narx: <b>${item['price']:,.2f}</b>\nQoldiq: {item['stock']} dona"
        if item["description"]:
            text += "\n\n" + html.escape(item["description"][:700])
        text += "\n\n<i>Xarid ilovada tasdiqlanadi. Haqiqiy pul olinmaydi.</i>"
        await self.show(
            target,
            text,
            self.back_keyboard(
                [self.web("Skinni ochish ↗", f"/skins/{item_id}")],
                [self.cb("← Katalog", "catalog:0")],
            ),
        )

    async def ticket(self, target, uid, ticket_id):
        def fetch():
            with self.s.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM support_tickets WHERE id=? AND (telegram_id=? OR ?=1)",
                    (ticket_id, str(uid), int(self.is_admin(uid))),
                ).fetchone()
                return dict(row) if row else None

        row = await asyncio.to_thread(fetch)
        if not row:
            return await self.show(target, "Murojaat topilmadi.", self.back_keyboard())
        text = f"📨 <b>Murojaat #{row['id']}</b>\n{html.escape(row['body'])}"
        if row["reply"]:
            text += "\n\n<b>Javob:</b>\n" + html.escape(row["reply"])
        elif self.is_admin(uid):
            text += f"\n\nJavob berish: <code>/reply {row['id']} javob matni</code>"
        else:
            text += "\n\nHolati: ochiq."
        await self.show(
            target,
            text,
            self.back_keyboard(
                [
                    self.cb(
                        "← Murojaatlar", "admin" if self.is_admin(uid) else "tickets:0"
                    )
                ]
            ),
        )

    async def callback(self, callback: CallbackQuery):
        message = callback.message
        if not isinstance(message, Message) or not self.private_context(callback):
            return await callback.answer(
                "Botning shaxsiy chatidan foydalaning.", show_alert=True
            )
        try:
            await callback.answer()
        except TelegramBadRequest:
            pass  # Expired spinner acknowledgements must not block the actual action.
        profile = await self.user(callback.from_user)
        action = callback.data[3:]
        if action == "all":
            await asyncio.to_thread(self.set_mode, callback.from_user.id, "catalog", "")
            return await self.view(callback, callback.from_user, "catalog", profile=profile)
        if action == "cancel":
            await asyncio.to_thread(self.clear_mode, callback.from_user.id)
            return await self.view(callback, callback.from_user, "menu", profile=profile)
        if action.startswith("faq:"):
            title, body = FAQ.get(action[4:], FAQ["login"])
            return await self.show(
                callback,
                f"<b>{title}</b>\n\n{body}",
                self.back_keyboard([self.cb("← Yordam", "help")]),
            )
        match = re.fullmatch(
            r"(catalog|inventory|history|tickets|item|ticket):(\d{1,9})", action
        )
        if match:
            section, number = match.group(1), int(match.group(2))
            if section == "item":
                return await self.item(callback, callback.from_user.id, number)
            if section == "ticket":
                return await self.ticket(callback, callback.from_user.id, number)
            return await self.view(callback, callback.from_user, section, number, profile=profile)
        if action in (
            "menu",
            "profile",
            "balance",
            "help",
            "support",
            "search",
            "admin",
            "unavailable",
        ):
            return await self.view(callback, callback.from_user, action, profile=profile)
        await self.show(
            callback,
            "Bu tugma eskirgan. Menyudan qayta tanlang.",
            self.menu_keyboard(callback.from_user.id),
        )

    @staticmethod
    def private_context(callback):
        return (
            callback.message.chat.type == "private"
            and callback.message.chat.id == callback.from_user.id
            and not callback.from_user.is_bot
        )

    async def old_callback(self, callback: CallbackQuery):
        try:
            await callback.answer("Menyuni /start orqali yangilang.", show_alert=True)
        except TelegramBadRequest:
            pass

    async def command_view(self, message, section):
        if self.private(message):
            await self.view(message, message.from_user, section)

    async def profile(self, message):
        await self.command_view(message, "profile")

    async def balance(self, message):
        await self.command_view(message, "balance")

    async def topup(self, message):
        await self.command_view(message, "topup")

    async def inventory(self, message):
        await self.command_view(message, "inventory")

    async def history(self, message):
        await self.command_view(message, "history")

    async def help(self, message):
        await self.command_view(message, "help")

    async def support(self, message):
        await self.command_view(message, "support")

    async def tickets(self, message):
        await self.command_view(message, "tickets")

    async def admin(self, message):
        await self.command_view(message, "admin")

    async def search(self, message):
        if not self.private(message):
            return
        await self.user(message.from_user)
        query = (message.text or "").partition(" ")[2].strip()
        command = (message.text or "").split()[0].split("@")[0]
        if command == "/search" and not query:
            return await self.view(message, message.from_user, "search")
        if len(query) > 100:
            return await self.show(
                message, "Skin nomi 100 belgidan oshmasin.", self.back_keyboard()
            )
        await asyncio.to_thread(self.set_mode, message.from_user.id, "catalog", query)
        await self.list_view(message, message.from_user, "catalog", 0)

    async def cancel(self, message):
        if not self.private(message):
            return
        await asyncio.to_thread(self.clear_mode, message.from_user.id)
        await self.menu(message)

    def save_ticket(self, uid, message_id, text):
        with self.s.connect() as conn:
            conn.execute(
                "INSERT INTO support_tickets(telegram_id,message_id,body) VALUES (?,?,?) ON CONFLICT(telegram_id,message_id) DO NOTHING",
                (str(uid), message_id, text),
            )
            row = conn.execute(
                "SELECT id FROM support_tickets WHERE telegram_id=? AND message_id=?",
                (str(uid), message_id),
            ).fetchone()
            conn.execute("DELETE FROM bot_sessions WHERE telegram_id=?", (str(uid),))
        return row["id"]

    def ticket_for_message(self, uid, message_id):
        with self.s.connect() as conn:
            row = conn.execute(
                "SELECT id FROM support_tickets WHERE telegram_id=? AND message_id=?",
                (str(uid), message_id),
            ).fetchone()
        return row["id"] if row else None

    async def ticket_receipt(self, message, ticket_id):
        await self.show(
            message,
            f"✅ <b>Murojaat #{ticket_id} saqlandi.</b>\nHolatini «Murojaatlarim» bo‘limidan ko‘ring.",
            self.back_keyboard([self.cb("📨 Murojaatlarim", "tickets:0")]),
        )

    async def reply(self, message: Message, bot: Bot):
        if not self.private(message):
            return
        if not self.is_admin(message.from_user.id):
            return await self.show(
                message, "Bu buyruq faqat administrator uchun.", self.back_keyboard()
            )
        match = re.fullmatch(
            r"/reply(?:@\w+)?\s+(\d{1,9})\s+([\s\S]{1,2500})", message.text or ""
        )
        if not match:
            return await message.answer("Namuna: /reply 12 Javob matni")
        ticket_id, text = int(match.group(1)), match.group(2).strip()
        if not text:
            return await message.answer("Javob matnini yozing.")

        def fetch():
            with self.s.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM support_tickets WHERE id=?", (ticket_id,)
                ).fetchone()
                return dict(row) if row else None

        row = await asyncio.to_thread(fetch)
        if not row:
            return await message.answer("Murojaat topilmadi.")
        if row["status"] == "answered":
            return await message.answer("Bu murojaatga allaqachon javob berilgan.")
        # This sends only an explicit administrator reply to a user's own support request.
        try:
            await bot.send_message(
                chat_id=int(row["telegram_id"]),
                text=f"💬 <b>Murojaat #{ticket_id} — javob</b>\n\n{html.escape(text)}",
                parse_mode="HTML",
                reply_markup=self.back_keyboard(
                    [self.cb("Murojaatni ko‘rish", f"ticket:{ticket_id}")]
                ),
            )
        except TelegramForbiddenError:
            return await message.answer(
                "Javob yetkazilmadi. Foydalanuvchi botni bloklagan bo‘lishi mumkin. Murojaat ochiq qoldi."
            )

        def finish():
            with self.s.connect() as conn:
                conn.execute(
                    "UPDATE support_tickets SET status='answered',reply=?,answered_at=CURRENT_TIMESTAMP WHERE id=?",
                    (text, ticket_id),
                )

        await asyncio.to_thread(finish)
        await message.answer(f"✅ #{ticket_id} murojaatga javob yuborildi.")

    async def text(self, message: Message):
        if not self.private(message):
            return
        await self.user(message.from_user)
        text = (message.text or "").strip()
        if not text:
            return await self.show(
                message,
                "Matnli xabar yozing yoki menyudan bo‘lim tanlang.",
                self.menu_keyboard(message.from_user.id),
            )
        if text.startswith("/"):
            return await self.show(
                message,
                "Buyruq topilmadi. /help orqali yordamni oching.",
                self.menu_keyboard(message.from_user.id),
            )
        existing = await asyncio.to_thread(
            self.ticket_for_message, message.from_user.id, message.message_id
        )
        if existing:
            return await self.ticket_receipt(message, existing)
        normalized = re.sub(r"[‘’ʼ'`!?.,]", "", text.casefold())
        intents = {
            "salom": "menu",
            "assalomu alaykum": "menu",
            "menyu": "menu",
            "bosh sahifa": "menu",
            "profil": "profile",
            "profilim": "profile",
            "hisobim": "profile",
            "balans": "balance",
            "balansim": "balance",
            "inventar": "inventory",
            "skinlarim": "inventory",
            "tarix": "history",
            "yordam": "help",
            "faq": "help",
            "balans toldirish": "topup",
            "murojaat": "support",
            "support": "support",
            "bekor": "menu",
        }
        mode = await asyncio.to_thread(self.mode, message.from_user.id)
        if normalized in ("bekor", "menyu", "bosh sahifa"):
            return await self.view(message, message.from_user, "menu")
        if mode.get("mode") == "support":
            if not 5 <= len(text) <= 1500:
                return await self.show(
                    message,
                    "Murojaat 5–1500 belgidan iborat bo‘lsin.",
                    self.back_keyboard([self.cb("Bekor qilish", "cancel")]),
                )
            ticket_id = await asyncio.to_thread(
                self.save_ticket, message.from_user.id, message.message_id, text
            )
            return await self.ticket_receipt(message, ticket_id)
        if normalized in intents:
            return await self.view(message, message.from_user, intents[normalized])
        if any(
            word in normalized
            for word in ("login", "kirish", "ochilmay", "telegramda oching")
        ):
            title, body = FAQ["login"]
            return await self.show(
                message,
                f"<b>{title}</b>\n\n{body}",
                self.back_keyboard([self.web("🎮 Ilovani ochish")]),
            )
        if not 2 <= len(text) <= 100:
            return await self.show(
                message,
                "Skin nomini 2–100 belgida yozing yoki menyudan tanlang.",
                self.menu_keyboard(message.from_user.id),
            )
        await asyncio.to_thread(self.set_mode, message.from_user.id, "catalog", text)
        await self.list_view(message, message.from_user, "catalog", 0)
