
from datetime import datetime, timedelta, date, time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.event import Event, Show, SeatCategoryPrice
from app.models.venue import Screen, Seat, Venue
from app.models.booking import Booking
from app.auth.security import require_roles

from app.schemas.event import (
    EventCreate,
    EventUpdate,
    EventResponse,
    ShowCreate,
    ShowUpdate,
    ShowResponse,
    ShowWithPrices,
)

from app.utils.redis_controls import (
    get_cached_json,
    set_cached_json,
    invalidate_event_cache,
)


router = APIRouter(tags=["Events and Shows"])

organizer_only = require_roles("organizer")


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def get_event_or_404(db: Session, event_id: int) -> Event:

    event = (
        db.query(Event)
        .filter(Event.id == event_id)
        .first()
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
        )

    return event


def get_show_or_404(db: Session, show_id: int) -> Show:

    show = (
        db.query(Show)
        .filter(Show.id == show_id)
        .first()
    )

    if show is None:
        raise HTTPException(
            status_code=404,
            detail="Show not found",
        )

    return show


def require_approved_organizer(user: User) -> None:

    if user.role != "organizer":
        raise HTTPException(
            status_code=403,
            detail="Organizer access required",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account is inactive",
        )

    if not user.is_approved:
        raise HTTPException(
            status_code=403,
            detail="Your organizer account has not been approved",
        )


def require_event_owner(event: Event, user: User) -> None:

    if event.organizer_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You can manage only your own events",
        )


def make_show_times(show_date, start_time, duration_minutes):

    starts_at = datetime.combine(
        show_date,
        start_time,
    )

    ends_at = starts_at + timedelta(
        minutes=duration_minutes,
    )

    booking_closes_at = starts_at - timedelta(
        minutes=30,
    )

    if starts_at <= datetime.now():
        raise HTTPException(
            status_code=422,
            detail="Shows must be scheduled for a future date and time",
        )

    return starts_at, ends_at, booking_closes_at


def validate_screen(db: Session, screen_id: int) -> Screen:

    screen = (
        db.query(Screen)
        .filter(Screen.id == screen_id)
        .first()
    )

    if screen is None or not screen.is_active:
        raise HTTPException(
            status_code=404,
            detail="Active screen not found",
        )

    venue = (
        db.query(Venue)
        .filter(Venue.id == screen.venue_id)
        .first()
    )

    if venue is None or not venue.is_active:
        raise HTTPException(
            status_code=409,
            detail="The screen's venue is inactive",
        )

    categories = {
        category
        for (category,) in (
            db.query(Seat.category)
            .filter(
                Seat.screen_id == screen_id,
                Seat.is_active.is_(True),
            )
            .distinct()
            .all()
        )
    }

    if not categories:
        raise HTTPException(
            status_code=409,
            detail="The screen has no active seats",
        )

    return screen


def validate_prices(prices, required_categories):

    supplied = [
        item.category
        for item in prices
    ]

    if len(supplied) != len(set(supplied)):
        raise HTTPException(
            status_code=422,
            detail="Each seat category may be priced only once",
        )

    if set(supplied) != required_categories:
        raise HTTPException(
            status_code=422,
            detail=(
                "Prices must be supplied for exactly these active seat "
                f"categories: {', '.join(sorted(required_categories))}"
            ),
        )


def check_show_overlap(
    db: Session,
    screen_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_show_id: int | None = None,
):

    # Require a 15-minute cleaning gap before and after each show.
    gap_start = starts_at - timedelta(minutes=15)
    gap_end = ends_at + timedelta(minutes=15)

    query = db.query(Show).filter(
        Show.screen_id == screen_id,
        Show.status != "Cancelled",
        Show.starts_at < gap_end,
        Show.ends_at > gap_start,
    )

    if exclude_show_id is not None:
        query = query.filter(
            Show.id != exclude_show_id,
        )

    if query.first():
        raise HTTPException(
            status_code=409,
            detail=(
                "This show conflicts with another show on the same screen. "
                "A 15-minute cleaning gap is required."
            ),
        )


def show_response_with_prices(db: Session, show: Show):

    prices = (
        db.query(SeatCategoryPrice)
        .filter(
            SeatCategoryPrice.show_id == show.id,
        )
        .order_by(SeatCategoryPrice.category)
        .all()
    )

    return ShowWithPrices(
        id=show.id,
        event_id=show.event_id,
        screen_id=show.screen_id,
        starts_at=show.starts_at,
        ends_at=show.ends_at,
        booking_closes_at=show.booking_closes_at,
        status=show.status,
        prices=[
            {
                "category": item.category,
                "price": item.price,
            }
            for item in prices
        ],
    )


