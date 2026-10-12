from conftest import INTERNAL, auth


def _create(client, order_id=10, user_id=1, amount=2400):
    return client.post(
        "/internal/payments",
        json={"order_id": order_id, "user_id": user_id, "amount_pence": amount, "currency": "gbp"},
        headers=INTERNAL,
    )


def test_config(client):
    assert client.get("/payments/config").json() == {"provider": "mock", "publishable_key": None}


def test_create_requires_internal_token(client):
    r = client.post(
        "/internal/payments",
        json={"order_id": 1, "user_id": 1, "amount_pence": 100, "currency": "GBP"},
    )
    assert r.status_code == 403


def test_create_is_idempotent_per_order(client):
    a = _create(client).json()
    b = _create(client).json()
    assert a["id"] == b["id"]
    assert a["currency"] == "GBP"
    assert a["status"] == "requires_payment"


def test_successful_card(client, notifier):
    pid = _create(client).json()["id"]
    r = client.post(
        f"/payments/{pid}/confirm", json={"card_number": "4242 4242 4242 4242"}, headers=auth()
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded"
    assert notifier.calls == [(10, "PAID", pid)]
    # Can't pay twice
    assert _create(client).status_code == 409
    again = client.post(
        f"/payments/{pid}/confirm", json={"card_number": "4242424242424242"}, headers=auth()
    )
    assert again.status_code == 409


def test_declined_card_allows_retry(client, notifier):
    pid = _create(client).json()["id"]
    r = client.post(
        f"/payments/{pid}/confirm", json={"card_number": "4000000000000002"}, headers=auth()
    )
    assert r.json()["status"] == "failed"
    assert r.json()["failure_reason"] == "card_declined"
    assert notifier.calls == [(10, "PAYMENT_FAILED", pid)]
    # A new attempt gets a fresh payment
    assert _create(client).json()["id"] != pid


def test_other_user_cannot_confirm(client):
    pid = _create(client, user_id=1).json()["id"]
    r = client.post(
        f"/payments/{pid}/confirm", json={"card_number": "4242424242424242"}, headers=auth(2)
    )
    assert r.status_code == 404
    assert client.get(f"/payments/{pid}", headers=auth(2)).status_code == 404


def test_orders_outage_is_recorded(client, notifier):
    notifier.down = True
    pid = _create(client).json()["id"]
    r = client.post(
        f"/payments/{pid}/confirm", json={"card_number": "4242424242424242"}, headers=auth()
    )
    assert r.json()["status"] == "succeeded"
    assert "shop_payment_notify_failures_total 1.0" in client.get("/metrics").text


def test_stripe_webhook_ignored_for_mock(client):
    assert client.post("/webhooks/stripe", content=b"{}").json() == {"received": True}
