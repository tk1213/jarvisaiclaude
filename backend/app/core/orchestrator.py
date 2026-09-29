"""JARVIS Core orchestrator (spec §4.1): one brain for every channel.

Takes a normalized InboundMessage, replays the session's history to Claude
with the home_control tools, runs whatever tools Claude calls, and returns
the final reply. The history is stored append-only: each API message becomes
one chat_sessions row, written only after the turn completes, and replayed
unchanged. Opus 5.5 binds its thinking blocks to the exact conversation
prefix, so editing or trimming earlier turns would invalidate them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.messages import Channel, InboundMessage
from app.core.prompts import SYSTEM_PROMPT, VOICE_HINT
from app.core.tools import TOOLS, ToolContext, run_tool
from app.models import ChatMessage, User

log = logging.getLogger(__name__)

BETAS = [
    # Re-run a declined request on a fallback model instead of just stopping.
    "server-side-fallback-2026-07-01",
    # Explicit preserved-thinking behavior: drop, rather than 400 on, a thinking
    # block whose prefix no longer matches (append-only history avoids this anyway).
    "thinking-binding-controls-2026-08-01",
]

_THINKING = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}


class CoreNotConfigured(RuntimeError):
    pass


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    ok: bool


@dataclass
class CoreReply:
    session_id: str
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


def _block_dict(block) -> dict:
    return block.to_dict() if hasattr(block, "to_dict") else dict(block)


def _reply_text(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


class Orchestrator:
    def __init__(self, client, *, model: str, effort: str, max_tool_rounds: int, timezone: str):
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tool_rounds = max_tool_rounds
        self.tz = ZoneInfo(timezone)

    def _history(self, db: Session, user: User, session_id: str) -> list[dict]:
        rows = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user.id, ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
        )
        return [{"role": r.role, "content": r.content["blocks"]} for r in rows]

    def _user_turn(self, text: str, channel: Channel) -> dict:
        # The current time (and channel hints) live in the user turn, not the system prompt, so the prefix stays stable.
        now = datetime.now(self.tz).strftime("%Y-%m-%d %H:%M (%A)")
        header = f"[เวลาปัจจุบัน: {now}]"
        if channel == Channel.voice:
            header += f"\n{VOICE_HINT}"
        return {"role": "user", "content": [{"type": "text", "text": f"{header}\n{text}"}]}

    def _call(self, messages: list[dict]):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            thinking=_THINKING,
            output_config={"effort": self.effort},
            betas=BETAS,
            fallbacks="default",
        )

    def handle(self, db: Session, tuya, user: User, msg: InboundMessage) -> CoreReply:
        session_id = msg.session_id or uuid.uuid4().hex
        history = self._history(db, user, session_id)
        new_messages = [self._user_turn(msg.text, msg.channel)]
        ctx = ToolContext(db=db, tuya=tuya, user=user)
        calls: list[ToolCallRecord] = []

        for _ in range(self.max_tool_rounds):
            response = self._call(history + new_messages)

            if response.stop_reason == "refusal":
                # Nothing is persisted for a declined turn, keeping the history clean.
                return CoreReply(session_id, "ขออภัยค่ะ เรื่องนี้ JARVIS ช่วยไม่ได้", calls)

            new_messages.append({"role": "assistant", "content": [_block_dict(b) for b in response.content]})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            results = []
            for tu in tool_uses:
                content, is_error = run_tool(ctx, tu.name, dict(tu.input))
                calls.append(ToolCallRecord(tu.name, dict(tu.input), not is_error))
                results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error}
                )
            # All results of one assistant turn go back in a single user message.
            new_messages.append({"role": "user", "content": results})
        else:
            log.warning("tool loop hit max rounds (%d) for session %s", self.max_tool_rounds, session_id)
            return CoreReply(session_id, "ขออภัยค่ะ งานนี้ซับซ้อนเกินไป ลองแบ่งเป็นคำสั่งสั้นๆ อีกครั้งนะคะ", calls)

        self._persist(db, user, msg, session_id, new_messages)
        text = _reply_text(response.content) or "เรียบร้อยค่ะ"
        if response.stop_reason == "max_tokens":
            text += " …"
        return CoreReply(session_id, text, calls)

    def _persist(self, db: Session, user: User, msg: InboundMessage, session_id: str, new_messages: list[dict]):
        for m in new_messages:
            db.add(
                ChatMessage(
                    user_id=user.id,
                    channel=msg.channel.value,
                    session_id=session_id,
                    role=m["role"],
                    content={"blocks": m["content"]},
                )
            )
        db.commit()


_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        s = get_settings()
        if not s.anthropic_api_key:
            raise CoreNotConfigured("ANTHROPIC_API_KEY is not set")
        _orchestrator = Orchestrator(
            anthropic.Anthropic(api_key=s.anthropic_api_key),
            model=s.claude_model,
            effort=s.claude_effort,
            max_tool_rounds=s.claude_max_tool_rounds,
            timezone=s.timezone,
        )
    return _orchestrator
