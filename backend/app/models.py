"""Data model (spec §5)."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Device control and financial documents are separate permissions (spec §6).
    can_control_devices: Mapped[bool] = mapped_column(Boolean, default=True)
    can_issue_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    line_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tuya_device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    room: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(32), default="")
    product_name: Mapped[str] = mapped_column(String(128), default="")
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[dict] = mapped_column(JSON, default=dict)
    # Set when the user renames / re-rooms the device, so a Tuya sync doesn't overwrite it.
    name_overridden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    room_overridden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Tuya rejected the last command for lack of permission (cloud project set to "Read").
    control_denied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # For IR remotes (e.g. category infrared_ac): the Tuya id of the IR hub that sends the signal.
    ir_hub_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flowaccount_contact_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DocumentLog(Base):
    """Every financial document issued through JARVIS, with who/where (spec §6)."""

    __tablename__ = "documents_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    doc_type: Mapped[str] = mapped_column(String(32))  # quotation, billing_note, receipt, ...
    flowaccount_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_amount: Mapped[str] = mapped_column(String(32), default="0")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    """Conversation history per user/channel/session, for long-term memory (spec §3.2)."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / tool
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderToken(Base):
    """Encrypted access tokens for Tuya / FlowAccount (spec §6)."""

    __tablename__ = "tokens"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
