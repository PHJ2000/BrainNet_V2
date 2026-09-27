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

-- Running upgrade 9e1c2a7d4b10 -> c2f4a6b8d010

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'NODE_RESTORE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'NODE_ACTIVATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'NODE_DEACTIVATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'PROJECT_CREATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'PROJECT_UPDATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'PROJECT_DELETE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'TAG_CREATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'TAG_UPDATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'TAG_DELETE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'TAG_REMOVE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'VOTE_CONFIRM';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'SUMMARY_CREATE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'MEMBER_REMOVE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'MEMBER_LEAVE';

ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS 'MEMBER_ROLE_CHANGE';

CREATE INDEX ix_activity_project_id_id ON activity_log (project_id, id);

CREATE INDEX ix_node_project_parent ON node (project_id, parent_id);

INSERT INTO node_version(node_id,version_no,content,author_id,created_at)
                  SELECT id,version,content,NULL,updated_at FROM node
                  ON CONFLICT (node_id,version_no) DO NOTHING;

UPDATE alembic_version SET version_num='c2f4a6b8d010' WHERE alembic_version.version_num = '9e1c2a7d4b10';

COMMIT;
