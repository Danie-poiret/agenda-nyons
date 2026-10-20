"""Focused checks for date scope, evidence gates, caching and HTML isolation."""
import copy
import json
import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import cinema_agenda as cinema
import cinema_reviews as reviews

TODAY = date(2026, 10, 20)
BOX = re.compile(r'<section class="section spectator-reviews".*?</section>', re.S)


class SpectatorReviewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = cinema.load_programme()
        cls.events = [cinema.film_event(f) for f in cls.cfg['films']]
        cls.cars = next(e for e in cls.events if e['film_title'] == 'Cars')
        cls.cache = json.loads((reviews.ROOT / 'cinema-spectator-reviews.json').read_text(encoding='utf-8'))

    def render(self, event):
        return reviews.render_spectator_reviews(event, TODAY)

    def test_real_session_cutoff_and_future_reprogramming(self):
        event = copy.deepcopy(self.cars)
        for dates, expected in [(['2026-10-19'], False),
                                (['2026-10-14', '2026-10-20'], True),
                                (['2027-01-01'], True), ([], False)]:
            event['sessions'] = [{'date': d} for d in dates]
            event['page_url'] = 'https://agenda.vivreanyons.fr/evenements/reprogrammation/'
            self.assertEqual(bool(self.render(event)), expected)

    def test_non_cinema_and_wrong_identity_hidden(self):
        for field, value in [('kind', 'concert'), ('poster', 'other'), ('film_title', 'Other')]:
            event = dict(self.cars, **{field: value})
            self.assertEqual(self.render(event), '')

    def test_invalid_evidence_and_drafts_hidden(self):
        for field, value in [('status', 'draft'), ('sources', []), ('points', []),
                             ('evidence', []), ('verified_on', '2026-10-21'),
                             ('acquisition', 'scraped'), ('editorial_basis', '')]:
            cache = copy.deepcopy(self.cache)
            cache['reviews']['allocine:55774'][field] = value
            with patch.object(reviews, '_read_cache', return_value=cache):
                self.assertEqual(self.render(self.cars), '', field)
        for error in [FileNotFoundError(), ValueError('invalid JSON')]:
            with patch.object(reviews, '_read_cache', side_effect=error):
                self.assertEqual(self.render(self.cars), '')

    def test_cache_reused(self):
        reviews._read_cache.cache_clear()
        with patch.object(Path, 'read_text', return_value=json.dumps(self.cache)) as read:
            self.assertTrue(self.render(self.cars))
            self.assertTrue(self.render(self.cars))
            self.assertEqual(read.call_count, 1)
        reviews._read_cache.cache_clear()

    def test_all_film_renders_preserve_everything_outside_box(self):
        shown = []
        for event in self.events:
            actual = cinema.render_film(event, self.cfg, TODAY)
            with patch.object(cinema, 'render_spectator_reviews', return_value=''):
                without_reviews = cinema.render_film(event, self.cfg, TODAY)
            self.assertEqual(BOX.sub('', actual), without_reviews)
            block = self.render(event)
            if block:
                shown.append(event['film_title'])
                self.assertLess(actual.index('Le petit mot de Papy'), actual.index('spectator-reviews-title'))
                self.assertLess(actual.index('spectator-reviews-title'), actual.index('<h2>Horaires'))
                self.assertNotIn('<script', block)
                self.assertNotIn('<iframe', block)
                self.assertIn('index,follow', actual)
                self.assertNotIn('noindex', actual)
        self.assertEqual(set(shown), {'Fausse Note', 'Cars', 'Mary et la fleur de la sorcière'})


if __name__ == '__main__':
    unittest.main()
