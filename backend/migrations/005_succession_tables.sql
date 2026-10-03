-- 005_succession_tables.sql
-- Suksesi & karier (SUC, PRD 12.6): ontologi skill + governance (SUC-006),
-- profil talent & skill karyawan (SUC-001), posisi kunci & nominasi
-- suksesor (SUC-002), talent pool dari 9-box (SUC-003), jalur karier &
-- IDP (SUC-004), marketplace peluang internal (SUC-005).
-- Idempoten; dijalankan sebagai pemilik DB.

-- SUC-002: penanda posisi kunci.
ALTER TABLE positions
    ADD COLUMN IF NOT EXISTS is_key BOOLEAN NOT NULL DEFAULT FALSE;

-- SUC-006: katalog skill dengan governance.
CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    name VARCHAR(120) NOT NULL,
    category VARCHAR(80),
    status VARCHAR(20) NOT NULL DEFAULT 'usulan',
    proposed_by_user_id UUID REFERENCES users (id),
    decided_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_skills_tenant_name UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS ix_skills_tenant_id ON skills (tenant_id);

-- SUC-001: skill per karyawan.
CREATE TABLE IF NOT EXISTS person_skills (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    skill_id UUID NOT NULL REFERENCES skills (id),
    proficiency INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_personskills_emp_skill
        UNIQUE (tenant_id, employment_id, skill_id)
);
CREATE INDEX IF NOT EXISTS ix_person_skills_tenant_id
    ON person_skills (tenant_id);
CREATE INDEX IF NOT EXISTS ix_person_skills_employment_id
    ON person_skills (employment_id);
CREATE INDEX IF NOT EXISTS ix_person_skills_skill_id
    ON person_skills (skill_id);

-- SUC-001: profil talent (mobilitas & aspirasi).
CREATE TABLE IF NOT EXISTS talent_profiles (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    mobility_preference VARCHAR(20) NOT NULL DEFAULT 'tidak_terbuka',
    career_aspiration TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_talentprofiles_emp UNIQUE (tenant_id, employment_id)
);
CREATE INDEX IF NOT EXISTS ix_talent_profiles_tenant_id
    ON talent_profiles (tenant_id);
CREATE INDEX IF NOT EXISTS ix_talent_profiles_employment_id
    ON talent_profiles (employment_id);

