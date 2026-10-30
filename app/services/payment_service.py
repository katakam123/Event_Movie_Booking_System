
import hashlib
import hmac
from decimal import Decimal, ROUND_HALF_UP

import razorpay

from app.config import settings


razorpay_client = razorpay.Client(
    auth=(
        settings.RAZORPAY_KEY_ID,
        settings.RAZORPAY_KEY_SECRET,
    )
)


def amount_to_paise(amount: Decimal) -> int:
    """Convert rupees into paise."""
    return int(
        (Decimal(amount) * Decimal("100")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def create_razorpay_order(booking):
    """Create a Razorpay order for a pending booking."""

    amount = amount_to_paise(Decimal(booking.grand_total))

    receipt = (
        booking.booking_number
        or booking.booking_reference
    )

    return razorpay_client.order.create(
        data={
            "amount": amount,
            "currency": getattr(booking, "currency", "INR"),
            "receipt": receipt[:40],
            "notes": {
                "booking_id": str(booking.id),
                "booking_reference": str(booking.booking_reference),
            },
        }
    )


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify Razorpay Checkout payment signature."""

    message = (
        f"{razorpay_order_id}|{razorpay_payment_id}"
    ).encode("utf-8")

    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        razorpay_signature,
    )


def verify_webhook_signature(
    payload: bytes,
    webhook_signature: str,
) -> bool:
    """Verify Razorpay webhook signature against the raw body."""

    expected_signature = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        webhook_signature,
    )
def fetch_razorpay_payment(razorpay_payment_id: str):
    """Retrieve payment details directly from Razorpay."""
    return razorpay_client.payment.fetch(razorpay_payment_id)   