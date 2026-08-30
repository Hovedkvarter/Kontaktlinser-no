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

from render_templates import render_product_page, render_category_page, render_home_page, render_guide_page, render_guides_index_page, render_brand_page, render_privacy_page, render_about_page, render_404_page, render_solution_product_page, render_solution_category_page, render_private_label_page, render_private_label_index_page, render_private_label_brand_page, render_manufacturer_page, render_illustration_disclaimer_page, render_terms_page, PRIVATE_LABEL_SUBBRANDS, MANUFACTURERS, BRAND_TO_MANUFACTURER, reconcile_product, _pack_size_from_id
from price_history import load_history, record_price, save_history

BUILD_DIR = Path(__file__).parent / "build"
CATALOG_PATH = Path(__file__).parent / "catalog.json"
SITE_CONTENT_PATH = Path(__file__).parent.parent / "site_content.json"
PRIVATE_LABELS_PATH = Path(__file__).parent.parent / "private_labels.json"


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


PUBLIC_CATALOG_VERSION = "1"


def _public_offers(offers: list[dict], now: datetime) -> list[dict]:
    """Bruker SAMME reconcile_product()-logikk som nettsidens egne
    tilbudskort -- pris/frakt/totalpris/lagerstatus i den offentlige
    feeden skal ALDRI kunne avvike fra det som faktisk vises på siden.
    checked_at (2026-08-27, dag 1 av kontrakten, ingen ekstern konsument
    ennå -- billigst mulig tidspunkt å legge den til) eksponerer data vi
    allerede har internt (brukt til is_stale i reconcile_product selv),
    siden ulike forhandlere/kilder kan ha ulik alder på prisen sin."""
    return [
        {
            "merchant": o["retailer"],
            "price": o["price_nok"],
            "shipping": o["shipping_nok"],
            "total_price": o["total"],
            "availability": "in_stock" if o["in_stock"] else "out_of_stock",
            "url": o["url"],
            "checked_at": o["checked_at"],
        }
        for o in reconcile_product(offers, now)
    ]


