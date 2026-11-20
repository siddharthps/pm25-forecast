"""The public page keeps AirNow's terms and our own rules (#14, T7; D-025, D-028, D-036).

D-025's obligations, each checked on the page's text:

1. AirNow values are labelled "preliminary, not validated";
2. the forecast is "experimental model forecast, not an official air quality forecast", with a
   link to AirNow.gov;
3. the reporting agencies and EPA AirNow are credited, with a link to AirNow's partners page;
4. AQI colours come from EPA's table, in one place (airwatch.aqi via the JSON), never the site.

And: every planned data source is credited (owner, D-036); no outside scripts or styles; data
is never written as HTML; the page reads the public bucket named in the settings.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

from airwatch.aqi import CATEGORIES
from airwatch.config import Settings
from airwatch.observations.sites import AGENCIES

SITE = Path(__file__).resolve().parents[2] / "site"
HTML = (SITE / "index.html").read_text(encoding="utf-8")
JS = (SITE / "app.js").read_text(encoding="utf-8")
CSS = (SITE / "style.css").read_text(encoding="utf-8")
TEXT = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", HTML))  # the page's words, one line


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found.append((tag, dict(attrs)))


def tags(name: str) -> list[dict[str, str | None]]:
    parser = Tags()
    parser.feed(HTML)
    return [attrs for tag, attrs in parser.found if tag == name]


def test_every_airnow_section_is_labelled_preliminary() -> None:
    assert TEXT.count("Preliminary, not validated") == 3  # tomorrow, monitors, history


def test_the_forecast_is_labelled_experimental_with_a_link_to_airnow() -> None:
    assert "Experimental model forecast, not an official air quality forecast." in TEXT
    assert "https://www.airnow.gov/" in [a.get("href") for a in tags("a")]


def test_agencies_and_airnow_are_credited() -> None:
    for agency in AGENCIES:
        assert agency in TEXT, agency
    assert "U.S. EPA AirNow program" in TEXT
    assert "https://www.airnow.gov/partners/" in [a.get("href") for a in tags("a")]


def test_every_planned_source_is_credited() -> None:
    for source in ("EPA AirNow", "EPA Air Quality System (AQS)", "Open-Meteo", "CC BY 4.0"):
        assert source in TEXT, source
    assert "Copernicus Atmosphere Monitoring Service (CAMS)" in TEXT


def test_no_aqi_colour_is_typed_into_the_site() -> None:
    for category in CATEGORIES:
        for text in (HTML, JS, CSS):
            assert category.hex not in text.lower(), category.name


def test_the_page_loads_nothing_from_other_sites() -> None:
    sources = [s.get("src") or "" for s in tags("script")]
    styles = [s.get("href") or "" for s in tags("link") if s.get("rel") == "stylesheet"]
    assert sources == ["app.js"]
    assert styles == ["style.css"]
    csp = next(m for m in tags("meta") if m.get("http-equiv") == "Content-Security-Policy")
    policy = csp.get("content") or ""
    assert "script-src 'self'" in policy
    assert f"connect-src 'self' https://{Settings.model_fields['public_bucket'].default}" in policy


def test_data_is_never_written_as_html() -> None:
    for risky in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert risky not in JS, risky


def test_the_page_reads_the_public_bucket_from_the_settings() -> None:
    bucket = Settings.model_fields["public_bucket"].default
    assert f'DATA_BASE = "https://{bucket}.s3.amazonaws.com/"' in JS


def test_the_page_works_at_phone_width() -> None:
    viewport = next(m for m in tags("meta") if m.get("name") == "viewport")
    assert viewport.get("content") == "width=device-width, initial-scale=1"
    assert ".scroll" in CSS
    assert "overflow-x: auto" in CSS  # wide tables scroll inside their box, not the page
    assert tags("html")[0].get("lang") == "en"
