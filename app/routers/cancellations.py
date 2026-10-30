
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.redis_client import redis_client
from app.auth.security import get_current_user, require_roles

from app.models.user import User
from app.models.event import Show
from app.models.booking import Booking, BookedSeat
from app.models.payment import Payment, Refund

from app.utils.email import (
    send_cancellation_email,
    send_show_cancelled_email,
)


router = APIRouter(tags=["Cancellations and Refunds"])

MONEY_PLACES = Decimal("0.01")

SUCCESS_PAYMENT_STATUSES = {
    "success",
    "succeeded",
    "paid",
}


def money(value):
    return Decimal(str(value or 0)).quantize(
        MONEY_PLACES,
        rounding=ROUND_HALF_UP,
    )


def acquire_show_mutex(show_id: int):
    lock = redis_client.lock(
        f"lock:show:{show_id}:mutex",
        timeout=30,
        blocking_timeout=5,
    )

    acquired = lock.acquire(blocking=True)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Show is currently being updated. Please try again.",
        )

    return lock


def calculate_customer_refund(booking: Booking, show: Show):
    now = datetime.now()
    time_remaining = show.starts_at - now

    if time_remaining <= timedelta(hours=2):
        raise HTTPException(
            status_code=400,
            detail="Cancellation is not allowed within 2 hours of the show.",
        )

    if time_remaining > timedelta(hours=24):
        return money(booking.ticket_total)

    return money(booking.ticket_total * Decimal("0.50"))


def create_mock_refund(
    db: Session,
    booking: Booking,
    refund_amount: Decimal,
    reason: str,
):
    """
    Allocate the refund across successful payments.
    Existing refunds are deducted from each payment's refundable balance.
    """

    remaining = money(refund_amount)

    payments = (
        db.query(Payment)
        .filter(Payment.booking_id == booking.id)
        .order_by(Payment.id.asc())
        .with_for_update()
        .all()
    )

    successful_payments = [
        payment
        for payment in payments
        if (payment.status or "").lower() in SUCCESS_PAYMENT_STATUSES
    ]

    for payment in successful_payments:
        if remaining <= 0:
            break

        already_refunded = (
            db.query(Refund)
            .filter(
                Refund.payment_id == payment.id,
                Refund.status == "Refunded",
            )
            .with_for_update()
            .all()
        )

        refunded_total = sum(
            (money(refund.amount) for refund in already_refunded),
            Decimal("0.00"),
        )

        refundable_balance = max(
            Decimal("0.00"),
            money(payment.amount) - refunded_total,
        )

        amount_to_refund = min(remaining, refundable_balance)

        if amount_to_refund <= 0:
            continue

        refund = Refund(
            booking_id=booking.id,
            payment_id=payment.id,
            amount=amount_to_refund,
            status="Refunded",
            reason=reason,
            refunded_at=datetime.now(),
        )

        db.add(refund)
        db.flush()

        remaining = money(remaining - amount_to_refund)

        if amount_to_refund == refundable_balance:
            payment.status = "Refunded"

    if remaining > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "The successful payments do not have enough refundable "
                "balance for this refund."
            ),
        )


def release_booking_seats(db: Session, booking: Booking):
    booked_seats = (
        db.query(BookedSeat)
        .filter(BookedSeat.booking_id == booking.id)
        .with_for_update()
        .all()
    )

    if any(seat.checked_in for seat in booked_seats):
        raise HTTPException(
            status_code=400,
            detail="A booking containing checked-in seats cannot be cancelled.",
        )

    for booked_seat in booked_seats:
        booked_seat.is_confirmed = False
        booked_seat.status = "cancelled"
        booked_seat.ticket_token = None


