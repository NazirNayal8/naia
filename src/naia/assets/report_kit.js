'use strict';

(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const PALETTE = {light: ['#2a78d6', '#eb6834'], dark: ['#3987e5', '#d95926']};
  const DASHES = ['', '', '6 3', '2 3', '8 3 2 3', '1 3'];
  const CSS = `
.nrk-root,.nrk-controls{--nrk-bg:#1e232b;--nrk-surface:#252c36;--nrk-text:#dde4ee;--nrk-muted:#a0adbf;--nrk-line:#445062;--nrk-grid:#364150;--nrk-link:#71b8ff;color:var(--nrk-text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
.nrk-root[data-theme="light"],.nrk-controls[data-theme="light"]{--nrk-bg:#fff;--nrk-surface:#f3f6fa;--nrk-text:#243044;--nrk-muted:#59687b;--nrk-line:#c0cbd8;--nrk-grid:#e1e7ef;--nrk-link:#236cae}
.nrk-root *,.nrk-controls *{box-sizing:border-box}.nrk-root [hidden]{display:none!important}.nrk-root{position:relative;min-width:0}.nrk-content{position:relative}.nrk-heading{margin:0 0 12px;color:var(--nrk-text);font:650 17px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}.nrk-caption{margin:10px 0;color:var(--nrk-muted);font-size:13px;line-height:1.6}.nrk-chart{display:block;width:100%;height:auto;overflow:visible}.nrk-chart text{fill:var(--nrk-text);font:12px -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}.nrk-chart .nrk-axis-label{fill:var(--nrk-muted);font-size:11px}.nrk-chart .nrk-facet-label{font-size:13px;font-weight:650}.nrk-chart .nrk-grid{stroke:var(--nrk-grid);stroke-width:1}.nrk-chart .nrk-axis{stroke:var(--nrk-line);stroke-width:1;fill:none}.nrk-chart .nrk-zero{stroke:var(--nrk-muted);stroke-width:1.4}.nrk-mark{outline:none}.nrk-mark:focus-visible>rect,.nrk-mark:focus-visible>circle,.nrk-mark:focus-visible>path{stroke:var(--nrk-text);stroke-width:3;filter:drop-shadow(0 0 3px var(--nrk-link))}.nrk-mark{cursor:help}.nrk-missing-label{fill:var(--nrk-muted)!important;font-size:10px!important}.nrk-legend{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:9px 20px;margin:8px 0 12px;color:var(--nrk-muted);font-size:12px}.nrk-legend-item{display:inline-flex;align-items:center;gap:7px}.nrk-legend-item svg{flex-shrink:0;overflow:visible}.nrk-tooltip{position:absolute;z-index:10;max-width:min(300px,90%);padding:9px 12px;background:var(--nrk-surface);border:1px solid var(--nrk-line);border-radius:6px;color:var(--nrk-text);font-size:12px;line-height:1.6;white-space:pre-line;pointer-events:none;box-shadow:0 8px 24px #0004}.nrk-warning,.nrk-error{margin:10px 0;padding:9px 12px;border:1px solid var(--nrk-line);border-left:3px solid #d95926;border-radius:4px;font-size:12px;line-height:1.6;color:var(--nrk-text);overflow-wrap:anywhere}.nrk-error{color:#edb6b6;background:#6b272733}.nrk-root[data-theme="light"] .nrk-error{color:#922c2c;background:#fff0f0}.nrk-numbers{margin:12px 0;color:var(--nrk-muted);font-size:12px}.nrk-numbers>summary{width:fit-content;cursor:pointer;color:var(--nrk-link);padding:4px 0}.nrk-numbers>summary:focus-visible,.nrk-table-wrap:focus-visible,.nrk-controls button:focus-visible{outline:2px solid var(--nrk-link);outline-offset:3px}.nrk-table-wrap{max-width:100%;overflow:auto;margin-top:8px}.nrk-table{width:100%;border-collapse:collapse;text-align:left;font-size:12px;color:var(--nrk-text)}.nrk-table th,.nrk-table td{padding:8px 10px;border-bottom:1px solid var(--nrk-grid);white-space:nowrap;vertical-align:top}.nrk-table th{background:var(--nrk-surface);font-weight:650}.nrk-table td.nrk-missing{color:var(--nrk-muted);font-style:italic}.nrk-controls{display:flex;flex-wrap:wrap;gap:12px 20px;margin:16px 0}.nrk-control{display:flex;flex-direction:column;gap:6px}.nrk-control-label{font-size:12px;font-weight:650}.nrk-control-options{display:flex;flex-wrap:wrap;gap:5px}.nrk-controls button{padding:6px 10px;margin:0;border:1px solid var(--nrk-line);border-radius:5px;background:var(--nrk-surface);color:var(--nrk-text);font:500 12px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;cursor:pointer}.nrk-controls button[aria-pressed="true"]{border-color:var(--nrk-link);box-shadow:inset 0 0 0 1px var(--nrk-link)}
@media(max-width:600px){.nrk-chart text{font-size:13px}.nrk-legend{justify-content:start;gap:8px 15px}.nrk-table th,.nrk-table td{padding:7px}.nrk-heading{font-size:16px}}`;
  let nextFigure = 0;

  function element(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  }

  function svg(tag, attributes = {}, text) {
    const result = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) result.setAttribute(key, String(value));
    if (text !== undefined) result.textContent = String(text);
    return result;
  }

  function installCSS() {
    if (document.querySelector('style[data-naia-report-kit]')) return;
    const style = element('style', CSS);
    style.dataset.naiaReportKit = '';
    document.head.append(style);
  }

  function own(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
  function key(value) { return typeof value + ':' + JSON.stringify(value); }
  function unique(values) {
    const seen = new Set();
    return values.filter(value => { const encoded = key(value); if (seen.has(encoded)) return false; seen.add(encoded); return true; });
  }
  function fields(rows) { return [...new Set(rows.flatMap(row => Object.keys(row)))]; }
  function ordered(values, preferred) {
    const result = unique(values);
    if (!Array.isArray(preferred)) return result;
    const rank = new Map(preferred.map((value, index) => [key(value), index]));
    return result.sort((a, b) => (rank.get(key(a)) ?? preferred.length) - (rank.get(key(b)) ?? preferred.length));
  }
  function finite(value, field, rowIndex) {
    if (value === null) return;
    if (typeof value !== 'number' || !Number.isFinite(value)) throw Error('Row ' + (rowIndex + 1) + ': ' + field + ' must be a finite number or null.');
  }
  function format(value, unit = '') {
    if (value === null || value === undefined) return 'Missing';
    if (typeof value !== 'number') return String(value);
    const number = Math.abs(value) > 0 && Math.abs(value) < 0.0001 ? value.toExponential(2) : value.toLocaleString('en-US', {maximumFractionDigits: 4});
    return number + unit;
  }
  function niceStep(range, count = 5) {
    if (!(range > 0) || !Number.isFinite(range)) return 1;
    const raw = range / count, power = 10 ** Math.floor(Math.log10(raw)), fraction = raw / power;
    return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
  }
  function axisRange(values, options = {}, {zero = false, clamp = false} = {}) {
    for (const name of ['min', 'max']) if (options[name] !== undefined && (typeof options[name] !== 'number' || !Number.isFinite(options[name]))) throw Error('Axis ' + name + ' must be finite.');
    if (options.min !== undefined && options.max !== undefined && options.min >= options.max) throw Error('Axis min must be smaller than max.');
    const valid = values.filter(value => value !== null);
    let min = valid.length ? Math.min(...valid) : 0;
    let max = valid.length ? Math.max(...valid) : 1;
    if (zero) { min = Math.min(0, min); max = Math.max(0, max); }
    if (options.min !== undefined) min = clamp ? options.min : Math.min(min, options.min);
    if (options.max !== undefined) max = clamp ? options.max : Math.max(max, options.max);
    if (min === max) {
      const padding = Math.abs(min) * .1 || 1;
      min = zero && min === 0 ? 0 : min - padding;
      max += padding;
    }
    if (min > max) {
      if (options.min !== undefined && options.max === undefined) max = min + (Math.abs(min) * .1 || 1);
      else if (options.max !== undefined && options.min === undefined) min = max - (Math.abs(max) * .1 || 1);
      else throw Error('Axis range is invalid.');
    }
    const step = niceStep(max - min);
    if (!(clamp && options.min !== undefined)) min = Math.floor(min / step) * step;
    if (!(clamp && options.max !== undefined)) max = Math.ceil(max / step) * step;
    if (min === max) max = min + step;
    if (!Number.isFinite(min) || !Number.isFinite(max) || !(min < max)) throw Error('Axis range is too large or too small to draw reliably.');
    const ticks = [];
    for (let value = Math.ceil(min / step) * step, n = 0; value <= max + step * 1e-8 && n < 100; value += step, n++) ticks.push(Math.abs(value) < step * 1e-8 ? 0 : Number(value.toPrecision(12)));
    return {min, max, ticks, step};
  }
  function scale(value, domain, start, end, clamp = false) {
    const bounded = clamp ? Math.max(domain.min, Math.min(domain.max, value)) : value;
    return start + (bounded - domain.min) / (domain.max - domain.min) * (end - start);
  }
  function resolve(value, root = document) {
    return typeof value === 'string' ? root.querySelector(value) : value;
  }
  function textLines(text, width, characterWidth = 6.4) {
    const lines = [];
    let line = '';
    for (const word of String(text).split(/\s+/)) {
      const candidate = line ? line + ' ' + word : word;
      if (line && candidate.length * characterWidth > width) { lines.push(line); line = word; }
      else line = candidate;
    }
    if (line) lines.push(line);
    return lines.length ? lines : [''];
  }
  function wrappedText(attributes, lines) {
    const text = svg('text', attributes);
    lines.forEach((line, index) => text.append(svg('tspan', {x: attributes.x, dy: index ? 14 : 0}, line)));
    return text;
  }
  function layoutWidth(host) {
    return Math.max(240, Math.min(1100, typeof host.clientWidth === 'number' && host.clientWidth > 0 ? Math.round(host.clientWidth) : 880));
  }

  function init(config = {}) {
    installCSS();
    let data = config.data ?? {};
    if (typeof data === 'string') {
      const source = document.querySelector(data);
      if (!source) throw Error('Report data element was not found: ' + data);
      try { data = JSON.parse(source.textContent); } catch (error) { throw Error('Report data is not valid JSON: ' + error.message); }
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error('Report data must contain named tidy tables.');
    if (data.tables && typeof data.tables === 'object' && !Array.isArray(data.tables)) data = data.tables;
    const tables = {};
    for (const [name, rows] of Object.entries(data)) tables[name] = Array.isArray(rows) ? rows.map(row => row && typeof row === 'object' && !Array.isArray(row) ? Object.freeze({...row}) : row) : rows;
    const controls = config.controls || {}, controlNames = Object.keys(controls), figures = [], listeners = new Set(), controlElements = [];
    const initial = {}, hash = new URLSearchParams(location.hash.slice(1));
    for (const name of controlNames) {
      if (!/^[A-Za-z_][A-Za-z0-9_-]{0,39}$/.test(name) || ['id', 'view', 'theme', 'prototype', 'constructor', '__proto__'].includes(name.toLowerCase())) throw Error('Invalid report control name: ' + name);
      const control = controls[name];
      if (!control || typeof control.options !== 'object' || Array.isArray(control.options) || !Object.keys(control.options).length) throw Error('Control ' + name + ' needs an options mapping.');
      for (const value of Object.keys(control.options)) if (value.length > 80 || /[\u0000-\u001f\u007f-\u009f]/.test(value)) throw Error('Control ' + name + ' has an invalid option value.');
      const fallback = control.default ?? Object.keys(control.options)[0];
      if (!own(control.options, fallback)) throw Error('Control ' + name + ' has an unknown default: ' + fallback);
      const supplied = hash.get(name);
      initial[name] = supplied !== null && own(control.options, supplied) ? supplied : String(fallback);
    }
    if (controlNames.length > 23) throw Error('A report supports at most 23 controls.');
    const theme = hash.get('theme') || config.theme || document.documentElement.dataset.theme || 'dark';
    initial.theme = ['dark', 'light'].includes(theme) ? theme : 'dark';
    let state = Object.freeze(initial);

    function tableRows(name) {
      if (!own(tables, name) || !Array.isArray(tables[name])) throw Error('Unknown or invalid report table: ' + name);
      if (tables[name].some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw Error('Table ' + name + ' must contain row objects.');
      return tables[name];
    }
    function relevantControls(rows, explicit) {
      if (explicit !== undefined) {
        if (!Array.isArray(explicit) || explicit.some(name => !controlNames.includes(name))) throw Error('Figure controls must list declared control names.');
        return [...new Set(explicit)];
      }
      return controlNames.filter(name => rows.some(row => own(row, name)));
    }
    function selectedRows(name, names, filter) {
      const rows = tableRows(name);
      return rows.filter(row => names.every(name => !own(row, name) || row[name] === state[name]) && (!filter || filter(row, state)));
    }
    function label(field, value, spec = {}) {
      if (value === null || value === undefined) return 'Missing';
      const mapping = spec.labels?.[field] || config.series?.[field] || controls[field]?.options;
      return mapping && own(mapping, String(value)) ? String(mapping[String(value)]) : String(value);
    }
    function unit(spec, axis, facet) {
      const value = spec[axis]?.unit;
      return typeof value === 'function' ? String(value(facet, state)) : String(value || '');
    }
    function template(value, rows) {
      if (typeof value === 'function') return String(value(rows.map(row => ({...row})), state));
      return String(value ?? '').replace(/\{([A-Za-z_][A-Za-z0-9_-]*)\}/g, (match, name) => name === 'count' ? String(rows.length) : own(state, name) ? name === 'theme' ? state.theme === 'light' ? 'Light' : 'Dark' : label(name, state[name]) : match);
    }
    function seriesList(allRows, rows, field) {
      if (!field) return ['__single__'];
      const declared = Object.keys(config.series?.[field] || {});
      const global = unique(allRows.map(row => row[field]));
      const stable = unique([...declared, ...ordered(global, declared)]);
      return {visible: unique(rows.map(row => row[field])).sort((a, b) => stable.findIndex(value => key(value) === key(a)) - stable.findIndex(value => key(value) === key(b))), stable};
    }
    function seriesStyle(value, list) {
      const index = Array.isArray(list) ? 0 : list.stable.findIndex(item => key(item) === key(value));
      return {index, color: PALETTE[state.theme][Math.max(index, 0) % 2], dash: DASHES[Math.max(index, 0) % DASHES.length], symbol: Math.max(index, 0) % 4, patterned: index >= 2};
    }
    function columnsFor(rows, spec) {
      if (spec.columns !== undefined && !Array.isArray(spec.columns)) throw Error('Table columns must be an array of field names or column specifications.');
      const definitions = spec.columns || fields(rows);
      return definitions.map(column => typeof column === 'string' ? {field: column, label: column} : column).map(column => {
        if (!column || typeof column.field !== 'string') throw Error('Every table column needs a field name.');
        return column;
      });
    }
    function validate(rows, spec) {
      if (!['bars', 'lines', 'scatter', 'table'].includes(spec.type)) throw Error('Unknown figure type: ' + spec.type);
      if (spec.filter !== undefined && typeof spec.filter !== 'function') throw Error('Figure filter must be a function.');
      if (spec.tooltip !== undefined && (!Array.isArray(spec.tooltip) || spec.tooltip.some(field => typeof field !== 'string'))) throw Error('Tooltip fields must be a list of field names.');
      const numeric = spec.type !== 'table', value = spec.value || spec.y?.field;
      if (numeric && (typeof value !== 'string' || !value)) throw Error('Numeric figures require an explicit value field (value or y.field).');
      if (numeric && (typeof spec.x !== 'string' || !spec.x)) throw Error('Numeric figures require an x field.');
      for (const field of ['series', 'facet']) if (spec[field] !== undefined && typeof spec[field] !== 'string') throw Error('Figure ' + field + ' must name a row field.');
      if (spec.point !== undefined && typeof spec.point !== 'string') throw Error('Figure point must name a row field.');
      const mapped = new Set([spec.x, spec.series, spec.facet, spec.point, value, ...controlNames, ...(spec.tooltip || [])].filter(Boolean));
      if (!numeric) for (const column of columnsFor(rows, spec)) mapped.add(column.field);
      for (const field of fields(rows)) {
        if (!mapped.has(field) && unique(rows.map(row => row[field])).length > 1) throw Error('Unmapped varying field: ' + field + '. Map it or list it in tooltip.');
      }
      const coordinates = new Set();
      rows.forEach((row, index) => {
        for (const [field, cell] of Object.entries(row)) if (typeof cell === 'number' && !Number.isFinite(cell)) throw Error('Row ' + (index + 1) + ': ' + field + ' must be finite.');
        for (const field of [spec.x, spec.series, spec.facet, spec.point, value].filter(Boolean)) if (!own(row, field)) throw Error('Row ' + (index + 1) + ' is missing field: ' + field);
        for (const field of [spec.x, spec.series, spec.facet, spec.point].filter(Boolean)) if (row[field] !== null && !['number', 'string', 'boolean'].includes(typeof row[field])) throw Error('Row ' + (index + 1) + ': ' + field + ' must be a simple value or null.');
        if (numeric) finite(row[value], value, index);
        if (spec.type === 'scatter') finite(row[spec.x], spec.x, index);
        if (spec.type === 'lines' && typeof row[spec.x] === 'number') finite(row[spec.x], spec.x, index);
        if (spec.type === 'scatter' && !spec.point) return;
        const dimensions = spec.type === 'scatter' ? [row[spec.facet], row[spec.series], row[spec.point]] : numeric ? [row[spec.facet], row[spec.x], row[spec.series]] : spec.x ? [row[spec.facet], row[spec.x], row[spec.series]] : Object.keys(row).sort().map(field => [field, row[field]]);
        const coordinate = JSON.stringify(dimensions.map(item => key(item)));
        if (coordinates.has(coordinate)) throw Error('Duplicate figure coordinate at row ' + (index + 1) + '; provide separate dimensions or precomputed data.');
        coordinates.add(coordinate);
      });
      return value;
    }
    function numbersTable(rows, spec, raw = false) {
      const wrapper = element('div', undefined, 'nrk-table-wrap');
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', 'Figure numbers');
      const table = element('table', undefined, 'nrk-table');
      const columns = raw ? columnsFor(rows, {}) : columnsFor(rows, spec);
      const head = element('thead'), headings = element('tr');
      for (const column of columns) headings.append(element('th', column.label || column.field));
      head.append(headings);
      const body = element('tbody');
      for (const row of rows) {
        const line = element('tr');
        for (const column of columns) {
          const value = row[column.field];
          const text = typeof column.format === 'function' ? column.format(value, row, state) : typeof value === 'number' ? format(value) : label(column.field, value, spec);
          line.append(element('td', text, value === null || value === undefined ? 'nrk-missing' : undefined));
        }
        body.append(line);
      }
      table.append(head, body);
      wrapper.append(table);
      return wrapper;
    }

    function figure(selector, originalSpec) {
      const host = resolve(selector);
      if (!host) throw Error('Figure element was not found: ' + selector);
      let spec = originalSpec;
      const identifier = 'nrk-' + ++nextFigure;
      host.classList.add('nrk-root');
      const content = element('div', undefined, 'nrk-content');
      host.append(content);
      const item = {host, content, spec: originalSpec, identifier, relevant: [], renderCount: 0, latestRows: [], width: layoutWidth(host)};

      function tooltipText(row, value, facet) {
        const parts = [];
        if (spec.series) parts.push(label(spec.series, row[spec.series], spec));
        if (spec.facet) parts.push(label(spec.facet, facet, spec));
        if (spec.type === 'scatter') {
          parts.push((spec.xAxis?.label || spec.labels?.fields?.[spec.x] || spec.x) + ': ' + format(row[spec.x], unit(spec, 'xAxis', facet)));
          parts.push((spec.y?.label || spec.labels?.fields?.[value] || value) + ': ' + format(row[value], unit(spec, 'y', facet)));
        } else parts.push(label(spec.x, row[spec.x], spec) + ': ' + format(row[value], unit(spec, 'y', facet)));
        if (spec.point && !(spec.tooltip || []).includes(spec.point)) parts.push(spec.point + ': ' + label(spec.point, row[spec.point], spec));
        for (const field of spec.tooltip || []) parts.push((spec.labels?.fields?.[field] || field) + ': ' + format(row[field]));
        return parts.join('\n');
      }
      function interactive(group, row, value, facet, tip) {
        group.classList.add('nrk-mark');
        group.setAttribute('tabindex', '0');
        group.setAttribute('role', 'img');
        const text = tooltipText(row, value, facet);
        group.setAttribute('aria-label', text.replace(/\n/g, ' · '));
        group.dataset.nrkSeries = spec.series ? String(row[spec.series]) : '__single__';
        group.dataset.nrkX = String(row[spec.x]);
        if (spec.facet) group.dataset.nrkFacet = String(facet);
        if (spec.point) group.dataset.nrkPoint = String(row[spec.point]);
        group.dataset.nrkValue = String(row[value]);
        group.dataset.nrkMissing = String(row[value] === null || ['scatter', 'lines'].includes(spec.type) && row[spec.x] === null);
        function show(event) {
          tip.textContent = text;
          tip.hidden = false;
          const bounds = content.getBoundingClientRect(), mark = group.getBoundingClientRect();
          const x = event?.clientX !== undefined ? event.clientX - bounds.left : mark.left + mark.width / 2 - bounds.left;
          const y = event?.clientY !== undefined ? event.clientY - bounds.top : mark.top - bounds.top;
          tip.style.left = Math.max(0, Math.min(x + 12, Math.max(0, bounds.width - tip.offsetWidth))) + 'px';
          tip.style.top = Math.max(0, y - tip.offsetHeight - 12) + 'px';
        }
        group.addEventListener('pointerenter', show);
        group.addEventListener('pointermove', show);
        group.addEventListener('pointerleave', () => { if (document.activeElement !== group) tip.hidden = true; });
        group.addEventListener('focus', show);
        group.addEventListener('blur', () => { tip.hidden = true; });
        group.addEventListener('keydown', event => { if (event.key === 'Escape') tip.hidden = true; });
      }
      function pointShape(style, x, y, radius = 5) {
        if (style.symbol === 1) return svg('path', {d: 'M' + x + ',' + (y - radius - 1) + 'L' + (x + radius + 1) + ',' + y + 'L' + x + ',' + (y + radius + 1) + 'L' + (x - radius - 1) + ',' + y + 'Z', fill: style.color, stroke: 'var(--nrk-bg)', 'stroke-width': 2});
        if (style.symbol === 2) return svg('rect', {x: x - radius, y: y - radius, width: radius * 2, height: radius * 2, rx: 1, fill: style.color, stroke: 'var(--nrk-bg)', 'stroke-width': 2});
        if (style.symbol === 3) return svg('path', {d: 'M' + x + ',' + (y - radius - 1) + 'L' + (x + radius + 1) + ',' + (y + radius) + 'L' + (x - radius - 1) + ',' + (y + radius) + 'Z', fill: style.color, stroke: 'var(--nrk-bg)', 'stroke-width': 2});
        return svg('circle', {cx: x, cy: y, r: radius, fill: style.color, stroke: 'var(--nrk-bg)', 'stroke-width': 2});
      }
      function legend(list) {
        const visible = Array.isArray(list) ? list : list.visible;
        if (!spec.series || visible.length < 2) return null;
        const result = element('div', undefined, 'nrk-legend');
        result.setAttribute('aria-label', 'Figure legend');
        for (const value of visible) {
          const style = seriesStyle(value, list), entry = element('span', undefined, 'nrk-legend-item'), sample = svg('svg', {width: 28, height: 14, viewBox: '0 0 28 14', 'aria-hidden': 'true'});
          if (spec.type === 'bars') {
            sample.append(svg('rect', {x: 4, y: 2, width: 20, height: 10, rx: 2, fill: style.color}));
            if (style.patterned) sample.append(svg('path', {d: 'M6 12L16 2M14 12L24 2', fill: 'none', stroke: 'var(--nrk-text)', 'stroke-width': 1.5}));
          } else {
            if (spec.type === 'lines') sample.append(svg('line', {x1: 0, y1: 7, x2: 28, y2: 7, stroke: style.color, 'stroke-width': 2, 'stroke-dasharray': style.dash}));
            sample.append(pointShape(style, 14, 7, 4));
          }
          entry.append(sample, element('span', label(spec.series, value, spec)));
          result.append(entry);
        }
        return result;
      }
      function chart(rows, value, tip) {
        const allRows = tableRows(spec.table), list = seriesList(allRows, rows, spec.series), series = Array.isArray(list) ? list : list.visible;
        const facets = spec.facet ? ordered(rows.map(row => row[spec.facet]), spec.order?.facet) : ['__all__'];
        const width = layoutWidth(host);
        const minimumPanel = spec.facetColumns === undefined ? 300 : 220;
        const requestedColumns = Math.max(1, Math.floor(Number(spec.facetColumns) || (facets.length > 1 ? 2 : 1)));
        const columns = width < 650 ? 1 : Math.min(requestedColumns, Math.max(1, facets.length), Math.max(1, Math.floor(width / minimumPanel)));
        const panelWidth = width / columns, panelHeight = facets.length > 1 ? 335 : 365;
        const result = svg('svg', {class: 'nrk-chart', viewBox: '0 0 ' + width + ' ' + (Math.ceil(facets.length / columns) * panelHeight), role: 'group', 'aria-label': template(spec.title || 'Interactive ' + spec.type + ' chart', rows)});
        result.append(svg('title', {}, template(spec.title || 'Interactive ' + spec.type + ' chart', rows)), svg('desc', {}, rows.length + ' data rows. Focus a mark to inspect its values. Full values are available under Show the numbers.'));
        const definitions = svg('defs');
        for (const seriesValue of series) {
          const style = seriesStyle(seriesValue, list);
          if (style.patterned) {
            const pattern = svg('pattern', {id: identifier + '-pattern-' + style.index, width: 7, height: 7, patternUnits: 'userSpaceOnUse'});
            pattern.append(svg('rect', {width: 7, height: 7, fill: style.color}), svg('path', {d: 'M-1 1L1 -1M0 7L7 0M6 8L8 6', stroke: 'var(--nrk-text)', 'stroke-width': 1.2, opacity: .7}));
            definitions.append(pattern);
          }
        }
        result.append(definitions);
        let clamped = 0, missing = 0;
        const sharedY = axisRange(rows.map(row => row[value]), spec.y, {zero: spec.type === 'bars', clamp: spec.type === 'scatter'});
        const numericX = spec.type === 'scatter' || spec.type === 'lines' && rows.every(row => row[spec.x] === null || typeof row[spec.x] === 'number');
        const sharedX = numericX ? axisRange(rows.map(row => row[spec.x]), spec.xAxis, {clamp: spec.type === 'scatter'}) : null;
        facets.forEach((facet, facetIndex) => {
          const selected = spec.facet ? rows.filter(row => key(row[spec.facet]) === key(facet)) : rows;
          const panel = svg('g', {class: 'nrk-panel', transform: 'translate(' + (facetIndex % columns * panelWidth) + ',' + (Math.floor(facetIndex / columns) * panelHeight) + ')'});
          const left = 62, right = panelWidth - 22;
          const categories = ordered(selected.map(row => row[spec.x]), spec.order?.x);
          if (spec.type === 'lines' && !spec.order?.x && numericX) categories.sort((a, b) => a - b);
          const categoryLabels = new Map(categories.map(category => [key(category), textLines(label(spec.x, category, spec), Math.max(45, (right - left) / Math.max(1, categories.length) - 6))]));
          const facetLines = spec.facet ? textLines(label(spec.facet, facet, spec), right - left) : [];
          const labelLineCount = numericX ? 1 : Math.max(1, ...[...categoryLabels.values()].map(lines => lines.length));
          const top = spec.facet ? Math.max(42, 18 + facetLines.length * 14) : 20;
          const bottom = panelHeight - Math.max(62, 42 + (labelLineCount - 1) * 14 + (spec.xAxis?.label ? 20 : 0));
          const domainY = spec.y?.shared === false ? axisRange(selected.map(row => row[value]), spec.y, {zero: spec.type === 'bars', clamp: spec.type === 'scatter'}) : sharedY;
          const domainX = sharedX;
          panel.dataset.nrkYmin = String(domainY.min);
          panel.dataset.nrkYmax = String(domainY.max);
          if (domainX) { panel.dataset.nrkXmin = String(domainX.min); panel.dataset.nrkXmax = String(domainX.max); }
          if (spec.facet) { panel.dataset.nrkFacet = String(facet); panel.append(wrappedText({x: left, y: 20, class: 'nrk-facet-label'}, facetLines)); }
          const yUnit = unit(spec, 'y', facet), xUnit = unit(spec, 'xAxis', facet);
          for (const tick of domainY.ticks) {
            const y = scale(tick, domainY, bottom, top);
            panel.append(svg('line', {x1: left, y1: y, x2: right, y2: y, class: tick === 0 ? 'nrk-grid nrk-zero' : 'nrk-grid'}), svg('text', {x: left - 9, y: y + 4, 'text-anchor': 'end', class: 'nrk-axis-label'}, format(tick, yUnit)));
          }
          panel.append(svg('path', {d: 'M' + left + ',' + top + 'V' + bottom + 'H' + right, class: 'nrk-axis'}));
          if (numericX) {
            for (const tick of domainX.ticks) {
              const x = scale(tick, domainX, left, right);
              panel.append(svg('text', {x, y: bottom + 23, 'text-anchor': 'middle', class: 'nrk-axis-label'}, format(tick, xUnit)));
            }
          }
          if (spec.xAxis?.label) panel.append(svg('text', {x: (left + right) / 2, y: panelHeight - 9, 'text-anchor': 'middle', class: 'nrk-axis-label'}, spec.xAxis.label));
          if (spec.y?.label) panel.append(svg('text', {transform: 'translate(13 ' + ((top + bottom) / 2) + ') rotate(-90)', 'text-anchor': 'middle', class: 'nrk-axis-label'}, spec.y.label));
          const categoryX = value => {
            const index = categories.findIndex(item => key(item) === key(value));
            return spec.type === 'bars' ? left + (index + .5) * (right - left) / Math.max(1, categories.length) : categories.length < 2 ? (left + right) / 2 : left + index * (right - left) / (categories.length - 1);
          };
          if (!numericX) for (const category of categories) panel.append(wrappedText({x: categoryX(category), y: bottom + 24, 'text-anchor': 'middle', class: 'nrk-axis-label'}, categoryLabels.get(key(category))));
          if (spec.type === 'bars') {
            const groupWidth = (right - left) / Math.max(1, categories.length), barWidth = Math.min(24, Math.max(2, (groupWidth - 15) / Math.max(1, series.length) - 4));
            const zero = scale(0, domainY, bottom, top);
            for (const row of selected) {
              const seriesValue = spec.series ? row[spec.series] : '__single__', seriesIndex = series.findIndex(item => key(item) === key(seriesValue)), style = seriesStyle(seriesValue, list);
              const x = categoryX(row[spec.x]) - series.length * (barWidth + 4) / 2 + seriesIndex * (barWidth + 4) + 2;
              const mark = svg('g');
              if (row[value] === null) {
                ++missing;
                mark.append(svg('rect', {x, y: zero - 4, width: barWidth, height: 8, rx: 2, fill: 'none', stroke: style.color, 'stroke-dasharray': '3 2'}), svg('text', {x: x + barWidth / 2, y: zero - 11, 'text-anchor': 'middle', class: 'nrk-missing-label'}, 'Missing'));
              } else {
                const y = scale(row[value], domainY, bottom, top), high = Math.min(y, zero), low = Math.max(y, zero), radius = Math.min(4, barWidth / 2, (low - high) / 2);
                const path = row[value] >= 0 ? 'M' + x + ',' + low + 'V' + (high + radius) + 'Q' + x + ',' + high + ' ' + (x + radius) + ',' + high + 'H' + (x + barWidth - radius) + 'Q' + (x + barWidth) + ',' + high + ' ' + (x + barWidth) + ',' + (high + radius) + 'V' + low + 'Z' : 'M' + x + ',' + high + 'V' + (low - radius) + 'Q' + x + ',' + low + ' ' + (x + radius) + ',' + low + 'H' + (x + barWidth - radius) + 'Q' + (x + barWidth) + ',' + low + ' ' + (x + barWidth) + ',' + (low - radius) + 'V' + high + 'Z';
                const bar = svg('path', {d: path, fill: style.patterned ? 'url(#' + identifier + '-pattern-' + style.index + ')' : style.color});
                bar.dataset.nrkBarTop = String(high);
                bar.dataset.nrkBarBottom = String(low);
                bar.dataset.nrkBaseline = String(zero);
                bar.dataset.nrkBarWidth = String(barWidth);
                mark.append(bar);
              }
              interactive(mark, row, value, facet, tip);
              panel.append(mark);
            }
          } else if (spec.type === 'lines') {
            for (const seriesValue of series) {
              const style = seriesStyle(seriesValue, list), lineRows = selected.filter(row => !spec.series || key(row[spec.series]) === key(seriesValue)).sort((a, b) => categories.findIndex(value => key(value) === key(a[spec.x])) - categories.findIndex(value => key(value) === key(b[spec.x])));
              let path = '', connected = false;
              for (const row of lineRows) {
                if (row[value] === null || row[spec.x] === null) { connected = false; continue; }
                const x = numericX ? scale(row[spec.x], domainX, left, right) : categoryX(row[spec.x]), y = scale(row[value], domainY, bottom, top);
                path += (connected ? 'L' : 'M') + x + ',' + y;
                connected = true;
              }
              panel.append(svg('path', {d: path, fill: 'none', stroke: style.color, 'stroke-width': 2, 'stroke-dasharray': style.dash}));
              for (const row of lineRows) {
                const mark = svg('g'), x = row[spec.x] === null ? left : numericX ? scale(row[spec.x], domainX, left, right) : categoryX(row[spec.x]);
                if (row[value] === null || row[spec.x] === null) {
                  ++missing;
                  mark.append(svg('circle', {cx: x, cy: bottom, r: 5, fill: 'none', stroke: style.color, 'stroke-dasharray': '3 2'}), svg('text', {x, y: bottom - 10, 'text-anchor': 'middle', class: 'nrk-missing-label'}, 'Missing'));
                } else mark.append(pointShape(style, x, scale(row[value], domainY, bottom, top)));
                interactive(mark, row, value, facet, tip);
                panel.append(mark);
              }
            }
          } else {
            if (spec.targetZone) {
              const zone = spec.targetZone;
              for (const field of ['xMin', 'xMax', 'yMin', 'yMax']) if (typeof zone[field] !== 'number' || !Number.isFinite(zone[field])) throw Error('Target zone needs finite ' + field + '.');
              if (zone.xMin > zone.xMax || zone.yMin > zone.yMax) throw Error('Target zone bounds are reversed.');
              const x1 = scale(zone.xMin, domainX, left, right, true), x2 = scale(zone.xMax, domainX, left, right, true), y1 = scale(zone.yMax, domainY, bottom, top, true), y2 = scale(zone.yMin, domainY, bottom, top, true);
              panel.append(svg('rect', {class: 'nrk-target-zone', x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: '#79bc99', 'fill-opacity': .12, stroke: '#79bc99', 'stroke-dasharray': '4 3'}));
              if (zone.label) panel.append(svg('text', {x: x1 + 5, y: y1 + 15, class: 'nrk-axis-label'}, zone.label));
            }
            for (const row of selected) {
              if (row[value] === null || row[spec.x] === null) { ++missing; continue; }
              const outside = row[spec.x] < domainX.min || row[spec.x] > domainX.max || row[value] < domainY.min || row[value] > domainY.max;
              if (outside) ++clamped;
              const style = seriesStyle(spec.series ? row[spec.series] : '__single__', list), mark = svg('g');
              mark.dataset.nrkClamped = String(outside);
              mark.append(pointShape(style, scale(row[spec.x], domainX, left, right, true), scale(row[value], domainY, bottom, top, true)));
              interactive(mark, row, value, facet, tip);
              if (outside) mark.setAttribute('aria-label', mark.getAttribute('aria-label') + ' · Outside axis range; shown at boundary');
              panel.append(mark);
            }
          }
          result.append(panel);
        });
        const warnings = [];
        if (clamped) warnings.push(clamped + ' point' + (clamped === 1 ? '' : 's') + ' outside the axis range ' + (clamped === 1 ? 'is' : 'are') + ' shown at the boundary. Tooltips and numbers retain the original values.');
        if (missing) warnings.push(missing + ' missing value' + (missing === 1 ? '' : 's') + (spec.type === 'scatter' ? ' could not be positioned; see Show the numbers.' : ' shown as Missing.'));
        return {chart: result, legend: legend(list), warnings};
      }
      function render() {
        const active = document.activeElement;
        const focusedMark = active?.classList?.contains('nrk-mark') && host.contains?.(active) ? {...active.dataset} : null;
        const numbersOpen = content.querySelector('.nrk-numbers')?.open === true;
        const focusedNumbers = active?.tagName === 'SUMMARY' && host.contains?.(active) && active.parentElement?.classList?.contains('nrk-numbers');
        item.renderCount++;
        item.width = layoutWidth(host);
        host.dataset.nrkRender = String(item.renderCount);
        host.dataset.theme = state.theme;
        content.replaceChildren();
        try {
          spec = {...originalSpec};
          for (const name of ['y', 'xAxis', 'targetZone']) {
            const value = typeof originalSpec[name] === 'function' ? originalSpec[name](state) : originalSpec[name];
            if (value !== undefined && value !== null && (typeof value !== 'object' || Array.isArray(value))) throw Error('Figure ' + name + ' must be an object or a function returning an object.');
            spec[name] = value ?? undefined;
          }
          const allRows = tableRows(spec.table);
          item.relevant = relevantControls(allRows, spec.controls);
          const rows = selectedRows(spec.table, item.relevant, spec.filter);
          item.latestRows = rows;
          host.dataset.nrkRows = String(rows.length);
          const value = validate(rows, spec);
          if (spec.title !== undefined) {
            const heading = spec.titleSelector ? resolve(spec.titleSelector, host) || resolve(spec.titleSelector) : element('h3', undefined, 'nrk-heading');
            if (!heading) throw Error('Figure title element was not found: ' + spec.titleSelector);
            heading.textContent = template(spec.title, rows);
            if (!spec.titleSelector) content.append(heading);
          }
          if (!rows.length) content.append(element('p', 'No data matches the selected controls.', 'nrk-warning'));
          else if (spec.type === 'table') content.append(numbersTable(rows, spec));
          else {
            const tip = element('div', undefined, 'nrk-tooltip');
            tip.id = identifier + '-tooltip';
            tip.setAttribute('role', 'tooltip');
            tip.hidden = true;
            const rendered = chart(rows, value, tip);
            content.append(rendered.chart);
            if (rendered.legend) content.append(rendered.legend);
            for (const warning of rendered.warnings) content.append(element('p', warning, 'nrk-warning'));
            content.append(tip);
          }
          if (spec.caption !== undefined) {
            const caption = spec.captionSelector ? resolve(spec.captionSelector, host) || resolve(spec.captionSelector) : element('p', undefined, 'nrk-caption');
            if (!caption) throw Error('Figure caption element was not found: ' + spec.captionSelector);
            caption.textContent = template(spec.caption, rows);
            if (!spec.captionSelector) content.append(caption);
          }
          if (spec.numbersTarget) {
            const destination = resolve(spec.numbersTarget);
            if (!destination) throw Error('Figure numbers element was not found: ' + spec.numbersTarget);
            destination.replaceChildren(numbersTable(rows, spec, true));
          } else if (spec.numbers !== false) {
            const numbers = element('details', undefined, 'nrk-numbers');
            numbers.open = numbersOpen;
            numbers.append(element('summary', 'Show the numbers'), numbersTable(rows, spec, true));
            content.append(numbers);
          }
          if (focusedMark) {
            const replacement = [...content.querySelectorAll('.nrk-mark')].find(mark => ['nrkPoint', 'nrkSeries', 'nrkFacet', 'nrkX', 'nrkValue'].every(name => mark.dataset[name] === focusedMark[name]));
            replacement?.focus({preventScroll: true});
          } else if (focusedNumbers) content.querySelector('.nrk-numbers summary')?.focus({preventScroll: true});
        } catch (error) {
          content.replaceChildren(element('p', error.message || String(error), 'nrk-error'));
          content.firstChild.setAttribute('role', 'alert');
        }
      }
      item.render = render;
      figures.push(item);
      render();
      resizeObserver?.observe(host);
      return Object.freeze({element: host, render, rows: () => item.latestRows.map(row => ({...row}))});
    }

    function syncURL() {
      const hash = new URLSearchParams(state).toString();
      try { history.replaceState(history.state, '', location.pathname + location.search + '#' + hash); }
      catch (_) { if (location.hash.slice(1) !== hash) location.hash = hash; }
      if (window.parent !== window) window.parent.postMessage({type: 'naia-report-state', state: {...state}}, '*');
    }
    function syncControls() {
      document.documentElement.dataset.theme = state.theme;
      for (const entry of controlElements) {
        entry.host.dataset.theme = state.theme;
        if (entry.select) entry.select.value = state[entry.name];
        for (const button of entry.buttons || []) button.setAttribute('aria-pressed', String(button.dataset.nrkValue === state[entry.name]));
      }
    }
    function setState(patch) {
      if (!patch || typeof patch !== 'object' || Array.isArray(patch)) throw Error('Report state must be an object.');
      const changed = [];
      for (const [name, value] of Object.entries(patch)) {
        if (name === 'theme') { if (!['dark', 'light'].includes(value)) throw Error('Unknown report theme: ' + value); }
        else if (!own(controls, name) || typeof value !== 'string' || !own(controls[name].options, value)) throw Error('Unknown report control value: ' + name + '=' + value);
        if (state[name] !== value) changed.push(name);
      }
      if (!changed.length) return state;
      state = Object.freeze({...state, ...patch});
      syncControls();
      syncURL();
      for (const item of figures) if (changed.includes('theme') || changed.some(name => item.relevant.includes(name))) item.render();
      for (const callback of listeners) callback(state, Object.freeze([...changed]));
      return state;
    }
    function resizeFigure(item) {
      if (item.spec.type !== 'table' && item.host.clientWidth > 0 && layoutWidth(item.host) !== item.width) item.render();
    }
    const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(entries => {
      for (const entry of entries) {
        const item = figures.find(figure => figure.host === entry.target);
        if (item) resizeFigure(item);
      }
    }) : null;
    if (!resizeObserver) {
      let queued = false;
      window.addEventListener('resize', () => {
        if (queued) return;
        queued = true;
        const resize = () => { queued = false; for (const item of figures) resizeFigure(item); };
        if (typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(resize);
        else resize();
      });
    }
    const defaultHost = resolve(config.controlsHost || '[data-naia-report-controls]');
    if (defaultHost) defaultHost.classList.add('nrk-controls');
    for (const name of controlNames) {
      const control = controls[name], supplied = control.selector ? resolve(control.selector) : null;
      if (supplied && supplied.tagName === 'SELECT') {
        supplied.addEventListener('change', () => setState({[name]: supplied.value}));
        controlElements.push({name, host: supplied, select: supplied});
      } else if (supplied || defaultHost) {
        const mount = supplied || defaultHost, group = element('div', undefined, 'nrk-control'), options = element('div', undefined, 'nrk-control-options'), buttons = [];
        group.append(element('span', control.label || name, 'nrk-control-label'));
        options.setAttribute('role', 'group');
        options.setAttribute('aria-label', control.label || name);
        for (const [value, text] of Object.entries(control.options)) {
          const button = element('button', text);
          button.type = 'button';
          button.dataset.nrkControl = name;
          button.dataset.nrkValue = value;
          button.addEventListener('click', () => setState({[name]: value}));
          buttons.push(button);
          options.append(button);
        }
        group.append(options);
        mount.append(group);
        controlElements.push({name, host: mount, buttons});
        mount.classList.add('nrk-controls');
      }
    }
    window.addEventListener('hashchange', () => {
      const params = new URLSearchParams(location.hash.slice(1)), patch = {};
      for (const name of controlNames) if (params.get(name) !== null && own(controls[name].options, params.get(name))) patch[name] = params.get(name);
      if (['dark', 'light'].includes(params.get('theme'))) patch.theme = params.get('theme');
      setState(patch);
    });
    syncControls();
    syncURL();
    return Object.freeze({
      figure,
      get state() { return state; },
      setState,
      rows(name, filters) {
        const allRows = tableRows(name), names = relevantControls(allRows);
        if (typeof filters === 'function') return selectedRows(name, names, filters).map(row => ({...row}));
        const values = filters && typeof filters === 'object' && !Array.isArray(filters) ? filters : {};
        return allRows.filter(row => names.every(name => !own(row, name) || row[name] === (own(values, name) ? values[name] : state[name])) && Object.entries(values).every(([name, value]) => own(row, name) && row[name] === value)).map(row => ({...row}));
      },
      onChange(callback) {
        if (typeof callback !== 'function') throw Error('Report change callback must be a function.');
        listeners.add(callback);
        return () => listeners.delete(callback);
      }
    });
  }

  window.NAIAReport = Object.freeze({init});
})();
