"""Current event selection shared by the existing agenda generators. No network or AI."""
from datetime import datetime
from zoneinfo import ZoneInfo

def clock(now=None):
    return (now or datetime.now(ZoneInfo('Europe/Paris'))).astimezone(ZoneInfo('Europe/Paris'))

def sessions(e,now=None):
    key=clock(now).strftime('%Y-%m-%dT%H:%M')
    return sorted((s for s in e.get('sessions',[]) if s['date']+'T'+s['time']>=key),key=lambda s:s['date']+s['time'])

def upcoming(e,now=None):
    day=clock(now).date().isoformat()
    if e.get('date_warning'):return False
    if e.get('kind')=='cinema':return bool(sessions(e,now))
    last=e.get('end_date') or e.get('start_date','')
    if last==day and e.get('end_time'):return e['end_time']>=clock(now).strftime('%H:%M')
    return last>=day

def next_key(e,now=None):
    day=clock(now).date().isoformat()
    if e.get('kind')=='cinema':
        s=sessions(e,now);return s[0]['date']+'T'+s[0]['time'] if s else '9999'
    return max(e['start_date'],day)+'T'+e.get('start_time','00:00')

def select(events,now=None):
    seen=set();out=[]
    for e in events:
        key=e.get('page_url') or e.get('url') or (e['title'],e['start_date'])
        if key in seen or not upcoming(e,now):continue
        seen.add(key);out.append(e)
    return sorted(out,key=lambda e:(next_key(e,now),e['title'].lower()))

def week_key(e,start):
    from datetime import timedelta
    first=start.isoformat();last=(start+timedelta(days=6)).isoformat()
    ss=sorted((s for s in e.get('sessions',[]) if first<=s['date']<=last),key=lambda s:s['date']+s['time'])
    return ss[0]['date']+'T'+ss[0]['time'] if ss else max(first,e['start_date'])+'T'+e.get('start_time','00:00')

def enrich(events,detail_cache,event_cache):
    import re
    months={'janvier':1,'février':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12}
    pattern=r'(\d{1,2}) ('+'|'.join(months)+r') (20\d{2})'
    for e in events:
        if e.get('kind')=='cinema':continue
        cached=event_cache.get(e.get('url'),{});p=detail_cache.get(e.get('url'),{}).get('practical') or cached.get('practical') or {}
        e['practical']=p
        if cached.get('slug'):e['page_url']='https://agenda.vivreanyons.fr/evenements/'+cached['slug']+'/'
        times=re.findall(r'(\d{1,2})\s*h\s*(\d{2})',p.get('date_time',''))
        if times:e['start_time']=times[0][0].zfill(2)+':'+times[0][1]
        if len(times)>1:e['end_time']=times[-1][0].zfill(2)+':'+times[-1][1]
        if p.get('date_time'):e['date_label']=p['date_time']
        e.pop('date_warning',None)
        m=re.search(pattern,p.get('date_time',''),re.I)
        if m:
            day=f'{int(m[3]):04d}-{months[m[2].lower()]:02d}-{int(m[1]):02d}'
            if not e['start_date']<=day<=(e.get('end_date') or e['start_date']):
                e['date_warning']='Date à confirmer : les données de calendrier et le texte de cette fiche se contredisent. Vérifiez auprès de l’organisateur.'
        if e.get('date_warning'):print('DATE A CONFIRMER — '+e['title'])
    return events
