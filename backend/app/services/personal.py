"""Personal money (the 💳 page): bank and fund accounts, income/expense entries, balances, and what LINE records
from a slip picture or a typed line: the "tk รับจ่าย" OA's one-to-one chat (it works out income or expense
itself) or, before that OA is set up, the jarvisclaude groups "สลิปรายรับ" / "สลิปรายจ่าย".

Every function that answers LINE returns the Thai reply to send; nothing here talks to LINE or Claude itself.
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.personal_models import BankAccount, PersonalEntry

log = logging.getLogger(__name__)

KINDS = ("income", "expense", "transfer")
# code -> (Thai name, words that mean this bank on a slip or in a typed line)
BANKS: dict[str, tuple[str, list[str]]] = {
    "KBANK": ("กสิกรไทย", ["กสิกรไทย", "กสิกร", "kbank", "kasikorn", "kplus", "k plus", "k+"]),
    "SCB": ("ไทยพาณิชย์", ["ไทยพาณิชย์", "scb", "siam commercial"]),
    "BBL": ("กรุงเทพ", ["ธนาคารกรุงเทพ", "กรุงเทพ", "บัวหลวง", "bbl", "bangkok bank", "bualuang"]),
    "KTB": ("กรุงไทย", ["กรุงไทย", "ktb", "krungthai", "krung thai"]),
    "BAY": ("กรุงศรี", ["กรุงศรีอยุธยา", "กรุงศรี", "krungsri", "bay"]),
    "TTB": ("ทีทีบี", ["ทหารไทยธนชาต", "ทหารไทย", "ธนชาต", "ทีทีบี", "ttb", "tmb", "thanachart"]),
    "GSB": ("ออมสิน", ["ออมสิน", "mymo", "gsb"]),
    "BAAC": ("ธ.ก.ส.", ["ธ.ก.ส.", "ธกส", "baac"]),
    "GHB": ("อาคารสงเคราะห์", ["อาคารสงเคราะห์", "ธอส", "ghb"]),
    "UOB": ("ยูโอบี", ["ยูโอบี", "uob"]),
    "CIMB": ("ซีไอเอ็มบี", ["ซีไอเอ็มบี", "cimb"]),
    "KKP": ("เกียรตินาคินภัทร", ["เกียรตินาคินภัทร", "เกียรตินาคิน", "kkp"]),
    "LHB": ("แลนด์ แอนด์ เฮ้าส์", ["แลนด์แอนด์เฮ้าส์", "lh bank", "lhb"]),
    "TISCO": ("ทิสโก้", ["ทิสโก้", "tisco"]),
    "TRUEMONEY": ("TrueMoney", ["ทรูมันนี่", "truemoney", "true money"]),
    "CASH": ("เงินสด", ["เงินสด", "cash"]),
    "OTHER": ("อื่นๆ", []),
    # Mutual funds kept as accounts (their real name goes in the nickname); a fund's balance is the money put in.
    **{f"FUND_{x}": (f"กองทุน {x}", [f"กองทุน {x}"]) for x in "ABCDEF"},
}
# Longest first, so "กรุงศรีอยุธยา" wins over "กรุงศรี" and "ทหารไทย" never reads as "ไทย…".
_ALIASES = sorted(((a.replace(" ", "").lower(), code) for code, (_, words) in BANKS.items() for a in words), key=lambda x: -len(x[0]))
_AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?![\d,])")
DELETE_WORDS = {"ลบล่าสุด", "ลบรายการล่าสุด", "ยกเลิกล่าสุด"}
BALANCE_WORDS = {"ยอด", "ยอดคงเหลือ", "ยอดเงิน", "เหลือเท่าไหร่", "คงเหลือ"}
PENDING_SECONDS = 600


class PersonalError(ValueError):
    pass


# --- Money and names ------------------------------------------------------------------------------------


def to_satang(value) -> int:
    if value is None or value == "":
        raise PersonalError("ต้องใส่จำนวนเงิน")
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise PersonalError(f"จำนวนเงินไม่ถูกต้อง: {value}") from None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(satang: int) -> str:
    return f"{satang / 100:,.2f}"


def bank_code(text: str | None) -> str | None:
    """The bank a slip or a typed line names, e.g. "ธ.กสิกรไทย" / "K PLUS" -> "KBANK"."""
    if not text:
        return None
    t = text.replace(" ", "").lower()
    for alias, code in _ALIASES:
        if alias in t:
            return code
    return None


def bank_name(code: str) -> str:
    return BANKS.get(code, (code, []))[0]


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def label(acc: BankAccount) -> str:
    """"กสิกร ใช้จ่าย (…1234)": what replies and the dashboard call an account."""
    name = acc.nickname or bank_name(acc.bank)
    tail = _digits(acc.account_no)[-4:]
    return f"{name} (…{tail})" if tail else name


def is_fund(code: str) -> bool:
    return code.startswith("FUND_")


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def named_accounts(accs: list[BankAccount], text: str) -> list[BankAccount]:
    """Accounts whose nickname appears in the text, e.g. "K-SET50" in "โอน 5000 กสิกร ไป K-SET50"."""
    t = _squash(text)
    return [a for a in accs if len(_squash(a.nickname)) >= 3 and _squash(a.nickname) in t]


def _drop_nicknames(accs: list[BankAccount], text: str) -> str:
    """The text without account nicknames, so the digits in a name like "K-SET50" aren't read as an amount."""
    for a in sorted(accs, key=lambda a: -len(a.nickname)):
        if len(_squash(a.nickname)) >= 3:
            text = re.sub(re.escape(a.nickname.strip()), " ", text, flags=re.IGNORECASE)
    return text


