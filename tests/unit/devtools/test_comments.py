"""The comment ban and its ratchet (#55, D-037).

Counts code comments per file, compares them with a committed baseline that may only go down,
and refuses comments in any file the baseline doesn't list.
"""

import json
import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from airwatch.devtools.comments import (
    BASELINE,
    SCOPE,
    Problem,
    check,
    count_tree,
    css_comment_lines,
    js_comment_lines,
    main,
    python_comment_lines,
    updated_baseline,
)

ROOT = Path(__file__).resolve().parents[3]
NOT_CODE = {".git", ".venv", ".claude", "notes", "tasks", "docs", "node_modules", "infra"}
CODE_SUFFIXES = {".py", ".js", ".mjs", ".css"}


def test_python_counts_own_line_and_trailing_comments() -> None:
    text = "# one\nx = 1  # two\n\n# three\n# four\ny = '# not a comment'\n"
    assert python_comment_lines(text) == [1, 2, 4, 5]


@pytest.mark.parametrize(
    "line",
    [
        "x = f()  # type: ignore[no-any-return]",
        "import a  # noqa: F401",
        "import a  # noqa",
        "if x:  # pragma: no cover",
        "# fmt: off",
        "# ruff: noqa: E501",
        "#!/usr/bin/env python",
    ],
)
def test_python_tool_pragmas_are_not_comments(line: str) -> None:
    assert python_comment_lines(line + "\n") == []


def test_a_pragma_followed_by_prose_still_counts() -> None:
    assert python_comment_lines("x = 1  # noqa: E501  # because the URL is long\n") == [1]


def test_docstrings_and_strings_are_not_comments() -> None:
    text = '"""Module."""\n\n\ndef f() -> None:\n    """# not a comment either."""\n'
    assert python_comment_lines(text) == []


def test_js_counts_line_and_block_comments() -> None:
    text = "// one\nconst a = 1; // two\n/* three\n   still three */\nconst b = 2;\n"
    assert js_comment_lines(text) == [1, 2, 3]


def test_jsdoc_before_a_declaration_is_a_docstring() -> None:
    text = "/** Does f. */\nfunction f() {}\n\n/**\n * Does g.\n */\nexport const g = 1;\n"
    assert js_comment_lines(text) == []


def test_jsdoc_not_before_a_declaration_counts() -> None:
    text = "f();\n/** a stray note */\nf();\n"
    assert js_comment_lines(text) == [2]


@pytest.mark.parametrize(
    "line",
    [
        'const u = "https://example.com/";',
        "const u = 'a // b';",
        "const u = `a // b ${x} // c`;",
        r"const ok = /^\.?\/(?:[\w.-]+\/?)*$/.test(s);",
        r"if (!/\.\.|\/\//.test(s)) {}",
        "const q = a / b / c;",
        'const s = "say \\"// hi\\"";',
        "const n = 1 + /[//]/.source.length;",
        "const n = a ^ /[//]/.lastIndex;",
        "const ok = /[/]// 2;",
    ],
)
def test_js_strings_regexes_and_division_are_not_comments(line: str) -> None:
    assert js_comment_lines(line + "\n") == []


def test_a_regex_after_return_is_not_a_comment() -> None:
    assert js_comment_lines("function f(s) {\n  return /\\/\\//.test(s);\n}\n") == []


def test_css_counts_block_comments_but_not_strings() -> None:
    text = '/* one */\na { content: "/* not */"; }\nb { c: d; } /* two\n three */\n'
    assert css_comment_lines(text) == [1, 3]


def test_a_file_over_its_baseline_fails() -> None:
    assert check({"src/a.py": 3}, {"src/a.py": 2}) == [
        Problem("src/a.py", "3 comments where the baseline allows 2: delete the new ones")
    ]


def test_a_new_file_with_comments_fails() -> None:
    assert check({"src/new.py": 1}, {}) == [
        Problem("src/new.py", "1 comment where the baseline allows 0: delete the new ones")
    ]


