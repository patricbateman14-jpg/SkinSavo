from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
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
START_BALANCE = float(os.getenv("DEMO_START_BALANCE", "250.00"))
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "").strip()

# Expanded demo catalog — realistic CS2-style names & prices (demo only)
SAMPLE_SKINS: list[dict[str, Any]] = [
    {
        "name": "AK-47 | Redline",
        "weapon": "AK-47",
        "skin": "Redline",
        "rarity": "Classified",
        "condition": "Field-Tested",
        "price": 18.75,
        "stock": 6,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AK-47+Redline",
        "description": "Qizil va qora rangdagi klassik AK-47 skin. Demo listing.",
    },
    {
        "name": "AWP | Asiimov",
        "weapon": "AWP",
        "skin": "Asiimov",
        "rarity": "Covert",
        "condition": "Field-Tested",
        "price": 92.50,
        "stock": 2,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AWP+Asiimov",
        "description": "Futuristik oq-to‘q sariq sniper finish. Demo listing.",
    },
    {
        "name": "M4A1-S | Printstream",
        "weapon": "M4A1-S",
        "skin": "Printstream",
        "rarity": "Covert",
        "condition": "Minimal Wear",
        "price": 74.20,
        "stock": 3,
        "image": "https://placehold.co/640x420/080808/ffffff?text=M4A1-S+Printstream",
        "description": "Monoxrom pearl-like dizayn. Demo listing.",
    },
    {
        "name": "USP-S | Kill Confirmed",
        "weapon": "USP-S",
        "skin": "Kill Confirmed",
        "rarity": "Covert",
        "condition": "Field-Tested",
        "price": 39.90,
        "stock": 5,
        "image": "https://placehold.co/640x420/080808/ffffff?text=USP-S+Kill+Confirmed",
        "description": "Yorqin illustratsiyali USP-S. Demo listing.",
    },
    {
        "name": "Glock-18 | Fade",
        "weapon": "Glock-18",
        "skin": "Fade",
        "rarity": "Restricted",
        "condition": "Factory New",
        "price": 82.00,
        "stock": 1,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Glock-18+Fade",
        "description": "Gradient metallic fade. Demo listing.",
    },
    {
        "name": "★ Karambit | Doppler",
        "weapon": "Knife",
        "skin": "Doppler",
        "rarity": "Covert",
        "condition": "Factory New",
        "price": 465.00,
        "stock": 1,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Karambit+Doppler",
        "description": "Egri pichoq, Doppler phase. Demo listing.",
    },
    {
        "name": "Desert Eagle | Printstream",
        "weapon": "Desert Eagle",
        "skin": "Printstream",
        "rarity": "Covert",
        "condition": "Minimal Wear",
        "price": 48.60,
        "stock": 4,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Desert+Eagle+Printstream",
        "description": "Oq-qora pearlescent finish. Demo listing.",
    },
    {
        "name": "P250 | See Ya Later",
        "weapon": "P250",
        "skin": "See Ya Later",
        "rarity": "Covert",
        "condition": "Minimal Wear",
        "price": 12.40,
        "stock": 9,
        "image": "https://placehold.co/640x420/080808/ffffff?text=P250+See+Ya+Later",
        "description": "Rangli creature-inspired skin. Demo listing.",
    },
    {
        "name": "AK-47 | Vulcan",
        "weapon": "AK-47",
        "skin": "Vulcan",
        "rarity": "Covert",
        "condition": "Field-Tested",
        "price": 68.30,
        "stock": 3,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AK-47+Vulcan",
        "description": "Qizil race-car uslubidagi AK. Demo listing.",
    },
    {
        "name": "AWP | Dragon Lore",
        "weapon": "AWP",
        "skin": "Dragon Lore",
        "rarity": "Covert",
        "condition": "Field-Tested",
        "price": 4200.00,
        "stock": 1,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AWP+Dragon+Lore",
        "description": "Afsonaviy oltin ajdaho. Demo listing (narx taxminiy).",
    },
    {
        "name": "★ Butterfly Knife | Fade",
        "weapon": "Knife",
        "skin": "Fade",
        "rarity": "Covert",
        "condition": "Factory New",
        "price": 890.00,
        "stock": 1,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Butterfly+Fade",
        "description": "Butterfly knife gradient fade. Demo listing.",
    },
    {
        "name": "M4A4 | Howl",
        "weapon": "M4A4",
        "skin": "Howl",
        "rarity": "Contraband",
        "condition": "Minimal Wear",
        "price": 1850.00,
        "stock": 1,
        "image": "https://placehold.co/640x420/080808/ffffff?text=M4A4+Howl",
        "description": "Contraband rarity, qizil bo‘ri. Demo listing.",
    },
    {
        "name": "USP-S | Neo-Noir",
        "weapon": "USP-S",
        "skin": "Neo-Noir",
        "rarity": "Covert",
        "condition": "Factory New",
        "price": 28.50,
        "stock": 7,
        "image": "https://placehold.co/640x420/080808/ffffff?text=USP-S+Neo-Noir",
        "description": "Badiiy neo-noir uslub. Demo listing.",
    },
    {
        "name": "AK-47 | Bloodsport",
        "weapon": "AK-47",
        "skin": "Bloodsport",
        "rarity": "Covert",
        "condition": "Minimal Wear",
        "price": 55.80,
        "stock": 4,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AK-47+Bloodsport",
        "description": "Sportiv qizil-qora AK. Demo listing.",
    },
    {
        "name": "AWP | Containment Breach",
        "weapon": "AWP",
        "skin": "Containment Breach",
        "rarity": "Covert",
        "condition": "Field-Tested",
        "price": 42.10,
        "stock": 5,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AWP+Containment",
        "description": "Yashil kontainment uslubi. Demo listing.",
    },
    {
        "name": "Glock-18 | Water Elemental",
        "weapon": "Glock-18",
        "skin": "Water Elemental",
        "rarity": "Classified",
        "condition": "Minimal Wear",
        "price": 9.80,
        "stock": 12,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Glock+Water",
        "description": "Suv elementlari. Demo listing.",
    },
    {
        "name": "★ Bayonet | Marble Fade",
        "weapon": "Knife",
        "skin": "Marble Fade",
        "rarity": "Covert",
        "condition": "Factory New",
        "price": 520.00,
        "stock": 2,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Bayonet+Marble",
        "description": "Marble Fade phase. Demo listing.",
    },
    {
        "name": "Desert Eagle | Blaze",
        "weapon": "Desert Eagle",
        "skin": "Blaze",
        "rarity": "Restricted",
        "condition": "Factory New",
        "price": 185.00,
        "stock": 2,
        "image": "https://placehold.co/640x420/080808/ffffff?text=Deagle+Blaze",
        "description": "Olovli blaze finish. Demo listing.",
    },
    {
        "name": "M4A1-S | Player Two",
        "weapon": "M4A1-S",
        "skin": "Player Two",
        "rarity": "Classified",
        "condition": "Field-Tested",
        "price": 14.20,
        "stock": 8,
        "image": "https://placehold.co/640x420/080808/ffffff?text=M4A1-S+Player+Two",
        "description": "O‘yinchi ikki uslubi. Demo listing.",
    },
    {
        "name": "AWP | Neo-Noir",
        "weapon": "AWP",
        "skin": "Neo-Noir",
        "rarity": "Covert",
        "condition": "Minimal Wear",
        "price": 38.90,
        "stock": 4,
        "image": "https://placehold.co/640x420/080808/ffffff?text=AWP+Neo-Noir",
        "description": "Badiiy neo-noir AWP. Demo listing.",
    },
]


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
        # Remove old seeded placeholder listings; preserve future admin-added skins.
        conn.execute("DELETE FROM skins WHERE image LIKE 'https://placehold.co/%' AND description LIKE '%Demo listing%'")


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


