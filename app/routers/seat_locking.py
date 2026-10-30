
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.redis_client import redis_client
from app.models.event import Show, SeatCategoryPrice
from app.models.venue import Screen, Seat
from app.models.booking import Booking, BookedSeat
from app.models.user import User
from app.auth.security import get_current_user, require_roles
from app.schemas.seat_lock import (
    SeatLockRequest,
    SeatLockResponse,
    ReleaseSeatLocksRequest,
    ShowSeatsResponse,
    ShowSeatResponse,
)

router = APIRouter(tags=["Seat Locking"])

customer_only = require_roles("customer")

LOCK_SECONDS = 600

# Update these values if your booking workflow uses different statuses.
CONFIRMED_BOOKING_STATUSES = {"confirmed", "paid", "completed"}


def get_show_or_404(db: Session, show_id: int) -> Show:
    show = db.query(Show).filter(Show.id == show_id).first()

    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    return show


def ensure_show_can_be_booked(show: Show):
    if show.status != "Scheduled" or not show.is_active:
        raise HTTPException(
            status_code=409,
            detail="This show is not available for booking",
        )

    if show.booking_closes_at <= datetime.now():
        raise HTTPException(
            status_code=409,
            detail="Booking has closed for this show",
        )


def lock_key(show_id: int, seat_id: int) -> str:
    return f"lock:show:{show_id}:seat:{seat_id}"


def get_booked_seat_ids(db: Session, show_id: int) -> set[int]:
    rows = (
        db.query(BookedSeat.seat_id)
        .join(Booking, Booking.id == BookedSeat.booking_id)
        .filter(
            BookedSeat.show_id == show_id,
            Booking.status.in_(CONFIRMED_BOOKING_STATUSES),
        )
        .all()
    )

    return {seat_id for (seat_id,) in rows}


def get_locked_seat_ids(show_id: int) -> set[int]:
    pattern = f"lock:show:{show_id}:seat:*"
    seat_ids = set()

    for key in redis_client.scan_iter(match=pattern):
        try:
            seat_ids.add(int(key.rsplit(":", 1)[1]))
        except (ValueError, IndexError):
            continue

    return seat_ids


def get_seat_prices(db: Session, show_id: int) -> dict[str, Decimal]:
    rows = (
        db.query(SeatCategoryPrice.category, SeatCategoryPrice.price)
        .filter(SeatCategoryPrice.show_id == show_id)
        .all()
    )

    return {category: price for category, price in rows}


def check_no_single_empty_seat(
    all_seats: list[Seat],
    occupied_seat_ids: set[int],
) -> None:
    """Reject a seat selection that leaves one active seat isolated."""
    seats_by_row: dict[str, list[Seat]] = {}

    for seat in all_seats:
        if seat.is_active:
            seats_by_row.setdefault(seat.row_label, []).append(seat)

    for row_seats in seats_by_row.values():
        row_seats.sort(key=lambda seat: seat.seat_number)

        occupied_numbers = {
            seat.seat_number
            for seat in row_seats
            if seat.id in occupied_seat_ids
        }

        active_numbers = {seat.seat_number for seat in row_seats}

        for number in active_numbers:
            if number in occupied_numbers:
                continue

            if (
                number - 1 in occupied_numbers
                and number + 1 in occupied_numbers
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Your selection would leave a single empty seat "
                        "between occupied seats in the same row."
                    ),
                )


@router.get(
    "/shows/{show_id}/seats",
    response_model=ShowSeatsResponse,
)
def get_show_seats(
    show_id: int,
    db: Session = Depends(get_db),
):
    show = get_show_or_404(db, show_id)

    seats = (
        db.query(Seat)
        .join(Screen, Screen.id == Seat.screen_id)
        .filter(Seat.screen_id == show.screen_id)
        .order_by(Seat.row_label, Seat.seat_number)
        .all()
    )

    prices = get_seat_prices(db, show_id)
    booked_ids = get_booked_seat_ids(db, show_id)
    locked_ids = get_locked_seat_ids(show_id)

    result = []

    for seat in seats:
        price = prices.get(seat.category)

        if (
            not seat.is_active
            or show.status != "Scheduled"
            or not show.is_active
        ):
            seat_status = "Unavailable"
        elif seat.id in booked_ids:
            seat_status = "Booked"
        elif seat.id in locked_ids:
            seat_status = "Locked"
        else:
            seat_status = "Available"

        result.append(
            ShowSeatResponse(
                seat_id=seat.id,
                row_label=seat.row_label,
                seat_number=seat.seat_number,
                category=seat.category,
                price=float(price) if price is not None else None,
                status=seat_status,
            )
        )

    return ShowSeatsResponse(
        show_id=show.id,
        show_status=show.status,
        seats=result,
    )


