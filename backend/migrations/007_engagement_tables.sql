-- 007_engagement_tables.sql
-- Engagement & layanan HR (PRD 13.3): pengumuman bertarget + tanda
-- baca (EXP-020), survei pulse/eNPS anonim (EXP-021), kudos
-- antarkaryawan (EXP-022), helpdesk + knowledge base (EXP-023).
-- Idempoten; dijalankan sebagai pemilik DB. Tanpa tanda persen di
-- seluruh teks (psycopg3 mem-parse-nya sebagai placeholder).

CREATE TABLE IF NOT EXISTS announcements (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    target_type VARCHAR(20) NOT NULL DEFAULT 'semua',
    target_org_unit_id UUID REFERENCES org_units (id),
    published_by_user_id UUID REFERENCES users (id),
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_announcements_tenant_id
    ON announcements (tenant_id);

CREATE TABLE IF NOT EXISTS announcement_reads (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    announcement_id UUID NOT NULL REFERENCES announcements (id),
    employment_id UUID NOT NULL REFERENCES employments (id),
    read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_annread_ann_emp
        UNIQUE (tenant_id, announcement_id, employment_id)
);
CREATE INDEX IF NOT EXISTS ix_announcement_reads_tenant_id
    ON announcement_reads (tenant_id);
CREATE INDEX IF NOT EXISTS ix_announcement_reads_announcement_id
    ON announcement_reads (announcement_id);
CREATE INDEX IF NOT EXISTS ix_announcement_reads_employment_id
    ON announcement_reads (employment_id);

CREATE TABLE IF NOT EXISTS surveys (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    kind VARCHAR(20) NOT NULL,
    title VARCHAR(200) NOT NULL,
    question TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'aktif',
    created_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_surveys_tenant_id ON surveys (tenant_id);

CREATE TABLE IF NOT EXISTS survey_responses (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    survey_id UUID NOT NULL REFERENCES surveys (id),
    respondent_hash VARCHAR(64) NOT NULL,
    score INTEGER NOT NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_surveyresp_survey_hash
        UNIQUE (tenant_id, survey_id, respondent_hash)
);
CREATE INDEX IF NOT EXISTS ix_survey_responses_tenant_id
    ON survey_responses (tenant_id);
CREATE INDEX IF NOT EXISTS ix_survey_responses_survey_id
    ON survey_responses (survey_id);

CREATE TABLE IF NOT EXISTS kudos (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    from_employment_id UUID NOT NULL REFERENCES employments (id),
    to_employment_id UUID NOT NULL REFERENCES employments (id),
    category VARCHAR(30) NOT NULL DEFAULT 'kolaborasi',
    message TEXT NOT NULL,
    visible_on_profile BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_kudos_tenant_id ON kudos (tenant_id);
CREATE INDEX IF NOT EXISTS ix_kudos_to_employment_id
    ON kudos (to_employment_id);

CREATE TABLE IF NOT EXISTS helpdesk_tickets (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    requester_employment_id UUID NOT NULL REFERENCES employments (id),
    category VARCHAR(30) NOT NULL,
    subject VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'baru',
    assignee_user_id UUID REFERENCES users (id),
    sla_due_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_helpdesk_tickets_tenant_id
    ON helpdesk_tickets (tenant_id);
CREATE INDEX IF NOT EXISTS ix_helpdesk_tickets_requester
    ON helpdesk_tickets (requester_employment_id);

CREATE TABLE IF NOT EXISTS helpdesk_messages (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    ticket_id UUID NOT NULL REFERENCES helpdesk_tickets (id),
    author_user_id UUID REFERENCES users (id),
    author_name VARCHAR(120) NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_helpdesk_messages_tenant_id
    ON helpdesk_messages (tenant_id);
CREATE INDEX IF NOT EXISTS ix_helpdesk_messages_ticket_id
    ON helpdesk_messages (ticket_id);

CREATE TABLE IF NOT EXISTS kb_articles (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants (id),
    category VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    keywords VARCHAR(255),
    created_by_user_id UUID REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_kb_articles_tenant_id
    ON kb_articles (tenant_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON
    announcements, announcement_reads, surveys, survey_responses, kudos,
    helpdesk_tickets, helpdesk_messages, kb_articles
TO hrisx_sql;

-- RLS isolasi tenant per tabel.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'announcements', 'announcement_reads', 'surveys',
        'survey_responses', 'kudos', 'helpdesk_tickets',
        'helpdesk_messages', 'kb_articles'
    ]
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
