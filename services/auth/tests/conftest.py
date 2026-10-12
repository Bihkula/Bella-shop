import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    JWT_SECRET="test-secret-at-least-32-bytes-long-0123",
    INTERNAL_TOKEN="test-internal",
    ADMIN_EMAIL="admin@shop.test",
    ADMIN_PASSWORD="admin-pass-123",
    PASSWORD_HASH_ITERATIONS="1000",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import throttle  # noqa: E402
from app.main import app  # noqa: E402
from shopcommon.db import Base, get_engine  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(get_engine())
    throttle._failures.clear()
    with TestClient(app) as c:
        yield c
