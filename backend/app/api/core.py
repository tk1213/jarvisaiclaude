import logging
import threading
from datetime import datetime, timedelta, timezone

import anthropic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import images as image_utils
from app.core.messages import Channel, InboundMessage
from app.core.orchestrator import CoreNotConfigured, get_orchestrator
from app.core.prompts import match_voice
from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user, get_tuya
from app.models import ChatMessage, User
from app.realtime import hub

log = logging.getLogger(__name__)
router = APIRouter(tags=["core"])


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    # "voice" when the dashboard's mic produced the text; JARVIS then answers in a speakable form.
    channel: Literal["dashboard", "voice"] = "dashboard"
    # The voice chosen on the dashboard; a male voice answers with ครับ.
    voice: Literal["female", "male"] = "female"
    # Pictures attached to this message (base64 or data: URLs, e.g. a customer's name card for a quotation).
    images: list[str] = Field(default_factory=list, max_length=image_utils.MAX_IMAGES)
    # Which open screen sent it: the others show the turn from the live stream, this one already has it.
    client_id: str = Field(default="", max_length=64)


class ToolCallOut(BaseModel):
    name: str
    input: dict
    ok: bool


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCallOut]


class ChatLine(BaseModel):
    role: Literal["user", "jarvis"]
    text: str
    tool_calls: list[ToolCallOut] = []
    pictures: int = 0


class ChatHistory(BaseModel):
    session_id: str | None
    messages: list[ChatLine]


class ChatReset(BaseModel):
    client_id: str = Field(default="", max_length=64)


DASHBOARD_CHANNELS = (Channel.dashboard.value, Channel.voice.value)
_lock = threading.Lock()
_reset_at: dict[int, datetime] = {}  # user id -> when they started over (older turns aren't continued)


def _as_utc(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def live_session(db: Session, user: User) -> str | None:
    """The user's dashboard conversation, shared by all their screens, unless it's gone quiet or they started over."""
    last = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id, ChatMessage.channel.in_(DASHBOARD_CHANNELS))
        .order_by(ChatMessage.id.desc())
        .limit(1)
    ).first()
    if last is None:
        return None
    at = _as_utc(last.created_at)
    with _lock:
        reset = _reset_at.get(user.id)
    if datetime.now(timezone.utc) - at > timedelta(minutes=get_settings().dashboard_session_idle_minutes) or (reset and at <= reset):
        return None
    return last.session_id


@router.get("/core/chat/current", response_model=ChatHistory)
def current_chat(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The conversation every dashboard screen shows: what was said, without Claude's tool traffic."""
    session_id = live_session(db, user)
    if session_id is None:
        return ChatHistory(session_id=None, messages=[])
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.user_id == user.id, ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    return ChatHistory(session_id=session_id, messages=[ChatLine(**r.content["display"]) for r in rows if "display" in r.content])


@router.post("/core/chat/reset", status_code=204)
def reset_chat(body: ChatReset, user: User = Depends(get_current_user)):
    """Start a new conversation on every screen (the "เริ่มใหม่" button)."""
    with _lock:
        _reset_at[user.id] = datetime.now(timezone.utc)
    hub.publish_to_user(user.id, {"type": "chat_reset", "origin": body.client_id})


@router.post("/core/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db), tuya=Depends(get_tuya), user: User = Depends(get_current_user)):
    """Talk to JARVIS from the dashboard. Every screen shares one conversation (live_session); session_id is
    ignored and kept only for older dashboards."""
    try:
        orchestrator = get_orchestrator()
    except CoreNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None

    try:
        jpegs = [image_utils.from_base64(i) for i in body.images]
    except image_utils.ImageError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    session_id = live_session(db, user)
    msg = InboundMessage(user_id=user.id, channel=Channel(body.channel), session_id=session_id, text=body.text, voice=body.voice, images=jpegs)
    try:
        reply = orchestrator.handle(db, tuya, user, msg)
    except anthropic.AuthenticationError:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Claude API key was rejected; check ANTHROPIC_API_KEY") from None
    except anthropic.RateLimitError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Claude API rate limit reached, try again shortly") from None
    except anthropic.APIStatusError as e:
        # 500, not 502: Cloudflare replaces an origin's 502 body with its own page, hiding this message.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Claude API error {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not reach the Claude API") from None
    except Exception as e:
        # Say what broke instead of a bare 500 (the full traceback is in the start.bat window).
        log.exception("chat failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"JARVIS error: {e.__class__.__name__}: {e}") from None

    out = ChatResponse(
        session_id=reply.session_id,
        reply=match_voice(reply.text, body.voice),
        tool_calls=[ToolCallOut(name=c.name, input=c.input, ok=c.ok) for c in reply.tool_calls],
    )
    # The user's other screens show the turn as it happens (only the one that asked speaks it).
    event = {"type": "chat", "origin": body.client_id, "text": body.text, "pictures": len(jpegs)}
    hub.publish_to_user(user.id, event | out.model_dump(mode="json"))
    return out
