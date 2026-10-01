import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, catalog, core, devices, documents, line, voice, ws
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.integrations.tuya import TuyaError, build_pulsar_consumer, get_tuya_client
from app.realtime import hub
from app.services.devices import refresh_ir_acs

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _poll_ir_acs_once() -> None:
    with SessionLocal() as db:
        for device in refresh_ir_acs(db, get_tuya_client()):
            log.info("IR AC %s changed outside JARVIS: %s", device.name, device.status)


async def _poll_ir_acs(interval: int) -> None:
    """Keep IR air conditioners current; commits reach the dashboard through the realtime hub."""
    while True:
        try:
            await asyncio.to_thread(_poll_ir_acs_once)
        except Exception:
            log.exception("IR AC poll failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.tuya_mode == "live" and s.jwt_secret == "change-me":
        raise RuntimeError("Set JWT_SECRET before running with TUYA_MODE=live")
    init_db()
    female = f"Google {s.google_tts_voice}" if s.google_tts_api_key else f"Edge {s.tts_voice}"
    log.info(
        "voice: female=%s rate=%s pitch=%s | numbers rate=%s | male=Edge %s rate=%s (from .env; restart the server after changing)",
        female, s.tts_rate, s.google_tts_pitch if s.google_tts_api_key else s.tts_pitch, s.tts_number_rate, s.tts_voice_male, s.tts_rate_male,
    )
    hub.bind_loop(asyncio.get_running_loop())

    consumer = build_pulsar_consumer()
    tasks = []
    if consumer:
        tasks.append(asyncio.create_task(consumer.run()))
    if s.tuya_mode == "live" and s.ir_ac_poll_seconds > 0:
        tasks.append(asyncio.create_task(_poll_ir_acs(s.ir_ac_poll_seconds)))
    yield
    hub.bind_loop(None)
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(core.router)
app.include_router(ws.router)
app.include_router(voice.router)
app.include_router(line.router)
app.include_router(documents.router)
app.include_router(catalog.router)


@app.exception_handler(TuyaError)
async def tuya_error_handler(_: Request, exc: TuyaError):
    return JSONResponse(status_code=502, content={"detail": str(exc), "tuya_code": exc.code})


@app.get("/health")
def health():
    return {"status": "ok", "tuya_mode": get_settings().tuya_mode}


# The built dashboard (frontend/dist) is served at / when present. Mounted last so
# API routes and /docs take precedence.
_DASHBOARD = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class DashboardFiles(StaticFiles):
    """Static files where the HTML is always revalidated, so a rebuilt dashboard shows up on a normal reload.

    Assets under /assets have hashed names and can be cached; without this header
    browsers may keep serving an old index.html that points at the old assets.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.media_type == "text/html":
            response.headers["Cache-Control"] = "no-cache"
        return response


if _DASHBOARD.is_dir():
    app.mount("/", DashboardFiles(directory=_DASHBOARD, html=True), name="dashboard")
