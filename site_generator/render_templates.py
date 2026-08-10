"""
render_templates.py

Rendrer produkt- og kategorisider som ferdig, statisk HTML - tilbudslisten,
prisene og "sist oppdatert"-tidspunktene ligger direkte i markupen som
returneres, IKKE bygget av JavaScript etter innlasting.

Grunnen: mange AI-crawlere (og noen eldre indekserere) kjører ikke
JavaScript. Er ikke prisen der i rå-HTML, finnes den ikke for dem. JS her
brukes kun til forbedringer ovenpå innhold som allerede er synlig uten den
(filter/sortering på kategorisiden) - se <noscript>-fallback i category-malen.

Bruker samme CSS-tokens som prototypene: ink/mist/aqua/mint, Space Grotesk /
Inter / IBM Plex Mono. Endres designsystemet, endres SHARED_STYLE - ett sted.
"""

from datetime import datetime, timezone
from html import escape

BASE_URL = "https://kontaktlinser.no"

SHARED_STYLE = """
:root {
  --ink: #0B2545; --mist: #F5F9FA; --aqua: #2EC4D6; --aqua-tint: #E4F7FA;
  --mint: #0BA36F; --mint-tint: #E4F6EE; --muted: #7C8A9E; --muted-bg: #ECEFF3;
  --border: #DCE4EA; --card-shadow: 0 1px 2px rgba(11, 37, 69, 0.06);
}
* { box-sizing: border-box; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
body { margin: 0; background: var(--mist); color: var(--ink); font-family: 'Inter', sans-serif; line-height: 1.5; }
a { color: inherit; }
.wrap { max-width: 760px; margin: 0 auto; padding: 0 20px 64px; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 20px; max-width: 760px; margin: 0 auto; flex-wrap: wrap; }
.topbar-logo { display: flex; align-items: center; gap: 8px; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.05rem; text-decoration: none; color: var(--ink); }
.topbar .ring-mark { width: 22px; height: 22px; flex-shrink: 0; }
.topbar-nav { display: flex; gap: 18px; flex-wrap: wrap; }
.topbar-nav a { font-size: 0.86rem; font-weight: 600; text-decoration: none; color: var(--ink); }
.topbar-nav a:hover { color: var(--aqua); }
.breadcrumb { font-size: 0.8rem; color: var(--muted); margin: 4px 0 20px; }
.breadcrumb a { text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.hero { position: relative; padding: 8px 0 22px; }
.hero-copy { position: relative; z-index: 1; max-width: 520px; }
.hero-copy .kicker { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
.hero-copy h1 { font-family: 'Space Grotesk', sans-serif; font-size: 1.9rem; line-height: 1.15; margin: 4px 0 8px; }
.hero-copy p { margin: 0; color: var(--muted); font-size: 0.92rem; }
.best-price-band { position: relative; background: var(--mint-tint); border: 1px solid #BFE7D5; border-radius: 14px; padding: 18px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
.best-price-band .label { font-size: 0.78rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.05em; }
.best-price-band .retailer { font-size: 0.95rem; color: var(--ink); margin-top: 2px; display: flex; align-items: center; gap: 6px; }
.best-price-band .price { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.6rem; color: var(--mint); white-space: nowrap; }
.offer-card, .product-card { display: flex; align-items: center; justify-content: space-between; gap: 14px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 10px; box-shadow: var(--card-shadow); text-decoration: none; color: var(--ink); }
.offer-card.is-lowest { border-color: var(--mint); background: var(--mint-tint); }
.offer-card.is-muted { opacity: 0.55; }
.product-card:hover, .offer-card a.cta:hover { border-color: var(--aqua); }
.offer-main, .product-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.offer-retailer, .product-name { font-weight: 600; font-size: 0.95rem; display: flex; align-items: center; gap: 6px; }
.lowest-tag { font-size: 0.68rem; font-weight: 600; color: white; background: var(--mint); padding: 2px 7px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.03em; }
.offer-meta, .product-meta, .retailer-count { font-size: 0.78rem; color: var(--muted); margin-top: 2px; }
.retailer-logo { height: 18px; width: auto; max-width: 92px; object-fit: contain; vertical-align: middle; }
.retailer-logo-chip { display: inline-flex; align-items: center; background: var(--ink); border-radius: 4px; padding: 3px 6px; }
.best-price-band .retailer-logo { height: 22px; max-width: 110px; }
.brand-card-badge.has-logo, .brand-card-badge.has-logo-dark { width: 52px; border-radius: 8px; padding: 4px; }
.brand-card-badge.has-logo { background: white; }
.brand-card-badge.has-logo-dark { background: var(--ink); }
.brand-logo-img { width: 100%; height: 100%; object-fit: contain; }
.brand-hero-row { display: flex; align-items: center; gap: 16px; }
.brand-hero-logo { flex-shrink: 0; width: 64px; height: 64px; border-radius: 50%; background: var(--aqua-tint); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.brand-hero-logo.has-logo, .brand-hero-logo.has-logo-dark { width: 128px; border-radius: 14px; padding: 10px; }
.brand-hero-logo.has-logo { background: white; }
.brand-hero-logo.has-logo-dark { background: var(--ink); }
.offer-price-col, .product-price-col { text-align: right; flex-shrink: 0; }
.offer-total, .price-value { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.05rem; }
.offer-breakdown { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: var(--muted); }
.price-label { font-size: 0.68rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.03em; }
.cta { display: inline-block; margin-top: 6px; font-size: 0.78rem; font-weight: 600; text-decoration: none; border: 1px solid var(--aqua); color: var(--aqua); padding: 5px 12px; border-radius: 20px; }
.offer-card.is-lowest .cta { background: var(--mint); border-color: var(--mint); color: white; }
.product-thumb { width: 52px; height: 52px; border-radius: 50%; background: var(--aqua-tint); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.9rem; color: var(--aqua); flex-shrink: 0; overflow: hidden; }
.product-thumb img { width: 100%; height: 100%; object-fit: cover; }
.chip { font-size: 0.82rem; font-weight: 600; padding: 7px 14px; border-radius: 20px; border: 1px solid var(--border); background: white; cursor: pointer; color: var(--ink); }
.chip.active { background: var(--ink); border-color: var(--ink); color: white; }
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 20px 0 24px; }
.list-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
.list-header h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0; }
.related, .guides { margin-top: 32px; }
.related h2, .guides h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1rem; margin: 0 0 10px; }
.related ul, .guides ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.related a, .guides a { display: block; font-size: 0.88rem; text-decoration: none; padding: 10px 14px; background: white; border: 1px solid var(--border); border-radius: 10px; }
.related a:hover, .guides a:hover { border-color: var(--aqua); }
.disclosure { font-size: 0.78rem; color: var(--muted); line-height: 1.6; border-top: 1px solid var(--border); padding-top: 18px; margin-top: 22px; }
@media (min-width: 560px) { .hero-copy h1 { font-size: 2.2rem; } }
.site-footer { margin-top: 48px; background: var(--ink); color: white; }
.footer-inner { max-width: 760px; margin: 0 auto; padding: 40px 20px 8px; display: flex; flex-wrap: wrap; gap: 32px 24px; }
.footer-col { flex: 1 1 140px; min-width: 140px; }
.footer-col h3 { font-family: 'Space Grotesk', sans-serif; font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--aqua); margin: 0 0 12px; }
.footer-col a { display: block; font-size: 0.85rem; color: rgba(255,255,255,0.78); text-decoration: none; padding: 3px 0; }
.footer-col a:hover { color: white; text-decoration: underline; }
.footer-brand-list { columns: 2; column-gap: 16px; }
.footer-disclosure { max-width: 760px; margin: 8px auto 0; padding: 20px 20px 0; font-size: 0.75rem; line-height: 1.6; color: rgba(255,255,255,0.55); border-top: 1px solid rgba(255,255,255,0.14); }
.footer-bottom { max-width: 760px; margin: 0 auto; padding: 14px 20px 28px; display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; font-size: 0.76rem; color: rgba(255,255,255,0.5); }
.footer-bottom a { color: rgba(255,255,255,0.5); text-decoration: none; }
.footer-bottom a:hover { color: white; }
"""

