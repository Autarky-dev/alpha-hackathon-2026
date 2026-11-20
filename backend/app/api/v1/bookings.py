"""
backend/app/api/v1/bookings.py
------------------------------
FastAPI endpoints for confirming holds, managing bookings, cancellations,
QR ticket issuance, and gate check-in.

Endpoints:
  - POST /holds/{hold_id}/confirm        : Confirm active hold into permanent booking
  - GET  /bookings/me                    : List current user's bookings
  - GET  /bookings/{booking_id}          : View specific booking details
  - POST /bookings/{booking_id}/cancel   : Cancel booking and release seats
  - GET  /bookings/{booking_id}/ticket   : Retrieve signed QR ticket token
  - POST /bookings/{booking_id}/check-in : Venue gate check-in by booking ID
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.booking import BookingResponse, CancelBookingResponse
from app.schemas.checkin import CheckInRequest, CheckInResponse, TicketTokenResponse
from app.services import booking_service, checkin_service

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. Hold Confirmation
# ---------------------------------------------------------------------------

@router.post(
    "/holds/{hold_id}/confirm",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm seat hold",
    description="Atomically converts an active, unexpired hold into a confirmed booking.",
)
def confirm_hold(
    hold_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = booking_service.confirm_hold(
        db=db,
        user_id=current_user.id,
        hold_id=hold_id,
    )
    seat_numbers = [bs.seat.seat_number for bs in booking.booking_seats]
    return BookingResponse(
        id=booking.id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        status=booking.status,
        created_at=booking.created_at,
        seat_numbers=seat_numbers,
        event_title=booking.event.title if booking.event else None,
        checked_in_at=booking.checked_in_at,
    )


# ---------------------------------------------------------------------------
# 2. Booking Management
# ---------------------------------------------------------------------------

@router.get(
    "/bookings/me",
    response_model=list[BookingResponse],
    summary="List my bookings",
    description="Returns all confirmed and cancelled bookings made by the authenticated user.",
)
def list_my_bookings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bookings = booking_service.list_my_bookings(db, user_id=current_user.id)
    results = []
    for b in bookings:
        seat_numbers = [bs.seat.seat_number for bs in b.booking_seats]
        results.append(
            BookingResponse(
                id=b.id,
                event_id=b.event_id,
                user_id=b.user_id,
                status=b.status,
                created_at=b.created_at,
                seat_numbers=seat_numbers,
                event_title=b.event.title if b.event else None,
                checked_in_at=b.checked_in_at,
            )
        )
    return results


@router.get(
    "/bookings/{booking_id}",
    response_model=BookingResponse,
    summary="Get booking details",
    description="View specific booking details. Non-admin users can only view their own bookings.",
)
def get_booking(
    booking_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin_or_org = current_user.role in [UserRole.ADMIN, UserRole.ORGANIZER]
    booking = booking_service.get_booking_details(
        db=db,
        user_id=current_user.id,
        booking_id=booking_id,
        is_admin_or_organizer=is_admin_or_org,
    )
    seat_numbers = [bs.seat.seat_number for bs in booking.booking_seats]
    return BookingResponse(
        id=booking.id,
        event_id=booking.event_id,
        user_id=booking.user_id,
        status=booking.status,
        created_at=booking.created_at,
        seat_numbers=seat_numbers,
        event_title=booking.event.title if booking.event else None,
        checked_in_at=booking.checked_in_at,
    )


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=CancelBookingResponse,
    summary="Cancel booking",
    description="Cancels a confirmed reservation and releases all its seats back to available status.",
)
def cancel_booking(
    booking_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin_or_org = current_user.role in [UserRole.ADMIN, UserRole.ORGANIZER]
    booking = booking_service.cancel_booking(
        db=db,
        user_id=current_user.id,
        booking_id=booking_id,
        is_admin_or_organizer=is_admin_or_org,
    )
    return CancelBookingResponse(
        id=booking.id,
        status=booking.status,
        message="Booking successfully cancelled and seats released",
    )


# ---------------------------------------------------------------------------
# 3. Tickets & Gate Check-In
# ---------------------------------------------------------------------------

@router.get(
    "/bookings/{booking_id}/ticket",
    response_model=TicketTokenResponse,
    summary="Get QR ticket token",
    description="Returns a cryptographically signed, tamper-proof QR ticket code for venue gate check-in.",
)
def get_ticket_qr(
    booking_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin_or_org = current_user.role in [UserRole.ADMIN, UserRole.ORGANIZER]
    booking = booking_service.get_booking_details(
        db=db,
        user_id=current_user.id,
        booking_id=booking_id,
        is_admin_or_organizer=is_admin_or_org,
    )
    token = checkin_service.generate_ticket_qr_token(booking.id, booking.event_id)
    return TicketTokenResponse(booking_id=booking.id, ticket_token=token)


@router.post(
    "/bookings/{booking_id}/check-in",
    response_model=CheckInResponse,
    summary="Check in booking directly",
    description="Checks in an attendee by booking ID. Restricted to the organizer who owns the event or admins.",
)
def check_in_by_booking_id(
    booking_id: uuid.UUID,
    request: CheckInRequest | None = None,
    current_user: User = Depends(require_roles(UserRole.ORGANIZER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    seat_nums = request.seat_numbers if request else None
    return checkin_service.check_in_booking(
        db=db,
        booking_id=booking_id,
        actor=current_user,
        seat_numbers=seat_nums,
    )
