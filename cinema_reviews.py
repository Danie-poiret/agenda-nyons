"""Verified editorial review cache: static HTML, no collection or model calls."""
import html
import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
START_DATE = date(2026, 10, 20)


@lru_cache(maxsize=1)
def _read_cache(path, mtime_ns, size):
    # File identity invalidates this in-process cache after an editorial update.
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _https_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username


def render_spectator_reviews(event, today=None):
    """Hide missing/unverified evidence and films whose sessions all precede cutoff."""
    try:
        if event.get("kind") != "cinema":
            return ""
        dates = [date.fromisoformat(s["date"]) for s in event["sessions"]]
        if not dates or max(dates) < START_DATE:
            return ""
        path = ROOT / "cinema-spectator-reviews.json"
        stat = path.stat()
        data = _read_cache(str(path), stat.st_mtime_ns, stat.st_size)
        if data.get("mode") != "verified_from_2026_10_20":
            return ""
        # A title alone is not enough: the verified poster also identifies the film.
        matches = [r for r in data["reviews"].values()
                   if r.get("film_title") == event.get("film_title")
                   and r.get("poster") == event.get("poster") and r.get("poster")]
        if len(matches) != 1:
            return ""
        review = matches[0]
        if (review.get("status") != "editorially_verified"
                or review.get("acquisition") != "manual_one_off"
                or review.get("editorial_basis") != "original_summary_public_reviews"):
            return ""
        checked = date.fromisoformat(review["verified_on"])
        today = today or datetime.now(ZoneInfo("Europe/Paris")).date()
        if checked > today:
            return ""
        sources, evidence, points = review["sources"], review["evidence"], review["points"]
        if (not sources or not all(_https_url(s["url"]) and s["label"].strip() for s in sources)
                or len(evidence) < 2 or not 2 <= len(points) <= 3):
            return ""
        for item in evidence:
            if not item["author"].strip() or not item["observation"].strip():
                return ""
            if date.fromisoformat(item["published_on"]) > checked:
                return ""
            if type(item["source"]) is not int or not 0 <= item["source"] < len(sources):
                return ""
        if not {"liked", "divides"}.issubset({p["kind"] for p in points}):
            return ""
        for point in points:
            if not point["text"].strip() or not point["evidence"]:
                return ""
            if not all(type(i) is int and 0 <= i < len(evidence) for i in point["evidence"]):
                return ""
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ""
    esc = html.escape
    links = " · ".join('<a href="' + esc(s["url"], quote=True) + '">' + esc(s["label"]) + '</a>' for s in sources)
    return ('<section class="section spectator-reviews" aria-labelledby="spectator-reviews-title" '
            'style="min-width:0;overflow-wrap:anywhere">'
            '<h2 id="spectator-reviews-title">🎬 Ce qu’en pensent les spectateurs</h2>'
            + ''.join('<p>' + esc(p["text"]) + '</p>' for p in points)
            + '<p class="source">Synthèse des avis consultés le ' + checked.strftime("%d/%m/%Y")
            + ' · ' + links + '</p></section>')

