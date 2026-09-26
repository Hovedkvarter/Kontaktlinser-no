"""
build_catalog.py

Limet mellom datainnhenting og sidegenerering. Kjøres etter at feeds er
lagt i feeds/ og før generate_pages.py:

    python3 build_catalog.py
    python3 site_generator/generate_pages.py site_generator/catalog_live.json

Leser:
  - products_meta.json     (statisk produktkatalog, ingen priser)
  - product_matching.json  (SKU/produktnummer -> produkt-id per nettverk)
  - sources_config.json    (feed eller scraper per forhandler/merke)

Skriver:
  - site_generator/catalog_live.json, i formatet generate_pages.py forventer.

Et tilbud som ikke kan matches til et kjent produkt-id blir ALDRI limt inn
et sted basert på gjetning - det logges og hoppes over allerede i
ingest_feed.load_feed(). Et produkt uten noen tilbud publiseres uten priser,
ikke med en gjettet eller gammel pris.
"""

import json
import os
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from offer import Offer
from ingest_feed import load_feed, load_feed_url, load_tradedoubler_feed
from scraper import scrape_product, should_scrape

ROOT = Path(__file__).parent
PRODUCTS_META_PATH = ROOT / "products_meta.json"
SOLUTIONS_META_PATH = ROOT / "solutions_meta.json"
PRODUCT_MATCHING_PATH = ROOT / "product_matching.json"
SOURCES_CONFIG_PATH = ROOT / "sources_config.json"
OUTPUT_PATH = ROOT / "site_generator" / "catalog_live.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_feed_offers(sources_config: dict, product_matching: dict) -> dict[str, list[Offer]]:
    """Kjør load_feed()/load_feed_url() for hver forhandler som har
    affiliate_feed konfigurert - enten som forhandler-bred standard eller
    som merke-spesifikk override - og grupper resultatet per produkt-id
    (satt av mapper-funksjonene selv). feed_url (ekte, levende feeds) hentes
    ferskt over HTTP hver gang; feed_path (lokale testfeeds) leses fra disk."""
    offers_by_product: dict[str, list[Offer]] = {}

    def _ingest(network: str, cfg: dict) -> None:
        match_map = product_matching.get(network, {})
        if "feed_urls" in cfg:
            # Paginert JSON-API, ikke en flat CSV-fil -- egen henter, se
            # load_tradedoubler_feed() i ingest_feed.py. feed_urls (flertall)
            # siden Shopping4net trenger flere søk for å dekke hele
            # katalogen (ett enkelt søk dekker ikke både linser og
            # øyeplager-produkter) -- Lenson/Lensway sine mindre kataloger
            # hentes derimot fullt ut med kun ett usøkt/paginert kall, så
            # for dem har feed_urls bare ett element. Nøkkelen på cfg
            # ("feed_urls", flertall) i stedet for network=="tradedoubler"
            # gjør dette forhandler-uavhengig -- samme prinsipp som feed_url/
            # feed_path-grenene under.
            offers = load_tradedoubler_feed(cfg["feed_urls"], match_map, cfg)
        elif "feed_url" in cfg:
            offers = load_feed_url(cfg["feed_url"], network, match_map, cfg)
        else:
            feed_path = ROOT / cfg["feed_path"]
            if not feed_path.exists():
                print(f"  [hopper over] feed ikke funnet: {feed_path}")
                return
            offers = load_feed(str(feed_path), network, match_map, cfg)
        for offer in offers:
            offers_by_product.setdefault(offer.product_id, []).append(offer)

    for retailer, cfg in sources_config.items():
        if retailer.startswith("$"):
            continue
        if cfg.get("default_source") == "affiliate_feed" and ("feed_path" in cfg or "feed_url" in cfg or "feed_urls" in cfg):
            _ingest(cfg["network"], cfg)

        for brand, override in cfg.get("brand_overrides", {}).items():
            if override.get("source") == "affiliate_feed":
                _ingest(override["network"], override)

    # Se product_matching.json sin "duplicate_products"-kommentar: en feed-
    # tabell kan bare mappe én SKU til ÉN product_id, så et par som Focus
    # Dailies / Dailies All Day Comfort (bekreftet samme fysiske vare, to
    # katalog-oppføringer) kan aldri begge fylles av samme feed-rad via
    # vanlig 1:1-matching. Kloner derfor tilbudene fra primær-id-en til
    # hver alias-id, med riktig product_id satt på hver kopi -- men KUN for
    # forhandlere alias-id-en ikke allerede har et EKTE, uavhengig treff
    # for selv (f.eks. Extra Optical/Shopping4net har egne SKU-rader for
    # begge navnene i sine feeds, og skal ikke overskrives/dupliseres).
    duplicate_products = product_matching.get("duplicate_products", {})
    for primary_id, alias_ids in duplicate_products.items():
        if primary_id.startswith("$"):
            continue
        primary_offers = offers_by_product.get(primary_id, [])
        for alias_id in alias_ids:
            existing_retailers = {o.retailer for o in offers_by_product.get(alias_id, [])}
            for offer in primary_offers:
                if offer.retailer in existing_retailers:
                    continue
                offers_by_product.setdefault(alias_id, []).append(replace(offer, product_id=alias_id))

    return offers_by_product


