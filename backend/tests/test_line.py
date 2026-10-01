import base64
import hashlib
import hmac
import json

import httpx
import pytest
from sqlalchemy import select

from app.api import line as line_api
from app.config import get_settings
from app.core import orchestrator as orch_module
from app.db import SessionLocal
from app.integrations import line as line_int
from app.models import ChatMessage, Device, User
from tests.test_orchestrator import FakeClaude, make, message, text, tool_use

SECRET = "test-channel-secret"


class FakeLine:
    """Records what JARVIS would send to LINE."""

    def __init__(self):
        self.sent: list[tuple[str, str, list[dict]]] = []
        self.loading: list[str] = []

    def send(self, reply_token, to, messages):
        self.sent.append((reply_token, to, messages))

    def show_loading(self, chat_id, seconds=20):
        self.loading.append(chat_id)


@pytest.fixture
def line(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", SECRET)
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    get_settings.cache_clear()
    fake = FakeLine()
    monkeypatch.setattr(line_api, "get_line_client", lambda: fake)
    line_api._codes.clear()
    line_api._fresh.clear()
    line_api._seen.clear()
    yield fake
    get_settings.cache_clear()


def post_event(client, event: dict, secret: str = SECRET):
    body = json.dumps({"destination": "U0", "events": [event]}).encode()
    sig = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return client.post("/line/webhook", content=body, headers={"x-line-signature": sig, "content-type": "application/json"})


_n = 0


def text_event(body: str, user: str = "Uowner") -> dict:
    global _n
    _n += 1
    return {
        "type": "message",
        "webhookEventId": f"ev{_n}",
        "replyToken": f"rt{_n}",
        "source": {"type": "user", "userId": user},
        "message": {"type": "text", "id": str(_n), "text": body},
    }


def last_text(fake: FakeLine) -> str:
    msg = fake.sent[-1][2][0]
    return msg["text"] if msg["type"] == "text" else msg["altText"]


def link(client, owner_headers, fake, line_user="Uowner"):
    code = client.post("/line/link-code", headers=owner_headers).json()["code"]
    post_event(client, text_event(code, line_user))
    return code


def test_signature_is_checked(client, line):
    assert post_event(client, text_event("hi"), secret="wrong").status_code == 401
    assert line.sent == []


def test_verify_button_gets_200(client, line):
    body = b'{"destination":"U0","events":[]}'
    sig = base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()
    assert client.post("/line/webhook", content=body, headers={"x-line-signature": sig}).status_code == 200


def test_not_configured(client, owner_headers):
    assert client.get("/line/status", headers=owner_headers).json() == {"configured": False, "linked": False}
    assert client.post("/line/link-code", headers=owner_headers).status_code == 503


def test_unknown_line_user_is_told_how_to_link(client, line, monkeypatch):
    monkeypatch.setattr(orch_module, "_orchestrator", None)  # would fail if JARVIS were asked
    post_event(client, text_event("เปิดปลั๊ก 2", "Ustranger"))
    assert "รหัส 6 หลัก" in last_text(line)
    post_event(client, text_event("123456", "Ustranger"))
    assert "ไม่ถูกต้อง" in last_text(line)


def test_link_code_links_once(client, owner_headers, line):
    code = link(client, owner_headers, line)
    assert "เชื่อม LINE กับบัญชี owner แล้ว" in last_text(line)
    assert client.get("/line/status", headers=owner_headers).json() == {"configured": True, "linked": True}
    # The code is single-use: another LINE account can't reuse it.
    post_event(client, text_event(code, "Uintruder"))
    assert "ไม่ถูกต้อง" in last_text(line)

    assert client.delete("/line/link", headers=owner_headers).status_code == 204
    assert client.get("/line/status", headers=owner_headers).json()["linked"] is False


def test_link_attempts_are_rate_limited(client, line):
    for _ in range(line_api.LINK_ATTEMPTS_PER_MINUTE):
        post_event(client, text_event("000000", "Uguess"))
    post_event(client, text_event("000000", "Uguess"))
    assert "บ่อยเกินไป" in last_text(line)


def test_linked_user_talks_to_jarvis_and_gets_a_flex_card(client, owner_headers, line, monkeypatch):
    link(client, owner_headers, line)
    client.post("/devices/sync", headers=owner_headers)
    with SessionLocal() as db:
        plug = db.scalar(select(Device).where(Device.name == "ปลั๊กกาต้มน้ำ"))
        plug_id = plug.id
    fake = FakeClaude(
        [
            message([tool_use("t1", "control_device", {"device_id": plug_id, "commands": [{"code": "switch_1", "value": True}]})], "tool_use"),
            message([text("เปิดปลั๊กกาต้มน้ำแล้วค่ะ TK")], "end_turn"),
            message([text("ไม่มีอะไรค้างค่ะ TK")], "end_turn"),
        ]
    )
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))

    post_event(client, text_event("เปิดปลั๊กกาต้มน้ำ"))
    _, to, messages = line.sent[-1]
    assert to == "Uowner" and line.loading == ["Uowner"]
    card = messages[0]
    assert card["type"] == "flex" and card["altText"] == "เปิดปลั๊กกาต้มน้ำแล้วค่ะ TK"
    rows = card["contents"]["body"]["contents"][3]["contents"]
    assert [[c["text"] for c in r["contents"]] for r in rows] == [["ปลั๊กกาต้มน้ำ", "เปิด"]]
    assert fake.requests[0]["messages"][0]["content"][0]["text"].endswith("เปิดปลั๊กกาต้มน้ำ")

    # The next message continues the same LINE conversation, answered as plain text.
    post_event(client, text_event("มีอะไรค้างไหม"))
    assert line.sent[-1][2][0] == line_int.text_message("ไม่มีอะไรค้างค่ะ TK")
    assert len(fake.requests[-1]["messages"]) == 5  # user, tool call, tool result, reply + the new question
    with SessionLocal() as db:
        rows = db.scalars(select(ChatMessage)).all()
        assert {r.channel for r in rows} == {"line"} and len({r.session_id for r in rows}) == 1


