import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    JWT_SECRET="test-secret-at-least-32-bytes-long-0123",
    INTERNAL_TOKEN="test-internal",
    PAYMENT_PROVIDER="mock",
)

import pytest  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:  # provider tests can still run without the web stack
    TestClient = None

from shopcommon.http_client import UpstreamError  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal"}


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.down = False

    def notify(self, order_id, status, payment_id):
        if self.down:
            raise UpstreamError(503, "orders down")
        self.calls.append((order_id, status, payment_id))


def auth(user_id: int = 1) -> dict[str, str]:
    from shopcommon.config import get_settings
    from shopcommon.security import Principal, create_access_token

    s = get_settings()
    tok = create_access_token(
        Principal(user_id, f"u{user_id}@shop.test", "customer"),
        secret=s.jwt_secret,
        issuer=s.jwt_issuer,
        audience=s.jwt_audience,
        ttl_seconds=300,
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def notifier():
    from app.deps import get_notifier
    from app.main import app

    n = FakeNotifier()
    app.dependency_overrides[get_notifier] = lambda: n
    yield n
    app.dependency_overrides.clear()


@pytest.fixture
def client(notifier):
    from app.main import app
    from shopcommon.db import Base, get_engine

    Base.metadata.drop_all(get_engine())
    with TestClient(app) as c:
        yield c
