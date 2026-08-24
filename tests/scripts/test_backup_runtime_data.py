from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from deeptutor.courses.deployment import SingleProcessCourseLock


def _module():
    path = Path(__file__).parents[2] / "scripts" / "backup-runtime-data.py"
    spec = importlib.util.spec_from_file_location("backup_runtime_data", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "system" / "auth").mkdir(parents=True)
    (data / "system" / "grants").mkdir()
    (data / "users" / "u_alice" / "user").mkdir(parents=True)
    (data / "system" / "auth" / "users.json").write_text(
        '{"alice":{"id":"u_alice","role":"user","disabled":false}}\n',
        encoding="utf-8",
    )
    (data / "system" / "grants" / "u_alice.json").write_text(
        '{"version":2,"user_id":"u_alice","partners":[]}\n', encoding="utf-8"
    )
    (data / "users" / "u_alice" / "user" / "courses.db").write_bytes(b"disposable-course-state")
    # The runtime lock is deliberately present but unlocked.  It must not be
    # restored because bringing it back could strand the next application.
    (data / "system" / "course-single-process.lock").touch()
    return data


def test_backup_verify_and_restore_round_trip_preserves_tree(tmp_path: Path, capsys) -> None:
    module = _module()
    data = _fixture_data(tmp_path)
    archive = tmp_path / "backups" / "school-beta.tgz"
    original_digest = module._tree_digest(tuple(module._iter_entries(data)))

    assert module.main(["create", "--data-root", str(data), "--output", str(archive)]) == 0
    created = capsys.readouterr().out
    assert '"status": "created"' in created
    assert archive.stat().st_mode & 0o777 == 0o600

    assert module.main(["verify", "--backup", str(archive)]) == 0
    verified = capsys.readouterr().out
    assert '"status": "verified"' in verified
    assert f'"tree_digest": "{original_digest}"' in verified

    (data / "system" / "auth" / "users.json").write_text("mutated\n", encoding="utf-8")
    (data / "unexpected.txt").write_text("must not survive restore\n", encoding="utf-8")
    assert module.main(["restore", "--backup", str(archive), "--data-root", str(data)]) == 1
    capsys.readouterr()

    assert (
        module.main(
            ["restore", "--backup", str(archive), "--data-root", str(data), "--replace"]
        )
        == 0
    )
    restored = capsys.readouterr().out
    assert '"status": "restored"' in restored
    assert f'"restored_tree_digest": "{original_digest}"' in restored
    assert module._tree_digest(tuple(module._iter_entries(data))) == original_digest
    assert not (data / "system" / "course-single-process.lock").exists()
    assert not (data / "unexpected.txt").exists()
    assert list(tmp_path.glob("data.before-restore-*"))


def test_backup_fails_when_application_owns_course_lock(tmp_path: Path) -> None:
    module = _module()
    data = _fixture_data(tmp_path)
    lock = SingleProcessCourseLock(data / module.LOCK_RELATIVE_PATH)
    lock.acquire(env={"WEB_CONCURRENCY": "1", "UVICORN_WORKERS": "1", "GUNICORN_CMD_ARGS": ""})
    try:
        with pytest.raises(module.BackupError, match="Another DeepTutor application process"):
            module.create_backup(data, tmp_path / "backup.tgz")
    finally:
        lock.release()


@pytest.mark.parametrize("entry_kind", ["symlink", "hardlink"])
def test_backup_rejects_linked_private_state(tmp_path: Path, entry_kind: str) -> None:
    module = _module()
    data = _fixture_data(tmp_path)
    source = data / "system" / "auth" / "source.txt"
    source.write_text("private", encoding="utf-8")
    target = data / "system" / "auth" / f"{entry_kind}.txt"
    if entry_kind == "symlink":
        target.symlink_to(source)
    else:
        target.hardlink_to(source)
    with pytest.raises(module.BackupError, match="(symbolic link|hard-linked)"):
        module.create_backup(data, tmp_path / "backup.tgz")
