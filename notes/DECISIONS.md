# Decisions log

Settled decisions with their reasons. One home per decision. Change a decision only with a new entry
that replaces the old one; never edit history. Session narrative goes in [JOURNAL.md](JOURNAL.md).

Format: **ID · date · decision**, then *Why*, *Alternatives*, and *Status*.

---

## D-001 · 2026-11-18 · Trial `addyosmani/agent-skills` at project level, not globally

- **Why:** Evaluate the 25 skills on this one project before letting them affect every project. If
  the trial goes well, install them globally then.
- **Alternatives:** Global install. This was done first and then undone at the user's request.
- **Status:** Active. They were installed into `MLOps Final Project/.claude/skills`, with
  `skills-lock.json` pinning commit `39b723c`. Where they should live is open question Q-1.

---

## D-002 · 2026-11-18 · Rebuild in a new public repo; make the 2025 repo private

- **Why:** The 2025 code has fundamental flaws (a random split on time-series data, model selection
  on the test set, a "forecast" that only backfills). Readers judge on first impressions, and anyone
  browsing the old code would see those flaws before any explanation. Making it private (rather than
  deleting it) also hides the old personal-email commits, keeps the history for the owner, and can
  be reversed.
- **How v1 is shown:** Only as prose. The new repo's docs describe what v1 got wrong and how v2
  avoids it, with no link to the old code.
- **Alternatives:**
  - Same repo with a `v2025` tag and a comparison page. This was my first recommendation, rejected
    because of the first-impression risk.
  - Delete the old repo. Rejected because it cannot be undone.
- **Status:** Agreed. Not done yet: creating the new repo and switching the old one to private
  both change public state, so each waits for an explicit go-ahead.
- **Carry over:** These notes (`notes/JOURNAL.md`, `notes/DECISIONS.md`) move to the new repo.

---

## D-003 · 2026-11-18 · The project's intent is confirmed (see INTENT.md)

- **Decision:** It is a live portfolio project for interviewers and also a learning project. It
  produces next-day PM2.5 forecasts for one city chosen on data merit, shown on a public page. The
  budget is under about $5 a month, with no always-on servers and a scheduler more reliable than
  GitHub cron. Prefect, MLflow, Evidently and AWS stay because learning them is a goal. Models go
  from a baseline to classical models to simple deep learning (under 6 hours of training each). The
  work is a fresh rebuild. Full text: [INTENT.md](INTENT.md).
- **Why:** Settled in an interview-me session. Two points the owner overrode:
  - **Keep Prefect and Evidently** even where simpler options would do, because learning them is a
    goal.
  - **GitHub cron is not the production scheduler**: in a previous project it fired late or not at
    all, and a Cloudflare Worker was needed as the trigger.
- **Settles:** Q-2 (purpose), Q-3 (a real next-day forecast, not a backfill), Q-5 (a fresh rebuild).
  Q-4 is partly settled: AWS stays and GitHub Actions is for CI only. *Which* reliable scheduler to
  use (for example Prefect Cloud or AWS EventBridge Scheduler) goes to the spec, after checking
  current free-tier limits.
- **Status:** Active.

---

## D-004 · 2026-11-18 · Train on EPA AQS history; forecast live from AirNow; measure the gap

- **Decision:**
  - Train on validated EPA AQS daily PM2.5 (back to 2009).
  - Forecast live from AirNow observations, which are hourly and preliminary.
  - Measure the AirNow-vs-AQS difference on the period where both exist, and report it.
  - Score the public track record against AirNow the next day. Re-score each forecast against AQS
    once validated data arrives, and show both scores.
- **Why:** AQS cannot drive a live forecast. Submissions are due by the end of the following
  quarter, and EPA says the AQS API does not host real-time data and points to AirNow. AQS gives
  the deepest, cleanest history. Treating the preliminary-vs-validated difference openly is a real
  production-ML issue worth showing.
- **Sources (checked 2026-11-18):** RAQSAPI "Timeliness of AQS data" vignette; aqs.epa.gov "About
  AQS data"; docs.airnowapi.org web services and FAQ.
- **Alternatives:**
  - AirNow only: consistent data, but the history depth is unconfirmed.
  - OpenAQ: an extra intermediary, and its rate-limit docs contradict each other.
