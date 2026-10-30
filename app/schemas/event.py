
from datetime import date, time, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EventCategory = Literal[
    "Movie", "Concert", "Comedy", "Sports", "Workshop"
]
AgeRating = Literal["U", "UA", "A"]
ShowStatus = Literal["Scheduled", "Cancelled", "Completed"]


class EventCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    category: EventCategory = "Movie"
    language: str = Field(min_length=2, max_length=50)
    description: str = Field(min_length=1, max_length=5000)
    duration_minutes: int = Field(gt=0, le=600)
    age_rating: AgeRating = "U"


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    category: EventCategory | None = None
    language: str | None = Field(default=None, min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    duration_minutes: int | None = Field(default=None, gt=0, le=600)
    age_rating: AgeRating | None = None
    status: Literal["Draft", "Published"] | None = None


class EventResponse(BaseModel):
    id: int
    organizer_id: int
    title: str
    category: str
    language: str
    description: str
    duration_minutes: int
    age_rating: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class SeatCategoryPriceInput(BaseModel):
    category: Literal["Silver", "Gold", "Recliner"]
    price: float = Field(gt=0, le=100000)


class ShowCreate(BaseModel):
    screen_id: int
    show_date: date
    start_time: time
    prices: list[SeatCategoryPriceInput] = Field(min_length=1)


class ShowUpdate(BaseModel):
    show_date: date | None = None
    start_time: time | None = None
    status: ShowStatus | None = None
    prices: list[SeatCategoryPriceInput] | None = None


class ShowResponse(BaseModel):
    id: int
    event_id: int
    screen_id: int
    starts_at: datetime
    ends_at: datetime
    booking_closes_at: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class ShowWithPrices(ShowResponse):
    prices: list[SeatCategoryPriceInput]
