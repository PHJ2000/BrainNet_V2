import json
import httpx
import pytest
from app.main import app
from app.core.security import create_access_token
from app.services.project_snapshot import MAX_BYTES
from app.routers import project_files
from app.services.project_backup import export_backup
from test_markdown_export import snapshot

@pytest.mark.asyncio
async def test_preview_is_read_only_and_checks_auth_and_size_before_parsing(monkeypatch):
    async def no_write(*args, **kwargs): raise AssertionError("preview must not call import")
    monkeypatch.setattr(project_files.backup_service, "import_backup", no_write)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/projects/import/preview", content=b"{}")).status_code == 401
        headers = {"Authorization": "Bearer " + create_access_token("7"), "Content-Type": "application/json"}
        ok = await client.post("/projects/import/preview", headers=headers, content=export_backup(snapshot()))
        assert ok.status_code == 200 and ok.json()["node_count"] == 9
        large = await client.post("/projects/import/preview", headers={**headers, "Content-Length": str(MAX_BYTES + 1)}, content=b"{}");
        assert large.status_code == 413
        invalid = await client.post("/projects/import/preview", headers=headers, content=b'{"schema_version":99}')
        assert invalid.status_code == 422 and "schema_version" in invalid.json()["message"]

@pytest.mark.asyncio
async def test_stream_limit_also_applies_without_content_length():
    from app.routers.project_files import read_backup
    class Stream:
        headers = {}
        async def stream(self):
            yield b"x" * MAX_BYTES
            yield b"x"
            raise AssertionError("must stop reading immediately at the limit")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error: await read_backup(Stream())
    assert error.value.status_code == 413
