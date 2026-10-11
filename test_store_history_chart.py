import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent/'site_generator'))
import store_history_chart as chart

class StoreChartTests(unittest.TestCase):
    def tearDown(self):
        chart.load_store_days.cache_clear()

    def test_latest_observation_local_day_stock_conflicts_and_identity(self):
        rows=[]
        def add(stamp,price,stock=True,name='Lens 30-pack'):
            rows.append(dict(product_id='lens-30',product_name=name,retailer='Store',checked_at=stamp,price_nok=price,in_stock=stock))
        add('2026-10-01T22:30:00+00:00',100)
        add('2026-10-02T12:00:00+00:00',110)
        add('2026-10-04T12:00:00+00:00',120,False)
        add('2026-10-05T12:00:00+00:00',125)
        add('2026-10-05T12:00:00+00:00',130)
        add('2026-10-06T12:00:00+00:00',20,name='Different pack')
        with tempfile.TemporaryDirectory() as tmp, patch.object(chart,'ARCHIVE',Path(tmp)):
            (Path(tmp)/'2026-10.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            data=chart.product_store_days('lens-30','Lens 30-pack')['Store']
            self.assertEqual([(r['date'],r['price']) for r in data],[('2026-10-02',110),('2026-10-04',None),('2026-10-05',None)])
            self.assertEqual(chart.product_store_days('another-pack','Lens 30-pack'),{})

if __name__ == '__main__': unittest.main()
