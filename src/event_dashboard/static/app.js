"use strict";

const TICK_MS = 5000;
const POLL_MS = 60000;
const DEFAULT_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"];

// Must match config.DEFAULT_TITLE on the server; shown translated in the UI.
const SERVER_DEFAULT_TITLE = "Upcoming events";

let state = { title: "", theme: "auto", language: "auto", rangeMinutes: 120, calendars: [] };
let lastUpdated = null;

const $ = (sel) => document.querySelector(sel);

function isDefaultTitle(title) {
  return !title || title === SERVER_DEFAULT_TITLE;
}

function applyAppearance(title, theme) {
  const shown = isDefaultTitle(title) ? t("defaultTitle") : title;
  $("#page-title").textContent = shown;
  document.title = shown;
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
  return date.toLocaleString(dateLocale(), opts) + (allDay ? ` ${t("allDay")}` : "");
}

function formatCountdown(ms) {
  if (ms <= 0) return t("startingNow");
  const totalMin = Math.ceil(ms / 60000);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return h ? t("inHoursMinutes", { h, m }) : t("inMinutes", { m });
}

function render() {
  const main = $("#dashboard");
  main.replaceChildren();
  applyAppearance(state.title, state.theme);
  updateRefreshTooltip();
  $("#range-label").textContent = t("rangeLabel", { minutes: state.rangeMinutes });
  if (!state.calendars.length) {
    main.append(el("p", { class: "muted" }, t("noCalendars")));
    return;
  }
  for (const cal of state.calendars) main.append(renderCalendar(cal));
  tick();
}

