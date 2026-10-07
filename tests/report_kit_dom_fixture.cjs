'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture(initialHash = '') {
  const events = new Map();
  let doc;
  function matchesSimple(node, selector) {
    if (!node || node.tagName === '#text') return false;
    const attributes = [...selector.matchAll(/\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]/g)];
    selector = selector.replace(/\[[^\]]+\]/g, '');
    for (const [, key, double, single, bare] of attributes) {
      const actual = node.getAttribute(key), wanted = double ?? single ?? bare;
      if (actual === null || (wanted !== undefined && actual !== wanted.trim())) return false;
    }
    const id = selector.match(/#([\w-]+)/);
    if (id && node.id !== id[1]) return false;
    for (const [, name] of selector.matchAll(/\.([\w-]+)/g)) if (!node.classList.contains(name)) return false;
    const type = selector.match(/^[\w*-]+/);
    return !type || type[0] === '*' || node.tagName.toLowerCase() === type[0].toLowerCase();
  }
  function matches(node, selector) {
    return selector.split(',').some(part => {
      const steps = part.trim().replace(/:scope\s*>\s*/g, '').split(/\s+(?![^\[]*\])/);
      let current = node;
      if (!matchesSimple(current, steps.pop())) return false;
      while (steps.length) {
        const wanted = steps.pop();
        current = current.parentNode;
        while (current && !matchesSimple(current, wanted)) current = current.parentNode;
        if (!current) return false;
      }
      return true;
    });
  }
  class Element {
    constructor(tag) {
      this.tagName = tag;
      this.nodeType = tag === '#text' ? 3 : 1;
      this.parentNode = null;
      this.childNodes = [];
      this.attrs = new Map();
      this.handlers = new Map();
      this._text = '';
      this.style = {setProperty(key, value) { this[key] = String(value); }};
      this.dataset = new Proxy({}, {set: (target, key, value) => {
        target[key] = String(value);
        this.attrs.set('data-' + key.replace(/[A-Z]/g, ch => '-' + ch.toLowerCase()), String(value));
        return true;
      }});
      this.classList = {
        contains: name => this.className.split(/\s+/).includes(name),
        add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(' '); },
        remove: (...names) => { this.className = this.className.split(/\s+/).filter(n => !names.includes(n)).join(' '); },
        toggle: (name, force) => {
          const enabled = force === undefined ? !this.classList.contains(name) : force;
          if (enabled) this.classList.add(name); else this.classList.remove(name);
          return enabled;
        }
      };
      this.hidden = false;
      this.ownerDocument = doc;
    }
    get children() { return this.childNodes.filter(n => n.nodeType === 1); }
    get firstChild() { return this.childNodes[0] || null; }
    get parentElement() { return this.parentNode; }
    get id() { return this.attrs.get('id') || ''; }
    set id(value) { this.attrs.set('id', String(value)); }
    get className() { return this.attrs.get('class') || ''; }
    set className(value) { this.attrs.set('class', String(value)); }
    get textContent() { return this._text + this.childNodes.map(n => n.textContent).join(''); }
    set textContent(value) { this._text = String(value ?? ''); this.childNodes = []; }
    get innerText() { return this.textContent; }
    get innerHTML() { return this.textContent; }
    set innerHTML(value) {
      if (value) throw Error('Mini DOM does not parse markup; create nodes in report kit');
      this.replaceChildren();
    }
    setAttribute(name, value) {
      this.attrs.set(name, String(value));
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())] = value;
    }
    getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
    hasAttribute(name) { return this.attrs.has(name); }
    removeAttribute(name) { this.attrs.delete(name); }
    append(...nodes) { for (const node of nodes) this.appendChild(node); }
    appendChild(node) {
      if (typeof node === 'string') { const text = new Element('#text'); text.textContent = node; node = text; }
      if (node.tagName === '#fragment') { for (const child of [...node.childNodes]) this.appendChild(child); return node; }
      node.remove(); node.parentNode = this; this.childNodes.push(node); return node;
    }
    prepend(...nodes) { for (const node of [...nodes].reverse()) this.insertBefore(node, this.firstChild); }
    insertBefore(node, reference) {
      if (!reference) return this.appendChild(node);
      node.remove(); node.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(reference), 0, node); return node;
    }
    replaceChildren(...nodes) {
      for (const child of this.childNodes) child.parentNode = null;
      this.childNodes = []; this._text = ''; this.append(...nodes);
    }
    remove() { if (this.parentNode) { const nodes=this.parentNode.childNodes; nodes.splice(nodes.indexOf(this),1); this.parentNode=null; } }
    querySelectorAll(selector) {
      const result = [];
      const walk = node => { for (const child of node.children) { if(matches(child, selector)) result.push(child); walk(child); } };
      walk(this); return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    matches(selector) { return matches(this, selector); }
    closest(selector) { let node=this; while(node) {if(matches(node,selector))return node;node=node.parentNode;} return null; }
    contains(node) { while(node){if(node===this)return true;node=node.parentNode;}return false; }
    addEventListener(type, callback) { const callbacks=this.handlers.get(type)||[];callbacks.push(callback);this.handlers.set(type,callbacks); }
    removeEventListener(type, callback) {this.handlers.set(type,(this.handlers.get(type)||[]).filter(fn=>fn!==callback));}
    dispatchEvent(event) {
      event.target ||= this;
      event.currentTarget = this;
      for (const callback of this.handlers.get(event.type)||[]) callback(event);
      if(event.bubbles && this.parentNode)this.parentNode.dispatchEvent(event);
      return true;
    }
    click() {this.dispatchEvent({type:'click',bubbles:true,target:this,preventDefault(){},stopPropagation(){}});}
    focus() {doc.activeElement=this;this.dispatchEvent({type:'focus',target:this});}
    blur() {this.dispatchEvent({type:'blur',target:this});}
    getBoundingClientRect() {return {x:0,y:0,left:0,top:0,right:640,bottom:320,width:640,height:320};}
    getBBox() {return {x:0,y:0,width:this.textContent.length*7,height:12};}
    get clientWidth() {return 640;}
    get offsetWidth() {return 180;}
    get offsetHeight() {return 60;}
    scrollIntoView() {}
  }
  doc = {
    documentElement: new Element('html'), body: new Element('body'), head: new Element('head'), readyState:'complete',
    createElement: tag => new Element(tag), createElementNS: (_,tag) => new Element(tag),
    createTextNode: text => {const node=new Element('#text');node.textContent=text;return node;},
    createDocumentFragment: () => new Element('#fragment'),
    getElementById: id => doc.documentElement.querySelector('#'+id),
    querySelector: selector => matchesSimple(doc.documentElement,selector) ? doc.documentElement : doc.documentElement.querySelector(selector),
    querySelectorAll: selector => doc.documentElement.querySelectorAll(selector),
    addEventListener(type, fn) {const callbacks=events.get(type)||[];callbacks.push(fn);events.set(type,callbacks);}
  };
  doc.documentElement.append(doc.head,doc.body);
  const location = new URL('http://localhost/report.html'+initialHash);
  const storage = new Map();
  const context = {
    document:doc, location, navigator:{language:'en-US'}, console, URL, URLSearchParams,
    localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,String(v))},
    history:{replaceState(_state,_title,url){const next=new URL(url,location);location.href=next.href;}},
    setTimeout, clearTimeout, requestAnimationFrame: fn=>{fn();return 1;}, cancelAnimationFrame(){},
    matchMedia:()=>({matches:false,addEventListener(){}}),
    getComputedStyle:()=>({color:'rgb(200,200,200)',getPropertyValue:()=>''}),
    ResizeObserver:class{observe(){}disconnect(){}},
    Event:class{constructor(type,options={}){this.type=type;Object.assign(this,options);}preventDefault(){}stopPropagation(){}},
    addEventListener(type,fn){const callbacks=events.get(type)||[];callbacks.push(fn);events.set(type,callbacks);},
    removeEventListener(type,fn){events.set(type,(events.get(type)||[]).filter(f=>f!==fn));}
  };
  context.window=context;context.self=context;context.parent=context;
  context.innerWidth=900;context.innerHeight=700;
  const sandbox=vm.createContext(context);
  vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),sandbox,{filename:'report_kit.js'});
  function host(id='chart'){const node=doc.createElement('div');node.id=id;doc.body.append(node);return node;}
  function api(data,extra={}){return sandbox.NAIAReport.init({data,...extra});}
  function plain(value){return JSON.parse(JSON.stringify(value));}
  function error(node){return node.querySelector('.nrk-error')?.textContent || '';}
  return {sandbox,doc,location,host,api,plain,error,events};
}

