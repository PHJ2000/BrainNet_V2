"""Measure the declared maximum file shape on an explicitly disposable database."""
import asyncio
import json
import os
import time
import tracemalloc
from pathlib import Path
from uuid import uuid4
from sqlalchemy import delete
from app.db.session import AsyncSessionLocal
from app.db.models.project import Project
from app.services.project_backup import parse_backup, import_backup, export_backup
from app.services.project_snapshot import read_snapshot

async def main():
    if os.getenv("ALLOW_TEST_DATABASE_RESET") != "1" or not os.environ["POSTGRES_URL"].endswith("/brainnet_test"):
        raise SystemExit("Dedicated brainnet_test database required")
    data = {"schema_version": 1, "exported_at": "2026-09-13T00:00:00Z", "project": {"name": "backup limit fixture"},
            "nodes": [], "tags": [{"ref": str(i), "name": f"태그 {i}", "color": "#6366f1"} for i in range(5000)],
            "node_tags": [{"node_ref": str(i), "tag_ref": str((i + j) % 5000)} for i in range(5000) for j in range(10)]}
    for i in range(5000):
        depth = (i - 1) % 100 + 1 if i else 0
        data["nodes"].append({"ref": str(i), "parent_ref": str(i - 1 if depth > 1 else 0) if i else None,
            "content": f"한글 노드 {i}", "state": "ACTIVE" if not i else "GHOST", "depth": depth,
            "order_index": i, "pos_x": i % 30 * 200, "pos_y": i // 30 * 120})
    raw = json.dumps(data, ensure_ascii=False).encode()
    tracemalloc.start(); start = time.perf_counter(); backup = parse_backup(raw)
    validation_ms = (time.perf_counter() - start) * 1000
    _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    start = time.perf_counter()
    result = None
    try:
        async with AsyncSessionLocal() as db:
            result = await import_backup(db, 7, f"max-shape-{uuid4()}", backup)
        import_ms = (time.perf_counter() - start) * 1000
        saved = parse_backup(export_backup(await read_snapshot(result["project_id"], 7)))
        assert len(saved.nodes) == 5000 and len(saved.tags) == 5000 and len(saved.node_tags) == 50000
        report = {"nodes": 5000, "tags": 5000, "links": 50000, "depth": 100, "input_bytes": len(raw),
                  "validation_ms": round(validation_ms, 1), "validation_peak_mib": round(peak / 2**20, 1),
                  "import_ms": round(import_ms, 1), "round_trip_counts_match": True}
        path = Path("experiments/runtime-nodes/results/next-version-2026-09-13/backup-limits.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        if result:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Project).where(Project.id == result["project_id"], Project.owner_id == 7,
                                                       Project.name == "backup limit fixture"))
                await db.commit()

if __name__ == "__main__": asyncio.run(main())