RING_MARK = """<svg class="ring-mark" viewBox="0 0 40 40" aria-hidden="true">
  <circle cx="20" cy="20" r="18" fill="none" stroke="#0B2545" stroke-width="2.2"/>
  <circle cx="20" cy="20" r="11" fill="none" stroke="#2EC4D6" stroke-width="2.2"/>
  <circle cx="20" cy="20" r="4" fill="#0B2545"/>
</svg>"""

FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">"""

GTM_HEAD = """<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','GTM-KGPF68');</script>
<!-- End Google Tag Manager -->"""

GTM_BODY = """<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-KGPF68"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->"""

TOPBAR_HTML = f"""<div class="topbar">
  <a href="/" class="topbar-logo">{RING_MARK} kontaktlinser.no</a>
  <nav class="topbar-nav">
    <a href="/#merker">Merker</a>
    <a href="/#kategorier">Kategorier</a>
    <a href="/guider/">Guider</a>
  </nav>
</div>"""

# Kuratert, ikke generert fra catalog.json -- oppdater manuelt hvis
# kategori- eller merkeutvalget endres vesentlig (samme praksis som TOPBAR_HTML).
FOOTER_CATEGORIES = [
    ("manedslinser", "Månedslinser"),
    ("dagslinser", "Dagslinser"),
    ("toriske-linser", "Toriske linser"),
    ("fargede-linser", "Fargede linser"),
    ("multifokale-linser", "Multifokale linser"),
]

FOOTER_BRANDS = [
    ("acuvue", "Acuvue"),
    ("adore", "ADORE"),
    ("air-optix", "Air Optix"),
    ("avaira", "Avaira"),
    ("biofinity", "Biofinity"),
    ("biomedics", "Biomedics"),
    ("biotrue", "Biotrue"),
    ("clariti", "Clariti"),
    ("dailies", "Dailies"),
    ("freshlook", "FreshLook"),
    ("myday", "MyDay"),
    ("precision1", "Precision1"),
    ("precision7", "Precision7"),
    ("proclear", "Proclear"),
    ("purevision", "PureVision"),
    ("soflens", "SofLens"),
    ("total30", "TOTAL30"),
    ("ultra", "ULTRA"),
]


def render_footer() -> str:
    year = datetime.now(timezone.utc).year
    category_links = "\n    ".join(
        f'<a href="/kontaktlinser/{slug}/">{escape(label)}</a>' for slug, label in FOOTER_CATEGORIES
    )
    brand_links = "\n      ".join(
        f'<a href="/merke/{slug}/">{escape(label)}</a>' for slug, label in FOOTER_BRANDS
    )
    return f"""<footer class="site-footer">
  <div class="footer-inner">
    <div class="footer-col">
      <h3>Kategorier</h3>
    {category_links}
    </div>
    <div class="footer-col">
      <h3>Merker</h3>
      <div class="footer-brand-list">
      {brand_links}
      </div>
    </div>
    <div class="footer-col">
      <h3>Guider</h3>
      <a href="/guider/">Alle guider</a>
      <a href="/guide/manedslinser-vs-dagslinser/">Månedslinser vs. dagslinser</a>
      <a href="/guide/hvordan-velge-kontaktlinser/">Hvordan velge kontaktlinser</a>
    </div>
  </div>
  <p class="footer-disclosure">
    kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser
    automatisk fra forhandlernes egne nettsider hver 6. time og sorterer alltid
    etter lavest totalpris inkl. frakt. Vi kan motta provisjon når du handler via
    lenkene våre &ndash; det påvirker verken prisen du betaler eller rangeringen
    av tilbud. Vi selger ikke kontaktlinser selv. Kontaktlinser er reseptvare:
    rådfør deg alltid med optiker ved valg av linsetype og styrke.
  </p>
  <div class="footer-bottom">
    <span>&copy; {year} kontaktlinser.no</span>
    <a href="/">Forside</a>
    <a href="/guider/">Guider</a>
  </div>
</footer>"""


LICENSED_IMAGE_SOURCES = {"affiliate_feed", "manufacturer_kit"}

# Nøytral bruk for å identifisere hvor tilbudet faktisk kommer fra (samme
# praksis som enhver prissammenligningstjeneste) - ikke ment å antyde
# partnerskap/godkjenning fra forhandleren. Hentet direkte fra hver
# forhandlers egen nettside (static/logos/), fjernes umiddelbart ved
# forespørsel. dark_bg=True betyr logoen er hvit/lys og trenger en mørk
# bakgrunnslapp for å være synlig på våre lyse kort.
RETAILER_LOGOS = {
    "Interoptik": ("interoptik.png", False),
    "Lensway": ("lensway.svg", False),
    "Lenson": ("lenson.svg", False),
    "Extra Optical": ("extraoptical.svg", False),
    "Shopping4net": ("shopping4net.png", True),
    "Lensit": ("lensit.svg", False),
    "Specsavers": ("specsavers.svg", False),
    "Synsam": ("synsam.svg", False),
    "Brilleland": ("brilleland.svg", False),
}


