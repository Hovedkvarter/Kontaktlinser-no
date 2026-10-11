"""Read archived observations for product charts; never fill missing dates."""
import gzip
import json
import math
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

ARCHIVE = Path(__file__).resolve().parents[1] / 'data/store_price_history'


@lru_cache(maxsize=1)
def load_store_days():
    latest = {}
    for path in sorted(ARCHIVE.glob('*.jsonl*')):
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8') as source:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                stamp = datetime.fromisoformat(row['checked_at'])
                day = stamp.astimezone(ZoneInfo('Europe/Oslo')).date().isoformat()
                key = (row['product_id'], row.get('product_name'), row['retailer'], day)
                price = row.get('price_nok')
                value = price if row.get('in_stock') is True and isinstance(price, (int, float)) and math.isfinite(price) and price > 0 else None
                previous = latest.get(key)
                if previous is None or stamp > previous[0]:
                    latest[key] = (stamp, value)
                elif stamp == previous[0] and value != previous[1]:
                    latest[key] = (stamp, None)  # Conflicting source evidence: show a gap.
    result = defaultdict(lambda: defaultdict(list))
    for (pid, name, store, day), (_, price) in sorted(latest.items(), key=lambda x: (x[0][0],str(x[0][1]),x[0][2],x[0][3])):
        result[(pid, name)][store].append({'date': day, 'price': price, 'store': store})
    return result


def product_store_days(product_id, product_name):
    # Name as well as canonical pack ID guards against a renamed/reassigned product.
    return dict(load_store_days().get((product_id, product_name), {})) if product_id else {}
