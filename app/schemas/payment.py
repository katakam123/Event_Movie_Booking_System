
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PaymentCreate(BaseModel):
    payment_method: Literal["UPI", "Card", "Net Banking"]


class RazorpayOrderResponse(BaseModel):
    booking_id: int
    booking_reference: str
    razorpay_order_id: str
    amount: int
    currency: str
    razorpay_key_id: str


class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    payment_method: Literal["UPI", "Card", "Net Banking"]


class PaymentResponse(BaseModel):
    id: int
    booking_id: int
    transaction_id: str
    amount: Decimal
    payment_method: str
    status: Literal["Pending", "Success", "Failed", "Refunded"]
    paid_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
