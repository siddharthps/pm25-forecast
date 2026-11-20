export const DATA_BASE = "https://pm25-forecast-public-65bc08.s3.amazonaws.com/";
export const HISTORY_DAYS = 14;
export const LOAD_ERROR =
  "The forecast data didn't load. Reload the page; if it still fails, the data server may be down.";

/** Where to read the JSON: the public bucket, or a same-site folder for a local preview. */
export function dataBase(search) {
  const asked = new URLSearchParams(search).get("data");
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

/** The forecast's own day, so the heading stays true whenever the page is read. */
export function forecastHeading(isoDate) {
  return `Forecast for ${formatDate(isoDate)}`;
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

/**
 * Where an AQI sits on the band, in percent. Each of the six categories takes an equal share
 * (as people read the AQI by category, not by number), and the value is placed within its own
 * category's range. Values beyond the band stay at its ends.
 */
export function scalePosition(aqi, scale) {
  const share = 100 / scale.length;
  const i = scale.findIndex((c) => aqi <= c.high);
  if (i === -1) return 100;
  const c = scale[i];
  const within = Math.min(Math.max((aqi - c.low) / (c.high - c.low), 0), 1);
  return (i + within) * share;
}

/**
 * Highest concentration first, the order the city summary uses (two monitors can share an AQI);
 * ties by site ID. Returns a new list.
 */
export function sortByConcentration(monitors) {
  return [...monitors].sort(
    (a, b) => b.pm25_ug_m3 - a.pm25_ug_m3 || a.site_id.localeCompare(b.site_id),
  );
}

/** A category's colours, from the scale table in the data; null for an unknown name. */
export function colorFor(category, scale) {
  const c = scale.find((s) => s.name === category);
  return c ? { color: c.color, textColor: c.text_color } : null;
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

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function chip(category, scale) {
  const node = el("span", category, "chip");
  const colors = colorFor(category, scale);
  if (colors) {
    node.style.backgroundColor = colors.color;
    node.style.color = colors.textColor;
  }
  return node;
}

function renderScale(latest) {
  const band = document.getElementById("band");
  band.replaceChildren();
  for (const c of latest.aqi_scale) {
    const segment = el("span", undefined, "segment");
    segment.style.backgroundColor = c.color;
    band.append(segment);
  }
  const marker = el("span", undefined, "marker");
  marker.style.left = `${scalePosition(latest.city.aqi, latest.aqi_scale)}%`;
  band.append(marker);
  band.setAttribute(
    "aria-label",
    `AQI scale from Good to Hazardous. The forecast, ${latest.city.aqi}, is ${latest.city.category}.`,
  );

  const legend = document.getElementById("legend");
  legend.replaceChildren();
  for (const c of latest.aqi_scale) {
    const item = el("li");
    const swatch = el("span", undefined, "swatch");
    swatch.style.backgroundColor = c.color;
    item.append(swatch, `${c.name} (${c.low}–${c.high === 500 ? "500+" : c.high})`);
    legend.append(item);
  }
}

function renderLatest(latest) {
  const city = monitorView(latest.city);
  document.getElementById("forecast-heading").textContent = forecastHeading(latest.forecast_date);
  document.getElementById("city-answer").textContent = `${city.category}, AQI ${city.aqi}`;
  document.getElementById("city-basis").textContent =
    `Highest of ${latest.forecasts.length} monitors: ${city.name}, ${city.pm25} (24-hour mean).`;
  renderScale(latest);
  document.getElementById("issued").textContent = formatIssued(latest.issued_at_utc);
  document.getElementById("aqi-source").textContent = latest.aqi_source;

  const rows = document.getElementById("monitors");
  rows.replaceChildren();
  for (const m of sortByConcentration(latest.forecasts)) {
    const v = monitorView(m);
    const tr = el("tr");
    const bar = el("td", undefined, "bar-cell");
    const track = el("span", undefined, "track");
    const fill = el("span", undefined, "fill");
    fill.style.width = `${scalePosition(m.aqi, latest.aqi_scale)}%`;
    fill.style.backgroundColor = v.color;
    track.append(fill);
    bar.append(track);
    const cat = el("td");
    cat.append(chip(v.category, latest.aqi_scale));
    tr.append(el("td", v.name), el("td", v.pm25, "num"), el("td", v.aqi, "num"), bar, cat);
    rows.append(tr);
  }
  const missing = document.getElementById("no-forecast");
  missing.replaceChildren();
  for (const m of latest.no_forecast) {
    missing.append(el("li", `${m.site_name}: not enough hours yesterday for a forecast.`));
  }
  missing.hidden = latest.no_forecast.length === 0;
}

function renderHistory(history, scale) {
  const rows = document.getElementById("history");
  rows.replaceChildren();
  for (const h of historyRows(history)) {
    const tr = el("tr");
    const cell = el("td");
    cell.append(chip(h.category, scale));
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
    renderHistory(history, latest.aqi_scale);
    status.hidden = true;
    document.getElementById("content").hidden = false;
  } catch {
    status.textContent = LOAD_ERROR;
  }
}

if (typeof document !== "undefined") {
  main();
}
