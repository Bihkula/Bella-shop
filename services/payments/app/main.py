from shopcommon.app import create_app

from .api import router
from .deps import get_provider


def check_provider() -> None:
    # Fail fast at startup if the gateway is misconfigured.
    get_provider()


app = create_app("payments", [router], on_startup=check_provider)
