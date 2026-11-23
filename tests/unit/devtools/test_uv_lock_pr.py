"""The weekly uv-lock job acts at most once: run twice, or after any one step fails (#43, D-027).

`open_pr` talks to the world only through `run`, so a fake GitHub stands in for `git` and `gh`.
It can fail any step, and its create can fail *after* opening the PR (a failed API write may
still have happened). The job's token is a GitHub App's (#115, D-049), so the PR's own CI runs:
nothing here ever starts a workflow, and the commit is the App's bot user's.
"""

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from airwatch.devtools import uv_lock_pr
from airwatch.devtools.uv_lock_pr import BRANCH, StepFailedError, open_pr
from tests.project_files import import_roots

LOCK_DIFF = (
    "diff --git a/uv.lock b/uv.lock\n"
    " [[package]]\n"
    '-name = "httpx"\n'
    '+name = "httpx"\n'
    '-version = "0.28.0"\n'
    '+version = "0.28.1"\n'
    ' source = { registry = "https://pypi.org/simple" }\n'
)
SLUG = "pm25-lock-bot"
BOT_ID = "123456789"
STEPS = ("bot-id", "push", "list", "create", "edit")


@dataclass
class FakeGitHub:
    lock_changed: bool = True
    diff_exit: int | None = None
    open_prs: list[int] = field(default_factory=list)
    fail: str | None = None
    create_fails_after_opening: bool = False
    bot_id: str = BOT_ID
    pushes: int = 0
    bodies: list[str] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)

    def _step(self, args: Sequence[str]) -> str:
        cmd = list(args)
        if cmd[:2] == ["git", "push"]:
            return "push"
        if cmd[:3] == ["gh", "api", f"users/{SLUG}[bot]"]:
            return "bot-id"
        if cmd[:3] == ["gh", "pr", "list"]:
            return "list"
        if cmd[:3] == ["gh", "pr", "create"]:
            return "create"
        if cmd[:3] == ["gh", "pr", "edit"]:
            return "edit"
        return "other"

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        cmd = list(args)
        self.calls.append(cmd)
        step = self._step(cmd)
        if step == "create" and self.create_fails_after_opening:
            self.open_prs.append(len(self.open_prs) + 1)
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 502")
        if step == self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        out = ""
        if cmd[:4] == ["git", "diff", "--quiet", "--"]:
            code = self.diff_exit if self.diff_exit is not None else int(self.lock_changed)
            return subprocess.CompletedProcess(cmd, code, "", "")
        if cmd[:2] == ["git", "diff"]:
            out = LOCK_DIFF
        elif step == "bot-id":
            out = self.bot_id + "\n"
        elif step == "push":
            self.pushes += 1
        elif step == "list":
            out = str(self.open_prs[0]) if self.open_prs else ""
        elif step == "create":
            self.open_prs.append(len(self.open_prs) + 1)
            self.bodies.append(cmd[cmd.index("--body") + 1])
        elif step == "edit":
            self.bodies.append(cmd[cmd.index("--body") + 1])
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def heal(self) -> None:
        self.fail = None
        self.create_fails_after_opening = False


def test_no_lockfile_change_pushes_and_opens_nothing() -> None:
    gh = FakeGitHub(lock_changed=False)
    assert open_pr(gh.run, SLUG) == "unchanged"
    assert gh.calls == [["git", "diff", "--quiet", "--", "uv.lock"]]


def test_a_broken_git_is_never_read_as_no_change() -> None:
    """`git diff --quiet` exits 0 (same) or 1 (changed); anything else means git itself failed."""
    gh = FakeGitHub(diff_exit=128)
    with pytest.raises(StepFailedError, match="diff failed \\(exit 128\\)"):
        open_pr(gh.run, SLUG)
    assert gh.calls == [["git", "diff", "--quiet", "--", "uv.lock"]]


def test_a_change_opens_one_pr() -> None:
    gh = FakeGitHub()
    assert open_pr(gh.run, SLUG) == "created"
    assert (gh.open_prs, gh.pushes) == ([1], 1)


def test_no_run_ever_starts_a_workflow() -> None:
    """The App token's own pull_request events run CI (D-049); a dispatch would only add a second
    CI run that the ruleset doesn't count."""
    for gh in (FakeGitHub(), FakeGitHub(open_prs=[4]), FakeGitHub(create_fails_after_opening=True)):
        open_pr(gh.run, SLUG)
        assert not [c for c in gh.calls if c[:2] == ["gh", "workflow"]]
        assert not [c for c in gh.calls if "dispatches" in " ".join(c)]


def test_running_twice_opens_at_most_one_pr() -> None:
    gh = FakeGitHub()
    open_pr(gh.run, SLUG)
    assert open_pr(gh.run, SLUG) == "updated"
    assert gh.open_prs == [1]
    assert gh.pushes == 2


