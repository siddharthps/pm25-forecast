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
- **Status:** Active. The variables, the live run's forecast and the lead-time mapping are
  settled in D-051 (2026-11-23).

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
  *Refined 2026-11-21 (D-045):* a reported-only 95% interval and verdict per baseline;
  the metrics and the selection are unchanged.
  *Noted 2026-11-24 (D-052):* the CAMS history is stitched from each run's first 12 hours, so
  the test's CAMS bar is stronger than CAMS was live; the gap is measured and stated, the
  baseline unchanged.
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
  in SSM Parameter Store as a SecureString). *2026-11-20 (T9, D-041):* settled. The Lambda POSTs
  to the deployment's `create_flow_run` with a Bearer user API key read from SSM, and an
  idempotency key per target day. The owner's drill confirms it on Prefect Cloud.

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
- **Status:** Active. *2026-11-20 (T10, D-042):* daily scoring is built. Each day is scored on
  the T+2 morning against settled AirNow data, and its score goes public in `history.json`.

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
- **Status:** Active, refined by D-050 (the 2026-11-25 review, held on 2026-11-23): the dates
  stand, the cut line can move once, at a check-in on 2026-12-12.

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
- **Status:** Active. Re-check Zensical's stable release around 2027-02. *Refined 2026-11-21
  (D-043):* Zensical 0.1.3; its strict build fails on broken links and anchors (the open
  point), and lychee runs offline as the separate checker.

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
- **Status:** Active. T12a's rules and severities: D-033. T12b's: D-054.

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
- **Status:** Active. *Refined 2026-11-21 (D-043):* the bottom line is `docs/index.md`, the
  outline `notes/OUTLINE.md`, the style sheet `notes/STYLE.md`; the caps are 400 and 1,000
  words.

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
  *2026-11-20 (T8, D-040):* settled as **keyless**. Prefect Managed supports AWS web identity
  federation, so the run assumes `pm25-forecast-prefect-run` and no key exists.

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
  *2026-11-20 (T8, D-040):* the pin is in `prefect.yaml` (`image:`), checked by a test against
  `.python-version`.

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
- **Status:** Active, except the CI trigger: D-049 replaces the `GITHUB_TOKEN` and dispatch
  with a GitHub App token (2026-11-23). Revisit if Dependabot's bundled uv reaches our floor and
  we want native updates (a new D-entry). Security alerts for uv still come from the dependency
  graph.

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
  the lists in step with the lock. *Refined 2026-11-24 (D-056):* releases wait 7 days in the job.

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
  hours are treated". *Refined 2026-11-24 (D-054):* AirNow hours are judged against their own
  site's instrument, no longer the widest range.

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
- **Status:** Active. Owner's choice, 2026-11-19. Refined by D-046 (2026-11-22): the suite's
  creep fixed, 4 workers re-measured, and CI's 75 s limit.
  *Refined 2026-11-24 (D-057):* the goal is the median of three quiet runs; tests
  distribute by group.

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

## D-040 · 2026-11-20 · The Prefect daily deployment (T8, #15)

- **AWS access: keyless** (settles D-024). Prefect Cloud is an OIDC identity provider, and a
  managed run can assume an AWS role through `AssumeRoleWithWebIdentity`. Prefect then injects
  temporary credentials ("Federated Identity" on the work pool; Prefect's guide
  `managed-aws-federated-identity`, read 2026-11-20).
  - `infra/prefect.tf` adds the OIDC provider and the role `pm25-forecast-prefect-run`, with
    only the T3b pipeline policy and sessions of up to 1 hour.
  - The trust is `StringEquals` on the `prefect-cloud` audience and `prefect:account:<our
    account ID>`. Prefect's token names the account, not a workspace or deployment, so any run
    in our account could assume the role. The account holds only this project.
- **No secrets in the run at all.** AirNow's hourly files are public, and the AWS credentials
  are injected. The AirNow API key and the AQS email and key are now optional settings:
  `Settings.aqs_credentials()` fails clearly in the two scripts that need them. A Secret block
  was rejected as unneeded. Templating one into `job_variables` was also ruled out, because the
  value would be resolved at deploy time and stored with the deployment.
