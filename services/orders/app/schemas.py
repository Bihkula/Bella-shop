from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LineItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=100)


class CreateOrder(BaseModel):
    items: list[LineItem] = Field(min_length=1, max_length=50)


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    name: str
    quantity: int
    unit_price_pence: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    total_pence: int
    currency: str
    payment_id: str | None
    created_at: datetime
    lines: list[OrderLineOut]


class CheckoutOut(BaseModel):
    order_id: int
    payment_id: str
    provider: str
    status: str
    client_secret: str | None = None
    publishable_key: str | None = None


class StatusUpdate(BaseModel):
    status: str
    payment_id: str
