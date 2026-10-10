"""Stable sitemap dates, based on changes to final HTML rather than the run date."""
import hashlib,json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parent
SITE='https://agenda.vivreanyons.fr/'
STATE='seo-page-state.json'

def page_hash(source):
    # Insignificant formatting changes should not announce new editorial content.
    source=re.sub(r'>\s+<','><',source.strip())
    return hashlib.sha256(source.encode('utf-8')).hexdigest()

class PageFlags(HTMLParser):
    def __init__(self,source):
        super().__init__();self.noindex=False;self.events=0;self.feed(source)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta' and a.get('name','').lower()=='robots' and 'noindex' in a.get('content','').lower():self.noindex=True
        if tag=='article' and 'event' in a.get('class','').split():self.events+=1
def eligible(path,source):
    flags=PageFlags(source)
    if flags.noindex:return False
    if path.startswith('semaines/semaine-') and not flags.events:return False
    return True

def build(sources,old_state,today):
    candidates=['index.html','semaines/index.html','evenements/index.html','cinema/index.html','aujourdhui/index.html']
    candidates+=sorted(p for p in sources if p.startswith('semaines/semaine-') and p.endswith('/index.html'))
    candidates+=sorted(p for p in sources if p.startswith('evenements/') and p not in candidates and p.endswith('/index.html'))
    state={'version':1,'pages':{}};entries=[]
    for path in dict.fromkeys(candidates):
        if path not in sources:continue
        source=sources[path];digest=page_hash(source);previous=old_state.get('pages',{}).get(path)
        # Unknown historical dates are omitted, never invented from a shallow checkout.
        lastmod=previous.get('lastmod') if previous and previous.get('hash')==digest else today if previous else None
        state['pages'][path]={'hash':digest,'lastmod':lastmod}
        if not eligible(path,source):continue
        url=SITE+path.removesuffix('index.html')
        date_node='<lastmod>'+lastmod+'</lastmod>' if lastmod else ''
        entries.append('  <url><loc>'+escape(url)+'</loc>'+date_node+'</url>')
    sitemap='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+'\n'.join(entries)+'\n</urlset>\n'
    return sitemap,state

def update(root=ROOT):
    root=Path(root);sources={p.relative_to(root).as_posix():p.read_text(encoding='utf-8') for p in root.rglob('index.html') if '.git' not in p.parts}
    file=root/STATE;state=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    sitemap,state=build(sources,state,datetime.now(ZoneInfo('Europe/Paris')).date().isoformat())
    (root/'sitemap.xml').write_text(sitemap,encoding='utf-8');file.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Agenda sitemap: {sitemap.count("<loc>")} indexable URLs; only verified modification dates emitted.')
if __name__=='__main__':update()
