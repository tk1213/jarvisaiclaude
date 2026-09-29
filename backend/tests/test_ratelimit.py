import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.ratelimit import RateLimiter


def test_limiter_window(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("app.ratelimit.time.monotonic", lambda: now[0])
    limiter = RateLimiter(window_seconds=60)

    for _ in range(3):
        limiter.hit("k", 3)
    with pytest.raises(HTTPException) as e:
        limiter.hit("k", 3)
    assert e.value.status_code == 429 and e.value.headers["Retry-After"] == "61"
    limiter.hit("other", 3)  # keys are independent

    now[0] += 60
    limiter.hit("k", 3)  # window has slid past the old hits


def test_login_is_rate_limited(client, owner_headers):
    limit = get_settings().rate_limit_login_per_minute
    # owner_headers already logged in once
    for _ in range(limit - 1):
        client.post("/auth/login", json={"username": "owner", "password": "wrong-password"})
    r = client.post("/auth/login", json={"username": "owner", "password": "password123"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_device_control_is_rate_limited(client, owner_headers):
    client.post("/devices/sync", headers=owner_headers)
    limit = get_settings().rate_limit_control_per_minute
    for _ in range(limit):
        assert client.post("/devices/1/power", json={"on": True}, headers=owner_headers).status_code == 200
    assert client.post("/devices/1/power", json={"on": True}, headers=owner_headers).status_code == 429
    # read-only endpoints are not limited
    assert client.get("/devices/1", headers=owner_headers).status_code == 200
