# The forecast

!!! note "Skeleton"
    Headings and notes only. The prose comes after the research freeze.

## What is predicted

- Tomorrow's daily mean PM2.5 (µg/m³, local calendar day) at each monitor in the metro area
  (D-005).
- Issued at 06:00 Chicago time for D+1 (D-019).

## How it is scored

- **Headline metric:** MAE, pooled across monitors (D-009).
- **Baselines:** {{ results.design.baselines }} to beat: persistence, climatology and CAMS
  (D-009).
- **Model variants:** {{ results.design.variants }}, declared before any result (D-010).
- **Cross-validation:** {{ results.design.cv_folds }} yearly folds, 2019–2024; the 2025 test is
  read once (D-008).

## What counts as a win

- The headline model beats persistence on the test year and on the live record. If it doesn't,
  this page says so.
