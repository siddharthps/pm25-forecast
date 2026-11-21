"""The docs rules (T11, D-022): no hand-typed numbers, macros that resolve, a length cap.

Every number in `docs/` comes from `results/results.json` through a macro such as
`{{ results.design.variants }}`. Outside macros, a digit is allowed only as part of a listed
literal: an ISO date, a year from 1900 to 2099, a clock time (`06:00`), a decision or task ID
(`D-008`, `T12b`), an issue number (`#18`), `PM2.5`, `PM10`, `D+1`, a version with a leading `v`,
an ordered-list marker, or a link target. Code blocks, inline code and HTML comments are checked
like prose.

Each macro's `results.…` path must exist in the file (a null placeholder counts), and each page
stays under its word cap.

Run `python -m airwatch.devtools.docs_check` from the project folder.
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DOCS = "docs"
RESULTS = "results/results.json"
DEFAULT_MAX_WORDS = 1000
MAX_WORDS: dict[str, int] = {"index.md": 400}

MACRO = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
REF = re.compile(r"\bresults\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
LINK_TARGET = re.compile(r"\]\([^)\s]*\)|<https?://[^>\s]+>|https?://\S+")
ALLOWED = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|(?<![\d.,])\b(?:19|20)\d{2}\b(?![\d.,]\d)"
    r"|\b(?:[01]\d|2[0-3]):[0-5]\d\b"
    r"|\bD-\d{3}\b"
    r"|\bT\d+[a-z]?\b"
    r"|#\d+\b"
    r"|\bPM(?:2\.5|10)\b"
    r"|\bD\+\d\b"
    r"|\bv\d+(?:\.\d+)*\b"
    r"|^[ \t]*\d+[.)](?=[ \t])",
    re.MULTILINE,
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
WORD = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*")


@dataclass(frozen=True, order=True)
class Problem:
    path: str
    message: str


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def prose_numbers(text: str) -> list[tuple[int, str]]:
    stripped = text
    for pattern in (MACRO, LINK_TARGET, ALLOWED):
        stripped = pattern.sub(_blank, stripped)
    return [(_line(stripped, m.start()), m.group(0)) for m in NUMBER.finditer(stripped)]


def macro_refs(text: str) -> list[tuple[int, str]]:
    return [
        (_line(text, macro.start()), ref.group(1))
        for macro in MACRO.finditer(text)
        for ref in REF.finditer(macro.group(0))
    ]


def word_count(text: str) -> int:
    return len(WORD.findall(LINK_TARGET.sub(" ", MACRO.sub(" ", text))))


def _resolves(results: object, dotted: str) -> bool:
    node = results
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def check_page(name: str, text: str, results: object) -> list[str]:
    messages = [
        f"line {line}: typed number '{number}' (use a macro from {Path(RESULTS).name})"
        for line, number in prose_numbers(text)
    ]
    messages += [
        f"line {line}: '{ref}' is not in {RESULTS}"
        for line, ref in macro_refs(text)
        if not _resolves(results, ref)
    ]
    cap = MAX_WORDS.get(name, DEFAULT_MAX_WORDS)
    words = word_count(text)
    if words > cap:
        messages.append(f"{words} words, over the cap of {cap}")
    return messages


def check(root: Path) -> list[Problem]:
    results = json.loads((root / RESULTS).read_text(encoding="utf-8"))
    docs = root / DOCS
    problems = []
    for page in sorted(docs.rglob("*.md")):
        name = page.relative_to(docs).as_posix()
        for message in check_page(name, page.read_text(encoding="utf-8"), results):
            problems.append(Problem(f"{DOCS}/{name}", message))
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    problems = check(args.root)
    for problem in problems:
        print(f"{problem.path}: {problem.message}")  # noqa: T201
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
