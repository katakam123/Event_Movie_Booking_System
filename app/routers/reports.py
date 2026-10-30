
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.security import get_current_user

from app.models.event import Event, Show
from app.models.booking import Booking, BookedSeat
from app.models.payment import Payment, Refund
from app.models.venue import Screen, Seat


router = APIRouter(
    prefix="/reports",
    tags=["Reports & Dashboard"],
)


# Change these values if your payment service uses different statuses.
SUCCESSFUL_PAYMENT_STATUSES = (
    "Success",
    "Succeeded",
    "Paid",
    "Completed",
)

SUCCESSFUL_REFUND_STATUSES = (
    "Refunded",
    "Completed",
    "Success",
)


# ---------------------------------------------------------
# COMMON HELPERS
# ---------------------------------------------------------

def get_user_role(current_user):
    """
    Return the user's role in lowercase.
    Supports either a string role or an Enum role.
    """
    role = getattr(current_user, "role", None)

    if role is None:
        return ""

    return str(getattr(role, "value", role)).lower().replace(" ", "_")


def check_role(current_user, allowed_roles):
    """
    Check whether the current user has permission.
    """
    role = get_user_role(current_user)

    if role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this report.",
        )


def date_range_bounds(from_date: date, to_date: date):
    """
    Convert inclusive date range into datetime boundaries.
    The end boundary is exclusive.
    """
    if from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be later than to_date.",
        )

    start_datetime = datetime.combine(from_date, time.min)
    end_datetime = datetime.combine(
        to_date + timedelta(days=1),
        time.min,
    )

    return start_datetime, end_datetime


def organizer_event_filter(query, current_user):
    """
    Restrict organizer reports to events owned by that organizer.
    Admin reports are not restricted by this helper.
    """
    if get_user_role(current_user) == "organizer":
        query = query.filter(
            Event.organizer_id == current_user.id
        )

    return query


def successful_payment_query(db, start_datetime, end_datetime):
    """
    Payments successfully completed during the requested period.
    """
    return (
        db.query(
            Booking.show_id.label("show_id"),
            func.coalesce(
                func.sum(Payment.amount), 0
            ).label("revenue"),
        )
        .join(Booking, Booking.id == Payment.booking_id)
        .filter(
            Payment.status.in_(SUCCESSFUL_PAYMENT_STATUSES),
            Payment.paid_at >= start_datetime,
            Payment.paid_at < end_datetime,
        )
        .group_by(Booking.show_id)
        .subquery()
    )


def refund_query(db, start_datetime, end_datetime):
    """
    Refund totals grouped by show during the requested period.
    """
    return (
        db.query(
            Booking.show_id.label("show_id"),
            func.coalesce(
                func.sum(Refund.amount), 0
            ).label("refund_amount"),
        )
        .join(Booking, Booking.id == Refund.booking_id)
        .filter(
            Refund.status.in_(SUCCESSFUL_REFUND_STATUSES),
            Refund.refunded_at >= start_datetime,
            Refund.refunded_at < end_datetime,
        )
        .group_by(Booking.show_id)
        .subquery()
    )


def money(value):
    """
    Convert SQL aggregate values into a JSON-friendly decimal.
    """
    return Decimal(str(value or 0)).quantize(
        Decimal("0.01")
    )


# ---------------------------------------------------------
# 1. ADMIN DASHBOARD
# GET /reports/admin-dashboard
# ADMIN ONLY
# ---------------------------------------------------------

@router.get("/admin-dashboard")
def admin_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    check_role(current_user, {"admin"})

    today = date.today()

    start_datetime = datetime.combine(today, time.min)
    end_datetime = start_datetime + timedelta(days=1)

    # Today's bookings
    today_bookings = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.created_at >= start_datetime,
            Booking.created_at < end_datetime,
        )
        .scalar()
        or 0
    )

    # Today's successful payment revenue
    today_revenue = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.status.in_(SUCCESSFUL_PAYMENT_STATUSES),
            Payment.paid_at >= start_datetime,
            Payment.paid_at < end_datetime,
        )
        .scalar()
    )

    # Today's successful refunds
    today_refunds = (
        db.query(func.coalesce(func.sum(Refund.amount), 0))
        .filter(
            Refund.status.in_(SUCCESSFUL_REFUND_STATUSES),
            Refund.refunded_at >= start_datetime,
            Refund.refunded_at < end_datetime,
        )
        .scalar()
    )

    today_refund_count = (
        db.query(func.count(Refund.id))
        .filter(
            Refund.status.in_(SUCCESSFUL_REFUND_STATUSES),
            Refund.refunded_at >= start_datetime,
            Refund.refunded_at < end_datetime,
        )
        .scalar()
        or 0
    )

    # Active events
    active_events = (
        db.query(func.count(Event.id))
        .filter(Event.is_active.is_(True))
        .scalar()
        or 0
    )

    # Tickets scanned today
    tickets_scanned = (
        db.query(func.count(BookedSeat.id))
        .filter(
            BookedSeat.checked_in.is_(True),
            BookedSeat.checked_in_at >= start_datetime,
            BookedSeat.checked_in_at < end_datetime,
        )
        .scalar()
        or 0
    )

    return {
        "report": "Admin Dashboard",
        "date": today.isoformat(),
        "today_bookings": today_bookings,
        "today_revenue": money(today_revenue),
        "today_refunds": money(today_refunds),
        "today_refund_count": today_refund_count,
        "active_events": active_events,
        "tickets_scanned": tickets_scanned,
    }


