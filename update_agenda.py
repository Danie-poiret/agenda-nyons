#!/usr/bin/env python3
"""Agenda automatique de Nyons + pages SEO hebdomadaires.

- Récupère l'agenda public de la Ville de Nyons.
- Met à jour agenda.json.
- Génère des pages HTML semaine par semaine dans /semaines/.
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
SITE = "https://danie-poiret.github.io/agenda-nyons/"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "agenda.json"
WEEKS_DIR = ROOT / "semaines"
CACHE_FILE = ROOT / "_seo_cache.json"
SITEMAP = ROOT / "sitemap.xml"
ROBOTS = ROOT / "robots.txt"

MAX_PAGES = 15
TIMEOUT = 25
SEO_WEEKS_AHEAD = 12
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
    "User-Agent": "Mozilla/5.0 (compatible; AgendaNyons/2.0; +https://github.com/Danie-poiret/agenda-nyons)",
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


def smallest_card(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", None) not in {"article", "li", "div", "section"}:
            continue
        txt = clean(parent.get_text(" ", strip=True))
        if len(txt) > 3500:
            break
        if DATE_RE.search(txt):
            return parent
    return None


def extract_summary(card, anchor, title):
    heading = anchor.find_parent(["h1", "h2", "h3", "h4", "h5"])
    if heading:
        for sib in heading.find_all_next("p", limit=4):
            if card not in sib.parents and sib is not card:
                break
            t = clean(sib.get_text(" ", strip=True))
            if len(t) >= 18 and title.lower() not in t.lower():
                return t[:420]
    for p in card.find_all("p"):
        t = clean(p.get_text(" ", strip=True))
        if len(t) >= 18 and title.lower() not in t.lower():
            return t[:420]
    return ""


def scrape_page(session, page: int):
    url = BASE if page == 1 else f"{BASE}?_pagination={page}"
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    found, seen = [], set()

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        if not is_event_url(href):
            continue

        title = clean(a.get_text(" ", strip=True))
        if len(title) < 4 or title.lower() in {
            "retour", "lire plus", "voir l'événement", "voir l’événement"
        }:
            continue

        href = href.split("#", 1)[0].split("?", 1)[0]
        if href in seen:
            continue

        card = smallest_card(a)
        if card is None:
            continue

        text = clean(card.get_text(" ", strip=True))
        dm = DATE_RE.search(text)
        if not dm:
            continue

        start = parse_match(dm)
        em = UNTIL_RE.search(text)
        end = parse_match(em) if em else start
        summary = extract_summary(card, a, title)
        cats = [c for c in CATEGORIES if c.lower() in text.lower()]

        found.append({
            "title": title,
            "start_date": start,
            "end_date": end,
            "summary": summary,
            "categories": cats,
            "url": href,
        })
        seen.add(href)

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

        before = len(all_events)
        for e in events:
            all_events[e["url"]] = e

        added = len(all_events) - before
        print(f"Page {page}: {len(events)} éléments, {added} nouveaux")
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
        highlight_html += (
            "<li><strong>" + esc(h["event_title"]) + "</strong> — "
            + esc(h["reason"]) + "</li>"
        )

    events_html = ""
    for e in events:
        cats = " · ".join(e.get("categories") or [])
        cats_html = f'<div class="cats">{esc(cats)}</div>' if cats else ""
        events_html += f"""
        <article class="event">
          <h3><a href="{esc(e['url'])}" target="_blank" rel="noopener">{esc(e['title'])}</a></h3>
          <p class="date">📅 {esc(format_event_date(e))}</p>
          {cats_html}
          <p><a class="official" href="{esc(e['url'])}" target="_blank" rel="noopener">Voir la fiche officielle →</a></p>
        </article>
        """

    structured_events = []
    for e in events:
        item = {
            "@type": "Event",
            "name": e["title"],
            "startDate": e["start_date"],
            "endDate": e["end_date"],
            "url": e["url"],
            "eventStatus": "https://schema.org/EventScheduled",
        }
        structured_events.append(item)

    json_ld = {
        "@context": "https://schema.org",
        "@graph": structured_events,
    }

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
    :root {{ color-scheme: light; }}
    body {{ margin:0; font-family:Arial,Helvetica,sans-serif; background:#f6f3ec; color:#252525; line-height:1.65; }}
    .wrap {{ max-width:980px; margin:auto; padding:28px 18px 60px; }}
    .hero {{ background:white; padding:28px; border-radius:18px; box-shadow:0 4px 20px rgba(0,0,0,.06); }}
    h1 {{ line-height:1.15; font-size:clamp(30px,5vw,48px); margin:.1em 0 .4em; }}
    h2 {{ margin-top:34px; font-size:28px; }}
    h3 {{ margin-bottom:4px; font-size:21px; }}
    a {{ color:#1659a5; }}
    .kicker {{ font-weight:700; letter-spacing:.05em; text-transform:uppercase; font-size:13px; }}
    .event {{ background:#fff; margin:14px 0; padding:18px 20px; border-radius:14px; }}
    .date {{ font-weight:700; margin:.35em 0; }}
    .cats {{ font-size:14px; opacity:.75; }}
    .official {{ font-weight:700; }}
    .source {{ margin-top:36px; padding:18px; background:#fff; border-radius:14px; font-size:14px; }}
    .nav {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px; }}
    .nav a {{ background:#fff; padding:8px 12px; border-radius:999px; text-decoration:none; }}
  </style>
</head>
<body>
  <main class="wrap">
    <nav class="nav">
      <a href="{SITE}">← Agenda interactif</a>
      <a href="{SITE}semaines/">Toutes les semaines</a>
    </nav>

    <section class="hero">
      <div class="kicker">Agenda de Nyons · semaine du {esc(french_date(start))}</div>
      <h1>{esc(title)}</h1>
      <p>{esc(editorial['intro'])}</p>
    </section>

    <section>
      <h2>⭐ Les rendez-vous à retenir</h2>
      <ul>{highlight_html}</ul>
    </section>

    <section>
      <h2>☀️ Que faire à Nyons ce week-end ?</h2>
      <p>{esc(editorial['weekend'])}</p>
    </section>

    <section>
      <h2>📅 Tous les événements {esc(label)}</h2>
      {events_html}
    </section>

    <section>
      <h2>ℹ️ Avant de vous déplacer</h2>
      <p>{esc(editorial['practical'])}</p>
    </section>

    <section>
      <p>{esc(editorial['conclusion'])}</p>
    </section>

    <div class="source">
      Source des dates et événements :
      <a href="{BASE}" target="_blank" rel="noopener">agenda officiel de la Ville de Nyons</a>.
      Les textes éditoriaux de cette page sont générés à partir des informations factuelles de l'agenda,
      sans remplacer la fiche officielle.
    </div>
  </main>
</body>
</html>
"""


