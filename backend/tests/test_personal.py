import base64
import io
from datetime import date

import pytest
from PIL import Image

from app.api import line as line_api
from app.db import PersonalSession
from app.personal_models import PersonalEntry
from app.services import personal
from tests.test_line import FakeLine, link, post_event, text_event  # noqa: F401  (the line fixture)
from tests.test_line import line  # noqa: F401

JPEG = base64.b64decode(base64.b64encode(b"x"))


def picture() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(out, "PNG")
    return out.getvalue()


def add(db, bank="KBANK", no="1112278905", opening="1000", default=False, nickname=""):
    return personal.save_account(db, {"bank": bank, "account_no": no, "opening": opening, "opening_date": "2026-01-01", "is_default": default, "nickname": nickname})


def slip(**kw) -> dict:
    base = {
        "is_slip": True,
        "amount": 500,
        "date": "2026-10-05",
        "time": "09:15",
        "sender_name": "นาย ก",
        "sender_bank": "ธ.ไทยพาณิชย์",
        "sender_account": "xxx-xxx555-4",
        "receiver_name": "TK",
        "receiver_bank": "กสิกรไทย",
        "receiver_account": "xxx-x-x7890-x",
        "reference": "REF001",
        "memo": None,
    }
    return base | kw


# --- Pure helpers -------------------------------------------------------------------------------------


def test_bank_code_and_parse_text():
    assert personal.bank_code("ธ.กสิกรไทย") == "KBANK"
    assert personal.bank_code("K PLUS") == "KBANK"
    assert personal.bank_code("ทหารไทยธนชาต") == "TTB"
    assert personal.bank_code("กรุงศรีอยุธยา") == "BAY"
    assert personal.bank_code("พร้อมเพย์") is None
    assert personal.parse_text("ค่าข้าว 120 กสิกร") == (12000, "KBANK", "ค่าข้าว")
    assert personal.parse_text("ค่าเช่า 5,000.50 บาท scb") == (500050, "SCB", "ค่าเช่า")
    assert personal.parse_text("สวัสดีค่ะ") == (None, None, "สวัสดีค่ะ")


def test_number_fits_masked_slips():
    assert personal.number_fits("1112278905", "xxx-x-x7890-x") is True  # KBank prints digits 6-9
    assert personal.number_fits("1234567890", "xxx-x-x7890-x") is False
    assert personal.number_fits("1112278905", "xxx-x-x5555-x") is False
    assert personal.number_fits("1234567890", "123-4-56789-0") is True  # full, positional
    assert personal.number_fits("1234567890", "123-4-56788-0") is False
    assert personal.number_fits("7890", "xxx-x-x7890-x") is True  # only the last 4 saved
    assert personal.number_fits("1234567890", "") is True  # nothing printed: don't rule out


def test_balance_counts_from_the_opening_date():
    with PersonalSession() as db:
        a = add(db)
        b = add(db, bank="SCB", no="5554")
        personal.save_entry(db, {"kind": "income", "account_id": a.id, "amount": "250.50", "date": "2026-02-01"})
        personal.save_entry(db, {"kind": "expense", "account_id": a.id, "amount": "50", "date": "2026-02-02"})
        personal.save_entry(db, {"kind": "expense", "account_id": a.id, "amount": "999", "date": "2025-12-31"})  # before opening
        personal.save_entry(db, {"kind": "transfer", "account_id": a.id, "to_account_id": b.id, "amount": "100", "date": "2026-02-03"})
        assert personal.balance(db, a) == 100000 + 25050 - 5000 - 10000
        assert personal.balance(db, b) == 100000 + 10000
        s = personal.summary(db, "2026-02")
        assert (s["month_in"], s["month_out"], s["total"]) == (250.5, 50, 2200.5)


# --- Slips --------------------------------------------------------------------------------------------


def test_income_slip_is_recorded_once():
    with PersonalSession() as db:
        add(db)
        reply = personal.record_slip(db, "G1", "income", slip(), JPEG)
        assert reply == "บันทึกรายรับ 500.00 บาท เข้า กสิกรไทย (…8905) แล้วค่ะ TK\nคงเหลือ 1,500.00 บาท"
        e = db.query(PersonalEntry).one()
        assert (e.kind, e.counterparty, e.entry_time, e.ref_no) == ("income", "นาย ก", "09:15", "REF001")
        assert (personal.slip_dir() / e.slip_file).read_bytes() == JPEG
        assert "บันทึกไปแล้ว" in personal.record_slip(db, "G1", "income", slip(), JPEG)
        assert db.query(PersonalEntry).count() == 1


def test_slip_in_the_wrong_group_is_not_recorded():
    with PersonalSession() as db:
        add(db)
        # Money that left the owner's KBANK account, sent to the income group.
        s = slip(sender_bank="กสิกรไทย", sender_account="xxx-x-x7890-x", receiver_bank="SCB", receiver_account="xxx-xxx111-1")
        assert "ส่งผิดกลุ่ม" in personal.record_slip(db, "G1", "income", s, JPEG)
        assert db.query(PersonalEntry).count() == 0


