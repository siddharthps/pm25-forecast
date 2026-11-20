"""The comment ban, enforced by a ratchet (#55, D-037).

Code comments are counted per file in the scoped folders and compared with a committed
baseline (`comment-baseline.json`). A file may never have more comments than the baseline
allows, and a file missing from it may have none. When comments are deleted the baseline must
be lowered to match (`--update`, which refuses to raise anything), so the allowance only ever
goes down.

Not counted: docstrings (Python) and JSDoc blocks directly before a declaration, tool pragmas
(`# type: ignore`, `# noqa`, `# pragma: no cover`, `# fmt:`, `# ruff:`, `# mypy:`), a first-line
shebang or coding line, and config files, which are out of scope (D-037).

Run `python -m airwatch.devtools.comments` to check, `--update` to lower the baseline.
"""

import argparse
import io
import json
import re
import sys
import tokenize
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

BASELINE = "comment-baseline.json"
SCOPE: dict[str, tuple[str, ...]] = {
    "src": (".py",),
    "scripts": (".py",),
    "tests": (".py", ".mjs"),
    "site": (".js", ".css"),
}
SKIP_PARTS = frozenset({"__pycache__", "node_modules"})

PRAGMA = re.compile(
    r"^#\s*(?:type:\s*ignore|noqa\b|pragma:|fmt:\s*(?:on|off|skip)|ruff:|mypy:|pyright:)[^#]*$"
)
CODING = re.compile(r"^#.*coding[:=]")
DECLARATION = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|const|let|var|class)\b")
REGEX_AFTER_CHAR = frozenset("(,=:[!&|?{};+-*%<>~^")
REGEX_AFTER_WORD = frozenset(
    {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw"}
    | {"instanceof", "yield", "await"}
)


@dataclass(frozen=True, order=True)
class Problem:
    path: str
    message: str


def python_comment_lines(text: str) -> list[int]:
    lines = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT or PRAGMA.match(tok.string):
            continue
        row = tok.start[0]
        if row <= 2 and (tok.string.startswith("#!") or CODING.match(tok.string)):  # noqa: PLR2004
            continue
        lines.append(row)
    return lines


def _skip_string(text: str, i: int, quote: str) -> int:
    i += 1
    while i < len(text) and text[i] != quote:
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _skip_regex(text: str, i: int) -> int:
    i += 1
    in_class = False
    while i < len(text) and text[i] != "\n":
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return i + 1
        i += 1
    return i


def _regex_allowed(text: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0 or text[j] in REGEX_AFTER_CHAR:
        return True
    end = j + 1
    while j >= 0 and (text[j].isalnum() or text[j] in "_$"):
        j -= 1
    return text[j + 1 : end] in REGEX_AFTER_WORD


def _is_jsdoc(text: str, start: int, end: int) -> bool:
    if not text.startswith("/**", start) or text.startswith("/**/", start):
        return False
    rest = text[end:].lstrip("\r\n\t ")
    return bool(DECLARATION.match(rest))


class _Scanner:
    """Walks JS or CSS source, skipping strings, template literals and regex literals."""

    def __init__(self, text: str, *, js: bool) -> None:
        self.text = text
        self.js = js
        self.lines: list[int] = []
        self.braces: list[int] = []
        self.in_template = False

    def run(self) -> list[int]:
        i = 0
        while i < len(self.text):
            i = self._template(i) if self.in_template else self._code(i)
        return self.lines

    def _line(self, i: int) -> int:
        return self.text.count("\n", 0, i) + 1

    def _template(self, i: int) -> int:
        text = self.text
        if text[i] == "\\":
            return i + 2
        if text[i] == "`":
            self.in_template = False
            return i + 1
        if text.startswith("${", i):
            self.braces.append(0)
            self.in_template = False
            return i + 2
        return i + 1

    def _code(self, i: int) -> int:
        text, ch = self.text, self.text[i]
        if text.startswith("/*", i):
            return self._block_comment(i)
        if ch in "\"'":
            return _skip_string(text, i, ch)
        if not self.js:
            return i + 1
        if text.startswith("//", i):
            self.lines.append(self._line(i))
            end = text.find("\n", i)
            return len(text) if end < 0 else end
        if ch == "`":
            self.in_template = True
        elif ch == "/" and _regex_allowed(text, i):
            return _skip_regex(text, i)
        elif ch in "{}" and self.braces:
            self._brace(ch)
        return i + 1

    def _block_comment(self, i: int) -> int:
        end = self.text.find("*/", i + 2)
        end = len(self.text) if end < 0 else end + 2
        if not (self.js and _is_jsdoc(self.text, i, end)):
            self.lines.append(self._line(i))
        return end

    def _brace(self, ch: str) -> None:
        if ch == "{":
            self.braces[-1] += 1
        elif self.braces[-1] == 0:
            self.braces.pop()
            self.in_template = True
        else:
            self.braces[-1] -= 1


def _scan_c_style(text: str, *, js: bool) -> list[int]:
    return _Scanner(text, js=js).run()


def js_comment_lines(text: str) -> list[int]:
    return _scan_c_style(text, js=True)


def css_comment_lines(text: str) -> list[int]:
    return _scan_c_style(text, js=False)


COUNTERS: dict[str, Callable[[str], list[int]]] = {
    ".py": python_comment_lines,
    ".js": js_comment_lines,
    ".mjs": js_comment_lines,
    ".css": css_comment_lines,
}


def count_tree(root: Path) -> dict[str, int]:
    counts = {}
    for folder, suffixes in SCOPE.items():
        for path in sorted((root / folder).rglob("*")):
            if path.suffix not in suffixes or SKIP_PARTS & set(path.parts) or not path.is_file():
                continue
            n = len(COUNTERS[path.suffix](path.read_text(encoding="utf-8")))
            if n:
                counts[path.relative_to(root).as_posix()] = n
    return counts


def check(counts: dict[str, int], baseline: dict[str, int]) -> list[Problem]:
    problems = []
    for path in sorted(counts.keys() | baseline.keys()):
        n, allowed = counts.get(path, 0), baseline.get(path, 0)
        if n > allowed:
            noun = "comment" if n == 1 else "comments"
            message = f"{n} {noun} where the baseline allows {allowed}: delete the new ones"
            problems.append(Problem(path, message))
        elif n < allowed:
            problems.append(
                Problem(
                    path,
                    f"{n} left where the baseline allows {allowed}: lower it with "
                    "`uv run python -m airwatch.devtools.comments --update`",
                )
            )
    return problems


def updated_baseline(counts: dict[str, int], baseline: dict[str, int]) -> dict[str, int]:
    over = sorted(p for p, n in counts.items() if n > baseline.get(p, 0))
    if over:
        raise ValueError(f"the baseline never goes up; over it: {', '.join(over)}")
    return {p: n for p, n in sorted(counts.items()) if n > 0}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--update", action="store_true", help="lower the baseline to match")
    args = parser.parse_args(argv)
    path = args.root / BASELINE
    baseline: dict[str, int] = json.loads(path.read_text(encoding="utf-8"))
    counts = count_tree(args.root)
    if args.update:
        try:
            new = updated_baseline(counts, baseline)
        except ValueError as exc:
            print(exc)  # noqa: T201
            return 1
        path.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"{BASELINE}: {sum(new.values())} comments allowed in {len(new)} files")  # noqa: T201
        return 0
    problems = check(counts, baseline)
    for problem in problems:
        print(f"{problem.path}: {problem.message}")  # noqa: T201
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
