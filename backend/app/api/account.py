"""The Account page: income/expense records, the monthly tax summary, tax reports and the FlowAccount sync.

Admin only for now; per-user access (view only / add only) comes with the user-permission page.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.account_models import AccountEntry
from app.config import get_settings
from app.db import get_account_db
from app.deps import require_admin
from app.integrations.flowaccount import FlowAccountError, get_flowaccount_client
from app.models import User
from app.services import accounting

router = APIRouter(prefix="/account", tags=["account"])


class EntryIn(BaseModel):
    kind: str = Field(pattern="^(income|expense)$")
    date: date
    doc_no: str = Field(default="", max_length=64)
    party: str = Field(min_length=1, max_length=256)
    party_tax_id: str = Field(default="", max_length=32)
    party_branch: str = Field(default="", max_length=64)
    party_type: str = Field(default="company", pattern="^(company|person)$")
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=64)
    base: float = Field(gt=0, le=1_000_000_000)
    vat: float | None = Field(default=None, ge=0, le=1_000_000_000)  # None = 7% of base
    wht_rate: int = Field(default=0, ge=0, le=15)
    wht: float | None = Field(default=None, ge=0, le=1_000_000_000)  # None = base × rate
    full_tax_invoice: bool = True
    excluded: bool = False


class ImportedEntryIn(BaseModel):
    """What can change on a record that came from FlowAccount."""

    excluded: bool | None = None
    full_tax_invoice: bool | None = None
    category: str | None = Field(default=None, max_length=64)
    party_type: str | None = Field(default=None, pattern="^(company|person)$")


def _entry(db: Session, entry_id: int) -> AccountEntry:
    entry = db.get(AccountEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    return entry


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/info")
def info(db: Session = Depends(get_account_db), _: User = Depends(require_admin)):
    s = get_settings()
    synced = accounting.last_sync(db)
    return {
        "flowaccount_mode": s.flowaccount_mode,
        "last_sync": synced.isoformat() if synced else None,
        "categories": accounting.EXPENSE_CATEGORIES,
        "company": {"name": s.company_name, "tax_id": s.company_tax_id, "branch": s.company_branch},
    }


@router.get("/entries")
def list_entries(kind: str, month: str, db: Session = Depends(get_account_db), _: User = Depends(require_admin)):
    try:
        return [accounting.entry_out(e) for e in accounting.list_entries(db, kind, month)]
    except accounting.AccountingError as e:
        raise _bad(e) from None


@router.post("/entries", status_code=201)
def add_entry(body: EntryIn, db: Session = Depends(get_account_db), user: User = Depends(require_admin)):
    try:
        return accounting.entry_out(accounting.save_manual(db, body.model_dump(mode="json"), created_by=user.username))
    except accounting.AccountingError as e:
        raise _bad(e) from None


@router.put("/entries/{entry_id}")
def edit_entry(entry_id: int, body: dict, db: Session = Depends(get_account_db), _: User = Depends(require_admin)):
    entry = _entry(db, entry_id)
    try:
        if entry.source == "manual":
            data = EntryIn.model_validate(body | {"kind": entry.kind}).model_dump(mode="json")
            return accounting.entry_out(accounting.save_manual(db, data, entry=entry))
        data = ImportedEntryIn.model_validate(body).model_dump(exclude_none=True)
        return accounting.entry_out(accounting.update_imported(db, entry, data))
    except accounting.AccountingError as e:
        raise _bad(e) from None
    except ValueError as e:  # pydantic validation of the body
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_account_db), _: User = Depends(require_admin)):
    try:
        accounting.delete_entry(db, _entry(db, entry_id))
    except accounting.AccountingError as e:
        raise _bad(e) from None


@router.post("/sync")
def sync(db: Session = Depends(get_account_db), _: User = Depends(require_admin)):
    """Read tax invoices and expenses from FlowAccount (the "ดึงข้อมูลจาก FlowAccount" button)."""
    try:
        counts = accounting.sync_flowaccount(db, get_flowaccount_client())
    except FlowAccountError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from None
    return counts | {"last_sync": accounting.last_sync(db).isoformat()}


@router.get("/summary")
def summary(month: str, db: Session = Depends(get_account_db), _: User = Depends(require_admin)):
    try:
        return accounting.summary(db, month)
    except accounting.AccountingError as e:
        raise _bad(e) from None


@router.get("/report", responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
def report(
    month: str,
    kind: str = Query(pattern="^(income|expense)$"),
    db: Session = Depends(get_account_db),
    _: User = Depends(require_admin),
):
    """รายงานภาษีขาย / รายงานภาษีซื้อ as an Excel file."""
    try:
        data = accounting.tax_report_xlsx(db, month, kind)
    except accounting.AccountingError as e:
        raise _bad(e) from None
    name = f"{'sales' if kind == 'income' else 'purchase'}-tax-{month}.xlsx"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
