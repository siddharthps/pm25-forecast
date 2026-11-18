"""The CI and Dependabot config keeps the rules in #6 (T2) and D-027.

These are text and structure checks on the workflow files, so a rule can't be dropped by an edit
that still produces valid YAML. They run offline in milliseconds.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
LOCK_UPGRADE = WORKFLOWS / "uv-lock-upgrade.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"

# `uses: owner/repo[/path]@<40-hex sha>  # vX.Y.Z` (the version comment on the same line, which
# is the form Dependabot keeps up to date).
PINNED = re.compile(r"^\s*-?\s*uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s+#\s*v\d+\.\d+\.\d+\s*$")
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _load(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} is not a YAML mapping"
    return data


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML follows YAML 1.1, where a bare `on` key loads as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "triggers must be a mapping"
    return triggers


def _run_lines(workflow: dict[Any, Any]) -> str:
    return "\n".join(
        str(step.get("run", ""))
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    )


def _uv_floor() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    required = pyproject["tool"]["uv"]["required-version"]
    match = re.fullmatch(r">=(\d+\.\d+\.\d+)", required)
    assert match, f"unexpected required-version form: {required!r}"
    return match.group(1)


def test_workflows_exist() -> None:
    # Guards the guards below: with no workflow files they would pass vacuously.
    assert CI in _workflow_files()
    assert LOCK_UPGRADE in _workflow_files()


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_sha_with_its_version(path: Path) -> None:
    bad = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if (m := USES.match(line)) and not m.group(1).startswith("./") and not PINNED.match(line)
    ]
    assert not bad, f"{path.name}: actions not pinned as '@<sha>  # vX.Y.Z': {bad}"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_token_is_read_only_by_default(path: Path) -> None:
    # Least privilege: a top-level `permissions: contents: read`; jobs widen it only as needed.
    assert _load(path).get("permissions") == {"contents": "read"}


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_uv_version_in_ci_is_the_pyproject_floor(path: Path) -> None:
    # CI, the lock job and every developer resolve with the same uv (D-027).
    for job in _load(path)["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                assert step.get("with", {}).get("version") == _uv_floor()


def test_ci_runs_on_prs_pushes_to_main_and_dispatch() -> None:
    triggers = _triggers(_load(CI))
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]
    # The lock-upgrade job dispatches CI on its branch (GITHUB_TOKEN PRs don't trigger it).
    assert "workflow_dispatch" in triggers


@pytest.mark.parametrize(
    "command",
    [
        "uv sync --frozen",
        "uv run --frozen ruff check",
        "uv run --frozen ruff format --check",
        "uv run --frozen mypy",
        "uv run --frozen pytest",
        "--cov",
        "uv lock --check",
    ],
)
def test_ci_runs_each_gate(command: str) -> None:
    assert command in _run_lines(_load(CI))


def test_ci_scans_full_history_with_the_pre_commit_gitleaks_version() -> None:
    ci = _load(CI)
    steps = [step for job in ci["jobs"].values() for step in job.get("steps", [])]
    gitleaks = [s for s in steps if str(s.get("uses", "")).startswith("gitleaks/gitleaks-action@")]
    assert len(gitleaks) == 1
    precommit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    pin = r"gitleaks/gitleaks\n\s+rev: [0-9a-f]{40}\s+# frozen: v(\d+\.\d+\.\d+)"
    match = re.search(pin, precommit)
    assert match, "gitleaks pin not found in .pre-commit-config.yaml"
    assert gitleaks[0]["env"]["GITLEAKS_VERSION"] == match.group(1)
    # Full history, so a secret in any commit of the PR is caught, not just the tip.
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert any(s.get("with", {}).get("fetch-depth") == 0 for s in checkouts)


def test_ci_never_keeps_the_checkout_token() -> None:
    for path in _workflow_files():
        for job in _load(path)["jobs"].values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    assert step.get("with", {}).get("persist-credentials") is False, path.name


def test_dependabot_updates_actions_but_not_python() -> None:
    # D-027: Python deps go through the scheduled `uv lock --upgrade` job, not Dependabot,
    # whose bundled uv is older than the pyproject floor.
    config = _load(DEPENDABOT)
    ecosystems = {u["package-ecosystem"] for u in config["updates"]}
    assert "github-actions" in ecosystems
    assert not ecosystems & {"uv", "pip"}


def test_lock_upgrade_job_is_scheduled_and_dispatches_ci() -> None:
    workflow = _load(LOCK_UPGRADE)
    triggers = _triggers(workflow)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    runs = _run_lines(workflow)
    assert "uv lock --upgrade" in runs
    assert "gh workflow run ci.yml" in runs
