#!/usr/bin/env python3
"""Agenda automatique de Nyons + pages SEO hebdomadaires.

- Récupère l'agenda public de la Ville de Nyons.
- Met à jour agenda.json.
- Génère des pages HTML semaine par semaine dans /semaines/.
- Génère les 50 prochains événements dans /evenements/ avec une fiche éditoriale par événement.
- Utilise OpenAI uniquement si OPENAI_API_KEY est disponible.
- Ne rappelle l'API que lorsqu'une semaine change.
- En cas d'échec de l'API, la publication continue avec un texte de secours.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

BASE = "https://www.nyons.com/sorties-actus/agenda/"
SITE = "https://agenda.vivreanyons.fr/"
BANNER_URL = "https://danie-poiret.github.io/banniere-nyons/"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "agenda.json"
WEEKS_DIR = ROOT / "semaines"
EVENTS_DIR = ROOT / "evenements"
CACHE_FILE = ROOT / "_seo_cache.json"
EVENT_CACHE_FILE = ROOT / "_event_seo_cache.json"
EVENT_DETAIL_CACHE_FILE = ROOT / "_event_detail_cache.json"
SITEMAP = ROOT / "sitemap.xml"
ROBOTS = ROOT / "robots.txt"

MAX_PAGES = 15
TIMEOUT = 25
SEO_WEEKS_AHEAD = 12
ROLLING_EVENT_LIMIT = 50
EVENT_DETAIL_TTL_HOURS = 48
MAX_EVENT_AI_CALLS = int(os.getenv("MAX_EVENT_AI_CALLS", "50"))
EVENT_PROMPT_VERSION = 4
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")

MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}
MONTH_NAMES = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai",
    6: "juin", 7: "juillet", 8: "août", 9: "septembre",
    10: "octobre", 11: "novembre", 12: "décembre",
}
WEEKDAYS = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
MONTH_RE = r"(?:janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)"
DATE_RE = re.compile(rf"(?:{WEEKDAYS}\s+)?(\d{{1,2}})\s+({MONTH_RE})\s+(20\d{{2}})", re.I)
UNTIL_RE = re.compile(rf"Jusqu['’]au\s+(?:{WEEKDAYS}\s+)?(\d{{1,2}})\s+({MONTH_RE})\s+(20\d{{2}})", re.I)

CATEGORIES = [
    "Administratif", "Cadre de vie", "Enfance / Jeunesse",
    "Patrimoine / Culture vivante", "Solidarité / Santé",
    "Sport / Loisirs", "Vie associative", "Citoyenneté", "Culture", "Loisirs",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_match(m: re.Match) -> str:
    d = int(m.group(1))
    month = MONTHS[m.group(2).lower()]
    y = int(m.group(3))
    return f"{y:04d}-{month:02d}-{d:02d}"


def parse_iso(s: str) -> date:
    return date.fromisoformat(s)


def is_event_url(href: str) -> bool:
    p = urlparse(href).path.rstrip("/")
    if p in ("/agenda", "/sorties-actus/agenda"):
        return False
    return p.startswith("/agenda/") or p.startswith("/sorties-actus/agenda/")


def date_from_match(m: re.Match) -> str:
    """Convertit un match DATE_RE / UNTIL_RE en date ISO."""
    return parse_match(m)


def page_event_headings(soup):
    """Retourne uniquement les vrais titres d'événements de la liste."""
    items = []
    seen = set()

    for h2 in soup.find_all("h2"):
        a = h2.find("a", href=True)
        if not a:
            continue

        href = urljoin(BASE, a["href"])
        if not is_event_url(href):
            continue

        href = href.split("#", 1)[0].split("?", 1)[0]
        title = clean(a.get_text(" ", strip=True))

        if len(title) < 4 or href in seen:
            continue

        items.append((title, href))
        seen.add(href)

    return items


def find_title_positions(page_text: str, items):
    """Repère les titres dans le texte complet en conservant l'ordre de la page."""
    located = []
    cursor = 0

    for title, href in items:
        pos = page_text.find(title, cursor)
        if pos < 0:
            pos = page_text.find(title)
        if pos < 0:
            print(f"Titre introuvable dans le texte: {title}", file=sys.stderr)
            continue

        located.append((title, href, pos))
        cursor = pos + len(title)

    return located


def is_until_match(text: str, match: re.Match) -> bool:
    """Vrai si la date trouvée appartient à une mention Jusqu'au."""
    left = text[max(0, match.start() - 35):match.start()].lower()
    return bool(re.search(r"jusqu['’]au\s*$", left))


def extract_start_from_before(segment: str):
    """Prend la dernière vraie date située juste avant le titre."""
    matches = [
        m for m in DATE_RE.finditer(segment)
        if not is_until_match(segment, m)
    ]
    if not matches:
        return None
    return date_from_match(matches[-1])


def extract_end_and_summary(segment: str, start_iso: str):
    """Extrait le résumé et une éventuelle date de fin après le titre."""
    end = start_iso

    em = UNTIL_RE.search(segment)
    if em:
        end = date_from_match(em)

    cut_positions = []

    if em:
        cut_positions.append(em.start())

    next_date = DATE_RE.search(segment)
    if next_date:
        cut_positions.append(next_date.start())

    summary_part = segment[:min(cut_positions)] if cut_positions else segment
    summary_part = clean(summary_part)

    for c in CATEGORIES:
        if summary_part.lower().startswith(c.lower()):
            summary_part = clean(summary_part[len(c):].lstrip(" ,·-"))

    return end, summary_part[:420]


def scrape_page(session, page: int):
    url = BASE if page == 1 else f"{BASE}?_pagination={page}"
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    items = page_event_headings(soup)

    page_text = clean(soup.get_text(" ", strip=True))
    located = find_title_positions(page_text, items)

    print(
        f"Page {page}: HTTP {r.status_code}, {len(r.text)} octets, "
        f"{len(items)} titre(s) H2 événement(s)"
    )

    found = []

    for i, (title, href, pos) in enumerate(located):
        prev_boundary = 0 if i == 0 else located[i - 1][2] + len(located[i - 1][0])
        next_boundary = len(page_text) if i + 1 == len(located) else located[i + 1][2]

        before = page_text[prev_boundary:pos]
        start = extract_start_from_before(before)

        if not start:
            print(f"Page {page}: date de début introuvable pour {title}", file=sys.stderr)
            continue

        after = page_text[pos + len(title):next_boundary]
        end, summary = extract_end_and_summary(after, start)

        cats = [
            c for c in CATEGORIES
            if c.lower() in before.lower()
        ]

        found.append({
            "title": title,
            "start_date": start,
            "end_date": end,
            "summary": summary,
            "categories": cats,
            "url": href,
        })

    return found


def scrape_all():
    session = requests.Session()
    all_events = {}
    stagnant = 0

    for page in range(1, MAX_PAGES + 1):
        try:
            events = scrape_page(session, page)
        except Exception as exc:
            print(f"Page {page}: erreur: {exc}", file=sys.stderr)
            if page == 1:
                raise
            break

        before_count = len(all_events)
        for e in events:
            all_events[e["url"]] = e

        added = len(all_events) - before_count
        print(f"Page {page}: {len(events)} événements extraits, {added} nouveaux")

        stagnant = stagnant + 1 if added == 0 else 0
        if stagnant >= 2:
            break

        time.sleep(0.6)

    events = sorted(
        all_events.values(),
        key=lambda e: (e["start_date"], e["title"].lower())
    )

    if len(events) < 3:
        raise RuntimeError(
            f"Extraction suspecte: seulement {len(events)} événements. "
            "agenda.json n'est pas remplacé."
        )

    print(f"TOTAL: {len(events)} événements uniques extraits.")
    print("Premiers événements extraits:")
    for e in events[:15]:
        print(f" - {e['start_date']} -> {e['end_date']} | {e['title']}")

    return events

