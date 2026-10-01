"use strict";

// Loads UI translations from /static/locales/<lang>.json.
// The language is the one selected in the settings, or the browser language for "auto".
const FALLBACK_LANG = "en";
const AUTO_LANG = "auto";
let LANG = FALLBACK_LANG;
let LANG_PREFERENCE = null;
let MESSAGES = {};
let FALLBACK_MESSAGES = {};
const localeCache = new Map();

function browserLanguages() {
  const preferred = navigator.languages && navigator.languages.length
    ? navigator.languages
    : [navigator.language || FALLBACK_LANG];
  const candidates = [];
  for (const tag of preferred) {
    const lower = String(tag).toLowerCase();
    for (const lang of [lower, lower.split("-")[0]]) {
      if (/^[a-z]{2,3}(-[a-z0-9]+)?$/.test(lang) && !candidates.includes(lang)) candidates.push(lang);
    }
  }
  return candidates;
}

async function fetchJson(url) {
  const resp = await fetch(url, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function loadLocale(lang) {
  if (!localeCache.has(lang)) {
    localeCache.set(lang, fetchJson(`/static/locales/${lang}.json`).catch((err) => {
      localeCache.delete(lang);
      throw err;
    }));
  }
  return localeCache.get(lang);
}

// Switch to `preference` ("auto" or a language code). Returns true if the language changed.
async function setLanguage(preference = AUTO_LANG) {
  if (preference === LANG_PREFERENCE) return false;
  LANG_PREFERENCE = preference;
  try {
    FALLBACK_MESSAGES = await loadLocale(FALLBACK_LANG);
  } catch (err) {
    console.warn("Could not load fallback translations:", err);
  }
  const candidates = preference === AUTO_LANG ? browserLanguages() : [preference];
  LANG = FALLBACK_LANG;
  MESSAGES = FALLBACK_MESSAGES;
  for (const lang of candidates) {
    if (lang === FALLBACK_LANG) break;
    try {
      MESSAGES = await loadLocale(lang);
      LANG = lang;
      break;
    } catch {
      // No translation for this language; try the next preferred one.
    }
  }
  document.documentElement.lang = LANG;
  return true;
}

// Locale for date formatting: the browser locale on "auto", otherwise the selected language.
function dateLocale() {
  return LANG_PREFERENCE && LANG_PREFERENCE !== AUTO_LANG ? LANG : undefined;
}

function languageName(lang) {
  try {
    const name = new Intl.DisplayNames([lang], { type: "language" }).of(lang);
    return name ? name.charAt(0).toLocaleUpperCase(lang) + name.slice(1) : lang;
  } catch {
    return lang;
  }
}

function t(key, params = {}) {
  const text = MESSAGES[key] ?? FALLBACK_MESSAGES[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

function translateDocument(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((node) => {
    if (MESSAGES[node.dataset.i18n] ?? FALLBACK_MESSAGES[node.dataset.i18n]) {
      node.textContent = t(node.dataset.i18n);
    }
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    if (MESSAGES[node.dataset.i18nPlaceholder] ?? FALLBACK_MESSAGES[node.dataset.i18nPlaceholder]) {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    }
  });
  root.querySelectorAll("[data-i18n-title]").forEach((node) => {
    if (MESSAGES[node.dataset.i18nTitle] ?? FALLBACK_MESSAGES[node.dataset.i18nTitle]) {
      node.title = t(node.dataset.i18nTitle);
    }
  });
  root.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    if (MESSAGES[node.dataset.i18nAriaLabel] ?? FALLBACK_MESSAGES[node.dataset.i18nAriaLabel]) {
      node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
    }
  });
}
