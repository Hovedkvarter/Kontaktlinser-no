"""
scraper.py

Generisk scraper som kun kjører for forhandler/merke-par der
sources_config.json faktisk sier "scraper" som kilde. Selectorene ligger i
config, ikke i koden -- endrer en forhandler layouten sin, oppdaterer du
config, ikke Python.

To hente-moduser, valgt via price_source i scraper_config (default "css"):
  "css"                - price_selector/sale_price_selector leses av
                          server-rendret DOM med BeautifulSoup, slik det
                          alltid har fungert her.
  "embedded_json"      - for React/SPA-forhandlere som ALDRI server-rendrer
                          prisen i DOM-en (CSS-selectorer treffer da
                          ingenting uansett hvor riktige de er).
                          embedded_json_pattern + _price_path plukker prisen
                          ut av en JSON-blob i en <script>-tag som ligger i
                          rå-HTML-en uavhengig av om JS kjøres.
  "shopify_variant_json" - for Shopify-forhandlere (Lensit) der
                          pakningsstørrelse er et variant-valg PÅ SAMME URL,
                          ikke en egen produktside. price_selector ville her
                          bare hentet prisen til whatever variant Shopify
                          rendrer som forhåndsvalgt -- for et produkt som
                          finnes i både 3- og 6-pakning kunne det HENDE å
                          treffe feil pakningsstørrelse, uten noen feilmelding
                          (funnet 2026-08-12: Air Optix HydraGlyde for
                          Astigmatism viste 3-pack-pris på 6-pack-produktet).
                          Krever et "variant"-felt per scrape_target som sier
                          nøyaktig hvilken pakningsstørrelse (Shopify sin
                          "public_title"/"title") som skal hentes -- finnes
                          ingen variant med akkurat den tittelen, hentes
                          INGEN pris, det gjettes aldri på nærmeste treff.
  "listing_page"       - for forhandlere (Coptikk) der selve produktsiden
                          ALDRI server-rendrer pris (kun via et JSON-API-kall
                          etter sidelast -- bekreftet ustabilt/500-feil ved
                          isolerte kall utenfor en ordinær nettleser-økt,
                          2026-08-16, IKKE brukt her av den grunn), MEN
                          kategori-LISTE-sidene ("alle månedslinser" osv.) ER
                          fullt server-rendret med schema.org Product/Offer-
                          mikrodata (pris + lagerstatus + URL) for hvert
                          produkt i listen. slug er her produktets EGEN
                          fulle URL-sti (f.eks.
                          "linsebutikk/manedslinser/biofinity-energys-6-linser"
                          -- IKKE et artikkelnummer). Scraperen henter i
                          stedet listesiden (siste stinivå strippet av slug)
                          og plukker ut riktig produkt sin pris/lagerstatus
                          ved å matche på slug sin fulle sti mot
                          itemprop="url" i mikrodataen -- se
                          _find_offer_in_listing_page().

To regler som IKKE er valgfrie:
1. Sjekk robots.txt før hver kjøring mot en gitt forhandler. Er stien disallowed,
   scraper vi ikke -- uansett hvor fristende dataene er.
2. Rate-limit per domene. Vi bygger ikke en tjeneste som legger unødig last på
   forhandlernes servere -- det er både uetisk og gjør oss lettere å blokkere.

Når et merke flyttes til affiliate_feed i sources_config.json, skal denne
scraperen automatisk hoppe over det paret -- se should_scrape().
"""

import json
import re
import time
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from offer import Offer, mark_staleness, compute_shipping_nok

MIN_DELAY_SECONDS = 3.0  # minimum tid mellom requests til samme domene
USER_AGENT = "kontaktlinser.no-prisbot/1.0 (+https://kontaktlinser.no/om-prisboten)"


def load_config(path: str = "sources_config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def should_scrape(config: dict, retailer: str, brand: str) -> bool:
    """Returnerer False hvis merket er flyttet til affiliate_feed eller manual.
    Dette er sikkerhetsnettet som gjør at en godkjent avtale faktisk stopper
    scraping av det merket, uten at noen må huske å slå av noe manuelt."""
    r = config.get(retailer, {})
    override = r.get("brand_overrides", {}).get(brand)
    source = override["source"] if override else r.get("default_source")
    return source == "scraper"


def robots_allows(base_url: str, path: str) -> bool:
    """Henter robots.txt selv, med en faktisk timeout - RobotFileParser.read()
    har INGEN timeout innebygd og kan henge for alltid hvis en side svarer
    trått eller ikke i det hele tatt. Det er nøyaktig den typen feil som skal
    gjøre en jobb rask og trygg å avbryte, ikke la den sitte fast timer i strekk."""
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        resp = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=8)
    except requests.RequestException:
        return False  # kan ikke bekrefte tillatelse -> ikke scrape

    if resp.status_code >= 400:
        return False  # ingen robots.txt eller feil -> ikke scrape uten bekreftet tillatelse

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(USER_AGENT, urljoin(base_url, path))


