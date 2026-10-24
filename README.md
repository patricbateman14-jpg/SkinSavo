# SkinSavo

CS2 demo marketplace on the existing FastAPI / SQLite / vanilla JavaScript stack.
Monochrome interface with authentic colored product art. No real payments,
Steam transfers or live market-price feed.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000. The public catalog works without sign-in. Account,
balance, purchase, sale and history require signed Telegram Mini App initData
in X-Telegram-Init-Data. Set BOT_TOKEN and WEBAPP_URL to connect your bot;
run python main.py as a separate bot process. ADMIN_TELEGRAM_ID grants the
matching signed user access to the existing admin listing panel.

New accounts start at zero. Explicit demo top-ups add simulated funds. Demo
purchases validate stock and balance in a SQLite write transaction and persist
inventory and history. Selling an owned demo item refunds its recorded purchase
price once. Admin deletion deactivates listings, preserving inventory. Existing
balances and database records are preserved. Startup never deletes demo rows.

## Catalog and artwork

Search, category, multiple rarity/condition selections and sorting work together.
Reset clears every filter. Pagination supports catalogs over 100 rows. Category
counts come from active database listings. Existing 20 demo records are retained;
no stock is added. Empty production databases remain empty until an admin adds
listings. No user/trade totals are presented as verified platform statistics.

Local artwork mappings and provenance: static/assets/manifest.json and
static/assets/sources.json. Trade banner: generated fictional promotional art.
See static/assets/README.md for attribution and the image generation prompt.
The screenshot mentioned in the brief was unavailable; implementation follows
its written layout specification.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/app.js
npm.cmd install --no-save --package-lock=false playwright
node scripts/check-browser.cjs
```

Browser checks require installed Chrome on Windows, a running local server and
the existing 20-row demo catalog. Six viewport widths, images, overflow, search,
combined category filters, reset, sorting, details, theme persistence, mobile
filters, guest access and uncaught JavaScript errors are checked. Screenshots
are saved to ignored test-results/. External Telegram SDK and Google fonts are
stubbed in guest browser tests; signed authentication is tested through the API.
No frontend compilation is required.

## Deployment

railway.json starts the existing ASGI app and checks /api/health. The existing
Render blueprint is retained. Set DATABASE_PATH to the database on the existing
persistent volume. Preserve that path and volume; never delete a database to
refresh catalog data. Startup adds the inventory table without changing rows.

Deploy the intended GitHub commit through the existing Railway service and
verify both its commit and /api/health version 0.3.0. A healthy URL alone does
not prove the intended commit deployed.

Production URL: https://skinsavo-web-production.up.railway.app/

Real payments, Steam integration, live inventory, real-time market pricing and
commercial asset licensing remain outside this demo implementation.
