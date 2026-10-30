
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, String, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin



class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        Enum(
            "admin",
            "organizer",
            "customer",
            "gate_staff",
            name="user_role",
        ),
        default="customer",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Events created by this user when they are an organizer.
    organized_events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="organizer",
        foreign_keys="Event.organizer_id",
    )

    # Bookings created by this user when they are a customer.
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking",
        back_populates="customer",
        foreign_keys="Booking.customer_id",
    )

    # Waitlist entries created by this user.
    waitlist_entries: Mapped[list["WaitlistEntry"]] = relationship(
        "WaitlistEntry",
        back_populates="customer",
    )
    is_approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    assigned_venue_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )