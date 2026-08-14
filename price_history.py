"""
price_history.py

Lagrer én "laveste pris"-måling per produkt per dag, til bruk i
prisutviklingsgrafen på produktsidene. Kalles fra generate_pages.py sin
build(), rett etter at hver produktsides tilbud er avstemt med SAMME
reconcile_product()-kall som avgjør hva som faktisk vises som "laveste
pris" akkurat da -- historikken skal alltid stemme med det som faktisk
sto på siden den dagen, ikke beregnes separat.

Bygget kjører hver 6. time, men vi vil ha ett punkt per dag, ikke fire --
record_price() overskriver derfor dagens rad i stedet for å legge til en
ny hver gang. Beholder maks MAX_DAYS rader, eldre rader forsvinner
automatisk ved neste kall.
"""

import json
from pathlib import Path

HISTORY_PATH = Path(__file__).parent / "site_generator" / "price_history.json"
MAX_DAYS = 365


def load_history(path: Path = HISTORY_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def record_price(history: dict, product_id: str, date_str: str, price: float, store: str) -> None:
    """Setter/overskriver dagens rad for produktet, sortert på dato, kuttet
    til de siste MAX_DAYS radene."""
    entries = history.setdefault(product_id, [])
    entries[:] = [e for e in entries if e["date"] != date_str]
    entries.append({"date": date_str, "price": price, "store": store})
    entries.sort(key=lambda e: e["date"])
    if len(entries) > MAX_DAYS:
        del entries[: len(entries) - MAX_DAYS]


def save_history(history: dict, path: Path = HISTORY_PATH) -> None:
    cleaned = {pid: entries for pid, entries in history.items() if entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
