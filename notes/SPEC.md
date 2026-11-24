# Spec: AirWatch v2 (V1)

Status: **V1, approved by the owner on 2026-11-18**. Changes go in delta specs
(`SPEC-<change>.md`) · Written 2026-11-18 · All dates are America/Chicago unless they carry a zone.

Sources of truth: the intent is in [INTENT.md](INTENT.md), and the settled decisions D-001 to D-014
are in [DECISIONS.md](DECISIONS.md). This spec links to decisions rather than repeating them: one
home per fact.

---

## Objective

**What:** a live service. Every day it forecasts **tomorrow's 24-hour mean PM2.5 at each monitor**
in one US metro area and publishes the forecasts, the actuals and an honest track record on a
public page.

**Who:** hiring managers and interviewers (main audience), and the owner (learning Prefect,
MLflow, Evidently and AWS). See [INTENT.md](INTENT.md).

### User stories

- *As an interviewer,* I open the page and see tomorrow's forecast for the city and each monitor,
  how accurate past forecasts were, and how the model compares with simple baselines and with CAMS.
- *As an interviewer,* I open the repo and find, for every design choice, a dated decision with
  its reasons, and a test suite that proves the "must never" rules (no leakage, at most one publish
  per day).
- *As the owner,* I get an email (and a GitHub issue) when a daily run is missing, the model
  degrades or the inputs drift, and I never have to start a run by hand.

### Capability map

| Module id | Responsibility | Depends on |
| --- | --- | --- |
| `observations` | PM2.5 from EPA AQS (validated history) and AirNow (live, preliminary) (D-004) | — |
| `weather` | Open-Meteo observed weather (ERA5), GFS forecasts as issued (Previous Runs), live GFS forecast, CAMS PM2.5 (D-007, D-009, D-051) | — |
| `validation` | Data-quality report on every source; blocks the pipeline on hard failures | observations, weather |
| `features` | Leakage-safe feature rows "as known at issue time" | validation |
| `training` | Baselines, 6 variants, rolling-origin CV, one-time test read, MLflow tracking and registry (D-008 to D-010) | features |
| `forecast` | Daily run: build today's features, predict D+1, write the durable record at most once | training, features |
| `monitoring` | Daily scoring, weekly Evidently drift, flags (D-013) | forecast, observations |
| `site` | Static page plus public JSON (D-012) | forecast, monitoring |
| `orchestration` | Prefect deployments and schedules, EventBridge→Lambda watchdog, SNS alerts (D-011) | all |

**Build order:** a walking skeleton through *every* module by 2026-11-25 (D-014), then deepen each
module in the order validation → features → training → monitoring → site.

### Key definitions (pinned here, used everywhere)

- **Issue time:** the daily run starts at **06:00 America/Chicago** on day *D*. It may use only
  data that existed before that moment: observations up to the end of *D−1*, and the weather
  forecast run most recently published before 06:00 local.
- **Target:** the mean of the hourly PM2.5 values at a monitor (µg/m³) over local calendar day
  **D+1**. A day is valid only with **≥ 18 of 24 hours** present (75%). One series per AQS site ×
  parameter 88101; co-located instruments (POCs) are averaged per hour first. Labels are built
  from AQS's *hourly* data with this rule, not from AQS's daily summary records, and only from
  continuous FEM instruments (D-032).
- **Training labels** come from AQS. **Live labels** come from AirNow: day T is scored on the
  morning of T+2, once its files have settled (D-042). The AQS re-score follows later (D-004).
- **Weather lead mapping (D-051):** for target day D+1 (a Phoenix day) issued at 06:00 Chicago
  on day D, weather values valid during D+1 are 19–44 hours ahead of issue. When rebuilding
  history from the Previous Runs API, every hour of D+1 uses `_previous_day3`: the last GFS run
  started at or before 72 h ahead of that hour, published about a day before the issue time.
  The live run uses the newest run published before it starts. This mapping gets one property
  test.

---

## Tech Stack

The exact versions are **looked up from PyPI when the repo is created and pinned in `uv.lock`**,
never typed from memory. Third-party GitHub Actions are pinned to commit SHAs with the version in a
comment.

