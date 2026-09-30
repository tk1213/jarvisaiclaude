"""Business documents through FlowAccount (spec §4.3, §6).

Issuing is two steps so nothing reaches FlowAccount without the user saying yes:
prepare() stores a draft in `documents_log` and returns a summary for JARVIS to read back;
issue() sends that draft, and only in a later message than the one that prepared it.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.integrations.flowaccount import DOC_PATHS, get_flowaccount_client
from app.models import Contact, DocumentLog, User

DOC_NAMES = {"quotation": "ใบเสนอราคา", "billing_note": "ใบวางบิล", "tax_invoice": "ใบกำกับภาษี", "receipt": "ใบเสร็จรับเงิน"}
VAT_RATE = Decimal("0.07")
DRAFT_HOURS = 24
# 1 = individual, 3 = juristic person (FlowAccount contactGroup)
_COMPANY = re.compile(r"บริษัท|หจก|ห้างหุ้นส่วน|จำกัด|co\.|ltd|limited|inc\.?", re.IGNORECASE)


class DocumentError(ValueError):
    """Something JARVIS should tell the user (missing data, not confirmed, no permission)."""


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def totals(items: list[dict], vat: bool, vat_inclusive: bool) -> dict:
    """subTotal / vatAmount / grandTotal the way FlowAccount lays them out (no document discount)."""
    sub = sum((_money(i["quantity"]) * _money(i["unit_price"]) for i in items), Decimal("0"))
    sub = _money(sub)
    if not vat:
        vat_amount, grand = Decimal("0.00"), sub
    elif vat_inclusive:
        vat_amount, grand = _money(sub * VAT_RATE / (1 + VAT_RATE)), sub
    else:
        vat_amount = _money(sub * VAT_RATE)
        grand = sub + vat_amount
    return {"sub_total": sub, "vat_amount": vat_amount, "grand_total": grand}


def _clean_customer(customer: dict) -> dict:
    name = (customer.get("name") or "").strip()
    if not name:
        raise DocumentError("ต้องมีชื่อลูกค้า")
    tax_id = re.sub(r"\D", "", customer.get("tax_id") or "")
    if tax_id and len(tax_id) != 13:
        raise DocumentError("เลขผู้เสียภาษีต้องมี 13 หลัก")
    return {
        "name": name,
        "tax_id": tax_id or None,
        "address": (customer.get("address") or "").strip() or None,
        "branch": (customer.get("branch") or "").strip() or None,
        "email": (customer.get("email") or "").strip() or None,
        "phone": (customer.get("phone") or "").strip() or None,
    }


def _clean_items(items: list[dict]) -> list[dict]:
    if not items:
        raise DocumentError("ต้องมีรายการสินค้าหรือบริการอย่างน้อย 1 รายการ")
    out = []
    for i in items:
        name = (i.get("name") or "").strip()
        qty, price = i.get("quantity"), i.get("unit_price")
        if not name or qty is None or price is None:
            raise DocumentError("ทุกรายการต้องมีชื่อ จำนวน และราคาต่อหน่วย")
        if Decimal(str(qty)) <= 0 or Decimal(str(price)) < 0:
            raise DocumentError(f"จำนวนหรือราคาของ '{name}' ไม่ถูกต้อง")
        out.append({"name": name, "quantity": float(qty), "unit_price": float(price), "unit": (i.get("unit") or "").strip()})
    return out


def prepare(
    db: Session,
    user: User,
    channel: str,
    doc_type: str,
    customer: dict,
    items: list[dict],
    vat: bool,
    vat_inclusive: bool,
    credit_days: int,
    remarks: str,
    today: date,
) -> DocumentLog:
    if not user.can_issue_documents:
        raise DocumentError("ผู้ใช้นี้ไม่มีสิทธิ์ออกเอกสารการเงิน")
    if doc_type not in DOC_PATHS:
        raise DocumentError(f"ไม่รู้จักเอกสารประเภท {doc_type}")
    if not 0 <= credit_days <= 365:
        raise DocumentError("เครดิตต้องอยู่ระหว่าง 0-365 วัน")
    cust = _clean_customer(customer)
    lines = _clean_items(items)
    t = totals(lines, vat, vat_inclusive)
    cash = doc_type == "receipt" or credit_days == 0
    payload = {
        "contactName": cust["name"],
        "contactAddress": cust["address"] or "",
        "contactTaxId": cust["tax_id"] or "",
        "contactBranch": cust["branch"] or "",
        "contactEmail": cust["email"] or "",
        "contactNumber": cust["phone"] or "",
        "contactGroup": 3 if cust["tax_id"] and _COMPANY.search(cust["name"]) else 1,
        "publishedOn": today.isoformat(),
        "creditType": 3 if cash else 1,
        "creditDays": 0 if cash else credit_days,
        "dueDate": (today + timedelta(days=0 if cash else credit_days)).isoformat(),
        "isVat": vat,
        "isVatInclusive": vat and vat_inclusive,
        "subTotal": float(t["sub_total"]),
        "discountAmount": 0,
        "totalAfterDiscount": float(t["sub_total"]),
        "vatAmount": float(t["vat_amount"]),
        "grandTotal": float(t["grand_total"]),
        "remarks": remarks.strip(),
        "items": [
            {
                "type": 3,  # non-inventory: a spoken order shouldn't move stock counts
                "name": i["name"],
                "quantity": i["quantity"],
                "unitName": i["unit"],
                "pricePerUnit": i["unit_price"],
                "total": float(_money(i["quantity"]) * _money(i["unit_price"])),
            }
            for i in lines
        ],
    }
    doc = DocumentLog(
        user_id=user.id,
        channel=channel,
        doc_type=doc_type,
        total_amount=str(t["grand_total"]),
        status="draft",
        payload={"flowaccount": payload, "customer": cust},
    )
    db.add(doc)
    db.commit()
    return doc


def summary(doc: DocumentLog) -> dict:
    p = doc.payload["flowaccount"]
    return {
        "draft_id": doc.id,
        "document": DOC_NAMES[doc.doc_type],
        "status": doc.status,
        "serial": doc.document_serial,
        "customer": doc.payload["customer"],
        "date": p["publishedOn"],
        "due_date": p["dueDate"],
        "items": [{"name": i["name"], "quantity": i["quantity"], "unit": i["unitName"], "unit_price": i["pricePerUnit"], "total": i["total"]} for i in p["items"]],
        "sub_total": p["subTotal"],
        "vat": p["vatAmount"] if p["isVat"] else None,
        "vat_inclusive": p["isVatInclusive"],
        "grand_total": p["grandTotal"],
        "remarks": p["remarks"],
    }


def issue(db: Session, user: User, draft_id: int, turn_started: datetime) -> DocumentLog:
    """Send a draft to FlowAccount. Refused unless the draft was prepared before the current message,
    i.e. the user has seen the summary and answered it."""
    if not user.can_issue_documents:
        raise DocumentError("ผู้ใช้นี้ไม่มีสิทธิ์ออกเอกสารการเงิน")
    doc = db.get(DocumentLog, draft_id)
    if doc is None or doc.user_id != user.id:
        raise DocumentError(f"ไม่พบร่างเอกสารหมายเลข {draft_id}")
    if doc.status != "draft":
        raise DocumentError(f"เอกสารนี้ออกไปแล้ว (เลขที่ {doc.document_serial})")
    created = _aware(doc.created_at)
    if created >= turn_started:
        raise DocumentError("ต้องสรุปเอกสารให้ผู้ใช้ตรวจและรอผู้ใช้ยืนยันในข้อความถัดไปก่อน ห้ามออกเอกสารในข้อความเดียวกับที่เตรียม")
    if datetime.now(timezone.utc) - created > timedelta(hours=DRAFT_HOURS):
        raise DocumentError("ร่างนี้เก่าเกิน 24 ชั่วโมงแล้ว ให้เตรียมเอกสารใหม่")

    issued = get_flowaccount_client().create_document(doc.doc_type, doc.payload["flowaccount"])
    doc.status = "issued"
    doc.document_serial = issued.serial or None
    doc.flowaccount_document_id = issued.record_id or None
    doc.contact_id = remember_contact(db, doc.payload["customer"]).id
    db.commit()
    return doc


def remember_contact(db: Session, cust: dict) -> Contact:
    """Long-term memory of customers (spec phase 2): the next document can reuse their details."""
    contact = None
    if cust.get("tax_id"):
        contact = db.scalar(select(Contact).where(Contact.tax_id == cust["tax_id"]))
    if contact is None:
        contact = db.scalar(select(Contact).where(func.lower(Contact.name) == cust["name"].lower()))
    if contact is None:
        contact = Contact(name=cust["name"])
        db.add(contact)
    for field in ("tax_id", "address", "email", "phone"):
        if cust.get(field):
            setattr(contact, field, cust[field])
    db.flush()
    return contact


def find_customers(db: Session, query: str, limit: int = 5) -> list[Contact]:
    q = f"%{query.strip()}%"
    return list(db.scalars(select(Contact).where(or_(Contact.name.ilike(q), Contact.tax_id.ilike(q))).order_by(Contact.updated_at.desc()).limit(limit)))


def recent(db: Session, user: User, limit: int = 10) -> list[DocumentLog]:
    return list(db.scalars(select(DocumentLog).where(DocumentLog.user_id == user.id).order_by(DocumentLog.id.desc()).limit(limit)))
