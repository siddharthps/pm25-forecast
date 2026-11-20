// The page's pure functions (#14, T7), run with Node's built-in test runner:
//   node --test tests/site/
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DATA_BASE,
  dataBase,
  formatDate,
  formatIssued,
  HISTORY_DAYS,
  historyRows,
  monitorView,
} from "../../site/app.js";

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
