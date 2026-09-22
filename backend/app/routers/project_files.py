from urllib.parse import quote
from fastapi import APIRouter, Depends, Header, Request, Response
from app.core.security import get_current_user_id
from app.services.project_snapshot import read_snapshot
from app.services.markdown_export import render_markdown, safe_filename
from app.services import project_backup as backup_service
from app.services.project_snapshot import MAX_BYTES
from app.services.node_operations import fail
from app.db.dependencies import get_db

router = APIRouter(prefix="/projects", tags=["Project files"])


@router.get("/{project_id}/export/workspace")
async def workspace_backup(project_id: int, uid=Depends(get_current_user_id)):
    from app.services.workspace_backup import export_workspace
    snapshot = await read_snapshot(project_id, uid, include_workspace=True)
    content = export_workspace(snapshot)
    filename = safe_filename(snapshot.project["name"] + "-workspace", "json")
    return Response(content, media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=workspace.json; filename*=UTF-8''{quote(filename)}",
        "Access-Control-Expose-Headers": "Content-Disposition", "Cache-Control": "no-store"})


async def read_backup(request):
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > MAX_BYTES: fail("BACKUP_TOO_LARGE", "File exceeds the 10 MiB limit", 413)
        except ValueError:
            fail("BACKUP_INVALID", "Invalid Content-Length", 400)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES: fail("BACKUP_TOO_LARGE", "File exceeds the 10 MiB limit", 413)
        chunks.append(chunk)
    return backup_service.parse_backup(b"".join(chunks))


@router.post("/import/preview")
async def import_preview(request: Request, uid=Depends(get_current_user_id)):
    return backup_service.preview_backup(await read_backup(request))


@router.post("/import", status_code=201)
async def import_project(request: Request, idempotency_key: str = Header(alias="Idempotency-Key"),
                         uid=Depends(get_current_user_id), db=Depends(get_db)):
    backup = await read_backup(request)
    return await backup_service.import_backup(db, uid, idempotency_key, backup)


@router.get("/{project_id}/export/json")
async def json_backup(project_id: int, uid=Depends(get_current_user_id)):
    snapshot = await read_snapshot(project_id, uid)
    content = backup_service.export_backup(snapshot)
    filename = safe_filename(snapshot.project["name"], "json")
    return Response(content, media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=brainnet.json; filename*=UTF-8''{quote(filename)}",
        "Access-Control-Expose-Headers": "Content-Disposition", "Cache-Control": "no-store"})


@router.get("/{project_id}/export/markdown")
async def markdown(project_id: int, root_id: int | None = None, include_inactive: bool = False,
                   uid=Depends(get_current_user_id)):
    snapshot = await read_snapshot(project_id, uid)
    content = render_markdown(snapshot, root_id, include_inactive)
    filename = safe_filename(snapshot.project["name"], "md")
    return Response(content, media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=brainnet.md; filename*=UTF-8''{quote(filename)}",
        "Access-Control-Expose-Headers": "Content-Disposition", "Cache-Control": "no-store"})
