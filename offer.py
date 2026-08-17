"""
offer.py

Ett delt Offer-format. Uansett om en pris kommer fra en affiliate-feed eller
en scraper, blir den gjort om til en av disse før den når reconcile() eller
sidegeneratoren. Ingen av de to trenger å vite eller bry seg om hvilken kilde
prisen kom fra -- det er hele poenget med å skille kilde-konfigurasjon fra
selve pipelinen.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

STALE_THRESHOLD_HOURS = 24


@dataclass
class Offer:
    retailer: str
    brand: str
    source: str            # "affiliate_feed" | "scraper" | "manual"
    network: str           # "adtraction" | "partner-ads" | "scrape" | "manual"
    price_nok: float
    shipping_nok: float
    url: str                # affiliate-lenke, eller direkte produkt-URL hvis scrapet
    in_stock: bool
    checked_at: str          # ISO 8601
    is_stale: bool = False
    is_lowest: bool = False
    image_url: str | None = None
    # Hvor bildet lovlig kommer fra. Vises IKKE på siden, men brukes til å
    # avgjøre om et bilde faktisk kan rendres:
    #   "affiliate_feed"      - bilde-URL levert av nettverket, trygt å bruke
    #   "manufacturer_kit"    - lastet ned fra produsentens presse-/media-kit
    #   "unlicensed"          - ingen bekreftet rettighet -> vis placeholder, ikke bildet
    image_source: str = "unlicensed"
    # Hvilket produkt i katalogen dette tilbudet faktisk gjelder. Settes av
    # build_catalog.py via SKU-matching (feed) eller direkte (scraper). Et
    # tilbud uten bekreftet product_id skal ALDRI limes til et produkt basert
    # på gjetning (f.eks. "det er det eneste Acuvue-produktet i feeden").
    product_id: str | None = None
    # Rå fraktpolicy ({"free_over": <NOK eller None>, "fee_nok": <NOK>}), IKKE
    # bare det ferdigberegnede shipping_nok-tallet for én pakning. Trengs for
    # å kunne regne ut riktig frakt ved et vilkårlig antall pakninger (f.eks.
    # antall-kalkulatoren på produktsiden) -- shipping_nok alene forteller
    # ikke om en forhandler har en fri-frakt-grense eller ikke. None betyr
    # ukjent policy, samme "vis ingenting vi ikke vet"-prinsipp som ellers.
    shipping_policy: dict | None = None


def mark_staleness(offer: Offer) -> Offer:
    checked = datetime.fromisoformat(offer.checked_at)
    age = datetime.now(timezone.utc) - checked.astimezone(timezone.utc)
    offer.is_stale = age > timedelta(hours=STALE_THRESHOLD_HOURS)
    return offer


def compute_shipping_nok(price_nok: float, shipping_cfg: dict | None) -> float:
    """Regner ut fraktkostnad ut fra forhandlerens egen, verifiserte
    fri-frakt-grense og gebyr (shipping_cfg = {"free_over": <NOK eller None>,
    "fee_nok": <NOK>} i sources_config.json). free_over=None betyr at
    forhandleren aldri tilbyr gratis frakt på enkeltbestillinger (f.eks.
    Synsam, 39 kr uansett beløp) -- IKKE det samme som fee_nok=0. Mangler
    shipping_cfg helt (forhandlerens fraktpolicy ikke undersøkt/bekreftet
    ennå), returneres 0.0 som en trygg, eksplisitt "ukjent"-standard --
    ALDRI gjett et gebyr uten kilde."""
    if not shipping_cfg:
        return 0.0
    free_over = shipping_cfg.get("free_over")
    if free_over is not None and price_nok >= free_over:
        return 0.0
    return shipping_cfg.get("fee_nok", 0.0)


LICENSED_IMAGE_SOURCES = {"affiliate_feed", "manufacturer_kit"}


def renderable_image_url(offer: Offer) -> str | None:
    """Returner bilde-URL kun hvis opphavet er kjent og lisensiert.
    Sidegeneratoren skal ALDRI falle tilbake på en scrapet bilde-URL her --
    bruk denne funksjonen i stedet for å lese offer.image_url direkte."""
    if offer.image_source in LICENSED_IMAGE_SOURCES and offer.image_url:
        return offer.image_url
    return None
