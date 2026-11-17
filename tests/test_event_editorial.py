"""Regression coverage for detailed, clean, unpaid event pages."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import update_agenda as agenda
from event_editorial import clean_source_text, event_description


def event(title="Atelier culinaire", url="https://www.nyons.com/agenda/test/"):
    return dict(title=title, url=url, start_date="2026-12-12", end_date="2026-12-12",
                summary="Un atelier annoncé.", categories=[])


class EventEditorialTests(unittest.TestCase):
    def test_categories_are_read_from_each_card_not_filters_or_neighbours(self):
        source = '''<nav>Administratif Sport / Loisirs Culture</nav>
        <article class="wpgb-card"><span class="wpgb-term-label">Vie associative</span><h2><a href="/agenda/vente/">Vente de clémentines</a></h2></article>
        <article class="wpgb-card"><span class="wpgb-term-label">Sport / Loisirs</span><h2><a href="/agenda/sport/">Tournoi</a></h2></article>'''
        labels = agenda.page_event_categories(agenda.BeautifulSoup(source, 'html.parser'))
        self.assertEqual(labels['https://www.nyons.com/agenda/vente/'], ['Vie associative'])
        self.assertEqual(labels['https://www.nyons.com/agenda/sport/'], ['Sport / Loisirs'])
        self.assertEqual(agenda.event_section_titles({'title':'Vente de clémentines', 'categories':labels['https://www.nyons.com/agenda/vente/']})[0], '📍 Ce qui est prévu')

    def test_clementine_sale_uses_its_actual_subject_and_variable_schedule(self):
        e = event("Vente de clémentines bio")
        e.update(start_date="2027-12-18", end_date="2027-12-18", summary="Clémentines de Nulès pour la fête de l’Olive piquée, par Amitié Nyons-Nulès.")
        p = dict(date_time="Samedi 18 décembre 2027 de 10h00 à 15h00", address="Place de la Libération Sud", phone="0663192728")
        text = "Retour Vente de clémentines bio en provenance de Nulès. Stand tenu par Amitié Nyons-Nulès pour la Fête de l’Olive piquée. " + p['date_time']
        copy = agenda.fallback_event_editorial(e, text, p)
        self.assertIn('Amitié Nyons-Nulès', copy['intro'])
        self.assertIn('région de Nulès', copy['why_it_matters'])
        self.assertIn('2027', copy['story'])
        self.assertNotIn('2026', copy['story'])
        self.assertNotIn('Pour préparer votre sortie', copy['why_it_matters'])
        self.assertIn('clémentines', copy['reader_question'])
        self.assertNotIn('gratuit', ' '.join(str(v) for v in copy.values()))

    def test_other_clementine_sale_does_not_invent_an_association_or_festival(self):
        e = event("Vente de clémentines bio")
        e['summary'] = 'Vente de fruits de la région de Nulès.'
        copy = agenda.fallback_event_editorial(e, 'Retour Vente de fruits de la région de Nulès.', {})
        self.assertNotIn('Amitié', copy['intro'])
        self.assertNotIn('Olive piquée', copy['intro'])

    def test_last_list_event_drops_footer_and_pagination(self):
        _, summary = agenda.extract_end_and_summary(
            "Recettes de fêtes ! 1 2 3 4 5 … 10 11 -> Abonnement aux informations de la ville de Nyons Recevez les dernières actualités", "2026-12-12")
        self.assertEqual(summary, "Recettes de fêtes !")
        self.assertEqual(clean_source_text(summary), summary)

    def test_short_detail_stops_before_footer_and_reads_abbreviated_address(self):
        source = """<h1>Atelier culinaire</h1><a>Retour</a><p>Réalisez vos blinis maison.</p>
        <p>Samedi 12 décembre 2026 de 14h00 à 16h30</p>
        <p>Maison des Huiles, 40 Pl. de la Libération</p><p>oliveetsens@gmail.com</p><p>0475269090</p>
        <h2>Abonnement aux informations de la ville de Nyons</h2><p>Mairie de Nyons 0475265000</p>"""
        data = agenda.extract_event_detail_data(source, event()["url"])
        self.assertNotIn("Abonnement", data["text"])
        self.assertEqual(data["practical"]["address"], "40 Pl. de la Libération")
        self.assertEqual(data["practical"]["location_name"], "Maison des Huiles")
        self.assertEqual(data["practical"]["phone"], "0475269090")

    def test_description_preserves_programme_prices_and_audience_without_contacts(self):
        practical = dict(date_time="Samedi 12 décembre 2026 de 14h00 à 16h30", address="40 Pl. de la Libération", phone="0475269090")
        detail = "Atelier culinaire Exporter l'événement Retour Description Blinis et pain d’épices. Public : Adultes Prix : 30€. " + practical["date_time"] + " 40 Pl. de la Libération 0475269090"
        text = event_description(event(), detail, practical)
        self.assertEqual(text, "Blinis et pain d’épices. Public : Adultes Prix : 30€.")
        with patch.object(agenda, "OpenAI", None):
            editorial = agenda.generate_event_editorial(event(), detail, practical)
        self.assertIn("30€", editorial["story"])
        self.assertIn("04 75 26 90 90", editorial["practical"])
        self.assertNotIn("Si le thème vous intéresse", editorial["why_it_matters"])
        self.assertIn("préparation", editorial["reader_question"])

    def test_daily_generation_preserves_written_copy_and_refreshes_all_local_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = event(), event("Conférence", "https://www.nyons.com/agenda/conference/")
            cache = {b["url"]: dict(event=b, editorial=dict(intro="Rédaction existante", story="Texte à garder", _fallback=False), prompt_version=agenda.EVENT_PROMPT_VERSION)}
            cache_file, details_file = root/'cache.json', root/'details.json'
            cache_file.write_text(json.dumps(cache), encoding='utf-8')
            details_file.write_text('{}', encoding='utf-8')
            with patch.multiple(agenda, EVENTS_DIR=root/'pages', EVENT_CACHE_FILE=cache_file, EVENT_DETAIL_CACHE_FILE=details_file, MAX_EVENT_AI_CALLS=0, OpenAI=None), patch.object(agenda, 'get_event_detail', return_value={'text': "Retour Programme complet avec recettes et astuces.", 'practical': {'date_time': '14 h à 16 h'}}), patch.object(agenda, 'generate_event_editorial', side_effect=AssertionError('No API call')), contextlib.redirect_stdout(io.StringIO()):
                agenda.generate_event_pages([a, b])
            updated = json.loads(cache_file.read_text(encoding='utf-8'))
            self.assertEqual(updated[b['url']]['editorial']['intro'], 'Rédaction existante')
            self.assertIn('recettes', updated[a['url']]['editorial']['story'])
            self.assertTrue(updated[a['url']]['editorial']['practical'])


if __name__ == '__main__':
    unittest.main()
