"""The city's monitors: one home for the site list (D-030). A test checks it against D-030."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["TRAINING_SITES", "VERIFIED_METHODS", "Method", "unverified_methods"]

# D-030: Phoenix's 10 qualifying monitors (AQS site IDs = AirNow AQSIDs), chosen by the frozen
# D-006 check. Maricopa County (013): 8; Pinal County (021): 2.
TRAINING_SITES = (
    "040130019",
    "040131003",
    "040131004",
    "040132001",
    "040134003",
    "040134005",
    "040139812",
    "040139997",
    "040210001",
    "040213015",
)


@dataclass(frozen=True)
class Method:
    """An AQS method code for parameter 88101, as AQS's method table describes it."""

    instrument: str
    recording_mode: str
    method_type: str
    epa_designation: str
    min_value: float
    max_value: float


# D-032 (settles OQ-8): the methods of the training sites' hourly instruments, checked against
# AQS's methods_all.html (parameter 88101) on 2026-11-19. All are continuous FEMs: the same kind
# of instrument AirNow reports. Min/max are AQS's valid ranges (the sourced bounds for T12).
VERIFIED_METHODS: dict[str, Method] = {
    "170": Method("Met One BAM-1020 w/VSCC", "Continuous", "FEM", "EQPM-0308-170", -10.0, 975.0),
    "181": Method(
        "Thermo TEOM 1400 FDMS or 1405 8500C FDMS w/VSCC",
        "Continuous",
        "FEM",
        "EQPM-0609-181",
        -10.0,
        5000.0,
    ),
    "182": Method(
        "Thermo TEOM 1405-DF Dichotomous FDMS", "Continuous", "FEM", "EQPM-0609-182", -10.0, 5000.0
    ),
    "638": Method(
        "Teledyne T640X at 16.67 LPM w/Network Data Alignment",
        "Continuous",
        "FEM",
        "EQPM-0516-238",
        0.0,
        10000.0,
    ),
}


def unverified_methods(codes: Iterable[object]) -> set[str]:
    """Method codes not in VERIFIED_METHODS: a new instrument type to check before training."""
    return {str(c) for c in codes} - VERIFIED_METHODS.keys()
