from conftest import INTERNAL, token_for


def test_catalogue_is_seeded(client):
    r = client.get("/products")
    assert r.status_code == 200
    assert len(r.json()) == 6


def test_search(client):
    names = [p["name"] for p in client.get("/products", params={"q": "mug"}).json()]
    assert names == ["Enamel Camp Mug"]


def test_get_missing(client):
    assert client.get("/products/9999").status_code == 404


def test_create_requires_admin(client):
    body = {"sku": "NEW-1", "name": "New", "price_pence": 100, "stock": 1}
    assert client.post("/products", json=body).status_code == 401
    assert client.post("/products", json=body, headers=token_for("customer")).status_code == 403
    r = client.post("/products", json=body, headers=token_for("admin"))
    assert r.status_code == 201
    assert client.post("/products", json=body, headers=token_for("admin")).status_code == 409


def test_update_and_deactivate(client):
    r = client.patch("/products/1", json={"price_pence": 999}, headers=token_for("admin"))
    assert r.json()["price_pence"] == 999
    client.patch("/products/1", json={"active": False}, headers=token_for("admin"))
    assert client.get("/products/1").status_code == 404


def test_reserve_and_release(client):
    before = client.get("/products/1").json()["stock"]
    r = client.post(
        "/internal/reserve",
        json={"items": [{"product_id": 1, "quantity": 2}, {"product_id": 1, "quantity": 1}]},
        headers=INTERNAL,
    )
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["quantity"] == 3
    assert line["unit_price_pence"] == 1200
    assert client.get("/products/1").json()["stock"] == before - 3

    client.post(
        "/internal/release", json={"items": [{"product_id": 1, "quantity": 3}]}, headers=INTERNAL
    )
    assert client.get("/products/1").json()["stock"] == before


def test_reserve_is_all_or_nothing(client):
    before = client.get("/products/2").json()["stock"]
    r = client.post(
        "/internal/reserve",
        json={"items": [{"product_id": 2, "quantity": 1}, {"product_id": 3, "quantity": 100}]},
        headers=INTERNAL,
    )
    assert r.status_code == 409
    assert client.get("/products/2").json()["stock"] == before


def test_reserve_unknown_product(client):
    r = client.post(
        "/internal/reserve", json={"items": [{"product_id": 999, "quantity": 1}]}, headers=INTERNAL
    )
    assert r.status_code == 404


def test_internal_endpoints_need_token(client):
    body = {"items": [{"product_id": 1, "quantity": 1}]}
    assert client.post("/internal/reserve", json=body).status_code == 403
    r = client.post("/internal/reserve", json=body, headers={"X-Internal-Token": "nope"})
    assert r.status_code == 403
