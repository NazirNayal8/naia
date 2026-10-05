/* Generic NAIA Lens graph viewer.
 * Palette, nested left-to-right layout, drag controls, camera and pulse design
 * follow tools/arch_viz_ui.js. Saved evidence is the only source of arrows.
 */
(() => {
  'use strict';
  const LEVELS = ['Pipeline', 'Modules', 'Blocks', 'Operations'];
  const PAD = 22, HEAD = 54, ROW_GAP = 24, COL_GAP = 82;
  const text = value => value == null ? '' : String(value);
  const short = (value, limit = 30) => {
    const s = text(value); return s.length > limit ? s.slice(0, limit - 1) + '…' : s;
  };
  const count = value => Number.isFinite(value) ? value.toLocaleString('en-US') : '—';

  function shapeSummary(value) {
    const shapes = [];
    function visit(item, depth = 0) {
      if (depth > 12 || shapes.length >= 8 || item == null) return;
      if (Array.isArray(item)) { item.forEach(x => visit(x, depth + 1)); return; }
      if (typeof item !== 'object') return;
      if (Array.isArray(item.shape)) {
        shapes.push(item.shape.length ? item.shape.map(text).join(' × ') : 'scalar');
      } else Object.values(item).forEach(x => visit(x, depth + 1));
    }
    visit(value);
    return shapes.join(' · ');
  }

  function prepareGraph(data) {
    if (!data || data.schema_version !== 1 || !Array.isArray(data.nodes) || !data.nodes.length)
      throw Error('Expected a saved architecture with schema_version=1 and nodes.');
    const model = { data, nodes: new Map(), children: new Map(), roots: [], chains: new Map(), calls: new Map(), fxModules: new Map() };
    for (const n of data.nodes) {
      if (!n || typeof n.id !== 'string' || !n.id || model.nodes.has(n.id)) throw Error('Invalid component identity.');
      model.nodes.set(n.id, n); model.children.set(n.id, []); model.calls.set(n.id, []);
    }
    for (const n of data.nodes) {
      if (n.parent == null) model.roots.push(n.id);
      else {
        if (!model.nodes.has(n.parent)) throw Error('Unknown parent component.');
        model.children.get(n.parent).push(n.id);
      }
      const chain = [], seen = new Set();
      let current = n.id;
      while (current != null) {
        if (seen.has(current) || !model.nodes.has(current)) throw Error('Invalid component hierarchy.');
        seen.add(current); chain.unshift(current); current = model.nodes.get(current).parent;
      }
      model.chains.set(n.id, chain);
      if (n.type === 'call_module' && typeof n.module_path === 'string') {
        if (!model.fxModules.has(n.module_path)) model.fxModules.set(n.module_path, []);
        model.fxModules.get(n.module_path).push(n.id);
      }
    }
    model.edges = data.edges || []; model.events = data.events || [];
    if (!Array.isArray(model.edges) || !Array.isArray(model.events)) throw Error('Invalid saved execution evidence.');
    for (const e of model.edges) {
      if (!e || !model.nodes.has(e.source) || !model.nodes.has(e.target) || !['traced', 'declared'].includes(e.evidence))
        throw Error('Dependency arrows need saved traced or declared evidence.');
    }
    model.events.forEach((e, index) => {
      if (!e || !model.nodes.has(e.node)) throw Error('Observed call references an unknown component.');
      model.calls.get(e.node).push({ event: e, index });
    });
    return model;
  }

  function expanded(model, id, state) {
    if (!model.children.get(id).length) return false;
    if (state.expand.has(id)) return state.expand.get(id);
    return state.granularity === 3 || model.chains.get(id).length - 1 < state.granularity;
  }

  function visibleOf(model, id, state) {
    for (const ancestor of model.chains.get(id)) {
      if (ancestor === id || !expanded(model, ancestor, state)) return ancestor;
    }
    return id;
  }

  function childUnder(model, id, parent) {
    const chain = model.chains.get(id);
    if (parent == null) return chain[0];
    const index = chain.indexOf(parent);
    return index >= 0 && index + 1 < chain.length ? chain[index + 1] : null;
  }

  function rankNodes(ids, pairs) {
    const successors = new Map(ids.map(id => [id, []])), state = new Map(), topo = [], forward = [];
    for (const [a, b] of pairs) if (a !== b) successors.get(a).push(b);
    function visit(id) {
      state.set(id, 1);
      for (const next of successors.get(id)) {
        if (state.get(next) === 1) continue; // Keep cyclic arrows; omit their back edges only from layout ranking.
        forward.push([id, next]);
        if (!state.get(next)) visit(next);
      }
      state.set(id, 2); topo.push(id);
    }
    ids.forEach(id => { if (!state.get(id)) visit(id); });
    topo.reverse();
    const preds = new Map(ids.map(id => [id, []])), nexts = new Map(ids.map(id => [id, []]));
    for (const [a, b] of forward) { preds.get(b).push(a); nexts.get(a).push(b); }
    const rank = new Map();
    for (const id of topo) rank.set(id, preds.get(id).reduce((r, p) => Math.max(r, rank.get(p) + 1), 0));
    for (const id of [...topo].reverse()) {
      if (nexts.get(id).length) rank.set(id, Math.max(0, Math.min(...nexts.get(id).map(n => rank.get(n))) - 1));
    }
    return rank;
  }

  function liftEdges(model, state) {
    const merged = new Map();
    for (const edge of model.edges) {
      const a = visibleOf(model, edge.source, state), b = visibleOf(model, edge.target, state);
      if (a === b && edge.source !== edge.target) continue;
      const key = JSON.stringify([a, b, edge.evidence, edge.kind || null, edge.comparison_id || null]);
      if (!merged.has(key)) merged.set(key, { key, a, b, evidence: edge.evidence, members: [] });
      merged.get(key).members.push(edge);
    }
    return [...merged.values()];
  }

  function layoutGraph(model, state) {
    function group(parent, kids) {
      const sizes = new Map(), inner = new Map(), pairs = [], seen = new Set();
      for (const id of kids) {
        if (expanded(model, id, state)) {
          const sub = group(id, model.children.get(id));
          inner.set(id, sub); sizes.set(id, { w: Math.max(240, sub.w + PAD * 2), h: sub.h + HEAD + PAD });
        } else {
          const n = model.nodes.get(id);
          sizes.set(id, { w: Math.min(258, Math.max(156, text(n.label || id).length * 7 + 38)), h: 96 });
        }
      }
      for (const e of model.edges) {
        const a = childUnder(model, e.source, parent), b = childUnder(model, e.target, parent);
        const key = JSON.stringify([a, b]);
        if (a && b && a !== b && sizes.has(a) && sizes.has(b) && !seen.has(key)) {
          seen.add(key); pairs.push([a, b]);
        }
      }
      const rank = rankNodes(kids, pairs), columns = [];
      // With no dependency evidence, use a compact grid, without inventing arrows or an execution order.
      if (!pairs.length && kids.length > 8) {
        const columnCount = Math.min(4, Math.ceil(Math.sqrt(kids.length)));
        kids.forEach((id, index) => {
          const column = Math.floor(index / Math.ceil(kids.length / columnCount));
          (columns[column] ||= []).push(id);
        });
      } else kids.forEach(id => { (columns[rank.get(id)] ||= []).push(id); });
      const neighbors = new Map(kids.map(id => [id, []]));
      for (const [a, b] of pairs) { neighbors.get(a).push(b); neighbors.get(b).push(a); }
      const centers = new Map(), widths = [], xs = [];
      let x = 0;
      columns.forEach((column, index) => {
        widths[index] = Math.max(...column.map(id => sizes.get(id).w));
        xs[index] = x; x += widths[index] + COL_GAP;
        const h = column.reduce((sum, id) => sum + sizes.get(id).h + ROW_GAP, -ROW_GAP);
        let y = -h / 2;
        column.forEach(id => { centers.set(id, y + sizes.get(id).h / 2); y += sizes.get(id).h + ROW_GAP; });
      });
      for (let sweep = 0; sweep < 4; sweep++) {
        const order = sweep % 2 ? [...columns.keys()].reverse() : [...columns.keys()];
        for (const index of order) {
          const column = columns[index]; if (!column) continue;
          const want = new Map(column.map(id => {
            const ns = neighbors.get(id).filter(n => rank.get(n) !== rank.get(id));
            return [id, ns.length ? ns.reduce((sum, n) => sum + centers.get(n), 0) / ns.length : centers.get(id)];
          }));
          column.sort((a, b) => want.get(a) - want.get(b));
          const tops = []; let bottom = -Infinity;
          column.forEach(id => {
            const top = Math.max(want.get(id) - sizes.get(id).h / 2, bottom + ROW_GAP);
            tops.push(top); bottom = top + sizes.get(id).h;
          });
          const drift = column.reduce((sum, id, i) => sum + tops[i] + sizes.get(id).h / 2 - want.get(id), 0) / column.length;
          column.forEach((id, i) => centers.set(id, tops[i] - drift + sizes.get(id).h / 2));
        }
      }
      const top = Math.min(...kids.map(id => centers.get(id) - sizes.get(id).h / 2));
      const bottom = Math.max(...kids.map(id => centers.get(id) + sizes.get(id).h / 2));
      const positions = new Map();
      columns.forEach((column, index) => column.forEach(id => {
        const size = sizes.get(id);
        positions.set(id, { x: xs[index] + (widths[index] - size.w) / 2, y: centers.get(id) - size.h / 2 - top, ...size });
      }));
      return { positions, inner, w: Math.max(0, x - COL_GAP), h: Math.max(0, bottom - top) };
    }
    const tree = group(null, model.roots), boxes = new Map();
    function place(tree, ox, oy) {
      for (const [id, p] of tree.positions) {
        const offset = state.offsets.get(id) || [0, 0], container = tree.inner.has(id);
        const box = { x: ox + p.x + offset[0], y: oy + p.y + offset[1], w: p.w, h: p.h, container };
        boxes.set(id, box);
        if (container) place(tree.inner.get(id), box.x + PAD, box.y + HEAD);
      }
    }
    function grow(id) {
      const box = boxes.get(id); if (!box || !box.container) return;
      for (const child of model.children.get(id)) {
        grow(child);
        const b = boxes.get(child); if (!b) continue;
        const right = Math.max(box.x + box.w, b.x + b.w + PAD), bottom = Math.max(box.y + box.h, b.y + b.h + PAD);
        box.x = Math.min(box.x, b.x - PAD); box.y = Math.min(box.y, b.y - HEAD);
        box.w = right - box.x; box.h = bottom - box.y;
      }
    }
    place(tree, 0, 0); model.roots.forEach(grow);
    return boxes;
  }

  function comparisonGraph(captures, playbackId) {
    const byId = new Map(), maps = new Map(), edges = [], changes = new Map(), tones = [4, 5, 2];
    const stable = value => JSON.stringify(value, (_key, v) => v && typeof v === 'object' && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v);
    captures.forEach((capture, index) => {
      const model = prepareGraph(capture.data), ids = new Map(); maps.set(capture.id, ids);
      for (const n of capture.data.nodes) ids.set(n.id, 'compare:' + (n.evidence === 'traced' ? 'fx:' + n.id
        : typeof n.module_path === 'string' ? 'module:' + n.module_path : 'id:' + n.id));
      for (const n of capture.data.nodes) {
        const id = ids.get(n.id), parent = n.parent == null ? null : ids.get(n.parent);
        const calls = model.calls.get(n.id), outputs = n.outputs || (calls.length ? calls[calls.length - 1].event.outputs : null);
        const variant = { id: capture.id, title: capture.title, tone: tones[index % tones.length], node: n,
          outputs, observed_calls: calls.length };
        if (!byId.has(id)) byId.set(id, { ...n, id, parent, comparison: [] });
        byId.get(id).comparison.push(variant);
        if (!changes.has(id)) changes.set(id, []);
        changes.get(id).push({ type: n.type, parameters: n.parameters, outputs, parent,
          shared_with: n.shared_with ? ids.get(n.shared_with) : null });
      }
      for (const e of capture.data.edges || []) edges.push({ ...e, source: ids.get(e.source), target: ids.get(e.target),
        comparison_id: capture.id, comparison_tone: tones[index % tones.length] });
    });
    for (const [id, node] of byId) {
      const records = changes.get(id);
      node.comparison_changes = ['type', 'parameters', 'outputs', 'parent', 'shared_with']
        .filter(key => new Set(records.map(record => stable(record[key]))).size > 1);
      if (node.comparison.length < captures.length) node.comparison_changes.unshift('presence');
    }
    const playback = captures.find(capture => capture.id === playbackId) || captures[0];
    const events = (playback.data.events || []).map(event => ({ ...event, node: maps.get(playback.id).get(event.node) }));
    return { data: { schema_version: 1, capture_mode: 'comparison', nodes: [...byId.values()], edges, events, warnings: [] }, maps };
  }

  // Pure graph behavior can also be verified without a browser or PyTorch.
  if (typeof module === 'object' && module.exports) {
    module.exports = { prepareGraph, shapeSummary, rankNodes, visibleOf, liftEdges, layoutGraph, comparisonGraph };
    return;
  }

  const $ = id => document.getElementById(id);
  const svg = $('graph'), reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const integrated = ['/architecture', '/architecture/'].includes(location.pathname);
  const panelMode = integrated && new URLSearchParams(location.search).get('panel') === '1';
  const S = {
    model: null, granularity: 1, expand: new Map(), offsets: new Map(), bends: new Map(),
    boxes: new Map(), nodeEls: new Map(), edgeEls: new Map(), selected: null, selectedEdge: null,
    camera: { cx: 0, cy: 0, scale: 1 }, drag: null, matches: [], matchIndex: -1,
    anim: { index: -1, playing: false, timer: null, epoch: 0, active: new Set(), rank: new Map(), stages: [] },
    currentId: null, library: [], graphs: new Map(), mode: 'single', comparisonLayout: 'side', compareIds: [],
    compareCaptures: [], compareMaps: new Map(), panels: new Map(), playbackId: null, loadVersion: 0, storageKey: null
  };
  function storageKey(id, data) {
    let hash = 2166136261;
    for (const char of JSON.stringify(data)) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
    return 'naia.lens.v1:' + id + ':' + (hash >>> 0).toString(16);
  }
  function saveView() {
    if (!S.storageKey) return;
    try { localStorage.setItem(S.storageKey, JSON.stringify({ granularity: S.granularity,
      expand: [...S.expand], offsets: [...S.offsets], bends: [...S.bends], theme: $('lens').dataset.theme,
      labels: $('edge-labels').value })); } catch (_error) { /* Storage can be unavailable in private sessions. */ }
  }
  function restoreView(id, data) {
    S.storageKey = storageKey(id, data); S.expand.clear(); S.offsets.clear(); S.bends.clear();
    S.granularity = 1;
    try {
      const saved = JSON.parse(localStorage.getItem(S.storageKey) || '{}');
      if (Number.isInteger(saved.granularity) && saved.granularity >= 0 && saved.granularity <= 3) S.granularity = saved.granularity;
      for (const [key, value] of saved.expand || []) if (S.model.nodes.has(key) && typeof value === 'boolean') S.expand.set(key, value);
      for (const field of ['offsets', 'bends']) for (const [key, value] of saved[field] || [])
        if (typeof key === 'string' && Array.isArray(value) && value.length === 2 && value.every(n => Number.isFinite(n) && Math.abs(n) < 1e7)) S[field].set(key, value);
      if (['dark', 'light'].includes(saved.theme)) setTheme(saved.theme);
      if (['changes', 'all', 'off'].includes(saved.labels)) $('edge-labels').value = saved.labels;
    } catch (_error) { /* Ignore malformed or obsolete browser preferences. */ }
  }
  function sideBySide() { return S.mode === 'compare' && S.comparisonLayout === 'side'; }
  function panelControl(action, value, onlyId) {
    if (!sideBySide()) return false;
    for (const [id, frame] of S.panels) if (!onlyId || onlyId === id)
      frame.contentWindow.postMessage({ type: 'naia-lens-control', action, value }, location.origin);
    return true;
  }
  function setTheme(theme) {
    $('lens').dataset.theme = theme; const light = theme === 'light';
    $('theme').textContent = light ? 'Dark' : 'Light'; $('theme').setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
    panelControl('theme', theme);
  }
  function element(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined) el.textContent = text(value);
    if (className) el.className = className;
    return el;
  }
  function svgEl(tag, attributes = {}, value) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, text(value));
    if (value !== undefined) el.textContent = text(value);
    return el;
  }
  function tone(id) {
    const node = S.model.nodes.get(id);
    const family = text(node.module_path || node.label || node.type).toLowerCase();
    if (/encoder|embedding|conv/.test(family)) return 0;
    if (/projector|projection|linear/.test(family)) return 1;
    if (/conditioning|action/.test(family)) return 2;
    if (/dynamics|predictor|attention/.test(family)) return 3;
    if (node.evidence === 'traced') return node.type === 'placeholder' ? 4 : node.type === 'output' ? 5 : 1;
    const chain = S.model.chains.get(id), branch = chain.length > 1 ? chain[1] : id;
    const peers = chain.length > 1 ? S.model.children.get(chain[0]) : S.model.roots;
    return Math.max(0, peers.indexOf(branch)) % 6;
  }
  function lastOutput(id) {
    const n = S.model.nodes.get(id), calls = S.model.calls.get(id);
    return n.outputs || (calls.length ? calls[calls.length - 1].event.outputs : null);
  }
  function nodeShape(node, box) {
    let type = text(node.type);
    if (type === 'call_module' && node.module_path) {
      const structural = [...S.model.nodes.values()].find(n => n.evidence !== 'traced' && n.module_path === node.module_path);
      if (structural) type = text(structural.type);
    }
    const w = box.w, h = box.h;
    if (/conv\d[d]?/i.test(type)) return svgEl('path', { d: 'M0 0 L' + w + ' ' + h * .18 + ' L' + w + ' ' + h * .82 + ' L0 ' + h + ' Z', class: 'av-shape' });
    if (/linear/i.test(type)) {
      const firstShape = (value, depth = 0) => {
        if (depth > 12 || !value || typeof value !== 'object') return null;
        if (Array.isArray(value.shape)) return value.shape;
        for (const child of Object.values(value)) { const found = firstShape(child, depth + 1); if (found) return found; }
        return null;
      };
      const calls = S.model.calls.get(node.id), input = calls.length ? firstShape(calls[calls.length - 1].event.inputs) : null;
      const output = firstShape(lastOutput(node.id)), a = input?.at(-1), b = output?.at(-1);
      if (Number.isFinite(a) && Number.isFinite(b) && a !== b) return svgEl('path', { d: b > a
        ? 'M0 ' + h * .2 + ' L' + w + ' 0 L' + w + ' ' + h + ' L0 ' + h * .8 + ' Z'
        : 'M0 0 L' + w + ' ' + h * .2 + ' L' + w + ' ' + h * .8 + ' L0 ' + h + ' Z', class: 'av-shape' });
      return svgEl('path', { d: 'M0 0 L' + (w - 16) + ' 0 L' + w + ' ' + h / 2 + ' L' + (w - 16) + ' ' + h + ' L0 ' + h + ' L16 ' + h / 2 + ' Z', class: 'av-shape' });
    }
    if (/attention/i.test(type)) return svgEl('ellipse', { cx: w / 2, cy: h / 2, rx: w / 2, ry: h / 2, class: 'av-shape' });
    if (node.type === 'call_function' || node.type === 'call_method')
      return svgEl('ellipse', { cx: box.w / 2, cy: box.h / 2, rx: box.w / 2, ry: box.h / 2, class: 'av-shape' });
    if (node.type === 'placeholder' || node.type === 'output')
      return svgEl('polygon', { points: '14,0 ' + (box.w - 14) + ',0 ' + box.w + ',' + box.h / 2 + ' ' + (box.w - 14) + ',' + box.h + ' 14,' + box.h + ' 0,' + box.h / 2, class: 'av-shape' });
    return svgEl('rect', { width: box.w, height: box.h, rx: /norm|relu|gelu|silu/i.test(text(node.type)) ? 24 : 10, class: 'av-shape' });
  }
  function hookNode(group, id) {
    group.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.target.closest('.av-toggle')) return;
      event.preventDefault(); event.stopPropagation(); pause();
      select(id, false);
      S.drag = { kind: 'node', id, x: event.clientX, y: event.clientY, start: S.offsets.get(id) || [0, 0] };
      svg.setPointerCapture(event.pointerId); group.classList.add('dragging');
    });
    group.addEventListener('dblclick', event => { event.preventDefault(); toggle(id); });
    group.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); toggle(id); }
    });
    group.addEventListener('focus', () => select(id, false));
  }
  function drawNode(id, box) {
    const node = S.model.nodes.get(id);
    const group = svgEl('g', { class: 'av-node tone-' + tone(id), transform: 'translate(' + box.x + ' ' + box.y + ')',
      tabindex: 0, role: 'button', 'aria-label': text(node.label || id) + ', ' + text(node.type || 'component'),
      'data-node': id });
    group.append(svgEl('title', {}, text(node.label || id) + '\n' + text(node.module_path || id)));
    if (box.container) {
      group.append(svgEl('rect', { width: box.w, height: box.h, rx: 12, class: 'av-box' }));
      group.append(svgEl('rect', { width: box.w, height: HEAD, rx: 12, fill: 'transparent', class: 'av-box-head' }));
      group.append(svgEl('text', { x: 15, y: 23, class: 'av-box-title' }, short(node.label || id, 40)));
      group.append(svgEl('text', { x: 15, y: 41, class: 'av-box-sub' },
        short(node.type || 'module', 28) + ' · ' + S.model.children.get(id).length + ' children'));
    } else {
      group.append(nodeShape(node, box));
      group.append(svgEl('text', { x: 14, y: 25, class: 'av-title' }, short(node.label || id, Math.floor((box.w - 32) / 7))));
      group.append(svgEl('text', { x: 14, y: 44, class: 'av-badge' }, short(node.type || node.evidence || 'component', 27)));
      const shape = shapeSummary(lastOutput(id));
      group.append(svgEl('text', { x: 14, y: 65, class: 'av-size' }, short(shape || (node.parameters != null ? count(node.parameters) + ' params' : ''), 31)));
      const calls = S.model.calls.get(id).length;
      group.append(svgEl('text', { x: 14, y: 83, class: 'av-badge' },
        calls ? calls + ' observed call' + (calls === 1 ? '' : 's') : node.evidence === 'traced' ? 'FX traced' : 'structure'));
    }
    if (S.model.children.get(id).length) {
      const toggleEl = svgEl('g', { class: 'av-toggle', transform: 'translate(' + (box.w - 17) + ' 17)' });
      toggleEl.append(svgEl('circle', { r: 9 }), svgEl('text', { x: 0, y: 4, 'text-anchor': 'middle' }, box.container ? '−' : '+'));
      toggleEl.addEventListener('pointerdown', event => event.stopPropagation());
      toggleEl.addEventListener('click', event => { event.stopPropagation(); toggle(id); });
      group.append(toggleEl);
      group.setAttribute('aria-expanded', String(box.container));
    }
    if (S.mode === 'compare' && node.comparison) {
      node.comparison.forEach((variant, index) => group.append(svgEl('rect', { x: -3 - index * 3, y: -3 - index * 3,
        width: box.w + 6 + index * 6, height: box.h + 6 + index * 6, rx: 12, class: 'av-compare-ring tone-' + variant.tone })));
      if (node.comparison_changes.length) group.append(svgEl('circle', { cx: box.w + 3, cy: 4, r: 6, class: 'av-diff-ring' }));
    }
    hookNode(group, id); S.nodeEls.set(id, group);
    (box.container ? $('boxes') : $('nodes')).append(group);
  }
  function edgePath(a, b, bend, offset = 0) {
    const sx = a.x + a.w, sy = a.y + a.h / 2 + offset, tx = b.x - 3, ty = b.y + b.h / 2 + offset;
    if (a === b) return 'M ' + sx + ' ' + sy + ' C ' + (sx + 100) + ' ' + (sy - 90) + ', ' + (sx + 100) + ' ' + (sy + 90) + ', ' + sx + ' ' + (sy + 12);
    if (bend) {
      const wx = (sx + tx) / 2 + bend[0], wy = (sy + ty) / 2 + bend[1], k = 55;
      return 'M ' + sx + ' ' + sy + ' C ' + (sx + k) + ' ' + sy + ', ' + (wx - k) + ' ' + wy + ', ' + wx + ' ' + wy +
        ' C ' + (wx + k) + ' ' + wy + ', ' + (tx - k) + ' ' + ty + ', ' + tx + ' ' + ty;
    }
    const k = Math.max(36, Math.abs(tx - sx) * .5), dip = tx <= sx ? 52 : 0;
    return 'M ' + sx + ' ' + sy + ' C ' + (sx + k) + ' ' + (sy + dip) + ', ' + (tx - k) + ' ' + (ty + dip) + ', ' + tx + ' ' + ty;
  }
  function drawEdges() {
    $('edges').replaceChildren(); S.edgeEls.clear();
    const lifted = liftEdges(S.model, S), parallel = new Map();
    for (const edge of lifted) {
      const a = S.boxes.get(edge.a), b = S.boxes.get(edge.b); if (!a || !b) continue;
      const pair = JSON.stringify([edge.a, edge.b]), lane = parallel.get(pair) || 0;
      parallel.set(pair, lane + 1);
      const d = edgePath(a, b, S.bends.get(edge.key), lane * 10);
      const variant = S.mode === 'compare' ? edge.members[0].comparison_tone : null;
      const marker = variant == null ? edge.evidence : 'compare-' + variant;
      const path = svgEl('path', { d, class: 'av-edge ' + edge.evidence + (variant == null ? '' : ' tone-' + variant), 'marker-end': 'url(#arrow-' + marker + ')' });
      const hit = svgEl('path', { d, class: 'av-edge-hit', 'aria-label': edge.evidence + ' dependency', tabindex: 0 });
      hit.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        event.preventDefault(); event.stopPropagation(); pause(); selectEdge(edge);
        S.drag = { kind: 'edge', id: edge.key, x: event.clientX, y: event.clientY, start: S.bends.get(edge.key) || [0, 0] };
        svg.setPointerCapture(event.pointerId);
      });
      hit.addEventListener('keydown', event => { if (event.key === 'Enter') selectEdge(edge); });
      const title = svgEl('title', {}, edge.evidence + ': ' + edge.members.map(e => e.source + ' → ' + e.target).join('\n'));
      path.append(title); $('edges').append(path, hit);
      S.edgeEls.set(edge.key, { edge, path });
      if (edge.members.length > 1) {
        $('edges').append(svgEl('text', { x: (a.x + a.w + b.x) / 2, y: (a.y + a.h / 2 + b.y + b.h / 2) / 2 - 8, class: 'av-elabel' }, '×' + edge.members.length));
      }
      const shape = shapeSummary(edge.members[0].shape || S.model.nodes.get(edge.members[0].source).outputs);
      const sourceShape = shapeSummary(S.model.nodes.get(edge.members[0].source).outputs);
      const targetShape = shapeSummary(S.model.nodes.get(edge.members[0].target).outputs);
      if (shape && ($('edge-labels').value === 'all' || ($('edge-labels').value === 'changes' && sourceShape !== targetShape)))
        $('edges').append(svgEl('text', { x: (a.x + a.w + b.x) / 2, y: (a.y + a.h / 2 + b.y + b.h / 2) / 2 + 17, 'text-anchor': 'middle', class: 'av-elabel' }, short(shape, 36)));
    }
    const shown = lifted.reduce((sum, e) => sum + e.members.length, 0), hidden = S.model.edges.length - shown;
    $('edge-status').textContent = S.model.edges.length
      ? S.model.edges.length + ' saved dependencies' + (hidden ? ' · ' + hidden + ' inside collapsed blocks' : '')
      : 'No dependency edges in this capture';
  }
  function renderSelection() {
    for (const [id, el] of S.nodeEls) {
      const representative = S.selected ? visibleOf(S.model, S.selected, S) : null;
      el.classList.toggle('selected', id === S.selected);
      el.classList.toggle('contains-selection', id === representative && id !== S.selected);
      el.classList.toggle('match', S.matches.some(match => visibleOf(S.model, match, S) === id));
      el.classList.toggle('reached', [...S.anim.active].some(active => visibleOf(S.model, active, S) === id));
    }
    for (const { edge, path } of S.edgeEls.values()) path.classList.toggle('selected', edge.key === S.selectedEdge);
  }
  function rebuild(refit = false) {
    S.anim.epoch++; $('pulses').replaceChildren();
    S.boxes = layoutGraph(S.model, S); S.nodeEls.clear();
    $('boxes').replaceChildren(); $('nodes').replaceChildren();
    for (const [id, box] of S.boxes) if (box.container) drawNode(id, box);
    for (const [id, box] of S.boxes) if (!box.container) drawNode(id, box);
    drawEdges(); renderSelection();
    for (const button of $('levels').querySelectorAll('button')) button.setAttribute('aria-pressed', String(Number(button.dataset.level) === S.granularity));
    if (refit) fit(); else applyCamera();
    paintActiveEdges(false);
  }
  function bounds() {
    const boxes = [...S.boxes.values()];
    return { x0: Math.min(...boxes.map(b => b.x)), y0: Math.min(...boxes.map(b => b.y)),
      x1: Math.max(...boxes.map(b => b.x + b.w)), y1: Math.max(...boxes.map(b => b.y + b.h)) };
  }
  function viewport() {
    const r = svg.getBoundingClientRect(); return { w: r.width || 800, h: r.height || 520 };
  }
  function applyCamera() {
    const { w, h } = viewport(), { cx, cy, scale } = S.camera;
    svg.setAttribute('viewBox', [cx - w / (2 * scale), cy - h / (2 * scale), w / scale, h / scale].join(' '));
  }
  function fit() {
    if (panelControl('fit')) return;
    if (!S.boxes.size) return;
    const b = bounds(), { w, h } = viewport();
    S.camera = { cx: (b.x0 + b.x1) / 2, cy: (b.y0 + b.y1) / 2,
      scale: Math.max(.025, Math.min(1.4, w / (b.x1 - b.x0 + 100), h / (b.y1 - b.y0 + 100))) };
    applyCamera();
  }
  function world(event) {
    const r = svg.getBoundingClientRect(), c = S.camera;
    return { x: c.cx + (event.clientX - r.left - r.width / 2) / c.scale, y: c.cy + (event.clientY - r.top - r.height / 2) / c.scale };
  }
  function zoomBy(factor, around) {
    if (panelControl('zoom', factor)) return;
    const old = S.camera.scale, next = Math.max(.025, Math.min(5, old * factor));
    if (around) {
      S.camera.cx = around.x - (around.x - S.camera.cx) * old / next;
      S.camera.cy = around.y - (around.y - S.camera.cy) * old / next;
    }
    S.camera.scale = next; applyCamera();
  }
  function reveal(id) {
    const box = S.boxes.get(visibleOf(S.model, id, S)); if (!box) return;
    S.camera.cx = box.x + box.w / 2; S.camera.cy = box.y + Math.min(box.h / 2, 120);
    S.camera.scale = Math.max(.65, S.camera.scale); applyCamera();
  }
  function toggle(id) {
    if (!S.model.children.get(id).length) { select(id); return; }
    pause(); S.expand.set(id, !expanded(S.model, id, S)); rebuild(true); select(id, false); saveView();
  }
  function setLevel(level) {
    pause(); S.granularity = Math.max(0, Math.min(3, level)); S.expand.clear();
    panelControl('level', S.granularity); rebuild(true); saveView();
  }
  function addRow(table, key, value) {
    const row = element('tr'); row.append(element('th', key), element('td', value)); table.append(row);
  }
  function jsonBlock(value) { return element('pre', JSON.stringify(value, null, 2)); }
  function select(id, focus = true) {
    S.selected = id; S.selectedEdge = null; renderSelection(); inspectNode(id);
    if (focus) reveal(id);
    if (panelMode) parent.postMessage({ type: 'naia-lens-selection', node: id }, location.origin);
  }
  function selectEdge(edge) {
    S.selected = null; S.selectedEdge = edge.key; renderSelection();
    $('detail-title').textContent = edge.evidence + ' dependency';
    $('detail-summary').textContent = edge.members.length + ' saved edge' + (edge.members.length === 1 ? '' : 's');
    $('detail').replaceChildren(jsonBlock(edge.members));
    if (panelMode) parent.postMessage({ type: 'naia-lens-edge-selection', source: edge.members[0].source,
      target: edge.members[0].target, evidence: edge.evidence }, location.origin);
  }
  function inspectNode(id) {
    const node = S.model.nodes.get(id), calls = S.model.calls.get(id), detail = $('detail');
    $('detail-title').textContent = text(node.label || id);
    $('detail-summary').textContent = text(node.type || 'component') + ' · ' + text(node.evidence || 'structural');
    detail.replaceChildren();
    const table = element('table', undefined, 'av-kv');
    addRow(table, 'ID', S.mode === 'compare' && node.comparison ? node.comparison[0].node.id : node.id);
    addRow(table, 'Path', node.module_path == null ? '—' : node.module_path || '(model root)');
    addRow(table, 'Parameters', node.parameters == null ? '—' : count(node.parameters));
    addRow(table, 'Outputs', shapeSummary(lastOutput(id)) || '—');
    if (node.shared_with) addRow(table, 'Shared with', node.shared_with);
    detail.append(table);
    if (S.mode === 'compare' && node.comparison) {
      detail.append(element('h3', 'Captured differences'));
      detail.append(element('p', node.comparison_changes.length ? node.comparison_changes.join(', ') : 'Matching recorded metadata', 'av-note'));
      for (const variant of node.comparison) {
        const card = element('div', undefined, 'av-variant tone-' + variant.tone);
        card.append(element('strong', variant.title), jsonBlock({ type: variant.node.type, parameters: variant.node.parameters,
          outputs: variant.outputs, parent: variant.node.parent, observed_calls: variant.observed_calls }));
        detail.append(card);
      }
    }
    const children = S.model.children.get(id);
    if (children.length) {
      detail.append(element('h3', 'Children'));
      const list = element('div');
      for (const child of children) {
        const button = element('button', text(S.model.nodes.get(child).label || child), 'av-link');
        button.type = 'button'; button.addEventListener('click', () => {
          S.model.chains.get(child).slice(0, -1).forEach(ancestor => S.expand.set(ancestor, true));
          rebuild(); select(child);
        });
        list.append(button, element('br'));
      }
      detail.append(list);
    }
    detail.append(element('h3', 'Recorded metadata'), jsonBlock(S.mode === 'compare' && node.comparison
      ? node.comparison.map(variant => ({ capture: variant.title, node: variant.node })) : node));
    if (calls.length) {
      detail.append(element('h3', 'Observed calls'));
      if (calls.length > 80) detail.append(element('p', 'Showing the first 80 of ' + calls.length + ' calls.', 'av-note'));
      for (const { event, index } of calls.slice(0, 80)) {
        const item = element('div', undefined, 'av-call');
        item.classList.toggle('active', $('playback-mode').value === 'calls' && S.anim.index === index);
        item.append(element('strong', 'Call ' + (index + 1) + (event.call ? ' · invocation ' + event.call : '')));
        item.append(jsonBlock({ inputs: event.inputs, kwargs: event.kwargs, outputs: event.outputs }));
        detail.append(item);
      }
    }
  }
  function search() {
    const query = $('search').value.trim().toLowerCase();
    S.matches = query ? [...S.model.nodes.values()].filter(n => [n.id, n.label, n.type, n.module_path].some(v => text(v).toLowerCase().includes(query))).map(n => n.id) : [];
    S.matchIndex = -1; $('search-status').textContent = query ? S.matches.length + ' matches' : '';
    $('search-next').disabled = !S.matches.length; renderSelection();
    panelControl('search', $('search').value);
  }
  function nextMatch() {
    if (panelControl('search-next')) return;
    if (!S.matches.length) return;
    S.matchIndex = (S.matchIndex + 1) % S.matches.length;
    const id = S.matches[S.matchIndex];
    S.model.chains.get(id).slice(0, -1).forEach(ancestor => S.expand.set(ancestor, true));
    rebuild(); select(id);
    $('search-status').textContent = (S.matchIndex + 1) + ' / ' + S.matches.length;
  }

  function pulse(path) {
    if (reducedMotion.matches || typeof path.getTotalLength !== 'function') return;
    const length = path.getTotalLength(); if (!length) return;
    const dot = svgEl('circle', { r: 4.5, class: 'av-pulse' }), start = performance.now(), epoch = S.anim.epoch;
    $('pulses').append(dot);
    const duration = 760 / Number($('speed').value);
    function frame(now) {
      if (!dot.isConnected || epoch !== S.anim.epoch) { dot.remove(); return; }
      const t = Math.max(0, Math.min(1, (now - start) / duration)), point = path.getPointAtLength(length * t);
      dot.setAttribute('cx', point.x); dot.setAttribute('cy', point.y);
      if (t < 1) requestAnimationFrame(frame); else dot.remove();
    }
    requestAnimationFrame(frame);
  }
  function paintActiveEdges(animate) {
    for (const { edge, path } of S.edgeEls.values()) {
      const active = S.anim.index >= 0 && edge.members.some(e => $('playback-mode').value === 'calls'
        ? S.anim.active.has(e.target) && (!e.comparison_id || e.comparison_id === S.playbackId)
        : S.anim.rank.get(e.source) === S.anim.stages[S.anim.index] && (!e.comparison_id || e.comparison_id === S.playbackId));
      path.classList.toggle('active', active);
      if (active && animate) pulse(path);
    }
  }
  function animationLength() {
    if (sideBySide()) return Math.max(0, ...S.compareCaptures.map(capture => $('playback-mode').value === 'calls'
      ? (capture.data.events || []).length : (capture.data.edges || []).length));
    return $('playback-mode').value === 'calls' ? S.model.events.length : S.anim.stages.length;
  }
  function updatePlaybackControls() {
    const disabled = !animationLength();
    $('play').disabled = disabled; $('step').disabled = disabled; $('reset-anim').disabled = disabled;
  }
  function stepAnimation() {
    if (panelControl('step')) return;
    const length = animationLength(); if (!length) return;
    S.anim.index = (S.anim.index + 1) % length; S.anim.active.clear();
    if ($('playback-mode').value === 'calls') {
      const event = S.model.events[S.anim.index], node = S.model.nodes.get(event.node);
      S.anim.active.add(event.node);
      // A captured FX call_module can share a recorded module path. This association creates no edges.
      if (node.module_path) {
        if (S.mode === 'compare') {
          const capture = S.compareCaptures.find(item => item.id === S.playbackId), map = S.compareMaps.get(S.playbackId);
          for (const fx of capture?.data.nodes || []) if (fx.type === 'call_module' && fx.module_path === node.module_path) S.anim.active.add(map.get(fx.id));
        } else for (const id of S.model.fxModules.get(node.module_path) || []) S.anim.active.add(id);
      }
      select(event.node, false);
      $('playback-status').textContent = 'Observed call ' + (S.anim.index + 1) + ' / ' + length + ': ' + text(node.label || node.id) +
        ' · input ' + (shapeSummary(event.inputs) || '—') + ' → output ' + (shapeSummary(event.outputs) || '—') + ' · illustrative, not timing';
    } else {
      const rank = S.anim.stages[S.anim.index];
      for (const [id, value] of S.anim.rank) if (value === rank) S.anim.active.add(id);
      $('playback-status').textContent = 'Saved dependency stage ' + (S.anim.index + 1) + ' / ' + length + ' · illustrative, not timing';
    }
    renderSelection(); paintActiveEdges(true);
  }
  function pause() { panelControl('pause'); S.anim.playing = false; clearTimeout(S.anim.timer); $('play').textContent = '▶ Play'; }
  function play() {
    if (sideBySide()) {
      if (S.anim.playing) { pause(); return; }
      panelControl('play'); S.anim.playing = true; $('play').textContent = '❚❚ Pause';
      $('playback-status').textContent = 'Each capture follows its own recorded sequence · illustrative, not timing'; return;
    }
    if (S.anim.playing) { pause(); return; }
    if (!animationLength()) return;
    S.anim.playing = true; $('play').textContent = '❚❚ Pause';
    function tick() {
      if (!S.anim.playing) return;
      stepAnimation();
      S.anim.timer = setTimeout(tick, (reducedMotion.matches ? 1100 : 900) / Number($('speed').value));
    }
    tick();
  }
  function resetAnimation() {
    panelControl('reset-anim');
    pause(); S.anim.index = -1; S.anim.active.clear(); S.anim.epoch++; $('pulses').replaceChildren();
    $('playback-status').textContent = 'Playback is illustrative, not measured timing.';
    renderSelection(); paintActiveEdges(false);
    if (S.selected) inspectNode(S.selected);
  }

  function exportSvg() {
    if (panelControl('export', null, $('playback-capture').value || S.compareIds[0])) return;
    if (!S.boxes.size) return;
    const copy = svg.cloneNode(true), sourceNodes = [svg, ...svg.querySelectorAll('*')], copyNodes = [copy, ...copy.querySelectorAll('*')];
    const properties = ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-dasharray',
      'stroke-linecap', 'stroke-linejoin', 'opacity', 'font-size', 'font-family', 'font-weight', 'text-anchor'];
    sourceNodes.forEach((node, index) => {
      const target = copyNodes[index], style = getComputedStyle(node);
      for (const key of properties) target.setAttribute(key, style.getPropertyValue(key));
      target.removeAttribute('tabindex'); target.removeAttribute('class'); target.removeAttribute('id');
    });
    // Keep marker identities so exported arrows remain connected to their definitions.
    copy.querySelectorAll('marker').forEach((marker, index) => marker.id = svg.querySelectorAll('marker')[index].id);
    for (const hit of copy.querySelectorAll('[aria-label="traced dependency"],[aria-label="declared dependency"]')) hit.remove();
    const b = bounds(), width = b.x1 - b.x0 + 100, height = b.y1 - b.y0 + 100;
    copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    copy.setAttribute('viewBox', [b.x0 - 50, b.y0 - 50, width, height].join(' '));
    copy.setAttribute('width', String(Math.min(10000, Math.max(600, width))));
    copy.setAttribute('height', String(Math.min(10000, Math.max(600, width)) * height / width));
    const background = svgEl('rect', { x: b.x0 - 50, y: b.y0 - 50, width, height,
      fill: getComputedStyle($('lens')).getPropertyValue('--av-bg').trim() });
    copy.insertBefore(background, copy.firstChild);
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml' }));
    const link = element('a'); link.href = url; link.download = 'naia-' + (S.mode === 'compare' ? 'comparison' : text(S.currentId || 'lens').replace(/[^a-z0-9_-]/gi, '-')) + '.svg';
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function setModel(data, key) {
    pause(); S.model = prepareGraph(data); S.selected = null; S.selectedEdge = null;
    S.matches = []; S.matchIndex = -1; S.anim.index = -1; S.anim.active.clear();
    restoreView(key, S.mode === 'compare' ? { ...data, events: [] } : data);
    const edges = S.model.edges.filter(edge => !edge.comparison_id || edge.comparison_id === S.playbackId);
    const ids = [...new Set(edges.flatMap(edge => [edge.source, edge.target]))];
    S.anim.rank = rankNodes(ids, edges.map(edge => [edge.source, edge.target]));
    S.anim.stages = [...new Set(S.anim.rank.values())].sort((a, b) => a - b);
    const hasCalls = sideBySide() ? S.compareCaptures.some(capture => (capture.data.events || []).length) : S.model.events.length;
    const hasEdges = sideBySide() ? S.compareCaptures.some(capture => (capture.data.edges || []).length) : edges.length;
    $('playback-mode').querySelector('[value="calls"]').disabled = !hasCalls;
    $('playback-mode').querySelector('[value="flow"]').disabled = !hasEdges;
    if ($('playback-mode').value === 'calls' && !hasCalls) $('playback-mode').value = 'flow';
    if ($('playback-mode').value === 'flow' && !hasEdges && hasCalls) $('playback-mode').value = 'calls';
    $('warnings').replaceChildren(element('li', 'Hierarchy shows module ownership. Observed call order does not establish tensor dependencies.'));
    for (const warning of data.warnings || []) $('warnings').append(element('li', warning));
    updatePlaybackControls(); rebuild(true); select(S.model.roots[0], false);
  }
  async function fetchCapture(id) {
    if (S.graphs.has(id)) return S.graphs.get(id);
    const response = await fetch('/api/architecture?id=' + encodeURIComponent(id)), data = await response.json();
    if (!response.ok) throw Error(data.error || 'Unable to load saved architecture.');
    prepareGraph(data); S.graphs.set(id, data); return data;
  }
  function syncComparisonToolbar() {
    const compare = S.mode === 'compare';
    $('capture').hidden = compare; $('compare-choices').hidden = !compare; $('compare-layout').hidden = !compare;
    $('playback-capture').hidden = !compare;
    $('comparison-legend').hidden = !compare;
    for (const button of $('view-mode').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.mode === S.mode));
    for (const button of $('compare-layout').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.layout === S.comparisonLayout));
    svg.toggleAttribute('hidden', sideBySide()); $('comparison-panels').hidden = !sideBySide();
  }
  function syncPanel(frame) {
    for (const [action, value] of [['level', S.granularity], ['theme', $('lens').dataset.theme], ['speed', Number($('speed').value)],
      ['labels', $('edge-labels').value], ['playback-mode', $('playback-mode').value]])
      frame.contentWindow.postMessage({ type: 'naia-lens-control', action, value }, location.origin);
  }
  async function updateComparison() {
    const version = ++S.loadVersion; pause();
    const ids = S.mode === 'compare' ? S.compareIds : [S.currentId];
    try {
      const loaded = await Promise.all(ids.map(async id => ({ id, title: S.library.find(item => item.id === id)?.title || id, data: await fetchCapture(id) })));
      if (version !== S.loadVersion) return;
      $('mode').classList.remove('error');
      S.compareCaptures = loaded; S.panels.clear(); $('comparison-panels').replaceChildren();
      $('comparison-legend').replaceChildren();
      syncComparisonToolbar();
      if (S.mode === 'single') {
        S.compareMaps.clear(); S.playbackId = null; setModel(loaded[0].data, S.currentId);
        $('mode').textContent = text(loaded[0].data.capture_mode || 'saved architecture') + ' · ' + S.model.nodes.size + ' components · ' + S.model.edges.length + ' saved dependencies';
        return;
      }
      if (!ids.includes(S.playbackId)) S.playbackId = ids[0];
      $('playback-capture').replaceChildren();
      loaded.forEach(capture => { const option = element('option', capture.title); option.value = capture.id; $('playback-capture').append(option); });
      $('playback-capture').value = S.playbackId;
      const comparison = comparisonGraph(loaded, S.playbackId); S.compareMaps = comparison.maps;
      setModel(comparison.data, 'compare:' + JSON.stringify(ids));
      $('mode').textContent = loaded.length + ' saved captures · ' + (sideBySide() ? 'independent hierarchies and call sequences' : 'overlay aligns module paths, then component IDs');
      $('warnings').append(element('li', 'Comparison highlights recorded metadata differences. Overlay playback uses the selected capture.'));
      loaded.forEach((capture, index) => {
        const legend = element('span'); legend.append(element('i', undefined, 'av-comparison-dot tone-' + [4, 5, 2][index % 3]), element('span', capture.title));
        $('comparison-legend').append(legend);
        for (const warning of capture.data.warnings || []) $('warnings').append(element('li', capture.title + ': ' + warning));
        if (!sideBySide()) return;
        const card = element('section', undefined, 'av-comparison-card'), title = element('div', undefined, 'av-comparison-title');
        title.append(element('i', undefined, 'av-comparison-dot tone-' + [4, 5, 2][index % 3]), element('span', capture.title));
        const frame = element('iframe'); frame.title = capture.title + ' architecture';
        frame.src = '/architecture?id=' + encodeURIComponent(capture.id) + '&panel=1';
        frame.addEventListener('load', () => syncPanel(frame));
        card.append(title, frame); $('comparison-panels').append(card); S.panels.set(capture.id, frame);
      });
      syncComparisonToolbar(); updatePlaybackControls();
    } catch (error) { $('mode').textContent = error.message; $('mode').classList.add('error'); }
  }
  async function loadLibrary() {
    if (!integrated || panelMode) {
      $('view-mode').querySelector('[data-mode="compare"]').disabled = true;
      $('view-mode').querySelector('[data-mode="compare"]').title = 'Compare registered captures in the project dashboard';
      $('capture').disabled = true; return;
    }
    try {
      const response = await fetch('/api/state'), state = await response.json();
      if (!response.ok) return;
      S.library = (state.architectures || []).filter(item => item.available !== false);
      if (!S.library.some(item => item.id === S.currentId)) S.library.unshift({ id: S.currentId, title: S.currentId });
      $('capture').replaceChildren(); $('compare-choices').replaceChildren();
      S.compareIds = [S.currentId, ...S.library.map(item => item.id).filter(id => id !== S.currentId)].slice(0, 3);
      for (const item of S.library) {
        const option = element('option', item.title || item.id); option.value = item.id; $('capture').append(option);
        const label = element('label'), checkbox = element('input'); checkbox.type = 'checkbox'; checkbox.value = item.id;
        checkbox.checked = S.compareIds.includes(item.id);
        checkbox.addEventListener('change', () => {
          const selected = [...$('compare-choices').querySelectorAll('input:checked')].map(input => input.value);
          if (selected.length < 2 || selected.length > 3) { checkbox.checked = !checkbox.checked; return; }
          S.compareIds = selected; updateComparison();
        });
        label.append(checkbox, element('span', item.title || item.id)); $('compare-choices').append(label);
      }
      $('capture').value = S.currentId; $('capture').disabled = false;
      $('view-mode').querySelector('[data-mode="compare"]').disabled = S.library.length < 2;
    } catch (_error) { $('view-mode').querySelector('[data-mode="compare"]').disabled = true; }
  }

  window.addEventListener('message', event => {
    if (event.origin !== location.origin || !event.data || typeof event.data !== 'object') return;
    if (panelMode && event.source === parent && event.data.type === 'naia-lens-control' && S.model) {
      const { action, value } = event.data;
      if (action === 'level' && Number.isInteger(value)) setLevel(value);
      else if (action === 'theme' && ['dark', 'light'].includes(value)) { setTheme(value); saveView(); }
      else if (action === 'zoom' && Number.isFinite(value) && value > 0) zoomBy(Math.max(.5, Math.min(2, value)));
      else if (action === 'fit') fit();
      else if (action === 'play' && !S.anim.playing) play();
      else if (action === 'pause') pause();
      else if (action === 'step') { pause(); stepAnimation(); }
      else if (action === 'reset-anim') resetAnimation();
      else if (action === 'reset-layout') { S.offsets.clear(); S.bends.clear(); rebuild(true); saveView(); }
      else if (action === 'export') exportSvg();
      else if (action === 'search' && typeof value === 'string') { $('search').value = value; search(); }
      else if (action === 'search-next') nextMatch();
      else if (action === 'speed' && Number.isFinite(value)) $('speed').value = String(Math.max(.25, Math.min(3, value)));
      else if (action === 'labels' && ['changes', 'all', 'off'].includes(value)) { $('edge-labels').value = value; drawEdges(); saveView(); }
      else if (action === 'playback-mode' && ['calls', 'flow'].includes(value) && !$('playback-mode').querySelector('[value="' + value + '"]').disabled) {
        $('playback-mode').value = value; resetAnimation(); updatePlaybackControls();
      }
      return;
    }
    const captureId = [...S.panels].find(([_id, frame]) => frame.contentWindow === event.source)?.[0];
    if (!captureId) return;
    if (event.data.type === 'naia-lens-ready') syncPanel(S.panels.get(captureId));
    else if (event.data.type === 'naia-lens-selection') {
      const id = S.compareMaps.get(captureId)?.get(event.data.node); if (id && S.model.nodes.has(id)) select(id, false);
    } else if (event.data.type === 'naia-lens-edge-selection') {
      const source = S.compareMaps.get(captureId)?.get(event.data.source), target = S.compareMaps.get(captureId)?.get(event.data.target);
      const edge = liftEdges(S.model, S).find(item => item.members.some(member => member.comparison_id === captureId
        && member.source === source && member.target === target && member.evidence === event.data.evidence));
      if (edge) selectEdge(edge);
    }
  });

  svg.addEventListener('wheel', event => {
    event.preventDefault(); if (!S.model) return;
    let delta = event.deltaY; if (event.deltaMode === 1) delta *= 16; else if (event.deltaMode === 2) delta *= 400;
    zoomBy(Math.exp(-Math.max(-150, Math.min(150, delta)) * .0015), world(event));
  }, { passive: false });
  svg.addEventListener('pointerdown', event => {
    if (!S.model || event.button !== 0 || event.target.closest('.av-node,.av-edge-hit')) return;
    event.preventDefault(); S.drag = { kind: 'pan', x: event.clientX, y: event.clientY, ...S.camera };
    svg.classList.add('panning'); svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove', event => {
    const d = S.drag; if (!d) return;
    const dx = (event.clientX - d.x) / S.camera.scale, dy = (event.clientY - d.y) / S.camera.scale;
    if (d.kind === 'pan') { S.camera.cx = d.cx - dx; S.camera.cy = d.cy - dy; applyCamera(); }
    else if (d.kind === 'node') { S.offsets.set(d.id, [d.start[0] + dx, d.start[1] + dy]); rebuild(); }
    else { S.bends.set(d.id, [d.start[0] + dx, d.start[1] + dy]); drawEdges(); renderSelection(); }
  });
  function endDrag() { S.drag = null; svg.classList.remove('panning'); for (const el of S.nodeEls.values()) el.classList.remove('dragging'); saveView(); }
  svg.addEventListener('pointerup', endDrag); svg.addEventListener('pointercancel', endDrag);
  $('levels').addEventListener('click', event => { const button = event.target.closest('[data-level]'); if (button && S.model) setLevel(Number(button.dataset.level)); });
  $('expand').addEventListener('click', () => setLevel(3));
  $('collapse').addEventListener('click', () => setLevel(0));
  $('fit').addEventListener('click', fit);
  $('zoom-in').addEventListener('click', () => zoomBy(1.25));
  $('zoom-out').addEventListener('click', () => zoomBy(.8));
  $('reset-layout').addEventListener('click', () => { panelControl('reset-layout'); S.offsets.clear(); S.bends.clear(); rebuild(true); saveView(); });
  $('export-svg').addEventListener('click', exportSvg);
  $('edge-labels').addEventListener('change', () => { panelControl('labels', $('edge-labels').value); drawEdges(); saveView(); });
  $('search').addEventListener('input', search);
  $('search').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); nextMatch(); } });
  $('search-next').addEventListener('click', nextMatch);
  $('play').addEventListener('click', play);
  $('step').addEventListener('click', () => { pause(); stepAnimation(); });
  $('reset-anim').addEventListener('click', resetAnimation);
  $('playback-mode').addEventListener('change', () => { panelControl('playback-mode', $('playback-mode').value); resetAnimation(); updatePlaybackControls(); });
  $('speed').addEventListener('input', () => panelControl('speed', Number($('speed').value)));
  $('theme').addEventListener('click', () => {
    setTheme($('lens').dataset.theme === 'light' ? 'dark' : 'light'); saveView();
  });
  $('capture').addEventListener('change', () => { S.currentId = $('capture').value; updateComparison(); });
  $('view-mode').addEventListener('click', event => {
    const button = event.target.closest('[data-mode]');
    if (!button || button.disabled || button.dataset.mode === S.mode) return;
    pause(); S.mode = button.dataset.mode; updateComparison();
  });
  $('compare-layout').addEventListener('click', event => {
    const button = event.target.closest('[data-layout]');
    if (!button || button.dataset.layout === S.comparisonLayout) return;
    pause(); S.comparisonLayout = button.dataset.layout; updateComparison();
  });
  $('playback-capture').addEventListener('change', () => {
    pause(); S.playbackId = $('playback-capture').value;
    const comparison = comparisonGraph(S.compareCaptures, S.playbackId); S.compareMaps = comparison.maps;
    setModel(comparison.data, 'compare:' + JSON.stringify(S.compareIds));
  });
  document.addEventListener('keydown', event => {
    if (!S.model || event.target.closest('input,select,textarea,button,a,summary')) return;
    const key = event.key.toLowerCase();
    if (key === 'f' || key === '0') fit();
    else if (key === '+' || key === '=') zoomBy(1.2);
    else if (key === '-') zoomBy(.83);
    else if (key === 'p' || key === 'k') play();
    else if (key === '.') { pause(); stepAnimation(); }
    else if (key === 'r') resetAnimation();
    else if (key === '[' || key === ']') setLevel(S.granularity + (key === ']' ? 1 : -1));
    else if (key === '/') $('search').focus();
    else if (key === 'escape' && S.selected) { const p = S.model.nodes.get(S.selected).parent; if (p) select(p); }
    else return;
    event.preventDefault();
  });
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => { if (S.model) applyCamera(); }).observe(svg);
  else window.addEventListener('resize', () => { if (S.model) applyCamera(); });
  window.addEventListener('pagehide', pause);

  async function loadGraph() {
    const id = new URLSearchParams(location.search).get('id');
    if (integrated) document.documentElement.classList.add('embedded');
    if (panelMode) document.documentElement.classList.add('panel');
    if (integrated && !id) throw Error('Choose a saved architecture from the NAIA dashboard.');
    const response = await fetch(integrated ? '/api/architecture?id=' + encodeURIComponent(id) : '/graph.json');
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Unable to load the saved architecture.');
    S.currentId = id || 'standalone'; S.graphs.set(S.currentId, data);
    for (const evidence of ['traced', 'declared', 'compare-4', 'compare-5', 'compare-2']) {
      const marker = svgEl('marker', { id: 'arrow-' + evidence, markerWidth: 9, markerHeight: 7, refX: 8, refY: 3.5, orient: 'auto' });
      marker.append(svgEl('path', { d: 'M0,0 L9,3.5 L0,7 Z', class: evidence.startsWith('compare-')
        ? 'av-arrow-compare tone-' + evidence.slice(-1) : 'av-arrow-' + evidence })); $('graph-defs').append(marker);
    }
    for (const control of $('lens').querySelectorAll('button,input,select')) control.disabled = false;
    $('view-mode').querySelector('[data-mode="compare"]').disabled = true;
    $('search-next').disabled = true;
    setModel(data, S.currentId);
    $('mode').textContent = text(data.capture_mode || 'saved architecture') + ' · ' + S.model.nodes.size + ' components · ' +
      S.model.edges.length + ' saved dependencies · ' + S.model.events.length + ' observed calls';
    const option = element('option', S.currentId); option.value = S.currentId; $('capture').append(option);
    await loadLibrary();
    if (panelMode) parent.postMessage({ type: 'naia-lens-ready' }, location.origin);
  }
  loadGraph().catch(error => {
    $('mode').textContent = error.message; $('mode').classList.add('error');
  });
})();