def test_ok_cancel_buttons_only_under_a_document_draft(client, owner_headers, line, monkeypatch):
    link(client, owner_headers, line)
    prepare_input = {
        "doc_type": "quotation",
        "customer": {"name": "บริษัท เอ จำกัด", "tax_id": None, "address": None, "branch": None, "email": None, "phone": None},
        "items": [{"name": "โช๊คประตู", "quantity": 2, "unit_price": 2190, "unit": "กล่อง"}],
        "vat": False,
        "vat_inclusive": False,
        "credit_days": 30,
        "remarks": None,
    }
    fake = FakeClaude(
        [
            message([text("สวัสดีค่ะ TK")], "end_turn"),
            message([tool_use("t1", "prepare_document", prepare_input)], "tool_use"),
            message([text("ยืนยันออกเอกสารไหมคะ TK")], "end_turn"),
            message([tool_use("t2", "issue_document", {"draft_id": 1})], "tool_use"),
            message([text("ออกใบเสนอราคาแล้วค่ะ TK")], "end_turn"),
        ]
    )
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))

    post_event(client, text_event("สวัสดี"))
    assert "quickReply" not in line.sent[-1][2][0]  # an ordinary answer has no buttons

    post_event(client, text_event("ทำใบเสนอราคาให้บริษัท เอ"))
    answer = line.sent[-1][2][0]
    labels = [i["action"]["label"] for i in answer["quickReply"]["items"]]
    assert labels == ["OK", "Cancel"] and [i["action"]["text"] for i in answer["quickReply"]["items"]] == ["OK", "Cancel"]

    post_event(client, text_event("OK"))
    assert line.sent[-1][2][0] == line_int.text_message("ออกใบเสนอราคาแล้วค่ะ TK")
    assert "quickReply" not in line.sent[-1][2][0]


