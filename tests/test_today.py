import ast
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import build_today as today

ROOT = Path(__file__).resolve().parents[1]

class TodayTests(unittest.TestCase):
    def test_descriptions_prefer_published_intro_and_keep_film_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "evenements/expo-2026-10-10/index.html"
            source.parent.mkdir(parents=True)
            source.write_text('<div class="lead">Notre <strong>description</strong> &amp; accueil.</div><p>Autre texte</p>', encoding="utf-8")
            events = [{"title": "Expo", "start_date": "2026-10-10", "url": "source", "summary": "Résumé brut parasite"},
                      {"title": "Film", "kind": "cinema", "start_date": "2026-10-10", "film": {"description": "Le petit mot déjà publié."}}]
            (root / "_event_seo_cache.json").write_text(json.dumps({"source": {"editorial": {"intro": "Ancienne introduction"}}}), encoding="utf-8")
            descriptions = today.published_descriptions(root, events)
            self.assertEqual(descriptions[today.event_path(events[0])], "Notre description & accueil.")
            self.assertEqual(descriptions[today.event_path(events[1])], "Le petit mot déjà publié.")
            source.unlink()
            self.assertEqual(today.published_descriptions(root, events)[today.event_path(events[0])], "Ancienne introduction")

    def test_market_all_weekdays(self):
        self.assertIn("aujourd’hui", today.market_text("2026-10-08"))
        for day in ("2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"):
            self.assertIn("jeudi 15 octobre 2026", today.market_text(day))
        self.assertIn("jeudi 8 octobre 2026", today.market_text("2026-10-07"))

    def test_exact_sessions_and_event_intervals(self):
        events=[{"title":"Expo","start_date":"2026-10-01","end_date":"2026-10-10"},
                {"title":"Passé","start_date":"2026-10-07"},
                {"title":"Film","kind":"cinema","start_date":"2026-10-01","end_date":"2026-10-10"}]
        self.assertEqual([e["title"] for e in today.today_events(events,"2026-10-08")],["Expo"])
        programme={"films":[{"title":"Film","sessions":[{"date":"2026-10-07","time":"20:00"},{"date":"2026-10-09","time":"18:00"}]}]}
        self.assertEqual(today.today_sessions(programme,"2026-10-08"),[])

    def test_weather_zero_null_stale_and_12h_clock(self):
        data={"weather":[{"date":"2026-10-08","mintempC":"0","maxtempC":"8","hourly":[{"precipMM":"0","windspeedKmph":"0"}]}],
              "current_condition":[{"localObsDateTime":"2026-10-08 03:15 PM","temp_C":"0","windspeedKmph":"0"}]}
        now=datetime(2026,10,8,16,tzinfo=ZoneInfo("Europe/Paris"))
        w=today.normalize_weather(data,"2026-10-08",now)
        self.assertEqual((w["temperature"],w["rain"],w["wind"]),(0,0,0))
        self.assertEqual(w["observation"],"15 h 15")
        self.assertIn("0 °C",today.weather_html(w,"2026-10-08",now))
        self.assertNotIn("weather-grid",today.weather_html(w,"2026-10-09",now))
        data["weather"][0]["hourly"][0]["precipMM"]=None
        self.assertIsNone(today.normalize_weather(data,"2026-10-08",now)["rain"])

    def test_generation_is_idempotent_and_does_not_touch_events_or_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for file in ("agenda.json","cinema-programme.json","index.html","sitemap.xml"):
                shutil.copy(ROOT/file, root/file)
            shutil.copytree(ROOT/"templates",root/"templates")
            now=datetime(2026,10,8,15,tzinfo=ZoneInfo("Europe/Paris"))
            original_agenda=(root/"agenda.json").read_bytes()
            original_programme=(root/"cinema-programme.json").read_bytes()
            with patch("build_today.urlopen",side_effect=AssertionError("No network in offline build")):
                today.build(root,now)
                home=(root/"index.html").read_bytes()
                page=(root/"aujourdhui/index.html").read_bytes()
                today.build(root,now)
            self.assertEqual(home,(root/"index.html").read_bytes())
            self.assertEqual(page,(root/"aujourdhui/index.html").read_bytes())
            self.assertEqual(original_agenda,(root/"agenda.json").read_bytes())
            self.assertEqual(original_programme,(root/"cinema-programme.json").read_bytes())
            self.assertEqual(home.count(b'id="nyons-today-link"'),1)
            self.assertNotIn("@@",page.decode())
            self.assertIn("jeudi 8 octobre 2026",page.decode())
            selected = today.today_events(json.loads(original_agenda)["events"], "2026-10-08")
            if selected:
                for event in selected:
                    self.assertIn(today.esc(event["title"]), page.decode())
            else:
                self.assertIn("Aucun événement annoncé", page.decode())
            self.assertFalse((root/"evenements").exists())
            self.assertFalse(list(root.glob("_*cache*")))

    def test_missing_weather_does_not_block_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for file in ("agenda.json","cinema-programme.json","index.html","sitemap.xml"):
                shutil.copy(ROOT/file,root/file)
            shutil.copytree(ROOT/"templates",root/"templates")
            with patch("build_today.urlopen",side_effect=OSError("offline")):
                today.build(root,datetime(2026,10,8,15,tzinfo=ZoneInfo("Europe/Paris")),weather=True)
            self.assertTrue((root/"aujourdhui/index.html").exists())

    def test_existing_generation_scripts_still_parse(self):
        for name in ("update_agenda.py","cinema_agenda.py","rollover_pages.py","build_today.py"):
            ast.parse((ROOT/name).read_text(encoding="utf-8"),filename=name)

if __name__=="__main__":
    unittest.main()

