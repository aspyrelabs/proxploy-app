"""In-process pub/sub bus (doc 02 §11.1): plain asyncio queues, no broker.

Zero subscribers costs nothing; a slow consumer loses deltas, and the UI's
interval refetch heals it (doc 06 §d, SSE is a hint channel, never the
source of truth).
"""
from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: str, data: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                pass
