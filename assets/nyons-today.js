(function (root) {
  'use strict';
  const zone = 'Europe/Paris';
  function parisClock(now = new Date()) {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).map(x=>[x.type,x.value]));
    return {day:p.year+'-'+p.month+'-'+p.day,time:p.hour+':'+p.minute};
  }
  function addDays(day, n) {
    const d = new Date(day+'T12:00:00Z');
    d.setUTCDate(d.getUTCDate()+n);
    return d.toISOString().slice(0,10);
  }
  function weekday(day) {return new Date(day+'T12:00:00Z').getUTCDay();}
  function rangeFor(day, view) {
    if(view==='demain') return {start:addDays(day,1),end:addDays(day,1)};
    if(view==='weekend') {
      const w=weekday(day), start=addDays(day,w===0?-1:w===6?0:6-w);
      return {start,end:addDays(start,1)};
    }
    return {start:day,end:day};
  }
  function nextThursday(day) {return addDays(day,(4-weekday(day)+7)%7 || 7);}
  function occurs(e, range) {
    return e.kind!=='cinema' && !!e.start_date && e.start_date<=range.end && (e.end_date||e.start_date)>=range.start;
  }
  function eventPath(e) {
    if(e.page_url) {
      try {const u=new URL(e.page_url,'https://agenda.vivreanyons.fr/');if(u.origin==='https://agenda.vivreanyons.fr' && u.pathname.startsWith('/evenements/')) return u.pathname;}catch (_) {}
    }
    const slug=String(e.title||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^\x00-\x7F]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,82).replace(/-+$/,'')||'evenement';
    return '/evenements/'+slug+'-'+e.start_date+'/';
  }
  function sessionsFor(films, range) {
    return films.flatMap(film=>(film.sessions||[]).filter(s=>s.date>=range.start && s.date<=range.end).map(s=>({film,session:s}))).sort((a,b)=>(a.session.date+a.session.time).localeCompare(b.session.date+b.session.time)||a.film.title.localeCompare(b.film.title));
  }
  function formatObservation(obs) {
    const m=obs.match(/ (\d{1,2}):(\d{2})(?:\s*(AM|PM))?/i);
    if(!m) return '';
    let hour=Number(m[1]);
    if(m[3]) hour=hour%12+(m[3].toUpperCase()==='PM'?12:0);
    return String(hour).padStart(2,'0')+' h '+m[2];
  }
  function normalizeWeather(data, day) {
    const forecast=(data.weather||[]).find(d=>d.date===day);
    if(!forecast) throw new Error('Prévisions du jour indisponibles');
    const current=(data.current_condition||[])[0]||{};
    const number=v=>v!==null && v!==undefined && String(v).trim()!=='' && Number.isFinite(Number(v))?Number(v):null;
    const obs=String(current.localObsDateTime||'');
    const validCurrent=obs.slice(0,10)===day;
    const hourly=forecast.hourly||[];
    const rain=hourly.map(h=>number(h.precipMM));
    return {date:day,temperature:validCurrent?number(current.temp_C):null,
      observation:validCurrent?formatObservation(obs):'',
      min:number(forecast.mintempC),max:number(forecast.maxtempC),
      rain:rain.length && rain.every(v=>v!==null)?Math.round(rain.reduce((a,b)=>a+b,0)*10)/10:null,
      wind:validCurrent?number(current.windspeedKmph):null,
      windMax:hourly.length && hourly.every(h=>number(h.windspeedKmph)!==null)?Math.max(...hourly.map(h=>number(h.windspeedKmph))):null,
      description:validCurrent?((current.lang_fr||current.weatherDesc||[])[0]||{}).value||'':'',
      fetched_at:new Date().toISOString()};
  }
  const api={parisClock,addDays,rangeFor,nextThursday,occurs,eventPath,sessionsFor,normalizeWeather};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  if(typeof document==='undefined') return;
  const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pretty=day=>new Intl.DateTimeFormat('fr-FR',{timeZone:zone,weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date(day+'T12:00:00Z'));
  const fmt=v=>v===null || v===undefined?'Non disponible':new Intl.NumberFormat('fr-FR',{maximumFractionDigits:1}).format(v);
  const params=new URLSearchParams(location.search);
  const view=['demain','weekend'].includes(params.get('vue'))?params.get('vue'):'aujourdhui';
  if(view!=='aujourdhui') {
    document.querySelector('meta[name="robots"]').content='noindex,follow';
    document.getElementById('weather-section').hidden=true;
  }
  let agenda=null, programme=null, lastDay='', weatherBusy=false;
  function renderDate() {
    const clock=parisClock(), range=rangeFor(clock.day,view);
    const label=view==='demain'?'DEMAIN À NYONS':view==='weekend'?'CE WEEK-END À NYONS':'NYONS AUJOURD’HUI';
    document.getElementById('today-title').textContent=label;
    document.getElementById('today-date').textContent=range.start===range.end?pretty(range.start):pretty(range.start)+' et '+pretty(range.end);
    document.getElementById('today-date').dateTime=range.start;
    document.getElementById('events-title').textContent=view==='aujourdhui'?'Que faire à Nyons aujourd’hui ?':view==='demain'?'Les événements demain à Nyons':'Les événements ce week-end à Nyons';
    document.getElementById('cinema-title').textContent=view==='aujourdhui'?'Cinéma à Nyons aujourd’hui':view==='demain'?'Cinéma demain à Nyons':'Cinéma ce week-end à Nyons';
    const thursday=weekday(range.start)===4?range.start:nextThursday(range.start);
    document.getElementById('market-text').textContent=thursday<=range.end?'Grand marché traditionnel le matin'+(view==='aujourdhui'?' aujourd’hui.':', '+pretty(thursday)+'.'):'Prochain grand marché traditionnel : '+pretty(thursday)+', le matin.';
    if(view!=='aujourdhui') document.title=label+' : événements et cinéma';
    return {clock,range};
  }
  function renderData() {
    const {clock,range}=renderDate();
    if(agenda) {
      const events=agenda.events.filter(e=>occurs(e,range)).sort((a,b)=>a.start_date.localeCompare(b.start_date)||a.title.localeCompare(b.title));
      document.getElementById('today-events').innerHTML=events.map(e=>'<article class="event"><div class="event-date">'+esc(e.start_date===e.end_date?pretty(e.start_date):'Du '+pretty(e.start_date)+' au '+pretty(e.end_date||e.start_date))+'</div><h3><a href="'+esc(eventPath(e))+'">'+esc(e.title)+'</a></h3><p>'+esc(e.summary)+'</p><a class="card-link" href="'+esc(eventPath(e))+'">Voir la fiche →</a></article>').join('')||'<p>Aucun événement annoncé pour cette date dans notre agenda. Retrouvez les autres rendez-vous dans <a href="/evenements/">tous les événements</a>.</p>';
      if(agenda.updated_at) document.getElementById('agenda-updated').textContent='Agenda actualisé le '+new Intl.DateTimeFormat('fr-FR',{timeZone:zone,dateStyle:'long',timeStyle:'short'}).format(new Date(agenda.updated_at))+'.';
    }
    if(programme) {
      const sessions=sessionsFor(programme.films,range);
      const filmLinks=new Map((agenda?agenda.events:[]).filter(e=>e.kind==='cinema').map(e=>[e.film_title||e.film?.title,eventPath(e)]));
      document.getElementById('today-cinema').innerHTML=sessions.map(({film,session})=>{
        const path=filmLinks.get(film.title)||'/cinema/';
        const past=session.date<clock.day || (session.date===clock.day && session.time<clock.time);
        return '<article class="session'+(past?' session-past':'')+'"><div class="session-time"><time datetime="'+esc(session.date)+'T'+esc(session.time)+'">'+esc(session.time.replace(':',' h '))+'</time>'+(range.start!==range.end?'<span>'+esc(pretty(session.date))+'</span>':'')+'</div><div><h3><a href="'+esc(path)+'">'+esc(film.title)+'</a></h3><p>'+esc(session.version||'')+(film.duration?' · '+esc(film.duration):'')+(past?' · Séance passée':'')+'</p><a class="card-link" href="'+esc(path)+'">Voir les horaires du film →</a></div></article>';
      }).join('')||(range.start>programme.period_end || range.end<programme.period_start?'<p>Le programme disponible ne couvre pas ces dates. <a href="https://www.cinema-arlequin.fr/" target="_blank" rel="noopener">Consulter le programme officiel de L’Arlequin</a>.</p>':'<p>Aucune séance annoncée à cette date dans le programme disponible.</p>');
    }
  }
  function weatherHTML(w) {
    const details=[['Température à '+(w.observation||'la dernière mise à jour'),w.temperature===null?'Non disponible':fmt(w.temperature)+' °C'],
      ['Mini / maxi prévus',fmt(w.min)+' / '+fmt(w.max)+' °C'],
      ['Pluie prévue sur la journée',w.rain===null?'Non disponible':fmt(w.rain)+' mm'],
      ['Vent'+(w.wind===null?' maximal prévu':''),fmt(w.wind===null?w.windMax:w.wind)+' km/h']];
    return '<div class="weather-grid">'+details.map(([label,value])=>'<div class="weather-metric"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></div>').join('')+'</div>'+(w.description?'<p>'+esc(w.description)+'</p>':'')+'<p class="muted">Météo du '+esc(pretty(w.date))+'. Prévisions et dernière observation disponible.</p>';
  }
  async function json(url) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),12000);
    try {const r=await fetch(url,{signal:controller.signal,cache:'no-store'});if(!r.ok) throw new Error('Données indisponibles');return await r.json();}finally{clearTimeout(timer);}
  }
  async function loadWeather() {
    if(view!=='aujourdhui'||weatherBusy) return;
    weatherBusy=true;
    const day=parisClock().day, zoneEl=document.getElementById('today-weather');
    let cached=null;
    try {cached=JSON.parse(localStorage.getItem('nyons-weather-v1')||'null');}catch(_){}
    try {
      if(cached && cached.date===day && Date.now()-Date.parse(cached.fetched_at)<1800000) {
        zoneEl.innerHTML=weatherHTML(cached);return;
      }
      let data;
      for(const host of ['wttr.is','wttr.in']) {
        try {data=normalizeWeather(await json('https://'+host+'/44.36,5.14?format=j1&lang=fr'),day);break;}catch(_){}
      }
      if(!data) {
        const snapshot=await json('/aujourdhui/meteo.json');
        if(snapshot.date!==day || Date.now()-Date.parse(snapshot.fetched_at)>21600000) throw new Error('Météo trop ancienne');
        data=snapshot;
      }
      if(parisClock().day!==day) return;
      zoneEl.innerHTML=weatherHTML(data);
      try {localStorage.setItem('nyons-weather-v1',JSON.stringify(data));}catch(_){}
    } catch(_) {
      if(parisClock().day===day) zoneEl.innerHTML='<p>La météo du jour est temporairement indisponible. <a href="https://wttr.in/Nyons?lang=fr">Consulter la météo de Nyons</a>.</p>';
    } finally {weatherBusy=false;}
  }
  async function loadData() {
    await Promise.all([
      json('/agenda.json').then(data=>{if(!Array.isArray(data.events)) throw new Error('Agenda invalide');agenda=data;renderData();}).catch(()=>{document.getElementById('today-events').innerHTML='<p>Les événements du jour sont temporairement indisponibles. <a href="/evenements/">Voir tous les événements</a>.</p>';}),
      json('/cinema-programme.json').then(data=>{if(!Array.isArray(data.films)) throw new Error('Programme invalide');programme=data;renderData();}).catch(()=>{document.getElementById('today-cinema').innerHTML='<p>Les séances sont temporairement indisponibles. <a href="/cinema/">Voir le cinéma</a>.</p>';})
    ]);
  }
  function tick() {
    const day=parisClock().day;
    renderData();
    if(day!==lastDay) {lastDay=day;loadData();loadWeather();}
  }
  // Hide the static snapshot before a midnight rollover or a different view.
  const snapshotDay=document.body.dataset.generatedDay;
  if(snapshotDay!==parisClock().day || view!=='aujourdhui') {
    document.getElementById('today-events').textContent='Chargement des événements…';
    document.getElementById('today-cinema').textContent='Chargement des séances…';
    document.getElementById('today-weather').textContent='Chargement de la météo…';
  }
  tick();
  setInterval(tick,30000);
  setInterval(()=>{loadData();loadWeather();},1800000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){tick();loadData();loadWeather();}});
})(typeof globalThis!=='undefined'?globalThis:this);
