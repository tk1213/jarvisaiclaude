"""Google Cloud Text-to-Speech: turns JARVIS's replies into MP3 audio for the dashboard."""

import base64

import httpx

API_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
# Google's per-request limit is 5000 bytes; Thai is 3 bytes per character in UTF-8.
MAX_CHARS = 1500


class TtsError(Exception):
    pass


def synthesize(text: str, *, api_key: str, voice: str, pitch: float, rate: float, timeout: float = 15) -> bytes:
    audio_config = {"audioEncoding": "MP3", "speakingRate": rate}
    if "Chirp" not in voice:  # Chirp voices reject the pitch setting
        audio_config["pitch"] = pitch
    body = {
        "input": {"text": text[:MAX_CHARS]},
        "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
        "audioConfig": audio_config,
    }
    try:
        r = httpx.post(API_URL, params={"key": api_key}, json=body, timeout=timeout)
    except httpx.HTTPError as e:
        raise TtsError(f"could not reach Google Text-to-Speech: {e.__class__.__name__}") from None
    if r.status_code != 200:
        try:
            message = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = r.text[:200]
        raise TtsError(f"Google Text-to-Speech error {r.status_code}: {message}")
    return base64.b64decode(r.json()["audioContent"])
