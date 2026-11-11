"""
Pydantic request & response schemas for FastAPI validation and Swagger UI docs.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150, examples=["Aarav Sharma"])
    email: str = Field(..., min_length=5, max_length=255, examples=["aarav.sharma@example.com"])
    phone: Optional[str] = Field(None, max_length=50, examples=["+91-9876543210"])
    city: Optional[str] = Field(None, max_length=120, examples=["Bengaluru"])
    segment: Literal["budget", "regular", "premium", "vip"] = "regular"


class OrderLineCreate(BaseModel):
    sku: str = Field(..., min_length=2, max_length=64, examples=["SKU-ELEC-101"])
    product_name: str = Field(..., min_length=2, max_length=200, examples=["Wireless Mouse"])
    category: str = Field("General", max_length=80, examples=["Electronics"])
    quantity: int = Field(..., gt=0, examples=[2])
    unit_price: float = Field(..., ge=0, examples=[49.99])
    discount_amount: float = Field(0.0, ge=0, examples=[5.00])
    is_points_eligible: bool = True


class OrderCreate(BaseModel):
    customer_id: str = Field(..., examples=["CUST-000001"])
    order_date: Optional[str] = Field(None, examples=["2026-11-11T10:30:00"])
    shipping_amount: float = Field(0.0, ge=0, examples=[0.0])
    tax_rate: float = Field(0.08, ge=0, le=0.5, examples=[0.08])
    auto_accrue: bool = Field(
        True,
        description="Automatically accrue loyalty points for this order upon creation.",
    )
    lines: list[OrderLineCreate] = Field(..., min_length=1)


class AccrueRequest(BaseModel):
    order_id: str = Field(..., examples=["ORD-2026-000001"])
    idempotency_key: Optional[str] = Field(None, examples=["ACCRUAL:ORD-2026-000001"])


class RedeemPointsRequest(BaseModel):
    account_id: str = Field(..., examples=["LOY-CUST-000001"])
    reward_id: Optional[str] = Field(None, examples=["REW-0001"])
    points: Optional[int] = Field(None, gt=0, examples=[500])
    quantity: int = Field(1, gt=0, examples=[1])
    idempotency_key: Optional[str] = Field(None, examples=["RDM-REQ-001"])


class RedemptionCreateRequest(BaseModel):
    account_id: str = Field(..., examples=["LOY-CUST-000001"])
    reward_id: str = Field(..., examples=["REW-0001"])
    quantity: int = Field(1, gt=0, examples=[1])
    idempotency_key: Optional[str] = Field(None, examples=["RDM-WEB-001"])


class ReversePointsRequest(BaseModel):
    order_id: str = Field(..., examples=["ORD-2026-000001"])
    return_amount: Optional[float] = Field(None, gt=0, examples=[45.00])
    order_line_id: Optional[str] = Field(None, examples=["ORL-2026-0000001"])
    return_quantity: Optional[int] = Field(None, gt=0, examples=[1])
    reason: str = Field("Customer product return", max_length=255)
    idempotency_key: Optional[str] = Field(None, examples=["REV-REQ-001"])


class ExpirePointsRequest(BaseModel):
    as_of_date: Optional[str] = Field(None, examples=["2026-11-11T23:59:59"])
    account_id: Optional[str] = Field(None, examples=["LOY-CUST-000001"])

