"""The site list is D-030's, exactly (one home: observations/sites.py)."""

import re
from pathlib import Path

from airwatch.observations.sites import TRAINING_SITES, VERIFIED_METHODS, unverified_methods


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
    # D-032: checked against AQS's methods_all.html (parameter 88101), 2026-11-19.
    assert set(VERIFIED_METHODS) == {"170", "181", "182", "638"}
    assert all(
        m.recording_mode == "Continuous" and m.method_type == "FEM"
        for m in VERIFIED_METHODS.values()
    )
    assert VERIFIED_METHODS["181"].max_value == 5000.0  # the 2014 fireworks hour's method


def test_unverified_method_codes_are_reported() -> None:
    assert unverified_methods(["170", "182", "999", None]) == {"999", "None"}
    assert unverified_methods(["170", "181", "182", "638"]) == set()


def test_every_training_site_has_a_name_and_an_agency() -> None:
    from airwatch.observations.sites import AGENCIES, SITE_AGENCY, SITE_NAMES  # noqa: PLC0415

    assert set(SITE_NAMES) == set(TRAINING_SITES)
    assert set(SITE_AGENCY) == set(TRAINING_SITES)
    assert AGENCIES == (
        "Maricopa County Air Quality Department",
        "Arizona Department of Environmental Quality",
        "Pinal County Air Quality Control District",
    )


def test_names_and_agencies_match_the_recorded_airnow_file() -> None:
    import csv  # noqa: PLC0415
    import io  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from airwatch.observations.sites import SITE_AGENCY, SITE_NAMES  # noqa: PLC0415

    fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "airnow" / "HourlyAQObs_2026111901.dat"
    )
    text = fixture.read_text(encoding="utf-8")
    rows = {r["AQSID"]: r for r in csv.DictReader(io.StringIO(text))}
    for site in TRAINING_SITES:
        assert (SITE_NAMES[site], SITE_AGENCY[site]) == (
            rows[site]["SiteName"],
            rows[site]["DataSource"],
        )
