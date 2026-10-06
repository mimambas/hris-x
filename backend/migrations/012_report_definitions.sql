-- ANL-002: definisi laporan tersimpan report builder.

CREATE TABLE IF NOT EXISTS report_definitions (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(120) NOT NULL,
    spec JSON NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reportdef_owner
    ON report_definitions (tenant_id, owner_user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON report_definitions TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['report_definitions']
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
