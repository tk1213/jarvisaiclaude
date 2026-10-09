import copy
import json

import pytest
from anthropic.types.beta import BetaMessage

from app.core import orchestrator as orch_module
from app.core.orchestrator import Orchestrator
from app.core.prompts import SYSTEM_PROMPT
from app.core.tools import TOOLS
from app.db import SessionLocal
from app.integrations.tuya import get_tuya_client
from app.models import ChatMessage, User
from app.services.devices import sync_devices


def message(content: list[dict], stop_reason: str) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


def tool_use(id_: str, name: str, input_: dict) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


class FakeClaude:
    """Returns scripted responses and records every request it receives."""

    def __init__(self, responses: list[BetaMessage]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


@pytest.fixture
def home():
    db = SessionLocal()
    user = User(username="owner", password_hash="x", can_control_devices=True)
    db.add(user)
    db.commit()
    tuya = get_tuya_client()
    devices = {d.name: d for d in sync_devices(db, tuya)}
    yield db, tuya, user, devices
    db.close()


def make(fake) -> Orchestrator:
    return Orchestrator(fake, model="claude-opus-5-5", effort="low", max_tool_rounds=4, timezone="Asia/Bangkok")


def ask(orch, db, tuya, user, text_, session_id=None):
    from app.core.messages import Channel, InboundMessage

    msg = InboundMessage(user_id=user.id, channel=Channel.dashboard, session_id=session_id, text=text_)
    return orch.handle(db, tuya, user, msg)


def test_requests_cache_the_repeated_prefix(home):
    db, tuya, user, _ = home
    fake = FakeClaude([message([text("สวัสดีค่ะ TK")], "end_turn")])
    ask(make(fake), db, tuya, user, "สวัสดี")
    assert fake.requests[0]["cache_control"] == {"type": "ephemeral"}


def test_turns_on_device_via_tools(home):
    db, tuya, user, devices = home
    light = devices["ไฟห้องนั่งเล่น"]
    fake = FakeClaude(
        [
            message([tool_use("t1", "get_devices", {"room": "นั่งเล่น"})], "tool_use"),
            message(
                [tool_use("t2", "control_device", {"device_id": light.id, "commands": [{"code": "switch_led", "value": True}]})],
                "tool_use",
            ),
            message([text("เปิดไฟห้องนั่งเล่นให้แล้วครับ")], "end_turn"),
        ]
    )
    reply = ask(make(fake), db, tuya, user, "เปิดไฟห้องนั่งเล่นหน่อย")

    assert reply.text == "เปิดไฟห้องนั่งเล่นให้แล้วครับ"
    assert [c.name for c in reply.tool_calls] == ["get_devices", "control_device"]
    assert all(c.ok for c in reply.tool_calls)
    assert tuya.get_device_status("mock-light-living")[0] == {"code": "switch_led", "value": True}

    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["system"] == SYSTEM_PROMPT and req["tools"] == TOOLS
    assert req["output_config"] == {"effort": "low"}
    assert req["thinking"]["type"] == "adaptive"
    assert "เปิดไฟห้องนั่งเล่นหน่อย" in req["messages"][0]["content"][0]["text"]

    # Tool results come back as one user message after the assistant turn.
    second = fake.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    result = second[2]["content"][0]
    assert result["tool_use_id"] == "t1" and not result["is_error"]
    assert "ไฟห้องนั่งเล่น" in result["content"]


def test_history_is_replayed_append_only(home):
    db, tuya, user, _ = home
    fake = FakeClaude(
        [
            message([{"type": "thinking", "thinking": "", "signature": "sig1"}, text("สวัสดีครับ")], "end_turn"),
            message([text("ยินดีครับ")], "end_turn"),
        ]
    )
    orch = make(fake)
    first = ask(orch, db, tuya, user, "สวัสดี")
    ask(orch, db, tuya, user, "ขอบคุณ", session_id=first.session_id)

    turn1, turn2 = fake.requests[0]["messages"], fake.requests[1]["messages"]
    # The second request starts with exactly what the first request sent plus the reply, byte for byte.
    assert turn2[: len(turn1)] == turn1
    assert turn2[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig1"}
    assert [m["role"] for m in turn2] == ["user", "assistant", "user"]
    assert db.query(ChatMessage).filter_by(session_id=first.session_id).count() == 4


def test_sessions_are_separate(home):
    db, tuya, user, _ = home
    fake = FakeClaude([message([text("a")], "end_turn"), message([text("b")], "end_turn")])
    orch = make(fake)
    ask(orch, db, tuya, user, "one")
    ask(orch, db, tuya, user, "two")
    assert len(fake.requests[1]["messages"]) == 1


def test_tool_errors_are_reported_to_claude(home):
    db, tuya, user, _ = home
    fake = FakeClaude(
        [
            message([tool_use("t1", "control_device", {"device_id": 999, "commands": [{"code": "x", "value": 1}]})], "tool_use"),
            message([text("ไม่พบอุปกรณ์ครับ")], "end_turn"),
        ]
    )
    reply = ask(make(fake), db, tuya, user, "เปิดอะไรสักอย่าง")
    result = fake.requests[1]["messages"][2]["content"][0]
    assert result["is_error"] is True and "999" in result["content"]
    assert reply.tool_calls[0].ok is False


def test_user_without_permission_cannot_control(home):
    db, tuya, user, devices = home
    user.can_control_devices = False
    db.commit()
    plug = devices["ปลั๊กกาต้มน้ำ"]
    fake = FakeClaude(
        [
            message([tool_use("t1", "control_device", {"device_id": plug.id, "commands": [{"code": "switch_1", "value": True}]})], "tool_use"),
            message([text("ไม่มีสิทธิ์ครับ")], "end_turn"),
        ]
    )
    ask(make(fake), db, tuya, user, "เปิดปลั๊ก")
    assert fake.requests[1]["messages"][2]["content"][0]["is_error"] is True
    assert tuya.get_device_status("mock-plug-kitchen")[0]["value"] is False


def test_refusal_is_not_persisted(home):
    db, tuya, user, _ = home
    fake = FakeClaude([message([], "refusal")])
    reply = ask(make(fake), db, tuya, user, "...")
    assert "ขออภัย" in reply.text
    assert db.query(ChatMessage).count() == 0


def test_runaway_tool_loop_stops_without_persisting(home):
    db, tuya, user, _ = home
    fake = FakeClaude([message([tool_use(f"t{i}", "list_scenes", {})], "tool_use") for i in range(4)])
    reply = ask(make(fake), db, tuya, user, "วนไปเรื่อยๆ")
    assert len(fake.requests) == 4
    assert db.query(ChatMessage).count() == 0  # a dangling tool_use would break the next turn
    assert reply.text


def test_chat_endpoint(client, owner_headers, monkeypatch):
    fake = FakeClaude([message([text("สวัสดีครับ")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    r = client.post("/core/chat", json={"text": "สวัสดี"}, headers=owner_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "สวัสดีค่ะ"  # the female voice never says ครับ
    assert body["session_id"] and body["tool_calls"] == []


def test_voice_channel_asks_for_a_speakable_reply(client, owner_headers, monkeypatch):
    from app.core.prompts import VOICE_HINT

    fake = FakeClaude([message([text("a")], "end_turn"), message([text("b")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    client.post("/core/chat", json={"text": "เปิดแอร์", "channel": "voice"}, headers=owner_headers)
    client.post("/core/chat", json={"text": "เปิดแอร์"}, headers=owner_headers)
    spoken, typed = (r["messages"][-1]["content"][0]["text"] for r in fake.requests)
    assert VOICE_HINT in spoken and VOICE_HINT not in typed
    assert fake.requests[0]["system"] == fake.requests[1]["system"]  # prefix stays stable
    assert client.post("/core/chat", json={"text": "x", "channel": "line"}, headers=owner_headers).status_code == 422


def test_chat_endpoint_without_key(client, owner_headers, monkeypatch):
    monkeypatch.setattr(orch_module, "_orchestrator", None)
    r = client.post("/core/chat", json={"text": "สวัสดี"}, headers=owner_headers)
    assert r.status_code == 503


def test_get_devices_reports_live_state(home):
    """The table can be stale (no Pulsar running); get_devices must not trust it."""
    from app.core.tools import ToolContext, run_tool

    db, tuya, user, devices = home
    tuya.send_commands("mock-plug-kitchen", [{"code": "switch_1", "value": True}])  # changed outside JARVIS
    content, is_error = run_tool(ToolContext(db, tuya, user), "get_devices", {"room": None})
    assert not is_error
    plug = next(d for d in json.loads(content) if d["name"] == "ปลั๊กกาต้มน้ำ")
    assert plug["status"]["switch_1"] is True


def test_get_devices_trusts_table_while_pulsar_is_live(home, monkeypatch):
    from app.core.tools import ToolContext, run_tool
    from app.integrations.tuya import pulsar

    db, tuya, user, devices = home
    monkeypatch.setattr(pulsar, "_connected", True)
    calls = []
    monkeypatch.setattr(tuya, "list_devices", lambda: calls.append(1) or [])
    content, is_error = run_tool(ToolContext(db, tuya, user), "get_devices", {"room": None})
    assert not is_error and calls == [] and len(json.loads(content)) == len(devices)


def test_user_turn_carries_device_list(home):
    db, tuya, user, devices = home
    fake = FakeClaude([message([text("ok")], "end_turn")])
    ask(make(fake), db, tuya, user, "เปิดไฟ")
    turn = fake.requests[0]["messages"][-1]["content"][0]["text"]
    plug = devices["ปลั๊กกาต้มน้ำ"]
    assert f"device_id={plug.id} ปลั๊กกาต้มน้ำ" in turn and turn.endswith("เปิดไฟ")


def test_web_search_pause_turn_is_resumed(home):
    db, tuya, user, _ = home
    search = {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "ราคาทองวันนี้"}}
    fake = FakeClaude(
        [
            message([search], "pause_turn"),
            message([text("ทองคำแท่งขายออก "), text("41,200 บาท (สมาคมค้าทองคำ) ค่ะ")], "end_turn"),
        ]
    )
    web_search = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
    orch = Orchestrator(fake, model="claude-opus-5-5", effort="low", max_tool_rounds=4, timezone="Asia/Bangkok", web_search=web_search)
    reply = ask(orch, db, tuya, user, "ราคาทองวันนี้เท่าไหร่")
    assert reply.text == "ทองคำแท่งขายออก 41,200 บาท (สมาคมค้าทองคำ) ค่ะ"
    assert fake.requests[0]["tools"][-1] == web_search
    # The paused turn goes back unchanged, with no extra user message, so the server resumes it.
    resumed = fake.requests[1]["messages"]
    assert resumed[-1]["role"] == "assistant" and resumed[-1]["content"][0]["type"] == "server_tool_use"


def test_rejected_web_search_falls_back_to_home_tools(home):
    import anthropic
    import httpx

    db, tuya, user, _ = home

    class RejectsSearch(FakeClaude):
        def create(self, **kwargs):
            if any(t.get("name") == "web_search" for t in kwargs["tools"]):
                self.requests.append(copy.deepcopy(kwargs))
                request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
                raise anthropic.BadRequestError(
                    "tools.6.web_search_20260209: Country code TH is not supported.",
                    response=httpx.Response(400, request=request),
                    body=None,
                )
            return super().create(**kwargs)

    fake = RejectsSearch([message([text("เปิดให้แล้วค่ะ")], "end_turn")])
    orch = Orchestrator(fake, model="claude-opus-5-5", effort="low", max_tool_rounds=4, timezone="Asia/Bangkok", web_search={"type": "web_search_20260209", "name": "web_search"})
    assert ask(orch, db, tuya, user, "เปิดปลั๊ก 1").text == "เปิดให้แล้วค่ะ"
    assert fake.requests[-1]["tools"] == TOOLS


def test_strict_tools_stay_under_the_union_limit():
    """The API rejects every request when strict tools have more than 16 nullable/union parameters in total."""

    def unions(schema) -> int:
        if isinstance(schema, list):
            return sum(unions(s) for s in schema)
        if not isinstance(schema, dict):
            return 0
        own = 1 if isinstance(schema.get("type"), list) or "anyOf" in schema else 0
        return own + sum(unions(v) for v in schema.values())

    assert sum(unions(t["input_schema"]) for t in TOOLS if t.get("strict")) <= 16


def test_male_voice_asks_for_krub(home):
    from app.core.messages import Channel, InboundMessage
    from app.core.prompts import MALE_VOICE_HINT

    db, tuya, user, _ = home
    fake = FakeClaude([message([text("ได้ครับ TK")], "end_turn"), message([text("ได้ค่ะ TK")], "end_turn")])
    orch = make(fake)
    orch.handle(db, tuya, user, InboundMessage(user_id=user.id, channel=Channel.voice, text="สวัสดี", voice="male"))
    orch.handle(db, tuya, user, InboundMessage(user_id=user.id, channel=Channel.voice, text="สวัสดี"))
    turns = [r["messages"][-1]["content"][0]["text"] for r in fake.requests]
    assert MALE_VOICE_HINT in turns[0] and MALE_VOICE_HINT not in turns[1]
    assert fake.requests[0]["system"] == fake.requests[1]["system"] == SYSTEM_PROMPT


def test_switching_back_to_female_voice_asks_for_ka(home):
    from app.core.messages import Channel, InboundMessage
    from app.core.prompts import FEMALE_VOICE_HINT, MALE_VOICE_HINT

    db, tuya, user, _ = home
    fake = FakeClaude([message([text(t)], "end_turn") for t in ("ได้ครับ TK", "ได้ค่ะ TK", "ได้ค่ะ TK")])
    orch = make(fake)
    first = orch.handle(db, tuya, user, InboundMessage(user_id=user.id, channel=Channel.voice, text="a", voice="male"))
    sid = first.session_id
    orch.handle(db, tuya, user, InboundMessage(user_id=user.id, channel=Channel.voice, session_id=sid, text="b"))
    fresh = orch.handle(db, tuya, user, InboundMessage(user_id=user.id, channel=Channel.voice, text="c"))
    turns = [r["messages"][-1]["content"][0]["text"] for r in fake.requests]
    assert MALE_VOICE_HINT in turns[0] and FEMALE_VOICE_HINT in turns[1]
    assert FEMALE_VOICE_HINT not in turns[2] and fresh.text == "ได้ค่ะ TK"  # a new conversation needs no reminder


def test_match_voice():
    from app.core.prompts import match_voice

    assert match_voice("เปิดปลั๊ก 2 แล้วค่ะ TK มีอะไรอีกไหมคะ", "male") == "เปิดปลั๊ก 2 แล้วครับ TK มีอะไรอีกไหมครับ"
    assert match_voice("ได้คะแนน 9 คะ", "male") == "ได้คะแนน 9 ครับ"  # คะ inside a word stays
    assert match_voice("เปิดแล้วครับ TK", "female") == "เปิดแล้วค่ะ TK"
    assert match_voice("เปิดแล้วค่ะ TK", "female") == "เปิดแล้วค่ะ TK"
