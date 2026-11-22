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
| [notes/STYLE.md](notes/STYLE.md) | The write-up's rules: docs vs notes, numbers, banned words, page template, length |
| [notes/OUTLINE.md](notes/OUTLINE.md) | The write-up's plan: pages, readers, charts, live snapshot, publishing |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Every command, its one home (imported below) |

## Commands

Every command, with how to run it: [DEVELOPMENT.md](DEVELOPMENT.md), imported here.

@DEVELOPMENT.md

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
  the owner asks (D-025, D-036). The report at `/report/` stays switched off until the owner's
  go after T28 (D-044). An agent-started `forecast.run --publish` also needs the owner's
  OK (it writes the real record and the public bucket); the scheduled run (T8) doesn't.
- Decisions are append-only: to change one, add a new D-entry that supersedes or refines it.
  When a task settles, refines or overtakes a D-entry or an open question, update its **Status**
  line (and the OQ list) in the same PR.
- Look up versions (PyPI, `gh api …/releases`); never write them from memory.
- Never type a number into `docs/`: it comes from `results/results.json` through a macro, and
  the docs check and Vale fail the build otherwise (notes/STYLE.md, D-043, D-044).
- Fix a failing check's cause; never loosen it. The only exception is scoping one check away from
  files we don't own (vendored, generated), recorded as a D-entry (D-029).
