
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
