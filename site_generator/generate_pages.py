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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # for generate_sitemap.py, price_history.py

from render_templates import render_product_page, render_category_page, render_home_page, render_guide_page, render_guides_index_page, render_brand_page, render_privacy_page, render_about_page, render_404_page, render_solution_product_page, render_solution_category_page, reconcile_product
from price_history import load_history, record_price, save_history

BUILD_DIR = Path(__file__).parent / "build"
CATALOG_PATH = Path(__file__).parent / "catalog.json"
SITE_CONTENT_PATH = Path(__file__).parent.parent / "site_content.json"


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(catalog_path: Path = CATALOG_PATH, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    # Linsevæske o.l. (fra solutions_meta.json, slått sammen inn i samme
    # katalog av build_catalog.py) har en annen datamodell -- ingen
    # category_slug -- og skal IKKE inn i de kontaktlinse-spesifikke løkkene
    # under (kategori-/merkesider leser categories[p["category_slug"]] og
    # ville krasjet på et produkt uten det feltet). Skilt ut her én gang.
    lens_products = [p for p in catalog["products"] if "category_slug" in p]
    solution_products = [p for p in catalog["products"] if "category_slug" not in p]

    home_html = render_home_page({**catalog, "products": lens_products}, now)
    write_file(BUILD_DIR / "index.html", home_html)
    print("  forside  -> /")

    products_by_id = {p["id"]: p for p in lens_products}

    price_history = load_history()
    today = now.date().isoformat()

    products_written = []
    for product in lens_products:
        offers = reconcile_product(product["offers"], now)
        best = next((o for o in offers if o["is_lowest"]), None)
        if best:
            record_price(price_history, product["id"], today, best["total"], best["retailer"])

        html = render_product_page(product, catalog["categories"], products_by_id, price_history.get(product["id"], []), now)
        out_path = BUILD_DIR / "kontaktlinser" / product["brand_slug"] / product["slug"] / "index.html"
        write_file(out_path, html)
        products_written.append(product)
        print(f"  produkt  -> /kontaktlinser/{product['brand_slug']}/{product['slug']}/")

    solutions_written = []
    for product in solution_products:
        offers = reconcile_product(product["offers"], now)
        best = next((o for o in offers if o["is_lowest"]), None)
        if best:
            record_price(price_history, product["id"], today, best["total"], best["retailer"])

        html = render_solution_product_page(product, now)
        out_path = BUILD_DIR / "linsevaeske" / product["brand_slug"] / product["slug"] / "index.html"
        write_file(out_path, html)
        solutions_written.append(product)
        print(f"  linsevæske -> /linsevaeske/{product['brand_slug']}/{product['slug']}/")

    save_history(price_history)

    write_file(BUILD_DIR / "linsevaeske" / "index.html", render_solution_category_page(solution_products, now))
    print("  linsevæske -> /linsevaeske/")

    for category_slug, category in catalog["categories"].items():
        products_in_category = [p for p in lens_products if p["category_slug"] == category_slug]
        html = render_category_page(category_slug, category, products_in_category, now)
        out_path = BUILD_DIR / "kontaktlinser" / category_slug / "index.html"
        write_file(out_path, html)
        print(f"  kategori -> /kontaktlinser/{category_slug}/")

    brand_labels = {p["brand_slug"]: p["brand_label"] for p in lens_products}
    for brand_slug, brand_label in brand_labels.items():
        products_for_brand = [p for p in lens_products if p["brand_slug"] == brand_slug]
        html = render_brand_page(brand_slug, brand_label, products_for_brand, catalog["categories"], now)
        out_path = BUILD_DIR / "merke" / brand_slug / "index.html"
        write_file(out_path, html)
        print(f"  merke    -> /merke/{brand_slug}/")

    guide_slugs = {g["slug"] for cat in catalog["categories"].values() for g in cat.get("guides", [])}
    for slug in guide_slugs:
        html = render_guide_page(slug)
        if html is None:
            print(f"  [advarsel] guide referert i en kategori, men mangler innhold: {slug}")
            continue
        write_file(BUILD_DIR / "guide" / slug / "index.html", html)
        print(f"  guide    -> /guide/{slug}/")

    write_file(BUILD_DIR / "guider" / "index.html", render_guides_index_page())
    print("  guider   -> /guider/")

    write_file(BUILD_DIR / "personvern" / "index.html", render_privacy_page(now))
    print("  personvern -> /personvern/")

    write_file(BUILD_DIR / "om-oss" / "index.html", render_about_page())
    print("  om oss   -> /om-oss/")

    write_file(BUILD_DIR / "404.html", render_404_page())
    print("  404      -> /404.html")

    static_src = Path(__file__).parent.parent / "static"
    if static_src.exists():
        static_out = BUILD_DIR / "static"
        shutil.copytree(static_src, static_out, dirs_exist_ok=True)
    return catalog


def update_site_content(catalog: dict, now: datetime) -> None:
    """Skriver site_content.json på nytt fra katalogen, med lastmod = nå,
    slik at generate_sitemap.py alltid reflekterer det som faktisk ble bygget."""
    today = now.date().isoformat()
    lens_products = [p for p in catalog["products"] if "category_slug" in p]
    solution_products = [p for p in catalog["products"] if "category_slug" not in p]
    site_content = {
        "static_pages": [
            {"path": "/", "lastmod": today},
            {"path": "/personvern/", "lastmod": today},
            {"path": "/om-oss/", "lastmod": today},
            {"path": "/linsevaeske/", "lastmod": today},
        ],
        "categories": [
            {"slug": slug, "lastmod": today} for slug in catalog["categories"].keys()
        ],
        "brands": [
            {"slug": b, "lastmod": today}
            for b in sorted({p["brand_slug"] for p in lens_products})
        ],
        "guides": [
            {"slug": g["slug"], "lastmod": today}
            for cat in catalog["categories"].values()
            for g in cat.get("guides", [])
        ],
        "products": [
            {"brand_slug": p["brand_slug"], "product_slug": p["slug"], "lastmod": today}
            for p in lens_products
        ],
        "solutions": [
            {"brand_slug": p["brand_slug"], "slug": p["slug"], "lastmod": today}
            for p in solution_products
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
