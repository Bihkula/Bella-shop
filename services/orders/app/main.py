from shopcommon.app import create_app

from . import models  # noqa: F401  (register tables before create_all)
from .api import router

app = create_app("orders", [router])
