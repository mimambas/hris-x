-- 004_learning_extensions.sql
-- Ekstensi Learning (LRN, PRD 12.5): konten kursus (LRN-001), penugasan
-- wajib + tenggat (LRN-002), nilai tes + sertifikat otomatis & masa
-- berlaku sertifikasi (LRN-003). Idempoten; dijalankan sebagai pemilik DB.

-- LRN-001/003: kolom baru training_courses.
ALTER TABLE training_courses
    ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) NOT NULL DEFAULT 'offline';
ALTER TABLE training_courses
    ADD COLUMN IF NOT EXISTS content_url VARCHAR(500);
ALTER TABLE training_courses
    ADD COLUMN IF NOT EXISTS passing_score INTEGER;
ALTER TABLE training_courses
    ADD COLUMN IF NOT EXISTS cert_validity_months INTEGER;

-- LRN-001/002/003: kolom baru training_enrollments.
ALTER TABLE training_enrollments
    ADD COLUMN IF NOT EXISTS progress_percent INTEGER NOT NULL DEFAULT 0;
ALTER TABLE training_enrollments
    ADD COLUMN IF NOT EXISTS due_date DATE;
ALTER TABLE training_enrollments
    ADD COLUMN IF NOT EXISTS is_mandatory BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE training_enrollments
    ADD COLUMN IF NOT EXISTS pre_score INTEGER;
ALTER TABLE training_enrollments
    ADD COLUMN IF NOT EXISTS post_score INTEGER;
ALTER TABLE training_enrollments
    ADD COLUMN IF NOT EXISTS cert_expires_at DATE;

-- LRN-002: penugasan wajib per populasi.
CREATE TABLE IF NOT EXISTS training_assignments (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    course_id UUID NOT NULL REFERENCES training_courses (id),
    target_type VARCHAR(20) NOT NULL,
    org_unit_id UUID,
    job_id UUID REFERENCES jobs (id),
    due_days INTEGER NOT NULL DEFAULT 30,
    enrollments_created INTEGER NOT NULL DEFAULT 0,
    created_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_training_assignments_tenant_id
    ON training_assignments (tenant_id);
CREATE INDEX IF NOT EXISTS ix_training_assignments_course_id
    ON training_assignments (course_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON training_assignments TO hrisx_sql;

ALTER TABLE training_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON training_assignments;
CREATE POLICY tenant_isolation ON training_assignments
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());
