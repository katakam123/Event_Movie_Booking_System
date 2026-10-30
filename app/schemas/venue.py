
from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_CATEGORIES = {"Silver", "Gold", "Recliner"}


class VenueCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    city: str = Field(min_length=2, max_length=100)
    address: str = Field(min_length=3, max_length=255)
    is_active: bool = True


class VenueUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    city: str | None = Field(default=None, min_length=2, max_length=100)
    address: str | None = Field(default=None, min_length=3, max_length=255)
    is_active: bool | None = None


class VenueResponse(VenueCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class ScreenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ScreenResponse(BaseModel):
    id: int
    venue_id: int
    name: str
    total_seats: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class BulkSeatCreate(BaseModel):
    rows: list[str] = Field(min_length=1, max_length=30)
    seats_per_row: int = Field(ge=1, le=100)
    category: str = "Silver"

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in ALLOWED_CATEGORIES:
            raise ValueError(
                "Category must be Silver, Gold, or Recliner"
            )
        return value

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, rows: list[str]) -> list[str]:
        normalized = [row.strip().upper() for row in rows]

        if any(
            not row or len(row) > 5
            for row in normalized
        ):
            raise ValueError("Each row label must contain 1-5 characters")

        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate row labels are not allowed")

        return normalized


class SeatStatusUpdate(BaseModel):
    is_active: bool


class SeatResponse(BaseModel):
    id: int
    screen_id: int
    row_label: str
    seat_number: int
    category: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SeatRowResponse(BaseModel):
    row_label: str
    seats: list[SeatResponse]


class ScreenLayoutResponse(BaseModel):
    screen_id: int
    screen_name: str
    venue_id: int
    total_seats: int
    available_seats: int
    rows: list[SeatRowResponse]
