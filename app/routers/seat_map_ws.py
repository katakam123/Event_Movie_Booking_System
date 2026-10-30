
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from app.auth.security import JWT_SECRET_KEY, JWT_ALGORITHM
from app.database import SessionLocal
from app.models.user import User
from app.websockets.seat_map import (
    read_show_seats,
    seat_map_manager,
)

router = APIRouter(tags=["Live Seat Map"])


def get_websocket_user(token: str):
    """Validate the JWT and return an active database user."""
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        subject = payload.get("sub")

        if subject is None:
            return None

        user_id = int(subject)

    except (JWTError, ValueError, TypeError):
        return None

    db = SessionLocal()

    try:
        user = db.query(User).filter(User.id == user_id).first()

        if user is None or not user.is_active:
            return None

        return {"id": user.id, "role": user.role}

    finally:
        db.close()


@router.websocket("/ws/shows/{show_id}/seats")
async def live_seat_map(websocket: WebSocket, show_id: int):
    token = websocket.query_params.get("token")
    user = get_websocket_user(token)

    if user is None:
        await websocket.close(code=1008, reason="Invalid access token")
        return

    try:
        snapshot = read_show_seats(show_id)
    except Exception:
        await websocket.close(code=1011, reason="Unable to load seat map")
        return

    if not snapshot["exists"]:
        await websocket.close(code=1008, reason="Show not found")
        return

    await websocket.accept()
    seat_map_manager.add(show_id, websocket, user["id"])

    try:
        # The initial full map must be the first application message.
        await seat_map_manager.send_initial_map(
            show_id, websocket, user["id"]
        )
        seat_map_manager.start_monitor(show_id)

        # Keep the connection alive. The browser can send a ping message.
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        seat_map_manager.remove(show_id, websocket)