- **Facts confirmed 2026-11-18** (read by the owner from the logged-in AirNow docs; the Data Use
  Guidelines PDF read directly):
  - **Rate limit:** up to **500 requests per hour** for both the hourly (`/Data`) and the daily
    (`/DailyData`) bounding-box web services. After that, an error until the next hour.
  - **API history window:** not stated. The docs note that raw ozone is returned "for all dates in
    2019 and years prior", which suggests multi-year history. To confirm with one live call in T5.
    The third-party "about 45 days" claim is likely wrong.
  - **Hourly file product:** `HourlyAQObs_yyyymmddhh.dat` at `https://files.airnowtech.org`
    (directory `/?prefix=airnow/YYYY/YYYYMMDD/`), updated hourly, **available from 2019-05-28**.
    The fields include **`AQSID`** (the AQS site ID, which gives a direct AirNow↔AQS mapping for
    T5), `Latitude`, `Longitude`, `GMTOffset`, `ValidDate`, `ValidTime`, `PM25` and `PM25_Unit`.
    The units vary, so they must be checked per row.
  - **Overlap for measuring the gap:** AirNow files from 2019-05-28 against AQS, which gives about
    6.5 years.
- **Status:** Active. Display obligations from the Data Use Guidelines → D-025.

---

## D-005 · 2026-11-18 · Target: next-day 24-hour mean PM2.5 per monitor, one pooled model

- **Decision:**
  - Target: tomorrow's 24-hour mean PM2.5 (µg/m³, local calendar day) at each monitor in the
    chosen metro area.
  - One model, pooled across monitors.
  - The public page shows a city summary (the median across monitors), its AQI category, and a
    per-monitor map.
- **Why:** A city-wide average changes meaning whenever a monitor is added or retired, while a
  per-monitor target stays well defined. Pooling gives more training rows. A continuous target keeps
  information that AQI categories throw away, and the categories can still be derived for display.
- **Alternatives:**
  - City-wide mean: rejected because it drifts with the monitor set.
  - AQI-category classification: rejected because it loses information and the classes are badly
    imbalanced.
- **Status:** Active. Still to settle in the spec: the local-day boundary and time zone, the minimum
  hourly completeness for a valid daily mean, and how to treat co-located instruments (POCs).

---

## D-006 · 2026-11-18 · Choose the city with a data check declared in advance

- **Decision:** The spec fixes the criteria and thresholds before any data is looked at. A small
  first task then scores 3–4 candidate metro areas (Chicago plus, for example, Salt Lake City,
  Los Angeles and Phoenix) on **data coverage only, never on model results**. Chicago wins ties.
- **Draft criteria** (made final in the spec, then frozen):
  - at least 5 PM2.5 monitors active in both AQS and AirNow;
  - at least 8 years of AQS history;
  - at least 75% daily completeness;
  - a real share of high-PM days (wildfire smoke or inversions);
  - Open-Meteo and CAMS coverage.
- **Why:** Fixing the criteria first stops the choice drifting toward whatever looks impressive.
  This is the same discipline as fixing the evaluation split before seeing results.
- **Alternatives:**
  - Keep Chicago without checking: coverage problems could surface after code depends on it.
  - Pick another city on reasoning alone.
- **Status:** Active. Settles Q-6 once the check has run.

---

## D-007 · 2026-11-18 · Weather: observed for training, forecasts as issued for test and live

- **Decision:**
  - **Training** uses observed weather (Open-Meteo Historical Weather API, ERA5 reanalysis) across
    the full AQS history.
  - The **test period** and **live forecasts** use weather *forecasts as they were issued*
    (Open-Meteo Previous Runs API for test, the Forecast API for live). The test score therefore
    reflects what is available in production.
  - A comparison variant is declared now: **trained only on archived forecasts** (from 2024-01,
    when most variables start), so the cost of the training/serving skew is measured, not assumed.
- **Why:** In production only tomorrow's forecast exists. Training on observed weather and also
  testing on it would leak future information and overstate skill. The Previous Runs API keeps
  forecasts at fixed lead times (`_previous_day1` is the forecast made 24 hours before the valid
  time), which lets us rebuild "what we would have known".
- **Sources (checked 2026-11-18):** open-meteo.com docs (Previous Runs API, Historical Forecast
  API, Air Quality API) and terms (non-commercial: under 10,000 calls a day; CC BY 4.0 attribution;
  CAMS attribution for air-quality data).
