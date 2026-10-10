"""How the JARVIS server is doing, for "สถานะระบบ" on LINE and the get_system_status tool: uptime, CPU, memory,
disk, CPU temperature, Tuya, Claude, the last backup and the code version. Reads Linux's /proc and /sys (the mini
PC); anything a machine doesn't offer (e.g. Windows) is left out rather than guessed.
"""

import glob
import re
import shutil
import subprocess
import time
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Device

STARTED = time.time()
REPO = Path(__file__).resolve().parents[3]
STATUS_WORDS = {"สถานะระบบ", "เช็คระบบ", "เช็กระบบ", "สถานะเซิร์ฟเวอร์", "server", "status"}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BACKUP_README = "อ่านก่อน.txt"

# Past these, the reply flags a problem.
DISK_FREE_MIN = 0.10
MEMORY_FREE_MIN = 0.10
HOT_C = 80


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


def machine_uptime() -> float | None:
    text = _read("/proc/uptime")
    return float(text.split()[0]) if text else None


def memory() -> tuple[int, int] | None:
    """(available, total) bytes."""
    text = _read("/proc/meminfo")
    if not text:
        return None
    values = {k: int(v.split()[0]) * 1024 for k, v in (line.split(":", 1) for line in text.splitlines() if ":" in line)}
    if "MemTotal" not in values or "MemAvailable" not in values:
        return None
    return values["MemAvailable"], values["MemTotal"]


def _cpu_times() -> tuple[int, int] | None:
    text = _read("/proc/stat")
    if not text:
        return None
    fields = [int(x) for x in text.splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return idle, sum(fields)


def cpu_percent(sample: float = 0.3) -> float | None:
    first = _cpu_times()
    if first is None:
        return None
    time.sleep(sample)
    second = _cpu_times()
    total = second[1] - first[1]
    return round(100 * (1 - (second[0] - first[0]) / total), 0) if total > 0 else None


def cpu_temperature() -> float | None:
    temps = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        text = _read(path)
        if text and text.strip().lstrip("-").isdigit():
            c = int(text) / 1000
            if 0 < c < 125:
                temps.append(c)
    return round(max(temps), 0) if temps else None


def disk() -> tuple[int, int] | None:
    """(free, total) bytes of the disk JARVIS's data lives on."""
    try:
        usage = shutil.disk_usage(REPO)
    except OSError:
        return None
    return usage.free, usage.total


@lru_cache
def code_version() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%h %cs"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def last_backup() -> date | None:
    root = Path(get_settings().backup_dir).expanduser()
    try:
        days = [p.name for p in root.iterdir() if p.is_dir() and _DAY.match(p.name) and (p / _BACKUP_README).exists()]
    except OSError:
        return None
    return date.fromisoformat(max(days)) if days else None


def collect(db: Session) -> dict:
    """Everything the status reply needs, as plain data (also what the get_system_status tool returns)."""
    from app.core import orchestrator  # imported here: the orchestrator imports the tools, which import this
    from app.integrations.tuya import pulsar

    s = get_settings()
    total = db.scalar(select(func.count()).select_from(Device)) or 0
    online = db.scalar(select(func.count()).select_from(Device).where(Device.online.is_(True))) or 0
    mem, space = memory(), disk()
    backup = last_backup()
    return {
        "jarvis_uptime_seconds": round(time.time() - STARTED),
        "machine_uptime_seconds": machine_uptime(),
        "cpu_percent": cpu_percent(),
        "cpu_temperature_c": cpu_temperature(),
        "memory_available_bytes": mem[0] if mem else None,
        "memory_total_bytes": mem[1] if mem else None,
        "disk_free_bytes": space[0] if space else None,
        "disk_total_bytes": space[1] if space else None,
        "tuya_mode": s.tuya_mode,
        "tuya_realtime_connected": pulsar.is_connected() if s.tuya_mode == "live" and s.tuya_pulsar_enabled else None,
        "devices_online": online,
        "devices_total": total,
        "claude_last_ok": orchestrator.claude_status["ok_at"],
        "claude_last_error": orchestrator.claude_status["error"],
        "claude_last_error_at": orchestrator.claude_status["error_at"],
        "last_backup": backup.isoformat() if backup else None,
        "code_version": code_version(),
    }


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} วัน {hours} ชม."
    if hours:
        return f"{hours} ชม. {minutes} นาที"
    return f"{minutes} นาที"


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f}"


