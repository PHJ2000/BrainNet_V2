BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 6269daf2e4b1

CREATE TABLE app_user (
    id BIGSERIAL NOT NULL,
    name VARCHAR(80),
    email VARCHAR(120) NOT NULL,
    pw_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_login_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (email)
);

CREATE TABLE project (
    id BIGSERIAL NOT NULL,
    owner_id BIGINT NOT NULL,
    name VARCHAR(120) NOT NULL,
    description TEXT,
    is_deleted BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(owner_id) REFERENCES app_user (id) ON DELETE CASCADE
);

CREATE TYPE act_type_t AS ENUM ('NODE_CREATE', 'NODE_UPDATE', 'NODE_DELETE', 'TAG_APPLY', 'VOTE_CAST', 'INVITE_SENT', 'INVITE_ACCEPT');

CREATE TABLE activity_log (
    id BIGSERIAL NOT NULL,
    user_id BIGINT,
    project_id BIGINT,
    type act_type_t NOT NULL,
    payload JSON,
    logged_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id),
    FOREIGN KEY(user_id) REFERENCES app_user (id)
);

CREATE TYPE role_t AS ENUM ('OWNER', 'EDITOR');

CREATE TABLE invite_token (
    token VARCHAR(48) NOT NULL,
    project_id BIGINT NOT NULL,
    email VARCHAR(120) NOT NULL,
    role role_t NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (token),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    CONSTRAINT idx_invite_email_project UNIQUE (email, project_id)
);

CREATE TYPE node_state_t AS ENUM ('GHOST', 'ACTIVE', 'ARCHIVED');

