
import os
import secrets
from pathlib import Path

import qrcode


BASE_DIR = Path(__file__).resolve().parents[2]
TICKET_DIR = BASE_DIR / "tickets"


def generate_ticket_token() -> str:
    return secrets.token_urlsafe(32)


def generate_ticket_qr(ticket_token: str) -> str:
    """
    Generate a QR image containing the unique ticket token.
    The gate-scanning API will validate this token later.
    """
    TICKET_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{ticket_token}.png"
    file_path = TICKET_DIR / filename

    image = qrcode.make(ticket_token)
    image.save(file_path)

    return str(file_path)
