(function (root) {
  'use strict';
  const months = ['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  function parisClock(now = new Date()) {
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(now).map(x => [x.type, x.value]));
    return {day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}`};
  }
  function monday(day) {
    const d = new Date(day + 'T12:00:00Z');
    d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7);
    return d.toISOString().slice(0, 10);
  }
  function weekSlug(day) {
    const [y, m, d] = monday(day).split('-').map(Number);
    const month = months[m].normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    return `semaine-${d}-${month}-${y}`;
  }
  function pretty(day) {
    const [y, m, d] = day.split('-').map(Number);
    return `${d} ${months[m]} ${y}`;
  }
  function futureSessions(event, clock) {
    return (event.sessions || []).filter(s => s.date > clock.day || (s.date === clock.day && s.time >= clock.time)).sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
  }
  function isUpcoming(event, clock) {
    return event.kind === 'cinema' ? futureSessions(event, clock).length > 0 : (event.end_date || event.start_date || '') >= clock.day;
  }
  function eventPath(e) {
    if (e.page_url) return new URL(e.page_url, 'https://agenda.vivreanyons.fr/').pathname;
    const slug = e.title.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 82).replace(/-+$/, '');
    return `/evenements/${slug}-${e.start_date}/`;
  }
  function nextKey(e, clock) {
    if (e.kind === 'cinema') { const s = futureSessions(e, clock)[0]; return s ? s.date + 'T' + s.time : '9999'; }
    return (e.start_date < clock.day ? clock.day : e.start_date) + 'T00:00';
  }
  const api = {parisClock, monday, weekSlug, futureSessions, isUpcoming, nextKey};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;
  const esc = value => String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
  let events = [], ready = false, lastTick = '';
  function render() {
    const clock = parisClock(), currentMonday = monday(clock.day), tick = clock.day + clock.time;
    if (tick === lastTick) return;
    lastTick = tick;
    const weekLink = '/semaines/' + weekSlug(clock.day) + '/';
    document.querySelectorAll('[data-current-week]').forEach(a => { a.href = weekLink; });
    document.querySelectorAll('.week-card').forEach(card => {
      const start = card.dataset.weekStart;
      if (!start) return;
      card.hidden = start < currentMonday;
      card.classList.toggle('current', start === currentMonday);
      const old = card.querySelector('.now');
      if (old) old.remove();
      if (start === currentMonday) { const badge = document.createElement('span'); badge.className = 'now'; badge.textContent = 'Cette semaine'; card.querySelector('.week-top').append(badge); }
    });
    const range = document.querySelector('meta[name="agenda-week-end"]');
    const status = document.getElementById('agenda-week-status');
    const archived = range && range.content < clock.day;
    if (status) {
      status.hidden = !archived;
      if (archived) status.innerHTML = `Cette semaine est terminée. Nous sommes le ${pretty(clock.day)}. <a href="${esc(weekLink)}"><strong>Voir la semaine en cours →</strong></a>`;
    }
    if (!ready) return;
    const byPath = new Map(events.map(e => [eventPath(e), e]));
    document.querySelectorAll('.grid > a.card, .events > article.event').forEach(card => {
      if (archived) return;
      const a = card.matches('a') ? card : card.querySelector('h3 a');
      if (!a) return;
      const e = byPath.get(new URL(a.href).pathname);
      if (!e) return;
      let sessions = futureSessions(e, clock);
      if (range) sessions = sessions.filter(s => s.date <= range.content);
      card.hidden = e.kind === 'cinema' ? sessions.length === 0 : !isUpcoming(e, clock);
      if (e.kind === 'cinema' && sessions.length) {
        const s = sessions[0], line = card.querySelector('.when, .date-line');
        if (line) line.textContent = `Prochaine séance : ${pretty(s.date)} à ${s.time.replace(':', ' h ')}`;
        const badge = card.querySelector('.datebox, .date-badge');
        if (badge) badge.innerHTML = `<strong>${Number(s.date.slice(8))}</strong><span>${months[Number(s.date.slice(5,7))].slice(0,3).toUpperCase()}</span>`;
      }
    });
    if (!archived) document.querySelectorAll('.grid, .events').forEach(list => {
      Array.from(list.children).sort((a,b) => {
        const get = card => {const link = card.matches('a') ? card : card.querySelector('h3 a'); return link && byPath.get(new URL(link.href).pathname);};
        const ea = get(a), eb = get(b);
        return (ea ? nextKey(ea,clock) : '9999').localeCompare(eb ? nextKey(eb,clock) : '9999');
      }).forEach(card => list.append(card));
    });
    const active = events.filter(e => isUpcoming(e, clock)).sort((a,b) => nextKey(a,clock).localeCompare(nextKey(b,clock)) || a.title.localeCompare(b.title));
    const zone = document.getElementById('events');
    if (zone) zone.innerHTML = active.slice(0,6).map(e => {
      const s = futureSessions(e,clock)[0];
      const label = s ? `Prochaine séance : ${pretty(s.date)} à ${s.time.replace(':',' h ')}` : e.date_label || (e.start_date === e.end_date ? pretty(e.start_date) : `Du ${pretty(e.start_date)} au ${pretty(e.end_date)}`);
      return `<article class="event"><div class="event-date">${esc(label)}</div><h3><a href="${esc(eventPath(e))}">${esc(e.title)}</a></h3><div class="event-links"><a href="${esc(eventPath(e))}">Lire notre fiche →</a></div></article>`;
    }).join('') || '<p>Aucun prochain rendez-vous annoncé pour le moment.</p>';
    const filmZone = document.querySelector('.cinema-home-cards') || (location.pathname === '/cinema/' ? document.querySelector('.cards') : null);
    if (filmZone) {
      let films = active.filter(e => e.kind === 'cinema');
      if (filmZone.classList.contains('cinema-home-cards')) films = films.slice(0,6);
      filmZone.innerHTML = films.map(e => {
        const s = futureSessions(e,clock)[0], f = e.film || {};
        return `<a class="film-card" href="${esc(eventPath(e))}"><img src="${esc(e.poster || f.poster)}" alt="${esc(f.poster_alt || 'Affiche de ' + e.film_title)}" width="320" loading="lazy"><h2>${esc(e.film_title || e.title)}</h2><p>Prochaine séance : ${pretty(s.date)} à ${s.time.replace(':',' h ')}</p><p>${esc(e.summary)}</p><strong>Voir les horaires →</strong></a>`;
      }).join('') || '<p>Le programme précédent est terminé. Consulte le site officiel de L’Arlequin en attendant le suivant.</p>';
    }
  }
  const style = document.createElement('style');
  style.textContent = '[hidden]{display:none!important}.agenda-week-status{padding:18px 22px;margin:18px 0;border:2px solid #a94f35;border-radius:14px;background:#fff2df;color:#262722;font-size:18px;line-height:1.6}.agenda-week-status a{color:#354622}[data-current-week].back{display:inline-block;margin:10px 0;padding:9px 14px;border:1px solid #d8cfbf;border-radius:24px;background:#fff;color:#354622;font-weight:700;text-decoration:none}';
  document.head.append(style);
  render();
  fetch('/agenda.json?date=' + parisClock().day, {cache:'no-store'}).then(r => {if (!r.ok) throw new Error('Agenda indisponible'); return r.json();}).then(data => {events = Array.isArray(data) ? data : data.events || []; ready = true; lastTick = ''; render();}).catch(() => {});
  setInterval(render, 30000);
  document.addEventListener('visibilitychange', () => {if (!document.hidden) render();});
})(typeof globalThis !== 'undefined' ? globalThis : this);
