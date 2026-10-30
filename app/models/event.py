
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    organizer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(30),
        default="movie",
        nullable=False,
    )

    language: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )

    duration_minutes: Mapped[Optional[int]] = mapped_column(
        nullable=True,
    )

    poster_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    category: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Movie",
        server_default="Movie",
    )

    age_rating: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="U",
        server_default="U",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Draft",
        server_default="Draft",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    organizer: Mapped["User"] = relationship(
        "User",
        back_populates="organized_events",
        foreign_keys=[organizer_id],
    )

    shows: Mapped[list["Show"]] = relationship(
        "Show",
        back_populates="event",
    )


class Show(TimestampMixin, Base):
    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    screen_id: Mapped[int] = mapped_column(
        ForeignKey("screens.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    starts_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    ends_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    booking_closes_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Scheduled",
        server_default="Scheduled",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    event: Mapped["Event"] = relationship(
        "Event",
        back_populates="shows",
    )

    screen: Mapped["Screen"] = relationship(
        "Screen",
        back_populates="shows",
    )

    seat_category_prices: Mapped[list["SeatCategoryPrice"]] = relationship(
        "SeatCategoryPrice",
        back_populates="show",
        cascade="all, delete-orphan",
    )

    bookings: Mapped[list["Booking"]] = relationship(
        "Booking",
        back_populates="show",
    )

    waitlist_entries: Mapped[list["WaitlistEntry"]] = relationship(
        "WaitlistEntry",
        back_populates="show",
    )


class SeatCategoryPrice(TimestampMixin, Base):
    __tablename__ = "seat_category_prices"

    __table_args__ = (
        UniqueConstraint(
            "show_id",
            "category",
            name="uq_show_seat_category",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    show_id: Mapped[int] = mapped_column(
        ForeignKey("shows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    show: Mapped["Show"] = relationship(
        "Show",
        back_populates="seat_category_prices",
    )
