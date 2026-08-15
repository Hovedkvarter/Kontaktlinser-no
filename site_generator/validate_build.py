"""
validate_build.py

Kjøres etter generate_pages.py, før noe rulles ut. Dette er terskelen mellom
"koden kjørte uten feil" og "siden er faktisk trygg å publisere" - de er
ikke det samme, som biofinity-eksempelet fra forrige runde viste.

Feiler (exit code 1) hvis:
  - en produktside mangler helt fra build/
  - en produktside har ugyldig JSON-LD (ødelagt strukturert data er verre
    enn ingen, siden det kan gi feil informasjon til Google/AI uten at noen
    ser det i en vanlig sidevisning)
  - andelen produkter uten noen tilbud er over en terskel - ett produkt uten
    data er normalt (feed hakket), mange samtidig er sannsynligvis en
    ekte feed- eller nettverksfeil, ikke reelt utsolgt hos alle.

Advarer (exit code 0, men logger) hvis:
  - enkelte produkter mangler tilbud, men under terskelen
"""

import json
import re
import sys
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build"
CATALOG_PATH = Path(__file__).parent / "catalog_live.json"
MAX_MISSING_RATIO = 0.3  # stopp utrulling hvis >30% av produktene har 0 tilbud


def extract_json_ld(html: str) -> dict | None:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(1))  # kaster JSONDecodeError hvis ugyldig - det er meningen


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    missing_offers_count = 0

    for product in catalog["products"]:
        # Linsevæske/øyedråper o.l. (fra solutions_meta.json) mangler
        # category_slug og ligger under /{solution_category}/, ikke
        # /kontaktlinser/ -- se generate_pages.py.
        base_dir = "kontaktlinser" if "category_slug" in product else product["solution_category"]
        page_path = BUILD_DIR / base_dir / product["brand_slug"] / product["slug"] / "index.html"

        if not page_path.exists():
            errors.append(f"MANGLER SIDE: {page_path}")
            continue

        html = page_path.read_text(encoding="utf-8")

        try:
            extract_json_ld(html)
        except json.JSONDecodeError as e:
            errors.append(f"UGYLDIG JSON-LD: {page_path} ({e})")

        if not product.get("offers"):
            missing_offers_count += 1
            warnings.append(f"Ingen tilbud: {product['id']} (publiseres uten priser)")

    missing_ratio = missing_offers_count / len(catalog["products"]) if catalog["products"] else 0
    if missing_ratio > MAX_MISSING_RATIO:
        errors.append(
            f"{missing_offers_count}/{len(catalog['products'])} produkter har 0 tilbud "
            f"({missing_ratio:.0%}, terskel er {MAX_MISSING_RATIO:.0%}). "
            f"Dette ser ut som en feed- eller nettverksfeil, ikke reell utsolgthet hos alle."
        )

    for w in warnings:
        print(f"  [advarsel] {w}")

    if errors:
        print("\nBygget er IKKE trygt å rulle ut:")
        for e in errors:
            print(f"  [feil] {e}")
        return 1

    print(f"\nValidering OK - {len(catalog['products']) - missing_offers_count}/{len(catalog['products'])} produkter har priser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
