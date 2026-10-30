
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import case
from app.auth.security import get_current_user
from app.database import get_db
from app.models.booking import Booking, BookedSeat
from app.models.event import Show
from app.models.user import User
from app.models.venue import Venue
from app.schemas.ticket import (
    TicketScanRequest,
    TicketScanResponse,
    ShowEntriesResponse,
)
from app.utils.ticket_pdf import generate_booking_pdf
from app.utils.ticket_qr import verify_signed_ticket


router = APIRouter(tags=["Tickets & Gate Entry"])


def authorize_booking_ticket(booking: Booking, user: User):
    if user.role == "admin":
        return

    if user.role == "customer" and booking.customer_id == user.id:
        return

    if user.role == "organizer":
        if booking.show.event.organizer_id == user.id:
            return

    raise HTTPException(
        status_code=403,
        detail="You cannot access this ticket.",
    )


@router.get("/bookings/{booking_id}/ticket")
def download_ticket(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.customer),
            joinedload(Booking.show)
            .joinedload(Show.event),
            joinedload(Booking.show)
            .joinedload(Show.screen)
            .joinedload("venue"),
            joinedload(Booking.booked_seats)
            .joinedload(BookedSeat.seat),
        )
        .filter(Booking.id == booking_id)
        .first()
    )

    if booking is None:
        raise HTTPException(
            status_code=404,
            detail="Booking not found.",
        )

    authorize_booking_ticket(booking, current_user)

    if booking.status != "Confirmed":
        raise HTTPException(
            status_code=409,
            detail="Tickets are available only for confirmed bookings.",
        )

    try:
        pdf_path = generate_booking_pdf(booking)
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unable to generate the ticket PDF.",
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{booking.booking_number}.pdf",
    )


@router.post(
    "/tickets/scan",
    response_model=TicketScanResponse,
)
def scan_ticket(
    payload: TicketScanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Only approved gate staff accounts can scan tickets.
    if current_user.role != "gate_staff":
        raise HTTPException(
            status_code=403,
            detail="Only gate staff can scan tickets.",
        )

    if not current_user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Your staff account is inactive.",
        )

    if not current_user.assigned_venue_id:
        raise HTTPException(
            status_code=403,
            detail="No venue has been assigned to your account.",
        )

    booking_number = verify_signed_ticket(payload.qr_data)

    if booking_number is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or forged ticket QR code.",
        )

    try:
        booking = (
            db.query(Booking)
            .options(
                joinedload(Booking.customer),
                joinedload(Booking.show)
                .joinedload(Show.screen),
                joinedload(Booking.booked_seats)
                .joinedload(BookedSeat.seat),
            )
            .filter(Booking.booking_number == booking_number)
            .with_for_update()
            .first()
        )

        if booking is None:
            raise HTTPException(
                status_code=404,
                detail="Booking not found.",
            )

        if booking.status != "Confirmed":
            raise HTTPException(
                status_code=409,
                detail="Ticket is not valid. Booking is not confirmed.",
            )

        show = booking.show
        screen = show.screen

        if screen.venue_id != current_user.assigned_venue_id:
            raise HTTPException(
                status_code=403,
                detail="This ticket belongs to another venue.",
            )

        now = datetime.now()

        scan_start = show.starts_at - timedelta(hours=1)

        if now < scan_start:
            raise HTTPException(
                status_code=409,
                detail="Ticket scanning opens one hour before the show.",
            )

        if now > show.ends_at:
            raise HTTPException(
                status_code=409,
                detail="The show has ended. Ticket scanning is closed.",
            )

        if show.status == "Cancelled":
            raise HTTPException(
                status_code=409,
                detail="This show has been cancelled.",
            )

        seats = (
            db.query(BookedSeat)
            .filter(BookedSeat.booking_id == booking.id)
            .with_for_update()
            .all()
        )

        if not seats:
            raise HTTPException(
                status_code=409,
                detail="No seats are attached to this booking.",
            )

        already_used = next(
            (seat for seat in seats if seat.checked_in),
            None,
        )

        if already_used:
            used_at = already_used.checked_in_at

            if used_at is None:
                used_at = "an earlier time"

            raise HTTPException(
                status_code=409,
                detail=f"Ticket already used at {used_at}",
            )

        # Mark every seat in the booking as checked in.
        for seat in seats:
            seat.checked_in = True
            seat.checked_in_at = now

        db.commit()

        seat_labels = [
            f"{seat.seat.row_label}{seat.seat.seat_number}"
            for seat in seats
        ]

        return TicketScanResponse(
            success=True,
            message="Ticket accepted. Entry allowed.",
            booking_number=booking.booking_number,
            customer_name=booking.customer.name,
            seats=seat_labels,
            seat_count=len(seats),
            checked_in_at=now,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to process ticket scan.",
        )


@router.get(
    "/shows/{show_id}/entries",
    response_model=ShowEntriesResponse,
)
def get_show_entries(
    show_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    show = (
        db.query(Show)
        .options(
            joinedload(Show.event),
            joinedload(Show.screen),
        )
        .filter(Show.id == show_id)
        .first()
    )

    if show is None:
        raise HTTPException(
            status_code=404,
            detail="Show not found.",
        )

    if current_user.role == "admin":
        pass
    elif current_user.role == "organizer":
        if show.event.organizer_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You cannot view entries for this event.",
            )
    elif current_user.role == "gate_staff":
        if show.screen.venue_id != current_user.assigned_venue_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot view entries for another venue.",
            )
    else:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view show entries.",
        )

    total_bookings = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.show_id == show_id,
            Booking.status == "Confirmed",
        )
        .scalar()
        or 0
    )

    entered_subquery = (
        db.query(
            BookedSeat.booking_id.label("booking_id"),
            func.sum(
                case(
                    (BookedSeat.checked_in.is_(True), 1),
                    else_=0,
                )
            ).label("checked_count"),
        )
        .group_by(BookedSeat.booking_id)
        .subquery()
    )

    entered_bookings = (
        db.query(func.count(Booking.id))
        .join(
            entered_subquery,
            entered_subquery.c.booking_id == Booking.id,
        )
        .filter(
            Booking.show_id == show_id,
            Booking.status == "Confirmed",
            entered_subquery.c.checked_count == Booking.seat_count,
        )
        .scalar()
        or 0
    )

    total_customers = (
        db.query(func.coalesce(func.sum(Booking.seat_count), 0))
        .filter(
            Booking.show_id == show_id,
            Booking.status == "Confirmed",
        )
        .scalar()
        or 0
    )

    pending_entries = total_bookings - entered_bookings

    return ShowEntriesResponse(
        show_id=show_id,
        total_bookings=total_bookings,
        entered_bookings=entered_bookings,
        pending_entries=pending_entries,
        total_customers=total_customers,
    )
