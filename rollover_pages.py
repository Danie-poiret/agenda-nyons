"""Keep dated archives clear and current selections independent of the daily scrape."""
import re
from datetime import date, timedelta
from pathlib import Path
from cinema_agenda import paris_today

SCRIPT = '<script src="/assets/agenda-current.js" defer></script>'
MONTHS = ['janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre']

def week_start(slug):
    m = re.fullmatch(r'semaine-(\d+)-([a-z]+)-(\d+)', slug)
    return date(int(m[3]), MONTHS.index(m[2])+1, int(m[1])) if m else None

def install_page(source, path, today=None):
    today = today or paris_today()
    monday = today - timedelta(days=today.weekday())
    path = str(path).replace('\\','/')
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
    return source

def install_live_agenda(root=None):
    root = Path(root or __file__).resolve()
    if root.is_file(): root = root.parent
    paths = [root/'index.html',root/'semaines/index.html',root/'evenements/index.html',root/'cinema/index.html']
    paths += list((root/'semaines').glob('semaine-*/index.html'))
    for p in paths:
        if p.exists(): p.write_text(install_page(p.read_text(encoding='utf-8'),p.relative_to(root)),encoding='utf-8')

if __name__ == '__main__': install_live_agenda()