# Nøytral, beskrivende bruk for å identifisere hvilket produkt/merke det
# faktisk er snakk om - selve definisjonen av nominativ varemerkebruk.
# Noen merker (Biofinity, Air Optix, Dailies, Precision1/7, Total30,
# FreshLook, Avaira, Biomedics, Clariti, MyDay, Proclear, Biotrue,
# PureVision, SofLens, Ultra) har ingen egen rendyrket ordmerke-logofil på
# produsentens offisielle side (kun produktbilder av emballasjen) - der
# brukes produsentens hovedlogo (CooperVision/Alcon/Bausch + Lomb) i
# stedet, etter eksplisitt avklaring med brukeren 2026-08-10.
BRAND_LOGOS = {
    "acuvue": ("acuvue.svg", False),
    "adore": ("adore.png", False),
    "air-optix": ("alcon.svg", True),
    "avaira": ("coopervision.png", False),
    "biofinity": ("coopervision.png", False),
    "biomedics": ("coopervision.png", False),
    "biotrue": ("bauschlomb.svg", True),
    "clariti": ("coopervision.png", False),
    "dailies": ("alcon.svg", True),
    "freshlook": ("alcon.svg", True),
    "myday": ("coopervision.png", False),
    "precision1": ("alcon.svg", True),
    "precision7": ("alcon.svg", True),
    "proclear": ("coopervision.png", False),
    "purevision": ("bauschlomb.svg", True),
    "soflens": ("bauschlomb.svg", True),
    "total30": ("alcon.svg", True),
    "ultra": ("bauschlomb.svg", True),
}


def _brand_badge(brand_slug: str, brand_label: str) -> tuple[str, str]:
    """Returnerer (ekstra CSS-klasse for badge-sirkelen, innhold i den) -
    logo når vi har en, ellers samme initial-fallback som før."""
    entry = BRAND_LOGOS.get(brand_slug)
    if not entry:
        return "", escape(brand_label[:2].upper())
    filename, dark_bg = entry
    img = f'<img class="brand-logo-img" src="/static/logos/{filename}" alt="" loading="lazy">'
    return ("has-logo has-logo-dark" if dark_bg else "has-logo"), img


def _retailer_badge_html(retailer: str) -> str:
    """Logo istedenfor navnetekst når vi har en - men navnet ligger fortsatt i
    rå-HTML (visuelt skjult), siden både skjermlesere og enkle AI-tekst-
    uttrekkere skal kunne se hvilken forhandler det er uten å tolke <img alt>."""
    entry = RETAILER_LOGOS.get(retailer)
    if not entry:
        return escape(retailer)
    filename, dark_bg = entry
    img = f'<img class="retailer-logo" src="/static/logos/{filename}" alt="{escape(retailer)}" loading="lazy">'
    logo = f'<span class="retailer-logo-chip">{img}</span>' if dark_bg else img
    hidden_name = f'<span style="position:absolute;left:-9999px;">{escape(retailer)}</span>'
    return logo + hidden_name


def _fmt_kr(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ") + " kr"


def _time_ago(checked_at: str, now: datetime) -> str:
    checked = datetime.fromisoformat(checked_at)
    hrs = round((now - checked).total_seconds() / 3600)
    if hrs < 1:
        return "akkurat nå"
    if hrs == 1:
        return "1 time siden"
    if hrs < 24:
        return f"{hrs} timer siden"
    return f"{round(hrs / 24)} dager siden"


def reconcile_product(offers: list[dict], now: datetime, stale_hours: int = 24) -> list[dict]:
    """Samme logikk som reconcile() i ingest_feed.py, men på rå dict-data
    slik generatoren kan kjøre den direkte på catalog.json uten omveier."""
    enriched = []
    for o in offers:
        checked = datetime.fromisoformat(o["checked_at"])
        age_hours = (now - checked).total_seconds() / 3600
        is_stale = age_hours > stale_hours
        total = o["price_nok"] + o["shipping_nok"]
        enriched.append({**o, "total": total, "is_stale": is_stale})

    eligible = [o for o in enriched if o["in_stock"] and not o["is_stale"]]
    lowest_total = min((o["total"] for o in eligible), default=None)

    for o in enriched:
        o["is_lowest"] = lowest_total is not None and o in eligible and o["total"] == lowest_total

    return sorted(enriched, key=lambda o: o["total"])


def pick_product_image(offers: list[dict]) -> str | None:
    for o in offers:
        if o.get("image_source") in LICENSED_IMAGE_SOURCES and o.get("image_url"):
            return o["image_url"]
    return None


def render_offer_card(o: dict, retailer: str) -> str:
    status_note = (
        '<div class="offer-meta" style="font-weight:600;">Utsolgt</div>' if not o["in_stock"]
        else '<div class="offer-meta" style="font-weight:600;">Pris ikke bekreftet siste 24t</div>' if o["is_stale"]
        else f'<div class="offer-meta">Sist oppdatert: {escape(_time_ago(o["checked_at"], datetime.now(timezone.utc)))}</div>'
    )
    css_class = "offer-card" + (" is-lowest" if o["is_lowest"] else "") + (" is-muted" if (o["is_stale"] or not o["in_stock"]) else "")
    lowest_tag = '<span class="lowest-tag">Lavest pris</span>' if o["is_lowest"] else ""
    shipping_text = f'+ {_fmt_kr(o["shipping_nok"])} frakt' if o["shipping_nok"] > 0 else "Fri frakt"
    rel = "sponsored nofollow" if o["source"] == "affiliate_feed" else "nofollow"

    return f"""<div class="{css_class}">
  <div class="offer-main">
    <div class="offer-retailer">{_retailer_badge_html(retailer)} {lowest_tag}</div>
    {status_note}
  </div>
  <div class="offer-price-col">
    <div class="offer-total">{_fmt_kr(o["total"])}</div>
    <div class="offer-breakdown">{escape(shipping_text)}</div>
    <a class="cta" href="{escape(o["url"])}" rel="{rel}">Se hos {escape(retailer)}</a>
  </div>
</div>"""


def render_product_page(product: dict, categories: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    image_url = pick_product_image(product["offers"])

    thumb = f'<img src="{escape(image_url)}" alt="{escape(product["name"])}" loading="lazy">' if image_url \
        else escape(product["brand_label"][:2].upper())

    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"]) for o in offers)

    best_band = ""
    if best:
        best_band = f"""<div class="best-price-band">
  <div class="label-group">
    <div class="label">Laveste pris</div>
    <div class="retailer">{_retailer_badge_html(best["retailer"])}</div>
  </div>
  <div class="price">{_fmt_kr(best["total"])}</div>
</div>"""

    in_stock_offers = [o for o in offers if o["in_stock"]]
    schema_offers = ",\n      ".join(f'''{{
        "@type": "Offer",
        "seller": {{"@type": "Organization", "name": "{escape(o["retailer"])}"}},
        "price": {o["total"]},
        "priceCurrency": "NOK",
        "url": "{escape(o["url"])}",
        "availability": "https://schema.org/InStock"
      }}''' for o in in_stock_offers)

    low_price = min((o["total"] for o in in_stock_offers), default=0)
    high_price = max((o["total"] for o in in_stock_offers), default=0)

    specs = product.get("specs", [])
    schema_props = ""
    if specs:
        schema_props = ',\n  "additionalProperty": [' + ",\n    ".join(
            f'{{"@type": "PropertyValue", "name": "{escape(label)}", "value": "{escape(value)}"}}'
            for label, value in specs
        ) + "]"

    long_description = product.get("long_description", product["description"])

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}},
  "offers": {{
    "@type": "AggregateOffer",
    "priceCurrency": "NOK",
    "lowPrice": {low_price},
    "highPrice": {high_price},
    "offerCount": {len(in_stock_offers)},
    "offers": [{schema_offers}]
  }}{schema_props}
}}"""

    specs_html = ""
    if specs:
        rows = "\n".join(
            f'<div class="spec-row"><span class="spec-label">{escape(label)}</span><span class="spec-value">{escape(value)}</span></div>'
            for label, value in specs
        )
        specs_html = f"""<div class="specs">
    <h2>Spesifikasjoner</h2>
    <div class="specs-table">{rows}</div>
    <p class="specs-note">Veiledende tall, satt sammen fra forhandlernes egne spesifikasjoner og produsentens produktinformasjon. Bekreft alltid mot din synsresept og pakningsvedlegget før kjøp.</p>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} – billigste pris | kontaktlinser.no</title>
