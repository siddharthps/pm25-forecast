# Write-up outline (D-022, D-044)

Seven short pages plus the README. Every page backs up a claim on the bottom line. The prose
comes after the research freeze (2026-12-23); until then each page is a skeleton. The style
sheet is [STYLE.md](STYLE.md).

## Readers (D-044)

- **The bottom line and the README:** anyone, a hiring manager or a member of the public. Plain
  words, no unexplained terms.
- **The chapters:** a technical reader (an ML or data interviewer). Each term is defined at its
  first use.

## Pages

| Page | File | Answers | Numbers and charts (`results/`) | Built on | Written in |
| --- | --- | --- | --- | --- | --- |
| Bottom line | `docs/index.md` | How good is the forecast, and how far to trust it? | `headline.*`, `test_vs.*`, `live.*`, `skew.*` | all below | T11 skeleton, T28 |
| The forecast | `docs/forecast.md` | What is predicted, and how is it scored? | `design.*` | D-005, D-008, D-009, D-010, D-019, D-045 | T11 skeleton, T28 |
| The data | `docs/data.md` | Where the data comes from, and what the checks found | validation counts; `skew.airnow_vs_aqs_mae_gap` | D-004, D-006, D-030 to D-033 | T12b, T28 |
| Models and evaluation | `docs/models.md` | Which variants, how the headline was chosen, the test result | CV MAE per variant; `test_vs.*`; **charts 1, 2, 4** | D-007 to D-010, D-045 | T16 to T23, T27, T28 |
| The live record | `docs/live.md` | How the daily forecasts have scored, by forecaster | `live.*`; **chart 3** | D-042, D-044 | T28, after T29 |
| How it runs | `docs/how-it-runs.md` | How the daily job stays up and acts once | job, watchdog, drill, tests, cost | D-011, D-019, D-040 to D-042 | T28 |
| Limits and next steps | `docs/limits.md` | What would change the answer; what v2 doesn't do | `skew.*` | SPEC § Out of scope | T28 |

A page is added to `docs/` (and the nav) in the task that writes its skeleton. The docs check
runs on every page from its first commit.

## Charts (D-044, declared before any result)

Each chart is drawn at build time from a data file the pipeline writes into `results/`, never
saved by hand, so a chart can't disagree with the numbers around it.

1. **Models against the baselines:** each variant's CV MAE beside persistence, climatology and
   CAMS, plus the headline model's 2025 test MAE.
2. **Error by month:** the headline model against persistence, month by month over 2025.
3. **Live forecast against what happened:** each day up to the snapshot, the headline model's
   days and the launch period marked apart.
4. **Bad-air days:** recall on days rated "Unhealthy for Sensitive Groups" or worse (D-009).

## The live record (D-044)

- Quoted **as of one fixed date:** the end of T29's 14-day window. The page links to the live
  page for today's numbers.
- **Split by forecaster:** the headline model is scored only on the days it issued (each record's
  `method`). The persistence launch period is shown apart.
- **Against all three baselines:** CAMS's D+1 forecast is saved each morning as issued, so the
  live comparison is fair.

## Publishing (D-044)

Served at `siddharthps.github.io/pm25-forecast/report/` by the existing Pages deploy. The deploy
is built and dry-run early but stays switched off until T28's write-up is in, and goes on only
at the owner's go.

## The README

What it is, the live link, and how v2 avoids v1's mistakes (D-002: prose only, no link to v1).
It stays short and points to the bottom line.
