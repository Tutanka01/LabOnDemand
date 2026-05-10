/**
 * i18n léger pour LabOnDemand.
 * Charge /i18n/{lang}.json, expose window.t(key, vars), applique [data-i18n] au DOM.
 * Doit être chargé AVANT tous les autres scripts (sauf darkmode.js).
 */
(function () {
  'use strict';

  const SUPPORTED = ['fr', 'en'];
  const DEFAULT_LANG = 'fr';

  function detectLang() {
    const stored = localStorage.getItem('labondemand-lang');
    if (stored && SUPPORTED.includes(stored)) return stored;
    const nav = (navigator.language || '').split('-')[0].toLowerCase();
    if (SUPPORTED.includes(nav)) return nav;
    return DEFAULT_LANG;
  }

  let _lang = detectLang();
  let _strings = {};

  function t(key, vars) {
    let msg = _strings[key];
    if (msg == null) return key;
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        msg = msg.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]);
      });
    }
    return msg;
  }

  function applyToDOM() {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      const key = el.getAttribute('data-i18n');
      const val = t(key);
      if (val !== key) el.textContent = val;
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      const key = el.getAttribute('data-i18n-placeholder');
      const val = t(key);
      if (val !== key) el.setAttribute('placeholder', val);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      const key = el.getAttribute('data-i18n-title');
      const val = t(key);
      if (val !== key) el.setAttribute('title', val);
    });
  }

  function injectLangSwitcher() {
    const header = document.querySelector('header .header-actions, header .nav-right, header');
    if (!header) return;
    if (document.getElementById('lang-switcher')) return;

    const sel = document.createElement('select');
    sel.id = 'lang-switcher';
    sel.setAttribute('aria-label', 'Language');
    sel.style.cssText = 'margin-left:8px;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:13px;cursor:pointer;';

    SUPPORTED.forEach(function (lang) {
      const opt = document.createElement('option');
      opt.value = lang;
      opt.textContent = lang === 'fr' ? '🇫🇷 FR' : '🇬🇧 EN';
      if (lang === _lang) opt.selected = true;
      sel.appendChild(opt);
    });

    sel.addEventListener('change', function () {
      localStorage.setItem('labondemand-lang', sel.value);
      location.reload();
    });

    header.appendChild(sel);
  }

  function load() {
    return fetch('/i18n/' + _lang + '.json?v=' + Date.now())
      .then(function (r) {
        if (!r.ok) throw new Error('i18n fetch failed: ' + r.status);
        return r.json();
      })
      .then(function (data) {
        _strings = data;
        applyToDOM();
        injectLangSwitcher();
        window._i18nLoaded = true;
        document.dispatchEvent(new CustomEvent('i18n-loaded', { detail: { lang: _lang } }));
      })
      .catch(function (err) {
        console.warn('[i18n] Failed to load', _lang, err);
        window._i18nLoaded = true;
        document.dispatchEvent(new CustomEvent('i18n-loaded', { detail: { lang: _lang, error: true } }));
      });
  }

  window.t = t;
  window.i18nLang = _lang;
  window.i18nApply = applyToDOM;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
