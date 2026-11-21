# Write-up outline (D-022)

About five short pages, plus the README. Each page supports the bottom line. Prose comes after
the research freeze (2026-12-23); until then each page is a skeleton (headings and bullets). The
style sheet is [STYLE.md](STYLE.md).

| Page | File | Answers | Key numbers (`results.json`) | Built on |
| --- | --- | --- | --- | --- |
| Bottom line | `docs/index.md` | How good is the forecast, and how far to trust it? | `headline.*`, `live.*`, `skew.*` | all below |
| The forecast | `docs/forecast.md` | What is predicted, and how is it scored? | `design.*` | D-005, D-008, D-009, D-010, D-019 |
| The data | `docs/data.md` | Where the data comes from, and what the validation found | validation counts; `skew.airnow_vs_aqs_mae_gap` | D-004, D-006, D-030 to D-033 |
| Models and evaluation | `docs/models.md` | Which variants were tried, how the headline was chosen, the test result | CV MAE per variant; `headline.*` | D-007 to D-010, T16 to T23, T27 |
| The live record | `docs/live.md` | How the daily forecasts have scored since launch, and how the job stays up | `live.*` | D-011, D-019, D-041, D-042 |
| Limits and next steps | `docs/limits.md` | What would change the answer, and what v2 doesn't do | `skew.*` | SPEC § Out of scope |

## The README

What it is, the live link, and how v2 avoids v1's mistakes (D-002: prose only, no link to v1).
It is the first thing a visitor reads, so it stays short and points to the bottom line.

## Pages are added when their task runs

Only the bottom line and the forecast page exist now (T11). Each other page starts as a
skeleton in the task that produces its numbers. The docs check runs on every page from its first
commit.
