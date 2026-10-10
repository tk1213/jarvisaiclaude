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


# --- "tk รับจ่าย": slips and typed lines in the one-to-one chat ------------------------------------------


def test_chat_slip_works_out_income_expense_and_transfer():
    with PersonalSession() as db:
        a = add(db)  # KBANK …8905
        b = add(db, bank="SCB", no="1115554")
        # Money into the owner's KBANK from a stranger: income.
        assert personal.record_chat_slip(db, "U1", slip(sender_account="xxx-xxx999-1"), JPEG).startswith("บันทึกรายรับ 500.00 บาท เข้า กสิกรไทย")
        # Money out of the owner's KBANK to a shop: expense.
        out = slip(reference="REF002", sender_bank="กสิกรไทย", sender_account="xxx-x-x7890-x", receiver_name="ร้านข้าว", receiver_bank="พร้อมเพย์", receiver_account=None)
        assert personal.record_chat_slip(db, "U1", out, JPEG).startswith("บันทึกรายจ่าย 500.00 บาท จาก กสิกรไทย")
        # Between the owner's own accounts: a transfer.
        move = slip(reference="REF003", sender_bank="กสิกรไทย", sender_account="xxx-x-x7890-x", receiver_bank="ไทยพาณิชย์", receiver_account="xxx-xx5554-x")
        assert personal.record_chat_slip(db, "U1", move, JPEG).startswith("บันทึกโอนระหว่างบัญชี 500.00 บาท จาก กสิกรไทย (…8905) ไป ไทยพาณิชย์ (…5554)")
        kinds = [(e.kind, e.account_id, e.to_account_id) for e in db.query(PersonalEntry).order_by(PersonalEntry.id)]
        assert kinds == [("income", a.id, None), ("expense", a.id, None), ("transfer", a.id, b.id)]


def test_chat_slip_that_cant_tell_asks_income_or_expense():
    with PersonalSession() as db:
        add(db, default=True)
        # Neither side shows a bank or number of the owner's.
        s = slip(sender_bank="พร้อมเพย์", sender_account=None, receiver_bank="พร้อมเพย์", receiver_account=None)
        reply = personal.record_chat_slip(db, "U1", s, JPEG)
        assert "เป็นรายรับหรือรายจ่ายคะ" in reply and "1) รายรับ" in reply and "2) รายจ่าย" in reply
        assert db.query(PersonalEntry).count() == 0
        assert personal.handle_chat_text(db, "U1", "2").startswith("บันทึกรายจ่าย 500.00 บาท จาก กสิกรไทย")
        e = db.query(PersonalEntry).one()
        assert (e.kind, e.source, e.ref_no) == ("expense", "slip", "REF001")


def test_chat_slip_into_a_fund_by_its_name():
    with PersonalSession() as db:
        bank = add(db)
        fund = add(db, bank="FUND_A", no="", opening="0", nickname="K-SET50")
        buy = slip(sender_bank="กสิกรไทย", sender_account="xxx-x-x7890-x", receiver_name="กองทุนเปิด K-SET50", receiver_bank="บลจ.กสิกรไทย", receiver_account=None)
        assert personal.record_chat_slip(db, "U1", buy, JPEG).startswith("บันทึกโอนระหว่างบัญชี 500.00 บาท จาก กสิกรไทย (…8905) ไป K-SET50")
        assert (personal.balance(db, bank), personal.balance(db, fund)) == (50000, 50000)


def test_chat_typed_lines():
    with PersonalSession() as db:
        a = add(db, default=True)
        b = add(db, bank="SCB", no="5554")
        fund = add(db, bank="FUND_B", no="", opening="0", nickname="K-SET50")
        assert personal.handle_chat_text(db, "U1", "จ่าย ค่าข้าว 120") == "บันทึกรายจ่าย 120.00 บาท จาก กสิกรไทย (…8905) แล้วค่ะ TK\nคงเหลือ 880.00 บาท"
        assert personal.handle_chat_text(db, "U1", "รับ ค่าจ้าง 5,000 scb").startswith("บันทึกรายรับ 5,000.00 บาท เข้า ไทยพาณิชย์ (…5554)")
        # No รับ/จ่าย: JARVIS asks which.
        assert "เป็นรายรับหรือรายจ่ายคะ" in personal.handle_chat_text(db, "U1", "ค่าน้ำ 300")
        assert personal.handle_chat_text(db, "U1", "2").startswith("บันทึกรายจ่าย 300.00 บาท จาก กสิกรไทย")
        # A transfer to a fund named by its nickname (its digits aren't the amount), and one by "กองทุน B".
        assert personal.handle_chat_text(db, "U1", "โอน 1000 กสิกร ไป K-SET50").startswith("บันทึกโอนระหว่างบัญชี 1,000.00 บาท จาก กสิกรไทย (…8905) ไป K-SET50")
        assert personal.handle_chat_text(db, "U1", "โอน 200 scb ไปกองทุน B").startswith("บันทึกโอนระหว่างบัญชี 200.00 บาท จาก ไทยพาณิชย์ (…5554) ไป K-SET50")
        assert personal.handle_chat_text(db, "U1", "โอน 200") == personal.TRANSFER_HELP
        assert personal.balance(db, fund) == 120000
        assert personal.balance(db, a) == 100000 - 12000 - 30000 - 100000
        assert personal.balance(db, b) == 100000 + 500000 - 20000
        assert personal.handle_chat_text(db, "U1", "ลบล่าสุด").startswith("ลบรายการล่าสุด 200.00 บาท")
        assert personal.handle_chat_text(db, "U1", "สวัสดี") is None
        assert "รายละเอียด" in personal.handle_chat_text(db, "U1", "จ่าย")


