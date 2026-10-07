'use strict';

(() => {
  let frame = document.getElementById('reportFrame');
  const open = document.getElementById('reportOpen');
  const themeButton = document.getElementById('reportTheme');
  const status = document.getElementById('reportViewerStatus');
  if (!frame || !open || !themeButton) return;

  const reserved = new Set(['id', 'view', 'prototype', 'constructor', '__proto__']);
  const MAX_KEYS = 24;
  const state = new Map([['theme', 'dark']]);
  const wrapperURL = new URL(location.href);
  const reportURL = new URL(frame.getAttribute('src'), location.href);
  reportURL.hash = '';
  reportURL.search = '';

  function validKey(key) {
    return /^[A-Za-z_][A-Za-z0-9_-]{0,39}$/.test(key) && !reserved.has(key.toLowerCase());
  }

  function validValue(key, value) {
    return typeof value === 'string' && value.length <= 80 && !/[\u0000-\u001f\u007f-\u009f]/.test(value)
      && (key !== 'theme' || value === 'dark' || value === 'light');
  }

  function readParams(params) {
    for (const [key, value] of params) {
      if (state.size >= MAX_KEYS && !state.has(key)) continue;
      if (validKey(key) && validValue(key, value)) state.set(key, value);
    }
  }

  readParams(new URLSearchParams(location.hash.slice(1)));
  readParams(wrapperURL.searchParams);

  function rawURL() {
    const url = new URL(reportURL);
    url.hash = new URLSearchParams(state).toString();
    return url.pathname + url.search + url.hash;
  }

  function update(navigate = false) {
    const theme = state.get('theme');
    document.body.dataset.theme = theme;
    themeButton.textContent = 'Theme: ' + (theme === 'light' ? 'Light' : 'Dark');
    themeButton.setAttribute('aria-label', 'Switch report to ' + (theme === 'light' ? 'dark' : 'light') + ' theme');
    themeButton.setAttribute('aria-pressed', String(theme === 'light'));
    const url = new URL(location.href);
    for (const [key, value] of state) url.searchParams.set(key, value);
    url.hash = '';
    try { history.replaceState(history.state, '', url.pathname + url.search); } catch (_) {}
    open.href = rawURL();
    if (navigate) {
      if (status) status.textContent = 'Loading report…';
      // A hash-only navigation would not rerun a report's initial state parsing.
      // Replace the browsing context, preserving its sandbox and accessibility.
      const next = frame.cloneNode(false);
      next.src = rawURL();
      next.addEventListener('load', () => { if (status) status.textContent = ''; });
      frame.replaceWith(next);
      frame = next;
    }
  }

  themeButton.addEventListener('click', () => {
    state.set('theme', state.get('theme') === 'light' ? 'dark' : 'light');
    update(true);
  });
  window.addEventListener('message', event => {
    if (event.source !== frame.contentWindow || event.origin !== 'null') return;
    const message = event.data;
    if (!message || typeof message !== 'object' || message.type !== 'naia-report-state') return;
    const values = message.state;
    if (!values || typeof values !== 'object' || Array.isArray(values)) return;
    const entries = Object.entries(values);
    if (!entries.length || entries.length > MAX_KEYS || entries.some(([key, value]) => !validKey(key) || !validValue(key, value))) return;
    const keys = new Set([...state.keys(), ...entries.map(([key]) => key)]);
    if (keys.size > MAX_KEYS) return;
    for (const [key, value] of entries) state.set(key, value);
    update();
  });
  update(true);
})();
