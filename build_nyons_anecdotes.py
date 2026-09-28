#!/usr/bin/env python3
"""Construit un catalogue d'histoires locales depuis les sommaires Terre d'Eygues.

Ce script sert uniquement à actualiser manuellement le catalogue. Le site utilise
ensuite le fichier JSON enregistré dans le dépôt, sans solliciter Terre d'Eygues
à chaque mise à jour de l'agenda.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


API_URL = (
    "https://terre-eygues.net/wp-json/wp/v2/pages"
    "?per_page=100&page=1&_fields=slug,link,content"
)
OUTPUT = Path(__file__).resolve().parent / "nyons_anecdotes.json"


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class SummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.issue = ""
        self.rows: list[dict[str, str]] = []
        self._heading_tag = ""
        self._heading_parts: list[str] = []
        self._in_p = False
        self._in_strong = False
        self._in_em = False
        self._strong_parts: list[str] = []
        self._current_strong: list[str] = []
        self._em_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"h3", "h4", "h5"}:
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "p":
            self._in_p = True
            self._strong_parts = []
            self._current_strong = []
            self._em_parts = []
        elif self._in_p and tag == "strong":
            self._in_strong = True
            self._current_strong = []
        elif self._in_p and tag == "em":
            self._in_em = True

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag:
            heading = clean("".join(self._heading_parts))
            if re.search(r"num[ée]ro\s+\d+", heading, re.I):
                self.issue = heading
            self._heading_tag = ""
        elif tag == "strong" and self._in_strong:
            text = clean("".join(self._current_strong))
            if text:
                self._strong_parts.append(text)
            self._in_strong = False
        elif tag == "em":
            self._in_em = False
        elif tag == "p" and self._in_p:
            if self._strong_parts:
                self.rows.append(
                    {
                        "title": self._strong_parts[-1],
                        "summary": clean("".join(self._em_parts)),
                        "issue": self.issue,
                    }
                )
            self._in_p = False
            self._in_strong = False
            self._in_em = False

    def handle_data(self, data: str) -> None:
        if self._heading_tag:
            self._heading_parts.append(data)
        if self._in_strong:
            self._current_strong.append(data)
        if self._in_em:
            self._em_parts.append(data)


SKIP = re.compile(
    r"^(?:sommaire|le mot|édito|edito|livres?(?:,| et|$)|revues?$|courrier|"
    r"cliquez|téléchargez|abonnement|le dossier$|rechercher|confidentialité|"
    r"assemblée générale|nos activités|in memoriam|un objet du musée$|"
    r"chroniques villageoises$|lecture d.un paysage$|patrimoine immatériel$|"
    r"pages provençales$|portrait$|hommage à|annonce de)",
    re.I,
)

LOCAL = re.compile(
    r"nyons|nyonsais|baronnies|eygues|pontias|randonne|arcades|saint-vincent|"
    r"champ de mars|oliv|scourtin|condorcet|venterol|mirabel|aubres|vinsobres|"
    r"sainte-jalle|les pilles|buis|rémuzat|taulignan|mollans|séderon|montbrun|"
    r"m[ée]vouillon|saint-may|rosans|la charce|vall[ée]e du lez",
    re.I,
)


TEMPLATES = (
    "La mémoire locale garde aussi l’histoire de « {title} ». Terre d’Eygues en a publié une étude en {year}.",
    "Parmi les épisodes documentés dans le Nyonsais figure « {title} », présenté par Terre d’Eygues en {year}.",
    "Un détail du patrimoine local a retenu l’attention de Terre d’Eygues : « {title} », dans son édition de {year}.",
    "Les archives de Terre d’Eygues font ressortir un sujet inattendu : « {title} », étudié en {year}.",
    "Saviez-vous que « {title} » appartient aux sujets conservés par la revue Terre d’Eygues depuis {year} ?",
    "Terre d’Eygues a remis en lumière « {title} » dans un numéro de {year}, afin d’en préserver la mémoire.",
    "Une curiosité des archives locales concerne « {title} ». Terre d’Eygues l’a documentée en {year}.",
    "La revue Terre d’Eygues conserve une trace de « {title} » dans son édition de {year}.",
)


def fetch_pages() -> list[dict]:
    request = Request(API_URL, headers={"User-Agent": "agenda-nyons/1.0"})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def main() -> None:
    candidates: list[dict[str, str | int]] = []
    seen_titles: set[str] = set()

    for page in fetch_pages():
        match = re.fullmatch(r"terre-d-?eygues-(19\d{2}|20\d{2})", page.get("slug", ""))
        if not match:
            continue

        year = match.group(1)
        parser = SummaryParser()
        parser.feed(page.get("content", {}).get("rendered", ""))

        for row in parser.rows:
            title = clean(row["title"]).strip(" .–—-")
            normalized = re.sub(r"\W+", " ", title.lower()).strip()
            short_unlocated = len(title.split()) < 3 and not LOCAL.search(title)
            if (
                len(title) < 9
                or len(title) > 190
                or short_unlocated
                or SKIP.search(title)
                or normalized in seen_titles
            ):
                continue

            seen_titles.add(normalized)
            summary = clean(row.get("summary", ""))
            is_local = bool(LOCAL.search(title + " " + summary))
            priority = (4 if summary and is_local else 3 if is_local else 2 if summary else 1)
            candidates.append(
                {
                    "title": title,
                    "year": year,
                    "issue": clean(row.get("issue", "")),
                    "source_url": page["link"],
                    "priority": priority,
                }
            )

    candidates.sort(key=lambda item: (-int(item["priority"]), -int(item["year"]), str(item["title"]).lower()))
    entries: list[dict[str, str]] = []
    for candidate in candidates:
        title = str(candidate["title"])
        year = str(candidate["year"])
        template = TEMPLATES[len(entries) % len(TEMPLATES)]
        entries.append(
            {
                "id": hashlib.sha256(f"{year}|{title}".encode("utf-8")).hexdigest()[:16],
                "text": template.format(title=title, year=year),
                "article_title": title,
                "publication_year": year,
                "issue": str(candidate["issue"]),
                "source_label": f"Terre d’Eygues — {title} ({year})",
                "source_url": str(candidate["source_url"]),
            }
        )

    payload = {
        "source": "Terre d’Eygues — Histoire et Patrimoine du Nyonsais et des Baronnies",
        "source_index": "https://terre-eygues.net/revue/achat-et-telechargement/",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(entries)} histoires locales enregistrées dans {OUTPUT.name}")


if __name__ == "__main__":
    main()