def test_split_kind():
    assert personal.split_kind("Kbank จ่าย 20 บาท") == ("expense", "Kbank 20 บาท")
    assert personal.split_kind("ค่าข้าว จ่าย 120") == ("expense", "ค่าข้าว 120")
    assert personal.split_kind("กสิกร รับ ค่าจ้าง 5000") == ("income", "กสิกร ค่าจ้าง 5000")
    assert personal.split_kind("รับค่าจ้าง 5000") == ("income", "ค่าจ้าง 5000")
    assert personal.split_kind("รายจ่ายค่าไฟ 800") == ("expense", "ค่าไฟ 800")
    assert personal.split_kind("จ่าย120 ค่าข้าว") == ("expense", "120 ค่าข้าว")
    assert personal.split_kind("Kbank โอน 5000 ไป K-SET50") == ("transfer", "Kbank 5000 ไป K-SET50")
    assert personal.split_kind("ค่าเครื่องรับสัญญาณ 500") == (None, "ค่าเครื่องรับสัญญาณ 500")
    assert personal.split_kind("รับ 100 จ่าย 50") == (None, "รับ 100 จ่าย 50")
    assert personal.split_kind("ค่าข้าว 120") == (None, "ค่าข้าว 120")


def test_kind_word_anywhere_in_the_line():
    with PersonalSession() as db:
        add(db, bank="KBANK", no="5531", nickname="TK Kbank")
        add(db, bank="BAY", no="6165", default=True)
        fund = add(db, bank="FUND_A", no="", opening="0", nickname="K-SET50")
        assert personal.handle_chat_text(db, "G", "Kbank จ่าย 20 บาท") == "บันทึกรายจ่าย 20.00 บาท จาก TK Kbank (…5531) แล้วค่ะ TK\nคงเหลือ 980.00 บาท"
        assert personal.handle_chat_text(db, "G", "ค่าข้าว จ่าย 120").startswith("บันทึกรายจ่าย 120.00 บาท จาก กรุงศรี (…6165)")
        assert db.query(PersonalEntry).order_by(PersonalEntry.id.desc()).first().note == "ค่าข้าว"
        assert personal.handle_chat_text(db, "G", "รับค่าจ้าง 5000").startswith("บันทึกรายรับ 5,000.00 บาท เข้า กรุงศรี")
        assert personal.handle_chat_text(db, "G", "Kbank โอน 300 ไป K-SET50").startswith("บันทึกโอนระหว่างบัญชี 300.00 บาท จาก TK Kbank")
        assert personal.balance(db, fund) == 30000
        assert "เป็นรายรับหรือรายจ่ายคะ" in personal.handle_chat_text(db, "G", "ค่าเครื่องรับสัญญาณ 500")


def test_balance_of_one_bank_or_fund():
    with PersonalSession() as db:
        add(db, bank="BAY", no="6165", nickname="TK กรุงศรี")
        add(db, bank="KBANK", no="5531", opening="2000")
        add(db, bank="FUND_A", no="", opening="300", nickname="K-SET50")
        for ask in ("ยอด กรุงศรี เหลือเท่าไร", "ยอดกรุงศรีเหลือเท่าไหร่", "ยอดคงเหลือ TK กรุงศรี"):
            assert personal.handle_chat_text(db, "G", ask) == "ยอด TK กรุงศรี (…6165) คงเหลือ 1,000.00 บาทค่ะ TK", ask
        assert personal.handle_chat_text(db, "G", "ยอด K-SET50") == "ยอด K-SET50 คงเหลือ 300.00 บาทค่ะ TK"
        assert personal.handle_chat_text(db, "G", "ยอดเหลือ กองทุน A") == "ยอด K-SET50 คงเหลือ 300.00 บาทค่ะ TK"
        assert "รวม 3,300.00 บาท" in personal.handle_chat_text(db, "G", "ยอดเหลือเท่าไหร่")
        assert "รวม 3,300.00 บาท" in personal.handle_text(db, "G", "expense", "ยอด")
        assert personal.handle_text(db, "G", "expense", "ยอด kbank") == "ยอด กสิกรไทย (…5531) คงเหลือ 2,000.00 บาทค่ะ TK"
        assert personal.handle_chat_text(db, "G", "มีอะไรเหลือไหม") is None  # chat, not a question about money
        # An entry that happens to say ยอด is still an entry.
        assert personal.handle_chat_text(db, "G", "จ่าย ยอดค้าง 50 kbank").startswith("บันทึกรายจ่าย 50.00 บาท")


