"""Read a Thai bank transfer slip with Claude: amount, date/time, both sides' banks and masked account numbers,
and the reference number. One request with a JSON schema; services.personal decides what to record.
"""

import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.core import images
from app.core.orchestrator import fallback_options, get_orchestrator
from app.services.personal import SLIP_DAYS_BACK

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

PROMPT = """รูปนี้คือหลักฐานการโอนเงิน/จ่ายเงินของธนาคารไทยหรือไม่ ถ้าใช่ อ่านข้อมูลตามที่พิมพ์ไว้:
- is_slip: true ถ้าเป็นหลักฐานการโอนเงิน/จ่ายบิล/เติมเงินที่สำเร็จแล้ว ทั้งสลิปจากแอปมือถือ และเอกสารเต็มหน้าจากระบบธนาคารธุรกิจ
  เช่น ใบแจ้งการชำระเงิน / Payment Advice / ใบยืนยันการโอนเงิน / Transfer Confirmation (SCB Business Net, K-BIZ, Krungthai Corporate ฯลฯ)
- amount: จำนวนเงินที่โอนเป็นบาท (ตัวเลข ไม่มีจุลภาค) ถ้ามีหลายช่องให้ใช้ยอดสุทธิที่จ่ายจริง เช่น "จำนวนเงินรวมทั้งสิ้น / Grand Total Amount"
  หรือ "Net Amount" ไม่ใช่ค่าธรรมเนียมหรือภาษี
- date: วันที่ทำรายการ รูปแบบ YYYY-MM-DD เป็น ค.ศ. (ถ้าสลิปเป็น พ.ศ. ให้ลบ 543 เช่น 5 ต.ค. 69 = 2026-10-05)
  เดือนไทย: ม.ค.=01 ก.พ.=02 มี.ค.=03 เม.ย.=04 พ.ค.=05 มิ.ย.=06 ก.ค.=07 ส.ค.=08 ก.ย.=09 ต.ค.=10 พ.ย.=11 ธ.ค.=12
  (เช่น 6 พ.ย. 69 09:24 น. = 2026-11-06) อ่านเดือนจากชื่อเดือนเท่านั้น ห้ามเอาตัวเลขของเวลามาเป็นวันหรือเดือน
- time: เวลา HH:MM
- sender_* และ receiver_*: ชื่อ ธนาคาร (เช่น กสิกรไทย ไทยพาณิชย์ หรือ พร้อมเพย์/ร้านค้า ถ้าไม่ใช่ธนาคาร) และเลขบัญชีตามที่พิมพ์ รวม x ที่ปิดไว้ เช่น xxx-x-x1234-x
- reference: เลขที่รายการ/เลขอ้างอิงของสลิป (ในใบแจ้งการชำระเงินคือ เลขที่อ้างอิงธนาคาร / Bank Reference หรือ Transaction Reference)
- memo: บันทึกช่วยจำในสลิป ถ้ามี
ช่องที่ไม่มีในสลิปให้เป็น null"""


class SlipReadError(RuntimeError):
    pass


def date_doubt(slip: dict, today: date | None = None) -> str | None:
    """Why the date read off a slip looks wrong (missing, in the future, or more than SLIP_DAYS_BACK days old); None
    when it looks right."""
    today = today or datetime.now(ZoneInfo(get_settings().timezone)).date()
    try:
        when = date.fromisoformat(slip.get("date") or "")
    except ValueError:
        return "no date"
    if when > today + timedelta(days=1):
        return f"date {when} is in the future"
    if when < today - timedelta(days=SLIP_DAYS_BACK):
        return f"date {when} is over {SLIP_DAYS_BACK} days old"
    return None


def _doubt(slip: dict, check: Callable[[dict], str | None] | None) -> str | None:
    if not slip.get("is_slip") or not slip.get("amount"):
        return "not a slip, or no amount"
    return date_doubt(slip) or (check(slip) if check else None)


def _log_read(model: str, slip: dict) -> None:
    log.info(
        "slip read by %s: amount=%s date=%s time=%s sender=%s %s receiver=%s %s ref=%s",
        model,
        *(slip.get(k) for k in ("amount", "date", "time", "sender_bank", "sender_account", "receiver_bank", "receiver_account", "reference")),
    )


def read_slip(jpeg_b64: str, check: Callable[[dict], str | None] | None = None) -> dict:
    """What a slip picture says; {"is_slip": False, ...} when it isn't one. Raises SlipReadError. When the slip model's
    read looks wrong (not a slip, no amount, an unlikely date, or whatever `check` objects to, e.g. no account of
    this book fits), the retry model reads it again, so only hard pictures cost more. Its read is kept when it has
    fewer doubts."""
    s = get_settings()
    client = get_orchestrator().client
    slip = read_slip_with(client, s.claude_slip_model, jpeg_b64)
    _log_read(s.claude_slip_model, slip)
    doubt = _doubt(slip, check)
    retry = s.claude_slip_retry_model
    if doubt and retry and retry != s.claude_slip_model:
        log.info("slip model %s: %s; reading again with %s", s.claude_slip_model, doubt, retry)
        try:
            again = read_slip_with(client, retry, jpeg_b64)
        except SlipReadError as e:
            log.warning("retry model could not read the slip either: %s", e)
            return slip
        _log_read(retry, again)
        if again.get("is_slip") and again.get("amount"):
            return again
    return slip


def read_slip_with(client, model: str, jpeg_b64: str) -> dict:
    """read_slip on a given model (also used by app.scripts.compare_models to check a cheaper model's accuracy)."""
    fallback = fallback_options(model)
    response = client.beta.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": [images.block(jpeg_b64), {"type": "text", "text": PROMPT}]}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        **({"betas": fallback["betas"], "fallbacks": fallback["fallbacks"]} if fallback else {}),
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
