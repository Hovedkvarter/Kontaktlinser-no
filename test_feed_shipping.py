"""Department shipping must follow the matched feed category."""
import json
import unittest
from pathlib import Path

from ingest_feed import map_tradedoubler_row
from offer import compute_shipping_nok


class FeedShippingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).parent / 'sources_config.json').read_text())

    def offer(self, source, category, price=400):
        row = {'categories': [{'name': category}], 'offers': [{
            'sourceProductId': 'fixture', 'availability': 'in_stock',
            'productUrl': 'https://example.invalid/product',
            'priceHistory': [{'price': {'value': price}}],
        }]}
        return map_tradedoubler_row(row, {'fixture': 'example-product'}, self.config[source])[0]

    def test_apotek_and_lenses_have_different_thresholds(self):
        pharmacy = self.offer('shopping4net', 'Apotek > Øyne & Ører > Øyeplager')
        lenses = self.offer('shopping4net', 'Kontaktlinser > Dagslinser')
        self.assertEqual(pharmacy.shipping_nok, 0)
        self.assertEqual(lenses.shipping_nok, 39)
        self.assertEqual(pharmacy.shipping_policy['free_over'], 350)
        self.assertEqual(lenses.shipping_policy['free_over'], 700)
        self.assertEqual(compute_shipping_nok(349, pharmacy.shipping_policy), 39)
        self.assertEqual(compute_shipping_nok(350, pharmacy.shipping_policy), 0)
        self.assertEqual(compute_shipping_nok(700, lenses.shipping_policy), 0)

    def test_other_retailer_keeps_its_default(self):
        offer = self.offer('lensway', 'Tilbehør')
        self.assertEqual(offer.shipping_policy, self.config['lensway']['shipping'])
        self.assertEqual(offer.shipping_nok, 50)


if __name__ == '__main__':
    unittest.main()
