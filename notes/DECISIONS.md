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
  - *2026-11-19 (T5):* the live input uses the **hourly file product**, which needs no key and
    carries `AQSID`. The planned API history check wasn't needed, so the API window is still
    unconfirmed. Checked on a real file: `PM25` is the raw hourly value, times are UTC, and each
    file is published about three hours after its hour (see `observations/airnow.py`).

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
- **Status:** Active. Settled since:
  - SPEC § Key definitions sets a valid day at ≥ 18 of 24 hours, with POCs averaged per hour.
  - The local-day zone is the `city_tz` setting (T3, #7), fixed when T4 picks the city.
  - AQS's daily-record rules: settled by D-032 (labels from hourly data with this rule; T5).

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
- **Frozen criteria (owner-approved 2026-11-18, T4 #9, committed before any candidate data was
  fetched):**
  - **Candidates:** the CBSAs (metro areas) of Chicago, Salt Lake City, Los Angeles and Phoenix.
    AQS's `list/cbsas` gives the codes. The rest of the lists isn't candidate data.
  - **Data:** AQS parameter 88101 (PM2.5, local conditions), **continuous hourly instruments only**
    (sample duration 1 hour). Days flagged as exceptional events (for example wildfire smoke) are
    **kept**.
  - **Monitor:** one AQS site; co-located instruments (POCs) at that site count as one monitor.
  - **Valid day:** at least one hourly instrument at the site reported **≥ 18 of 24 hours** that
    day (local day, as AQS daily summaries are).
  - **Good year:** **≥ 75%** of that calendar year's days are valid days.
  - **Qualifying monitor:** all three of these hold.
    - It has **≥ 8 good years** in 2009–2024.
    - **2024** is one of them.
    - Its AQS site ID appears for PM2.5 in AirNow's monitoring-site list on the day the check runs.
  - **A city passes** if it meets all four rules below.
    1. **≥ 5 qualifying monitors.**
    2. **Bad-air share ≥ 0.5%.** That is, ≥ 0.5% of valid monitor-days in 2009–2024 at the
       qualifying monitors have a daily mean **above 35.0 µg/m³**, the 24-hour primary NAAQS
       (EPA NAAQS table, read 2026-11-18). A site's daily mean is the mean of its instruments'
       daily means.
    3. **Test year present:** **≥ 5** qualifying monitors have **2025** as a good year. Only day
       counts are used. 2025 PM values are dropped as they are read, and never stored, printed or
       scored (D-008).
    4. **Weather coverage:** one request each to Open-Meteo and CAMS at the CBSA's centre returns
       data.
  - **Choice:** **Chicago, if it passes.** Otherwise, the passing city with the most qualifying
    monitors. Ties are broken by the higher bad-air share. If no city passes, stop and bring the
    scored table to the owner (no rule is relaxed silently).
- **Clarifications (made before any candidate was scored; each committed before the scoring
  script ran):**
  - *2026-11-18, owner:* "appears for PM2.5 in AirNow's monitoring-site list" means a row in
    `Monitoring_Site_Locations_V2.dat` with `Parameter = PM2.5` and **`Status = Active`**, matched
    on `AQSID` (the 9-digit state + county + site code). The list also carries inactive sites,
    and D-006's draft said "active in both".
  - *2026-11-18, field mapping (checked on Charlotte, CBSA 16740, not a candidate):* an "hourly
    instrument" is an AQS daily-summary row with `sample_duration_code = "1"` ("1 HOUR"), and its
    `observation_count` is the number of hours reported that day. The `24-HR BLK AVG` rows (code
    `X`) are AQS's derived per-standard summaries and aren't counted again.
  - *2026-11-18, CBSA codes:* the candidates are pinned to the current OMB codes **Chicago 16980,
    Salt Lake City 41620, Los Angeles 31080, Phoenix 38060**. Each is checked against AQS's
    `list/cbsas` name.
    - AQS's list also carries **31100** "Los Angeles-Long Beach-Santa Ana, CA". Census's
      December 2009 delineation (`list1.txt`) shows 31100 made of Los Angeles and Orange
      counties. Since February 2013, the same two counties are 31080 "Los Angeles-Long
      Beach-Anaheim" (Census Feb 2013 `list1.xls`; BLS OEWS area definitions, May 2025).
    - It's the same area renumbered, so 31080 is used. If an LA year returns no rows under 31080,
      that year is fetched under 31100, and the fallback is recorded in the result.
  - *2026-11-19, a new event label (no scoring had happened):* the first live run stopped, as
    designed, on the unknown `event_type` "Concurred Events Excluded" in Chicago's data.
    - Every such hourly row has an "Events Included" twin for the same instrument-day (20,857
      pairs; labels counted, no values read).
    - So it's an *excluded* version and is dropped. The included version is kept, as the frozen
      rule says. Any other new label still stops the check.
  - *2026-11-18, weather "centre":* the CBSA's centre for the weather check is the mean position
    of its PM2.5 monitors in the AQS rows (AQS's CBSA list carries no coordinates).
- **Status:** Active. Criteria **Frozen** (above). Settles Q-6 once the check has run.

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
- **Status:** Active. **Frozen.** Persistence on a thin day (a monitor without a valid D−1 is
  skipped and listed, never filled from an older day): D-034.
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
- **Status:** Active. Settles Q-4b. S3 conditional writes: verified against AWS's docs and on real
  S3 in T6, recorded in D-034. Still to verify (T9): how a Lambda calls the Prefect API (key stored
  in SSM Parameter Store as a SecureString).

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
- **Status:** Active, **refined by D-028**: the public JSON lives in its own bucket, not a prefix of
  the private one. Attribution must appear on the page: EPA AirNow and AQS, Open-Meteo
  (CC BY 4.0) and CAMS. The public files' contents (`latest.json`, `history.json`), the page and
  its go-live gate: D-036.

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
- **Status:** Active.
  - Terraform 1.17.2 was installed in T0c (checksum and signature verified).
  - The first resources were applied in T3b (#8, PR #41): `hashicorp/aws` 6.73.0, with state in
    `pm25-forecast-tfstate-65bc08`.

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
- **Status:** Active. **Frozen:** the T3 property tests hard-code it. AirNow keeps rewriting
  its hourly files for about 7.7 hours; the strict issue-time cut is in D-034.
  - *2026-11-19, kept for Phoenix (owner, D-030):* the issue time follows the publisher's clock
    (the author is in Chicago), not the forecast city's. Phoenix's D−1 ends at 07:00 UTC, and the
    issue is 11:00 or 12:00 UTC, so there's a 4–5 hour margin. Nothing leaks, and the data is
    complete.

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
- **Status:** Active. T12a's rules and severities: D-033.

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
- **Status:** Active. Added to T7's "done when" list. The AQI rules, the colours' one home and
  the go-live gate are in D-036.
  *2026-11-20:* obligation 6 is met. The owner emailed the signed form, and AirNow's
  reply is in D-039.

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

## D-029 · 2026-11-18 · `ruff format` skips the vendored skills (scoped, not loosened)

- **Decision:** `[tool.ruff.format] exclude = [".claude/skills/**"]` in `pyproject.toml`. Ruff
  *lint* coverage is unchanged, and so is formatting of every file the project owns, including
  Python code blocks in our own Markdown.
- **Why:**
  - `ruff format` also formats Python code blocks inside Markdown, and one upstream skill file
    failed.
  - Those files are copied from upstream and not edited here (D-020). Reformatting them would
    fork them from their source and make updates noisy.
  - The rule "fix the cause, never loosen the check" is about our own output. These files aren't
    ours.
- **Rule refined (owner, 2026-11-18):**
  - The owner's global CLAUDE.md and SPEC § Boundaries now allow scoping one check away from
    files the project doesn't own, recorded as a D-entry.
  - Whole checks and rules are never relaxed.
- **Status:** Active. Owner accepted, 2026-11-18. *Refined 2026-11-20 (#55, D-037):* the
  `.claude/skills/**` exclusions in markdownlint and `ruff format` now list exactly the vendored
  skills in `skills-lock.json`, so our own skills (`delete-comment`) stay checked; a test keeps
  the lists in step with the lock.

---

## D-030 · 2026-11-19 · The city is Phoenix (settles Q-6, by the frozen D-006 check)

- **Decision:** AirWatch forecasts the **Phoenix-Mesa-Scottsdale, AZ** metro area (CBSA
  **38060**). `city_tz` is `America/Phoenix` (no daylight saving time).
- **Why:** it is the only candidate that passed every frozen D-006 rule. The run was
  `scripts/city_check.py` on 2026-11-19, 03:19–03:34 UTC, with the AirNow site list of the same
  day. The rules and all their clarifications were committed first (`4390340` … `0570c91`).

  | City | CBSA | Qualifying monitors | Bad-air share | Good 2025 | Weather | Result |
  | --- | --- | --- | --- | --- | --- | --- |
  | Chicago | 16980 | 3 | 0.44% | 3 | yes | fails: monitors, bad-air share, 2025 |
  | Salt Lake City | 41620 | 4 | 1.22% | 4 | yes | fails: monitors, 2025 |
  | Los Angeles | 31080 | 1 | 1.50% | 1 | yes | fails: monitors, 2025 |
  | **Phoenix** | 38060 | **10** | 0.57% | **10** | yes | **passes** |

- **What limited the others (descriptive only; no rule was changed):** few sites have ≥ 8 good
  years of *hourly* 88101 data. Many hourly regulatory instruments in Chicago, Salt Lake City and
  Los Angeles began reporting in 2016 or later. Phoenix's went hourly in 2010–2012.
- **Consequences:**
  - The issue time stays 06:00 America/Chicago (D-019, frozen; see its Status).
  - Training labels come from Phoenix's 10 qualifying monitors (AQS site IDs): 040130019,
    040131003, 040131004, 040132001, 040134003, 040134005, 040139812, 040139997, 040210001,
    040213015. That's eight in Maricopa County (013) and two in Pinal County (021).
  - The public page credits the Arizona and Maricopa County agencies (D-025).
- **Alternatives:** none. The choice rule was fixed in advance. Chicago, the default, would have
  won only if it passed.
- **Status:** Active.

---

## D-031 · 2026-11-19 · Raw data is stored as received; out-of-range readings are counted, not blocked

- **Decision:**
  - Downloads (`raw/`) keep every reading as received.
  - `validate_hourly` blocks only on *structural* problems: columns, types, UTC times, site
    IDs, and "available after measured".
  - Readings outside a crude, unsourced range (−10 to 1,000 µg/m³) are **counted**, in each
    part's manifest entry and its log line, and never dropped or blocked at ingestion.
  - T12 sets sourced bounds and decides how such hours are treated.
- **Why:** The first bulk run stopped on 1,167 µg/m³ at site 040130019, at 07:00 UTC on
  2014-01-01. That's midnight in Phoenix on New Year's, almost certainly fireworks. It's a real
  event, and my guessed 1,000 limit would have blocked it.
  - Judging data belongs downstream of a faithful raw copy, so every quality decision is
    visible and repeatable.
  - This fixes the check's cause (a guessed bound in the wrong place). It doesn't loosen it:
    the count is still reported, and T12 still decides.
- **Alternatives (rejected):**
  - Raise the bound and keep blocking: still a guess, and the next real extreme stops the run.
  - Drop out-of-range hours at download: loses real events from the raw copy permanently.
- **Status:** Active. Owner's choice, 2026-11-19. The sourced per-method bounds are in D-032;
  how out-of-range hours are treated is settled in D-033 (excluded and counted).

---

## D-032 · 2026-11-19 · Labels and live inputs come from the same kind of instrument (settles OQ-8)

- **Decision:**
  - Training labels are built from AQS **hourly** `sampleData` (parameter 88101, sample
    duration 1 hour), averaged into daily means by our own rule: POCs per hour first, then
    ≥ 18 of 24 hours of the city's local day.
  - AQS's own daily summary records (and their sample-duration and pollutant-standard
    variants) are **not used for labels**, so OQ-8's question about which daily records count
    doesn't arise.
- **Checked against AQS's method table** (`methods_all.html`, parameter 88101, 2026-11-19).
  The training sites' hourly instruments use four methods, all **Continuous** and **FEM**:
  - 170: Met One BAM-1020 (EQPM-0308-170);
  - 181: Thermo TEOM 1400/1405 FDMS (EQPM-0609-181);
  - 182: Thermo TEOM 1405-DF FDMS (EQPM-0609-182);
  - 638: Teledyne T640X (EQPM-0516-238).
  - AirNow reports continuous monitors, and the same sites (`AQSID` = AQS site ID). So labels
    and live inputs measure the same thing.
  - The codes and their AQS valid ranges are in `observations/sites.py`.
  - `unverified_methods` flags any other code before training. A new instrument type is
    checked, never assumed.
- **For T12 (D-031):** AQS's per-method valid ranges are the *sourced* bounds:
  - 170: −10 to 975;
  - 181 and 182: −10 to 5,000;
  - 638: 0 to 10,000.
  - The 2014 fireworks hour (1,167) came from method 181, so it's inside its instrument's range.
- **Status:** Active.

---

## D-033 · 2026-11-19 · Validation rules for the skeleton (T12a)

- **Decision:** what each rule does, set before any real data was checked:

  | Class | Rule | Severity | Effect on the rows |
  | --- | --- | --- | --- |
  | Duplicates | the same (source, site, POC, hour) twice | hard | run stops |
  | Implausible values | a method with no sourced range (D-032) | hard | run stops; excluded |
  | Implausible values | outside the method's AQS valid range | warn | **excluded and counted** |
  | Implausible values | negative but inside the range | info | kept (instrument noise) |
  | Implausible values | 12+ identical hourly values in a row, one instrument | warn | kept |
  | Coverage gaps | a local site-month with < 75% of its hours usable | warn | none |
  | Coverage gaps | a listed site with no rows at all | warn | none |
  | AirNow IDs | the reader's drop counts (not an AQS ID, unmatched site, other) | info | none |

  - **Hard** stops the run: the daily flow writes no record (T6 wires this).
  - **Warn** is reported and the run goes on. **Info** is counted for the record.
  - AirNow rows carry no method, so they get the widest verified range (−10 to 10,000).
  - Coverage is judged on usable hours, with co-located instruments counted once per hour.
    History starts each site at its first reading and covers the final years only (2009 to
    the start of the current year). The daily flow expects the whole day.
  - Reports hold counts, sites and times, never a measurement. So a report covering 2025 says
    nothing about the test period's values (D-008).
- **Why:**
  - **Out-of-range hours are excluded (owner's choice):** AQS says the instrument can't
    measure outside its range, so such a reading is a fault. One faulty hour shouldn't stop the
    day, but it shouldn't skew the average either. The raw copy keeps it (D-031).
  - **The flat-line rule is a judgement (owner's choice):** no published EPA threshold was
    found. Half a day of identical values is very unusual, and warn-only makes a false alarm
    free. T12b can tighten it.
  - **75%** is the SPEC's daily rule (18 of 24 hours), applied per month.
  - **Duplicates are hard** because a repeated hour means a pipeline or source fault, and it
    would silently double-weight that hour in a daily mean.
- **Alternatives (rejected by the owner):**
  - out-of-range hours: keep them and only warn, or block the run;
  - flat lines: 6+ hours, or 24+ hours with exclusion.
- **Status:** Active. Owner's choices, 2026-11-19. Refines D-021 and settles D-031's "how such
  hours are treated".

---

## D-034 · 2026-11-19 · The daily forecast's record and its edge cases (T6)

- **Decision:** set before any real run, by the owner:
  1. **The record is named after the target day:** `records/forecast_date=<D+1>/forecast.json`.
     Scoring (T10), the page (T7) and the AQS re-score (T26) look up a day directly; the issue
     date is stored inside.
  2. **A monitor without a valid D−1** (under 18 of 24 hours) is left out and listed in the
     record with its hour count. **No qualifying monitor:** the run fails with no record, so a
     retry can succeed once AirNow's files arrive.
  3. **Fail loudly until T9:** every failure raises and the command exits 1. Prefect (T8) marks
     the run failed, and T9 adds the email alert.
  4. **Strict issue-time cut:** only AirNow rows published by the issue time are used. Later
     rows are dropped and counted (`dropped_published_after_issue`).
- **Measured on 2026-11-19:** AirNow **rewrites each hourly file for about 7.7 hours** after its
  hour. Every file of 2026-11-17 and 2026-11-18 was last modified 6.7–7.7 hours after it. The
  "about three hours" seen in T5 was only a first version.
  - An on-time run (06:00 Chicago = 12:00 UTC in winter) sees every file as it stood then.
  - A run after about 13:42 UTC drops D−1's last two hours (22 of 24 left, still valid).
- **S3 behaviour relied on** (AWS user guide "conditional writes" and the PutObject API
  reference, read 2026-11-19):
  - `If-None-Match: *` writes only if the key has no current version, otherwise **412**;
  - of racing writes, "the first write operation to finish succeeds";
  - **409** means a delete raced the write, and the docs say to retry (we retry 3 times);
  - on a versioned bucket a delete reopens the key, so the pipeline has no delete permission
    (`infra/iam.tf`) and no lifecycle rule expires a current record (`infra/s3.tf`);
  - a lost reply after a successful write would look like a 412 on retry. So on 412 the stored
    record is read back and used, and the published forecast is always the recorded one.
  - moto 5.2.5 enforces the 412 and the delete-reopens behaviour (checked 2026-11-19).
- **Order of a run:** check the issue time → reuse an existing record (never recompute) →
  fetch → drop late rows → validate, saving the report → stop on a hard failure → forecast →
  **record (once)** → publish `latest.json`. That file is never rewritten with the same content
  and never moved to an older day.
- **Why:**
  - (1) avoids a "+1 day" in every reader;
  - (2) keeps nine monitors' forecasts when one is down, and never hides the gap;
  - (3) builds alerting once, in T9;
  - (4) keeps the live track record, our truly unseen test, free of after-the-fact data.
- **Alternatives (rejected by the owner):** (1) issue date; (2) any thin monitor stops the run,
  or fall back to an older day (that would change D-009's persistence); (3) build the email
  now; (4) use the latest files and flag the record.
- **Status:** Active. Owner's choices, 2026-11-19. Refines D-019 (the AirNow timing) and D-009
  (persistence on a thin day).

---

## D-035 · 2026-11-19 · Tests run in parallel to keep the core suite under 30 s

- **Decision:** pytest-xdist 3.8.0 (looked up on PyPI) runs the core suite on **4 workers with
  `--dist load`** (`pyproject.toml` addopts). `-n 0` runs serially, e.g. when debugging.
- **Why:** T6's leakage property tests run the whole forecast on every example, and pandas'
  fixed cost per call makes each run about 20 ms. The suite went from about 24 s to 34 s, over
  the SPEC's 30 s.
  - Profiling found no single hotspot to fix.
  - Removing repeated work (a cached baseline, one moto per file) wasn't enough.
  - Measured: serial 33 s; 4 workers with `load` 15 s; 6 or 8 workers 19–20 s; 12 (`auto`)
    24 s, because starting workers costs more than it saves.
- **Alternatives (rejected by the owner):** fewer property examples in the everyday run (it
  checks less); a separate CI step for these tests (locally they'd only run on request).
- **Status:** Active. Owner's choice, 2026-11-19.

---

## D-036 · 2026-11-19 · The public page: AQI rules, public files, credits and the go-live gate (T7)

- **AQI, from EPA's Technical Assistance Document** (EPA-403/B-26-003, May 2026, read
  2026-11-19), in one home, `airwatch/aqi.py`:
  - PM2.5 truncated to 1 decimal; Equation 1 on Table 6's 24-hour breakpoints; the index rounded
    to the nearest integer (p. 13–14);
  - above AQI 500, Equation 1 extends the 301–500 segment (Table 6, footnote 4);
  - **the area's value is the highest monitor** (p. 13: "the highest concentration among all of
    the monitors within each reporting area");
  - the categories and **standard colours** from Tables 1–2. ColorVision Assist colours are
    optional and not used.
  - **Not in the TAD:** a negative mean reads as AQI 0, and the text on each colour is black or
    white, whichever has the higher WCAG contrast.
- **The colours have one home:** `aqi.py`, sent in the JSON. The site holds none (a test checks
  this). This refines D-025's "pinned in one place in `site/`" to one place overall.
- **Public files** (`publish.py`, version 2):
  - `latest.json` has the city summary and every monitor;
  - `history.json` holds every recorded day, newest first, **rebuilt from the private records**
    on each run, so it can't drift from them.
  - Each payload must pass a strict JSON schema (`forecast/schemas/`, no field outside the list)
    and a secret scan before upload; a refusal writes nothing.
- **The page:** plain HTML, CSS and JavaScript, with no outside scripts or styles.
  - A Content-Security-Policy allows only the page itself and the public bucket.
  - Data is written as text, never as HTML.
  - A local `?data=` preview accepts same-site paths only (a test found that `//host/` slipped
    through the first rule).
  - No chart library yet: charts are T25, which pins its version.
- **Checks on the page's code:** Biome 2.6.8 (`biomejs/pre-commit`, pinned to the release
  commit, published 2026-11-15) lints and formats the JavaScript and CSS. `node --test` runs the
  page's tests in CI, with Node from `.nvmrc`. The lint-coverage test now also requires every
  JS and CSS file to be in Biome's scope.
- **Go-live gate (owner's choice):** `.github/workflows/pages.yml` packages only `index.html`,
  `app.js` and `style.css`. Its deploy job runs only when the repository variable
  `PAGES_GO_LIVE` is `true`. The owner sets it after emailing the signed AirNow guidelines form
  (D-025) and waiting for any reply.
- **Credits (owner's choice, against the agent's recommendation):** every planned source from
  the first page, each with what it's used for:
  - EPA AirNow (the forecasts shown);
  - EPA AQS (validated history, training);
  - Open-Meteo, CC BY 4.0 (weather, being added);
  - Copernicus CAMS (composition forecasts, being added).

  The agencies (Maricopa County AQD, Arizona DEQ, Pinal County AQCD, from AirNow's
  `DataSource` field) and EPA AirNow come first, as D-025 requires.
- **Why:** EPA's rules are the data provider's terms (D-025), so they're taken from the document
  and pinned by tests to its own worked example. The gate keeps a public repo's Pages site from
  going live before the form. The schema and scan stop a future bug from publishing private
  data.
- **Alternatives:**
  - deploy normally once the form is sent, or leave the deploy job out (owner chose the gate);
  - credit only the sources in use (the agent's recommendation; the owner chose all);
  - the median monitor as the city value (rejected: the TAD says the highest).
- **Design review (frontend-design plugin; owner chose "fixes and scale band", system font),
  same night, before the PR:**
  - **Fixes:**
    - the heading names the forecast day ("Forecast for …"), never "Tomorrow", which goes
      wrong once that day has started;
    - the page's own palette is neutral and cool, with no colour that could pass for an AQI
      category (a test checks every colour in `style.css`);
    - the history uses the category colours;
    - links show a visible keyboard focus;
    - the load error says what happened and what to do.
  - **The scale band is the hero:** the six categories as equal segments, with a marker placed
    within the forecast's category. `latest.json` carries the category table from
    `aqi_scale()`, so the colours still have one home.
  - **Monitors are listed by concentration, highest first.** That's the rule that picks the
    city summary, because two monitors can share an AQI. Each monitor has a CSS bar, hidden on
    narrow screens where it repeats the number.
  - **Type:** a 1.25 modular scale on the system font. Self-hosting a typeface was declined.
  - **Checked by screenshot** in headless Edge at desktop width and in a 360 px frame. A
    plain 390 px window looked clipped only because headless Edge has a minimum window width.
- **Status:** Active. Owner's choices, 2026-11-19. Refines D-025 (where the colours live).
  *2026-11-20:* the go-live gate is met (D-039).

---

## D-039 · 2026-11-20 · AirNow's reply: the go-live gate is met (#14)

- **Decision:** the page may go public with the D-025 credits and labels as built. The owner
  emailed the signed Data Use Guidelines form to `dmc@airnowtech.org` (D-025, obligation 6),
  and AirNow replied.
- **The reply, as the owner summarised it (2026-11-20):**
  - AirNow data is U.S. government public-domain information.
  - Emailing beforehand is an administrative courtesy, so AirNow can track outside
    integrations and share data-handling advice. It is not a licence step, and it doesn't
    block a non-commercial student or portfolio project.
  - They may follow up in a couple of weeks, or may not.
- **Still open:** the email also asked whether AirNow tells the three reporting agencies, or
  whether the owner should. The reply as summarised doesn't answer that. The page already
  credits the agencies first (D-025, obligation 3). If AirNow's follow-up asks for more, it
  gets a new D-entry.
- **Why:** D-036's gate was "after emailing the form and waiting for any reply". The reply
  came, and it says the email was never a blocker.
- **Status:** Active. Owner's decision, 2026-11-20. Meets the gate in D-036 and obligation 6
  in D-025.

---

## D-037 · 2026-11-20 · Code comments are banned, held by a ratchet (#55)

- **Decision:** code says what it does through names, types, test ids and assert messages.
  Whatever a comment would add beyond that goes where it belongs:
  - a decision goes to a D-entry in this file;
  - a test's scenario goes into its docstring;
  - a hacky spot gets an issue to fix the code.
- **Scope (owner, 2026-11-20):** Python `#` comments in `src/`, `scripts/` and `tests/`; JS and
  CSS comments in `site/` and `tests/site/`.
  - Not counted: Python docstrings, and JSDoc blocks directly before a declaration (the JS
    equivalent).
  - Not counted: tool pragmas (`# type: ignore`, `# noqa`, `# pragma: no cover`, `# fmt:`,
    `# ruff:`, `# mypy:`). A pragma followed by prose still counts.
  - Not counted: config files (workflows, Terraform, `pyproject.toml`, pre-commit). Their
    comments carry the version tag after each pinned SHA and the reason for each lint ignore,
    which other rules require.
- **Enforcement:** `airwatch.devtools.comments`, run as a pre-commit hook (so also in CI's
  pre-commit step) and as a core test.
  - It counts comments per file against `comment-baseline.json`. A file may never go over its
    allowance, and a file not listed may have none.
  - When comments are deleted, the baseline must be lowered to match (`--update`). `--update`
    refuses to raise any allowance, so the baseline only ever goes down.
  - A test checks that every folder holding code is in the scope, so a new folder can't slip
    past it.
- **Why:** comments drift from the code they describe. Some also excuse a hack that then gets
  copied. Decisions in a comment are invisible to anyone reading this log. Ruff has no rule
  that bans comments (its `ERA` only catches commented-out code), so the check is our own.
- **Where the checker lives:** in the package (`src/airwatch/devtools/`), so strict mypy and
  the coverage floor apply to it, like the rest of the core logic.
- **The process:** `/delete-comment` (`.claude/skills/delete-comment/`) sorts comments into
  Tautology, Stale, Excuse and Decision record, then acts on each kind. The first pass's list
  is kept in `notes/comment-audit-2026-11-20.tsv`, and the facts it moved out of the code are
  in D-038.
- **Status:** Active. Owner's request and choices, 2026-11-20.

---

## D-038 · 2026-11-20 · Code notes: the decisions that lived in comments (#55)

- **Decision:** these choices and facts came out of code comments in the D-037 audit. No other
  entry held them. Each names where it applies. Comments that only pointed to an existing entry
  were deleted, since that entry stays the fact's home (the full list is in
  `notes/comment-audit-2026-11-20.tsv`).
- **AQS API** (`scripts/aqs_bulk.py`, `scripts/city_check.py`, `AQS_PAUSE_S = 6.0`):
  - AQS's terms ask for at most 10 requests a minute and a 5-second pause between requests
    ("Request Limits and Terms of Service", `aqs.epa.gov/aqsweb/documents/data_api.html`, page
    dated 2020-01-10, read 2026-11-20). A violation may get the account disabled without
    notice. Six seconds keeps under both limits.
- **AQS data** (`airwatch.observations`):
  - An AQS site ID is 9 digits: state (2), county (3), site (4). AirNow's `AQSID` uses the
    same form for monitors that are in AQS.
  - AQS's `time_local` is local *standard* time all year, with no DST. Only the GMT fields are
    read.
  - An AQS row's `available_at_utc` is the end of its `date_of_last_change` day. That's the
    earliest moment AQS is known to have held the value, which is what the leakage rule needs.
  - `time_utc` in the hourly schema is the start of the hour.
  - The bulk download writes a part's data first and only then the manifest entry that marks
    it done. A failed data write leaves the part to fetch again, never listed as done with no
    data behind it.
- **AirNow** (`airwatch.observations.airnow`):
  - About 30% of live PM2.5 rows carry 12-character or lettered IDs: temporary, tribal or
    international monitors. They can never map to an AQS site, so they're counted, not fatal.
- **Logging:** `scripts/aqs_bulk.py` and `airwatch.validation.report` set `botocore`, `boto3` and
  `urllib3` to ERROR. The SDK otherwise logs its own retries and token refreshes with
  tracebacks, and our rule is that request details are never logged. #52 gathers this into one
  logging setup. (httpx's request logging is handled by `fetch_json`, whose docstring says how.)
- **Time** (`airwatch.timeutil` and its property tests):
  - `ISSUE_TZ` and `ISSUE_HOUR_LOCAL` are module constants, deliberately not settings. Changing
    them changes every result, and D-019 is frozen.
  - `datetime` is a subclass of `date`, so a function that takes a calendar day rejects a
    `datetime` explicitly. Passing one is almost always a bug about which day is meant.
  - The DST reference in the tests follows US law since 2007 (Energy Policy Act of 2005): DST
    starts the second Sunday in March and ends the first Sunday in November, both at 02:00.
  - Hypothesis's `datetimes()` takes naive bounds, and `timezones=` decides whether examples are
    aware. That's why the bounds carry `# noqa: DTZ001`.
  - Instants in different zones are compared as POSIX timestamps. PEP 495 makes `==` False
    across zones for a time in the fold, the repeated hour when DST ends.
- **Validation** (`airwatch.validation`):
  - A missing value is never inside an instrument's valid range, so it's excluded.
  - The Markdown report shows the first 20 items per rule; the JSON keeps every item.
  - The last group of tests in `test_checks.py` came from planting bugs in the checks, as
    tests of the tests.
- **The page** (`site/`):
  - `?data=` accepts a same-site path only: `./x` or `/x`, named segments, no `..`, and never
    `//`, because to a browser `//host/` is another site.
  - On narrow screens the monitor bar is hidden, because it repeats the AQI number. Its room
    goes to the category name.
- **Tests:**
  - Secret-shaped test strings are built in pieces (`"AKIA" + "…"`), so secret scanners don't
    flag the test file itself.
  - PyYAML follows YAML 1.1, where a bare `on` key loads as the boolean `True`. The workflow
    tests read both keys.
  - The 2025 property test in `test_city_check.py` runs 20 Hypothesis examples. Each one
    re-scores about 15,000 history rows, and the property is that 2025 values are never read
    at all, not a hunt for rare edge cases. This predates D-035, where the owner declined fewer
    property examples in general. It stays as it was and is recorded here.
- **Status:** Active. Recorded from the code, 2026-11-20 (#55).

---

## Open questions (to settle, then move into a D-entry)

- Further open items are listed in [SPEC.md](SPEC.md) § Open Questions.

Closed: Q-6 → D-030 (Phoenix, by the D-006 check). Q-1 → D-020. Q-2, Q-3, Q-5 → D-003.
Q-4 → D-003 and D-011.
