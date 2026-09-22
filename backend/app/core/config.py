import os


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(f"{name} environment variable is required")
    return value.strip()


def jwt_secret_env() -> str:
    value = required_env("JWT_SECRET")
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 bytes")
    return value


def positive_int_env(name: str, default: str) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def bool_env(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return value == "true"


JWT_SECRET = jwt_secret_env()
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
if JWT_ALGORITHM != "HS256":
    raise RuntimeError("JWT_ALGORITHM must be HS256 during legacy/Spring coexistence")

ACCESS_TOKEN_EXPIRE_MINUTES = positive_int_env("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
REQUIRE_NODE_VERSION = bool_env("REQUIRE_NODE_VERSION", "true")


def allowed_origins() -> list[str]:
    from urllib.parse import urlsplit
    origins = [s.strip().rstrip("/") for s in os.getenv(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:18080"
    ).split(",") if s.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise RuntimeError("CORS_ALLOWED_ORIGINS must contain explicit HTTP(S) origins")
    return origins
