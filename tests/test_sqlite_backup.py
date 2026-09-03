import os
import sqlite3
from pathlib import Path

import pytest

from deploy import sqlite_backup

ROOT = Path(__file__).resolve().parents[1]


def _database(tmp_path: Path) -> Path:
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE fixture (value TEXT NOT NULL)")
        connection.execute("INSERT INTO fixture VALUES ('preserved')")
    return source


def test_backup_is_checked_synced_and_atomically_published_in_order(
    tmp_path: Path, monkeypatch
):
    source = _database(tmp_path)
    target = tmp_path / "backups" / "target.sqlite3"
    target.parent.mkdir()
    events = []
    real_connect = sqlite3.connect
    connection_number = 0

    class RecordedConnection:
        def __init__(self, connection):
            self.connection = connection

        def backup(self, destination):
            events.append("backup")
            return self.connection.backup(destination.connection)

        def execute(self, statement):
            if " ".join(statement.split()) == "PRAGMA quick_check":
                events.append("quick_check")
            return self.connection.execute(statement)

        def close(self):
            self.connection.close()

    def recorded_connect(*args, **kwargs):
        nonlocal connection_number
        connection_number += 1
        return RecordedConnection(real_connect(*args, **kwargs))

    real_chmod = os.chmod
    real_replace = os.replace
    real_file_sync = sqlite_backup._fsync_file
    real_directory_sync = sqlite_backup._fsync_directory

    def recorded_chmod(path, mode):
        events.append(("chmod", mode))
        return real_chmod(path, mode)

    def recorded_file_sync(path):
        events.append("fsync_file")
        return real_file_sync(path)

    def recorded_replace(source_path, target_path):
        events.append("replace")
        return real_replace(source_path, target_path)

    def recorded_directory_sync(path):
        events.append("fsync_directory")
        return real_directory_sync(path)

    monkeypatch.setattr(sqlite_backup.sqlite3, "connect", recorded_connect)
    monkeypatch.setattr(sqlite_backup.os, "chmod", recorded_chmod)
    monkeypatch.setattr(sqlite_backup, "_fsync_file", recorded_file_sync)
    monkeypatch.setattr(sqlite_backup.os, "replace", recorded_replace)
    monkeypatch.setattr(sqlite_backup, "_fsync_directory", recorded_directory_sync)

    sqlite_backup.create_backup(source, target)

    assert connection_number == 2
    assert events == [
        "backup",
        "quick_check",
        ("chmod", 0o600),
        "fsync_file",
        "replace",
        "fsync_directory",
    ]
    assert target.is_file()
    assert not Path(f"{target}.partial").exists()
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600
    with real_connect(f"file:{target}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("SELECT value FROM fixture").fetchone() == (
            "preserved",
        )


def test_file_sync_failure_propagates_without_a_partial_or_published_backup(
    tmp_path: Path, monkeypatch
):
    source = _database(tmp_path)
    target = tmp_path / "target.sqlite3"

    def fail_file_sync(path):
        raise OSError("injected file fsync failure")

    monkeypatch.setattr(sqlite_backup, "_fsync_file", fail_file_sync)

    with pytest.raises(OSError, match="injected file fsync failure"):
        sqlite_backup.create_backup(source, target)

    assert not target.exists()
    assert not Path(f"{target}.partial").exists()


def test_directory_sync_failure_removes_the_published_name_and_propagates(
    tmp_path: Path, monkeypatch
):
    source = _database(tmp_path)
    target = tmp_path / "target.sqlite3"
    calls = 0

    def fail_first_directory_sync(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected directory fsync failure")

    monkeypatch.setattr(sqlite_backup, "_fsync_directory", fail_first_directory_sync)

    with pytest.raises(OSError, match="injected directory fsync failure"):
        sqlite_backup.create_backup(source, target)

    assert calls == 2
    assert not target.exists()
    assert not Path(f"{target}.partial").exists()


def test_release_calls_the_importable_backup_helper_before_runtime_mutation():
    script = (ROOT / "deploy" / "release.sh").read_text(encoding="utf-8")
    function_start = script.index("create_database_backup()")
    function_end = script.index("\n}\n", function_start)
    function = script[function_start:function_end]

    assert '"${SCRIPT_DIR}/sqlite_backup.py"' in function
    assert "<<'PY'" not in function
    snapshot_timers = script.index('for name in "${TIMER_NAMES[@]}"; do', function_end)
    mark_dirty = script.index("TIMER_STATE_DIRTY=1", snapshot_timers)
    stop_timers = script.index('run_host systemctl stop "${name}"', mark_dirty)
    check_workers = script.index('service="${name%.timer}.service"', stop_timers)
    backup_call = script.index("\ncreate_database_backup\n", check_workers)
    mark_stop_attempted = script.index("APP_STOP_ATTEMPTED=1", backup_call)
    stop_service = script.index(
        "trace_command systemctl stop docket.service", mark_stop_attempted
    )
    mark_stopped = script.index("APP_STOPPED=1", stop_service)
    move_tree = script.index('run_fs mv -- "${OPT_DOCKET}" "${BACKUP}"', stop_service)
    assert (
        snapshot_timers
        < mark_dirty
        < stop_timers
        < check_workers
        < backup_call
        < mark_stop_attempted
        < stop_service
        < mark_stopped
        < move_tree
    )
