"""Suite-card preflight keeps route errors out of the embedded viewer."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

FIXTURE = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Element {
  constructor(tag='div') {this.tagName=tag;this.hidden=false;this.attrs={};this.listeners={};this.children=[];
    this.style={setProperty(){}};this.classList={toggle(){}};this.open=false;this._text='';}
  set textContent(value) {this._text=String(value);this.children=[];}
  get textContent() {return this._text;}
  set src(value) {this.attrs.src=value;}
  get src() {return this.attrs.src;}
  setAttribute(key,value) {this.attrs[key]=value;}
  getAttribute(key) {return this.attrs[key]??null;}
  removeAttribute(key) {delete this.attrs[key];}
  replaceChildren(...children) {this.children=children;}
  append(...children) {this.children.push(...children);}
  addEventListener(event,callback) {(this.listeners[event] ||= []).push(callback);}
  showModal() {this.open=true;}
  close() {this.open=false;for(const callback of this.listeners.close || [])callback();}
}
const elements=new Map(),requests=[];
const context={URL,console,input,assert,requests,
  location:{href:'http://127.0.0.1:8767/?view=suites',origin:'http://127.0.0.1:8767'},
  $:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},
  element:(tag,text)=>{const result=new Element(tag);if(text!==undefined)result.textContent=text;return result;},
  suiteStatus:node=>node.status||'ready',suiteColor:()=> '#abc',architectureLinks(){},
  fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject})),
  tick:()=>new Promise(resolve=>setImmediate(resolve)),
  response:(ok=true,error=null,type='text/html')=>({ok,status:ok?200:400,
    headers:{get:()=>type},json:async()=>({error})})};
vm.createContext(context);
vm.runInContext("let selectedSuiteId=null,suiteCardRequest=0,suiteCardLoadingUrl=null;"+
  "let suiteById=new Map(),graphNodes=new Map();const state={};"+input.source+input.close,context);
vm.runInContext(String.raw`
const frame=$('suiteCardFrame'),notice=$('suiteNoCard'),dialog=$('suiteDialog'),link=$('suiteOpenTab');
const card=id=>({id,title:'Suite '+id,card:'.lab/suites/'+id+'/card.md',status:'ready'});
suiteById.set('A',card('A'));suiteById.set('B',card('B'));
const finish=async(index,result=response())=>{requests[index].resolve(result);await tick();};
(async()=>{
  if(input.case==='success') {
    selectSuite('A');assert.equal(dialog.open,true);assert.equal(frame.hidden,true);
    assert.equal(notice.textContent,'Loading suite card…');assert.equal(link.hidden,false);
    await finish(0);assert.equal(frame.src,'/suite-card?id=A');assert.equal(frame.hidden,false);assert.equal(notice.hidden,true);
    assert.equal(link.href,'/suite-card?id=A');assert.equal(frame.title,'Suite A suite card');
    assert.equal(requests[0].url,'http://127.0.0.1:8767/suite-card?id=A');
    assert.equal(requests[0].options.credentials,'same-origin');assert.equal(requests[0].options.redirect,'error');
  } else if(input.case==='route_error') {
    const error='Report path is excluded from project access <img src=x onerror=alert(1)>';
    selectSuite('A');await finish(0,response(false,error,'application/json; charset=utf-8'));
    assert.equal(frame.src,undefined);assert.equal(frame.hidden,true);assert.equal(notice.hidden,false);
    assert.equal(notice.textContent,error);assert.equal('innerHTML' in notice,false);assert.equal(link.hidden,false);
    selectSuite('A');await finish(1);assert.equal(frame.hidden,false);assert.equal(notice.hidden,true);
  } else if(input.case==='network_error') {
    selectSuite('A');requests[0].reject(Error('Network unavailable'));await tick();
    assert.equal(notice.textContent,'Network unavailable');assert.equal(frame.hidden,true);assert.equal(frame.src,undefined);
  } else if(input.case==='invalid_response') {
    selectSuite('A');await finish(0,response(true,null,'application/json'));
    assert.equal(notice.textContent,'Suite card did not return an HTML page.');assert.equal(frame.src,undefined);
    selectSuite('A');await finish(1,{...response(false,null,'application/json'),json:async()=>{throw Error('bad json');}});
    assert.equal(notice.textContent,'Suite card could not be loaded (HTTP 400).');
  } else if(input.case==='foreign_origin') {
    suiteById.get('A').card_url='https://elsewhere.invalid/card';selectSuite('A');await tick();
    assert.equal(requests.length,0);assert.equal(notice.textContent,'Suite cards must use the same origin as NAIA.');
    assert.equal(frame.src,undefined);
  } else if(input.case==='switch_race') {
    selectSuite('A');selectSuite('B');await finish(1);await finish(0,response(false,'Old failure','application/json'));
    assert.equal(frame.src,'/suite-card?id=B');assert.equal(frame.hidden,false);assert.equal(notice.hidden,true);
    assert.equal(frame.title,'Suite B suite card');assert.equal(link.href,'/suite-card?id=B');
  } else if(input.case==='close_race') {
    selectSuite('A');dialog.close();await finish(0);
    assert.equal(frame.src,undefined);assert.equal(frame.hidden,true);assert.equal(dialog.open,false);
    selectSuite('A');dialog.close();selectSuite('A');await finish(1);assert.equal(frame.src,undefined);
    await finish(2);assert.equal(frame.src,'/suite-card?id=A');assert.equal(frame.hidden,false);
    dialog.close();assert.equal(frame.src,undefined);assert.equal(frame.hidden,true);
  } else if(input.case==='unavailable') {
    selectSuite('A');suiteById.get('B').card_available=false;suiteById.get('B').card_error='Missing suite card';
    selectSuite('B');await finish(0);
    assert.equal(requests.length,1);assert.equal(frame.src,undefined);assert.equal(frame.hidden,true);
    assert.equal(notice.hidden,false);assert.equal(notice.textContent,'Missing suite card');assert.equal(link.hidden,true);
  } else if(input.case==='reload') {
    selectSuite('A');selectSuite('A');assert.equal(requests.length,1);await finish(0);
    selectSuite('A');assert.equal(requests.length,1);assert.equal(frame.hidden,false);
    selectSuite('A',{reloadCard:true});assert.equal(requests.length,2);assert.equal(frame.src,undefined);
    await finish(1,response(false,'New failure','application/json'));
    assert.equal(notice.textContent,'New failure');assert.equal(frame.hidden,true);
  } else throw Error('Unknown case '+input.case);
})().catch(error=>{console.error(error);process.exitCode=1;});
`,context);
"""