def test_a_file_under_its_baseline_asks_for_the_baseline_to_be_lowered() -> None:
    problems = check({"src/a.py": 1}, {"src/a.py": 2})
    assert [p.path for p in problems] == ["src/a.py"]
    assert "--update" in problems[0].message


def test_a_baseline_entry_for_a_file_now_clean_or_gone_must_be_removed() -> None:
    problems = check({}, {"src/gone.py": 2})
    assert [p.path for p in problems] == ["src/gone.py"]
    assert "--update" in problems[0].message


def test_matching_the_baseline_passes() -> None:
    assert check({"src/a.py": 2, "src/b.py": 0}, {"src/a.py": 2}) == []


def test_update_only_ever_lowers() -> None:
    assert updated_baseline({"src/a.py": 1, "src/b.py": 0}, {"src/a.py": 2, "src/b.py": 1}) == {
        "src/a.py": 1
    }
    with pytest.raises(ValueError, match=re.escape("src/a.py")):
        updated_baseline({"src/a.py": 3}, {"src/a.py": 2})
    with pytest.raises(ValueError, match=re.escape("src/new.py")):
        updated_baseline({"src/new.py": 1}, {})


@given(
    counts=st.dictionaries(st.sampled_from(["a.py", "b.py", "c.py"]), st.integers(0, 5)),
    baseline=st.dictionaries(st.sampled_from(["a.py", "b.py", "c.py"]), st.integers(1, 5)),
)
def test_the_ratchet_never_raises_an_allowance(
    counts: dict[str, int], baseline: dict[str, int]
) -> None:
    try:
        new = updated_baseline(counts, baseline)
    except ValueError:
        assert any(n > baseline.get(p, 0) for p, n in counts.items())
        return
    assert all(0 < n <= baseline[p] for p, n in new.items())
    assert check(counts, new) == []


def test_count_tree_reads_every_scoped_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1  # c\n", encoding="utf-8")
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "a.js").write_text("// c\n", encoding="utf-8")
    (tmp_path / "site" / "a.css").write_text("/* c */\n", encoding="utf-8")
    (tmp_path / "site" / "a.html").write_text("<!-- out of scope -->\n", encoding="utf-8")
    assert count_tree(tmp_path) == {"site/a.css": 1, "site/a.js": 1, "src/a.py": 1}


def test_every_folder_with_code_is_in_scope() -> None:
    folders = {
        p.relative_to(ROOT).parts[0]
        for p in ROOT.rglob("*")
        if p.suffix in CODE_SUFFIXES
        and len(p.relative_to(ROOT).parts) > 1
        and p.relative_to(ROOT).parts[0] not in NOT_CODE
        and not p.relative_to(ROOT).parts[0].startswith(".")
        and "__pycache__" not in p.parts
    }
    assert {"src", "scripts", "tests", "site"} <= folders, "discovery broke: nothing to guard"
    assert folders <= set(SCOPE), f"code outside the comment ban: {sorted(folders - set(SCOPE))}"


def test_the_repository_keeps_to_its_baseline() -> None:
    baseline = json.loads((ROOT / BASELINE).read_text(encoding="utf-8"))
    assert check(count_tree(ROOT), baseline) == []


def test_main_reports_problems_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# c\n", encoding="utf-8")
    (tmp_path / BASELINE).write_text("{}\n", encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    assert "src/a.py" in capsys.readouterr().out


def test_main_update_lowers_and_then_passes(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# c\n", encoding="utf-8")
    (tmp_path / BASELINE).write_text('{"src/a.py": 3}\n', encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    assert main(["--root", str(tmp_path), "--update"]) == 0
    assert json.loads((tmp_path / BASELINE).read_text(encoding="utf-8")) == {"src/a.py": 1}
    assert main(["--root", str(tmp_path)]) == 0


def test_main_update_refuses_to_raise(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# c\n# d\n", encoding="utf-8")
    (tmp_path / BASELINE).write_text('{"src/a.py": 1}\n', encoding="utf-8")
    assert main(["--root", str(tmp_path), "--update"]) == 1
    assert json.loads((tmp_path / BASELINE).read_text(encoding="utf-8")) == {"src/a.py": 1}
