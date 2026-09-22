"""One authorized, repeatable-read snapshot shared by both export formats."""
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal
from app.db.models.project import Project
from app.db.models.node import Node
from app.db.models.tag import Tag
from app.db.models.tag_node import TagNode
from app.services.node_operations import authorize, fail

MAX_NODES = 5000
MAX_DEPTH = 100
MAX_TAGS = 5000
MAX_LINKS = 50000
MAX_BYTES = 10 * 1024 * 1024


@dataclass
class Snapshot:
    project: dict
    nodes: list[dict]
    tags: list[dict]
    node_tags: list[dict]
    exported_at: str
    workspace: dict | None = None


def traversal(nodes):
    by_id = {n["id"]: n for n in nodes}
    if len(by_id) != len(nodes):
        fail("INVALID_GRAPH", "nodes: duplicate IDs", 422)
    children = {}
    for n in nodes:
        if n["parent_id"] is not None and n["parent_id"] not in by_id:
            fail("INVALID_GRAPH", f"nodes.{n['id']}.parent_id: missing parent", 422)
        children.setdefault(n["parent_id"], []).append(n)
    for values in children.values():
        values.sort(key=lambda n: (n["order_index"], n["id"]))
    ordered, depths = [], {}
    stack = [(n, 0) for n in reversed(children.get(None, []))]
    while stack:
        n, depth = stack.pop()
        if n["id"] in depths:
            fail("INVALID_GRAPH", "nodes: parent cycle", 422)
        if depth > MAX_DEPTH:
            fail("PROJECT_LIMIT", f"nodes.{n['id']}: maximum depth is {MAX_DEPTH}", 422)
        depths[n["id"]] = depth
        ordered.append(n)
        stack.extend((c, depth + 1) for c in reversed(children.get(n["id"], [])))
    if len(ordered) != len(nodes):
        fail("INVALID_GRAPH", "nodes: parent cycle or missing root", 422)
    return ordered, depths


async def read_snapshot(project_id, actor_id, include_workspace=False):
    async with AsyncSessionLocal() as db:
        await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await authorize(db, project_id, actor_id)
        project = await db.get(Project, project_id)
        rows = (await db.execute(select(Node).where(Node.project_id == project_id)
                                 .order_by(Node.id).limit(MAX_NODES + 1))).scalars().all()
        tags = (await db.execute(select(Tag).where(Tag.project_id == project_id)
                                 .order_by(Tag.id).limit(MAX_TAGS + 1))).scalars().all()
        links = (await db.execute(select(TagNode.node_id, TagNode.tag_id).join(Node, Node.id == TagNode.node_id)
                    .where(Node.project_id == project_id).order_by(TagNode.node_id, TagNode.tag_id)
                    .limit(MAX_LINKS + 1))).all()
        if len(rows) > MAX_NODES or len(tags) > MAX_TAGS or len(links) > MAX_LINKS:
            fail("PROJECT_LIMIT", f"Export supports {MAX_NODES} nodes, {MAX_TAGS} tags and {MAX_LINKS} links", 422)
        snapshot = Snapshot({"name": project.name, "description": project.description},
            [{"id": n.id, "parent_id": n.parent_id, "content": n.content, "state": n.state.value,
              "depth": n.depth, "order_index": n.order_index, "pos_x": n.pos_x, "pos_y": n.pos_y} for n in rows],
            [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
            [{"node_id": n, "tag_id": t} for n, t in links], datetime.now(timezone.utc).isoformat())
        traversal(snapshot.nodes)
        tag_ids = {t["id"] for t in snapshot.tags}
        if any(link["tag_id"] not in tag_ids for link in snapshot.node_tags):
            fail("INVALID_GRAPH", "node_tags: tag belongs to another project", 422)
        if include_workspace:
            from app.services.workspace_backup import read_workspace
            snapshot.workspace = await read_workspace(db, project_id, actor_id)
        return snapshot