@unittest.skipUnless(NODE, "Node is needed for suite-card UI contracts")
class SuiteCardViewerTest(unittest.TestCase):
    def case(self, name):
        source = (ROOT / "src/naia/assets/app.js").read_text()
        viewer = source[source.index("function cancelSuiteCardLoad()"):
                        source.index("async function setSuiteStatus(")]
        close = next(line for line in source.splitlines()
                     if line.startswith("$('suiteDialog').addEventListener('close'"))
        result = subprocess.run(
            [NODE, "-e", FIXTURE],
            input=json.dumps({"source": viewer, "close": close, "case": name}),
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_success_keeps_same_origin_iframe_and_new_tab_link(self):
        self.case("success")

    def test_route_error_is_text_and_reopening_retries(self):
        self.case("route_error")

    def test_network_error_never_loads_failed_iframe(self):
        self.case("network_error")

    def test_non_html_and_malformed_error_have_readable_fallbacks(self):
        self.case("invalid_response")

    def test_foreign_card_url_is_not_fetched(self):
        self.case("foreign_origin")

    def test_late_response_cannot_replace_another_suite(self):
        self.case("switch_race")

    def test_close_and_reopen_ignore_earlier_requests(self):
        self.case("close_race")

    def test_known_unreadable_card_cancels_pending_viewer(self):
        self.case("unavailable")

    def test_refresh_preserves_loaded_card_and_explicit_reload_rechecks(self):
        self.case("reload")


if __name__ == "__main__":
    unittest.main()
