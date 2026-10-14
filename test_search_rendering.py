"""Search compilation contracts; sitewide assertions run after the ordinary build."""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'site_generator'))
from search_assets import compile_search, search_program

LEGACY = '\n(function () { /* legacy-search-fixture */ })();\n'


class SearchCompilationTests(unittest.TestCase):
    def test_only_search_fragment_changes(self):
        before = '<html><title>Uendret</title><script>menu();' + LEGACY + '</script><a href="/go/token">Butikk</a><script type="application/ld+json">{"url":"https://kontaktlinser.no/"}</script></html>'
        after = compile_search(before, LEGACY)
        self.assertEqual(after.replace(search_program(), LEGACY), before)
        self.assertEqual(after.count('Kontaktlinser.no search v2.'), 1)

    def test_empty_marker_rejected(self):
        with self.assertRaises(ValueError): compile_search('anything', '')

    def test_duplicate_script_rejected(self):
        with self.assertRaises(ValueError): compile_search(LEGACY * 2, LEGACY)

    def test_missing_script_with_form_rejected(self):
        with self.assertRaises(ValueError): compile_search('<form class="topbar-search search-row"></form>', LEGACY)

    def test_no_form_page_unchanged(self):
        self.assertEqual(compile_search('<html>No search</html>', LEGACY), '<html>No search</html>')

    def test_safe_inlining(self):
        self.assertNotIn('</script', search_program().lower())

    def test_hook_only_changes_html(self):
        source = (ROOT / 'site_generator/generate_pages.py').read_text()
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'write_file')
        self.assertIn('if path.suffix == ".html":', ast.get_source_segment(source, fn))
        self.assertIn('compile_search(content, LENS_SEARCH_JS)', ast.get_source_segment(source, fn))

    def test_guide_tracking_contract_retained(self):
        code = search_program()
        self.assertIn("event: 'guide_search_click', guide: guide, product: name, source: source", code)
        self.assertNotIn('outbound_click', code)
        self.assertNotIn('gtag(', code)

    @unittest.skipUnless((ROOT / 'site_generator/build/index.html').exists(), 'full build not present locally')
    def test_all_built_html_uses_one_search_program(self):
        from render_templates import LENS_SEARCH_JS
        pages = list((ROOT / 'site_generator/build').rglob('*.html'))
        self.assertGreater(len(pages), 400)
        checked = 0
        for page in pages:
            html = page.read_text(encoding='utf-8')
            if re.search(r'class=["\'][^"\']*\bsearch-row\b', html):
                checked += 1
                self.assertNotIn(LENS_SEARCH_JS, html, str(page))
                self.assertEqual(html.count('Kontaktlinser.no search v2.'), 1, str(page))
                self.assertNotIn('item.search.indexOf(q)', html, str(page))
        self.assertGreater(checked, 400)
        print(f'Built pages with new search verified: {checked}')


if __name__ == '__main__':
    unittest.main()
