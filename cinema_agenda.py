"""One permanent agenda page per film; sessions are explicit, never a daily date range."""
import html,json,re,unicodedata
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
SITE='https://agenda.vivreanyons.fr/'
MONTHS=['','janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre']
def paris_today():return datetime.now(ZoneInfo('Europe/Paris')).date()
def slug(text):
    raw=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().lower()
    return re.sub('[^a-z0-9]+','-',raw).strip('-')[:82].rstrip('-')

def browser_slug(text):
    raw=''.join(ch for ch in unicodedata.normalize('NFD',text) if not unicodedata.combining(ch)).lower()
    return re.sub('[^a-z0-9]+','-',raw).strip('-')[:82].rstrip('-')

def alternate_path(e):
    return f"evenements/{browser_slug(e['title'])}-{e['start_date']}/"
def fmt(raw):
    d=date.fromisoformat(raw);return f'{d.day} {MONTHS[d.month]} {d.year}'
def load_programme():return json.loads((ROOT/'cinema-programme.json').read_text(encoding='utf-8'))
def film_event(f):
    dates=sorted({s['date'] for s in f['sessions']})
    title=f.get('event_title') or 'Cinéma — '+f['title']
    path=f'evenements/{slug(title)}-{dates[0]}/'
    return {'title':title,'film_title':f['title'],'kind':'cinema','start_date':dates[0],'end_date':dates[-1],'date_label':'Séances datées du '+fmt(dates[0])+' au '+fmt(dates[-1])+' — voir les horaires','summary':f['description'],'categories':['Cinéma','Culture'],'url':f.get('source_event_url') or SITE+path,'page_url':SITE+path,'sessions':f['sessions'],'poster':f['poster'],'film':f}
def merge_cinema_events(events):
    data=load_programme();films=[film_event(f) for f in data['films']]
    replace={e['url'] for e in films}
    return sorted([e for e in events if e.get('kind')!='cinema' and e.get('url') not in replace]+films,key=lambda e:(e['start_date'],e['title'].lower()))
