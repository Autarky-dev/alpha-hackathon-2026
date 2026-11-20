"""
backend/app/services/audit_service.py
-------------------------------------
Audit logging and hash-sharding engine for SeatLock.

Key Design:
  - 4 Shard Tables: audit_logs_0, audit_logs_1, audit_logs_2, audit_logs_3.
  - Shard Routing:
      * Event logs: int(event_id) % 4
      * Non-event logs: int(actor_id) % 4 (or 0 if no actor)
  - Transactional Integrity:
      * Audit log writes join the ongoing transaction when `commit=False`.
  - Filtered Queries:
      * Event-specific queries scan ONLY the single relevant shard table.
      * Unfiltered or multi-event queries combine shards via UNION ALL.
  - Security:
      * Passwords, hashes, and JWT secrets are strictly filtered before write.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models.audit import AuditLog0, AuditLog1, AuditLog2, AuditLog3

# Shard table registry matching shard index 0, 1, 2, 3
SHARDS = [AuditLog0, AuditLog1, AuditLog2, AuditLog3]


def get_shard_index(
    event_id: uuid.UUID | str | None = None,
    actor_id: uuid.UUID | str | None = None,
) -> int:
    """
    Deterministically route log entry to one of 4 shards:
      1. If event_id is present: int(event_id) % 4
      2. If actor_id is present: int(actor_id) % 4
      3. Otherwise: 0
    """
    if event_id:
        val = uuid.UUID(str(event_id)) if not isinstance(event_id, uuid.UUID) else event_id
        return val.int % 4
    if actor_id:
        val = uuid.UUID(str(actor_id)) if not isinstance(actor_id, uuid.UUID) else actor_id
        return val.int % 4
    return 0


def log_audit(
    db: Session,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    event_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> Any:
    """
    Write a structured audit entry into the appropriate shard.
    If commit=False, joins the ongoing database transaction.
    """
    # Sanitize details to guarantee zero credentials or tokens leak
    safe_details = details.copy() if details else {}
    for sensitive_key in [
        "password",
        "password_hash",
        "token",
        "access_token",
        "jwt",
        "secret",
        "authorization",
    ]:
        safe_details.pop(sensitive_key, None)

    shard_idx = get_shard_index(event_id=event_id, actor_id=actor_id)
    ShardModel = SHARDS[shard_idx]

    entry = ShardModel(
        actor_id=actor_id,
        actor_role=actor_role,
        event_id=event_id,
        action=action,
        details=safe_details,
    )
    db.add(entry)

    if commit:
        db.commit()
        db.refresh(entry)

    return entry


def query_audit_logs(
    db: Session,
    event_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Query audit log entries across shards.

    Optimization:
      - If event_id is supplied: Queries ONLY the target shard table directly.
      - If event_id is None: Queries all 4 shards combined via UNION ALL.

    Returns:
      (entries: list[dict], total_count: int)
    """
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    if event_id is not None:
        # SINGLE-SHARD QUERY PATH
        shard_idx = get_shard_index(event_id=event_id)
        Model = SHARDS[shard_idx]

        query = db.query(Model).filter(Model.event_id == event_id)
        if actor_id:
            query = query.filter(Model.actor_id == actor_id)
        if action:
            query = query.filter(Model.action == action)
        if date_from:
            query = query.filter(Model.created_at >= date_from)
        if date_to:
            query = query.filter(Model.created_at <= date_to)

        total = query.count()
        records = (
            query.order_by(Model.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        entries = [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "actor_role": r.actor_role,
                "event_id": r.event_id,
                "action": r.action,
                "details": r.details,
                "created_at": r.created_at,
                "shard_id": shard_idx,
            }
            for r in records
        ]
        return entries, total

    else:
        # MULTI-SHARD FEDERATED QUERY PATH (UNION ALL)
        subqueries = []
        for idx, Model in enumerate(SHARDS):
            stmt = select(
                Model.id,
                Model.actor_id,
                Model.actor_role,
                Model.event_id,
                Model.action,
                Model.details,
                Model.created_at,
                literal(idx).label("shard_id"),
            )
            if actor_id:
                stmt = stmt.where(Model.actor_id == actor_id)
            if action:
                stmt = stmt.where(Model.action == action)
            if date_from:
                stmt = stmt.where(Model.created_at >= date_from)
            if date_to:
                stmt = stmt.where(Model.created_at <= date_to)
            subqueries.append(stmt)

        combined = union_all(*subqueries).subquery()

        # Count total
        count_stmt = select(func.count()).select_from(combined)
        total = db.execute(count_stmt).scalar() or 0

        # Retrieve page
        data_stmt = (
            select(combined)
            .order_by(combined.c.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = db.execute(data_stmt).fetchall()

        entries = [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "actor_role": r.actor_role,
                "event_id": r.event_id,
                "action": r.action,
                "details": r.details,
                "created_at": r.created_at,
                "shard_id": r.shard_id,
            }
            for r in rows
        ]
        return entries, total
