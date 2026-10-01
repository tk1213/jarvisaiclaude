import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.messages import Channel, InboundMessage
from app.db import SessionLocal
from app.integrations import flowaccount as fa
from app.integrations.tuya import get_tuya_client
from app.models import Contact, DocumentLog, User
from app.services import documents as docs
from tests.test_orchestrator import FakeClaude, make, message, text, tool_use

CUSTOMER = {"name": "บริษัท ลูกค้า จำกัด", "tax_id": "0105555555555", "address": "กรุงเทพฯ", "branch": None, "email": None, "phone": None}
ITEMS = [{"name": "ค่าออกแบบ", "quantity": 2, "unit_price": 1000, "unit": "งาน"}]


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def owner(db):
    user = User(username="owner", password_hash="x", can_issue_documents=True)
    db.add(user)
    db.commit()
    return user


def test_totals():
    items = [{"quantity": 2, "unit_price": 1000}]
    assert docs.totals(items, vat=True, vat_inclusive=False) == {"sub_total": Decimal("2000.00"), "vat_amount": Decimal("140.00"), "grand_total": Decimal("2140.00")}
    assert docs.totals([{"quantity": 1, "unit_price": 1070}], vat=True, vat_inclusive=True)["vat_amount"] == Decimal("70.00")
    assert docs.totals([{"quantity": 3, "unit_price": 33.335}], vat=False, vat_inclusive=False)["grand_total"] == Decimal("100.02")


def test_prepare_builds_flowaccount_payload(db, owner):
    doc = docs.prepare(db, owner, "line", "quotation", CUSTOMER, ITEMS, True, False, 30, "ยืนราคา 30 วัน", date(2026, 10, 1))
    p = doc.payload["flowaccount"]
    assert doc.status == "draft" and doc.total_amount == "2140.00" and doc.channel == "line"
    assert p["contactGroup"] == 3 and p["contactTaxId"] == "0105555555555"
    assert (p["publishedOn"], p["dueDate"], p["creditType"], p["creditDays"]) == ("2026-10-01", "2026-10-31", 1, 30)
    assert (p["subTotal"], p["vatAmount"], p["grandTotal"], p["isVat"]) == (2000.0, 140.0, 2140.0, True)
    assert p["items"] == [{"type": 3, "name": "ค่าออกแบบ", "quantity": 2.0, "unitName": "งาน", "pricePerUnit": 1000.0, "total": 2000.0}]
    # A receipt is always cash.
    receipt = docs.prepare(db, owner, "line", "receipt", CUSTOMER, ITEMS, False, False, 30, "", date(2026, 10, 1)).payload["flowaccount"]
    assert (receipt["creditType"], receipt["creditDays"], receipt["dueDate"]) == (3, 0, "2026-10-01")


@pytest.mark.parametrize(
    ("customer", "items", "error"),
    [
        ({**CUSTOMER, "name": " "}, ITEMS, "ชื่อลูกค้า"),
        ({**CUSTOMER, "tax_id": "123"}, ITEMS, "13 หลัก"),
        (CUSTOMER, [], "อย่างน้อย 1"),
        (CUSTOMER, [{**ITEMS[0], "quantity": 0}], "ไม่ถูกต้อง"),
    ],
)
def test_prepare_rejects_bad_input(db, owner, customer, items, error):
    with pytest.raises(docs.DocumentError, match=error):
        docs.prepare(db, owner, "dashboard", "quotation", customer, items, False, False, 0, "", date(2026, 10, 1))


def test_needs_document_permission(db):
    user = User(username="kid", password_hash="x", can_issue_documents=False)
    db.add(user)
    db.commit()
    with pytest.raises(docs.DocumentError, match="สิทธิ์"):
        docs.prepare(db, user, "dashboard", "quotation", CUSTOMER, ITEMS, False, False, 0, "", date(2026, 10, 1))


def test_issue_requires_a_later_message(db, owner):
    before = datetime.now(timezone.utc)
    doc = docs.prepare(db, owner, "dashboard", "quotation", CUSTOMER, ITEMS, True, False, 30, "", date(2026, 10, 1))
    with pytest.raises(docs.DocumentError, match="ยืนยัน"):
        docs.issue(db, owner, doc.id, turn_started=before)
    issued = docs.issue(db, owner, doc.id, turn_started=datetime.now(timezone.utc))
    assert issued.status == "issued" and issued.document_serial.startswith("QT-MOCK-")
    with pytest.raises(docs.DocumentError, match="ออกไปแล้ว"):
        docs.issue(db, owner, doc.id, turn_started=datetime.now(timezone.utc))
    # The customer is remembered for next time.
    assert [c.name for c in docs.find_customers(db, "ลูกค้า")] == ["บริษัท ลูกค้า จำกัด"]
    assert db.get(Contact, issued.contact_id).tax_id == "0105555555555"


