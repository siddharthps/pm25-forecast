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

### T12a merged (#51)

- **PR #51 squash-merged** (`c8e0307`) and #12 closed. Three boxes are ticked. The fourth has a
  status note: the stop on a hard failure is built, and wiring it into the forecast is a box on
  #13.
- **Follow-ups:** a box on #13 and one on #20 (per-site AirNow ranges); #52 (log times in UTC)
  was created and listed in `tasks/todo.md`.

## 2026-11-19: T6 (#13) persistence forecast, on branch `13-forecast` (CST night, from 20:30)

- **Owner's decisions, before any real run (D-034):**
  - the record is named after the target day;
  - a thin monitor is skipped and listed, and no qualifying monitor means no record;
  - fail loudly until T9;
  - a strict issue-time cut.
- **Read the S3 docs first** (conditional writes and PutObject): 412 if the key exists, the
  first racing write wins, 409 (a racing delete) is retried. On a versioned bucket a delete
  reopens the key; `infra/` already allows no deletes and never expires a current record.
  moto 5.2.5 enforces the 412.
- **Built:**
  - `storage.py`: `S3Store` moves here (one home) and gains `create_if_absent`.
  - `forecast/record.py`: the keys, `build_record`, `write_once` (an existing record wins and
    is read back).
  - `forecast/publish.py`: `latest.json`, derived, rounded and "preliminary". It's never
    rewritten with the same content and never moved to an older day.
  - `forecast/run.py`: `run_daily` with injected edges. The command is a dry run unless given
    `--publish`, and exits 1 on any failure.
  - `config.public_bucket`.
- **Check first:** `tests/integration/test_forecast_once.py`.
  - Running twice writes one record version and one public version.
  - Each of six steps failing in turn (fetch, validate, compute, report, record, publish)
    leaves at most one record and never a public file without one, and the retry then
    completes.
  - Also tested: a racing writer's record wins; a dry run writes nothing; an early run is
    refused.
- **Leakage properties:** a row published after the issue time counts as if deleted, whatever
  its value; rows from the unfinished issue day never change the forecast.
- **24 planted bugs:** 6 survived at first, and each led to a new test (e.g. a run exactly at
  06:00, another full day overwriting the observed one, a dry run re-publishing). Then all 24
  were caught.
- **Speed (D-035):** the suite reached about 34 s (over 30). Profiling showed pandas' per-call
  overhead, not a hotspot. With pytest-xdist on 4 workers and `--dist load` it takes about 16 s.
- **First real run, a dry run:** at 03:07 UTC, target 2026-11-20 (issued 2026-11-19 12:00 UTC,
  observed 2026-11-18).
  - All 10 monitors were forecast, from 22 hours each. 20 rows were dropped as published after
    the issue time (2 hours × 10), as predicted from the rewrite timing.
  - Validation passed. Nothing was written to either bucket (checked by listing them).

- **First real publish (owner's OK), 03:14 UTC:** target 2026-11-20, 10 monitors, 20 late rows
  dropped. It was issued late (generated 21:14 Chicago), and the record says so.
  - A second `--publish` reused the record ("already_recorded"), with nothing rewritten.
  - **The 412 on real S3:** a deliberate second `create_if_absent` on the record was refused,
    and the record's sha256 was unchanged.
  - **Versions:** record 1, validation report 1, `latest.json` 1.
  - **Public access:** an anonymous GET of `latest.json` returns 200, and listing the bucket
    returns 403, as D-028 intends. The public file holds only the derived keys.

### Traps found (T6)

- **AirNow rewrites each hourly file for about 7.7 hours.** Last-Modified is the *latest*
  version, so a late run must cut by the issue time (D-034).
- **A `daily_means` rewrite gained nothing.** The cost is pandas' fixed overhead per call, so
  measure before optimising. It was reverted.
- **`pytest -n auto` on 12 cores was slower than 4 workers:** each worker's start-up (pandas,
  moto) outweighs the gain.
- **With xdist the summary no longer says "1 deselected".** `--co -n 0` confirmed the live test
  is still excluded.
- **A property test that drops its inputs before they matter proves nothing.** The first
  "issue-day rows" test gave them a publish time after 06:00, so the cut removed them first.

### T6 merged (#53)

- **PR #53 squash-merged** (`b07f35a`); #13 closed with all five boxes ticked.

## 2026-11-19: T7 (#14) public page, on branch `14-page` (CST night, from 21:25)

- **Facts looked up, not recalled:**
  - EPA's AQI TAD, **EPA-403/B-26-003, May 2026**. The fetch agent couldn't extract the PDF's
    text, so the saved PDF was read directly. The PM2.5 breakpoints are Table 6, p. 14; the
    truncation, Equation 1 and rounding are on p. 13; the standard colours are Table 2, p. 4.
    The TAD says the reporting area uses the **highest monitor**, which settled the city
    summary.
  - **Agencies**, from AirNow's `DataSource` field: Maricopa County AQD (7 monitors), Arizona
    DEQ (1), Pinal County AQCD (2).
  - **Pages** was already enabled (workflow builds), at `siddharthps.github.io/pm25-forecast/`.
  - The AirNow guidelines form hasn't been sent yet.
  - **Versions:** jsonschema 4.26.0; Biome 2.6.8 (published 2026-11-15); setup-node v7.1.0;
    upload-pages-artifact v5.0.0; deploy-pages v5.0.1. All are pinned to SHAs.
- **Owner's decisions (D-036):**
  - build now, and deploy only after the form is sent and any reply has arrived (the
    `PAGES_GO_LIVE` gate);
  - credit every planned source now. This went against the agent's recommendation, so each
    credit says what the source is used for.
- **Built:**
  - `aqi.py`;
  - `publish.py` v2 (city summary, history from the records, schema and secret scan);
  - `sites.py` names and agencies;
  - `storage.list_keys`;
  - `site/` (HTML, CSS, JS, with a CSP and text-only rendering);
  - `pages.yml`;
  - Biome, `node --test` in CI, and `.nvmrc`.
- **Tests:**
  - every expected AQI comes from the TAD (its worked example: 35.9 gives 102);
  - D-025's obligations are tested on the page's text;
  - 7 Node tests;
  - the workflow tests check the gate, the permissions and that only the page's files are
    published.
  - 19 planted bugs: 2 survived at first (a guard test that failed for another reason, and a
    test comparing a constant with itself), and both were strengthened. Then all were caught.
- **A real bug caught by a test:** the first `?data=` preview rule let `//evil.example/` through,
  which a browser treats as another site. The rule now refuses `//` and `..`.
- **Local preview** of the real 20 Nov record: Durango Complex is the highest monitor, at
  AQI 52 (Moderate). It was served on 127.0.0.1 only.

### Traps found (T7)

- **A Python script writing regexes inside a heredoc:** `\.` warns as an invalid escape. It
  still wrote the right text, but raw strings or the Edit tool are safer.