| Concern | Choice |
| --- | --- |
| Language | Python 3.12, the version the Prefect Managed image uses (D-026) |
| Packaging | `uv`, `pyproject.toml`, `uv.lock`. The only `requirements` file is exported from `uv.lock` for the Prefect run (`requirements/prefect-run.txt`, D-040) |
| Orchestration | Prefect 3 + Prefect Cloud Hobby, Prefect Managed work pool (D-011) |
| Tracking and registry | MLflow; backend per OQ-2 |
| Models | scikit-learn (Ridge, RF), XGBoost, LightGBM, PyTorch (LSTM, TCN), all on CPU |
| Monitoring | Evidently 0.7+ (`DataDefinition` API) |
| Data | pandas, pyarrow (Parquet) |
| Config | pydantic-settings (typed, read from the environment, validated at startup; no import-time side effects) |
| HTTP | httpx with timeouts and retry/backoff; **credentials never in URLs that get logged** |
| Cloud | AWS: S3 (private and public prefixes), EventBridge Scheduler, Lambda, SNS, SSM Parameter Store |
| Infrastructure as code | Terraform, remote state in versioned private S3, region us-east-1 (D-018) |
| Site | Static HTML/JS on GitHub Pages; one pinned chart library from an allowed CDN |
| Docs | Zensical, pinned in a `docs` dependency group; numbers from `results/results.json` via native macros (`airwatch.docs_macros`); Vale for the style sheet; lychee, offline, as the separate link and anchor checker in CI (D-016, D-043) |
| Scaffold | `uv init --package` src layout + the folders below; not CCDS (D-015) |
| Quality | Ruff (lint and format), mypy (strict on `src/`), pytest, Hypothesis, moto, time-machine, mutmut, pre-commit, gitleaks |

Where these come from: carried over from v1 (uv, Ruff, pytest, moto, mypy, pre-commit, pandas,
XGBoost, scikit-learn, Prefect, MLflow, Evidently, S3); required by decisions D-007 to D-016; the
owner's verification rules (Hypothesis, mutmut, frozen clock, secret scanning); my own picks, each
confirmed when added (pydantic-settings, httpx, pyarrow, SSM Parameter Store).

---

## Commands

The commands that work today live in [DEVELOPMENT.md](../DEVELOPMENT.md), their one home
(D-043; `CLAUDE.md` imports it). Below are the target commands, which become real as each module lands:

```bash
uv sync --frozen                         # install exactly what the lockfile says
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -m "not slow and not live"  # core suite: offline, seeded, < 30 s
uv run pytest -m slow                     # model smoke tests on small data
uv run pytest -m live                     # opt-in calls to the real APIs, never in CI
uv run mutmut run                        # Linux only (WSL or CI); paths in [tool.mutmut] (D-048)
uv run python -m airwatch.validation.report --source all     # data-quality report
uv run python -m airwatch.training.cv --variant lightgbm      # one variant, CV only
uv run python -m airwatch.training.final_test                 # reads the 2025 test ONCE (guarded)
uv run python -m airwatch.forecast.run --target-day 2026-11-25    # a dry run; --publish acts (D-034)
uv run prefect --no-prompt deploy --all  # deploy flows to Prefect Cloud (prefect.yaml; D-040)
uv run --group docs zensical build --strict  # build the docs into site_build/ (D-043)
```

---

## Project Structure

