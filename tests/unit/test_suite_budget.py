"""The suite's time limit (#83, D-046): a run longer than `SUITE_BUDGET_S` seconds fails.

CI sets the limit at 75 s, about 1.45 times its slowest run seen (52 s): shared runners vary
too much for 30 s. Unset, as on the owner's PC, nothing is timed. The plugin runs here inside
a small inner pytest session.
"""

from pathlib import Path

import pytest
import yaml

from tests.suite_budget import ENV

ROOT = Path(__file__).resolve().parents[2]

SLOW = "import time\n\ndef test_slow():\n    time.sleep(0.2)\n"
FAILING = "import time\n\ndef test_slow_and_wrong():\n    time.sleep(0.2)\n    assert False\n"


def _run(pytester: pytest.Pytester, body: str) -> pytest.RunResult:
    pytester.makepyfile(body)
    return pytester.runpytest_inprocess("-p", "tests.suite_budget", "-p", "no:cacheprovider")


def test_without_a_budget_nothing_is_timed(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV, raising=False)
    assert _run(pytester, SLOW).ret == pytest.ExitCode.OK


def test_a_run_within_the_budget_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV, "60")
    assert _run(pytester, SLOW).ret == pytest.ExitCode.OK


def test_a_run_over_the_budget_fails_and_says_why(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV, "0.05")
    result = _run(pytester, SLOW)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*over its budget of 0.05 s*SUITE_BUDGET_S*"])


def test_being_over_budget_never_hides_a_failure(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV, "0.05")
    assert _run(pytester, FAILING).ret == pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize("raw", ["", "fast", "0", "-5", "nan", "inf"])
def test_a_bad_budget_is_a_usage_error(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(ENV, raw)
    assert _run(pytester, SLOW).ret == pytest.ExitCode.USAGE_ERROR


def test_ci_runs_the_core_suite_with_the_75_s_budget() -> None:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = [s for job in ci["jobs"].values() for s in job.get("steps", [])]
    core = [s for s in steps if s.get("name") == "Core tests with coverage"]
    assert len(core) == 1
    assert core[0].get("env", {}).get(ENV) == "75"


def test_the_plugin_is_loaded_for_every_run() -> None:
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert '"tests.suite_budget"' in conftest
