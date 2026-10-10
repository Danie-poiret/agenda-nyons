"""Check all tracked HTML, local references, JSON-LD and sitemap signals."""
import json,html,os,sys
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,unquote
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
class Parse(HTMLParser):
    def __init__(self,s):
        super().__init__();self.refs=[];self.canonicals=[];self.robots=[];self.scripts=[];self.capture=False;self.buf=[];self.feed(s)
    def handle_starttag(self,t,attrs):
        a=dict(attrs)
        for k in ('href','src','poster'):
            if a.get(k):self.refs.append((k,a[k]))
        if t=='link' and a.get('rel')=='canonical':self.canonicals.append(a.get('href'))
        if t=='meta' and a.get('name','').lower()=='robots':self.robots.append(a.get('content',''))
        if t=='script' and a.get('type')=='application/ld+json':self.capture=True;self.buf=[]
    def handle_data(self,s):
        if self.capture:self.buf.append(s)
    def handle_endtag(self,t):
        if t=='script' and self.capture:self.scripts.append(''.join(self.buf));self.capture=False
def inspect(files,sources,host):
    files=set(files);errors=[];parsed={};refs=0;schemas=0
    for path,source in sources.items():
        if not path.endswith('.html'):continue
        p=Parse(source);parsed[path]=p
        for script in p.scripts:
            try:json.loads(script);schemas+=1
            except json.JSONDecodeError as e:errors.append(f'{path}: invalid JSON-LD: {e}')
        for attr,raw in p.refs:
            u=urlsplit(urljoin('https://'+host+'/'+path,html.unescape(raw)))
            if u.hostname not in {host,host.removeprefix('www.')}:continue
            refs+=1;target=unquote(u.path).lstrip('/')
            candidates=[target,target.rstrip('/')+'/index.html' if target else 'index.html']
            if not any(c in files for c in candidates):errors.append(f'{path}: missing {attr} target {raw}')
    urls=[n.text for n in ET.fromstring(sources['sitemap.xml']).findall('{*}url/{*}loc')]
    if len(urls)!=len(set(urls)):errors.append('Sitemap contains duplicate URLs')
    for url in urls:
        target=unquote(urlsplit(url).path).lstrip('/');target=target+'index.html' if not target or target.endswith('/') else target
        p=parsed.get(target)
        if urlsplit(url).hostname!=host:errors.append(f'Sitemap host differs: {url}')
        elif p is None:errors.append(f'Sitemap target missing: {url}')
        elif p.canonicals!=[url]:errors.append(f'Sitemap canonical differs: {url}: {p.canonicals}')
        elif any('noindex' in r.lower() for r in p.robots):errors.append(f'Noindex page in sitemap: {url}')
    return {'htmlPages':len(parsed),'localReferences':refs,'validJSONLD':schemas,'sitemapURLs':len(urls),'errors':errors}
def main():
    files=[]
    for folder,dirs,names in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.audit-tools','audit-output','__pycache__','.venv'}]
        files.extend((Path(folder)/n).relative_to(ROOT).as_posix() for n in names)
    sources={p:(ROOT/p).read_text(encoding='utf-8') for p in files if p.endswith('.html') or p=='sitemap.xml'}
    host=(ROOT/'CNAME').read_text(encoding='utf-8').strip();result=inspect(files,sources,host)
    print(json.dumps(result,ensure_ascii=True,indent=2));raise SystemExit(bool(result['errors']))
if __name__=='__main__':main()
