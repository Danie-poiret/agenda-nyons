#!/usr/bin/env python3
"""Récupère l'agenda public de la Ville de Nyons et génère agenda.json.
Le script ne contourne aucune authentification et limite volontairement le nombre de requêtes.
"""
from __future__ import annotations
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.nyons.com/sorties-actus/agenda/"
OUT = Path(__file__).with_name("agenda.json")
MAX_PAGES = 15
TIMEOUT = 25

MONTHS = {
    "janvier":1,"février":2,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"août":8,"aout":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12,"decembre":12,
}
WEEKDAYS = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
MONTH_RE = r"(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)"
DATE_RE = re.compile(rf"(?:{WEEKDAYS}\s+)?(\d{{1,2}})\s+({MONTH_RE})\s+(20\d{{2}})", re.I)
UNTIL_RE = re.compile(rf"Jusqu['’]au\s+(?:{WEEKDAYS}\s+)?(\d{{1,2}})\s+({MONTH_RE})\s+(20\d{{2}})", re.I)

CATEGORIES = [
    "Administratif","Cadre de vie","Enfance / Jeunesse","Patrimoine / Culture vivante",
    "Solidarité / Santé","Sport / Loisirs","Vie associative","Citoyenneté","Culture","Loisirs"
]

HEADERS={
    "User-Agent":"Mozilla/5.0 (compatible; AgendaNyons/1.0; +https://github.com/)",
    "Accept-Language":"fr-FR,fr;q=0.9,en;q=0.5",
}

def clean(s:str)->str:
    return re.sub(r"\s+"," ",s or "").strip()

def parse_match(m:re.Match):
    d=int(m.group(1)); month=MONTHS[m.group(2).lower()]; y=int(m.group(3))
    return f"{y:04d}-{month:02d}-{d:02d}"

def is_event_url(href:str)->bool:
    p=urlparse(href).path.rstrip("/")
    if p in ("/agenda","/sorties-actus/agenda"): return False
    return p.startswith("/agenda/") or p.startswith("/sorties-actus/agenda/")

def smallest_card(anchor):
    """Trouve le plus petit conteneur parent qui contient à la fois le titre et une date."""
    for parent in anchor.parents:
        if getattr(parent,"name",None) not in {"article","li","div","section"}: continue
        txt=clean(parent.get_text(" ",strip=True))
        if len(txt)>3500: break
        if DATE_RE.search(txt): return parent
    return None

def extract_summary(card, anchor, title):
    heading=anchor.find_parent(["h1","h2","h3","h4","h5"])
    if heading:
        for sib in heading.find_all_next("p",limit=4):
            if card not in sib.parents and sib is not card: break
            t=clean(sib.get_text(" ",strip=True))
            if len(t)>=18 and title.lower() not in t.lower(): return t[:420]
    for p in card.find_all("p"):
        t=clean(p.get_text(" ",strip=True))
        if len(t)>=18 and title.lower() not in t.lower(): return t[:420]
    return ""

def scrape_page(session, page:int):
    url=BASE if page==1 else f"{BASE}?_pagination={page}"
    r=session.get(url,headers=HEADERS,timeout=TIMEOUT)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    found=[]
    seen=set()
    for a in soup.find_all("a",href=True):
        href=urljoin(BASE,a["href"])
        if not is_event_url(href): continue
        title=clean(a.get_text(" ",strip=True))
        if len(title)<4 or title.lower() in {"retour","lire plus","voir l'événement","voir l’événement"}: continue
        href=href.split("#",1)[0].split("?",1)[0]
        if href in seen: continue
        card=smallest_card(a)
        if card is None: continue
        text=clean(card.get_text(" ",strip=True))
        dm=DATE_RE.search(text)
        if not dm: continue
        start=parse_match(dm)
        em=UNTIL_RE.search(text)
        end=parse_match(em) if em else start
        summary=extract_summary(card,a,title)
        cats=[c for c in CATEGORIES if c.lower() in text.lower()]
        found.append({"title":title,"start_date":start,"end_date":end,"summary":summary,"categories":cats,"url":href})
        seen.add(href)
    return found

def main():
    session=requests.Session()
    all_events={}
    stagnant=0
    for page in range(1,MAX_PAGES+1):
        try:
            events=scrape_page(session,page)
        except Exception as exc:
            print(f"Page {page}: erreur: {exc}",file=sys.stderr)
            if page==1: raise
            break
        before=len(all_events)
        for e in events: all_events[e["url"]]=e
        added=len(all_events)-before
        print(f"Page {page}: {len(events)} éléments, {added} nouveaux")
        stagnant = stagnant+1 if added==0 else 0
        if stagnant>=2: break
        time.sleep(.6)

    events=sorted(all_events.values(),key=lambda e:(e["start_date"],e["title"].lower()))
    if len(events)<3:
        raise RuntimeError(f"Extraction suspecte: seulement {len(events)} événements. agenda.json n'est pas remplacé.")

    payload={
        "source":BASE,
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "count":len(events),
        "events":events,
    }
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(events)} événements écrits dans {OUT.name}")

if __name__=="__main__":
    main()
