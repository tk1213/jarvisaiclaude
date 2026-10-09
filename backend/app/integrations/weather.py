"""Live weather and air quality from Open-Meteo (free, no API key): current conditions, the next hours' rain
chance, a few days' forecast and PM2.5. Web search only finds stale snapshots of weather pages.
"""

import logging
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
RAIN_HOURS = 12  # hourly rain chance reported for the next this-many hours

# WMO weather codes as Open-Meteo reports them.
CONDITIONS = {
    0: "ท้องฟ้าแจ่มใส",
    1: "มีเมฆเล็กน้อย",
    2: "มีเมฆบางส่วน",
    3: "เมฆมาก",
    45: "มีหมอก",
    48: "มีหมอก",
    51: "ฝนปรอยๆ",
    53: "ฝนปรอยๆ",
    55: "ฝนปรอยหนาแน่น",
    56: "ฝนปรอยๆ",
    57: "ฝนปรอยหนาแน่น",
    61: "ฝนตกเล็กน้อย",
    63: "ฝนตกปานกลาง",
    65: "ฝนตกหนัก",
    66: "ฝนตกเล็กน้อย",
    67: "ฝนตกหนัก",
    80: "ฝนตกเป็นช่วงๆ",
    81: "ฝนตกเป็นช่วงๆ",
    82: "ฝนตกหนักเป็นช่วงๆ",
    95: "พายุฝนฟ้าคะนอง",
    96: "พายุฝนฟ้าคะนองมีลูกเห็บ",
    99: "พายุฝนฟ้าคะนองมีลูกเห็บ",
}


class WeatherError(RuntimeError):
    pass


def condition(code) -> str:
    return CONDITIONS.get(int(code), "ไม่ทราบ") if code is not None else "ไม่ทราบ"


def _get(client: httpx.Client, url: str, params: dict) -> dict:
    r = client.get(url, params=params)
    r.raise_for_status()
    return r.json()


def get_weather(latitude: float, longitude: float, timezone: str, days: int, client: httpx.Client | None = None) -> dict:
    """Now, the next hours' rain chance, `days` days of forecast and air quality for one point."""
    owned = client is None
    client = client or httpx.Client(timeout=10)
    try:
        try:
            data = _get(
                client,
                FORECAST_URL,
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": timezone,
                    "forecast_days": max(days, 2),  # tomorrow's hours too, for an evening's "next 12 hours"
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                    "hourly": "precipitation_probability",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
                },
            )
        except (httpx.HTTPError, ValueError) as e:
            raise WeatherError(f"ดึงข้อมูลอากาศจาก Open-Meteo ไม่ได้: {e}") from None
        try:
            air = _get(client, AIR_URL, {"latitude": latitude, "longitude": longitude, "timezone": timezone, "current": "pm2_5,pm10,us_aqi"})
        except (httpx.HTTPError, ValueError) as e:
            log.info("air quality not available: %s", e)  # the weather is still worth answering with
            air = {}
    finally:
        if owned:
            client.close()

    now = data.get("current") or {}
    out = {
        "source": "Open-Meteo",
        "now": {
            "time": now.get("time"),
            "condition": condition(now.get("weather_code")),
            "temperature_c": now.get("temperature_2m"),
            "feels_like_c": now.get("apparent_temperature"),
            "humidity_percent": now.get("relative_humidity_2m"),
            "rain_mm": now.get("precipitation"),
            "wind_kmh": now.get("wind_speed_10m"),
        },
        "rain_chance_next_hours": _next_hours(data.get("hourly") or {}, now.get("time")),
        "days": _days(data.get("daily") or {})[:days],
    }
    current_air = air.get("current") or {}
    if current_air:
        out["air"] = {"pm2_5": current_air.get("pm2_5"), "pm10": current_air.get("pm10"), "us_aqi": current_air.get("us_aqi")}
    return out


def _next_hours(hourly: dict, now: str | None) -> list[dict]:
    """Rain chance for the hours from the current one on, e.g. [{"time": "18:00", "percent": 60}, ...]."""
    times, chances = hourly.get("time") or [], hourly.get("precipitation_probability") or []
    start = (now or "")[:13]  # "2026-10-09T20"
    rows = [(t, c) for t, c in zip(times, chances) if t[:13] >= start]
    return [{"time": t[11:16], "percent": c} for t, c in rows[:RAIN_HOURS]]


def _days(daily: dict) -> list[dict]:
    keys = ("time", "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max", "precipitation_sum")
    columns = [daily.get(k) or [] for k in keys]
    days = []
    for date, code, high, low, chance, rain in zip(*columns):
        days.append(
            {
                "date": date,
                "weekday": datetime.fromisoformat(date).strftime("%A"),
                "condition": condition(code),
                "max_c": high,
                "min_c": low,
                "rain_chance_percent": chance,
                "rain_mm": rain,
            }
        )
    return days
