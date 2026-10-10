import unittest
from seo_sitemap import build
PAGE='<html><head><meta name="robots" content="index,follow"></head><body><p>Archive locale</p></body></html>'
class Dates(unittest.TestCase):
    def test_unknown_history_has_no_invented_date(self):
        xml,state=build({'index.html':PAGE},{},'2026-10-10')
        self.assertNotIn('<lastmod>',xml)
        self.assertIsNone(state['pages']['index.html']['lastmod'])
    def test_unchanged_page_keeps_date(self):
        _,state=build({'index.html':PAGE},{},'2026-10-10');state['pages']['index.html']['lastmod']='2026-09-20'
        xml,new=build({'index.html':PAGE},state,'2026-10-11')
        self.assertIn('<lastmod>2026-09-20</lastmod>',xml)
    def test_changed_content_gets_change_date(self):
        _,state=build({'index.html':PAGE},{},'2026-10-10')
        xml,new=build({'index.html':PAGE.replace('Archive locale','Archive enrichie')},state,'2026-10-11')
        self.assertIn('<lastmod>2026-10-11</lastmod>',xml)
        xml,_=build({'index.html':PAGE.replace('Archive locale','Archive enrichie')},new,'2026-10-12')
        self.assertIn('<lastmod>2026-10-11</lastmod>',xml)
    def test_noindex_and_empty_weeks_excluded_but_archive_kept(self):
        sources={'index.html':PAGE,'evenements/archive/index.html':PAGE,'evenements/hidden/index.html':PAGE.replace('index,follow','noindex,follow'),'semaines/semaine-vide/index.html':PAGE}
        xml,_=build(sources,{},'2026-10-10')
        self.assertIn('/evenements/archive/',xml)
        self.assertNotIn('/evenements/hidden/',xml);self.assertNotIn('/semaines/semaine-vide/',xml)
    def test_formatting_only_preserves_date(self):
        _,state=build({'index.html':PAGE},{},'2026-10-10');state['pages']['index.html']['lastmod']='2026-09-20'
        xml,_=build({'index.html':PAGE.replace('><','>\n  <')},state,'2026-10-11')
        self.assertIn('<lastmod>2026-09-20</lastmod>',xml)
if __name__=='__main__':unittest.main()
