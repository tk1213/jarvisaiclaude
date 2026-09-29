import pytest

from app.api import voice as voice_api
from app.config import get_settings
from app.integrations import edge_voice


@pytest.fixture(autouse=True)
def fresh_audio_cache():
    voice_api._cache.clear()


class FakeCommunicate:
    calls: list = []

    def __init__(self, text, voice, rate, pitch, **_timeouts):
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

        def __init__(self, text, voice, rate, pitch, **_timeouts):
            self.prosody = (rate, pitch)
            super().__init__(text, voice, rate, pitch)

    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", PickyService)
    monkeypatch.setattr(get_settings(), "tts_pitch", "+5Hz")
    r = client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert r.status_code == 200 and r.content == b"ok"


def test_rate_and_pitch_are_normalized(client, owner_headers, monkeypatch):
    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(get_settings(), "tts_rate", "-55%")
    monkeypatch.setattr(get_settings(), "tts_pitch", "10hz")
    assert client.post("/voice/tts", json={"text": "x"}, headers=owner_headers).status_code == 200
    assert FakeCommunicate.calls[-1][2:] == ("-50%", "+10Hz")

    monkeypatch.setattr(get_settings(), "tts_pitch", "-5Hz")  # the service gives no audio for this
    client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert FakeCommunicate.calls[-1][3] == "+0Hz"

    monkeypatch.setattr(get_settings(), "tts_rate", "slow")
    r = client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert r.status_code == 502 and "TTS_RATE" in r.json()["detail"]


def test_numbers_are_split_out():
    assert edge_voice.split_numbers("อุณหภูมิ 28.6 องศา ความชื้น 62 %") == [
        ("อุณหภูมิ", False),
        ("28.6", True),
        ("องศา ความชื้น", False),
        ("62", True),
    ]
    assert edge_voice.split_numbers("เปิดแล้วค่ะ") == [("เปิดแล้วค่ะ", False)]


def test_numbers_are_spoken_slower_and_streamed(client, owner_headers, monkeypatch):
    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.calls.clear()
    token = owner_headers["Authorization"].split()[1]
    r = client.get("/voice/tts", params={"text": "กำลังไฟ 1,250 วัตต์", "token": token})
    assert r.status_code == 200 and r.content == b"mp3" * 3 and r.headers["content-type"] == "audio/mpeg"
    rates = {text: rate for text, _, rate, _ in FakeCommunicate.calls}
    assert rates == {"กำลังไฟ": "-8%", "1,250": "-30%", "วัตต์": "-8%"}


def test_stream_requires_token(client):
    assert client.get("/voice/tts", params={"text": "x", "token": "bad"}).status_code == 401


def test_repeated_requests_reuse_one_synthesis(client, owner_headers, monkeypatch):
    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.calls.clear()
    token = owner_headers["Authorization"].split()[1]
    for _ in range(3):
        assert client.get("/voice/tts", params={"text": "สวัสดีค่ะ", "token": token}).content == b"mp3"
    assert len(FakeCommunicate.calls) == 1


def test_google_voice_first_with_slow_numbers(client, owner_headers, monkeypatch):
    import base64

    import httpx

    from app.integrations import google_tts

    sent = {}

    async def fake_post(self, url, params, json):
        sent.update(json)
        return httpx.Response(200, json={"audioContent": base64.b64encode(b"g-mp3").decode()})

    monkeypatch.setattr(get_settings(), "google_tts_api_key", "k")
    monkeypatch.setattr(google_tts.httpx.AsyncClient, "post", fake_post)
    assert client.get("/voice/config", headers=owner_headers).json()["voice"] == "th-TH-Neural2-C"
    r = client.post("/voice/tts", json={"text": "อุณหภูมิ 28.6 องศา <ร้อน>"}, headers=owner_headers)
    assert r.content == b"g-mp3"
    assert sent["input"]["ssml"] == '<speak>อุณหภูมิ <prosody rate="70%">28.6</prosody> องศา &lt;ร้อน&gt;</speak>'
    assert sent["audioConfig"] == {"audioEncoding": "MP3", "speakingRate": 0.92, "pitch": 1.5}


def test_google_failure_falls_back_to_edge(client, owner_headers, monkeypatch):
    import httpx

    from app.integrations import google_tts

    async def denied(self, url, params, json):
        return httpx.Response(403, json={"error": {"message": "API key not valid"}})

    monkeypatch.setattr(get_settings(), "google_tts_api_key", "bad")
    monkeypatch.setattr(google_tts.httpx.AsyncClient, "post", denied)
    monkeypatch.setattr(edge_voice.edge_tts, "Communicate", FakeCommunicate)
    assert client.post("/voice/tts", json={"text": "สวัสดีค่ะ"}, headers=owner_headers).content == b"mp3"
