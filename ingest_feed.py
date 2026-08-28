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


def _resolve_product_ids(product_match: dict, sku: Optional[str]) -> list[str]:
    """product_matching.json sin verdi er normalt en enkelt product_id-streng,
    men kan også være en liste -- brukt der to produkter i katalogen (f.eks.
    "Focus Dailies" og "Dailies All Day Comfort", samme fysiske vare under to
    navn, bekreftet 2026-08-27) begge skal vise SAMME feed-tilbud. Én rad
    matcher da til flere produkt-id-er i stedet for å måtte dupliseres i
    feeden (som ikke finnes to ganger der)."""
    if not sku:
        return []
    match = product_match.get(sku)
    if match is None:
        return []
    return match if isinstance(match, list) else [match]


def map_adtraction_row(row: dict, product_match: dict[str, str], retailer_cfg: dict) -> list[Offer]:
    """Adtraction sin faktiske eksport er et Google Shopping-formatert feed
    (id/title/link/image_link/price/availability/brand osv.) -- bekreftet mot
    ekte feed fra ExtraOptical 2026-08-12, IKKE den samme kolonnestrukturen
    som ble gjettet før noen ekte avtale fantes. 'link' er allerede den
    ferdige affiliate-trackinglenken (Adtraction sin egen domain, med
    butikkens url som et parameter i den), ikke butikkens rå produkt-url --
    limes rett inn som Offer.url uten videre bearbeiding. 'price' har
    valutakode som suffiks (f.eks. "495 NOK").

    Delt mapper for ALLE Adtraction-forhandlere (ExtraOptical, Apotekhjem,
    ...) siden det er samme feed-format uansett annonsør -- retailer/frakt
    hentes fra retailer_cfg (display_name/shipping fra sources_config.json)
    i stedet for å hardkodes, siden en samle-feed for flere forhandlere
    aldri finnes her (én Adtraction-feed = én forhandler, id-navnerommet
    er IKKE delt på tvers av forhandlere -- derfor også egen
    product_matching-nøkkel per forhandler, se sources_config.json sin
    'network'-verdi for hver)."""
    sku = row.get("id")
    product_ids = _resolve_product_ids(product_match, sku)
    if not product_ids:
        return []  # ukjent produkt - hopp over i stedet for å gjette

    price_text = row.get("sale_price") or row.get("price") or ""
    price_match = re.search(r"[\d.,]+", price_text)
    if not price_match:
        return []

    try:
        price_nok = float(price_match.group().replace(",", "."))
        checked_at = datetime.now(timezone.utc).isoformat()
        shipping_policy = retailer_cfg.get("shipping")
        return [mark_staleness(Offer(
            retailer=retailer_cfg["display_name"],
            brand="",  # settes av build_catalog.py fra products_meta etter matching
            source="affiliate_feed",
            network="adtraction",
            price_nok=price_nok,
            shipping_nok=compute_shipping_nok(price_nok, shipping_policy),
            shipping_policy=shipping_policy,
            url=row["link"],
            in_stock=row.get("availability") == "in_stock",
            checked_at=checked_at,
            image_url=row.get("image_link") or None,
            image_source="affiliate_feed" if row.get("image_link") else "unlicensed",
            product_id=product_id,
        )) for product_id in product_ids]
    except (KeyError, ValueError):
        return []  # logg og hopp over feilformede rader i stedet for å publisere feil data


def map_partner_ads_row(row: dict, product_match: dict[str, str], retailer_cfg: dict) -> list[Offer]:
    """Juster feltnavn til Partner-ads sine faktiske eksport-kolonner.
    Forventer en 'produktnummer'-kolonne som finnes i product_match.
    retailer_cfg er ubrukt her -- Partner-ads er en samle-feed med egen
    'shop'-kolonne per rad, retailer-navnet kommer derfra, ikke fra config."""
    sku = row.get("produktnummer")
    product_ids = _resolve_product_ids(product_match, sku)
    if not product_ids:
        return []

    try:
        return [mark_staleness(Offer(
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
        )) for product_id in product_ids]
    except (KeyError, ValueError):
        return []


