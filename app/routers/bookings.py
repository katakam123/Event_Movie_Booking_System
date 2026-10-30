
from datetime import datetime, timedelta, time
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.redis_client import redis_client
from app.models.booking import Booking, BookedSeat
from app.models.event import Show, Event, SeatCategoryPrice
from app.models.venue import Screen, Seat
from app.models.user import User
from app.auth.security import get_current_user
from app.schemas.booking import BookingCreate, BookingResponse

router = APIRouter(prefix="/bookings", tags=["Bookings"])

MAX_SEATS_PER_BOOKING = 10
CONVENIENCE_FEE_PER_SEAT = Decimal("30.00")
GST_RATE = Decimal("0.18")

PENDING_STATUS = "Pending Payment"
CONFIRMED_STATUS = "Confirmed"
EXPIRED_STATUS = "Expired"
CANCELLED_STATUS = "Cancelled"

LOCK_PREFIX = "lock:show:{show_id}:seat:"
MUTEX_PREFIX = "lock:show:{show_id}:mutex"


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def seat_lock_key(show_id: int, seat_id: int) -> str:
    return f"lock:show:{show_id}:seat:{seat_id}"


def release_customer_locks(
    show_id: int,
    customer_id: int,
    seat_ids: list[int] | None = None,
) -> None:
    """Delete only Redis locks owned by the specified customer."""
    if seat_ids is None:
        pattern = f"lock:show:{show_id}:seat:*"
        seat_ids = []

        for key in redis_client.scan_iter(match=pattern):
            try:
                seat_ids.append(int(key.rsplit(":", 1)[1]))
            except (ValueError, IndexError):
                continue

    for seat_id in seat_ids:
        key = seat_lock_key(show_id, seat_id)
        owner = redis_client.get(key)

        if owner is not None and str(owner) == str(customer_id):
            redis_client.delete(key)


def expire_old_bookings(
    db: Session,
    customer_id: int | None = None,
) -> None:
    """
    Expire overdue pending bookings and release their reserved seats
    and Redis locks.
    """
    now = datetime.now()

    query = db.query(Booking).filter(
        Booking.status == PENDING_STATUS,
        Booking.expires_at <= now,
    )

    if customer_id is not None:
        query = query.filter(Booking.customer_id == customer_id)

    expired_bookings = query.all()

    for booking in expired_bookings:
        booking.status = EXPIRED_STATUS

        for booked_seat in booking.booked_seats:
            booked_seat.status = "expired"
            booked_seat.is_confirmed = False
            booked_seat.ticket_token = None

        release_customer_locks(
            show_id=booking.show_id,
            customer_id=booking.customer_id,
            seat_ids=[item.seat_id for item in booking.booked_seats],
        )


def verify_show_is_bookable(show: Show) -> None:
    now = datetime.now()

    if not show.is_active or show.status != "Scheduled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This show is not available for booking.",
        )

    if show.booking_closes_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking has closed for this show.",
        )

    if show.starts_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This show has already started.",
        )


def get_booking_or_404(
    db: Session,
    booking_id: int,
) -> Booking:
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.booked_seats),
            joinedload(Booking.show).joinedload(Show.event),
        )
        .filter(Booking.id == booking_id)
        .first()
    )

    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found.",
        )

    return booking


