from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prometheus_client import Counter
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shopcommon.auth import require_admin, require_internal
from shopcommon.db import get_db

from .models import Product
from .schemas import (
    ProductIn,
    ProductOut,
    ProductUpdate,
    ReservedLine,
    ReserveRequest,
    ReserveResponse,
)

router = APIRouter()
STOCK_EVENTS = Counter("shop_stock_events_total", "Stock reservations/releases", ["event"])


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Product).where(Product.active.is_(True))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    return db.scalars(stmt.order_by(Product.id).limit(limit).offset(offset)).all()


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product or not product.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_product(body: ProductIn, db: Session = Depends(get_db)):
    product = Product(**body.model_dump(), active=True)
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "SKU already exists") from None
    return product


@router.patch(
    "/products/{product_id}",
    response_model=ProductOut,
    dependencies=[Depends(require_admin)],
)
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    return product


def _merge(items) -> dict[int, int]:
    qty: dict[int, int] = defaultdict(int)
    for item in items:
        qty[item.product_id] += item.quantity
    return dict(qty)


@router.post(
    "/internal/reserve",
    response_model=ReserveResponse,
    dependencies=[Depends(require_internal)],
)
def reserve(body: ReserveRequest, db: Session = Depends(get_db)):
    """Atomically decrement stock for every line, or none of them.

    The conditional UPDATE (stock >= qty) makes concurrent checkouts safe
    without a read-then-write race."""
    wanted = _merge(body.items)
    lines: list[ReservedLine] = []
    for product_id, qty in sorted(wanted.items()):  # stable order avoids deadlocks
        result = db.execute(
            update(Product)
            .where(Product.id == product_id, Product.active.is_(True), Product.stock >= qty)
            .values(stock=Product.stock - qty)
        )
        if result.rowcount != 1:
            db.rollback()
            STOCK_EVENTS.labels("reserve_rejected").inc()
            exists = db.get(Product, product_id)
            if not exists or not exists.active:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {product_id} not found")
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Insufficient stock for product {product_id}"
            )
        p = db.get(Product, product_id)
        lines.append(
            ReservedLine(
                product_id=p.id,
                name=p.name,
                quantity=qty,
                unit_price_pence=p.price_pence,
                currency=p.currency,
            )
        )
    db.commit()
    STOCK_EVENTS.labels("reserved").inc()
    return ReserveResponse(lines=lines)


@router.post(
    "/internal/release",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def release(body: ReserveRequest, db: Session = Depends(get_db)):
    for product_id, qty in _merge(body.items).items():
        db.execute(
            update(Product).where(Product.id == product_id).values(stock=Product.stock + qty)
        )
    db.commit()
    STOCK_EVENTS.labels("released").inc()