-- SUC-002: nominasi suksesor.
CREATE TABLE IF NOT EXISTS succession_nominations (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    position_id UUID NOT NULL REFERENCES positions (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    readiness VARCHAR(20) NOT NULL,
    notes TEXT,
    nominated_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_succnom_position_emp
        UNIQUE (tenant_id, position_id, employment_id)
);
CREATE INDEX IF NOT EXISTS ix_succession_nominations_tenant_id
    ON succession_nominations (tenant_id);
CREATE INDEX IF NOT EXISTS ix_succession_nominations_position_id
    ON succession_nominations (position_id);
CREATE INDEX IF NOT EXISTS ix_succession_nominations_employment_id
    ON succession_nominations (employment_id);

-- SUC-003: talent pool (snapshot 9-box per siklus).
CREATE TABLE IF NOT EXISTS talent_pools (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    name VARCHAR(200) NOT NULL,
    cycle_id UUID NOT NULL REFERENCES review_cycles (id),
    box_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_talent_pools_tenant_id
    ON talent_pools (tenant_id);
CREATE INDEX IF NOT EXISTS ix_talent_pools_cycle_id
    ON talent_pools (cycle_id);

CREATE TABLE IF NOT EXISTS talent_pool_members (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    pool_id UUID NOT NULL REFERENCES talent_pools (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    box_key VARCHAR(40) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_talentpoolmember_pool_emp
        UNIQUE (tenant_id, pool_id, employment_id)
);
CREATE INDEX IF NOT EXISTS ix_talent_pool_members_tenant_id
    ON talent_pool_members (tenant_id);
CREATE INDEX IF NOT EXISTS ix_talent_pool_members_pool_id
    ON talent_pool_members (pool_id);
CREATE INDEX IF NOT EXISTS ix_talent_pool_members_employment_id
    ON talent_pool_members (employment_id);

-- SUC-004: jalur karier antarjabatan.
CREATE TABLE IF NOT EXISTS career_paths (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    from_job_id UUID NOT NULL REFERENCES jobs (id),
    to_job_id UUID NOT NULL REFERENCES jobs (id),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_careerpath_from_to
        UNIQUE (tenant_id, from_job_id, to_job_id)
);
CREATE INDEX IF NOT EXISTS ix_career_paths_tenant_id
    ON career_paths (tenant_id);
CREATE INDEX IF NOT EXISTS ix_career_paths_from_job_id
    ON career_paths (from_job_id);
CREATE INDEX IF NOT EXISTS ix_career_paths_to_job_id
    ON career_paths (to_job_id);

-- SUC-004: IDP per karyawan per tahun.
CREATE TABLE IF NOT EXISTS idps (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    target_job_id UUID REFERENCES jobs (id),
    year INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'aktif',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_idps_emp_year UNIQUE (tenant_id, employment_id, year)
);
CREATE INDEX IF NOT EXISTS ix_idps_tenant_id ON idps (tenant_id);
CREATE INDEX IF NOT EXISTS ix_idps_employment_id ON idps (employment_id);
CREATE INDEX IF NOT EXISTS ix_idps_target_job_id ON idps (target_job_id);

CREATE TABLE IF NOT EXISTS idp_items (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    idp_id UUID NOT NULL REFERENCES idps (id),
    title VARCHAR(300) NOT NULL,
    course_id UUID REFERENCES training_courses (id),
    target_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'belum',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_idp_items_tenant_id ON idp_items (tenant_id);
CREATE INDEX IF NOT EXISTS ix_idp_items_idp_id ON idp_items (idp_id);
CREATE INDEX IF NOT EXISTS ix_idp_items_course_id ON idp_items (course_id);

-- SUC-005: marketplace peluang internal.
CREATE TABLE IF NOT EXISTS internal_opportunities (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    kind VARCHAR(20) NOT NULL,
    title VARCHAR(300) NOT NULL,
    description TEXT,
    org_unit_id UUID REFERENCES org_units (id),
    status VARCHAR(20) NOT NULL DEFAULT 'terbuka',
    created_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_internal_opportunities_tenant_id
    ON internal_opportunities (tenant_id);
CREATE INDEX IF NOT EXISTS ix_internal_opportunities_org_unit_id
    ON internal_opportunities (org_unit_id);

CREATE TABLE IF NOT EXISTS internal_applications (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    opportunity_id UUID NOT NULL REFERENCES internal_opportunities (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    status VARCHAR(20) NOT NULL DEFAULT 'diajukan',
    cover_note TEXT,
    decided_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_intapp_opp_emp
        UNIQUE (tenant_id, opportunity_id, employment_id)
);
CREATE INDEX IF NOT EXISTS ix_internal_applications_tenant_id
    ON internal_applications (tenant_id);
CREATE INDEX IF NOT EXISTS ix_internal_applications_opportunity_id
    ON internal_applications (opportunity_id);
CREATE INDEX IF NOT EXISTS ix_internal_applications_employment_id
    ON internal_applications (employment_id);

-- Hak akses role aplikasi (ADR-0014: aplikasi hanya DML).
GRANT SELECT, INSERT, UPDATE, DELETE ON
    skills, person_skills, talent_profiles, succession_nominations,
    talent_pools, talent_pool_members, career_paths, idps, idp_items,
    internal_opportunities, internal_applications
TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'skills', 'person_skills', 'talent_profiles',
        'succession_nominations', 'talent_pools', 'talent_pool_members',
        'career_paths', 'idps', 'idp_items', 'internal_opportunities',
        'internal_applications'
    ]
    LOOP
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