```text
pm25-forecast/                 new public repo (D-002, D-017); package name `airwatch`
├── .claude/skills/            project-scope agent skills + skills-lock.json (D-020)
├── src/airwatch/
│   ├── config.py              typed settings; the only place that reads the environment
│   ├── timeutil.py            UTC/local conversion, issue-time rules (single home)
│   ├── logutil.py             the one logging setup: UTC times with a Z (#52)
│   ├── aqi.py                 EPA's AQI rules and colours (single home; D-036)
│   ├── storage.py             S3 get/put/list and create-only-if-absent (D-034)
│   ├── errors.py              ReportableError: errors whose message is safe to log (#56)
│   ├── observations/          aqs.py, airnow.py, schema.py, sites.py (D-030 sites, D-032 methods),
│   │                          metadata.py (city check, HTTP retries), aqs_bulk.py (T13)
│   ├── weather/               leads.py (the 72-hour rule), openmeteo.py, bulk.py (T14), cams.py
│   ├── validation/            checks.py (whole problem classes), report.py
│   ├── features/              build.py (as-of-issue-time feature rows)
│   ├── training/              split.py, baselines.py, models/, cv.py, final_test.py, registry.py
│   ├── forecast/              run.py, record.py (conditional write), publish.py, schemas/ (D-036)
│   ├── monitoring/            compute.py (Prefect minutes ledger), score.py (daily scoring, D-042), drift.py, flags.py
│   ├── flows/                 Prefect flows (thin wrappers that call the modules above)
│   ├── watchdog/              handler.py (the backup-trigger Lambda; stdlib + boto3 only), build.py (its zip; D-041)
│   ├── devtools/              comments.py (the comment ban, D-037), docs_check.py (the docs rules, D-043)
│   └── docs_macros.py         results.json → the docs' `results` variable (D-043)
├── scripts/                   manual tools: city_check.py (reads only), aqs_bulk.py (dry run unless --apply)
├── data/                      local cache of downloads (gitignored; raw data never committed)
├── infra/                     Terraform (D-018); the watchdog's zip is built into infra/build/ (gitignored)
├── site/                      static page (HTML/JS/CSS; deployed only after the go-live switch, D-036)
├── biome.json, .nvmrc         Biome lint/format for the page's JS and CSS; Node version for its tests
├── prefect.yaml               the Prefect deployment: schedule, image, pull steps (D-040)
├── requirements/              exported from uv.lock: prefect-run.txt (the Prefect run, D-040), watchdog.txt (D-041)
├── tests/
│   ├── conftest.py            Hypothesis profiles, the `daily` flow fixture; loads suite_budget.py (D-046)
│   ├── suite_budget.py        fails a run past SUITE_BUDGET_S seconds (CI: 75 s, D-046)
│   ├── project_files.py       the scope tests' walk, skipping ignored folders (D-046)
│   ├── unit/                  one file per module
│   ├── property/              Hypothesis: leakage, time and DST, per-group, idempotency
│   ├── integration/           moto S3, frozen clock, fake APIs (recorded fixtures)
│   ├── site/                  the page's JavaScript tests (node --test)
│   └── regressions/           shrunk failing cases saved from Hypothesis
├── notes/                     INTENT, SPEC, DECISIONS, JOURNAL, TOKENS, STYLE and OUTLINE (the write-up's rules
│                              and plan, D-044), guides/ (owner-run steps)
├── docs/                      the write-up (Zensical); numbers via macros; built into site_build/ (gitignored)
├── results/                   results.json, the single source for every number in the prose, and the charts' data
├── zensical.toml              the docs site config (D-043)
├── .vale.ini, styles/         Vale: the banned words, and count words in docs/ (D-043, D-044)
├── DEVELOPMENT.md             every command, its one home; imported by CLAUDE.md (D-043)
└── .github/workflows/         CI, Pages deploy, weekly lock upgrade, mutmut on demand
```

Rule: flows contain no logic. Everything testable lives in `src/airwatch/<module>` and is tested
without Prefect.

---

## Code Style

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

LOCAL_TZ = ZoneInfo("America/Chicago")  # from config in real code; shown inline here
ISSUE_HOUR_LOCAL = 6


def issue_time_utc(forecast_day: date) -> datetime:
    """Return the UTC instant at which the forecast for `forecast_day` (D+1) is issued.

    The forecast is issued at 06:00 local on the day before the target day.
    """
    issue_local = datetime.combine(
        forecast_day - pd.Timedelta(days=1), datetime.min.time(), tzinfo=LOCAL_TZ
    ).replace(hour=ISSUE_HOUR_LOCAL)
    return issue_local.astimezone(ZoneInfo("UTC"))


def known_at(df: pd.DataFrame, cutoff_utc: datetime) -> pd.DataFrame:
    """Keep only rows that existed before `cutoff_utc`. Every feature builder must call this."""
    if df["available_at_utc"].dt.tz is None:
        raise ValueError("available_at_utc must be timezone-aware UTC")
    return df.loc[df["available_at_utc"] < cutoff_utc]
