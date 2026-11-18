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

### Next

- **T2 (#6) CI** on branch `6-ci`: a GitHub Actions workflow running `uv sync --frozen`, Ruff,
  mypy, pytest (+ coverage report) and gitleaks on every PR. Actions pinned to SHAs (looked up).
  Dependabot for actions (and `uv` if GitHub supports it). Then add the required checks to the
  `protect-main` ruleset.
- After CI is green on uv 0.13.9: delete `~/.local/bin/uv-0.7.20-backup/` (owner's OK).
- **2026-11-20:** milestone A due. **2026-11-25:** skeleton checkpoint, D-014 review, delete the
  old AWS key and IAM user.
