"""SSE live-events endpoint (doc 05 §Streaming 4): one-way JSON deltas."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from proxploy.api.deps import authorize
from proxploy.services.authn import resolve_session

router = APIRouter(prefix="/events", tags=["events"])

PING_S = 15

# Called directly inside the handler, not via Depends: a StreamingResponse
# would hold a DI-scoped DB session open for the whole connection. Same
# pattern api/jobs.py::job_stream uses. Authentication alone is NOT enough
# here: this bus carries host, app, job and alert deltas for the entire
# cluster, so a user with no team membership (denied everything else by
# Phase 8 amendment A1) could otherwise still watch the whole system through
# it. viewer-level `meta.read` is the "is an authorized user of this install"
# floor, and it requires a real membership.
_read = authorize("meta", "read")


@router.get("/stream")
async def events_stream(request: Request):
    # Resolve auth with a short-lived session: never hold a DB connection
    # open for the lifetime of the stream.
    raw = request.cookies.get(request.app.state.settings.session_cookie)

    def check():
        with request.app.state.sessionmaker() as db:
            user = resolve_session(db, raw) if raw else None
            if user is not None:
                _read(request, db, user)
            return user

    user = await asyncio.to_thread(check)
    if user is None:
        raise HTTPException(401, "authentication required")

    bus = request.app.state.bus

    async def gen():
        q = bus.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=PING_S)
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
