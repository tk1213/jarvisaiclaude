import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, core, devices, voice, ws
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


@app.exception_handler(TuyaError)
async def tuya_error_handler(_: Request, exc: TuyaError):
    return JSONResponse(status_code=502, content={"detail": str(exc), "tuya_code": exc.code})


@app.get("/health")
def health():
    return {"status": "ok", "tuya_mode": get_settings().tuya_mode}


# The built dashboard (frontend/dist) is served at / when present. Mounted last so
# API routes and /docs take precedence.
_DASHBOARD = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DASHBOARD.is_dir():
    app.mount("/", StaticFiles(directory=_DASHBOARD, html=True), name="dashboard")
