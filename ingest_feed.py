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
from typing import Optional
import csv
import json

from offer import Offer, mark_staleness

LICENSED_IMAGE_SOURCES = {"affiliate_feed", "manufacturer_kit"}


def map_adtraction_row(row: dict, product_match: dict[str, str]) -> Optional[Offer]:
    """Juster feltnavn til Adtraction sine faktiske eksport-kolonner.
    Forventer en 'sku'-kolonne som finnes i product_match."""
    sku = row.get("sku")
    product_id = product_match.get(sku) if sku else None
    if product_id is None:
        return None  # ukjent produkt - hopp over i stedet for å gjette

    try:
        return mark_staleness(Offer(
            retailer=row["merchant_name"],
            brand="",  # settes av build_catalog.py fra products_meta etter matching
            source="affiliate_feed",
            network="adtraction",
            price_nok=float(row["price"]),
            shipping_nok=float(row.get("shipping_cost", 0) or 0),
            url=row["tracking_url"],
            in_stock=row.get("in_stock", "1") == "1",
            checked_at=row["last_updated"],
            image_url=row.get("image_url") or None,
            image_source="affiliate_feed" if row.get("image_url") else "unlicensed",
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


def load_feed(path: str, network: str, product_match: dict[str, str]) -> list[Offer]:
    mapper = NETWORK_MAPPERS[network]
    offers = []
    skipped = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            offer = mapper(row, product_match)
            if offer:
                offers.append(offer)
            else:
                skipped += 1
    if skipped:
        print(f"  [{network}] {skipped} rad(er) i {path} kunne ikke matches til et kjent produkt")
    return offers


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
