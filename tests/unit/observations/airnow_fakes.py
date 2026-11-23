"""The recorded AirNow hourly file (its one home), and a fake file server built from it.

`PUBLISHED` is the recording's own `Last-Modified` time: AirNow published the 01:00 UTC hour at
04:21:33 UTC.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "airnow" / "HourlyAQObs_2026111901.dat"
PUBLISHED = datetime(2026, 11, 19, 4, 21, 33, tzinfo=UTC)


def text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def file_for_hour(hour_utc: datetime) -> str:
    """The recorded file, relabelled as the hour `hour_utc` (as AirNow would publish it)."""
    rows = list(csv.DictReader(io.StringIO(text())))
    for r in rows:
        r["ValidDate"], r["ValidTime"] = f"{hour_utc:%m/%d/%Y}", f"{hour_utc:%H}:00"
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def day_transport(missing: frozenset[int] = frozenset()) -> httpx.MockTransport:
    """Serves every hourly file, published 3 hours after its hour; `missing` hours are 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        stamp = request.url.path.rsplit("_", 1)[1].removesuffix(".dat")
        hour = datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=UTC)
        if hour.hour in missing:
            return httpx.Response(404)
        published = hour + timedelta(hours=3)
        return httpx.Response(
            200,
            text=file_for_hour(hour),
            headers={"Last-Modified": published.strftime("%a, %d %b %Y %H:%M:%S GMT")},
        )

    return httpx.MockTransport(handler)
