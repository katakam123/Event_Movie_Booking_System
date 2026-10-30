
from datetime import datetime

from pydantic import BaseModel, Field


class TicketScanRequest(BaseModel):
    qr_data: str = Field(min_length=1, max_length=500)


class TicketScanResponse(BaseModel):
    success: bool
    message: str
    booking_number: str
    customer_name: str
    seats: list[str]
    seat_count: int
    checked_in_at: datetime


class ShowEntriesResponse(BaseModel):
    show_id: int
    total_bookings: int
    entered_bookings: int
    pending_entries: int
    total_customers: int
