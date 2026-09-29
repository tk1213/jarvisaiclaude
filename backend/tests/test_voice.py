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
    assert FakeCommunicate.calls[-1] == ("สวัสดีค่ะ", "th-TH-PremwadeeNeural", "-8%", "+15Hz")


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


def test_dashboard_html_is_revalidated(client):
    from pathlib import Path

    if not (Path(__file__).resolve().parents[2] / "frontend" / "dist").is_dir():
        return
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_falls_back_to_default_prosody(client, owner_headers, monkeypatch):
    class PickyService(FakeCommunicate):
        async def stream(self):
            if self.prosody != ("+0%", "+0Hz"):
                return  # the service accepted the request but sent no audio
            yield {"type": "audio", "data": b"ok"}

        def __init__(self, text, voice, rate, pitch):
            self.prosody = (rate, pitch)
            super().__init__(text, voice, rate, pitch)

    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", PickyService)
    monkeypatch.setattr(get_settings(), "tts_pitch", "-5Hz")
    r = client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert r.status_code == 200 and r.content == b"ok"


def test_rate_and_pitch_are_normalized(client, owner_headers, monkeypatch):
    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(get_settings(), "tts_rate", "-55%")
    monkeypatch.setattr(get_settings(), "tts_pitch", "10hz")
    assert client.post("/voice/tts", json={"text": "x"}, headers=owner_headers).status_code == 200
    assert FakeCommunicate.calls[-1][2:] == ("-50%", "+10Hz")

    monkeypatch.setattr(get_settings(), "tts_rate", "slow")
    r = client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert r.status_code == 502 and "TTS_RATE" in r.json()["detail"]
