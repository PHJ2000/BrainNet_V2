from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import InvalidTokenError as JWTError

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET

SECRET_KEY = JWT_SECRET
ALGORITHM = JWT_ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(sub: str, expires_delta: Optional[timedelta] = None) -> str:
    if not sub.isdigit() or int(sub) <= 0:
        raise ValueError("JWT subject must be a positive numeric user id")
    lifetime = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    expire = datetime.now(timezone.utc) + lifetime
    return jwt.encode({"sub": sub, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if not isinstance(sub, str) or not sub.isdigit() or int(sub) <= 0:
            raise credentials_exc
        return sub
    except JWTError:
        raise credentials_exc


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM],
                         options={"require": ["exp", "sub"], "verify_exp": False})
    sub, expires = payload.get("sub"), payload.get("exp")
    if (not isinstance(sub, str) or not sub.isascii() or not sub.isdigit() or len(sub) > 19 or int(sub) <= 0
            or type(expires) not in (int, float)):
        raise JWTError("Invalid access token claims")
    import math
    if expires > 253402300799 or expires <= datetime.now(timezone.utc).timestamp() or not math.isfinite(expires):
        raise JWTError("Expired access token")
    return payload