app = FastAPI(title="SkinSavo API", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class DemoTopUp(BaseModel):
    telegram_id: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=10000)


class SkinCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    weapon: str = Field(min_length=1, max_length=80)
    skin: str = Field(min_length=1, max_length=100)
    rarity: str = Field(min_length=1, max_length=50)
    condition: str = Field(min_length=1, max_length=50)
    price: float = Field(ge=0, le=100000000)
    stock: int = Field(ge=0, le=1000000)
    image: str = Field(min_length=8, max_length=2000)
    description: str = Field(default="", max_length=2000)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": "demo",
        "catalog_source": "sample_data",
        "version": "0.2.0",
    }


@app.get("/api/skins")
def list_skins(
    q: str = Query(default="", max_length=100),
    sort: str = Query(default="featured"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    sql = "SELECT * FROM skins WHERE active = 1"
    params: list[Any] = []

    if q.strip():
        needle = f"%{q.strip()}%"
        sql += " AND (name LIKE ? OR weapon LIKE ? OR skin LIKE ? OR rarity LIKE ? OR condition LIKE ?)"
        params.extend([needle] * 5)

    order_map = {
        "price_asc": "price ASC",
        "price_desc": "price DESC",
        "name": "name COLLATE NOCASE ASC",
        "stock": "stock DESC",
        "featured": "id ASC",
    }
    order = order_map.get(sort, "id ASC")

    with db() as conn:
        count_sql = "SELECT COUNT(*) FROM skins WHERE active = 1"
        count_params: list[Any] = []
        if q.strip():
            count_sql += " AND (name LIKE ? OR weapon LIKE ? OR skin LIKE ? OR rarity LIKE ? OR condition LIKE ?)"
            count_params = params[:]

        total = conn.execute(count_sql, count_params).fetchone()[0]
        rows = conn.execute(
            sql + f" ORDER BY {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "demo": True,
    }


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
def get_user(telegram_id: str, username: str = ""):
    if not telegram_id or len(telegram_id) > 80:
        raise HTTPException(status_code=400, detail="Noto‘g‘ri Telegram ID")
    return {**user_payload(telegram_id, username), "demo": True}


@app.post("/api/demo/topup")
def demo_topup(payload: DemoTopUp):
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
def user_history(telegram_id: str):
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
