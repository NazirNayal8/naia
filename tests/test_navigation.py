"""Execute the production tab navigation against a small DOM/history fixture."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


NODE = shutil.which("node")


def navigation_source():
    source = (Path(__file__).resolve().parents[1] / "src/naia/assets/app.js").read_text()
    storage = source[source.index("const DECK_KEY="):source.index("let unpacked=")]
    production = storage + source[source.index("const VIEW_PANELS="):source.index("function suiteStatus(")]
    startup = re.search(r"^const initialView=.*$", source, re.MULTILINE).group()
    invocation = re.search(r"^setView\(initialView.*$", source, re.MULTILINE).group()
    startup += "\n" + invocation.split(".then(refresh)", 1)[0] + ";"
    popstate = re.search(r"^window.addEventListener\('popstate'.*$", source,
                         re.MULTILINE).group()
    return {"production": production, "startup": startup, "popstate": popstate,
            "view_key": "naia.view", "export": True}


FIXTURE = r"""
const assert=require('node:assert/strict'), vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const tabs=['queue','suites','arch','reports'];
function fixture(href,storedView='queue') {
  const nodes=new Map(), storage=new Map([[input.view_key,storedView]]), listeners={};
  function node(id) {
    if(!nodes.has(id))nodes.set(id,{id,hidden:false,dataset:{view:id.replace(/Tab$/,'')},attrs:{},
      classList:{toggle(){}},setAttribute(key,value){this.attrs[key]=value;}});
    return nodes.get(id);
  }
  const historyEntries=[href],calls=[];
  let position=0;
  const context={URL,URLSearchParams,console,location:new URL(href),state:{},currentView:'queue',
    graphReady:false,$:node,document:{getElementById:node,body:node('body'),
      querySelector:selector=>node(selector),querySelectorAll:selector=>
        selector==='[data-view]'?tabs.map(name=>node(name+'Tab')):[node('queueAction')]},
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
    addEventListener:(kind,callback)=>(listeners[kind]??=[]).push(callback),
    renderSuiteGraph:()=>{context.graphReady=true;},renderArchive:async()=>{},message:()=>{},
    NAIAReports:{show:async()=>{}},ArchViz:{show:()=>{}},
    history:{pushState(state,title,url){context.location=new URL(url);historyEntries.splice(++position);
      historyEntries.push(context.location.href);calls.push('push');},
      replaceState(state,title,url){context.location=new URL(url);historyEntries[position]=context.location.href;
        calls.push('replace');}}};
  context.window=context;
  vm.createContext(context);
  vm.runInContext(input.production+'\n'+input.startup+'\n'+input.popstate,context);
  return {context,calls,storage,historyEntries,node,
    async select(view){await context.setView(view,true);},
    async traverse(delta){position+=delta;context.location=new URL(historyEntries[position]);
      for(const callback of listeners.popstate||[])await callback();},
    view(){return vm.runInContext('Object.keys(VIEW_PANELS).find(name=>!document.getElementById(VIEW_PANELS[name]).hidden)',context);}};
}
function checkView(f,view){assert.equal(f.view(),view);assert.equal(f.context.location.searchParams.get('view'),view);
  if(view!=='archive')assert.equal(f.node(view+'Tab').attrs['aria-selected'],'true');}