# ---------------------------------------------------------
# CREATE EVENT
# ---------------------------------------------------------

@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(organizer_only),
):

    require_approved_organizer(current_user)

    event = Event(
        organizer_id=current_user.id,
        title=data.title,
        category=data.category,
        event_type=data.category.lower(),
        language=data.language,
        description=data.description,
        duration_minutes=data.duration_minutes,
        age_rating=data.age_rating,
        status="Draft",
        is_active=True,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    invalidate_event_cache(event.id)

    return event


# ---------------------------------------------------------
# GET ALL PUBLISHED EVENTS
# SEARCH, FILTER, SORT AND PAGINATION
# ---------------------------------------------------------

@router.get(
    "/events",
    response_model=list[EventResponse],
)
def list_published_events(
    title: str | None = Query(
        None,
        description="Search event title using partial matching",
    ),

    city: str | None = Query(
        None,
        description="Filter by venue city",
    ),

    category: str | None = Query(
        None,
        description="Filter by event category",
    ),

    language: str | None = Query(
        None,
        description="Filter by event language",
    ),

    from_date: date | None = Query(
        None,
        description="Filter shows from this date",
    ),

    to_date: date | None = Query(
        None,
        description="Filter shows until this date",
    ),

    min_price: Decimal | None = Query(
        None,
        ge=0,
        description="Minimum ticket price",
    ),

    max_price: Decimal | None = Query(
        None,
        ge=0,
        description="Maximum ticket price",
    ),

    skip: int = Query(
        0,
        ge=0,
        description="Number of records to skip",
    ),

    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Maximum number of records to return",
    ),

    sort_by: str = Query(
        "title",
        pattern="^(title|show_date|price)$",
        description="Sort by title, show_date, or price",
    ),

    order: str = Query(
        "asc",
        pattern="^(asc|desc)$",
        description="Sort order: asc or desc",
    ),

    db: Session = Depends(get_db),
):

    # Validate date range.
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="from_date cannot be later than to_date",
        )

    # Validate price range.
    if (
        min_price is not None
        and max_price is not None
        and min_price > max_price
    ):
        raise HTTPException(
            status_code=422,
            detail="min_price cannot be greater than max_price",
        )

    # Start with published and active events.
    query = db.query(Event).filter(
        Event.status == "Published",
        Event.is_active.is_(True),
    )

    # -----------------------------------------------------
    # TITLE SEARCH
    # -----------------------------------------------------

    if title:
        query = query.filter(
            Event.title.ilike(f"%{title.strip()}%"),
        )

    # -----------------------------------------------------
    # CATEGORY FILTER
    # -----------------------------------------------------

    if category:
        query = query.filter(
            Event.category.ilike(category.strip()),
        )

    # -----------------------------------------------------
    # LANGUAGE FILTER
    # -----------------------------------------------------

    if language:
        query = query.filter(
            Event.language.ilike(language.strip()),
        )

    # -----------------------------------------------------
    # CITY FILTER
    # Show -> Screen -> Venue
    # -----------------------------------------------------

    if city:

        city_subquery = (
            db.query(Show.id)
            .join(
                Screen,
                Show.screen_id == Screen.id,
            )
            .join(
                Venue,
                Screen.venue_id == Venue.id,
            )
            .filter(
                Show.event_id == Event.id,
                Venue.city.ilike(f"%{city.strip()}%"),
            )
            .exists()
        )

        query = query.filter(city_subquery)

    # -----------------------------------------------------
    # DATE RANGE FILTER
    # -----------------------------------------------------

    if from_date or to_date:

        date_subquery = db.query(Show.id).filter(
            Show.event_id == Event.id,
            Show.status == "Scheduled",
        )

        if from_date:
            date_subquery = date_subquery.filter(
                Show.starts_at >= datetime.combine(
                    from_date,
                    time.min,
                ),
            )

        if to_date:
            date_subquery = date_subquery.filter(
                Show.starts_at < datetime.combine(
                    to_date + timedelta(days=1),
                    time.min,
                ),
            )

        query = query.filter(
            date_subquery.exists(),
        )

    # -----------------------------------------------------
    # PRICE RANGE FILTER
    # -----------------------------------------------------

    if min_price is not None or max_price is not None:

        price_subquery = (
            db.query(SeatCategoryPrice.show_id)
            .join(
                Show,
                Show.id == SeatCategoryPrice.show_id,
            )
            .filter(
                Show.event_id == Event.id,
                Show.status == "Scheduled",
            )
        )

        if min_price is not None:
            price_subquery = price_subquery.filter(
                SeatCategoryPrice.price >= min_price,
            )

        if max_price is not None:
            price_subquery = price_subquery.filter(
                SeatCategoryPrice.price <= max_price,
            )

        query = query.filter(
            price_subquery.exists(),
        )

    # -----------------------------------------------------
    # SORTING SUBQUERIES
    # -----------------------------------------------------

    first_show_date = (
        db.query(func.min(Show.starts_at))
        .filter(
            Show.event_id == Event.id,
            Show.status == "Scheduled",
        )
        .correlate(Event)
        .scalar_subquery()
    )

    lowest_price = (
        db.query(func.min(SeatCategoryPrice.price))
        .join(
            Show,
            Show.id == SeatCategoryPrice.show_id,
        )
        .filter(
            Show.event_id == Event.id,
            Show.status == "Scheduled",
        )
        .correlate(Event)
        .scalar_subquery()
    )

    # Choose the sorting column.
    if sort_by == "title":
        sort_expression = Event.title

    elif sort_by == "show_date":
        sort_expression = first_show_date

    else:
        sort_expression = lowest_price

    # Apply sorting direction.
    if order == "desc":
        query = query.order_by(
            sort_expression.desc(),
            Event.id.desc(),
        )

    else:
        query = query.order_by(
            sort_expression.asc(),
            Event.id.asc(),
        )

    # -----------------------------------------------------
    # PAGINATION
    # -----------------------------------------------------

    events = (
        query
        .offset(skip)
        .limit(limit)
        .all()
    )

    return events


