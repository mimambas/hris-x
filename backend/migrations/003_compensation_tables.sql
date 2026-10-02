-- ==============================================================================
-- HRIS-X — 003_compensation_tables.sql
-- Tabel modul Kompensasi (CMP, PRD 12.4 F3) + kolom grade pada jobs
-- + izin + policy RLS.
--
-- KENAPA FILE INI ADA: role aplikasi (hrisx_sql) SENGAJA tidak punya hak
-- CREATE di schema public (hardening ADR-0014: role aplikasi hanya DML).
-- create_all() di startup aplikasi karena itu GAGAL di staging/produksi
-- (permission denied for schema public) setiap ada tabel baru.
--
-- CARA PAKAI: jalankan SEKALI sebagai pemilik database (Neon Console ->
-- SQL Editor, database hris_x_staging, atau psql dengan string owner).
-- Idempoten (IF NOT EXISTS / DROP POLICY IF EXISTS / ADD COLUMN IF NOT EXISTS).
-- ==============================================================================

CREATE TABLE IF NOT EXISTS pay_grades (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	code VARCHAR(20) NOT NULL,
	name VARCHAR(120) NOT NULL,
	band_min BIGINT NOT NULL,
	band_mid BIGINT NOT NULL,
	band_max BIGINT NOT NULL,
	is_active BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_paygrade_tenant_code UNIQUE (tenant_id, code),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX IF NOT EXISTS ix_pay_grades_tenant_id ON pay_grades (tenant_id);

CREATE TABLE IF NOT EXISTS comp_cycles (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	name VARCHAR(120) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	period_year INTEGER NOT NULL,
	effective_date DATE NOT NULL,
	status VARCHAR(20) NOT NULL,
	guideline JSON,
	created_by_user_id UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	finalized_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_comp_cycles_tenant_id ON comp_cycles (tenant_id);

CREATE TABLE IF NOT EXISTS comp_cycle_budgets (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	cycle_id UUID NOT NULL,
	org_unit_id UUID NOT NULL,
	budget_amount BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_compbudget_cycle_unit UNIQUE (tenant_id, cycle_id, org_unit_id),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id),
	FOREIGN KEY(cycle_id) REFERENCES comp_cycles (id),
	FOREIGN KEY(org_unit_id) REFERENCES org_units (id)
);

CREATE INDEX IF NOT EXISTS ix_comp_cycle_budgets_cycle_id ON comp_cycle_budgets (cycle_id);
CREATE INDEX IF NOT EXISTS ix_comp_cycle_budgets_org_unit_id ON comp_cycle_budgets (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_comp_cycle_budgets_tenant_id ON comp_cycle_budgets (tenant_id);

CREATE TABLE IF NOT EXISTS comp_proposals (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	cycle_id UUID NOT NULL,
	employment_id UUID NOT NULL,
	person_id UUID NOT NULL,
	org_unit_id UUID,
	current_salary BIGINT NOT NULL,
	proposed_salary BIGINT NOT NULL,
	rating NUMERIC(5, 2),
	guideline_min_pct NUMERIC(6, 2),
	guideline_max_pct NUMERIC(6, 2),
	status VARCHAR(30) NOT NULL,
	over_budget BOOLEAN NOT NULL,
	submitted_by_user_id UUID,
	approved_by_user_id UUID,
	extra_approved_by_user_id UUID,
	notes TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_compproposal_cycle_emp UNIQUE (tenant_id, cycle_id, employment_id),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id),
	FOREIGN KEY(cycle_id) REFERENCES comp_cycles (id),
	FOREIGN KEY(employment_id) REFERENCES employments (id),
	FOREIGN KEY(person_id) REFERENCES persons (id),
	FOREIGN KEY(org_unit_id) REFERENCES org_units (id),
	FOREIGN KEY(submitted_by_user_id) REFERENCES users (id),
	FOREIGN KEY(approved_by_user_id) REFERENCES users (id),
	FOREIGN KEY(extra_approved_by_user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_comp_proposals_cycle_id ON comp_proposals (cycle_id);
CREATE INDEX IF NOT EXISTS ix_comp_proposals_employment_id ON comp_proposals (employment_id);
CREATE INDEX IF NOT EXISTS ix_comp_proposals_person_id ON comp_proposals (person_id);
CREATE INDEX IF NOT EXISTS ix_comp_proposals_org_unit_id ON comp_proposals (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_comp_proposals_tenant_id ON comp_proposals (tenant_id);

-- CMP-001: jabatan menempel ke pay grade.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS pay_grade_id UUID;
DO $$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'jobs_pay_grade_id_fkey') THEN
		ALTER TABLE jobs ADD CONSTRAINT jobs_pay_grade_id_fkey
			FOREIGN KEY (pay_grade_id) REFERENCES pay_grades (id);
	END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_jobs_pay_grade_id ON jobs (pay_grade_id);

-- Izin DML untuk role aplikasi (pola yang sama dengan migrasi sebelumnya).
GRANT SELECT, INSERT, UPDATE, DELETE ON pay_grades TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON comp_cycles TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON comp_cycle_budgets TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON comp_proposals TO hrisx_sql;

-- Policy RLS isolasi tenant untuk 4 tabel baru (pola migrasi 001).
ALTER TABLE pay_grades ENABLE ROW LEVEL SECURITY;
ALTER TABLE pay_grades FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON pay_grades;
CREATE POLICY tenant_isolation ON pay_grades
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

ALTER TABLE comp_cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE comp_cycles FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON comp_cycles;
CREATE POLICY tenant_isolation ON comp_cycles
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

ALTER TABLE comp_cycle_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE comp_cycle_budgets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON comp_cycle_budgets;
CREATE POLICY tenant_isolation ON comp_cycle_budgets
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

ALTER TABLE comp_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE comp_proposals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON comp_proposals;
CREATE POLICY tenant_isolation ON comp_proposals
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());
