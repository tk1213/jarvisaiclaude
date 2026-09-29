"""Spoken replies with Microsoft Edge's online neural voices (the "Read aloud" service, via edge-tts).

Free and needs no key, but it's an unofficial endpoint: if it fails, the dashboard
falls back to the browser's own voices.
"""

import edge_tts

MAX_CHARS = 1500


class TtsError(Exception):
    pass


async def synthesize(text: str, *, voice: str, rate: str, pitch: str) -> bytes:
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