def test_slip_between_own_accounts_is_a_transfer():
    with PersonalSession() as db:
        a = add(db)
        b = add(db, bank="SCB", no="1115554")
        s = slip(sender_bank="กสิกรไทย", sender_account="xxx-x-x7890-x", receiver_bank="ไทยพาณิชย์", receiver_account="xxx-xx5554-x")
        reply = personal.record_slip(db, "G1", "expense", s, JPEG)
        assert reply.startswith("บันทึกโอนระหว่างบัญชี 500.00 บาท จาก กสิกรไทย (…8905) ไป ไทยพาณิชย์ (…5554)")
        e = db.query(PersonalEntry).one()
        assert (e.kind, e.account_id, e.to_account_id) == ("transfer", a.id, b.id)


def test_a_stranger_at_the_same_bank_is_not_a_transfer():
    with PersonalSession() as db:
        add(db, bank="SCB", no="1115554")
        add(db)
        # Sender is someone at SCB with no digits shown: it must not be taken for the owner's SCB account.
        s = slip(sender_account=None)
        assert personal.record_slip(db, "G1", "income", s, JPEG).startswith("บันทึกรายรับ")
        assert db.query(PersonalEntry).one().kind == "income"


def test_unclear_slip_asks_which_account():
    with PersonalSession() as db:
        add(db, no="1112278901", nickname="ใช้จ่าย")
        b = add(db, no="2222278902", nickname="เก็บ")
        reply = personal.record_slip(db, "G1", "income", slip(), JPEG)
        assert "1) ใช้จ่าย (…8901)" in reply and "2) เก็บ (…8902)" in reply
        assert db.query(PersonalEntry).count() == 0
        assert personal.handle_text(db, "G1", "income", "2").startswith("บันทึกรายรับ 500.00 บาท เข้า เก็บ")
        assert db.query(PersonalEntry).one().account_id == b.id
        assert "รายละเอียด" in personal.handle_text(db, "G1", "income", "2")  # nothing is waiting: a bare number isn't an entry
        assert db.query(PersonalEntry).count() == 1


def test_not_a_slip():
    with PersonalSession() as db:
        add(db)
        assert "ไม่แน่ใจว่าเป็นสลิป" in personal.record_slip(db, "G1", "expense", {"is_slip": False}, JPEG)


# --- Typed lines --------------------------------------------------------------------------------------


def test_typed_entries_delete_and_balance():
    with PersonalSession() as db:
        add(db, default=True)
        add(db, bank="SCB", no="5554")
        assert personal.handle_text(db, "G2", "expense", "ค่าข้าว 120") == "บันทึกรายจ่าย 120.00 บาท จาก กสิกรไทย (…8905) แล้วค่ะ TK\nคงเหลือ 880.00 บาท"
        assert personal.handle_text(db, "G2", "expense", "ค่าน้ำมัน 500 scb").startswith("บันทึกรายจ่าย 500.00 บาท จาก ไทยพาณิชย์ (…5554)")
        e = db.query(PersonalEntry).order_by(PersonalEntry.id).first()
        assert (e.note, e.source, e.origin, e.entry_date) == ("ค่าข้าว", "text", "expense", personal.today())
        assert personal.handle_text(db, "G2", "expense", "ลบล่าสุด").startswith("ลบรายการล่าสุด 500.00 บาท")
        assert personal.handle_text(db, "G2", "income", "ลบล่าสุด") == "ยังไม่มีรายการจากกลุ่มนี้ให้ลบค่ะ"
        assert "รวม 1,880.00 บาท" in personal.handle_text(db, "G2", "expense", "ยอด")
        assert personal.handle_text(db, "G2", "expense", "ขอบคุณนะ") is None


def test_typed_entry_without_default_asks():
    with PersonalSession() as db:
        add(db)
        add(db, bank="SCB", no="5554")
        assert "1) กสิกรไทย (…8905)" in personal.handle_text(db, "G2", "expense", "ค่าข้าว 120")
        assert personal.handle_text(db, "G2", "expense", "1").startswith("บันทึกรายจ่าย 120.00 บาท จาก กสิกรไทย")


# --- LINE groups --------------------------------------------------------------------------------------


def group_event(message: dict, user="Uowner", group="Gin", kind="message") -> dict:
    ev = text_event("")
    return ev | {"type": kind, "source": {"type": "group", "groupId": group, "userId": user}, "message": message}


@pytest.fixture
def groups(line):  # noqa: F811
    line.groups = {"Gin": "สลิปรายรับ", "Gout": "สลิปรายจ่าย", "Gfam": "ครอบครัว"}
    return line


