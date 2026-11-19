"""The city's monitors: one home for the site list (D-030). A test checks it against D-030."""

from __future__ import annotations

__all__ = ["TRAINING_SITES"]

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
