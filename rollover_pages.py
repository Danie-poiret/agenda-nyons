"""Keep dated archives clear and current selections independent of the daily scrape."""
import re
import json,html,unicodedata
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from cinema_agenda import paris_today
from event_selection import enrich,sessions,upcoming,next_key

SCRIPT = '<script src="/assets/agenda-current.js?v=20261022-events" defer></script>'
MONTHS = ['janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre']

def week_start(slug):
    m = re.fullmatch(r'semaine-(\d+)-([a-z]+)-(\d+)', slug)
    return date(int(m[3]), MONTHS.index(m[2])+1, int(m[1])) if m else None

def listing_url(e):
    if e.get('page_url'):return e['page_url']
    value=unicodedata.normalize('NFKD',e['title']).encode('ascii','ignore').decode().lower()
    slug=re.sub('[^a-z0-9]+','-',value).strip('-')[:82].rstrip('-')
    return 'https://agenda.vivreanyons.fr/evenements/'+slug+'-'+e['start_date']+'/'

def order_listing(source,path,events,today):
    """Correct navigation cards after the existing generation, preserving detail pages."""
    weekly=path.startswith('semaines/semaine-')
    if not weekly and path!='evenements/index.html':return source
    first=week_start(path.split('/')[1]) if weekly else today
    last=first+timedelta(days=6) if weekly else None
    # Dated archives remain accessible, with their original contents.
    if last and last<today:return source
    now=datetime.now(ZoneInfo('Europe/Paris'))
    if first>now.date():now=datetime.combine(first,datetime.min.time(),tzinfo=ZoneInfo('Europe/Paris'))
    by_url={listing_url(e):e for e in events}
    pattern=r'<article class="event"[^>]*>.*?</article>' if weekly else r'<a class="card"[^>]*>.*?</a>'
    matches=list(re.finditer(pattern,source,re.S));ordered=[]
    for m in matches:
        card=m.group(0);links=re.findall(r'href="([^"]+)"',card)
        e=next((by_url[html.unescape(u)] for u in links if html.unescape(u) in by_url),None)
        if not e or not upcoming(e,now):continue
        ss=sessions(e,now)
        if last:ss=[s for s in ss if first.isoformat()<=s['date']<=last.isoformat()]
        if e.get('kind')=='cinema':
            if not ss:continue
            day=ss[0]['date'];key=day+'T'+ss[0]['time']
            label=('Séances cette semaine : '+' ; '.join(s['date'][8:10]+'/'+s['date'][5:7]+'/'+s['date'][:4]+' à '+s['time'].replace(':',' h ')+' ('+s['version']+')' for s in ss)) if weekly else 'Prochaine séance : '+day[8:10]+'/'+day[5:7]+'/'+day[:4]+' à '+ss[0]['time'].replace(':',' h ')
        else:
            day=max(first.isoformat(),e['start_date']);key=day+'T'+e.get('start_time','00:00')
            label=e.get('date_label')
            if not label:label=e['start_date'][8:10]+'/'+e['start_date'][5:7]+'/'+e['start_date'][:4]+(' → '+e['end_date'][8:10]+'/'+e['end_date'][5:7]+'/'+e['end_date'][:4] if e['end_date']!=e['start_date'] else '')
            if e['start_date']<today.isoformat():label='En cours — '+label
        month=['JAN','FÉV','MAR','AVR','MAI','JUIN','JUIL','AOÛ','SEP','OCT','NOV','DÉC'][int(day[5:7])-1]
        badge_class='date-badge' if weekly else 'datebox'
        badge=f'<div class="{badge_class}"><strong>{int(day[8:10])}</strong><span>{month}</span></div>'
        if weekly:badge=f'<div class="date-badge"><span>{int(day[8:10])}</span><small>{month}</small></div>'
        card=re.sub(r'<div class="'+badge_class+r'">.*?</div>',lambda _:badge,card,count=1,flags=re.S)
        card=re.sub(r'<p class="(?:when|date-line)">.*?</p>',lambda _:'<p class="'+('date-line' if weekly else 'when')+'">'+html.escape(label)+'</p>',card,count=1,flags=re.S)
        if not weekly:
            card=re.sub(r' data-event-(?:start|end)="[^"]*"','',card)
            card=card.replace('<a class="card"','<a class="card" data-event-start="'+e['start_date']+'" data-event-end="'+e['end_date']+'"',1)
        ordered.append((key,e['title'].lower(),card,e))
    ordered.sort(key=lambda item:(item[0],item[1]))
    if matches:source=source[:matches[0].start()]+'\n'.join(x[2] for x in ordered)+source[matches[-1].end():]
    if not ordered and matches:source=source.replace('<section class="grid">','<section class="grid"><p>Aucun prochain événement annoncé pour le moment. <a href="https://www.nyons.com/sorties-actus/agenda/">Consulter l’agenda municipal</a>.</p>',1)
    # Keep the pre-existing weekly ItemList consistent with the visible order.
    def schema(m):
        try:data=json.loads(m[1])
        except (ValueError,TypeError):return m[0]
        if data.get('@type')!='ItemList':return m[0]
        data['itemListElement']=[{'@type':'ListItem','position':i,'name':row[3]['title'],'url':listing_url(row[3])} for i,row in enumerate(ordered,1)]
        return '<script type="application/ld+json">'+json.dumps(data,ensure_ascii=False)+'</script>'
    return re.sub(r'<script type="application/ld\+json">(.*?)</script>',schema,source,flags=re.S)

