"""Personal money (the 💳 page), in its own database file (backend/data/personal/personal.db).

Amounts are whole satang (integers). A bank account's balance is its opening balance plus everything
recorded on or after the opening date.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import PersonalBase
from app.models import utcnow


class BankAccount(PersonalBase):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank: Mapped[str] = mapped_column(String(16))  # code from services.personal.BANKS, e.g. "KBANK"
    nickname: Mapped[str] = mapped_column(String(64), default="")
    # Full number (best: matches the masked number printed on slips) or just the last digits.
    account_no: Mapped[str] = mapped_column(String(20), default="")
    opening_satang: Mapped[int] = mapped_column(Integer, default=0)
    opening_date: Mapped[date] = mapped_column(Date)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # used when a typed entry names no bank
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PersonalEntry(PersonalBase):
    """Money in, money out, or a transfer between two of the owner's own accounts."""

    __tablename__ = "personal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # "income" | "expense" | "transfer"
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    entry_time: Mapped[str] = mapped_column(String(5), default="")  # "HH:MM" from the slip
    amount_satang: Mapped[int] = mapped_column(Integer)
    # income: the account that received it; expense: the one that paid; transfer: the one it left.
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    to_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id"), nullable=True)  # transfers only
    counterparty: Mapped[str] = mapped_column(String(256), default="")  # who paid / who was paid
    note: Mapped[str] = mapped_column(Text, default="")
    ref_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # slip reference, stops duplicates
    source: Mapped[str] = mapped_column(String(16), default="manual")  # "slip" | "text" (LINE) | "manual" (dashboard)
    origin: Mapped[str] = mapped_column(String(16), default="")  # LINE group it came from: "income" | "expense"
    slip_file: Mapped[str] = mapped_column(String(256), default="")  # relative to PERSONAL_SLIP_DIR
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
