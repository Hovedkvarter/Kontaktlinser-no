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
.topbar { display: flex; align-items: center; gap: 8px; padding: 18px 20px; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.05rem; max-width: 760px; margin: 0 auto; }
.topbar .ring-mark { width: 22px; height: 22px; flex-shrink: 0; }
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
.best-price-band .retailer { font-size: 0.95rem; color: var(--ink); margin-top: 2px; }
.best-price-band .price { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.6rem; color: var(--mint); white-space: nowrap; }
.offer-card, .product-card { display: flex; align-items: center; justify-content: space-between; gap: 14px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 10px; box-shadow: var(--card-shadow); text-decoration: none; color: var(--ink); }
.offer-card.is-lowest { border-color: var(--mint); background: var(--mint-tint); }
.offer-card.is-muted { opacity: 0.55; }
.product-card:hover, .offer-card a.cta:hover { border-color: var(--aqua); }
.offer-main, .product-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.offer-retailer, .product-name { font-weight: 600; font-size: 0.95rem; display: flex; align-items: center; gap: 6px; }
.lowest-tag { font-size: 0.68rem; font-weight: 600; color: white; background: var(--mint); padding: 2px 7px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.03em; }
.offer-meta, .product-meta, .retailer-count { font-size: 0.78rem; color: var(--muted); margin-top: 2px; }
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
"""

RING_MARK = """<svg class="ring-mark" viewBox="0 0 40 40" aria-hidden="true">
  <circle cx="20" cy="20" r="18" fill="none" stroke="#0B2545" stroke-width="2.2"/>
  <circle cx="20" cy="20" r="11" fill="none" stroke="#2EC4D6" stroke-width="2.2"/>
  <circle cx="20" cy="20" r="4" fill="#0B2545"/>
</svg>"""

FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">"""

LICENSED_IMAGE_SOURCES = {"affiliate_feed", "manufacturer_kit"}


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
    <div class="offer-retailer">{escape(retailer)} {lowest_tag}</div>
    {status_note}
  </div>
  <div class="offer-price-col">
    <div class="offer-total">{_fmt_kr(o["total"])}</div>
    <div class="offer-breakdown">{escape(shipping_text)}</div>
    <a class="cta" href="{escape(o["url"])}" rel="{rel}">Se hos {escape(retailer)}</a>
  </div>
</div>"""


def render_product_page(product: dict, now: datetime | None = None) -> str:
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
    <div class="retailer">{escape(best["retailer"])}</div>
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

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}},
  "offers": {{
    "@type": "AggregateOffer",
    "priceCurrency": "NOK",
    "lowPrice": {low_price},
    "highPrice": {high_price},
    "offerCount": {len(in_stock_offers)},
    "offers": [{schema_offers}]
  }}
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} – billigste pris | kontaktlinser.no</title>
<meta name="description" content="Sammenlign priser på {escape(product["name"])} hos norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
</style>
</head>
<body>
<div class="topbar">{RING_MARK} kontaktlinser.no</div>
<div class="wrap">
  <p class="breadcrumb">
    <a href="/">Hjem</a> ›
    <a href="/kontaktlinser/{escape(product["category_slug"])}/">{escape(product["category_slug"])}</a> ›
    <a href="/merke/{escape(product["brand_slug"])}/">{escape(product["brand_label"])}</a> ›
    {escape(product["name"])}
  </p>
  <div class="hero">
    <div class="product-thumb" style="width:84px;height:84px;font-size:1.4rem;">{thumb}</div>
    <div class="hero-copy">
      <div class="kicker">{escape(product["brand_label"])}</div>
      <h1>{escape(product["name"])}</h1>
      <p>{escape(product["description"])} Priser fra {len(offers)} norske nettbutikker.</p>
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
</div>
</body>
</html>"""


def render_home_page(catalog: dict) -> str:
    category_links = "\n".join(
        f'<li><a href="/kontaktlinser/{escape(slug)}/">{escape(category["label"])}</a></li>'
        for slug, category in catalog["categories"].items()
    )

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>kontaktlinser.no – sammenlign priser på kontaktlinser</title>
<meta name="description" content="Sammenlign priser på kontaktlinser fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
{FONT_LINKS}
<style>{SHARED_STYLE}</style>
</head>
<body>
<div class="topbar">{RING_MARK} kontaktlinser.no</div>
<div class="wrap">
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Prissammenligning</div>
      <h1>Finn billigste kontaktlinser</h1>
      <p>Vi sammenligner priser fra norske nettbutikker, oppdatert fortløpende. Velg en kategori for å se alle produkter og laveste pris.</p>
    </div>
  </div>
  <div class="related">
    <h2>Kategorier</h2>
    <ul>
      {category_links}
    </ul>
  </div>
</div>
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
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(category["label"])} – sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(category["intro"])}">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
<div class="topbar">{RING_MARK} kontaktlinser.no</div>
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
</body>
</html>"""