def test_old_drafts_expire(db, owner):
    doc = docs.prepare(db, owner, "dashboard", "quotation", CUSTOMER, ITEMS, False, False, 0, "", date(2026, 10, 1))
    doc.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    with pytest.raises(docs.DocumentError, match="24 ชั่วโมง"):
        docs.issue(db, owner, doc.id, turn_started=datetime.now(timezone.utc))


def test_confirmation_flow_through_jarvis(db, owner):
    tuya = get_tuya_client()
    prepare_input = {"doc_type": "quotation", "customer": CUSTOMER, "items": ITEMS, "vat": True, "vat_inclusive": False, "credit_days": 30, "remarks": None}
    fake = FakeClaude(
        [
            # Turn 1: prepares, then (wrongly) tries to issue straight away; the tool refuses.
            message([tool_use("t1", "prepare_document", prepare_input)], "tool_use"),
            message([tool_use("t2", "issue_document", {"draft_id": 1})], "tool_use"),
            message([text("ใบเสนอราคา 2,140.00 บาท ยืนยันออกเอกสารไหมคะ TK")], "end_turn"),
            # Turn 2: the user confirmed.
            message([tool_use("t3", "issue_document", {"draft_id": 1})], "tool_use"),
            message([text("ออกใบเสนอราคาแล้วค่ะ TK")], "end_turn"),
        ]
    )
    orch = make(fake)
    first = orch.handle(db, tuya, owner, InboundMessage(user_id=owner.id, channel=Channel.dashboard, text="ออกใบเสนอราคาให้บริษัท ลูกค้า"))
    assert [(c.name, c.ok) for c in first.tool_calls] == [("prepare_document", True), ("issue_document", False)]
    assert db.get(DocumentLog, 1).status == "draft"

    second = orch.handle(db, tuya, owner, InboundMessage(user_id=owner.id, channel=Channel.dashboard, session_id=first.session_id, text="ยืนยัน"))
    assert [(c.name, c.ok) for c in second.tool_calls] == [("issue_document", True)]
    doc = db.get(DocumentLog, 1)
    assert doc.status == "issued" and doc.document_serial.startswith("QT-MOCK-")
    result = json.loads(fake.requests[3 + 1]["messages"][-1]["content"][0]["content"])
    assert result["serial"] == doc.document_serial and result["grand_total"] == 2140.0


def test_documents_endpoint(client, owner_headers):
    with SessionLocal() as s:
        user = s.query(User).filter_by(username="owner").one()
        docs.prepare(s, user, "line", "receipt", CUSTOMER, ITEMS, False, False, 0, "", date(2026, 10, 1))
    rows = client.get("/documents", headers=owner_headers).json()
    assert [(r["document"], r["status"], r["customer"], r["grand_total"], r["channel"]) for r in rows] == [
        ("ใบเสร็จรับเงิน", "draft", "บริษัท ลูกค้า จำกัด", "2000.00", "line")
    ]


class MemoryTokens:
    def __init__(self):
        self.saved = None

    def load(self):
        return self.saved

    def save(self, token, expires_at):
        self.saved = (token, expires_at)


def test_live_client_token_and_document():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/token":
            form = parse_qs(request.content.decode())
            assert form == {"grant_type": ["client_credentials"], "scope": ["flowaccount-api"], "client_id": ["cid"], "client_secret": ["sec"]}
            return httpx.Response(200, json={"access_token": f"tok{len(calls)}", "expires_in": 86400, "token_type": "bearer"})
        if request.headers["authorization"] == "Bearer tok1" and len(calls) == 2:
            return httpx.Response(401, json={"message": "expired"})
        assert request.url.path == "/v1/quotations"
        return httpx.Response(200, json={"status": True, "data": {"recordId": 42, "documentSerial": "QT2026100001"}})

    store = MemoryTokens()
    client = fa.FlowAccountClient("https://openapi.flowaccount.com/v1", "cid", "sec", "flowaccount-api", token_store=store, http=httpx.Client(transport=httpx.MockTransport(handler)))
    issued = client.create_document("quotation", {"contactName": "x"})
    assert (issued.record_id, issued.serial) == ("42", "QT2026100001")
    # 401 on the first try -> one new token and one retry.
    assert [c.url.path for c in calls] == ["/v1/token", "/v1/quotations", "/v1/token", "/v1/quotations"]
    assert calls[-1].headers["authorization"] == "Bearer tok3" and store.saved[0] == "tok3"
    # The saved token is reused.
    client.create_document("quotation", {})
    assert [c.url.path for c in calls[4:]] == ["/v1/quotations"]


