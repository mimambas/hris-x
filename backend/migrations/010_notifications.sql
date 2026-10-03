-- EXP-005: notifikasi in-app + preferensi notifikasi per pengguna.
-- Kanal email/whatsapp belum terhubung; preferensinya disimpan dan
-- berlaku saat kanal pengiriman tersedia.

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    category VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    link VARCHAR(200),
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_notifications_user
    ON notifications (tenant_id, user_id, is_read, created_at);

CREATE TABLE IF NOT EXISTS notification_preferences (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    user_id UUID NOT NULL REFERENCES users(id),
    category VARCHAR(30) NOT NULL,
    channel VARCHAR(20) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_notif_pref_user_cat_channel
        UNIQUE (user_id, category, channel)
);
CREATE INDEX IF NOT EXISTS ix_notif_pref_user
    ON notification_preferences (tenant_id, user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON notifications TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON notification_preferences TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['notifications', 'notification_preferences']
    LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(t) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(t) || ' FORCE ROW LEVEL SECURITY';
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t
              AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE 'CREATE POLICY tenant_isolation ON ' || quote_ident(t)
                || ' USING (tenant_id = app.current_tenant_id())'
                || ' WITH CHECK (tenant_id = app.current_tenant_id())';
        END IF;
    END LOOP;
END $$;
