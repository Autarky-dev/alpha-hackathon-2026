"""
backend/app/api/v1/events.py
----------------------------
FastAPI endpoints for Event management, Seat Map retrieval, Seat Holds,
Attendee Manifests, and Venue Check-In.

Endpoints:
  - GET  /events                     : List events
  - POST /events                     : Create event with ownership (Organizer / Admin)
  - GET  /events/organizer/mine      : List events owned by current organizer
  - GET  /events/{event_id}          : Event details
  - PUT  /events/{event_id}          : Update event with OCC and ownership check
  - GET  /events/{event_id}/seats    : Venue seat map with real-time availability
  - POST /events/{event_id}/hold     : Hold 1-4 seats for 5 minutes (Student / User)
  - GET  /events/{event_id}/attendees: Attendee manifest & metrics (Owner / Admin)
  - POST /events/{event_id}/check-in : Venue gate check-in via QR or booking ID
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.booking import HoldCreateRequest, HoldResponse, SeatMapResponse
from app.schemas.checkin import CheckInRequest, CheckInResponse, EventAttendeesResponse
from app.schemas.event import EventCreate, EventResponse, EventUpdate
from app.services import booking_service, checkin_service, event_service

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. Event Catalog & Administration
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=list[EventResponse],
    summary="List all events",
    description="Returns upcoming and active events ordered by start time.",
)
def list_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return event_service.list_events(db, skip=skip, limit=limit)


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create event",
    description="Creates a new event, sets ownership to creator, and initializes venue seats. Requires ORGANIZER or ADMIN role.",
)
def create_event(
    event_data: EventCreate,
    current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    return event_service.create_event(db, event_data, creator=current_user)


@router.get(
    "/organizer/mine",
    response_model=list[EventResponse],
    summary="List organizer's events",
    description="Returns events owned by the authenticated organizer (or all events for admins).",
)
def list_my_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    is_admin = current_user.role == UserRole.ADMIN
    return event_service.list_organizer_events(
        db=db,
        organizer_id=current_user.id,
        is_admin=is_admin,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="Get event details",
)
def get_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    return event_service.get_event_by_id(db, event_id)


@router.put(
    "/{event_id}",
    response_model=EventResponse,
    summary="Update event (Optimistic Locking & Ownership)",
    description="Updates event info. Enforces optimistic concurrency control and organizer ownership.",
)
def update_event(
    event_id: uuid.UUID,
    event_data: EventUpdate,
    current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    return event_service.update_event(db, event_id, event_data, actor=current_user)


# ---------------------------------------------------------------------------
# 2. Seat Map & Seat Holds
# ---------------------------------------------------------------------------

@router.get(
    "/{event_id}/seats",
    response_model=SeatMapResponse,
    summary="Get venue seat map",
    description="Returns the full seat map with real-time status (available, held, booked). Reconciles expired holds automatically.",
)
def get_seat_map(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    # Optional authentication to mark seats currently held by calling user
    current_user: Optional[User] = Depends(lambda: None),
):
    user_id = current_user.id if current_user else None
    return booking_service.get_seat_map(db, event_id, current_user_id=user_id)


@router.post(
    "/{event_id}/hold",
    response_model=HoldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Hold 1-4 seats",
    description="Acquires a 5-minute temporary hold on up to 4 seats. Atomically replaces any previous active hold for this student.",
)
def hold_seats(
    event_id: uuid.UUID,
    request: HoldCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hold = booking_service.hold_seats(
        db=db,
        user_id=current_user.id,
        event_id=event_id,
        seat_numbers=request.seat_numbers,
    )
    seat_numbers = [hs.seat.seat_number for hs in hold.hold_seats]
    return HoldResponse(
        id=hold.id,
        event_id=hold.event_id,
        user_id=hold.user_id,
        expires_at=hold.expires_at,
        seat_numbers=seat_numbers,
        message="Seats successfully held for 5 minutes",
    )


# ---------------------------------------------------------------------------
# 3. Organizer Check-In Operations & Manifest
# ---------------------------------------------------------------------------

@router.get(
    "/{event_id}/attendees",
    response_model=EventAttendeesResponse,
    summary="Get event attendee manifest",
    description="Returns attendee manifest and check-in counts. Restricted to the organizer who owns the event or admins.",
)
def get_event_attendees(
    event_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    return checkin_service.get_event_attendees(db=db, event_id=event_id, actor=current_user)


@router.post(
    "/{event_id}/check-in",
    response_model=CheckInResponse,
    summary="Check in attendee at venue gate",
    description="Validates ticket QR token or booking ID, prevents duplicate entry, and marks attendee as checked in.",
)
def check_in_attendee(
    event_id: uuid.UUID,
    request: CheckInRequest,
    current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    booking_id = request.booking_id
    if request.qr_token:
        token_bid, token_eid = checkin_service.decode_ticket_qr_token(request.qr_token)
        if token_eid != event_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ticket QR token was issued for a different event.",
            )
        booking_id = token_bid

    if not booking_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either booking_id or qr_token must be provided for check-in.",
        )

    return checkin_service.check_in_booking(
        db=db,
        booking_id=booking_id,
        actor=current_user,
        event_id=event_id,
        seat_numbers=request.seat_numbers,
    )
