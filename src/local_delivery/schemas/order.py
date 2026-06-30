"""Order schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrderItemRequest(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    dc_id: str
    items: list[OrderItemRequest]
    delivery_address: str
    order_id: UUID


class OrderLineItemResponse(BaseModel):
    product_id: UUID
    name: str
    quantity: int
    unit_price_cents: int


class OrderResponse(BaseModel):
    order_id: UUID
    status: str
    items: list[OrderLineItemResponse]
    total_amount_cents: int
    delivery_address: str
    created_at: datetime
    updated_at: datetime


class AdvanceStatusRequest(BaseModel):
    status: str


class CancelResponse(BaseModel):
    order_id: UUID
    status: str
    updated_at: datetime


class SweepResponse(BaseModel):
    orders_cancelled: int
    message: str
