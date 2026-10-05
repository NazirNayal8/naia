'use strict';
let state = null, items = [], ordered = [], focusId = '', editingId = null, draggedId = null;
let completion = null, selectedArchitecture = null, selectedSuiteId = null, currentView = 'queue';
let suiteById = new Map(), graphNodes = new Map(), graphEdges = [];
let graphReady = false, graphScale = 1, graphOffset = {x:0,y:0}, graphBounds = {x:0,y:0,width:800,height:500};
const $ = id => document.getElementById(id);
const element = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const DECK_KEY='naia.deck.unpacked', VIEW_KEY='naia.view', POS_KEY='naia.suiteGraph.positions', SEALED_KEY='naia.suiteGraph.hideSealed';
function stored(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; } }
function storeValue(key, value) { try { localStorage.setItem(key,value); } catch (_) {} }
let unpacked=stored(DECK_KEY,'0')==='1', hideSealed=stored(SEALED_KEY,'0')==='1';
function esc(value) { return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function message(text='', error=false) {
  $('status').textContent=text; $('status').className=error?'error':'';
  for (const node of document.querySelectorAll('dialog [data-error]')) node.textContent=error&&node.closest('dialog').open?text:'';
}
function guarded(action) {
  return async event => {
    const control=event?.currentTarget, submit=control?.tagName==='FORM'?control.querySelector('button[type="submit"]'):control;
    if (submit?.tagName==='BUTTON') submit.disabled=true;
    try { await action(event); } catch (error) { message(error.message || String(error),true); }
    finally { if(submit?.tagName==='BUTTON') submit.disabled=false; }
  };
}
function button(text, action, cls='ghost') {
  const node=element('button',text,cls); node.type='button'; node.addEventListener('click',guarded(action)); return node;
}
async function request(path, data) {
  const options=data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-NAIA-Token':state?.token || ''},body:JSON.stringify(data)};
  const response=await fetch(path,options), result=await response.json();
  if(!response.ok)throw Error(result.error || 'Request failed');
  return result;
}
function taskItems(tasks) {
  if (Array.isArray(tasks?.items)) return tasks.items;
  const byId=tasks?.items || {};
  return (tasks?.order || Object.keys(byId)).map(id=>byId[id]).filter(Boolean);
}
function isActive(task) { return ['active','in_progress'].includes(task?.status); }
function priorityColor(score) { const ratio=(Math.max(1,Math.min(100,Number(score)||1))-1)/99; return 'hsl('+(215-ratio*210)+' 72% 52%)'; }
function oneSentence(value) { const text=String(value ?? '').trim(), match=text.match(/^.*?[.!?](?:\s|$)/); return match?match[0].trim():text; }
function materialLink(material) {
  const value=String(material);
  const url=/^https?:\/\//i.test(value)?value:'/material?path='+encodeURIComponent(value);
  return '<a target="_blank" rel="noopener" href="'+esc(url)+'">'+esc(value)+'</a>';
}
function dependencies(task) {
  if(!task.depends_on?.length)return '';
  const byId=new Map(items.map(item=>[item.id,item]));
  return '<div class="label">Related tasks · informational only</div><div class="dependency-list">'+task.depends_on.map(id=>{
    const related=byId.get(id), resolved=related?.status==='done', status=resolved?'resolved':related?.status || 'missing';
    return '<span class="dependency '+(resolved?'':'unresolved')+'" title="'+esc(status)+'">'+esc(id)+' · '+esc(status)+'</span>';
  }).join('')+'</div>';
}
function architectureLinks(host, field, id) {
  const related=(state?.architectures || []).filter(item=>item[field]===id);
  if(!related.length)return;
  const links=element('div',undefined,'architecture-links'); links.append(element('span','Architecture','label'));
  for(const architecture of related)links.append(button(architecture.title,()=>openArchitecture(architecture.id)));
  host.append(links);
}
function taskCard(task,index) {
  const card=element('article',undefined,'task-card '+(task.id===focusId?'focused ':'')+task.status);
  card.dataset.id=task.id; card.draggable=unpacked;
  const score=task.priority ?? (ordered.length<=1?100:100-index*99/(ordered.length-1));
  card.style.setProperty('--priority-color',priorityColor(score));
  card.innerHTML='<div class="top"><span class="priority-mark"><span class="drag-handle" aria-hidden="true">⠿</span><span class="priority-dot" title="Relative priority" aria-label="Relative priority"></span></span><span class="status">'+esc(task.status)+'</span></div><h2>'+esc(task.title)+'</h2><p class="summary">'+esc(oneSentence(task.goal || task.decision || task.title))+'</p>';
  const details=element('div',undefined,'details'); details.id='task-details-'+index;
  const toggle=button('See full',()=>{
    const open=details.classList.toggle('open'); toggle.textContent=open?'Hide details':'See full'; toggle.setAttribute('aria-expanded',String(open));
  });
  toggle.dataset.detail='1'; toggle.setAttribute('aria-controls',details.id); toggle.setAttribute('aria-expanded','false');
  details.innerHTML='<div class="label">ID · TYPE · OWNER</div><p>'+esc(task.id)+' · '+esc(task.type || 'task')+' · '+esc(task.owner || 'unassigned')+'</p><div class="label">Full goal</div><p>'+esc(task.goal)+'</p><div class="label">Decision / deliverable</div><p>'+esc(task.decision)+'</p><div class="label">Review material</div><ul class="materials">'+((task.materials || []).map(value=>'<li>'+materialLink(value)+'</li>').join('') || '<li>None</li>')+'</ul>'+dependencies(task);
  architectureLinks(details,'task',task.id);
  const actions=element('div');
  if(task.status==='ready')actions.append(button('Start',()=>act('start',{id:task.id}),''));
  if(isActive(task))actions.append(button('Complete',()=>openCompletion(task.id),''),
    button('Pause',()=>act('pause',{id:task.id}),'secondary'));
  if(task.status==='paused')actions.append(button('Resume',()=>act('resume',{id:task.id}),''));
  actions.append(button('Modify',()=>openTaskForm(task.id),'secondary'),button('Remove',()=>removeTask(task.id),'danger'));
  details.append(actions); card.append(toggle,details); return card;
}
function applyDeck() {
  const mode=unpacked?'unpacked':'packed';
  $('deck').className='deck '+mode; $('deckWrap').className='deck-wrap '+mode+(ordered.length?'':' empty-deck');
  $('deckToggle').textContent=unpacked?'Pack cards':'Unpack all';
  $('reorderHint').textContent=unpacked?'Drag cards to set their priority':'Unpack cards to reorder them';
  for(const card of $('deck').querySelectorAll('.task-card'))card.draggable=unpacked;
}
function renderQueue() {
  const openIds=new Set([...$('deck').querySelectorAll('.task-card')].filter(card=>card.querySelector('.details.open')).map(card=>card.dataset.id));
  items=taskItems(state?.tasks); ordered=items.filter(task=>!['done','cancelled','removed'].includes(task.status));
  focusId=state?.focus_id || items.find(isActive)?.id || items.find(task=>task.status==='ready')?.id || '';
  $('deck').replaceChildren();
  for(const [index,task] of ordered.entries()) {
    const card=taskCard(task,index);
    if(openIds.has(task.id)){card.querySelector('.details').classList.add('open');const toggle=card.querySelector('[data-detail]');toggle.textContent='Hide details';toggle.setAttribute('aria-expanded','true');}
    $('deck').append(card);
  }
  if(!ordered.length)$('deck').append(element('div','No actionable tasks remain.','empty'));
  $('count').textContent=ordered.length+' open'; $('pauseCurrentAction').replaceChildren();
  const current=items.find(task=>task.id===focusId);
  if(isActive(current))$('pauseCurrentAction').append(button('Pause current',()=>act('pause',{id:current.id})));
  $('resolveNext').disabled=!focusId; applyDeck();
}
async function act(action,payload={}) {
  message(); await request('/api/action',{action,...payload}); await refresh(); return true;
}
function setValue(id,value) { $(id).value=value ?? ''; }
function listValue(id) { return $(id).value.split(/[,\n]/).map(value=>value.trim()).filter(Boolean); }
function openTaskForm(id=null) {
  const task=id?items.find(item=>item.id===id):null; editingId=task?.id || null;
  $('formTitle').textContent=task?'Modify task':'New task'; setValue('taskId',task?.id); $('taskId').disabled=Boolean(task);
  const choices=task?[['keep','Keep current position']]:[];
  choices.push(['top','Highest priority (top)']);
  for(const item of ordered)if(item.id!==task?.id)choices.push(['after:'+item.id,'After — '+item.title]);
  choices.push(['bottom','Lowest priority (bottom)']);
  $('taskPlacement').replaceChildren(...choices.map(([value,text])=>{const option=element('option',text);option.value=value;return option;}));
  setValue('taskPlacement',task?'keep':'bottom');setValue('taskTitle',task?.title);setValue('taskType',task?.type || 'task');setValue('taskOwner',task?.owner || 'unassigned');
  setValue('taskGoal',task?.goal);setValue('taskDecision',task?.decision);setValue('taskMaterials',(task?.materials || []).join('\n'));setValue('taskDependencies',(task?.depends_on || []).join('\n'));
  message();$('taskDialog').showModal();requestAnimationFrame(()=>$(task?'taskTitle':'taskId').focus());
}
async function saveTask(event) {
  event.preventDefault();
  const payload={id:editingId || $('taskId').value.trim(),placement:$('taskPlacement').value,title:$('taskTitle').value.trim(),type:$('taskType').value.trim() || 'task',owner:$('taskOwner').value.trim() || 'unassigned',goal:$('taskGoal').value.trim(),decision:$('taskDecision').value.trim(),materials:listValue('taskMaterials'),depends_on:listValue('taskDependencies')};
  await act(editingId?'edit':'add',payload);$('taskDialog').close();
}
function openCompletion(id=null) {
  const task=items.find(item=>item.id===(id || focusId)); if(!task)return;
  completion={action:id?'done':'resolve',id:task.id};
  $('completionTitle').textContent=id?'Complete task':'Resolve next task';$('completionContext').textContent=task.id+' — '+task.title;
  setValue('completionNote','');message();$('completionDialog').showModal();requestAnimationFrame(()=>$('completionNote').focus());
}
async function completeTask(event) {
  event.preventDefault();if(!completion)return;
  const payload={note:$('completionNote').value.trim(),id:completion.id};
  await act(completion.action,payload);$('completionDialog').close();
}
async function removeTask(id) {
  if(confirm('Remove '+id+' from the queue? It will remain available in the archive.'))await act('remove',{id});
}
function animateDeckMove(mutator) {
  const cards=[...$('deck').querySelectorAll('.task-card')], before=new Map(cards.map(card=>[card,card.getBoundingClientRect()]));
  mutator();
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  for(const card of cards){const first=before.get(card),last=card.getBoundingClientRect(),dx=first.left-last.left,dy=first.top-last.top;
    if((dx || dy)&&card.animate)card.animate([{transform:'translate('+dx+'px,'+dy+'px)'},{transform:'translate(0,0)'}],{duration:210,easing:'cubic-bezier(.2,.8,.2,1)'});
  }
}
$('deck').addEventListener('dragstart',event=>{
  const card=event.target.closest('.task-card');
  if(!unpacked || !card || event.target.closest('button,a,input,select,textarea')){event.preventDefault();return;}
  draggedId=card.dataset.id;card.classList.add('dragging');event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',draggedId);
});
$('deck').addEventListener('dragover',event=>{
  if(!unpacked || !draggedId)return;event.preventDefault();
  const dragged=[...$('deck').children].find(card=>card.dataset.id===draggedId),target=event.target.closest('.task-card');
  $('deck').querySelectorAll('.drag-over').forEach(card=>card.classList.remove('drag-over'));
  if(!dragged || !target || target===dragged)return;
  const before=event.clientY<target.getBoundingClientRect().top+target.offsetHeight/2,reference=before?target:target.nextSibling;
  if(reference===dragged || (before&&dragged.nextSibling===target))return;
  animateDeckMove(()=>$('deck').insertBefore(dragged,reference));target.classList.add('drag-over');
});
$('deck').addEventListener('drop',guarded(async event=>{
  if(!unpacked || !draggedId)return;event.preventDefault();
  const ids=[...$('deck').querySelectorAll('.task-card')].map(card=>card.dataset.id);
  try { await act('reorder',{ordered_ids:ids});$('reorderHint').textContent='Order saved · drag again to adjust'; }
  catch(error){renderQueue();throw error;}
}));
$('deck').addEventListener('dragend',()=>{
  $('deck').querySelectorAll('.task-card').forEach(card=>card.classList.remove('dragging','drag-over'));draggedId=null;
});
function notesHTML(task) {
  return (task.notes || []).map(note=>'<div class="label">'+esc(typeof note==='object'?note.at || 'Note':'Note')+'</div><p class="note">'+esc(typeof note==='object'?note.text:note)+'</p>').join('');
}
async function renderArchive() {
  const out=await request('/api/archive'), archived=Array.isArray(out)?out:out.items || [],host=$('archiveView');host.replaceChildren();
  archived.sort((a,b)=>String(b.archived_at || b.updated_at || '').localeCompare(String(a.archived_at || a.updated_at || '')));
  $('pageSubtitle').textContent=archived.length+' archived';
  for(const [index,task] of archived.entries()){
    const card=element('article',undefined,'task-card');
    card.style.setProperty('--priority-color',priorityColor(task.priority ?? (archived.length<=1?100:100-index*99/(archived.length-1))));
    card.innerHTML='<div class="top"><span class="priority-dot" title="Former relative priority" aria-label="Former relative priority"></span><span class="status">'+esc(task.archived_at || '')+'</span></div><h2>'+esc(task.title || task.id)+'</h2><p>'+esc(task.goal)+'</p><details><summary>See archived details</summary><div class="label">ID · Previous status · Owner</div><p>'+esc(task.id)+' · '+esc(task.status)+' · '+esc(task.owner || 'unassigned')+'</p><div class="label">Decision</div><p>'+esc(task.decision)+'</p><div class="label">Review material</div><ul class="materials">'+((task.materials || []).map(value=>'<li>'+materialLink(value)+'</li>').join('') || '<li>None</li>')+'</ul>'+notesHTML(task)+'</details>';
    host.append(card);
  }
  if(!archived.length)host.append(element('div','No removed tasks have been archived.','empty'));
}
const VIEW_PANELS={queue:'queueView',suites:'suitesView',arch:'archView',archive:'archiveView'};
const VIEW_SUBTITLES={queue:'Project queue · one decision at a time',suites:'Live experiment map · summaries and results',arch:'Network architectures · tensor shapes and observed calls',archive:'Removed tasks'};
async function setView(view,updateURL=false) {
  if(!VIEW_PANELS[view])view='queue';currentView=view;
  for(const [key,id] of Object.entries(VIEW_PANELS))$(id).hidden=key!==view;
  for(const tab of document.querySelectorAll('[data-view]')){const on=tab.dataset.view===view;tab.classList.toggle('active',on);tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1;}
  document.querySelector('nav').hidden=view==='archive';document.body.classList.toggle('archive-mode',view==='archive');
  document.querySelectorAll('.queue-action').forEach(node=>node.hidden=view!=='queue');
  $('pageTitle').textContent=view==='archive'?'Removed tasks':'NAIA';$('pageSubtitle').textContent=VIEW_SUBTITLES[view];
  $('archiveLink').textContent=view==='archive'?'← Active queue':'Archive';$('archiveLink').href=view==='archive'?'/':'/?view=archive';
  if(view!=='archive')storeValue(VIEW_KEY,view);
  if(updateURL){const url=new URL(location.href);if(url.pathname==='/archive')url.pathname='/';if(view==='queue')url.searchParams.delete('view');else url.searchParams.set('view',view);history.pushState({view},'',url);}
  if(state&&view==='suites'&&!graphReady)renderSuiteGraph(true);
  if(state&&view==='archive')await renderArchive();
}
function suiteStatus(suite) { return suite.ui_status || suite.status || 'proposed'; }
function suiteGroup(status) {
  if(['active','running','training','evaluating','reopened'].includes(status))return 'active';
  if(['sealed','shelved'].includes(status))return 'sealed';return 'pending';
}
function suiteColor(status) { return {active:'#45b97c',sealed:'#9b7cff',pending:'#d6a84b'}[suiteGroup(status)]; }
function svgEl(tag,attrs={}) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);
  return node;
}
const NODE_MIN_W=200,NODE_MAX_W=272,NODE_PAD=15,TITLE_LH=17,HEAD_H=34,NODE_FOOT=10,COL_GAP=34,ROW_GAP=78,GRAPH_PAD=46;
const TITLE_FONT='600 13px -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif',META_FONT='700 10px -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif';
let textRuler=null;try{textRuler=document.createElement('canvas').getContext('2d');}catch(_){}
function textWidth(text,font) { if(!textRuler)return String(text).length*(font===META_FONT?6:7);textRuler.font=font;return textRuler.measureText(String(text)).width; }
function wrapText(text,maxWidth,font) {
  const lines=[];let line='';
  for(const word of String(text || '').split(/\s+/).filter(Boolean)){
    const candidate=line?line+' '+word:word;
    if(line&&textWidth(candidate,font)>maxWidth){lines.push(line);line=word;}else line=candidate;
  }
  if(line)lines.push(line);return lines.length?lines:['Untitled'];
}
function nodeMetrics(node) {
  const tag=String(node.id || '').split('_')[0],status=suiteGroup(suiteStatus(node)).toUpperCase(),pill=Math.round(textWidth(status,META_FONT)+status.length*.6+20);
  const headWidth=NODE_PAD*2+textWidth(tag,META_FONT)+18+pill,lines=wrapText(node.title,NODE_MAX_W-NODE_PAD*2,TITLE_FONT),longest=Math.max(...lines.map(line=>textWidth(line,TITLE_FONT)));
  const width=Math.round(Math.max(NODE_MIN_W,headWidth,Math.min(NODE_MAX_W,longest+NODE_PAD*2)));
  return {tag,status,pill,lines,width,height:HEAD_H+lines.length*TITLE_LH+NODE_FOOT};
}
function effectiveParents(nodes,visible) {
  const parents=new Map();
  for(const node of nodes){
    const found=new Map(),seen=new Set([node.id]),stack=(node.predecessors || []).map(id=>({id,indirect:false}));
    while(stack.length){const link=stack.pop();if(visible.has(link.id)){if(!found.has(link.id)||!link.indirect)found.set(link.id,link.indirect);continue;}
      if(seen.has(link.id))continue;seen.add(link.id);
      for(const id of suiteById.get(link.id)?.predecessors || [])stack.push({id,indirect:true});
    }
    parents.set(node.id,[...found].map(([id,indirect])=>({id,indirect})));
  }
  return parents;
}
function suitePositions(nodes,parents) {
  const parentIds=id=>(parents.get(id) || []).map(link=>link.id),metrics=new Map(nodes.map(node=>[node.id,nodeMetrics(node)])),levels=new Map(nodes.map(node=>[node.id,0]));
  for(let pass=0;pass<nodes.length;pass++)for(const node of nodes){const above=parentIds(node.id).filter(id=>levels.has(id));if(above.length)levels.set(node.id,Math.max(...above.map(id=>levels.get(id)+1)));}
  const ranks=new Map();for(const node of nodes){const level=levels.get(node.id) || 0;if(!ranks.has(level))ranks.set(level,[]);ranks.get(level).push(node);}
  const draft=new Map(),rows=[];
  for(const level of [...ranks.keys()].sort((a,b)=>a-b)){
    const row=ranks.get(level).map((node,index)=>{const placed=parentIds(node.id).map(id=>draft.get(id)).filter(value=>value!==undefined);return {node,index,key:placed.length?placed.reduce((sum,value)=>sum+value,0)/placed.length:index*(NODE_MIN_W+COL_GAP)};});
    row.sort((a,b)=>a.key-b.key || a.index-b.index);let cursor=0;
    for(const entry of row){const width=metrics.get(entry.node.id).width;draft.set(entry.node.id,cursor+width/2);cursor+=width+COL_GAP;}
    rows.push(row.map(entry=>entry.node));
  }
  const widths=rows.map(row=>row.reduce((sum,node)=>sum+metrics.get(node.id).width,0)+COL_GAP*Math.max(0,row.length-1)),widest=Math.max(NODE_MIN_W,...widths),positions=new Map();let y=GRAPH_PAD;
  rows.forEach((row,index)=>{let x=GRAPH_PAD+(widest-widths[index])/2,tallest=0;
    for(const node of row){const metric=metrics.get(node.id);positions.set(node.id,{x:Math.round(x),y:Math.round(y),w:metric.width,h:metric.height});x+=metric.width+COL_GAP;tallest=Math.max(tallest,metric.height);}
    y+=tallest+ROW_GAP;
  });
  return {positions,metrics};
}
function edgePath(from,to) {
  const a={x:from.x+from.w/2,y:from.y+from.h/2},b={x:to.x+to.w/2,y:to.y+to.h/2},below=to.y>=from.y+from.h-8,above=from.y>=to.y+to.h-8;
  if(below || above){const down=below,start={x:a.x,y:down?from.y+from.h:from.y},end={x:b.x,y:down?to.y-4:to.y+to.h+4},bend=Math.max(26,Math.abs(end.y-start.y)*.45);
    return 'M '+start.x+' '+start.y+' C '+start.x+' '+(start.y+(down?bend:-bend))+', '+end.x+' '+(end.y-(down?bend:-bend))+', '+end.x+' '+end.y;
  }
  const right=b.x>=a.x,start={x:right?from.x+from.w:from.x,y:a.y},end={x:right?to.x-4:to.x+to.w+4,y:b.y},bend=Math.max(26,Math.abs(end.x-start.x)*.45);
  return 'M '+start.x+' '+start.y+' C '+(start.x+(right?bend:-bend))+' '+start.y+', '+(end.x-(right?bend:-bend))+' '+end.y+', '+end.x+' '+end.y;
}
function refreshEdges(id=null) { for(const edge of graphEdges){if(id&&edge.from!==id&&edge.to!==id)continue;const a=graphNodes.get(edge.from),b=graphNodes.get(edge.to);if(a&&b)edge.el.setAttribute('d',edgePath(a.box,b.box));} }
function highlightEdges(id,on) { for(const edge of graphEdges)if(edge.from===id || edge.to===id)edge.el.classList.toggle('linked',on); }
function readPositions() { try {const out=JSON.parse(stored(POS_KEY,'{}'));return out&&typeof out==='object'?out:{};}catch(_){return {};} }
function writePositions() { const positions=readPositions();for(const [id,entry] of graphNodes)positions[id]={x:entry.box.x,y:entry.box.y};storeValue(POS_KEY,JSON.stringify(positions)); }
function fittedSize() {
  const svg=$('suiteGraph'),aspect=(svg.clientWidth || 800)/(svg.clientHeight || 540);let width=graphBounds.width,height=graphBounds.height;
  if(width/height<aspect)width=height*aspect;else height=width/aspect;return {width,height};
}
function graphViewport() { const size=fittedSize();return {width:size.width/graphScale,height:size.height/graphScale}; }
function applyGraphView() {
  const size=graphViewport(),x=graphBounds.x+graphBounds.width/2-graphOffset.x,y=graphBounds.y+graphBounds.height/2-graphOffset.y;
  $('suiteGraph').setAttribute('viewBox',(x-size.width/2)+' '+(y-size.height/2)+' '+size.width+' '+size.height);
}
function updateGraphBounds(keepView=false) {
  if(!graphNodes.size)return;
  const old=fittedSize(),oldX=graphBounds.x+graphBounds.width/2,oldY=graphBounds.y+graphBounds.height/2;
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  for(const {box} of graphNodes.values()){minX=Math.min(minX,box.x);minY=Math.min(minY,box.y);maxX=Math.max(maxX,box.x+box.w);maxY=Math.max(maxY,box.y+box.h);}
  graphBounds={x:minX-GRAPH_PAD,y:minY-GRAPH_PAD,width:maxX-minX+GRAPH_PAD*2,height:maxY-minY+GRAPH_PAD*2};
  if(keepView){graphScale*=fittedSize().width/old.width;graphOffset.x+=graphBounds.x+graphBounds.width/2-oldX;graphOffset.y+=graphBounds.y+graphBounds.height/2-oldY;}
}
function graphDefs() {
  const defs=svgEl('defs'),fill=svgEl('linearGradient',{id:'nodeFill',x1:'0',y1:'0',x2:'0',y2:'1'});
  fill.append(svgEl('stop',{offset:'0','stop-color':'#2f2f34'}),svgEl('stop',{offset:'1','stop-color':'#232327'}));defs.append(fill);
  for(const [id,color] of [['arrow','#5c5c63'],['arrowHot','#cfcfd8']]){const marker=svgEl('marker',{id,viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'6',markerHeight:'6',orient:'auto-start-reverse'});marker.append(svgEl('path',{d:'M 0 1 L 10 5 L 0 9 z',fill:color}));defs.append(marker);}
  return defs;
}
function buildSuiteNode(node,box,metric) {
  const group=svgEl('g',{class:'suite-node','data-id':node.id,tabindex:'0',role:'button','aria-label':node.title+', '+suiteStatus(node),transform:'translate('+box.x+' '+box.y+')'});
  group.style.setProperty('--node-color',suiteColor(suiteStatus(node)));
  const title=svgEl('title');title.textContent=node.id+' · '+node.title;group.append(title);
  group.append(svgEl('rect',{class:'node-card',width:box.w,height:box.h,rx:'14'}));
  group.append(svgEl('path',{class:'node-rail',d:'M 14 0.5 A 13.5 13.5 0 0 0 0.5 14 L 0.5 '+(box.h-14)+' A 13.5 13.5 0 0 0 14 '+(box.h-.5)}));
  const tag=svgEl('text',{class:'node-tag',x:NODE_PAD,y:23});tag.textContent=metric.tag;group.append(tag);
  group.append(svgEl('rect',{class:'node-pill',x:box.w-NODE_PAD-metric.pill,y:11,width:metric.pill,height:17,rx:8.5}));
  const status=svgEl('text',{class:'node-status',x:box.w-NODE_PAD-metric.pill/2,y:23,'text-anchor':'middle'});status.textContent=metric.status;group.append(status);
  metric.lines.forEach((line,index)=>{const text=svgEl('text',{class:'node-title',x:NODE_PAD,y:HEAD_H+12+index*TITLE_LH});text.textContent=line;group.append(text);});
  group.addEventListener('keydown',event=>{if(event.key==='Enter' || event.key===' '){event.preventDefault();selectSuite(node.id);}});
  group.addEventListener('pointerenter',()=>highlightEdges(node.id,true));group.addEventListener('pointerleave',()=>highlightEdges(node.id,false));
  let drag=null;
  group.addEventListener('pointerdown',event=>{
    if(event.button)return;event.stopPropagation();event.preventDefault();drag={x:event.clientX,y:event.clientY,origin:{x:box.x,y:box.y},moved:false};
    group.classList.add('dragging');group.parentNode.append(group);group.setPointerCapture(event.pointerId);
  });
  group.addEventListener('pointermove',event=>{
    if(!drag)return;const svg=$('suiteGraph'),viewport=graphViewport(),dx=event.clientX-drag.x,dy=event.clientY-drag.y;
    if(Math.abs(dx)>3 || Math.abs(dy)>3)drag.moved=true;
    box.x=Math.round(drag.origin.x+dx*viewport.width/(svg.clientWidth || 1));box.y=Math.round(drag.origin.y+dy*viewport.height/(svg.clientHeight || 1));
    group.setAttribute('transform','translate('+box.x+' '+box.y+')');refreshEdges(node.id);
  });
  const release=event=>{
    if(!drag)return;const moved=drag.moved;drag=null;group.classList.remove('dragging');
    if(group.hasPointerCapture(event.pointerId))group.releasePointerCapture(event.pointerId);
    if(moved){writePositions();updateGraphBounds(true);applyGraphView();}else if(event.type==='pointerup')selectSuite(node.id);
  };
  group.addEventListener('pointerup',release);group.addEventListener('pointercancel',release);return group;
}
function renderSuiteGraph(preserveView=false) {
  graphReady=true;const svg=$('suiteGraph');svg.replaceChildren();
  const all=[...suiteById.values()],nodes=hideSealed?all.filter(node=>suiteGroup(suiteStatus(node))!=='sealed'):all,hidden=all.length-nodes.length;
  const keepView=preserveView&&nodes.length===graphNodes.size&&nodes.every(node=>graphNodes.has(node.id));
  $('sealedToggle').textContent=hideSealed?'Show sealed':'Hide sealed';$('sealedToggle').setAttribute('aria-pressed',String(hideSealed));
  $('suiteMeta').textContent=nodes.length+' of '+all.length+' suites shown'+(hidden?' · '+hidden+' sealed hidden':'');
  graphNodes=new Map();graphEdges=[];
  if(!nodes.length){graphBounds={x:0,y:0,width:800,height:500};graphOffset={x:0,y:0};graphScale=1;applyGraphView();
    const empty=svgEl('text',{x:400,y:250,'text-anchor':'middle',fill:'#9d9d9d'});empty.textContent=all.length?'Every suite is hidden':'No suites registered.';svg.append(empty);return;
  }
  const visible=new Set(nodes.map(node=>node.id)),parents=effectiveParents(nodes,visible),layout=suitePositions(nodes,parents),positions=readPositions();
  for(const [id,box] of layout.positions){const saved=positions[id];if(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y)){box.x=saved.x;box.y=saved.y;}}
  svg.append(graphDefs());const scene=svgEl('g',{id:'suiteScene'}),edgeLayer=svgEl('g',{class:'edge-layer'}),nodeLayer=svgEl('g',{class:'node-layer'});scene.append(edgeLayer,nodeLayer);
  for(const node of nodes){const box=layout.positions.get(node.id),group=buildSuiteNode(node,box,layout.metrics.get(node.id));nodeLayer.append(group);graphNodes.set(node.id,{node,box,group});}
  for(const node of nodes)for(const link of parents.get(node.id) || []){
    if(!graphNodes.has(link.id))continue;
    const el=svgEl('path',{class:'suite-edge'+(link.indirect?' indirect':'')});if(link.indirect)el.setAttribute('aria-label','Scientific lineage through a hidden suite');
    edgeLayer.append(el);graphEdges.push({from:link.id,to:node.id,el});
  }
  svg.append(scene);refreshEdges();updateGraphBounds(keepView);
  for(const [id,{group}] of graphNodes)group.classList.toggle('selected',id===selectedSuiteId);
  if(keepView)applyGraphView();else resetGraph();
}
function selectSuite(id,{reloadCard=false}={}) {
  const node=suiteById.get(id);if(!node)return;selectedSuiteId=id;
  for(const [key,{group}] of graphNodes)group.classList.toggle('selected',key===id);
  const status=suiteStatus(node),color=suiteColor(status);$('suiteModalTitleWrap').style.setProperty('--node-color',color);
  $('suiteModalStatus').textContent=status;$('suiteModalTitle').textContent=node.title;
  const options=state.suite_statuses || ['proposed','ready','queued','training','evaluating','active','running','reopened','sealed','shelved','approved'];
  $('suiteStatusSelect').replaceChildren(...[...new Set([...options,status])].map(value=>{const option=element('option',value.replaceAll('_',' '));option.value=value;return option;}));
  $('suiteStatusSelect').value=status;$('suiteSealButton').hidden=node.status==='sealed' || status==='sealed';
  $('suiteModalSummary').replaceChildren(element('p',node.summary || 'No summary recorded yet.'));
  const result=node.result || (node.results_ready?'Results ready for review.':'');
  if(result){const latest=element('div',undefined,'suite-result');latest.style.setProperty('--node-color',color);latest.append(element('div','Latest result','label'),element('div',String(result)));$('suiteModalSummary').append(latest);}
  architectureLinks($('suiteModalSummary'),'suite',node.id);
  const url=node.card_url || '/suite-card?id='+encodeURIComponent(node.id);
  const hasCard=node.card_available!==false&&Boolean(node.card_url || node.card || state.cards?.[node.id]!==undefined);
  $('suiteNoCard').textContent=node.card_error || 'This suite has no readable card.';
  $('suiteOpenTab').href=url;$('suiteOpenTab').hidden=!hasCard;$('suiteCardFrame').hidden=!hasCard;$('suiteNoCard').hidden=hasCard;
  if(hasCard){$('suiteCardFrame').title=node.title+' suite card';if(reloadCard||$('suiteCardFrame').getAttribute('src')!==url)$('suiteCardFrame').src=url;}
  if(!$('suiteDialog').open)$('suiteDialog').showModal();
}
async function setSuiteStatus(status) {
  const node=suiteById.get(selectedSuiteId);if(!node || status===suiteStatus(node))return;
  if(status==='sealed'&&!confirm('Seal '+node.id+'?'))return;
  const controls=[$('suiteStatusSelect'),$('suiteStatusSave'),$('suiteSealButton')];controls.forEach(control=>control.disabled=true);
  try { await request('/api/suite-status',{id:node.id,status});await refresh();selectSuite(node.id);message('Suite status saved.'); }
  finally { controls.forEach(control=>control.disabled=false); }
}
function zoomGraph(factor) { graphScale=Math.max(.4,Math.min(2.5,graphScale*factor));applyGraphView(); }
function resetGraph() { graphScale=1;graphOffset={x:0,y:0};const svg=$('suiteGraph');if(svg.clientWidth)graphScale=Math.min(1,fittedSize().width/svg.clientWidth);applyGraphView(); }
let pan=null;
$('suiteGraph').addEventListener('wheel',event=>{
  event.preventDefault();let delta=event.deltaY;if(event.deltaMode===1)delta*=16;else if(event.deltaMode===2)delta*=400;if(event.ctrlKey)delta*=3;
  zoomGraph(Math.exp(-Math.max(-140,Math.min(140,delta))*.0008));
},{passive:false});
$('suiteGraph').addEventListener('pointerdown',event=>{
  if(event.button || event.target.closest('.suite-node'))return;
  pan={x:event.clientX,y:event.clientY,offset:{...graphOffset}};$('suiteGraph').classList.add('dragging');$('suiteGraph').setPointerCapture(event.pointerId);
});
$('suiteGraph').addEventListener('pointermove',event=>{
  if(!pan)return;const svg=$('suiteGraph'),viewport=graphViewport();
  graphOffset.x=pan.offset.x+(event.clientX-pan.x)*viewport.width/(svg.clientWidth || 1);graphOffset.y=pan.offset.y+(event.clientY-pan.y)*viewport.height/(svg.clientHeight || 1);applyGraphView();
});
for(const name of ['pointerup','pointercancel'])$('suiteGraph').addEventListener(name,event=>{
  pan=null;$('suiteGraph').classList.remove('dragging');if($('suiteGraph').hasPointerCapture(event.pointerId))$('suiteGraph').releasePointerCapture(event.pointerId);
});
function openArchitecture(id) { selectedArchitecture=id;renderArchitectures();return setView('arch',true); }
function renderArchitectures() {
  const host=$('archView'),existingFrame=host.querySelector('iframe'),architectures=state.architectures || [];host.replaceChildren();
  if(!architectures.length){host.append(element('div','No architectures saved yet. Ask your assistant to capture a model and attach it to a suite or review task.','empty'));return;}
  if(!architectures.some(item=>item.id===selectedArchitecture))selectedArchitecture=(architectures.find(item=>item.available) || architectures[0]).id;
  const layout=element('div',undefined,'architecture-workspace'),library=element('aside',undefined,'architecture-library');
  library.append(element('h2','Saved architectures'),element('p','Select a model to inspect its hierarchy and observed calls.'));
  for(const architecture of architectures){
    const choice=button(architecture.title,()=>openArchitecture(architecture.id),'architecture-choice'+(architecture.id===selectedArchitecture?' selected':''));
    choice.setAttribute('aria-pressed',String(architecture.id===selectedArchitecture));
    choice.append(element('small',[architecture.suite,architecture.task].filter(Boolean).join(' · ') || architecture.id),element('span',architecture.available?'Saved graph':'Unavailable','tag'+(architecture.available?'':' error')));library.append(choice);
  }
  const architecture=architectures.find(item=>item.id===selectedArchitecture),viewer=element('article',undefined,'architecture-viewer'),heading=element('div',undefined,'architecture-heading'),title=element('div');
  title.append(element('h2',architecture.title));
  const associations=[architecture.suite&&'Suite: '+architecture.suite,architecture.task&&'Review: '+architecture.task].filter(Boolean);
  if(associations.length)title.append(element('p',associations.join(' · ')));heading.append(title);
  if(architecture.available){
    const url='/architecture?id='+encodeURIComponent(architecture.id),link=element('a','Open full viewer','viewer-link');link.href=url;link.target='_blank';link.rel='noopener';heading.append(link);viewer.append(heading);
    let frame=existingFrame;if(!frame || frame.dataset.architectureId!==architecture.id){frame=element('iframe');frame.src=url;frame.dataset.architectureId=architecture.id;frame.loading='lazy';}
    frame.title='Architecture: '+architecture.title;viewer.append(frame);
  }else viewer.append(heading,element('div',architecture.error || 'This saved graph is unavailable. Ask your assistant to capture and register it again.','empty error'));
  layout.append(library,viewer);host.append(layout);
}
async function refresh({reloadCard=false}={}) {
  state=await request('/api/state');renderQueue();
  const suites=Array.isArray(state.suites)?state.suites:state.suites?.nodes || [];
  suiteById=new Map(suites.map(node=>[node.id,node]));graphReady=false;
  if(currentView==='suites')renderSuiteGraph(true);
  if($('suiteDialog').open&&suiteById.has(selectedSuiteId))selectSuite(selectedSuiteId,{reloadCard});
  renderArchitectures();if(currentView==='archive')await renderArchive();
}
for(const tab of document.querySelectorAll('[data-view]'))tab.addEventListener('click',guarded(()=>setView(tab.dataset.view,true)));
document.querySelector('nav').addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=[...document.querySelectorAll('[data-view]')],index=tabs.indexOf(document.activeElement);if(index<0)return;
  event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  tabs[next].focus();setView(tabs[next].dataset.view,true).catch(error=>message(error.message,true));
});
$('archiveLink').addEventListener('click',guarded(event=>{event.preventDefault();return setView(currentView==='archive'?'queue':'archive',true);}));
$('newTask').addEventListener('click',()=>openTaskForm());
$('resolveNext').addEventListener('click',()=>openCompletion());
$('deckToggle').addEventListener('click',()=>{unpacked=!unpacked;storeValue(DECK_KEY,unpacked?'1':'0');applyDeck();});
$('taskForm').addEventListener('submit',guarded(saveTask));
$('completionForm').addEventListener('submit',guarded(completeTask));
for(const node of document.querySelectorAll('[data-close]'))node.addEventListener('click',()=>$(node.dataset.close).close());
for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',event=>{if(event.target===dialog&&((event.clientX<dialog.getBoundingClientRect().left)||(event.clientX>dialog.getBoundingClientRect().right)||(event.clientY<dialog.getBoundingClientRect().top)||(event.clientY>dialog.getBoundingClientRect().bottom)))dialog.close();});
$('taskDialog').addEventListener('close',()=>editingId=null);$('completionDialog').addEventListener('close',()=>completion=null);
$('sealedToggle').addEventListener('click',()=>{hideSealed=!hideSealed;storeValue(SEALED_KEY,hideSealed?'1':'0');renderSuiteGraph();});
$('graphZoomIn').addEventListener('click',()=>zoomGraph(1.2));$('graphZoomOut').addEventListener('click',()=>zoomGraph(.8));$('graphFit').addEventListener('click',resetGraph);
$('graphReset').addEventListener('click',()=>{try{localStorage.removeItem(POS_KEY);}catch(_){}renderSuiteGraph();});
$('suiteStatusSave').addEventListener('click',guarded(()=>setSuiteStatus($('suiteStatusSelect').value)));
$('suiteSealButton').addEventListener('click',guarded(()=>setSuiteStatus('sealed')));
$('sync').addEventListener('click',guarded(async()=>{await request('/api/sync',{});await refresh({reloadCard:true});message('Validated results refreshed.');}));
window.addEventListener('resize',()=>{if(graphReady)applyGraphView();});
window.addEventListener('popstate',()=>setView(location.pathname==='/archive'?'archive':new URLSearchParams(location.search).get('view') || 'queue').catch(error=>message(error.message,true)));
const initialView=location.pathname==='/archive'?'archive':new URLSearchParams(location.search).get('view') || stored(VIEW_KEY,'queue');
setView(initialView).then(refresh).catch(error=>message(error.message,true));
