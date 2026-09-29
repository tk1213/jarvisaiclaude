from app.config import get_settings
from app.integrations import edge_voice


class FakeCommunicate:
    calls: list = []

    def __init__(self, text, voice, rate, pitch):
        FakeCommunicate.calls.append((text, voice, rate, pitch))

    async def stream(self):
        yield {"type": "WordBoundary"}
        yield {"type": "audio", "data": b"mp"}
        yield {"type": "audio", "data": b"3"}


def test_server_voice(client, owner_headers, monkeypatch):
    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", FakeCommunicate)
    assert client.get("/voice/config", headers=owner_headers).json() == {"engine": "server", "voice": "th-TH-PremwadeeNeural"}
    r = client.post("/voice/tts", json={"text": "สวัสดีค่ะ"}, headers=owner_headers)
    assert r.status_code == 200 and r.content == b"mp3" and r.headers["content-type"] == "audio/mpeg"
    assert FakeCommunicate.calls[-1] == ("สวัสดีค่ะ", "th-TH-PremwadeeNeural", "+8%", "+15Hz")


def test_voice_failure_is_reported(client, owner_headers, monkeypatch):
    class Broken(FakeCommunicate):
        async def stream(self):
            raise ConnectionError("offline")
            yield

    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", Broken)
    r = client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert r.status_code == 502 and "offline" in r.json()["detail"]


def test_browser_engine(client, owner_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "tts_engine", "browser")
    assert client.get("/voice/config", headers=owner_headers).json() == {"engine": "browser", "voice": None}
    assert client.post("/voice/tts", json={"text": "x"}, headers=owner_headers).status_code == 503


def test_tts_requires_login(client):
    assert client.post("/voice/tts", json={"text": "x"}).status_code == 401