```

Conventions:

- Full type hints, and `mypy --strict` on `src/`.
- Timestamps are timezone-aware, stored in UTC; the local time zone is applied only for display
  and day boundaries.
- Every column holding data from outside carries `available_at_utc`.
- Logging is structured, with no secrets, tokens or credentialed URLs. Errors are reported by type
  only.
- Functions are pure where possible; I/O sits at the edges (`observations`, `weather`, `record`,
  `publish`).

---

## Testing Strategy

Every task states its check before its code. The checks:

| Rule ("must never") | Test |
| --- | --- |
| No leakage | Hypothesis: changing or deleting any input with `available_at_utc ≥ issue time` leaves every feature row for that issue time unchanged |
| Per-monitor work stays per-monitor | Hypothesis: shuffling or changing other monitors' data cannot change a monitor's per-monitor features |
| Time is right, including around DST | Hypothesis: `issue_time_utc` and the day boundaries match a simple reference across DST changes (March and November) |
| At most one publish | Integration (moto + frozen clock): running the daily flow twice, or after any single step fails, writes ≤ 1 record and ≤ 1 public JSON per date. The watchdog never triggers when the record exists. |
| Nothing private goes public | Unit: every public payload must pass a strict JSON schema (no field outside the list) and a secret scan before upload; a refusal writes nothing (D-036) |
| The page keeps AirNow's terms | Unit: D-025's labels, notice, link and credits are checked on the page's text; no AQI colour is typed into the site (D-036) |
| No duplicate or rescaled features | Unit test: no two feature columns are identical or exact linear rescalings of each other |
| Test set read once | `final_test.py` refuses to run without a freeze flag and writes a one-time marker; CI fails if test-period metrics appear anywhere else |
| Prose matches results | CI: no digit in `docs/` outside a macro except allow-listed literals, every macro resolves in `results/results.json`, and count words (two to twelve) fail in Vale (D-043, D-044) |
| Charts match results | Each chart is drawn at build time from its data file in `results/`; a test ties the declared charts to their data files (D-044) |
| Wins are verdicts | Each baseline comparison quotes the pipeline's verdict from D-045's interval; the interval code reproduces a planted gap on simulated data first |
| Docs links | CI: the strict Zensical build, then lychee offline over the built site, fails on any broken link or anchor (D-016, D-043) |
| New evaluation code reproduces a known number | The CV harness must reproduce hand-computed persistence MAE on a small fixture before any model result is trusted |

- **Outside world:** the clock, S3, the AirNow, AQS and Open-Meteo APIs, the Prefect API and SNS
  are all faked. Recorded API responses are fixtures, and each fake has a test that fails at
  every step in turn.
- **Mutation testing** (mutmut) on `timeutil.py` and `config.py` from #42, then `features/`,
  `forecast/record.py` and `training/split.py` as they land (D-048).
  Every surviving mutant is either killed by a new test or explained in the journal.
- **Coverage:** ≥ 85% line coverage on `src/airwatch` (excluding `flows/`), enforced in CI as a
  floor. It is a floor, not the goal; placeholder tests like v1's `assert True` are banned.
- **Speed:** the core suite is offline and seeded, runs in under 30 seconds on 4 parallel workers
  (D-035), and starts no Prefect server. CI fails the run past 75 s, its own noisier limit
  (D-046).
- **The page's JavaScript** is tested with `node --test` and linted by Biome, both in CI (D-036).

---

## Boundaries

- **Always:**
  - Work on a branch per issue, and open a PR. CI must be green before merging.
  - Commit with the owner's GitHub noreply address (repo-local config).
  - Write the check before the code.
  - Use UTC with an explicit zone.
  - Validate inputs at module edges.
  - Record decisions in DECISIONS.md and keep a dated JOURNAL entry per session.
  - Look up versions; never recall them.
- **Ask first:**
  - Commit, push, open or merge a PR, create GitHub issues or repos, or change a repo's
    visibility.
  - Create or change any AWS or Prefect Cloud resource, or anything that costs money.
  - Add a dependency.
  - Change CI, a schedule or a decision marked **Frozen**.
  - Make any change to the split, metrics or selection rule.
  - Read the 2025 test.
- **Never:**
  - Print, log or commit secrets, `.env` or tokens.
  - Put credentials in URLs that get logged.
  - Open files whose saved outputs contain test-period results.
  - Change an evaluation choice after seeing results, or add a model variant after the first CV
    result.
  - Loosen a failing check instead of fixing its cause. (Scoping one check away from files the
    project doesn't own, such as the vendored skills, is not loosening; it needs a D-entry, as in
    D-029.)
  - Run production from two places.
  - Publish raw or licensed data publicly.

---

## Success Criteria

V1 is done when all of the following hold. Each is checkable.

1. **Live:** from the day the headline model goes live (T23; D-050), the page has shown its
   new D+1 forecast every day for **14 days in a row** without manual action. The S3 records
   prove it (one per date, none duplicated).
2. **Watchdog proven:** in a deliberate drill (the primary run disabled for one day), the watchdog
   triggered the run, or emailed when that failed, and the day still has exactly one record.
3. **Honest evaluation:**
   - CV results exist for all 6 variants (or "not evaluated" with the calendar reason, per D-014)
     and for the 3 baselines.
   - The headline model was chosen by the frozen rule (D-010).
   - The 2025 test was read once, and the marker proves it.
4. **Baselines:** the page and the write-up show the headline model against persistence,
   climatology and CAMS on MAE, whatever the result, each with its D-045 interval and verdict,
   on the test year and on the live snapshot (D-044). If it loses, the write-up says so.
5. **Skew measured:** the observed-weather vs forecasts-only variant (D-007) and the AirNow vs AQS
   gap (D-004) are each reported with a number.
6. **Checks green:** lint, `mypy --strict`, the core suite under 30 s (on the owner's PC; CI
   fails it past 75 s, D-046), coverage ≥ 85%, the
   property tests, mutation testing with no unexplained survivors, the docs number check, and
   secret scanning, all in CI.
7. **Cost:** the AWS bill stays under **$5 a month**, with a billing alarm set at $5. Prefect
   managed minutes stay **≤ 300 a month** (60% of the free 500).
8. **Monitoring:** a weekly Evidently drift report is linked from the page, and at least one flag
   has been exercised end to end (a test flag produces an email and a GitHub issue).
9. **Documented:** every tool choice traces to a D-entry, and the README explains in prose what v1
   got wrong and how v2 avoids it, without linking to v1 (D-002).

---

## Out of Scope (Deferred)

- Automatic retraining and promotion: needs a safe promotion rule and uses up the free quota (D-013).
- More than one city at a time: the intent limits V1 to one.
- Other pollutants such as ozone: same reason.
- Prediction intervals or quantile forecasts: valuable, but they add to the metric surface; a V2
  candidate. (D-045's interval is different: it is on the MAE gap between two forecasters,
  reported only.)
- A Temporal Fusion Transformer or other large models: excluded (D-010).
- A real-time API or user accounts: out of scope in the intent.
- Running on AWS ECS: only if Prefect's free plan changes (D-011).
- A custom domain for the page: it costs money and isn't needed.

---

## Open Questions

- **OQ-2 · MLflow backend:** with no always-on server, where do runs and the registry live? For
  example, a local SQLite tracking store on the owner's PC plus S3 artifacts, with the daily flow
  loading the *promoted* model from S3 through a pinned pointer file (no MLflow server needed at
  forecast time), or a hosted free MLflow. To check: current hosted options and limits.

Closed after approval (recorded as D-entries, no change to V1's requirements):

- OQ-1 → D-004 and D-025 (AirNow limits and history, then the data-use rules; T0a);
- OQ-3 → D-018 (Terraform);
- OQ-4 → D-026 (Python 3.12; T1);
- OQ-5 → D-006 (city-check criteria frozen; T4);
- OQ-6 → D-019 (06:00 confirmed);
- OQ-7 → D-020 (skills in the repo);
- OQ-8 → D-032 (labels from AQS hourly continuous FEMs, our own daily rule; T5).
