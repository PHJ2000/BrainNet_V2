import copy
import json
import pytest
from fastapi import HTTPException
from app.services.project_backup import parse_backup, export_backup, preview_backup
from app.services.project_snapshot import MAX_BYTES
from test_markdown_export import snapshot


def fixture():
    return json.loads(export_backup(snapshot()))


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema_version=2),
    lambda d: d.update(schema_version=True),
    lambda d: d["nodes"].append(d["nodes"][0]),
    lambda d: d["nodes"][1].update(parent_ref="missing"),
    lambda d: d["nodes"][0].update(parent_ref="n2"),
    lambda d: d["nodes"][1].update(depth=0),
    lambda d: d["nodes"][1].update(state="INVALID"),
    lambda d: d["nodes"][1].update(pos_x=float("nan")),
    lambda d: d["nodes"][1].update(order_index=-1),
    lambda d: d["nodes"][1].update(order_index=2147483648),
    lambda d: d["node_tags"][0].update(tag_ref="missing"),
    lambda d: d["node_tags"].append(d["node_tags"][0]),
    lambda d: d["nodes"][1].update(parent_ref=None, depth=0),
    lambda d: d["project"].update(name="a" * 121),
    lambda d: d["project"].update(owner_id=123),
    lambda d: d["nodes"][0].update(content="nul\x00"),
    lambda d: d["nodes"][0].update(content="\ud800"),
])
def test_invalid_backup_is_rejected_with_path(change):
    data = fixture(); change(data)
    with pytest.raises(HTTPException) as error:
        parse_backup(json.dumps(data).encode())
    assert error.value.status_code == 422
    assert error.value.detail["message"]


def test_limits_before_parsing_and_duplicate_json_keys(monkeypatch):
    with pytest.raises(HTTPException): parse_backup(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(HTTPException): parse_backup(b"\xff")
    def must_not_parse(*args, **kwargs): raise AssertionError("size must be checked first")
    monkeypatch.setattr(json, "loads", must_not_parse)
    with pytest.raises(HTTPException) as error: parse_backup(b"x" * (MAX_BYTES + 1))
    assert error.value.status_code == 413


def test_legacy_depth_adjustments_are_explicit_and_do_not_change_source():
    data = snapshot(); data.nodes[5]["depth"] = 0
    before = copy.deepcopy(data.nodes)
    backup = parse_backup(export_backup(data))
    assert preview_backup(backup)["depth_adjustments"] == [{"node_ref": "n6", "stored_depth": 0, "depth": 5}]
    assert data.nodes == before


def test_maximum_node_count_depth_and_overflow():
    data = fixture()
    data["nodes"] = [{**data["nodes"][0], "ref": str(i), "parent_ref": str(i - 1) if i else None,
                       "depth": i, "state": "GHOST"} for i in range(101)]
    data["node_tags"] = []
    assert len(parse_backup(json.dumps(data).encode()).nodes) == 101
    data["nodes"].append({**data["nodes"][-1], "ref": "101", "parent_ref": "100", "depth": 101})
    with pytest.raises(HTTPException): parse_backup(json.dumps(data).encode())
    data["nodes"] = [{**data["nodes"][0], "ref": str(i)} for i in range(5000)]
    assert len(parse_backup(json.dumps(data).encode()).nodes) == 5000
    data["nodes"].append({**data["nodes"][0], "ref": "5000"})
    with pytest.raises(HTTPException): parse_backup(json.dumps(data).encode())
