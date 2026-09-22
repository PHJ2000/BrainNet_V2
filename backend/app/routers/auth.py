from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.models.user import User
from app.db.dependencies import get_db
from app.models.auth import Token, UserCreate, UserRead
from app.services.passwords import DUMMY_HASH, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])




@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    # Hash before acquiring a connection; the DB enforces email uniqueness.
    pw_hash = await hash_password(body.password)
    user = User(email=body.email, name=body.name, pw_hash=pw_hash,
                created_at=datetime.now(timezone.utc))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        cause = error.orig
        state = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
        if state == "23505" and (await db.execute(
            select(User.id).where(User.email == body.email)
        )).scalar_one_or_none() is not None:
            raise HTTPException(409, "Email already registered") from None
        raise
    await db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    # Legacy short passwords remain usable; do not silently truncate bcrypt input.
    if (len(form.username) > 120 or not 1 <= len(form.password.encode("utf-8")) <= 72
            or "\x00" in form.password):
        raise HTTPException(422, "Invalid login input")
    user = (await db.execute(select(User).where(User.email == form.username))).scalar_one_or_none()
    user_id, hashed = (user.id, user.pw_hash) if user else (None, DUMMY_HASH)
    await db.rollback()  # Release the connection before checking bcrypt.
    valid = await verify_password(form.password, hashed)
    if user_id is None or not valid:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": create_access_token(str(user_id)), "token_type": "Bearer"}
