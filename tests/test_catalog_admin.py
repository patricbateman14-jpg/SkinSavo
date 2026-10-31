import hashlib
import hmac
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from PIL import Image

import main


class CatalogAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = (main.DB_PATH, main.DATABASE_BACKEND, main.DATABASE_URL, main.BOT_TOKEN, main.ADMIN_TELEGRAM_ID)
        main.DB_PATH = str(Path(self.temp.name) / "catalog.db")
        main.DATABASE_BACKEND = "sqlite"
        main.DATABASE_URL = ""
        main.BOT_TOKEN = "catalog-test-only"
        main.ADMIN_TELEGRAM_ID = "1"
        main.init_db()
        self.client = TestClient(main.app)
        self.payload = dict(weapon="AK-47", skin="Aphrodite", rarity="Covert", condition="Battle-Scarred",
                            price=12.45, stock=397, image="https://example.com/weapon.png")

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()
        main.DB_PATH, main.DATABASE_BACKEND, main.DATABASE_URL, main.BOT_TOKEN, main.ADMIN_TELEGRAM_ID = self.previous

    def headers(self, uid=1, **extra):
        data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid})}
        key = hmac.new(b"WebAppData", main.BOT_TOKEN.encode(), hashlib.sha256).digest()
        data["hash"] = hmac.new(key, "\n".join(f"{k}={v}" for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        return {"X-Telegram-Init-Data": urlencode(data), **extra}

    def png(self, size=(80, 40), format="PNG"):
        output = io.BytesIO()
        Image.new("RGBA" if format == "PNG" else "RGB", size).save(output, format=format)
        return output.getvalue()

    def create(self, **changes):
        return self.client.post("/api/admin/skins", json={**self.payload, **changes}, headers=self.headers())

    def test_upload_requires_admin_and_png_not_just_a_filename(self):
        path = "/api/admin/images"
        self.assertEqual(self.client.post(path, content=self.png()).status_code, 401)
        self.assertEqual(self.client.post(path, content=self.png(), headers=self.headers(2, **{"Content-Type": "image/png"})).status_code, 403)
        self.assertEqual(self.client.post(path, content=self.png(), headers=self.headers(**{"Content-Type": "text/plain"})).status_code, 415)
        for content in (b"<svg onload='alert(1)'/>", self.png(format="JPEG"), self.png((16, 16))):
            self.assertEqual(self.client.post(path, content=content, headers=self.headers(**{"Content-Type": "image/png"})).status_code, 422)
        self.assertEqual(self.client.post(path, content=b"x" * (8 * 1024 * 1024 + 1), headers=self.headers(**{"Content-Type": "image/png"})).status_code, 413)

    def test_png_transparency_persistence_dedup_and_catalog_url(self):
        replies = [self.client.post("/api/admin/images", content=self.png(), headers=self.headers(**{"Content-Type": "image/png"})).json() for _ in range(2)]
        self.assertEqual(replies[0]["url"], replies[1]["url"])
        self.assertTrue(replies[0]["transparent"])
        response = self.client.get(replies[0]["url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response.headers["cache-control"])
        with Image.open(io.BytesIO(response.content)) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(self.create(image=replies[0]["url"]).status_code, 200)
        main.init_db()
        self.assertEqual(self.client.get(replies[0]["url"]).content, response.content)
        self.assertEqual(self.client.get("/media/skins/main.py").status_code, 404)
        self.assertEqual(self.create(image="/media/skins/" + "a" * 64 + ".png").status_code, 422)

    def test_validation_and_canonical_choices(self):
        for changes in ({"rarity": "classifid"}, {"condition": "invalid"}, {"stock": -1}, {"stock": 1.5},
                        {"weapon": "  "}, {"skin": "  "}, {"price": -1}, {"price": 1.234}, {"image": "javascript:alert(1)"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 422)
        item = self.create(rarity="covert", condition="bs").json()["item"]
        self.assertEqual(item["name"], "AK-47 | Aphrodite")
        self.assertEqual(item["rarity"], "Covert")
        self.assertEqual(item["condition"], "Battle-Scarred")

    def test_som_balance_purchase_and_currency_metadata(self):
        self.assertEqual(self.client.get("/api/health").json()["currency"], "UZS")
        self.assertEqual(self.client.get("/api/session", headers=self.headers()).json()["currency"], "UZS")
        item = self.create(price=136885, stock=1).json()["item"]
        self.client.post("/api/demo/topup", json={"telegram_id": "1", "amount": 150000}, headers=self.headers()).raise_for_status()
        self.client.post("/api/demo/purchase", json={"skin_id": item["id"]}, headers=self.headers()).raise_for_status()
        self.assertEqual(self.client.get("/api/users/1", headers=self.headers()).json()["balance"], 13115)
        self.assertEqual(self.client.post("/api/demo/topup", json={"telegram_id": "1", "amount": 10000001}, headers=self.headers()).status_code, 422)

    def test_admin_edits_and_archive_do_not_change_owned_items(self):
        item = self.create(stock=2).json()["item"]
        self.client.post("/api/demo/topup", json={"telegram_id": "1", "amount": 50}, headers=self.headers()).raise_for_status()
        self.client.post("/api/demo/purchase", json={"skin_id": item["id"]}, headers=self.headers()).raise_for_status()
        path = f"/api/admin/skins/{item['id']}"
        self.assertEqual(self.client.put(path, json=self.payload, headers=self.headers(2)).status_code, 403)
        changed = {**self.payload, "price": 45, "stock": 1, "rarity": "Classified", "skin": "Updated"}
        self.assertEqual(self.client.put(path, json=changed, headers=self.headers()).status_code, 200)
        owned = self.client.get("/api/inventory", headers=self.headers()).json()["items"][0]
        self.assertEqual(owned["price"], 12.45)
        self.assertEqual(owned["name"], "AK-47 | Aphrodite")
        self.client.delete(path, headers=self.headers()).raise_for_status()
        self.assertEqual(self.client.get(f"/api/skins/{item['id']}", headers=self.headers()).status_code, 404)
        listed = self.client.get("/api/admin/skins?q=Updated", headers=self.headers()).json()
        self.assertEqual(listed["items"][0]["active"], 0)
        self.assertEqual(self.client.get("/api/admin/skins", headers=self.headers(2)).status_code, 403)
        self.client.put(path, json={**changed, "active": True}, headers=self.headers()).raise_for_status()
        self.assertEqual(self.client.get(f"/api/skins/{item['id']}", headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.put("/api/admin/skins/99999", json=self.payload, headers=self.headers()).status_code, 404)
