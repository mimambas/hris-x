-- 009_data_changes.sql
-- Perubahan data pribadi via approval + OTP rekening (EXP-004,
-- PRD 13.1). Termasuk kolom alamat domisili pada persons yang belum
-- ada. Idempoten; dijalankan sebagai pemilik DB. Tanpa tanda persen
-- di seluruh teks (psycopg3 mem-parse-nya sebagai placeholder).

ALTER TABLE persons ADD COLUMN IF NOT EXISTS address TEXT;

CREATE TABLE IF NOT EXISTS data_change_requests (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    person_id UUID NOT NULL REFERENCES persons (id),
    change_type VARCHAR(20) NOT NULL,
    old_values JSON NOT NULL DEFAULT '{}',
    new_values JSON NOT NULL DEFAULT '{}',
    status VARCHAR(25) NOT NULL DEFAULT 'menunggu_persetujuan',
    note VARCHAR(500),
    otp_hash VARCHAR(64),
    otp_code VARCHAR(6),
    otp_expires_at TIMESTAMPTZ,
    otp_attempts INTEGER NOT NULL DEFAULT 0,
    otp_verified_at TIMESTAMPTZ,
    decided_by_user_id UUID REFERENCES users (id),
    decision_reason VARCHAR(500),
    decided_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dcr_tenant_id
    ON data_change_requests (tenant_id);
CREATE INDEX IF NOT EXISTS ix_dcr_employment_id
    ON data_change_requests (employment_id);
CREATE INDEX IF NOT EXISTS ix_dcr_person_id
    ON data_change_requests (person_id);
CREATE INDEX IF NOT EXISTS ix_dcr_status
    ON data_change_requests (status);

GRANT SELECT, INSERT, UPDATE, DELETE ON data_change_requests
TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['data_change_requests']
    LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(t)
            || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(t)
            || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'DROP POLICY IF EXISTS tenant_isolation ON '
            || quote_ident(t);
        EXECUTE 'CREATE POLICY tenant_isolation ON ' || quote_ident(t)
            || ' USING (tenant_id = app.current_tenant_id())'
            || ' WITH CHECK (tenant_id = app.current_tenant_id())';
    END LOOP;
END
$$;
