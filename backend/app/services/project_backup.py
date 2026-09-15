"""Validated project files and one-transaction import into a fresh project."""
import hashlib
import json
from datetime import datetime, timezone
from pydantic import ValidationError
from sqlalchemy import insert, select, text
from app.db.models.node import Node
from app.db.models.project import Project
from app.db.models.project_import import ProjectImport
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.tag import Tag
from app.db.models.tag_node import TagNode
from app.db.models.user import User
from app.models.project_backup import ProjectBackup, EXCLUDED
from app.services.project_snapshot import MAX_BYTES, traversal
from app.services.node_operations import digest, fail


def export_backup(snapshot):
    ordered, depths = traversal(snapshot.nodes)
    refs = {n["id"]: f"n{i + 1}" for i, n in enumerate(ordered)}
    tag_refs = {t["id"]: f"t{i + 1}" for i, t in enumerate(snapshot.tags)}
    data = {"schema_version": 1, "exported_at": snapshot.exported_at, "project": snapshot.project,
        "nodes": [{"ref": refs[n["id"]], "parent_ref": refs.get(n["parent_id"]),
                   **{k: n[k] for k in ("content", "state", "order_index", "pos_x", "pos_y")},
                   "depth": depths[n["id"]]} for n in ordered],
        "tags": [{"ref": tag_refs[t["id"]], "name": t["name"], "color": t["color"]} for t in snapshot.tags],
        "node_tags": sorted([{"node_ref": refs[r["node_id"]], "tag_ref": tag_refs[r["tag_id"]]}
                            for r in snapshot.node_tags], key=lambda r: (r["node_ref"], r["tag_ref"])),
        "depth_adjustments": [{"node_ref": refs[n["id"]], "stored_depth": n["depth"], "depth": depths[n["id"]]}
                              for n in ordered if n["depth"] != depths[n["id"]]]}
    try:
        data = ProjectBackup.model_validate(data).model_dump(mode="json")
    except ValidationError as error:
        validation_failure(error)
    result = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(result) > MAX_BYTES:
        fail("BACKUP_TOO_LARGE", "Backup exceeds the 10 MiB UTF-8 file limit", 413)
    return result


def validation_failure(error):
    first = error.errors()[0]
    path = ".".join(str(part) for part in first["loc"]) or "file"
    fail("BACKUP_INVALID", f"{path}: {first['msg']}", 422)


def parse_backup(raw):
    if len(raw) > MAX_BYTES:
        fail("BACKUP_TOO_LARGE", "File exceeds the 10 MiB limit", 413)
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_keys,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite value: {value}")))
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            fail("BACKUP_VERSION", "schema_version: only version 1 is supported", 422)
        return ProjectBackup.model_validate(value)
    except ValidationError as error:
        validation_failure(error)
    except (ValueError, UnicodeError, RecursionError) as error:
        fail("BACKUP_INVALID", f"file: invalid UTF-8 JSON ({str(error)[:160]})", 422)


def preview_backup(backup):
    return {"name": backup.project.name, "description": backup.project.description,
            "node_count": len(backup.nodes), "tag_count": len(backup.tags), "link_count": len(backup.node_tags),
            "excluded": EXCLUDED, "depth_adjustments": [a.model_dump() for a in backup.depth_adjustments],
            "states": {s: sum(n.state == s for n in backup.nodes) for s in ("ACTIVE", "GHOST", "ARCHIVED")}}


async def _reserve_ids(db, table, count):
    # Table is an internal constant, never supplied by the file.
    if not count: return []
    return list((await db.execute(text("SELECT nextval(pg_get_serial_sequence(:table, 'id')) FROM generate_series(1, :count)"),
                    {"table": table, "count": count})).scalars().all())


async def import_backup(db, actor_id, key, backup):
    actor_id = int(actor_id)
    if not key.strip() or len(key) > 128:
        fail("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must contain 1 to 128 characters", 422)
    fingerprint = digest(backup.model_dump(mode="json"))
    lock = int(hashlib.sha256(f"project-import:{actor_id}:{key}".encode()).hexdigest()[:15], 16)
    try:
        await db.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
        if await db.get(User, actor_id) is None:
            fail("UNAUTHORIZED", "Account no longer exists", 401)
        prior = await db.get(ProjectImport, (actor_id, key))
        if prior:
            if prior.request_hash != fingerprint:
                fail("IDEMPOTENCY_KEY_REUSED", "Key belongs to a different backup", 409)
            project = await db.get(Project, prior.project_id) if prior.project_id else None
            if not project or project.is_deleted or project.owner_id != actor_id:
                fail("IMPORT_RESULT_GONE", "The original imported project is no longer available", 410)
            return {"project_id": project.id, "name": project.name}
        project = Project(owner_id=actor_id, name=backup.project.name,
                          description=backup.project.description, is_deleted=False)
        db.add(project); await db.flush()
        db.add(ProjectUserRole(project_id=project.id, user_id=actor_id, role="OWNER"))
        node_ids = await _reserve_ids(db, "node", len(backup.nodes))
        tag_ids = await _reserve_ids(db, "tag", len(backup.tags))
        node_map = dict(zip((n.ref for n in backup.nodes), node_ids))
        tag_map = dict(zip((t.ref for t in backup.tags), tag_ids))
        # Parent-first batches, with fresh versions and actor ownership.
        for depth in sorted({n.depth for n in backup.nodes}):
            values = [{"id": node_map[n.ref], "project_id": project.id, "author_id": actor_id,
                       "parent_id": node_map.get(n.parent_ref), "content": n.content, "state": n.state,
                       "depth": n.depth, "order_index": n.order_index, "pos_x": n.pos_x, "pos_y": n.pos_y,
                       "version": 0} for n in backup.nodes if n.depth == depth]
            await db.execute(insert(Node), values)
        if backup.tags:
            await db.execute(insert(Tag), [{"id": tag_map[t.ref], "project_id": project.id,
                                          "name": t.name, "color": t.color} for t in backup.tags])
        if backup.node_tags:
            await db.execute(insert(TagNode), [{"node_id": node_map[r.node_ref], "tag_id": tag_map[r.tag_ref]}
                                              for r in backup.node_tags])
        db.add(ProjectImport(actor_id=actor_id, request_key=key, request_hash=fingerprint,
                             project_id=project.id, created_at=datetime.now(timezone.utc)))
        await db.commit()
        return {"project_id": project.id, "name": project.name}
    except BaseException:
        await db.rollback()
        raise