def collect_scraped_offers(products_meta: dict, sources_config: dict) -> dict[str, list[Offer]]:
    """For hvert produkt: scrape kun de (forhandler, slug)-parene som
    fortsatt er satt til 'scraper' i sources_config akkurat nå. Et merke som
    nylig fikk en godkjent avtale faller automatisk ut her uten kodeendring."""
    offers_by_product: dict[str, list[Offer]] = {}

    for product in products_meta["products"]:
        for target in product.get("scrape_targets", []):
            retailer = target["retailer"]
            if retailer not in sources_config:
                print(f"  [advarsel] ukjent forhandler i scrape_targets: {retailer}")
                continue
            if not should_scrape(sources_config, retailer, product["brand_slug"]):
                continue  # flyttet til feed siden sist - ikke scrape

            offer = scrape_product(
                retailer, product["brand_slug"], target["slug"], sources_config[retailer],
                expected_variant=target.get("variant"),
            )
            if offer is None:
                print(f"  [ingen data] scraping av {retailer}/{target['slug']} ga ikke noe tilbud")
                continue
            offer.product_id = product["id"]
            offers_by_product.setdefault(product["id"], []).append(offer)

    return offers_by_product


# Daglig kjøring (fra 2026-09-26): feedene hentes hver gang, men skraping er
# tregt (~8 min, bevisst 3 s pause per domene) og skrapede priser endrer seg
# sjelden (målt over 18 dager: 5 av 8 forhandlere 0 endringer). Full skraping
# gjøres derfor ca. annenhver dag. Beslutningen tas ut fra DATA, ikke
# ukedag/paritet: er de nyeste skrapede tilbudene i forrige catalog_live.json
# yngre enn grensen, gjenbrukes de; ellers skrapes alt på nytt. Det tåler
# GitHub sine cron-forsinkelser og en feilet kjøring uten å hoppe over to
# ganger på rad. 36 t gir daglig kjøring -> skrap dag 1, gjenbruk dag 2, skrap dag 3.
SCRAPE_MAX_AGE_HOURS = 36


def reuse_fresh_scraped_offers(products_meta: dict, sources_config: dict) -> dict[str, list[Offer]] | None:
    """Kun når KL_SKIP_FRESH_SCRAPE=1 (satt av den planlagte kjøringen i
    build-and-deploy.yml -- manuell kjøring og lokal kjøring skraper alltid
    fullt). Returnerer forrige runde sine skrapede tilbud UENDRET, inkludert
    deres opprinnelige checked_at (siden viser dermed ærlig når de sist ble
    kontrollert), eller None hvis vi ikke trygt kan gjenbruke -- da skraper
    kalleren som vanlig."""
    try:
        previous = load_json(OUTPUT_PATH)
        previous_products = {p["id"]: p for p in previous["products"]}
    except (OSError, ValueError, KeyError):
        print("  [full skraping] fant ikke en lesbar forrige catalog_live.json")
        return None

    newest = None
    for p in previous["products"]:
        for o in p.get("offers", []):
            if o.get("source") == "scraper":
                checked = datetime.fromisoformat(o["checked_at"])
                if newest is None or checked > newest:
                    newest = checked
    if newest is None:
        print("  [full skraping] forrige katalog har ingen skrapede tilbud")
        return None
    age_hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
    if age_hours >= SCRAPE_MAX_AGE_HOURS:
        print(f"  [full skraping] forrige skraping er {age_hours:.0f} t gammel (grense {SCRAPE_MAX_AGE_HOURS} t)")
        return None

    reused: dict[str, list[Offer]] = {}
    for product in products_meta["products"]:
        active = set()
        for target in product.get("scrape_targets", []):
            retailer = target["retailer"]
            if retailer in sources_config and should_scrape(sources_config, retailer, product["brand_slug"]):
                active.add(sources_config[retailer].get("display_name", retailer))
        if not active:
            continue
        for o in previous_products.get(product["id"], {}).get("offers", []):
            if o.get("source") == "scraper" and o["retailer"] in active:
                try:
                    reused.setdefault(product["id"], []).append(Offer(**o))
                except TypeError:
                    print("  [full skraping] forrige katalog har et uventet tilbudsformat")
                    return None
    if not reused:
        print("  [full skraping] ingen skrapede tilbud å gjenbruke")
        return None
    n = sum(len(v) for v in reused.values())
    print(f"Gjenbruker {n} skrapede tilbud fra forrige kjøring ({age_hours:.0f} t gamle, grense {SCRAPE_MAX_AGE_HOURS} t) -- hopper over skraping")
    return reused


