"""Data-quality checks on hourly PM2.5 (#12, T12a; #20, T12b; D-021, D-033, D-054).

Each check covers one *problem class*, never a single case, and reports every rule it applies,
at zero too, so a report shows that a check ran. Severities:

- **hard:** the data can't be trusted as a whole (a pipeline or source fault). The run stops:
  `ValidationResult.raise_if_failed` raises, and the daily flow writes no record (T6).
- **warn:** a real problem, limited to some rows or site-months. Reported; the run goes on.
- **info:** counted for the record, not a problem in itself.

Rules (D-033; T12b's from D-054):

| Class | Rule | Severity | Rows |
| --- | --- | --- | --- |
| wrong entity | `site_not_listed`: a row from a site that isn't listed | hard | excluded |
| dates | `future_hour`: an hour that hasn't ended at run time | hard | excluded |
| duplicates | `duplicate_hours`: a (source, site, POC, hour) seen twice | hard | kept |
| implausible values | `unverified_method`: no sourced range (D-032) | hard | excluded |
| implausible values | `outside_valid_range`: outside AQS's method range | warn | excluded |
| implausible values | `negative_in_range`: below zero, in range (noise) | info | kept |
| implausible values | `flat_line`: 12+ identical hours in a row, one instrument | warn | kept |
| coverage gaps | `coverage_gap`: a local site-month < 75% usable hours | warn | - |
| coverage gaps | `site_missing`: a listed site with no rows at all | warn | - |
| key reuse | `method_changed`: an instrument's method changes (each change) | info | kept |
| AirNow IDs | `airnow_not_aqs_id`, `airnow_unmatched_site`, `airnow_rows_dropped` | info | - |
| units | `unit_mismatch`: AirNow rows dropped for a unit other than µg/m³ | warn | - |

With a `reference` (`airwatch.validation.reference`; the report only):

| Class | Rule | Severity | Rows |
| --- | --- | --- | --- |
| wrong entity | `site_outside_city`: AQS places a site outside the CBSA, or lacks it | hard | - |
| key reuse | `site_moved`: AQS, AirNow and our coordinates > 1 km apart | warn | - |
| key reuse | `airnow_method_stale`: AQS's current instrument isn't `AIRNOW_METHOD`'s | warn | - |
| dates | `outside_active_period`: an AQS hour outside its monitor's open dates | warn | excluded |

AirNow rows carry no method: each is judged against its site's instrument (`AIRNOW_METHOD`),
and a site without one is unverified. AQS units are checked when AQS is read
(`airwatch.observations.aqs`), so a wrong unit never reaches this module.

Raw data is never changed (D-031): `clean` is a filtered copy. Items name sites, instruments,
times and counts, never a measurement, so reports can be logged and shared.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from airwatch.errors import ReportableError
from airwatch.observations.schema import validate_hourly
from airwatch.observations.sites import AIRNOW_METHOD, SITE_COORDS, VERIFIED_METHODS
from airwatch.timeutil import ensure_utc, local_day_window_utc
from airwatch.validation.reference import MAX_SITE_OFFSET_KM, Monitor, Reference, distance_km

__all__ = [
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

FLATLINE_MIN_HOURS = 12
COVERAGE_MIN_SHARE = 0.75
_HOUR = pd.Timedelta(hours=1)

KEY = ["source", "site_id", "poc", "time_utc"]

CoverageFrom = Literal["window", "first_reading"]
Item = dict[str, str | int | float]


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


class ValidationFailedError(ReportableError):
    """At least one hard rule caught something. The message names rules and counts only."""


@dataclass(frozen=True, eq=False)
class ValidationResult:
    findings: tuple[Finding, ...]
    clean: pd.DataFrame
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
    now: datetime,
    coverage_from: CoverageFrom = "window",
    ingest_drops: Mapping[str, int] | None = None,
    reference: Reference | None = None,
) -> ValidationResult:
    """Every check on an hourly frame (the shared schema). Raises ValueError on a bad schema.

    `now` is the run time: an hour that hasn't ended by then is refused.
    `coverage_from="window"` expects each site for the whole window (the daily flow);
    `"first_reading"` starts each site at its first row (history, where monitors began at
    different times). `ingest_drops` are the AirNow reader's drop counts, when there are any.
    `reference` adds the rules that need AQS's monitor records and AirNow's site list.

    Each excluded row is counted by the first rule that excludes it, in the order: unlisted
    site, future hour, unverified method, outside the valid range, outside the active period.
    """
    validate_hourly(df)
    run_at = ensure_utc(now)
    df = df.reset_index(drop=True)
    listed = tuple(sites)

    unlisted = _flag(~df["site_id"].isin(listed))
    future = ~unlisted & _flag(df["time_utc"] + _HOUR > pd.Timestamp(run_at))
    unverified = ~unlisted & ~future & _unverified_mask(df)
    outside = ~unlisted & ~future & ~unverified & _outside_range_mask(df)
    removed = unlisted | future | unverified | outside
    inactive = pd.Series(False, index=df.index)
    if reference is not None:
        inactive = ~removed & _inactive_mask(df, reference.monitors, tz)
    clean = df[~(removed | inactive)].reset_index(drop=True)
    in_list = df[~unlisted]

    n_unlisted, n_future = int(unlisted.sum()), int(future.sum())
    findings = [
        Finding(
            "wrong entity",
            "site_not_listed",
            Severity.HARD,
            n_unlisted,
            excluded=n_unlisted,
            items=_hours_per_site(df[unlisted]),
        ),
        Finding(
            "dates",
            "future_hour",
            Severity.HARD,
            n_future,
            excluded=n_future,
            items=_hours_per_instrument(df[future]),
        ),
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
        _method_changes(in_list),
        *_coverage(
            clean, df=in_list, window=window, tz=tz, sites=listed, coverage_from=coverage_from
        ),
    ]
    if reference is not None:
        findings += _reference_rules(
            reference, listed, today=run_at.astimezone(tz).date(), df=df, inactive=inactive
        )
    if ingest_drops is not None:
        findings.extend(_airnow_ids(ingest_drops))
    return ValidationResult(tuple(findings), clean, len(df))


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


def _flag(mask: pd.Series) -> pd.Series:
    """A plain bool mask (comparisons on string columns give pandas' nullable booleans)."""
    return mask.fillna(value=False).astype(bool)


def _effective_method(df: pd.DataFrame) -> pd.Series:
    """Each row's method: its own, or for AirNow (none given) its site's `AIRNOW_METHOD`."""
    own = df["method_code"].astype(object)
    airnow = _flag((df["source"] == "airnow") & df["method_code"].isna())
    return own.where(~airnow, df["site_id"].astype(object).map(AIRNOW_METHOD))


def _unverified_mask(df: pd.DataFrame) -> pd.Series:
    method = _effective_method(df)
    return _flag(method.isna() | ~method.isin(list(VERIFIED_METHODS)))


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
    method = _effective_method(df)
    lo = method.map({c: m.min_value for c, m in VERIFIED_METHODS.items()}).astype(float)
    hi = method.map({c: m.max_value for c, m in VERIFIED_METHODS.items()}).astype(float)
    value = df["value_ug_m3"]
    inside = (value >= lo) & (value <= hi)
    return _flag(~inside)


def _hours_per_site(rows: pd.DataFrame) -> tuple[Item, ...]:
    counts = rows.groupby("site_id").size()
    return tuple({"site_id": str(s), "hours": int(n)} for s, n in sorted(counts.items()))


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


def _method_changes(df: pd.DataFrame) -> Finding:
    """Each change of method at one AQS instrument, in time order (AirNow gives no method)."""
    rows = df[_flag(df["source"] != "airnow")].sort_values(
        ["site_id", "poc", "time_utc", "method_code"], kind="stable"
    )
    site = rows["site_id"].to_numpy(dtype=object)
    poc = rows["poc"].to_numpy()
    method = rows["method_code"].fillna("none").to_numpy(dtype=object)
    times = rows["time_utc"]
    changed = (site[1:] == site[:-1]) & (poc[1:] == poc[:-1]) & (method[1:] != method[:-1])
    items: tuple[Item, ...] = tuple(
        {
            "site_id": str(site[i + 1]),
            "poc": int(poc[i + 1]),
            "time_utc": times.iloc[i + 1].isoformat(),
            "from": str(method[i]),
            "to": str(method[i + 1]),
        }
        for i in np.flatnonzero(changed)
    )
    return Finding("key reuse", "method_changed", Severity.INFO, len(items), items=items)


def _inactive_mask(df: pd.DataFrame, monitors: Sequence[Monitor], tz: ZoneInfo) -> pd.Series:
    """AQS rows on a local day outside every open period of their (site, POC) monitor."""
    periods: defaultdict[tuple[str, int], list[tuple[date, date | None]]] = defaultdict(list)
    for m in monitors:
        periods[(m.site_id, m.poc)].append((m.open_date, m.close_date))
    out = pd.Series(False, index=df.index)
    aqs = df[_flag(df["source"] != "airnow")]
    if aqs.empty:
        return out
    day = aqs["time_utc"].dt.tz_convert(tz).dt.date
    for _, group in aqs.groupby(["site_id", "poc"]):
        days = day.loc[group.index]
        key = (str(group["site_id"].iloc[0]), int(group["poc"].iloc[0]))
        active = pd.Series(False, index=days.index)
        for opened, closed in periods.get(key, []):
            active |= (days >= opened) & (days <= (closed or date.max))
        out.loc[group.index] = ~active
    return out


def _reference_rules(
    reference: Reference,
    sites: tuple[str, ...],
    *,
    today: date,
    df: pd.DataFrame,
    inactive: pd.Series,
) -> list[Finding]:
    by_site: defaultdict[str, list[Monitor]] = defaultdict(list)
    for m in reference.monitors:
        by_site[m.site_id].append(m)
    outside_city: list[Item] = []
    moved: list[Item] = []
    stale: list[Item] = []
    for site in sorted(sites):
        monitors = by_site.get(site, [])
        cbsas = sorted({m.cbsa_code or "none" for m in monitors} - {reference.city_cbsa})
        if not monitors:
            outside_city.append({"site_id": site, "reason": "no_aqs_record"})
        elif cbsas:
            outside_city.append({"site_id": site, "reason": "cbsa " + ",".join(cbsas)})
        points = [(m.lat, m.lon) for m in monitors]
        points += list(reference.airnow_coords.get(site, ()))
        if site in SITE_COORDS:
            points.append(SITE_COORDS[site])
        km = max((distance_km(a, b) for a, b in itertools.combinations(points, 2)), default=0.0)
        if km > MAX_SITE_OFFSET_KM:
            moved.append({"site_id": site, "km": round(km, 2)})
        current = sorted(
            {
                m.last_method_code
                for m in monitors
                if m.last_method_code in VERIFIED_METHODS
                and (m.close_date is None or m.close_date >= today)
            }
        )
        listed = AIRNOW_METHOD.get(site)
        if current != [listed]:
            stale.append(
                {"site_id": site, "listed": listed or "none", "aqs": ",".join(current) or "none"}
            )
    n_inactive = int(inactive.sum())
    return [
        Finding(
            "wrong entity",
            "site_outside_city",
            Severity.HARD,
            len(outside_city),
            items=tuple(outside_city),
        ),
        Finding("key reuse", "site_moved", Severity.WARN, len(moved), items=tuple(moved)),
        Finding("key reuse", "airnow_method_stale", Severity.WARN, len(stale), items=tuple(stale)),
        Finding(
            "dates",
            "outside_active_period",
            Severity.WARN,
            n_inactive,
            excluded=n_inactive,
            items=_hours_per_instrument(df[inactive]),
        ),
    ]


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


def _airnow_ids(drops: Mapping[str, int]) -> list[Finding]:
    id_reasons = {"not_an_aqs_site_id", "unmatched_site", "unit_not_ug_m3"}
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
        Finding("units", "unit_mismatch", Severity.WARN, int(drops.get("unit_not_ug_m3", 0))),
    ]
