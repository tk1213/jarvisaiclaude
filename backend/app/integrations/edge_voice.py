"""Spoken replies with Microsoft Edge's online neural voices (the "Read aloud" service, via edge-tts).

Free and needs no key, but it's an unofficial endpoint: if it fails, the dashboard
falls back to the browser's own voices.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator

import edge_tts

log = logging.getLogger(__name__)

MAX_CHARS = 1500
# Numbers ("28.6", "1,250", "-3") are spoken separately at a slower rate so they're easy to catch.
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
MAX_NUMBER_PARTS = 8
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
    if m[1] == "-" and int(m[2]) > 0:
        # The Thai voices return no audio for a lowered pitch, so the voice's natural pitch is the floor.
        log.warning("TTS_PITCH %s: lowering the pitch isn't supported by this voice; using +0Hz", pitch)
        return "+0Hz"
    return f"+{m[2]}Hz"


async def _stream(text: str, voice: str, rate: str, pitch: str) -> bytes:
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    if not audio:
        raise edge_tts.exceptions.NoAudioReceived("no audio")
    return bytes(audio)


def split_numbers(text: str) -> list[tuple[str, bool]]:
    """[(segment, is_number), ...] with blank or punctuation-only pieces dropped."""
    parts: list[tuple[str, bool]] = []
    pos = 0
    for m in NUMBER.finditer(text):
        parts.append((text[pos : m.start()], False))
        parts.append((m.group(), True))
        pos = m.end()
    parts.append((text[pos:], False))
    return [(p.strip(), is_num) for p, is_num in parts if re.search(r"\w", p)]


async def speak_parts(text: str, *, voice: str, rate: str, pitch: str, number_rate: str) -> AsyncIterator[bytes]:
    """MP3 audio for text, in order, with numbers slowed down. Parts are synthesized concurrently
    and yielded as soon as each is ready, so playback can start before the whole reply is done.
    MP3 frames from the same voice concatenate into one playable stream."""
    text = text[:MAX_CHARS]
    parts = split_numbers(text)
    if not any(is_num for _, is_num in parts) or len(parts) > 2 * MAX_NUMBER_PARTS + 1:
        parts = [(text, False)]
    tasks = [
        asyncio.create_task(synthesize(p, voice=voice, rate=number_rate if is_num else rate, pitch=pitch))
        for p, is_num in parts
    ]
    try:
        for task in tasks:
            yield await task
    finally:
        for task in tasks:
            task.cancel()


async def synthesize(text: str, *, voice: str, rate: str, pitch: str) -> bytes:
    """Speak with the configured rate/pitch; if the service returns nothing, retry once as configured
    (it fails transiently) and then with its default rate/pitch, so the reply keeps the same voice."""
    rate, pitch = clamp_rate(rate), normalize_pitch(pitch)
    attempts = [(rate, pitch), (rate, pitch)]
    if (rate, pitch) != ("+0%", "+0Hz"):
        attempts.append(("+0%", "+0Hz"))
    error: Exception | None = None
    for i, (r, p) in enumerate(attempts):
        try:
            audio = await _stream(text[:MAX_CHARS], voice, r, p)
        except Exception as e:  # edge-tts raises aiohttp and its own errors
            error = e
            log.warning("Edge voice attempt %d (rate=%s pitch=%s) failed: %s: %s", i + 1, r, p, e.__class__.__name__, e)
            continue
        if i == len(attempts) - 1 and len(attempts) == 3:
            log.warning("spoke with the default rate/pitch because rate=%s pitch=%s produced no audio", rate, pitch)
        return audio
    raise TtsError(f"Edge voice failed: {error.__class__.__name__}: {error}")
