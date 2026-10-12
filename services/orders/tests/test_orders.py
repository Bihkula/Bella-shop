from app.models import OrderStatus
from conftest import INTERNAL, auth


def _create(client, items=None, user_id=1):
    items = items or [{"product_id": 1, "quantity": 2}]
    return client.post("/orders", json={"items": items}, headers=auth(user_id))


def test_create_order_totals(client):
    r = _create(client, [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 1}])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_pence"] == 2 * 1200 + 2500
    assert body["status"] == "PENDING_PAYMENT"
    assert len(body["lines"]) == 2


def test_out_of_stock_passes_through(client):
    r = _create(client, [{"product_id": 2, "quantity": 5}])
    assert r.status_code == 409


def test_requires_login(client):
    assert client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]}).status_code == 401


def test_users_cannot_see_each_others_orders(client):
    oid = _create(client, user_id=1).json()["id"]
    assert client.get(f"/orders/{oid}", headers=auth(1)).status_code == 200
    assert client.get(f"/orders/{oid}", headers=auth(2)).status_code == 404
    assert client.get(f"/orders/{oid}", headers=auth(99, "admin")).status_code == 200
    assert client.get("/orders", headers=auth(2)).json() == []


def test_checkout_calls_payments(client, fakes):
    _, payments = fakes
    oid = _create(client).json()["id"]
    r = client.post(f"/orders/{oid}/checkout", headers=auth())
    assert r.status_code == 200, r.text
    assert r.json()["payment_id"] == f"pay_{oid}"
    assert payments.calls[0]["amount_pence"] == 2400
    assert payments.calls[0]["currency"] == "GBP"


def test_payment_callback_marks_paid_and_is_idempotent(client):
    oid = _create(client).json()["id"]
    body = {"status": OrderStatus.PAID, "payment_id": "pay_x"}
    for _ in range(2):
        r = client.post(f"/internal/orders/{oid}/status", json=body, headers=INTERNAL)
        assert r.status_code == 200
        assert r.json()["status"] == "PAID"
    # A paid order can't be checked out or cancelled again.
    assert client.post(f"/orders/{oid}/checkout", headers=auth()).status_code == 409
    assert client.post(f"/orders/{oid}/cancel", headers=auth()).status_code == 409


def test_illegal_transition_rejected(client):
    oid = _create(client).json()["id"]
    client.post(f"/orders/{oid}/cancel", headers=auth())
    r = client.post(
        f"/internal/orders/{oid}/status",
        json={"status": "PAID", "payment_id": "p"},
        headers=INTERNAL,
    )
    assert r.status_code == 409


def test_callback_needs_internal_token(client):
    oid = _create(client).json()["id"]
    r = client.post(f"/internal/orders/{oid}/status", json={"status": "PAID", "payment_id": "p"})
    assert r.status_code == 403


def test_cancel_releases_stock(client, fakes):
    products, _ = fakes
    oid = _create(client, [{"product_id": 1, "quantity": 3}]).json()["id"]
    assert products.stock[1] == 2
    r = client.post(f"/orders/{oid}/cancel", headers=auth())
    assert r.json()["status"] == "CANCELLED"
    assert products.stock[1] == 5


def test_retry_after_failed_payment(client):
    oid = _create(client).json()["id"]
    client.post(
        f"/internal/orders/{oid}/status",
        json={"status": "PAYMENT_FAILED", "payment_id": "p"},
        headers=INTERNAL,
    )
    assert client.post(f"/orders/{oid}/checkout", headers=auth()).status_code == 200


def test_payments_outage_masked_as_503(client, fakes):
    from shopcommon.http_client import UpstreamError

    _, payments = fakes
    payments.fail_with = UpstreamError(500, "boom: internal stack trace")
    oid = _create(client).json()["id"]
    r = client.post(f"/orders/{oid}/checkout", headers=auth())
    assert r.status_code == 503
    assert "stack trace" not in r.text


def test_state_machine():
    assert OrderStatus.can_move("PENDING_PAYMENT", "PAID")
    assert OrderStatus.can_move("PAYMENT_FAILED", "PAID")
    assert not OrderStatus.can_move("PAID", "CANCELLED")
    assert not OrderStatus.can_move("CANCELLED", "PAID")
