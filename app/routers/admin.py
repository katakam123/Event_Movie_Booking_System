
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.venue import Venue
from app.auth.security import get_current_user, hash_password
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


class StaffCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    venue_id: int


class StaffResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_active: bool
    is_approved: bool
    assigned_venue_id: int

    model_config = ConfigDict(from_attributes=True)


@router.put(
    "/organizers/{user_id}/approve",
    response_model=UserResponse,
)
def approve_organizer(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    organizer = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if organizer is None or organizer.role != "organizer":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organizer not found",
        )

    organizer.is_approved = True
    db.commit()
    db.refresh(organizer)

    return organizer


@router.post(
    "/staff",
    response_model=StaffResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_staff(
    data: StaffCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    existing_user = (
        db.query(User)
        .filter(User.email == data.email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    venue = (
        db.query(Venue)
        .filter(Venue.id == data.venue_id)
        .first()
    )

    if venue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Venue not found",
        )

    staff = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role="gate_staff",
        is_active=True,
        is_approved=True,
        assigned_venue_id=venue.id,
    )

    db.add(staff)

    try:
        db.commit()
        db.refresh(staff)
    except Exception:
        db.rollback()
        raise

    return staff
