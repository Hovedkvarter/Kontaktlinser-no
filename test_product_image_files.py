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
