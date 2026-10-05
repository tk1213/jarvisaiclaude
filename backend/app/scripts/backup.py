"""Back up everything JARVIS can't re-create: the code (a git bundle, with the latest from GitHub), backend\\.env,
the databases and the slip pictures of the personal-money page. One folder per day under BACKUP_DIR; the newest BACKUP_KEEP_DAYS stay.

    python -m app.scripts.backup          # back up now (replaces today's folder); backup.bat runs this
    python -m app.scripts.backup --auto   # the daily task: does nothing if today's backup is already done

Databases are copied with SQLite's backup API, so it's safe while start.bat is running.
"""

import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from app.config import get_settings

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
BUNDLE = "jarvis-code.bundle"
README = "อ่านก่อน.txt"
SLIPS = "personal-slips"
DONE = "backup-ok.txt"  # written last: a folder without it is incomplete
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sqlite_path(url: str) -> Path | None:
    """The file behind a sqlite:/// URL (relative paths are relative to backend\\, like start.bat), None otherwise."""
    if not url.startswith("sqlite:///") or url.startswith("sqlite:///:memory:"):
        return None
    path = Path(url.removeprefix("sqlite:///"))
    return path if path.is_absolute() else (BACKEND / path).resolve()


def copy_sqlite(src: Path, dst: Path) -> None:
    source = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # No password prompts (the daily task has nobody to answer them) and no console window on Windows.
    env = os.environ | {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=timeout, env=env, creationflags=flags, check=False)


def bundle_code(dst: Path, notes: list[str]) -> str:
    """The whole repository with its history in one file; returns the commit it's at."""
    if shutil.which("git") is None:
        raise RuntimeError("ไม่พบโปรแกรม git")
    try:
        fetched = _git("fetch", "origin", "--quiet")
        if fetched.returncode != 0:
            notes.append(f"ดึงโค้ดล่าสุดจาก GitHub ไม่ได้ ใช้โค้ดในเครื่องแทน ({fetched.stderr.strip()[:200]})")
    except subprocess.TimeoutExpired:
        notes.append("ดึงโค้ดล่าสุดจาก GitHub ไม่ทันเวลา ใช้โค้ดในเครื่องแทน")
    made = _git("bundle", "create", str(dst), "--all")
    if made.returncode != 0:
        raise RuntimeError(made.stderr.strip()[:300] or "git bundle failed")
    head = _git("log", "-1", "--format=%h %cd %s", "--date=format:%Y-%m-%d", "origin/main")
    if head.returncode != 0:
        head = _git("log", "-1", "--format=%h %cd %s", "--date=format:%Y-%m-%d")
    return head.stdout.strip()


def backup(root: Path, keep: int, auto: bool = False, today: date | None = None) -> tuple[Path | None, list[str]]:
    """Make today's backup folder. Returns (folder, problems); folder is None when --auto found it already done."""
    day = (today or date.today()).isoformat()
    target = root / day
    if auto and (target / DONE).exists():
        return None, []
    root.mkdir(parents=True, exist_ok=True)
    work = root / f".{day}.partial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    s = get_settings()
    problems: list[str] = []
    notes: list[str] = []
    places: list[tuple[str, Path]] = []  # (file in the backup, where it goes back to)

    env = BACKEND / ".env"
    if env.exists():
        shutil.copy2(env, work / ".env")
        places.append((".env", env))
    else:
        problems.append(f"ไม่พบ {env}")

    databases = (
        ("jarvis.db", s.database_url),
        ("catalog.db", s.catalog_database_url),
        ("account.db", s.account_database_url),
        ("personal.db", s.personal_database_url),
    )
    for name, url in databases:
        path = sqlite_path(url)
        if path is None:
            notes.append(f"{name}: ฐานข้อมูลไม่ใช่ SQLite ({url.split(':', 1)[0]}) ต้องสำรองด้วยเครื่องมือของฐานข้อมูลนั้นเอง")
        elif not path.exists():
            notes.append(f"{name}: ยังไม่มีไฟล์ {path}")
        else:
            try:
                copy_sqlite(path, work / name)
                places.append((name, path))
            except sqlite3.Error as e:
                problems.append(f"สำรอง {name} ไม่ได้: {e}")

    slips = Path(s.personal_slip_dir)
    slips = slips if slips.is_absolute() else (BACKEND / slips).resolve()
    if slips.is_dir():
        try:
            shutil.copytree(slips, work / SLIPS)
            places.append((SLIPS, slips))
        except OSError as e:
            problems.append(f"สำรองรูปสลิปไม่ได้: {e}")

    commit = ""
    try:
        commit = bundle_code(work / BUNDLE, notes)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        problems.append(f"สำรองโค้ดไม่ได้: {e}")

    (work / README).write_text(_readme(day, commit, places, notes + problems), encoding="utf-8-sig")
    if not problems:
        (work / DONE).write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    work.rename(target)
    prune(root, keep)
    return target, problems


