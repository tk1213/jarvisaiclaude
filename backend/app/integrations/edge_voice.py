"""Spoken replies with Microsoft Edge's online neural voices (the "Read aloud" service, via edge-tts).

Free and needs no key, but it's an unofficial endpoint: if it fails, the dashboard
falls back to the browser's own voices.
"""

import logging
import re

import edge_tts

log = logging.getLogger(__name__)

MAX_CHARS = 1500
# The service only speaks between half and double speed; outside that it silently returns no audio.
RATE_RANGE = (-50, 100)


class TtsError(Exception):
    pass


def clamp_rate(rate: str) -> str:
    """Keep a "+N%"/"-N%" rate inside what the service accepts (e.g. -55% becomes -50%)."""
    m = re.fullmatch(r"\s*([+-]?)(\d+)\s*%\s*", rate)
    if not m:
        raise TtsError(f"TTS_RATE must look like +10% or -20%, got {rate!r}")
    value = int(m[2]) * (-1 if m[1] == "-" else 1)
    clamped = max(RATE_RANGE[0], min(RATE_RANGE[1], value))
    if clamped != value:
        log.warning("TTS_RATE %s is outside %s..%s%%; using %+d%%", rate, *RATE_RANGE, clamped)
    return f"{clamped:+d}%"


def normalize_pitch(pitch: str) -> str:
    m = re.fullmatch(r"\s*([+-]?)(\d+)\s*[Hh][Zz]\s*", pitch)
    if not m:
        raise TtsError(f"TTS_PITCH must look like +15Hz or -10Hz, got {pitch!r}")
    return f"{m[1] or '+'}{m[2]}Hz"


async def synthesize(text: str, *, voice: str, rate: str, pitch: str) -> bytes:
    rate, pitch = clamp_rate(rate), normalize_pitch(pitch)
    audio = bytearray()
    try:
        async for chunk in edge_tts.Communicate(text[:MAX_CHARS], voice, rate=rate, pitch=pitch).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
    except Exception as e:  # edge-tts raises aiohttp and its own errors
        raise TtsError(f"Edge voice failed: {e.__class__.__name__}: {e}") from None
    if not audio:
        raise TtsError("Edge voice returned no audio")
    return bytes(audio)
