"""The docs macros (T11, D-016, D-044): `results/results.json` becomes the `results` variable.

Zensical calls `define_env` with an env holding `variables` and `project_dir`. A null result is
shown as a visible placeholder, so pages need no filter (filters clash with table pipes).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from airwatch.docs_macros import PENDING, define_env, for_display

ROOT = Path(__file__).resolve().parents[2]

JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(), inner, max_size=3),
    max_leaves=10,
)


def _env(project_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(variables={}, filters={}, project_dir=str(project_dir))


def test_results_file_becomes_the_results_variable(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "results.json").write_text(
        '{"design": {"variants": 6}, "headline": {"mae": null}}', "utf-8"
    )
    env = _env(tmp_path)
    define_env(env)
    assert env.variables["results"] == {"design": {"variants": 6}, "headline": {"mae": PENDING}}


def test_a_missing_results_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        define_env(_env(tmp_path))


@pytest.mark.parametrize(
    ("value", "shown"),
    [(None, PENDING), (6, 6), (0, 0), (False, False), ("", ""), ([None, 1], [PENDING, 1])],
)
def test_only_nulls_become_the_placeholder(value: object, shown: object) -> None:
    assert for_display(value) == shown


@given(JSON)
def test_display_keeps_every_key_and_every_non_null_value(value: object) -> None:
    def nulls_out(node: object) -> object:
        if isinstance(node, dict):
            return {k: nulls_out(v) for k, v in node.items()}
        if isinstance(node, list):
            return [nulls_out(v) for v in node]
        return PENDING if node is None else node

    assert for_display(value) == nulls_out(value)


def test_the_real_results_file_loads() -> None:
    env = _env(ROOT)
    define_env(env)
    raw = json.loads((ROOT / "results" / "results.json").read_text("utf-8"))
    assert env.variables["results"] == for_display(raw)
