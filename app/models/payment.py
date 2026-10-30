
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    transaction_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )

    transaction_ref: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True
    )

    # Razorpay fields
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )

    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )

    razorpay_signature: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    payment_method: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Pending"
    )

    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    booking = relationship(
        "Booking",
        back_populates="payments",
    )

    refunds = relationship(
        "Refund",
        back_populates="payment",
    )


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="Refunded", index=True
    )

    reason: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    refunded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    booking = relationship(
        "Booking",
        back_populates="refunds",
    )

    payment = relationship(
        "Payment",
        back_populates="refunds",
    )


class RazorpayWebhookEvent(Base):
    __tablename__ = "razorpay_webhook_events"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    # Razorpay event ID makes webhook processing idempotent.
    event_id: Mapped[str] = mapped_column(
        String(150), unique=True, nullable=False, index=True
    )

    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    payment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    payment = relationship("Payment")
