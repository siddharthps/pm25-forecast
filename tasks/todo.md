# Task index: AirWatch v2

The tracker is **GitHub Issues** on
[siddharthps/pm25-forecast](https://github.com/siddharthps/pm25-forecast/issues). Each issue holds
its task's "Done when" boxes. This file only maps task numbers (used in the plan and in "Depends
on" lines) to issues. Plan and order: [plan.md](plan.md). Created 2026-11-18 from the approved
drafts.

Milestones: **A: Foundation** (due 2026-11-20) · **B: Skeleton live** (2026-11-25) · **C: Cut
line** (2026-12-16) · **D: Complete**.

| Task | Issue | Title | Milestone | State (2026-11-20, from GitHub) |
| --- | --- | --- | --- | --- |
| T0a | [#1](https://github.com/siddharthps/pm25-forecast/issues/1) | AirNow API account + read the gated docs | A | closed |
| T0b | [#2](https://github.com/siddharthps/pm25-forecast/issues/2) | Prefect Cloud Hobby account + workspace | A | closed |
| T0c | [#3](https://github.com/siddharthps/pm25-forecast/issues/3) | AWS hygiene and project identity | A | open until 11-25 (delete the old key); register completed (#96) |
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
| T7 | [#14](https://github.com/siddharthps/pm25-forecast/issues/14) | Public JSON and static page | B | closed (live 2026-11-20, D-039) |
| T8 | [#15](https://github.com/siddharthps/pm25-forecast/issues/15) | Prefect daily deployment | B | closed (first scheduled run 2026-11-21, D-040) |
| T9 | [#16](https://github.com/siddharthps/pm25-forecast/issues/16) | Watchdog (EventBridge → Lambda → Prefect / SNS) | B | closed (applied and drilled 2026-11-20, D-041) |
| T10 | [#17](https://github.com/siddharthps/pm25-forecast/issues/17) | Daily scoring | B | closed (merged #74, 2026-11-21, D-042) |
| T11 | [#18](https://github.com/siddharthps/pm25-forecast/issues/18) | Docs stub, number check and README skeleton | B | closed (merged #84, 2026-11-22 UTC, D-043) |
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
| [#42](https://github.com/siddharthps/pm25-forecast/issues/42) | Mutation testing (mutmut) on the existing core logic (merged #95, 2026-11-22 UTC, D-048) | T3b | B |
| [#43](https://github.com/siddharthps/pm25-forecast/issues/43) | uv-lock job: idempotency and step-failure tests (merged #94; open until a real run opens a PR with CI) | T3b | B |
| [#52](https://github.com/siddharthps/pm25-forecast/issues/52) | Log timestamps in UTC with the zone shown (one logging setup) (merged #92, 2026-11-22 UTC) | T12a | B |
| [#56](https://github.com/siddharthps/pm25-forecast/issues/56) | Forecast failure log prints the exception message, not only its type (merged #91, 2026-11-22 UTC) | comment audit (#55) | B |
| [#57](https://github.com/siddharthps/pm25-forecast/issues/57) | AirNow POC: replace the 0 sentinel or record it (merged #93, 2026-11-22 UTC, D-047) | comment audit (#55) | B |
| [#58](https://github.com/siddharthps/pm25-forecast/issues/58) | test_publish: pytest ids instead of a dummy 'assert why' (merged #89, 2026-11-22 UTC) | comment audit (#55) | B |
| [#59](https://github.com/siddharthps/pm25-forecast/issues/59) | Leakage property test: assume() instead of an early return (merged #90, 2026-11-22 UTC) | comment audit (#55) | B |
| [#75](https://github.com/siddharthps/pm25-forecast/issues/75) | Watchdog schedules send the time placeholder escaped (fixed in #76; closed 2026-11-22 after a silent morning) | the first real watchdog checks (T9) | B |
| [#78](https://github.com/siddharthps/pm25-forecast/issues/78) | Save CAMS's D+1 forecast each morning, as issued (with T14; running before T23) | the write-up plan (T11, D-044) | C |
| [#79](https://github.com/siddharthps/pm25-forecast/issues/79) | The pipeline writes results.json and the chart data | T11 (D-043, D-044) | C |
| [#80](https://github.com/siddharthps/pm25-forecast/issues/80) | Draw the write-up's four charts at build time | the write-up plan (T11, D-044) | C |
| [#81](https://github.com/siddharthps/pm25-forecast/issues/81) | Block-bootstrap intervals and verdicts (D-045) | the write-up plan (T11, D-045) | C |
| [#82](https://github.com/siddharthps/pm25-forecast/issues/82) | Publish the write-up at /report/, kept switched off until T28 | the write-up plan (T11, D-044) | C |
| [#83](https://github.com/siddharthps/pm25-forecast/issues/83) | Core test suite back under its 30 s budget (merged #85, 2026-11-22 UTC, D-046) | T11 timing checks | B |
| [#86](https://github.com/siddharthps/pm25-forecast/issues/86) | Scheduled run: report a failed step's error by type, as #56 did for the CLI | #56 | C |
| [#87](https://github.com/siddharthps/pm25-forecast/issues/87) | Leakage property: why the unfinished-day test discards 1,220 of 3,220 examples | #59 | C |
| [#88](https://github.com/siddharthps/pm25-forecast/issues/88) | One process-zone test helper for the time-zone tests (after #52 and #42 merge) | #42 | C |

The **State** column is a snapshot. GitHub is the source of truth, and this column is not kept in
sync.