function formatTime(date) {
  return date.toLocaleTimeString(dateLocale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderCalendar(cal) {
  const section = el("section", { class: "calendar" });
  section.dataset.id = cal.id;
  section.style.setProperty("--cal-color", cal.color);
  const header = el("div", { class: "calendar-head" });
  const button = el("button", { type: "button", class: "icon-button calendar-refresh" });
  button.append($("#refresh-button svg").cloneNode(true));
  let tooltip = t("refreshCalendarTooltip", { name: cal.name });
  if (cal.updated) tooltip += "\n" + t("lastUpdated", { time: formatTime(cal.updated) });
  button.title = tooltip;
  button.setAttribute("aria-label", t("refreshCalendarTooltip", { name: cal.name }));
  button.addEventListener("click", () => refreshCalendar(cal.id, button));
  header.append(el("h2", {}, cal.name), button);
  section.append(header);
  if (cal.error) section.append(el("p", { class: "error" }, t("error", { message: cal.error })));
  else if (!cal.events.length) section.append(el("p", { class: "muted" }, t("noEvents")));
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
  return section;
}

async function refreshCalendar(id, button) {
  if (button.disabled) return;
  button.disabled = true;
  button.classList.add("loading");
  try {
    const resp = await fetch(`/api/calendars/${encodeURIComponent(id)}/events?refresh=true`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const cal = { ...data.calendar, updated: new Date() };
    const index = state.calendars.findIndex((c) => c.id === id);
    const section = document.querySelector(`#dashboard .calendar[data-id="${CSS.escape(id)}"]`);
    if (index < 0 || !section || data.range_minutes !== state.rangeMinutes) {
      await loadEvents(); // config changed meanwhile; reload everything
      return;
    }
    state.calendars[index] = cal;
    section.replaceWith(renderCalendar(cal));
    tick();
  } catch (err) {
    button.title = t("refreshCalendarFailed", { message: err.message });
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
  }
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

function updateRefreshTooltip() {
  const button = $("#refresh-button");
  let text = t("refreshTooltip");
  if (lastUpdated) {
    text += "\n" + t("lastUpdated", { time: formatTime(lastUpdated) });
  }
  button.title = text;
}

async function loadEvents(refresh = false) {
  try {
    const resp = await fetch(refresh ? "/api/events?refresh=true" : "/api/events");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const updated = new Date();
    state = {
      title: data.title,
      theme: data.theme,
      language: data.language || "auto",
      rangeMinutes: data.range_minutes,
      calendars: data.calendars.map((cal) => ({ ...cal, updated })),
    };
    // Don't switch the UI language under an open settings panel (it may be previewing another one).
    if ($("#settings").hidden && (await setLanguage(state.language))) translateDocument();
    lastUpdated = updated;
    render();
  } catch (err) {
    $("#dashboard").replaceChildren(el("p", { class: "error" }, t("loadEventsFailed", { message: err.message })));
  }
}

// ---- Settings ----

function addCalendarRow(cal = {}) {
  const list = $("#calendar-list");
  const row = $("#calendar-row").content.firstElementChild.cloneNode(true);
  translateDocument(row);
  row.dataset.id = cal.id || "";
  row.querySelector(".cal-name").value = cal.name || "";
  row.querySelector(".cal-url").value = cal.url || "";
  row.querySelector(".cal-color").value = cal.color || DEFAULT_COLORS[list.children.length % DEFAULT_COLORS.length];
  row.querySelector(".cal-remove").addEventListener("click", () => row.remove());
  list.append(row);
}

async function fillLanguageOptions(selected) {
  const select = $("#language-input");
  select.querySelectorAll("option:not([value='auto'])").forEach((opt) => opt.remove());
  let languages = [];
  try {
    const resp = await fetch("/api/languages");
    if (resp.ok) languages = await resp.json();
  } catch (err) {
    console.warn("Could not load language list:", err);
  }
  if (selected !== "auto" && !languages.includes(selected)) languages.push(selected);
  for (const lang of languages) {
    select.append(el("option", { value: lang }, languageName(lang)));
  }
  select.value = selected;
}

async function previewLanguage(preference) {
  if (await setLanguage(preference)) {
    translateDocument();
    render();
  }
}

async function openSettings() {
  const msg = $("#settings-message");
  msg.textContent = "";
  msg.className = "";
  try {
    const resp = await fetch("/api/config");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const cfg = await resp.json();
    await fillLanguageOptions(cfg.language || "auto");
    $("#title-input").value = isDefaultTitle(cfg.title) ? "" : cfg.title;
    $("#theme-input").value = cfg.theme;
    $("#range-input").value = cfg.range_minutes;
    $("#calendar-list").replaceChildren();
    cfg.calendars.forEach(addCalendarRow);
  } catch (err) {
    msg.textContent = t("loadSettingsFailed", { message: err.message });
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
    language: $("#language-input").value,
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
    msg.textContent = t("saveFailed", { message: err.message });
    msg.className = "error";
  }
}

// Close the panel and undo any unsaved theme/language preview.
async function cancelSettings() {
  setSettingsVisible(false);
  applyAppearance(state.title, state.theme);
  await previewLanguage(state.language);
}

async function refreshCalendars() {
  const button = $("#refresh-button");
  if (button.disabled) return;
  button.disabled = true;
  button.classList.add("loading");
  try {
    await loadEvents(true);
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
  }
}

$("#refresh-button").addEventListener("click", refreshCalendars);
$("#settings-toggle").addEventListener("click", () => {
  if ($("#settings").hidden) openSettings();
  else cancelSettings();
});
$("#theme-input").addEventListener("change", (e) => applyAppearance(state.title, e.target.value));
$("#language-input").addEventListener("change", (e) => previewLanguage(e.target.value));
$("#cancel-settings").addEventListener("click", cancelSettings);
$("#add-calendar").addEventListener("click", () => addCalendarRow());
$("#settings-form").addEventListener("submit", saveSettings);

async function init() {
  await setLanguage("auto");
  translateDocument();
  applyAppearance(state.title, state.theme);
  await loadEvents();
  setInterval(tick, TICK_MS);
  setInterval(loadEvents, POLL_MS);
}

init();
