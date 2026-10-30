
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["customer", "organizer"] = "customer"


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool
    is_approved: bool
    assigned_venue_id: int | None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
