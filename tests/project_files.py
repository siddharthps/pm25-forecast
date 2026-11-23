"""Walk the project for the scope tests without entering folders they ignore (#83), and read what
a module imports (#103).

`walk(root, skip)` yields what `root.rglob("*")` would, minus everything under a top-level
folder named in `skip` or starting with a dot. Those folders are never entered: `.venv` alone
holds tens of thousands of files.

`import_roots(path)` names the top-level package of every import in the file, anywhere in it. A
relative import comes back with a leading dot (`.x`, or `.` alone), so it can never pass as a
standard-library name: the modules checked with it run alone, outside their package.
"""

import ast
from collections.abc import Iterator
from pathlib import Path


def walk(root: Path, skip: set[str]) -> Iterator[Path]:
    for child in sorted(root.iterdir()):
        if child.name in skip or child.name.startswith("."):
            continue
        yield child
        if child.is_dir():
            yield from child.rglob("*")


def import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            roots.add("." + root if node.level else root)
    return roots
