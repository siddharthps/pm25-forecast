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