def authorize_booking_access(
    booking: Booking,
    current_user: User,
) -> None:
    if current_user.role == "admin":
        return

    if (
        current_user.role == "customer"
        and booking.customer_id == current_user.id
    ):
        return

    if (
        current_user.role == "organizer"
        and booking.show.event.organizer_id == current_user.id
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not allowed to access this booking.",
    )


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(
    data: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create bookings.",
        )

    if not current_user.is_active or not current_user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not approved for booking.",
        )

    if len(data.seat_ids) != len(set(data.seat_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate seat IDs are not allowed.",
        )

    if len(data.seat_ids) > MAX_SEATS_PER_BOOKING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="You can book at most 10 seats at a time.",
        )

    mutex_key = MUTEX_PREFIX.format(show_id=data.show_id)
    newly_created_booking = None

    try:
        expire_old_bookings(db, current_user.id)
        db.flush()

        with redis_client.lock(
            mutex_key,
            timeout=30,
            blocking_timeout=5,
        ):
            show = (
                db.query(Show)
                .filter(Show.id == data.show_id)
                .with_for_update()
                .first()
            )

            if show is None:
                raise HTTPException(
                    status_code=404,
                    detail="Show not found.",
                )

            verify_show_is_bookable(show)

            seats = (
                db.query(Seat)
                .filter(
                    Seat.screen_id == show.screen_id,
                    Seat.id.in_(data.seat_ids),
                )
                .all()
            )

            seats_by_id = {seat.id: seat for seat in seats}

            missing_ids = sorted(
                set(data.seat_ids) - set(seats_by_id)
            )

            if missing_ids:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "Some seats do not belong to this show's screen.",
                        "seat_ids": missing_ids,
                    },
                )

            inactive_ids = [
                seat_id
                for seat_id in data.seat_ids
                if not seats_by_id[seat_id].is_active
            ]

            if inactive_ids:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Some seats are inactive.",
                        "seat_ids": inactive_ids,
                    },
                )

            now = datetime.now()
            ttls = []

            for seat_id in data.seat_ids:
                key = seat_lock_key(data.show_id, seat_id)
                owner = redis_client.get(key)
                ttl = redis_client.ttl(key)

                if (
                    owner is None
                    or str(owner) != str(current_user.id)
                    or ttl <= 0
                ):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "You must lock every selected seat before booking.",
                            "seat_ids": [seat_id],
                        },
                    )

                ttls.append(ttl)

            occupied_ids = (
                db.query(BookedSeat.seat_id)
                .join(Booking, Booking.id == BookedSeat.booking_id)
                .filter(
                    BookedSeat.show_id == data.show_id,
                    Booking.status == CONFIRMED_STATUS,
                    BookedSeat.is_confirmed.is_(True),
                )
                .all()
            )
            occupied_ids = {seat_id for (seat_id,) in occupied_ids}

            conflict_ids = sorted(
                set(data.seat_ids) & occupied_ids
            )

            if conflict_ids:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Some selected seats are already booked.",
                        "seat_ids": conflict_ids,
                    },
                )

            price_rows = (
                db.query(
                    SeatCategoryPrice.category,
                    SeatCategoryPrice.price,
                )
                .filter(SeatCategoryPrice.show_id == data.show_id)
                .all()
            )

            prices = {
                category: money(price)
                for category, price in price_rows
            }

            missing_prices = [
                seat_id
                for seat_id in data.seat_ids
                if seats_by_id[seat_id].category not in prices
            ]

            if missing_prices:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "A price is not configured for some seat categories.",
                        "seat_ids": missing_prices,
                    },
                )

            ticket_total = sum(
                (
                    prices[seats_by_id[seat_id].category]
                    for seat_id in data.seat_ids
                ),
                Decimal("0.00"),
            )

            convenience_fee = money(
                CONVENIENCE_FEE_PER_SEAT * len(data.seat_ids)
            )

            gst_amount = money(
                (ticket_total + convenience_fee) * GST_RATE
            )

            grand_total = money(
                ticket_total + convenience_fee + gst_amount
            )

            # The booking cannot outlive the shortest seat lock.
            expires_at = now + timedelta(seconds=min(ttls))

            booking_number = (
                f"BKG-{now.strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
            )

            booking = Booking(
                booking_number=booking_number,
                booking_reference=booking_number,
                customer_id=current_user.id,
                show_id=data.show_id,
                seat_count=len(data.seat_ids),
                ticket_total=ticket_total,
                convenience_fee=convenience_fee,
                gst_amount=gst_amount,
                grand_total=grand_total,
                total_amount=grand_total,
                currency="INR",
                status=PENDING_STATUS,
                expires_at=expires_at,
            )

            db.add(booking)
            db.flush()

            for seat_id in data.seat_ids:
                seat = seats_by_id[seat_id]

                db.add(
                    BookedSeat(
                        booking_id=booking.id,
                        show_id=data.show_id,
                        seat_id=seat_id,
                        price=prices[seat.category],
                        status="reserved",
                        is_confirmed=False,
                        checked_in=False,
                    )
                )

            db.commit()

            newly_created_booking = booking.id

        return get_booking_response(db, newly_created_booking)

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A booking conflict occurred. Please try again.",
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Unable to create the booking. Please try again.",
        )


def get_booking_response(
    db: Session,
    booking_id: int,
) -> Booking:
    return (
        db.query(Booking)
        .options(joinedload(Booking.booked_seats))
        .filter(Booking.id == booking_id)
        .first()
    )


@router.get("", response_model=list[BookingResponse])
def get_my_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    expire_old_bookings(db)
    db.commit()

    query = db.query(Booking).options(
        joinedload(Booking.booked_seats),
        joinedload(Booking.show).joinedload(Show.event),
    )

    if current_user.role == "customer":
        query = query.filter(
            Booking.customer_id == current_user.id
        )

    elif current_user.role == "organizer":
        query = (
            query.join(Show, Booking.show_id == Show.id)
            .join(Event, Show.event_id == Event.id)
            .filter(Event.organizer_id == current_user.id)
        )

    elif current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to view bookings.",
        )

    return query.order_by(Booking.created_at.desc()).all()


@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    expire_old_bookings(db, current_user.id if current_user.role == "customer" else None)
    db.commit()

    booking = get_booking_or_404(db, booking_id)
    authorize_booking_access(booking, current_user)

    return booking