# ---------------------------------------------------------
# 2. EVENT SALES REPORT
# GET /reports/event-sales
# ADMIN AND ORGANIZER
# ---------------------------------------------------------

@router.get("/event-sales")
def event_sales_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    check_role(current_user, {"admin", "organizer"})

    start_datetime, end_datetime = date_range_bounds(
        from_date,
        to_date,
    )

    # Report is based on show start date.
    query = (
        db.query(Event, Show)
        .join(Show, Show.event_id == Event.id)
        .filter(
            Show.starts_at >= start_datetime,
            Show.starts_at < end_datetime,
        )
    )

    query = organizer_event_filter(query, current_user)

    show_rows = query.order_by(
        Show.starts_at.asc()
    ).all()

    results = []

    total_tickets = 0
    total_revenue = Decimal("0.00")
    total_refunds = Decimal("0.00")

    for event, show in show_rows:

        # Confirmed tickets sold for this show
        tickets_sold = (
            db.query(func.count(BookedSeat.id))
            .join(
                Booking,
                Booking.id == BookedSeat.booking_id,
            )
            .filter(
                Booking.show_id == show.id,
                BookedSeat.is_confirmed.is_(True),
            )
            .scalar()
            or 0
        )

        # Successful payments associated with this show.
        revenue = (
            db.query(
                func.coalesce(func.sum(Payment.amount), 0)
            )
            .join(
                Booking,
                Booking.id == Payment.booking_id,
            )
            .filter(
                Booking.show_id == show.id,
                Payment.status.in_(
                    SUCCESSFUL_PAYMENT_STATUSES
                ),
                Payment.paid_at >= start_datetime,
                Payment.paid_at < end_datetime,
            )
            .scalar()
        )

        # Successful refunds associated with this show.
        refunds = (
            db.query(
                func.coalesce(func.sum(Refund.amount), 0)
            )
            .join(
                Booking,
                Booking.id == Refund.booking_id,
            )
            .filter(
                Booking.show_id == show.id,
                Refund.status.in_(
                    SUCCESSFUL_REFUND_STATUSES
                ),
                Refund.refunded_at >= start_datetime,
                Refund.refunded_at < end_datetime,
            )
            .scalar()
        )

        revenue = money(revenue)
        refunds = money(refunds)

        results.append({
            "event_id": event.id,
            "event_title": event.title,
            "show_id": show.id,
            "show_date": show.starts_at,
            "tickets_sold": tickets_sold,
            "revenue": revenue,
            "refunds": refunds,
        })

        total_tickets += tickets_sold
        total_revenue += revenue
        total_refunds += refunds

    return {
        "report": "Event Sales Report",
        "from_date": from_date,
        "to_date": to_date,
        "total_tickets_sold": total_tickets,
        "total_revenue": money(total_revenue),
        "total_refunds": money(total_refunds),
        "shows": results,
    }


# ---------------------------------------------------------
# 3. SHOW OCCUPANCY REPORT
# GET /reports/occupancy
# ADMIN AND ORGANIZER
# ---------------------------------------------------------

