"""The Pages workflow keeps the go-live gate and publishes only the page (#14, T7; D-025, D-036).

The generic rules (actions pinned to SHAs, a read-only default token) are checked for every
workflow in test_ci_config.py.
"""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
SITE_FILES = {"index.html", "app.js", "style.css"}


def _load() -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(PAGES.read_text(encoding="utf-8"))
    return data


def test_it_runs_only_when_the_page_changes_or_on_request() -> None:
    workflow = _load()
    triggers: dict[str, Any] = workflow["on"] if "on" in workflow else workflow[True]
    assert triggers["push"]["branches"] == ["main"]
    assert "site/**" in triggers["push"]["paths"]
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers


def test_nothing_deploys_until_the_owner_turns_on_go_live() -> None:
    deploy = _load()["jobs"]["deploy"]
    assert deploy["if"] == "vars.PAGES_GO_LIVE == 'true'"
    assert deploy["needs"] == "build"


def test_only_the_deploy_job_can_write_to_pages() -> None:
    jobs = _load()["jobs"]
    assert jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert "permissions" not in jobs["build"]


def test_only_the_pages_own_files_are_published() -> None:
    steps = _load()["jobs"]["build"]["steps"]
    collect = next(s for s in steps if s.get("name") == "Collect only the page's files")
    assert collect["run"].split("\n")[1].strip() == (
        "cp site/index.html site/app.js site/style.css _site/"
    )
    upload = next(s for s in steps if "upload-pages-artifact" in str(s.get("uses")))
    assert upload["with"]["path"] == "_site/"
    assert {p.name for p in (ROOT / "site").iterdir() if p.is_file()} == SITE_FILES, (
        "a new file in site/ must be added to the deploy on purpose"
    )
