"""The 💳 personal-money and 🏢 company-money pages: bank accounts, balances, and income/expense entries, also fed by
the LINE groups ("TKรับจ่าย" -> personal, "สลิปรายรับ" / "สลิปรายจ่าย" -> company).

Both pages run the same code on their own database file; access follows the "personal" / "company" page levels.
"""

from collections.abc import Callable

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import permissions
from app.db import CompanySession, get_company_db, get_personal_db
from app.models import User
from app.personal_models import BankAccount, PersonalEntry
from app.services import personal


class AccountIn(BaseModel):
    bank: str = Field(max_length=16)
    nickname: str = Field(default="", max_length=64)
    account_no: str = Field(default="", max_length=32)
    opening: float = Field(default=0, ge=-1_000_000_000, le=1_000_000_000)
    opening_date: date
    is_default: bool = False


class MoveIn(BaseModel):
    entry_ids: list[int] = Field(min_length=1, max_length=500)
    account_id: int


class EntryIn(BaseModel):
    kind: str = Field(pattern="^(income|expense|transfer)$")
    date: date
    time: str = Field(default="", pattern=r"^(\d{2}:\d{2})?$")
    amount: float = Field(gt=0, le=1_000_000_000)
    account_id: int
    to_account_id: int | None = None
    counterparty: str = Field(default="", max_length=256)
    note: str = Field(default="", max_length=2000)


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _account(db: Session, account_id: int) -> BankAccount:
    acc = db.get(BankAccount, account_id)
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return acc


def _entry(db: Session, entry_id: int) -> PersonalEntry:
    entry = db.get(PersonalEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    return entry


def _account_out(db: Session, a: BankAccount) -> dict:
    return {
        "id": a.id,
        "bank": a.bank,
        "bank_name": personal.bank_name(a.bank),
        "nickname": a.nickname,
        "account_no": a.account_no,
        "label": personal.label(a),
        "opening": a.opening_satang / 100,
        "opening_date": a.opening_date.isoformat(),
        "is_default": a.is_default,
        "balance": personal.balance(db, a) / 100,
    }


def _names(db: Session) -> dict[int, str]:
    return {a.id: personal.label(a) for a in personal.accounts(db)}


def make_router(page: str, get_book_db: Callable) -> APIRouter:
    """The API of one money page (/personal or /company), on its own database and page permission."""
    router = APIRouter(prefix=f"/{page}", tags=[page])
    can_view = permissions.require(page)
    can_edit = permissions.require(page, "edit")

    @router.get("/banks")
    def banks(_: User = Depends(can_view)):
        return [{"code": code, "name": name} for code, (name, _words) in personal.BANKS.items()]


    @router.get("/accounts")
    def list_accounts(db: Session = Depends(get_book_db), _: User = Depends(can_view)):
        return [_account_out(db, a) for a in personal.accounts(db)]


    @router.post("/accounts", status_code=201)
    def add_account(body: AccountIn, db: Session = Depends(get_book_db), _: User = Depends(can_edit)):
        try:
            return _account_out(db, personal.save_account(db, body.model_dump()))
        except personal.PersonalError as e:
            raise _bad(e) from None


    @router.put("/accounts/{account_id}")
    def edit_account(account_id: int, body: AccountIn, db: Session = Depends(get_book_db), _: User = Depends(can_edit)):
        try:
            return _account_out(db, personal.save_account(db, body.model_dump(), _account(db, account_id)))
        except personal.PersonalError as e:
            raise _bad(e) from None


    @router.delete("/accounts/{account_id}", status_code=204)
    def delete_account(account_id: int, db: Session = Depends(get_book_db), _: User = Depends(can_edit)):
        try:
            personal.delete_account(db, _account(db, account_id))
        except personal.PersonalError as e:
            raise _bad(e) from None


    @router.get("/summary")
    def summary(month: str, db: Session = Depends(get_book_db), _: User = Depends(can_view)):
        try:
            return personal.summary(db, month)
        except personal.PersonalError as e:
            raise _bad(e) from None


    @router.get("/entries")
    def list_entries(kind: str, month: str, account_id: int | None = None, db: Session = Depends(get_book_db), _: User = Depends(can_view)):
        if kind not in ("income", "expense"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind must be income or expense")
        try:
            rows = personal.list_entries(db, kind, month, account_id)
        except personal.PersonalError as e:
            raise _bad(e) from None
        names = _names(db)
        return [personal.entry_out(e, names) for e in rows]


    @router.post("/entries", status_code=201)
    def add_entry(body: EntryIn, db: Session = Depends(get_book_db), _: User = Depends(can_edit)):
        try:
            e = personal.save_entry(db, body.model_dump())
        except personal.PersonalError as err:
            raise _bad(err) from None
        return personal.entry_out(e, _names(db))


    @router.put("/entries/{entry_id}")
    def edit_entry(entry_id: int, body: EntryIn, db: Session = Depends(get_book_db), _: User = Depends(can_edit)):
        try:
            e = personal.save_entry(db, body.model_dump(), _entry(db, entry_id))
        except personal.PersonalError as err:
            raise _bad(err) from None
        return personal.entry_out(e, _names(db))


    @router.delete("/entries/{entry_id}", status_code=204)
    def delete_entry(entry_id: int, db: Session = Depends(get_book_db), _: User = Depends(can_edit)):
        personal.delete_entry(db, _entry(db, entry_id))
        return Response(status_code=204)


    @router.get("/entries/{entry_id}/slip")
    def slip(entry_id: int, db: Session = Depends(get_book_db), _: User = Depends(can_view)):
        entry = _entry(db, entry_id)
        path = (personal.slip_dir() / entry.slip_file).resolve() if entry.slip_file else None
        if path is None or not path.is_relative_to(personal.slip_dir().resolve()) or not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No slip picture")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    return router


router = make_router("personal", get_personal_db)
company_router = make_router("company", get_company_db)


@router.post("/entries/move-to-company")
def move_to_company(
    body: MoveIn,
    db: Session = Depends(get_personal_db),
    _: User = Depends(permissions.require("personal", "edit")),
    __: User = Depends(permissions.require("company", "edit")),
):
    """Move entries recorded here before the company page existed (from the old slip groups) to company money."""
    with CompanySession() as company:
        try:
            return {"moved": personal.move_entries(db, company, body.entry_ids, body.account_id)}
        except personal.PersonalError as e:
            raise _bad(e) from None
