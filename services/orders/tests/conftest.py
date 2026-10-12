import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    JWT_SECRET="test-secret-at-least-32-bytes-long-0123",
    INTERNAL_TOKEN="test-internal",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.clients import get_payments_client, get_products_client  # noqa: E402
from app.main import app  # noqa: E402
from shopcommon.config import get_settings  # noqa: E402
from shopcommon.db import Base, get_engine  # noqa: E402
from shopcommon.http_client import UpstreamError  # noqa: E402
from shopcommon.security import Principal, create_access_token  # noqa: E402

INTERNAL = {"X-Internal-Token": "test-internal"}

CATALOGUE = {
    1: {"name": "Mug", "price": 1200, "stock": 5},
    2: {"name": "Tee", "price": 2500, "stock": 1},
}


class FakeProducts:
    def __init__(self) -> None:
        self.stock = {pid: p["stock"] for pid, p in CATALOGUE.items()}
        self.released: list[list[dict]] = []

    def reserve(self, items):
        for it in items:
            if it["product_id"] not in CATALOGUE:
                raise UpstreamError(404, "Product not found")
            if self.stock[it["product_id"]] < it["quantity"]:
                raise UpstreamError(409, "Insufficient stock")
        for it in items:
            self.stock[it["product_id"]] -= it["quantity"]
        return [
            {
                "product_id": it["product_id"],
                "name": CATALOGUE[it["product_id"]]["name"],
                "quantity": it["quantity"],
                "unit_price_pence": CATALOGUE[it["product_id"]]["price"],
                "currency": "GBP",
            }
            for it in items
        ]

    def release(self, items):
        self.released.append(items)
        for it in items:
            self.stock[it["product_id"]] += it["quantity"]


class FakePayments:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: UpstreamError | None = None

    def create_payment(self, **kw):
        if self.fail_with:
            raise self.fail_with
        self.calls.append(kw)
        return {"id": f"pay_{kw['order_id']}", "provider": "mock", "status": "requires_payment"}


def auth(user_id: int = 1, role: str = "customer") -> dict[str, str]:
    s = get_settings()
    tok = create_access_token(
        Principal(user_id, f"u{user_id}@shop.test", role),
        secret=s.jwt_secret,
        issuer=s.jwt_issuer,
        audience=s.jwt_audience,
        ttl_seconds=300,
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def fakes():
    products, payments = FakeProducts(), FakePayments()
    app.dependency_overrides[get_products_client] = lambda: products
    app.dependency_overrides[get_payments_client] = lambda: payments
    yield products, payments
    app.dependency_overrides.clear()


@pytest.fixture
def client(fakes):
    Base.metadata.drop_all(get_engine())
    with TestClient(app) as c:
        yield c