def test_reset_starts_a_new_conversation(client, owner_headers, line, monkeypatch):
    link(client, owner_headers, line)
    fake = FakeClaude([message([text("หนึ่งค่ะ")], "end_turn"), message([text("สองค่ะ")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    post_event(client, text_event("หนึ่ง"))
    post_event(client, text_event("เริ่มใหม่"))
    assert "เริ่มบทสนทนาใหม่" in last_text(line)
    post_event(client, text_event("สอง"))
    assert len(fake.requests[-1]["messages"]) == 1


def test_redelivered_event_is_answered_once(client, owner_headers, line, monkeypatch):
    link(client, owner_headers, line)
    fake = FakeClaude([message([text("ค่ะ")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    event = text_event("สวัสดี")
    post_event(client, event)
    post_event(client, event)
    assert len(fake.requests) == 1


def test_non_text_and_group_messages(client, owner_headers, line):
    link(client, owner_headers, line)
    sticker = text_event("") | {"message": {"type": "sticker", "id": "9"}}
    post_event(client, sticker)
    assert "ข้อความตัวอักษร" in last_text(line)
    count = len(line.sent)
    post_event(client, text_event("เปิดไฟ") | {"source": {"type": "group", "groupId": "G1", "userId": "Uowner"}})
    assert len(line.sent) == count


def test_claude_errors_are_reported_in_chat(client, owner_headers, line, monkeypatch):
    import anthropic
    import httpx

    link(client, owner_headers, line)

    class Broke:
        def handle(self, *a, **k):
            req = httpx.Request("POST", "https://api.anthropic.com")
            raise anthropic.BadRequestError("credit balance is too low", response=httpx.Response(400, request=req), body=None)

    monkeypatch.setattr(orch_module, "_orchestrator", Broke())
    post_event(client, text_event("เปิดไฟ"))
    assert "Claude API error 400" in last_text(line)


def test_signature_helper():
    body = b"abc"
    sig = base64.b64encode(hmac.new(b"s", body, hashlib.sha256).digest()).decode()
    assert line_int.valid_signature("s", body, sig)
    assert not line_int.valid_signature("s", body + b"x", sig)
    assert not line_int.valid_signature("", body, sig)


def test_info_messages():
    msgs = line_int.info_messages(
        "ราคาทองวันนี้ 1 ต.ค. 2569\n- ทองแท่ง ขายออก 52,000 บาท",
        links=[{"label": "สมาคมค้าทองคำ", "url": "https://www.goldtraders.or.th"}, {"label": "bad", "url": "javascript:alert(1)"}],
        location={"title": "สยามพารากอน", "address": "ถ.พระราม 1 กรุงเทพฯ", "latitude": 13.7466, "longitude": 100.5347},
        image_url="https://example.com/gold.jpg",
    )
    assert [m["type"] for m in msgs] == ["text", "text", "image"]
    assert msgs[0]["text"].endswith("สมาคมค้าทองคำ: https://www.goldtraders.or.th") and "javascript" not in msgs[0]["text"]
    assert msgs[1]["text"] == "📍 สยามพารากอน\nถ.พระราม 1 กรุงเทพฯ\nhttps://www.google.com/maps/search/?api=1&query=13.7466%2C100.5347"
    assert msgs[2] == {"type": "image", "originalContentUrl": "https://example.com/gold.jpg", "previewImageUrl": "https://example.com/gold.jpg"}
    # Unknown coordinates: the link searches by name and address; non-https images are dropped.
    msgs = line_int.info_messages("", location={"title": "ร้านป้าแดง", "address": "สีลม", "latitude": None, "longitude": None}, image_url="http://x/y.jpg")
    assert msgs == [{"type": "text", "text": "📍 ร้านป้าแดง\nสีลม\n" + line_int.maps_link("ร้านป้าแดง สีลม")}]


def test_send_to_line_tool(client, owner_headers, line, monkeypatch):
    from app.core.tools import ToolContext, run_tool

    pushed = []

    class Pusher:
        def push(self, to, messages):
            pushed.append((to, messages))

    monkeypatch.setattr(line_int, "get_line_client", lambda: Pusher())
    args = {"text": "ข่าวเด่นวันนี้", "links": None, "location": None, "image_url": None}
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "owner"))
        out, is_error = run_tool(ToolContext(db=db, tuya=None, user=owner, channel="voice"), "send_to_line", args)
        assert is_error and "ยังไม่ได้เชื่อม LINE" in out

    link(client, owner_headers, line)
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == "owner"))
        out, is_error = run_tool(ToolContext(db=db, tuya=None, user=owner, channel="voice"), "send_to_line", args)
    assert not is_error and json.loads(out) == {"sent": ["text"]}
    assert pushed == [("Uowner", [{"type": "text", "text": "ข่าวเด่นวันนี้"}])]


def test_tool_crash_and_line_network_errors_are_contained(monkeypatch):
    from app.core import tools

    def boom(ctx, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setitem(tools._HANDLERS, "list_scenes", boom)
    out, is_error = tools.run_tool(tools.ToolContext(db=None, tuya=None, user=None), "list_scenes", {})
    assert is_error and "RuntimeError: disk full" in out

    def offline(request):
        raise httpx.ConnectError("no route")

    client = line_int.LineClient("t", http=httpx.Client(base_url=line_int.API, transport=httpx.MockTransport(offline)))
    with pytest.raises(line_int.LineError, match="ConnectError"):
        client.push("U1", [{"type": "text", "text": "x"}])


def test_unexpected_chat_error_says_what_broke(client, owner_headers, monkeypatch):
    class Broken:
        def handle(self, *a, **k):
            raise KeyError("blocks")

    monkeypatch.setattr(orch_module, "_orchestrator", Broken())
    r = client.post("/core/chat", json={"text": "hi"}, headers=owner_headers)
    assert r.status_code == 500 and r.json()["detail"] == "JARVIS error: KeyError: 'blocks'"
