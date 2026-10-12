import logging

from sqlalchemy import func, select

from shopcommon.app import create_app
from shopcommon.config import env
from shopcommon.db import session_scope

from .api import router
from .models import Product

log = logging.getLogger(__name__)

SAMPLE_PRODUCTS = [
    ("MUG-001", "Enamel Camp Mug", "Speckled enamel, 350ml.", 1200, 40),
    ("TEE-001", "Organic Cotton Tee", "Heavyweight, garment-dyed.", 2500, 60),
    ("BAG-001", "Waxed Canvas Tote", "Brass rivets, leather handles.", 4800, 25),
    ("NB-001", "Dot-Grid Notebook", "A5, 192 pages, lay-flat binding.", 1450, 80),
    ("CAP-001", "Six-Panel Cap", "Washed cotton twill.", 2200, 30),
    ("SOCK-001", "Merino Hiking Socks", "Cushioned sole, pair.", 1600, 100),
]


def seed_catalogue() -> None:
    if (env("SEED_SAMPLE_DATA", "true") or "").lower() != "true":
        return
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(Product)):
            return
        for sku, name, desc, price, stock in SAMPLE_PRODUCTS:
            db.add(Product(sku=sku, name=name, description=desc, price_pence=price, stock=stock,
                           active=True))
        db.commit()
        log.info("seeded %d sample products", len(SAMPLE_PRODUCTS))


app = create_app("products", [router], on_startup=seed_catalogue)
