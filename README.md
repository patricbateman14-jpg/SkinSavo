# SkinSavo 🎮

Premium Telegram Mini App for a CS2 skin catalog.  
Python / FastAPI backend · SQLite demo storage · Modern dark UI optimized for mobile & Telegram.

## Features

- **Premium dark UI** with light theme toggle, glass effects, smooth animations
- Responsive skin cards (image, rarity, condition, price, stock)
- Search by name / weapon / rarity / condition + quick category chips
- Sorting: Tavsiya · Arzon · Qimmat · Nom · Qoldiq
- Skin detail bottom-sheet modal
- Per-user demo balance, simulated top-up, balance history
- Skeleton loading states, empty states, toast notifications
- Telegram Mini App SDK + bot `/start` with WebApp button
- Render.com deployment blueprint

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # or copy on Windows
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

> **Note:** If you already ran an older version, delete `skinsavo.db` once so the expanded catalog (20 skins) is seeded.

Telegram Mini App behavior requires opening the app from Telegram over **HTTPS**.

## Connect Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and put the token in `.env` as `BOT_TOKEN`.
2. Deploy the web app to a public HTTPS URL and set `WEBAPP_URL` to that exact URL.
3. Run the bot process: `python main.py`
4. Optionally set the bot menu button in BotFather.

Web service and bot are separate processes:
- `uvicorn main:app --host 0.0.0.0 --port 8000` — API + frontend
- `python main.py` — Telegram bot polling

**Never commit `.env` or your bot token.**

## Deploy to Render

Use **New + → Blueprint** and select this repository.  
Set `WEBAPP_URL` (final public HTTPS URL) and `BOT_TOKEN` in the service environment.

**Storage note:** the included blueprint uses `/tmp` for a simple demo database (ephemeral). For production attach a persistent disk or switch to PostgreSQL.

## Important: demo only

- Catalog is **sample/demo data** (20 CS2-style skins). Not a live market feed.
- Demo top-ups only change a simulated balance. No real payments, purchases, or Steam transfers.
- Before real users/funds: add Telegram `initData` signature validation, rate limits, persistent storage, audit logs, and a payment provider. Never trust a browser-supplied user ID alone.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/skins?q=&sort=&limit=&offset=` | List / search skins |
| GET | `/api/skins/{id}` | Skin detail |
| GET | `/api/users/{telegram_id}` | User + balance |
| POST | `/api/demo/topup` | Demo top-up only |
| GET | `/api/users/{telegram_id}/history` | Balance history |

## Tech stack

- Backend: FastAPI, aiogram 3, SQLite, Pydantic
- Frontend: Vanilla JS, modern CSS (no framework), Telegram WebApp SDK
- Deploy: Render blueprint

---

Made for demo / portfolio use. Not affiliated with Valve or Steam.
