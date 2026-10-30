
from io import BytesIO
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from app.utils.ticket_qr import create_signed_ticket


BASE_DIR = Path(__file__).resolve().parents[2]
TICKET_DIR = BASE_DIR / "tickets"


def generate_booking_pdf(booking) -> str:
    """
    Generate one PDF ticket for a confirmed booking.
    Returns the PDF file path.
    """
    if booking.status != "Confirmed":
        raise ValueError("Only confirmed bookings can generate tickets.")

    TICKET_DIR.mkdir(parents=True, exist_ok=True)

    show = booking.show
    event = show.event
    screen = show.screen
    venue = screen.venue

    qr_payload = create_signed_ticket(booking.booking_number)

    qr_image = qrcode.make(qr_payload)
    qr_buffer = BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    filename = f"{booking.booking_number}.pdf"
    file_path = TICKET_DIR / filename

    pdf = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4

    pdf.setTitle(f"Ticket {booking.booking_number}")

    pdf.setFillColor(colors.HexColor("#172554"))
    pdf.rect(0, height - 48 * mm, width, 48 * mm, fill=1, stroke=0)

    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(20 * mm, height - 23 * mm, "EVENT TICKET")

    pdf.setFont("Helvetica", 11)
    pdf.drawString(
        20 * mm,
        height - 34 * mm,
        f"Booking: {booking.booking_number}",
    )

    y = height - 65 * mm

    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawString(20 * mm, y, event.title)

    y -= 13 * mm

    details = [
        ("Venue", venue.name),
        ("Address", venue.address),
        ("City", venue.city),
        ("Screen", screen.name),
        ("Show date", show.starts_at.strftime("%d-%m-%Y")),
        ("Show time", show.starts_at.strftime("%I:%M %p")),
        ("End time", show.ends_at.strftime("%I:%M %p")),
        ("Customer", booking.customer.name),
        ("Seat count", str(booking.seat_count)),
        (
            "Seats",
            ", ".join(
                f"{item.seat.row_label}{item.seat.seat_number}"
                for item in booking.booked_seats
            ),
        ),
        ("Amount paid", f"INR {booking.grand_total}"),
        ("Payment status", "Confirmed"),
    ]

    pdf.setFont("Helvetica", 10)

    for label, value in details:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(20 * mm, y, f"{label}:")
        pdf.setFont("Helvetica", 10)

        # Avoid drawing extremely long values off the page.
        value = str(value)[:100]
        pdf.drawString(65 * mm, y, value)
        y -= 9 * mm

    qr_x = width - 65 * mm
    qr_y = 25 * mm

    pdf.drawImage(
    ImageReader(qr_buffer),
    qr_x,
    qr_y,
    width=40 * mm,
    height=40 * mm,
)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(20 * mm, 20 * mm, "Present this QR code at the entry gate.")
    pdf.drawString(20 * mm, 15 * mm, "Each booking can be scanned only once.")

    pdf.save()

    return str(file_path)