def one_account(accs: list[BankAccount], text: str) -> BankAccount | None:
    """The single account a piece of typed text names, by nickname first and then by bank."""
    named = named_accounts(accs, text)
    if len(named) == 1:
        return named[0]
    code = bank_code(_drop_nicknames(accs, text))
    same = [a for a in accs if a.bank == code]
    return same[0] if len(same) == 1 else None


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


# --- Accounts -------------------------------------------------------------------------------------------


def accounts(db: Session) -> list[BankAccount]:
    return list(db.scalars(select(BankAccount).order_by(BankAccount.id)))


def save_account(db: Session, data: dict, acc: BankAccount | None = None) -> BankAccount:
    code = data.get("bank")
    if code not in BANKS:
        raise PersonalError("เลือกธนาคาร")
    try:
        opening_date = date.fromisoformat(str(data.get("opening_date") or ""))
    except ValueError:
        raise PersonalError("วันที่ของเงินต้นไม่ถูกต้อง") from None
    acc = acc or BankAccount()
    acc.bank = code
    acc.nickname = (data.get("nickname") or "").strip()[:64]
    acc.account_no = _digits(data.get("account_no"))[:20]
    acc.opening_satang = to_satang(data.get("opening") if data.get("opening") not in (None, "") else 0)
    acc.opening_date = opening_date
    acc.is_default = bool(data.get("is_default"))
    db.add(acc)
    db.flush()
    if acc.is_default:  # only one default account
        for other in accounts(db):
            if other.id != acc.id:
                other.is_default = False
    db.commit()
    return acc


def delete_account(db: Session, acc: BankAccount) -> None:
    used = db.scalar(select(func.count()).select_from(PersonalEntry).where(or_(PersonalEntry.account_id == acc.id, PersonalEntry.to_account_id == acc.id)))
    if used:
        raise PersonalError(f"บัญชีนี้มีรายการอยู่ {used} รายการ ลบรายการก่อน หรือแก้ชื่อบัญชีแทน")
    db.delete(acc)
    db.commit()


def balance(db: Session, acc: BankAccount) -> int:
    """Opening balance plus everything on or after the opening date."""
    total = acc.opening_satang
    rows = db.scalars(
        select(PersonalEntry).where(
            PersonalEntry.entry_date >= acc.opening_date, or_(PersonalEntry.account_id == acc.id, PersonalEntry.to_account_id == acc.id)
        )
    )
    for e in rows:
        if e.kind == "income" and e.account_id == acc.id:
            total += e.amount_satang
        elif e.kind == "expense" and e.account_id == acc.id:
            total -= e.amount_satang
        elif e.kind == "transfer":
            if e.account_id == acc.id:
                total -= e.amount_satang
            if e.to_account_id == acc.id:
                total += e.amount_satang
    return total


