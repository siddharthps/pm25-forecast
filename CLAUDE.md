# CLAUDE.md: map for agent sessions

This file points to where things live. It doesn't repeat them; each fact has one home.

## Start here

- **Where we are and what's next:** the last "Next" section of [notes/JOURNAL.md](notes/JOURNAL.md).
- **Tasks:** GitHub issues on `siddharthps/pm25-forecast`; [tasks/todo.md](tasks/todo.md) maps
  task numbers (T1, T2, …) to issue numbers. Order and checkpoints: [tasks/plan.md](tasks/plan.md).

## Project records (read before deciding anything)

| File | Holds |
| --- | --- |
| [notes/INTENT.md](notes/INTENT.md) | Why the project exists, for whom, constraints, out of scope |
| [notes/SPEC.md](notes/SPEC.md) | V1 spec: definitions, structure, testing rules, boundaries, success criteria |
| [notes/DECISIONS.md](notes/DECISIONS.md) | Every settled decision (D-001…) with its why; **Frozen** ones never change after results |
| [notes/JOURNAL.md](notes/JOURNAL.md) | Dated session log, traps found, next steps |
| [notes/TOKENS.md](notes/TOKENS.md) | Every credential's purpose, location, expiry, renewal (never values) |

## Commands

```bash
uv sync --frozen                       # install exactly what uv.lock says
uv run ruff check . && uv run ruff format --check .
uv run mypy                            # strict; config in pyproject.toml
uv run pytest                          # fast offline core suite (-m slow / -m live are opt-in)
uv run pytest tests/property --hypothesis-profile=explore   # fresh random search (default is derandomized)
uv run pre-commit run --all-files      # every hook, including gitleaks, markdownlint, terraform fmt
terraform -chdir=infra test            # infra safety rules on the plan, mock AWS provider, offline
aws sso login --profile pm25           # AWS access (never use long-lived keys)
```

Infrastructure lives in `infra/`. The owner runs `plan` and `apply`, following
[infra/README.md](infra/README.md). CI never has AWS credentials.

## Rules that bite (details in SPEC § Boundaries and the owner's global CLAUDE.md)

- Commit, push, open or merge PRs, create issues, or change anything outside this PC **only when
  the owner asks**. Branch per issue (`<issue>-<slug>`), never commit to `main`.
- Write the check before the code. Use timezone-aware UTC everywhere. Credentials never go in logs
  or URLs that get logged.
- Never read 2025 test-period results before the freeze (D-008); never change a **Frozen**
  decision.
- Look up versions (PyPI, `gh api …/releases`); never write them from memory.
- Fix a failing check's cause; never loosen it. The only exception is scoping one check away from
  files we don't own (vendored, generated), recorded as a D-entry (D-029).
