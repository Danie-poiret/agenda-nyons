"""Block publication when a current non-cinema event has an incomplete template."""
import json
from pathlib import Path
from bs4 import BeautifulSoup
from cinema_agenda import paris_today
from event_cache import preferred_event_entries


def audit(root):
    cache = json.loads((root/'_event_seo_cache.json').read_text(encoding='utf8'))
    active = json.loads((root/'agenda.json').read_text(encoding='utf8'))['events']
    today = paris_today().isoformat()
    errors = []
    checked = 0
    for item in preferred_event_entries(cache, active):
        if item['event'].get('end_date', '') < today:
            continue
        checked += 1
        slug = item['slug']
        page = root/'evenements'/slug/'index.html'
        if not page.exists():
            errors.append(f'{slug}: fiche absente')
            continue
        soup = BeautifulSoup(page.read_text(encoding='utf8'), 'html.parser')
        for selector in ['h1', '.lead', '.practical-box', '.anecdote p', '.question', '.source a[href]', '.calendar-action']:
            node = soup.select_one(selector)
            if not node or not node.get_text(' ', strip=True):
                errors.append(f'{slug}: bloc absent ou vide ({selector})')
        if (item.get('practical') or {}).get('address') and not soup.select_one('.map-action'):
            errors.append(f'{slug}: itinéraire absent')
        text = soup.get_text(' ', strip=True)
        for generic in ['Pour préparer votre sortie, retrouvez ci-dessus', 'Qu’aimeriez-vous découvrir lors de']:
            if generic in text:
                errors.append(f'{slug}: ancien texte générique')
    return checked, errors


if __name__ == '__main__':
    checked, errors = audit(Path(__file__).resolve().parent)
    print(f'Fiches actuelles contrôlées : {checked}. Anomalies : {len(errors)}.')
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))
