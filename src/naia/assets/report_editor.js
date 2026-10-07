'use strict';

(() => {
  const hiddenStyle = document.createElement('style');
  hiddenStyle.textContent = '[data-naia-section][hidden]{display:none!important}';
  document.head.append(hiddenStyle);
  // Only a served report inside the trusted wrapper can edit. The same bridge
  // may be included in standalone exports, where it is deliberately inert.
  const script = document.currentScript;
  let trustedOrigin;
  try {
    const source = new URL(script?.src || '', document.baseURI);
    if (!script?.src || !['http:', 'https:'].includes(source.protocol) || window.parent === window) return;
    trustedOrigin = source.origin;
  } catch (_) { return; }

  const MAX_BLOCKS = 128, MAX_TEXT = 8192, MAX_TOTAL = 32768;
  const textEncoder = new TextEncoder();
  const tags = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'DT', 'DD',
    'BLOCKQUOTE', 'FIGCAPTION', 'SPAN', 'STRONG', 'EM', 'B', 'I', 'SMALL', 'CITE', 'Q']);
  const attributes = ['contenteditable', 'tabindex', 'role', 'aria-multiline', 'aria-label', 'aria-disabled', 'spellcheck'];
  let session = null, busy = false, blocks = new Map(), active = null, structure = null, dragging = null;

  function plainObject(value) { return value && typeof value === 'object' && !Array.isArray(value); }
  function validID(id) {
    return typeof id === 'string' && /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(id)
      && !['id', 'view', 'constructor', 'prototype', '__proto__'].includes(id.toLowerCase());
  }
  function validText(value) {
    if (typeof value !== 'string' || value.length > MAX_TEXT * 2 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) return false;
    let length = 0;
    for (const character of value) {
      if (++length > MAX_TEXT || character.length === 1 && character.charCodeAt(0) >= 0xd800 && character.charCodeAt(0) <= 0xdfff) return false;
    }
    return true;
  }
  function tell(type, values = {}) {
    window.parent.postMessage({type, ...values}, trustedOrigin);
  }
  function error(message, editSession = session, recoverable = false) {
    tell('naia-report-editor-error', {session: editSession, message, recoverable});
  }
  function installStyle() {
    if (document.querySelector('style[data-naia-report-editor]')) return;
    const style = document.createElement('style');
    style.dataset.naiaReportEditor = '';
    style.textContent = `.naia-report-editable{cursor:text;overflow-wrap:anywhere;min-height:1em}.naia-report-editable[aria-disabled="true"]{cursor:default;opacity:.85}.naia-report-edit-input{appearance:none;display:block;box-sizing:border-box;width:100%;max-width:100%;min-width:1em;min-height:1em;padding:0;margin:0;border:0;border-radius:0;background:transparent;color:inherit;font:inherit;letter-spacing:inherit;text-align:inherit;white-space:pre-wrap;resize:none;overflow:hidden;outline:0!important;box-shadow:none!important}.naia-report-edit-input[readonly]{cursor:text}.naia-report-layout-panel,.naia-report-layout-tools{color:var(--ink,var(--nrk-text,#d4d4d4));background:var(--surface,var(--nrk-surface,#252526));border:1px solid var(--rule,var(--nrk-line,#555));border-radius:5px;font:12px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}.naia-report-layout-panel{position:fixed;right:14px;bottom:14px;z-index:30;max-width:min(360px,calc(100vw - 28px));max-height:60vh;overflow:auto;padding:8px;box-shadow:0 3px 14px #0002}.naia-report-layout-tools{position:absolute;right:4px;top:2px;z-index:5;display:flex;align-items:center;gap:3px;padding:3px;max-width:100%;opacity:0;pointer-events:none}.naia-report-layout-section:hover>.naia-report-layout-tools,.naia-report-layout-section:focus-within>.naia-report-layout-tools,.naia-report-layout-visual:hover>.naia-report-layout-tools,.naia-report-layout-visual:focus-within>.naia-report-layout-tools{opacity:1;pointer-events:auto}.naia-report-layout-visual>.naia-report-layout-tools{top:0;transform:translateY(-100%)}.naia-report-layout-panel button,.naia-report-layout-tools button,.naia-report-layout-tools select{appearance:auto;background:transparent;color:inherit;border:1px solid var(--rule,var(--nrk-line,#555));border-radius:3px;padding:4px 6px;margin:0;font:inherit;cursor:pointer}.naia-report-layout-tools select{max-width:130px}.naia-report-layout-tools button:focus-visible,.naia-report-layout-tools select:focus-visible,.naia-report-layout-panel button:focus-visible,.naia-report-layout-panel input:focus-visible,.naia-report-layout-panel textarea:focus-visible{outline:2px solid var(--accent,#4daafc);outline-offset:2px}.naia-report-layout-panel button:disabled,.naia-report-layout-tools button:disabled,.naia-report-layout-tools select:disabled{opacity:.5;cursor:default}.naia-report-layout-drag{cursor:grab!important}.naia-report-layout-panel form{display:grid;gap:8px;margin-top:8px}.naia-report-layout-panel [hidden]{display:none!important}.naia-report-layout-panel label{display:grid;gap:4px}.naia-report-layout-panel input,.naia-report-layout-panel textarea{box-sizing:border-box;width:100%;min-width:0;padding:6px;background:var(--bg,#181818);color:inherit;border:1px solid var(--rule,#555);border-radius:3px;font:inherit}.naia-report-layout-panel textarea{resize:vertical}.naia-report-layout-restore{display:grid;gap:4px;margin-top:6px}.naia-report-layout-restore:empty{display:none}.naia-report-layout-restore button{text-align:left;overflow-wrap:anywhere}.naia-report-layout-drop{box-shadow:inset 0 3px var(--accent,#4daafc)}@media(hover:none){.naia-report-layout-tools{opacity:1;pointer-events:auto}}@media(max-width:900px){.naia-report-layout-tools{position:static;opacity:1;pointer-events:auto;flex-wrap:wrap;grid-column:1/-1;align-self:start;width:fit-content;box-sizing:border-box;margin:0 0 8px}.naia-report-layout-visual>.naia-report-layout-tools{top:auto;transform:none}}`;
    document.head.append(style);
  }
  function restoreAttribute(node, name, value) {
    if (value === null) node.removeAttribute(name);
    else node.setAttribute(name, value);
  }
  function stop(restore) {
    const anchor = captureAnchor(restore);
    if (active) deactivate(active);
    for (const block of blocks.values()) {
      const node = block.node;
      node.textContent = restore ? block.original : block.text;
      if (!block.highlighted) node.classList.remove('naia-report-editable');
      for (const [name, value] of block.attributes) restoreAttribute(node, name, value);
      node.removeEventListener('focus', focus);
      node.removeEventListener('click', click);
      node.removeEventListener('keydown', keydown);
    }
    finishStructure(restore);
    restoreAnchor(anchor);
    blocks = new Map();
    session = null;
    busy = false;
    active = null;
  }
  function edits() {
    const changes = Object.create(null);
    let total = 0;
    for (const [id, block] of blocks) {
      const text = block.text;
      if (!validText(text)) return null;
      total += textEncoder.encode(text).length;
      if (total > MAX_TOTAL) return null;
      if (!block.addition && text !== block.original) {
        changes[id] = text;
      }
    }
    return changes;
  }
  function resizeField(field) {
    field.style.height = 'auto';
    field.style.height = field.scrollHeight + 'px';
  }
  function input(event) {
    if (!session) return;
    const field = event.currentTarget;
    const block = blocks.get(field.dataset.naiaEditInput);
    if (!block || field !== block.field) return;
    if (busy) { field.value = block.text; return; }
    const previous = block.text;
    block.text = field.value;
    const changes = edits();
    if (changes === null) {
      const caret = field.selectionStart;
      block.text = previous;
      field.value = previous;
      field.setSelectionRange(Math.min(caret, previous.length), Math.min(caret, previous.length));
      error('Text is too long or contains unsupported characters. Each block supports 8,192 characters and report text supports 32 KiB.', session, true);
    } else {
      if (block.addition) block.addition[block.part] = block.text;
      publish(changes);
    }
    resizeField(field);
  }
  function deactivate(block) {
    if (!block.field) return;
    if (block.field.value !== block.text) input({currentTarget: block.field});
    block.field = null;
    block.node.textContent = block.text;
    block.node.setAttribute('tabindex', '0');
    block.node.setAttribute('role', 'button');
    if (active === block) active = null;
  }
  function activate(block) {
    if (!session || busy || block.field) return;
    if (active) deactivate(active);
    const node = block.node;
    const width = node.getBoundingClientRect().width;
    const inline = getComputedStyle(node).display.startsWith('inline');
    let field = block.editor;
    if (!field) {
      field = document.createElement('textarea');
      field.className = 'naia-report-edit-input';
      field.dataset.naiaEditInput = node.getAttribute('data-naia-edit');
      field.rows = 1;
      field.spellcheck = true;
      field.value = block.text;
      field.setAttribute('aria-label', node.getAttribute('aria-label') || 'Editable report text');
      field.addEventListener('input', input);
      field.addEventListener('blur', () => { if (block.field === field) deactivate(block); });
      block.editor = field;
    }
    if (field.value !== block.text) field.value = block.text;
    field.readOnly = false;
    field.style.width = inline ? Math.max(36, Math.ceil(width)) + 'px' : '100%';
    field.style.display = inline ? 'inline-block' : 'block';
    field.style.verticalAlign = inline ? 'bottom' : '';
    block.field = field;
    active = block;
    node.setAttribute('tabindex', '-1');
    node.setAttribute('role', 'group');
    node.replaceChildren(field);
    resizeField(field);
    field.focus({preventScroll: true});
  }
  function focus(event) {
    const block = blocks.get(event.currentTarget.getAttribute('data-naia-edit'));
    if (block) activate(block);
  }
  function click(event) {
    if (event.target === event.currentTarget || !event.currentTarget.contains(document.activeElement)) focus(event);
  }
  function keydown(event) {
    if (event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) {
      event.preventDefault();
      focus(event);
    }
  }
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function captureAnchor(existingOnly = false) {
    const candidates = [...blocks.values()].filter(block => !existingOnly || !block.addition).map(block => block.node);
    if (structure) for (const item of structure.items.values()) {
      if (existingOnly && structure.additions.has(item.container)) continue;
      candidates.push(item.kind === 'visual' ? item.node.querySelector('svg,canvas,img') || item.node : item.node);
    }
    const visible = candidates.map(node => ({node, top: node.getBoundingClientRect().top, bottom: node.getBoundingClientRect().bottom}))
      .filter(candidate => candidate.bottom > 0 && candidate.top < window.innerHeight && candidate.node.getBoundingClientRect().height > 0)
      .sort((a, b) => Math.abs(a.top) - Math.abs(b.top));
    return visible[0] || null;
  }
  function restoreAnchor(anchor) {
    if (anchor?.node.isConnected) window.scrollBy(0, anchor.node.getBoundingClientRect().top - anchor.top);
  }
  function button(text, attribute, id, action, label = text) {
    const node = element('button', text);
    node.type = 'button';
    node.setAttribute(attribute, id);
    node.setAttribute('aria-label', label);
    node.title = label;
    node.addEventListener('click', event => { event.stopPropagation(); if (!busy) action(); });
    return node;
  }
  function managed(container) {
    const attribute = container.kind === 'sections' ? 'data-naia-section' : 'data-naia-item';
    return [...container.node.children].filter(node => node.hasAttribute(attribute));
  }
  function layoutProposal() {
    if (!structure) return null;
    const orders = Object.create(null);
    for (const container of structure.containers.values()) {
      const attribute = container.kind === 'sections' ? 'data-naia-section' : 'data-naia-item';
      orders[container.id] = managed(container).map(node => node.getAttribute(attribute));
    }
    return {orders, hidden: [...structure.sections.values()].filter(section => section.node.hidden).map(section => section.id).sort(),
      add: [...structure.additions.values()].map(({id, container, title, text}) => ({id, container, title, text}))};
  }
  function publish(changes = edits()) {
    if (!session || busy || changes === null) return;
    const layout = layoutProposal();
    tell('naia-report-edits', {session, changes, ...(layout ? {layout} : {})});
  }
  function prepareStructure(value) {
    if (value === null || value === undefined) return null;
    if (!plainObject(value) || !Array.isArray(value.containers) || !Array.isArray(value.sections)
      || !Array.isArray(value.items) || value.sections.length > 64 || value.items.length > 256 || value.containers.length > 65) throw Error('The approved report layout is invalid.');
    const result = {containers: new Map(), sections: new Map(), items: new Map(), additions: new Map(), tools: [], panel: null};
    function uniqueNode(attribute, id) {
      if (!validID(id)) throw Error('The approved report layout has an invalid ID.');
      const nodes = [...document.querySelectorAll('[' + attribute + ']')].filter(node => node.getAttribute(attribute) === id);
      if (nodes.length !== 1) throw Error('The displayed layout differs from the saved report. Reload before editing.');
      return nodes[0];
    }
    for (const container of value.containers) {
      if (!plainObject(container) || result.containers.has(container.id) || !['sections', 'items'].includes(container.kind)
        || !Array.isArray(container.order) || container.order.length > 256 || new Set(container.order).size !== container.order.length) throw Error('The approved report containers are invalid.');
      const node = uniqueNode('data-naia-layout', container.id);
      const entry = {...container, node, original: [...node.childNodes]};
      result.containers.set(container.id, entry);
      const ids = managed(entry).map(child => child.getAttribute(container.kind === 'sections' ? 'data-naia-section' : 'data-naia-item'));
      if (JSON.stringify(ids) !== JSON.stringify(container.order) || ids.length !== node.children.length) throw Error('The displayed layout differs from its approved source. Reload before editing.');
    }
    const roots = [...result.containers.values()].filter(container => container.kind === 'sections');
    if (roots.length !== 1) throw Error('The report needs one approved section container.');
    result.root = roots[0];
    for (const section of value.sections) {
      const node = uniqueNode('data-naia-section', section.id);
      if (result.sections.has(section.id) || section.container !== result.root.id || typeof section.label !== 'string'
        || typeof section.hidden !== 'boolean' || node.hidden !== section.hidden || node.parentElement !== result.root.node
        || result.containers.get(section.id)?.node !== node || result.containers.get(section.id)?.kind !== 'items') throw Error('The displayed sections differ from the saved report.');
      result.sections.set(section.id, {...section, node, originalHidden: section.hidden, style: node.getAttribute('style')});
    }
    for (const item of value.items) {
      const node = uniqueNode('data-naia-item', item.id);
      if (result.items.has(item.id) || !['visual', 'text'].includes(item.kind) || typeof item.label !== 'string'
        || node.parentElement !== result.sections.get(item.container)?.node || (node.getAttribute('data-naia-kind') || 'text') !== item.kind) throw Error('The displayed items differ from the saved report.');
      result.items.set(item.id, {...item, node, style: node.getAttribute('style')});
    }
    if (result.containers.size !== result.sections.size + 1 || result.root.order.length !== result.sections.size
      || [...result.containers.values()].filter(container => container.kind === 'items').reduce((n, container) => n + container.order.length, 0) !== result.items.size) throw Error('The approved layout is incomplete.');
    return result;
  }
  function finishStructure(restore) {
    if (!structure) return;
    for (const node of structure.tools) node.remove();
    structure.panel?.remove();
    if (restore) {
      for (const container of structure.containers.values()) {
        if (!structure.additions.has(container.id)) container.node.replaceChildren(...container.original);
      }
      for (const section of structure.sections.values()) {
        if (structure.additions.has(section.id)) section.node.remove();
        else section.node.hidden = section.originalHidden;
      }
    }
    for (const section of structure.sections.values()) {
      section.node.classList.remove('naia-report-layout-section');
      restoreAttribute(section.node, 'style', section.style);
    }
    for (const item of structure.items.values()) {
      item.node.classList.remove('naia-report-layout-visual', 'naia-report-layout-drop');
      restoreAttribute(item.node, 'style', item.style);
    }
    document.removeEventListener('dragover', dragover);
    document.removeEventListener('drop', drop);
    dragging = null;
    structure = null;
  }
  function preserveScroll(action) {
    const left = window.scrollX, top = window.scrollY;
    action();
    window.scrollTo(left, top);
  }
  function move(kind, id, containerID, beforeID = null) {
    if (!structure || busy) return;
    const entry = (kind === 'sections' ? structure.sections : structure.items).get(id);
    const container = structure.containers.get(containerID);
    const lookup = kind === 'sections' ? structure.sections : structure.items;
    const before = beforeID === null ? null : lookup.get(beforeID);
    if (!entry || !container || container.kind !== kind || before && before.node.parentElement !== container.node || before?.id === id) return;
    if (active) deactivate(active);
    preserveScroll(() => container.node.insertBefore(entry.node, before?.node || null));
    entry.container = containerID;
    refreshStructure();
    publish();
  }
  function step(kind, id, direction) {
    const lookup = kind === 'sections' ? structure.sections : structure.items;
    const entry = lookup.get(id), container = structure.containers.get(entry.container);
    const list = managed(container), index = list.indexOf(entry.node), target = index + direction;
    if (target < 0 || target >= list.length) return;
    const next = direction < 0 ? list[target] : list[target + 1] || null;
    move(kind, id, entry.container, next?.getAttribute(kind === 'sections' ? 'data-naia-section' : 'data-naia-item') || null);
  }
  function dragButton(kind, id) {
    const node = button(kind === 'sections' ? 'Move section' : 'Move visual', kind === 'sections' ? 'data-naia-section-drag' : 'data-naia-item-drag', id, () => {});
    node.className = 'naia-report-layout-drag';
    node.draggable = true;
    node.addEventListener('dragstart', event => {
      if (busy || !session) { event.preventDefault(); return; }
      if (active) deactivate(active);
      dragging = {kind, id};
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', id);
    });
    node.addEventListener('dragend', () => { dragging = null; clearDrop(); });
    return node;
  }
  function toolbar(node) {
    const tools = element('div', undefined, 'naia-report-layout-tools');
    tools.dataset.naiaEditorTools = '';
    node.prepend(tools);
    structure.tools.push(tools);
    if (getComputedStyle(node).position === 'static') node.style.position = 'relative';
    return tools;
  }
  function sectionTools(section) {
    section.node.classList.add('naia-report-layout-section');
    const tools = toolbar(section.node);
    tools.append(dragButton('sections', section.id),
      button('↑', 'data-naia-section-up', section.id, () => step('sections', section.id, -1), 'Move section earlier'),
      button('↓', 'data-naia-section-down', section.id, () => step('sections', section.id, 1), 'Move section later'),
      button('Remove', 'data-naia-remove-section', section.id, () => {
        if (active && section.node.contains(active.node)) deactivate(active);
        section.node.hidden = true; refreshStructure(); publish();
      }, 'Remove section (can be restored)'));
  }
  function visualTools(item) {
    item.node.classList.add('naia-report-layout-visual');
    const tools = toolbar(item.node);
    const destination = element('select');
    destination.dataset.naiaMoveItem = item.id;
    destination.setAttribute('aria-label', 'Move visual to section');
    destination.addEventListener('change', () => move('items', item.id, destination.value));
    tools.append(dragButton('items', item.id),
      button('↑', 'data-naia-item-up', item.id, () => step('items', item.id, -1), 'Move visual earlier'),
      button('↓', 'data-naia-item-down', item.id, () => step('items', item.id, 1), 'Move visual later'), destination);
  }
  function refreshStructure() {
    if (!structure) return;
    const restore = structure.panel.querySelector('.naia-report-layout-restore');
    restore.replaceChildren();
    for (const section of structure.sections.values()) {
      if (section.node.hidden) restore.append(button('Restore: ' + section.label, 'data-naia-restore-section', section.id, () => {
        section.node.hidden = false; refreshStructure(); publish();
      }));
      const list = managed(structure.containers.get(section.container)), index = list.indexOf(section.node);
      section.node.querySelector('[data-naia-section-up]').disabled = busy || index <= 0;
      section.node.querySelector('[data-naia-section-down]').disabled = busy || index === list.length - 1;
    }
    for (const item of structure.items.values()) {
      if (item.kind !== 'visual') continue;
      const destination = item.node.querySelector('[data-naia-move-item]');
      destination.replaceChildren();
      for (const section of structure.sections.values()) {
        if (!section.node.hidden || section.id === item.container) {
          const option = element('option', section.label); option.value = section.id; destination.append(option);
        }
      }
      destination.value = item.container;
      const list = managed(structure.containers.get(item.container)), index = list.indexOf(item.node);
      item.node.querySelector('[data-naia-item-up]').disabled = busy || index <= 0;
      item.node.querySelector('[data-naia-item-down]').disabled = busy || index === list.length - 1;
    }
    for (const control of [...structure.panel.querySelectorAll('button,input,textarea'), ...structure.tools.flatMap(node => [...node.querySelectorAll('button,select')])]) {
      if (control.matches('[data-naia-section-up],[data-naia-section-down],[data-naia-item-up],[data-naia-item-down]')) continue;
      control.disabled = busy;
    }
    structure.panel.querySelector('[data-naia-add-section]').disabled = busy || structure.additions.size >= 32
      || structure.sections.size >= 64 || structure.items.size + 2 > 256 || blocks.size + 2 > MAX_BLOCKS;
  }
  function clearDrop() {
    document.querySelectorAll('.naia-report-layout-drop').forEach(node => node.classList.remove('naia-report-layout-drop'));
  }
  function dropTarget(event) {
    if (!structure || !dragging || busy || !(event.target instanceof Element)) return null;
    if (dragging.kind === 'sections') {
      const node = event.target.closest('[data-naia-section]'), section = structure.sections.get(node?.dataset.naiaSection);
      if (!section || section.id === dragging.id) return null;
      const after = event.clientY > node.getBoundingClientRect().top + node.getBoundingClientRect().height / 2;
      const list = managed(structure.containers.get(section.container)), index = list.indexOf(node);
      return {node, container: section.container, before: after ? list[index + 1]?.dataset.naiaSection || null : section.id};
    }
    const itemNode = event.target.closest('[data-naia-item]'), item = structure.items.get(itemNode?.dataset.naiaItem);
    if (item) {
      if (item.id === dragging.id) return null;
      const after = event.clientY > itemNode.getBoundingClientRect().top + itemNode.getBoundingClientRect().height / 2;
      const list = managed(structure.containers.get(item.container)), index = list.indexOf(itemNode);
      return {node: itemNode, container: item.container, before: after ? list[index + 1]?.dataset.naiaItem || null : item.id};
    }
    const node = event.target.closest('[data-naia-section]'), section = structure.sections.get(node?.dataset.naiaSection);
    return section ? {node, container: section.id, before: null} : null;
  }
  function dragover(event) {
    const target = dropTarget(event);
    clearDrop();
    if (!target) return;
    event.preventDefault(); event.dataTransfer.dropEffect = 'move'; target.node.classList.add('naia-report-layout-drop');
  }
  function drop(event) {
    const target = dropTarget(event);
    if (!target) return;
    event.preventDefault();
    move(dragging.kind, dragging.id, target.container, target.before);
    dragging = null; clearDrop();
  }
  function addSection(title, text) {
    if (!structure || busy || !validText(title) || !validText(text) || !title.trim()
      || structure.additions.size >= 32 || structure.sections.size >= 64 || structure.items.size + 2 > 256 || blocks.size + 2 > MAX_BLOCKS) {
      error('Enter a section title and keep the section within the report limits.', session, true); return false;
    }
    const current = [...blocks.values()].reduce((total, block) => total + textEncoder.encode(block.text).length, 0);
    if (current + textEncoder.encode(title + text).length > MAX_TOTAL) { error('Report text supports at most 32 KiB.', session, true); return false; }
    const id = 'new-' + [...crypto.getRandomValues(new Uint8Array(8))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    const addition = {id, container: structure.root.id, title, text};
    const node = element('section'); node.dataset.naiaSection = id; node.dataset.naiaLayout = id;
    const section = {...addition, label: title.slice(0, 512), hidden: false, node, style: null};
    for (const [part, tag] of [['title', 'h2'], ['text', 'p']]) {
      const itemID = id + '-' + part, itemNode = element(tag, addition[part]);
      itemNode.dataset.naiaItem = itemID; itemNode.dataset.naiaEdit = itemID;
      if (part === 'text') itemNode.style.whiteSpace = 'pre-line';
      node.append(itemNode);
      structure.items.set(itemID, {id: itemID, container: id, label: addition[part].slice(0, 512), kind: 'text', node: itemNode, style: itemNode.getAttribute('style')});
      const block = {node: itemNode, original: addition[part], text: addition[part], field: null, editor: null, highlighted: false,
        attributes: attributes.map(name => [name, itemNode.getAttribute(name)]), addition, part};
      blocks.set(itemID, block); enableBlock(block);
    }
    structure.additions.set(id, addition); structure.sections.set(id, section);
    structure.containers.set(id, {id, kind: 'items', node, order: [id + '-title', id + '-text'], original: []});
    structure.root.node.append(node); sectionTools(section); refreshStructure(); publish();
    return true;
  }
  function setupStructure() {
    if (!structure) return;
    const panel = element('div', undefined, 'naia-report-layout-panel');
    panel.dataset.naiaEditorTools = ''; panel.setAttribute('role', 'group'); panel.setAttribute('aria-label', 'Report sections');
    structure.panel = panel;
    const form = element('form'); form.hidden = true;
    const titleLabel = element('label', 'Section title'), title = element('input'); title.dataset.naiaNewTitle = ''; title.value = 'New section'; titleLabel.append(title);
    const textLabel = element('label', 'Section text'), text = element('textarea'); text.dataset.naiaNewText = ''; text.rows = 3; textLabel.append(text);
    form.append(titleLabel, textLabel,
      button('Add section', 'data-naia-confirm-add', '', () => { if (addSection(title.value, text.value)) form.hidden = true; }),
      button('Cancel', 'data-naia-dismiss-add', '', () => { form.hidden = true; }));
    form.addEventListener('submit', event => { event.preventDefault(); if (addSection(title.value, text.value)) form.hidden = true; });
    panel.append(button('Add section', 'data-naia-add-section', '', () => { form.hidden = !form.hidden; if (!form.hidden) title.focus({preventScroll: true}); }),
      element('div', undefined, 'naia-report-layout-restore'), form);
    document.body.append(panel);
    for (const section of structure.sections.values()) sectionTools(section);
    for (const item of structure.items.values()) if (item.kind === 'visual') visualTools(item);
    document.addEventListener('dragover', dragover); document.addEventListener('drop', drop);
    refreshStructure();
  }
  function enableBlock(block) {
    const node = block.node;
    node.classList.add('naia-report-editable'); node.setAttribute('contenteditable', 'false'); node.setAttribute('tabindex', '0'); node.setAttribute('role', 'button'); node.setAttribute('aria-disabled', 'false');
    if (!node.hasAttribute('aria-label')) node.setAttribute('aria-label', 'Edit report text');
    node.addEventListener('focus', focus); node.addEventListener('click', click); node.addEventListener('keydown', keydown);
  }
  function start(message) {
    if (session) return;
    const nextSession = message.session;
    if (typeof nextSession !== 'string' || !/^[A-Za-z0-9-]{24,96}$/.test(nextSession)
      || !Array.isArray(message.blocks) || message.blocks.length > MAX_BLOCKS || !message.blocks.length && !message.layout) return;
    const marked = new Map();
    for (const node of document.querySelectorAll('[data-naia-edit]')) {
      const id = node.getAttribute('data-naia-edit');
      if (!validID(id) || marked.has(id)) { error('The report has invalid or duplicate text markers.', nextSession); return; }
      marked.set(id, node);
    }
    if (marked.size !== message.blocks.length) { error('The report text changed. Reload it before editing.', nextSession); return; }
    const approved = new Map();
    let total = 0;
    for (const item of message.blocks) {
      if (!plainObject(item) || !validID(item.id) || approved.has(item.id)
        || !validText(item.text)) {
        error('The approved text snapshot is invalid.', nextSession); return;
      }
      total += textEncoder.encode(item.text).length;
      const node = marked.get(item.id);
      if (total > MAX_TOTAL || !node || !tags.has(node.tagName) || node.namespaceURI !== 'http://www.w3.org/1999/xhtml'
        || [...node.childNodes].some(child => child.nodeType !== Node.TEXT_NODE)
        || node.closest('head,table,caption,thead,tbody,tfoot,tr,td,th,script,style,svg,math,form,button,select,option,optgroup,textarea,template,noscript,iframe,object,embed,canvas,pre,code,a,audio,video,datalist,output,[data-naia-readonly]')
        || node.textContent !== item.text) {
        error('The displayed text differs from the saved report or is not a plain text block. Reload it before editing.', nextSession); return;
      }
      approved.set(item.id, {node, original: item.text, text: item.text, field: null, editor: null,
        highlighted: node.classList.contains('naia-report-editable'),
        attributes: attributes.map(name => [name, node.getAttribute(name)])});
    }
    let approvedStructure;
    try { approvedStructure = prepareStructure(message.layout); }
    catch (problem) { error(problem.message, nextSession); return; }
    session = nextSession;
    blocks = approved;
    structure = approvedStructure;
    const anchor = captureAnchor();
    installStyle();
    for (const block of blocks.values()) enableBlock(block);
    setupStructure();
    restoreAnchor(anchor);
    tell('naia-report-edit-started', {session});
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== trustedOrigin || !plainObject(event.data)) return;
    const message = event.data;
    if (message.type === 'naia-report-editor-probe') tell('naia-report-editor-ready');
    else if (message.type === 'naia-report-edit-start') start(message);
    else if (session && message.session === session && message.type === 'naia-report-edit-stop' && typeof message.restore === 'boolean') stop(message.restore);
    else if (session && message.session === session && message.type === 'naia-report-edit-busy' && typeof message.busy === 'boolean') {
      busy = message.busy;
      for (const block of blocks.values()) {
        if (block.field) block.field.readOnly = busy;
        block.node.setAttribute('aria-disabled', String(busy));
      }
      refreshStructure();
    }
  });
  document.addEventListener('click', event => {
    if (!session || !event.target.closest?.('a[href]')) return;
    event.preventDefault();
    error('Save or cancel report changes before following report links.', session, true);
  }, true);
  window.addEventListener('resize', () => { if (active?.field) resizeField(active.field); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => tell('naia-report-editor-ready'), {once: true});
  else tell('naia-report-editor-ready');
})();
