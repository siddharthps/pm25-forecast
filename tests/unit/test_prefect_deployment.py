"""The Prefect deployment's rules, read from prefect.yaml (#15, T8; D-011, D-019, D-040).

The schedule is the frozen issue time; a scheduled run publishes and a manual one doesn't; the
run installs exactly what uv.lock says; no secret is in the file; at most 5 deployments.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from airwatch.flows import daily
from airwatch.timeutil import ISSUE_HOUR_LOCAL, ISSUE_TZ

ROOT = Path(__file__).resolve().parents[2]
PREFECT_YAML = ROOT / "prefect.yaml"
REQUIREMENTS = ROOT / "requirements" / "prefect-run.txt"
EXPORT = [
    "uv",
    "export",
    "--frozen",
    "--no-dev",
    "--no-emit-project",
    "--no-header",
    "--format",
    "requirements.txt",
]
HOBBY_DEPLOYMENTS = 5


def _config() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(PREFECT_YAML.read_text(encoding="utf-8"))
    return loaded


def _daily() -> dict[str, Any]:
    found = [d for d in _config()["deployments"] if d["name"] == "daily-forecast"]
    assert len(found) == 1
    deployment: dict[str, Any] = found[0]
    return deployment


def _env() -> dict[str, str]:
    env: dict[str, str] = _daily()["work_pool"]["job_variables"]["env"]
    return env


def _steps(name: str) -> list[dict[str, Any]]:
    return [step[name] for step in _config()["pull"] if name in step]


def test_deployments_stay_within_the_hobby_plan() -> None:
    assert 1 <= len(_config()["deployments"]) <= HOBBY_DEPLOYMENTS


def test_the_schedule_is_the_frozen_issue_time() -> None:
    schedules = _daily()["schedules"]
    assert len(schedules) == 1
    assert schedules[0]["cron"] == f"0 {ISSUE_HOUR_LOCAL} * * *"
    assert schedules[0]["timezone"] == str(ISSUE_TZ)
    assert schedules[0]["active"] is True


def test_only_the_schedule_publishes() -> None:
    """A manual run uses the deployment's parameters: a dry run (the owner's rule)."""
    deployment = _daily()
    assert deployment.get("parameters", {}).get("publish", False) is False
    assert deployment["schedules"][0]["parameters"] == {"publish": True}


def test_the_entrypoint_is_the_thin_flow() -> None:
    path, _, name = _daily()["entrypoint"].partition(":")
    assert (ROOT / path).resolve() == Path(daily.__file__).resolve()
    assert getattr(daily, name).name == "daily-forecast"


def test_it_runs_on_the_managed_pool() -> None:
    assert _daily()["work_pool"]["name"] == "managed-pool"


def test_code_comes_from_this_repository_main_branch() -> None:
    clones = _steps("prefect.deployments.steps.git_clone")
    assert clones == [
        {
            "id": "clone",
            "repository": "https://github.com/siddharthps/pm25-forecast.git",
            "branch": "main",
        }
    ]


def test_dependencies_come_from_the_lock_export_then_the_package_alone() -> None:
    installs = _steps("prefect.deployments.steps.pip_install_requirements")
    assert installs == [
        {"directory": "{{ clone.directory }}", "requirements_file": "requirements/prefect-run.txt"}
    ]
    scripts = _steps("prefect.deployments.steps.run_shell_script")
    assert [s["script"] for s in scripts] == ["pip install --no-deps {{ clone.directory }}"]
    names = [next(iter(step)) for step in _config()["pull"]]
    assert names == [
        "prefect.deployments.steps.git_clone",
        "prefect.deployments.steps.pip_install_requirements",
        "prefect.deployments.steps.run_shell_script",
    ]


def test_the_requirements_file_matches_uv_lock() -> None:
    uv = shutil.which("uv")
    assert uv, "uv must be on PATH"
    out = subprocess.run(
        [uv, *EXPORT[1:]], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert REQUIREMENTS.read_text(encoding="utf-8") == out, (
        "regenerate: " + " ".join(EXPORT) + " > requirements/prefect-run.txt"
    )


def test_every_requirement_is_pinned_and_hashed() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==\S+", text, flags=re.MULTILINE)
    assert "prefect" in pins and "pandas" in pins
    assert "airwatch" not in pins
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text.strip())
    assert all("--hash=sha256:" in b for b in blocks)


def test_no_secret_value_is_in_the_deployment() -> None:
    text = PREFECT_YAML.read_text(encoding="utf-8")
    env = _env()
    assert env, "guards the guard: the env must be found where Prefect reads it"
    assert not {k for k in env if re.search(r"KEY|SECRET|TOKEN|PASSWORD|EMAIL", k)}
    assert "AKIA" not in text
    assert "prefect.blocks.secret" not in text, "resolved at deploy time and stored: load at run"


def test_our_own_logs_reach_prefect() -> None:
    env = _env()
    assert env["PREFECT_LOGGING_EXTRA_LOGGERS"] == "airwatch"


def test_the_weekly_lock_upgrade_regenerates_the_requirements_too() -> None:
    """Otherwise the lock job's own PR would fail the drift test above."""
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "uv-lock-upgrade.yml").read_text(encoding="utf-8")
    )
    runs = [str(s.get("run", "")) for job in workflow["jobs"].values() for s in job["steps"]]
    upgrade = next(i for i, r in enumerate(runs) if r.strip() == "uv lock --upgrade")
    assert runs[upgrade + 1].strip() == " ".join(EXPORT) + " > requirements/prefect-run.txt"
    assert any("-- uv.lock requirements/prefect-run.txt" in r for r in runs)


def test_the_image_pins_the_projects_python() -> None:
    """D-026: the run uses the Python we test on, never Prefect's moving default."""
    python = ".".join((ROOT / ".python-version").read_text(encoding="utf-8").split(".")[:2])
    image = _daily()["work_pool"]["job_variables"]["image"]
    assert image == f"prefecthq/prefect:3-python{python}"


def test_a_hung_run_is_stopped_within_30_minutes() -> None:
    """The pool's default is 24 h: one hung run could burn ~1,440 of the 500 free minutes (#63)."""
    assert _daily()["work_pool"]["job_variables"]["timeout"] <= 1800
