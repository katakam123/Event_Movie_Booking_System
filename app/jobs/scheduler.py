
import logging

from app.jobs.scheduled_jobs import (
    expired_booking_job,
    show_reminder_job,
    show_completion_job,
    event_completion_job,
)

from apscheduler.schedulers.background import BackgroundScheduler


logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone="Asia/Kolkata",
)


def start_scheduler():
    if scheduler.running:
        logger.info("Scheduler is already running.")
        return

    scheduler.add_job(
        expired_booking_job,
        trigger="interval",
        minutes=1,
        id="expired_booking_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        show_reminder_job,
        trigger="interval",
        minutes=30,
        id="show_reminder_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        show_completion_job,
        trigger="interval",
        minutes=15,
        id="show_completion_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        event_completion_job,
        trigger="cron",
        hour=0,
        minute=0,
        id="event_completion_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()

    logger.info("APScheduler started successfully.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
