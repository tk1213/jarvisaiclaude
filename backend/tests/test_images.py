import base64
import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.api import line as line_api
from app.core import images
from app.core import orchestrator as orch_module
from app.db import SessionLocal
from app.integrations.line import LineError
from app.models import ChatMessage
from tests.test_line import line, link, post_event, text_event  # noqa: F401  (fixture)
from tests.test_orchestrator import FakeClaude, make, message, text


def png(width=4000, height=3000) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


def size(jpeg_b64: str) -> tuple[int, int]:
    return Image.open(io.BytesIO(base64.b64decode(jpeg_b64))).size


def test_pictures_are_shrunk_to_jpeg():
    assert size(images.to_jpeg(png())) == (1024, 768)
    data_url = "data:image/png;base64," + base64.b64encode(png(300, 200)).decode()
    assert size(images.from_base64(data_url)) == (300, 200)  # small pictures keep their size
    with pytest.raises(images.ImageError):
        images.to_jpeg(b"not a picture")
    with pytest.raises(images.ImageError):
        images.from_base64("@@not base64@@")


def test_chat_sends_pictures_once_and_keeps_them_out_of_history(client, owner_headers, monkeypatch):
    fake = FakeClaude([message([text("ลูกค้าชื่อบริษัท เอ จำกัด ค่ะ TK")], "end_turn"), message([text("ค่ะ TK")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    picture = base64.b64encode(png(800, 600)).decode()
    r = client.post("/core/chat", json={"text": "ลูกค้าในรูปชื่ออะไร", "images": [picture]}, headers=owner_headers)
    assert r.status_code == 200
    content = fake.requests[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert "แนบรูป 1 รูป" in content[1]["text"]

    with SessionLocal() as db:
        stored = db.scalars(select(ChatMessage).where(ChatMessage.role == "user")).first()
        assert stored.content["blocks"][0] == orch_module.IMAGE_PLACEHOLDER

    client.post("/core/chat", json={"text": "ต่อเลย", "session_id": r.json()["session_id"]}, headers=owner_headers)
    replayed = fake.requests[1]["messages"][0]["content"]
    assert all(b["type"] != "image" for b in replayed)


def test_chat_rejects_a_bad_picture(client, owner_headers, monkeypatch):
    monkeypatch.setattr(orch_module, "_orchestrator", make(FakeClaude([])))
    r = client.post("/core/chat", json={"text": "ดูรูป", "images": [base64.b64encode(b"nope").decode()]}, headers=owner_headers)
    assert r.status_code == 400
    r = client.post("/core/chat", json={"text": "ดูรูป", "images": ["x"] * 5}, headers=owner_headers)
    assert r.status_code == 422


def image_event(message_id: str, user: str = "Uowner") -> dict:
    return text_event("", user) | {"message": {"type": "image", "id": message_id}}


@pytest.fixture
def line_pictures(line, monkeypatch):  # noqa: F811
    downloads = {"m1": png(), "m2": png(500, 500), "bad": b"nope"}

    def get_content(message_id):
        if message_id == "offline":
            raise LineError("LINE content: ConnectError")
        return downloads[message_id]

    line.get_content = get_content
    line_api._pending_images.clear()
    yield line
    line_api._pending_images.clear()


def test_line_pictures_wait_silently_for_the_next_text(client, owner_headers, line_pictures, monkeypatch):
    link(client, owner_headers, line_pictures)
    fake = FakeClaude([message([text("อ่านรูปแล้วค่ะ TK")], "end_turn"), message([text("ค่ะ TK")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    sent = len(line_pictures.sent)

    post_event(client, image_event("m1"))
    post_event(client, image_event("m2"))
    assert len(line_pictures.sent) == sent and fake.requests == []  # silent, JARVIS not asked yet

    post_event(client, text_event("ทำใบเสนอราคาชุด A ให้ลูกค้าในรูป"))
    content = fake.requests[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    assert size(content[0]["source"]["data"]) == (1024, 768)

    post_event(client, text_event("ต่อ"))  # used once only
    assert all(b["type"] != "image" for b in fake.requests[1]["messages"][-1]["content"])


def test_line_pictures_expire(client, owner_headers, line_pictures, monkeypatch):
    link(client, owner_headers, line_pictures)
    fake = FakeClaude([message([text("ค่ะ TK")], "end_turn")])
    monkeypatch.setattr(orch_module, "_orchestrator", make(fake))
    post_event(client, image_event("m1"))
    jpeg, at = line_api._pending_images["Uowner"][0]
    line_api._pending_images["Uowner"] = [(jpeg, at - line_api.PENDING_IMAGE_SECONDS - 1)]
    post_event(client, text_event("ดูรูป"))
    assert [b["type"] for b in fake.requests[0]["messages"][0]["content"]] == ["text"]


def test_line_picture_problems_are_reported(client, owner_headers, line_pictures):
    post_event(client, image_event("m1", "Ustranger"))
    assert "รหัส 6 หลัก" in line_pictures.sent[-1][2][0]["text"]
    assert "Ustranger" not in line_api._pending_images

    link(client, owner_headers, line_pictures)
    post_event(client, image_event("bad"))
    assert "เปิดรูปนี้ไม่ได้" in line_pictures.sent[-1][2][0]["text"]
    post_event(client, image_event("offline"))
    assert "โหลดรูปจาก LINE ไม่ได้" in line_pictures.sent[-1][2][0]["text"]
    for _ in range(5):
        post_event(client, image_event("m2"))
    assert "ครั้งละ 4 รูป" in line_pictures.sent[-1][2][0]["text"]
    assert len(line_api._pending_images["Uowner"]) == 4


def test_line_client_downloads_from_the_data_host():
    import httpx

    from app.integrations.line import LineClient

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=b"jpeg") if "ok" in request.url.path else httpx.Response(404, text="gone")

    http = httpx.Client(base_url="https://api.line.me/v2/bot", transport=httpx.MockTransport(handler))
    client = LineClient("token", http=http)
    assert client.get_content("ok1") == b"jpeg"
    assert seen == ["https://api-data.line.me/v2/bot/message/ok1/content"]
    with pytest.raises(LineError):
        client.get_content("old")