@router.post(
    "/shows/{show_id}/lock-seats",
    response_model=SeatLockResponse,
)
def lock_seats(
    show_id: int,
    data: SeatLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(customer_only),
):
    show = get_show_or_404(db, show_id)
    ensure_show_can_be_booked(show)

    if len(data.seat_ids) != len(set(data.seat_ids)):
        raise HTTPException(
            status_code=422,
            detail="Duplicate seat IDs are not allowed",
        )

    screen_seats = (
        db.query(Seat)
        .filter(Seat.screen_id == show.screen_id)
        .all()
    )
    seats_by_id = {seat.id: seat for seat in screen_seats}

    missing_ids = [
        seat_id for seat_id in data.seat_ids
        if seat_id not in seats_by_id
    ]

    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail={"message": "Some seats do not belong to this screen",
                    "seat_ids": missing_ids},
        )

    inactive_ids = [
        seat_id for seat_id in data.seat_ids
        if not seats_by_id[seat_id].is_active
    ]

    if inactive_ids:
        raise HTTPException(
            status_code=409,
            detail={"message": "Inactive seats cannot be locked",
                    "seat_ids": inactive_ids},
        )

    booked_ids = get_booked_seat_ids(db, show_id)
    already_booked = sorted(set(data.seat_ids) & booked_ids)

    if already_booked:
        raise HTTPException(
            status_code=409,
            detail={"message": "Some seats are already booked",
                    "seat_ids": already_booked},
        )

    all_locked_ids = get_locked_seat_ids(show_id)
    other_locked_ids = set()

    for seat_id in all_locked_ids:
        owner_id = redis_client.get(lock_key(show_id, seat_id))

        if owner_id is not None and owner_id != str(current_user.id):
            other_locked_ids.add(seat_id)

    unavailable = sorted(set(data.seat_ids) & other_locked_ids)

    if unavailable:
        raise HTTPException(
            status_code=409,
            detail={"message": "Some seats are already locked",
                    "seat_ids": unavailable},
        )

    # Enforce the maximum of 10 active locks per customer per show.
    own_locked_ids = {
        seat_id
        for seat_id in all_locked_ids
        if redis_client.get(lock_key(show_id, seat_id))
        == str(current_user.id)
    }

    combined_own_ids = own_locked_ids | set(data.seat_ids)

    if len(combined_own_ids) > 10:
        raise HTTPException(
            status_code=409,
            detail="You can lock at most 10 seats for one show",
        )

    # Include existing bookings, locks owned by others, and this selection.
    # Inactive seats are unavailable and are not treated as empty seats.
    occupied_ids = booked_ids | all_locked_ids | set(data.seat_ids)

    try:
        check_no_single_empty_seat(screen_seats, occupied_ids)
    except HTTPException:
        raise

    newly_locked = []

    try:
        # A per-show mutex serializes requests from this API instance group.
        with redis_client.lock(
            f"lock:show:{show_id}:mutex",
            timeout=15,
            blocking_timeout=5,
        ):
            # Re-check Redis state after acquiring the mutex.
            for seat_id in data.seat_ids:
                key = lock_key(show_id, seat_id)
                existing_owner = redis_client.get(key)

                if existing_owner == str(current_user.id):
                    continue

                success = redis_client.set(
                    key,
                    str(current_user.id),
                    nx=True,
                    ex=LOCK_SECONDS,
                )

                if not success:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Seat lock conflict",
                            "seat_ids": [seat_id],
                        },
                    )

                newly_locked.append(key)

    except HTTPException:
        for key in newly_locked:
            if redis_client.get(key) == str(current_user.id):
                redis_client.delete(key)
        raise
    except Exception:
        for key in newly_locked:
            if redis_client.get(key) == str(current_user.id):
                redis_client.delete(key)

        raise HTTPException(
            status_code=503,
            detail="Unable to acquire seat locks. Please try again.",
        )

    return SeatLockResponse(
        show_id=show_id,
        seat_ids=data.seat_ids,
        locked=True,
        lock_expires_at=datetime.now() + timedelta(seconds=LOCK_SECONDS),
        message="Seats locked successfully for 10 minutes",
    )


@router.delete(
    "/shows/{show_id}/lock-seats",
    response_model=SeatLockResponse,
)
def release_seat_locks(
    show_id: int,
    data: ReleaseSeatLocksRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(customer_only),
):
    get_show_or_404(db, show_id)

    if len(data.seat_ids) != len(set(data.seat_ids)):
        raise HTTPException(
            status_code=422,
            detail="Duplicate seat IDs are not allowed",
        )

    not_owned = []

    for seat_id in data.seat_ids:
        owner_id = redis_client.get(lock_key(show_id, seat_id))

        if owner_id != str(current_user.id):
            not_owned.append(seat_id)

    if not_owned:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "You can release only your own active locks",
                "seat_ids": not_owned,
            },
        )

    for seat_id in data.seat_ids:
        key = lock_key(show_id, seat_id)

        # Re-check the owner before deleting the key.
        if redis_client.get(key) == str(current_user.id):
            redis_client.delete(key)

    return SeatLockResponse(
        show_id=show_id,
        seat_ids=data.seat_ids,
        locked=False,
        lock_expires_at=datetime.now(),
        message="Seat locks released successfully",
    )
