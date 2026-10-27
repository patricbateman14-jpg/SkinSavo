"""Real PostgreSQL integration checks. Run only against the isolated local test DB."""

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from bot_delivery import TelegramDelivery
from storage import (
    Database,
    StorageFrozen,
    StorageUnavailable,
    connection_settings,
    sqlite_connection,
)
from storage_migration import (
    TABLES,
    MigrationError,
    abort_uncommitted_migration,
    freeze_and_backup,
    migrate_to_postgres,
)

TEST_URL = os.getenv("TEST_POSTGRES_URL", "")


class DatabaseConfigurationTests(unittest.TestCase):
    def test_tls_and_bad_urls_fail_without_exposing_passwords(self):
        for url in (
            "https://private-secret@example.com",
            "postgresql://u:private-secret@example.com/db?sslmode=disable",
        ):
            with self.assertRaises(StorageUnavailable) as error:
                connection_settings(url)
            self.assertNotIn("private-secret", str(error.exception))
        settings = connection_settings(
            "postgresql://postgres.project:encoded%40password@aws-0-region.pooler.supabase.com:5432/postgres"
        )
        self.assertEqual(settings["password"], "encoded@password")
        self.assertTrue(settings["ssl_context"])


@unittest.skipUnless(TEST_URL, "TEST_POSTGRES_URL is not configured")
class PostgresStorageTests(unittest.TestCase):
    def setUp(self):
        url = urlsplit(TEST_URL)
        if (
            url.hostname not in ("127.0.0.1", "localhost", "::1")
            or url.path != "/skinsavo_test"
        ):
            raise RuntimeError(
                "Integration tests require the dedicated localhost skinsavo_test database"
            )
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / "source.db"
        self.previous = (
            main.DB_PATH,
            main.DATABASE_URL,
            main.DATABASE_BACKEND,
            main.BOT_TOKEN,
            main.ADMIN_TELEGRAM_ID,
        )
        main.database.close()
        main.DB_PATH = str(self.source)
        main.DATABASE_BACKEND = "sqlite"
        main.BOT_TOKEN = "postgres-test-only-token"
        main.ADMIN_TELEGRAM_ID = "301"
        main.init_db()
        main.sync_telegram_profile(
            {
                "id": 301,
                "first_name": "O‘tkir <test>",
                "username": "pguser",
                "photo_url": "https://example.com/avatar.jpg",
            }
        )
        with main.db() as conn:
            conn.execute("UPDATE users SET balance=42.3 WHERE telegram_id='301'")
            conn.execute(
                "INSERT INTO skins(id,name,weapon,skin,rarity,condition,price,stock,image,description) VALUES (11,'AK-47 | Redline','AK-47','Redline','Classified','Field-Tested',18.75,2,'https://example.com/item.png','Skin')"
            )
            conn.execute(
                "INSERT INTO inventory(id,telegram_id,skin_id,name,price) VALUES (19,'301',11,'AK-47 | Redline',18.75)"
            )
            conn.execute(
                "INSERT INTO balance_events(id,telegram_id,amount,event_type,note) VALUES (9,'301',0.3,'demo_topup','Sinov ✅')"
            )
            conn.execute(
                "INSERT INTO support_tickets(id,telegram_id,message_id,body) VALUES (7,'301',17,'Private question <safe>')"
            )
            conn.execute(
                "INSERT INTO bot_sessions VALUES ('301','catalog','Redline',?)",
                (time.time() + 1800,),
            )
            conn.execute(
                "INSERT INTO telegram_updates(update_id,payload,owner_id) VALUES (101,?,'301')",
                (json.dumps({"update_id": 101}),),
            )
        self.pg = Database(
            lambda: str(self.source), lambda: TEST_URL, lambda: "postgres"
        )
        with self.pg.postgres_connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS skinsavo CASCADE")
            conn.execute(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF; END $$"
            )
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        main.database.close()
        self.pg.close()
        (
            main.DB_PATH,
            main.DATABASE_URL,
            main.DATABASE_BACKEND,
            main.BOT_TOKEN,
            main.ADMIN_TELEGRAM_ID,
        ) = self.previous
        self.temp.cleanup()

    def migrate(self):
        report = migrate_to_postgres(self.pg)
        main.DATABASE_URL = TEST_URL
        main.DATABASE_BACKEND = "postgres"
        return report

    def headers(self, uid=301):
        fields = {
            "auth_date": str(int(time.time())),
            "user": json.dumps(
                {"id": uid, "first_name": "PG User", "username": "pguser"}
            ),
        }
        secret = hmac.new(
            b"WebAppData", main.BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        fields["hash"] = hmac.new(
            secret,
            "\n".join(
                f"{key}={value}" for key, value in sorted(fields.items())
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        return {"X-Telegram-Init-Data": urlencode(fields)}

    def test_complete_copy_is_verified_and_restarts_do_not_overwrite_new_balances(self):
        report = self.migrate()
        self.assertEqual(set(report["counts"]), set(TABLES))
        self.assertEqual(report["counts"]["users"], 1)
        with main.db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE telegram_id='301'"
            ).fetchone()
            self.assertEqual(user["balance"], Decimal("42.3"))
            self.assertEqual(user["first_name"], "O‘tkir <test>")
            self.assertTrue(user["photo_url"])
            conn.execute("UPDATE users SET balance=75 WHERE telegram_id='301'")
        self.assertTrue(migrate_to_postgres(self.pg)["already_migrated"])
        with main.db() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT balance FROM users WHERE telegram_id='301'"
                ).fetchone()[0],
                75,
            )
        with self.assertRaises(StorageFrozen):
            with sqlite_connection(self.source):
                pass
        self.assertEqual(len(list(self.source.parent.glob("*.pre-supabase-*.db"))), 1)
        with self.assertRaises(MigrationError):
            abort_uncommitted_migration(self.pg)

    def test_pooler_float_formatting_preserves_queue_timestamps_exactly(self):
        claimed_at = 1792912401.1234567
        with main.db() as conn:
            conn.execute(
                "UPDATE telegram_updates SET claimed_at=?, available_at=? WHERE update_id=101",
                (claimed_at, claimed_at + 60),
            )
        # Supabase's pooler defaults to 15 significant digits. Seed that real
        # server setting to reproduce truncation in the DB-API text protocol.
        pool = self.pg.pool()
        raw = pool.acquire()
        cursor = raw.cursor()
        cursor.execute("SET SESSION extra_float_digits=0")
        raw.commit()
        cursor.close()
        pool.release(raw)
        self.migrate()
        with self.pg.postgres_connection() as conn:
            row = conn.execute(
                "SELECT claimed_at,available_at FROM telegram_updates WHERE update_id=101"
            ).fetchone()
        self.assertEqual(row["claimed_at"], claimed_at)
        self.assertEqual(row["available_at"], claimed_at + 60)

    def test_recently_closed_pool_socket_recovers_before_running_work(self):
        self.migrate()
        pool = self.pg.pool()
        raw = pool.acquire()
        raw.close()
        pool.release(raw)
        with self.pg.postgres_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_reused_connection_rolls_back_failed_work_and_restores_local_settings(self):
        self.migrate()
        with self.assertRaisesRegex(ValueError, "cancel work"):
            with self.pg.postgres_connection() as conn:
                conn.execute("UPDATE users SET balance=0 WHERE telegram_id='301'")
                conn.execute("SET LOCAL search_path=public")
                conn.execute("SET LOCAL extra_float_digits=0")
                raise ValueError("cancel work")
        with self.pg.postgres_connection() as conn:
            self.assertEqual(conn.execute("SELECT balance FROM users WHERE telegram_id='301'").fetchone()[0], Decimal("42.3"))
            self.assertEqual(conn.execute("SHOW extra_float_digits").fetchone()[0], "3")

    def test_api_login_topup_purchase_sale_and_sequence_continue_after_import(self):
        self.migrate()
        session = self.client.get("/api/session", headers=self.headers())
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["user"]["balance"], 42.3)
        topup = self.client.post(
            "/api/demo/topup",
            headers=self.headers(),
            json={"telegram_id": "301", "amount": 0.2},
        )
        self.assertEqual(topup.status_code, 200)
        self.assertEqual(topup.json()["balance"], 42.5)
        purchase = self.client.post(
            "/api/demo/purchase", headers=self.headers(), json={"skin_id": 11}
        )
        self.assertEqual(purchase.status_code, 200)
        inventory = self.client.get("/api/inventory", headers=self.headers()).json()[
            "items"
        ]
        new_id = max(item["id"] for item in inventory)
        self.assertGreater(new_id, 19)
        sale = self.client.post(
            f"/api/demo/inventory/{new_id}/sell", headers=self.headers()
        )
        self.assertEqual(sale.status_code, 200)
        self.assertEqual(
            self.client.get("/api/users/301", headers=self.headers()).json()["balance"],
            42.5,
        )
        self.assertEqual(
            self.client.get("/api/users/302", headers=self.headers()).status_code, 403
        )
        self.assertEqual(self.client.get("/api/inventory").status_code, 401)

    def test_concurrent_last_stock_cannot_be_bought_twice(self):
        self.migrate()
        main.sync_telegram_profile({"id": 302, "first_name": "Other"})
        with main.db() as conn:
            conn.execute("DELETE FROM inventory")
            conn.execute("UPDATE users SET balance=100")
            conn.execute("UPDATE skins SET stock=1 WHERE id=11")

        def buy(uid):
            return self.client.post(
                "/api/demo/purchase", headers=self.headers(uid), json={"skin_id": 11}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(buy, (301, 302)))
        self.assertEqual(sorted(results), [200, 409])
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT SUM(balance) FROM users").fetchone()[0],
                Decimal("181.25"),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0], 1
            )

    def test_same_account_balance_is_locked_before_spending(self):
        self.migrate()
        with main.db() as conn:
            conn.execute("DELETE FROM inventory")
            conn.execute("UPDATE users SET balance=20")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: self.client.post(
                        "/api/demo/purchase",
                        headers=self.headers(),
                        json={"skin_id": 11},
                    ).status_code,
                    range(2),
                )
            )
        self.assertEqual(sorted(results), [200, 409])
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT balance FROM users").fetchone()[0], Decimal("1.25")
            )

    def test_duplicate_sale_refunds_only_once(self):
        self.migrate()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: self.client.post(
                        "/api/demo/inventory/19/sell", headers=self.headers()
                    ).status_code,
                    range(2),
                )
            )
        self.assertEqual(sorted(results), [200, 404])
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT balance FROM users").fetchone()[0],
                Decimal("61.05"),
            )
            self.assertEqual(conn.execute("SELECT stock FROM skins").fetchone()[0], 3)

    def test_queue_claims_are_locked_and_callbacks_use_portable_queries(self):
        self.migrate()
        delivery = TelegramDelivery(main.db, None, None)
        self.assertFalse(delivery.enqueue({"update_id": 101}))
        delivery.enqueue({"update_id": 102, "message": {"from": {"id": 302}}})
        with ThreadPoolExecutor(max_workers=2) as executor:
            rows = list(executor.map(lambda _: delivery.claim(), range(2)))
        self.assertEqual({row["update_id"] for row in rows}, {101, 102})
        self.assertIsNone(delivery.claim())
        found = main.chat.list_data(301, "catalog", 0)
        self.assertEqual(found[1], 1)
        self.assertEqual(main.chat.save_ticket(301, 17, "Duplicate"), 7)
        with main.db() as conn:
            self.assertTrue(
                conn.execute(
                    "SELECT * FROM support_tickets WHERE id=? AND (telegram_id=? OR ?=1)",
                    (7, "999", 1),
                ).fetchone()
            )

    def test_failed_copy_rolls_back_target_and_resume_uses_same_backup(self):
        with patch(
            "storage_migration.import_snapshot",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(RuntimeError):
                migrate_to_postgres(self.pg)
        with self.pg.postgres_connection() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM storage_migrations").fetchone()[0], 0
            )
        self.assertEqual(
            self.client.get("/api/session", headers=self.headers()).status_code, 503
        )
        self.assertEqual(len(list(self.source.parent.glob("*.pre-supabase-*.db"))), 1)
        self.assertFalse(migrate_to_postgres(self.pg)["already_migrated"])
        self.assertEqual(len(list(self.source.parent.glob("*.pre-supabase-*.db"))), 1)

    def test_atomic_queue_claim_serializes_a_chat_and_recovers_exhausted_head(self):
        self.migrate()
        delivery=TelegramDelivery(main.db,None,None)
        delivery.enqueue({'update_id':102,'message':{'from':{'id':301}}})
        with ThreadPoolExecutor(max_workers=2) as executor:
            rows=list(executor.map(lambda _:delivery.claim(),range(2)))
        self.assertEqual(sum(row is not None for row in rows),1)
        with main.db() as conn:
            conn.execute("UPDATE telegram_updates SET attempts=5, claimed_at=? WHERE update_id=101", (time.time()-121,))
        self.assertEqual(delivery.claim()['update_id'],102)
        with main.db() as conn:
            self.assertEqual(conn.execute('SELECT status FROM telegram_updates WHERE update_id=101').fetchone()[0],'failed')
    def test_abort_then_new_writes_creates_a_new_snapshot(self):
        self.pg.init_postgres_schema()
        first, _ = freeze_and_backup(self.source, self.pg)
        abort_uncommitted_migration(self.pg)
        with main.db() as conn:
            conn.execute("UPDATE users SET balance=99 WHERE telegram_id='301'")
        self.migrate()
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT balance FROM users").fetchone()[0], 99
            )
        self.assertEqual(len(list(self.source.parent.glob("*.pre-supabase-*.db"))), 2)

    def test_nonempty_target_and_unprepared_source_are_rejected_without_freezing(self):
        self.pg.init_postgres_schema()
        with self.pg.postgres_connection() as conn:
            conn.execute("INSERT INTO users(telegram_id,balance) VALUES ('999',50)")
        with self.assertRaises(MigrationError):
            migrate_to_postgres(self.pg)
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT balance FROM users").fetchone()[0], 42.3
            )
        with self.pg.postgres_connection() as conn:
            conn.execute("DELETE FROM users")
        with main.db() as conn:
            conn.execute("DROP TABLE storage_meta")
        with self.assertRaises(MigrationError):
            migrate_to_postgres(self.pg)

    def test_private_schema_rls_blocks_publishable_role(self):
        self.migrate()
        with main.db() as conn:
            self.assertFalse(
                conn.execute(
                    "SELECT has_schema_privilege('anon','skinsavo','USAGE')"
                ).fetchone()[0]
            )
            self.assertFalse(
                conn.execute(
                    "SELECT has_table_privilege('anon','skinsavo.users','SELECT')"
                ).fetchone()[0]
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname='skinsavo' AND relrowsecurity"
                ).fetchone()[0],
                8,
            )
        with self.assertRaises(StorageUnavailable):
            with main.db() as conn:
                conn.execute("SET LOCAL ROLE anon")
                conn.execute("SELECT * FROM skinsavo.users").fetchall()

    def test_deleted_high_ids_are_not_reused_and_admin_creation_works(self):
        with main.db() as conn:
            conn.execute(
                "INSERT INTO skins(id,name,weapon,skin,rarity,condition,price,stock,image,description) SELECT 1000,name,weapon,skin,rarity,condition,price,stock,image,description FROM skins WHERE id=11"
            )
            conn.execute("DELETE FROM skins WHERE id=1000")
        self.migrate()
        response = self.client.post(
            "/api/admin/skins",
            headers=self.headers(),
            json={
                "name": "AWP | Test",
                "weapon": "AWP",
                "skin": "Test",
                "rarity": "Covert",
                "condition": "Factory New",
                "price": 12.3,
                "stock": 1,
                "image": "https://example.com/image.png",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["item"]["id"], 1000)


if __name__ == "__main__":
    unittest.main()
