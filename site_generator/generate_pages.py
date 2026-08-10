"""
generate_pages.py

Kjør denne som siste steg i bygge-jobben, etter at ingest_feed.py/scraper.py
har oppdatert prisdataene. Leser catalog.json, skriver én HTML-fil per
produkt og én per kategori til build/, og oppdaterer til slutt
site_content.json + sitemap.xml slik at nye/endrede sider faktisk blir
oppdaget.

    python3 generate_pages.py

Output-struktur (matcher URL-skjemaet fra informasjonsarkitekturen):
    build/kontaktlinser/{brand_slug}/{product_slug}/index.html
    build/kontaktlinser/{category_slug}/index.html
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # for generate_sitemap.py

from render_templates import render_product_page, render_category_page, render_home_page

BUILD_DIR = Path(__file__).parent / "build"
CATALOG_PATH = Path(__file__).parent / "catalog.json"
SITE_CONTENT_PATH = Path(__file__).parent.parent / "site_content.json"


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(catalog_path: Path = CATALOG_PATH, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    home_html = render_home_page(catalog, now)
    write_file(BUILD_DIR / "index.html", home_html)
    print("  forside  -> /")

    products_written = []
    for product in catalog["products"]:
        html = render_product_page(product, now)
        out_path = BUILD_DIR / "kontaktlinser" / product["brand_slug"] / product["slug"] / "index.html"
        write_file(out_path, html)
        products_written.append(product)
        print(f"  produkt  -> /kontaktlinser/{product['brand_slug']}/{product['slug']}/")

    for category_slug, category in catalog["categories"].items():
        products_in_category = [p for p in catalog["products"] if p["category_slug"] == category_slug]
        html = render_category_page(category_slug, category, products_in_category, now)
        out_path = BUILD_DIR / "kontaktlinser" / category_slug / "index.html"
        write_file(out_path, html)
        print(f"  kategori -> /kontaktlinser/{category_slug}/")

    return catalog


def update_site_content(catalog: dict, now: datetime) -> None:
    """Skriver site_content.json på nytt fra katalogen, med lastmod = nå,
    slik at generate_sitemap.py alltid reflekterer det som faktisk ble bygget."""
    today = now.date().isoformat()
    site_content = {
        "static_pages": [{"path": "/", "lastmod": today}],
        "categories": [
            {"slug": slug, "lastmod": today} for slug in catalog["categories"].keys()
        ],
        "brands": [
            {"slug": b, "lastmod": today}
            for b in sorted({p["brand_slug"] for p in catalog["products"]})
        ],
        "guides": [
            {"slug": g["slug"], "lastmod": today}
            for cat in catalog["categories"].values()
            for g in cat.get("guides", [])
        ],
        "products": [
            {"brand_slug": p["brand_slug"], "product_slug": p["slug"], "lastmod": today}
            for p in catalog["products"]
        ],
    }
    SITE_CONTENT_PATH.write_text(json.dumps(site_content, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    catalog_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CATALOG_PATH
    print(f"Bygger sider fra {catalog_path} ...")

    now = datetime.now(timezone.utc)
    catalog = build(catalog_path, now)

    print("Oppdaterer site_content.json ...")
    update_site_content(catalog, now)

    print("Regenererer sitemap ...")
    import generate_sitemap
    import os
    os.chdir(Path(__file__).parent.parent)
    generate_sitemap.main()

    print("Ferdig.")
