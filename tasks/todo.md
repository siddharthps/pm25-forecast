# Task index: AirWatch v2

The tracker is **GitHub Issues** on
[siddharthps/pm25-forecast](https://github.com/siddharthps/pm25-forecast/issues). Each issue holds
its task's "Done when" boxes. This file only maps task numbers (used in the plan and in "Depends
on" lines) to issues. Plan and order: [plan.md](plan.md). Created 2026-11-18 from the approved
drafts.

Milestones: **A: Foundation** (due 2026-11-20) · **B: Skeleton live** (2026-11-25) · **C: Cut
line** (2026-12-16) · **D: Complete**.

| Task | Issue | Title | Milestone | State (2026-11-19, from GitHub) |
| --- | --- | --- | --- | --- |
| T0a | [#1](https://github.com/siddharthps/pm25-forecast/issues/1) | AirNow API account + read the gated docs | A | closed |
| T0b | [#2](https://github.com/siddharthps/pm25-forecast/issues/2) | Prefect Cloud Hobby account + workspace | A | closed |
| T0c | [#3](https://github.com/siddharthps/pm25-forecast/issues/3) | AWS hygiene and project identity | A | open until 11-25 (delete the old key) |
| T0d | [#4](https://github.com/siddharthps/pm25-forecast/issues/4) | Create the new public GitHub repo | A | closed |
| T1 | [#5](https://github.com/siddharthps/pm25-forecast/issues/5) | Day-zero scaffold and quality gates | A | closed |
| T2 | [#6](https://github.com/siddharthps/pm25-forecast/issues/6) | CI on GitHub Actions | A | open: merged (#39); closes after the 11-23 lock-job PR passes CI |
| T3 | [#7](https://github.com/siddharthps/pm25-forecast/issues/7) | Typed config and time rules | A | closed |
| T3b | [#8](https://github.com/siddharthps/pm25-forecast/issues/8) | Terraform base: data buckets and permissions | A | closed |
| T4 | [#9](https://github.com/siddharthps/pm25-forecast/issues/9) | City data check (D-006) | B | closed |
| T5 | [#10](https://github.com/siddharthps/pm25-forecast/issues/10) | Observations skeleton | B | closed |
| T13 | [#11](https://github.com/siddharthps/pm25-forecast/issues/11) | AQS bulk history download | B | closed |
| T12a | [#12](https://github.com/siddharthps/pm25-forecast/issues/12) | Validation module, first three problem classes | B | closed |
| T6 | [#13](https://github.com/siddharthps/pm25-forecast/issues/13) | Persistence forecast and at-most-once durable record | B | closed |
| T7 | [#14](https://github.com/siddharthps/pm25-forecast/issues/14) | Public JSON and static page | B | open: merged (#54); go-live pending (AirNow form, then `PAGES_GO_LIVE`) |
| T8 | [#15](https://github.com/siddharthps/pm25-forecast/issues/15) | Prefect daily deployment | B | open |
| T9 | [#16](https://github.com/siddharthps/pm25-forecast/issues/16) | Watchdog (EventBridge → Lambda → Prefect / SNS) | B | open |
| T10 | [#17](https://github.com/siddharthps/pm25-forecast/issues/17) | Daily scoring | B | open |
| T11 | [#18](https://github.com/siddharthps/pm25-forecast/issues/18) | Docs stub, number check and README skeleton | B | open |
| T14 | [#19](https://github.com/siddharthps/pm25-forecast/issues/19) | Weather ingestion | C | open |
| T12b | [#20](https://github.com/siddharthps/pm25-forecast/issues/20) | Validation, remaining problem classes and weather sources | C | open |
| T15 | [#21](https://github.com/siddharthps/pm25-forecast/issues/21) | Leakage-safe features | C | open |
| T16 | [#22](https://github.com/siddharthps/pm25-forecast/issues/22) | CV harness and baselines | C | open |
| T17 | [#23](https://github.com/siddharthps/pm25-forecast/issues/23) | MLflow backend and promotion pointer | C | open |
| T18 | [#24](https://github.com/siddharthps/pm25-forecast/issues/24) | Ridge + Random Forest (CV only) | C | open |
| T19 | [#25](https://github.com/siddharthps/pm25-forecast/issues/25) | XGBoost + LightGBM (CV only) | C | open |
| T20 | [#26](https://github.com/siddharthps/pm25-forecast/issues/26) | LSTM (CV only) | C | open |
| T21 | [#27](https://github.com/siddharthps/pm25-forecast/issues/27) | TCN (CV only), first on the cut line | C | open |
| T22 | [#28](https://github.com/siddharthps/pm25-forecast/issues/28) | Skew measurements | C | open |
| T23 | [#29](https://github.com/siddharthps/pm25-forecast/issues/29) | Select the headline and promote it | C | open |
| T24 | [#30](https://github.com/siddharthps/pm25-forecast/issues/30) | Weekly drift and flags | C | open |
| T25 | [#31](https://github.com/siddharthps/pm25-forecast/issues/31) | Page map and track-record charts (cut line 2) | C | open |
| T26 | [#32](https://github.com/siddharthps/pm25-forecast/issues/32) | AQS re-scoring (cut line 3) | C | open |
| T27 | [#33](https://github.com/siddharthps/pm25-forecast/issues/33) | Final test, read once | D | open |
| T28 | [#34](https://github.com/siddharthps/pm25-forecast/issues/34) | Write-up | D | open |
| T29 | [#35](https://github.com/siddharthps/pm25-forecast/issues/35) | Live acceptance | D | open |
| T30 | [#36](https://github.com/siddharthps/pm25-forecast/issues/36) | Retire v1 | D | open |

## Added along the way (no T-number; plan.md rule 6)

| Issue | Title | Found in | Milestone |
| --- | --- | --- | --- |
| [#42](https://github.com/siddharthps/pm25-forecast/issues/42) | Mutation testing (mutmut) on the existing core logic | T3b | B |
| [#43](https://github.com/siddharthps/pm25-forecast/issues/43) | uv-lock job: idempotency and step-failure tests | T3b | B |
| [#52](https://github.com/siddharthps/pm25-forecast/issues/52) | Log timestamps in UTC with the zone shown (one logging setup) | T12a | B |

The **State** column is a snapshot. GitHub is the source of truth, and this column is not kept in
sync.