def calendar(e):
    def esc(s):return s.replace('\\','\\\\').replace(';','\\;').replace(',','\\,').replace('\n','\\n')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//VivreAnyons//Cinema Nyons//FR','CALSCALE:GREGORIAN']
    f=e['film']
    for s in f['sessions']:
        start=datetime.fromisoformat(s['date']+'T'+s['time']).replace(tzinfo=ZoneInfo('Europe/Paris'))
        utc=start.astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
        lines+=['BEGIN:VEVENT','UID:'+slug(f['title'])+'-'+s['date']+'-'+s['time'].replace(':','')+'@agenda.vivreanyons.fr','DTSTAMP:'+datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ'),'DTSTART:'+utc,'SUMMARY:'+esc(f['title']+' — '+s['version']),'LOCATION:'+esc('28 place de la Libération, 26110 Nyons'),'DESCRIPTION:'+esc(f['description']+'\n'+e['page_url']),'URL:'+e['page_url'],'END:VEVENT']
    lines+=['END:VCALENDAR']
    # RFC 5545: fold long UTF-8 content lines without breaking encoded characters.
    folded=[]
    for line in lines:
        chunk=''
        for c in line:
            if len((chunk+c).encode('utf-8'))>73:folded.append(chunk);chunk=' '+c
            else:chunk+=c
        folded.append(chunk)
    return '\r\n'.join(folded)+'\r\n'

CSS='''*{box-sizing:border-box}body{margin:0;background:#f6f1e8;color:#262722;font:16px/1.7 Arial,sans-serif}a{color:#354622}.top{max-width:1180px;margin:auto;padding:15px 18px 0}.ad-shell{border-radius:16px;overflow:hidden;background:#fff}.ad-frame{display:block;width:100%;aspect-ratio:3/1;border:0}.ad-note{text-align:right;font-size:11px;color:#666}.wrap{max-width:1060px;margin:auto;padding:20px 18px 60px}.nav{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 18px}.nav a,.action{display:inline-block;border:1px solid #d8cfbf;padding:9px 14px;border-radius:24px;text-decoration:none;background:#fff;font-weight:700}.hero{background:linear-gradient(125deg,#354622,#566b3a);color:#fff;padding:35px;border-radius:22px}h1{font:700 clamp(28px,4vw,46px)/1.16 Georgia,serif;margin:8px 0 16px}.hero p{margin:0}.film-layout{display:grid;grid-template-columns:245px minmax(0,1fr);gap:25px;margin-top:25px}.poster{margin:0}.poster img{display:block;width:100%;height:auto;border-radius:12px}.poster figcaption{font-size:13px;padding:8px 0;color:#686b63}.section{background:#fffdf9;border:1px solid #e4dccd;border-radius:16px;padding:22px;margin-bottom:20px}.section h2{margin:0 0 12px;font:700 25px/1.2 Georgia,serif}.section p{margin:0 0 14px}.section p:last-child{margin:0}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse}caption{text-align:left;font-weight:700;padding-bottom:12px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #e4dccd}th{background:#e9eddc}td:nth-child(2){white-space:nowrap}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:15px}.note{color:#666;font-size:14px}.source{font-size:13px;color:#686b63}.qa{border-bottom:1px solid #e4dccd;padding:12px 0}.qa h3{margin:0 0 7px;font-size:18px}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.film-card{display:block;padding:16px;background:#fffdf9;border:1px solid #e4dccd;border-radius:16px;text-decoration:none}.film-card img{display:block;width:120px;max-width:100%;height:170px;object-fit:contain;margin:auto}.film-card h2{font-size:20px;line-height:1.3}.film-card p{font-size:14px}.archive{padding:12px;background:#f2e5df;border-radius:10px}.source a{overflow-wrap:anywhere}@media(max-width:750px){.film-layout{grid-template-columns:1fr}.poster{max-width:220px;margin:auto}.hero{padding:24px}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:480px){.cards{grid-template-columns:1fr}.wrap{padding:12px}.section{padding:16px}table{min-width:390px}}'''
def shell(title,description,canonical,body,ld=None,poster=None):
    esc=html.escape
    return '<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><meta name="description" content="'+esc(description,quote=True)+'"><meta name="robots" content="index,follow"><link rel="canonical" href="'+esc(canonical,quote=True)+'"><meta property="og:title" content="'+esc(title,quote=True)+'"><meta property="og:description" content="'+esc(description,quote=True)+'">'+('<meta property="og:image" content="'+esc(poster,quote=True)+'">' if poster else '')+'<style>'+CSS+'</style>'+('<script type="application/ld+json">'+json.dumps(ld,ensure_ascii=False).replace('</','<\\/')+'</script>' if ld else '')+'</head><body><aside class="top" aria-label="Sélection de livres sur Nyons"><div class="ad-shell"><iframe class="ad-frame" src="https://agenda.vivreanyons.fr/banniere-livres/" title="Voir ma sélection de vieux livres sur Nyons" loading="lazy"></iframe></div><div class="ad-note">Publicité · lien affilié</div></aside><main class="wrap"><nav class="nav"><a href="/">← Agenda de Nyons</a><a href="/cinema/">🎬 Tous les films</a><a href="/evenements/">Tous les événements</a><a href="/semaines/">Par semaine</a></nav>'+body+'</main></body></html>'

def render_film(e,config,today=None):
    today=today or paris_today();f=e['film'];esc=html.escape
    title=f['title']+' à Nyons : horaires au cinéma L’Arlequin'
    description=('Voir '+f['title']+' à Nyons : séances datées du '+fmt(e['start_date'])+' au '+fmt(e['end_date'])+', versions, tarifs et adresse du cinéma L’Arlequin.')
    qa=[('Où voir '+f['title']+' à Nyons ?','Au cinéma L’Arlequin, 28 place de la Libération, 26110 Nyons.'),('Quels sont les horaires des séances ?','Les dates et horaires de chaque séance figurent dans le tableau de cette fiche. Le programme couvre le '+fmt(config['period_start'])+' au '+fmt(config['period_end'])+'. Vérifie les éventuels changements sur cinema-arlequin.fr.'),('Comment réserver ou demander un renseignement ?','Consulte le site officiel de L’Arlequin ou téléphone au 04 75 26 01 41. Les animations avec réservation obligatoire sont précisées dans la fiche.')]
    schemas=[]
    for s in f['sessions']:
        start=datetime.fromisoformat(s['date']+'T'+s['time']).replace(tzinfo=ZoneInfo('Europe/Paris')).isoformat()
        schemas.append({'@type':'ScreeningEvent','name':f['title']+' — '+s['version'],'startDate':start,'eventStatus':'https://schema.org/EventScheduled','eventAttendanceMode':'https://schema.org/OfflineEventAttendanceMode','url':e['page_url'],'description':f['description'],'image':f['poster'],'workPresented':{'@type':'Movie','name':f['title']},'location':{'@type':'Place','name':'Cinéma L’Arlequin','address':{'@type':'PostalAddress','streetAddress':'28 place de la Libération','postalCode':'26110','addressLocality':'Nyons','addressCountry':'FR'}}})
    schemas.append({'@type':'FAQPage','mainEntity':[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in qa]})
    schemas.append({'@type':'BreadcrumbList','itemListElement':[{'@type':'ListItem','position':1,'name':'Agenda de Nyons','item':SITE},{'@type':'ListItem','position':2,'name':'Films à Nyons','item':SITE+'cinema/'},{'@type':'ListItem','position':3,'name':f['title'],'item':e['page_url']}]})
    rows=''.join('<tr><td>'+esc(fmt(s['date']))+'</td><td>'+esc(s['time'].replace(':',' h '))+'</td><td>'+esc(s['version'])+(' · 20 € pour la soirée' if s.get('price')==20 else '')+('</td></tr>') for s in f['sessions'])
    price=f.get('price_note') or (f"{f['price']:.2f} € la place pour tous.".replace('.',',') if 'price' in f else 'Plein tarif : 8 € ; réduit sur justificatif : 7,50 € ; enfant de moins de 14 ans : 6 €. Dix entrées : 56 €, valables un an et aussi à Vaison. Supplément 3D : 1 €.')
    body='<header class="hero"><span>🎬 CINÉMA À NYONS</span><h1>'+esc(f['title'])+' : séances à Nyons</h1><p>Au cinéma L’Arlequin · programme du '+esc(fmt(config['period_start']))+' au '+esc(fmt(config['period_end']))+'</p></header>'
    if e['end_date']<today.isoformat():body+='<p class="archive">Ce programme est terminé. Consulte les nouveaux films dans la rubrique cinéma.</p>'
    body+='<div class="film-layout"><figure class="poster"><img src="'+esc(f['poster'],quote=True)+'" alt="'+esc(f['poster_alt'],quote=True)+'" width="320" decoding="async" fetchpriority="high"><figcaption>Affiche de '+esc(f['title'])+'. Un coup d’œil, puis choisis ta séance.</figcaption></figure><div><section class="section"><h2>Le petit mot de Papy</h2><p>'+esc(f['description'])+'</p>'
    if f.get('age'):body+='<p><strong>'+esc(f['age'])+'</strong></p>'
    if f.get('duration'):body+='<p>Durée annoncée : '+esc(f['duration'])+'.</p>'
    if f.get('duration_note'):body+='<p class="note">'+esc(f['duration_note'])+'</p>'
    body+='</section><section class="section"><h2>Horaires de '+esc(f['title'])+' à Nyons</h2><div class="table-wrap"><table><caption>Les séances du programme — dates distinctes, selon le film</caption><thead><tr><th scope="col">Date</th><th scope="col">Heure</th><th scope="col">Version / animation</th></tr></thead><tbody>'+rows+'</tbody></table></div><p class="note">Les séances passées au fil du programme restent datées dans ce tableau. Pour réserver, choisis une séance à venir.</p></section><section class="section"><h2>Tarifs et réservation</h2><p>'+esc(price)+'</p>'
    if f.get('special_note'):body+='<p>'+esc(f['special_note'])+'</p>'
    body+='<p><a href="https://www.cinema-arlequin.fr/" target="_blank" rel="noopener">Voir les séances et la billetterie du cinéma</a> · <a href="tel:+33475260141">04 75 26 01 41</a></p></section></div></div><section class="section"><h2>Adresse du cinéma L’Arlequin</h2><p>28 place de la Libération, 26110 Nyons. Avant de venir, regarde <a href="https://www.vivreanyons.fr/infos-pratiques-nyons/ou-se-garer-a-Nyons/">où laisser la voiture près du centre</a>. Tu peux aussi choisir <a href="https://www.vivreanyons.fr/restaurants-de-nyons/">une table pour dîner</a> ou faire un tour dans <a href="https://www.vivreanyons.fr/que-faire-nyons/Vieilles-ruelles-de-Nyons/">les petites rues du vieux Nyons</a>.</p><div class="actions"><a class="action" href="evenement.ics" download>📅 Ajouter les séances à mon calendrier</a><a class="action" href="https://www.google.com/maps/dir/?api=1&amp;destination=Cinema+Arlequin%2C+28+place+de+la+Liberation%2C+26110+Nyons" target="_blank" rel="noopener">🗺️ Voir l’itinéraire</a></div></section><section class="section"><h2>Questions / réponses</h2>'+''.join('<div class="qa"><h3>'+esc(q)+'</h3><p>'+esc(a)+'</p></div>' for q,a in qa)+'</section><p class="source">Programme et affiche : <a href="https://www.cinema-arlequin.fr/" target="_blank" rel="noopener">cinéma L’Arlequin</a>. <a href="'+esc(config['source_pdf'],quote=True)+'" target="_blank" rel="noopener">Programme officiel en PDF</a> · <a href="https://www.vivreanyons.fr/infos-pratiques-nyons/cinema-nyons/">Le guide complet du cinéma de Nyons</a>. Programme vérifié le '+esc(fmt(config['verified_on']))+'.</p>'
    return shell(title,description,e['page_url'],body,{'@context':'https://schema.org','@graph':schemas},f['poster'])

def cards(events,today):
    out=[]
    for e in events:
        future=[s for s in e['sessions'] if s['date']>=today.isoformat()]
        if not future:continue
        f=e['film'];s=future[0]
        out.append('<a class="film-card" href="'+html.escape(e['page_url'],quote=True)+'"><img src="'+html.escape(f['poster'],quote=True)+'" alt="'+html.escape(f['poster_alt'],quote=True)+'" width="320" loading="lazy"><h2>'+html.escape(f['title'])+'</h2><p>Prochaine séance : '+fmt(s['date'])+' à '+s['time'].replace(':',' h ')+'</p><p>'+html.escape(f['description'])+'</p><strong>Voir les horaires →</strong></a>')
    return ''.join(out)

def generate_cinema_pages(today=None):
    today=today or paris_today();cfg=load_programme();events=[film_event(f) for f in cfg['films']]
    for e in events:
        folder=ROOT/e['page_url'].removeprefix(SITE);folder.mkdir(parents=True,exist_ok=True)
        (folder/'index.html').write_text(render_film(e,cfg,today),encoding='utf-8')
        (folder/'evenement.ics').write_text(calendar(e),encoding='utf-8',newline='')
        alias=alternate_path(e)
        if alias!=e['page_url'].removeprefix(SITE):
            alias_folder=ROOT/alias;alias_folder.mkdir(parents=True,exist_ok=True)
            target=html.escape(e['page_url'],quote=True)
            redirect='<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="robots" content="noindex,follow"><link rel="canonical" href="'+target+'"><meta http-equiv="refresh" content="0;url='+target+'"><title>'+html.escape(e['film_title'])+' à Nyons</title></head><body><p><a href="'+target+'">Voir la fiche et les horaires de '+html.escape(e['film_title'])+' à Nyons</a></p></body></html>'
            (alias_folder/'index.html').write_text(redirect,encoding='utf-8')
    active=sorted([e for e in events if e['end_date']>=today.isoformat()],key=lambda e:(next(s['date']+'T'+s['time'] for s in e['sessions'] if s['date']>=today.isoformat()),e['title']))
    body='<header class="hero"><h1>Cinéma à Nyons : films et horaires de L’Arlequin</h1><p>Un film, une fiche, toutes ses séances. Choisis ton affiche, puis regarde les dates et la version avant de partir.</p></header><section class="section" style="margin-top:22px"><h2>Le programme du moment</h2><p>Du '+fmt(cfg['period_start'])+' au '+fmt(cfg['period_end'])+'. Les films dont la dernière séance est passée ne figurent plus dans cette sélection.</p></section><section class="cards">'+cards(active,today)+'</section>'
    if not active:body+='<p class="archive">Le programme précédent est terminé. Consulte le site officiel de L’Arlequin en attendant la prochaine mise à jour.</p>'
    body+='<p class="source"><a href="https://www.cinema-arlequin.fr/">Programme officiel de L’Arlequin</a> · <a href="https://www.vivreanyons.fr/infos-pratiques-nyons/cinema-nyons/">Adresse et tarifs du cinéma de Nyons</a></p>'
    folder=ROOT/'cinema';folder.mkdir(exist_ok=True)
    (folder/'index.html').write_text(shell('Cinéma Nyons : films, séances et horaires de L’Arlequin','Les films à voir au cinéma L’Arlequin de Nyons : une fiche par film, affiches, séances VF et VO, horaires datés et tarifs.',SITE+'cinema/',body),encoding='utf-8')
    home=ROOT/'index.html'
    if home.exists():
        source=home.read_text(encoding='utf-8')
        block='<!-- CINEMA_FILMS_START --><section class="box"><h2>🎬 Les films à voir à Nyons</h2><p>Une affiche te plaît ? Ouvre sa fiche : Papy t’y a regroupé les séances, les versions et les petits repères utiles.</p><div class="cinema-home-cards">'+cards(active[:6],today)+'</div><p><a class="btn" href="/cinema/">Voir tous les films et leurs horaires →</a></p></section><!-- CINEMA_FILMS_END -->'
        if '<!-- CINEMA_FILMS_START -->' in source:source=re.sub(r'<!-- CINEMA_FILMS_START -->.*?<!-- CINEMA_FILMS_END -->',lambda _:block,source,flags=re.S)
        else:source=source.replace('<section class="box local">',block+'<section class="box local">',1)
        if '.cinema-home-cards{' not in source:source=source.replace('</style>','.cinema-home-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}.cinema-home-cards .film-card{display:block;padding:14px;background:#fff;border:1px solid #ddd;border-radius:14px;text-decoration:none}.cinema-home-cards img{width:120px;max-width:100%;height:170px;object-fit:contain;display:block;margin:auto}.cinema-home-cards h2{font-size:19px}.cinema-home-cards p{font-size:14px}@media(max-width:700px){.cinema-home-cards{grid-template-columns:1fr}}</style>',1)
        if 'href="/cinema/">🎬 Films' not in source:source=source.replace('<a class="btn" href="/semaines/">','<a class="btn" href="/cinema/">🎬 Films et séances de cinéma</a>\n      <a class="btn" href="/semaines/">',1)
        home.write_text(source,encoding='utf-8')
    return events
