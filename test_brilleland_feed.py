"""Real Adtraction feed regression checks: variant safety and outbound tracking."""
import json
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent / "site_generator"))

from ingest_feed import load_feed, map_brilleland_row
from scraper import should_scrape
from site_generator.render_templates import reconcile_product, render_offer_card

ROOT = Path(__file__).parent

class BrillelandFeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / 'sources_config.json').read_text())
        cls.match = json.loads((ROOT / 'product_matching.json').read_text())['adtraction_brilleland']
        cls.offers = load_feed(str(ROOT / 'tests/fixtures/brilleland-adtraction.csv'), 'adtraction_brilleland', cls.match, cls.config['brilleland'])
        cls.by_id = {o.product_id: o for o in cls.offers}

    def test_existing_coverage_and_no_duplicate_offers(self):
        meta = json.loads((ROOT / 'products_meta.json').read_text())
        expected = {p['id'] for p in meta['products'] if any(t['retailer'] == 'brilleland' for t in p.get('scrape_targets', []))}
        self.assertTrue(expected <= set(self.by_id))
        self.assertEqual(len(self.offers), len(self.by_id))
        self.assertEqual(len(self.offers), 77)
        self.assertEqual(len(expected), 31)

    def test_destination_correction_preserves_tracking_and_future_feed_updates(self):
        import csv
        from urllib.parse import quote
        with (ROOT / 'tests/fixtures/brilleland-adtraction.csv').open() as f:
            row = next(r for r in csv.DictReader(f) if r['id'] == '40000310')
        correction = self.config['brilleland']['destination_corrections']['40000310']
        original = row['link']
        offer = self.by_id['dailies-aquacomfort-plus-multifocal-30pk']
        self.assertEqual(offer.url, original.replace(correction['old_url'], correction['new_url']))
        self.assertEqual(offer.price_nok, 357)
        for target in (correction['new_url'], 'https://www.brilleland.no/future-product/'):
            row['link'] = original.replace(correction['old_url'], target)
            self.assertEqual(map_brilleland_row(row, self.match, self.config['brilleland'])[0].url, row['link'])
        row['link'] = original.replace(correction['old_url'], quote(correction['old_url'], safe=''))
        corrected = map_brilleland_row(row, self.match, self.config['brilleland'])[0].url
        self.assertEqual(parse_qs(urlparse(corrected).query)['url'], [correction['new_url']])

    def test_iwear_miru_variants_and_pack_sizes(self):
        expected = {
            '40000699': ('miru-1month-6pk', 395),
            '40000700': ('miru-1month-toric-6pk', 510),
            '40000733': ('miru-1month-multifocal-6pk', 610),
            '40000690': ('miru-1day-upside-30pk', 299),
            '40000692': ('miru-1day-upside-astigmatism-30pk', 395),
            '40000694': ('miru-1day-upside-multifocal-30pk', 460),
            '40000672': ('miru-1day-flatpack-30pk', 252),
            '40000674': ('miru-1day-flatpack-astigmatism-30pk', 297),
            '40000676': ('miru-1day-flatpack-multifocal-30pk', 330),
        }
        for sku, (pid, price) in expected.items():
            self.assertEqual(self.match[sku], pid)
            self.assertEqual(self.by_id[pid].price_nok, price)
            self.assertEqual(parse_qs(urlparse(self.by_id[pid].url).query)['cupa_sku'], [sku])
        meta = {p['id']: p for p in json.loads((ROOT / 'products_meta.json').read_text())['products']}
        self.assertEqual(dict(meta['miru-1day-flatpack-astigmatism-30pk']['specs'])['Diameter'], '14,5')
        self.assertEqual(dict(meta['miru-1day-flatpack-multifocal-30pk']['specs'])['Basekurve'], '8,4')
        self.assertEqual(dict(meta['miru-1month-6pk']['specs'])['Brukstid'], 'Månedslinse')

    def test_iwear_aliases_and_families_cover_each_variant(self):
        aliases = json.loads((ROOT / 'private_labels.json').read_text())['labels']
        by_slug = {a['slug']: a['real_product_id'] for a in aliases}
        self.assertEqual(len(by_slug), len(aliases))
        self.assertEqual(by_slug['iwear-oxygen-xr'], 'biofinity-xr-6pk')
        families = {f['slug']: set(f['member_ids']) for f in json.loads((ROOT / 'product_families.json').read_text())['families']}
        for alias, family in [('connect', 'miru-1month'), ('flex', 'miru-1day-upside'), ('slim', 'miru-1day-flatpack')]:
            targets = {by_slug['iwear-' + alias + suffix] for suffix in ['', '-astigmatism', '-multifocal']}
            self.assertEqual(targets, families[family])
        self.assertTrue(families['miru-1day-upside'].isdisjoint(families['miru-1day-flatpack']))

    def test_three_packs_never_become_six_packs(self):
        self.assertEqual(self.match['40000281'], 'biofinity-multifocal-3pk')
        self.assertEqual(self.match['40000179'], 'biofinity-toric-3pk')
        self.assertEqual(self.by_id['biofinity-multifocal-3pk'].price_nok, 431)
        self.assertEqual(self.by_id['biofinity-toric-3pk'].price_nok, 333)
        self.assertEqual(self.by_id['biofinity-multifocal-6pk'].price_nok, 860)
        self.assertEqual(self.by_id['biofinity-toric-6pk'].price_nok, 666)

    def test_tracking_and_merchant_are_preserved_in_rendered_card(self):
        for offer in self.offers:
            self.assertEqual(offer.network, 'adtraction')
            self.assertEqual(offer.source, 'affiliate_feed')
            self.assertEqual(offer.retailer, 'Brilleland')
            parsed = urlparse(offer.url)
            self.assertEqual(parsed.hostname, 'to.brilleland.no')
            query = parse_qs(parsed.query)
            self.assertEqual(query['as'], ['2102229792'])
            self.assertEqual(query['fid'], ['657'])
            self.assertEqual(urlparse(query['url'][0]).hostname, 'www.brilleland.no')
            rendered = reconcile_product([asdict(offer)], datetime.now(timezone.utc))[0]
            self.assertEqual(rendered['url'], offer.url)
            html = render_offer_card(rendered, offer.retailer, offer.product_id, offer.product_id, {})
            self.assertIn('sponsored', html)
            self.assertIn('to.brilleland.no', html)

    def test_legacy_scraper_disabled_and_shipping_policy_preserved(self):
        self.assertFalse(should_scrape(self.config, 'brilleland', 'acuvue'))
        self.assertEqual(self.by_id['acuvue-moist-30pk'].shipping_nok, 59)
        self.assertEqual(self.by_id['dailies-total1-multifocal-90pk'].shipping_nok, 0)

    def test_unrelated_sunglasses_are_excluded(self):
        self.assertNotIn('90121391', self.match)
        self.assertTrue(all(o.in_stock for o in self.offers))

    def test_complete_feed_accounting(self):
        audit = json.loads((ROOT / 'docs/brilleland-feed-audit.json').read_text())['rows']
        self.assertEqual(len(audit), 77)
        self.assertIn('40000310', self.match)
        self.assertEqual(next(r for r in audit if r['sku'] == '40000310')['status'], 'mapped')
        self.assertEqual(len({r['sku'] for r in audit}), 77)
        self.assertEqual({r['sku'] for r in audit if r['status'] == 'mapped'}, set(self.match))
        for row in audit:
            if row['status'] != 'mapped':
                self.assertNotIn(row['sku'], self.match)
                self.assertTrue(row['reason'])

    def test_distinct_lens_designs_and_single_total30_offer(self):
        self.assertEqual(self.match['40000752'], 'clariti-1day-multifocal-3add-30pk')
        self.assertEqual(self.match['40000381'], 'clariti-1day-multifocal-30pk')
        self.assertEqual(self.match['40000561'], 'misight-1day-30pk')
        self.assertNotIn('myday-misight-1day-30pk', self.by_id)
        self.assertEqual(sum(o.product_id == 'total30-multifocal-6pk' for o in self.offers), 1)

    def test_new_products_and_aliases_have_valid_targets(self):
        meta = json.loads((ROOT / 'products_meta.json').read_text())['products']
        ids = {p['id'] for p in meta}
        self.assertEqual(len(ids), len(meta))
        self.assertTrue(set(self.by_id) <= ids)
        aliases = json.loads((ROOT / 'private_labels.json').read_text())['labels']
        self.assertTrue(all(a['real_product_id'] in ids for a in aliases))

if __name__ == '__main__':
    unittest.main()
