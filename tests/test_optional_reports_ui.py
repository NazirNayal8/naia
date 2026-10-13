"""Execute the Reports library against optional/unavailable-folder responses."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


FIXTURE = r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attrs = {};
    this.listeners = {}; this.hidden = false; this.disabled = false; this._text = '';
    const classes = new Set();
    this.classList = {add: name => classes.add(name), contains: name => classes.has(name),
      toggle(name, enabled) {if(enabled)classes.add(name); else classes.delete(name);}};
  }
  set textContent(value) {this._text = String(value); this.children = [];}
  get textContent() {return this._text + this.children.map(child => child.textContent).join('');}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this._text = ''; this.children = [...children];}
  setAttribute(key, value) {this.attrs[key] = value;}
  addEventListener(event, callback) {(this.listeners[event] ||= []).push(callback);}
  fire(event) {for(const callback of this.listeners[event] || [])callback({preventDefault(){}});}
  focus() {this.focused = true;}
}
function descendants(element) {return [element, ...element.children.flatMap(descendants)];}
function find(host, predicate) {return descendants(host).find(predicate);}
const responses = [], requests = [], stored = JSON.stringify({query:'pusher',tags:['cube']});
const storage = new Map([['naia.reports.filters', stored]]);
const context = {document:{createElement:tag => new Element(tag)},
  localStorage:{getItem:key => storage.get(key),setItem:(key,value) => storage.set(key,value)},
  URLSearchParams, AbortController, clearTimeout, setTimeout, console,
  fetch:async(url,options) => {
    requests.push({url,options});
    const result = responses.shift();
    assert.ok(result, 'Unexpected fetch');
    if(result.throw)throw Error(result.throw);
    return {ok:result.ok !== false,json:async() => result.payload};
  }};
context.window = context;
vm.createContext(context); vm.runInContext(input.source, context);
const host = new Element('main'), ui = context.NAIAReports;
const unavailable = {reports:[],tags:[],warnings:['Report path is excluded from project access'],
  available:false,message:'Reports are unavailable: Report path is excluded from project access'};
const available = {reports:[{id:'CUBE',title:'Cube report',tags:['cube']}],tags:['cube'],
  warnings:[],available:true};
const tick = () => new Promise(resolve => setImmediate(resolve));
const search = () => find(host, item => 'reportSearch' in item.dataset);
const clear = () => find(host, item => 'reportClear' in item.dataset);
const status = () => find(host, item => 'reportStatus' in item.dataset);
const warnings = () => find(host, item => 'reportWarnings' in item.dataset);
(async() => {
  if(input.case === 'unavailable') {
    responses.push({payload:unavailable}); await ui.show(host);
    assert.equal(status().textContent, 'Reports unavailable');
    assert.equal(status().classList.contains('nr-error'), false);
    assert.equal(warnings().hidden, true);
    assert.equal(warnings().textContent, '');
    assert.equal(host.textContent.split(unavailable.warnings[0]).length - 1, 1);
    assert.ok(host.textContent.includes('Other tabs are still available'));
    assert.ok(host.textContent.includes('restart the interface'));
    assert.equal(host.textContent.includes('0 reports'), false);
    assert.equal(host.textContent.includes('No reports match'), false);
    assert.equal(host.textContent.includes('Reports could not be loaded'), false);
    assert.equal(search().disabled, true); assert.equal(clear().disabled, true);
    assert.equal(storage.get('naia.reports.filters'), stored);
    assert.equal(host.attrs['aria-busy'], 'false');
  } else if(input.case === 'missing') {
    storage.clear(); responses.push({payload:{reports:[],tags:[],warnings:[],available:true}});
    await ui.show(host);
    assert.ok(host.textContent.includes('No project reports are available yet.'));
    assert.equal(status().textContent, '0 reports');
    assert.equal(search().disabled, false); assert.equal(clear().disabled, false);
    assert.equal(find(host, item => item.textContent === 'Check again'), undefined);
  } else if(input.case === 'recovery') {
    responses.push({payload:unavailable}); await ui.show(host);
    responses.push({payload:available});
    find(host, item => item.tagName === 'button' && item.textContent === 'Check again').fire('click');
    await tick(); await tick();
    assert.equal(requests.length, 2);
    assert.deepEqual(requests.map(request => request.url), ['/api/reports?q=pusher&tag=cube','/api/reports?q=pusher&tag=cube']);
    assert.equal(search().value, 'pusher');
    assert.equal(search().disabled, false); assert.equal(clear().disabled, false);
    assert.equal(clear().hidden, false);
    assert.equal(storage.get('naia.reports.filters'), stored);
    assert.equal(status().textContent, '1 report');
    assert.ok(host.textContent.includes('Cube report'));
    assert.equal(host.textContent.includes('Reports unavailable'), false);
    assert.equal(host.textContent.includes('Other tabs are still available'), false);
    const tag = find(host, item => item.dataset.tag === 'cube');
    assert.equal(tag.attrs['aria-pressed'], 'true');
    assert.equal(host.attrs['aria-busy'], 'false');
  } else if(input.case === 'fallback') {
    responses.push({payload:{...unavailable,message:''}}); await ui.show(host);
    assert.equal(host.textContent.split(unavailable.warnings[0]).length - 1, 1);
    responses.push({payload:{...unavailable,message:'',warnings:[]}}); await ui.refresh(host);
    assert.ok(host.textContent.includes('The configured report folder cannot be accessed.'));
  } else if(input.case === 'text_only') {
    const marker = '<img src=x onerror=alert(1)>';
    responses.push({payload:{...unavailable,message:marker}}); await ui.show(host);
    assert.ok(host.textContent.includes(marker));
    assert.equal(find(host, item => item.tagName === 'img'), undefined);
    assert.equal(descendants(host).some(item => 'innerHTML' in item), false);
  } else if(input.case === 'network_error') {
    responses.push({ok:false,payload:{error:'Unexpected service failure'}}); await ui.show(host);
    assert.equal(status().textContent, 'Unexpected service failure');
    assert.equal(status().classList.contains('nr-error'), true);
    assert.ok(find(host, item => item.tagName === 'button' && item.textContent === 'Try again'));
    assert.equal(host.textContent.includes('Reports unavailable'), false);
  } else throw Error('Unknown case: ' + input.case);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


@unittest.skipUnless(NODE, "Node is needed for Reports UI contracts")
class OptionalReportsUITest(unittest.TestCase):
    def case(self, name):
        result = subprocess.run(
            [NODE, "-e", FIXTURE],
            input=json.dumps({"source": (ROOT / "src/naia/assets/reports.js").read_text(),
                              "case": name}),
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unavailable_is_a_non_error_state_and_does_not_duplicate_reason(self):
        self.case("unavailable")

    def test_missing_folder_is_an_available_empty_library(self):
        self.case("missing")

    def test_check_again_recovers_controls_and_preserves_filters(self):
        self.case("recovery")

    def test_missing_message_uses_warning_or_fallback_once(self):
        self.case("fallback")

    def test_reason_is_only_rendered_as_text(self):
        self.case("text_only")

    def test_network_failures_keep_existing_error_and_retry_behavior(self):
        self.case("network_error")


if __name__ == "__main__":
    unittest.main()
