// AirWatch page (#14, T7; D-025, D-036). Reads latest.json and history.json from the public
// bucket and renders them. Every value comes from those files: the AQI, its category and its
// colour are computed once, in Python (airwatch.aqi, from EPA's AQI TAD), never here.
// Data is written with textContent only, never as HTML.

export const DATA_BASE = "https://pm25-forecast-public-65bc08.s3.amazonaws.com/";
export const HISTORY_DAYS = 14;

/** Where to read the JSON: the public bucket, or a same-site folder for a local preview. */
export function dataBase(search) {
  const asked = new URLSearchParams(search).get("data");
  // A same-site path only: "./x" or "/x", named segments, no "..", and never "//" (to a
  // browser, "//host/" is another site).
  if (asked && /^\.?\/(?:[\w.-]+\/?)*$/.test(asked) && !/\.\.|\/\//.test(asked)) {
    return asked.endsWith("/") ? asked : `${asked}/`;
  }
  return DATA_BASE;
}

/** "2026-11-21" -> "Saturday, 21 November 2026" (a calendar date, so no time zone shift). */
export function formatDate(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** "2026-11-20T12:00:00+00:00" -> "20 Nov 2026, 06:00 Chicago time". */
export function formatIssued(isoUtc) {
  const text = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "America/Chicago",
  }).format(new Date(isoUtc));
  return `${text} Chicago time`;
}

/** One monitor as display strings. */
export function monitorView(m) {
  return {
    name: m.site_name,
    pm25: `${m.pm25_ug_m3.toFixed(1)} µg/m³`,
    aqi: String(m.aqi),
    category: m.category,
    color: m.color,
    textColor: m.text_color,
  };
}

/** The newest days of history for the table, newest first. */
export function historyRows(history, limit = HISTORY_DAYS) {
  return history.days.slice(0, limit).map((day) => ({
    date: formatDate(day.forecast_date),
    aqi: String(day.city.aqi),
    category: day.city.category,
  }));
}

// --- the page (browser only) ------------------------------------------------------------------

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function chip(view) {
  const node = el("span", view.category, "chip");
  node.style.backgroundColor = view.color;
  node.style.color = view.textColor;
  return node;
}

function renderLatest(latest) {
  const city = monitorView(latest.city);
  document.getElementById("forecast-date").textContent = formatDate(latest.forecast_date);
  const box = document.getElementById("city");
  box.style.backgroundColor = city.color;
  box.style.color = city.textColor;
  document.getElementById("city-aqi").textContent = city.aqi;
  document.getElementById("city-category").textContent = city.category;
  document.getElementById("city-basis").textContent =
    `Highest of ${latest.forecasts.length} monitors: ${city.name}, ${city.pm25} (24-hour mean).`;
  document.getElementById("issued").textContent = formatIssued(latest.issued_at_utc);
  document.getElementById("aqi-source").textContent = latest.aqi_source;

  const rows = document.getElementById("monitors");
  rows.replaceChildren();
  for (const m of latest.forecasts) {
    const v = monitorView(m);
    const tr = el("tr");
    tr.append(el("td", v.name), el("td", v.pm25, "num"), el("td", v.aqi, "num"));
    const cell = el("td");
    cell.append(chip(v));
    tr.append(cell);
    rows.append(tr);
  }
  const missing = document.getElementById("no-forecast");
  missing.replaceChildren();
  for (const m of latest.no_forecast) {
    missing.append(el("li", `${m.site_name}: not enough hours yesterday for a forecast.`));
  }
  missing.hidden = latest.no_forecast.length === 0;
}

function renderHistory(history) {
  const rows = document.getElementById("history");
  rows.replaceChildren();
  for (const h of historyRows(history)) {
    const tr = el("tr");
    const cell = el("td");
    cell.append(el("span", h.category));
    tr.append(el("td", h.date), el("td", h.aqi, "num"), cell);
    rows.append(tr);
  }
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${response.status}`);
  return response.json();
}

async function main() {
  const base = dataBase(window.location.search);
  const status = document.getElementById("status");
  try {
    const [latest, history] = await Promise.all([
      getJson(`${base}latest.json`),
      getJson(`${base}history.json`),
    ]);
    renderLatest(latest);
    renderHistory(history);
    status.hidden = true;
    document.getElementById("content").hidden = false;
  } catch {
    status.textContent = "The forecast couldn't be loaded. Please try again later.";
  }
}

if (typeof document !== "undefined") {
  main();
}
