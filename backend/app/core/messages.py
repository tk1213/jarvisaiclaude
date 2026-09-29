"""Normalized input for JARVIS Core (spec §4.1).

Every channel (Dashboard, LINE, Voice) converts its payload into an
InboundMessage before it reaches the orchestrator, so the brain only ever
sees one shape. The LLM orchestrator that consumes it arrives in phase 1.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Channel(str, Enum):
    dashboard = "dashboard"
    line = "line"
    voice = "voice"


class InboundMessage(BaseModel):
    user_id: int
    channel: Channel
    session_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