def write_agenda(events):
    payload = {
        "source": BASE,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(events),
        "events": events,
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    tmp.replace(OUT)
    print(f"OK: {len(events)} événements écrits dans {OUT.name}")


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def french_date(d: date) -> str:
    return f"{d.day} {MONTH_NAMES[d.month]} {d.year}"


def week_label(start: date) -> str:
    end = start + timedelta(days=6)
    if start.year == end.year:
        if start.month == end.month:
            return f"du {start.day} au {end.day} {MONTH_NAMES[end.month]} {end.year}"
        return (
            f"du {start.day} {MONTH_NAMES[start.month]} "
            f"au {end.day} {MONTH_NAMES[end.month]} {end.year}"
        )
    return (
        f"du {french_date(start)} au {french_date(end)}"
    )


def slug_week(start: date) -> str:
    month = MONTH_NAMES[start.month]
    month = (
        month.replace("é", "e")
        .replace("û", "u")
        .replace("ô", "o")
        .replace("à", "a")
    )
    return f"semaine-{start.day}-{month}-{start.year}"


def event_weeks(event):
    start = parse_iso(event["start_date"])
    end = parse_iso(event["end_date"])
    w = monday_of(start)
    last = monday_of(end)
    while w <= last:
        yield w
        w += timedelta(days=7)


def group_weeks(events):
    today = date.today()
    first = monday_of(today)
    last = first + timedelta(days=7 * (SEO_WEEKS_AHEAD - 1))
    weeks = {}

    for event in events:
        for w in event_weeks(event):
            if first <= w <= last:
                weeks.setdefault(w, []).append(event)

    for w in weeks:
        weeks[w] = sorted(
            weeks[w],
            key=lambda e: (e["start_date"], e["title"].lower())
        )
    return dict(sorted(weeks.items()))


def safe_summary_for_ai(text: str) -> str:
    text = clean(text)
    return text[:260]


def event_facts_for_ai(events):
    facts = []
    for e in events:
        facts.append({
            "title": e["title"],
            "start_date": e["start_date"],
            "end_date": e["end_date"],
            "categories": e["categories"],
            "summary_source": safe_summary_for_ai(e.get("summary", "")),
            "official_url": e["url"],
        })
    return facts


def week_hash(start: date, events):
    payload = {
        "week": start.isoformat(),
        "events": event_facts_for_ai(events),
        "prompt_version": 3,
        "model": OPENAI_MODEL,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache):
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def load_json_file(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json_file(path: Path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def slugify(text: str, max_len=82) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.encode("ascii", "ignore").decode("ascii").lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return (raw[:max_len].rstrip("-") or "evenement")


def event_slug(event) -> str:
    return f"{slugify(event['title'])}-{event['start_date']}"


def event_local_url(event) -> str:
    return f"{SITE}evenements/{event_slug(event)}/"


def event_page_path(event) -> Path:
    return EVENTS_DIR / event_slug(event) / "index.html"


def event_status(event) -> str:
    today = date.today()
    start = parse_iso(event["start_date"])
    end = parse_iso(event["end_date"])
    if today < start:
        return "À venir"
    if start <= today <= end:
        return "En cours"
    return "Événement terminé"


def rolling_events(events):
    today = date.today()
    future = [e for e in events if parse_iso(e["end_date"]) >= today]
    return sorted(
        future,
        key=lambda e: (e["start_date"], e["title"].lower()),
    )[:ROLLING_EVENT_LIMIT]


def event_facts(event, detail_text="", practical=None):
    practical = practical or {}
    return {
        "title": event["title"],
        "start_date": event["start_date"],
        "end_date": event["end_date"],
        "categories": event.get("categories") or [],
        "summary_source": clean(event.get("summary", ""))[:700],
        "detail_source": clean(detail_text)[:4200],
        "practical": {
            "date_time": clean(practical.get("date_time", "")),
            "location_name": clean(practical.get("location_name", "")),
            "address": clean(practical.get("address", "")),
            "phone": clean(practical.get("phone", "")),
            "email": clean(practical.get("email", "")),
            "website": clean(practical.get("website", "")),
        },
        "official_url": event["url"],
    }


def event_hash(event, detail_text="", practical=None):
    payload = {
        "event": event_facts(event, detail_text, practical),
        "prompt_version": EVENT_PROMPT_VERSION,
        "model": OPENAI_MODEL,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def detail_cache_fresh(entry) -> bool:
    stamp = entry.get("fetched_at")
    if not stamp:
        return False
    try:
        fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - fetched.astimezone(timezone.utc)
        return age <= timedelta(hours=EVENT_DETAIL_TTL_HOURS)
    except Exception:
        return False


def _jsonld_objects(soup):
    """Retourne les objets JSON-LD présents dans la fiche."""
    objects = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, dict):
                objects.append(obj)
                graph = obj.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
            elif isinstance(obj, list):
                stack.extend(obj)
    return objects


def extract_event_detail_data(html_text: str, source_url: str):
    """
    Extrait uniquement le bloc de l'événement :
    dates/horaires, lieu, adresse, téléphone, email et site organisateur.
    Évite les blocs 'événements similaires', abonnement et coordonnées mairie.
    """
    soup = BeautifulSoup(html_text, "html.parser")

    practical = {
        "date_time": "",
        "location_name": "",
        "address": "",
        "phone": "",
        "email": "",
        "website": "",
    }

    # JSON-LD Event si disponible.
    json_event = {}
    for obj in _jsonld_objects(soup):
        obj_type = obj.get("@type")
        types = obj_type if isinstance(obj_type, list) else [obj_type]
        if "Event" in types:
            json_event = obj
            break

    location = json_event.get("location")
    if isinstance(location, dict):
        practical["location_name"] = clean(location.get("name", ""))
        address = location.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("streetAddress"),
                address.get("postalCode"),
                address.get("addressLocality"),
            ]
            practical["address"] = clean(" ".join(str(x) for x in parts if x))
        elif isinstance(address, str):
            practical["address"] = clean(address)

    # Nettoyage du DOM.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup

    raw_lines = [clean(x) for x in root.get_text("\n", strip=True).splitlines()]
    lines = [x for x in raw_lines if x]

    # Coupe AVANT les recommandations / abonnement / pied de page.
    stop_markers = (
        "ces événements pourraient vous intéresser",
        "ces evenements pourraient vous interesser",
        "abonnement aux informations",
        "recevez les dernières actualités",
        "recevez les dernieres actualites",
        "mairie de nyons",
    )

    event_lines = []
    started = False

    for line in lines:
        low = line.lower()

        # Commence au H1 / titre de fiche, ou à défaut au premier contenu daté.
        if not started:
            if soup.find("h1") and clean(soup.find("h1").get_text(" ", strip=True)) == line:
                started = True
            elif re.search(r"\b20\d{2}\b", line):
                started = True

        if not started:
            continue

        if any(marker in low for marker in stop_markers):
            break

        event_lines.append(line)

    # Sécurité : si le découpage a raté, prend seulement les premières lignes utiles.
    if len(event_lines) < 3:
        event_lines = lines[:80]

    joined = "\n".join(event_lines)

    # 1) Date + horaires complets.
    date_candidates = []
    for line in event_lines:
        low = line.lower()
        has_month = any(month in low for month in MONTHS)
        has_year = bool(re.search(r"\b20\d{2}\b", line))
        has_time = bool(re.search(r"\b\d{1,2}\s*h\s*\d{2}\b", low))
        looks_range = low.startswith("du ") or low.startswith("le ") or " au " in low

        if has_month and has_year and has_time and looks_range:
            date_candidates.append(line)

    if date_candidates:
        practical["date_time"] = max(date_candidates, key=len)[:320]

    # 2) Lieu + adresse.
    address_line = ""
    for line in event_lines:
        if re.search(r"\b26110\b", line) and re.search(r"\bnyons\b", line, re.I):
            address_line = line
            break

    if address_line:
        # Cas réel Nyons :
        # "Maison ... - 40 place de la Libération, 26110 Nyons"
        if " - " in address_line:
            left, right = address_line.split(" - ", 1)
            if not practical["location_name"]:
                practical["location_name"] = clean(left)
            if not practical["address"]:
                practical["address"] = clean(right)
        else:
            if not practical["address"]:
                practical["address"] = clean(address_line)

    # 3) Email : priorité au TEXTE visible, car le mailto du site Nyons
    # peut être un lien de partage sans l'adresse dans href.
    m = re.search(
        r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
        joined,
        re.I,
    )
    if m:
        practical["email"] = clean(m.group(0))

    # 4) Téléphone : cherche uniquement AVANT la zone recommandations/mairie.
    phone_matches = re.findall(
        r"(?<!\d)(?:\+33\s*[1-9]|0[1-9])(?:[\s.\-]*\d{2}){4}(?!\d)",
        joined,
    )
    if phone_matches:
        practical["phone"] = clean(phone_matches[0])

    # 5) Site organisateur externe.
    # On filtre nyons.com, réseaux sociaux et liens techniques.
    blocked = (
        "nyons.com", "facebook.com", "instagram.com",
        "twitter.com", "x.com", "youtube.com", "6tematik.fr",
    )

    # Domaines visibles dans le bloc événement : très fiable.
    visible_urls = re.findall(
        r"https?://[^\s<>\"]+",
        joined,
        re.I,
    )
    for candidate in visible_urls:
        candidate = candidate.rstrip(").,;]")
        parsed = urlparse(candidate)
        host = parsed.netloc.lower()
        if not host:
            continue
        if any(host == b or host.endswith("." + b) for b in blocked):
            continue
        practical["website"] = candidate
        break

    # Si le texte rendu ne contient pas l'URL brute, cherche dans les <a>.
    if not practical["website"]:
        for a in soup.find_all("a", href=True):
            href = clean(a.get("href", ""))
            label = clean(a.get_text(" ", strip=True))

            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue

            absolute = urljoin(source_url, href)
            parsed = urlparse(absolute)
            host = parsed.netloc.lower()

            if parsed.scheme not in ("http", "https"):
                continue
            if any(host == b or host.endswith("." + b) for b in blocked):
                continue

            # Évite PDF / documents et liens sans rapport.
            if parsed.path.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")):
                continue

            # Préfère les liens dont le libellé ressemble à une URL/site.
            if "http" in label.lower() or "." in label:
                practical["website"] = absolute
                break

    # Texte destiné à GPT = uniquement le bloc événement, sans recommandations ni mairie.
    detail_text = clean(" ".join(event_lines))[:5200]

    return {
        "text": detail_text,
        "practical": {k: clean(v) for k, v in practical.items()},
    }


def get_event_detail(session, event, detail_cache):
    key = event["url"]
    cached = detail_cache.get(key, {})

    cached_practical = cached.get("practical") or {}
    practical_complete_enough = (
        isinstance(cached_practical, dict)
        and bool(cached_practical.get("date_time"))
        and bool(cached_practical.get("address"))
        and bool(cached_practical.get("phone"))
    )

    if (
        cached.get("text")
        and detail_cache_fresh(cached)
        and practical_complete_enough
    ):
        return {
            "text": cached.get("text", ""),
            "practical": cached_practical,
        }

    try:
        r = session.get(event["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()

        data = extract_event_detail_data(r.text, event["url"])
        detail = data.get("text", "")
        practical = data.get("practical") or {}

        if len(detail) < 80:
            detail = clean(event.get("summary", ""))

        detail_cache[key] = {
            "text": detail,
            "practical": practical,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        time.sleep(0.12)

        return {
            "text": detail,
            "practical": practical,
        }

    except Exception as exc:
        print(
            f"Détail {event['title']}: erreur ({exc}), résumé de liste utilisé.",
            file=sys.stderr,
        )
        return {
            "text": cached.get("text") or clean(event.get("summary", "")),
            "practical": cached.get("practical") or {},
        }


def fallback_event_editorial(event):
    title = event["title"]
    when = format_event_date(event)
    summary = clean(event.get("summary", ""))

    if summary:
        intro = (
            f"{title} est annoncé à Nyons {when}. "
            f"{summary} "
            "Cette fiche rassemble les informations utiles disponibles afin de retrouver rapidement "
            "ce rendez-vous sans parcourir l'ensemble de l'agenda."
        )
    else:
        intro = (
            f"{title} est annoncé à Nyons {when}. "
            "Cette fiche rassemble les éléments factuels actuellement disponibles pour préparer la sortie "
            "et retrouver facilement la source officielle."
        )

    return {
        "seo_title": f"{title} à Nyons",
        "meta_description": trim_meta(
            f"{title} à Nyons : {when}. Dates, informations pratiques et source officielle de l'événement."
        ),
        "intro": intro,
        "story": (
            "L'intérêt de cette page est de remettre les informations essentielles dans leur contexte "
            "sans ajouter de détails non publiés. Le titre, la période et les éléments de la fiche source "
            "permettent déjà de situer clairement le rendez-vous dans l'agenda de Nyons."
        ),
        "why_it_matters": (
            "Pour choisir une sortie, les informations les plus utiles sont souvent très simples : "
            "la date, le lieu, la durée et les conditions pratiques. Cette fiche les regroupe afin de "
            "faciliter la décision avant de consulter, si besoin, la source officielle."
        ),
        "practical": (
            "Avant le déplacement, vérifiez les horaires, tarifs, conditions d'accès ou éventuelles "
            "modifications sur la fiche officielle lorsqu'ils ne sont pas explicitement indiqués ici."
        ),
        "reader_question": f"Qu'est-ce qui vous attire le plus dans « {title} » ?",
        "_fallback": True,
    }


def generate_event_editorial(event, detail_text, practical=None):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        print(f"Événement {event['title']}: OpenAI indisponible, texte de secours.")
        return fallback_event_editorial(event)

    schema = {
        "type": "object",
        "properties": {
            "seo_title": {"type": "string"},
            "meta_description": {"type": "string"},
            "intro": {"type": "string"},
            "story": {"type": "string"},
            "why_it_matters": {"type": "string"},
            "practical": {"type": "string"},
            "reader_question": {"type": "string"},
        },
        "required": [
            "seo_title", "meta_description", "intro", "story",
            "why_it_matters", "practical", "reader_question",
        ],
        "additionalProperties": False,
    }

    facts = event_facts(event, detail_text, practical)
    system = (
        "Tu écris pour Vivre à Nyons comme un chroniqueur local expérimenté. "
        "Le propriétaire du site appelle ce ton 'à la Papy' : chaleureux, direct, vivant, "
        "avec une vraie intelligence locale, mais jamais bavard pour remplir. "
        "Avant d'écrire, identifie mentalement CE QUI REND CET ÉVÉNEMENT PARTICULIER : "
        "son lieu, sa période, sa durée, son thème, son organisation, ses horaires, "
        "son caractère sportif, culturel, associatif ou pratique. "
        "Commence par l'angle le plus intéressant, pas par une formule générale sur Nyons. "
        "Chaque fiche doit être reconnaissable et différente des autres. "
        "Tu peux faire des rapprochements simples avec Nyons, la saison ou la vie locale "
        "uniquement quand ils découlent logiquement des faits fournis. "
        "Tu dois aider le lecteur à comprendre rapidement pourquoi cette sortie mérite son attention, "
        "ce qu'il faut retenir et ce qu'il doit vérifier avant de se déplacer. "
        "Utilise intelligemment les informations pratiques structurées quand elles existent : "
        "horaires, lieu, adresse, téléphone, email et site. "
        "Ne recopie pas mécaniquement ces informations dans tous les paragraphes : "
        "elles sont déjà affichées dans un bloc pratique sur la page. "
        "Évite absolument les phrases passe-partout et les formulations interchangeables. "
        "Évite notamment : 'ce rendez-vous s'inscrit dans', 'fait partie de la vie locale', "
        "'une belle occasion de', 'un moment à ne pas manquer', 'il y en a pour tous les goûts', "
        "'que vous soyez habitant ou visiteur', sauf si une formulation est réellement nécessaire. "
        "Varie les rythmes de phrases et les transitions. "
        "Le ton peut être légèrement complice, comme quelqu'un qui connaît bien Nyons, "
        "sans inventer de souvenir personnel ni prétendre avoir assisté à l'événement. "
        "RÈGLE ABSOLUE : n'invente jamais une ambiance constatée, une fréquentation, un tarif, "
        "un programme, un public officiel, une réservation, un organisateur, un lieu, un horaire, "
        "un historique ou un témoignage absent des faits fournis. "
        "Quand les faits sont limités, écris moins mais écris mieux."
    )

    user = (
        "Rédige la fiche éditoriale d'un événement de Nyons à partir UNIQUEMENT des faits JSON ci-dessous.\n\n"
        "Objectif : produire un texte utile, local et vraiment spécifique à CET événement, "
        "sans remplissage SEO.\n"
        "Longueur cible quand la matière le permet : environ 280 à 460 mots au total.\n\n"
        "- seo_title : naturel, précis, informatif, idéalement moins de 65 caractères. "
        "Évite les titres génériques du type 'date et infos' si un angle plus précis est possible.\n"
        "- meta_description : environ 140 à 160 caractères, factuelle et attirante sans exagération.\n"
        "- intro : 80 à 130 mots. Ouvre avec l'élément le plus distinctif : date, durée, lieu, "
        "type d'événement, particularité concrète. Ne commence pas par 'À Nyons, il y a toujours...' "
        "ni par une généralité touristique.\n"
        "- story : 100 à 170 mots. Explique ce qui distingue ce rendez-vous des autres événements "
        "de l'agenda et donne du contexte uniquement à partir des faits disponibles. "
        "Fais ressortir les éléments précis plutôt que de reformuler le titre.\n"
        "- why_it_matters : 60 à 110 mots. Donne une lecture utile : quelle envie de sortie cela peut "
        "satisfaire, ce qu'un lecteur peut chercher à savoir, ce qui rend l'événement notable. "
        "Ne prétends pas connaître un public officiel s'il n'est pas indiqué.\n"
        "- practical : 45 à 90 mots. Résume les points utiles à garder en tête et distingue clairement "
        "ce qui est connu de ce qui doit être vérifié. Ne répète pas toute l'adresse ou tous les contacts "
        "si le bloc pratique les affiche déjà.\n"
        "- reader_question : une seule question simple, naturelle et directement liée à cet événement. "
        "Pas de question passe-partout du type 'Et vous, allez-vous y aller ?' si on peut être plus précis.\n\n"
        "Cherche de la variété lexicale. Aucun paragraphe ne doit pouvoir être réutilisé tel quel "
        "pour un autre événement.\n\n"
        f"FAITS:\n{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=OPENAI_MODEL,
            store=False,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "agenda_nyons_event_page",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        data = json.loads(response.output_text)
        data["meta_description"] = trim_meta(data.get("meta_description", ""))
        data["_fallback"] = False
        return data
    except Exception as exc:
        print(f"Événement {event['title']}: OpenAI erreur ({exc}), texte de secours.", file=sys.stderr)
        return fallback_event_editorial(event)


def render_event_page(event, editorial, related_events=None, practical=None):
    related_events = related_events or []
    practical = practical or {}
    canonical = event_local_url(event)
    status = event_status(event)
    cats = " · ".join(event.get("categories") or [])
    meta = trim_meta(editorial.get("meta_description", ""))
    seo_title = clean(editorial.get("seo_title", "")) or f"{event['title']} à Nyons"

    related_html = ""
    for other in related_events[:3]:
        related_html += f'''<a class="related-card" href="{esc(event_local_url(other))}">
          <strong>{esc(other['title'])}</strong>
          <span>{esc(format_event_date(other))}</span>
        </a>'''

    archive_note = ""
    if status == "Événement terminé":
        archive_note = '''<div class="archive-note"><strong>📚 Événement terminé.</strong> Cette fiche reste en ligne comme archive locale. Pour les prochains rendez-vous, consultez l’agenda actuel.</div>'''

    date_display = clean(practical.get("date_time", "")) or format_event_date(event)

    info_rows = []
    if practical.get("location_name"):
        info_rows.append(
            f'<div class="info-row"><span>📍</span><div><strong>Lieu</strong><br>{esc(practical["location_name"])}</div></div>'
        )
    if practical.get("address"):
        info_rows.append(
            f'<div class="info-row"><span>🗺️</span><div><strong>Adresse</strong><br>{esc(practical["address"])}</div></div>'
        )
    if practical.get("phone"):
        phone_href = re.sub(r"[^0-9+]", "", practical["phone"])
        info_rows.append(
            f'<div class="info-row"><span>☎️</span><div><strong>Téléphone</strong><br><a href="tel:{esc(phone_href)}">{esc(practical["phone"])}</a></div></div>'
        )
    if practical.get("email"):
        info_rows.append(
            f'<div class="info-row"><span>✉️</span><div><strong>Email</strong><br><a href="mailto:{esc(practical["email"])}">{esc(practical["email"])}</a></div></div>'
        )
    if practical.get("website"):
        label = urlparse(practical["website"]).netloc or practical["website"]
        info_rows.append(
            f'<div class="info-row"><span>🌐</span><div><strong>Site</strong><br><a href="{esc(practical["website"])}" target="_blank" rel="noopener">{esc(label)}</a></div></div>'
        )

    practical_section = ""
    if info_rows or practical.get("date_time"):
        practical_section = (
            '<section class="section practical-box"><h2>📌 Infos pratiques</h2>'
            '<div class="info-grid">'
            f'<div class="info-row info-date"><span>📅</span><div><strong>Dates et horaires</strong><br>{esc(date_display)}</div></div>'
            + "".join(info_rows)
            + '</div></section>'
        )

    event_ld = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": event["title"],
        "startDate": event["start_date"],
        "endDate": event["end_date"],
        "url": canonical,
        "sameAs": event["url"],
        "eventStatus": "https://schema.org/EventScheduled",
        "description": meta,
    }
    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Agenda de Nyons", "item": SITE},
            {"@type": "ListItem", "position": 2, "name": "Événements", "item": f"{SITE}evenements/"},
            {"@type": "ListItem", "position": 3, "name": event["title"], "item": canonical},
        ],
    }

    cats_html = f'<div class="cats">{esc(cats)}</div>' if cats else ""
    related_section = ""
    if related_html:
        related_section = f'<section class="section"><h2>📍 D’autres rendez-vous proches</h2><div class="related">{related_html}</div></section>'

    return f'''<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(seo_title)}</title>
  <meta name="description" content="{esc(meta)}">
  <link rel="canonical" href="{esc(canonical)}">
  <meta name="robots" content="index,follow">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{esc(seo_title)}">
  <meta property="og:description" content="{esc(meta)}">
  <meta property="og:url" content="{esc(canonical)}">
  <script type="application/ld+json">{json.dumps(event_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(breadcrumb_ld, ensure_ascii=False)}</script>
  <style>
    *{{box-sizing:border-box}} :root{{--olive:#566b3a;--olive-dark:#354622;--terracotta:#a94f35;--cream:#f6f1e8;--paper:#fffdf9;--ink:#262722;--muted:#686b63;--line:#e4dccd;--shadow:0 12px 34px rgba(52,48,38,.10)}}
    body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--cream);color:var(--ink);line-height:1.72}} a{{color:var(--olive-dark)}}
    .top{{max-width:1180px;margin:auto;padding:15px 18px 0}} .ad-shell{{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:var(--shadow)}} .ad-frame{{display:block;width:100%;aspect-ratio:3/1;border:0}} .ad-note{{font-size:11px;text-align:right;color:#777;margin:6px 4px 0}}
    .wrap{{max-width:980px;margin:auto;padding:18px 18px 64px}} .nav{{display:flex;gap:9px;flex-wrap:wrap;margin:8px 0 18px}} .nav a{{padding:9px 13px;background:#fff;border:1px solid var(--line);border-radius:999px;text-decoration:none;font-weight:800;font-size:13px}}
    .hero{{background:linear-gradient(125deg,var(--olive-dark),var(--olive) 62%,#788d58);color:#fff;border-radius:24px;padding:clamp(27px,5vw,52px);box-shadow:var(--shadow)}}
    .status{{display:inline-block;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.15);font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:.04em}} h1{{font-size:clamp(31px,5vw,50px);line-height:1.08;margin:.35em 0 .3em}} .date{{font-size:18px;font-weight:800;margin:0 0 8px}} .cats{{opacity:.9;font-size:14px}}
    .lead{{font-size:19px;background:var(--paper);border-left:5px solid var(--terracotta);padding:22px 24px;border-radius:16px;margin:24px 0;box-shadow:0 6px 22px rgba(52,48,38,.055)}}
    .section{{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:22px 24px;margin:18px 0}} .section h2{{margin:0 0 9px;font-size:25px;line-height:1.2}} .section p{{margin:0}}.practical-box{{border-top:5px solid var(--terracotta)}}.info-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}}.info-row{{display:flex;gap:11px;align-items:flex-start;background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px;min-width:0}}.info-row span{{flex:0 0 24px;font-size:19px}}.info-row a{{overflow-wrap:anywhere}}.info-date{{grid-column:1/-1;background:#f6f0e4}}
    .question{{background:#efe7cf;border-radius:18px;padding:22px 24px;margin:20px 0;font-weight:800;font-size:18px}} .source{{font-size:13px;color:var(--muted);margin-top:24px;padding:18px;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.65)}}
    .archive-note{{padding:14px 17px;margin:20px 0;background:#f2e5df;border-left:5px solid var(--terracotta);border-radius:12px}} .related{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}} .related-card{{display:flex;flex-direction:column;gap:6px;padding:16px;background:#fff;border:1px solid var(--line);border-radius:14px;text-decoration:none}} .related-card span{{font-size:13px;color:var(--muted)}}
    @media(max-width:720px){{.related,.info-grid{{grid-template-columns:1fr}}.info-date{{grid-column:auto}}.top{{padding:9px 9px 0}}.wrap{{padding:10px 11px 45px}}.hero{{border-radius:18px;padding:24px 20px}}.lead,.section{{padding:18px}}}}
  </style>
</head>
<body>
  <aside class="top" aria-label="Sélection de livres sur Nyons"><div class="ad-shell"><iframe class="ad-frame" src="{BANNER_URL}" loading="eager" title="Voir ma sélection de vieux livres sur Nyons"></iframe></div><div class="ad-note">Publicité · lien affilié</div></aside>
  <main class="wrap">
    <nav class="nav"><a href="{SITE}">← Agenda</a><a href="{SITE}evenements/">📌 50 prochains événements</a><a href="{SITE}semaines/">📅 Par semaine</a></nav>
    <header class="hero"><span class="status">{esc(status)}</span><h1>{esc(event['title'])}</h1><p class="date">📅 {esc(date_display)}</p>{cats_html}</header>
    {archive_note}
    {practical_section}
    <div class="lead">{esc(editorial.get('intro',''))}</div>
    <section class="section"><h2>🌿 Le rendez-vous, côté Nyons</h2><p>{esc(editorial.get('story',''))}</p></section>
    <section class="section"><h2>👀 Pourquoi regarder cette sortie de plus près ?</h2><p>{esc(editorial.get('why_it_matters',''))}</p></section>
    <section class="section"><h2>ℹ️ Avant de vous déplacer</h2><p>{esc(editorial.get('practical',''))}</p></section>
    <div class="question">💬 {esc(editorial.get('reader_question',''))}</div>
    {related_section}
    <div class="source"><strong>Source factuelle :</strong> <a href="{esc(event['url'])}" target="_blank" rel="noopener">fiche officielle de l’événement sur nyons.com</a>. Le texte de cette page est une présentation éditoriale originale construite à partir des informations publiées. Les informations pratiques peuvent évoluer.</div>
  </main>
</body>
</html>'''


def render_events_index(active_events, event_cache):
    cards = []
    for e in active_events:
        entry = event_cache.get(e["url"], {})
        editorial = entry.get("editorial") or fallback_event_editorial(e)
        intro = clean(editorial.get("intro", ""))
        excerpt = intro[:190]
        if len(intro) > 190:
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"
        cards.append(f'''<a class="card" href="{esc(event_local_url(e))}">
          <div class="datebox"><strong>{parse_iso(e['start_date']).day}</strong><span>{esc(MONTH_NAMES[parse_iso(e['start_date']).month][:3].upper())}</span></div>
          <div><h2>{esc(e['title'])}</h2><p class="when">{esc(format_event_date(e))}</p><p>{esc(excerpt)}</p><b>Lire la fiche →</b></div>
        </a>''')

    return f'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>50 prochains événements à Nyons</title><meta name="description" content="Les 50 prochains événements à Nyons : sorties, culture, loisirs et rendez-vous locaux avec une fiche détaillée pour chacun."><link rel="canonical" href="{SITE}evenements/"><meta name="robots" content="index,follow"><style>
*{{box-sizing:border-box}}:root{{--olive:#566b3a;--olive-dark:#354622;--terracotta:#a94f35;--cream:#f6f1e8;--paper:#fffdf9;--ink:#262722;--muted:#6b6d65;--line:#e4dccd;--shadow:0 12px 34px rgba(52,48,38,.10)}}body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--cream);color:var(--ink);line-height:1.62}}.top{{max-width:1180px;margin:auto;padding:15px 18px 0}}.ad-shell{{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:var(--shadow)}}.ad-frame{{display:block;width:100%;aspect-ratio:3/1;border:0}}.ad-note{{font-size:11px;text-align:right;color:#777;margin:6px 4px 0}}.wrap{{max-width:1080px;margin:auto;padding:18px 18px 60px}}.nav{{display:flex;gap:9px;flex-wrap:wrap;margin:8px 0 18px}}.nav a{{padding:9px 13px;background:#fff;border:1px solid var(--line);border-radius:999px;text-decoration:none;font-weight:800;font-size:13px;color:var(--olive-dark)}}.hero{{background:linear-gradient(125deg,var(--olive-dark),var(--olive) 62%,#788d58);color:#fff;border-radius:24px;padding:clamp(28px,5vw,52px);box-shadow:var(--shadow)}}h1{{font-size:clamp(32px,5vw,52px);line-height:1.08;margin:.15em 0 .3em}}.hero p{{max-width:800px;margin:0;font-size:18px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:22px}}.card{{display:flex;gap:15px;background:var(--paper);border:1px solid var(--line);border-radius:17px;padding:18px;color:var(--ink);text-decoration:none;box-shadow:0 6px 22px rgba(52,48,38,.055)}}.card:hover{{transform:translateY(-2px)}}.card h2{{margin:0 0 6px;font-size:19px;line-height:1.25}}.card p{{margin:5px 0;color:var(--muted)}}.card b{{color:var(--olive-dark);font-size:14px}}.datebox{{flex:0 0 58px;height:64px;background:var(--terracotta);color:#fff;border-radius:13px;text-align:center;padding:8px 3px;line-height:1}}.datebox strong{{display:block;font-size:24px}}.datebox span{{display:block;margin-top:6px;font-size:11px;font-weight:900;letter-spacing:.08em}}.when{{font-weight:800!important;color:var(--ink)!important;font-size:13px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.top{{padding:9px 9px 0}}.wrap{{padding:10px 11px 45px}}.hero{{border-radius:18px}}}}
</style></head><body><aside class="top"><div class="ad-shell"><iframe class="ad-frame" src="{BANNER_URL}" loading="eager" title="Voir ma sélection de vieux livres sur Nyons"></iframe></div><div class="ad-note">Publicité · lien affilié</div></aside><main class="wrap"><nav class="nav"><a href="{SITE}">← Agenda interactif</a><a href="{SITE}semaines/">📅 Agenda par semaine</a></nav><section class="hero"><div>NYONS · SORTIES À VENIR</div><h1>Les 50 prochains événements à Nyons</h1><p>Une sélection roulante : lorsqu’un rendez-vous passe, le suivant entre automatiquement dans la liste. Chaque événement dispose de sa propre fiche éditoriale.</p></section><section class="grid">{''.join(cards)}</section></main></body></html>'''


def generate_event_pages(events):
    EVENTS_DIR.mkdir(exist_ok=True)
    active = rolling_events(events)
    event_cache = load_json_file(EVENT_CACHE_FILE)
    detail_cache = load_json_file(EVENT_DETAIL_CACHE_FILE)
    session = requests.Session()
    ai_calls = 0

    for idx, event in enumerate(active, start=1):
        detail_data = get_event_detail(session, event, detail_cache)
        detail = detail_data.get("text", "")
        practical = detail_data.get("practical") or {}
        digest = event_hash(event, detail, practical)
        cached = event_cache.get(event["url"], {})

        if (
            cached.get("hash") == digest
            and cached.get("editorial")
            and not cached.get("editorial", {}).get("_fallback", False)
        ):
            editorial = cached["editorial"]
            print(f"FICHE {idx:02d}/50: inchangée, aucun appel API — {event['title']}")
        elif ai_calls < MAX_EVENT_AI_CALLS:
            editorial = generate_event_editorial(event, detail, practical)
            ai_calls += 1
            print(f"FICHE {idx:02d}/50: contenu éditorial généré — {event['title']}")
        else:
            editorial = cached.get("editorial") or fallback_event_editorial(event)
            print(f"FICHE {idx:02d}/50: limite API atteinte, texte conservé/secours — {event['title']}")

        event_cache[event["url"]] = {
            "hash": digest,
            "slug": event_slug(event),
            "event": event,
            "editorial": editorial,
            "practical": practical,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": OPENAI_MODEL,
        }

    cached_events = []
    for entry in event_cache.values():
        e = entry.get("event")
        if e and entry.get("editorial"):
            cached_events.append(e)
    cached_events.sort(key=lambda e: (e["start_date"], e["title"].lower()))

    for entry in event_cache.values():
        event = entry.get("event")
        editorial = entry.get("editorial")
        practical = entry.get("practical") or {}
        if not event or not editorial:
            continue
        nearby = [
            other for other in cached_events
            if other["url"] != event["url"]
            and abs((parse_iso(other["start_date"]) - parse_iso(event["start_date"])).days) <= 10
        ][:3]
        folder = EVENTS_DIR / event_slug(event)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(
            render_event_page(event, editorial, nearby, practical),
            encoding="utf-8",
        )

    (EVENTS_DIR / "index.html").write_text(
        render_events_index(active, event_cache),
        encoding="utf-8",
    )
    save_json_file(EVENT_CACHE_FILE, event_cache)
    save_json_file(EVENT_DETAIL_CACHE_FILE, detail_cache)
    print(
        f"OK: {len(active)} événement(s) dans la sélection roulante, "
        f"{len(cached_events)} fiche(s) conservée(s), {ai_calls} appel(s) API ce passage."
    )

def fallback_editorial(start: date, events):
    label = week_label(start)
    titles = [e["title"] for e in events[:3]]
    intro = (
        f"Vous cherchez que faire à Nyons {label} ? "
        f"Cette sélection rassemble {len(events)} rendez-vous annoncés dans "
        "l’agenda officiel de la Ville de Nyons. Retrouvez ci-dessous les dates "
        "essentielles et les liens vers les fiches officielles pour préparer votre semaine."
    )
    weekend = (
        "Pour organiser votre week-end, consultez les événements datés du samedi "
        "et du dimanche dans la liste ci-dessous. Les horaires, tarifs et éventuelles "
        "modifications restent à vérifier sur la fiche officielle de chaque rendez-vous."
    )
    practical = (
        "Avant de vous déplacer, vérifiez la fiche officielle : certains événements "
        "peuvent être modifiés, reportés ou soumis à réservation."
    )
    conclusion = (
        "Cette page est mise à jour automatiquement à partir de l’agenda public de Nyons. "
        "Revenez régulièrement pour découvrir les nouveaux rendez-vous annoncés."
    )
    highlights = [
        {"event_title": t, "reason": "Un rendez-vous à retrouver dans l’agenda de la semaine."}
        for t in titles
    ]
    meta = (
        f"Agenda de Nyons {label} : sorties, animations et événements de la semaine, "
        "avec dates et liens vers les fiches officielles."
    )
    return {
        "meta_description": meta,
        "intro": intro,
        "weekend": weekend,
        "practical": practical,
        "conclusion": conclusion,
        "highlights": highlights,
    }


def generate_editorial(start: date, events):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        print("OpenAI indisponible: texte de secours utilisé.")
        return fallback_editorial(start, events)

    schema = {
        "type": "object",
        "properties": {
            "meta_description": {"type": "string"},
            "intro": {"type": "string"},
            "weekend": {"type": "string"},
            "practical": {"type": "string"},
            "conclusion": {"type": "string"},
            "highlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_title": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["event_title", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "meta_description", "intro", "weekend",
            "practical", "conclusion", "highlights"
        ],
        "additionalProperties": False,
    }

    facts = event_facts_for_ai(events)
    system = (
        "Tu es rédacteur local francophone spécialisé dans le tourisme et le SEO utile. "
        "Tu écris pour une page 'Agenda de Nyons'. "
        "Tu dois apporter une vraie valeur éditoriale sans recopier la source. "
        "RÈGLES ABSOLUES : utilise uniquement les faits fournis; n'invente jamais "
        "d'horaire, de tarif, de lieu, de programme, de public cible, de réservation "
        "ou de caractéristique non présente; ne cite pas mot pour mot les résumés source; "
        "ne fais pas de bourrage de mots-clés; écris naturellement; si une information "
        "manque, ne la suppose pas. Les titres d'événements choisis dans highlights "
        "doivent être reproduits exactement."
    )
    user = (
        f"Semaine : {week_label(start)}\n\n"
        "À partir des événements JSON ci-dessous, crée un contenu éditorial ORIGINAL en français.\n"
        "- meta_description : environ 140 à 160 caractères.\n"
        "- intro : 120 à 180 mots, utile et naturel.\n"
        "- weekend : 80 à 130 mots sur la façon de choisir les sorties du week-end, "
        "sans inventer de détails.\n"
        "- practical : 50 à 90 mots de conseils de vérification pratiques.\n"
        "- conclusion : 50 à 90 mots.\n"
        "- highlights : 2 ou 3 événements maximum, avec leur titre EXACT et une raison "
        "courte fondée uniquement sur les faits fournis.\n\n"
        f"ÉVÉNEMENTS:\n{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=OPENAI_MODEL,
            store=False,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "agenda_nyons_seo",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        data = json.loads(response.output_text)

        valid_titles = {e["title"] for e in events}
        data["highlights"] = [
            h for h in data.get("highlights", [])
            if h.get("event_title") in valid_titles
        ][:3]

        if not data["highlights"]:
            data["highlights"] = fallback_editorial(start, events)["highlights"]

        return data
    except Exception as exc:
        print(f"OpenAI: erreur ({exc}). Texte de secours utilisé.", file=sys.stderr)
        return fallback_editorial(start, events)


def trim_meta(text: str, limit=160):
    text = clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def format_event_date(e):
    start = parse_iso(e["start_date"])
    end = parse_iso(e["end_date"])
    if start == end:
        return french_date(start)
    return f"du {french_date(start)} au {french_date(end)}"


def esc(s):
    return html.escape(str(s or ""), quote=True)


def render_week_page(start: date, events, editorial):
    end = start + timedelta(days=6)
    label = week_label(start)
    slug = slug_week(start)
    canonical = f"{SITE}semaines/{slug}/"
    title = f"Agenda de Nyons {label} : que faire cette semaine ?"
    meta = trim_meta(editorial["meta_description"])

    highlight_html = ""
    for h in editorial["highlights"]:
        highlight_html += f"""
        <article class="highlight">
          <div class="highlight-star">★</div>
          <div>
            <h3>{esc(h["event_title"])}</h3>
            <p>{esc(h["reason"])}</p>
          </div>
        </article>
        """

    events_html = ""
    for e in events:
        cats = " · ".join(e.get("categories") or [])
        cats_html = f'<div class="cats">{esc(cats)}</div>' if cats else ""
        event_start = parse_iso(e["start_date"])
        date_badge = (
            f'<div class="date-badge"><span>{event_start.day}</span>'
            f'<small>{esc(MONTH_NAMES[event_start.month][:3].upper())}</small></div>'
        )
        local_exists = event_page_path(e).exists()
        title_url = event_local_url(e) if local_exists else e["url"]
        title_attrs = "" if local_exists else ' target="_blank" rel="noopener"'
        local_cta = (
            f'<a class="official" href="{esc(event_local_url(e))}">Lire notre fiche <span aria-hidden="true">→</span></a>'
            if local_exists else ""
        )
        events_html += f"""
        <article class="event">
          {date_badge}
          <div class="event-content">
            <h3><a href="{esc(title_url)}"{title_attrs}>{esc(e['title'])}</a></h3>
            <p class="date-line">📅 {esc(format_event_date(e))}</p>
            {cats_html}
            {local_cta}
            <a class="official" href="{esc(e['url'])}" target="_blank" rel="noopener">
              Source officielle <span aria-hidden="true">↗</span>
            </a>
          </div>
        </article>
        """

    structured_events = []
    for e in events:
        structured_events.append({
            "@type": "Event",
            "name": e["title"],
            "startDate": e["start_date"],
            "endDate": e["end_date"],
            "url": e["url"],
            "eventStatus": "https://schema.org/EventScheduled",
        })

    json_ld = {"@context": "https://schema.org", "@graph": structured_events}

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(meta)}">
  <link rel="canonical" href="{esc(canonical)}">
  <meta name="robots" content="index,follow">
  <script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
  <style>
    * {{ box-sizing:border-box; }}
    :root {{
      --olive:#566b3a;
      --olive-dark:#354622;
      --terracotta:#a94f35;
      --cream:#f6f1e8;
      --paper:#fffdf9;
      --ink:#262722;
      --muted:#6b6d65;
      --line:#e4dccd;
      --shadow:0 12px 34px rgba(52,48,38,.10);
    }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0;
      font-family:Arial,Helvetica,sans-serif;
      background:var(--cream);
      color:var(--ink);
      line-height:1.68;
    }}
    a {{ color:var(--olive-dark); }}
    .top {{
      max-width:1180px;
      margin:0 auto;
      padding:16px 18px 0;
    }}
    .ad-shell {{
      background:#fff;
      border:1px solid var(--line);
      border-radius:16px;
      overflow:hidden;
      box-shadow:var(--shadow);
    }}
    .ad-frame {{
      display:block;
      width:100%;
      aspect-ratio:3 / 1;
      border:0;
      background:#fff;
    }}
    .ad-note {{
      margin:7px 5px 0;
      text-align:right;
      font-size:11px;
      color:#7c7c75;
    }}
    .wrap {{
      max-width:1120px;
      margin:auto;
      padding:18px 18px 64px;
    }}
    .nav {{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      margin:10px 0 18px;
    }}
    .nav a {{
      display:inline-flex;
      align-items:center;
      padding:9px 14px;
      border:1px solid var(--line);
      background:rgba(255,255,255,.78);
      border-radius:999px;
      text-decoration:none;
      font-weight:700;
      font-size:14px;
    }}
    .hero {{
      position:relative;
      overflow:hidden;
      color:#fff;
      background:linear-gradient(125deg,var(--olive-dark),var(--olive) 58%,#788d58);
      padding:clamp(26px,5vw,52px);
      border-radius:24px;
      box-shadow:var(--shadow);
    }}
    .hero::after {{
      content:"";
      position:absolute;
      width:240px;height:240px;
      border-radius:50%;
      right:-80px;top:-95px;
      background:rgba(255,255,255,.08);
    }}
    .kicker {{
      font-weight:800;
      letter-spacing:.08em;
      text-transform:uppercase;
      font-size:12px;
      opacity:.88;
    }}
    h1 {{
      max-width:900px;
      line-height:1.08;
      font-size:clamp(31px,5vw,52px);
      margin:.22em 0 .42em;
    }}
    .hero p {{
      max-width:850px;
      margin:0;
      font-size:clamp(16px,2vw,19px);
    }}
    .section-title {{
      display:flex;
      align-items:center;
      gap:10px;
      margin:42px 0 17px;
    }}
    .section-title h2 {{
      margin:0;
      font-size:clamp(24px,3.5vw,32px);
      line-height:1.2;
    }}
    .section-title span {{
      font-size:26px;
    }}
    .highlights {{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:14px;
    }}
    .highlight {{
      display:flex;
      gap:13px;
      background:var(--paper);
      border:1px solid var(--line);
      border-radius:17px;
      padding:18px;
      box-shadow:0 6px 22px rgba(52,48,38,.06);
    }}
    .highlight-star {{
      flex:0 0 38px;
      width:38px;height:38px;
      display:grid;place-items:center;
      border-radius:12px;
      background:#efe7cf;
      color:#8c6a18;
      font-size:20px;
    }}
    .highlight h3 {{
      margin:0 0 6px;
      line-height:1.25;
      font-size:18px;
    }}
    .highlight p {{ margin:0;color:var(--muted);font-size:14px; }}
    .editorial {{
      background:var(--paper);
      border-left:5px solid var(--terracotta);
      border-radius:16px;
      padding:21px 23px;
      box-shadow:0 6px 22px rgba(52,48,38,.055);
    }}
    .events {{
      display:grid;
      grid-template-columns:repeat(2,minmax(0,1fr));
      gap:14px;
    }}
    .event {{
      display:flex;
      gap:16px;
      align-items:flex-start;
      background:var(--paper);
      border:1px solid var(--line);
      border-radius:18px;
      padding:18px;
      box-shadow:0 6px 22px rgba(52,48,38,.055);
      transition:transform .15s ease,box-shadow .15s ease;
    }}
    .event:hover {{
      transform:translateY(-2px);
      box-shadow:0 10px 28px rgba(52,48,38,.095);
    }}
    .date-badge {{
      flex:0 0 58px;
      width:58px;
      padding:8px 4px;
      text-align:center;
      color:#fff;
      background:var(--terracotta);
      border-radius:14px;
      line-height:1;
    }}
    .date-badge span {{
      display:block;
      font-size:24px;
      font-weight:900;
    }}
    .date-badge small {{
      display:block;
      margin-top:5px;
      font-size:11px;
      font-weight:800;
      letter-spacing:.08em;
    }}
    .event-content {{ min-width:0; }}
    .event h3 {{
      margin:0 0 7px;
      font-size:19px;
      line-height:1.25;
    }}
    .event h3 a {{ text-decoration:none; }}
    .event h3 a:hover {{ text-decoration:underline; }}
    .date-line {{ margin:0 0 5px;font-weight:700;font-size:14px; }}
    .cats {{ color:var(--muted);font-size:13px;margin-bottom:10px; }}
    .official {{
      display:inline-block;
      margin-top:5px;
      font-weight:800;
      font-size:14px;
      text-decoration:none;
    }}
    .source {{
      margin-top:42px;
      padding:18px 20px;
      border:1px solid var(--line);
      background:rgba(255,255,255,.65);
      border-radius:15px;
      color:var(--muted);
      font-size:13px;
    }}
    @media (max-width:840px) {{
      .highlights,.events {{ grid-template-columns:1fr; }}
    }}
    @media (max-width:520px) {{
      .top {{ padding:9px 9px 0; }}
      .wrap {{ padding:10px 11px 45px; }}
      .hero {{ border-radius:18px;padding:24px 20px; }}
      .event {{ padding:15px;gap:12px; }}
      .date-badge {{ flex-basis:51px;width:51px; }}
      .date-badge span {{ font-size:21px; }}
      .nav a {{ font-size:12px;padding:8px 11px; }}
      .ad-shell {{ border-radius:10px; }}
    }}
  </style>
</head>
<body>
  <aside class="top" aria-label="Sélection de livres sur Nyons">
    <div class="ad-shell">
      <iframe class="ad-frame" src="{BANNER_URL}" loading="eager"
              title="Voir ma sélection de vieux livres sur Nyons"></iframe>
    </div>
    <div class="ad-note">Publicité · lien affilié</div>
  </aside>

  <main class="wrap">
    <nav class="nav">
      <a href="{SITE}">← Agenda interactif</a>
      <a href="{SITE}semaines/">📅 Toutes les semaines</a>
      <a href="{SITE}evenements/">📌 50 prochains événements</a>
    </nav>

    <section class="hero">
      <div class="kicker">Nyons · agenda de la semaine</div>
      <h1>{esc(title)}</h1>
      <p>{esc(editorial['intro'])}</p>
    </section>

    <section>
      <div class="section-title"><span>⭐</span><h2>Les rendez-vous à retenir</h2></div>
      <div class="highlights">{highlight_html}</div>
    </section>

    <section>
      <div class="section-title"><span>☀️</span><h2>Que faire à Nyons ce week-end ?</h2></div>
      <div class="editorial"><p>{esc(editorial['weekend'])}</p></div>
    </section>

    <section>
      <div class="section-title"><span>📅</span><h2>Tous les événements {esc(label)}</h2></div>
      <div class="events">{events_html}</div>
    </section>

    <section>
      <div class="section-title"><span>ℹ️</span><h2>Avant de vous déplacer</h2></div>
      <div class="editorial"><p>{esc(editorial['practical'])}</p></div>
    </section>

    <section class="editorial" style="margin-top:22px">
      <p>{esc(editorial['conclusion'])}</p>
    </section>

    <div class="source">
      <strong>Source des dates et événements :</strong>
      <a href="{BASE}" target="_blank" rel="noopener">agenda officiel de la Ville de Nyons</a>.
      Les textes éditoriaux apportent une présentation complémentaire à partir des informations factuelles disponibles.
    </div>
  </main>
</body>
</html>
"""

def render_weeks_index(weeks):
    cards = []
    today_monday = monday_of(date.today())
    for start, events in weeks.items():
        slug = slug_week(start)
        current = " current" if start == today_monday else ""
        badge = '<span class="now">Cette semaine</span>' if start == today_monday else ""
        cards.append(f"""
        <a class="week-card{current}" href="{slug}/">
          <div class="week-top">
            <span class="calendar">📅</span>
            {badge}
          </div>
          <h2>Agenda de Nyons {esc(week_label(start))}</h2>
          <p>{len(events)} événement(s) annoncé(s)</p>
          <span class="cta">Voir la semaine →</span>
        </a>
        """)

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Agenda de Nyons semaine par semaine</title>
  <meta name="description" content="Agenda de Nyons semaine par semaine : sorties, animations et événements avec liens vers les fiches officielles.">
  <link rel="canonical" href="{SITE}semaines/">
  <meta name="robots" content="index,follow">
  <style>
    * {{ box-sizing:border-box; }}
    :root {{
      --olive:#566b3a;
      --olive-dark:#354622;
      --terracotta:#a94f35;
      --cream:#f6f1e8;
      --paper:#fffdf9;
      --ink:#262722;
      --muted:#6b6d65;
      --line:#e4dccd;
      --shadow:0 12px 34px rgba(52,48,38,.10);
    }}
    body {{
      margin:0;
      font-family:Arial,Helvetica,sans-serif;
      background:var(--cream);
      color:var(--ink);
      line-height:1.65;
    }}
    .top {{
      max-width:1180px;
      margin:0 auto;
      padding:16px 18px 0;
    }}
    .ad-shell {{
      background:#fff;
      border:1px solid var(--line);
      border-radius:16px;
      overflow:hidden;
      box-shadow:var(--shadow);
    }}
    .ad-frame {{
      display:block;
      width:100%;
      aspect-ratio:3 / 1;
      border:0;
      background:#fff;
    }}
    .ad-note {{
      margin:7px 5px 0;
      text-align:right;
      font-size:11px;
      color:#7c7c75;
    }}
    .wrap {{ max-width:1120px;margin:auto;padding:18px 18px 64px; }}
    .back {{
      display:inline-block;
      margin:8px 0 18px;
      padding:9px 14px;
      border:1px solid var(--line);
      background:#fff;
      border-radius:999px;
      color:var(--olive-dark);
      text-decoration:none;
      font-weight:800;
      font-size:14px;
    }}
    .hero {{
      background:linear-gradient(125deg,var(--olive-dark),var(--olive) 58%,#788d58);
      color:#fff;
      border-radius:24px;
      padding:clamp(28px,5vw,54px);
      box-shadow:var(--shadow);
    }}
    .hero .kicker {{
      text-transform:uppercase;
      font-weight:800;
      font-size:12px;
      letter-spacing:.08em;
      opacity:.88;
    }}
    h1 {{
      margin:.2em 0 .3em;
      line-height:1.08;
      font-size:clamp(32px,5vw,52px);
    }}
    .hero p {{
      max-width:780px;
      margin:0;
      font-size:clamp(16px,2vw,19px);
    }}
    .weeks {{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:16px;
      margin-top:24px;
    }}
    .week-card {{
      display:block;
      position:relative;
      padding:22px;
      min-height:210px;
      background:var(--paper);
      border:1px solid var(--line);
      border-radius:18px;
      color:var(--ink);
      text-decoration:none;
      box-shadow:0 7px 25px rgba(52,48,38,.065);
      transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease;
    }}
    .week-card:hover {{
      transform:translateY(-3px);
      box-shadow:0 13px 30px rgba(52,48,38,.11);
      border-color:#cfc3af;
    }}
    .week-card.current {{
      border:2px solid var(--terracotta);
    }}
    .week-top {{
      display:flex;
      justify-content:space-between;
      align-items:center;
      min-height:35px;
    }}
    .calendar {{ font-size:28px; }}
    .now {{
      padding:5px 9px;
      border-radius:999px;
      background:#f2dfd8;
      color:#7f3321;
      font-weight:800;
      font-size:11px;
      text-transform:uppercase;
      letter-spacing:.05em;
    }}
    .week-card h2 {{
      margin:18px 0 8px;
      font-size:20px;
      line-height:1.28;
    }}
    .week-card p {{ color:var(--muted);margin:0 0 16px; }}
    .cta {{ color:var(--olive-dark);font-weight:900; }}
    .source {{
      margin-top:34px;
      padding:17px 19px;
      background:rgba(255,255,255,.68);
      border:1px solid var(--line);
      border-radius:15px;
      color:var(--muted);
      font-size:13px;
    }}
    .source a {{ color:var(--olive-dark); }}
    @media(max-width:850px) {{ .weeks {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media(max-width:560px) {{
      .top {{ padding:9px 9px 0; }}
      .wrap {{ padding:10px 11px 44px; }}
      .hero {{ border-radius:18px;padding:25px 20px; }}
      .weeks {{ grid-template-columns:1fr;gap:12px; }}
      .week-card {{ min-height:0;padding:18px; }}
      .ad-shell {{ border-radius:10px; }}
    }}
  </style>
</head>
<body>
  <aside class="top" aria-label="Sélection de livres sur Nyons">
    <div class="ad-shell">
      <iframe class="ad-frame" src="{BANNER_URL}" loading="eager"
              title="Voir ma sélection de vieux livres sur Nyons"></iframe>
    </div>
    <div class="ad-note">Publicité · lien affilié</div>
  </aside>

  <main class="wrap">
    <a class="back" href="{SITE}">← Agenda interactif</a>
    <a class="back" href="{SITE}evenements/">📌 50 prochains événements</a>

    <section class="hero">
      <div class="kicker">Sorties · animations · vie locale</div>
      <h1>Agenda de Nyons semaine par semaine</h1>
      <p>Choisissez une semaine pour découvrir les événements annoncés à Nyons, avec une présentation claire et des liens vers les fiches officielles.</p>
    </section>

    <section class="weeks">
      {''.join(cards)}
    </section>

    <div class="source">
      <strong>Source :</strong>
      <a href="{BASE}" target="_blank" rel="noopener">Ville de Nyons — agenda officiel</a>.
      Mise à jour automatique.
    </div>
  </main>
</body>
</html>
"""

def write_sitemap():
    urls = [SITE, f"{SITE}semaines/", f"{SITE}evenements/"]
    if WEEKS_DIR.exists():
        for p in sorted(WEEKS_DIR.glob("semaine-*/index.html")):
            urls.append(f"{SITE}semaines/{p.parent.name}/")
    if EVENTS_DIR.exists():
        for p in sorted(EVENTS_DIR.glob("*/index.html")):
            urls.append(f"{SITE}evenements/{p.parent.name}/")

    today = date.today().isoformat()
    entries = "\n".join(
        f"  <url><loc>{html.escape(u)}</loc><lastmod>{today}</lastmod></url>"
        for u in urls
    )
    SITEMAP.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n",
        encoding="utf-8",
    )
    ROBOTS.write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE}sitemap.xml\n",
        encoding="utf-8",
    )


def generate_seo_pages(events):
    WEEKS_DIR.mkdir(exist_ok=True)
    weeks = group_weeks(events)
    cache = load_cache()

    for start, week_events in weeks.items():
        key = start.isoformat()
        digest = week_hash(start, week_events)
        cached = cache.get(key, {})

        if cached.get("hash") == digest and cached.get("editorial"):
            editorial = cached["editorial"]
            print(f"SEO {key}: inchangé, aucun appel API.")
        else:
            editorial = generate_editorial(start, week_events)
            cache[key] = {
                "hash": digest,
                "editorial": editorial,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model": OPENAI_MODEL,
            }
            print(f"SEO {key}: contenu éditorial généré.")

        folder = WEEKS_DIR / slug_week(start)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(
            render_week_page(start, week_events, editorial),
            encoding="utf-8",
        )

    (WEEKS_DIR / "index.html").write_text(
        render_weeks_index(weeks),
        encoding="utf-8",
    )
    save_cache(cache)
    write_sitemap()
    print(f"OK: {len(weeks)} page(s) SEO hebdomadaire(s) préparée(s).")


def main():
    events = scrape_all()
    write_agenda(events)
    generate_event_pages(events)
    generate_seo_pages(events)


if __name__ == "__main__":
    main()
