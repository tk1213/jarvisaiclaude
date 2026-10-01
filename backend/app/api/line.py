"""LINE Official Account channel (spec §4.1): webhook in, JARVIS Core, reply out.

Only LINE users linked to a JARVIS account are answered: the owner gets a 6-digit code on the dashboard
and sends it to the OA once. Anyone else who adds the OA can't reach the house.
"""

import json
import logging
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import images as image_utils
from app.core.messages import Channel, InboundMessage
from app.core.orchestrator import CoreNotConfigured, get_orchestrator
from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.integrations import line as line_integration
from app.integrations.line import (
    CONFIRM_CHOICES,
    LineClient,
    LineError,
    reply_message,
    text_message,
    valid_signature,
)
from app.integrations.tuya import TuyaError, get_tuya_client
from app.models import ChatMessage, Device, User
from app.ratelimit import limiter

log = logging.getLogger(__name__)
router = APIRouter(tags=["line"])

LINK_CODE_SECONDS = 600
LINK_ATTEMPTS_PER_MINUTE = 5
RESET_WORDS = {"เริ่มใหม่", "เริ่มบทสนทนาใหม่", "reset"}
DEVICE_TOOLS = {"control_device", "control_air_conditioner"}

_lock = threading.Lock()
_codes: dict[str, tuple[int, float]] = {}  # code -> (user id, expires at)
_fresh: set[int] = set()  # users who asked for a new conversation
_seen: OrderedDict[str, None] = OrderedDict()  # webhook event ids already handled (LINE may redeliver)
# Pictures sent without text wait here (silently) for the user's next text message, e.g. a customer's
# name card first and then "ทำใบเสนอราคาชุด A ให้ลูกค้าในรูป".
PENDING_IMAGE_SECONDS = 600
_pending_images: dict[str, list[tuple[str, float]]] = {}  # LINE user id -> [(base64 JPEG, received at)]


def _configured() -> bool:
    s = get_settings()
    return bool(s.line_channel_secret and s.line_channel_access_token)


def get_line_client() -> LineClient:
    return line_integration.get_line_client()


# --- Linking a LINE user to a JARVIS account -------------------------------------------------------


class LineStatus(BaseModel):
    configured: bool
    linked: bool


class LinkCode(BaseModel):
    code: str
    expires_in: int


@router.get("/line/status", response_model=LineStatus)
def line_status(user: User = Depends(get_current_user)):
    return LineStatus(configured=_configured(), linked=user.line_user_id is not None)


@router.post("/line/link-code", response_model=LinkCode)
def new_link_code(user: User = Depends(get_current_user)):
    """A one-time code to send to the LINE OA; it links that LINE account to this user."""
    if not _configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LINE is not set up (LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN)")
    now = time.monotonic()
    with _lock:
        for code in [c for c, (uid, exp) in _codes.items() if uid == user.id or exp < now]:
            del _codes[code]
        code = f"{secrets.randbelow(1_000_000):06d}"
        while code in _codes:
            code = f"{secrets.randbelow(1_000_000):06d}"
        _codes[code] = (user.id, now + LINK_CODE_SECONDS)
    return LinkCode(code=code, expires_in=LINK_CODE_SECONDS)


