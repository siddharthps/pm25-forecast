"""Validation "must never" rules (#12, T12a; #20, T12b), as properties:

- per-site work stays per-site: another site's rows, however bad, never change one site's
  findings or its usable rows;
- the result doesn't depend on row order;
- exclusion only removes rows, and every removed row is counted once, by the first rule.

Every run carries a reference (one monitor per site, opening on a drawn day) and a drawn run
time, so T12b's unlisted sites, future hours and inactive monitors are drawn alongside T12a's
duplicates, unverified methods and out-of-range values.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from airwatch.observations.sites import SITE_COORDS
from airwatch.validation.checks import ValidationResult, Window, run_checks
from airwatch.validation.reference import Monitor, Reference
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame

PHOENIX = ZoneInfo("America/Phoenix")
WINDOW = Window(START, START + timedelta(days=2))
UNLISTED = "040139998"

values = st.lists(
    st.one_of(
        st.sampled_from([4.0, 4.0, 4.0, -3.0, -50.0, 2000.0, float("nan")]),
        st.floats(min_value=-20, max_value=1200, allow_nan=False),
    ),
    max_size=48,
)
run_hours = st.integers(min_value=0, max_value=60)
open_days = st.integers(min_value=-1, max_value=2)


def reference(opened_day: int) -> Reference:
    opened = (START + timedelta(days=opened_day)).astimezone(PHOENIX).date()
    return Reference(
        monitors=(
            Monitor(SITE_A, 1, opened, None, *SITE_COORDS[SITE_A], "38060", "170"),
            Monitor(SITE_B, 3, date(2010, 1, 1), None, *SITE_COORDS[SITE_B], "38060", "182"),
        ),
        airnow_coords={},
        city_cbsa="38060",
    )


def run(df: pd.DataFrame, now_h: int, opened_day: int) -> ValidationResult:
    return run_checks(
        df,
        window=WINDOW,
        tz=PHOENIX,
        sites=(SITE_A, SITE_B),
        now=START + timedelta(hours=now_h),
        reference=reference(opened_day),
    )


def site_view(result: ValidationResult, site: str) -> tuple[object, ...]:
    """Everything the result says about one site."""
    items = tuple(
        (f.rule, tuple(i for i in f.items if i.get("site_id") == site)) for f in result.findings
    )
    rows = result.clean[result.clean["site_id"] == site].reset_index(drop=True)
    return items, rows.to_json(date_format="iso")


@given(
    a=values,
    b=values,
    b_hours=st.integers(min_value=1, max_value=3),
    dup=st.booleans(),
    now_h=run_hours,
    opened_day=open_days,
)
def test_another_sites_rows_never_change_this_sites_result(  # noqa: PLR0913
    *, a: list[float], b: list[float], b_hours: int, dup: bool, now_h: int, opened_day: int
) -> None:
    only_a = frame(a)
    other = frame(b, site=SITE_B, step_h=b_hours, method="181")
    if dup and len(other):
        other = concat(other, other.iloc[[0]])
    alone = run(only_a, now_h, opened_day)
    together = run(concat(only_a, other), now_h, opened_day)
    assert site_view(alone, SITE_A) == site_view(together, SITE_A)


@given(
    a=values,
    b=values,
    c=values,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    now_h=run_hours,
    opened_day=open_days,
)
def test_row_order_never_changes_the_result(  # noqa: PLR0913
    *, a: list[float], b: list[float], c: list[float], seed: int, now_h: int, opened_day: int
) -> None:
    df = concat(frame(a), frame(b, site=SITE_B, poc=3), frame(c, site=UNLISTED))
    shuffled = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    first, second = run(df, now_h, opened_day), run(shuffled, now_h, opened_day)
    assert first.findings == second.findings
    key = ["site_id", "poc", "time_utc"]
    assert (
        first.clean.sort_values(key)
        .reset_index(drop=True)
        .equals(second.clean.sort_values(key).reset_index(drop=True))
    )


@given(a=values, b=values, c=values, now_h=run_hours, opened_day=open_days)
def test_exclusion_only_removes_rows_and_counts_each_one(
    *, a: list[float], b: list[float], c: list[float], now_h: int, opened_day: int
) -> None:
    df = concat(
        frame(a),
        frame(b, site=SITE_B, poc=3, method="999"),
        frame(c, site=UNLISTED, method="999"),
    )
    result = run(df, now_h, opened_day)
    excluded = sum(f.excluded for f in result.findings)
    assert len(result.clean) + excluded == len(df)
    merged = result.clean.merge(df, how="left", indicator=True)
    assert (merged["_merge"] == "both").all()
