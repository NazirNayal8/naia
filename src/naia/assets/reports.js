'use strict';

(() => {
  const STORAGE_KEY = 'naia.reports.filters';
  const instances = new WeakMap();
  let current = null, nextId = 0;

  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }

  function strings(value) {
    return Array.isArray(value) ? [...new Set(value.filter(item => typeof item === 'string' && item.trim()))] : [];
  }

  function loadFilters() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return {query: typeof value.query === 'string' ? value.query : '', tags: strings(value.tags)};
    } catch (_) { return {query: '', tags: []}; }
  }

  function saveFilters(instance) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({query: instance.query, tags: [...instance.tags]})); }
    catch (_) {}
  }

  function setStatus(instance, text, error = false) {
    instance.status.textContent = text;
    instance.status.classList.toggle('nr-error', error);
  }

  function updateClear(instance) {
    instance.clear.hidden = !instance.query && !instance.tags.size;
  }

  function tagButton(instance, tag, filter = false) {
    const button = node('button', tag, filter ? 'nr-tag nr-filter-tag' : 'nr-tag');
    button.type = 'button';
    button.dataset.tag = tag;
    button.setAttribute('aria-pressed', String(instance.tags.has(tag)));
    button.setAttribute('aria-label', 'Filter by tag: ' + tag);
    button.addEventListener('click', () => {
      if (instance.tags.has(tag)) instance.tags.delete(tag);
      else instance.tags.add(tag);
      saveFilters(instance);
      updateClear(instance);
      renderTags(instance);
      void refreshInstance(instance);
    });
    return button;
  }

  function renderTags(instance) {
    const available = [...new Set([...instance.availableTags, ...instance.tags])].sort((a, b) => a.localeCompare(b));
    instance.tagList.replaceChildren(...available.map(tag => tagButton(instance, tag, true)));
    instance.tagGroup.hidden = !available.length;
  }

  function reportCard(instance, report, index) {
    const card = node('article', undefined, 'nr-card');
    const heading = node('h3', undefined, 'nr-card-title');
    heading.id = instance.id + '-report-' + index;
    card.setAttribute('aria-labelledby', heading.id);
    const title = typeof report.title === 'string' && report.title ? report.title : String(report.id || 'Untitled report');
    if (typeof report.id === 'string' && /^[A-Z0-9_]+$/.test(report.id)) {
      const link = node('a', title);
      link.href = '/report?id=' + encodeURIComponent(report.id);
      heading.append(link);
    } else heading.textContent = title;
    const top = node('div', undefined, 'nr-card-top');
    top.append(heading);
    if (typeof report.date === 'string' && report.date) {
      const date = node('time', report.date, 'nr-date');
      date.dateTime = report.date;
      top.append(date);
    }
    card.append(top);
    const tags = strings(report.tags);
    if (tags.length) {
      const tagList = node('div', undefined, 'nr-card-tags');
      tagList.append(...tags.map(tag => tagButton(instance, tag)));
      card.append(tagList);
    }
    if (typeof report.summary === 'string' && report.summary) card.append(node('p', report.summary, 'nr-summary'));
    const segments = report.snippetsegments || report.snippet_segments || report.snippet;
    if (Array.isArray(segments) && segments.some(segment => typeof segment?.text === 'string' && segment.text)) {
      const snippet = node('p', undefined, 'nr-snippet');
      for (const segment of segments) {
        if (typeof segment?.text !== 'string') continue;
        snippet.append(node(segment.hit === true ? 'mark' : 'span', segment.text));
      }
      card.append(snippet);
    }
    if (report.error) card.append(node('p', String(report.error), 'nr-card-error'));
    return card;
  }

  function renderWarnings(instance, values) {
    const warnings = strings(values);
    instance.warnings.hidden = !warnings.length;
    instance.warnings.replaceChildren();
    if (!warnings.length) return;
    instance.warnings.append(node('summary', warnings.length + ' report index warning' + (warnings.length === 1 ? '' : 's')));
    const list = node('ul');
    for (const warning of warnings) list.append(node('li', warning));
    instance.warnings.append(list);
  }

  async function refreshInstance(instance) {
    clearTimeout(instance.timer);
    instance.controller?.abort();
    const sequence = ++instance.sequence;
    const controller = new AbortController();
    instance.controller = controller;
    const params = new URLSearchParams({q: instance.query.trim()});
    for (const tag of instance.tags) params.append('tag', tag);
    instance.host.setAttribute('aria-busy', 'true');
    setStatus(instance, instance.query.trim() || instance.tags.size ? 'Searching reports…' : 'Loading reports…');
    try {
      const response = await fetch('/api/reports?' + params, {headers: {Accept: 'application/json'}, signal: controller.signal});
      const payload = await response.json();
      if (sequence !== instance.sequence) return;
      if (!response.ok) throw Error(typeof payload.error === 'string' ? payload.error : 'Could not load reports.');
      if (!Array.isArray(payload.reports)) throw Error('The report index returned an invalid response.');
      instance.availableTags = strings(payload.tags);
      renderTags(instance);
      renderWarnings(instance, payload.warnings);
      const reports = payload.reports.filter(report => report && typeof report === 'object' && !Array.isArray(report));
      instance.cards.replaceChildren(...reports.map((report, index) => reportCard(instance, report, index)));
      if (!reports.length) {
        const filtered = Boolean(instance.query.trim() || instance.tags.size);
        instance.cards.append(node('div', filtered ? 'No reports match these filters. Try another search or clear the filters.' : 'No project reports are available yet.', 'nr-empty'));
      }
      setStatus(instance, reports.length + ' report' + (reports.length === 1 ? '' : 's'));
    } catch (error) {
      if (sequence !== instance.sequence || error?.name === 'AbortError') return;
      const message = error?.message || 'Could not load reports.';
      setStatus(instance, message, true);
      const empty = node('div', undefined, 'nr-empty');
      empty.append(node('p', 'Reports could not be loaded.'));
      const retry = node('button', 'Try again', 'nr-control');
      retry.type = 'button';
      retry.addEventListener('click', () => { void refreshInstance(instance); });
      empty.append(retry);
      instance.cards.replaceChildren(empty);
    } finally {
      if (sequence === instance.sequence) {
        instance.host.setAttribute('aria-busy', 'false');
        instance.controller = null;
      }
    }
  }

  function createInstance(host) {
    const saved = loadFilters();
    const instance = {host, id: 'nr-library-' + ++nextId, query: saved.query, tags: new Set(saved.tags), availableTags: [], sequence: 0, timer: null, controller: null};
    host.classList.add('nr-library');
    const heading = node('div', undefined, 'nr-heading');
    heading.append(node('h2', 'Project reports'), node('p', 'Search findings, figures and supporting analysis.'));
    const toolbar = node('form', undefined, 'nr-toolbar');
    toolbar.setAttribute('role', 'search');
    toolbar.setAttribute('aria-label', 'Search project reports');
    const label = node('label', 'Search reports', 'nr-search-label');
    const input = node('input');
    input.type = 'search';
    input.name = 'q';
    input.autocomplete = 'off';
    input.placeholder = 'Titles, tags and report text';
    input.value = instance.query;
    input.dataset.reportSearch = '';
    label.append(input);
    instance.input = input;
    instance.clear = node('button', 'Clear filters', 'nr-control nr-clear');
    instance.clear.type = 'button';
    instance.clear.dataset.reportClear = '';
    instance.clear.addEventListener('click', () => {
      instance.query = '';
      instance.tags.clear();
      input.value = '';
      saveFilters(instance);
      updateClear(instance);
      renderTags(instance);
      void refreshInstance(instance);
      input.focus();
    });
    toolbar.append(label, instance.clear);
    instance.tagGroup = node('div', undefined, 'nr-tag-group');
    instance.tagGroup.append(node('span', 'Filter by tags', 'nr-filter-label'));
    instance.tagList = node('div', undefined, 'nr-tag-list');
    instance.tagList.setAttribute('role', 'group');
    instance.tagList.setAttribute('aria-label', 'Filter reports by tag; selected tags must all match');
    instance.tagGroup.append(instance.tagList);
    instance.tagGroup.hidden = true;
    instance.status = node('p', '', 'nr-status');
    instance.status.dataset.reportStatus = '';
    instance.status.setAttribute('role', 'status');
    instance.status.setAttribute('aria-live', 'polite');
    instance.status.setAttribute('aria-atomic', 'true');
    instance.warnings = node('details', undefined, 'nr-warnings');
    instance.warnings.dataset.reportWarnings = '';
    instance.warnings.hidden = true;
    instance.cards = node('div', undefined, 'nr-cards');
    host.replaceChildren(heading, toolbar, instance.tagGroup, instance.status, instance.warnings, instance.cards);
    updateClear(instance);
    toolbar.addEventListener('submit', event => {
      event.preventDefault();
      instance.query = input.value;
      saveFilters(instance);
      updateClear(instance);
      void refreshInstance(instance);
    });
    input.addEventListener('input', () => {
      instance.query = input.value;
      saveFilters(instance);
      updateClear(instance);
      clearTimeout(instance.timer);
      ++instance.sequence;
      instance.controller?.abort();
      instance.host.setAttribute('aria-busy', 'true');
      setStatus(instance, 'Searching reports…');
      instance.timer = setTimeout(() => { void refreshInstance(instance); }, 220);
    });
    instances.set(host, instance);
    return instance;
  }

  window.NAIAReports = Object.freeze({
    show(host) {
      if (!host || typeof host.replaceChildren !== 'function') return Promise.resolve();
      current = instances.get(host);
      if (current) return Promise.resolve();
      current = createInstance(host);
      return refreshInstance(current);
    },
    refresh(host) {
      const instance = host ? instances.get(host) : current;
      return instance ? refreshInstance(instance) : host ? this.show(host) : Promise.resolve();
    }
  });
})();
