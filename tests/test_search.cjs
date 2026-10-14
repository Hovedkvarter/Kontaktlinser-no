'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const engine = require('../site_generator/lens_search.js');

function item(name, href, search = name, meta = '') {
  return {name, href, search, meta, image: null};
}
const data = [
  item('1-Day Acuvue Moist 30-pack','/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/'),
  item('1-Day Acuvue Moist 90-pack','/kontaktlinser/acuvue/1-day-acuvue-moist-90-pack/'),
  item('1-Day Acuvue Moist for Astigmatism 30-pack','/kontaktlinser/acuvue/1-day-acuvue-moist-for-astigmatism-30-pack/'),
  item('1-Day Acuvue Moist Multifocal 30-pack','/kontaktlinser/acuvue/1-day-acuvue-moist-multifocal-30-pack/'),
  item('Acuvue Oasys 6-pack','/kontaktlinser/acuvue/acuvue-oasys-6-pack/'),
  item('Acuvue Oasys MAX 1-Day 30-pack','/kontaktlinser/acuvue/acuvue-oasys-max-1-day-30-pack/'),
  item('Acuvue Oasys 1-Day with HydraLuxe 90-pack','/kontaktlinser/acuvue/acuvue-oasys-1-day-with-hydraluxe-90-pack/'),
  item('Dailies Total1 30-pack','/kontaktlinser/dailies/dailies-total1-30-pack/'),
  item('Dailies Total1 90-pack','/kontaktlinser/dailies/dailies-total1-90-pack/'),
  item('Dailies Total1 180-pack','/kontaktlinser/dailies/dailies-total1-180-pack/'),
  item('Dailies Total1','/serie/dailies-total1/','dailies total1 7 produkter'),
  item('Biofinity 6-pack','/kontaktlinser/biofinity/biofinity-6-pack/','biofinity 6-pack toriske-linser'),
  item('Biofinity Toric 6-pack','/kontaktlinser/biofinity/biofinity-toric-6-pack/'),
  item('Biofinity Toric 3-pack','/kontaktlinser/biofinity/biofinity-toric-3-pack/'),
  item('Biofinity XR 6-pack','/kontaktlinser/biofinity/biofinity-xr-6-pack/'),
  item('Biofinity Multifocal 6-pack','/kontaktlinser/biofinity/biofinity-multifocal-6-pack/'),
  item('iWear Slim','/private-label/iwear-slim/','iwear slim brilleland'),
  item('iWear Slim Astigmatism','/private-label/iwear-slim-astigmatism/'),
  item('Hylo-Comod 10 ml','/oyedraper/hylo/hylo-comod-10-ml/','hylo comod 10 ml øyedråper'),
  item('Opti-Free PureMoist 300 ml','/linsevaeske/opti-free/opti-free-puremoist-300-ml/'),
];
const index = engine.createIndex(data);
const result = q => engine.search(index,q);
const names = q => result(q).results.map(r=>r.item.name);