- **Alternatives:**
  - Archived forecasts only: under 3 years of history, too thin for the deep-learning models.
  - No weather: likely weak, and cannot anticipate weather-driven changes.
- **Status:** Active. Still to settle in the spec: the exact variables, which forecast issue time
  the live run uses, and the lead-time mapping.

---

## D-008 · 2026-11-18 · Split: develop on 2009–2024, test on 2025 (read once), then live

- **Decision:**
  - **Development:** 2009-01-01 to 2024-12-31. All tuning and model choice happen here, using
    rolling-origin CV (expanding window, one validation fold per year 2019–2024, 1-day embargo
    between train and validation).
  - **Test:** 2025-01-01 to 2025-12-31. It is read **once**, at the research freeze, by one script
    in one place. No test numbers are printed or logged during development.
  - **Live:** the public track record from launch is a second, truly out-of-sample test.
- **Why:** The test is a full year, so every season counts, and 2025 lies inside the period with
  archived forecasts (D-007). The v1 failures this prevents: a random split on time series, and
  model choice based on test RMSE.
- **Note:** The forecasts-only variant (D-007) gets only 2024 for training before the 2025 test.
  It measures the skew; it is not a serious contender.
- **Alternatives:**
  - A 6-month test: rejected because it covers only part of the seasonal cycle.
  - Live only: rejected because there would be no score at launch.
- **Status:** Active. **Frozen:** never changed after results are seen.

---

## D-009 · 2026-11-18 · Headline metric is MAE; three baselines to beat

- **Decision:**
  - **Headline metric:** MAE (µg/m³) on the next-day per-monitor mean, pooled across monitors.
  - **Also reported, but never used to choose a model:** RMSE; a skill score against persistence
    (1 − MAE_model / MAE_persistence); recall on days rated "Unhealthy for Sensitive Groups" or
    worse.
  - **Baselines,** all scored on the same rows:
    1. **Persistence:** tomorrow's value equals today's.
    2. **Climatology:** each monitor's development-period mean for that day of year, smoothed.
    3. **CAMS:** the Open-Meteo/CAMS global PM2.5 forecast at the monitor's location. This is the
       outside physics-based bar, available from 2022-08, so it covers the 2025 test year.
- **Why:** PM2.5 is right-skewed, so RMSE is driven by a few smoke days. MAE reads as "µg/m³ off
  on a typical day". The extreme days still count through RMSE and the recall figure, which are
  reported but not used for selection.
- **Alternatives:**
  - RMSE with persistence only.
  - MAE with persistence only: rejected because it drops the CAMS comparison, which is the most
    convincing bar to beat.
- **Status:** Active. **Frozen.**
- **Clarification (2026-11-18, before any result was seen; no change to the decision):**
  **Persistence** means *the forecast for D+1 equals the last complete day's observed mean, which
  is D−1*. At the 06:00 issue time (D-019), day D is not yet observed, so using D would leak. In
  effect this is two-day persistence, and it is what any honest forecaster would have at 06:00.

---

## D-010 · 2026-11-18 · Six model variants, declared before any results

- **Variants**, all on the same features, rows and CV folds:
  1. **Ridge** (linear sanity check)
  2. **Random Forest**
  3. **XGBoost**
  4. **LightGBM**
  5. **LSTM**: small, over the last 14 days of PM and weather
  6. **TCN** (temporal CNN): small, same 14-day window
  - Plus the forecasts-only training variant from D-007, used to measure skew. It is not eligible
    for the headline.
- **Selection rule (frozen):** the headline model has the **lowest mean CV MAE over the 2019–2024
  folds**; on a tie (within one standard error), the simpler model wins (order: Ridge < RF <
  XGBoost/LightGBM < LSTM/TCN). The 2025 test is read once, after selection, and **never** changes
  the choice. No variant may be added after the first CV result is seen.
- **Budget:** each variant must train in **under 6 hours on the owner's PC CPU**, including its
  tuning search. Time one small run before any full search.
- **Why:** One model from each family. Two gradient-boosting libraries and two deep-learning
  architectures allow like-for-like comparisons, so "DL vs GBM" doesn't rest on one architecture.
  The owner added XGBoost and RF to my four-model proposal.
