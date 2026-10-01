"use strict";

const TICK_MS = 5000;
const POLL_MS = 60000;
const DEFAULT_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"];

let state = { title: "Upcoming events", theme: "auto", rangeMinutes: 120, calendars: [] };

const $ = (sel) => document.querySelector(sel);

function applyAppearance(title, theme) {
  $("#page-title").textContent = title;
  document.title = title;
  document.documentElement.dataset.theme = ["light", "dark"].includes(theme) ? theme : "auto";
}

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatStart(date, allDay) {
  const opts = allDay
    ? { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" }
    : { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" };
  return date.toLocaleString(undefined, opts) + (allDay ? " (all day)" : "");
}

function formatCountdown(ms) {
  if (ms <= 0) return "starting now";
  const totalMin = Math.ceil(ms / 60000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return "in " + (h ? `${h}h ` : "") + `${m}m`;
}

function render() {
  const main = $("#dashboard");
  main.replaceChildren();
  applyAppearance(state.title, state.theme);
  $("#range-label").textContent = `(next ${state.rangeMinutes} min)`;
  if (!state.calendars.length) {
    main.append(el("p", { class: "muted" }, "No calendars configured. Click ⚙ to add one."));
    return;
  }
  for (const cal of state.calendars) {
    const section = el("section", { class: "calendar" });
    section.style.setProperty("--cal-color", cal.color);
    section.append(el("h2", {}, cal.name));
    if (cal.error) section.append(el("p", { class: "error" }, `Error: ${cal.error}`));
    else if (!cal.events.length) section.append(el("p", { class: "muted" }, "No upcoming events."));
    for (const ev of cal.events) {
      const row = el("div", { class: "event" });
      const head = el("div", { class: "event-head" });
      head.append(el("span", { class: "event-title", title: ev.title }, ev.title));
      const time = el("span", { class: "event-time" });
      head.append(time);
      const bar = el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100" });
      const fill = el("div", { class: "bar-fill" });
      bar.append(fill);
      row.append(head, bar);
      row._ev = { start: new Date(ev.start), allDay: ev.all_day, time, fill, bar };
      section.append(row);
    }
    main.append(section);
  }
  tick();
}

function tick() {
  const now = Date.now();
  const windowMs = state.rangeMinutes * 60000;
  document.querySelectorAll(".event").forEach((row) => {
    const ev = row._ev;
    const remaining = ev.start.getTime() - now;
    const pct = Math.max(0, Math.min(100, (1 - remaining / windowMs) * 100));
    ev.fill.style.width = pct.toFixed(1) + "%";
    ev.bar.setAttribute("aria-valuenow", pct.toFixed(0));
    ev.time.textContent = `${formatStart(ev.start, ev.allDay)} · ${formatCountdown(remaining)}`;
  });
}

async function loadEvents() {
  try {
    const resp = await fetch("/api/events");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    state = {
      title: data.title,
      theme: data.theme,
      rangeMinutes: data.range_minutes,
      calendars: data.calendars,
    };
    render();
  } catch (err) {
    $("#dashboard").replaceChildren(el("p", { class: "error" }, `Could not load events: ${err.message}`));
  }
}

// ---- Settings ----

function addCalendarRow(cal = {}) {
  const list = $("#calendar-list");
  const row = $("#calendar-row").content.firstElementChild.cloneNode(true);
  row.dataset.id = cal.id || "";
  row.querySelector(".cal-name").value = cal.name || "";
  row.querySelector(".cal-url").value = cal.url || "";
  row.querySelector(".cal-color").value = cal.color || DEFAULT_COLORS[list.children.length % DEFAULT_COLORS.length];
  row.querySelector(".cal-remove").addEventListener("click", () => row.remove());
  list.append(row);
}

async function openSettings() {
  const msg = $("#settings-message");
  msg.textContent = "";
  msg.className = "";
  try {
    const resp = await fetch("/api/config");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const cfg = await resp.json();
    $("#title-input").value = cfg.title;
    $("#theme-input").value = cfg.theme;
    $("#range-input").value = cfg.range_minutes;
    $("#calendar-list").replaceChildren();
    cfg.calendars.forEach(addCalendarRow);
  } catch (err) {
    msg.textContent = `Could not load settings: ${err.message}`;
    msg.className = "error";
  }
  setSettingsVisible(true);
}

function setSettingsVisible(visible) {
  $("#settings").hidden = !visible;
  $("#settings-toggle").setAttribute("aria-expanded", String(visible));
}

function formatValidationError(detail) {
  if (!Array.isArray(detail)) return String(detail);
  return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
}

async function saveSettings(event) {
  event.preventDefault();
  const msg = $("#settings-message");
  const calendars = [...document.querySelectorAll("#calendar-list .calendar-row")].map((row) => {
    const cal = {
      name: row.querySelector(".cal-name").value.trim(),
      url: row.querySelector(".cal-url").value.trim(),
      color: row.querySelector(".cal-color").value,
    };
    if (row.dataset.id) cal.id = row.dataset.id;
    return cal;
  });
  const body = {
    title: $("#title-input").value.trim(),
    theme: $("#theme-input").value,
    range_minutes: parseInt($("#range-input").value, 10),
    calendars,
  };
  try {
    const resp = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(formatValidationError(data.detail || `HTTP ${resp.status}`));
    }
    setSettingsVisible(false);
    await loadEvents();
  } catch (err) {
    msg.textContent = `Save failed: ${err.message}`;
    msg.className = "error";
  }
}

$("#settings-toggle").addEventListener("click", () => {
  if ($("#settings").hidden) openSettings();
  else setSettingsVisible(false);
});
$("#theme-input").addEventListener("change", (e) => applyAppearance(state.title, e.target.value));
$("#cancel-settings").addEventListener("click", () => {
  applyAppearance(state.title, state.theme);
  setSettingsVisible(false);
});
$("#add-calendar").addEventListener("click", () => addCalendarRow());
$("#settings-form").addEventListener("submit", saveSettings);

loadEvents();
setInterval(tick, TICK_MS);
setInterval(loadEvents, POLL_MS);
