"""Recover only observations documented in committed catalogs, oldest first."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store_price_history import archive_catalog

if __name__ == '__main__':
    commits = subprocess.check_output(['git','log','--reverse','--format=%H','HEAD','--','site_generator/catalog_live.json'], text=True).splitlines()
    total = 0
    for sha in commits:
        raw = subprocess.check_output(['git','show',f'{sha}:site_generator/catalog_live.json'], text=True)
        total += archive_catalog(json.loads(raw), provenance=f'git:{sha}')
    print(f'Recovered {total} observations from {len(commits)} catalog revisions')
    # Immutable compressed baseline; future observations append to plain JSONL.
    import gzip
    from store_price_history import ARCHIVE
    for path in ARCHIVE.glob('*.jsonl'):
        target = path.with_suffix('.jsonl.gz')
        if target.exists():
            continue  # Never overwrite an existing baseline.
        target.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        path.unlink()
