
import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket
from sqlalchemy import func

from app.database import SessionLocal
from app.models.booking import Booking, BookedSeat
from app.models.event import Show, SeatCategoryPrice
from app.models.venue import Seat, Screen
from app.redis_client import redis_client


LOCK_KEY_PREFIX = "lock:show:{show_id}:seat:"
BOOKED_STATUSES = {"confirmed", "paid", "completed"}


def get_lock_key(show_id: int, seat_id: int) -> str:
    return LOCK_KEY_PREFIX.format(show_id=show_id) + str(seat_id)


def read_show_seats(show_id: int) -> dict[str, Any]:
    """Read current seat state from MySQL and Redis."""
    db = SessionLocal()

    try:
        show = db.query(Show).filter(Show.id == show_id).first()

        if show is None:
            return {"exists": False, "seats": {}}

        screen = db.query(Screen).filter(
            Screen.id == show.screen_id
        ).first()

        if screen is None:
            return {"exists": False, "seats": {}}

        seats = (
            db.query(Seat)
            .filter(Seat.screen_id == screen.id)
            .order_by(Seat.row_label, Seat.seat_number)
            .all()
        )

        prices = {
            price.category: float(price.price)
            for price in db.query(SeatCategoryPrice)
            .filter(SeatCategoryPrice.show_id == show_id)
            .all()
        }

        booked_ids = {
            seat_id
            for (seat_id,) in (
                db.query(BookedSeat.seat_id)
                .join(Booking, Booking.id == BookedSeat.booking_id)
                .filter(
                    BookedSeat.show_id == show_id,
                    func.lower(Booking.status).in_(BOOKED_STATUSES),
                )
                .all()
            )
        }

        # Redis returns only keys that still exist, so expired locks
        # disappear automatically from this snapshot.
        lock_owners = {}
        pattern = f"lock:show:{show_id}:seat:*"

        for key in redis_client.scan_iter(match=pattern):
            seat_id_text = key.rsplit(":", 1)[-1]
            owner_id = redis_client.get(key)

            if owner_id is not None:
                try:
                    lock_owners[int(seat_id_text)] = int(owner_id)
                except ValueError:
                    continue

        show_unavailable = (
            not show.is_active
            or show.status != "Scheduled"
        )

        result = {}

        for seat in seats:
            owner_id = lock_owners.get(seat.id)

            if show_unavailable or not seat.is_active:
                status = "Unavailable"
            elif seat.id in booked_ids:
                status = "Booked"
                owner_id = None
            elif owner_id is not None:
                status = "Locked"
            else:
                status = "Available"

            result[seat.id] = {
                "seat_id": seat.id,
                "row_label": seat.row_label,
                "seat_number": seat.seat_number,
                "category": seat.category,
                "price": prices.get(seat.category),
                "status": status,
                "owner_id": owner_id,
            }

        return {
            "exists": True,
            "show_status": show.status,
            "seats": result,
        }

    finally:
        db.close()


def client_seat(seat: dict, user_id: int) -> dict:
    """Never expose another customer's ID to WebSocket clients."""
    result = {
        key: value
        for key, value in seat.items()
        if key != "owner_id"
    }

    if seat["status"] == "Locked" and seat["owner_id"] == user_id:
        result["status"] = "Yours"

    return result


def seat_label(seat: dict) -> str:
    return f"{seat['row_label']}{seat['seat_number']}"


def describe_change(old: dict, new: dict) -> str:
    label = seat_label(new)

    if new["status"] == "Booked":
        return f"Seat {label} is now Booked"

    if new["status"] == "Locked":
        return f"Seat {label} is now Locked"

    if new["status"] == "Unavailable":
        return f"Seat {label} is now Unavailable"

    if old["status"] == "Booked":
        return f"Seat {label} is now Available after a booking change"

    if old["status"] == "Locked":
        return f"Seat {label} is now Available; its lock was released or expired"

    return f"Seat {label} is now Available"


class SeatMapManager:
    def __init__(self):
        self.connections = defaultdict(dict)
        self.monitor_tasks = {}
        self.previous_states = {}

    def add(self, show_id: int, websocket: WebSocket, user_id: int):
        self.connections[show_id][websocket] = user_id

    def remove(self, show_id: int, websocket: WebSocket):
        self.connections[show_id].pop(websocket, None)

        if not self.connections[show_id]:
            self.connections.pop(show_id, None)

            task = self.monitor_tasks.pop(show_id, None)
            if task and not task.done():
                task.cancel()

            self.previous_states.pop(show_id, None)

    async def send_initial_map(
        self, show_id: int, websocket: WebSocket, user_id: int
    ):
        snapshot = read_show_seats(show_id)

        if not snapshot["exists"]:
            await websocket.send_json({
                "type": "error",
                "message": "Show or screen not found",
            })
            return

        seats = [
            client_seat(seat, user_id)
            for seat in snapshot["seats"].values()
        ]

        await websocket.send_json({
            "type": "seat_map",
            "show_id": show_id,
            "show_status": snapshot["show_status"],
            "seats": seats,
        })

    async def broadcast_changes(self, show_id: int):
        """Poll the authoritative state to detect locks, expiry and bookings."""
        try:
            while self.connections.get(show_id):
                snapshot = read_show_seats(show_id)

                if not snapshot["exists"]:
                    break

                current = snapshot["seats"]
                previous = self.previous_states.get(show_id)

                if previous is not None:
                    changed_ids = set(previous) | set(current)

                    for seat_id in sorted(changed_ids):
                        old = previous.get(seat_id)
                        new = current.get(seat_id)

                        if old == new:
                            continue

                        seat_for_message = new or old
                        message = (
                            f"Seat {seat_label(seat_for_message)} "
                            "is no longer present in the seat map"
                            if new is None
                            else describe_change(old or new, new)
                        )

                        for websocket, user_id in list(
                            self.connections.get(show_id, {}).items()
                        ):
                            payload = {
                                "type": "seat_update",
                                "show_id": show_id,
                                "message": message,
                                "seat": (
                                    client_seat(new, user_id)
                                    if new is not None
                                    else None
                                ),
                            }

                            try:
                                await websocket.send_json(payload)
                            except Exception:
                                self.remove(show_id, websocket)

                self.previous_states[show_id] = current
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            raise
        except Exception:
            # A transient database/Redis issue should not crash the app.
            await asyncio.sleep(1)

    def start_monitor(self, show_id: int):
        task = self.monitor_tasks.get(show_id)

        if task is None or task.done():
            self.monitor_tasks[show_id] = asyncio.create_task(
                self.broadcast_changes(show_id)
            )


seat_map_manager = SeatMapManager()
