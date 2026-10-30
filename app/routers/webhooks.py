
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.booking import Booking
from app.models.payment import Payment, RazorpayWebhookEvent
from app.services.payment_service import verify_webhook_signature
from app.routers.payments import confirm_booking_after_payment


router = APIRouter(
    prefix="/webhooks",
    tags=["Razorpay Webhooks"],
)


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(
        default=None,
        alias="X-Razorpay-Signature",
    ),
    x_razorpay_event_id: str | None = Header(
        default=None,
        alias="x-razorpay-event-id",
    ),
):
    # Read the exact raw bytes. Do not re-serialize JSON before verifying.
    raw_body = await request.body()

    if not x_razorpay_signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay webhook signature.",
        )

    if not x_razorpay_event_id:
        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay event ID.",
        )

    if not verify_webhook_signature(
        raw_body,
        x_razorpay_signature,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid Razorpay webhook signature.",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook JSON payload.",
        )

    event_type = payload.get("event")

    if event_type not in ("payment.captured", "payment.failed"):
        return {
            "status": "ignored",
            "event": event_type,
        }

    payment_entity = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )

    razorpay_payment_id = payment_entity.get("id")
    razorpay_order_id = payment_entity.get("order_id")

    if not razorpay_payment_id or not razorpay_order_id:
        raise HTTPException(
            status_code=400,
            detail="Webhook does not contain payment and order IDs.",
        )

    try:
        # Check whether this event was already processed.
        existing_event = (
            db.query(RazorpayWebhookEvent)
            .filter(
                RazorpayWebhookEvent.event_id == x_razorpay_event_id
            )
            .first()
        )

        if existing_event and existing_event.processed:
            return {
                "status": "already_processed",
                "event_id": x_razorpay_event_id,
            }

        if existing_event:
            # An unprocessed event may be retried after an earlier failure.
            webhook_event = existing_event
        else:
            webhook_event = RazorpayWebhookEvent(
                event_id=x_razorpay_event_id,
                event_type=event_type,
                processed=False,
            )
            db.add(webhook_event)
            db.flush()

        payment = (
            db.query(Payment)
            .filter(
                Payment.razorpay_order_id == razorpay_order_id
            )
            .with_for_update()
            .first()
        )

        if payment is None:
            raise HTTPException(
                status_code=404,
                detail="Payment order not found.",
            )

        webhook_event.payment_id = payment.id
        webhook_event.event_type = event_type

        if event_type == "payment.failed":
            # Do not overwrite a previously successful payment.
            if payment.status == "Pending":
                payment.status = "Failed"

            webhook_event.processed = True
            webhook_event.processed_at = datetime.utcnow()

            db.commit()

            return {
                "status": "processed",
                "event": event_type,
            }

        # payment.captured
        if payment.status == "Success":
            if payment.razorpay_payment_id == razorpay_payment_id:
                webhook_event.processed = True
                webhook_event.processed_at = datetime.utcnow()
                db.commit()

                return {
                    "status": "already_paid",
                    "event_id": x_razorpay_event_id,
                }

            raise HTTPException(
                status_code=409,
                detail="A different payment has already confirmed this booking.",
            )

        if payment.status != "Pending":
            raise HTTPException(
                status_code=409,
                detail="Payment is not in a pending state.",
            )

        booking = (
            db.query(Booking)
            .options(joinedload(Booking.booked_seats))
            .filter(Booking.id == payment.booking_id)
            .with_for_update()
            .first()
        )

        if booking is None:
            raise HTTPException(
                status_code=404,
                detail="Booking not found.",
            )

        # Verify the captured amount and currency.
        expected_amount = int(
            payment.amount * 100
        )

        if int(payment_entity.get("amount", 0)) != expected_amount:
            raise HTTPException(
                status_code=400,
                detail="Captured payment amount does not match booking amount.",
            )

        if payment_entity.get("currency") != getattr(
            booking, "currency", "INR"
        ):
            raise HTTPException(
                status_code=400,
                detail="Captured payment currency does not match booking.",
            )

        if payment_entity.get("status") != "captured":
            raise HTTPException(
                status_code=400,
                detail="Razorpay payment is not captured.",
            )

        confirm_booking_after_payment(
            db=db,
            booking=booking,
            payment=payment,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=None,
        )

        webhook_event.processed = True
        webhook_event.processed_at = datetime.utcnow()

        db.commit()

        return {
            "status": "processed",
            "event": event_type,
            "booking_id": booking.id,
        }

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        db.rollback()

        # A concurrent delivery may have inserted this event first.
        duplicate = (
            db.query(RazorpayWebhookEvent)
            .filter(
                RazorpayWebhookEvent.event_id == x_razorpay_event_id
            )
            .first()
        )

        if duplicate and duplicate.processed:
            return {
                "status": "already_processed",
                "event_id": x_razorpay_event_id,
            }

        raise HTTPException(
            status_code=409,
            detail="Webhook processing conflict. Razorpay can retry.",
        )

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Webhook processing failed. Razorpay can retry.",
        ) from exc
