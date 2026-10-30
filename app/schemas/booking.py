
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BookingCreate(BaseModel):
    show_id: int = Field(gt=0)
    seat_ids: list[int] = Field(min_length=1, max_length=10)


class BookedSeatResponse(BaseModel):
    seat_id: int
    price: Decimal
    status: str

    model_config = ConfigDict(from_attributes=True)


class BookingResponse(BaseModel):
    id: int
    booking_number: str | None
    customer_id: int
    show_id: int
    seat_count: int
    ticket_total: Decimal
    convenience_fee: Decimal
    gst_amount: Decimal
    grand_total: Decimal
    currency: str
    status: Literal[
        "Pending Payment", "Confirmed", "Cancelled", "Expired"
    ]
    expires_at: datetime
    confirmed_at: datetime | None
    booked_seats: list[BookedSeatResponse]

    model_config = ConfigDict(from_attributes=True)
