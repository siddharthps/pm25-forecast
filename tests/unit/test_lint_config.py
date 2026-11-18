"""Every folder that holds Python code is actually linted by Ruff.

Owner's rule (day-zero checklist): a tool's include/exclude list once skipped two folders
silently. This test discovers code folders itself, so a new folder can't be missed.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOT_CODE = {".git", ".venv", ".claude", "notes", "tasks", "docs"}


def _code_folders() -> set[str]:
    folders = set()
    for path in ROOT.rglob("*.py"):
        top = path.relative_to(ROOT).parts[0]
        if (
            len(path.relative_to(ROOT).parts) > 1
            and top not in NOT_CODE
            and not top.startswith(".")
        ):
            folders.add(top)
    return folders


def _ruff_files() -> set[str]:
    out = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--show-files", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {
        Path(line.strip()).resolve().relative_to(ROOT).parts[0]
        for line in out.splitlines()
        if line.strip()
    }


def test_code_folders_are_discovered() -> None:
    # Guards the guard: if discovery breaks, the main test would pass vacuously.
    assert {"src", "tests"} <= _code_folders()


def test_every_code_folder_is_linted() -> None:
    missing = _code_folders() - _ruff_files()
    assert not missing, f"Ruff does not check these code folders: {sorted(missing)}"