<meta name="description" content="{escape(long_description[:155])}">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.specs {{ margin-top: 32px; }}
.specs h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 12px; }}
.specs-table {{ background: white; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
.spec-row {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 16px; font-size: 0.88rem; border-bottom: 1px solid var(--border); }}
.spec-row:last-child {{ border-bottom: none; }}
.spec-label {{ color: var(--muted); }}
.spec-value {{ font-family: 'IBM Plex Mono', monospace; text-align: right; }}
.specs-note {{ font-size: 0.76rem; color: var(--muted); margin-top: 10px; line-height: 1.5; }}
</style>
</head>
<body>
{GTM_BODY}
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb">
    <a href="/">Hjem</a> ›
    <a href="/kontaktlinser/{escape(product["category_slug"])}/">{escape(categories[product["category_slug"]]["label"])}</a> ›
    <a href="/merke/{escape(product["brand_slug"])}/">{escape(product["brand_label"])}</a> ›
    {escape(product["name"])}
  </p>
  <div class="hero">
    <div class="product-thumb" style="width:84px;height:84px;font-size:1.4rem;">{thumb}</div>
    <div class="hero-copy">
      <div class="kicker">{escape(product["brand_label"])}</div>
      <h1>{escape(product["name"])}</h1>
      <p>{escape(long_description)}</p>
    </div>
  </div>
  {best_band}
  <div class="offers">
    <h2>Alle tilbud, sortert etter total pris</h2>
    {offer_cards_html}
  </div>
  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker ikke prisen du
    betaler eller rekkefølgen på tilbudene. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
  </p>
  {specs_html}
</div>
{render_footer()}
</body>
</html>"""


def render_brand_page(brand_slug: str, brand_label: str, products: list[dict], categories: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"] and not o["is_stale"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        image_url = pick_product_image(p["offers"])
        rows.append({"product": p, "lowest": lowest, "image_url": image_url})

    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        thumb = f'<img src="{escape(r["image_url"])}" alt="{escape(p["name"])}" loading="lazy">' if r["image_url"] \
            else escape(p["brand_label"][:2].upper())
        price_block = (
            f'<div class="price-label">Fra</div><div class="price-value" style="color:var(--mint);">{_fmt_kr(lowest["total"])}</div>'
            f'<div class="retailer-count">{len(p["offers"])} forhandlere</div>'
            if lowest else '<div class="retailer-count">Ingen tilbud tilgjengelig</div>'
        )
        href = f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/'
        category_label = categories[p["category_slug"]]["label"]
        return f"""<a class="product-card" href="{escape(href)}" data-category="{escape(p["category_slug"])}">
  <div class="product-thumb">{thumb}</div>
  <div class="product-main">
    <div class="product-name">{escape(p["name"])}</div>
    <div class="product-meta">{escape(category_label)}</div>
  </div>
  <div class="product-price-col">{price_block}</div>
</a>"""

    product_rows_html = "\n".join(render_row(r) for r in rows)

    brand_logo_cls, brand_logo_content = _brand_badge(brand_slug, brand_label)
    brand_logo_block = f'<div class="brand-hero-logo {brand_logo_cls}">{brand_logo_content}</div>' if brand_logo_cls else ""

    category_slugs = sorted({p["category_slug"] for p in products})
    category_chips = "".join(
        f'<button class="chip" data-category="{escape(c)}">{escape(categories[c]["label"])}</button>' for c in category_slugs
    )

    schema_items = ",\n      ".join(
        f'''{{"@type": "ListItem", "position": {i+1}, "url": "{BASE_URL}/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/", "name": "{escape(p["name"])}"}}'''
        for i, p in enumerate(products)
    )
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "BreadcrumbList", "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
      {{"@type": "ListItem", "position": 2, "name": "{escape(brand_label)}", "item": "{BASE_URL}/merke/{brand_slug}/"}}
    ]}},
    {{"@type": "ItemList", "itemListElement": [{schema_items}]}}
  ]
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(brand_label)} kontaktlinser – sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="Sammenlign priser på alle {escape(brand_label)}-kontaktlinser vi følger, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{GTM_BODY}
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(brand_label)}</p>
  <div class="hero">
    <div class="brand-hero-row">
      {brand_logo_block}
      <div class="hero-copy">
        <div class="kicker">Merke</div>
        <h1>{escape(brand_label)}</h1>
        <p>Alle {escape(brand_label)}-linser vi følger prisen på, sortert etter lavest pris.</p>
      </div>
    </div>
  </div>

  <div class="filter-row" id="filter-row" role="group" aria-label="Filtrer etter kategori">
    <button class="chip active" data-category="all">Alle kategorier</button>
    {category_chips}
  </div>

  <div class="list-header">
    <h2 id="result-count">{len(products)} produkter</h2>
  </div>

  <div id="product-list">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>

  <p class="disclosure">
    Vi sorterer alltid etter lavest pris. Vi kan få provisjon når du handler
    via lenkene på produktsidene, men det påvirker ikke prisen du betaler
    eller rangeringen av produkter eller tilbud.
  </p>
</div>

<script>
  const filterRow = document.getElementById('filter-row');
  const list = document.getElementById('product-list');

  filterRow.addEventListener('click', e => {{
    const btn = e.target.closest('.chip');
    if (!btn) return;
    filterRow.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    const category = btn.dataset.category;
    let visible = 0;
    list.querySelectorAll('.product-card').forEach(card => {{
      const show = category === 'all' || card.dataset.category === category;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
  }});
</script>
{render_footer()}
</body>
</html>"""


def render_home_page(catalog: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    def render_lens_card(p: dict) -> str:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"] and not o["is_stale"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        image_url = pick_product_image(p["offers"])
        thumb = f'<img src="{escape(image_url)}" alt="{escape(p["name"])}" loading="lazy">' if image_url \
            else escape(p["brand_label"][:2].upper())
        price_block = (
            f'<div class="price-label">Fra</div><div class="price-value" style="color:var(--mint);">{_fmt_kr(lowest["total"])}</div>'
            if lowest else '<div class="retailer-count">Ingen tilbud tilgjengelig</div>'
        )
        href = f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/'
        search_key = f'{p["name"]} {p["brand_label"]}'.lower()
        return f"""<a class="product-card" href="{escape(href)}" data-search="{escape(search_key)}">
  <div class="product-thumb">{thumb}</div>
  <div class="product-main">
    <div class="product-name">{escape(p["name"])}</div>
    <div class="product-meta">{escape(p["brand_label"])}</div>
  </div>
  <div class="product-price-col">{price_block}</div>
</a>"""

    lens_cards_html = "\n".join(render_lens_card(p) for p in catalog["products"])

    def render_category_card(slug: str, category: dict) -> str:
        count = sum(1 for p in catalog["products"] if p["category_slug"] == slug)
        n_label = "produkt" if count == 1 else "produkter"
        return f"""<a class="category-card" href="/kontaktlinser/{escape(slug)}/">
  <div class="category-card-label">{escape(category["label"])}</div>
  <div class="category-card-count">{count} {n_label}</div>
</a>"""

    category_cards_html = "\n".join(
        render_category_card(slug, category) for slug, category in catalog["categories"].items()
    )

    brand_counts: dict[str, int] = {}
    brand_labels: dict[str, str] = {}
    for p in catalog["products"]:
        brand_counts[p["brand_slug"]] = brand_counts.get(p["brand_slug"], 0) + 1
        brand_labels[p["brand_slug"]] = p["brand_label"]
    brand_order = sorted(brand_counts, key=lambda b: (-brand_counts[b], brand_labels[b]))

    def render_brand_card(slug: str) -> str:
        label = brand_labels[slug]
        count = brand_counts[slug]
        n_label = "produkt" if count == 1 else "produkter"
        extra_cls, badge_content = _brand_badge(slug, label)
        badge_class = ("brand-card-badge " + extra_cls).strip()
        return f"""<a class="brand-card" href="/merke/{escape(slug)}/">
  <div class="{badge_class}">{badge_content}</div>
  <div class="brand-card-info">
    <div class="brand-card-name">{escape(label)}</div>
    <div class="brand-card-count">{count} {n_label}</div>
  </div>
</a>"""

    brand_cards_html = "\n".join(render_brand_card(slug) for slug in brand_order)

    category_icons = {
        "dagslinser": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke-linecap="round"/>',
        "manedslinser": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
        "toriske-linser": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.6"/>',
        "fargede-linser": '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16" fill="currentColor" stroke="none" opacity="0.35"/>',
        "multifokale-linser": '<circle cx="9" cy="9" r="5"/><circle cx="15" cy="15" r="5"/>',
    }

    def render_category_card(slug: str, category: dict) -> str:
        count = sum(1 for p in catalog["products"] if p["category_slug"] == slug)
        n_label = "produkt" if count == 1 else "produkter"
        icon = category_icons.get(slug, "")
        return f"""<a class="category-card" href="/kontaktlinser/{escape(slug)}/">
  <svg class="category-card-icon" viewBox="0 0 24 24" fill="none" stroke="var(--aqua)" stroke-width="1.6" aria-hidden="true">{icon}</svg>
  <div class="category-card-label">{escape(category["label"])}</div>
  <div class="category-card-count">{count} {n_label}</div>
</a>"""

    category_cards_html = "\n".join(
        render_category_card(slug, category) for slug, category in catalog["categories"].items()
    )

    guide_cards_html = "\n".join(
        f"""<a class="guide-mini-card" href="/guide/{escape(slug)}/">
  <div class="guide-card-title">{escape(g["title"])}</div>
  <div class="guide-card-desc">{escape(g["description"])}</div>
</a>"""
        for slug, g in GUIDE_CONTENT.items()
    )

    n_retailers = len({o["retailer"] for p in catalog["products"] for o in p["offers"]})
    n_products = len(catalog["products"])

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>kontaktlinser.no – sammenlign priser på kontaktlinser</title>
<meta name="description" content="Sammenlign priser på kontaktlinser fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
{FONT_LINKS}
<style>{SHARED_STYLE}
.hero {{ display: flex; flex-direction: column; gap: 20px; padding: 8px 0 24px; }}
.hero-copy {{ max-width: 560px; }}
.hero-media {{ border-radius: 18px; overflow: hidden; aspect-ratio: 16 / 9; box-shadow: var(--card-shadow); }}
.hero-media img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.hero-photo-credit {{ font-size: 0.66rem; color: var(--muted); margin: -14px 0 4px; text-align: right; }}
.hero-actions {{ margin-top: 16px; }}
.btn-primary {{ display: inline-block; background: var(--ink); color: white; font-weight: 600; font-size: 0.88rem; text-decoration: none; padding: 11px 20px; border-radius: 24px; }}
.btn-primary:hover {{ background: var(--aqua); }}
.trust-strip {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px; margin: 40px 0 0; box-shadow: var(--card-shadow); }}
.trust-item {{ font-size: 0.78rem; color: var(--muted); }}
.trust-item strong {{ display: block; font-family: 'Space Grotesk', sans-serif; font-size: 1.15rem; color: var(--ink); }}
.search-section {{ margin: 28px 0 36px; }}
.search-section h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 10px; }}
.search-row {{ position: relative; }}
.search-input {{ width: 100%; font-family: 'Inter', sans-serif; font-size: 1.05rem; padding: 16px 20px; border: 1px solid var(--border); border-radius: 14px; background: white; box-shadow: var(--card-shadow); }}
.search-input:focus {{ outline: none; border-color: var(--aqua); }}
.search-suggestions {{ display: none; position: absolute; top: calc(100% + 6px); left: 0; right: 0; background: white; border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 12px 28px rgba(11, 37, 69, 0.14); max-height: 380px; overflow-y: auto; z-index: 20; }}
.search-suggestion {{ display: flex; align-items: center; gap: 10px; padding: 10px 14px; text-decoration: none; color: var(--ink); border-bottom: 1px solid var(--border); }}
.search-suggestion:last-child {{ border-bottom: none; }}
.search-suggestion:hover {{ background: var(--mist); }}
.search-suggestion .product-thumb {{ width: 36px; height: 36px; font-size: 0.68rem; }}
.search-suggestion-name {{ font-weight: 600; font-size: 0.86rem; }}
.search-suggestion-meta {{ font-size: 0.74rem; color: var(--muted); }}
.search-no-match {{ padding: 14px; font-size: 0.84rem; color: var(--muted); }}
.section-header {{ display: flex; align-items: baseline; justify-content: space-between; margin: 32px 0 12px; scroll-margin-top: 20px; }}
.section-header:first-of-type {{ margin-top: 0; }}
.section-header h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0; }}
.category-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
.category-card {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px; box-shadow: var(--card-shadow); border-left: 3px solid var(--aqua); }}
.category-card:hover {{ border-color: var(--aqua); }}
.category-card-icon {{ width: 20px; height: 20px; margin-bottom: 8px; }}
.category-card-label {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.98rem; }}
.category-card-count {{ font-size: 0.78rem; color: var(--muted); margin-top: 3px; }}
.brand-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
.brand-card {{ display: flex; align-items: center; gap: 10px; min-width: 0; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; box-shadow: var(--card-shadow); }}
.brand-card:hover {{ border-color: var(--aqua); }}
.brand-card-badge {{ flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%; background: var(--aqua-tint); color: var(--aqua); display: flex; align-items: center; justify-content: center; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.8rem; }}
.brand-card-info {{ min-width: 0; }}
.brand-card-name {{ font-weight: 600; font-size: 0.88rem; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.brand-card-count {{ font-size: 0.74rem; color: var(--muted); }}
.lens-grid {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
.lens-grid .product-card {{ margin-bottom: 0; }}
.no-results {{ display: none; font-size: 0.85rem; color: var(--muted); padding: 8px 2px; }}
.guide-mini-grid {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
.guide-mini-card {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; box-shadow: var(--card-shadow); }}
.guide-mini-card:hover {{ border-color: var(--aqua); }}
@media (min-width: 560px) {{ .brand-grid {{ grid-template-columns: repeat(3, 1fr); }} .trust-strip {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (min-width: 640px) {{ .lens-grid {{ grid-template-columns: 1fr 1fr; }} .category-grid {{ grid-template-columns: repeat(3, 1fr); }} .guide-mini-grid {{ grid-template-columns: 1fr 1fr; }} }}
@media (min-width: 700px) {{ .hero {{ flex-direction: row; align-items: center; gap: 32px; }} .hero-copy {{ flex: 1; }} .hero-media {{ flex: 0 0 42%; aspect-ratio: 4 / 3; }} }}
</style>
</head>
<body>
{GTM_BODY}
{TOPBAR_HTML}
<div class="wrap">
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Prissammenligning</div>
      <h1>Finn billigste kontaktlinser</h1>
      <p>Vi sammenligner priser fra norske nettbutikker, oppdatert fortløpende. Søk eller velg en linse under for å se alle tilbud.</p>
      <div class="hero-actions">
        <a href="#merker" class="btn-primary">Se alle merker</a>
      </div>
    </div>
    <div class="hero-media">
      <img src="/static/hero-eye.jpg" alt="" loading="eager">
    </div>
  </div>
  <p class="hero-photo-credit">Foto: Amanda Dalbjörn / Unsplash</p>

  <div class="search-section">
    <h2>Søk etter linse eller merke</h2>
    <div class="search-row">
      <label for="lens-search" class="visually-hidden" style="position:absolute;left:-9999px;">Søk etter linse eller merke</label>
      <input type="search" id="lens-search" class="search-input" placeholder="F.eks. «Biofinity» eller «Dailies»" autocomplete="off">
      <div class="search-suggestions" id="search-suggestions"></div>
    </div>
  </div>

  <div class="section-header" id="merker">
    <h2>Merker</h2>
  </div>
  <div class="brand-grid">
    {brand_cards_html}
  </div>

  <div class="section-header" id="kategorier">
    <h2>Kategorier</h2>
  </div>
  <div class="category-grid">
    {category_cards_html}
  </div>

  <div class="section-header">
    <h2 id="lens-grid-heading">Alle linser</h2>
  </div>
  <div id="lens-grid" class="lens-grid">
    {lens_cards_html}
  </div>
  <p class="no-results" id="no-results">Ingen linser matcher søket ditt. Prøv et annet merke, eller se en kategori over.</p>

  <div class="section-header">
    <h2>Guider</h2>
  </div>
  <div class="guide-mini-grid">
    {guide_cards_html}
  </div>

  <div class="trust-strip">
    <div class="trust-item"><strong>{n_retailers}</strong>forhandlere sammenlignet</div>
    <div class="trust-item"><strong>{n_products}</strong>linser fulgt</div>
    <div class="trust-item"><strong>6t</strong>mellom hver prisoppdatering</div>
    <div class="trust-item"><strong>0 kr</strong>i skjulte gebyrer hos oss</div>
  </div>
</div>

<script>
  // Progressiv forbedring: alle linsekort finnes allerede i DOM-en over og
  // fungerer som vanlige lenker uten JS. Dette skjuler/viser dem basert på
  // søketekst -- bygger dem aldri fra scratch. Hurtiglinkene i dropdownen
  // under søkefeltet er samme kort gjenbrukt (klonet fra DOM-en), ikke en
  // egen datakilde.
  const searchInput = document.getElementById('lens-search');
  const grid = document.getElementById('lens-grid');
  const cards = Array.from(grid.querySelectorAll('.product-card'));
  const noResults = document.getElementById('no-results');
  const suggestions = document.getElementById('search-suggestions');

  function renderSuggestions(q) {{
    if (!q) {{
      suggestions.style.display = 'none';
      suggestions.innerHTML = '';
      return;
    }}
    const matches = cards.filter(card => card.dataset.search.includes(q)).slice(0, 8);
    if (matches.length === 0) {{
      suggestions.innerHTML = '<div class="search-no-match">Ingen treff. Prøv et annet merke eller produktnavn.</div>';
      suggestions.style.display = 'block';
      return;
    }}
    suggestions.innerHTML = matches.map(card => {{
      const thumbHtml = card.querySelector('.product-thumb').outerHTML;
      const name = card.querySelector('.product-name').textContent;
      const meta = card.querySelector('.product-meta').textContent;
      return `<a class="search-suggestion" href="${{card.getAttribute('href')}}">${{thumbHtml}}` +
        `<div><div class="search-suggestion-name">${{name}}</div>` +
        `<div class="search-suggestion-meta">${{meta}}</div></div></a>`;
    }}).join('');
    suggestions.style.display = 'block';
  }}

  searchInput.addEventListener('input', () => {{
    const q = searchInput.value.trim().toLowerCase();
    renderSuggestions(q);
    let visible = 0;
    cards.forEach(card => {{
      const show = q === '' || card.dataset.search.includes(q);
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    noResults.style.display = visible === 0 ? 'block' : 'none';
  }});

  searchInput.addEventListener('focus', () => {{
    if (searchInput.value.trim()) renderSuggestions(searchInput.value.trim().toLowerCase());
  }});

  document.addEventListener('click', e => {{
    if (!e.target.closest('.search-row')) suggestions.style.display = 'none';
  }});
</script>
{render_footer()}
</body>
</html>"""


GUIDE_CONTENT = {
    "manedslinser-vs-dagslinser": {
        "title": "Månedslinser vs. dagslinser – hva passer deg?",
        "description": "Fordeler og ulemper ved månedslinser og dagslinser, og hvordan brukshyppighet avgjør hva som lønner seg.",
        "body_html": """
<p>Det korte svaret: bruker du linser <strong>sjeldnere enn 4–5 dager i uken</strong>, kommer
dagslinser oftest billigst ut totalt sett, selv om prisen per linse er høyere. Bruker du
linser <strong>daglig</strong>, er månedslinser normalt rimeligst per bruksdag.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Dagslinser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Nytt, rent par hver dag – ingen rengjøring eller oppbevaringsvæske</li>
  <li>Praktisk til sport, reise eller sjelden bruk</li>
  <li>Lavere risiko for øyeinfeksjon siden linsen aldri gjenbrukes</li>
  <li>Høyere kostnad per linse, og mer emballasjeavfall ved daglig bruk</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Månedslinser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Samme par brukes i opptil 30 dager (følg optikerens anbefaling)</li>
  <li>Lavere kostnad per bruksdag ved daglig bruk</li>
  <li>Krever daglig rengjøring og riktig oppbevaringsvæske</li>
  <li>Mange moderne månedslinser (silikonhydrogel) slipper gjennom mer oksygen enn eldre
  materialer, noe som kan gi bedre komfort ved lange dager med linser</li>
</ul>

<p style="margin-top:24px;">Uansett type: følg alltid byttefrekvensen optikeren har satt for
akkurat din linse og resept – det er ikke bare et prisspørsmål, men avgjørende for
øyehelsen.</p>
""",
    },
    "hvordan-velge-kontaktlinser": {
        "title": "Hvordan velge kontaktlinser",
        "description": "En kort guide til hva som avgjør riktig kontaktlinsetype: resept, brukshyppighet, synsfeil og øynenes behov.",
        "body_html": """
<p>Kontaktlinser er reseptvare, også de uten styrke (f.eks. fargede linser). Første steg er
alltid en synsundersøkelse hos optiker, som fastsetter styrke, krumning og linsetype
øynene dine tåler godt.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Det resepten din vanligvis avgjør</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li><strong>Astigmatisme</strong> (skjev hornhinne) → toriske linser, formet for å ligge
  stabilt i en bestemt retning</li>
  <li><strong>Alderssyn</strong> (vansker med å se på nært hold fra ca. 40–45 år) →
  multifokale/progressive linser</li>
  <li><strong>Sfærisk syn</strong> uten astigmatisme eller alderssyn → vanlige sfæriske
  linser, det enkleste og billigste utvalget</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Andre ting som spiller inn</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Hvor ofte du bruker linser, se vår <a href="/guide/manedslinser-vs-dagslinser/">sammenligning
  av månedslinser og dagslinser</a></li>
  <li>Tørre øyne kan gjøre enkelte materialer (silikonhydrogel) mer behagelige enn andre</li>
  <li>Fargede linser krever samme oppfølging som andre linser, selv uten styrke</li>
</ul>

<p style="margin-top:24px;">Vi sammenligner priser på tvers av nettbutikker, men kan
aldri erstatte en synsundersøkelse – bruk alltid en resept som er gyldig for den
spesifikke linsen du bestiller.</p>
""",
    },
}


def render_guide_page(slug: str) -> str | None:
    guide = GUIDE_CONTENT.get(slug)
    if guide is None:
        return None

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(guide["title"])} | kontaktlinser.no</title>
<meta name="description" content="{escape(guide["description"])}">
{FONT_LINKS}
<style>{SHARED_STYLE}</style>
</head>
<body>
{GTM_BODY}
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(guide["title"])}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Guide</div>
      <h1>{escape(guide["title"])}</h1>
    </div>
  </div>
  <div style="max-width:640px;">
    {guide["body_html"]}
  </div>
</div>
{render_footer()}
</body>
</html>"""


def render_guides_index_page() -> str:
    cards_html = "\n".join(
        f"""<a class="guide-card" href="/guide/{escape(slug)}/">
  <div class="guide-card-title">{escape(g["title"])}</div>
  <div class="guide-card-desc">{escape(g["description"])}</div>
</a>"""
        for slug, g in GUIDE_CONTENT.items()
    )

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Guider – kontaktlinser.no</title>
<meta name="description" content="Guider om kontaktlinser: hvordan velge riktig type, og forskjellen på dagslinser og månedslinser.">
{FONT_LINKS}
<style>{SHARED_STYLE}
.guide-card {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; box-shadow: var(--card-shadow); margin-bottom: 10px; }}
.guide-card:hover {{ border-color: var(--aqua); }}
.guide-card-title {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; margin-bottom: 4px; }}
.guide-card-desc {{ font-size: 0.86rem; color: var(--muted); }}
</style>
</head>
<body>
{GTM_BODY}
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › Guider</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Guider</div>
      <h1>Guider</h1>
      <p>Kort og saklig hjelp til å velge riktig kontaktlinse.</p>
    </div>
  </div>
  {cards_html}
</div>
{render_footer()}
</body>
</html>"""


def render_category_page(category_slug: str, category: dict, products: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"] and not o["is_stale"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        image_url = pick_product_image(p["offers"])
        rows.append({"product": p, "lowest": lowest, "image_url": image_url})

    # Statisk render, sortert lavest-først som standard - dette er det AI-crawlere
    # og brukere uten JS faktisk ser.
    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        thumb = f'<img src="{escape(r["image_url"])}" alt="{escape(p["name"])}" loading="lazy">' if r["image_url"] \
            else escape(p["brand_label"][:2].upper())
        price_block = (
            f'<div class="price-label">Fra</div><div class="price-value" style="color:var(--mint);">{_fmt_kr(lowest["total"])}</div>'
            f'<div class="retailer-count">{len(p["offers"])} forhandlere</div>'
            if lowest else '<div class="retailer-count">Ingen tilbud tilgjengelig</div>'
        )
        href = f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/'
        return f"""<a class="product-card" href="{escape(href)}" data-brand="{escape(p["brand_slug"])}">
  <div class="product-thumb">{thumb}</div>
  <div class="product-main">
    <div class="product-name">{escape(p["name"])}</div>
    <div class="product-meta">{escape(p["brand_label"])}</div>
  </div>
  <div class="product-price-col">{price_block}</div>
</a>"""

    product_rows_html = "\n".join(render_row(r) for r in rows)

    brand_slugs = sorted({p["brand_slug"] for p in products})
    brand_chips = "".join(
        f'<button class="chip" data-brand="{escape(b)}">{escape(b.capitalize())}</button>' for b in brand_slugs
    )

    guides_html = "\n".join(
        f'<li><a href="/guide/{escape(g["slug"])}/">{escape(g["title"])}</a></li>' for g in category.get("guides", [])
    )

    schema_items = ",\n      ".join(
        f'''{{"@type": "ListItem", "position": {i+1}, "url": "{BASE_URL}/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/", "name": "{escape(p["name"])}"}}'''
        for i, p in enumerate(products)
    )
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "BreadcrumbList", "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
      {{"@type": "ListItem", "position": 2, "name": "{escape(category["label"])}", "item": "{BASE_URL}/kontaktlinser/{category_slug}/"}}
    ]}},
    {{"@type": "ItemList", "itemListElement": [{schema_items}]}}
  ]
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(category["label"])} – sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(category["intro"])}">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{GTM_BODY}
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(category["label"])}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Kategori</div>
      <h1>{escape(category["label"])}</h1>
      <p>{escape(category["intro"])}</p>
    </div>
  </div>

  <div class="filter-row" id="filter-row" role="group" aria-label="Filtrer etter merke">
    <button class="chip active" data-brand="all">Alle merker</button>
    {brand_chips}
  </div>

  <div class="list-header">
    <h2 id="result-count">{len(products)} produkter</h2>
    <button class="sort-toggle" id="sort-toggle" style="font-size:0.78rem;font-weight:600;color:var(--aqua);background:none;border:none;cursor:pointer;">Sorter: Lavest pris ↑</button>
  </div>

  <!-- Statisk, allerede sortert lavest-først. JS under er kun en forbedring
       (filter/re-sortering) ovenpå dette - fungerer uten JS også. -->
  <div id="product-list">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering og sortering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>

  <div class="guides">
    <h2>Guider</h2>
    <ul>{guides_html}</ul>
  </div>

  <p class="disclosure">
    Vi sorterer alltid etter lavest pris. Vi kan få provisjon når du handler
    via lenkene på produktsidene, men det påvirker ikke prisen du betaler
    eller rangeringen av produkter eller tilbud.
  </p>
</div>

<script>
  // Progressiv forbedring: alle produktkort finnes allerede i DOM-en over.
  // Denne koden skjuler/viser og re-sorterer dem - den bygger dem aldri fra
  // scratch, så innholdet er identisk med eller uten JS.
  const filterRow = document.getElementById('filter-row');
  const list = document.getElementById('product-list');
  const sortToggle = document.getElementById('sort-toggle');
  let ascending = true;

  filterRow.addEventListener('click', e => {{
    const btn = e.target.closest('.chip');
    if (!btn) return;
    filterRow.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    const brand = btn.dataset.brand;
    let visible = 0;
    list.querySelectorAll('.product-card').forEach(card => {{
      const show = brand === 'all' || card.dataset.brand === brand;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
  }});

  sortToggle.addEventListener('click', () => {{
    ascending = !ascending;
    sortToggle.textContent = 'Sorter: Lavest pris ' + (ascending ? '↑' : '↓');
    const cards = Array.from(list.querySelectorAll('.product-card'));
    cards.sort((a, b) => {{
      const av = parseFloat(a.querySelector('.price-value')?.textContent.replace(/\\D/g, '')) || Infinity;
      const bv = parseFloat(b.querySelector('.price-value')?.textContent.replace(/\\D/g, '')) || Infinity;
      return ascending ? av - bv : bv - av;
    }});
    cards.forEach(c => list.appendChild(c));
  }});
</script>
{render_footer()}
</body>
</html>"""
