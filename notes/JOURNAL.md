# Journal

One dated entry per working session: what was done, traps found, fixes.
Settled decisions and their reasons live in [DECISIONS.md](DECISIONS.md), not here.

---

## 2026-11-18: Revival review of the 2025 project

**Context.** The project has been untouched since the last commit on 2025-08-04. The goal now is to
update it, with a full restructure on the table. Before anything changed, the whole repo was read and
checked.

### What was done

- Installed `addyosmani/agent-skills` (25 skills) at **project level** as a trial (see D-001).
- Read every flow, script, test file, config file and doc page.
- Did **not** open `flows/mlflow.db`, `mlruns/` or `reports/*.html`, because they contain test-set
  results.
- Read `.env` for key names only, never values.
- Installed the locked dependencies (`uv sync --frozen --group dev` → `.venv`, gitignored) and ran
  the checks with dummy credentials, so no real AWS or EPA keys were used.

### Baseline numbers (2026-11-18, from `uv.lock`)

| Check | Result |
| --- | --- |
| Tests | 182 passed, **3 failed**, 185 total, about 6 min (each run starts a temporary Prefect server) |
| Coverage (`flows/`) | 95.27% |
| Ruff | clean |
| mypy (`flows/`) | **36 errors** in 9 files |
| CI | disabled (placeholder job only, actions not pinned to SHAs) |
| Versions resolved | Python 3.12.11, Prefect 3.4.11, MLflow 3.1.4, Evidently 0.6.7, scikit-learn 1.7.1, XGBoost 3.0.3, pandas 2.3.1 |

The 3 failing tests:

- `test_data_ingestion.py::TestAirQualityIngestionFlow::test_air_quality_ingestion_flow_success`
- `test_data_ingestion.py::TestAirQualityIngestionFlow::test_air_quality_ingestion_flow_missing_bucket_name`
- `test_model_monitoring.py::TestModelMonitoringFlow::test_model_monitoring_flow_success_no_drift`

### Findings

#### Evaluation (the most serious problems)

- **F1.** **Random split on time-series data** (`model_training.split_data`, `train_test_split`): same-day
  readings from nearby monitors land in both train and test, so the scores are optimistic.
- **F2.** **The model is chosen by test RMSE** (`model_selector.get_best_non_overfit_run`,
  `order_by test_rmse`), which uses up the test set. The "overfit" check is only
  `val_rmse > 1e-4`.
- **F3.** **The only features are location and calendar fields** (lat, lon, year, month, day of
  week, day of year, is_weekend), so the model is in effect a seasonal average per site. There is no
  baseline to beat.
- **F4.** **"Inference" is not a forecast.** It downloads a year that has already been measured and
  predicts the same days. The regression report uses `current_data` as both reference and current.
- **F5.** **The drift alert fires almost every time.** `year` is a drift feature, and 2025 lies outside
  2009–2024. Drift then raises `ValueError`, so the monitoring flow fails.

#### Wiring and operations

- **F6.** **EPA API key leaks into logs.** Both ingestion flows print or log the full request URL, which
  contains `email` and `key`.
- **F7.** **No data validation.** Failed years are only logged, so gaps pass silently, and there is
  no de-duplication. AQS daily data probably has several rows per site and day (POC, sample duration,
  pollutant standard). *To verify against the AQS docs.*
- **F8.** **The selector and inference are not connected.** The selector uploads to
  `selected_models/<run_id>`, but inference loads a hard-coded artifact path
  (`m-1099ed93…`). There is no model registry step.
- **F9.** **Hard-coded config:** the bucket name and `MLFLOW_URI` in `model_selector.py`, and the buckets
  in the `Makefile`. Modules raise errors or create boto3 clients at import time.
- **F10.** **`scripts/deploy_monitoring.py` cannot run:** it uses the Prefect 2
  `Deployment.build_from_flow`, which Prefect 3 removed.
- **F11.** **Two open Dependabot branches bump Evidently to 0.7.x.** This is probably breaking (I believe
  `ColumnMapping` was removed). *To verify, not from memory.*
- **F12.** **Docker:** the image runs as root, installs compilers, uses `COPY . .` and only runs inference.
  `requirements.txt` duplicates `pyproject.toml` and puts Jupyter and MkDocs in the runtime
  dependencies.
- **F13.** **Docs:** three overlapping pairs of chapters (monitoring 05/08/11, deployment 04/07/10,
  testing 06/09), and `docs/index.md` is still the MkDocs template. README figures ("RMSE < 5",
  "99% success", "~1000 records/s") have no evidence behind them.
- **F14.** **Tests:** about 10 tests are placeholders (`assert True` or import checks). `test_data.py`
  hard-codes "182 tests, 88.90% coverage". Most of the tests mock S3 and MLflow.

#### Repo hygiene and security

- **F15.** Good: `.env`, `*.pkl`, `mlflow.db` and the reports were never committed, and no AWS key pattern
  appears anywhere in the git history.
- **F16.** **18 of 20 commits use non-noreply author addresses** and are already pushed. There is no
  repo-local `user.email`.
- **F17.** **`.env` holds long-lived AWS access keys**, probably more than a year old. Rotate them or
  move to short-lived credentials.
- **F18.** Local clutter, not tracked: `mlartifacts/` 64 MB, `.mypy_cache/` 169 MB, `reports/`
  7.5 MB, and `flows/mlflow.db`.

**Worth keeping:** one module per stage, moto S3 fakes, the `uv` lockfile, the Ruff setup.

### Traps found

- Running the tests without overriding the environment would load the real `.env` through
  `load_dotenv()`. Always export dummy `AWS_*`, `S3_*`, `EPA_*` and `MLFLOW_*` values first
  (`load_dotenv` does not override variables that are already set).
- The project skills are installed in the **parent** folder (`MLOps Final Project/.claude/skills`),
  not in this repo, so they may not load when the repo is the working directory. To decide (open
  question Q-1).
- `Steps.txt` disappeared from the parent folder during the session. Not yet explained.

