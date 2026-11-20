"""PM2.5 AQI (#14, T7): every expected value comes from EPA's AQI Technical Assistance Document.

Source: *Technical Assistance Document for the Reporting of Daily Air Quality - the Air Quality
Index (AQI)*, EPA-403/B-26-003, May 2026 (read 2026-11-19):

- p. 13: truncate PM2.5 to 1 decimal place; Equation 1 (linear between breakpoints); round the
  index to the nearest integer; use the highest concentration among the reporting area's
  monitors;
- p. 14, Table 6: the PM2.5 24-hour breakpoints; footnote 4: above AQI 500, use Equation 1 with
  the AQI 500 concentration (325.4 ug/m3);
- p. 15: the worked example, PM2.5 35.9 -> 102;
- p. 4, Table 2: the standard AQI colours (required; ColorVision Assist colours are optional).
"""

import pytest

from airwatch.aqi import (
    CATEGORIES,
    aqi_category,
    pm25_aqi,
    round_index,
    text_color,
    truncate_pm25,
)


@pytest.mark.parametrize(
    ("raw", "truncated"),
    [(9.09, 9.0), (9.1, 9.1), (35.49, 35.4), (0.06, 0.0), (125.4999, 125.4), (12.0, 12.0)],
)
def test_pm25_is_truncated_not_rounded(raw: float, truncated: float) -> None:
    assert truncate_pm25(raw) == truncated


@pytest.mark.parametrize(
    ("pm25", "aqi"),
    [
        (0.0, 0),
        (9.0, 50),  # top of Good
        (9.1, 51),  # bottom of Moderate
        (35.4, 100),
        (35.5, 101),  # bottom of Unhealthy for Sensitive Groups
        (35.9, 102),  # the TAD's own worked example (p. 15)
        (55.4, 150),
        (55.5, 151),
        (125.4, 200),
        (125.5, 201),
        (225.4, 300),
        (225.5, 301),
        (325.4, 500),  # footnote 4: the AQI 500 concentration
        (425.4, 699),  # above 500: Equation 1 on the 301-500 segment, extended
        (9.09, 50),  # truncated to 9.0 first
    ],
)
def test_pm25_to_aqi_follows_table_6(pm25: float, aqi: int) -> None:
    assert pm25_aqi(pm25) == aqi


def test_half_points_round_up_as_in_the_tad() -> None:
    # The TAD's ozone example (p. 15) rounds 125.5 to 126.
    assert round_index(125.5) == 126
    assert round_index(125.4999) == 125


def test_a_negative_mean_reads_as_zero() -> None:
    # Daily means can dip just below zero (instrument noise, D-033). The TAD has no rule for
    # it; the AQI starts at 0, so it reads as 0 (D-036).
    assert pm25_aqi(-0.4) == 0


def test_the_six_categories_and_their_standard_colours() -> None:
    assert [(c.name, c.low, c.high, c.rgb) for c in CATEGORIES] == [
        ("Good", 0, 50, (0, 228, 0)),
        ("Moderate", 51, 100, (255, 255, 0)),
        ("Unhealthy for Sensitive Groups", 101, 150, (255, 126, 0)),
        ("Unhealthy", 151, 200, (255, 0, 0)),
        ("Very Unhealthy", 201, 300, (143, 63, 151)),
        ("Hazardous", 301, None, (126, 0, 35)),
    ]
    assert [c.hex for c in CATEGORIES] == [
        "#00e400",
        "#ffff00",
        "#ff7e00",
        "#ff0000",
        "#8f3f97",
        "#7e0023",
    ]


@pytest.mark.parametrize(
    ("aqi", "name"),
    [
        (0, "Good"),
        (50, "Good"),
        (51, "Moderate"),
        (101, "Unhealthy for Sensitive Groups"),
        (200, "Unhealthy"),
        (300, "Very Unhealthy"),
        (301, "Hazardous"),
        (699, "Hazardous"),
    ],
)
def test_each_index_falls_in_one_category(aqi: int, name: str) -> None:
    assert aqi_category(aqi).name == name


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Good", "#000000"),
        ("Moderate", "#000000"),
        ("Unhealthy for Sensitive Groups", "#000000"),
        ("Very Unhealthy", "#ffffff"),
        ("Hazardous", "#ffffff"),
    ],
)
def test_text_on_each_colour_uses_the_higher_contrast(name: str, text: str) -> None:
    category = next(c for c in CATEGORIES if c.name == name)
    assert text_color(category) == text
