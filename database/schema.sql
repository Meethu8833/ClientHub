-- ============================================================================
-- ClientHub CRM — PostgreSQL 16 schema
-- ============================================================================
-- This file is the DESIGN CONTRACT for the database. When the Django apps are
-- built, their migrations become the executable authority; this file documents
-- the intended shape and constraints.
--
-- Conventions
--   * PKs: BIGINT GENERATED ALWAYS AS IDENTITY.
--   * Timestamps: timestamptz, UTC. created_at on everything; updated_at where
--     rows are mutable (maintained by trigger, see bottom of file).
--   * Money: NUMERIC(12,2). Never float.
--   * Enum-like fields: VARCHAR + CHECK constraint (not native ENUM types) so
--     values can change with an ALTER of one constraint, and Django TextChoices
--     map onto them 1:1.
--   * Soft delete (is_active flag): companies, clients, projects, users —
--     records with audit/financial history. Operational rows hard-delete.
--   * PostgreSQL does NOT auto-index FK columns, so every FK used in lookups
--     gets an explicit index.
--   * Polymorphic parents (comments, attachments, notifications, activity
--     logs) use (entity_type, entity_id). Referential integrity for those is
--     enforced at the application layer — the CHECK on entity_type limits the
--     universe of targets.
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;   -- case-insensitive emails

-- ============================================================================
-- 1. AUTH & ACCESS
-- ============================================================================

