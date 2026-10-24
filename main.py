from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "skinsavo.db"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
START_BALANCE = 0.0  # Only explicit demo top-ups credit simulated funds.
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "").strip()

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                balance REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                weapon TEXT NOT NULL,
                skin TEXT NOT NULL,
                rarity TEXT NOT NULL,
                condition TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL,
                image TEXT NOT NULL,
                description TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS balance_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT NOT NULL,
                amount REAL NOT NULL,
                event_type TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
            """
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT NOT NULL REFERENCES users(telegram_id),
            skin_id INTEGER NOT NULL REFERENCES skins(id),
            name TEXT NOT NULL, price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'owned',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def user_payload(telegram_id: str, username: str = "") -> dict[str, Any]:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, balance) VALUES (?, ?, ?)",
            (telegram_id, username, START_BALANCE),
        )
        if username:
            conn.execute(
                "UPDATE users SET username = ? WHERE telegram_id = ? AND (username = '' OR username IS NULL)",
                (username, telegram_id),
            )
        row = conn.execute(
            "SELECT telegram_id, username, balance FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
    return dict(row)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="SkinSavo API", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class DemoTopUp(BaseModel):
    telegram_id: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=10000, allow_inf_nan=False)


class SkinCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    weapon: str = Field(min_length=1, max_length=80)
    skin: str = Field(min_length=1, max_length=100)
    rarity: str = Field(min_length=1, max_length=50)
    condition: str = Field(min_length=1, max_length=50)
    price: float = Field(ge=0, le=100000000, allow_inf_nan=False)
    stock: int = Field(ge=0, le=1000000)
    image: str = Field(min_length=8, max_length=2000)
    description: str = Field(default="", max_length=2000)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


def telegram_user_from_init_data(init_data: str) -> dict[str, Any]:
    if not BOT_TOKEN or not init_data:
        raise HTTPException(status_code=401, detail="Telegram Mini App orqali kiring")
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = data.pop("hash", "")
        auth_date = int(data.get("auth_date", "0"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Telegram sessiyasi noto‘g‘ri")
    if not received_hash or abs(int(time.time()) - auth_date) > 86400:
        raise HTTPException(status_code=401, detail="Telegram sessiyasi eskirgan")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Telegram imzosi tekshiruvdan o‘tmadi")
    try:
        user = json.loads(data.get("user", "{}"))
        if not isinstance(user, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Telegram user ma’lumoti noto‘g‘ri")
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="Telegram foydalanuvchisi aniqlanmadi")
    return user


def require_admin(init_data: str) -> dict[str, Any]:
    user = telegram_user_from_init_data(init_data)
    if not ADMIN_TELEGRAM_ID or str(user.get("id")) != ADMIN_TELEGRAM_ID:
        raise HTTPException(status_code=403, detail="Bu amal faqat administrator uchun")
    return user

@app.get("/api/session")
def session_info(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    if not x_telegram_init_data:
        return {"authenticated": False, "is_admin": False}
    user = telegram_user_from_init_data(x_telegram_init_data)
    return {"authenticated": True, "telegram_id": str(user["id"]), "username": user.get("username", ""),
            "is_admin": bool(ADMIN_TELEGRAM_ID and str(user["id"]) == ADMIN_TELEGRAM_ID)}


@app.post("/api/admin/skins")
def admin_create_skin(payload: SkinCreate, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    require_admin(x_telegram_init_data)
    image = payload.image.strip()
    if not image.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Rasm havolasi http:// yoki https:// bilan boshlanishi kerak")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO skins (name, weapon, skin, rarity, condition, price, stock, image, description, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (payload.name.strip(), payload.weapon.strip(), payload.skin.strip(), payload.rarity.strip(), payload.condition.strip(), payload.price, payload.stock, image, payload.description.strip()),
        )
        row = conn.execute("SELECT * FROM skins WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": dict(row), "ok": True}


@app.delete("/api/admin/skins/{skin_id}")
def admin_delete_skin(skin_id: int, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    require_admin(x_telegram_init_data)
    with db() as conn:
        cur = conn.execute("UPDATE skins SET active = 0 WHERE id = ?", (skin_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Skin topilmadi")
    return {"ok": True, "deleted_id": skin_id}

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": "demo",
        "catalog_source": "admin_managed",
        "version": "0.3.0",
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
    }


CATEGORIES = {
    "Rifles": ["AK-47", "M4A1-S", "M4A4", "FAMAS", "Galil AR", "AUG", "SG 553"],
    "Snipers": ["AWP", "SSG 08", "SCAR-20", "G3SG1"],
    "SMGs": ["MP9", "MP7", "MP5-SD", "MAC-10", "UMP-45", "P90", "PP-Bizon"],
    "Shotguns": ["Nova", "XM1014", "MAG-7", "Sawed-Off"],
    "Pistols": ["USP-S", "Glock-18", "Desert Eagle", "P250", "Five-SeveN", "Tec-9", "CZ75-Auto", "P2000", "R8 Revolver", "Dual Berettas"],
    "Knives": ["Knife", "Karambit", "Bayonet", "Butterfly Knife"],
    "Gloves": ["Gloves", "Hand Wraps", "Sport Gloves", "Driver Gloves"],
}


def category_of(item):
    weapon = item["weapon"]
    if any(word in weapon.lower() for word in ("knife", "karambit", "bayonet")):
        return "Knives"
    if "glove" in weapon.lower() or "wraps" in weapon.lower():
        return "Gloves"
    return next((key for key, weapons in CATEGORIES.items() if weapon in weapons), "Other")


@app.get("/api/skins")
def list_skins(q: str = Query(default="", max_length=100), sort: str = "featured",
               category: str = "", rarity: str = "", condition: str = "",
               limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    with db() as conn:
        items = [dict(row) for row in conn.execute("SELECT * FROM skins WHERE active = 1 ORDER BY id")]
    counts = {key: sum(category_of(item) == key for item in items) for key in CATEGORIES}
    total_catalog = len(items)
    items = [item for item in items if
             (not q.strip() or q.strip().lower() in " ".join(str(item[k]) for k in ("name", "weapon", "skin", "rarity", "condition")).lower())
             and (not category or category_of(item) == category)
             and (not rarity or item["rarity"] in rarity.split(","))
             and (not condition or item["condition"] in condition.split(","))]
    if sort in ("price_asc", "price_desc"):
        items.sort(key=lambda i: i["price"], reverse=sort == "price_desc")
    elif sort in ("name", "name_desc"):
        items.sort(key=lambda i: i["name"].lower(), reverse=sort == "name_desc")
    elif sort == "stock":
        items.sort(key=lambda i: i["stock"], reverse=True)
    return {"items": items[offset:offset + limit], "total": len(items), "catalog_total": total_catalog,
            "categories": counts, "limit": limit, "offset": offset, "demo": True}


@app.get("/api/skins/{skin_id}")
def get_skin(skin_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM skins WHERE id = ? AND active = 1", (skin_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Skin topilmadi")
    return dict(row)


@app.get("/api/users/{telegram_id}")
def get_user(telegram_id: str, username: str = "", x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    authorize_user(telegram_id, x_telegram_init_data)
    if not telegram_id or len(telegram_id) > 80:
        raise HTTPException(status_code=400, detail="Noto‘g‘ri Telegram ID")
    return {**user_payload(telegram_id, username), "demo": True}


@app.post("/api/demo/topup")
def demo_topup(payload: DemoTopUp, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    authorize_user(payload.telegram_id, x_telegram_init_data)
    """Demo-only endpoint. Credits simulated funds. No real payments."""
    user_payload(payload.telegram_id)
    with db() as conn:
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
            (payload.amount, payload.telegram_id),
        )
        conn.execute(
            """
            INSERT INTO balance_events (telegram_id, amount, event_type, note)
            VALUES (?, ?, ?, ?)
            """,
            (
                payload.telegram_id,
                payload.amount,
                "demo_topup",
                "Simulated top-up; no real money",
            ),
        )
        row = conn.execute(
            "SELECT telegram_id, username, balance FROM users WHERE telegram_id = ?",
            (payload.telegram_id,),
        ).fetchone()
    return {
        **dict(row),
        "demo": True,
        "message": "Demo balans yangilandi. Haqiqiy to‘lov amalga oshmadi.",
    }


@app.get("/api/users/{telegram_id}/history")
def user_history(telegram_id: str, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    authorize_user(telegram_id, x_telegram_init_data)
    if not telegram_id or len(telegram_id) > 80:
        raise HTTPException(status_code=400, detail="Noto‘g‘ri Telegram ID")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT amount, event_type, note, created_at
            FROM balance_events
            WHERE telegram_id = ?
            ORDER BY id DESC
            LIMIT 50
            """,
            (telegram_id,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


def authorize_user(telegram_id: str, init_data: str):
    user = telegram_user_from_init_data(init_data)
    if str(user["id"]) != telegram_id:
        raise HTTPException(status_code=403, detail="Boshqa foydalanuvchi hisobiga kirish taqiqlangan")
    return user


class DemoPurchase(BaseModel):
    skin_id: int = Field(gt=0)


@app.post("/api/demo/purchase")
def demo_purchase(payload: DemoPurchase, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    user = telegram_user_from_init_data(x_telegram_init_data)
    uid = str(user["id"])
    user_payload(uid, user.get("username", ""))
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        skin = conn.execute("SELECT * FROM skins WHERE id = ? AND active = 1", (payload.skin_id,)).fetchone()
        if not skin or skin["stock"] < 1:
            raise HTTPException(status_code=409, detail="Skin qoldig‘i mavjud emas")
        balance = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (uid,)).fetchone()[0]
        if balance < skin["price"]:
            raise HTTPException(status_code=409, detail="Demo balans yetarli emas")
        conn.execute("UPDATE skins SET stock = stock - 1 WHERE id = ?", (skin["id"],))
        conn.execute("UPDATE users SET balance = ROUND(balance - ?, 2) WHERE telegram_id = ?", (skin["price"], uid))
        conn.execute("INSERT INTO inventory (telegram_id, skin_id, name, price) VALUES (?, ?, ?, ?)", (uid, skin["id"], skin["name"], skin["price"]))
        conn.execute("INSERT INTO balance_events (telegram_id, amount, event_type, note) VALUES (?, ?, 'demo_purchase', ?)", (uid, -skin["price"], skin["name"]))
    return {"ok": True, "demo": True}


@app.get("/api/inventory")
def inventory(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    user = telegram_user_from_init_data(x_telegram_init_data)
    with db() as conn:
        rows = conn.execute("SELECT i.*, s.image, s.condition FROM inventory i JOIN skins s ON s.id=i.skin_id WHERE i.telegram_id=? ORDER BY i.id DESC", (str(user["id"]),)).fetchall()
    return {"items": [dict(row) for row in rows], "demo": True}


@app.post("/api/demo/inventory/{item_id}/sell")
def sell_demo_item(item_id: int, x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    user = telegram_user_from_init_data(x_telegram_init_data)
    uid = str(user["id"])
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute("SELECT * FROM inventory WHERE id=? AND telegram_id=? AND status='owned'", (item_id, uid)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Inventar elementi topilmadi")
        conn.execute("UPDATE inventory SET status='sold' WHERE id=?", (item_id,))
        conn.execute("UPDATE skins SET stock=stock+1 WHERE id=?", (item["skin_id"],))
        conn.execute("UPDATE users SET balance=ROUND(balance+?, 2) WHERE telegram_id=?", (item["price"], uid))
        conn.execute("INSERT INTO balance_events (telegram_id, amount, event_type, note) VALUES (?, ?, 'demo_sale', ?)", (uid, item["price"], item["name"]))
    return {"ok": True, "demo": True}


# ---------- Telegram bot ----------
dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message, bot: Bot):
    if not WEBAPP_URL.startswith("https://"):
        await message.answer(
            "🎮 SkinSavo demo tayyor.\n\n"
            "Mini-ilovani ishga tushirish uchun .env faylida WEBAPP_URL qiymatiga HTTPS domen yozing."
        )
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🎮 SkinSavo ochish",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
    )
    await message.answer(
        "🎮 <b>SkinSavo</b>ga xush kelibsiz!\n\n"
        "CS2 skinlar katalogini ko‘ring.\n"
        "Balans hozircha <b>demo</b> rejimda ishlaydi.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def run_bot() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN .env faylida ko‘rsatilmagan")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())
