
from typing import Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class Venue(TimestampMixin, Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    address: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    city: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    state: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    country: Mapped[str] = mapped_column(
        String(100),
        default="India",
        nullable=False,
    )

    postal_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    screens: Mapped[list["Screen"]] = relationship(
        "Screen",
        back_populates="venue",
        cascade="all, delete-orphan",
    )


class Screen(TimestampMixin, Base):
    __tablename__ = "screens"

    __table_args__ = (
        UniqueConstraint(
            "venue_id",
            "name",
            name="uq_screen_venue_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    venue_id: Mapped[int] = mapped_column(
        ForeignKey("venues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    total_rows: Mapped[int] = mapped_column(
        Integer,
        default=10,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    venue: Mapped["Venue"] = relationship(
        "Venue",
        back_populates="screens",
    )

    seats: Mapped[list["Seat"]] = relationship(
        "Seat",
        back_populates="screen",
        cascade="all, delete-orphan",
    )

    shows: Mapped[list["Show"]] = relationship(
        "Show",
        back_populates="screen",
    )


class Seat(TimestampMixin, Base):
    __tablename__ = "seats"

    __table_args__ = (
        UniqueConstraint(
            "screen_id",
            "row_label",
            "seat_number",
            name="uq_seat_screen_row_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    screen_id: Mapped[int] = mapped_column(
        ForeignKey("screens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    row_label: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    seat_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        default="Regular",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    screen: Mapped["Screen"] = relationship(
        "Screen",
        back_populates="seats",
    )

    booked_seats: Mapped[list["BookedSeat"]] = relationship(
        "BookedSeat",
        back_populates="seat",
    )
