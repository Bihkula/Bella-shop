def _register(client, email="alice@example.com", password="password123"):
    return client.post("/register", json={"email": email, "password": password})


def _login(client, email="alice@example.com", password="password123"):
    return client.post("/login", json={"email": email, "password": password})


def test_register_and_login(client):
    r = _register(client)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "customer"

    r = _login(client)
    assert r.status_code == 200
    token = r.json()["access_token"]

    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_email_is_case_insensitive(client):
    _register(client, email="Bob@Example.com")
    assert _register(client, email="bob@example.com").status_code == 409
    assert _login(client, email="BOB@example.com").status_code == 200


def test_short_password_rejected(client):
    assert _register(client, password="short").status_code == 422


def test_bad_password(client):
    _register(client)
    assert _login(client, password="wrong-password").status_code == 401


def test_unknown_user_gets_same_error(client):
    r = _login(client, email="nobody@example.com")
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_throttle_after_repeated_failures(client):
    _register(client)
    for _ in range(5):
        _login(client, password="wrong-password")
    assert _login(client).status_code == 429


def test_me_requires_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_admin_seeded(client):
    r = _login(client, email="admin@example.com", password="admin-pass-123")
    token = r.json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "admin"


def test_health_and_metrics(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    _login(client, email="x@example.com")
    body = client.get("/metrics").text
    assert "http_requests_total" in body
    assert 'route="/login"' in body
    assert "shop_auth_logins_total" in body
