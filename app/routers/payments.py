from app.config import settings
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.redis_client import redis_client
from app.models.booking import Booking, BookedSeat
from app.models.event import Show
from app.models.payment import Payment
from app.models.user import User
from app.auth.security import get_current_user
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentVerificationRequest,
    RazorpayOrderResponse,
)
from app.routers.bookings import release_customer_locks
from app.utils.ticket_qr import generate_ticket_qr
from app.services.payment_service import (
    amount_to_paise,
    create_razorpay_order,
    fetch_razorpay_payment,
    verify_payment_signature,
)

router = APIRouter(tags=["Payments"])

PENDING_STATUS = "Pending Payment"
CONFIRMED_STATUS = "Confirmed"
EXPIRED_STATUS = "Expired"

MUTEX_PREFIX = "lock:show:{show_id}:mutex"


def make_transaction_id() -> str:
    return (
        f"TXN-{datetime.now().strftime('%Y%m%d')}-"
        f"{uuid4().hex[:10].upper()}"
    )


def lock_key(show_id: int, seat_id: int) -> str:
    return f"lock:show:{show_id}:seat:{seat_id}"


def get_booking_for_payment(
    db: Session,
    booking_id: int,
    customer_id: int,
) -> Booking:
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.booked_seats),
            joinedload(Booking.show),
        )
        .filter(
            Booking.id == booking_id,
            Booking.customer_id == customer_id,
        )
        .first()
    )

    if booking is None:
        raise HTTPException(
            status_code=404,
            detail="Booking not found.",
        )

    return booking


def verify_payment_locks(booking: Booking) -> list[int]:
    invalid_seats = []

    for item in booking.booked_seats:
        key = lock_key(booking.show_id, item.seat_id)
        owner = redis_client.get(key)
        ttl = redis_client.ttl(key)

        if (
            owner is None
            or str(owner) != str(booking.customer_id)
            or ttl <= 0
        ):
            invalid_seats.append(item.seat_id)

    return invalid_seats


def validate_booking_before_payment(
    db: Session,
    booking: Booking,
) -> list[int]:
    """Validate booking, show, Redis locks and seat conflicts."""

    now = datetime.now()

    if booking.status != PENDING_STATUS:
        raise HTTPException(
            status_code=409,
            detail=f"Booking cannot be paid. Status: {booking.status}.",
        )

    if booking.expires_at <= now:
        booking.status = EXPIRED_STATUS

        for item in booking.booked_seats:
            item.status = "expired"
            item.is_confirmed = False
            item.ticket_token = None

        release_customer_locks(
            booking.show_id,
            booking.customer_id,
            [item.seat_id for item in booking.booked_seats],
        )

        db.commit()

        raise HTTPException(
            status_code=409,
            detail="Booking expired. Please select seats again.",
        )

    show = (
        db.query(Show)
        .filter(Show.id == booking.show_id)
        .with_for_update()
        .first()
    )

    if show is None:
        raise HTTPException(status_code=404, detail="Show not found.")

    if (
        not show.is_active
        or show.status != "Scheduled"
        or show.booking_closes_at <= now
        or show.starts_at <= now
    ):
        raise HTTPException(
            status_code=409,
            detail="This show is no longer accepting payments.",
        )

    if not booking.booked_seats:
        raise HTTPException(
            status_code=409,
            detail="This booking has no reserved seats.",
        )

    invalid_seats = verify_payment_locks(booking)

    if invalid_seats:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Some seat locks have expired. Please book again.",
                "seat_ids": invalid_seats,
            },
        )

    seat_ids = [item.seat_id for item in booking.booked_seats]

    conflicts = (
        db.query(BookedSeat.seat_id)
        .filter(
            BookedSeat.show_id == booking.show_id,
            BookedSeat.seat_id.in_(seat_ids),
            BookedSeat.is_confirmed.is_(True),
            BookedSeat.booking_id != booking.id,
        )
        .all()
    )

    conflict_ids = [seat_id for (seat_id,) in conflicts]

    if conflict_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Some seats have already been booked.",
                "seat_ids": conflict_ids,
            },
        )

    return seat_ids


