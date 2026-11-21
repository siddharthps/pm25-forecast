"""The docs macros (T11, D-016): `results/results.json` becomes the `results` variable.

Zensical calls `define_env` with an env holding `variables`, `filters` and `project_dir`. The
`show` filter prints a value, or a visible placeholder while the result is still null.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from airwatch.docs_macros import PENDING, define_env, show

ROOT = Path(__file__).resolve().parents[2]


def _env(project_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(variables={}, filters={}, project_dir=str(project_dir))


def test_results_file_becomes_the_results_variable(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "results.json").write_text('{"design": {"variants": 6}}', "utf-8")
    env = _env(tmp_path)
    define_env(env)
    assert env.variables["results"] == {"design": {"variants": 6}}
    assert env.filters["show"] is show


def test_a_missing_results_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        define_env(_env(tmp_path))


@pytest.mark.parametrize(("value", "shown"), [(None, PENDING), (6, "6"), (4.25, "4.25")])
def test_show_marks_pending_values(value: object, shown: str) -> None:
    assert show(value) == shown


def test_the_real_results_file_loads() -> None:
    env = _env(ROOT)
    define_env(env)
    assert (
        json.loads((ROOT / "results" / "results.json").read_text("utf-8"))
        == env.variables["results"]
    )
