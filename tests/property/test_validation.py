"""Validation "must never" rules (#12, T12a), as properties:

- per-site work stays per-site: another site's rows, however bad, never change one site's
  findings or its usable rows;
- the result doesn't depend on row order;
- exclusion only removes rows, and every removed row is counted.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from airwatch.validation.checks import ValidationResult, Window, run_checks
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame

PHOENIX = ZoneInfo("America/Phoenix")
WINDOW = Window(START, START + timedelta(days=2))

values = st.lists(
    st.one_of(
        st.sampled_from([4.0, 4.0, 4.0, -3.0, -50.0, 2000.0, float("nan")]),
        st.floats(min_value=-20, max_value=1200, allow_nan=False),
    ),
    max_size=48,
)


def run(df: pd.DataFrame) -> ValidationResult:
    return run_checks(df, window=WINDOW, tz=PHOENIX, sites=(SITE_A, SITE_B))


def site_view(result: ValidationResult, site: str) -> tuple[object, ...]:
    """Everything the result says about one site."""
    items = tuple(
        (f.rule, tuple(i for i in f.items if i.get("site_id") == site)) for f in result.findings
    )
    rows = result.clean[result.clean["site_id"] == site].reset_index(drop=True)
    return items, rows.to_json(date_format="iso")


@given(a=values, b=values, b_hours=st.integers(min_value=1, max_value=3), dup=st.booleans())
def test_another_sites_rows_never_change_this_sites_result(
    a: list[float], b: list[float], b_hours: int, dup: bool
) -> None:
    only_a = frame(a)
    other = frame(b, site=SITE_B, step_h=b_hours, method="181")
    if dup and len(other):
        other = concat(other, other.iloc[[0]])
    assert site_view(run(only_a), SITE_A) == site_view(run(concat(only_a, other)), SITE_A)


@given(a=values, b=values, seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_row_order_never_changes_the_result(a: list[float], b: list[float], seed: int) -> None:
    df = concat(frame(a), frame(b, site=SITE_B, poc=3))
    shuffled = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    first, second = run(df), run(shuffled)
    assert first.findings == second.findings
    key = ["site_id", "poc", "time_utc"]
    assert (
        first.clean.sort_values(key)
        .reset_index(drop=True)
        .equals(second.clean.sort_values(key).reset_index(drop=True))
    )


@given(a=values, b=values)
def test_exclusion_only_removes_rows_and_counts_each_one(a: list[float], b: list[float]) -> None:
    df = concat(frame(a), frame(b, site=SITE_B, method="999"))
    result = run(df)
    excluded = sum(f.excluded for f in result.findings)
    assert len(result.clean) + excluded == len(df)
    merged = result.clean.merge(df, how="left", indicator=True)
    assert (merged["_merge"] == "both").all()
