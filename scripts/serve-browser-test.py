"""Local-only signed Telegram fixture. Never use this launcher for deployment."""
import sqlite3
import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main
import uvicorn


async def fixture_telegram(application):
    application.state.bot_username = 'SkinSavoTestBot'
    application.state.telegram_ready = True
    application.state.telegram_menu_ready = True


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='skinsavo-browser-') as directory:
        main.DB_PATH = str(Path(directory) / 'fixture.db')
        main.DATABASE_BACKEND = 'sqlite'
        main.DATABASE_URL = ''
        with closing(sqlite3.connect((ROOT / 'skinsavo.db').as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(main.DB_PATH)) as target:
                source.backup(target)
        main.BOT_TOKEN = '123456789:browser-test-secret-only'
        main.configure_telegram = fixture_telegram
        uvicorn.run(main.app, host='127.0.0.1', port=int(os.environ.get('SKINSAVO_TEST_PORT', '8000')), access_log=False)
