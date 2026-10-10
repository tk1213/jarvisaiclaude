import json
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.core import orchestrator
from app.core.tools import ToolContext, run_tool
from app.db import SessionLocal
from app.services import system_status
from tests.test_line import FakeLine, link, post_event, text_event  # noqa: F401
from tests.test_line import line  # noqa: F401


@pytest.fixture
def backups(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    get_settings.cache_clear()
    orchestrator.claude_status.update(ok_at=None, error_at=None, error=None)
    yield tmp_path
    get_settings.cache_clear()


def backup_on(root, day):
    (root / day).mkdir()
    (root / day / "อ่านก่อน.txt").write_text("x")


def today():
    return datetime.now(timezone.utc).astimezone().date().isoformat()


def test_healthy_report(backups):
    backup_on(backups, today())
    orchestrator.claude_status["ok_at"] = datetime.now(timezone.utc)
    with SessionLocal() as db:
        text = system_status.report(db)
    assert text.startswith("ระบบปกติค่ะ TK ✅"), text
    assert "• จาร์วิสทำงานมา " in text
    assert "Tuya: โหมดทดสอบ (mock)" in text
    assert "• Claude: ตอบล่าสุด" in text and "✓" in text
    assert "• สำรองข้อมูลล่าสุด:" in text


def test_problems_are_flagged(backups, monkeypatch):
    backup_on(backups, "2026-01-01")
    orchestrator.claude_status.update(
        ok_at=datetime.now(timezone.utc) - timedelta(hours=1), error_at=datetime.now(timezone.utc), error="Your credit balance is too low"
    )
    monkeypatch.setattr(system_status, "disk", lambda: (1 * 1024**3, 100 * 1024**3))
    monkeypatch.setattr(system_status, "cpu_temperature", lambda: 85.0)
    with SessionLocal() as db:
        text = system_status.report(db)
    head = text.splitlines()[0]
    for problem in ("ดิสก์ใกล้เต็ม", "เครื่องร้อนเกินไป", "Claude ตอบไม่ได้", "ไม่ได้สำรองข้อมูลมา"):
        assert problem in head, head
    assert "credit balance is too low" in text


def test_no_backup_yet(backups):
    with SessionLocal() as db:
        assert "ไม่พบไฟล์สำรอง" in system_status.report(db)


def test_durations():
    assert system_status._duration(35 * 60) == "35 นาที"
    assert system_status._duration(5 * 3600 + 120) == "5 ชม. 2 นาที"
    assert system_status._duration(2 * 86400 + 5 * 3600) == "2 วัน 5 ชม."


def test_tool_returns_plain_json(backups):
    orchestrator.claude_status["ok_at"] = datetime.now(timezone.utc)
    with SessionLocal() as db:
        out, err = run_tool(ToolContext(db=db, tuya=None, user=None), "get_system_status", {})
    data = json.loads(out)
    assert not err and data["tuya_mode"] == "mock" and data["claude_last_ok"].endswith("+00:00")


def test_line_status_word_answers_without_claude(client, owner_headers, line, backups, monkeypatch):  # noqa: F811
    monkeypatch.setattr(orchestrator, "_orchestrator", None)  # Claude isn't even configured
    monkeypatch.setattr(orchestrator, "get_orchestrator", lambda: pytest.fail("Claude was called"))
    link(client, owner_headers, line)
    post_event(client, text_event("สถานะระบบ"))
    assert line.sent[-1][2][0]["text"].splitlines()[0].startswith(("ระบบปกติ", "⚠️"))
    post_event(client, text_event("Server"))
    assert "จาร์วิสทำงานมา" in line.sent[-1][2][0]["text"]