def _clock(at: datetime | None) -> str:
    return at.astimezone(ZoneInfo(get_settings().timezone)).strftime("%d/%m %H:%M") if at else "-"


def report(db: Session) -> str:
    """The Thai reply to "สถานะระบบ": a ✅ or ⚠️ headline, then one line per part."""
    st = collect(db)
    problems: list[str] = []
    lines: list[str] = []

    up = f"• จาร์วิสทำงานมา {_duration(st['jarvis_uptime_seconds'])}"
    if st["machine_uptime_seconds"] is not None:
        up += f" (เครื่องเปิดมา {_duration(st['machine_uptime_seconds'])})"
    lines.append(up)

    parts = []
    if st["cpu_percent"] is not None:
        parts.append(f"CPU {st['cpu_percent']:.0f}%")
    if st["memory_total_bytes"]:
        used = st["memory_total_bytes"] - st["memory_available_bytes"]
        parts.append(f"RAM {_gb(used)}/{_gb(st['memory_total_bytes'])} GB")
        if st["memory_available_bytes"] / st["memory_total_bytes"] < MEMORY_FREE_MIN:
            problems.append("RAM ใกล้เต็ม")
    if st["disk_total_bytes"]:
        parts.append(f"ดิสก์ว่าง {_gb(st['disk_free_bytes'])} GB")
        if st["disk_free_bytes"] / st["disk_total_bytes"] < DISK_FREE_MIN:
            problems.append("ดิสก์ใกล้เต็ม")
    if st["cpu_temperature_c"] is not None:
        parts.append(f"อุณหภูมิ CPU {st['cpu_temperature_c']:.0f} °C")
        if st["cpu_temperature_c"] >= HOT_C:
            problems.append("เครื่องร้อนเกินไป")
    if parts:
        lines.append("• " + " · ".join(parts))

    tuya = "Tuya: โหมดทดสอบ (mock)" if st["tuya_mode"] == "mock" else "Tuya: เชื่อมต่อ ✓"
    if st["tuya_realtime_connected"] is not None:
        tuya += " · แจ้งเตือนสด ✓" if st["tuya_realtime_connected"] else " · แจ้งเตือนสด ✗"
        if not st["tuya_realtime_connected"]:
            problems.append("Tuya แจ้งเตือนสดหลุด")
    lines.append(f"• {tuya} · อุปกรณ์ออนไลน์ {st['devices_online']}/{st['devices_total']}")

    ok_at, err_at = st["claude_last_ok"], st["claude_last_error_at"]
    if err_at and (ok_at is None or err_at > ok_at):
        lines.append(f"• Claude: error ล่าสุด {_clock(err_at)} ✗ {st['claude_last_error']}")
        problems.append("Claude ตอบไม่ได้")
    elif ok_at:
        lines.append(f"• Claude: ตอบล่าสุด {_clock(ok_at)} ✓")
    else:
        lines.append("• Claude: ยังไม่มีการเรียกตั้งแต่เปิดระบบ")

    backup = st["last_backup"]
    if backup is None:
        lines.append("• สำรองข้อมูล: ยังไม่พบ ⚠️")
        problems.append("ไม่พบไฟล์สำรอง")
    else:
        age = (datetime.now(ZoneInfo(get_settings().timezone)).date() - date.fromisoformat(backup)).days
        lines.append(f"• สำรองข้อมูลล่าสุด: {date.fromisoformat(backup):%d/%m/%Y}" + (" ⚠️" if age > 1 else ""))
        if age > 1:
            problems.append(f"ไม่ได้สำรองข้อมูลมา {age} วัน")

    if st["code_version"]:
        lines.append(f"• โค้ดเวอร์ชัน: {st['code_version']}")

    head = "ระบบปกติค่ะ TK ✅" if not problems else f"⚠️ มีเรื่องต้องดูค่ะ TK: {', '.join(problems)}"
    return "\n".join([head, *lines])
