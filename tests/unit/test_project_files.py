"""The shared walk for the scope tests (#83): it skips ignored top-level folders before entering.

The scope tests (lint, Biome, comment ban) look for code across the whole project, and drop
`.venv` and other ignored folders anyway. Walking into them first cost about 2 s per scan.
"""

from pathlib import Path

from tests.project_files import walk


def _tree(root: Path, paths: list[str]) -> Path:
    for rel in paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return root


def _rel(root: Path, skip: set[str]) -> set[str]:
    return {p.relative_to(root).as_posix() for p in walk(root, skip)}


def test_skipped_and_hidden_top_folders_are_not_entered(tmp_path: Path) -> None:
    root = _tree(tmp_path, ["src/a.py", ".venv/lib/b.py", "notes/c.py", "top.py"])
    assert _rel(root, {"notes"}) == {"src", "src/a.py", "top.py"}


def test_a_skipped_name_deeper_down_is_still_walked(tmp_path: Path) -> None:
    root = _tree(tmp_path, ["src/notes/a.py", "src/.hidden/b.py"])
    assert _rel(root, {"notes"}) == {
        "src",
        "src/notes",
        "src/notes/a.py",
        "src/.hidden",
        "src/.hidden/b.py",
    }


def test_it_matches_a_full_walk_filtered_at_the_top(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        ["src/x/a.py", "site/b.js", ".git/c", "docs/d.md", "site_build/e.js", "f.toml"],
    )
    skip = {"docs", "site_build"}
    full = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.relative_to(root).parts[0] not in skip
        and not p.relative_to(root).parts[0].startswith(".")
    }
    assert _rel(root, skip) == full