def test_line_slip_group(client, owner_headers, groups, monkeypatch):
    link(client, owner_headers, groups)
    with PersonalSession() as db:
        add(db)
    monkeypatch.setattr(line_api, "read_slip", lambda jpeg: slip())
    groups.contents["m1"] = picture()
    post_event(client, group_event({"type": "image", "id": "m1"}))
    assert groups.sent[-1][1] == "Gin"
    assert groups.sent[-1][2][0]["text"].startswith("บันทึกรายรับ 500.00 บาท")
    post_event(client, group_event({"type": "text", "id": "t1", "text": "ค่าข้าว 120"}, group="Gout"))
    assert groups.sent[-1][2][0]["text"].startswith("บันทึกรายจ่าย 120.00 บาท")
    with PersonalSession() as db:
        assert personal.balance(db, personal.accounts(db)[0]) == 100000 + 50000 - 12000


def test_line_groups_ignore_others(client, owner_headers, groups, monkeypatch):
    link(client, owner_headers, groups)
    with PersonalSession() as db:
        add(db, default=True)
    count = len(groups.sent)
    post_event(client, group_event({"type": "text", "id": "t1", "text": "ค่าข้าว 120"}, user="Ufriend"))  # not linked
    post_event(client, group_event({"type": "text", "id": "t2", "text": "ค่าข้าว 120"}, group="Gfam"))  # not a slip group
    post_event(client, group_event({"type": "text", "id": "t3", "text": "กินข้าวยัง"}))  # ordinary chat
    assert len(groups.sent) == count
    with PersonalSession() as db:
        assert db.query(PersonalEntry).count() == 0


def test_line_group_join_explains(client, groups):
    post_event(client, group_event({}, group="Gout", kind="join"))
    assert "บันทึกรายจ่าย" in groups.sent[-1][2][0]["text"]
    post_event(client, group_event({}, group="Gfam", kind="join"))
    assert "เท่านั้น" in groups.sent[-1][2][0]["text"]


# --- API ----------------------------------------------------------------------------------------------


def test_api(client, owner_headers):
    h = owner_headers
    r = client.post("/personal/accounts", headers=h, json={"bank": "KBANK", "nickname": "หลัก", "account_no": "123-4-56789-0", "opening": 1000, "opening_date": "2026-10-01", "is_default": True})
    assert r.status_code == 201, r.text
    acc = r.json()
    assert (acc["account_no"], acc["label"], acc["balance"]) == ("1234567890", "หลัก (…7890)", 1000)
    assert client.post("/personal/accounts", headers=h, json={"bank": "XX", "opening_date": "2026-10-01"}).status_code == 400
    r = client.post("/personal/entries", headers=h, json={"kind": "expense", "date": "2026-10-03", "amount": 120, "account_id": acc["id"], "note": "ข้าว"})
    assert r.status_code == 201, r.text
    entry = r.json()
    r = client.put(f"/personal/entries/{entry['id']}", headers=h, json={"kind": "expense", "date": "2026-10-03", "amount": 150, "account_id": acc["id"]})
    assert r.json()["amount"] == 150
    rows = client.get("/personal/entries", headers=h, params={"kind": "expense", "month": "2026-10"}).json()
    assert [e["amount"] for e in rows] == [150]
    assert client.get("/personal/entries", headers=h, params={"kind": "income", "month": "2026-10"}).json() == []
    s = client.get("/personal/summary", headers=h, params={"month": "2026-10"}).json()
    assert (s["total"], s["month_out"]) == (850, 150)
    assert client.get(f"/personal/entries/{entry['id']}/slip", headers=h).status_code == 404
    assert client.delete(f"/personal/accounts/{acc['id']}", headers=h).status_code == 400  # has entries
    assert client.delete(f"/personal/entries/{entry['id']}", headers=h).status_code == 204
    assert client.delete(f"/personal/accounts/{acc['id']}", headers=h).status_code == 204
    assert any(b["code"] == "SCB" for b in client.get("/personal/banks", headers=h).json())


def test_slip_picture_endpoint(client, owner_headers):
    with PersonalSession() as db:
        add(db)
        personal.record_slip(db, "G1", "income", slip(), JPEG)
        entry = db.query(PersonalEntry).one()
        entry_id, path = entry.id, personal.slip_dir() / entry.slip_file
    r = client.get(f"/personal/entries/{entry_id}/slip", headers=owner_headers)
    assert r.status_code == 200 and r.content == JPEG
    assert client.delete(f"/personal/entries/{entry_id}", headers=owner_headers).status_code == 204
    assert not path.exists()


def test_api_is_admin_only(client, owner_headers):
    client.post("/users", headers=owner_headers, json={"username": "kid", "password": "password123"})
    token = client.post("/auth/login", json={"username": "kid", "password": "password123"}).json().get("access_token")
    assert token
    assert client.get("/personal/accounts", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get("/personal/accounts").status_code == 401


def test_month_range():
    assert personal.month_range("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))
    with pytest.raises(personal.PersonalError):
        personal.month_range("2026-13")
