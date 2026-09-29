import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import SessionLocal
from app.deps import get_current_user
from app.integrations import edge_voice
from app.models import User
from app.security import decode_access_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceConfig(BaseModel):
    # "server" = /voice/tts returns audio; "browser" = the dashboard uses the browser's voices.
    engine: str
    voice: str | None


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.get("/config", response_model=VoiceConfig)
def voice_config(_: User = Depends(get_current_user)):
    s = get_settings()
    if s.tts_engine == "edge":
        return VoiceConfig(engine="server", voice=s.tts_voice)
    return VoiceConfig(engine="browser", voice=None)


def _parts(text: str):
    s = get_settings()
    if s.tts_engine != "edge":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "server voice is off (TTS_ENGINE=browser)")
    log.info("speaking with %s rate=%s pitch=%s numbers=%s", s.tts_voice, s.tts_rate, s.tts_pitch, s.tts_number_rate)
    return edge_voice.speak_parts(
        text, voice=s.tts_voice, rate=s.tts_rate, pitch=s.tts_pitch, number_rate=s.tts_number_rate
    )


@router.post("/tts", responses={200: {"content": {"audio/mpeg": {}}}})
async def tts(body: TtsRequest, _: User = Depends(get_current_user)):
    """Speak text with the configured voice (the whole MP3 at once)."""
    parts = _parts(body.text)
    try:
        audio = b"".join([chunk async for chunk in parts])
    except edge_voice.TtsError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/tts", responses={200: {"content": {"audio/mpeg": {}}}})
async def tts_stream(text: str = Query(min_length=1, max_length=1500), token: str = ""):
    """Same audio, streamed so an <audio> element starts playing before the reply is fully synthesized.

    <audio src> can't send headers, so the JWT comes as ?token= (like the WebSocket).
    """
    try:
        user_id = decode_access_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from None
    with SessionLocal() as db:
        if db.get(User, user_id) is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    parts = _parts(text)
    try:
        first = await anext(parts)  # fail with a status code while we still can
    except edge_voice.TtsError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    except StopAsyncIteration:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "nothing to say") from None

    async def rest():
        yield first
        try:
            async for chunk in parts:
                yield chunk
        except edge_voice.TtsError as e:
            log.warning("voice stream cut short: %s", e)

    return StreamingResponse(rest(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
