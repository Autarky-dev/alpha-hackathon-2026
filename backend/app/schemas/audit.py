"""
backend/app/schemas/audit.py
----------------------------
Pydantic schemas for querying structured, sharded audit logs.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class AuditLogEntry(BaseModel):
    """A single audit log entry returned from a shard."""
    id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None
    event_id: uuid.UUID | None = None
    action: str
    details: dict | None = None
    created_at: datetime
    shard_id: int

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """Paginated response containing audit log records."""
    total: int
    limit: int
    offset: int
    entries: list[AuditLogEntry]
