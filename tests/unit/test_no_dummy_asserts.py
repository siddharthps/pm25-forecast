"""No test keeps a parameter alive with a bare `assert <param>` (#58).

Such a line exists only to quiet Ruff's unused-argument rule (ARG001). It checks nothing, and
the description it carries never reaches pytest's output. A case's description belongs in
`pytest.param(..., id="...")`.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]


def _dummy_asserts(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        params = {a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        found.extend(
            f"{node.name}: assert {stmt.test.id}"
            for stmt in ast.walk(node)
            if isinstance(stmt, ast.Assert)
            and isinstance(stmt.test, ast.Name)
            and stmt.test.id in params
        )
    return found


def test_the_check_finds_a_bare_assert_on_a_parameter() -> None:
    source = (
        "def test_a(change, why):\n    change()\n    assert why\n"
        "def test_b(x):\n    assert x == 1\n"
        "def test_c(x):\n    y = x\n    assert y\n"
    )
    assert _dummy_asserts(source) == ["test_a: assert why"]


def test_no_test_asserts_a_bare_parameter() -> None:
    files = sorted(TESTS.rglob("*.py"))
    assert len(files) > 20, "discovery broke: nothing to guard"
    found = {
        p.relative_to(TESTS).as_posix(): hits
        for p in files
        if (hits := _dummy_asserts(p.read_text(encoding="utf-8")))
    }
    assert not found, f"name the case with pytest.param(..., id=...) instead: {found}"
