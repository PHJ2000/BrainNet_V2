"""Plain UTF-8 Markdown; original text is preserved in safe fenced blocks."""
import re
from app.services.project_snapshot import traversal
from app.services.node_operations import fail


def safe_filename(name, extension):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:80].rstrip(" .") or "BrainNet"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return f"{value}.{extension}"


def escaped(value):
    # Metadata never becomes active HTML/Markdown; multiline original text is fenced below.
    value = value.replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", value)


def fenced(value, indent=""):
    longest = max((len(m.group()) for m in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return "\n".join(indent + line for line in [fence + "text", *value.split("\n"), fence])


def render_markdown(snapshot, root_id=None, include_inactive=False):
    ordered, depths = traversal(snapshot.nodes)
    by_id = {n["id"]: n for n in ordered}
    if root_id is not None and root_id not in by_id:
        fail("NODE_NOT_FOUND", "Selected export branch no longer exists", 404)
    scope = set()
    for n in ordered:
        if root_id is None or n["id"] == root_id or n["parent_id"] in scope:
            scope.add(n["id"])
    included = {n["id"] for n in ordered if n["id"] in scope and (include_inactive or n["state"] == "ACTIVE")}
    context = set()
    for node_id in included:
        parent = by_id[node_id]["parent_id"]
        while parent in scope:
            if parent not in included:
                context.add(parent)
            parent = by_id[parent]["parent_id"]
    tag_names = {t["id"]: t["name"] for t in snapshot.tags}
    attached = {}
    for link in snapshot.node_tags:
        attached.setdefault(link["node_id"], []).append(tag_names[link["tag_id"]])
    lines = [f"# {escaped(snapshot.project['name'])}", "", f"내보낸 시각: {snapshot.exported_at}",
             f"범위: {'전체 프로젝트' if root_id is None else f'노드 {root_id}와 모든 자손'}",
             f"상태: {'ACTIVE / GHOST / ARCHIVED' if include_inactive else 'ACTIVE (나머지 조상은 맥락 표시)'}", "",
             "원문은 text 코드 블록에 보존됩니다. 맥락 조상은 관계 표시용이며 본문을 포함하지 않습니다.", ""]
    if snapshot.project.get("description"):
        lines += ["## 프로젝트 설명", "", fenced(snapshot.project["description"]), ""]
    base_depth = depths.get(root_id, 0)
    for n in ordered:
        node_id = n["id"]
        if node_id not in included | context:
            continue
        depth = depths[node_id] - base_depth
        title = f"노드 {node_id}" + (" · 맥락 조상" if node_id in context else "")
        indent = "" if depth < 5 else "  " * (depth - 5) + "  "
        lines += [("#" * (depth + 2) + " " + title) if depth < 5 else "  " * (depth - 5) + "- **" + title + "**", "",
                  indent + f"상태: {n['state']} · 부모: {n['parent_id'] if n['parent_id'] is not None else '없음'}",
                  indent + "태그: " + (", ".join(escaped(t) for t in attached.get(node_id, [])) or "없음"), ""]
        if node_id in included:
            lines += [fenced(n["content"], indent), ""]
    if not included:
        lines += ["내보내기 조건에 맞는 노드가 없습니다.", ""]
    return "\n".join(lines)
