# backend/app/db/session.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

# .env 불러오기
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL 환경 변수가 설정되지 않았습니다.")

sqlalchemy_echo = os.getenv("SQLALCHEMY_ECHO", "false").strip().lower()
if sqlalchemy_echo not in {"true", "false"}:
    raise ValueError("SQLALCHEMY_ECHO must be true or false")

engine = create_async_engine(
    DATABASE_URL,
    echo=sqlalchemy_echo == "true",
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
