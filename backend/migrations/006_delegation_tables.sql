-- 006_delegation_tables.sql
-- ESS/MSS (PRD 13.2): delegasi approval atasan saat cuti (EXP-013).
-- Idempoten; dijalankan sebagai pemilik DB. Tanpa tanda persen di
-- seluruh teks (psycopg3 mem-parse-nya sebagai placeholder).

CREATE TABLE IF NOT EXISTS approval_delegations (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    delegator_employment_id UUID NOT NULL REFERENCES employments (id),
    delegate_employment_id UUID NOT NULL REFERENCES employments (id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'aktif',
    note VARCHAR(255),
    created_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_approval_delegations_tenant_id
    ON approval_delegations (tenant_id);
CREATE INDEX IF NOT EXISTS ix_approval_delegations_delegator
    ON approval_delegations (delegator_employment_id);
CREATE INDEX IF NOT EXISTS ix_approval_delegations_delegate
    ON approval_delegations (delegate_employment_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON approval_delegations TO hrisx_sql;

ALTER TABLE approval_delegations ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_delegations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON approval_delegations;
CREATE POLICY tenant_isolation ON approval_delegations
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());
