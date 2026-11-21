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
uv run pytest                          # fast offline core suite, 4 workers (D-035; -n 0 = serial); -m slow / -m live are opt-in
uv run pytest tests/property --hypothesis-profile=explore   # fresh random search (default is derandomized)
uv run pre-commit run --all-files      # every hook: gitleaks, markdownlint, Biome, terraform fmt
node --test tests/site/                # the page's JavaScript tests (Node from .nvmrc)
terraform -chdir=infra test            # infra safety rules on the plan, mock AWS provider, offline
aws sso login --profile pm25           # AWS access (never use long-lived keys); lasts 8 hours
uv run pytest -m live -o log_cli=true --log-cli-level=INFO   # opt-in real-API checks, counts only
AWS_PROFILE=pm25 uv run python scripts/aqs_bulk.py           # AQS history to S3: dry run; --apply acts
uv run python scripts/city_check.py    # the frozen D-006 city check (reads only; cached in data/)
AWS_PROFILE=pm25 uv run python -m airwatch.validation.report --source all  # D-033 report (reads only)
AWS_PROFILE=pm25 uv run python -m airwatch.forecast.run   # D+1 forecast: dry run; --publish acts
uv export --frozen --no-dev --no-emit-project --no-header --format requirements.txt > requirements/prefect-run.txt  # after any uv.lock change (D-040)
uv export --frozen --only-group watchdog --no-emit-project --no-header --format requirements.txt > requirements/watchdog.txt  # likewise (D-041)
uv run python -m airwatch.watchdog.build  # the watchdog Lambda's zip, into infra/build/, before any terraform plan (D-041)
```

Run every command from the project folder (`cd ~/code/pm25-forecast`). Scripts that change
anything outside this PC are dry runs unless given `--apply`. Keys live in the gitignored `.env`
(names in [.env.example](.env.example); register in [notes/TOKENS.md](notes/TOKENS.md)).

Infrastructure lives in `infra/`. The owner runs `plan` and `apply`, following
[infra/README.md](infra/README.md). CI never has AWS credentials.

## Rules that bite (details in SPEC § Boundaries and the owner's global CLAUDE.md)

- Committing and pushing to a task branch is fine without asking (owner, 2026-11-19). Open or
  merge PRs, create or edit issues, or change anything else outside this PC **only when the owner
  asks**. Branch per issue (`<issue>-<slug>`), never commit to `main`, never force-push: push
  rebased work under a new branch name instead.
- Write the check before the code. Use timezone-aware UTC everywhere. Credentials never go in logs
  or URLs that get logged.
- Never read 2025 test-period results before the freeze (D-008); never change a **Frozen**
  decision.
- Nothing goes public before go-live: never set `PAGES_GO_LIVE` or start a Pages deploy unless
  the owner asks (D-025, D-036). An agent-started `forecast.run --publish` also needs the owner's
  OK (it writes the real record and the public bucket); the scheduled run (T8) doesn't.
- Decisions are append-only: to change one, add a new D-entry that supersedes or refines it.
  When a task settles, refines or overtakes a D-entry or an open question, update its **Status**
  line (and the OQ list) in the same PR.
- Look up versions (PyPI, `gh api …/releases`); never write them from memory.
- Fix a failing check's cause; never loosen it. The only exception is scoping one check away from
  files we don't own (vendored, generated), recorded as a D-entry (D-029).
