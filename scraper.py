"""
scraper.py

Generisk scraper som kun kjører for forhandler/merke-par der
sources_config.json faktisk sier "scraper" som kilde. Selectorene ligger i
config, ikke i koden -- endrer en forhandler layouten sin, oppdaterer du
config, ikke Python.

To hente-moduser, valgt via price_source i scraper_config (default "css"):
  "css"           - price_selector/sale_price_selector leses av server-rendret
                     DOM med BeautifulSoup, slik det alltid har fungert her.
  "embedded_json" - for React/SPA-forhandlere som ALDRI server-rendrer prisen
                     i DOM-en (CSS-selectorer treffer da ingenting uansett hvor
                     riktige de er). embedded_json_pattern + _price_path
                     plukker prisen ut av en JSON-blob i en <script>-tag som
                     ligger i rå-HTML-en uavhengig av om JS kjøres.

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

from offer import Offer, mark_staleness

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


def _find_price_in_embedded_json(sc: dict, resp_text: str) -> float | None:
    """Enkelte forhandlere (Lenson/Lensway) er React-apper der prisen ALDRI
    finnes i server-rendret DOM -- CSS-selectorer treffer ingenting uansett
    hvor riktige de er. Prisen ligger derimot ferdig utregnet (rabatt
    inkludert) som en JSON-blob i en <script>-tag, ment for deres egen
    analytics -- den blobben er til stede uten at JS kjøres."""
    m = re.search(sc["embedded_json_pattern"], resp_text, re.S)
    if not m:
        return None
    try:
        value = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    for key in sc["embedded_json_price_path"]:
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError):
            return None
    return float(value) if isinstance(value, int | float) else None


def scrape_product(retailer: str, brand: str, slug: str, cfg: dict) -> Offer | None:
    """Henter én produktside og returnerer en Offer, eller None hvis siden
    ikke kan hentes, ikke er tillatt av robots.txt, eller mangler forventede felt."""
    sc = cfg["scraper_config"]
    base_url = sc["base_url"]
    path = sc["product_url_pattern"].format(slug=slug)

    if not robots_allows(base_url, path):
        return None  # respekter robots.txt uten unntak

    _rate_limiter.wait(base_url, min_delay=sc.get("crawl_delay_seconds"))

    try:
        resp = requests.get(
            urljoin(base_url, path),
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    if sc.get("price_source") == "embedded_json":
        price = _find_price_in_embedded_json(sc, resp.text)
    else:
        price = _find_price_in_dom(sc, soup)
    if price is None:
        return None  # ikke publiser en pris vi ikke faktisk fant

    stock_el = soup.select_one(sc["stock_selector"]) if sc.get("stock_selector") else None
    in_stock = True
    if stock_el is not None:
        in_stock = "utsolgt" not in stock_el.get_text(strip=True).lower()

    return mark_staleness(Offer(
        retailer=retailer,
        brand=brand,
        source="scraper",
        network="scrape",
        price_nok=price,
        shipping_nok=0.0,  # legg til egen selector hvis frakt vises separat
        url=urljoin(base_url, path),
        in_stock=in_stock,
        checked_at=datetime.now(timezone.utc).isoformat(),
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
