from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RefundResponse(BaseModel):
    id: int
    booking_id: int
    payment_id: int
    amount: Decimal
    status: str
    reason: str | None
    refunded_at: datetime | None

    model_config = ConfigDict(from_attributes=True)