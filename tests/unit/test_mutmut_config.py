"""mutmut runs the core suite in a copy of the repo, so the copy must hold all of it (#42).

The repo-wide tests read files outside `src/` and `tests/` (the page, the workflows, the docs).
A top-level entry missing from `also_copy` breaks mutmut's clean run, and every mutant is left
"not checked".
"""

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mutmut() -> dict[str, list[str]]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config: dict[str, list[str]] = pyproject["tool"]["mutmut"]
    return config


def test_every_tracked_top_level_entry_is_copied() -> None:
    tracked = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD"],  # noqa: S607  (git from PATH, fixed arguments)
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "src" in tracked
    copied = {entry.rstrip("/") for entry in _mutmut()["also_copy"]}
    assert set(tracked) - {"src"} <= copied


def test_it_mutates_only_listed_source_files() -> None:
    config = _mutmut()
    assert config["source_paths"] == ["src/"]
    for path in config["only_mutate"]:
        assert (ROOT / path).is_file(), path


OPT_IN = {"live"}
"""Test folders mutmut may skip: they call real external APIs (`-m live`, never in CI)."""


def test_mutmut_runs_every_offline_test_folder() -> None:
    """#112: with `tests/integration` left out, every mutant only the integration tests catch
    (the forecast's publish path, the job) was reported as a survivor: 88 in `run_daily` alone."""
    folders = {
        p.name
        for p in (ROOT / "tests").iterdir()
        if p.is_dir() and any(p.rglob("test_*.py")) and p.name not in OPT_IN
    }
    assert folders == {"unit", "property", "integration"}, "a new test folder: add it here"
    selection = set(_mutmut()["pytest_add_cli_args_test_selection"])
    assert {f"tests/{f}" for f in folders} <= selection
