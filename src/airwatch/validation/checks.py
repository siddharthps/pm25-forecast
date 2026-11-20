"""Data-quality checks on hourly PM2.5 (#12, T12a; D-021, D-033).

Each check covers one *problem class*, never a single case, and reports every rule it applies,
at zero too, so a report shows that a check ran. Severities:

- **hard:** the data can't be trusted as a whole (a pipeline or source fault). The run stops:
  `ValidationResult.raise_if_failed` raises, and the daily flow writes no record (T6).
- **warn:** a real problem, limited to some rows or site-months. Reported; the run goes on.
- **info:** counted for the record, not a problem in itself.

Rules (D-033):

| Class | Rule | Severity | Rows |
| --- | --- | --- | --- |
| duplicates | `duplicate_hours`: a (source, site, POC, hour) seen twice | hard | kept |
| implausible values | `unverified_method`: no sourced range (D-032) | hard | excluded |
| implausible values | `outside_valid_range`: outside AQS's method range | warn | excluded |
| implausible values | `negative_in_range`: below zero, in range (noise) | info | kept |
| implausible values | `flat_line`: 12+ identical hours in a row, one instrument | warn | kept |
| coverage gaps | `coverage_gap`: a local site-month < 75% usable hours | warn | - |
| coverage gaps | `site_missing`: a listed site with no rows at all | warn | - |
| AirNow IDs | `airnow_not_aqs_id`, `airnow_unmatched_site`, `airnow_rows_dropped` | info | - |

Raw data is never changed (D-031): `clean` is a filtered copy. Items name sites, instruments,
times and counts, never a measurement, so reports can be logged and shared.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from airwatch.observations.schema import validate_hourly
from airwatch.observations.sites import VERIFIED_METHODS
from airwatch.timeutil import ensure_utc, local_day_window_utc

__all__ = [
    "AIRNOW_RANGE_UG_M3",
    "COVERAGE_MIN_SHARE",
    "FLATLINE_MIN_HOURS",
    "CoverageFrom",
    "Finding",
    "Severity",
    "ValidationFailedError",
    "ValidationResult",
    "Window",
    "run_checks",
]

# D-033: owner's choices on 2026-11-19, set before any real data was checked.
FLATLINE_MIN_HOURS = 12  # a judgement (no published EPA threshold found); warn only
COVERAGE_MIN_SHARE = 0.75  # the SPEC's daily rule (18 of 24 hours), applied per month
# AirNow rows carry no method, so they get the widest range across the verified methods.
AIRNOW_RANGE_UG_M3 = (
    min(m.min_value for m in VERIFIED_METHODS.values()),
    max(m.max_value for m in VERIFIED_METHODS.values()),
)

KEY = ["source", "site_id", "poc", "time_utc"]

CoverageFrom = Literal["window", "first_reading"]
Item = dict[str, str | int]


class Severity(StrEnum):
    HARD = "hard"
    WARN = "warn"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    """One rule's outcome: how many rows or site-months it caught, and which."""

    problem_class: str
    rule: str
    severity: Severity
    count: int
    excluded: int = 0
    items: tuple[Item, ...] = ()


