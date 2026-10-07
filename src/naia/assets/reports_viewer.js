'use strict';

(() => {
  let frame = document.getElementById('reportFrame');
  const open = document.getElementById('reportOpen');
  const themeButton = document.getElementById('reportTheme');
  const status = document.getElementById('reportViewerStatus');
  const editButton = document.getElementById('reportEdit');
  const saveButton = document.getElementById('reportSave');
  const cancelButton = document.getElementById('reportCancel');
  const editStatus = document.getElementById('reportEditStatus');
  const dirtyIndicator = document.getElementById('reportDirty');
  if (!frame || !open || !themeButton) return;

  // This credential belongs only to the trusted wrapper. The opaque report gets
  // a short-lived edit session and approved plain text, never an API credential.
  const editToken = document.body.dataset.reportEditToken || '';
  const reportID = document.body.dataset.reportId || '';
  const MAX_BLOCKS = 128, MAX_TEXT = 8192, MAX_TOTAL = 32768;
  const textEncoder = new TextEncoder();
  let snapshot = null, session = null, changes = Object.create(null), layout = null;
  let phase = 'idle', bridgeReady = false, dirty = false, generation = 0;
  let bridgeTimer = null, startTimer = null;
  let availability = editToken ? 'Checking report editing…' : 'Report editing is unavailable in this viewer.';

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

  function blockID(id) {
    return typeof id === 'string' && /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(id)
      && !reserved.has(id.toLowerCase());
  }

  function plainObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value);
  }

  function validText(value) {
    if (typeof value !== 'string' || value.length > MAX_TEXT * 2 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) return false;
    let length = 0;
    for (const character of value) {
      if (++length > MAX_TEXT || character.length === 1 && character.charCodeAt(0) >= 0xd800 && character.charCodeAt(0) <= 0xdfff) return false;
    }
    return true;
  }

  function validSnapshot(value) {
    if (!plainObject(value) || value.id !== reportID || typeof value.editable !== 'boolean'
      || typeof value.revision !== 'string' || !/^[a-f0-9]{64}$/.test(value.revision)
      || !Array.isArray(value.blocks) || value.blocks.length > MAX_BLOCKS) return false;
    const ids = new Set();
    let total = 0;
    for (const block of value.blocks) {
      if (!plainObject(block) || !blockID(block.id) || ids.has(block.id)
        || !validText(block.text)) return false;
      ids.add(block.id);
      total += textEncoder.encode(block.text).length;
    }
    return total <= MAX_TOTAL && (!value.editable || value.blocks.length > 0 || value.layout)
      && validLayoutSnapshot(value.layout);
  }

  function validLayoutSnapshot(value) {
    if (value === undefined || value === null) return true;
    if (!plainObject(value) || !Array.isArray(value.containers) || !Array.isArray(value.sections)
      || !Array.isArray(value.items) || value.sections.length > 64 || value.items.length > 256
      || value.containers.length > 65) return false;
    const containers = new Map(), sections = new Map(), items = new Map();
    for (const container of value.containers) {
      if (!plainObject(container) || !blockID(container.id) || containers.has(container.id)
        || !['sections', 'items'].includes(container.kind) || !Array.isArray(container.order)
        || container.order.length > 256 || container.order.some(id => !blockID(id))
        || new Set(container.order).size !== container.order.length) return false;
      containers.set(container.id, container);
    }
    const roots = value.containers.filter(container => container.kind === 'sections');
    if (roots.length !== 1) return false;
    for (const section of value.sections) {
      if (!plainObject(section) || !blockID(section.id) || sections.has(section.id)
        || section.container !== roots[0].id || typeof section.hidden !== 'boolean'
        || typeof section.label !== 'string' || section.label.length > 512
        || containers.get(section.id)?.kind !== 'items') return false;
      sections.set(section.id, section);
    }
    for (const item of value.items) {
      if (!plainObject(item) || !blockID(item.id) || items.has(item.id) || sections.has(item.id)
        || item.id === roots[0].id || !sections.has(item.container)
        || !['visual', 'text'].includes(item.kind) || typeof item.label !== 'string'
        || item.label.length > 512) return false;
      items.set(item.id, item);
    }
    return roots[0].order.length === sections.size
      && roots[0].order.every(id => sections.has(id))
      && containers.size === sections.size + 1
      && value.containers.filter(container => container.kind === 'items').every(container =>
        container.order.every(id => items.get(id)?.container === container.id))
      && value.containers.filter(container => container.kind === 'items').reduce((n, container) => n + container.order.length, 0) === items.size;
  }

  function proposedLayout(value) {
    if (!snapshot?.layout || !plainObject(value) || Object.keys(value).sort().join(',') !== 'add,hidden,orders'
      || !plainObject(value.orders) || !Array.isArray(value.hidden) || !Array.isArray(value.add)
      || value.add.length > 32 || value.hidden.length > 64 || Object.keys(value.orders).length > 65) return null;
    const original = snapshot.layout;
    const root = original.containers.find(container => container.kind === 'sections');
    const sectionIDs = new Set(original.sections.map(section => section.id));
    const itemIDs = new Set(original.items.map(item => item.id));
    const used = new Set([root.id, ...sectionIDs, ...itemIDs, ...snapshot.blocks.map(block => block.id)]);
    const additions = [];
    for (const addition of value.add) {
      if (!plainObject(addition) || Object.keys(addition).sort().join(',') !== 'container,id,text,title'
        || !blockID(addition.id) || addition.container !== root.id || !validText(addition.title) || !validText(addition.text)) return null;
      const ids = [addition.id, addition.id + '-title', addition.id + '-text'];
      if (ids.some(id => !blockID(id) || used.has(id))) return null;
      ids.forEach(id => used.add(id));
      sectionIDs.add(addition.id);
      itemIDs.add(addition.id + '-title'); itemIDs.add(addition.id + '-text');
      additions.push({id: addition.id, container: root.id, title: addition.title, text: addition.text});
    }
    if (sectionIDs.size > 64 || itemIDs.size > 256 || snapshot.blocks.length + additions.length * 2 > MAX_BLOCKS
      || value.hidden.some(id => !sectionIDs.has(id)) || new Set(value.hidden).size !== value.hidden.length) return null;
    const orders = Object.create(null);
    for (const container of original.containers) orders[container.id] = [...container.order];
    for (const addition of additions) {
      orders[root.id].push(addition.id);
      orders[addition.id] = [addition.id + '-title', addition.id + '-text'];
    }
    for (const [id, order] of Object.entries(value.orders)) {
      if (!(id === root.id || sectionIDs.has(id)) || !Array.isArray(order) || order.length > 256
        || order.some(child => !blockID(child)) || new Set(order).size !== order.length) return null;
      orders[id] = [...order];
    }
    if (orders[root.id].length !== sectionIDs.size || orders[root.id].some(id => !sectionIDs.has(id))) return null;
    const placed = [...sectionIDs].flatMap(id => orders[id]);
    if (placed.length !== itemIDs.size || new Set(placed).size !== placed.length || placed.some(id => !itemIDs.has(id))) return null;
    return {orders, hidden: [...value.hidden].sort(), add: additions};
  }

  function layoutChanged(value) {
    if (!value) return false;
    if (value.add.length) return true;
    const original = snapshot.layout;
    return JSON.stringify(value.hidden) !== JSON.stringify(original.sections.filter(section => section.hidden).map(section => section.id).sort())
      || original.containers.some(container => JSON.stringify(value.orders[container.id]) !== JSON.stringify(container.order));
  }

  function notify(message, error = false) {
    if (!editStatus) return;
    editStatus.textContent = message;
    editStatus.classList.toggle('nr-error', error);
  }

  function controls() {
    document.body.dataset.editState = phase;
    const active = session !== null;
    if (editButton) {
      editButton.hidden = active;
      editButton.disabled = phase !== 'idle' || !editToken || !bridgeReady || !snapshot || !snapshot.editable;
      editButton.title = editButton.disabled ? availability : 'Edit report text and layout';
    }
    if (saveButton) {
      saveButton.hidden = !active;
      saveButton.disabled = phase !== 'editing' || !dirty;
      saveButton.textContent = phase === 'saving' ? 'Saving…' : 'Save';
    }
    if (cancelButton) {
      cancelButton.hidden = !active;
      cancelButton.disabled = phase === 'saving';
    }
    if (dirtyIndicator) dirtyIndicator.hidden = !dirty;
    themeButton.disabled = phase === 'saving';
    if (saveButton) saveButton.setAttribute('aria-busy', String(phase === 'saving'));
  }

  function post(message) {
    // The iframe deliberately has an opaque origin, so targetOrigin must be '*'.
    // Incoming replies are checked against this exact browsing context below.
    frame.contentWindow.postMessage(message, '*');
  }

  function endEditing(restore = true) {
    if (session) post({type: 'naia-report-edit-stop', session, restore});
    clearTimeout(startTimer);
    session = null;
    changes = Object.create(null);
    layout = null;
    dirty = false;
    phase = 'idle';
    controls();
  }

  async function request(path, payload) {
    const response = await fetch(path, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-NAIA-Token': editToken},
      body: JSON.stringify(payload)
    });
    let result;
    try { result = await response.json(); } catch (_) { throw Error('The server returned an unreadable response.'); }
    if (!response.ok) {
      const error = Error(typeof result.error === 'string' ? result.error.slice(0, 500) : 'The request failed.');
      error.status = response.status;
      throw error;
    }
    if (!validSnapshot(result)) throw Error('The server returned an invalid text snapshot.');
    return result;
  }

  async function checkAvailability(navGeneration) {
    if (!editToken) { controls(); return; }
    try {
      const value = await request('/api/report-edit', {id: reportID});
      if (navGeneration !== generation || session) return;
      snapshot = value;
      availability = !value.editable ? (typeof value.reason === 'string' ? value.reason : 'This report has no editable text.')
        : bridgeReady ? 'Edit marked text and managed report sections.' : 'This report has no active editor. Opened reports remain read-only.';
      notify(availability);
    } catch (error) {
      if (navGeneration !== generation || session) return;
      snapshot = null;
      availability = 'Report editing is unavailable: ' + error.message;
      notify(availability, true);
    }
    controls();
  }

  function loaded(navGeneration) {
    if (navGeneration !== generation) return;
    if (status) status.textContent = '';
    post({type: 'naia-report-editor-probe'});
    checkAvailability(navGeneration);
    clearTimeout(bridgeTimer);
    bridgeTimer = setTimeout(() => {
      if (navGeneration !== generation || bridgeReady || session || !editToken) return;
      if (!snapshot || snapshot.editable) {
        availability = 'This report has no active editor. Opened reports remain read-only.';
        notify(availability);
      }
      controls();
    }, 2000);
  }

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
      endEditing();
      bridgeReady = false;
      snapshot = null;
      generation += 1;
      const navGeneration = generation;
      availability = editToken ? 'Checking report editing…' : 'Report editing is unavailable in this viewer.';
      notify(availability);
      controls();
      if (status) status.textContent = 'Loading report…';
      // A hash-only navigation would not rerun a report's initial state parsing.
      // Replace the browsing context, preserving its sandbox and accessibility.
      const next = frame.cloneNode(false);
      next.src = rawURL();
      next.addEventListener('load', () => loaded(navGeneration));
      frame.replaceWith(next);
      frame = next;
    }
  }

  themeButton.addEventListener('click', () => {
    if (phase === 'saving') return;
    if (dirty && !confirm('Discard unsaved report changes and switch theme?')) return;
    state.set('theme', state.get('theme') === 'light' ? 'dark' : 'light');
    update(true);
  });
  if (editButton) editButton.addEventListener('click', async () => {
    if (editButton.disabled || phase !== 'idle') return;
    const navGeneration = generation;
    phase = 'loading';
    notify('Preparing text editing…');
    controls();
    try {
      const value = await request('/api/report-edit', {id: reportID});
      if (navGeneration !== generation) return;
      snapshot = value;
      if (!value.editable) throw Error(typeof value.reason === 'string' ? value.reason : 'This report has no editable text.');
      if (!bridgeReady) throw Error('The report editor is unavailable.');
      session = typeof crypto.randomUUID === 'function' ? crypto.randomUUID()
        : [...crypto.getRandomValues(new Uint8Array(24))].map(value => value.toString(16).padStart(2, '0')).join('');
      phase = 'starting';
      controls();
      post({type: 'naia-report-edit-start', session, blocks: snapshot.blocks, layout: snapshot.layout || null});
      startTimer = setTimeout(() => {
        if (phase !== 'starting') return;
        endEditing();
        availability = 'The report editor did not respond. Reload the report to retry.';
        bridgeReady = false;
        notify(availability, true);
        controls();
      }, 3000);
    } catch (error) {
      if (navGeneration !== generation) return;
      phase = 'idle';
      availability = error.message;
      notify('Report editing is unavailable: ' + error.message, true);
      controls();
    }
  });
  if (cancelButton) cancelButton.addEventListener('click', () => {
    if (phase === 'saving') return;
    const conflict = phase === 'conflict';
    endEditing();
    if (conflict) update(true);
    else notify('Report changes discarded.');
    editButton?.focus({preventScroll: true});
  });
  if (saveButton) saveButton.addEventListener('click', async event => {
    // Report scripts and message events can propose drafts, never initiate saves.
    if (!event.isTrusted || phase !== 'editing' || !dirty || !session || !snapshot) return;
    const savingSession = session;
    const draft = {...changes};
    const draftLayout = layout;
    phase = 'saving';
    post({type: 'naia-report-edit-busy', session, busy: true});
    notify('Saving report changes…');
    controls();
    try {
      const value = await request('/api/report-save', {id: reportID, revision: snapshot.revision, changes: draft,
        ...(draftLayout ? {layout: draftLayout} : {})});
      if (session !== savingSession) return;
      snapshot = value;
      endEditing(false);
      availability = 'Edit report text and layout.';
      notify('Report changes saved.' + (typeof value.backup === 'string' && value.backup.length <= 1024
        ? ' Backup: ' + value.backup : ' A backup was kept.'));
      editButton?.focus({preventScroll: true});
    } catch (error) {
      if (session !== savingSession) return;
      if (error.status === 409) {
        phase = 'conflict';
        notify('This report changed on disk. Your edits are still here. Cancel to load the latest version.', true);
      } else {
        phase = 'editing';
        post({type: 'naia-report-edit-busy', session, busy: false});
        notify('Could not save: ' + error.message + ' Your edits are still here.', true);
      }
      controls();
    }
  });
  document.addEventListener('click', event => {
    const anchor = event.target.closest?.('a[href]');
    if (!anchor) return;
    if (phase === 'saving') {
      event.preventDefault();
      notify('Wait for the report changes to finish saving.');
      return;
    }
    if (dirty) {
      if (!confirm('Discard unsaved report changes and open this link?')) event.preventDefault();
      else { endEditing(); notify('Report changes discarded.'); }
    }
  }, true);
  window.addEventListener('beforeunload', event => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('message', event => {
    if (event.source !== frame.contentWindow || event.origin !== 'null') return;
    const message = event.data;
    if (!plainObject(message)) return;
    if (message.type === 'naia-report-editor-ready') {
      bridgeReady = true;
      clearTimeout(bridgeTimer);
      if (!session && snapshot && snapshot.editable) {
        availability = 'Edit marked text and managed report sections.';
        notify(availability);
      }
      controls();
      return;
    }
    if (message.type === 'naia-report-edit-started' && session && message.session === session && phase === 'starting') {
      clearTimeout(startTimer);
      phase = 'editing';
      notify('Click text to edit. Use section and figure handles to rearrange the report. Save when ready.');
      controls();
      return;
    }
    if (message.type === 'naia-report-editor-error' && session && message.session === session) {
      if (phase === 'saving' || phase === 'conflict') return;
      const detail = typeof message.message === 'string' ? message.message.slice(0, 500) : 'The report text could not be edited.';
      if (dirty || phase === 'editing' && message.recoverable === true) notify(detail + ' Your edits are still here.', true);
      else { endEditing(); bridgeReady = false; availability = detail; notify(detail, true); }
      controls();
      return;
    }
    if (message.type === 'naia-report-edits') {
      if (phase !== 'editing' || !session || message.session !== session || !snapshot || !plainObject(message.changes)) return;
      const entries = Object.entries(message.changes);
      if (entries.length > MAX_BLOCKS) return;
      const originals = new Map(snapshot.blocks.map(block => [block.id, block.text]));
      const nextLayout = message.layout === undefined ? null : proposedLayout(message.layout);
      if (message.layout !== undefined && nextLayout === null) return;
      let total = 0;
      const proposed = Object.create(null);
      for (const [id, text] of entries) {
        if (!blockID(id) || !originals.has(id) || !validText(text)) return;
        total += textEncoder.encode(text).length;
        if (total > MAX_TOTAL) return;
        if (text !== originals.get(id)) proposed[id] = text;
      }
      if (snapshot.blocks.reduce((sum, block) => sum + textEncoder.encode(
        Object.prototype.hasOwnProperty.call(proposed, block.id) ? proposed[block.id] : block.text
      ).length, 0) + (nextLayout?.add || []).reduce((sum, addition) => sum + textEncoder.encode(addition.title).length
        + textEncoder.encode(addition.text).length, 0) > MAX_TOTAL) return;
      changes = proposed;
      layout = layoutChanged(nextLayout) ? nextLayout : null;
      dirty = Object.keys(changes).length > 0 || layout !== null;
      controls();
      return;
    }
    if (message.type !== 'naia-report-state' || phase === 'saving' || phase === 'conflict') return;
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
