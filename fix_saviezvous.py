#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "_event_seo_cache.json"
ANECDOTES = ROOT / "nyons_anecdotes.json"
EVENTS = ROOT / "evenements"
VERSION = 3

STOPWORDS = {
    "administratif", "ancien", "ancienne", "apres", "atelier", "avec", "cadre",
    "cette", "dans", "depuis", "des", "drome", "enfance", "entre", "evenement",
    "faire", "fete", "histoire", "journee", "jours", "leur", "leurs", "loisirs",
    "maison", "nyons", "nyonsais", "patrimoine", "pendant", "place", "pour",
    "sante", "selon", "solidarite", "sport", "ville", "vivante", "vous",
}

THEME_GROUPS = (
    {"petanque", "boule", "boulodrome"},
    {"education", "populaire", "instruction", "ecole", "enseignement", "savoir", "citoyennete"},
    {"musique", "musical", "concert", "chant", "chorale", "opera", "jazz", "quartet"},
    {"theatre", "scene", "comedie", "impro", "spectacle"},
    {"livre", "lecture", "litterature", "ecrivain", "auteur", "barjavel", "camus"},
    {"peinture", "peintre", "tableau", "artiste", "expo", "exposition", "picasso", "chagall", "bruegel"},
    {"agriculture", "agricole", "paysan", "vendange", "vigne", "vin"},
    {"cuisine", "culinaire", "tapenade", "olive", "olivier", "gnocchi", "risotto", "gastronomie"},
    {"science", "scientifique", "geologie", "gres", "glaciation", "fossile"},
    {"yoga", "meditation", "bienetre", "respiration"},
    {"danse", "danser", "ballet"},
    {"photo", "photographie", "photographe"},
    {"cinema", "film", "projection"},
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    text = unicodedata.normalize("NFKD", clean(value).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def terms(value):
    out = set()
    for word in norm(value).split():
        if len(word) < 4 or word in STOPWORDS:
            continue
        out.add(word)
        if len(word) > 5 and word.endswith("s"):
            out.add(word[:-1])
    return out


def score(event, anecdote):
    title = clean(event.get("title", ""))
    title_norm = norm(title)
    title_terms = terms(title)

    a_title = clean(anecdote.get("article_title", ""))
    a_text = clean(anecdote.get("text", ""))
    a_terms = terms(a_title + " " + a_text)
    a_title_terms = terms(a_title)

    s = 0

    # PRIORITÉ ABSOLUE AU TITRE DE L'ÉVÉNEMENT.
    shared_title = title_terms & a_terms
    shared_titles = title_terms & a_title_terms
    s += len(shared_title) * 30
    s += len(shared_titles) * 45

    # Les match_phrases sont des correspondances documentaires explicites.
    for phrase in anecdote.get("match_phrases") or []:
        p = norm(phrase)
        if p and p in title_norm:
            s += 150

    # Familles sémantiques : pétanque/boule, éducation/instruction, etc.
    for group in THEME_GROUPS:
        if title_terms & group and a_terms & group:
            s += 60

    # Résumé et titre SEO seulement comme second niveau.
    context = " ".join([
        clean(event.get("summary", "")),
        clean(event.get("editorial", {}).get("seo_title", "")),
        clean(event.get("editorial", {}).get("meta_description", "")),
    ])
    context_terms = terms(context)
    s += len(context_terms & a_terms) * 2

    return s


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    payload = json.loads(ANECDOTES.read_text(encoding="utf-8"))
    anecdotes = [a for a in payload.get("entries", []) if isinstance(a, dict) and a.get("id") and a.get("text")]
    catalog = {a["id"]: a for a in anecdotes}

    entries = []
    for url, item in cache.items():
        event = dict(item.get("event") or {})
        if not event or not item.get("slug"):
            continue
        event["editorial"] = item.get("editorial") or {}
        entries.append((url, item, event))

    # Toutes les attributions sont recalculées : aucune ancienne anecdote générique
    # n'est conservée simplement parce qu'elle était en cache.
    candidates = []
    for url, item, event in entries:
        for anecdote in anecdotes:
            candidates.append((score(event, anecdote), url, anecdote["id"]))

    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    assigned = {}
    used = set()

    # On retient d'abord les vraies correspondances sémantiques.
    for s, url, anecdote_id in candidates:
        if s <= 0 or url in assigned or anecdote_id in used:
            continue
        assigned[url] = anecdote_id
        used.add(anecdote_id)

    # Si aucun rapport thématique n'existe, on utilise une anecdote unique de secours.
    remaining = [a["id"] for a in anecdotes if a["id"] not in used]
    for url, item, event in entries:
        if url in assigned:
            continue
        if not remaining:
            break
        assigned[url] = remaining.pop(0)

    section_re = re.compile(
        r'<section class="section anecdote"><h2>💡 Le saviez-vous \?</h2>.*?</section>',
        re.S,
    )

    changed = 0
    for url, item, event in entries:
        anecdote_id = assigned.get(url)
        anecdote = catalog.get(anecdote_id)
        if not anecdote:
            continue

        item["anecdote_id"] = anecdote_id
        item["anecdote_assignment_version"] = VERSION

        page = EVENTS / item["slug"] / "index.html"
        if not page.exists():
            continue

        source = clean(anecdote.get("source_label") or "Repère documentaire")
        block = (
            '<section class="section anecdote"><h2>💡 Le saviez-vous ?</h2>'
            f'<p>{html.escape(clean(anecdote["text"]), quote=True)}</p>'
            f'<p class="heritage-source">Repère documentaire : {html.escape(source, quote=True)}</p>'
            '</section>'
        )

        old = page.read_text(encoding="utf-8")
        new, n = section_re.subn(block, old, count=1)
        if n and new != old:
            page.write_text(new, encoding="utf-8")
            changed += 1

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Le saviez-vous : {changed} fiche(s) mise(s) à jour.")
    print(f"Attributions sémantiques recalculées : {len(assigned)}.")

    # Contrôle ciblé demandé : éducation populaire doit utiliser son anecdote dédiée.
    for url, item, event in entries:
        if "education-populaire" in item.get("slug", ""):
            a = catalog.get(item.get("anecdote_id"), {})
            print("CONTROLE EDUCATION POPULAIRE:", clean(a.get("text", "")))


if __name__ == "__main__":
    main()
