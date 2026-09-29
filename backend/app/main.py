import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, core, devices, ws
from app.config import get_settings
from app.db import init_db
from app.integrations.tuya import TuyaError, build_pulsar_consumer
from app.realtime import hub

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.tuya_mode == "live" and s.jwt_secret == "change-me":
        raise RuntimeError("Set JWT_SECRET before running with TUYA_MODE=live")
    init_db()
    hub.bind_loop(asyncio.get_running_loop())

    consumer = build_pulsar_consumer()
    task = asyncio.create_task(consumer.run()) if consumer else None
    yield
    hub.bind_loop(None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(core.router)
app.include_router(ws.router)


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
