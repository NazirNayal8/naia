"""Run the production queue renderer/drag handlers without real project records."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def queue_source():
    source = (ROOT / "src/naia/assets/app.js").read_text()
    return (source[source.index("function taskItems("):source.index("async function act(")]
            + source[source.index("function animateDeckMove("):source.index("function notesHTML(")])


FIXTURE = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Element {
  constructor(tag) {this.tagName=tag.toUpperCase();this.children=[];this.dataset={};
    this.attrs={};this.listeners={};this.style={setProperty(){}};this.className='';
    this.offsetHeight=100;this._text='';this._html='';
    this.classList={contains:name=>this.className.split(/\s+/).includes(name),
      add:(...names)=>{this.className=[...new Set([...this.className.split(/\s+/),...names])].filter(Boolean).join(' ');},
      remove:(...names)=>{this.className=this.className.split(/\s+/).filter(name=>!names.includes(name)).join(' ');},
      toggle:(name,force)=>{const on=force??!this.classList.contains(name);
        this.classList[on?'add':'remove'](name);return on;}};
  }
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set innerHTML(value){this._html=value;this.children=[];}
  get innerHTML(){return this._html;}
  append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
  replaceChildren(...children){this.children=[];this.append(...children);}
  insertBefore(child,reference){this.children=this.children.filter(node=>node!==child);
    const index=reference?this.children.indexOf(reference):this.children.length;
    assert.ok(index>=0);this.children.splice(index,0,child);child.parent=this;}
  get nextSibling(){return this.parent?.children[this.parent.children.indexOf(this)+1]||null;}
  matches(selector){if(selector.startsWith('.'))return selector.slice(1).split('.').every(name=>this.classList.contains(name));
    if(selector.startsWith('['))return selector==='[data-detail]'&&this.dataset.detail!==undefined;
    return selector.toUpperCase()===this.tagName;}
  querySelectorAll(selector){return this.children.flatMap(child=>[
    ...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  closest(selector){return selector.split(',').some(part=>this.matches(part))?this:this.parent?.closest(selector)||null;}
  setAttribute(name,value){this.attrs[name]=value;}
  addEventListener(name,callback){(this.listeners[name]||=[]).push(callback);}
  getBoundingClientRect(){return {left:0,top:(this.parent?.children.indexOf(this)||0)*100};}
  async fire(name,extra={}){const event={target:this,preventDefault(){this.prevented=true;},
    dataTransfer:{effectAllowed:'',setData(){}},...extra};
    for(const callback of this.listeners[name]||[])await callback(event);return event;}
}
const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);};
const calls=[],context={console,state:null,items:[],ordered:[],focusId:'',unpacked:false,draggedId:null,
  $:node,document:{createElement:tag=>new Element(tag)},
  element:(tag,text,cls)=>{const out=new Element(tag);if(text!==undefined)out.textContent=text;if(cls)out.className=cls;return out;},
  button:(text,callback,cls='ghost')=>{const out=new Element('button');out.textContent=text;out.className=cls;
    out.addEventListener('click',callback);return out;},
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  guarded:callback=>callback,act:async(action,payload)=>calls.push({action,payload}),
  matchMedia:()=>({matches:true}),openTaskForm(){},openCompletion(){},removeTask(){}};
vm.createContext(context);vm.runInContext(input.source,context);
function setTasks(tasks,focus='') {context.state={tasks:{items:tasks},focus_id:focus,architectures:[]};context.renderQueue();}
function task(id,status='ready'){return {id,title:'Task '+id,status,goal:'Review '+id,priority:50,materials:[]};}
function ids(){return node('deck').children.filter(card=>card.classList.contains('task-card')).map(card=>card.dataset.id);}
function card(id){return node('deck').children.find(card=>card.dataset.id===id);}
function assertIds(expected){assert.deepEqual(ids(),expected);}
(async()=>{
  if(input.case==='promotion') {
    const tasks=[task('A'),task('C','active'),task('B','in_progress'),task('D','paused'),task('E','done')];
    const before=JSON.stringify(tasks);setTasks(tasks,'A');assertIds(['C','B','A','D']);
    assert.equal(JSON.stringify(tasks),before);assert.equal(context.focusId,'C');
    assert.equal(node('count').textContent,'4 open · 2 active');
    for(const id of ['C','B']){assert.equal(card(id).classList.contains('is-active'),true);
      assert.match(card(id).innerHTML,/active-badge/);assert.match(card(id).innerHTML,/>Active<\/span>/);}
    assert.equal(card('A').classList.contains('is-active'),false);
    assert.equal(card('A').innerHTML.includes('active-badge'),false);
    assert.equal(card('C').classList.contains('focused'),true);
    assert.equal(card('B').classList.contains('focused'),false);
  } else if(input.case==='packed') {
    setTasks([task('A'),task('B','active'),task('C','active')]);
    assert.equal(node('deck').className,'deck packed has-active');
    assert.equal(node('deckToggle').textContent,'Unpack all');
    assert.ok(node('deck').children.every(card=>card.draggable===false));
    context.unpacked=true;context.applyDeck();
    assert.equal(node('deck').className,'deck unpacked has-active');
    assert.ok(node('deck').children.every(card=>card.draggable));
    assert.equal(node('reorderHint').textContent,'Drag within active or queued tasks to reorder');
    setTasks([task('A'),task('B')]);context.unpacked=false;context.applyDeck();
    assert.equal(node('deck').className,'deck packed');
    assert.equal(node('count').textContent,'2 open · 0 active');
  } else if(input.case==='details_focus') {
    setTasks([task('A'),task('B','active'),task('C','active')],'C');
    assert.equal(context.focusId,'C');assert.equal(card('C').classList.contains('focused'),true);
    await card('B').querySelector('[data-detail]').fire('click');
    assert.equal(card('B').querySelector('.details').classList.contains('open'),true);
    context.renderQueue();assert.equal(card('B').querySelector('.details').classList.contains('open'),true);
    const complete=card('B').querySelector('.details').querySelectorAll('button').find(button=>button.textContent==='Complete');
    assert.ok(complete);assert.ok(node('pauseCurrentAction').children.length);
  } else if(input.case==='fallback') {
    setTasks([{id:'A',title:'No status'},task('B','done'),task('C','removed')],'C');
    assertIds(['A']);assert.equal(context.focusId,'A');assert.match(card('A').innerHTML,/>ready<\/span>/);
    assert.ok(card('A').querySelector('.details').querySelectorAll('button').some(button=>button.textContent==='Start'));
    setTasks([]);assert.equal(context.focusId,'');assert.equal(node('resolveNext').disabled,true);
    assert.equal(node('count').textContent,'0 open · 0 active');
  } else if(input.case==='drag_groups') {
    context.unpacked=true;setTasks([task('A'),task('B','active'),task('C'),task('D','active')]);
    assertIds(['B','D','A','C']);
    await node('deck').fire('dragstart',{target:card('D')});
    const across=await node('deck').fire('dragover',{target:card('A'),clientY:201});
    assert.equal(across.prevented,undefined);assertIds(['B','D','A','C']);
    await node('deck').fire('dragover',{target:card('B'),clientY:1});assertIds(['D','B','A','C']);
    await node('deck').fire('drop',{target:card('B')});
    assert.equal(calls.length,1);assert.equal(calls[0].action,'reorder');
    assert.deepEqual(Array.from(calls[0].payload.ordered_ids),['D','B','A','C']);
    await node('deck').fire('dragend');
    await node('deck').fire('dragstart',{target:card('C')});
    await node('deck').fire('dragover',{target:card('A'),clientY:201});assertIds(['D','B','C','A']);
    await node('deck').fire('drop',{target:card('D')});assert.equal(calls.length,1);
    assertIds(['B','D','A','C']);
  } else if(input.case==='task_shapes') {
    context.state={tasks:{items:{A:task('A'),B:task('B','active'),C:task('C')},order:['C','A','B']},architectures:[]};
    context.renderQueue();assertIds(['B','C','A']);
    context.state.tasks.items.B.status='paused';context.renderQueue();assertIds(['C','A','B']);
    assert.equal(node('deck').classList.contains('has-active'),false);
  } else throw Error('Unknown case '+input.case);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@unittest.skipUnless(NODE, "Node is needed for production queue UI contracts")
class ActiveQueueUITest(unittest.TestCase):
    def case(self, name):
        result = subprocess.run([NODE, "-e", FIXTURE],
                                input=json.dumps({"source": queue_source(), "case": name}),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_active_and_legacy_statuses_promote_without_mutation_and_have_badges(self):
        self.case("promotion")

    def test_packed_mode_marks_all_active_tasks_and_preserves_no_active_fallback(self):
        self.case("packed")

    def test_selected_active_focus_and_details_survive_rendering(self):
        self.case("details_focus")

    def test_missing_status_is_ready_and_closed_tasks_are_never_focused(self):
        self.case("fallback")

    def test_dragging_orders_within_groups_but_never_crosses_the_active_boundary(self):
        self.case("drag_groups")

    def test_both_array_and_keyed_task_payloads_restore_manual_order_after_pause(self):
        self.case("task_shapes")


class ActiveQueueStyleTest(unittest.TestCase):
    def test_packed_visibility_has_no_rule_that_hides_other_active_tasks(self):
        css = (ROOT / "src/naia/assets/style.css").read_text()
        self.assertIn(".deck.packed:not(.has-active) .task-card:not(:first-child){display:none}", css)
        self.assertIn(".deck.packed.has-active .task-card:not(.is-active){display:none}", css)
        self.assertNotIn(".deck.packed .task-card:not(:first-child)", css)

    def test_highlight_matches_local_palette_without_card_size_changes(self):
        css = (ROOT / "src/naia/assets/style.css").read_text()
        self.assertIn(".task-card .top{min-height:26px}", css)
        self.assertIn(".task-card.is-active{background:linear-gradient(115deg,#203c36,#202d29)", css)
        self.assertIn("border-color:#53bba1;border-left-color:#4fd1b0", css)
        self.assertIn(".task-card.is-active .details{border-top-color:#3b685b}", css)
        active_rule = css.split(".task-card.is-active{", 1)[1].split("}", 1)[0]
        self.assertNotIn("padding:", active_rule)
        self.assertNotIn("font-size:", active_rule)
        self.assertNotIn("transform:", active_rule)


if __name__ == "__main__":
    unittest.main()
