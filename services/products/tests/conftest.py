import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    JWT_SECRET="test-secret-at-least-32-bytes-long-0123",
    INTERNAL_TOKEN="test-internal",
    SEED_SAMPLE_DATA="true",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from shopcommon.config import get_settings  # noqa: E402
from shopcommon.db import Base, get_engine  # noqa: E402
from shopcommon.security import Principal, create_access_token  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal"}


def token_for(role: str, user_id: int = 1) -> dict[str, str]:
    s = get_settings()
    tok = create_access_token(
        Principal(user_id, f"{role}@shop.test", role),
        secret=s.jwt_secret,
        issuer=s.jwt_issuer,
        audience=s.jwt_audience,
        ttl_seconds=300,
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def client():
    Base.metadata.drop_all(get_engine())
    with TestClient(app) as c:
        yield c
