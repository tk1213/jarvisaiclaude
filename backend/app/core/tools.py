"""home_control.* tools exposed to Claude (spec §4.1, §4.2).

Each tool is a JSON schema for the API plus a handler that runs with the
caller's database session, Tuya client and user, so permissions and rate
limits apply exactly as they do on the REST API.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.tuya import TuyaError, pulsar
from app.models import Device, User
from app.ratelimit import limiter
from app.services import devices as svc


class ToolError(Exception):
    """A failure Claude should see and explain, returned as an is_error tool_result."""


@dataclass
class ToolContext:
    db: Session
    tuya: Any
    user: User


def _device_summary(d: Device) -> dict:
    return {
        "device_id": d.id,
        "name": d.name,
        "room": d.room,
        "category": d.category,
        "online": d.online,
        "status": d.status,
    }


def _get_device(ctx: ToolContext, device_id: int) -> Device:
    try:
        return svc.get_device(ctx.db, device_id)
    except svc.DeviceNotFound:
        raise ToolError(f"ไม่พบอุปกรณ์ device_id={device_id} ให้เรียก get_devices ดูรายการก่อน") from None


def _require_control(ctx: ToolContext) -> None:
    if not ctx.user.can_control_devices:
        raise ToolError("ผู้ใช้นี้ไม่มีสิทธิ์ควบคุมอุปกรณ์")
    try:
        limiter.hit(f"control:{ctx.user.id}", get_settings().rate_limit_control_per_minute)
    except HTTPException:
        raise ToolError("สั่งงานถี่เกินไป กรุณารอสักครู่แล้วลองใหม่") from None


def get_devices(ctx: ToolContext, room: str | None = None) -> Any:
    # While the Pulsar stream is up the table is already current; refreshing costs a Tuya call per device.
    if not pulsar.is_connected():
        svc.refresh_all_status(ctx.db, ctx.tuya)
    found = svc.find_devices(ctx.db, room=room or None)
    return [_device_summary(d) for d in found]


def get_device_status(ctx: ToolContext, device_id: int) -> Any:
    device = _get_device(ctx, device_id)
    return _device_summary(svc.refresh_status(ctx.db, ctx.tuya, device))


def control_device(ctx: ToolContext, device_id: int, commands: list[dict]) -> Any:
    _require_control(ctx)
    device = _get_device(ctx, device_id)
    if device.category == svc.IR_AC_CATEGORY:
        raise ToolError("อุปกรณ์นี้เป็นแอร์ที่สั่งผ่านรีโมท IR ให้ใช้ control_air_conditioner แทน")
    if not device.online:
        raise ToolError(f"อุปกรณ์ '{device.name}' ออฟไลน์อยู่")
    return _device_summary(svc.control_device(ctx.db, ctx.tuya, device, commands))


def control_air_conditioner(
    ctx: ToolContext,
    device_id: int,
    power: bool | None = None,
    mode: str | None = None,
    temperature: int | None = None,
    fan: str | None = None,
) -> Any:
    _require_control(ctx)
    device = _get_device(ctx, device_id)
    try:
        updated = svc.set_ac(ctx.db, ctx.tuya, device, power=power, mode=mode, temp=temperature, fan=fan)
    except ValueError as e:
        raise ToolError(str(e)) from None
    return _device_summary(updated)


def list_scenes(ctx: ToolContext) -> Any:
    return [{"scene_id": str(s["scene_id"]), "name": s["name"]} for s in ctx.tuya.list_scenes()]


def set_scene(ctx: ToolContext, scene_id: str) -> Any:
    _require_control(ctx)
    ctx.tuya.trigger_scene(scene_id)
    return {"triggered": scene_id}


_VALUE_SCHEMA = {"anyOf": [{"type": "boolean"}, {"type": "number"}, {"type": "string"}]}

TOOLS: list[dict] = [
    {
        "name": "get_devices",
        "description": (
            "List the smart-home devices JARVIS knows about, with id, name, room, online flag and current "
            "status data points. Call this before controlling a device so you use the right device_id and codes."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "room": {
                    "type": ["string", "null"],
                    "description": "Only devices whose room contains this text; null for all devices.",
                }
            },
            "required": ["room"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_device_status",
        "description": "Fetch one device's live status from Tuya Cloud (use when fresh readings matter, e.g. power usage).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"device_id": {"type": "integer"}},
            "required": ["device_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "control_device",
        "description": (
            "Send Tuya data-point commands to a device, e.g. [{\"code\": \"switch_1\", \"value\": true}] to turn a "
            "plug on. Use only codes that appear in the device's status. Returns the device's new status."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "integer"},
                "commands": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {"code": {"type": "string"}, "value": _VALUE_SCHEMA},
                        "required": ["code", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["device_id", "commands"],
            "additionalProperties": False,
        },
    },
    {
        "name": "control_air_conditioner",
        "description": (
            "Control an air conditioner driven by an IR remote (category infrared_ac). Pass only the settings "
            "to change; the rest keep their current values, and changing mode/temperature/fan also turns it on. "
            "Its status shows switch_power, mode (0 cool, 1 heat, 2 auto, 3 fan, 4 dry), temperature (°C) and "
            "fan (0 auto, 1 low, 2 mid, 3 high). IR is one-way, so status is what was last sent."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "integer"},
                "power": {"type": ["boolean", "null"], "description": "true on, false off, null unchanged"},
                "mode": {"anyOf": [{"type": "string", "enum": ["cool", "heat", "auto", "fan", "dry"]}, {"type": "null"}]},
                "temperature": {"type": ["integer", "null"], "description": "16-30 °C"},
                "fan": {"anyOf": [{"type": "string", "enum": ["auto", "low", "mid", "high"]}, {"type": "null"}]},
            },
            "required": ["device_id", "power", "mode", "temperature", "fan"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_scenes",
        "description": "List the Tuya scenes (tap-to-run automations) configured in the home.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "set_scene",
        "description": "Run a Tuya scene by scene_id (get ids from list_scenes).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"scene_id": {"type": "string"}},
            "required": ["scene_id"],
            "additionalProperties": False,
        },
    },
]

_HANDLERS: dict[str, Callable[..., Any]] = {
    "get_devices": get_devices,
    "get_device_status": get_device_status,
    "control_device": control_device,
    "control_air_conditioner": control_air_conditioner,
    "list_scenes": list_scenes,
    "set_scene": set_scene,
}


def run_tool(ctx: ToolContext, name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool call; returns (content for tool_result, is_error)."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", True
    try:
        result = handler(ctx, **tool_input)
    except ToolError as e:
        return str(e), True
    except TuyaError as e:
        return f"Tuya ตอบกลับ error: {e.msg} (code {e.code})", True
    except (TypeError, ValueError) as e:
        return f"Invalid input for {name}: {e}", True
    return json.dumps(result, ensure_ascii=False), False
