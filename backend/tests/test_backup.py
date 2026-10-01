import sqlite3
import subprocess
from datetime import date, timedelta

import pytest

from app.db import SessionLocal
from app.models import User
from app.scripts import backup as backup_mod


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A backend folder with a .env and a git repo whose origin is a local "GitHub"."""
    github = tmp_path / "github.git"
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    (repo / "start.bat").write_text("echo hi")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "first", cwd=repo)
    git("clone", "-q", "--bare", str(repo), str(github), cwd=tmp_path)
    git("remote", "add", "origin", str(github), cwd=repo)
    backend = repo / "backend"
    backend.mkdir()
    (backend / ".env").write_text("ANTHROPIC_API_KEY=x\n")
    monkeypatch.setattr(backup_mod, "BACKEND", backend)
    monkeypatch.setattr(backup_mod, "REPO", repo)
    return tmp_path / "backups", repo


def test_backup_has_everything_needed_to_restore(setup, tmp_path):
    root, _ = setup
    with SessionLocal() as db:
        db.add(User(username="tk", password_hash="x"))
        db.commit()
    folder, problems = backup_mod.backup(root, keep=15, today=date(2026, 10, 1))
    assert problems == [] and folder == root / "2026-10-01"
    assert sorted(p.name for p in folder.iterdir()) == [".env", "backup-ok.txt", "catalog.db", "jarvis-code.bundle", "jarvis.db", "อ่านก่อน.txt"]
    assert (folder / ".env").read_text() == "ANTHROPIC_API_KEY=x\n"
    assert sqlite3.connect(folder / "jarvis.db").execute("select username from users").fetchall() == [("tk",)]
    readme = (folder / "อ่านก่อน.txt").read_text(encoding="utf-8-sig")
    assert "first" in readme and "jarvis.db  ->" in readme

    # The code comes back from the bundle alone.
    git("clone", "-q", str(folder / "jarvis-code.bundle"), str(tmp_path / "restored"), cwd=tmp_path)
    git("checkout", "-q", "main", cwd=tmp_path / "restored")
    assert (tmp_path / "restored" / "start.bat").read_text() == "echo hi"


def test_daily_task_backs_up_once_a_day(setup):
    root, _ = setup
    day = date(2026, 10, 1)
    assert backup_mod.backup(root, keep=15, auto=True, today=day)[0] is not None
    assert backup_mod.backup(root, keep=15, auto=True, today=day) == (None, [])
    # backup.bat by hand replaces today's folder
    assert backup_mod.backup(root, keep=15, today=day)[0] == root / "2026-10-01"


def test_incomplete_backup_is_retried(setup):
    root, _ = setup
    (backup_mod.BACKEND / ".env").unlink()
    folder, problems = backup_mod.backup(root, keep=15, auto=True, today=date(2026, 10, 1))
    assert problems and not (folder / "backup-ok.txt").exists()
    assert backup_mod.backup(root, keep=15, auto=True, today=date(2026, 10, 1))[0] is not None


def test_only_the_newest_days_are_kept(setup):
    root, _ = setup
    first = date(2026, 10, 1)
    other = root / "my-files"
    other.mkdir(parents=True)
    for i in range(17):
        backup_mod.backup(root, keep=15, today=first + timedelta(days=i))
    days = sorted(p.name for p in root.iterdir() if p.is_dir() and p != other)
    assert len(days) == 15 and days[0] == "2026-10-03" and days[-1] == "2026-10-17"
    assert other.exists()  # folders the backup didn't make are never deleted


def test_main_writes_a_log_line(setup, monkeypatch):
    root, _ = setup
    monkeypatch.setenv("BACKUP_DIR", str(root))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert backup_mod.main([]) == 0
        assert backup_mod.main(["--auto"]) == 0
    finally:
        get_settings.cache_clear()
    lines = (root / "backup.log").read_text(encoding="utf-8").splitlines()
    assert "OK" in lines[0] and "already done" in lines[1]


def test_sqlite_paths_are_relative_to_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_mod, "BACKEND", tmp_path)
    assert backup_mod.sqlite_path("sqlite:///./jarvis.db") == tmp_path / "jarvis.db"
    assert backup_mod.sqlite_path("postgresql+psycopg://x@y/z") is None
