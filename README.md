# SkinSavo

CS2 demo marketplace on FastAPI / vanilla JavaScript, with shared SQLite or
Supabase PostgreSQL storage for the site and Telegram bot.
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
never returned to clients. Updates commit to the configured database inbox before HTTP 200;
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
Render blueprint is retained. Keep DATABASE_PATH pointing to the existing SQLite
database and retain its persistent volume during the Supabase cutover.
Startup adds missing tables/columns without replacing existing records.

## Move existing data to Supabase

The server uses a PostgreSQL connection URI, not the public publishable key.
Copy the **Session pooler** URI from the Supabase project's Connect dialog into
Railway's secret DATABASE_URL variable. Percent-encode special password
characters. An example without credentials is in .env.example. TLS is required
for external databases. The connection pool uses at most five connections per
application process and also works with transaction pooling; search_path and
time zone are set within each transaction.

The target is the private **skinsavo** schema. It has RLS enabled and no grants
to Supabase anon/authenticated roles. All site and bot access continues through
the existing Telegram-verified backend. Publishable keys do not authorize reads
or writes to these account tables. Supabase Auth is not required for Telegram login.

1. Deploy this compatibility version with DATABASE_BACKEND=sqlite (the default).
   DATABASE_URL may already be present. Confirm /api/health reports this commit
   and database_backend=sqlite. This stage prepares the existing source for a
   coordinated freeze; the URL alone does not activate a different database.
2. Set DATABASE_BACKEND=postgres in Railway Variables and redeploy. The startup
   freezes writes to the existing SQLite source, creates a same-volume snapshot,
   imports all seven application tables in one PostgreSQL transaction, and checks
   every row count and content checksum before committing. IDs, historical ID
   sequences, profile fields, balances, history, inventory, support tickets,
   conversation state and bot inbox records are retained. Expect a short
   maintenance interval during the switch.
3. Confirm /api/health reports database_backend=postgres and
   database_migration_verified=true, plus the expected Git revision and bot
   readiness. In Supabase Dashboard select the skinsavo schema to inspect tables.

The original SQLite database remains frozen and its *.pre-supabase-*.db snapshot
is retained. Neither is uploaded to Git. Subsequent restarts use the migration
receipt and never re-import old balances over new PostgreSQL data. A missing
source, an unprepared source, a nonempty unverified target or a copy mismatch
stops the migration. PostgreSQL failures never switch the app back to SQLite.

For manual operation inside the existing Railway service/volume:

```sh
python scripts/migrate_database.py --check
python scripts/migrate_database.py
```

If an import fails after the source freeze, fix the target connection/data issue
and redeploy to resume the same snapshot. To abandon an uncommitted import,
restore DATABASE_BACKEND=sqlite and run
`python scripts/migrate_database.py --abort-uncommitted` against that same source
and target. It thaws SQLite only after proving the target has no migration
receipt and no application rows. A committed cutover cannot be rolled back this
way because PostgreSQL may already contain newer balances.

PostgreSQL integration tests use an isolated local database and refuse a remote
or differently named target. They reset only the dedicated test schema:

```powershell
docker run --detach --rm --name skinsavo-postgres-test --publish 127.0.0.1:55432:5432 --env POSTGRES_PASSWORD=skinsavo-local-test-only --env POSTGRES_DB=skinsavo_test postgres:17-alpine
$env:TEST_POSTGRES_URL='postgresql://postgres:skinsavo-local-test-only@127.0.0.1:55432/skinsavo_test?sslmode=disable'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
docker stop skinsavo-postgres-test
```

Without TEST_POSTGRES_URL, PostgreSQL integration checks are skipped; existing
SQLite tests remain isolated from any production DATABASE_URL. Migration tests
cover data preservation, restart/resume, rejected unsafe targets, backup recovery,
concurrent purchases/sales, inbox locks, sequences and RLS.
Connection reference: [Supabase PostgreSQL connections](https://supabase.com/docs/guides/database/connecting-to-postgres).

Deploy the intended GitHub commit through the existing Railway service and
verify both its commit and /api/health version 0.4.0. The health response reports
telegram_configured, telegram_ready, telegram_menu_ready, telegram_webhook_ready
and telegram_chat_worker_ready without credentials. Confirm both webhook and
worker readiness when deploying chat changes. database_backend and
database_migration_verified identify the active storage without revealing
credentials. Bot and delivery tests mock all
Telegram sends; production verification does not send unsolicited test messages.
A healthy URL alone does
not prove the intended commit deployed.

Production URL: https://skinsavo-web-production.up.railway.app/

Real payments, Steam integration, live inventory, real-time market pricing and
commercial asset licensing remain outside this demo implementation.
