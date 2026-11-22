# Bottom line

!!! note "Skeleton"
    Each *(pending)* fills in from `results/results.json` once its result exists. The prose is
    written after the research freeze (2026-12-23).

## What AirWatch does

Every morning at 06:00 Chicago time, AirWatch forecasts tomorrow's average level of fine
particles (PM2.5) at each air monitor in the Phoenix metro area, and publishes it. Each
forecast is saved before it goes public, then scored once the day's readings are in.

## The answer

The forecaster is **{{ results.headline.model }}**, picked by a rule fixed before any result
was seen. On 2025, a year it never saw while being built, it was off by
{{ results.headline.test_mae }} µg/m³ on a typical day. Against the simple ways of guessing
tomorrow:

| Compared with | Its error (µg/m³) | AirWatch better by | Likely range ({{ results.design.ci_level }}%) | Verdict |
| --- | --- | --- | --- | --- |
| Tomorrow like the last full day | {{ results.test_vs.persistence.mae }} | {{ results.test_vs.persistence.gap }} | {{ results.test_vs.persistence.ci_low }} to {{ results.test_vs.persistence.ci_high }} | {{ results.test_vs.persistence.verdict }} |
| The usual level for that date | {{ results.test_vs.climatology.mae }} | {{ results.test_vs.climatology.gap }} | {{ results.test_vs.climatology.ci_low }} to {{ results.test_vs.climatology.ci_high }} | {{ results.test_vs.climatology.verdict }} |
| A global physics forecast (CAMS) | {{ results.test_vs.cams.mae }} | {{ results.test_vs.cams.gap }} | {{ results.test_vs.cams.ci_low }} to {{ results.test_vs.cams.ci_high }} | {{ results.test_vs.cams.verdict }} |

"No clear difference" means the likely range includes no gain at all.

## Live, as of {{ results.live.as_of }}

Since it took over on {{ results.live.model.first_day }}, the model has been scored on
{{ results.live.model.days_scored }} days, off by {{ results.live.model.mae }} µg/m³ on a
typical day. Against tomorrow-like-today: **{{ results.live.model_vs.persistence.verdict }}**.
Before that, from {{ results.live.launch_period.first_day }}, the page published the simple
guess, scored apart. [The live page](https://siddharthps.github.io/pm25-forecast/) shows
today's numbers.

## How far to trust it

- **Predicted weather:** the model learns from measured weather but forecasts with predicted
  weather, which costs {{ results.skew.weather_forecast_vs_observed_mae_gap }} µg/m³.
- **Early readings:** live scores use early readings, corrected later; the difference is
  {{ results.skew.airnow_vs_aqs_mae_gap }} µg/m³.

## Where to look next

- [The forecast](forecast.md): what is predicted, and how it is scored.