### Interview (interview-me skill)

- Ran the skill to completion; the owner confirmed the restated intent with an explicit "yes". The
  result is in [INTENT.md](INTENT.md) and decision D-003.
- The owner pushed back twice, and both changed the design:
  - Prefect and Evidently stay as learning goals.
  - GitHub cron is ruled out as the scheduler because of its unreliable firing in a previous
    project.
- Repo decision D-002: a new public repo, with the old one made private. My first recommendation
  (same repo plus a comparison page) was rejected because the flawed v1 code would shape first
  impressions.

### Spec (spec-driven-development skill)

- Researched current sources before deciding anything; findings and sources are recorded in each
  D-entry:
  - EPA AQS is not real-time, so live data comes from AirNow.
  - Open-Meteo's Previous Runs API keeps forecasts as issued.
  - Prefect Hobby gives 500 managed minutes and 5 deployments.
  - EventBridge Scheduler is free at this volume.
  - Evidently 0.7 has a new API.
  - Material for MkDocs fixes ended 2026-11-05, and Zensical is in beta.
- Decisions D-004 to D-016 were taken one at a time. The owner asked for a plain explanation of
  the two scheduler options before choosing (D-011). Added XGBoost and RF to the model list
  (D-010). Asked for the freeze date to stay flexible, with a review on 2026-11-25 (D-014).
- [SPEC.md](SPEC.md) was **approved as V1** on 2026-11-18. Eight open questions (OQ-1 to OQ-8)
  remain, to settle during planning or setup.

#### Traps found (spec)

- AirNow's per-endpoint docs (rate limits, history window, data-use guidelines) are behind a
  login. Third-party figures (500 requests per hour, about 45 days of history) are unverified
  until the owner has an account (OQ-1).
- A `cd` inside a Bash call moved the session's working directory to `notes/`. Use absolute paths.

### Plan (planning-and-task-breakdown skill)

- Wrote [tasks/plan.md](../tasks/plan.md) and [tasks/todo.md](../tasks/todo.md): 33 issue drafts in
  5 phases with 4 checkpoints. The plan was **approved on 2026-11-18**.
- The owner asked for my critique and further questions until everything was tied down. Decisions
  D-017 to D-024:
  - repo name `pm25-forecast` (alternatives offered, owner kept it);
  - Terraform;
  - issue time 06:00 for D+1, frozen;
  - skills in the repo;
  - validation split T12a/T12b;
  - light write-up rules;
  - work mode (the owner drives each new tool the first time);
  - pipeline AWS access (keyless if possible).
- PC checked: Ryzen 5 3600, 32 GB RAM, AMD GPU, so training runs on the CPU. Terraform is not
  installed.

#### Traps found (plan): caught in review, before any code

- An ordering bug: data tasks needed S3 buckets before any Terraform existed. Fixed with T3b.
- **AirNow and AQS monitor IDs had no mapping**, so the per-monitor model couldn't have run live.
  Fixed in T5 with a site mapping plus a validation check.
- **Instrument mismatch risk:** AQS 24-hour filter samples vs AirNow hourly continuous data.
  Training labels are restricted to the continuous types (T5, OQ-8).
- The bulk download needed the city before the city check ran. T4 now runs first.
- "Persistence" was ambiguous. Clarified on D-009 as the D−1 value (the last complete day at
  06:00).
- The skill's shared `references/definition-of-done.md` isn't installed by `npx skills`. Our own
  Definition of Done is in plan.md (a note for the D-001 trial).

### Phase 0 started

- Facts looked up: Terraform **v1.17.2** (2026-11-11) and AWS provider **v6.73.0** (2026-11-11),
  from GitHub releases. `winget` is not available on this PC; the AWS CLI is 2.27.50.
