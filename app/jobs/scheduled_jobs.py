
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.redis_client import redis_client

from app.models.booking import Booking, BookedSeat
from app.models.event import Show, Event

from app.utils.email import send_show_reminder_email


logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone="Asia/Kolkata",
)


def release_expired_booking_locks(booking):
    """
    Delete only Redis seat locks owned by this booking's customer.
    The value stored by the seat-lock endpoint must be the customer ID.
    """

    for booked_seat in booking.booked_seats:
        key = (
            f"lock:show:{booking.show_id}:seat:"
            f"{booked_seat.seat_id}"
        )

        try:
            current_owner = redis_client.get(key)

            if current_owner == str(booking.customer_id):
                redis_client.delete(key)

        except Exception:
            logger.exception(
                "Could not release Redis lock for booking %s",
                booking.id,
            )


def expired_booking_job():
    """
    Run every minute.

    Expire Pending Payment bookings after expires_at,
    release their reserved seats, and remove their Redis locks.
    """

    db = SessionLocal()

    try:
        now = datetime.now()

        expired_bookings = (
            db.query(Booking)
            .filter(
                Booking.status == "Pending Payment",
                Booking.expires_at <= now,
            )
            .order_by(Booking.expires_at.asc())
            .all()
        )

        expired_count = 0

        for booking in expired_bookings:
            lock = redis_client.lock(
                f"lock:show:{booking.show_id}:mutex",
                timeout=30,
                blocking_timeout=5,
            )

            acquired = False

            try:
                acquired = lock.acquire(blocking=True)

                if not acquired:
                    continue

                # Re-read and lock the booking after obtaining the mutex.
                booking = (
                    db.query(Booking)
                    .filter(Booking.id == booking.id)
                    .with_for_update()
                    .first()
                )

                if (
                    not booking
                    or booking.status != "Pending Payment"
                    or booking.expires_at > datetime.now()
                ):
                    continue

                booked_seats = (
                    db.query(BookedSeat)
                    .filter(BookedSeat.booking_id == booking.id)
                    .with_for_update()
                    .all()
                )

                booking.status = "Expired"

                for booked_seat in booked_seats:
                    booked_seat.is_confirmed = False
                    booked_seat.status = "expired"
                    booked_seat.ticket_token = None

                db.flush()

                release_expired_booking_locks(booking)

                db.commit()
                expired_count += 1

            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to expire booking %s",
                    booking.id,
                )

            finally:
                if acquired and lock.owned():
                    lock.release()

        if expired_count:
            logger.info(
                "Expired %s pending bookings.",
                expired_count,
            )

    except Exception:
        db.rollback()
        logger.exception("Expired booking job failed.")

    finally:
        db.close()


def show_reminder_job():
    """
    Run every 30 minutes.

    Email customers whose confirmed show starts in the next 3 hours.
    Set reminder_sent_at only after successful email delivery.
    """

    db = SessionLocal()

    try:
        now = datetime.now()
        reminder_limit = now + timedelta(hours=3)

        bookings = (
            db.query(Booking)
            .join(Show, Booking.show_id == Show.id)
            .options(
                joinedload(Booking.customer),
                joinedload(Booking.show).joinedload(Show.event),
                joinedload(Booking.show).joinedload(Show.screen),
            )
            .filter(
                Booking.status == "Confirmed",
                Booking.reminder_sent_at.is_(None),
                Show.status == "Scheduled",
                Show.starts_at > now,
                Show.starts_at <= reminder_limit,
            )
            .all()
        )

        sent_count = 0

        for booking in bookings:
            try:
                customer = booking.customer
                show = booking.show
                venue_name = show.screen.venue.name

                success = send_show_reminder_email(
                    recipient=customer.email,
                    customer_name=customer.name,
                    event_name=show.event.title,
                    booking_number=booking.booking_number,
                    starts_at=show.starts_at.strftime(
                        "%d-%m-%Y %I:%M %p"
                    ),
                    venue_name=venue_name,
                )

                if success:
                    booking.reminder_sent_at = datetime.now()
                    db.commit()
                    sent_count += 1
                else:
                    db.rollback()

            except Exception:
                db.rollback()
                logger.exception(
                    "Reminder failed for booking %s",
                    booking.id,
                )

        if sent_count:
            logger.info(
                "Sent %s show reminder emails.",
                sent_count,
            )

    except Exception:
        db.rollback()
        logger.exception("Show reminder job failed.")

    finally:
        db.close()


def show_completion_job():
    """
    Run every 15 minutes.

    Mark scheduled shows as Completed after their ends_at time.
    """

    db = SessionLocal()

    try:
        now = datetime.now()

        updated = (
            db.query(Show)
            .filter(
                Show.status == "Scheduled",
                Show.ends_at <= now,
            )
            .update(
                {
                    Show.status: "Completed",
                    Show.is_active: False,
                },
                synchronize_session=False,
            )
        )

        db.commit()

        if updated:
            logger.info(
                "Marked %s shows as Completed.",
                updated,
            )

    except Exception:
        db.rollback()
        logger.exception("Show completion job failed.")

    finally:
        db.close()


def event_completion_job():
    """
    Run once a day.

    Mark events Completed when they have at least one show
    and every show has status Completed.
    """

    db = SessionLocal()

    try:
        events = db.query(Event).all()
        completed_count = 0

        for event in events:
            shows = (
                db.query(Show)
                .filter(Show.event_id == event.id)
                .all()
            )

            if not shows:
                continue

            all_completed = all(
                (show.status or "").lower() == "completed"
                for show in shows
            )

            if all_completed and (event.status or "").lower() != "completed":
                event.status = "Completed"
                completed_count += 1

        db.commit()

        if completed_count:
            logger.info(
                "Marked %s events as Completed.",
                completed_count,
            )

    except Exception:
        db.rollback()
        logger.exception("Event completion job failed.")

    finally:
        db.close()
