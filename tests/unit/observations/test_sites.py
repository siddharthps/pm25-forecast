"""The site list is D-030's, exactly (one home: observations/sites.py)."""

import csv
import io
import math
import re
from itertools import combinations
from pathlib import Path

from airwatch.observations.sites import (
    AGENCIES,
    SITE_AGENCY,
    SITE_COORDS,
    SITE_NAMES,
    TRAINING_SITES,
    VERIFIED_METHODS,
    unverified_methods,
)
from tests.unit.observations.airnow_fakes import text


def test_training_sites_are_exactly_d030s() -> None:
    decisions = (Path(__file__).resolve().parents[3] / "notes" / "DECISIONS.md").read_text(
        encoding="utf-8"
    )
    block = decisions[decisions.index("## D-030") :]
    block = block[: block.index("\n## ", 5)]
    ids = re.findall(r"\b04\d{7}\b", block)
    assert tuple(sorted(set(ids))) == TRAINING_SITES
    assert len(TRAINING_SITES) == 10


def test_verified_methods_are_continuous_fems_with_their_aqs_ranges() -> None:
    assert set(VERIFIED_METHODS) == {"170", "181", "182", "638"}
    assert all(
        m.recording_mode == "Continuous" and m.method_type == "FEM"
        for m in VERIFIED_METHODS.values()
    )
    assert VERIFIED_METHODS["181"].max_value == 5000.0


def test_unverified_method_codes_are_reported() -> None:
    assert unverified_methods(["170", "182", "999", None]) == {"999", "None"}
    assert unverified_methods(["170", "181", "182", "638"]) == set()


def test_every_training_site_has_a_name_and_an_agency() -> None:
    assert set(SITE_NAMES) == set(TRAINING_SITES)
    assert set(SITE_AGENCY) == set(TRAINING_SITES)
    assert AGENCIES == (
        "Maricopa County Air Quality Department",
        "Arizona Department of Environmental Quality",
        "Pinal County Air Quality Control District",
    )


def test_every_training_site_has_coordinates() -> None:
    assert set(SITE_COORDS) == set(TRAINING_SITES)
    assert all(
        isinstance(lat, float) and isinstance(lon, float) for lat, lon in SITE_COORDS.values()
    )


SAME_SITE_KM = 1.0


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111.0, (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0])))


def test_the_tolerance_is_under_half_the_closest_two_monitors() -> None:
    """So coordinates copied from the wrong monitor can never pass. AQS and AirNow publish
    positions up to 571 m apart for the same monitor (Glendale, 2026-11-23), hence 1 km."""
    closest = min(_km(SITE_COORDS[a], SITE_COORDS[b]) for a, b in combinations(SITE_COORDS, 2))
    assert closest > 2 * SAME_SITE_KM


def test_coordinates_agree_with_the_recorded_airnow_file() -> None:
    rows = {r["AQSID"]: r for r in csv.DictReader(io.StringIO(text()))}
    for site in TRAINING_SITES:
        airnow = (float(rows[site]["Latitude"]), float(rows[site]["Longitude"]))
        assert _km(SITE_COORDS[site], airnow) < SAME_SITE_KM, site


def test_names_and_agencies_match_the_recorded_airnow_file() -> None:
    rows = {r["AQSID"]: r for r in csv.DictReader(io.StringIO(text()))}
    for site in TRAINING_SITES:
        assert (SITE_NAMES[site], SITE_AGENCY[site]) == (
            rows[site]["SiteName"],
            rows[site]["DataSource"],
        )
