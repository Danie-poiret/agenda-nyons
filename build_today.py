#!/usr/bin/env python3
"""Build Nyons today from existing files only. No event generator or OpenAI import."""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PARIS = ZoneInfo("Europe/Paris")
MONTHS = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
BUTTON = '<a id="nyons-today-link" class="btn btn-main" href="/aujourdhui/">☀️ NYONS AUJOURD’HUI</a>'


def esc(value):
    return html.escape(str(value or ""), quote=True)


def pretty(day):
    d = date.fromisoformat(day)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month]} {d.year}"


def event_path(event):
    from urllib.parse import urlparse
    if event.get("page_url"):
        parsed = urlparse(event["page_url"])
        if parsed.netloc in ("", "agenda.vivreanyons.fr") and parsed.path.startswith("/evenements/"):
            return parsed.path
    raw = unicodedata.normalize("NFKD", event["title"])
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:82].rstrip("-") or "evenement"
    return f"/evenements/{slug}-{event['start_date']}/"


def today_events(events, day):
    return sorted(
        [e for e in events if e.get("kind") != "cinema"
         and e.get("start_date", "9999") <= day <= (e.get("end_date") or e["start_date"])],
        key=lambda e: (e["start_date"], e["title"]),
    )


def today_sessions(programme, day):
    return sorted(
        [(film, s) for film in programme["films"] for s in film.get("sessions", []) if s["date"] == day],
        key=lambda item: (item[1]["time"], item[0]["title"]),
    )