CREATE TABLE roles (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            VARCHAR(50)  NOT NULL UNIQUE,          -- 'admin', 'manager', 'staff'
    description     TEXT,
    permissions     JSONB        NOT NULL DEFAULT '{}',    -- optional fine-grained flags
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_id         BIGINT       NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    email           CITEXT       NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    phone           VARCHAR(30),
    avatar_url      TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,    -- soft delete / deactivation
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_role_id ON users (role_id);

-- ============================================================================
-- 2. CRM CORE — companies (organisations) and clients (people)
-- ============================================================================

CREATE TABLE companies (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                VARCHAR(255) NOT NULL,
    industry            VARCHAR(100),
    website             VARCHAR(255),
    email               CITEXT,
    phone               VARCHAR(30),
    address_line1       VARCHAR(255),
    address_line2       VARCHAR(255),
    city                VARCHAR(100),
    state               VARCHAR(100),
    postal_code         VARCHAR(20),
    country             VARCHAR(100),
    account_manager_id  BIGINT REFERENCES users(id) ON DELETE RESTRICT,
    status              VARCHAR(20)  NOT NULL DEFAULT 'prospect'
                        CHECK (status IN ('prospect', 'active', 'inactive')),
    notes               TEXT,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,   -- soft delete
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_companies_account_manager ON companies (account_manager_id);
CREATE INDEX idx_companies_status          ON companies (status) WHERE is_active;
CREATE INDEX idx_companies_name            ON companies (name);

CREATE TABLE clients (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          BIGINT REFERENCES companies(id) ON DELETE SET NULL,  -- NULL = individual client
    first_name          VARCHAR(100) NOT NULL,
    last_name           VARCHAR(100) NOT NULL,
    email               CITEXT       NOT NULL UNIQUE,
    phone               VARCHAR(30),
    job_title           VARCHAR(100),
    is_primary_contact  BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,   -- soft delete
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_clients_company ON clients (company_id);
-- at most ONE primary contact per company
CREATE UNIQUE INDEX uq_clients_one_primary_per_company
    ON clients (company_id)
    WHERE is_primary_contact AND company_id IS NOT NULL;

-- ============================================================================
-- 3. DELIVERY — projects, members, milestones, tasks
-- ============================================================================

CREATE TABLE projects (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      BIGINT       NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    client_id       BIGINT       REFERENCES clients(id)  ON DELETE SET NULL,  -- main contact person
    created_by      BIGINT       REFERENCES users(id)    ON DELETE SET NULL,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    status          VARCHAR(20)  NOT NULL DEFAULT 'planned'
                    CHECK (status IN ('planned', 'in_progress', 'on_hold', 'completed', 'cancelled')),
    start_date      DATE,
    end_date        DATE,
    budget          NUMERIC(12,2) CHECK (budget >= 0),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,   -- soft delete
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_project_dates
        CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX idx_projects_company_status ON projects (company_id, status);
CREATE INDEX idx_projects_client         ON projects (client_id);
CREATE INDEX idx_projects_status         ON projects (status) WHERE is_active;

CREATE TABLE project_members (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id       BIGINT      NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id          BIGINT      NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    role_on_project  VARCHAR(20) NOT NULL DEFAULT 'member'
                     CHECK (role_on_project IN ('manager', 'member')),
    joined_at        DATE        NOT NULL DEFAULT CURRENT_DATE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_member UNIQUE (project_id, user_id)
);

CREATE INDEX idx_project_members_user ON project_members (user_id);

CREATE TABLE milestones (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id      BIGINT       NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    due_date        DATE,
    sort_order      INTEGER      NOT NULL DEFAULT 0,
    is_completed    BOOLEAN      NOT NULL DEFAULT FALSE,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_milestones_project ON milestones (project_id);

CREATE TABLE tasks (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id       BIGINT       NOT NULL REFERENCES projects(id)   ON DELETE CASCADE,
    milestone_id     BIGINT       REFERENCES milestones(id)          ON DELETE SET NULL,
    parent_task_id   BIGINT       REFERENCES tasks(id)               ON DELETE CASCADE,  -- subtasks
    assignee_id      BIGINT       REFERENCES users(id)               ON DELETE SET NULL,
    created_by       BIGINT       REFERENCES users(id)               ON DELETE SET NULL,
    title            VARCHAR(255) NOT NULL,
    description      TEXT,
    status           VARCHAR(20)  NOT NULL DEFAULT 'todo'
                     CHECK (status IN ('todo', 'in_progress', 'review', 'done')),
    priority         VARCHAR(20)  NOT NULL DEFAULT 'medium'
                     CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    due_date         DATE,
    estimated_hours  NUMERIC(6,2) CHECK (estimated_hours >= 0),
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_tasks_project_status ON tasks (project_id, status);   -- kanban board query
CREATE INDEX idx_tasks_assignee       ON tasks (assignee_id);
CREATE INDEX idx_tasks_milestone      ON tasks (milestone_id);
CREATE INDEX idx_tasks_parent         ON tasks (parent_task_id);
CREATE INDEX idx_tasks_due_open       ON tasks (due_date) WHERE status <> 'done';

-- ============================================================================
-- 4. COLLABORATION — comments & attachments (polymorphic)
-- ============================================================================

CREATE TABLE comments (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    author_id          BIGINT      REFERENCES users(id)    ON DELETE SET NULL,  -- keep comment if author deleted
    parent_comment_id  BIGINT      REFERENCES comments(id) ON DELETE CASCADE,   -- threaded replies
    entity_type        VARCHAR(30) NOT NULL
                       CHECK (entity_type IN ('project', 'task', 'milestone', 'support_ticket')),
    entity_id          BIGINT      NOT NULL,
    body               TEXT        NOT NULL,
    edited_at          TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_comments_entity ON comments (entity_type, entity_id, created_at);
CREATE INDEX idx_comments_author ON comments (author_id);

CREATE TABLE attachments (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uploaded_by    BIGINT       REFERENCES users(id) ON DELETE SET NULL,
    entity_type    VARCHAR(30)  NOT NULL
                   CHECK (entity_type IN ('company', 'client', 'project', 'task', 'comment',
                                          'support_ticket', 'ticket_reply', 'quotation',
                                          'invoice', 'meeting')),
    entity_id      BIGINT       NOT NULL,
    file_path      TEXT         NOT NULL,             -- storage key: documents/{yyyy}/{mm}/{uuid}.{ext}
    original_name  VARCHAR(255) NOT NULL,             -- user-facing filename
    mime_type      VARCHAR(100) NOT NULL,
    size_bytes     BIGINT       NOT NULL CHECK (size_bytes > 0),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_attachments_entity   ON attachments (entity_type, entity_id);
CREATE INDEX idx_attachments_uploader ON attachments (uploaded_by);

-- ============================================================================
-- 5. SUPPORT — tickets & replies
-- ============================================================================

CREATE TABLE support_tickets (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_no    VARCHAR(20)  NOT NULL UNIQUE,        -- e.g. 'TCK-2026-00041', generated app-side
    company_id   BIGINT       REFERENCES companies(id) ON DELETE RESTRICT,
    client_id    BIGINT       REFERENCES clients(id)   ON DELETE SET NULL,   -- who raised it
    project_id   BIGINT       REFERENCES projects(id)  ON DELETE SET NULL,
    assigned_to  BIGINT       REFERENCES users(id)     ON DELETE SET NULL,
    subject      VARCHAR(255) NOT NULL,
    description  TEXT         NOT NULL,
    status       VARCHAR(30)  NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'in_progress', 'waiting_on_client', 'resolved', 'closed')),
    priority     VARCHAR(20)  NOT NULL DEFAULT 'medium'
                 CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    resolved_at  TIMESTAMPTZ,
    closed_at    TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- a ticket must be traceable to a company or a person
    CONSTRAINT chk_ticket_has_origin CHECK (company_id IS NOT NULL OR client_id IS NOT NULL)
);

CREATE INDEX idx_tickets_status_priority ON support_tickets (status, priority);
CREATE INDEX idx_tickets_company         ON support_tickets (company_id);
CREATE INDEX idx_tickets_assignee        ON support_tickets (assigned_to);

CREATE TABLE ticket_replies (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticket_id    BIGINT      NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    user_id      BIGINT      REFERENCES users(id)   ON DELETE SET NULL,  -- staff author…
    client_id    BIGINT      REFERENCES clients(id) ON DELETE SET NULL,  -- …or client author
    body         TEXT        NOT NULL,
    is_internal  BOOLEAN     NOT NULL DEFAULT FALSE,   -- staff-only note, hidden from client
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- authored by staff OR client, never both (both NULL allowed after author deletion)
    CONSTRAINT chk_reply_single_author CHECK (NOT (user_id IS NOT NULL AND client_id IS NOT NULL))
);

CREATE INDEX idx_ticket_replies_ticket ON ticket_replies (ticket_id, created_at);

-- ============================================================================
-- 6. BILLING — quotations, invoices, payments
-- ============================================================================

CREATE TABLE quotations (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quote_no         VARCHAR(20)  NOT NULL UNIQUE,     -- e.g. 'QUO-2026-00007'
    company_id       BIGINT       NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    client_id        BIGINT       REFERENCES clients(id)  ON DELETE SET NULL,
    project_id       BIGINT       REFERENCES projects(id) ON DELETE SET NULL,
    created_by       BIGINT       REFERENCES users(id)    ON DELETE SET NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'sent', 'accepted', 'rejected', 'expired')),
    issue_date       DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_until      DATE,
    currency         CHAR(3)      NOT NULL DEFAULT 'EUR',
    subtotal         NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    discount_amount  NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    tax_amount       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    total            NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (total >= 0),
    notes            TEXT,
    terms            TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_quote_validity CHECK (valid_until IS NULL OR valid_until >= issue_date)
);

CREATE INDEX idx_quotations_company ON quotations (company_id);
CREATE INDEX idx_quotations_status  ON quotations (status);

CREATE TABLE quotation_items (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_id  BIGINT        NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    description   VARCHAR(255)  NOT NULL,
    quantity      NUMERIC(10,2) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price    NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    line_total    NUMERIC(12,2) GENERATED ALWAYS AS (ROUND(quantity * unit_price, 2)) STORED,
    sort_order    INTEGER       NOT NULL DEFAULT 0
);

CREATE INDEX idx_quotation_items_quotation ON quotation_items (quotation_id);

CREATE TABLE invoices (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_no       VARCHAR(20)  NOT NULL UNIQUE,     -- e.g. 'INV-2026-00113'
    company_id       BIGINT       NOT NULL REFERENCES companies(id)  ON DELETE RESTRICT,
    project_id       BIGINT       REFERENCES projects(id)   ON DELETE SET NULL,
    quotation_id     BIGINT       REFERENCES quotations(id)  ON DELETE SET NULL,  -- provenance
    created_by       BIGINT       REFERENCES users(id)       ON DELETE SET NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'sent', 'partially_paid', 'paid', 'overdue', 'cancelled')),
    issue_date       DATE         NOT NULL DEFAULT CURRENT_DATE,
    due_date         DATE,
    currency         CHAR(3)      NOT NULL DEFAULT 'EUR',
    subtotal         NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    discount_amount  NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    tax_amount       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    total            NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (total >= 0),
    amount_paid      NUMERIC(12,2) NOT NULL DEFAULT 0
                     CHECK (amount_paid >= 0 AND amount_paid <= total),
    notes            TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_invoice_dates CHECK (due_date IS NULL OR due_date >= issue_date)
);

CREATE INDEX idx_invoices_company     ON invoices (company_id);
CREATE INDEX idx_invoices_status_due  ON invoices (status, due_date);
CREATE INDEX idx_invoices_project     ON invoices (project_id);

CREATE TABLE invoice_items (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id  BIGINT        NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description VARCHAR(255)  NOT NULL,
    quantity    NUMERIC(10,2) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price  NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    line_total  NUMERIC(12,2) GENERATED ALWAYS AS (ROUND(quantity * unit_price, 2)) STORED,
    sort_order  INTEGER       NOT NULL DEFAULT 0
);

CREATE INDEX idx_invoice_items_invoice ON invoice_items (invoice_id);

CREATE TABLE payments (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id    BIGINT        NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,  -- money history is sacred
    received_by   BIGINT        REFERENCES users(id) ON DELETE SET NULL,
    amount        NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    payment_date  DATE          NOT NULL DEFAULT CURRENT_DATE,
    method        VARCHAR(20)   NOT NULL DEFAULT 'bank_transfer'
                  CHECK (method IN ('bank_transfer', 'card', 'cash', 'cheque', 'online', 'other')),
    reference_no  VARCHAR(100),                      -- bank/gateway transaction reference
    notes         TEXT,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_payments_invoice ON payments (invoice_id);
CREATE INDEX idx_payments_date    ON payments (payment_date);

-- ============================================================================
-- 7. SCHEDULING — meetings & attendees
-- ============================================================================

CREATE TABLE meetings (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organizer_id  BIGINT       REFERENCES users(id)     ON DELETE SET NULL,
    company_id    BIGINT       REFERENCES companies(id) ON DELETE SET NULL,
    project_id    BIGINT       REFERENCES projects(id)  ON DELETE SET NULL,
    title         VARCHAR(255) NOT NULL,
    agenda        TEXT,
    starts_at     TIMESTAMPTZ  NOT NULL,
    ends_at       TIMESTAMPTZ  NOT NULL,
    location      VARCHAR(255),                        -- physical location…
    meeting_link  TEXT,                                -- …or video-call URL
    status        VARCHAR(20)  NOT NULL DEFAULT 'scheduled'
                  CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_meeting_times CHECK (ends_at > starts_at)
);

CREATE INDEX idx_meetings_starts_at ON meetings (starts_at);
CREATE INDEX idx_meetings_organizer ON meetings (organizer_id);
CREATE INDEX idx_meetings_project   ON meetings (project_id);

CREATE TABLE meeting_attendees (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    meeting_id  BIGINT      NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id     BIGINT      REFERENCES users(id)   ON DELETE CASCADE,  -- internal attendee…
    client_id   BIGINT      REFERENCES clients(id) ON DELETE CASCADE,  -- …or external attendee
    response    VARCHAR(20) NOT NULL DEFAULT 'invited'
                CHECK (response IN ('invited', 'accepted', 'declined', 'tentative')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- exactly one of user_id / client_id
    CONSTRAINT chk_attendee_one_person
        CHECK ((user_id IS NOT NULL)::int + (client_id IS NOT NULL)::int = 1)
);

CREATE UNIQUE INDEX uq_meeting_attendee_user
    ON meeting_attendees (meeting_id, user_id)   WHERE user_id   IS NOT NULL;
CREATE UNIQUE INDEX uq_meeting_attendee_client
    ON meeting_attendees (meeting_id, client_id) WHERE client_id IS NOT NULL;

-- ============================================================================
-- 8. SYSTEM — notifications, audit trail, activity timeline
-- ============================================================================

CREATE TABLE notifications (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_id  BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type          VARCHAR(50)  NOT NULL,        -- 'task_assigned', 'ticket_reply', 'invoice_overdue', …
    title         VARCHAR(255) NOT NULL,
    body          TEXT,
    entity_type   VARCHAR(30),                  -- deep-link target (optional)
    entity_id     BIGINT,
    read_at       TIMESTAMPTZ,                  -- NULL = unread
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_recipient ON notifications (recipient_id, created_at DESC);
CREATE INDEX idx_notifications_unread    ON notifications (recipient_id) WHERE read_at IS NULL;

-- Append-only, machine-oriented: exactly WHAT changed in WHICH row (compliance/debugging).
CREATE TABLE audit_logs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(10) NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
    table_name  VARCHAR(63) NOT NULL,
    record_id   BIGINT      NOT NULL,
    old_values  JSONB,                          -- NULL on insert
    new_values  JSONB,                          -- NULL on delete
    ip_address  INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_logs_record ON audit_logs (table_name, record_id, created_at DESC);
CREATE INDEX idx_audit_logs_user   ON audit_logs (user_id, created_at DESC);

-- Append-only, human-oriented: the "timeline" feed shown on detail pages.
CREATE TABLE activity_logs (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id     BIGINT      REFERENCES users(id) ON DELETE SET NULL,
    verb         VARCHAR(50) NOT NULL,          -- 'created', 'status_changed', 'commented', 'uploaded', …
    entity_type  VARCHAR(30) NOT NULL
                 CHECK (entity_type IN ('company', 'client', 'project', 'milestone', 'task',
                                        'support_ticket', 'quotation', 'invoice', 'payment', 'meeting')),
    entity_id    BIGINT      NOT NULL,
    description  TEXT,                          -- pre-rendered sentence for the feed
    metadata     JSONB       NOT NULL DEFAULT '{}',   -- e.g. {"from": "todo", "to": "done"}
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_activity_logs_entity ON activity_logs (entity_type, entity_id, created_at DESC);
CREATE INDEX idx_activity_logs_actor  ON activity_logs (actor_id, created_at DESC);

-- ============================================================================
-- 9. updated_at maintenance trigger — attached to every table that has one
-- ============================================================================

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOR t IN
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'updated_at'
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
    END LOOP;
END $$;

COMMIT;