def test_live_client_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(400, json={"status": False, "message": "contactName is required"})

    client = fa.FlowAccountClient("https://x/v1", "a", "b", "flowaccount-api", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(fa.FlowAccountError, match="contactName is required"):
        client.create_document("receipt", {})

    bad = fa.FlowAccountClient("https://x/v1", "a", "b", "s", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "invalid_client"}))))
    with pytest.raises(fa.FlowAccountError, match="invalid_client"):
        bad.create_document("receipt", {})


def test_live_client_network_error():
    def offline(request):
        raise httpx.ConnectError("no route")

    client = fa.FlowAccountClient("https://x/v1", "a", "b", "s", http=httpx.Client(transport=httpx.MockTransport(offline)))
    with pytest.raises(fa.FlowAccountError, match="ติดต่อ FlowAccount ไม่ได้ \\(ConnectError"):
        client.create_document("quotation", {})


def test_cancel_stops_a_draft_from_being_issued(db, owner):
    tuya = get_tuya_client()
    prepare_input = {"doc_type": "quotation", "customer": CUSTOMER, "items": ITEMS, "vat": False, "vat_inclusive": False, "credit_days": 0, "remarks": None}
    fake = FakeClaude(
        [
            message([tool_use("t1", "prepare_document", prepare_input)], "tool_use"),
            message([text("ยืนยันออกเอกสารไหมคะ TK")], "end_turn"),
            # The user tapped Cancel.
            message([tool_use("t2", "cancel_document", {"draft_id": 1})], "tool_use"),
            message([text("ยกเลิกร่างแล้วค่ะ TK")], "end_turn"),
            # Later an OK arrives anyway: the cancelled draft is refused.
            message([tool_use("t3", "issue_document", {"draft_id": 1})], "tool_use"),
            message([text("ร่างนี้ยกเลิกไปแล้วค่ะ TK")], "end_turn"),
        ]
    )
    orch = make(fake)
    first = orch.handle(db, tuya, owner, InboundMessage(user_id=owner.id, channel=Channel.line, text="ใบเสนอราคา"))
    second = orch.handle(db, tuya, owner, InboundMessage(user_id=owner.id, channel=Channel.line, session_id=first.session_id, text="Cancel"))
    assert [(c.name, c.ok) for c in second.tool_calls] == [("cancel_document", True)]
    assert db.get(DocumentLog, 1).status == "cancelled"
    third = orch.handle(db, tuya, owner, InboundMessage(user_id=owner.id, channel=Channel.line, session_id=first.session_id, text="OK"))
    assert [(c.name, c.ok) for c in third.tool_calls] == [("issue_document", False)]
    assert db.get(DocumentLog, 1).status == "cancelled"


def test_issued_document_cannot_be_cancelled(db, owner):
    doc = DocumentLog(user_id=owner.id, channel="line", doc_type="quotation", status="issued", document_serial="QT-1", payload={})
    db.add(doc)
    db.commit()
    with pytest.raises(docs.DocumentError, match="ออกไปแล้ว"):
        docs.cancel(db, owner, doc.id)


def test_persona_keeps_document_replies_short():
    from app.core.prompts import SYSTEM_PROMPT

    # The owner checks details in FlowAccount; JARVIS only names the document and the customer.
    assert '"ร่าง<ประเภทเอกสาร>ของ<ชื่อลูกค้า> ยืนยันไหมคะ TK"' in SYSTEM_PROMPT
    assert '"ออก<ประเภทเอกสาร>ของ<ชื่อลูกค้า>เรียบร้อยแล้วค่ะ TK"' in SYSTEM_PROMPT
    assert "ไม่บอกเลขที่เอกสาร" in SYSTEM_PROMPT
