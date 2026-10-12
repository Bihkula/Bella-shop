import pytest

from app.providers import MockProvider, Status, build_provider, luhn_valid


@pytest.mark.parametrize(
    "number,ok",
    [
        ("4242424242424242", True),
        ("4242 4242 4242 4242", True),
        ("4000000000000002", True),
        ("4242424242424241", False),
        ("1234", False),
        ("4242abcd42424242", False),
    ],
)
def test_luhn(number, ok):
    assert luhn_valid(number) is ok


def test_mock_outcomes():
    m = MockProvider()
    assert m.charge("4242 4242 4242 4242").status == Status.SUCCEEDED
    declined = m.charge("4000000000000002")
    assert (declined.status, declined.failure_reason) == (Status.FAILED, "card_declined")
    assert m.charge("4000000000009995").failure_reason == "insufficient_funds"
    assert m.charge("4242424242424241").failure_reason == "invalid_number"


def test_mock_intent_refs_are_unique():
    m = MockProvider()
    a = m.create_intent(amount_pence=1, currency="GBP", metadata={}, idempotency_key="a")
    b = m.create_intent(amount_pence=1, currency="GBP", metadata={}, idempotency_key="b")
    assert a.provider_ref != b.provider_ref
    assert a.status == Status.REQUIRES_PAYMENT


def test_build_provider_validation():
    assert build_provider("mock").name == "mock"
    with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
        build_provider("stripe")
    with pytest.raises(RuntimeError, match="Unknown"):
        build_provider("paypal")