CREATE TABLE node (
    id BIGSERIAL NOT NULL,
    project_id BIGINT NOT NULL,
    parent_id BIGINT,
    author_id BIGINT,
    content TEXT NOT NULL,
    state node_state_t NOT NULL,
    depth INTEGER NOT NULL,
    order_index INTEGER NOT NULL,
    pos_x FLOAT,
    pos_y FLOAT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(author_id) REFERENCES app_user (id),
    FOREIGN KEY(parent_id) REFERENCES node (id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE
);

CREATE TABLE project_user_role (
    project_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role role_t NOT NULL,
    invited_at TIMESTAMP WITH TIME ZONE NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (project_id, user_id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE
);

CREATE TABLE tag (
    id BIGSERIAL NOT NULL,
    project_id BIGINT NOT NULL,
    name VARCHAR(80) NOT NULL,
    color VARCHAR(7),
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE
);

CREATE TABLE node_metrics (
    node_id BIGINT NOT NULL,
    subtree_size INTEGER NOT NULL,
    density_score FLOAT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (node_id),
    FOREIGN KEY(node_id) REFERENCES node (id) ON DELETE CASCADE
);

CREATE TABLE node_version (
    id BIGSERIAL NOT NULL,
    node_id BIGINT NOT NULL,
    version_no INTEGER NOT NULL,
    content TEXT NOT NULL,
    author_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(author_id) REFERENCES app_user (id),
    FOREIGN KEY(node_id) REFERENCES node (id) ON DELETE CASCADE,
    UNIQUE (node_id, version_no)
);

CREATE TABLE tag_node (
    tag_id BIGINT NOT NULL,
    node_id BIGINT NOT NULL,
    PRIMARY KEY (tag_id, node_id),
    FOREIGN KEY(node_id) REFERENCES node (id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tag (id) ON DELETE CASCADE
);

CREATE TABLE tag_summary (
    id BIGSERIAL NOT NULL,
    tag_id BIGINT NOT NULL,
    summary_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tag_id) REFERENCES tag (id) ON DELETE CASCADE
);

CREATE TABLE project_history (
    id BIGSERIAL NOT NULL,
    project_id BIGINT NOT NULL,
    tag_summary_id BIGINT,
    decided_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(tag_summary_id) REFERENCES tag_summary (id)
);

CREATE TABLE vote (
    id BIGSERIAL NOT NULL,
    tag_summary_id BIGINT NOT NULL,
    voter_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(tag_summary_id) REFERENCES tag_summary (id) ON DELETE CASCADE,
    FOREIGN KEY(voter_id) REFERENCES app_user (id),
    UNIQUE (tag_summary_id, voter_id)
);

INSERT INTO alembic_version (version_num) VALUES ('6269daf2e4b1') RETURNING alembic_version.version_num;

-- Running upgrade 6269daf2e4b1 -> 4c389bbebfad

UPDATE alembic_version SET version_num='4c389bbebfad' WHERE alembic_version.version_num = '6269daf2e4b1';

-- Running upgrade 4c389bbebfad -> 9e1c2a7d4b10

DO $$
        DECLARE duplicate_projects text;
        BEGIN
            SELECT string_agg(project_id::text, ', ' ORDER BY project_id)
            INTO duplicate_projects
            FROM (
                SELECT project_id
                FROM node
                WHERE parent_id IS NULL AND state = 'ACTIVE'
                GROUP BY project_id
                HAVING count(*) > 1
            ) duplicates;

            IF duplicate_projects IS NOT NULL THEN
                RAISE EXCEPTION
                    'duplicate ACTIVE roots must be resolved for projects: %',
                    duplicate_projects;
            END IF;
        END $$;;

ALTER TABLE node ADD COLUMN version INTEGER DEFAULT '0' NOT NULL;

CREATE UNIQUE INDEX uq_node_active_root_per_project ON node (project_id) WHERE parent_id IS NULL AND state = 'ACTIVE';

CREATE TABLE idempotency_request (
    id BIGSERIAL NOT NULL,
    actor_id BIGINT NOT NULL,
    project_id BIGINT NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response_status INTEGER,
    response_body JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_idempotency_actor_key UNIQUE (actor_id, idempotency_key)
);

CREATE INDEX ix_idempotency_expires_at ON idempotency_request (expires_at);

CREATE TABLE outbox_event (
    id BIGSERIAL NOT NULL,
    event_id VARCHAR(36) NOT NULL,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id BIGINT NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    attempt_count INTEGER DEFAULT '0' NOT NULL,
    lease_until TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    PRIMARY KEY (id),
    UNIQUE (event_id)
);

CREATE INDEX ix_outbox_unpublished ON outbox_event (occurred_at) WHERE published_at IS NULL;

UPDATE alembic_version SET version_num='9e1c2a7d4b10' WHERE alembic_version.version_num = '4c389bbebfad';

-- Running upgrade 9e1c2a7d4b10 -> b810001

CREATE TABLE node_operation (
    id VARCHAR(36) NOT NULL,
    sequence BIGINT GENERATED BY DEFAULT AS IDENTITY,
    project_id BIGINT NOT NULL,
    actor_id BIGINT,
    node_id BIGINT NOT NULL,
    kind VARCHAR(16) NOT NULL,
    request_key VARCHAR(128),
    request_hash VARCHAR(64),
    before JSONB NOT NULL,
    after JSONB NOT NULL,
    response JSONB,
    undone_by VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_node_operation_request UNIQUE (project_id, actor_id, request_key),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(actor_id) REFERENCES app_user (id) ON DELETE SET NULL
);

CREATE INDEX ix_node_operation_project_sequence ON node_operation (project_id, sequence);

CREATE INDEX ix_node_operation_expires ON node_operation (expires_at);

UPDATE alembic_version SET version_num='b810001' WHERE alembic_version.version_num = '9e1c2a7d4b10';

-- Running upgrade b810001 -> b811001

CREATE TABLE project_import (
    actor_id BIGINT NOT NULL,
    request_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    project_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (actor_id, request_key),
    FOREIGN KEY(actor_id) REFERENCES app_user (id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE SET NULL
);

UPDATE alembic_version SET version_num='b811001' WHERE alembic_version.version_num = 'b810001';

-- Running upgrade b811001 -> b822001

COMMIT;

ALTER TYPE role_t ADD VALUE IF NOT EXISTS 'VIEWER';

BEGIN;

UPDATE alembic_version SET version_num='b822001' WHERE alembic_version.version_num = 'b811001';

-- Running upgrade b822001 -> b922001

CREATE TABLE work_item (
    id VARCHAR(36) NOT NULL,
    project_id BIGINT NOT NULL,
    node_id BIGINT,
    creator_id BIGINT,
    title VARCHAR(240) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    priority VARCHAR(16) NOT NULL,
    assignee_id BIGINT,
    due_date DATE,
    version INTEGER NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_work_item_status CHECK (status IN ('TODO','DOING','DONE','CANCELED')),
    CONSTRAINT ck_work_item_priority CHECK (priority IN ('LOW','MEDIUM','HIGH')),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(node_id) REFERENCES node (id) ON DELETE SET NULL,
    FOREIGN KEY(creator_id) REFERENCES app_user (id) ON DELETE SET NULL,
    FOREIGN KEY(assignee_id) REFERENCES app_user (id) ON DELETE SET NULL
);

CREATE TABLE discussion (
    id VARCHAR(36) NOT NULL,
    project_id BIGINT NOT NULL,
    node_id BIGINT,
    author_id BIGINT,
    body TEXT NOT NULL,
    resolved BOOLEAN NOT NULL,
    version INTEGER NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(node_id) REFERENCES node (id) ON DELETE SET NULL,
    FOREIGN KEY(author_id) REFERENCES app_user (id) ON DELETE SET NULL
);

CREATE TABLE node_bookmark (
    user_id BIGINT NOT NULL,
    node_id BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (user_id, node_id),
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE,
    FOREIGN KEY(node_id) REFERENCES node (id) ON DELETE CASCADE
);

CREATE TABLE ai_proposal (
    id VARCHAR(36) NOT NULL,
    project_id BIGINT NOT NULL,
    actor_id BIGINT,
    mode VARCHAR(16) NOT NULL,
    instruction VARCHAR(1000) NOT NULL,
    sources JSONB NOT NULL,
    status VARCHAR(16) NOT NULL,
    output TEXT,
    error_code VARCHAR(80),
    task_id VARCHAR(36),
    request_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(actor_id) REFERENCES app_user (id) ON DELETE SET NULL,
    FOREIGN KEY(task_id) REFERENCES work_item (id) ON DELETE SET NULL
);

CREATE TABLE workspace_activity (
    id BIGSERIAL NOT NULL,
    project_id BIGINT NOT NULL,
    actor_id BIGINT,
    kind VARCHAR(40) NOT NULL,
    target_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(actor_id) REFERENCES app_user (id) ON DELETE SET NULL
);

CREATE INDEX ix_work_item_project_created ON work_item (project_id, created_at, id);

CREATE INDEX ix_discussion_project_created ON discussion (project_id, created_at, id);

CREATE INDEX ix_ai_proposal_project_created ON ai_proposal (project_id, created_at, id);

CREATE INDEX ix_workspace_activity_project_id ON workspace_activity (project_id, id);

UPDATE alembic_version SET version_num='b922001' WHERE alembic_version.version_num = 'b822001';

-- Running upgrade b922001 -> b922002

CREATE TABLE personal_asset (
    id VARCHAR(36) NOT NULL,
    user_id BIGINT NOT NULL,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_personal_asset_name UNIQUE (user_id, kind, name),
    CONSTRAINT ck_personal_asset_kind CHECK (kind IN ('SEARCH','TEMPLATE')),
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='b922002' WHERE alembic_version.version_num = 'b922001';

-- Running upgrade b922002 -> b922003

ALTER TABLE ai_proposal ADD COLUMN lease_token VARCHAR(36);

ALTER TABLE ai_proposal ADD COLUMN started_at TIMESTAMP WITH TIME ZONE;

CREATE TABLE discussion_reply (
    id VARCHAR(36) NOT NULL,
    project_id BIGINT NOT NULL,
    discussion_id VARCHAR(36) NOT NULL,
    author_id BIGINT,
    body TEXT NOT NULL,
    mentions JSONB NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(discussion_id) REFERENCES discussion (id) ON DELETE CASCADE,
    FOREIGN KEY(author_id) REFERENCES app_user (id) ON DELETE SET NULL
);

CREATE INDEX ix_reply_thread ON discussion_reply (discussion_id, created_at, id);

CREATE TABLE workspace_notification (
    id BIGSERIAL NOT NULL,
    user_id BIGINT NOT NULL,
    project_id BIGINT NOT NULL,
    discussion_id VARCHAR(36) NOT NULL,
    reply_id VARCHAR(36) NOT NULL,
    read BOOLEAN NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
    FOREIGN KEY(discussion_id) REFERENCES discussion (id) ON DELETE CASCADE,
    FOREIGN KEY(reply_id) REFERENCES discussion_reply (id) ON DELETE CASCADE
);

CREATE INDEX ix_notification_user ON workspace_notification (user_id, id);

CREATE TABLE knowledge_link (
    source_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    label VARCHAR(120) NOT NULL,
    creator_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (source_id, target_id),
    CONSTRAINT ck_knowledge_link_distinct CHECK (source_id <> target_id),
    FOREIGN KEY(source_id) REFERENCES node (id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES node (id) ON DELETE CASCADE,
    FOREIGN KEY(creator_id) REFERENCES app_user (id) ON DELETE SET NULL
);

CREATE INDEX ix_knowledge_link_target ON knowledge_link (target_id);

CREATE TABLE task_dependency (
    task_id VARCHAR(36) NOT NULL,
    requires_id VARCHAR(36) NOT NULL,
    PRIMARY KEY (task_id, requires_id),
    CONSTRAINT ck_task_dependency_distinct CHECK (task_id <> requires_id),
    FOREIGN KEY(task_id) REFERENCES work_item (id) ON DELETE CASCADE,
    FOREIGN KEY(requires_id) REFERENCES work_item (id) ON DELETE CASCADE
);

CREATE TABLE workspace_draft (
    user_id BIGINT NOT NULL,
    project_id BIGINT NOT NULL,
    kind VARCHAR(16) NOT NULL,
    payload JSONB NOT NULL,
    version INTEGER NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (user_id, project_id, kind),
    FOREIGN KEY(user_id) REFERENCES app_user (id) ON DELETE CASCADE,
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE
);

CREATE TABLE ai_project_policy (
    project_id BIGINT NOT NULL,
    daily_limit INTEGER NOT NULL,
    input_limit INTEGER NOT NULL,
    version INTEGER NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (project_id),
    CONSTRAINT ck_ai_policy_limits CHECK (daily_limit BETWEEN 0 AND 100 AND input_limit BETWEEN 100 AND 16000),
    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE
);

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX ix_node_content_trgm ON node USING gin (content gin_trgm_ops);

CREATE INDEX ix_work_item_title_trgm ON work_item USING gin (title gin_trgm_ops);

UPDATE alembic_version SET version_num='b922003' WHERE alembic_version.version_num = 'b922002';

-- Running upgrade b922003 -> b922004

ALTER TABLE work_item ADD COLUMN checklist JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE work_item ADD COLUMN repeat_every_days INTEGER;

ALTER TABLE work_item ADD COLUMN recurrence_parent_id VARCHAR(36);

ALTER TABLE work_item ADD CONSTRAINT fk_work_item_recurrence FOREIGN KEY(recurrence_parent_id) REFERENCES work_item (id) ON DELETE SET NULL;

ALTER TABLE work_item ADD CONSTRAINT uq_work_item_recurrence_parent UNIQUE (recurrence_parent_id);

ALTER TABLE work_item ADD CONSTRAINT ck_work_item_repeat CHECK (repeat_every_days IS NULL OR (repeat_every_days BETWEEN 1 AND 365 AND due_date IS NOT NULL));

CREATE INDEX ix_work_item_assignee_due ON work_item (assignee_id, due_date, id);

CREATE INDEX ix_work_item_project_status_due ON work_item (project_id, status, due_date);

UPDATE alembic_version SET version_num='b922004' WHERE alembic_version.version_num = 'b922003';

COMMIT;
