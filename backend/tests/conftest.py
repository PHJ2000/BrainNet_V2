import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# Import-time settings deliberately fail closed in production.  Tests provide
# only non-secret deterministic values before application modules are loaded.
os.environ.setdefault("JWT_SECRET", "brainnet-ci-test-secret-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://brainnet:brainnet@localhost:5432/brainnet")
os.environ.setdefault("NODE_EVENTS_ENABLED", "false")
os.environ.setdefault("AI_QUEUE_ENABLED", "false")