def test_an_existing_open_pr_is_reused() -> None:
    gh = FakeGitHub(open_prs=[7])
    assert open_pr(gh.run, SLUG) == "updated"
    assert gh.open_prs == [7]
    assert ["gh", "pr", "create"] not in [c[:3] for c in gh.calls]


@pytest.mark.parametrize("step", STEPS)
def test_any_one_step_failing_leaves_at_most_one_pr_and_a_rerun_recovers(step: str) -> None:
    gh = FakeGitHub(fail=step, open_prs=[3] if step == "edit" else [])
    with pytest.raises(StepFailedError, match=f"^{step} failed \\(exit 1\\)$"):
        open_pr(gh.run, SLUG)
    assert len(gh.open_prs) <= 1
    gh.heal()
    open_pr(gh.run, SLUG)
    assert len(gh.open_prs) == 1


def test_a_create_that_errors_but_opened_the_pr_is_not_repeated() -> None:
    gh = FakeGitHub(create_fails_after_opening=True)
    assert open_pr(gh.run, SLUG) == "updated"
    assert gh.open_prs == [1]


def test_the_commit_is_the_apps_bot_users() -> None:
    """GitHub links a commit to an account by its noreply email, `<id>+<slug>[bot]@…`."""
    gh = FakeGitHub()
    open_pr(gh.run, SLUG)
    assert ["git", "config", "user.name", f"{SLUG}[bot]"] in gh.calls
    email = f"{BOT_ID}+{SLUG}[bot]@users.noreply.github.com"
    assert ["git", "config", "user.email", email] in gh.calls


def test_a_failed_bot_id_lookup_stops_before_anything_is_committed() -> None:
    gh = FakeGitHub(fail="bot-id")
    with pytest.raises(StepFailedError, match=r"^bot-id failed"):
        open_pr(gh.run, SLUG)
    assert not [c for c in gh.calls if c[:2] in (["git", "commit"], ["git", "push"])]


@pytest.mark.parametrize("bad", ["", "abc", "12 34", "-1", "0"])
def test_a_bot_id_that_is_not_a_positive_number_is_refused(bad: str) -> None:
    """An empty or odd answer would commit as a made-up email that links to nobody."""
    gh = FakeGitHub(bot_id=bad)
    with pytest.raises(StepFailedError, match=r"^bot-id gave no user id$"):
        open_pr(gh.run, SLUG)
    assert gh.pushes == 0


@pytest.mark.parametrize("slug", ["", "Bad Slug", "x[bot]", "a/b"])
def test_a_malformed_app_slug_is_refused_before_any_command(slug: str) -> None:
    gh = FakeGitHub()
    with pytest.raises(StepFailedError, match=r"^app slug is not a GitHub App slug$"):
        open_pr(gh.run, slug)
    assert gh.calls == []


def test_the_pr_body_lists_the_changed_names_and_versions() -> None:
    gh = FakeGitHub()
    open_pr(gh.run, SLUG)
    assert gh.bodies == [
        "## Changed packages\n\n```diff\n"
        '-name = "httpx"\n+name = "httpx"\n-version = "0.28.0"\n+version = "0.28.1"\n'
        "```\n"
    ]


def test_the_commands_in_order() -> None:
    gh = FakeGitHub()
    open_pr(gh.run, SLUG)
    files = ["uv.lock", "requirements/prefect-run.txt", "requirements/watchdog.txt"]
    title = "chore(deps): weekly uv lock --upgrade"
    expected = [
        ["git", "diff", "--quiet", "--", "uv.lock"],
        ["gh", "api", f"users/{SLUG}[bot]", "--jq", ".id"],
        ["gh", "auth", "setup-git"],
        ["git", "config", "user.name", f"{SLUG}[bot]"],
        ["git", "config", "user.email", f"{BOT_ID}+{SLUG}[bot]@users.noreply.github.com"],
        ["git", "switch", "-C", BRANCH],
        ["git", "commit", "--quiet", "-m", title, "--", *files],
        ["git", "push", "--force", "origin", BRANCH],
        ["git", "diff", "HEAD~1", "--", "uv.lock"],
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
        [
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            BRANCH,
            "--title",
            title,
            "--body",
            gh.bodies[0],
        ],
    ]
    assert gh.calls == expected


def test_no_command_carries_a_token() -> None:
    gh = FakeGitHub()
    open_pr(gh.run, SLUG)
    assert not [c for c in gh.calls if any("token" in a.lower() for a in c)]


def test_the_module_needs_only_the_standard_library() -> None:
    roots = import_roots(Path(uv_lock_pr.__file__))
    assert roots, "guards the guard: no imports found"
    assert roots <= set(sys.stdlib_module_names), roots - set(sys.stdlib_module_names)
