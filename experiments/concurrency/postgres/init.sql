CREATE TABLE IF NOT EXISTS benchmark_root (
    project_id BIGINT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