def map_tradedoubler_row(product: dict, product_match: dict[str, str]) -> list[Offer]:
    """Shopping4Net (Tradedoubler, program-id 198299, bekreftet 2026-08-20).
    ANNERLEDES enn de andre nettverkene: hvert 'produkt' er et nøstet
    JSON-objekt (offers[0] med pris/lenke/lagerstatus, categories[] med full
    kategoristi, productImage.url), ikke en flat CSV-rad -- se
    load_tradedoubler_feed() for selve HTTP/paginering-delen.

    Filtrerer ALLTID på kategoristi her ("Kontaktlinser > ..."), ikke bare i
    søket som henter feeden -- q=kontaktlinser/øyedråper i feed_url er et
    uverifisert/udokumentert søkefilter (Tradedoubler sitt API har ingen
    dokumentert kategori-parameter), så dette er et sikkerhetsnett mot at et
    løst relatert produkt (søket ga f.eks. også mascara og solkrem) noensinne
    limes inn som en linse/væske ved en feiltakelse.

    offers[0].sourceProductId brukes som SKU-nøkkel i product_matching.json
    (Tradedoubler sin egen, stabile produktkode -- mer robust enn Adtraction
    sin navnebaserte 'id'). Rader der feedens EGET navn og URL/produktkode
    motsier hverandre på pakningsstørrelse (f.eks. ReNu Multipurpose '360 ml'
    med produktkode/URL som sier '355ml'), eller der vi sporer FLERE
    pakningsstørrelser av samme produktnavn uten at feeden skiller dem
    (f.eks. bare 'Biofinity XR' uten 3-/6-pack-angivelse), er bevisst IKKE
    tatt med i product_matching -- samme prinsipp som Adtraction-feeden."""
    categories = [c.get("name", "") for c in product.get("categories", [])]
    if not any(c.startswith(("Kontaktlinser >", "Apotek > Allergi > Øyendråper", "Apotek > Øyne")) for c in categories):
        return []

    offers = product.get("offers") or []
    if not offers:
        return []
    offer = offers[0]
    sku = offer.get("sourceProductId")
    product_ids = _resolve_product_ids(product_match, sku)
    if not product_ids:
        return []

    price_history = offer.get("priceHistory") or []
    if not price_history:
        return []
    try:
        price_nok = float(price_history[0]["price"]["value"])
    except (KeyError, ValueError, TypeError):
        return []

    image_url = (product.get("productImage") or {}).get("url") or None
    checked_at = datetime.now(timezone.utc).isoformat()
    return [mark_staleness(Offer(
        retailer="Shopping4net",
        brand="",  # settes av build_catalog.py fra products_meta etter matching
        source="affiliate_feed",
        network="tradedoubler",
        price_nok=price_nok,
        # Kjøpsvilkår (shopping4net.com/no/Informasjon/Kjoepsvilkaar.htm,
        # 2026-08-20): gratis frakt over 700 kr for Kontaktlinser-avdelingen
        # spesifikt ("Kontaktlinser: kr 700" -- ulikt Skjønnhet/Helsekost sine
        # 350 kr, bekreftet av brukeren mot Shopping4net sin egen
        # "Fri Frakt"-info-modal samme dag). Selve vilkårsteksten oppga ikke
        # et fast gebyr under grensen ("styres av postnummer og størrelse"),
        # men brukeren bekreftet 39 kr direkte 2026-08-20.
        shipping_nok=compute_shipping_nok(price_nok, {"free_over": 700, "fee_nok": 39}),
        shipping_policy={"free_over": 700, "fee_nok": 39},
        url=offer.get("productUrl"),
        in_stock=offer.get("availability") == "in_stock",
        checked_at=checked_at,
        image_url=image_url,
        image_source="affiliate_feed" if image_url else "unlicensed",
        product_id=product_id,
    )) for product_id in product_ids]


NETWORK_MAPPERS = {
    "adtraction": map_adtraction_row,
    "adtraction_apotekhjem": map_adtraction_row,
    "partner-ads": map_partner_ads_row,
}


def _load_feed_rows(rows: csv.DictReader, network: str, product_match: dict[str, str], source_label: str, retailer_cfg: dict) -> list[Offer]:
    mapper = NETWORK_MAPPERS[network]
    offers = []
    skipped = 0
    for row in rows:
        row_offers = mapper(row, product_match, retailer_cfg)
        if row_offers:
            offers.extend(row_offers)
        else:
            skipped += 1
    if skipped:
        print(f"  [{network}] {skipped} rad(er) i {source_label} kunne ikke matches til et kjent produkt")
    return offers


def load_feed(path: str, network: str, product_match: dict[str, str], retailer_cfg: dict) -> list[Offer]:
    with open(path, newline="", encoding="utf-8") as f:
        return _load_feed_rows(csv.DictReader(f), network, product_match, path, retailer_cfg)


def load_feed_url(url: str, network: str, product_match: dict[str, str], retailer_cfg: dict) -> list[Offer]:
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
    return _load_feed_rows(csv.DictReader(io.StringIO(resp.text)), network, product_match, url, retailer_cfg)


