import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import account, auth, catalog, core, devices, documents, line, voice, ws
from app.config import get_settings
from app.db import AccountSession, SessionLocal, init_db
from app.integrations.flowaccount import get_flowaccount_client
from app.integrations.tuya import TuyaError, build_pulsar_consumer, get_tuya_client
from app.realtime import hub
from app.services import accounting
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


ACCOUNT_SYNC_HOURS = 24


def _sync_account_if_due() -> None:
    with AccountSession() as db:
        synced = accounting.last_sync(db)
        if synced and (datetime.now(timezone.utc) - synced).total_seconds() < ACCOUNT_SYNC_HOURS * 3600:
            return
        counts = accounting.sync_flowaccount(db, get_flowaccount_client())
        log.info("Account: read FlowAccount documents (%s)", counts)


async def _sync_account_daily() -> None:
    """Keep the Account page's income/expenses current: FlowAccount is read once a day (checked hourly)."""
    while True:
        try:
            await asyncio.to_thread(_sync_account_if_due)
        except Exception:
            log.exception("Account: FlowAccount sync failed (will retry in an hour)")
        await asyncio.sleep(3600)


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
    if s.flowaccount_mode == "live":
        tasks.append(asyncio.create_task(_sync_account_daily()))
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
app.include_router(account.router)


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
