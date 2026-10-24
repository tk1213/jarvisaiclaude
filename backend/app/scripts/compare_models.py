"""Check a cheaper Claude model's accuracy against Opus 5.5 before (or after) switching to it, with real API calls.

    python -m app.scripts.compare_models                  # 20 recent slips + 8 chat commands, Haiku 5.5 vs Opus 5.5
    python -m app.scripts.compare_models --slips 40       # more slips
    python -m app.scripts.compare_models --model claude-sonnet-5-5

Slips: the pictures JARVIS already saved (personal and company money) are read again by both models and compared with
what was recorded (amount, date, reference), which the owner has already checked, and with each other.
Chat: sample commands run against the mock home (TUYA_MODE=mock in a throwaway database), so no Tuya quota is used and
no real device moves; both models' tool calls and replies are compared. Costs a few baht in Claude tokens.
"""

import argparse
import base64
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

PRICES = {  # USD per million tokens: input, output, cache read, cache write (5 min)
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}
REFERENCE = "claude-opus-5-5"
THB_PER_USD = 35
COMMANDS = [
    "เปิดปลั๊กกาต้มน้ำ",
    "ปิดไฟห้องนั่งเล่น",
    "ห้องทำงานอุณหภูมิกี่องศา",
    "ตั้งแอร์ห้องทำงาน 24 องศา โหมดเย็น",
    "มีอะไรเปิดอยู่บ้าง",
    "เปิดแอร์ห้องนอนแล้วตั้ง 26 องศา",
    "ปิดทุกอย่างให้หน่อย",
    "สวัสดีจาร์วิส",
]
FIELDS = ("amount", "date", "time", "sender_bank", "sender_account", "receiver_bank", "receiver_account", "reference")


class Meter:
    """Wraps the Anthropic client to add up token usage (and so cost) per model."""

    def __init__(self, client):
        self._client = client
        self.usage: dict[str, list[int]] = {}
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        response = self._client.beta.messages.create(**kwargs)
        u = response.usage
        row = self.usage.setdefault(kwargs["model"], [0, 0, 0, 0])
        for i, value in enumerate((u.input_tokens, u.output_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens)):
            row[i] += value or 0
        return response

    def baht(self, model: str) -> float:
        row = self.usage.get(model, [0, 0, 0, 0])
        price = PRICES.get(model, PRICES[REFERENCE])
        return sum(n * p for n, p in zip(row, price)) / 1_000_000 * THB_PER_USD


def _norm(field: str, value) -> str:
    if value is None:
        return ""
    if field == "amount":
        try:
            return f"{float(str(value).replace(',', '')):.2f}"
        except ValueError:
            return str(value)
    if field.endswith("_account"):
        return re.sub(r"[^0-9xX]", "", str(value)).lower()
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _slip_rows(db_path: Path, limit: int) -> list[dict]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT amount_satang, entry_date, ref_no, slip_file FROM personal_entries WHERE slip_file != '' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def compare_slips(meter: Meter, model: str, limit: int, db_paths: list[Path], slip_dir: Path) -> None:
    from app.services.slip_reader import SlipReadError, read_slip_with

    rows = [r for p in db_paths for r in _slip_rows(p, limit)][:limit]
    print(f"\n=== สลิป: {model} เทียบกับ {REFERENCE} ({len(rows)} ใบ) ===")
    if not rows:
        print("ยังไม่มีรูปสลิปที่บันทึกไว้ ข้ามส่วนนี้")
        return
    recorded_ok = {model: 0, REFERENCE: 0}
    same = {f: 0 for f in FIELDS}
    for n, row in enumerate(rows, 1):
        picture = slip_dir / row["slip_file"]
        if not picture.is_file():
            continue
        b64 = base64.b64encode(picture.read_bytes()).decode()
        read = {}
        for m in (model, REFERENCE):
            try:
                read[m] = read_slip_with(meter, m, b64)
            except SlipReadError as e:
                read[m] = {"error": str(e)}
        truth = (f"{row['amount_satang'] / 100:.2f}", str(row["entry_date"]), _norm("reference", row["ref_no"]))
        for m in (model, REFERENCE):
            got = (_norm("amount", read[m].get("amount")), str(read[m].get("date") or ""), _norm("reference", read[m].get("reference")))
            ok = got[0] == truth[0] and got[1] == truth[1] and (not truth[2] or got[2] == truth[2])
            recorded_ok[m] += ok
        diffs = [f for f in FIELDS if _norm(f, read[model].get(f)) != _norm(f, read[REFERENCE].get(f))]
        for f in FIELDS:
            same[f] += f not in diffs
        mark = "✓" if not diffs else "✗ ต่างกันที่ " + ", ".join(diffs)
        print(f"{n:3}. {row['slip_file']}  {mark}")
        for f in diffs:
            print(f"       {f}: {model}={read[model].get(f)!r}  {REFERENCE}={read[REFERENCE].get(f)!r}")
    total = len(rows)
    print(f"\nตรงกับที่บันทึกไว้ (ยอด + วันที่ + เลขอ้างอิง): {model} {recorded_ok[model]}/{total}, {REFERENCE} {recorded_ok[REFERENCE]}/{total}")
    print("ตรงกับ Opus รายช่อง: " + ", ".join(f"{f} {same[f]}/{total}" for f in FIELDS))