def build_public_catalog(lens_products: list[dict], solution_products: list[dict], now: datetime) -> dict:
    """Bygger den OFFENTLIGE, versjonerte data-kontrakten på /data/catalog.json
    -- en bevisst kuratert eksportform for eksterne integrasjoner (f.eks.
    Cartbooster), IKKE en rå kopi av catalog_live.json. catalog_live.json er
    et internt byggeformat som kan endre feltnavn/struktur når som helst uten
    varsel (se build_catalog.py); denne funksjonen er den ENESTE plassen som
    får lov til å endre formen på /data/catalog.json, og KUN med en økt
    "version" hvis endringen bryter bakoverkompatibilitet -- eksterne
    konsumenter skal kunne stole på formen uten å følge interne refaktoreringer.
    Ingen felt her er noe som ikke allerede vises offentlig et sted på en
    produktside (pris/frakt/lenke/lagerstatus) -- ingen ny eksponering.

    STABILE ID-ER: p["id"] (fra products_meta.json/solutions_meta.json) ER
    den offentlige kontraktens id-felt -- eksterne konsumenter (Cartbooster)
    forventes å lagre/referere denne på tvers av samtaler/analytics/AI-
    anbefalinger. Regel: ENDRE ALDRI en eksisterende produkt-id (selv om
    navn/URL/kategori endres) -- kun legg til nye id-er for nye produkter.
    Samme prinsipp som vi allerede fulgte ubevisst (ingen id er noensinne
    blitt endret i dette prosjektet), nå skrevet ned som en eksplisitt regel
    siden id-en har fått en ekstern konsument å svare til.

    CURRENCY: "NOK" er hardkodet på toppnivå, ikke per tilbud -- riktig
    design er én valuta per feed/marked (en fremtidig UK-versjon av denne
    kontrakten ville hatt sin egen "currency": "GBP", ikke blandet valuta i
    samme fil)."""
    products_out = []
    for p in lens_products:
        parsed = _pack_size_from_id(p["id"])
        manufacturer = MANUFACTURERS.get(BRAND_TO_MANUFACTURER.get(p["brand_slug"], ""), {}).get("name")
        products_out.append({
            "id": p["id"],
            "name": p["name"],
            "brand": p["brand_label"],
            "category": p["category_slug"],
            "pack_size": parsed[1] if parsed else None,
            "attributes": {"manufacturer": manufacturer} if manufacturer else {},
            "offers": _public_offers(p["offers"], now),
        })
    for p in solution_products:
        manufacturer = MANUFACTURERS.get(BRAND_TO_MANUFACTURER.get(p["brand_slug"], ""), {}).get("name")
        attributes = {"size_ml": p.get("size_ml")}
        if manufacturer:
            attributes["manufacturer"] = manufacturer
        products_out.append({
            "id": p["id"],
            "name": p["name"],
            "brand": p["brand_label"],
            "category": p["solution_category"],
            "pack_size": None,
            "attributes": attributes,
            "offers": _public_offers(p["offers"], now),
        })
    return {
        "version": PUBLIC_CATALOG_VERSION,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "NOK",
        "products": products_out,
    }


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

    private_labels = json.loads(PRIVATE_LABELS_PATH.read_text(encoding="utf-8"))["labels"] if PRIVATE_LABELS_PATH.exists() else []

    # Motsatt retning av private_labels.json sin vanlige bruk: her grupperer vi
    # etter det EKTE produktet, slik at produktsiden kan vise "selges også som"
    # -- private-label-siden lenker allerede den andre veien (til det ekte
    # produktet), men ikke omvendt før nå.
    aliases_by_product_id: dict[str, list[dict]] = {}
    for label in private_labels:
        aliases_by_product_id.setdefault(label["real_product_id"], []).append(label)

    home_html = render_home_page({**catalog, "products": lens_products}, now, private_labels=private_labels)
    write_file(BUILD_DIR / "index.html", home_html)
    print("  forside  -> /")

    products_by_id = {p["id"]: p for p in lens_products}

    price_history = load_history()
    today = now.date().isoformat()

    products_written = []
    for product in lens_products:
        offers = reconcile_product(product["offers"], now)
        best = next((o for o in offers if o["is_lowest"]), None)
        # Prishistorikk-grafen skal vise laveste PRODUKTPRIS (uten frakt),
        # ikke laveste totalpris -- kan være en ANNEN forhandler enn den som
        # vinner på total (den med lavest frakt vinner ikke nødvendigvis på
        # ren produktpris). Regnes derfor ut separat fra best["total"].
        eligible = [o for o in offers if o["in_stock"]]
        if eligible:
            cheapest = min(eligible, key=lambda o: o["price_nok"])
            record_price(price_history, product["id"], today, cheapest["price_nok"], cheapest["retailer"])

        html = render_product_page(product, catalog["categories"], products_by_id, price_history.get(product["id"], []), now, aliases_by_product_id.get(product["id"], []))
        out_path = BUILD_DIR / "kontaktlinser" / product["brand_slug"] / product["slug"] / "index.html"
        write_file(out_path, html)
        products_written.append(product)
        print(f"  produkt  -> /kontaktlinser/{product['brand_slug']}/{product['slug']}/")

    solutions_written = []
    for product in solution_products:
        offers = reconcile_product(product["offers"], now)
        best = next((o for o in offers if o["is_lowest"]), None)
        eligible = [o for o in offers if o["in_stock"]]
        if eligible:
            cheapest = min(eligible, key=lambda o: o["price_nok"])
            record_price(price_history, product["id"], today, cheapest["price_nok"], cheapest["retailer"])

        cat_slug = product["solution_category"]
        html = render_solution_product_page(product, now)
        out_path = BUILD_DIR / cat_slug / product["brand_slug"] / product["slug"] / "index.html"
        write_file(out_path, html)
        solutions_written.append(product)
        print(f"  {cat_slug} -> /{cat_slug}/{product['brand_slug']}/{product['slug']}/")

    save_history(price_history)

    public_catalog = build_public_catalog(lens_products, solution_products, now)
    write_file(BUILD_DIR / "data" / "catalog.json", json.dumps(public_catalog, indent=2, ensure_ascii=False))
    print(f"  data     -> /data/catalog.json ({len(public_catalog['products'])} produkter)")

    solution_categories = sorted({p["solution_category"] for p in solution_products})
    for cat_slug in solution_categories:
        products_in_cat = [p for p in solution_products if p["solution_category"] == cat_slug]
        write_file(BUILD_DIR / cat_slug / "index.html", render_solution_category_page(cat_slug, products_in_cat, now))
        print(f"  {cat_slug} -> /{cat_slug}/")

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

    brand_counts = {slug: len([p for p in lens_products if p["brand_slug"] == slug]) for slug in brand_labels}
    for manufacturer_slug in MANUFACTURERS:
        html = render_manufacturer_page(manufacturer_slug, brand_counts, brand_labels)
        out_path = BUILD_DIR / "produsent" / manufacturer_slug / "index.html"
        write_file(out_path, html)
        print(f"  produsent -> /produsent/{manufacturer_slug}/")

    if private_labels:
        for label in private_labels:
            real_product = products_by_id.get(label["real_product_id"])
            if real_product is None:
                print(f"  [advarsel] private label '{label['slug']}' peker til ukjent produkt-id: {label['real_product_id']}")
                continue
            html = render_private_label_page(label, real_product, catalog["categories"], now)
            write_file(BUILD_DIR / "private-label" / label["slug"] / "index.html", html)
            print(f"  private-label -> /private-label/{label['slug']}/")

        write_file(BUILD_DIR / "private-label" / "index.html", render_private_label_index_page(private_labels, products_by_id, catalog["categories"], now))
        print("  private-label -> /private-label/")

        labels_by_chain: dict[str, list[dict]] = {}
        for label in private_labels:
            labels_by_chain.setdefault(label["chain"], []).append(label)
        for chain, chain_labels in labels_by_chain.items():
            slug = PRIVATE_LABEL_SUBBRANDS.get(chain, chain).lower()
            html = render_private_label_brand_page(chain, chain_labels, products_by_id, catalog["categories"], now)
            write_file(BUILD_DIR / "merke" / slug / "index.html", html)
            print(f"  merke    -> /merke/{slug}/ ({chain})")

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

    write_file(BUILD_DIR / "vilkar" / "index.html", render_terms_page(now))
    print("  vilkar   -> /vilkar/")

    write_file(BUILD_DIR / "om-oss" / "index.html", render_about_page())
    print("  om oss   -> /om-oss/")

    write_file(BUILD_DIR / "om-produktillustrasjoner" / "index.html", render_illustration_disclaimer_page())
    print("  illustrasjoner -> /om-produktillustrasjoner/")

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
    solution_categories = sorted({p["solution_category"] for p in solution_products})
    private_labels = json.loads(PRIVATE_LABELS_PATH.read_text(encoding="utf-8"))["labels"] if PRIVATE_LABELS_PATH.exists() else []
    site_content = {
        "static_pages": [
            {"path": "/", "lastmod": today},
            {"path": "/personvern/", "lastmod": today},
            {"path": "/om-oss/", "lastmod": today},
            {"path": "/om-produktillustrasjoner/", "lastmod": today},
            {"path": "/vilkar/", "lastmod": today},
        ] + [
            {"path": f"/{cat_slug}/", "lastmod": today} for cat_slug in solution_categories
        ] + ([{"path": "/private-label/", "lastmod": today}] if private_labels else []),
        "categories": [
            {"slug": slug, "lastmod": today} for slug in catalog["categories"].keys()
        ],
        "brands": [
            {"slug": b, "lastmod": today}
            for b in sorted({p["brand_slug"] for p in lens_products})
        ] + [
            {"slug": PRIVATE_LABEL_SUBBRANDS.get(chain, chain).lower(), "lastmod": today}
            for chain in sorted({label["chain"] for label in private_labels})
        ],
        "manufacturers": [
            {"slug": slug, "lastmod": today} for slug in MANUFACTURERS
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
            {"solution_category": p["solution_category"], "brand_slug": p["brand_slug"], "slug": p["slug"], "lastmod": today}
            for p in solution_products
        ],
        "private_labels": [
            {"slug": label["slug"], "lastmod": today} for label in private_labels
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
