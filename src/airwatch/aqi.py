"""The PM2.5 Air Quality Index: one home for EPA's rules (#14, T7; D-025, D-036).

Source: *Technical Assistance Document for the Reporting of Daily Air Quality - the Air Quality
Index (AQI)*, EPA-403/B-26-003, May 2026, read 2026-11-19:

- p. 13: truncate PM2.5 (ug/m3) to 1 decimal place; Equation 1 interpolates linearly between
  the two breakpoints that contain the concentration; round the index to the nearest integer.
  The reporting area's value uses the highest concentration among its monitors.
- p. 14, Table 6: the PM2.5 24-hour breakpoints below. Footnote 4: above AQI 500, use
  Equation 1 with the AQI 500 concentration, 325.4 ug/m3.
- p. 3-4, Tables 1-2: the category names and the standard colours (RGB), which are required.

Not in the TAD, and decided in D-036: a negative mean reads as AQI 0, and the text colour on
each category is whichever of black or white has the higher WCAG contrast.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

__all__ = [
    "BREAKPOINTS",
    "CATEGORIES",
    "TAD_SOURCE",
    "Category",
    "aqi_category",
    "aqi_scale",
    "pm25_aqi",
    "round_index",
    "text_color",
    "truncate_pm25",
]

TAD_SOURCE = "EPA-403/B-26-003 (May 2026)"

# (concentration low, concentration high, AQI low, AQI high), Table 6. The last row's top is the
# AQI 500 concentration from footnote 4; values above it extend that segment.
BREAKPOINTS: tuple[tuple[Decimal, Decimal, int, int], ...] = (
    (Decimal("0.0"), Decimal("9.0"), 0, 50),
    (Decimal("9.1"), Decimal("35.4"), 51, 100),
    (Decimal("35.5"), Decimal("55.4"), 101, 150),
    (Decimal("55.5"), Decimal("125.4"), 151, 200),
    (Decimal("125.5"), Decimal("225.4"), 201, 300),
    (Decimal("225.5"), Decimal("325.4"), 301, 500),
)


@dataclass(frozen=True)
class Category:
    name: str
    low: int
    high: int | None  # None: no upper bound (Hazardous is "301+")
    rgb: tuple[int, int, int]

    @property
    def hex(self) -> str:
        return "#{:02x}{:02x}{:02x}".format(*self.rgb)


# Tables 1 and 2: names, AQI ranges and the standard colours.
CATEGORIES: tuple[Category, ...] = (
    Category("Good", 0, 50, (0, 228, 0)),
    Category("Moderate", 51, 100, (255, 255, 0)),
    Category("Unhealthy for Sensitive Groups", 101, 150, (255, 126, 0)),
    Category("Unhealthy", 151, 200, (255, 0, 0)),
    Category("Very Unhealthy", 201, 300, (143, 63, 151)),
    Category("Hazardous", 301, None, (126, 0, 35)),
)


def truncate_pm25(pm25: float) -> float:
    """Truncate to 1 decimal place (p. 13), exactly: 9.09 -> 9.0, never 9.1."""
    return float(Decimal(repr(pm25)).quantize(Decimal("0.1"), rounding=ROUND_DOWN))


def round_index(value: float) -> int:
    """Round to the nearest integer, halves up (the TAD rounds 125.5 to 126, p. 15)."""
    return int(Decimal(repr(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pm25_aqi(pm25: float) -> int:
    """The AQI for a 24-hour PM2.5 concentration (Equation 1 on Table 6)."""
    c = Decimal(repr(truncate_pm25(max(pm25, 0.0))))
    # The first row whose top contains c; above the last top, the last row extends (footnote 4).
    # Truncation puts c on the 0.1 grid, where the rows leave no gaps.
    c_lo, c_hi, i_lo, i_hi = next((row for row in BREAKPOINTS if c <= row[1]), BREAKPOINTS[-1])
    index = (Decimal(i_hi - i_lo) / (c_hi - c_lo)) * (c - c_lo) + i_lo
    return round_index(float(index))


def aqi_category(aqi: int) -> Category:
    for category in CATEGORIES:
        if category.high is None or aqi <= category.high:
            return category
    raise AssertionError("unreachable")  # pragma: no cover


def aqi_scale() -> list[dict[str, str | int]]:
    """The six categories for the page's scale band. Hazardous is drawn up to AQI 500, the top
    of Table 6 (footnote 4); higher values sit at the band's end."""
    top = BREAKPOINTS[-1][3]
    return [
        {
            "name": c.name,
            "low": c.low,
            "high": c.high if c.high is not None else top,
            "color": c.hex,
            "text_color": text_color(c),
        }
        for c in CATEGORIES
    ]


def _luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2 relative luminance."""

    def channel(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4  # noqa: PLR2004

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_color(category: Category) -> str:
    """Black or white, whichever contrasts more with the category's colour."""
    lum = _luminance(category.rgb)
    on_black = (lum + 0.05) / 0.05
    on_white = 1.05 / (lum + 0.05)
    return "#000000" if on_black >= on_white else "#ffffff"
