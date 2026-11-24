"""The CI and Dependabot config keeps the rules in #6 (T2) and D-027.

These are text and structure checks on the workflow files, so a rule can't be dropped by an edit
that still produces valid YAML. They run offline in milliseconds.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from airwatch.devtools import uv_lock_pr
from tests.repo_config import (
    PREFECT_EXPORT,
    ROOT,
    WATCHDOG_EXPORT,
    WORKFLOWS,
    load_yaml,
    precommit_hook,
    run_lines,
    steps,
    triggers,
    workflow_files,
)

CI = WORKFLOWS / "ci.yml"
LOCK_UPGRADE = WORKFLOWS / "uv-lock-upgrade.yml"
MUTMUT = WORKFLOWS / "mutmut.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"

PINNED = re.compile(r"^\s*-?\s*uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s+#\s*v\d+\.\d+\.\d+\s*$")
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)")


def _uv_floor() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    required = pyproject["tool"]["uv"]["required-version"]
    match = re.fullmatch(r">=(\d+\.\d+\.\d+)", required)
    assert match, f"unexpected required-version form: {required!r}"
    return match.group(1)


def test_workflows_exist() -> None:
    assert CI in workflow_files(), "guards the guards: no workflows, so they pass vacuously"
    assert LOCK_UPGRADE in workflow_files()


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_sha_with_its_version(path: Path) -> None:
    bad = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if (m := USES.match(line)) and not m.group(1).startswith("./") and not PINNED.match(line)
    ]
    assert not bad, f"{path.name}: actions not pinned as '@<sha>  # vX.Y.Z': {bad}"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_workflow_token_is_read_only_by_default(path: Path) -> None:
    assert load_yaml(path).get("permissions") == {"contents": "read"}


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_uv_version_in_ci_is_the_pyproject_floor(path: Path) -> None:
    for step in steps(load_yaml(path)):
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
            assert step.get("with", {}).get("version") == _uv_floor()


def test_ci_runs_on_prs_pushes_to_main_and_dispatch() -> None:
    on = triggers(load_yaml(CI))
    assert "pull_request" in on
    assert on["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in on


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
        "node --test tests/site/",
    ],
)
def test_ci_runs_each_gate(command: str) -> None:
    assert command in run_lines(load_yaml(CI))


def test_ci_scans_full_history_with_the_pre_commit_gitleaks_version() -> None:
    ci_steps = steps(load_yaml(CI))
    gitleaks = [
        s for s in ci_steps if str(s.get("uses", "")).startswith("gitleaks/gitleaks-action@")
    ]
    assert len(gitleaks) == 1
    precommit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    pin = r"gitleaks/gitleaks\n\s+rev: [0-9a-f]{40}\s+# frozen: v(\d+\.\d+\.\d+)"
    match = re.search(pin, precommit)
    assert match, "gitleaks pin not found in .pre-commit-config.yaml"
    assert gitleaks[0]["env"]["GITLEAKS_VERSION"] == match.group(1)
    checkouts = [s for s in ci_steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert any(s.get("with", {}).get("fetch-depth") == 0 for s in checkouts), (
        "full history, so a secret in any commit of the PR is caught, not just the tip"
    )


def _terraform_job() -> dict[Any, Any]:
    jobs = [j for j in load_yaml(CI)["jobs"].values() if j.get("name") == "Terraform"]
    assert len(jobs) == 1, "ci.yml needs exactly one job named 'Terraform' (#8)"
    job = jobs[0]
    assert isinstance(job, dict)
    return job


@pytest.mark.parametrize(
    "command",
    [
        "terraform fmt -check -recursive",
        "terraform init -backend=false -input=false -lockfile=readonly",
        "terraform validate",
        "terraform test",
    ],
)
def test_ci_checks_terraform_offline(command: str) -> None:
    runs = "\n".join(str(s.get("run", "")) for s in _terraform_job()["steps"])
    assert command in runs


def test_ci_terraform_version_matches_main_tf() -> None:
    main_tf = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    match = re.search(r'required_version = "~> (\d+\.\d+\.\d+)"', main_tf)
    assert match, "required_version not found in infra/main.tf"
    tf_steps = _terraform_job()["steps"]
    setup = [s for s in tf_steps if str(s.get("uses", "")).startswith("hashicorp/setup-terraform@")]
    assert len(setup) == 1
    assert setup[0]["with"]["terraform_version"] == match.group(1)


def test_every_skipped_pre_commit_hook_is_checked_elsewhere_in_ci() -> None:
    """A hook skipped in CI's pre-commit step needs its own CI step, or the check vanishes."""
    covered_by = {
        "ruff-check": "uv run --frozen ruff check",
        "ruff-format": "uv run --frozen ruff format --check",
        "mypy": "uv run --frozen mypy",
        "terraform-fmt": "terraform fmt -check -recursive",
        "gitleaks": "gitleaks/gitleaks-action@",
    }
    skip_steps = [s for s in steps(load_yaml(CI)) if "SKIP" in s.get("env", {})]
    assert len(skip_steps) == 1
    skipped = set(skip_steps[0]["env"]["SKIP"].split(","))
    unknown = skipped - covered_by.keys()
    assert not unknown, f"skipped in CI with no known replacement: {sorted(unknown)}"
    text = CI.read_text(encoding="utf-8")
    for hook in skipped:
        assert covered_by[hook] in text, f"{hook} is skipped but nothing else in CI runs it"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_ci_never_keeps_the_checkout_token(path: Path) -> None:
    for step in steps(load_yaml(path)):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, path.name


def test_coverage_floor_is_at_least_85() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] >= 85