@router.delete("/line/link", status_code=204)
def unlink(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.line_user_id = None
    db.commit()


def _take_code(code: str) -> int | None:
    with _lock:
        entry = _codes.pop(code, None)
    if entry is None or entry[1] < time.monotonic():
        return None
    return entry[0]


# --- Webhook -------------------------------------------------------------------------------------


@router.post("/line/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    """LINE calls this for every message. It must answer fast, so the reply is sent from a background task."""
    s = get_settings()
    if not _configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LINE is not set up")
    body = await request.body()
    if not valid_signature(s.line_channel_secret, body, request.headers.get("x-line-signature", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
    for event in json.loads(body).get("events", []):
        if _already_seen(event.get("webhookEventId")):
            continue
        background.add_task(handle_event, event)
    return {"ok": True}  # LINE's "Verify" button sends no events and only needs this 200


def _already_seen(event_id: str | None) -> bool:
    if not event_id:
        return False
    with _lock:
        if event_id in _seen:
            return True
        _seen[event_id] = None
        while len(_seen) > 500:
            _seen.popitem(last=False)
    return False


def handle_event(event: dict) -> None:
    source = event.get("source") or {}
    if source.get("type") != "user":
        return  # groups and rooms: JARVIS only works in a one-to-one chat
    line_user_id = source.get("userId")
    reply_token = event.get("replyToken")
    if not line_user_id or not reply_token:
        return
    client = get_line_client()
    try:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.line_user_id == line_user_id))
            message = _answer(db, client, event, line_user_id, user)
        if message:
            client.send(reply_token, line_user_id, [message])
    except LineError:
        log.exception("could not answer on LINE")


def _answer(db: Session, client: LineClient, event: dict, line_user_id: str, user: User | None) -> dict | None:
    kind = event.get("type")
    if kind == "follow":
        if user:
            return text_message(f"ยินดีต้อนรับกลับค่ะ {user.display_name or user.username} มีอะไรให้ช่วยไหมคะ")
        return text_message(_how_to_link())
    if kind != "message":
        return None
    message = event.get("message") or {}
    if message.get("type") == "image":
        if user is None:
            return text_message(_how_to_link())
        return _keep_image(client, line_user_id, message)
    if message.get("type") != "text":
        return text_message("ตอนนี้จาร์วิสอ่านได้แค่ข้อความตัวอักษรกับรูปภาพค่ะ")
    text = (message.get("text") or "").strip()
    if user is None:
        return text_message(_link(db, line_user_id, text))
    if text.lower() in RESET_WORDS:
        with _lock:
            _fresh.add(user.id)
            _pending_images.pop(line_user_id, None)
        return text_message("เริ่มบทสนทนาใหม่แล้วค่ะ มีอะไรให้ช่วยไหมคะ")
    client.show_loading(line_user_id)
    return _ask_jarvis(db, user, text, _take_images(line_user_id))


def _keep_image(client: LineClient, line_user_id: str, message: dict) -> dict | None:
    """Store a picture for the next text message and stay silent (the owner sends pictures, then says what to do)."""
    try:
        jpeg = image_utils.to_jpeg(client.get_content(message.get("id", "")))
    except image_utils.ImageError:
        return text_message("เปิดรูปนี้ไม่ได้ค่ะ ลองส่งใหม่อีกครั้งนะคะ")
    except LineError as e:
        log.warning("could not download a LINE picture: %s", e)
        return text_message("โหลดรูปจาก LINE ไม่ได้ค่ะ ลองส่งใหม่อีกครั้งนะคะ")
    now = time.monotonic()
    with _lock:
        kept = [p for p in _pending_images.get(line_user_id, []) if now - p[1] < PENDING_IMAGE_SECONDS]
        kept.append((jpeg, now))
        if len(kept) > image_utils.MAX_IMAGES:
            kept = kept[-image_utils.MAX_IMAGES :]
            _pending_images[line_user_id] = kept
            return text_message(f"รับรูปได้ครั้งละ {image_utils.MAX_IMAGES} รูปค่ะ จาร์วิสจะใช้ {image_utils.MAX_IMAGES} รูปล่าสุดนะคะ")
        _pending_images[line_user_id] = kept
    return None


def _take_images(line_user_id: str) -> list[str]:
    now = time.monotonic()
    with _lock:
        pending = _pending_images.pop(line_user_id, [])
    return [jpeg for jpeg, at in pending if now - at < PENDING_IMAGE_SECONDS]


def _how_to_link() -> str:
    return (
        "สวัสดีค่ะ จาร์วิสยังไม่รู้จักบัญชี LINE นี้\n"
        "เปิด Dashboard ของ JARVIS กดปุ่ม \"LINE\" ที่มุมบน แล้วส่งรหัส 6 หลักที่ได้มาในแชทนี้ค่ะ"
    )


def _link(db: Session, line_user_id: str, text: str) -> str:
    if not (len(text) == 6 and text.isdigit()):
        return _how_to_link()
    try:
        limiter.hit(f"line-link:{line_user_id}", LINK_ATTEMPTS_PER_MINUTE)
    except HTTPException:
        return "ลองรหัสบ่อยเกินไปค่ะ รอสักครู่แล้วลองใหม่นะคะ"
    user_id = _take_code(text)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        return "รหัสไม่ถูกต้องหรือหมดอายุแล้วค่ะ ขอรหัสใหม่จาก Dashboard ได้เลยนะคะ"
    if db.scalar(select(User).where(User.line_user_id == line_user_id)):
        return "บัญชี LINE นี้เชื่อมกับผู้ใช้อื่นอยู่แล้วค่ะ"
    user.line_user_id = line_user_id
    db.commit()
    return f"เชื่อม LINE กับบัญชี {user.display_name or user.username} แล้วค่ะ สั่งงานจาร์วิสในแชทนี้ได้เลย เช่น \"เปิดปลั๊ก 2\""


def _session_id(db: Session, user: User) -> str | None:
    """Continue the last LINE conversation unless it's gone quiet (or the user asked to start over)."""
    with _lock:
        if user.id in _fresh:
            _fresh.discard(user.id)
            return None
    last = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id, ChatMessage.channel == Channel.line.value)
        .order_by(ChatMessage.id.desc())
        .limit(1)
    ).first()
    if last is None:
        return None
    at = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - at > timedelta(minutes=get_settings().line_session_idle_minutes):
        return None
    return last.session_id


def _ask_jarvis(db: Session, user: User, text: str, images: list[str] | None = None) -> dict:
    try:
        orchestrator = get_orchestrator()
    except CoreNotConfigured:
        return text_message("จาร์วิสยังไม่ได้ตั้งค่า ANTHROPIC_API_KEY ค่ะ")
    msg = InboundMessage(user_id=user.id, channel=Channel.line, session_id=_session_id(db, user), text=text[:4000], images=images or [])
    try:
        reply = orchestrator.handle(db, get_tuya_client(), user, msg)
    except anthropic.APIStatusError as e:
        log.warning("Claude API error on LINE: %s", e)
        return text_message(f"ขออภัยค่ะ ตอนนี้จาร์วิสคิดไม่ได้ (Claude API error {e.status_code}) ลองดูที่ Dashboard นะคะ")
    except (anthropic.APIConnectionError, TuyaError) as e:
        log.warning("JARVIS failed on LINE: %s", e)
        return text_message("ขออภัยค่ะ ตอนนี้เชื่อมต่อไม่ได้ ลองใหม่อีกครั้งนะคะ")
    except Exception:
        log.exception("JARVIS failed on LINE")
        return text_message("ขออภัยค่ะ เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะคะ")
    ids = {c.input.get("device_id") for c in reply.tool_calls if c.ok and c.name in DEVICE_TOOLS}
    devices = [d for d in (db.get(Device, i) for i in sorted(i for i in ids if isinstance(i, int))) if d]
    # A fresh document draft waits for the owner's answer: offer OK / Cancel buttons (and only then).
    drafted = any(c.ok and c.name == "prepare_document" for c in reply.tool_calls)
    return reply_message(reply.text, devices, CONFIRM_CHOICES if drafted else None)
