"""Every folder that holds Python code is actually linted by Ruff.

Owner's rule (day-zero checklist): a tool's include/exclude list once skipped two folders
silently. This test discovers code folders itself, so a new folder can't be missed.
"""

import re
import subprocess
import sys
from pathlib import Path

import yaml

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


# --- JavaScript and CSS (the page, T7): every such file is in Biome's pre-commit scope --------

WEB_SUFFIXES = {".js", ".mjs", ".css"}


def _biome_pattern() -> re.Pattern[str]:

    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [h for repo in config["repos"] for h in repo["hooks"] if h["id"] == "biome-check"]
    assert len(hooks) == 1, "exactly one biome-check hook"
    return re.compile(hooks[0]["files"])


def _web_files() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.suffix in WEB_SUFFIXES
        and path.relative_to(ROOT).parts[0] not in NOT_CODE
        and not path.relative_to(ROOT).parts[0].startswith(".")
        and "node_modules" not in path.parts
        and "htmlcov" not in path.parts
    )


def test_web_files_are_discovered() -> None:
    # Guards the guard: the page's script must be found, or the next test passes vacuously.
    assert "site/app.js" in _web_files()


def test_every_web_file_is_checked_by_biome() -> None:
    pattern = _biome_pattern()
    missing = [f for f in _web_files() if not pattern.search(f)]
    assert not missing, f"Biome's hook does not cover: {missing}"
