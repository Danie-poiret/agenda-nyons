"""Regression tests for the agenda without an API key or SDK."""
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import fix_saviezvous as facts
ROOT = Path(__file__).resolve().parents[1]
BLOCK = '<section class="section anecdote"><h2>💡 Le saviez-vous ?</h2><p>Ancien bloc</p></section>'
FACT = 'Le piano produit ses sons grâce à des marteaux qui frappent les cordes, contrairement au clavecin dont les cordes sont pincées.'
OTHER = 'Dans un concert, la musique peut être jouée par plusieurs instruments réunis au sein d’un ensemble dont chaque musicien interprète une partie.'

def entry(slug, title='Concert de piano'):
    return {'slug': slug, 'event': {'title': title, 'summary': title, 'start_date': '2026-11-01'}, 'editorial': {'intro': 'Texte déjà publié, à conserver.'}, 'practical': {'place': 'Lieu vérifié'}}

class NoApiFactsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = self.root / '_event_seo_cache.json'
        self.cache = self.root / '_saviezvous_cache.json'
        self.pages = self.root / 'evenements'
        p = patch.multiple(facts, EVENT_CACHE=self.events, FACT_CACHE=self.cache, EVENTS_DIR=self.pages, FACT_BANK=self.root / 'bank.json')
        p.start()
        self.addCleanup(p.stop)

    def prepare(self, entries, records):
        self.events.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
        self.cache.write_text(json.dumps({'version': 1, 'entries': records}, ensure_ascii=False), encoding='utf-8')
        for item in entries.values():
            page = self.pages / item['slug'] / 'index.html'
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text('<main><h1>Titre existant</h1><p>Date et lieu confirmés</p>' + BLOCK + '<a href="/">Agenda</a></main>', encoding='utf-8')

    def run_local(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'obsolete-key-not-to-be-used'}), patch('socket.create_connection', side_effect=AssertionError('Unexpected network call')), contextlib.redirect_stdout(io.StringIO()):
            facts.main()

    def text(self, slug):
        return (self.pages / slug / 'index.html').read_text(encoding='utf-8')

    def test_missing_fact_does_not_block_or_publish_an_empty_block(self):
        original = entry('nouveau')
        self.prepare({'url': original}, {})
        self.run_local()
        self.assertNotIn('Le saviez-vous', self.text('nouveau'))
        self.assertIn('<p>Date et lieu confirmés</p>', self.text('nouveau'))
        self.assertEqual(json.loads(self.events.read_text(encoding='utf-8'))['url'], original)

    def test_existing_record_editorial_and_second_run_are_stable(self):
        record = {'text': FACT, 'source_label': 'Repère déjà publié', 'model': 'historical', 'generated_at': '2026-10-01'}
        self.prepare({'url': entry('concert')}, {'concert': record})
        self.run_local()
        self.assertIn(FACT, self.text('concert'))
        self.assertEqual(json.loads(self.cache.read_text(encoding='utf-8'))['entries']['concert'], record)
        paths = [self.cache, self.events, self.pages / 'concert/index.html']
        first = [p.read_bytes() for p in paths]
        self.run_local()
        self.assertEqual(first, [p.read_bytes() for p in paths])

    def test_unrelated_fact_is_not_forced_into_an_event(self):
        record = {'text': FACT}
        self.prepare({'url': entry('loto', 'Loto associatif')}, {'loto': record})
        self.run_local()
        self.assertNotIn('Le saviez-vous', self.text('loto'))
        self.assertEqual(json.loads(self.cache.read_text(encoding='utf-8'))['entries']['loto'], record)

    def test_duplicate_fact_is_not_published_twice(self):
        self.prepare({'a': entry('a'), 'b': entry('b')}, {'a': {'text': FACT}, 'b': {'text': FACT}})
        self.run_local()
        self.assertIn(FACT, self.text('a'))
        self.assertNotIn('Le saviez-vous', self.text('b'))

    def test_duplicate_manual_fact_uses_a_distinct_cached_fact(self):
        self.prepare({'a': entry('a'), 'b': entry('b')}, {'b': {'text': OTHER}})
        with patch.object(facts, 'manual_fact', return_value={'text': FACT, 'source_label': 'Repère manuel'}):
            self.run_local()
        self.assertIn(FACT, self.text('a'))
        self.assertIn(OTHER, self.text('b'))

    def test_manual_fact_available_without_api(self):
        self.prepare({'url': entry('brownies', 'Atelier brownies')}, {})
        self.run_local()
        self.assertIn('Palmer House', self.text('brownies'))

    def test_missing_event_page_still_fails_validation(self):
        self.prepare({'url': entry('absent')}, {})
        (self.pages / 'absent/index.html').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Fiche HTML absente'):
            self.run_local()

    def set_bank(self, bank):
        (self.root / 'bank.json').write_text(json.dumps({'facts': bank}), encoding='utf-8')

    def test_bank_fills_an_absent_section_with_a_clickable_source_and_is_stable(self):
        self.prepare({'url': entry('concert')}, {})
        self.run_local()
        self.set_bank([{'id': 'piano', 'match': ['piano'], 'text': FACT, 'source_label': 'Source piano', 'source_url': 'https://example.org/piano/'}])
        self.run_local()
        text = self.text('concert')
        self.assertIn(FACT, text)
        self.assertIn('href="https://example.org/piano/"', text)
        self.run_local()
        self.assertEqual(text, self.text('concert'))

    def test_bank_reserves_existing_facts_and_omits_exhausted_or_unrelated_topics(self):
        self.prepare({'a': entry('a'), 'b': entry('b'), 'c': entry('c'), 'd': entry('d', 'Exposition')}, {'b': {'text': FACT}})
        self.set_bank([{'match': ['piano'], 'text': FACT}, {'match': ['piano'], 'text': OTHER}])
        self.run_local()
        self.assertIn(FACT, self.text('b'))
        self.assertIn(OTHER, self.text('a'))
        self.assertNotIn('Le saviez-vous', self.text('c'))
        self.assertNotIn('Le saviez-vous', self.text('d'))

    def test_curated_bank_has_valid_distinct_sourced_facts(self):
        bank = json.loads((ROOT / 'saviezvous_facts.json').read_text(encoding='utf-8'))['facts']
        self.assertEqual(len(bank), len({facts.fact_key(f['text']) for f in bank}))
        for f in bank:
            self.assertTrue(facts.valid_fact(f['text']), f['id'])
            self.assertTrue(f['match'])
            self.assertTrue(f['source_url'].startswith('https://'))

    def test_old_cache_entries_are_not_deleted(self):
        record = {'text': FACT}
        self.prepare({'url': entry('nouveau')}, {'ancien': record})
        self.run_local()
        self.assertEqual(json.loads(self.cache.read_text(encoding='utf-8'))['entries']['ancien'], record)

