"""Google Cloud Text-to-Speech: the official, keyed voice service, used first when GOOGLE_TTS_API_KEY is set."""

import base64
import re
from xml.sax.saxutils import escape

import httpx

from app.integrations.edge_voice import NUMBER

API_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
# Google's limit is 5000 bytes of input; Thai is 3 bytes per character in UTF-8, plus the SSML tags.
MAX_CHARS = 1200


class TtsError(Exception):
    pass


def percent(value: str) -> int:
    """'+8%' / '-20%' -> 8 / -20."""
    m = re.fullmatch(r"\s*([+-]?)(\d+)\s*%\s*", value)
    if not m:
        raise TtsError(f"expected a rate like -20%, got {value!r}")
    return int(m[2]) * (-1 if m[1] == "-" else 1)


def to_ssml(text: str, number_rate: str) -> str:
    """Plain text as SSML with numbers read more slowly, relative to the rest of the sentence."""
    slow = f"{max(20, 100 + percent(number_rate))}%"
    out, pos = [], 0
    for m in NUMBER.finditer(text):
        out.append(escape(text[pos : m.start()]))
        out.append(f'<prosody rate="{slow}">{escape(m.group())}</prosody>')
        pos = m.end()
    out.append(escape(text[pos:]))
    return f"<speak>{''.join(out)}</speak>"


async def synthesize(text: str, *, api_key: str, voice: str, rate: str, pitch: float, number_rate: str, timeout: float = 10) -> bytes:
    speaking_rate = min(4.0, max(0.25, 1 + percent(rate) / 100))
    audio_config: dict = {"audioEncoding": "MP3", "speakingRate": speaking_rate}
    if "Chirp" not in voice:  # Chirp voices take neither pitch nor SSML
        audio_config["pitch"] = pitch
        payload = {"ssml": to_ssml(text[:MAX_CHARS], number_rate)}
    else:
        payload = {"text": text[:MAX_CHARS]}
    body = {
        "input": payload,
        "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
        "audioConfig": audio_config,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(API_URL, params={"key": api_key}, json=body)
    except httpx.HTTPError as e:
        raise TtsError(f"could not reach Google Text-to-Speech: {e.__class__.__name__}") from None
    if r.status_code != 200:
        try:
            message = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = r.text[:200]
        raise TtsError(f"Google Text-to-Speech error {r.status_code}: {message}")
    return base64.b64decode(r.json()["audioContent"])
