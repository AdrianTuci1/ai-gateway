from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator
from contextlib import asynccontextmanager

from agw.core.time import utcnow
from agw.db.models import TraceSpan
from agw.store.base import Store

# The middleware always writes the root span with this id, so child spans
# created inside the request can point at it without knowing the row id.
ROOT_SPAN_ID = "root"


async def record_span(
    store: Store,
    *,
    workspace_id: uuid.UUID,
    trace_id: str,
    name: str,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    kind: str = "internal",
    status: str = "ok",
    duration_ms: int = 0,
    actor_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    attributes: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> TraceSpan:
    span = TraceSpan(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        trace_id=trace_id,
        span_id=span_id or uuid.uuid4().hex[:16],
        parent_span_id=parent_span_id,
        name=name,
        kind=kind,
        status=status,
        duration_ms=duration_ms,
        actor_type=actor_type,
        actor_id=actor_id,
        attributes=attributes or {},
        started_at=started_at or utcnow(),
        created_at=utcnow(),
    )
    await store.record_trace_span(span)
    return span


@asynccontextmanager
async def span_timer() -> AsyncIterator[dict[str, int]]:
    """Measure a block: `async with span_timer() as t: ... t["duration_ms"]`."""
    started = time.perf_counter()
    state: dict[str, int] = {"duration_ms": 0}
    try:
        yield state
    finally:
        state["duration_ms"] = int((time.perf_counter() - started) * 1000)


__all__ = ["ROOT_SPAN_ID", "record_span", "span_timer"]
