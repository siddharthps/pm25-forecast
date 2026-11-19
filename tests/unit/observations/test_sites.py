"""The site list is D-030's, exactly (one home: observations/sites.py)."""

import re
from pathlib import Path

from airwatch.observations.sites import TRAINING_SITES


def test_training_sites_are_exactly_d030s() -> None:
    decisions = (Path(__file__).resolve().parents[3] / "notes" / "DECISIONS.md").read_text(
        encoding="utf-8"
    )
    block = decisions[decisions.index("## D-030") :]
    block = block[: block.index("\n## ", 5)]
    ids = re.findall(r"\b04\d{7}\b", block)
    assert tuple(sorted(set(ids))) == TRAINING_SITES
    assert len(TRAINING_SITES) == 10