@router.get("/occupancy")
def occupancy_report(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    check_role(current_user, {"admin", "organizer"})

    query = (
        db.query(Event, Show, Screen)
        .join(Show, Show.event_id == Event.id)
        .join(Screen, Screen.id == Show.screen_id)
        .filter(
            Show.is_active.is_(True),
            Event.is_active.is_(True),
        )
    )

    query = organizer_event_filter(query, current_user)

    show_rows = query.order_by(
        Show.starts_at.asc()
    ).all()

    results = []

    for event, show, screen in show_rows:

        # Total active seats in this screen
        total_seats = (
            db.query(func.count(Seat.id))
            .filter(
                Seat.screen_id == screen.id,
                Seat.is_active.is_(True),
            )
            .scalar()
            or 0
        )

        # Confirmed seats for this show
        confirmed_seats = (
            db.query(func.count(BookedSeat.id))
            .join(
                Booking,
                Booking.id == BookedSeat.booking_id,
            )
            .filter(
                Booking.show_id == show.id,
                BookedSeat.is_confirmed.is_(True),
                BookedSeat.seat_id.in_(
                    db.query(Seat.id).filter(
                        Seat.screen_id == screen.id,
                        Seat.is_active.is_(True),
                    )
                ),
            )
            .scalar()
            or 0
        )

        occupancy_percentage = (
            round((confirmed_seats / total_seats) * 100, 2)
            if total_seats > 0
            else 0.0
        )

        # Occupancy by seat category
        category_rows = (
            db.query(
                Seat.category,
                func.count(Seat.id).label("total_seats"),
            )
            .filter(
                Seat.screen_id == screen.id,
                Seat.is_active.is_(True),
            )
            .group_by(Seat.category)
            .all()
        )

        category_results = []

        for category, category_total in category_rows:

            category_booked = (
                db.query(func.count(BookedSeat.id))
                .join(
                    Booking,
                    Booking.id == BookedSeat.booking_id,
                )
                .join(
                    Seat,
                    Seat.id == BookedSeat.seat_id,
                )
                .filter(
                    Booking.show_id == show.id,
                    BookedSeat.is_confirmed.is_(True),
                    Seat.screen_id == screen.id,
                    Seat.category == category,
                    Seat.is_active.is_(True),
                )
                .scalar()
                or 0
            )

            category_percentage = (
                round(
                    (category_booked / category_total) * 100,
                    2,
                )
                if category_total > 0
                else 0.0
            )

            category_results.append({
                "category": category,
                "total_seats": category_total,
                "booked_seats": category_booked,
                "available_seats": (
                    category_total - category_booked
                ),
                "occupancy_percentage": category_percentage,
            })

        results.append({
            "event_id": event.id,
            "event_title": event.title,
            "show_id": show.id,
            "show_date": show.starts_at,
            "screen_id": screen.id,
            "screen_name": screen.name,
            "total_seats": total_seats,
            "booked_seats": confirmed_seats,
            "available_seats": max(
                total_seats - confirmed_seats,
                0,
            ),
            "occupancy_percentage": occupancy_percentage,
            "categories": category_results,
        })

    return {
        "report": "Show Occupancy Report",
        "total_shows": len(results),
        "shows": results,
    }


# ---------------------------------------------------------
# 4. TOP 10 EVENTS
# GET /reports/top-events
# ADMIN ONLY
# ---------------------------------------------------------

@router.get("/top-events")
def top_events_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    check_role(current_user, {"admin"})

    start_datetime, end_datetime = date_range_bounds(
        from_date,
        to_date,
    )

    results = (
        db.query(
            Event.id.label("event_id"),
            Event.title.label("event_title"),
            func.count(BookedSeat.id).label("tickets_sold"),
        )
        .join(
            Show,
            Show.event_id == Event.id,
        )
        .join(
            Booking,
            Booking.show_id == Show.id,
        )
        .join(
            BookedSeat,
            BookedSeat.booking_id == Booking.id,
        )
        .filter(
            Show.starts_at >= start_datetime,
            Show.starts_at < end_datetime,
            BookedSeat.is_confirmed.is_(True),
        )
        .group_by(
            Event.id,
            Event.title,
        )
        .order_by(
            func.count(BookedSeat.id).desc(),
            Event.id.asc(),
        )
        .limit(10)
        .all()
    )

    events = []

    for rank, row in enumerate(results, start=1):
        events.append({
            "rank": rank,
            "event_id": row.event_id,
            "event_title": row.event_title,
            "tickets_sold": row.tickets_sold,
        })

    return {
        "report": "Top 10 Events",
        "from_date": from_date,
        "to_date": to_date,
        "events": events,
    }


# ---------------------------------------------------------
# 5. REFUND REPORT
# GET /reports/refunds
# ADMIN ONLY
# ---------------------------------------------------------

@router.get("/refunds")
def refunds_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    check_role(current_user, {"admin"})

    start_datetime, end_datetime = date_range_bounds(
        from_date,
        to_date,
    )

    rows = (
        db.query(
            Refund.reason,
            func.count(Refund.id).label("refund_count"),
            func.coalesce(
                func.sum(Refund.amount), 0
            ).label("refund_amount"),
        )
        .filter(
            Refund.status.in_(SUCCESSFUL_REFUND_STATUSES),
            Refund.refunded_at >= start_datetime,
            Refund.refunded_at < end_datetime,
        )
        .group_by(Refund.reason)
        .order_by(Refund.reason.asc())
        .all()
    )

    reason_results = []

    total_count = 0
    total_amount = Decimal("0.00")

    for row in rows:
        amount = money(row.refund_amount)

        reason_results.append({
            "reason": row.reason or "Unspecified",
            "refund_count": row.refund_count,
            "refund_amount": amount,
        })

        total_count += row.refund_count
        total_amount += amount

    return {
        "report": "Refund Report",
        "from_date": from_date,
        "to_date": to_date,
        "total_refund_count": total_count,
        "total_refund_amount": money(total_amount),
        "refunds_by_reason": reason_results,
    }
