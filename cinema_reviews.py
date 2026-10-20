"""Manually verified editorial summaries; pilot only, with no network or AI calls."""
import html
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Expanding this allowlist requires the user's explicit validation of the pilot.
PILOT_URL = "https://agenda.vivreanyons.fr/evenements/cinema-fausse-note-2026-10-14/"

def render_spectator_reviews(event):
    if event.get("page_url") != PILOT_URL or event.get("film_title") != "Fausse Note":
        return ""
    try:
        data = json.loads((ROOT / "cinema-spectator-reviews.json").read_text(encoding="utf-8"))
        review = data.get("reviews", {}).get(PILOT_URL, {})
        if data.get("mode") != "pilot_only" or review.get("status") != "editorially_verified":
            return ""
        if review.get("film_title") != event.get("film_title"):
            return ""
        if review.get("acquisition") != "manual_one_off":
            return ""
        checked = date.fromisoformat(review["verified_on"])
        if checked > date.today():
            return ""
        sources = review["sources"]
        if not sources or not all(s.get("url", "").startswith("https://") and s.get("label") for s in sources):
            return ""
        if not review.get("strengths", "").strip() or not review.get("reservations", "").strip():
            return ""
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""
    esc = html.escape
    links = " · ".join('<a href="' + esc(s["url"], quote=True) + '">' + esc(s["label"]) + '</a>' for s in sources)
    return ('<section class="section spectator-reviews" aria-labelledby="spectator-reviews-title" '
            'style="min-width:0;overflow-wrap:anywhere">'
            '<h2 id="spectator-reviews-title">🎬 Ce qu’en pensent les spectateurs</h2>'
            '<p>' + esc(review["strengths"]) + ' ' + esc(review["reservations"]) + '</p>'
            '<p class="source">Synthèse des avis consultés le ' + checked.strftime("%d/%m/%Y") + ' · ' + links + '</p></section>')