def confirm_booking_after_payment(
    db: Session,
    booking: Booking,
    payment: Payment,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> None:
    """Confirm booking only after verified Razorpay payment."""

    if booking.status == CONFIRMED_STATUS:
        if payment.razorpay_payment_id == razorpay_payment_id:
            return

        raise HTTPException(
            status_code=409,
            detail="Booking has already been confirmed.",
        )

    seat_ids = validate_booking_before_payment(db, booking)

    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature
    payment.status = "Success"
    payment.paid_at = datetime.now()

    booking.status = CONFIRMED_STATUS
    booking.confirmed_at = datetime.now()

    for item in booking.booked_seats:
        item.status = "booked"
        item.is_confirmed = True
        item.checked_in = False
        item.ticket_token = uuid4().hex

    db.flush()

    for item in booking.booked_seats:
        generate_ticket_qr(item.ticket_token)

    db.flush()

    release_customer_locks(
        booking.show_id,
        booking.customer_id,
        seat_ids,
    )


@router.post(
    "/bookings/{booking_id}/pay",
    response_model=RazorpayOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def pay_for_booking(
    booking_id: int,
    data: PaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=403,
            detail="Only customers can make payments.",
        )

    if not current_user.is_active or not current_user.is_approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is not approved for payment.",
        )

    booking = get_booking_for_payment(
        db,
        booking_id,
        current_user.id,
    )

    mutex_key = MUTEX_PREFIX.format(show_id=booking.show_id)

    try:
        with redis_client.lock(
            mutex_key,
            timeout=30,
            blocking_timeout=5,
        ):
            booking = (
                db.query(Booking)
                .options(
                    joinedload(Booking.booked_seats),
                    joinedload(Booking.show),
                )
                .filter(
                    Booking.id == booking_id,
                    Booking.customer_id == current_user.id,
                )
                .with_for_update()
                .first()
            )

            if booking is None:
                raise HTTPException(
                    status_code=404,
                    detail="Booking not found.",
                )

            if booking.status == CONFIRMED_STATUS:
                raise HTTPException(
                    status_code=409,
                    detail="This booking has already been paid.",
                )

            seat_ids = validate_booking_before_payment(db, booking)

            # Reuse an existing pending Razorpay order when possible.
            existing_payment = (
                db.query(Payment)
                .filter(
                    Payment.booking_id == booking.id,
                    Payment.status == "Pending",
                    Payment.razorpay_order_id.isnot(None),
                )
                .order_by(Payment.id.desc())
                .first()
            )

            if existing_payment:
                return RazorpayOrderResponse(
                    booking_id=booking.id,
                    booking_reference=booking.booking_reference,
                    razorpay_order_id=existing_payment.razorpay_order_id,
                    amount=amount_to_paise(booking.grand_total),
                    currency=getattr(booking, "currency", "INR"),
                    razorpay_key_id=__import__(
                        "app.config", fromlist=["settings"]
                    ).settings.RAZORPAY_KEY_ID,
                )

            # Create the Razorpay order.
            order = create_razorpay_order(booking)

            payment = Payment(
                booking_id=booking.id,
                transaction_id=make_transaction_id(),
                transaction_ref=make_transaction_id(),
                razorpay_order_id=order["id"],
                amount=booking.grand_total,
                payment_method=data.payment_method,
                status="Pending",
            )

            db.add(payment)
            db.commit()

            return RazorpayOrderResponse(
                booking_id=booking.id,
                booking_reference=booking.booking_reference,
                razorpay_order_id=order["id"],
                amount=order["amount"],
                currency=order["currency"],
                razorpay_key_id=__import__(
                    "app.config", fromlist=["settings"]
                ).settings.RAZORPAY_KEY_ID,
            )

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Payment order conflict. Please try again.",
        )

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Unable to create Razorpay order. Please try again.",
        ) from exc


