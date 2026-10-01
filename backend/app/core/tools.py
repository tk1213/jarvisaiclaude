"""home_control.* and flowaccount.* tools exposed to Claude (spec §4.1-4.3).

Each tool is a JSON schema for the API plus a handler that runs with the
caller's database session, Tuya client and user, so permissions and rate
limits apply exactly as they do on the REST API.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations import line as line_api
from app.integrations.flowaccount import FlowAccountError
from app.integrations.tuya import TuyaError, pulsar
from app.models import Device, User
from app.ratelimit import limiter
from app.services import devices as svc
from app.services import catalog
from app.services import documents as docs


log = logging.getLogger(__name__)


class ToolError(Exception):
    """A failure Claude should see and explain, returned as an is_error tool_result."""


@dataclass
class ToolContext:
    db: Session
    tuya: Any
    user: User
    channel: str = "dashboard"
    # When the user's current message arrived: a document may only be issued from a draft made before it.
    turn_started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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


def find_customers(ctx: ToolContext, query: str) -> Any:
    return [
        {"name": c.name, "tax_id": c.tax_id, "address": c.address, "email": c.email, "phone": c.phone}
        for c in docs.find_customers(ctx.db, query)
    ]


def prepare_document(
    ctx: ToolContext,
    doc_type: str,
    customer: dict,
    items: list[dict],
    vat: bool,
    vat_inclusive: bool,
    credit_days: int,
    remarks: str | None,
) -> Any:
    today = datetime.now(ZoneInfo(get_settings().timezone)).date()
    doc = docs.prepare(ctx.db, ctx.user, ctx.channel, doc_type, customer, items, vat, vat_inclusive, credit_days, remarks or "", today)
    return docs.summary(doc)


def issue_document(ctx: ToolContext, draft_id: int) -> Any:
    return docs.summary(docs.issue(ctx.db, ctx.user, draft_id, ctx.turn_started))


def list_documents(ctx: ToolContext, limit: int) -> Any:
    return [
        {"draft_id": d.id, "document": docs.DOC_NAMES.get(d.doc_type, d.doc_type), "status": d.status, "serial": d.document_serial,
         "customer": (d.payload.get("customer") or {}).get("name"), "grand_total": d.total_amount, "created_at": d.created_at.isoformat()}
        for d in docs.recent(ctx.db, ctx.user, max(1, min(limit, 20)))
    ]


def send_to_line(ctx: ToolContext, text: str, links: list[dict] | None, location: dict | None, image_url: str | None) -> Any:
    if not line_api.line_configured():
        raise ToolError("ยังไม่ได้ตั้งค่า LINE OA")
    if not ctx.user.line_user_id:
        raise ToolError("บัญชีนี้ยังไม่ได้เชื่อม LINE ให้กดปุ่ม LINE บน Dashboard เพื่อเชื่อมก่อน")
    messages = line_api.info_messages(text, links, location, image_url)
    try:
        line_api.get_line_client().push(ctx.user.line_user_id, messages)
    except line_api.LineError as e:
        raise ToolError(f"ส่งเข้า LINE ไม่สำเร็จ: {e}") from None
    return {"sent": [m["type"] for m in messages]}


def find_products(ctx: ToolContext, query: str) -> Any:
    found = catalog.find_products(ctx.db, query)
    if not found:
        return {"products": [], "note": "ไม่พบในรายการสินค้า (กด 'อัปเดตสินค้า' บน Dashboard ถ้าเพิ่งเพิ่มใน FlowAccount)"}
    return {"products": [catalog.product_summary(p) for p in found]}


def save_product_set(ctx: ToolContext, name: str, items: list[dict], customer: str | None = None, remarks: str | None = None) -> Any:
    product_set = catalog.save_set(ctx.db, name, items, customer, remarks)
    saved = next(s for s in catalog.list_sets(ctx.db) if s["id"] == product_set.id)
    unknown = [i["product"] for i in saved["items"] if not catalog.find_products(ctx.db, i["product"])]
    return {**saved, "not_in_product_list": unknown}


def set_product_set_remarks(ctx: ToolContext, name: str, remarks: str) -> Any:
    product_set = catalog.set_remarks(ctx.db, name, remarks)
    return {"set": product_set.name, "remarks": product_set.remarks}


def get_product_set(ctx: ToolContext, name: str, times: float) -> Any:
    return catalog.expand_set(ctx.db, name, times or 1)


def list_product_sets(ctx: ToolContext) -> Any:
    return catalog.list_sets(ctx.db)


def delete_product_set(ctx: ToolContext, name: str) -> Any:
    catalog.delete_set(ctx.db, name)
    return {"deleted": name}


def last_order(ctx: ToolContext, customer: str) -> Any:
    return catalog.last_order(ctx.db, customer)


_NULLABLE_STR = {"type": ["string", "null"]}

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
    {
        "name": "send_to_line",
        "description": (
            "Push information to the user's own LINE chat (their linked account), e.g. when they say "
            "\"ส่งเข้าไลน์\". text: the content to keep (news summary, gold prices...) with sources' dates. "
            "links: source pages. location: a place, sent as a Google Maps link; give latitude/longitude only when "
            "you are sure of them (else null and the link searches by name/address). image_url: a direct https link to a "
            "JPEG/PNG file (not a web page), or null. Pushes count toward the LINE OA's monthly message quota."
        ),
        # Not strict: the API allows at most 16 nullable/union parameters across strict tools, and
        # services.documents / integrations.line validate this input themselves.
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "links": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                                "required": ["label", "url"],
                                "additionalProperties": False,
                            },
                        },
                        {"type": "null"},
                    ]
                },
                "location": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "address": {"type": "string"},
                                "latitude": {"type": ["number", "null"]},
                                "longitude": {"type": ["number", "null"]},
                            },
                            "required": ["title", "address", "latitude", "longitude"],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ]
                },
                "image_url": _NULLABLE_STR,
            },
            "required": ["text", "links", "location", "image_url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_products",
        "description": (
            "Search the product list copied from FlowAccount by name or code (tone marks and spaces don't matter). "
            "Use it to get the exact product name, unit and price before preparing a document."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "e.g. 'โช๊ค GUTE 1.5'"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_product_set",
        "description": (
            "Create or replace a named product set (e.g. 'ชุด A') that a customer orders repeatedly. items: product "
            "(use the exact name from find_products when it's in the list), quantity, optional unit_price only for a "
            "special price that should override the list price, optional unit. customer: optional, who the set is for. "
            "remarks: optional หมายเหตุ printed on documents quoted from this set (keep the user's wording)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "customer": {"type": "string"},
                "remarks": {"type": "string"},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "product": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "unit": {"type": "string"},
                        },
                        "required": ["product", "quantity"],
                    },
                },
            },
            "required": ["name", "items"],
        },
    },
    {
        "name": "get_product_set",
        "description": (
            "A saved product set's items with current prices, multiplied by times (how many sets were ordered), "
            "and its remarks. Pass the items to prepare_document and the set's remarks as the document remarks; "
            "if an item has no price, ask the user for it."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "times": {"type": "number", "description": "number of sets, usually 1"}},
            "required": ["name", "times"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_product_set_remarks",
        "description": "Set or change only the หมายเหตุ of a saved product set (empty string clears it); items stay as they are.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "remarks": {"type": "string"}},
            "required": ["name", "remarks"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_product_sets",
        "description": "All saved product sets and what's in them.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "delete_product_set",
        "description": "Delete a saved product set by name (only when the user asks).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "last_order",
        "description": "The items, VAT and credit terms of the newest document for a customer, for 'เหมือนครั้งก่อน'.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"customer": {"type": "string"}},
            "required": ["customer"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_customers",
        "description": "Search customers remembered from earlier documents by name or tax id, to reuse their details.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_document",
        "description": (
            "Step 1 of issuing a FlowAccount document: validates it, computes totals/VAT and saves a DRAFT. "
            "Nothing is sent to FlowAccount. Read the returned summary back to the user and ask them to confirm. "
            "doc_type: quotation (ใบเสนอราคา), billing_note (ใบวางบิล), tax_invoice (ใบกำกับภาษี/ใบแจ้งหนี้), "
            "receipt (ใบเสร็จรับเงิน). vat: add 7% VAT; vat_inclusive: the prices already include VAT. "
            "credit_days: payment term / validity in days (0 = cash)."
        ),
        # Not strict: the API allows at most 16 nullable/union parameters across strict tools, and
        # services.documents / integrations.line validate this input themselves.
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "enum": ["quotation", "billing_note", "tax_invoice", "receipt"]},
                "customer": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "tax_id": _NULLABLE_STR,
                        "address": _NULLABLE_STR,
                        "branch": _NULLABLE_STR,
                        "email": _NULLABLE_STR,
                        "phone": _NULLABLE_STR,
                    },
                    "required": ["name", "tax_id", "address", "branch", "email", "phone"],
                    "additionalProperties": False,
                },
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number", "description": "baht per unit"},
                            "unit": _NULLABLE_STR,
                        },
                        "required": ["name", "quantity", "unit_price", "unit"],
                        "additionalProperties": False,
                    },
                },
                "vat": {"type": "boolean"},
                "vat_inclusive": {"type": "boolean"},
                "credit_days": {"type": "integer"},
                "remarks": _NULLABLE_STR,
            },
            "required": ["doc_type", "customer", "items", "vat", "vat_inclusive", "credit_days", "remarks"],
            "additionalProperties": False,
        },
    },
    {
        "name": "issue_document",
        "description": (
            "Step 2: send a prepared draft to FlowAccount and get its document number. Only call this after the "
            "user has explicitly confirmed the summary in a new message (e.g. \"ยืนยัน\", \"ออกได้เลย\"); "
            "it is refused in the same message that prepared the draft."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "integer"}},
            "required": ["draft_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_documents",
        "description": "The user's most recent documents (drafts and issued), newest first.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "1-20"}},
            "required": ["limit"],
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
    "send_to_line": send_to_line,
    "find_customers": find_customers,
    "find_products": find_products,
    "save_product_set": save_product_set,
    "get_product_set": get_product_set,
    "set_product_set_remarks": set_product_set_remarks,
    "list_product_sets": list_product_sets,
    "delete_product_set": delete_product_set,
    "last_order": last_order,
    "prepare_document": prepare_document,
    "issue_document": issue_document,
    "list_documents": list_documents,
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
    except (docs.DocumentError, catalog.CatalogError) as e:
        return str(e), True
    except FlowAccountError as e:
        return str(e), True
    except line_api.LineError as e:
        return f"ส่งเข้า LINE ไม่สำเร็จ: {e}", True
    except (TypeError, ValueError) as e:
        return f"Invalid input for {name}: {e}", True
    except Exception as e:
        # One broken tool shouldn't fail the whole reply: Claude sees the error and can tell the user.
        log.exception("tool %s failed", name)
        return f"{name} ขัดข้อง: {e.__class__.__name__}: {e}", True
    return json.dumps(result, ensure_ascii=False), False
