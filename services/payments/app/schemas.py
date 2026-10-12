from pydantic import BaseModel, ConfigDict, Field


class CreatePayment(BaseModel):
    order_id: int
    user_id: int
    amount_pence: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: int
    amount_pence: int
    currency: str
    provider: str
    status: str
    failure_reason: str | None = None
    client_secret: str | None = None
    publishable_key: str | None = None


class MockConfirm(BaseModel):
    # Only used by the mock gateway. With Stripe, card data goes straight
    # from the browser to Stripe and never reaches this service.
    card_number: str = Field(min_length=12, max_length=23)


class ProviderConfig(BaseModel):
    provider: str
    publishable_key: str | None = None