def _load_tradedoubler_query(url: str, product_match: dict[str, str]) -> tuple[list[Offer], int]:
    """Henter ALLE sider for ETT søk (q=...) i Tradedoubler sin paginerte
    JSON-API. url skal IKKE inneholde et eget ;page=-segment -- det settes
    her per side, rett før ?token=... (Tradedoubler sitt matrix-parameter-
    format). Henter side for side til en side returnerer færre produkter enn
    pageSize (siste side), med et hardt tak på 20 sider (2000 produkter) som
    sikkerhetsnett mot en uendelig løkke hvis APIet oppfører seg uventet."""
    if "?" not in url:
        print(f"  [tradedoubler] uventet feed_url-format (mangler ?token=): {url}")
        return [], 0
    base, token_part = url.split("?", 1)

    offers: list[Offer] = []
    skipped = 0
    page = 1
    while page <= 20:
        page_url = f"{base};page={page}?{token_part}"
        try:
            resp = requests.get(page_url, headers={"User-Agent": "kontaktlinser.no-feedbot/1.0"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [tradedoubler] klarte ikke å hente side {page} av {url}: {e}")
            break
        products = data.get("products", [])
        for product in products:
            product_offers = map_tradedoubler_row(product, product_match)
            if product_offers:
                offers.extend(product_offers)
            else:
                skipped += 1
        if len(products) < 100:
            break
        page += 1
    return offers, skipped


def load_tradedoubler_feed(urls: list[str], product_match: dict[str, str]) -> list[Offer]:
    """Shopping4Net sin feed dekkes ikke av ETT søk -- q=kontaktlinser og
    q=øyedråper gir DELVIS overlappende, men ikke identiske, treffsett
    (Tradedoubler sitt q-filter er et uverifisert/udokumentert
    relevanssøk, ingen ekte kategori-parameter er funnet). Henter derfor
    flere søk (urls) og slår sammen -- samme produkt kan dukke opp i mer enn
    ett søk, så resultatet dedupliseres på product_id til slutt (siste
    treff vinner; prisen er uansett identisk siden det er samme rad i
    Tradedoubler sin database uansett hvilket søk som fant den)."""
    all_offers: list[Offer] = []
    total_skipped = 0
    for url in urls:
        offers, skipped = _load_tradedoubler_query(url, product_match)
        all_offers.extend(offers)
        total_skipped += skipped
    if total_skipped:
        print(f"  [tradedoubler] {total_skipped} produkt-forekomst(er) matchet ikke et kjent produkt eller falt utenfor sporet kategori")

    deduped: dict[str, Offer] = {}
    for offer in all_offers:
        deduped[offer.product_id] = offer
    return list(deduped.values())


def pick_product_image(offers: list[Offer]) -> Optional[str]:
    """Én produktside har ett bilde, ikke ett per forhandler. Velg det første
    lisensierte bildet blant tilbudene - scrapede tilbud har image_source
    'unlicensed' og blir aldri valgt her, uansett hvor fint bildet ser ut."""
    for o in offers:
        if o.image_source in LICENSED_IMAGE_SOURCES and o.image_url:
            return o.image_url
    return None


def _pick_lowest(eligible: list[Offer]) -> Offer | None:
    """Velger ÉN vinner blant tilbud på lager og ikke utdaterte, ved eksakt
    lik totalpris (2026-08-18, etter avtale med brukeren):
    1) foretrekk et tilbud vi har en affiliate-avtale med (source ==
       "affiliate_feed") fremfor et vi ikke har,
    2) blant flere med avtale, velg den med best provisjon for oss -- IKKE
       implementert ennå, kun Extra Optical har avtale i dag, så det finnes
       ingenting å sammenligne. Bygges når en to. avtale finnes.
    Prisen er identisk for kunden i alle disse tilfellene uansett -- regelen
    avgjør kun hvem som får "Lavest pris"-merket når det ikke er noen reell
    prisforskjell å vise frem. Se disclosure-teksten på produktsidene."""
    if not eligible:
        return None
    lowest_total = min(o.price_nok + o.shipping_nok for o in eligible)
    tied = [o for o in eligible if o.price_nok + o.shipping_nok == lowest_total]
    if len(tied) == 1:
        return tied[0]
    with_deal = [o for o in tied if o.source == "affiliate_feed"]
    return with_deal[0] if with_deal else tied[0]


def reconcile(product_id_to_offers: dict[str, list[Offer]]) -> dict:
    """Beregner is_lowest per produkt basert KUN på tilbud som er på lager og
    ikke utdaterte. Et utdatert eller utsolgt tilbud kan aldri "vinne" mint-
    merket, selv om tallet er lavest -- å vise mint på en pris kunden ikke
    faktisk kan få er nøyaktig den feilen denne pipelinen skal forhindre."""
    result = {}
    for product_id, offers in product_id_to_offers.items():
        eligible = [o for o in offers if o.in_stock and not o.is_stale]
        winner = _pick_lowest(eligible)
        for o in offers:
            o.is_lowest = winner is not None and o is winner
        result[product_id] = [asdict(o) for o in offers]
    return result


if __name__ == "__main__":
    # Se build_catalog.py for faktisk sammenkobling av feeds, scraping og
    # produktkatalog. Denne filen er kun normaliserings- og beregningslaget.
    pass
