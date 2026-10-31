-- One-off operator action explicitly requested by the owner on 2026-10-31.
-- Run as the Supabase project owner after deploying the UZS application.
-- The receipt prevents repeating the reset; changed live counts abort it.
BEGIN;
CREATE SCHEMA IF NOT EXISTS skinsavo_ops AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA skinsavo_ops FROM PUBLIC, anon, authenticated, skinsavo_runtime;
CREATE TABLE IF NOT EXISTS skinsavo_ops.demo_resets (
    reset_key TEXT PRIMARY KEY,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    before_state JSONB NOT NULL
);
ALTER TABLE skinsavo_ops.demo_resets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE skinsavo_ops.demo_resets FROM PUBLIC, anon, authenticated, skinsavo_runtime;
LOCK TABLE skinsavo.users, skinsavo.skins, skinsavo.inventory, skinsavo.balance_events IN ACCESS EXCLUSIVE MODE;
DO $reset$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM skinsavo_ops.demo_resets WHERE reset_key='uzs_fresh_start_20261031') THEN
        IF (SELECT COUNT(*) FROM skinsavo.skins) <> 1
           OR NOT EXISTS (SELECT 1 FROM skinsavo.skins WHERE id=9 AND name='salom')
           OR (SELECT COUNT(*) FROM skinsavo.inventory) <> 2
           OR (SELECT COUNT(*) FROM skinsavo.balance_events) <> 8 THEN
            RAISE EXCEPTION 'Demo state changed since inspection; reset aborted';
        END IF;
        INSERT INTO skinsavo_ops.demo_resets(reset_key, before_state)
        SELECT 'uzs_fresh_start_20261031', jsonb_build_object(
            'balances', (SELECT jsonb_agg(jsonb_build_object('telegram_id',telegram_id,'balance',balance)) FROM skinsavo.users),
            'skins', (SELECT jsonb_agg(to_jsonb(s)) FROM skinsavo.skins s),
            'inventory', (SELECT jsonb_agg(to_jsonb(i)) FROM skinsavo.inventory i),
            'balance_events', (SELECT jsonb_agg(to_jsonb(e)) FROM skinsavo.balance_events e)
        );
        DELETE FROM skinsavo.inventory;
        DELETE FROM skinsavo.balance_events;
        DELETE FROM skinsavo.skins WHERE id=9;
        UPDATE skinsavo.users SET balance=0 WHERE balance<>0;
    END IF;
END $reset$;
COMMIT;
SELECT (SELECT COUNT(*) FROM skinsavo.skins) AS skins,
       (SELECT COUNT(*) FROM skinsavo.inventory) AS inventory,
       (SELECT COUNT(*) FROM skinsavo.balance_events) AS balance_events,
       (SELECT COUNT(*) FROM skinsavo.users WHERE balance<>0) AS nonzero_balances,
       (SELECT COUNT(*) FROM skinsavo.users) AS preserved_profiles,
       EXISTS (SELECT 1 FROM skinsavo_ops.demo_resets WHERE reset_key='uzs_fresh_start_20261031') AS reset_recorded;