# Beskyttelse mot at en forhandler "faller ut" av siden (bestemt 2026-09-26:
# Kai ville ikke at overgangen til daglig oppdatering skulle gjøre at noen
# forsvinner). Før daglig kjøring rettet neste kjøring en glipp innen 6 t; nå
# ville en feilet henting gitt opptil 48 t uten forhandleren. Feed-glippen
# 2026-09-19 (Extra Optical ga 0 rader uten feilmelding og alle 82 tilbud
# forsvant) er det konkrete eksempelet. Gjenbrukte tilbud beholder sin
# opprinnelige checked_at (siden viser dermed når de sist ble kontrollert) og
# faller ut av seg selv når de er for gamle -- ingen stille evig gjenbruk.
FEED_CARRY_MAX_HOURS = 36      # = FEED_STALE_HOURS i render_templates.py
SCRAPED_CARRY_MAX_HOURS = 60   # = SCRAPED_STALE_HOURS i render_templates.py
FEED_COLLAPSE_RATIO = 0.5      # feed med < 50 % av forrige antall tilbud = kollaps
COLLAPSE_MIN_PREVIOUS = 5      # ikke vurder forhandlere med færre tilbud enn dette


def _active_scraped_names(product: dict, sources_config: dict) -> set[str]:
    names = set()
    for target in product.get("scrape_targets", []):
        retailer = target["retailer"]
        if retailer in sources_config and should_scrape(sources_config, retailer, product["brand_slug"]):
            names.add(sources_config[retailer].get("display_name", retailer))
    return names


def protect_against_dropouts(
    feed_offers: dict[str, list[Offer]],
    scraped_offers: dict[str, list[Offer]],
    products_meta: dict,
    sources_config: dict,
    scraped_this_run: bool = True,
    previous: dict | None = None,
    now: datetime | None = None,
) -> None:
    """Endrer feed_offers/scraped_offers på stedet.
    1) FEED-KOLLAPS: gir en (fortsatt konfigurert) feed under halvparten av
       forrige antall tilbud, gjenbrukes forrige runde sine tilbud fra den
       forhandleren hvis de er yngre enn FEED_CARRY_MAX_HOURS.
    2) SKRAPING (kun når vi faktisk skrapet nå): et (produkt, forhandler)-par
       som hadde et tilbud sist men ga ingenting nå, får forrige tilbud
       gjenbrukt hvis det er yngre enn SCRAPED_CARRY_MAX_HOURS.
    Alt som gjenbrukes logges tydelig med [DROPOUT-BESKYTTELSE]."""
    now = now or datetime.now(timezone.utc)
    if previous is None:
        try:
            previous = load_json(OUTPUT_PATH)
        except (OSError, ValueError):
            return
    try:
        prev_by_product = {p["id"]: p.get("offers", []) for p in previous["products"]}
    except (KeyError, TypeError):
        return

    def age_hours(o: dict) -> float:
        return (now - datetime.fromisoformat(o["checked_at"])).total_seconds() / 3600

    def has(offers_by_product: dict, pid: str, retailer: str) -> bool:
        return any(x.retailer == retailer for x in offers_by_product.get(pid, []))

    def carry(target: dict, pid: str, o: dict) -> bool:
        try:
            target.setdefault(pid, []).append(Offer(**o))
            return True
        except TypeError:
            return False

    # 1) feed-kollaps
    configured_feeds = {
        cfg.get("display_name", key)
        for key, cfg in sources_config.items()
        if not key.startswith("$") and cfg.get("default_source") == "affiliate_feed"
        and ("feed_url" in cfg or "feed_urls" in cfg or "feed_path" in cfg)
    }
    prev_n: dict[str, int] = {}
    for offs in prev_by_product.values():
        for o in offs:
            if o.get("source") == "affiliate_feed" and o["retailer"] in configured_feeds:
                prev_n[o["retailer"]] = prev_n.get(o["retailer"], 0) + 1
    new_n: dict[str, int] = {}
    for offs in feed_offers.values():
        for o in offs:
            new_n[o.retailer] = new_n.get(o.retailer, 0) + 1
    for retailer, before in prev_n.items():
        now_n = new_n.get(retailer, 0)
        if before < COLLAPSE_MIN_PREVIOUS or now_n >= before * FEED_COLLAPSE_RATIO:
            continue
        carried = too_old = 0
        for pid, offs in prev_by_product.items():
            for o in offs:
                if o.get("source") != "affiliate_feed" or o["retailer"] != retailer or has(feed_offers, pid, retailer):
                    continue
                if age_hours(o) >= FEED_CARRY_MAX_HOURS:
                    too_old += 1
                elif carry(feed_offers, pid, o):
                    carried += 1
        print(f"  [DROPOUT-BESKYTTELSE] {retailer}: feeden ga {now_n} tilbud mot {before} sist -- gjenbruker {carried} fra forrige kjøring (< {FEED_CARRY_MAX_HOURS} t), {too_old} var for gamle")

    # 2) enkelttilbud som feilet under skraping
    if not scraped_this_run:
        return
    carried_by: dict[str, int] = {}
    too_old_by: dict[str, int] = {}
    for product in products_meta["products"]:
        pid = product["id"]
        for name in _active_scraped_names(product, sources_config):
            if has(scraped_offers, pid, name):
                continue
            for o in prev_by_product.get(pid, []):
                if o.get("source") != "scraper" or o["retailer"] != name:
                    continue
                if age_hours(o) >= SCRAPED_CARRY_MAX_HOURS:
                    too_old_by[name] = too_old_by.get(name, 0) + 1
                elif carry(scraped_offers, pid, o):
                    carried_by[name] = carried_by.get(name, 0) + 1
    for name in sorted(set(carried_by) | set(too_old_by)):
        print(f"  [DROPOUT-BESKYTTELSE] {name}: {carried_by.get(name, 0)} skrapede tilbud feilet i dag -- gjenbruker forrige (< {SCRAPED_CARRY_MAX_HOURS} t), {too_old_by.get(name, 0)} var for gamle")


