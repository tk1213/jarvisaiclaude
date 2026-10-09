"""The dashboard chat is one conversation across all the owner's screens."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.api import core as core_api
from app.core import orchestrator as orch_module
from app.db import SessionLocal
from app.models import ChatMessage
from tests.test_orchestrator import FakeClaude, make, message, text, tool_use


def _token(headers):
    return headers["Authorization"].split()[1]


def say(client, headers, words, client_id="tab-a", channel="dashboard"):
    r = client.post("/core/chat", json={"text": words, "client_id": client_id, "channel": channel}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_screens_share_one_conversation_and_reload_it(client, owner_headers, monkeypatch):
    core_api._reset_at.clear()
    fake = FakeClaude(
        [
            message([tool_use("t1", "list_scenes", {})], "tool_use"),
            message([text("ไม่มี scene ค่ะ TK")], "end_turn"),
            message([text("สวัสดีค่ะ TK")], "end_turn"),
        ]
    )
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    assert client.get("/core/chat/current", headers=owner_headers).json() == {"session_id": None, "messages": []}

    first = say(client, owner_headers, "มี scene อะไรบ้าง", client_id="tab-a")
    second = say(client, owner_headers, "สวัสดี", client_id="tab-b", channel="voice")  # another screen, no session id
    assert first["session_id"] == second["session_id"]
    assert len(fake.requests[2]["messages"]) == 5  # the second screen's turn sees the first screen's

    current = client.get("/core/chat/current", headers=owner_headers).json()
    assert current["session_id"] == first["session_id"]
    assert current["messages"] == [
        {"role": "user", "text": "มี scene อะไรบ้าง", "tool_calls": [], "pictures": 0},
        {"role": "jarvis", "text": "ไม่มี scene ค่ะ TK", "tool_calls": [{"name": "list_scenes", "input": {}, "ok": True}], "pictures": 0},
        {"role": "user", "text": "สวัสดี", "tool_calls": [], "pictures": 0},
        {"role": "jarvis", "text": "สวัสดีค่ะ TK", "tool_calls": [], "pictures": 0},
    ]


def test_reset_and_quiet_start_over(client, owner_headers, monkeypatch):
    core_api._reset_at.clear()
    fake = FakeClaude([message([text(f"ตอบ {i}")], "end_turn") for i in range(3)])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    first = say(client, owner_headers, "หนึ่ง")

    assert client.post("/core/chat/reset", json={"client_id": "tab-a"}, headers=owner_headers).status_code == 204
    assert client.get("/core/chat/current", headers=owner_headers).json()["messages"] == []
    second = say(client, owner_headers, "สอง")
    assert second["session_id"] != first["session_id"]
    assert len(fake.requests[1]["messages"]) == 1  # nothing from before the reset

    with SessionLocal() as db:  # 31 minutes of quiet
        db.execute(update(ChatMessage).values(created_at=datetime.now(timezone.utc) - timedelta(minutes=31)))
        db.commit()
    assert client.get("/core/chat/current", headers=owner_headers).json()["session_id"] is None
    assert say(client, owner_headers, "สาม")["session_id"] not in (first["session_id"], second["session_id"])


def test_turns_and_resets_reach_only_this_users_screens(client, owner_headers, monkeypatch):
    core_api._reset_at.clear()
    fake = FakeClaude([message([text("สวัสดีค่ะ TK")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    client.post("/users", headers=owner_headers, json={"username": "kid", "password": "password123"})
    kid = client.post("/auth/login", json={"username": "kid", "password": "password123"}).json()["access_token"]
    client.post("/devices/sync", headers=owner_headers)

    with client.websocket_connect(f"/ws/devices?token={_token(owner_headers)}") as mine, client.websocket_connect(f"/ws/devices?token={kid}") as theirs:
        reply = say(client, owner_headers, "สวัสดี", client_id="tab-a")
        event = mine.receive_json()
        assert event == {
            "type": "chat",
            "origin": "tab-a",
            "text": "สวัสดี",
            "pictures": 0,
            "session_id": reply["session_id"],
            "reply": "สวัสดีค่ะ TK",
            "tool_calls": [],
        }
        client.post("/core/chat/reset", json={"client_id": "tab-b"}, headers=owner_headers)
        assert mine.receive_json() == {"type": "chat_reset", "origin": "tab-b"}
        # The other user gets device updates but never this chat.
        client.post("/devices/1/power", json={"on": True}, headers=owner_headers)
        assert theirs.receive_json()["type"] == "device"