def test_transfers_count_per_account_but_not_in_month_totals():
    with PersonalSession() as db:
        a = add(db)
        b = add(db, bank="SCB", no="5554")
        personal.save_entry(db, {"kind": "expense", "account_id": a.id, "amount": "50", "date": "2026-02-02"})
        personal.save_entry(db, {"kind": "transfer", "account_id": a.id, "to_account_id": b.id, "amount": "100", "date": "2026-02-03"})
        s = personal.summary(db, "2026-02")
        assert (s["month_in"], s["month_out"]) == (0, 50)
        by_id = {x["id"]: x for x in s["accounts"]}
        assert (by_id[a.id]["month_in"], by_id[a.id]["month_out"]) == (0, 150)
        assert (by_id[b.id]["month_in"], by_id[b.id]["month_out"]) == (100, 0)
        # Filtered by account, a transfer shows as money in on its destination and money out of its source.
        assert [e.kind for e in personal.list_entries(db, "income", "2026-02", b.id)] == ["transfer"]
        assert personal.list_entries(db, "income", "2026-02", a.id) == []
        assert [e.kind for e in personal.list_entries(db, "expense", "2026-02", a.id)] == ["transfer", "expense"]
        assert personal.list_entries(db, "expense", "2026-02", b.id) == []


# --- LINE group "tk รับจ่าย" -----------------------------------------------------------------------------


def test_rabjai_group(client, owner_headers, groups, monkeypatch):
    groups.groups["Grj"] = "tk รับจ่าย"
    link(client, owner_headers, groups)
    with PersonalSession() as db:
        add(db, default=True)
    post_event(client, group_event({}, group="Grj", kind="join"))
    assert "รับ ค่าจ้าง 5000" in groups.sent[-1][2][0]["text"]
    post_event(client, group_event({"type": "text", "id": "t1", "text": "จ่าย ค่าข้าว 120"}, group="Grj"))
    assert groups.sent[-1][1] == "Grj"
    assert groups.sent[-1][2][0]["text"].startswith("บันทึกรายจ่าย 120.00 บาท")
    # A slip works out income by itself.
    monkeypatch.setattr(line_api, "read_slip", lambda jpeg: slip())
    groups.contents["m1"] = picture()
    post_event(client, group_event({"type": "image", "id": "m1"}, group="Grj"))
    assert groups.sent[-1][2][0]["text"].startswith("บันทึกรายรับ 500.00 บาท")
    # No รับ/จ่าย: JARVIS asks, and the answer records it.
    post_event(client, group_event({"type": "text", "id": "t2", "text": "ค่าน้ำ 300"}, group="Grj"))
    assert "เป็นรายรับหรือรายจ่ายคะ" in groups.sent[-1][2][0]["text"]
    post_event(client, group_event({"type": "text", "id": "t3", "text": "2"}, group="Grj"))
    assert groups.sent[-1][2][0]["text"].startswith("บันทึกรายจ่าย 300.00 บาท")
    with PersonalSession() as db:
        assert personal.balance(db, personal.accounts(db)[0]) == 100000 - 12000 + 50000 - 30000
    # Ordinary chat and other members stay unanswered.
    count = len(groups.sent)
    post_event(client, group_event({"type": "text", "id": "t4", "text": "กินข้าวยัง"}, group="Grj"))
    post_event(client, group_event({"type": "text", "id": "t5", "text": "จ่าย 5"}, group="Grj", user="Ufriend"))
    assert len(groups.sent) == count


def test_group_kind():
    assert line_api.group_kind("tk รับจ่าย") == "both"
    assert line_api.group_kind("สลิปรายรับ") == "income"
    assert line_api.group_kind("สลิปรายจ่าย") == "expense"
    assert line_api.group_kind("ครอบครัว") is None


def test_banks_include_funds(client, owner_headers):
    banks = {b["code"]: b["name"] for b in client.get("/personal/banks", headers=owner_headers).json()}
    assert [banks[f"FUND_{x}"] for x in "ABCDEF"] == ["กองทุน A", "กองทุน B", "กองทุน C", "กองทุน D", "กองทุน E", "กองทุน F"]
