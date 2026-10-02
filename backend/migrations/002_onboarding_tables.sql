-- ==============================================================================
-- HRIS-X — 002_onboarding_tables.sql
-- Tabel modul Onboarding & Offboarding (ONB, PRD 12.2 F2) + izin + policy RLS.
--
-- KENAPA FILE INI ADA: role aplikasi (hrisx_sql) SENGAJA tidak punya hak
-- CREATE di schema public (hardening ADR-0014: role aplikasi hanya DML).
-- create_all() di startup aplikasi karena itu GAGAL di staging/produksi
-- (permission denied for schema public) setiap ada tabel baru.
--
-- CARA PAKAI: jalankan SEKALI sebagai pemilik database (Neon Console ->
-- SQL Editor, database hris_x_staging, atau psql dengan string owner).
-- Idempoten (IF NOT EXISTS / DROP POLICY IF EXISTS).
-- ==============================================================================


CREATE TABLE IF NOT EXISTS onboarding_templates (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_by_user_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)

;
CREATE INDEX IF NOT EXISTS ix_onboarding_templates_tenant_id ON onboarding_templates (tenant_id);

CREATE TABLE IF NOT EXISTS onboarding_processes (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	person_id UUID NOT NULL, 
	employment_id UUID, 
	template_id UUID NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	start_date DATE NOT NULL, 
	target_date DATE, 
	notes TEXT, 
	created_by_user_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	FOREIGN KEY(person_id) REFERENCES persons (id), 
	FOREIGN KEY(employment_id) REFERENCES employments (id), 
	FOREIGN KEY(template_id) REFERENCES onboarding_templates (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)

;
CREATE INDEX IF NOT EXISTS ix_onboarding_processes_person_id ON onboarding_processes (person_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_processes_tenant_id ON onboarding_processes (tenant_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_processes_employment_id ON onboarding_processes (employment_id);

CREATE TABLE IF NOT EXISTS onboarding_template_tasks (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	template_id UUID NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	team VARCHAR(20) NOT NULL, 
	due_offset_days INTEGER NOT NULL, 
	sort_order INTEGER NOT NULL, 
	required_doc_type VARCHAR(30), 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	FOREIGN KEY(template_id) REFERENCES onboarding_templates (id)
)

;
CREATE INDEX IF NOT EXISTS ix_onboarding_template_tasks_template_id ON onboarding_template_tasks (template_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_template_tasks_tenant_id ON onboarding_template_tasks (tenant_id);

CREATE TABLE IF NOT EXISTS onboarding_tasks (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	process_id UUID NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	team VARCHAR(20) NOT NULL, 
	assignee_user_id UUID, 
	due_date DATE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	completed_by_user_id UUID, 
	notes TEXT, 
	required_doc_type VARCHAR(30), 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	FOREIGN KEY(process_id) REFERENCES onboarding_processes (id), 
	FOREIGN KEY(assignee_user_id) REFERENCES users (id), 
	FOREIGN KEY(completed_by_user_id) REFERENCES users (id)
)

;
CREATE INDEX IF NOT EXISTS ix_onboarding_tasks_assignee_user_id ON onboarding_tasks (assignee_user_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_tasks_process_id ON onboarding_tasks (process_id);
CREATE INDEX IF NOT EXISTS ix_onboarding_tasks_tenant_id ON onboarding_tasks (tenant_id);

-- Izin DML untuk role aplikasi (pola yang sama dengan 65 tabel lama).
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_templates TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_template_tasks TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_processes TO hrisx_sql;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_tasks TO hrisx_sql;

-- Policy RLS isolasi tenant untuk 4 tabel baru (pola migrations/001_rls.sql).
ALTER TABLE onboarding_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_templates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON onboarding_templates;
CREATE POLICY tenant_isolation ON onboarding_templates
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

ALTER TABLE onboarding_template_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_template_tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON onboarding_template_tasks;
CREATE POLICY tenant_isolation ON onboarding_template_tasks
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

ALTER TABLE onboarding_processes ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_processes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON onboarding_processes;
CREATE POLICY tenant_isolation ON onboarding_processes
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

ALTER TABLE onboarding_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON onboarding_tasks;
CREATE POLICY tenant_isolation ON onboarding_tasks
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());
