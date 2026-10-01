import logging

import anthropic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.messages import Channel, InboundMessage
from app.core.orchestrator import CoreNotConfigured, get_orchestrator
from app.db import get_db
from app.deps import get_current_user, get_tuya
from app.models import User

log = logging.getLogger(__name__)
router = APIRouter(tags=["core"])


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    # "voice" when the dashboard's mic produced the text; JARVIS then answers in a speakable form.
    channel: Literal["dashboard", "voice"] = "dashboard"


class ToolCallOut(BaseModel):
    name: str
    input: dict
    ok: bool


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCallOut]


@router.post("/core/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db), tuya=Depends(get_tuya), user: User = Depends(get_current_user)):
    """Talk to JARVIS from the dashboard. Omit session_id to start a new conversation."""
    try:
        orchestrator = get_orchestrator()
    except CoreNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None

    msg = InboundMessage(user_id=user.id, channel=Channel(body.channel), session_id=body.session_id, text=body.text)
    try:
        reply = orchestrator.handle(db, tuya, user, msg)
    except anthropic.AuthenticationError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Claude API key was rejected; check ANTHROPIC_API_KEY") from None
    except anthropic.RateLimitError:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Claude API rate limit reached, try again shortly") from None
    except anthropic.APIStatusError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Claude API error {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach the Claude API") from None
    except Exception as e:
        # Say what broke instead of a bare 500 (the full traceback is in the start.bat window).
        log.exception("chat failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"JARVIS error: {e.__class__.__name__}: {e}") from None

    return ChatResponse(
        session_id=reply.session_id,
        reply=reply.text,
        tool_calls=[ToolCallOut(name=c.name, input=c.input, ok=c.ok) for c in reply.tool_calls],
    )
