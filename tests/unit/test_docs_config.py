"""The docs setup keeps T11's rules (D-016, D-022, D-043).

Zensical is pinned and builds strictly into `site_build/` (the page's source owns `site/`), with
the macros reading `results.json`. CI builds the site and runs a separate offline link and
anchor checker over it. Vale and the docs check run as pre-commit hooks. The dev commands have
one home, imported by CLAUDE.md.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

from tests.repo_config import ROOT, load_yaml, precommit_hook, workflow
from tests.unit import test_lint_config
from tests.unit.devtools import test_comments

ZENSICAL = ROOT / "zensical.toml"
DOCS_PAGES = ("docs/index.md", "README.md", "DEVELOPMENT.md")


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _project() -> dict[str, Any]:
    project: dict[str, Any] = _toml(ZENSICAL)["project"]
    return project


def _nav_pages(nav: list[Any]) -> set[str]:
    pages: set[str] = set()
    for item in nav:
        for value in item.values() if isinstance(item, dict) else [item]:
            pages |= _nav_pages(value) if isinstance(value, list) else {value}
    return pages


def test_zensical_is_pinned_exactly_in_the_docs_group() -> None:
    group = _toml(ROOT / "pyproject.toml")["dependency-groups"]["docs"]
    zensical = [d for d in group if d.startswith("zensical")]
    assert len(zensical) == 1
    assert re.fullmatch(r"zensical==\d+\.\d+\.\d+", zensical[0])


def test_zensical_builds_strictly_into_site_build() -> None:
    project = _project()
    assert project["docs_dir"] == "docs"
    assert project["site_dir"] == "site_build"
    assert project["strict"] is True
    assert project.get("validation", True) is not False
    assert "site_build/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_macros_read_results_and_fail_on_anything_undefined() -> None:
    macros = _project()["plugins"]["macros"]
    assert macros["modules"] == ["airwatch.docs_macros"]
    assert macros["module_name"] == ""
    assert macros["on_undefined"] == "strict"
    assert macros["on_error_fail"] is True


def test_every_docs_page_is_in_the_nav_and_back() -> None:
    nav = _nav_pages(_project()["nav"])
    on_disk = {p.relative_to(ROOT / "docs").as_posix() for p in (ROOT / "docs").rglob("*.md")}
    assert nav == on_disk
    assert "index.md" in nav


def test_ci_builds_the_docs_strictly_then_checks_links_offline() -> None:
    steps = workflow("ci.yml")["jobs"]["docs"]["steps"]
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "uv sync --frozen --group docs" in runs
    assert "uv run --frozen zensical build --strict" in runs
    lychee = [s for s in steps if str(s.get("uses", "")).startswith("lycheeverse/lychee-action@")]
    assert len(lychee) == 1
    inputs = lychee[0]["with"]
    assert re.fullmatch(r"v\d+\.\d+\.\d+", inputs["lycheeVersion"])
    args = inputs["args"]
    for flag in ("--offline", "--include-fragments", "--index-files index.html", "site_build"):
        assert flag in args, flag
    assert inputs.get("fail", True) is True


def test_vale_and_the_docs_check_run_as_hooks_over_the_docs() -> None:
    vale, docs_check = precommit_hook("vale"), precommit_hook("docs-check")
    assert vale["repo"] == "https://github.com/vale-cli/vale"
    pattern = re.compile(vale["files"])
    for page in DOCS_PAGES:
        assert pattern.search(page), page
    assert "airwatch.devtools.docs_check" in docs_check["entry"]
    assert re.compile(docs_check["files"]).search("results/results.json")


def test_vale_uses_the_project_style_on_markdown() -> None:
    ini = (ROOT / ".vale.ini").read_text(encoding="utf-8")
    assert re.search(r"^StylesPath\s*=\s*styles$", ini, re.MULTILINE)
    assert re.search(r"^BasedOnStyles\s*=\s*AirWatch$", ini, re.MULTILINE)
    rules = list((ROOT / "styles").glob("*/*.yml"))
    assert rules, "the AirWatch style has no rules"
    for rule in rules:
        data = load_yaml(rule)
        assert data["level"] == "error", f"{rule.name}: only errors fail the hook"


def test_dev_commands_have_one_home_imported_by_claude_md() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    dev = (ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")
    assert re.search(r"^@DEVELOPMENT\.md$", claude, re.MULTILINE)
    assert "uv sync --frozen" in dev
    assert "uv sync --frozen" not in claude
    assert "(DEVELOPMENT.md)" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_scope_tests_skip_exactly_the_docs_build_output() -> None:
    assert test_comments.GENERATED_DOCS == test_lint_config.GENERATED_DOCS == _project()["site_dir"]


def test_count_words_are_banned_in_docs_only() -> None:
    ini = (ROOT / ".vale.ini").read_text(encoding="utf-8")
    docs_section = ini.split("[docs/**/*.md]", 1)[1]
    assert re.search(r"^BasedOnStyles\s*=\s*AirWatch,\s*AirWatchDocs$", docs_section, re.MULTILINE)
    rule = load_yaml(ROOT / "styles" / "AirWatchDocs" / "NumberWords.yml")
    assert rule["level"] == "error"
    assert {"two", "six", "twelve"} <= set(rule["tokens"])
    assert "one" not in rule["tokens"]