# ---------------------------------------------------------
# GET SINGLE EVENT - REDIS CACHE
# ---------------------------------------------------------

@router.get(
    "/events/{event_id}",
    response_model=EventResponse,
)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
):

    cache_key = f"events:detail:{event_id}"

    cached_event = get_cached_json(cache_key)

    if cached_event is not None:
        return cached_event

    event = get_event_or_404(
        db,
        event_id,
    )

    if event.status != "Published" or not event.is_active:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
        )

    set_cached_json(
        cache_key,
        event,
        ttl=300,
    )

    return event


# ---------------------------------------------------------
# UPDATE EVENT
# ---------------------------------------------------------

@router.put(
    "/events/{event_id}",
    response_model=EventResponse,
)
def update_event(
    event_id: int,
    data: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(organizer_only),
):

    require_approved_organizer(current_user)

    event = get_event_or_404(
        db,
        event_id,
    )

    require_event_owner(
        event,
        current_user,
    )

    changes = data.model_dump(
        exclude_unset=True,
    )

    new_duration = changes.get("duration_minutes")

    if (
        new_duration is not None
        and new_duration != event.duration_minutes
    ):

        has_future_shows = (
            db.query(Show)
            .filter(
                Show.event_id == event.id,
                Show.status == "Scheduled",
                Show.starts_at > datetime.now(),
            )
            .first()
        )

        if has_future_shows:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cancel or reschedule future shows before changing "
                    "the event duration"
                ),
            )

    for field, value in changes.items():
        setattr(event, field, value)

    if "category" in changes:
        event.event_type = changes["category"].lower()

    db.commit()
    db.refresh(event)

    invalidate_event_cache(event.id)

    return event


# ---------------------------------------------------------
# CREATE SHOW
# ---------------------------------------------------------

@router.post(
    "/events/{event_id}/shows",
    response_model=ShowWithPrices,
    status_code=status.HTTP_201_CREATED,
)
def create_show(
    event_id: int,
    data: ShowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(organizer_only),
):

    require_approved_organizer(current_user)

    event = get_event_or_404(
        db,
        event_id,
    )

    require_event_owner(
        event,
        current_user,
    )

    if event.status != "Published" or not event.is_active:
        raise HTTPException(
            status_code=409,
            detail="Publish the event before scheduling a show",
        )

    screen = validate_screen(
        db,
        data.screen_id,
    )

    active_categories = {
        category
        for (category,) in (
            db.query(Seat.category)
            .filter(
                Seat.screen_id == screen.id,
                Seat.is_active.is_(True),
            )
            .distinct()
            .all()
        )
    }

    validate_prices(
        data.prices,
        active_categories,
    )

    starts_at, ends_at, booking_closes_at = make_show_times(
        data.show_date,
        data.start_time,
        event.duration_minutes,
    )

    check_show_overlap(
        db,
        screen.id,
        starts_at,
        ends_at,
    )

    show = Show(
        event_id=event.id,
        screen_id=screen.id,
        starts_at=starts_at,
        ends_at=ends_at,
        booking_closes_at=booking_closes_at,
        status="Scheduled",
        is_active=True,
    )

    db.add(show)
    db.flush()

    for price_input in data.prices:

        db.add(
            SeatCategoryPrice(
                show_id=show.id,
                category=price_input.category,
                price=Decimal(str(price_input.price)),
            )
        )

    db.commit()
    db.refresh(show)

    invalidate_event_cache(event.id)

    return show_response_with_prices(
        db,
        show,
    )


