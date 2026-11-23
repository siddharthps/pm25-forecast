"""Every folder that holds Python code is actually linted by Ruff.

Owner's rule (day-zero checklist): a tool's include/exclude list once skipped two folders
silently. This test discovers code folders itself, so a new folder can't be missed.
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from tests.project_files import walk
from tests.repo_config import ROOT, load_yaml, precommit_hook

NOT_CODE = {".git", ".venv", ".claude", "notes", "tasks", "docs"}


def _code_folders() -> set[str]:
    folders = set()
    for path in walk(ROOT, NOT_CODE):
        if path.suffix == ".py" and len(path.relative_to(ROOT).parts) > 1:
            folders.add(path.relative_to(ROOT).parts[0])
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
    assert {"src", "tests"} <= _code_folders(), "guards the guard: discovery broke"


def test_every_code_folder_is_linted() -> None:
    missing = _code_folders() - _ruff_files()
    assert not missing, f"Ruff does not check these code folders: {sorted(missing)}"


WEB_SUFFIXES = {".js", ".mjs", ".css"}
GENERATED_DOCS = "site_build"


def _biome_pattern() -> re.Pattern[str]:
    return re.compile(precommit_hook("biome-check")["files"])


def _web_files() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in walk(ROOT, NOT_CODE | {GENERATED_DOCS})
        if path.suffix in WEB_SUFFIXES
        and "node_modules" not in path.parts
        and "htmlcov" not in path.parts
    )


def test_web_files_are_discovered() -> None:
    assert "site/app.js" in _web_files(), "guards the guard: the page's script is missing"


def test_every_web_file_is_checked_by_biome() -> None:
    pattern = _biome_pattern()
    missing = [f for f in _web_files() if not pattern.search(f)]
    assert not missing, f"Biome's hook does not cover: {missing}"


def _vendored_skill_globs() -> set[str]:
    lock = json.loads((ROOT / "skills-lock.json").read_text(encoding="utf-8"))
    return {f".claude/skills/{name}/**" for name in lock["skills"]}


def _skill_globs(patterns: list[str]) -> set[str]:
    return {p for p in patterns if p.startswith(".claude/skills/")}


def test_our_own_skills_exist_beside_the_vendored_ones() -> None:
    ours = {p.name for p in (ROOT / ".claude" / "skills").iterdir() if p.is_dir()} - {
        g.split("/")[2] for g in _vendored_skill_globs()
    }
    assert "delete-comment" in ours, "guards the guard: no skill of our own to keep linted"


def test_markdownlint_skips_only_the_vendored_skills() -> None:
    config = load_yaml(ROOT / ".markdownlint-cli2.yaml")
    assert _skill_globs(config["ignores"]) == _vendored_skill_globs()


def test_ruff_format_skips_only_the_vendored_skills() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert _skill_globs(pyproject["tool"]["ruff"]["format"]["exclude"]) == _vendored_skill_globs()
