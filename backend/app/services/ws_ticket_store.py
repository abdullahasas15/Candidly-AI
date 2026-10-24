"""Shared, database-backed single-use enforcement for WebSocket tickets."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from backend.app.database import AsyncSessionLocal
from backend.app.models import WebSocketTicketUse

logger = logging.getLogger("candidly.interview_v2.ws_ticket_store")

# Tickets issued by the API carry a jti. Legacy/internal signed tickets without
# one still get single-use behavior by using the token digest as the key.
DEFAULT_TICKET_TTL = timedelta(minutes=5)


def ticket_consumption_id(token: str, claims: Dict[str, Any]) -> str:
    """Return a stable, bounded primary key for this signed ticket."""
    raw_id = claims.get("jti") or hashlib.sha256(token.encode("utf-8")).hexdigest()
    return str(raw_id)[:64]


def _ticket_expiry(claims: Dict[str, Any]) -> datetime:
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
    return datetime.now(timezone.utc).replace(tzinfo=None) + DEFAULT_TICKET_TTL


async def consume_ws_ticket(token: str, claims: Dict[str, Any]) -> bool:
    """Atomically consume a ticket.

    Returns True exactly once for a given ticket, even when multiple server
    workers receive the same replay concurrently. Returns False for a replay.
    Database errors are allowed to propagate so the router can fail closed.
    """
    ticket_id = ticket_consumption_id(token, claims)
    expires_at = _ticket_expiry(claims)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        # Keep the replay table bounded; expired tickets are rejected by JWT
        # validation before reaching this point.
        await db.execute(
            delete(WebSocketTicketUse).where(WebSocketTicketUse.expires_at < now)
        )
        db.add(
            WebSocketTicketUse(
                ticket_id=ticket_id,
                session_id=str(claims.get("session_id") or ""),
                user_id=str(claims.get("sub") or claims.get("id") or "") or None,
                expires_at=expires_at,
                consumed_at=now,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return False
    return True