def compare_chat(meter: Meter, model: str) -> None:
    from app.config import get_settings
    from app.core.messages import Channel, InboundMessage
    from app.core.orchestrator import Orchestrator
    from app.db import SessionLocal, init_db
    from app.integrations.tuya import get_tuya_client
    from app.models import User
    from app.services.devices import sync_devices

    init_db()
    s = get_settings()
    print(f"\n=== แชท (บ้านจำลอง): {model} เทียบกับ {REFERENCE} ===")
    results: dict[str, list] = {}
    for m in (model, REFERENCE):
        with SessionLocal() as db:
            tuya = get_tuya_client()
            tuya.__init__()  # a fresh mock home for each model
            sync_devices(db, tuya)
            user = db.query(User).filter_by(username="compare").first() or User(username="compare", password_hash="x", is_admin=True)
            db.add(user)
            db.commit()
            orch = Orchestrator(meter, model=m, effort=s.claude_effort, max_tool_rounds=s.claude_max_tool_rounds, timezone=s.timezone)
            for command in COMMANDS:
                reply = orch.handle(db, tuya, user, InboundMessage(user_id=user.id, channel=Channel.dashboard, text=command))
                calls = [(c.name, json.dumps(c.input, ensure_ascii=False, sort_keys=True)) for c in reply.tool_calls if c.name not in ("get_devices", "get_device_status")]
                results.setdefault(command, []).append((reply.text, calls))
    agree = 0
    for command in COMMANDS:
        (text_m, calls_m), (text_r, calls_r) = results[command]
        same = sorted(calls_m) == sorted(calls_r)
        agree += same
        print(f"\n• {command}   {'✓ สั่งงานเหมือนกัน' if same else '✗ สั่งงานต่างกัน'}")
        print(f"   {model}: {text_m}")
        print(f"   {REFERENCE}: {text_r}")
        if not same:
            print(f"   เครื่องมือ {model}: {calls_m}\n   เครื่องมือ {REFERENCE}: {calls_r}")
        if not text_m.rstrip().endswith(("ค่ะ TK", "คะ TK")):
            print(f"   ⚠️ {model} ไม่ได้ลงท้าย ค่ะ TK")
    print(f"\nสั่งงานเหมือน Opus: {agree}/{len(COMMANDS)} คำสั่ง")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="claude-haiku-5-5")
    parser.add_argument("--slips", type=int, default=20)
    parser.add_argument("--no-chat", action="store_true")
    args = parser.parse_args(argv)

    from app.config import get_settings

    real = get_settings()
    if not real.anthropic_api_key:
        print("ยังไม่ได้ตั้ง ANTHROPIC_API_KEY ใน backend/.env")
        return 1
    backend = Path(__file__).resolve().parents[2]

    def path_of(url: str) -> Path:
        p = Path(url.removeprefix("sqlite:///"))
        return p if p.is_absolute() else backend / p

    slip_dbs = [path_of(real.personal_database_url), path_of(real.company_database_url)]
    slip_dir = Path(real.personal_slip_dir)
    slip_dir = slip_dir if slip_dir.is_absolute() else backend / slip_dir

    # Everything below runs on throwaway databases and the mock home: no Tuya quota, nothing real changes.
    tmp = tempfile.mkdtemp(prefix="jarvis-compare-")
    for key in ("DATABASE_URL", "CATALOG_DATABASE_URL", "ACCOUNT_DATABASE_URL", "PERSONAL_DATABASE_URL", "COMPANY_DATABASE_URL"):
        os.environ[key] = f"sqlite:///{tmp}/{key.lower()}.db"
    os.environ["TUYA_MODE"] = "mock"
    os.environ["FLOWACCOUNT_MODE"] = "mock"
    get_settings.cache_clear()

    import anthropic

    meter = Meter(anthropic.Anthropic(api_key=real.anthropic_api_key))
    compare_slips(meter, args.model, args.slips, slip_dbs, slip_dir)
    if not args.no_chat:
        compare_chat(meter, args.model)
    print("\n=== ค่าใช้จ่ายของการทดสอบนี้ (โดยประมาณ) ===")
    for m in (args.model, REFERENCE):
        print(f"{m}: {meter.baht(m):.2f} บาท  (tokens in/out/cache-read/cache-write = {meter.usage.get(m, [0, 0, 0, 0])})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
