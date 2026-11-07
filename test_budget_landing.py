"""Behavioural regressions for the shopping landing page, without network."""
import copy
import json
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).parent / 'site_generator'))
import budget_landing as landing
import render_templates as t

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)


def offer(price, retailer='Store', **changes):
    return dict(price_nok=price, shipping_nok=0, retailer=retailer,
                url='https://example.org/lens', checked_at=NOW.isoformat(),
                in_stock=True, source='affiliate_feed', **changes)


def product(id, offers, category='dagslinser'):
    return dict(id=id, name=id, slug=id, brand_slug='acuvue', brand_label='Acuvue',
                category_slug=category, manual_image='/static/products/acuvue-oasys-6pk.jpg', offers=offers)


def catalog(products):
    return {'categories': {k: {'label': k} for k in landing.CATEGORIES}, 'products': products}


class LandingTests(unittest.TestCase):
    def test_fresh_stock_positive_prices_and_unique_stores(self):
        bad = [offer(1), offer(2), offer(-1), offer(float('nan')), offer(0)]
        bad[0]['in_stock'] = False
        bad[1]['checked_at'] = (NOW-timedelta(days=20)).isoformat()
        p = product('test-30pk', bad+[offer(100), offer(110), offer(130, 'Second')])
        rows = landing.select_products(catalog([p]), NOW)
        self.assertEqual(rows[0]['lowest']['price_nok'], 100)
        soup = BeautifulSoup(landing.render_budget_landing(catalog([p]), NOW), 'html.parser')
        self.assertIn('hos 2 butikker', soup.select_one('.product-tile-store-line').text)
        self.assertEqual(soup.select_one('.product-tile-price-number').text, '100')

    def test_neutral_ranking_keeps_lensit_and_legacy_default_unchanged(self):
        offers = [offer(80, 'Lensit'), offer(100, 'Partner')]
        original = copy.deepcopy(offers)
        row = landing.select_products(catalog([product('test-30pk', offers)]), NOW)[0]
        self.assertEqual(row['lowest']['retailer'], 'Lensit')
        self.assertEqual(len(row['offers']), 2)
        self.assertEqual([o['retailer'] for o in t.reconcile_product(offers, NOW)], ['Partner'])
        self.assertEqual(offers, original)

    def test_category_balance_models_and_trial_exclusion(self):
        products = []
        for cat in landing.CATEGORIES:
            products.extend(product(f'{cat}-{i}-30pk', [offer(i+100)], cat) for i in range(5))
            products.append(product(f'{cat}-0-90pk', [offer(200)], cat))
            products.append(product(f'{cat}-trial-1pk', [offer(1)], cat))
        result = landing.select_products(catalog(products), NOW)
        self.assertEqual(len(result), 12)
        for cat in landing.CATEGORIES:
            self.assertEqual(sum(r['product']['category_slug'] == cat for r in result), 3)
        self.assertEqual([r['lowest']['price_nok'] for r in result], sorted(r['lowest']['price_nok'] for r in result))
        reverse = landing.select_products(catalog(list(reversed(products))), NOW)
        self.assertEqual([r['product']['id'] for r in result], [r['product']['id'] for r in reverse])

    def test_empty_state_has_no_fake_prices_or_product_schema(self):
        c = catalog([product('test-30pk', [offer(1)])])
        html = landing.render_budget_landing(c, NOW+timedelta(days=20))
        soup = BeautifulSoup(html, 'html.parser')
        self.assertFalse(soup.select('.product-tile'))
        self.assertIn('Ingen ferske priser', html)
        graph = next(json.loads(node.string)['@graph'] for node in soup.select('[type="application/ld+json"]') if '@graph' in json.loads(node.string))
        self.assertEqual(graph[0]['mainEntity']['numberOfItems'], 0)
        self.assertNotIn('AggregateOffer', html)
        self.assertEqual(len(soup.select('h1')), 1)
        self.assertEqual(soup.select_one('[rel="canonical"]')['href'], t.BASE_URL+landing.PATH)
        self.assertIn('search-row', html)
        self.assertNotIn('data-guide=', html)
        self.assertIn(t.CONSENT_SCRIPT, html)

    def test_missing_image_and_unknown_pack_are_not_selected(self):
        p = product('test-30pk', [offer(100)])
        p.pop('manual_image')
        self.assertEqual(landing.select_products(catalog([p, product('unknown', [offer(100)])]), NOW), [])


if __name__ == '__main__':
    unittest.main()
