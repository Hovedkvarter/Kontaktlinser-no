"""Preserve catalog observations per store; never treat a rebuild as a price check.

Monthly JSONL archives are append-only and intentionally have no age-based purge.
Only source checked_at timestamps are used. Missing offers do not imply sold out.
"""
import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'data/store_price_history'


def observations(catalog):
    for product in catalog['products']:
        for offer in product.get('offers', []):
            stamp = offer.get('checked_at')
            try:
                checked = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                if checked.tzinfo is None:
                    continue
                price = offer.get('price_nok')
                if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                    continue
            except (TypeError, ValueError, AttributeError):
                continue
            if not product.get('id') or not offer.get('retailer'):
                continue
            row = {key: offer.get(key) for key in (
                'retailer', 'price_nok', 'shipping_nok', 'shipping_policy',
                'in_stock', 'source', 'network')}
            row.update(product_id=product['id'], product_name=product.get('name'),
                       product_specs=product.get('specs'), currency='NOK',
                       checked_at=checked.astimezone(timezone.utc).isoformat())
            # is_stale/is_lowest are derived at render time, not observations.
            raw = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
            row['observation_id'] = hashlib.sha256(raw.encode()).hexdigest()
            yield row


def archive_catalog(catalog, directory=ARCHIVE, provenance='catalog'):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    grouped = {}
    for row in observations(catalog):
        grouped.setdefault(row['checked_at'][:7], []).append(row)
    added = 0
    for month, rows in grouped.items():
        path = directory / f'{month}.jsonl'
        existing = set()
        for saved in (path.with_suffix('.jsonl.gz'), path):
            if saved.exists():
                opener = gzip.open if saved.suffix == '.gz' else open
                with opener(saved, 'rt', encoding='utf-8') as source:
                    existing.update(json.loads(line)['observation_id'] for line in source if line.strip())
        with path.open('a', encoding='utf-8') as out:
            for row in rows:
                if row['observation_id'] in existing:
                    continue
                row['provenance'] = provenance
                out.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n')
                existing.add(row['observation_id'])
                added += 1
    return added


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT / 'site_generator/catalog_live.json')
    parser.add_argument('--archive', type=Path, default=ARCHIVE)
    args = parser.parse_args()
    count = archive_catalog(json.loads(args.catalog.read_text()), args.archive)
    print(f'Archived {count} new store price observations')
