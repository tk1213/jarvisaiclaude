"""Income and expense records for the Account page, in their own database file (backend/data/account/account.db).

Amounts are whole satang (integers), so VAT and totals add up exactly.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import AccountBase
from app.models import utcnow


class AccountEntry(AccountBase):
    """One income (sales tax invoice) or expense (purchase) line of the books."""

    __tablename__ = "account_entries"
    __table_args__ = (UniqueConstraint("source", "kind", "external_id", name="uq_account_entry_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # "income" | "expense"
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    doc_no: Mapped[str] = mapped_column(String(64), default="")  # tax invoice number
    party: Mapped[str] = mapped_column(String(256), default="")  # customer or supplier
    party_tax_id: Mapped[str] = mapped_column(String(32), default="")
    party_branch: Mapped[str] = mapped_column(String(64), default="")  # "สำนักงานใหญ่" or a branch number
    # "company" or "person": decides ภ.ง.ด.53 or ภ.ง.ด.3 for tax withheld from a payment.
    party_type: Mapped[str] = mapped_column(String(16), default="company")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    base_satang: Mapped[int] = mapped_column(Integer, default=0)  # before VAT
    vat_satang: Mapped[int] = mapped_column(Integer, default=0)
    wht_rate: Mapped[int] = mapped_column(Integer, default=0)  # % withheld (income: by the customer; expense: by us)
    wht_satang: Mapped[int] = mapped_column(Integer, default=0)
    # Expenses: only a full tax invoice (ใบกำกับภาษีเต็มรูป) makes its VAT claimable input tax.
    full_tax_invoice: Mapped[bool] = mapped_column(Boolean, default=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)  # kept but not counted (e.g. a voided document)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # "manual" | "flowaccount"
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_status: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AccountSetting(AccountBase):
    """Small key/value facts about the books, e.g. when FlowAccount was last read."""

    __tablename__ = "account_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
