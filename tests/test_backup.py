"""สำรองฐานข้อมูลอัตโนมัติ (NFR-7, TOR 5.1)"""
import sqlite3
from datetime import datetime

from core.backup import (
    BackupFile, days_covered, files_to_prune, is_backup_due, list_backups, parse_backup_time, read_status, run_backup,
)


def bf(ts: str) -> BackupFile:
    return BackupFile(name=f"app_{ts}.db", size=1, created_at=datetime.strptime(ts, "%Y%m%d_%H%M%S"))


def test_parse_name():
    assert parse_backup_time("app_20261028_030000.db") == datetime(2026, 10, 28, 3, 0)
    assert parse_backup_time("status.json") is None


def test_due_once_per_day_after_hour():
    files = [bf("20261027_030001")]
    assert not is_backup_due(files, datetime(2026, 10, 28, 2, 59), 3)  # ยังไม่ถึงตี 3
    assert is_backup_due(files, datetime(2026, 10, 28, 3, 0), 3)
    assert not is_backup_due(files + [bf("20261028_030005")], datetime(2026, 10, 28, 15, 0), 3)
    assert is_backup_due([], datetime(2026, 10, 28, 15, 0), 3)  # ติดตั้งใหม่ สำรองทันที


def test_prune_keeps_newest():
    files = [bf(f"202610{d:02d}_030000") for d in range(28, 10, -1)]  # ใหม่ -> เก่า 18 ไฟล์
    pruned = files_to_prune(files, 14)
    assert len(pruned) == 4 and pruned[0].name == "app_20261014_030000.db"
    assert days_covered(files[:14]) == 14


def test_run_backup_creates_valid_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "7")
    db = tmp_path / "app.db"
    con = sqlite3.connect(db)
    con.execute("create table t (x int)")
    con.execute("insert into t values (42)")
    con.commit()
    con.close()
    out = tmp_path / "backups"
    for d in range(1, 10):  # ไฟล์เก่า 9 ชุด
        (out).mkdir(exist_ok=True)
        (out / f"app_202610{d:02d}_030000.db").write_bytes(b"old")
    status = run_backup(db, out, datetime(2026, 10, 28, 3, 0, 1))
    assert status["ok"], status
    newest = list_backups(out)[0]
    assert newest.name == "app_20261028_030001.db"
    assert sqlite3.connect(out / newest.name).execute("select x from t").fetchone()[0] == 42
    assert len(list_backups(out)) == 7  # เก็บไม่น้อยกว่า 7 ชุด ตามที่ตั้ง
    assert read_status(out)["file"] == newest.name


def test_failed_backup_is_reported(tmp_path):
    status = run_backup(tmp_path / "missing" / "nope.db", tmp_path / "b", datetime(2026, 10, 28, 3, 0))
    assert status["ok"] is False and "ไม่สำเร็จ" in status["message"]
