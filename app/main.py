
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.redis_client import check_redis

from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router
from app.routers.venues import router as venues_router
from app.routers.events import router as events_router
from app.routers.seat_locking import router as seat_locking_router
from app.routers.seat_map_ws import router as seat_map_ws_router
from app.routers.bookings import router as bookings_router
from app.routers.payments import router as payments_router
from app.routers.tickets import router as tickets_router

from app.routers import cancellations, waitlist

from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers.reports import router as reports_router
from app.routers.webhooks import router as webhooks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup
    check_redis()
    start_scheduler()

    logging.info("Application startup completed.")

    yield

    # Application shutdown
    stop_scheduler()
    logging.info("Application shutdown completed.")


app = FastAPI(
    title="Event & Movie Ticket Booking System",
    description=(
        "Backend API for event management, movie shows, "
        "seat reservations, payments and QR tickets."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# Register API routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(venues_router)
app.include_router(events_router)
app.include_router(seat_locking_router)
app.include_router(seat_map_ws_router)
app.include_router(bookings_router)
app.include_router(payments_router)
app.include_router(tickets_router)
app.include_router(cancellations.router)
app.include_router(waitlist.router)
app.include_router(reports_router)
app.include_router(webhooks_router)

BASE_DIR = Path(__file__).resolve().parent.parent


@app.get("/", tags=["Health"])
def home():
    return {
        "message": "Event & Movie Ticket Booking API is running"
    }


@app.get("/health", tags=["Health"])
def health():
    try:
        redis_ok = check_redis()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Redis health check failed",
        ) from exc

    return {
        "status": "ok",
        "redis": "connected" if redis_ok else "unavailable",
    }


@app.get("/seat-map-test", include_in_schema=False)
def seat_map_test():
    return FileResponse(
        BASE_DIR / "static" / "seat_map_test.html"
    )
