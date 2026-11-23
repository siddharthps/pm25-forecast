"""Read the repository's own config files for the guardrail tests (#103): one copy of each loader.

PyYAML reads a workflow's `on:` key as the boolean `True`, so `triggers` looks under both; a loader
that forgot would find no triggers and let a trigger rule pass vacuously. A pre-commit hook is
looked up by id and must appear exactly once, so a duplicated hook can't hide behind the first.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"

_UV_EXPORT = ["uv", "export", "--frozen"]
_UV_FORMAT = ["--no-emit-project", "--no-header", "--format", "requirements.txt"]
PREFECT_EXPORT = [*_UV_EXPORT, "--no-dev", *_UV_FORMAT]
WATCHDOG_EXPORT = [*_UV_EXPORT, "--only-group", "watchdog", *_UV_FORMAT]


def load_yaml(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} is not a YAML mapping"
    return data


def workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def workflow(name: str) -> dict[Any, Any]:
    return load_yaml(WORKFLOWS / name)


def triggers(wf: dict[Any, Any]) -> dict[str, Any]:
    found = wf.get("on", wf.get(True))
    assert isinstance(found, dict), "triggers must be a mapping"
    return found


def steps(wf: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in wf["jobs"].values() for step in job.get("steps", [])]


def run_lines(wf: dict[Any, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in steps(wf))


def precommit_hook(hook_id: str) -> dict[str, Any]:
    """The one hook with `hook_id`, with its repo's URL under "repo"."""
    found = [
        {**hook, "repo": repo["repo"]}
        for repo in load_yaml(PRE_COMMIT)["repos"]
        for hook in repo["hooks"]
        if hook["id"] == hook_id
    ]
    assert len(found) == 1, f"exactly one {hook_id!r} hook in .pre-commit-config.yaml"
    return found[0]


def uv_export(command: list[str]) -> str:
    """What `command` (one of the *_EXPORT lists) prints now, run from the project folder."""
    uv = shutil.which("uv")
    assert uv, "uv must be on PATH"
    done = subprocess.run([uv, *command[1:]], cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout
