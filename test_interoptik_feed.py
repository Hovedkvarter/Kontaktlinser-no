"""Interoptik must use its own SKU namespace and feed stock/tracking."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from ingest_feed import load_feed
from scraper import should_scrape
from feed_discovery import active_sources

ROOT = Path(__file__).parent

class InteroptikFeedTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT/'sources_config.json').read_text())
        self.cfg = self.config['interoptik']
        self.matching = json.loads((ROOT/'product_matching.json').read_text())[self.cfg['network']]

    def test_feed_replaces_scraping_and_enters_discovery(self):
        self.assertFalse(should_scrape(self.config, 'interoptik', 'miru'))
        self.assertFalse(should_scrape(self.config, 'interoptik', 'acuvue'))
        self.assertIn('interoptik', dict(active_sources(self.config)))
        self.assertEqual(self.cfg['network'], 'adtraction_interoptik')

    def test_ingestion_preserves_tracking_price_stock_and_unknown_exclusion(self):
        link='https://to.interoptik.no/t/t?a=1717731578&as=2102229792&t=2&tk=1&cupa_sku=40000751&fid=1169&url=https://www.interoptik.no/kontaktlinser/miru/miru-1month-multifocal-6-pack/'
        rows=[dict(id='40000751', title='Miru 1month Multifocal 6-pack', price='790 NOK',sale_price='',availability='in_stock',link=link),
              dict(id='40000634', title='Precision1 30 pack',price='322 NOK',sale_price='299 NOK',availability='out_of_stock',link='https://example.invalid/precision1'),
              dict(id='unmapped-glasses',title='Glasses',price='900 NOK',sale_price='',availability='in_stock',link='https://example.invalid/glasses')]
        with tempfile.NamedTemporaryFile(mode='w',suffix='.csv',newline='') as f:
            w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows);f.flush()
            offers=load_feed(f.name,self.cfg['network'],self.matching,self.cfg)
        self.assertEqual(len(offers),2)
        self.assertEqual(offers[0].product_id,'miru-1month-multifocal-6pk')
        self.assertEqual(offers[0].url,link)
        self.assertEqual(offers[0].source,'affiliate_feed')
        self.assertTrue(offers[0].in_stock)
        self.assertEqual(offers[0].shipping_nok,0)
        self.assertEqual(offers[1].price_nok,299)
        self.assertFalse(offers[1].in_stock)

    def test_verified_pack_pairs_remain_separate(self):
        for sku30, sku90, family in [
            ('40000584', '40000585', 'dailies-all-day-comfort'),
            ('40000576', '40000577', 'biotrue-oneday'),
            ('40000572', '40000574', 'biotrue-oneday-presbyopia'),
        ]:
            self.assertEqual(self.matching[sku30], family + '-30pk')
            self.assertEqual(self.matching[sku90], family + '-90pk')
        self.assertEqual(self.matching['40000607'], 'eyexpert-natural-30pk')
        self.assertEqual(self.matching['90120619'], 'thealoz-duo-gel-30x04g')
        self.assertEqual(len(set(self.matching.values())),len(self.matching))

if __name__=='__main__':unittest.main()
