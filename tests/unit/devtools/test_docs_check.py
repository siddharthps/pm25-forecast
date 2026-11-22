"""The docs rules (T11, D-022): no hand-typed numbers, macros that resolve, a length cap.

Every number in `docs/` prose comes from `results/results.json` through a macro. A digit outside
a macro fails, unless it is an allow-listed literal (dates, years, decision and task IDs, issue
numbers, versions, list markers, link targets). A macro that names a key missing from the file
fails, and so does a page longer than its cap.
"""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from airwatch.devtools.docs_check import (
    DEFAULT_MAX_WORDS,
    MAX_WORDS,
    Problem,
    check,
    macro_refs,
    main,
    prose_numbers,
    word_count,
)

ROOT = Path(__file__).resolve().parents[3]


def _numbers(text: str) -> list[str]:
    return [n for _, n in prose_numbers(text)]


def test_a_typed_number_is_found_with_its_line() -> None:
    assert prose_numbers("# Title\n\nThe model's MAE was 4.2 here.\n") == [(3, "4.2")]


@pytest.mark.parametrize(
    "text",
    [
        "MAE {{ results.headline.mae }} on the test.",
        "{{ results.design.variants | show }} variants.",
        "{% if results.headline.mae %}x{% endif %}",
        "Develop on 2009\u20132024, test on 2025.",
        "The first forecast was for 2026-11-22.",
        "Issued at 06:00 and checked at 23:59.",
        "Settled in D-008 and D-016, built in T11 and T12b (#18).",
        "Fine particles (PM2.5) and PM10, forecast for D+1.",
        "Built with Zensical v0.1.3.",
        "1. First step\n2. Second step\n",
        "See [the issue](https://github.com/o/r/issues/18) and <https://example.com/a1>.",
        "Read [D-008](https://example.com/x#d-008-2026-11-18).",
        "Concentrations in µg/m³.",
    ],
)
def test_allowed_literals_and_macros_pass(text: str) -> None:
    assert _numbers(text) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Six variants, 6 of them.", ["6"]),
        ("An MAE of 4.20 µg/m³.", ["4.20"]),
        ("It beat persistence by 12%.", ["12"]),
        ("```text\nscore 3\n```\n", ["3"]),
        ("Inline `n=7` code.", ["7"]),
        ("<!-- 42 -->", ["42"]),
        ("Version 0.1.3 without a v.", ["0.1.3"]),
        ("In 1999 and 3000.", ["3000"]),
        ("A ratio of 3:2 or 24:00.", ["3", "2", "24", "00"]),
        ("A 1,000 word page.", ["1,000"]),
    ],
)
def test_numbers_outside_macros_fail(text: str, found: list[str]) -> None:
    assert _numbers(text) == found


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("MAE was {{ 4.2 }} here.", ["4.2"]),
        ("{{ results.headline.mae or 3 }}", ["3"]),
        ("{% if results.headline.mae > 5 %}y{% endif %}", ["5"]),
        ('{{ "%.1f" | format(results.headline.mae) }}', ["1"]),
        ("{# a note with 12 in it #}", ["12"]),
    ],
)
def test_numbers_typed_inside_a_macro_fail(text: str, found: list[str]) -> None:
    assert _numbers(text) == found


@pytest.mark.parametrize(
    "text",
    [
        "{{ results.items[3] }}",
        "{{ results.design.ci_level }}%",
        "{{ results.test_vs.cams.ci_low }} to {{ results.test_vs.cams.ci_high }}",
    ],
)
def test_results_paths_inside_macros_pass(text: str) -> None:
    assert _numbers(text) == []


@given(
    n=st.integers(min_value=0, max_value=10**9).filter(lambda n: not 1900 <= n <= 2099),
    before=st.sampled_from(["The MAE was ", "About ", "(", "— "]),
    after=st.sampled_from([" µg/m³.", " days", ")", "% better."]),
)
def test_any_typed_integer_fails_and_the_same_inside_a_macro_passes(
    n: int, before: str, after: str
) -> None:
    assert _numbers(f"{before}{n}{after}") == [str(n)]
    assert _numbers(f"{before}{{{{ results.x[{n}] }}}}{after}") == []


@given(
    year=st.integers(min_value=1900, max_value=2099),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
)
def test_every_iso_date_and_year_is_allowed(year: int, month: int, day: int) -> None:
    assert _numbers(f"On {year}-{month:02d}-{day:02d}, in {year}.") == []


def test_macro_refs_name_the_dotted_paths() -> None:
    text = "{{ results.headline.mae }} and {{ results.design.variants | show }}, {{ other }}"
    assert macro_refs(text) == [(1, "headline.mae"), (1, "design.variants")]


def test_word_count_skips_macros_and_markup() -> None:
    assert word_count("# A title\n\nTwo words {{ results.a.b }} here.\n") == 5


def _site(tmp_path: Path, pages: dict[str, str], results: object) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "results.json").write_text(json.dumps(results), encoding="utf-8")
    for name, text in pages.items():
        (tmp_path / "docs" / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_check_reports_numbers_missing_keys_and_long_pages(tmp_path: Path) -> None:
    long_page = "word " * (DEFAULT_MAX_WORDS + 1)
    root = _site(
        tmp_path,
        {
            "a.md": "Fine: {{ results.design.variants }}.\nTyped: 7.\n",
            "b.md": "Missing: {{ results.design.nope }}.\n",
            "c.md": long_page,
        },
        {"design": {"variants": 6}},
    )
    assert check(root) == [
        Problem("docs/a.md", "line 2: typed number '7' (use a macro from results.json)"),
        Problem("docs/b.md", "line 1: 'design.nope' is not in results/results.json"),
        Problem("docs/c.md", f"{DEFAULT_MAX_WORDS + 1} words, over the cap of {DEFAULT_MAX_WORDS}"),
    ]


def test_null_placeholders_resolve(tmp_path: Path) -> None:
    root = _site(
        tmp_path, {"a.md": "{{ results.headline.mae | show }}"}, {"headline": {"mae": None}}
    )
    assert check(root) == []


def test_main_returns_one_on_problems_and_zero_when_clean(tmp_path: Path) -> None:
    root = _site(tmp_path, {"a.md": "Typed 7."}, {})
    assert main(["--root", str(root)]) == 1
    (root / "docs" / "a.md").write_text("Clean.", encoding="utf-8")
    assert main(["--root", str(root)]) == 0


def test_the_bottom_line_is_capped_at_one_page() -> None:
    assert MAX_WORDS["index.md"] < DEFAULT_MAX_WORDS


def test_the_real_docs_pass() -> None:
    assert check(ROOT) == []