def prune(root: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` day folders (only folders this script made)."""
    days = sorted((p for p in root.iterdir() if p.is_dir() and DAY.match(p.name) and (p / README).exists()), key=lambda p: p.name)
    old = days[: max(0, len(days) - max(keep, 1))]
    for p in old:
        shutil.rmtree(p, ignore_errors=True)
    for p in root.glob(".*.partial"):  # left over from a run that was cut off
        shutil.rmtree(p, ignore_errors=True)
    return old


def _readme(day: str, commit: str, places: list[tuple[str, Path]], remarks: list[str]) -> str:
    lines = [
        f"สำรองข้อมูล JARVIS วันที่ {day} เวลา {datetime.now():%H:%M}",
        "",
        "ไฟล์ในโฟลเดอร์นี้",
        f"- {BUNDLE}  โค้ดทั้งหมดพร้อมประวัติ" + (f" (ล่าสุดบน GitHub: {commit})" if commit else ""),
        "- .env        คีย์ลับทั้งหมด ห้ามส่งให้ใครหรือส่งทาง LINE/อีเมล",
        "- jarvis.db   ข้อมูลหลัก: ผู้ใช้ การเชื่อม LINE อุปกรณ์ ลูกค้า ประวัติเอกสารและแชท",
        "- catalog.db  สินค้าและชุดสินค้า FlowAccount (ชุด A/B/C หมายเหตุ ราคาพิเศษ)",
        "- account.db  บัญชีรายรับ-รายจ่ายของหน้า Account (สำหรับสรุปภาษี)",
        "- personal.db การเงินส่วนตัว: บัญชีธนาคาร รายรับ รายจ่าย",
        f"- {SLIPS}  รูปสลิปจากกลุ่ม LINE สลิปรายรับ/สลิปรายจ่าย (ทั้งโฟลเดอร์)",
        "",
    ]
    if remarks:
        lines += ["หมายเหตุจากการสำรองครั้งนี้", *[f"- {r}" for r in remarks], ""]
    lines += [
        "กู้คืนแค่ข้อมูล (เครื่องเดิม ไฟล์เสียหรือลบไปโดยไม่ตั้งใจ)",
        "1. ปิด start.bat",
        "2. ก๊อปไฟล์จากโฟลเดอร์นี้ไปทับที่เดิม:",
        *[f"   {name}  ->  {path}" for name, path in places],
        "3. เปิด start.bat",
        "",
        "ย้ายไปเครื่องใหม่",
        "1. ลง Python 3.14, Node.js และ Git",
        "2. เปิด PowerShell แล้วพิมพ์ (แก้ <โฟลเดอร์นี้> เป็นที่อยู่ของโฟลเดอร์สำรองนี้):",
        "   cd D:\\Claude",
        f'   git clone "<โฟลเดอร์นี้>\\{BUNDLE}" jarvisclaude',
        "   cd jarvisclaude",
        "   git checkout main",
        "   git remote set-url origin https://github.com/tk1213/jarvisaiclaude.git",
        "   git pull                 (ถ้าเข้า GitHub ได้ จะได้โค้ดล่าสุด)",
        "   cd backend",
        "   py -3.14 -m venv .venv",
        "   .venv\\Scripts\\activate",
        '   pip install -e ".[dev]"',
        "   cd ..\\frontend",
        "   npm install",
        "   npm run build",
        f"3. ก๊อป .env, jarvis.db, catalog.db, account.db, personal.db และโฟลเดอร์ {SLIPS} ไปไว้ที่เดียวกับข้อ 2 ของ \"กู้คืนแค่ข้อมูล\" ด้านบน",
        "   (ถ้าโฟลเดอร์ใหม่ไม่ใช่ D:\\Claude\\jarvisclaude ให้วางในโฟลเดอร์ backend ของที่ใหม่แทน)",
        "   (catalog.db อยู่ใน backend\\data\\flowaccount, account.db อยู่ใน backend\\data\\account,",
        "    personal.db อยู่ใน backend\\data\\personal และรูปสลิปคือ backend\\data\\personal\\slips ถ้ายังไม่มีโฟลเดอร์ให้สร้างก่อน)",
        "4. ย้าย Cloudflare tunnel: เครื่องเก่ารัน cloudflared.exe service uninstall (Run as Administrator)",
        "   เครื่องใหม่รันคำสั่ง cloudflared.exe service install <token> จากหน้า Tunnels ใน Cloudflare Zero Trust",
        "5. ดับเบิลคลิก start.bat แล้วดับเบิลคลิก backup-schedule.bat เพื่อตั้งสำรองอัตโนมัติบนเครื่องใหม่",
        "",
    ]
    return "\r\n".join(lines)


def log(root: Path, text: str) -> None:
    print(text)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with open(root / "backup.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    s = get_settings()
    root = Path(s.backup_dir)
    auto = "--auto" in argv
    try:
        folder, problems = backup(root, s.backup_keep_days, auto=auto)
    except Exception as e:  # the daily task runs unseen: always leave a line in backup.log
        log(root, f"FAILED {e.__class__.__name__}: {e}")
        return 1
    if folder is None:
        log(root, "today's backup is already done")
        return 0
    if problems:
        log(root, f"INCOMPLETE {folder}: " + " / ".join(problems))
        return 1
    log(root, f"OK {folder} (keeping the newest {s.backup_keep_days} days)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
