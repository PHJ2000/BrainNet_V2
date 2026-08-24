from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select

from app.core.security import ALGORITHM, SECRET_KEY
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.session import AsyncSessionLocal
from app.utils.ws_manager import connect, disconnect

router = APIRouter()


@router.websocket("/projects/{project_id}/ws")
async def project_ws(
    project_id: int,
    websocket: WebSocket,
    token: str = Query(...),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if (
            not isinstance(subject, str)
            or not subject.isdigit()
            or int(subject) <= 0
        ):
            raise JWTError()
        user_id = int(subject)
    except (JWTError, ValueError):
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        membership = await db.execute(
            select(ProjectUserRole.project_id)
            .join(Project, Project.id == ProjectUserRole.project_id)
            .where(
                ProjectUserRole.project_id == project_id,
                ProjectUserRole.user_id == user_id,
                Project.is_deleted.is_(False),
            )
        )
        if membership.scalar_one_or_none() is None:
            await websocket.close(code=4403)
            return

    await connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        disconnect(project_id, websocket)
