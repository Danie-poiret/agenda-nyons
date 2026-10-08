const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const api=require('../assets/nyons-today.js');

(async()=>{
  const base=process.env.UI_BASE_URL||'http://127.0.0.1:4173';
  const browser=await chromium.launch();
  const context=await browser.newContext({viewport:{width:1280,height:900},timezoneId:'America/Los_Angeles'});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  try {
    const agenda=await (await context.request.get(base+'/agenda.json')).json();
    const programme=await (await context.request.get(base+'/cinema-programme.json')).json();
    const day=api.parisClock().day;
    await page.goto(base+'/',{waitUntil:'domcontentloaded'});
    await page.locator('#nyons-today-link').waitFor({state:'visible'});
    assert.equal(await page.locator('#nyons-today-link').getAttribute('href'),'/aujourdhui/');
    await page.locator('#nyons-today-link').click();
    await page.waitForURL('**/aujourdhui/');
    await page.waitForFunction(()=>document.getElementById('today-date').dateTime===new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()));
    for(const [view,title]of [['aujourdhui','NYONS AUJOURD’HUI'],['demain','DEMAIN À NYONS'],['weekend','CE WEEK-END À NYONS']]) {
      await page.goto(base+'/aujourdhui/'+(view==='aujourdhui'?'':'?vue='+view),{waitUntil:'domcontentloaded'});
      assert.equal(await page.locator('#today-title').textContent(),title);
      const range=api.rangeFor(day,view);
      const expectedEvents=agenda.events.filter(e=>api.occurs(e,range));
      const expectedSessions=api.sessionsFor(programme.films,range);
      await page.waitForFunction(({events,sessions})=>document.querySelectorAll('#today-events .event').length===events&&document.querySelectorAll('#today-cinema .session').length===sessions,{events:expectedEvents.length,sessions:expectedSessions.length});
      for(const e of expectedEvents) assert.ok((await page.locator('#today-events').textContent()).includes(e.title),e.title);
      for(const item of expectedSessions) assert.ok((await page.locator('#today-cinema').textContent()).includes(item.film.title),item.film.title);
      assert.equal(await page.locator('#today-date').getAttribute('datetime'),range.start);
      assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'),'https://agenda.vivreanyons.fr/aujourdhui/');
      assert.equal(await page.locator('#weather-section').isVisible(),view==='aujourdhui');
      console.log(view+': '+expectedEvents.length+' événements, '+expectedSessions.length+' séances, date '+range.start);
      if(view==='aujourdhui') {
        await page.locator('.weather-grid').waitFor({timeout:40000});
        const weather=await page.locator('#today-weather').textContent();
        assert.ok(weather.includes('°C')&&weather.includes('mm')&&weather.includes('km/h'));
        assert.ok(!weather.includes('Non disponible'),'Temperature/weather missing: '+weather);
        console.log('Météo affichée : '+weather);
      }
    }
    await page.goto(base+'/aujourdhui/',{waitUntil:'domcontentloaded'});
    fs.mkdirSync('work/today-screenshots',{recursive:true});
    for(const width of [1280,375]) {
      await page.setViewportSize({width,height:900});
      await page.waitForTimeout(500);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width+'px');
      await page.screenshot({path:'work/today-screenshots/today-'+width+'.png',fullPage:true});
      console.log('Mise en page vérifiée à '+width+' px.');
    }
    await page.goto(base+'/evenements/',{waitUntil:'domcontentloaded'});
    assert.ok((await page.locator('h1').textContent()).includes('Nyons'));
    await page.goto(base+'/cinema/',{waitUntil:'domcontentloaded'});
    assert.ok((await page.locator('h1').textContent()).match(/Nyons|NYONS/));
    assert.deepEqual(errors,[]);
    console.log('Accueil, sélections et pages existantes contrôlés sans erreur JavaScript.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
