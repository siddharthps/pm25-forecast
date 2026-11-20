"""The city's monitors: one home for the site list (D-030). A test checks it against D-030."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = [
    "AGENCIES",
    "SITE_AGENCY",
    "SITE_NAMES",
    "TRAINING_SITES",
    "VERIFIED_METHODS",
    "Method",
    "unverified_methods",
]

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


SITE_NAMES = {
    "040130019": "West Phoenix",
    "040131003": "Mesa - Brooks Reservoir",
    "040131004": "North Phoenix",
    "040132001": "Glendale Community College",
    "040134003": "South Phoenix",
    "040134005": "Tempe",
    "040139812": "Durango Complex",
    "040139997": "Phoenix JLG Supersite",
    "040210001": "Casa Grande Downtown",
    "040213015": "Hidden Valley",
}
_MARICOPA = "Maricopa County Air Quality Department"
_ADEQ = "Arizona Department of Environmental Quality"
_PINAL = "Pinal County Air Quality Control District"
SITE_AGENCY = {
    "040130019": _MARICOPA,
    "040131003": _MARICOPA,
    "040131004": _MARICOPA,
    "040132001": _MARICOPA,
    "040134003": _MARICOPA,
    "040134005": _MARICOPA,
    "040139812": _MARICOPA,
    "040139997": _ADEQ,
    "040210001": _PINAL,
    "040213015": _PINAL,
}
AGENCIES = tuple(dict.fromkeys(SITE_AGENCY.values()))


@dataclass(frozen=True)
class Method:
    """An AQS method code for parameter 88101, as AQS's method table describes it."""

    instrument: str
    recording_mode: str
    method_type: str
    epa_designation: str
    min_value: float
    max_value: float


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
