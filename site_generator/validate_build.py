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
  - en side i det bygde nettstedet er foreldreløs (ingen annen side lenker
    til den, kun sitemap.xml vet den finnes) - samme usynlige feilklasse som
    gjorde at alle 49 /serie/-sidene sto uindekserte i ukevis (2026-09-18),
    fanges nå automatisk her i stedet for å oppdages tilfeldig i Search
    Console måneder senere.

Advarer (exit code 0, men logger) hvis:
  - enkelte produkter mangler tilbud, men under terskelen
"""

import json
import re
import sys
from pathlib import Path

BUILD_DIR = Path(__file__).parent / "build"
CATALOG_PATH = Path(__file__).parent / "catalog_live.json"
BASE_URL = "https://kontaktlinser.no"
MAX_MISSING_RATIO = 0.3  # stopp utrulling hvis >30% av produktene har 0 tilbud

# Sider som bevisst IKKE trenger noen innkommende lenke fra en annen side:
# forsiden ER selve inngangspunktet, og 404-siden skal aldri lenkes til
# (den nås kun når noe annet allerede har feilet).
ORPHAN_EXEMPT_PATHS = {"/", "/404.html"}


def extract_json_ld(html: str) -> dict | None:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(1))  # kaster JSONDecodeError hvis ugyldig - det er meningen


def _internal_href_targets(html: str) -> set[str]:
    """Alle interne lenkemål (href) i en HTML-fil, normalisert til
    site-relative stier (f.eks. "/serie/acuvue-oasys/"). Både relative
    (/foo/) og fullt kvalifiserte (https://kontaktlinser.no/foo/) lenker
    telles, siden begge forekommer i kildekoden avhengig av kontekst."""
    targets: set[str] = set()
    for href in re.findall(r'href="([^"]+)"', html):
        if href.startswith(BASE_URL):
            href = href[len(BASE_URL):]
        if not href.startswith("/"):
            continue
        targets.add(href.split("?", 1)[0].split("#", 1)[0])
    return targets


def check_orphan_pages(errors: list[str]) -> None:
    """Enhver side i det ferdigbygde nettstedet som INGEN annen side
    faktisk lenker til -- kun oppdagbar for krypere via sitemap.xml -- er
    reelt foreldreløs. Krypere nedprioriterer slike sider kraftig i
    praksis: bekreftet 2026-09-18 at alle 49 /serie/-sidene sto
    "Oppdaget - ikke indeksert" i Search Console i ukevis av nøyaktig
    denne grunnen (ingen produkt- eller private label-side lenket til
    dem, kun sitemap.xml visste de fantes). Sjekker HELE det bygde
    nettstedet, ikke bare produktsider, siden denne feilklassen kan ramme
    enhver ny sidetype som legges til uten at noen husker å legge inn en
    kryssreferanse fra et annet sted."""
    all_pages: dict[str, Path] = {}
    for html_path in BUILD_DIR.rglob("index.html"):
        rel_dir = html_path.relative_to(BUILD_DIR).parent
        url_path = "/" if str(rel_dir) == "." else f"/{rel_dir.as_posix()}/"
        all_pages[url_path] = html_path

    linked_to: set[str] = set()
    for html_path in all_pages.values():
        linked_to |= _internal_href_targets(html_path.read_text(encoding="utf-8"))

    orphans = sorted(
        url_path for url_path in all_pages
        if url_path not in ORPHAN_EXEMPT_PATHS and url_path not in linked_to
    )
    for url_path in orphans:
        errors.append(f"FORELDRELØS SIDE: {url_path} -- ingen annen side lenker til den (kun i sitemap.xml)")


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

    check_orphan_pages(errors)

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