# ---------------------------------------------------------
# GET SHOWS FOR AN EVENT
# PAGINATION INCLUDED
# ---------------------------------------------------------

@router.get(
    "/events/{event_id}/shows",
    response_model=list[ShowWithPrices],
)
def list_event_shows(
    event_id: int,

    skip: int = Query(
        0,
        ge=0,
        description="Number of shows to skip",
    ),

    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Maximum shows to return",
    ),

    db: Session = Depends(get_db),
):

    event = get_event_or_404(
        db,
        event_id,
    )

    if event.status != "Published" or not event.is_active:
        raise HTTPException(
            status_code=404,
            detail="Event not found",
        )

    shows = (
        db.query(Show)
        .filter(
            Show.event_id == event_id,
            Show.status == "Scheduled",
            Show.starts_at > datetime.now(),
        )
        .order_by(Show.starts_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        show_response_with_prices(db, show)
        for show in shows
    ]


# ---------------------------------------------------------
# UPDATE SHOW
# ---------------------------------------------------------

@router.put(
    "/shows/{show_id}",
    response_model=ShowWithPrices,
)
def update_show(
    show_id: int,
    data: ShowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(organizer_only),
):

    require_approved_organizer(current_user)

    show = get_show_or_404(
        db,
        show_id,
    )

    event = get_event_or_404(
        db,
        show.event_id,
    )

    require_event_owner(
        event,
        current_user,
    )

    if show.status != "Scheduled":
        raise HTTPException(
            status_code=409,
            detail="Only scheduled shows can be updated",
        )

    changes = data.model_dump(
        exclude_unset=True,
    )

    if changes.get("status") in {"Cancelled", "Completed"}:
        raise HTTPException(
            status_code=422,
            detail="Use PUT /shows/{show_id}/cancel to cancel a show",
        )

    if "prices" in changes and changes["prices"] is not None:

        confirmed_booking = (
            db.query(Booking)
            .filter(
                Booking.show_id == show.id,
                Booking.status == "Confirmed",
            )
            .first()
        )

        if confirmed_booking:
            raise HTTPException(
                status_code=409,
                detail="Show prices cannot change after a confirmed booking",
            )

        active_categories = {
            category
            for (category,) in (
                db.query(Seat.category)
                .filter(
                    Seat.screen_id == show.screen_id,
                    Seat.is_active.is_(True),
                )
                .distinct()
                .all()
            )
        }

        validate_prices(
            changes["prices"],
            active_categories,
        )

    new_date = changes.get(
        "show_date",
        show.starts_at.date(),
    )

    new_time = changes.get(
        "start_time",
        show.starts_at.time(),
    )

    starts_at, ends_at, booking_closes_at = make_show_times(
        new_date,
        new_time,
        event.duration_minutes,
    )

    check_show_overlap(
        db,
        show.screen_id,
        starts_at,
        ends_at,
        exclude_show_id=show.id,
    )

    show.starts_at = starts_at
    show.ends_at = ends_at
    show.booking_closes_at = booking_closes_at

    if "prices" in changes and changes["prices"] is not None:

        db.query(SeatCategoryPrice).filter(
            SeatCategoryPrice.show_id == show.id,
        ).delete(
            synchronize_session=False,
        )

        for price_input in changes["prices"]:

            db.add(
                SeatCategoryPrice(
                    show_id=show.id,
                    category=price_input["category"],
                    price=Decimal(str(price_input["price"])),
                )
            )

    db.commit()
    db.refresh(show)

    invalidate_event_cache(show.event_id)

    return show_response_with_prices(
        db,
        show,
    )


# ---------------------------------------------------------
# CANCEL SHOW
# ---------------------------------------------------------

@router.put(
    "/shows/{show_id}/cancel",
    response_model=ShowResponse,
)
def cancel_show(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(organizer_only),
):

    require_approved_organizer(current_user)

    show = get_show_or_404(
        db,
        show_id,
    )

    event = get_event_or_404(
        db,
        show.event_id,
    )

    require_event_owner(
        event,
        current_user,
    )

    if show.status != "Scheduled":
        raise HTTPException(
            status_code=409,
            detail="Only scheduled shows can be cancelled",
        )

    show.status = "Cancelled"
    show.is_active = False

    db.commit()
    db.refresh(show)

    invalidate_event_cache(show.event_id)

    return show
