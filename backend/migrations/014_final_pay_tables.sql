-- PAY-014: tabel konfigurasi pesangon (bracket masa kerja + faktor
-- per alasan terminasi) dan catatan final pay per employment.
-- Nilai bawaan di-seed oleh aplikasi (services/final_pay.py) mengikuti
-- PP 35/2021 Pasal 40; tabel dapat diganti per tenant dari UI.

CREATE TABLE IF NOT EXISTS severance_brackets (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    component VARCHAR(20) NOT NULL,
    min_years NUMERIC(6, 2) NOT NULL,
    max_years NUMERIC(6, 2),
    months INTEGER NOT NULL,
    CONSTRAINT uq_sevbracket_tenant_comp_min
        UNIQUE (tenant_id, component, min_years)
);
CREATE INDEX IF NOT EXISTS ix_sevbracket_tenant_comp
    ON severance_brackets (tenant_id, component);

CREATE TABLE IF NOT EXISTS severance_reason_factors (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    reason VARCHAR(255) NOT NULL,
    pesangon_factor NUMERIC(6, 3) NOT NULL DEFAULT 1.0,
    upmk_factor NUMERIC(6, 3) NOT NULL DEFAULT 1.0,
    uph_included BOOLEAN NOT NULL DEFAULT TRUE,
    pkwt_compensation BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_sevfactor_tenant_reason UNIQUE (tenant_id, reason)
);
CREATE INDEX IF NOT EXISTS ix_sevfactor_tenant
    ON severance_reason_factors (tenant_id);

CREATE TABLE IF NOT EXISTS final_pays (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    employment_id UUID NOT NULL REFERENCES employments(id),
    termination_date DATE NOT NULL,
    reason VARCHAR(255) NOT NULL,
    years_of_service NUMERIC(8, 3) NOT NULL,
    monthly_wage INTEGER NOT NULL,
    breakdown JSON NOT NULL DEFAULT '{}',
    gross_total INTEGER NOT NULL DEFAULT 0,
    loan_deduction INTEGER NOT NULL DEFAULT 0,
    tax_amount INTEGER NOT NULL DEFAULT 0,
    net_amount INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_by_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_finalpay_tenant_emp
    ON final_pays (tenant_id, employment_id);

GRANT SELECT, INSERT, UPDATE, DELETE
    ON severance_brackets, severance_reason_factors, final_pays
    TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'severance_brackets', 'severance_reason_factors', 'final_pays'
    ]
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