for (const q of ['1 day acuvue','1-day acuvue','1day acuvue','1–day acuvue','1\u2011day acuvue','  1 DAY  ACUVUE  ']) {
  test('same search set: '+q,()=>assert.deepEqual(names(q),names('1-Day Acuvue')));
}
for (const q of ['acuvue moist 1 day','moist acuvue day 1','ACUVUE® 1-day™ MOIST']) {
  test('word order / symbols: '+q,()=>assert(names(q).includes('1-Day Acuvue Moist 30-pack')));
}
for (const q of ['dailies total1','dailies total 1','dailies total-1']) {
  test('Total1 spelling: '+q,()=>assert.equal(result(q).results[0].item.href,'/serie/dailies-total1/'));
}
for (const unit of ['pk','pack','pakning','pakke','stk','linser']) {
  test('pack spelling: '+unit,()=>assert.equal(names('biofinity toric 6 '+unit)[0],'Biofinity Toric 6-pack'));
}
for (const [q,expected] of [['acuve moist','1-Day Acuvue Moist 30-pack'],['biofinty toric 6pk','Biofinity Toric 6-pack'],['acuvue mosit','1-Day Acuvue Moist 30-pack']]) {
  test('conservative typo: '+q,()=>{
    assert(names(q).includes(expected)); assert(result(q).approximate); assert.equal(engine.directMatch(result(q)),null);
  });
}
test('valid exact matches do not get mixed with fuzzy guesses',()=>assert(!result('acuvue moist').approximate));
test('partial word completion',()=>assert(names('acuv mois').includes('1-Day Acuvue Moist 30-pack')));
test('Norwegian letters',()=>assert.equal(names('oyedraper')[0],'Hylo-Comod 10 ml'));
test('private label spelling',()=>assert.equal(names('i wear slim')[0],'iWear Slim'));
test('pack sizes are strict',()=>assert.deepEqual(names('acuvue moist 90 pk'),['1-Day Acuvue Moist 90-pack']));
test('numbers are not prefixes',()=>assert.equal(names('biofinity 60').length,0));
test('wrong pack does not fuzzy fall back',()=>assert.equal(names('acuve moist 60 pk').length,0));
test('missing variant does not silently drop',()=>assert.equal(names('biofinity max').length,0));
test('XR remains explicit',()=>assert(names('biofinity xr').every(n=>n.includes('XR'))));
test('Toric cannot be supplied by keyword metadata',()=>assert(names('biofinity toric').every(n=>n.includes('Toric'))));
test('Multifocal remains explicit',()=>assert(names('acuvue moist multifocal').every(n=>n.includes('Multifocal'))));
test('series counts are not pack sizes',()=>assert.equal(names('dailies total1 7 pack').length,0));
test('a brand number is not a pack size',()=>assert.equal(names('dailies total1 1 pk').length,0));
test('duplicate numeric intent cannot reuse one token',()=>assert.equal(names('total 1 1').length,0));
test('wide query never jumps to an arbitrary product',()=>assert.equal(engine.directMatch(result('1 day acuvue')),null));
test('exact product can open immediately',()=>assert.equal(engine.directMatch(result('1 day acuvue moist 90 pk')).item.name,'1-Day Acuvue Moist 90-pack'));
test('exact series can open without guessing a pack',()=>assert.equal(engine.directMatch(result('dailies total 1')).item.href,'/serie/dailies-total1/'));
test('empty query',()=>assert.equal(names('').length,0));
test('nonsense query',()=>assert.equal(names('zxqvpy').length,0));
test('long query is bounded',()=>assert(result('a'.repeat(200)).tooLong));
test('malformed index is a load error, not zero results',()=>assert.throws(()=>engine.createIndex({error:'oops'})));
test('unsafe/external result destinations are excluded',()=>assert.equal(engine.createIndex([
 item('x','javascript:alert(1)'),item('x','//evil.test'),item('x','/\\evil.test'),item('x','https://evil.test')
]).length,0));
test('deduplicates href',()=>assert.equal(engine.createIndex([data[0],data[0]]).length,1));
test('matching never mutates names, hrefs or input data',()=>{
 const snapshot=JSON.stringify(data);engine.search(index,'acuve moist');assert.equal(JSON.stringify(data),snapshot);
});
test('all fixture names find their own original href',()=>{
 for(const entry of data)assert(names(entry.name).includes(entry.name),entry.name);
});

const builtIndex = path.join(__dirname,'../site_generator/build/data/search-index.json');
test('all names in the actually built site retain their original destinations', {skip:!fs.existsSync(builtIndex)},()=>{
 const current=JSON.parse(fs.readFileSync(builtIndex,'utf8'));const prepared=engine.createIndex(current);
 assert(prepared.length>200,'unexpectedly small index');
 for(const entry of current){
  assert(engine.search(prepared,entry.name).results.some(r=>r.item.href===entry.href),entry.href);
 }
 const sets=['1 day acuvue','1-day acuvue','1day acuvue'].map(q=>engine.search(prepared,q).results.map(r=>r.item.href));
 assert(sets[0].length>0);assert.deepEqual(sets[0],sets[1]);assert.deepEqual(sets[1],sets[2]);
 console.log('Current built search entries checked: '+current.length);
});
