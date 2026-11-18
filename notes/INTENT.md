# Statement of intent: AirWatch v2

Confirmed by the owner on 2026-11-18 (interview-me). This is the "why and what" that the spec and
every later decision must serve. Change it only with a new entry in [DECISIONS.md](DECISIONS.md).

| Aspect | Intent |
| --- | --- |
| **Outcome** | A rebuilt AirWatch that runs live. It forecasts **next-day PM2.5 for one city**, chosen on data merit (fresh daily data, several monitors, enough history, interesting pollution events); Chicago is the default if nothing beats it. A **public page** shows forecasts against what was actually measured, building a track record. |
| **User** | Hiring managers and interviewers reading the repo and the live page. Takeaway: *"this person understands production ML, not just notebooks."* |
| **Why now** | The 2025 version is dated and fundamentally flawed (see [JOURNAL.md](JOURNAL.md), 2026-11-18). The owner also wants to learn the 2026 versions of the tools while doing it properly. |
| **Success** | The page updates **daily without manual help**. The track record is **honest**: time-based evaluation, a simple baseline to beat, test set read once. Every tool choice is **justified** in the decisions log. |
| **Constraints** | Under about **$5 a month**, ideally close to $0. **No always-on servers.** A scheduler **more reliable than GitHub cron**, with a **backup trigger** and **at-most-once** daily runs. Time: about **20 h in the first week** (from 2026-11-18), then about **10 h a week**. No hard deadline. |
| **Models** | Baseline → classical → **simpler deep-learning models**, each **under 6 h to train**. A model must beat the baseline to earn its place, and the models to compare are declared before results are seen. Training happens off the daily schedule (on the owner's PC or a cheap one-off machine). |
| **Tools** | **Prefect, MLflow, Evidently and AWS** each do real work, because learning them is a goal in itself. **GitHub Actions is for CI only**, not the production schedule. |
| **Approach** | A fresh rebuild in a **new public repo** with noreply commits from the first commit; the 2025 repo is made private ([D-002](DECISIONS.md)). Carried over: one module per stage, moto fakes, `uv`, Ruff. |
| **Out of scope** | More than one city at a time; more pollutants; a real-time API or user accounts; large or GPU-heavy models; paid or always-on hosting; keeping the old backfill flow working. |
