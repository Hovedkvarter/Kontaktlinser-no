import gzip
import json
import tempfile
import unittest
from pathlib import Path
from store_price_history import archive_catalog

class StoreHistoryTests(unittest.TestCase):
    def test_observations_survive_changes_and_removal_without_rebuild_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            offer = dict(retailer='Shop', price_nok=100, checked_at='2026-10-10T10:00:00+00:00', in_stock=True)
            catalog = {'products': [dict(id='lens-30', name='Lens 30 pack', offers=[offer, dict(offer, retailer='Other', price_nok=120)])]}
            self.assertEqual(archive_catalog(catalog, tmp), 2)
            path = Path(tmp)/'2026-10.jsonl'
            path.with_suffix('.jsonl.gz').write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            path.unlink()
            self.assertEqual(archive_catalog(catalog, tmp), 0)
            offer['is_stale'] = True
            self.assertEqual(archive_catalog(catalog, tmp), 0)
            offer.update(price_nok=90, checked_at='2026-10-10T15:00:00+00:00', in_stock=False)
            self.assertEqual(archive_catalog(catalog, tmp), 1)
            self.assertEqual(archive_catalog({'products': []}, tmp), 0)
            rows = [json.loads(x) for x in (gzip.decompress(path.with_suffix('.jsonl.gz').read_bytes()).decode() + path.read_text()).splitlines()]
            self.assertEqual([r['price_nok'] for r in rows], [100,120,90])
            self.assertFalse(rows[-1]['in_stock'])

    def test_missing_timestamps_and_invalid_prices_are_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            offers = [dict(retailer='Shop',price_nok=p,checked_at=t) for p,t in [(0,'2026-10-10T00:00:00Z'),(float('nan'),'2026-10-10T00:00:00Z'),(100,None),(100,'2026-10-10'),(100,'2026-10-10T00:00:00Z')]]
            self.assertEqual(archive_catalog({'products':[dict(id='x',offers=offers)]},tmp),1)

if __name__ == '__main__':
    unittest.main()
