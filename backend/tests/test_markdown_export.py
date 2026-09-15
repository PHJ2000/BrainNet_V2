import pytest
from fastapi import HTTPException
from app.services.project_snapshot import Snapshot, traversal
from app.services.markdown_export import render_markdown, safe_filename

def snapshot():
    nodes = [{"id": i + 1, "parent_id": i or None, "state": "ACTIVE" if i != 2 else "GHOST",
              "content": f"노드 {i + 1}\n한글 😀 <script> / [link](url)\n```python\nprint('x')\n```",
              "order_index": 0, "depth": i, "pos_x": None, "pos_y": 0} for i in range(9)]
    return Snapshot({"name": "한글 *프로젝트*", "description": "설명"}, nodes,
                    [{"id": 1, "name": "<tag>", "color": None}], [{"node_id": 9, "tag_id": 1}], "2026-09-13T00:00:00Z")

def test_markdown_scope_states_special_text_deep_tree_and_stable_order():
    data = snapshot()
    text = render_markdown(data)
    assert text.startswith("# 한글 \\*프로젝트\\*")
    assert "노드 3 · 맥락 조상" in text and "노드 2\n한글" in text
    assert "노드 3\n한글" not in text
    assert "```python\nprint('x')\n```" in text
    assert "````text" in text and "#######" not in text
    assert "\\<tag\\>" in text
    assert render_markdown(data) == text
    full = render_markdown(data, include_inactive=True)
    assert "노드 3\n한글" in full
    branch = render_markdown(data, root_id=8, include_inactive=True)
    assert "노드 7" not in branch and "노드 8" in branch and "노드 9" in branch
    data.nodes = list(reversed(data.nodes))
    assert render_markdown(data) == text

def test_empty_snapshot_invalid_graph_and_windows_names():
    data = snapshot(); data.nodes = []; data.node_tags = []
    assert "맞는 노드가 없습니다" in render_markdown(data)
    with pytest.raises(HTTPException): render_markdown(data, root_id=5)
    with pytest.raises(HTTPException): traversal([{"id": 1, "parent_id": 1, "order_index": 0}])
    with pytest.raises(HTTPException): traversal([{"id": 1, "parent_id": 2, "order_index": 0}])
    assert safe_filename("CON", "md") == "_CON.md"
    assert safe_filename('A/B:한글?. ', "md") == "A_B_한글_.md"
