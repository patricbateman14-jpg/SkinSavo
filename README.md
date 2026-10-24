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

Open http://127.0.0.1:8000 to see the Telegram-only gate. The application and
every business API require Telegram-signed Mini App initData in
X-Telegram-Init-Data. There is no password or browser registration flow.
Set BOT_TOKEN and the production HTTPS WEBAPP_URL in Railway. Startup verifies
the bot with getMe and configures its default SkinSavo Mini App menu button.
BOT_USERNAME is optional and is resolved from the token. Run python main.py as
a separate bot process to handle /start with the inline Mini App button.
Do not start a second poller for an already running bot. ADMIN_TELEGRAM_ID grants
the matching signed user access to the existing admin listing panel.

Verified login automatically creates or updates ID, name, username, photo URL
(when Telegram provides it), language and Premium flag. Balances and inventory
are preserved. Usernames and photos are optional. Client-supplied profile fields
are ignored. No phone number, password, or contact permission is requested.
The gate remains until the backend confirms the Telegram signature. Forged,
expired, duplicated or malformed credentials are rejected by the server.
The branded splash remains for at least three seconds and waits longer for a
slow profile response. Telegram launch data is re-read during initialization;
signed data in the launch fragment/query can also be recovered if SDK setup is
delayed. The official Telegram SDK is served locally from static/telegram-web-app.js.
Plain Telegram browser tabs and old reply-keyboard buttons do not provide Mini
App credentials: use the bot's SkinSavo menu button or a configured Main Mini App.

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
# In another terminal: .\.venv\Scripts\python.exe scripts/serve-browser-test.py
node scripts/check-browser.cjs
node scripts/check-telegram-entry.cjs
```

Browser checks require installed Chrome on Windows and the isolated test launcher
above. It copies the local catalog into a temporary database, uses a test-only
token, and makes no Telegram API calls. Never deploy that launcher. Browser tests
cover unsigned/forged rejection and HMAC-verified automatic login, then test six
viewport widths, images, catalog controls, profile, inventory and theme. The
Telegram SDK is simulated with test-signed initData; the actual backend signature
check runs unchanged. Screenshots go to ignored test-results/. No frontend build
is required. Actual Telegram-client login still needs a real user to open the bot.

## Deployment

railway.json starts the existing ASGI app and checks /api/health. The existing
Render blueprint is retained. Set DATABASE_PATH to the database on the existing
persistent volume. Preserve that path and volume; never delete a database to
refresh catalog data. Startup adds the inventory table without changing rows.

Deploy the intended GitHub commit through the existing Railway service and
verify both its commit and /api/health version 0.4.0. The health response reports
telegram_configured, telegram_ready and telegram_menu_ready without credentials.
A healthy URL alone does
not prove the intended commit deployed.

Production URL: https://skinsavo-web-production.up.railway.app/

Real payments, Steam integration, live inventory, real-time market pricing and
commercial asset licensing remain outside this demo implementation.
