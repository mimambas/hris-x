-- ==============================================================================
-- HRIS-X — 001_rls.sql
-- Row Level Security PostgreSQL untuk isolasi tenant (Sprint 2, CHR-001/PLT).
--
-- CARA PAKAI (produksi, Postgres):
--   1. Jalankan skrip ini sekali sebagai pemilik database:
--        psql "$DATABASE_URL" -f backend/migrations/001_rls.sql
--   2. Aplikasi WAJIB menyetel konteks tenant di setiap transaksi:
--        SET LOCAL app.tenant_id = '<tenant-uuid>';
--      "SET LOCAL" membuat konteks otomatis hilang saat transaksi selesai,
--      sehingga tidak ada kebocoran antar-request (aman untuk pool koneksi).
--   3. Role aplikasi HANYA diberi GRANT SELECT/INSERT/UPDATE/DELETE pada
--      tabel — bukan pemilik tabel — agar policy benar-benar dievaluasi.
--
-- CATATAN:
--   * SQLite (development/test) tidak mendukung RLS; isolasi tenant di
--     sana tetap ditegakkan di level aplikasi (tenant_id di setiap query).
--   * Tabel dengan kolom tenant_id tercakup; tabel tanpa tenant_id
--     (mis. migrasi internal) tidak diberi policy.
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
            'tenants', 'users', 'persons', 'employments',
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
            'payroll_policies', 'payroll_runs', 'payroll_lines'
          )
    LOOP
        -- Isolasi tenant: baris hanya terlihat bila tenant_id cocok.
        -- 'tenants' sendiri: hanya baris tenant aktif yang terlihat.
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        IF t = 'tenants' THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING (id = app.current_tenant_id()) '
                'WITH CHECK (id = app.current_tenant_id())', t);
        ELSE
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING (tenant_id = app.current_tenant_id()) '
                'WITH CHECK (tenant_id = app.current_tenant_id())', t);
        END IF;
    END LOOP;
END
$$;

-- Verifikasi cepat (opsional):
--   SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public';
--   SELECT policyname, cmd FROM pg_policies WHERE schemaname='public';
