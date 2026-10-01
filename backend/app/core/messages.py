"""Normalized input for JARVIS Core (spec §4.1).

Every channel (Dashboard, LINE, Voice) converts its payload into an
InboundMessage before it reaches the orchestrator, so the brain only ever
sees one shape. It is consumed by app.core.orchestrator.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Channel(str, Enum):
    dashboard = "dashboard"
    line = "line"
    voice = "voice"


class InboundMessage(BaseModel):
    user_id: int
    channel: Channel
    # None starts a new conversation; the reply carries the id to continue it.
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    text: str = Field(min_length=1)
    # The dashboard's chosen speaking voice; a male voice answers with ครับ instead of ค่ะ.
    voice: Literal["female", "male"] = "female"
    # Pictures sent with this message, already shrunk to base64 JPEG by app.core.images.
    images: list[str] = Field(default_factory=list, max_length=4)
