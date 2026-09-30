import asyncio
import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import SessionLocal
from app.deps import get_current_user
from app.integrations import edge_voice, google_tts
from app.models import User
from app.security import decode_access_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])
# Why the last reply couldn't be voiced; an <audio> element can't read error bodies, so the page asks here.
_last_error: str | None = None


class VoiceConfig(BaseModel):
    # "server" = /voice/tts returns audio; "browser" = the dashboard uses the browser's voices.
    engine: str
    voice: str | None


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.get("/config", response_model=VoiceConfig)
def voice_config(_: User = Depends(get_current_user)):
    s = get_settings()
    if s.google_tts_api_key:
        return VoiceConfig(engine="server", voice=s.google_tts_voice)
    if s.tts_engine == "edge":
        return VoiceConfig(engine="server", voice=s.tts_voice)
    return VoiceConfig(engine="browser", voice=None)


_CACHE_SECONDS = 120
_cache: dict[tuple, tuple[float, bytes]] = {}
_inflight: dict[tuple, asyncio.Future] = {}


# Words the voices would otherwise spell out letter by letter ("J-A-R-V-I-S").
# ASCII-only boundaries: Python counts Thai letters as word characters, and "JARVISค่ะ" has no space.
PRONUNCIATIONS = [
    # "JARVIS", "Jarvis", "J.A.R.V.I.S.", "J A R V I S"
    (re.compile(r"(?<![a-z])j[.\s]*a[.\s]*r[.\s]*v[.\s]*i[.\s]*s(?![a-z])\.?", re.IGNORECASE), "จาร์วิส"),
    # the name spelled out in Thai letters
    (re.compile(r"เจ\s*เอ\s*อาร์\s*วี\s*ไอ\s*เอส"), "จาร์วิส"),
]


def for_speech(text: str) -> str:
    for pattern, spoken in PRONUNCIATIONS:
        text = pattern.sub(spoken, text)
    return text


async def _audio_for(text: str) -> bytes:
    """The MP3 for text, synthesized once: browsers may request the same <audio> URL more than once,
    and every extra synthesis is another call to the voice service (which then tends to fail)."""
    text = for_speech(text)
    s = get_settings()
    if s.tts_engine != "edge" and not s.google_tts_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "server voice is off (TTS_ENGINE=browser)")
    key = (text, s.google_tts_api_key != "", s.google_tts_voice, s.google_tts_pitch, s.tts_voice, s.tts_rate, s.tts_pitch, s.tts_number_rate)
    now = time.monotonic()
    for k in [k for k, (at, _) in _cache.items() if now - at > _CACHE_SECONDS]:
        del _cache[k]
    if key in _cache:
        return _cache[key][1]
    if key in _inflight:
        return await asyncio.shield(_inflight[key])

    future = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        started = time.perf_counter()
        audio = await _synthesize(text)
        log.info("voice ready in %.1fs", time.perf_counter() - started)
    except Exception as e:
        future.set_exception(e)
        future.exception()  # mark retrieved when nobody else was waiting
        raise
    finally:
        _inflight.pop(key, None)
    future.set_result(audio)
    _cache[key] = (time.monotonic(), audio)
    return audio


async def _synthesize(text: str) -> bytes:
    s = get_settings()
    google_error = None
    if s.google_tts_api_key:
        log.info("speaking with Google %s rate=%s pitch=%sst", s.google_tts_voice, s.tts_rate, s.google_tts_pitch)
        try:
            return await google_tts.synthesize(
                text,
                api_key=s.google_tts_api_key,
                voice=s.google_tts_voice,
                rate=s.tts_rate,
                pitch=s.google_tts_pitch,
                number_rate=s.tts_number_rate,
            )
        except google_tts.TtsError as e:
            google_error = e
            if s.tts_engine != "edge":
                raise edge_voice.TtsError(str(e)) from None
            log.warning("Google voice failed, trying Edge: %s", e)
    log.info("speaking with Edge %s rate=%s pitch=%s numbers=%s", s.tts_voice, s.tts_rate, s.tts_pitch, s.tts_number_rate)
    try:
        parts = edge_voice.speak_parts(text, voice=s.tts_voice, rate=s.tts_rate, pitch=s.tts_pitch, number_rate=s.tts_number_rate)
        return b"".join([chunk async for chunk in parts])
    except edge_voice.TtsError as e:
        if google_error:
            raise edge_voice.TtsError(f"{google_error} / {e}") from None
        raise


def _failed(e: Exception) -> HTTPException:
    global _last_error
    _last_error = str(e)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, _last_error)


@router.get("/last-error")
def last_error(_: User = Depends(get_current_user)):
    return {"error": _last_error}


@router.post("/tts", responses={200: {"content": {"audio/mpeg": {}}}})
async def tts(body: TtsRequest, _: User = Depends(get_current_user)):
    """Speak text with the configured voice (the whole MP3 at once)."""
    try:
        audio = await _audio_for(body.text)
    except edge_voice.TtsError as e:
        raise _failed(e) from None
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/tts", responses={200: {"content": {"audio/mpeg": {}}}})
async def tts_stream(text: str = Query(min_length=1, max_length=1500), token: str = ""):
    """Same audio for an <audio> element (numbers slowed, parts synthesized in parallel).

    <audio src> can't send headers, so the JWT comes as ?token= (like the WebSocket).
    """
    try:
        user_id = decode_access_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from None
    with SessionLocal() as db:
        if db.get(User, user_id) is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    try:
        audio = await _audio_for(text)
    except edge_voice.TtsError as e:
        raise _failed(e) from None
    # A complete body with a known length: the <audio> element plays it without re-requesting.
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
