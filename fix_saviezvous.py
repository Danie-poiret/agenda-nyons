#!/usr/bin/env python3
"""Crée un « Le saviez-vous ? » unique et réellement lié à chaque fiche.

Réutilise les faits enregistrés dans _saviezvous_cache.json et les repères
manuels, sans API. Sans fait pertinent disponible, le bloc facultatif est omis :
la récupération et la publication des événements continuent normalement.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVENT_CACHE = ROOT / "_event_seo_cache.json"
FACT_CACHE = ROOT / "_saviezvous_cache.json"
FACT_BANK = ROOT / "saviezvous_facts.json"
EVENTS_DIR = ROOT / "evenements"
FACT_VERSION = 1

STOPWORDS = {
    "administratif", "ancien", "ancienne", "apres", "atelier", "avec",
    "cadre", "cette", "dans", "depuis", "drome", "enfance", "entre",
    "evenement", "faire", "fete", "histoire", "journee", "jours", "leur",
    "leurs", "loisirs", "maison", "nyons", "nyonsais", "patrimoine",
    "pendant", "place", "pour", "selon", "solidarite", "ville", "vivante",
    "vous", "envie", "decouvrir", "propose", "rendez", "sortie",
}

THEME_GROUPS = (
    {"petanque", "boule", "boulodrome"},
    {"education", "populaire", "instruction", "ecole", "enseignement", "citoyennete"},
    {"musique", "musical", "musicien", "concert", "chant", "voix", "vocal", "opera", "jazz", "maqam", "corde"},
    {"theatre", "theatral", "scene", "comedie", "impro", "spectacle", "piece", "conte", "dramaturgie"},
    {"livre", "lecture", "litterature", "ecrivain", "auteur", "roman", "poesie", "dedicace"},
    {"peinture", "peintre", "tableau", "artiste", "exposition", "picasso", "chagall", "bruegel", "art"},
    {"agriculture", "agricole", "agriculteur", "paysan", "vendange", "vigne", "vin", "jardin"},
    {"cuisine", "culinaire", "tapenade", "olive", "gnocchi", "risotto", "brownie", "cacao", "chocolat", "gastronomie"},
    {"fermentation", "lactofermentation", "lactique", "fermente", "bacterie", "acidification"},
    {"science", "scientifique", "geologie", "gres", "glaciation", "fossile", "climat", "pi"},
    {"yoga", "meditation", "respiration", "souffle", "posture", "chant", "voix"},
    {"danse", "danser", "ballet", "mouvement", "landing"},
    {"photo", "photographie", "photographe", "urbex"},
    {"cinema", "film", "projection", "documentaire", "realisateur", "cine", "debat"},
    {"jeu", "jeux", "carte", "cartes", "belote", "loto"},
    {"sante", "mental", "psychique", "unafam", "therapie"},
    {"funeraire", "obseque", "deces", "rituel", "volonte", "directive"},
    {"compost", "dechet", "organique", "sol"},
    {"ruche", "abeille", "miel", "pollinisateur"},
    {"trail", "course", "sentier", "endurance", "sport"},
    {"couture", "couturiere", "textile", "tissu", "soie"},
)

def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

def norm(value) -> str:
    text = unicodedata.normalize("NFKD", clean(value).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))

def terms(value) -> set[str]:
    result = set()
    for word in norm(value).split():
        if len(word) < 4 or word in STOPWORDS:
            continue
        result.add(word)
        if len(word) > 5 and word.endswith("s"):
            result.add(word[:-1])
    return result

def fact_key(text) -> str:
    return re.sub(r"\s+", " ", norm(text)).strip()

def event_context(item) -> str:
    event = item.get("event") or {}
    editorial = item.get("editorial") or {}
    return " ".join([
        clean(event.get("title", "")),
        clean(editorial.get("reader_question", "")),
        clean(event.get("summary", "")),
        clean(editorial.get("seo_title", "")),
        clean(editorial.get("meta_description", "")),
        clean(editorial.get("intro", "")),
        " ".join(event.get("categories") or []),
    ])

def valid_fact(text) -> bool:
    text = clean(text)
    count = len(text.split())
    return (18 <= count <= 75 and not re.search(r"https?://|www\.", text, re.I) and not re.search(r"\b(peut-être|probablement|il semble|on peut supposer)\b", text, re.I))

def topical_fact(item, text) -> bool:
    context = event_context(item)
    if terms(context) & terms(text):
        return True
    context_words = set(norm(context).split())
    fact_words = set(norm(text).split())
    return any(context_words & group and fact_words & group for group in THEME_GROUPS)

def manual_fact(item):
    subject = norm(event_context(item))
    if "lactofermentation" in subject:
        return {"text": "Lors de la lactofermentation, des bactéries lactiques transforment les sucres de l’aliment en acides. Cette acidification freine le développement de nombreux micro-organismes indésirables et contribue ainsi à la conservation.", "source_label": "INRAE — Le potentiel des aliments fermentés"}
    if "brownies" in subject or "brownie" in subject:
        return {"text": "Le Palmer House de Chicago rattache la création de son brownie à l’Exposition universelle de 1893. Bertha Palmer souhaitait alors un dessert chocolaté plus facile à transporter qu’une part de gâteau.", "source_label": "Palmer House, Chicago — The Brownie"}
    if "education populaire" in subject:
        return {"text": "En France, l’éducation populaire trouve notamment ses racines dans le rapport sur l’instruction publique présenté par Condorcet en 1792 ; elle vise l’accès du plus grand nombre aux savoirs, à la culture et à la citoyenneté.", "source_label": "INJEP — L’éducation populaire en France, fiche repère"}
    if "8 jours de la ville" in subject or "petanque" in subject:
        return {"text": "La pétanque moderne est née à La Ciotat en 1907. Son nom vient du provençal « pèd tanca », qui signifie jouer les pieds plantés.", "source_label": "Fédération Française de Pétanque et de Jeu Provençal"}
    return None

def bank_candidates(item):
    if not FACT_BANK.exists():
        return []
    data = json.loads(FACT_BANK.read_text(encoding="utf-8"))
    # Match the actual subject, not the broad administrative categories.
    event = item.get("event") or {}
    subject = " " + norm(clean(event.get("title")) + " " + clean(event.get("summary"))) + " "
    return [fact for fact in data["facts"]
            if any(" " + norm(word) + " " in subject for word in fact.get("match", []))]


def load_fact_cache():
    if not FACT_CACHE.exists():
        return {"version": FACT_VERSION, "entries": {}}
    try:
        data = json.loads(FACT_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": FACT_VERSION, "entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"version": FACT_VERSION, "entries": {}}
    return data

def stable_record(fact, old=None, model=None):
    old = old if isinstance(old, dict) else {}
    if clean(old.get("text")) == clean(fact.get("text")):
        return old
    record = {"text": clean(fact.get("text", "")), "source_label": clean(fact.get("source_label", "")), "model": model or "cache", "version": FACT_VERSION, "generated_at": datetime.now(timezone.utc).isoformat()}
    if fact.get("source_url"):
        record["source_url"] = fact["source_url"]
    return record

def render_fact(page, fact):
    section_re = re.compile(r'<section class="section anecdote"><h2>💡 Le saviez-vous \?</h2>.*?</section>', re.S)
    if fact is None:
        old = page.read_text(encoding="utf-8")
        new = section_re.sub("", old)
        if new != old:
            page.write_text(new, encoding="utf-8")
            return True
        return False
    source = clean(fact.get("source_label", ""))
    source_html = html.escape(source, quote=True)
    url = clean(fact.get("source_url"))
    if source and url.startswith("https://"):
        source_html = f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{source_html}</a>'
    source_html = f'<p class="heritage-source">Repère documentaire : {source_html}</p>' if source else ""
    block = '<section class="section anecdote"><h2>💡 Le saviez-vous ?</h2>' + f'<p>{html.escape(clean(fact["text"]), quote=True)}</p>' + source_html + '</section>'
    old = page.read_text(encoding="utf-8")
    new, count = section_re.subn(block, old, count=1)
    if count == 0:
        # A previous keyless run may have omitted this optional section.
        anchor = '<div class="question">' if '<div class="question">' in old else '</main>'
        if anchor not in old:
            raise RuntimeError(f"Emplacement Le saviez-vous introuvable : {page}")
        new = old.replace(anchor, block + "\n    " + anchor, 1)
    if new != old:
        page.write_text(new, encoding="utf-8")
        return True
    return False

def main():
    event_cache = json.loads(EVENT_CACHE.read_text(encoding="utf-8"))
    fact_cache = load_fact_cache()
    cached_facts = fact_cache.get("entries", {})
    entries = []
    for url, item in event_cache.items():
        slug = clean(item.get("slug", ""))
        if slug and item.get("event") and item.get("editorial"):
            entries.append((slug, item))
    entries.sort(key=lambda row: (clean((row[1].get("event") or {}).get("start_date", "")), row[0]))
    assigned = {}
    used_keys = set()
    for slug, item in entries:
        manual = manual_fact(item)
        cached = cached_facts.get(slug) if isinstance(cached_facts, dict) else None
        for candidate in (manual, cached):
            if not isinstance(candidate, dict):
                continue
            text = clean(candidate.get("text", ""))
            key = fact_key(text)
            if valid_fact(text) and topical_fact(item, text) and key and key not in used_keys:
                assigned[slug] = dict(candidate, text=text, source_label=clean(candidate.get("source_label", "")))
                used_keys.add(key)
                break
    # Reserve every existing fact before filling gaps from the curated bank.
    for slug, item in entries:
        if slug in assigned:
            continue
        for candidate in bank_candidates(item):
            text = clean(candidate.get("text"))
            key = fact_key(text)
            if valid_fact(text) and topical_fact(item, text) and key and key not in used_keys:
                assigned[slug] = dict(candidate, text=text)
                used_keys.add(key)
                break
    missing = [(slug, item) for slug, item in entries if slug not in assigned]
    if len(used_keys) != len(assigned):
        raise RuntimeError("Des textes Le saviez-vous sont encore dupliqués")
    updated_cache = dict(cached_facts)
    changed = 0
    for slug, item in entries:
        page = EVENTS_DIR / slug / "index.html"
        if not page.exists():
            raise RuntimeError(f"Fiche HTML absente : {page}")
        if slug not in assigned:
            if render_fact(page, None):
                changed += 1
            item.pop("anecdote_id", None)
            item.pop("anecdote_assignment_version", None)
            continue
        fact = assigned[slug]
        manual = manual_fact(item)
        old = cached_facts.get(slug) if isinstance(cached_facts, dict) else None
        record = stable_record(fact, old, model="manual" if manual else ("local-bank" if fact.get("id") else "cache"))
        updated_cache[slug] = record
        item["anecdote_id"] = "topic-" + hashlib.sha256(record["text"].encode("utf-8")).hexdigest()[:16]
        item["anecdote_assignment_version"] = 100 + FACT_VERSION
        if render_fact(page, record):
            changed += 1
    fact_cache = {"version": FACT_VERSION, "entries": updated_cache}
    FACT_CACHE.write_text(json.dumps(fact_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    EVENT_CACHE.write_text(json.dumps(event_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Le saviez-vous : {len(assigned)} faits thématiques uniques conservés, {len(missing)} blocs facultatifs omis.")
    print(f"Pages modifiées : {changed}. Aucun appel API.")
    for wanted in ("lactofermentation", "brownies", "education-populaire"):
        for slug, _item in entries:
            if wanted in slug and slug in assigned:
                print(f"CONTROLE {slug}: {assigned[slug]['text']}")
                break

if __name__ == "__main__":
    main()
