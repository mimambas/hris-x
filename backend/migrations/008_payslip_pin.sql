-- 008_payslip_pin.sql
-- PIN akses slip gaji self-service (EXP-003, PRD 13.1). Satu PIN
-- (hash bcrypt) per akun pengguna; 5 kegagalan verifikasi beruntun
-- mengunci 15 menit. HR mereset dengan menghapus baris ini.
-- Idempoten; dijalankan sebagai pemilik DB. Tanpa tanda persen di
-- seluruh teks (psycopg3 mem-parse-nya sebagai placeholder).

CREATE TABLE IF NOT EXISTS payslip_pins (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    user_id UUID NOT NULL REFERENCES users (id),
    pin_hash VARCHAR(255) NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_payslip_pins_tenant_user
        UNIQUE (tenant_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_payslip_pins_tenant_id
    ON payslip_pins (tenant_id);
CREATE INDEX IF NOT EXISTS ix_payslip_pins_user_id
    ON payslip_pins (user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON payslip_pins TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['payslip_pins']
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
