
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.redis_client import redis_client
from app.auth.security import get_current_user, require_roles

from app.models.user import User
from app.models.event import Show, SeatCategoryPrice
from app.models.booking import Booking, BookedSeat
from app.models.waitlist import WaitlistEntry

from app.utils.email import send_waitlist_email


router = APIRouter(tags=["Waitlist"])


class WaitlistCreateRequest(BaseModel):
    seat_count: int = Field(default=1, ge=1, le=10)
    preferred_category: str | None = None


def get_available_seat_count(db: Session, show_id: int):
    show = (
        db.query(Show)
        .filter(Show.id == show_id)
        .first()
    )

    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")

    total_seats = len(show.screen.seats)

    booked_seats = (
        db.query(BookedSeat.seat_id)
        .filter(
            BookedSeat.show_id == show_id,
            BookedSeat.is_confirmed.is_(True),
        )
        .distinct()
        .count()
    )

    locked_seat_ids = set()

    lock_pattern = f"lock:show:{show_id}:seat:*"

    for key in redis_client.scan_iter(match=lock_pattern):
        seat_id = key.rsplit(":", 1)[-1]

        try:
            locked_seat_ids.add(int(seat_id))
        except ValueError:
            continue

    # Avoid counting confirmed seats as available merely because
    # they have an old Redis lock key.
    confirmed_ids = {
        row[0]
        for row in (
            db.query(BookedSeat.seat_id)
            .filter(
                BookedSeat.show_id == show_id,
                BookedSeat.is_confirmed.is_(True),
            )
            .distinct()
            .all()
        )
    }

    effective_locked_count = len(locked_seat_ids - confirmed_ids)

    return max(
        0,
        total_seats - booked_seats - effective_locked_count,
    )


def get_active_waitlist_entry(
    db: Session,
    show_id: int,
    customer_id: int,
):
    return (
        db.query(WaitlistEntry)
        .filter(
            WaitlistEntry.show_id == show_id,
            WaitlistEntry.customer_id == customer_id,
            WaitlistEntry.status.in_(["Waiting", "Notified"]),
        )
        .first()
    )


@router.post("/shows/{show_id}/waitlist", status_code=201)
def join_waitlist(
    show_id: int,
    payload: WaitlistCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("customer")),
):
    show = (
        db.query(Show)
        .filter(Show.id == show_id)
        .first()
    )

    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")

    if not show.is_active or (show.status or "").lower() != "scheduled":
        raise HTTPException(
            status_code=400,
            detail="This show is not available for waitlist registration.",
        )

    if show.booking_closes_at <= datetime.now():
        raise HTTPException(
            status_code=400,
            detail="Booking for this show has closed.",
        )

    if payload.preferred_category:
        category_exists = (
            db.query(SeatCategoryPrice)
            .filter(
                SeatCategoryPrice.show_id == show_id,
                SeatCategoryPrice.category == payload.preferred_category,
            )
            .first()
        )

        if not category_exists:
            raise HTTPException(
                status_code=400,
                detail="Invalid seat category for this show.",
            )

    existing_booking = (
        db.query(Booking)
        .filter(
            Booking.show_id == show_id,
            Booking.customer_id == current_user.id,
            Booking.status.in_(["Pending Payment", "Confirmed"]),
        )
        .first()
    )

    if existing_booking:
        raise HTTPException(
            status_code=409,
            detail="You already have a booking for this show.",
        )

    existing_entry = get_active_waitlist_entry(
        db,
        show_id,
        current_user.id,
    )

    if existing_entry:
        raise HTTPException(
            status_code=409,
            detail="You are already on the waitlist for this show.",
        )

    available_seats = get_available_seat_count(db, show_id)

    if available_seats > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "This show is not sold out. "
                "Please book available seats instead."
            ),
        )

    entry = WaitlistEntry(
        show_id=show_id,
        customer_id=current_user.id,
        seat_count=payload.seat_count,
        preferred_category=payload.preferred_category,
        status="Waiting",
    )

    db.add(entry)
    db.commit()
    db.refresh(entry)

    return {
        "message": "Successfully joined the waitlist.",
        "waitlist_id": entry.id,
        "show_id": entry.show_id,
        "seat_count": entry.seat_count,
        "preferred_category": entry.preferred_category,
        "status": entry.status,
        "note": "Joining the waitlist does not guarantee a seat.",
    }


@router.get("/shows/{show_id}/waitlist")
def get_show_waitlist(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("admin", "organizer")
    ),
):
    show = (
        db.query(Show)
        .filter(Show.id == show_id)
        .first()
    )

    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")

    if (
        current_user.role == "organizer"
        and show.event.organizer_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can view only waitlists for your own events.",
        )

    entries = (
        db.query(WaitlistEntry)
        .filter(
            WaitlistEntry.show_id == show_id,
            WaitlistEntry.status.in_(["Waiting", "Notified"]),
        )
        .order_by(
            WaitlistEntry.created_at.asc(),
            WaitlistEntry.id.asc(),
        )
        .all()
    )

    return [
        {
            "waitlist_id": entry.id,
            "customer_id": entry.customer_id,
            "customer_name": entry.customer.name,
            "customer_email": entry.customer.email,
            "seat_count": entry.seat_count,
            "preferred_category": entry.preferred_category,
            "status": entry.status,
            "joined_at": entry.created_at,
        }
        for entry in entries
    ]


@router.delete("/waitlist/{waitlist_id}")
def cancel_waitlist_entry(
    waitlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = (
        db.query(WaitlistEntry)
        .filter(WaitlistEntry.id == waitlist_id)
        .first()
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Waitlist entry not found.",
        )

    if (
        current_user.role != "admin"
        and entry.customer_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot cancel another customer's waitlist entry.",
        )

    if entry.status not in ["Waiting", "Notified"]:
        raise HTTPException(
            status_code=400,
            detail="This waitlist entry is already inactive.",
        )

    entry.status = "Cancelled"

    db.commit()

    return {
        "message": "Waitlist entry cancelled successfully.",
        "waitlist_id": entry.id,
        "status": entry.status,
    }


def notify_waitlist_customers(
    db: Session,
    show_id: int,
    available_categories: list[str] | None = None,
    available_seat_count: int | None = None,
    background_tasks: BackgroundTasks | None = None,
):
    """
    Notify eligible customers in FIFO order.

    This sends availability notifications only. It does not reserve
    seats or automatically create bookings.
    """

    show = (
        db.query(Show)
        .filter(Show.id == show_id)
        .first()
    )

    if not show:
        return 0

    entries = (
        db.query(WaitlistEntry)
        .filter(
            WaitlistEntry.show_id == show_id,
            WaitlistEntry.status == "Waiting",
        )
        .order_by(
            WaitlistEntry.created_at.asc(),
            WaitlistEntry.id.asc(),
        )
        .all()
    )

    notified_count = 0
    remaining_seats = available_seat_count

    for entry in entries:
        if remaining_seats is not None and entry.seat_count > remaining_seats:
            continue

        if (
            available_categories is not None
            and entry.preferred_category
            and entry.preferred_category not in available_categories
        ):
            continue

        if background_tasks is not None:
            background_tasks.add_task(
                send_waitlist_email,
                entry.customer.email,
                entry.customer.name,
                show.event.title,
                show.id,
                entry.seat_count,
            )

        entry.status = "Notified"
        notified_count += 1

        if remaining_seats is not None:
            remaining_seats -= entry.seat_count

    db.commit()

    return notified_count
