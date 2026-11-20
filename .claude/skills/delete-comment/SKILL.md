---
name: delete-comment
description: Audits code comments in this repository and removes them under the D-037 comment ban. Sorts each comment as Tautology, Stale, Excuse or Decision record, then deletes it, files an issue, or records it in notes/DECISIONS.md, and lowers the comment-baseline.json ratchet. Use when the comment-ban check fails, when comment-baseline.json still allows comments, or when asked to "delete comments", "run the comment audit" or "/delete-comment" for a file or folder.
---

# Delete comments (D-037)

Code in this repository carries no comments. `airwatch.devtools.comments` enforces it against
`comment-baseline.json`, a per-file allowance that only goes down. This skill is the process
for getting a file's count to zero without losing anything a comment knew.

## Scope

Counted (D-037): Python `#` comments in `src/`, `scripts/`, `tests/`; JS and CSS comments in
`site/` and `tests/site/`.

Not counted, so leave them: docstrings, JSDoc directly before a declaration, tool pragmas
(`# type: ignore`, `# noqa`, `# pragma: no cover`, `# fmt:`, `# ruff:`, `# mypy:`), and config
files. A pragma followed by prose counts: keep the pragma, sort the prose.

## Steps

1. **List the comments.** Find what's counted, with line numbers:

   ```bash
   uv run python -m airwatch.devtools.comments          # which files are over or under
   uv run python -c "from pathlib import Path; from airwatch.devtools.comments import COUNTERS; \
   p = Path('FILE'); print(COUNTERS[p.suffix](p.read_text(encoding='utf-8')))"
   ```

   Read each comment with the code around it. A run of own-line comments is one comment.

2. **Sort each one into exactly one kind,** and write the list (path, line, kind, action,
   note) as a dated TSV in `notes/`, like `notes/comment-audit-2026-11-20.tsv`:

   | Kind | Test | Action |
   | --- | --- | --- |
   | Tautology | The names, types or test name already say it | Delete |
   | Stale | It describes code, a task or a state that is gone | Delete |
   | Excuse | It explains away a hack: a magic value, a dummy assert, a silent skip, a promise the code doesn't keep | Delete, and file an issue to fix the code |
   | Decision record | An important, non-obvious choice or fact | Give it a home (below), then delete |

   Read the code before calling something a tautology. If the comment claims something the
   code doesn't do, it's an Excuse, not a tautology.

3. **Give each decision record one home,** checked in this order:
   - **Already recorded?** Search `notes/DECISIONS.md`, `notes/SPEC.md`, `notes/TOKENS.md` and
     the nearest docstring for the fact itself, not just the D-number the comment names. If
     it's there, delete the comment.
   - **Can the code say it?** A `pytest.param(..., id="...")` for a table row; an assert
     message for why an expected value is right; a test docstring for the scenario a whole test
     checks; a name or a clearer expression for a constant (for example
     `datetime(2024, 3, 1, tzinfo=PHOENIX).astimezone(UTC)` instead of a comment saying "00:00
     Phoenix"). Never compute an expected value with the code under test.
   - **Otherwise it's a new D-entry,** grouped by module, for a batch like D-038. Check every
     claim against the code and look up every outside source before writing it down.

   A docstring is for the whole function or test, never a line-level note in disguise.

4. **File each Excuse as an issue** before deleting its comment, only when the owner asked for
   this audit. Use the tracker's format: Description, "Check first", "Done when" boxes, Files,
   Size, and a Source line naming the comment. Put the issue number in the TSV.

5. **Delete, then lower the ratchet:**

   ```bash
   uv run ruff format . && uv run ruff check .
   uv run python -m airwatch.devtools.comments --update   # refuses to raise any allowance
   uv run pytest && node --test tests/site/ && uv run pre-commit run --all-files
   ```

6. **Commit** the TSV, the new D-entries, the code and the lowered baseline together, and say
   what each kind came to in the commit message.

## Never

- Never raise an allowance in `comment-baseline.json`, and never add a file to it by hand.
  If a comment truly can't go yet, leave the baseline where it is and file an issue.
- Never move a comment into a string, a dummy variable or a stray JSDoc block to get past the
  check.
- Never delete a pragma, a shebang, or a comment in a config file.
- Never point to a D-entry as a fact's home without reading that entry.
