import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.deps import get_current_user
from app.integrations import edge_voice
from app.models import User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceConfig(BaseModel):
    # "server" = POST /voice/tts returns audio; "browser" = the dashboard uses the browser's voices.
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


@router.post("/tts", responses={200: {"content": {"audio/mpeg": {}}}})
async def tts(body: TtsRequest, _: User = Depends(get_current_user)):
    """Speak text with the configured voice (MP3)."""
    s = get_settings()
    if s.tts_engine != "edge":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "server voice is off (TTS_ENGINE=browser)")
    log.info("speaking with %s rate=%s pitch=%s", s.tts_voice, s.tts_rate, s.tts_pitch)
    try:
        audio = await edge_voice.synthesize(body.text, voice=s.tts_voice, rate=s.tts_rate, pitch=s.tts_pitch)
    except edge_voice.TtsError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return Response(content=audio, media_type="audio/mpeg")
