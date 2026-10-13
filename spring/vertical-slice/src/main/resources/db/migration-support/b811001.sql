
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