def test_dependabot_updates_actions_but_not_python() -> None:
    config = load_yaml(DEPENDABOT)
    ecosystems = {u["package-ecosystem"] for u in config["updates"]}
    assert "github-actions" in ecosystems
    assert not ecosystems & {"uv", "pip"}


COOLDOWN_DAYS = 7
LOCK_UPGRADE_CMD = f'uv lock --upgrade --exclude-newer "{COOLDOWN_DAYS} days"'


def test_the_weekly_lock_waits_as_long_as_dependabot_does_for_actions() -> None:
    """D-056: a release reaches the lock PR only once it's a week old, as Actions updates do
    (Dependabot's cooldown). Only the job sets it, so a local `uv lock` is unaffected."""
    (actions,) = [
        u for u in load_yaml(DEPENDABOT)["updates"] if u["package-ecosystem"] == "github-actions"
    ]
    assert actions["cooldown"]["default-days"] == COOLDOWN_DAYS
    runs = [str(step.get("run", "")).strip() for step in steps(load_yaml(LOCK_UPGRADE))]
    (upgrade,) = [r for r in runs if r.startswith("uv lock")]
    assert upgrade.startswith(LOCK_UPGRADE_CMD), "no upgrade without the wait"
    extra = upgrade.removeprefix(LOCK_UPGRADE_CMD).split()
    assert all(re.fullmatch(r"--exclude-newer-package=[a-z0-9-]+=false", e) for e in extra), (
        "only an urgent release's exemption (DEVELOPMENT.md) may follow"
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "exclude-newer" not in pyproject["tool"]["uv"], "the wait lives in the job only"


def test_the_weekly_lock_upgrade_refreshes_both_exports_then_opens_its_pr() -> None:
    """Both requirements files are regenerated and committed with the lock, or the lock job's
    own PR would fail the drift tests (test_prefect_deployment.py, watchdog/test_build.py)."""
    workflow = load_yaml(LOCK_UPGRADE)
    on = triggers(workflow)
    assert "schedule" in on
    assert "workflow_dispatch" in on
    runs = [str(step.get("run", "")).strip() for step in steps(workflow)]
    upgrade = next(i for i, r in enumerate(runs) if r.startswith(LOCK_UPGRADE_CMD))
    prefect = " ".join(PREFECT_EXPORT) + " > requirements/prefect-run.txt"
    watchdog = " ".join(WATCHDOG_EXPORT) + " > requirements/watchdog.txt"
    assert runs[upgrade + 1] == prefect
    assert watchdog in runs
    pr_step = next(i for i, r in enumerate(runs) if "src/airwatch/devtools/uv_lock_pr.py" in r)
    assert upgrade < runs.index(prefect) < runs.index(watchdog) < pr_step, (
        "lock, both exports, then the PR step"
    )
    assert {"uv.lock", "requirements/prefect-run.txt", "requirements/watchdog.txt"} <= set(
        uv_lock_pr.FILES
    )
    module = (ROOT / "src/airwatch/devtools/uv_lock_pr.py").read_text(encoding="utf-8")
    assert '"workflow"' not in module, "no CI dispatch: the PR's own CI runs (D-049)"


def test_the_lock_pr_is_opened_with_a_scoped_github_app_token() -> None:
    """D-049: GITHUB_TOKEN's pull_request runs wait for a person's approval, and a dispatched CI
    run doesn't count for the ruleset. An App installation token's events run CI normally."""
    workflow = load_yaml(LOCK_UPGRADE)
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {"contents": "read"}, "GITHUB_TOKEN writes nothing here"
    all_steps = steps(workflow)
    (app,) = [
        s
        for s in all_steps
        if str(s.get("uses", "")).startswith("actions/create-github-app-token@")
    ]
    assert app["with"] == {
        "client-id": "${{ vars.LOCK_APP_CLIENT_ID }}",
        "private-key": "${{ secrets.LOCK_APP_PRIVATE_KEY }}",
        "permission-contents": "write",
        "permission-pull-requests": "write",
    }, "the token asks for only what the job does: push the branch, open or edit the PR"
    pr_step = next(s for s in all_steps if "uv_lock_pr.py" in str(s.get("run", "")))
    assert pr_step["env"] == {
        "GH_TOKEN": f"${{{{ steps.{app['id']}.outputs.token }}}}",
        "APP_SLUG": f"${{{{ steps.{app['id']}.outputs.app-slug }}}}",
    }
    assert all_steps.index(app) < all_steps.index(pr_step)
    text = LOCK_UPGRADE.read_text(encoding="utf-8")
    assert "github.token" not in text
    assert "secrets.GITHUB_TOKEN" not in text


def test_mutation_testing_runs_only_when_started_by_hand() -> None:
    """D-048: on demand, never on a schedule or a PR, so a survivor never blocks a merge."""
    workflow = load_yaml(MUTMUT)
    assert set(triggers(workflow)) == {"workflow_dispatch"}
    (job,) = workflow["jobs"].values()
    assert job["runs-on"] == "ubuntu-latest"
    runs = run_lines(workflow)
    assert "uv sync --frozen" in runs
    assert "uv run mutmut run" in runs
    assert "uv run mutmut results" in runs
    assert "GITHUB_STEP_SUMMARY" in runs


def test_terraform_fmt_never_prints_file_contents() -> None:
    """`-diff` would print the gitignored terraform.tfvars, which holds private values (#64)."""
    assert "-diff" not in precommit_hook("terraform-fmt")["entry"].split()
    ci = CI.read_text(encoding="utf-8")
    assert "terraform fmt" in ci, "guards the guard: CI's format step must be found"
    assert all("-diff" not in line for line in ci.splitlines() if "terraform fmt" in line)
