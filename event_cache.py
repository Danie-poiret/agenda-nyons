"""Choose one public page per slug, favouring the current municipal URL."""


def preferred_event_entries(cache, active=()):
    current_urls = {event['url'] for event in active}
    selected = {}
    for url, item in cache.items():
        event = item.get('event') or {}
        slug = item.get('slug')
        if not slug or not event or not item.get('editorial') or event.get('kind') == 'cinema':
            continue
        priority = (url in current_urls, item.get('generated_at') or '', url)
        if slug not in selected or priority > selected[slug][0]:
            selected[slug] = (priority, item)
    return [row[1] for _, row in sorted(selected.items())]
