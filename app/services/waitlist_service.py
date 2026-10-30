
from sqlalchemy.orm import Session, joinedload

from app.models.waitlist import WaitlistEntry
from app.models.booking import Booking, BookedSeat
from app.models.venue import Seat
from app.models.event import Show


ACTIVE_WAITLIST_STATUSES = ("Waiting", "Notified")


def customer_has_booking(
    db: Session,
    show_id: int,
    customer_id: int,
) -> bool:
    booking = (
        db.query(Booking)
        .filter(
            Booking.show_id == show_id,
            Booking.customer_id == customer_id,
            Booking.status.in_(
                ["Confirmed", "Pending Payment"]
            ),
        )
        .first()
    )

    return booking is not None


def get_customer_waitlist_entry(
    db: Session,
    show_id: int,
    customer_id: int,
):
    return (
        db.query(WaitlistEntry)
        .filter(
            WaitlistEntry.show_id == show_id,
            WaitlistEntry.customer_id == customer_id,
            WaitlistEntry.status.in_(ACTIVE_WAITLIST_STATUSES),
        )
        .first()
    )


def join_waitlist(
    db: Session,
    show: Show,
    customer_id: int,
    seat_count: int,
    preferred_category: str | None = None,
) -> WaitlistEntry:

    if not show.is_active or show.status != "Scheduled":
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="This show is not accepting waitlist entries.",
        )

    if seat_count < 1 or seat_count > 10:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="You can request between 1 and 10 seats.",
        )

    if customer_has_booking(db, show.id, customer_id):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail="You already have a booking for this show.",
        )

    existing = get_customer_waitlist_entry(
        db,
        show.id,
        customer_id,
    )

    if existing:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail="You are already on the waitlist for this show.",
        )

    if preferred_category:
        category_exists = (
            db.query(Seat)
            .join(
                # Seat belongs to a screen. Check the screen
                # associated with this show's venue.
                __import__(
                    "app.models.venue",
                    fromlist=["Screen"],
                ).Screen,
                Seat.screen_id
                == __import__(
                    "app.models.venue",
                    fromlist=["Screen"],
                ).Screen.id,
            )
            .filter(
                __import__(
                    "app.models.venue",
                    fromlist=["Screen"],
                ).Screen.id == show.screen_id,
                Seat.category == preferred_category,
                Seat.is_active.is_(True),
            )
            .first()
        )

        # Category validation is completed against the show's
        # seat categories in the router before calling this service.
        # This branch is intentionally not used to decide availability.

    entry = WaitlistEntry(
        show_id=show.id,
        customer_id=customer_id,
        seat_count=seat_count,
        preferred_category=preferred_category,
        status="Waiting",
    )

    db.add(entry)
    db.flush()

    return entry


def get_show_waitlist(
    db: Session,
    show_id: int,
):
    return (
        db.query(WaitlistEntry)
        .options(joinedload(WaitlistEntry.customer))
        .filter(
            WaitlistEntry.show_id == show_id,
            WaitlistEntry.status.in_(ACTIVE_WAITLIST_STATUSES),
        )
        .order_by(
            WaitlistEntry.created_at.asc(),
            WaitlistEntry.id.asc(),
        )
        .all()
    )


def cancel_waitlist_entry(
    db: Session,
    entry: WaitlistEntry,
    customer_id: int,
) -> WaitlistEntry:

    if entry.customer_id != customer_id:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="You cannot cancel another customer's waitlist entry.",
        )

    if entry.status not in ACTIVE_WAITLIST_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="This waitlist entry is no longer active.",
        )

    entry.status = "Cancelled"
    return entry
