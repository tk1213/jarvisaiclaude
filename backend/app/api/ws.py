import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.models import User
from app.realtime import hub
from app.security import decode_access_token

router = APIRouter()


@router.websocket("/ws/devices")
async def device_updates(websocket: WebSocket, token: str = ""):
    """Streams {"type": "device", "device": {...}} / {"type": "device_removed", "id": ...} events, and this user's
    dashboard chat ({"type": "chat", ...} / {"type": "chat_reset", ...}) so every open screen shows the same conversation.

    Browsers can't set headers on WebSocket requests, so the JWT comes as ?token=.
    """
    try:
        user_id = decode_access_token(token)
    except Exception:
        await websocket.close(code=4401)
        return
    with SessionLocal() as db:
        if db.get(User, user_id) is None:
            await websocket.close(code=4401)
            return

    await websocket.accept()
    queue = hub.subscribe(user_id)

    async def forward():
        while True:
            await websocket.send_json(await queue.get())

    async def wait_for_close():
        # We don't expect client messages; this just notices a disconnect promptly.
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await websocket.receive_text()

    tasks = [asyncio.create_task(forward()), asyncio.create_task(wait_for_close())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        hub.unsubscribe(queue)