def install_page(source, path, today=None,events=None):
    today = today or paris_today()
    monday = today - timedelta(days=today.weekday())
    path = str(path).replace('\\','/')
    source = re.sub(r'<script src="/assets/agenda-current\.js(?:\?[^"]*)?" defer(?:="defer")?></script>', '', source)
    if SCRIPT not in source:
        source = source.replace('</head>', SCRIPT+'</head>',1)
    # The shared renderer owns the homepage selection, including cinema cards.
    if path == 'index.html':
        source = re.sub(r'<script>\s*function slugifyEvent\(text\).*?</script>', '', source, flags=re.S)
    if path.startswith('semaines/semaine-'):
        start = week_start(path.split('/')[1]); end = start + timedelta(days=6)
        if 'name="agenda-week-end"' not in source:
            source = source.replace('</head>', f'<meta name="agenda-week-end" content="{end.isoformat()}"></head>',1)
        if 'id="agenda-week-status"' not in source:
            hidden = '' if end < today else ' hidden'
            notice = f'<p id="agenda-week-status" class="agenda-week-status" role="status"{hidden}>Cette semaine est terminée. <a data-current-week href="/semaines/">Voir la semaine en cours →</a></p>'
            source = source.replace('<section class="hero">', notice+'\n<section class="hero">',1)
    if path == 'semaines/index.html':
        def card(match):
            classes, slug, body = match.groups(); start = week_start(slug)
            body = re.sub(r'<span class="now">.*?</span>', '', body, flags=re.S)
            if start == monday: body = body.replace('<span class="calendar">📅</span>', '<span class="calendar">📅</span><span class="now">Cette semaine</span>')
            classes = 'week-card current' if start == monday else 'week-card'
            return f'<a class="{classes}" data-week-start="{start.isoformat()}" href="{slug}/"'+(' hidden' if start < monday else '')+'>'+body+'</a>'
        source = re.sub(r'<a class="(week-card[^"]*)"(?: data-week-start="[^"]*")? href="(semaine-[^/]+)/"(?: hidden)?>(.*?)</a>', card, source, flags=re.S)
    if 'data-current-week' not in source or path.startswith('semaines/semaine-'):
        link = '<a class="back" data-current-week href="/semaines/">📅 La semaine en cours</a>'
        if '📅 La semaine en cours' not in source:
            source = re.sub(r'(<main[^>]*>)', r'\1\n'+link, source, count=1)
    if events is not None:source=order_listing(source,path,events,today)
    return source

def install_live_agenda(root=None):
    root = Path(root or __file__).resolve()
    if root.is_file(): root = root.parent
    events=None
    if (root/'agenda.json').exists():
        payload=json.loads((root/'agenda.json').read_text(encoding='utf8'))
        def cached(name):return json.loads((root/name).read_text(encoding='utf8')) if (root/name).exists() else {}
        events=enrich(payload.get('events',[]),cached('_event_detail_cache.json'),cached('_event_seo_cache.json'))
        (root/'agenda.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    paths = [root/'index.html',root/'semaines/index.html',root/'evenements/index.html',root/'cinema/index.html']
    paths += list((root/'semaines').glob('semaine-*/index.html'))
    for p in paths:
        if p.exists(): p.write_text(install_page(p.read_text(encoding='utf-8'),p.relative_to(root),events=events),encoding='utf-8')

if __name__ == '__main__': install_live_agenda()