(async()=>{
  const base='http://127.0.0.1:8766/';
  if(input.case==='refresh') {
    for(const view of tabs){const f=fixture(base+'?view=reports','reports');await f.select(view);checkView(f,view);
      const fresh=fixture(f.context.location.href,view==='reports'?'queue':'reports');checkView(fresh,view);
      assert.equal(fresh.historyEntries.length,1);assert.ok(!fresh.calls.includes('push'));}
  } else if(input.case==='initial') {
    for(const view of tabs){const f=fixture(base+'?view='+view+'&task=T1&suite=S1#figure','reports');
      checkView(f,view);assert.equal(f.historyEntries.length,1);assert.deepEqual(f.calls,[]);}
    const f=fixture(base+'?view=reports,&task=T1#figure','queue');checkView(f,'reports');
    assert.deepEqual(f.calls,['replace']);assert.equal(f.context.location.searchParams.get('task'),'T1');
    assert.equal(f.context.location.hash,'#figure');
  } else if(input.case==='history') {
    const f=fixture(base+'?view=reports');await f.select('queue');await f.select('suites');await f.select('arch');
    assert.equal(f.historyEntries.length,4);await f.traverse(-1);checkView(f,'suites');
    await f.traverse(-1);checkView(f,'queue');await f.traverse(-1);checkView(f,'reports');
    await f.traverse(1);checkView(f,'queue');await f.traverse(1);checkView(f,'suites');
    await f.traverse(1);checkView(f,'arch');assert.deepEqual(f.calls,['push','push','push']);
    await f.select('arch');assert.equal(f.historyEntries.length,4);
    assert.deepEqual(f.calls,['push','push','push']);
  } else if(input.case==='parameters') {
    const f=fixture(base+'?view=reports&task=T%2B1&suite=S%2F1&extra=a%20b&extra=c#figure-2');
    for(const view of tabs){await f.select(view);checkView(f,view);
      assert.equal(f.context.location.searchParams.get('task'),'T+1');
      assert.equal(f.context.location.searchParams.get('suite'),'S/1');
      assert.deepEqual(f.context.location.searchParams.getAll('extra'),['a b','c']);
      assert.equal(f.context.location.hash,'#figure-2');}
  } else if(input.case==='invalid') {
    for(const view of ['missing','__proto__','constructor','toString']) {
      const f=fixture(base+'?view='+view,'reports');checkView(f,'queue');
      assert.deepEqual(f.calls,['replace']);await f.select(view);checkView(f,'queue');
      assert.deepEqual(f.calls,['replace']);}
  } else if(input.case==='storage') {
    for(const view of tabs){const f=fixture(base+'?task=T1#figure',view);checkView(f,view);
      assert.deepEqual(f.calls,['replace']);assert.equal(f.context.location.searchParams.get('task'),'T1');
      assert.equal(f.context.location.hash,'#figure');}
    const f=fixture(base,'constructor');checkView(f,'queue');assert.deepEqual(f.calls,['replace']);
  } else if(input.case==='archive') {
    const f=fixture(base+'archive?task=T1#figure','reports');checkView(f,'archive');
    assert.equal(f.context.location.pathname,'/');assert.deepEqual(f.calls,['replace']);
    assert.equal(f.node('nav').hidden,true);assert.equal(f.storage.get(input.view_key),'reports');
    await f.select('queue');checkView(f,'queue');assert.equal(f.node('nav').hidden,false);
    await f.traverse(-1);checkView(f,'archive');assert.equal(f.historyEntries.length,2);
    const fresh=fixture(f.context.location.href,'reports');checkView(fresh,'archive');
    assert.equal(fresh.context.location.searchParams.get('task'),'T1');assert.equal(fresh.context.location.hash,'#figure');
  } else throw Error('Unknown navigation case: '+input.case);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@unittest.skipUnless(NODE, "Node is needed for tab navigation contracts")
class NavigationTest(unittest.TestCase):
    def case(self, name):
        result = subprocess.run([NODE, "-e", FIXTURE],
                                input=json.dumps({**navigation_source(), "case": name}),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_selected_tab_survives_refresh_even_with_stale_storage(self):
        self.case("refresh")

    def test_initial_url_wins_and_report_comma_is_replaced(self):
        self.case("initial")

    def test_browser_history_restores_tabs_without_extra_entries(self):
        self.case("history")

    def test_tab_changes_preserve_task_suite_query_and_fragment(self):
        self.case("parameters")

    def test_invalid_and_inherited_view_names_fall_back_to_queue(self):
        self.case("invalid")

    def test_missing_url_view_uses_storage_and_canonicalizes_url(self):
        self.case("storage")

    def test_archive_navigation_canonicalizes_path_and_preserves_return_history(self):
        self.case("archive")


if __name__ == "__main__":
    unittest.main()
