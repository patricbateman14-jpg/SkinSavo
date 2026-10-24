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
BOT_USERNAME is optional and is resolved from the token. The web service also
handles bot chat through an authenticated webhook; no separate bot worker is
needed. Startup registers commands and installs /telegram/webhook on WEBAPP_URL.
It switches this bot from polling/any previous webhook to this deployment and
preserves Telegram's pending updates. Do not run a poller alongside it.
ADMIN_TELEGRAM_ID grants
the matching signed user access to the existing admin listing panel.

Verified login automatically creates or updates ID, name, username, photo URL
(when Telegram provides it), language and Premium flag. Balances and inventory
are preserved. Usernames and photos are optional. Client-supplied profile fields
are ignored. No phone number, password, or contact permission is requested.
The gate remains until the backend confirms the Telegram signature. Forged,
expired, duplicated or malformed credentials are rejected by the server.
The branded splash remains for at least three seconds and waits longer for a
slow profile response. A small early script starts verification before the
application, fonts and artwork. Fresh signed launch fragment/query data takes
precedence over cached SDK credentials. Temporary network errors and 5xx
responses retry up to three times with bounded timeouts. Invalid signatures
are never accepted or repeatedly retried. No new registration is created by a retry.

Telegram launch data is re-read during initialization; native bridges get up
to ten seconds and late credentials can recover the gate automatically for
thirty seconds, or on hash/focus/online events. Fetch timeouts use AbortController
without requiring AbortSignal.timeout in older WebViews. A signed launch fragment
is retained for deep-page refresh when sessionStorage is disabled. No profile
is trusted until the backend verifies its Telegram signature.

Fonts load without blocking scripts. Artwork and catalog requests run in parallel
and cannot hold the verified profile behind the login screen. The official
Telegram SDK is served locally from static/telegram-web-app.js.
It loads asynchronously: a slow SDK download cannot block verification or the
page, and native controls are attached when it arrives.
Plain Telegram browser tabs and old reply-keyboard buttons do not provide Mini
App credentials: use the bot's SkinSavo menu button or a configured Main Mini App.
The bot's /start handler removes old reply keyboards, replaces per-chat menu
overrides and sends inline Mini App buttons. python main.py remains a local-only
polling alternative and refuses to start when a webhook is already active.

## Bot chat

Private chat includes a compact inline menu, profile, demo balance, inventory,
history, paginated skin catalog, skin details, name search, help and support.
Commands are installed in Telegram's command menu. Ordinary skin-name messages
search the same database as the site; common Uzbek menu/login phrases also work.
Buttons open the relevant Mini App URL with the existing signed automatic login.
Chat does not execute purchases, sales or top-ups; those actions are confirmed
in the existing application.

/support collects one text message, creates a durable ticket and supports
/cancel. /tickets shows only that user's requests. ADMIN_TELEGRAM_ID enables
/admin and /reply TICKET_ID MESSAGE. Replies are sent only after that explicit
administrator command; answered tickets do not send a second reply. Users,
balances, profile photos and inventory are shared with the site and preserved.
Group chats and callbacks from another chat cannot expose account information.
Message content is escaped before HTML rendering, and per-user flood control
limits repeated chat actions.

Webhook requests require X-Telegram-Bot-Api-Secret-Token. The secret is derived
from BOT_TOKEN unless TELEGRAM_WEBHOOK_SECRET is explicitly configured. It is
never returned to clients. Updates commit to a SQLite inbox before HTTP 200;
duplicate update IDs are ignored. The worker preserves each user's update order,
retries temporary failures up to five attempts, respects Telegram rate limits
and recovers interrupted processing. Successful payloads are cleared, leaving
deduplication metadata. Failed inbox rows retain the payload for operator review.
An abrupt crash between sending a Telegram message and saving its delivery
result can repeat that outgoing reply; Telegram does not provide a send-message
idempotency key. Support-ticket creation itself is deduplicated.

Bot protocol references: [Telegram webhooks](https://core.telegram.org/bots/api#setwebhook)
and [aiogram update dispatch](https://docs.aiogram.dev/en/latest/dispatcher/webhook.html).

New accounts start at zero. Explicit demo top-ups add simulated funds. Demo
purchases validate stock and balance in a SQLite write transaction and persist
inventory and history. Selling an owned demo item refunds its recorded purchase
price once. Admin deletion deactivates listings, preserving inventory. Existing
balances and database records are preserved. Startup never deletes demo rows.

## Catalog and artwork

Each main feature has a shareable URL: `/` (home), `/skins` (catalog),
`/skins/123` (skin detail), `/profile`, `/inventory`, `/balance`,
`/balance/topup`, `/history`, `/faq` and `/admin`. Account actions open full
pages. Direct links and refresh return the application shell; every page still
requires verified Telegram login. Unknown paths return 404.

Navigation supports browser back/forward and Telegram's Back button. Catalog
search, sorting and filters remain in the URL when opening a skin and returning.
The initial login splash stays for at least three seconds; navigation within
the authenticated app does not restart it.

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
node scripts/check-pages.cjs
```

Browser checks require installed Chrome on Windows and the isolated test launcher
above. It copies the local catalog into a temporary database, uses a test-only
token, and makes no Telegram API calls. Never deploy that launcher. Browser tests
can use another port via SKINSAVO_TEST_PORT on the launcher and SKINSAVO_TEST_URL
on the check scripts. They cover unsigned/forged rejection and HMAC-verified
automatic login, then test six
viewport widths, images, catalog controls, profile, inventory and theme. The
Telegram SDK is simulated with test-signed initData; the actual backend signature
check runs unchanged. Screenshots go to ignored test-results/. No frontend build
is required. Page checks also exercise direct links, refresh, back/forward,
filter URLs and the persisted demo top-up/purchase/sale flow. Start a fresh
isolated launcher before repeating the page transaction checks. The Telegram
entry checks use the locally served official SDK and cover late bridges,
expired SDK cache with a fresh launch, disabled storage, older timeout APIs,
temporary network/server/proxy failures, and stalled nonessential resources.
Actual Telegram-client login
still needs a real user to open the bot.

## Deployment

railway.json starts the existing ASGI app and checks /api/health. The existing
Render blueprint is retained. Set DATABASE_PATH to the database on the existing
persistent volume. Preserve that path and volume; never delete a database to
refresh catalog data. Startup adds the inventory table without changing rows.

Deploy the intended GitHub commit through the existing Railway service and
verify both its commit and /api/health version 0.4.0. The health response reports
telegram_configured, telegram_ready, telegram_menu_ready, telegram_webhook_ready
and telegram_chat_worker_ready without credentials. Confirm both webhook and
worker readiness when deploying chat changes. Bot and delivery tests mock all
Telegram sends; production verification does not send unsolicited test messages.
A healthy URL alone does
not prove the intended commit deployed.

Production URL: https://skinsavo-web-production.up.railway.app/

Real payments, Steam integration, live inventory, real-time market pricing and
commercial asset licensing remain outside this demo implementation.
