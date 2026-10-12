import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from shopcommon.auth import get_current_user, require_internal
from shopcommon.db import get_db
from shopcommon.http_client import UpstreamError
from shopcommon.security import Principal

from .deps import OrdersNotifier, get_notifier, get_provider
from .models import Payment
from .providers import MockProvider, PaymentProvider, Status, WebhookError
from .schemas import CreatePayment, MockConfirm, PaymentOut, ProviderConfig

log = logging.getLogger(__name__)
router = APIRouter()

PAYMENTS = Counter("shop_payments_total", "Payment outcomes", ["provider", "status"])
PAYMENT_VOLUME = Counter(
    "shop_payment_amount_pence_total", "Value of successful payments", ["currency"]
)
NOTIFY_FAILURES = Counter("shop_payment_notify_failures_total", "Failed order callbacks")

ORDER_STATUS = {Status.SUCCEEDED: "PAID", Status.FAILED: "PAYMENT_FAILED"}


def _out(p: Payment, provider: PaymentProvider) -> PaymentOut:
    out = PaymentOut.model_validate(p)
    out.publishable_key = provider.publishable_key
    return out


def _settle(db: Session, payment: Payment, new_status: str, reason: str | None,
            notifier: OrdersNotifier) -> bool:
    """Record the final outcome and tell the orders service. Returns True if
    the order service acknowledged."""
    if payment.status != new_status:
        payment.status = new_status
        payment.failure_reason = reason
        PAYMENTS.labels(payment.provider, new_status).inc()
        if new_status == Status.SUCCEEDED:
            PAYMENT_VOLUME.labels(payment.currency).inc(payment.amount_pence)
    try:
        notifier.notify(payment.order_id, ORDER_STATUS[new_status], payment.id)
        payment.order_notified = True
    except UpstreamError as exc:
        NOTIFY_FAILURES.inc()
        log.error("could not notify orders for payment %s: %s", payment.id, exc)
        payment.order_notified = False
    db.commit()
    return payment.order_notified


@router.get("/payments/config", response_model=ProviderConfig)
def provider_config(provider: PaymentProvider = Depends(get_provider)):
    return ProviderConfig(provider=provider.name, publishable_key=provider.publishable_key)


@router.post(
    "/internal/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal)],
)
def create_payment(
    body: CreatePayment,
    db: Session = Depends(get_db),
    provider: PaymentProvider = Depends(get_provider),
):
    # Reuse an open attempt so double-clicking "Pay" never creates two charges.
    existing = db.scalar(
        select(Payment).where(
            Payment.order_id == body.order_id,
            Payment.status.in_([Status.REQUIRES_PAYMENT, Status.SUCCEEDED]),
        )
    )
    if existing:
        if existing.status == Status.SUCCEEDED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Order already paid")
        return _out(existing, provider)

    payment_id = f"pay_{secrets.token_hex(12)}"
    intent = provider.create_intent(
        amount_pence=body.amount_pence,
        currency=body.currency,
        metadata={"order_id": body.order_id, "payment_id": payment_id},
        idempotency_key=payment_id,
    )
    payment = Payment(
        id=payment_id,
        order_id=body.order_id,
        user_id=body.user_id,
        amount_pence=body.amount_pence,
        currency=body.currency.upper(),
        provider=provider.name,
        provider_ref=intent.provider_ref,
        client_secret=intent.client_secret,
        status=intent.status,
    )
    db.add(payment)
    db.commit()
    PAYMENTS.labels(provider.name, "created").inc()
    return _out(payment, provider)


def _owned(db: Session, payment_id: str, user: Principal) -> Payment:
    p = db.get(Payment, payment_id)
    if not p or (p.user_id != user.user_id and not user.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return p


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(
    payment_id: str,
    user: Principal = Depends(get_current_user),
    db: Session = Depends(get_db),
    provider: PaymentProvider = Depends(get_provider),
):
    return _out(_owned(db, payment_id, user), provider)


@router.post("/payments/{payment_id}/confirm", response_model=PaymentOut)
def confirm_mock_payment(
    payment_id: str,
    body: MockConfirm,
    user: Principal = Depends(get_current_user),
    db: Session = Depends(get_db),
    provider: PaymentProvider = Depends(get_provider),
    notifier: OrdersNotifier = Depends(get_notifier),
):
    if not isinstance(provider, MockProvider):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Confirm with Stripe.js; this endpoint is mock-only"
        )
    payment = _owned(db, payment_id, user)
    if payment.status != Status.REQUIRES_PAYMENT:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Payment is {payment.status}")
    outcome = provider.charge(body.card_number)
    _settle(db, payment, outcome.status, outcome.failure_reason, notifier)
    return _out(payment, provider)


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
    provider: PaymentProvider = Depends(get_provider),
    notifier: OrdersNotifier = Depends(get_notifier),
):
    # Signature verification needs the raw body, which is only available async.
    # The rest (DB + HTTP callback with retries) is blocking, so run it in the
    # threadpool rather than stalling the event loop.
    payload = await request.body()
    return await run_in_threadpool(
        _handle_stripe_event, payload, stripe_signature, db, provider, notifier
    )


def _handle_stripe_event(
    payload: bytes,
    stripe_signature: str | None,
    db: Session,
    provider: PaymentProvider,
    notifier: OrdersNotifier,
) -> dict:
    try:
        event = provider.parse_webhook(payload, stripe_signature)
    except WebhookError as exc:
        log.warning("rejected webhook: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature") from exc
    if event is None:
        return {"received": True}

    payment = db.scalar(select(Payment).where(Payment.provider_ref == event.provider_ref))
    if not payment:
        log.warning("webhook for unknown intent %s", event.provider_ref)
        return {"received": True}
    if payment.status == event.status and payment.order_notified:
        return {"received": True}  # duplicate delivery

    if not _settle(db, payment, event.status, event.failure_reason, notifier):
        # Non-2xx makes Stripe retry delivery with backoff.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Order service unavailable")
    return {"received": True}
