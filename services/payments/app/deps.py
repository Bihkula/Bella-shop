from functools import lru_cache

from shopcommon.config import env
from shopcommon.http_client import ServiceClient

from .providers import PaymentProvider, build_provider


@lru_cache
def get_provider() -> PaymentProvider:
    return build_provider(
        env("PAYMENT_PROVIDER", "mock") or "mock",
        secret_key=env("STRIPE_SECRET_KEY", "") or "",
        webhook_secret=env("STRIPE_WEBHOOK_SECRET", "") or "",
        publishable_key=env("STRIPE_PUBLISHABLE_KEY", "") or "",
    )


class OrdersNotifier:
    def __init__(self) -> None:
        self.http = ServiceClient(env("ORDERS_URL", "http://orders:8000") or "")

    def notify(self, order_id: int, status: str, payment_id: str) -> None:
        self.http.request(
            "POST",
            f"/internal/orders/{order_id}/status",
            {"status": status, "payment_id": payment_id},
        )


def get_notifier() -> OrdersNotifier:
    return OrdersNotifier()
