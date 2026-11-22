"""The core suite stays under its 30 s budget (SPEC § Testing, D-035, #83).

Each of the 4 workers collects every test file, so an import at the top of a test file is paid
4 times. Prefect alone took about 2 s per worker, to collect a handful of tests. Those tests
import it through the `daily` fixture instead, so only a worker that runs one pays.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
HEAVY = ("prefect", "airwatch.flows")


def _top_level_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _heavy(names: set[str]) -> set[str]:
    return {n for n in names if any(n == h or n.startswith(f"{h}.") for h in HEAVY)}


def test_the_heavy_check_sees_both_import_forms(tmp_path: Path) -> None:
    sample = tmp_path / "test_x.py"
    sample.write_text(
        "import prefect\nfrom airwatch.flows import daily\nimport os\n"
        "def f():\n    import prefect.runtime\n",
        encoding="utf-8",
    )
    assert _heavy(_top_level_imports(sample)) == {
        "prefect",
        "airwatch.flows",
        "airwatch.flows.daily",
    }


def test_no_test_file_imports_prefect_at_the_top() -> None:
    files = sorted(TESTS.rglob("*.py"))
    assert len(files) > 20, "discovery broke: nothing to guard"
    found = {
        p.relative_to(TESTS).as_posix(): sorted(heavy)
        for p in files
        if (heavy := _heavy(_top_level_imports(p)))
    }
    assert not found, f"import these through the `daily` fixture instead: {found}"
