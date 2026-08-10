"""
scraper.py

Generisk scraper som kun kjører for forhandler/merke-par der
sources_config.json faktisk sier "scraper" som kilde. Selectorene ligger i
config, ikke i koden -- endrer en forhandler layouten sin, oppdaterer du
config, ikke Python.

To regler som IKKE er valgfrie:
1. Sjekk robots.txt før hver kjøring mot en gitt forhandler. Er stien disallowed,
   scraper vi ikke -- uansett hvor fristende dataene er.
2. Rate-limit per domene. Vi bygger ikke en tjeneste som legger unødig last på
   forhandlernes servere -- det er både uetisk og gjør oss lettere å blokkere.

Når et merke flyttes til affiliate_feed i sources_config.json, skal denne
scraperen automatisk hoppe over det paret -- se should_scrape().
"""

import json
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
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urljoin(base_url, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        return False  # kan ikke bekrefte tillatelse -> ikke scrape
    return rp.can_fetch(USER_AGENT, urljoin(base_url, path))


class DomainRateLimiter:
    def __init__(self, min_delay: float = MIN_DELAY_SECONDS):
        self.min_delay = min_delay
        self._last_request: dict[str, float] = {}

    def wait(self, domain: str) -> None:
        last = self._last_request.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)
        self._last_request[domain] = time.monotonic()


_rate_limiter = DomainRateLimiter()


def scrape_product(retailer: str, brand: str, slug: str, cfg: dict) -> Offer | None:
    """Henter én produktside og returnerer en Offer, eller None hvis siden
    ikke kan hentes, ikke er tillatt av robots.txt, eller mangler forventede felt."""
    sc = cfg["scraper_config"]
    base_url = sc["base_url"]
    path = sc["product_url_pattern"].format(slug=slug)

    if not robots_allows(base_url, path):
        return None  # respekter robots.txt uten unntak

    _rate_limiter.wait(base_url)

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

    price_el = soup.select_one(sc["price_selector"])
    stock_el = soup.select_one(sc["stock_selector"])
    if price_el is None:
        return None  # ikke publiser en pris vi ikke faktisk fant

    price_text = price_el.get_text(strip=True).replace("kr", "").replace(",", ".").strip()
    try:
        price = float("".join(c for c in price_text if c.isdigit() or c == "."))
    except ValueError:
        return None

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
