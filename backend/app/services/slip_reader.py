"""Read a Thai bank transfer slip with Claude: amount, date/time, both sides' banks and masked account numbers,
and the reference number. One request with a JSON schema; services.personal decides what to record.
"""

import json
import logging

from app.config import get_settings
from app.core import images
from app.core.orchestrator import get_orchestrator

log = logging.getLogger(__name__)

_TEXT = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "is_slip": {"type": "boolean"},
        "amount": {"type": ["number", "null"]},
        "date": _TEXT,
        "time": _TEXT,
        "sender_name": _TEXT,
        "sender_bank": _TEXT,
        "sender_account": _TEXT,
        "receiver_name": _TEXT,
        "receiver_bank": _TEXT,
        "receiver_account": _TEXT,
        "reference": _TEXT,
        "memo": _TEXT,
    },
    "required": [
        "is_slip",
        "amount",
        "date",
        "time",
        "sender_name",
        "sender_bank",
        "sender_account",
        "receiver_name",
        "receiver_bank",
        "receiver_account",
        "reference",
        "memo",
    ],
    "additionalProperties": False,
}

PROMPT = """รูปนี้คือสลิปโอนเงิน/จ่ายเงินของธนาคารไทยหรือไม่ ถ้าใช่ อ่านข้อมูลตามที่พิมพ์ในสลิป:
- is_slip: true ถ้าเป็นสลิปโอนเงิน/จ่ายบิล/เติมเงินที่สำเร็จแล้ว
- amount: จำนวนเงินเป็นบาท (ตัวเลข ไม่มีจุลภาค)
- date: วันที่ทำรายการ รูปแบบ YYYY-MM-DD เป็น ค.ศ. (ถ้าสลิปเป็น พ.ศ. ให้ลบ 543 เช่น 5 ต.ค. 69 = 2026-10-05)
- time: เวลา HH:MM
- sender_* และ receiver_*: ชื่อ ธนาคาร (เช่น กสิกรไทย ไทยพาณิชย์ หรือ พร้อมเพย์/ร้านค้า ถ้าไม่ใช่ธนาคาร) และเลขบัญชีตามที่พิมพ์ รวม x ที่ปิดไว้ เช่น xxx-x-x1234-x
- reference: เลขที่รายการ/เลขอ้างอิงของสลิป
- memo: บันทึกช่วยจำในสลิป ถ้ามี
ช่องที่ไม่มีในสลิปให้เป็น null"""


class SlipReadError(RuntimeError):
    pass


def read_slip(jpeg_b64: str) -> dict:
    """What a slip picture says; {"is_slip": False, ...} when it isn't one. Raises SlipReadError."""
    s = get_settings()
    response = get_orchestrator().client.beta.messages.create(
        model=s.claude_model,
        max_tokens=4000,
        messages=[{"role": "user", "content": [images.block(jpeg_b64), {"type": "text", "text": PROMPT}]}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise SlipReadError("Claude refused to read this picture")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("slip reader returned non-JSON (stop %s): %s", response.stop_reason, text[:200])
        raise SlipReadError("could not read the slip") from e
    return data if isinstance(data, dict) else {"is_slip": False}
