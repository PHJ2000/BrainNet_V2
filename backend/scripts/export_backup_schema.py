"""Generate the published v1 schema/example from the runtime validation model."""
import json
from pathlib import Path
from app.models.project_backup import ProjectBackup

root = Path(__file__).resolve().parents[2]
directory = root / "docs" / "backup"
directory.mkdir(parents=True, exist_ok=True)
schema = ProjectBackup.model_json_schema()
schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "BrainNet project backup v1",
               "description": "Project data only. Maximum UTF-8 file size: 10 MiB. No accounts, credentials, memberships, votes, metrics or operation history."})
(directory / "project-backup-v1.schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
example = {"schema_version": 1, "exported_at": "2026-09-13T00:00:00Z",
    "project": {"name": "나의 아이디어", "description": "로컬 백업 예제"},
    "nodes": [{"ref": "n1", "parent_ref": None, "content": "여행 계획", "state": "ACTIVE", "depth": 0, "order_index": 0, "pos_x": 400, "pos_y": 300},
              {"ref": "n2", "parent_ref": "n1", "content": "준비할 것\n지도와 충전기", "state": "GHOST", "depth": 1, "order_index": 0, "pos_x": 600, "pos_y": 450}],
    "tags": [{"ref": "t1", "name": "준비", "color": "#6366f1"}],
    "node_tags": [{"node_ref": "n2", "tag_ref": "t1"}], "depth_adjustments": []}
ProjectBackup.model_validate(example)
(directory / "example-v1.json").write_text(json.dumps(example, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Published v1 schema and validated example")