@router.post(
    "/bookings/{booking_id}/verify-payment",
    response_model=PaymentResponse,
)
def verify_booking_payment(
    booking_id: int,
    data: PaymentVerificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=403,
            detail="Only customers can verify payments.",
        )

    booking = get_booking_for_payment(
        db,
        booking_id,
        current_user.id,
    )

    mutex_key = MUTEX_PREFIX.format(show_id=booking.show_id)

    try:
        with redis_client.lock(
            mutex_key,
            timeout=30,
            blocking_timeout=5,
        ):
            booking = (
                db.query(Booking)
                .options(joinedload(Booking.booked_seats))
                .filter(
                    Booking.id == booking_id,
                    Booking.customer_id == current_user.id,
                )
                .with_for_update()
                .first()
            )

            if booking is None:
                raise HTTPException(
                    status_code=404,
                    detail="Booking not found.",
                )

            payment = (
                db.query(Payment)
                .filter(
                    Payment.booking_id == booking.id,
                    Payment.razorpay_order_id == data.razorpay_order_id,
                )
                .with_for_update()
                .first()
            )

            if payment is None:
                raise HTTPException(
                    status_code=404,
                    detail="Payment order not found.",
                )

            if payment.status == "Success":
                if payment.razorpay_payment_id == data.razorpay_payment_id:
                    return payment

                raise HTTPException(
                    status_code=409,
                    detail="This booking has already been paid.",
                )

            if payment.status != "Pending":
                raise HTTPException(
                    status_code=409,
                    detail="This payment is not pending.",
                )

            valid_signature = verify_payment_signature(
                data.razorpay_order_id,
                data.razorpay_payment_id,
                data.razorpay_signature,
            )

            if not valid_signature:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Razorpay payment signature.",
                )

            # Verify payment details directly with Razorpay.
            gateway_payment = fetch_razorpay_payment(
                data.razorpay_payment_id
            )

            if gateway_payment.get("order_id") != data.razorpay_order_id:
                raise HTTPException(
                    status_code=400,
                    detail="Payment does not belong to this order.",
                )

            expected_amount = amount_to_paise(payment.amount)

            if int(gateway_payment.get("amount", 0)) != expected_amount:
                raise HTTPException(
                    status_code=400,
                    detail="Payment amount does not match booking amount.",
                )

            if gateway_payment.get("currency") != getattr(
                booking, "currency", "INR"
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Payment currency does not match booking currency.",
                )

            if gateway_payment.get("status") != "captured":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Razorpay payment is not captured yet. "
                        "Wait for payment capture and try again."
                    ),
                )

            confirm_booking_after_payment(
                db=db,
                booking=booking,
                payment=payment,
                razorpay_payment_id=data.razorpay_payment_id,
                razorpay_signature=data.razorpay_signature,
            )

            db.commit()
            db.refresh(payment)

            return payment

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Payment transaction conflict. Please contact support.",
        )

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Unable to verify payment. Please try again.",
        ) from exc


@router.get(
    "/bookings/{booking_id}/payments",
    response_model=list[PaymentResponse],
)
def get_booking_payments(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.show).joinedload(Show.event)
        )
        .filter(Booking.id == booking_id)
        .first()
    )

    if booking is None:
        raise HTTPException(
            status_code=404,
            detail="Booking not found.",
        )

    allowed = (
        current_user.role == "admin"
        or (
            current_user.role == "customer"
            and booking.customer_id == current_user.id
        )
        or (
            current_user.role == "organizer"
            and booking.show.event.organizer_id == current_user.id
        )
    )

    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to view these payments.",
        )

    return (
        db.query(Payment)
        .filter(Payment.booking_id == booking_id)
        .order_by(Payment.id.desc())
        .all()
    )
