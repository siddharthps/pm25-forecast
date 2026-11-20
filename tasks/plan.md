# Implementation Plan: AirWatch v2 (V1)

Source spec: [notes/SPEC.md](../notes/SPEC.md) (V1, approved 2026-11-18) · Decisions:
[notes/DECISIONS.md](../notes/DECISIONS.md) · Status: **approved by the owner on 2026-11-18** ·
Dates are America/Chicago.

**Tracker:** GitHub Issues on
[siddharthps/pm25-forecast](https://github.com/siddharthps/pm25-forecast/issues), created
2026-11-18. There are 36 issues (#1–#36) with 4 milestones, and each issue holds its task's "Done
when" boxes. [todo.md](todo.md) maps T-numbers to issue numbers. This file and `notes/` moved into
the repo in T1 (#5). The ticks below follow GitHub; the issues are the source of truth.

## Overview

The build has two parts. First, a **walking skeleton**, live by **2026-11-25** (D-014): every
module exists in a crude form. The persistence baseline forecasts daily, the page is up and the
watchdog is on. Second, a **deepening phase**: each module gets more depth inside a pipeline that
already works, ending at the **research freeze on 2026-12-23**. The cut-line check is on
2026-12-16. The plan front-loads the risky, slow and outside-world pieces, because last time the
delivery path was built last and its bugs surfaced three days before the deadline.

## Architecture decisions (already settled; one home each)

| Topic | Decision |
| --- | --- |
| Repo | New public repo; the old one made private (D-002) |
| Data | AQS history + AirNow live, with the gap measured (D-004); per-monitor next-day mean (D-005) |
| City | Declared data check (D-006): **Phoenix** won (D-030), with its 10 monitors and their instrument types (D-032) |
| Weather | Observed for training, forecasts as issued for test and live (D-007) |
| Evaluation | Develop on 2009–2024 with rolling CV, test on 2025 read once, then live (D-008); MAE + 3 baselines (D-009); 6 frozen variants (D-010) |
| Runtime | Prefect Cloud Managed + EventBridge→Lambda watchdog, S3 conditional write (D-011, verified in D-034); issue 06:00 Chicago for D+1 (D-019); AWS access keyless or a rotated narrow key (D-024) |
| Infra and repo | Terraform (D-018); `siddharthps/pm25-forecast` (D-017); skills in the repo (D-020) |
| Ways of working | Validation split T12a/T12b (D-021, rules in D-033); light write-up rules (D-022); owner drives each new tool first (D-023); tests in parallel (D-035) |
| Page | GitHub Pages + public JSON in its own bucket (D-012, D-028); AQI per EPA's TAD, schema-checked files, a go-live gate (D-036) |
| Monitoring | Daily scoring, weekly drift, retraining by hand (D-013) |
| Scaffold and docs | uv src layout (D-015); Zensical + a separate link checker (D-016) |

## Dependency graph

```text
T0 owner accounts ──────────────┐ (AirNow key, Prefect Cloud, AWS hygiene + Terraform, new repo)
T1 scaffold → T2 CI → T3 config/time → T3b Terraform base (buckets, IAM)
                         │
          T4 city check (first: metadata only)
                         │
          ┌──────────────┴───────────────┐
          T5 observations + site mapping  T13 AQS bulk download (starts as soon as T4+T5 allow: slowest)
                         │
                  T12a validation (3 problem classes)
                         │
                  T6 forecast + durable record
                         │
          ┌──────────────┼──────────────┐
          T7 publish+site  T8 Prefect deploy  T10 daily scoring
                         │
                  T9 watchdog ───────────► T11 docs stub ► CHECKPOINT 11-25
                                                   │
T14 weather → T12b validation (rest) → T15 features → T16 CV harness + baselines → T17 MLflow
        → T18–T22 variants (in declared order) → T23 promote headline
        → T24 drift + flags, T25 map, T26 AQS re-score ► CHECKPOINT 12-16 (cut line)
        → T27 final test (once) → T28 write-up ► FREEZE 12-23 → T29 live criteria → T30 retire v1
```

## Task list (index; the full bodies are in [todo.md](todo.md))

### Phase 0: Owner actions (start today, in parallel)

- [x] T0a: AirNow account + read the gated docs (OQ-1) · *owner* (2026-11-18; key storage in
  the repo and live check follow in T1/T5)
- [x] T0b: Prefect Cloud Hobby account + workspace · *owner* (2026-11-18; CLI login check in T8)
- [x] T0c: AWS hygiene: SSO login, $5 alarm, v1 key deactivated, Terraform 1.17.2, state bucket
  · *owner, agent guides* (2026-11-18; delete the old key on 11-25)
- [x] T0d: Create `siddharthps/pm25-forecast` (D-017) · *owner approves, agent runs* (2026-11-18)

### Phase 1: Foundation (week 1)

- [x] T1: Day-zero scaffold and quality gates (merged #37, 2026-11-18)
- [ ] T2: CI on GitHub Actions (SHA-pinned) (merged #39, 2026-11-18; #6 closes once the 11-23
  lock-job PR passes CI)
- [x] T3: Typed config + time rules, with DST property tests (merged #40, 2026-11-18)
- [x] T3b: Terraform base: versioned private data bucket, public JSON bucket (D-028), pipeline IAM
  · *owner runs the first apply* (merged #41, 2026-11-18)

### Checkpoint A: Foundation (target 2026-11-20)

- [x] `uv sync --frozen`, lint, `mypy --strict` and the core tests pass locally and in CI on a PR
- [x] Secret scan runs in CI; the noreply email is verified on the first commit
- [x] Owner reviews before the skeleton begins (the milestone A notes review, #44/#45)

### Phase 2: Walking skeleton (week 1, target 2026-11-25)

- [x] T4: City data check (D-006), **first**: freeze the thresholds, score the candidates, write
  a D-entry (merged #46, 2026-11-18; Phoenix, D-030)
- [x] T5: Observations skeleton: AirNow live + AQS client, daily means, AirNow↔AQS site mapping,
  matching instrument types (merged #47, 2026-11-18)
- [x] T13: AQS bulk history download, started as soon as T4 and T5 allow (runs in the background)
  (merged #48, 2026-11-18; 1,217,348 rows)
- [x] T12a: Validation module + report, first 3 problem classes, on AirNow and AQS (D-021) (merged
  #51, 2026-11-19)
- [x] T6: Persistence forecast + at-most-once durable record (merged #53, 2026-11-19; first real
  record for 2026-11-20)
- [ ] T7: Public JSON + static page on GitHub Pages (merged #54, 2026-11-19; **live 2026-11-20**,
  D-039)
- [ ] T8: Prefect daily deployment (Managed pool, 06:00 Chicago)
- [ ] T9: Watchdog: EventBridge → Lambda → Prefect API / SNS, in Terraform (D-018)
- [ ] T10: Daily scoring of yesterday's forecast
- [ ] T11: Bottom line + outline + style sheet (Vale), docs stub, `results.json` number check,
  README skeleton (D-022)

### Checkpoint B: Skeleton live (2026-11-25), plus the D-014 review

- [ ] The page shows a real D+1 persistence forecast produced by the scheduled run, with no manual
  action
- [ ] The watchdog dry drill passes (record present → no action; record absent → trigger)
- [ ] **Re-evaluate the timeline (D-014)**; any change becomes a new D-entry before results are seen

### Phase 3: Deepen (weeks 2–5)

- [ ] T14: Weather ingestion: ERA5 history, Previous Runs archive, live forecast, CAMS
- [ ] T12b: Validation: remaining problem classes + weather sources (D-021)
- [ ] T15: Leakage-safe features + property tests + mutation testing
- [ ] T16: CV harness + 3 baselines (must reproduce a hand-computed persistence MAE first)
- [ ] T17: MLflow backend (OQ-2) + promotion pointer
- [ ] T18: Ridge + Random Forest (CV only)
- [ ] T19: XGBoost + LightGBM (CV only; time one small run first)
- [ ] T20: LSTM (CV only)
- [ ] T21: TCN (CV only), **first on the cut line**
- [ ] T22: Skew measurements: forecasts-only variant + the AirNow-vs-AQS gap
- [ ] T23: Select the headline by the frozen rule, then promote it into the daily forecast
- [ ] T24: Weekly Evidently drift + flags (email + GitHub issue)
- [ ] T25: Page: per-monitor map + track-record charts, **second on the cut line**
- [ ] T26: AQS re-scoring of past forecasts, **third on the cut line**

### Checkpoint C: Cut line (2026-12-16)

- [ ] Anything unfinished from T21, T25, T26 is cut in that order, by calendar, and reported as
  "not evaluated" or "deferred"
- [ ] Every remaining variant has CV results; no test numbers seen anywhere

### Phase 4: Freeze and delivery (to 2026-12-23, then live criteria)

- [ ] T27: Final test, read once (guarded) → `results.json`
- [ ] T28: Write-up: README + docs chapters from `results.json`; how v2 fixes v1's mistakes, in
  prose
- [ ] T29: Live acceptance: 14 consecutive days + a deliberate watchdog drill
- [ ] T30: Retire v1: make the old repo private (D-002) · *owner approves*

### Checkpoint D: Complete

- [ ] All 9 success criteria in SPEC.md are met, each with evidence linked from its issue

## Definition of Done (every task, on top of its own acceptance criteria)

The skill's shared `definition-of-done.md` wasn't installed, so this is ours, from the owner's rules:

1. Its check was written first and fails without the change (where the task has code).
2. Lint, `mypy --strict`, the core tests and the secret scan are green in CI on the PR.
3. Branch per issue → PR → the owner asks to merge; the task is done **only once merged**.
4. No secrets, credentialed URLs or test-period results in code, logs, outputs or commits.
5. The journal has an entry for the session; any new decision is in DECISIONS.md.
6. New work found along the way gets its own issue; it is never a silent addition.

## Time budget (estimates are a guide, not a cap)

| Window | Owner hours available | Planned |
| --- | --- | --- |
| 2026-11-18 → 11-25 | about 20 h | Phase 0 (about 2 h, owner) + Phases 1–2 (review and decisions; agent-heavy) |
| 11-26 → 12-16 | about 30 h | Phase 3 |
| 12-17 → 12-23 | about 10 h | Phase 4 (T27, T28) |
| After 12-23 | as needed | T29 runs on the calendar (14 days of evidence), then T30 |

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| AirNow limits or history worse than assumed | High | T0a reads the real limits first; cache hourly data; nationwide file products as a fallback |
| Prefect Hobby limits (5 deployments, 500 min) or a plan change | Med | Deployment budget: daily forecast, weekly drift, plus spares; minutes alarm at 300; ECS fallback (D-011) |
| AQS bulk download slow or rate-limited | Med | T13 starts early, in the background, resumable and idempotent per year and site |
| Zensical beta breaks the build | Low | Pin the exact version; written fallback (D-016) |
| Training/serving skew larger than expected | Med | It's measured (T22) and reported, not hidden |
| Time-zone or DST bugs in the issue time | High | One `timeutil` home + property tests in T3, before any data code |
| AirNow rewrites hourly files for ~7.7 h after the hour (found in T6) | Med | Strict issue-time cut: rows published after 06:00 are dropped and counted; a property test proves they can't change a forecast (D-034) |
| Double publish on retry or watchdog | High | S3 conditional write + an idempotency test that fails at each step in turn (T6, T9) |
| Accidental test peek | High | `final_test.py` guard + a CI check that no test-period metrics appear elsewhere (T16, T27) |
| AirNow monitors don't map cleanly to AQS sites | High | Explicit site mapping in T5; unmatched monitors excluded and counted; a validation check |
| Training labels measured differently from live (filter vs continuous) | High | AQS labels restricted to the hourly continuous types AirNow reports (T5, OQ-8) |
| Long-lived AWS key outside AWS (Prefect Managed) | Med | Keyless if supported, else a narrow key rotated every 90 days (D-024) |
| Publishing data the terms don't allow | Med | T0a checks the AirNow data-use guidelines; T7 depends on it |

## Parallelization

- **Owner (Phase 0)** runs in parallel with T1–T3.
- **T4 (city check)** runs first in Phase 2 (metadata only, about 1–2 h); the rest of the skeleton
  reads the city from config.
- **T13 (bulk download)** runs in the background as soon as the city (T4) and the AQS client (T5)
  exist.
- **T18–T21** are independent in code, but run in the declared order so the cut line works.

## How we work (D-023)

The agent implements most tasks and explains every PR in plain terms. The **owner runs the first
use of each new tool** from a step-by-step guide: Terraform (T3b), the Prefect deploy (T8), the
first MLflow run (T18), the first Evidently report (T24), and the AWS console checks (T0c).
Commits, pushes, PRs, merges, issue creation and every outside-world change happen only when the
owner asks.

## Open questions

- Settled since the spec: OQ-1 → D-004 and D-025 (AirNow, T0a), OQ-3 → D-018 (Terraform), OQ-4 →
  D-026 (Python 3.12, T1), OQ-6 → D-019 (06:00, D+1), OQ-7 → D-020 (skills in the repo).
- OQ-5 (city thresholds) → D-006, frozen in T4. OQ-8 (AQS daily rules) → D-032, in T5.
- Still open, each with a home: **OQ-2** (MLflow backend) → T17 · the v1 S3 buckets → listed in
  T0c, decided in T30.
- The skill's shared `references/definition-of-done.md` wasn't installed with the skills; ours is
  above. Worth noting for the skills trial (D-001).