def month_range(month: str) -> tuple[date, date]:
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", month or "")
    if not m:
        raise PersonalError("เดือนต้องอยู่ในรูปแบบ YYYY-MM")
    year, mon = int(m[1]), int(m[2])
    return date(year, mon, 1), (date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1))


def _comes_in(e: PersonalEntry, account_id: int) -> bool:
    return (e.kind == "income" and e.account_id == account_id) or (e.kind == "transfer" and e.to_account_id == account_id)


def _goes_out(e: PersonalEntry, account_id: int) -> bool:
    return e.kind in ("expense", "transfer") and e.account_id == account_id


def summary(db: Session, month: str) -> dict:
    start, end = month_range(month)
    rows = list(db.scalars(select(PersonalEntry).where(PersonalEntry.entry_date >= start, PersonalEntry.entry_date < end)))
    accs = accounts(db)
    out = []
    for a in accs:
        mine = [e for e in rows if e.account_id == a.id or e.to_account_id == a.id]
        out.append(
            {
                "id": a.id,
                "label": label(a),
                "bank": a.bank,
                "bank_name": bank_name(a.bank),
                "balance": balance(db, a) / 100,
                # Per account, money moved in from / out to the owner's other accounts counts too (like a statement);
                # the month's totals below leave transfers out, since they're neither income nor expense.
                "month_in": sum(e.amount_satang for e in mine if _comes_in(e, a.id)) / 100,
                "month_out": sum(e.amount_satang for e in mine if _goes_out(e, a.id)) / 100,
            }
        )
    return {
        "month": month,
        "accounts": out,
        "total": sum(a["balance"] for a in out),
        "month_in": sum(e.amount_satang for e in rows if e.kind == "income") / 100,
        "month_out": sum(e.amount_satang for e in rows if e.kind == "expense") / 100,
    }


# --- Entries --------------------------------------------------------------------------------------------


def entry_out(e: PersonalEntry, names: dict[int, str]) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "date": e.entry_date.isoformat(),
        "time": e.entry_time,
        "amount": e.amount_satang / 100,
        "account_id": e.account_id,
        "account": names.get(e.account_id, "-"),
        "to_account_id": e.to_account_id,
        "to_account": names.get(e.to_account_id, "") if e.to_account_id else "",
        "counterparty": e.counterparty,
        "note": e.note,
        "ref_no": e.ref_no or "",
        "source": e.source,
        "has_slip": bool(e.slip_file),
    }


def list_entries(db: Session, kind: str, month: str, account_id: int | None = None) -> list[PersonalEntry]:
    """A month's income or expenses. A transfer between the owner's accounts shows on both pages, as money in to
    its destination and money out of its source, but counts as neither."""
    start, end = month_range(month)
    q = select(PersonalEntry).where(PersonalEntry.entry_date >= start, PersonalEntry.entry_date < end, PersonalEntry.kind.in_([kind, "transfer"]))
    if account_id:
        side = PersonalEntry.to_account_id if kind == "income" else PersonalEntry.account_id
        q = q.where(or_(and_(PersonalEntry.kind == kind, PersonalEntry.account_id == account_id), and_(PersonalEntry.kind == "transfer", side == account_id)))
    return list(db.scalars(q.order_by(PersonalEntry.entry_date.desc(), PersonalEntry.entry_time.desc(), PersonalEntry.id.desc())))


def save_entry(db: Session, data: dict, entry: PersonalEntry | None = None) -> PersonalEntry:
    """Add or edit an entry from the dashboard."""
    kind = data.get("kind") or (entry.kind if entry else "")
    if kind not in KINDS:
        raise PersonalError("ประเภทรายการไม่ถูกต้อง")
    acc = db.get(BankAccount, int(data.get("account_id") or 0))
    if acc is None:
        raise PersonalError("เลือกบัญชี")
    to_acc = None
    if kind == "transfer":
        to_acc = db.get(BankAccount, int(data.get("to_account_id") or 0))
        if to_acc is None or to_acc.id == acc.id:
            raise PersonalError("เลือกบัญชีปลายทางที่ไม่ใช่บัญชีเดียวกัน")
    amount = to_satang(data.get("amount"))
    if amount <= 0:
        raise PersonalError("จำนวนเงินต้องมากกว่า 0")
    try:
        entry_date = date.fromisoformat(str(data.get("date") or ""))
    except ValueError:
        raise PersonalError("วันที่ไม่ถูกต้อง") from None
    e = entry or PersonalEntry(source="manual", origin="dashboard")
    e.kind, e.entry_date, e.amount_satang = kind, entry_date, amount
    e.entry_time = (data.get("time") or "")[:5]
    e.account_id, e.to_account_id = acc.id, to_acc.id if to_acc else None
    e.counterparty = (data.get("counterparty") or "").strip()[:256]
    e.note = (data.get("note") or "").strip()[:2000]
    db.add(e)
    db.commit()
    return e