- **Code and dependencies** (owner's choice: lock-exact):
  - Each run clones `main` from the public repo. Prefect documents no way to pin a commit, and
    `main` changes only through CI-gated PRs.
  - It installs `requirements/prefect-run.txt`, exported from `uv.lock` with hashes, then our
    package with `--no-deps`. A test fails if the file drifts from the lock, and the weekly
    lock job regenerates it in the same commit.
  - The image is pinned to `prefecthq/prefect:3-python3.12` (D-026).
- **Dry run unless scheduled:** the flow defaults to `publish=False`. Only the 06:00
  America/Chicago schedule passes `publish: true` (D-019), so a manual run from the UI or CLI
  writes no record and no public file.
- **Thin flow:** `airwatch.flows.daily` reads the settings and its run ID and scheduled start,
  then calls `airwatch.forecast.job.daily_job`. The job and every rule it relies on are tested
  without Prefect. The flow has no retries, because a failed day is the watchdog's to handle
  (D-011).
- **Compute minutes** (owner's choice: a ledger now, email in T9):
  - Prefect bills from container start-up to teardown, rounded up, and documents no usage API.
  - Each run files its estimate once, under its run ID, in
    `reports/compute/month=YYYY-MM/` (UTC months). The estimate runs from the scheduled start
    to the end of the run, rounded up, plus 1 minute of teardown.
  - The month's total is logged, with a warning above 300 of the free 500 minutes. A dry run is
    counted too, since it uses the same minutes. The ledger is written even when the forecast
    fails.
  - The email at 300 moves to T9, which builds the SNS path anyway. Until then, the estimate is
    checked against Prefect's usage page by hand.
- **Deployments used:** 1 of the Hobby plan's 5 (a test caps `prefect.yaml` at 5).
- **Status:** Active. Owner's choices, 2026-11-20. The first deploy is the owner's
  (`notes/guides/T8-PREFECT.md`, D-023). *2026-11-20 (#63):* runs time out after 30 minutes
  (owner's choice), because the managed pool's default is 24 hours. *2026-11-20, first deploy
  (#15):*
  - Deployment `daily-forecast/daily-forecast` created. The AWS role was applied, and the pool's
    Federated Identity set.
  - Two manual dry runs completed. The second (`rose-ocelot`, `target_day=2026-11-19`) fetched
    AirNow on Prefect's machines and forecast 9 monitors. It wrote a ledger entry and no record
    or public file.
  - The managed pool's default image is `prefecthq/prefect-client:3-latest`, so the D-026 pin is
    what keeps the run on Python 3.12.
  - Two first-run fixes: install our package from inside the clone (#66), and set the `airwatch`
    logger to INFO so its lines reach Prefect (#68).
  - *Correction:* "Prefect documents no way to pin a commit" is wrong. Prefect 3.9.4's
    `git_clone` step accepts `commit_sha`. Runs still clone `main`, because the reason above
    (`main` changes only through CI-gated PRs) still holds.
  - *2026-11-20 (T9, D-041):* the email at 300 minutes is built: the watchdog sends it once a
    month.
  - *2026-11-21, the first scheduled run:* `jade-seahorse`, scheduled for 06:00 Chicago
    (12:00 UTC) with `publish: true`, Completed.
    - It recorded 2026-11-22 for 10 monitors, all with a valid day, then published
      `latest.json` and `history.json` in the same second, after the record.
    - The page shows AQI 54, Moderate. About 3 minutes; 12 of 500 this month.
    - No manual action (Checkpoint B).

---

## D-041 · 2026-11-20 · The watchdog (T9, #16)

- **Shape** (refines D-011): EventBridge Scheduler invokes one Lambda twice a day, in
  America/Chicago time (08:00 and 09:00 exist every day; DST changes happen at 02:00).
  - **08:00, retry:** no record for the target day (D+1, D-034) → start the deployment through
    the Prefect API, with `publish: true`, the explicit `target_day`, and the idempotency key
    `watchdog-<day>`, then email. A repeated call returns the same run (HTTP 200, per Prefect's
    server code). A failed start emails and fails.
  - **09:00, verify** (owner's choice): the record still missing → email. It starts nothing and
    never reads the key.
  - **Drill** (`"drill": true` in a hand-made test event):
    - it uses its own idempotency key, `watchdog-drill-<day>`, so a test never uses up a real
      day's key, and its emails say DRILL;
    - a drill retry must target a day whose 06:00 issue time hasn't come. The run it starts then
      stops as too early, before writing anything, so a drill can't publish.
  - "Done" is the S3 record, checked by listing the exact key (D-011).
  - A late retry is safe: `run_daily` accepts any time after 06:00, uses only AirNow rows
    published by 06:00, and reuses an existing record (D-034).
- **Compute-minutes email** (moved from T8, D-040; owner's choice: once a month): at 08:00 the
  Lambda sums the month's ledger the same way `record_run` does. Over 300 of the free 500, it
  creates `reports/compute-alerts/month=YYYY-MM/over-300.json` only if absent, then emails.
  - The marker sits outside the ledger folder, because `record_run` sums every file in that
    folder.
  - Record first, then email (owner's global rule). If the email then fails, the run fails, and
    the error alarm below emails instead.
- **Fails closed:**
  - every error emails its kind (an AWS error code or an exception type, never the text) and is
    re-raised;
  - a CloudWatch alarm on the Lambda's `Errors` (which counts timeouts) emails through the same
    topic;
  - Lambda's own async retries are off, because a failed check has already emailed; the
    scheduler retries a failed invoke twice, within an hour.
  - Known gap: if the scheduler itself stopped invoking, nothing would email. The page's date
    shows it.
- **Credentials:**
  - Hobby has no service accounts (Prefect's pricing page and service-account docs, read
    2026-11-20). So the key is a dedicated user API key, `pm25-forecast-watchdog`, with an
    expiry date (TOKENS.md).
  - It's a SecureString at `/pm25-forecast/prefect-api-key`, created by the owner outside
    Terraform, so its value is never in Terraform's state. The role may read that one parameter.
    The `aws/ssm` key already lets every principal in the account decrypt (SSM docs), so no KMS
    grant is added.
  - **The SDK's loggers are pinned at WARNING.** At DEBUG, botocore logs response bodies, and a
    test showed the SSM reply's key in them. The Lambda logs at INFO.
- **Least privilege:**
  - the Lambda: list `records/` and `reports/compute/`, read the ledger, create the alert
    marker, read the one parameter, publish to the one topic, write its own logs;
  - the scheduler role: invoke this Lambda only, trusted only for this account;
  - no deletes, no wildcard resources (Terraform tests, with planted bugs caught).
- **Packaging:**
  - `src/airwatch/watchdog/handler.py` imports only the standard library and boto3 (a test
    checks), because `airwatch/__init__.py` needs the installed package's metadata.
  - Its record key, ledger rules and target day are tested equal to the forecast's. The target
    day is checked by a property test across 2026–2040, DST days included.
  - `python -m airwatch.watchdog.build` zips it as `handler.py`, plus boto3 and tzdata from
    `requirements/watchdog.txt` (a `watchdog` dependency group, exported with hashes, checked
    for drift, and regenerated by the weekly lock job). The wheels are for Linux arm64 and
    Python 3.12.
  - AWS recommends shipping the SDK (Lambda runtimes page). AWS doesn't document whether the
    image has time-zone files, so tzdata is bundled.
  - The zip is reproducible: two real builds give the same SHA-256, so `plan` shows no change
    until the code or lock does.
- **Runtime:** `python3.12` on arm64 (D-026), with 128 MB and a 60 s timeout. Deprecation:
  2028-10-31 (Lambda runtimes page, read 2026-11-20).
- **Cost** (AWS pricing pages, read 2026-11-20):
  - Lambda: 1M requests free a month.
  - EventBridge Scheduler: 14M invocations free.
  - SSM standard parameters: free.
  - SNS: 1,000 email notifications free.
  - CloudWatch: 10 alarm metrics and 5 GB of logs free.
  - About 60 invocations a month: $0.
- **Alternatives:**
  - Wait in the Lambda for the retry's record: up to 15 minutes billed, and a false alarm if
    Prefect starts slowly.
  - Email only when the start fails: a retry that starts and then fails would go unnoticed.
  - Email every day over 300: up to about 30 emails a month.
  - Terraform-managed SSM value: the key would sit in state.
  - Rely on the runtime's boto3 and time-zone files: against AWS's advice, and unversioned.
- **Status:** Active. Owner's choices, 2026-11-20. The first plan, apply and drill are the
  owner's (`notes/guides/T9-WATCHDOG.md`, D-023). *2026-11-20, set up and drilled (#16):*
  - Plan: 13 to add; applied. A second plan showed no changes. The email subscription is
    confirmed.
  - Four drill invokes, all as designed:
    - verify for 11-21 (record present): no email;
    - verify for 11-22 (missing): the DRILL email;
    - retry for 11-22: one Prefect run, `fragrant-turaco` (`publish: true`, key
      `watchdog-drill-2026-11-22`). It failed with `TooEarlyError` and wrote only a ledger
      entry (3 min);
    - the same retry again: `already started` and still one run. That confirms on Prefect
      Cloud the idempotency behaviour read in the server code.
  - The watchdog's logs: 4 INFO lines, with no key-shaped string and no `Bearer`.
  - The zip no longer carries uv's empty `.lock` file (#73). That changes the zip's hash
    once, so the next plan updates the Lambda's code.
  - *2026-11-21, the first real checks failed* (08:00 and 09:00, both emailed, and the
    error alarm fired; nothing else was affected, and the forecast was recorded at 06:01):
    - **The cause:** `jsonencode` in `infra/watchdog.tf` wrote the placeholder's `<` and
      `>` as `\u003c` and `\u003e`. The scheduler substitutes only the literal
      `<aws.scheduler.scheduled-time>`, so the Lambda got the placeholder itself.
    - **Why the checks missed it:** the Terraform test compared the input after
      `jsondecode`, which turns the escapes back into `<` and `>`. The drill invoked the
      Lambda directly, so it never went through the scheduler.
    - **The fix:** the input is plain text. A Terraform test now checks the raw string for
      the literal placeholder (it failed on the old code), and the guide reads each
      schedule's stored input after apply. The error email now names the value it got
      (at most 60 characters; it holds no secret).
    - *Applied 2026-11-21 (0 added, 3 changed)*. Both stored inputs read back with literal
      `<` and `>`. A one-time schedule (13:45 Chicago, deleted after completion) then ran a
      drill verify through the real scheduler. It logged `target_day 2026-11-22, record
      present` (so a real time was substituted), sent no email, and deleted itself. The
      guide now has this test as step 7b.

---

## D-042 · 2026-11-20 · Daily scoring (T10, #17)

- **When** (owner's choice): day T is scored by the run on the **morning of T+2** (from 06:00
  Chicago), from a **fresh download** of all of T's AirNow hours.
  - AirNow rewrites each hourly file for about 7.7 hours (D-034). At 06:00 on T+1, T's last hours
    aren't final, and the forecast's strict cut drops them (20 Nov's record used 22 of 24 hours).
  - By the T+2 morning every file for T has settled, so the score is complete, final for AirNow,
    and the same whenever the run happens (a watchdog retry gives the same answer).
  - `score_day` refuses a day before that moment.
- **Actual:** each monitor's mean over the local day with the forecast's own rule. The new
  `day_means` in `forecast/run.py` is now the one home of the 18-hour rule for forecast and score.
  The same validation runs first. A hard failure leaves the day unscored, for a later run.
- **Score:**
  - per monitor: forecast minus actual (positive means the forecast was too high), and its
    absolute value;
  - for the city: the mean absolute error (MAE) and the mean error (bias) over the scored
    monitors, from unrounded values;
  - a forecast monitor without a valid actual is left out of both and listed in `no_actual`, with
    its hours. A day with no valid actual at all is still a final score, with a null MAE.
- **Once per day:** create-only at `reports/scores/forecast_date=<T>/score.json` (inside the
  pipeline policy's `reports/`, so no IAM change), then reused. A racing writer's score wins. A dry
  run computes and writes nothing.
- **Catching up:** each run looks back 7 days, so a day missed by a failed run is scored later. A
  failing day doesn't stop the others; the failures are raised together at the end.
- **In the job:** scoring runs after the forecast is recorded and published, so it can never stop
  or undo that morning's forecast. `history.json` is rebuilt afterwards, even if a day failed, so
  the scored days still appear. A scoring failure fails the Prefect run; the watchdog stays quiet,
  because the record exists. The email for it comes with the flags (T24).
- **Public** (owner's choice: now, in `history.json`; D-012 already lists "recent actuals,
  scores"):
  - a scored day gains `score`: each monitor's actual (truncated to 1 decimal like the forecast,
    with its AQI and category) and error (2 decimals); the city's MAE and bias (2 decimals);
    `n_scored`; and the `no_actual` site IDs;
  - the history schema lists every field, so nothing extra can go public. The field is optional,
    so the page and `version` 2 are unchanged. The page draws it in T25;
  - errors come from the unrounded values, so a published error can differ by 0.1 from the
    published forecast minus the published actual.
- **Preliminary:** live scores are against AirNow. The AQS re-score follows (T26, D-004).
- **Checks:**
  - 534 Python tests, including 16 for scoring, the history and schema tests, and four
    integration runs on moto, with the forecast recorded on one morning and scored two days
    later;
  - 18 planted bugs caught (sign, MAE without abs, a day early, overwrite, dry-run write, the
    18-hour rule, the lookback, history not republished, and others).
- **Alternatives (rejected by the owner):** score on T+1 with the 06:00 view (usually 22 of 24
  hours); score on T+1 with the files at run time (the answer depends on the time of the run);
  keep the scores private until T25.
- **Status:** Active. Owner's choices, 2026-11-20. First real score: the 2026-11-22 run scores
  2026-11-20.

---

## D-043 · 2026-11-21 · The write-up's setup (T11, #18)

- **Docs tool:** Zensical **0.1.3** (PyPI, 2026-11-20), pinned with `==` in a separate `docs`
  dependency group, so the daily job's and the watchdog's requirements stay unchanged (D-040,
  D-041). Config in `zensical.toml`: `docs_dir = "docs"`, `site_dir = "site_build"` (the page's
  source owns `site/`), `strict = true`.
- **Numbers:** `results/results.json` is the one source. `airwatch.docs_macros` loads it as
  `results` through Zensical's native macros (`modules = ["airwatch.docs_macros"]`,
  `on_undefined = "strict"`, `on_error_fail = true`). A null shows as *(pending)*, with no
  filter needed, because a filter's `|` breaks a table row. The file holds the design counts
  from the frozen decisions (variants, baselines, folds) and nulls for every result. Writing it
  from the pipeline is a separate task.
- **Number check** (`airwatch.devtools.docs_check`, a pre-commit hook and a core test): any digit
  in `docs/` outside a macro's `results.…` path fails, code blocks, HTML comments and the rest of
  each macro included (so `{{ 4.2 }}` fails; found in the PR #84 review). Allowed literals: ISO
  dates, years 1900–2099, clock times (`06:00`, added when the first page needed the issue
  time), decision and task IDs, issue numbers, `PM2.5`, `PM10`, `D+1`, versions with a `v`,
  ordered-list markers, link targets. A macro naming a missing key fails too.
- **Length cap:** 400 words for the bottom line, 1,000 for any other page.
- **Vale 3.28.1** as a pre-commit hook (the upstream golang hook, pinned to the tag's commit), over
  `docs/`, the README and DEVELOPMENT.md. One project style, `styles/AirWatch/Banned.yml`, at
  `error` level. CI runs it in the pre-commit step.
- **Links:** Zensical's strict build already fails on broken links and anchors (checked
  2026-11-21 with a planted broken anchor), which settles D-016's open point. The separate checker
  D-016 asks for is **lychee 0.24.2** through `lycheeverse/lychee-action` 2.9.0, **offline**
  (`--offline --include-fragments`) over `site_build/` in a new CI `docs` job, so an outside site
  being slow can't fail a PR.
- **Dev commands:** one home, `DEVELOPMENT.md` at the root (owner's choice), linked from the
  README and imported by `CLAUDE.md` with `@DEVELOPMENT.md`. Not in `docs/`, so it isn't
  published or number-checked.
- **Scoped, not loosened (D-029):** two discovery tests (the comment ban's folder scope, Biome's
  file scope) walk the disk and found Zensical's bundled theme JS and CSS in the gitignored
  `site_build/`. That is generated output we don't own, so both skip exactly that folder. A test
  ties the skipped name to `site_dir`, so it can't drift.
- **Alternatives:**
  - Zensical in the `dev` group: rejected, since the docs build isn't needed for the core suite.
  - Vale in CI only, from a downloaded binary: rejected, because the hook gives the same version
    locally.
  - lychee checking outside links on every PR: rejected because it would be flaky. An outside-link
    check can come later as its own scheduled job.
- **Status:** Active. 2026-11-21. Refines D-016 (tool and versions; its open point settled) and
  D-022 (how its checks run).

---

## D-044 · 2026-11-21 · The write-up's plan: pages, readers, charts, live record, publishing (#18)

Settled with the owner one question at a time, before any result was seen. The plan itself lives
in `notes/OUTLINE.md`, the writing rules in `notes/STYLE.md`.

- **Live numbers are a dated snapshot,** taken at the end of T29's 14-day window and quoted "as
  of" that date, with a link to the live page for today's numbers. *Why:* the prose is written
  once; a live number that keeps updating would move under it.
- **Counts written as words are banned in `docs/`** ("two" to "twelve"; Vale, error level). "One"
  stays allowed. *Why:* "six variants" dodged the digit check.
- **Four charts, declared now:** models against the baselines, error by month, the live forecast
  against what happened, and bad-air recall. Each is drawn **at build time** from a data file the
  pipeline writes into `results/`, and the images are never committed. *Why:* a chart saved by
  hand goes stale like a typed number, and declaring the charts before the results stops us from
  choosing only the flattering ones.
- **Seven pages:** a separate "How it runs" page for the engineering (record before publish, one
  record a day, the watchdog and its drill, tests, cost). *Why:* it is a main point for
  interviewers and was squeezed into half a page.
- **Two levels of reader:** the bottom line and the README in plain words for anyone; the
  chapters for a technical reader, with each term defined at first use.
- **Published at `/report/`** on the existing GitHub Pages site, by the same deploy. Built and
  dry-run early but switched off until T28's write-up is in, and switched on only at the owner's
  go. *Why:* the docs need a built site (raw Markdown shows the macros), and a half-empty
  report shouldn't be anyone's first impression.
- **The live record is compared with all three baselines,** so the daily job saves CAMS's D+1
  forecast each morning as issued. *Why:* SPEC criterion 4 asks for all three, and a CAMS
  forecast downloaded later may have been revised, which would be an unfair comparison. This is
  the one time-sensitive item: every day not saved is a day without a CAMS comparison.
- **The live record is split by forecaster:** the headline model is scored only on the days it
  issued (each record's `method`); the persistence launch period is shown apart. *Why:* pooling
  would mix persistence's days into the model's score.
- **The bottom line shows all three baselines,** not only persistence (SPEC criterion 4).
- **Alternatives (each offered, not chosen):** live numbers always current; number words left to
  review or warned only; charts saved by the pipeline or drawn in the browser; one live page for
  both topics; one reader level throughout; a separate docs host; publishing the skeleton now or
  page by page; live compared with persistence and climatology only; pooling the live days.
- **Status:** Active. Owner's choices, 2026-11-21. The build work is in its own issues.

---

## D-045 · 2026-11-21 · How sure the result is: intervals and verdicts, reported only

- **Decision:** each comparison with a baseline, on the 2025 test year and on the live snapshot,
  reports the MAE gap (baseline MAE minus model MAE; positive means the model is better) with a
  **95% interval** from a **circular block bootstrap**:
  - blocks of 7 consecutive days, with every monitor on a resampled day kept together (nearby
    days and monitors share the same air);
  - 10,000 resamples, a fixed seed, and the percentile interval.
- **Verdict, fixed before any result:**
  - `better` if the whole interval is above zero;
  - `worse` if it is wholly below zero;
  - `no clear difference` otherwise.
  The pipeline writes the verdict into `results.json`, and the write-up quotes it. If the
  interval includes zero, the page says "no clear difference", whatever the point estimate.
- **Reported only:** the intervals and verdicts never affect model choice. D-010's selection
  rule, D-009's metrics and the one-time test read (D-008) are unchanged. The test-year
  intervals are computed in the same single run that reads the test set (T27), never by a
  second read.
- **Why:** with one test year, a gap of a fraction of a µg/m³ could be luck. The interval shows
  that, and a wording rule fixed in advance stops the prose from being softened after the result
  is known.
- **Note:** the live snapshot covers only a few weeks, so its intervals will be wide. That is
  reported as it is, not worked around.
- **Wording:** the owner chose "say 'not clearly better'". Vale bans "clearly", so the label is
  "no clear difference", with the same meaning. A third label, `worse`, covers an interval wholly
  below zero.
- **Alternatives:** no interval, with the limits page saying the comparison has no error bars
  (offered, not chosen); report the range with no wording rule (offered, not chosen).
- **Status:** Active. **Frozen.** Owner's choice, 2026-11-21, before any result was seen. Adds to
  D-009 without changing it.

---

## D-046 · 2026-11-22 · The core suite's speed: what was cut, and CI's 75 s limit (#83)

- **Found:** the core suite had crept to 29–31 s wall on the owner's PC (about 25 s as pytest
  reports it), at D-035's 30 s line. Measured, not guessed:
  - the lint, Biome and comment-ban scope tests walked all of `.venv` (39,478 files) before
    dropping it, about 2 s per scan, five scans a run;
  - each of the 4 workers imported Prefect (about 2 s) just to collect two flow test files.
  - The rest is spread across pandas inside the property tests, as D-035 found; no hotspot.
- **Fixed, same tests and the same Hypothesis examples:** the scans skip ignored top-level
  folders before entering them (`tests/project_files.py`; old and new results diffed, identical),
  and the flow module comes through a `daily` fixture, with a static test keeping Prefect out of
  test files' top-level imports. Collection went from 4.3 s to 2.2 s. Paired runs against `main`
  saved about 4.7 s; wall time on the owner's PC is now about 26–28 s.
- **Worker count re-measured:** 6 workers were no better than 4 within the noise (26–28 s
  each); D-035's 4 stands.
- **The limit:** CI fails the core test step when it runs over **75 s** (`SUITE_BUDGET_S`, read
  by the plugin in `tests/suite_budget.py`; timing starts before collection). The same commit
  took 26–52 s on CI's shared runners, with coverage, so a 30 s limit there would fail at
  random. 75 s is about 1.45 times the slowest run seen: it catches real creep, such as a heavy
  import or a slow new test, without flaking. A bad value is a usage error, so a typo can't
  switch the check off. Unset, as on the owner's PC, nothing is timed.
- **The 30 s goal stays** (SPEC § Testing), measured by hand on the owner's PC.
- **Alternatives:** a 30 s limit on full local runs (it would fail now and then on a busy PC);
  both limits; report the time without failing (all offered, not chosen). Fewer property
  examples stays rejected (D-035).
- **Status:** Active. Owner's choice, 2026-11-22 (the CI limit). Refines D-035.
  *Refined 2026-11-24 (D-057):* the goal is the median of three quiet runs; tests
  distribute by group.

---

## D-047 · 2026-11-22 · AirNow's missing instrument number is -1, a named marker (#57)

- **The problem:** every hourly row has a `poc`, the number AQS gives each instrument at a site
  (a non-null `int16`). AirNow gives none, and the parser wrote a bare `0`. Code that groups,
  joins or deduplicates by `(site_id, poc)` had to know that 0 meant "unknown". EPA's formats
  describe the POC as a one- or two-digit number, so 0 could be a real instrument.
- **Decision:** AirNow rows carry `POC_NOT_GIVEN = -1` (`airwatch.observations.schema`), outside
  the 0–99 range, so it can't be read as a real instrument. `validate_hourly` enforces it as
  structure: AirNow rows must carry the marker, and AQS rows must be in 0–99.
- **Checked against real data:** the project's AQS history before 2025 (160 site-years,
  1,080,807 rows) has only POC 3; a live AirNow day passes the new rule.
- **Earlier outputs:** forecast records hold only counts per rule, so none differs. The private
  validation reports list example rows with their POC: AirNow examples read 0 up to the
  2026-11-23 report and -1 after it.
- **Alternatives:** keep 0 and name it (least change, but 0 is a legal POC); a nullable `Int16`
  with `pd.NA` (pandas drops missing keys when grouping by default and can't compare them with
  `==`, so the duplicate, flat-line and instrument checks would each need changing, and AirNow
  rows could quietly drop out of a check). Both offered, not chosen.
- **Status:** Active. Owner's choice, 2026-11-22.

---

## D-048 · 2026-11-22 · Mutation testing: mutmut 3, on demand in CI or WSL, never blocking (#42)

- **Tool:** mutmut 3.8.1 (PyPI, 2026-10-28), a dev dependency. It needs `fork`, so it runs on
  Linux only: GitHub's runners, or WSL on the owner's PC.
- **Where (owner's choice):** a hand-started GitHub job (`.github/workflows/mutmut.yml`,
  dispatch only) that lists the survivors in its summary, and the same command in WSL
  (DEVELOPMENT.md). Run after changing a mutated module, before its merge. It never blocks a
  merge, since a survivor needs a judgement: killed by a new test, or explained in the journal.
- **Why both:** they run in different zones. WSL runs on Chicago time, CI on UTC. The first run
  found two `issue_time_utc` mutants that passed only because WSL's zone equals the issue zone;
  tests now move the process zone (POSIX only).
- **Scope:** `src/airwatch/timeutil.py` and `src/airwatch/config.py` (`[tool.mutmut]`); T15
  extends `only_mutate` with `features/`, `forecast/record.py` and `training/split.py`.
- **The copy:** mutmut tests a copy of the repo, so `also_copy` lists every tracked top-level
  entry (a test keeps that list complete). Two repository checks are deselected inside the
  copy only, because they check the repo itself and the copy's `src/` is mutmut's generated
  code: the comment-ban baseline, and the `also_copy` test (the copy has no git). Both still
  run in the normal suite. This scopes checks away from generated files, as D-029 allows.
- **First run (2026-11-22, WSL, 12 CPUs):** 65 mutants, 2 min 3 s; 51 killed, 14 survived.
  Three were real gaps, now killed (the two above, and a `tzinfo` whose offset is `None`). The
  other 11 change only an error message's text, which the tests deliberately don't pin. After
  the new tests: 54 killed, 11 survived, 1 min 50 s.
- **Alternatives:** a weekly scheduled run as well (a job to watch, and GitHub's cron can be
  late or dropped); WSL only (depends on remembering, and tests only Chicago time). Both
  offered, not chosen.
- **Status:** Active. Owner's choice, 2026-11-22.

---

## D-049 · 2026-11-23 · The lock PR is opened with a GitHub App token (#115, refines D-027)

- **Decision:** `uv-lock-upgrade.yml` pushes the branch and opens or edits its PR with a
  short-lived installation token from a private GitHub App, minted by
  `actions/create-github-app-token` (v3.3.0, pinned by SHA). The job's `GITHUB_TOKEN` is
  read-only. The CI dispatch step is deleted. Commits are the App's bot user's
  (`<slug>[bot]`, noreply email `<user id>+<slug>[bot]@…`, the id looked up through the API).
- **Why:** D-027's dispatch didn't make the PR mergeable. Seen on 2026-11-23 with #114:
  - The PR's own `pull_request` run was held at `action_required` until a person approved it.
  - The dispatched CI passed on the same commit, but the `main` ruleset didn't count it: the
    merge API answered "4 of 4 required status checks are expected".
- **Facts (read 2026-11-23):**
  - GitHub's "Triggering a workflow" page: events from `GITHUB_TOKEN` create no new runs,
    except `workflow_dispatch` and `repository_dispatch`. A PR it opens or updates creates
    `pull_request` runs "in an approval-required state". A GitHub App installation token or a
    PAT "lets `pull_request` workflows run automatically".
  - An installation token expires after 1 hour (GitHub's installation-token page), and the
    action revokes it in its post step unless `skip-token-revoke` is set (its README).
  - The README's own recipe sets git's user to the App's bot user, as above.
  - The action takes `client-id`; `app-id` is deprecated. v3.4.0 (2026-11-18) was inside the
    7-day cooldown that Dependabot keeps for actions, so v3.3.0 (2026-10-12) is pinned.
- **The App:** private ("Only on this account"), installed on this repo only, webhook off,
  repository permissions Contents and Pull requests read and write (Metadata read is
  automatic). The workflow asks for only those two. Client ID in the repo variable
  `LOCK_APP_CLIENT_ID`, private key in the repo secret `LOCK_APP_PRIVATE_KEY` (TOKENS.md).
  Once it works, the repo setting "Allow GitHub Actions to create and approve pull requests"
  that D-027 needed can be turned off.
- **Alternatives:**
  - Keep `GITHUB_TOKEN`, drop the dispatch, and approve the PR's run by hand each week: no new
    credential, but a weekly click before the PR has any counted checks.
  - A fine-grained PAT: the PR and pushes are the owner's, and it expires (at most a year).
  - D-027 rejected both an App and a PAT as extra credentials; that was before the dispatch
    was seen not to count.
- **For #113:** the watchdog needs a GitHub credential to start this workflow. If the same App
  can serve (the Lambda minting a token from the key in SSM), #113 uses it: one key to rotate.
- **Status:** Active. Owner's choice, 2026-11-23.

---

## D-050 · 2026-11-23 · Timeline review: dates kept, one check-in on 12-12 (#120, refines D-014)

- **Decision:** the review D-014 set for 2026-11-25, held two days early with the owner. All
  dates America/Chicago.
  - **Dates kept:** cut line **Wed 2026-12-16**, research freeze **Wed 2026-12-23**. The owner's
    time stays as planned, about 30 h from 11-26 to 12-16.
  - **One check-in, Sat 2026-12-12:** keep the cut line or move it later, once.
    - Decided only by what is done, what is left and the owner's free time, never by any
      model's scores.
    - Any move is written as a new D-entry that day, before any test result is seen.
    - The freeze moves by the same number of days, so the test-and-write-up week stays a full
      week.
    - At most one week: cut line no later than 2026-12-23, freeze no later than 2026-12-30.
  - **Cut order unchanged:** the TCN, then the per-monitor map, then AQS re-scoring.
  - **Work added since the plan:**
    - Required, planned in like any task: #78 (the CAMS forecast saved daily), #79–#82 (the
      write-up's build work) and #112 (mutation tests on the must-never rules).
    - Fill-in, done in gaps (such as a long model search) or after the freeze, which allows
      fixes: #113, #86, #87.
    - None of it goes on the cut list.
  - **The 14-day live check (T29) counts from the headline model going live (T23).** Days
    forecast by persistence alone don't count. SPEC success criterion 1 says so.
  - **Soft waypoints** (signals for the check-in, not deadlines; missing one changes nothing by
    itself):
    - **Sun 11-29:** weather data in (T14); the CAMS forecast saved daily (#78).
    - **Sat 12-05:** T12b, T15, T16 (with the 3 baselines), T17.
    - **Sat 12-12 (check-in):** T18–T20, T22, #79, #81.
    - **Wed 12-16 (cut line):** T21, T23, T24, T25, T26, #80, #82, #112.
- **Why:**
  - The skeleton was live on 2026-11-22, three days early: 14 tasks (10 medium, 4 small) in
    about 4 days, then two days of test hardening.
  - What is left before the cut line is about twice that, and the model work is the least
    predictable part (full searches up to 6 h each), so the buffer is kept rather than spent.
  - The owner is unsure of their free time near mid-December, hence a cut line that can move.
    A single fixed check-in, bounded to one week, keeps the move a calendar decision (D-014's
    rule) rather than one that slides a day at a time.
  - Moving the freeze with the cut line protects the delivery week: in the last project the
    delivery path's bugs surfaced three days before the deadline.
  - Counting the live check from T23 proves the published model runs daily, which is what T29's
    dependency on T23 means.
- **Alternatives:**
  - More owner hours (45 h or more), first chosen and then withdrawn by the owner: 30 h stands.
  - A check-in on Wed 12-09 (the agent's suggestion), any time up to 12-16, or two check-ins
    (12-02 and 12-09); the owner chose Sat 12-12.
  - A fixed freeze while the cut line moves; a move of up to two weeks, or no limit.
  - Counting persistence days toward the live check (already passing, but it proves the
    pipeline rather than the published model), or starting it after the freeze (over the
    holidays, when a failure is slower to notice).
- **Facts:** clock checked 2026-11-23 19:38 CST (2026-11-24 01:38 UTC). No test-period result
  has been read (D-008). Thanksgiving is Thu 11-26, the first day of the deepening phase.
- **Status:** Active. Owner's choices, 2026-11-23. Next review: the 2026-12-12 check-in.

---

## D-051 · 2026-11-23 · Weather: GFS Global, 8 variables, the 72-hour rule (#19, refines D-007)

- **Decision:**
  - **Training weather:** Open-Meteo's Historical Weather API with `models=era5`, fixed. Not
    "best match", which mixes in ECMWF IFS from 2017; not ERA5-Land, which lacks most variables.
  - **Forecast weather (the test rebuild, the forecasts-only variant and live):** one model,
    `models=gfs_global` (NOAA GFS Global), in the Previous Runs API and the Forecast API alike.
  - **Variables (8, hourly):** `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`,
    `wind_direction_10m`, `precipitation`, `surface_pressure`, `cloud_cover`,
    `shortwave_radiation`.
    - Dew point is left out: it is computed from temperature and humidity, so it duplicates them.
    - Boundary-layer height is left out: it is in ERA5, but the forecast archive has none.
  - **Where:** each monitor's own coordinates (10 points). Points in the same grid cell repeat
    the same values.
  - **Lead rule (replaces SPEC's 24/48 h split):** the test rebuild and the forecasts-only
    variant take `_previous_day3` for every hour of D+1: the last GFS run started at or before
    72 h ahead of that hour. The live run takes the newest run published before it starts, and
    records that run's start time (the metadata's `last_run_initialisation_time`).
- **Why the lead rule changed:** the leakage rule is "only what was published before the issue
  time"; the archive instead offers fixed offsets counted back from each *valid* hour. The
  target day is a Phoenix day (UTC−7 all year), 07:00 UTC on D+1 to 07:00 UTC on D+2, and the
  issue time is 12:00 UTC in winter and 11:00 UTC in summer.
  - `_previous_day1` (SPEC's rule for the first 24 h) always lands on runs started at or after
    06 UTC on day D, 5–6 h or less before the issue time, so it leaks or nearly leaks for every
    hour it covers. GFS appears 5.35–6.29 h after it starts (the readings below).
  - `_previous_day2`, every hour (this entry's first draft, from a Chicago-day reckoning): the
    last hour or two (06:00 UTC, and 07:00 UTC for end-stamped sums like precipitation) land on
    the 06 UTC run of day D. In summer it starts 5 h before the issue time and appears after
    it; in winter it starts 6 h before and may appear minutes before it. A leak or a near miss
    either way.
  - `_previous_day3`: the newest run any hour can use is the 06 UTC run of D−1, published about
    a day before the issue time. Safe whatever GFS's delay, up to about 29 h.
  - The cost is small: at Phoenix, February–December 2024 (the development period; 8,040 hours,
    against ERA5), GFS's mean absolute error grew from 2 to 3 days ahead by about 1–4%
    (temperature 2.64 → 2.69 °C, wind 4.48 → 4.51 km/h, humidity 8.75 → 9.11%). Live's
    forecasts are made 31–55 h ahead, so the test errs pessimistic, never flattering.
- **Facts (checked 2026-11-23 to 11-24 UTC, Phoenix, 33.45 N 112.07 W):**
  - Open-Meteo docs: `_previous_day1` is "the value predicted 24 hours before valid time",
    `_previous_day2` 48 hours. "Most models are archived from January 2024." There is no
    previous-runs archive for the Air Quality API (CAMS).
  - **Real archive starts:** GFS Global, all 8 variables, 2024-01-20 12:00 UTC at
    `_previous_day2`, and 2024-01-21 12:00 UTC at `_previous_day3` (the bulk download,
    2026-11-24: the first 36 hours from 2024-01-20 are empty at every site); ECMWF IFS 0.25°
    2024-02-05, and its `shortwave_radiation` only from 2024-03-07. No gaps after the start,
    through 2025-12-31. The `gfs025` model name returns nothing; `gfs_global` is the name.
  - **The offset rounds down:** matching `_previous_day2` for 2026-11-22 against named runs
    (Single Runs API, `&run=`) found, for the hours one run alone matched, the last run started
    at or before 48 h earlier. At 10:00 and 16:00 UTC it was the earlier run, not the nearest.
    The Single Runs API had no GFS run from 2024 or 2025 (four dates tried), so the offset
    archive is the only record of past forecasts.
  - **Publication delay (metadata API, `/data/<model>/static/meta.json`):** `gfs_global` is
    served from `ncep_gfs013` (the model the Single Runs API names in its error for
    `gfs_global`). Its 18 UTC run of 2026-11-23 was available 5.35 h after it started;
    `ncep_gfs025`'s same run took 6.29 h (one reading each). CAMS global: 2 runs a day, the
    12 UTC run available 9.92 h after it started.
  - ERA5 from 2009 has all 8 variables plus boundary-layer height; ERA5-Land lacks 7 of them.
  - The 10 monitors fall in about 5 cells of a 0.25° grid. The two Pinal County monitors are
    about 60 km south of central Phoenix.
  - Terms: non-commercial use under 10,000 calls a day, 5,000 an hour, 600 a minute, 300,000 a
    month; CC BY 4.0; CAMS attribution required on the air-quality data.
- **Alternatives:**
  - ECMWF IFS 0.25°: about 6 weeks less complete history. Best match: its model mix shifts by
    place and lead.
  - SPEC's 24/48 h split, and `_previous_day2` for every hour: both leak (above).
  - `_previous_day2` with a `_previous_day3` fallback for the last hours: also safe and a little
    closer to live, but a two-case rule that leans on GFS's delay staying under about 11 h. The
    owner chose the one-offset rule for simplicity.
  - Moving the issue time (e.g. to 07:00 Phoenix, 14:00 UTC all year) would let
    `_previous_day2` work with about 1 h 40 min to 2 h 40 min of margin. Not taken: D-019 is
    Frozen, and the gain is the 1–4% above.
  - Dew point kept: a duplicate feature. One city-centre point: weather 60 km off for two
    monitors.
  - The models were not compared on accuracy: that would mean choosing by results.
- **Checks:** one property test of the lead rule: on every target day 2009–2030, in both
  seasons, every hour of the Phoenix day (and the end-stamped hour after it) uses a run published
  before the issue time, given a generous delay. The live job's recorded run start times show the
  margin holds in practice.
- **Status:** Active. Owner's choices, 2026-11-23.

---

## D-052 · 2026-11-24 · CAMS: the history is stitched; "as issued" is the issue day's 00 UTC run (#19)

- **Decision:**
  - **The archive is stitched** (the #19 check). Open-Meteo's CAMS global history takes each
    hour from the first 12 hours of a run, so on paper CAMS forecasts 0–11 h ahead. A real
    day-ahead CAMS forecast at our issue time is 31–54 h ahead.
  - **The test year's CAMS baseline uses the stitched history.** No as-issued CAMS forecast from
    2025 survives, and D-009 (Frozen) keeps CAMS as a baseline. The write-up says this bar is
    stronger than CAMS really was live, and gives the measured gap below. CAMS's score is never
    adjusted by the gap.
  - **"As issued"** (the gap check below, and the live save, #78) means the CAMS global run that
    started at **00 UTC on the issue day** D: the newest run on a normal morning (owner's choice,
    2026-11-24). A later run is never used. The live save records the run it really got, so the
    premise is checked as days accrue.
  - **Daily mean:** CAMS `pm2_5` is an instant value per hour. A monitor's daily mean is the
    mean of the 24 hourly stamps in the local day's half-open window (`city_tz`, the same day
    as our target, D-005), and all 24 must be present; a day with any gap has no CAMS value and
    is listed.
  - **The gap, declared before any number is seen:** over target days from 2026-04-03 (the
    first whose as-issued run, 2026-04-02 00 UTC, is kept) to the day the check runs, each
    monitor-day with an as-issued mean, a stitched mean and a valid observed mean (AirNow,
    ≥ 18 hours): the MAE of each against the observed mean, their difference, and the mean
    absolute difference between the two CAMS means; skipped monitor-days are counted by reason.
    Descriptive only: never used to choose, tune or correct anything.
- **Why the 00 UTC run:** at the issue time (12:00 UTC in winter, 11:00 UTC in summer) it has
  been out about 2.2 h in winter and 1.2 h in summer on the readings below. The day before's
  12 UTC run is always out but 12 h staler, and would make CAMS look worse than it is live,
  flattering our model. If the 00 UTC run is ever late, this choice understates the gap, which
  errs against us.
- **Facts (checked 2026-11-24 UTC, central Phoenix and the 10 monitors):**
  - Docs (open-meteo.com/en/docs/air-quality-api): CAMS global, 0.4°, 3-hourly, 5-day forecasts,
    "August 2022 onwards", updated every 12 hours; `pm2_5` is instant, in µg/m³ (the response
    spells the unit with a Greek mu, `μg/m³`). The docs don't say how past data is built.
  - **Stitched:** 12 runs (00 and 12 UTC, 2026-11-01 to 11-21) against the history: equal at
    every lead 0–11 h in 12 of 12, and at leads 12–23 h in 0–2 of 12; differences at 24–45 h
    reached 20 µg/m³.
  - **No offset archive:** `pm2_5_previous_day1` to `_day3` are empty on every date tried
    (2022–2026), in the Air Quality and Previous Runs APIs alike. The Previous Runs API's plain
    `pm2_5` equals the history exactly.
  - **Single runs** (Single Runs API, `models=cams_global`, `&run=`): from the 00 UTC run of
    2026-04-02 (none on 2026-04-01 or earlier), 121 hours each. Missing to 2026-11-23: the 12 UTC
    runs of 05-10, 05-12, 06-24, 06-28, 08-27 and the 00 UTC run of 06-25. A missing run inside
    that span answers with every value empty; one before it, with an error naming the model
    `cams_global_greenhouse_gases`. The values are still CAMS global's: leads 0–11 h equal the
    `cams_global` history exactly (above).
  - **History:** from 2022-08-04 00:00 UTC (the 3 days before it are empty), no gaps to
    2026-11-23 at any monitor. The 10 monitors fall in 7 grid cells.
  - **Publication delay** (`/data/cams_global/static/meta.json`): the 00 UTC run of 2026-11-24
    appeared 9.80 h after it started; the 12 UTC run of 2026-11-23, 9.92 h (D-051).
  - Terms: the attribution to the CAMS ENSEMBLE data provider and to Open-Meteo is required. The
    docs say nothing about showing the values publicly; #78 settles that.
- **Alternatives:**
  - The day before's 12 UTC run: always out in time, but staler than live (above).
  - Both runs, one as a sensitivity: more to build and explain, for a descriptive figure.
  - CAMS scored only on the live record: D-009 is Frozen and lists CAMS on the test.
- **Status:** Active. Owner's choice, 2026-11-24. The live save: D-053.

---

## D-053 · 2026-11-24 · The daily CAMS save: as issued, beside the forecast record (#78)

- **Decision:**
  - **What:** each scheduled run saves CAMS global's PM2.5 forecast for the target day at every
    monitor (its own coordinates): the run Open-Meteo's Air Quality API serves at that moment,
    named by the API's metadata read before and after the data, as for live GFS (D-051). A run
    that changed in between is refused.
  - **Which run:** the as-issued run is 00 UTC on the issue day (D-052). A run started later is
    refused (`run_after_as_issued`), never saved as issued. An older run (the 00 UTC run not yet
    out) is saved with its own start: what was really there.
  - **Where:** `records/forecast_date=<target>/cams.json` in the private bucket, create-only,
    beside `forecast.json`. `records/` keeps every version; `raw/` expires old ones, and an
    as-issued forecast can't be fetched again from the live API.
  - **Holds:** per monitor, the 24 hourly values of the target's local day, the hours present
    and the daily mean (D-052's rule: all 24, else none); the run's start and publication time;
    the issue time and whether the run was published before it; the fetch time (all UTC, with
    zone); the source and model.
  - **When and how it fails:** after the forecast is recorded and published, and after scoring
    and `history.json`, so a failure can't stop or undo either. A failure is logged by type and
    fails the run, as scoring does (D-042). A second run the same morning finds the file and
    fetches nothing. A dry run fetches and builds but writes nothing.
- **Public display: allowed, with notices.** Open-Meteo's data is CC BY 4.0: credit, a link to
  the licence, changes indicated, and a link to Open-Meteo where the data is shown. The
  Copernicus licence (v1.2, Nov 2019) allows any lawful use, including "communication to the
  public" and "adaptation" (4.2). A page showing these values (a later task, D-044) carries
  "Contains modified Copernicus Atmosphere Monitoring Service information <year>", says that
  neither the European Commission nor ECMWF is responsible for any use of it (5.1.2, 5.1.3), and
  credits Open-Meteo. Until then the values stay in the private bucket, and test fixtures keep
  synthetic values.
- **Why:** persistence and climatology can be recomputed later; CAMS as issued can't from the
  live API. The Single Runs API keeps runs too (D-052), but its timing is unrecorded, and the
  live API is what a forecaster would have read.
- **Facts (checked 2026-11-24 about 13:10 UTC, central Phoenix):** the live API's values for
  2026-11-25/26 equal the 00 UTC run of 2026-11-24 from the Single Runs API in 48 of 48 hours;
  the metadata named that run before and after the fetch (published 09:48 UTC). The next run
  (12 UTC) appears about 22 UTC, so a run at the 06:00 Chicago issue time normally gets the
  as-issued run. Terms: open-meteo.com/en/licence and /en/terms (free API non-commercial: private
  or non-profit sites without subscriptions or ads), apps.ecmwf.int/datasets/licences/copernicus/.
- **Alternatives:**
  - The Single Runs API: the same values, an unrecorded delay. Kept for a backfill if a morning
    is missed.
  - Saving the hourly values only, or the mean only: the hours keep the rule recomputable, the
    mean keeps the record readable; both are small.
  - Saving under `raw/`: old versions expire there.
- **Status:** Active. 2026-11-24.

---

## D-054 · 2026-11-24 · Validation's remaining classes: entity, key reuse, dates, units (#20, T12b)

- **Decision (owner's choices, 2026-11-24):** a fault in the pipeline or a source stops the run;
  a problem limited to some rows warns; an instrument change is counted.

  | Class | Rule | Severity | Rows |
  | --- | --- | --- | --- |
  | Wrong entity | a row from a site that isn't listed (`site_not_listed`) | hard | excluded |
  | Wrong entity | AQS places a listed site outside the city's CBSA, or lacks it | hard | none |
  | Key reuse | a site's AQS, AirNow and our positions > 1 km apart (`site_moved`) | warn | none |
  | Key reuse | AQS's instrument isn't `AIRNOW_METHOD`'s (`airnow_method_stale`) | warn | none |
  | Key reuse | an instrument's method changes (`method_changed`, each change) | info | kept |
  | Dates | an hour that hasn't ended at run time (`future_hour`) | hard | excluded |
  | Dates | an AQS hour outside its monitor's dates (`outside_active_period`) | warn | excluded |
  | Units | AirNow rows dropped for a unit other than µg/m³ (`unit_mismatch`) | warn | none |
  | Weather dates | an hour outside its file; a run after its hour; early availability | hard | none |
  | Weather values | outside its physical range (`outside_physical_range`) | reported | kept |

  - **AirNow ranges (the T12a box, refines D-033):** AirNow rows carry no method, so each is
    judged against its own site's instrument: `AIRNOW_METHOD` in `observations/sites.py`, the
    site's open hourly AQS monitor (POC 3 at every site). Seven sites run method 182 (−10 to
    5,000), JLG Supersite 638 (0 to 10,000), the two Pinal sites 170 (−10 to 975). A site with
    no listed instrument is unverified (hard), as D-032 does for AQS. The list is fixed in code
    so the daily run needs no AQS call; the AQS report warns when AQS's records disagree, and
    the list changes only by a reviewed edit.
  - **Reference data** (`validation/reference.py`): AQS's `monitors/bySite` records and AirNow's
    `Monitoring_Site_Locations_V2.dat`. Only the report fetches them; the daily run carries
    none, so the four rules that need them don't run there. Neither holds a measurement.
  - **1 km** is the site list's existing tolerance: AQS and AirNow publish positions up to
    0.57 km apart for the same monitor (Glendale), and the two closest monitors are over 2 km
    apart (a test checks both).
  - **Each excluded row is counted once**, by the first rule that excludes it: unlisted site,
    future hour, unverified method, outside the valid range, outside the active period (a
    property test).
  - **Units** are checked where the unit is still known, when each source is read: AQS stops
    parsing on another unit, Open-Meteo and CAMS refuse the response (`unit`), AirNow drops the
    row and the report now counts it apart. Each has a test with a planted bad unit.
  - **Weather's location** is checked when a response is read (`grid_too_far`), at the
    coordinates in `SITE_COORDS`, which `site_moved` now checks against AQS and AirNow.
  - **Physical ranges:** percentages 0 to 100, direction 0 to 360°, rain, wind, sunlight and
    PM2.5 never negative; generous upper bounds and −60 to 60 °C, 500 to 1,100 hPa, far outside
    anything Phoenix sees. Values outside are kept as received (D-031); the features (T15)
    decide what to do with them.
  - The flat-line rule (D-033) is unchanged.
- **Measured before deciding (2026-11-24):**
  - Every AQS hourly row lies inside its monitor's open period; each site's history starts on
    its monitor's open date. All 10 sites are in CBSA 38060 in AQS and AirNow; each has one
    position in AQS, equal to `SITE_COORDS`; AirNow's are within 0.57 km.
  - AQS's hourly rows all come from POC 3. Seven method changes, each a clean switch in one
    month (West Phoenix 181 → 170 → 181 → 182, a loaned instrument), none a reused ID.
  - Two weeks of AirNow (2026-11-09 to 11-22): no hour outside its own site's range.
  - Weather and CAMS: 81 values outside the physical ranges, all GFS-archive cloud cover at
    exactly −1 or 101 % (37 and 44, every site, 2024 to 2025): rounding at the ends of the range.
- **Why:** the owner's day-one rule, whole problem classes on every source (D-021). Stopping on
  a fault and warning on a limited problem is D-033's split, kept.
- **Alternatives (rejected by the owner):** every new rule a warning; the location rules hard
  too; looking the AirNow instrument up in AQS on every run (an AQS call and key in the daily
  run, and AQS lags months); keeping the widest AirNow range.
- **Status:** Active. Owner's choices, 2026-11-24. Refines D-021 (T12b done) and D-033 (AirNow
  ranges per site).

---

## D-055 · 2026-11-24 · The scheduled run reports a foreign error by type (#86, refines #56)

- **Decision:** `daily_job` re-raises any error from someone else's code as `JobFailedError`,
  whose message is the target day and the error's type ("2026-11-25: daily job failed:
  ValueError"), raised `from None` so the printed traceback drops the original and its message.
  Our own `ReportableError`s pass through unchanged; `KeyboardInterrupt` and other non-`Exception`
  errors are never caught. Scoring logs a failed day as "<day>: scoring failed (<type>)" with no
  traceback, and `ScoringError` (days and type names only) becomes a `ReportableError`.
- **What changes for the run:** it still ends Failed, so the watchdog and alerts behave as before,
  and the minutes are still filed first. Prefect's log shows the type and the frames of our own
  code, no longer the foreign message or the frames below it.
- **Why:** #56's rule (errors by type; only our own messages printed) held on the command line
  but not on the daily path, where Prefect logs the full exception. A message from pandas,
  botocore or httpx can quote a cell, a bucket key or a URL.
- **Cost:** debugging a scheduled failure needs a local rerun to see the foreign message. A
  dry run reproduces any day (`python -m airwatch.forecast.run`), so that is cheap.
- **Alternatives:** filtering Prefect's log handler (it sees formatted text, too late to judge
  what is data); keeping the chain and trusting Prefect's private logs (breaks the rule on the
  path that runs every day).
- **Status:** Active. 2026-11-24.

---

## D-056 · 2026-11-24 · Python releases wait 7 days in the weekly lock job (#122, refines D-027)

- **Decision (owner's choice, 2026-11-24):** the weekly lock job runs
  `uv lock --upgrade --exclude-newer "7 days"`, the same wait Dependabot's cooldown gives Actions
  updates. Only the job sets it: `pyproject.toml` has no `exclude-newer`. A new or raised
  minimum (`>=` or `==`) must be a release at least 7 days old. An urgent release is taken by
  hand with a one-week exemption on the job's line (DEVELOPMENT.md). A test checks the job's
  command, that only such exemptions may follow it, and that the wait equals Dependabot's.
- **Facts (uv 0.13.9, tried 2026-11-24 on a copy of the project):**
  - uv turns "7 days" into a cutoff at each run ("Resolving despite existing lockfile due to
    addition of global exclude newer <timestamp>").
  - A lock made with the flag leaves `uv.lock` unchanged for a later `uv lock --locked` without
    it, so local runs agree with the job.
  - With `--upgrade`, uv ignores locked versions newer than the cutoff: it re-resolves to the
    newest release before it, hence the exemption for an urgent release.
  - Our minimums are set to the newest release when a package is added (boto3>=1.44.6 on 11-18),
    so a cutoff in `pyproject.toml` would fail every local lock for that package's first week.
    By the next run (2026-11-30) every current minimum is over 7 days old (PyPI upload times),
    including the `zensical==0.1.3` pin and its `zensical-ui==0.0.43`.
  - uv's docs: `exclude-newer` takes a timestamp or a duration ("30 days", "P7D"), compared with
    each file's upload time; `exclude-newer-package` sets or disables (`false`) the cutoff for one
    package (docs.astral.sh/uv/reference/settings/#exclude-newer and #exclude-newer-package,
    docs.astral.sh/uv/concepts/resolution/#reproducible-resolutions, read 2026-11-24).
- **Why:** #119 opened with filelock 4.3.1 two minutes after its upload. A week lets a broken or
  malicious release be found and yanked before it reaches the lock.
- **Alternatives (rejected by the owner):** the cutoff in `pyproject.toml` for everyone (an
  exemption for every new minimum until it ages); no wait, holding each lock PR by hand.
- **Status:** Active. 2026-11-24.

---

## D-057 · 2026-11-24 · The 30 s goal is the median of three quiet runs; tests grouped by Prefect (#124)

- **Decision (owner's choice, 2026-11-24):** the core suite's 30 s goal (D-035) is judged as the
  median of three back-to-back runs on the owner's PC with other heavy apps closed, pytest's own
  figure. A busy-PC timing is noise and doesn't fail the goal. CI's 75 s limit (D-046) is
  unchanged. The suite distributes with `--dist loadgroup`, and every test using the `daily`
  fixture joins one `prefect` group (`tests/conftest.py`), so one worker imports Prefect instead
  of two or three; a test checks both.
- **Measured (2026-11-24):**
  - Before T14 (`72b8396`) vs `main` (`ea33d84`): summed test time 58.9 → 79.0 s, about +5 s
    wall over 4 workers, all from new tests (validation properties +6.1 s, the daily job +3.7 s,
    weather +3.0 s, leakage properties +1.6 s); no old test slower.
  - The same code: 26.8 to 27.0 s over five quiet runs in the morning; 31 to 35 s in the
    afternoon with a browser and editor busy (CPU about 20%), an 8 s swing.
  - `loadgroup` against `load`, six alternating pairs: about 1.2 s faster on average (−2.9 to
    +1.1 s per pair). `worksteal`: about 1 s faster in three pairs.
  - Profiling a validation property: `run_checks` is about 40% of an example, spread across
    pandas' overhead on small frames, with no single hot spot.
- **Why:** a goal that the same code passes or fails depending on what else the PC is doing
  measures the PC, not the suite.
- **Alternatives (rejected by the owner):** raising the goal to 35 s; keeping 30 s at any time and
  spending hours speeding up the property tests without cutting examples.
- **Status:** Active. 2026-11-24. Refines D-035 and D-046.

---

## Open questions (to settle, then move into a D-entry)

- Further open items are listed in [SPEC.md](SPEC.md) § Open Questions.

Closed: Q-6 → D-030 (Phoenix, by the D-006 check). Q-1 → D-020. Q-2, Q-3, Q-5 → D-003.
Q-4 → D-003 and D-011.
