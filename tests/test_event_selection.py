import unittest
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from event_selection import select,sessions,week_key,upcoming

class EventSelectionTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,22,17,tzinfo=ZoneInfo('Europe/Paris'))
    def test_exhibition_is_kept_until_last_day(self):
        e={'title':'Expo','start_date':'2026-10-20','end_date':'2026-10-31'}
        self.assertTrue(upcoming(e,self.now))
        self.assertFalse(upcoming(e,datetime(2026,11,1,tzinfo=ZoneInfo('Europe/Paris'))))
    def test_past_cinema_session_does_not_set_next_date(self):
        e={'title':'Film','kind':'cinema','sessions':[{'date':'2026-10-22','time':'16:00'},{'date':'2026-11-09','time':'19:00'}]}
        self.assertEqual(sessions(e,self.now),[{'date':'2026-11-09','time':'19:00'}])
    def test_week_9_november_uses_its_own_session(self):
        film={'title':'Film','start_date':'2026-11-04','sessions':[{'date':'2026-11-04','time':'19:00'},{'date':'2026-11-10','time':'21:00'}]}
        armistice={'title':'Armistice','start_date':'2026-11-11'}
        later={'title':'Spectacle','start_date':'2026-11-13'}
        ordered=sorted([later,armistice,film],key=lambda e:week_key(e,date(2026,11,9)))
        self.assertEqual([e['title'] for e in ordered],['Film','Armistice','Spectacle'])
    def test_duplicates_and_unconfirmed_dates(self):
        e={'title':'Sortie','start_date':'2026-11-01','end_date':'2026-11-01','url':'https://example.org/event'}
        self.assertEqual(len(select([e,e],self.now)),1)
        self.assertEqual(select([{**e,'date_warning':'À confirmer'}],self.now),[])
    def test_known_end_time_hides_finished_workshop(self):
        e={'title':'Atelier','start_date':'2026-10-22','end_date':'2026-10-22','end_time':'12:00'}
        self.assertFalse(upcoming(e,self.now))
    def test_dst_is_resolved_in_paris(self):
        self.assertEqual(datetime(2026,10,24,20,tzinfo=ZoneInfo('Europe/Paris')).utcoffset(),timedelta(hours=2))
        self.assertEqual(datetime(2026,10,25,20,tzinfo=ZoneInfo('Europe/Paris')).utcoffset(),timedelta(hours=1))

if __name__=='__main__':unittest.main()