def delete_entry(db: Session, entry: PersonalEntry) -> None:
    if entry.slip_file:
        try:
            (slip_dir() / entry.slip_file).unlink(missing_ok=True)
        except OSError:
            log.warning("could not delete slip %s", entry.slip_file)
    db.delete(entry)
    db.commit()


def slip_dir() -> Path:
    path = Path(get_settings().personal_slip_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path  # relative to backend/, like start.bat
    return path


def save_slip_picture(jpeg: bytes, day: date) -> str:
    rel = f"{day:%Y-%m}/{uuid.uuid4().hex}.jpg"
    target = slip_dir() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(jpeg)
    return rel


# --- Matching a slip to the owner's accounts --------------------------------------------------------------


def _common_run(a: str, b: str) -> int:
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def number_fits(account_no: str, printed: str | None) -> bool:
    """Whether a masked number from a slip ("xxx-x-x1234-x") can be this account."""
    acc = _digits(account_no)
    shown = re.sub(r"[^0-9xX*•]", "", printed or "")
    visible = _digits(shown)
    if not acc or not visible:
        return True  # nothing to compare: don't rule it out
    if len(acc) >= 8 and len(shown) == len(acc):
        return all(c == d for c, d in zip(shown, acc) if c.isdigit())
    return acc in visible or visible in acc or _common_run(acc, visible) >= 3


def match_accounts(accs: list[BankAccount], bank: str | None, printed: str | None, strict: bool = False) -> list[BankAccount]:
    """The owner's accounts a slip side can be. strict: the slip must show digits that fit (used for the other
    side of a slip, so a stranger at the same bank is never taken for the owner's own account)."""
    code = bank_code(bank)
    if code is None:
        return []
    if strict and not _digits(printed):
        return []
    return [a for a in accs if a.bank == code and number_fits(a.account_no, printed) and (not strict or _digits(a.account_no))]



def fund_matches(accs: list[BankAccount], name: str | None, bank: str | None, printed: str | None) -> list[BankAccount]:
    """Fund accounts a slip side can be: the side's name or bank names the fund (its nickname, e.g. "K-SET50"),
    or the fund has a number saved and the printed one fits it."""
    text = _squash(f"{name or ''} {bank or ''}")
    found = []
    for a in accs:
        if not is_fund(a.bank):
            continue
        nick = _squash(a.nickname)
        if (len(nick) >= 3 and nick in text) or (_digits(a.account_no) and _digits(printed) and number_fits(a.account_no, printed)):
            found.append(a)
    return found


def side_matches(accs: list[BankAccount], slip: dict, side: str, strict: bool = False) -> list[BankAccount]:
    """The owner's accounts (bank or fund) one side of a slip ("sender" / "receiver") can be."""
    found = match_accounts(accs, slip.get(f"{side}_bank"), slip.get(f"{side}_account"), strict)
    found += [a for a in fund_matches(accs, slip.get(f"{side}_name"), slip.get(f"{side}_bank"), slip.get(f"{side}_account")) if a not in found]
    return found


def guess_kind(accs: list[BankAccount], slip: dict) -> str | None:
    """Which side of a slip is the owner's: the sender -> "expense", the receiver -> "income". Both of them is a
    transfer, which the expense path records as one. None when the slip can't tell (then the chat asks)."""
    for strict in (True, False):
        sent = side_matches(accs, slip, "sender", strict)
        got = side_matches(accs, slip, "receiver", strict)
        if sent and not got:
            return "expense"
        if got and not sent:
            return "income"
        if len(sent) == 1 and len(got) == 1 and sent[0].id != got[0].id:
            return "expense"
        if sent and got:
            return None
    return None


# --- LINE: pending questions -------------------------------------------------------------------------------


@dataclass
class Pending:
    """A slip or typed line waiting for the owner's answer: which account it was or, in the "tk รับจ่าย" chat,
    whether it was income or expense."""

    kind: str  # "income" | "expense"; "" while asking which of the two
    amount: int
    entry_date: date
    entry_time: str = ""
    counterparty: str = ""
    note: str = ""
    ref_no: str | None = None
    source: str = "text"
    slip_file: str = ""
    choices: list[int] = field(default_factory=list)  # account ids, numbered from 1
    slip: dict | None = None  # asking income or expense: the slip as read, and its picture
    jpeg: bytes = b""
    raw: str = ""  # asking income or expense: the typed line
    at: float = field(default_factory=time.monotonic)


_pending: dict[str, Pending] = {}  # LINE group or user id -> what's waiting


def _ask_which(key: str, p: Pending, accs: list[BankAccount], why: str) -> str:
    p.choices = [a.id for a in accs]
    _pending[key] = p
    lines = "\n".join(f"{n}) {label(a)}" for n, a in enumerate(accs, 1))
    return f"{why} {money(p.amount)} บาท ใช้บัญชีไหนคะ พิมพ์เลขลำดับได้เลย\n{lines}"


def _ask_kind(key: str, p: Pending, why: str) -> str:
    _pending[key] = p
    return f"{why} {money(p.amount)} บาท เป็นรายรับหรือรายจ่ายคะ พิมพ์เลขลำดับได้เลย\n1) รายรับ\n2) รายจ่าย"


def _answer_pending(db: Session, key: str, text: str) -> str | None:
    """A number answering the question waiting in this chat; None when it isn't one."""
    p = _pending.get(key)
    if p and time.monotonic() - p.at > PENDING_SECONDS:
        _pending.pop(key, None)
        p = None
    if p is None or not text.isdigit():
        return None
    n = int(text)
    if not p.kind:
        if n not in (1, 2):
            return None
        _pending.pop(key, None)
        kind = "income" if n == 1 else "expense"
        if p.slip is not None:
            checked = _check_slip(db, p.slip)
            return checked if isinstance(checked, str) else _slip_as(db, key, kind, p.slip, p.jpeg, checked, in_group=False)
        return _typed_entry(db, key, kind, p.raw)
    if not 1 <= n <= len(p.choices):
        return None
    _pending.pop(key, None)
    acc = db.get(BankAccount, p.choices[n - 1])
    return _record(db, p, acc) if acc else "ไม่พบบัญชีนั้นแล้วค่ะ"


def _record(db: Session, p: Pending, acc: BankAccount, to_acc: BankAccount | None = None) -> str:
    kind = "transfer" if to_acc else p.kind
    e = PersonalEntry(
        kind=kind,
        entry_date=p.entry_date,
        entry_time=p.entry_time,
        amount_satang=p.amount,
        account_id=acc.id,
        to_account_id=to_acc.id if to_acc else None,
        counterparty=p.counterparty[:256],
        note=p.note[:2000],
        ref_no=p.ref_no,
        source=p.source,
        origin=p.kind,
        slip_file=p.slip_file,
    )
    db.add(e)
    db.commit()
    if kind == "transfer":
        return (
            f"บันทึกโอนระหว่างบัญชี {money(p.amount)} บาท จาก {label(acc)} ไป {label(to_acc)} แล้วค่ะ TK\n"
            f"คงเหลือ {label(acc)} {money(balance(db, acc))} บาท / {label(to_acc)} {money(balance(db, to_acc))} บาท"
        )
    word, way = ("รายรับ", "เข้า") if kind == "income" else ("รายจ่าย", "จาก")
    return f"บันทึก{word} {money(p.amount)} บาท {way} {label(acc)} แล้วค่ะ TK\nคงเหลือ {money(balance(db, acc))} บาท"


# --- LINE: slips -------------------------------------------------------------------------------------------


def _check_slip(db: Session, slip: dict) -> str | tuple[int, date, str | None]:
    """(amount, date, reference) of a slip worth recording, or the reply saying why it isn't."""
    if not slip.get("is_slip") or not slip.get("amount"):
        return "ไม่แน่ใจว่าเป็นสลิปโอนเงินค่ะ ลองส่งรูปที่ชัดขึ้น หรือพิมพ์เอง เช่น \"ค่าข้าว 120 กสิกร\""
    try:
        amount = to_satang(slip["amount"])
    except PersonalError:
        amount = 0
    try:
        entry_date = date.fromisoformat(slip.get("date") or "")
    except ValueError:
        entry_date = today()
    if amount <= 0:
        return "อ่านจำนวนเงินในสลิปไม่ได้ค่ะ ลองส่งรูปที่ชัดขึ้น หรือพิมพ์เอง"
    ref = (slip.get("reference") or "").strip()[:64] or None
    dup = db.scalar(select(PersonalEntry).where(PersonalEntry.ref_no == ref)) if ref else None
    if dup:
        return f"สลิปนี้บันทึกไปแล้วค่ะ ({dup.entry_date:%d/%m/%Y} {money(dup.amount_satang)} บาท)"
    if not accounts(db):
        return "ยังไม่มีบัญชีธนาคารในระบบค่ะ เพิ่มที่หน้า 💳 การเงินส่วนตัว บน Dashboard ก่อนนะคะ"
    return amount, entry_date, ref


def record_slip(db: Session, group: str, kind: str, slip: dict, jpeg: bytes) -> str:
    """A slip picture sent to "สลิปรายรับ" (kind income) or "สลิปรายจ่าย" (kind expense), already read by Claude."""
    checked = _check_slip(db, slip)
    if isinstance(checked, str):
        return checked
    return _slip_as(db, group, kind, slip, jpeg, checked, in_group=True)


def record_chat_slip(db: Session, chat: str, slip: dict, jpeg: bytes) -> str:
    """A slip picture sent to the "tk รับจ่าย" chat: income, expense or a transfer, from whose accounts its two
    sides are. When that can't be told, it asks."""
    checked = _check_slip(db, slip)
    if isinstance(checked, str):
        return checked
    kind = guess_kind(accounts(db), slip)
    if kind is None:
        return _ask_kind(chat, Pending(kind="", amount=checked[0], entry_date=checked[1], slip=slip, jpeg=jpeg), "สลิป")
    return _slip_as(db, chat, kind, slip, jpeg, checked, in_group=False)


def _slip_as(db: Session, key: str, kind: str, slip: dict, jpeg: bytes, checked: tuple[int, date, str | None], in_group: bool) -> str:
    """Record a slip as income or expense (or a transfer, when the other side is the owner's too)."""
    amount, entry_date, ref = checked
    accs = accounts(db)
    mine_side, other_side = ("receiver", "sender") if kind == "income" else ("sender", "receiver")
    mine = side_matches(accs, slip, mine_side)
    other = side_matches(accs, slip, other_side, strict=True)
    if len(other) == 1:
        # The other side is surely this account (its digits fit), so it can't be this side too.
        mine = [a for a in mine if a.id != other[0].id]
    if not mine and len(other) == 1:
        where = "ออกจาก" if kind == "income" else "เข้า"
        hint = "ส่งผิดกลุ่มหรือเปล่าคะ " if in_group else ""
        return f"สลิปนี้เป็นเงิน{where} {label(other[0])} {hint}ยังไม่ได้บันทึกนะคะ"

    them = slip.get("sender_name") if kind == "income" else slip.get("receiver_name")
    p = Pending(
        kind=kind,
        amount=amount,
        entry_date=entry_date,
        entry_time=(slip.get("time") or "")[:5],
        counterparty=(them or "").strip(),
        note=(slip.get("memo") or "").strip(),
        ref_no=ref,
        source="slip",
        slip_file=save_slip_picture(jpeg, entry_date),
    )
    if not mine and len(accs) == 1:
        mine = accs  # nothing to choose from
    if len(mine) == 1:
        # Both ends are the owner's own accounts: a transfer, not income or expense.
        if len(other) == 1 and other[0].id != mine[0].id:
            src, dst = (other[0], mine[0]) if kind == "income" else (mine[0], other[0])
            return _record(db, p, src, dst)
        return _record(db, p, mine[0])
    word = "รายรับ" if kind == "income" else "รายจ่าย"
    return _ask_which(key, p, mine or accs, f"{word}จากสลิป")


# --- LINE: typed lines -------------------------------------------------------------------------------------


def parse_text(text: str) -> tuple[int | None, str | None, str]:
    """"ค่าข้าว 120 กสิกร" -> (12000 satang, "KBANK", "ค่าข้าว"); the last number is the amount."""
    numbers = list(_AMOUNT.finditer(text))
    if not numbers:
        return None, None, text.strip()
    m = numbers[-1]
    amount = to_satang(m[0])
    rest = (text[: m.start()] + " " + text[m.end() :]).strip()
    code = bank_code(rest)
    if code:
        for alias, c in _ALIASES:
            if c == code:
                rest = re.sub(re.escape(alias), " ", rest, flags=re.IGNORECASE) if alias.isascii() else rest.replace(alias, " ")
        rest = re.sub(r"\b(ธนาคาร|ธ\.|บาท)\b", " ", rest)
    rest = re.sub(r"\s+", " ", rest.replace("บาท", " ")).strip(" -:,")
    return amount, code, rest


def _typed_entry(db: Session, key: str, kind: str, text: str) -> str | None:
    """"ค่าข้าว 120 กสิกร" as income or expense; None when there's no amount in it (ordinary chat)."""
    accs = accounts(db)
    named = named_accounts(accs, text)
    amount, code, note = parse_text(_drop_nicknames(accs, text))
    if amount is None:
        return None
    if not note and not code and not named:
        # A bare number is more likely a late answer to an expired question than an entry.
        return "พิมพ์รายละเอียดกับจำนวนเงินด้วยนะคะ เช่น \"ค่าข้าว 120\" หรือ \"ค่าข้าว 120 กสิกร\""
    if amount <= 0:
        return "จำนวนเงินต้องมากกว่า 0 ค่ะ"
    p = Pending(kind=kind, amount=amount, entry_date=today(), note=note)
    if not accs:
        return "ยังไม่มีบัญชีธนาคารในระบบค่ะ เพิ่มที่หน้า 💳 การเงินส่วนตัว บน Dashboard ก่อนนะคะ"
    if len(named) == 1:
        return _record(db, p, named[0])
    if code:
        same = [a for a in accs if a.bank == code]
        if len(same) == 1:
            return _record(db, p, same[0])
        return _ask_which(key, p, same or accs, f"\"{note or text}\"")
    default = _default_account(accs)
    if default:
        return _record(db, p, default)
    return _ask_which(key, p, accs, f"\"{note or text}\"")


def _default_account(accs: list[BankAccount]) -> BankAccount | None:
    return next((a for a in accs if a.is_default), None) or (accs[0] if len(accs) == 1 else None)


TRANSFER_HELP = "บอกจำนวนเงิน บัญชีต้นทาง และปลายทางด้วยนะคะ เช่น \"โอน 5000 กสิกร ไป กองทุน A\""


def _typed_transfer(db: Session, text: str) -> str:
    """"5000 กสิกร ไป K-SET50" (after "โอน"): money moved between two of the owner's accounts or funds."""
    accs = accounts(db)
    m = re.search(r"\s*(?:ไปยัง|ไปที่|ไป|เข้า)\s*", text)
    if m is None:
        return TRANSFER_HELP
    left, right = text[: m.start()], text[m.end() :]
    to = one_account(accs, right)
    numbers = list(_AMOUNT.finditer(_drop_nicknames(accs, left))) or list(_AMOUNT.finditer(_drop_nicknames(accs, right)))
    src = one_account(accs, left) or _default_account(accs)
    if not numbers or to is None or src is None or src.id == to.id:
        return TRANSFER_HELP
    amount = to_satang(numbers[0][0])
    if amount <= 0:
        return "จำนวนเงินต้องมากกว่า 0 ค่ะ"
    return _record(db, Pending(kind="expense", amount=amount, entry_date=today()), src, to)


def _delete_latest(db: Session, kind: str | None) -> str:
    """Delete the latest entry LINE recorded (from one slip group, or any when kind is None)."""
    q = select(PersonalEntry).where(PersonalEntry.source.in_(["slip", "text"]))
    if kind:
        q = q.where(PersonalEntry.origin == kind)
    last = db.scalar(q.order_by(PersonalEntry.id.desc()))
    if last is None:
        return "ยังไม่มีรายการจากกลุ่มนี้ให้ลบค่ะ" if kind else "ยังไม่มีรายการจาก LINE ให้ลบค่ะ"
    info = f"{money(last.amount_satang)} บาท ({last.entry_date:%d/%m/%Y})"
    delete_entry(db, last)
    return f"ลบรายการล่าสุด {info} แล้วค่ะ TK"


def _balances(db: Session) -> str:
    accs = accounts(db)
    if not accs:
        return "ยังไม่มีบัญชีธนาคารในระบบค่ะ"
    rows = [(label(a), balance(db, a)) for a in accs]
    lines = "\n".join(f"{name}: {money(b)} บาท" for name, b in rows)
    return f"ยอดคงเหลือค่ะ TK\n{lines}\nรวม {money(sum(b for _, b in rows))} บาท"


def handle_text(db: Session, group: str, kind: str, text: str) -> str | None:
    """A typed line in a slip group: an answer to a pending question, a command, or an entry like "ค่าข้าว 120 กสิกร"."""
    text = text.strip()
    answer = _answer_pending(db, group, text)
    if answer is not None:
        return answer
    if text in DELETE_WORDS:
        return _delete_latest(db, kind)
    if text in BALANCE_WORDS:
        return _balances(db)
    return _typed_entry(db, group, kind, text)


CHAT_HELP = (
    "จาร์วิสบันทึกรายรับรายจ่ายให้ค่ะ TK\n"
    "- ส่งรูปสลิปมาได้เลย (ดูเองว่ารับหรือจ่าย)\n"
    "- หรือพิมพ์เอง เช่น \"รับ ค่าจ้าง 5000 กสิกร\" / \"จ่าย ค่าข้าว 120\" (ไม่บอกธนาคารจะใช้บัญชีหลัก)\n"
    "- โอนระหว่างบัญชี เช่น \"โอน 5000 กสิกร ไป กองทุน A\"\n"
    "- \"ยอด\" ดูยอดคงเหลือ / \"ลบล่าสุด\" ลบรายการล่าสุด"
)
_CHAT_WORD = re.compile(r"^(รายรับ|รายจ่าย|รับ|จ่าย|โอน)(?=[\s\d]|$)")


def handle_chat_text(db: Session, chat: str, text: str) -> str:
    """A typed line in the "tk รับจ่าย" chat. It starts with รับ / จ่าย / โอน; without one, JARVIS asks which."""
    text = text.strip()
    answer = _answer_pending(db, chat, text)
    if answer is not None:
        return answer
    if text in DELETE_WORDS:
        return _delete_latest(db, None)
    if text in BALANCE_WORDS:
        return _balances(db)
    m = _CHAT_WORD.match(text)
    if m:
        rest = text[m.end() :].strip()
        if m[1] == "โอน":
            return _typed_transfer(db, rest)
        kind = "income" if m[1] in ("รับ", "รายรับ") else "expense"
        return _typed_entry(db, chat, kind, rest) or f"พิมพ์รายละเอียดกับจำนวนเงินด้วยนะคะ เช่น \"{m[1]} ค่าข้าว 120\""
    accs = accounts(db)
    amount, code, note = parse_text(_drop_nicknames(accs, text))
    if amount is None:
        return CHAT_HELP
    if not note and not code and not named_accounts(accs, text):
        return "พิมพ์รายละเอียดกับจำนวนเงินด้วยนะคะ เช่น \"จ่าย ค่าข้าว 120\" หรือ \"รับ ค่าจ้าง 5000 กสิกร\""
    if amount <= 0:
        return "จำนวนเงินต้องมากกว่า 0 ค่ะ"
    return _ask_kind(chat, Pending(kind="", amount=amount, entry_date=today(), raw=text), f"\"{note or text}\"")


def clear_pending() -> None:
    _pending.clear()
