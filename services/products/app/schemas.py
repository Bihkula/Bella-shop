from pydantic import BaseModel, ConfigDict, Field


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    price_pence: int = Field(ge=0)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    stock: int = Field(default=0, ge=0)
    image_url: str = ""


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_pence: int | None = Field(default=None, ge=0)
    stock: int | None = Field(default=None, ge=0)
    image_url: str | None = None
    active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: str
    price_pence: int
    currency: str
    stock: int
    image_url: str
    active: bool


class LineItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=100)


class ReserveRequest(BaseModel):
    items: list[LineItem] = Field(min_length=1, max_length=50)


class ReservedLine(BaseModel):
    product_id: int
    name: str
    quantity: int
    unit_price_pence: int
    currency: str


class ReserveResponse(BaseModel):
    lines: list[ReservedLine]