class DomainRateLimiter:
    def __init__(self, min_delay: float = MIN_DELAY_SECONDS):
        self.min_delay = min_delay
        self._last_request: dict[str, float] = {}

    def wait(self, domain: str, min_delay: float | None = None) -> None:
        """min_delay overstyrer standarden -- enkelte forhandlere (f.eks.
        ExtraOptical) krever lengre crawl-delay enn 3 sek i robots.txt."""
        delay = min_delay if min_delay is not None else self.min_delay
        last = self._last_request.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request[domain] = time.monotonic()


_rate_limiter = DomainRateLimiter()


def _find_price_in_dom(sc: dict, soup: BeautifulSoup) -> float | None:
    """Tilbudspris (sale_price_selector) vinner over ordinærpris når begge
    finnes -- flere forhandlere viser strøket originalpris + kampanjepris
    side om side i samme markup."""
    price_el = None
    if sc.get("sale_price_selector"):
        price_el = soup.select_one(sc["sale_price_selector"])
    if price_el is None:
        price_el = soup.select_one(sc["price_selector"])
    if price_el is None:
        return None
    price_text = price_el.get_text(strip=True).replace("kr", "").replace(",", ".").strip()
    try:
        return float("".join(c for c in price_text if c.isdigit() or c == "."))
    except ValueError:
        return None


_SHOPIFY_VARIANT_JSON_RE = re.compile(
    r'<script[^>]*id="ProductJson-product-template"[^>]*>(.*?)</script>', re.S
)


def _find_price_in_shopify_variants(resp_text: str, expected_variant: str | None) -> float | None:
    """Plukker prisen til den ene Shopify-varianten (pakningsstørrelsen) vi
    faktisk vil ha, fra variant-JSON-en Shopify alltid legger i rå-HTML-en
    (samme data driver variant-velgeren på siden). expected_variant matches
    mot variantens public_title/title (f.eks. "6", "30", "90") -- finnes ikke
    en variant med akkurat den tittelen, returneres None. Vi gjetter ALDRI
    nærmeste variant, selv om det bare finnes én -- se docstring i scraper.py
    for hvorfor (default-variant-bugen fra 2026-08-12)."""
    if not expected_variant:
        return None
    m = _SHOPIFY_VARIANT_JSON_RE.search(resp_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    for variant in data.get("variants", []):
        title = str(variant.get("public_title") or variant.get("title") or "").strip()
        if title == expected_variant:
            price = variant.get("price")
            return float(price) / 100 if isinstance(price, int | float) else None
    return None  # ingen variant matchet forventet pakningsstørrelse


def _resolve_json_path(value, path: list[str]):
    """Navigerer value[path[0]][path[1]]... -- returnerer None hvis en nøkkel
    mangler underveis, i stedet for å kaste. Delt av pris- og lagerstatus-
    oppslag i embedded_json-modus, som begge leser fra samme JSON-blob."""
    for key in path:
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError):
            return None
    return value


