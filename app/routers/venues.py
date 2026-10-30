
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.venue import Venue, Screen, Seat
from app.models.user import User
from app.auth.security import get_current_user, require_roles

from app.schemas.venue import (
    VenueCreate,
    VenueUpdate,
    VenueResponse,
    ScreenCreate,
    ScreenResponse,
    BulkSeatCreate,
    SeatStatusUpdate,
    SeatResponse,
    SeatRowResponse,
    ScreenLayoutResponse,
)

router = APIRouter(tags=["Venues and Screens"])

admin_only = require_roles("admin")


# --------------------------------------------------
# CREATE VENUE
# --------------------------------------------------

@router.post(
    "/venues",
    response_model=VenueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_venue(
    payload: VenueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    venue = Venue(**payload.model_dump())

    db.add(venue)

    try:
        db.commit()
        db.refresh(venue)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Unable to create venue.",
        )

    return venue


# --------------------------------------------------
# GET ALL VENUES WITH PAGINATION
# --------------------------------------------------

@router.get("/venues", response_model=list[VenueResponse])
def list_venues(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return (
        db.query(Venue)
        .filter(Venue.is_active.is_(True))
        .order_by(Venue.name)
        .offset(skip)
        .limit(limit)
        .all()
    )


# --------------------------------------------------
# GET VENUE BY ID
# --------------------------------------------------

@router.get("/venues/{venue_id}", response_model=VenueResponse)
def get_venue(
    venue_id: int,
    db: Session = Depends(get_db),
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found.",
        )

    return venue


# --------------------------------------------------
# UPDATE VENUE
# --------------------------------------------------

@router.put("/venues/{venue_id}", response_model=VenueResponse)
def update_venue(
    venue_id: int,
    payload: VenueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(venue, key, value)

    db.commit()
    db.refresh(venue)

    return venue


# --------------------------------------------------
# CREATE SCREEN
# --------------------------------------------------

@router.post(
    "/venues/{venue_id}/screens",
    response_model=ScreenResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_screen(
    venue_id: int,
    payload: ScreenCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found.",
        )

    screen = Screen(
        venue_id=venue_id,
        **payload.model_dump(),
    )

    db.add(screen)

    try:
        db.commit()
        db.refresh(screen)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Screen with this name already exists in this venue.",
        )

    return screen


# --------------------------------------------------
# GET SCREENS FOR A VENUE
# --------------------------------------------------

@router.get(
    "/venues/{venue_id}/screens",
    response_model=list[ScreenResponse],
)
def list_screens(
    venue_id: int,
    db: Session = Depends(get_db),
):
    venue = db.query(Venue).filter(Venue.id == venue_id).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found.",
        )

    return (
        db.query(Screen)
        .filter(
            Screen.venue_id == venue_id,
            Screen.is_active.is_(True),
        )
        .order_by(Screen.name)
        .all()
    )


# --------------------------------------------------
# BULK CREATE SEATS
# --------------------------------------------------

@router.post(
    "/screens/{screen_id}/seats/bulk",
    status_code=status.HTTP_201_CREATED,
)
def bulk_create_seats(
    screen_id: int,
    payload: BulkSeatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    screen = db.query(Screen).filter(Screen.id == screen_id).first()

    if not screen:
        raise HTTPException(
            status_code=404,
            detail="Screen not found.",
        )

    seats = []

    for seat_data in payload.seats:
        seats.append(
            Seat(
                screen_id=screen_id,
                **seat_data.model_dump(),
            )
        )

    db.add_all(seats)

    try:
        db.flush()

        screen.total_seats = (
            db.query(func.count(Seat.id))
            .filter(
                Seat.screen_id == screen_id,
                Seat.is_active.is_(True),
            )
            .scalar()
        )

        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Duplicate seat or invalid seat data.",
        )

    return {
        "message": "Seats created successfully.",
        "total_created": len(seats),
    }


# --------------------------------------------------
# GET SEATS FOR A SCREEN
# --------------------------------------------------

@router.get(
    "/screens/{screen_id}/seats",
    response_model=list[SeatResponse],
)
def list_seats(
    screen_id: int,
    db: Session = Depends(get_db),
):
    screen = db.query(Screen).filter(Screen.id == screen_id).first()

    if not screen:
        raise HTTPException(
            status_code=404,
            detail="Screen not found.",
        )

    return (
        db.query(Seat)
        .filter(
            Seat.screen_id == screen_id,
            Seat.is_active.is_(True),
        )
        .order_by(Seat.row_label, Seat.seat_number)
        .all()
    )


# --------------------------------------------------
# UPDATE SEAT STATUS
# --------------------------------------------------

@router.patch(
    "/seats/{seat_id}/status",
    response_model=SeatResponse,
)
def update_seat_status(
    seat_id: int,
    payload: SeatStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    seat = db.query(Seat).filter(Seat.id == seat_id).first()

    if not seat:
        raise HTTPException(
            status_code=404,
            detail="Seat not found.",
        )

    seat.is_active = payload.is_active

    db.commit()
    db.refresh(seat)

    return seat


# --------------------------------------------------
# GET SCREEN LAYOUT
# --------------------------------------------------

@router.get(
    "/screens/{screen_id}/layout",
    response_model=ScreenLayoutResponse,
)
def get_screen_layout(
    screen_id: int,
    db: Session = Depends(get_db),
):
    screen = db.query(Screen).filter(Screen.id == screen_id).first()

    if not screen:
        raise HTTPException(
            status_code=404,
            detail="Screen not found.",
        )

    seats = (
        db.query(Seat)
        .filter(
            Seat.screen_id == screen_id,
            Seat.is_active.is_(True),
        )
        .order_by(Seat.row_label, Seat.seat_number)
        .all()
    )

    grouped_seats = defaultdict(list)

    for seat in seats:
        grouped_seats[seat.row_label].append(seat)

    rows = [
        SeatRowResponse(
            row_label=row_label,
            seats=row_seats,
        )
        for row_label, row_seats in sorted(grouped_seats.items())
    ]

    return ScreenLayoutResponse(
        screen_id=screen.id,
        screen_name=screen.name,
        total_seats=len(seats),
        rows=rows,
    )
