
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
import re


class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: str = "customer"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        allowed_roles = {"customer", "organizer"}
        value = value.lower().strip()
        if value not in allowed_roles:
            raise ValueError("Public registration allows only customer or organizer")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool
    is_approved: bool
    assigned_venue_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        if value is not None and not re.fullmatch(r"[0-9]{10}", value):
            raise ValueError("Phone number must contain exactly 10 digits")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
