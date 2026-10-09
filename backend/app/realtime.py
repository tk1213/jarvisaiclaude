"""Real-time device updates for the dashboard (spec §4.4), plus each user's dashboard chat (shared by all their
open screens).

Every commit that touches a Device, whatever caused it (Pulsar events, REST
calls, JARVIS tools, sync), is published to connected WebSocket clients.
Commits happen on worker threads, so events hop onto the server's event loop
with call_soon_threadsafe before being fanned out to subscriber queues.
"""

import asyncio
import logging

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import Device
from app.schemas import DeviceOut

log = logging.getLogger(__name__)

_PENDING_KEY = "realtime_device_events"


class DeviceHub:
    def __init__(self, queue_size: int = 100):
        self._queues: dict[asyncio.Queue, int | None] = {}  # queue -> the user it belongs to
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue_size = queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def subscribe(self, user_id: int | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self._queue_size)
        self._queues[q] = user_id
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.pop(q, None)

    def publish(self, events: list[dict]) -> None:
        """Thread-safe; a no-op until the server has bound its loop."""
        loop = self._loop
        if loop is None or loop.is_closed() or not events:
            return
        loop.call_soon_threadsafe(self._fanout, events)

    def publish_to_user(self, user_id: int, event: dict) -> None:
        """An event only that user's screens receive (their chat)."""
        self.publish([{**event, "_user": user_id}])

    def _fanout(self, events: list[dict]) -> None:
        for q, owner in list(self._queues.items()):
            for e in events:
                if "_user" in e:
                    if e["_user"] != owner:
                        continue
                    e = {k: v for k, v in e.items() if k != "_user"}
                try:
                    q.put_nowait(e)
                except asyncio.QueueFull:
                    log.warning("dropping device event for a slow dashboard client")


hub = DeviceHub()


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _ctx) -> None:
    # new/dirty/deleted still show the pre-flush state here, and ids are assigned.
    pending: dict = session.info.setdefault(_PENDING_KEY, {})
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Device):
            pending[obj.id] = {"type": "device", "device": DeviceOut.model_validate(obj).model_dump(mode="json")}
    for obj in session.deleted:
        if isinstance(obj, Device):
            pending[obj.id] = {"type": "device_removed", "id": obj.id}


@event.listens_for(Session, "after_commit")
def _publish(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if pending:
        hub.publish(list(pending.values()))


@event.listens_for(Session, "after_rollback")
def _discard(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
