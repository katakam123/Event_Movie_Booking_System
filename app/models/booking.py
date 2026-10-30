
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    booking_number: Mapped[str | None] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=True,
    )

    booking_reference: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    show_id: Mapped[int] = mapped_column(
        ForeignKey("shows.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    seat_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    ticket_total: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    convenience_fee: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    gst_amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    grand_total: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    total_amount: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Pending Payment",
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    customer = relationship(
        "User",
        back_populates="bookings",
    )

    show = relationship(
        "Show",
        back_populates="bookings",
    )

    booked_seats = relationship(
        "BookedSeat",
        back_populates="booking",
        cascade="all, delete-orphan",
    )

    payments = relationship(
        "Payment",
        back_populates="booking",
    )

    refunds = relationship(
        "Refund",
        back_populates="booking",
    )


class BookedSeat(TimestampMixin, Base):
    __tablename__ = "booked_seats"

    __table_args__ = (
        UniqueConstraint(
            "show_id",
            "confirmed_seat_id",
            name="uq_confirmed_seat_per_show",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    show_id: Mapped[int] = mapped_column(
        ForeignKey("shows.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    seat_id: Mapped[int] = mapped_column(
        ForeignKey("seats.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="reserved",
    )

    ticket_token: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    checked_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    confirmed_seat_id: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN is_confirmed = 1 THEN seat_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )

    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    booking = relationship(
        "Booking",
        back_populates="booked_seats",
    )

    seat = relationship(
        "Seat",
        back_populates="booked_seats",
    )
