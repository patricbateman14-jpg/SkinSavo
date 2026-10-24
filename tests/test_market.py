import hashlib
import hmac
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
import main


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        main.DB_PATH = str(Path(self.temp.name) / 'test.db')
        main.BOT_TOKEN = 'test-only-token'
        main.ADMIN_TELEGRAM_ID = '1'
        self.client = TestClient(main.app)
        main.init_db()
        with main.db() as conn:
            for name, weapon, rarity, condition, price, stock in [
                ('AK-47 | Redline', 'AK-47', 'Classified', 'Field-Tested', 20, 1),
                ('AWP | Asiimov', 'AWP', 'Covert', 'Minimal Wear', 90, 2),
                ('Glock-18 | Fade', 'Glock-18', 'Restricted', 'Factory New', 50, 3),
            ]:
                conn.execute('INSERT INTO skins (name,weapon,skin,rarity,condition,price,stock,image,description) VALUES (?,?,?,?,?,?,?,?,?)',
                             (name,weapon,name.split('|')[1].strip(),rarity,condition,price,stock,'https://example.com/item.png','Demo listing'))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def headers(self, uid=1, expired=False):
        data = {'auth_date': str(int(time.time()) - (90000 if expired else 0)), 'user': json.dumps({'id':uid,'username':'tester'})}
        secret = hmac.new(b'WebAppData',main.BOT_TOKEN.encode(),hashlib.sha256).digest()
        data['hash'] = hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
        return {'X-Telegram-Init-Data':urlencode(data)}

    def test_combined_filters_and_sort(self):
        result = self.client.get('/api/skins',params={'q':'Redline','category':'Rifles','rarity':'Classified','condition':'Field-Tested','sort':'price_desc'}).json()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['catalog_total'],3)
        self.assertEqual(result['categories']['Pistols'],1)
        self.assertEqual(self.client.get('/api/skins?category=Snipers&rarity=Classified').json()['total'],0)
        self.assertEqual([s['price'] for s in self.client.get('/api/skins?sort=price_desc').json()['items']],[90,50,20])
        self.assertEqual(self.client.get('/api/skins?offset=1&limit=1').json()['items'][0]['id'],2)

    def test_authentication_and_ownership(self):
        self.assertEqual(self.client.get('/api/users/1').status_code,401)
        self.assertEqual(self.client.get('/api/users/2',headers=self.headers()).status_code,403)
        self.assertEqual(self.client.get('/api/inventory',headers=self.headers(expired=True)).status_code,401)
        self.assertEqual(self.client.post('/api/demo/topup',json={'telegram_id':'2','amount':50},headers=self.headers()).status_code,403)

    def test_purchase_sell_and_persistence(self):
        headers=self.headers()
        self.assertEqual(self.client.get('/api/users/1',headers=headers).json()['balance'],0)
        self.assertEqual(self.client.post('/api/demo/purchase',json={'skin_id':1},headers=headers).status_code,409)
        self.client.post('/api/demo/topup',json={'telegram_id':'1','amount':50},headers=headers).raise_for_status()
        self.client.post('/api/demo/purchase',json={'skin_id':1},headers=headers).raise_for_status()
        self.assertEqual(self.client.get('/api/users/1',headers=headers).json()['balance'],30)
        self.assertEqual(self.client.post('/api/demo/purchase',json={'skin_id':1},headers=headers).status_code,409)
        item=self.client.get('/api/inventory',headers=headers).json()['items'][0]
        self.assertEqual(self.client.post(f"/api/demo/inventory/{item['id']}/sell",headers=self.headers(2)).status_code,404)
        self.client.post(f"/api/demo/inventory/{item['id']}/sell",headers=headers).raise_for_status()
        self.assertEqual(self.client.post(f"/api/demo/inventory/{item['id']}/sell",headers=headers).status_code,404)
        self.assertEqual(self.client.get('/api/users/1',headers=headers).json()['balance'],50)
        main.init_db()
        self.assertEqual(len(self.client.get('/api/inventory',headers=headers).json()['items']),1)
        self.assertEqual(self.client.get('/api/skins').json()['total'],3)

    def test_admin_and_invalid_input(self):
        payload={'name':'Test','weapon':'AK-47','skin':'Test','rarity':'Covert','condition':'Factory New','price':10,'stock':1,'image':'https://example.com/test.png'}
        self.assertEqual(self.client.post('/api/admin/skins',json=payload,headers=self.headers(2)).status_code,403)
        self.assertEqual(self.client.post('/api/admin/skins',json=payload,headers=self.headers()).status_code,200)
        self.assertEqual(self.client.post('/api/demo/topup',json={'telegram_id':'1','amount':-1},headers=self.headers()).status_code,422)
        self.assertEqual(self.client.get('/api/skins/999').status_code,404)

    def test_static_assets(self):
        self.assertEqual(self.client.get('/').status_code,200)
        manifest=self.client.get('/static/assets/manifest.json').json()
        for url in manifest.values():
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.content.startswith(b'\x89PNG'))

    def test_last_stock_cannot_be_purchased_twice(self):
        for uid in (1, 2):
            self.client.post('/api/demo/topup', json={'telegram_id':str(uid),'amount':100}, headers=self.headers(uid)).raise_for_status()
        def purchase(uid):
            return self.client.post('/api/demo/purchase', json={'skin_id':1}, headers=self.headers(uid)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(purchase, (1, 2))), [200, 409])
        with main.db() as conn:
            self.assertEqual(conn.execute('SELECT stock FROM skins WHERE id=1').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM inventory').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT SUM(balance) FROM users').fetchone()[0], 180)

    def test_admin_deactivation_preserves_owned_inventory(self):
        headers=self.headers()
        self.client.post('/api/demo/topup',json={'telegram_id':'1','amount':50},headers=headers).raise_for_status()
        self.client.post('/api/demo/purchase',json={'skin_id':1},headers=headers).raise_for_status()
        self.client.delete('/api/admin/skins/1',headers=headers).raise_for_status()
        self.assertEqual(self.client.get('/api/skins/1').status_code,404)
        self.assertEqual(len(self.client.get('/api/inventory',headers=headers).json()['items']),1)


if __name__=='__main__':
    unittest.main()
