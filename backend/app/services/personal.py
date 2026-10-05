"""Personal money (the 💳 page): bank accounts, income/expense entries, balances, and what the LINE groups
"สลิปรายรับ" / "สลิปรายจ่าย" record from a slip picture or a typed line such as "ค่าข้าว 120 กสิกร".

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

from sqlalchemy import func, or_, select
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
                "month_in": sum(e.amount_satang for e in mine if e.kind == "income") / 100,
                "month_out": sum(e.amount_satang for e in mine if e.kind == "expense") / 100,
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
    """A month's income or expenses; transfers show on both pages (they move money but count as neither)."""
    start, end = month_range(month)
    q = select(PersonalEntry).where(PersonalEntry.entry_date >= start, PersonalEntry.entry_date < end, PersonalEntry.kind.in_([kind, "transfer"]))
    if account_id:
        q = q.where(or_(PersonalEntry.account_id == account_id, PersonalEntry.to_account_id == account_id))
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


# --- LINE: pending questions -------------------------------------------------------------------------------


@dataclass
class Pending:
    """A slip or typed line waiting for the owner to say which account it was."""

    kind: str  # "income" | "expense"
    amount: int
    entry_date: date
    entry_time: str
    counterparty: str
    note: str
    ref_no: str | None
    source: str
    slip_file: str
    choices: list[int] = field(default_factory=list)
    at: float = field(default_factory=time.monotonic)


_pending: dict[str, Pending] = {}  # LINE group id -> what's waiting


def _ask_which(group: str, p: Pending, accs: list[BankAccount], why: str) -> str:
    p.choices = [a.id for a in accs]
    _pending[group] = p
    lines = "\n".join(f"{n}) {label(a)}" for n, a in enumerate(accs, 1))
    return f"{why} {money(p.amount)} บาท ใช้บัญชีไหนคะ พิมพ์เลขลำดับได้เลย\n{lines}"


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


def record_slip(db: Session, group: str, kind: str, slip: dict, jpeg: bytes) -> str:
    """A slip picture sent to "สลิปรายรับ" (kind income) or "สลิปรายจ่าย" (kind expense), already read by Claude."""
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

    accs = accounts(db)
    if not accs:
        return "ยังไม่มีบัญชีธนาคารในระบบค่ะ เพิ่มที่หน้า 💳 การเงินส่วนตัว บน Dashboard ก่อนนะคะ"
    mine_side, other_side = ("receiver", "sender") if kind == "income" else ("sender", "receiver")
    mine = match_accounts(accs, slip.get(f"{mine_side}_bank"), slip.get(f"{mine_side}_account"))
    other = match_accounts(accs, slip.get(f"{other_side}_bank"), slip.get(f"{other_side}_account"), strict=True)
    if len(other) == 1:
        # The other side is surely this account (its digits fit), so it can't be this side too.
        mine = [a for a in mine if a.id != other[0].id]
    if not mine and len(other) == 1:
        where = "ออกจาก" if kind == "income" else "เข้า"
        return f"สลิปนี้เป็นเงิน{where} {label(other[0])} ส่งผิดกลุ่มหรือเปล่าคะ ยังไม่ได้บันทึกนะคะ"

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
    if len(mine) == 1:
        # Both ends are the owner's own accounts: a transfer, not income or expense.
        if len(other) == 1 and other[0].id != mine[0].id:
            src, dst = (other[0], mine[0]) if kind == "income" else (mine[0], other[0])
            return _record(db, p, src, dst)
        return _record(db, p, mine[0])
    word = "รายรับ" if kind == "income" else "รายจ่าย"
    return _ask_which(group, p, mine or accs, f"{word}จากสลิป")


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


def handle_text(db: Session, group: str, kind: str, text: str) -> str | None:
    """A typed line in a slip group: an answer to a pending question, a command, or an entry like "ค่าข้าว 120 กสิกร"."""
    text = text.strip()
    pending = _pending.get(group)
    if pending and time.monotonic() - pending.at > PENDING_SECONDS:
        _pending.pop(group, None)
        pending = None
    if pending and text.isdigit() and 1 <= int(text) <= len(pending.choices):
        _pending.pop(group, None)
        acc = db.get(BankAccount, pending.choices[int(text) - 1])
        return _record(db, pending, acc) if acc else "ไม่พบบัญชีนั้นแล้วค่ะ"

    if text in DELETE_WORDS:
        last = db.scalar(
            select(PersonalEntry).where(PersonalEntry.origin == kind, PersonalEntry.source.in_(["slip", "text"])).order_by(PersonalEntry.id.desc())
        )
        if last is None:
            return "ยังไม่มีรายการจากกลุ่มนี้ให้ลบค่ะ"
        info = f"{money(last.amount_satang)} บาท ({last.entry_date:%d/%m/%Y})"
        delete_entry(db, last)
        return f"ลบรายการล่าสุด {info} แล้วค่ะ TK"
    if text in BALANCE_WORDS:
        accs = accounts(db)
        if not accs:
            return "ยังไม่มีบัญชีธนาคารในระบบค่ะ"
        rows = [(label(a), balance(db, a)) for a in accs]
        lines = "\n".join(f"{name}: {money(b)} บาท" for name, b in rows)
        return f"ยอดคงเหลือค่ะ TK\n{lines}\nรวม {money(sum(b for _, b in rows))} บาท"

    amount, code, note = parse_text(text)
    if amount is None:
        return None  # ordinary chat in the group: stay quiet
    if not note and not code:
        # A bare number is more likely a late answer to an expired question than an entry.
        return "พิมพ์รายละเอียดกับจำนวนเงินด้วยนะคะ เช่น \"ค่าข้าว 120\" หรือ \"ค่าข้าว 120 กสิกร\""
    if amount <= 0:
        return "จำนวนเงินต้องมากกว่า 0 ค่ะ"
    p = Pending(kind=kind, amount=amount, entry_date=today(), entry_time="", counterparty="", note=note, ref_no=None, source="text", slip_file="")
    accs = accounts(db)
    if not accs:
        return "ยังไม่มีบัญชีธนาคารในระบบค่ะ เพิ่มที่หน้า 💳 การเงินส่วนตัว บน Dashboard ก่อนนะคะ"
    if code:
        same = [a for a in accs if a.bank == code]
        if len(same) == 1:
            return _record(db, p, same[0])
        return _ask_which(group, p, same or accs, f"\"{note or text}\"")
    default = next((a for a in accs if a.is_default), None) or (accs[0] if len(accs) == 1 else None)
    if default:
        return _record(db, p, default)
    return _ask_which(group, p, accs, f"\"{note or text}\"")


def clear_pending() -> None:
    _pending.clear()
