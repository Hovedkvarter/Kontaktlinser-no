"""Protect verified pack identity and prevent duplicate/incorrect retailer offers."""
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'site_generator'))
import render_templates as render


class ContactLensReviewTests(unittest.TestCase):
    def setUp(self):
        self.match = json.loads((ROOT / 'product_matching.json').read_text())
        self.products = {p['id']: p for p in json.loads((ROOT / 'products_meta.json').read_text())['products']}
        self.catalog = {p['id']: p for p in json.loads((ROOT / 'site_generator/catalog_live.json').read_text())['products']}

    def test_everclear_daily_and_monthly_packs_are_not_interchanged(self):
        expected = {'10914': ('everclear-prime-30pk', 30, 'Dagslinse'),
                    '10915': ('everclear-prime-astigmatism-30pk', 30, 'Dagslinse'),
                    '10917': ('everclear-ultimate1-astigmatism-30pk', 30, 'Dagslinse'),
                    '10919': ('everclear-ultimate30-astigmatism-3pk', 3, 'Månedslinse')}
        for sku, (pid, pack, wear) in expected.items():
            for network in ['tradedoubler_lenson', 'tradedoubler_lensway']:
                self.assertEqual(self.match[network][sku], pid)
            specs = dict(self.products[pid]['specs'])
            self.assertEqual(specs['Pakningsstørrelse'], f'{pack} linser')
            self.assertEqual(specs['Brukstid'], wear)
            self.assertEqual({o['retailer'] for o in self.catalog[pid]['offers']}, {'Lenson', 'Lensway'})
            self.assertEqual(len(self.catalog[pid]['offers']), 2)

    def test_shopping4net_pack_sizes_are_exact(self):
        expected = {'LM': 'acuvue-moist-astigmatism-30pk',
                    'LU': 'acuvue-oasys-1day-astigmatism-30pk',
                    'LBXR': 'biofinity-xr-3pk', 'LP2P': 'purevision2-presbyopia-6pk'}
        for sku, pid in expected.items():
            self.assertEqual(self.match['tradedoubler'][sku], pid)
            self.assertEqual(sum(o['retailer'] == 'Shopping4net' for o in self.catalog[pid]['offers']), 1)

    def test_mislabelled_myday_never_maps_to_proclear(self):
        self.assertEqual(self.match['adtraction']['MyDay 1 day Sphere 30 stk'], 'myday-30pk')
        self.assertEqual(self.match['adtraction']['Proclear 1 day 30 stk'], 'proclear-1day-30pk')
        self.assertIn('Extra Optical', render.DIRECT_LINK_RETAILERS)
        raw = self.catalog['myday-30pk']['offers']
        offers = render.reconcile_product(raw, datetime.fromisoformat(max(o['checked_at'] for o in raw)))
        offer = next(o for o in offers if o['retailer'] == 'Extra Optical')
        self.assertTrue(offer['url'].startswith('https://extraoptical.no/myday-1-day-sphere-30-stk?'))
        self.assertEqual(offer['source'], 'direct_link')

    def test_ambiguous_and_unavailable_rows_do_not_create_duplicates(self):
        for sku in ['1-DAY ACUVUE 30 stk', '1-DAY ACUVUE 90 stk']:
            self.assertNotIn(sku, self.match['adtraction'])
        for sku in ['40000719', '40000720']:
            self.assertNotIn(sku, self.match['adtraction_interoptik'])
        for sku in ['LAOA', 'CL', 'LB1']:
            self.assertNotIn(sku, self.match['tradedoubler'])

    def test_prime_family_does_not_mix_ultimate_replacement_schedules(self):
        families = json.loads((ROOT / 'product_families.json').read_text())['families']
        prime = next(f for f in families if f['slug'] == 'everclear-prime')
        self.assertEqual(set(prime['member_ids']), {'everclear-prime-30pk', 'everclear-prime-astigmatism-30pk'})


if __name__ == '__main__':
    unittest.main()
