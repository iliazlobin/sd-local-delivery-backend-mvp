"""Catalog schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CatalogItem(BaseModel):
    product_id: str
    name: str
    brand: str
    category: str
    unit_price_cents: int
    available_qty: int
    available: bool


class CatalogPage(BaseModel):
    items: list[CatalogItem]
    page: int
    page_size: int
    total: int


class CatalogQuery(BaseModel):
    dc_id: str
    category: str | None = None
    q: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=100)
