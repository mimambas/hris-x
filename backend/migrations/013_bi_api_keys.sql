-- ANL-005: kunci API ekspor data warehouse/BI.

CREATE TABLE IF NOT EXISTS bi_api_keys (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(120) NOT NULL,
    key_hash VARCHAR(64) NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_biapikey_owner
    ON bi_api_keys (tenant_id, owner_user_id);
CREATE INDEX IF NOT EXISTS ix_biapikey_hash ON bi_api_keys (key_hash);

GRANT SELECT, INSERT, UPDATE, DELETE ON bi_api_keys TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['bi_api_keys']
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
