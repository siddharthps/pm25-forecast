# Bottom line

!!! note "Skeleton"
    This page is a skeleton. Each *(pending)* fills in from `results/results.json` once its
    result exists; the prose is written after the research freeze (2026-12-23).

## What AirWatch does

Every morning at 06:00 Chicago time, AirWatch forecasts tomorrow's daily mean PM2.5 for each
monitor in the Phoenix metro area and publishes it. Each forecast is recorded before it is
published, and scored once the day's readings are in.

## The answer

- **Headline model:** {{ results.headline.model | show }}, chosen by a rule fixed before any
  result was seen.
- **Test year (2025, read once):** MAE {{ results.headline.test_mae | show }} µg/m³, against
  {{ results.headline.persistence_test_mae | show }} µg/m³ for persistence.
- **Skill against persistence:** {{ results.headline.skill_vs_persistence | show }}.
- **Live track record:** {{ results.live.days_scored | show }} days scored, MAE
  {{ results.live.mae | show }} µg/m³, against {{ results.live.persistence_mae | show }} µg/m³ for
  persistence.

## How far to trust it

- **Weather forecasts versus observed weather:** the MAE gap is
  {{ results.skew.weather_forecast_vs_observed_mae_gap | show }} µg/m³.
- **Live data versus validated data:** the MAE gap between AirNow and AQS is
  {{ results.skew.airnow_vs_aqs_mae_gap | show }} µg/m³.

## Where to look next

- [The forecast](forecast.md): what is predicted, and how it is scored.
