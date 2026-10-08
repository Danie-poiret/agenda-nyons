const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const api = require('../assets/nyons-today.js');

test('Paris date is independent of visitor timezone, including midnight and DST', () => {
  assert.equal(api.parisClock(new Date('2026-10-07T22:30:00Z')).day, '2026-10-08');
  assert.equal(api.parisClock(new Date('2026-10-25T01:30:00Z')).time, '02:30');
  assert.equal(api.parisClock(new Date('2026-12-31T23:30:00Z')).day, '2027-01-01');
});
test('tomorrow, weekend, month and year boundaries', () => {
  assert.deepEqual(api.rangeFor('2026-10-08','demain'),{start:'2026-10-09',end:'2026-10-09'});
  assert.deepEqual(api.rangeFor('2026-10-08','weekend'),{start:'2026-10-10',end:'2026-10-11'});
  assert.deepEqual(api.rangeFor('2026-10-11','weekend'),{start:'2026-10-10',end:'2026-10-11'});
  assert.equal(api.addDays('2026-12-31',1),'2027-01-01');
  assert.equal(api.nextThursday('2026-10-08'),'2026-10-15');
  assert.equal(api.nextThursday('2026-10-09'),'2026-10-15');
});
test('events include overlapping exhibitions, exclude past/future and cinema ranges', () => {
  const r={start:'2026-10-08',end:'2026-10-08'};
  assert.ok(api.occurs({start_date:'2026-10-01',end_date:'2026-10-10'},r));
  assert.ok(api.occurs({start_date:'2026-10-08'},r));
  assert.ok(!api.occurs({start_date:'2026-10-07',end_date:'2026-10-07'},r));
  assert.ok(!api.occurs({start_date:'2026-10-09'},r));
  assert.ok(!api.occurs({kind:'cinema',start_date:'2026-10-01',end_date:'2026-10-10'},r));
});
test('cinema uses explicit sessions only; never turns a date range into daily screenings', () => {
  const films=[{title:'Film',sessions:[{date:'2026-10-07',time:'18:00'},{date:'2026-10-09',time:'20:00'}]}];
  assert.equal(api.sessionsFor(films,api.rangeFor('2026-10-08','aujourdhui')).length,0);
  assert.equal(api.sessionsFor(films,api.rangeFor('2026-10-08','demain')).length,1);
});
test('all current event paths point to existing pages', () => {
  const agenda=JSON.parse(fs.readFileSync('agenda.json','utf8'));
  for(const e of agenda.events) assert.ok(fs.existsSync('.'+api.eventPath(e)+'index.html'),e.title);
});
test('weather keeps zero values, rejects wrong day and never displays yesterday as today', () => {
  const data={current_condition:[{localObsDateTime:'2026-10-08 03:15 PM',temp_C:'0',windspeedKmph:'0'}],
    weather:[{date:'2026-10-08',mintempC:'0',maxtempC:'8',hourly:[{precipMM:'0',windspeedKmph:'0'}]}]};
  const w=api.normalizeWeather(data,'2026-10-08');
  assert.equal(w.temperature,0);assert.equal(w.rain,0);assert.equal(w.wind,0);
  assert.equal(w.observation,'15 h 15');
  assert.throws(()=>api.normalizeWeather(data,'2026-10-09'));
  data.current_condition[0].localObsDateTime='2026-10-07 03:15 PM';
  assert.equal(api.normalizeWeather(data,'2026-10-08').temperature,null);
  data.weather[0].hourly[0].precipMM=null;
  assert.equal(api.normalizeWeather(data,'2026-10-08').rain,null);
});
test('render runs with denied storage, failed APIs and tomorrow view', async () => {
  const elements=new Map();
  const element=id=>{if(!elements.has(id)) elements.set(id,{textContent:'',innerHTML:'',hidden:false});return elements.get(id);};
  const document={body:{dataset:{generatedDay:'2000-01-01'}},hidden:false,
    getElementById:element,querySelector:element,addEventListener(){}};
  const context={document,location:{search:'?vue=demain'},Intl,Date,URL,URLSearchParams,AbortController,
    setTimeout,clearTimeout,setInterval(){},fetch:async()=>{throw new Error('offline');},
    localStorage:{getItem(){throw new Error('denied');},setItem(){throw new Error('denied');}}};
  vm.runInNewContext(fs.readFileSync('assets/nyons-today.js','utf8'),context);
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.equal(element('today-title').textContent,'DEMAIN À NYONS');
  assert.equal(element('weather-section').hidden,true);
  assert.match(element('today-events').innerHTML,/temporairement indisponibles/);
  assert.match(element('today-cinema').innerHTML,/temporairement indisponibles/);
});
