'use strict';
let state = null;
let selectedArchitecture = null;
const element = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
function button(label, action) { const b = element('button', label); b.addEventListener('click', async () => { b.disabled = true; try { await action(); } catch (e) { message(e.message, true); } finally { b.disabled = false; } }); return b; }
function message(text, error=false) { const n = document.querySelector('#status'); n.textContent=text; n.className=error?'error':''; }
async function request(path, data) {
  const options = data ? {method:'POST',headers:{'Content-Type':'application/json','X-NAIA-Token':state.token},body:JSON.stringify(data)} : {};
  const response = await fetch(path, options); const result = await response.json(); if (!response.ok) throw Error(result.error || 'Request failed'); return result;
}
async function action(id, value) { const note = ['done','cancel'].includes(value) ? prompt('Decision or note (optional):','') : ''; if (note===null) return; await request('/api/task',{id,action:value,note}); await refresh(); }
function showTab(id) {
  for (const tab of document.querySelectorAll('main section')) tab.hidden=tab.id!==id;
  for (const tab of document.querySelectorAll('nav button')) tab.classList.toggle('selected',tab.dataset.tab===id);
}
function openArchitecture(id) { selectedArchitecture=id; renderArchitectures(); showTab('architectures'); }
function relatedArchitectures(card, field, id) {
  const related=(state.architectures||[]).filter(item=>item[field]===id);
  if (!related.length) return;
  const links=element('div',undefined,'architecture-links');
  links.append(element('span','Architecture','field-label'));
  for (const architecture of related) links.append(button(architecture.title,()=>openArchitecture(architecture.id)));
  card.append(links);
}
function renderTasks() {
  const host = document.querySelector('#tasks'); host.replaceChildren(); const cards=element('div',undefined,'cards');
  for (const id of state.tasks.order) {
    const task=state.tasks.items[id]; if (['done','cancelled'].includes(task.status)) continue;
    const card=element('article',undefined,'card '+(task.status==='active'?'active':''));
    card.append(element('span',task.status+' · '+task.owner,'tag'),element('h2',task.title),element('p',task.goal),element('strong','Decision: '+task.decision));
    if(task.depends_on.length) card.append(element('p','Related tasks: '+task.depends_on.join(', ')));
    if(task.materials?.length) {
      const materials=element('ul',undefined,'materials');
      for (const material of task.materials) materials.append(element('li',material));
      card.append(element('p','Review materials','field-label'),materials);
    }
    relatedArchitectures(card,'task',id);
    const actions=element('div',undefined,'actions');
    const available=task.status==='active'?['pause','done']:task.status==='paused'?['resume','done']:['start','move-top','done'];
    for (const value of available) actions.append(button(value.replace('-',' '),()=>action(id,value)));
    card.append(actions); cards.append(card);
  }
  host.append(cards.childElementCount?cards:element('div','No reviews queued. Ask your assistant to add a task.','empty'));
}
function renderSuites() {
  const host=document.querySelector('#suites'); host.replaceChildren(); const graph=element('div',undefined,'graph');
  const svgNS='http://www.w3.org/2000/svg'; const svg=document.createElementNS(svgNS,'svg'); const byId=new Map(state.suites.map(s=>[s.id,s])); const levels=new Map(),positions=new Map(),counts=new Map();
  function level(id){if(levels.has(id))return levels.get(id);const s=byId.get(id);const n=s.predecessors.length?1+Math.max(...s.predecessors.map(level)):0;levels.set(id,n);return n;}
  for(const suite of state.suites){const depth=level(suite.id),row=counts.get(depth)||0;counts.set(depth,row+1);positions.set(suite.id,{x:20+depth*245,y:20+row*90});}
  function shape(tag,attrs){const n=document.createElementNS(svgNS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;}
  const width=state.suites.length?Math.max(...[...positions.values()].map(p=>p.x))+220:300,height=Math.max(100,...[...positions.values()].map(p=>p.y+80));svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('width',width);svg.setAttribute('height',height);svg.setAttribute('role','img');svg.setAttribute('aria-label','Scientific suite lineage, not scheduler dependencies');
  for(const suite of state.suites)for(const predecessor of suite.predecessors){const a=positions.get(predecessor),b=positions.get(suite.id);svg.append(shape('path',{d:`M${a.x+205},${a.y+28} C${a.x+230},${a.y+28} ${b.x-25},${b.y+28} ${b.x},${b.y+28}`,class:'lineage-edge'}));svg.append(shape('path',{d:`M${b.x-6},${b.y+24} L${b.x},${b.y+28} L${b.x-6},${b.y+32}`,class:'lineage-edge'}));}
  for(const suite of state.suites){const p=positions.get(suite.id);svg.append(shape('rect',{x:p.x,y:p.y,width:205,height:56,rx:10,class:'lineage-node'}));const label=shape('text',{x:p.x+12,y:p.y+24,class:'lineage-label'});label.textContent=suite.id;svg.append(label);const status=shape('text',{x:p.x+12,y:p.y+43,class:'lineage-status'});status.textContent=suite.results_ready?'Ready for review':suite.status;svg.append(status);}
  if(state.suites.length)graph.append(svg);
  host.append(graph); const cards=element('div',undefined,'cards');
  for(const suite of state.suites) { const card=element('article',undefined,'card'); card.append(element('span',suite.results_ready?'Results ready for review':suite.status,'tag'),element('h2',suite.title)); relatedArchitectures(card,'suite',suite.id); const detail=element('details'); detail.append(element('summary','Suite card'),element('pre',state.cards[suite.id])); card.append(detail); cards.append(card); }
  host.append(cards.childElementCount?cards:element('div','No suites registered. Discuss your next experiment with your assistant.','empty'));
}
function renderArchitectures() {
  const host=document.querySelector('#architectures');
  const existingFrame=host.querySelector('iframe');
  host.replaceChildren();
  const architectures=state.architectures||[];
  if (!architectures.length) {
    host.append(element('div','No architectures saved yet. Ask your assistant to capture a model and attach it to a suite or review task.','empty'));
    return;
  }
  if (!architectures.some(item=>item.id===selectedArchitecture)) selectedArchitecture=(architectures.find(item=>item.available)||architectures[0]).id;
  const layout=element('div',undefined,'architecture-workspace');
  const library=element('aside',undefined,'architecture-library');
  library.append(element('h2','Saved architectures'),element('p','Select a model to inspect its hierarchy and observed calls.'));
  for (const architecture of architectures) {
    const choice=button(architecture.title,()=>openArchitecture(architecture.id));
    choice.className='architecture-choice'+(architecture.id===selectedArchitecture?' selected':'');
    choice.setAttribute('aria-pressed',String(architecture.id===selectedArchitecture));
    const metadata=[architecture.suite,architecture.task].filter(Boolean).join(' · ')||architecture.id;
    choice.append(element('small',metadata),element('span',architecture.available?'Saved graph':'Unavailable','tag'+(architecture.available?'':' error')));
    library.append(choice);
  }
  const architecture=architectures.find(item=>item.id===selectedArchitecture);
  const viewer=element('article',undefined,'architecture-viewer');
  const heading=element('div',undefined,'architecture-heading');
  const title=element('div'); title.append(element('h2',architecture.title));
  const associations=[architecture.suite&&'Suite: '+architecture.suite,architecture.task&&'Review: '+architecture.task].filter(Boolean);
  if (associations.length) title.append(element('p',associations.join(' · ')));
  heading.append(title);
  if (architecture.available) {
    const url='/architecture?id='+encodeURIComponent(architecture.id);
    const link=element('a','Open full viewer','viewer-link'); link.href=url; link.target='_blank'; link.rel='noopener';
    heading.append(link); viewer.append(heading);
    let frame=existingFrame;
    if (!frame || frame.dataset.architectureId!==architecture.id) {
      frame=element('iframe'); frame.src=url; frame.dataset.architectureId=architecture.id; frame.loading='lazy';
    }
    frame.title='Architecture: '+architecture.title;
    viewer.append(frame);
  } else {
    viewer.append(heading,element('div',architecture.error||'This saved graph is unavailable. Ask your assistant to capture and register it again.','empty error'));
  }
  layout.append(library,viewer); host.append(layout);
}
function renderContext() {
  const host=document.querySelector('#context'); host.replaceChildren();
  host.append(element('h2','Onboarding: '+state.context.onboarding.status));
  const integration = state.context.assistants;
  host.append(element('p',integration?.selection ? 'Assistant integration: '+integration.selection+' · '+integration.instruction_files.join(', ') : 'Ask your assistant to choose Codex, Claude, or both.'));
  for(const [key, answer] of Object.entries(state.context.answers)) { const card=element('article',undefined,'card'); card.append(element('strong',key+' · '+(answer.confirmed?'confirmed':'needs user input')),element('pre',JSON.stringify(answer.value,null,2))); host.append(card); }
  host.append(element('p','Ask your assistant to update project settings. This view does not edit or confirm answers.'));
}
async function refresh() { state=await request('/api/state'); renderTasks(); renderSuites(); renderArchitectures(); renderContext(); }
for (const b of document.querySelectorAll('nav button')) b.addEventListener('click',()=>showTab(b.dataset.tab));
document.querySelector('#sync').addEventListener('click',async()=>{ try { await request('/api/sync',{}); await refresh(); message('Validated results refreshed.'); } catch(e) { message(e.message,true); } });
refresh().catch(e=>message(e.message,true));