def _parse_embedded_json(sc: dict, resp_text: str):
    """Plukker ut og parser JSON-blobben embedded_json_pattern peker på.
    Returnerer None ved treff-/parse-feil, ellers det parsede objektet."""
    m = re.search(sc["embedded_json_pattern"], resp_text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _find_price_in_embedded_json(sc: dict, resp_text: str) -> float | None:
    """Enkelte forhandlere (Lenson/Lensway) er React-apper der prisen ALDRI
    finnes i server-rendret DOM -- CSS-selectorer treffer ingenting uansett
    hvor riktige de er. Prisen ligger derimot ferdig utregnet (rabatt
    inkludert) som en JSON-blob i en <script>-tag, ment for deres egen
    analytics -- den blobben er til stede uten at JS kjøres.
    Samme mekanisme kan i prinsippet også dekke forhandlere der prisen ligger i et
    eget JSON-API-endepunkt i stedet for i en <script>-tag på produktsiden --
    da er embedded_json_pattern satt til "(.*)" (fanger hele respons-teksten
    som gruppe 1, siden hele responsen ALLEREDE er ren JSON)."""
    value = _parse_embedded_json(sc, resp_text)
    if value is None:
        return None
    value = _resolve_json_path(value, sc["embedded_json_price_path"])
    return float(value) if isinstance(value, int | float) else None


def _find_stock_in_embedded_json(sc: dict, resp_text: str) -> bool:
    """Leser lagerstatus fra samme JSON-blob som prisen, når forhandleren
    faktisk oppgir et eget felt for det (embedded_json_stock_path er da
    satt i sources_config.json). Default True (antatt på lager) hvis feltet
    ikke er konfigurert -- matcher de andre embedded_json-forhandlerne, der
    ingen pålitelig lagerstatus-indikator ble funnet ved verifisering."""
    path = sc.get("embedded_json_stock_path")
    if not path:
        return True
    value = _parse_embedded_json(sc, resp_text)
    if value is None:
        return True
    value = _resolve_json_path(value, path)
    return value if isinstance(value, bool) else True


def _find_offer_in_listing_page(soup: BeautifulSoup, product_path: str) -> tuple[float, bool] | None:
    """Coptikk (og trolig andre Litium-baserte sider) rendrer ALDRI pris på
    selve produktsiden -- kun via et JSON-API-kall etter sidelast, som viste
    seg ustabilt (500-feil) ved isolerte kall utenfor en ordinær nettleser-
    økt. Kategori-LISTE-sidene er derimot fullt server-rendret med
    schema.org Product/Offer-mikrodata for hvert produkt i listen -- så vi
    henter listesiden i stedet, og finner riktig produkt ved å matche
    product_path mot det produktkortet sin egen itemprop="url"-lenke, i
    stedet for å anta en bestemt rekkefølge eller posisjon i listen."""
    for wrapper in soup.select('[itemtype="http://schema.org/Product"]'):
        url_el = wrapper.select_one('[itemprop="url"]')
        if url_el is None:
            continue
        href = (url_el.get("href") or "").rstrip("/")
        if href != product_path.rstrip("/"):
            continue
        price_el = wrapper.select_one(".price")
        if price_el is None:
            return None
        price_text = price_el.get_text(strip=True).replace(".", "").replace(",", ".")
        try:
            price = float("".join(c for c in price_text if c.isdigit() or c == "."))
        except ValueError:
            return None
        avail_el = wrapper.select_one('[itemprop="availability"]')
        in_stock = "instock" in (avail_el.get("href") or "").lower() if avail_el else True
        return price, in_stock
    return None  # produktet finnes ikke i denne listen -- gjett aldri


def scrape_product(
    retailer: str, brand: str, slug: str, cfg: dict,
    expected_variant: str | None = None,
) -> Offer | None:
    """Henter én produktside og returnerer en Offer, eller None hvis siden
    ikke kan hentes, ikke er tillatt av robots.txt, eller mangler forventede felt.
    expected_variant brukes kun når price_source er "shopify_variant_json" --
    se scraper.py sin docstring.
    Når price_source er "listing_page" er slug produktets EGEN fulle URL-sti
    (ikke noe som formateres inn i product_url_pattern) -- vi henter i
    stedet kategori-listesiden ett stinivå opp og matcher riktig produkt der."""
    sc = cfg["scraper_config"]
    base_url = sc["base_url"]
    price_source = sc.get("price_source")

    if price_source == "listing_page":
        path = "/" + slug.rsplit("/", 1)[0].lstrip("/")
    else:
        path = sc["product_url_pattern"].format(slug=slug)

    if not robots_allows(base_url, path):
        print(f"    [debug] {retailer}/{slug}: robots.txt tillater ikke {path} (eller kunne ikke hentes)")
        return None  # respekter robots.txt uten unntak

    _rate_limiter.wait(base_url, min_delay=sc.get("crawl_delay_seconds"))

    try:
        resp = requests.get(
            urljoin(base_url, path),
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"    [debug] {retailer}/{slug}: hente-feil ({status or e.__class__.__name__})")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    in_stock = True
    if price_source == "shopify_variant_json":
        price = _find_price_in_shopify_variants(resp.text, expected_variant)
    elif price_source == "embedded_json":
        price = _find_price_in_embedded_json(sc, resp.text)
    elif price_source == "listing_page":
        result = _find_offer_in_listing_page(soup, "/" + slug.lstrip("/"))
        if result is None:
            print(f"    [debug] {retailer}/{slug}: status={resp.status_code} len={len(resp.text)} -- produkt ikke funnet i listen")
            return None  # produktet ble ikke funnet i listen -- gjett aldri
        price, in_stock = result
    else:
        price = _find_price_in_dom(sc, soup)
        if price is None:
            print(f"    [debug] {retailer}/{slug}: status={resp.status_code} len={len(resp.text)} price_selector={sc.get('price_selector')!r} -- ingen treff")
    if price is None:
        return None  # ikke publiser en pris vi ikke faktisk fant

    stock_el = soup.select_one(sc["stock_selector"]) if sc.get("stock_selector") else None
    if stock_el is not None:
        in_stock = "utsolgt" not in stock_el.get_text(strip=True).lower()
    elif price_source == "embedded_json":
        in_stock = _find_stock_in_embedded_json(sc, resp.text)

    display_path = ("/" + slug.lstrip("/")) if price_source == "listing_page" else path

    return mark_staleness(Offer(
        retailer=cfg.get("display_name", retailer),
        brand=brand,
        source="scraper",
        network="scrape",
        price_nok=price,
        shipping_nok=compute_shipping_nok(price, sc.get("shipping")),
        url=urljoin(base_url, display_path),
        in_stock=in_stock,
        checked_at=datetime.now(timezone.utc).isoformat(),
        shipping_policy=sc.get("shipping"),
    ))


def scrape_all(products: list[dict], config_path: str = "sources_config.json") -> list[Offer]:
    """products: liste av {"retailer", "brand", "slug"} -- kun paene der
    should_scrape() er True blir faktisk hentet."""
    cfg = load_config(config_path)
    offers = []
    for p in products:
        retailer_cfg = cfg.get(p["retailer"])
        if not retailer_cfg or not should_scrape(cfg, p["retailer"], p["brand"]):
            continue
        offer = scrape_product(p["retailer"], p["brand"], p["slug"], retailer_cfg)
        if offer:
            offers.append(offer)
    return offers
