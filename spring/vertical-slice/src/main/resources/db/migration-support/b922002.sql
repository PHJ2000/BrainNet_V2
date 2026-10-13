
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