class NoApiWorkflowTests(unittest.TestCase):

    def test_no_paid_secret_or_sdk_in_daily_workflow(self):
        self.assertNotIn('OPENAI_API_KEY', (ROOT / '.github/workflows/update-agenda.yml').read_text(encoding='utf-8'))
        self.assertNotIn('openai', (ROOT / 'requirements.txt').read_text(encoding='utf-8').lower())

    def test_core_generators_work_without_sdk_even_with_an_old_key(self):
        spec = importlib.util.spec_from_file_location('agenda_without_sdk', ROOT / 'update_agenda.py')
        m = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'openai': None}), patch.dict(os.environ, {'OPENAI_API_KEY': 'obsolete-key-not-to-be-used'}):
            spec.loader.exec_module(m)
            e = {'title': 'Concert', 'start_date': '2026-11-01', 'end_date': '2026-11-01', 'summary': 'Présentation officielle', 'url': 'https://www.nyons.com/evenement-test/'}
            with contextlib.redirect_stdout(io.StringIO()):
                editorial = m.generate_event_editorial(e, 'Texte officiel', {})
                week = m.generate_editorial(date(2026, 11, 2), [])
        self.assertTrue(editorial['_fallback'])
        self.assertIn('Présentation officielle', editorial['intro'])
        self.assertTrue(week['intro'])
if __name__ == '__main__':
    unittest.main()