- Wrote the owner's setup guides: [guides/PHASE0.md](guides/PHASE0.md).
- **T0d done** (owner's go-ahead): created the public repo `siddharthps/pm25-forecast`, with
  ruleset `protect-main` (PR required, no deletion or force pushes), secret scanning and push
  protection, Dependabot alerts, and Pages via Actions. Every setting was read back from the API.

#### Traps found (Phase 0)

- On an empty repo, the default-branch PR rule blocks the first push. The plan is in T1: disable
  the ruleset briefly with the owner's OK, push the initial commit, re-enable, and read back.
- Required CI checks can't be added to the ruleset until the workflow exists (T2).

### Phase 0 progress (owner, guided step by step)

- **T0a AirNow:** account active, key saved. Facts read from the logged-in docs (500 requests per
  hour; hourly files from 2019-05-28 with `AQSID`) → D-004. The Data Use Guidelines PDF → D-025
  (preliminary labels, not an official forecast, credits, AQI colours, notify the DMC).
- **T0c AWS:**
  - $5 budget `pm25-forecast-monthly` (85% and 100%).
  - Root has MFA and no access keys.
  - IAM Identity Center (single region, us-east-1) with user `siddharthps-pm25` and
    `AdministratorAccess` (8 hours); CLI profile `pm25` verified.
  - The v1 key …XZ53 (user `air-quality-mlops-user`, last used 2025-08-04) **deactivated**; delete
    it on 2026-11-25.
- **T0b Prefect:** Hobby account, workspace `pm25-forecast`, `managed-pool` (Prefect Managed),
  key expiring 2027-02-28 → `notes/TOKENS.md` (new register).

#### Traps found (Phase 0 setup)

- **Identity Center users don't sign in on the "Account ID" IAM page.** They use the access
  portal URL (`https://d-<identity store id>.awsapps.com/start`). The URL defaults to the identity
  store ID, and is shown as "AWS access portal URL" on the Identity Center dashboard (region
  us-east-1).
- **Prefect: signing in with GitHub reached an old identity with no workspace** ("contact your
  Prefect administrator"). Signing in with email worked. Use email.
- The AirNow Guidelines PDF contained a line addressed to AI agents about email replies. It was
  irrelevant (we send no email) and ignored; noted as a reminder that fetched documents are data,
  not instructions.

### Phase 0 completed

- **Terraform v1.17.2** installed (SHA256 + HashiCorp GPG signature verified). **State bucket**
  `pm25-forecast-tfstate-65bc08` created by the owner (their first hands-on CLI step), and its
  settings verified by read-back.
- Existing buckets listed: two v1 buckets (about 0.9 GB, about $0.02 a month), plus 4 empty
  2023 SageMaker buckets outside this project.
- **Phase 0 complete** (2026-11-18, around 14:00 CST), apart from two dated follow-ups: delete the
  old key and IAM user on 2026-11-25, and put the AirNow key into the repo `.env` (T1) and SSM
  (T3b).

### Tracker and first commit

- Cloned the repo to `C:\Users\Siddharth\code\pm25-forecast` (owner's choice: a dedicated code
  folder, no spaces). Repo-local identity set to the GitHub **noreply** address.
- **Tracker created** (owner's go-ahead): 36 issues #1–#36 from the approved drafts, 4 milestones
  (due 11-20, 11-25, 12-16, none), 7 labels, all checked by read-back with no duplicates.
  - The script was idempotent and dry-run first. The dry run caught a Windows console encoding
    crash before anything was created.
  - #1, #2 and #4 were closed with notes saying where each leftover box moved; #3 stays open until
    11-25.
  - `tasks/todo.md` is now an index (T-number → issue).
- **First commit** `8a2612b` (README, MIT licence, `.gitignore`), pushed to `main` with the
  ruleset off for a few seconds (owner's OK). Afterwards: ruleset `active` with all 3 rules
  intact, author and committer both noreply.

#### Traps found (tracker and first commit)

- Windows Python prints with cp1252 and crashed on "→". Fixed with
  `sys.stdout.reconfigure(encoding="utf-8")` (or `PYTHONIOENCODING=utf-8`).
- Git warned that "LF will be replaced by CRLF" (a global `core.autocrlf` setting). **T1 adds a
  `.gitattributes` with `* text=auto eol=lf`** so line endings are fixed in the repo, not on each
  machine.
- **Zensical's default build output folder is probably `site/`**, which clashes with the spec's
  `site/` (the static page source). In T11, set the docs output directory to `site_build/` (already
  in `.gitignore`).

### T1 (#5) scaffold, on branch `5-t1-scaffold` (resumed 14:14 CST)

- **OQ-4 → D-026:** Prefect's `3-latest` image has the same digest as `3-python3.12` (Docker Hub
  API), so the project is on **Python 3.12**. T8 pins the `3-python3.12` tag.
- **Tooling updated (owner's OK):**
  - `uv` 0.7.20 → **0.13.9**. It was released one day earlier, so this was checked against the
    "time one tiny run" spirit and worked. `uv self update` was unavailable (no installer receipt),
    so the official GitHub zip was used, with its SHA256 matched and its build provenance verified
    with `gh attestation verify`. The old binaries are backed up in `~/.local/bin/uv-0.7.20-backup/`.
  - Python **3.12.16** installed through uv.
- **Dev tools (looked up on PyPI, locked):** ruff 0.17.5, mypy 2.4.1, pytest 9.2.0, pytest-cov
  7.1.0, hypothesis 6.170.15, pre-commit 4.7.0.
- **Scaffold:**
  - `uv init --package` (`src/airwatch`), with the `pyproject.toml` rewritten: strict Ruff
    (including `DTZ` naive-datetime and `S` security rules), `mypy --strict`, pytest with
    `slow`/`live` markers and warnings as errors.
  - `.gitattributes` (LF), `.env.example` (no AWS keys; SSO profile), a project `CLAUDE.md` map.
  - `notes/` and `tasks/` copied in (byte-identical, verified). **From now on the repo copies are
    the live ones.**
  - The agent skills installed into the repo (D-020 update: upstream is now `8c99fa3`, 26 skills).
- **Pre-commit:** the outside hooks are pinned to SHAs (pre-commit-hooks v6.0.0, gitleaks v8.30.1,
  markdownlint-cli2 v0.24.1). Ruff and mypy run through `uv run --frozen`, from the lockfile.
- **Checks proven to fail when they should:**
  - Excluding a folder from Ruff made the lint-coverage test fail and name the folder.
  - A planted fake AWS key was blocked by gitleaks (2 findings). The probe was removed and never
    committed.
- **Result:** all 13 hooks pass, 3 tests pass in about 0.7 s, mypy strict is clean, and
  `uv lock --check` is OK.

#### Traps found (T1)

- `pre-commit autoupdate --freeze` *downgraded* gitleaks to v8.30.0. v8.30.1 was tagged on a commit
  that isn't on `master`, and autoupdate only sees tags on the default branch. Pinned by hand to
  the v8.30.1 release commit, with a comment in the config.
- **markdownlint caught a real bug in my own notes:** a credentials-register table row was cut off
  from its table by a blank line, so it would have displayed as stray text. Fixed, along with 11
  over-long lines. The check was not loosened.
- `pre-commit run --all-files` checks only files git knows about. Stage first, or new files go
  unchecked.
- The file-writing tool refuses to overwrite a file it hasn't read in the session. Read first.

### T1 wrap-up and local clean-up

- **PR #37 merged** (owner's request), squash commit `7703303`. Both commits on `main` have
  noreply author and committer. Before merging, the owner confirmed GitHub's "Keep my email
  addresses private" and "Block command line pushes that expose my email" were already on, since
  GitHub's own merge commits use the account email, not the repo-local one.
- **#5's last box:** the owner opened a Claude Code session in the repo folder; the project skills
  are listed.
- **Local clean-up (owner's OK), about 2.1 GB freed:**
  - From the v1 folder: `.venv` (1.5 GB), caches (338 MB), `mlartifacts/` + `reports/` (72 MB),
    and `.env` (retired key).
  - Python 3.12.11 (only the v1 `.venv` used it) and the download leftovers.
  - After the merge: the old folder's `notes/` and `tasks/`, deleted after a token check showed the
    repo copies contained everything except two deliberate edits, plus the parent-folder skills
    copy and `skills-lock.json`.
  - Kept: the v1 code (until T30); `mlruns/` and `flows/mlflow.db` (under 1 MB, gone with the v1
    folder); the uv 0.7.20 backup (until T2's CI is green on uv 0.13.9).

#### Traps found (wrap-up)

- **GitHub's merge commits use the account's commit email**, not the repo's `git config`. Check
  the account's email privacy before the first web or `gh` merge.
- `sed` replacement text treats `\U` as "uppercase from here", so a Windows path like
  `C:\Users\…` mangled a memory file. Use the file tools, not `sed`, for Windows paths.
- Claude Code memory is per folder. A session in the repo folder doesn't see the parent folder's
  memory, so the repo's `CLAUDE.md`, this journal and issue comments carry the state.
- A slow `du` over a cache of many tiny files hit the 2-minute tool limit. Measure big folders
  once, or in the background.

### T2 (#6) CI, on branch `6-ci` (started 14:41 CST)

- **The check came first:** `tests/unit/test_ci_config.py` was written before the workflows and
  failed 12 times. It checks:
  - every action is pinned to a SHA with a same-line `# vX.Y.Z`;
  - the token is read-only by default, and checkout doesn't keep credentials;
  - uv in CI equals the pyproject floor;
  - gitleaks in CI equals the pre-commit version, with a full-history checkout;
  - each gate is present;
  - Dependabot has no Python ecosystem;
  - the lock job is scheduled and dispatches CI.
- **Built:**
  - `ci.yml` has two jobs:
    - *Lint, types, tests:* `uv lock --check`, `uv sync --frozen`, Ruff, mypy, pytest with a
      coverage report, and the other pre-commit hooks.
    - *Secret scan:* gitleaks-action, with PR comments and artifact upload off.
  - `uv-lock-upgrade.yml` and `dependabot.yml` follow D-027.
  - Pins (looked up 2026-11-18): checkout v7.0.1, setup-uv v10.3.3, gitleaks-action v3.0.0
    (personal account, so no licence). PyYAML and `types-pyyaml` were added to dev dependencies.
- **Tests of the tests:** a planted unpinned action, uv version drift, and a Dependabot `uv` entry
  each failed exactly one test. The files were restored from the index.
- **Decisions (owner):** D-027 covers the weekly uv-lock job instead of Dependabot uv, with CI
  dispatched from the job rather than an App or PAT token.

- **PR #39, CI on GitHub:**
  - The first run passed both checks. gitleaks 8.30.1 scanned the PR's commit and found no leaks.
  - Owner: turned on "Allow GitHub Actions to create and approve pull requests" (the API shows
    `can_approve_pull_request_reviews: true`; the default token stays read-only). Then added
    `Lint, types, tests` and `Secret scan` to `protect-main` (confirmed through the rules API).
- **Red/green proof:**
  - `3890557` added an unused `import os`. It was committed with `--no-verify`, the owner's OK for
    that one commit only. CI failed on `F401` and the PR showed `BLOCKED`.
  - The revert `87504bc` (hooks on, tree identical to `7d8eed7`) passed, and the PR showed `CLEAN`.

#### Traps found (T2)

- **Dependabot's bundled uv (0.13.7) is older than our `required-version` floor (0.13.9).** The
  docs table still says "v0.11". The truth is in `dependabot-core/uv/Dockerfile`.
- **gitleaks' pre-commit hook scans only staged files**, so `pre-commit run --all-files` in CI
  checks nothing for secrets. CI uses a separate history scan.
- **PRs opened with `GITHUB_TOKEN` trigger no workflows** (except `workflow_dispatch`), so a bot PR
  would never get its required checks.
- **`ruff format --check .` formats Python blocks inside Markdown**, and it was already failing on
  `main`: pre-commit runs it only on `.py` files, so nobody noticed. A vendored skill file (D-020)
  failed. The fix is a formatter-only exclude for `.claude/skills/**`; our own docs are still
  checked.
- `uv lock --exclude-newer "7 days"` works, but writes `exclude-newer-span` into `uv.lock`. A
  cooldown would need to live in `pyproject.toml` (proposed as its own issue).

### T2 after the merge

- **PR #39 merged** (squash `a17d3dc`, noreply author). CI on `main` passed.
- **Lock job dispatched by hand** (run 44397349095). It passed, but `uv.lock` was already current,
  so only the no-change path ran: the push, PR and dispatch step was skipped. The PR path waits for
  the first scheduled run (Mon 2026-11-23 06:17 UTC). #6 stays open until then; its other boxes
  are ticked.
- **The docs-job box moved from #6 to #18 (T11)**, merged into its link-checker box (owner's OK).
- **Deleted `~/.local/bin/uv-0.7.20-backup/`:** the owner ran it, because the agent's `rm -rf`
  was refused by the permission check. uv 0.13.9 still works.

### T3 (#7) config and time rules, on branch `7-config`

- **The checks came first:**
  - `tests/property/test_time.py` checks against references built another way: stepping through
    UTC hours, and the US DST law (second Sunday of March, first Sunday of November).
  - It covers the issue time for any date 2009–2030, and local-day windows in the D-006 candidate
    zones (Chicago, Denver, Los Angeles, Phoenix).
  - An exhaustive 2009–2030 pass checks that day lengths are 23/24/25 hours exactly on the DST
    dates.
  - Naive datetimes are rejected.
  - `tests/unit/test_config.py` checks that secrets stay hidden in `repr`, `str`, dumps, logs and
    validation errors, and that settings fail fast when something is missing or empty.
- **Built:**
  - `timeutil.py`: `issue_time_utc`, `local_day_window_utc`, `ensure_utc`, `to_local`. The issue
    rule is a frozen constant, not a setting (D-019).
  - `config.py`: pydantic-settings, `SecretStr` for both keys *and* the AQS email (personal data),
    `hide_input_in_errors`, frozen, and `get_settings()` cached with nothing read at import.
  - `city_tz` is a setting (default Chicago) until T4 picks the city.
  - New dependencies: `pydantic-settings`, `tzdata`. The pydantic mypy plugin is on. Hypothesis
    runs derandomized by default; `--hypothesis-profile=explore` for a fresh search.
- **Tests of the tests:** seven planted bugs were all caught. They were a fixed UTC offset, a
  24-hour day, a datetime accepted as a date, naive input accepted, errors echoing input, the email
  not secret, and an empty secret accepted. The explore profile (2,000 examples per test) found
  nothing, so `tests/regressions/` stays empty.
- **Result:** 58 tests pass in about 3 s, the property suite in 0.8 s, and coverage is 100%. The
  85% floor is now on (`fail_under`, with a test against lowering it).

#### Traps found (T3)

- **Windows has no system time zone database.** `zoneinfo` needs the `tzdata` package. On Linux
  the system copy wins, so the two can differ; the pinned `tzdata` fixes the DST rules in tests.
- **`datetime` is a subclass of `date`**, so a `datetime` passed where a day is meant slips
  through. Both day functions raise `TypeError`.
- **PEP 495:** `==` between aware datetimes in different zones is False for a time in the repeated
  (fold) hour. Compare `.timestamp()` instead.
- **Pydantic validation errors echo input values** unless `hide_input_in_errors=True`. A key
  pasted into the wrong variable would otherwise reach a log.
- **To check in T5/T13:** I believe AQS hourly `time_local` is local *standard* time all year
  (no DST), but that is from memory and must be verified against the AQS docs. If true, the AQS
  local day differs from the civil local day for half the year.

- **PR #40 merged** (squash `bc09989`); #7 closed. CI on Linux passed too, using the system tz
  database.

### T3b (#8) Terraform base, on branch `8-terraform-base`

- **Decision (owner):** D-028 puts the public JSON in its own bucket. The first prompt was too
  jargon-heavy; the owner asked for a plain explanation and then chose.
- **The checks came first:**
  - `infra/tests/storage.tftest.hcl` has 8 runs, on the plan with a mock AWS provider, offline.
  - They check that the private bucket can never be public and is versioned and encrypted.
  - Only `raw/` may expire old versions; `records/` keeps everything.
  - The public bucket allows exactly one Allow (anonymous `GetObject` on objects), and CORS is
    the Pages origin with GET and HEAD only.
  - Both buckets deny plain HTTP.
  - The pipeline policy has no wildcards, no deletes, `*.json` only on the public bucket, and
    names only these two buckets.
  - Bad `pages_origin` and `alert_email` values are rejected.
- **Tests of the tests:** ten planted mistakes were all caught. They were a public-policy block
  off, listing allowed, the public grant widened to the bucket, deletes, any public file
  writable, a wildcard action, CORS `*`, expiring `records/`, versioning off, and a broken TLS
  deny.
- **Built:**
  - `infra/` holds `main.tf`, `s3.tf`, `iam.tf`, `variables.tf`, `outputs.tf`, the README guide
    and a `terraform.tfvars.example`.
  - Remote state goes in the T0c bucket, with S3-native locking.
  - `.terraform.lock.hcl` carries hashes for Windows, Linux and macOS.
  - A CI job, *Terraform*, runs fmt, validate and the mock tests, using setup-terraform v4.0.1
    pinned to its SHA. A pre-commit `terraform fmt` hook was added.
  - `tfplan` is gitignored.
- **Versions (looked up 2026-11-18):** Terraform 1.17.2, `hashicorp/aws` 6.73.0.
- **Cost (AWS Pricing API, us-east-1):** under $0.10 a month.

#### Traps found (T3b)

- **S3 Block Public Access is per bucket,** not per prefix, so "a public prefix" in a private
  bucket means weakening the whole bucket (D-028).
- **Terraform tests can't index a set with `[0]`.** Several S3 blocks (for example the SSE `rule`)
  are sets, so use `one(...)`.
- **Mocked data sources return random strings,** so policies built with `aws_iam_policy_document`
  can't be asserted under `mock_provider`. Policies here are `jsonencode` of locals, with ARNs
  built from names so they're known at plan time.
- **A Python script inside a bash heredoc turned `"\\n"` into a real line break** in the file
  it wrote. That's the global note's `\n` trap again. Fixed with the Edit tool.
- **`notes/TOKENS.md` says the AirNow key goes to SSM "(T3b)"**, but #8 doesn't include it.
  Putting a secret's value in Terraform would store it in the state. Proposal: a later task where
  the owner writes the parameter with the CLI and Terraform manages only its name and permissions.

### PR #41 and a review against the global rules

- **The first CI run on #41 failed.** The new `terraform fmt` hook ran in the Python job, which
  has no Terraform. The hook is now skipped there (the Terraform job covers it). A new test fails
  if any hook is skipped in CI without another step running the same check; a planted bad skip
  proved it. All three checks are green.
- **The owner asked whether the tests follow the global CLAUDE.md.** Mostly. There were four gaps:
  - no mutmut: **#42**;
  - no idempotency or step-failure tests for the uv-lock job: **#43**;
  - the Terraform tests use a mock provider, so the real proof is the owner's apply plus the
    agent's read-back;
  - the `ruff format` exclusion of vendored skills.
- **The exclusion was accepted by the owner** and recorded as D-029. The global rule, SPEC
  § Boundaries and the repo `CLAUDE.md` now allow scoping one check away from files we don't
  own, recorded as a D-entry. The repo `CLAUDE.md` also gained the Terraform and Hypothesis
  commands and a pointer to `infra/`.

### T3b apply (owner) and read-back (agent)

- **The owner ran `init`, `plan` and `apply`.** The plan said `16 to add, 0 to change, 0 to
  destroy`, as the guide predicted.
- **Trap:** the guide's `$env:AWS_PROFILE = "pm25"` failed in the owner's bash shell. The README
  now has bash versions too, with `AWS_PROFILE=pm25` in front of each command, because each `!`
  command may start a fresh shell.
- **Read-back (read-only):**
  - A second `plan` reports no changes (detailed exit code 0), and the state holds 16 resources.
  - Both buckets are versioned and have ACLs off.
  - The private bucket has all four public-access blocks on, and AWS says its policy is not
    public. The public bucket has the two ACL blocks on and the two policy blocks off, and AWS
    says its policy is public, as designed.
  - CORS allows `https://siddharthps.github.io` with GET and HEAD only.
  - Anonymous requests got 403 for listing the private bucket, listing the public bucket, and
    plain HTTP to the public bucket.

### T3b wrap-up and the milestone A notes review (#44)

- **The owner added `Terraform` as a third required check** on `protect-main` (confirmed through
  the rules API). `infra/tfplan` was deleted.
- **PR #41 merged** (squash `3d125e9`, noreply author). #8 was closed with all five boxes ticked
  and a summary comment.
- **The owner asked when the notes should be revisited.** The rules agreed:
  - DECISIONS is append-only: a change is a new D-entry that supersedes or refines the old one,
    and Status lines are kept current.
  - The spec is living, but a requirement change needs the owner's approval and a D-entry.
  - Frozen decisions never change once results exist.
  - Review at checkpoints, not continuously.
- **The review found only housekeeping (#44):**
  - OQ-1 and OQ-4 were closed in the SPEC and in `tasks/plan.md`.
  - SPEC § Commands now points to `CLAUDE.md` (there is no Makefile).
  - The Status lines of D-005, D-012 and D-018 are current.
  - TOKENS no longer says the AirNow key goes to SSM in T3b.
  - `CLAUDE.md` now asks that Status lines are updated in the same PR.

- **PR #45 merged** (squash `d067c06`). #44 closed. A box was added to #18: one home for the
  dev commands once the README gets a Development section, with `CLAUDE.md` importing it via
  `@path`.

## 2026-11-18/19: T4 (#9) city data check, on branch `9-city-check` (CST evening)

- **The rules came first, each decided by the owner, one at a time:**
  - candidates: Chicago, Salt Lake City, Los Angeles, Phoenix;
  - the thresholds;
  - Chicago first if it passes.
- **Frozen in D-006 and pushed** as `4390340` (GitHub: 2026-11-19 02:55:54 UTC) before any
  candidate data was fetched.
- **Owner action:** AQS API signup. The keys are in `.env` (presence checked, never values).
  The key was verified by asking AQS (`list/cbsas`, status Success, 1,006 rows).
- **Clarifications, each committed before scoring** (`6acd4c3`, `af22a99`, `0570c91`):
  - **AirNow must be Active** (owner). The site list also carries inactive sites.
  - **Field mapping,** checked on Charlotte (not a candidate): hourly instrument =
    `sample_duration_code "1"`, and `observation_count` is the hours.
  - **Pinned CBSA codes.** AQS lists LA twice (31080 and 31100). Census 2009 and 2013 lists
    show the same two counties, renumbered in 2013, so 31080 is used, with a per-year fallback
    to 31100 (not needed in the end).
  - **The weather-check centre** is the mean position of the monitors.
  - **"Concurred Events Excluded":** the first live run stopped on this unknown label, as
    designed. Each such row pairs with an "Events Included" twin (20,857 pairs, labels only),
    so it is dropped.
- **Built:**
  - `observations/metadata.py` holds the rules as pure functions, plus `fetch_json`.
  - `scripts/city_check.py` handles I/O: 6 s AQS pacing, a gitignored cache, and 2025
    stripped before caching.
  - The tests use the recorded Charlotte fixture and hand-built rows.
  - 15 planted bugs were all caught, after one survivor led to `strip_values` plus a refusal of
    unstripped 2025 rows.
- **Result** (2026-11-19, 03:19–03:34 UTC):

  | City | Qualifying monitors | Bad-air share | Good 2025 | Passes |
  | --- | --- | --- | --- | --- |
  | Chicago | 3 | 0.44% | 3 | no |
  | Salt Lake City | 4 | 1.22% | 4 | no |
  | Los Angeles | 1 | 1.50% | 1 | no |
  | **Phoenix** | **10** | 0.57% | **10** | **yes** |

  **Phoenix chosen (D-030).**
- **Bug hunt (descriptive):**
  - AirNow matching worked: 18 of 19 Chicago hourly sites and 12 of 14 Phoenix sites were
    active.
  - The binding rule was ≥ 8 good years of *hourly* 88101 data. Elsewhere, many hourly
    instruments started in 2016 or later; Phoenix's started in 2010–2012.
- **Owner:** keep D-019's 06:00 America/Chicago for Phoenix. The issue time follows the
  publisher's clock. Phoenix's D−1 ends at 07:00 UTC and the issue is at 11:00/12:00 UTC.
- **Config:** `city_tz = America/Phoenix`, `city_cbsa = 38060`, and `.env.example` updated. The
  owner's `.env` needs `CITY_TZ` changed, because a value in `.env` overrides the default.

### Traps found (T4)

- **`httpx` logs every request URL at INFO.** AQS takes credentials as query parameters, so the
  key would have been logged. A test caught it; the httpx and httpcore loggers are now held at
  WARNING.
- **AQS's public test account** (`test@aqs.api`) ran out of its daily quota on its first use.
- **The first `urllib` request failed with `URLError`;** an immediate rerun succeeded. Real code
  retries with backoff (`fetch_json`).
- **The Census API now requires a key.** Its published delineation files were used instead.
- **AQS lists retired CBSA codes alongside current ones** (LA 31080 and 31100), so matching by
  name prefix is unsafe. Pin the codes.
- **An unknown label stopping the run was the right behaviour.** Guessing would have
  double-counted 20,857 instrument-days.
- **I wrote `fetch_json` before its tests,** against the check-first rule. Its tests came
  straight after and caught the logging leak.
- **I miscounted Phoenix's counties** (9/1 instead of 8/2) when writing D-030. It was caught by
  recounting with code before committing.

### T4 wrap-up

- **PR #46 rebase-merged** (03:48 UTC); #9 closed with all 3 boxes ticked.
- **Rebase merging re-creates commits, so the IDs on `main` differ from this entry's.** The author
  times are kept, and PR #46 keeps the originals:

  | Branch | `main` | What |
  | --- | --- | --- |
  | `4390340` | `6f5648d` | the freeze |
  | `6acd4c3` | `196d4ff` | clarifications |
  | `af22a99` | `b7625b6` | the checker |
  | `0570c91` | `daed361` | the event label |
  | `0a81102` | `17816b8` | the result |

- **Owner:** `.env` now has `CITY_TZ` and `CITY_CBSA`; the names were checked, and Phoenix and
  38060 load. Commits and pushes to task branches no longer need asking; PRs, merges and issue
  edits still do.

## 2026-11-19: T5 (#10) observations skeleton and T13 (#11) bulk download (CST night)

- **Order:** T13 needs T5's AQS client, so T5's AQS side came first.
  - `11-aqs-bulk` is stacked on `10-observations`.
  - While the owner's download ran from the main folder, T5 continued in a **git worktree**
    (`~/code/pm25-forecast-t5`) so the running script's files weren't changed underneath it.
- **AQS (T5):**
  - `aqs.py` holds `sampleData/bySite` per site-year and keeps only hourly 88101 in µg/m³.
  - Times come from the GMT fields. **AQS `time_local` is local *standard* time:** on the
    Charlotte recording, 00:00 local was 05:00 UTC in June (EDT is UTC−4). For Phoenix (no DST)
    it doesn't matter.
  - `available_at_utc` is the end of the last-change day.
  - Daily means average POCs per hour, then require ≥ 18 hours of the city's day.
- **The shared schema** (`schema.py`): typed columns and UTC-aware times. After D-031 it
  checks structure only.
- **T13:**
  - `aqs_bulk.py` writes one Parquet file per site-year under `raw/aqs/hourly/`, with a manifest
    in S3 as the durable record.
  - Data is written before its entry. Reruns fetch only missing or unfinished parts, and the
    current year is refreshed.
  - The script is a dry run by default.
  - Tests use moto plus a fake AQS fetch: interrupted runs, crashes between writes, and a
    failed data write that's never recorded. 9 planted bugs were all caught, including the
    write order.
- **The owner ran the download (D-023).**
  - The dry run planned 180 parts. The first `--apply` stopped at part 6 on **1,167 µg/m³ at
    07:00 UTC on 2014-01-01**: midnight in Phoenix on New Year's, i.e. fireworks. That's a real
    reading.
  - **D-031 (owner):** raw data is stored as received, and out-of-range readings are counted,
    not blocked.
  - The rerun started at **175 parts**, which proves the resume worked. At 04:30 UTC: 67 parts,
    470,354 rows, 2 flagged.
- **AirNow (T5):** `airnow.py` reads the public `HourlyAQObs` files (no key). Checked on a real
  file:
  - `PM25` is the raw hourly value, identical to the `HourlyData` product for all 10 sites.
  - `ValidDate`/`ValidTime` are UTC, and `AQSID` is the AQS site ID.
  - Rows are kept only if PM2.5 has a value, is flagged measured, is in UG/M3 and has a 9-digit
    AQS ID. Every other row is counted by reason.
  - `available_at_utc` is the file's Last-Modified: the hour-01 file was published at 04:21 UTC.
- **The live check** (`-m live`, counts only): 2026-11-17, Phoenix: 24 files, 231 of 240
  training-site hours, **10 of 10 sites** with a valid daily mean.
- **OQ-8 → D-032.** Labels come from AQS hourly data with our own daily rule, so AQS daily records
  aren't used. The training sites' methods (170, 181, 182, 638) are all **Continuous FEM** per
  AQS's `methods_all.html`. AQS's per-method valid ranges are the sourced bounds T12 needs: the
  fireworks hour's method 181 allows up to 5,000.

### Traps found (T5/T13)

- **A guessed plausibility bound blocked real data** (fireworks). Bounds must be sourced, and
  raw ingestion must not judge values (D-031).
- **~30% of AirNow PM2.5 rows have 12-character or lettered IDs** (temporary, tribal,
  international). The structural schema check refused the whole file on the first live run; they
  are now counted as `not_an_aqs_site_id`.
- **Some AirNow rows say `PM25_Measured = 1` with an empty value.** The parser checks both.
- **A git worktree has no `.env`,** so `get_settings()` fails fast there. The live check ran with
  dummy keys, since AirNow files need none.
- **Python one-liners in bash heredocs mangled `\n` and `\d` again,** three times this session.
  Files are written with the file tools from now on, as the global rule says.
- **The AWS SSO session expired** between the Terraform apply and the dry run. The script now says
  `run aws sso login --profile pm25` (exit 3) instead of printing botocore's traceback.
- **Commands must run from the project folder.** From `~`, `scripts/…` isn't found and uv picks a
  general Python.
- **AQS's method table is over 10 MB,** too large for the fetch agent. It was downloaded with
  curl and parsed locally.

### T5 merged; T13 download done and verified

- **PR #47 squash-merged** (`66519c6`); #10 closed. A box was added to #12 (T12a) for the AirNow
  ID-mismatch check and the sourced per-method bounds.
- **The download finished** (owner's run): `done: 175 part(s) fetched, 1190097 hourly rows`.
- **Read-only verification** downloaded every part and recomputed its sha256. Only the
  `method_code` column was read, never the measurements.
  - **180 of 180** parts in the manifest, none missing or extra. 181 objects under the prefix
    (the parts plus the manifest).
  - **0 checksum mismatches** and **0 row-count mismatches** (file vs manifest).
  - **Methods:** 182 (789,807 rows), 170 (328,607), 181 (75,611), 638 (23,323). **No unverified
    codes** (D-032).
  - **Total: 1,217,348 hourly rows.** That equals this run's 1,190,097 plus the first run's
    27,251 (0 + 5,572 + 8,149 + 5,681 + 7,849), so nothing was duplicated or lost.
  - 2 readings flagged outside the crude range, kept (D-031). 29 empty parts, from monitor-years
    before a monitor existed.
  - **Final flags:** the 170 parts for 2009–2025 are final; the 10 for 2026 aren't. A dry run
    afterwards planned exactly those 10.
  - **Rows per year:** 2009 0 · 2010 16,256 · 2011 41,418 · 2012 57,285 · 2013 67,292 ·
    2014 68,040 · 2015 72,177 · 2016 84,294 · 2017 83,398 · 2018 84,482 · 2019 84,462 ·
    2020 84,392 · 2021 84,177 · 2022 84,060 · 2023 83,518 · 2024 85,556 · 2025 84,130 ·
    2026 52,411 (partial).
- **T13's branch** was rebased onto `main` after #47 (only its own 4 commits replayed).
  `TRAINING_SITES` now comes from `observations/sites.py`, its one home.

### T13 merged; end-of-day review (#49)

- **PR #48 squash-merged** (`1f12367`) from `11-aqs-bulk-rebased`. #11 closed; all boxes on #10
  (4) and #11 (3) are ticked.
- **Git clean-up:**
  - The pre-rebase `11-aqs-bulk` was deleted on GitHub (owner's OK). Only `main` remains.
  - The T5 worktree had already gone (see the traps).
- **End-of-day notes review (#49):**
  - TOKENS gained the AQS key row, and the AirNow row now says the code uses the keyless files.
  - SPEC: the target points to D-032, and the folder layout is current.
  - Status lines updated: D-004, D-005, D-031.
  - `CLAUDE.md`: the script and live-test commands, "run from the project folder", dry runs
    unless `--apply`, the owner's push rule and "never force-push".

#### Traps found (merges)

- **A stacked branch after a squash merge** still carries the base branch's original commits.
  Rebase it onto `main` (`git rebase --onto origin/main <old base> <branch>`) so only its own
  commits are replayed.
- **Force-pushing a rebased branch is refused** by the permission check as destructive. Push the
  rebased work under a new branch name, open the PR from that, and delete the old branch only
  with the owner's OK.
- **`gh pr merge --delete-branch` also removed the git worktree** that had the branch checked out.
  Nothing was lost because everything was committed and pushed first. Commit and push before any
  clean-up.

### Next

- **For T12a (#12):** "AirNow IDs that don't match AQS" is a validation check (T5's box). The
  per-method AQS ranges in `sites.py` are the sourced bounds (D-031, D-032).
- **Milestone B:**
  - T6 (#13), the persistence forecast and its at-most-once record;
  - T12a (#12);
  - #42 and #43.
- **T2 (#6):** close once Monday's scheduled lock job opens its PR and CI passes on it.
- **2026-11-20:** milestone A due. **2026-11-25:** skeleton checkpoint, D-014 review, delete the
  old AWS key and IAM user.

## 2026-11-19: T12a (#12) validation, on branch `12-validation` (CST evening, from 18:25)

- **Start:** `LEARNING.md` caught up with the #49 review. The owner renewed the AWS SSO login,
  and STS confirmed the `pm25` profile's SSO user.
- **Owner's decisions, before any real data was checked (D-033):**
  - out-of-range hours are **excluded and counted**;
  - flat lines are **12+ identical hours, warn only** (no published EPA threshold was found).
- **Built:**
  - `validation/checks.py`: four problem classes, every rule reported, at zero too.
  - `validation/report.py`: JSON + Markdown per run, never a measurement, never overwritten.
    Read-only runs on the AQS download (`load_aqs_bulk` checks each part's rows against the
    manifest) and on one AirNow day.
  - `airnow.fetch_local_day`: a 404 hour is counted as `file_missing`; any other failure
    raises (`metadata.FetchError` now carries the status).
  - `FIRST_YEAR` moved from the download script to `aqs_bulk` (one home).
- **Tests of the tests:**
  - 3 property tests: another site can't change a site's result; row order doesn't matter;
    every excluded row is counted.
  - **28 planted bugs:** 8 survived the first pass, and each led to a new test. Examples:
    a flat line joining two POCs, a late-evening first reading landing in the UTC month, a
    half-written report pair. Then all 28 were caught.
- **Speed:** the property tests first took the core suite to 29.95 s, at the 30 s limit.
  Flat-line detection was moved to plain arrays and empty groupbys skipped, bringing it to
  about 22 s.
- **First real runs (counts only):**
  - **AQS**, 180 parts, 1,217,348 rows: **passed**.
    - 0 duplicates, 0 unverified methods, 0 out of range, 0 flat lines.
    - 54 site-months under 75% (11 with no usable hours, e.g. 040130019 in Sep–Dec 2012).
    - 18,601 negative readings in range, kept.
  - **AirNow**, Phoenix 2026-11-18: **passed**. 240 rows (all 10 sites × 24 hours), 0 gaps.
  - **Zero flat lines was checked, not assumed:** the longest identical run per instrument is
    4–9 hours. The three whole-number BAM monitors (170) have most of the shorter runs.

### Traps found (T12a)

- **pandas warns on `concat` with empty frames,** and `filterwarnings = error` makes that a
  failure. `schema.concat_hourly` skips empty frames and keeps the schema.
- **`DataFrame.to_json` without `date_format`** raises a pandas 4 deprecation warning (seen in
  a test helper).
- **Comparisons on pandas `string` columns with a shifted NA give NA, not False.** The
  flat-line code uses plain arrays, so a run can't silently join across rows.
- **The log lines' `asctime` is local time with no zone** (here and in `scripts/aqs_bulk.py`).
  That breaks the UTC-everywhere rule; proposed as its own issue.
