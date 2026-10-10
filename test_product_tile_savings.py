"""Regression checks for comparison savings on the shared product tile."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'site_generator'))
from render_templates import _render_product_tile


def offer(store, price, **extra):
    return dict(retailer=store, price_nok=price, total=price, in_stock=True, is_stale=False, **extra)


def tile(offers):
    return _render_product_tile(href='/product/', name='Example 30-pack', image_url=None,
        fallback_initials='EX', category_label='Dagslinser', secondary_line_html='',
        lowest=None, other_count=99, comparison_offers=offers)


class ProductTileSavingsTests(unittest.TestCase):
    def test_filters_unavailable_and_stale_and_counts_unique_stores(self):
        stale=offer('Old', 1000); stale['is_stale']=True
        unavailable=offer('Unavailable', 5000); unavailable['in_stock']=False
        html=tile([offer('A', 100), offer('A', 110), offer('B', 200), stale, unavailable])
        self.assertIn('Spar 50 %', html)
        self.assertIn('hos 2 butikker', html)
        self.assertIn('samme pakning, uten frakt', html)
        self.assertNotIn('Lavest hos', html)
        self.assertNotIn('priser →', html)

    def test_one_store_equal_prices_or_tiny_difference_have_no_badge(self):
        for offers in [[offer('A',100)], [offer('A',100),offer('B',100)],
                       [offer('A',100),offer('B',100.5)]]:
            self.assertNotIn('class="product-tile-savings"', tile(offers))

    def test_invalid_or_stale_only_means_no_price(self):
        stale=offer('Old', 100); stale['is_stale']=True
        html=tile([stale,offer('Zero',0),offer('Invalid',float('nan'))])
        self.assertIn('Ingen tilbud tilgjengelig', html)
        self.assertNotIn('class="product-tile-savings"', html)

    def test_percentage_never_rounds_up(self):
        self.assertIn('Spar 33 %', tile([offer('A',100),offer('B',150)]))


if __name__ == '__main__':
    unittest.main()
