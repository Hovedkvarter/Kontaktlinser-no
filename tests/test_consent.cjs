'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const script=fs.readFileSync('site_generator/consent.js','utf8');
function boot({saved,config={},url='https://kontaktlinser.no/',session}={}) {
  const elements={},handlers={},listeners={},cookies=[];
  const local=new Map(saved ? [['kl_consent_v2',JSON.stringify(saved)]]:[]);
  const data=new Map(session ? [['kl_acquisition_v1',JSON.stringify(session)]]:[]);
  const storage=map=>({getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)});
  for(const id of ['overlay','step-main','step-settings','stats','affiliate','ads','accept','reject','customize','back','save','toggle-providers','providers-list']) {
    elements['consent-'+id]={hidden:true,checked:false,focus(){},addEventListener(n,fn){this[n]=fn;}};
  }
  const document={getElementById:id=>elements[id],addEventListener(n,fn){(handlers[n]??=[]).push(fn);}};
  Object.defineProperty(document,'cookie',{set:v=>cookies.push(v)});
  const window={location:{href:url},dataLayer:[],__klTrackingConfig:{gtm_consent_reviewed:true,context_ttl_seconds:1800,...config},
    __loadGTM(){window.loaded=(window.loaded||0)+1;},addEventListener(n,fn){listeners[n]=fn;}};
  vm.runInNewContext(script,{window,document,localStorage:storage(local),sessionStorage:storage(data),URL,
    crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'},Date});
  return {window,elements,data,cookies,listeners,local,
    press:id=>elements['consent-'+id].click(),
    emit(name='click',affiliate=true,href='/go/tgt_AAAAAAAAAAAAAAAAAAAAAAAAAA'){
      const link={href,getAttribute:k=>k==='data-retailer'?'Synthetic':affiliate?'1':'0'};
      const e={button:0,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},
        target:{closest:selector=>selector==='[data-consent-open]'?null:
          selector==='a[data-affiliate="1"]'?(affiliate?link:null):link}};
      for(const fn of handlers[name]||[])fn(e); e.link=link; return e;
    }};
}
const consent=(stats,affiliate,ads)=>({version:2,at:Date.now(),stats,affiliate,ads});
const events=b=>b.window.dataLayer.filter(x=>x.event);
test('no pre-consent event buffering or retroactive replay',()=>{
  const b=boot(); b.emit(); b.emit('click',false); assert.equal(events(b).length,0);
  b.press('accept'); assert.equal(events(b).length,0); b.emit(); assert.equal(events(b).length,1);
});
test('defaults precede updates and tag load; personalization always denied',()=>{
  const b=boot({saved:consent(true,true,true)});
  assert.equal(b.window.dataLayer[0][1],'default');
  assert.equal(b.window.dataLayer[0][2].ad_storage,'denied');
  assert.equal(b.window.dataLayer[1][2].ad_personalization,'denied'); assert.equal(b.window.loaded,1);
});
test('statistics permission does not grant ads or affiliate; every ordinary alternate click blocked',()=>{
  const b=boot({saved:consent(true,false,false)});
  for(const n of ['click','auxclick','contextmenu'])assert.equal(b.emit(n).defaultPrevented,true);
  assert.equal(b.emit('click',false).defaultPrevented,false);
  assert.equal(b.window.dataLayer[1][2].ad_storage,'denied');
});
test('withdrawal stops events and clears acquisition immediately',()=>{
  const b=boot({saved:consent(true,true,true)}); b.emit(); b.press('reject'); b.emit('click',false);
  assert.equal(events(b).length,1); assert.equal(b.window['ga-disable-G-ELJYYBLS6H'],true);
  assert.match(b.cookies.at(-1),/Max-Age=0/);
});
test('other tab withdrawal is applied',()=>{
  const b=boot({saved:consent(true,true,true)}); b.local.clear(); b.listeners.storage({key:'kl_consent_v2'});
  b.emit('click',false); assert.equal(events(b).length,0);
});
test('old/malformed/expired saved permission never infers consent',()=>{
  for(const saved of [{stats:true},consent('true',true,true),{...consent(true,true,true),at:0}]) {
    const b=boot({saved});assert.equal(b.window.loaded,undefined);assert.equal(b.elements['consent-overlay'].hidden,false);
  }
});
test('GTM remains unloaded until container review, even after accept',()=>{
  const b=boot({config:{gtm_consent_reviewed:false}}); b.press('accept'); b.emit();
  assert.equal(b.window.loaded,undefined);assert.equal(events(b).length,0);
});
const config={acquisition_enabled:true,account_id:'123'};
const url='https://kontaktlinser.no/?gclid=synthetic_google_click&kl_campaign=456';
test('capture requires both permissions; no new permission inherited',()=>{
  for(const c of [consent(true,true,false),consent(true,false,true)]) {
    const b=boot({saved:c,config,url}); assert.equal(b.data.size,0);assert.match(b.cookies.at(-1),/Max-Age=0/);
  }
});
test('consented acquisition survives internal navigation and expires without sliding',()=>{
  const b=boot({saved:consent(false,true,true),config,url});
  const c=JSON.parse(b.data.get('kl_acquisition_v1'));assert.equal(c.campaign_id,'456');
  const next=boot({saved:consent(false,true,true),config,session:c});
  assert.match(next.cookies.at(-1),/synthetic_google_click/);assert.equal(events(next).length,0);
  const expired=boot({saved:consent(true,true,true),config,session:{...c,acquired_at:c.acquired_at-1900}});
  assert.equal(expired.data.size,0);
});
test('invalid or ambiguous Google identifiers do not carry prior attribution',()=>{
  for(const query of ['gclid=x&wbraid=y&kl_campaign=456','gclid=x&gclid=y&kl_campaign=456','gclid=x&kl_campaign=mail@example.test']) {
    const b=boot({saved:consent(true,true,true),config,url:'https://kontaktlinser.no/?'+query});
    assert.equal(b.data.size,0);
  }
});

test('pilot click uses own tab visit and never exposes Google ID in URL',()=>{
  const b=boot({saved:consent(true,true,true),config:{...config,pilot_paths:['/'],pilot_retailers:['Synthetic']},url});
  const c=JSON.parse(b.data.get('kl_acquisition_v1'));
  const e=b.emit();
  assert.equal(new URL(e.link.href).searchParams.get('acq_visit'),c.visit_id);
  assert(!e.link.href.includes('synthetic_google_click'));
  assert.equal(JSON.parse(b.data.get('kl_acquisition_v1')).visit_id,c.visit_id);
  const direct=b.emit('click',true,'https://network.example.test/original');
  assert.equal(direct.link.href,'https://network.example.test/original');
});
