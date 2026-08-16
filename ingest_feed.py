"""
ingest_feed.py

Leser inn affiliate-feeds (Adtraction, Partner-ads, Awin, ...) og normaliserer
dem til det delte Offer-skjemaet i offer.py.

En feed-fil fra én forhandler inneholder normalt MANGE produkter for et
merke, ikke bare ett. Derfor matches hver rad mot et internt produkt-id via
en SKU/produktnummer-oppslagstabell (product_matching.json, lastet av
build_catalog.py og gitt inn som `product_match`). En rad hvis SKU ikke
finnes i oppslagstabellen blir ALDRI limt til et produkt basert på gjetning
(f.eks. "det er det eneste Acuvue-produktet i feeden") - den hoppes over.

reconcile() beregner deretter is_lowest per produkt-id fra tilbud som
faktisk er på lager og ikke utdaterte -- det er DEN ENESTE tingen som skal
utløse mint-fargen ("lavest pris") på siden. Sett aldri is_lowest manuelt.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional
import csv
import io
import json
import re

import requests

from offer import Offer, mark_staleness, compute_shipping_nok

LICENSED_IMAGE_SOURCES = {"affiliate_feed", "manufacturer_kit"}


def map_adtraction_row(row: dict, product_match: dict[str, str]) -> Optional[Offer]:
    """Adtraction sin faktiske eksport er et Google Shopping-formatert feed
    (id/title/link/image_link/price/availability/brand osv.) -- bekreftet mot
    ekte feed fra ExtraOptical 2026-08-12, IKKE den samme kolonnestrukturen
    som ble gjettet før noen ekte avtale fantes. 'link' er allerede den
    ferdige affiliate-trackinglenken (Adtraction sin egen domain, med
    butikkens url som et parameter i den), ikke butikkens rå produkt-url --
    limes rett inn som Offer.url uten videre bearbeiding. 'price' har
    valutakode som suffiks (f.eks. "495 NOK").

    Denne feeden er per i dag ENESTE Adtraction-forhandler
    (ExtraOptical) og har ingen egen merchant-navn-kolonne (feeden er
    forhandler-spesifikk, ikke en samle-feed for flere butikker) -- retailer
    er derfor hardkodet her. Legges en ANNEN Adtraction-forhandler til senere,
    må dette parameteriseres."""
    sku = row.get("id")
    product_id = product_match.get(sku) if sku else None
    if product_id is None:
        return None  # ukjent produkt - hopp over i stedet for å gjette

    price_text = row.get("sale_price") or row.get("price") or ""
    price_match = re.search(r"[\d.,]+", price_text)
    if not price_match:
        return None

    try:
        price_nok = float(price_match.group().replace(",", "."))
        return mark_staleness(Offer(
            retailer="Extra Optical",
            brand="",  # settes av build_catalog.py fra products_meta etter matching
            source="affiliate_feed",
            network="adtraction",
            price_nok=price_nok,
            # Feeden har ikke fraktdata (shipping-kolonnen er alltid tom, bekreftet
            # 2026-08-12). VIKTIG: Extra Optical har ULIK fraktpolicy for briller
            # (frakt-og-levering-siden sier 49 kr/gratis over 600 kr) og kontaktlinser
            # (bekreftet direkte på en faktisk linse-produktside 2026-08-16: "Frakt 45,-
            # eller fri frakt over 900,-") -- brukte feilaktig briller-tallet først,
            # rettet til de linse-spesifikke tallene under. Regnes ut her siden feeden
            # selv ikke leverer fraktdata.
            shipping_nok=compute_shipping_nok(price_nok, {"free_over": 900, "fee_nok": 45}),
            url=row["link"],
            in_stock=row.get("availability") == "in_stock",
            checked_at=datetime.now(timezone.utc).isoformat(),
            image_url=row.get("image_link") or None,
            image_source="affiliate_feed" if row.get("image_link") else "unlicensed",
            product_id=product_id,
        ))
    except (KeyError, ValueError):
        return None  # logg og hopp over feilformede rader i stedet for å publisere feil data


def map_partner_ads_row(row: dict, product_match: dict[str, str]) -> Optional[Offer]:
    """Juster feltnavn til Partner-ads sine faktiske eksport-kolonner.
    Forventer en 'produktnummer'-kolonne som finnes i product_match."""
    sku = row.get("produktnummer")
    product_id = product_match.get(sku) if sku else None
    if product_id is None:
        return None

    try:
        return mark_staleness(Offer(
            retailer=row["shop"],
            brand="",
            source="affiliate_feed",
            network="partner-ads",
            price_nok=float(row["pris"]),
            shipping_nok=float(row.get("frakt", 0) or 0),
            url=row["link"],
            in_stock=row.get("lager", "yes") == "yes",
            checked_at=row["oppdatert"],
            image_url=row.get("bilde_url") or None,
            image_source="affiliate_feed" if row.get("bilde_url") else "unlicensed",
            product_id=product_id,
        ))
    except (KeyError, ValueError):
        return None


NETWORK_MAPPERS = {
    "adtraction": map_adtraction_row,
    "partner-ads": map_partner_ads_row,
}


def _load_feed_rows(rows: csv.DictReader, network: str, product_match: dict[str, str], source_label: str) -> list[Offer]:
    mapper = NETWORK_MAPPERS[network]
    offers = []
    skipped = 0
    for row in rows:
        offer = mapper(row, product_match)
        if offer:
            offers.append(offer)
        else:
            skipped += 1
    if skipped:
        print(f"  [{network}] {skipped} rad(er) i {source_label} kunne ikke matches til et kjent produkt")
    return offers


def load_feed(path: str, network: str, product_match: dict[str, str]) -> list[Offer]:
    with open(path, newline="", encoding="utf-8") as f:
        return _load_feed_rows(csv.DictReader(f), network, product_match, path)


def load_feed_url(url: str, network: str, product_match: dict[str, str]) -> list[Offer]:
    """Henter en feed direkte over HTTP i stedet for fra en lokal fil --
    brukes for ekte affiliate-feeds som skal hentes ferske ved hver bygging
    (live pris/lager-data), ikke en fil noen har lastet ned og kan glemme å
    oppdatere. Feiler hentingen, publiseres ingen tilbud fra denne feeden
    denne runden -- IKKE gjenbruk gårsdagens data stille."""
    try:
        resp = requests.get(url, headers={"User-Agent": "kontaktlinser.no-feedbot/1.0"}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [{network}] klarte ikke å hente feed fra URL: {e}")
        return []
    return _load_feed_rows(csv.DictReader(io.StringIO(resp.text)), network, product_match, url)


def pick_product_image(offers: list[Offer]) -> Optional[str]:
    """Én produktside har ett bilde, ikke ett per forhandler. Velg det første
    lisensierte bildet blant tilbudene - scrapede tilbud har image_source
    'unlicensed' og blir aldri valgt her, uansett hvor fint bildet ser ut."""
    for o in offers:
        if o.image_source in LICENSED_IMAGE_SOURCES and o.image_url:
            return o.image_url
    return None


def reconcile(product_id_to_offers: dict[str, list[Offer]]) -> dict:
    """Beregner is_lowest per produkt basert KUN på tilbud som er på lager og
    ikke utdaterte. Et utdatert eller utsolgt tilbud kan aldri "vinne" mint-
    merket, selv om tallet er lavest -- å vise mint på en pris kunden ikke
    faktisk kan få er nøyaktig den feilen denne pipelinen skal forhindre."""
    result = {}
    for product_id, offers in product_id_to_offers.items():
        eligible = [o for o in offers if o.in_stock and not o.is_stale]
        if eligible:
            lowest_total = min(o.price_nok + o.shipping_nok for o in eligible)
            for o in offers:
                o.is_lowest = (
                    o in eligible and (o.price_nok + o.shipping_nok) == lowest_total
                )
        result[product_id] = [asdict(o) for o in offers]
    return result


if __name__ == "__main__":
    # Se build_catalog.py for faktisk sammenkobling av feeds, scraping og
    # produktkatalog. Denne filen er kun normaliserings- og beregningslaget.
    pass
