'use strict';
let graph, timer=null, step=0; const nodes=new Map(), elements=new Map();
function create(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function select(id){const node=nodes.get(id),events=graph.events.filter(e=>e.node===id);document.querySelector('#detail').textContent=JSON.stringify({component:node,observed_calls:events},null,2);}
function branch(node){const detail=create('details');detail.open=!node.parent;const summary=create('summary');summary.append(create('b',node.label||node.id),create('small',node.type||node.evidence));summary.addEventListener('click',()=>select(node.id));detail.append(summary);elements.set(node.id,detail);for(const child of graph.nodes.filter(n=>n.parent===node.id))detail.append(branch(child));return detail;}
function expand(value){for(const item of elements.values())item.open=value;for(const root of graph.nodes.filter(n=>!n.parent))elements.get(root.id).open=true;}
function stop(){clearInterval(timer);timer=null;document.querySelector('#play').textContent='Play observed calls';}
document.querySelector('#expand').addEventListener('click',()=>expand(true));document.querySelector('#collapse').addEventListener('click',()=>expand(false));
document.querySelector('#play').addEventListener('click',()=>{if(timer){stop();return;}if(!graph.events.length)return;step=0;document.querySelector('#play').textContent='Stop playback';timer=setInterval(()=>{for(const e of elements.values())e.classList.remove('hot');if(step>=graph.events.length){stop();return;}const event=graph.events[step++];const item=elements.get(event.node);let parent=item.parentElement.closest('details');while(parent){parent.open=true;parent=parent.parentElement.closest('details');}item.classList.add('hot');select(event.node);document.querySelector('#mode').textContent=`Observed call ${step}/${graph.events.length}: ${event.node} (illustrative playback, not measured timing)`;},800);});
async function loadGraph() {
  const integrated=['/architecture','/architecture/'].includes(location.pathname);
  const id=new URLSearchParams(location.search).get('id');
  if (integrated && !id) throw Error('Choose a saved architecture from the NAIA dashboard.');
  const response=await fetch(integrated?'/api/architecture?id='+encodeURIComponent(id):'/graph.json');
  const data=await response.json();
  if (!response.ok) throw Error(data.error||'Unable to load the saved architecture.');
  graph={...data,events:data.events||[],edges:data.edges||[]};
  for(const node of graph.nodes) nodes.set(node.id,node);
  for(const root of graph.nodes.filter(n=>!n.parent)) document.querySelector('#tree').append(branch(root));
  document.querySelector('#mode').textContent=(graph.capture_mode||'declared graph')+' · expand blocks to inspect hierarchy';
  for(const warning of graph.warnings||[]) document.querySelector('#warnings').append(create('li',warning));
  for(const edge of graph.edges) document.querySelector('#edges').append(create('div',`${edge.source} → ${edge.target} [${edge.evidence}]`));
  if(!graph.edges.length) document.querySelector('#edges').textContent='No tensor-dependency edges established. Module call order is not a data-flow graph.';
  document.querySelector('#expand').disabled=false;
  document.querySelector('#collapse').disabled=false;
  document.querySelector('#play').disabled=!graph.events.length;
}
loadGraph().catch(e=>{document.querySelector('#mode').textContent=e.message;});
