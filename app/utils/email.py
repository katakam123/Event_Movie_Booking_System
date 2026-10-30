
import os
import smtplib
import logging

from pathlib import Path
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "True").lower() == "true"


def send_email(
    recipient: str,
    subject: str,
    body: str,
    attachment_path: str | None = None,
) -> bool:
    """Send an email, optionally attaching a PDF file."""

    try:
        if not all([
            SMTP_HOST,
            SMTP_USER,
            SMTP_PASSWORD,
            SMTP_FROM_EMAIL,
        ]):
            logger.error("SMTP configuration is incomplete.")
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = SMTP_FROM_EMAIL
        message["To"] = recipient
        message.set_content(body)

        if attachment_path:
            file_path = Path(attachment_path)

            if not file_path.is_file():
                logger.error("Email attachment not found: %s", file_path)
                return False

            with file_path.open("rb") as file:
                file_data = file.read()

            message.add_attachment(
                file_data,
                maintype="application",
                subtype="pdf",
                filename=file_path.name,
            )

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USE_TLS:
                server.starttls()

            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)

        logger.info("Email sent successfully to %s", recipient)
        return True

    except Exception:
        logger.exception("Failed to send email to %s", recipient)
        return False


def send_booking_confirmed_email(
    recipient,
    customer_name,
    booking_number,
    ticket_pdf_path,
):
    return send_email(
        recipient,
        "Your Ticket Booking Is Confirmed",
        (
            f"Hello {customer_name},\n\n"
            "Your booking has been confirmed.\n\n"
            f"Booking Number: {booking_number}\n\n"
            "Your PDF ticket is attached. Please present its QR code "
            "at the venue entrance.\n\n"
            "Thank you for booking with us."
        ),
        attachment_path=ticket_pdf_path,
    )


def send_payment_failed_email(
    recipient,
    customer_name,
    booking_number,
):
    return send_email(
        recipient,
        "Payment Failed",
        (
            f"Hello {customer_name},\n\n"
            "Unfortunately, your payment could not be completed.\n\n"
            f"Booking Number: {booking_number}\n\n"
            "Please try booking again or check your payment details."
        ),
    )


def send_cancellation_email(
    recipient,
    customer_name,
    booking_number,
    refund_amount,
    reason,
):
    return send_email(
        recipient,
        "Booking Cancelled - Refund Details",
        (
            f"Hello {customer_name},\n\n"
            "Your booking has been cancelled.\n\n"
            f"Booking Number: {booking_number}\n"
            f"Reason: {reason}\n"
            f"Refund Amount: {refund_amount}\n\n"
            "This is a mock refund record. No real payment gateway "
            "transaction has been performed."
        ),
    )


def send_show_cancelled_email(
    recipient,
    customer_name,
    event_name,
    booking_number,
    refund_amount,
):
    return send_email(
        recipient,
        "Show Cancelled - Refund Information",
        (
            f"Hello {customer_name},\n\n"
            f"The show '{event_name}' has been cancelled by the organizer.\n\n"
            f"Booking Number: {booking_number}\n"
            f"Refund Amount: {refund_amount}\n\n"
            "This is a mock refund record. No real payment gateway "
            "transaction has been performed."
        ),
    )


def send_waitlist_email(
    recipient,
    customer_name,
    event_name,
    show_id,
    seat_count,
):
    return send_email(
        recipient,
        "Seats May Be Available - Waitlist Update",
        (
            f"Hello {customer_name},\n\n"
            f"Seats may now be available for '{event_name}'.\n"
            f"Show ID: {show_id}\n"
            f"Requested seats: {seat_count}\n\n"
            "Please visit the application and check availability.\n"
            "This email does not reserve seats for you."
        ),
    )


def send_show_reminder_email(
    recipient,
    customer_name,
    event_name,
    booking_number,
    starts_at,
    venue_name,
):
    return send_email(
        recipient,
        "Reminder: Your Upcoming Show",
        (
            f"Hello {customer_name},\n\n"
            f"This is a reminder for '{event_name}'.\n\n"
            f"Booking Number: {booking_number}\n"
            f"Venue: {venue_name}\n"
            f"Show Starts At: {starts_at}\n\n"
            "Please arrive early and keep your ticket QR code ready."
        ),
    )
