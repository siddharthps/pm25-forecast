"""Walk the project for the scope tests without entering folders they ignore (#83).

`walk(root, skip)` yields what `root.rglob("*")` would, minus everything under a top-level
folder named in `skip` or starting with a dot. Those folders are never entered: `.venv` alone
holds tens of thousands of files.
"""

from collections.abc import Iterator
from pathlib import Path


def walk(root: Path, skip: set[str]) -> Iterator[Path]:
    for child in sorted(root.iterdir()):
        if child.name in skip or child.name.startswith("."):
            continue
        yield child
        if child.is_dir():
            yield from child.rglob("*")
