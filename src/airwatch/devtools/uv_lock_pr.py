"""Push the weekly lockfile upgrade, and open or reuse its one PR (#43, D-027, D-049).

`.github/workflows/uv-lock-upgrade.yml` runs `uv lock --upgrade` and the two exports, then this
file by path, with no project installed: it needs only the standard library.

At most once, run twice or after any one step fails:

- one fixed branch, force-pushed, and at most one open PR on it, found by listing first;
- a create that errors is checked by listing again, since a failed write may still have
  happened; a PR found then is reused;
- with no lockfile change, nothing is pushed or opened.

The token is a GitHub App's installation token (#115, D-049), so the PR's own `pull_request` CI
runs with no one approving it, and nothing here starts a workflow. The commit is the App's bot
user's: its noreply email carries the user id, looked up before anything is committed.

`gh` reads its token from `GH_TOKEN` and acts as git's credential helper, so no token is ever
an argument, a URL or in the git config.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

BRANCH = "deps/uv-lock-upgrade"
TITLE = "chore(deps): weekly uv lock --upgrade"
FILES = ("uv.lock", "requirements/prefect-run.txt", "requirements/watchdog.txt")
APP_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
USER_ID = re.compile(r"^[1-9][0-9]*$")
CHANGED_LINE = re.compile(r"^[-+](name|version) = ")

Run = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
Outcome = Literal["unchanged", "created", "updated"]


class StepFailedError(RuntimeError):
    """A step's command exited non-zero. The message names the step and exit code, no output."""


def _real_run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:  # pragma: no cover
    return subprocess.run(list(args), capture_output=True, text=True, check=False)  # noqa: S603  (fixed git/gh arguments)


def _ok(run: Run, step: str, args: Sequence[str]) -> str:
    result = run(args)
    if result.returncode != 0:
        raise StepFailedError(f"{step} failed (exit {result.returncode})")
    return result.stdout


def lock_changed(run: Run) -> bool:
    result = run(["git", "diff", "--quiet", "--", "uv.lock"])
    if result.returncode not in (0, 1):
        raise StepFailedError(f"diff failed (exit {result.returncode})")
    return result.returncode == 1


def pr_body(lock_diff: str) -> str:
    changed = "".join(f"{ln}\n" for ln in lock_diff.splitlines() if CHANGED_LINE.match(ln))
    return f"## Changed packages\n\n```diff\n{changed}```\n"


def _open_pr(run: Run) -> str | None:
    out = _ok(
        run,
        "list",
        [
            "gh",
            "pr",
            "list",
            "--head",
            BRANCH,
            "--state",
            "open",
            "--json",
            "number",
            "--jq",
            ".[0].number // empty",
        ],
    )
    return out.strip() or None


def _bot_identity(run: Run, app_slug: str) -> tuple[str, str]:
    name = f"{app_slug}[bot]"
    user_id = _ok(run, "bot-id", ["gh", "api", f"users/{name}", "--jq", ".id"]).strip()
    if not USER_ID.match(user_id):
        raise StepFailedError("bot-id gave no user id")
    return name, f"{user_id}+{name}@users.noreply.github.com"


def open_pr(run: Run, app_slug: str) -> Outcome:
    """One run of the job's last step. Raises StepFailedError when a step fails."""
    if not APP_SLUG.match(app_slug):
        raise StepFailedError("app slug is not a GitHub App slug")
    if not lock_changed(run):
        return "unchanged"
    name, email = _bot_identity(run, app_slug)
    _ok(run, "setup-git", ["gh", "auth", "setup-git"])
    _ok(run, "config", ["git", "config", "user.name", name])
    _ok(run, "config", ["git", "config", "user.email", email])
    _ok(run, "switch", ["git", "switch", "-C", BRANCH])
    _ok(run, "commit", ["git", "commit", "--quiet", "-m", TITLE, "--", *FILES])
    _ok(run, "push", ["git", "push", "--force", "origin", BRANCH])
    body = pr_body(_ok(run, "diff", ["git", "diff", "HEAD~1", "--", "uv.lock"]))

    outcome: Outcome = "updated"
    pr = _open_pr(run)
    if pr is None:
        created = run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                BRANCH,
                "--title",
                TITLE,
                "--body",
                body,
            ]
        )
        if created.returncode == 0:
            outcome = "created"
        else:
            pr = _open_pr(run)
            if pr is None:
                raise StepFailedError(f"create failed (exit {created.returncode})")
    if pr is not None:
        _ok(run, "edit", ["gh", "pr", "edit", pr, "--body", body])
    return outcome


SUMMARY = {
    "unchanged": "uv.lock is already up to date.",
    "created": f"Opened the PR on `{BRANCH}`; its own CI runs.",
    "updated": f"Updated the open PR on `{BRANCH}`; its own CI runs.",
}


def main() -> int:  # pragma: no cover  (the workflow's edge)
    try:
        outcome = open_pr(_real_run, os.environ.get("APP_SLUG", ""))
    except StepFailedError as exc:
        print(f"uv-lock PR: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    line = SUMMARY[outcome]
    print(line)  # noqa: T201
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
