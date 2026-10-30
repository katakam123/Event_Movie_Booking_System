
import hashlib
import hmac
import os
from pathlib import Path

import qrcode
from dotenv import load_dotenv

load_dotenv()

TICKET_HMAC_SECRET = os.getenv("TICKET_HMAC_SECRET")

if not TICKET_HMAC_SECRET:
    raise RuntimeError("TICKET_HMAC_SECRET is missing from .env")

TICKETS_DIR = Path("tickets")
TICKETS_DIR.mkdir(parents=True, exist_ok=True)


def create_signed_ticket(booking_number: str) -> str:
    """Create a secure HMAC-signed QR payload."""

    signature = hmac.new(
        TICKET_HMAC_SECRET.encode("utf-8"),
        booking_number.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{booking_number}.{signature}"


def verify_signed_ticket(qr_data: str) -> str | None:
    """Verify a signed QR payload and return the booking number."""

    if not qr_data or "." not in qr_data:
        return None

    booking_number, supplied_signature = qr_data.rsplit(".", 1)

    if not booking_number or not supplied_signature:
        return None

    expected_signature = hmac.new(
        TICKET_HMAC_SECRET.encode("utf-8"),
        booking_number.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        supplied_signature,
        expected_signature,
    ):
        return None

    return booking_number


def generate_ticket_qr(booking_number: str) -> str:
    """
    Generate a QR code PNG for a booking.

    The QR contains the signed booking number.
    Returns the generated image path.
    """

    if not booking_number:
        raise ValueError("Booking number cannot be empty.")

    signed_payload = create_signed_ticket(booking_number)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )

    qr.add_data(signed_payload)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    file_path = TICKETS_DIR / f"{booking_number}.png"

    image.save(file_path)

    return str(file_path)