def render_weeks_index(weeks):
    cards = []
    for start, events in weeks.items():
        slug = slug_week(start)
        cards.append(
            f'<li><a href="{slug}/"><strong>Agenda de Nyons {esc(week_label(start))}</strong>'
            f' — {len(events)} événement(s)</a></li>'
        )

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
    body {{ font-family:Arial,Helvetica,sans-serif; max-width:900px; margin:auto; padding:30px 18px; line-height:1.6; }}
    li {{ margin:12px 0; }}
  </style>
</head>
<body>
  <p><a href="{SITE}">← Agenda interactif</a></p>
  <h1>Agenda de Nyons semaine par semaine</h1>
  <p>Choisissez une semaine pour consulter les sorties et événements annoncés à Nyons.</p>
  <ul>{''.join(cards)}</ul>
  <p>Source : <a href="{BASE}">Ville de Nyons — agenda officiel</a>.</p>
</body>
</html>
"""


def write_sitemap():
    urls = [SITE, f"{SITE}semaines/"]
    if WEEKS_DIR.exists():
        for p in sorted(WEEKS_DIR.glob("semaine-*/index.html")):
            urls.append(f"{SITE}semaines/{p.parent.name}/")

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
    generate_seo_pages(events)


if __name__ == "__main__":
    main()
