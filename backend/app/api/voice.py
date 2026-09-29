from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.deps import get_current_user
from app.integrations import google_tts
from app.models import User

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceConfig(BaseModel):
    # "google" = POST /voice/tts returns audio; "browser" = the dashboard uses the browser's voices.
    engine: str
    voice: str | None


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.get("/config", response_model=VoiceConfig)
def voice_config(_: User = Depends(get_current_user)):
    s = get_settings()
    if s.google_tts_api_key:
        return VoiceConfig(engine="google", voice=s.google_tts_voice)
    return VoiceConfig(engine="browser", voice=None)


@router.post("/tts", responses={200: {"content": {"audio/mpeg": {}}}})
def tts(body: TtsRequest, _: User = Depends(get_current_user)):
    """Speak text with the configured Google voice (MP3)."""
    s = get_settings()
    if not s.google_tts_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GOOGLE_TTS_API_KEY is not set")
    try:
        audio = google_tts.synthesize(
            body.text, api_key=s.google_tts_api_key, voice=s.google_tts_voice, pitch=s.google_tts_pitch, rate=s.google_tts_rate
        )
    except google_tts.TtsError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return Response(content=audio, media_type="audio/mpeg")
