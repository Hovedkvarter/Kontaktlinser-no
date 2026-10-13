"""Prevent a missing WebP source from hiding an available original image."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent / "site_generator"))
import render_templates as render
from site_generator import validate_build as validate


class ProductImageFilesTests(unittest.TestCase):
    def test_original_is_used_until_webp_exists(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(render, '_REPO_ROOT', Path(tmp)):
            folder = Path(tmp) / 'static/products'
            folder.mkdir(parents=True)
            (folder / 'example.jpg').write_bytes(b'original')
            jpg = '/static/products/example.jpg'
            html = render._img_tag(jpg, 'Example')
            self.assertIn('src="' + jpg + '"', html)
            self.assertNotIn('<source', html)
            (folder / 'example.webp').write_bytes(b'webp')
            self.assertIn('srcset="/static/products/example.webp"', render._img_tag(jpg, 'Example'))

    def test_homepage_uses_private_label_package_photo(self):
        import json
        root = Path(__file__).parent
        catalog = json.loads((root / 'site_generator/catalog_live.json').read_text())
        labels = json.loads((root / 'private_labels.json').read_text())['labels']
        html = render.render_home_page(catalog, private_labels=labels)
        import re
        card = re.search(r'<a class="brand-card[^>]+href="/merke/iwear/">(.*?)</a>', html, re.S).group(1)
        self.assertIn('/static/private-label/iwear-', card)
        self.assertNotIn('pli-iwear-pack', card)
        self.assertNotIn('/static/products/', card)

    def test_illustration_fallback_and_original_priority(self):
        product = {'name': 'Example', 'brand_label': 'Example', 'offers': [],
                   'illustration_image': '/static/product-illustrations/example.svg'}
        url = render._product_image(product)
        self.assertEqual(url, product['illustration_image'])
        html = render._product_hero_visual(product, url)
        self.assertIn('Egen illustrasjon, ikke et ekte produktbilde.', html)
        self.assertIn('href="/om-produktillustrasjoner/">Les mer</a>', html)
        self.assertIn('alt="Egen illustrasjon av Example"', html)
        product['manual_image'] = '/static/products/original.jpg'
        self.assertEqual(render._product_image(product), product['manual_image'])
        self.assertNotIn('own-illustration-note', render._product_hero_visual(product, product['manual_image']))

    def test_wrong_pack_images_are_excluded(self):
        import json
        catalog = json.loads((Path(__file__).parent / 'site_generator/catalog_live.json').read_text())
        product = next(p for p in catalog['products'] if p['id'] == 'freshlook-oneday-30pk')
        self.assertEqual(render._product_image(product), product['illustration_image'])
        self.assertEqual(len(product['excluded_image_urls']), 3)

    def test_validator_checks_srcset_even_when_original_exists(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(validate, 'BUILD_DIR', Path(tmp)):
            root = Path(tmp)
            (root / 'static').mkdir()
            (root / 'static/original.jpg').write_bytes(b'original')
            (root / 'index.html').write_text('<picture><source srcset="/static/missing.webp 1x, /static/original.jpg 2x"><img src="/static/original.jpg"></picture><img src="https://example.org/external.jpg">')
            errors = []
            validate.check_local_image_files(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn('/static/missing.webp', errors[0])
            (root / 'static/missing.webp').write_bytes(b'webp')
            errors = []
            validate.check_local_image_files(errors)
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
