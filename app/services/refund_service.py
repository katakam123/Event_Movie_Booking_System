
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.payment import Payment, Refund


CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def calculate_customer_refund(
    booking: Booking,
    now: datetime | None = None,
) -> Decimal:
    """
    Customer cancellation policy:

    More than 24 hours: 100% ticket_total
    2 to 24 hours: 50% ticket_total
    Less than 2 hours: cancellation not allowed

    Convenience fee and GST are not refunded.
    """

    now = now or datetime.now()

    if booking.status.lower() != "confirmed":
        raise HTTPException(
            status_code=400,
            detail="Only confirmed bookings can be cancelled.",
        )

    show_start = booking.show.starts_at
    remaining = show_start - now

    if remaining.total_seconds() < 2 * 60 * 60:
        raise HTTPException(
            status_code=400,
            detail="Cancellation is not allowed less than 2 hours before the show.",
        )

    ticket_total = money(booking.ticket_total)

    if remaining.total_seconds() > 24 * 60 * 60:
        return ticket_total

    return money(ticket_total * Decimal("0.50"))


def create_refund(
    db: Session,
    booking: Booking,
    payment: Payment,
    amount: Decimal,
    reason: str,
) -> Refund:
    """
    Create a mock refund record.

    This does not initiate an actual payment gateway refund.
    """

    amount = money(amount)

    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=400,
            detail="Refund amount must be greater than zero.",
        )

    if payment.booking_id != booking.id:
        raise HTTPException(
            status_code=400,
            detail="Payment does not belong to this booking.",
        )

    if payment.status.lower() not in ("success", "succeeded", "paid"):
        raise HTTPException(
            status_code=400,
            detail="Only successful payments can be refunded.",
        )

    existing_refunds = (
        db.query(Refund)
        .filter(
            Refund.payment_id == payment.id,
            Refund.status == "Refunded",
        )
        .all()
    )

    already_refunded = sum(
        (money(refund.amount) for refund in existing_refunds),
        Decimal("0.00"),
    )

    refundable_balance = money(payment.amount) - already_refunded

    if amount > refundable_balance:
        raise HTTPException(
            status_code=400,
            detail="Refund amount exceeds the remaining refundable payment balance.",
        )

    refund = Refund(
        booking_id=booking.id,
        payment_id=payment.id,
        amount=amount,
        reason=reason,
        status="Refunded",
        refunded_at=datetime.now(),
    )

    db.add(refund)

    # Mark payment refunded only when its entire amount is refunded.
    if amount == refundable_balance:
        payment.status = "Refunded"

    return refund


def get_booking_refunds(
    db: Session,
    booking_id: int,
) -> list[Refund]:
    return (
        db.query(Refund)
        .filter(Refund.booking_id == booking_id)
        .order_by(Refund.created_at.desc())
        .all()
    )
