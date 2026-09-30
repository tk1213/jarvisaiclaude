import base64
import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from app.api import line as line_api
from app.config import get_settings
from app.core import orchestrator as orch_module
from app.db import SessionLocal
from app.integrations import line as line_int
from app.models import ChatMessage, Device
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