- **Alternatives:** Adding a Temporal Fusion Transformer: rejected because it is heavy to tune, may
  exceed 6 hours on CPU, and the owner would rather understand each model than add more.
- **Status:** Active. **Frozen.**

---

## D-011 · 2026-11-18 · Scheduling: Prefect Cloud runs the job; an AWS watchdog backs it up

- **Decision:**
  - **Primary:** a Prefect Cloud schedule runs the daily flow on a **Prefect Managed** work pool
    (free Hobby plan).
  - **Backup:** an **AWS EventBridge Scheduler** rule, about 2 hours later, starts a small
    **Lambda**. If today's forecast record is missing from S3, it triggers the Prefect deployment
    through the Prefect API. If that also fails or times out, it sends an email through **SNS**.
  - **At most once:** the forecast is written with an S3 conditional write (create only if absent),
    keyed by forecast date. A second trigger cannot publish twice.
  - **Done** is defined by that S3 record, never by a local file or by Prefect's own run state.
- **Why:**
  - It is the lightest setup, and the code runs in one place (the owner's "run it in one place"
    rule).
  - Prefect is used as a real orchestrator (a learning goal).
  - The backup is independent of Prefect's scheduler.
  - It costs about $0.
  - It can move later: the work pool is a deployment setting, so moving to AWS ECS is a config
    change, not a rewrite.
- **Facts (checked 2026-11-18, prefect.io/pricing and the Managed docs):**
  - Hobby: 5 deployments, 500 managed minutes a month, 7-day run history, 5 automations.
  - A managed run gets 4 vCPU and 16 GB, uses the official Prefect image plus pip packages, and
    needs its code in a remote location such as git.
  - Custom or push pools appear to be paid-only. That is my reading of the plan table.
  - EventBridge Scheduler: 14 million free invocations a month.
- **Risks:**
  - Prefect's free plan could change. Moving to ECS is the fallback.
  - The flow must stay well under 500 minutes a month.
  - 5 deployments is a hard cap, so plan which flows get one.
- **Alternatives:**
  - AWS runs the job and Prefect observes: rejected because it needs a second execution path for
    the backup and more setup.
  - Two full triggers where the first wins: rejected because the code would run in two places.
- **Status:** Active. Settles Q-4b. To verify during build: how S3 conditional writes behave, and
  how a Lambda calls the Prefect API (key stored in SSM Parameter Store as a SecureString).

---

## D-012 · 2026-11-18 · Public page on GitHub Pages; data as public JSON in S3

- **Decision:**
  - A static site (HTML plus a small pinned chart library) served free with HTTPS by
    **GitHub Pages**. CI deploys it only when the page code changes.
  - Each day the flow writes small **derived** JSON files (today's forecast, recent actuals,
    scores) to a **separate public-read S3 prefix**, which the page fetches (CORS limited to the
    Pages origin).
  - Raw or licensed data, models and anything private stay in private S3.
- **Why:** No daily bot commits, the page and its data are cleanly separated, and it costs about
  $0. It follows the "keep private and public outputs apart" rule. Secret-scan any public output
  before writing it.
- **Alternatives:**
  - S3 + CloudFront: more setup, and more ways to misconfigure a public bucket.
  - Streamlit Community Cloud: free apps sleep, so a slow wake-up for interviewers, and hosting
    terms change.
- **Status:** Active. Attribution must appear on the page: EPA AirNow and AQS, Open-Meteo
  (CC BY 4.0) and CAMS.

---

## D-013 · 2026-11-18 · Monitoring: daily scoring, weekly drift, retraining by hand

- **Decision:**
  - **Daily:** score yesterday's forecast against AirNow and update the public track record.
    Re-score against AQS when validated data arrives (D-004).
  - **Weekly:** an Evidently drift report comparing recent model **inputs** with the training
    data, linked from the page. Calendar features (year, day of year) are excluded from drift
    checks, because they always drift by construction (a v1 bug).
  - **Flags never fail the forecast flow.** A flag emails the owner and opens a GitHub issue.
  - **Retraining** is a manual, logged decision (a journal entry and a decision entry). Trigger
    rule: the rolling 30-day MAE is worse than persistence's for 14 days in a row, or a drift flag
    is confirmed on review.
- **Why:** In v1, drift raised an error that failed the flow and fired almost every time.
  Retraining the deep-learning models is expensive and runs on the owner's PC. Manual retraining
  keeps the free Prefect minutes and deployments for the daily path.