@dataclass(frozen=True)
class Window:
    """The half-open UTC period [start, end) that coverage is judged over."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", ensure_utc(self.start))
        object.__setattr__(self, "end", ensure_utc(self.end))
        if not self.start < self.end:
            raise ValueError("window start must be before its end")


class ValidationFailedError(RuntimeError):
    """At least one hard rule caught something. The message names rules and counts only."""


@dataclass(frozen=True, eq=False)
class ValidationResult:
    findings: tuple[Finding, ...]
    clean: pd.DataFrame  # the usable rows: input minus every excluded row
    rows_in: int

    @property
    def passed(self) -> bool:
        return not self.hard_failures

    @property
    def hard_failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.HARD and f.count)

    def finding(self, rule: str) -> Finding:
        for f in self.findings:
            if f.rule == rule:
                return f
        raise KeyError(rule)

    def raise_if_failed(self) -> None:
        if self.hard_failures:
            listed = ", ".join(f"{f.rule}: {f.count}" for f in self.hard_failures)
            raise ValidationFailedError(f"hard validation failure ({listed})")


def run_checks(  # noqa: PLR0913  (each argument is one part of the run's context)
    df: pd.DataFrame,
    *,
    window: Window,
    tz: ZoneInfo,
    sites: Iterable[str],
    coverage_from: CoverageFrom = "window",
    ingest_drops: Mapping[str, int] | None = None,
) -> ValidationResult:
    """Every check on an hourly frame (the shared schema). Raises ValueError on a bad schema.

    `coverage_from="window"` expects each site for the whole window (the daily flow);
    `"first_reading"` starts each site at its first row (history, where monitors began at
    different times). `ingest_drops` are the AirNow reader's drop counts, when there are any.
    """
    validate_hourly(df)
    df = df.reset_index(drop=True)

    unverified = _unverified_mask(df)
    outside = ~unverified & _outside_range_mask(df)
    clean = df[~(unverified | outside)].reset_index(drop=True)

    findings = [
        _duplicates(df),
        _unverified(df, unverified),
        Finding(
            "implausible values",
            "outside_valid_range",
            Severity.WARN,
            int(outside.sum()),
            excluded=int(outside.sum()),
            items=_hours_per_instrument(df[outside]),
        ),
        Finding(
            "implausible values",
            "negative_in_range",
            Severity.INFO,
            int((clean["value_ug_m3"] < 0).sum()),
        ),
        _flat_lines(clean),
        *_coverage(
            clean, df=df, window=window, tz=tz, sites=tuple(sites), coverage_from=coverage_from
        ),
    ]
    if ingest_drops is not None:
        findings.extend(_airnow_ids(ingest_drops))
    return ValidationResult(tuple(findings), clean, len(df))


# --- duplicates ----------------------------------------------------------------------------


def _duplicates(df: pd.DataFrame) -> Finding:
    extra = df.duplicated(KEY, keep="first")
    if not extra.any():
        return Finding("duplicates", "duplicate_hours", Severity.HARD, 0)
    keys = df.loc[df.duplicated(KEY, keep=False), ["site_id", "poc", "time_utc"]]
    keys = keys.drop_duplicates().sort_values(["site_id", "poc", "time_utc"])
    items: tuple[Item, ...] = tuple(
        {"site_id": str(s), "poc": int(p), "time_utc": t.isoformat()}
        for s, p, t in keys.itertuples(index=False)
    )
    return Finding("duplicates", "duplicate_hours", Severity.HARD, int(extra.sum()), items=items)


# --- implausible values --------------------------------------------------------------------


def _unverified_mask(df: pd.DataFrame) -> pd.Series:
    method = df["method_code"]
    no_method = method.isna() & (df["source"] != "airnow")  # only AirNow may lack a method
    unknown = method.notna() & ~method.isin(list(VERIFIED_METHODS))
    return (no_method | unknown).fillna(value=False).astype(bool)


def _unverified(df: pd.DataFrame, mask: pd.Series) -> Finding:
    if not mask.any():
        return Finding("implausible values", "unverified_method", Severity.HARD, 0)
    rows = df[mask].assign(method_code=df.loc[mask, "method_code"].fillna("none"))
    counts = rows.groupby(["site_id", "poc", "method_code"]).size().reset_index(name="n")
    items: tuple[Item, ...] = tuple(
        {"site_id": str(s), "poc": int(p), "method_code": str(m), "hours": int(n)}
        for s, p, m, n in counts.sort_values(["site_id", "poc", "method_code"]).itertuples(
            index=False
        )
    )
    n = int(mask.sum())
    return Finding(
        "implausible values", "unverified_method", Severity.HARD, n, excluded=n, items=items
    )


def _outside_range_mask(df: pd.DataFrame) -> pd.Series:
    method = df["method_code"].astype(object)
    lo_default, hi_default = AIRNOW_RANGE_UG_M3
    lo = method.map({c: m.min_value for c, m in VERIFIED_METHODS.items()}).astype(float)
    hi = method.map({c: m.max_value for c, m in VERIFIED_METHODS.items()}).astype(float)
    lo = lo.fillna(lo_default)
    hi = hi.fillna(hi_default)
    value = df["value_ug_m3"]
    inside = (value >= lo) & (value <= hi)  # a missing value is never inside
    return ~inside


def _hours_per_instrument(rows: pd.DataFrame) -> tuple[Item, ...]:
    if rows.empty:
        return ()
    counts = rows.groupby(["site_id", "poc"]).size().reset_index(name="n")
    return tuple(
        {"site_id": str(s), "poc": int(p), "hours": int(n)}
        for s, p, n in counts.sort_values(["site_id", "poc"]).itertuples(index=False)
    )


def _flat_lines(clean: pd.DataFrame) -> Finding:
    """Runs of identical values in consecutive hours at one instrument (plain arrays: fast)."""
    rows = clean.sort_values(KEY, kind="stable")
    n = len(rows)
    if n < FLATLINE_MIN_HOURS:
        return Finding("implausible values", "flat_line", Severity.WARN, 0)
    source = rows["source"].to_numpy(dtype=object)
    site = rows["site_id"].to_numpy(dtype=object)
    poc = rows["poc"].to_numpy()
    time = rows["time_utc"].dt.tz_convert(None).to_numpy()
    value = rows["value_ug_m3"].to_numpy()
    continues = np.zeros(n, dtype=bool)
    continues[1:] = (
        (source[1:] == source[:-1])
        & (site[1:] == site[:-1])
        & (poc[1:] == poc[:-1])
        & (np.diff(time) == np.timedelta64(1, "h"))
        & (value[1:] == value[:-1])
    )
    starts = np.flatnonzero(~continues)
    lengths = np.diff(np.append(starts, n))
    times = rows["time_utc"]
    found = sorted(
        (str(site[i]), int(poc[i]), times.iloc[i].isoformat(), int(h))
        for i, h in zip(starts, lengths, strict=True)
        if h >= FLATLINE_MIN_HOURS
    )
    items: tuple[Item, ...] = tuple(
        {"site_id": s_, "poc": p, "start_utc": t, "hours": h} for s_, p, t, h in found
    )
    return Finding("implausible values", "flat_line", Severity.WARN, len(items), items=items)


# --- coverage gaps -------------------------------------------------------------------------


def _month_starts_utc(start: datetime, end: datetime, tz: ZoneInfo) -> list[datetime]:
    """UTC starts of the local calendar months touching [start, end), plus the next one."""
    local = start.astimezone(tz).date().replace(day=1)
    out = []
    while True:
        first = local_day_window_utc(local, tz)[0]
        out.append(first)
        if first >= end:
            return out
        local = date(local.year + local.month // 12, local.month % 12 + 1, 1)


def _coverage(  # noqa: PLR0913  (the frames and the run's context)
    clean: pd.DataFrame,
    *,
    df: pd.DataFrame,
    window: Window,
    tz: ZoneInfo,
    sites: tuple[str, ...],
    coverage_from: CoverageFrom,
) -> list[Finding]:
    present = sorted(set(df["site_id"]))
    missing = sorted(set(sites) - set(present))
    gaps: list[Item] = []
    for site in present:
        start = window.start
        if coverage_from == "first_reading":
            first = df.loc[df["site_id"] == site, "time_utc"].min().to_pydatetime()
            start = max(start, first)
        if start >= window.end:
            continue
        hours = pd.DatetimeIndex(clean.loc[clean["site_id"] == site, "time_utc"]).unique()
        hours = hours.sort_values()
        bounds = _month_starts_utc(start, window.end, tz)
        for m_start, m_end in itertools.pairwise(bounds):
            seg_start, seg_end = max(m_start, start), min(m_end, window.end)
            expected = int((seg_end - seg_start) / timedelta(hours=1))
            if expected <= 0:
                continue
            got = int(hours.searchsorted(seg_end) - hours.searchsorted(seg_start))
            if got < COVERAGE_MIN_SHARE * expected:
                month = m_start.astimezone(tz).strftime("%Y-%m")
                gaps.append({"site_id": site, "month": month, "hours": got, "expected": expected})
    return [
        Finding("coverage gaps", "coverage_gap", Severity.WARN, len(gaps), items=tuple(gaps)),
        Finding(
            "coverage gaps",
            "site_missing",
            Severity.WARN,
            len(missing),
            items=tuple({"site_id": s} for s in missing),
        ),
    ]


# --- AirNow IDs (T5) -----------------------------------------------------------------------


def _airnow_ids(drops: Mapping[str, int]) -> list[Finding]:
    id_reasons = {"not_an_aqs_site_id", "unmatched_site"}
    others = {r: int(n) for r, n in sorted(drops.items()) if r not in id_reasons}
    other_items: tuple[Item, ...] = tuple({"reason": r, "rows": n} for r, n in others.items())
    return [
        Finding(
            "AirNow IDs",
            "airnow_not_aqs_id",
            Severity.INFO,
            int(drops.get("not_an_aqs_site_id", 0)),
        ),
        Finding(
            "AirNow IDs",
            "airnow_unmatched_site",
            Severity.INFO,
            int(drops.get("unmatched_site", 0)),
        ),
        Finding(
            "AirNow IDs",
            "airnow_rows_dropped",
            Severity.INFO,
            sum(others.values()),
            items=other_items,
        ),
    ]
