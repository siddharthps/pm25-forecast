"""AQS bulk history download (#11, T13): one Parquet file per site-year in private S3.

- **Durable record:** a manifest in S3 (`MANIFEST_KEY`) lists every finished part, with its rows,
  sha256 and fetch time. "Done" comes from the manifest, never from local files.
- **Order of writes:** the data file first, then its manifest entry. A crash in between leaves an
  unrecorded file, which the next run fetches again and overwrites (same key, so no duplicates).
- **Resumable and idempotent:** a rerun fetches only parts missing from the manifest, plus parts
  not yet final. A year is final once it has ended. The current year is refreshed on every run.
- **Quiet:** logs say which part and how many rows, never a measurement or a credential.
- **Single writer:** one run at a time (the manifest is read, updated and written back).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from airwatch.observations.aqs import parse_sample_rows
from airwatch.observations.schema import count_outside_crude_range
from airwatch.storage import S3Store

__all__ = [
    "FIRST_YEAR",
    "MANIFEST_KEY",
    "PREFIX",
    "Part",
    "Summary",
    "load_manifest",
    "plan_parts",
    "run_download",
]

log = logging.getLogger(__name__)

FIRST_YEAR = 2009
PREFIX = "raw/aqs/hourly/"
MANIFEST_KEY = PREFIX + "manifest.json"


@dataclass(frozen=True, order=True)
class Part:
    """One site-year of hourly data."""

    site_id: str
    year: int

    @property
    def key(self) -> str:
        return f"{PREFIX}site={self.site_id}/year={self.year}.parquet"


@dataclass(frozen=True)
class Summary:
    fetched: int
    rows: int


def plan_parts(
    sites: Iterable[str],
    *,
    first_year: int,
    today: date,
    manifest_parts: Mapping[str, Mapping[str, Any]],
) -> list[Part]:
    """Parts to fetch: those missing from the manifest, or recorded but not yet final."""
    todo = []
    for site in sites:
        for year in range(first_year, today.year + 1):
            part = Part(site, year)
            entry = manifest_parts.get(part.key)
            if entry is None or not entry.get("final", False):
                todo.append(part)
    return sorted(todo)


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow")
    return buf.getvalue()


def load_manifest(store: S3Store) -> dict[str, Any]:
    raw = store.get(MANIFEST_KEY)
    if raw is None:
        return {"version": 1, "parts": {}}
    manifest: dict[str, Any] = json.loads(raw)
    return manifest


def run_download(  # noqa: PLR0913  (each argument is an injected edge: store, fetch, clock)
    store: S3Store,
    fetch: Callable[[str, int], list[dict[str, Any]]],
    sites: Iterable[str],
    *,
    first_year: int,
    today: date,
    now: Callable[[], datetime],
) -> Summary:
    """Fetch every missing or unfinished part, writing data before its manifest entry."""
    manifest = load_manifest(store)
    parts = plan_parts(sites, first_year=first_year, today=today, manifest_parts=manifest["parts"])
    log.info("%d part(s) to fetch", len(parts))
    total_rows = 0
    for i, part in enumerate(parts, start=1):
        df = parse_sample_rows(fetch(part.site_id, part.year))
        flagged = count_outside_crude_range(df)
        data = _parquet_bytes(df)
        store.put(part.key, data)
        manifest["parts"][part.key] = {
            "key": part.key,
            "site_id": part.site_id,
            "year": part.year,
            "rows": len(df),
            "outside_crude_range": flagged,
            "sha256": hashlib.sha256(data).hexdigest(),
            "fetched_at_utc": now().isoformat(),
            "final": part.year < today.year,
        }
        store.put(MANIFEST_KEY, json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
        total_rows += len(df)
        log.info(
            "[%d/%d] site %s, %d: %d rows, %d outside crude range",
            i,
            len(parts),
            part.site_id,
            part.year,
            len(df),
            flagged,
        )
    return Summary(fetched=len(parts), rows=total_rows)
