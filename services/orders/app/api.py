import logging

from fastapi import APIRouter, Depends, HTTPException, status
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session

from shopcommon.auth import get_current_user, require_internal
from shopcommon.db import get_db
from shopcommon.http_client import UpstreamError
from shopcommon.security import Principal

from .clients import PaymentsClient, ProductsClient, get_payments_client, get_products_client
from .models import Order, OrderLine, OrderStatus
from .schemas import CheckoutOut, CreateOrder, OrderOut, StatusUpdate

log = logging.getLogger(__name__)
router = APIRouter()

ORDERS = Counter("shop_orders_total", "Order lifecycle events", ["event"])
REVENUE = Counter("shop_revenue_pence_total", "Revenue from paid orders (pence)", ["currency"])


def _upstream(exc: UpstreamError) -> HTTPException:
    # Pass through client errors (e.g. out of stock); mask server errors.
    if 400 <= exc.status_code < 500:
        return HTTPException(exc.status_code, exc.detail)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Dependency unavailable")


def _owned_order(db: Session, order_id: int, user: Principal) -> Order:
    order = db.get(Order, order_id)
    # 404 rather than 403 so we don't reveal other users' order ids.
    if not order or (order.user_id != user.user_id and not user.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


def _lines_payload(order: Order) -> list[dict]:
    return [{"product_id": ln.product_id, "quantity": ln.quantity} for ln in order.lines]


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: CreateOrder,
    user: Principal = Depends(get_current_user),
    db: Session = Depends(get_db),
    products: ProductsClient = Depends(get_products_client),
):
    items = [i.model_dump() for i in body.items]
    try:
        reserved = products.reserve(items)
    except UpstreamError as exc:
        ORDERS.labels("rejected").inc()
        raise _upstream(exc) from exc

    currencies = {ln["currency"] for ln in reserved}
    if len(currencies) != 1:
        products.release(items)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mixed currencies in one order")

    order = Order(
        user_id=user.user_id,
        status=OrderStatus.PENDING_PAYMENT,
        currency=currencies.pop(),
        total_pence=sum(ln["unit_price_pence"] * ln["quantity"] for ln in reserved),
        lines=[
            OrderLine(
                product_id=ln["product_id"],
                name=ln["name"],
                quantity=ln["quantity"],
                unit_price_pence=ln["unit_price_pence"],
            )
            for ln in reserved
        ],
    )
    db.add(order)
    try:
        db.commit()
    except Exception:
        db.rollback()
        products.release(items)  # compensate: give the stock back
        raise
    ORDERS.labels("created").inc()
    return order


@router.get("/orders", response_model=list[OrderOut])
def list_orders(user: Principal = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Order).where(Order.user_id == user.user_id).order_by(Order.id.desc())
    return db.scalars(stmt.limit(100)).all()


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int, user: Principal = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _owned_order(db, order_id, user)


@router.post("/orders/{order_id}/checkout", response_model=CheckoutOut)
def checkout(
    order_id: int,
    user: Principal = Depends(get_current_user),
    db: Session = Depends(get_db),
    payments: PaymentsClient = Depends(get_payments_client),
):
    order = _owned_order(db, order_id, user)
    if order.status not in (OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order is {order.status}")
    try:
        payment = payments.create_payment(
            order_id=order.id,
            user_id=order.user_id,
            amount_pence=order.total_pence,
            currency=order.currency,
        )
    except UpstreamError as exc:
        raise _upstream(exc) from exc

    order.payment_id = payment["id"]
    db.commit()
    ORDERS.labels("checkout_started").inc()
    return CheckoutOut(
        order_id=order.id,
        payment_id=payment["id"],
        provider=payment["provider"],
        status=payment["status"],
        client_secret=payment.get("client_secret"),
        publishable_key=payment.get("publishable_key"),
    )


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel(
    order_id: int,
    user: Principal = Depends(get_current_user),
    db: Session = Depends(get_db),
    products: ProductsClient = Depends(get_products_client),
):
    order = _owned_order(db, order_id, user)
    if not OrderStatus.can_move(order.status, OrderStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order is {order.status}")
    order.status = OrderStatus.CANCELLED
    db.commit()
    products.release(_lines_payload(order))
    ORDERS.labels("cancelled").inc()
    return order


@router.post(
    "/internal/orders/{order_id}/status",
    response_model=OrderOut,
    dependencies=[Depends(require_internal)],
)
def payment_status_callback(order_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    """Called by the payments service when a payment settles."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.status == body.status:
        return order  # idempotent: webhooks can be delivered more than once
    if not OrderStatus.can_move(order.status, body.status):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Cannot move {order.status} -> {body.status}"
        )
    order.status = body.status
    order.payment_id = body.payment_id
    db.commit()
    if body.status == OrderStatus.PAID:
        ORDERS.labels("paid").inc()
        REVENUE.labels(order.currency).inc(order.total_pence)
    elif body.status == OrderStatus.PAYMENT_FAILED:
        ORDERS.labels("payment_failed").inc()
    log.info("order %s -> %s", order.id, order.status)
    return order
