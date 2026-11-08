"""Black Friday must not turn ordinary prices into sale claims."""
import json
import unittest
from datetime import timedelta
from bs4 import BeautifulSoup
from test_budget_landing import NOW, offer, product, catalog
from site_generator import black_friday as page

class BlackFridayTests(unittest.TestCase):
    def test_store_price_difference_is_not_a_campaign(self):
        c = catalog([product('test-30pk', [offer(100,'A'), offer(200,'B'), offer(210,'B')])])
        html = page.render_black_friday(c, NOW)
        soup = BeautifulSoup(html, 'html.parser')
        self.assertFalse(soup.select('.product-tile-savings, .product-tile-high-price'))
        self.assertEqual(soup.select_one('.product-tile-price-number').text, '100')
        self.assertIn('hos 2 butikker', soup.select_one('.product-tile-store-line').text)
        self.assertIn('ingen bekreftede Black Friday-kampanjer', html)
        self.assertNotIn('priceValidUntil', html)

    def test_expired_prices_disappear_from_cards_and_schema(self):
        html = page.render_black_friday(catalog([product('test-30pk', [offer(100)])]), NOW+timedelta(days=2))
        soup = BeautifulSoup(html, 'html.parser')
        self.assertFalse(soup.select('.product-tile'))
        graph = next(data['@graph'] for node in soup.select('script[type="application/ld+json"]') if '@graph' in (data := json.loads(node.string)))
        self.assertEqual(graph[0]['mainEntity']['numberOfItems'],0)
        self.assertIn('Ingen ferske priser',html)

    def test_page_identity_and_original_product_destinations(self):
        soup = BeautifulSoup(page.render_black_friday(catalog([product('test-30pk',[offer(100)])]), NOW),'html.parser')
        self.assertEqual(len(soup.select('h1')),1)
        self.assertEqual(soup.select_one('link[rel="canonical"]')['href'],'https://kontaktlinser.no/black-friday-kontaktlinser/')
        self.assertEqual(soup.select_one('.product-tile-cta')['href'],'/kontaktlinser/acuvue/test-30pk/')
        self.assertTrue(soup.select_one('.budget-filters').has_attr('hidden'))
        self.assertFalse(soup.select('meta[name="robots"][content*="noindex"]'))

if __name__ == '__main__': unittest.main()
