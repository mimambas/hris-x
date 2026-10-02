-- ==============================================================================
-- HRIS-X — 001_rls.sql
-- Row Level Security PostgreSQL untuk isolasi tenant (Sprint 2, CHR-001/PLT).
--
-- CARA PAKAI (produksi, Postgres):
--   1. Jalankan skrip ini sekali sebagai pemilik database:
--        psql "$DATABASE_URL" -f backend/migrations/001_rls.sql
--   2. Aplikasi menyetel konteks tenant OTOMATIS per request via handler
--      SQLAlchemy `after_begin` (app/core/rls.py, ADR-0014) — tidak perlu
--      SET LOCAL manual di kode request. "SET LOCAL" membuat konteks
--      otomatis hilang saat transaksi selesai, sehingga tidak ada kebocoran
--      antar-request (aman untuk pool koneksi).
--   3. Role aplikasi HANYA diberi GRANT SELECT/INSERT/UPDATE/DELETE pada
--      tabel — bukan pemilik tabel — agar policy benar-benar dievaluasi.
--   4. SKRIP BATCH (seed.py, demo) yang jalan langsung ke Postgres di luar
--      request HTTP HARUS menyetel GUC manual per transaksi/sesi:
--        SET LOCAL app.tenant_id = '<tenant-uuid>';
--      atau dijalankan sebelum migrasi RLS ini diterapkan.
--
-- CATATAN:
--   * SQLite (development/test) tidak mendukung RLS; isolasi tenant di
--     sana tetap ditegakkan di level aplikasi (tenant_id di setiap query).
--   * Tabel dengan kolom tenant_id tercakup; tabel tanpa tenant_id
--     (mis. migrasi internal) tidak diberi policy.
--   * Tabel `tenants` SENGAJA DIKECUALIKAN dari RLS (lihat bawah): slug
--     bersifat semi-publik (sudah terekspos di /public/jobs?tenant=) dan
--     wajib bisa di-resolve SEBELUM autentikasi — login me-resolve tenant
--     by slug pre-auth (pola bootstrap standar). Rasional penuh: ADR-0014.
--   * CREATE POLICY ... IF NOT EXISTS tidak tersedia di semua versi
--     Postgres; skrip ini menghapus policy lama dulu (idempoten).
-- ==============================================================================

-- Fungsi pembantu: membaca tenant aktif dari GUC sesi.
CREATE OR REPLACE FUNCTION app.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

-- Terapkan policy ke seluruh tabel yang punya kolom tenant_id.
DO $$
DECLARE
    t text;
BEGIN
    FOR t IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename IN (
            'users', 'persons', 'employments',
            'legal_entities', 'legal_entity_info',
            'org_units', 'org_unit_info',
            'locations', 'location_info',
            'cost_centers', 'cost_center_info',
            'jobs', 'positions',
            'job_info', 'comp_info',
            'custom_field_definitions', 'custom_field_values',
            'permission_roles', 'permission_groups', 'role_assignments',
            'field_permissions', 'audit_logs',
            'lifecycle_events', 'event_reasons',
            'contracts', 'contract_info', 'tenant_contract_policies',
            'documents',
            'salary_components', 'salary_component_info',
            'comp_assignments', 'comp_assignment_info',
            'payroll_policies', 'payroll_runs', 'payroll_lines',
            'shifts', 'shift_assignments', 'holidays', 'attendance_records',
            'leave_types', 'leave_balances', 'leave_requests',
            'tenant_leave_policies', 'tenant_attendance_policies',
            'overtime_rates', 'overtime_requests',
            'job_requisitions', 'job_postings', 'candidates',
            'job_applications', 'interviews', 'interview_feedbacks',
            'offers',
            'review_cycles', 'performance_goals', 'appraisals',
            'tenant_performance_policies', 'training_courses',
            'training_enrollments',
            'claim_types', 'claims', 'tenant_loan_policies', 'loans',
            'loan_installments',
            'onboarding_templates', 'onboarding_template_tasks',
            'onboarding_processes', 'onboarding_tasks'
          )
    LOOP
        -- Isolasi tenant: baris hanya terlihat bila tenant_id cocok.
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = app.current_tenant_id()) '
            'WITH CHECK (tenant_id = app.current_tenant_id())', t);
    END LOOP;
END
$$;

-- Tabel `tenants` DIKECUALIKAN dari RLS (ADR-0014): slug semi-publik dan
-- wajib bisa di-resolve sebelum autentikasi (login by slug pre-auth).
-- Idempoten: aman dijalankan ulang / setelah migrasi versi lama yang
-- sempat memberi policy pada tabel ini.
DROP POLICY IF EXISTS tenant_isolation ON tenants;
ALTER TABLE tenants DISABLE ROW LEVEL SECURITY;

-- Verifikasi cepat (opsional):
--   SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
--   SELECT policyname, cmd FROM pg_policies WHERE schemaname='public';
