-- EXP-012: permintaan tukar shift satu hari antar karyawan.

CREATE TABLE IF NOT EXISTS shift_swap_requests (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    requester_employment_id UUID NOT NULL REFERENCES employments(id),
    partner_employment_id UUID NOT NULL REFERENCES employments(id),
    swap_date DATE NOT NULL,
    requester_shift_id UUID NOT NULL REFERENCES shifts(id),
    partner_shift_id UUID NOT NULL REFERENCES shifts(id),
    reason VARCHAR(500),
    warnings JSON NOT NULL DEFAULT '[]',
    status VARCHAR(25) NOT NULL DEFAULT 'menunggu_partner',
    partner_decided_at TIMESTAMPTZ,
    decided_by_user_id UUID REFERENCES users(id),
    decision_reason VARCHAR(500),
    decided_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_swap_requester
    ON shift_swap_requests (tenant_id, requester_employment_id, status);
CREATE INDEX IF NOT EXISTS ix_swap_partner
    ON shift_swap_requests (tenant_id, partner_employment_id, status);
CREATE INDEX IF NOT EXISTS ix_swap_date
    ON shift_swap_requests (tenant_id, swap_date);

GRANT SELECT, INSERT, UPDATE, DELETE ON shift_swap_requests TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['shift_swap_requests']
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