@router.put("/bookings/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("customer")),
):
    booking = (
        db.query(Booking)
        .filter(
            Booking.id == booking_id,
            Booking.customer_id == current_user.id,
        )
        .first()
    )

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")

    if (booking.status or "").lower() != "confirmed":
        raise HTTPException(
            status_code=400,
            detail="Only confirmed bookings can be cancelled.",
        )

    lock = acquire_show_mutex(booking.show_id)

    try:
        booking = (
            db.query(Booking)
            .filter(Booking.id == booking_id)
            .with_for_update()
            .first()
        )

        show = (
            db.query(Show)
            .filter(Show.id == booking.show_id)
            .with_for_update()
            .first()
        )

        if not show or (show.status or "").lower() == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="This show is not available for customer cancellation.",
            )

        if (booking.status or "").lower() != "confirmed":
            raise HTTPException(
                status_code=409,
                detail="This booking has already been processed.",
            )

        refund_amount = calculate_customer_refund(booking, show)

        release_booking_seats(db, booking)

        create_mock_refund(
            db=db,
            booking=booking,
            refund_amount=refund_amount,
            reason="Customer Cancellation",
        )

        booking.status = "Cancelled"

        db.commit()

        background_tasks.add_task(
            send_cancellation_email,
            current_user.email,
            current_user.name,
            booking.booking_number,
            str(refund_amount),
            "Customer Cancellation",
        )

        return {
            "message": "Booking cancelled successfully.",
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "refund_amount": str(refund_amount),
            "refund_status": "Refunded",
            "note": (
                "This is a mock refund record. No real payment gateway "
                "transaction has been performed."
            ),
        }

    except Exception:
        db.rollback()
        raise

    finally:
        if lock.owned():
            lock.release()


@router.get("/bookings/{booking_id}/refunds")
def get_booking_refunds(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = db.query(Booking).filter(
        Booking.id == booking_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")

    if (
        current_user.role != "admin"
        and booking.customer_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied.")

    refunds = (
        db.query(Refund)
        .filter(Refund.booking_id == booking_id)
        .order_by(Refund.refunded_at.desc())
        .all()
    )

    return [
        {
            "refund_id": refund.id,
            "booking_id": refund.booking_id,
            "payment_id": refund.payment_id,
            "amount": str(refund.amount),
            "status": refund.status,
            "reason": refund.reason,
            "refunded_at": refund.refunded_at,
        }
        for refund in refunds
    ]


@router.put("/shows/{show_id}/cancel")
def cancel_show(
    show_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "organizer")),
):
    show = db.query(Show).filter(Show.id == show_id).first()

    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")

    if current_user.role == "organizer":
        if show.event.organizer_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You can cancel only your own shows.",
            )

    lock = acquire_show_mutex(show_id)

    try:
        show = (
            db.query(Show)
            .filter(Show.id == show_id)
            .with_for_update()
            .first()
        )

        if (show.status or "").lower() == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="This show is already cancelled.",
            )

        if show.starts_at <= datetime.now():
            raise HTTPException(
                status_code=400,
                detail="A show that has already started cannot be cancelled.",
            )

        bookings = (
            db.query(Booking)
            .filter(
                Booking.show_id == show_id,
                Booking.status.ilike("confirmed"),
            )
            .with_for_update()
            .all()
        )

        # A show cancellation is not allowed after any ticket has been used.
        for booking in bookings:
            booked_seats = (
                db.query(BookedSeat)
                .filter(BookedSeat.booking_id == booking.id)
                .all()
            )

            if any(seat.checked_in for seat in booked_seats):
                raise HTTPException(
                    status_code=409,
                    detail="Cannot cancel a show after a customer has checked in.",
                )

        show.status = "Cancelled"
        show.is_active = False

        for booking in bookings:
            refund_amount = money(booking.grand_total)

            release_booking_seats(db, booking)

            create_mock_refund(
                db=db,
                booking=booking,
                refund_amount=refund_amount,
                reason="Show Cancellation",
            )

            booking.status = "Cancelled"

            background_tasks.add_task(
                send_show_cancelled_email,
                booking.customer.email,
                booking.customer.name,
                show.event.title,
                booking.booking_number,
                str(refund_amount),
            )

        db.commit()

        return {
            "message": "Show cancelled successfully.",
            "show_id": show.id,
            "cancelled_bookings": len(bookings),
            "refund_total": str(
                sum(
                    (money(booking.grand_total) for booking in bookings),
                    Decimal("0.00"),
                )
            ),
        }

    except Exception:
        db.rollback()
        raise

    finally:
        if lock.owned():
            lock.release()
