
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class SeatLockRequest(BaseModel):
    seat_ids: list[int] = Field(min_length=1, max_length=10)


class SeatLockResponse(BaseModel):
    show_id: int
    seat_ids: list[int]
    locked: bool
    lock_expires_at: datetime
    message: str


class ReleaseSeatLocksRequest(BaseModel):
    seat_ids: list[int] = Field(min_length=1, max_length=10)


class ShowSeatResponse(BaseModel):
    seat_id: int
    row_label: str
    seat_number: int
    category: str
    price: float | None
    status: str


class ShowSeatsResponse(BaseModel):
    show_id: int
    show_status: str
    seats: list[ShowSeatResponse]
