"""JARVIS Core orchestrator (spec §4.1): one brain for every channel.

Takes a normalized InboundMessage, replays the session's history to Claude
with the home_control tools, runs whatever tools Claude calls, and returns
the final reply. The history is stored append-only: each API message becomes
one chat_sessions row, written only after the turn completes, and replayed
unchanged. Opus 5.5 binds its thinking blocks to the exact conversation
prefix, so editing or trimming earlier turns would invalidate them.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.messages import Channel, InboundMessage
from app.core.images import block as image_block
from app.core.prompts import FEMALE_VOICE_HINT, MALE_VOICE_HINT, SYSTEM_PROMPT, VOICE_HINT
from app.core.tools import TOOLS, ToolContext, run_tool
from app.models import ChatMessage, Device, User

log = logging.getLogger(__name__)

BETAS = [
    # Re-run a declined request on a fallback model instead of just stopping.
    "server-side-fallback-2026-07-01",
    # Explicit preserved-thinking behavior: drop, rather than 400 on, a thinking
    # block whose prefix no longer matches (append-only history avoids this anyway).
    "thinking-binding-controls-2026-08-01",
]

_THINKING = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}


IMAGE_PLACEHOLDER = {"type": "text", "text": "[รูปภาพที่ผู้ใช้ส่งมาในข้อความนี้ ไม่ได้เก็บไว้ในประวัติ]"}


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
    # Web search answers arrive as several text blocks (one per cited span) that form one reply.
    return "".join(b.text for b in content if b.type == "text").strip()


def device_snapshot(db: Session) -> str:
    """One line per device, from the table Pulsar keeps current."""
    lines = []
    for d in db.scalars(select(Device).order_by(Device.id)):
        status = {k: v for k, v in (d.status or {}).items() if v not in ("", None)}
        lines.append(
            f"- device_id={d.id} {d.name} | ห้อง: {d.room or '-'} | {d.category} | "
            f"{'ออนไลน์' if d.online else 'ออฟไลน์'} | {json.dumps(status, ensure_ascii=False)}"
        )
    return "\n".join(lines)


class Orchestrator:
    def __init__(self, client, *, model: str, effort: str, max_tool_rounds: int, timezone: str, web_search: dict | None = None):
        self.client = client
        # The tool list stays the same for the whole process so the cached prefix does too.
        self.tools = TOOLS + ([web_search] if web_search else [])
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

    def _user_turn(
        self, text: str, channel: Channel, devices: str = "", male_voice: bool = False, back_to_female: bool = False, images: list[str] | None = None
    ) -> dict:
        # The current time (and channel hints) live in the user turn, not the system prompt, so the prefix stays stable.
        now = datetime.now(self.tz).strftime("%Y-%m-%d %H:%M (%A)")
        header = f"[เวลาปัจจุบัน: {now}]"
        if devices:
            header += f"\n[อุปกรณ์ในบ้านตอนนี้]\n{devices}"
        if channel == Channel.voice:
            header += f"\n{VOICE_HINT}"
        if male_voice:
            header += f"\n{MALE_VOICE_HINT}"
        elif back_to_female:
            header += f"\n{FEMALE_VOICE_HINT}"
        if images:
            header += f"\n[ผู้ใช้แนบรูป {len(images)} รูปมากับข้อความนี้]"
        pictures = [image_block(i) for i in images or []]
        return {"role": "user", "content": [*pictures, {"type": "text", "text": f"{header}\n{text}"}]}

    def _call(self, messages: list[dict]):
        try:
            return self._create(messages)
        except anthropic.BadRequestError as e:
            # A web search setting the API rejects shouldn't stop home control: drop search and carry on.
            if "web_search" not in str(e) or len(self.tools) == len(TOOLS):
                raise
            log.warning("web search disabled for this run, the API rejected it: %s", e)
            self.tools = TOOLS
            return self._create(messages)

    def _create(self, messages: list[dict]):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=messages,
            thinking=_THINKING,
            output_config={"effort": self.effort},
            betas=BETAS,
            fallbacks="default",
            # Every call re-sends the same tools, system prompt and (append-only) history; caching that prefix
            # bills the repeat at the cache-read rate instead of full input price. The breakpoint moves to the
            # end of each request, so the next tool round or turn within 5 minutes reads everything before it.
            cache_control={"type": "ephemeral"},
        )

    def handle(self, db: Session, tuya, user: User, msg: InboundMessage) -> CoreReply:
        session_id = msg.session_id or uuid.uuid4().hex
        history = self._history(db, user, session_id)
        # Attaching the device list saves Claude a get_devices round trip on most commands.
        # Earlier turns with the male voice make the model keep saying ครับ; say so when it's female again.
        back_to_female = msg.voice == "female" and any(
            MALE_VOICE_HINT in block.get("text", "")
            for m in history
            if m["role"] == "user" and isinstance(m["content"], list)
            for block in m["content"]
            if isinstance(block, dict)
        )
        new_messages = [self._user_turn(msg.text, msg.channel, device_snapshot(db), msg.voice == "male", back_to_female, msg.images)]
        ctx = ToolContext(db=db, tuya=tuya, user=user, channel=msg.channel.value, turn_started=datetime.now(timezone.utc))
        calls: list[ToolCallRecord] = []

        for round_no in range(1, self.max_tool_rounds + 1):
            started = time.perf_counter()
            response = self._call(history + new_messages)
            u = response.usage
            log.info(
                "Claude round %d: %.1fs (%s) tokens in=%d cache_read=%d cache_write=%d out=%d",
                round_no,
                time.perf_counter() - started,
                response.stop_reason,
                u.input_tokens,
                u.cache_read_input_tokens or 0,
                u.cache_creation_input_tokens or 0,
                u.output_tokens,
            )

            if response.stop_reason == "refusal":
                # Nothing is persisted for a declined turn, keeping the history clean.
                return CoreReply(session_id, "ขออภัยค่ะ เรื่องนี้จาร์วิสช่วยไม่ได้", calls)

            new_messages.append({"role": "assistant", "content": [_block_dict(b) for b in response.content]})
            # Searches run on Anthropic's side; list them too so the chat shows what JARVIS did.
            calls += [ToolCallRecord(b.name, dict(b.input), True) for b in response.content if b.type == "server_tool_use"]
            if response.stop_reason == "pause_turn":
                # A long server-side web search paused; sending the turn back as-is resumes it.
                continue
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            results = []
            for tu in tool_uses:
                started = time.perf_counter()
                content, is_error = run_tool(ctx, tu.name, dict(tu.input))
                log.info("tool %s: %.1fs%s", tu.name, time.perf_counter() - started, " (error)" if is_error else "")
                calls.append(ToolCallRecord(tu.name, dict(tu.input), not is_error))
                results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error}
                )
            # All results of one assistant turn go back in a single user message.
            new_messages.append({"role": "user", "content": results})
        else:
            log.warning("tool loop hit max rounds (%d) for session %s", self.max_tool_rounds, session_id)
            return CoreReply(session_id, "ขออภัยค่ะ งานนี้ซับซ้อนเกินไป ลองแบ่งเป็นคำสั่งสั้นๆ อีกครั้งนะคะ", calls)

        text = _reply_text(response.content) or "เรียบร้อยค่ะ"
        if response.stop_reason == "max_tokens":
            text += " …"
        self._persist(db, user, msg, session_id, new_messages, text, calls)
        return CoreReply(session_id, text, calls)

    def _persist(
        self, db: Session, user: User, msg: InboundMessage, session_id: str, new_messages: list[dict], reply: str, calls: list[ToolCallRecord]
    ):
        # Pictures are used for this turn only: storing them would re-send them (and their tokens) on every
        # later turn. What JARVIS read from them is in its reply and tool calls; drop_block covers the changed prefix.
        new_messages = [
            {**m, "content": [IMAGE_PLACEHOLDER if isinstance(b, dict) and b.get("type") == "image" else b for b in m["content"]]}
            if m["role"] == "user" and isinstance(m["content"], list)
            else m
            for m in new_messages
        ]
        # What the chat shows for this turn (the dashboard reloads it on every screen); never sent to Claude.
        shown = {
            0: {"role": "user", "text": msg.text, "pictures": len(msg.images)},
            len(new_messages) - 1: {"role": "jarvis", "text": reply, "tool_calls": [c.__dict__ for c in calls]},
        }
        for i, m in enumerate(new_messages):
            content = {"blocks": m["content"]} | ({"display": shown[i]} if i in shown else {})
            db.add(ChatMessage(user_id=user.id, channel=msg.channel.value, session_id=session_id, role=m["role"], content=content))
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
            web_search=(
                {
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": s.web_search_max_uses,
                    "user_location": {"type": "approximate", "timezone": s.timezone}
                    | ({"country": s.web_search_country} if s.web_search_country else {}),
                }
                if s.web_search_enabled
                else None
            ),
        )
    return _orchestrator
