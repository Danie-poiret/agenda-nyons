#!/usr/bin/env python3
"""Crée un « Le saviez-vous ? » unique et réellement lié à chaque fiche.

Les textes sont conservés dans _saviezvous_cache.json. Une fiche déjà traitée
n'occasionne donc aucun nouvel appel à l'API lors des mises à jour quotidiennes.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

ROOT = Path(__file__).resolve().parent
EVENT_CACHE = ROOT / "_event_seo_cache.json"
FACT_CACHE = ROOT / "_saviezvous_cache.json"
EVENTS_DIR = ROOT / "evenements"
FACT_VERSION = 1
BATCH_SIZE = int(os.getenv("SAVIEZVOUS_BATCH_SIZE", "30"))
MAX_API_CALLS = int(os.getenv("MAX_SAVIEZVOUS_API_CALLS", "8"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")

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

def batch_payload(batch):
    result = []
    for slug, item in batch:
        event = item.get("event") or {}
        editorial = item.get("editorial") or {}
        result.append({"event_key": slug, "title": clean(event.get("title", "")), "reader_question": clean(editorial.get("reader_question", "")), "summary": clean(event.get("summary", ""))[:700], "categories": event.get("categories") or [], "editorial_context": clean(" ".join([editorial.get("seo_title", ""), editorial.get("meta_description", ""), editorial.get("intro", "")]))[:850]})
    return result

def generate_batch(batch, used_texts):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return {}
    schema = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "object", "properties": {"event_key": {"type": "string"}, "text": {"type": "string"}}, "required": ["event_key", "text"], "additionalProperties": False}}}, "required": ["facts"], "additionalProperties": False}
    system = ("Tu es fact-checkeur et médiateur culturel. Pour chaque événement, écris un fait pédagogique en français, réel, prudent et directement lié à son sujet principal. N'invente jamais un fait sur l'événement, son programme ou une personne nommée. Pour un titre artistique obscur, utilise un fait certain sur la discipline clairement indiquée par le résumé : théâtre, musique, danse, littérature, peinture, etc. N'attribue aucun bienfait médical non démontré.")
    prompt = ("Produis exactement un texte pour chaque event_key.\nLe vrai sujet doit être déduit en priorité de title et reader_question, puis confirmé par summary et editorial_context. Reader_question est un indice : ne la recopie pas.\n\nRègles absolues :\n- environ 25 à 55 mots ;\n- fait général vérifiable et lien évident avec le sujet ;\n- aucune invention sur l'événement ou l'artiste ;\n- pas de statistique récente, de conseil médical, d'URL ou de source inventée ;\n- tous les textes doivent être différents, y compris pour les événements portant le même titre ; choisis alors des angles factuels distincts ;\n- ne parle jamais de Nyons par défaut lorsqu'un sujet plus précis existe.\n\n" + f"TEXTES DÉJÀ UTILISÉS:\n{json.dumps(used_texts[-140:], ensure_ascii=False)}\n\n" + f"FICHES:\n{json.dumps(batch_payload(batch), ensure_ascii=False, indent=2)}")
    response = OpenAI(api_key=api_key).responses.create(model=OPENAI_MODEL, store=False, input=[{"role": "system", "content": system}, {"role": "user", "content": prompt}], text={"format": {"type": "json_schema", "name": "agenda_nyons_saviezvous", "strict": True, "schema": schema}})
    data = json.loads(response.output_text)
    expected = {slug: item for slug, item in batch}
    used_keys = {fact_key(text) for text in used_texts}
    result = {}
    for value in data.get("facts", []):
        slug = clean(value.get("event_key", ""))
        text = clean(value.get("text", ""))
        key = fact_key(text)
        if slug in expected and slug not in result and valid_fact(text) and topical_fact(expected[slug], text) and key and key not in used_keys:
            result[slug] = {"text": text, "source_label": ""}
            used_keys.add(key)
    return result

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
    return {"text": clean(fact.get("text", "")), "source_label": clean(fact.get("source_label", "")), "model": model or OPENAI_MODEL, "version": FACT_VERSION, "generated_at": datetime.now(timezone.utc).isoformat()}

def render_fact(page, fact):
    section_re = re.compile(r'<section class="section anecdote"><h2>💡 Le saviez-vous \?</h2>.*?</section>', re.S)
    source = clean(fact.get("source_label", ""))
    source_html = f'<p class="heritage-source">Repère documentaire : {html.escape(source, quote=True)}</p>' if source else ""
    block = '<section class="section anecdote"><h2>💡 Le saviez-vous ?</h2>' + f'<p>{html.escape(clean(fact["text"]), quote=True)}</p>' + source_html + '</section>'
    old = page.read_text(encoding="utf-8")
    new, count = section_re.subn(block, old, count=1)
    if count != 1:
        raise RuntimeError(f"Bloc Le saviez-vous introuvable : {page}")
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
        candidate = manual or cached
        if not isinstance(candidate, dict):
            continue
        text = clean(candidate.get("text", ""))
        key = fact_key(text)
        if valid_fact(text) and (manual or topical_fact(item, text)) and key and key not in used_keys:
            assigned[slug] = {"text": text, "source_label": clean(candidate.get("source_label", ""))}
            used_keys.add(key)
    missing = [(slug, item) for slug, item in entries if slug not in assigned]
    calls = 0
    while missing and calls < MAX_API_CALLS:
        batch = missing[:BATCH_SIZE]
        try:
            generated = generate_batch(batch, [fact["text"] for fact in assigned.values()])
        except Exception as exc:
            print(f"Erreur génération Le saviez-vous : {exc}", file=sys.stderr)
            generated = {}
        calls += 1
        if not generated:
            break
        for slug, fact in generated.items():
            key = fact_key(fact["text"])
            if slug not in assigned and key not in used_keys:
                assigned[slug] = fact
                used_keys.add(key)
        missing = [(slug, item) for slug, item in entries if slug not in assigned]
    if missing:
        sample = ", ".join(slug for slug, _ in missing[:6])
        raise RuntimeError(f"Correction interrompue : {len(missing)} fiche(s) sans fait thématique, dont {sample}")
    if len(used_keys) != len(entries):
        raise RuntimeError("Des textes Le saviez-vous sont encore dupliqués")
    updated_cache = {}
    changed = 0
    for slug, item in entries:
        fact = assigned[slug]
        manual = manual_fact(item)
        old = cached_facts.get(slug) if isinstance(cached_facts, dict) else None
        record = stable_record(fact, old, model="manual" if manual else OPENAI_MODEL)
        updated_cache[slug] = record
        item["anecdote_id"] = "topic-" + hashlib.sha256(record["text"].encode("utf-8")).hexdigest()[:16]
        item["anecdote_assignment_version"] = 100 + FACT_VERSION
        page = EVENTS_DIR / slug / "index.html"
        if not page.exists():
            raise RuntimeError(f"Fiche HTML absente : {page}")
        if render_fact(page, record):
            changed += 1
    fact_cache = {"version": FACT_VERSION, "entries": updated_cache}
    FACT_CACHE.write_text(json.dumps(fact_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    EVENT_CACHE.write_text(json.dumps(event_cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Le saviez-vous : {len(entries)} faits thématiques uniques contrôlés.")
    print(f"Pages modifiées : {changed}. Appels API groupés : {calls}.")
    for wanted in ("lactofermentation", "brownies", "education-populaire"):
        for slug, _item in entries:
            if wanted in slug:
                print(f"CONTROLE {slug}: {assigned[slug]['text']}")
                break

if __name__ == "__main__":
    main()
