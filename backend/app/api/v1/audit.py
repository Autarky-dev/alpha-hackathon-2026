"""
backend/app/api/v1/audit.py
---------------------------
FastAPI router for querying structured, sharded audit logs.

Endpoints:
  - GET /audit-logs : Query audit trail with event, actor, action, and date filters.
    * Direct single-shard execution when event_id is supplied.
    * Multi-shard UNION ALL federation when event_id is None.
    * Admins can query all logs. Organizers are restricted to events they own.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.event import Event
from app.models.user import User, UserRole
from app.schemas.audit import AuditLogEntry, AuditLogListResponse
from app.services import audit_service

router = APIRouter()


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="Query audit logs across shards",
    description=(
        "Retrieves paginated audit log entries. If `event_id` is specified, "
        "only the dedicated shard table is queried. If omitted, entries from all 4 shards "
        "are federated via UNION ALL. Organizers are restricted to events they own."
    ),
)
def get_audit_logs(
    event_id: uuid.UUID | None = Query(None, description="Event ID to target a specific shard"),
    actor_id: uuid.UUID | None = Query(None, description="Filter by actor user ID"),
    action: str | None = Query(None, description="Filter by action name (e.g. SEAT_HOLD, BOOKING_CONFIRMED)"),
    date_from: datetime | None = Query(None, description="Filter entries created after this timestamp"),
    date_to: datetime | None = Query(None, description="Filter entries created before this timestamp"),
    limit: int = Query(50, ge=1, le=500, description="Page limit (default 50)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.ORGANIZER)),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    # 1. Authorization: If Organizer, verify ownership of the requested event
    if current_user.role == UserRole.ORGANIZER:
        if not event_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organizers must supply an event_id to inspect audit logs.",
            )

        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event with id '{event_id}' not found.",
            )

        if event.organizer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized: You can only view audit logs for events you own.",
            )

    # 2. Query logs via audit service
    entries, total = audit_service.query_audit_logs(
        db=db,
        event_id=event_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    return AuditLogListResponse(
        total=total,
        limit=limit,
        offset=offset,
        entries=[AuditLogEntry(**e) for e in entries],
    )