def patch_brand_field(offers_by_product: dict[str, list[Offer]], products_meta: dict) -> None:
    """Feed-mapperne setter brand='' siden en enkelt feed-fil kan dekke flere
    merker. Fyll inn riktig merke nå som vi vet hvilket produkt-id det er."""
    brand_by_id = {p["id"]: p["brand_slug"] for p in products_meta["products"]}
    for product_id, offers in offers_by_product.items():
        brand = brand_by_id.get(product_id, "")
        for o in offers:
            if not o.brand:
                o.brand = brand


def build_catalog(products_meta: dict, offers_by_product: dict[str, list[Offer]]) -> dict:
    known_ids = {p["id"] for p in products_meta["products"]}
    unknown = set(offers_by_product) - known_ids
    if unknown:
        print(f"  [advarsel] tilbud matchet til produkt-id-er som ikke finnes i products_meta.json: {unknown}")

    products_out = []
    for product in products_meta["products"]:
        offers = offers_by_product.get(product["id"], [])
        if not offers:
            print(f"  [ingen tilbud] {product['id']} publiseres uten priser")
        products_out.append({
            **{k: v for k, v in product.items() if k != "scrape_targets"},
            "offers": [asdict(o) for o in offers],
        })

    return {"categories": products_meta["categories"], "products": products_out}


def main() -> None:
    print("Leser konfigurasjon ...")
    products_meta = load_json(PRODUCTS_META_PATH)
    if SOLUTIONS_META_PATH.exists():
        # Linsevæske o.l. lever i en egen fil (annen datamodell -- size_ml/
        # solution_type i stedet for category_slug/specs), men går inn i
        # SAMME katalog-pipeline siden scraping/feed-matching er identisk.
        # "categories" hentes kun fra products_meta.json -- solutions_meta.json
        # trenger ikke sin egen, produktene har bare ikke category_slug.
        solutions_meta = load_json(SOLUTIONS_META_PATH)
        products_meta = {**products_meta, "products": products_meta["products"] + solutions_meta["products"]}
    product_matching = load_json(PRODUCT_MATCHING_PATH)
    sources_config = load_json(SOURCES_CONFIG_PATH)

    print("Henter feed-tilbud ...")
    feed_offers = collect_feed_offers(sources_config, product_matching)

    scraped_offers = None
    if os.environ.get("KL_SKIP_FRESH_SCRAPE") == "1":
        scraped_offers = reuse_fresh_scraped_offers(products_meta, sources_config)
    scraped_this_run = scraped_offers is None
    if scraped_this_run:
        print("Henter scrapede tilbud ...")
        scraped_offers = collect_scraped_offers(products_meta, sources_config)

    protect_against_dropouts(feed_offers, scraped_offers, products_meta, sources_config, scraped_this_run=scraped_this_run)

    combined: dict[str, list[Offer]] = {}
    for source_dict in (feed_offers, scraped_offers):
        for product_id, offers in source_dict.items():
            combined.setdefault(product_id, []).extend(offers)

    patch_brand_field(combined, products_meta)

    catalog = build_catalog(products_meta, combined)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Skrevet: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
