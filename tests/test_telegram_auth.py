import asyncio
import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from aiogram.types import Message
import main


class TelegramAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        main.DB_PATH = str(Path(self.temp.name) / 'test.db')
        main.BOT_TOKEN = '123456:unit-test-secret'
        main.WEBAPP_URL = 'https://skinsavo.example'
        self.client = TestClient(main.app)
        main.init_db()
        self.user = {'id': 900719925474099, 'first_name': 'Aziz', 'last_name': 'Aliyev',
                     'username': 'aziz', 'language_code': 'uz', 'is_premium': True,
                     'photo_url': 'https://t.me/i/userpic/320/example.jpg'}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def signed(self, *, user=None, age=0, extra=None):
        data = {'auth_date': str(int(time.time()) - age),
                'user': json.dumps(self.user if user is None else user, ensure_ascii=False, separators=(',', ':')),
                'query_id': 'test-query'}
        if extra:
            data.update(extra)
        key = hmac.new(b'WebAppData', main.BOT_TOKEN.encode(), hashlib.sha256).digest()
        data['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        return urlencode(data)

    def session(self, data):
        return self.client.get('/api/session', headers={'X-Telegram-Init-Data':data})

    def test_auto_signup_and_idempotent_login(self):
        first = self.session(self.signed())
        self.assertEqual(first.status_code, 200)
        profile = first.json()['user']
        for key in ('username','first_name','last_name','photo_url','language_code','is_premium'):
            self.assertEqual(profile[key], self.user[key])
        self.assertEqual(profile['telegram_id'], str(self.user['id']))
        self.assertEqual(profile['balance'], 0)
        self.assertTrue(profile['last_login_at'])
        with main.db() as conn:
            conn.execute('UPDATE users SET balance=125 WHERE telegram_id=?', (str(self.user['id']),))
        self.user.update(first_name='Yangi ism', username='newname', photo_url='')
        updated = self.session(self.signed()).json()['user']
        self.assertEqual(updated['first_name'], 'Yangi ism')
        self.assertEqual(updated['username'], 'newname')
        self.assertEqual(updated['photo_url'], '')
        self.assertEqual(updated['balance'], 125)
        with main.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_username_and_photo_optional_and_client_name_ignored(self):
        self.user.pop('username')
        self.user.pop('photo_url')
        self.session(self.signed()).raise_for_status()
        result = self.client.get(f"/api/users/{self.user['id']}?username=spoofed", headers={'X-Telegram-Init-Data': self.signed()})
        self.assertEqual(result.json()['username'], '')
        self.assertEqual(result.json()['first_name'], 'Aziz')

    def test_unsigned_browser_and_all_private_routes_blocked(self):
        for path in ('/api/session','/api/skins','/api/skins/1','/api/inventory','/api/users/1','/api/users/1/history'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        self.assertEqual(self.client.get('/api/app-config').status_code, 200)
        with main.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)

    def test_tampering_wrong_token_expiry_and_future(self):
        data = self.signed()
        self.assertEqual(self.session(data.replace('Aziz', 'Attacker')).status_code, 401)
        main.BOT_TOKEN = 'different-secret'
        self.assertEqual(self.session(data).status_code, 401)
        self.assertEqual(self.session(self.signed(age=90000)).status_code, 401)
        self.assertEqual(self.session(self.signed(age=-120)).status_code, 401)
        self.assertEqual(self.session(data + '&auth_date=1').status_code, 401)

    def test_malformed_signed_user_rejected_without_server_error(self):
        for user in ([], 'text', {'id':True}, {'id':-1}, {'id':'123'}, {'id':1,'is_bot':True}, {'id':1,'first_name':[]}):
            with self.subTest(user=user):
                self.assertEqual(self.session(self.signed(user=user)).status_code, 401)
        self.assertEqual(self.session('not-a-query').status_code, 401)
        self.assertEqual(self.session('x' * 17000).status_code, 401)

    def test_signature_field_and_escaped_unicode_url(self):
        self.user['first_name'] = 'O‘tkir / <b>'
        self.user['photo_url'] = 'https://t.me/i/userpic/320/a/b.jpg'
        self.assertEqual(self.session(self.signed(extra={'signature':'telegram-signature'})).status_code, 200)

    def test_old_schema_migration_preserves_balance_and_records(self):
        legacy = Path(self.temp.name) / 'legacy.db'
        with sqlite3.connect(legacy) as conn:
            conn.execute("CREATE TABLE users (telegram_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '', balance REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("INSERT INTO users (telegram_id,username,balance) VALUES ('10','oldname',83.5)")
        conn.close()
        main.DB_PATH = str(legacy)
        main.init_db()
        main.init_db()
        with main.db() as conn:
            user = dict(conn.execute('SELECT * FROM users').fetchone())
        self.assertEqual(user['username'], 'oldname')
        self.assertEqual(user['balance'], 83.5)
        self.assertEqual(user['first_name'], '')

    def test_bot_start_uses_inline_mini_app_button_and_persists_profile(self):
        message = Message.model_validate({'message_id':1, 'date':int(time.time()),
            'chat':{'id':123,'type':'private'}, 'from':{'id':123,'is_bot':False,'first_name':'Bot User','username':'botuser'}})
        bot = AsyncMock()
        # Bind message to the mock bot so Message.answer uses it without network.
        message = message.as_(bot)
        asyncio.run(main.start_handler(message, bot))
        call = bot.call_args.args[0]
        self.assertEqual(call.reply_markup.inline_keyboard[0][0].web_app.url, main.mini_app_launch_url())
        bot.set_chat_menu_button.assert_awaited_once()
        self.assertEqual(bot.set_chat_menu_button.call_args.kwargs['chat_id'], 123)
        self.assertEqual(bot.set_chat_menu_button.call_args.kwargs['menu_button'].web_app.url, main.mini_app_launch_url())
        self.assertTrue(bot.call_args_list[0].args[0].reply_markup.remove_keyboard)
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT first_name FROM users WHERE telegram_id='123'").fetchone()[0], 'Bot User')

    def test_launch_url_preserves_query_and_clears_stale_fragment(self):
        main.WEBAPP_URL = 'https://skinsavo.example/?lang=uz#old-section'
        self.assertEqual(main.mini_app_launch_url(), 'https://skinsavo.example/?lang=uz&miniapp=4')

    def test_main_app_link_only_when_telegram_confirms_configuration(self):
        main.app.state.bot_username = 'SkinSavoTestBot'
        main.app.state.telegram_main_app = False
        self.assertEqual(self.client.get('/api/app-config').json()['mini_app_url'], 'https://t.me/SkinSavoTestBot?start=app')
        main.app.state.telegram_main_app = True
        self.assertEqual(self.client.get('/api/app-config').json()['mini_app_url'], 'https://t.me/SkinSavoTestBot?startapp')


if __name__ == '__main__':
    unittest.main()