def market_text(day):
    d = date.fromisoformat(day)
    if d.weekday() == 3:
        return "Grand marché traditionnel le matin aujourd’hui."
    next_day = d + timedelta(days=(3 - d.weekday()) % 7)
    return f"Prochain grand marché traditionnel : {pretty(next_day.isoformat())}, le matin."


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def normalize_weather(data, day, now=None):
    forecast = next(d for d in data["weather"] if d["date"] == day)
    current = (data.get("current_condition") or [{}])[0]
    obs = current.get("localObsDateTime", "")
    valid = obs[:10] == day
    match = re.search(r" (\d{1,2}):(\d{2})(?:\s*(AM|PM))?", obs, re.I)
    observation = ""
    if valid and match:
        hour = int(match[1])
        if match[3]:
            hour = hour % 12 + (12 if match[3].upper() == "PM" else 0)
        observation = f"{hour:02d} h {match[2]}"
    hourly = forecast.get("hourly", [])
    rain = [number(h.get("precipMM")) for h in hourly]
    wind = [number(h.get("windspeedKmph")) for h in hourly]
    now = now or datetime.now(PARIS)
    minutes = now.astimezone(PARIS).hour * 60 + now.astimezone(PARIS).minute
    nearest = min(hourly, key=lambda h: abs(int(h.get("time", 0)) // 100 * 60 + int(h.get("time", 0)) % 100 - minutes), default={})
    if not valid:
        hour = int(nearest.get("time", 0)) // 100
        minute = int(nearest.get("time", 0)) % 100
        observation = f"{hour:02d} h {minute:02d}"
    condition = current if valid else nearest
    desc = (condition.get("lang_fr") or condition.get("weatherDesc") or [{}])[0].get("value", "")
    return {
        "date": day, "temperature": number(current.get("temp_C")) if valid else number(nearest.get("tempC")),
        "observation": observation, "isForecast": not valid, "min": number(forecast.get("mintempC")),
        "max": number(forecast.get("maxtempC")),
        "rain": round(sum(rain), 1) if rain and all(n is not None for n in rain) else None,
        "wind": number(current.get("windspeedKmph")) if valid else number(nearest.get("windspeedKmph")),
        "windMax": max(wind) if wind and all(n is not None for n in wind) else None,
        "description": desc, "fetched_at": (now or datetime.now(PARIS)).isoformat(),
    }


def refresh_weather(root, day):
    path = root / "aujourdhui/meteo.json"
    for host in ("wttr.is", "wttr.in"):
        try:
            request = Request(f"https://{host}/44.36,5.14?format=j1&lang=fr",
                              headers={"User-Agent": "AgendaNyons/1.0 (+https://agenda.vivreanyons.fr/)", "Accept": "application/json"})
            with urlopen(request, timeout=15) as response:
                data = normalize_weather(json.load(response), day)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Météo : données du jour reçues de {host}.")
            return
        except Exception as error:
            print(f"Météo {host} indisponible ({type(error).__name__}); essai de secours.")
    print("Météo : sélection publiée sans bloquer l’agenda, dernier instantané conservé.")


def fmt(value):
    return "Non disponible" if value is None else f"{value:g}".replace(".", ",")


def weather_html(weather, day, now):
    try:
        age = (now - datetime.fromisoformat(weather["fetched_at"])).total_seconds()
        if weather["date"] != day or not 0 <= age <= 21600:
            raise ValueError("stale")
    except (KeyError, ValueError, TypeError):
        return '<p>Chargement de la météo du jour… <a href="https://wttr.in/Nyons?lang=fr">Consulter la météo de Nyons</a>.</p>'
    values = [
        (("Température prévue vers " if weather.get("isForecast") else "Température à ") + (weather.get("observation") or "la dernière mise à jour"),
         fmt(weather.get("temperature")) + (" °C" if weather.get("temperature") is not None else "")),
        ("Mini / maxi prévus", f"{fmt(weather.get('min'))} / {fmt(weather.get('max'))} °C"),
        ("Pluie prévue sur la journée", fmt(weather.get("rain")) + (" mm" if weather.get("rain") is not None else "")),
        (("Vent prévu" if weather.get("isForecast") else "Vent") if weather.get("wind") is not None else "Vent maximal prévu",
         fmt(weather.get("wind") if weather.get("wind") is not None else weather.get("windMax")) + " km/h"),
    ]
    cards = "".join(f'<div class="weather-metric"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>' for label, value in values)
    return f'<div class="weather-grid">{cards}</div><p>{esc(weather.get("description", ""))}</p><p class="muted">Météo du {esc(pretty(day))}. Prévisions et dernière observation disponible.</p>'


def build(root=ROOT, now=None, weather=False):
    root = Path(root)
    now = now or datetime.now(PARIS)
    day = now.astimezone(PARIS).date().isoformat()
    output = root / "aujourdhui"
    output.mkdir(exist_ok=True)
    if weather:
        refresh_weather(root, day)
    agenda = json.loads((root / "agenda.json").read_text(encoding="utf-8"))
    programme = json.loads((root / "cinema-programme.json").read_text(encoding="utf-8"))
    events = today_events(agenda["events"], day)
    cards = []
    for event in events:
        path = event_path(event)
        label = pretty(day) if event["start_date"] == (event.get("end_date") or event["start_date"]) else f"Du {pretty(event['start_date'])} au {pretty(event.get('end_date') or event['start_date'])}"
        cards.append(f'<article class="event"><div class="event-date">{esc(label)}</div><h3><a href="{esc(path)}">{esc(event["title"])}</a></h3><p>{esc(event.get("summary", ""))}</p><a class="card-link" href="{esc(path)}">Voir la fiche →</a></article>')
    event_content = "".join(cards) or '<p>Aucun événement annoncé pour cette date dans notre agenda. <a href="/evenements/">Voir tous les événements</a>.</p>'
    links = {e.get("film_title") or e.get("film", {}).get("title"): event_path(e)
             for e in agenda["events"] if e.get("kind") == "cinema"}
    sessions = []
    for film, session in today_sessions(programme, day):
        path = links.get(film["title"], "/cinema/")
        past = session["time"] < now.astimezone(PARIS).strftime("%H:%M")
        label = session.get("version", "") + (" · " + film["duration"] if film.get("duration") else "") + (" · Séance passée" if past else "")
        sessions.append(f'<article class="session{" session-past" if past else ""}"><div class="session-time"><time datetime="{day}T{esc(session["time"])}">{esc(session["time"].replace(":", " h "))}</time></div><div><h3><a href="{esc(path)}">{esc(film["title"])}</a></h3><p>{esc(label)}</p><a class="card-link" href="{esc(path)}">Voir les horaires du film →</a></div></article>')
    uncovered = day < programme["period_start"] or day > programme["period_end"]
    cinema_content = "".join(sessions) or ('<p>Le programme disponible ne couvre pas ces dates. <a href="https://www.cinema-arlequin.fr/">Consulter le programme officiel de L’Arlequin</a>.</p>' if uncovered else '<p>Aucune séance annoncée à cette date dans le programme disponible.</p>')
    try:
        snapshot = json.loads((output / "meteo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
        (output / "meteo.json").write_text("{}\n", encoding="utf-8")
    values = {
        "DAY": day, "DATE": esc(pretty(day)), "MARKET": esc(market_text(day)),
        "EVENTS": event_content, "CINEMA": cinema_content,
        "WEATHER": weather_html(snapshot, day, now),
        "UPDATED": esc("Agenda actualisé le " + pretty(agenda["updated_at"][:10]) + ".") if agenda.get("updated_at") else "",
    }
    page = (root / "templates/nyons-today.html").read_text(encoding="utf-8")
    for key, value in values.items():
        page = page.replace(f"@@{key}@@", value)
    if re.search(r"@@[A-Z]+@@", page):
        raise ValueError("Unfilled template")
    (output / "index.html").write_text(page, encoding="utf-8")
    home_path = root / "index.html"
    home = home_path.read_text(encoding="utf-8")
    if 'id="nyons-today-link"' not in home:
        if '<div class="buttons">' not in home:
            raise ValueError("Homepage buttons not found")
        home = home.replace('<div class="buttons">', '<div class="buttons">\n      ' + BUTTON, 1)
        home_path.write_text(home, encoding="utf-8")
    sitemap_path = root / "sitemap.xml"
    sitemap = sitemap_path.read_text(encoding="utf-8")
    url = "https://agenda.vivreanyons.fr/aujourdhui/"
    if f"<loc>{url}</loc>" not in sitemap:
        sitemap_path.write_text(sitemap.replace("</urlset>", f"  <url><loc>{url}</loc><lastmod>{day}</lastmod></url>\n</urlset>"), encoding="utf-8")
    print(f"Nyons aujourd’hui : {day}, {len(events)} événements, {len(sessions)} séances. Aucun appel OpenAI.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--weather", action="store_true", help="Fetch free wttr.in weather; default uses only saved data")
    build(weather=parser.parse_args().weather)
