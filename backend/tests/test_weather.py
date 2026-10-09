import json

import httpx
import pytest

from app.core import tools
from app.core.tools import ToolContext, run_tool
from app.integrations import weather

FORECAST = {
    "current": {
        "time": "2026-10-09T20:15",
        "temperature_2m": 28.4,
        "apparent_temperature": 32.1,
        "relative_humidity_2m": 80,
        "precipitation": 0.0,
        "weather_code": 3,
        "wind_speed_10m": 7.2,
    },
    "hourly": {
        "time": [f"2026-10-09T{h:02d}:00" for h in range(24)] + [f"2026-10-10T{h:02d}:00" for h in range(24)],
        "precipitation_probability": list(range(48)),
    },
    "daily": {
        "time": ["2026-10-09", "2026-10-10"],
        "weather_code": [3, 95],
        "temperature_2m_max": [33.0, 32.5],
        "temperature_2m_min": [25.1, 25.4],
        "precipitation_probability_max": [40, 85],
        "precipitation_sum": [1.2, 18.4],
    },
}
AIR = {"current": {"time": "2026-10-09T20:00", "pm2_5": 24.6, "pm10": 31.0, "us_aqi": 77}}


def client(air_status: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.open-meteo.com":
            return httpx.Response(200, json=FORECAST)
        return httpx.Response(air_status, json=AIR)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def test_weather_now_rain_hours_days_and_air():
    c, seen = client()
    w = weather.get_weather(13.8, 100.6, "Asia/Bangkok", 2, client=c)
    assert w["now"] == {
        "time": "2026-10-09T20:15",
        "condition": "เมฆมาก",
        "temperature_c": 28.4,
        "feels_like_c": 32.1,
        "humidity_percent": 80,
        "rain_mm": 0.0,
        "wind_kmh": 7.2,
    }
    # From the current hour (20:00) on, 12 hours.
    hours = w["rain_chance_next_hours"]
    assert (len(hours), hours[0], hours[-1]) == (12, {"time": "20:00", "percent": 20}, {"time": "07:00", "percent": 31})
    assert w["days"][1] == {
        "date": "2026-10-10",
        "weekday": "Saturday",
        "condition": "พายุฝนฟ้าคะนอง",
        "max_c": 32.5,
        "min_c": 25.4,
        "rain_chance_percent": 85,
        "rain_mm": 18.4,
    }
    assert w["air"] == {"pm2_5": 24.6, "pm10": 31.0, "us_aqi": 77}
    assert seen[0].url.params["forecast_days"] == "2" and seen[0].url.params["timezone"] == "Asia/Bangkok"


def test_weather_without_air_quality():
    c, _ = client(air_status=503)
    w = weather.get_weather(13.8, 100.6, "Asia/Bangkok", 1, client=c)
    assert "air" not in w and w["now"]["temperature_c"] == 28.4
    assert [d["date"] for d in w["days"]] == ["2026-10-09"] and len(w["rain_chance_next_hours"]) == 12


def test_tool_uses_home_unless_a_place_is_given(monkeypatch):
    calls = []

    def fake(lat, lon, tz, days):
        calls.append((lat, lon, days))
        return {"now": {}}

    monkeypatch.setattr(weather, "get_weather", fake)
    ctx = ToolContext(db=None, tuya=None, user=None)
    out, err = run_tool(ctx, "get_weather", {"place": None, "latitude": None, "longitude": None, "days": 1})
    assert not err and json.loads(out)["place"] == "ลาดพร้าว"
    out, err = run_tool(ctx, "get_weather", {"place": "เชียงใหม่", "latitude": 18.79, "longitude": 98.98, "days": 30})
    assert json.loads(out)["place"] == "เชียงใหม่"
    assert calls == [(13.803, 100.607, 1), (18.79, 98.98, 7)]


def test_tool_reports_a_failed_lookup(monkeypatch):
    def broken(*a):
        raise weather.WeatherError("ดึงข้อมูลอากาศจาก Open-Meteo ไม่ได้: timeout")

    monkeypatch.setattr(weather, "get_weather", broken)
    out, err = run_tool(ToolContext(db=None, tuya=None, user=None), "get_weather", {"place": None, "latitude": None, "longitude": None, "days": 1})
    assert err and "Open-Meteo" in out


def test_tool_is_listed():
    assert any(t["name"] == "get_weather" for t in tools.TOOLS)


@pytest.mark.parametrize("code,text", [(0, "ท้องฟ้าแจ่มใส"), (63, "ฝนตกปานกลาง"), (None, "ไม่ทราบ"), (12, "ไม่ทราบ")])
def test_condition(code, text):
    assert weather.condition(code) == text