const cases = {
  responsive_width_stacks_facets_and_preserves_focus_and_numbers() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',target:'Long near scientific label',v:2},{x:'A',target:'Long far scientific label',v:20}]});
    Object.defineProperty(host,'clientWidth',{value:300,configurable:true});
    const handle=R.figure('#chart',{type:'bars',table:'rows',x:'x',facet:'target',value:'v'});
    assert.equal(f.error(host),'');
    assert.equal(host.querySelector('.nrk-chart').getAttribute('viewBox').split(' ')[2],'300');
    const panels=host.querySelectorAll('.nrk-panel');
    assert.equal(panels[0].getAttribute('transform'),'translate(0,0)');
    assert.equal(panels[1].getAttribute('transform'),'translate(0,335)');
    host.querySelector('.nrk-numbers').open=true;
    host.querySelector('.nrk-mark').focus();
    Object.defineProperty(host,'clientWidth',{value:900,configurable:true});
    handle.render();
    assert.equal(host.querySelector('.nrk-chart').getAttribute('viewBox').split(' ')[2],'900');
    assert.equal(host.querySelector('.nrk-numbers').open,true);
    assert.ok(f.doc.activeElement.classList.contains('nrk-mark'));
    assert.ok(host.contains(f.doc.activeElement));
  },
  dynamic_scatter_axes_and_zone_leave_spec_unchanged() {
    const f=fixture(),host=f.host(),R=f.api({rows:[
      {crit:'moderate',x:12,v:12},{crit:'strict',x:12,v:12}]},
      {controls:{crit:{options:{moderate:'Moderate',strict:'Strict'},default:'moderate'}}});
    const axis=state=>({min:0,max:state.crit==='moderate'?20:10});
    const zone=state=>{const tau=state.crit==='moderate'?20:10;return{xMin:0,xMax:tau,yMin:0,yMax:tau,label:'Tolerance '+tau};};
    const spec=Object.freeze({type:'scatter',table:'rows',x:'x',value:'v',xAxis:axis,y:axis,targetZone:zone});
    R.figure('#chart',spec);
    assert.equal(f.error(host),'');
    assert.equal(Number(host.querySelector('.nrk-panel').dataset.nrkXmax),20);
    assert.ok(host.textContent.includes('Tolerance 20'));
    const count=Number(host.dataset.nrkRender);
    R.setState({crit:'strict'});
    assert.equal(f.error(host),'');
    assert.equal(Number(host.querySelector('.nrk-panel').dataset.nrkXmax),10);
    assert.equal(Number(host.querySelector('.nrk-panel').dataset.nrkYmax),10);
    assert.ok(host.textContent.includes('Tolerance 10'));
    assert.ok(host.querySelector('[data-nrk-clamped="true"]'));
    assert.ok(Number(host.dataset.nrkRender)>count);
    assert.equal(spec.xAxis,axis);assert.equal(spec.y,axis);assert.equal(spec.targetZone,zone);
    assert.ok(Object.isFrozen(spec));
  },

  scatter_repeated_observations_and_explicit_identity() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:.4,v:.4,episode:1},{x:.4,v:.4,episode:2}]});
    R.figure('#chart',{type:'scatter',table:'rows',x:'x',value:'v',tooltip:['episode']});
    assert.equal(f.error(host),'');
    assert.equal(host.querySelectorAll('.nrk-mark').length,2);
    const f2=fixture(),host2=f2.host(),R2=f2.api({rows:[{x:.4,v:.4,episode:1},{x:.5,v:.5,episode:1}]});
    R2.figure('#chart',{type:'scatter',table:'rows',x:'x',value:'v',point:'episode'});
    assert.match(f2.error(host2),/duplicate|identity|coordinate|point/i);
  },
  nonfinite_tooltip_and_table() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:1,n:Infinity}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v',tooltip:['n']});
    assert.match(f.error(host),/finite|invalid|number/i);
    const f2=fixture(),host2=f2.host(),R2=f2.api({rows:[{model:'A',score:Infinity}]});
    R2.figure('#chart',{type:'table',table:'rows'});
    assert.match(f2.error(host2),/finite|invalid|number/i);
  },
  irrelevant_controls_do_not_rerender() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{dur:'short',x:'A',v:1},{dur:'long',x:'A',v:2}]},
      {controls:{dur:{options:{short:'Short',long:'Long'},default:'short'},
                 crit:{options:{moderate:'Moderate',strict:'Strict'},default:'moderate'}}});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v'});
    const count=Number(host.dataset.nrkRender);
    R.setState({crit:'strict'});
    assert.equal(Number(host.dataset.nrkRender),count);
    R.setState({dur:'long'});
    assert.ok(Number(host.dataset.nrkRender)>count);
  },
  stable_declared_series_when_other_series_absent() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',train:'single',v:1},{x:'A',train:'background',v:2}]},
      {series:{train:{single:'One background',background:'20 backgrounds'}}});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',series:'train',value:'v'});
    const background=host.querySelector('[data-nrk-series="background"] path').getAttribute('fill');
    const f2=fixture(),host2=f2.host(),R2=f2.api({rows:[{x:'A',train:'background',v:2}]},
      {series:{train:{single:'One background',background:'20 backgrounds'}}});
    R2.figure('#chart',{type:'bars',table:'rows',x:'x',series:'train',value:'v'});
    assert.equal(host2.querySelector('[data-nrk-series="background"] path').getAttribute('fill'),background);
  },
  change_callbacks_unsubscribe() {
    const f=fixture(),R=f.api({rows:[]},{controls:{dur:{options:{short:'Short',long:'Long'},default:'short'}}});
    let calls=0;
    const remove=R.onChange((state,changed)=>{calls++;assert.ok(Object.isFrozen(state));assert.ok(changed.includes('dur'));});
    R.setState({dur:'long'});assert.equal(calls,1);
    remove();R.setState({dur:'short'});assert.equal(calls,1);
  },

  explicit_value() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',score:4}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x'});
    assert.match(f.error(host),/value|numeric|field/i);
  },
  duplicates() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:1},{x:'A',v:2}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v'});
    assert.match(f.error(host),/duplicate|coordinate/i);
  },
  unresolved_columns() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:1,variant:'one'},{x:'B',v:2,variant:'two'}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v'});
    assert.match(f.error(host),/variant|unresolved|column|dimension/i);
  },
  tooltip_exemption() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:1,n:20},{x:'B',v:2,n:30}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v',tooltip:['n']});
    assert.equal(f.error(host),'');
    assert.equal(host.querySelectorAll('.nrk-mark').length,2);
  },
  null_is_missing() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:null},{x:'B',v:0}]});
    const handle=R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v'});
    assert.equal(f.error(host),'');
    assert.equal(host.querySelectorAll('[data-nrk-missing="true"]').length,1);
    const missing=host.querySelector('[data-nrk-missing="true"]');
    assert.notEqual(missing.getAttribute('data-nrk-value'),'0');
    assert.equal(host.querySelectorAll('[data-nrk-value="0"]').length,1);
    assert.ok(handle.rows().some(row=>row.v===null));
  },
  nonfinite() {
    for(const bad of [NaN,Infinity,-Infinity,'3']) {
      const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:bad}]});
      R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v'});
      assert.match(f.error(host),/finite|numeric|number|invalid/i);
    }
  },
  negative_bars_expand_axis() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:-4},{x:'B',v:12}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v',y:{min:0,max:10}});
    assert.equal(f.error(host),'');
    const panel=host.querySelector('.nrk-panel');
    assert.ok(Number(panel.dataset.nrkYmin)<=-4);
    assert.ok(Number(panel.dataset.nrkYmax)>=12);
    const negative=host.querySelector('[data-nrk-value="-4"] path');
    assert.ok(Number(negative.dataset.nrkBarBottom)>Number(negative.dataset.nrkBarTop));
    assert.equal(Number(negative.dataset.nrkBarTop),Number(negative.dataset.nrkBaseline));
  },
  line_axis_expands() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:-2},{x:'B',v:3}]});
    R.figure('#chart',{type:'lines',table:'rows',x:'x',value:'v',y:{min:0,max:1}});
    assert.equal(f.error(host),'');
    const panel=host.querySelector('.nrk-panel');
    assert.ok(Number(panel.dataset.nrkYmin)<=-2 && Number(panel.dataset.nrkYmax)>=3);
  },
  scatter_clamps_overflow() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:-2,v:2},{x:.5,v:.5}]});
    R.figure('#chart',{type:'scatter',table:'rows',x:'x',value:'v',xAxis:{min:0,max:1},y:{min:0,max:1}});
    assert.equal(f.error(host),'');
    const panel=host.querySelector('.nrk-panel');
    assert.equal(Number(panel.dataset.nrkXmin),0);assert.equal(Number(panel.dataset.nrkXmax),1);
    assert.equal(Number(panel.dataset.nrkYmin),0);assert.equal(Number(panel.dataset.nrkYmax),1);
    assert.match(host.textContent,/beyond|outside|clamp|edge|overflow/i);
  },
  facets_shared_scale() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',target:'near',v:2},{x:'A',target:'far',v:20}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',facet:'target',value:'v',order:{facet:['near','far']},y:{shared:true}});
    assert.equal(f.error(host),'');
    const panels=host.querySelectorAll('.nrk-panel');
    assert.equal(panels.length,2);
    assert.equal(panels[0].dataset.nrkYmin,panels[1].dataset.nrkYmin);
    assert.equal(panels[0].dataset.nrkYmax,panels[1].dataset.nrkYmax);
    assert.ok(Number(panels[0].dataset.nrkYmax)>=20);
  },
  rows_and_state_are_immutable() {
    const f=fixture(),R=f.api({rows:[{dur:'short',x:'A',v:1},{dur:'long',x:'A',v:2}]},
      {controls:{dur:{options:{short:'Short',long:'Long'},default:'short'}}});
    const rows=R.rows('rows');rows[0].v=99;
    assert.equal(R.rows('rows')[0].v,1);
    assert.ok(Object.isFrozen(R.state));
    const first=f.plain(R.state);
    R.setState({dur:'long'});
    assert.equal(R.rows('rows')[0].v,2);
    assert.equal(first.dur,'short');
    assert.throws(()=>R.setState({dur:'unknown'}),/control|invalid|option/i);
  },
  colors_stable_and_controls_rerender() {
    const f=fixture(),host=f.host(),R=f.api({rows:[
      {dur:'short',x:'A',train:'single',v:1},{dur:'short',x:'A',train:'background',v:2},
      {dur:'long',x:'A',train:'background',v:3}]},
      {controls:{dur:{options:{short:'Short',long:'Long'},default:'short'}},
       series:{train:{single:'One background',background:'20 backgrounds'}}});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',series:'train',value:'v'});
    assert.equal(f.error(host),'');
    const before=host.querySelector('[data-nrk-series="background"] path').getAttribute('fill');
    assert.ok(before);
    const count=Number(host.dataset.nrkRender);
    R.setState({dur:'long'});
    assert.equal(f.error(host),'');
    assert.ok(Number(host.dataset.nrkRender)>count);
    assert.equal(host.querySelector('[data-nrk-series="background"] path').getAttribute('fill'),before);
    assert.equal(host.querySelector('[data-nrk-series="background"]').dataset.nrkValue,'3');
  },
  show_numbers_and_focus_tooltip() {
    const f=fixture(),host=f.host(),R=f.api({rows:[{x:'A',v:7,n:20}]});
    R.figure('#chart',{type:'bars',table:'rows',x:'x',value:'v',tooltip:['n'],y:{unit:'%'}});
    assert.equal(f.error(host),'');
    const details=host.querySelector('.nrk-numbers');
    assert.ok(details && /Show(?: the)? numbers/i.test(details.textContent));
    assert.ok(details.querySelector('table').textContent.includes('7'));
    const mark=host.querySelector('.nrk-mark');
    assert.equal(mark.getAttribute('tabindex'),'0');
    mark.focus();
    const tip=f.doc.querySelector('.nrk-tooltip');
    assert.ok(tip && !tip.hidden && tip.textContent.includes('7'));
  },
  bookmark_and_theme() {
    const f=fixture('#dur=long&theme=light');
    const R=f.api({rows:[]},{controls:{dur:{options:{short:'Short',long:'Long'},default:'short'}}});
    assert.equal(R.state.dur,'long');assert.equal(R.state.theme,'light');
    R.setState({dur:'short',theme:'dark'});
    assert.ok(f.location.hash.includes('dur=short')&&f.location.hash.includes('theme=dark'));
    assert.throws(()=>R.setState({theme:'invalid'}),/theme|invalid/i);
    assert.equal(f.doc.documentElement.dataset.theme,'dark');
  }
};

const name=process.argv[3];
if(!cases[name])throw Error('Unknown fixture case '+name);
cases[name]();
console.log(JSON.stringify({case:name,passed:true}));
