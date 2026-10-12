"""Payment gateway abstraction.

* MockProvider  - offline gateway for local dev, CI and demos. Uses Stripe-style
                  test card numbers so the UX matches the real thing.
* StripeProvider - real PaymentIntents. Card data never touches our servers:
                  the browser confirms the intent with Stripe.js using the
                  client_secret, and Stripe tells us the outcome via webhook.

This module has no web-framework imports so it is easy to unit test.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol


class Status:
    REQUIRES_PAYMENT = "requires_payment"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class IntentResult:
    provider_ref: str
    status: str
    client_secret: str | None = None


@dataclass(frozen=True)
class ChargeOutcome:
    status: str
    failure_reason: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    provider_ref: str
    status: str
    failure_reason: str | None = None


class WebhookError(Exception):
    pass


class PaymentProvider(Protocol):
    name: str
    publishable_key: str | None

    def create_intent(
        self, *, amount_pence: int, currency: str, metadata: dict, idempotency_key: str
    ) -> IntentResult: ...

    def parse_webhook(self, payload: bytes, signature: str | None) -> WebhookEvent | None: ...


def luhn_valid(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 12 or len(digits) != len([c for c in number if not c.isspace()]):
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class MockProvider:
    """Deterministic fake gateway.

    4242 4242 4242 4242  -> succeeds
    4000 0000 0000 0002  -> card_declined
    4000 0000 0000 9995  -> insufficient_funds
    anything failing Luhn -> invalid_number
    """

    name = "mock"
    publishable_key = None

    DECLINES = {
        "4000000000000002": "card_declined",
        "4000000000009995": "insufficient_funds",
    }

    def create_intent(self, *, amount_pence, currency, metadata, idempotency_key):
        return IntentResult(
            provider_ref=f"mock_pi_{secrets.token_hex(8)}",
            status=Status.REQUIRES_PAYMENT,
        )

    def charge(self, card_number: str) -> ChargeOutcome:
        number = card_number.replace(" ", "").replace("-", "")
        if not luhn_valid(number):
            return ChargeOutcome(Status.FAILED, "invalid_number")
        if number in self.DECLINES:
            return ChargeOutcome(Status.FAILED, self.DECLINES[number])
        return ChargeOutcome(Status.SUCCEEDED)

    def parse_webhook(self, payload, signature):
        return None


class StripeProvider:
    name = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str, publishable_key: str) -> None:
        import stripe  # imported lazily so the mock path has no hard dependency

        self._stripe = stripe
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self.publishable_key = publishable_key

    def create_intent(self, *, amount_pence, currency, metadata, idempotency_key):
        intent = self._stripe.PaymentIntent.create(
            api_key=self._secret_key,
            idempotency_key=idempotency_key,
            amount=amount_pence,
            currency=currency.lower(),
            metadata={k: str(v) for k, v in metadata.items()},
            automatic_payment_methods={"enabled": True},
        )
        return IntentResult(
            provider_ref=intent.id,
            status=Status.REQUIRES_PAYMENT,
            client_secret=intent.client_secret,
        )

    def parse_webhook(self, payload, signature):
        if not signature:
            raise WebhookError("missing Stripe-Signature header")
        try:
            event = self._stripe.Webhook.construct_event(
                payload, signature, self._webhook_secret
            )
        except (ValueError, self._stripe.SignatureVerificationError) as exc:
            raise WebhookError(str(exc)) from exc

        obj = event["data"]["object"]
        if event["type"] == "payment_intent.succeeded":
            return WebhookEvent(obj["id"], Status.SUCCEEDED)
        if event["type"] == "payment_intent.payment_failed":
            err = obj.get("last_payment_error") or {}
            return WebhookEvent(obj["id"], Status.FAILED, err.get("code") or "payment_failed")
        return None  # ignore events we don't handle


def build_provider(name: str, *, secret_key: str = "", webhook_secret: str = "",
                   publishable_key: str = "") -> PaymentProvider:
    if name == "mock":
        return MockProvider()
    if name == "stripe":
        missing = [k for k, v in {
            "STRIPE_SECRET_KEY": secret_key,
            "STRIPE_WEBHOOK_SECRET": webhook_secret,
            "STRIPE_PUBLISHABLE_KEY": publishable_key,
        }.items() if not v]
        if missing:
            raise RuntimeError(f"PAYMENT_PROVIDER=stripe needs {', '.join(missing)}")
        return StripeProvider(secret_key, webhook_secret, publishable_key)
    raise RuntimeError(f"Unknown PAYMENT_PROVIDER {name!r}")
