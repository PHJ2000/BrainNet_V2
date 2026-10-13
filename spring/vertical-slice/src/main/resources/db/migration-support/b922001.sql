
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
