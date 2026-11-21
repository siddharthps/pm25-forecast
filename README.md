# pm25-forecast

AirWatch: live next-day PM2.5 forecasts for the Phoenix metro area, with an honest public track
record.

**Live page:** <https://siddharthps.github.io/pm25-forecast/>

> Skeleton: the headings and notes below are filled in as prose after the research freeze
> (2026-12-23). Until then, the [issues](https://github.com/siddharthps/pm25-forecast/issues)
> hold the plan.

## What it is

- Every morning at 06:00 Chicago time, a scheduled job forecasts tomorrow's daily mean PM2.5 at
  each monitor and publishes it to the live page.
- Each forecast is recorded before it is published, and scored against the day's readings once
  they are in.
- The write-up (`docs/`) reports the headline model against persistence, climatology and CAMS,
  whatever the result.

## How v2 avoids v1's mistakes

- **v1 split time series at random,** so the model saw the future. v2 splits by time: develop on
  2009–2024 with rolling-origin cross-validation, test on 2025 (D-008).
- **v1 chose its model on the test set.** v2 fixes the selection rule and the variants before any
  result, and reads the test year once (D-008, D-010).
- **v1's "forecast" only backfilled past days.** v2 issues a real forecast each morning, recorded
  before the day it predicts, with a public track record (D-019).

## Development

The commands for checks, docs, data and infrastructure are in [DEVELOPMENT.md](DEVELOPMENT.md).
Decisions and their reasons are in [notes/DECISIONS.md](notes/DECISIONS.md).
