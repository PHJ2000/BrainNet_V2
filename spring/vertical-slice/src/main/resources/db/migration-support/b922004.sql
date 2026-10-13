
ALTER TABLE work_item ADD COLUMN checklist JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE work_item ADD COLUMN repeat_every_days INTEGER;

ALTER TABLE work_item ADD COLUMN recurrence_parent_id VARCHAR(36);

ALTER TABLE work_item ADD CONSTRAINT fk_work_item_recurrence FOREIGN KEY(recurrence_parent_id) REFERENCES work_item (id) ON DELETE SET NULL;

ALTER TABLE work_item ADD CONSTRAINT uq_work_item_recurrence_parent UNIQUE (recurrence_parent_id);

ALTER TABLE work_item ADD CONSTRAINT ck_work_item_repeat CHECK (repeat_every_days IS NULL OR (repeat_every_days BETWEEN 1 AND 365 AND due_date IS NOT NULL));

CREATE INDEX ix_work_item_assignee_due ON work_item (assignee_id, due_date, id);

CREATE INDEX ix_work_item_project_status_due ON work_item (project_id, status, due_date);