- **Alternatives:**
  - Automatic retraining: needs a safe promotion rule and uses up the free quota. Deferred to V2.
  - Daily scoring only: rejected because it skips Evidently, a learning goal.
- **Status:** Active.

---

## D-014 · 2026-11-18 · Timeline: skeleton by 2026-11-25, research freeze 2026-12-23 (flexible)

- **Decision:**
  - **By Wed 2026-11-25 (America/Chicago):** a crude end-to-end version is live. The persistence
    baseline forecasts daily, the page is up and the watchdog is on.
  - **Weeks 2–5:** validation, features, the 6 variants (D-010), monitoring (D-013).
  - **Research freeze: Wed 2026-12-23** (about 60 hours in total). After it, only fixes,
    delivery and the write-up. The 2025 test is read **once** at the freeze.
  - **Cut line:** if something is not done by **2026-12-16**, cut in this order: the TCN, then
    the per-monitor map, then AQS re-scoring. A cut variant is reported as "not evaluated", never
    silently dropped. Cuts are decided **by the calendar, never by results**.
- **Flexible (the owner's note):** these dates are a plan, not a cap. **Re-evaluate on
  2026-11-25**, when the walking skeleton should be live. Any change becomes a new D-entry made
  **before** any test result is seen.
- **Why:** The owner's rule of a walking skeleton first: in the last project, the delivery path
  was built last and its bugs surfaced three days before the deadline. The freeze stops numbers
  moving under the write-up.
- **Facts:** clock checked 2026-11-18 11:50 CST (17:50 UTC). The PC is on America/Chicago time.
  All dates here are America/Chicago.
- **Status:** Active. Next review: 2026-11-25.

---

## D-015 · 2026-11-18 · Scaffold: uv src layout plus the spec's folders (not CCDS)

- **Decision:** Create the repo with `uv init --package` (the standard Python src layout,
  `pyproject.toml`, `uv.lock`), then add only the folders the spec names (SPEC § Project
  Structure). No empty placeholder folders.
- **Why:** Cookiecutter Data Science (v1's template, v2.2.0 on PyPI) is built for analysis
  projects with `data/`, `notebooks/` and `models/` inside the repo. In v2, data and models live in
  S3 and the repo is a deployable service. v1 shows the mismatch: empty `data/*/.gitkeep` folders
  and 64 MB of `mlartifacts` in the working tree.
- **Alternatives:**
  - CCDS v2 again: familiar, but shaped for analysis, not a service.
  - A third-party service template: brings someone else's tooling choices, which would then need
    undoing.
- **Status:** Active.

---

## D-016 · 2026-11-18 · Docs: Zensical from day zero, pinned, with a separate link checker

- **Decision:**
  - Write the docs with **Zensical**, pinned to an exact version (looked up at setup).
  - Numbers in the prose come from `results/results.json` through Zensical's native `macros` or
    `markdownextradata` support.
  - **A link and anchor checker runs separately in CI**, so the "strict links" rule does not
    depend on the docs tool.
  - **Fallback**, if a beta release breaks the build: Material for MkDocs 9.7.x with `mkdocs<2`.
    Zensical reads `mkdocs.yml` natively, so switching is cheap.
- **Why (checked 2026-11-18):**
  - Material for MkDocs promised critical fixes only until 2026-11-05, and its team moved to
    Zensical.
  - MkDocs 2.0 is a pre-release, incompatible with Material, has no plugin system and offers no
    migration path.
  - Zensical 0.1.2 (2026-11-17) is in beta since 0.1.0 (2026-11-05), with stable planned about
    three months later.
  - It natively supports macros (since 0.0.40, with differences: a new environment per page, only
    `define_env`, no post-build hooks), markdownextradata and table-reader. Custom MkDocs plugins
    do not run.
- **Unconfirmed:** whether Zensical fails builds on broken links or anchors (its docs pages
  returned 404), hence the separate checker. Also its GitHub Pages deploy steps, to look up at
  setup.
- **Alternatives:**
  - MkDocs 1.x + Material 9.7: frozen, so a migration would come later anyway.
  - Sphinx + MyST: very stable, but a heavier config and a different ecosystem.
- **Status:** Active. Re-check Zensical's stable release around 2027-02.

---

## D-017 · 2026-11-18 · The new repo is `siddharthps/pm25-forecast`

- **Decision:** Repo `pm25-forecast`, with the page at `siddharthps.github.io/pm25-forecast`.
  "AirWatch" stays as the project's display name in the docs.
- **Why:** Descriptive, searchable and city-free (the city check could pick somewhere other than
  Chicago). The owner chose this over my recommendation, `airwatch`.
- **Status:** Active. The repo is created in T0d with the owner's go-ahead.

---

## D-018 · 2026-11-18 · AWS infrastructure in Terraform (settles OQ-3)

- **Decision:** All AWS resources (buckets, Lambda, EventBridge Scheduler, SNS, SSM, IAM, budget
  alarm) are defined in Terraform under `infra/`, with remote state in a **versioned private S3
  bucket**. Exact versions of the Terraform CLI and the AWS provider are looked up and pinned.
  Region **us-east-1** (as in v1) unless T0c finds a reason to change. The owner's alert email
  goes in a gitignored `*.tfvars`, never in the repo.
- **Why:** The most widely used IaC tool. Resources are reviewable in PRs and can be rebuilt or
  torn down with one command, which also proves the "under $5" claim. OpenTofu is a drop-in
  alternative if the BSL licence ever matters.
- **Alternatives:**
  - AWS CDK in Python: AWS-only, needs a bootstrap stack and adds Node.
  - Console steps: not reproducible, and drift goes unnoticed.
- **Status:** Active. Terraform isn't installed yet; installing it is part of T0c.

---

## D-019 · 2026-11-18 · Issue time 06:00 America/Chicago, forecasting D+1 (settles OQ-6)

- **Decision:** Confirmed as in SPEC § Key definitions. The run starts at 06:00 local on D and
  uses complete observations through the end of D−1 plus the latest weather run published before
  06:00.
- **Why:** History can be rebuilt exactly from whole days, the page updates every morning, and it
  is a genuine next-day forecast.
- **Alternatives:**
  - 18:00 with today's partial data: needs hourly AQS history and exact partial-day matching.
  - Forecasting today instead of tomorrow: rejected because it isn't next-day.
- **Status:** Active. **Frozen:** the T3 property tests hard-code it.

---

## D-020 · 2026-11-18 · Skills installed into the new repo and committed (settles OQ-7, Q-1)

- **Decision:** In T1, run `npx skills add addyosmani/agent-skills` at project scope inside
  `pm25-forecast`. Commit `.claude/skills/` and `skills-lock.json` (pinned commit plus hashes).
  Afterwards, delete the copy in the parent folder.
- **Why:** Any session opened in the repo gets the skills, the trial setup is reproducible, and
  the workflow is visible to reviewers. It is still a trial (D-001): a global install only if the
  owner likes them.
- **Note:** The installer copies only skill folders. Shared `references/` (such as
  `definition-of-done.md`) are not installed, so the plan defines its own Definition of Done.
- **Installed 2026-11-18 (T1):** upstream had moved on since the trial install that morning, from
  commit `39b723c` (25 skills) to `8c99fa3` (26 skills, adding `accessibility-engineering`), and 4
  existing skill files had changed. The new script `accessibility-engineering/scripts/audit-a11y.sh`
  was reviewed: it runs `@axe-core/cli` and `pa11y` through `npx` at pinned versions against a
  given URL, and deletes only its own temp folder. The two scripts reviewed earlier are unchanged.
  `skills-lock.json` pins `8c99fa3` with hashes.
- **Status:** Active.

---

## D-021 · 2026-11-18 · Validation is split: a basic report in the skeleton, full classes later

- **Decision:**
  - **T12a (Phase 2, skeleton):** the validation module and report framework, with three problem
    classes from day one: duplicates by site/POC/date, implausible values, and coverage gaps. It
    runs on AirNow and AQS, in both the daily flow and the bulk download.
  - **T12b (Phase 3):** the remaining classes (key reuse, wrong-entity records, reference dates,
    units) and the weather sources.
- **Why:** This is the owner's own rule: validation is its own first module, run on every source
  from the start. In a previous project, bad records surfaced one at a time, the last one in the
  final rebuild. Cost: about +2 hours in week 1.
- **Status:** Active.

---

## D-022 · 2026-11-18 · Write-up rules: light version now, expandable

- **Decision:** In T11, before any chapter prose:
  1. A one-page **bottom line** with `results.json` placeholders.
  2. A **chapter outline**.
  3. A one-page **style sheet** covering banned words, the page template, and what goes in docs
     versus notes.

  **Vale** checks the style sheet in CI, with a simple length cap per page. The rest of the
  owner's book discipline (per-section length targets, the chapter-1 review loop) is added only if
  the docs grow past a handful of pages.
- **Why:** The write-up is a README plus about 5 short pages, not a book, but the last write-up
  needed many review passes. The owner asked to start light and be able to expand.
- **Status:** Active.

---

## D-023 · 2026-11-18 · Work mode: the agent builds; the owner drives each new tool the first time

- **Decision:** The agent implements most tasks and explains each PR in plain terms (what changed,
  why, what to look at). For the **first use of each new tool** (first Prefect deploy, first
  Terraform plan/apply, first MLflow run, first Evidently report, first AWS console check), the
  owner runs the commands from a step-by-step guide.
- **Why:** Learning the tools is a stated goal, and doing it at these points teaches what matters
  without hand-writing all the plumbing. It keeps the 2026-11-25 and 2026-12-23 dates realistic.
- **Alternatives:**
  - The agent builds and the owner only reviews: learning would come mostly from reading.
  - The owner builds and the agent guides: the dates would likely move.
- **Status:** Active.

---

## D-024 · 2026-11-18 · Pipeline AWS access: keyless if possible, else a rotated narrow key

- **Decision:**
  - In T8, first check (from current Prefect and AWS docs) whether Prefect Managed runs can assume
    an AWS role without stored keys (OIDC-style federation). If yes, use that.
  - If not, use a **dedicated IAM user** whose only rights are this project's S3 prefixes. Its key
    is stored as a Prefect secret block, rotated **every 90 days** (recorded in
    `notes/TOKENS.md`, with an email reminder).
  - Either way, the docs say plainly which approach is used and why.
- **Why:** Prefect Managed runs outside AWS but must write to S3. The owner's rule prefers
  short-lived credentials. A narrowly scoped, rotated key is the honest fallback.
- **Alternatives:**
  - A rotated key without checking for keyless access: misses a chance to avoid long-lived keys.
  - Routing writes through API Gateway + Lambda: an extra API to build and secure, for a small
    gain.
- **Status:** Active.

---

## D-025 · 2026-11-18 · The public page follows the AirNow Data Exchange Guidelines

- **Source:** *U.S. EPA AirNow Data Exchange Guidelines* (PDF linked from the AirNow API FAQ,
  "Last Updated August 2025"), read 2026-11-18.
- **Obligations, and how the page meets each one:**
  1. *AirNow data are preliminary, and displays must say so.* → Every page section showing AirNow
     values is labelled **"preliminary, not validated"**.
  2. *Use validated (AQS) data for analysis whenever possible.* → Already the design: training,
     CV and the 2025 test use AQS (D-004, D-008). Live scores are labelled preliminary and
     re-scored against AQS later (T26).
  3. *Credit the state, local and tribal agencies and the EPA AirNow program first.* → A credits
     block naming the reporting agencies for the city's monitors, plus EPA AirNow, linking to
     `airnow.gov/partners`.
  4. *Data, official forecasts and advisories must not be altered; agencies are the forecast
     authority.* → Observed values are shown as received. Derived values (daily means) are
     labelled as derived. Our forecast is labelled **"experimental model forecast, not an official
     air quality forecast"**, with a link to AirNow.gov for official forecasts and advisories.
  5. *Show AQI using the official categories and RGB colours (AQI Technical Assistance
     Document).* → The page's AQI colours come from that document, pinned in one place in
     `site/`.
  6. *Tell the agencies and AirNow that a product relies on the data, and keep contact details
     current.* → **Owner action:** sign the guidelines form and email it to `dmc@airnowtech.org`
     before the page goes public (T7). The agent does not send email.
- **Why:** These are the data provider's terms, and following them visibly is part of the
  "production ML done properly" story.
- **Status:** Active. Added to T7's "done when" list.

---

## D-026 · 2026-11-18 · Python 3.12, matching Prefect's managed image (settles OQ-4)

- **Decision:**
  - The project targets **Python 3.12** (`requires-python = ">=3.12,<3.13"`, plus a
    `.python-version` file).
  - Ruff `target-version` and mypy `python_version` are set to match.
  - The Prefect deployment (T8) pins the image tag `prefecthq/prefect:3-python3.12`, not
    `3-latest`, so a change in Prefect's default can't silently change the runtime.
- **Evidence (Docker Hub API, 2026-11-18):** `prefecthq/prefect:3-latest` has the same amd64
  digest (`sha256:f4e4f4ff612c…`) as `3-python3.12`; both were pushed 2026-11-13. Tags 3.10
  through 3.14 also exist.
- **Why:** Develop and test on the same Python the daily run uses. Pinning the tag makes a runtime
  upgrade a deliberate change.
- **Status:** Active. Revisit when moving to a newer Python (a new D-entry, and an image tag change
  in T8).

## D-027 · 2026-11-18 · Python dependency updates: a weekly uv-lock job, not Dependabot (T2)

- **Decision:**
  - Dependabot handles **`github-actions` only**, grouped weekly with a 7-day cooldown.
  - Python dependencies are upgraded by `.github/workflows/uv-lock-upgrade.yml`: weekly
    `uv lock --upgrade` with the pinned uv (the `required-version` floor). It opens or refreshes
    one PR on the fixed branch `deps/uv-lock-upgrade`.
  - PRs opened with `GITHUB_TOKEN` don't trigger workflows, so the job then runs
    `gh workflow run ci.yml --ref deps/uv-lock-upgrade` (`workflow_dispatch` is the documented
    exception). The checks land on the PR's head commit. No extra credential is stored.
  - `tests/unit/test_ci_config.py` enforces all of this.
- **Evidence (2026-11-18):** The GitHub docs source (`github/docs`,
  `data/reusables/dependabot/supported-package-managers.md`) lists `uv` for version and security
  updates. `dependabot-core` regenerates `uv.lock` by running uv, and its `uv/Dockerfile` copies
  **uv 0.13.7**. Our `[tool.uv] required-version = ">=0.13.9"` would make every Dependabot uv run
  fail. This is inferred from uv's documented `required-version` behaviour, not observed.
- **Options rejected:**
  - Lowering the floor to Dependabot's uv: local, CI and Dependabot could resolve differently,
    and the floor would follow Dependabot's release pace.
  - A GitHub App or a PAT for CI on the bot PRs: both are extra credentials, and a PAT expires.
- **Needs (owner, one-off):** Settings → Actions → General → "Allow GitHub Actions to create and
  approve pull requests".
- **Status:** Active. Revisit if Dependabot's bundled uv reaches our floor and we want native
  updates (a new D-entry). Security alerts for uv still come from the dependency graph.

## D-028 · 2026-11-18 · Public JSON in its own bucket, not a prefix of the private one (refines D-012)

- **Decision:**
  - **Private bucket `pm25-forecast-data-65bc08`:** all four S3 Block Public Access settings on.
  - **Public bucket `pm25-forecast-public-65bc08`:** derived JSON only.
    - Anonymous `s3:GetObject` on objects, granted through the bucket policy.
    - No listing, ACLs still blocked, and CORS limited to the Pages origin.
  - The pipeline policy may put only `*.json` objects there.
  - `infra/tests/storage.tftest.hcl` enforces all of this on every plan.
- **Why:**
  - Block Public Access is set per bucket. A public prefix inside the private bucket would need
    the bucket-wide policy blocks off. Then only a policy statement would keep `raw/`, `records/`
    and `models/` private, and one mistake could publish licensed or private data.
  - With two buckets, the worst a misplaced key can do is fail to appear on the page. This follows
    the owner's rule to keep private and public outputs apart.
- **Facts:** The account has no account-level Block Public Access configuration (read-only
  check, 2026-11-18), so a public-read bucket is possible. Adding an account-level block later
  would break the page.
- **Alternatives:** A public prefix in one bucket, as D-012 literally says. Rejected for the
  risk above.
- **Status:** Active. Owner's choice, 2026-11-18.

---

## Open questions (to settle, then move into a D-entry)

- **Q-6:** Which city? *(settled by the D-006 data check in T4)*
- Further open items are listed in [SPEC.md](SPEC.md) § Open Questions.

Closed: Q-1 → D-020. Q-2, Q-3, Q-5 → D-003. Q-4 → D-003 and D-011.