- **`sed` with nested quotes failed twice.** Edit or Write is the safe route on Windows (the
  owner's tool-trap rule).
- **pre-commit `--all-files` skips untracked files.** Stage new files before running a new hook,
  or it reports "no files to check".
- **The public bucket still holds the old-format `latest.json`** (v1) and no `history.json`. The
  next `--publish` run (the already-recorded path) writes both.

### T7 design review and merge (#54)

- **frontend-design review** (the owner chose the fixes plus the scale band; recorded in
  D-036):
  - the heading names the day;
  - a neutral palette (tested);
  - an AQI scale band as the hero;
  - monitors sorted by concentration, which fixed a table/summary mismatch the screenshots
    showed;
  - focus styles and a clear load error.
- **Screenshots via headless Edge.** A plain 390 px window clips at headless Edge's minimum
  width; a 360 px iframe gives the true phone layout.
- **PR #54 squash-merged** (`74e7292`). #14 stays **open** until go-live: four boxes ticked, and
  the D-025 box waits on the form.
- **After the merge**, the Pages workflow ran: "Package the page" succeeded and "Deploy" was
  **skipped** (the switch is off). The Pages URL returns 404, so nothing is public.

### Next

- **Go-live (#14), owner first:**
  1. Email the signed form: page 1 of `https://docs.airnowapi.org/docs/DataUseGuidelines.pdf`,
     to `dmc@airnowtech.org`. Ask whether AirNow informs the three reporting agencies or the
     owner should (the guidelines say derived products "must be made known" to them).
  2. After any reply, record it as a D-entry.
  3. Refresh the real public files to v2: a `--publish` rerun on the existing record, which
     writes `latest.json` v2 and `history.json` and leaves the record untouched.
  4. Set `PAGES_GO_LIVE=true` (a repository variable), dispatch the Pages workflow, and check
     the live URL.
- **Milestone B, after go-live:** T8 (#15) Prefect daily deployment (the owner runs the first
  deploy); T9 (#16) watchdog; T10 (#17) scoring; T11 (#18); #42, #43, #52.
- **Dates:** T2 (#6) closes after Monday 11-23's lock-job PR passes CI. **11-25:** checkpoint B,
  the D-014 review, delete the old AWS key and IAM user (T0c, #3).
- **Timeline honesty:** T6 and T7 are done; T8, T9, T10 and T11 remain before 11-25.

## 2026-11-20: comment audit (#55), on branch `55-comment-audit` (CST, to about 12:45)

A detour before go-live, at the owner's request. Go-live (#14) resumes on `14-go-live`.

- **Owner's choices:** the scope is code comments only (not docstrings, pragmas or config
  files), and decision records go to D-entries.
- **The check came first.** `airwatch.devtools.comments` counts comments per file against
  `comment-baseline.json`, and `--update` only lowers it. It runs as a pre-commit hook and a
  core test. The first commit set the baseline at 322 comment lines in 44 files. Planting bugs
  in it found two gaps in its tests: a regex literal after an operator, and a `/` inside a
  regex character class. Both now have tests. The one surviving planted bug can't change any
  result.
- **288 comments sorted** (`notes/comment-audit-2026-11-20.tsv`): 131 tautologies, 2 stale,
  5 excuses (4 issues, #56–#59), 150 decision records. Of those, 71 were already recorded, 28
  are new in D-038, and 51 moved into the code. The baseline is now `{}`, net 202 lines fewer.
- **`/delete-comment` skill** in `.claude/skills/delete-comment/`.

### Traps found

- **My comment dump hid comments.** It skipped any comment on a line already shown as context
  for the one above, so 5 went unlisted. The deletion script refused to touch comments that
  weren't on the list, and its report named them. Lesson: the tool that acts should also check
  that the list is complete.
- **"Already recorded" needs reading, not grepping for a D-number.** Three claims were wrong on
  a first check against the code: the SDK log level (ERROR, not WARNING), which scripts set it,
  and where the httpx fact lived (`fetch_json`'s docstring). The D-019 "constants, not
  settings" point wasn't recorded anywhere, so it went into D-038.
- **Computing a fixture from the code under test makes a test tautological.** `ISSUE_AT` is
  written as 06:00 Chicago converted to UTC, not as `issue_time_utc(TARGET)`.
- **A blanket `.claude/skills/**` lint exclusion would have hidden our own skill.** Both
  exclusions now list exactly the vendored skills (D-029 refined).
- **Windows Git Bash has no tz database for `TZ=…`:** `date` printed GMT. Use `zoneinfo` in
  Python for local times.

### Next

- PR for #55 when the owner asks. Then back to go-live on `14-go-live` (its journal "Next"
  section). Expect a small conflict in `notes/JOURNAL.md` and `notes/DECISIONS.md` when the two
  branches meet.

## 2026-11-20: go-live (#14), on branch `14-go-live` (CST, about 12:45 to 13:00)

- **AirNow replied** to the signed form (owner's summary): the data is public domain, and the
  email is a courtesy, not a licence step. Recorded as D-039 (D-037 and D-038 are taken by PR
  #60). The question of who tells the three reporting agencies is still unanswered. The page
  credits them first.
- **First forecast for a day still ahead:** `forecast.run --target-day 2026-11-21 --publish`
  (owner's OK). It recorded once with 10 monitors and wrote `latest.json` v2 and `history.json`
  (11-21 and 11-20). The run was after 06:00 Chicago, so the issue-time cut (D-034) decided what
  it could see.
- **Checked before the switch:** both public files return 200, and the bucket's CORS allows
  `https://siddharthps.github.io`.
- **`PAGES_GO_LIVE=true`** (repository variable, 18:53 UTC), then the Pages workflow was
  dispatched on `main` (run 44797001271). Both jobs succeeded.
- **Live:** `https://siddharthps.github.io/pm25-forecast/` returns 200 with the three
  "Preliminary, not validated" labels, the experimental-forecast notice and the partners link.
  Rendered in headless Edge, it shows "Forecast for Saturday, 21 November 2026", AQI 55,
  Moderate. Only the page's files are deployed (`README.md` returns 404).

### Traps found

- **S3 serves the JSON as `binary/octet-stream`.** That's harmless, because the page uses
  `fetch().json()`, which ignores the content type. Worth a `Content-Type` on upload if
  anything else ever reads these files.

### Next

- **The page goes stale after 11-21** until T8 (#15), the Prefect daily deployment, runs every
  morning. That's the next task.
- PR #60 (comment audit) merged. These go-live docs were replayed onto the new `main` as
  branch `14-go-live-docs` (no force-push), with the two append-only conflicts in `JOURNAL.md`
  resolved by keeping both sides in date order. #14 closes with that PR.
- Then T9 (#16), T10 (#17), T11 (#18) before checkpoint B on 11-25.

## 2026-11-20: T8 (#15) Prefect daily deployment, on branch `15-prefect-daily` (CST afternoon)

Start: after #60 and #61 merged and the finished branches were deleted. The page is live; T8 makes
it update every morning.

- **Docs first (D-024 said check before choosing):** Prefect Managed supports AWS web identity
  federation, so the run is **keyless**: an OIDC provider and the role
  `pm25-forecast-prefect-run` in `infra/prefect.tf`, with only the T3b pipeline policy.
  Prefect's token names the account, not the workspace, so the trust is our account ID plus the
  `prefect-cloud` audience, matched with `StringEquals`.
- **The run needs no secret at all.** AirNow's hourly files are public (TOKENS.md already said
  the API key wasn't used). So all three secrets became optional settings, and the AQS scripts
  ask for theirs through `aqs_credentials()`. A Secret block templated into `job_variables`
  would have been resolved at deploy time and stored with the deployment.
- **Owner's choices:**
  - dependencies are a hashed `uv export` of the lock, checked for drift, and regenerated by the
    weekly lock job;
  - compute minutes go in a ledger now, with the email moved to T9 (#16 edited, note on #15).
- **D-026 had already decided the image pin** (`prefecthq/prefect:3-python3.12`). I nearly left
  it at Prefect's default; reading the D-entries before deciding caught it.
- **Shape:** `flows/daily.py` only passes inputs to `forecast/job.py`'s `daily_job`. That job
  runs the forecast and then always files the minutes, before any failure is re-raised. The
  flow defaults to a dry run, and only the schedule passes `publish: true`.
- **Checks:**
  - 453 Python tests and 12 Terraform tests pass.
  - Six bugs planted in the ledger were all caught, after adding an upper-case run-ID case and an
    over-the-line warning test.
  - A planted wide trust policy (`StringLike`, `prefect:account:*`) fails the Terraform test.

### Traps found

- **A test that reads config from the wrong place passes vacuously.** `job_variables` sits under
  `work_pool` in `prefect.yaml`, so my no-secrets test was reading an empty dict. It now asserts
  that the env exists first.
- **Terraform's mock provider invents ARNs that fail AWS's ARN format check** when one resource
  passes an ARN to another. Give those mocked resources realistic `arn` defaults.
- **`prefect work-pool get-default-base-job-template --type prefect:managed` doesn't work
  offline:** managed pools exist only in Prefect Cloud. The owner's guide reads the template
  there with `work-pool inspect`.
- **D-026 to D-029 have no `---` separators,** so a `sed` range ending at `---` runs into the
  next entries. Use a script that finds the next `## D-` heading.

### Next

- PR for #15 when the owner asks. After it merges, the owner follows
  `notes/guides/T8-PREFECT.md`: account ID, Terraform apply (3 to add), CLI login, work pool,
  Federated Identity, deploy, a manual dry run.
- Then I check the ledger entry and the logs (reads only). The first scheduled run (06:00
  Chicago) should write the next day's record.

## 2026-11-20: T8 (#15) first deploy, owner-run (CST, about 13:30 to 20:30)

Start: after #62 merged. The owner ran each step of `notes/guides/T8-PREFECT.md`. I merged the
fixes as they came up and checked each result with reads only.

- **Terraform:** plan 3 to add, applied. The role ARN output matched `pm25-forecast-prefect-run`.
- **Prefect:** CLI logged in (workspace `siddharthpm/default`). `managed-pool` already existed.
  The owner set the pool's Federated Identity in the UI. Deployment `daily-forecast` created,
  with the 06:00 America/Chicago schedule active.
- **Fixes merged along the way:**
  - #63/#64 (PR #65): 30-minute run timeout (owner's choice), and the terraform-fmt hook no
    longer prints file contents;
  - #66 (PR #67): install our package from inside the clone;
  - #68 (PR #69): set the `airwatch` logger to INFO.
- **Runs:**
  - `bright-piculet`: Crashed in the pull steps (#66).
  - `invaluable-tiger`: Completed, but logged none of our lines (#68). It reused the existing 11-21
    record, so it fetched nothing. Ledger: 3 min.
  - `rose-ocelot` (`target_day=2026-11-19`, no record for that day): Completed. Logs:
    `2026-11-19: dry run, 9 monitor(s) forecast; nothing written` and the compute line (6 of
    500 min this month). In S3: a new ledger entry, no new record, public files unchanged since
    the 12:52 publish. No credential in the logs.
- **The owner formatted the local `terraform.tfvars`,** the last box on #64.
  `terraform fmt -check -recursive infra` passes.
- **D-040 status note:** the deploy, the two fixes, the default image
  (`prefect-client:3-latest`, so the D-026 pin matters), and a correction (`git_clone` does
  accept `commit_sha`).

### Traps found

- **The Prefect CLI crashes on the Windows console's cp1252 encoding,** sometimes after the
  action has happened (`deploy`, and `run --watch` after the run was created). Use
  `PYTHONUTF8=1`, and list the actual state before retrying.
- **`pip_install_requirements` and a pip target of `{{ clone.directory }}`:** the step outputs a
  bare folder name, so pip read it as a package name from PyPI. Run the install from inside the
  clone (`run_shell_script` with `directory`). A test now bans a bare template value as a pip
  target.
- **`PREFECT_LOGGING_EXTRA_LOGGERS` attaches Prefect's handler but sets no level,** so the
  logger's inherited WARNING dropped our INFO lines. The run still showed Completed, so only
  reading the logs caught it.
- **`terraform fmt -diff -recursive` printed a gitignored file's private values** (#64). Never
  use `-diff` where gitignored files sit inside the folder.
- **A dry run that reuses an existing record proves nothing about the fetch.** Pick a past day
  with no record to test the download.
- **`terraform -chdir=infra fmt infra/terraform.tfvars` fails:** `-chdir` moves first, so the
  path is relative to `infra/`.

### Next

- 2026-11-21 after 06:00 Chicago: check that the scheduled run wrote the 11-22 record and
  updated the live page. If it did, close #15.
- Then T9 (#16): the watchdog, plus the compute-minutes email.

## 2026-11-20: T9 (#16) watchdog, on branch `16-watchdog` (CST, about 20:40 to 21:30)

Start: after #70 and #71 merged; the first scheduled Prefect run is due 2026-11-21 06:00.

- **Docs first:**
  - Prefect: `create_flow_run` with a Bearer key; the body takes `parameters` and an
    `idempotency_key` (read from the installed client). A repeated key returns the existing run
    with HTTP 200 (Prefect's server code). Hobby has no service accounts.
  - AWS: Lambda's Python runtimes and dates, Scheduler's DST rules and context attributes, SSM
    and KMS permissions, SNS email confirmation, and the free tiers.
- **Owner's choices:**
  - a check-only 09:00 run after the 08:00 retry, with emails at both;
  - the minutes email once a month, through a create-once marker.
- **Shape:** `src/airwatch/watchdog/handler.py` (stdlib + boto3 only), zipped by
  `airwatch.watchdog.build` with boto3 and tzdata from a new `watchdog` dependency group
  (`requirements/watchdog.txt`). `infra/watchdog.tf` adds 13 resources. D-041 records it all.
- **A drill mode** came out of writing the guide: a test retry for a future day would have used
  up that day's real idempotency key. Drills get `watchdog-drill-<day>`, DRILL emails, and must
  target a day not yet issued, so their run stops as too early.
- **Checks:**
  - 507 Python tests (50 for the watchdog) and 19 Terraform tests pass. Watchdog coverage is 99%.
  - The real build runs twice and gives the same SHA-256, and the handler and boto3 import from
    the unpacked zip.
  - 23 planted bugs (16 in the handler, 7 in the Terraform) were all caught.

### Traps found

- **At DEBUG, botocore logs response bodies,** including the decrypted SSM key. A test with the
  root logger at DEBUG caught it. The Lambda pins the SDK's loggers at WARNING and logs at INFO.
- **`airwatch/__init__.py` reads the installed package's version,** so nothing in a bare zip
  can import `airwatch`. The handler is standalone, and tests check it agrees with the forecast's
  record key, ledger rules and target day.
- **A marker in the ledger's month folder would break `record_run`,** which sums every file there.
  The marker lives in `reports/compute-alerts/`.
- **Without `s3:ListBucket`, HeadObject on a missing key returns 403, not 404** (S3 HeadObject API
  reference). Our ListBucket grants are limited to prefixes, so instead of relying on how that
  condition applies to a HEAD, the record check lists the exact key.
- **`terraform test -filter=tests/x.tftest.hcl` on Windows matches nothing and still exits 0**
  ("could not be found"). Use a backslash. My planted-bug script first reported every Terraform
  plant as missed; it now refuses to run when the filter matches nothing.
- **A shared `.tfmock.hcl` (`mock_provider { source = ... }`)** keeps realistic mock ARNs in one
  place, once several test files apply the same resources.
- **Bash heredocs with quotes break on Windows** (the global notes already say so). Edit scripts
  go in the scratchpad.

### Next

- PR for #16 when the owner asks. After it merges, the owner follows
  `notes/guides/T9-WATCHDOG.md`: Prefect key, SSM parameter, two IDs, build, plan (13 to add),
  apply, confirm the email, then the drill.
- 2026-11-21 after 06:00 Chicago: check the first scheduled run, then close #15.

## 2026-11-20: T9 (#16) set up and drilled, owner-run (CST, about 21:20 to 21:45)

Start: after #72 merged. The owner ran each step of `notes/guides/T9-WATCHDOG.md`; I checked each
result with reads only.

- **Key and IDs:** the Prefect key `pm25-forecast-watchdog` was created (it expires 2027-02-28)
  and put in SSM `/pm25-forecast/prefect-api-key` (SecureString, `alias/aws/ssm`). I checked its
  metadata, never its value. The workspace and deployment IDs went into `terraform.tfvars`.
- **Build:** a 17 MB zip, SHA-256 `e6326c39…`. The Lambda's deployed code hash matches it.
- **Terraform:** plan 13 to add; applied; a second plan showed no changes. The owner confirmed the
  email subscription during the apply.
- **Drill:** four invokes, all as designed (D-041 status). The retry drill's run,
  `fragrant-turaco`, stopped as too early. It wrote no record and no public file, only its
  minutes (9 of 500 this month). The repeat got `already started`, with still one run.
- **Logs:** 4 INFO summary lines; no key-shaped string and no `Bearer`.
- **Follow-up in #73:** the zip drops uv's empty `.lock`, and the guide gets
  `MSYS_NO_PATHCONV=1`.

### Traps found

- **Git Bash rewrites a leading `/` in arguments into a Windows path.**
  `--parameter-filters Key=Name,Values=/pm25-forecast/...` silently matched nothing. Use
  `MSYS_NO_PATHCONV=1`, or a JMESPath `--query` on the name.
- **The AWS SSO session had expired** (8 hours, TOKENS.md) between the morning and the evening
  steps, so the first read failed. Log in again before each owner session.
- **`aws s3 ls` on an empty prefix exits 1:** in a chained check, that is not a failure.

### Next

- 2026-11-21 after 06:00 Chicago: check the first scheduled Prefect run (11-22 record, page), then
  close #15. At 08:00 and 09:00 the watchdog's real checks should stay silent.
- After #73 merges, the owner rebuilds the zip and applies the 1-change plan (the Lambda's code).
- Then T10 (#17), daily scoring.

## 2026-11-20: T10 (#17) daily scoring, on branch `17-daily-scoring` (CST, about 21:55 to 22:40)

Start: after #73 merged. The first scheduled run is due 2026-11-21 06:00.

- **Found first:** the run already computes each monitor's valid daily mean, because that's the
  persistence forecast. So `persistence` now calls a new `day_means`, the one home of the 18-hour
  rule for forecast and score.
- **Owner's choices:**
  - score day T on the T+2 morning from a fresh download, so all of T's hours have settled;
  - publish the actuals and errors in `history.json` now.
- **Built:**
  - `monitoring/score.py`: create-once scores under `reports/scores/`, a 7-day catch-up, and
    failures raised together at the end;
  - `publish.py` and the history schema: an optional `score` per day;
  - `job.py`: scoring after the forecast, and `history.json` rebuilt even after a failed day.
  - D-042 records it all; D-013's status updated.
- **Checks:** 534 Python and 13 page tests pass; scoring is fully covered; 18 planted bugs were
  all caught.

### Traps found

- **Backticks inside a `bash -c "..."` run as commands:** a docstring lost its word `day`. Use the
  Edit tool, or a scratch script, for any text with backticks.
- **A test fake published days before they happened:** the schema refused `available_at_utc`
  before `time_utc`. Each fake day is now published 3 hours after it ends.
- **The first 18-hour plant was in the wrong place:** it changed a reported count, not the rule,
  so no test could notice. The rule lives in `observations/aqs.py` (`MIN_HOURS`), and a plant
  there was caught.
- **An import cycle was avoided:** `publish` can't import `monitoring.score` (score → run →
  publish), so `score_key` lives with the other S3 keys in `forecast/record.py`.

### Next

- **Merge after the 2026-11-21 morning check, not before.** The first scheduled run then tests
  exactly the code that was deployed and drilled.
- 2026-11-21 after 06:00: check the scheduled run, then close #15. The watchdog stays quiet at
  08:00 and 09:00.
- 2026-11-22 06:00: the first real score (2026-11-20).
- Then T11 (#18), then the milestone-B follow-ups.

## 2026-11-21: the first scheduled run (#15), checked (CST, about 06:25)

- **`jade-seahorse`**, scheduled for 06:00 Chicago with `publish: true`, ended Completed. Its log
  reads `2026-11-22: recorded, 10 monitor(s), 0 without a valid day (published: True)`, and it
  took about 3 minutes (12 of 500 this month).
- **S3:** the record for 2026-11-22 was written at 06:01:26, with `latest.json` and `history.json`
  in the same second, after it.
- **The page** loads (HTTP 200). The public file it reads is served with the page's CORS origin,
  modified 12:01:26 UTC. It shows 2026-11-22: AQI 54, Moderate, 10 monitors.
- **Checkpoint B:** "a real forecast by the scheduled run, with no manual action" is met.
- #15 closes with T10's merge (#74), which adds scoring to the job, its last box.

### Next

- The watchdog's first real checks, 08:00 and 09:00, should stay silent.
- After 09:00: the owner rebuilds the watchdog zip and applies the 1-change plan (#73's `.lock`).
- 2026-11-22 06:00: the first real score (2026-11-20).
- Then T11 (#18), then the milestone-B follow-ups.

## 2026-11-21: the watchdog's first real checks failed, and the fix (CST, about 09:15)

- **What the owner got:** at 08:00 and 09:00, "The watchdog failed: the event needs
  scheduled_time as UTC", plus the error alarm. The fail-closed design worked; the backup didn't.
  The forecast was already recorded (06:01), and the watchdog started nothing.
- **The cause** (read from the schedules, `aws scheduler get-schedule`): their input held
  `\u003caws.scheduler.scheduled-time\u003e`. Terraform's `jsonencode` escapes `<` and `>`, and
  the scheduler substitutes only the literal placeholder. So the Lambda received the placeholder.
- **Why it got through:**
  - the Terraform test compared `jsondecode(input)`, which turns the escapes back;
  - the drill invoked the Lambda directly, skipping the scheduler-to-Lambda step;
  - the plan output showed `&lt;aws.scheduler.scheduled-time&gt;`, and I read that as HTML
    escaping in the terminal paste, not as a sign.
- **The fix, test first:**
  - the input is plain text;
  - a Terraform test checks the raw string (it failed on the old code);
  - the error email names the value it received;
  - the guide reads each stored input after apply.

### Traps found

- **Terraform's `jsonencode` escapes `<`, `>` and `&` as `\u003c`, `\u003e` and `\u0026`.** Any
  service that looks for a literal placeholder (EventBridge Scheduler's context attributes) won't
  see it. Test the raw string, never a decoded one.
- **A drill that skips the real trigger proves the target, not the wiring.** After apply, read
  what the trigger will actually send.

### Next

- The owner applies: rebuild the zip, then a plan of 3 changes (the two schedules, and the Lambda's
  code with #73's `.lock` cleanup). Then read the stored inputs.
- 2026-11-22: 06:00 brings the first real score; 08:00 and 09:00 are the watchdog's real
  end-to-end test.

## 2026-11-21: the watchdog fix applied and tested through the real scheduler (CST, to about 13:50)

- **#76 merged.** The owner rebuilt the zip (`f32c3b94…`, now without uv's `.lock`) and applied: 0
  added, 3 changed (the two schedules, and the Lambda's code). Terraform labelled the input
  change "whitespace changes", because it compares decoded JSON, the same blind spot as the old
  test. The stored inputs read back with literal `<` and `>`.
- **End-to-end test:** a one-time schedule, `at(2026-11-21T13:45:00)` America/Chicago, deleted
  after completion. It invoked a drill verify through the real scheduler. The log at 19:45:34Z
  reads `target_day 2026-11-22, record present`. No email; only the two real schedules remain.
- #75: four of five boxes ticked. The last is a silent 2026-11-22 morning. The test is now step
  7b of the T9 guide.

### Traps found

- **Terraform's plan hides an escaping-only change:** it shows "# whitespace changes", with the
  same decoded contents on both sides. A change shown there with no visible difference is still
  real.
- **A one-time schedule (`at(...)` plus `ActionAfterCompletion=DELETE`)** is a clean end-to-end
  test of any scheduler target: it fires once and leaves nothing behind.

### Next

- 2026-11-22: 06:00, the first real score (2026-11-20); 08:00 and 09:00, silent watchdog checks.
  Then close #75.
- T11 (#18) on the owner's go.

## 2026-11-21: T11 (#18) the write-up's setup, on branch `18-docs-stub` (CST, about 13:55 to 18:20)

- **Morning check deferred:** the owner asked for it at 13:52 on 2026-11-21, but every item (the
  run for 2026-11-23, the first score, the silent 08:00 and 09:00 checks) falls on 2026-11-22.
  #75 stays open.
- **Built, checks first:** the number check (`airwatch.devtools.docs_check`, with property tests),
  the macros module, the config tests, then Zensical 0.1.3, `results/results.json` (design counts
  and nulls), two skeleton pages, Vale, a CI `docs` job with lychee offline, `DEVELOPMENT.md` as
  the commands' one home, the README skeleton, `notes/STYLE.md` and `notes/OUTLINE.md`. D-043.
- **Proved by planting faults:** an undefined macro key and a broken anchor each abort the strict
  build; Vale fails on "very" and "robust"; the number check caught the pages' own "06:00"
  before clock times were allowed.
- **Not run locally:** lychee. Downloading and running its binary was refused by the permission
  check, so its first run is CI on the PR.
- **The write-up's plan, settled with the owner** (13 questions, one at a time, before any
  result): live numbers as a dated snapshot; count words banned in `docs/`; four charts drawn at
  build from pipeline data; a separate "How it runs" page; two reader levels; publishing at
  `/report/`, off until T28; live compared with all three baselines (CAMS saved daily) and
  split by forecaster; a reported-only bootstrap interval with a verdict rule. D-044, D-045
  (Frozen), D-009's status line. The bottom line now shows all three baselines (SPEC
  criterion 4).

### Traps found

- **Zensical's macros resolve files from the working directory,** not the config's folder. The
  macros module builds the path from `env.project_dir`.
- **A build folder under the project shows up in disk-walking scope tests:** Zensical's theme
  bundles JS and CSS into `site_build/`. Two tests now skip exactly that folder (D-029's rule).
- **The core suite is at the 30 s line on main too** (28.7 s warm, against 28.8 s on this
  branch): the property tests have grown since D-035's 15 s. That needs its own issue.
- **Git Bash's `sed` reads `\|` as "or":** a replace meant for a literal `\|` matched at every
  space and wrecked a page. Edit files with Edit or a scratch script, as the owner's rule says.
- **A Jinja filter inside a Markdown table cell breaks the row** (its `|` splits the cell).
  Nulls now show as *(pending)* without a filter.

### Next

- Issues created with the owner's OK: #78 CAMS saved daily (**next**, time-sensitive), #79
  `results.json` from the pipeline, #80 charts at build, #81 intervals and verdicts, #82 the
  `/report/` deploy kept off, #83 the 30 s budget. In todo.md's "Added along the way" table; T10
  ticked in plan.md (merged #74).
- Owner: open the PR; add `Docs build and links` to `protect-main` once it passes.
- 2026-11-22 after 09:15: the morning check, then close #75.

## 2026-11-21: #84 reviewed and merged; #78's timing corrected (CST, about 18:20 to 23:55)

- **Review of #84 found a hole:** a number typed inside a macro (`{{ 4.2 }}`,
  `{% if results.x > 5 %}`) passed the number check, because macros were skipped whole. Failing
  tests first, then the fix (dc610bc): only a macro's `results.…` path may hold digits. D-043
  updated to match.
- Merged as 7ae5b53 (2026-11-22 UTC), all four checks green; lychee's first run checked the
  site's links with no errors. #18 closed; T11 ticked in plan.md and todo.md.
- The owner added `Docs build and links` to `protect-main`; read back, it lists four required
  checks.

### Traps found

- **#78 was called time-sensitive, which overstated it.** The live record scores the model only
  on days it issued itself (D-044, question 12), and that starts at T23. So CAMS saving must be
  running before T23, not now. With the owner's OK, #78 moved next to T14 (which builds the CAMS
  download anyway), with a deadline of running and verified about a week before T23.

### Next

- 2026-11-22 after 09:15 CST: the morning check, then close #75.
- By 2026-11-25: the D-014 timeline review (Checkpoint B).

## 2026-11-22: #83 the core suite's speed, on branch `83-suite-budget` (CST, about 00:00 to 00:30)

- **Measured first:** three warm runs on `main`, 24–25 s as pytest reports it and 30–31 s wall.
  The tests themselves add up to 58 s across 4 workers (about 15 s each); the rest was fixed
  cost per worker.
- **Causes found:** the scope tests walked all of `.venv` (39,478 files) before dropping it,
  about 2 s per scan, five scans a run; and every worker imported Prefect (about 2 s) to
  collect two flow test files.
- **Fixed** with the same tests and examples: a pruned walk (`tests/project_files.py`, old and new
  results diffed, identical) and a `daily` fixture, with a static test against top-level Prefect
  imports. Collection 4.3 s to 2.2 s; paired with `main`, about 4.7 s faster; 26–28 s wall.
- **The limit (owner's choice, D-046):** CI fails the core test step past 75 s, through
  `tests/suite_budget.py`. Shown failing at 5 s, with and without coverage, and passing at 75 s.

### Traps found

- **This PC's speed drifts by a third within an hour** (validation properties at 2.9 s, then
  4.2 s), so a before-and-after timing is only fair in alternating pairs.
- **CI's runner varies even more:** the same commit took 26 to 45 s. A tight time limit there
  would be a flaky test.
- **Don't trust `-X importtime` under pytest:** test modules load through pytest's own importer
  and don't show up. cProfile on `--collect-only` found Prefect.

### Next

- One PR for `83-suite-budget`, with `78-cams-timing` (records only) merged in, so the journal
  can't conflict between two PRs. Tick #83 in plan.md once it's merged.
- 2026-11-22 after 09:15 CST: the morning check, then close #75.
- Then T14 (weather ingestion, with #78); the D-014 review by 2026-11-25.

## 2026-11-22: the morning check, then milestone B's small issues (CST, 12:25–13:40, 20:00–20:15)

- **The 06:00 run, `nano-pony`,** ended Completed. Its log reads
  `2026-11-23: recorded, 10 monitor(s), 0 without a valid day (published: True)`; about 3 minutes,
  15 of 500 this month.
- **The first real score:** the same run logged `2026-11-20: scored, 10 monitor(s)`. In the public
  `history.json`, 2026-11-20 has a `score` block: 10 scored, none without an actual. Its MAE and
  bias match a hand recomputation from the ten per-monitor errors (error = forecast − actual).
- **The page** loads (HTTP 200). `latest.json` (12:01:41 UTC) and `history.json` (12:01:51 UTC) are
  served with the page's CORS origin; `latest.json` shows 2026-11-23.
- **The watchdog stayed silent:** at 08:00 (retry) and 09:00 (verify), both logged
  `target_day 2026-11-23, record present`. The error alarm stayed OK, last changed 2026-11-21
  15:16 UTC. #75's last box ticked, and #75 closed with this evidence.
- **#83 ticked** in plan.md and todo.md (merged #85, 2026-11-22 06:36 UTC, D-046).
- **The owner's order for the rest of Phase 2:** the small issues and milestone A's two first;
  the D-014 review last. One branch per issue, none touching this journal (the session's entry
  lives here, on `83-tick-merged`), so the PRs can't conflict on it.
  - **#58** (`58-publish-test-ids`): schema cases named by `pytest.param` ids; a static test bans a
    bare `assert <param>` (it found exactly the two cases first).
  - **#59** (`59-leakage-assume`): `assume()` for an all-late draw. Hypothesis statistics showed
    the property mostly tested the trivial branch: 94% of examples (97% under `explore`) left both
    sites under 18 hours. Late rows are now a set of positions: 90% compare forecasts (95% under
    `explore`). A planted one-hour leak fails, shrunk to one row one second late (the old
    strategy caught that one too; the gain is coverage).
  - **#56** (`56-failure-log-type-only`): `failure_line` prints the message only for a
    `ReportableError` (new marker base for our own errors); the two bare `RuntimeError`s on the
    run's path got named classes. All four foreign-value cases fail on the old line.
  - **#52** (`52-utc-logging`): `airwatch.logutil.configure()`, lines like
    `2026-11-22T18:57:57.305Z ...`. The issue named three callers; `forecast.run`'s `main` was a
    fourth. Red on the old formatter; the real-`tzset` test ran on Linux (WSL), 9 passed.
  - **#57** (`57-airnow-poc`): AirNow's POC is `POC_NOT_GIVEN = -1`, enforced by the schema
    (owner's choice, D-047). EPA's formats allow 0; our AQS history before 2025 is all POC 3
    (1,080,807 rows); the live AirNow test passes.
  - **#43** (`43-uv-lock-script`): the job's push/PR/dispatch moved into
    `airwatch.devtools.uv_lock_pr`, run by path with no project installed. A test pins the old
    script's exact command sequence. Fake `git`/`gh` tests cover reruns and each step failing;
    five fail with the reuse guard removed. New: a create that errors is checked by listing again.
  - **#42** (`42-mutmut`, on top of `57-airnow-poc` so D-047 and D-048 can't conflict): mutmut
    3.8.1, on demand in CI or WSL (owner's choice, D-048). **First timed run** (WSL, 12 CPUs):
    65 mutants, 2 min 3 s, 51 killed, 14 survived. Killed with new tests: two `issue_time_utc`
    mutants (zone dropped) that passed only because WSL runs on Chicago time, and a `tzinfo`
    whose offset is `None`. **Explained:** the other 11 change only error-message text
    (`config._zone` 8, `aqs_credentials` 1, `_require_date` 2), which the tests don't pin by
    design. After: 54 killed, 11 survived, 1 min 50 s.
  - **#3** (`3-tokens-register`): TOKENS.md gains the GitHub CLI login and `GITHUB_TOKEN` (GitHub
    docs read 2026-11-22). `sts get-caller-identity` shows the Identity Center
    `AdministratorAccess` role. Its last box waits for 2026-11-25.
- **All nine branches merged together** in a scratch worktree: 666 passed, Ruff and mypy clean.
  Every pair also merges without conflict.
- **The owner delegated the open choices** (about 13:35: "you choose what is best and let me
  know"). Chosen: PRs for all nine branches, CI waited for by PR number, merges left to the
  owner; the three findings filed as #86 (scheduled run's error by type), #87 (the
  unfinished-day property's invalid examples) and #88 (one process-zone test helper), all in
  milestone C so Phase 2 doesn't grow; #78 moved to milestone C (label phase-3), matching
  todo.md. #3's "pipeline's narrow identity" box ticked after reading the role back:
  `pm25-forecast-prefect-run`, one attached policy `pm25-forecast-pipeline`.
- **CLAUDE.md** gained three rules from today: errors by type through `ReportableError`; this
  PC and WSL sit on the issue zone, so zone tests move the process zone; and how to run several
  issue branches in one session without journal or D-entry conflicts.

- **Merged (owner's go, about 20:00 CST, after a pause):** #89–#94 and #96 as squash merges;
  #95 after merging `main` into its branch (D-048 against #93's squashed D-047, the only
  conflict) and a fresh CI run; this records PR #97 last. The closed issues' boxes ticked; #43
  and #3 keep one open box each.

### Traps found

- **Prefect's CLI log output contains a non-ASCII byte (`µ`),** so `grep` called it a binary file
  and dropped the scoring line. `grep -a` reads it as text.
- **`aws logs filter-log-events --output text` splits multi-line messages,** which breaks
  line-by-line parsing. Read `--output json` instead, and compute epoch start times in code, not
  by hand (a hand-typed one returned nothing).
- **The AWS SSO session had expired** (it lasts 8 hours). A morning check needs
  `aws sso login --profile pm25` first.
- **A green property can test little:** only `--hypothesis-show-statistics` with an `event()` per
  branch showed #59's 94%. The same view shows the unfinished-day property discarding 1,220 of
  3,220 examples under `explore`, cause not yet known.
- **A test machine on the issue zone hides zone bugs:** this PC and WSL both run on Chicago time.
  Tests that matter move the process zone (`TZ` + `tzset`, POSIX only, so WSL and CI).
- **mutmut runs the suite in a copy:** with only `tests/` copied, every mutant stayed "not
  checked" in a few seconds (the clean run failed). Read `mutmut results` before trusting a run.
- **Windows can't delete a deep worktree** ("Filename too long"); `Remove-Item` with the `\\?\`
  prefix can, then `git worktree prune`.

### Next

- Tonight, Monday 06:17 UTC (00:17 CST): the first scheduled lock run, and the first with the
  new module (#94 is on `main`). Check that it opened or updated one PR with CI; that closes #6
  and #43's last box.
- 2026-11-25: #3's old key and IAM user deleted, the owner confirming first. Then the D-014
  timeline review, the last item of Checkpoint B.
- Follow-ups filed: #86, #87, #88 (milestone C); #88 is unblocked once #95 is merged.
- Then T14 (weather ingestion, with #78).

## 2026-11-22: the test-suite audit and its six groups (CST, about 20:15 to 21:15)

- **The audit (read-only first):** all 673 core cases read and measured. Before: 22.4 s with 4
  workers; coverage 1,794/1,810 lines (99.12%) and 390/404 branches (96.53%), 98.64% combined. The
  suite wasn't bloated: about 14 cases were redundant. The findings were one flake, weak
  assertions, copied setup code and about a dozen untested error paths. Report and live status:
  a private page (artifact `7bvtahBZQc1Z4mH9xScCnK`). The owner asked for the groups one at a
  time, each explained before any change; every group below was approved that way.
- **Group 1, #98** (`98-test-suite-correctness`): `test_2025_pm_values_never_change_the_result`
  failed under `--cov` (`DeadlineExceeded`; 180–224 ms per example against 200 ms) and now sets
  `deadline=None`. Strengthened: the AirNow drop count (exact, 43), six "city fails" tests
  (each asserts its reason), the step-failure test (one exception type and message per step;
  the old tuple was all `RuntimeError`s), one email count. One test was renamed. A planted
  mistake passed each old test and fails the new one.
- **Group 2, #99** (`99-test-suite-gaps`): 20 cases for untested paths, each pinning today's
  behaviour (no bugs found):
  - `validate_hourly`'s refusals (new `test_schema.py`), including `available_at_utc` equal to
    `time_utc`;
  - an AirNow file without `Last-Modified`;
  - the watchdog's real `_urllib_post` against a local 127.0.0.1 server;
  - five JS-scanner cases;
  - a `git diff` exit of 128;
  - the Unhealthy text colour;
  - a malformed AQS site ID.

  Planted mistakes showed the first four scanner cases missed a nested-brace bug, so a fifth
  was added. Dropped: two low-value branches, and `metadata.py:244`, which can't be reached.
- **#101** (`101-retryable-dead-line`, owner's choice: delete): `_retryable` takes the two types
  its caller catches; `test_fetch_json.py` passes unchanged. The only app-code change.
- **Group 3, #100** (`100-test-suite-redundancy`): 14 cases removed or folded:
  - `test_dst_days_are_in_range` ×6 and `DST_EXAMPLES` (no other test read the list);
  - `test_scoring_is_deterministic` (one process can't show set-order changes);
  - the logging DST unit test (×3), its three instants now `@example`s on the property;
  - `test_the_target_defaults_to_the_latest_due` and `test_a_real_retry_never_uses_a_drill_key`
    (assertions moved into a sibling);
  - three lock-upgrade workflow tests, now one in `test_ci_config.py`.

  A per-test coverage run (`--cov-context=test`, checked first on two tests known to own lines)
  found no line or branch only these covered. Missed lines and branches were identical in every
  file after.
- **Group 4, #102** (`102-test-suite-parametrize`): four parametrizations. The 09:00 verify case
  gained "starts no Prefect run"; a verify that contacted Prefect had passed.
- **Group 5, #103** (`103-test-helpers`) **and #88** (`88-process-zone-helper`): one home each for
  YAML/workflow/pre-commit reading (`tests/repo_config.py`), the import walk, the city-check
  history, the AirNow fixture, and the process zone (`tests/process_zone.py`, with its own
  tests). The test ids were identical before and after. Planted config mistakes and two broken
  zone helpers are caught. WSL ran the zone tests: 685 passed, none skipped.
- **Group 6 skipped (owner's choice):** sharing one moto per file in four files (34 starts,
  7.2 s of CPU) would save about 0.5–1 s of wall time. That's inside the 0.9 s run-to-run noise
  and below the 1 s bar, and it would cost per-test isolation.
- **After:**
  - 685 core cases, about 20 fewer test bodies;
  - 1,803/1,808 lines (99.72%) and 399/402 branches (99.25%), 99.64% combined;
  - what's still missed is deliberate: the two dropped branches, and the build lines only the
    `slow` test runs;
  - time is unchanged within noise: three runs each, `main` 23.8–27.8 s, the stack 23.2–23.5 s.
- **Branches are stacked** because each adds a row at the same place in `tasks/todo.md`: #98 ←
  #99 ← #100 ← #101 ← #102 ← #103 ← #88, so they merge in that order. This records branch is
  off `main` and touches only this journal.

### Traps found

- **`coverage json` re-reads today's source:** old data reported against changed files gave
  1,808 statements for a 1,810-statement run. Keep the JSON written at the time as the
  baseline.
- **A file named `.coverage.<x>.json` beside `.coverage.<x>`** is picked up as a data file
  (`file is not a database`). Write the reports to another folder.
- **A deadline flake needs coverage *and* parallel workers:** the test passed alone, even under
  coverage. `--hypothesis-show-statistics` gave the per-example time instead of a wait for the
  next failure.
- **Accepting `RuntimeError` accepts all of ours:** `ReportableError`s subclass it, so a test
  that means one error type needs `type(e) is X` or a message match.
- **A dict keyed by hook id hides a duplicated hook.** The shared lookup counts instead.
- **`serve_forever()` polls every 0.5 s,** so a local test server's teardown took 0.5 s per test.
  `serve_forever(0.01)` fixes it.
- **Bash heredocs turned `\\n` into a real newline** in a replacement script (the owner's notes
  already warn); multi-line edits went through the Edit tool.

- **Merged (owner's go, about 21:20 CST):** PRs #104–#110 as squash merges in the stack's order,
  each after its four required checks passed; then this records PR (#111). From #105 on, each
  branch conflicted with the squashed `main` (`tasks/todo.md` first, then two test files at
  #109), so `main` was merged into the next branch. That merge changed no file in the branch,
  and `main` matched the previous branch's tip. The final `main` is identical to the stack
  tested locally and in WSL (`5906a15`). Issues #98–#103 and #88 closed; #112 filed: mutation
  testing for the modules that hold the must-never rules.
- **Lessons recorded:** a "phase-end test check" section in the owner's global CLAUDE.md
  (weak tests first, mutation testing on the core, one or two PRs). In this repo's CLAUDE.md,
  issue branches leave `tasks/todo.md` to the records branch too, and the zone rule names
  `tests/process_zone.py`.

### Next

- Tonight's 06:17 UTC lock run (#6, #43), and #3 on 2026-11-25; then the D-014 timeline review,
  the last box of Checkpoint B.
- #112 (milestone C): time one module under mutmut before the full run.

## 2026-11-23: the dropped lock run, #114, and the lock PR's App token (CST, about 10:10 to 11:20)

- **The dropped run:** `uv-lock-upgrade.yml`'s cron (Mondays 06:17 UTC) never fired on
  2026-11-23; by 16:12 UTC the workflow had one run, the hand-started one from 2026-11-18. This is
  the GitHub cron risk D-001 names. Filed **#113** (milestone C): the watchdog starts the weekly
  lock run and the GitHub cron is dropped (owner's choice over a Cloudflare Worker, both $0; and
  over keeping the cron as a backup).
- **#114, started by hand (owner's OK):** run 45215418192 opened #114 (20 patch and minor
  upgrades: boto3/botocore 1.44.9, pydantic 2.14.4, redis 8.2.0, ruff 0.17.6, …), and the CI it
  dispatched passed. #43 and #6 were closed on that, then **reopened**: the merge was blocked.
  - **Trap:** the `main` ruleset doesn't count a `workflow_dispatch` CI run, even on the PR's
    head commit. The merge API said "4 of 4 required status checks are expected"; `gh pr merge`
    says only "the base branch policy prohibits the merge".
  - **Trap:** a PR opened by `GITHUB_TOKEN` *does* create `pull_request` runs, held at
    `action_required` until a person approves them (GitHub's "Triggering a workflow" page). D-027
    assumed no run at all. The owner's `--approve` review changed nothing; it wasn't the gap.
  - A first guess, the ruleset's `require_extra_approval_for_unattributed_changes`, was wrong:
    other repos report it adds nothing when the required review count is 0 (second-hand only).
  - Fixed by approving the held run (owner's OK); its checks passed and #114 merged (`2de110c`).
    The watchdog's zip changes with `requirements/watchdog.txt`, so the next `terraform plan`
    shows a Lambda update.
- **#115 (milestone B), PR #116:** the lock PR is opened with a private GitHub App's token
  (D-049, refines D-027): `actions/create-github-app-token` v3.3.0 (v3.4.0 is inside the 7-day
  cooldown), Contents and Pull requests write only, commits as the App's bot user, no dispatch.
  Tests first; three planted mistakes each caught. The owner created `pm25-forecast-lock`, set
  `LOCK_APP_CLIENT_ID` and `LOCK_APP_PRIVATE_KEY`, and the `.pem` was deleted (it was in the repo
  folder; `.gitignore`'s `*.pem` kept it out).
  - **Trap:** saving an App's permissions ("The GitHub App has been updated") doesn't grant them
    to the installation; it must accept them on its Configure page. Until then the token step
    fails with "The permissions requested are not granted to this installation" (two runs).
  - Run 45221876228 from the branch: the token minted; `uv.lock` was already up to date.
  - Run 45226966584 from the branch (pydocket 0.31.0 → 0.32.0) opened **#117** as
    `app/pm25-forecast-lock`: its own `pull_request` CI started with no approval and passed, the
    commit is linked to `pm25-forecast-lock[bot]`, and GitHub reported it mergeable. #116 merged
    (`a3c9128`, owner's OK); #115, #43 and #6 closed.
  - **Trap:** a run from an issue branch builds the lock PR on that branch, so #117 first carried
    #116's diff too. After #116 merged, a run from `main` (45227715893) force-updated it to the
    lock change alone, and its CI passed again.
  - #117 merged (`bc69595`, owner's OK) on its own checks, with no approval and no `--admin`: the
    first lock PR to do so. The owner then turned off "Allow GitHub Actions to create and approve
    pull requests" (API: `can_approve_pull_request_reviews: false`, default permissions `read`).

### Next

- 2026-11-25: #3's old key and IAM user deleted (owner confirms first); then the D-014 timeline
  review, the last box of Checkpoint B, counting #113.
- #113 (watchdog starts the lock run, using the same App if its D-entry finds it fits); #112.

## 2026-11-23: the D-014 timeline review (#120), and #119 held (CST, about 19:35 to 20:10)

- **The late cron:** the Monday 06:17 UTC lock schedule did fire, at 18:03 UTC (run
  45234243772), about 12 hours late, not dropped as the morning entry assumed. It opened **#119**
  as `app/pm25-forecast-lock`, and its own CI passed with no approval: the first scheduled lock
  PR under D-049. The lateness is more evidence for #113.
- **#119 held, not merged:** filelock 4.3.0 → 4.3.1, which PyPI shows uploaded at 18:01 UTC,
  two minutes before the run locked it. It's dev-only (pre-commit → virtualenv), so waiting costs
  nothing. Next Monday's run refreshes the PR, when the release is 7 days old.
  - Filed **#122** (milestone C): a 7-day cooldown on Python releases, as Dependabot keeps for
    Actions. A dry run (`uv lock --upgrade --dry-run --exclude-newer "7 days"`, uv 0.13.9, no
    file changed) accepts the relative cutoff but fails on `zensical==0.1.3`, an exact pin
    younger than 7 days. The fix needs a per-package rule and a D-entry. It's fill-in work, like
    the housekeeping D-050 names.
- **The D-014 review (#120, PR #121, `a455df0`):** held with the owner two days early, one
  question at a time. **D-050** refines D-014:
  - the dates are kept (cut line 12-16, freeze 12-23), with 30 owner hours to 12-16;
  - one check-in on **Sat 12-12** may move the cut line up to a week, by progress and free time
    only, and the freeze moves with it;
  - the cut order is unchanged;
  - #78, #79–#82 and #112 are required, and #113, #86 and #87 are fill-in;
  - the 14-day live check counts from T23 (SPEC criterion 1 and #35 edited);
  - soft waypoints are set for 11-29, 12-05, 12-12 and 12-16.
  - The owner went against the agent's suggestion on the check-in date (12-09 → 12-12) and
    withdrew a first answer of 45+ hours for the planned 30.

### Traps found

- **A pre-commit failure inside `git commit -q && git push` still pushed:** the commit and push
  were joined with a newline, not `&&`, so the failed commit left the branch pushed at `main`'s
  head. Chain the push on the commit's success.
- **`gh pr checks --watch` straight after `gh pr create`** said "no checks reported" again (the
  global rule's trap); a second call, once the run was queued, worked.

### Next

- **2026-11-25:** #3's old key and IAM user deleted (owner confirms first); milestone B then
  closes.
- **Sun 11-29 waypoint:** T14 (weather ingestion) with #78 (the CAMS forecast saved daily).
- **Mon 11-30:** #119 refreshed by the lock run; merge if filelock 4.3.1 isn't yanked.
- Fill-in: #122, #113, #86, #87.

## 2026-11-23/24: T14 (#19) part 1, on branch `19-weather` (CST, about 20:10 to 23:40)

- **D-051 (refines D-007), owner's choices one at a time:** ERA5 (`models=era5`) for training,
  NOAA GFS Global (`gfs_global`) for the test rebuild, the forecasts-only variant and live; 8
  variables (dew point out as a duplicate, boundary-layer height out: no forecast archive); each
  monitor's own coordinates; and **`_previous_day3` for every hour** of the target day.
  - **The spec's lead rule leaked.** `_previous_day1` for the first 24 h lands on runs started
    at or after 06 UTC on the issue day. Found from Open-Meteo's docs, then checked by matching
    `_previous_day2` against named runs: the archive takes the last run started at or before the
    offset (rounds down).
  - **The agent's first fix leaked too:** `_previous_day2` for every hour was worked out with
    Chicago's day, but the target day is Phoenix's (07 UTC to 07 UTC), so its last stamps land
    on the issue day's 06 UTC run. The owner was asked to decide before that premise was checked,
    then re-asked; lesson saved to the agent's memory (verify a premise with real data and a
    worked example before asking).
  - **72 h costs little:** GFS against ERA5 at Phoenix, February–December 2024 (development
    period, 8,040 hours): mean absolute error grew 1–4% from 2 to 3 days ahead.
  - The owner asked whether a different start time would be simpler; D-019's 06:00 is Frozen,
    and a 07:00 Phoenix start would let 48 h work with under 3 h of margin. A side-by-side table
    and "what happens when such a bug surfaces after a freeze" went into the owner's private
    learning notes.
  - **Facts that changed tonight:** the archive starts 2024-01-20 (GFS), not "January 2024";
    `gfs_global` is served from `ncep_gfs013`, whose runs appeared 5.35 h after starting
    (`ncep_gfs025`'s took 6.29 h, the figure first recorded). No GFS run from 2024–2025 is in
    the Single Runs API, so the offset archive is the only record of past forecasts.
- **Built, tests first, each with planted mistakes caught after a clean baseline:**
  - `weather/leads.py`, the 72-hour rule: a property test over every day 2009–2030 that every
    hour uses a run published before the issue time, given an 18 h delay, against a stepping
    reference; pinned tests show why not 24 or 48 h. Mutmut (WSL): all of its mutants killed,
    after two new tests (offset 7 untested; times with seconds). 106 mutants, 96 killed, the 10
    left are the message-text ones explained on 2026-11-22.
  - `sites.SITE_COORDS`, from AQS: within 1 km of the recorded AirNow file. AQS and AirNow differ
    by up to 571 m for one monitor (Glendale); the closest two monitors are 4.75 km apart.
  - `weather/openmeteo.py`: a `Query` per monitor and UTC days, units spelled out, responses
    refused by named rules, every row with its run and `available_at_utc`; the live run read
    before and after the data. Opt-in live checks pass on the real API.
  - `weather/bulk.py` and `scripts/weather_bulk.py`: the AQS download's rules, plus pacing.
- **The bulk download (owner's OK):** 190 of 190 parts in the manifest, each with its file
  (191 objects under `raw/weather/`). The first run (22:17 CST) stopped after 37 parts on a 429
  (below); the rerun (22:23 to 23:28 CST) fetched the other 153 (1,327,584 rows) with no error.
  - ERA5 2009-2024: every site-year complete (8,760 or 8,784 rows), 0 missing values.
  - GFS archive 2025 (the test year): complete, 0 missing values.
  - **GFS archive 2024:** the first 36 hours (2024-01-20 00:00 to 01-21 11:00 UTC) are empty
    for every variable, at every site: `_previous_day3` starts 2024-01-21 12:00 UTC, a day and
    a half after `_previous_day2`.
  - **GFS archive 2026 (not final):** `cloud_cover` alone is missing for 29 hours on
    2026-04-18/19 at all 10 sites. Both gaps go to the coverage check (T14 part 2) and T12b.

### Traps found

- **Pacing one window only:** the first run paced the hour and sent 37 year files (about 960
  counted calls) in 20 s; Open-Meteo answered 429 (600 a minute). The manifest held the 37, and
  the rerun planned the other 153. `CallBudget` now holds the minute, hour and day at half each,
  with a property test; one planted mistake (calls forgotten after half a window) survived it
  until the generator gained short gaps.
- **Open-Meteo weights requests:** over 10 variables or 2 weeks counts as several calls
  (pricing page); a site-year of our 8 variables is about 26.
- **A planted mistake "caught" by a test that always failed:** check that every test passes on
  the untouched code before planting. The longitude test moved the grid point closer, not away.
- **A guessed tolerance:** 100 m for "same monitor" failed on real data; it now comes from the
  closest two monitors.
- **Windows:** Python's `write_text` wrote CRLF into `pyproject.toml` (the line-ending hook
  stopped the commit); `\n` inside a shell heredoc became a real line break; `wsl.exe` from Git
  Bash drops quotes and rewrites `/mnt/c` paths (now in DEVELOPMENT.md); a worktree under the
  scratchpad couldn't be removed by git (path too long) and needed `rm -rf` plus `prune`.
- **A time quoted unchecked:** commit `016d932` says the first live check ran about 04:10 UTC;
  it was about 03:25 UTC. Left as pushed (no force-push).
- **The core suite** is back at its 30 s goal (main 22.1 s vs the branch 27.2 s back to back;
  29.9–33.5 s on other runs): filed **#124**. The bulk tests moved to `MemoryStore` (4.4 s to
  2.3 s), one still on the real `S3Store`.

- **A closing keyword inside a denial:** #125's description said it "doesn't close #19", and
  GitHub closed #19 on the merge (`3e6995f`), reading "close #19" as a keyword. Reopened at once
  with a comment. For a partial PR, write "Refs #N" and never put "close", "fix" or "resolve"
  next to the number.
- **Merges (owner's OK, given before bed: merge if the full suite passes):** #125 and this
  records PR, after the full suite passed on `main` with both merged together and each PR's own
  CI passed.

### Next

- **2026-11-25:** #3's old key and IAM user deleted (owner confirms first); milestone B closes.
- **T14 part 2 (#19), by the 11-29 waypoint:** the archive's coverage check (2024-01-21 12 UTC on),
  the CAMS download and its archive-bias check, and the daily live save with #78.
- Fill-in: #124, #122, #113, #86, #87.

## 2026-11-24: T14 (#19) part 2, on branch `19-weather-part2` (CST, about 05:35 to 07:15)

- **D-052, the CAMS check (owner's choice of run):** Open-Meteo's CAMS global history is
  **stitched** from each run's first 12 hours: 12 runs (2026-11-01 to 11-21) equal the history
  at every lead 0–11 h, 12 of 12, and at leads 12–23 h in 0–2 of 12. A real day-ahead CAMS
  forecast at our issue time is 31–54 h ahead. No offset archive exists for CAMS
  (`pm2_5_previous_dayN` empty everywhere); whole runs are kept only from 2026-04-02 (Single Runs
  API). So the 2025 test's CAMS baseline is the stitched history, a bar stronger than CAMS was
  live, and the gap is measured on 2026.
  - "As issued" is the issue day's 00 UTC run (owner, after a plainer re-ask: the first prompt
    was too dense). It was out 9.80 h after starting (one reading): 2.2 h before the winter issue
    time, 1.2 h before the summer one.
  - The gap's figures were declared in D-052 before any were seen; the first target day was
    corrected to 2026-04-03 (the first whose run is kept) before the run.
- **Built, tests first, each module's planted mistakes caught after a clean baseline:**
  `weather/cams.py` (36 tests, 7 plants; the as-issued rule as a property against a stepping
  reference, 2022–2030), CAMS in the bulk download, `weather/coverage.py` (10 tests, 6 plants)
  and `weather/cams_gap.py` with `scripts/cams_gap.py` (9 tests, 7 plants). Core suite: 836
  passed, 25.7 s.
- **The CAMS download (owner's OK):** 50 parts, 2022-08-04 to 2026-11-23, 0 missing values;
  12:01 to 12:05 UTC, with this year's 10 GFS parts refreshed.
- **The coverage check on the real bucket:** 240 of 240 planned parts, 0 failures. Gaps: the GFS
  archive's 36-hour lead-in in 2024 at every monitor, and `cloud_cover` 2026-04-18 13:00 to
  04-19 17:00 UTC (29 h) at all 10. Nothing else.
- **The gap run (12:11 to 13:05 UTC; reads only):** 2,271 monitor-days, 2026-04-03 to 11-22.
  MAE against observed: as issued 6.16 µg/m³, stitched 5.61, difference 0.55 (the stitched
  history's error about 9% smaller); mean absolute difference between the two CAMS means 1.93.
  Skipped 69: 10 without an as-issued run (the missing 00 UTC run of 06-25, target 06-26, all
  10 monitors), 59 without a valid observed day; none for incomplete CAMS or failed validation.
  Summary: `data/reports/cams_gap/cams-gap-2026-11-24.json` (gitignored). The write-up takes the
  figures through `results.json` (#79), never typed.
- **#78's terms, looked up for its D-entry:** Open-Meteo data is CC BY 4.0 (credit, licence
  link, changes indicated; a link where the data is shown); the Copernicus licence (v1.2) allows
  any lawful use including public display of modified values, with "Contains modified
  Copernicus Atmosphere Monitoring Service information [Year]" and a statement that neither the
  European Commission nor ECMWF is responsible for the use. The free API is non-commercial.

### Traps found

- **The AWS login expired 52 s after the dry run;** the first `--apply` stopped at its first S3
  call and wrote nothing. Its task reported exit 0 because an `echo` followed it: the script
  itself exits 3 on a login error. Logs now end with the script's own exit code.
- **A missing CAMS run answers two ways:** inside the kept span, 200 with every value empty;
  before it, an error naming `cams_global_greenhouse_gases`. Both count as no run.
- **Greek mu:** the unit comes back as `μg/m³` (U+03BC), not the micro sign; under `python -I`
  the Windows console can't print it (`-I` ignores `PYTHONIOENCODING`).
- **Test fixtures in a public repo:** CAMS responses keep their real structure and stamps with
  synthetic `pm2_5` values until #78 settles public display.
- **mypy reads `pd.isna(float)` as never true** (pandas stubs): `math.isnan` instead.

- **Merged:** #127 (`2555b80`, squash) after its CI passed (owner: "you choose what's best and
  do it" for part 2). #19 stays open for #78.

## 2026-11-24: #78 the daily CAMS save, on branch `78-cams-daily-save` (CST, about 07:15 to 07:50)

- **D-053:** each scheduled run saves CAMS global's PM2.5 for the target day at every monitor
  to `records/forecast_date=<day>/cams.json` (private, create-only, every version kept), after
  the forecast, scoring and `history.json`. Source: the live Air Quality API, read between two
  reads of the run in `cams_global`'s metadata. A run newer than the as-issued one is refused;
  an older one is saved with its own start. The file holds each monitor's 24 hours and mean, the
  run's start and publication, the issue time and `published_before_issue`.
  - **Premise checked first:** the live API's values for 2026-11-25/26 equal the 00 UTC run of
    11-24 from the Single Runs API in 48 of 48 hours; the metadata named that run before and
    after (published 09:48 UTC, 2.2 h before the issue time).
  - **Terms (for public display later):** Open-Meteo CC BY 4.0; the Copernicus licence v1.2
    allows communication to the public of modified values with "Contains modified Copernicus
    Atmosphere Monitoring Service information <year>" and the EC/ECMWF disclaimer.
  - No Terraform change: the run role already reads and writes `records/`. The scheduled run
    clones `main`, so the merge deploys it.
- **Built, tests first:** the save (13 tests, including a property that a second run never
  changes a saved file), the live fetch (7), the job at each step in turn (6: a CAMS failure
  keeps the forecast, its publish, `history.json` and the minutes, and fails the run; a scoring
  failure still saves; a failed forecast saves nothing; a retry fetches nothing). Twelve planted
  mistakes each caught. Core suite: 862 passed, 23.3 s. The opt-in live check and a real dry run
  (all 10 monitors, 24 of 24 hours each) pass.

### Traps found

- **A shell heredoc with nested triple quotes** broke in Git Bash; edit scripts go through the
  Write tool (the global rule).

- **Merged:** #128 (`561ee4f`, squash) after its CI passed. #78 and #19 stay open until the
  first real `cams.json` is seen.

## 2026-11-24: T12b (#20), validation's other classes, branch `20-validation-part2` (CST, 09:55 to 10:50)

- **D-054 (owner's choices):** faults stop the run, problems limited to some rows warn, an
  instrument change is counted; AirNow hours are judged against each site's own instrument
  (`AIRNOW_METHOD`, a fixed list the AQS report checks against AQS). New rules: wrong entity
  (`site_not_listed`, `site_outside_city`), key reuse (`site_moved`, `airnow_method_stale`,
  `method_changed`), dates (`future_hour`, `outside_active_period`), units (`unit_mismatch`);
  for the weather files `hours_outside_part`, `run_after_valid`, `available_before_run`
  (hard) and `outside_physical_range` (counted, kept). `run_checks` now takes the run time.
  - **Reference data** (`validation/reference.py`): AQS's `monitors/bySite` and AirNow's site
    list, fetched by the report only; the daily run doesn't call AQS.
  - **Premises checked on real data first** (counts, dates, codes; no measurement): every AQS
    hour inside its monitor's open period; all 10 sites in CBSA 38060 with one AQS position,
    equal to ours, AirNow's within 0.57 km; seven clean method changes; two weeks of AirNow with
    no hour outside its own site's range; 81 GFS-archive cloud-cover values at exactly −1 or
    101 %.
- **Built, tests first:** 21 rule tests, 26 reference tests (parsers and fetch on a mock
  transport), 14 weather tests. The three validation properties now draw a reference and a run
  time, so unlisted sites, future hours and inactive monitors join T12a's faults (every
  excluded row counted once, row order and other sites never matter; up to 62 ms per example).
  Folding them in instead of adding two more kept the suite at 53.4 s with coverage (budget
  75 s; the two extra had made it 60 to 67 s). 23 planted mistakes, each caught by the unit
  tests; the properties alone catch the three counting ones. Units already had a
  planted-bad-unit test at every source (AQS, AirNow, Open-Meteo, CAMS). Core suite: 923
  passed.
- **The full AQS history report** (2026-11-24 16:38 UTC, 180 parts, 1,217,348 rows, reference
  from AQS and AirNow): **passed**, nothing excluded.
  - T12a's rules unchanged from 2026-11-20: 54 coverage gaps (site-months under 75%, 3 to 8 per
    site), 0 duplicates, unverified methods, out-of-range hours or flat lines, 18,601 negative
    hours inside the range (kept).
  - T12b's: 0 unlisted sites, sites outside the CBSA, moved sites, stale AirNow instruments,
    future hours or hours outside an active period; 7 method changes (West Phoenix 2011, 2013,
    2014; North Phoenix 2014; Glendale 2015; Durango 2013; JLG Supersite 2024 to the T640X).
  - AirNow for 2026-11-23 passed (238 rows kept); the weather coverage passed (240 of 240
    files, no date fault; the 81 cloud-cover values counted).

- **Merged:** #129 (`4baaaaa`, squash; owner: "go ahead") after its CI passed on a rerun (the
  first run failed building the Vale hook: a stream error from the Go module proxy, not our
  code). #20's boxes ticked and the issue closed. #112's mutation list now also names
  `validation/reference.py`, `weather/cams.py` and `weather/cams_save.py` (owner's OK).

### Traps found

- **A scratch script's name was already taken** by an earlier session's file: Write refused it
  (not read first) and the command chained after it ran the old script, which stopped at its
  first assertion before writing. Scratch scripts now get a task prefix (`t12b_…`).

### Next

- **2026-11-25 after 12:00 UTC (06:00 CST):** check the first real `cams.json` in S3 (#78's last
  box), then close #78 and #19.
- **2026-11-25:** #3's old key and IAM user deleted (owner confirms first); milestone B closes.
- T15 (#21): what to do with the −1 and 101 % cloud-cover values (D-054 leaves it to the
  features).
- Fill-in: #124, #122, #113, #86, #87.

## 2026-11-24: fill-ins #87, #86, #122 done, #124 measured (CST, about 11:15 to 12:15)

- **#87 (#131):** the leakage property's "invalid" draws are Hypothesis's bookkeeping: status
  `gave_up`, "exceeded maximum test case size", never running the body (1,431 at 0.00 s against
  226 s for 2,000 passing; Hypothesis's observability output). A bare list of 1 to 4 bounded
  floats does the same in an empty test. Events now label the cases; under `explore` about 3%
  draw a value outside the site's range, none in the default 100.
- **#86 (#132, D-055):** `daily_job` re-raises a foreign error as `JobFailedError` (the day and
  the type, `from None`); our own errors pass unchanged; interrupts are never caught. Found
  along the way: scoring's `log.exception` put the foreign message and traceback in Prefect's
  log; now it logs the type, and `ScoringError` is a `ReportableError`. 7 planted mistakes caught.
- **#122 (#133, D-056, owner's choice):** the weekly job runs
  `uv lock --upgrade --exclude-newer "7 days"`; `pyproject.toml` has no cutoff; new minimums must
  be a week old. Tried on a copy: a cutoff in `pyproject.toml` fails every local lock while a
  minimum is under a week old (ours are set to the newest release when added), and `--upgrade`
  under a cutoff downgrades a newer locked version, so an urgent release needs a one-week
  exemption (DEVELOPMENT.md). Every current minimum is old enough by 2026-11-30 (PyPI times).
- **#124 measured, kept open:** before T14 (`72b8396`) vs `main`, summed test time 58.9 → 79.0 s
  (about +5 s wall), all new tests (validation properties +6.1 s, daily job +3.7 s, weather +3.0
  s, leakage +1.6 s); no old test slower. `main` 26.8 to 27.0 s on a quiet PC, 28.4 to 34.0 s
  later the same day; #132 and #133 add about 1.3 s. Next lever: the validation properties
  (`run_checks` is about 40% of each example, building the frames the rest).

### Traps found

- **A command on its own line runs even when the one before failed:** a fix to a records script
  failed its assertion, and the next line still ran the unfixed script (caught in the diff,
  reverted). Chain dependent steps with `&&`.
- The stacked branch conflicted on `DECISIONS.md` after #132's squash merge, as CLAUDE.md
  warns; the branch's copy was kept, checked to differ from `main` only by D-056.

### Next

- **2026-11-25 after 12:00 UTC (06:00 CST):** check the first real `cams.json` in S3 (#78's last
  box), then close #78 and #19.
- **2026-11-25:** #3's old key and IAM user deleted (owner confirms first); milestone B closes.
- **2026-11-30 (Mon):** the first lock run with the 7-day wait (#122); check it resolves.
- T15 (#21) next, with the −1 and 101 % cloud-cover values to settle.
- Fill-in left: #113 (watchdog starts the lock run: token, Terraform apply, drill), #124
  (validation properties first), #112 (mutation list).

## 2026-11-24: fill-ins #124 and #113 merged, #112 timed (CST, about 13:15 to 14:35)

- **#124 (#135, D-057, owner's choice):** the 30 s goal is the median of three quiet runs. Tests
  using the `daily` fixture join one xdist group with `--dist loadgroup` (about 1.2 s faster over
  six paired runs; a test checks both). No test or example removed. Closed.
- **#113 (#136, D-058):** the watchdog starts `uv-lock-upgrade.yml` on Mondays at 08:00 Chicago
  (create-once marker, GitHub dispatch, run ID recorded) and reads the run back at 09:00; the
  forecast and lock checks never skip each other; the workflow lost its cron and a test bans one
  in any workflow (D-003; the issue's "D-001" was a slip). GitHub's REST docs re-read: the
  dispatch answers 200 with `workflow_run_id`; Actions write to dispatch, read to read a run.
  - **mutmut on `handler.py`** (WSL, about 5 min): every survivor in the new or changed code
    killed, except 8 explained: `"UTF-8"` for `"utf-8"` (3, the same codec); a missing run `path`
    defaulting to `None` or `"XXXX"` instead of `""` (3, the run is refused either way); message
    text only (2: "reply named no run ID", "drill must be true or false"). 52 survivors in older
    code are left to #112. Killed with new tests: drill labels on lock and error emails, the
    stored marker and run, the JSON content type, the 09:00 result's run ID, the "unknown" state,
    GitHub not answering at 09:00, the unknown-mode message, and the drill guard on the real
    clock (`datetime.now(None)` would have compared a naive time and crashed a Lambda drill).
  - mutmut's own copy of a module imports `mutmut`; the handler's stdlib-only import check now
    allows that only for files under `mutants/`.
  - **Open for the owner:** the token, SSM, the zip, plan and apply, and the drill (T9 guide
    section 9). Until the apply nothing starts the lock run.
- **#112 timed:** `validation/checks.py` alone, 1,111 mutants in 14.3 min (1,007 killed, 103
  survived, 1 timeout); `watchdog/handler.py` about 5 min. The whole list (12 modules, about
  2,400 lines) is about an hour per run, and the survivors need a session or two.

### Traps found

- **A mutmut results script must set `only_mutate` first:** with the config reset it listed no
  mutants and printed nothing.
- **A commit isn't gated on the tests:** a commit went in with one failing test, and mutmut's clean
  run then failed in 33 s. Dependent steps now chain on the test result.

### Next

- **2026-11-25 after 12:00 UTC:** the first real `cams.json` (#78), then close #78 and #19.
- **2026-11-25:** #3's old key and IAM user (owner confirms); milestone B closes.
- **Owner:** #113's token, apply and drill (T9 guide section 9), before Monday 2026-11-30.
- **2026-11-30 (Mon):** the first watchdog-started lock run, with the 7-day wait (D-056).
- #112's full run and survivors; then T15 (#21).

## 2026-11-24: #113 applied and drilled (CST, about 14:35 to 15:05)

- **Owner:** fine-grained token `pm25-forecast-watchdog-lock` (this repo, Actions read and write,
  expires 2027-02-28) in SSM `/pm25-forecast/github-lock-token`; zip rebuilt (sha256 `efaa4df3…`,
  the merged code); `apply`: 0 added, 3 changed, 0 destroyed (the guide said 2: it missed the
  role's description; corrected).
- **Drill for Monday 2026-11-30:** 08:00 → `"lock": "dispatched"`, run 45484178486 (GitHub lists
  it, `workflow_dispatch`); the same call twice more → `"already dispatched"`, no new run; 09:00 →
  `"lock": "failure"` with the DRILL email and the run's link; a Monday with no run (12-07) →
  `"lock": "missing"`. Five `watchdog {...}` log lines, no token or key in the logs.
- **The run failed as D-056 intends:** today's 7-day cutoff (11-17) excludes `zensical==0.1.3`
  (11-20). By Monday 11-30 every minimum is older than the cutoff, so the first real run should
  open the lock PR with CI, which closes #113's drill box and #43's last box.
- The lock email now reads "hadn't succeeded by 09:00 Chicago (state: …)" (was "is failure").

### Next

- **2026-11-30 (Mon) after 09:00 Chicago:** the first watchdog-started lock run: check it
  succeeded and its PR's CI ran; then close #113 and #43.
- **2026-11-25:** the first real `cams.json` (#78, #19); #3's old key and user (owner confirms).
- #112's full run and survivors; then T15 (#21).

## 2026-11-24: the email wording deployed; a stale Terraform lock (CST, about 15:05 to 15:15)

- **Deployed #138's wording:** the zip rebuilt from `main` (`ab41361`, sha256 `618df6d5…`, the same
  as from the branch); `plan`: 1 change, the Lambda's code; `apply`: 0 added, 1 changed. The live
  Lambda's `CodeSha256` equals the zip's.
- **Records:** DEVELOPMENT.md gains the mutmut timings; the T9 guide, the stale-lock fix; todo.md,
  the #113 and #112 rows.

### Traps found

- **A stopped `apply` leaves Terraform's S3 state lock** ("Error acquiring the state lock", 412,
  an apply from this PC at 20:56 UTC). Checked first: no `terraform` process, and the Lambda
  still on the old code, so nothing had landed. `force-unlock -force <ID>` released it and the
  saved plan applied (T9 guide).
- **Pasting a reply into `!` runs its prose as commands:** harmless "command not found" lines,
  but a pasted `! rm` would run. Copy only the code block.

### Next

- **2026-11-25 after 12:00 UTC (06:00 CST):** the first real `cams.json` (#78), then close #78
  and #19; #3's old key and user (owner confirms); milestone B closes.
- **2026-11-30 (Mon) after 09:00 Chicago:** the first watchdog-started lock run succeeded and its
  PR's CI ran; then close #113 and #43.
- #112's full run and survivors; then T15 (#21).

## 2026-11-24: #112 mutation testing, branch `112-mutation-tests` (CST, 15:05 to 17:35, owner away)

- **The mutation list:** `only_mutate` now holds #112's twelve modules beside the first three
  (15 in all). **Found first:** mutmut's test selection left out `tests/integration`, so every
  mutant only those tests catch was a false survivor (88 in `run_daily`, all of `_encode` and
  `_publish_all` "no tests"). Added, with a test that every offline test folder is selected.
- **Runs (WSL, 12 CPUs):** without integration 623 survived (26.5 min); with it 509 (35.7 min);
  after the first new tests 348 (23.9 min); after all of them **260** (22.5 min), 141 "no tests"
  (the CLI `main`, `lambda_handler`, `_urllib_get`: real edges, `pragma: no cover`), 2 timeouts.
- **Killed with new tests** (each also proved by hand-planted mutants; every one caught except
  the equivalents below):
  - forecast: dates from the issue zone under a moved process zone (Kiritimati, a day ahead at
    the issue time); the next day's first hour never in a site's hour count; byte-stable files;
    `published` a real bool on every path; the saved report's source and Phoenix-day window;
  - storage: an AWS error without metadata;
  - CAMS save: Phoenix's day mean (values rising by the hour, so windows differ); a run published
    exactly at the issue time; NaN refused; every outcome's day and save; a lost race with
    nothing readable;
  - minutes ledger: a retry keeps the first minutes; exactly 300 is not over the line; a zone
    whose offset is `None`; the file format;
  - publish: a same-day update replaces `latest.json`, an older day never does; where a schema
    failed;
  - scoring: the stored score on reuse; no-record outcomes' day; a lost race; zero hours by
    default; the file format;
  - validation: every rule's class and severity pinned, clean and firing; 12 identical hours;
    readings of exactly 0; a one-hour window; a monitor closing today; exactly 1.0 km; two-place
    rounding; comparisons within one source, site and instrument; a reopened monitor; every
    site judged; months and "today" in the city zone; missing drop counts;
  - reference: the distance's longitude term against the spherical law of cosines; blank codes
    as `None`; the site ID's state and county; retries; no header or data; a no-data site that
    never stops the loop; schema: a fresh index after stacking;
  - CAMS client: query builders called inside tests (module-level ones map to no test); the
    history start and one-day boundaries; a live query on UTC; a run's whole days; a grid point
    exactly 0.4° away; a live run ignored by a history parse; the early-value count; retries; a
    run published exactly at the fetch; daily means sorted by site;
  - watchdog: every setting read, the API URL trimmed; the target day under a moved process
    zone; AWS errors without an Error block; a nameless Prefect reply; DRILL on a failed drill
    retry; the monthly alert's marker and plain subject.
- **Explained (the 260 left):** 133 change only message or log text (an `XX` wrap, a case change,
  `None` for a message); 36 pass `strict=`, `index=`, `utc=` (on aware times), `kind=`,
  `dtype=`, `sort=` or `ignore_index=` where the result is the same; 15 change a retry count,
  backoff or timeout default, which no test times; `"UTF-8"` for `"utf-8"`; equivalents by
  construction: `keep=`, `reset_index(name=None)` then read by position, `astype(None)`,
  `MaxKeys`, `method=None` with data (urllib posts), a subject slice the subject never reaches,
  `emailed=None` (falsy), method-change items from `i-1` (always the same site and instrument),
  `columns=None` (the dict is in `COLUMNS` order), `hours_ok`'s `>` and `count - 2` (equality
  needs `count - 1 = 120 + offset` with `count % 24 == 0`: unreachable), the zone and drop counts
  passed to validation in scoring and the forecast (they feed only coverage warnings and info
  counts); `cams_save`'s `if len(mean) else nan` is dead code (`daily_means` always returns a
  row).
- **Follow-up, not ruled on (about 8):** two `checks` month-label and coverage mutants with
  `astimezone(None)` survive the Kiritimati tests (why isn't yet known);
  `S3Store.create_if_absent`'s retry count and pause (3) aren't pinned; the second
  `live_run is not None or` in `cams.parse`; `dropna(subset=None)` in `cams.daily_means`.
- Core suite after: 1,048 passed and 16 skipped (the zone tests, POSIX only), 26.7 s.
- **Records:** D-059 records the new scope and test selection (refines D-048); SPEC's
  mutation line and the todo row follow it.

### Traps found

- **A test selection that skips a folder makes false survivors:** check that
  `pytest_add_cli_args_test_selection` covers every test folder before trusting a survivor
  (now a test).
- **Module-level test data maps to no test:** mutmut attributes calls during collection to none,
  so a builder used only there shows as a survivor although its output is asserted.
- **`git checkout -- <file>` to undo a planted edit also undoes uncommitted work on that file:**
  the mutation-list edit had to be redone; commit before planting by sed.

### Next

- **2026-11-25 after 12:00 UTC:** the first real `cams.json` (#78), then close #78 and #19; #3's
  old key and user (owner confirms); milestone B closes.
- **2026-11-30 (Mon) after 09:00 Chicago:** the first watchdog-started lock run; close #113, #43.
- #112: its PR (Refs #112) through CI and the owner's merge; the follow-ups above are #140.
- T15 (#21).

## 2026-11-24: #140, #112's last survivors, branch `140-mutmut-survivors` (CST, 20:20 to 21:20)

- **#141 merged** (Refs #112, 2026-11-25 02:21 UTC). Its body said "which closes #112", a GitHub
  closing keyword, so the merge closed #112; reopened with a comment, the body reworded.
- **Runs (WSL, 12 CPUs, only `checks`, `storage` and `cams`, a clone-only list):** `main`
  132 survived, 1 timeout (950 s); the branch 130 (883 s).
- **Killed with new tests** (each also proved by a planted mistake: the new test fails, `main`'s
  passes):
  - `checks`: the month label's `astimezone(None)`. The old test ran in Kiritimati, east of
    Phoenix, where a Phoenix month's first hour is still the same date, so it passed with its
    rule removed; it now runs in Pago Pago (UTC-11). The first month's `astimezone(None)`: a
    window from 23:00 Phoenix on 29 February, in Kiritimati, must judge February's hour;
  - `storage.create_if_absent`: three tries, then the error naming them; pauses of 1 s then 2 s
    by default;
  - `cams.parse`: a live run handed to a history or single-run parse changes nothing, both run
    columns compared. The survivor was the first `live_run is not None and` (line 233); the
    2026-11-24 entry named the second, which the old tests already caught.
- **Explained (equivalent):** `daily_means`'s `dropna(subset=None)` (its callers pass `parse`'s
  rows, where only `pm2_5` can be missing); `groupby` without `sort=True` (the default); `//` as
  `/` (24.0 equals 24); `range(…+2)` in `create_if_absent` (the third try raises first);
  `first > end`, `start > window.end`, `expected < 0` and `break` in the coverage code (each
  only adds a zero-hour segment, which is skipped, or stops after the last one).
- **#112's "Done when" is met:** every survivor in its modules is killed or explained.

### Traps found

- **A closing keyword anywhere in a "Refs" PR's body closes the issue:** "which closes #112"
  did. Check the body for close, fix or resolve before a number, and the issue after a merge.
- **mutmut's kill counts flake:** four mutants that can't change a result (two message texts,
  `default=1.0` at the exactly-1.0-km boundary, `poc[i - 1]`) were killed on `main` and survived
  on the branch, and `kind="XXstableXX"` (ignored by pandas for a multi-column sort) the other
  way round, with no change to their code or tests. A test fails at random inside mutmut's copy;
  survivors aren't hidden, but kills can be counted that didn't happen. Not yet an issue.
- **An east-only zone test can't catch a month-start bug:** a local midnight seen from further
  east is still the same date. Test a zone on each side of the city.

### Next

- **2026-11-25 after 12:00 UTC:** the first real `cams.json` (#78), then close #78 and #19; #3's
  old key and user (owner confirms); milestone B closes.
- **2026-11-30 (Mon) after 09:00 Chicago:** the first watchdog-started lock run; close #113, #43.
- #140's PR (closes #140 and #112); an issue for the mutmut kill flake (owner's call).
- T15 (#21).

## 2026-11-24: #143, the mutmut verdict flake, branch `143-mutmut-flake` (CST, 21:45 to 23:20)

- **#142 merged** (2026-11-25 03:39 UTC); it closed #140 and #112. #143 filed for the flake.
- **Found:** a Hypothesis deadline, not a random test. With an equivalent mutant active, the
  tests mutmut maps to it passed 60 of 60 times run one at a time, but 6 of 12 copies run at once
  (mutmut's parallelism) failed `test_row_order_never_changes_the_result`: an example took 252
  to 304 ms against the default 200 ms, faster on the rerun, so Hypothesis raised "Unreliable
  test timings". mutmut counts any failure as a kill, so a mutant no test catches could be
  reported as caught, not only harmless ones.
- **Fixed (owner's choice, D-060):** `deadline=None` on the three validation properties, with a
  test that fails if one loses it (red first). The other 18 property tests keep the default:
  their examples take under 1 ms.
- **Proof:** two mutmut runs of `checks.py` on `3a3dc3e`: 60 not killed each (59 survived, 1
  timeout), the same list; the five mutants that flipped in #140 survive in both. No survivor
  appeared that the earlier runs didn't list, so the false kills hid no real gap there.

### Traps found

- **A direct pytest in mutmut's `mutants/` folder imports the unmutated package:** the venv's
  editable install wins. Set `PYTHONPATH=<clone>/mutants/src`, and prove the switch works with
  a control mutant that must fail, before trusting a pass.
- **`bash -c "…"` through `wsl.exe` expands variables on the Windows side** (`$PWD` became the
  Windows checkout), as DEVELOPMENT.md warns: put such commands in a script.
- **A flake that needs load won't show one test at a time:** reproduce at the parallelism the
  tool really uses.

### Next

- **2026-11-25 after 12:00 UTC:** the first real `cams.json` (#78), then close #78 and #19; #3's
  old key and user (owner confirms); milestone B closes.
- **2026-11-30 (Mon) after 09:00 Chicago:** the first watchdog-started lock run; close #113, #43.
- #143's PR (the owner decides when to open it).
- T15 (#21).

## 2026-11-25: #143 merged, #78 and #19 closed, branch `session-records-1125` (CST, from 06:10)

- **#144 merged** (2026-11-25 12:13 UTC, all four CI checks green); it closed #143.
- **The first real `cams.json` checked** (#78's last box): `records/forecast_date=2026-11-26/`
  in the private bucket. Written 12:01:47 UTC, 11 s after `forecast.json`; `fetched_at_utc`
  carries its zone; the 00 UTC run was published 10:08:50 UTC, before the 12:00 UTC issue
  (`published_before_issue` true); 10 monitors, each a daily mean of 24 of 24 hours, the same
  site set as `forecast.json`.
- **#78 and #19 closed** (owner's OK), their boxes ticked. #19's "responses cached" means the
  history in S3 with reruns fetching only missing parts; the CAMS bias is in D-052, and #79
  carries it into the write-up.
- **#3 closed:** a read-only check first (the key …XZ53 still last used 2025-08-04, the user's
  only credential; its policy attached to nothing else). The owner then deleted the key, the
  user `air-quality-mlops-user` and `MLOpsProjectS3AndBasicAccessPolicy` in the console, from
  the agent's step-by-step guide. Read back: both NoSuchEntity, no IAM users left.
  `notes/TOKENS.md` updated. The #3 body's garbled `…` and `·` repaired in the same edit.
- **The v1 and 2023 SageMaker buckets deleted early** (owner's request, D-061; #36's bucket box
  ticked, #36 stays open): the contents listed first, no copy kept (owner's choice, against the
  recommended local copy). Read back: only the three `pm25-forecast-*` buckets remain, with
  their objects.
- **Milestones A and B closed** (owner's OK); both had 0 open issues.
- **The 2023 SageMaker Studio domain removed** (owner's choice; outside the project): the owner
  deleted the domain, its EFS file system (6 mount targets), its two NFS security groups and its
  execution role and policy, from the agent's guide. Read back: no domains, no EFS file systems,
  no such security groups, role and policy NoSuchEntity; `pm25-forecast-prefect-run` and the
  three project buckets untouched. About 15 other 2023 SageMaker roles and 5 policies remain
  (outside the project; a cleanup only if the owner asks).

### Traps found

- **The SSO session had expired overnight** (8 hours): the check waited on the owner's
  `aws sso login`.
- **`aws s3 cp` has no `-q`;** it's `--only-show-errors`.
- **#3 is in milestone A, not B:** the earlier "Next" lines said closing it closes milestone B.
  B had 0 open issues already; #3 was A's last.
- **AWS CLI text output on Windows ends in `\r`:** a domain ID read into a shell variable failed
  validation until piped through `tr -d '\r'`.
- **`list-objects-v2 --query KeyCount` printed `None`** under the CLI's paging; `aws s3 ls
  --recursive --summarize` gives the real count.

### Next

- `session-records-1125`'s PR (the owner decides when to open it).
- **2026-11-30 (Mon) after 09:00 Chicago:** the first watchdog-started lock run; close #113, #43.
- T15 (#21).
