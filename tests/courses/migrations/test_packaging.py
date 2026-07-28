"""P4-01 wheel-content regression checks for the migration authority."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile

_BASELINE_SQL = "deeptutor/courses/migrations/sql/0000_phase3a_baseline.sql"


def _build_wheel(project: Path, output: Path) -> Path:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(output),
            ".",
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    wheels = list(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_root_and_cli_wheels_ship_the_baseline_migration_sql(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    # The CLI project points package discovery at the root.  Build it first so
    # the root wheel's temporary setuptools build tree cannot affect discovery.
    for project in (root / "packaging" / "deeptutor-cli", root):
        wheel = _build_wheel(project, tmp_path / project.name)
        with zipfile.ZipFile(wheel) as archive:
            assert _BASELINE_SQL in archive.namelist()
