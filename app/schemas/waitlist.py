from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WaitlistCreate(BaseModel):
    seat_count: int = Field(gt=0, le=10)
    preferred_category: str | None = None


class WaitlistResponse(BaseModel):
    id: int
    show_id: int
    customer_id: int
    seat_count: int
    preferred_category: str | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)