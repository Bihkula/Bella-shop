"""Clients for sibling services. Wrapped in classes so tests can swap them."""

from shopcommon.config import env
from shopcommon.http_client import ServiceClient


class ProductsClient:
    def __init__(self) -> None:
        self.http = ServiceClient(env("PRODUCTS_URL", "http://products:8000") or "")

    def reserve(self, items: list[dict]) -> list[dict]:
        return self.http.request("POST", "/internal/reserve", {"items": items})["lines"]

    def release(self, items: list[dict]) -> None:
        self.http.request("POST", "/internal/release", {"items": items})


class PaymentsClient:
    def __init__(self) -> None:
        self.http = ServiceClient(env("PAYMENTS_URL", "http://payments:8000") or "")

    def create_payment(
        self, *, order_id: int, user_id: int, amount_pence: int, currency: str
    ) -> dict:
        return self.http.request(
            "POST",
            "/internal/payments",
            {
                "order_id": order_id,
                "user_id": user_id,
                "amount_pence": amount_pence,
                "currency": currency,
            },
        )


def get_products_client() -> ProductsClient:
    return ProductsClient()


def get_payments_client() -> PaymentsClient:
    return PaymentsClient()
