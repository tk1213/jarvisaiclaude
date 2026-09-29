from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import auth, devices
from app.config import get_settings
from app.db import init_db
from app.integrations.tuya import TuyaError


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.tuya_mode == "live" and s.jwt_secret == "change-me":
        raise RuntimeError("Set JWT_SECRET before running with TUYA_MODE=live")
    init_db()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(devices.router)


@app.exception_handler(TuyaError)
async def tuya_error_handler(_: Request, exc: TuyaError):
    return JSONResponse(status_code=502, content={"detail": str(exc), "tuya_code": exc.code})


@app.get("/health")
def health():
    return {"status": "ok", "tuya_mode": get_settings().tuya_mode}
