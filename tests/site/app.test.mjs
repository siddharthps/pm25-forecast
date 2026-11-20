// The page's pure functions (#14, T7), run with Node's built-in test runner:
//   node --test tests/site/
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  colorFor,
  DATA_BASE,
  dataBase,
  forecastHeading,
  formatDate,
  formatIssued,
  HISTORY_DAYS,
  historyRows,
  LOAD_ERROR,
  monitorView,
  scalePosition,
  sortByConcentration,
} from "../../site/app.js";

// The table latest.json carries (from airwatch.aqi; the page itself holds no colours).
const SCALE = [
  { name: "Good", low: 0, high: 50, color: "#00e400", text_color: "#000000" },
  { name: "Moderate", low: 51, high: 100, color: "#ffff00", text_color: "#000000" },
  {
    name: "Unhealthy for Sensitive Groups",
    low: 101,
    high: 150,
    color: "#ff7e00",
    text_color: "#000000",
  },
  { name: "Unhealthy", low: 151, high: 200, color: "#ff0000", text_color: "#000000" },
  { name: "Very Unhealthy", low: 201, high: 300, color: "#8f3f97", text_color: "#ffffff" },
  { name: "Hazardous", low: 301, high: 500, color: "#7e0023", text_color: "#ffffff" },
];

test("data comes from the public bucket by default", () => {
  assert.equal(dataBase(""), DATA_BASE);
  assert.equal(DATA_BASE, "https://pm25-forecast-public-65bc08.s3.amazonaws.com/");
});

test("a local preview may read a same-site folder", () => {
  assert.equal(dataBase("?data=./preview"), "./preview/");
  assert.equal(dataBase("?data=/preview/"), "/preview/");
});

test("a preview can never point the page at another site", () => {
  for (const bad of [
    "?data=https://evil.example/",
    "?data=//evil.example/",
    "?data=../outside/",
    "?data=javascript:alert(1)",
  ]) {
    assert.equal(dataBase(bad), DATA_BASE, bad);
  }
});

test("dates are calendar dates, never shifted by a time zone", () => {
  assert.equal(formatDate("2026-11-21"), "Saturday, 21 November 2026");
  assert.equal(formatDate("2026-03-08"), "Sunday, 8 March 2026"); // a US DST change day
});

test("the issue time is shown on Chicago's clock", () => {
  assert.equal(formatIssued("2026-11-20T12:00:00+00:00"), "20 Nov 2026, 06:00 Chicago time");
  assert.equal(formatIssued("2026-07-01T11:00:00+00:00"), "1 Jul 2026, 06:00 Chicago time");
});

test("a monitor's values are shown as given, with one decimal", () => {
  const view = monitorView({
    site_id: "040130019",
    site_name: "West Phoenix",
    pm25_ug_m3: 8,
    aqi: 44,
    category: "Good",
    color: "#00e400",
    text_color: "#000000",
  });
  assert.deepEqual(view, {
    name: "West Phoenix",
    pm25: "8.0 µg/m³",
    aqi: "44",
    category: "Good",
    color: "#00e400",
    textColor: "#000000",
  });
});

test("history shows the newest days first, up to the limit", () => {
  const days = Array.from({ length: 20 }, (_, i) => ({
    forecast_date: `2026-11-${String(30 - i).padStart(2, "0")}`,
    city: { aqi: i, category: "Good" },
  }));
  const rows = historyRows({ days });
  assert.equal(HISTORY_DAYS, 14); // two weeks on the page
  assert.equal(rows.length, 14);
  assert.equal(rows[0].date, "Monday, 30 November 2026");
  assert.equal(rows[0].aqi, "0");
});

test("the heading names the forecast day, never 'tomorrow'", () => {
  assert.equal(forecastHeading("2026-11-21"), "Forecast for Saturday, 21 November 2026");
});

test("each category takes an equal share of the band", () => {
  assert.equal(scalePosition(0, SCALE), 0);
  assert.equal(scalePosition(50, SCALE), 100 / 6); // top of Good: the end of segment 1
  assert.equal(scalePosition(51, SCALE), 100 / 6); // bottom of Moderate: its start
  assert.ok(Math.abs(scalePosition(52, SCALE) - (1 + 1 / 49) * (100 / 6)) < 1e-9);
  assert.equal(scalePosition(500, SCALE), 100);
});

test("values beyond the band stay on it", () => {
  assert.equal(scalePosition(699, SCALE), 100); // above 500
  assert.equal(scalePosition(-3, SCALE), 0);
});

test("monitors are listed by concentration, highest first, as the city summary picks", () => {
  // Two monitors can share an AQI (9.5 and 9.9 both give 52); the higher concentration leads,
  // so the first row is always the monitor the summary names. Ties go by site ID.
  const rows = [
    { site_id: "040131003", pm25_ug_m3: 4.0, aqi: 22 },
    { site_id: "040134003", pm25_ug_m3: 9.5, aqi: 52 },
    { site_id: "040139812", pm25_ug_m3: 9.9, aqi: 52 },
    { site_id: "040130019", pm25_ug_m3: 9.5, aqi: 52 },
  ];
  assert.deepEqual(
    sortByConcentration(rows).map((r) => r.site_id),
    ["040139812", "040130019", "040134003", "040131003"],
  );
  assert.equal(rows[0].site_id, "040131003"); // the input is not reordered
});

test("a category's colours come from the scale table", () => {
  assert.deepEqual(colorFor("Moderate", SCALE), { color: "#ffff00", textColor: "#000000" });
  assert.equal(colorFor("Not a category", SCALE), null);
});

test("a failed load says what happened and what to do", () => {
  assert.match(LOAD_ERROR, /didn't load/);
  assert.match(LOAD_ERROR, /Reload/);
  assert.doesNotMatch(LOAD_ERROR, /sorry/i);
});
