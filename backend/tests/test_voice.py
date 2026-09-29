import base64

import httpx

from app.config import get_settings
from app.integrations import google_tts


def test_browser_engine_without_key(client, owner_headers):
    assert client.get("/voice/config", headers=owner_headers).json() == {"engine": "browser", "voice": None}
    assert client.post("/voice/tts", json={"text": "สวัสดีค่ะ"}, headers=owner_headers).status_code == 503


def test_google_tts(client, owner_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_tts_api_key", "k")
    sent = {}

    def fake_post(url, params, json, timeout):
        sent.update(json)
        return httpx.Response(200, json={"audioContent": base64.b64encode(b"mp3").decode()})

    monkeypatch.setattr(google_tts.httpx, "post", fake_post)
    assert client.get("/voice/config", headers=owner_headers).json()["engine"] == "google"
    r = client.post("/voice/tts", json={"text": "สวัสดีค่ะ"}, headers=owner_headers)
    assert r.status_code == 200 and r.content == b"mp3" and r.headers["content-type"] == "audio/mpeg"
    assert sent["voice"] == {"languageCode": "th-TH", "name": "th-TH-Neural2-C"}
    assert sent["audioConfig"]["pitch"] == 2.0


def test_google_error_is_reported(client, owner_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_tts_api_key", "bad")
    monkeypatch.setattr(
        google_tts.httpx, "post", lambda *a, **k: httpx.Response(403, json={"error": {"message": "API key not valid"}})
    )
    r = client.post("/voice/tts", json={"text": "x"}, headers=owner_headers)
    assert r.status_code == 502 and "API key not valid" in r.json()["detail"]


def test_tts_requires_login(client):
    assert client.post("/voice/tts", json={"text": "x"}).status_code == 401
