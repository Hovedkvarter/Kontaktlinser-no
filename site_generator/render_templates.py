"""
render_templates.py

Rendrer produkt- og kategorisider som ferdig, statisk HTML - tilbudslisten,
prisene og "sist oppdatert"-tidspunktene ligger direkte i markupen som
returneres, IKKE bygget av JavaScript etter innlasting.

Grunnen: mange AI-crawlere (og noen eldre indekserere) kj√∏rer ikke
JavaScript. Er ikke prisen der i r√•-HTML, finnes den ikke for dem. JS her
brukes kun til forbedringer ovenp√• innhold som allerede er synlig uten den
(filter/sortering p√• kategorisiden) - se <noscript>-fallback i category-malen.

Bruker samme CSS-tokens som prototypene: ink/mist/blue/mint og Mulish. Endres designsystemet, endres SHARED_STYLE - ett sted.
"""

import hashlib
import json
import math
import re
import statistics
import struct
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from offer import compute_shipping_nok
from store_history_chart import product_store_days

# New content gets a new URL so browsers/CDNs cannot reuse an older chart.
_STORE_CHART_VERSION = hashlib.sha256((Path(__file__).resolve().parents[1] / "static/store-history-chart.js").read_bytes()).hexdigest()[:12]


def _json_str(s: str) -> str:
    """JSON-escaper for strengverdier som limes inn i h√•ndbygde JSON-LD
    <script>-blokker -- IKKE html.escape() (som escape()-navnet ellers
    brukes til overalt p√• siden for vanlig HTML-markup). html.escape()
    gj√∏r "&" om til bokstavelig "&amp;"-TEKST, som blir st√•ende som feil
    tegn inni selve JSON-en (gyldig JSON-syntaks, men feil VERDI -- en
    lenke med "&amp;" i stedet for "&" er en √∏delagt URL). Oppdaget
    2026-09-05: rammet fra f√∏r kun det f√•tallet affiliate-URL-er med "&" i
    seg, men ble et utbredt, reelt problem samme dag UTM-parametre
    (utm_source&utm_medium&utm_campaign) ble lagt til p√• nesten alle
    ikke-affiliate tilbudslenker. Returnerer STRENGEN UTEN omsluttende
    anf√∏rselstegn -- malene rundt legger selv til `"..."`."""
    return json.dumps(s)[1:-1]


BASE_URL = "https://kontaktlinser.no"


def _abs_url(url: str | None) -> str | None:
    """Rot-relativ sti (/static/...) -> absolutt https-URL. Allerede absolutte
    URL-er returneres uendret. Brukes for ALLE bilde-URL-er i metadata og
    strukturert data (og:image, Product.image, Article.image): Web Standard
    krever absolutte bilde-URL-er der, mens selve <img src> trygt kan v√¶re
    rot-relativ."""
    if url and url.startswith("/") and not url.startswith("//"):
        return BASE_URL + url
    return url


# --- Bildedimensjoner (width/height p√• <img>, hindrer layoutskift) -----------
# Egne filer under /static/ leses direkte fra disk (ren Python, ingen PIL --
# CI installerer bare requests/beautifulsoup4). Bilder vi viser fra en
# forhandlers feed (ikke v√•re filer) sl√•s opp i image_dimensions.json, som
# lages av probe_image_dimensions.py og committes; verken byggingen eller
# denne funksjonen gj√∏r noen gang nettverkskall. Ukjent dimensjon -> ingen
# width/height-attributter (aldri en gjetning).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_IMAGE_DIMS_FILE = _REPO_ROOT / "image_dimensions.json"
_dims_cache: dict[str, tuple[int, int] | None] = {}
_upstream_dims: dict[str, list[int]] | None = None


def _read_image_size(path: Path) -> tuple[int, int] | None:
    """Bredde/h√∏yde fra JPEG-, PNG- eller WebP-header. None hvis ukjent format."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                kind = head[12:16]
                if kind == b"VP8X":
                    return (1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little"))
                if kind == b"VP8L":
                    bits = int.from_bytes(head[21:25], "little")
                    return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
                if kind == b"VP8 ":
                    w, h = struct.unpack("<HH", head[26:30])
                    return (w & 0x3FFF, h & 0x3FFF)
                return None
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    code = marker[1]
                    if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                        continue
                    seglen = struct.unpack(">H", f.read(2))[0]
                    if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        _, h, w = struct.unpack(">BHH", f.read(5))
                        return (w, h)
                    f.seek(seglen - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def _image_dims(url: str | None) -> tuple[int, int] | None:
    global _upstream_dims
    if not url:
        return None
    if url in _dims_cache:
        return _dims_cache[url]
    dims = None
    if url.startswith("/static/"):
        dims = _read_image_size(_REPO_ROOT / url.lstrip("/"))
    else:
        if _upstream_dims is None:
            try:
                _upstream_dims = json.loads(_IMAGE_DIMS_FILE.read_text(encoding="utf-8"))["images"]
            except (OSError, ValueError, KeyError):
                _upstream_dims = {}
        d = _upstream_dims.get(url)
        if d and len(d) == 2 and d[0] > 0 and d[1] > 0:
            dims = (int(d[0]), int(d[1]))
    _dims_cache[url] = dims
    return dims


def _dim_attrs(url: str | None) -> str:
    """` width="W" height="H"` for kjente bilder, ellers tom streng."""
    d = _image_dims(url)
    return f' width="{d[0]}" height="{d[1]}"' if d else ""


def _og_meta(title: str, description: str, url: str, image: str | None = None) -> str:
    """Open Graph/Twitter Card-tagger, delt av alle sidetyper -- gjenbruker
    alltid samme tittel/beskrivelse som den vanlige <title>/<meta
    description> p√• siden, aldri egen tekst, slik at de to aldri kan komme
    ut av synk med hverandre. Faller tilbake til logoen n√•r siden ikke har
    et eget produktbilde (kategori/merke/guide/forside osv.)."""
    img = _abs_url(image) or f"{BASE_URL}/static/logo.png"
    return f"""<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{escape(url)}">
<meta property="og:image" content="{escape(img)}">
<meta property="og:site_name" content="Kontaktlinser.no">
<meta property="og:locale" content="nb_NO">
<meta name="twitter:card" content="summary_large_image">"""

SHARED_STYLE = """
@font-face { font-family: 'Mulish'; font-style: normal; font-weight: 200 1000; font-display: swap; src: url('/static/fonts/mulish-latin-variable.woff2') format('woff2'); }
button, input, select, textarea { font-family: 'Mulish', sans-serif; }
:root {
  --ink: #0B2545; --mist: #F5F9FA; --blue: #2563EB; --blue-tint: #E8EFFE; --blue-dark: #1D4ED8;
  --mint: #0BA36F; --mint-tint: #E4F6EE; --muted: #64748B; --muted-bg: #ECEFF3;
  --border: #DCE4EA; --card-shadow: 0 1px 2px rgba(11, 37, 69, 0.06);
  --coral: #E8637A; --coral-tint: #FCEAED; --amber: #D9A02B; --amber-tint: #FBF3E0;
  --lavender: #8B7FD6; --lavender-tint: #EEEBFA; --sky: #4F8FE8; --sky-tint: #E8F0FC;
  --orange: #FB923C; --orange-dark: #F0740F;
}
* { box-sizing: border-box; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
body { margin: 0; background: var(--mist); color: var(--ink); font-family: 'Mulish', sans-serif; line-height: 1.5; }
a { color: inherit; }
.wrap { max-width: 760px; margin: 0 auto; padding: 0 20px 64px; }
/* Tekstsider (guider, om oss osv.) holder seg smale for lesbarhet selv p√•
   store skjermer -- kun grid-/liste-/pristabellsider trenger mer bredde.
   wrap-wide: forside/kategori/merke-oversikter. wrap-product: produkt-
   /pristabellsider. Se .brand-grid for tilh√∏rende kolonne√∏kning ved
   samme breakpoint (.category-rows er en enkel radliste, skalerer ikke
   i kolonner). */
@media (min-width: 1024px) {
  .wrap-wide { max-width: 1280px; }
  .wrap-product { max-width: 1280px; }
}
.topbar { display: flex; align-items: center; justify-content: flex-start; gap: 32px; padding: 14px 20px; max-width: 760px; margin: 0 auto; flex-wrap: wrap; }
.topbar-logo { display: flex; align-items: center; text-decoration: none; }
.topbar-logo img { height: 24px; width: auto; display: block; mix-blend-mode: multiply; }
@media (min-width: 640px) { .topbar-logo img { height: 26px; } }
.topbar-nav { display: flex; gap: 6px; flex-wrap: wrap; }
.topbar-nav a { font-size: 0.95rem; font-weight: 600; text-decoration: none; color: var(--ink); }
.topbar-nav a:hover { color: var(--blue); }
.topbar-mobile-actions { display: none; }
.topbar-icon-btn { display: flex; align-items: center; justify-content: center; width: 38px; height: 38px; background: white; border: 1px solid var(--border); border-radius: 10px; color: var(--ink); cursor: pointer; padding: 0; }
.topbar-icon-btn svg { width: 19px; height: 19px; }
.topbar-icon-btn:hover, .topbar-icon-btn[aria-expanded="true"] { border-color: var(--blue); color: var(--blue); }
/* Kompakt mobil-header (2026-09-27) -- .topbar-nav/.topbar-search skjules
   som standard under 700px og vises kun n√•r brukeren faktisk trykker meny-
   /s√∏k-ikonet (se _topbar_html() sin docstring-kommentar for hvorfor dette
   er trygt for LENS_SEARCH_JS). .topbar-mobile-actions dyttes til slutt i
   raden med margin-left:auto (samme rad som logoen), slik at ikonene alltid
   havner √∏verst til h√∏yre uansett om .topbar-nav er √•pen eller lukket. */
@media (max-width: 699px) {
  .topbar { gap: 10px 12px; }
  .topbar-mobile-actions { display: flex; gap: 8px; margin-left: auto; }
  .topbar-nav { display: none; width: 100%; flex-direction: column; align-items: stretch; gap: 0; order: 4; }
  .topbar-nav.is-open { display: flex; }
  .topbar-nav .nav-item { width: 100%; }
  .topbar-nav .nav-trigger { width: 100%; justify-content: space-between; padding: 12px 4px; border-bottom: 1px solid var(--border); border-radius: 0; }
  .topbar-search.is-open { display: block !important; }
}
.nav-item { position: relative; }
.nav-trigger { display: flex; align-items: center; gap: 4px; background: none; border: none; font-family: inherit; font-size: 0.95rem; font-weight: 600; color: var(--ink); cursor: pointer; padding: 8px 6px; border-radius: 8px; }
.nav-trigger:hover, .nav-item.is-open .nav-trigger { color: var(--blue); }
.nav-caret { font-size: 0.65em; color: var(--muted); transition: transform 0.15s ease; }
.nav-item.is-open .nav-caret { transform: rotate(180deg); }
.mega-menu { position: absolute; top: 100%; left: 0; background: white; border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 14px 32px rgba(11, 37, 69, 0.14); padding: 14px; z-index: 50; opacity: 0; visibility: hidden; transform: translateY(-6px); transition: opacity 0.15s ease, transform 0.15s ease, visibility 0s linear 0.15s; }
.mega-menu-cols { display: flex; gap: 28px; }
.mega-col { display: flex; flex-direction: column; gap: 1px; min-width: 170px; }
.mega-col-title { font-weight: 700; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 6px; }
.mega-menu-link { display: flex; align-items: center; gap: 10px; color: var(--ink); text-decoration: none; font-size: 0.88rem; padding: 7px 10px; margin: 0 -10px; border-radius: 8px; transition: background 0.12s ease, color 0.12s ease; }
.mega-menu-link:hover { background: var(--mist); color: var(--blue); }
.mega-see-all { display: block; text-align: center; margin: 10px 0 0; padding: 10px 16px; border-radius: 999px; background: var(--blue); color: white !important; font-weight: 700; }
.mega-see-all:hover { background: var(--blue-dark); color: white !important; }
.mega-menu-rich { width: min(94vw, 380px); padding: 20px; }
.mega-rich-grid { display: grid; grid-template-columns: 1fr; gap: 24px; margin-bottom: 16px; }
@media (min-width: 700px) {
  /* Hver variant er bredden dens egne kolonner faktisk trenger -- IKKE √©n
     felles bredde for alle tre, det tvang de to smalere menyene (Merker,
     Guider) un√∏dvendig brede og √∏kte risikoen for at de skj√∏t utenfor
     viewport ved 1024px (nedre st√∏ttede breddegrense), siden posisjonen
     deres i navigasjonen varierer. */
  .mega-menu-rich:has(.mega-rich-grid-2col) { width: 580px; }
  .mega-menu-rich:has(.mega-rich-grid-3col-plain) { width: 540px; }
  .mega-menu-rich:has(.mega-rich-grid-2col-plain) { width: 400px; }
  .mega-rich-grid-2col { grid-template-columns: 220px 1fr; }
  .mega-rich-grid-3col-plain { grid-template-columns: repeat(3, 150px); gap: 18px; }
  .mega-rich-grid-2col-plain { grid-template-columns: repeat(2, 170px); gap: 18px; }
}
.mega-rich-col { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mega-panel-kicker { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--blue); }
.mega-panel-heading { font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 1.1rem; line-height: 1.3; color: var(--ink); margin: 4px 0 0; }
.mega-panel-text { font-size: 0.85rem; color: var(--muted); line-height: 1.5; margin: 6px 0 0; }
/* "Alle merker A-√Ö" (2026-09-29) -- CSS-multikolonne (samme teknikk som
   .footer-brand-list) i stedet for et grid, siden listen har et variabelt
   antall lenker (25+ i dag, vokser n√•r nye merker/private label-serier
   legges til) og multikolonne fyller kolonnene i lesevennlig topp-til-bunn-
   rekkef√∏lge uten at vi m√• telle rader manuelt. break-inside:avoid hindrer
   at √©n lenke visuelt kuttes over kolonnegrensen. */
.mega-allbrands { columns: 2; column-gap: 14px; }
.mega-allbrands-link { font-size: 0.83rem; padding: 5px 8px; margin: 0 -8px; break-inside: avoid; }
.mega-link-row { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); padding: 7px 10px; margin: 0 -10px; border-radius: 8px; transition: background 0.12s ease; }
.mega-link-row:hover { background: var(--mist); }
.mega-link-row-icon { flex-shrink: 0; width: 26px; height: 26px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; }
.mega-link-row-icon svg { width: 14px; height: 14px; }
.mega-link-row-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.mega-link-row-label { font-size: 0.83rem; font-weight: 600; }
.mega-link-row-sub { font-size: 0.75rem; color: var(--muted); }
.mega-link-row-chevron { flex-shrink: 0; width: 14px; height: 14px; color: var(--muted); }
@media (hover: hover) {
  .nav-item:hover .mega-menu, .nav-item:focus-within .mega-menu { opacity: 1; visibility: visible; transform: translateY(0); transition-delay: 0s; }
}
.nav-item.is-open .mega-menu { opacity: 1; visibility: visible; transform: translateY(0); transition-delay: 0s; }
/* Under 1280px er .mega-menu ellers venstre-forankret til SIN EGEN
   nav-item-knapp (position:absolute; left:0 relative til .nav-item) -- for
   en knapp langt til h√∏yre i navigasjonen (f.eks. "Guider") skyter en
   380-720px bred meny da langt utenfor et smalt mobilvindu. .topbar er
   display:flex UTEN justify-content:space-between, s√• innholdet
   (logo+nav) henger fast venstrestilt inni boksen -- og siden .topbar selv
   er en full-bredde blokk (display:flex oppf√∏rer seg som display:block for
   selve boksen) helt opp til den treffer sitt eget max-width-tak (760px
   under 1024px, 1200px fra og med 1024px, se .topbar-regelen over), flytter
   IKKE nav-knappene seg til h√∏yre n√•r viewporten vokser -- de blir
   liggende p√• n√∏yaktig samme pikselposisjon fra venstre kant helt til
   .topbar treffer 1200px-taket sitt og margin:0 auto begynner √• sentrere
   boksen. M√•lt i praksis skjer det f√∏rst et sted mellom ca. 1179px og
   1220px viewport-bredde (avhenger av om scrollbaren tar layoutplass eller
   ikke, dvs. Windows vs. Mac-overlay-scrollbar) -- IKKE ved 1024px slik man
   skulle tro av .topbar sitt eget brytpunkt. En fastbredde-meny (540-720px,
   satt i @media (min-width:700px) over) kan derfor stikke rett utenfor
   viewporten helt opp til den sonen, og gir horisontal scroll p√• body selv
   n√•r menyen er lukket (position:absolute + visibility:hidden opptar
   fortsatt layoutplass). L√•ser i stedet menyen til viewporten med
   position:fixed og faste sidemarger helt opp til og med 1279px -- godt
   over den m√•lte faresonen, som ekstra margin mot at font-rendering eller
   fremtidige menytekster flytter kryssingspunktet noe -- og JS-en i
   TOPBAR_HTML sitt <script> (closeAll()/trigger-click) setter inline top=
   like under selve topbaren ved √•pning -- position:fixed sin top er alltid
   viewport-relativ, s√• getBoundingClientRect().bottom fungerer uendret
   uansett scroll-posisjon. top:70px under er kun et statisk fallback-tall
   for det (usannsynlige) tilfellet JS ikke kj√∏rer. Klarer nav-item bevisst
   IKKE position:static her -- feil forankringskontekst ville kun flyttet
   problemet et hakk (fortsatt konteksten til den enkelte knappen),
   position:fixed l√∏ser det uansett hvilken knapp som er trigger. Fra og
   med 1280px er all praktisk testing (opp til 1920px) uten overflow, siden
   .topbar da for lengst har truffet 1200px-taket sitt og sentrerer
   innholdet med god margin til h√∏yre. */
@media (max-width: 1279px) {
  .mega-menu, .mega-menu-rich {
    position: fixed; left: 12px; right: 12px; top: 70px; width: auto; max-width: none;
    max-height: calc(100vh - 90px); overflow-y: auto; padding: 16px;
  }
}
.breadcrumb { font-size: 0.8rem; color: var(--muted); margin: 4px 0 20px; }
.breadcrumb a { text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.hero { position: relative; padding: 8px 0 22px; }
.hero-copy { position: relative; z-index: 1; max-width: 520px; }
.hero-copy .kicker { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
.hero-copy h1 { font-family: 'Mulish', sans-serif; font-size: 1.9rem; line-height: 1.15; margin: 4px 0 8px; }
.hero-copy p { margin: 0; color: var(--muted); font-size: 1rem; line-height: 1.55; }
.offer-card, .product-card { display: flex; align-items: center; justify-content: space-between; gap: 14px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 10px; box-shadow: var(--card-shadow); text-decoration: none; color: var(--ink); }
.offer-card.is-lowest { border-color: var(--mint); background: var(--mint-tint); }
.offer-card.is-muted { opacity: 0.55; }
.offer-card:hover, .offer-card:focus-visible { border-color: var(--blue); }
.offer-card.is-lowest:hover, .offer-card.is-lowest:focus-visible { border-color: var(--mint); }
.offer-card:hover .price-pill, .offer-card:focus-visible .price-pill { opacity: 0.88; }
.product-card:hover { border-color: var(--blue); }
.offer-main, .product-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.offer-retailer, .product-name { font-weight: 600; font-size: 0.95rem; display: flex; align-items: center; gap: 6px; }
.offer-meta, .product-meta, .retailer-count { font-size: 0.78rem; color: var(--muted); margin-top: 2px; }
.retailer-logo { height: 18px; width: auto; max-width: 92px; object-fit: contain; vertical-align: middle; }
.retailer-logo-chip { display: inline-flex; align-items: center; background: var(--ink); border-radius: 4px; padding: 3px 6px; }
.brand-card-badge.has-logo, .brand-card-badge.has-logo-dark { width: 52px; border-radius: 8px; padding: 4px; }
.brand-card-badge.has-logo { background: white; }
.brand-card-badge.has-logo-dark { background: var(--ink); }
.brand-logo-img { width: 100%; height: 100%; object-fit: contain; }
.brand-hero-row { display: flex; align-items: center; gap: 16px; }
.brand-hero-logo { flex-shrink: 0; width: 64px; height: 64px; border-radius: 50%; background: var(--blue-tint); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.brand-hero-logo.has-logo, .brand-hero-logo.has-logo-dark { width: 128px; border-radius: 14px; padding: 10px; }
.brand-hero-logo.has-logo { background: white; }
.brand-hero-logo.has-logo-dark { background: var(--ink); }
.product-price-col { text-align: right; flex-shrink: 0; }
.price-value { font-family: 'Mulish', sans-serif; font-weight: 600; font-size: 1.05rem; }
.price-label { font-size: 0.68rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.03em; }
.offer-price-col { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
.offer-shipping { display: flex; align-items: center; gap: 5px; font-size: 0.78rem; color: var(--muted); white-space: nowrap; }
.offer-shipping svg { width: 15px; height: 15px; color: var(--mint); flex-shrink: 0; }
.price-pill { display: inline-block; font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 1.15rem; color: white; background: var(--blue); padding: 10px 22px; border-radius: 999px; text-decoration: none; white-space: nowrap; }
.price-pill:hover { opacity: 0.88; }
.offer-card.is-lowest .price-pill { background: var(--mint); }
/* .offer-card hadde ingen mobil-spesifikk layout i det hele tatt -- p√•
   smale skjermer presset ikke-brytende fraktekst (.offer-shipping) i
   .offer-price-col butikk-logoen sammen, og et merke som pleide √• st√• der
   (n√• fjernet) br√∏t internt til 2 linjer og dekket fraktt√©ksten (Kai,
   2026-09-27, skjermbilde av live-siden). Fikset ved √• stable
   logo-raden og pris/frakt-raden p√• mobil, og la selve fraktteksten f√•
   bryte til 1-2 linjer inne i sin egen rad i stedet for √• presses av en
   fastbredde prispille ved siden av. Kun mobil -- desktop er uendret. */
@media (max-width: 699px) {
  .offer-card { flex-wrap: wrap; }
  .offer-main { flex-basis: 100%; }
  .offer-price-col { flex-basis: 100%; justify-content: space-between; align-items: center; }
  .offer-shipping { white-space: normal; flex: 1; min-width: 0; align-items: flex-start; }
}
.product-thumb { width: 52px; height: 52px; border-radius: 50%; background: var(--blue-tint); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 0.9rem; color: var(--blue); flex-shrink: 0; overflow: hidden; }
.product-thumb img { width: 100%; height: 100%; object-fit: cover; }
.chip { font-size: 0.82rem; font-weight: 600; padding: 7px 14px; border-radius: 20px; border: 1px solid var(--border); background: white; cursor: pointer; color: var(--ink); }
.chip.active { background: var(--blue); border-color: var(--blue); color: white; }
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 20px 0 24px; }
.list-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
.list-header h2 { font-family: 'Mulish', sans-serif; font-size: 1.05rem; margin: 0; }
.related, .guides { margin-top: 32px; }
.related h2, .guides h2 { font-family: 'Mulish', sans-serif; font-size: 1rem; margin: 0 0 10px; }
.related ul, .guides ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.related a, .guides a { display: block; font-size: 0.88rem; text-decoration: none; padding: 10px 14px; background: white; border: 1px solid var(--border); border-radius: 10px; }
.related a:hover, .guides a:hover { border-color: var(--blue); }
.disclosure { font-size: 0.78rem; color: var(--muted); line-height: 1.6; border-top: 1px solid var(--border); padding-top: 18px; margin-top: 22px; }
@media (min-width: 560px) { .hero-copy h1 { font-size: 2.2rem; } }
.site-footer { margin-top: 48px; background: var(--ink); color: white; }
.footer-inner { max-width: 760px; margin: 0 auto; padding: 40px 20px 8px; display: flex; flex-wrap: wrap; gap: 32px 24px; }
.footer-col { flex: 1 1 140px; min-width: 140px; }
.footer-col h3 { font-family: 'Mulish', sans-serif; font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--blue); margin: 0 0 12px; }
.footer-col a { display: block; font-size: 0.85rem; color: rgba(255,255,255,0.78); text-decoration: none; padding: 3px 0; }
.footer-col a:hover { color: white; text-decoration: underline; }
.footer-brand-list { columns: 2; column-gap: 16px; }
.footer-disclosure { max-width: 760px; margin: 8px auto 0; padding: 20px 20px 0; font-size: 0.75rem; line-height: 1.6; color: rgba(255,255,255,0.55); border-top: 1px solid rgba(255,255,255,0.14); }
.footer-bottom { max-width: 760px; margin: 0 auto; padding: 14px 20px 28px; display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center; font-size: 0.76rem; color: rgba(255,255,255,0.5); }
.footer-bottom a { color: rgba(255,255,255,0.5); text-decoration: none; }
.footer-bottom a:hover { color: white; }
.consent-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(11, 37, 69, 0.45); display: flex; align-items: center; justify-content: center; padding: 20px; }
.consent-overlay[hidden] { display: none; }
.consent-modal { background: white; border-radius: 16px; max-width: 460px; width: 100%; max-height: 85vh; overflow-y: auto; padding: 28px; box-shadow: 0 20px 60px rgba(11, 37, 69, 0.28); }
.consent-modal h2 { font-family: 'Mulish', sans-serif; font-size: 1.15rem; margin: 0 0 14px; }
.consent-text { font-size: 0.88rem; line-height: 1.6; color: var(--ink); margin: 0 0 20px; }
.consent-text a { color: var(--blue); }
.consent-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.consent-btn { font-family: 'Mulish', sans-serif; font-size: 0.84rem; font-weight: 600; padding: 10px 18px; border-radius: 20px; cursor: pointer; border: 1px solid transparent; }
.consent-btn-primary { background: var(--ink); color: white; }
.consent-btn-primary:hover { background: var(--blue); }
.consent-btn-secondary { background: white; color: var(--ink); border-color: var(--border); }
.consent-btn-secondary:hover { border-color: var(--blue); }
.consent-category { border-top: 1px solid var(--border); padding: 14px 0; }
.consent-category:first-of-type { border-top: none; padding-top: 0; }
.consent-category-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-weight: 600; font-size: 0.9rem; }
.consent-category-desc { font-size: 0.8rem; color: var(--muted); line-height: 1.5; margin: 6px 0 0; }
.consent-toggle { flex-shrink: 0; appearance: none; -webkit-appearance: none; width: 40px; height: 24px; background: var(--border); border-radius: 12px; position: relative; cursor: pointer; margin: 0; transition: background 0.15s; }
.consent-toggle::before { content: ""; position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; background: white; border-radius: 50%; transition: transform 0.15s; box-shadow: 0 1px 3px rgba(11, 37, 69, 0.3); }
.consent-toggle:checked { background: var(--blue); }
.consent-toggle:checked::before { transform: translateX(16px); }
.consent-toggle:disabled { opacity: 0.6; cursor: default; }
.consent-link-btn { background: none; border: none; color: var(--blue); font-size: 0.82rem; font-weight: 600; text-decoration: underline; cursor: pointer; padding: 14px 0 0; display: block; }
.consent-providers-list:not([hidden]) { list-style: none; padding: 8px 0 0; margin: 0; font-size: 0.82rem; color: var(--muted); }
.consent-providers-list li { padding: 3px 0; }
.consent-more-link { font-size: 0.8rem; }
@media (min-width: 1024px) {
  .topbar, .footer-inner, .footer-disclosure, .footer-bottom { max-width: 1280px; }
}
.product-tile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 18px; margin-bottom: 8px; }
.product-tile { position: relative; display: flex; flex-direction: column; background: white; border: 1px solid var(--border); border-radius: 16px; overflow: hidden; box-shadow: 0 6px 18px rgba(11, 37, 69, 0.06); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.product-tile:hover { transform: translateY(-3px); border-color: #B9C9DD; box-shadow: 0 10px 28px rgba(11, 37, 69, 0.11); }
.product-tile-image-link { display: block; text-decoration: none; }
.product-tile-image { height: 190px; margin: 14px 14px 0; border-radius: 12px; background: var(--mist); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.product-tile-image.has-photo { background: var(--mist); }
.product-tile-image img { display: block; width: 86%; height: auto; max-height: 150px; object-fit: contain; mix-blend-mode: multiply; }
.product-tile-fallback { font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 1.8rem; color: var(--blue); }
.product-tile-body { padding: 16px 18px 0; flex-grow: 1; display: flex; flex-direction: column; }
.product-tile-category { display: inline-block; align-self: flex-start; margin-bottom: 10px; padding: 5px 8px; border-radius: 999px; background: var(--blue-tint); color: var(--blue); font-size: 0.75rem; line-height: 1; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
.product-tile-name-link { text-decoration: none; color: var(--ink); }
.product-tile-name-link .product-name { font-size: 1.05rem; line-height: 1.35; font-weight: 700; min-height: 2.7em; }
.product-tile-manufacturer { display: block; margin-top: 6px; font-size: 0.85rem; color: var(--muted); text-decoration: none; }
.product-tile-manufacturer:hover { text-decoration: underline; }
.product-tile-specs-row { display: flex; gap: 14px; margin-top: 12px; flex-wrap: wrap; }
.product-tile-spec { display: flex; align-items: center; gap: 5px; font-family: 'Mulish', sans-serif; font-size: 0.78rem; color: var(--muted); }
.product-tile-spec svg { width: 14px; height: 14px; color: var(--blue); flex-shrink: 0; }
.product-tile-divider { height: 1px; margin: 16px 0 14px; background: var(--border); }
.product-tile-price-link { display: block; text-decoration: none; color: var(--ink); margin-top: auto; }
.product-tile-high-price, .product-tile-price-from { display: none; }
.product-tile-price-label { font-size: 0.8rem; color: #5B6B80; margin-bottom: 3px; }
.product-tile-price { font-family: 'Mulish', sans-serif; display: flex; align-items: baseline; gap: 4px; color: var(--ink); }
.product-tile-price-number { font-size: 1.9rem; line-height: 1; font-weight: 700; letter-spacing: -0.02em; }
.product-tile-price-currency { font-size: 0.9rem; font-weight: 700; }
.product-tile-store-line { margin-top: 8px; font-size: 0.85rem; color: var(--muted); }
.product-tile-store-name { color: var(--ink); font-weight: 700; }
.product-tile-store-count { color: var(--blue); font-weight: 700; }
.product-tile-cta { display: block; margin: 16px 18px 18px; padding: 12px 16px; background: var(--blue); color: white; text-decoration: none; text-align: center; font-size: 0.9rem; font-weight: 700; border-radius: 9px; transition: background 0.15s; }
.product-tile:hover .product-tile-cta { background: var(--blue-dark); }
.product-tile-savings { display: none; }
/* Mobile product lists: reference 003, two cards per row. Keep full names
   and native links; no line clamping or JavaScript-dependent content. */
  .mobile-products-first { display: flex; flex-direction: column; }
  .mobile-products-first > .priority-products { order: -1; min-width: 0; }
  .mobile-products-first > .supporting-content { min-width: 0; }

@media (max-width: 600px) {
  .product-tile-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .product-tile { min-width: 0; border-radius: 10px; box-shadow: none; }
  .product-tile-image { height: 126px; margin: 34px 5px 0; border-radius: 6px; background: white; }
  .product-tile-image.has-photo { background: white; }
  .product-tile-image img { width: 100%; max-height: 126px; }
  .product-tile-body { padding: 10px 10px 0; min-width: 0; }
  .product-tile-name-link { order: -2; overflow-wrap: anywhere; }
  .product-tile-name-link .product-name { font-size: .875rem; line-height: 1.3; min-height: 0; }
  .product-tile-category { order: -1; background: none; color: var(--muted); padding: 0; margin: 5px 0 0; font-size: .75rem; line-height: 1.35; text-transform: none; letter-spacing: 0; }
  .product-tile-manufacturer[href^="/produsent/"], .product-tile-manufacturer[href^="/merke/"], .product-tile-specs-row { display: none; }
  .product-tile-divider { height: 0; margin: 12px 0 0; }
  .private-label-brand-hero .brand-hero-logo { display: none; }
  .product-tile-price-label { font-size: .7rem; min-height: 1.05rem; }
  .product-tile-price-label-default { display: none; }
  .product-tile-high-price { display: inline; }
  .product-tile-price-from { display: inline; font-size: .8rem; font-weight: 500; }
  .product-tile-price-number { font-size: 1.45rem; }
  .product-tile-price-currency { font-size: .8rem; }
  .product-tile-store-line { font-size: .72rem; line-height: 1.4; margin-top: 5px; overflow-wrap: anywhere; }
  .product-tile:hover .product-tile-cta { background: #0759bf; }
  .product-tile-savings { display: inline-block; position: absolute; top: 10px; left: 10px; padding: 4px 8px; border-radius: 999px; background: #d0443b; color: #fff; font-size: .7rem; font-weight: 700; line-height: 1.1; cursor: help; }
  .product-tile-savings:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .product-tile-savings:hover::after, .product-tile-savings:focus::after { content: attr(data-explanation); position: absolute; z-index: 3; top: calc(100% + 6px); left: 0; width: 120px; box-sizing: border-box; padding: 8px; border-radius: 6px; background: var(--ink); color: white; font-size: .7rem; font-weight: 400; line-height: 1.4; }
  .product-tile-cta { display: flex; align-items: center; justify-content: center; min-height: 44px; box-sizing: border-box; margin: 8px; padding: 8px 4px; font-size: .75rem; font-weight: 500; line-height: 1.3; border-radius: 7px; background: #0866d9; }
}
/* Desktop: savings and highest-price line only. */
@media (min-width: 601px) {
  .product-tile-price-from { display: inline; font-size: 1rem; font-weight: 500; }
  .product-tile-price-label-default { display: none; }
  .product-tile-high-price { display: inline; }
  .product-tile-price-label { min-height: 1.2em; }
  .product-tile-savings { display: inline-block; position: absolute; z-index: 2; top: 10px; left: 10px; padding: 4px 8px; border-radius: 999px; background: #d0443b; color: #fff; font-size: .7rem; font-weight: 700; line-height: 1.1; cursor: help; }
  .product-tile-savings:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .product-tile-savings:hover::after, .product-tile-savings:focus::after { content: attr(data-explanation); position: absolute; z-index: 3; top: calc(100% + 6px); left: 0; width: 180px; box-sizing: border-box; padding: 8px; border-radius: 6px; background: var(--ink); color: white; font-size: .7rem; font-weight: 400; line-height: 1.4; }
}
.faq-section { margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }
.faq-section h2 { font-family: 'Mulish', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }
.faq-item { margin-bottom: 18px; }
.faq-item h3 { font-size: 0.94rem; margin: 0 0 6px; }
.faq-item p { font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin: 0; }
.methodology { margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }
.methodology h2 { font-family: 'Mulish', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }
.methodology dl { margin: 0; }
.methodology-row { display: flex; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.methodology-row:last-child { border-bottom: none; }
.methodology-row dt { flex: 0 0 110px; font-weight: 600; font-size: 0.88rem; }
.methodology-row dd { margin: 0; font-size: 0.88rem; color: var(--muted); line-height: 1.6; }
/* Flyttet hit fra render_product_page sin egen <style> 2026-09-27 -- brukes n√•
   av B√ÖDE produktsiden og serie-siden sitt nye prisinnsikt-panel (se
   render_family_price_insight()), √©n kilde i stedet for to kopier. */
.price-history { margin-top: 28px; }
.price-history h2 { font-family: 'Mulish', sans-serif; font-size: 1.05rem; margin: 0 0 6px; }
.price-history-summary { font-size: 0.85rem; color: var(--muted); margin: 0 0 12px; }
.price-history-chart { width: 100%; height: auto; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 4px 0; }
/* fill settes INLINE per <path> (se _render_price_history_chart), ikke her --
   en side kan n√• ha FLERE grafer samtidig (serie-siden sitt prisinnsikt-panel,
   √©n per pakningsst√∏rrelse), og en delt CSS-regel med en fast #id ville pekt
   alle grafene til samme (f√∏rste) gradient i dokumentet -- funnet 2026-09-27
   da 90-pakning-fanen viste linjen uten fylt areal under. */
.price-history-area { stroke: none; }
.price-history-line { fill: none; stroke: var(--orange-dark); stroke-width: 2.25; stroke-linejoin: round; stroke-linecap: round; }
.price-history-dot { fill: white; stroke: var(--orange-dark); stroke-width: 1.5; }
.price-history-dot-last { fill: var(--orange-dark); stroke: white; stroke-width: 1.5; }
.price-history-gridline { stroke: var(--border); stroke-width: 1; stroke-dasharray: 3 3; }
.price-history-axis-label { font-family: 'Mulish', sans-serif; font-size: 9.5px; fill: var(--muted); }
.price-history-current-label { font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 11px; fill: var(--orange-dark); }
/* Price Intelligence (Product Gold Standard v1, 2026-09-27, flyttet hit
   2026-09-28 for gjenbruk p√• ALLE produkttyper -- Kai: "gjelder alle
   produkter p√• domenet kontaktlinser.no ... alle kontaktlinser, egne
   merkenavn kontaktlinser, og alle Tilbeh√∏r produkter", inkl.
   linsev√¶ske/√∏yedr√•per som deler samme rendringsfunksjon som Tilbeh√∏r).
   Var opprinnelig i render_product_page() sin egen lokale <style>-blokk
   -- flyttet til SHARED_STYLE (global) slik at render_solution_
   product_page()/render_private_label_page() ogs√• f√•r den, uten
   duplisering. Mobil (regel 27): kompakt, stablet. Desktop (regel 28,
   >=860px): 4 toppmetrikker p√• √©n rad, mer luft -- men fortsatt
   restrained, "skal fortsatt f√∏les som Kontaktlinser.no", ikke et tett
   analytics-dashboard. */
.price-intel { margin-top: 28px; background: white; border: 1px solid var(--border); border-radius: 16px; padding: 18px; }
.price-intel-head { margin-bottom: 14px; }
.price-intel-head-text h2 { font-family: 'Mulish', sans-serif; font-size: 1.1rem; margin: 0; }
.price-intel-head-text p { font-size: 0.84rem; color: var(--muted); margin: 3px 0 0; line-height: 1.5; }
.price-intel-coverage { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 0.76rem; color: var(--muted); background: white; border: 1px solid var(--border); border-radius: 10px; padding: 7px 11px; }
.price-intel-coverage svg { width: 15px; height: 15px; color: var(--blue); flex-shrink: 0; }
.price-intel-coverage strong { color: var(--ink); }
/* Price Intelligence v2 -- "premium data publication"-redesign
   (2026-09-29, Kai, godkjent mockup-bilde 58.webp er visuell fasit).
   Filosofi: mindre dashboard-kort/gr√•-bl√• flater, mer typografi/luft/
   tynne skillelinjer -- tallene ER designet, ikke pakket inn i bokser.
   All underliggende logikk/beregning er UENDRET fra logikk-/semantikk-
   runden tidligere samme dag -- dette er ren presentasjon. */
/* Egen "container" slik at topplaget (metrikkrad + statuspille) kan tilpasse
   seg MODULENS faktiske bredde, ikke viewporten -- modulen er smalere enn
   viewporten (siden rundt + padding), s√• en @media-terskel ville truffet
   feil. Uten container-query-st√∏tte gjelder bare mobil-stylingen (stablet),
   som er trygg. */
.price-intel { container-type: inline-size; container-name: pintel; }
.price-intel-eyebrow { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--blue); margin: 0 0 4px; }
.price-intel-coverage-days { display: block; font-size: 0.7rem; color: var(--muted); margin-top: 2px; }
/* Prim√¶rraden: "Pris n√•" (dominerende) + tre skilte historikk-metrikker
   + en atskilt statuspille. Kun √©n periodes .price-intel-primary er
   noensinne synlig (.active) -- server-rendret, fungerer uten JS. */
.price-intel-primary { display: none; margin-bottom: 16px; }
.price-intel-primary.active { display: block; }
.price-intel-metrics-row { display: flex; flex-wrap: wrap; gap: 14px 0; }
.price-intel-metric-col { flex: 1 1 46%; box-sizing: border-box; padding-right: 10px; }
.price-intel-metric-current { flex: 1 1 100%; margin-bottom: 2px; }
.price-intel-value { display: block; font-family: 'Mulish', sans-serif; font-weight: 600; font-size: 1.15rem; color: var(--ink); line-height: 1.1; }
.price-intel-value-lg { display: block; font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 2.1rem; color: var(--ink); line-height: 1.05; }
.price-intel-metric-label { display: block; font-size: 0.72rem; color: var(--muted); margin-top: 4px; line-height: 1.35; }
.price-intel-metric-info { display: inline-block; opacity: 0.7; margin-left: 2px; }
.price-intel-metric-desc { display: block; font-size: 0.66rem; color: var(--muted); opacity: 0.85; margin-top: 5px; line-height: 1.4; max-width: 190px; }
.price-intel-metric-sublabel { display: block; font-size: 0.68rem; color: var(--muted); margin-top: 1px; }
.price-intel-current-dot { display: inline-flex; align-items: center; gap: 5px; font-size: 0.74rem; font-weight: 600; color: var(--mint); margin-top: 6px; }
.price-intel-current-dot i { width: 7px; height: 7px; border-radius: 50%; background: var(--mint); display: inline-block; font-style: normal; }
/* Status: fortsatt en diskret tinted "konklusjon"-pille (regel 5: "may
   remain a subtle tinted module because it represents a conclusion
   rather than a raw metric"), men n√• atskilt fra r√•dataraden, ikke en
   grid-rute blant metrikkene. */
.price-intel-status-pill { display: flex; align-items: center; gap: 9px; background: var(--mint-tint); border-radius: 12px; padding: 11px 14px; margin-top: 14px; }
.price-intel-status-pill .price-intel-status-icon { flex-shrink: 0; width: 28px; height: 28px; border-radius: 50%; background: white; display: flex; align-items: center; justify-content: center; }
.price-intel-status-pill .price-intel-status-icon svg { width: 15px; height: 15px; color: var(--mint); }
.price-intel-status-pill span { font-size: 0.76rem; color: var(--muted); line-height: 1.4; }
.price-intel-status-pill span strong { display: block; font-size: 0.86rem; color: var(--ink); margin-bottom: 1px; }
.price-intel-status-pill.price-intel-status-up, .price-intel-status-pill.price-intel-status-high { background: #FDECEC; }
.price-intel-status-pill.price-intel-status-up .price-intel-status-icon svg, .price-intel-status-pill.price-intel-status-high .price-intel-status-icon svg { color: #D64545; }
/* Periodevelger -- uendret fra forrige runde: kompakte piller, aktiv =
   m√∏rk navy. */
.price-intel-period-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.price-intel-period-tab { font-size: 0.76rem; font-weight: 600; font-family: inherit; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border); background: white; color: var(--muted); cursor: pointer; }
.price-intel-period-tab.active { background: var(--ink); border-color: var(--ink); color: white; }
.price-intel-period-tab:disabled { opacity: 0.35; cursor: not-allowed; }
.price-intel-chart-panel { display: none; }
.price-intel-chart-panel.active { display: block; }
/* Grafens "hylle" -- smalnes inn og sentreres p√• stor desktop (regel
   8/9: "the chart should NOT span the entire Price Intelligence width...
   narrower but still important", 220-240px h√∏yde beholdt uendret). */
.price-intel-chart-shell { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px 8px; }
.price-intel-chart-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px 12px; margin-bottom: 6px; font-size: 0.72rem; color: var(--muted); flex-wrap: wrap; }
.price-intel-chart-toolbar-badge { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); border-radius: 999px; padding: 4px 10px; background: white; }
.price-intel-chart-toolbar-badge svg { width: 13px; height: 13px; color: var(--muted); flex-shrink: 0; }
.price-intel-chart .price-history-chart { padding: 2px 0; }
.price-intel-hit { fill: transparent; stroke: none; cursor: pointer; }
/* Mellomliggende dato-tikker (ikke f√∏rste/siste) skjules under 640px --
   samme kompakte to-etiketters mobilvisning som f√∏r, mens desktop n√•
   viser alle (v2-redesign runde 2, rapport #3). */
@media (max-width: 639px) {
  .price-intel-chart .price-history-axis-label-x:not(.price-history-axis-label-edge) { display: none; }
}
/* Intelligens-raden -- fortsatt tynt-kantede hvite kort, men n√• kappet i
   bredde og SENTRERT som en gruppe (v2-redesign runde 2, rapport #4/#6:
   "do not simply stretch the remaining two cards to fill the entire
   width... Keep them at approximately the same intended card width").
   flex i stedet for grid auto-fit -- auto-fit STREKKER hvert spor til √•
   dele bredden likt uansett antall kort, n√∏yaktig det som ga de
   "gigantiske 50/50-kortene" Kai pekte p√•; flex+justify-content:center
   lar hvert kort beholde sin egen, tiltenkte bredde og heller la
   overskuddsplassen bli synlig luft p√• sidene av raden. */
.price-intel-cards { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-top: 14px; }
.price-intel-card { background: white; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; flex: 1 1 260px; }
.price-intel-card h3 { display: flex; align-items: center; gap: 7px; font-family: 'Mulish', sans-serif; font-size: 0.88rem; margin: 0; color: var(--ink); }
.price-intel-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.price-intel-card-head-note { font-size: 0.7rem; color: var(--muted); white-space: nowrap; }
.price-intel-card h3 svg { width: 16px; height: 16px; flex-shrink: 0; }
.price-intel-card-h-spread svg, .price-intel-card-h-qty svg { color: var(--blue); }
.price-intel-card-h-winner svg { color: var(--amber); }
.price-intel-card-row { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; font-size: 0.84rem; color: var(--ink); }
.price-intel-card-row span { color: var(--muted); }
.price-intel-card-row strong { font-family: 'Mulish', sans-serif; font-weight: 600; }
/* "31 %"-utropet -- egen, fremtredende callout (regel 12: "make the
   proprietary spread metric prominent"), erstatter den tidligere
   ren-tekst-raden med samme tall. */
.price-intel-spread-callout { margin-top: 9px; padding: 11px 12px; background: var(--mint-tint); border-radius: 10px; }
.price-intel-spread-callout strong { display: block; font-family: 'Mulish', sans-serif; font-size: 1.3rem; color: var(--mint); line-height: 1.1; }
.price-intel-spread-callout span { display: block; font-size: 0.74rem; color: var(--muted); margin-top: 2px; }
.price-intel-card-note { display: flex; align-items: flex-start; gap: 5px; font-size: 0.72rem; color: var(--muted); margin: 10px 0 0; line-height: 1.45; }
.price-intel-zero-note { margin: 9px 0 0; font-size: 0.7rem; color: var(--muted); line-height: 1.4; }
.price-intel-qty-note { display: flex; align-items: flex-start; gap: 5px; font-size: 0.74rem; color: var(--ink); margin: 10px 0 0; line-height: 1.5; background: var(--amber-tint); border-radius: 8px; padding: 8px 10px; }
.price-intel-frequency-panel { display: none; }
.price-intel-frequency-panel.active { display: block; }
.price-intel-frequency-number { font-family: 'Mulish', sans-serif; font-weight: 600; font-size: 1.55rem; color: var(--ink); }
.price-intel-frequency-description { font-size: 0.8rem; line-height: 1.5; color: var(--muted); margin: 8px 0 12px; }
.price-intel-frequency-bar { display: flex; gap: 2px; height: 10px; border-radius: 999px; overflow: hidden; background: var(--mist); }
.price-intel-frequency-lower { background: #94A3B8; }
.price-intel-frequency-equal { background: #2563EB; }
.price-intel-frequency-higher { background: #CBD5E1; }
.price-intel-frequency-legend { display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 0.7rem; color: var(--muted); margin-top: 9px; }
.price-intel-frequency-label { display: inline-flex; align-items: center; gap: 5px; }
.price-intel-frequency-label i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.price-intel-winners-list { display: flex; flex-direction: column; gap: 7px; }
.price-intel-winner-row { display: grid; grid-template-columns: 80px 1fr auto; align-items: center; gap: 8px; font-size: 0.78rem; }
.price-intel-winner-store { font-weight: 600; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.price-intel-winner-bar { display: block; height: 6px; background: var(--mist); border-radius: 999px; overflow: hidden; }
.price-intel-winner-bar span { display: block; height: 100%; background: var(--orange-dark); border-radius: 999px; }
.price-intel-winner-days { color: var(--muted); white-space: nowrap; font-size: 0.74rem; }
/* 0-dagers-butikker: beholdt synlig (Kai bekreftet dette eksplisitt
   tidligere samme uke -- "viser at de faktisk er sammenlignet"), men n√•
   visuelt dempet (regel 13: "Do not let zero-value merchants create
   visual clutter"). */
.price-intel-winner-row-zero { opacity: 0.5; }
/* "Kj√∏per du flere esker?" -- ren tabell, IKKE et eget kortsett per rad. */
.price-intel-qty-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.price-intel-qty-table th { text-align: left; font-weight: 600; color: var(--muted); font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.02em; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.price-intel-qty-table td { padding: 5px 4px 5px 0; border-bottom: 1px solid var(--border); color: var(--ink); }
.price-intel-qty-table tr:last-child td { border-bottom: none; }
.price-intel-qty-table td:first-child { font-weight: 600; }
.price-intel-qty-table td:nth-child(2) { font-family: 'Mulish', sans-serif; font-weight: 600; }
/* "Kort fortalt" -- diskre konklusjon, ikke en stor bl√• dashboard-boks
   (regel 17: "Do not make it look like an AI response"). */
.price-intel-conclusion { display: none; margin-top: 16px; border-radius: 12px; overflow: hidden; background: var(--blue-tint); }
.price-intel-conclusion.active { display: block; }
.price-intel-summary { display: flex; gap: 10px; align-items: flex-start; padding: 14px 16px; font-size: 0.84rem; line-height: 1.55; color: var(--ink); }
.price-intel-summary strong { display: block; margin-bottom: 2px; color: var(--blue); }
.price-intel-summary-icon { flex-shrink: 0; width: 26px; height: 26px; border-radius: 50%; background: white; display: flex; align-items: center; justify-content: center; font-size: 0.9rem; }
/* Egen-data-stripen (regel 16) -- sm√•, redaksjonelle statistikker med
   tynne skillelinjer, IKKE flere kort. Adaptiv: bygges kun av elementer
   som faktisk har data (se render_price_intelligence()). */
.price-intel-stat-strip { display: flex; flex-wrap: wrap; gap: 12px 0; padding: 14px 16px; background: white; border-top: 1px solid var(--border); }
.price-intel-stat { flex: 1 1 46%; display: flex; align-items: flex-start; gap: 8px; box-sizing: border-box; padding-right: 10px; }
.price-intel-stat svg { width: 15px; height: 15px; color: var(--muted); flex-shrink: 0; margin-top: 2px; }
.price-intel-stat strong { display: block; font-family: 'Mulish', sans-serif; font-size: 0.92rem; color: var(--ink); }
.price-intel-stat span { display: block; font-size: 0.68rem; color: var(--muted); line-height: 1.3; margin-top: 1px; }
/* Footer -- metodikklenke + en √ÜRLIG oppdateringsdato. Bevisst INGEN
   klokkeslett ("kl. HH:MM") slik mockupen viste -- samme l√¶rdom som
   Fase 16 tidligere samme dag (se _price_intel_chart_domain sin
   docstring-nabo lenger opp): en tid-stemplet p√•stand p√• en STATISK
   side blir feil i det √∏yeblikket noen leser siden senere enn
   byggetidspunktet. Bruker i stedet den samme "sist bekreftet
   {dato}"-konvensjonen som resten av siden allerede f√∏lger konsekvent. */
.price-intel-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 0.72rem; color: var(--muted); }
.price-intel-footer a { color: var(--blue); font-weight: 600; text-decoration: none; }
.price-intel-footer-source { display: flex; align-items: center; gap: 6px; }
.price-intel-footer-source svg { width: 13px; height: 13px; flex-shrink: 0; }
@media (min-width: 860px) {
  /* Hele modulen kappet smalere enn siden rundt (v2-redesign runde 2,
     rapport #1: "Hele komposisjonen er for bred og flat... match the
     mockup's compact centered composition") -- IKKE bare grafen. Uten
     dette tak strekker `.price-intel` seg til `.wrap-product` sin fulle
     1280px, og alt inni (metrikkrad, kort, graf) arver den bredden og
     virker "flat"/tynt utspredt uansett hvor mye de enkelte delene
     strammes til. 1000px valgt som et bevisst, tydelig SMALERE tak enn
     siden for √∏vrig -- gir modulen sin egen, synlig sentrerte
     "publisert markedsrapport"-identitet i stedet for √• flyte sammen
     med resten av den brede produktsiden.*/
  .price-intel { padding: 26px 30px; }
  .price-intel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
  .price-intel-head-text p { max-width: 480px; }
  .price-intel-coverage { margin-top: 0; flex-shrink: 0; }
  /* IKKE justify-content:space-between -- det var n√∏yaktig det som ga
     det synlige, "malplasserte" tomrommet mellom siste metrikk-kolonne
     og statuspillen Kai pekte p√• (runde 2, rapport #3: "Stabil pris har
     blitt en stor gr√∏nn boks helt ute til h√∏yre"). R√•dataraden og
     pillen skal sitte SAMMEN med et fast, moderat mellomrom, ikke
     spres ut over hele bredden av en flex-rad. */
  /* Robust topplag: flex-wrap (ingen absolute posisjonering/negative
     marger) -- statuspillen ligger til h√∏yre KUN n√•r den faktisk f√•r
     plass ved siden av metrikkraden, ellers wrapper den ned p√• egen rad,
     venstrejustert, i sin naturlige bredde. Dermed kan den aldri dekke
     metrikktekst, uansett modulbredde eller tekstlengde. */
  .price-intel-primary.active { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 20px 24px; }
  .price-intel-metrics-row { flex: 0 1 auto; flex-wrap: nowrap; min-width: 0; }
  .price-intel-metric-col { flex: 0 0 auto; padding: 0 16px; border-left: 1px solid var(--border); }
  .price-intel-metric-col:first-child, .price-intel-metric-current { border-left: none; padding-left: 0; flex-basis: auto; margin-bottom: 0; }
  .price-intel-status-pill { margin-top: 0; flex: 0 1 270px; min-width: 240px; max-width: 360px; padding: 16px 18px; box-sizing: border-box; }
  .price-intel-value-lg { font-size: 3rem; }
  .price-intel-value { font-size: 1.6rem; }
  .price-intel-metric-label { font-size: 0.8rem; }
  .price-intel-metric-sublabel { font-size: 0.72rem; }
  .price-intel-metric-desc { font-size: 0.7rem; max-width: 185px; }
  /* Smal modul (smal desktop/tablet): metrikkene g√•r i et 3-kolonne-rutenett
     under "Pris n√•" (som mobil, uten skillelinjer), og statuspillen tar
     egen rad under -- venstrejustert, aldri bredere enn 420px. */
  @container pintel (max-width: 940px) {
    .price-intel-metrics-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px 0; width: 100%; }
    .price-intel-metric-current { grid-column: 1 / -1; }
    .price-intel-metric-col, .price-intel-metric-col:first-child { padding: 0 14px 0 0; border-left: none; }
    .price-intel-status-pill { flex: 1 1 100%; max-width: 420px; }
  }
  /* Grafens "hylle" -- 680px, dvs. grafens EGEN native viewBox-bredde
     (`_render_price_intelligence_chart()` sin `width=680`), ikke et
     vilk√•rlig tall -- runde 2, rapport #3: "the chart is still too
     large... the attached image is the sizing reference", ikke en
     strekking av hele det (n√• smalere) modulinnholdet. Innenfor et
     ~940px innholdsomr√•de (1000px modul minus padding) gir 680px synlig,
     bevisst luft p√• begge sider, som i mockupen. */
  .price-intel-chart-shell { max-width: 980px; margin-inline: auto; padding: 14px 18px 10px; }
  /* Kortene kapper n√• i .price-intel-card selv (flex-basis 260px, se
     over) -- her settes kun et TAK per kort (runde 2, rapport #4/#6) slik
     at 2 eller 3 kort forblir sin egen, tiltenkte bredde og heller
     etterlater synlig luft i raden (via justify-content:center) enn √•
     strekkes til √• fylle 100 % n√•r et kort (typisk "Kj√∏per du flere
     esker?") er betinget skjult. */
  .price-intel-card { flex: 0 1 calc((100% - 24px) / 3); max-width: calc((100% - 24px) / 3); }
  .price-intel-stat { flex: 1 1 0; padding: 0 14px; border-left: 1px solid var(--border); }
  .price-intel-stat:first-child { border-left: none; padding-left: 0; }
  .price-intel-stat-strip { flex-wrap: nowrap; padding: 16px 20px; }
}

/* Price Intelligence Gold Standard v1 ‚Äî ChatGPT branch, 2026-10-05.
   Presentation-only override layer. The existing calculation engine,
   offer engine, affiliate logic and shared brand/series chart rules stay intact. */
.price-intel{
  max-width:none;
  padding:22px 18px;
  border-radius:18px;
  box-shadow:none;
}
.price-intel-head{margin-bottom:24px}
.price-intel-eyebrow{font-size:.68rem;letter-spacing:.11em}
.price-intel-head-text h2{font-size:1.45rem;letter-spacing:-.02em}
.price-intel-head-text p{max-width:620px;font-size:.86rem;line-height:1.6}
.price-intel-coverage{border:0;background:transparent;padding:0;font-size:.73rem}
.price-intel-primary{padding:0 0 20px;border-bottom:1px solid var(--border)}
.price-intel-metrics-row{gap:18px 0}
.price-intel-value-lg,.price-intel-value{letter-spacing:-.035em}
.price-intel-metric-label{font-weight:500}
.price-intel-metric-desc{display:none}
.price-intel-status-pill{border:0;box-shadow:none}
.price-intel-period-tabs{margin:18px 0 20px}
.price-intel-chart-shell{border:0;border-radius:0;padding:0;max-width:none;width:100%}
.price-intel-chart-toolbar{padding:0 2px 8px;border-bottom:1px solid var(--border);margin-bottom:8px}
.price-intel-chart-toolbar-badge{border:0;background:transparent;padding:0}
.price-intel-chart .price-history-chart{border:0;border-radius:0}

.price-intel .price-history-line{stroke-width:1.3;vector-effect:non-scaling-stroke}
.price-intel .store-chart-controls{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin:18px 0 8px}
.price-intel .store-chart-periods{margin-left:auto;text-align:right}
.price-intel .store-chart-periods .price-intel-period-tabs{justify-content:flex-end;margin:0 0 10px}
.price-intel .store-chart-caption{font-size:.76rem;color:var(--muted);margin:0}
.price-intel .store-chart-picker{position:relative;flex-shrink:0;font-size:.8rem;z-index:5}
.price-intel .store-chart-picker summary{list-style:none;display:flex;align-items:center;justify-content:space-between;gap:18px;cursor:pointer;padding:9px 15px;border:1px solid var(--border);border-radius:999px;background:white}
.price-intel .store-chart-picker summary::after{content:"";width:7px;height:7px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:translateY(-2px) rotate(45deg);flex-shrink:0}
.price-intel .store-chart-picker summary::-webkit-details-marker{display:none}
.price-intel .store-chart-options{position:absolute;left:0;top:44px;min-width:220px;max-height:320px;overflow:auto;padding:8px;border:1px solid var(--border);border-radius:12px;background:white;box-shadow:0 8px 24px #0b25451a}
.price-intel .store-chart-options label{display:flex;gap:10px;align-items:center;padding:10px 8px;cursor:pointer}
.price-intel .store-chart-options input{accent-color:var(--blue);width:17px;height:17px}
.price-intel .store-chart-selected{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.price-intel .store-chart-selected[hidden],.price-intel .store-chart-picker[hidden]{display:none}
.price-intel .store-chart-chip{display:inline-flex;align-items:center;gap:7px;border:0;border-radius:999px;background:var(--mist);color:var(--ink);padding:7px 10px;font:inherit;font-size:.76rem;cursor:pointer}
.price-intel .store-chart-swatch{width:8px;height:8px;border-radius:50%;display:inline-block}
.price-intel .price-intel-chart-wrap{position:relative}
.price-intel .store-chart-tooltip{position:absolute;z-index:4;pointer-events:none;background:white;border:1px solid var(--border);border-radius:12px;box-shadow:0 5px 18px #0b25451a;padding:12px 15px;color:var(--ink);font-size:.8rem;max-width:230px}
.price-intel .store-chart-tooltip strong{display:block;font-size:1rem;margin:5px 0}
.price-intel .store-chart-tooltip span{display:block}
.price-intel .store-chart-tooltip[hidden]{display:none}
.price-intel .store-chart-endpoints{position:absolute;right:8px;top:0;box-sizing:border-box;color:var(--ink)}
.price-intel .store-chart-endpoints-heading{font-size:11px;color:var(--muted);padding:20px 10px 0}
.price-intel .store-chart-endpoint{position:absolute;left:0;right:0;height:50px;box-sizing:border-box;border:1px solid var(--border);border-radius:10px;background:#fff;box-shadow:0 2px 8px #0b254505;display:grid;grid-template-columns:minmax(0,1fr) auto;align-content:center;column-gap:8px;padding:7px 10px 7px 17px;font-size:11px}
.price-intel .store-chart-endpoint::before{content:"";position:absolute;left:6px;top:8px;bottom:8px;width:3px;border-radius:3px;background:var(--store-color)}
.price-intel .store-chart-endpoint-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;align-self:center}
.price-intel .store-chart-endpoint strong{font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}
.price-intel .store-chart-endpoint time{grid-column:1/-1;color:var(--muted);font-size:10px;margin-top:3px}
.price-intel .store-chart-endpoint.is-winner{height:116px;display:flex;flex-direction:column;justify-content:center;gap:4px;padding:12px 18px;border-color:#ffdfc5;background:linear-gradient(120deg,#fffaf5,#fff5eb)}
.price-intel .store-chart-endpoint.is-winner .store-chart-endpoint-name{align-self:auto;font-size:12px;color:var(--muted)}
.price-intel .store-chart-endpoint.is-winner strong{font-size:25px;line-height:1.2}
.price-intel .store-chart-endpoint-winner{font-size:12px;font-weight:600}
.price-intel .store-chart-endpoint.is-winner time{font-size:11px;margin-top:0}
.price-intel .store-chart-endpoints.is-mobile{position:static;width:100%;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
.price-intel .store-chart-endpoints.is-mobile .store-chart-endpoints-heading{grid-column:1/-1;padding:0 2px 2px}
.price-intel .store-chart-endpoints.is-mobile .store-chart-endpoint{position:relative;height:auto;min-height:52px}
.price-intel .store-chart-endpoints.is-mobile .store-chart-endpoint.is-winner{grid-column:1/-1;display:grid;grid-template-columns:1fr auto;gap:2px 12px;min-height:72px;padding:10px 16px}
.price-intel .store-chart-endpoints.is-mobile .store-chart-endpoint.is-winner strong{grid-column:2;grid-row:1/3;align-self:center;font-size:23px}
.price-intel .store-chart-endpoints.is-mobile .store-chart-endpoint.is-winner time{grid-column:1/-1}
.price-intel .store-chart-keyboard{width:100%;margin:8px 0;accent-color:var(--orange-dark)}
.price-intel .store-chart-keyboard:not(:focus){position:absolute;width:1px;height:1px;clip-path:inset(50%);overflow:hidden}
@media(max-width:600px){.price-intel .store-chart-controls{flex-direction:column;gap:12px}.price-intel .store-chart-periods{width:100%;text-align:left}.price-intel .store-chart-periods .price-intel-period-tabs{justify-content:flex-start}.price-intel .store-chart-picker{width:100%}.price-intel .store-chart-options{width:100%}.price-intel .store-chart-chip{min-height:40px}}
.price-intel-chart-mobile{display:none}
.price-intel-chart-desktop{display:block}
.price-intel-cards{margin-top:30px;gap:0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.price-intel-card{
  border:0;border-radius:0;padding:22px 24px;background:transparent;
  max-width:none!important;flex:1 1 50%;
}
.price-intel-card+.price-intel-card{border-left:1px solid var(--border)}
.price-intel-winners-panel{display:none}
.price-intel-winners-panel.active{display:block}
.price-intel-card h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.055em}
.price-intel-card-head-note{font-size:.68rem}
.price-intel-card-row{font-size:.82rem;padding:4px 0}
.price-intel-spread-callout{background:transparent;border-radius:0;padding:14px 0 0;margin-top:12px;border-top:1px solid var(--border)}
.price-intel-spread-callout strong{font-size:2rem;color:var(--ink);letter-spacing:-.04em}
.price-intel-winner-bar{height:5px}
.price-intel-conclusion{margin-top:28px;border-radius:14px;background:#f3f7fb;border:1px solid #e6edf4}
.price-intel-summary{padding:18px 20px}
.price-intel-summary strong{color:var(--ink);font-size:.9rem}
.price-intel-summary-icon{display:none}
.price-intel-stat-strip{padding:16px 20px;background:rgba(255,255,255,.72)}
.price-intel-stat svg{display:none}
.price-intel-stat strong{font-size:1rem;letter-spacing:-.02em}
.price-intel-stat span{font-size:.69rem}
.price-intel-history-data{margin-top:30px;padding-top:26px;border-top:1px solid var(--border)}
.price-intel-section-kicker{margin:0 0 4px;font-size:.67rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--blue)}
.price-intel-section-head h3{margin:0;font-family:'Mulish',sans-serif;font-size:1.05rem;color:var(--ink)}
.price-intel-section-head p{margin:5px 0 0;max-width:680px;font-size:.76rem;line-height:1.5;color:var(--muted)}
.price-intel-history-table-wrap{margin-top:14px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.price-intel-history-table{width:100%;border-collapse:collapse;min-width:760px;font-size:.76rem}
.price-intel-history-table th,.price-intel-history-table td{padding:10px 12px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
.price-intel-history-table thead th{font-size:.64rem;text-transform:uppercase;letter-spacing:.045em;color:var(--muted);font-weight:600}
.price-intel-history-table th:first-child,.price-intel-history-table td:first-child{text-align:left}
.price-intel-history-table tbody th{font-weight:650;color:var(--ink)}
.price-intel-history-table tbody td{font-family:'Mulish',sans-serif;color:var(--ink)}
/* Smal desktop (modulens innhold <= 800px, dvs. ca. 860-1010px viewport): den
   8-kolonners tabellen har min-width 760px og ville scrollet sidelengs. Her
   komprimeres den i stedet: ingen min-width, tettere padding, mindre
   kolonneoverskrifter som f√•r brytes over to linjer. Gjelder kun >=860px
   (mobil <860px bruker det stablede kort-oppsettet under). */
@media (min-width:860px){
  @container pintel (max-width:800px){
    .price-intel-history-table{min-width:0}
    .price-intel-history-table th,.price-intel-history-table td{padding:9px 5px}
    .price-intel-history-table thead th{font-size:.58rem;letter-spacing:.02em;white-space:normal;line-height:1.25;vertical-align:bottom}
    .price-intel-history-table td{font-size:.72rem}
  }
}
.price-intel-footer{margin-top:18px}

@media (min-width:860px){
  .price-intel{padding:32px 36px}
  .price-intel-head{align-items:flex-start}
  .price-intel-primary.active{gap:34px;align-items:center}
  .price-intel-metrics-row{justify-content:flex-start!important}
  .price-intel-metric-current{min-width:170px}
  .price-intel-metric-col{padding:0 22px}
  .price-intel-value-lg{font-size:3.2rem}
  .price-intel-value{font-size:1.55rem}
  .price-intel-status-pill{width:260px;padding:14px 16px}
  .price-intel-chart-shell{max-width:none}
  .price-intel-card{flex:0 1 calc((100% - 24px)/3);max-width:385px!important}
  .price-intel-stat-strip{gap:0}
  .price-intel-history-details>summary{display:none}
}
@media (max-width:859px){
  .price-intel{margin-top:22px;padding:18px 14px;border-radius:14px}
  .price-intel-head{margin-bottom:18px}
  .price-intel-head-text h2{font-size:1.25rem}
  .price-intel-coverage{margin-top:10px}
  .price-intel-primary.active{display:block}
  .price-intel-metric-current{flex:1 1 100%;padding-bottom:10px}
  .price-intel-value-lg{font-size:2.45rem}
  .price-intel-value{font-size:1.2rem}
  .price-intel-metric-col{flex:1 1 50%;padding:8px 12px 8px 0;border:0}
  .price-intel-metric-col:nth-child(even){padding-left:12px;border-left:1px solid var(--border)}
  .price-intel-status-pill{width:auto;margin-top:12px}
  .price-intel-period-tabs{flex-wrap:wrap;overflow:visible;gap:8px;padding-bottom:0}
  .price-intel-period-tab{flex:0 0 auto;min-height:40px;padding:8px 13px}
  .price-intel-period-tab:disabled{display:none}
  .price-intel-chart-toolbar-badge{display:none}
  .price-intel-chart-desktop{display:none}
  .price-intel-chart-mobile{display:block;width:100%;height:auto}
  .price-intel-chart-wrap{width:100%}
  .price-intel-chart-mobile .price-history-axis-label-x{display:block!important}
  .price-intel-cards{display:block;margin-top:24px}
  .price-intel-card{width:100%;max-width:none!important;padding:18px 4px}
  .price-intel-card+.price-intel-card{border-left:0;border-top:1px solid var(--border)}
  .price-intel-winner-row{grid-template-columns:72px 1fr auto}
  .price-intel-conclusion{margin-top:22px}
  .price-intel-summary{padding:16px}
  .price-intel-stat-strip{display:grid;grid-template-columns:1fr 1fr;gap:14px 18px;padding:16px}
  .price-intel-stat{display:block;padding:0;border:0}
  .price-intel-history-data{margin-top:24px;padding-top:22px}
  .price-intel-history-details{margin-top:12px}
  .price-intel-history-details>summary{cursor:pointer;list-style:none;display:flex;align-items:center;justify-content:space-between;min-height:42px;padding:10px 0;font-size:.78rem;font-weight:650;color:var(--blue)}
  .price-intel-history-details>summary::-webkit-details-marker{display:none}
  .price-intel-history-details>summary::after{content:"+";font-size:1.1rem;color:var(--muted)}
  .price-intel-history-details[open]>summary::after{content:"‚Äì"}
  .price-intel-history-details:not([open])>.price-intel-history-table-wrap{display:none}
  .price-intel-history-table-wrap{overflow:visible}
  .price-intel-history-table{min-width:0;display:block}
  .price-intel-history-table thead{display:none}
  .price-intel-history-table tbody{display:block}
  .price-intel-history-table tr{display:grid;grid-template-columns:1fr 1fr;gap:9px 16px;padding:14px 0;border-bottom:1px solid var(--border)}
  .price-intel-history-table th,.price-intel-history-table td{display:block;padding:0;border:0;text-align:left!important;white-space:normal}
  .price-intel-history-table tbody th{grid-column:1/-1;font-family:'Mulish',sans-serif;font-size:.88rem}
  .price-intel-history-table td{font-size:.78rem}
  .price-intel-history-table td:nth-child(2)::before{content:"Laveste";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(3)::before{content:"H√∏yeste";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(4)::before{content:"Median";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(5)::before{content:"Prisspenn";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(6)::before{content:"Prisendringer";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(7)::before{content:"Vinnerbytter";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(8)::before{content:"Butikker billigst";display:block;font-family:Mulish,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
}

"""

# Navnet er historisk (fonter) - inneholder n√• ogs√• favicon-taggene, satt
# inn her bevisst fremfor √• r√∏re alle 9 sidetypenes <head> hver for seg.
# favicon-o.png er den oransje "O"-en (ring + ansiktssilhuett) besk√•ret ut
# av static/logo.png, med hvit bakgrunn gjort gjennomsiktig - se historikk
# 2026-08-11.
# Fontene er selv-hostet (static/fonts/, @font-face-regler i SHARED_STYLE)
# i stedet for √• lastes fra Google Fonts -- unng√•r to eksterne DNS-oppslag +
# en render-blokkerende stylesheet-foresp√∏rsel per sidevisning (2026-08-18).
# Kun "latin"-delmengden (U+0000-00FF m.fl.) er lastet ned -- dekker √¶√∏√•
# (innenfor U+0000-00FF) og all norsk tekst p√• siden, samme reelle
# tegndekning siten allerede hadde via Google Fonts sin "latin"-delmengde.
FONT_LINKS = """<link rel="preload" href="/static/fonts/mulish-latin-variable.woff2" as="font" type="font/woff2" crossorigin>
<link rel="icon" type="image/png" href="/static/favicon-o.png">
<link rel="apple-touch-icon" href="/static/favicon-o.png">
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "WebSite", "name": "Kontaktlinser.no", "url": "https://kontaktlinser.no", "description": "Uavhengig prissammenligningstjeneste for kontaktlinser, linsev√¶ske og √∏yedr√•per fra norske nettbutikker.", "inLanguage": "nb", "publisher": {"@type": "Organization", "name": "Kontaktlinser.no", "url": "https://kontaktlinser.no", "logo": {"@type": "ImageObject", "url": "https://kontaktlinser.no/static/logo.png"}, "sameAs": ["https://www.facebook.com/kontaktlinser.no/"]}}</script>"""

# GTM lastes IKKE lenger automatisk - kun definert her, faktisk kalt av
# CONSENT_SCRIPT etter samtykke (lagret fra forrige bes√∏k) eller n√•r bruker
# trykker "Godta alle"/"Lagre valg" med statistikk p√• i samtykke-banneret.
# Ingen <noscript>-fallback lenger: uten JS kan vi ikke innhente samtykke
# interaktivt, og skal derfor ikke sette GTM-cookien i det hele tatt for de
# bes√∏kende - se CONSENT_BANNER_HTML/CONSENT_SCRIPT og /personvern/.
GTM_HEAD = """<!-- Google Tag Manager (lastes kun etter samtykke - se CONSENT_SCRIPT) -->
<script>
function __loadGTM() {
  if (window.__gtmLoaded) return;
  window.__gtmLoaded = true;
  (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
  new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
  j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
  'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
  })(window,document,'script','dataLayer','GTM-5RZFVNQM');
}
</script>
<!-- End Google Tag Manager -->"""

# Midtstilt popup (ikke bunn-banner), modellert etter Prisjakts cookie-flyt
# (skjermbilder delt av bruker 2026-08-11): generisk "X samarbeidspartnere"
# i hovedteksten (ikke navngi Tradedoubler/Awin/Adtraction der), med en egen
# "Innstillinger"-visning som har per-kategori-toggles + en nedtonet "Vis
# alle leverand√∏rer"-lenke som avsl√∏rer de faktiske navnene. Selve
# /personvern/-siden navngir dem fortsatt √•pent (det er nettopp poenget med
# den siden). To kategorier, ikke bundlet i ett avkryssingsfelt (Datatilsynets
# krav): statistikk (GTM) og affiliate-sporing (settes av nettverkets/
# forhandlerens eget domene n√•r du klikker en tilbudslenke, ikke av oss
# direkte, men du skal likevel kunne velge det bort p√• forh√•nd).
CONSENT_BANNER_HTML = """<div id="consent-overlay" class="consent-overlay" hidden>
  <div class="consent-modal" role="dialog" aria-modal="true" aria-labelledby="consent-title">
    <div id="consent-step-main">
      <h2 id="consent-title">Vi bruker cookies p√• Kontaktlinser.no</h2>
      <p class="consent-text">
        Vi og v√•re samarbeidspartnere bruker cookies til statistikk og for √•
        registrere n√•r et kj√∏p hos en forhandler skjedde via en lenke fra oss,
        slik at vi kan motta provisjon. Du velger selv, og kan endre valget
        n√•r som helst. <a href="/personvern/">Mer informasjon</a>.
      </p>
      <div class="consent-actions">
        <button type="button" id="consent-customize" class="consent-btn consent-btn-secondary">Innstillinger</button>
        <button type="button" id="consent-reject" class="consent-btn consent-btn-secondary">Kun n√∏dvendige</button>
        <button type="button" id="consent-accept" class="consent-btn consent-btn-primary">Godta</button>
      </div>
    </div>
    <div id="consent-step-settings" hidden>
      <h2>Cookieinnstillinger</h2>
      <p class="consent-text">Velg hvilke typer cookies du godtar. N√∏dvendige cookies kan ikke sl√•s av.</p>

      <div class="consent-category">
        <div class="consent-category-row">
          <span>N√∏dvendig</span>
          <input type="checkbox" class="consent-toggle" checked disabled>
        </div>
      </div>
      <div class="consent-category">
        <div class="consent-category-row">
          <span>Statistikk</span>
          <input type="checkbox" class="consent-toggle" id="consent-stats" checked>
        </div>
        <p class="consent-category-desc">M√•ler trafikk og bruk av siden, slik at vi vet hva som faktisk er nyttig.</p>
      </div>
      <div class="consent-category">
        <div class="consent-category-row">
          <span>Affiliate-sporing</span>
          <input type="checkbox" class="consent-toggle" id="consent-affiliate" checked>
        </div>
        <p class="consent-category-desc">Registrerer at et kj√∏p kom via en lenke fra oss, slik at forhandleren kan betale riktig provisjon.</p>
        <button type="button" id="consent-toggle-providers" class="consent-link-btn">Vis alle leverand√∏rer</button>
        <ul id="consent-providers-list" class="consent-providers-list" hidden>
          <li>Tradedoubler</li>
          <li>Awin</li>
          <li>Adtraction</li>
        </ul>
      </div>

      <div class="consent-actions" style="margin-top:18px;">
        <button type="button" id="consent-back" class="consent-btn consent-btn-secondary">Avbryt</button>
        <button type="button" id="consent-save" class="consent-btn consent-btn-primary">Lagre valg</button>
      </div>
    </div>
  </div>
</div>"""

CONSENT_SCRIPT = """<script>
(function () {
  var KEY = 'kl_consent_v1';

  function getConsent() {
    try { return JSON.parse(localStorage.getItem(KEY)); } catch (e) { return null; }
  }

  function apply(c) {
    window.__klConsent = c;
    if (c.stats && window.__loadGTM) window.__loadGTM();
  }

  function saveConsent(c) {
    c.timestamp = new Date().toISOString();
    try { localStorage.setItem(KEY, JSON.stringify(c)); } catch (e) {}
    apply(c);
  }

  var overlay = document.getElementById('consent-overlay');
  var existing = getConsent();
  if (existing) {
    apply(existing);
  } else if (overlay) {
    overlay.hidden = false;
  }

  if (!overlay) return;

  var stepMain = document.getElementById('consent-step-main');
  var stepSettings = document.getElementById('consent-step-settings');

  function hide() { overlay.hidden = true; }
  function showSettings() { stepMain.hidden = true; stepSettings.hidden = false; }
  function showMain() { stepSettings.hidden = true; stepMain.hidden = false; }

  document.getElementById('consent-accept').addEventListener('click', function () {
    saveConsent({ stats: true, affiliate: true });
    hide();
  });
  document.getElementById('consent-reject').addEventListener('click', function () {
    saveConsent({ stats: false, affiliate: false });
    hide();
  });
  document.getElementById('consent-customize').addEventListener('click', showSettings);
  document.getElementById('consent-back').addEventListener('click', showMain);
  document.getElementById('consent-toggle-providers').addEventListener('click', function () {
    var list = document.getElementById('consent-providers-list');
    list.hidden = !list.hidden;
  });
  document.getElementById('consent-save').addEventListener('click', function () {
    saveConsent({
      stats: document.getElementById('consent-stats').checked,
      affiliate: document.getElementById('consent-affiliate').checked
    });
    hide();
  });
})();

// Utg√•ende-klikk-sporing (2026-08-31): pusher ETT dataLayer-event per
// klikk p√• en tilbudslenke (data-retailer er satt av render_offer_card/
// render_winner_widget), uansett om forhandleren har avtale eller ikke --
// gir en per-forhandler klikkoversikt selv for de uten avtale, bl.a. som
// dokumentasjon n√•r vi ber om en avtale senere. Trygt √• kj√∏re UBETINGET
// (ikke bak samtykke-sjekk her): window.dataLayer.push() gj√∏r ingenting i
// seg selv, det bare legger til i et array i minnet -- selve sendingen
// skjer f√∏rst n√•r GTM.js er lastet, og det skjer FORTSATT kun etter
// samtykke (se apply()/__loadGTM over). Uten samtykke blir arrayet aldri
// lest av noe, og forsvinner med siden ved neste navigasjon.
//
// Forhandlerlenker √•pnes i ny fane (target="_blank", se render_offer_card/
// render_winner_widget) -- brukeren beholder Kontaktlinser.no √•pent og kan
// sammenligne flere butikker uten √• miste sammenligningen, samme m√∏nster
// bekreftet hos andre prissammenligningstjenester. Siden fanen med DENNE
// siden ALDRI navigerer bort, er det ingen kappl√∏p mot GTM-sendingen lenger
// -- vanlig window.open()/target="_blank"-navigering kan skje helt normalt,
// vi trenger bare √• pushe dataLayer-eventet ved siden av.
//
// eventCallback/eventTimeout-m√∏nsteret under er likevel beholdt som
// fallback for en lenke uten target="_blank" (skulle en s√•nn dukke opp et
// sted): tilbudslenker som navigerer i SAMME fane rekker ofte √• forlate
// siden F√òR GTM faktisk har sendt hendelsen til GA4 -- bekreftet i praksis
// 2026-08-31 (klikk ga aldri noe utslag i sanntidsrapporten). preventDefault()
// + maks 300ms forsinket navigering l√∏ser det for det tilfellet.
window.dataLayer = window.dataLayer || [];
document.addEventListener('click', function (e) {
  var link = e.target.closest('a[data-retailer]');
  if (!link) return;
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

  if (link.target === '_blank') {
    // Nettleseren h√•ndterer selve navigeringen til den nye fanen -- vi
    // pusher bare sporingseventet ved siden av, ingen forsinkelse n√∏dvendig.
    window.dataLayer.push({
      event: 'outbound_click',
      retailer: link.getAttribute('data-retailer'),
      affiliate: link.getAttribute('data-affiliate') === '1'
    });
    return;
  }

  e.preventDefault();
  var navigated = false;
  function go() {
    if (navigated) return;
    navigated = true;
    window.location.href = link.href;
  }
  window.dataLayer.push({
    event: 'outbound_click',
    retailer: link.getAttribute('data-retailer'),
    affiliate: link.getAttribute('data-affiliate') === '1',
    eventCallback: go,
    eventTimeout: 300
  });
  setTimeout(go, 300);
});
</script>"""

# BRAND_LOGOS/_brand_badge flyttet hit (fra sin opprinnelige plass lenger
# ned i filen) fordi TOPBAR_HTML under n√• viser ekte merkelogoer i
# dropdownene -- en modulniv√•-konstant kan ikke referere noe som f√∏rst
# defineres senere i filen.
#
# N√∏ytral, beskrivende bruk for √• identifisere hvilket produkt/merke det
# faktisk er snakk om - selve definisjonen av nominativ varemerkebruk.
#
# 2026-08-30: 16 merker (Air Optix, Avaira, Biofinity, Biomedics, Biotrue,
# Clariti, Dailies, FreshLook, MyDay, Precision1, Precision7, Proclear,
# PureVision, SofLens, TOTAL30, ULTRA) hadde en periode en logo besk√•ret
# fra et lisensiert produktbilde (se logo_sources.json-kommentaren og
# git-historikken for teknikken) -- FJERNET igjen samme dag etter at
# bruker testet resultatet live og fant kvaliteten for d√•rlig (utvasket
# kontrast, beskj√¶ringsartefakter som en gjenv√¶rende stripe/strek fra
# emballasjedesignet). Disse 16 har derfor bevisst INGEN logofil her n√•,
# og faller tilbake til den vanlige initial-badgen inntil en ekte
# offisiell kilde er funnet (se /vilkar/-diskusjonen om ECP-portaler --
# Alcon/CooperVision/Bausch+Lomb sine er alle innloggingssperret for
# fagpersoner, i motsetning til Acuvue sin √•pne kilde under). Ikke legg
# disse tilbake med samme beskj√¶ringsteknikk uten en tydelig kvalitets-
# forbedring f√∏rst.
BRAND_LOGOS = {
    "acuvue": ("acuvue.png", False),
    "adore": ("adore.png", False),
}


def _brand_badge(brand_slug: str, brand_label: str) -> tuple[str, str]:
    """Returnerer (ekstra CSS-klasse for badge-sirkelen, innhold i den) -
    logo n√•r vi har en, ellers samme initial-fallback som f√∏r."""
    entry = BRAND_LOGOS.get(brand_slug)
    if not entry:
        return "", escape(brand_label[:2].upper())
    filename, dark_bg = entry
    img = f'<img class="brand-logo-img" src="/static/logos/{filename}" alt="" loading="lazy">'
    return ("has-logo has-logo-dark" if dark_bg else "has-logo"), img


# Samme ikonsett/fargepalett/undertekster som forsidens kategori-rader
# (render_home_page) -- flyttet til modulniv√• slik at TOPBAR_HTML sin
# Kontaktlinser-dropdown kan gjenbruke n√∏yaktig samme visuelle spr√•k uten
# √• finne opp et nytt sett eller duplisere ikonene. IKKE mint her,
# reservert for "laveste pris" andre steder p√• siden.
CATEGORY_ICONS = {
    "dagslinser": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke-linecap="round"/>',
    "manedslinser": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "toriske-linser": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.6"/>',
    "fargede-linser": '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16" fill="currentColor" stroke="none" opacity="0.35"/>',
    "multifokale-linser": '<circle cx="9" cy="9" r="5"/><circle cx="15" cy="15" r="5"/>',
}
CATEGORY_COLORS = {
    "manedslinser": "blue",
    "dagslinser": "amber",
    "toriske-linser": "sky",
    "fargede-linser": "lavender",
    "multifokale-linser": "coral",
}
# Bakgrunnsbilde per kategori (static/categories/bg-{navn}-{320,613}.webp)
CATEGORY_BG = {
    "manedslinser": "maaned",
    "dagslinser": "dag",
    "toriske-linser": "toriske",
    "fargede-linser": "fargede",
    "multifokale-linser": "multifokale",
}
CATEGORY_TAGLINES = {
    "manedslinser": "Popul√¶r og kostnadseffektiv",
    "dagslinser": "Friske linser hver dag",
    "toriske-linser": "For deg med astigmatisme",
    "fargede-linser": "Endre eller forsterk √∏yefargen",
    "multifokale-linser": "For n√¶r, mellom og fjern",
}

# Kort, faktabasert "hva er X"-forklaring per kategori -- vises i en egen
# boks p√• kategorisiden (2026-09-05, del av kategorisideredesignet). Samme
# forsiktige stil som GUIDE_CONTENT: generelle, godt etablerte fakta, ingen
# spesifikke medisinske r√•d. "les_mer_slug" er bevisst IKKE hardkodet til √©n
# fast guide -- render_category_page faller tilbake til f√∏rste guide i
# kategoriens egen guides-liste hvis ingen egen verdi er satt her.
CATEGORY_EXPLAINERS = {
    "dagslinser": "Dagslinser, ogs√• kalt endagslinser eller 1-dagslinser, brukes √©n dag og kastes etter bruk. De gir god hygiene, h√∏y komfort og krever ikke rengj√∏ring eller oppbevaring i linsev√¶ske.",
    "manedslinser": "M√•nedslinser brukes i inntil 30 dager (f√∏lg alltid optikerens anbefaling) f√∏r de byttes ut, og rengj√∏res og oppbevares i linsev√¶ske mellom hver bruk. Ofte rimeligere per dag enn dagslinser.",
    "toriske-linser": "Toriske linser er utformet for √• korrigere astigmatisme (skjevhet i hornhinnen) i tillegg til vanlig n√¶r- eller langsynthet. De har en spesiell form som gj√∏r at de ikke roterer fritt i √∏yet.",
    "fargede-linser": "Fargede kontaktlinser endrer eller forsterker √∏yenfargen, og finnes b√•de med og uten styrke. F√∏lg alltid bruksanvisningen n√∏ye, ogs√• for linser uten synskorrigering.",
    "multifokale-linser": "Multifokale linser korrigerer alderssyn (presbyopi) ved √• kombinere flere styrker i samme linse, slik at du kan se skarpt p√• flere avstander uten lesebriller.",
}

_SHIELD_ICON = '<path d="M12 3l7 3v5c0 5-3.2 7.8-7 9-3.8-1.2-7-4-7-9V6z"/><path d="M9 12l2 2 4-4"/>'
_BUILDING_ICON = '<path d="M3 21V10l6-4 6 4v11"/><path d="M9 21v-5h4v5"/><path d="M15 21V13l6-3v11"/>'


def _mega_link_row(icon_svg: str, label: str, sublabel: str, href: str) -> str:
    """Rad med lite ikon + tittel + undertekst + pil -- til 'Nyttig √•
    vite'-listen i Merker-dropdownen. Alle href-er som bruker denne M√Ö
    peke til en side som faktisk finnes -- ikke gjett."""
    return f'''<a class="mega-link-row" href="{href}">
          <span class="mega-link-row-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon_svg}</svg></span>
          <span class="mega-link-row-text"><span class="mega-link-row-label">{label}</span><span class="mega-link-row-sub">{sublabel}</span></span>
          <svg class="mega-link-row-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
        </a>'''


# Kontaktlinser-dropdownen (2026-09-29) -- Kai viste Lensway sin
# tilsvarende meny som referanse: "slik som her under kontaktlinser.no
# gj√∏res mye mer minimalistisk n√•r man klikker p√• kontaktlinser" --
# erstattet den tidligere rike 3-kolonners menyen (fargede ikon-rader,
# merke-logo-kort, et bakgrunnsbilde-promo-kort) med rene, korte
# tekstlenke-lister, samme minimalistiske stil som Lensway sin "Type"/
# "Varemerke"-meny. Begge datalistene (_MEGA_CATEGORIES/_MEGA_TOP_BRANDS)
# er UENDRET -- kun rendringen er ny (plain `.mega-menu-link` i stedet for
# ikon-rader/logo-kort).
_MEGA_TOP_BRANDS = [
    ("biofinity", "Biofinity"), ("acuvue", "Acuvue"), ("air-optix", "Air Optix"),
    ("dailies", "Dailies"), ("precision1", "Precision1"), ("biotrue", "Biotrue"),
]
_MEGA_TOP_BRANDS_PLAIN_HTML = "\n        ".join(
    f'<a class="mega-menu-link" href="/merke/{slug}/">{escape(name)}</a>' for slug, name in _MEGA_TOP_BRANDS
)

_MEGA_CATEGORIES = [
    ("dagslinser", "Dagslinser"), ("manedslinser", "M√•nedslinser"),
    ("toriske-linser", "Toriske linser"), ("fargede-linser", "Fargede linser"),
    ("multifokale-linser", "Multifokale linser"),
]
_MEGA_CATEGORY_LINKS_HTML = "\n        ".join(
    f'<a class="mega-menu-link" href="/kontaktlinser/{slug}/">{escape(label)}</a>' for slug, label in _MEGA_CATEGORIES
)

# S√∏keboksen i toppmenyen (2026-09-27, brukerens eget √∏nske om at den skal
# passe visuelt til resten av menyen -- "lik h√∏yde", alts√• samme skriftst√∏rrelse
# som menyteksten) er BEVISST bygget med de samme klassenavnene
# (search-row/search-input/search-icon/search-btn/search-suggestions) som
# LENS_SEARCH_STYLE/LENS_SEARCH_JS allerede definerer for forsiden/guide-
# sidene -- fungerer derfor med N√òYAKTIG samme JS uten en eneste ny linje kode,
# kun en mer spesifikk CSS-overstyring for selve st√∏rrelsen (samme m√∏nster som
# .guide-cta .search-input allerede bruker for SIN variant).
# Vises p√• ALLE sider UNNTATT forsiden (som har sin egen, st√∏rre s√∏keboks i
# heroen) -- derfor to konstanter bygget fra samme funksjon i stedet for to
# hardkodede kopier av hele menyen.
_TOPBAR_SEARCH_HTML = """<form class="topbar-search search-row" id="topbar-search-panel" role="search" action="#" onsubmit="return false;">
    <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/></svg>
    <label for="topbar-lens-search" class="visually-hidden" style="position:absolute;left:-9999px;">S√∏k etter linse eller merke</label>
    <input type="search" id="topbar-lens-search" class="search-input" placeholder="S√∏k etter linse eller merke" autocomplete="off">
    <button type="button" class="search-btn">S√∏k</button>
    <div class="search-suggestions"></div>
  </form>"""


def _topbar_html(show_search: bool = True) -> str:
    search_html = _TOPBAR_SEARCH_HTML if show_search else ""
    # Kompakt mobil-header (2026-09-27, Kai: "s√∏kefunksjon √∏verst p√•
    # produktkort p√• mobil er un√∏dvendig. heller et s√∏keikon oppe er fint.
    # Feks. logo, s√∏keikon og et annet ikon for meny oppe til h√∏yre [...]
    # kompakt og bra fra toppen"). Under 700px er B√ÖDE .topbar-nav (de fire
    # menyknappene) OG .topbar-search (selve inputfeltet) skjult som
    # standard, og vises via disse to knappene i stedet -- s√∏k og meny
    # uavhengig av hverandre, akkurat som Kai spesifiserte. Kun s√∏keknappen
    # er betinget p√• show_search (forsiden har sin egen, st√∏rre hero-s√∏k og
    # trenger den ikke); menyknappen vises alltid.
    #
    # Selve s√∏keskjemaet (.search-row/.search-input osv.) er FYSISK UENDRET
    # -- kun CSS-synligheten endres via .is-open. Elementet finnes i DOM-en
    # hele tiden (display:none skjuler visningen, ikke selve noden), s√•
    # LENS_SEARCH_JS sin document.querySelectorAll('.search-row') finner
    # det akkurat som f√∏r uansett √•pen/lukket tilstand -- ingen risiko for
    # √• gjenintrodusere "s√∏ket svarer ikke"-bugen fra tidligere i dag
    # (se CLAUDE.md), siden selve elementet aldri fjernes/legges til.
    mobile_actions_html = (
        (
            '<button type="button" class="topbar-icon-btn" id="topbar-search-toggle" aria-label="S√∏k" aria-expanded="false" aria-controls="topbar-search-panel">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/></svg>'
            '</button>' if show_search else ''
        ) +
        '<button type="button" class="topbar-icon-btn" id="topbar-menu-toggle" aria-label="Meny" aria-expanded="false" aria-controls="topbar-nav">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
        '</button>'
    )
    return f"""<div class="topbar">
  <a href="/" class="topbar-logo"><picture><source srcset="/static/logo.webp" type="image/webp"><img src="/static/logo.png" alt="Kontaktlinser.no" width="700" height="79" loading="eager"></picture></a>
  <div class="topbar-mobile-actions">{mobile_actions_html}</div>
  <nav class="topbar-nav" id="topbar-nav">
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Kontaktlinser <span class="nav-caret">‚ñæ</span></button>
      <div class="mega-menu mega-menu-rich">
        <div class="mega-rich-grid mega-rich-grid-2col-plain">
          <div class="mega-rich-col">
            <div class="mega-col-title">Type</div>
            {_MEGA_CATEGORY_LINKS_HTML}
            <a class="mega-menu-link" href="/private-label/">Optikerkjedenes varemerker</a>
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Varemerke</div>
            {_MEGA_TOP_BRANDS_PLAIN_HTML}
          </div>
        </div>
        <a class="mega-menu-link mega-see-all" href="/#merker">Alle merker ‚Üí</a>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Merker <span class="nav-caret">‚ñæ</span></button>
      <div class="mega-menu mega-menu-rich">
        <div class="mega-rich-grid mega-rich-grid-2col">
          <div class="mega-rich-col">
            <div class="mega-panel-kicker">Merker</div>
            <div class="mega-panel-heading">Bla i alle kontaktlinsemerker</div>
            <p class="mega-panel-text">Ekte merker og optikerkjedenes egne serier, sortert alfabetisk.</p>
            <div class="mega-col-title" style="margin-top:18px;">Nyttig √• vite</div>
            {_mega_link_row(_SHIELD_ICON, "Optikerkjedenes varemerker", "Samme linse, andre navn", "/private-label/")}
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Alle merker A‚Äì√Ö</div>
            <div class="mega-allbrands">
              {_MEGA_ALL_BRANDS_HTML}
            </div>
          </div>
        </div>
        <a class="mega-menu-link mega-see-all" href="/#merker">Se alle merker ‚Üí</a>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Tilbeh√∏r <span class="nav-caret">‚ñæ</span></button>
      <div class="mega-menu">
        <div class="mega-col">
          <div class="mega-col-title">Kategori</div>
          <a class="mega-menu-link" href="/linsevaeske/">Linsev√¶ske</a>
          <a class="mega-menu-link" href="/oyedraper/">√òyedr√•per</a>
          <a class="mega-menu-link" href="/tilbehor/">Etui og hjelpemidler</a>
        </div>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Guider <span class="nav-caret">‚ñæ</span></button>
      <div class="mega-menu mega-menu-rich">
        <div class="mega-rich-grid mega-rich-grid-3col-plain">
          <div class="mega-rich-col">
            <div class="mega-col-title">Kom i gang</div>
            <a class="mega-menu-link" href="/guide/hvordan-velge-kontaktlinser/">Hvordan velge riktig linse</a>
            <a class="mega-menu-link" href="/guide/hvordan-bruke-kontaktlinser/">Slik bruker du kontaktlinser</a>
            <a class="mega-menu-link" href="/guide/hvorfor-bruke-kontaktlinser/">Hvorfor bruke kontaktlinser</a>
            <a class="mega-menu-link" href="/guide/kontaktlinser-for-barn/">Kontaktlinser for barn</a>
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Linseguider</div>
            <a class="mega-menu-link" href="/guide/manedslinser-vs-dagslinser/">Dagslinser vs. m√•nedslinser</a>
            <a class="mega-menu-link" href="/guide/kontaktlinser-med-astigmatisme/">Toriske linser og astigmatisme</a>
            <a class="mega-menu-link" href="/guide/multifokale-kontaktlinser/">Multifokale linser</a>
            <a class="mega-menu-link" href="/guide/harde-eller-myke-linser/">Harde eller myke linser</a>
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">√òyehelse</div>
            <a class="mega-menu-link" href="/guide/vedlikehold-av-kontaktlinser/">Vedlikehold og hygiene</a>
            <a class="mega-menu-link" href="/guide/kontaktlinser-og-torre-oyne/">T√∏rre √∏yne</a>
            <a class="mega-menu-link" href="/guide/rode-oyne-og-svie-med-kontaktlinser/">R√∏de √∏yne og svie</a>
            <a class="mega-menu-link" href="/guide/kan-jeg-bytte-kontaktlinsemerke-selv/">Bytte linsemerke selv</a>
          </div>
        </div>
        <a class="mega-menu-link mega-see-all" href="/guider/">Se alle guider ‚Üí</a>
      </div>
    </div>
  </nav>
  {search_html}
</div>
<style>{LENS_SEARCH_STYLE}
/* Ingen margin-left:auto -- det ga et unaturlig stort, tomt gap f√∏r boksen
   (brukeren s√• dette live og ba om at den heller skal starte rett til h√∏yre
   for "Guider", med SAMME mellomrom som resten av menyen -- alts√• vanlig
   flex-flyt, samme .topbar sitt gap:32px som alt annet i raden -- og deretter
   strekke seg selv til kanten av headeren via flex-grow, ikke via margin. */
.topbar-search {{ flex: 1 1 220px; min-width: 200px; }}
/* Skriftst√∏rrelsen MATCHER .nav-trigger sin (0.95rem) med vilje -- brukerens
   krav var at bokstavene i s√∏kefeltet skal ha samme h√∏yde som menyteksten,
   ikke bare at boksen skal se "passe stor" ut. Total h√∏yde (padding+tekst+
   kant) lander da sv√¶rt n√¶r .nav-trigger sin egen h√∏yde uten noe eget
   h√∏yde-tall √• holde synkront med menyen manuelt. */
.topbar-search .search-input {{ width: 100%; font-size: 0.95rem; padding: 7px 62px 7px 32px; border-radius: 9px; box-shadow: none; }}
.topbar-search .search-icon {{ left: 10px; width: 15px; height: 15px; }}
.topbar-search .search-btn {{ right: 4px; top: 4px; bottom: 4px; padding: 0 13px; font-size: 0.82rem; border-radius: 6px; }}
@media (max-width: 699px) {{
  /* Skjult som standard (Kai, 2026-09-27: s√∏keikon i stedet for et synlig
     felt) -- .topbar-search-toggle over √•pner den igjen via .is-open.
     Selve elementet er alltid i DOM-en, kun display:none -- se
     _topbar_html() sin docstring-kommentar for hvorfor det er trygt. */
  .topbar-search {{ display: none; order: 5; flex: 1 1 100%; margin-top: 6px; }}
}}
</style>
<script>
(function () {{
  var items = document.querySelectorAll('.nav-item');
  var topbarEl = document.querySelector('.topbar');
  function closeAll() {{
    for (var i = 0; i < items.length; i++) {{
      items[i].classList.remove('is-open');
      var t = items[i].querySelector('.nav-trigger');
      if (t) t.setAttribute('aria-expanded', 'false');
      var m = items[i].querySelector('.mega-menu');
      if (m) m.style.top = '';
    }}
  }}
  for (var i = 0; i < items.length; i++) {{
    (function (item) {{
      var trigger = item.querySelector('.nav-trigger');
      if (!trigger) return;
      trigger.addEventListener('click', function () {{
        var isOpen = item.classList.contains('is-open');
        closeAll();
        if (!isOpen) {{
          item.classList.add('is-open');
          trigger.setAttribute('aria-expanded', 'true');
          // Kun under 1280px-brytpunktet (se .mega-menu sin @media (max-width:
          // 1279px) i SHARED_STYLE) -- der er menyen position:fixed og trenger
          // en presis top= like under topbaren, siden CSS-en sitt statiske
          // fallback-tall (70px) ikke tar h√∏yde for at logo+navigasjon kan
          // brytes til to linjer p√• sv√¶rt smale skjermer.
          if (topbarEl && window.innerWidth < 1280) {{
            var menu = item.querySelector('.mega-menu');
            if (menu) menu.style.top = (topbarEl.getBoundingClientRect().bottom + 8) + 'px';
          }}
        }}
      }});
    }})(items[i]);
  }}
  document.addEventListener('click', function (e) {{
    if (!e.target.closest('.nav-item')) closeAll();
  }});
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape') closeAll();
  }});

  // Kompakt mobil-header (2026-09-27): meny-/s√∏k-ikonet √•pner/lukker
  // .topbar-nav/.topbar-search uavhengig av hverandre. Lukker .topbar-nav
  // (meny) n√•r s√∏k √•pnes og omvendt, siden begge tar full bredde under
  // 700px og ellers kan st√• √•pne opp√• hverandre.
  function toggleMobilePanel(btn, panel, otherBtn, otherPanel) {{
    if (!btn || !panel) return;
    var isOpen = panel.classList.contains('is-open');
    panel.classList.toggle('is-open', !isOpen);
    btn.setAttribute('aria-expanded', (!isOpen).toString());
    if (!isOpen && otherPanel) {{
      otherPanel.classList.remove('is-open');
      if (otherBtn) otherBtn.setAttribute('aria-expanded', 'false');
    }}
    if (!isOpen && panel.id === 'topbar-search-panel') {{
      var input = panel.querySelector('.search-input');
      if (input) input.focus();
    }}
  }}
  var menuBtn = document.getElementById('topbar-menu-toggle');
  var searchBtn = document.getElementById('topbar-search-toggle');
  var navPanel = document.getElementById('topbar-nav');
  var searchPanel = document.getElementById('topbar-search-panel');
  if (menuBtn) menuBtn.addEventListener('click', function (e) {{ e.stopPropagation(); toggleMobilePanel(menuBtn, navPanel, searchBtn, searchPanel); }});
  if (searchBtn) searchBtn.addEventListener('click', function (e) {{ e.stopPropagation(); toggleMobilePanel(searchBtn, searchPanel, menuBtn, navPanel); }});
  document.addEventListener('click', function (e) {{
    if (e.target.closest('.topbar-mobile-actions, #topbar-nav, #topbar-search-panel')) return;
    if (navPanel) {{ navPanel.classList.remove('is-open'); if (menuBtn) menuBtn.setAttribute('aria-expanded', 'false'); }}
    if (searchPanel) {{ searchPanel.classList.remove('is-open'); if (searchBtn) searchBtn.setAttribute('aria-expanded', 'false'); }}
  }});
}})();
{LENS_SEARCH_JS}
</script>"""
# TOPBAR_HTML/TOPBAR_HTML_NO_SEARCH bygges lenger nede i filen, rett etter at
# LENS_SEARCH_STYLE/LENS_SEARCH_JS (referert over) faktisk finnes -- et kall
# her ville feilet med NameError siden de er definert langt senere.

# Kuratert, ikke generert fra catalog.json -- oppdater manuelt hvis
# kategori- eller merkeutvalget endres vesentlig (samme praksis som TOPBAR_HTML).
FOOTER_CATEGORIES = [
    ("manedslinser", "M√•nedslinser"),
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
    ("clearlii", "Clearlii"),
    ("dailies", "Dailies"),
    ("freshlook", "FreshLook"),
    ("live", "Live"),
    ("miru", "MIRU"),
    ("misight", "MiSight"),
    ("myday", "MyDay"),
    ("precision1", "Precision1"),
    ("precision7", "Precision7"),
    ("proclear", "Proclear"),
    ("purevision", "PureVision"),
    ("soflens", "SofLens"),
    ("total30", "TOTAL30"),
    ("ultra", "ULTRA"),
]

# Gamle, fortsatt Google-indekserte URL-er fra forrige versjon av siden.
# Opprinnelig (2026-08-11) kun 10 stk funnet via "site:kontaktlinser.no".
# Utvidet til full dekning (2026-08-16) via en systematisk gjennomgang av
# Wayback Machine sitt CDX-arkiv for hele det gamle domenet (239 unike
# innholds-URL-er med status 200, ekskl. bilder/CSS/ASP.NET-systemfiler),
# kryssjekket mot dagens katalog/merker/private-label/guider -- se
# CLAUDE.md for metodikk og bevisste skj√∏nnsvurderinger (f.eks. hvorfor
# enkelte gamle produkter peker til merke-siden i stedet for et konkret
# produkt, n√•r riktig pakningsst√∏rrelse/variant ikke kunne bekreftes).
# GitHub Pages kan ikke servere .aspx som HTML (bekreftet: mime-db mangler
# .aspx, serveres som application/octet-stream) - derfor ingen ekte
# server-side 301 her, kun en klientsidevis omdirigering fra 404-siden (se
# render_404_page). Ekte 301-er via Cloudflare er en egen, separat plan.
# N√∏klene M√Ö v√¶re sm√• bokstaver (matches mot location.pathname.toLowerCase()
# i JS-en).
LEGACY_REDIRECTS = {
    "/1-day_acuvue_for_astigmatism.aspx": "/merke/acuvue/",
    "/annonse.aspx": "/",
    "/daysoft_uv.aspx": "/kontaktlinser/dagslinser/",
    "/fargelinser-bla.aspx": "/kontaktlinser/fargede-linser/",
    "/fargelinser-brune.aspx": "/kontaktlinser/fargede-linser/",
    "/fargelinser-gronne.aspx": "/kontaktlinser/fargede-linser/",
    "/fargelinser-rode.aspx": "/kontaktlinser/fargede-linser/",
    "/fargelinser-svarte.aspx": "/kontaktlinser/fargede-linser/",
    "/fargelinser-uten-styrke.aspx": "/kontaktlinser/fargede-linser/",
    "/infosider/for_barn.aspx": "/guide/kontaktlinser-for-barn/",
    "/infosider/harde_eller_myke_linser.aspx": "/guide/harde-eller-myke-linser/",
    "/infosider/hvordan.aspx": "/guide/hvordan-bruke-kontaktlinser/",
    "/infosider/hvorfor.aspx": "/guide/hvorfor-bruke-kontaktlinser/",
    "/infosider/kontaktlinsens_materiale.aspx": "/guide/kontaktlinsens-materiale/",
    "/infosider/korrigerende_kontaktlinser.aspx": "/guide/korrigerende-kontaktlinser/",
    "/infosider/kosmetiske_kontaktlinser.aspx": "/guide/kosmetiske-kontaktlinser/",
    "/infosider/produksjon_av_kontaktlinser.aspx": "/guide/produksjon-av-kontaktlinser/",
    "/infosider/reising_med_kontaktlinser.aspx": "/guide/reising-med-kontaktlinser/",
    "/infosider/terapeutiske_kontaktlinser.aspx": "/guide/terapeutiske-kontaktlinser/",
    "/infosider/vedlikehold_av_linser.aspx": "/guide/vedlikehold-av-kontaktlinser/",
    "/infosider/vedlikehold_av_linser/vedlikehold_av_kontaktlinsene.aspx": "/guide/vedlikehold-av-kontaktlinser/",
    "/kontaktlinser/bifokale_linser.aspx": "/kontaktlinser/multifokale-linser/",
    "/kontaktlinser/dagslinser.aspx": "/kontaktlinser/dagslinser/",
    "/kontaktlinser/dagslinser/linser.aspx": "/kontaktlinser/dagslinser/",
    "/kontaktlinser/dognet_rundt_linser.aspx": "/",
    "/kontaktlinser/fargede_linser.aspx": "/kontaktlinser/fargede-linser/",
    "/kontaktlinser/fargede_linser/fargelinser.aspx": "/kontaktlinser/fargede-linser/",
    "/kontaktlinser/fargede_linser/gule_kontaktlinser.aspx": "/kontaktlinser/fargede-linser/",
    "/kontaktlinser/fargede_linser/svarte_kontaktlinser.aspx": "/kontaktlinser/fargede-linser/",
    "/kontaktlinser/langtidslinser.aspx": "/",
    "/kontaktlinser/linsevaeske_tilbehor.aspx": "/linsevaeske/",
    "/kontaktlinser/manedslinser.aspx": "/kontaktlinser/manedslinser/",
    "/kontaktlinser/progressive_linser.aspx": "/kontaktlinser/multifokale-linser/",
    "/kontaktlinser/toriske_linser.aspx": "/kontaktlinser/toriske-linser/",
    "/kontaktlinser/ukelinser.aspx": "/",
    "/kontaktlinser_.aspx": "/",
    "/leverandorer/alcon.aspx": "/",
    "/leverandorer/amo.aspx": "/",
    "/leverandorer/barnaux_healthcare.aspx": "/",
    "/leverandorer/bausch_and_lomb.aspx": "/",
    "/leverandorer/ciba_vision.aspx": "/",
    "/leverandorer/cl_tinters.aspx": "/",
    "/leverandorer/clearlab.aspx": "/",
    "/leverandorer/clearly_contacts.aspx": "/",
    "/leverandorer/comfort.aspx": "/",
    "/leverandorer/consol.aspx": "/",
    "/leverandorer/coopervision.aspx": "/",
    "/leverandorer/eyemed-technologies.aspx": "/",
    "/leverandorer/johnson_and_johnson.aspx": "/",
    "/leverandorer/lensway.aspx": "/",
    "/leverandorer/ocular_sciences.aspx": "/",
    "/leverandorer/provis_limited.aspx": "/",
    "/leverandorer/soleko.aspx": "/",
    "/leverandorer/yourlenses.aspx": "/",
    "/produkt/1-day-acuvue-moist-multifocal.aspx": "/kontaktlinser/acuvue/1-day-acuvue-moist-multifocal-30-pack/",
    "/produkt/1-day_acuvue.aspx": "/merke/acuvue/",
    "/produkt/1-day_acuvue_for_astigmatism.aspx": "/merke/acuvue/",
    "/produkt/1-day_acuvue_moist.aspx": "/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/",
    "/produkt/1-day_acuvue_moist_for_astigmatism.aspx": "/kontaktlinser/acuvue/1-day-acuvue-moist-for-astigmatism-30-pack/",
    "/produkt/1-day_acuvue_trueye.aspx": "/merke/acuvue/",
    "/produkt/acuvue.aspx": "/merke/acuvue/",
    "/produkt/acuvue_2.aspx": "/merke/acuvue/",
    "/produkt/acuvue_2_colours_enhancers.aspx": "/merke/acuvue/",
    "/produkt/acuvue_2_colours_opaque.aspx": "/merke/acuvue/",
    "/produkt/acuvue_advance.aspx": "/merke/acuvue/",
    "/produkt/acuvue_advance_for_astigmatism.aspx": "/merke/acuvue/",
    "/produkt/acuvue_bifocal.aspx": "/merke/acuvue/",
    "/produkt/acuvue_oasys.aspx": "/kontaktlinser/acuvue/acuvue-oasys-6-pack/",
    "/produkt/acuvue_oasys_for_astigmatism.aspx": "/kontaktlinser/acuvue/acuvue-oasys-for-astigmatism-6-pack/",
    "/produkt/adore_bi-tone.aspx": "/kontaktlinser/adore/adore-bi-tone-2-pack/",
    "/produkt/adore_dare.aspx": "/kontaktlinser/adore/adore-dare-2-pack/",
    "/produkt/adore_tri-tone.aspx": "/merke/adore/",
    "/produkt/air-optix-colors.aspx": "/kontaktlinser/air-optix/air-optix-colors-2-pack/",
    "/produkt/air-optix-ex.aspx": "/merke/air-optix/",
    "/produkt/air-optix-plus-hydraglyde.aspx": "/kontaktlinser/air-optix/air-optix-plus-hydraglyde-6-pack/",
    "/produkt/air_optix.aspx": "/merke/air-optix/",
    "/produkt/air_optix_aqua.aspx": "/merke/air-optix/",
    "/produkt/air_optix_aqua_multifocal.aspx": "/merke/air-optix/",
    "/produkt/air_optix_for_astigmatism.aspx": "/merke/air-optix/",
    "/produkt/air_optix_night_and_day.aspx": "/merke/air-optix/",
    "/produkt/air_optix_nightandday_aqua.aspx": "/kontaktlinser/air-optix/air-optix-night-day-aqua-6-pack/",
    "/produkt/aosept.aspx": "/linsevaeske/",
    "/produkt/aquify.aspx": "/linsevaeske/",
    "/produkt/avaira-toric.aspx": "/merke/avaira/",
    "/produkt/avaira_kontaktlinser.aspx": "/merke/avaira/",
    "/produkt/biocolor_55.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/biofinity-multifocal.aspx": "/kontaktlinser/biofinity/biofinity-multifocal-6-pack/",
    "/produkt/biofinity-xr.aspx": "/merke/biofinity/",
    "/produkt/biofinity.aspx": "/kontaktlinser/biofinity/biofinity-6-pack/",
    "/produkt/biofinity_toric.aspx": "/kontaktlinser/biofinity/biofinity-toric-6-pack/",
    "/produkt/bioflex.aspx": "/",
    "/produkt/bioflex_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/biomedics-1day-extra-toric.aspx": "/kontaktlinser/biomedics/biomedics-1day-extra-toric-30-pack/",
    "/produkt/biomedics-1day-extra.aspx": "/kontaktlinser/biomedics/biomedics-1day-extra-30-pack/",
    "/produkt/biomedics_1-day.aspx": "/merke/biomedics/",
    "/produkt/biomedics_1_day_toric.aspx": "/merke/biomedics/",
    "/produkt/biomedics_55_evolution.aspx": "/kontaktlinser/biomedics/biomedics-55-evolution-6-pack/",
    "/produkt/biomedics_55_evolution_color.aspx": "/merke/biomedics/",
    "/produkt/biomedics_toric.aspx": "/kontaktlinser/biomedics/biomedics-toric-6-pack/",
    "/produkt/biotrue-oneday.aspx": "/kontaktlinser/biotrue/biotrue-oneday-30-pack/",
    "/produkt/biotrue_oneday_for_presbyopia.aspx": "/kontaktlinser/biotrue/biotrue-oneday-for-presbyopia-30-pack/",
    "/produkt/blic_dag.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/blink.aspx": "/oyedraper/",
    "/produkt/cibasoft.aspx": "/",
    "/produkt/cibasoft_visitint.aspx": "/",
    "/produkt/classic_kontaktlinser.aspx": "/",
    "/produkt/clear58.aspx": "/",
    "/produkt/clear_1-day.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/clear_38.aspx": "/",
    "/produkt/clear_55a.aspx": "/",
    "/produkt/clear_all-day.aspx": "/",
    "/produkt/clearly_colors.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/clearly_colors_special_effects.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/clens_100.aspx": "/linsevaeske/",
    "/produkt/contact_30_day.aspx": "/kontaktlinser/manedslinser/",
    "/produkt/crazy_lenses.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/dailies-aquacomfort-plus-multifocal.aspx": "/kontaktlinser/dailies/dailies-aquacomfort-plus-multifocal-30-pack/",
    "/produkt/dailies-aquacomfort-plus-toric.aspx": "/kontaktlinser/dailies/dailies-aquacomfort-plus-toric-30-pack/",
    "/produkt/dailies-total-1-multifocal.aspx": "/kontaktlinser/dailies/dailies-total1-multifocal-30-pack/",
    "/produkt/dailies-total-1-multifocal/dailies-aquacomfort-plus-spheric.aspx": "/kontaktlinser/dailies/dailies-aquacomfort-plus-30-pack/",
    "/produkt/dailies-total1.aspx": "/kontaktlinser/dailies/dailies-total1-30-pack/",
    "/produkt/dailies_aqua_comfort_plus.aspx": "/kontaktlinser/dailies/dailies-aquacomfort-plus-30-pack/",
    "/produkt/daysoft_uv_58.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/easysept.aspx": "/linsevaeske/easysept/easysept-120-ml/",
    "/produkt/easyvision_adan_opteyes.aspx": "/merke/easyvision/",
    "/produkt/easyvision_all_day.aspx": "/merke/easyvision/",
    "/produkt/easyvision_all_day_all_night.aspx": "/merke/easyvision/",
    "/produkt/easyvision_aspheric_all_day.aspx": "/merke/easyvision/",
    "/produkt/easyvision_colors.aspx": "/merke/easyvision/",
    "/produkt/easyvision_elite_oneday.aspx": "/merke/easyvision/",
    "/produkt/easyvision_oneday.aspx": "/merke/easyvision/",
    "/produkt/easyvision_varifocal.aspx": "/merke/easyvision/",
    "/produkt/expressions_accent.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/expressions_colors.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/extend.aspx": "/",
    "/produkt/eye_q_24.aspx": "/private-label/eyeq-24/",
    "/produkt/eye_q_one-day.aspx": "/merke/eyeq/",
    "/produkt/eye_q_premium.aspx": "/private-label/eyeq-premium/",
    "/produkt/eye_q_premium_2.aspx": "/merke/eyeq/",
    "/produkt/eye_q_toric.aspx": "/merke/eyeq/",
    "/produkt/eyecare_30.aspx": "/",
    "/produkt/eyes4u_dagslinser.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/focus_dailies.aspx": "/kontaktlinser/dailies/focus-dailies-30-pack/",
    "/produkt/focus_dailies_all_day.aspx": "/merke/dailies/",
    "/produkt/focus_dailies_progressives.aspx": "/merke/dailies/",
    "/produkt/focus_dailies_toric.aspx": "/merke/dailies/",
    "/produkt/focus_monthly.aspx": "/kontaktlinser/manedslinser/",
    "/produkt/focus_monthly_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/focus_progressives.aspx": "/kontaktlinser/multifokale-linser/",
    "/produkt/focus_softcolors.aspx": "/kontaktlinser/fargede-linser/",
    "/produkt/focus_toric_visitint.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/focus_visitint.aspx": "/",
    "/produkt/frequency_1_day.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/frequency_1_day_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/frequency_38.aspx": "/",
    "/produkt/frequency_55.aspx": "/",
    "/produkt/frequency_55_ab.aspx": "/",
    "/produkt/frequency_58_uv.aspx": "/",
    "/produkt/frequency_xc.aspx": "/",
    "/produkt/frequency_xcel_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/frequency_xcel_toric_xr.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/freshcare_dailies.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/freshlook_colorblends.aspx": "/merke/freshlook/",
    "/produkt/freshlook_colors.aspx": "/merke/freshlook/",
    "/produkt/freshlook_dimensions.aspx": "/merke/freshlook/",
    "/produkt/freshlook_one-day.aspx": "/kontaktlinser/freshlook/freshlook-oneday-30-pack/",
    "/produkt/freshlook_radiance.aspx": "/merke/freshlook/",
    "/produkt/iwear_1_day.aspx": "/merke/iwear/",
    "/produkt/iwear_dd_supreme_1_day.aspx": "/merke/iwear/",
    "/produkt/iwear_dr_color.aspx": "/merke/iwear/",
    "/produkt/iwear_xr_supreme.aspx": "/merke/iwear/",
    "/produkt/iwear_xr_supreme_toric.aspx": "/merke/iwear/",
    "/produkt/lensway_case.aspx": "/tilbehor/",
    "/produkt/lensway_hand_desinfection_spray.aspx": "/",
    "/produkt/lensway_solution.aspx": "/linsevaeske/",
    "/produkt/mediflex_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/myday-daily-disposable.aspx": "/kontaktlinser/myday/myday-30-pack/",
    "/produkt/neoflex_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/opti-free_ampuller.aspx": "/linsevaeske/",
    "/produkt/opti-free_express.aspx": "/linsevaeske/opti-free/opti-free-express-120-ml/",
    "/produkt/opti-free_express_norub.aspx": "/linsevaeske/",
    "/produkt/opti-free_replenish.aspx": "/linsevaeske/",
    "/produkt/opti-tears_free_rewetting_drops.aspx": "/oyedraper/",
    "/produkt/optima_fw.aspx": "/",
    "/produkt/precision_uv.aspx": "/",
    "/produkt/proclear-multifocal-xr.aspx": "/kontaktlinser/proclear/proclear-multifocal-xr-3-pack/",
    "/produkt/proclear-toric-xr.aspx": "/kontaktlinser/proclear/proclear-toric-xr-3-pack/",
    "/produkt/proclear_1-day_multifocal.aspx": "/kontaktlinser/proclear/proclear-1-day-multifocal-30-pack/",
    "/produkt/proclear_1_day.aspx": "/kontaktlinser/proclear/proclear-1-day-30-pack/",
    "/produkt/proclear_compatibles.aspx": "/merke/proclear/",
    "/produkt/proclear_compatibles_toric.aspx": "/merke/proclear/",
    "/produkt/proclear_ep.aspx": "/merke/proclear/",
    "/produkt/proclear_multifocal.aspx": "/kontaktlinser/proclear/proclear-multifocal-6-pack/",
    "/produkt/proclear_sphere.aspx": "/kontaktlinser/proclear/proclear-sphere-6-pack/",
    "/produkt/proclear_toric.aspx": "/kontaktlinser/proclear/proclear-toric-6-pack/",
    "/produkt/proclear_xc.aspx": "/merke/proclear/",
    "/produkt/procon_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/purevision-2-hd-for-astigmatism.aspx": "/kontaktlinser/purevision/purevision2-for-astigmatism-6-pack/",
    "/produkt/purevision-2-hd.aspx": "/kontaktlinser/purevision/purevision2-6-pack/",
    "/produkt/purevision-2-multifocal.aspx": "/kontaktlinser/purevision/purevision2-for-presbyopia-6-pack/",
    "/produkt/purevision.aspx": "/kontaktlinser/purevision/purevision-6-pack/",
    "/produkt/purevision_multifocal.aspx": "/kontaktlinser/purevision/purevision-multifocal-6-pack/",
    "/produkt/purevision_toric.aspx": "/merke/purevision/",
    "/produkt/queens-trilogy.aspx": "/",
    "/produkt/queens-twins.aspx": "/",
    "/produkt/renu_flight_pack.aspx": "/linsevaeske/renu/renu-flight-pack-100-ml/",
    "/produkt/renu_multi-purpose.aspx": "/linsevaeske/renu/renu-multi-purpose-60-ml/",
    "/produkt/renu_onthego.aspx": "/linsevaeske/",
    "/produkt/s-75.aspx": "/",
    "/produkt/seequence.aspx": "/",
    "/produkt/soflens-natural-colors.aspx": "/merke/soflens/",
    "/produkt/soflens_38.aspx": "/kontaktlinser/soflens/soflens-38-6-pack/",
    "/produkt/soflens_59.aspx": "/kontaktlinser/soflens/soflens-59-6-pack/",
    "/produkt/soflens_66.aspx": "/merke/soflens/",
    "/produkt/soflens_daily_disposable.aspx": "/kontaktlinser/soflens/soflens-daily-disposable-30-pack/",
    "/produkt/soflens_daily_disposable_for_astigmatism.aspx": "/kontaktlinser/soflens/soflens-daily-disposable-for-astigmatism-30-pack/",
    "/produkt/soflens_multifocal.aspx": "/kontaktlinser/soflens/soflens-multifocal-6-pack/",
    "/produkt/soflens_natural_colors.aspx": "/merke/soflens/",
    "/produkt/soflens_one_day.aspx": "/merke/soflens/",
    "/produkt/soflens_toric.aspx": "/kontaktlinser/soflens/soflens-toric-6-pack/",
    "/produkt/solo_care_aqua.aspx": "/linsevaeske/solocare/solocare-aqua-360-ml/",
    "/produkt/solo_care_soft.aspx": "/linsevaeske/",
    "/produkt/standard_lens.aspx": "/",
    "/produkt/standard_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/surevue.aspx": "/",
    "/produkt/synolens_oneday.aspx": "/kontaktlinser/dagslinser/",
    "/produkt/systane.aspx": "/oyedraper/",
    "/produkt/ultraflex_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/search.aspx": "/",
    "/sitemap.aspx": "/",
    "/sporsmal_og_svar/anbefalte-websider.aspx": "/",
    "/sporsmal_og_svar/konsernsider.aspx": "/",
    "/sporsmal_og_svar/kontakt_oss.aspx": "/om-oss/",
    "/sporsmal_og_svar/kontaktlinsens_historie.aspx": "/guide/kontaktlinsens-historie/",
    "/sporsmal_og_svar/kontaktlinser_faq.aspx": "/",
    "/sporsmal_og_svar/om_kontaktlinser_no.aspx": "/om-oss/",
    "/sporsmal_og_svar/om_kontaktlinser_no/yourlenses.aspx": "/",
    # Slug-migrering 2026-09-05: fulle, kanoniske produktnavn i URL-en
    # i stedet for korte slugs (se CLAUDE.md) -- disse 57 var reelle,
    # allerede-linkede URL-er samme dag de ble byttet ut, ikke gamle
    # .aspx-lenker.
    "/kontaktlinser/acuvue/oasys-6-pack/": "/kontaktlinser/acuvue/acuvue-oasys-6-pack/",
    "/kontaktlinser/acuvue/vita-6-pack/": "/kontaktlinser/acuvue/acuvue-vita-6-pack/",
    "/kontaktlinser/acuvue/moist-30-pack/": "/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/",
    "/kontaktlinser/acuvue/oasys-max-1-day-30-pack/": "/kontaktlinser/acuvue/acuvue-oasys-max-1-day-30-pack/",
    "/kontaktlinser/acuvue/oasys-1-day-hydraluxe-30-pack/": "/kontaktlinser/acuvue/acuvue-oasys-1-day-with-hydraluxe-30-pack/",
    "/kontaktlinser/acuvue/oasys-astigmatism-6-pack/": "/kontaktlinser/acuvue/acuvue-oasys-for-astigmatism-6-pack/",
    "/kontaktlinser/acuvue/moist-astigmatism-30-pack/": "/kontaktlinser/acuvue/1-day-acuvue-moist-for-astigmatism-30-pack/",
    "/kontaktlinser/air-optix/colors-2-pack/": "/kontaktlinser/air-optix/air-optix-colors-2-pack/",
    "/kontaktlinser/adore/bi-tone-2-pack/": "/kontaktlinser/adore/adore-bi-tone-2-pack/",
    "/kontaktlinser/adore/dare-2-pack/": "/kontaktlinser/adore/adore-dare-2-pack/",
    "/kontaktlinser/acuvue/oasys-multifocal-6-pack/": "/kontaktlinser/acuvue/acuvue-oasys-multifocal-6-pack/",
    "/kontaktlinser/biofinity/energys-6-pack/": "/kontaktlinser/biofinity/biofinity-energys-6-pack/",
    "/kontaktlinser/biofinity/xr-6-pack/": "/kontaktlinser/biofinity/biofinity-xr-6-pack/",
    "/kontaktlinser/air-optix/night-day-aqua-6-pack/": "/kontaktlinser/air-optix/air-optix-night-day-aqua-6-pack/",
    "/kontaktlinser/biomedics/biomedics-1-day-xtra-30-pack/": "/kontaktlinser/biomedics/biomedics-1day-extra-30-pack/",
    "/kontaktlinser/biomedics/biomedics-1-day-xtra-toric-30-pack/": "/kontaktlinser/biomedics/biomedics-1day-extra-toric-30-pack/",
    "/kontaktlinser/acuvue/moist-90-pack/": "/kontaktlinser/acuvue/1-day-acuvue-moist-90-pack/",
    "/kontaktlinser/acuvue/moist-astigmatism-90-pack/": "/kontaktlinser/acuvue/1-day-acuvue-moist-for-astigmatism-90-pack/",
    "/kontaktlinser/acuvue/oasys-1-day-hydraluxe-90-pack/": "/kontaktlinser/acuvue/acuvue-oasys-1-day-with-hydraluxe-90-pack/",
    "/kontaktlinser/acuvue/oasys-max-1-day-90-pack/": "/kontaktlinser/acuvue/acuvue-oasys-max-1-day-90-pack/",
    "/kontaktlinser/biomedics/biomedics-1-day-xtra-90-pack/": "/kontaktlinser/biomedics/biomedics-1day-extra-90-pack/",
    "/kontaktlinser/acuvue/moist-multifocal-30-pack/": "/kontaktlinser/acuvue/1-day-acuvue-moist-multifocal-30-pack/",
    "/kontaktlinser/acuvue/moist-multifocal-90-pack/": "/kontaktlinser/acuvue/1-day-acuvue-moist-multifocal-90-pack/",
    "/kontaktlinser/acuvue/oasys-1-day-for-astigmatism-30-pack/": "/kontaktlinser/acuvue/acuvue-oasys-1-day-for-astigmatism-30-pack/",
    "/kontaktlinser/acuvue/oasys-1-day-for-astigmatism-90-pack/": "/kontaktlinser/acuvue/acuvue-oasys-1-day-for-astigmatism-90-pack/",
    "/kontaktlinser/biofinity/multifocal-toric-3-pack/": "/kontaktlinser/biofinity/biofinity-multifocal-toric-3-pack/",
    "/kontaktlinser/biofinity/xr-toric-3-pack/": "/kontaktlinser/biofinity/biofinity-xr-toric-3-pack/",
    "/kontaktlinser/biofinity/xr-3-pack/": "/kontaktlinser/biofinity/biofinity-xr-3-pack/",
    "/kontaktlinser/proclear/1-day-30-pack/": "/kontaktlinser/proclear/proclear-1-day-30-pack/",
    "/kontaktlinser/proclear/1-day-90-pack/": "/kontaktlinser/proclear/proclear-1-day-90-pack/",
    "/kontaktlinser/proclear/1-day-multifocal-30-pack/": "/kontaktlinser/proclear/proclear-1-day-multifocal-30-pack/",
    "/kontaktlinser/proclear/multifocal-6-pack/": "/kontaktlinser/proclear/proclear-multifocal-6-pack/",
    "/kontaktlinser/proclear/multifocal-toric-3-pack/": "/kontaktlinser/proclear/proclear-multifocal-toric-3-pack/",
    "/kontaktlinser/proclear/multifocal-xr-3-pack/": "/kontaktlinser/proclear/proclear-multifocal-xr-3-pack/",
    "/kontaktlinser/proclear/toric-xr-3-pack/": "/kontaktlinser/proclear/proclear-toric-xr-3-pack/",
    "/kontaktlinser/soflens/38-6-pack/": "/kontaktlinser/soflens/soflens-38-6-pack/",
    "/kontaktlinser/soflens/daily-disposable-for-astigmatism-30-pack/": "/kontaktlinser/soflens/soflens-daily-disposable-for-astigmatism-30-pack/",
    "/kontaktlinser/soflens/multifocal-6-pack/": "/kontaktlinser/soflens/soflens-multifocal-6-pack/",
    "/kontaktlinser/clearlii/clearlii-monthly-6-pack/": "/kontaktlinser/clearlii/clearlii-hydrogel-manedslinser-6-pack/",
    "/kontaktlinser/queens-trilogy/queens-trilogy-2-pack/": "/kontaktlinser/queens-trilogy/queen-s-trilogy-2-pack/",
    "/kontaktlinser/acuvue/oasys-max-1-day-astigmatism-30-pack/": "/kontaktlinser/acuvue/acuvue-oasys-max-1-day-for-astigmatism-30-pack/",
    "/linsevaeske/opti-free/puremoist-90-ml/": "/linsevaeske/opti-free/opti-free-puremoist-90-ml/",
    "/linsevaeske/opti-free/puremoist-300-ml/": "/linsevaeske/opti-free/opti-free-puremoist-300-ml/",
    "/linsevaeske/opti-free/express-355-ml/": "/linsevaeske/opti-free/opti-free-express-355-ml/",
    "/linsevaeske/opti-free/express-120-ml/": "/linsevaeske/opti-free/opti-free-express-120-ml/",
    "/linsevaeske/everclear/refresh-250-ml/": "/linsevaeske/everclear/everclear-refresh-250-ml/",
    "/linsevaeske/acuvue-revitalens/revitalens-100-ml/": "/linsevaeske/acuvue-revitalens/acuvue-revitalens-100-ml/",
    "/linsevaeske/acuvue-revitalens/revitalens-300-ml/": "/linsevaeske/acuvue-revitalens/acuvue-revitalens-300-ml/",
    "/linsevaeske/swati/lens-solution-100-ml/": "/linsevaeske/swati/swati-lens-solution-100-ml/",
    "/oyedraper/oxyal/trehalos-duo-action-10-ml/": "/oyedraper/oxyal/oxyal-trehalos-duo-action-10-ml/",
    "/oyedraper/oxyal/trehalos-triple-action-10-ml/": "/oyedraper/oxyal/oxyal-trehalos-triple-action-10-ml/",
    "/oyedraper/oxyal/triple-action-10-ml/": "/oyedraper/oxyal/oxyal-triple-action-10-ml/",
    "/oyedraper/artelac/artelac-10-ml/": "/oyedraper/artelac/artelac-oyedraper-10-ml/",
    "/oyedraper/viscotears/viscotears-10-g/": "/oyedraper/viscotears/viscotears-oyegel-10-g/",
    "/oyedraper/hyprosan/hyprosan-10-ml/": "/oyedraper/hyprosan/hyprosan-oyedraper-10-ml/",
    "/oyedraper/desodrop/desodrop-8-ml/": "/oyedraper/desodrop/desodrop-oyedraper-8-ml/",
    "/oyedraper/cleye/cleye-10-ml/": "/oyedraper/cleye/cleye-oyedraper-10-ml/",
}


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
      <a href="/guide/manedslinser-vs-dagslinser/">M√•nedslinser vs. dagslinser</a>
      <a href="/guide/hvordan-velge-kontaktlinser/">Hvordan velge kontaktlinser</a>
      <a href="/private-label/">Optikerkjedenes egne merker</a>
    </div>
    <div class="footer-col">
      <h3>Metodikk</h3>
      <a href="/slik-sammenligner-vi-priser/">Slik sammenligner vi priser</a>
      <a href="/slik-matcher-vi-produkter/">Slik matcher vi produkter</a>
      <a href="/redaksjonelle-prinsipper/">Redaksjonelle prinsipper</a>
      <a href="/affiliate-og-finansiering/">Affiliate og finansiering</a>
    </div>
  </div>
  <p class="footer-disclosure">
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser
    automatisk fra forhandlerne, oppdaterer dem daglig og sorterer etter
    lavest pris (sl√• p√• ¬´Pris inkludert frakt¬ª for √• se totalprisen). Vi kan motta provisjon n√•r du handler via
    lenkene v√•re &ndash; det p√•virker verken prisen du betaler eller rangeringen
    av tilbud. Vi selger ikke kontaktlinser selv. Kontaktlinser er reseptvare:
    r√•df√∏r deg alltid med optiker ved valg av linsetype og styrke.
  </p>
  <div class="footer-bottom">
    <span>&copy; {year} Kontaktlinser.no</span>
    <a href="/">Forside</a>
    <a href="/guider/">Guider</a>
    <a href="/om-oss/" rel="author">Om oss</a>
    <a href="/personvern/" rel="privacy-policy">Personvern og cookies</a>
    <a href="/vilkar/" rel="terms-of-service">Vilk√•r og ansvarsfraskrivelse</a>
    <a href="/meld-feil/">Meld feil</a>
    {_contact_email_link()}
    <a href="https://www.facebook.com/kontaktlinser.no/" rel="me noopener" target="_blank" aria-label="Kontaktlinser.no p√• Facebook">Facebook</a>
  </div>
</footer>"""


LICENSED_IMAGE_SOURCES = {"affiliate_feed", "manufacturer_kit"}

# N√∏ytral bruk for √• identifisere hvor tilbudet faktisk kommer fra (samme
# praksis som enhver prissammenligningstjeneste) - ikke ment √• antyde
# partnerskap/godkjenning fra forhandleren. Hentet direkte fra hver
# forhandlers egen nettside (static/logos/), fjernes umiddelbart ved
# foresp√∏rsel. dark_bg=True betyr logoen er hvit/lys og trenger en m√∏rk
# bakgrunnslapp for √• v√¶re synlig p√• v√•re lyse kort.
RETAILER_LOGOS = {
    "Interoptik": ("interoptik.png", False),
    "Lensway": ("lensway.svg", False),
    "Lenson": ("lenson.svg", False),
    "Extra Optical": ("extraoptical.svg", False),
    "Shopping4net": ("shopping4net.png", False),
    "Lensit": ("lensit.svg", False),
    "Specsavers": ("specsavers.svg", False),
    "Synsam": ("synsam.svg", False),
    "Brilleland": ("brilleland.svg", False),
    "Apotekhjem": ("apotekhjem.png", False),
}


# Kjedenavnet (Synsam/Brilleland/Specsavers/Coptikk) skal IKKE vises p√• disse
# seriene ute p√• siden (bruker-beslutning 2026-08-30) -- de skal fremst√• som
# egne merker, p√• linje med ekte linsemerker. Full kobling til kjeden ligger
# fortsatt p√• /private-label/, en egen side dedikert til akkurat den
# forklaringen. PRIVATE_LABEL_SUBBRANDS brukes derfor kun til √• sl√• opp
# visningsnavnet (chain -> serienavn), aldri til √• vise/nevne selve kjeden.
PRIVATE_LABEL_SUBBRANDS = {
    "Brilleland": "iWear",
    "Synsam": "EyeQ",
    "Specsavers": "Easyvision",
    "Coptikk": "Ascend",
    "Mister Spex": "TrueLens",
}

# "Alle merker A-√Ö" i toppmenyens Merker-dropdown (2026-09-29). Kai, med
# skjermbilde av den gamle dropdownen: "brukere trenger ikke bli sendt til
# Produsent. De √∏nsker √• komme til kontaktlinse merker. La oss lage en pen
# oversikt over kun alle merker her, ogs√• iwear og de." -- erstatter den
# tidligere "Bla etter produsent"-listen (som pekte til /produsent/-sidene)
# med en komplett, alfabetisk liste over ALLE /merke/-sider: ekte merker
# (FOOTER_BRANDS) OG optikerkjedenes egne serier (PRIVATE_LABEL_SUBBRANDS)
# om hverandre -- bevisst IKKE splittet i to seksjoner slik footeren gj√∏r
# det (footeren skiller dem eksplisitt), siden Kai her spesifikt ba om at
# iWear m.fl. skal st√• sammen med de andre i √©n oversikt. Bygget fra de to
# samme, allerede etablerte kildelistene -- ingen tredje merkeliste √•
# holde manuelt i sync ved siden av disse to. Ligger her (ikke sammen med
# de andre _MEGA_*-konstantene lenger oppe i filen) fordi den avhenger av
# begge -- FOOTER_BRANDS og PRIVATE_LABEL_SUBBRANDS er begge definert
# tidligere i modulen enn dette punktet, men etter _MEGA_TOP_BRANDS m.fl.
_MEGA_ALL_BRANDS = sorted(
    FOOTER_BRANDS + [(subbrand.lower(), subbrand) for subbrand in PRIVATE_LABEL_SUBBRANDS.values()],
    key=lambda t: t[1].lower(),
)
_MEGA_ALL_BRANDS_HTML = "\n        ".join(
    f'<a class="mega-menu-link mega-allbrands-link" href="/merke/{slug}/">{escape(name)}</a>' for slug, name in _MEGA_ALL_BRANDS
)

# Egne (ikke offisielle/registrerte) ordmerke-logoer for seriene, laget av
# bruker 2026-08-30 -- IKKE hentet fra kjeden, se disclaimer-avsnittet i
# render_illustration_disclaimer_page(). Filene er besk√•ret fra brukerens
# eget bilde med (R)-merket fjernet (bevisst -- disse er ikke registrerte
# varemerker, s√• et ¬Æ ville v√¶rt misvisende). N√∏kkel er SERIENAVNET
# (PRIVATE_LABEL_SUBBRANDS sin verdi), aldri kjeden. iWear/Lumiere7 mangler
# fortsatt en fil/produktkobling.
PRIVATE_LABEL_SUBBRAND_LOGOS: dict[str, str] = {
    "EyeQ": "pl-eyeq.png",
    "Easyvision": "pl-easyvision.png",
    "Ascend": "pl-ascend.png",
}

# L√ÖST rekkef√∏lge (satt 2026-08-30, bekreftet l√•st -- ikke tidsstyrt --
# 2026-08-31). Se den fyldige begrunnelsen i render_home_page() der denne
# brukes. Lest direkte av lenspricer.no sin faktiske forside (bilde-
# alt-tekster p√• merke-rutenettet, i den rekkef√∏lgen de vises der)
# 2026-08-30, med to bevisste ombytter (Acuvue<->Dailies, Biomedics<->ULTRA)
# for √• ikke v√¶re en 1:1-kopi. IKKE vist noe sted p√• siden -- brukeren har
# eksplisitt bekreftet at dette forblir en ren intern/kode-detalj.
# Opprinnelig tenkt som midlertidig (erstattes av ekte trafikktall etter
# ~3 m√•neder), men bruker bestemte 2026-08-31 at rangeringen i stedet
# skal st√• fast ut 2026 -- ingen automatisk overgang til trafikkbasert
# sortering er planlagt lenger. Endre kun denne listen n√•r bruker
# eksplisitt ber om det, ikke p√• en tidsfrist.
LENSPRICER_INSPIRED_ORDER: list[str] = [
    "acuvue", "dailies", "biofinity", "iwear", "easyvision", "eyeq",
    "soflens", "biotrue", "clariti", "air-optix", "myday", "purevision",
    "precision1", "proclear", "live", "biomedics", "ultra", "avaira",
    "total30", "precision7",
]
_LENSPRICER_RANK: dict[str, int] = {slug: i for i, slug in enumerate(LENSPRICER_INSPIRED_ORDER)}

# ---------------------------------------------------------------------------
# Private label-illustrasjoner (2026-08-30). Kjedenes egne private
# label-serier har ikke en egen ordmerke-logo eller eget produktbilde vi kan
# vise (kun produktbilder av det EKTE produktets emballasje, som ville vist
# feil boks under feil navn) -- bruker har derfor levert egne, ikke-
# fotografiske illustrasjoner per serie (EyeQ/Ascend/Easyvision), bygget som
# CSS-farger/gradienter + tekst, ALDRI en p√•stand om ekte produktemballasje.
# Se render_illustration_disclaimer_page() for teksten som forklarer dette
# (lenket fra hvert sted en illustrasjon vises). Design-canvaset i de
# originale mockupene var 560x225px -- alle m√•l under er konvertert til cqw
# (container query width, relativt til elementets EGEN bredde via
# container-type:inline-size) slik at illustrasjonen skalerer korrekt uansett
# hvor liten/stor boksen den vises i er (mobil-merkekort vs. produktrutenett).
# Klassenavn er prefikset (pli-eyeq-/pli-ascend-/pli-ev-) for √• aldri kunne
# kollidere med andre klasser i SHARED_STYLE (f.eks. .active/.variant/.count
# er alle for generiske navn til √• la st√• uprefikset i en s√• stor stilark).
PRIVATE_LABEL_ILLUSTRATION_STYLE = """
.pli-eyeq-box{position:relative;width:100%;height:100%;background:#fff;border-radius:7px;overflow:hidden}
.pli-eyeq-qbox{display:grid;grid-template-columns:58% 42%;align-items:stretch}
.pli-eyeq-qvisual{display:flex;align-items:center;justify-content:center;padding:1.786cqw 0.714cqw 1.786cqw 2.5cqw;overflow:hidden}
.pli-eyeq-qmark{font-size:23.571cqw;line-height:.8;font-weight:950;letter-spacing:-.105em;background:var(--g);-webkit-background-clip:text;background-clip:text;color:transparent}
.pli-eyeq-copy{padding:6.071cqw 10.357cqw 4.286cqw 1.786cqw;display:flex;flex-direction:column;justify-content:space-between;min-width:0;height:100%;box-sizing:border-box}
.pli-eyeq-wear,.pli-eyeq-variant{font-weight:850;letter-spacing:.03em;line-height:1.05}
.pli-eyeq-wear{font-size:3.036cqw}
.pli-eyeq-variant{font-size:2.857cqw;margin-top:.357cqw}
.pli-eyeq-micro{font-size:1.25cqw;letter-spacing:.09em;margin-top:2.143cqw;color:#606770;font-weight:650}
.pli-eyeq-eyeq-vertical{position:absolute;top:1.25cqw;right:.893cqw;bottom:1.25cqw;writing-mode:vertical-rl;transform:rotate(180deg);display:flex;align-items:center;justify-content:center;font-size:7.679cqw;font-weight:950;letter-spacing:.055em;line-height:.86;background:var(--g);-webkit-background-clip:text;background-clip:text;color:transparent}
.pli-eyeq-q1{--g:radial-gradient(circle at 30% 18%,#f5cf84 0 10%,#dd8c67 24%,#9b5b8c 44%,#59356f 65%,#28274f 100%)}
.pli-eyeq-q2{--g:radial-gradient(circle at 66% 22%,#80dadd 0 11%,#5caecb 22%,#7c5faa 45%,#3a427d 67%,#172750 100%)}
.pli-eyeq-q3{--g:radial-gradient(circle at 35% 20%,#c9eb97 0 11%,#59c7aa 25%,#2a99aa 43%,#4c6ba8 65%,#352a60 100%)}
.pli-eyeq-q4{--g:radial-gradient(circle at 31% 21%,#7bd9cf 0 10%,#2d8f9c 24%,#504c9d 43%,#8e358a 64%,#2b285f 100%)}
.pli-eyeq-q5{--g:radial-gradient(circle at 27% 18%,#f9d68c 0 10%,#e47e94 25%,#b43876 44%,#672360 66%,#270d3d 100%)}
.pli-eyeq-precision{display:grid;grid-template-columns:60% 40%;background:linear-gradient(112deg,#16bec3 0%,#0d91af 39%,#0a5ca1 60%,#fff 60.4%);--g:linear-gradient(90deg,#fff,#e1fbff)}
.pli-eyeq-precision .pli-eyeq-qvisual{justify-content:flex-start;padding-left:4.286cqw}
.pli-eyeq-precision .pli-eyeq-qmark{font-size:12.857cqw;letter-spacing:-.05em;color:#fff;background:none;-webkit-text-fill-color:#fff}
.pli-eyeq-precision .pli-eyeq-copy{padding:6.071cqw 3.571cqw 4.286cqw 2.857cqw}
.pli-eyeq-precision .pli-eyeq-wear,.pli-eyeq-precision .pli-eyeq-variant{color:#123c6e}
.pli-eyeq-precision .pli-eyeq-micro{color:#567}
.pli-eyeq-precision .pli-eyeq-eyeq-horizontal{font-size:5.536cqw;font-weight:950;letter-spacing:.06em;color:#12528a}
.pli-eyeq-total30{display:grid;grid-template-columns:60% 40%;background:linear-gradient(118deg,#132b73 0 55%,#d7aa4d 55.4% 69%,#fff 69.4%);--g:linear-gradient(135deg,#fff,#c9d8ff)}
.pli-eyeq-total30 .pli-eyeq-qvisual{justify-content:flex-start;padding-left:4.286cqw}
.pli-eyeq-total30 .pli-eyeq-qmark{font-size:13.393cqw;letter-spacing:-.06em}
.pli-eyeq-total30 .pli-eyeq-copy{padding:6.071cqw 3.393cqw 4.286cqw 2.5cqw}
.pli-eyeq-total30 .pli-eyeq-wear,.pli-eyeq-total30 .pli-eyeq-variant{color:#17336e}
.pli-eyeq-total30 .pli-eyeq-eyeq-horizontal{font-size:5.536cqw;font-weight:950;letter-spacing:.06em;color:#17336e}

.pli-ascend-pack{width:100%;height:100%;background:#fff;border-radius:7px;overflow:hidden;position:relative}
.pli-ascend-content{position:absolute;z-index:3;left:6.429cqw;top:6.607cqw}
.pli-ascend-maker{font-size:1.964cqw;color:#777;margin-bottom:1.429cqw;letter-spacing:.01em}
.pli-ascend-wordmark{font-size:9.643cqw;font-weight:300;letter-spacing:-.055em;line-height:.88;color:#707174}
.pli-ascend-variant{font-size:3.75cqw;font-weight:400;color:var(--accent);margin-top:1.429cqw;letter-spacing:-.02em}
.pli-ascend-desc{font-size:1.429cqw;color:#8b8c8f;margin-top:.893cqw}
.pli-ascend-qty{position:absolute;right:3.929cqw;top:3.571cqw;font-size:1.964cqw;color:#85878a;z-index:4}
.pli-ascend-sweep1,.pli-ascend-sweep2{position:absolute;left:-7%;width:118%;border-radius:0 0 55% 35%/0 0 90% 80%;transform:rotate(-2deg);transform-origin:center}
.pli-ascend-sweep1{height:16.25cqw;bottom:4.464cqw;background:#c7c8ca;z-index:1}
.pli-ascend-sweep2{height:14.643cqw;bottom:-3.571cqw;background:var(--accent);z-index:2}
.pli-ascend-corner{position:absolute;right:2.857cqw;bottom:2.143cqw;z-index:4;width:16.964cqw;height:6.071cqw;border:2px solid rgba(255,255,255,.75);border-left-color:transparent;transform:skewX(-18deg)}
.pli-ascend-active{--accent:#169348}
.pli-ascend-active-mf{--accent:#078fa2}
.pli-ascend-active-toric{--accent:#147ca4}
.pli-ascend-evolve{--accent:#73a930}
.pli-ascend-evolve-toric{--accent:#4f8fa7}
.pli-ascend-premier{--accent:#2452a0}
.pli-ascend-premier-toric{--accent:#2854a5}
.pli-ascend-premier-mf{--accent:#283467}

.pli-ev-pack{width:100%;height:100%;border-radius:7px;overflow:hidden;position:relative;background:var(--bg,#fff)}
.pli-ev-pack-inner{position:absolute;inset:0;display:flex}
.pli-ev-left{width:66%;padding:6.071cqw 3.571cqw 3.75cqw 5cqw;display:flex;flex-direction:column;justify-content:space-between;position:relative;z-index:2;box-sizing:border-box}
.pli-ev-count{position:absolute;top:0;left:0;min-width:23.571cqw;padding:1.429cqw 3.214cqw 1.429cqw 3.571cqw;border-bottom-right-radius:28px;background:var(--count,#55c9c6);color:#fff;font-size:1.964cqw;font-weight:750;line-height:1.05}
.pli-ev-count strong{font-size:4.107cqw;margin-right:.714cqw;vertical-align:-.357cqw}
.pli-ev-brand{margin-top:6.071cqw}
.pli-ev-easy{font-size:6.607cqw;font-weight:350;letter-spacing:-.045em;line-height:.88;color:var(--brand,#fff)}
.pli-ev-easy b{font-weight:760}
.pli-ev-variant{margin-top:1.964cqw;font-size:3.036cqw;font-weight:760;color:var(--accent,#fff)}
.pli-ev-micro{font-size:1.25cqw;line-height:1.25;color:var(--micro,rgba(255,255,255,.75));max-width:41.071cqw}
.pli-ev-mosaic{width:40%;position:absolute;right:-.357cqw;top:0;bottom:0;overflow:hidden}
.pli-ev-tile{position:absolute;width:11.071cqw;height:11.071cqw;border-radius:0 0 62px 0;opacity:.98}
.pli-ev-t1{right:20cqw;top:0;background:#fff}
.pli-ev-t2{right:8.929cqw;top:0;background:#247aa1;transform:rotate(90deg)}
.pli-ev-t3{right:-2.143cqw;top:0;background:#dce633;transform:rotate(180deg)}
.pli-ev-t4{right:14.643cqw;top:11.071cqw;background:#52c4c0;transform:rotate(270deg)}
.pli-ev-t5{right:3.571cqw;top:11.071cqw;background:#fff;transform:rotate(90deg)}
.pli-ev-t6{right:-7.5cqw;top:11.071cqw;background:#20739a}
.pli-ev-t7{right:20cqw;top:22.143cqw;background:#dce633;transform:rotate(180deg)}
.pli-ev-t8{right:8.929cqw;top:22.143cqw;background:#2f86a6;transform:rotate(270deg)}
.pli-ev-t9{right:-2.143cqw;top:22.143cqw;background:#d7eff0;transform:rotate(90deg)}
.pli-ev-t10{right:3.214cqw;top:33.214cqw;background:#58c8c1;transform:rotate(180deg)}
.pli-ev-vitrea,.pli-ev-umere,.pli-ev-vitrea-toric,.pli-ev-umere-toric,.pli-ev-vitrea-mf{--bg:#fff;--brand:#777d82;--micro:#9aa0a5;--count:#54c8c5;--accent:#43bdb9}
.pli-ev-vitrea-toric,.pli-ev-umere-toric{--count:#1b9ab7;--accent:#168faf}
.pli-ev-vitrea-mf{--count:#48a957;--accent:#4cab59}
.pli-ev-vitrea .pli-ev-mosaic,.pli-ev-umere .pli-ev-mosaic,.pli-ev-vitrea-toric .pli-ev-mosaic,.pli-ev-umere-toric .pli-ev-mosaic,.pli-ev-vitrea-mf .pli-ev-mosaic{width:43%}
.pli-ev-uvicia,.pli-ev-uvicia-toric{--bg:#62bdbc;--brand:#fff;--micro:rgba(255,255,255,.84);--count:#fff;--accent:#fff}
.pli-ev-uvicia .pli-ev-count,.pli-ev-uvicia-toric .pli-ev-count{color:#57b9b8;background:#fff}
.pli-ev-uvicia-toric{--bg:#5aa4be}
.pli-ev-opteyes,.pli-ev-opteyes-toric,.pli-ev-opteyes-mf{--bg:#69c2c0;--brand:#fff;--micro:rgba(255,255,255,.82);--count:#fff;--accent:#fff}
.pli-ev-opteyes .pli-ev-count,.pli-ev-opteyes-toric .pli-ev-count,.pli-ev-opteyes-mf .pli-ev-count{color:#58b9b8;background:#fff}
.pli-ev-opteyes-toric{--bg:#5798b3}
.pli-ev-opteyes-mf{--bg:#4f9ea1}
.pli-ev-uvicia-toric .pli-ev-t4,.pli-ev-opteyes-toric .pli-ev-t4,.pli-ev-umere-toric .pli-ev-t4,.pli-ev-vitrea-toric .pli-ev-t4{background:#1d6fa0}
.pli-ev-opteyes-mf .pli-ev-t3,.pli-ev-vitrea-mf .pli-ev-t3{background:#65b967}
.pli-ev-opteyes-mf .pli-ev-t7,.pli-ev-vitrea-mf .pli-ev-t7{background:#dfe94a}
.pli-caption{display:block;font-size:.68rem;color:var(--muted);margin-top:4px;text-decoration:none}
.pli-caption:hover{text-decoration:underline}
/* De 3 illustrasjons-familiene er tegnet for et 560x225px (~2.49:1) design-
   canvas, MYE bredere/flatere enn de vanlige produktbilde-boksene (4:3 p√•
   merkekort, fast 190px h√∏yde p√• produktfliser) -- strekkes de inn i disse
   uendret, blir de visuelt forvrengt. .pli-frame overstyrer merkekortets
   aspect-ratio til illustrasjonens EGEN, og .pli-tile-wrap gir samme
   effekt p√• produktfliser (der boksen har fast h√∏yde + sentrerer innholdet
   i stedet for aspect-ratio) ved √• style bredden i stedet, med h√∏yden
   utledet automatisk via cqw i selve illustrasjonen. */
/* .pli-frame er n√• en INDRE wrapper inni .brand-card-photo (ikke lenger
   satt direkte p√• .brand-card-photo selv) -- .brand-card-photo beholder
   sin vanlige 4:3-boks som ALLE kort (bilde eller illustrasjon) deler,
   slik at rutenettet stretcher til lik h√∏yde uten √• bli rotete (funnet
   og fikset 2026-08-30: ulik boks-h√∏yde mellom bilde-kort og
   illustrasjon-kort ga et synlig ujevnt rutenett n√•r PC-versjonen fikk
   samme bildef√∏rte kort som mobil). Illustrasjonen sentreres i stedet
   for √• strekkes/forvrenges, med sin egen naturlige 560:225-proporsjon
   bevart inni den delte 4:3-boksen. */
.pli-tile-wrap{width:86%;aspect-ratio:560/225;container-type:inline-size}

/* iWear (Brilleland) -- levert 2026-08-30, samme dag som en midlertidig
   tekst-ordmerke (se _pli_iwear_logo_html()) siden brukerens fil selv sier
   "ikke offisiell iWear-logo". Samme 560x225-canvas/cqw-teknikk som de tre
   andre seriene. */
.pli-iwear-pack{width:100%;height:100%;position:relative;overflow:hidden;background:#fff;border-radius:7px;--c1:#078e91;--c2:#11b8ad}
.pli-iwear-band{height:3.214cqw;background:var(--c1)}
.pli-iwear-copy{position:absolute;left:4.821cqw;top:8.393cqw;z-index:3}
.pli-iwear-brand{font-size:8.393cqw;font-weight:750;letter-spacing:-.055em}
.pli-iwear-brand i{font-style:normal;color:var(--c1)}
.pli-iwear-variant{font-size:3.393cqw;color:var(--c1);text-transform:lowercase}
.pli-iwear-kind{font-size:1.429cqw;color:#777;margin-top:1.071cqw}
.pli-iwear-qty{position:absolute;left:5.000cqw;bottom:4.286cqw;font-size:5.000cqw;font-weight:750;z-index:3}
.pli-iwear-qty span{display:block;font-size:1.250cqw;margin-top:0.893cqw}
.pli-iwear-art{position:absolute;right:-2.679cqw;top:3.214cqw;width:48%;height:36.964cqw;background:radial-gradient(circle at 52% 50%,#fff 0 23%,transparent 24%),radial-gradient(ellipse at 55% 50%,transparent 0 31%,var(--c2) 32% 35%,transparent 36% 43%,var(--c1) 44% 53%,transparent 54%),linear-gradient(135deg,#fff 0 5%,var(--c2) 6% 44%,var(--c1) 45% 100%);border-radius:52% 0 0 52%}
.pli-iwear-fit{--c1:#78b75a;--c2:#b7df83}
.pli-iwear-fresh{--c1:#51a6c4;--c2:#94d4dd}
.pli-iwear-activ{--c1:#087f82;--c2:#12b7a9}
.pli-iwear-harmony{--c1:#6c258f;--c2:#a967c5}
.pli-iwear-oxygen{--c1:#0b78a0;--c2:#52b6d0}
.pli-iwear-balance{--c1:#489aa8;--c2:#91c6b5}
.pli-iwear-oxygen-relax{--c1:#173d99;--c2:#32a6df}
.pli-iwear-go-toric{--c1:#0b7561;--c2:#44b18c}
.pli-iwear-fit-toric{--c1:#5d9e64;--c2:#8bc68b}
.pli-iwear-activ-toric{--c1:#08709b;--c2:#16aaa8}
.pli-iwear-harmony-toric{--c1:#6c168f;--c2:#b060c6}
.pli-iwear-oxygen-toric{--c1:#11679e;--c2:#3b9fc7}
.pli-iwear-balance-toric{--c1:#367b9c;--c2:#6eb4b4}
.pli-iwear-oxygen-mf{--c1:#31539d;--c2:#658fd1}
"""

# name -> (mark, wear, variant, family) hentet direkte fra brukerens
# eyeq-illustrasjonspakke-v4.html sitt products-array, n√∏kkel byttet fra
# navn til private_labels.json sin slug (samme 20 EyeQ/Synsam-oppf√∏ringer).
EYEQ_ILLUSTRATIONS: dict[str, dict] = {
    "eyeq-24": {"mark": "Q4", "wear": "MONTHLY", "variant": "24", "family": "q4"},
    "eyeq-24-for-astigmatism": {"mark": "Q4", "wear": "MONTHLY", "variant": "ASTIGMATISM", "family": "q4"},
    "eyeq-24-progressive": {"mark": "Q4", "wear": "MONTHLY", "variant": "PROGRESSIVE", "family": "q4"},
    "eyeq-digital-focus": {"mark": "Q5", "wear": "MONTHLY", "variant": "DIGITAL FOCUS", "family": "q5"},
    "eyeq-24-xr": {"mark": "Q4", "wear": "MONTHLY", "variant": "24 XR", "family": "q4"},
    "eyeq-one-day-classic": {"mark": "Q2", "wear": "1-DAY", "variant": "CLASSIC", "family": "q2"},
    "eyeq-one-day-classic-for-astigmatism": {"mark": "Q2", "wear": "1-DAY", "variant": "ASTIGMATISM", "family": "q2"},
    "eyeq-toric-classic": {"mark": "Q1", "wear": "MONTHLY", "variant": "ASTIGMATISM", "family": "q1"},
    "eyeq-one-day-premium": {"mark": "Q3", "wear": "1-DAY", "variant": "PREMIUM", "family": "q3"},
    "eyeq-one-day-premium-progressive": {"mark": "Q3", "wear": "1-DAY", "variant": "PROGRESSIVE", "family": "q3"},
    "eyeq-premium": {"mark": "Q2", "wear": "MONTHLY", "variant": "PREMIUM", "family": "q2"},
    "eyeq-premium-for-astigmatism": {"mark": "Q2", "wear": "MONTHLY", "variant": "ASTIGMATISM", "family": "q2"},
    "eyeq-premium-progressive": {"mark": "Q2", "wear": "MONTHLY", "variant": "PROGRESSIVE", "family": "q2"},
    "eyeq-hydro": {"mark": "Q3", "wear": "MONTHLY", "variant": "HYDRO", "family": "q3"},
    "eyeq-hydro-for-astigmatism": {"mark": "Q3", "wear": "MONTHLY", "variant": "ASTIGMATISM", "family": "q3"},
    "eyeq-hydro-progressive": {"mark": "Q3", "wear": "MONTHLY", "variant": "PROGRESSIVE", "family": "q3"},
    "eyeq-total30": {"mark": "T30", "wear": "MONTHLY", "variant": "TOTAL 30", "family": "total30"},
    "eyeq-total30-for-astigmatism": {"mark": "T30", "wear": "MONTHLY", "variant": "FOR ASTIGMATISM", "family": "total30"},
    "eyeq-precision1": {"mark": "P1", "wear": "1-DAY", "variant": "PRECISION 1", "family": "precision"},
    "eyeq-precision1-for-astigmatism": {"mark": "P1", "wear": "1-DAY", "variant": "FOR ASTIGMATISM", "family": "precision"},
}

# Fra ascend-illustrasjonspakke-v1.html -- "maker" (CooperVision) er den
# EKTE produsenten bak Ascend-serien, ikke kjeden (Coptikk), s√• den nevnes
# fortsatt -- kun kjedenavnet (Coptikk) er det brukeren ikke vil ha med her.
ASCEND_ILLUSTRATIONS: dict[str, dict] = {
    "ascend-evolve-plus": {"variant": "evolve+", "qty": "6", "desc": "monthly contact lenses", "family": "evolve"},
    "ascend-active-1-day": {"variant": "active", "qty": "30", "desc": "daily disposable contact lenses", "family": "active"},
    "ascend-premier": {"variant": "premier", "qty": "6", "desc": "monthly contact lenses", "family": "premier"},
    "ascend-active-multifocal-1-day": {"variant": "active multifocal", "qty": "30", "desc": "multifocal contact lenses", "family": "active-mf"},
    "ascend-evolve-plus-toric": {"variant": "evolve+ toric", "qty": "6", "desc": "contact lenses for astigmatism", "family": "evolve-toric"},
    "ascend-active-toric-1-day": {"variant": "active toric", "qty": "30", "desc": "contact lenses for astigmatism", "family": "active-toric"},
    "ascend-premier-toric": {"variant": "premier toric", "qty": "6", "desc": "contact lenses for astigmatism", "family": "premier-toric"},
    "ascend-premier-multifocal-distance": {"variant": "premier multifocal ¬∑ distance", "qty": "6", "desc": "multifocal contact lenses", "family": "premier-mf"},
    "ascend-premier-multifocal-near": {"variant": "premier multifocal ¬∑ near", "qty": "6", "desc": "multifocal contact lenses", "family": "premier-mf"},
}

# Fra easyvision-illustrasjonspakke-v1.html. Den originale pakken hadde en
# "Specsavers"-tekstlinje √∏verst i illustrasjonen -- FJERNET her med vilje
# (bruker: "vi nevner igjen ikke specsavers"), resten av illustrasjonen er
# uendret fra det brukeren sendte.
EASYVISION_ILLUSTRATIONS: dict[str, dict] = {
    "easyvision-opteyes": {"variant": "Opteyes", "qty": "6", "label": "monthly<br>contact lenses", "family": "opteyes"},
    "easyvision-opteyes-toric": {"variant": "Opteyes Toric", "qty": "6", "label": "contact lenses<br>for astigmatism", "family": "opteyes-toric"},
    "easyvision-opteyes-multifocal": {"variant": "Opteyes Multifocal", "qty": "6", "label": "multifocal<br>contact lenses", "family": "opteyes-mf"},
    "easyvision-opteyes-xr": {"variant": "Opteyes XR", "qty": "3x", "label": "monthly<br>contact lenses", "family": "opteyes"},
    "easyvision-uvicia-plus": {"variant": "Uvicia Plus", "qty": "6x", "label": "monthly<br>contact lenses", "family": "uvicia"},
    "easyvision-uvicia-plus-toric": {"variant": "Uvicia Toric Plus", "qty": "6x", "label": "contact lenses<br>for astigmatism", "family": "uvicia-toric"},
    "easyvision-umere": {"variant": "Umere", "qty": "30", "label": "daily disposable<br>contact lenses", "family": "umere"},
    "easyvision-umere-toric": {"variant": "Umere Toric", "qty": "30", "label": "contact lenses<br>for astigmatism", "family": "umere-toric"},
    "easyvision-vitrea": {"variant": "Vitrea", "qty": "30", "label": "daily disposable<br>contact lenses", "family": "vitrea"},
    "easyvision-vitrea-toric": {"variant": "Vitrea Toric", "qty": "30", "label": "contact lenses<br>for astigmatism", "family": "vitrea-toric"},
    "easyvision-vitrea-multifocal": {"variant": "Vitrea Multifocal", "qty": "30", "label": "multifocal<br>contact lenses", "family": "vitrea-mf"},
}


def _pli_eyeq(slug: str) -> str | None:
    d = EYEQ_ILLUSTRATIONS.get(slug)
    if not d:
        return None
    q_family = d["family"].startswith("q")
    box_cls = f'pli-eyeq-box {"pli-eyeq-qbox " if q_family else ""}pli-eyeq-{d["family"]}'
    vertical_html = '<div class="pli-eyeq-eyeq-vertical">EYEQ</div>' if q_family else ""
    horizontal_html = "" if q_family else '<div class="pli-eyeq-eyeq-horizontal">EYEQ</div>'
    return f"""<div class="{box_cls}" role="img" aria-label="Illustrasjon, ikke et ekte produktbilde">
  <div class="pli-eyeq-qvisual"><div class="pli-eyeq-qmark">{escape(d["mark"])}</div></div>
  <div class="pli-eyeq-copy">
    <div>
      <div class="pli-eyeq-wear">{escape(d["wear"])}</div>
      <div class="pli-eyeq-variant">{escape(d["variant"])}</div>
      <div class="pli-eyeq-micro">CONTACT LENS</div>
    </div>
    {horizontal_html}
  </div>
  {vertical_html}
</div>"""


def _pli_ascend(slug: str) -> str | None:
    d = ASCEND_ILLUSTRATIONS.get(slug)
    if not d:
        return None
    return f"""<div class="pli-ascend-pack pli-ascend-{d["family"]}" role="img" aria-label="Illustrasjon, ikke et ekte produktbilde">
  <div class="pli-ascend-content">
    <div class="pli-ascend-maker">CooperVision</div>
    <div class="pli-ascend-wordmark">ascend</div>
    <div class="pli-ascend-variant">{escape(d["variant"])}</div>
    <div class="pli-ascend-desc">{escape(d["desc"])}</div>
  </div>
  <div class="pli-ascend-qty">{escape(d["qty"])} lenses</div>
  <div class="pli-ascend-sweep1"></div>
  <div class="pli-ascend-sweep2"></div>
  <div class="pli-ascend-corner"></div>
</div>"""


def _pli_easyvision(slug: str) -> str | None:
    d = EASYVISION_ILLUSTRATIONS.get(slug)
    if not d:
        return None
    tiles = "".join(f'<i class="pli-ev-tile pli-ev-t{i}"></i>' for i in range(1, 11))
    return f"""<div class="pli-ev-pack pli-ev-{d["family"]}" role="img" aria-label="Illustrasjon, ikke et ekte produktbilde">
  <div class="pli-ev-pack-inner">
    <div class="pli-ev-left">
      <div class="pli-ev-count"><strong>{escape(d["qty"])}</strong>{d["label"]}</div>
      <div class="pli-ev-brand">
        <div class="pli-ev-easy">easy<b>vision</b></div>
        <div class="pli-ev-variant">{escape(d["variant"])}</div>
      </div>
      <div class="pli-ev-micro">CONTACT LENS &middot; PRODUCT ILLUSTRATION</div>
    </div>
    <div class="pli-ev-mosaic">{tiles}</div>
  </div>
</div>"""


# Fra iwear-produktsett-og-logo-v1.html (2026-08-30).
IWEAR_ILLUSTRATIONS: dict[str, dict] = {
    "iwear-oxygen": {"variant": "Oxygen", "qty": "6", "kind": "MONTHLY LENSES", "family": "oxygen"},
    "iwear-oxygen-astigmatism": {"variant": "Oxygen Astigmatism", "qty": "6", "kind": "FOR ASTIGMATISM", "family": "oxygen-toric"},
    "iwear-oxygen-presbyopia": {"variant": "Oxygen Presbyopia", "qty": "6", "kind": "MULTIFOCAL LENSES", "family": "oxygen-mf"},
    "iwear-oxygen-relax": {"variant": "Oxygen Relax", "qty": "3", "kind": "MONTHLY LENSES", "family": "oxygen-relax"},
    "iwear-oxygen-xr": {"variant": "Oxygen XR", "qty": "3", "kind": "MONTHLY LENSES", "family": "oxygen"},
    "iwear-balance-plus": {"variant": "Balance Plus", "qty": "6", "kind": "MONTHLY LENSES", "family": "balance"},
    "iwear-balance-plus-astigmatism": {"variant": "Balance Plus Astigmatism", "qty": "6", "kind": "FOR ASTIGMATISM", "family": "balance-toric"},
    "iwear-fit": {"variant": "Fit", "qty": "30", "kind": "DAILY LENSES", "family": "fit"},
    "iwear-fit-astigmatism": {"variant": "Fit Astigmatism", "qty": "30", "kind": "FOR ASTIGMATISM", "family": "fit-toric"},
    "iwear-go-astigmatism": {"variant": "Go Astigmatism", "qty": "6", "kind": "FOR ASTIGMATISM", "family": "go-toric"},
    "iwear-harmony": {"variant": "Harmony", "qty": "30", "kind": "DAILY LENSES", "family": "harmony"},
    "iwear-harmony-astigmatism": {"variant": "Harmony Astigmatism", "qty": "30", "kind": "FOR ASTIGMATISM", "family": "harmony-toric"},
    "iwear-activ": {"variant": "Activ", "qty": "30", "kind": "DAILY LENSES", "family": "activ"},
    "iwear-activ-astigmatism": {"variant": "Activ Astigmatism", "qty": "30", "kind": "FOR ASTIGMATISM", "family": "activ-toric"},
    "iwear-fresh": {"variant": "Fresh", "qty": "30", "kind": "DAILY LENSES", "family": "fresh"},
}


def _pli_iwear(slug: str) -> str | None:
    d = IWEAR_ILLUSTRATIONS.get(slug)
    if not d:
        return None
    return f"""<div class="pli-iwear-pack pli-iwear-{d["family"]}" role="img" aria-label="Illustrasjon, ikke et ekte produktbilde">
  <div class="pli-iwear-band"></div>
  <div class="pli-iwear-copy">
    <div class="pli-iwear-brand"><i>i</i>Wear</div>
    <div class="pli-iwear-variant">{escape(d["variant"])}</div>
    <div class="pli-iwear-kind">{escape(d["kind"])}</div>
  </div>
  <div class="pli-iwear-qty">{escape(d["qty"])}<span>{escape(d["kind"])}</span></div>
  <div class="pli-iwear-art"></div>
</div>"""


TRUELENS_ILLUSTRATIONS = {
    "truelens-premium-daily", "truelens-platinum-daily", "truelens-platinum-daily-toric",
    "truelens-platinum-daily-multifocal", "truelens-premium-monthly", "truelens-premium-monthly-toric",
    "truelens-premium-monthly-multifocal", "truelens-platinum-monthly", "truelens-platinum-monthly-toric",
    "truelens-platinum-monthly-multifocal",
}


def _pli_truelens(slug: str) -> str | None:
    """TrueLens (Mister Spex)-illustrasjoner -- i motsetning til de tre andre
    kjedene (rene CSS-tegnede "fake bokser", se _pli_iwear() m.fl.) er dette
    ekte rasterbilder Kai leverte 2026-09-29 (kuttet fra et samlet
    referanseark han selv sa er "Illustrasjoner av TrueLens-serien. Faktisk
    emballasje kan avvike."). Egne, ikke-offisielle mockups av TrueLens-
    emballasjen, IKKE offisielle produktbilder fra Mister Spex -- samme
    "illustrasjon, ikke ekte produktbilde"-behandling som de tre andre
    kjedene likevel, per eksplisitt instruks. object-fit:contain (ikke
    cover) siden bildene er portrettformat (~1,25:1) mens den delte
    .pli-tile-wrap/.pli-frame er tegnet for de andre kjedenes brede
    2,49:1-illustrasjonscanvas -- contain unng√•r at boksmotivet beskj√¶res,
    p√• bekostning av synlig luft i sidekantene p√• det brede rutenett-kortet.

    Rot-√•rsak funnet 2026-09-29 (etter to mislykkede fors√∏k -- fast px-grense,
    s√• prosent-grense, begge uten effekt): den delte `.pli-tile-wrap` (satt
    av KALLEREN, ikke her) har `aspect-ratio:560/225`, men INGEN
    `overflow:hidden` p√• seg selv. Uten det ignorerer CSS-motoren
    aspect-ratio n√•r et barn sitt "automatic minimum size" (min-content)
    krever mer plass -- og et bilde i portrettformat (340√ó~270,
    height:auto) krever nettopp det, s√• `.pli-tile-wrap` ble stille strukket
    til bildets EGEN ratio (~1,25:1) i stedet for den tiltenkte 2,49:1,
    og spiste dermed opp all plassen "Egen illustrasjon..."-bildeteksten
    trengte (bekreftet med getBoundingClientRect(): `.pli-tile-wrap` sin
    egen h√∏yde matchet bildets naturlige ratio, ikke 560/225, uansett
    skjermbredde). De tre andre kjedenes CSS-tegnede illustrasjoner rammes
    aldri av dette siden ALT innholdet deres allerede er absolutt
    posisjonert (se `_pli_iwear()` m.fl.) -- de bidrar null til
    "automatic minimum size"-beregningen. L√∏sningen her er identisk:
    `<img>` tas ut av normal flyt med `position:absolute` inni en tom
    `position:relative`-wrapper (som selv IKKE bidrar med noe
    min-content-krav), slik at `.pli-tile-wrap` sin aspect-ratio endelig
    f√•r virke som tiltenkt, og bildeteksten f√•r plassen den trenger."""
    if slug not in TRUELENS_ILLUSTRATIONS:
        return None
    return (
        '<div style="position:relative;width:100%;height:100%;">'
        f'<img src="/static/private-label/{slug}.webp" alt="" loading="lazy" '
        'style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;" '
        'role="img" aria-label="Illustrasjon, ikke et ekte produktbilde">'
        '</div>'
    )


def render_private_label_illustration(chain: str, slug: str) -> str | None:
    """Returnerer illustrasjons-HTML for en private label-variant, eller None
    hvis vi ikke har noen. Kjeden brukes KUN til √• velge riktig visuell
    familie, aldri vist i selve illustrasjonen."""
    if chain == "Brilleland":
        return _pli_iwear(slug)
    if chain == "Synsam":
        return _pli_eyeq(slug)
    if chain == "Coptikk":
        return _pli_ascend(slug)
    if chain == "Specsavers":
        return _pli_easyvision(slug)
    if chain == "Mister Spex":
        return _pli_truelens(slug)
    return None


def render_illustration_disclaimer_page() -> str:
    """/om-produktillustrasjoner/ -- lenket fra hvert sted en egen
    illustrasjon (ikke et ekte produktbilde) ELLER en egen serie-logo
    (ikke kjedens offisielle/registrerte merke) vises. F√∏rste avsnitt er
    brukerens egen tekst om illustrasjonene, limt inn ordrett 2026-08-30.
    Andre avsnitt (om serie-logoene) er lagt til samme dag, etter
    brukerens eget √∏nske om √• utvide denne siden fremfor √• lage en egen --
    samme underliggende begrunnelse i begge tilfeller ("egen fremstilling,
    ikke offisielt materiale")."""
    body = """<p>Kontaktlinser.no benytter b√•de originale produktbilder og egne produktillustrasjoner. N√•r et originalt produktbilde ikke er tilgjengelig, kan vi bruke en egen illustrasjon for √• gj√∏re det enklere √• identifisere og sammenligne produkter. Slike illustrasjoner er ikke originale produktbilder eller offisiell produktemballasje fra produsenten. Utforming, farger, tekst og andre visuelle detaljer kan derfor avvike fra produktets faktiske emballasje.</p>
  <p>Enkelte optikerkjeders egne merkenavn (private label-serier som EyeQ, Ascend og Easyvision) vises med en egen, selvlaget ordmerke-logo i stedet for kjedens offisielle logo. Dette er ikke et registrert varemerke eller en offisiell logo fra kjeden -- det er en egen visuell fremstilling laget av kontaktlinser.no for √• gj√∏re seriene lettere √• kjenne igjen.</p>
  <p>Produktnavn, logoer og varemerker tilh√∏rer sine respektive rettighetshavere. Kontaktlinser.no er en uavhengig prissammenlignings- og informasjonstjeneste og selger ikke kontaktlinser selv.</p>"""
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "Om produktillustrasjoner", "item": "{BASE_URL}/om-produktillustrasjoner/"}}
  ]
}}"""
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Om produktillustrasjoner | Kontaktlinser.no</title>
<meta name="description" content="Hvorfor kontaktlinser.no noen ganger viser en egen illustrasjon i stedet for et ekte produktbilde.">
<link rel="canonical" href="{BASE_URL}/om-produktillustrasjoner/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> ‚Ä∫ Om produktillustrasjoner</p>
  <div class="hero"><div class="hero-copy"><h1>Om produktillustrasjoner</h1></div></div>
  <div style="max-width:720px;font-size:1rem;line-height:1.7;">
    {body}
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""

# Merke -> produsent-kobling (2026-08-18), verifisert ett og ett merke mot
# offisielle produsentkilder (aldri gjettet p√• navnelikhet) -- se agent-logg
# for kildene. KUN de fire globale produsentene + Eyemed Technologies (ADORE)
# dekker samtlige 18 linsemerker i katalogen per dags dato. Linsev√¶ske-/
# √∏yedr√•pe-merker (Opti-Free, Systane, ReNu, Hylo osv.) er bevisst IKKE med
# her enn√• -- egen runde om √∏nskelig, annen produsent-miks.
MANUFACTURERS = {
    "coopervision": {
        "name": "CooperVision",
        "official_url": "https://coopervision.no/",
        "official_url_label": "coopervision.no",
        "brand_slugs": ["biofinity", "proclear", "myday", "avaira", "clariti", "biomedics", "live", "misight"],
        "description_html": """
<p>CooperVision ble stiftet i 1980 som en egen forretningsenhet under det som i dag heter
The Cooper Companies, med hovedkontor i San Ramon, California. Selskapet er verdens
tredje st√∏rste produsent av myke kontaktlinser, og er s√¶rlig kjent for Aquaform Comfort
Science-materialet som brukes i Biofinity-serien.</p>
""",
    },
    "alcon": {
        "name": "Alcon",
        "official_url": "https://www.myalcon.com/no/contact-lenses/",
        "official_url_label": "myalcon.com/no",
        "brand_slugs": ["dailies", "air-optix", "precision1", "precision7", "total30", "freshlook"],
        "description_html": """
<p>Alcon ble grunnlagt i 1945 i Fort Worth, Texas, og har i dag hovedkontor i Gen√®ve i
Sveits etter √• ha blitt skilt ut som eget b√∏rsnotert selskap fra Novartis i 2019. Alcon
regnes som verdens st√∏rste √∏yehelseselskap, og st√•r bak vanngradient-teknologien i
Dailies Total1 og Precision7 ‚Äì markedets eneste linse godkjent for √©n ukes bruk.</p>
""",
    },
    "bausch-lomb": {
        "name": "Bausch + Lomb",
        "official_url": "https://www.bausch.no/",
        "official_url_label": "bausch.no",
        "brand_slugs": ["purevision", "soflens", "biotrue", "ultra"],
        "description_html": """
<p>Bausch + Lomb er et av bransjens eldste selskaper, grunnlagt i 1853 i Rochester, New
York av John Jacob Bausch og Henry Lomb. Selskapet regnes i dag som en av de fire st√∏rste
kontaktlinseprodusentene i verden, og st√•r bak MoistureSeal-teknologien i ULTRA-serien ‚Äì
Biotrue-produktene er utviklet med utgangspunkt i egenskapene til kroppens egen t√•refilm.</p>
""",
    },
    "jnj-vision": {
        "name": "Johnson & Johnson Vision",
        "official_url": "https://www.acuvue.com/nb-no",
        "official_url_label": "acuvue.com",
        "brand_slugs": ["acuvue"],
        "description_html": """
<p>Johnson & Johnson Vision lanserte i 1987 Acuvue ‚Äì verdens f√∏rste masseproduserte
engangskontaktlinse ‚Äì og regnes som verdens ledende produsent av engangslinser.
Acuvue-serien produseres blant annet ved selskapets anlegg i Irland.</p>
""",
    },
    "eyemed-technologies": {
        "name": "Eyemed Technologies",
        "official_url": "https://adorelenses.com/en/",
        "official_url_label": "adorelenses.com",
        "brand_slugs": ["adore"],
        "description_html": """
<p>Eyemed Technologies er en italiensk produsent med base i Casorate Sempione, spesialisert
p√• kosmetiske og fargede kontaktlinser under merkenavnet ADORE. Selskapet er vesentlig
mindre enn de tre globale produsentene over, med salg i over 30 land.</p>
""",
    },
    "menicon": {
        "name": "Menicon",
        "official_url": "https://www.menicon.com/consumer/",
        "official_url_label": "menicon.com",
        "brand_slugs": ["miru"],
        "description_html": """
<p>Menicon ble grunnlagt i 1951 av Kyoichi Tanaka og var Japans f√∏rste kontaktlinseprodusent.
Selskapet har hovedkontor i Nagoya og er i dag representert i over 80 land, med Miru-serien
som sin daglinse-satsning i det europeiske markedet.</p>
""",
    },
    "pegavision": {
        "name": "Pegavision",
        "official_url": "https://www.pegavision.com/en/",
        "official_url_label": "pegavision.com",
        "brand_slugs": ["clearlii"],
        "description_html": """
<p>Pegavision ble grunnlagt i 2009 som et joint venture mellom elektronikkkonsernene Pegatron
og Kinsus, med hovedkontor i Taoyuan i Taiwan. Selskapet er b√∏rsnotert (TSE: PEGAVISION) og
driver egen forskning, utvikling og produksjon av myke kontaktlinser ‚Äì blant annet
Clearlii-serien som selges gjennom nordiske apotek.</p>
""",
    },
}

BRAND_TO_MANUFACTURER: dict[str, str] = {
    brand_slug: manufacturer_slug
    for manufacturer_slug, data in MANUFACTURERS.items()
    for brand_slug in data["brand_slugs"]
}

# Original, faktabasert "om merket"-innhold for merke-sidene (2026-08-19).
# Materiale-/teknologinavn er verifisert direkte mot produsentens egne
# kilder (Bausch + Lomb pi.bausch.com/ecp.bauschcontactlenses.com m.fl.),
# ALDRI kopiert fra en forhandlers markedsf√∏ringstekst -- se f.eks.
# SofLens-runden der en forhandlerside p√•sto 70% vanninnhold generelt for
# dagslinsen, mens produsentens egen kilde bekrefter 59%. Plasseres UNDER
# produktlisten p√• merke-siden, ikke over -- prissammenligningen er
# fortsatt hovedfunksjonen, samme prinsipp som private label-sidene.
BRAND_CONTENT: dict[str, str] = {
    "soflens": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om SofLens</h2>
<p>SofLens er en linseserie fra Bausch + Lomb, et av bransjens eldste kontaktlinseselskaper
(grunnlagt i 1853). Serien dekker de fleste behov: dagslinser, m√•nedslinser, toriske linser
for astigmatisme og multifokale linser for alderssyn (presbyopi).</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i SofLens-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>SofLens Daily Disposable</strong> ‚Äì hilafilcon B, 59 % vanninnhold. Kastes etter √©n
  dags bruk.</li>
  <li><strong>SofLens 38</strong> ‚Äì polymacon, 38 % vanninnhold (navnet viser til dette tallet).
  M√•nedslinse.</li>
  <li><strong>SofLens Toric</strong> ‚Äì alphafilcon A, 66 % vanninnhold. Bruker Bausch + Lombs
  patenterte Lo-Torque-design, som holder linsen stabil i riktig rotasjon ‚Äì avgj√∏rende for at
  den toriske korreksjonen av astigmatisme skal sitte riktig gjennom dagen.</li>
  <li><strong>SofLens Multifocal</strong> ‚Äì bruker Natra-Sight Optics, med en bredere
  overgangssone mellom n√¶r-, mellom- og langsynt-korreksjon, beregnet p√• alderssyn.</li>
</ul>
""",
    "acuvue": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Acuvue</h2>
<p>Acuvue er Johnson & Johnson Visions kontaktlinsemerke, og regnes som verdens ledende
produsent av engangslinser. Familien spenner fra dagslinser til linser for to ukers bruk,
i sf√¶riske, toriske og multifokale varianter.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i Acuvue-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>1-Day Acuvue Moist</strong> ‚Äì etafilcon A, 58 % vanninnhold. Bruker LACREON-
  teknologi, som binder et fuktighetsbevarende stoff direkte inn i linsematerialet.</li>
  <li><strong>Acuvue Oasys</strong> (2-ukers) ‚Äì senofilcon A, en silikonhydrogel med 38 %
  vanninnhold og h√∏y oksygengjennomtrengelighet. Bruker HYDRACLEAR PLUS-teknologi, en
  fuktighetsgivende overflatebehandling som etterligner t√•refilmen.</li>
  <li><strong>Acuvue Oasys MAX 1-Day</strong> ‚Äì samme senofilcon A-materiale som Oasys, men
  tilf√∏rt TearStable-teknologi for jevn fuktighet gjennom dagen og et OptiBlue-filter som
  reduserer bl√•tt/fiolett lys fra skjermer med om lag 60 %.</li>
</ul>
""",
    "dailies": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Dailies</h2>
<p>Dailies er Alcons familie av dagslinser, og spenner over flere atskilte produktlinjer med
ulike materialer og teknologier ‚Äì fra den opprinnelige Focus Dailies-serien til de nyere
AquaComfort Plus- og Total1-linjene.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i Dailies-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Dailies AquaComfort Plus</strong> ‚Äì nelfilcon A, 69 % vanninnhold. Et
  fuktighetssystem tilsatt linsen (HPMC, PEG og PVA) skal gi jevn komfort gjennom dagen.</li>
  <li><strong>Dailies Total1</strong> ‚Äì delefilcon A, en silikonhydrogel bygget med
  "vanngradient"-teknologi: kjernen har 33 % vanninnhold, mens selve overflaten som m√∏ter
  √∏yet n√•r over 80 % vann. Gir vesentlig h√∏yere oksygengjennomtrengelighet enn
  AquaComfort Plus.</li>
  <li><strong>Focus Dailies</strong> ‚Äì den opprinnelige Dailies-linjen, senere supplert av
  AquaComfort Plus og Total1.</li>
</ul>
""",
    "biofinity": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Biofinity</h2>
<p>Biofinity er CooperVisions flaggskip blant m√•nedslinser, og finnes i sf√¶risk, torisk,
multifokal og utvidet bruk-variant (XR). Serien er bygget rundt selskapets egen
Aquaform Comfort Science-teknologi.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Biofinity er laget av comfilcon A, med 48 % vanninnhold. Aquaform Comfort
Science-teknologien binder vann tilsvarende det dobbelte av materialets egen vekt, og skaper
naturlig fuktbarhet uten behov for en egen overflatebehandling ‚Äì i motsetning til enkelte
andre linser som er avhengige av en tilsatt fuktighetsbelegg.</p>
""",
    "purevision": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om PureVision</h2>
<p>PureVision er en av Bausch + Lombs eldre og mest etablerte m√•nedslinser, bygget rundt
selskapets AerGel-teknologi.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">PureVision er laget av balafilcon A, en silikonhydrogel med 36 % vanninnhold.
AerGel-teknologien slipper gjennom naturlige niv√•er med oksygen og er motstandsdyktig mot
proteinavleiringer, mens den nyere PureVision2 i tillegg har ComfortMoist-teknologi som
tilf√∏rer ekstra fuktighet p√• linseoverflaten.</p>
""",
    "biotrue": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Biotrue</h2>
<p>Biotrue ONEday er Bausch + Lombs dagslinse, utviklet med utgangspunkt i egenskapene til
hornhinnen og t√•refilmen.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Biotrue er laget av nesofilcon A (markedsf√∏rt som "HyperGel"), med 78 %
vanninnhold ‚Äì tilsvarende hornhinnens eget naturlige vanninnhold. Surface Active Technology
skal bevare 98 % av fuktigheten i opptil 16 timer, mens en egen Peri-Ballast-utforming holder
de toriske variantene stabile gjennom vanlige blunkebevegelser.</p>
""",
    "ultra": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om ULTRA</h2>
<p>ULTRA er Bausch + Lombs nyere m√•nedslinse, bygget rundt MoistureSeal-teknologien.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">ULTRA er laget av samfilcon A, en silikonhydrogel med 46 % vanninnhold.
MoistureSeal-teknologien er utviklet gjennom en to-trinns produksjonsprosess og skal bevare
95 % av linsens fuktighet i opptil 16 timer.</p>
""",
    "air-optix": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Air Optix</h2>
<p>Air Optix er Alcons etablerte m√•nedslinse-serie, med varianter for sf√¶risk korreksjon,
astigmatisme, alderssyn og fargede linser.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Air Optix plus HydraGlyde er laget av lotrafilcon B, en silikonhydrogel med
33 % vanninnhold. HydraGlyde-teknologien er en overflatebehandling som kontinuerlig tilf√∏rer
fuktighet til linseoverflaten, mens SmartShield-teknologien skal gj√∏re linsen mer
motstandsdyktig mot avleiringer.</p>
""",
    "precision1": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Precision1</h2>
<p>Precision1 er Alcons daglinse, ofte et f√∏rstevalg for nye linsebrukere.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Precision1 er laget av verofilcon A, en silikonhydrogel med 51 % vanninnhold
i kjernen. SmartSurface-teknologien tilf√∏rer et tynt, permanent fuktighetslag med over 80 %
vanninnhold p√• selve overflaten, slik at linsen kombinerer stabil oksygengjennomtrengelighet
fra kjernen med fuktighet p√• overflaten.</p>
""",
    "precision7": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Precision7</h2>
<p>Precision7 er Alcons ukelinse (7 dagers brukstid) ‚Äì en mellomting mellom en dagslinse og
en m√•nedslinse i bytterutine.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Precision7 er laget av serafilcon A, med 55 % vanninnhold. Activ-Flo-
teknologien er ment √• etterfylle fuktighet gjennom hele den syv dager lange brukstiden.</p>
""",
    "total30": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om TOTAL30</h2>
<p>TOTAL30 er Alcons premium m√•nedslinse, bygget p√• samme vanngradient-prinsipp som
Dailies Total1, bare i en versjon beregnet for en hel m√•neds bruk.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">TOTAL30 er laget av lehfilcon A, med 55 % vanninnhold i kjernen som stiger
gradvis til n√¶r 100 % ved selve overflaten (vanngradient-teknologi). Celligent-teknologien
skal bidra til √• holde linseoverflaten motstandsdyktig mot bakterier og fettavleiringer
gjennom hele den 30 dager lange brukstiden.</p>
""",
    "freshlook": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om FreshLook</h2>
<p>FreshLook er Alcons serie med fargede kontaktlinser, bygget p√• selskapets 3-i-1-
fargeteknologi som blander tre nyanser i √©n linse for et naturlig utseende.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Godt √• vite</h2>
<p style="font-size:1rem;line-height:1.7;">Fargede linser krever samme resept og tilpasning hos optiker som andre
kontaktlinser, selv uten styrke ‚Äì se v√•r <a href="/guide/kosmetiske-kontaktlinser/">guide om
kosmetiske og fargede kontaktlinser</a>.</p>
""",
    "avaira": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Avaira</h2>
<p>Avaira Vitality er CooperVisions to-ukerslinse, med sf√¶risk og torisk variant.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Avaira Vitality er laget av fanfilcon A, med 55 % vanninnhold. Linsen har
klasse I UV-blokkering, den h√∏yeste klassifiseringen, som blokkerer over 90 % av UVA- og
over 99 % av UVB-str√•lene.</p>
""",
    "biomedics": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Biomedics</h2>
<p>Biomedics er en eldre og godt etablert linseserie fra CooperVision, med varianter for
b√•de dags- og to-ukersbruk.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Biomedics er laget av ocufilcon D, en hydrogel med 55 % vanninnhold, som
er myk og fleksibel og bidrar til fuktighet gjennom brukstiden.</p>
""",
    "clariti": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Clariti</h2>
<p>Clariti 1 day er CooperVisions rimeligere daglinse-serie i silikonhydrogel, med sf√¶risk,
torisk og multifokal variant.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Clariti er laget av somofilcon A, med 56 % vanninnhold og innebygget
UV-beskyttelse. WetLoc-teknologien skal fordele fuktighet jevnt over hele linseoverflaten.</p>
""",
    "myday": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om MyDay</h2>
<p>MyDay er CooperVisions premium daglinse, med sf√¶risk, torisk og multifokal variant ‚Äì
samt MyDay MiSight, en egen daglinse godkjent for myopikontroll hos barn.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">MyDay er laget av stenfilcon A, med 54 % vanninnhold. Linsen bruker samme
Aquaform-teknologi som Biofinity, som binder vann naturlig i materialet uten behov for en
egen overflatebehandling.</p>
""",
    "proclear": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Proclear</h2>
<p>Proclear er CooperVisions linseserie rettet spesielt mot brukere som opplever t√∏rre √∏yne,
i dags-, to-ukers- og multifokal variant.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Proclear er laget av omafilcon A, tilf√∏rt CooperVisions PC-teknologi. Denne
bygger inn fosforylkolin (PC) ‚Äì et stoff som naturlig finnes i cellene i kroppen ‚Äì som binder
vann til og gjennom linsen for √• redusere rask utt√∏rking.</p>
""",
    "adore": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om ADORE</h2>
<p>ADORE er en linseserie for kosmetiske og fargede kontaktlinser fra den italienske
produsenten Eyemed Technologies, med flere fargekolleksjoner (blant annet Bi-tone og Dare).
Selv uten styrke regnes fargede linser som medisinsk utstyr og krever samme resept og
tilpasning hos optiker som andre kontaktlinser ‚Äì se v√•r
<a href="/guide/kosmetiske-kontaktlinser/">guide om kosmetiske og fargede kontaktlinser</a>.</p>
""",
    "miru": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Miru</h2>
<p>Miru er den japanske produsenten Menicons linser for daglig og m√•nedlig utskifting, med varianter for sf√¶risk
korreksjon, astigmatisme og alderssyn.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Miru 1day UpSide er laget av midafilcon A, en silikonhydrogel med 56 %
vanninnhold. Menicon kombinerer MeniSilk Air-teknologi (fuktighet) med NanoGloss Pro
(en glatt, lav-friksjons overflate) for √• gi linsen komforten til en tradisjonell hydrogel-
linse med h√•ndteringsegenskapene til en silikonhydrogel.</p>
""",
    "live": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Live</h2>
<p>Live er CooperVisions rimeligere daglinse, posisjonert mot unge og f√∏rstegangsbrukere.
Linsen selges ogs√• under andre navn hos enkelte utenlandske forhandlere/optikerkjeder, som
en del av samme CooperVision-plattform.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Live er laget av somofilcon A, en silikonhydrogel med 56 % vanninnhold ‚Äì
samme materiale som brukes i CooperVisions Clariti 1 day. AquaGen-teknologien skal binde
fuktighet naturlig til og gjennom linsen.</p>
""",
    "clearlii": """
<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Clearlii</h2>
<p>Clearlii er et apotek-eksklusivt linsemerke, opprinnelig lansert i Stockholm i 2011 under
navnet Apotekslinsen. Merket ble til Clearlii og fikk egenproduserte linser i 2018, og selges i
dag hos 800‚Äì900 apotek og 150+ optikere i fem nordiske land. Linsene produseres av den
taiwanske produsenten Pegavision.</p>

<h2 style="font-family:'Mulish',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i Clearlii-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Clearlii Daily</strong> ‚Äì etafilcon A, 58 % vanninnhold. Tilsatt hyaluronsyre for
  linsebrukere med t√∏rre √∏yne.</li>
  <li><strong>Clearlii Vitamin</strong> ‚Äì samme etafilcon A-materiale (58 % vanninnhold) som
  Daily, i tillegg tilsatt vitamin E, B6 og B12 samt hyaluronsyre.</li>
  <li><strong>Clearlii Hydrogel M√•nedslinser</strong> ‚Äì polymacon, 38 % vanninnhold, med et
  mykt kant-design ("Silk & Soft Edge").</li>
</ul>
""",
}


def _retailer_badge_html(retailer: str) -> str:
    """Logo istedenfor navnetekst n√•r vi har en - men navnet ligger fortsatt i
    r√•-HTML (visuelt skjult), siden b√•de skjermlesere og enkle AI-tekst-
    uttrekkere skal kunne se hvilken forhandler det er uten √• tolke <img alt>."""
    entry = RETAILER_LOGOS.get(retailer)
    if not entry:
        return escape(retailer)
    filename, dark_bg = entry
    img = f'<img class="retailer-logo" src="/static/logos/{filename}" alt="{escape(retailer)}" loading="lazy">'
    logo = f'<span class="retailer-logo-chip">{img}</span>' if dark_bg else img
    hidden_name = f'<span style="position:absolute;left:-9999px;">{escape(retailer)}</span>'
    return logo + hidden_name


def _obfuscate_email(email: str) -> str:
    """Numeriske HTML-entiteter per tegn - vises normalt i alle nettlesere og
    fungerer uten JS (ingen brudd p√• "innhold skal finnes i r√•-HTML"-
    prinsippet), men gj√∏r adressen usynlig for enkle regex-baserte
    e-post-innh√∏stere som leser r√• HTML/tekst uten √• rendre den."""
    return "".join(f"&#{ord(c)};" for c in email)


def _contact_email_link(css_class: str = "") -> str:
    obf = _obfuscate_email("kontakt@kontaktlinser.no")
    cls = f' class="{css_class}"' if css_class else ""
    return f'<a href="mailto:{obf}"{cls}>{obf}</a>'


def _mailto_link(subject: str, label: str, css_class: str = "") -> str:
    """Som _contact_email_link(), men med et forh√•ndsutfylt emnefelt og en
    egen lenketekst i stedet for √• gjenta selve e-postadressen -- brukt av
    /meld-feil/ sine tre snarveier (feil pris/feil produktmatching/annet)."""
    obf = _obfuscate_email("kontakt@kontaktlinser.no")
    cls = f' class="{css_class}"' if css_class else ""
    subject_q = subject.replace(" ", "%20")
    return f'<a href="mailto:{obf}?subject={subject_q}"{cls}>{escape(label)}</a>'


def _fmt_kr(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ") + " kr"


def _render_product_tile(*, href: str, name: str, image_url: str | None, fallback_initials: str,
                          category_label: str | None, secondary_line_html: str,
                          lowest: dict | None, other_count: int, data_attr: str = "",
                          illustration_html: str | None = None, specs_row_html: str = "",
                          comparison_offers: list[dict] | None = None) -> str:
    """Delt kortmarkup for merke-/kategori-/tilbeh√∏r-/private label-rutenett
    (render_brand_page, render_category_page, render_solution_category_page,
    render_private_label_brand_page) -- √©n mal, page-spesifikt innhold
    (kategori-badge, "sekund√¶rlinje" under produktnavnet: produsent/merke/
    ekte-produkt-lenke) sendes inn som ferdig HTML fra hver kallested.
    illustration_html (egen tegnet grafikk, se render_private_label_illustration)
    vinner over b√•de image_url og fallback_initials n√•r den er satt."""
    href_esc = escape(href)
    if illustration_html:
        image_block = f'<div class="pli-tile-wrap">{illustration_html}</div>'
        image_cls = "product-tile-image has-photo"
    elif image_url:
        image_block = _img_tag(image_url, name)
        image_cls = "product-tile-image has-photo"
    else:
        image_block = f'<span class="product-tile-fallback">{escape(fallback_initials)}</span>'
        image_cls = "product-tile-image"
    category_badge = f'<div class="product-tile-category">{escape(category_label)}</div>' if category_label else ""

    savings_html = ""
    highest_price = None
    store_count = max(0, other_count + 1)
    if comparison_offers is not None:
        # Same product/pack only. One fresh, in-stock positive price per store.
        by_store = {}
        for offer in comparison_offers:
            price = offer.get("price_nok", 0)
            if not offer.get("in_stock") or offer.get("is_stale", True) or not math.isfinite(price) or price <= 0:
                continue
            key = offer["retailer"].strip().casefold()
            if key not in by_store or price < by_store[key]["price_nok"]:
                by_store[key] = offer
        valid = list(by_store.values())
        store_count = len(valid)
        lowest = min(valid, key=lambda o: (o["price_nok"], o["total"]), default=None)
        if len(valid) >= 2:
            high = max(o["price_nok"] for o in valid)
            if high > lowest["price_nok"]:
                highest_price = high
            # Floor rather than overstate savings; omit sub-1% differences.
            percent = math.floor((high - lowest["price_nok"]) / high * 100)
            if percent >= 1:
                explanation = f"{percent} % lavere enn h√∏yeste tilgjengelige butikkpris for samme pakning, uten frakt."
                savings_html = (f'<span class="product-tile-savings" tabindex="0" '
                                f'aria-label="{escape(explanation)}" data-explanation="{escape(explanation)}">'
                                f'Spar {percent} %</span>')

    if lowest:
        num = f'{lowest["price_nok"]:,.0f}'.replace(",", " ")
        store_html = f' hos {store_count} {"butikk" if store_count == 1 else "butikker"}'
        high_html = f'<s class="product-tile-high-price">{_fmt_kr(highest_price)}</s>' if highest_price is not None else ""
        price_block = (
            f'<div class="product-tile-price-label"><span class="product-tile-price-label-default">Fra (ekskl. frakt)</span>{high_html}</div>'
            f'<div class="product-tile-price"><span class="product-tile-price-from">Fra</span><span class="product-tile-price-number">{num}</span>'
            f'<span class="product-tile-price-currency">kr</span></div>'
            f'<div class="product-tile-store-line">{store_html}</div>'
        )
    else:
        price_block = '<div class="product-tile-store-line">Ingen tilbud tilgjengelig</div>'

    return f"""<div class="product-tile"{data_attr}>
  {savings_html}
  <a class="product-tile-image-link" href="{href_esc}"><div class="{image_cls}">{image_block}</div></a>
  <div class="product-tile-body">
    {category_badge}
    <a class="product-tile-name-link" href="{href_esc}"><div class="product-name">{escape(name)}</div></a>
    {secondary_line_html}
    {specs_row_html}
    <div class="product-tile-divider"></div>
    <a class="product-tile-price-link" href="{href_esc}">{price_block}</a>
  </div>
  <a class="product-tile-cta" href="{href_esc}">Sammenlign priser</a>
</div>"""


def _last_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month, 31, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def oslo_date(checked_at: str):
    """Datoen (norsk tid) et UTC-tidspunkt faller p√•. Egen sommertid-regel (EU:
    siste s√∏ndag i mars kl. 01:00 UTC til siste s√∏ndag i oktober kl. 01:00 UTC)
    i stedet for zoneinfo, siden tzdata ikke er garantert installert. Viktig for
    den nattlige kj√∏ringen (~22:45 UTC = etter midnatt i Norge): den synlige datoen
    og sitemapens lastmod skal v√¶re samme dato."""
    dt = datetime.fromisoformat(checked_at).astimezone(timezone.utc)
    dst = (_last_sunday(dt.year, 3) + timedelta(hours=1)) <= dt < (_last_sunday(dt.year, 10) + timedelta(hours=1))
    return (dt + timedelta(hours=2 if dst else 1)).date()


def _verified_tag(checked_at: str) -> str:
    """Absolutt, maskinlesbar dato: <time datetime="2026-09-27">27.09.2026</time>.
    Erstatter "Sist oppdatert: N timer siden" (2026-09-27): den relative teksten ble
    regnet ut ved bygging og var feil hver gang noen leste siden senere enn bygget.
    Samme dato som lastmod i sitemap og dateModified i JSON-LD."""
    d = oslo_date(checked_at)
    return f'<time datetime="{d.isoformat()}">{d.strftime("%d.%m.%Y")}</time>'


def _newest_checked(offers: list[dict]) -> str | None:
    stamps = [o["checked_at"] for o in offers]
    return max(stamps) if stamps else None


# Rangering blant forhandlere MED affiliate-avtale, brukt KUN til √• avgj√∏re
# rekkef√∏lge/vinner ved eksakt lik totalpris (aldri prisen selv). Lavere tall
# = vinner tidligere.
#
# Bruker bekreftet 2026-08-31 provisjonssatsene for samtlige fem
# affiliate_feed-forhandlere: Lenson, Lensway, Shopping4net og Extra
# Optical har alle 8 %, Apotekhjem har 10 %. Ved eksakt lik totalpris gir
# en h√∏yere prosentsats av samme kronebel√∏p reelt mer inntjening, s√•
# Apotekhjem rangeres foran de fire andre. De fire med lik sats (8 %) er
# bevisst IKKE innbyrdes rangert -- ingen prioritering mellom dem er
# meningsfull siden 8 % av samme bel√∏p er samme bel√∏p uansett hvem som
# vinner (alfabetisk fallback i _tie_break_key() holder for dem).
AFFILIATE_TIE_PRIORITY: dict[str, int] = {
    "Apotekhjem": 0,
}


# Forhandlere vi MIDLERTIDIG lenker direkte til (uten affiliate-sporing) fordi
# deres affiliate-lenke er √∏delagt hos nettverket. Extra Optical (Adtraction,
# a=1487383541&as=2102229792) svarer "Invalid link -- broken or no longer
# available" for ALLE sporingslenker fra og med 2026-10-05 (feeden gir fortsatt
# de samme lenkene, s√• feilen er hos Adtraction/programmet, ikke her). Slike
# tilbud rendres som ikke-affiliate (source "direct_link": rel nofollow, UTM,
# ingen Chillout-clickout, ingen affiliate-fortrinn ved lik pris) med
# m√•l-URL-en hentet ut av `url=`-parameteren i Adtraction-lenken. TILBAKERULLING:
# t√∏m settet n√•r Adtraction-lenkene virker igjen (√©n endring, ingen annen kode).
DIRECT_LINK_RETAILERS: set[str] = {"Extra Optical"}


def _direct_url_from_adtraction(url: str) -> str | None:
    """M√•l-URL-en bak en Adtraction-sporingslenke (`...&url=<m√•l>`, alltid siste
    parameter). None hvis lenken ikke har et http(s)-m√•l -- da beholdes
    originalen uendret."""
    m = re.search(r"[?&]url=(https?://[^\s]+)$", url)
    return unquote(m.group(1)) if m else None


def _tie_break_key(o: dict) -> tuple:
    """Sorteringsn√∏kkel for eksakt lik totalpris -- brukt av B√ÖDE
    _pick_lowest() (hvem f√•r "Lavest pris"-merket) og reconcile_product()
    sin hovedsortering (rekkef√∏lgen tilbudene faktisk VISES i p√• siden).
    Disse to brukte ULIK logikk frem til 2026-08-31 -- bruker oppdaget at
    en forhandler UTEN avtale (skrapet) kunne vises F√òR en med avtale i
    selve listen (kun alfabetisk/opprinnelig rekkef√∏lge ved lik pris),
    selv om _pick_lowest() allerede korrekt ga badgen til avtale-
    forhandleren. N√• deler begge samme regel:
    1) affiliate-avtale (source == "affiliate_feed") f√∏r ingen avtale,
    2) blant flere avtaler, se AFFILIATE_TIE_PRIORITY over,
    3) alfabetisk som siste, forutsigbare fallback."""
    is_affiliate = o.get("source") == "affiliate_feed"
    return (
        0 if is_affiliate else 1,
        AFFILIATE_TIE_PRIORITY.get(o["retailer"], 999),
        o["retailer"],
    )


def _pick_lowest(eligible: list[dict]) -> dict | None:
    """Velger √âN vinner blant tilbud p√• lager og ikke utdaterte, ved eksakt
    lik totalpris (2026-08-18, etter avtale med brukeren) -- se
    _tie_break_key() for selve regelen, delt med reconcile_product() sin
    hovedsortering siden 2026-08-31. Prisen er identisk for kunden i alle
    disse tilfellene uansett -- regelen avgj√∏r kun hvem som f√•r "Lavest
    pris"-merket (og hvem som vises f√∏rst i listen) n√•r det ikke er noen
    reell prisforskjell √• vise frem. Se disclosure-teksten p√•
    produktsidene, som nevner dette eksplisitt."""
    if not eligible:
        return None
    lowest_total = min(o["total"] for o in eligible)
    tied = [o for o in eligible if o["total"] == lowest_total]
    if len(tied) == 1:
        return tied[0]
    return min(tied, key=_tie_break_key)


def _add_utm_params(url: str) -> str:
    """UTM-tagger utg√•ende lenker til forhandlere UTEN avtale (skrapet
    kilde) -- 2026-08-31, etter bruker√∏nske. Gir forhandleren mulighet til
    √• se i egen analytics at bes√∏ket kom fra oss, selv uten aktiv
    affiliate-avtale (nyttig dokumentasjon n√•r vi ber om en avtale senere).
    Affiliate-lenker (source == affiliate_feed) skal ALDRI r√∏res her --
    kalleren sjekker det -- de har allerede nettverkets egne
    tracking-parametre, og √• endre URL-en kan i verste fall √∏delegge
    attribusjonen av provisjonen v√•r."""
    parsed = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.startswith("utm_")]
    query += [
        ("utm_source", "kontaktlinserno"),
        ("utm_medium", "referral"),
        ("utm_campaign", "prissammenligning"),
    ]
    return urlunsplit(parsed._replace(query=urlencode(query)))


# Daglig oppdatering (fra 2026-09-26): et feed-tilbud er normalt opptil ~24 t
# gammelt ved bygging, et skrapet tilbud opptil ~48 t (full skraping annenhver
# dag, se build_catalog.py). Grensene ligger over det med margin for GitHub
# Actions sine cron-forsinkelser, slik at "ikke nylig bekreftet"-merket bare
# vises n√•r noe faktisk har sviktet -- ikke p√• hver push-bygging sent p√• dagen.
FEED_STALE_HOURS = 36
SCRAPED_STALE_HOURS = 60


def reconcile_product(offers: list[dict], now: datetime, stale_hours: int | None = None) -> list[dict]:
    """Samme logikk som reconcile() i ingest_feed.py, men p√• r√• dict-data
    slik generatoren kan kj√∏re den direkte p√• catalog.json uten omveier.

    UTM-tagger her (ETT sted, ikke i hver render-funksjon) siden ALLE
    kallere -- render_offer_card, winner_band, qty-kalkulatorens JSON, og
    JSON-LD-schemaet -- bruker o["url"] fra nettopp denne enrichede
    listen. De tre forste gar na gjennom outbound_url(), som kan bytte
    den ut med en clickout fra Chillout; JSON-LD gjor det ikke. o["url"]
    her er fortsatt leverandorens URL og den eneste kilden til den. En feed-URL for et affiliate-tilbud f√•r ALDRI UTM-parametre,
    kun skrapede (ikke-avtale) tilbud."""
    enriched = []
    for o in offers:
        checked = datetime.fromisoformat(o["checked_at"])
        age_hours = (now - checked).total_seconds() / 3600
        limit = stale_hours if stale_hours is not None else (
            FEED_STALE_HOURS if o.get("source") == "affiliate_feed" else SCRAPED_STALE_HOURS
        )
        is_stale = age_hours > limit
        total = o["price_nok"] + o["shipping_nok"]
        source = o.get("source")
        direct_url = (
            _direct_url_from_adtraction(o["url"])
            if o.get("retailer") in DIRECT_LINK_RETAILERS and source == "affiliate_feed"
            else None
        )
        if direct_url:
            source, base_url = "direct_link", direct_url
        else:
            base_url = o["url"]
        url = base_url if source == "affiliate_feed" else _add_utm_params(base_url)
        enriched.append({**o, "total": total, "is_stale": is_stale, "url": url, "source": source})

    newest = max((o["checked_at"] for o in enriched), default=None)
    newest_day = oslo_date(newest) if newest else None
    # >= 2 dager eldre enn sidens nyeste (ikke 1): daglig kj√∏ring med skraping
    # annenhver dag gir vanligvis skrapede tilbud som er 1 dag eldre enn feedene --
    # det er normalt og skal ikke st√• p√• hvert kort. 2+ dager betyr at noe faktisk
    # ikke ble hentet (gjenbrukt tilbud), og da vises datoen √¶rlig p√• kortet.
    for o in enriched:
        o["older_than_page"] = newest_day is not None and (newest_day - oslo_date(o["checked_at"])).days >= 2

    eligible = [o for o in enriched if o["in_stock"]]

    # Lensit svarer ikke p√• gjentatte avtaleforesp√∏rsler (4-5 henvendelser
    # uten svar, 2026-09-16) -- etter bruker√∏nske skal de ikke lenger vises
    # n√•r de er billigst (ville gitt dem gratis salg uten noen avtale).
    # De vises fortsatt som et vanlig, ikke-vinnende tilbud n√•r de IKKE er
    # billigst. "Billigst" avgj√∏res p√• selve prisen (inkl. evt. uavgjort),
    # ikke bare hvem som til slutt f√•r trof√©-merket via tie-break.
    if eligible:
        lowest_total = min(o["total"] for o in eligible)
        if any(o["retailer"] == "Lensit" and o["total"] == lowest_total for o in eligible):
            enriched = [o for o in enriched if o["retailer"] != "Lensit"]
            eligible = [o for o in enriched if o["in_stock"]]

    winner = _pick_lowest(eligible)

    for o in enriched:
        o["is_lowest"] = winner is not None and o is winner

    return sorted(enriched, key=lambda o: (o["total"],) + _tie_break_key(o))


# Shopping4Net sine produktbilder ER hvitere enn Extra Optical sine
# (bekreftet ved pikselsampling 2026-08-21: EO ligger p√• ca. (243,243,243),
# S4N p√• ekte hvit), MEN de er faste 270x270px-thumbnails uansett produkt
# (bekreftet p√• 7 stikkpr√∏ver samme dag) -- mot Extra Optical sine ekte
# produktbilder i 1760x1200/2200x1500. Ved v√•r nye, st√∏rre hero-bildest√∏rrelse
# p√• PC (340px) blir S4N-bildet synlig oppskalert og uskarpt -- brukeren
# reagerte p√• nettopp dette. Skarphet/oppl√∏sning veier tyngre enn en liten
# gr√•-vs-hvit-forskjell i bakgrunnen, s√• Extra Optical foretrekkes fortsatt
# (tilbake til opprinnelig fil-rekkef√∏lge i sources_config.json, ingen egen
# prioritering n√∏dvendig -- se git-historikk for det forkastede fors√∏ket p√•
# √• foretrekke S4N).
def pick_product_image(offers: list[dict]) -> str | None:
    for o in offers:
        if o.get("image_source") in LICENSED_IMAGE_SOURCES and o.get("image_url"):
            return o["image_url"]
    return None


def _img_tag(image_url: str, alt: str, css_class: str = "", loading: str = "lazy") -> str:
    """<picture>+WebP for v√•re egne manuelt kuraterte bilder (static/products/*.jpg,
    som ALLTID har en generert .webp ved siden av seg -- se scriptet som
    konverterte hele mappen 2026-08-30), vanlig <img> for bilder vi henter
    direkte fra en forhandlers feed (image_source affiliate_feed/
    manufacturer_kit) -- vi kontrollerer ikke de filene og har ingen WebP-
    variant av dem."""
    cls_attr = f' class="{escape(css_class)}"' if css_class else ""
    dims = _dim_attrs(image_url)
    if image_url.startswith("/static/products/") and image_url.endswith(".jpg"):
        webp_url = image_url[:-4] + ".webp"
        return (f'<picture><source srcset="{escape(webp_url)}" type="image/webp">'
                f'<img{cls_attr} src="{escape(image_url)}" alt="{escape(alt)}"{dims} loading="{loading}"></picture>')
    return f'<img{cls_attr} src="{escape(image_url)}" alt="{escape(alt)}"{dims} loading="{loading}">'


def _private_label_image(label: dict) -> str | None:
    """Only use reviewed, licensed images of this exact private-label package."""
    if label.get("image_source") in LICENSED_IMAGE_SOURCES:
        return label.get("image_url")
    return None


def _product_image(product: dict) -> str | None:
    """Et manuelt kuratert produsent-pressebilde (manual_image i
    products_meta.json, se PRODUCT_IMAGES) vinner alltid over et
    skrapet/feed-bilde -- egen research/nedlasting, h√∏yere og mer
    konsistent kvalitet enn det en tilfeldig forhandler sin feed gir.
    Finnes ikke et manuelt bilde, faller vi tilbake til
    pick_product_image() sin vanlige logikk."""
    manual = product.get("manual_image")
    if manual:
        return manual
    # Private-label packaging belongs on its own alias page, never on the
    # manufacturer product (e.g. an iWear box is not a MIRU product photo).
    private_brands = tuple(name.lower() for name in PRIVATE_LABEL_SUBBRANDS.values())
    return pick_product_image([
        offer for offer in product["offers"]
        if not any(brand in re.sub(r"[^a-z0-9]", "", (offer.get("image_url") or "").lower())
                   for brand in private_brands)
    ])


TRUCK_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="1" y="7" width="13" height="9" rx="1" fill="currentColor"/><path d="M14 10h4l3 3v3h-7z" fill="currentColor" opacity="0.6"/><circle cx="6" cy="18" r="2" fill="currentColor"/><circle cx="17" cy="18" r="2" fill="currentColor"/></svg>'

# Isometrisk eske-ikon (topp-flate + to sideflater med ulik opasitet for
# skygge/dybde) -- brukt p√• antallsvelgerens piller, siden "esker" bokstavelig
# talt betyr fysiske pakkeesker, ikke bare et tall.
BOX_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 8l9-4 9 4-9 4-9-4z" fill="currentColor" opacity="0.5"/><path d="M3 8v8l9 4v-8L3 8z" fill="currentColor" opacity="0.8"/><path d="M21 8v8l-9 4v-8l9-4z" fill="currentColor"/></svg>'
# Blyant-ikon for "Eget antall"-pillen -- samme piktogram-spr√•k, men signaliserer
# at dette er en verdi brukeren selv skriver inn, ikke et fast antall esker.
PENCIL_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 17.25V20h2.75L17.81 8.94l-2.75-2.75L4 17.25z" fill="currentColor"/><path d="M19.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 2.75 2.75 1.83-1.83z" fill="currentColor" opacity="0.6"/></svg>'
# Pokal-ikon i vinner-boksen -- gir litt "stas"/humor til √• v√¶re billigst, ikke
# bare et n√∏kternt tall.
TROPHY_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M7 4h10v4a5 5 0 0 1-5 5 5 5 0 0 1-5-5V4z" fill="currentColor"/><path d="M7 5H4a3 3 0 0 0 3 4M17 5h3a3 3 0 0 1-3 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/><rect x="10.5" y="13" width="3" height="4" fill="currentColor"/><rect x="7" y="18" width="10" height="2.2" rx="1.1" fill="currentColor"/></svg>'
# Dr√•pe-ikon for linsetype-badger (toriske/multifokale/fargede linser) og
# kalender-ikon for brukstid-badger (dagslinser/m√•nedslinser/ukelinser) --
# se _product_type_badges().
DROPLET_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M12 2.5c3 4 6 8.2 6 11.8a6 6 0 1 1-12 0c0-3.6 3-7.8 6-11.8z" fill="currentColor"/></svg>'
BASISKURVE_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 18c0-7 4-13 8-13s8 6 8 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
DIAMETER_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M4 12h16" stroke="currentColor" stroke-width="1.6" stroke-dasharray="1.6 2.2"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/></svg>'
TAG_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M11.4 3.6l8 8a2 2 0 0 1 0 2.8l-5 5a2 2 0 0 1-2.8 0l-8-8V4.6a1 1 0 0 1 1-1h6.8z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="8" cy="8" r="1.3" fill="currentColor"/></svg>'
# N√∏ytral (IKKE mint/gr√∏nt -- det fargenavnet er reservert for "laveste pris",
# se designsystem-regelen i CLAUDE.md) avkrysningsikon til enkle faktalister
# som "Kort om X"-boksen p√• serie-siden.
CHECK_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 12.5l2.5 2.5L16 9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
RESET_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 12a8 8 0 1 1 2.6 5.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M4 17v-5h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
X_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>'
# To overlappende kontaktlinser -- egen tegnet illustrasjon (se
# /om-produktillustrasjoner/) brukt i "Hva er X?"-boksen p√• kategorisidene.
# Bevisst generisk (samme for alle 5 kategorier), ekte hex i stedet for
# currentColor siden illustrasjonen bruker to ulike bl√•toner samtidig.
LENS_PAIR_ILLUSTRATION_SVG = '''<svg viewBox="0 0 120 88" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <ellipse cx="46" cy="48" rx="34" ry="26" fill="#E8EFFE" stroke="#2563EB" stroke-width="2.2"/>
  <ellipse cx="76" cy="40" rx="34" ry="26" fill="#FFFFFF" stroke="#2563EB" stroke-width="2.2"/>
  <path d="M30 36a26 20 0 0 1 18-9" stroke="#2563EB" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.45"/>
  <path d="M60 28a26 20 0 0 1 18-9" stroke="#2563EB" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.45"/>
</svg>'''
CALENDAR_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 9.5h18" stroke="currentColor" stroke-width="1.8"/><path d="M7 3v4M17 3v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
SUN_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'

# Badger p√• produktsidens hero -- KUN utledet fra verifiserte spesifikasjons-
# felt (Linsetype/Brukstid i products_meta.json), aldri egne p√•stander eller
# markedsf√∏ringsord (se brukerens eksplisitte "ikke uverifiserte slagord"-
# tilbakemelding 2026-08-29). N√∏kkelord-basert i stedet for eksakt verdi-match,
# siden feltene er fritekst med reell variasjon ("Ukelinse (7 dager)",
# "M√•nedslinse (godkjent for kontinuerlig bruk)", "Multifokal og torisk" osv.)
# -- bekreftet mot samtlige verdier i products_meta.json 2026-08-29.
# "Sf√¶risk" alene gir bevisst INGEN badge -- det er standard-tilfellet for
# de fleste linser, ikke en differensierende egenskap √• fremheve.
_TYPE_BADGE_KEYWORDS = [
    ("Torisk", "Toriske linser"),
    ("Multifokal", "Multifokale linser"),
    ("Farget", "Fargede linser"),
    ("myopikontroll", "Myopikontroll"),
]
_USAGE_BADGE_KEYWORDS = [
    ("Dagslinse", "Dagslinser"),
    ("Ukelinse", "Ukelinser"),
    ("14-dagerslinse", "14-dagerslinser"),
    ("M√•nedslinse", "M√•nedslinser"),
    ("3 m√•neder", "3-m√•nederslinser"),
]


def _product_type_badges(specs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Returnerer (ikon, tekst)-par for hero-badgene, utledet fra Linsetype/
    Brukstid-radene i specs -- se modulniv√•-kommentaren over listene for
    hvorfor n√∏kkelord-match i stedet for eksakt verdi."""
    badges: list[tuple[str, str]] = []
    spec_dict = dict(specs)
    linsetype = spec_dict.get("Linsetype", "")
    for keyword, label in _TYPE_BADGE_KEYWORDS:
        if keyword.lower() in linsetype.lower():
            badges.append((DROPLET_ICON_SVG, label))
    brukstid = spec_dict.get("Brukstid", "")
    for keyword, label in _USAGE_BADGE_KEYWORDS:
        if keyword.lower() in brukstid.lower():
            badges.append((CALENDAR_ICON_SVG, label))
            break  # kun √©n brukstid-badge -- feltet beskriver ett og samme faktum
    return badges


def _render_product_badges(specs: list[tuple[str, str]]) -> str:
    badges = _product_type_badges(specs)
    if not badges:
        return ""
    items = "".join(
        f'<span class="hero-badge">{icon}<span>{escape(label)}</span></span>'
        for icon, label in badges
    )
    return f'<div class="hero-badges">{items}</div>'


def _hero_facts_html(specs: list[tuple[str, str]], pack_size: int | None) -> str:
    """Kompakt faktarad i Product Stage, KUN p√• desktop (Product Desktop Gold
    Standard v1, 2026-09-27, punkt 8: "Facts m√• komme fra dokumenterte
    produktdata" -- maks 3-4 stk, ALDRI et gjettet/fabrikert tall). Et
    produkt uten f.eks. Basiskurve i specs (som SofLens Daily Disposable)
    viser rett og slett f√¶rre fakta i stedet for √• finne p√• et tall --
    konsistent med prosjektets "aldri gjett data"-regel. CSS-en
    (.hero-facts) holder denne skjult under 860px, s√• mobil-Gold-Standard-
    en er up√•virket uansett."""
    spec_dict = dict(specs)
    facts: list[str] = []
    brukstid = spec_dict.get("Brukstid")
    if brukstid:
        facts.append(escape(brukstid))
    if pack_size:
        facts.append(f"{pack_size} linser")
    materiale = spec_dict.get("Materiale")
    if materiale:
        facts.append(escape(materiale))
    basiskurve = spec_dict.get("Basiskurve")
    if basiskurve:
        facts.append(f"BC {escape(basiskurve)}")
    if not facts:
        return ""
    items = '<span class="hero-fact-sep">¬∑</span>'.join(f"<span>{f}</span>" for f in facts[:4])
    return f'<div class="hero-facts">{items}</div>'


def outbound_url(
    o: dict, retailer: str, product_id: str | None, clickouts: dict | None, surface: str
) -> str:
    """Den utgaende URL-en for ETT tilbud pa EN flate: clickout eller leverandor.

    **Alle kommersielle klikkflater kaller denne, og bare denne.** Kortet,
    vinnerbandet og antallskalkulatorens JSON gikk hver sin vei til
    `o["url"]`, og resultatet var at et konvertert tilbud kunne bli klikket
    gjennom leverandoren fra den mest fremtredende lenken pa siden. En flate
    som rendrer leverandor-URL-en skal gjore det fordi svaret var ingenting,
    aldri fordi kartet ikke nadde fram til den.

    **JSON-LD kaller den ikke, og det er en uttalt policy.** Strukturerte
    data er ikke en klikkflate: `offers.url` leses av sokemotorer, og en
    forstepartsredirect der er en annen avgjorelse med andre konsekvenser.

    Det tredje leddet -- `source == "affiliate_feed"` -- er ikke oppslaget.
    Et skrapet tilbud har ingen avtale bak seg og ingen provisjon a
    attribuere, sa /go/ ville myntet en click_id for en lenke ingen
    nettverkspartner noen gang ser.

    Generatoren kan fortsatt ikke LAGE en /go/-lenke: den har en streng
    Chillout returnerte, eller ingenting.
    """
    if not _surface_is_on(clickouts, surface):
        return o["url"]
    resolved = (clickouts or {}).get((product_id, retailer))
    return (resolved if o["source"] == "affiliate_feed" else None) or o["url"]


def _surface_is_on(clickouts, surface: str) -> bool:
    """Om DENNE flaten far bruke clickout-kartet.

    **Et vanlig dict betyr alle flater.** Det er det testene og enhver kaller
    fra for bryteren fantes sender, og den trygge lesningen av "ingen
    konfigurasjon her" er oppf√∏rselen som allerede var utrullet -- ikke a sla
    av noe stille. Er oppsettet derimot lest og tomt, er det en avgj√∏relse
    noen tok, og da er alt av.
    """
    enabled = getattr(clickouts, "enabled", None)
    return True if enabled is None else surface in enabled


def render_offer_card(o: dict, retailer: str, product_name: str | None = None,
                      product_id: str | None = None,
                      clickouts: dict | None = None,
                      is_winner: bool | None = None,
                      tags_html: str | None = None) -> str:
    # is_winner/tags_html: kun brukt av pilot-visningen (Prisjakt-modellen), der
    # "vinneren" er laveste produktpris og merkene settes utenfra. Standard er
    # uendret: vinner = laveste totalpris (o["is_lowest"]).
    status_note = (
        '<div class="offer-meta" style="font-weight:600;">Utsolgt</div>' if not o["in_stock"]
        else f'<div class="offer-meta" style="font-weight:600;">Pris ikke nylig bekreftet (sist {_verified_tag(o["checked_at"])})</div>' if o["is_stale"]
        else f'<div class="offer-meta">Sist oppdatert: {_verified_tag(o["checked_at"])}</div>' if o.get("older_than_page")
        else ""
    )
    winner = o["is_lowest"] if is_winner is None else is_winner
    css_class = "offer-card" + (" is-lowest" if winner else "") + (" is-muted" if not o["in_stock"] else "")
    # "Laveste pris"/"Lavest totalpris"-merket er fjernet (2026-09-27, Kai:
    # "ta bare vekk den gr√∏nne Laveste pris i tabellen. Den skal ikke v√¶re
    # der lengre") -- den gr√∏nne is-lowest-bakgrunnen/kanten markerer
    # fortsatt vinneren visuelt, kun tekstmerket er borte. tags_html-
    # parameteren er derfor ubrukt her n√• (beholdt i signaturen for √•
    # ikke m√•tte endre kallestedet i render_price_list()).
    # Produktprisen er hovedtallet (stort), frakt en egen liten linje over --
    # samme m√∏nster som Prisjakt/Klarna bruker, som er det norske brukere er
    # vant til √• lese. Vi dropper en egen "Totalt X kr"-linje per rad (var
    # opplevd som st√∏y -- tre tall stablet opp√• hverandre p√• hvert kort);
    # seksjonsoverskriften over lista sier allerede at den er sortert etter
    # totalpris, og toppbanneret viser vinnerens totalsum -- "Lavest pris"-
    # merket (ALLTID totalpris-basert, se reconcile()) er dermed fortsatt
    # etterpr√∏vbart uten at hvert enkelt kort m√• gjenta regnestykket.
    shipping_text = _shipping_note(o["shipping_nok"], o.get("shipping_policy"))
    rel = "sponsored" if o["source"] == "affiliate_feed" else "nofollow"
    price_label = (
        f'G√• til {escape(retailer)} for {escape(product_name)}, {_fmt_kr(o["price_nok"])}'
        if product_name else f'Se hos {escape(retailer)}, {_fmt_kr(o["price_nok"])}'
    )

    # Hele kortet er selve lenken (ikke bare pris-pillen) -- sm√• knapper er
    # vonde touch-m√•l p√• mobil, og det gir uansett bare ett meningsfullt sted
    # √• klikke per rad. price-pill er derfor et <span>, ikke en egen <a> --
    # n√∏stede <a>-tagger er ugyldig HTML og ville brutt visningen.
    is_affiliate = "1" if o["source"] == "affiliate_feed" else "0"

    # CHILLOUT-CLICKOUT, HENTET -- IKKE HARDKODET.
    #
    # /go/ er kontaktlinser.no sitt eget, forstepartsledd ut: Chillout mynter
    # sin egen click_id FOR nettverket rutes, og 302-redirecter deretter til
    # noyaktig den tracking-URL-en som ellers hadde statt her.
    #
    # `clickouts` kommer fra chillout_clickout.clickout_urls(), som spor
    # lesekontrakten pa byggetidspunktet. **Denne funksjonen kan ikke lage en
    # /go/-lenke.** Det finnes ingen formatstreng, ingen prefiks og ingen
    # token her lenger: den har enten en streng Chillout har returnert, eller
    # ingenting. Et Chillout som ikke svarer kan derfor ikke produsere en
    # lenke, bare la v√¶re a produsere en -- og da star leverandor-URL-en igjen,
    # som er det siden rendret for utrullingen.
    #
    # Dekningen ligger i chillout_clickout.CONVERTED, ett par. Den anvendes
    # pa svaret, sa kontrakten kan gjerne tilby clickouts for Shopping4net og
    # Extra Optical -- det gjor den -- uten at noe mer rendres.
    #
    # Alt annet pa kortet er bevisst urort: rel, target, data-retailer,
    # data-affiliate, klasser og markup. data-affiliate kommer fra
    # o["source"], ikke fra URL-en, sa outbound_click-eventet rapporterer
    # noyaktig som for. GA4s automatiske Enhanced Measurement "click" fyrer
    # ikke for en konvertert lenke fordi /go/ er samme domene -- kontrollert
    # 2026-09-23: ingen key event, ingen audience, ingen exploration leser
    # den.
    # **`source` er fortsatt med i betingelsen.** Kartet er nokkelt pa
    # (produkt, forhandler), og bootstrap-porten hadde et tredje ledd som et
    # oppslag alene mister: et SKRAPET tilbud har ingen avtale bak seg og
    # ingen provisjon a attribuere, og /go/ ville myntet en click_id for en
    # lenke ingen nettverkspartner noen gang ser. Kontrakten ville neppe
    # tilby en clickout for et slikt tilbud -- men "neppe" er ikke en
    # garanti siden dette rendres pa denne siden av HTTP.
    href = escape(outbound_url(o, retailer, product_id, clickouts, "offer_card"))
    return f"""<a class="{css_class}" href="{href}" target="_blank" rel="{rel} noopener" aria-label="{price_label}" data-retailer="{escape(retailer)}" data-affiliate="{is_affiliate}">
  <div class="offer-main">
    <div class="offer-retailer">{_retailer_badge_html(retailer)}</div>
    {status_note}
  </div>
  <div class="offer-price-col">
    <div class="offer-shipping">{TRUCK_ICON_SVG}<span class="offer-shipping-text">{escape(shipping_text)}</span></div>
    <span class="price-pill">{_fmt_kr(o["price_nok"])}</span>
  </div>
</a>"""


def _shipping_note(shipping_nok: float, shipping_policy: dict | None) -> str:
    """Skiller mellom "alltid gratis frakt" og "gratis frakt fordi grensen
    tilfeldigvis er n√•dd ved akkurat denne bestillingsst√∏rrelsen" -- √• si
    "Gratis frakt" uten forbehold i det siste tilfellet er misvisende, siden
    brukeren lett kan tro forhandleren alltid har fri frakt, ikke bare ved
    dette antallet esker.

    shipping_policy=None betyr at forhandlerens fraktgebyr under fri-frakt-
    grensen faktisk er UKJENT (se compute_shipping_nok() i offer.py, f.eks.
    Vitusapotek/Apotekhjem) -- IKKE at frakten er gratis. compute_shipping_nok()
    returnerer 0.0 som eksplisitt "ukjent"-standard i dette tilfellet, s√•
    shipping_nok alene kan ikke skille de to -- shipping_policy M√Ö sjekkes
    f√∏rst, ellers vises "Gratis frakt" feilaktig for en ordre godt under en
    kjent fri-frakt-grense."""
    if shipping_policy is None:
        return "Frakt beregnes i kassen"
    if shipping_nok <= 0:
        free_over = shipping_policy.get("free_over")
        if free_over:
            return f"Gratis frakt over {_fmt_kr(free_over)}"
        return "Gratis frakt"
    return f"{_fmt_kr(shipping_nok)} frakt"


# Delt mellom kontaktlinse- og linsev√¶ske/√∏yedr√•pe-produktsider -- teksten
# handler om selve sammenligningsmotoren (produktpris/frakt/totalpris-
# begrepene), ikke om noe produktspesifikt, s√• samme streng brukes ordrett
# begge steder i stedet for √• duplisere den.
METHODOLOGY_HTML = """<div class="methodology">
    <h2>Slik sammenligner vi priser</h2>
    <dl>
      <div class="methodology-row"><dt>Produktpris</dt><dd>Prisen butikken oppgir for selve produktet, uten frakt.</dd></div>
      <div class="methodology-row"><dt>Frakt</dt><dd>Fraktkostnaden beregnes for antallet esker du har valgt. Dersom kj√∏pet kvalifiserer til fri frakt hos butikken, tar beregningen hensyn til dette.</dd></div>
      <div class="methodology-row"><dt>Totalpris</dt><dd>Produktpris for valgt antall pluss eventuell frakt.</dd></div>
      <div class="methodology-row"><dt>Sortering</dt><dd>Standard er lavest produktpris. Sl√•r du p√• ¬´Pris inkludert frakt¬ª, regnes frakten med og butikkene sorteres etter lavest totalpris. Derfor kan butikken med lavest produktpris v√¶re en annen enn butikken med lavest totalpris.</dd></div>
      <div class="methodology-row"><dt>Oppdatering</dt><dd>Prisene hentes automatisk og oppdateres daglig.</dd></div>
    </dl>
    <a href="/slik-sammenligner-vi-priser/" style="font-size:0.85rem;font-weight:600;color:var(--blue);text-decoration:none;">Les mer om metodikken v√•r ‚Üí</a>
  </div>"""


# Delt mellom produktsider og private-label-sider, slik at "billigst akkurat
# n√•"-widgeten ser identisk ut begge steder (se render_winner_widget).
WINNER_WIDGET_STYLE = """
.winner-band { display: flex; align-items: center; justify-content: space-between; gap: 16px; background: var(--mint-tint); border: 1px solid #BFE7D5; border-radius: 14px; padding: 16px 18px; margin: 14px 0; text-decoration: none; color: inherit; }
.winner-band:hover, .winner-band:focus-visible { border-color: var(--mint); box-shadow: 0 2px 8px rgba(11, 163, 111, 0.18); }
.winner-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.winner-trophy { width: 44px; height: 44px; border-radius: 50%; background: white; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.winner-trophy svg { width: 22px; height: 22px; color: var(--mint); }
.winner-band .label { font-size: 0.78rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.05em; }
.winner-band .retailer { font-size: 0.95rem; color: var(--ink); margin-top: 3px; display: flex; align-items: center; gap: 6px; }
.winner-band .winner-shipping { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }
.winner-price-group { text-align: right; flex-shrink: 0; }
.winner-price-note { font-size: 0.75rem; color: var(--muted); margin-top: 5px; }
.price-pill.is-winner { background: var(--mint); font-size: 1.3rem; padding: 12px 24px; }
.winner-cta { display: none; }
/* Product Mobile Gold Standard v1 (2026-09-27, samme dag) -- vinnerkortet
   viser n√• PRIS (232 kr/eske + 59 kr frakt) og et Savings Signal-merke
   igjen, som erstatter den tidligere "Prisjakt-modellen" (ingen pris i
   selve kortet, kun i lista under) fra tidligere samme dag. Dette er en
   bevisst, eksplisitt instruert reversering -- ikke en glipp -- basert p√•
   en mye mer detaljert mockup/brief. "Prisjakt-modellen"-kommentaren
   lenger ned i filen er bevisst latt st√• som historikk/kontekst for
   HVORFOR den forrige modellen ble valgt, selv om den ikke lenger
   beskriver dagens faktiske kort. */
.winner-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.winner-band-cta .winner-top { align-self: stretch; width: 100%; }
.winner-band-cta .winner-top .label-group { align-items: flex-start; text-align: left; }
.winner-savings { flex-shrink: 0; width: 54px; height: 54px; border-radius: 50%; background: linear-gradient(135deg, #FDE68A 0%, #E7C254 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1.05; box-shadow: 0 2px 6px rgba(191, 151, 36, 0.28); }
.winner-savings[hidden] { display: none; }
.winner-savings-label { font-size: 0.55rem; font-weight: 600; color: #0F172A; text-transform: uppercase; letter-spacing: 0.02em; }
.winner-savings-pct { font-size: 0.9rem; font-weight: 800; color: #0F172A; }
.winner-price-line { font-size: 0.86rem; color: var(--ink); text-align: center; }
/* Nesten hvit bakgrunn med en ekstremt subtil mint-gradient (ikke flat
   var(--mint-tint) lenger) + minimal skygge -- "premium og rolig", ikke
   en affiliate-bannerannonse (Kais ord). */
.winner-band-cta { background: linear-gradient(165deg, #FFFFFF 0%, #F3FBF7 100%); box-shadow: var(--card-shadow); }
.winner-band-cta .winner-btn { background: linear-gradient(135deg, #0E7A4E 0%, #0B6A43 100%); }
.qty-box { background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }
.qty-box-title { font-weight: 600; font-size: 0.92rem; margin-bottom: 10px; }
/* Antall + fraktbryter P√Ö SAMME RAD, ogs√• p√• mobil (Kai, 2026-09-27:
   "Da er det bare √Ö f√• denne rekken p√• plass.. p√• en linje p√• mobil") --
   tittelen flyttet ut til sin egen linje over (se .qty-box-title), denne
   raden er n√• KUN pillene + fraktboksen, nowrap uansett bredde. De
   kompakte .qty-pill-reglene lenger ned (scoped til .wrap-product) er
   det som faktisk gj√∏r plassen til overs -- uten dem hadde ikke raden
   hatt en sjanse p√• 375px. */
.qty-box-row { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; }
.qty-box-row .qty-pills { flex: 1 1 auto; min-width: 0; }
/* Frakt-bryteren som egen boks med ikon/etikett/undertekst/ekte
   vippebryter (2026-09-27, etter mockup) -- egen modifier-klasse
   (.ship-chip-boxed) i stedet for √• endre den delte .ship-chip/
   .ship-chip-dot-pillen som linsev√¶ske-/private label-sidene fortsatt
   bruker uendret. */
.ship-chip-boxed { display: flex; align-items: center; gap: 10px; border-radius: 14px; padding: 10px 14px; text-align: left; white-space: normal; flex-shrink: 0; }
.ship-chip-icon { flex-shrink: 0; color: var(--blue); display: flex; }
.ship-chip-icon svg { width: 20px; height: 20px; }
.ship-chip-text { display: flex; flex-direction: column; min-width: 0; }
.ship-chip-label { font-weight: 700; font-size: 0.86rem; color: var(--ink); }
.ship-chip-sub { font-size: 0.72rem; color: var(--muted); margin-top: 1px; }
.ship-chip-toggle { flex-shrink: 0; margin-left: auto; width: 40px; height: 24px; border-radius: 12px; background: var(--border); position: relative; transition: background-color 0.15s; }
.ship-chip-toggle::before { content: ""; position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; border-radius: 50%; background: white; box-shadow: 0 1px 3px rgba(11, 37, 69, 0.3); transition: transform 0.15s; }
.ship-chip-boxed[aria-pressed="true"] { border-color: var(--blue); }
.ship-chip-boxed[aria-pressed="true"] .ship-chip-toggle { background: var(--blue); }
.ship-chip-boxed[aria-pressed="true"] .ship-chip-toggle::before { transform: translateX(16px); }
/* 5 faste piller + "Eget" (skjult under 640px, se #qty-pill-custom) --
   linsev√¶ske-/√∏yedr√•pe-/private label-alias-sidene, uendret. */
.qty-pills { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
@media (min-width: 640px) { .qty-pills { grid-template-columns: repeat(6, 1fr); } }
/* Produktsiden derimot: 6 FASTE piller (1/2/4/6/8/10), ingen "Eget" (se
   render_winner_widget() sin qty_choices/include_custom_pill), og
   fraktbryteren flyttet ut av denne raden (se render_price_list()) --
   s√• det er plass til alle 6 side om side selv p√• 320px mobil, ingen
   640px-brytpunkt n√∏dvendig her. Scoped via .product-stage (IKKE
   .wrap-product, som viste seg √• v√¶re delt med linsev√¶ske-/private
   label-/serie-sidene ogs√• -- .product-stage finnes derimot KUN i
   render_product_page() sin egen DOM, uansett skjermbredde, siden den
   ble innf√∏rt som en ustylet wrapper-div rundt .hero-card + qty_html
   allerede p√• mobil, se Desktop Gold Standard v1-runden samme dag). */
.product-stage .qty-pills { grid-template-columns: repeat(6, 1fr); }
.qty-pill { display: flex; flex-direction: column; align-items: center; gap: 3px; font-family: 'Mulish', sans-serif; background: linear-gradient(180deg, #FFFFFF 0%, var(--mist) 100%); border: 1px solid var(--border); border-radius: 10px; padding: 10px 6px; font-size: 0.9rem; font-weight: 600; text-align: center; cursor: pointer; color: var(--ink); line-height: 1.3; box-shadow: 0 3px 0 #C4D2D9, 0 4px 6px rgba(11,37,69,0.12); transition: transform 0.08s ease, box-shadow 0.08s ease; }
.qty-pill:active { transform: translateY(2px); box-shadow: 0 1px 0 #C4D2D9, 0 2px 3px rgba(11,37,69,0.1); }
.qty-pill svg { width: 20px; height: 20px; color: var(--blue); }
.qty-pill span { font-size: 0.75rem; font-weight: 400; color: var(--muted); }
/* Kompakt pille-variant, KUN p√• produktsiden (.wrap-product) -- ikon og
   enhetstekst ("eske"/"esker") skjules, kun tallet vises, akkurat som
   mockupen. Linsev√¶ske-/private label-sidene beholder de st√∏rre,
   fullstendige pillene uendret siden de ikke deler rad med noen
   fraktboks og har god plass. */
.wrap-product .qty-pill { flex-direction: row; justify-content: center; padding: 10px 2px; }
.wrap-product .qty-pill svg, .wrap-product .qty-pill span { display: none; }
@media (max-width: 479px) {
  /* Under 480px: enda knappere -- fraktbryteren deler n√• rad med
     "Priser for X esker"-overskriften i .offers-head (flyttet dit fra
     antallsvelgeren, se _ship_chip_boxed_html()), som er trangt p√• de
     smaleste skjermene. */
  .wrap-product .ship-chip-boxed { padding: 8px 10px; gap: 6px; }
  .wrap-product .ship-chip-label { font-size: 0.78rem; }
  .wrap-product .ship-chip-toggle { width: 34px; height: 20px; }
  .wrap-product .ship-chip-toggle::before { width: 16px; height: 16px; }
  .wrap-product .ship-chip-boxed[aria-pressed="true"] .ship-chip-toggle::before { transform: translateX(14px); }
}
.qty-pill.is-active { background: linear-gradient(180deg, #3ED4E4 0%, var(--blue) 100%); border-color: var(--blue); color: white; box-shadow: 0 3px 0 #1B95A3, 0 4px 6px rgba(11,37,69,0.18); }
.qty-pill.is-active:active { box-shadow: 0 1px 0 #1B95A3, 0 2px 3px rgba(11,37,69,0.15); }
.qty-pill.is-active svg { color: white; }
.qty-pill.is-active span { color: rgba(255,255,255,0.85); }
/* "Eget antall" -- kun linsev√¶ske-/√∏yedr√•pe-/private label-alias-sidene
   n√• (produktsiden fjernet den, se render_winner_widget() sin
   include_custom_pill-parameter, Kai 2026-09-27: "Ta bort Eget som
   valg av esker"). */
#qty-pill-custom { display: none; }
@media (min-width: 640px) { #qty-pill-custom { display: block; } }
.qty-custom-row { margin-top: 10px; }
#qty-custom-input { width: 140px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-family: 'Mulish', sans-serif; font-size: 0.9rem; }
/* Erstatter den tidligere "üí° Tips"-linja OG en usynlig (CSS-utenfor-skjerm)
   fallback-tekst -- Kai sin korreksjon 2026-09-27, etter √• ha sjekket Googles
   egne spam-retningslinjer: CSS som plasserer tekst utenfor skjermen st√•r
   DER som et eksempel p√• skjult tekst, mens et ekte, brukbart <details>-
   element (accordion) eksplisitt nevnes som en LEGITIM vis/skjul-mekanisme
   som ikke bryter retningslinjene. https://developers.google.com/search/docs/essentials/spam-policies
   <details> krever ingen JavaScript for √• utvides -- innholdet er ekte,
   server-rendret HTML uansett √•pen/lukket tilstand, lesbart for b√•de
   mennesker OG roboter uten JS (OAI-SearchBot m.fl. -- IKKE GPTBot, som er
   blokkert i robots.txt og aldri n√•r hit; GPTBot krabber til modelltrening,
   OAI-SearchBot er den som faktisk kan sitere siden i et AI-s√∏kesvar).
   Lukket som standard (ingen "open"-attributt) holder siden kompakt. */
.qty-multi { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 12px; }
.qty-multi summary { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; cursor: pointer; list-style: none; font-size: 0.85rem; color: var(--ink); }
.qty-multi summary::-webkit-details-marker { display: none; }
.qty-multi-label { font-weight: 600; flex-shrink: 0; }
.qty-multi-preview { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-family: 'Mulish', sans-serif; font-size: 0.82rem; }
.qty-multi-preview strong { color: var(--ink); font-weight: 600; }
.qty-multi-chevron { margin-left: auto; flex-shrink: 0; width: 16px; height: 16px; color: var(--muted); transition: transform 0.15s; }
.qty-multi[open] .qty-multi-chevron { transform: rotate(180deg); }
.qty-multi-body { margin: 10px 0 0; padding-left: 2px; display: flex; flex-direction: column; gap: 5px; font-size: 0.82rem; color: var(--muted); }
.qty-multi-body strong { color: var(--ink); }
"""


def _savings_eligible_offers(offers: list[dict], incl: bool) -> list[dict]:
    """Sammenligningsgrunnlaget for Savings Signal -- IKKE n√∏dvendigvis det
    samme som `eligible` ellers p√• siden. Kai sin korreksjon 2026-09-27:
    utelat utg√•tte (is_stale) tilbud, og i frakt-modus utelat tilbud med
    ukjent fraktpolicy (shipping_policy=None) siden ukjent frakt ALDRI skal
    telle som 0 kr i en totalpris-sammenligning."""
    pool = [o for o in offers if o["in_stock"] and not o.get("is_stale")]
    if incl:
        pool = [o for o in pool if o.get("shipping_policy") is not None]
    return pool


def _savings_metric(o: dict, qty: int, incl: bool) -> float:
    product_total = o["price_nok"] * qty
    if not incl:
        return product_total
    return product_total + compute_shipping_nok(product_total, o.get("shipping_policy"))


def compute_savings_pct(offers: list[dict], qty: int, incl: bool) -> int | None:
    """Eksakt, dynamisk besparelse -- IKKE "opptil" (Kai, 2026-09-27):
    saving_pct = (h√∏yeste - laveste sammenlignbare pris) / h√∏yeste * 100,
    for samme canonical produkt/pakning (gitt, siden `offers` alltid er ett
    produkt) og valgt quantity/prismodus. Avrundes ALLTID nedover
    (Math.floor) slik at vi aldri kommuniserer en st√∏rre besparelse enn den
    faktiske. Skjules helt under 10 % eller med f√¶rre enn 2 gyldige,
    sammenlignbare tilbud -- heller ingen besparelse enn en misvisende en."""
    pool = _savings_eligible_offers(offers, incl)
    if len(pool) < 2:
        return None
    values = [_savings_metric(o, qty, incl) for o in pool]
    highest, lowest = max(values), min(values)
    if highest <= 0:
        return None
    pct = math.floor((highest - lowest) / highest * 100)
    return pct if pct >= 10 else None


def _winner_price_line(o: dict, qty: int, incl: bool, unit_singular: str, unit_plural: str) -> str:
    """'232 kr/eske + 59 kr frakt' (ett eske), '928 kr/4 esker + 59 kr frakt'
    (flere esker, total produktpris -- 'kr/eske' gir ikke mening over 1), eller
    '291 kr inkl. frakt' i fraktmodus. Ukjent fraktpolicy i fraktmodus vises
    √¶rlig ('+ frakt beregnes i kassen'), late ALDRI som frakt er kjent/inkludert
    n√•r den ikke er det."""
    price_nok = o["price_nok"]
    shipping_policy = o.get("shipping_policy")
    product_total = price_nok * qty
    shipping_nok = compute_shipping_nok(product_total, shipping_policy)
    if incl and shipping_policy is not None:
        return f"{_fmt_kr(product_total + shipping_nok)} inkl. frakt"
    unit_part = f"{_fmt_kr(price_nok)}/{escape(unit_singular)}" if qty == 1 else f"{_fmt_kr(product_total)}/{qty} {escape(unit_plural)}"
    note = _shipping_note(shipping_nok, shipping_policy)
    if note.startswith("Gratis") or note.startswith("Frakt beregnes"):
        return f"{unit_part} ¬∑ {note}"
    return f"{unit_part} + {note}"


def _ship_chip_boxed_html(id_attr: str) -> str:
    """Den "boksede" frakt-vippebryteren (ikon/etikett/ekte bryter),
    brukt i prislisteheaderen p√• produktsiden (Kai, 2026-09-27, "MOVE
    SHIPPING TOGGLE ONLY": flyttet UT av quantity-omr√•det, inn i
    "Sammenlign priser"/"Priser for X esker"-headeren -- samme
    plassering p√• B√ÖDE mobil og desktop). Ingen undertekst ("Vis
    totalpris inkl. frakt") lenger -- Kai eksplisitt: "we do not need
    the current secondary line... Simply show: üöö Pris med frakt ‚óã",
    kompakt nok til √• h√∏re hjemme i selve headerraden."""
    return (
        f'<button type="button" class="ship-chip ship-chip-boxed" id="{id_attr}" aria-pressed="false">'
        f'<span class="ship-chip-icon" aria-hidden="true">{TRUCK_ICON_SVG}</span>'
        '<span class="ship-chip-label">Pris med frakt</span>'
        '<span class="ship-chip-toggle" aria-hidden="true"></span>'
        '</button>'
    )


def render_winner_widget(best: dict, offers: list[dict], product_name: str | None = None, unit_singular: str = "eske", unit_plural: str = "esker", product_id: str | None = None, clickouts: dict | None = None, wide: bool = False, qty_multi_inline: bool = True, qty_choices: tuple[int, ...] = (1, 2, 4, 6, 10), include_custom_pill: bool = True) -> tuple[str, str, str]:
    """Returnerer (winner_band, qty_box) som ETT tuple: vinnerkortet st√•r i toppen av
    siden, antallsvelgeren (qty_box) som egen seksjon under.

    Product Mobile Gold Standard v1 (2026-09-27, samme dag -- erstatter
    "Prisjakt-modellen" nedenfor, se kommentar der for historikken): kortet
    viser N√Ö pris ("232 kr/eske + 59 kr frakt"), et Savings Signal-merke
    ("Spar 43 %", kun ved >=10 % og >=2 sammenlignbare tilbud) og en
    "G√• til butikk"-knapp. `best` er tilbudet med laveste PRODUKTPRIS
    (samme som f√∏r). unit_singular/unit_plural: "eske"/"esker" for
    kontaktlinser, "flaske"/"flasker" for linsev√¶ske/√∏yedr√•per.

    Standardtilstanden (1 enhet, uten frakt) er ALLTID ekte, ferdig-rendret HTML, og det
    samme er 2/4/10-eksemplene i `<details class="qty-multi">`-raden under velgeren
    ("Pris ved flere esker") -- et vanlig, ekte HTML-element som ikke krever JavaScript
    for √• utvides, lesbart av roboter uten JS uansett √•pen/lukket tilstand (relevant her
    er OAI-SearchBot, IKKE GPTBot -- GPTBot er blokkert i robots.txt og krabber uansett
    kun til modelltrening, se der). Dette var tidligere en CSS-utenfor-skjerm-skjult
    tekst (til 2026-09-27) -- luket ut etter at Kai sjekket Googles spam-retningslinjer:
    CSS som plasserer tekst utenfor skjermen listes DER som et eksempel p√• skjult tekst,
    mens et <details>-element eksplisitt nevnes som en legitim vis/skjul-mekanisme.

    Fraktkostnaden regnes p√• nytt per antall (compute_shipping_nok), ikke bare
    multiplisert med shipping_nok for √©n enhet -- en fri-frakt-grense som ikke er n√•dd
    ved 1 enhet kan fint v√¶re n√•dd ved 4, og gir da en annen vinner enn ved enkeltkj√∏p."""
    if not best:
        return "", "", ""

    rel = "sponsored" if best["source"] == "affiliate_feed" else "nofollow"
    is_affiliate = "1" if best["source"] == "affiliate_feed" else "0"
    aria = f'G√• til {escape(best["retailer"])} for {escape(product_name)}' if product_name else f'G√• til {escape(best["retailer"])}'
    # Standard server-rendret tilstand er alltid qty=1/uten frakt (samme som
    # resten av kortet) -- JS tar over ved antalls-/frakt-bytte, se
    # _QTY_CALC_SCRIPT sin computeSavingsPct()/winnerPriceLine(), som er
    # bevisst holdt i n√∏yaktig synk med disse to Python-funksjonene.
    savings_pct = compute_savings_pct(offers, 1, False)
    price_line = _winner_price_line(best, 1, False, unit_singular, unit_plural)
    savings_html = (
        f'<div class="winner-savings" id="winner-savings"><span class="winner-savings-label">Spar</span><span class="winner-savings-pct">{savings_pct} %</span></div>'
        if savings_pct is not None else
        '<div class="winner-savings" id="winner-savings" hidden><span class="winner-savings-label">Spar</span><span class="winner-savings-pct">0 %</span></div>'
    )
    # Kortet er en <div>; selve KNAPPEN er lenken (id + tracking-attributter),
    # slik at ingenting havner n√∏stet inni en annen <a>.
    winner_band = f"""<div class="winner-band winner-band-cta{' winner-band-wide' if wide else ''}">
  <div class="winner-top">
    <div class="label-group">
      <div class="label" id="winner-label">Laveste pris</div>
      <div class="winner-sub" id="winner-sub">for 1 {escape(unit_singular)}</div>
    </div>
    {savings_html}
  </div>
  <div class="retailer" id="winner-retailer">{_retailer_badge_html(best["retailer"])}</div>
  <div class="winner-price-line" id="winner-price-line">{price_line}</div>
  <a class="winner-btn" id="winner-band-link" href="{escape(outbound_url(best, best["retailer"], product_id, clickouts, "winner_band"))}" target="_blank" rel="{rel} noopener" aria-label="{aria}" data-retailer="{escape(best["retailer"])}" data-affiliate="{is_affiliate}">G√• til butikk <span aria-hidden="true">&#8594;</span></a>
</div>"""

    eligible = [o for o in offers if o["in_stock"]]
    if len(eligible) < 2:
        return winner_band, "", ""  # ingen reell antalls-sammenligning √• tilby med 0-1 tilbud

    def total_for_qty(o: dict, qty: int) -> float:
        product_total = o["price_nok"] * qty
        return product_total + compute_shipping_nok(product_total, o.get("shipping_policy"))

    # "Eget antall"-pillen fjernet helt (Kai, 2026-09-27: "Ta bort Eget
    # som valg av esker"), erstattet med en ny fast "8"-pille (samme dag,
    # oppf√∏lging: "Antall Esker overalt. 1,2,4,6,8,10, b√•de p√• desktop
    # og mobil") -- seks faste antall n√•, p√• b√•de mobil og desktop.
    # Frakt-bryteren er samtidig flyttet UT av denne raden (se
    # render_price_list()), s√• hele bredden er n√• pillenes alene.
    pills = "".join(
        f'<button type="button" class="qty-pill{" is-active" if qty == 1 else ""}" data-qty="{qty}">{BOX_ICON_SVG}{qty}<span>{escape(unit_singular) if qty == 1 else escape(unit_plural)}</span></button>'
        for qty in qty_choices
    )
    if include_custom_pill:
        pills += f'<button type="button" class="qty-pill" data-qty="custom" id="qty-pill-custom">{PENCIL_ICON_SVG}Eget<span>antall</span></button>'

    # Kompakt forh√•ndsvisning i selve <summary>-raden ("2 esker ¬∑ 514 kr" osv.)
    # pluss en mer detaljert (butikk + frakt) rad per antall i den utvidbare
    # kroppen -- begge deler er ekte, server-rendret HTML uansett √•pen/lukket
    # tilstand, se docstringen over.
    multi_preview_parts, multi_detail_parts = [], []
    for qty in (2, 4, 10):
        best_o = min(eligible, key=lambda o: total_for_qty(o, qty))
        total = total_for_qty(best_o, qty)
        qty_shipping = compute_shipping_nok(best_o["price_nok"] * qty, best_o.get("shipping_policy"))
        note = _shipping_note(qty_shipping, best_o.get("shipping_policy"))
        multi_preview_parts.append(f'<span>{qty} {escape(unit_plural)} ¬∑ <strong>{_fmt_kr(total)}</strong></span>')
        multi_detail_parts.append(
            f'<p>{qty} {escape(unit_plural)} ¬∑ <strong>{escape(best_o["retailer"])}</strong> ¬∑ {_fmt_kr(total)} totalt ¬∑ {note}</p>'
        )
    qty_multi_html = f'''<details class="qty-multi">
    <summary>
      <span class="qty-multi-label">Pris ved flere {escape(unit_plural)}</span>
      <span class="qty-multi-preview">{"".join(multi_preview_parts)}</span>
      <svg class="qty-multi-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
    </summary>
    <div class="qty-multi-body">{"".join(multi_detail_parts)}</div>
  </details>'''

    # ALLE tilbud (ikke bare "eligible") sendes med her -- selv et utsolgt/
    # utdatert tilbuds pris/frakt-rad under skal fortsatt oppdateres riktig
    # ved antallsbytte, det er bare "Lavest pris"-merket og vinner-boksen som
    # aldri kan lande p√• et slikt tilbud (samme regel som reconcile()).
    calc_offers = []
    for o in offers:
        logo_entry = RETAILER_LOGOS.get(o["retailer"])
        calc_offers.append({
            "retailer": o["retailer"],
            "price_nok": o["price_nok"],
            "shipping_policy": o.get("shipping_policy"),
            "url": outbound_url(o, o["retailer"], product_id, clickouts, "quantity_calculator"),
            "rel": ("sponsored" if o["source"] == "affiliate_feed" else "nofollow") + " noopener",
            "logo_file": logo_entry[0] if logo_entry else None,
            "logo_dark": logo_entry[1] if logo_entry else False,
            "in_stock": o["in_stock"],
            "is_stale": o["is_stale"],
        })
    calc_offers_json = json.dumps(calc_offers, ensure_ascii=False).replace("</", "<\\/")

    # Frakt-bryteren bodde tidligere her, ved siden av antallspillene
    # (Product Mobile Gold Standard v1, 2026-09-27). Flyttet UT av
    # quantity-omr√•det og inn i prislisteheaderen i stedet (Kai, samme
    # dag, IMPORTANT UI CHANGE -- MOVE SHIPPING TOGGLE ONLY: "The toggle
    # belongs to the price comparison section, because it controls
    # which price basis is used for the comparison/ranking" -- gjelder
    # n√• B√ÖDE mobil og desktop, ikke lenger kun desktop som i en
    # tidligere, siden overstyrt versjon av samme instruks). Se
    # render_price_list()'s `product_ship_chip_html`-parameter og
    # `_ship_chip_boxed_html()`. `qty-box-row` inneholder derfor n√• KUN
    # antallspillene.
    custom_row_html = (
        f'<div class="qty-custom-row" id="qty-custom-row" hidden>'
        f'<input type="number" id="qty-custom-input" min="1" max="50" inputmode="numeric" placeholder="Antall {escape(unit_plural)}"></div>'
        if include_custom_pill else ""
    )
    qty_box = f"""<div class="qty-box">
    <div class="qty-box-title">Antall {escape(unit_plural)}</div>
    <div class="qty-box-row">
      <div class="qty-pills" id="qty-pills">{pills}</div>
    </div>
    {custom_row_html}
    {qty_multi_html if qty_multi_inline else ""}
  </div>
  <script type="application/json" id="qty-offers-data" data-product-name="{escape(product_name or '')}" data-unit-singular="{escape(unit_singular)}" data-unit-plural="{escape(unit_plural)}">{calc_offers_json}</script>
  {_QTY_CALC_SCRIPT}"""

    # qty_multi_html ("Pris ved flere esker") returneres n√• SEPARAT (egen
    # tredje verdi) i stedet for √• alltid ligge inni qty_box -- produktsiden
    # (2026-09-27, Kai: "Teksten Pris ved flere esker, flyttes ogs√• ned
    # under priser") plasserer den under prislista i stedet. De to andre
    # kallerne (linsev√¶ske/√∏yedr√•per, private label-alias) er uendret --
    # de limer den rett tilbake inn der den var (se kallestedene).
    return winner_band, qty_box, qty_multi_html


# ---------------------------------------------------------------------------
# PRISJAKT-MODELLEN (utrullet 2026-09-27 p√• alle produktsider: kontaktlinser, linsev√¶ske/
# √∏yedr√•per og private label). Avtalt med Kai etter konkurrentgjennomgang: Prisjakt,
# Pricerunner, Prisguiden, godpris og Lenspricer viser alle pris UTEN frakt som standard,
# og Prisjakt har en chip "Pris inkludert frakt" som legger p√• frakt og sorterer om.
#   - Toppknappen ("Laveste pris ... G√• til tilbud") sier IKKE pris.
#   - Lista under er sortert p√• produktpris (uten frakt); chippen "Pris inkludert frakt"
#     viser og sorterer p√• totalpris for valgt antall. Valget huskes (localStorage).
#   - Antallsvelgeren gjelder begge modi.
#   - Kortet med laveste TOTALpris merkes "Lavest totalpris" ogs√• i standardvisningen n√•r
#     det er en annen butikk enn den med laveste produktpris (vi p√•st√•r aldri "lavest" om
#     noe som ikke er det).
#   - Samlesider (kategori/merke/serie/private label-oversikter) viser "Fra"-pris uten frakt.
PRICE_LIST_STYLE = """
.offers-head { display: flex; align-items: center; justify-content: space-between; gap: 12px 16px; flex-wrap: wrap; margin: 0 0 12px; }
.offers-head h2 { margin: 0; }
.offers-sort-label { font-size: 0.78rem; color: var(--muted); }
/* "Vis alle priser (X butikker)" -- KUN mobil (Kai, 2026-09-27,
   desktop-korreksjon: "Do not collapse the merchant price list. On
   desktop, render all valid current offers immediately [...] The full
   merchant list is part of the value proposition"). Server-siden bygger
   fortsatt `is-collapsed`-klassen og knappen n√•r det er >10 tilbud
   (samme `collapse_after`-param, brukt av B√ÖDE mobil og desktop, terskel
   hevet fra 3 til 10 p√• Kais eksplisitte √∏nske 2026-09-29: "Vis alle
   treff opp til 10 priser, og deretter hvis flere, klikk for √• vise
   alle"), men CSS-en her gj√∏r kollapsen usynlig >=860px -- samme
   brytpunkt som resten av sidens desktop-layout (.hero-main sitt grid).
   Ingen JS-endring n√∏dvendig: _QTY_CALC_SCRIPT sin render() sorterer og
   re-append'er HELE listen uansett skjerm-bredde, kollapsen var alltid
   bare et rent CSS-lag opp√• den samme, allerede fullstendige listen. */
.offers.is-collapsed .offers-list .offer-card:nth-child(n+11) { display: none; }
.offers-show-more { display: block; width: 100%; margin-top: 10px; padding: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; font-family: 'Mulish', sans-serif; font-weight: 600; font-size: 0.88rem; color: var(--blue); cursor: pointer; text-align: center; }
.offers-show-more:hover { border-color: var(--blue); }
@media (min-width: 860px) {
  .offers.is-collapsed .offers-list .offer-card:nth-child(n+11) { display: flex; }
  .offers-show-more { display: none; }
}
.ship-chip { display: inline-flex; align-items: center; gap: 9px; background: white; border: 1.5px solid var(--border); border-radius: 999px; padding: 9px 16px 9px 12px; font-family: 'Mulish', sans-serif; font-weight: 600; font-size: 0.88rem; color: var(--ink); cursor: pointer; transition: border-color 0.15s, background-color 0.15s; }
.ship-chip:hover { border-color: var(--blue); }
.ship-chip:focus-visible { outline: 3px solid var(--blue-tint); outline-offset: 1px; border-color: var(--blue); }
.ship-chip-dot { width: 18px; height: 18px; border-radius: 50%; border: 2px solid #B8C6CF; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; background: white; transition: background-color 0.15s, border-color 0.15s; }
.ship-chip[aria-pressed="true"] { border-color: var(--ink); background: var(--blue-tint); }
.ship-chip[aria-pressed="true"] .ship-chip-dot { background: var(--ink); border-color: var(--ink); }
.ship-chip[aria-pressed="true"] .ship-chip-dot::after { content: ""; width: 5px; height: 9px; border: solid white; border-width: 0 2px 2px 0; transform: translateY(-1px) rotate(45deg); }
.winner-band-cta { flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 14px; max-width: 380px; margin: 14px auto; }
.winner-band-cta:hover, .winner-band-cta:focus-within { border-color: #BFE7D5; box-shadow: none; }
.winner-band-cta .winner-left { flex-direction: column; align-items: center; gap: 0; }
.winner-band-cta .label-group { display: flex; flex-direction: column; align-items: center; }
.winner-band-cta .label { font-size: 0.86rem; letter-spacing: 0.06em; }
.winner-sub { font-size: 0.82rem; color: var(--muted); margin-top: 1px; }
.winner-band-cta .retailer { justify-content: center; margin-top: 14px; }
.winner-band-cta .retailer-logo { height: 30px; max-width: 150px; }
.winner-btn { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; background: var(--mint); color: white; font-weight: 700; font-size: 0.95rem; padding: 12px 20px; border-radius: 999px; text-decoration: none; white-space: nowrap; transition: filter 0.15s, box-shadow 0.15s; }
.winner-btn:hover, .winner-btn:focus-visible { filter: brightness(0.93); box-shadow: 0 3px 10px rgba(11, 163, 111, 0.28); }
.winner-more { font-size: 0.82rem; font-weight: 600; color: var(--blue); text-decoration: none; }
.winner-more:hover { text-decoration: underline; }
#tilbud { scroll-margin-top: 16px; }
/* Sider uten hero-kolonne (linsev√¶ske, √∏yedr√•per, private label): kortet blir
   en bred stripe. Info-elementene (winner-top/retailer/pris-linje) er n√•
   flate s√∏sken (ikke lenger n√∏stet i en .winner-left-wrapper), s√• de plasseres
   hver for seg i kolonne 1, mens knappen spenner alle tre radene i kolonne 2. */
@media (min-width: 700px) {
  .winner-band-wide { max-width: none; margin: 16px 0; display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto auto; align-items: center; text-align: left; column-gap: 28px; row-gap: 4px; padding: 18px 24px; }
  .winner-band-wide .winner-top { grid-column: 1; grid-row: 1; }
  .winner-band-wide .winner-top .label-group { align-items: flex-start; text-align: left; }
  .winner-band-wide .retailer { grid-column: 1; grid-row: 2; justify-content: flex-start; margin-top: 4px; }
  .winner-band-wide .winner-price-line { grid-column: 1; grid-row: 3; text-align: left; margin-top: 2px; }
  .winner-band-wide .winner-btn { grid-column: 2; grid-row: 1 / 4; width: auto; min-width: 210px; }
}
@media (min-width: 860px) {
  /* align-self: center -- kortet er kun s√• h√∏yt som innholdet og flyter midt i
     kolonnen, i stedet for √• strekkes til hele hero-radens h√∏yde (ga et stort
     tomrom inni kortet). */
  .hero-main .winner-band-cta { align-self: center; padding: 42px 20px 22px; gap: 16px; }
}
"""

_QTY_CALC_SCRIPT = r"""<script>
(function () {
  var dataEl = document.getElementById('qty-offers-data');
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);
  var productName = dataEl.getAttribute('data-product-name') || '';
  var unitSingular = dataEl.getAttribute('data-unit-singular') || 'eske';
  var unitPlural = dataEl.getAttribute('data-unit-plural') || 'esker';
  var pills = document.querySelectorAll('.qty-pill');
  var labelEl = document.getElementById('winner-label');
  var retailerEl = document.getElementById('winner-retailer');
  var winnerLink = document.getElementById('winner-band-link');
  var priceLineEl = document.getElementById('winner-price-line');
  var savingsEl = document.getElementById('winner-savings');
  var state = { qty: 1, incl: false };
  // Dette scriptet ligger F√òR .offers og bryteren i kildekoden (vinnerboksen og
  // antallsvelgeren st√•r √∏verst), s√• elementer under sl√•s opp f√∏rst n√•r de brukes.

  function computeShipping(productTotal, policy) {
    if (!policy) return 0;
    var freeOver = policy.free_over;
    if (freeOver !== null && freeOver !== undefined && productTotal >= freeOver) return 0;
    return policy.fee_nok || 0;
  }
  function fmtKr(n) {
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' kr';
  }
  function shippingNote(shipping, policy) {
    if (!policy) return 'Frakt beregnes i kassen';
    if (shipping <= 0) {
      if (policy.free_over) return 'Gratis frakt over ' + fmtKr(policy.free_over);
      return 'Gratis frakt';
    }
    return fmtKr(shipping) + ' frakt';
  }
  function retailerBadge(o) {
    if (!o.logo_file) return o.retailer;
    var img = '<img class="retailer-logo" src="/static/logos/' + o.logo_file + '" alt="' + o.retailer + '" loading="lazy">';
    var logo = o.logo_dark ? '<span class="retailer-logo-chip">' + img + '</span>' : img;
    return logo + '<span style="position:absolute;left:-9999px;">' + o.retailer + '</span>';
  }
  function findCard(cards, retailer) {
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].getAttribute('data-retailer') === retailer) return cards[i];
    }
    return null;
  }
  // Speiler compute_savings_pct()/_winner_price_line() i render_templates.py
  // n√∏yaktig -- samme utelatelsesregler (utg√•tt, ukjent frakt i fraktmodus),
  // samme Math.floor-avrunding, samme 10%-terskel. Hold disse i synk.
  function savingsEligible(incl) {
    var pool = [];
    for (var i = 0; i < data.length; i++) {
      var o = data[i];
      if (!o.in_stock || o.is_stale) continue;
      if (incl && !o.shipping_policy) continue;
      pool.push(o);
    }
    return pool;
  }
  function savingsMetric(o, qty, incl) {
    var productTotal = o.price_nok * qty;
    if (!incl) return productTotal;
    return productTotal + computeShipping(productTotal, o.shipping_policy);
  }
  function computeSavingsPct(qty, incl) {
    var pool = savingsEligible(incl);
    if (pool.length < 2) return null;
    var lo = Infinity, hi = -Infinity;
    for (var i = 0; i < pool.length; i++) {
      var v = savingsMetric(pool[i], qty, incl);
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (hi <= 0) return null;
    var pct = Math.floor((hi - lo) / hi * 100);
    return pct >= 10 ? pct : null;
  }
  function winnerPriceLine(o, qty, incl) {
    var productTotal = o.price_nok * qty;
    var shipping = computeShipping(productTotal, o.shipping_policy);
    if (incl && o.shipping_policy) return fmtKr(productTotal + shipping) + ' inkl. frakt';
    var unitPart = qty === 1 ? (fmtKr(o.price_nok) + '/' + unitSingular) : (fmtKr(productTotal) + '/' + qty + ' ' + unitPlural);
    var note = shippingNote(shipping, o.shipping_policy);
    if (note.indexOf('Gratis') === 0 || note.indexOf('Frakt beregnes') === 0) return unitPart + ' ¬∑ ' + note;
    return unitPart + ' + ' + note;
  }

  function render() {
    var qty = state.qty, incl = state.incl;
    var results = [];
    for (var i = 0; i < data.length; i++) {
      var o = data[i];
      var productTotal = o.price_nok * qty;
      var shipping = computeShipping(productTotal, o.shipping_policy);
      results.push({ o: o, idx: i, productTotal: productTotal, shipping: shipping, total: productTotal + shipping });
    }
    // Standard: laveste produktpris. Med "Pris inkludert frakt": laveste totalpris.
    // Lik pris -> den andre prisen -> opprinnelig rekkef√∏lge (server har allerede
    // lagt avtale-forhandlere foran ved eksakt likt).
    results.sort(function (a, b) {
      var ka = incl ? a.total : a.productTotal, kb = incl ? b.total : b.productTotal;
      var sa = incl ? a.productTotal : a.total, sb = incl ? b.productTotal : b.total;
      return (ka - kb) || (sa - sb) || (a.idx - b.idx);
    });
    var best = null;
    for (var i = 0; i < results.length; i++) { if (results[i].o.in_stock) { best = results[i]; break; } }

    if (best) {
      labelEl.textContent = incl ? 'Lavest totalpris' : 'Laveste pris';
      var subEl = document.getElementById('winner-sub');
      if (subEl) subEl.textContent = 'for ' + qty + ' ' + (qty === 1 ? unitSingular : unitPlural);
      retailerEl.innerHTML = retailerBadge(best.o);
      if (priceLineEl) priceLineEl.textContent = winnerPriceLine(best.o, qty, incl);
      if (savingsEl) {
        var pct = computeSavingsPct(qty, incl);
        if (pct === null) {
          savingsEl.hidden = true;
        } else {
          savingsEl.hidden = false;
          var pctEl = savingsEl.querySelector('.winner-savings-pct');
          if (pctEl) pctEl.textContent = pct + ' %';
        }
      }
      winnerLink.setAttribute('href', best.o.url);
      winnerLink.setAttribute('rel', best.o.rel);
      winnerLink.setAttribute('aria-label', 'G√• til ' + best.o.retailer + (productName ? ' for ' + productName : ''));
      winnerLink.setAttribute('data-retailer', best.o.retailer);
      winnerLink.setAttribute('data-affiliate', best.o.rel.indexOf('sponsored') !== -1 ? '1' : '0');
    }

    var qtyLabelEl = document.getElementById('offers-qty-label');
    if (qtyLabelEl) qtyLabelEl.textContent = qty + ' ' + (qty === 1 ? unitSingular : unitPlural);
    var sortLabelEl = document.getElementById('offers-sort-label');
    if (sortLabelEl) sortLabelEl.textContent = incl ? 'Sortert etter totalpris' : 'Sortert etter pris (uten frakt)';

    var offersList = document.querySelector('.offers-list');
    var cards = offersList ? offersList.querySelectorAll('.offer-card') : [];
    if (!offersList || !cards.length) return;
    for (var i = 0; i < results.length; i++) {
      var r = results[i];
      var card = findCard(cards, r.o.retailer);
      if (!card) continue;
      var shown = incl ? r.total : r.productTotal;
      var pricePillEl = card.querySelector('.price-pill');
      if (pricePillEl) pricePillEl.textContent = fmtKr(shown);
      card.setAttribute('aria-label', 'G√• til ' + r.o.retailer + (productName ? ' for ' + productName : '') + ', ' + fmtKr(shown) + (incl ? ' inkl. frakt' : ' uten frakt'));
      var shipTextEl = card.querySelector('.offer-shipping-text');
      if (shipTextEl) shipTextEl.textContent = (incl && r.shipping > 0 && r.o.shipping_policy) ? 'inkl. ' + fmtKr(r.shipping) + ' frakt' : shippingNote(r.shipping, r.o.shipping_policy);
      var isBest = !!(best && r.o.retailer === best.o.retailer);
      card.classList.toggle('is-lowest', isBest);
      offersList.appendChild(card);
    }
  }

  function setIncl(v, track) {
    state.incl = v;
    var chip = document.getElementById('ship-chip');
    if (chip) chip.setAttribute('aria-pressed', v ? 'true' : 'false');
    try { localStorage.setItem('kl_incl_shipping', v ? '1' : '0'); } catch (e) {}
    render();
    if (track) {
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'price_shipping_toggle', included: v ? 'yes' : 'no' });
    }
  }
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('#ship-chip')) setIncl(!state.incl, true);
    var showMoreBtn = e.target.closest && e.target.closest('#offers-show-more');
    if (showMoreBtn) {
      var offersEl = document.querySelector('.offers');
      if (offersEl) offersEl.classList.remove('is-collapsed');
      showMoreBtn.remove();
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({ event: 'offers_show_all' });
    }
  });

  var customRow = document.getElementById('qty-custom-row');
  var customInput = document.getElementById('qty-custom-input');
  for (var i = 0; i < pills.length; i++) {
    pills[i].addEventListener('click', function (e) {
      for (var j = 0; j < pills.length; j++) { pills[j].classList.remove('is-active'); }
      e.currentTarget.classList.add('is-active');
      var qty = e.currentTarget.getAttribute('data-qty');
      if (qty === 'custom') {
        if (customRow) customRow.hidden = false;
        if (customInput) {
          customInput.focus();
          var v = parseInt(customInput.value, 10);
          if (v) { state.qty = v; render(); }
        }
      } else {
        if (customRow) customRow.hidden = true;
        state.qty = parseInt(qty, 10);
        render();
      }
    });
  }
  if (customInput) {
    customInput.addEventListener('input', function () {
      var v = parseInt(customInput.value, 10);
      if (v && v > 0) { state.qty = v; render(); }
    });
  }

  function restoreChoice() {
    try { if (localStorage.getItem('kl_incl_shipping') === '1') setIncl(true, false); } catch (e) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restoreChoice);
  else restoreChoice();
})();
</script>"""

PRICE_DISCLOSURE_HTML = """<p class="disclosure">
    Butikkene sorteres etter lavest produktpris. Sl√• p√• ¬´Pris inkludert frakt¬ª for √•
    se og sortere etter totalpris (produktpris + frakt) for antallet du har valgt.
    Vi kan f√• provisjon n√•r du handler via lenkene, men det p√•virker aldri prisen du
    betaler. Rekkef√∏lgen er alltid basert p√• pris, bortsett fra ved eksakt lik pris
    mellom to tilbud, der vi kan prioritere en forhandler vi har avtale med. Varer
    uten bekreftet lager kan ikke vinne ¬´laveste pris¬ª, og hvert tilbud viser n√•r det
    sist ble kontrollert.
  </p>"""


def order_by_product_price(offers: list[dict]) -> list[dict]:
    return sorted(offers, key=lambda o: (o["price_nok"], o["total"]) + _tie_break_key(o))


def render_price_list(offers: list[dict], product_name: str, product_id: str, clickouts: dict | None,
                      title: str = "Sammenlign priser og butikker", show_ship_chip: bool = True,
                      qty_unit_label: str | None = None, collapse_after: int | None = None,
                      product_ship_chip_html: str | None = None) -> tuple[str, dict | None]:
    """Prislista med chippen "Pris inkludert frakt". Returnerer (html, ex_best) der ex_best er
    tilbudet med laveste PRODUKTPRIS (p√• lager) -- det toppknappen (render_winner_widget) skal
    peke p√•. Statisk standardvisning = uten frakt, antall 1; JS (_QTY_CALC_SCRIPT) tar resten.

    qty_unit_label/collapse_after: kun brukt av produktsiden (Product Mobile
    Gold Standard v1, 2026-09-27) -- qty_unit_label bytter overskriften til
    en dynamisk "Priser for 1 eske" (+ sorteringsetikett) i stedet for
    `title`, og collapse_after (10 p√• produktsiden) skjuler resten av
    kortene bak en "Vis alle priser (X butikker)"-knapp. Begge er None/av
    som standard,
    s√• linsev√¶ske-/√∏yedr√•pe- og private label-alias-sidene er uendret.

    product_ship_chip_html: kun produktsiden (Kai, 2026-09-27, "IMPORTANT
    UI CHANGE -- MOVE SHIPPING TOGGLE ONLY": "The toggle belongs to the
    price comparison section, because it controls which price basis is
    used for the comparison/ranking" -- gjelder B√ÖDE mobil og desktop).
    Den FERDIGBYGGEDE frakt-vippebryteren (`_ship_chip_boxed_html()`,
    bygget i render_product_page()), rendres her, h√∏yrejustert i
    .offers-head ved siden av den dynamiske "Priser for X
    esker"-overskriften. None/av som standard, s√• linsev√¶ske-/
    √∏yedr√•pe- og private label-alias-sidene (som fortsatt bruker den
    enkle `show_ship_chip`/`chip`-mekanismen under) er uendret."""
    ordered = order_by_product_price(offers)
    ex_best = next((o for o in ordered if o["in_stock"]), None)

    cards = "\n".join(
        render_offer_card(o, o["retailer"], product_name, product_id, clickouts, is_winner=(o is ex_best))
        for o in ordered
    )
    # show_ship_chip=False p√• produktsiden (Product Mobile Gold Standard v1,
    # 2026-09-27) -- bryteren flyttet til qty_box i render_winner_widget,
    # ved siden av antalls-tittelen. Standard er fortsatt True, s√•
    # linsev√¶ske-/√∏yedr√•pe- og private label-alias-sidene (som ikke er
    # restrukturert i denne runden) beholder chippen akkurat som f√∏r.
    chip = (
        '<button type="button" class="ship-chip" id="ship-chip" aria-pressed="false">'
        '<span class="ship-chip-dot" aria-hidden="true"></span>Pris inkludert frakt</button>'
    ) if (ordered and show_ship_chip) else ""
    # "Sortert etter pris (uten frakt)"-etiketten er ERSTATTET av selve
    # frakt-vippebryteren n√•r den er til stede (Kai, 2026-09-27: "der
    # hvor Sortert etter pris (uten frakt) st√•r i dag som skal da
    # erstattes med switchen") -- bryteren KOMMUNISERER allerede hvilken
    # prisbasis lista er sortert etter (av/p√•), s√• en egen tekstetikett
    # ved siden av er overfl√∏dig. Uendret (fortsatt med etiketten) for
    # linsev√¶ske-/√∏yedr√•pe-/private label-alias-sidene, som ikke har
    # denne bryteren i headeren.
    header_html = (
        f'<h2>Priser for <span id="offers-qty-label">{escape(qty_unit_label)}</span></h2>'
        + ("" if product_ship_chip_html else '<span class="offers-sort-label" id="offers-sort-label">Sortert etter pris (uten frakt)</span>')
        if qty_unit_label else f'<h2>{escape(title)}</h2>'
    )
    n_in_stock = len([o for o in ordered if o["in_stock"]])
    collapse = collapse_after is not None and n_in_stock > collapse_after
    show_more_html = (
        f'<button type="button" class="offers-show-more" id="offers-show-more">'
        f'Vis alle priser ({n_in_stock} {"butikk" if n_in_stock == 1 else "butikker"})</button>'
        if collapse else ""
    )
    html = f"""<div class="offers{' is-collapsed' if collapse else ''}" id="tilbud">
    <div class="offers-head">
      {header_html}
      {chip}
      {product_ship_chip_html or ""}
    </div>
    <div class="offers-list">{cards}</div>
    {show_more_html}
  </div>"""
    return html, ex_best


def _pack_size_from_id(product_id: str) -> tuple[str, int] | None:
    """Plukker ut ('produkt-stamme', pakningsst√∏rrelse) fra en id som slutter
    p√• f.eks. '-30pk' eller '-3pk'. Brukes til √• finne s√∏sken i andre
    pakningsst√∏rrelser uten √• hardkode hvilke st√∏rrelser som finnes -- samme
    produkt kan ha 2 eller 3 s√∏sken (f.eks. Dailies AquaComfort Plus i
    30/90/180-pakning)."""
    if not product_id.endswith("pk"):
        return None
    stem, sep, size_part = product_id[:-2].rpartition("-")
    if not sep or not size_part.isdigit():
        return None
    return stem, int(size_part)


def find_pack_siblings(product: dict, products_by_id: dict) -> list[tuple[int, dict]]:
    """ALLE andre pakningsst√∏rrelser av samme faktiske produkt, stigende etter
    pakningsst√∏rrelse.

    KONTAKTLINSER.NO-REGEL (egenskap/katalog), IKKE en universell canonical
    Product identity-regel. Regelen bygger p√• denne siten sin LOKALE
    id-konvensjon `<stamme>-<N>pk`, der `<N>` er antall linser per pakning
    (f.eks. `everclear-elite-90pk` -> stamme `everclear-elite`, 90 linser).
    Disse id-ene er Kontaktlinser.no sine egne interne produkt-id-er og koder
    pakningsst√∏rrelse; de er IKKE Chillouts canonical `product_id` (en opak
    `prd_...`-id, der Kontaktlinser-id-en bare er et alias). Regelen sier derfor
    ingenting om produktidentitet for Chillout eller andre properties og skal
    ikke gjenbrukes der. En annen property m√• definere sin egen
    variant-/pakningsregel.

    "Samme produkt" = lik stamme foran avsluttende -Npk OG samme merke og
    kategori; aldri navnelikhet. En variant med annet navn i stammen (f.eks.
    '...-astigmatism-30pk' mot '...-30pk') er et eget produkt og telles ikke."""
    parsed = _pack_size_from_id(product["id"])
    if not parsed:
        return []
    stem = parsed[0]
    siblings: list[tuple[int, dict]] = []
    for pid, other in products_by_id.items():
        if pid == product["id"]:
            continue
        other_parsed = _pack_size_from_id(pid)
        if not other_parsed or other_parsed[0] != stem:
            continue
        if other.get("brand_slug") != product.get("brand_slug") or other.get("category_slug") != product.get("category_slug"):
            continue
        siblings.append((other_parsed[1], other))
    siblings.sort(key=lambda s: s[0])
    return siblings


def _is_daily_lens(product: dict) -> bool:
    """Dagslinse ut fra den faktiske produktegenskapen (spesifikasjonen
    "Brukstid"), ikke ut fra hvilken kategori produktet tilfeldigvis ligger i:
    toriske, multifokale og fargede dagslinser ligger i egne kategorier."""
    return any(label == "Brukstid" and value == "Dagslinse" for label, value in product.get("specs", []))


_NORWEGIAN_MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"]


def _format_no_date(date_str: str, with_year: bool = True) -> str:
    """'2026-08-19' -> '19. august 2026' (eller '19. august' uten √•rstall)."""
    year, month, day = date_str.split("-")
    text = f"{int(day)}. {_NORWEGIAN_MONTHS[int(month) - 1]}"
    return f"{text} {year}" if with_year else text


# Price Intelligence (Product Gold Standard v1, 2026-09-27) -- gjenbrukbart
# rammeverk for prisutviklings-modulen, IKKE produktspesifikk kode (Kai,
# absolutt regel 8). Periodene som faktisk kan velges avhenger av hvor mye
# historikk vi FAKTISK har for produktet (se _price_intelligence_eligible_
# periods()) -- i dag (2026-09-27) har INGEN produkt mer enn 45 dagers
# historikk (price_history.json sjekket direkte), s√• 90 dager/6 m√•neder/1 √•r
# er deaktivert for absolutt alle produkter enn√•. Dette er IKKE hardkodet
# noe sted -- rammeverket aktiverer periodene automatisk etter hvert som
# price_history.json vokser med √©n dag per bygging (record_price() i
# price_history.py), uten kodeendring.
PRICE_INTELLIGENCE_PERIODS: list[tuple[str, str, int | None]] = [
    ("30d", "30 dager", 30),
    ("90d", "90 dager", 90),
    ("6m", "6 m√•neder", 182),
    ("1y", "1 √•r", 365),
    ("all", "All historikk", None),
]

# Toleranse for "stabil pris" (regel 6: "Avoid meaningless claims caused by
# 1 kr fluctuations") -- en endring innenfor +-STATUS_STABLE_TOLERANCE_PCT
# regnes IKKE som en reell opp-/nedgang. Et produkt m√• ha v√¶rt helt
# UENDRET i minst STATUS_FLAT_MIN_DAYS sammenhengende dager (regnet
# bakover fra siste observasjon) for √• f√• den mer spesifikke "flat i N
# dager"-meldingen i stedet for en generisk "stabil"-melding.
STATUS_STABLE_TOLERANCE_PCT = 3.0
STATUS_FLAT_MIN_DAYS = 7


def _price_intelligence_eligible_periods(coverage_days: int) -> list[tuple[str, str, int | None]]:
    """Hvilke av PRICE_INTELLIGENCE_PERIODS vi faktisk har nok data til √•
    vise (regel 7/21/22 -- "Only enable periods for which sufficient data
    exists", data-kvalitetsport). "All historikk" er alltid tilgjengelig
    (den viser uansett bare det vi faktisk har)."""
    return [(key, label, days) for key, label, days in PRICE_INTELLIGENCE_PERIODS if days is None or coverage_days >= days]


def _price_intelligence_window(history: list[dict], days: int | None) -> list[dict]:
    """Historikken for det siste `days`-vinduet (None = alt vi har). `history`
    er alltid sortert eldst->nyest (garantert av record_price())."""
    return history if days is None else history[-days:]


def _price_intelligence_status(window: list[dict]) -> dict:
    """Deterministisk statusvurdering for ETT vindu av historikken --
    ALDRI en LLM-generert kommentar (regel 5), kun de eksplisitte reglene
    dokumentert her (regel 6):
      1. flat: prisen har v√¶rt helt UENDRET i >=STATUS_FLAT_MIN_DAYS dager
         (regnet bakover fra siste observasjon) -- den mest spesifikke,
         mest informative meldingen n√•r den gjelder.
      2. historical_low/historical_high: dagens pris er n√∏yaktig lik
         laveste/h√∏yeste pris i DETTE vinduet (ikke n√∏dvendigvis
         all-time -- "relevant history period" i regel 6, konsekvent med
         at alle andre tall i modulen ogs√• er periode-relative) OG
         spennet i vinduet er MATERIELT (range_pct >=
         STATUS_STABLE_TOLERANCE_PCT). Uten materialitets-kravet ville et
         produkt som har svingt mellom 449 og 454 kr (~1,1 %) blitt
         flagget "h√∏yeste registrerte pris" i r√∏dt bare fordi dagens pris
         tilfeldigvis traff periodens (ubetydelige) tak -- funnet og
         rettet 2026-09-29 etter et konkret Kai-eksempel (Biofinity Toric
         6-pack). Et lite, ikke-meningsfullt spenn faller i stedet
         gjennom til "stable" via pct_change-sjekken under.
      3. down/up: prisendring fra vinduets F√òRSTE til SISTE observasjon,
         utenfor +-STATUS_STABLE_TOLERANCE_PCT.
      4. Ellers: stable (liten, ikke-meningsfull svingning)."""
    prices = [h["price"] for h in window]
    current = prices[-1]
    period_low, period_high = min(prices), max(prices)
    period_start = prices[0]

    flat_days = 0
    for p in reversed(prices):
        if p == current:
            flat_days += 1
        else:
            break

    pct_change = ((current - period_start) / period_start * 100) if period_start else 0.0
    range_pct = ((period_high - period_low) / period_low * 100) if period_low else 0.0
    material_range = range_pct >= STATUS_STABLE_TOLERANCE_PCT

    if flat_days >= STATUS_FLAT_MIN_DAYS:
        kind = "flat"
    elif material_range and current == period_low and period_low != period_high:
        kind = "historical_low"
    elif material_range and current == period_high and period_low != period_high:
        kind = "historical_high"
    elif pct_change <= -STATUS_STABLE_TOLERANCE_PCT:
        kind = "down"
    elif pct_change >= STATUS_STABLE_TOLERANCE_PCT:
        kind = "up"
    else:
        kind = "stable"

    return {
        "kind": kind,
        "current": current,
        "period_start": period_start,
        "period_low": period_low,
        "period_high": period_high,
        "pct_change": pct_change,
        "range_pct": range_pct,
        "flat_days": flat_days,
    }


def _price_intelligence_metrics(history: list[dict], period_days: int | None) -> dict | None:
    """Alle tallene ETT periode-panel trenger, for ETT produkts historikk.
    Returnerer None hvis vinduet er tomt (skal ikke skje i praksis siden
    perioden allerede er filtrert til kvalifiserte via
    _price_intelligence_eligible_periods(), men lar aldri en tom liste
    krasje videre ned i statistics.median())."""
    window = _price_intelligence_window(history, period_days)
    if not window:
        return None
    prices = [h["price"] for h in window]
    status = _price_intelligence_status(window)
    return {
        "window": window,
        "n_days": len(window),
        "current": prices[-1],
        "low": min(prices),
        "low_date": min(window, key=lambda h: h["price"])["date"],
        "high": max(prices),
        "high_date": max(window, key=lambda h: h["price"])["date"],
        "median": statistics.median(prices),
        "status": status,
    }


def _render_price_history_chart(history: list[dict], show_heading: bool = True, gradient_id: str = "priceHistoryFade") -> str:
    """SVG-linjegraf med fadet fylt areal under, over laveste PRODUKTPRIS
    (uten frakt) per dag, tegnet server-side -- ingen JS-bibliotek, fungerer
    uten at noe script kj√∏rer. Viser ingenting f√∏r vi faktisk har minst en
    ukes historikk (en 2-punkts graf fra dag 2 ser useri√∏s ut). Vokser med
    √©n dag per bygging inntil price_history.py sin MAX_DAYS-grense (365) er
    n√•dd. Byttet fra s√∏ylediagram til linje+areal 2026-08-21 etter
    bruker√∏nske (s√• for "klumpete" ut) om noe n√¶rmere Prisjakt sin egen
    prisgraf -- gradienten (priceHistoryFade) g√•r fra m√∏rkere oransje ved
    selve linjen til nesten gjennomsiktig ved grunnlinjen.

    'price' i history-radene er produktets pris ALENE (record_price() i
    generate_pages.py kalles med best["price_nok"], ikke best["total"] --
    endret 2026-08-21 etter bruker√∏nske om at frakt IKKE skal p√•virke
    grafen). Y-aksen har prisetiketter p√• VENSTRE side (brukerens uttrykte
    preferanse, i motsetning til h√∏yre-plasserte referanser). N√•r prisen
    har v√¶rt helt flat i hele perioden (min==max) ville en ekte skala
    kollapse til √©n linje helt i bunnen av grafen -- lager i stedet et
    symmetrisk kunstig spenn rundt prisen, slik at linjen lander midt i
    grafen med luft (og akseverdier) over og under, ikke pinnet til bunnen."""
    if len(history) < 7:
        return ""

    n = len(history)
    prices = [h["price"] for h in history]
    real_min, real_max = min(prices), max(prices)

    if real_min == real_max:
        # Flat pris hele perioden -- kunstig, symmetrisk spenn rundt
        # prisen (minst 10 kr, ellers 12 % av prisen) slik at s√∏ylene
        # lander midt i grafen i stedet for helt i bunnen.
        half_span = max(10.0, real_min * 0.12)
        min_price, max_price = real_min - half_span, real_min + half_span
    else:
        pad = (real_max - real_min) * 0.08
        min_price, max_price = real_min - pad, real_max + pad
    price_range = max_price - min_price

    width, height = 680, 180
    pad_left, pad_right, pad_top, pad_bottom = 48, 8, 14, 22
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    baseline_y = pad_top + plot_h

    def y_for(price: float) -> float:
        return pad_top + (1 - (price - min_price) / price_range) * plot_h

    def x_for(i: int) -> float:
        return pad_left + (i / (n - 1) if n > 1 else 0) * plot_w

    def short_date(date_str: str) -> str:
        _, month, day = date_str.split("-")
        return f"{day}.{month}"

    line_points = " ".join(f"{x_for(i):.1f},{y_for(h['price']):.1f}" for i, h in enumerate(history))
    area_path = (
        f"M{x_for(0):.1f},{baseline_y:.1f} "
        + " ".join(f"L{x_for(i):.1f},{y_for(h['price']):.1f}" for i, h in enumerate(history))
        + f" L{x_for(n - 1):.1f},{baseline_y:.1f} Z"
    )

    dots = []
    for i, h in enumerate(history):
        is_last = i == n - 1
        cls = "price-history-dot price-history-dot-last" if is_last else "price-history-dot"
        # 'store' finnes kun n√•r historikken er for ETT produkt -- serie-
        # siden sitt gjennomsnitt over flere produkter (se
        # _family_price_insight_data()) har ingen enkelt butikk √• vise.
        tooltip = f"{short_date(h['date'])}: {_fmt_kr(h['price'])} hos {escape(h['store'])}" if h.get('store') \
            else f"{short_date(h['date'])}: {_fmt_kr(h['price'])} (snitt for serien)"
        r = 3.2 if is_last else 2.2
        dots.append(f'<circle cx="{x_for(i):.1f}" cy="{y_for(h["price"]):.1f}" r="{r}" class="{cls}"><title>{tooltip}</title></circle>')
    dots_svg = "\n      ".join(dots)

    last = history[-1]
    last_label_y = max(pad_top + 9, y_for(last["price"]) - 8)
    last_label_anchor = "end" if n > 1 else "middle"

    axis_prices = [max_price, (min_price + max_price) / 2, min_price]
    axis_html = "\n      ".join(
        f'<line x1="{pad_left}" y1="{y_for(p):.1f}" x2="{width - pad_right}" y2="{y_for(p):.1f}" class="price-history-gridline" />\n'
        f'      <text x="{pad_left - 6}" y="{y_for(p) + 3:.1f}" text-anchor="end" class="price-history-axis-label">{escape(_fmt_kr(p))}</text>'
        for p in axis_prices
    )

    first = history[0]
    date_axis_html = (
        f'<text x="{pad_left}" y="{height - 6}" class="price-history-axis-label">{escape(short_date(first["date"]))}</text>\n'
        f'      <text x="{width - pad_right}" y="{height - 6}" text-anchor="end" class="price-history-axis-label">{escape(short_date(last["date"]))}</text>'
    )

    heading_html = f"""<h2>Prisutvikling</h2>
    <p class="price-history-summary">Laveste produktpris (uten frakt) siste {n} dager: {_fmt_kr(real_min)}.</p>""" if show_heading else ""
    return f"""<div class="price-history">
    {heading_html}
    <svg viewBox="0 0 {width} {height}" class="price-history-chart" role="img" aria-label="Prisutvikling siste {n} dager, fra {_fmt_kr(real_min)} til {_fmt_kr(real_max)}">
      <defs>
        <linearGradient id="{gradient_id}" x1="0" y1="{pad_top}" x2="0" y2="{baseline_y}" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#F0740F" stop-opacity="0.38" />
          <stop offset="100%" stop-color="#FB923C" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      {axis_html}
      <path d="{area_path}" class="price-history-area" fill="url(#{gradient_id})" />
      <polyline points="{line_points}" class="price-history-line" />
      {dots_svg}
      <text x="{x_for(n - 1):.1f}" y="{last_label_y:.1f}" text-anchor="{last_label_anchor}" class="price-history-current-label">{escape(_fmt_kr(last["price"]))}</text>
      {date_axis_html}
    </svg>
  </div>"""


# Chart Y-akse-gulv (logikk-/semantikk-runden 2026-09-29, regel 12-14, Kai:
# "the current chart auto-range can make tiny price movements look
# enormous... 449 -> 454 kr currently fills almost the full vertical plot
# range"). Et rent prosentvis padd av OBSERVERT spenn (den gamle logikken)
# gir et vilk√•rlig lite vindu n√•r spennet selv er lite -- en ekte ~1 %
# bevegelse fyller da hele grafh√∏yden og ser ut som et stup/rebound. Gulvet
# under sikrer et visningsspenn p√• MINST `_CHART_MIN_ABS_RANGE_NOK` kr
# ELLER `_CHART_MIN_PCT_RANGE` av referanseprisen (medianen), whichever er
# st√∏rst -- for et ~450 kr-produkt blir det ~50 % = ~225 kr, s√• en 449->454
# kr-bevegelse fortsatt er synlig, men ikke dominerer hele grafen. Gulvet
# er KUN en nedre grense (regel 14: "Never clip observations to satisfy
# the minimum-domain rule") -- et ekte, st√∏rre spenn (f.eks. 299->499 kr)
# vinner alltid over gulvet og klippes aldri.
_CHART_MIN_ABS_RANGE_NOK = 25.0
_CHART_MIN_PCT_RANGE = 0.50


def _price_intel_chart_domain(prices: list[float]) -> tuple[float, float]:
    """Y-aksens (min, max) for Price Intelligence-grafen -- se
    _CHART_MIN_ABS_RANGE_NOK/_CHART_MIN_PCT_RANGE over for begrunnelsen.
    Dekker ogs√• det tidligere spesialtilfellet "helt flat pris" (real_min
    == real_max) naturlig: da er observert spenn 0, og hele visningsspennet
    kommer fra gulvet alene, symmetrisk rundt prisen -- ingen egen
    if-gren n√∏dvendig lenger."""
    real_min, real_max = min(prices), max(prices)
    reference = statistics.median(prices)
    min_visual_range = max(_CHART_MIN_ABS_RANGE_NOK, reference * _CHART_MIN_PCT_RANGE)
    observed_range = real_max - real_min
    visual_range = max(observed_range, min_visual_range)
    extra = (visual_range - observed_range) / 2
    lo, hi = real_min - extra, real_max + extra
    pad = visual_range * 0.08
    return lo - visual_range * 0.20, hi + pad


def _nice_axis_ticks(lo: float, hi: float, target: int = 4) -> list[float]:
    """Runde Y-akse-verdier innenfor [lo, hi], ca. `target` stk. Steg velges
    fra en 1-2-5-serie slik at antallet havner mellom 3 og 5; faller tilbake
    til jevnt fordelte verdier hvis domenet er for smalt for runde tall."""
    span = hi - lo
    if span <= 0:
        return [lo]
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        first = math.ceil(lo / step) * step
        ticks = []
        v = first
        while v <= hi + 1e-9:
            ticks.append(float(v))
            v += step
        if 3 <= len(ticks) <= 5:
            return ticks
    return [lo + span * i / (target - 1) for i in range(target)]


def _render_price_intelligence_chart(window: list[dict], gradient_id: str, mobile: bool = False) -> str:
    """Strammere graf enn _render_price_history_chart() (KUN brukt av denne,
    IKKE av merke-/serie-sidenes _family_price_insight_data()-visning, som
    fortsatt bruker den gamle -- uendret der, se Kai sin regel om √• ikke
    r√∏re annet). Mindre vertikal luft, restrained rutenett (2 linjer i
    stedet for 3), ingen synlig prikk per dag -- kun siste punkt (regel 8:
    "no circle marker for every single daily observation... current/latest
    point may have a marker"). Usynlige, brede hover-m√•l (price-intel-hit)
    beholder ekte per-dag-tooltip (dato + pris) via SVG <title>, helt uten
    JS, akkurat som originalgrafen."""
    n = len(window)
    prices = [h["price"] for h in window]
    real_min, real_max = min(prices), max(prices)
    min_price, max_price = _price_intel_chart_domain(prices)
    price_range = max_price - min_price

    width, height = ((340, 205) if mobile else (680, 224))
    pad_left, pad_right, pad_top, pad_bottom = ((42, 8, 12, 24) if mobile else (46, 8, 12, 20))
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    baseline_y = pad_top + plot_h

    def y_for(price: float) -> float:
        return pad_top + (1 - (price - min_price) / price_range) * plot_h

    def x_for(i: int) -> float:
        return pad_left + (i / (n - 1) if n > 1 else 0) * plot_w

    def short_date(date_str: str) -> str:
        _, month, day = date_str.split("-")
        return f"{day}.{month}"

    line_points = " ".join(f"{x_for(i):.1f},{y_for(h['price']):.1f}" for i, h in enumerate(window))
    area_path = (
        f"M{x_for(0):.1f},{baseline_y:.1f} "
        + " ".join(f"L{x_for(i):.1f},{y_for(h['price']):.1f}" for i, h in enumerate(window))
        + f" L{x_for(n - 1):.1f},{baseline_y:.1f} Z"
    )
    hit_targets = "\n      ".join(
        f'<circle cx="{x_for(i):.1f}" cy="{y_for(h["price"]):.1f}" r="9" class="price-intel-hit">'
        f'<title>{escape(_format_no_date(h["date"], with_year=False))}: {_fmt_kr(h["price"])}{" hos " + escape(h["store"]) if h.get("store") else ""}</title></circle>'
        for i, h in enumerate(window)
    )
    last = window[-1]
    last_label_y = max(pad_top + 9, y_for(last["price"]) - 8)
    last_label_anchor = "end" if n > 1 else "middle"
    # ~4 "pene" Y-akse-nivaaer (runde 3, Kai: "two labels are too sparse...
    # keep the existing minimum visual-range logic") -- selve domenet
    # (min_price/max_price over) er UENDRET, kun etikettene/rutenettet
    # legges paa runde verdier INNENFOR det eksisterende domenet.
    axis_prices = _nice_axis_ticks(min_price, max_price)
    axis_html = "\n      ".join(
        f'<line x1="{pad_left}" y1="{y_for(p):.1f}" x2="{width - pad_right}" y2="{y_for(p):.1f}" class="price-history-gridline" />\n'
        f'      <text x="{pad_left - 6}" y="{y_for(p) + 3:.1f}" text-anchor="end" class="price-history-axis-label">{escape(_fmt_kr(p))}</text>'
        for p in axis_prices
    )
    # Flere dato-etiketter p√• desktop (v2-redesign, rapport #3: mockupen
    # viser ~7-9 datoer -- "31. aug ¬∑ 3. sep ¬∑ 6. sep ¬∑ ... ¬∑ 29. sep",
    # ikke bare f√∏rste/siste). Desktop rendrer opptil ni tikker. Mobilvarianten bruker samme data, men
    # en egen smal SVG-geometri med tre tikker (f√∏rste/midt/siste), slik at
    # grafen beholder lesbar h√∏yde og aksetekst p√• 375px uten horisontal scroll
    # (samme kompakte mobilvisning som f√∏r). Ca. √©n tikk per uke, med et
    # tak p√• 9 for √• unng√• overfylt akse p√• et helt √•rs historikk.
    if mobile and n > 1:
        tick_idx = sorted(set([0, (n - 1) // 2, n - 1]))
    else:
        tick_step = max(1, round((n - 1) / 7)) if n > 1 else 1
        tick_idx = sorted(set(range(0, n, tick_step))) if n > 1 else [0]
        # Siste regul√¶re tikk droppes hvis den ligger for n√¶r selve sluttpunktet.
        if n > 1 and tick_idx and (n - 1 - tick_idx[-1]) < tick_step / 2:
            tick_idx = tick_idx[:-1]
        if n > 1:
            tick_idx.append(n - 1)
        if len(tick_idx) > 9:
            tick_idx = sorted(set(tick_idx[::2]) | {0, n - 1})
    date_axis_html = "\n      ".join(
        f'<text x="{x_for(i):.1f}" y="{height - 5}" '
        f'text-anchor="{"start" if i == 0 else "end" if i == n - 1 else "middle"}" '
        f'class="price-history-axis-label price-history-axis-label-x{" price-history-axis-label-edge" if i in (0, n - 1) else ""}">'
        f'{escape(short_date(window[i]["date"]))}</text>'
        for i in tick_idx
    )
    return f"""<svg viewBox="0 0 {width} {height}" class="price-history-chart price-intel-chart {"price-intel-chart-mobile" if mobile else "price-intel-chart-desktop"}" role="img" aria-label="Prisutvikling, fra {_fmt_kr(real_min)} til {_fmt_kr(real_max)}">
      <defs>
        <linearGradient id="{gradient_id}" x1="0" y1="{pad_top}" x2="0" y2="{baseline_y}" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#F0740F" stop-opacity="0.32" />
          <stop offset="100%" stop-color="#FB923C" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      {axis_html}
      <path d="{area_path}" class="price-history-area" fill="url(#{gradient_id})" />
      <polyline points="{line_points}" class="price-history-line" />
      <circle cx="{x_for(n - 1):.1f}" cy="{y_for(last['price']):.1f}" r="3.2" class="price-history-dot price-history-dot-last" />
      {hit_targets}
      <text x="{x_for(n - 1):.1f}" y="{last_label_y:.1f}" text-anchor="{last_label_anchor}" class="price-history-current-label">{escape(_fmt_kr(last["price"]))}</text>
      {date_axis_html}
    </svg>"""


_PRICE_INTEL_STATUS_ICONS = {
    "flat": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 12h4l3-7 4 14 3-7h2"/></svg>',
    "stable": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 12h16"/></svg>',
    "down": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7l7 7 4-4 5 5M20 11v4h-4"/></svg>',
    "up": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 17l7-7 4 4 5-5M20 13V9h-4"/></svg>',
    "historical_low": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 4v12M6 16l-3-3M6 16l3-3M12 4v16M18 4v9M18 13l-3-3M18 13l3-3"/></svg>',
    "historical_high": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 20V8M6 8l-3 3M6 8l3 3M12 20V4M18 20v-9M18 11l-3 3M18 11l3 3"/></svg>',
}


def _vs_median_text(current: float, median: float, n_days: int) -> str | None:
    """"Dagens laveste pris er 479 kr, 5,5 % over 30-dagers medianen paa 454 kr."
    -- regnet dynamisk, aldri hardkodet. None naar median mangler/er 0 eller
    avviket avrundes til 0,0 %."""
    if not median:
        return None
    pct = (current - median) / median * 100
    if abs(pct) < 0.05:
        return None
    pct_txt = f"{abs(pct):.1f}".replace(".", ",")
    dir_txt = "over" if pct > 0 else "under"
    return f"Dagens laveste pris er {_fmt_kr(current)}, {pct_txt} % {dir_txt} {n_days}-dagers medianen p√• {_fmt_kr(median)}."


def _price_intelligence_status_text(status: dict, n_days: int, period_label: str, median: float | None = None) -> tuple[str, str, str]:
    """(css-modifikator, kort tittel, forklarende setning) for statuskortet
    -- ALLTID fra de deterministiske reglene i _price_intelligence_status(),
    ALDRI en generert kommentar (Kai, regel 5: "Do not use an LLM to invent
    price commentary").

    "historical_high" sin tittel er bevisst "H√∏yt prisniv√•", IKKE "H√∏yeste
    registrerte pris" (logikk-/semantikk-runden 2026-09-29, Kai: "these
    are NOT the same thing" -- historisk-serie-maks og dagens
    butikk-maks/-median i "Prisforskjell mellom butikkene"-kortet m√• ha
    synlig ulike etiketter, ellers leses de lett som samme tall). Siden
    statusen n√• ogs√• krever et MATERIELT spenn (se
    _price_intelligence_status()), utl√∏ses denne kun n√•r dagens pris
    faktisk er n√¶r en reell topp, ikke ved en 1 kr-svingning som
    tilfeldigvis traff periodens tak. "historical_low" beholder sin
    faktiske, ikke-selgende tittel "Laveste registrerte pris" (Kai:
    unng√• promoterende spr√•k som "Fantastisk pris" -- et rent faktautsagn
    er riktig her uansett)."""
    kind = status["kind"]
    current = status["current"]
    if kind == "flat":
        return "flat", "Stabil pris", f"Laveste produktpris har v√¶rt {_fmt_kr(current)} i {status['flat_days']} dager."
    vs_median = _vs_median_text(current, median, n_days) if median is not None else None
    if kind == "historical_low":
        return "low", "Laveste registrerte pris", vs_median or f"Dagens pris er den laveste vi har registrert i denne perioden ({period_label})."
    if kind == "historical_high":
        return "high", "H√∏yt prisniv√•", vs_median or f"Dagens pris er n√¶r det h√∏yeste niv√•et vi har registrert i denne perioden ({period_label})."
    if kind == "down":
        return "down", "Pris ned", f"Laveste produktpris har falt {abs(status['pct_change']):.0f} % de siste {n_days} dagene."
    if kind == "up":
        return "up", "Pris opp", f"Laveste produktpris er {abs(status['pct_change']):.0f} % h√∏yere enn for {n_days} dager siden."
    return "stable", "Stabil pris", f"Laveste produktpris har endret seg lite de siste {n_days} dagene."


def _price_intelligence_summary_text(product_name: str, metrics: dict, period_label: str, spread: dict | None = None) -> str:
    """"Kort oppsummert" -- fra strukturerte, deterministiske maler (Kai,
    regel 20: "generated from structured deterministic templates, not
    free-form AI"), aldri fritekst fra en spr√•kmodell. `spread` (fra
    _price_intelligence_merchant_spread(), CURRENT tilbud, IKKE historikk)
    er valgfri og legger til √©n ekstra, faktabasert setning n√•r den
    finnes -- matcher regel 20 sitt eget eksempel ("Det er 32 %
    prisforskjell mellom billigste og dyreste butikk akkurat n√•")."""
    status = metrics["status"]
    kind, n_days = status["kind"], metrics["n_days"]
    name = escape(product_name)
    spread_sentence = f" Det er {spread['spread_pct']} % prisforskjell mellom billigste og dyreste butikk akkurat n√•." if spread else ""
    if kind == "flat":
        flat_days = status["flat_days"]
        # VIKTIG: bruk flat_days (den faktiske, sammenhengende
        # uendret-strekken), IKKE hele periodens n_days -- prisen kan ha
        # v√¶rt flat de siste 7 dagene inni et 30-dagers vindu der den
        # FAKTISK endret seg tidligere i perioden. √Ö p√•st√• at dagens pris
        # er "b√•de laveste og h√∏yeste" for HELE perioden i et slikt
        # tilfelle ville v√¶rt en usann p√•stand (regel 2/3: aldri finn p√•/
        # feilrepresenter tall) -- selv om flat_days>=7 riktig utl√∏ser
        # "flat"-status, m√• selve SETNINGEN referere til det som faktisk
        # er flatt, ikke til en periode den ikke gjelder for.
        if flat_days >= n_days:
            return f"Prisen p√• {name} har v√¶rt stabil i {period_label.lower()}, med {_fmt_kr(status['current'])} som b√•de laveste og h√∏yeste registrerte pris i perioden.{spread_sentence}"
        return f"Prisen p√• {name} har v√¶rt uendret p√• {_fmt_kr(status['current'])} de siste {flat_days} dagene.{spread_sentence}"
    if kind in ("down", "up"):
        retning = "falt" if kind == "down" else "steget"
        lavere_hoyere = "lavere" if kind == "down" else "h√∏yere"
        return (f"Laveste registrerte pris har {retning} fra {_fmt_kr(status['period_start'])} til {_fmt_kr(status['current'])} de siste {n_days} dagene. "
                f"Dagens laveste pris er {abs(status['pct_change']):.0f} % {lavere_hoyere} enn ved starten av perioden.{spread_sentence}")
    return f"Laveste produktpris for {name} har ligget mellom {_fmt_kr(metrics['low'])} og {_fmt_kr(metrics['high'])} de siste {n_days} dagene.{spread_sentence}"


def _price_intelligence_merchant_spread(offers: list[dict]) -> dict | None:
    """"Prisforskjell mellom butikkene" (regel 10-12) -- CURRENT, levende
    tilbud (IKKE historikk), samme sammenligningsgrunnlag som Winner Card
    sin Savings Signal (_savings_eligible_offers(), qty=1, uten frakt --
    sidens standard prisbasis). Krever >=2 gyldige tilbud, ellers None (en
    "spredning" mellom kun ett tilbud er meningsl√∏s). spread_pct regnes
    EKSAKT som Savings Signal (regel 11: "Use the same conceptual basis as
    Winner Card Savings Signal") og rundes ALLTID nedover (regel 12:
    "Display whole percentages conservatively")."""
    pool = _savings_eligible_offers(offers, incl=False)
    if len(pool) < 2:
        return None
    prices = sorted(o["price_nok"] for o in pool)
    lowest, highest = prices[0], prices[-1]
    median = statistics.median(prices)
    spread_pct = math.floor((highest - lowest) / highest * 100) if highest else 0
    return {"lowest": lowest, "median": median, "highest": highest, "spread_pct": spread_pct, "n_offers": len(pool)}


def _price_intelligence_merchant_winners(history: list[dict], all_retailers: set[str] | None = None) -> dict | None:
    """"Prisvinner over tid" (regel 13-16) -- KUN fra faktisk lagrede
    `store`-felt i historikken, aldri utledet/gjettet.

    Uavgjort-regel (regel 14): price_history.json lagrer KUN vinner-
    butikken for dagen (record_price() kalles med samme reconcile_
    product() som avgj√∏r "laveste pris" p√• selve siden den dagen) --
    en eventuell uavgjort mellom to butikker med eksakt lik pris er
    derfor ALLEREDE avgjort deterministisk av reconcile_product() sin
    egen tie-break-n√∏kkel (_tie_break_key()/AFFILIATE_TIE_PRIORITY) i
    det √∏yeblikket dataen ble lagret. Denne modulen har ingen tilgang
    til de andre tilbudene for en historisk dag (kun vinneren ble
    lagret), og kan derfor verken gjenoppdage eller telle en historisk
    uavgjort-situasjon i etterkant -- den regner ganske enkelt den
    lagrede, allerede-tie-brutte vinneren for hver dag.

    `all_retailers` (visuelt reset-brief, 2026-09-29): butikker som selger
    produktet akkurat n√• (fra CURRENT `offers`) men som ALDRI har vunnet
    laveste pris i historikken f√•r en synlig "0 dager"-rad i stedet for √•
    v√¶re usynlige -- viser at de faktisk er sammenlignet, ikke bare
    frav√¶rende. Kun ekte, faktisk-selgende butikker legges til p√• denne
    m√•ten, aldri en oppdiktet liste."""
    wins: dict[str, int] = {}
    prev_winner: str | None = None
    changes = 0
    for entry in history:
        store = entry.get("store")
        if not store:
            continue
        wins[store] = wins.get(store, 0) + 1
        if prev_winner is not None and store != prev_winner:
            changes += 1
        prev_winner = store

    if not wins:
        return None
    if all_retailers:
        for r in all_retailers:
            wins.setdefault(r, 0)
    ranked = sorted(wins.items(), key=lambda kv: (-kv[1], kv[0]))
    n_days = len(history)
    top_count = ranked[0][1]
    # Uavgjort-spraak (runde 3): ALLE butikker med samme hoeyeste dagantall
    # nevnes -- aldri en av dem alene som "vinneren" naar to har like mange
    # dager. `ranked` er allerede sortert (-antall, navn), saa rekkefoelgen
    # er deterministisk.
    top_stores = [st for st, c in ranked if c == top_count]
    total_wins = sum(c for _, c in ranked)
    return {"ranked": ranked, "n_days": n_days, "changes": changes, "top_store": ranked[0][0], "top_count": top_count,
            "top_stores": top_stores, "total_wins": total_wins}


def _price_intelligence_recent_winner_count(history: list[dict], window_days: int = 90) -> dict | None:
    """"N butikker har v√¶rt prisvinner siste {vindu} dager" -- egen-data-
    stripen (v2-redesign, regel 16). Bevisst et ANNET, kortere vindu enn
    "Prisvinner over tid"-kortet (som alltid bruker HELE historikken) --
    et eget, kort vindu er mer relevant som en "hvor konkurranseutsatt er
    dette produktet nylig"-indikator. Vinduet er `min(window_days,
    len(history))`, ALDRI en p√•st√•tt lengde vi ikke faktisk har data for
    -- samme "ikke lov til √• hevde en periode vi ikke dekker"-prinsipp
    som resten av modulen (se `_price_intelligence_eligible_periods()`).
    Ingen `all_retailers` her (i motsetning til `_price_intelligence_
    merchant_winners()` sin bruk andre steder) -- denne tellingen skal
    KUN telle butikker som faktisk har vunnet minst √©n dag i vinduet, en
    0-dagers-butikk ville gitt en misvisende "flere konkurrenter" enn
    det som faktisk er observert der."""
    window = history[-window_days:] if len(history) >= window_days else history
    w = _price_intelligence_merchant_winners(window)
    if not w:
        return None
    return {"n_stores": len(w["ranked"]), "n_days": len(window)}


def _price_intelligence_quantity_table(offers: list[dict], unit_singular: str, unit_plural: str, qty_choices: tuple[int, ...] = (1, 2, 4, 6, 8, 10)) -> dict | None:
    """"Kj√∏per du flere esker?" (visuelt reset-brief punkt 9, 2026-09-29) --
    samme sammenligningsgrunnlag som resten av modulen: CURRENT tilbud
    (ikke historikk), uten frakt, kun in_stock/ikke-utg√•tte (se
    _savings_eligible_offers()) -- samme prisbasis som "Prisforskjell
    mellom butikkene", nettopp derfor sammenlignbare. For hvert antall:
    billigste butikk sin produktpris √ó antall, ALDRI utledet/gjettet, kun
    regnet direkte fra levende tilbud (samme prinsipp som qty-multi-raden
    i render_winner_widget(), men uten frakt siden resten av denne
    modulen konsekvent er uten-frakt-basert). Krever >=2 gyldige tilbud,
    samme terskel som resten av modulen.

    Skjules HELT (returnerer None) n√•r vinnerbutikken er den samme p√•
    tvers av ALLE viste antall (logikk-/semantikk-runden 2026-09-29,
    Kai: "Do not show the Quantity Intelligence card merely because
    quantity calculations exist... Intelligence should reveal
    something, not merely repeat arithmetic"). Uten volumrabatter i
    datamodellen (hver butikks pris er line√¶r -- pris √ó antall) er
    vinnerbytte den ENESTE reelle intelligensen tabellen kan avdekke;
    n√•r ingen bytte skjer er raden bare gangetabellen for den ene
    billigste butikken, og Kai ba eksplisitt om √• heller skjule kortet
    enn √• fylle det med generisk "billigste butikk kan endre seg"-tekst
    n√•r vi konkret VET at den ikke gj√∏r det i dette tilfellet."""
    pool = _savings_eligible_offers(offers, incl=False)
    if len(pool) < 2:
        return None
    rows = []
    first_store = None
    change_qty = None
    for qty in qty_choices:
        best_o = min(pool, key=lambda o: o["price_nok"] * qty)
        total = best_o["price_nok"] * qty
        rows.append({"qty": qty, "total": total, "store": best_o["retailer"]})
        if first_store is None:
            first_store = best_o["retailer"]
        elif change_qty is None and best_o["retailer"] != first_store:
            change_qty = qty
    if change_qty is None:
        return None
    return {"rows": rows, "change_qty": change_qty}


def render_price_intelligence(history: list[dict], product_name: str, unit_singular: str = "eske", unit_plural: str = "esker", offers: list[dict] | None = None, product_id: str | None = None) -> str:
    """Price Intelligence-modulen (Product Gold Standard v1, 2026-09-27).
    Erstatter den gamle, enkle "Prisutvikling"-grafen p√• produktsider
    (kontaktlinser, linsev√¶ske/√∏yedr√•per/Tilbeh√∏r og private label).

    VISUELT RESET (2026-09-29, Kai, med godkjent mockup-bilde): data-
    modellen/beregningene er UENDRET (Kai, regel 13: "Preserve everything
    functional") -- kun presentasjonen bygget om, fra en "intern
    analytics-dashboard"-f√∏lelse (mange tunge rektangul√¶re blokker,
    oversized chart, frikoblet header, oppsummering F√òR intelligensen
    den oppsummerer, for mye bl√•/gr√• flate) til √©n sammenhengende,
    hvit-dominert flate som f√∏lger mockupen tett:
      - Metrikk-stripen (5 kompakte felt: n√•/laveste/h√∏yeste/median/status)
        ligger n√• F√òR periodevelgeren, ikke lenger i samme blokk som grafen.
      - Selve grafen st√•r alene mellom periodevelger og intelligens-raden.
      - "Kort oppsummert" er flyttet til BUNNEN, som en smal, lysebl√•
        stripe -- konklusjonen kommer etter dataene, ikke f√∏r dem.
      - Ny tredje intelligens-kolonne: "Kj√∏per du flere esker?"
        (_price_intelligence_quantity_table()), samme CURRENT-tilbud-
        grunnlag som "Prisforskjell mellom butikkene".
      - "Prisvinner over tid" viser n√• ogs√• butikker som ALDRI har vunnet
        (0 dager) n√•r de fortsatt selger produktet i dag, for kontekst
        (se _price_intelligence_merchant_winners() sin all_retailers).

    Metrikk-stripen, grafen OG oppsummeringen er alle tre fortsatt
    periode-avhengige (bytter sammen n√•r en periode-fane klikkes), men
    ligger n√• i tre separate DOM-grupper (`.price-intel-metrics-strip`/
    `.price-intel-chart-panel`/`.price-intel-summary`, alle med samme
    `data-period`-attributt) i stedet for √©n delt blokk -- nettopp for √•
    kunne plassere dem tre ulike steder visuelt (topp/midt/bunn) mens de
    fortsatt oppdateres samlet. JS-en toggler n√• ALLE elementer med et
    `data-period`-attributt i ett steg (inkludert selve fane-knappene, som
    ogs√• har attributtet) i stedet for tre separate sp√∏rringer.

    LOGIKK-/SEMANTIKK-RUNDE (2026-09-29, Kai, "not another design brief
    ... primarily about making sure the intelligence is mathematically
    correct, semantically precise, not visually misleading, genuinely
    useful, deterministic, adaptive"): ren logikk-/tekst-polish, IKKE en
    ny visuell runde. Fem reelle funn rettet:
      1. `_price_intelligence_status()` klassifiserte tidligere
         historical_low/high kun p√• "current == period_low/high", uansett
         hvor LITE spennet i perioden var -- et produkt som svingte
         449<->454 kr (~1,1 %) ble flagget r√∏dt "h√∏yeste registrerte
         pris" bare fordi dagens pris traff periodens (ubetydelige) tak.
         Krever n√• et MATERIELT spenn (range_pct >=
         STATUS_STABLE_TOLERANCE_PCT) f√∏r historical_low/high i det hele
         tatt kan utl√∏ses -- ellers faller den naturlig gjennom til
         "stable" via samme toleranse som resten av statuslogikken.
      2. Historikk-metrikkenes "H√∏yeste registrerte pris" er n√• "H√∏yeste
         prisniv√•" (+ tooltip), og status-tittelen for historical_high er
         "H√∏yt prisniv√•" -- unng√•r at disse forveksles med "Prisforskjell
         mellom butikkene" sin egen, helt ANNERLEDES "h√∏yeste pris"
         (dagens butikk-maks, ikke historisk serie-maks). Den kortets rader
         omd√∏pt til "Laveste/H√∏yeste BUTIKKpris" av samme grunn.
      3. Laveste/h√∏yeste-dato viser n√• "F√∏rst registrert {dato}" i stedet
         for en bar dato -- unng√•r at en verdi som faktisk gjaldt i flere
         dager leses som om den kun eksisterte akkurat den ene datoen
         (Python sin min()/max() plukker allerede F√òRSTE forekomst
         kronologisk, kun teksten var upresis).
      4. `_render_price_intelligence_chart()` sitt Y-akse-spenn hadde
         ikke noe gulv -- et lite observert spenn (449-454 kr) ble padded
         med kun 10 % av SEG SELV, som fylte hele grafh√∏yden med en
         ubetydelig bevegelse. Ny `_price_intel_chart_domain()` sikrer et
         visningsspenn p√• minst `_CHART_MIN_ABS_RANGE_NOK` kr eller
         `_CHART_MIN_PCT_RANGE` av medianprisen -- ekte, st√∏rre spenn
         klippes aldri, gulvet er kun en nedre grense.
      5. "Kj√∏per du flere esker?" skjules n√• helt n√•r vinnerbutikken er
         den samme uansett antall (`_price_intelligence_quantity_table()`
         returnerer None) -- uten volumrabatter i datamodellen er
         vinnerbytte den eneste reelle intelligensen tabellen kan vise;
         ren gangetabell er ikke intelligens. `.price-intel-cards` sin
         desktop-CSS byttet fra fast `repeat(3,...)` til
         `repeat(auto-fit, minmax(220px,1fr))` slik at raden ikke f√•r en
         tom tredje kolonne n√•r kortet er skjult.
    Databehandlingen ellers -- tie-break ved lik butikkpris
    (`_tie_break_key()`/`AFFILIATE_TIE_PRIORITY`, allerede en dokumentert,
    deterministisk prioritetsliste, ALDRI array-/databaserekkef√∏lge), √©n
    rad per faktisk kalenderdag (`record_price()` overskriver, legger
    aldri til duplikater), og at manglende observasjonsdager aldri telles
    som uendret/null (de er ganske enkelt frav√¶rende fra historikk-listen)
    -- var allerede korrekt og er UENDRET denne runden.

    V2 -- "PREMIUM DATA PUBLICATION"-REDESIGN (2026-09-29, samme dag, Kai,
    godkjent mockup-bilde 58.webp som visuell fasit -- "the attached
    mockup wins" der den avviker fra den skriftlige spec-en, men den
    skriftlige spec-en er fortsatt fasit for datalogikk/eligibility/
    semantikk/tilgjengelighet). Ren presentasjon, INGEN
    beregning/eligibility-regel endret fra runden over. Fem strukturelle
    endringer:
      1. "Pris n√•" er n√• VISUELT DOMINERENDE (2,1rem, egen stor verdi),
         med de tre historikk-metrikkene ved siden av som en tynn,
         skilt-delt rad (`.price-intel-metrics-row`/`-col`,
         `border-left` som skillelinje) i stedet for like store
         grid-fliser -- "the numbers themselves should become the visual
         design", ikke pakket i gr√• bokser. Statuspillen er n√• en egen,
         atskilt komponent ved siden av (fortsatt tinted -- regel 5: "may
         remain a subtle tinted module because it represents a
         conclusion"), ikke en grid-rute blant r√•dataene.
      2. Grafen har f√•tt en smal "hylle" p√• stor desktop
         (`.price-intel-chart-shell{max-width:1100px}`, regel 8) -- IKKE
         en proporsjonal nedskalering av h√∏yden (regel 9), kun bredden
         begrenses og sentreres. En liten, IKKE-INTERAKTIV verkt√∏ylinje
         over grafen ("Laveste registrerte produktpris per dag" +
         "Viser laveste registrerte pris per dag") -- bevisst uten
         nedoverpil/dropdown-chevron, siden det ikke finnes noen reell
         alternativ dataserie √• velge mellom enn√•; √• tegne en falsk
         interaktiv kontroll ville v√¶rt misvisende UI.
      3. "31 %"-tallet i "Prisforskjell mellom butikkene" har f√•tt en
         egen, fremtredende callout-boks (`.price-intel-spread-callout`,
         regel 12: "make the proprietary spread metric prominent") i
         stedet for en rad blant de andre. 0-dagers-butikker i
         "Prisvinnere over tid" er beholdt synlige (Kai bekreftet
         eksplisitt tidligere samme uke at dette er √∏nsket -- "viser at
         de faktisk er sammenlignet"), men visuelt dempet
         (`.price-intel-winner-row-zero`, regel 13: "Do not let
         zero-value merchants create visual clutter" -- l√∏st med
         dempning, ikke fjerning, for √• ikke motsi den tidligere,
         eksplisitte avgj√∏relsen).
      4. Ny "egen-data"-stripe nederst (regel 16,
         `.price-intel-stat-strip`) -- fem redaksjonelle statistikker
         (dager siden prisendring, antall prisvinnerbytter, antall
         distinkte prisvinnere de siste `min(90, coverage_days)` dagene
         via ny `_price_intelligence_recent_winner_count()`,
         periodens prisvariasjon i prosent, periodens laveste pris) --
         KUN elementer der underliggende data faktisk finnes (adaptiv,
         regel 16: "Only display metrics that are meaningful and
         supported"). Periode-avhengig som resten av modulen (bytter med
         fanene), bortsett fra prisvinner-tallet som bruker sitt eget,
         faste 90-dagers-vindu (samme "ikke la et helt annet tall late
         som det f√∏lger den valgte fanen"-prinsipp som resten av siden).
      5. Bevisst IKKE implementert: mockupens "Sist oppdatert: ... kl.
         HH:MM"-klokkeslett. Samme l√¶rdom som allerede dokumentert for
         merke-siden samme dag ("Fase 16... et KLOKKESLETT-basert
         ferskhet-krav ble fjernet tidligere i prosjektet nettopp fordi
         det ble feil hver gang noen leste en statisk side senere enn
         byggetidspunktet") -- `price_history.json` lagrer uansett aldri
         klokkeslett, kun kalenderdato, s√• et p√•st√•tt klokkeslett m√•tte
         v√¶rt either oppdiktet eller byggetidspunktet (som blir usant f√•
         timer senere p√• en statisk side). Footeren viser i stedet
         `historikkens siste dato` via den samme "sist bekreftet
         {dato}"-konvensjonen resten av siden allerede bruker
         konsekvent. Samme grunn: mockupens "Oppdatert i dag"-merkelapp
         p√• Kort fortalt-boksen er IKKE implementert -- en relativ "i
         dag"-p√•stand p√• en statisk side blir usann i intervallet mellom
         to daglige bygg, akkurat samme feilklasse."""
    if len(history) < 7:
        return ""

    store_days = product_store_days(product_id, product_name)
    coverage_days = len(history)
    coverage_start = history[0]["date"]
    latest_date = history[-1]["date"]
    periods = _price_intelligence_eligible_periods(coverage_days)
    period_keys = {key for key, _, _ in periods}
    default_key = "30d" if "30d" in period_keys else "all"
    spread = _price_intelligence_merchant_spread(offers) if offers else None
    all_retailers = {o["retailer"] for o in offers} if offers else set()
    # Den gamle antallsinnsikten erstattes av historisk prisfrekvens.
    # Bidireksjonal "bytte"-pil, kun brukt av egen-data-stripen sitt
    # "N ganger har prisvinneren skiftet"-element -- ingen delt konstant
    # finnes fra f√∏r som passer semantisk (TROPHY_ICON_SVG er allerede
    # brukt til selve butikknavnet, ikke byttefrekvensen).
    _swap_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h13l-3-3M20 17H7l3 3"/></svg>'
    _chart_toolbar_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 21V10M12 21V4M19 21v-7"/></svg>'

    # Ett gjennoml√∏p over PRICE_INTELLIGENCE_PERIODS i FAST rekkef√∏lge (30
    # dager -> 90 dager -> 6 m√•neder -> 1 √•r -> All historikk), IKKE
    # kvalifiserte perioder f√∏rst med deaktiverte tacket p√• til slutt --
    # sistnevnte ga "All historikk" (alltid kvalifisert, siden den ikke har
    # noen dagsgrense) rett etter "30 dager" i stedet for sist, i strid med
    # mockupens eksplisitte rekkef√∏lge (visuelt reset-brief punkt 4).
    # Oppdaget 2026-09-29 ved √• faktisk sjekke et produkt med f√¶rre enn 90
    # dagers historikk i browser-panelet, ikke antatt.
    tabs, primary_strips, chart_panels, stat_strips, summary_strips, history_table_rows, winner_panels, frequency_panels = [], [], [], [], [], [], [], []
    n_enabled = 0
    for key, label, days in PRICE_INTELLIGENCE_PERIODS:
        if key not in period_keys:
            tabs.append(f'<button type="button" class="price-intel-period-tab" disabled title="Ikke nok historikk enn√•">{escape(label)}</button>')
            continue
        metrics = _price_intelligence_metrics(history, days)
        if metrics is None:
            continue
        n_enabled += 1
        active = key == default_key
        active_cls = " active" if active else ""
        tabs.append(f'<button type="button" class="price-intel-period-tab{active_cls}" data-period="{key}">{escape(label)}</button>')
        status = metrics["status"]
        status_mod, status_title, status_msg = _price_intelligence_status_text(status, metrics["n_days"], label, metrics["median"])
        summary_text = _price_intelligence_summary_text(product_name, metrics, label, spread)
        chart_svg = _render_price_intelligence_chart(metrics["window"], gradient_id=f"priceIntelFade-{key}")
        chart_svg_mobile = _render_price_intelligence_chart(metrics["window"], gradient_id=f"priceIntelFadeMobile-{key}", mobile=True)
        period_phrase = "i hele perioden" if key == "all" else f"siste {label}"
        period_winners = _price_intelligence_merchant_winners(metrics["window"], all_retailers)
        observed_prices = [row["price"] for row in metrics["window"]]
        reference_price = observed_prices[-1]
        lower_days = sum(p < reference_price for p in observed_prices)
        equal_days = sum(p == reference_price for p in observed_prices)
        higher_days = sum(p > reference_price for p in observed_prices)
        observed_days = len(observed_prices)
        frequency_segments = "".join(
            f'<span class="price-intel-frequency-{klass}" style="flex:{count}" aria-hidden="true"></span>'
            for count, klass in ((lower_days, "lower"), (equal_days, "equal"), (higher_days, "higher"))
            if count
        )
        frequency_legend = "".join(
            f'<span class="price-intel-frequency-label"><i class="price-intel-frequency-{klass}" aria-hidden="true"></i>{caption}: {count}</span>'
            for count, klass, caption in ((lower_days, "lower", "Lavere"), (equal_days, "equal", "Samme"), (higher_days, "higher", "H√∏yere"))
        )
        frequency_panels.append(f'''<div class="price-intel-card price-intel-frequency-panel{active_cls}" data-period="{key}">
          <div class="price-intel-card-head"><h3>Hvor vanlig er dagens pris?</h3><span class="price-intel-card-head-note">{escape(label)}</span></div>
          <div class="price-intel-frequency-number">{lower_days + equal_days} av {observed_days}</div>
          <p class="price-intel-frequency-description">Prisen har v√¶rt p√• siste registrerte niv√• eller lavere i {lower_days + equal_days} av {observed_days} observerte dager.</p>
          <div class="price-intel-frequency-bar" role="img" aria-label="Lavere: {lower_days} dager. Samme: {equal_days} dager. H√∏yere: {higher_days} dager.">{frequency_segments}</div>
          <div class="price-intel-frequency-legend">{frequency_legend}</div>
          <p class="price-intel-card-note">Laveste registrerte produktpris uten frakt. Manglende dager telles ikke.</p>
        </div>''')

        primary_strips.append(f'''<div class="price-intel-primary{active_cls}" data-period="{key}">
    <div class="price-intel-metrics-row">
      <div class="price-intel-metric-col price-intel-metric-current">
        <span class="price-intel-value-lg">{_fmt_kr(metrics["current"])}</span>
        <span class="price-intel-metric-label">Pris n√•</span>
        <span class="price-intel-current-dot"><i></i>Laveste pris akkurat n√•</span>
      </div>
      <div class="price-intel-metric-col">
        <span class="price-intel-value">{_fmt_kr(metrics["low"])}</span>
        <span class="price-intel-metric-label">Laveste pris<br>{period_phrase}</span>
        <span class="price-intel-metric-sublabel">F√∏rst registrert {_format_no_date(metrics["low_date"])}</span>
      </div>
      <div class="price-intel-metric-col" title="H√∏yeste registrerte verdi for den laveste tilgjengelige produktprisen i valgt periode.">
        <span class="price-intel-value">{_fmt_kr(metrics["high"])}</span>
        <span class="price-intel-metric-label">H√∏yeste prisniv√•<br>{period_phrase} <span class="price-intel-metric-info" aria-hidden="true">&#9432;</span></span>
        <span class="price-intel-metric-desc">H√∏yeste registrerte verdi for den laveste tilgjengelige produktprisen i perioden.</span>
      </div>
      <div class="price-intel-metric-col" title="Medianen av den laveste registrerte produktprisen for hver dag i perioden.">
        <span class="price-intel-value">{_fmt_kr(metrics["median"])}</span>
        <span class="price-intel-metric-label">{metrics["n_days"]}-dagers median <span class="price-intel-metric-info" aria-hidden="true">&#9432;</span></span>
        <span class="price-intel-metric-desc">Medianen av den laveste registrerte produktprisen for hver dag i perioden.</span>
      </div>
    </div>
    <div class="price-intel-status-pill price-intel-status-{status_mod}"><span class="price-intel-status-icon">{_PRICE_INTEL_STATUS_ICONS[status["kind"]]}</span><span><strong>{escape(status_title)}</strong>{escape(status_msg)}</span></div>
  </div>''')
        chart_panels.append(f'''<div class="price-intel-chart-panel{active_cls}" data-period="{key}">
    <div class="price-intel-chart-shell">
      <script type="application/json" class="store-chart-data">{json.dumps({"lowest": metrics["window"], "stores": {name: [row for row in rows if metrics["window"][0]["date"] <= row["date"] <= metrics["window"][-1]["date"]] for name, rows in store_days.items()}}, ensure_ascii=True).replace("<", "\\u003c")}</script>
      <div class="price-intel-chart-wrap">{chart_svg}{chart_svg_mobile}</div>
    </div>
  </div>''')
        # Egen-data-stripe (v2-redesign, regel 16) -- KUN elementer der
        # underliggende data faktisk finnes/er meningsfull, se
        # docstringen over for hvert elements datakilde.
        stat_parts = []
        if status["flat_days"] >= 1:
            n = status["flat_days"]
            stat_parts.append((CALENDAR_ICON_SVG, f'{n} {"dag" if n == 1 else "dager"}', 'siden siste prisendring'))
        if period_winners and period_winners["changes"] > 0:
            n = period_winners["changes"]
            stat_parts.append((_swap_icon, f'{n} {"gang" if n == 1 else "ganger"}', f'har prisvinneren skiftet {period_phrase}'))
        if period_winners:
            n = len([1 for _store, count in period_winners["ranked"] if count > 0])
            if n > 0:
                stat_parts.append((TROPHY_ICON_SVG, f'{n} {"butikk" if n == 1 else "butikker"}', f'har v√¶rt prisvinner {period_phrase}'))
        if metrics["low"] != metrics["high"]:
            range_pct_display = f'{status["range_pct"]:.1f}'.replace('.', ',')
            stat_parts.append((_PRICE_INTEL_STATUS_ICONS["up"], f'{range_pct_display} %', f'prisspenn {period_phrase}'))
        stat_parts.append((TAG_ICON_SVG, _fmt_kr(metrics["low"]), 'laveste pris vi har registrert' if key == "all" else 'laveste pris i perioden'))
        stat_html = "".join(
            f'<div class="price-intel-stat">{icon}<div><strong>{escape(val)}</strong><span>{escape(desc)}</span></div></div>'
            for icon, val, desc in stat_parts
        )
        # Kort fortalt + egen-data-stripen er ETT sammenhengende
        # konklusjonsmodul (runde 3, Kai) -- en blaa boks med oppsummeringen
        # oeverst og de fem statistikkene i en hvit stripe under, i stedet
        # for to urelaterte blokker.
        summary_strips.append(f'''<div class="price-intel-conclusion{active_cls}" data-period="{key}">
    <div class="price-intel-summary"><span class="price-intel-summary-icon" aria-hidden="true">&#128161;</span><span><strong>Kort fortalt</strong>{summary_text}</span></div>
    <div class="price-intel-stat-strip">{stat_html}</div>
  </div>''')

        # Prisvinnere f√∏lger valgt periode. Dagens butikkspredning er
        # fortsatt et √∏yeblikksbilde og st√•r fast, mens historisk
        # vinnerrangering/andel/bytter bytter sammen med graf og metrikker.
        if period_winners and len(period_winners["ranked"]) >= 1:
            max_count = max(1, period_winners["ranked"][0][1])
            positive_winners = [(store, count) for store, count in period_winners["ranked"] if count > 0]
            zero_winner_count = sum(1 for _store, count in period_winners["ranked"] if count == 0)
            winner_rows = "".join(
                f'<div class="price-intel-winner-row"><span class="price-intel-winner-store">{escape(store)}</span>'
                f'<span class="price-intel-winner-bar"><span style="width:{round(count / max_count * 100)}%"></span></span>'
                f'<span class="price-intel-winner-days">{count} {"dag" if count == 1 else "dager"} &middot; {round(count / period_winners["total_wins"] * 100)} %</span></div>'
                for store, count in positive_winners
            )
            zero_note = (
                f'<p class="price-intel-zero-note">{zero_winner_count} {"annen butikk" if zero_winner_count == 1 else "andre butikker"} er ogs√• sammenlignet, men har ikke v√¶rt billigst i perioden.</p>'
                if zero_winner_count else ""
            )
            changes_sentence = (
                f' Prisvinneren har endret seg {period_winners["changes"]} {"gang" if period_winners["changes"] == 1 else "ganger"} i perioden.'
                if period_winners["changes"] > 0 else ""
            )
            tops = period_winners["top_stores"]
            if len(tops) == 1:
                top_sentence = f'{escape(tops[0])} har hatt lavest registrert produktpris i {period_winners["top_count"]} av {period_winners["n_days"]} observerte dager i perioden.'
            else:
                names = ", ".join(escape(t) for t in tops[:-1]) + " og " + escape(tops[-1])
                both = "begge" if len(tops) == 2 else "alle"
                top_sentence = f'{names} har {both} hatt lavest registrert produktpris i {period_winners["top_count"]} av {period_winners["n_days"]} observerte dager i perioden.'
            winner_panels.append(f'''<div class="price-intel-card price-intel-winners-panel{active_cls}" data-period="{key}">
      <div class="price-intel-card-head"><h3 class="price-intel-card-h-winner">{TROPHY_ICON_SVG}Prisvinnere over tid</h3><span class="price-intel-card-head-note">{escape(label)}</span></div>
      <div class="price-intel-winners-list">{winner_rows}</div>
      {zero_note}
      <p class="price-intel-card-note">{top_sentence}{changes_sentence}</p>
    </div>''')

        # Gold Standard: server-rendret "Prishistorikk i tall". Dette er
        # samme canonical beregning som driver graf/metrikker, ikke en
        # separat SEO-kopi. Dermed kan bruker, crawler og senere Chillout
        # Specialist lese periodedata uten √• m√•tte tolke SVG eller klikke
        # faner. Kun perioder med faktisk nok historikk rendres.
        price_changes = sum(
            1 for prev, cur in zip(metrics["window"], metrics["window"][1:])
            if prev["price"] != cur["price"]
        )
        winner_changes = period_winners["changes"] if period_winners else 0
        distinct_winners = (
            len([1 for _store, count in period_winners["ranked"] if count > 0])
            if period_winners else 0
        )
        range_pct_text = f'{status["range_pct"]:.1f} %'.replace('.', ',')
        history_table_rows.append(
            f'<tr><th scope="row">{escape(label)}</th>'
            f'<td>{_fmt_kr(metrics["low"])}</td>'
            f'<td>{_fmt_kr(metrics["high"])}</td>'
            f'<td>{_fmt_kr(metrics["median"])}</td>'
            f'<td>{escape(range_pct_text)}</td>'
            f'<td>{price_changes}</td>'
            f'<td>{winner_changes}</td>'
            f'<td>{distinct_winners}</td></tr>'
        )

    if n_enabled == 0:
        return ""

    script_html = """<script>
(function () {
  var wrap = document.currentScript.closest('.price-intel');
  if (!wrap) return;
  var historyDetails = wrap.querySelector('.price-intel-history-details');
  if (historyDetails && window.matchMedia && window.matchMedia('(max-width: 859px)').matches) {
    historyDetails.removeAttribute('open');
  }
  wrap.querySelectorAll('.price-intel-period-tab[data-period]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var period = tab.getAttribute('data-period');
      wrap.querySelectorAll('[data-period]').forEach(function (el) {
        el.classList.toggle('active', el.getAttribute('data-period') === period);
      });
    });
  });
})();
</script>"""

    # "Prisforskjell mellom butikkene" (regel 10-12) -- CURRENT tilbud, ikke
    # periode-avhengig, vises derfor KUN √©n gang. Skjules helt hvis <2
    # gyldige tilbud (samme grunnlag som Savings Signal). Radetikettene er
    # bevisst "Laveste/H√∏yeste BUTIKKpris" (ikke bare "Laveste/H√∏yeste
    # pris") -- logikk-/semantikk-runden 2026-09-29, Kai: dette er
    # DAGENS spredning mellom butikker, et helt annet tall enn
    # historikk-metrikkenes "Laveste registrerte pris"/"H√∏yeste
    # prisniv√•" over. Uten den presiseringen kan f.eks. 454 kr (dagens
    # laveste butikkpris) og 666 kr (dagens h√∏yeste butikkpris) lett
    # forveksles med historiske min/maks-tall lenger opp i modulen.
    # "31 %"-tallet er n√• en egen, fremtredende callout-boks (v2-redesign
    # regel 12), ikke bare en rad blant de andre.
    spread_card = ""
    if spread:
        spread_card = f'''<div class="price-intel-card">
    <div class="price-intel-card-head"><h3 class="price-intel-card-h-spread"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 21V10M12 21V4M19 21v-7"/></svg>Prisforskjell mellom butikkene</h3></div>
    <div class="price-intel-card-row"><span>Laveste butikkpris</span><strong>{_fmt_kr(spread["lowest"])}</strong></div>
    <div class="price-intel-card-row"><span>Medianpris</span><strong>{_fmt_kr(spread["median"])}</strong></div>
    <div class="price-intel-card-row"><span>H√∏yeste butikkpris</span><strong>{_fmt_kr(spread["highest"])}</strong></div>
    <div class="price-intel-spread-callout"><strong>{spread["spread_pct"]} %</strong><span>Forskjell mellom laveste og h√∏yeste butikkpris</span></div>
    <p class="price-intel-card-note"><span aria-hidden="true">&#9432;</span> Basert p√• priser uten frakt, for 1 {escape(unit_singular)}.</p>
  </div>'''

    winner_panels_html = "".join(winner_panels)
    frequency_panels_html = "".join(frequency_panels)
    cards_html = f'<div class="price-intel-cards">{spread_card}{winner_panels_html}{frequency_panels_html}</div>'

    return f'''<div class="price-intel">
  <div class="price-intel-head">
    <div class="price-intel-head-text">
      <p class="price-intel-eyebrow">Prisintelligens</p>
      <h2>Prisutvikling</h2>
      <p>F√∏lg utviklingen i laveste registrerte produktpris, sammenlign butikkene og utforsk prishistorikken.</p>
    </div>
    <div class="price-intel-coverage">{CALENDAR_ICON_SVG}<span>Vi har fulgt prisen siden<br><strong>{_format_no_date(coverage_start)}</strong><span class="price-intel-coverage-days">{coverage_days} dager med data</span></span></div>
  </div>
  {"".join(primary_strips)}
  <div class="store-chart-controls">
    <details class="store-chart-picker" hidden><summary>Velg butikk</summary><div class="store-chart-options"></div></details>
    <div class="store-chart-periods"><div class="price-intel-period-tabs" role="tablist">{"".join(tabs)}</div><p class="store-chart-caption">Laveste registrerte produktpris per dag</p></div>
  </div>
  <div class="store-chart-selected" hidden></div>
  {"".join(chart_panels)}
  {cards_html}
  {"".join(summary_strips)}
  <section class="price-intel-history-data" aria-labelledby="price-intel-history-title">
    <div class="price-intel-section-head">
      <div>
        <p class="price-intel-section-kicker">Historiske n√∏kkeltall</p>
        <h3 id="price-intel-history-title">Prishistorikk i tall</h3>
        <p>Samme prisdata som i grafen, publisert som lesbare n√∏kkeltall for periodene vi har nok historikk til √• beregne.</p>
      </div>
    </div>
    <details class="price-intel-history-details" open>
      <summary>Se historiske n√∏kkeltall</summary>
      <div class="price-intel-history-table-wrap">
        <table class="price-intel-history-table">
          <thead><tr><th>Periode</th><th>Laveste</th><th>H√∏yeste prisniv√•</th><th>Median</th><th>Prisspenn</th><th>Prisendringer</th><th>Vinnerbytter</th><th>Butikker billigst</th></tr></thead>
          <tbody>{"".join(history_table_rows)}</tbody>
        </table>
      </div>
    </details>
  </section>
  <div class="price-intel-footer">
    <span class="price-intel-footer-source"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_SHIELD_ICON}</svg>Alle priser hentes daglig fra norske nettbutikker. <a href="/slik-sammenligner-vi-priser/">Les mer om hvordan vi samler inn priser &rarr;</a></span>
    <span>Prisdata sist bekreftet: {_format_no_date(latest_date)}</span>
  </div>
  {script_html}
  <script src="/static/store-history-chart.js?v={_STORE_CHART_VERSION}" defer></script>
</div>'''


def _family_price_insight_data(rows: list[dict], price_history: dict) -> dict[int, dict]:
    """Sl√•r sammen prishistorikken for ALLE medlemmer i familien med SAMME
    pakningsst√∏rrelse til √©n gjennomsnittlig serie-pris per dag -- en type
    innsikt ingen enkelt produktside kan gi alene (snittet av flere faktiske
    produkter, ikke √©n linses pris). Kai sitt eksplisitte √∏nske 2026-09-27:
    "prisinnsikt skal gjelde gjennomsnitt for serien, ikke 1 produkt".
    Grupperes per pack_size siden ulike pakningsst√∏rrelser ikke er
    sammenlignbare i kroner (232 kr for 30 stk vs. 599 kr for 90 stk er ikke
    et "snitt" som gir mening). Kun dager der MINST √âTT medlem faktisk har en
    registrert pris tas med -- aldri en oppdiktet verdi for en dag ingen av
    dem ble sjekket, og antall bidragsytende produkter kan derfor variere
    litt dag for dag etter hvert som nye produkter f√•r egen prishistorikk."""
    by_pack: dict[int, list[str]] = {}
    for r in rows:
        if r["pack_size"]:
            by_pack.setdefault(r["pack_size"], []).append(r["product"]["id"])

    result: dict[int, dict] = {}
    for pack_size, product_ids in by_pack.items():
        per_date: dict[str, list[float]] = {}
        for pid in product_ids:
            for entry in price_history.get(pid, []):
                per_date.setdefault(entry["date"], []).append(entry["price"])
        merged = [{"date": d, "price": sum(vals) / len(vals)} for d, vals in sorted(per_date.items())]
        result[pack_size] = {"history": merged, "n_products": len(product_ids)}
    return result


def render_family_price_insight(family_name: str, insight_by_pack: dict[int, dict], scope_label: str = "i serien", heading: str | None = None) -> str:
    """Prisinnsikt for HELE serien -- se _family_price_insight_data() for
    hvordan tallene regnes ut. √ân fane per pakningsst√∏rrelse familien faktisk
    har (kun 30-pack her: √©n fane, ingen faner √• bytte mellom -- un√∏dvendig
    UI for noe som uansett ikke kan velges bort). Begge/alle paneler ligger
    FERDIGBYGGET i DOM-en samtidig (ren CSS/JS-visning, ingen klientside-
    utregning) -- bytte av fane er derfor √∏yeblikkelig og fungerer uten JS
    ogs√• (viser bare det f√∏rste panelet i s√• fall). Samme 7-dagers terskel
    som selve grafen (_render_price_history_chart) -- en pakningsst√∏rrelse
    med for lite historikk enn√• utelates helt i stedet for √• vise et
    up√•litelig snitt. scope_label: gjenbrukt av render_brand_page() 2026-09-27
    for et merke-niv√• snitt p√• tvers av HELE merket, ikke bare √©n serie --
    "i serien" er da feil (villedende presist), default beholdt uendret for
    den opprinnelige serie-siden-bruken."""
    pack_sizes = sorted(k for k, v in insight_by_pack.items() if len(v["history"]) >= 7)
    if not pack_sizes:
        return ""

    tabs, panels = [], []
    for i, pack_size in enumerate(pack_sizes):
        data = insight_by_pack[pack_size]
        history = data["history"]
        prices = [h["price"] for h in history]
        n = len(history)
        current = prices[-1]
        avg = sum(prices) / n
        lo, hi = min(prices), max(prices)
        pct = round((current - avg) / avg * 100) if avg else 0
        trend_class = "insight-down" if pct < 0 else ("insight-up" if pct > 0 else "insight-flat")
        trend_sign = "" if pct == 0 else ("+" if pct > 0 else "")
        trend_arrow = "‚Üì" if pct < 0 else ("‚Üë" if pct > 0 else "‚Üí")
        chart_html = _render_price_history_chart(history, show_heading=False, gradient_id=f"priceHistoryFade-{pack_size}")
        active = " active" if i == 0 else ""
        tabs.append(f'<button type="button" class="insight-tab{active}" data-pack="{pack_size}">{pack_size} linser</button>')
        panels.append(f'''<div class="price-insight-panel{active}" data-pack="{pack_size}">
    <div class="price-insight-now">
      <div class="price-insight-current">{_fmt_kr(current)}</div>
      <div class="price-insight-label">Snitt laveste pris n√• &middot; {data["n_products"]} varianter {scope_label}</div>
      <div class="price-insight-trend {trend_class}"><span aria-hidden="true">{trend_arrow}</span> {trend_sign}{pct} % <span class="price-insight-trend-note">vs. {n} dagers snitt</span></div>
      <div class="price-insight-tiles">
        <div class="price-insight-tile"><strong>{_fmt_kr(lo)}</strong><span>{n} dagers laveste</span></div>
        <div class="price-insight-tile"><strong>{_fmt_kr(avg)}</strong><span>{n} dagers snitt</span></div>
        <div class="price-insight-tile"><strong>{_fmt_kr(hi)}</strong><span>{n} dagers h√∏yeste</span></div>
      </div>
    </div>
    <div class="price-insight-chart">{chart_html}</div>
  </div>''')

    tabs_html = f'<div class="insight-tabs" role="tablist">{"".join(tabs)}</div>' if len(pack_sizes) > 1 else ""
    script_html = "" if len(pack_sizes) <= 1 else """<script>
(function () {
  var wrap = document.currentScript.closest('.price-insight');
  if (!wrap) return;
  wrap.querySelectorAll('.insight-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var pack = tab.getAttribute('data-pack');
      wrap.querySelectorAll('.insight-tab').forEach(function (t) { t.classList.toggle('active', t === tab); });
      wrap.querySelectorAll('.price-insight-panel').forEach(function (p) { p.classList.toggle('active', p.getAttribute('data-pack') === pack); });
    });
  });
})();
</script>"""
    return f'''<div class="price-insight">
  <div class="price-insight-head">
    <h2>{escape(heading) if heading else f"Prisinnsikt for {escape(family_name)}"}</h2>
    {tabs_html}
  </div>
  {"".join(panels)}
  {script_html}
</div>'''


def _kz_accordion(summary: str, inner_html: str, kz_id: str | None = None) -> str:
    """Generisk kollapset seksjon for produktsidens "kunnskapssone"
    (Product Mobile Gold Standard v1, 2026-09-27) -- ekte, server-rendret
    <details>/<summary> (samme Google-verifiserte m√∏nster som
    render_winner_widget() sin "Pris ved flere esker"-rad), ikke
    CSS-skjult tekst. Returnerer "" hvis inner_html er tom, slik at
    kallerne kan sende inn betinget bygget HTML uten egne if-sjekker."""
    if not inner_html:
        return ""
    id_attr = f' id="{escape(kz_id)}"' if kz_id else ""
    return f'''<details class="kz-accordion"{id_attr}>
    <summary>{escape(summary)}<svg class="kz-accordion-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="kz-accordion-body">{inner_html}</div>
  </details>'''


def render_product_page(product: dict, categories: dict, products_by_id: dict | None = None, price_history: list[dict] | None = None, now: datetime | None = None, aliases: list[dict] | None = None, family: dict | None = None, clickouts: dict | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    image_url = _product_image(product)

    pack_size_callout = ""
    parsed = _pack_size_from_id(product["id"])
    siblings: list[tuple[int, dict]] = []
    if parsed and best and products_by_id:
        _, pack_size = parsed
        siblings = find_pack_siblings(product, products_by_id)
        this_per_lens = best["total"] / pack_size
        callout_rows: list[str] = []
        for sibling_pack_size, sibling in siblings:
            sibling_offers = reconcile_product(sibling["offers"], now)
            sibling_eligible = [o for o in sibling_offers if o["in_stock"]]
            sibling_best = min(sibling_eligible, key=lambda o: o["total"], default=None)
            if not sibling_best:
                continue
            sibling_per_lens = sibling_best["total"] / sibling_pack_size
            sibling_href = f'/kontaktlinser/{sibling["brand_slug"]}/{sibling["slug"]}/'
            diff_pct = abs(sibling_per_lens - this_per_lens) / this_per_lens * 100
            if diff_pct < 1:
                comparison = "omtrent samme pris per linse"
            else:
                retning = "billigere" if sibling_per_lens < this_per_lens else "dyrere"
                comparison = f"{diff_pct:.0f} % {retning} per linse"
            per_lens_str = f"{sibling_per_lens:.2f}".replace(".", ",") + " kr/linse"
            callout_rows.append(f"""<a class="pack-size-callout" href="{escape(sibling_href)}">
  <div class="pack-size-callout-text">
    Finnes ogs√• i <strong>{sibling_pack_size}-pakning</strong> ‚Äî {per_lens_str} ({comparison})
  </div>
  <div class="pack-size-callout-arrow">‚Üí</div>
</a>""")
        # En rad per andre pakningsst√∏rrelse, stigende. Med ett s√∏sken er
        # markup identisk med f√∏r.
        pack_size_callout = "\n".join(callout_rows)

    # Alternativ stavem√•te (kun familier med eksplisitt "alt_name" i
    # product_families.json, i dag bare Dailies Total1): √©n n√∏ytral setning i
    # "Om"-teksten, aldri i tittel, H1, URL, canonical eller schema.
    alt_name_html = ""
    alt_name = (family or {}).get("alt_name")
    if alt_name and family["name"] in product["name"]:
        base_name = re.sub(r"\s+\d+-pack$", "", product["name"])
        alt_name_html = f"<p>Produktnavnet kan ogs√• skrives {escape(base_name.replace(family['name'], alt_name, 1))}.</p>"

    family_callout = ""
    if family:
        family_callout = f"""<a class="pack-size-callout" href="/serie/{escape(family["slug"])}/">
  <div class="pack-size-callout-text">
    Se hele <strong>{escape(family["name"])}</strong>-serien ‚Äî sammenlign sf√¶risk, torisk og andre varianter
  </div>
  <div class="pack-size-callout-arrow">‚Üí</div>
</a>"""

    thumb = _img_tag(image_url, product["name"], loading="eager") if image_url \
        else escape(product["brand_label"][:2].upper())

    ship_chip_html = _ship_chip_boxed_html("ship-chip") if offers else ""
    offers_block, ex_best = render_price_list(offers, product["name"], product["id"], clickouts, show_ship_chip=False, qty_unit_label="1 eske", collapse_after=10, product_ship_chip_html=ship_chip_html)

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser p√• <strong>{escape(product["name"])}</strong> hos norske nettbutikker. Fra <strong>{_fmt_kr(ex_best["price_nok"])}</strong> hos {escape(ex_best["retailer"])} (ekskl. frakt). Kontaktlinser.no er en uavhengig sammenligningstjeneste - sl√• p√• ¬´Pris inkludert frakt¬ª under for √• se totalprisen med frakt. Priser sist bekreftet {_verified_tag(_newest_checked(offers))}.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi f√∏lger prisen p√• <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne linsen akkurat n√•. Prisene oppdateres daglig.</p>
</section>"""

    winner_html, qty_html, qty_multi_html = render_winner_widget(ex_best, offers, product["name"], product_id=product["id"], clickouts=clickouts, qty_multi_inline=False, qty_choices=(1, 2, 4, 6, 8, 10), include_custom_pill=False)
    badges_html = _render_product_badges(product.get("specs", []))
    hero_facts_html = _hero_facts_html(product.get("specs", []), parsed[1] if parsed else None)

    in_stock_offers = [o for o in offers if o["in_stock"]]
    # "price" er produktprisen alene, ikke fraktinkludert totalsum -- ellers
    # ser vi kunstig dyrere ut enn konkurrenter i Googles eget SERP-utdrag,
    # som typisk viser ex-frakt-priser. Selve fraktkostnaden ligger separat i
    # shippingDetails i stedet, slik schema.org faktisk er ment √• brukes.
    # V√•r EGEN "Lavest pris"-rangering (reconcile()) er up√•virket av dette og
    # forblir totalpris-basert -- kun denne strukturerte dataen endres.
    schema_offers = ",\n      ".join(f'''{{
        "@type": "Offer",
        "seller": {{"@type": "Organization", "name": "{escape(o["retailer"])}"}},
        "price": {o["price_nok"]},
        "priceCurrency": "NOK",
        "url": "{_json_str(o["url"])}",
        "availability": "https://schema.org/InStock",
        "shippingDetails": {{
          "@type": "OfferShippingDetails",
          "shippingRate": {{"@type": "MonetaryAmount", "value": {o["shipping_nok"]}, "currency": "NOK"}},
          "shippingDestination": {{"@type": "DefinedRegion", "addressCountry": "NO"}}
        }}
      }}''' for o in in_stock_offers)

    low_price = min((o["price_nok"] for o in in_stock_offers), default=0)
    high_price = max((o["price_nok"] for o in in_stock_offers), default=0)

    specs = product.get("specs", [])
    schema_props = ""
    if specs:
        schema_props = ',\n  "additionalProperty": [' + ",\n    ".join(
            f'{{"@type": "PropertyValue", "name": "{escape(label)}", "value": "{escape(value)}"}}'
            for label, value in specs
        ) + "]"

    long_description = product.get("long_description", product["description"])
    # Meta-beskrivelsen skal lede med selve sammenligningen (pris/butikker),
    # ikke produktets materialbeskrivelse -- et ekte Google-treff (vist av
    # brukeren 2026-08-28) viste linsemateriale/UV-filter-tekst i stedet for
    # pris, mens et annet treff for en annen linse fikk Google til √•
    # generere en pris-ledet snippet selv (fra ai_summary-avsnittet lenger
    # ned p√• siden) -- ustabilt, siden det er opp til Google om den
    # omskriver. Gir Google et sterkt, riktig signal direkte i meta-taggen
    # i stedet for √• stole p√• at den finner riktig avsnitt selv.
    #
    # Antall forhandlere (len(product["offers"])) er BEVISST fjernet fra
    # denne setningen (2026-09-05, brukeren oppdaget et ekte Google-treff
    # som sa "fra 2 norske nettbutikker" for en produktvariant med lav
    # dekning) -- tallet varierer sterkt per pakningsst√∏rrelse/variant og
    # kan se svakt ut i SERP for et produkt som tilfeldigvis f√∏res av f√•
    # forhandlere, mens et sitewide-tall ville v√¶rt misvisende for et
    # produkt som ikke f√∏res av alle. Selve verdien i setningen (pris +
    # hvilken butikk) krever ikke tallet i det hele tatt.
    meta_description = (
        f'Vi sammenligner priser p√• {product["name"]} hos norske nettbutikker. '
        f'Laveste pris akkurat n√• er {_fmt_kr(ex_best["price_nok"])} hos {ex_best["retailer"]}.'
    ) if ex_best else long_description[:155]

    manufacturer_slug = BRAND_TO_MANUFACTURER.get(product["brand_slug"])
    manufacturer_link_html = (
        f'<p style="margin-top:8px;"><a href="/produsent/{manufacturer_slug}/" style="font-size:0.9rem;color:var(--muted);">'
        f'Produsert av {escape(MANUFACTURERS[manufacturer_slug]["name"])} ‚Üí</a></p>'
        if manufacturer_slug else ""
    )

    offers_schema = ""
    if in_stock_offers:
        offers_schema = f''',
  "offers": {{
    "@type": "AggregateOffer",
    "priceCurrency": "NOK",
    "lowPrice": {low_price},
    "highPrice": {high_price},
    "offerCount": {len(in_stock_offers)},
    "offers": [{schema_offers}]
  }}'''

    # dateModified = ferskeste checked_at blant tilbudene som faktisk er p√•
    # lager -- et konkret, sant "sist bekreftet"-tidspunkt, ikke en gjettet
    # eller statisk dato. Freshness-signal for AI-siteringstillit.
    date_modified = max((o["checked_at"] for o in in_stock_offers), default=None)
    product_href = f'{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/'
    # BreadcrumbList manglet her (fantes allerede p√• kategori-/merke-/
    # produsent-sider, men ikke p√• selve produktsiden -- funnet 2026-09-05;
    # samme mangel ble senere samme dag funnet p√• private label-sidene ogs√•,
    # se render_private_label_page). Speiler n√∏yaktig den synlige
    # br√∏dsmulen under (Hjem > kategori > merke > produktnavn).
    breadcrumb_schema = f'''{{"@type": "BreadcrumbList", "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "{_json_str(categories[product["category_slug"]]["label"])}", "item": "{BASE_URL}/kontaktlinser/{product["category_slug"]}/"}},
    {{"@type": "ListItem", "position": 3, "name": "{_json_str(product["brand_label"])}", "item": "{BASE_URL}/merke/{product["brand_slug"]}/"}},
    {{"@type": "ListItem", "position": 4, "name": "{_json_str(product["name"])}", "item": "{product_href}"}}
  ]}}'''
    product_schema = f'''{{
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}}{f', "image": "{escape(_abs_url(image_url))}"' if image_url else ""}{f', "dateModified": "{date_modified}"' if date_modified else ""}{offers_schema}{schema_props}
}}'''
    schema_json = f'''{{
  "@context": "https://schema.org",
  "@graph": [{breadcrumb_schema}, {product_schema}]
}}'''
    schema_json_html = f'<script type="application/ld+json">{schema_json}</script>' if in_stock_offers else ""

    specs_html = ""
    if specs:
        rows = "\n".join(
            f'<tr><th scope="row" class="spec-label">{escape(label)}</th><td class="spec-value">{escape(value)}</td></tr>'
            for label, value in specs
        )
        # Ekte <table>-markup (ikke div-grid) -- lettere for AI-crawlere √•
        # trekke ut spesifikasjonene som strukturerte data, se GEO-revisjonen.
        specs_html = f"""<div class="specs">
    <h2>Spesifikasjoner</h2>
    <table class="specs-table"><tbody>{rows}</tbody></table>
    <p class="specs-note">Veiledende tall, satt sammen fra forhandlernes egne spesifikasjoner og produsentens produktinformasjon. Bekreft alltid mot din synsresept og pakningsvedlegget f√∏r kj√∏p.</p>
  </div>"""
    specs_html += manufacturer_link_html

    price_history_html = render_price_intelligence(price_history or [], product["name"], offers=offers, product_id=product["id"])

    aliases_html = ""
    if aliases:
        alias_rows = "\n    ".join(
            f'<li><a href="/private-label/{escape(a["slug"])}/">{escape(a["name"])}</a> hos {escape(a["chain"])}</li>'
            for a in aliases
        )
        n = len(aliases)
        chains_word = "kjede" if n == 1 else "kjeder"
        aliases_html = f"""<div class="aliases-note">
    <strong>Selges ogs√• under andre navn:</strong> {escape(product["name"])} pakkes om og selges under eget varenavn hos {n} optiker{chains_word}:
    <ul>
    {alias_rows}
    </ul>
    <a href="/private-label/">Om optikerkjedenes egne merker ‚Üí</a>
  </div>"""

    # Dynamisk FAQ bygget fra SAMME beregnede data som resten av siden
    # (best/in_stock_offers/parsed) -- aldri hardkodet forhandler/pris, og
    # aldri flere sp√∏rsm√•l enn det finnes et p√•litelig svar p√• (f.eks.
    # "hvor lenge varer den" krever KJENT pakningsst√∏rrelse OG at det
    # faktisk er en dagslinse -- ellers utelates sp√∏rsm√•let helt i stedet
    # for √• gjette).
    product_faq: list[dict] = []
    if best:
        cheapest_product_offer = min(in_stock_offers, key=lambda o: o["price_nok"])
        if cheapest_product_offer["retailer"] != best["retailer"]:
            billigst_svar = (
                f'{cheapest_product_offer["retailer"]} har lavest produktpris: {_fmt_kr(cheapest_product_offer["price_nok"])} uten frakt. '
                f'Regner du med frakt, blir {best["retailer"]} billigst: {_fmt_kr(best["total"])} totalt inkludert frakt. '
                f'Velger du flere esker, kan en annen butikk bli billigst, siden fraktgrenser varierer mellom butikkene.'
            )
        else:
            billigst_svar = (
                f'{best["retailer"]} har lavest pris, b√•de uten og med frakt: {_fmt_kr(best["price_nok"])} uten frakt '
                f'({_fmt_kr(best["total"])} inkludert frakt).'
            )
        product_faq.append({"question": f'Hvor er {product["name"]} billigst?', "answer": billigst_svar})

        laveste_produktpris = min(o["price_nok"] for o in in_stock_offers)
        product_faq.append({
            "question": f'Hva koster {product["name"]}?',
            "answer": f'Laveste produktpris p√• {product["name"]} er {_fmt_kr(laveste_produktpris)} uten frakt akkurat n√•. '
                      f'Totalprisen avhenger av hvilken butikk du velger og fraktkostnaden der.',
        })

    if parsed:
        _, pack_size = parsed
        product_faq.append({
            "question": f'Hvor mange linser er det i {product["name"]}?',
            "answer": f'√ân pakke inneholder {pack_size} linser.',
        })
        if _is_daily_lens(product):
            days_two_eyes = pack_size // 2
            product_faq.append({
                "question": f'Hvor lenge varer {product["name"]}?',
                "answer": f'Til ett √∏ye varer pakningen i {pack_size} dager (√©n linse per dag). Bruker du linser med samme '
                          f'styrke p√• begge √∏yne fra samme pakning, varer den {days_two_eyes} dager. Har du ulik styrke p√• '
                          f'hvert √∏ye, trenger du vanligvis en egen pakning per √∏ye.',
            })

    product_faq.append({
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk daglig. Vi viser butikkens produktpris "
                  "uten frakt og beregner totalpris basert p√• frakt og antallet esker du velger.",
    })

    product_faq_html, product_faq_schema = _render_faq_accordion_block(product_faq, f'Vanlige sp√∏rsm√•l om {product["name"]}')

    # "Relatert til X" -- kun ekte, entydige sider (s√∏sken-pakninger, merke,
    # kategori, produsent), aldri en generisk lenkevegg av urelaterte merker
    # (se V1-spesifikasjonens Section 11/37 -- doorway-lenker er bevisst unng√•tt).
    related_items = []
    for sibling_pack_size, sibling in sorted(siblings, key=lambda s: s[0]):
        related_items.append((
            f'/kontaktlinser/{sibling["brand_slug"]}/{sibling["slug"]}/',
            f'{sibling["name"]}',
        ))
    related_items.append((f'/merke/{product["brand_slug"]}/', f'Alle {product["brand_label"]}-kontaktlinser'))
    related_items.append((f'/kontaktlinser/{product["category_slug"]}/', f'Alle {categories[product["category_slug"]]["label"].lower()}'))
    if manufacturer_slug:
        related_items.append((f'/produsent/{manufacturer_slug}/', f'{MANUFACTURERS[manufacturer_slug]["name"]}-kontaktlinser'))
    related_html = ""
    if related_items:
        related_links = "\n    ".join(f'<li><a href="{escape(href)}">{escape(label)}</a></li>' for href, label in related_items)
        related_html = f"""<div class="related">
    <h2>Relatert til {escape(product["name"])}</h2>
    <ul>
    {related_links}
    </ul>
  </div>"""

    disclosure_html = PRICE_DISCLOSURE_HTML
    methodology_html = METHODOLOGY_HTML

    # Kunnskapssonen (Product Mobile Gold Standard v1, 2026-09-27): samme
    # ekte innhold som f√∏r, bare gruppert bak <details>-accordions i stedet
    # for alltid synlig -- se _kz_accordion()-docstringen. Ingen ny data,
    # ingen fjernet informasjon, kun omorganisert under "kunnskaps-bruddet".
    kz_specs_html = _kz_accordion("Produktspesifikasjoner", specs_html)
    kz_faq_html = _kz_accordion(f'Vanlige sp√∏rsm√•l om {product["name"]}', product_faq_html)
    kz_sources_html = _kz_accordion("Kilder og dokumentasjon", methodology_html + related_html)

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} ¬ª Sammenlign og f√• billigste pris</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/">
{_og_meta(f'{product["name"]} ¬ª Sammenlign og f√• billigste pris', meta_description, f'{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/', image_url)}
{FONT_LINKS}
{schema_json_html}
{product_faq_schema}
<style>{SHARED_STYLE}
.hero-card {{ background: white; border: 1px solid var(--border); border-radius: 20px; padding: 20px; margin-bottom: 20px; }}
.hero-card .hero-copy h1 {{ font-size: 1.6rem; }}
.hero-subtitle {{ margin: 2px 0 0; font-size: 0.92rem; color: var(--muted); font-weight: 500; }}
/* "Pris ved flere esker" st√•r n√• som et eget, frittst√•ende element under
   prislista i stedet for inni .qty-box (Kai, 2026-09-27: "Teksten Pris
   ved flere esker, flyttes ogs√• ned under priser") -- delt .qty-multi-CSS
   forutsetter fortsatt at den er siste barn INNI en hvit .qty-box-kortboks
   (fortsatt sant p√• linsev√¶ske-/private label-sidene, ur√∏rt der), s√• den
   f√•r en egen kort-innpakning KUN her via >-selektoren (direkte barn av
   .wrap-product treffer bare denne siden sin plassering). */
.wrap-product > .qty-multi {{ background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }}
.hero-main {{ display: flex; flex-direction: column; gap: 16px; }}
/* Product Mobile Gold Standard v1 (2026-09-27): produktbilde (~2/3) og
   Winner Card (~1/3) side ved side p√• mobil -- bildet skal klart v√¶re
   hovedpersonen visuelt, IKKE to like kolonner. .hero-media-row er en ren
   mobil-gruppering; p√• >=1280px blir den display:contents slik at bildet
   og vinnerkortet igjen er DIREKTE grid-barn av .hero-main og treffes av
   akkurat samme grid-column/-row-regler som f√∏r (uendret desktop-layout,
   se Kai 2026-09-27: "du gj√∏r f√∏rst mobil produktsiden ferdig n√•,
   korrekt? ikke desktop?"). */
/* align-items: flex-start (IKKE stretch) -- med stretch presset bildet seg
   til vinnerkortets (tallere) naturlige h√∏yde i stedet for √• faktisk f√∏lge
   sin egen aspect-ratio, siden stretch og aspect-ratio konkurrerer om
   kryss-aksen i en flex-rad. flex-start lar hvert element ha sin egen,
   naturlige h√∏yde -- bildet blir kortere (matcher det faktiske,
   liggende eskebildet), og vinnerkortet trenger ikke lenger strekke seg
   opp til en un√∏dvendig h√∏yde bare fordi det st√•r ved siden av et
   kvadratisk bilde. */
.hero-media-row {{ display: flex; align-items: flex-start; gap: 12px; }}
.hero-media-row .hero-product-image {{ flex: 2 1 0; min-width: 0; margin: 0; }}
.hero-media-row .winner-band {{ flex: 1 1 0; min-width: 0; margin: 0; }}
@media (min-width: 640px) {{ .hero-media-row {{ gap: 16px; }} }}
/* Vinnerkortet i den smale ~1/3-kolonnen: reduser padding/skrift/logo/
   spar-sirkel F√òR vi vurderer stacking (Kai sin brief, punkt 25) --
   scoped til (max-width:1279px) slik at desktopkortet IKKE ber√∏res (viktig:
   .hero-media-row blir display:contents p√• >=1280px, men selektoren under
   ville uansett fortsatt truffet desktop-kortet via DOM-etterkommerskap
   uten denne media-grensen, siden display:contents ikke fjerner elementet
   fra treet). */
@media (max-width: 1279px) {{
  /* Kai, etter f√∏rste runde: "Laveste Pris mer firkantet" + "veldig mye
     plass rundt selve bilde". Begge kommer av samme rot-√•rsak -- den delte
     .hero-product-image-regelen (brukt over hele siden der et STORT,
     kvadratisk bilde er riktig) tvang en 1:1-firkant ogs√• her, i en langt
     smalere ~2/3-kolonne, og .hero-media-row sin align-items:stretch
     presset i tillegg bildet opp til vinnerkortets (tallere) naturlige
     h√∏yde -- aspect-ratio og stretch konkurrerer om kryss-aksen i en
     flex-rad, og stretch vant. Fikset i to steg: (1) .hero-media-row
     bruker n√• align-items:flex-start (se der) slik at bildet faktisk f√•r
     lov til √• f√∏lge sin egen, kortere aspect-ratio i stedet for √• strekkes
     opp, og (2) vinnerkortet komprimert videre her (tettere linjer, ett
     linje-slag i stedet for to for "Laveste pris"/"for 1 eske") for √•
     n√¶rme seg Kais egen designspec sitt h√∏yde-m√•l (140-160px) selv i en
     smalere ~1/3-kolonne enn spec-bildet opprinnelig viste. */
  .hero-media-row .hero-product-image {{ aspect-ratio: 4 / 3; }}
  .product-stage .hero-media-row .winner-band-cta {{ padding: 10px 8px; gap: 6px; align-self: flex-start; }}
  .hero-media-row .winner-top {{ align-items: center; }}
  .hero-media-row .winner-band-cta .label-group {{ flex-direction: row; align-items: baseline; gap: 4px; flex-wrap: wrap; }}
  .hero-media-row .winner-band-cta .label {{ font-size: 0.68rem; letter-spacing: 0.01em; }}
  .hero-media-row .winner-sub {{ font-size: 0.64rem; margin-top: 0; }}
  .hero-media-row .winner-band-cta .retailer {{ margin-top: 6px !important; }}
  .hero-media-row .winner-band-cta .retailer-logo {{ height: 18px; max-width: 88px; }}
  .hero-media-row .winner-price-line {{ font-size: 0.68rem; line-height: 1.3; }}
  .hero-media-row .winner-savings {{ width: 34px; height: 34px; }}
  .hero-media-row .winner-savings-label {{ font-size: 0.4rem; }}
  .hero-media-row .winner-savings-pct {{ font-size: 0.62rem; }}
  /* white-space:normal (ikke nowrap) -- "G√• til butikk" klippet p√• de
     aller smaleste skjermene (320px) selv etter gjentatt skrift-
     nedskalering; √• presse teksten enda mindre gikk ut over lesbarheten.
     Lar heller CTA-en bryte til to linjer der det trengs enn √• vise
     avkuttet tekst. */
  .hero-media-row .winner-btn {{ font-size: 0.68rem; padding: 8px 4px; gap: 3px; margin-top: 2px; white-space: normal; text-align: center; line-height: 1.25; }}
}}
/* Kicker (merke/serie over H1) + kompakt faktarad ("Dagslinse ¬∑ 30 linser
   ¬∑ Hilafilcon B ¬∑ BC 8,6") -- Product Desktop Gold Standard v1,
   2026-09-27, punkt 3+8. Skjult som standard (mobil-Gold-Standard-en
   fjernet bevisst kickeren over H1 tidligere samme dag, se commit
   9657bfb1d -- IKKE gjeninnf√∏r den der), vises kun >=1280px der Kai
   bekreftet at det er plass ("Her kan ogs√• Soflens eller produsent
   vises, da det er plass til det"). */
.hero-kicker, .hero-facts {{ display: none; }}
/* 2026-10-11: Behold det godkjente bilde/vinnerkort-oppsettet under
   1280px. Tre minimumskolonner (1060px) + gap (64px) + padding/border
   (74px) trenger 1198px inne i sidens wrapper for √• unng√• overflyt. */
/* Product Stage: EKTE tre-kolonners CSS Grid p√• desktop -- bilde |
   produktidentitet+kontroller | Winner Card, ALLE i samme vertikale
   arbeidsflate. Revidert 2026-09-27, samme dag, etter at Kai konkret
   avviste forrige fors√∏k (title+fakta over hele bredden, bilde og
   Winner Card som separate "√∏yer" under): "Han har beholdt strukturen
   fra den gamle heroen og bare restylet elementene... Det er ikke
   designet v√•rt." Referansen krever bilde+identitet/kontroller+
   Winner Card side om side i √âN rad -- eksakte kolonneproporsjoner og
   m√•l-m√•l (bildeh√∏yde, pillest√∏rrelser, typografi) er Kais egne, ikke
   estimert.

   .qty-box er FORTSATT en egen, separat DOM-node (s√∏sken av .hero-card
   inni .product-stage, se render_product_page()) -- IKKE flyttet i
   treet, av samme grunn som forrige runde: mobil skal forbli 100%
   uendret. I stedet "flates" .hero-card/.hero-main/.hero-media-row ut
   med display:contents p√• desktop, slik at DERES barn (.hero-copy,
   .hero-product-image, .winner-band) blir direkte grid-barn av
   .product-stage -- sammen med .qty-box, som allerede var en direkte
   .product-stage-barn. display:contents er KUN satt inni denne
   media-queryen, s√• mobilens DOM-boksmodell er fullstendig up√•virket
   under 1280px. */
@media (min-width: 1280px) {{
  .product-stage {{
    display: grid;
    grid-template-columns: minmax(360px, 0.95fr) minmax(420px, 1.10fr) minmax(280px, 0.72fr);
    grid-template-areas: "image identity price" "image controls price";
    column-gap: 32px;
    row-gap: 40px;
    background: white; border: 1px solid var(--border); border-radius: 20px;
    padding: 32px 36px;
  }}
  .product-stage .hero-card, .product-stage .hero-main, .product-stage .hero-media-row {{ display: contents; }}
  .product-stage .hero-kicker {{ display: block; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 0 0 6px; }}
  .product-stage .hero-copy {{ grid-area: identity; align-self: start; }}
  .product-stage .hero-copy h1 {{ font-size: 2rem; line-height: 1.18; margin: 0; }}
  .product-stage .hero-subtitle {{ font-size: 1.2rem; font-weight: 400; margin: 8px 0 0; }}
  .hero-facts {{ display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin: 24px 0 0; font-size: 0.92rem; color: var(--muted); }}
  .hero-fact-sep {{ color: var(--border); }}
  .product-stage .hero-product-image {{ grid-area: image; align-self: center; width: 100%; height: 320px; max-width: none; margin: 0; }}
  .product-stage > .qty-box {{ grid-area: controls; align-self: start; border: none; background: transparent; padding: 0; margin: 0; }}
  /* Kompakte, faste pillest√∏rrelser (56-64x44-48px) -- IKKE den
     elastiske repeat(6, 1fr)-grid-en fra mobil, som ville strukket
     pillene til √• fylle hele den n√• mye smalere midtkolonnen. Valgt
     tilstand er blek mint/gr√∏nn kant/m√∏rk tekst her, IKKE den bl√•
     gradienten fra mobil-pillene (Kai, punkt 6: "Remove the bright
     blue gradient selected state on desktop"). Frakt-vippebryteren
     bodde tidligere i denne raden ogs√• (`.qty-box-row`) -- flyttet til
     prislisteheaderen p√• B√ÖDE mobil og desktop n√• (se
     render_price_list()), s√• raden inneholder kun pillene igjen. */
  .product-stage .qty-pills {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .product-stage .qty-pill {{ width: 60px; height: 46px; padding: 0; box-shadow: none; }}
  .product-stage .qty-pill.is-active {{ background: var(--mint-tint); border-color: var(--mint); color: var(--ink); box-shadow: none; }}
  .product-stage .qty-pill.is-active span {{ color: var(--muted); }}
  .product-stage .winner-band {{ grid-area: price; align-self: center; margin: 0; width: 100%; background: white; flex-direction: column; align-items: center; text-align: center; gap: 10px; position: relative; padding: 24px 18px 18px; }}
  .product-stage .winner-left {{ flex-direction: column; align-items: center; gap: 0; }}
  .product-stage .winner-trophy {{ position: absolute; top: -22px; left: 50%; transform: translateX(-50%); box-shadow: 0 2px 6px rgba(11, 37, 69, 0.15); }}
  .product-stage .winner-band .label {{ margin-top: 0; }}
  .product-stage .winner-band .retailer {{ justify-content: center; margin-top: 10px; }}
  .product-stage .winner-band .winner-shipping {{ margin-top: 10px; }}
  .product-stage .winner-price-group {{ text-align: center; }}
  .product-stage .price-pill.is-winner {{ display: inline-block; background: none; color: var(--mint); padding: 0; font-size: 1.7rem; line-height: 1; }}
  .product-stage .winner-price-note {{ margin-top: 7px; line-height: 1; }}
  .product-stage .winner-cta {{ display: inline-flex; align-items: center; justify-content: center; gap: 6px; margin-top: 10px; background: var(--mint); color: white; font-weight: 700; font-size: 0.85rem; padding: 11px 22px; border-radius: 999px; }}
}}
/* wrap-product er delt med linsev√¶ske-/private label-produktsider (som
   fortsatt bruker den gamle, smalere hero-layouten) -- utvider den KUN her,
   siden det er denne nye, bredere hero-en som faktisk trenger albuerommet.
   Kommer etter {{SHARED_STYLE}} i selve <style>-taggen, s√• denne regelen
   vinner kaskaden uten !important (samme spesifisitet, senere i kilden). */
@media (min-width: 1024px) {{ .wrap-product {{ max-width: 1280px; }} }}
.hero-badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0; }}
.hero-badge {{ display: inline-flex; align-items: center; gap: 6px; background: white; border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px 6px 10px; font-size: 0.8rem; font-weight: 600; color: var(--blue); }}
.hero-badge svg {{ width: 15px; height: 15px; flex-shrink: 0; }}
/* "Kunnskaps-bruddet" (Product Mobile Gold Standard v1, 2026-09-27) --
   den visuelle overgangen mellom kj√∏pssonen (alt over) og kunnskapssonen
   (alt under): flankerende linjer rundt en liten, diskret etikett. */
.kz-break {{ display: flex; align-items: center; gap: 12px; margin: 36px 0 20px; color: var(--muted); font-size: 0.76rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
.kz-break::before, .kz-break::after {{ content: ""; flex: 1; height: 1px; background: var(--border); }}
.kz {{ display: flex; flex-direction: column; gap: 4px; }}
.kz > h2 {{ font-family: 'Mulish', sans-serif; font-size: 1.1rem; margin: 0 0 4px; }}
.kz-accordion {{ background: white; border: 1px solid var(--border); border-radius: 14px; padding: 4px 18px; margin: 10px 0; }}
.kz-accordion summary {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; list-style: none; padding: 16px 0; font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 0.98rem; color: var(--ink); }}
.kz-accordion summary::-webkit-details-marker {{ display: none; }}
.kz-accordion-chevron {{ flex-shrink: 0; width: 18px; height: 18px; color: var(--muted); transition: transform 0.15s; }}
.kz-accordion[open] .kz-accordion-chevron {{ transform: rotate(180deg); }}
.kz-accordion-body {{ padding-bottom: 16px; }}
.kz-accordion-body .specs, .kz-accordion-body .methodology, .kz-accordion-body .related {{ margin-top: 0; }}
.kz-accordion-body .specs h2, .kz-accordion-body .methodology h2, .kz-accordion-body .related h2 {{ display: none; }}
.kz-accordion-body .faq-section .faq-accordion-item:first-child {{ border-top: none; }}
/* _faq_accordion_item() (per-sp√∏rsm√•l-accordionen inni "Vanlige
   sp√∏rsm√•l"-boksen) er gjenbrukt fra brand-/serie-siden, men reglene som
   faktisk ST√òRRELSESBEGRENSER den (.faq-chevron m.fl.) l√• kun i DE
   funksjonenes egne <style>-blokker -- aldri kopiert hit. Uten dem har
   <svg class="faq-chevron"> ingen bredde/h√∏yde-regel i det hele tatt, og
   rendres i sin fulle, ubegrensede viewBox-st√∏rrelse (>100px, oppdaget av
   Kai p√• en skjermdump). Kopiert inn her, identisk med kildene. */
.faq-accordion-item {{ border-top: 1px solid var(--border); }}
.faq-accordion-item:last-child {{ border-bottom: 1px solid var(--border); }}
.faq-accordion-item summary {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; list-style: none; padding: 13px 0; font-weight: 600; font-size: 0.92rem; color: var(--ink); }}
.faq-accordion-item summary::-webkit-details-marker {{ display: none; }}
.faq-chevron {{ flex-shrink: 0; width: 16px; height: 16px; color: var(--muted); transition: transform 0.15s; }}
.faq-accordion-item[open] .faq-chevron {{ transform: rotate(180deg); }}
.faq-accordion-item p {{ margin: 0 0 15px; color: var(--muted); font-size: 0.88rem; line-height: 1.55; }}
.hero-card .product-ai-summary {{ background: var(--blue-tint); border-left: none; border-radius: 10px; margin: 16px 0 0; }}
.aliases-note {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin: 20px 0; font-size: 0.88rem; line-height: 1.6; }}
.aliases-note ul {{ margin: 8px 0; padding-left: 20px; }}
.aliases-note a {{ color: var(--blue); text-decoration: none; font-weight: 600; }}
.aliases-note a:hover {{ text-decoration: underline; }}
.specs {{ margin-top: 32px; }}
.specs h2 {{ font-family: 'Mulish', sans-serif; font-size: 1.05rem; margin: 0 0 12px; }}
.specs-table {{ width: 100%; background: white; border: 1px solid var(--border); border-radius: 12px; border-collapse: collapse; overflow: hidden; font-size: 0.88rem; }}
.specs-table tr {{ border-bottom: 1px solid var(--border); }}
.specs-table tr:last-child {{ border-bottom: none; }}
.specs-table th, .specs-table td {{ padding: 10px 16px; }}
.spec-label {{ text-align: left; font-weight: 400; color: var(--muted); }}
.spec-value {{ text-align: right; font-family: 'Mulish', sans-serif; }}
.specs-note {{ font-size: 0.76rem; color: var(--muted); margin-top: 10px; line-height: 1.5; }}
.pack-size-callout {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; margin: 16px 0; text-decoration: none; color: inherit; font-size: 0.85rem; }}
.pack-size-callout:hover {{ border-color: var(--blue); }}
.pack-size-callout-arrow {{ color: var(--blue); font-size: 1.1rem; flex-shrink: 0; }}
/* Fyller hele kortbredden helt fra minste mobilskjerm (kvadratisk via
   aspect-ratio) -- tidligere var mobil l√•st til en fast 200x200px-boks som
   etterlot mye tomt rom i et bredere kort (fant og fikset 2026-08-30, se
   brukerens tilbakemelding om at bildene p√• mobil produktsider var for
   sm√•). P√• desktop (>=1280px, Product Desktop Gold Standard v1,
   2026-09-27) overstyrer `.hero-main .hero-product-image` denne med en
   egen 4:3-aspect-ratio (se der) -- bildet spenner IKKE lenger to
   grid-rader (den midtre tekstkolonnen som tidligere ga bildet en tekst-
   h√∏yde √• matche, er fjernet, se punkt 4 i spec-en). */
.hero-product-image {{ width: 100%; height: auto; aspect-ratio: 1 / 1; margin: 0 auto; border-radius: 18px; background: var(--mist); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; padding: 10px; box-sizing: border-box; font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 2.4rem; color: var(--blue); }}
.hero-product-image img {{ width: 100%; height: 100%; object-fit: contain; }}
@media (min-width: 640px) {{ .hero-product-image {{ border-radius: 20px; font-size: 2.6rem; }} }}
@media (min-width: 1280px) {{ .hero-product-image {{ width: 100%; height: 100%; aspect-ratio: auto; margin: 0; font-size: 3rem; }} }}
/* Fade-masken (radial gradient som lot hvite produktbilder smelte inn i
   siden) er fjernet -- den var designet for √• blande hvitt inn i en FARGET
   hero-bakgrunn, men heroen er n√• selv hvit (se .hero-card), s√• masken
   gjorde ingenting nyttig lenger og risikerte i tillegg √• dempe kantene p√•
   bilder som IKKE er helt rene hvite (se SofLens-bildet med gr√• bakgrunn
   som avsl√∏rte den "blob"-formede kanteffekten tidligere i dag). Minimal
   padding (6px, ikke 0) kun for √• unng√• at bildet klipper helt inntil
   kortkanten -- ellers skal bildet fylle mest mulig av ruta, som √∏nsket. */
.hero-product-image.has-photo {{ background: transparent; border: none; padding: 6px; }}
.hero-product-image.has-photo img {{ object-fit: contain; }}

{WINNER_WIDGET_STYLE}
.product-ai-summary {{ background: var(--blue-tint); border-left: 4px solid var(--blue); border-radius: 0 10px 10px 0; padding: 12px 18px; margin: 12px 0; font-size: 0.95rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary p {{ margin: 0; }}
.product-ai-summary.fallback {{ background: var(--muted-bg); border-left-color: var(--muted); color: var(--muted); }}
{PRICE_LIST_STYLE}</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-product">
  <p class="breadcrumb">
    <a href="/">Hjem</a> ‚Ä∫
    <a href="/kontaktlinser/{escape(product["category_slug"])}/">{escape(categories[product["category_slug"]]["label"])}</a> ‚Ä∫
    <a href="/merke/{escape(product["brand_slug"])}/">{escape(product["brand_label"])}</a> ‚Ä∫
    {escape(product["name"])}
  </p>
  <div class="product-stage">
    <div class="hero-card">
      <div class="hero-main">
        <div class="hero-copy">
          <p class="hero-kicker">{escape(product["brand_label"])}</p>
          <h1>{escape(product["name"])}</h1>
          <p class="hero-subtitle">Sammenlign priser</p>
          {hero_facts_html}
        </div>
        <div class="hero-media-row">
          <div class="hero-product-image{' has-photo' if image_url else ''}">{thumb}</div>
          {winner_html}
        </div>
      </div>
    </div>
    {qty_html}
  </div>
  {offers_block}
  <noscript><style>.offers-show-more{{display:none}}.offers.is-collapsed .offers-list .offer-card{{display:flex}}</style></noscript>
  {price_history_html}
  {qty_multi_html}
  {disclosure_html}
  {pack_size_callout}
  {family_callout}

  <div class="kz-break"><span>Alt om {escape(product["name"])}</span></div>
  <div class="kz">
    {ai_summary_html}
    <h2>Om {escape(product["name"])}</h2>
    <p>{escape(long_description)}</p>{alt_name_html}
    {badges_html}
    {aliases_html}
    {kz_specs_html}
    {kz_faq_html}
    {kz_sources_html}
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def _brand_family_summary(family: dict, member_products: list[dict], categories: dict, now: datetime) -> dict | None:
    """Samme type per-produkt-oppsummering som render_family_page() sin
    rows/table_groups bygger, men skalert ned til det merke-siden faktisk
    trenger (√©n oppsummeringsrad PER SERIE, ikke per behov) -- egen, enklere
    funksjon i stedet for √• gjenbruke render_family_page sin interne (ikke
    faktorerte ut) logikk direkte."""
    rows = []
    for p in member_products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        best = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        specs = {label: value for label, value in p.get("specs", [])}
        pack = _pack_size_from_id(p["id"])
        rows.append({
            "product": p, "best": best, "eligible": eligible,
            "category_label": categories.get(p["category_slug"], {}).get("label", ""),
            "material": specs.get("Materiale"),
            "wc": _parse_spec_numbers(specs.get("Vanninnhold")),
            "pack_size": pack[1] if pack else None,
        })
    if not rows:
        return None
    type_labels = sorted({r["category_label"] for r in rows if r["category_label"]})
    materials = {r["material"] for r in rows if r["material"]}
    wc_values = {tuple(r["wc"]) for r in rows if r["wc"]}
    packs = sorted({r["pack_size"] for r in rows if r["pack_size"]})
    prices = [r["best"]["price_nok"] for r in rows if r["best"]]
    rep = min(rows, key=lambda r: r["pack_size"] or 0)
    return {
        "slug": family["slug"], "name": family["name"], "rows": rows,
        "type_labels": type_labels,
        "material": next(iter(materials)) if len(materials) == 1 else None,
        "wc": next(iter(wc_values)) if len(wc_values) == 1 else None,
        "packs": packs,
        "min_price": min(prices) if prices else None,
        "n_products": len(rows),
        "image": _product_image(rep["product"]),
        "href": f'/serie/{family["slug"]}/',
    }


BRAND_PAGE_STYLE = """
/* Merke-siden sitt l√∏ft (2026-09-27, samme dag som serie-siden sin
   FAQ-regelmotor) -- egne brand-*-klassenavn (ikke gjenbruk av
   serie-siden sine serie-*-klassenavn, selv der m√∏nsteret er identisk)
   for √• holde de to sidetypene sin CSS uavhengige av hverandre. */
.brand-stat-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.brand-stat-pill { display: flex; align-items: center; gap: 8px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 6px 10px; box-shadow: var(--card-shadow); }
.brand-stat-icon { width: 24px; height: 24px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.brand-stat-icon svg { width: 13px; height: 13px; }
.brand-stat-label { font-size: 0.68rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.02em; line-height: 1.25; }
.brand-stat-value { font-size: 0.82rem; font-weight: 600; color: var(--ink); line-height: 1.25; }
.brand-section-lead { color: var(--muted); font-size: 0.88rem; margin: 0 0 14px; }
/* Series Portrait Cards (2026-09-27, samme dag, etter Kais 19-punkts
   brief + presisering om kortbredde). Kortet skal ALDRI strekkes bredere
   bare fordi merket har f√• serier -- minmax() med en fast maks (340px),
   IKKE 1fr, s√• tomme grid-spor bare blir ubrukt luft i stedet for at de
   fyller ekte kort til unaturlig bredde. auto-fill (ikke auto-fit) sikrer
   samme oppf√∏rsel uansett om det er 1, 2, 3, 4, 5 eller 8 serier. */
.brand-section-header-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.brand-section-kicker { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin-bottom: 2px; }
.brand-section-header-row h2 { margin: 0 0 6px; }
.brand-section-header-row .brand-section-lead { margin: 0; }
.brand-serie-compare-link { font-size: 0.85rem; font-weight: 600; color: var(--blue); text-decoration: none; white-space: nowrap; margin-top: 4px; }
.brand-serie-compare-link:hover { text-decoration: underline; }
/* minmax(280px, 1fr), IKKE en fast maks-px -- auto-fill teller antall
   spor etter MIN-verdien kun n√•r maks er ubestemt (1fr), som gir flest
   mulig kolonner ("4 kort p√• √©n rad der plassen tillater" -- en fast
   maks-px (f.eks. 350px) far derimot brukt til selve spor-TELLINGEN i
   Grid-spesifikasjonen, som i praksis ga bare 3 kolonner √• 1240px
   containerbredde her, ikke 4). Tomme auto-fill-spor forblir usynlig
   luft (IKKE strukket brede) selv med 1fr, siden 1fr bare fordeler
   overskuddsplass likt p√• ALLE spor (ekte og tomme) -- se
   CSS_GRID_SERIES_WIDTH-testnotat i CLAUDE.md. */
.brand-serie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); justify-content: start; align-items: stretch; gap: 18px; margin-bottom: 32px; }
.brand-serie-card { display: flex; flex-direction: column; max-width: 350px; background: white; border: 1px solid var(--border); border-radius: 16px; overflow: hidden; text-decoration: none; color: var(--ink); box-shadow: var(--card-shadow); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.brand-serie-card:hover, .brand-serie-card:focus-visible { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(11, 37, 69, 0.1); border-color: #B9C4CE; }
.brand-serie-card-top { padding: 16px 16px 0; background: linear-gradient(180deg, var(--serie-tint, var(--mist)) 0%, rgba(255, 255, 255, 0) 68%); }
.brand-serie-card-eyebrow { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
.brand-serie-card-image { height: 148px; margin-top: 8px; display: flex; align-items: center; justify-content: center; }
.brand-serie-card-image img { max-width: 76%; max-height: 100%; height: auto; object-fit: contain; transition: transform 0.18s ease; }
.brand-serie-card:hover .brand-serie-card-image img, .brand-serie-card:focus-visible .brand-serie-card-image img { transform: scale(1.02); }
.brand-serie-card-fallback { font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 1.6rem; color: var(--blue); }
.brand-serie-card-body { flex: 1; display: flex; flex-direction: column; padding: 14px 16px 16px; }
.brand-serie-card-name { font-family: 'Mulish', sans-serif; font-weight: 700; font-size: 1rem; line-height: 1.3; }
.brand-serie-card-desc { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin: 6px 0 0; font-size: 0.82rem; line-height: 1.45; color: var(--muted); }
.brand-serie-card-pills { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.brand-serie-card-pill { border: 1px solid var(--border); border-radius: 999px; padding: 2px 8px; font-size: 0.64rem; font-weight: 500; color: var(--muted); }
.brand-serie-card-spacer { flex: 1; min-height: 10px; }
.brand-serie-card-foot { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 0.78rem; color: var(--muted); }
.brand-serie-card-foot strong { color: var(--ink); font-weight: 700; }
.brand-serie-card-cta { display: flex; align-items: center; justify-content: center; gap: 6px; margin-top: 12px; padding: 9px 14px; border: 1px solid var(--border); border-radius: 10px; font-size: 0.82rem; font-weight: 600; color: var(--ink); transition: border-color 0.18s ease, color 0.18s ease; }
.brand-serie-card-cta span { transition: transform 0.18s ease; }
.brand-serie-card:hover .brand-serie-card-cta, .brand-serie-card:focus-visible .brand-serie-card-cta { border-color: var(--blue); color: var(--blue); }
.brand-serie-card:hover .brand-serie-card-cta span, .brand-serie-card:focus-visible .brand-serie-card-cta span { transform: translateX(3px); }
.brand-facts { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); height: 100%; box-sizing: border-box; }
.brand-facts h2 { margin: 0 0 14px; font-family: 'Mulish', sans-serif; font-size: 1.05rem; }
/* Prisintelligens ved siden av "i korte trekk" (Kai 2026-09-27: "kan v√¶re
   ved siden av gjen.snitt priser som p√• serier ... slik at vi har det
   samme her som p√• serie") -- samme to-kolonners stretch-m√∏nster som
   .serie-insight-row (Prisinnsikt + Kort om X). */
.brand-insight-row { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 8px 0 32px; }
@media (min-width: 900px) { .brand-insight-row { grid-template-columns: 1fr 1fr; align-items: stretch; } }
.brand-i-tall { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); height: 100%; box-sizing: border-box; }
.brand-i-tall h2 { margin: 0; font-family: 'Mulish', sans-serif; font-size: 1.05rem; }
.brand-i-tall-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 14px; }
@media (min-width: 480px) and (max-width: 899px) { .brand-i-tall-grid { grid-template-columns: repeat(3, 1fr); } }
.brand-i-tall-tile { background: var(--mist); border: 1px solid var(--border); border-radius: 12px; padding: 14px 12px; }
.brand-i-tall-icon { width: 30px; height: 30px; border-radius: 50%; display: fleÎü8·º≠z &ä€^t¥¿‰¥»‹§Ä¥¥Å’≠©ïπ—îΩô…ïµ—•ë•ùî(ÄÄÄÄÄÄÄÄåÅ≠Ö—ïùΩ…•ï»ÅôÖ±±ï»Å—•±âÖ≠îÅ—•∞ÅQ}%=9}MYΩâ±’îÅ§ÅÕ—ïëï–ÅôΩ»Éî(ÄÄÄÄÄÄÄÄåÅ≠…ÖÕ©îÅï±±ï»ÅŸ•ÕîÅ•πùïπ—•πú∏(ÄÄÄÄÄÄÄÅïÂï}•çΩ∏ÄÙÄúÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅ·µ±πÃÙâ°——¿ËºΩ››‹π‹ÃπΩ…úº»¿¿¿ΩÕŸúàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îàÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêà¯Ò¡Ö—†ÅêÙâ4»Äƒ…Ã–¥‹Äƒ¿¥‹Äƒ¿Ä‹Äƒ¿Ä‹¥–Ä‹¥ƒ¿Ä‹¥ƒ¿¥‹¥ƒ¿¥›Ëàº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÃàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îÙâπΩπîàº¯ΩÕŸú¯ú(ÄÄÄÄÄÄÄÅ¡ï…ÕΩπ}•çΩ∏ÄÙÄúÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅ·µ±πÃÙâ°——¿ËºΩ››‹π‹ÃπΩ…úº»¿¿¿ΩÕŸúàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùà‡àÅ»ÙàÃ∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4‘Ä»¡å¿¥–ÄÃ¥ÿ∏‘Ä‹¥ÿ∏’Ã‹Ä»∏‘Ä‹Äÿ∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‘àº¯ΩÕŸú¯ú(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}•çΩπ}µÖ¿ÄÙÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâëÖùÕ±•πÕï»àËÄ†âÖµâï»à∞ÅMU9}%=9}MY§∞ÄâµÖπïëÕ±•πÕï»àËÄ†âÕ≠‰à∞Å19I}%=9}MY§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ—Ω…•Õ≠îµ±•πÕï»àËÄ†âçΩ…Ö∞à∞ÅïÂï}•çΩ∏§∞Äâµ’±—•ôΩ≠Ö±îµ±•πÕï»àËÄ†â±ÖŸïπëï»à∞Å¡ï…ÕΩπ}•çΩ∏§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâôÖ…ùïëîµ±•πÕï»àËÄ†âµ•π–à∞ÅI=A1Q}%=9}MY§∞(ÄÄÄÄÄÄÄÅÙ((ÄÄÄÄÄÄÄÅëïòÅÕΩ…—•µïπ—}çÖ…ê°åËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅÕï…•ïÕ}—·–ÄÙÄàÉ
‹Äàπ©Ω•∏°çlâÕï…•ïÕ}πÖµïÃât§Å•òÅçlâÕï…•ïÕ}πÖµïÃâtÅï±ÕîÄàà(ÄÄÄÄÄÄÄÄÄÄÄÅçΩ±Ω»∞Å•çΩ∏ÄÙÅçÖ—ïùΩ…Â}•çΩπ}µÖ¿πùï–°çlâÕ±’úât∞Ä†ââ±’îà∞ÅQ}%=9}MY§§(ÄÄÄÄÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúúúÒÑÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êàÅ°…ïòÙàçÌïÕçÖ¡î°çlâÕ±’úât•ÙàÅëÖ—ÑµçÖ—ïùΩ…‰ÙâÌïÕçÖ¡î°çlâÕ±’úât•Ùà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÌçΩ±Ω…Ùµ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÌçΩ±Ω…Ù§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµ±Öâï∞à˘ÌïÕçÖ¡î°çlâ±Öâï∞ât•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµçΩ’π–à˘ÌçlâçΩ’π–âuÙÅÏâ¡…Ωë’≠–àÅ•òÅçlâçΩ’π–âtÄÙÙÄƒÅï±ÕîÄâ¡…Ωë’≠—ï»âÙΩë•ÿ¯(ÄÄÄÅÌòúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµÕï…•ïÃà˘ÌïÕçÖ¡î°Õï…•ïÕ}—·–•ÙΩë•ÿ¯úÅ•òÅÕï…•ïÕ}—·–Åï±ÕîÄúùÙ(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµ±•π¨à˘MîÅÌïÕçÖ¡î°çlâ±Öâï∞âtπ±Ω›ï»†§•ÙÉäHΩë•ÿ¯(ÄÄΩÑ¯úúú(ÄÄÄÄÄÄÄÅÕΩ…—•µïπ—}°—µ∞ÄÙÅòúúúÒ†»˘ÌïÕçÖ¡î°â…Öπë}±Öâï∞•ÙµÕΩ…—•µïπ—ï–ÅôΩ…≠±Ö…–Ω†»¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ÖπêµÕïç—•Ω∏µ±ïÖêà˘Ì±ï∏°ÕΩ…—•µïπ—}çÖ…ëÃ•ÙÅ≠Ö—ïùΩ…•ï»ÅµïêÅ—•∞ÅÕÖµµï∏ÅÌ±ï∏°¡…Ωë’ç—Ã•ÙÅ¡…Ωë’≠—ï»Ä¥¥ÅŸï±úÅëï∏ÅÕΩ¥Å¡ÖÕÕï»Åë•—–Åâï°Ωÿ∏Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°ÕΩ…—•µïπ—}çÖ…ê°å§ÅôΩ»ÅåÅ•∏ÅÕΩ…—•µïπ—}çÖ…ëÃ•Ù(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥ÄàÃ¿Åï±±ï»Ä‰¿Å±•πÕï»¸àÄ¥¥Åï≠—îÅÖπÖ±ÂÕîÅCÅQYILÅÖÿÅµï…≠ï–∞Å≠’∏ÅâÂùùï–(ÄÄÄÄåÅ°Ÿ•ÃÅŸ§ÅôÖ≠—•Õ¨Å°Ö»ÅπΩ¨Å…Ωâ’Õ—îÄÃ¿º‰¿µ¡Ö»Ä°ÕÖµµîÅ’πëï…±•ùùïπëî(ÄÄÄÄåÅ¡…Ωë’≠–ÅŸ•ÑÅ}¡Öç≠}Õ•Èï}ô…Ωµ}•ê∞Å•≠≠îÅ’±•≠îÅ¡…Ωë’≠—ï»§∏ÅQï…Õ≠ï∞Å√î(ÄÄÄÄåÅµ•πÕ–Ä»Å¡Ö»Ä¥¥Åï—–Åïπ≠ï±–Å¡Ö»Åï»Å•≠≠îÅï∏ÄâÖπÖ±ÂÕîà∞Åëï–Åï»ÅâÖ…îÅëï–(ÄÄÄÄåÅÕÖµµîÅ—Ö±±ï–ÅÕΩ¥ÅÖ±±ï…ïëîÅÕ”ï»Å§ÅDµï∏Ä†â°Ÿ•±≠ï∏Å¡Ö≠π•πúÅ°Ö»Å±ÖŸïÕ–(ÄÄÄÄåÅ¡…•ÃÅ¡ï»Å±•πÕîà§∏ÅMîÅ-Ö§ÅÕ•∏Å¡ÖÕ—ïëîÅâ…•ïò∞ÅÖÕîÄƒƒËÄâ!Ÿ•ÃÅµÖ¡¡•πùï∏(ÄÄÄÄåÅ•≠≠îÅï»ÅÕ•≠≠ï»ËÅ•≠≠îÅâÂùúÅµΩë’±ï∏Åïπªî∏à(ÄÄÄÅ¡Öç≠}¡Ö•…ÃÄÙÅmt(ÄÄÄÅâÂ}Õ—ï¥ËÅë•ç—mÕ—»∞Åë•ç—m•π–∞Åë•ç—utÄÙÅÌÙ(ÄÄÄÅôΩ»Å»Å•∏Å…Ω›ÃË(ÄÄÄÄÄÄÄÅ¡Ö…ÕïêÄÙÅ}¡Öç≠}Õ•Èï}ô…Ωµ}•ê°…lâ¡…Ωë’ç–âulâ•êât§(ÄÄÄÄÄÄÄÅ•òÅ¡Ö…ÕïêÅÖπêÅ…lâ±Ω›ïÕ–âtË(ÄÄÄÄÄÄÄÄÄÄÄÅÕ—ï¥∞Å¡Öç¨ÄÙÅ¡Ö…Õïê(ÄÄÄÄÄÄÄÄÄÄÄÅâÂ}Õ—ï¥πÕï—ëïôÖ’±–°Õ—ï¥∞ÅÌÙ•m¡Öç≠tÄÙÅ»(ÄÄÄÅôΩ»ÅÕ—ï¥∞ÅâÂ}¡Öç¨Å•∏ÅâÂ}Õ—ï¥π•—ïµÃ†§Ë(ÄÄÄÄÄÄÄÅ•òÄÃ¿Å•∏ÅâÂ}¡Öç¨ÅÖπêÄ‰¿Å•∏ÅâÂ}¡Öç¨Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ»Ã¿∞Å»‰¿ÄÙÅâÂ}¡Öç≠lÃ¡t∞ÅâÂ}¡Öç≠l‰¡t(ÄÄÄÄÄÄÄÄÄÄÄÅ¿Ã¿ÄÙÅ»Ã¡lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÄºÄÃ¿(ÄÄÄÄÄÄÄÄÄÄÄÅ¿‰¿ÄÙÅ»‰¡lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÄºÄ‰¿(ÄÄÄÄÄÄÄÄÄÄÄÅ¡Öç≠}¡Ö•…ÃπÖ¡¡ïπê°ÏâπÖµîàËÅ»Ã¡lâ¡…Ωë’ç–âulâπÖµîât∞Äâ¿Ã¿àËÅ¿Ã¿∞Äâ¿‰¿àËÅ¿‰¡Ù§(ÄÄÄÅ¡Öç≠|Ã¡|‰¡}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ±ï∏°¡Öç≠}¡Ö•…Ã§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÅπ|‰¡}ç°ïÖ¡ï»ÄÙÅÕ’¥†ƒÅôΩ»Å¡¿Å•∏Å¡Öç≠}¡Ö•…ÃÅ•òÅ¡¡lâ¿‰¿âtÄÅ¡¡lâ¿Ã¿ât§(ÄÄÄÄÄÄÄÅâïÕ—}ï·Öµ¡±îÄÙÅµÖ‡°¡Öç≠}¡Ö•…Ã∞Å≠ï‰ı±ÖµâëÑÅ¡¿ËÅÖâÃ°¡¡lâ¿Ã¿âtÄ¥Å¡¡lâ¿‰¿ât§§(ÄÄÄÄÄÄÄÅ¿Ã¡}—·–ÄÙÅòùÌâïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtË∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅ¿‰¡}—·–ÄÙÅòùÌâïÕ—}ï·Öµ¡±ïlâ¿‰¿âtË∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅë•ôô}¡ç–ÄÙÅ…Ω’πê°ÖâÃ°âïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtÄ¥ÅâïÕ—}ï·Öµ¡±ïlâ¿‰¿ât§ÄºÅâïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtÄ®Äƒ¿¿§(ÄÄÄÄÄÄÄÅç°ïÖ¡ï…}›Ω…êÄÙÄà‰¿µ¡Ö≠π•πùï∏àÅ•òÅâïÕ—}ï·Öµ¡±ïlâ¿‰¿âtÄÅâïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtÅï±ÕîÄàÃ¿µ¡Ö≠π•πùï∏à(ÄÄÄÄÄÄÄÅ¡Öç≠|Ã¡|‰¡}°—µ∞ÄÙÅòúúúÒ†»¯Ã¿Åï±±ï»Ä‰¿Å±•πÕï»¸Ω†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µçÖ…êà¯(ÄÄÄÄÒ¿˘Ω»ÅÌπ|‰¡}ç°ïÖ¡ï…ÙÅÖÿÅÌ±ï∏°¡Öç≠}¡Ö•…Ã•ÙÅÕÖµµïπ±•ùπâÖ…îÅÌïÕçÖ¡î°â…Öπë}±Öâï∞•Ùµ¡…Ωë’≠—ï»Å°Ö»Ä‰¿µ¡Ö≠π•πùï∏Å±ÖŸï…îÅ¡…•ÃÅ¡ï»Å±•πÕîÅïπ∏Å—•±ÕŸÖ…ïπëîÄÃ¿µ¡Ö≠π•πúÅÖ≠≠’…Ö–Åªî∏Å≠Õïµ¡ï∞Ä¥¥ÅÌïÕçÖ¡î°âïÕ—}ï·Öµ¡±ïlâπÖµîât•ÙËΩ¿¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µù…•êà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÕ≠‰µ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÕ≠‰§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì	=a}%=9}MYÙΩë•ÿ¯ÒÕ—…Ωπú˘Ì¿Ã¡}—·—ÙÅ≠»ΩÕ—…Ωπú¯ÒÕ¡Ö∏¯Ã¿µ¡Öç¨∞Å¡ï»Å±•πÕîΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µµ•π–µ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µµ•π–§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì	=a}%=9}MYÙΩë•ÿ¯ÒÕ—…Ωπú˘Ì¿‰¡}—·—ÙÅ≠»ΩÕ—…Ωπú¯ÒÕ¡Ö∏¯‰¿µ¡Öç¨∞Å¡ï»Å±•πÕîΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÖµâï»µ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÖµâï»§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘ÌQ}%=9}MYÙΩë•ÿ¯ÒÕ—…Ωπú˘Ìë•ôô}¡ç—ÙÄîΩÕ—…Ωπú¯ÒÕ¡Ö∏˘Ω…Õ≠©ï±∞Ä¥¥ÅÌïÕçÖ¡î°ç°ïÖ¡ï…}›Ω…ê•ÙÅâ•±±•ùÕ–ΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µπΩ—îà˘-’∏ÅÕÖµµîÅ’πëï…±•ùùïπëîÅ¡…Ωë’≠–ÅÕÖµµïπ±•ùπï–Ä°Ö±ë…§Å’±•≠îÅ¡…Ωë’≠—ï»ÅµΩ–Å°Ÿï…Öπë…î§∏Å!’Õ¨ÉîÅ…ïùπîÅµïêÅô…Ö≠–ÅôΩ»ÅÖ≠≠’…Ö–Åëï–ÅÖπ—Ö±±ï–Åë‘Å—…ïπùï»∏Ω¿¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥Äâ9Â——•ùîÅ…ïÕÕ’…Õï»àÄ¥¥Å%--Äâ3ô»Åµï»ÅΩ¥ÅÌâ…ÖπëÙàÄ°-Ö§ÅÕ•∏Å¡ÖÕ—ïëî(ÄÄÄÄåÅâ…•ïòÅï»Åï≠Õ¡±•Õ•—–Å√îÅëï——îËÅù’•ëïπîÅ°Öπë±ï»ÅΩ¥Å≠Ωπ—Ö≠—±•πÕï»(ÄÄÄÄåÅùïπï…ï±–∞Å•≠≠îÅΩ¥Åµï…≠ï–§∏Å©ïπâ…’≠ï»Å…ïπëï…}ù’•ëï}—•±î†§Ä°ÕÖµµî(ÄÄÄÄåÅô’π≠Õ©Ω∏ÅÕΩ¥ÄΩù’•ëï»ºµΩŸï…Õ•≠—ï∏ÅΩúÅôΩ…Õ•ëï∏§Åë•…ï≠—îÄ¥¥ÅÖ±±îÄ–¿(ÄÄÄÄåÅù’•ëï»Å°Ö»ÅªîÅïùï–ÅôΩ—ºÄ°ÕîÅU%}A!=Q=L§∞ÅœîÅëï——îÅâ±•»ÅÖ±±—•ê(ÄÄÄÄåÅâ•±ëï≠Ω…–∞Å•πùï∏Åïùï∏Å≠Ωµ¡Ωπïπ–ÉîÅŸïë±•≠ï°Ω±ëîÅ°ï»∏(ÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃÄÙÅlâ°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»ât(ÄÄÄÅ•òÄâëÖùÕ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃÅÖπêÄâµÖπïëÕ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†âµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»à§(ÄÄÄÅï±•òÄâ—Ω…•Õ≠îµ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†â≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•Õµîà§(ÄÄÄÅï±•òÄâµ’±—•ôΩ≠Ö±îµ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†âµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»à§(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†â°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»à§(ÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†ââåµôΩ…≠±Ö…–à§(ÄÄÄÅâ…Öπë}ù’•ëïÕ}°—µ∞ÄÙÅòúúúÒ†»˘9Â——•ùîÅ…ïÕÕ’…Õï»Ω†»¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ÖπêµÕïç—•Ω∏µ±ïÖêà˘…—•≠±ï»∞ÅôΩ…≠±Ö…•πùï»ÅΩúÅù’•ëï»ÅÕΩ¥Å°©ï±¡ï»ÅëïúÉîÅ—ÑÅùΩëîÅŸÖ±ú∏Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°…ïπëï…}ù’•ëï}—•±î°Õ±’ú∞ÅU%}=9Q9QmÕ±’ùt§ÅôΩ»ÅÕ±’úÅ•∏Åâ…Öπë}ù’•ëï}Õ±’ùÃÅ•òÅÕ±’úÅ•∏ÅU%}=9Q9P•Ù(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥ÄâA…Ωë’Õïπ–àÄ¥¥Å≠Ωµ¡Ö≠–ÅµΩë’∞∞ÅÕ—Â…≠ï»Åïπ—•—‰µ°•ï…Ö…≠•ï–ÅA…Ωë’Õïπ–(ÄÄÄÄåÄ¥¯Å5ï…≠îÄ¥¯ÅMï…•îÄ¥¯ÅA…Ωë’≠–∏Å-’∏ÅâÂùùï–Å°Ÿ•ÃÅŸ§ÅôÖ≠—•Õ¨Å°Ö»Åï∏(ÄÄÄÄåÅ¡…Ωë’Õïπ–µ≠Ωâ±•πúÄ°	I9}Q=}59UQUIH§∏(ÄÄÄÅâ…Öπë}µÖπ’ôÖç—’…ï…}µΩë’±ï}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅµÖπ’ôÖç—’…ï…}Õ±’úË(ÄÄÄÄÄÄÄÅµòÄÙÅ59UQUIIMmµÖπ’ôÖç—’…ï…}Õ±’ùt(ÄÄÄÄÄÄÄÅâ…Öπë}µÖπ’ôÖç—’…ï…}µΩë’±ï}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖπ’ôÖç—’…ï»µçÖ…êà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖπ’ôÖç—’…ï»µ≠•ç≠ï»à˘A…Ωë’Õïπ–Ωë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖπ’ôÖç—’…ï»µπÖµîà˘ÌïÕçÖ¡î°µôlâπÖµîât•ÙΩë•ÿ¯(ÄÄÄÄÒÑÅç±ÖÕÃÙââ…ÖπêµµÖπ’ôÖç—’…ï»µ±•π¨àÅ°…ïòÙàΩ¡…Ωë’Õïπ–ΩÌïÕçÖ¡î°µÖπ’ôÖç—’…ï…}Õ±’ú•Ùºà˘1ïÃÅµï»ÅΩ¥ÅÌïÕçÖ¡î°µôlâπÖµîât•ÙÉäHΩÑ¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥Äâ=¥Å•πôΩ…µÖÕ©Ωπï∏Å√îÅëïππîÅÕ•ëï∏àÄ¥¥ÅÕÖµµîÅô•…îµï±ïµïπ—ï»µ∑·πÕ—ï»(ÄÄÄÄåÅÕΩ¥Å-Ö§ÅÕ•∏Å¡ÖÕ—ïëîÅâ…•ïòÅâÑÅΩ¥∞Å—ï≠Õ—ïπîÅï»Å	Y%MMPÅ•ëïπ—•Õ≠îÅµïê(ÄÄÄÄåÄ°•≠≠îÅπÂîÅ√ïÕ—Öπëï»Åïπ∏§Åëï–ÅÕΩ¥ÅÖ±±ï…ïëîÅÕ”ï»Å§Åë•Õç±ΩÕ’…îµÖŸÕπ•——ï–(ÄÄÄÄåÅΩúÅ√îÄΩÕ±•¨µÕÖµµïπ±•ùπï»µŸ§µ¡…•Õï»ºÄ¥¥ÄâΩ¡¡ëÖ—ï…ïÃÅëÖù±•úà∞Å•≠≠î(ÄÄÄÄåÄâô±ï…îÅùÖπùï»ÅëÖù±•úàÅÕΩ¥Åâ…•ïòÅÕ•—–Åï≠Õïµ¡ï∞ÅôΩ…ïÕ±º∞ÅÕ•ëï∏Åëï–(ÄÄÄÄåÅŸ•±±îÅ€ô…–Åï∏Å√ïÕ—ÖπêÅŸ§Å•≠≠îÅ≠Ö∏ÅëΩ≠’µïπ—ï…îÄ°ÕîÅ…Ö¡¡Ω…–Å—•∞Å-Ö§§∏(ÄÄÄÅâ…Öπë}—…’Õ—}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–à¯(ÄÄÄÄÒ†»˘=¥Å•πôΩ…µÖÕ©Ωπï∏Å√îÅëïππîÅÕ•ëï∏Ω†»¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µù…•êà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘A…Ωë’≠—•πôΩ…µÖÕ©Ω∏ΩÕ—…Ωπú¯Ò¿˘	ÖÕï…–Å√îÅëΩ≠’µïπ—ï…—îÅ¡…Ωë’Õïπ—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»ÅΩúÅ€ï»Å¡…Ωë’≠—ëÖ—ÖâÖÕî∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘A…•Õï»ΩÕ—…Ωπú¯Ò¿˘!ïπ—ïÃÅô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÅΩúÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘-Ωµµï…Õ•ï±±îÅ±ïπ≠ï»ΩÕ—…Ωπú¯Ò¿˘Y§Å≠Ö∏ÅµΩ——ÑÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Åüï»ÅŸ•ëï…îÅ—•∞Åï∏Åâ’—•≠¨∏Åï——îÅ√ïŸ•…≠ï»ÅÖ±ë…§Å¡…•Õ…ï≠≠ïõ·±ùï∏∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘MÖµµïπ±•ùπ•πúΩÕ—…Ωπú¯Ò¿˘A…•ÃÅ¡ï»Å±•πÕîÅâï…ïùπïÃÅô…ÑÅ¡Ö≠π•πùÕÕ”·……ï±Õî∏ÅQΩ—Ö±¡…•ÃÅ•π≠±’ëï…ï»Åô…Ö≠–Åëï»Åô…Ö≠—ëÖ—ÑÅï»Å—•±ù©ïπùï±•ú∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙââ…Öπêµ—…’Õ–µ±•π≠Ãà¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩÕ±•¨µÕÖµµïπ±•ùπï»µŸ§µ¡…•Õï»ºà˘M±•¨ÅÕÖµµïπ±•ùπï»ÅŸ§Å¡…•Õï»ÉäHΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩ…ïëÖ≠Õ©Ωπï±±îµ¡…•πÕ•¡¡ï»ºà˘IïëÖ≠Õ©Ωπï±±îÅ¡…•πÕ•¡¡ï»ÉäHΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩΩ¥µΩÕÃºà˘=¥Å-Ωπ—Ö≠—±•πÕï»ππºÉäHΩÑ¯(ÄÄÄÄΩ¿¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÅÕç°ïµÖ}•—ïµÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÅÌ§¨≈Ù∞Äâ’…∞àËÄâÌ	M}UI1ÙΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°¡lâπÖµîât•ÙâıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å§∞Å¿Å•∏Åïπ’µï…Ö—î°¡…Ωë’ç—Ã§(ÄÄÄÄ§(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌïÕçÖ¡î°â…Öπë}±Öâï∞•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩµï…≠îΩÌâ…Öπë}Õ±’ùÙºâıÙ(ÄÄÄÅuıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ%—ïµ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅmÌÕç°ïµÖ}•—ïµÕıuıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°â…Öπë}±Öâï∞•ÙÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°µï—Ö}ëïÕç…•¡—•Ω∏•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩµï…≠îΩÌâ…Öπë}Õ±’ùÙºà¯)Ì}Ωù}µï—Ñ°òùÌâ…Öπë}±Öâï±ÙÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Åµï—Ö}ëïÕç…•¡—•Ω∏∞ÅòùÌ	M}UI1ÙΩµï…≠îΩÌâ…Öπë}Õ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯)Ìâ…Öπë}ôÖ≈}Õç°ïµÖÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù)ÌU%}Q%1}MQe1Ù)Ì	I9}A}MQe1Ù(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°â…Öπë}±Öâï∞•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµçΩπ—ïπ–à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµ…Ω‹à¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘5ï…≠îΩë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°â…Öπë}±Öâï∞•ÙΩ†ƒ¯(ÄÄÄÄÄÄÄÄÄÅÌâ…Öπë}Õ’â—•—±ï}°—µ±Ù(ÄÄÄÄÄÄÄÄÄÄÒ¿˘Ìâ…Öπë}•π—…Ω}Õïπ—ïπçïÙΩ¿¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµç—Ñµ…Ω‹à¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒÑÅç±ÖÕÃÙââ…Öπêµ°ï…ºµç—ÑàÅ°…ïòÙàç¡…Ωë’≠—ï»à˘MîÅÖ±±îÅÌïÕçÖ¡î°â…Öπë}±Öâï∞•Ùµ¡…Ωë’≠—ï»ÉäHΩÑ¯(ÄÄÄÄÄÄÄÄÄÄÄÅÌµÖπ’ôÖç—’…ï…}±•π≠}°—µ±Ù(ÄÄÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµµïë•ÑàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯(ÄÄÄÄÄÄÒ¡•ç—’…î¯(ÄÄÄÄÄÄÄÄÒÕΩ’…çîÅµïë•ÑÙà°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§àÅ—Â¡îÙâ•µÖùîΩ›ïâ¿àÅÕ…çÕï–ÙàΩÕ—Ö—•åΩ°ï…ºΩâ…Öπê¥‘ÿ¿π›ïâ¿Ä‘ÿ¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩâ…Öπê¥‡–¿π›ïâ¿Ä‡–¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩâ…Öπê¥ƒƒ»¿π›ïâ¿Äƒƒ»¡‹àÅÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ»¿¡¡‡§Ä‘ÿ¡¡‡∞Ä–¡Ÿ‹à¯(ÄÄÄÄÄÄÄÄÒ•µúÅÕ…åÙâëÖ—ÑÈ•µÖùîΩù•òÌâÖÕîÿ–±H¡±=±°E	 ’	-1	%Q=‹ÙÙàÅÖ±–ÙààÅ›•ë—†Ùà‘ÿ¿àÅ°ï•ù°–ÙàÃ‡‘àÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄÄÄΩ¡•ç—’…î¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ—Ö—Ãà˘Ìâ…Öπë}°ï…Ω}Õ—Ö—Õ}°—µ±ÙΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâµΩâ•±îµ¡…Ωë’ç—Ãµô•…Õ–à¯(ÄÄÒë•ÿÅç±ÖÕÃÙâÕ’¡¡Ω…—•πúµçΩπ—ïπ–à¯(ÄÅÌÕï…•ïÕ}πÖŸ}°—µ±Ù(ÄÅÌâ…Öπë}•πÕ•ù°—}…Ω›}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•Ω…•—‰µ¡…Ωë’ç—Ãà¯(ÄÄÒ†»Å•êÙâ¡…Ωë’≠—ï»à˘±±îÅÌïÕçÖ¡î°â…Öπë}±Öâï∞•Ùµ¡…Ωë’≠—ï»Ω†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙâô•±—ï»µ…Ω‹àÅ•êÙâô•±—ï»µ…Ω‹àÅ…Ω±îÙâù…Ω’¿àÅÖ…•Ñµ±Öâï∞Ùâ•±—…ï»Åï——ï»Å≠Ö—ïùΩ…§à¯(ÄÄÄÄÒâ’——Ω∏Åç±ÖÕÃÙâç°•¿ÅÖç—•ŸîàÅëÖ—ÑµçÖ—ïùΩ…‰ÙâÖ±∞à˘±±îÅ≠Ö—ïùΩ…•ï»Ωâ’——Ω∏¯(ÄÄÄÅÌçÖ—ïùΩ…Â}ç°•¡ÕÙ(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ±•Õ–µ°ïÖëï»à¯(ÄÄÄÄÒ†»Å•êÙâ…ïÕ’±–µçΩ’π–à˘Ì±ï∏°¡…Ωë’ç—Ã•ÙÅ¡…Ωë’≠—ï»Ω†»¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅ•êÙâ¡…Ωë’ç–µ±•Õ–àÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµù…•êà¯(ÄÄÄÅÌ¡…Ωë’ç—}…Ω›Õ}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÄÒπΩÕç…•¡–¯Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‹·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà˘•±—…ï…•πúÅ≠…ïŸï»Å)ÖŸÖMç…•¡–∏Å1•Õ—ï∏ÅΩŸï»ÅŸ•Õï»ÅÖ±±îÅ¡…Ωë’≠—ï»∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏Ω¿¯ΩπΩÕç…•¡–¯((ÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÅÌÕΩ…—•µïπ—}°—µ±Ù(ÄÅÌâ…Öπë}çΩµ¡Ö…ï}…Ω›}°—µ±Ù(ÄÅÌ¡Öç≠|Ã¡|‰¡}°—µ±Ù(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµôÖƒµ›…Ö¿à˘Ìâ…Öπë}ôÖ≈}°—µ±ÙΩë•ÿ¯(ÄÅÌâ…Öπë}ù’•ëïÕ}°—µ±Ù(ÄÅÌâ…Öπë}µÖπ’ôÖç—’…ï…}µΩë’±ï}°—µ±Ù((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅY§ÅÕΩ…—ï…ï»ÅÖ±±—•êÅï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ÅY§Å≠Ö∏ÅõîÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Å°Öπë±ï»(ÄÄÄÅŸ•ÑÅ±ïπ≠ïπîÅ√îÅ¡…Ωë’≠—Õ•ëïπî∞Åµï∏Åëï–Å√ïŸ•…≠ï»Å•≠≠îÅ¡…•Õï∏Åë‘Åâï—Ö±ï»(ÄÄÄÅï±±ï»Å…Öπùï…•πùï∏ÅÖÿÅ¡…Ωë’≠—ï»Åï±±ï»Å—•±â’ê∏(ÄÄΩ¿¯((ÄÅÌòúÒë•ÿÅÕ—Â±îÙâµÖ‡µ›•ë—†Ë‹»¡¡‡ÌµÖ…ù•∏µ—Ω¿ËÃ…¡‡Ïà˘Ì	I9}=9Q9Qmâ…Öπë}Õ±’ùuÙΩë•ÿ¯úÅ•òÅâ…Öπë}Õ±’úÅ•∏Å	I9}=9Q9PÅï±ÕîÄàâÙ((ÄÅÌâ…Öπë}—…’Õ—}°—µ±Ù(Ωë•ÿ¯((ÒÕç…•¡–¯(ÄÅçΩπÕ–Åô•±—ï…IΩ‹ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùô•±—ï»µ…Ω‹ú§Ï(ÄÅçΩπÕ–Å±•Õ–ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…Ωë’ç–µ±•Õ–ú§Ï((ÄÅô’πç—•Ω∏ÅÖ¡¡±Â	…Öπë•±—ï»°çÖ—ïùΩ…‰§ÅÌÏ(ÄÄÄÅçΩπÕ–Åâ—∏ÄÙÅô•±—ï…IΩ‹π≈’ï…ÂMï±ïç—Ω»†úπç°•¡mëÖ—ÑµçÖ—ïùΩ…‰ÙàúÄ¨ÅçÖ—ïùΩ…‰Ä¨Äúâtú§Ï(ÄÄÄÅ•òÄ†Öâ—∏§Å…ï—’…∏Ï(ÄÄÄÅô•±—ï…IΩ‹π≈’ï…ÂMï±ïç—Ω…±∞†úπç°•¿ú§πôΩ…Öç†°åÄÙ¯Ååπç±ÖÕÕ1•Õ–π…ïµΩŸî†ùÖç—•Ÿîú§§Ï(ÄÄÄÅâ—∏πç±ÖÕÕ1•Õ–πÖëê†ùÖç—•Ÿîú§Ï(ÄÄÄÅ±ï–ÅŸ•Õ•â±îÄÙÄ¿Ï(ÄÄÄÅ±•Õ–π≈’ï…ÂMï±ïç—Ω…±∞†úπ¡…Ωë’ç–µ—•±îú§πôΩ…Öç†°çÖ…êÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–ÅÕ°Ω‹ÄÙÅçÖ—ïùΩ…‰ÄÙÙÙÄùÖ±∞úÅÒÅçÖ…êπëÖ—ÖÕï–πçÖ—ïùΩ…‰ÄÙÙÙÅçÖ—ïùΩ…‰Ï(ÄÄÄÄÄÅçÖ…êπÕ—Â±îπë•Õ¡±Ö‰ÄÙÅÕ°Ω‹Ä¸ÄúúÄËÄùπΩπîúÏ(ÄÄÄÄÄÅ•òÄ°Õ°Ω‹§ÅŸ•Õ•â±î¨¨Ï(ÄÄÄÅıÙ§Ï(ÄÄÄÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù…ïÕ’±–µçΩ’π–ú§π—ï·—Ωπ—ïπ–ÄÙÅŸ•Õ•â±îÄ¨ÄúÅ¡…Ωë’≠—ï»úÏ(ÄÅıÙ((ÄÄººÄâMΩ…—•µïπ—ï–ÅôΩ…≠±Ö…–àÅÕ•πîÄâMîÅ`ÉäHàµ≠Ω…–Å±ïπ≠ï»Å—•∞(ÄÄººÄåÒ≠Ö—ïùΩ…§µÕ±’ú¯Ä¥¥ÅÕÖµµîÅô•±—ï»µ…ÖêÅÕΩ¥ÅÖ±±ï…ïëîÅô•ππïÃÅŸïê(ÄÄººÅ¡…Ωë’≠—±•Õ—ï∏∞Å•≠≠îÅï∏Åïùï∏ÅÕ•ëî∏Å-´·…ïÃÅ√îÅ±ÖÕ—•πúÅ°Ÿ•ÃÅÕ•ëï∏Éï¡πïÃ(ÄÄººÅë•…ï≠—îÅµïêÅï–ÅÕ±•≠–Å°ÖÕ†Ä°òπï≠Ã∏Åô…ÑÅï∏Åï≠Õ—ï…∏Å±ïπ≠î§∏(ÄÅçΩπÕ–Å•π•—•Ö±Ö—ïùΩ…‰ÄÙÅ›•πëΩ‹π±ΩçÖ—•Ω∏π°ÖÕ†π…ï¡±Öçî†úåú∞Äúú§Ï(ÄÅ•òÄ°•π•—•Ö±Ö—ïùΩ…‰ÄòòÅô•±—ï…IΩ‹π≈’ï…ÂMï±ïç—Ω»†úπç°•¡mëÖ—ÑµçÖ—ïùΩ…‰ÙàúÄ¨Å•π•—•Ö±Ö—ïùΩ…‰Ä¨Äúâtú§§ÅÌÏ(ÄÄÄÅÖ¡¡±Â	…Öπë•±—ï»°•π•—•Ö±Ö—ïùΩ…‰§Ï(ÄÅıÙ(ÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπâ…ÖπêµÕΩ…—•µïπ–µçÖ…êú§πôΩ…Öç†°çÖ…êÄÙ¯ÅÌÏ(ÄÄÄÅçÖ…êπÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅÖ¡¡±Â	…Öπë•±—ï»°çÖ…êπëÖ—ÖÕï–πçÖ—ïùΩ…‰§Ï(ÄÄÄÄÄÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…Ωë’≠—ï»ú§πÕç…Ω±±%π—ΩY•ï‹°ÌÏÅâï°ÖŸ•Ω»ËÄùÕµΩΩ—†ú∞Åâ±Ωç¨ËÄùÕ—Ö…–úÅıÙ§Ï(ÄÄÄÅıÙ§Ï(ÄÅıÙ§Ï((ÄÅô•±—ï…IΩ‹πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞ÅîÄÙ¯ÅÌÏ(ÄÄÄÅçΩπÕ–Åâ—∏ÄÙÅîπ—Ö…ùï–πç±ΩÕïÕ–†úπç°•¿ú§Ï(ÄÄÄÅ•òÄ†Öâ—∏§Å…ï—’…∏Ï(ÄÄÄÅÖ¡¡±Â	…Öπë•±—ï»°â—∏πëÖ—ÖÕï–πçÖ—ïùΩ…‰§Ï(ÄÅıÙ§Ï(ΩÕç…•¡–¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}µÖπ’ôÖç—’…ï…}¡Öùî°µÖπ’ôÖç—’…ï…}Õ±’úËÅÕ—»∞Åâ…Öπë}çΩ’π—ÃËÅë•ç—mÕ—»∞Å•π—t∞Åâ…Öπë}±Öâï±ÃËÅë•ç—mÕ—»∞ÅÕ—…t∞Å¡…Ωë’ç—ÃËÅ±•Õ—më•ç—t∞ÅçÖ—ïùΩ…•ïÃËÅë•ç–∞Å¡…Ωë’ç—}ôÖµ•±•ïÃËÅ±•Õ—më•ç—t∞ÅπΩ‹ËÅëÖ—ï—•µî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâùï∏ÅÕ•ëîÅ¡ï»Å¡…Ωë’Õïπ–Ä†Ω¡…Ωë’Õïπ–ΩÌÕ±’ùÙº§Ä¥¥Å%--Åëï–ÅÕÖµµîÅÕΩ¥Åï∏(ÄÄÄÅµï…≠îµÕ•ëîÄ†Ωµï…≠îΩÌÕ±’ùÙº§ËÅï–Åµï…≠îÅï»Åï—–Å¡…Ωë’≠—πÖŸ∏Ä°	•Ωô•π•—‰§∞Åï∏(ÄÄÄÅ¡…Ωë’Õïπ–Å≠Ö∏ÅÕ”îÅâÖ¨Åô±ï…îÅµï…≠ï»Ä°ΩΩ¡ï…Y•Õ•Ω∏Ä¥¯Å	•Ωô•π•—‰∞ÅA…Ωç±ïÖ»∞(ÄÄÄÅ5ÂÖ‰∞Ä∏∏∏§∏ÅΩ…∑ï±ï–Åï»Åï∏Åï≠—î∞Å’—üïïπëîÅ±ïπ≠îÅ—•∞Å¡…Ωë’Õïπ—ïπÃÅïùï∏(ÄÄÄÅÕ•ëîÄ°•πùï∏Å≠Ωπ≠’……ïπ–Å§Åëï–ÅπΩ…Õ≠îÅµÖ…≠ïëï–Å°Ö»Åëï——î∞ÅÕîÅ…ïÕïÖ…ç†(ÄÄÄÄ»¿»ÿ¥¿‡¥ƒ‡§Å¡±’ÕÃÅΩ…•ù•πÖ∞Å—ï≠Õ–ÅΩ¥Å¡…Ωë’Õïπ—ï∏Ä¥¥Å•≠≠îÅâÖ…îÅï∏(ÄÄÄÅŸ•ëï…ïÕïπë•πú∏Åâ…Öπë}çΩ’π—ÃΩâ…Öπë}±Öâï±ÃÅ≠Ωµµï»Åô…ÑÅëï∏ÅÕÖµµî(ÄÄÄÅ’—…ïùπ•πùï∏ÅÕΩ¥Å…ïπëï…}°Ωµï}¡ÖùîÅÖ±±ï…ïëîÅù´·»∞ÅÕïπë–Å•π∏ÅÕ±•¨ÅÖ–Åëïππî(ÄÄÄÅô’π≠Õ©Ωπï∏Å•≠≠îÅ—…ïπùï»ÉîÅŸ•—îÅπΩîÅΩ¥Å≠Ö—Ö±ΩúµÕ—…’≠—’…ï∏ÅÕï±ÿ∏ààà(ÄÄÄÅëÖ—ÑÄÙÅ59UQUIIMmµÖπ’ôÖç—’…ï…}Õ±’ùt(ÄÄÄÅπÖµîÄÙÅëÖ—ÖlâπÖµîât((ÄÄÄÅΩ›π}â…Öπë}Õ±’ùÃÄÙÅmÃÅôΩ»ÅÃÅ•∏ÅëÖ—Ölââ…Öπë}Õ±’ùÃâtÅ•òÅÃÅ•∏Åâ…Öπë}çΩ’π—Õt((ÄÄÄÅëïòÅ…ïπëï…}â…Öπë}çÖ…ê°Õ±’úËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ±Öâï∞ÄÙÅâ…Öπë}±Öâï±ÕmÕ±’ùt(ÄÄÄÄÄÄÄÅçΩ’π–ÄÙÅâ…Öπë}çΩ’π—ÕmÕ±’ùt(ÄÄÄÄÄÄÄÅπ}±Öâï∞ÄÙÄâ¡…Ωë’≠–àÅ•òÅçΩ’π–ÄÙÙÄƒÅï±ÕîÄâ¡…Ωë’≠—ï»à(ÄÄÄÄÄÄÄÅï·—…Ö}ç±Ã∞ÅâÖëùï}çΩπ—ïπ–ÄÙÅ}â…Öπë}âÖëùî°Õ±’ú∞Å±Öâï∞§(ÄÄÄÄÄÄÄÅâÖëùï}ç±ÖÕÃÄÙÄ†ââ…ÖπêµçÖ…êµâÖëùîÄàÄ¨Åï·—…Ö}ç±Ã§πÕ—…•¿†§(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒÑÅç±ÖÕÃÙââ…ÖπêµçÖ…êàÅ°…ïòÙàΩµï…≠îΩÌïÕçÖ¡î°Õ±’ú•Ùºà¯(ÄÄÒë•ÿÅç±ÖÕÃÙâÌâÖëùï}ç±ÖÕÕÙà˘ÌâÖëùï}çΩπ—ïπ—ÙΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµ•πôºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµπÖµîà˘ÌïÕçÖ¡î°±Öâï∞•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµçΩ’π–à˘ÌçΩ’π—ÙÅÌπ}±Öâï±ÙΩë•ÿ¯(ÄÄΩë•ÿ¯(ΩÑ¯ààà((ÄÄÄÅ¡…Ωë’ç—ÃÄÙÅm¿ÅôΩ»Å¿Å•∏Å¡…Ωë’ç—ÃÅ•òÅ¡lââ…Öπë}Õ±’úâtÅ•∏ÅΩ›π}â…Öπë}Õ±’ùÕt(ÄÄÄÅâÂ}•êÄÙÅÌ¡lâ•êâtËÅ¿ÅôΩ»Å¿Å•∏Å¡…Ωë’ç—ÕÙ(ÄÄÄÅÕ’µµÖ…•ïÃÄÙÅmt(ÄÄÄÅôΩ»ÅôÖµ•±‰Å•∏Å¡…Ωë’ç—}ôÖµ•±•ïÃË(ÄÄÄÄÄÄÄÅµïµâï…ÃÄÙÅmâÂ}•ëmµ•ëtÅôΩ»Åµ•êÅ•∏ÅôÖµ•±Âlâµïµâï…}•ëÃâtÅ•òÅµ•êÅ•∏ÅâÂ}•ët(ÄÄÄÄÄÄÄÅ•òÅ±ï∏°µïµâï…Ã§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅÕ’µµÖ…‰ÄÙÅ}â…Öπë}ôÖµ•±Â}Õ’µµÖ…‰°ôÖµ•±‰∞Åµïµâï…Ã∞ÅçÖ—ïùΩ…•ïÃ∞ÅπΩ‹§(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅÕ’µµÖ…‰Ë(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ’µµÖ…•ïÃπÖ¡¡ïπê°Õ’µµÖ…‰§(ÄÄÄÅÕ’µµÖ…•ïÃπÕΩ…–°≠ï‰ı±ÖµâëÑÅ‡ËÅ·lâµ•π}¡…•çîâtÅΩ»Åô±ΩÖ–†â•πòà§§(ÄÄÄÅçÖ…ëÃÄÙÅmt(ÄÄÄÅôΩ»Å¡…Ωë’ç–Å•∏Å¡…Ωë’ç—ÃË(ÄÄÄÄÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅŸÖ±•êÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âtÅÖπêÅπΩ–ÅΩlâ•Õ}Õ—Ö±îâut(ÄÄÄÄÄÄÄÅ±Ω›ïÕ–ÄÙÅµ•∏°ŸÖ±•ê∞Å≠ï‰ı±ÖµâëÑÅºËÄ°Ωlâ¡…•çï}πΩ¨ât∞ÅΩlâ—Ω—Ö∞ât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄÄÄÄÅçÖ…êÄÙÅ}…ïπëï…}¡…Ωë’ç—}—•±î†(ÄÄÄÄÄÄÄÄÄÄÄÅ°…ïòıòúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ¡…Ωë’ç—lââ…Öπë}Õ±’úâuÙΩÌ¡…Ωë’ç—lâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÅπÖµîı¡…Ωë’ç—lâπÖµîât∞Å•µÖùï}’…∞ı}¡…Ωë’ç—}•µÖùî°¡…Ωë’ç–§∞(ÄÄÄÄÄÄÄÄÄÄÄÅôÖ±±âÖç≠}•π•—•Ö±Ãı¡…Ωë’ç—lââ…Öπë}±Öâï∞âulË…tπ’¡¡ï»†§∞(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ıçÖ—ïùΩ…•ïÕm¡…Ωë’ç—lâçÖ—ïùΩ…Â}Õ±’úâuulâ±Öâï∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕïçΩπëÖ…Â}±•πï}°—µ∞ıòúÒÑÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµµÖπ’ôÖç—’…ï»àÅ°…ïòÙàΩµï…≠îΩÌïÕçÖ¡î°¡…Ωë’ç—lââ…Öπë}Õ±’úât•Ùºà˘ÌïÕçÖ¡î°¡…Ωë’ç—lââ…Öπë}±Öâï∞ât•ÙΩÑ¯ú∞(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ïÕ–ı±Ω›ïÕ–∞ÅΩ—°ï…}çΩ’π–ı±ï∏°Ωôôï…Ã§¥ƒ∞ÅçΩµ¡Ö…•ÕΩπ}Ωôôï…ÃıΩôôï…Ã∞(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅçÖ…ëÃπÖ¡¡ïπê†°±Ω›ïÕ—lâ¡…•çï}πΩ¨âtÅ•òÅ±Ω›ïÕ–Åï±ÕîÅô±ΩÖ–†â•πòà§∞ÅçÖ…ê§§(ÄÄÄÅ¡…Ωë’ç—}çÖ…ëÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°çÖ…êÅôΩ»Å|∞ÅçÖ…êÅ•∏ÅÕΩ…—ïê°çÖ…ëÃ∞Å≠ï‰ı±ÖµâëÑÅ‡ËÅ·l¡t§§(ÄÄÄÅÕï…•ïÕ}°—µ∞ÄÙÄ†úÒÕïç—•Ω∏Åç±ÖÕÃÙâµÖπ’ôÖç—’…ï»µÕï…•ïÃà¯Ò†»˘A…Ωë’≠—Õï…•ï»Ω†»¯Òë•ÿÅç±ÖÕÃÙââ…ÖπêµÕï…•îµù…•êà¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄ¨Äààπ©Ω•∏°â…Öπë}Õï…•ïÕ}çÖ…ê°Õ’µµÖ…‰∞Å§§ÅôΩ»Å§∞ÅÕ’µµÖ…‰Å•∏Åïπ’µï…Ö—î°Õ’µµÖ…•ïÃ§§(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄ¨ÄúΩë•ÿ¯ΩÕïç—•Ω∏¯ú§Å•òÅÕ’µµÖ…•ïÃÅï±ÕîÄàà((ÄÄÄÅâ…Öπë}çÖ…ëÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°…ïπëï…}â…Öπë}çÖ…ê°Ã§ÅôΩ»ÅÃÅ•∏ÅΩ›π}â…Öπë}Õ±’ùÃ§(ÄÄÄÅ—Ω—Ö±}¡…Ωë’ç—ÃÄÙÅÕ’¥°â…Öπë}çΩ’π—ÕmÕtÅôΩ»ÅÃÅ•∏ÅΩ›π}â…Öπë}Õ±’ùÃ§(ÄÄÄÅâ…Öπë}πÖµïÃÄÙÅmâ…Öπë}±Öâï±ÕmÕtÅôΩ»ÅÃÅ•∏ÅΩ›π}â…Öπë}Õ±’ùÕt(ÄÄÄÅâ…ÖπëÕ}—ï·–ÄÙÅâ…Öπë}πÖµïÕl¡tÅ•òÅ±ï∏°â…Öπë}πÖµïÃ§ÄÙÙÄƒÅï±ÕîÄà∞Äàπ©Ω•∏°â…Öπë}πÖµïÕlË¥≈t§Ä¨ÄàÅΩúÄàÄ¨Åâ…Öπë}πÖµïÕl¥≈t((ÄÄÄÅµï—Ö}ëïÕç…•¡—•Ω∏ÄÙÅòâ=¥ÅÌπÖµïÙ∞Å¡…Ωë’Õïπ—ï∏ÅâÖ¨ÅÌâ…ÖπëÕ}—ï·—ÙÉäLÅÕΩ¥Å¡…Ωë’Õïπ–∞Å—ï≠πΩ±Ωù§ÅΩúÅ±ïπ≠îÅ—•∞Åëï…ïÃÅΩôô•Õ•ï±±îÅπï——Õ•ëî∏à((ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°πÖµî•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩ¡…Ωë’Õïπ–ΩÌµÖπ’ôÖç—’…ï…}Õ±’ùÙºâıÙ(ÄÄÄÅuıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ=…ùÖπ•ÈÖ—•Ω∏à∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°πÖµî•Ùà∞Äâ’…∞àËÄâÌ}©ÕΩπ}Õ—»°ëÖ—ÖlùΩôô•ç•Ö±}’…∞ùt•ÙâıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°πÖµî•ÙÉäLÅA…Ωë’Õïπ—ï∏ÅâÖ¨ÅÌïÕçÖ¡î°â…ÖπëÕ}—ï·–•ÙÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°µï—Ö}ëïÕç…•¡—•Ω∏•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩ¡…Ωë’Õïπ–ΩÌµÖπ’ôÖç—’…ï…}Õ±’ùÙºà¯)Ì}Ωù}µï—Ñ°òùÌπÖµïÙÉäLÅA…Ωë’Õïπ—ï∏ÅâÖ¨ÅÌâ…ÖπëÕ}—ï·—Ùú∞Åµï—Ö}ëïÕç…•¡—•Ω∏∞ÅòùÌ	M}UI1ÙΩ¡…Ωë’Õïπ–ΩÌµÖπ’ôÖç—’…ï…}Õ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯(ÒÕ—Â±î˘ÌM!I}MQe1Ù)Ì	I9}A}MQe1Ù(πµÖπ’ôÖç—’…ï»µÕï…•ïÃÅÌÏÅµÖ…ù•∏ËÄÃŸ¡‡Ä¿ÏÅıÙ(πâ…Öπêµù…•êÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†»∞Ä≈ô»§ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(πâ…ÖπêµçÖ…êÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµ•∏µ›•ë—†ËÄ¿ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ—¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πâ…ÖπêµçÖ…êÈ°ΩŸï»ÅÌÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(πâ…ÖπêµçÖ…êµâÖëùîÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄÃŸ¡‡ÏÅ°ï•ù°–ËÄÃŸ¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅıÙ(πâ…ÖπêµçÖ…êµ•πôºÅÌÏÅµ•∏µ›•ë—†ËÄ¿ÏÅıÙ(πâ…ÖπêµçÖ…êµπÖµîÅÌÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏»‘ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅ—ï·–µΩŸï…ô±Ω‹ËÅï±±•¡Õ•ÃÏÅ›°•—îµÕ¡ÖçîËÅπΩ›…Ö¿ÏÅıÙ(πâ…ÖπêµçÖ…êµçΩ’π–ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‘ÿ¡¡‡§ÅÌÏÄπâ…Öπêµù…•êÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†Ã∞Ä≈ô»§ÏÅıÙÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°πÖµî•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘A…Ωë’Õïπ–Ωë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°πÖµî•ÙΩ†ƒ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒÕïç—•Ω∏Åç±ÖÕÃÙâµÖπ’ôÖç—’…ï»µ¡…Ωë’ç—Ãà¯(ÄÄÄÄÒ†»˘±±îÅ¡…Ωë’≠—ï»Åô…ÑÅÌïÕçÖ¡î°πÖµî•ÙÄ°Ì±ï∏°¡…Ωë’ç—Ã•Ù§Ω†»¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµù…•êà˘Ì¡…Ωë’ç—}çÖ…ëÕ}°—µ±ÙΩë•ÿ¯(ÄÄΩÕïç—•Ω∏¯((ÄÅÌÕï…•ïÕ}°—µ±Ù((ÄÄÒë•ÿÅÕ—Â±îÙâµÖ‡µ›•ë—†Ë‹»¡¡‡ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÄÅÌëÖ—ÖlâëïÕç…•¡—•Ωπ}°—µ∞âuÙ(ÄÄΩë•ÿ¯((ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë»¡¡‡Ä¿ÄÃ…¡‡Ïà¯(ÄÄÄÄÒÑÅ°…ïòÙâÌïÕçÖ¡î°ëÖ—ÖlùΩôô•ç•Ö±}’…∞ùt•ÙàÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»àÅÕ—Â±îÙâôΩπ–µ›ï•ù°–Ëÿ¿¿ÌçΩ±Ω»ÈŸÖ»†¥µâ±’îµëÖ…¨§Ïà¯(ÄÄÄÄÄÅ=ôô•Õ•ï±∞Åπï——Õ•ëîËÅÌïÕçÖ¡î°ëÖ—ÖlùΩôô•ç•Ö±}’…±}±Öâï∞ùt•ÙÉä\(ÄÄÄÄΩÑ¯(ÄÄΩ¿¯((ÄÄÒ†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏≈…ï¥ÌµÖ…ù•∏Ë¿Ä¿ÄƒŸ¡‡Ïà¯(ÄÄÄÅÌïÕçÖ¡î°πÖµî•ıÃÅµï…≠ï»Å°ΩÃÅΩÕÃÄ°Ì—Ω—Ö±}¡…Ωë’ç—ÕÙÅ¡…Ωë’≠—ï»Å—Ω—Ö±–§(ÄÄΩ†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµù…•êà¯(ÄÄÄÅÌâ…Öπë}çÖ…ëÕ}°—µ±Ù(ÄÄΩë•ÿ¯((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îàÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËÃ…¡‡Ïà¯(ÄÄÄÅ-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—îÅΩúÅ°Ö»Å•πùï∏ÅÖŸ—Ö±îÅµïê(ÄÄÄÅÌïÕçÖ¡î°πÖµî•Ù∏Å1ïπ≠ï∏Å—•∞Åëï…ïÃÅπï——Õ•ëîÅΩŸï»Åï»Å≠’∏Åï∏Å•πôΩ…µÖ—•ÿÅ°ïπŸ•Õπ•πú∞Å•≠≠î(ÄÄÄÅï∏ÅÖππΩπÕîÅï±±ï»Åï–ÅÕÖµÖ…âï•ê∏(ÄÄΩ¿¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(((åÅï±–Åµï±±Ω¥ÅôΩ…Õ•ëï∏ÅΩúÅù’•ëîµÕ•ëïπîÄ†»¿»ÿ¥¿‰¥»‘§ËÅù’•ëîµÕ•ëïπîÅõï»ÅµïÕ–(åÅΩ…ùÖπ•Õ¨Å—…Öô•≠¨∞Åµï∏ÅµÖπùîÅôΩ…±Ö—ï»ÅÕ•ëï∏Å…ï—–Åï——ï»ÉîÅ°ÑÅ±ïÕ–ÅÕŸÖ…ï–Ä¥¥(åÅœ·≠ïâΩ≠Õï∏Åù•»Åëï¥Åï∏ÅπÖ—’…±•úÅπïÕ—îÅ°Öπë±•πúÄ†âô•π∏Å±ÖŸïÕ—îÅ¡…•ÃÅ√î(åÅ±•πÕïπîÅµ•πîà§Å’—ï∏ÉîÅ±•ùùîÅ§ÅŸï•ï∏ÅôΩ»ÅÕï±ŸîÅù’•ëï∏∏)19M}MI!}MQe1ÄÙÄààà(πÕïÖ…ç†µ…Ω‹ÅÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅÙ(πÕïÖ…ç†µ•çΩ∏ÅÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ±ïô–ËÄƒ·¡‡ÏÅ—Ω¿ËÄ‘¿îÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¥‘¿î§ÏÅ›•ë—†ËÄ»¡¡‡ÏÅ°ï•ù°–ËÄ»¡¡‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ¡Ω•π—ï»µïŸïπ—ÃËÅπΩπîÏÅÙ(πÕïÖ…ç†µ•π¡’–ÅÏÅ›•ë—†ËÄƒ¿¿îÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅ¡Öëë•πúËÄƒŸ¡‡Äƒ¿¡¡‡ÄƒŸ¡‡Ä–·¡‡ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ—…ÖπÕ•—•Ω∏ËÅâΩ‡µÕ°ÖëΩ‹Ä¿∏ƒ’Ã∞ÅâΩ…ëï»µçΩ±Ω»Ä¿∏ƒ’ÃÏÅÙ(πÕïÖ…ç†µ•π¡’–È°ΩŸï»ÅÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’îµëÖ…¨§ÏÅÙ(πÕïÖ…ç†µ•π¡’–ÈôΩç’ÃÅÏÅΩ’—±•πîËÅπΩπîÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’îµëÖ…¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä¿Ä¿Ä—¡‡ÅŸÖ»†¥µâ±’îµ—•π–§ÏÅÙ(πÕïÖ…ç†µ…Ω‹ÈôΩç’Ãµ›•—°•∏ÄπÕïÖ…ç†µ•çΩ∏ÅÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅÙ(πÕïÖ…ç†µâ—∏ÅÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ…•ù°–ËÄŸ¡‡ÏÅ—Ω¿ËÄŸ¡‡ÏÅâΩ——Ω¥ËÄŸ¡‡ÏÅ¡Öëë•πúËÄ¿Ä»¡¡‡ÏÅâΩ…ëï»ËÅπΩπîÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’î§ÏÅçΩ±Ω»ËÅ›°•—îÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅ—…ÖπÕ•—•Ω∏ËÅâÖç≠ù…Ω’πêµçΩ±Ω»Ä¿∏ƒ’ÃÏÅÙ(πÕïÖ…ç†µâ—∏È°ΩŸï»ÅÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµëÖ…¨§ÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•ΩπÃÅÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ—Ω¿ËÅçÖ±å†ƒ¿¿îÄ¨ÄŸ¡‡§ÏÅ±ïô–ËÄ¿ÏÅ…•ù°–ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Äƒ…¡‡Ä»·¡‡Å…ùâÑ†ƒƒ∞ÄÃ‹∞Äÿ‰∞Ä¿∏ƒ–§ÏÅµÖ‡µ°ï•ù°–ËÄÃ‡¡¡‡ÏÅΩŸï…ô±Ω‹µ‰ËÅÖ’—ºÏÅËµ•πëï‡ËÄ»¿ÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•Ω∏ÅÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅ¡Öëë•πúËÄƒ¡¡‡Äƒ—¡‡ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ…ëï»µâΩ——Ω¥ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•Ω∏È±ÖÕ–µç°•±êÅÏÅâΩ…ëï»µâΩ——Ω¥ËÅπΩπîÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•Ω∏È°ΩŸï»ÅÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•Ω∏Äπ¡…Ωë’ç–µ—°’µàÅÏÅ›•ë—†ËÄÃŸ¡‡ÏÅ°ï•ù°–ËÄÃŸ¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•Ω∏µπÖµîÅÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅÙ(πÕïÖ…ç†µÕ’ùùïÕ—•Ω∏µµï—ÑÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‹’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅÙ(πÕïÖ…ç†µπºµµÖ—ç†ÅÏÅ¡Öëë•πúËÄƒ—¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡—…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅÙ(πù’•ëîµç—ÑÅÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúËÄƒ·¡‡Äƒ·¡‡ÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄ»…¡‡Ä¿ÏÅÙ(πù’•ëîµç—ÑµçΩµ¡Öç–ÅÏÅ¡Öëë•πúËÄƒ—¡‡ÄƒŸ¡‡ÏÅÙ(πù’•ëîµç—Ñµ—•—±îÅÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅµÖ…ù•∏ËÄ¿Ä¿Ä—¡‡ÏÅÙ(πù’•ëîµç—ÑµçΩµ¡Öç–Äπù’•ëîµç—Ñµ—•—±îÅÏÅµÖ…ù•∏µâΩ——Ω¥ËÄƒ¡¡‡ÏÅÙ(πù’•ëîµç—Ñµ—ï·–ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ…¡‡ÏÅÙ(πù’•ëîµç—ÑÄπÕïÖ…ç†µ•π¡’–ÅÏÅôΩπ–µÕ•ÈîËÄ≈…ï¥ÏÅ¡Öëë•πúËÄƒ—¡‡Ä‰…¡‡Äƒ—¡‡Ä–Ÿ¡‡ÏÅÙ(πù’•ëîµç—ÑÄπÕïÖ…ç†µ•çΩ∏ÅÏÅ±ïô–ËÄƒŸ¡‡ÏÅ›•ë—†ËÄƒ·¡‡ÏÅ°ï•ù°–ËÄƒ·¡‡ÏÅÙ(πù’•ëîµç—Ñµ±•π≠ÃÅÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄŸ¡‡Ä·¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ…¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅÙ(πù’•ëîµç—Ñµ±•π≠ÃÅÑÅÏÅ¡Öëë•πúËÄ—¡‡Äƒ¡¡‡ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‰‰Â¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅÙ(πù’•ëîµç—Ñµ±•π≠ÃÅÑÈ°ΩŸï»ÅÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅÙ(ààà()19M}MI!})LÄÙÄààà(°ô’πç—•Ω∏Ä†§ÅÏ(ÄÄººÅ-´·…ïÃÅô…ÑÅQ=A	I}!Q50∞ÅÕΩ¥Å±•ùùï»Å—•ë±•úÅ§ÄÒâΩë‰¯Ä¥¥ÅaHÅôΩ…Õ•ëïπÃ(ÄÄººÅïùï∏ÄπÕïÖ…ç†µ…Ω‹Ä°°ï…ºµœ·≠ïôï±—ï–§Åï»Å¡Ö…Õï–Å•π∏Å§Å=4µï∏Å√îÅÕ•ëï»(ÄÄººÅÕΩ¥Å°Ö»Åï∏ÅÕ±•¨Åï≠Õ—…ÑÅ…Öê∏ÅU—ï∏ÅëïππîÅ=5Ωπ—ïπ—1ΩÖëïêµÕ©ï≠≠ï∏(ÄÄººÅ…ï—’…πï…—îÅÕç…•¡—ï–Å—•ë±•úÄ°…Ω›Ãπ±ïπù—†ÄÙÙÙÄ¿Å√îÅëï–Å—•ëÕ¡’π≠—ï–Åëï–(ÄÄººÅ≠´·…—î§ÅΩúÅâÖπë–Å1I$ÅπΩï∏ÅïŸïπ–µ±Â——ï…îÅ√îÅôΩ…Õ•ëïπÃÅœ·≠ïôï±–Ä¥¥(ÄÄººÅΩ¡¡ëÖùï–Ä»¿»ÿ¥¿‰¥»‹Ä°-Ö§ËÄâœ·≠ïô’π≠Õ©Ω∏ÅŸ•…≠ï»Å•≠≠îÅªîÑÅ√î(ÄÄººÅÕ—Ö…—Õ•ëï∏à§∏ÅM•ëï»Åëï»ÄπÕïÖ…ç†µ…Ω‹ÅÖ±±ï…ïëîÅô•ππïÃÅªï»ÅÕç…•¡—ï–(ÄÄººÅ≠´·…ï»Ä°…ïÖëÂM—Ö—îÄÑÙÙÄù±ΩÖë•πúú§Å≠´·…ï»Å•π•–†§Å’µ•ëëï±âÖ…–ÅÕΩ¥Åõ·»∏(ÄÅô’πç—•Ω∏Å•π•–†§ÅÏ(ÄÅŸÖ»Å…Ω›ÃÄÙÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπÕïÖ…ç†µ…Ω‹ú§Ï(ÄÅ•òÄ†Ö…Ω›Ãπ±ïπù—†§Å…ï—’…∏Ï((ÄÄººÅΩ…Õ•ëï∏Å°Ö»Å•πëï≠Õï∏Å•ππïâÂùêÅÕΩ¥ÅÕ≠©’±–Å)M=8ÏÅù’•ëîµÕ•ëïπîÅ°ïπ—ï»Åëï∏(ÄÄººÅõ·…Õ–Åªï»ÅπΩï∏ÅôÖ≠—•Õ¨ÅôΩ≠’Õï…ï»Åœ·≠ïôï±—ï–Ä°°Ω±ëï»Åù’•ëîµ!Q50µï∏Å±ï—–§∏(ÄÅŸÖ»ÅëÖ—ÖA…Ωµ•ÕîÄÙÅπ’±∞Ï(ÄÅô’πç—•Ω∏Å±ΩÖëÖ—Ñ†§ÅÏ(ÄÄÄÅ•òÄ°ëÖ—ÖA…Ωµ•Õî§Å…ï—’…∏ÅëÖ—ÖA…Ωµ•ÕîÏ(ÄÄÄÅŸÖ»Å•π±•πïA…Ωë’ç—ÃÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…Ωë’ç–µÕïÖ…ç†µëÖ—Ñú§Ï(ÄÄÄÅ•òÄ°•π±•πïA…Ωë’ç—Ã§ÅÏ(ÄÄÄÄÄÅŸÖ»Å•π±•πï1Öâï±ÃÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…•ŸÖ—îµ±Öâï∞µÕïÖ…ç†µëÖ—Ñú§Ï(ÄÄÄÄÄÅëÖ—ÖA…Ωµ•ÕîÄÙÅA…Ωµ•Õîπ…ïÕΩ±Ÿî†(ÄÄÄÄÄÄÄÅ)M=8π¡Ö…Õî°•π±•πïA…Ωë’ç—Ãπ—ï·—Ωπ—ïπ–§πçΩπçÖ–°•π±•πï1Öâï±ÃÄ¸Å)M=8π¡Ö…Õî°•π±•πï1Öâï±Ãπ—ï·—Ωπ—ïπ–§ÄËÅmt§(ÄÄÄÄÄÄ§Ï(ÄÄÄÅÙÅï±ÕîÅÏ(ÄÄÄÄÄÅëÖ—ÖA…Ωµ•ÕîÄÙÅôï—ç††úΩëÖ—ÑΩÕïÖ…ç†µ•πëï‡π©ÕΩ∏ú§(ÄÄÄÄÄÄÄÄπ—°ï∏°ô’πç—•Ω∏Ä°»§ÅÏÅ…ï—’…∏Å»π©ÕΩ∏†§ÏÅÙ§(ÄÄÄÄÄÄÄÄπçÖ—ç†°ô’πç—•Ω∏Ä†§ÅÏÅëÖ—ÖA…Ωµ•ÕîÄÙÅπ’±∞ÏÅ…ï—’…∏ÅmtÏÅÙ§Ï(ÄÄÄÅÙ(ÄÄÄÅ…ï—’…∏ÅëÖ—ÖA…Ωµ•ÕîÏ(ÄÅÙ((ÄÅô’πç—•Ω∏ÅïÕå°Ã§ÅÏ(ÄÄÄÅ…ï—’…∏ÅM—…•πú°Ã§π…ï¡±Öçî†Ωlò¯àùtΩú∞Åô’πç—•Ω∏Ä°å§ÅÏ(ÄÄÄÄÄÅ…ï—’…∏ÅÏúòúËÄúôÖµ¿Ïú∞ÄúúËÄúô±–Ïú∞Äú¯úËÄúôù–Ïú∞ÄúàúËÄúô≈’Ω–Ïú∞ÄàúàËÄúòåÃ‰ÏùımçtÏ(ÄÄÄÅÙ§Ï(ÄÅÙ((ÄÅô’πç—•Ω∏Å—…Öç¨°…Ω‹∞ÅπÖµî∞ÅÕΩ’…çî§ÅÏ(ÄÄÄÅŸÖ»Åù’•ëîÄÙÅ…Ω‹πùï———…•â’—î†ùëÖ—Ñµù’•ëîú§Ï(ÄÄÄÅ•òÄ†Öù’•ëî§Å…ï—’…∏Ï(ÄÄÄÅ›•πëΩ‹πëÖ—Ö1ÖÂï»ÄÙÅ›•πëΩ‹πëÖ—Ö1ÖÂï»ÅÒÅmtÏ(ÄÄÄÅ›•πëΩ‹πëÖ—Ö1ÖÂï»π¡’Õ†°ÌïŸïπ–ËÄùù’•ëï}ÕïÖ…ç°}ç±•ç¨ú∞Åù’•ëîËÅù’•ëî∞Å¡…Ωë’ç–ËÅπÖµî∞ÅÕΩ’…çîËÅÕΩ’…çïÙ§Ï(ÄÅÙ((ÄÅ…Ω›ÃπôΩ…Öç†°ô’πç—•Ω∏Ä°…Ω‹§ÅÏ(ÄÄÄÅŸÖ»Å•π¡’–ÄÙÅ…Ω‹π≈’ï…ÂMï±ïç—Ω»†úπÕïÖ…ç†µ•π¡’–ú§Ï(ÄÄÄÅŸÖ»ÅÕ’ùùïÕ—•ΩπÃÄÙÅ…Ω‹π≈’ï…ÂMï±ïç—Ω»†úπÕïÖ…ç†µÕ’ùùïÕ—•ΩπÃú§Ï(ÄÄÄÅŸÖ»Åâ’——Ω∏ÄÙÅ…Ω‹π≈’ï…ÂMï±ïç—Ω»†úπÕïÖ…ç†µâ—∏ú§Ï((ÄÄÄÅô’πç—•Ω∏Å°•ëî†§ÅÏÅÕ’ùùïÕ—•ΩπÃπÕ—Â±îπë•Õ¡±Ö‰ÄÙÄùπΩπîúÏÅÕ’ùùïÕ—•ΩπÃπ•ππï…!Q50ÄÙÄúúÏÅÙ((ÄÄÄÅô’πç—•Ω∏Å…ïπëï»°ƒ§ÅÏ(ÄÄÄÄÄÅ•òÄ†Öƒ§ÅÏÅ°•ëî†§ÏÅ…ï—’…∏ÏÅÙ(ÄÄÄÄÄÅ±ΩÖëÖ—Ñ†§π—°ï∏°ô’πç—•Ω∏Ä°Ö±∞§ÅÏ(ÄÄÄÄÄÄÄÅ•òÄ°•π¡’–πŸÖ±’îπ—…•¥†§π—Ω1Ω›ï…ÖÕî†§ÄÑÙÙÅƒ§Å…ï—’…∏Ï(ÄÄÄÄÄÄÄÅŸÖ»ÅµÖ—ç°ïÃÄÙÅÖ±∞πô•±—ï»°ô’πç—•Ω∏Ä°•—ï¥§ÅÏÅ…ï—’…∏Å•—ï¥πÕïÖ…ç†π•πëï·=ò°ƒ§ÄÑÙÙÄ¥ƒÏÅÙ§πÕ±•çî†¿∞Ä‡§Ï(ÄÄÄÄÄÄÄÅ•òÄ°µÖ—ç°ïÃπ±ïπù—†ÄÙÙÙÄ¿§ÅÏ(ÄÄÄÄÄÄÄÄÄÅÕ’ùùïÕ—•ΩπÃπ•ππï…!Q50ÄÙÄúÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µπºµµÖ—ç†à˘%πùï∏Å—…ïôò∏ÅAÀ·ÿÅï–ÅÖππï–Åµï…≠îÅï±±ï»Å¡…Ωë’≠—πÖŸ∏∏Ωë•ÿ¯úÏ(ÄÄÄÄÄÄÄÄÄÅÕ’ùùïÕ—•ΩπÃπÕ—Â±îπë•Õ¡±Ö‰ÄÙÄùâ±Ωç¨úÏ(ÄÄÄÄÄÄÄÄÄÅ…ï—’…∏Ï(ÄÄÄÄÄÄÄÅÙ(ÄÄÄÄÄÄÄÅÕ’ùùïÕ—•ΩπÃπ•ππï…!Q50ÄÙÅµÖ—ç°ïÃπµÖ¿°ô’πç—•Ω∏Ä°•—ï¥§ÅÏ(ÄÄÄÄÄÄÄÄÄÅŸÖ»Å—°’µàÄÙÅ•—ï¥π•µÖùî(ÄÄÄÄÄÄÄÄÄÄÄÄ¸ÄúÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µ—°’µàà¯Ò•µúÅÕ…åÙàúÄ¨ÅïÕå°•—ï¥π•µÖùî§Ä¨ÄúàÅÖ±–ÙààÅ±ΩÖë•πúÙâ±ÖÈ‰à¯Ωë•ÿ¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄËÄúÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µ—°’µàà¯úÄ¨ÅïÕå†°•—ï¥πâÖëùîÅÒÅ•—ï¥πµï—Ñ§πÕ±•çî†¿∞Ä»§π—ΩU¡¡ï…ÖÕî†§§Ä¨ÄúΩë•ÿ¯úÏ(ÄÄÄÄÄÄÄÄÄÅ…ï—’…∏ÄúÒÑÅç±ÖÕÃÙâÕïÖ…ç†µÕ’ùùïÕ—•Ω∏àÅ°…ïòÙàúÄ¨ÅïÕå°•—ï¥π°…ïò§Ä¨ÄúàÅëÖ—ÑµπÖµîÙàúÄ¨ÅïÕå°•—ï¥ππÖµî§Ä¨Äúà¯úÄ¨Å—°’µàÄ¨(ÄÄÄÄÄÄÄÄÄÄÄÄúÒë•ÿ¯Òë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µÕ’ùùïÕ—•Ω∏µπÖµîà¯úÄ¨ÅïÕå°•—ï¥ππÖµî§Ä¨ÄúΩë•ÿ¯úÄ¨(ÄÄÄÄÄÄÄÄÄÄÄÄúÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µÕ’ùùïÕ—•Ω∏µµï—Ñà¯úÄ¨ÅïÕå°•—ï¥πµï—Ñ§Ä¨ÄúΩë•ÿ¯Ωë•ÿ¯ΩÑ¯úÏ(ÄÄÄÄÄÄÄÅÙ§π©Ω•∏†úú§Ï(ÄÄÄÄÄÄÄÅÕ’ùùïÕ—•ΩπÃπÕ—Â±îπë•Õ¡±Ö‰ÄÙÄùâ±Ωç¨úÏ(ÄÄÄÄÄÅÙ§Ï(ÄÄÄÅÙ((ÄÄÄÅ•π¡’–πÖëëŸïπ—1•Õ—ïπï»†ù•π¡’–ú∞Åô’πç—•Ω∏Ä†§ÅÏÅ…ïπëï»°•π¡’–πŸÖ±’îπ—…•¥†§π—Ω1Ω›ï…ÖÕî†§§ÏÅÙ§Ï(ÄÄÄÅ•π¡’–πÖëëŸïπ—1•Õ—ïπï»†ùôΩç’Ãú∞Åô’πç—•Ω∏Ä†§ÅÏ(ÄÄÄÄÄÅ±ΩÖëÖ—Ñ†§Ï(ÄÄÄÄÄÅ•òÄ°•π¡’–πŸÖ±’îπ—…•¥†§§Å…ïπëï»°•π¡’–πŸÖ±’îπ—…•¥†§π—Ω1Ω›ï…ÖÕî†§§Ï(ÄÄÄÅÙ§Ï(ÄÄÄÅëΩç’µïπ–πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Åô’πç—•Ω∏Ä°î§ÅÏÅ•òÄ†Ö…Ω‹πçΩπ—Ö•πÃ°îπ—Ö…ùï–§§ÅÕ’ùùïÕ—•ΩπÃπÕ—Â±îπë•Õ¡±Ö‰ÄÙÄùπΩπîúÏÅÙ§Ï(ÄÄÄÅÕ’ùùïÕ—•ΩπÃπÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Åô’πç—•Ω∏Ä°î§ÅÏ(ÄÄÄÄÄÅŸÖ»Å±•π¨ÄÙÅîπ—Ö…ùï–πç±ΩÕïÕ–†úπÕïÖ…ç†µÕ’ùùïÕ—•Ω∏ú§Ï(ÄÄÄÄÄÅ•òÄ°±•π¨§Å—…Öç¨°…Ω‹∞Å±•π¨πùï———…•â’—î†ùëÖ—ÑµπÖµîú§∞ÄùÕ’ùùïÕ—•Ω∏ú§Ï(ÄÄÄÅÙ§Ï((ÄÄÄÄººÄâO·¨àµ≠πÖ¡¡ï∏Ωπ—ï»Åüï»Å—•∞Åëï–ÅâïÕ—îÅ—…ïôôï–∞ÅÕÖµµîÅ…ïÕ’±—Ö–ÅÕΩ¥Éî(ÄÄÄÄººÅ≠±•≠≠îÅõ·…Õ—îÅôΩ…Õ±ÖúÄ¥¥ÅŸ§Å°Ö»Å•πùï∏Åïùï∏Åœ·≠ï…ïÕ’±—Ö–µÕ•ëî∞Å≠’∏(ÄÄÄÄººÅÖ’—Ωô’±±õ·…•πú∞ÅœîÅëï——îÅï»Åªô…µïÕ—îÅπÖ—’…±•ùîÄâœ·¨àµ°Öπë±•πú∏(ÄÄÄÅô’πç—•Ω∏ÅùΩQΩ	ïÕ—5Ö—ç††§ÅÏ(ÄÄÄÄÄÅŸÖ»ÅƒÄÙÅ•π¡’–πŸÖ±’îπ—…•¥†§π—Ω1Ω›ï…ÖÕî†§Ï(ÄÄÄÄÄÅ•òÄ†Öƒ§ÅÏÅ•π¡’–πôΩç’Ã†§ÏÅ…ï—’…∏ÏÅÙ(ÄÄÄÄÄÅ±ΩÖëÖ—Ñ†§π—°ï∏°ô’πç—•Ω∏Ä°Ö±∞§ÅÏ(ÄÄÄÄÄÄÄÅŸÖ»ÅâïÕ–ÄÙÅÖ±∞πô•πê°ô’πç—•Ω∏Ä°•—ï¥§ÅÏÅ…ï—’…∏Å•—ï¥πÕïÖ…ç†π•πëï·=ò°ƒ§ÄÑÙÙÄ¥ƒÏÅÙ§Ï(ÄÄÄÄÄÄÄÅ•òÄ°âïÕ–§ÅÏÅ—…Öç¨°…Ω‹∞ÅâïÕ–ππÖµî∞Äùâ’——Ω∏ú§ÏÅ›•πëΩ‹π±ΩçÖ—•Ω∏π°…ïòÄÙÅâïÕ–π°…ïòÏÅÙ(ÄÄÄÄÄÄÄÅï±ÕîÅÏÅ…ïπëï»°ƒ§ÏÅÙ(ÄÄÄÄÄÅÙ§Ï(ÄÄÄÅÙ(ÄÄÄÅâ’——Ω∏πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞ÅùΩQΩ	ïÕ—5Ö—ç†§Ï(ÄÄÄÅ•π¡’–πÖëëŸïπ—1•Õ—ïπï»†ù≠ïÂëΩ›∏ú∞Åô’πç—•Ω∏Ä°î§ÅÏ(ÄÄÄÄÄÅ•òÄ°îπ≠ï‰ÄÙÙÙÄùπ—ï»ú§ÅÏÅîπ¡…ïŸïπ—ïôÖ’±–†§ÏÅùΩQΩ	ïÕ—5Ö—ç††§ÏÅÙ(ÄÄÄÅÙ§Ï(ÄÅÙ§Ï(ÄÅÙ(ÄÅ•òÄ°ëΩç’µïπ–π…ïÖëÂM—Ö—îÄÙÙÙÄù±ΩÖë•πúú§ÅÏ(ÄÄÄÅëΩç’µïπ–πÖëëŸïπ—1•Õ—ïπï»†ù=5Ωπ—ïπ—1ΩÖëïêú∞Å•π•–§Ï(ÄÅÙÅï±ÕîÅÏ(ÄÄÄÅ•π•–†§Ï(ÄÅÙ)Ù§†§Ï(ààà((åÅ}—Ω¡âÖ…}°—µ∞†§Ä°ëïô•πï…–Å±Öπù–Å—•ë±•ùï…îÅ§Åô•±ï∏∞Å…ï—–Åëï»ÅQ=A	I}!Q50(åÅ°•Õ—Ω…•Õ¨Å°Ö»Å±•ùùï–§Å…ïôï…ï…ï»Å—•∞Å19M}MI!}MQe1Ω19M}MI!})LÄ¥¥(åÅÕï±ŸîÅ≠Ö±±ï–Å∑îÅëï…ôΩ»ÅÕ≠©îÅ!H∞Åï——ï»ÅÖ–ÅâïùùîÅô•ππïÃ∞Å•≠≠îÅëï»Åô’π≠Õ©Ωπï∏(åÅï»Åëïô•πï…–∏)Q=A	I}!Q50ÄÙÅ}—Ω¡âÖ…}°—µ∞†§)Q=A	I}!Q51}9=}MI ÄÙÅ}—Ω¡âÖ…}°—µ∞°Õ°Ω›}ÕïÖ…ç†ıÖ±Õî§(((åÅO·≠ïΩ…êÅ¡ï»Å—•±âï£·…Õ≠Ö—ïùΩ…§∏ÅïëîÉõ„îÅΩúÅÖÕç•§µŸÖ…•Öπ—ï»∞ÅÕ•ëï∏ÅµÖπùîÅÕ≠…•Ÿï»(åÄâΩÂïë…Ö¡ï»àºâ±•πÕïŸÖïÕ≠îàÅ’—ï∏ÅÕ¡ïÕ•Ö±—ïù∏∏Å-’∏Åâ…’≠–Å—•∞ÉîÅ5Q!Ä°Ö±ë…§ÅŸ•Õ–§∏)M=1UQ%=9}MI!}QI5LÄÙÅÏ(ÄÄÄÄâ±•πÕïŸÖïÕ≠îàËÄâ±•πÕï€ôÕ≠îÅ±•πÕïŸÖïÕ≠îà∞(ÄÄÄÄâΩÂïë…Ö¡ï»àËÄã·ÂïëÀï¡ï»ÅΩÂïë…Ö¡ï»É·Âï¡±ï•îÅΩÂï¡±ï•îà∞(ÄÄÄÄâ—•±âï°Ω»àËÄâ—•±âï£·»Å—•±âï°Ω»Åï—’§Å°©ï±¡ïµ•ë±ï»à∞)Ù(()ëïòÅâ’•±ë}ÕïÖ…ç°}•πëï‡°¡…Ωë’ç—ÃËÅ±•Õ—më•ç—t∞Å¡…•ŸÖ—ï}±Öâï±ÃËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî∞ÅÕΩ±’—•ΩπÃËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî∞ÅôÖµ•±•ïÃËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯Å±•Õ—më•ç—tË(ÄÄÄÄààâO·≠ï•πëï≠Õï∏ÅÕΩ¥Åë…•Ÿï»ÅÖ’—Ωô’±±õ·…•πùï∏Ä°ôΩ…Õ•ëîËÅ•ππïâÂùêÅÕΩ¥(ÄÄÄÅÕ≠©’±–Å)M=8ÏÅù’•ëîµÕ•ëï»ËÅ°ïπ—ïÃÅô…ÑÄΩëÖ—ÑΩÕïÖ…ç†µ•πëï‡π©ÕΩ∏§∏(ÄÄÄÄâµï—ÑàÅï»Åëï∏ÅÕÂπ±•ùîÅ’πëï…—ï≠Õ–µ±•π©ï∏Å§ÅôΩ…Õ±ÖùïπîÄ¥¥Å≠©ïëïπÖŸπï–(ÄÄÄÅÕ≠Ö∞Å%--ÅŸ•ÕïÃÅëï»Ä°ÕÖµµîÅ…ïùï∞ÅÕΩ¥Å…ïÕ—ï∏ÅÖÿÅÕ•ëï∏§∞Åµï∏ÄâÕïÖ…ç†à(ÄÄÄÄ°≠’∏Åâ…’≠–Å—•∞ÉîÅ5Q!∞ÅÖ±ë…§ÅŸ•Õ–§Åâï°Ω±ëï»Åëï–∞ÅÕ•ëï∏Åï∏Åâ…’≠ï»ÅÕΩ¥(ÄÄÄÅœ·≠ï»ÄâMÂπÕÖ¥àÅôΩ…—ÕÖ—–Åã·»Åô•ππîÅÂïD∏ààà(ÄÄÄÅïπ—…•ïÃÄÙÅl(ÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâπÖµîàËÅ¡lâπÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµï—ÑàËÅ¡lââ…Öπë}±Öâï∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ°…ïòàËÅòúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ•µÖùîàËÅ}¡…Ωë’ç—}•µÖùî°¿§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕïÖ…ç†àËÅòùÌ¡lâπÖµîâuÙÅÌ¡lââ…Öπë}±Öâï∞âuÙúπ±Ω›ï»†§∞(ÄÄÄÄÄÄÄÅÙ(ÄÄÄÄÄÄÄÅôΩ»Å¿Å•∏Å¡…Ωë’ç—Ã(ÄÄÄÅt(ÄÄÄÅïπ—…•ïÃÄ¨ÙÅl(ÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâπÖµîàËÅ¡lâπÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµï—ÑàËÅòùÌ¡lââ…Öπë}±Öâï∞âuÙÉ
‹ÅÌM=1UQ%=9}Q=I%Mm¡lâÕΩ±’—•Ωπ}çÖ—ïùΩ…‰âuulâ±Öâï∞âuÙú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ°…ïòàËÅòúΩÌ¡lâÕΩ±’—•Ωπ}çÖ—ïùΩ…‰âuÙΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ•µÖùîàËÅ}¡…Ωë’ç—}•µÖùî°¿§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕïÖ…ç†àËÅòùÌ¡lâπÖµîâuÙÅÌ¡lââ…Öπë}±Öâï∞âuÙÅÌM=1UQ%=9}MI!}QI5Lπùï–°¡lâÕΩ±’—•Ωπ}çÖ—ïùΩ…‰ât∞Äàà•Ùúπ±Ω›ï»†§∞(ÄÄÄÄÄÄÄÅÙ(ÄÄÄÄÄÄÄÅôΩ»Å¿Å•∏Ä°ÕΩ±’—•ΩπÃÅΩ»Åmt§(ÄÄÄÅt(ÄÄÄÅïπ—…•ïÃÄ¨ÙÅl(ÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâπÖµîàËÅ±Öâï±lâπÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµï—ÑàËÄâùï–Åµï…≠ïπÖŸ∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ°…ïòàËÅòúΩ¡…•ŸÖ—îµ±Öâï∞ΩÌ±Öâï±lâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ•µÖùîàËÅ9Ωπî∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕïÖ…ç†àËÅòùÌ±Öâï±lâπÖµîâuÙÅÌ±Öâï±lâç°Ö•∏âuÙúπ±Ω›ï»†§∞(ÄÄÄÄÄÄÄÄÄÄÄÄåÄââÖëùîàÄ†»¿»ÿ¥¿‰¥»‰∞Å-Ö§ËÄâÕï»ÅŸ§Å•≠≠îÅ°Ö»ÅÕ±•≠–Å±•—îÅ•≠Ω∏Å√î(ÄÄÄÄÄÄÄÄÄÄÄÄåÅëîÅπÂî∏∏àÄ¥¯Äâëï–Åù©ï±ëï»ÅÖ±±îÅùï–Åµï…≠ïπÖŸ∏à§Ä¥¥Å’—ï∏Åëï——î(ÄÄÄÄÄÄÄÄÄÄÄÄåÅôÖ±–Å)Lµï∏Ä°ÕîÅ19M}MI!})L§Å—•±âÖ≠îÅ—•∞ÉîÅ—ÑÅëîÄ»Åõ·…Õ—î(ÄÄÄÄÄÄÄÄÄÄÄÄåÅâΩ≠Õ—ÖŸïπîÅÖÿÄâµï—ÑàÅôΩ»Åœ·≠ïôΩ…Õ±Öùï—ÃÅôÖ±±âÖç¨µ•≠Ω∏Åªï»(ÄÄÄÄÄÄÄÄÄÄÄÄåÄâ•µÖùîàÅï»Åπ’±∞Ä°Ö±±—•êÅπ’±∞Å°ï»∞ÅµïêÅŸ•±©îÄ¥¥ÅŸ§ÅŸ•Õï»ÅÖ±ë…§(ÄÄÄÄÄÄÄÄÄÄÄÄåÅëï–Åï≠—îÅ¡…Ωë’≠—ï—ÃÅâ•±ëîÅ’πëï»Åï–Å¡…•ŸÖ–Åµï…≠ïπÖŸ∏§∏ÅM•ëï∏(ÄÄÄÄÄÄÄÄÄÄÄÄåÄâµï—ÑàÅï»Åëï∏ÅM55Åùïπï…•Õ≠îÅ—ï≠Õ—ï∏Ä†âùï–Åµï…≠ïπÖŸ∏à§ÅôΩ»(ÄÄÄÄÄÄÄÄÄÄÄÄåÅÖ±±îÄ‡–Å¡…•ŸÖ—îÅ±Öâï∞µ¡…Ωë’≠—ï»∞ÅùÑÅëï–ÅÕÖµµîÅµïπ•πùÕ≥·Õî(ÄÄÄÄÄÄÄÄÄÄÄÄåÄâàµ•≠Ω∏Å√îÅ—Ÿï…ÃÅÖÿÅ11ÅÖÿÅëï¥Ä¥¥Å•≠≠îÅï∏ÅQ…’ï1ïπÃµÕ¡ïÕ•ô•≠¨(ÄÄÄÄÄÄÄÄÄÄÄÄåÅôï•∞∞Åµï∏Åï∏Åï≠Õ•Õ—ï…ïπëîÅôï•∞Å§ÅÖ±±îÅô•…îÅΩ¡¡…•ππï±•ùîÅ≠©ïëï»(ÄÄÄÄÄÄÄÄÄÄÄÄåÅΩùœî∞Åõ·…Õ–ÅÕÂπ±•úÅªîÅÕΩ¥Åëï–Åôïµ—îÅÕï——ï–Åù©Ω…ëîÅ∑·πÕ—ï…ï–(ÄÄÄÄÄÄÄÄÄÄÄÄåÅ—Âëï±•ú∏ÄââÖëùîàÅù•»Å§ÅÕ—ïëï–Åï–Å¡…Ωë’≠—…ï±ïŸÖπ–ÅôÖ±±âÖç¨µ•≠Ω∏(ÄÄÄÄÄÄÄÄÄÄÄÄåÅô…ÑÅÕï±ŸîÅµï…≠ïπÖŸπï–Ä°òπï≠Ã∏ÄâQ…’ï1ïπÃÅA…ïµ•’¥ÅÖ•±‰àÄ¥¯ÄâQHà∞(ÄÄÄÄÄÄÄÄÄÄÄÄåÄâ•]ïÖ»Å=·Âùï∏ÅaHàÄ¥¯Äâ%\à§∞ÅÕÖµµîÅ¡…•πÕ•¡¿ÅÕΩ¥Åï≠—îÅ¡…Ωë’≠—ï»(ÄÄÄÄÄÄÄÄÄÄÄÄåÅÖ±±ï…ïëîÅõï»ÅŸ•ÑÅÕ•∏Åïùï∏Åâ…Öπë}±Öâï∞∏(ÄÄÄÄÄÄÄÄÄÄÄÄââÖëùîàËÅ±Öâï±lâπÖµîâulË…tπ’¡¡ï»†§∞(ÄÄÄÄÄÄÄÅÙ(ÄÄÄÄÄÄÄÅôΩ»Å±Öâï∞Å•∏Ä°¡…•ŸÖ—ï}±Öâï±ÃÅΩ»Åmt§(ÄÄÄÅt(ÄÄÄÄåÅMï…•îµÕ•ëï»Ä†ΩÕï…•îΩÌÕ±’ùÙº§ÅµÖπù±ï–Å±ïπùîÅïπ°Ÿï»Å•ππ≠ΩµµïπëîÅ±ïπ≠îÅ’—ïπΩ¥(ÄÄÄÄåÅÕ•—ïµÖ¿π·µ∞Ä°ÕîÅùïπï…Ö—ï}¡ÖùïÃπ¡‰ÅÕ•∏Å≠Ωµµïπ—Ö»ÅΩ¥Äâ=¡¡ëÖùï–Ä¥Å•≠≠î(ÄÄÄÄåÅ•πëï≠Õï…–àÅ§ÅMïÖ…ç†ÅΩπÕΩ±îÄ»¿»ÿ¥¿‰¥ƒ‡§Ä¥¥Å±Öù–Å—•∞Å°ï»Ä»¿»ÿ¥¿‰¥»‹ÅÕ±•¨ÅÖ–(ÄÄÄÄåÅï–Åœ·¨Å√îÅòπï≠Ã∏ÄâÖç’Ÿ’îÅµΩ•Õ–ÅÕï…•îàÅôÖ≠—•Õ¨Åô•ππï»ÅÕÖµ±îµÕ•ëï∏∏(ÄÄÄÅïπ—…•ïÃÄ¨ÙÅl(ÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâπÖµîàËÅòùÌôÖµlâπÖµîâuÙµÕï…•ï∏ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµï—ÑàËÅòùMï…•îÉ
‹ÅÌôÖµlâçΩ’π–âuÙÅŸÖ…•Öπ—ï»ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ°…ïòàËÅòúΩÕï…•îΩÌôÖµlâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ•µÖùîàËÅôÖ¥πùï–†â•µÖùîà§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕïÖ…ç†àËÅòùÌôÖµlâπÖµîâuÙÅÕï…•îÅÕï…•ï∏úπ±Ω›ï»†§∞(ÄÄÄÄÄÄÄÅÙ(ÄÄÄÄÄÄÄÅôΩ»ÅôÖ¥Å•∏Ä°ôÖµ•±•ïÃÅΩ»Åmt§(ÄÄÄÅt(ÄÄÄÅ…ï—’…∏Åïπ—…•ïÃ(()ëïòÅ…ïπëï…}ù’•ëï}ÕïÖ…ç°}çÖ…ê°ù’•ëï}Õ±’úËÅÕ—»∞ÅçΩµ¡Öç–ËÅâΩΩ∞ÄÙÅÖ±Õî§Ä¥¯ÅÕ—»Ë(ÄÄÄÅ—•—±îÄÙÄâ	…’≠ï»Åë‘Å≠Ωπ—Ö≠—±•πÕï»¸Å•π∏Å±ÖŸïÕ—îÅ¡…•Ãà(ÄÄÄÅ…Ω‹ÄÙÅòàààÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µ…Ω‹àÅëÖ—Ñµù’•ëîÙâÌïÕçÖ¡î°ù’•ëï}Õ±’ú•Ùà¯(ÄÄÄÄÄÄÒÕŸúÅç±ÖÕÃÙâÕïÖ…ç†µ•çΩ∏àÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Òç•…ç±îÅç‡Ùàƒ¿∏‘àÅç‰Ùàƒ¿∏‘àÅ»Ùàÿ∏‘àº¯Ò¡Ö—†ÅêÙâ4»¿Ä»¡∞¥–∏‡¥–∏‡àº¯ΩÕŸú¯(ÄÄÄÄÄÄÒ•π¡’–Å—Â¡îÙâÕïÖ…ç†àÅç±ÖÕÃÙâÕïÖ…ç†µ•π¡’–àÅ¡±Öçï°Ω±ëï»ÙâO·¨Å±•πÕîÅï±±ï»Åµï…≠îàÅÖ…•Ñµ±Öâï∞ÙâO·¨Åï——ï»Å±•πÕîÅï±±ï»Åµï…≠îàÅÖ’—ΩçΩµ¡±ï—îÙâΩôòà¯(ÄÄÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâÕïÖ…ç†µâ—∏à˘O·¨Ωâ’——Ω∏¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µÕ’ùùïÕ—•ΩπÃà¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯ààà(ÄÄÄÅ•òÅçΩµ¡Öç–Ë(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒÖÕ•ëîÅç±ÖÕÃÙâù’•ëîµç—ÑÅù’•ëîµç—ÑµçΩµ¡Öç–àÅÖ…•Ñµ±Öâï∞ÙâMÖµµïπ±•ù∏Å¡…•Õï»àÅëÖ—ÑµπΩÕπ•¡¡ï–¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙâù’•ëîµç—Ñµ—•—±îà˘Ì—•—±ïÙΩ¿¯(ÄÄÄÅÌ…Ω›Ù(ÄÄΩÖÕ•ëî¯ààà(ÄÄÄÅ…ï—’…∏ÅòàààÒÖÕ•ëîÅç±ÖÕÃÙâù’•ëîµç—ÑàÅÖ…•Ñµ±Öâï∞ÙâMÖµµïπ±•ù∏Å¡…•Õï»àÅëÖ—ÑµπΩÕπ•¡¡ï–¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙâù’•ëîµç—Ñµ—•—±îà˘Ì—•—±ïÙΩ¿¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙâù’•ëîµç—Ñµ—ï·–à˘O·¨Å√îÅ±•πÕï∏Åï±±ï»Åµï…≠ï–Åë‘Åâ…’≠ï»ÉäLÅŸ§ÅÕÖµµïπ±•ùπï»ÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÅΩúÅ±Ö»ÅëïúÅÕîÅ¡…•Õï∏ÅãïëîÅµïêÅΩúÅ’—ï∏Åô…Ö≠–∏Ω¿¯(ÄÄÄÅÌ…Ω›Ù(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµç—Ñµ±•π≠Ãà¯(ÄÄÄÄÄÄÒÕ¡Ö∏˘±±ï»Åâ±ÑÅï——ï»Å—Â¡îËΩÕ¡Ö∏¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩëÖùÕ±•πÕï»ºà˘ÖùÕ±•πÕï»ΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩµÖπïëÕ±•πÕï»ºà˘7ïπïëÕ±•πÕï»ΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ω—Ω…•Õ≠îµ±•πÕï»ºà˘QΩ…•Õ≠îΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωµ’±—•ôΩ≠Ö±îµ±•πÕï»ºà˘5’±—•ôΩ≠Ö±îΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàºçµï…≠ï»à˘±±îÅµï…≠ï»ΩÑ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩÖÕ•ëî¯ààà(()ëïòÅ…ïπëï…}°Ωµï}¡Öùî°çÖ—Ö±ΩúËÅë•ç–∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî∞Å¡…•ŸÖ—ï}±Öâï±ÃËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî∞ÅÕΩ±’—•Ωπ}¡…Ωë’ç—ÃËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî∞ÅôÖµ•±•ïÃËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§((ÄÄÄÄåÅO·≠ï•πëï≠Õï∏Ä°’πëï»§Åë…•Ÿï»Å≠’∏Åœ·≠ïôΩ…Õ±Öúµë…Ω¡ëΩ›πï∏Ä¥¥ÅôΩ…Õ•ëï∏(ÄÄÄÄåÅŸ•Õï»Å%--Å±ïπùï»Åï–Åô’±±–Å¡…Ωë’≠—ù…•êÄ°ô©ï…πï–Ä»¿»ÿ¥¿‡¥ƒ‘§∏ÅÖ—Ñ(ÄÄÄÄåÅÕïπëïÃÅÕΩ¥ÅÕ≠©’±–Å)M=8Å§ÅÕ—ïëï–ÅôΩ»ÅÕÂπ±•ùîÅ≠Ω…–∞ÅÕ±•¨ÅÖ–Åœ·≠ï–(ÄÄÄÄåÅôΩ…—ÕÖ—–Åëï≠≠ï»ÅÖ±–Å’—ï∏ÅÖ–ÅôΩ…Õ•ëïπÃÅ!Q50Ω=4Å∑îÅ•ππï°Ω±ëîÅ°Ÿï…–(ÄÄÄÄåÅïπïÕ—îÅ¡…Ωë’≠–Ä°ìï…±•úÅôΩ»ÅÕ•ëïŸï≠–ÅΩúÅôΩ»Å—Ω¡•Õ¨ÅM<µôΩ≠’Ã§∏(ÄÄÄÅÕïÖ…ç°}•πëï·}©ÕΩ∏ÄÙÅ©ÕΩ∏πë’µ¡Ã†(ÄÄÄÄÄÄÄÅâ’•±ë}ÕïÖ…ç°}•πëï‡°çÖ—Ö±Ωùlâ¡…Ωë’ç—Ãât∞ÅÕΩ±’—•ΩπÃıÕΩ±’—•Ωπ}¡…Ωë’ç—Ã§∞ÅïπÕ’…ï}ÖÕç•§ıÖ±Õî(ÄÄÄÄ§π…ï¡±Öçî†àºà∞ÄàÒqpºà§(ÄÄÄÅ¡…•ŸÖ—ï}±Öâï±}ÕïÖ…ç°}•πëï·}©ÕΩ∏ÄÙÅ©ÕΩ∏πë’µ¡Ã†(ÄÄÄÄÄÄÄÅâ’•±ë}ÕïÖ…ç°}•πëï‡°mt∞Å¡…•ŸÖ—ï}±Öâï±Ã∞ÅôÖµ•±•ïÃıôÖµ•±•ïÃ§∞ÅïπÕ’…ï}ÖÕç•§ıÖ±Õî(ÄÄÄÄ§π…ï¡±Öçî†àºà∞ÄàÒqpºà§((ÄÄÄÅâ…Öπë}çΩ’π—ÃËÅë•ç—mÕ—»∞Å•π—tÄÙÅÌÙ(ÄÄÄÅâ…Öπë}±Öâï±ÃËÅë•ç—mÕ—»∞ÅÕ—…tÄÙÅÌÙ(ÄÄÄÄåÅ—–Å…ï¡…ïÕïπ—Ö—•Ÿ–Å¡…Ωë’≠—â•±ëîÅ¡ï»Åµï…≠îÄ¥¥Å—•∞ÅëîÅπÂî∞ÅÕ”·……î(ÄÄÄÄåÅµï…≠îµ≠Ω…—ïπîÅ√îÅµΩâ•∞Ä°ÕîÅ…ïπëï…}â…Öπë}çÖ…êÅ’πëï»§∏ÅΩ…ï—…ï≠≠ï»Åï–(ÄÄÄÄåÅ¡…Ωë’≠–ÅÕΩ¥ÅôÖ≠—•Õ¨Å!HÅï–Åâ•±ëîÄ°µÖπ’ï±–Å≠’…Ö—ï…–Åï±±ï»Å±•ÕïπÕ•ï…–(ÄÄÄÄåÅôïïêµâ•±ëîÅŸ•ÑÅ}¡…Ωë’ç—}•µÖùî§Åô…ïµôΩ»ÅâÖ…îÅëï–Åõ·…Õ—îÅ¡…Ωë’≠—ï–Å§(ÄÄÄÄåÅ≠Ö—Ö±Ωúµ…ï≠≠ïõ·±ùï∏∞ÅÕΩ¥Å≠’ππîÅ€ô…–Åï–Å’—ï∏Åâ•±ëîÅ§Åëï–Å°ï±îÅ—Ö—–∏(ÄÄÄÅâ…Öπë}ÕÖµ¡±ï}•µÖùîËÅë•ç—mÕ—»∞ÅÕ—…tÄÙÅÌÙ(ÄÄÄÄåÅπ—Ö±∞Å%MQ%9-QÅôΩ…°Öπë±ï…îÅÕΩ¥ÅôÖ≠—•Õ¨Å°Ö»Åµï…≠ï–Å√îÅ±Öùï»Ä¥¥Åâ…’≠–(ÄÄÄÄåÅ—•∞ÉîÅÕΩ…—ï…îÅ5ï…≠ï»µÕï≠Õ©Ωπï∏Ä†»¿»ÿ¥¿‡¥Ã¿∞Åï——ï»Åâ…’≠ï…ïπÃÉ·πÕ≠îÅΩ¥(ÄÄÄÄåÅï∏ÄâµïÕ–Å¡Ω¡’≥ô…îÅ§Å9Ω…ùîàµ…ï≠≠ïõ·±ùî§∏ÅY§Å°Ö»Å•πùï∏Åïùï∏Å—…Öô•≠¨Éî(ÄÄÄÄåÅâÖÕï…îÅëï——îÅ√îÅïπªî∞ÅΩúÅï–Å¡Ö»Å•ππ±•µ—îÄâ$µùïπï…ï…—îÅ¡Ω¡’≥ô…•—ï—Ã¥(ÄÄÄÄåÅ—Öâï±±ï»àÅÕÖµµîÅëÖúÅ•ππï°Ω±ë–ÅâïùùîÅŸï…•ô•Õï…âÖ…–Å’…•≠—•ùîÅ√ïÕ—Öπëï»(ÄÄÄÄåÄ°â∞πÑ∏Å•]ïÖ»Åôï•±Ö≠—•úÅ≠πÂ——ï–Å—•∞Å%π—ï…Ω¡—•¨∞ÅΩúÅïŸï…ç±ïÖ»Å1%Q(ÄÄÄÄåÅôï•±Ö≠—•úÅ≠Ö±–Å1ïπÕ›Ö‰µï≠Õ≠±’Õ•ÿÅªï»Åëï∏ÅôÖ≠—•Õ¨ÅÕï±ùïÃÅ°ΩÃÅ(ÄÄÄÄåÅ1ïπÕΩ∏ÅΩúÅ1ïπÕ›Ö‰§Ä¥¥ÅôΩ…≠ÖÕ—ï–ÅÕΩ¥ÅëÖ—Öù…’ππ±Öú∞ÅÕÖµµîÅ¡…•πÕ•¡¿ÅÕΩ¥(ÄÄÄÄåÅ—•ë±•ùï…îÅÖŸŸ•Õ—îÅ$µëΩ≠’µïπ—ï»Å§Åëï——îÅ¡…ΩÕ©ï≠—ï–∏Å	…ïëëîÅ§ÅôÖ≠—•Õ¨(ÄÄÄÄåÅôΩ…°Öπë±ï…ëï≠π•πúÅï»Åëï…•µΩ–Åï≠—îÅëÖ—ÑÅŸ§ÅÖ±±ï…ïëîÅ°Ö»ËÅôΩ…°Öπë±ï…î(ÄÄÄÄåÅŸï±ùï»ÅÕï±ÿÅ°ŸÑÅëîÅõ·…ï»ÅâÖÕï…–Å√îÅïùπîÅÕÖ±ùÕ—Ö±∞∞ÅœîÅï–Åµï…≠îÅÕΩ¥(ÄÄÄÄåÅõ·…ïÃÅÖÿÅµÖπùîÅ’ÖŸ°ïπù•ùîÅôΩ…°Öπë±ï…îÅï»Åï–Å…ïï±–Ä°Ω¥Åïπ∏Å•πë•…ï≠—î§(ÄÄÄÄåÅï——ï…Õ√·…Õï±ÕÕ•ùπÖ∞Ä¥¥Å%--ÅâÖ…îÅï–Å—Ö±∞Å√îÅ°ŸΩ»ÅµÖπùîÅ¡Ö≠π•πùÕÕ”·…»¥(ÄÄÄÄåÅï±Õï»ΩŸÖ…•Öπ—ï»ÅY$Å°Ö»Å±Öù–Å•π∏ÅÖÿÅµï…≠ï–∏(ÄÄÄÅâ…Öπë}…ï—Ö•±ï…ÃËÅë•ç—mÕ—»∞ÅÕï—mÕ—…utÄÙÅÌÙ(ÄÄÄÅ¡…Ωë’ç—}âÂ}•êËÅë•ç—mÕ—»∞Åë•ç—tÄÙÅÌÙ(ÄÄÄÅôΩ»Å¿Å•∏ÅçÖ—Ö±Ωùlâ¡…Ωë’ç—ÃâtË(ÄÄÄÄÄÄÄÅ¡…Ωë’ç—}âÂ}•ëm¡lâ•êâutÄÙÅ¿(ÄÄÄÄÄÄÄÅâ…Öπë}çΩ’π—Õm¡lââ…Öπë}Õ±’úâutÄÙÅâ…Öπë}çΩ’π—Ãπùï–°¡lââ…Öπë}Õ±’úât∞Ä¿§Ä¨Äƒ(ÄÄÄÄÄÄÄÅâ…Öπë}±Öâï±Õm¡lââ…Öπë}Õ±’úâutÄÙÅ¡lââ…Öπë}±Öâï∞ât(ÄÄÄÄÄÄÄÅ•òÅ¡lââ…Öπë}Õ±’úâtÅπΩ–Å•∏Åâ…Öπë}ÕÖµ¡±ï}•µÖùîË(ÄÄÄÄÄÄÄÄÄÄÄÅ•µúÄÙÅ}¡…Ωë’ç—}•µÖùî°¿§(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ•µúË(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅâ…Öπë}ÕÖµ¡±ï}•µÖùïm¡lââ…Öπë}Õ±’úâutÄÙÅ•µú(ÄÄÄÄÄÄÄÅ…ï—Ö•±ï…ÃÄÙÅâ…Öπë}…ï—Ö•±ï…ÃπÕï—ëïôÖ’±–°¡lââ…Öπë}Õ±’úât∞ÅÕï–†§§(ÄÄÄÄÄÄÄÅôΩ»ÅºÅ•∏Å¿πùï–†âΩôôï…Ãà∞Åmt§Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅºπùï–†â•π}Õ—Ωç¨à§Ë(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ…ï—Ö•±ï…ÃπÖëê°Ωlâ…ï—Ö•±ï»ât§((ÄÄÄÅëïòÅ…ïπëï…}â…Öπë}çÖ…ê°Õ±’úËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ±Öâï∞ÄÙÅâ…Öπë}±Öâï±ÕmÕ±’ùt(ÄÄÄÄÄÄÄÅçΩ’π–ÄÙÅâ…Öπë}çΩ’π—ÕmÕ±’ùt(ÄÄÄÄÄÄÄÅπ}±Öâï∞ÄÙÄâ¡…Ωë’≠–àÅ•òÅçΩ’π–ÄÙÙÄƒÅï±ÕîÄâ¡…Ωë’≠—ï»à(ÄÄÄÄÄÄÄÅï·—…Ö}ç±Ã∞ÅâÖëùï}çΩπ—ïπ–ÄÙÅ}â…Öπë}âÖëùî°Õ±’ú∞Å±Öâï∞§(ÄÄÄÄÄÄÄÅâÖëùï}ç±ÖÕÃÄÙÄ†ââ…ÖπêµçÖ…êµâÖëùîÄàÄ¨Åï·—…Ö}ç±Ã§πÕ—…•¿†§(ÄÄÄÄÄÄÄÅÕÖµ¡±ï}•µÖùîÄÙÅâ…Öπë}ÕÖµ¡±ï}•µÖùîπùï–°Õ±’ú§(ÄÄÄÄÄÄÄÅçÖ…ë}ç±ÃÄÙÄââ…ÖπêµçÖ…êÅ°ÖÃµ¡°Ω—ºàÅ•òÅÕÖµ¡±ï}•µÖùîÅï±ÕîÄââ…ÖπêµçÖ…êà(ÄÄÄÄÄÄÄÅ¡°Ω—Ω}°—µ∞ÄÙÄ°òúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµ¡°Ω—ºà˘Ì}•µù}—Öú°ÕÖµ¡±ï}•µÖùî∞Å±Öâï∞•ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ•òÅÕÖµ¡±ï}•µÖùîÅï±ÕîÄàà§(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒÑÅç±ÖÕÃÙâÌçÖ…ë}ç±ÕÙàÅ°…ïòÙàΩµï…≠îΩÌïÕçÖ¡î°Õ±’ú•Ùºà¯(ÄÅÌ¡°Ω—Ω}°—µ±Ù(ÄÄÒë•ÿÅç±ÖÕÃÙâÌâÖëùï}ç±ÖÕÕÙà˘ÌâÖëùï}çΩπ—ïπ—ÙΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµ•πôºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµπÖµîà˘ÌïÕçÖ¡î°±Öâï∞•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµçΩ’π–à˘ÌçΩ’π—ÙÅÌπ}±Öâï±ÙΩë•ÿ¯(ÄÄΩë•ÿ¯(ΩÑ¯ààà((ÄÄÄÅëïòÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}ç°Ö•π}çÖ…ê°ç°Ö•∏ËÅÕ—»∞ÅçΩ’π–ËÅ•π–∞ÅÕÖµ¡±ï}•µÖùîËÅÕ—»ÅÅ9Ωπî∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ•±±’Õ—…Ö—•Ωπ}°—µ∞ËÅÕ—»ÅÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÄåÅ-©ïëïπÖŸπï–Ä°MÂπÕÖ¥Ω	…•±±ï±ÖπêΩM¡ïçÕÖŸï…ÃΩΩ¡—•≠¨§ÅΩúÅ≠©ïëïπÃÅïùï∏(ÄÄÄÄÄÄÄÄåÅ±ΩùºÅÕ≠Ö∞Å%--ÅŸ•ÕïÃÅ°ï»Ä¥¥Åâ…’≠ï»É·πÕ≠ï»Ä†»¿»ÿ¥¿‡¥Ã¿§ÅÖ–Åë•ÕÕî(ÄÄÄÄÄÄÄÄåÅÕï…•ïπîÅô…ïµÕ”ï»ÅÕΩ¥ÅïùπîÅµï…≠ï»Å√îÅ±•π©îÅµïêÅï≠—îÅ±•πÕïµï…≠ï»∏(ÄÄÄÄÄÄÄÄåÅ-Ωâ±•πúÅ—•∞Å≠©ïëï∏Å±•ùùï»ÅôΩ…—ÕÖ—–Å√îÄΩ¡…•ŸÖ—îµ±Öâï∞ºÄ°ïùï∏(ÄÄÄÄÄÄÄÄåÅΩŸï…Õ•≠—ÕÕ•ëîÅëïë•≠ï…–Å—•∞ÅÖ≠≠’…Ö–Åëï∏ÅôΩ…≠±Ö…•πùï∏§∏Å%±±’Õ—…ÖÕ©Ω∏(ÄÄÄÄÄÄÄÄåÄ°ïùï∏Å—ïùπï–Åù…Öô•≠¨∞ÅÕîÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}•±±’Õ—…Ö—•Ω∏§ÅŸ•ππï»(ÄÄÄÄÄÄÄÄåÅÖ±±—•êÅΩŸï»Åï–Å≥ïπ–Åâ•±ëîÅÖÿÅëï–Åï≠—îÅ¡…Ωë’≠—ï–Ä¥¥Å•]ïÖ»Ω	…•±±ï±Öπê(ÄÄÄÄÄÄÄÄåÅ°Ö»Å•πùï∏Å•±±’Õ—…ÖÕ©ΩπÕ¡Ö≠≠îÅïπªîÅΩúÅôÖ±±ï»Åëï…ôΩ»ÅôΩ…—ÕÖ—–Å—•±âÖ≠î(ÄÄÄÄÄÄÄÄåÅ—•∞Åëï–Å≥ïπ—îÅ¡…Ωë’≠—â•±ëï–Ä¨Åï∏Å•π•—•Ö∞µâÖëùî∏(ÄÄÄÄÄÄÄÅπ}±Öâï∞ÄÙÄâïùï–Åµï…≠îàÅ•òÅçΩ’π–ÄÙÙÄƒÅï±ÕîÄâïùπîÅµï…≠ï»à(ÄÄÄÄÄÄÄÅÕ’ââ…ÖπêÄÙÅAI%YQ}1	1}MU		I9Lπùï–°ç°Ö•∏∞Åç°Ö•∏§(ÄÄÄÄÄÄÄÅÕ’ââ…Öπë}±ΩùºÄÙÅAI%YQ}1	1}MU		I9}1==Lπùï–°Õ’ââ…Öπê§(ÄÄÄÄÄÄÄÅ•òÅ•±±’Õ—…Ö—•Ωπ}°—µ∞Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ…ë}ç±ÃÄÙÄââ…ÖπêµçÖ…êÅ°ÖÃµ¡°Ω—ºà(ÄÄÄÄÄÄÄÄÄÄÄÅ¡°Ω—Ω}°—µ∞ÄÙÅòúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµ¡°Ω—ºà¯Òë•ÿÅç±ÖÕÃÙâ¡±§µô…Öµîà˘Ì•±±’Õ—…Ö—•Ωπ}°—µ±ÙΩë•ÿ¯Ωë•ÿ¯ú(ÄÄÄÄÄÄÄÄÄÄÄÅâÖëùï}°—µ∞ÄÙÄ°òúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµâÖëùîÅ°ÖÃµ±Ωùºà¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòúÒ•µúÅç±ÖÕÃÙââ…Öπêµ±Ωùºµ•µúàÅÕ…åÙàΩÕ—Ö—•åΩ±ΩùΩÃΩÌÕ’ââ…Öπë}±ΩùΩÙàÅÖ±–ÙààÅ±ΩÖë•πúÙâ±ÖÈ‰à¯Ωë•ÿ¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ•òÅÕ’ââ…Öπë}±ΩùºÅï±ÕîÄàà§(ÄÄÄÄÄÄÄÅï±•òÅÕÖµ¡±ï}•µÖùîË(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ…ë}ç±ÃÄÙÄââ…ÖπêµçÖ…êÅ°ÖÃµ¡°Ω—ºà(ÄÄÄÄÄÄÄÄÄÄÄÅ¡°Ω—Ω}°—µ∞ÄÙÅòúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµ¡°Ω—ºà˘Ì}•µù}—Öú°ÕÖµ¡±ï}•µÖùî∞ÅÕ’ââ…Öπê•ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÄÄÄÄÅâÖëùï}°—µ∞ÄÙÅòúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµâÖëùîà˘ÌïÕçÖ¡î°Õ’ââ…ÖπëlË…tπ’¡¡ï»†§•ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ…ë}ç±ÃÄÙÄââ…ÖπêµçÖ…êà(ÄÄÄÄÄÄÄÄÄÄÄÅ¡°Ω—Ω}°—µ∞ÄÙÄàà(ÄÄÄÄÄÄÄÄÄÄÄÅâÖëùï}°—µ∞ÄÙÅòúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµâÖëùîà˘ÌïÕçÖ¡î°Õ’ââ…ÖπëlË…tπ’¡¡ï»†§•ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒÑÅç±ÖÕÃÙâÌçÖ…ë}ç±ÕÙàÅ°…ïòÙàΩµï…≠îΩÌïÕçÖ¡î°Õ’ââ…Öπêπ±Ω›ï»†§•Ùºà¯(ÄÅÌ¡°Ω—Ω}°—µ±Ù(ÄÅÌâÖëùï}°—µ±Ù(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµ•πôºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµπÖµîà˘ÌïÕçÖ¡î°Õ’ââ…Öπê•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµçÖ…êµçΩ’π–à˘ÌçΩ’π—ÙÅÌπ}±Öâï±ÙΩë•ÿ¯(ÄÄΩë•ÿ¯(ΩÑ¯ààà((ÄÄÄÅç°Ö•π}çΩ’π—ÃËÅë•ç—mÕ—»∞Å•π—tÄÙÅÌÙ(ÄÄÄÅç°Ö•π}ÕÖµ¡±ï}•µÖùîËÅë•ç—mÕ—»∞ÅÕ—…tÄÙÅÌÙ(ÄÄÄÅç°Ö•π}•±±’Õ—…Ö—•Ω∏ËÅë•ç—mÕ—»∞ÅÕ—…tÄÙÅÌÙ(ÄÄÄÅôΩ»Å±Öâï∞Å•∏Ä°¡…•ŸÖ—ï}±Öâï±ÃÅΩ»Åmt§Ë(ÄÄÄÄÄÄÄÅç°Ö•∏ÄÙÅ±Öâï±lâç°Ö•∏ât(ÄÄÄÄÄÄÄÅç°Ö•π}çΩ’π—Õmç°Ö•πtÄÙÅç°Ö•π}çΩ’π—Ãπùï–°ç°Ö•∏∞Ä¿§Ä¨Äƒ(ÄÄÄÄÄÄÄÅ•òÅç°Ö•∏ÅπΩ–Å•∏Åç°Ö•π}•±±’Õ—…Ö—•Ω∏Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ°—µ∞ÄÙÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}•±±’Õ—…Ö—•Ω∏°ç°Ö•∏∞Å±Öâï±lâÕ±’úât§(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ°—µ∞Ë(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅç°Ö•π}•±±’Õ—…Ö—•Ωπmç°Ö•πtÄÙÅ°—µ∞(ÄÄÄÄÄÄÄÅ•òÅç°Ö•∏ÅπΩ–Å•∏Åç°Ö•π}ÕÖµ¡±ï}•µÖùîË(ÄÄÄÄÄÄÄÄÄÄÄÅ…ïÖ±}¡…Ωë’ç–ÄÙÅ¡…Ωë’ç—}âÂ}•êπùï–°±Öâï∞πùï–†â…ïÖ±}¡…Ωë’ç—}•êà§§(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ…ïÖ±}¡…Ωë’ç–Ë(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ•µúÄÙÅ}¡…Ωë’ç—}•µÖùî°…ïÖ±}¡…Ωë’ç–§(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ•µúË(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅç°Ö•π}ÕÖµ¡±ï}•µÖùïmç°Ö•πtÄÙÅ•µú(ÄÄÄÅÖπÂ}¡±•}•±±’Õ—…Ö—•Ω∏ÄÙÅâΩΩ∞°ç°Ö•π}•±±’Õ—…Ö—•Ω∏§(ÄÄÄÅ¡±•}ë•Õç±Ö•µï…}πΩ—îÄÙÄ†(ÄÄÄÄÄÄÄÄúÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ëƒ¡¡‡Ä¿Ä¿ÌôΩπ–µÕ•ÈîË¿∏‹……ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà¯ú(ÄÄÄÄÄÄÄÄù9Ωï∏Åµï…≠ï»ÅΩŸï»ÅŸ•ÕïÃÅµïêÅï∏Åïùï∏Å•±±’Õ—…ÖÕ©Ω∏Å§ÅÕ—ïëï–ÅôΩ»Åï–Åï≠—îÅ¡…Ωë’≠—â•±ëî∏Äú(ÄÄÄÄÄÄÄÄúÒÑÅ°…ïòÙàΩΩ¥µ¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»ºàÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ì—ï·–µëïçΩ…Ö—•Ω∏È’πëï…±•πîÏà˘1ïÃÅ°ŸΩ…ôΩ»ÉäHΩÑ¯Ω¿¯ú(ÄÄÄÄÄÄÄÅ•òÅÖπÂ}¡±•}•±±’Õ—…Ö—•Ω∏Åï±ÕîÄàà(ÄÄÄÄ§((ÄÄÄÄåÅMΩ…—ï…•πùÕ°•Õ—Ω…•≠¨ËÄƒ‘∏¿‡ÅµÖπ’ï±∞Å¡•ππ•πúÅÖÿÄÃÅµï…≠ï»Ä¥¯ÄÃ¿∏¿‡Å…ïï±∞(ÄÄÄÄåÅôΩ…°Öπë±ï…â…ïëëîµÕΩ…—ï…•πúÄ°ÕîÅù•–µ°•Õ—Ω…•≠¨§Ä¥¯ÄÃ¿∏¿‡ÅÕÖµµîÅëÖú∞(ÄÄÄÄåÅ¡…•ŸÖ—îÅ±Öâï∞µÕï…•ïπîÅÕµï±—ï–Å•π∏Å§É•∏Åôï±±ïÃÅ…Öπùï…•πúÅ§ÅÕ—ïëï–ÅôΩ»(ÄÄÄÄåÅï∏Åïùï∏Åâ±Ω≠¨É·Ÿï…Õ–∏(ÄÄÄÄå(ÄÄÄÄåÄÃ¿∏¿‡Ä°ÕÖµµîÅëÖú∞Åπ‰Å…’πëî§ËÅâ…’≠ï»É·πÕ≠ï–Åï∏Å—…ïë©îÅ—•±ªô…µ•πúÄ¥¥(ÄÄÄÄåÅïùπîÅ—…Öô•≠≠—Ö±∞Åô•ππïÃÅ•≠≠îÅïπªîÄ°π‰ÅÕ•ëî∞Å±•—îÅ—…Öô•≠¨§∞ÅœîÅŸ§(ÄÄÄÄåÄâ±Ö»ÅΩÕÃÅ•πÕ¡•…ï…îÅÖÿàÅ±ïπÕ¡…•çï»ππºÅÕ•∏ÅôÖ≠—•Õ≠î∞ÅΩâÕï…Ÿï…—î(ÄÄÄÄåÅôΩ…Õ•ëï…ï≠≠ïõ·±ùîÄ°±ïÕ–ÅÖÿÅÖ±–µ—ï≠Õ–Å√îÅëï…ïÃÅâ•±ëï…’—ïπï—–(ÄÄÄÄåÄ»¿»ÿ¥¿‡¥Ã¿Ä¥¥Å%--Åï∏Å√ïÕ—ÖπêÅΩ¥Å¡Ω¡’±Ö…•—ï–ΩÕÖ±ùÕ—Ö±∞∞ÅâÖ…îÅ°ŸÑÅëî(ÄÄÄÄåÅôÖ≠—•Õ¨ÅŸ•Õï»∞ÅŸï…•ô•Õï…âÖ…–ÅŸïêÉîÅâïœ·≠îÅÕ•ëï∏§∞ÅµïêÅï–Å¡Ö»ÅâïŸ•ÕÕ—î(ÄÄÄÄåÅΩµâÂ——ï»Ä°ç’Ÿ’îΩÖ•±•ïÃÅΩúÅ	•Ωµïë•çÃΩU1QI§ÅÕ±•¨ÅÖ–Åëï–Å•≠≠îÅï»Åï∏(ÄÄÄÄåÄƒËƒµ≠Ω¡§∏Å%--ÅπïŸπ–ΩŸ•Õ–ÅπΩîÅÕ—ïêÅ√îÅÕï±ŸîÅÕ•ëï∏Ä¥¥Å…ï∏Å•π—ï…∏(ÄÄÄÄåÅÕΩ…—ï…•πùÕ±Ωù•≠¨∞Åâï≠…ïô—ï–ÅÖÿÅâ…’≠ï»ÅÖ–Åëï–ÅÕ≠Ö∞ÅôΩ…â±§ÅÕ±•¨∏(ÄÄÄÄå(ÄÄÄÄåÄÃƒ∏¿‡ËÅΩ¡¡…•ππï±•úÅ—ïπ≠–Åµ•ë±ï…—•ë•úÄ°ï…Õ—Ö——ïÃÅÖÿÅïùπîÅ—…Öô•≠≠—Ö±∞(ÄÄÄÄåÅï——ï»Å¯ÃÅ∑ïπïëï»§∞Åµï∏Åâ…’≠ï»ÅâïÕ—ïµ—îÅÖ–Å19MAI%I}%9MA%I}=IH(ÄÄÄÄåÅ§ÅÕ—ïëï–ÅÕ≠Ö∞ÅÕ”îÅMPÅ’–Ä»¿»ÿÄ¥¥Å•πùï∏ÅÖ’—ΩµÖ—•Õ¨ÅΩŸï…ùÖπúÅ—•∞(ÄÄÄÄåÅ—…Öô•≠≠âÖÕï…–ÅÕΩ…—ï…•πúÅï»Å¡±Öπ±Öù–Å±ïπùï»Ä°’ÖπÕï—–ÅΩ¥Å–ΩQ4¥(ÄÄÄÄåÅÕ—Ö—•Õ—•≠¨ÅÕ≠’±±îÅâ±§ÅÕÖ—–ÅΩ¡¿Å§Åµï±±Ωµ—•ëï∏§∏Åπë…îÅ≠’∏Å…Öπùï…•πùï∏(ÄÄÄÄåÅªï»Åâ…’≠ï»Åï≠Õ¡±•Õ•—–Åâï»ÅΩ¥Åëï–∞Å•≠≠îÅ√îÅï∏Å—•ëÕô…•Õ–∏(ÄÄÄÄåÅ5ï…≠ï»ÅŸ§Å°Ö»ÅÕΩ¥Å%--ÅÕ”ï»Å§ÅëïππîÅ±•Õ—ï∏Ä°ïπ—ï∏ÅôΩ…ë§Å±ïπÕ¡…•çï»ππº(ÄÄÄÄåÅ•≠≠îÅõ·…ï»Åëï¥∞Åï±±ï»ÅôΩ…ë§ÅπÖŸπï–Åëï…ïÃÅ•≠≠îÅ—Âëï±•úÅ≠’ππîÅ≠Ωâ±ïÃ(ÄÄÄÄåÅ—•∞Åï–ÅÖÿÅ€ï…îÅµï…≠ï»∞Åòπï≠Ã∏Åëï…ïÃÄâ1’µ•ï…îàºâ…ïÕ°—ïç†à§ÅôÖ±±ï»(ÄÄÄÄåÅ—•±âÖ≠îÅ—•∞Åëï∏ÅÕÖµµîÅôΩ…°Öπë±ï…â…ïëëîµÕΩ…—ï…•πùï∏ÅÕΩ¥Åõ·»∏(ÄÄÄÅçÖ…ë}•—ïµÃËÅ±•Õ—m—’¡±ïm•π–∞Å•π–∞Å•π–∞ÅÕ—»∞ÅÕ—…utÄÙÅmt(ÄÄÄÅ’π…Öπ≠ïêÄÙÅ±ï∏°19MAI%I}%9MA%I}=IH§(ÄÄÄÅôΩ»ÅÕ±’úÅ•∏Åâ…Öπë}çΩ’π—ÃË(ÄÄÄÄÄÄÄÅ…Öπ¨ÄÙÅ}19MAI%I}I9,πùï–°Õ±’ú∞Å’π…Öπ≠ïê§(ÄÄÄÄÄÄÄÅçÖ…ë}•—ïµÃπÖ¡¡ïπê††(ÄÄÄÄÄÄÄÄÄÄÄÅ…Öπ¨∞Äµ±ï∏°â…Öπë}…ï—Ö•±ï…Ãπùï–°Õ±’ú∞Ä†§§§∞Äµâ…Öπë}çΩ’π—ÕmÕ±’ùt∞Åâ…Öπë}±Öâï±ÕmÕ±’ùt∞(ÄÄÄÄÄÄÄÄÄÄÄÅ…ïπëï…}â…Öπë}çÖ…ê°Õ±’ú§∞(ÄÄÄÄÄÄÄÄ§§(ÄÄÄÅôΩ»Åç°Ö•∏∞ÅçΩ’π–Å•∏Åç°Ö•π}çΩ’π—Ãπ•—ïµÃ†§Ë(ÄÄÄÄÄÄÄÅÕ’ââ…ÖπêÄÙÅAI%YQ}1	1}MU		I9Lπùï–°ç°Ö•∏∞Åç°Ö•∏§(ÄÄÄÄÄÄÄÅ…Öπ¨ÄÙÅ}19MAI%I}I9,πùï–°Õ’ââ…Öπêπ±Ω›ï»†§∞Å’π…Öπ≠ïê§(ÄÄÄÄÄÄÄÅçÖ…ë}•—ïµÃπÖ¡¡ïπê††(ÄÄÄÄÄÄÄÄÄÄÄÅ…Öπ¨∞Ä¥ƒ∞ÄµçΩ’π–∞ÅÕ’ââ…Öπê∞(ÄÄÄÄÄÄÄÄÄÄÄÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}ç°Ö•π}çÖ…ê°ç°Ö•∏∞ÅçΩ’π–∞Åç°Ö•π}ÕÖµ¡±ï}•µÖùîπùï–°ç°Ö•∏§∞Åç°Ö•π}•±±’Õ—…Ö—•Ω∏πùï–°ç°Ö•∏§§∞(ÄÄÄÄÄÄÄÄ§§(ÄÄÄÅçÖ…ë}•—ïµÃπÕΩ…–°≠ï‰ı±ÖµâëÑÅ•—ï¥ËÅ•—ïµlË—t§(ÄÄÄÅâ…Öπë}çÖ…ëÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°•—ïµl—tÅôΩ»Å•—ï¥Å•∏ÅçÖ…ë}•—ïµÃ§((ÄÄÄÅëïòÅ…ïπëï…}çÖ—ïùΩ…Â}…Ω‹°Õ±’úËÅÕ—»∞ÅçÖ—ïùΩ…‰ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ•çΩ∏ÄÙÅQ=Ie}%=9Lπùï–°Õ±’ú∞Äàà§(ÄÄÄÄÄÄÄÅçΩ±Ω»ÄÙÅQ=Ie}=1=ILπùï–°Õ±’ú∞Äââ±’îà§(ÄÄÄÄÄÄÄÅ—Öù±•πîÄÙÅQ=Ie}Q1%9Lπùï–°Õ±’ú∞Äàà§(ÄÄÄÄÄÄÄÅâúÄÙÅQ=Ie}	πùï–°Õ±’ú§(ÄÄÄÄÄÄÄÅâù}°—µ∞ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÅòúÒ•µúÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹µâúàÅÕ…åÙàΩÕ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâúµÌâùÙ¥Ã»¿π›ïâ¿àÄú(ÄÄÄÄÄÄÄÄÄÄÄÅòùÕ…çÕï–ÙàΩÕ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâúµÌâùÙ¥Ã»¿π›ïâ¿ÄÃ»¡‹∞ÄΩÕ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâúµÌâùÙ¥ÿƒÃπ›ïâ¿ÄÿƒÕ‹àÄú(ÄÄÄÄÄÄÄÄÄÄÄÅòùÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§Ä»Ã¡¡‡∞Ä°µ•∏µ›•ë—†ËÄ‹¿¡¡‡§ÄÃ–¡¡‡∞Ä»¿¡¡‡àÄú(ÄÄÄÄÄÄÄÄÄÄÄÅòùÖ±–ÙààÅ›•ë—†ÙàÿƒÃàÅ°ï•ù°–Ùà»‹ÃàÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯ú(ÄÄÄÄÄÄÄÄ§Å•òÅâúÅï±ÕîÄàà(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒÑÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹ÅçÖ–µÌïÕçÖ¡î°çΩ±Ω»•ÙàÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÌïÕçÖ¡î°Õ±’ú•Ùºà¯(ÄÅÌâù}°—µ±Ù(ÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹µ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÌçΩ±Ω…Ùµ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÌçΩ±Ω…Ù§Ïà¯(ÄÄÄÄÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩÕŸú¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹µ—ï·–à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹µ±Öâï∞à˘ÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞ât•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹µëïÕåà˘ÌïÕçÖ¡î°—Öù±•πî•ÙΩë•ÿ¯(ÄÄΩë•ÿ¯(ÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω‹µÖ……Ω‹àÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»∏–àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêà¯Ò¡Ö—†ÅêÙâ4‘Äƒ…†ƒ—4ƒÃÄŸ∞ÿÄÿ¥ÿÄÿàº¯ΩÕŸú¯ΩÕ¡Ö∏¯(ΩÑ¯ààà((ÄÄÄÅçÖ—ïùΩ…Â}…Ω›Õ}°—µ∞ÄÙÄâq∏àπ©Ω•∏†(ÄÄÄÄÄÄÄÅ…ïπëï…}çÖ—ïùΩ…Â}…Ω‹°Õ±’ú∞ÅçÖ—ïùΩ…‰§ÅôΩ»ÅÕ±’ú∞ÅçÖ—ïùΩ…‰Å•∏ÅçÖ—Ö±ΩùlâçÖ—ïùΩ…•ïÃâtπ•—ïµÃ†§(ÄÄÄÄ§((ÄÄÄÅù’•ëï}çÖ…ëÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°…ïπëï…}ù’•ëï}—•±î°Õ±’ú∞Åú§ÅôΩ»ÅÕ±’ú∞ÅúÅ•∏ÅU%}=9Q9Pπ•—ïµÃ†§§((ÄÄÄÅπ}…ï—Ö•±ï…ÃÄÙÅ±ï∏°ÌΩlâ…ï—Ö•±ï»âtÅôΩ»Å¿Å•∏ÅçÖ—Ö±Ωùlâ¡…Ωë’ç—ÃâtÅôΩ»ÅºÅ•∏Å¡lâΩôôï…ÃâuÙ§(ÄÄÄÅπ}¡…Ωë’ç—ÃÄÙÅ±ï∏°çÖ—Ö±Ωùlâ¡…Ωë’ç—Ãât§(ÄÄÄÅ°Ωµï}ôÖ≈}°—µ∞∞Å°Ωµï}ôÖ≈}Õç°ïµÑÄÙÅ}…ïπëï…}ôÖ≈}â±Ωç¨°!=5}D§((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘	•±±•ùîÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ≠Ωπ—Ö≠—±•πÕï»Åô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅY§ÅŸ•Õï»ÅÖ±±—•êÅâ•±±•ùÕ—îÅ—•±ù©ïπùï±•ùîÅ—•±â’ê∏à¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1Ùºà¯)Ì}Ωù}µï—Ñ†ù	•±±•ùîÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞ÄùMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ≠Ωπ—Ö≠—±•πÕï»Åô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅY§ÅŸ•Õï»ÅÖ±±—•êÅâ•±±•ùÕ—îÅ—•±ù©ïπùï±•ùîÅ—•±â’ê∏ú∞Å	M}UI0Ä¨Äúºú•Ù)Ì°Ωµï}ôÖ≈}Õç°ïµÖÙ)Ì=9Q}1%9-MÙ(Ò±•π¨Å…ï∞Ùâ¡…ï±ΩÖêàÅÖÃÙâ•µÖùîàÅ—Â¡îÙâ•µÖùîΩ›ïâ¿àÅµïë•ÑÙà°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§àÅôï—ç°¡…•Ω…•—‰Ùâ°•ù†àÅ•µÖùïÕ…çÕï–ÙàΩÕ—Ö—•åΩ°ï…ºΩïÂî¥‘ÿ¿π›ïâ¿Ä‘ÿ¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩïÂî¥‡–¿π›ïâ¿Ä‡–¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩïÂî¥ƒƒ»¿π›ïâ¿Äƒƒ»¡‹àÅ•µÖùïÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ»¿¡¡‡§Ä‘–¡¡‡∞Ä–…Ÿ‹à¯(ÒÕ—Â±î˘ÌM!I}MQe1Ù)ÌAI%YQ}1	1}%11UMQIQ%=9}MQe1Ù(π°ï…ºµ¡Öπï∞ÅÌÏÅ¡Öëë•πúËÄ¿ÏÅıÙ(π°ï…ºÅÌÏ(ÄÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏ(ÄÅ¡Öëë•πúËÄ·¡‡Ä¿Ä»—¡‡Ï)ıÙ(π°ï…ºµçΩπ—ïπ–ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅËµ•πëï‡ËÄ»ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒŸ¡‡ÏÅıÙ(π°ï…ºµµïë•ÑÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(π°ï…ºµÕ’â—ï·–ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰—…ï¥ÏÅµÖ‡µ›•ë—†ËÄ–‡¡¡‡ÏÅıÙ(º®ÅO·≠ïôï±—ï–Åï»ÅÕ•ëïπÃÅŸ•≠—•ùÕ—îÅï±ïµïπ–ËÅ—Â≠¨Åâ≥îÅ≠Öπ–∞Å—Âëï±•úÅôΩ≠’Õ…•πú∞Åâ≥îÅ≠πÖ¡¿∏Ä®º(π°ï…ºÄπÕïÖ…ç†µ•π¡’–ÅÌÏÅâΩ…ëï»ËÄ…¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúµ—Ω¿ËÄƒ›¡‡ÏÅ¡Öëë•πúµâΩ——Ω¥ËÄƒ›¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä·¡‡Ä»—¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒ–§ÏÅıÙ(π°ï…ºÄπÕïÖ…ç†µ•π¡’–ÈôΩç’ÃÅÌÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’îµëÖ…¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä¿Ä¿Ä’¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏»»§∞Ä¿Ä·¡‡Ä»—¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒ–§ÏÅıÙ(π°ï…ºÄπÕïÖ…ç†µâ—∏ÅÌÏÅ…•ù°–ËÄ·¡‡ÏÅ—Ω¿ËÄ·¡‡ÏÅâΩ——Ω¥ËÄ·¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ≈¡‡ÏÅıÙ)µïë•ÑÄ°µÖ‡µ›•ë—†ËÄÿ‰Â¡‡§ÅÌÏ(ÄÄπ°ï…ºÄπÕïÖ…ç†µ•π¡’–ÅÌÏÅôΩπ–µÕ•ÈîËÄ≈…ï¥ÏÅ¡Öëë•πúµ±ïô–ËÄ–—¡‡ÏÅ¡Öëë•πúµ…•ù°–ËÄ‡—¡‡ÏÅıÙ(ÄÄπ°ï…ºÄπÕïÖ…ç†µ•çΩ∏ÅÌÏÅ±ïô–ËÄƒ’¡‡ÏÅıÙ(ÄÄπ°ï…ºÄπÕïÖ…ç†µâ—∏ÅÌÏÅ¡Öëë•πúËÄ¿ÄƒŸ¡‡ÏÅıÙ)ıÙ(π—…’Õ–µçÖ…êÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅùÖ¿ËÄƒ—¡‡ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅ¡Öëë•πúËÄƒŸ¡‡ÏÅıÙ(π—…’Õ–µçÖ…êµ•çΩ∏ÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄ–¡¡‡ÏÅ°ï•ù°–ËÄ–¡¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(π—…’Õ–µçÖ…êµ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄ»¡¡‡ÏÅ°ï•ù°–ËÄ»¡¡‡ÏÅıÙ(π—…’Õ–µçÖ…êµ—•—±îÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰’…ï¥ÏÅµÖ…ù•∏ËÄ¿Ä¿Ä—¡‡ÏÅıÙ(π—…’Õ–µçÖ…êµ—ï·–ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡—…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(π—…’Õ–µÕ—…•¿ÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»Ä≈ô»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅ¡Öëë•πúËÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄ–¡¡‡Ä¿Ä¿ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(π—…’Õ–µ•—ï¥ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(π—…’Õ–µ•—ï¥µ•çΩ∏ÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄÃ—¡‡ÏÅ°ï•ù°–ËÄÃ—¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅıÙ(π—…’Õ–µ•—ï¥µ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄƒ›¡‡ÏÅ°ï•ù°–ËÄƒ›¡‡ÏÅıÙ(π—…’Õ–µ•—ï¥ÅÕ—…ΩπúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ≈…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π—…’Õ–µ•—ï¥ÅÕ¡Ö∏ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(πÕïç—•Ω∏µ°ïÖëï»ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅâÖÕï±•πîÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅµÖ…ù•∏ËÄÃ…¡‡Ä¿Äƒ…¡‡ÏÅÕç…Ω±∞µµÖ…ù•∏µ—Ω¿ËÄ»¡¡‡ÏÅıÙ(πÕïç—•Ω∏µ°ïÖëï»Èô•…Õ–µΩòµ—Â¡îÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄ¿ÏÅıÙ(πÕïç—•Ω∏µ°ïÖëï»Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω›ÃÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹ÅÌÏÄ¥µçÖ–µâúËÄçŸÏÄ¥µçÖ–µâΩ…ëï»ËÄçŸ—ÏÄ¥µçÖ–µÖççïπ–ËÅŸÖ»†¥µâ±’î§ÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅ•ÕΩ±Ö—•Ω∏ËÅ•ÕΩ±Ö—îÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ…¡‡ÏÅµ•∏µ°ï•ù°–ËÄ‹Ÿ¡‡ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µçÖ–µâú§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µçÖ–µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ—¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏ƒ’Ã∞ÅâΩ…ëï»µçΩ±Ω»Ä¿∏ƒ’Ã∞ÅâΩ‡µÕ°ÖëΩ‹Ä¿∏ƒ’ÃÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹πçÖ–µâ±’îÅÌÏÄ¥µçÖ–µâúËÄçŸÏÄ¥µçÖ–µâΩ…ëï»ËÄçŸ—ÏÄ¥µçÖ–µÖççïπ–ËÄå»‘ÿÕÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹πçÖ–µÖµâï»ÅÌÏÄ¥µçÖ–µâúËÄç	ÏÄ¥µçÖ–µâΩ…ëï»ËÄç—Ÿ	ÏÄ¥µçÖ–µÖççïπ–ËÄçÂ¿…ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹πçÖ–µÕ≠‰ÅÌÏÄ¥µçÖ–µâúËÄç’ÏÄ¥µçÖ–µâΩ…ëï»ËÄçÕÕ‡ÏÄ¥µçÖ–µÖççïπ–ËÄå—·‡ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹πçÖ–µ±ÖŸïπëï»ÅÌÏÄ¥µçÖ–µâúËÄç’¡ÏÄ¥µçÖ–µâΩ…ëï»ËÄç≈·ÿÏÄ¥µçÖ–µÖççïπ–ËÄå·›ÿÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹πçÖ–µçΩ…Ö∞ÅÌÏÄ¥µçÖ–µâúËÄç…–ÏÄ¥µçÖ–µâΩ…ëï»ËÄçŸŸÏÄ¥µçÖ–µÖççïπ–ËÄç‡ÿÃ›ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹È°ΩŸï»∞ÄπçÖ—ïùΩ…‰µ…Ω‹ÈôΩç’ÃµŸ•Õ•â±îÅÌÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µçÖ–µÖççïπ–§ÏÅıÙ(º®Å	Ö≠ù…’ππÕâ•±ëï–Å±•ùùï»ÅâÖ¨Å•ππ°Ω±ëï–ÅΩúÅôÖëï»Å’–ÅµΩ–ÅŸïπÕ—…î∞ÅœîÅ—ï≠Õ—ï∏ÅÖ±±—•êÅÕ”ï»Å√îÅëï∏Å±ÂÕîÅ¡ÖÕ—ï±±ï∏∏Ä®º(πçÖ—ïùΩ…‰µ…Ω‹µâúÅÌÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ—Ω¿ËÄ¿ÏÅ…•ù°–ËÄ¿ÏÅ°ï•ù°–ËÄƒ¿¿îÏÅ›•ë—†ËÄ‘»îÏÅËµ•πëï‡ËÄ¥ƒÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅΩâ©ïç–µ¡ΩÕ•—•Ω∏ËÄƒ¿¿îÄ‘¿îÏÅ¡Ω•π—ï»µïŸïπ—ÃËÅπΩπîÏÄµ›ïâ≠•–µµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–‘î§ÏÅµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–‘î§ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹µ•çΩ∏ÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄ–¡¡‡ÏÅ°ï•ù°–ËÄ–¡¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä≈¡‡ÄÕ¡‡Å…ùâÑ†ƒƒ∞ÄÃ‹∞Äÿ‰∞Ä¿∏¿‡§ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹µ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄ»¡¡‡ÏÅ°ï•ù°–ËÄ»¡¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹µ—ï·–ÅÌÏÅô±ï‡ËÄƒÏÅµ•∏µ›•ë—†ËÄ¿ÏÅµÖ‡µ›•ë—†ËÄ‘‡îÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹µ±Öâï∞ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰’…ï¥ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹µëïÕåÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‘¿¿ÏÅçΩ±Ω»ËÄå–‹‘‘ÿ‰ÏÅµÖ…ù•∏µ—Ω¿ËÄ…¡‡ÏÅ±•πîµ°ï•ù°–ËÄƒ∏Ã‘ÏÅıÙ(º®ÅA•∞ËÅÖ±±—•êÅÕÂπ±•úÄ°±•—ï∏§Å√îÅµΩâ•∞Ω—Ω’ç†∞ÅŸ•ÕïÃÅŸïêÅ°ΩŸï»Å√îÅëïÕ≠—Ω¿Ä®º(πçÖ—ïùΩ…‰µ…Ω‹µÖ……Ω‹ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ…•ù°–ËÄƒ¡¡‡ÏÅ—Ω¿ËÄ‘¿îÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¥‘¿î§ÏÅ›•ë—†ËÄ»·¡‡ÏÅ°ï•ù°–ËÄ»·¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅ…ùâÑ†»‘‘∞Ä»‘‘∞Ä»‘‘∞Ä¿∏‡‘§ÏÅçΩ±Ω»ËÅŸÖ»†¥µçÖ–µÖççïπ–§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä≈¡‡Ä—¡‡Å…ùâÑ†ƒƒ∞ÄÃ‹∞Äÿ‰∞Ä¿∏ƒ»§ÏÅıÙ(πçÖ—ïùΩ…‰µ…Ω‹µÖ……Ω‹ÅÕŸúÅÌÏÅ›•ë—†ËÄƒ—¡‡ÏÅ°ï•ù°–ËÄƒ—¡‡ÏÅıÙ(πâ…Öπêµù…•êÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†»∞Ä≈ô»§ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(πâ…ÖπêµçÖ…êÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµ•∏µ›•ë—†ËÄ¿ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ—¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πâ…ÖπêµçÖ…êÈ°ΩŸï»ÅÌÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(πâ…ÖπêµçÖ…êµâÖëùîÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄÃŸ¡‡ÏÅ°ï•ù°–ËÄÃŸ¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅıÙ(πâ…ÖπêµçÖ…êµ•πôºÅÌÏÅµ•∏µ›•ë—†ËÄ¿ÏÅıÙ(πâ…ÖπêµçÖ…êµπÖµîÅÌÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏»‘ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅ—ï·–µΩŸï…ô±Ω‹ËÅï±±•¡Õ•ÃÏÅ›°•—îµÕ¡ÖçîËÅπΩ›…Ö¿ÏÅıÙ(πâ…ÖπêµçÖ…êµçΩ’π–ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(πâ…ÖπêµçÖ…êµ¡°Ω—ºÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ)ÌU%}Q%1}MQe1Ù(º®Å5ï…≠îµ≠Ω…—ïπîËÅâÂ——ï–Åô…ÑÅï∏Å±•—ï∏ÅÕ•…≠ï∞µ±ΩùºÅ—•∞Åï–ÅÕ”·……îÅ¡…Ωë’≠—â•±ëî(ÄÄÄ†»¿»ÿ¥¿‡¥Ã¿∞Åï——ï»Åâ…’≠ï…ïπÃÉ·πÕ≠îÅΩ¥ÉîÅ±•ùπîÅ±ïπÕ¡…•çï»ππºÅÕ•∏(ÄÄÅµΩâ•±Õ•ëî§∏Å=¡¡…•ππï±•úÅ-U8Å’πëï»Ä‹¿¡¡‡Ä°AÅâï°Ω±ë–Åëï∏Å≠Ωµ¡Ö≠—î(ÄÄÅ±Ωùº≠πÖŸ∏µ…Öëï∏§∞Åµï∏Åâ…’≠ï»ÅâÑÅÕÖµµîÅëÖúÅΩ¥ÅÖ–Åëï–Åâ•±ëïõ·…—îÅ≠Ω…—ï–(ÄÄÅÕ≠Ö∞Åù©ï±ëîÅ√îÅAÅΩùœîÄ¥¥Åë•ÕÕîÅ…ïù±ïπîÅï»Åëï…ôΩ»ÅUQ8Åµïë•Ñµ≈’ï…‰∞(ÄÄÅù©ï±ëï»ÅÖ±±îÅâ…ïëëï»∏Å-Ω…–ÅUQ8Åï–Åâ•±ëîÄ°ÕÖµ¡±ï}•µÖùîÅµÖπù±ï–§(ÄÄÅâï°Ω±ëï»Åëï∏ÅŸÖπ±•ùîÅ±ΩùºµÕ•…≠ï∞µ…Öëï∏Å’ÖπÕï—–Åâ…ïëëîÄ¥¥Å•πùï∏Å—Ωµ–º(ÄÄÅ≠πï≠–Å≠Ω…–∏(ÄÄÅ	Öëùï∏Ä°±ΩùºΩ•π•—•Ö∞§ÅŸÖ»ÅΩ¡¡…•ππï±•úÅÕ≠©’±–Å°ï»Ä°ë•Õ¡±Ö‰ÈπΩπî§∏ÅAÀ·Ÿëî(ÄÄÄ»¿»ÿ¥¿‡¥Ã¿Åï∏ÅÖâÕΩ±’—–Å¡ΩÕ•Õ©Ωπï…–Äâç°•¿àÅΩ¡√îÅ¡…Ωë’≠—â•±ëï–Ä°ï——ï»Åï–(ÄÄÅµΩç≠’¿Åâ…’≠ï…ï∏ÅŸ•Õ—î§Ä¥¥Å…ïŸï…Õï…–ÅÕÖµµîÅëÖúËÅâ…’≠ï…ï∏ÅœîÅ…ïÕ’±—Ö—ï–(ÄÄÅ±•ŸîÅΩúÅÕÂπ—ïÃÅëï–ÅœîÅìï…±•úÅ’–Ä°âÖëùï∏Åâ±îÅôΩ»ÅΩô—îÅôΩ»ÅÕµÖ∞Ω≠’——ï–ÅÖÿ(ÄÄÅôΩ»Å±ÖπùîÅµï…≠ïπÖŸ∏Ω±Ωùºµ¡…Ω¡Ω…Õ©Ωπï»∞ÅÕîÅÕ≠©ï…µâ•±ëî§∏ÅQ•±âÖ≠îÅ—•∞(ÄÄÅë•Õ¡±Ö‰ÈπΩπîÄ¥¥Å≠Ω…–ÅµïêÅâ•±ëîÅŸ•Õï»ÅªîÅ-U8Åâ•±ëîÄ¨ÅπÖŸ∏ΩÖπ—Ö±∞Å’πëï»∞(ÄÄÅ•πùï∏Å±ΩùºµΩŸï…±Ö‰∏ÅMÖµµîÅïπë…•πúÅÖŸëï≠≠ï–ÅΩúÅô•≠Õï–Åï–Å…ïï±–Åâ…’≠≠ï–(ÄÄÅ≠Ω…–ÅÕÖµ—•ë•úÄ°’ïπë…ï–ÅÖÿÅëïππîÅ…ïŸï…Õï…•πùï∏§ËÅ¡…•ŸÖ—îÅ±Öâï∞µ≠©ïëïπïÃ(ÄÄÅ≠Ω…–Ä°ÂïDΩ•]ïÖ»ΩÖÕÂŸ•Õ•Ω∏ΩÕçïπê§Å°ÖëëîÅ1I$Åõï—–Äπ°ÖÃµ¡°Ω—ºÄ°•πùï∏(ÄÄÅÕÖµ¡±ï}•µÖùîÅŸÖ»Å…ïùπï–Å’–ÅôΩ»Åëï¥§Ä¥¥Å√îÅµΩâ•∞ÅôÖ±–ÅëîÅ—•±âÖ≠îÅ—•∞Åëï∏(ÄÄÅùÖµ±îÅÕµÖ±îÅ…Öêµ±ÖÂΩ’—ï∏ÅµïêÅï∏Ä‘…¡‡Å±ΩùºµâÖëùî∞ÅÕΩ¥Å≠±ïµ—îÅπÖŸπï–Åπïê(ÄÄÅ—•∞Äƒ¥–ÅâΩ≠Õ—ÖŸï»Ä†â∏∏∏à∞Äâ§∏∏∏à∞ÄâÕå∏∏∏à§∏Å•ÕÕîÅ°Ö»ÅôΩ…—ÕÖ—–Åï–Åï≠—î(ÄÄÅ¡…Ωë’≠—â•±ëîΩ•±±’Õ—…ÖÕ©Ω∏∞ÅâÖ…îÅ’—ï∏Å±ΩùºµΩŸï…±ÖÂï∏ÅΩ¡√î∏Ä®º(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÅÌÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅÖ±•ù∏µ•—ïµÃËÅÕ—…ï—ç†ÏÅùÖ¿ËÄ¿ÏÅ¡Öëë•πúËÄ¿ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅıÙ(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÄπâ…ÖπêµçÖ…êµ¡°Ω—ºÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅ›•ë—†ËÄƒ¿¿îÏÅÖÕ¡ïç–µ…Ö—•ºËÄ–ÄºÄÃÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅıÙ(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÄπâ…ÖπêµçÖ…êµ¡°Ω—ºÅ•µúÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩπ—Ö•∏ÏÅ¡Öëë•πúËÄƒ¡¡‡ÏÅâΩ‡µÕ•È•πúËÅâΩ…ëï»µâΩ‡ÏÅıÙ(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÄπâ…ÖπêµçÖ…êµ¡°Ω—ºÄπ¡±§µô…ÖµîÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅÖÕ¡ïç–µ…Ö—•ºËÄ‘ÿ¿ÄºÄ»»‘ÏÅçΩπ—Ö•πï»µ—Â¡îËÅ•π±•πîµÕ•ÈîÏÅıÙ(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÄπâ…ÖπêµçÖ…êµâÖëùîÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÄπâ…ÖπêµçÖ…êµ•πôºÅÌÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ—¡‡Äƒ—¡‡ÏÅıÙ(πâ…ÖπêµçÖ…êπ°ÖÃµ¡°Ω—ºÄπâ…ÖπêµçÖ…êµπÖµîÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‰·…ï¥ÏÅ›°•—îµÕ¡ÖçîËÅπΩ…µÖ∞ÏÅıÙ(πµΩâ•±îµΩπ±‰µâ±Ωç¨ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ)µïë•ÑÄ°µÖ‡µ›•ë—†ËÄÿ‰Â¡‡§ÅÌÏ(ÄÄπ—…’Õ–µçÖ…êÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(ÄÄº®Å-Ö—ïùΩ…•ï»Åô±Â——ï–Å’πëï»Å5ï…≠ï»Å√îÅµΩâ•∞∞ÅΩúÅÕï±ŸîÄâ5ï…≠ï»à¥(ÄÄÄÄÅΩŸï…Õ≠…•ô—ï∏ÅÕ≠©’±ïÃÅ°ï±–Ä¥¥Å…ï—–Åô…ÑÅœ·¨Å—•∞Åµï…≠îµ≠Ω…—ïπî∞ÅÕÖµµî(ÄÄÄÄÅ∑·πÕ—ï»ÅÕΩ¥Å±ïπÕ¡…•çï»ππºÅÕ•∏ÅµΩâ•±Õ•ëîÄ°â…’≠ï…ïπÃÅïùï–É·πÕ≠î∞(ÄÄÄÄÄ»¿»ÿ¥¿‡¥Ã¿§∏ÅQºÅ≠Ω¡•ï»ÅÖÿÅ≠Ö—ïùΩ…§µâ±Ω≠≠ï∏Åô•ππïÃÅ§ÅµÖ…≠’¡ï∏(ÄÄÄÄÄ°ëïÕ≠—Ω¿µΩπ±‰µâ±Ωç¨Å•ππ§Å°ï…ºµ¡Öπï∞∞ÅµΩâ•±îµΩπ±‰µâ±Ωç¨Å…ï—–Åï——ï»(ÄÄÄÄÅµï…≠îµ…’—ïπï——ï–§Ä¥¥Å≠’∏ÅMLµë•Õ¡±Ö‰ÅÕ≠•±±ï»Åëï¥∞Å•πùï∏Å)L∏ÅAÅï»(ÄÄÄÄÅëï…µïêÅô’±±Õ—ïπë•úÅ’À·…–ËÅÕÖµµîÅµÖ…≠’¿∞ÅÕÖµµîÅ≠±ÖÕÕï»∞Åë•ÕÕîÅ…ïù±ïπî(ÄÄÄÄÅù©ï±ëï»Å≠’∏Å’πëï»Ä‹¿¡¡‡∏Ä®º(ÄÄçµï…≠ï»ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(ÄÄπëïÕ≠—Ω¿µΩπ±‰µâ±Ωç¨ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(ÄÄπµΩâ•±îµΩπ±‰µâ±Ωç¨ÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅıÙ)ıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‘ÿ¡¡‡§ÅÌÏÄπâ…Öπêµù…•êÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†Ã∞Ä≈ô»§ÏÅıÙÄπ—…’Õ–µÕ—…•¿ÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†–∞Ä≈ô»§ÏÅıÙÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§ÅÌÏ(ÄÄπâ…Öπêµù…•êÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†–∞Ä≈ô»§ÏÅıÙ(ÄÄπÕïÖ…ç†µ•π¡’–ÅÌÏÅ¡Öëë•πúËÄƒ·¡‡Äƒ»¡¡‡Äƒ·¡‡Ä‘…¡‡ÏÅôΩπ–µÕ•ÈîËÄƒ∏ƒ’…ï¥ÏÅıÙ(ÄÄπÕïÖ…ç†µ•çΩ∏ÅÌÏÅ±ïô–ËÄ»…¡‡ÏÅ›•ë—†ËÄ»…¡‡ÏÅ°ï•ù°–ËÄ»…¡‡ÏÅıÙ(ÄÄπÕïÖ…ç†µâ—∏ÅÌÏÅ¡Öëë•πúËÄ¿Ä»Ÿ¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰·…ï¥ÏÅıÙ((ÄÄº®Å-Ωµ¡Ö≠–Å°ï…ºÄ°çÑ∏ÄÃÿ¿¥–¿¿Å¡‡§ËÅ±ÂÕ–Å≠Ω…–∞Åâ•±ëï–Åù±•»Å•π∏Åô…ÑÅ£·Â…îÅµïêÅï∏(ÄÄÄÄÅµÂ¨ÅµÖÕ≠îÅµΩ–ÅŸïπÕ—…î∞ÅÕ±•¨ÅÖ–Åëï–Å•≠≠îÅÕï»Å’–ÅÕΩ¥Å—ºÅÕï¡Ö…Ö—îÅâΩ≠Õï»∏(ÄÄÄÄÄπ°ï…ºµµïë•ÑÅõï»ÅΩŸï…ô±Ω‹È°•ëëï∏Å-U8Å√îÅÕïúÅÕï±ÿÄ°•≠≠îÅ√îÄπ°ï…º§∞Åï±±ï…Ã(ÄÄÄÄÅŸ•±±îÅœ·≠ïôΩ…Õ±ÖùïπîÅâ±§Å≠±•¡¡ï–ÅÖÿÅ≠Ω…—≠Öπ—ï∏∏Ä®º(ÄÄπ°ï…ºµ¡Öπï∞ÅÌÏÅâÖç≠ù…Ω’πêËÅπΩπîÏÅâΩ…ëï»ËÅπΩπîÏÅ¡Öëë•πúËÄ¿ÏÅâΩ‡µÕ°ÖëΩ‹ËÅπΩπîÏÅıÙ(ÄÄπ°ï…ºÅÌÏ(ÄÄÄÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§Ï(ÄÄÄÅâΩ…ëï»µ…Öë•’ÃËÄ»—¡‡Ï(ÄÄÄÅâÖç≠ù…Ω’πêËÅ±•πïÖ»µù…Öë•ïπ–†ƒ¿¡ëïú∞ÄçÄ¿î∞ÄçŸÂÄ‘¿î∞ÄçÂ≈Äƒ¿¿î§Ï(ÄÄÄÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§Ï(ÄÄÄÅ¡Öëë•πúËÄÃ—¡‡Ä–·¡‡ÄÃ¡¡‡Ï(ÄÅıÙ(ÄÄπ°ï…ºµçΩπ—ïπ–ÅÌÏÅµÖ‡µ›•ë—†ËÄ‘ÿîÏÅùÖ¿ËÄƒ—¡‡ÏÅıÙ(ÄÄº®Å1•—–Åµ•πë…îΩ—…Âùùï…îÅïπ∏Åõ·»Ä†»¿»ÿ¥¿‰¥»‹∞Å-Ö§ËÄâ≠Ö∏ÅŸï∞Å€ô…îÅ√îÄƒ(ÄÄÄÄÅ±•π©î¸à§Ä¥¥ÅŸïêÄƒ¿»—¡‡Åâ…ïëëîÄ°ëï»ÅëïππîÅ—ºµ≠Ω±Ωππîµ±ÖÂΩ’—ï∏ÅÖ≠≠’…Ö–(ÄÄÄÄÅÕ—Ö…—ï»§Å°ÖëëîÄâ•π∏Åâ•±±•ùÕ—îÅ≠Ωπ—Ö≠—±•πÕï»àÅ9U10ÅµÖ…ù•∏Å—•∞(ÄÄÄÄÅ≠Ωπ—ïπï…ï∏Ä†–‡‹∞‡Ÿ¡‡Å—ï≠Õ–Å§Åï∏Ä–‡‹∞‡Ÿ¡‡Åâ…ïêÅ≠Ω±ΩππîÄ¥¥Å•ëïπ—•Õ¨Å√î(ÄÄÄÄÅ¡•≠Õï±ï–§∞ÅœîÅëï∏Åµ•πÕ—îÅôΩπ–µµï—…•≠¨µôΩ…Õ≠©ï±∞Ä°òπï≠Ã∏Å]•πëΩ›Ãú(ÄÄÄÄÅ±ïÖ…QÂ¡îµ…ïπëï…•πúÅÖÿÅM¡ÖçîÅ…Ω—ïÕ¨ÅŸÃ∏ÅëïππîÉ·≠—ï∏ÅÕ•∏(ÄÄÄÄÅ—ïÕ–µâ…Ω›Õï»§ÅŸÖ»ÅπΩ¨Å—•∞ÉîÅŸ•¡¡îÅëï∏ÅΩŸï»Å§Å—ºÅ±•π©ï»∏ÅMïπ≠ï–(ÄÄÄÄÅç±Öµ¿µï∏Åù•»Å¯ÿ¡¡‡Å…ïï±∞ÅµÖ…ù•∏ÅŸïêÄƒ¿»—¡‡Å§ÅÕ—ïëï–ÅôΩ»Ä¡¡‡∞Å’—ï∏Éî(ÄÄÄÄÅïπë…îÅÕï±ŸîÅ ƒµ—ï≠Õ—ï∏Ä°M<µª·Â—…Ö±–§∏Ä®º(ÄÄπ°ï…ºµ°ïÖë•πúÅ†ƒÅÌÏÅôΩπ–µÕ•ÈîËÅç±Öµ¿†ƒ∏‹’…ï¥∞Ä»∏ŸŸ‹∞Ä»∏Ã’…ï¥§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ƒ‘ÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(ÄÄπ°ï…ºµµïë•ÑÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ—Ω¿ËÄ¿ÏÅ…•ù°–ËÄ¿ÏÅâΩ——Ω¥ËÄ¿ÏÅ›•ë—†ËÄ–ÿîÏÅËµ•πëï‡ËÄƒÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅâΩ…ëï»µ…Öë•’ÃËÄ¿Ä»—¡‡Ä»—¡‡Ä¿ÏÅ¡Ω•π—ï»µïŸïπ—ÃËÅπΩπîÏÄµ›ïâ≠•–µµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–¿î§ÏÅµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–¿î§ÏÅıÙ(ÄÄπ°ï…ºµµïë•ÑÅ¡•ç—’…îÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅıÙ(ÄÄπ°ï…ºµµïë•ÑÅ•µúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅΩâ©ïç–µ¡ΩÕ•—•Ω∏ËÅ…•ù°–Åçïπ—ï»ÏÅıÙ(ÄÄπ°ï…ºÄπÕïÖ…ç†µ•π¡’–ÅÌÏÅ¡Öëë•πúËÄ»¡¡‡Äƒ–¡¡‡Ä»¡¡‡Ä‘·¡‡ÏÅôΩπ–µÕ•ÈîËÄƒ∏……ï¥ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Äƒ¡¡‡ÄÃ¡¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒÿ§ÏÅıÙ(ÄÄπ°ï…ºÄπÕïÖ…ç†µ•çΩ∏ÅÌÏÅ±ïô–ËÄ»—¡‡ÏÅıÙ(ÄÄπ°ï…ºÄπÕïÖ…ç†µâ—∏ÅÌÏÅ¡Öëë•πúËÄ¿ÄÃ…¡‡ÏÅôΩπ–µÕ•ÈîËÄ≈…ï¥ÏÅıÙ(ÄÄπ—…’Õ–µçÖ…êÅÌÏÅâÖç≠ù…Ω’πêËÅ—…ÖπÕ¡Ö…ïπ–ÏÅâΩ…ëï»ËÅπΩπîÏÅ¡Öëë•πúËÄ¿ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ…¡‡ÏÅıÙ(ÄÄπ—…’Õ–µçÖ…êµ—•—±îÅÌÏÅµÖ…ù•∏ËÄ¿Ä¿Ä…¡‡ÏÅıÙ(ÄÄπ—…’Õ–µçÖ…êµ—ï·–ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅµÖ‡µ›•ë—†ËÄ‘»¡¡‡ÏÅıÙ(ÄÄç≠Ö—ïùΩ…•ï»ÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄÃ…¡‡ÄÖ•µ¡Ω…—Öπ–ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω›ÃÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†‘∞Ä≈ô»§ÏÅùÖ¿ËÄƒŸ¡‡ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹ÅÌÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅô±ï‡µÕ—Ö…–ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµ•∏µ°ï•ù°–ËÄƒ‘¡¡‡ÏÅ¡Öëë•πúËÄƒŸ¡‡ÄƒŸ¡‡Äƒ·¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ·¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä≈¡‡Ä…¡‡Å…ùâÑ†ƒƒ∞ÄÃ‹∞Äÿ‰∞Ä¿∏¿ÿ§∞Ä¿ÄŸ¡‡Äƒ·¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏¿‘§ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹È°ΩŸï»∞ÄπçÖ—ïùΩ…‰µ…Ω‹ÈôΩç’ÃµŸ•Õ•â±îÅÌÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¥…¡‡§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Äƒ¡¡‡Ä»Ÿ¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒ–§ÏÅıÙ(ÄÄº®Å1•πÕï∏Å±•ùùï»ÅπïëîÅ—•∞Å£·Â…îÄ°â•±ëï–ÅÕ≠Ö±ï…ïÃÅµïêÅ≠Ω…—â…ïëëï∏∞ÅôΩ…Öπ≠…ï–Å§Åâ’ππï∏§ÅµïêÅôÖëîÅµΩ–ÅŸïπÕ—…îÅΩúÅΩ¡¿∞(ÄÄÄÄÅΩúÅï∏Å¡ÖÕ—ï±∞µ”ï≠îÅâÖ¨Å—ï≠Õ—ï∏Ä†ËÈâïôΩ…î§∞ÅœîÅ—•——ï∞ÅΩúÅâïÕ≠…•Ÿï±ÕîÅÖ±±—•êÅï»Å±ï——îÉîÅ±ïÕî∏Ä®º(ÄÄπçÖ—ïùΩ…‰µ…Ω‹µâúÅÌÏÅ—Ω¿ËÅÖ’—ºÏÅâΩ——Ω¥ËÄ¿ÏÅ…•ù°–ËÄ¥‡îÏÅ›•ë—†ËÄƒ»»îÏÅ°ï•ù°–ËÅÖ’—ºÏÅµÖ‡µ›•ë—†ËÅπΩπîÏÄµ›ïâ≠•–µµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–»î§∞Å±•πïÖ»µù…Öë•ïπ–†ƒ‡¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä»–î§ÏÄµ›ïâ≠•–µµÖÕ¨µçΩµ¡ΩÕ•—îËÅÕΩ’…çîµ•∏ÏÅµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–»î§∞Å±•πïÖ»µù…Öë•ïπ–†ƒ‡¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä»–î§ÏÅµÖÕ¨µçΩµ¡ΩÕ•—îËÅ•π—ï…Õïç–ÏÅıÙ(ÄÄº®Å5’±—•ôΩ≠Ö±îËÅ—ºÅÕ—Öâ±ïëîÅ±•πÕï»Å—Ö»Åµï»Å¡±ÖÕÃÏÅÕ≠ÂÿÅâ•±ëï–Å±•—–ÅµΩ–Å£·Â…îÅœîÅâïÕ≠…•Ÿï±Õï∏ÅÕ”ï»Åô…§Ä®º(ÄÄπçÖ—ïùΩ…‰µ…Ω‹πçÖ–µçΩ…Ö∞ÄπçÖ—ïùΩ…‰µ…Ω‹µâúÅÌÏÅ…•ù°–ËÄ¥ƒ‘îÏÅ›•ë—†ËÄƒƒ¿îÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹ËÈâïôΩ…îÅÌÏÅçΩπ—ïπ–ËÄààÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ•πÕï–ËÄ¿ÏÅËµ•πëï‡ËÄ¥ƒÏÅâÖç≠ù…Ω’πêËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞ÅŸÖ»†¥µçÖ–µâú§Ä¿î∞ÅŸÖ»†¥µçÖ–µâú§Ä–ÿî∞Å—…ÖπÕ¡Ö…ïπ–Ä‡¿î§ÏÅ¡Ω•π—ï»µïŸïπ—ÃËÅπΩπîÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹µ•çΩ∏ÅÌÏÅ›•ë—†ËÄ–—¡‡ÏÅ°ï•ù°–ËÄ–—¡‡ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹µ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄ»…¡‡ÏÅ°ï•ù°–ËÄ»…¡‡ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹µ—ï·–ÅÌÏÅô±ï‡ËÅπΩπîÏÅµÖ‡µ›•ë—†ËÄ‹ÿîÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹µÖ……Ω‹ÅÌÏÅ—Ω¿ËÅÖ’—ºÏÅâΩ——Ω¥ËÄƒ…¡‡ÏÅ…•ù°–ËÄƒ…¡‡ÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ï`†¥—¡‡§ÏÅ›•ë—†ËÄÃ¡¡‡ÏÅ°ï•ù°–ËÄÃ¡¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µçÖ–µÖççïπ–§ÏÅçΩ±Ω»ËÅ›°•—îÏÅΩ¡Öç•—‰ËÄ¿ÏÅ—…ÖπÕ•—•Ω∏ËÅΩ¡Öç•—‰Ä¿∏ƒ’Ã∞Å—…ÖπÕôΩ…¥Ä¿∏ƒ’ÃÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µ…Ω‹È°ΩŸï»ÄπçÖ—ïùΩ…‰µ…Ω‹µÖ……Ω‹∞ÄπçÖ—ïùΩ…‰µ…Ω‹ÈôΩç’ÃµŸ•Õ•â±îÄπçÖ—ïùΩ…‰µ…Ω‹µÖ……Ω‹ÅÌÏÅΩ¡Öç•—‰ËÄƒÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ï`†¿§ÏÅıÙ)ıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51}9=}MI!Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµ¡Öπï∞à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩπ—ïπ–à¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµ°ïÖë•πúÅ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘A…•ÕÕÖµµïπ±•ùπ•πúΩë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÒ†ƒ˘•π∏Åâ•±±•ùÕ—îÅ≠Ωπ—Ö≠—±•πÕï»Ω†ƒ¯(ÄÄÄÄÄÄÄÄÄÄÒ¿Åç±ÖÕÃÙâ°ï…ºµÕ’â—ï·–à˘Y§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Åô…ÑÅÌπ}…ï—Ö•±ï…ÕÙÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅMîÅ¡…•Õï∏ÅµïêÅΩúÅ’—ï∏Åô…Ö≠–∏Ω¿¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µÕïç—•Ω∏à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µ…Ω‹à¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒÕŸúÅç±ÖÕÃÙâÕïÖ…ç†µ•çΩ∏àÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Òç•…ç±îÅç‡Ùàƒ¿∏‘àÅç‰Ùàƒ¿∏‘àÅ»Ùàÿ∏‘àº¯Ò¡Ö—†ÅêÙâ4»¿Ä»¡∞¥–∏‡¥–∏‡àº¯ΩÕŸú¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒ±Öâï∞ÅôΩ»Ùâ±ïπÃµÕïÖ…ç†àÅç±ÖÕÃÙâŸ•Õ’Ö±±‰µ°•ëëï∏àÅÕ—Â±îÙâ¡ΩÕ•—•Ω∏ÈÖâÕΩ±’—îÌ±ïô–Ë¥‰‰‰Â¡‡Ïà˘O·¨Åï——ï»Å±•πÕîÅï±±ï»Åµï…≠îΩ±Öâï∞¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒ•π¡’–Å—Â¡îÙâÕïÖ…ç†àÅ•êÙâ±ïπÃµÕïÖ…ç†àÅç±ÖÕÃÙâÕïÖ…ç†µ•π¡’–àÅ¡±Öçï°Ω±ëï»ÙâO·¨Åï——ï»Å±•πÕîÅï±±ï»Åµï…≠îàÅÖ’—ΩçΩµ¡±ï—îÙâΩôòà¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâÕïÖ…ç†µâ—∏àÅ•êÙâÕïÖ…ç†µâ—∏à˘O·¨Ωâ’——Ω∏¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕïÖ…ç†µÕ’ùùïÕ—•ΩπÃàÅ•êÙâÕïÖ…ç†µÕ’ùùïÕ—•ΩπÃà¯Ωë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µçÖ…êà¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µçÖ…êµ•çΩ∏à¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Ò¡Ö—†ÅêÙâ4ƒ»ÄÕ∞‹ÄÕÿ’å¿Ä‘¥Ã∏»Ä‹∏‡¥‹Ä‰¥Ã∏‡¥ƒ∏»¥‹¥–¥‹¥ÂXŸËàº¯Ò¡Ö—†ÅêÙâ4‰Äƒ…∞»Ä»Ä–¥–àº¯ΩÕŸú¯Ωë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µçÖ…êµ—•—±îà˘UÖŸ°ïπù•úÅΩúÅΩ¡¡ëÖ—ï…–Ωë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒ¿Åç±ÖÕÃÙâ—…’Õ–µçÖ…êµ—ï·–à˘-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—î∏ÅY§Å°ïπ—ï»Å¡…•Õï»ÅÖ’—ΩµÖ—•Õ¨ÅΩúÅΩ¡¡ëÖ—ï…ï»Åëï¥ÅëÖù±•ú∞ÅΩúÅ±Ö»ÅëïúÅÕîÅ¡…•Õï∏ÅãïëîÅµïêÅΩúÅ’—ï∏Åô…Ö≠–∏Ω¿¯(ÄÄÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµµïë•ÑàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯(ÄÄÄÄÄÄÄÄÒ¡•ç—’…î¯(ÄÄÄÄÄÄÄÄÄÄÒÕΩ’…çîÅµïë•ÑÙà°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§àÅ—Â¡îÙâ•µÖùîΩ›ïâ¿àÅÕ…çÕï–ÙàΩÕ—Ö—•åΩ°ï…ºΩïÂî¥‘ÿ¿π›ïâ¿Ä‘ÿ¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩïÂî¥‡–¿π›ïâ¿Ä‡–¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩïÂî¥ƒƒ»¿π›ïâ¿Äƒƒ»¡‹àÅÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ»¿¡¡‡§Ä‘–¡¡‡∞Ä–…Ÿ‹à¯(ÄÄÄÄÄÄÄÄÄÄÒ•µúÅÕ…åÙâëÖ—ÑÈ•µÖùîΩù•òÌâÖÕîÿ–±H¡±=±°E	 ’	-1	%Q=‹ÙÙàÅÖ±–ÙààÅ›•ë—†Ùà‘ÿ¿àÅ°ï•ù°–ÙàÃ‡»àÅôï—ç°¡…•Ω…•—‰Ùâ°•ù†àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄÄÄÄÄΩ¡•ç—’…î¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯((ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠Ö—ïùΩ…•ï»µâ±Ωç¨ÅëïÕ≠—Ω¿µΩπ±‰µâ±Ωç¨à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕïç—•Ω∏µ°ïÖëï»àÅ•êÙâ≠Ö—ïùΩ…•ï»àÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»¡¡‡Ïà¯(ÄÄÄÄÄÄÄÄÒ†»˘-Ö—ïùΩ…•ï»Ω†»¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω›Ãà¯(ÄÄÄÄÄÄÄÅÌçÖ—ïùΩ…Â}…Ω›Õ}°—µ±Ù(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâÕïç—•Ω∏µ°ïÖëï»àÅ•êÙâµï…≠ï»à¯(ÄÄÄÄÒ†»˘5ï…≠ï»Ω†»¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµù…•êà¯(ÄÄÄÅÌâ…Öπë}çÖ…ëÕ}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÅÌ¡±•}ë•Õç±Ö•µï…}πΩ—ïÙ((ÄÄÒë•ÿÅç±ÖÕÃÙâ≠Ö—ïùΩ…•ï»µâ±Ωç¨ÅµΩâ•±îµΩπ±‰µâ±Ωç¨à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕïç—•Ω∏µ°ïÖëï»àÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»¡¡‡Ïà¯(ÄÄÄÄÄÄÒ†»˘-Ö—ïùΩ…•ï»Ω†»¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µ…Ω›Ãà¯(ÄÄÄÄÄÅÌçÖ—ïùΩ…Â}…Ω›Õ}°—µ±Ù(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâÕïç—•Ω∏µ°ïÖëï»à¯(ÄÄÄÄÒ†»˘’•ëï»Ω†»¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµù…•êà¯(ÄÄÄÅÌù’•ëï}çÖ…ëÕ}°—µ±Ù(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µÕ—…•¿à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥µ•çΩ∏à¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Ò¡Ö—†ÅêÙâ4»¿∏‘‰ÄƒÃ∏–≈0ƒ»Ä»…∞¥‰¥‰Ä‡∏‘‰¥‡∏‘Â»Ä»Ä¿Ä¿ÄƒÄƒÃÄÕ†’Ñ»Ä»Ä¿Ä¿ÄƒÄ»Ä…ÿ’Ñ»Ä»Ä¿Ä¿Äƒ¥∏–ƒÄ»∏–≈Ëàº¯Òç•…ç±îÅç‡Ùàƒÿ∏‘àÅç‰Ùà‹∏‘àÅ»Ùàƒ∏»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îÙâπΩπîàº¯ΩÕŸú¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿ¯ÒÕ—…Ωπú˘Ìπ}¡…Ωë’ç—ÕÙÅ±•πÕï»ΩÕ—…Ωπú¯ÒÕ¡Ö∏˘=¡¡ëÖ—ï…–ÅëÖù±•úΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥µ•çΩ∏à¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Ò¡Ö—†ÅêÙâ4–ÄÂ∞ƒ¥’†ƒ—∞ƒÄ‘àº¯Ò¡Ö—†ÅêÙâ4–ÄÂÿƒ¡ÑƒÄƒÄ¿Ä¿Ä¿ÄƒÄ≈†ƒ—ÑƒÄƒÄ¿Ä¿Ä¿Äƒ¥≈X‰àº¯Ò¡Ö—†ÅêÙâ4–ÄÂ†ƒŸ4‰∏‘Ä»¡ÿ¥‘∏’†’X»¿àº¯ΩÕŸú¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿ¯ÒÕ—…Ωπú˘Ìπ}…ï—Ö•±ï…ÕÙÅπï——â’—•≠≠ï»ΩÕ—…Ωπú¯ÒÕ¡Ö∏˘MÖµµïπ±•ùπï–ÅëÖù±•úΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥µ•çΩ∏à˘ÌQIU-}%=9}MYÙΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿ¯ÒÕ—…Ωπú˘5ïêÅï±±ï»Å’—ï∏Åô…Ö≠–ΩÕ—…Ωπú¯ÒÕ¡Ö∏˘‘ÅŸï±ùï»Å°ŸÑÅë‘ÅÕÖµµïπ±•ùπï»ΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ—…’Õ–µ•—ï¥µ•çΩ∏à¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Ò¡Ö—†ÅêÙâ4ƒ»ÄÕ∞‹ÄÕÿ’å¿Ä‘¥Ã∏»Ä‹∏‡¥‹Ä‰¥Ã∏‡¥ƒ∏»¥‹¥–¥‹¥ÂXŸËàº¯ΩÕŸú¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿ¯ÒÕ—…Ωπú˘UÖŸ°ïπù•úΩÕ—…Ωπú¯ÒÕ¡Ö∏˘Y§ÅÕï±ùï»Å•≠≠îÅ±•πÕï»ÅÕï±ÿΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÅÌ5Q!==1=e}!Q51Ù((ÄÅÌ°Ωµï}ôÖ≈}°—µ±Ù(Ωë•ÿ¯((ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω©ÕΩ∏àÅ•êÙâ¡…Ωë’ç–µÕïÖ…ç†µëÖ—Ñà˘ÌÕïÖ…ç°}•πëï·}©ÕΩπÙΩÕç…•¡–¯(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω©ÕΩ∏àÅ•êÙâ¡…•ŸÖ—îµ±Öâï∞µÕïÖ…ç†µëÖ—Ñà˘Ì¡…•ŸÖ—ï}±Öâï±}ÕïÖ…ç°}•πëï·}©ÕΩπÙΩÕç…•¡–¯(ÒÕç…•¡–¯(ÄÄººÅO·≠ï–Å≠´·…ï»ÅµΩ–Åï∏Å±•—ï∏ÅÕ≠©’±–Å)M=8µ•πëï≠ÃÄ°ΩŸï»§∞Å•≠≠îÅµΩ–ÅÕÂπ±•ùî(ÄÄººÅ¡…Ωë’≠—≠Ω…–Ä¥¥ÅôΩ…Õ•ëï∏ÅŸ•Õï»ÅâïŸ•ÕÕ–Å%--Å±ïπùï»ÅÖ±±îÅÌπ}¡…Ωë’ç—ÕÙ(ÄÄººÅ±•πÕïπîÄ°ô©ï…πï–Ä»¿»ÿ¥¿‡¥ƒ‘∞ÅÕîÅ1Uπµê§ËÅï∏ÅôΩ…Õ•ëîÅÕ—Ö¡¡ï–Åô’±∞ÅÖÿ(ÄÄººÅ°Ÿï…–ÅïπïÕ—îÅ¡…Ωë’≠–Å’—ŸÖππï–Åëï–Å—Ω¡•Õ≠îÅôΩ≠’Õï–ÅôΩ»ÅM<Ω$µÕ•—ï…•πú(ÄÄººÅΩúÅ≠Ωπ≠’……ï…—îÅµïêÅïùπîÅ≠Ö—ïùΩ…§¥Ωµï…≠ïÕ•ëï»ÅΩ¥ÅëîÅÕÖµµîÅœ·≠ïπî∏(ÄÄººÅ-Ö—ïùΩ…•ïπîÅΩúÅµï…≠ïπîÅ’πëï»Åï»ÅªîÅëï∏Å…ïï±±îÄâÕîÅÖ±–àµ•ππùÖπùï∏∏(ÄÄººÅMï±ŸîÅœ·≠ï±Ωù•≠≠ï∏Åï»Åëï±–ÅµïêÅù’•ëîµÕ•ëïπîÅΩúÅ—Ω¡¡µïπÂï∏Ä°≠´·…ïÃÅªîÅô…Ñ(ÄÄººÅQ=A	I}!Q50∞ÅÕîÅ19M}MI!})LÄ¥¥Å’ππüï»ÅÖ–Å%%µï∏Å≠´·…ï»Å—ºÅùÖπùï»Å√î(ÄÄººÅÕÖµµîÅÕ•ëîÅΩúÅëΩââï±—â•πëï»ÅïŸïπ–µ±Â——ï…îÅ√îÅôΩ…Õ•ëïπÃÅïùï–Åœ·≠ïôï±–§∏(ΩÕç…•¡–¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()U%}=9Q9PÄÙÅÏ(ÄÄÄÄâµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ7ïπïëÕ±•πÕï»ÅŸÃ∏ÅëÖùÕ±•πÕï»ÉäLÅ°ŸÑÅ¡ÖÕÕï»Åëïú¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒ¿à∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâΩ…ëï±ï»ÅΩúÅ’±ïµ¡ï»ÅŸïêÅ∑ïπïëÕ±•πÕï»ÅΩúÅëÖùÕ±•πÕï»∞ÅΩúÅ°ŸΩ…ëÖ∏Åâ…’≠Õ°Â¡¡•ù°ï–ÅÖŸù´·»Å°ŸÑÅÕΩ¥Å≥·ππï»ÅÕïú∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ï–Å≠Ω…—îÅÕŸÖ…ï–ËÅâ…’≠ï»Åë‘Å±•πÕï»ÄÒÕ—…Ωπú˘Õ©ï±ëπï…îÅïπ∏Ä”äL‘ÅëÖùï»Å§Å’≠ï∏ΩÕ—…Ωπú¯∞Å≠Ωµµï»)ëÖùÕ±•πÕï»ÅΩô—ïÕ–Åâ•±±•ùÕ–Å’–Å—Ω—Ö±–ÅÕï—–∞ÅÕï±ÿÅΩ¥Å¡…•Õï∏Å¡ï»Å±•πÕîÅï»Å£·Âï…î∏Å	…’≠ï»Åë‘)±•πÕï»ÄÒÕ—…Ωπú˘ëÖù±•úΩÕ—…Ωπú¯∞Åï»Å∑ïπïëÕ±•πÕï»ÅπΩ…µÖ±–Å…•µï±•ùÕ–Å¡ï»Åâ…’≠ÕëÖú∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘ÖùÕ±•πÕï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘9Â—–∞Å…ïπ–Å¡Ö»Å°Ÿï»ÅëÖúÉäLÅ•πùï∏Å…ïπù´·…•πúÅï±±ï»ÅΩ¡¡âïŸÖ…•πùÕ€ôÕ≠îΩ±§¯(ÄÄÒ±§˘A…Ö≠—•Õ¨Å—•∞ÅÕ¡Ω…–∞Å…ï•ÕîÅï±±ï»ÅÕ©ï±ëï∏Åâ…’¨Ω±§¯(ÄÄÒ±§˘1ÖŸï…îÅ…•Õ•≠ºÅôΩ»É·Âï•πôï≠Õ©Ω∏ÅÕ•ëï∏Å±•πÕï∏ÅÖ±ë…§Åù©ïπâ…’≠ïÃΩ±§¯(ÄÄÒ±§˘#·Âï…îÅ≠ΩÕ—πÖêÅ¡ï»Å±•πÕî∞ÅΩúÅµï»ÅïµâÖ±±ÖÕ©ïÖŸôÖ±∞ÅŸïêÅëÖù±•úÅâ…’¨Ω±§¯(Ω’∞¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‰’…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘–Åï≠Õïµ¡ï∞Å√îÅï∏ÅµÂîÅâ…’≠–ÅëÖùÕ±•πÕîÅï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÕΩô±ïπÃΩÕΩô±ïπÃµëÖ•±‰µë•Õ¡ΩÕÖâ±î¥Ã¿µ¡Öç¨ºà˘MΩô1ïπÃÅÖ•±‰Å•Õ¡ΩÕÖâ±îΩÑ¯+äLÅÕÖµµïπ±•ù∏Å¡…•Õï»ÅΩúÅÕîÅ°ŸΩ»ÅµÖπùîÅôΩ…°Öπë±ï…îÅÕΩ¥Åõ·…ï»Åëï∏ÅÖ≠≠’…Ö–Åªî∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘7ïπïëÕ±•πÕï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘MÖµµîÅ¡Ö»Åâ…’≠ïÃÅ§ÅΩ¡¡—•∞ÄÃ¿ÅëÖùï»Ä°õ·±úÅΩ¡—•≠ï…ïπÃÅÖπâïôÖ±•πú§Ω±§¯(ÄÄÒ±§˘1ÖŸï…îÅ≠ΩÕ—πÖêÅ¡ï»Åâ…’≠ÕëÖúÅŸïêÅëÖù±•úÅâ…’¨Ω±§¯(ÄÄÒ±§˘-…ïŸï»ÅëÖù±•úÅ…ïπù´·…•πúÅΩúÅ…•≠—•úÅΩ¡¡âïŸÖ…•πùÕ€ôÕ≠îΩ±§¯(ÄÄÒ±§˘5ÖπùîÅµΩëï…πîÅ∑ïπïëÕ±•πÕï»Ä°Õ•±•≠Ωπ°Âë…Ωùï∞§ÅÕ±•¡¡ï»Åù©ïππΩ¥Åµï»ÅΩ≠ÕÂùï∏Åïπ∏Åï±ë…î(ÄÅµÖ—ï…•Ö±ï»∞ÅπΩîÅÕΩ¥Å≠Ö∏Åù§Åâïë…îÅ≠ΩµôΩ…–ÅŸïêÅ±ÖπùîÅëÖùï»ÅµïêÅ±•πÕï»Ω±§¯(Ω’∞¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‰’…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘–Åï≠Õïµ¡ï∞Å√îÅï∏ÅµΩëï…πîÅÕ•±•≠Ωπ°Âë…Ωùï∞µ∑ïπïëÕ±•πÕîÅï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ω’±—…ÑΩ’±—…Ñ¥ÿµ¡Öç¨ºà˘U±—…ÑÄÿµ¡Öç¨ΩÑ¯Åô…ÑÅ	Ö’Õç†Ä¨Å1Ωµà∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘UÖπÕï—–Å—Â¡îËÅõ·±úÅÖ±±—•êÅâÂ——ïô…ï≠ŸïπÕï∏ÅΩ¡—•≠ï…ï∏Å°Ö»ÅÕÖ—–ÅôΩ»)Ö≠≠’…Ö–Åë•∏Å±•πÕîÅΩúÅ…ïÕï¡–ÉäLÅëï–Åï»Å•≠≠îÅâÖ…îÅï–Å¡…•ÕÕ√·…Õ∑ï∞∞Åµï∏ÅÖŸù´·…ïπëîÅôΩ»+·Âï°ï±Õï∏∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»ÅëÖùÕ±•πÕï»Åï±±ï»Å∑ïπïëÕ±•πÕï»Åâ•±±•ùÕ–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ	…’≠ï»Åë‘Å±•πÕï»ÅÕ©ï±ëπï…îÅïπ∏Ä”äL‘ÅëÖùï»Å§Å’≠ï∏∞Å≠Ωµµï»ÅëÖùÕ±•πÕï»ÅΩô—ïÕ–Åâ•±±•ùÕ–Å’–Å—Ω—Ö±–ÅÕï—–∞ÅÕï±ÿÅΩ¥Å¡…•Õï∏Å¡ï»Å±•πÕîÅï»Å£·Âï…î∏Å	…’≠ï»Åë‘Å±•πÕï»ÅëÖù±•ú∞Åï»Å∑ïπïëÕ±•πÕï»ÅπΩ…µÖ±–Å…•µï±•ùÕ–Å¡ï»Åâ…’≠ÕëÖú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅôΩ…ëï±ï∏ÅµïêÅëÖùÕ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9Â—–∞Å…ïπ–Å¡Ö»Å°Ÿï»ÅëÖúÉäLÅ•πùï∏Å…ïπù´·…•πúÅï±±ï»ÅΩ¡¡âïŸÖ…•πùÕ€ôÕ≠î∏ÅA…Ö≠—•Õ¨Å—•∞ÅÕ¡Ω…–∞Å…ï•ÕîÅï±±ï»ÅÕ©ï±ëï∏Åâ…’¨∞ÅΩúÅ±ÖŸï…îÅ…•Õ•≠ºÅôΩ»É·Âï•πôï≠Õ©Ω∏ÅÕ•ëï∏Å±•πÕï∏ÅÖ±ë…§Åù©ïπâ…’≠ïÃ∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅôΩ…ëï±ï∏ÅµïêÅ∑ïπïëÕ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ1ÖŸï…îÅ≠ΩÕ—πÖêÅ¡ï»Åâ…’≠ÕëÖúÅŸïêÅëÖù±•úÅâ…’¨∏Å5ÖπùîÅµΩëï…πîÅ∑ïπïëÕ±•πÕï»Ä°Õ•±•≠Ωπ°Âë…Ωùï∞§ÅÕ±•¡¡ï»Åù©ïππΩ¥Åµï»ÅΩ≠ÕÂùï∏Åïπ∏Åï±ë…îÅµÖ—ï…•Ö±ï»∞ÅÕΩ¥Å≠Ö∏Åù§Åâïë…îÅ≠ΩµôΩ…–ÅŸïêÅ±ÖπùîÅëÖùï»ÅµïêÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ…ëÖ∏ÅŸï±ùîÅ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒ¿à∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ∏Å≠Ω…–Åù’•ëîÅ—•∞Å°ŸÑÅÕΩ¥ÅÖŸù´·»Å…•≠—•úÅ≠Ωπ—Ö≠—±•πÕï—Â¡îËÅ…ïÕï¡–∞Åâ…’≠Õ°Â¡¡•ù°ï–∞ÅÕÂπÕôï•∞ÅΩúÉ·ÂπïπïÃÅâï°Ωÿ∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘-Ωπ—Ö≠—±•πÕï»Åï»Å…ïÕï¡—ŸÖ…î∞ÅΩùœîÅëîÅ’—ï∏ÅÕ—Â…≠îÄ°òπï≠Ã∏ÅôÖ…ùïëîÅ±•πÕï»§∏Å·…Õ—îÅÕ—ïúÅï»)Ö±±—•êÅï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîÅ°ΩÃÅΩ¡—•≠ï»∞ÅÕΩ¥ÅôÖÕ—Õï——ï»ÅÕ—Â…≠î∞Å≠…’µπ•πúÅΩúÅ±•πÕï—Â¡î+·ÂπïπîÅë•πîÅ”ï±ï»ÅùΩë–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘ï–Å…ïÕï¡—ï∏Åë•∏ÅŸÖπ±•ùŸ•ÃÅÖŸù´·»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘Õ—•ùµÖ—•ÕµîΩÕ—…Ωπú¯Ä°Õ≠©ïÿÅ°Ω…π°•ππî§ÉäHÅ—Ω…•Õ≠îÅ±•πÕï»∞ÅôΩ…µï–ÅôΩ»ÉîÅ±•ùùî(ÄÅÕ—Öâ•±–Å§Åï∏ÅâïÕ—ïµ–Å…ï—π•πúΩ±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘±ëï…ÕÕÂ∏ΩÕ—…Ωπú¯Ä°ŸÖπÕ≠ï»ÅµïêÉîÅÕîÅ√îÅªô…–Å°Ω±êÅô…ÑÅçÑ∏Ä–√äL–‘Éï»§ÉäH(ÄÅµ’±—•ôΩ≠Ö±îΩ¡…Ωù…ïÕÕ•ŸîÅ±•πÕï»Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘Mõô…•Õ¨ÅÕÂ∏ΩÕ—…Ωπú¯Å’—ï∏ÅÖÕ—•ùµÖ—•ÕµîÅï±±ï»ÅÖ±ëï…ÕÕÂ∏ÉäHÅŸÖπ±•ùîÅÕõô…•Õ≠î(ÄÅ±•πÕï»∞Åëï–Åïπ≠±ïÕ—îÅΩúÅâ•±±•ùÕ—îÅ’—ŸÖ±ùï–ÉäLÅòπï≠Ã∏(ÄÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îºƒµëÖ‰µÖç’Ÿ’îµµΩ•Õ–¥Ã¿µ¡Öç¨ºà˘ç’Ÿ’îÅ5Ω•Õ–ΩÑ¯Ω±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘πë…îÅ—•πúÅÕΩ¥ÅÕ¡•±±ï»Å•π∏Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘!ŸΩ»ÅΩô—îÅë‘Åâ…’≠ï»Å±•πÕï»∞ÅÕîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»ºà˘ÕÖµµïπ±•ùπ•πú(ÄÅÖÿÅ∑ïπïëÕ±•πÕï»ÅΩúÅëÖùÕ±•πÕï»ΩÑ¯Ω±§¯(ÄÄÒ±§˘S·……îÉ·ÂπîÅ≠Ö∏Åù´·…îÅïπ≠ï±—îÅµÖ—ï…•Ö±ï»Ä°Õ•±•≠Ωπ°Âë…Ωùï∞§Åµï»Åâï°Öùï±•ùîÅïπ∏ÅÖπë…îΩ±§¯(ÄÄÒ±§˘Ö…ùïëîÅ±•πÕï»Å≠…ïŸï»ÅÕÖµµîÅΩ¡¡õ·±ù•πúÅÕΩ¥ÅÖπë…îÅ±•πÕï»∞ÅÕï±ÿÅ’—ï∏ÅÕ—Â…≠îΩ±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘Y§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÅ—Ÿï…ÃÅÖÿÅπï——â’—•≠≠ï»∞Åµï∏Å≠Ö∏)Ö±ë…§Åï…Õ—Ö——îÅï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîÉäLÅâ…’¨ÅÖ±±—•êÅï∏Å…ïÕï¡–ÅÕΩ¥Åï»ÅùÂ±ë•úÅôΩ»Åëï∏)Õ¡ïÕ•ô•≠≠îÅ±•πÕï∏Åë‘ÅâïÕ—•±±ï»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅŸï±ùîÅ≠Ωπ—Ö≠—±•πÕï»ÅÕï±ÿ∞Å’—ï∏ÅÕÂπÕ’πëï…œ·≠ï±Õî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏Å-Ωπ—Ö≠—±•πÕï»Åï»Å…ïÕï¡—ŸÖ…î∞ÅΩùœîÅëîÅ’—ï∏ÅÕ—Â…≠îÄ°òπï≠Ã∏ÅôÖ…ùïëîÅ±•πÕï»§∏Å·…Õ—îÅÕ—ïúÅï»ÅÖ±±—•êÅï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîÅ°ΩÃÅΩ¡—•≠ï»∞ÅÕΩ¥ÅôÖÕ—Õï——ï»ÅÕ—Â…≠î∞Å≠…’µπ•πúÅΩúÅ±•πÕï—Â¡îÉ·ÂπïπîÅë•πîÅ”ï±ï»ÅùΩë–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!Ÿ•±≠ï∏Å±•πÕï—Â¡îÅ¡ÖÕÕï»ÅŸïêÅÖÕ—•ùµÖ—•Õµî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâQΩ…•Õ≠îÅ±•πÕï»∞ÅôΩ…µï–ÅôΩ»ÉîÅ±•ùùîÅÕ—Öâ•±–Å§Åï∏ÅâïÕ—ïµ–Å…ï—π•πúÅ§É·Âï–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!Ÿ•±≠ï∏Å±•πÕï—Â¡îÅ¡ÖÕÕï»ÅŸïêÅÖ±ëï…ÕÕÂ∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ5’±—•ôΩ≠Ö±îΩ¡…Ωù…ïÕÕ•ŸîÅ±•πÕï»Å¡ÖÕÕï»ÅπΩ…µÖ±–ÅâïÕ–ÅŸïêÅÖ±ëï…ÕÕÂ∏Ä°ŸÖπÕ≠ï»ÅµïêÉîÅÕîÅ√îÅªô…–Å°Ω±êÅô…ÑÅçÑ∏Ä–√äL–‘Éï»§∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µôΩ»µâÖ…∏àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ωπ—Ö≠—±•πÕï»ÅôΩ»ÅâÖ…∏à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ»ÅâÖ…∏ÅôΩ»Å’πùîÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»¸Å!ŸÑÅÕΩ¥ÅôÖ≠—•Õ¨ÅÖŸù´·»ÅΩ¥Åï–ÅâÖ…∏Åï»Å≠±Ö»∞ÅΩúÅ°ŸΩ…ôΩ»ÅëÖùÕ±•πÕï»ÅΩô—îÅÖπâïôÖ±ïÃÅÕΩ¥Åõ·…Õ—ïŸÖ±ú∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ï–Åô•ππïÃÅ•πùï∏ÅôÖÕ–Åµ•πÕ—ïÖ±ëï»ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»∏Å=¡—•≠ï…îÅŸ’…ëï…ï»Å§ÅÕ—ïëï–(ÒÕ—…Ωπú˘µΩëïπ°ï–ΩÕ—…Ωπú¯ÉäLÅΩ¥ÅâÖ…πï–Å≠±Ö…ï»ÉîÅõ·±ùîÅï∏Å°Âù•ïπï…’—•πîÅÕï±ÿÄ°ŸÖÕ≠îÅ°ïπëï»∞)Õï——îÅ•π∏Ω—ÑÅ’–Å±•πÕï∏Å…•≠—•ú∞Å•≠≠îÅÕΩŸîÅµïêÅ±•πÕï∏Å•ππî§ÉäLÅô…ïµôΩ»Åï–ÅâïÕ—ïµ–Éï…Õ—Ö±∞∏)5ÖπùîÅâÖ…∏ÅπïêÅ§Ä„äLƒ¿∑ï…ÕÖ±ëï…ï∏Åô’πùï…ï»Åô•π–ÅµïêÅ±•πÕï»∞ÅµïπÃÅÖπë…îÅã·»ÅŸïπ—î∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸΩ…ôΩ»ÅëÖùÕ±•πÕï»ÅΩô—îÅÖπâïôÖ±ïÃÅ—•∞ÅâÖ…∏Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘9Â—–∞Å…ïπ–Å¡Ö»Å°Ÿï»ÅëÖúÉäLÅ•πùï∏Å…ïπù´·…•πúÅï±±ï»ÅΩ¡¡âïŸÖ…•πùÕ€ôÕ≠îÉîÅ°’Õ≠îÅ√îΩ±§¯(ÄÄÒ±§˘1ÖŸï…îÅ≠ΩπÕï≠ŸïπÃÅ°Ÿ•ÃÅï∏Å±•πÕîÅµ•Õ—ïÃÅï±±ï»Åù±ïµµïÃÅï∏ÅëÖúΩ±§¯(ÄÄÒ±§˘1ÖŸï…îÅ•πôï≠Õ©ΩπÕ…•Õ•≠ºÅïπ∏Å±•πÕï»ÅÕΩ¥Åù©ïπâ…’≠ïÃÅΩŸï»Å—•êΩ±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘5ÂΩ¡•≠Ωπ—…Ω±∞Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘π≠ï±—îÅëÖùÕ±•πÕï»Åï»Å§ÅëÖúÅΩùœîÅùΩë≠©ïπ–ÅÕ¡ïÕ•ô•≠–ÅôΩ»ÉîÅâ…ïµÕîÅ’—Ÿ•≠±•πúÅÖÿ)ªô…ÕÂπ—°ï–Ä°µÂΩ¡•≠Ωπ—…Ω±∞§Å°ΩÃÅâÖ…∏ÅΩúÅ’πùîÉäLÅòπï≠Ã∏(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩµÂëÖ‰ΩµÂëÖ‰µµ•Õ•ù°–¥ƒµëÖ‰¥Ã¿µ¡Öç¨ºà˘5ÂÖ‰Å5•M•ù°–ΩÑ¯∞ÅÕ¡ïÕ•ô•≠–)’—Ÿ•≠±ï–ÅôΩ»Åëï——îÅôΩ…∑ï±ï–∏Åï——îÅï»ÅπΩîÅï∏ÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÅŸ’…ëï…ï»ÅΩúÅõ·±ùï»ÅΩ¡¿)•πë•Ÿ•ë’ï±–∞Å•≠≠îÅπΩîÅµÖ∏ÅŸï±ùï»ÅÕï±ÿ∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘UÖπÕï—–ÅÖ±ëï»ËÅï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîÅ°ΩÃÅΩ¡—•≠ï»Åï»ÅÖ±±—•êÅõ·…Õ—îÅÕ—ïú∞ÅΩúÅâÖ…πï–Åã·»)õ·±ùïÃÅΩ¡¿Å©ïŸπ±•úÅœîÅ±ïπùîÅëï–Åâ…’≠ï»Å±•πÕï»∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘%õ·±ùîÄÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩôÖµ•±•îΩâÖ…∏ΩâÖ…∏µΩúµ≠Ωπ—Ö≠—±•πÕï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9Ω…Õ¨Å!ï±Õï•πôΩ…µÖ—•≠¨Ä°9!$§ΩÑ¯Åï»Åëï–ÅÕ—Ω…îÅ•πë•Ÿ•ë’ï±±îÅôΩ…Õ≠©ï±±ï»Å§Åªï»Åï–ÅâÖ…∏Åï»Å≠±Ö…–∞ÅÕï±ÿÅΩ¥Åëï–Åô•ππïÃÅï∏ÅŸÖπ±•úÅ—Ωµµï±ô•πùï……ïùï∞ËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩπ°§ππºΩôÖµ•±•îΩâÖ…∏ΩâÖ…∏µΩúµ≠Ωπ—Ö≠—±•πÕï»àÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘YÖπ±•ùîÅÖπâïôÖ±•πùï»Åï»ÅÖ–ÅâÖ…∏Å≠Ö∏ÅâïùÂππîÉîÅâ…’≠îÅ±•πÕï»Åªï»ÅëîÅï»Å§Äƒ»¥ƒÃÉï…ÃÅÖ±ëï…ï∏∏Å5ï∏Åëï–Åô•ππïÃÄƒ–∑ï…•πùï»ÅÕΩ¥Åï»ÅôΩ»Å’µΩëπîÅ—•∞ÉîÅâ…’≠îÅ±•πÕï»∞ÅΩúÄƒ¿∑ï…•πùï»ÅÕΩ¥Åï»ÅµΩëπîÅπΩ¨∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩôÖµ•±•îΩâÖ…∏ΩâÖ…∏µΩúµ≠Ωπ—Ö≠—±•πÕï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9!$∞Å	Ö…∏ÅΩúÅ≠Ωπ—Ö≠—±•πÕï»ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅùÖµµï±–Å∑îÅï–ÅâÖ…∏Å€ô…îÅôΩ»ÉîÅâ…’≠îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâï–Åô•ππïÃÅ•πùï∏ÅôÖÕ–Åµ•πÕ—ïÖ±ëï»∏Å=¡—•≠ï…îÅŸ’…ëï…ï»Å§ÅÕ—ïëï–ÅΩ¥ÅâÖ…πï–Åï»ÅµΩëïπ–ÅπΩ¨Å—•∞ÉîÅõ·±ùîÅ°Âù•ïπï…’—•πï∏ÅÕï±ÿ∞Å•≠≠îÅï–ÅâïÕ—ïµ–Éï…Õ—Ö±∞∏Å5ÖπùîÅô’πùï…ï»Åô•π–Åô…ÑÄ„äLƒ¿∑ï…ÕÖ±ëï…ï∏∞ÅµïπÃÅÖπë…îÅã·»ÅŸïπ—î∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»ÅÖπâïôÖ±ïÃÅΩô—îÅëÖùÕ±•πÕï»Å—•∞ÅâÖ…∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâÖùÕ±•πÕï»Å≠…ïŸï»Å•πùï∏Å…ïπù´·…•πúÅï±±ï»ÅΩ¡¡âïŸÖ…•πùÕ€ôÕ≠î∞Åù•»Å±ÖŸï…îÅ≠ΩπÕï≠ŸïπÃÅ°Ÿ•ÃÅï∏Å±•πÕîÅµ•Õ—ïÃÅï∏ÅëÖú∞ÅΩúÅ°Ö»Å±ÖŸï…îÅ•πôï≠Õ©ΩπÕ…•Õ•≠ºÅïπ∏Å±•πÕï»ÅÕΩ¥Åù©ïπâ…’≠ïÃÅΩŸï»Å—•ê∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°Ö…ëîµï±±ï»µµÂ≠îµ±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!Ö…ëîÅï±±ï»ÅµÂ≠îÅ±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâΩ…Õ≠©ï±±ï∏Å√îÅµÂ≠îÅΩúÅ°Ö…ëîÄ°ùÖÕÕù©ïππΩµ—…ïπùï±•ùî§Å≠Ωπ—Ö≠—±•πÕï»∞ÅΩúÅ°ŸΩ…ôΩ»ÅëîÅÖ±±ï»Åô±ïÕ—îÅ§ÅëÖúÅâ…’≠ï»ÅµÂ≠îÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘îÅÖ±±ï»Åô±ïÕ—îÅ≠Ωπ—Ö≠—±•πÕï»ÅÕΩ¥ÅÕï±ùïÃÅ§ÅëÖúÉäLÅΩúÅÖ±–ÅŸ§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÅ°ï»)√îÅ-Ωπ—Ö≠—±•πÕï»ππºÉäLÅï»ÄÒÕ—…Ωπú˘µÂ≠îÅ±•πÕï»ΩÕ—…Ωπú¯Ä°°Âë…Ωùï∞Åï±±ï»ÅÕ•±•≠Ωπ°Âë…Ωùï∞§∞ÅÕΩ¥(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯∏Å!Ö…ëî(°ùÖÕÕù©ïππΩµ—…ïπùï±•ùîΩI@§Å±•πÕï»Åô•ππïÃÅôΩ…—ÕÖ—–∞Åµï∏Åâ…’≠ïÃÅ§ÅëÖúÅõ·…Õ–ÅΩúÅô…ïµÕ–Å—•∞)Õ¡ïÕ•ï±±îÅÕÂπÕôΩ…°Ω±ê∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘5Â≠îÅ±•πÕï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘-ΩµôΩ…—Öâ±îÅô…ÑÅõ·…Õ—îÅÕ—’πê∞Å≠Ω…–Å—•±Ÿïππ•πùÕ—•êΩ±§¯(ÄÄÒ±§˘1•ùùï»Å—ï—–ÅµΩ–É·Âï–ÉäLÅµ•πë…îÅ…•Õ•≠ºÅôΩ»ÅÖ–Å…’Õ¨Å≠Ωµµï»Å’πëï»Å±•πÕï∏Ω±§¯(ÄÄÒ±§˘	…ïë–Å’—ŸÖ±úÅÖÿÅëÖùÃ¥∞Å’≠ïÃ¥ÅΩúÅ∑ïπïëÕ±•πÕï»Ω±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!Ö…ëîÅ±•πÕï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘-Ö∏Åù§ÅÕ≠Ö…¡ï…îÅÕÂ∏ÅŸïêÅ’…ïùï±µïÕÕ•úÅ°Ω…π°•ππîÄ°òπï≠Ã∏Å≠ï…Ö—Ω≠Ωπ’Ã§Åï±±ï»ÅÕ€ô…–(ÄÅ£·‰ÅÖÕ—•ùµÖ—•ÕµîΩ±§¯(ÄÄÒ±§˘1ïπù…îÅ—•±Ÿïππ•πùÕ—•êÅïπ∏ÅµÂ≠îÅ±•πÕï»Ω±§¯(ÄÄÒ±§˘-…ïŸï»Å—•±¡ÖÕπ•πúÅΩúÅΩ¡¡õ·±ù•πúÅ°ΩÃÅÕ¡ïÕ•Ö±•Õï…–ÅΩ¡—•≠ï»ø·Âï±ïùîΩ±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘!Ÿ•±≠ï∏Å—Â¡îÅÕΩ¥Å¡ÖÕÕï»ÅÖŸù´·…ïÃÅÖÿÅÕÂπÕôΩ…°Ω±ëïπîÅë•πî∞Å•≠≠îÅ¡ï…ÕΩπ±•úÅ¡…ïôï…ÖπÕî)Ö±ïπîÉäLÅëï——îÅï»ÅπΩîÅΩ¡—•≠ï…ï∏ÅŸ’…ëï…ï»ÅŸïêÅÕÂπÕ’πëï…œ·≠ï±Õï∏∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅŸÖπ±•ùÕ–Å§ÅëÖú∞Å°Ö…ëîÅï±±ï»ÅµÂ≠îÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâîÅÖ±±ï»Åô±ïÕ—îÅâ…’≠ï»ÅµÂ≠îÅ±•πÕï»Ä°°Âë…Ωùï∞Åï±±ï»ÅÕ•±•≠Ωπ°Âë…Ωùï∞§Å§ÅëÖú∏Å!Ö…ëîÄ°ùÖÕÕù©ïππΩµ—…ïπùï±•ùî§Å±•πÕï»Åâ…’≠ïÃÅõ·…Õ–ÅΩúÅô…ïµÕ–ÅŸïêÅÕ¡ïÕ•ï±±îÅÕÂπÕôΩ…°Ω±ê∞ÅÕΩ¥Å’…ïùï±µïÕÕ•úÅ°Ω…π°•ππîÅï±±ï»ÅÕ€ô…–Å£·‰ÅÖÕ—•ùµÖ—•Õµî∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Å°Ö…ëîÅ±•πÕï»Åâïë…îÅïπ∏ÅµÂ≠î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%≠≠îÅùïπï…ï±–ÉäLÅëîÅ≠Ö∏Åù§ÅÕ≠Ö…¡ï…îÅÕÂ∏ÅŸïêÅâïÕ—ïµ—îÅ—•±Õ—Öπëï»ÅÕΩ¥Å≠ï…Ö—Ω≠Ωπ’Ã∞Åµï∏Å≠…ïŸï»Å±ïπù…îÅ—•±Ÿïππ•πú∏Å!Ÿ•±≠ï∏Å—Â¡îÅÕΩ¥Å¡ÖÕÕï»ÅÖŸù´·…ïÃÅÖÿÅÕÂπÕôΩ…°Ω±ëïπîÅë•πî∞ÅŸ’…ëï…–ÅÖÿÅï∏ÅΩ¡—•≠ï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ…ëÖ∏ÅÕï——îÅ•π∏ÅΩúÅ—ÑÅ’–Å≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâQ…•ππŸ•ÃÅô…ïµùÖπùÕ∑ï—îÅôΩ»ÉîÅÕï——îÅ•π∏ÅΩúÅ—ÑÅ’–Å≠Ωπ—Ö≠—±•πÕï»Å—…Âù–ÅΩúÅ°Âù•ïπ•Õ¨∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ΩêÅ°Âù•ïπîÅï»ÅŸ•≠—•ùï…îÅïπ∏ÅÕï±ŸîÅ—ï≠π•≠≠ï∏∏ÅYÖÕ¨ÅΩúÅ”·…¨Å°ïπëïπîÅù…’πë•úÅõ·»Åë‘)—Ö»Å§Å±•πÕïπî∞Å°Ÿï»ÅïπïÕ—îÅùÖπú∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Mï——îÅ•π∏Å±•πÕï∏Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘M©ï≠¨ÅÖ–Å±•πÕï∏Å•≠≠îÅï»ÅŸ…ïπù–Ä°Õ≠Ö∞ÅëÖππîÅï∏Å©ïŸ∏ÅÕØï∞∞Å•≠≠îÅ°ÑÅ≠Öπ–ÅÕΩ¥ÅŸ•¡¡ï»Å’–§Ω±§¯(ÄÄÒ±§˘Q…ï≠¨Åπïë…îÉ·Âï±Ω≠¨ÅôΩ…Õ•≠—•úÅπïê∞ÅΩúÅ°Ω±êÅù©ï…πîÉ·Ÿ…îÉ·Âï±Ω≠¨ÅΩ¡¡îÅµïêÅëï∏ÅÖπë…î(ÄÅ£ïπëï∏Ω±§¯(ÄÄÒ±§˘MîÅΩ¡¡ΩŸï»Åï±±ï»Å…ï—–Åô…ï¥∞ÅΩúÅ¡±ÖÕÕï»Å±•πÕï∏ÅôΩ…Õ•≠—•úÅ√îÅëï–Å°Ÿ•—îÅÖÿÉ·Âï–Ω±§¯(ÄÄÒ±§˘MîÅπïêΩâ±’π¨Å…Ω±•úÉäLÅ±•πÕï∏Åô•ππï»ÅÕï±ÿÅ…ï—–Å¡ΩÕ•Õ©Ω∏Å√îÅ°Ω…π°•ππï∏Ω±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘QÑÅ’–Å±•πÕï∏Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘MîÅΩ¡¡ΩŸï»∞Å—…ï≠¨Åπïë…îÉ·Âï±Ω≠¨ÅπïêΩ±§¯(ÄÄÒ±§˘-±Â¿Å±•πÕï∏ÅôΩ…Õ•≠—•úÅµïêÅ—Ωµµï∞ÅΩúÅ¡ï≠ïô•πùï»∞Åï±±ï»ÅÕ≠ÂÿÅëï∏ÅπïëΩŸï»ÅµΩ–Åëï–(ÄÅ°Ÿ•—îÅÖÿÉ·Âï–Åõ·»Åë‘Å≥·ô—ï»Åëï∏ÅÖÿΩ±§¯(ÄÄÒ±§˘±ë…§Åâ…’¨Åπïù±ï»Åë•…ï≠—îÅµΩ–Å°Ω…π°•ππï∏Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘M±•—ï»Åë‘ÅµïêÉîÅõîÅëï–Å—•∞∞Åï»Åëï–Å°ï±–ÅπΩ…µÖ±–ÅëîÅõ·…Õ—îÅùÖπùïπîÉäLÅΩ¡—•≠ï…ï∏ÅÕΩ¥)—•±¡ÖÕÕï–Å±•πÕïπîÅë•πîÅŸ•Õï»ÅëïúÅù©ï…πîÅ—ï≠π•≠≠ï∏Å√îÅπÂ—–∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅŸ•≠—•ùÕ–ÉîÅ°’Õ≠îÅõ·»ÅµÖ∏ÅÕï——ï»Å•π∏Å≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâYÖÕ¨ÅΩúÅ”·…¨Å°ïπëïπîÅù…’πë•úÅõ·…Õ–∞Å°Ÿï»ÅïπïÕ—îÅùÖπúÉäLÅùΩêÅ°Âù•ïπîÅï»ÅŸ•≠—•ùï…îÅïπ∏ÅÕï±ŸîÅ•ππÕï——•πùÕ—ï≠π•≠≠ï∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏ÅŸï–Å©ïúÅΩ¥Å±•πÕï∏Åï»ÅŸ…ïπù–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ∏Å…•≠—•úÅŸïπë–Å±•πÕîÅëÖππï»Åï∏Å©ïŸ∏ÅÕØï∞∏Å»Åëï∏ÅŸ…ïπù–∞ÅŸ•¡¡ï»Å≠Öπ—ï∏Å’—ΩŸï»Å§ÅÕ—ïëï–ÅôΩ»ÉîÅã·ÂîÅ©ïŸπ–Å•ππΩŸï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ôΩ»µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ…ôΩ»Åâ…’≠îÅ≠Ωπ—Ö≠—±•πÕï»Åô…ïµôΩ»Åâ…•±±ï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâΩ…ëï±ïπîÅŸïêÅ≠Ωπ—Ö≠—±•πÕï»ÅÕÖµµïπ±•ùπï–ÅµïêÅâ…•±±ï»∞ÅΩúÅ°ŸÑÅÕΩ¥Å—Ö±ï»ÅôΩ»ÉîÅ≠Ωµâ•πï…îÅâïùùîÅëï±ï»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘-Ωπ—Ö≠—±•πÕï»ÅΩúÅâ…•±±ï»Å≥·Õï»ÅÕÖµµîÅù…’ππ±ïùùïπëîÅâï°ΩÿÉäLÅ≠Ω……•ùï…–ÅÕÂ∏ÉäLÅµï∏Å¡ÖÕÕï»)’±•≠–ÅÖŸ°ïπù•úÅÖÿÅ±•ŸÕÕ—•∞ÅΩúÅÕ•—’ÖÕ©Ω∏∏Å5ÖπùîÅ≠Ωµâ•πï…ï»ÅâïùùîÅëï±ï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Ω…ëï±ï»ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘’±±–∞Å’ôΩ…Õ—Â……ï–ÅÕÂπÕôï±–ÉäLÅ•πùï∏Åâ…•±±ïÕ—ÖπúÅï±±ï»Å≠Öπ–Å§ÅÕÂπÕ…Öπëï∏Ω±§¯(ÄÄÒ±§˘’ùùï»Å•≠≠îÅŸïêÅ—ïµ¡ï…Ö—’…Õ≠•ô—î∞Å…ïù∏Åï±±ï»Åâ…’¨ÅÖÿÅµ’ππâ•πêΩ°©ï±¥Ω±§¯(ÄÄÒ±§˘A…Ö≠—•Õ¨ÅŸïêÅÕ¡Ω…–ÅΩúÅôÂÕ•Õ¨ÅÖ≠—•Ÿ•—ï–Ω±§¯(ÄÄÒ±§˘-Ö∏Å≠Ωµâ•πï…ïÃÅµïêÅŸÖπ±•ùîÅÕΩ±â…•±±ï»Å’—ï∏ÅÕ—Â…≠îΩ±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸÑÅÕΩ¥Å—Ö±ï»ÅôΩ»Åâ…•±±ï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘%πùï∏ÅëÖù±•úÅ°Âù•ïπï…’—•πîÅï±±ï»ÅâïÀ·…•πúÅÖÿÉ·Âï–Ω±§¯(ÄÄÒ±§˘-Ö∏Å€ô…îÅâïë…îÅïùπï–ÅŸïêÅÕ€ô…–Å”·……îÉ·ÂπîÅï±±ï»Åïπ≠ï±—îÉ·Âï—•±Õ—Öπëï»Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘ï–Åï»Å•≠≠îÅïπ—ï∏Ωï±±ï»ÉäLÅµÖπùîÅâ…’≠ï»Å±•πÕï»Å§ÅÖ≠—•ŸîÅ¡ï…•Ωëï»ÅÖÿÅëÖùï∏ÅΩúÅâ…•±±ï»)…ïÕ—ï∏ÅÖÿÅ—•ëï∏∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Å≠Ωπ—Ö≠—±•πÕï»Åâïë…îÅïπ∏Åâ…•±±ï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%≠≠îÅª·ëŸïπë•ùŸ•ÃÅâïë…î∞Åµï∏ÅÖππï…±ïëïÃÉäLÅ±•πÕï»Åù•»Åï–Åô’±±–ÅÕÂπÕôï±–Å’—ï∏Åâ…•±±ïÕ—ÖπúÅï±±ï»Åë’ùù•πú∞ÅµïπÃÅâ…•±±ï»Å≠…ïŸï»Å•πùï∏ÅëÖù±•úÅ°Âù•ïπï…’—•πî∏Å5ÖπùîÅâ…’≠ï»ÅâïùùîÅëï±ï»ÅÖŸ°ïπù•úÅÖÿÅÕ•—’ÖÕ©Ω∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâŸïë±•≠ï°Ω±êµÖÿµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâYïë±•≠ï°Ω±êÅÖÿÅ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâI•≠—•úÅ…ïπù´·…•πúÅΩúÅΩ¡¡âïŸÖ…•πúÅÖÿÅ≠Ωπ—Ö≠—±•πÕï»ÅÕΩ¥Åù©ïπâ…’≠ïÃ∞ÅΩúÅëîÅŸÖπ±•ùÕ—îÅôï•±ïπîÉîÅ’ππüî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ÖùÕ±•πÕï»Å≠ÖÕ—ïÃÅï——ï»É•∏ÅëÖúÅΩúÅ—…ïπùï»Å•≠≠îÅ…ïπù´·…•πú∏Å	…’≠ï»Åë‘Å’≠ïÃ¥Åï±±ï»)∑ïπïëÕ±•πÕï»∞Åï»Å…•≠—•úÅŸïë±•≠ï°Ω±êÅÖŸù´·…ïπëîÅôΩ»É·Âï°ï±Õï∏ÉäLÅ•≠≠îÅâÖ…îÅôΩ»ÅÖ–Å±•πÕï∏)Õ≠Ö∞ÅŸÖ…îÅ±ïπùî∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘…’ππ…ïù±ï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘	…’¨ÅÖ±±—•êÄÒÕ—…Ωπú˘ôï…Õ¨ΩÕ—…Ωπú¯Å±•πÕï€ôÕ≠î∞ÅÕΩ¥(ÄÄÒÑÅ°…ïòÙàΩ±•πÕïŸÖïÕ≠îΩ…ïπ‘Ω…ïπ‘µµ’±—§µ¡’…¡ΩÕî¥Ãÿ¿µµ∞ºà˘Iï9‘Å5’±—§µA’…¡ΩÕîΩÑ¯ÉäLÅôÂ±∞(ÄÅÖ±ë…§Å√îÅùÖµµï∞Å€ôÕ≠îÅ§Åï—’•ï–Ä£
≠—Ω¡¡•πúÅΩôõ
Ï§∞ÅÕ≠•ô–Åëï∏Å°ï±–Å°Ÿï»ÅùÖπúΩ±§¯(ÄÄÒ±§˘·±úÅΩ¡—•≠ï…ïπÃÅÖπâïôÖ±—îÅùπ§µΩúµÕ≠Â±∞µ…’—•πîÅ°Ÿ•ÃÅ€ôÕ≠ï∏Å—•±Õ•ï»Åëï–∞ÅÕï±ÿÅΩ¥(ÄÅïπ≠ï±—îÅ€ôÕ≠ï»ÅµÖ…≠ïëÕõ·…ïÃÅÕΩ¥Äâπºµ…’ààΩ±§¯(ÄÄÒ±§˘M≠•ô–ÅΩ¡¡âïŸÖ…•πùÕï—’§Å©ïŸπ±•úÄ°õ·±úÅ¡…Ωë’Õïπ—ïπÃÅÖπâïôÖ±•πú∞ÅΩô—îÅ°Ÿï»ÄƒªäLÃ∏Å∑ïπïê§Ω±§¯(ÄÄÒ±§˘	…’¨ÅÖ±ë…§ÅÕ¡…•πùŸÖπ∏Åï±±ï»ÅÕ¡Â—–Å√îÅ±•πÕïπîÉäLÅëï–Å≠Ö∏Å—•±õ·…îÅµ•≠…ΩΩ…ùÖπ•Õµï»(ÄÅ±•πÕï€ôÕ≠ï∏Å•≠≠îÅï»Å±Öùï–ÅôΩ»ÉîÅë…ï¡îΩ±§¯(ÄÄÒ±§˘·±úÅâÂ——ïô…ï≠ŸïπÕï∏Å±•πÕï∏ÅôÖ≠—•Õ¨Åï»ÅùΩë≠©ïπ–ÅôΩ»∞ÅÕï±ÿÅΩ¥Åëï∏ÅôΩ…—ÕÖ—–Åõ·±ïÃ(ÄÅ≠ΩµôΩ…—Öâï∞Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ë»—¡‡Ïà˘Y§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÅ±•πÕï€ôÕ≠îÅô…ÑÅô±ï…îÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÉäLÅÕî(ÒÑÅ°…ïòÙàºà˘ôΩ…Õ•ëï∏ΩÑ¯ÅôΩ»ÉîÅœ·≠îÅΩ¡¿Åëï∏Åë‘Åâ…’≠ï»∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘%õ·±ùîÄÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩ±•ŸÕÕ—•∞ΩïùïπΩµÕΩ…úΩ≠Ωπ—Ö≠—±•πÕï»µΩúµŸÖπ∏àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9Ω…Õ¨Å!ï±Õï•πôΩ…µÖ—•≠¨Ä°9!$§ΩÑ¯Åï»Åëï——îÅï–ÅÖÿÅëîÅ—Âëï±•ùÕ—îÅÀïëïπîÅô…ÑÅãïëîÅÖµï…•≠ÖπÕ≠îÅΩúÅπΩ…Õ≠îÅ°ï±ÕïµÂπë•ù°ï—ï»ËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩπ°§ππºΩ±•ŸÕÕ—•∞ΩïùïπΩµÕΩ…úΩ≠Ωπ—Ö≠—±•πÕï»µΩúµŸÖπ∏àÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘ïëîÅÅΩúÅ!$Å¡…ïÕ•Õï…ï»ÅÖ–Å±•πÕï»ÅΩúÅ±•πÕïï—’§ÅÖ±ë…§ÅÕ≠Ö∞Å…ïπÕïÃΩÕ≠Â±±ïÃÅï±±ï»ÅΩ¡¡âïŸÖ…ïÃÅ§ÅÕ¡…•πùŸÖπ∏∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩ±•ŸÕÕ—•∞ΩïùïπΩµÕΩ…úΩ≠Ωπ—Ö≠—±•πÕï»µΩúµŸÖπ∏àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9!$∞Å-Ωπ—Ö≠—±•πÕï»ÅΩúÅŸÖπ∏ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅôÂ±±îÅ√îÅùÖµµï∞Å±•πÕï€ôÕ≠îÅ§Åï—’•ï–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏Å	…’¨ÅÖ±±—•êÅôï…Õ¨Å€ôÕ≠îÅΩúÅÕ≠•ô–Åëï∏Å°ï±–Å°Ÿï»ÅùÖπúÉäLÉîÅôÂ±±îÅ√îÅùÖµµï∞Å€ôÕ≠îÄ£
≠—Ω¡¡•πúÅΩôõ
Ï§Å…ïë’Õï…ï»Åëï∏ÅëïÕ•πô•Õï…ïπëîÅïôôï≠—ï∏Åâï—…Ö≠—ï±•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅΩô—îÅã·»Å©ïúÅÕ≠•ô—îÅΩ¡¡âïŸÖ…•πùÕï—’§¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ·±úÅ¡…Ωë’Õïπ—ïπÃÅÖπâïôÖ±•πúÅôΩ»Å±•πÕï€ôÕ≠ï∏Åë•∏∞ÅΩô—îÅ°Ÿï»ÄƒªäLÃ∏Å∑ïπïê∏Å–ÅùÖµµï±–Åï—’§Å≠Ö∏Å°’ÕîÅâÖ≠—ï…•ï»ÅÕï±ÿÅΩ¥Åëï–ÅÕï»Å…ïπ–Å’–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ…ï•Õ•πúµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâIï•Õ•πúÅµïêÅ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâA…Ö≠—•Õ≠îÅ—•¡ÃÅôΩ»ÉîÅâ…’≠îÅ≠Ωπ—Ö≠—±•πÕï»Å√îÅ…ï•Õî∞Åô…ÑÅô±Â—’…ïπÃÅ”·……îÅ≠Öâ•π±’ô–Å—•∞Å€ôÕ≠ï…ïù±ï»Å§Å£ïπëâÖùÖÕ©ï∏∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘-Ωπ—Ö≠—±•πÕï»Åï»Å¡…Ö≠—•Õ≠îÅ√îÅ…ï•Õî∞Åµï∏ÅπΩï∏ÅõîÅôΩ…âï…ïëï±Õï»Åù´·»Åëï–Åïπ≠±ï…î∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘·»ÅÖŸ…ï•ÕîΩ†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘AÖ≠¨ÅπΩ¨Å±•πÕï»ÅΩúÅïŸïπ—’ï±∞Å±•πÕï€ôÕ≠îÅ—•∞Å°ï±îÅ…ï•Õï∏ÉäLÅ•≠≠îÅÖ±±îÅµï…≠ï»Åï»(ÄÅ—•±ù©ïπùï±•ùîÅΩŸï…Ö±–Ω±§¯(ÄÄÒ±§˘QÑÅµïêÅâ…•±±ï»ÅÕΩ¥ÅâÖç≠’¿∞Å§Å—•±ôï±±îÅ•……•—ÖÕ©Ω∏Åï±±ï»Å”·……îÉ·ÂπîÅ’πëï…Ÿï•ÃΩ±§¯(ÄÄÒ±§˘1•πÕï€ôÕ≠îÅ§Å£ïπëâÖùÖÕ©îÅ∑îÅõ·±ùîÅŸÖπ±•ùîÅ€ôÕ≠ï…ïù±ï»Ä°âï°Ω±ëï…îÅ’πëï»Äƒ¿¿Åµ∞§Ω±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Uπëï…Ÿï•ÃΩ†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘-Öâ•π±’ô–Å√îÅô±‰Åï»ÅÕ€ô…–Å”·…»ÅΩúÅ≠Ö∏Åù´·…îÅ±•πÕï»Åµ•πë…îÅâï°Öùï±•ùîÅ√îÅ±Öπùî(ÄÅô±ÂŸπ•πùï»ÉäLÅ°ÑÉ·ÂïëÀï¡ï»Åï±±ï»Åâ…•±±ï»Å—•±ù©ïπùï±•úΩ±§¯(ÄÄÒ±§˘ÖùÕ±•πÕï»Åï»ÅΩô—îÅ¡…Ö≠—•Õ≠îÅ√îÅ…ï•Õî∞ÅÕ•ëï∏Åë‘ÅÕ±•¡¡ï»ÉîÅ°ÑÅµïêÅï—’§ÅΩú(ÄÅΩ¡¡âïŸÖ…•πùÕ€ôÕ≠îÉäLÅòπï≠Ã∏ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îºƒµëÖ‰µÖç’Ÿ’îµµΩ•Õ–¥Ã¿µ¡Öç¨ºà˘ç’Ÿ’î(ÄÅ5Ω•Õ–ΩÑ¯Ω±§¯(Ω’∞¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅ°ÑÅ±•πÕï€ôÕ≠îÅ§Å£ïπëâÖùÖÕ©ï∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∞Åµï∏Åëï∏Å∑îÅõ·±ùîÅŸÖπ±•ùîÅ€ôÕ≠ï…ïù±ï»ÅôΩ»Å£ïπëâÖùÖÕ©îÄ°âï°Ω±ëï…îÅ’πëï»Äƒ¿¿Åµ∞§∏ÅY’…ëï»Å°ï±±ï»Å…ï•ÕïÕ”·……ï±Õï»Åï±±ï»ÅëÖùÕ±•πÕï»Å°Ÿ•ÃÅë‘ÅŸ•∞Å’ππüîÅ€ôÕ≠îÅ°ï±–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åâ±•»Å≠Ωπ—Ö≠—±•πÕï»Åµï»Å’≠ΩµôΩ…—Öâ±îÅ√îÅô±‰¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ-Öâ•π±’ô–Åï»ÅÕ€ô…–Å”·…»∞ÅπΩîÅÕΩ¥Å≠Ö∏Åù´·…îÅ±•πÕï»Åµ•πë…îÅâï°Öùï±•ùîÅ√îÅ±ÖπùîÅô±ÂŸπ•πùï»∏ÉaÂïëÀï¡ï»Åï±±ï»Åï∏Å¡Ö’ÕîÅµïêÅâ…•±±ï»Å≠Ö∏Å°©ï±¡î∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠ΩÕµï—•Õ≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-ΩÕµï—•Õ≠îÅΩúÅôÖ…ùïëîÅ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâÖ…ùïëîÅ≠Ωπ—Ö≠—±•πÕï»Åï»Å…ïÕï¡—ŸÖ…îÅ√îÅ±•¨Å±•π©îÅµïêÅÖπë…îÅ±•πÕï»∞ÅÕï±ÿÅ’—ï∏ÅÕ—Â…≠î∏ÅM±•¨ÅŸï±ùï»Åë‘Åëï¥Å—…Âù–∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘Ö…ùïëîÅΩúÅ≠ΩÕµï—•Õ≠îÅ≠Ωπ—Ö≠—±•πÕï»Åï»Å≠Ωπ—Ö≠—±•πÕï»Å√îÅ±•¨Å±•π©îÅµïêÅÖ±±îÅÖπë…îÉäL)ΩùœîÅëîÄÒÕ—…Ωπú˘’—ï∏ÅÕ—Â…≠îΩÕ—…Ωπú¯ÅÕΩ¥Å≠’∏Åïπë…ï»É·ÂïôÖ…ùï∏∏ÅîÅ…ïùπïÃÅÕΩ¥Åµïë•Õ•πÕ¨)’—Õ—Â»ÅΩúÅ≠…ïŸï»ÅÕÖµµîÅ—•±¡ÖÕπ•πúÅΩúÅ°Âù•ïπîÅÕΩ¥ÅÕÂπÕ≠Ω……•ùï…ïπëîÅ±•πÕï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘-´·¿ÅÖ±±—•êÅô…ÑÅÕï…ß·ÕîÅôΩ…°Öπë±ï…îΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘U≠ŸÖ±•ô•Õï…—îÄâôïÕ—•ŸÖ±±•πÕï»àÅï±±ï»Å≠ΩÕ—Âµï±•πÕï»Å≠´·¡–Å’—ï∏Å—•±¡ÖÕπ•πúÄ°òπï≠Ã∏Åô…Ñ)’Õï…ß·ÕîÅ’—ïπ±ÖπëÕ≠îÅπï——â’—•≠≠ï»§Å°Ö»ÅŸïÕïπ—±•úÅ£·Âï…îÅ…•Õ•≠ºÅôΩ»Åôï•∞Å¡ÖÕÕôΩ…¥ÅΩú+·Âï•πôï≠Õ©Ω∏Åïπ∏Å±•πÕï»Åô…ÑÅôΩ…°Öπë±ï…îÅÕΩ¥Åõ·±ùï»ÅπΩ…Õ≠îÅ≠…ÖÿÅ—•∞Åµïë•Õ•πÕ¨Å’—Õ—Â»ÉäL)ÕΩ¥Åòπï≠Ã∏ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωô…ïÕ°±ΩΩ¨Ωô…ïÕ°±ΩΩ¨µΩπïëÖ‰¥Ã¿µ¡Öç¨ºà˘…ïÕ°1ΩΩ¨)=πïÖ‰ΩÑ¯∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MÖµµîÅ…ïù±ï»ÅÕΩ¥ÅôΩ»ÅŸÖπ±•ùîÅ±•πÕï»Åù©ï±ëï»ËÅÕÂπÕ’πëï…œ·≠ï±ÕîΩ—•±¡ÖÕπ•πúÅ°ΩÃÅΩ¡—•≠ï»)õ·…Õ–∞ÅΩúÅÕÖµµîÅ°Âù•ïπï…’—•πï»ÅŸïêÅâ…’¨∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâQ…ïπùï»Å©ïúÅ…ïÕï¡–ÅôΩ»ÅôÖ…ùïëîÅ≠Ωπ—Ö≠—±•πÕï»Å’—ï∏ÅÕ—Â…≠î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∏ÅÖ…ùïëîÅ±•πÕï»Å…ïùπïÃÅÕΩ¥Åµïë•Õ•πÕ¨Å’—Õ—Â»Å’ÖπÕï—–ÅÕ—Â…≠î∞ÅΩúÅ≠…ïŸï»ÅÕÖµµîÅ—•±¡ÖÕπ•πúÅ°ΩÃÅΩ¡—•≠ï»ÅÕΩ¥ÅÕÂπÕ≠Ω……•ùï…ïπëîÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Åëï–Å—…Âù–ÉîÅ≠´·¡îÅâ•±±•ùîÅ≠ΩÕ—Âµï±•πÕï»Å’—ï∏Å—•±¡ÖÕπ•πú¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∞Åëï–Åô…ÖÀïëïÃ∏Å1•πÕï»Å≠´·¡–Å’—ï∏Å—•±¡ÖÕπ•πúÅô…ÑÅ’Õï…ß·ÕîÅ≠•±ëï»Å°Ö»ÅŸïÕïπ—±•úÅ£·Âï…îÅ…•Õ•≠ºÅôΩ»Åôï•∞Å¡ÖÕÕôΩ…¥ÅΩúÉ·Âï•πôï≠Õ©Ω∏Åïπ∏Å±•πÕï»Åô…ÑÅôΩ…°Öπë±ï…îÅÕΩ¥Åõ·±ùï»ÅπΩ…Õ≠îÅ≠…ÖÿÅ—•∞Åµïë•Õ•πÕ¨Å’—Õ—Â»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïπÃµµÖ—ï…•Ö±îàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ωπ—Ö≠—±•πÕïπÃÅµÖ—ï…•Ö±îà∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâΩ…Õ≠©ï±±ï∏Å√îÅÕ•±•≠Ωπ°Âë…Ωùï∞ÅΩúÅŸÖπ±•úÅ°Âë…Ωùï∞∞ÅΩúÅ°ŸΩ…ôΩ»ÅµÖ—ï…•Ö±ï–Å√ïŸ•…≠ï»Å≠ΩµôΩ…–ÅΩúÉ·Âï°ï±Õî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘5Ö—ï…•Ö±ï–Åï∏Å±•πÕîÅï»Å±Öùï–ÅÖÿÅÖŸù´·»Åâ±Öπ–ÅÖππï–Å°ŸΩ»ÅµÂîÅΩ≠ÕÂùï∏ÅÕΩ¥ÅÕ±•¡¡ï»)ù©ïππΩ¥Å—•∞Å°Ω…π°•ππï∏ÉäLÅπΩîÅ°Ω…π°•ππï∏Åï»ÅÖŸ°ïπù•úÅÖÿÅÕ•ëï∏Åëï∏Å•≠≠îÅ°Ö»Åïùπî)â±Ωìï…ï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘M•±•≠Ωπ°Âë…Ωùï∞Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘ï–ÅŸÖπ±•ùÕ—îÅµÖ—ï…•Ö±ï–Å§ÅµΩëï…πîÅ±•πÕï»Ä°•π≠±’ëï…–ÅëîÅô±ïÕ—îÅŸ§Åõ·±ùï»Å¡…•ÕïπîÅ√î)°ï»∞ÅÕΩ¥ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îΩÖç’Ÿ’îµΩÖÕÂÃ¥ÿµ¡Öç¨ºà˘ç’Ÿ’îÅ=ÖÕÂÃΩÑ¯§∏ÅM±•¡¡ï»Åù©ïππΩ¥)ŸïÕïπ—±•úÅµï»ÅΩ≠ÕÂùï∏Åïπ∏Åï±ë…îÅ°Âë…Ωùï∞µµÖ—ï…•Ö±ï»∞ÅπΩîÅÕΩ¥Å≠Ö∏Åù§Åâïë…îÅ≠ΩµôΩ…–ÅŸïê)±ÖπùîÅëÖùï»ÅµïêÅ±•πÕï»Å§∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘YÖπ±•úÅ°Âë…Ωùï∞Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘±ë…î∞Åµï∏ÅôΩ…—ÕÖ—–Å§Åâ…’¨Å§Åïπ≠ï±—îÅ±•πÕï»∏Å!Ö»Å—Â¡•Õ¨Å£·Âï…îÅŸÖππ•ππ°Ω±ê∞ÅÕΩ¥ÅôΩ»)πΩï∏Å≠Ö∏ÅΩ¡¡±ïŸïÃÅÖππï…±ïëïÃÅ≠ΩµôΩ…—Öâï±–Åïπ∏ÅÕ•±•≠Ωπ°Âë…Ωùï∞∞ÅÕ¡ïÕ•ï±–Å—•ë±•úÅ§)â…’≠Õ—•ëï∏∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘5Ö—ï…•Ö±îÅΩúÅŸÖππ•ππ°Ω±êÅÕ”ï»ÅΩ¡¡ù•—–Å’πëï»ÅÕ¡ïÕ•ô•≠ÖÕ©Ωπï»Å√îÅ°Ÿï»Å¡…Ωë’≠—Õ•ëîÅ°ï»)√îÅ-Ωπ—Ö≠—±•πÕï»ππº∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅôΩ…Õ≠©ï±±ï∏Å√îÅÕ•±•≠Ωπ°Âë…Ωùï∞ÅΩúÅŸÖπ±•úÅ°Âë…Ωùï∞¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâM•±•≠Ωπ°Âë…Ωùï∞ÅÕ±•¡¡ï»Åù©ïππΩ¥ÅŸïÕïπ—±•úÅµï»ÅΩ≠ÕÂùï∏Å—•∞Å°Ω…π°•ππï∏Åïπ∏Åï±ë…îÅ°Âë…Ωùï∞µµÖ—ï…•Ö±ï»∞ÅπΩîÅÕΩ¥Å≠Ö∏Åù§Åâïë…îÅ≠ΩµôΩ…–ÅŸïêÅ±ÖπùîÅëÖùï»ÅµïêÅ±•πÕï»Å§∏ÅYÖπ±•úÅ°Âë…Ωùï∞Å°Ö»ÅΩô—îÅ£·Âï…îÅŸÖππ•ππ°Ω±ê∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ω……•ùï…ïπëîµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ω……•ùï…ïπëîÅ≠Ωπ—Ö≠—±•πÕï»ÅŸïêÅÖÕ—•ùµÖ—•ÕµîÅΩúÅÖ±ëï…ÕÕÂ∏à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ëÖ∏Å—Ω…•Õ≠îÅ±•πÕï»Å≠Ω……•ùï…ï»ÅÖÕ—•ùµÖ—•Õµî∞ÅΩúÅ°ŸΩ…ëÖ∏Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»Å≠Ω……•ùï…ï»ÅÖ±ëï…ÕÕÂ∏∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘π≠ï∞Åªô…ÕÂπ—°ï–Åï±±ï»Å±ÖπùÕÂπ—°ï–Å≠Ω……•ùï…ïÃÅµïêÅÕõô…•Õ≠îÅ±•πÕï»∏ÅQºÅŸÖπ±•ùî)ÕÂπÕôΩ…°Ω±êÅ≠…ïŸï»Åïùπî∞Åµï»ÅÖŸÖπÕï…—îÅ±•πÕï—Â¡ï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘QΩ…•Õ≠îÅ±•πÕï»Ä°ÖÕ—•ùµÖ—•Õµî§Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘YïêÅÖÕ—•ùµÖ—•ÕµîÄ°Õ≠©ïÿÅ°Ω…π°•ππî§Å∑îÅ±•πÕï∏Å°ÑÅ’±•¨ÅÕ—Â…≠îÅ§Å’±•≠îÅ…ï—π•πùï»∞ÅΩú)±•ùùîÅÕ—Öâ•±–Å’—ï∏ÉîÅ…Ω—ï…îÅ§É·Âï–∏ÅQΩ…•Õ≠îÅ±•πÕï»Åï»ÅôΩ…µï–ÅÕ¡ïÕ•ï±–ÅôΩ»Åëï——î∞ÅΩú)≠…ïŸï»Åï∏Åµï»Åª·ÂÖ≠—•úÅ—•±¡ÖÕπ•πúÅïπ∏ÅŸÖπ±•ùîÅÕõô…•Õ≠îÅ±•πÕï»ÉäLÅòπï≠Ã∏(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰µ—Ω…•å¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ÅQΩ…•åΩÑ¯∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘5’±—•ôΩ≠Ö±îΩ¡…Ωù…ïÕÕ•ŸîÅ±•πÕï»Ä°Ö±ëï…ÕÕÂ∏§Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘…ÑÅ…’πë–Ä–√äL–‘∑ï…ÕÖ±ëï…ï∏ÅÕŸï≠≠ïÃÉ·Âï—ÃÅïŸπîÅ—•∞ÉîÅÕ—•±±îÅÕ≠Ö…¡–Å√îÅªô…–Å°Ω±ê∏)5’±—•ôΩ≠Ö±îÅ±•πÕï»Å°Ö»Åô±ï…îÅÕ—Â…≠ïÕΩπï»Å§ÅÕÖµµîÅ±•πÕîÄ°—Â¡•Õ¨ÅôΩ»Åªô…–∞Åµï±±Ωµë•Õ—ÖπÕî)ΩúÅ±Öπù–Å°Ω±ê∞ÅÕΩ¥ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰µµ’±—•ôΩçÖ∞¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰)5’±—•ôΩçÖ∞ΩÑ¯§∞ÅΩúÅ≠Ö∏Å≠…ïŸîÅï∏Å≠Ω…–Å—•±Ÿïππ•πùÕ¡ï…•ΩëîÅõ·»Å°©ï…πï∏Å≥ô…ï»ÉîÅâ…’≠îÅÕΩπïπî)…•≠—•ú∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘	ïùùîÅ—Â¡ï»Å≠…ïŸï»Åï∏Å¡…ïÕ•ÃÅ…ïÕï¡–Åô…ÑÅΩ¡—•≠ï»ÉäLÅëï——îÅï»Å•≠≠îÅπΩîÅµÖ∏Å≠Ö∏)—•±ªô…µîÅÕïúÅµïêÅï∏ÅŸÖπ±•úÅÕõô…•Õ¨ÅÕ—Â…≠î∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å≠Ö∏Å©ïúÅ•≠≠îÅâ…’≠îÅŸÖπ±•ùîÅ±•πÕï»ÅŸïêÅÖÕ—•ùµÖ—•Õµî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâYïêÅÖÕ—•ùµÖ—•ÕµîÅ∑îÅ±•πÕï∏Å°ÑÅ’±•¨ÅÕ—Â…≠îÅ§Å’±•≠îÅ…ï—π•πùï»ÅΩúÅ±•ùùîÅÕ—Öâ•±–Å’—ï∏ÉîÅ…Ω—ï…îÅ§É·Âï–∏Åï–Å≠…ïŸï»Å—Ω…•Õ≠îÅ±•πÕï»∞ÅôΩ…µï–ÅÕ¡ïÕ•ï±–ÅôΩ»Åëï——î∞ÅµïêÅï∏Åµï»Åª·ÂÖ≠—•úÅ—•±¡ÖÕπ•πúÅïπ∏ÅÕõô…•Õ≠îÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ7îÅ©ïúÅŸïππîÅµïúÅ—•∞Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ=ô—îÅ©Ñ∏Å5’±—•ôΩ≠Ö±îÅ±•πÕï»Å°Ö»Åô±ï…îÅÕ—Â…≠ïÕΩπï»Å§ÅÕÖµµîÅ±•πÕî∞ÅΩúÅëï–Å≠Ö∏Å—ÑÅï∏Å≠Ω…–Å—•±Ÿïππ•πùÕ¡ï…•ΩëîÅõ·»Å°©ï…πï∏Å≥ô…ï»ÉîÅâ…’≠îÅÕΩπïπîÅ…•≠—•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡…Ωë’≠Õ©Ω∏µÖÿµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâM±•¨Å¡…Ωë’Õï…ïÃÅ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ-Ω…–ÅΩ¥Å°ŸΩ…ëÖ∏ÅµΩëï…πîÅµÂ≠îÅ≠Ωπ—Ö≠—±•πÕï»Å¡…Ωë’Õï…ïÃ∞Å≠ŸÖ±•—ï—ÕÕ•≠…ïÃÅΩúÅ…ïù’±ï…ïÃÅÕΩ¥Åµïë•Õ•πÕ¨Å’—Õ—Â»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘îÅô±ïÕ—îÅµΩëï…πîÅµÂ≠îÅ≠Ωπ—Ö≠—±•πÕï»Å¡…Ωë’Õï…ïÃÅŸïêÄÒÕ—…Ωπú˘Õ”·¡•πúΩÕ—…Ωπú¯ËÅô±Â—ïπëî)±•πÕïµÖ—ï…•Ö±îÅÕ¡À·Â—ïÃÅ•π∏Å§Å¡…ïÕ•ÕîÅ¡±ÖÕ—ôΩ…µï»ÅÕΩ¥Åù•»Å±•πÕï∏Å…•≠—•úÅ≠…’µπ•πú∞)ë•Öµï—ï»ÅΩúÅÕ—Â…≠î∞Åõ·»Åëï∏Å°ï…ëïÃÅΩúÅâïÖ…âï•ëïÃÅôï…ë•úÅ§ÅÕ—ï…•±îÅ±Ω≠Ö±ï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘-ŸÖ±•—ï—Õ≠Ωπ—…Ω±∞ÅΩúÅ…ïù’±ï…•πúΩ†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘!Ÿï»Å±•πÕîÅ≠Ωπ—…Ω±±ï…ïÃÅôΩ»Å…•≠—•úÅôΩ…¥ÅΩúÅÕ—Â…≠îÅõ·»Å¡Ö≠≠•πúΩ±§¯(ÄÄÒ±§˘1•πÕïπîÅ¡Ö≠≠ïÃÅ§ÅÕ—ï…•∞ÅÕÖ±—ŸÖππÕ≥·Õπ•πúÅ§ÅôΩ…Õïù±ï–ÅïµâÖ±±ÖÕ©îΩ±§¯(ÄÄÒ±§˘-Ωπ—Ö≠—±•πÕï»Å…ïùπïÃÅÕΩ¥Åµïë•Õ•πÕ¨Å’—Õ—Â»Å§ÅTΩaLÅΩúÅÕ≠Ö∞Å€ô…îÅµµï…≠ï–Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘ïππîÅÕ—…ïπùîÅ¡…Ωë’≠Õ©ΩπÃ¥ÅΩúÅ≠ŸÖ±•—ï—Õ≠Ωπ—…Ω±±ï∏Åï»Åï∏ÅÖÿÅù…’ππïπîÅ—•∞ÅÖ–Åëï–Å≥·ππï»)ÕïúÉîÅ≠´·¡îÅ±•πÕï»Åô…ÑÅôΩ…°Öπë±ï…îÅÕΩ¥Åõ·±ùï»Å…ïùï±Ÿï…≠ï–∞Å•≠≠îÅ’…ïù’±ï…—îÅ≠•±ëï»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏Å±ÖùïÃÅµÂ≠îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâîÅô±ïÕ—îÅ¡…Ωë’Õï…ïÃÅŸïêÅÕ”·¡•πúËÅô±Â—ïπëîÅ±•πÕïµÖ—ï…•Ö±îÅÕ¡À·Â—ïÃÅ•π∏Å§Å¡…ïÕ•ÕîÅ¡±ÖÕ—ôΩ…µï»ÅÕΩ¥Åù•»Å…•≠—•úÅ≠…’µπ•πú∞Åë•Öµï—ï»ÅΩúÅÕ—Â…≠î∞Åõ·»Å±•πÕï∏Å°ï…ëïÃ∞Å≠Ωπ—…Ω±±ï…ïÃÅΩúÅ¡Ö≠≠ïÃÅ§ÅÕ—ï…•∞ÅÕÖ±—ŸÖππÕ≥·Õπ•πú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïπÃµ°•Õ—Ω…•îàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ωπ—Ö≠—±•πÕïπÃÅ°•Õ—Ω…•îà∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ…ÑÅ1ïΩπÖ…ëºÅëÑÅY•πç•ÃÅ—•ë±•ùîÅÕ≠•ÕÕï»Å—•∞ÅµΩëï…πîÅëÖùÕ±•πÕï»ÉäLÅï∏Å≠Ω…–Å°•Õ—Ω…•≠¨ÅΩ¥Å≠Ωπ—Ö≠—±•πÕïπÃÅ’—Ÿ•≠±•πú∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘%ëïï∏ÅΩ¥Åï∏Å±•πÕîÅÕΩ¥Å±•ùùï»Åë•…ï≠—îÅ√îÉ·Âï–Åï»ÅΩŸï……ÖÕ≠ïπëîÅùÖµµï∞∞Åµï∏Åëï–Å—Ω¨+ï…°’πë…ï»Åõ·»Å—ï≠πΩ±Ωù•ï∏ÅôÖπ—ïÃÅôΩ»ÉîÅôÖ≠—•Õ¨Å±ÖùîÅëï∏∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘…ÑÅ•ì§Å—•∞Åù±ÖÕÕ±•πÕîΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘1ïΩπÖ…ëºÅëÑÅY•πç§ÅÕ≠•ÕÕï…—îÅ≠ΩπÕï¡—ï»ÅÕΩ¥Å≠Ö∏Åµ•ππîÅΩ¥Å≠Ωπ—Ö≠—±•πÕï»ÅÖ±±ï…ïëîÅ…’πë–(ƒ‘¿‡∞Åµï∏Åëï——îÅŸÖ»Å—ïΩ…ï—•Õ≠îÅ—ïùπ•πùï»∞Å•≠≠îÅπΩîÅÕΩ¥Å≠’ππîÅâ…’≠ïÃ∏ÅîÅõ·…Õ—îÅ…ïï±±î)≠Ωπ—Ö≠—±•πÕïπîÉäLÅ—’πùîÅù±ÖÕÕ±•πÕï»ÅÕΩ¥Åëï≠≠ï–Å°ï±îÅëï–ÅÕÂπ±•ùîÉ·Âï–Ä°Õ≠±ï…Ö±•πÕï»§ÉäL)≠Ω¥Åõ·…Õ–Å√îÅÕ±’——ï∏ÅÖÿÄƒ‡¿¿µ—Ö±±ï–∞ÅΩúÅŸÖ»Å±Öπù–Åô…ÑÅ≠ΩµôΩ…—Öâ±îÅŸïêÅëÖùïπÃ)Õ—ÖπëÖ…ê∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘A±ÖÕ–ÅΩúÅëï∏ÅµΩëï…πîÅµÂ≠îÅ±•πÕï∏Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘1ï——ï…îÅ¡±ÖÕ—±•πÕï»Å≠Ω¥Å√îÄƒ‰Ã√äL–¿µ—Ö±±ï–∏Åï–ÅŸ•…≠ï±•úÅÕ—Ω…îÅù©ïππΩµâ…’ëëï–Å≠Ω¥Å§(ƒ‰ÿƒ∞ÅëÑÅëï∏Å—Õ©ï≠≠•Õ≠îÅ≠©ïµ•≠ï…ï∏Å=——ºÅ]•ç°—ï…±îÅ’—Ÿ•≠±ï–Åëï∏Åõ·…Õ—îÅµÂ≠î)°Âë…Ωùï∞µ≠Ωπ—Ö≠—±•πÕï∏ÉäLÅµÖ—ï…•Ö±ï–ÅÕΩ¥ÅôΩ…—ÕÖ—–Å±•ùùï»Å—•∞Åù…’π∏ÅôΩ»ÅëîÅô±ïÕ—îÅ±•πÕï»)ÕΩ¥ÅÕï±ùïÃÅ§ÅëÖú∏ÅÖùÕ±•πÕï»Ä°—•∞ÅïπùÖπùÕâ…’¨§Åâ±îÅŸÖπ±•úÅô…ÑÄƒ‰‰¿µ—Ö±±ï–ÅΩúÅ’—ΩŸï»∞ÅΩú)ï»Å§ÅëÖúÅï–ÅÖÿÅëîÅµïÕ–Åâ…’≠—îÅÖ±—ï…πÖ—•Ÿïπî∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!Ÿï¥ÅΩ¡¡ôÖπ–Åëï∏ÅµΩëï…πîÅµÂ≠îÅ≠Ωπ—Ö≠—±•πÕï∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâï∏Å—Õ©ï≠≠•Õ≠îÅ≠©ïµ•≠ï…ï∏Å=——ºÅ]•ç°—ï…±îÅ’—Ÿ•≠±ï–Åëï∏Åõ·…Õ—îÅµÂ≠îÅ°Âë…Ωùï∞µ≠Ωπ—Ö≠—±•πÕï∏Å§Äƒ‰ÿƒÉäLÅµÖ—ï…•Ö±ï–ÅÕΩ¥ÅôΩ…—ÕÖ—–Å±•ùùï»Å—•∞Åù…’π∏ÅôΩ»ÅëîÅô±ïÕ—îÅ±•πÕï»ÅÕΩ¥ÅÕï±ùïÃÅ§ÅëÖú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ—ï…Ö¡ï’—•Õ≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâQï…Ö¡ï’—•Õ≠îÅ≠Ωπ—Ö≠—±•πÕï»Ä°âÖπëÖÕ©ï±•πÕï»§à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâQï…Ö¡ï’—•Õ≠îÅ≠Ωπ—Ö≠—±•πÕï»Åâ…’≠ïÃÅ—•∞ÉîÅâïÕ≠Â——îÅï±±ï»Åâï°Öπë±îÉ·Âï–Åµïë•Õ•πÕ¨∞Å•≠≠îÅ—•∞ÅÕÂπÕ≠Ω……•ùï…•πú∞ÅΩúÅôΩ…Õ≠…•ŸïÃÅÖÿÉ·Âï±ïùî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘Qï…Ö¡ï’—•Õ≠îÅ≠Ωπ—Ö≠—±•πÕï»Ä°Ωô—îÅ≠Ö±–ÅâÖπëÖÕ©ï±•πÕï»§Å°Ö»Åï–ÅÖππï–ÅôΩ…∑ï∞Åïπ∏ÅŸÖπ±•ùî)≠Ωπ—Ö≠—±•πÕï»ËÅëîÅâ…’≠ïÃÅ•≠≠îÅ¡…•∑ô…–ÅôΩ»ÉîÅ≠Ω……•ùï…îÅÕÂπï–∞Åµï∏ÅôΩ»ÉîÅâïÕ≠Â——îÅï±±ï»)âï°Öπë±îÅÕï±ŸîÉ·Âï–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘YÖπ±•ùîÅâ…’≠ÕΩµÀïëï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘	ïÕ≠Â——îÅ°Ω…π°•ππïπÃÅΩŸï…ô±Ö—îÅµïπÃÅëï∏Åù…Ω»Åï——ï»ÅÕ≠Öëî∞Åâï—ïππï±ÕîÅï±±ï»Å≠•…’…ù§Ω±§¯(ÄÄÒ±§˘1•πë…îÅÕµï…—îÅŸïêÅïπ≠ï±—îÅ°Ω…π°•ππï—•±Õ—Öπëï»Ω±§¯(ÄÄÒ±§˘!Ω±ëîÅï∏Å’Õ—Öâ•∞Å°Ω…π°•ππïΩŸï…ô±Ö—îÅ√îÅ¡±ÖÕÃÅ’πëï»Å—•±°ï±•πúΩ±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘Qï…Ö¡ï’—•Õ≠îÅ±•πÕï»ÅôΩ…Õ≠…•ŸïÃÅΩúÅõ·±ùïÃÅΩ¡¿ÅÖÿÄÒÕ—…Ωπú˚·Âï±ïùîΩÕ—…Ωπú¯∞Å•≠≠îÅŸÖ±ù–)Õï±ÿÅÕ±•¨ÅµÖ∏Å≠Ö∏ÅŸï±ùîÅÕÂπÕ≠Ω……•ùï…ïπëîÅ±•πÕï»Å°ΩÃÅΩ¡—•≠ï»∏Å	…’≠ï∏∞ÅŸÖ…•ù°ï—ï∏ÅΩú)Ω¡¡õ·±ù•πùï∏Åï»Å•πë•Ÿ•ë’ï±–Å—•±¡ÖÕÕï–Åëï∏Åµïë•Õ•πÕ≠îÅ—•±Õ—Öπëï∏∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»Åï∏Å—ï…Ö¡ï’—•Õ¨Å≠Ωπ—Ö≠—±•πÕîÄ°âÖπëÖÕ©ï±•πÕî§¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ∏Å±•πÕîÅÕΩ¥Åâ…’≠ïÃÅ—•∞ÉîÅâïÕ≠Â——îÅï±±ï»Åâï°Öπë±îÉ·Âï–Åµïë•Õ•πÕ¨ÉäLÅôΩ»Åï≠Õïµ¡ï∞ÅôΩ»ÉîÅâïÕ≠Â——îÅ°Ω…π°•ππï∏Å’πëï»Å—•±°ï±•πúÅï——ï»ÅÕ≠ÖëîÅï±±ï»Å≠•…’…ù§ÉäLÅ•≠≠îÅ¡…•∑ô…–ÅôΩ»ÉîÅ≠Ω……•ùï…îÅÕÂπï–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅŸï±ùîÅ—ï…Ö¡ï’—•Õ≠îÅ±•πÕï»ÅÕï±ÿ¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏ÅQï…Ö¡ï’—•Õ≠îÅ±•πÕï»ÅôΩ…Õ≠…•ŸïÃÅΩúÅõ·±ùïÃÅΩ¡¿ÅÖÿÉ·Âï±ïùîÅ’–Åô…ÑÅï∏Åµïë•Õ•πÕ¨ÅŸ’…ëï…•πú∞Å•≠≠îÅŸÖ±ù–ÅÕï±ÿÅÕ±•¨ÅµÖ∏ÅŸï±ùï»ÅÕÂπÕ≠Ω……•ùï…ïπëîÅ±•πÕï»Å°ΩÃÅΩ¡—•≠ï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•ÕµîàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâQΩ…•Õ≠îÅ±•πÕï»ÅΩúÅÖÕ—•ùµÖ—•Õµîà∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸÑÅÖÕ—•ùµÖ—•ÕµîÅï»∞Å°ŸΩ…ôΩ»Åëï–Å≠…ïŸï»Å—Ω…•Õ≠îÅ±•πÕï»∞ÅΩúÅ°ŸΩ…ôΩ»Åë•ÕÕîÅï»Å±•—–Åµï»Å≠…ïŸïπëîÉîÅ—•±¡ÖÕÕîÅïπ∏ÅŸÖπ±•ùîÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘Õ—•ùµÖ—•ÕµîÅâï—Â»ÅÖ–Å°Ω…π°•ππï∏Å°Ö»Åï∏Å±•—–Å’…ïùï±µïÕÕ•ú∞ÅΩŸÖ±ôΩ…µï–Å≠…’µπ•πúÅ§)Õ—ïëï–ÅôΩ»ÉîÅ€ô…îÅ©ïŸπ–Å…’πê∏Åï–Åù´·»ÅÖ–ÅÕÂ∏Å≠Ö∏Åâ±§Å’Õ≠Ö…¡–Åï±±ï»ÅôΩ…Ÿ…ïπù–Å√îÅãïëî)ªô…–ÅΩúÅ±Öπù–Å°Ω±êÉäLÅ•≠≠îÅâÖ…îÅëï–Åïπî∞ÅÕΩ¥ÅŸïêÅŸÖπ±•úÅªô»¥Åï±±ï»Å±ÖπùÕÂπ—°ï–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸÑÅï»Å—Ω…•Õ≠îÅ±•πÕï»¸Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘QΩ…•Õ≠îÅ±•πÕï»Åï»Å≠Ωπ—Ö≠—±•πÕï»ÅÕ¡ïÕ•Ö±ôΩ…µï–ÅôΩ»ÉîÅ≠Ω……•ùï…îÅÖÕ—•ùµÖ—•Õµî∏Å$ÅµΩ—Õï—π•πú)—•∞Åï∏ÅŸÖπ±•úÅÕõô…•Õ¨Å±•πÕîÄ°ÕΩ¥Å°Ö»Å±•¨ÅÕ—Â…≠îÅ§ÅÖ±±îÅ…ï—π•πùï»ÅΩúÅ≠Ö∏Å…Ω—ï…îÅô…•—–Å’—ï∏)Ö–Åëï–Åµï…≠ïÃ§Å∑îÅï∏Å—Ω…•Õ¨Å±•πÕîÅ°ÑÅ’±•¨ÅÕ—Â…≠îÅ§Å’±•≠îÅ…ï—π•πùï»∞ÅΩúÅëï∏Å∑îÅ±•ùùîÅÕ—Öâ•±–)§Å…•≠—•úÅ¡ΩÕ•Õ©Ω∏ÅôΩ»ÉîÅŸ•…≠î∏Å1•πÕïπîÅï»Åëï…ôΩ»ÅâÂùùï–ÅµïêÅï∏Å±•—–Å—Âπù…îÅπïë…îÅ≠Öπ–Åï±±ï»)—ÂππÕΩπï»ÅÕΩ¥Åù´·»ÅÖ–ÅëîÄâ…ï——ï»ÅÕïúÅÕï±ÿÅΩ¡¿àÅ√îÉ·Âï–ÉäLÅòπï≠Ã∏(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îΩÖç’Ÿ’îµΩÖÕÂÃµôΩ»µÖÕ—•ùµÖ—•Õ¥¥ÿµ¡Öç¨ºà˘ç’Ÿ’îÅ=ÖÕÂÃÅôΩ»)Õ—•ùµÖ—•Õ¥ΩÑ¯∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸΩ…ôΩ»Å—•±¡ÖÕπ•πùï∏Åï»Å±•—–Åµï»Å≠…ïŸïπëîΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘Ω…ë§Å±•πÕï∏Å∑îÅÕ”îÅ…•≠—•úÅŸï§∞Å—…ïπùï»ÅΩ¡—•≠ï…ï∏Åµï»Å¡…ïÕ•ÃÅ•πôΩ…µÖÕ©Ω∏Åô…Ñ)ÕÂπÕ’πëï…œ·≠ï±Õï∏Ä°Õ—Â…≠î∞ÅÕÂ±•πëï…≠Ω……ï≠Õ©Ω∏ÅΩúÅÖ≠Õï∏Åëï∏ÅÕ≠Ö∞Å±•ùùîÅ§§Åïπ∏ÅŸïêÅï∏ÅŸÖπ±•ú)Õõô…•Õ¨Å±•πÕî∏Å9Ωï∏ÅõîÅ¡À·Ÿï»ÅÕïúÅô…ï¥Å—•∞ÅâïÕ—îÅ¡ÖÕÕôΩ…¥∞ÅÕ¡ïÕ•ï±–ÅŸïêÅ£·Âï…îÅù…ÖêÅÖÿ)ÖÕ—•ùµÖ—•Õµî∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MîÅ€ï»ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ω—Ω…•Õ≠îµ±•πÕï»ºà˘ΩŸï…Õ•≠–ÅΩŸï»Å—Ω…•Õ≠îÅ±•πÕï»ΩÑ¯)ôΩ»ÉîÅÕÖµµïπ±•ùπîÅ¡…•Õï»Å√îÅ—Ÿï…ÃÅÖÿÅµï…≠ï»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅôΩ…Õ≠©ï±±ï∏Å√îÅï∏ÅŸÖπ±•úÅΩúÅï∏Å—Ω…•Õ¨Å±•πÕî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ∏ÅŸÖπ±•úÅÕõô…•Õ¨Å±•πÕîÅ°Ö»Å±•¨ÅÕ—Â…≠îÅ§ÅÖ±±îÅ…ï—π•πùï»ÅΩúÅ≠Ö∏Å…Ω—ï…îÅô…•—–∏Å∏Å—Ω…•Õ¨Å±•πÕîÄ°ôΩ»ÅÖÕ—•ùµÖ—•Õµî§Å°Ö»Å’±•¨ÅÕ—Â…≠îÅ§Å’±•≠îÅ…ï—π•πùï»ÅΩúÅ∑îÅ±•ùùîÅÕ—Öâ•±–Å§Å…•≠—•úÅ¡ΩÕ•Õ©Ω∏ÅôΩ»ÉîÅ≠Ω……•ùï…îÅÕÂπï–Å…•≠—•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å—Ö»Åëï–Å±•—–Å±ïπù…îÅ—•êÉîÅ—•±¡ÖÕÕîÅ—Ω…•Õ≠îÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ…ë§Å±•πÕï∏Å∑îÅ±•ùùîÅ…•≠—•úÅŸï§Å√îÉ·Âï–∞Å—…ïπùÃÅµï»Å¡…ïÕ•ÃÅ•πôΩ…µÖÕ©Ω∏Åô…ÑÅÕÂπÕ’πëï…œ·≠ï±Õï∏Ä°ÕÂ±•πëï…Õ—Â…≠îÅΩúÅÖ≠Õî§∞ÅΩúÅπΩï∏ÅõîÅ¡À·Ÿï»ÅÕïúÅô…ï¥Å—•∞ÅâïÕ—îÅ¡ÖÕÕôΩ…¥∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ5’±—•ôΩ≠Ö±îÅ≠Ωπ—Ö≠—±•πÕï»ÅŸïêÅÖ±ëï…ÕÕÂ∏à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ëÖ∏Åµ’±—•ôΩ≠Ö±îÅ≠Ωπ—Ö≠—±•πÕï»Åô’πùï…ï»ÅŸïêÅÖ±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§∞ÅΩúÅ°ŸΩ»Å±ÖπúÅ—•±Ÿïππ•πúÅµÖ∏Å≠Ö∏ÅôΩ…Ÿïπ—î∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§Åï»Åï∏ÅπÖ—’…±•ú∞ÅÖ±ëï…Õ…ï±Ö—ï…–ÅÕŸï≠≠ï±ÕîÅÖÿÉ·Âï—ÃÅïŸπîÅ—•∞Éî)Õ—•±±îÅÕ≠Ö…¡–Å√îÅªô…–Å°Ω±ê∞ÅÕΩ¥ÅëîÅô±ïÕ—îÅµï…≠ï»Åô…ÑÅ…’πë–Ä–√äL–‘∑ï…ÕÖ±ëï…ï∏∏)5’±—•ôΩ≠Ö±îÅ≠Ωπ—Ö≠—±•πÕï»Åï»Å±Öùï–ÅôΩ»ÉîÅ≠Ω……•ùï…îÅëï——î∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸΩ…ëÖ∏Åô’πùï…ï»Åëî¸Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘$ÅÕ—ïëï–ÅôΩ»ÉîÅâÂ——îÅµï±±Ω¥ÅÕΩπï»ÅÕ±•¨ÅµÖ∏Åù´·»ÅµïêÅ¡…Ωù…ïÕÕ•ŸîÅâ…•±±ïù±ÖÕÃ∞Å°Ö»)µ’±—•ôΩ≠Ö±îÅ±•πÕï»Åô±ï…îÅÕ—Â…≠ïÕΩπï»Å—•±ù©ïπùï±•úÅÕÖµ—•ë•úÄ°ôΩ»Åªô…–∞Åµï±±Ωµë•Õ—ÖπÕîÅΩú)±Öπù–Å°Ω±ê∞ÅÕΩ¥Å§ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îΩÖç’Ÿ’îµΩÖÕÂÃµµ’±—•ôΩçÖ∞¥ÿµ¡Öç¨ºà˘ç’Ÿ’îÅ=ÖÕÂÃ)5’±—•ôΩçÖ∞ΩÑ¯§∏Å!©ï…πï∏Å≥ô…ï»Åù…ÖëŸ•ÃÉîÅ¡…•Ω…•—ï…îÅ…•≠—•úÅÕΩπîÅÖŸ°ïπù•úÅÖÿÅ°ŸÑÅë‘ÅÕï»Å√î+äLÅëï——îÅ≠Ö±±ïÃÅÕ•µ’±—ÖπŸ•Õ©Ω∏∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Q•±Ÿïππ•πúΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘îÅô±ïÕ—îÅâ…’≠ï»Ä«äL»Å’≠ï»Å√îÉîÅŸïππîÅÕïúÅ—•∞Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»∏ÅU±•≠îÅëïÕ•ù∏Ä°òπï≠Ã∏)µïêÅÕ≠Ö…¡ïÕ—îÅÕΩπîÅÕïπ—…ï…–ÅôΩ»Åªô»¥Åï±±ï»Å±ÖπùÕÂ∏§Å¡ÖÕÕï»Å’±•≠–Åô…ÑÅ¡ï…ÕΩ∏Å—•∞Å¡ï…ÕΩ∏ÉäL)ëï——îÅï»ÅπΩîÅΩ¡—•≠ï…ï∏Å°©ï±¡ï»ÅëïúÉîÅô•ππîÅô…Ö¥Å—•∞∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MîÅ€ï»ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωµ’±—•ôΩ≠Ö±îµ±•πÕï»ºà˘ΩŸï…Õ•≠–ÅΩŸï»Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»ΩÑ¯)ôΩ»ÉîÅÕÖµµïπ±•ùπîÅ¡…•Õï»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏Åô’πùï…ï»Åµ’±—•ôΩ≠Ö±îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâîÅ°Ö»Åô±ï…îÅÕ—Â…≠ïÕΩπï»Å—•±ù©ïπùï±•úÅÕÖµ—•ë•úÄ°ªô…–∞Åµï±±Ωµë•Õ—ÖπÕî∞Å±Öπù–Å°Ω±ê§∞ÅΩúÅ°©ï…πï∏Å≥ô…ï»Åù…ÖëŸ•ÃÉîÅ¡…•Ω…•—ï…îÅ…•≠—•úÅÕΩπîÅÖŸ°ïπù•úÅÖÿÅ°ŸÑÅë‘ÅÕï»Å√îÄ°Õ•µ’±—ÖπŸ•Õ©Ω∏§∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»Å±ÖπúÅ—•êÅ—Ö»Åëï–ÉîÅŸïππîÅÕïúÅ—•∞Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâYÖπ±•ùŸ•ÃÄ«äL»Å’≠ï»∞Åµï∏Åëï–ÅŸÖ…•ï…ï»Åô…ÑÅ¡ï…ÕΩ∏Å—•∞Å¡ï…ÕΩ∏∏ÅU±•≠îÅ±•πÕïëïÕ•ù∏Å¡ÖÕÕï»Å’±•≠–∞ÅΩúÅΩ¡—•≠ï…ï∏Å°©ï±¡ï»ÅëïúÉîÅô•ππîÅ…•≠—•úÅ—Â¡î∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µµÖ∏µÕΩŸîµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ö∏ÅµÖ∏ÅÕΩŸîÅµïêÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»ÅëîÅô±ïÕ—îÅ≠Ωπ—Ö≠—±•πÕï»Å•≠≠îÅã·»Åâ…’≠ïÃÅ’πëï»Åœ·Ÿ∏∞ÅΩúÅ°Ÿ•±≠îÅ’ππ—Ö¨ÅÕΩ¥Åô•ππïÃ∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘5ïêÅëîÅô±ïÕ—îÅŸÖπ±•ùîÅëÖùÃ¥ÅΩúÅ∑ïπïëÕ±•πÕï»ËÄÒÕ—…Ωπú˘πï§ΩÕ—…Ωπú¯∞Åë‘Åã·»Å•≠≠îÅÕΩŸîÅµïê)±•πÕïπîÅ§∏Å–Å±’≠≠ï–É·Âï±Ω≠¨Å…ïë’Õï…ï»Å§ÅÕïúÅÕï±ÿÅΩ≠ÕÂùïπ—•±õ·…Õï±ï∏Å—•∞Å°Ω…π°•ππï∏∞ÅΩúÅï∏)±•πÕîÅΩ¡√îÅù´·»Åëï——îÅïπëÑÅµ•πë…î∏ÉÅÕΩŸîÅµïêÅ±•πÕï»Åï»ÅΩùœîÅôΩ…â’πëï–ÅµïêÅŸïÕïπ—±•ú)£·Âï…îÅ…•Õ•≠ºÅôΩ»É·Âï•πôï≠Õ©Ω∏∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘•ππïÃÅëï–Å’ππ—Ö¨¸Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘π≠ï±—îÅ±•πÕï—Â¡ï»Åï»ÅÕ¡ïÕ•ï±–ÅùΩë≠©ïπ–ÅôΩ»Å≠Ωπ—•π’ï…±•úÅâ…’¨Ä°œï≠Ö±–Äâï·—ïπëïêÅ›ïÖ»à§∞)ëï»ÅµÖ∏Å≠Ö∏ÅÕΩŸîÅµïêÅ±•πÕïπîÅ§ÅΩŸï»Åô±ï…îÅì·ù∏∏Åï——îÅù©ï±ëï»Å≠’∏ÅÕ¡ïÕ•ô•≠≠î∞)ùΩë≠©ïπ—îÅ±•πÕï»∞ÅΩúÅ≠’∏Åï——ï»ÅÖ–Åï∏É·Âï±ïùîÅï±±ï»ÅΩ¡—•≠ï»Å°Ö»ÅŸ’…ëï…–ÅΩúÅùΩë≠©ïπ–)Ö≠≠’…Ö–Åëï–ÅôΩ»ÅëïúÉäLÅ•≠≠îÅπΩîÅµÖ∏ÅŸï±ùï»ÅÕï±ÿÅÕΩ¥ÅÕ—ÖπëÖ…ê∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!Ÿ•ÃÅëï–ÅÕ≠©ï»ÅŸïêÅï–Å’°ï±∞Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘!Ö»Åë‘ÅÕΩŸπï–ÅµïêÅŸÖπ±•ùîÅ±•πÕï»Å§∞Å—ÑÅëï¥Å’–ÅœîÅÕπÖ…–Åë‘Å€ï≠πï»ÅΩúÅù§É·ÂπïπîÅï∏Å¡Ö’Õî∏)QÑÅ≠Ωπ—Ö≠–ÅµïêÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÅ°Ÿ•ÃÅë‘Åµï…≠ï»ÅÀ·ë°ï–∞ÅÕµï…—îÅï±±ï»Å’≠±Ö…–ÅÕÂ∏)ï——ï…√î∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘%õ·±ùîÄÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩÕÂ≠ëΩµµï»ΩΩÂîΩâ…Â—π•πùÕôï•∞µπïëÕÖ—–µÕÂ∏Ω≠Ωπ—Ö≠—±•πÕï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9Ω…Õ¨Å!ï±Õï•πôΩ…µÖ—•≠¨Ä°9!$§ΩÑ¯Åï»Å…•Õ•≠Ωï∏ÅôΩ»Åœï»Å√îÅ°Ω…π°•ππï∏Åœô…±•úÅÕ—Ω»ÅŸïêÅâ…’¨ÅÖÿÅ±•πÕï»ÅΩŸï»ÅπÖ——ï∏ËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩπ°§ππºΩÕÂ≠ëΩµµï»ΩΩÂîΩâ…Â—π•πùÕôï•∞µπïëÕÖ—–µÕÂ∏Ω≠Ωπ—Ö≠—±•πÕï»àÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘1•πÕïπîÅ≠Ö∏Åù§Åœï»Å√îÅ°Ω…π°•ππï∏∏Å5Â≠îÅ≠Ωπ—Ö≠—±•πÕï»Åù•»Å±ï——ï…îÅœï»Åïπ∏Å°Ö…ëî∏ÅI•Õ•≠Ωï∏Åï»Åœô…±•úÅÕ—Ω»Å°Ÿ•ÃÅ±•πÕïπîÅâ…’≠ïÃÅΩŸï»ÅπÖ——ï∏∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩÕÂ≠ëΩµµï»ΩΩÂîΩâ…Â—π•πùÕôï•∞µπïëÕÖ—–µÕÂ∏Ω≠Ωπ—Ö≠—±•πÕï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9!$∞Å-Ωπ—Ö≠—±•πÕï»ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ·»Å©ïúÅÕΩŸîÅµïêÅ≠Ωπ—Ö≠—±•πÕïπîÅµ•πî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∞Å•≠≠îÅµïêÅŸÖπ±•ùîÅëÖùÃ¥Åï±±ï»Å∑ïπïëÕ±•πÕï»∏Åï–Å…ïë’Õï…ï»ÅΩ≠ÕÂùïπ—•±õ·…Õï±ï∏Å—•∞Å°Ω…π°•ππï∏ÅΩúÉ·≠ï»Å…•Õ•≠Ωï∏ÅôΩ»É·Âï•πôï≠Õ©Ω∏ÅŸïÕïπ—±•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ•ππïÃÅëï–Å±•πÕï»ÅµÖ∏Å≠Ö∏ÅÕΩŸîÅµïê¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∞Åïπ≠ï±—îÅ±•πÕï»Åï»ÅÕ¡ïÕ•ï±–ÅùΩë≠©ïπ–ÅôΩ»Å≠Ωπ—•π’ï…±•úÅâ…’¨ÅΩŸï»Åô±ï…îÅì·ù∏∞Åµï∏Å≠’∏Åï——ï»ÅÖ–Åï∏É·Âï±ïùîÅï±±ï»ÅΩ¡—•≠ï»Å°Ö»ÅŸ’…ëï…–ÅΩúÅùΩë≠©ïπ–Åπï——Ω¡¿Åëï–ÅôΩ»Åëïú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µµÖ∏µë’Õ©îµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ’Õ©îÅµïêÅ≠Ωπ—Ö≠—±•πÕï»¸ÅM±•¨Å’ππüï»Åë‘Å¡…Ωâ±ïµï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‰¥¿‘à∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ-Ω…–ÅÕŸÖ»ËÅ’ππüîÅŸÖπ∏Å§Å±•πÕïπîÅ°Ÿ•ÃÅë‘Å≠Ö∏∏ÅMîÅ°ŸΩ…ôΩ»∞ÅΩúÅª·ÂÖ≠—•úÅ°ŸÑÅë‘ÅÕ≠Ö∞Åù´·…îÅ°Ÿ•ÃÅëîÅâ±•»Å€ï—îÅ±•≠ïŸï∞∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ï–ÅÖπâïôÖ±ïÃÉîÅ’ππüîÅÖ–Å≠Ωπ—Ö≠—±•πÕïπîÅ≠Ωµµï»Å§Å≠Ωπ—Ö≠–ÅµïêÅŸÖπ∏ÉäLÅïπ—ï∏Åëï–Åï»)ë’Õ©ŸÖπ∏∞ÅâÖÕÕïπùŸÖπ∏Åï±±ï»ÅŸÖπ∏Åô…ÑÅÕ´‡Ω•ππÕ´‡∏ÅYÖπ∏Å≠Ö∏Å•ππï°Ω±ëîÅµ•≠…ΩΩ…ùÖπ•Õµï»(°â±Öπ–ÅÖππï–ÅçÖπ—°ÖµΩïâÑ§ÅÕΩ¥Å≠Ö∏ÅÕï——îÅÕïúÅôÖÕ–Å’πëï»Å±•πÕï∏ÅΩúÅôΩÀï…ÕÖ≠îÅÖ±ŸΩ…±•ùî∞)ŸÖπÕ≠ï±•úÅâï°Öπë±ïâÖ…îÉ·Âï•πôï≠Õ©Ωπï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!Ÿ•ÃÅ±•πÕïπîÅâ±•»Å€ï—îΩ†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘ÖùÕ±•πÕï»ËΩÕ—…Ωπú¯Å≠ÖÕ–Åëï¥ÅΩúÅÕï—–Å•π∏Åï–ÅπÂ—–∞Å…ïπ–Å¡Ö»Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘©ïπâ…’≠âÖ…îÅ±•πÕï»ËΩÕ—…Ωπú¯Å…ïπù´·»ÅΩúÅëïÕ•πô•Õï»Åëï¥Åù…’πë•úÅµïêÅ±•πÕï€ôÕ≠î(ÄÅõ·»ÅëîÅâ…’≠ïÃÅ•ù©ï∏ÉäLÅÕ≠Â±∞Åëï¥ÅÖ±ë…§ÅâÖ…îÅµïêÅŸÖπ∏Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘M≠Ö∞Åë‘ÅÕ€·µµîÅΩúÉ·πÕ≠ï»Å≠±Ö…–ÅÕÂ∏Å§ÅŸÖππï–∞Åï»Å—ï——Õ•——ïπëîÅÕ€·µµïâ…•±±ï»Åï–Å—…Âùùï…î)Ö±—ï…πÖ—•ÿÅïπ∏ÉîÅâï°Ω±ëîÅ≠Ωπ—Ö≠—±•πÕïπîÅ§∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘%õ·±ùîÄÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩ±•ŸÕÕ—•∞ΩïùïπΩµÕΩ…úΩ≠Ωπ—Ö≠—±•πÕï»µΩúµŸÖπ∏àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9Ω…Õ¨Å!ï±Õï•πôΩ…µÖ—•≠¨Ä°9!$§ΩÑ¯∞ÅµïêÅ°ïπŸ•Õπ•πúÅ—•∞ÅΩ±≠ï°ï±Õï•πÕ—•—’——ï–∞Åï»ÅÖ≠Öπ—Ö∑·âîµ•πôï≠Õ©Ω∏Åï∏ÅÖπï…≠©ïπ–ÅΩúÅÖ±ŸΩ…±•úÅ…•Õ•≠ºÅŸïêÅ≠Ωπ—Ö≠—±•πÕïâ…’¨Å§ÅŸÖπ∏ËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩπ°§ππºΩ±•ŸÕÕ—•∞ΩïùïπΩµÕΩ…úΩ≠Ωπ—Ö≠—±•πÕï»µΩúµŸÖπ∏àÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘-ï…Ö—•—–Åï»Åï∏ÅÖ±ŸΩ…±•úÉ·Âï•πôï≠Õ©Ω∏ÅÕΩ¥Å§Å°ΩŸïëÕÖ¨ÅÕïÃÅ°ΩÃÅâ…’≠ï…îÅÖÿÅÖ±±îÅ—Â¡ï»Å≠Ωπ—Ö≠—±•πÕï»∏ÅQ•±Õ—Öπëï∏Åï»ÅΩô—îÅÕµï…—ïô’±∞ÅΩúÅŸÖπÕ≠ï±•úÉîÅâï°Öπë±î∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩ±•ŸÕÕ—•∞ΩïùïπΩµÕΩ…úΩ≠Ωπ—Ö≠—±•πÕï»µΩúµŸÖπ∏àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9!$∞Å-Ωπ—Ö≠—±•πÕï»ÅΩúÅŸÖπ∏ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅë’Õ©îÅµïêÅ≠Ωπ—Ö≠—±•πÕïπîÅ√î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâï–ÅÖπâïôÖ±ïÃÉîÅ’ππüîÅëï–∏ÅYÖπ∏Å≠Ö∏Å•ππï°Ω±ëîÅµ•≠…ΩΩ…ùÖπ•Õµï»ÅÕΩ¥Å≠Ö∏ÅÕï——îÅÕïúÅôÖÕ–Å’πëï»Å±•πÕï∏ÅΩúÅù§ÅÖ±ŸΩ…±•ùîÉ·Âï•πôï≠Õ©Ωπï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅã·»Å©ïúÅù´·…îÅ°Ÿ•ÃÅ±•πÕïπîÅâ±•»Å€ï—î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâÖùÕ±•πÕï»Åã·»Å≠ÖÕ—ïÃÅΩúÅâÂ——ïÃÅµïêÅï–ÅπÂ—–Å¡Ö»∏Å©ïπâ…’≠âÖ…îÅ±•πÕï»Åã·»Å…ïπù´·…ïÃÅΩúÅëïÕ•πô•Õï…ïÃÅù…’πë•úÅµïêÅ±•πÕï€ôÕ≠îÅõ·»ÅëîÅâ…’≠ïÃÅ•ù©ï∏ÉäLÅÕ≠Â±∞Åëï¥ÅÖ±ë…§ÅâÖ…îÅµïêÅŸÖπ∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µΩúµ—Ω……îµΩÂπîàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ωπ—Ö≠—±•πÕï»ÅΩúÅ”·……îÉ·Âπîà∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»Å≠Ωπ—Ö≠—±•πÕï»Å≠Ö∏Åù§Å”·……îÉ·Âπî∞ÅΩúÅ°ŸÑÅÕΩ¥Å≠Ö∏Å°©ï±¡îÉäLÅô…ÑÅ±•πÕïŸÖ±úÅ—•∞É·ÂïëÀï¡ï»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘S·……îÉ·ÂπîÅï»Åï∏ÅÖÿÅëîÅŸÖπ±•ùÕ—îÅ¡±ÖùïπîÅâ±Öπ–Å≠Ωπ—Ö≠—±•πÕïâ…’≠ï…î∏Å1•πÕï∏Å≠Ö∏Å√ïŸ•…≠î)°ŸΩ…ëÖ∏Å”ï…ïô•±µï∏ÅôΩ…ëï±ï»ÅÕïúÅΩŸï»É·Âï–∞ÅΩúÅ±ÖπùîÅëÖùï»ÅôΩ…Ö∏ÅÕ≠©ï…¥Ä°ëï»ÅµÖ∏Åâ±’π≠ï»)Õ©ï±ëπï…î§ÅôΩ…Õ—ï…≠ï»ÅΩô—îÅ¡…Ωâ±ïµï–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸÑÅ≠Ö∏Å°©ï±¡îΩ†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘5Ωëï…πîÅÕ•±•≠Ωπ°Âë…Ωùï∞µ±•πÕï»Åï»ÅΩô—îÅµï»Å≠ΩµôΩ…—Öâ±îÅŸïêÅ”·……îÉ·ÂπîÅïπ∏Åï±ë…î(ÄÅµÖ—ï…•Ö±ï»ÉäLÅÕîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩ≠Ωπ—Ö≠—±•πÕïπÃµµÖ—ï…•Ö±îºà˘ù’•ëîÅΩ¥Å±•πÕïµÖ—ï…•Ö±ï»ΩÑ¯Ω±§¯(ÄÄÒ±§˘	…’¨Å≠’∏É·ÂïëÀï¡ï»Ωô’≠—ï…ëÀï¡ï»Åâï…ïùπï–ÅôΩ»Åâ…’¨ÅÕÖµµï∏ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»∞ÅÕΩ¥(ÄÄÒÑÅ°…ïòÙàΩΩÂïë…Ö¡ï»ΩÕÂÕ—ÖπîΩÕÂÕ—Öπîµ’±—…Ñ¥ƒ¿µµ∞ºà˘MÂÕ—ÖπîÅU±—…ÑΩÑ¯ÉäLÅ•≠≠îÅÖ±±î(ÄÉ·ÂïëÀï¡ï»Åï»Å—…ÂùùîÉîÅâ…’≠îÅµïêÅ±•πÕï∏Å§Ω±§¯(ÄÄÒ±§˘-Ω…—ï…îÅâ…’≠Õ—•êÅïπ≠ï±—îÅëÖùï»∞ÅµïêÅâïŸ•ÕÕ—îÅ¡Ö’Õï»Åô…ÑÅ±•πÕï»Ω±§¯(ÄÄÒ±§˘!’Õ¨ÉîÅâ±’π≠îÅâïŸ•ÕÕ–ÅΩô—ï…îÅŸïêÅ±ïπù…îÅÕ≠©ï…∑·≠—ï»Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘YïëŸÖ…ï»Å¡±Öùïπî∞Å≠Ö∏Åëï–Å—ÂëîÅ√îÅôï•∞Å±•πÕï—Â¡îÅï±±ï»Å¡ÖÕÕôΩ…¥ÉäLÅ—ÑÅëï–ÅΩ¡¿Åµïê)Ω¡—•≠ï…ï∏Åë•∏∏ÅY§ÅÕÖµµïπ±•ùπï»ÅΩùœîÅ¡…•Õï»Å√îÄÒÑÅ°…ïòÙàΩΩÂïë…Ö¡ï»ºà˚·ÂïëÀï¡ï»ΩÑ¯Åô…Ñ)ô±ï…îÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åâ±•»É·ÂπïπîÅ”·……îÅÖÿÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ1•πÕï∏Å≠Ö∏Å√ïŸ•…≠îÅ°ŸΩ…ëÖ∏Å”ï…ïô•±µï∏ÅôΩ…ëï±ï»ÅÕïúÅΩŸï»É·Âï–∞ÅΩúÅ…ïë’Õï…–Åâ±’π≠ïô…ï≠ŸïπÃÅŸïêÅÕ≠©ï…µâ…’¨ÅôΩ…Õ—ï…≠ï»ÅΩô—îÅ¡…Ωâ±ïµï–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅâ…’≠îÅŸÖπ±•ùîÉ·ÂïëÀï¡ï»ÅµïêÅ±•πÕïπîÅ§¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%≠≠îÅÖ±±îÉ·ÂïëÀï¡ï»Åï»Å—…ÂùùîÉîÅâ…’≠îÅµïêÅ≠Ωπ—Ö≠—±•πÕï»Å§É·Âï–∏Å	…’¨Å≠’∏Åô’≠—ï…ëÀï¡ï»ÅÕΩ¥Åï»ÅÕ¡ïÕ•ô•≠–Åâï…ïùπï–ÅôΩ»Åâ…’¨ÅÕÖµµï∏ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâM±•¨Å±ïÕï»Åë‘Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏Åë•∏à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ∏Å•±±’Õ—…ï…–ÅôΩ…≠±Ö…•πúÅÖÿÅôΩ…≠Ω…—ï±ÕïπîÅ√îÅï∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–ÉäLÅA]H∞Å	∞Å%∞Åe0∞Åa%LÅΩúÅ∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘-Ωπ—Ö≠—±•πÕïïÕ≠ï∏Åï±±ï»Å…ïÕï¡—ï∏Åë•∏ÅŸ•Õï»Åù©ï…πîÅô±ï…îÅ—Ö±∞ÅΩúÅôΩ…≠Ω…—ï±Õï»∏ÅUπëï»Åï»)ï–Åï≠Õïµ¡ï∞ÉäLÅ—…Â≠¨Å√îÅï∏ÅŸï…ë§ÅôΩ»ÉîÅõîÅëï∏ÅôΩ…≠±Ö…–ËΩ¿¯((ÒÕ—Â±î¯(π…‡µù…•êÅÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†Ã∞Ä≈ô»§ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ…ù•∏ËÄ»¡¡‡Ä¿ÏÅÙ(π…‡µçï±∞ÅÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡Ä·¡‡ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅÙ(π…‡µçï±∞È°ΩŸï»ÅÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅÙ(π…‡µçï±∞µ±Öâï∞ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‹……ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿—ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅÙ(π…‡µçï±∞µŸÖ±’îÅÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄƒ∏ƒ’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅµÖ…ù•∏µ—Ω¿ËÄ…¡‡ÏÅÙ)µïë•ÑÄ°µÖ‡µ›•ë—†ËÄ–‡¡¡‡§ÅÏÄπ…‡µù…•êÅÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†»∞Ä≈ô»§ÏÅÙÅÙ(ΩÕ—Â±î¯(Òë•ÿÅç±ÖÕÃÙâ…‡µù…•êà¯(ÄÄÒÑÅç±ÖÕÃÙâ…‡µçï±∞àÅ°…ïòÙàΩù’•ëîΩ¡›»µÕ¡†µôΩ…≠±Ö…–ºà¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µ±Öâï∞à˘A]HΩë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µŸÖ±’îà¯¥»∏‘¿Ωë•ÿ¯ΩÑ¯(ÄÄÒÑÅç±ÖÕÃÙâ…‡µçï±∞àÅ°…ïòÙàΩù’•ëîΩâåµôΩ…≠±Ö…–ºà¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µ±Öâï∞à˘	Ωë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µŸÖ±’îà¯‡∏ÿΩë•ÿ¯ΩÑ¯(ÄÄÒÑÅç±ÖÕÃÙâ…‡µçï±∞àÅ°…ïòÙàΩù’•ëîΩë•ÑµôΩ…≠±Ö…–ºà¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µ±Öâï∞à˘%Ωë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µŸÖ±’îà¯ƒ–∏»Ωë•ÿ¯ΩÑ¯(ÄÄÒÑÅç±ÖÕÃÙâ…‡µçï±∞àÅ°…ïòÙàΩù’•ëîΩçÂ∞µôΩ…≠±Ö…–ºà¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µ±Öâï∞à˘e0Ωë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µŸÖ±’îà¯¥ƒ∏»‘Ωë•ÿ¯ΩÑ¯(ÄÄÒÑÅç±ÖÕÃÙâ…‡µçï±∞àÅ°…ïòÙàΩù’•ëîΩÖ·•ÃµôΩ…≠±Ö…–ºà¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µ±Öâï∞à˘a%LΩë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µŸÖ±’îà¯‰¿Ωë•ÿ¯ΩÑ¯(ÄÄÒÑÅç±ÖÕÃÙâ…‡µçï±∞àÅ°…ïòÙàΩù’•ëîΩÖëêµôΩ…≠±Ö…–ºà¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µ±Öâï∞à˘Ωë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ…‡µçï±∞µŸÖ±’îà¯¨ƒ∏‘¿Ωë•ÿ¯ΩÑ¯(Ωë•ÿ¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‡……ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿Ë¥·¡‡Ïà˘≠Õïµ¡ï±ï–Åï»Å≠’∏Å•±±’Õ—…Ö—•Ÿ–∞Å•≠≠îÅï∏Å…ïï±∞Å…ïÕï¡–∏Å%≠≠îÅÖ±±îÅ±•πÕï»Å°Ö»ÅÖ±±î)Ÿï…ë•ïπîËÅe0ÅΩúÅa%LÅù©ï±ëï»Å≠’∏Å—Ω…•Õ≠îÅ±•πÕï»Ä°ÖÕ—•ùµÖ—•Õµî§∞ÅÅù©ï±ëï»Å≠’∏)µ’±—•ôΩ≠Ö±îÅ±•πÕï»Ä°Ö±ëï…ÕÕÂ∏§∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘-Ω…–ÅΩ¥Å°Ÿï»ÅŸï…ë§Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‰Ïà¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘A]HΩMA ΩÕ—…Ωπú¯ÉäLÅù…’ππÕ—Â…≠ï∏∞Å≠Ω……•ùï…ï»Åªô»¥Åï±±ï»Å±ÖπùÕÂπ—°ï–Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘	ΩÕ—…Ωπú¯ÉäLÅâÖÕîµ≠’…Ÿî∞Å°ŸΩ»Å≠…’¥Å±•πÕï∏Åï»Ä°∑îÅ¡ÖÕÕîÅ°Ω…π°•ππï∏Åë•∏§Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘%ΩÕ—…Ωπú¯ÉäLÅë•Öµï—ï»∞Å±•πÕïπÃÅâ…ïëëîÅô…ÑÅ≠Öπ–Å—•∞Å≠Öπ–Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘e0ΩÕ—…Ωπú¯ÉäLÅï≠Õ—…ÑÅÕ—Â…≠îÅÕΩ¥Å≠Ω……•ùï…ï»ÅÖÕ—•ùµÖ—•ÕµîÄ°≠’∏Å—Ω…•Õ≠îÅ±•πÕï»§Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘a%LΩÕ—…Ωπú¯ÉäLÅ…ï—π•πùï∏ÅÖÕ—•ùµÖ—•Õµîµ≠Ω……ï≠Õ©Ωπï∏ÅÕ≠Ö∞Å±•ùùîÅ§Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘ΩÕ—…Ωπú¯ÉäLÅ—•±±ïùùÕÕ—Â…≠îÅôΩ»Åªô…ÕÂ∏ÅŸïêÅÖ±ëï…ÕÕÂ∏Ä°≠’∏Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»§Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘±±îÅŸï…ë•ïπîÅôÖÕ—Õï——ïÃÅÖÿÅΩ¡—•≠ï…ï∏Åë•∏Å’πëï»ÅÕÂπÕ’πëï…œ·≠ï±Õï∏∞ÅΩúÅÕ≠Ö∞ÅÖ±±—•ê)Õ—ïµµîÅª·ÂÖ≠—•úÅµïêÅëï–Åë‘ÅâïÕ—•±±ï»ÉäLÅÕîÅΩùœîÄÒÑÅ°…ïòÙàΩù’•ëîΩÕÖµµîµÕ—Â…≠îµâ…•±±ï»µΩúµ±•πÕï»ºà˘°ŸΩ…ôΩ»)ï∏Åâ…•±±ï…ïÕï¡–Å•≠≠îÅï»Åëï–ÅÕÖµµîÅÕΩ¥Åï∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–ΩÑ¯∏ÅMîÅòπï≠Ã∏)Õ¡ïÕ•ô•≠ÖÕ©ΩπÕ—Öâï±±ï∏Å√îÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰)Õ•∏Å¡…Ωë’≠—Õ•ëîΩÑ¯ÅôΩ»ÉîÅÕîÅ°ŸΩ…ëÖ∏Åë•ÕÕîÅŸï…ë•ïπîÅôÖ≠—•Õ¨ÅΩ¡¡ù•ÃÅ√îÅï∏Åï≠—îÅ±•πÕî∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ7îÅ≠Ωπ—Ö≠—±•πÕïπîÅµ•πîÅ°ÑÅÖ±±îÅë•ÕÕîÅŸï…ë•ïπî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏Åe0ÅΩúÅa%LÅù©ï±ëï»Å≠’∏Å—Ω…•Õ≠îÅ±•πÕï»ÅôΩ»ÅÖÕ—•ùµÖ—•Õµî∞ÅΩúÅÅù©ï±ëï»Å≠’∏Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»ÅôΩ»ÅÖ±ëï…ÕÕÂ∏∏ÅîÅô±ïÕ—îÅ—…ïπùï»ÅâÖ…îÅA]HΩMA ∞Å	ÅΩúÅ%∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»Åô•ππï»Å©ïúÅë•ÕÕîÅŸï…ë•ïπîÅôΩ»Åµ•πîÅïùπîÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâîÅÕ”ï»Å√îÅ…ïÕï¡—ï∏Åë•∏Åô…ÑÅÕÂπÕ’πëï…œ·≠ï±Õï∏Å°ΩÃÅΩ¡—•≠ï»∞ÅΩúÅ√îÅïÕ≠ï∏Å—•∞Å±•πÕïπîÅë‘ÅÖ±±ï…ïëîÅâ…’≠ï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄââåµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅâï—Â»Å	Å√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ	Ä°âÖÕîµ≠’…Ÿî§Åï»Å≠…’µπ•πùï∏Å√îÅâÖ≠Õ•ëï∏ÅÖÿÅ≠Ωπ—Ö≠—±•πÕï∏∞ÅΩúÅ∑îÅ¡ÖÕÕîÅôΩ…µï∏Å√îÅë•∏Åïùï∏Å°Ω…π°•ππî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘	ÅÕ”ï»ÅôΩ»ÅâÖÕîµ≠’…ŸîÉäLÅ≠…’µπ•πùÕ…Öë•’Õï∏Å√îÅâÖ≠Õ•ëï∏ÅÖÿÅ±•πÕï∏∞Å∑ï±–Å§Åµ•±±•µï—ï»(°—Â¡•Õ¨Åµï±±Ω¥Ä‡∞ÃÅΩúÄ‰∞¿ÅôΩ»ÅµÂ≠îÅ±•πÕï»§∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘	Å∑îÅ¡ÖÕÕîÅ≠…’µπ•πùï∏Å√îÅë•∏Åïùï∏Å°Ω…π°•ππî∏Å∏ÅôΩ»Åô±Ö–Å	Åù´·»ÅÖ–Å±•πÕï∏ÅÕ•——ï»)≥·Õ–ÅΩúÅâïŸïùï»ÅÕïúÅôΩ»ÅµÂîÅ√îÉ·Âï–∏Å∏ÅôΩ»Åâ…Öπ–Ä°Õ—…Ö¥§Å	Åù´·»ÅÖ–Å±•πÕï∏ÅÕ•——ï»ÅôΩ»)—ï—–∞ÅπΩîÅÕΩ¥Å≠Ö∏Åù§Å’âï°ÖúÅï±±ï»Å…ïë’Õï…–ÅΩ≠ÕÂùïπ—•±õ·…Õï∞Å—•∞Å°Ω…π°•ππï∏∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘	ÅôÖÕ—Õï——ïÃÅÖÿÅΩ¡—•≠ï…ï∏Åë•∏Å’πëï»ÅÕÂπÕ’πëï…œ·≠ï±Õï∏Ω±•πÕï—•±¡ÖÕπ•πùï∏∞ÅΩúÅÕ≠Ö∞)Ö±±—•êÅÕ—ïµµîÅª·ÂÖ≠—•úÅµïêÅëï–ÅÕΩ¥ÅÕ”ï»Å√îÅ…ïÕï¡—ï∏Åë•∏ÉäLÅÕîÅΩùœîÅ€ï»(ÒÑÅ°…ïòÙàΩù’•ëîΩôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ºà˘ΩŸï…Õ•≠–ÅΩŸï»Å°ï±îÅ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ΩÑ¯∏)–Åï≠Õïµ¡ï∞Å√îÅï∏Å±•πÕîÅµïêÅ	Ä‡∞ÿÅµ¥Åï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅâï—Â»Å	Å√îÅï∏Å≠Ωπ—Ö≠—±•πÕïïÕ≠î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ	Ä°âÖÕîµ≠’…Ÿî§Åï»Å≠…’µπ•πùÕ…Öë•’Õï∏Å√îÅâÖ≠Õ•ëï∏ÅÖÿÅ±•πÕï∏Å§Åµ•±±•µï—ï»∞ÅΩúÅ∑îÅ¡ÖÕÕîÅ≠…’µπ•πùï∏Å√îÅë•∏Åïùï∏Å°Ω…π°•ππî∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅÕ≠©ï»Å°Ÿ•ÃÅ	µŸï…ë•ï∏Åï»Åôï•∞¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ»Åô±Ö–Å	Åù´·»ÅÖ–Å±•πÕï∏ÅÕ•——ï»Å≥·Õ–ÅΩúÅâïŸïùï»ÅÕïúÅôΩ»ÅµÂî∏ÅΩ»Åâ…Öπ–Å	Åù´·»ÅÖ–Å±•πÕï∏ÅÕ•——ï»ÅôΩ»ÅÕ—…Öµ–∞ÅπΩîÅÕΩ¥Å≠Ö∏Åù§Å’âï°ÖúÅï±±ï»Å…ïë’Õï…–ÅΩ≠ÕÂùïπ—•±õ·…Õï∞∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâë•ÑµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅâï—Â»Å%Å√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ%Ä°ë•Öµï—ï»§Åï»Å≠Ωπ—Ö≠—±•πÕïπÃÅ—Ω—Ö±îÅâ…ïëëîÅô…ÑÅ≠Öπ–Å—•∞Å≠Öπ–∞ÅΩúÅ√ïŸ•…≠ï»Å°ŸΩ…ëÖ∏Å±•πÕï∏ÅÕïπ—…ï…ï»ÅÕïúÅ√îÉ·Âï–∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘%ÅÕ”ï»ÅôΩ»Åë•Öµï—ï»ÉäLÅ±•πÕïπÃÅ—Ω—Ö±îÅâ…ïëëîÅô…ÑÅ≠Öπ–Å—•∞Å≠Öπ–∞Å∑ï±–Å§Åµ•±±•µï—ï»(°—Â¡•Õ¨Åµï±±Ω¥ÄƒÃ∞‘ÅΩúÄƒ–∞‘ÅôΩ»ÅµÂ≠îÅ±•πÕï»§∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘ï•∞Åë•Öµï—ï»Å√ïŸ•…≠ï»Å°ŸΩ…ëÖ∏Å±•πÕï∏ÅÕïπ—…ï…ï»ÅÕïúÅ√îÉ·Âï–ÅΩúÅ°ŸΩ»ÅµÂîÅÖÿ)°Ω…π°•ππï∏Åëï∏Åëï≠≠ï»∏ÅMÖµµï∏ÅµïêÅ	Ä°âÖÕîµ≠’…Ÿî§ÅÖŸù´·»Å%Å°ŸΩ»ÅùΩë–Å±•πÕï∏Å¡ÖÕÕï»+·ÂïôΩ…µï∏Åë•∏∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘%ÅôÖÕ—Õï——ïÃÅÖÿÅΩ¡—•≠ï…ï∏Åë•∏Å’πëï»ÅÕÂπÕ’πëï…œ·≠ï±Õï∏∞ÅΩúÅÕ≠Ö∞ÅÖ±±—•êÅÕ—ïµµî)ª·ÂÖ≠—•úÅµïêÅ…ïÕï¡—ï∏Åë•∏ÉäLÅÕîÅΩùœîÅ€ï»(ÒÑÅ°…ïòÙàΩù’•ëîΩôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ºà˘ΩŸï…Õ•≠–ÅΩŸï»Å°ï±îÅ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ΩÑ¯∏)–Åï≠Õïµ¡ï∞Å√îÅï∏Å±•πÕîÅµïêÅ%Äƒ–∞¿Åµ¥Åï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅâï—Â»Å%Å√îÅï∏Å≠Ωπ—Ö≠—±•πÕïïÕ≠î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%Ä°ë•Öµï—ï»§Åï»Å±•πÕïπÃÅ—Ω—Ö±îÅâ…ïëëîÅô…ÑÅ≠Öπ–Å—•∞Å≠Öπ–Å§Åµ•±±•µï—ï»∞ÅÕΩ¥Å√ïŸ•…≠ï»Å°ŸΩ…ëÖ∏Å±•πÕï∏ÅÕïπ—…ï…ï»ÅÕïúÅΩúÅ°ŸΩ»ÅµÂîÅÖÿÉ·Âï–Åëï∏Åëï≠≠ï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅŸï±ùîÅï∏ÅÖππï∏Å%Åïπ∏Åëï–ÅÕΩ¥ÅÕ”ï»Å√îÅ…ïÕï¡—ï∏Åµ•∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏Å%Åï»ÅôÖÕ—ÕÖ—–ÅÖÿÅΩ¡—•≠ï…ï∏Åë•∏Å’–Åô…ÑÅë•∏Åïùï∏É·ÂïôΩ…¥∞ÅΩúÅÕ≠Ö∞ÅÖ±±—•êÅÕ—ïµµîÅª·ÂÖ≠—•úÅµïêÅ…ïÕï¡—ï∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡›»µÕ¡†µôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅâï—Â»ÅA]HÅΩúÅMA Å√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâA]HÄ°ï±±ï»ÅMA §Åï»Åù…’ππÕ—Â…≠ï∏Å√îÅï∏Å≠Ωπ—Ö≠—±•πÕî∞ÅÕΩ¥Å≠Ω……•ùï…ï»Åªô»¥Åï±±ï»Å±ÖπùÕÂπ—°ï–∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘A]HÄ°¡Ω›ï»§ÅΩúÅMA Ä°Õõô…î§Åï»Å—ºÅπÖŸ∏Å√îÅëï–ÅÕÖµµîËÅù…’ππÕ—Â…≠ï∏Å—•∞Å±•πÕï∏∞ÅΩ¡¡ù•—–Å§)ë•Ω¡—…•ï»Ä°§∏ÅU±•≠îÅ¡…Ωë’Õïπ—ï»Åâ…’≠ï»Å’±•¨ÅôΩ…≠Ω…—ï±ÕîÅ√îÅ¡Ö≠π•πùï∏∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘–ÄÒÕ—…Ωπú˘πïùÖ—•Ÿ–Å—Ö±∞ΩÕ—…Ωπú¯Ä°òπï≠Ã∏Ä¥»∞‘¿§Åâï—Â»ÅÖ–Å±•πÕï∏Å≠Ω……•ùï…ï»)ªô…ÕÂπ—°ï–∏Å–ÄÒÕ—…Ωπú˘¡ΩÕ•—•Ÿ–Å—Ö±∞ΩÕ—…Ωπú¯Ä°òπï≠Ã∏Ä¨ƒ∞‘¿§Åâï—Â»ÅÖ–Åëï∏Å≠Ω……•ùï…ï»)±ÖπùÕÂπ—°ï–∏Å)ºÅ£·Âï…îÅ—Ö±∞∞Å©ºÅÕ—ï…≠ï…îÅ≠Ω……ï≠Õ©Ω∏∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘A]HΩMA ÅôÖÕ—Õï——ïÃÅÖÿÅΩ¡—•≠ï…ï∏Åë•∏Å’πëï»ÅÕÂπÕ’πëï…œ·≠ï±Õï∏ÉäLÅÕîÅΩùœîÅ€ï»(ÒÑÅ°…ïòÙàΩù’•ëîΩôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ºà˘ΩŸï…Õ•≠–ÅΩŸï»Å°ï±îÅ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ΩÑ¯∏)M—Â…≠ïΩµÀïëï–Åï∏Å±•πÕîÅëï≠≠ï»ÅÕ”ï»ÅΩ¡¡ù•—–Å’πëï»ÅÕ¡ïÕ•ô•≠ÖÕ©Ωπï»Å√îÅ°Ÿï»Å¡…Ωë’≠—Õ•ëî∞)òπï≠Ã∏Å°ΩÃÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»ÅôΩ…Õ≠©ï±±ï∏Å√îÅA]HÅΩúÅMA ¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%πùï∏ÉäLÅëï–Åï»Å—ºÅ’±•≠îÅπÖŸ∏ÅôΩ»Åëï–ÅÕÖµµîËÅ±•πÕïπÃÅù…’ππÕ—Â…≠îÅ§Åë•Ω¡—…•ï»∏ÅU±•≠îÅ¡…Ωë’Õïπ—ï»Åâ…’≠ï»Å’±•¨ÅôΩ…≠Ω…—ï±ÕîÅ√îÅ¡Ö≠π•πùï∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅâï—Â»Åï–ÅπïùÖ—•Ÿ–Å—Ö±∞Å√îÅ≠Ωπ—Ö≠—±•πÕïÕ—Â…≠ï∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ–ÅπïùÖ—•Ÿ–Å—Ö±∞Åâï—Â»ÅÖ–Å±•πÕï∏Å≠Ω……•ùï…ï»Åªô…ÕÂπ—°ï–∏Å–Å¡ΩÕ•—•Ÿ–Å—Ö±∞Åâï—Â»ÅÖ–Åëï∏Å≠Ω……•ùï…ï»Å±ÖπùÕÂπ—°ï–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâçÂ∞µôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅâï—Â»Åe0Å√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâe0Ä°ÕÂ±•πëï»§ÅÖπù•»ÅÕ—Â…≠ï∏Å√îÅÖÕ—•ùµÖ—•Õµîµ≠Ω……ï≠Õ©Ωπï∏Å§Åï∏Å—Ω…•Õ¨Å≠Ωπ—Ö≠—±•πÕî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘e0ÅÕ”ï»ÅôΩ»ÅÕÂ±•πëï»∞ÅΩúÅÖπù•»Å°ŸΩ»ÅµÂîÅï≠Õ—…ÑÅÕ—Â…≠îÅÕΩ¥Å—…ïπùÃÅôΩ»ÉîÅ≠Ω……•ùï…î)ÖÕ—•ùµÖ—•ÕµîÄ°Õ≠©ïÿÅ°Ω…π°•ππî§∏ÅYï…ë•ï∏Åù©ï±ëï»Å≠’∏Å—Ω…•Õ≠îÅ±•πÕï»ÉäLÅ°Ö»Åë‘Å•≠≠î)ÖÕ—•ùµÖ—•Õµî∞Å°Ö»Å…ïÕï¡—ï∏Åë•∏ÅπΩ…µÖ±–Å•πùï∏Åe0µŸï…ë§∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘e0Åâ…’≠ïÃÅÖ±±—•êÅÕÖµµï∏ÅµïêÅï∏ÄÒÑÅ°…ïòÙàΩù’•ëîΩÖ·•ÃµôΩ…≠±Ö…–ºà˘a%LµŸï…ë§ΩÑ¯∞)ÕΩ¥ÅÖπù•»Å§Å°Ÿ•±≠ï∏Å…ï—π•πúÅ≠Ω……ï≠Õ©Ωπï∏ÅÕ≠Ö∞Å±•ùùî∏ÅîÅ—ºÅ°ïπùï»ÅÕÖµµï∏ÅΩúÅ∑îÅâïùùî)Õ—ïµµîÅôΩ»ÅÖ–Å±•πÕï∏ÅÕ≠Ö∞Åô’πùï…îÅ…•≠—•ú∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩ≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•Õµîºà˘ù’•ëîÅΩ¥Å—Ω…•Õ≠îÅ±•πÕï»ÅΩú)ÖÕ—•ùµÖ—•ÕµîΩÑ¯ÅôΩ»Åµï»ÅΩ¥Å°ŸΩ…ëÖ∏Åëï——îÅô’πùï…ï»Å§Å¡…Ö≠Õ•Ã∞Åï±±ï»ÅÕÖµµïπ±•ù∏Å¡…•Õï»Å√î)ï∏Å—Ω…•Õ¨Å±•πÕîÅÕΩ¥ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îΩÖç’Ÿ’îµΩÖÕÂÃµôΩ»µÖÕ—•ùµÖ—•Õ¥¥ÿµ¡Öç¨ºà˘ç’Ÿ’î)=ÖÕÂÃÅôΩ»ÅÕ—•ùµÖ—•Õ¥ΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅâï—Â»Åe0Å√îÅï∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâe0Ä°ÕÂ±•πëï»§ÅÖπù•»Å°ŸΩ»ÅµÂîÅï≠Õ—…ÑÅÕ—Â…≠îÅÕΩ¥Å—…ïπùÃÅôΩ»ÉîÅ≠Ω……•ùï…îÅÖÕ—•ùµÖ—•Õµî∏ÅYï…ë•ï∏Åù©ï±ëï»Å≠’∏Å—Ω…•Õ≠îÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅ°ÑÅï∏Åe0µŸï…ë§Å’—ï∏Åa%L¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∞Åe0ÅΩúÅa%LÅâ…’≠ïÃÅÖ±±—•êÅÕÖµµï∏ÉäLÅa%LÅÖπù•»Å…ï—π•πùï∏Åe0µ≠Ω……ï≠Õ©Ωπï∏ÅÕ≠Ö∞Å±•ùùîÅ§∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâÖ·•ÃµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅâï—Â»Åa%LÅ√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâa%LÅÖπù•»Å§Å°Ÿ•±≠ï∏Å…ï—π•πúÅÖÕ—•ùµÖ—•Õµîµ≠Ω……ï≠Õ©Ωπï∏Å§Åï∏Å—Ω…•Õ¨Å≠Ωπ—Ö≠—±•πÕîÅÕ≠Ö∞Å±•ùùî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘a%LÄ°ΩùœîÅÕ≠…ïŸï–Å`§ÅÖπù•»Å§Å°Ÿ•±≠ï∏Å…ï—π•πú∞ÅΩ¡¡ù•—–Å§Åù…Öëï»Åô…ÑÄ¿Å—•∞Äƒ‡¿∞)ÖÕ—•ùµÖ—•Õµîµ≠Ω……ï≠Õ©Ωπï∏Å§Å±•πÕï∏ÅÕ≠Ö∞Å±•ùùî∏ÅYï…ë•ï∏Åâ…’≠ïÃÅÖ±±—•êÅÕÖµµï∏Åµïê(ÒÑÅ°…ïòÙàΩù’•ëîΩçÂ∞µôΩ…≠±Ö…–ºà˘e0ΩÑ¯∞ÅΩúÅù©ï±ëï»Å≠’∏Å—Ω…•Õ≠îÅ±•πÕï»∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘QΩ…•Õ≠îÅ±•πÕï»Åï»ÅôΩ…µï–ÅôΩ»ÉîÅ±•ùùîÅÕ—Öâ•±–Å§É•∏ÅâïÕ—ïµ–Å…ï—π•πúÅ√îÉ·Âï–Ä°§)µΩ—Õï—π•πúÅ—•∞ÅŸÖπ±•ùîÅ±•πÕï»∞ÅÕΩ¥Å≠Ö∏Å…Ω—ï…îÅô…•—–Å’—ï∏ÅÖ–Åëï–Åµï…≠ïÃ§∏Åa%LÅôΩ…—ï±±ï»)±•πÕï∏Åª·ÂÖ≠—•úÅ°Ÿ•±≠ï∏Å…ï—π•πúÅëï∏ÅÕ≠Ö∞ÅÕ”îÅ§ÅôΩ»ÅÖ–Å≠Ω……ï≠Õ©Ωπï∏ÅÕ≠Ö∞Åô’πùï…îÅ…•≠—•ú∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩ≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•Õµîºà˘ù’•ëîÅΩ¥Å—Ω…•Õ≠îÅ±•πÕï»ÅΩú)ÖÕ—•ùµÖ—•ÕµîΩÑ¯ÅôΩ»Åµï»ÅΩ¥Å°ŸΩ…ôΩ»Åëï——îÅï»Å±•—–Åµï»Å≠…ïŸïπëîÉîÅ—•±¡ÖÕÕîÅïπ∏ÅŸÖπ±•ùî)±•πÕï»∞Åï±±ï»ÅÕÖµµïπ±•ù∏Å¡…•Õï»Å√îÅï∏Å—Ω…•Õ¨Å±•πÕîÅÕΩ¥(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰µ—Ω…•å¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ÅQΩ…•åΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅâï—Â»Åa%LÅ√îÅï∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâa%LÅÖπù•»Å§Å°Ÿ•±≠ï∏Å…ï—π•πúÄ†√äLƒ‡¿Åù…Öëï»§ÅÖÕ—•ùµÖ—•Õµîµ≠Ω……ï≠Õ©Ωπï∏Å§Å±•πÕï∏ÅÕ≠Ö∞Å±•ùùî∏Å	…’≠ïÃÅÖ±±—•êÅÕÖµµï∏ÅµïêÅe0∞ÅΩúÅù©ï±ëï»Å≠’∏Å—Ω…•Õ≠îÅ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åï»Åa%LÅŸ•≠—•úÅôΩ»Å—Ω…•Õ≠îÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâQΩ…•Õ≠îÅ±•πÕï»Å∑îÅ±•ùùîÅÕ—Öâ•±–Å§Å…•≠—•úÅ…ï—π•πúÅ√îÉ·Âï–ÅôΩ»ÅÖ–Å≠Ω……ï≠Õ©Ωπï∏ÅÕ≠Ö∞Åô’πùï…î∏Åa%LÅôΩ…—ï±±ï»Å±•πÕï∏Åª·ÂÖ≠—•úÅ°Ÿ•±≠ï∏Å…ï—π•πúÅëï–Åï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâÖëêµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅâï—Â»ÅÅ√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâÅï»Å—•±±ïùùÕÕ—Â…≠ï∏ÅôΩ»Åªô…ÕÂ∏Å§Åï∏Åµ’±—•ôΩ≠Ö∞Å≠Ωπ—Ö≠—±•πÕî∞Åâ…’≠–Å—•∞ÉîÅ≠Ω……•ùï…îÅÖ±ëï…ÕÕÂ∏∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘Ä°Öëë•Õ©Ω∏Ω—•±±ïùú§Åï»Åï∏Åï≠Õ—…ÑÅÕ—Â…≠ïŸï…ë§ÅÕΩ¥Å±ïùùïÃÅ—•∞Åù…’ππÕ—Â…≠ï∏(†ÒÑÅ°…ïòÙàΩù’•ëîΩ¡›»µÕ¡†µôΩ…≠±Ö…–ºà˘A]HΩMA ΩÑ¯§ÅôΩ»ÉîÅ≠Ω……•ùï…îÅÖ±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§∏)Yï…ë•ï∏Åù©ï±ëï»Å≠’∏Åµ’±—•ôΩ≠Ö±îΩ¡…Ωù…ïÕÕ•ŸîÅ≠Ωπ—Ö≠—±•πÕï»∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘ÅΩ¡¡ù•ÃÅÖ±±—•êÅÕΩ¥Åï–Å¡ΩÕ•—•Ÿ–Å—Ö±∞Ä°òπï≠Ã∏Ä¨ƒ∞‘¿§∞ÅΩúÅÖπù•»Å°ŸΩ»ÅµÂîÅï≠Õ—…Ñ)Õ—Â…≠îÉ·Âï–Å—…ïπùï»ÅôΩ»ÉîÅÕîÅÕ≠Ö…¡–Å√îÅªô…–Å°Ω±ê∞Å§Å—•±±ïùúÅ—•∞Åù…’ππ≠Ω……ï≠Õ©Ωπï∏ÅôΩ»)±Öπù–Å°Ω±ê∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»ºà˘ù’•ëîÅΩ¥Åµ’±—•ôΩ≠Ö±îÅ≠Ωπ—Ö≠—±•πÕï»)ŸïêÅÖ±ëï…ÕÕÂ∏ΩÑ¯ÅôΩ»Åµï»ÅΩ¥Å°ŸΩ…ëÖ∏Åë•ÕÕîÅ±•πÕïπîÅô’πùï…ï»∞Åï±±ï»ÅÕÖµµïπ±•ù∏Å¡…•Õï»Å√îÅï∏)µ’±—•ôΩ≠Ö∞Å±•πÕîÅÕΩ¥(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îΩÖç’Ÿ’îµΩÖÕÂÃµµ’±—•ôΩçÖ∞¥ÿµ¡Öç¨ºà˘ç’Ÿ’îÅ=ÖÕÂÃÅ5’±—•ôΩçÖ∞ΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅâï—Â»ÅÅ√îÅï∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâÅï»Åï∏Åï≠Õ—…ÑÅÕ—Â…≠ïŸï…ë§ÅÕΩ¥Å±ïùùïÃÅ—•∞Åù…’ππÕ—Â…≠ï∏ÅôΩ»ÉîÅ≠Ω……•ùï…îÅÖ±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§∏Å©ï±ëï»Å≠’∏Åµ’±—•ôΩ≠Ö±îΩ¡…Ωù…ïÕÕ•ŸîÅ≠Ωπ—Ö≠—±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åï»ÅÅÖ±±—•êÅï–Å¡ΩÕ•—•Ÿ–Å—Ö±∞¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ…ë§Åëï–ÅÖπù•»Å°ŸΩ»ÅµÂîÅï≠Õ—…ÑÅ¡±’ÕÃµÕ—Â…≠îÉ·Âï–Å—…ïπùï»ÅôΩ»ÉîÅÕîÅÕ≠Ö…¡–Å√îÅªô…–Å°Ω±ê∞Å’ÖŸ°ïπù•úÅÖÿÅΩ¥Åù…’ππÕ—Â…≠ï∏Ä°A]HΩMA §Å§ÅÕïúÅÕï±ÿÅï»Å¡ΩÕ•—•ÿÅï±±ï»ÅπïùÖ—•ÿ∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ»µ±ïπùîµ≠Ö∏µµÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ»Å±ïπùîÅ≠Ö∏ÅµÖ∏Åâ…’≠îÅ≠Ωπ—Ö≠—±•πÕï»ÅΩ¥ÅëÖùï∏¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâIï—π•πùÕ±•π©ï»ÅôΩ»ÅëÖù±•úÅâ…’≠Õ—•êÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»∞ÅΩúÅ—ïù∏Å√îÅÖ–Åë‘Åã·»Å—ÑÅëï¥Å’–Å—•ë±•ùï…î∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘îÅô±ïÕ—îÅ”ï±ï»ÅµÂ≠îÅ≠Ωπ—Ö≠—±•πÕï»Å≠ΩµôΩ…—Öâï±–Å§Å…’πë–ÄƒÀäLƒ–Å—•µï»ÅÕÖµµïπ°ïπùïπëî∞Åµï∏)ëï∏Åª·ÂÖ≠—•ùîÅù…ïπÕï∏ÅÖŸ°ïπùï»ÅÖÿÅ±•πÕï—Â¡î∞ÅµÖ—ï…•Ö±îÅΩúÅ°ŸÑÅΩ¡—•≠ï…ï∏Åë•∏Å°Ö»ÅùΩë≠©ïπ–)ôΩ»ÅÖ≠≠’…Ö–Åë•πîÅ±•πÕï»ÉäLÅõ·±úÅÖ±±—•êÅëï∏ÅÖπâïôÖ±•πùï∏Åô…ïµôΩ»Åï–Åùïπï…ï±–Å—Ö±∞∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Qïù∏Å√îÅÖ–Åë‘Åã·»Å—ÑÅ’–Å±•πÕïπîÅ—•ë±•ùï…îΩ†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘S·……°ï–Åï±±ï»Å•……•—ÖÕ©Ω∏Ω±§¯(ÄÄÒ±§˘K·ë°ï–Ω±§¯(ÄÄÒ±§˘U≠±Ö…–ÅÕÂ∏Ω±§¯(ÄÄÒ±§˘ïπï…ï±–Å’âï°ÖúΩ±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘§Åù©ï…πîÉ·ÂπïπîÅ±•πÕïô…§Å—•êÅªï»Åë‘Å≠Ö∏∞ÅôΩ»Åï≠Õïµ¡ï∞ÅΩ¥Å≠Ÿï±ëï∏Å°©ïµµî∏ÅUÖπÕï—–)â…’≠Õ—•êÅù©ï±ëï»ÅÕÖµµîÅ…ïùï∞ËÅŸÖπ±•ùîÅ±•πÕï»Åï»Å•≠≠îÅµïπ–ÅôΩ»ÅÕÖµµïπ°ïπùïπëîÅâ…’¨Åì·ùπï–)…’πë–ÉäLÅÕîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩ≠Ö∏µµÖ∏µÕΩŸîµµïêµ≠Ωπ—Ö≠—±•πÕï»ºà˘ù’•ëîÅΩ¥ÉîÅÕΩŸîÅµïê)≠Ωπ—Ö≠—±•πÕï»ΩÑ¯∏Å	…’≠ï»Åë‘Åï∏ÅëÖùÕ±•πÕîÅÕΩ¥(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÕΩô±ïπÃΩÕΩô±ïπÃµëÖ•±‰µë•Õ¡ΩÕÖâ±î¥Ã¿µ¡Öç¨ºà˘MΩô1ïπÃÅÖ•±‰)•Õ¡ΩÕÖâ±îΩÑ¯∞ÅÕï——ï»Åë‘Å’ÖπÕï—–Å•π∏Åï–Å°ï±–ÅπÂ—–Å¡Ö»ÅπïÕ—îÅëÖú∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅµÖπùîÅ—•µï»ÅΩ¥ÅëÖùï∏Å≠Ö∏Å©ïúÅâ…’≠îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâîÅô±ïÕ—îÅ”ï±ï»ÅµÂ≠îÅ±•πÕï»Å≠ΩµôΩ…—Öâï±–Å§Å…’πë–ÄƒÀäLƒ–Å—•µï»∞Åµï∏Åõ·±úÅÖ±±—•êÅΩ¡—•≠ï…ïπÃÅÕ¡ïÕ•ô•≠≠îÅÖπâïôÖ±•πúÅôΩ»ÅÖ≠≠’…Ö–Åë•πîÅ±•πÕï»Åô…ïµôΩ»Åï–Åùïπï…ï±–Å—Ö±∞∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅï»Å—ïù∏Å√îÅÖ–Å©ïúÅã·»Å—ÑÅ’–Å±•πÕïπîÅ—•ë±•ùï…îÅïπ∏Å¡±Öπ±Öù–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâS·……°ï–∞Å•……•—ÖÕ©Ω∏∞ÅÀ·ë°ï–∞Å’≠±Ö…–ÅÕÂ∏Åï±±ï»Åùïπï…ï±–Å’âï°ÖúÅï»ÅÖ±±îÅ—ïù∏Å√îÅÖ–Åë‘Åã·»Å—ÑÅ’–Å±•πÕïπîÅΩúÅù§É·ÂπïπîÅï∏Å¡Ö’Õî∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâÕÖµµîµÕ—Â…≠îµâ…•±±ï»µΩúµ±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ö∏Å©ïúÅâ…’≠îÅÕÖµµîÅÕ—Â…≠îÅ√îÅ≠Ωπ—Ö≠—±•πÕï»ÅÕΩ¥Å√îÅâ…•±±ï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»Åâ…•±±ïÕ—Â…≠ï∏Åë•∏ÅŸÖπ±•ùŸ•ÃÅ•≠≠îÅ≠Ö∏Åâ…’≠ïÃÅë•…ï≠—îÅ√îÅ≠Ωπ—Ö≠—±•πÕï»∞ÅΩúÅ°ŸΩ…ôΩ»Åï∏Åïùï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîÅ—…ïπùÃ∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘YÖπ±•ùŸ•ÃÄÒÕ—…Ωπú˘πï§ΩÕ—…Ωπú¯ÉäLÅ•≠≠îÅë•…ï≠—î∏Å	…•±±ï»ÅÕ•——ï»ÅΩµ—…ïπ–Äƒ»Åµ¥Åô…ÑÉ·Âï–∞)µïπÃÅ≠Ωπ—Ö≠—±•πÕï»Å±•ùùï»Å…ï—–Å√îÅ°Ω…π°•ππï∏∏ÅïππîÅÖŸÕ—Öπëï∏Ä°≠Ö±–ÅŸï…—ï·ÖŸÕ—Öπê§)√ïŸ•…≠ï»Å°ŸΩ»ÅÕ—ï…¨Å≠Ω……ï≠Õ©Ωπï∏ÅôÖ≠—•Õ¨ÅΩ¡¡±ïŸïÃ∞ÅÕ¡ïÕ•ï±–ÅŸïêÅ£·Âï…îÅÕ—Â…≠ï»Ä°ù…ΩŸ–ÅÕï—–)ô…ÑÅ…’πë–É
ƒ–∞¿¿Åë•Ω¡—…•ï»ÅΩúÅΩ¡¡ΩŸï»Åâ±•»ÅôΩ…Õ≠©ï±±ï∏Åµï…≠âÖ»§∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘-Ωπ—Ö≠—±•πÕï…ïÕï¡–Åï»Åµï»Åïπ∏ÅâÖ…îÅÕ—Â…≠îΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–Å•π≠±’ëï…ï»ÅΩùœîÅ	ÅΩúÅ%Ä°ÕîÅ€ï»(ÒÑÅ°…ïòÙàΩù’•ëîΩôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ºà˘ΩŸï…Õ•≠–ÅΩŸï»Å°ï±îÅ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ΩÑ¯§+äLÅ∑ï∞ÅÕΩ¥Åï∏Åâ…•±±ï…ïÕï¡–Å•≠≠îÅ°Ö»∏Åï——îÅ≠…ïŸï»Åï∏Åïùï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîΩ±•πÕï—•±¡ÖÕπ•πú∞)•≠≠îÅâÖ…îÅï–Åù©ïπâ…’¨ÅÖÿÅâ…•±±ï—Ö±±ïπî∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘;ï»Åë‘Å°Ö»Åõï—–Åï∏Åïùï∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–∞Å≠Ö∏Åë‘Åœ·≠îÅΩ¡¿Åª·ÂÖ≠—•úÅëï–Å¡…Ωë’≠—ï–)Ω¡—•≠ï…ï∏Å°Ö»ÅÕÖ—–ÅëïúÅΩ¡¿ÅµïêÉäLÅôΩ»Åï≠Õïµ¡ï∞Åï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩëÖ•±•ïÃΩôΩç’ÃµëÖ•±•ïÃ¥‰¿µ¡Öç¨ºà˘Ωç’ÃÅÖ•±•ïÃÄ‰¿µ¡Öç¨ΩÑ¯Åï∏ÅµÂî)â…’≠–ÅëÖùÕ±•πÕîÅâ±Öπ–ÅπÂîÅ±•πÕïâ…’≠ï…îÉäLÅΩúÅÕÖµµïπ±•ùπîÅ¡…•Õï»Åô…ÑÅô±ï…îÅπΩ…Õ≠î)πï——â’—•≠≠ï»∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘-Ω…–ÅÕÖù–ËÅâ…’¨ÅÖ±±—•êÅï∏Å…ïÕï¡–ÅÕΩ¥Åï»ÅÕÖ—–ÅΩ¡¿ÅÕ¡ïÕ•ô•≠–ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»∞Å•≠≠î)â…•±±ïÕ—Â…≠ï∏Åë•∏∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅâÖ…îÅâ…’≠îÅâ…•±±ïÕ—Â…≠ï∏Åµ•∏Å√îÅ≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâYÖπ±•ùŸ•ÃÅ•≠≠îÅë•…ï≠—î∏ÅŸÕ—Öπëï∏Åµï±±Ω¥Åâ…•±±ïù±ÖÕÃÅΩúÉ·ÂîÄ°Ÿï…—ï·ÖŸÕ—Öπê§Åù´·»ÅÖ–Åïôôï≠—•ÿÅÕ—Â…≠îÅΩô—îÅ∑îÅ©’Õ—ï…ïÃ∞ÅÕ¡ïÕ•ï±–ÅŸïêÅ£·Âï…îÅÕ—Â…≠ï»∏Å-Ωπ—Ö≠—±•πÕï»Å—…ïπùï»ÅΩùœîÅ	ÅΩúÅ%∞ÅÕΩ¥Å•≠≠îÅô•ππïÃÅ√îÅï∏Åâ…•±±ï…ïÕï¡—ï–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å—…ïπùÃÅï∏Åïùï∏ÅÕÂπÕ’πëï…œ·≠ï±ÕîÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ…ë§Åï∏ÅΩ¡—•≠ï»ÅëÑÅ∑ï±ï»Å°Ω…π°•ππïπÃÅ≠…’µπ•πúÄ°ôΩ»Å…•≠—•úÅ	§ÅΩúÅâï≠…ïô—ï»Å…•≠—•úÅ¡ÖÕÕôΩ…¥ÉäLÅ•≠≠îÅâÖ…îÅÕ—Â…≠ï∏∞ÅÕ±•¨Åï∏ÅŸÖπ±•úÅÕÂπÕ’πëï…œ·≠ï±ÕîÅôΩ»Åâ…•±±ï»Åù´·»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸÑµ≠ΩÕ—ï»µ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸÑÅ≠ΩÕ—ï»Å≠Ωπ—Ö≠—±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»Åëï–Å•≠≠îÅô•ππïÃÅï—–ÅôÖÕ–ÅÕŸÖ»Å√îÅ°ŸÑÅ≠Ωπ—Ö≠—±•πÕï»Å≠ΩÕ—ï»∞ÅΩúÅ°ŸÑÅÕΩ¥ÅôÖ≠—•Õ¨ÅÖŸù´·»Å¡…•Õï∏∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ï–Åô•ππïÃÅ•≠≠îÅï—–ÅôÖÕ–ÅÕŸÖ»ÉäLÅ¡…•Õï∏Å√îÅ≠Ωπ—Ö≠—±•πÕï»ÅŸÖ…•ï…ï»ÅµÂîÅ’–Åô…Ñ)±•πÕï—Â¡î∞Åµï…≠î∞Å¡Ö≠π•πùÕÕ”·……ï±ÕîÅΩúÅ°Ÿ•±≠ï∏ÅôΩ…°Öπë±ï»Åë‘ÅŸï±ùï»∏ÅQºÅ’±•≠î)≠Ωπ—Ö≠—±•πÕï»Å≠Ö∏Å≠ΩÕ—îÅÕ€ô…–ÅôΩ…Õ≠©ï±±•úÅÕï±ÿÅΩ¥ÅëîÅëï≠≠ï»ÅÕÖµµîÅÕÂπÕâï°Ωÿ∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸÑÅÕΩ¥Å√ïŸ•…≠ï»Å¡…•Õï∏Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘5ï…≠îÅΩúÅ—ï≠πΩ±Ωù§ΩÕ—…Ωπú¯ÉäLÅπÂï…îÅµÖ—ï…•Ö±ï»Ä°òπï≠Ã∏ÅÕ•±•≠Ωπ°Âë…Ωùï∞§Å≠ΩÕ—ï»(ÄÅΩô—îÅµï»Åïπ∏Åï±ë…îΩ±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘1•πÕï—Â¡îΩÕ—…Ωπú¯ÉäLÅëÖùÕ±•πÕï»Å≠ΩÕ—ï»Åµï»Å¡ï»Å±•πÕîÅïπ∏Å∑ïπïëÕ±•πÕï»∞Åµï∏Å≠Ö∏(ÄÅ±•≠ïŸï∞Å≥·ππîÅÕïúÅÖŸ°ïπù•úÅÖÿÅâ…’≠Õ°Â¡¡•ù°ï–Ω±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘AÖ≠π•πùÕÕ”·……ï±ÕîΩÕ—…Ωπú¯ÉäLÅÕ”·……îÅ¡Ö≠π•πùï»Å°Ö»ÅΩô—îÄ°µï∏Å•≠≠îÅÖ±±—•ê§Å±ÖŸï…î(ÄÅ¡…•ÃÅ¡ï»Å±•πÕîΩ±§¯(ÄÄÒ±§¯ÒÕ—…Ωπú˘Ω…°Öπë±ï»ΩÕ—…Ωπú¯ÉäLÅ¡…•ÕïπîÅŸÖ…•ï…ï»Åµï±±Ω¥Åâ’—•≠≠ï»ÅΩúÅïπë…ï»ÅÕïúÅΩŸï»Å—•êΩ±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘ï∏ÅµïÕ–Å√ï±•—ï±•ùîÅ∑ï—ï∏ÉîÅô•ππîÅ…•≠—•úÅ¡…•ÃÅôΩ»ÅÖ≠≠’…Ö–Åë•πîÅ±•πÕï»Åï»ÉîÅœ·≠îÅëï¥)Ω¡¿Åë•…ï≠—îÉäLÅâ…’¨Åœ·≠ïôï±—ï–Å√îÄÒÑÅ°…ïòÙàºà˘ôΩ…Õ•ëï∏ΩÑ¯ÅôΩ»ÉîÅÕÖµµïπ±•ùπî)Ω¡¡ëÖ—ï…—îÅ¡…•Õï»Åô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅMîÅòπï≠Ã∏Åù©ï±ëïπëîÅ¡…•ÃÅ√î(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯Åï±±ï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îºƒµëÖ‰µÖç’Ÿ’îµµΩ•Õ–¥Ã¿µ¡Öç¨ºà˘ç’Ÿ’îÅ5Ω•Õ–ΩÑ¯ÅÕΩ¥Å≠Ωπ≠…ï—îÅï≠Õïµ¡±ï»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åï»Åëï–Å•≠≠îÅï—–ÅôÖÕ–ÅÕŸÖ»Å√îÅ°ŸÑÅ≠Ωπ—Ö≠—±•πÕï»Å≠ΩÕ—ï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâA…•Õï∏ÅŸÖ…•ï…ï»ÅµÂîÅ’–Åô…ÑÅ±•πÕï—Â¡î∞Åµï…≠î∞Å¡Ö≠π•πùÕÕ”·……ï±ÕîÅΩúÅôΩ…°Öπë±ï»∏ÅQºÅ’±•≠îÅ±•πÕï»Å≠Ö∏Å≠ΩÕ—îÅÕ€ô…–ÅôΩ…Õ≠©ï±±•úÅÕï±ÿÅΩ¥ÅëîÅëï≠≠ï»ÅÕÖµµîÅÕÂπÕâï°Ωÿ∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏Åô•ππï»Å©ïúÅ…•≠—•úÅ¡…•ÃÅôΩ»ÅÖ≠≠’…Ö–Åµ•πîÅ±•πÕï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâO·¨ÅΩ¡¿ÅπÖŸπï–Åô…ÑÅïÕ≠ï∏Åë•∏Å√îÅôΩ…Õ•ëï∏ÅÖÿÅ-Ωπ—Ö≠—±•πÕï»ππºÅôΩ»ÉîÅÕîÅΩ¡¡ëÖ—ï…—îÅ¡…•Õï»Åô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ÅM≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅôΩ»ÉîÅÕîÅ—Ω—Ö±¡…•Õï∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡Ö≠π•πùÕÕ—Ω……ï±Õî¥Ã¿µŸÃ¥‰¿àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄàÃ¿ÅŸÃ∏Ä‰¿µ¡Ö≠π•πúÉäLÅ°ŸÑÅ≥·ππï»ÅÕïú¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ»ÅÕ”·……îÅ¡Ö≠π•πùï»ÅÖ±±—•êÅâ•±±•ùÕ–Å¡ï»Å±•πÕî¸ÅM±•¨ÅŸ’…ëï…ï»Åë‘Å¡Ö≠π•πùÕÕ”·……ï±ÕîÅ…•≠—•ú∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘M”·……îÅ¡Ö≠π•πùï»Å°Ö»ÅΩô—îÅ±ÖŸï…îÅ¡…•ÃÅ¡ï»Å±•πÕî∞ÅÕ•ëï∏ÅµÖπùîÅ¡…Ωë’Õïπ—ï»ÅΩú)ôΩ…°Öπë±ï…îÅù•»Åï∏ÅŸ•ÕÃÅµïπùëï…ÖâÖ—–ÉäLÅµï∏ÄÒÕ—…Ωπú˘•≠≠îÅÖ±±—•êΩÕ—…Ωπú¯∏Åï–Å≥·ππï»ÅÕïúÉî)ôÖ≠—•Õ¨ÅÕ©ï≠≠îÅ¡…•ÃÅ¡ï»Å±•πÕîÅôΩ»Å¡Ö≠π•πùÕÕ”·……ï±ÕïπîÅë‘ÅŸ’…ëï…ï»∞Å§ÅÕ—ïëï–ÅôΩ»ÉîÅÖπ—Ñ∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Q•πúÉîÅŸ’…ëï…îÅ’—ΩŸï»Å¡…•Õï∏Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘∏ÅÕ—Ω»Å¡Ö≠π•πúÅ≠…ïŸï»Å£·Âï…îÅïπùÖπùÕ’—±ïùúΩ±§¯(ÄÄÒ±§˘!Ÿ•ÃÅÕ—Â…≠ï∏Åë•∏Åïπë…ï»ÅÕïú∞Å≠Ö∏Åë‘ÅÕ•——îÅ•ù©ï∏ÅµïêÅ’â…’≠—îÅ±•πÕï»Ω±§¯(ÄÄÒ±§˘M©ï≠¨Å°Ω±ëâÖ…°ï—ÕëÖ—ºÅ°Ÿ•ÃÅë‘Å≠´·¡ï»Åï∏ÅÕ—Ω»Å¡Ö≠π•πúÅë‘Åâ…’≠ï»ÅÕ©ï±ëï∏Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩ¡…•Ãµ¡ï»µ±•πÕîµÕ±•¨µÕÖµµïπ±•ùπï»µë‘ºà˘ù’•ëîÅΩ¥ÉîÅÕÖµµïπ±•ùπî)¡…•ÃÅ¡ï»Å±•πÕîΩÑ¯ÅôΩ»Å°ŸΩ…ëÖ∏Åë‘Å…ïùπï»Å’–Åëï–Å…ïï±±îÅÕÖµµïπ±•ùπ•πùÕù…’ππ±Öùï–∏Å–)ï≠Õïµ¡ï∞Å√îÅï–Å¡…Ωë’≠–ÅÕΩ¥Åô•ππïÃÅ§ÅâïùùîÅÕ”·……ï±Õï»Åï»(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩëÖ•±•ïÃΩôΩç’ÃµëÖ•±•ïÃ¥Ã¿µ¡Öç¨ºà˘Ωç’ÃÅÖ•±•ïÃÄÃ¿µ¡Öç¨ΩÑ¯ÅΩú(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩëÖ•±•ïÃΩôΩç’ÃµëÖ•±•ïÃ¥‰¿µ¡Öç¨ºà¯‰¿µ¡Öç¨ΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Ä‰¿µ¡Ö≠π•πúÅÖ±±—•êÅâ•±±•ùï…îÅ¡ï»Å±•πÕîÅïπ∏ÄÃ¿µ¡Ö≠π•πú¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ=ô—î∞Åµï∏Å•≠≠îÅÖ±±—•ê∏Åï–Å≥·ππï»ÅÕïúÉîÅÕ©ï≠≠îÅ¡…•ÃÅ¡ï»Å±•πÕîÅë•…ï≠—îÅôΩ»Å¡…Ωë’≠—ïπîÅë‘ÅŸ’…ëï…ï»∞Å§ÅÕ—ïëï–ÅôΩ»ÉîÅÖπ—ÑÅÖ–ÅÕ”·……îÅ¡Ö≠π•πúÅÖ’—ΩµÖ—•Õ¨Åï»Åâ•±±•ùÕ–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅã·»Å©ïúÅ—ïπ≠îÅ√îÅõ·»Å©ïúÅ≠´·¡ï»Åï∏ÅÕ—Ω»Å¡Ö≠π•πú¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ#·Âï…îÅïπùÖπùÕ’—±ïùú∞ÅÖ–ÅÕ—Â…≠ï∏Åë•∏Å≠Ö∏Åïπë…îÅÕïúÅΩŸï»Å—•ê∞ÅΩúÅ°Ω±ëâÖ…°ï—ÕëÖ—ºÅ°Ÿ•ÃÅë‘Åâ…’≠ï»Å±•πÕï»ÅÕ©ï±ëï∏∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡…•Ãµ¡ï»µ±•πÕîµÕ±•¨µÕÖµµïπ±•ùπï»µë‘àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâA…•ÃÅ¡ï»Å±•πÕîÉäLÅÕ±•¨ÅÕÖµµïπ±•ùπï»Åë‘Å…•≠—•úà∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»Åë‘Åã·»ÅÕîÅ√îÅ¡…•ÃÅ¡ï»Å±•πÕîÅ§ÅÕ—ïëï–ÅôΩ»Å≠’∏Å¡Ö≠π•πùÕ¡…•Ã∞ÅµïêÅï–Åïπ≠ï±–Å…ïùπïï≠Õïµ¡ï∞∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘;ï»Åë‘ÅÕÖµµïπ±•ùπï»Å≠Ωπ—Ö≠—±•πÕï¡…•Õï»ÉäLÅÕ¡ïÕ•ï±–Å√îÅ—Ÿï…ÃÅÖÿÅ’±•≠îÅ¡Ö≠π•πùÕÕ”·……ï±Õï»)ï±±ï»Å¡…Ωë’≠—ï»ÉäLÅù•»Å¡Ö≠π•πùÕ¡…•Õï∏ÅÖ±ïπîÅï–Åµ•ÕŸ•ÕïπëîÅâ•±ëî∏Åï∞ÅÖ±±—•êÅ—Ω—Ö±¡…•Õï∏Å√î)Öπ—Ö±∞Å±•πÕï»Å§Å¡Ö≠π•πùï∏ÅôΩ»Åï∏Å…ïï±∞ÅÕÖµµïπ±•ùπ•πú∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘≠Õïµ¡ï∞Ä°≠’∏Å•±±’Õ—…Ö—•Ÿ–∞Å•≠≠îÅ…ïï±±îÅ¡…•Õï»§Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§¯Ã¿µ¡Ö≠π•πúÅ—•∞ÄÃ¿¿Å≠»ÄÙÄƒ¿Å≠»Å¡ï»Å±•πÕîΩ±§¯(ÄÄÒ±§¯‰¿µ¡Ö≠π•πúÅ—•∞Ä‹‘¿Å≠»ÄÙÄ‡∞ÃÃÅ≠»Å¡ï»Å±•πÕîΩ±§¯(Ω’∞¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘Mï±ÿÅΩ¥Ä‰¿µ¡Ö≠π•πùï∏Å≠ΩÕ—ï»Åµï»Å—Ω—Ö±–∞Åï»Åëï∏Åâ•±±•ùÕ–Å¡ï»Å±•πÕîÅ§Åëï——îÅï≠Õïµ¡ï±ï–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘=µ—…ïπ—±•úÅ∑ïπïëÕ≠ΩÕ—πÖêΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘ÖπúÅ¡…•ÃÅ¡ï»Å±•πÕîÅµïêÅ°ŸΩ»ÅµÖπùîÅë‘ÅôÖ≠—•Õ¨Åâ…’≠ï»Å¡ï»Å∑ïπïê∏Åï——îÅŸÖ…•ï…ï»ÅµÂî)µï±±Ω¥ÅëÖùÕ±•πÕï»Ä£•∏Å±•πÕîÅ¡ï»Åâ…’≠–ÅëÖú§ÅΩúÅ∑ïπïëÕ±•πÕï»Ä°—Â¡•Õ¨Å—ºÅ±•πÕï»Å¡ï»Å∑ïπïê∞+•∏Å¡ï»É·Âî§ÉäLÅÕîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»ºà˘ù’•ëîÅΩ¥Å∑ïπïëÕ±•πÕï»)ŸÃ∏ÅëÖùÕ±•πÕï»ΩÑ¯ÅôΩ»Åâ…’≠Õ°Â¡¡•ù°ï–∏ÅMîÅï≠—î∞ÅΩ¡¡ëÖ—ï…–Å¡…•ÃÅ¡ï»Å¡Ö≠π•πúÅôΩ»Åï∏)∑ïπïëÕ±•πÕîÅÕΩ¥ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ω’±—…ÑΩ’±—…Ñ¥ÿµ¡Öç¨ºà˘U±—…ÑÄÿµ¡Öç¨ΩÑ¯ÅÕΩ¥)≠Ωπ≠…ï–Åï≠Õïµ¡ï∞∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åã·»Å©ïúÅÕîÅ√îÅ¡…•ÃÅ¡ï»Å±•πÕîÅ§ÅÕ—ïëï–ÅôΩ»Å¡Ö≠π•πùÕ¡…•Õï∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ…ë§Åëï–Åù•»Åï–Å…ïï±–ÅÕÖµµïπ±•ùπ•πùÕù…’ππ±ÖúÅ√îÅ—Ÿï…ÃÅÖÿÅ’±•≠îÅ¡Ö≠π•πùÕÕ”·……ï±Õï»ÅΩúÅ¡…Ωë’≠—ï»ÉäLÅ¡Ö≠π•πùÕ¡…•Õï∏ÅÖ±ïπîÅ≠Ö∏Åù§Åï–Åµ•ÕŸ•ÕïπëîÅâ•±ëîÅÖÿÅ°ŸÑÅÕΩ¥ÅôÖ≠—•Õ¨Å≥·ππï»ÅÕïú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏Å…ïùπï»Å©ïúÅ’–ÅΩµ—…ïπ—±•úÅ∑ïπïëÕ≠ΩÕ—πÖê¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâÖπúÅ¡…•ÃÅ¡ï»Å±•πÕîÅµïêÅ°ŸΩ»ÅµÖπùîÅ±•πÕï»Åë‘ÅôÖ≠—•Õ¨Åâ…’≠ï»Å¡ï»Å∑ïπïêÉäLÅëï——îÅŸÖ…•ï…ï»ÅµÂîÅµï±±Ω¥ÅëÖùÕ±•πÕï»ÅΩúÅ∑ïπïëÕ±•πÕï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ôΩ»µŸÖ…•ï…ï»µ¡…•Õïπîµµï±±Ω¥µâ’—•≠≠ïπîàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ…ôΩ»ÅŸÖ…•ï…ï»Å¡…•ÕïπîÅ√îÅ≠Ωπ—Ö≠—±•πÕï»Åµï±±Ω¥Åâ’—•≠≠ïπî¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»ÅÕÖµµîÅ≠Ωπ—Ö≠—±•πÕîÅ≠Ö∏Å≠ΩÕ—îÅ’±•≠–Å°ΩÃÅôΩ…Õ≠©ï±±•ùîÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘MÖµµîÅ≠Ωπ—Ö≠—±•πÕîÅ≠Ö∏Å≠ΩÕ—îÅ’±•≠–Åô…ÑÅâ’—•≠¨Å—•∞Åâ’—•≠¨∞ÅÖÿÅô±ï…îÅù…’ππï»ËΩ¿¯((Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘U±•≠îÅ•ππ≠´·¡ÕÖŸ—Ö±ï»ÅΩúÅŸΩ±’¥ÅµïêÅ¡…Ωë’Õïπ—ï∏Ω±§¯(ÄÄÒ±§˘U±•≠îÅë…•ô—Õ≠ΩÕ—πÖëï»ÅΩúÅô…Ö≠—¡Ω±•—•≠¨Ω±§¯(ÄÄÒ±§˘Q•ëÕâïù…ïπÕïëîÅ≠Öµ¡Öπ©ï»ÅΩúÅ—•±â’êΩ±§¯(ÄÄÒ±§˘!ŸΩ»ÅΩô—îÅëï∏Åïπ≠ï±—îÅâ’—•≠≠ï∏ÅΩ¡¡ëÖ—ï…ï»ÅÕ•πîÅïùπîÅ¡…•Õï»Ω±§¯(Ω’∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘ï——îÅï»Åπï——Ω¡¿Åëï…ôΩ»Åëï–Å≥·ππï»ÅÕïúÉîÅÕÖµµïπ±•ùπîÅ√îÅ—Ÿï…ÃÅÖÿÅâ’—•≠≠ï»Å§ÅÕ—ïëï–ÅôΩ»+îÅ°Öπë±îÅ°ΩÃÅëï∏Åõ·…Õ—îÅµÖ∏Å≠Ωµµï»ÅΩŸï»∏ÅA…•ÕïπîÅ≠Ö∏ÅΩùœîÅïπë…îÅÕïúÅô…ÑÅëÖúÅ—•∞ÅëÖúÉäLÅŸ§)Ω¡¡ëÖ—ï…ï»Å¡…•ÕïπîÅëÖù±•ú∏ÅMîÅòπï≠Ã∏(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯ÅôΩ»Åï–Å≠Ωπ≠…ï–)ï≠Õïµ¡ï∞Å√îÅ°ŸΩ»ÅµÂîÅ¡…•Õï∏ÅôÖ≠—•Õ¨ÅŸÖ…•ï…ï»Åµï±±Ω¥Åâ’—•≠≠ïπîÅÖ≠≠’…Ö–Åªî∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å≠ΩÕ—ï»ÅÕÖµµîÅ≠Ωπ—Ö≠—±•πÕîÅ’±•≠–Å°ΩÃÅôΩ…Õ≠©ï±±•ùîÅâ’—•≠≠ï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâU±•≠îÅ•ππ≠´·¡ÕÖŸ—Ö±ï»∞Åë…•ô—Õ≠ΩÕ—πÖëï»∞Åô…Ö≠—¡Ω±•—•≠¨ÅΩúÅ—•ëÕâïù…ïπÕïëîÅ≠Öµ¡Öπ©ï»Åù´·»ÅÖ–Å¡…•Õï∏Å√îÅÕÖµµîÅ±•πÕîÅ≠Ö∏ÅŸÖ…•ï…îÅµï±±Ω¥ÅôΩ…°Öπë±ï…î∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅΩô—îÅïπë…ï»Å¡…•ÕïπîÅÕïú¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâA…•ÕïπîÅ≠Ö∏Åïπë…îÅÕïúÅô…ÑÅëÖúÅ—•∞ÅëÖú∏Å-Ωπ—Ö≠—±•πÕï»ππºÅΩ¡¡ëÖ—ï…ï»Å¡…•ÕïπîÅô…ÑÅôΩ…°Öπë±ï…πîÅëÖù±•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µ≠Ωπ—Ö≠—±•πÕï»µπºµâï…ïùπï»µ—Ω—Ö±¡…•ÃàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ…ëÖ∏Å-Ωπ—Ö≠—±•πÕï»ππºÅâï…ïùπï»Å—Ω—Ö±¡…•Ãà∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâM±•¨ÅÕï»Åë‘Å—Ω—Ö±¡…•Õï∏Ä°¡…Ωë’≠—¡…•ÃÄ¨Åô…Ö≠–§ÅµïêÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
Ï∞ÅΩúÅ°ŸΩ…ôΩ»Åëï∏Å≠Ö∏Åù§Åï–ÅÖππï–Å…ïÕ’±—Ö–Åïπ∏Å¡…Ωë’≠—¡…•ÃÅÖ±ïπî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘-Ωπ—Ö≠—±•πÕï»ππºÅŸ•Õï»Å¡…Ωë’≠—¡…•Õï∏Å’—ï∏Åô…Ö≠–ÅÕΩ¥ÅÕ—ÖπëÖ…ê∞ÅÕ±•¨Åë‘Åï»ÅŸÖπ–Å—•∞Åô…Ñ)Öπë…îÅ¡…•ÕÕÖµµïπ±•ùπï…î∏ÅM≥ï»Åë‘Å√îÄÒÕ—…Ωπú˚
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏΩÕ—…Ωπú¯ÅΩŸï»Å¡…•Õ±•Õ—ï∏∞)Ÿ•Õï»ÅΩúÅÕΩ…—ï…ï»ÅŸ§Å§ÅÕ—ïëï–Åï——ï»ÄÒÕ—…Ωπú˘—Ω—Ö±¡…•ÃΩÕ—…Ωπú¯ÉäLÅ¡…Ωë’≠—¡…•ÃÅ¡±’ÕÃÅô…Ö≠–ÉäLÅôΩ»)Öπ—Ö±±ï–Åë‘Å°Ö»ÅŸÖ±ù–∏Åï–Å≠Ö∏Åïπë…îÅ°Ÿ•±≠ï∏Åâ’—•≠¨ÅÕΩ¥Åï»Åâ•±±•ùÕ–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘≠Õïµ¡ï∞Ä°≠’∏Å•±±’Õ—…Ö—•Ÿ–∞Å•≠≠îÅ…ïï±±îÅ¡…•Õï»§Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘	’—•≠¨ÅËÅ¡…Ωë’≠—¡…•ÃÄ»‘¿Å≠»Ä¨Åô…Ö≠–Ä‹‰Å≠»ÄÙÄÒÕ—…Ωπú¯Ã»‰Å≠»ΩÕ—…Ωπú¯Å—Ω—Ö±–Ω±§¯(ÄÄÒ±§˘	’—•≠¨ÅËÅ¡…Ωë’≠—¡…•ÃÄ»ÿ‘Å≠»Ä¨Åù…Ö—•ÃÅô…Ö≠–ÄÙÄÒÕ—…Ωπú¯»ÿ‘Å≠»ΩÕ—…Ωπú¯Å—Ω—Ö±–Ω±§¯(Ω’∞¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘Mï±ÿÅΩ¥Å	’—•≠¨ÅÅ°Ö»Å±ÖŸïÕ–Å¡…Ωë’≠—¡…•Ã∞Åï»Å	’—•≠¨ÅÅôÖ≠—•Õ¨Åâ•±±•ùÕ–Åªï»Åô…Ö≠–Å…ïùπïÃ)µïê∏ÅMï»Åë‘Å≠’∏Å√îÅ¡…Ωë’≠—¡…•Õï∏Åë•…ï≠—îÅ°ΩÃÅ°Ÿï»Åâ’—•≠¨∞Å≠Ö∏Åë‘Å±ï—–ÅïπëîÅΩ¡¿ÅµïêÅëï–)ëÂ…ïÕ—îÅÖ±—ï…πÖ—•Ÿï–Å’—ï∏ÉîÅŸ•—îÅëï–∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘YÖ…ï»Å’—ï∏Åâï≠…ïô—ï–Å±Öùï…Õ—Ö—’ÃÅ≠Ö∏Å•≠≠îÅŸ•ππîÅµï…≠ï–É
≠±ÖŸïÕ—îÅ¡…•œ
Ï∞ÅΩúÅ°Ÿï…–Å—•±â’êÅŸ•Õï»)ªï»Åëï–ÅÕ•Õ–Åâ±îÅ≠Ωπ—…Ω±±ï…–∏ÅY§ÅΩ¡¡ëÖ—ï…ï»Å¡…•ÕïπîÅëÖù±•ú∏ÅMîÅï–)ï≠—îÅï≠Õïµ¡ï∞Å√îÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÖç’Ÿ’îºƒµëÖ‰µÖç’Ÿ’îµµΩ•Õ–¥Ã¿µ¡Öç¨ºà˘ç’Ÿ’îÅ5Ω•Õ–ΩÑ¯ÅÕ•∏)¡…Ωë’≠—Õ•ëîÅôΩ»ÉîÅÕîÅ—Ω—Ö±¡…•Ãµ…ïùπïÕ—Â≠≠ï–Å§Å¡…Ö≠Õ•Ã∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å≠Ö∏Å©ïúÅÕ≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
Ï¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ…ë§Åô…Ö≠–Åï»Åï∏Å…ïï±∞Åëï∞ÅÖÿÅëï–Åë‘ÅôÖ≠—•Õ¨Åâï—Ö±ï»∞ÅΩúÅ≠Ö∏Åïπë…îÅ°Ÿ•±≠ï∏Åâ’—•≠¨ÅÕΩ¥Åïùïπ—±•úÅï»Åâ•±±•ùÕ–ÉäLÅï∏Å±ÖÿÅ¡…Ωë’≠—¡…•ÃÅµïêÅ£·‰Åô…Ö≠–Å≠Ö∏ÅïπëîÅΩ¡¿ÅëÂ…ï…îÅïπ∏Åï∏Å£·Âï…îÅ¡…Ωë’≠—¡…•ÃÅµïêÅù…Ö—•ÃÅô…Ö≠–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅΩô—îÅΩ¡¡ëÖ—ï…ïÃÅ¡…•Õïπî¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâY§ÅΩ¡¡ëÖ—ï…ï»Å¡…•ÕïπîÅô…ÑÅôΩ…°Öπë±ï…πîÅëÖù±•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïÖâΩππïµïπ–µŸÃµ≠©Ω¡îµÕï±ÿàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ωπ—Ö≠—±•πÕïÖâΩππïµïπ–Åï±±ï»Å≠´·¡îÅÕï±ÿÉäLÅ°ŸÑÅ≥·ππï»ÅÕïú¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâΩ…ëï±ï»ÅΩúÅ’±ïµ¡ï»ÅŸïêÅÖâΩππïµïπ–Å√îÅ≠Ωπ—Ö≠—±•πÕï»ÅÕÖµµïπ±•ùπï–ÅµïêÉîÅâïÕ—•±±îÅÕï±ÿÅ°Ÿï»ÅùÖπú∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘±ï…îÅôΩ…°Öπë±ï…îÅ—•±âÂ»ÅÖâΩππïµïπ–ΩôÖÕ–Å±ïŸï…•πúÅÖÿÅ≠Ωπ—Ö≠—±•πÕï»∞ÅπΩï∏ÅùÖπùï»Åµïê)…ÖâÖ—–∏Å=¥Åëï–Å≥·ππï»ÅÕïúÅÖŸ°ïπùï»ÅÖÿÅ°ŸÑÅë‘Å¡…•Ω…•—ï…ï»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Ω…ëï±ï»ÅµïêÅÖâΩππïµïπ–Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘M±•¡¡ï»ÉîÅ°’Õ≠îÉîÅâïÕ—•±±îÅ√îÅπÂ—–Ω±§¯(ÄÄÒ±§˘-Ö∏Åù§Åï∏ÅôÖÕ–Å…ÖâÖ—–Å°ΩÃÅïπ≠ï±—îÅôΩ…°Öπë±ï…îΩ±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸÑÅë‘Åã·»ÅŸ•—îΩ†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘–ÅÖâΩππïµïπ–Åâ•πëï»ÅëïúÅ—•∞É•∏ÅôΩ…°Öπë±ï…ÃÅ¡…•Ã∞ÅµïπÃÅ¡…•Õï»Åùïπï…ï±–ÅŸÖ…•ï…ï»)µï±±Ω¥Åâ’—•≠≠ï»ÅΩúÅΩŸï»Å—•ê∏ÅâΩππïµïπ—Õ¡…•Õï∏Åï»Åëï…ôΩ»Å•≠≠îÅª·ëŸïπë•ùŸ•ÃÅëï∏Å±ÖŸïÕ—î)—•±ù©ïπùï±•ùîÅ—•∞Åïπ°Ÿï»Å—•ê∏ÅM©ï≠¨Åù©ï…πîÅ©ïŸπ±•úÅΩ¥ÅÖâΩππïµïπ—Õ¡…•Õï∏Åë•∏ÅôΩ»Åòπï≠Ã∏(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ω’±—…ÑΩ’±—…Ñ¥ÿµ¡Öç¨ºà˘U±—…ÑÄÿµ¡Öç¨ΩÑ¯ÅôΩ…—ÕÖ—–Åï»)≠Ωπ≠’……ÖπÕïëÂ≠—•úÅŸïêÉîÅÕÖµµïπ±•ùπîÄÒÑÅ°…ïòÙàºà˘°ΩÃÅΩÕÃΩÑ¯∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»ÅÖâΩππïµïπ–ÅÖ±±—•êÅâ•±±•ùï…îÅïπ∏ÉîÅ≠´·¡îÅÕï±ÿ¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%≠≠îÅª·ëŸïπë•ùŸ•Ã∏Å–ÅÖâΩππïµïπ–Åâ•πëï»ÅëïúÅ—•∞É•∏ÅôΩ…°Öπë±ï…ÃÅ¡…•Ã∞ÅÕΩ¥Å•≠≠îÅÖ±±—•êÅï»Åëï∏Å±ÖŸïÕ—îÅ—•±ù©ïπùï±•ùîÅ—•∞Åïπ°Ÿï»Å—•êÉäLÅëï–ÅÖŸ°ïπùï»ÅÖÿÅ…ÖâÖ——ï∏ÅΩúÅ°ŸΩ…ëÖ∏Å¡…•ÕïπîÅâïŸïùï»ÅÕïúÅΩŸï»Å—•ê∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅÕ§ÅΩ¡¿Åï–Å±•πÕïÖâΩππïµïπ–Åªï»Å©ïúÅŸ•∞¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâï–ÅŸÖ…•ï…ï»Åµï±±Ω¥ÅôΩ…°Öπë±ï…îÉäLÅÕ©ï≠¨ÅŸ•±Øï…ïπîÅ°ΩÃÅëï∏ÅÖ≠—’ï±±îÅâ’—•≠≠ï∏∏Å-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å•πùï∏ÅÖŸ—Ö±îÅµïêÅôΩ…°Öπë±ï…πîÅΩ¥Åëï——î∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µ≠©Ω¡îµ≠Ωπ—Ö≠—±•πÕï»µ¡Ñµπï—–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ!ŸΩ…ëÖ∏Å≠´·¡îÅ≠Ωπ—Ö≠—±•πÕï»Å√îÅπï—–à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâM—ïùïπîÅôΩ»ÉîÅâïÕ—•±±îÅ≠Ωπ—Ö≠—±•πÕï»Å—…Âù–Å√îÅπï—–∞Åô…ÑÅ…ïÕï¡–Å—•∞Åô’±±õ·…–Å≠´·¿Å°ΩÃÅôΩ…°Öπë±ï»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˚ÅâïÕ—•±±îÅ≠Ωπ—Ö≠—±•πÕï»Å√îÅπï—–Åï»Åïπ≠ï±–Åªï»Åë‘ÅŸï–Å°ŸÑÅë‘Å—…ïπùï»ËΩ¿¯((ÒΩ∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‰Ïà¯(ÄÄÒ±§˘!ÑÅï∏ÅùÂ±ë•úÅ…ïÕï¡–Åô…ÑÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÄ°Õ—Â…≠î∞Å	∞Å%∞ÅΩúÅïÿ∏Åe0Ωa%LΩ(ÄÉäLÅÕîÅ€ï»ÄÒÑÅ°…ïòÙàΩù’•ëîΩôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏ºà˘ù’•ëîÅΩ¥ÉîÅ±ïÕîÅ…ïÕï¡—ï∏Åë•∏ΩÑ¯§Ω±§¯(ÄÄÒ±§˘•π∏Å…•≠—•úÅ¡…Ωë’≠–ÉäLÅœ·¨ÅΩ¡¿ÅπÖŸπï–Åô…ÑÅïÕ≠ï∏Åë•∏Å√îÄÒÑÅ°…ïòÙàºà˘ôΩ…Õ•ëï∏ΩÑ¯Å€ï»∞(ÄÅòπï≠Ã∏ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωô•π•—‰Ωâ•Ωô•π•—‰¥ÿµ¡Öç¨ºà˘	•Ωô•π•—‰ΩÑ¯Ω±§¯(ÄÄÒ±§˘MÖµµïπ±•ù∏Å—Ω—Ö±¡…•ÃÅ°ΩÃÅπΩ…Õ≠îÅôΩ…°Öπë±ï…îΩ±§¯(ÄÄÒ±§˘Yï±úÅôΩ…°Öπë±ï»ÅΩúÅô’±±õ·»Å≠´·¡ï–Å°ΩÃÅëï¥Ω±§¯(ΩΩ∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘-Ωπ—Ö≠—±•πÕï»ππºÅÕï±ùï»Å•≠≠îÅ≠Ωπ—Ö≠—±•πÕï»ÅÕï±ÿÉäLÅŸ§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»ÅΩúÅÕïπëï»Åëïú)Ÿ•ëï…îÅ—•∞ÅôΩ…°Öπë±ï…ï∏∞ÅÕΩ¥Å£ïπë—ï…ï»ÅÕï±ŸîÅ≠´·¡ï–∞Åâï—Ö±•πú∞Å±ïŸï…•πúÅΩúÅïŸïπ—’ï±∞)…ï—’»∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅ—…ïπùï»Å©ïúÅôΩ»ÉîÅâïÕ—•±±îÅ≠Ωπ—Ö≠—±•πÕï»Å√îÅπï—–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ∏ÅùÂ±ë•úÅ…ïÕï¡–Åô…ÑÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÅµïêÅÕ—Â…≠î∞Å	ÅΩúÅ%Ä°ΩúÅïÿ∏Åe0∞Åa%LÅï±±ï»ÅÅÖŸ°ïπù•úÅÖÿÅ±•πÕï—Â¡î§∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ’±±õ·…ï»Å©ïúÅ≠´·¡ï–Å°ΩÃÅ-Ωπ—Ö≠—±•πÕï»ππº¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏ÅY§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»ÅΩúÅÕïπëï»ÅëïúÅŸ•ëï…îÅ—•∞ÅôΩ…°Öπë±ï…ï∏Åë‘ÅŸï±ùï»∞ÅÕΩ¥Å£ïπë—ï…ï»ÅÕï±ŸîÅ≠´·¡ï–∞Åâï—Ö±•πúÅΩúÅ±ïŸï…•πú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µµÖ∏µ≠©Ω¡îµ≠Ωπ—Ö≠—±•πÕï»µ’—ï∏µ…ïÕï¡–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ö∏ÅµÖ∏Å≠´·¡îÅ≠Ωπ—Ö≠—±•πÕï»Å’—ï∏Å…ïÕï¡–¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ-Ωπ—Ö≠—±•πÕï»Å…ïùπïÃÅÕΩ¥Åµïë•Õ•πÕ¨Å’—Õ—Â»Å§Å9Ω…ùîÅΩúÅ≠…ïŸï»ÅùÂ±ë•úÅ…ïÕï¡–∞ÅΩùœîÅ’—ï∏ÅÕ—Â…≠î∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿¯ÒÕ—…Ωπú˘9ï§∏ΩÕ—…Ωπú¯Å-Ωπ—Ö≠—±•πÕï»Å…ïùπïÃÅÕΩ¥Åµïë•Õ•πÕ¨Å’—Õ—Â»Å§Å9Ω…ùî∞ÅΩúÅ≠…ïŸï»)ùÂ±ë•úÅ…ïÕï¡–Ω—•±¡ÖÕπ•πúÅô…ÑÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÉäLÅëï——îÅù©ï±ëï»ÅΩùœîÅ±•πÕï»Å’—ï∏)Õ—Â…≠î∞ÅÕΩ¥ÅôÖ…ùïëîÅ≠ΩÕµï—•Õ≠îÅ±•πÕï»∏Ω¿¯((Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘Mï…ß·ÕîÅôΩ…°Öπë±ï…îÅâï»ÅΩ¥Å…ïÕï¡–µ•πôΩ…µÖÕ©Ω∏ÅŸïêÅâïÕ—•±±•πú∏Å-´·¿Åô…ÑÅ’Õï…ß·Õî)≠•±ëï»ÅÕΩ¥Å•≠≠îÅ≠…ïŸï»Åëï——îÅô…ÖÀïëïÃÉäLÅëï–É·≠ï»Å…•Õ•≠Ωï∏ÅôΩ»Åôï•∞Å¡ÖÕÕôΩ…¥Åï±±ï»ÅÕ—Â…≠î∞)ΩúÅëï…µïêÅôΩ»É·Âï•……•—ÖÕ©Ω∏Åï±±ï»ÄµÕ≠Öëî∏ÅMï±ÿÅï∏ÅôÖ…ùï±•πÕîÅ’—ï∏ÅÕ—Â…≠î∞ÅÕΩ¥(ÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»Ωô…ïÕ°±ΩΩ¨Ωô…ïÕ°±ΩΩ¨µΩπïëÖ‰¥Ã¿µ¡Öç¨ºà˘…ïÕ°1ΩΩ¨Å=πïÖ‰ΩÑ¯∞Å≠…ïŸï»)Ö±—œîÅùÂ±ë•úÅ…ïÕï¡–∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ7îÅ©ïúÅ°ÑÅ…ïÕï¡–ÅôΩ»Å±•πÕï»Å’—ï∏ÅÕ—Â…≠î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∏ÅMï±ÿÅôÖ…ùïëîÅ≠ΩÕµï—•Õ≠îÅ±•πÕï»Å’—ï∏ÅÕÂπÕ≠Ω……ï≠Õ©Ω∏Å…ïùπïÃÅÕΩ¥Åµïë•Õ•πÕ¨Å’—Õ—Â»ÅΩúÅ≠…ïŸï»ÅùÂ±ë•úÅ—•±¡ÖÕπ•πúÅ°ΩÃÅΩ¡—•≠ï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸÑÅã·»Å©ïúÅ—ïπ≠îÅ°Ÿ•ÃÅï∏Åπï——â’—•≠¨Å•≠≠îÅÕ√·»ÅΩ¥Å…ïÕï¡–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâï–Åï»Åï–ÅŸÖ…Õï±Õ—ïù∏∏ÅUππüîÅôΩ…°Öπë±ï…îÅÕΩ¥Å•≠≠îÅ≠…ïŸï»Å…ïÕï¡–µ•πôΩ…µÖÕ©Ω∏ÅŸïêÅâïÕ—•±±•πú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µ©ïúµâÂ——îµ≠Ωπ—Ö≠—±•πÕïµï…≠îµÕï±ÿàËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ-Ö∏Å©ïúÅâÂ——îÅ≠Ωπ—Ö≠—±•πÕïµï…≠îÅÕï±ÿ¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒÿà∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâ!ŸΩ…ôΩ»Åëï–Å•≠≠îÅÖπâïôÖ±ïÃÉîÅâÂ——îÅ—•∞Åï–É
≠—•±ÕŸÖ…ïπëó
ÏÅ≠Ωπ—Ö≠—±•πÕïµï…≠îÅ√îÅïùï∏Å£ïπê∞ÅÕï±ÿÅµïêÅ±•¨ÅÕ—Â…≠î∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘ï–ÅÖπâïôÖ±ïÃÄÒÕ—…Ωπú˘•≠≠îΩÕ—…Ωπú¯ÉîÅâÂ——îÅ—•∞Åï–ÅÖππï–Åµï…≠îÅ°ï±–Å√îÅïùï∏Å£ïπê∞ÅÕï±ÿ)Ω¥ÅÕ—Â…≠ï∏Ä°A]HΩMA §Åï»Åëï∏ÅÕÖµµî∏ÅU±•≠îÅµï…≠ï»Å≠Ö∏Å°ÑÅ’±•¨Å	∞Å%∞ÅµÖ—ï…•Ö±îÅΩú)±•πÕïëïÕ•ù∏ÉäLÅÖ±–Åëï——îÅ√ïŸ•…≠ï»Å°ŸΩ…ëÖ∏Å±•πÕï∏ÅôÖ≠—•Õ¨ÅÕ•——ï»ÅΩúÅõ·±ïÃ∞Å•≠≠îÅâÖ…î)Õ—Â…≠ï∏∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘Uππ—Ö≠ï–ËÅ¡…•ŸÖ—îÅ±Öâï∞Ω†»¯(Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘!Ÿ•ÃÅëï–Åï»ÅÕπÖ≠¨ÅΩ¥Åª·ÂÖ≠—•úÅÕÖµµîÅôÂÕ•Õ≠îÅ±•πÕîÅÕΩ±ù–Å’πëï»Åï–ÅÖππï–ÅπÖŸ∏Ä°òπï≠Ã∏Åï∏)Ω¡—•≠ï…≠©ïëïÃÅïùï–Åµï…≠î§∞Åï»Åëï——îÅπΩîÅÖππï–Åïπ∏ÉîÅôÖ≠—•Õ¨ÅâÂ——îÅ¡…Ωë’≠–ÉäLÅÕîÅ€ï»(ÒÑÅ°…ïòÙàΩ¡…•ŸÖ—îµ±Öâï∞ºà˘ΩŸï…Õ•≠–ÅΩŸï»ÅΩ¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ΩÑ¯∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘Y’…ëï…ï»Åë‘Åï–Å°ï±–ÅÖππï–Å¡…Ωë’≠–∞Å—ÑÅëï–ÅΩ¡¿ÅµïêÅΩ¡—•≠ï…ï∏Åë•∏Åõ·…Õ–∏Ω¿¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅâÂ——îÅ—•∞Åï–Åâ•±±•ùï…îÅµï…≠îÅµïêÅÕÖµµîÅÕ—Â…≠î¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ%≠≠îÅ’—ï∏ÉîÅÕ©ï≠≠îÅµïêÅΩ¡—•≠ï»Åõ·…Õ–∏Å	∞Å%ÅΩúÅµÖ—ï…•Ö±îÅ≠Ö∏ÅŸÖ…•ï…îÅµï±±Ω¥Åµï…≠ï»ÅÕï±ÿÅŸïêÅ±•¨ÅÕ—Â…≠î∞ÅΩúÅ√ïŸ•…≠ï»Å°ŸΩ…ëÖ∏Å±•πÕï∏ÅôÖ≠—•Õ¨ÅÕ•——ï»∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Åëï–Å—…Âù–ÉîÅâÂ——îÅ—•∞Åï∏Å¡…•ŸÖ—îÅ±Öâï∞µŸï…Õ©Ω∏ÅÖÿÅ±•πÕï∏Åµ•∏¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∞Å°Ÿ•ÃÅëï–Åï»Åª·ÂÖ≠—•úÅÕÖµµîÅôÂÕ•Õ≠îÅ±•πÕîÅÕΩ±ù–Å’πëï»Åï–ÅÖππï–ÅπÖŸ∏ÉäLÅÕîÅ€ï»ÅΩŸï…Õ•≠–ÅΩŸï»ÅΩ¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»∏Åï–Åï»ÅπΩîÅÖππï–Åïπ∏ÉîÅâÂ——îÅ—•∞Åï–ÅôÖ≠—•Õ¨Å’±•≠–Å¡…Ωë’≠–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ±•πÕîµÕ•——ï»µôÖÕ–µ§µΩÂï–àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâ1•πÕîÅÕ•——ï»ÅôÖÕ–Å§É·Âï–¸Å´·»Åëï——îÄ°ΩúÅ•≠≠îÅëï——î§à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‰¥¿‘à∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâMΩ¥Å…ïùï∞Å’ôÖ…±•úÉäLÅ±•πÕï∏Å°Ö»ÅâÖ…îÅ”·…≠ï–Å’–Åï±±ï»Åô±Â——ï–ÅÕïú∏ÅMîÅëîÅ—…ÂùùîÅÕ—ïùïπîÅôΩ»ÉîÅ≥·ÕπîÅëï∏∞ÅΩúÅªï»Åë‘Å°ï±±ï»Åã·»ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»ÅµïêÅëï–ÅÕÖµµî∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘-©ïππïÃÅ±•πÕï∏ÄâôÖÕ—≥ïÕ–àÅ§É·Âï–∞Å°Ö»Åëï∏ÅÕΩ¥Å…ïùï∞ÅâÖ…îÅ”·…≠ï–Å±•—–Å’–Åï±±ï»Åô±Â——ï–ÅÕïú)—•∞Åï–ÅÖππï–ÅÕ—ïêÅ§É·Âï–Åïπ∏Åë‘Åï»ÅŸÖπ–Å—•∞ÉîÅô•ππîÅëï∏∏Åï–Åï»Å•≠≠îÅôÖ…±•úÅ§ÅÕïúÅÕï±ÿ∞Åµï∏)ëï–Åô•ππïÃÅï∏Å…•≠—•úÅΩúÅï∏ÅùÖ∞Å∑ï—îÉîÅ£ïπë—ï…îÅëï–Å√î∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘YÖπ±•ùîÅù…’ππï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘1•πÕï∏Å°Ö»Å”·…≠ï–Å’–ÉäLÅΩô—îÅôΩ…ë§Åëï∏Å°Ö»Å€ô…–Å§É·Âï–Å±ïπùï»Åïπ∏ÅëîÅÖπâïôÖ±—îÅçÑ∏Ä‡Å—•µïπîÅµÖπùîÅï≠Õ¡ï…—ï»Åô…ÖÀïëï»ÉîÅΩŸï…Õ≠…•ëî∞Åï±±ï»ÅôΩ…ë§É·Âï–Åï»Å”·…–Ω±§¯(ÄÄÒ±§˘1•πÕï∏Å°Ö»Åù±ïêÅΩ¡¿Å’πëï»Åëï–É·Ÿ…îÉ·Âï±Ω≠≠ï–Ω±§¯(ÄÄÒ±§˘‘Åâ±’π≠ï»ÅµÂîÅΩúÅÕ—…ïÕÕï»∞ÅÕΩ¥Åù´·»Åëï–ÅŸÖπÕ≠ï±•ùï…îÉîÅ≠©ïππîÅ°ŸΩ»Å±•πÕï∏ÅôÖ≠—•Õ¨Åï»Ω±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘M±•¨Åù´·»Åë‘Åëï–Å—…Âù–Ω†»¯(ÒΩ∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘YÖÕ¨Å°ïπëïπîÅù…’πë•úÅõ·…Õ–Ω±§¯(ÄÄÒ±§˘’≠–É·Âï–ÅµïêÅ±•πÕï€ôÕ≠îÅï±±ï»É·ÂïëÀï¡ï»Å±Öùï–ÅôΩ»Åâ…’¨ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»Ω±§¯(ÄÄÒ±§˘1’≠¨É·Âï–ÅΩúÅµÖÕÕï»ÅôΩ…Õ•≠—•úÅ√îÅëï–Å±’≠≠ïëîÉ·Âï±Ω≠≠ï–Å§ÅπΩï∏ÅÕï≠’πëï»Ω±§¯(ÄÄÒ±§˘	±’π¨Å…Ω±•úÅµïπÃÅë‘ÅÕï»ÅΩ¡¿∞ÅπïêÅΩúÅ—•∞ÅÕ•ëï∏ÉäLÅ±•πÕï∏Åù±•»ÅΩô—îÅ—•±âÖ≠îÅÖÿÅÕïúÅÕï±ÿΩ±§¯(ΩΩ∞¯((Òë•ÿÅÕ—Â±îÙââÖç≠ù…Ω’πêËç—‘ÌâΩ…ëï»Ë≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÌâΩ…ëï»µ…Öë•’ÃËƒ…¡‡Ì¡Öëë•πúËƒ—¡‡ÄƒŸ¡‡ÌµÖ…ù•∏ËƒŸ¡‡Ä¿ÌôΩπ–µÕ•ÈîË¿∏‡’…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏ÿÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÒÕ—…Ωπú˘%≠≠îÅùπ§Å°Ö…ë–Å§É·Âï–∞ÅΩúÅâ…’¨ÅÖ±ë…§Å¡•πÕï—–∞Åªï∞Åï±±ï»ÅÖπë…îÅÕ¡•ÕÕîÅù©ïπÕ—Öπëï»ΩÕ—…Ωπú¯ÅôΩ»Éî)õîÅ—Ö¨Å§Å±•πÕï∏∏Å3·Õπï»Åëï∏Å•≠≠îÅï——ï»ÅπΩï∏ÅôΩ…œ·¨∞Åï±±ï»Åë‘Å≠©ïππï»ÅÕµï…—îÅï±±ï»ÅÕï»)À·ë°ï–∞Åã·»Åë‘ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»∞É·Âï±ïùîÅï±±ï»Å±ïùïŸÖ≠–ÅÕÖµµîÅëÖúÉäLÅ•≠≠îÅŸïπ–ÅΩúÅÕîÅÖ∏∏(Ωë•ÿ¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘»Åë‘Å’Õ•≠≠ï»Å√îÅΩ¥Å±•πÕï∏ÅôÖ≠—•Õ¨Åï»Å’—îÅÖÿÉ·Âï–∞Å≠Ö∏ÅΩ¡—•≠ï…ï∏Åïπ≠ï±–ÅÕ©ï≠≠îÅëï——îÅµïê)ï∏Å±Öµ¡îÉäLÅëï–Åï»Å•≠≠îÅπΩîÉîÅ≠Ÿ•îÅÕïúÅôΩ»ÉîÅÕ√·……îÅΩ¥∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘%õ·±ùîÄÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩÕÂ≠ëΩµµï»ΩΩÂîΩâ…Â—π•πùÕôï•∞µπïëÕÖ—–µÕÂ∏Ω≠Ωπ—Ö≠—±•πÕï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9Ω…Õ¨Å!ï±Õï•πôΩ…µÖ—•≠¨Ä°9!$§ΩÑ¯Åù©ï±ëï»ÅëïππîÅïπ≠±îÅ—Ωµµï±ô•πùï……ïùï±ï∏ÅôΩ»Åªï»Åë‘Åã·»ÅΩ¡¡œ·≠îÅ±ïùîËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩπ°§ππºΩÕÂ≠ëΩµµï»ΩΩÂîΩâ…Â—π•πùÕôï•∞µπïëÕÖ—–µÕÂ∏Ω≠Ωπ—Ö≠—±•πÕï»àÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘-Ωπ—Ö≠–Å±ïùîÅëï…ÕΩ¥Åë‘Å°Ö»Å°Ö—–Å’âï°ÖúÅΩŸï»Å±ïπù…îÅ—•êÅï±±ï»Åëï…ÕΩ¥É·ÂπïπîÅë•πîÅï»ÅÀ·ëîÅï±±ï»Åœï…î∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩÕÂ≠ëΩµµï»ΩΩÂîΩâ…Â—π•πùÕôï•∞µπïëÕÖ—–µÕÂ∏Ω≠Ωπ—Ö≠—±•πÕï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9!$∞Å-Ωπ—Ö≠—±•πÕï»ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å±•πÕï∏ÅôΩ…ÕŸ•ππîÅâÖ¨Å§É·Âï–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∞Åëï–Åï»ÅÖπÖ—Ωµ•Õ¨Å’µ’±•ú∏ÅM±•µ°•ππï∏Ä°≠Ωπ©’π≠—•ŸÑ§ÅëÖππï»Åï∏ÅÕÖµµïπ°ïπùïπëî∞Å±’≠≠ï–Å±ΩµµîÅ…’πë–ÅÕï±ŸîÉ·Âïï¡±ï–∞ÅœîÅï∏Å≠Ωπ—Ö≠—±•πÕîÅ≠Ö∏ÅÖ±ë…§Å°ÖŸπîÅâÖ¨É·Âï–∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»Å±ïπùîÅ≠Ö∏Å©ïúÅ¡À·ŸîÅÕï±ÿÅõ·»Å©ïúÅΩ¡¡œ·≠ï»ÅΩ¡—•≠ï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9Ωï∏ÅõîÅôΩ…Õ•≠—•ùîÅôΩ…œ·¨ÅµïêÅô’≠–ÅΩúÅµÖÕÕï…•πúÅï»Åù…ï•–∏Å-©ïππï»Åë‘ÅÕµï…—î∞ÅÕï»ÅÀ·ë°ï–∞Åï±±ï»Å±•πÕï∏Å•≠≠îÅ≥·Õπï»∞Åã·»Åë‘ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»Åï±±ï»Å±ïùïŸÖ≠–ÅÕÖµµîÅëÖúÅ§ÅÕ—ïëï–ÅôΩ»ÉîÅôΩ…—Õï——îÉîÅ¡À·ŸîÅÕï±ÿ∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ’≠±Ö…–µÕÂ∏µµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâU≠±Ö…–Åï±±ï»Å”ï≠ï—îÅÕÂ∏ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅŸÖπ±•ùîÉï…ÕÖ≠ï»à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒ‹à∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâîÅŸÖπ±•ùÕ—î∞Å’ôÖ…±•ùîÉï…ÕÖ≠ïπîÅ—•∞ÅÖ–ÅÕÂπï–Åâ±•»Å’≠±Ö…–ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»Å§∞ÅΩúÅ°Ÿ•±≠îÅ—ïù∏Åë‘Åã·»Å—ÑÅ√îÅÖ±ŸΩ»∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘A±’—Õï±•úÅ’≠±Ö…–ÅÕÂ∏ÅµïêÅ±•πÕïπîÅ§Åï»ÅÕ©ï±ëï∏ÅÖ±ŸΩ…±•ú∞ÅΩúÅÕ≠Â±ëïÃÅÕΩ¥Å…ïùï∞ÅπΩîÅïπ≠ï±–)ΩúÅ’ôÖ…±•ú∏Åï–Åô•ππïÃÅ±•≠ïŸï∞ÅπΩï∏Å≠Ωµâ•πÖÕ©Ωπï»ÅÖÿÅÕÂµ¡—Ωµï»Åë‘Åã·»Å—ÑÅ√îÅÖ±ŸΩ»∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘YÖπ±•ùî∞Å’ôÖ…±•ùîÉï…ÕÖ≠ï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘M≠•——ï∏Å±•πÕî∞Åï±±ï»ÅÖŸ±ï•…•πùï»Ä°¡…Ω—ï•∏Ωôï—–Åô…ÑÅ”ï…ï€ôÕ≠ï∏§Å√îÅΩŸï…ô±Ö—ï∏Ω±§¯(ÄÄÒ±§˘1•πÕï∏Å±•ùùï»ÅŸ…ïπù–Ä°•ππ§Å’–§Ω±§¯(ÄÄÒ±§¯ÒÑÅ°…ïòÙàΩù’•ëîΩ≠Ωπ—Ö≠—±•πÕï»µΩúµ—Ω……îµΩÂπîºà˘S·……îÉ·ÂπîΩÑ¯Ω±§¯(ÄÄÒ±§˘1•πÕï∏Åï»Åâ…’≠–Å±ïπùï»Åïπ∏ÅÖπâïôÖ±–ÅâÂ——ï•π—ï…ŸÖ±∞Ω±§¯(ÄÄÒ±§˘M—Â…≠ï∏ÅÕ—ïµµï»Å•≠≠îÅ±ïπùï»ÉäLÅÕÂπï–Åïπë…ï»ÅÕïúÅù…ÖëŸ•ÃÅΩŸï»Å—•êÅôΩ»ÅëîÅô±ïÕ—îΩ±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘π≠±îÅ—•πúÉîÅÕ©ï≠≠îÅõ·…Õ–Ω†»¯(ÒΩ∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘	±’π¨ÅπΩï∏ÅùÖπùï»∞ÅΩúÅâ…’¨Åô’≠—ï…ëÀï¡ï»Åâï…ïùπï–ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»Ω±§¯(ÄÄÒ±§˘QÑÅ’–Å±•πÕï∏∞ÅÕ©ï≠¨ÅÖ–Åëï∏Å•≠≠îÅï»ÅŸ…ïπù–∞Å…ïπù´·»ÅΩúÅÕï—–Åëï∏Å•π∏Å√îÅπÂ—–Ω±§¯(ÄÄÒ±§˘	Â—–Å—•∞Åï∏Åπ‰Å±•πÕîÅ°Ÿ•ÃÅëï∏Åªô…µï»ÅÕïúÅÕ±’——ï∏ÅÖÿÅâÂ——ïÕÂ≠±’Õï∏Ω±§¯(ΩΩ∞¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘ï»ÅÖŸ±ï•…•πùï»Å√îÅ±•πÕïΩŸï…ô±Ö—ï∏Å•ù©ï∏ÅΩô—î∞Å≠Ö∏Åï∏ÅëÖùÕ±•πÕîÅ€ô…îÅŸï…ë–ÉîÅŸ’…ëï…îÉäL)µïêÅòπï≠Ã∏ÄÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÕΩô±ïπÃΩÕΩô±ïπÃµëÖ•±‰µë•Õ¡ΩÕÖâ±î¥Ã¿µ¡Öç¨ºà˘MΩô1ïπÃÅÖ•±‰)•Õ¡ΩÕÖâ±îΩÑ¯ÅÕï——ï»Åë‘Å•π∏Åï–Å°ï±–ÅπÂ—–∞Å…ïπ–Å¡Ö»Å°Ÿï»ÅëÖú∞ÅœîÅ¡…Ωâ±ïµï–ÅΩ¡¡Õ”ï»)Õ©ï±ëπï…î∏Ω¿¯((Òë•ÿÅÕ—Â±îÙââÖç≠ù…Ω’πêËç—‘ÌâΩ…ëï»Ë≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÌâΩ…ëï»µ…Öë•’ÃËƒ…¡‡Ì¡Öëë•πúËƒ—¡‡ÄƒŸ¡‡ÌµÖ…ù•∏ËƒŸ¡‡Ä¿ÌôΩπ–µÕ•ÈîË¿∏‡’…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏ÿÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯)-Ωµµï»Åëï–Å’≠±Ö…îÅÕÂπï–ÄÒÕ—…Ωπú˘¡±’—Õï±•ú∞ÅÕÖµµï∏ÅµïêÅÕµï…—î∞ÅÀ·ë°ï–∞Å±ÂÕõ·±ÕΩµ°ï–Åï±±ï»)Õï≠…ï–ΩÕ—…Ωπú¯∞Å≠Ö∏Åëï–Å€ô…îÅ—ïù∏Å√îÅï∏É·Âï•πôï≠Õ©Ω∏Åï±±ï»ÅÖππï∏Å—•±Õ—ÖπêÅÕΩ¥Å—…ïπùï»Å…ÖÕ¨)âï°Öπë±•πú∏ÅQÑÅÖÿÅ±•πÕï∏ÅΩúÅΩ¡¡œ·¨ÅΩ¡—•≠ï»Åï±±ï»Å±ïùîÅÕÖµµîÅëÖú∏(Ωë•ÿ¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘!Ö»ÅÕÂπï–Åïπë…ï–ÅÕïúÅù…ÖëŸ•ÃÅΩŸï»Å±ïπù…îÅ—•êÅ’—ï∏ÅÖπë…îÅÕÂµ¡—Ωµï»∞Åï»Åëï–ÅΩô—ïÕ–ÅâÖ…î)—ïù∏Å√îÅÖ–Åëï–Åï»Å√îÅ—•ëîÅµïêÅï∏Åπ‰ÅÕÂπÕ’πëï…œ·≠ï±Õî∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘9!$ÅÕ•∏ÅŸï•Ÿ•Õï»ÅôΩ»ÅÀ·ëîÉ·ÂπîÅ±•Õ—ï»ÅΩ¡¿Å≠Ωπ≠…ï—îÅŸÖ…Õï±—ïù∏Å’πëï»ÅΩŸï…Õ≠…•ô—ï∏É
≠Qïù∏Å√îÅÖ±ŸΩ…±•úÉ·ÂïÕÂ≠ëΩ∑
ÏÉäLÅ…ïë’Õï…–ÅÕÂ∏Åï»Åï—–ÅÖÿÅëï¥ËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩπ°§ππºΩÕÂµ¡—Ωµï»Ω•πôï≠Õ©Ωπï»Ω…Ωë–µΩÂîµŸï•Ÿ•Õï»àÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘Iïë’Õï…–ÅÕÂ∏∞Å±ÂÕÕ≠Â°ï–∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩπ°§ππºΩÕÂµ¡—Ωµï»Ω•πôï≠Õ©Ωπï»Ω…Ωë–µΩÂîµŸï•Ÿ•Õï»àÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘9!$∞ÅK·ë–É·ÂîÉäLÅŸï•Ÿ•Õï»ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Å”ï≠ï—îÅÕÂ∏ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»ÅôÖ…±•ú¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâMΩ¥Å…ïùï∞Å•≠≠îÉäLÅΩô—ïÕ–ÅÕ≠Â±ëïÃÅëï–Åï∏ÅÕ≠•——ï∏Åï±±ï»Åôï•±Ÿïπë–Å±•πÕî∏Å5ï∏Å≠Ωµµï»Åëï–Å¡±’—Õï±•úÅÕÖµµï∏ÅµïêÅÕµï…—î∞ÅÀ·ë°ï–Åï±±ï»Å±ÂÕõ·±ÕΩµ°ï–∞Åã·»Åë‘ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»Åï±±ï»Å±ïùîÅÕÖµµîÅëÖú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Åâ±•»Å±•πÕï∏ÅÕ≠•——ï∏ÅœîÅôΩ…–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâA…Ω—ï•∏ÅΩúÅôï—–Åô…ÑÅ”ï…ï€ôÕ≠ï∏Å±ïùùï»ÅÕïúÅπÖ—’…±•úÅ√îÅ±•πÕïΩŸï…ô±Ö—ï∏ÅΩŸï»Å—•ê∏ÅÖù±•πÕï»ÅâÂ——ïÃÅëï…ôΩ»Å°Ÿï»ÅëÖú∞ÅµïπÃÅ∑ïπïëÃ¥ÅΩúÅ’≠ï±•πÕï»Å—…ïπùï»Åù…’πë•úÅ…ïπù´·…•πúÅµïêÅ±•πÕï€ôÕ≠îÅ’πëï…Ÿï•Ã∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞(ÄÄÄÄâ…ΩëîµΩÂπîµΩúµÕŸ•îµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâ—•—±îàËÄâK·ëîÉ·ÂπîÅΩúÅÕŸ•îÅµïêÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅªï»Åã·»Åë‘ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»¸à∞(ÄÄÄÄÄÄÄÄâ’¡ëÖ—ïêàËÄà»¿»ÿ¥¿‡¥ƒ‹à∞(ÄÄÄÄÄÄÄÄâëïÕç…•¡—•Ω∏àËÄâYÖπ±•ùî∞Åµ•±ëï…îÉï…ÕÖ≠ï»Å—•∞ÅÀ·ëîÅΩúÅÕŸ•ïπëîÉ·ÂπîÅµïêÅ≠Ωπ—Ö≠—±•πÕï»∞ÅΩúÅëîÅŸÖ…Õï±—ïùπïπîÅÕΩ¥Åâï—Â»ÅÖ–Åë‘Åã·»ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»ÅÕÖµµîÅëÖú∏à∞(ÄÄÄÄÄÄÄÄââΩëÂ}°—µ∞àËÄààà(Ò¿˘1ï—–ÅÀ·ë°ï–ÅΩúÅÕŸ•îÅï»ÅùÖπÕ≠îÅŸÖπ±•úÅâ±Öπ–Å≠Ωπ—Ö≠—±•πÕïâ…’≠ï…îÅΩúÅÕΩ¥Å…ïùï∞Å’ôÖ…±•ú∏ÅMΩ¥)±•πÕïâ…’≠ï»Åï»Åëï–Å±•≠ïŸï∞Å±’…–ÉîÅ≠©ïππîÅ•ù©ï∏Åªï»ÅÕÂµ¡—ΩµïπîÅâï—Â»ÅÖ–Åë‘Åã·»Å°Öπë±îÅ…ÖÕ≠–∏Ω¿¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘YÖπ±•ùî∞Åµ•±ëï…îÉï…ÕÖ≠ï»Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘Ω»Å±ÖπúÅâ…’≠Õ—•êÅ§Å≥·¡ï–ÅÖÿÅëÖùï∏ÉäLÅï≠Õ¡ï…—ï»Åô…ÖÀïëï»Åùïπï…ï±–Åµï»Åïπ∏ÅçÑ∏Ä‡Å—•µï»ÅÕÖµµïπ°ïπùïπëîÅâ…’¨Ω±§¯(ÄÄÒ±§˘S·…–Å•ππï≠±•µÑÅï±±ï»Å±ÖπùîÅÕ≠©ï…∑·≠—ï»Ω±§¯(ÄÄÒ±§˘1ï—–Å•……•—ÖÕ©Ω∏Åô…ÑÅï∏ÅÖŸ±ï•…•πúÅ√îÅ±•πÕï≠Öπ—ï∏Ω±§¯(ÄÄÒ±§˘±±ï…ù§Ä°¡Ω±±ï∏∞ÅÕ”·ÿ§ÅÕΩ¥ÅôΩ…Õ—ï…≠ïÃÅÖÿÅ±•πÕïâ…’¨Ω±§¯(Ω’∞¯((Ò†»ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Ëù5’±•Õ†ú±ÕÖπÃµÕï…•òÌôΩπ–µÕ•ÈîËƒ∏¿’…ï¥ÌµÖ…ù•∏Ë»·¡‡Ä¿Äƒ¡¡‡Ïà˘!ŸÑÅë‘Åã·»Åù´·…îΩ†»¯(ÒΩ∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§ÌôΩπ–µÕ•ÈîË≈…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà¯(ÄÄÒ±§˘QÑÅÖÿÅ±•πÕï∏ÅµïêÅï∏ÅùÖπúÅë‘Å≠©ïππï»Å’âï°ÖúΩ±§¯(ÄÄÒ±§˘§É·Âï–Åï∏Å¡Ö’ÕîÉäLÅ•≠≠îÅÕï—–Å•π∏Åï∏Åπ‰Å±•πÕîÅÕÖµµîÅëÖúÅ°Ÿ•ÃÅ•……•—ÖÕ©Ωπï∏Å•≠≠îÅï»Å°ï±–ÅâΩ…—îΩ±§¯(ÄÄÒ±§˘	…’¨Åô’≠—ï…ëÀï¡ï»Åâï…ïùπï–ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»ÅΩ¥Åëï–Å°©ï±¡ï»∞ÅÕΩ¥(ÄÄÒÑÅ°…ïòÙàΩΩÂïë…Ö¡ï»ΩÕÂÕ—ÖπîΩÕÂÕ—Öπîµ’±—…Ñ¥ƒ¿µµ∞ºà˘MÂÕ—ÖπîÅU±—…ÑΩÑ¯Ω±§¯(ΩΩ∞¯((Òë•ÿÅÕ—Â±îÙââÖç≠ù…Ω’πêËç—‘ÌâΩ…ëï»Ë≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÌâΩ…ëï»µ…Öë•’ÃËƒ…¡‡Ì¡Öëë•πúËƒ—¡‡ÄƒŸ¡‡ÌµÖ…ù•∏ËƒŸ¡‡Ä¿ÌôΩπ–µÕ•ÈîË¿∏‡’…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏ÿÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÒÕ—…Ωπú˘=¡¡œ·¨ÅΩ¡—•≠ï»∞Å±ïùîÅï±±ï»Å±ïùïŸÖ≠–ÅÕÖµµîÅëÖúΩÕ—…Ωπú¯Å°Ÿ•ÃÅë‘Å§Å—•±±ïùúÅΩ¡¡±ïŸï»ÅÕµï…—î(°•≠≠îÅâÖ…îÅ’âï°Öú§∞Å≠…Öô—•úÅÀ·ë°ï–∞Å±ÂÕõ·±ÕΩµ°ï–∞ÅÕï≠…ï–∞Åï±±ï»Åõ·±ï±Õï∏ÅÖÿÅÖ–ÅπΩîÅôΩ…—ÕÖ—–)ï»Å§É·Âï–Åï——ï»ÅÖ–Å±•πÕï∏Åï»Å—Ö—–ÅÖÿ∏Åï——îÅ≠Ö∏Å€ô…îÅ—ïù∏Å√îÅï∏É·Âï•πôï≠Õ©Ω∏∞ÅÕΩ¥Å’âï°Öπë±ï–)≠Ö∏Åâ±§ÅÖ±ŸΩ…±•ú∏ÅQΩµµï±ô•πùï……ïùï±ï∏Åï»Åïπ≠ï∞ËÅï»Åë‘Å§Å—Ÿ•∞∞Å—ÑÅ±•πÕï∏Å’–∏(Ωë•ÿ¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà˘MΩÿÅÖ±ë…§ÅµïêÅ±•πÕï»ÅÕΩ¥Å•≠≠îÅï»ÅùΩë≠©ïπ–ÅôΩ»Åëï–∞Åâ…’¨ÅÖ±ë…§ÅÕ¡…•πùŸÖπ∏Åï±±ï»ÅÕ¡Â—–Å√î)ï∏Å±•πÕî∞ÅâÂ—–Å±•πÕïï—’•ï–Å°Ÿï…–ÄÃ∏Å∑ïπïê∞ÅΩúÅ°Ω±êÅëïúÅ—•∞ÅÖπâïôÖ±–ÅâÂ——ï•π—ï…ŸÖ±∞ÅôΩ»)±•πÕîÅΩúÅ€ôÕ≠îÉäLÅëï–Å…ïë’Õï…ï»Å…•Õ•≠Ωï∏ÅôΩ»ÅÖ–Åëï——îÅΩ¡¡Õ”ï»Å§Å’—ùÖπùÕ¡’π≠—ï–∏Ω¿¯((Ò¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‹Ïà˘%õ·±ùîÄÒÑÅ°…ïòÙâ°——¡ÃËºΩ››‹π°ï±ÕïπΩ…ùîππºΩÕÂ≠ëΩ¥ΩΩÂïÕÂ≠ëΩµµï»ΩΩÂï≠Ö—Ö…»ºàÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘!ï±ÕïπΩ…ùîΩÑ¯∞Åëï∏ÅΩôôïπ—±•ùîÅπΩ…Õ≠îÅ°ï±Õï¡Ω…—Ö±ï∏∞Åù©ï±ëï»Åõ·±ùïπëîÅÖπâïôÖ±•πúÅôΩ»Å≠Ωπ—Ö≠—±•πÕïâ…’≠ï…îÅµïêÅ—ïù∏Å√îÉ·Âï≠Ö—Ö…»ËΩ¿¯((Òâ±Ωç≠≈’Ω—îÅç•—îÙâ°——¡ÃËºΩ››‹π°ï±ÕïπΩ…ùîππºΩÕÂ≠ëΩ¥ΩΩÂïÕÂ≠ëΩµµï»ΩΩÂï≠Ö—Ö…»ºàÅÕ—Â±îÙââΩ…ëï»µ±ïô–ËÕ¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÌµÖ…ù•∏ËƒŸ¡‡Ä¿Ì¡Öëë•πúË—¡‡Ä¿Ä—¡‡ÄƒŸ¡‡ÌôΩπ–µÕ•ÈîË¿∏Â…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ë¿Ïà˘	…’≠ï»Åë‘Å≠Ωπ—Ö≠—±•πÕï»ÅΩúÅµï…≠ï»ÅÕÂµ¡—Ωµï»Å√îÉ·Âï≠Ö—Ö…»∞Åã·»Åë‘Å—ÑÅ’–Å≠Ωπ—Ö≠—±•πÕïπîÅΩúÅ…ÖÕ≠–ÅΩ¡¡œ·≠îÅ±ïùî∏Ω¿¯(ÄÄÒôΩΩ—ï»ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌµÖ…ù•∏µ—Ω¿ËŸ¡‡Ïà¯ôµëÖÕ†ÏÄÒç•—î¯ÒÑÅ°…ïòÙâ°——¡ÃËºΩ››‹π°ï±ÕïπΩ…ùîππºΩÕÂ≠ëΩ¥ΩΩÂïÕÂ≠ëΩµµï»ΩΩÂï≠Ö—Ö…»ºàÅ—Ö…ùï–Ùâ}â±Öπ¨àÅ…ï∞ÙâπΩΩ¡ïπï»à˘!ï±ÕïπΩ…ùî∞ÉaÂï≠Ö—Ö…»Ä°≠Ωπ©’π≠—•Ÿ•—–§ΩÑ¯Ωç•—î¯ΩôΩΩ—ï»¯(Ωâ±Ωç≠≈’Ω—î¯(ààà∞(ÄÄÄÄÄÄÄÄâôÖƒàËÅl(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅâÖ…îÅŸïπ—îÅ√îÅÖ–ÅÀ·ë°ï—ï∏Åüï»ÅΩŸï»¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâYïêÅµ•±ê∞Å≠Ω…—ŸÖ…•úÅÀ·ë°ï–Å’—ï∏ÅÕµï…—î∞Å©ÑÉäLÅ—ÑÅÖÿÅ±•πÕï∏ÅΩúÅù§É·Âï–Åï∏Å¡Ö’Õî∏ÅYïëŸÖ…ï»ÅÀ·ë°ï—ï∏Åµï»Åïπ∏Åï∏ÅëÖú∞Åï±±ï»Å≠Ωµµï»Åëï–ÅÕÖµµï∏ÅµïêÅÕµï…—î∞Å±ÂÕõ·±ÕΩµ°ï–Åï±±ï»ÅÕï≠…ï–∞Åã·»Åë‘ÅΩ¡¡œ·≠îÅΩ¡—•≠ï»Åï±±ï»Å±ïùîÅ§ÅÕ—ïëï–ÅôΩ»ÉîÅŸïπ—î∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å—ÖÃÅÀ·ë°ï–ÅµïêÅ≠Ωπ—Ö≠—±•πÕï»Åµï»ÅÖ±ŸΩ…±•úÅïπ∏ÅŸÖπ±•úÅÀ·ë°ï–Å§É·Âï–¸à∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâΩ…ë§Åï∏Å±•πÕîÅ§É·Âï–Å§ÅÕ©ï±ëπîÅ—•±ôï±±ï»Å≠Ö∏Åâ•ë…ÑÅ—•∞ÅâÖ≠—ï…•ï±±îÅ•πôï≠Õ©Ωπï»ÅÕΩ¥Å—…ïπùï»Å…ÖÕ¨Åâï°Öπë±•πú∏ÅîÅÖ±±ï»Åô±ïÕ—îÅ—•±ôï±±ï»Åï»Å’ôÖ…±•ùî∞Åµï∏Åëï–Åï»ÅŸï…ë–ÉîÅ≠©ïππîÅ•ù©ï∏ÅŸÖ…Õï±—ïùπïπîÅ—•ë±•ú∏à∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ∞(ÄÄÄÄÄÄÄÅt∞(ÄÄÄÅÙ∞)Ù(()ëïòÅ}…ïπëï…}ôÖ≈}â±Ωç¨°ôÖƒËÅ±•Õ—më•ç—t∞Å°ïÖë•πúËÅÕ—»ÄÙÄâ=ô—îÅÕ—•±—îÅÕ√·…Õ∑ï∞à§Ä¥¯Å—’¡±ïmÕ—»∞ÅÕ—…tË(ÄÄÄÄààâ	Âùùï»ÅãïëîÅÕÂπ±•úÅDµµÖ…≠’¿ÅΩúÅEAÖùîµÕç°ïµÑÅô…ÑÅÕÖµµîÅÌ≈’ïÕ—•Ω∏±ÖπÕ›ï…Ùµ±•Õ—î∞(ÄÄÄÅÕ±•¨ÅÖ–Å•ππ°Ω±êÅΩúÅÕ—…’≠—’…ï…–ÅëÖ—ÑÅÖ±ë…§Å≠Ö∏Å≠ΩµµîÅ’–ÅÖÿÅÕÂπ¨ÅµïêÅ°Ÿï…Öπë…î∏ààà(ÄÄÄÅ•òÅπΩ–ÅôÖƒË(ÄÄÄÄÄÄÄÅ…ï—’…∏Äàà∞Äàà(ÄÄÄÅ•—ïµÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏†(ÄÄÄÄÄÄÄÅòàààÒë•ÿÅç±ÖÕÃÙâôÖƒµ•—ï¥à¯(ÄÄÒ†Ã˘ÌïÕçÖ¡î°•—ïµlâ≈’ïÕ—•Ω∏ât•ÙΩ†Ã¯(ÄÄÒ¿˘ÌïÕçÖ¡î°•—ïµlâÖπÕ›ï»ât•ÙΩ¿¯(Ωë•ÿ¯ààà(ÄÄÄÄÄÄÄÅôΩ»Å•—ï¥Å•∏ÅôÖƒ(ÄÄÄÄ§(ÄÄÄÅôÖ≈}°—µ∞ÄÙÅòàààÒë•ÿÅç±ÖÕÃÙâôÖƒµÕïç—•Ω∏à¯(ÄÄÄÄÒ†»˘ÌïÕçÖ¡î°°ïÖë•πú•ÙΩ†»¯(ÄÄÄÅÌ•—ïµÕ}°—µ±Ù(ÄÄΩë•ÿ¯ààà(ÄÄÄÅôÖ≈}ïπ—•—•ïÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏ(ÄÄÄÄÄÄÄÄâ—Â¡îàËÄâE’ïÕ—•Ω∏à∞(ÄÄÄÄÄÄÄÄâπÖµîàËÄâÌïÕçÖ¡î°•—ïµlâ≈’ïÕ—•Ω∏ât•Ùà∞(ÄÄÄÄÄÄÄÄâÖççï¡—ïëπÕ›ï»àËÅÌÏâ—Â¡îàËÄâπÕ›ï»à∞Äâ—ï·–àËÄâÌïÕçÖ¡î°•—ïµlâÖπÕ›ï»ât•ÙâıÙ(ÄÄÄÄÄÅıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å•—ï¥Å•∏ÅôÖƒ(ÄÄÄÄ§(ÄÄÄÅôÖ≈}Õç°ïµÑÄÙÅòàààÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâEAÖùîà∞(ÄÄâµÖ•ππ—•—‰àËÅl(ÄÄÄÄÄÅÌôÖ≈}ïπ—•—•ïÕÙ(ÄÅt)ıÙΩÕç…•¡–¯ààà(ÄÄÄÅ…ï—’…∏ÅôÖ≈}°—µ∞∞ÅôÖ≈}Õç°ïµÑ(()ëïòÅ}…ïπëï…}ôÖ≈}ÖççΩ…ë•Ωπ}â±Ωç¨°ôÖƒËÅ±•Õ—më•ç—t∞Å°ïÖë•πúËÅÕ—»ÄÙÄâ=ô—îÅÕ—•±—îÅÕ√·…Õ∑ï∞à§Ä¥¯Å—’¡±ïmÕ—»∞ÅÕ—…tË(ÄÄÄÄààâMÖµµîÅÌ≈’ïÕ—•Ω∏±ÖπÕ›ï…Ùµ•ππëÖ—ÑÅΩúÅÕÖµµîÅEAÖùîµÕç°ïµÑÅÕΩ¥(ÄÄÄÅ}…ïπëï…}ôÖ≈}â±Ωç¨†§∞Åµï∏ÅŸ•Õ’ï±–Åï∏Å≠Ω±±Ö¡Õï–ÄÒëï—Ö•±Ã¯µÖççΩ…ë•Ω∏Å¡ï»(ÄÄÄÅÕ√·…Õ∑ï∞Ä°}ôÖ≈}ÖççΩ…ë•Ωπ}•—ï¥†§∞ÅÕÖµµîÅù©ïπâ…’≠—îÅ≠Ωµ¡Ωπïπ–ÅÕΩ¥(ÄÄÄÅÕï…•î¥Ωµï…≠îµÕ•ëïπîÅÕ•∏ÅD§Å§ÅÕ—ïëï–ÅôΩ»Åï∏ÅÖ±±—•êµÕÂπ±•úÅô±Ö–Å±•Õ—î∏(ÄÄÄÅ	…’≠–ÅÖÿÅ…ïπëï…}¡…Ωë’ç—}¡Öùî†§ÅÕ•∏ÅπÂîÄâ≠’ππÕ≠Ö¡ÕÕΩπîà(ÄÄÄÄ°A…Ωë’ç–Å5Ωâ•±îÅΩ±êÅM—ÖπëÖ…êÅÿƒ∞Ä»¿»ÿ¥¿‰¥»‹§Ä¥¥Å-U8Åëï»∞Å…ïÕ—ï∏ÅÖÿ(ÄÄÄÅÕ•ëïπîÅÕΩ¥Åâ…’≠ï»Å}…ïπëï…}ôÖ≈}â±Ωç¨†§Åï»Å’À·…–∏ààà(ÄÄÄÅ•òÅπΩ–ÅôÖƒË(ÄÄÄÄÄÄÄÅ…ï—’…∏Äàà∞Äàà(ÄÄÄÅ•—ïµÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°}ôÖ≈}ÖççΩ…ë•Ωπ}•—ï¥°•—ï¥§ÅôΩ»Å•—ï¥Å•∏ÅôÖƒ§(ÄÄÄÅôÖ≈}°—µ∞ÄÙÅòàààÒë•ÿÅç±ÖÕÃÙâôÖƒµÕïç—•Ω∏à¯(ÄÄÄÅÌ•—ïµÕ}°—µ±Ù(ÄÄΩë•ÿ¯ààà(ÄÄÄÅôÖ≈}ïπ—•—•ïÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏ(ÄÄÄÄÄÄÄÄâ—Â¡îàËÄâE’ïÕ—•Ω∏à∞(ÄÄÄÄÄÄÄÄâπÖµîàËÄâÌïÕçÖ¡î°•—ïµlâ≈’ïÕ—•Ω∏ât•Ùà∞(ÄÄÄÄÄÄÄÄâÖççï¡—ïëπÕ›ï»àËÅÌÏâ—Â¡îàËÄâπÕ›ï»à∞Äâ—ï·–àËÄâÌïÕçÖ¡î°•—ïµlâÖπÕ›ï»ât•ÙâıÙ(ÄÄÄÄÄÅıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å•—ï¥Å•∏ÅôÖƒ(ÄÄÄÄ§(ÄÄÄÅôÖ≈}Õç°ïµÑÄÙÅòàààÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâEAÖùîà∞(ÄÄâµÖ•ππ—•—‰àËÅl(ÄÄÄÄÄÅÌôÖ≈}ïπ—•—•ïÕÙ(ÄÅt)ıÙΩÕç…•¡–¯ààà(ÄÄÄÅ…ï—’…∏ÅôÖ≈}°—µ∞∞ÅôÖ≈}Õç°ïµÑ(()ëïòÅ}ôÖ≈}ÖççΩ…ë•Ωπ}•—ï¥°•—ï¥ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÅ…ï—’…∏ÅòúúúÒëï—Ö•±ÃÅç±ÖÕÃÙâôÖƒµÖççΩ…ë•Ω∏µ•—ï¥à¯(ÄÄÄÄÒÕ’µµÖ…‰˘ÌïÕçÖ¡î°•—ïµlâ≈’ïÕ—•Ω∏ât•ÙÒÕŸúÅç±ÖÕÃÙâôÖƒµç°ïŸ…Ω∏àÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Ò¡Ö—†ÅêÙâ4ÿÄÂ∞ÿÄÿÄÿ¥ÿàº¯ΩÕŸú¯ΩÕ’µµÖ…‰¯(ÄÄÄÄÒ¿˘ÌïÕçÖ¡î°•—ïµlâÖπÕ›ï»ât•ÙΩ¿¯(ÄÄΩëï—Ö•±Ã¯úúú(()ëïòÅ}…ïπëï…}ôÖµ•±Â}ôÖ≈}ÖççΩ…ë•Ω∏°çÖ—ïùΩ…•ÈïêËÅ±•Õ—m—’¡±ïmÕ—»∞Å±•Õ—më•ç—uut∞Å°ïÖë•πúËÅÕ—»§Ä¥¯Å—’¡±ïmÕ—»∞ÅÕ—…tË(ÄÄÄÄààâMï…•îµÕ•ëï∏ÅÕ•∏ÅDÄ†»¿»ÿ¥¿‰¥»‹§ËÅïùï∏∞ÅIUAAIPÄÒëï—Ö•±Ã¯µÖççΩ…ë•Ω∏Å§(ÄÄÄÅÕ—ïëï–ÅôΩ»Å}…ïπëï…}ôÖ≈}â±Ωç¨†§ùÃÅÖ±±—•êµÕÂπ±•ùîÅô±Ö—îÅ±•Õ—îÄ¥¥ÅÕî(ÄÄÄÅ…ïπëï…}ôÖµ•±Â}¡Öùî†§ÅÕ•∏Å…ïùï±µΩ—Ω»µ≠Ωµµïπ—Ö»ÅôΩ»Å°ŸΩ…ôΩ»Ä°ŸÖ…•Öâï±–(ÄÄÄÅÖπ—Ö±∞ÅÕ√·…Õ∑ï∞Å¡ï»ÅôÖµ•±•î∞ÅÖ±ë…§ÅôÂ±–Å’–Å—•∞Åï–ÅôÖÕ–ÅÖπ—Ö±∞§∏ÅMÖµµî(ÄÄÄÅ≠Ω±±Ö¡ÕïëîÄÒëï—Ö•±Ã¯µ∑·πÕ—ï»ÅÕΩ¥ÅÖ±±ï…ïëîÅï»ÅΩΩù±îµŸï…•ô•Õï…–Å§(ÄÄÄÅ…ïπëï…}›•ππï…}›•ëùï–†§ÅÕ•∏ÄâA…•ÃÅŸïêÅô±ï…îÅïÕ≠ï»àµ…Öê∏((ÄÄÄÅçÖ—ïùΩ…•ÈïêËÅ±•Õ—îÅÖÿÄ°≠Ö—ïùΩ…•πÖŸ∏∞ÅÕ√·…Õ∑ï∞µ±•Õ—î§Ä¥¥Å—ΩµµîÅ≠Ö—ïùΩ…•ï»(ÄÄÄÅ’—ï±Ö—ïÃÅ°ï±–Ä°ï∏ÅôÖµ•±•îÅ’—ï∏ÅÕ¡ïåµÕ√·…Õ∑ï∞ÅŸ•Õï»Å•πùï∏Å—Ω¥(ÄÄÄÄâM¡ïÕ•ô•≠ÖÕ©Ωπï»àµΩŸï…Õ≠…•ô–§∏ÅEAÖùîµÕç°ïµÑÅô±Ö—ïÃÅ’–Å√îÅ—Ÿï…ÃÅÖÿ(ÄÄÄÅ≠Ö—ïùΩ…•ïπîÄ°Õç°ïµÑπΩ…úÅ°Ö»Å•πùï∏Å≠Ö—ïùΩ…§µù…’¡¡ï…•πúÅôΩ»ÅEAÖùî§∞Åµï∏(ÄÄÄÅâÂùùïÃÅô…ÑÅ--UIPÅÕÖµµîÅÕ√·…Õ∑ï∞ΩÕŸÖ»ÅÕΩ¥ÅŸ•ÕïÃÄ¥¥Å•ππ°Ω±êÅΩú(ÄÄÄÅÕ—…’≠—’…ï…–ÅëÖ—ÑÅ≠Ö∏ÅëÑÅÖ±ë…§Å≠ΩµµîÅ’–ÅÖÿÅÕÂπ¨∏ààà(ÄÄÄÅÖ±±}•—ïµÃÄÙÅm•—ï¥ÅôΩ»Å|∞Å•—ïµÃÅ•∏ÅçÖ—ïùΩ…•ÈïêÅôΩ»Å•—ï¥Å•∏Å•—ïµÕt(ÄÄÄÅ•òÅπΩ–ÅÖ±±}•—ïµÃË(ÄÄÄÄÄÄÄÅ…ï—’…∏Äàà∞Äàà(ÄÄÄÅÕïç—•ΩπÕ}°—µ∞ÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúúÒë•ÿÅç±ÖÕÃÙâôÖƒµçÖ—ïùΩ…‰à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâôÖƒµçÖ—ïùΩ…‰µ±Öâï∞à˘ÌïÕçÖ¡î°çÖ—}±Öâï∞•ÙΩë•ÿ¯(ÄÄÄÅÏààπ©Ω•∏°}ôÖ≈}ÖççΩ…ë•Ωπ}•—ï¥°•—ï¥§ÅôΩ»Å•—ï¥Å•∏Å•—ïµÃ•Ù(ÄÄΩë•ÿ¯úúú(ÄÄÄÄÄÄÄÅôΩ»ÅçÖ—}±Öâï∞∞Å•—ïµÃÅ•∏ÅçÖ—ïùΩ…•ÈïêÅ•òÅ•—ïµÃ(ÄÄÄÄ§(ÄÄÄÅôÖ≈}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙâôÖƒµÕïç—•Ω∏à¯(ÄÄÄÄÒ†»˘ÌïÕçÖ¡î°°ïÖë•πú•ÙΩ†»¯(ÄÄÄÅÌÕïç—•ΩπÕ}°—µ±Ù(ÄÄΩë•ÿ¯úúú(ÄÄÄÅôÖ≈}ïπ—•—•ïÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏ(ÄÄÄÄÄÄÄÄâ—Â¡îàËÄâE’ïÕ—•Ω∏à∞(ÄÄÄÄÄÄÄÄâπÖµîàËÄâÌïÕçÖ¡î°•—ïµlâ≈’ïÕ—•Ω∏ât•Ùà∞(ÄÄÄÄÄÄÄÄâÖççï¡—ïëπÕ›ï»àËÅÌÏâ—Â¡îàËÄâπÕ›ï»à∞Äâ—ï·–àËÄâÌïÕçÖ¡î°•—ïµlâÖπÕ›ï»ât•ÙâıÙ(ÄÄÄÄÄÅıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å•—ï¥Å•∏ÅÖ±±}•—ïµÃ(ÄÄÄÄ§(ÄÄÄÅôÖ≈}Õç°ïµÑÄÙÅòúúúÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâEAÖùîà∞(ÄÄâµÖ•ππ—•—‰àËÅl(ÄÄÄÄÄÅÌôÖ≈}ïπ—•—•ïÕÙ(ÄÅt)ıÙΩÕç…•¡–¯úúú(ÄÄÄÅ…ï—’…∏ÅôÖ≈}°—µ∞∞ÅôÖ≈}Õç°ïµÑ(()!=5}DÄÙÅl(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏Åô’πùï…ï»Å-Ωπ—Ö≠—±•πÕï»ππº¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—î∏ÅY§Å°ïπ—ï»Å¡…•Õï»ÅÖ’—ΩµÖ—•Õ¨Åô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÅΩúÅΩ¡¡ëÖ—ï…ï»Åëï¥ÅëÖù±•ú∞ÅΩúÅŸ•Õï»Å—•±â’ëïπîÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏Å‘Å≠Ö∏ÅÕ≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅôΩ»ÉîÅÕîÅΩúÅÕΩ…—ï…îÅï——ï»Å—Ω—Ö±¡…•ÃÄ¥Å¡…Ωë’≠—¡…•ÃÅ¡±’ÕÃÅô…Ö≠–∏Å‘Å≠´·¡ï»Å•≠≠îÅ°ΩÃÅΩÕÃÏÅŸ§Å±ïπ≠ï»ÅëïúÅŸ•ëï…îÅ—•∞ÅôΩ…°Öπë±ï…ï∏Åë‘ÅŸï±ùï»∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-ΩÕ—ï»Åëï–Åµï»ÉîÅ≠´·¡îÅŸ•ÑÅï∏Å¡…•ÕÕÖµµïπ±•ùπ•πùÕÕ•ëî¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∏ÅA…•Õï∏Åë‘ÅÕï»Åï»ÅôΩ…°Öπë±ï…ïπÃÅïùï∏Å¡…•Ã∞ÅΩúÅë‘Åâï—Ö±ï»ÅÖ≠≠’…Ö–Åëï–ÅÕÖµµîÅÕΩ¥ÅΩ¥Åë‘Åù•≠¨Åë•…ï≠—îÅ—•∞Åπï——â’—•≠≠ï∏∏ÅY§Å≠Ö∏ÅµΩ——ÑÅ¡…ΩŸ•Õ©Ω∏Åô…ÑÅïπ≠ï±—îÅôΩ…°Öπë±ï…îÅªï»Åë‘Å°Öπë±ï»ÅŸ•ÑÅ±ïπ≠ïπîÅ€ï…î∞Åµï∏Åëï–Å√ïŸ•…≠ï»ÅŸï…≠ï∏Å¡…•Õï∏Åë‘Åâï—Ö±ï»Åï±±ï»Å°Ÿ•±≠ï–Å—•±â’êÅÕΩ¥ÅŸ•ÕïÃÅÕΩ¥Å±ÖŸïÕ–∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅΩô—îÅΩ¡¡ëÖ—ï…ïÃÅ¡…•Õïπî¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâY§ÅΩ¡¡ëÖ—ï…ï»Å¡…•ÕïπîÅô…ÑÅôΩ…°Öπë±ï…πîÅëÖù±•ú∏Å!Ÿï…–Å—•±â’êÅŸ•Õï»Åªï»Åëï–ÅÕ•Õ–Åâ±îÅ≠Ωπ—…Ω±±ï…–∞ÅΩúÅŸÖ…ï»ÅÕΩ¥ÅµÖπù±ï»Åâï≠…ïô—ï–Å±Öùï…Õ—Ö—’ÃÅ≠Ö∏Å•≠≠îÅŸ•ππîÅµï…≠ï–É
≠±ÖŸïÕ—îÅ¡…•œ
Ï∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ëÖ∏Å’ππüï»Å©ïúÅÕ≠©’±—îÅô…Ö≠—≠ΩÕ—πÖëï»¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâY§ÅÕΩ…—ï…ï»ÅÖ±±—•êÅ—•±â’ëïπîÅï——ï»Å—Ω—Ö∞Å¡…•ÃÄ¥Å¡…Ωë’≠—¡…•ÃÅ¡±’ÕÃÅô…Ö≠–Ä¥Å•≠≠îÅâÖ…îÅ¡…Ωë’≠—¡…•Õï∏ÅÖ±ïπî∏Å∏Åπï——â’—•≠¨ÅµïêÅ±ÖÿÅ¡…Ωë’≠—¡…•Ã∞Åµï∏Å£·Â–Åô…Ö≠—ùïâÂ»∞Å°ÖŸπï»Åëï…ôΩ»Å•≠≠îÅÖ’—ΩµÖ—•Õ¨É·Ÿï…Õ–∞ÅÕ±•¨Åëï∏Å≠Ö∏Åù´·…îÅΩ¥Åë‘ÅâÖ…îÅÕÖµµïπ±•ùπï»Å¡…Ωë’≠—¡…•Õï»Åë•…ï≠—îÅ√îÅôΩ…°Öπë±ï…πïÃÅïùπîÅÕ•ëï»∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»ÅëÖùÕ±•πÕï»Åï±±ï»Å∑ïπïëÕ±•πÕï»Åâ•±±•ùÕ–¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâï–Å≠Ωµµï»ÅÖ∏Å√îÅ±•πÕï—Â¡î∞Åµï…≠îÅΩúÅ°ŸΩ»ÅΩô—îÅë‘Åâ…’≠ï»Å±•πÕï»Ä¥Åëï–Åô•ππïÃÅ•≠≠îÅï—–ÅÕŸÖ»ÅÕΩ¥Åù©ï±ëï»ÅôΩ»ÅÖ±±î∏ÅMîÅ€ï»Åù’•ëîÅΩ¥Å∑ïπïëÕ±•πÕï»ÅŸÃ∏ÅëÖùÕ±•πÕï»∞ÅΩúÅâ…’¨Å≠Ö—ïùΩ…•ïπîÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅ—•∞ÉîÅÕÖµµïπ±•ùπîÅôÖ≠—•Õ≠îÅ¡…•Õï»ÅôΩ»ÅÖ≠≠’…Ö–Åëï∏ÅÕ—Â…≠ï∏ÅΩúÅ¡Ö≠π•πùÕÕ”·……ï±Õï∏Åë‘Å—…ïπùï»∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâMï±ùï»Åëï…îÅΩùœîÅ±•πÕï€ôÕ≠îÅΩúÉ·ÂïëÀï¡ï»¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∏Å$Å—•±±ïùúÅ—•∞Å≠Ωπ—Ö≠—±•πÕï»ÅÕÖµµïπ±•ùπï»ÅŸ§Å¡…•Õï»Å√îÅ±•πÕï€ôÕ≠îÅΩúÉ·ÂïëÀï¡ï»Åô…ÑÅëîÅÕÖµµîÅπΩ…Õ≠îÅπï——â’—•≠≠ïπî∞Åï——ï»ÅÕÖµµîÅ¡…•πÕ•¡¿ËÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∞ÅµïêÅµ’±•ù°ï–Å—•∞ÉîÅÕîÅ—Ω—Ö±¡…•ÃÅ•π≠±’ëï…–Åô…Ö≠–∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ…ôΩ»Å°Ö»ÅπΩï∏Å≠Ωπ—Ö≠—±•πÕï»Å—ºÅôΩ…Õ≠©ï±±•ùîÅπÖŸ∏¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ±ï…îÅΩ¡—•≠ï…≠©ïëï»ÅÕï±ùï»Å≠©ïπ—îÅ≠Ωπ—Ö≠—±•πÕï»Å’πëï»ÅÕ•—–Åïùï–ÅŸÖ…ïπÖŸ∏Ä¥ÅôΩ»Åï≠Õïµ¡ï∞ÅÕï±ùïÃÅ	•Ωô•π•—‰ÅΩùœîÅ’πëï»ÅπÖŸπï–É
≠•]ïÖ»Å=·Âùïª
Ï∏Åï–Åï»ÅÕÖµµîÅôÂÕ•Õ≠îÅ¡…Ωë’≠–∞ÅâÖ…îÅµïêÅï∏ÅÖππï∏ÅïµâÖ±±ÖÕ©îÅΩúÅπÖŸ∏∏ÅY§Å°Ö»Åï∏Åïùï∏ÅΩŸï…Õ•≠–ÅΩŸï»Åë•ÕÕîÅ≠Ωâ±•πùïπîÅ’πëï»Å=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ»Å-Ωπ—Ö≠—±•πÕï»ππºÅï∏Åπï——â’—•≠¨Åï±±ï»Åï–ÅÖ¡Ω—ï¨¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ9ï§∞Å-Ωπ—Ö≠—±•πÕï»ππºÅï»ÅŸï…≠ï∏Åï∏Åπï——â’—•≠¨Åï±±ï»Åï–ÅÖ¡Ω—ï¨Ä¥ÅŸ§Åï»Åï∏Å’ÖŸ°ïπù•úÅÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—îÅΩúÅÕï±ùï»Å•πùïπ—•πúÅÕï±ÿ∏Å-Ωπ—Ö≠—±•πÕï»Åï»Å…ïÕï¡—ŸÖ…î∞ÅœîÅÀïëõ·»ÅëïúÅÖ±±—•êÅµïêÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÅΩ¥Å…•≠—•úÅ±•πÕï—Â¡îÅΩúÅÕ—Â…≠îÅõ·»Å≠´·¿∏à∞(ÄÄÄÅÙ∞(ÄÄÄÅÏ(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ-Ö∏Å©ïúÅœ·≠îÅΩ¡¿Åï∏ÅÕ¡ïÕ•ô•≠¨Å±•πÕîÅë•…ï≠—î¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ)Ñ∞Åœ·≠ïôï±—ï–É·Ÿï…Õ–Å√îÅôΩ…Õ•ëï∏Å±Ö»ÅëïúÅœ·≠îÅï——ï»Å±•πÕïπÖŸ∏Åï±±ï»Åµï…≠îÅΩúÅüîÅ…ï—–Å—•∞Å¡…Ωë’≠—Õ•ëï∏ÅµïêÅù©ï±ëïπëîÅ¡…•Õï»Åô…ÑÅÖ±±îÅôΩ…°Öπë±ï…îÅŸ§Åõ·±ùï»∏à∞(ÄÄÄÅÙ∞)t(()ëïòÅ…ïπëï…}ù’•ëï}¡Öùî°Õ±’úËÅÕ—»§Ä¥¯ÅÕ—»ÅÅ9ΩπîË(ÄÄÄÅù’•ëîÄÙÅU%}=9Q9Pπùï–°Õ±’ú§(ÄÄÄÅ•òÅù’•ëîÅ•ÃÅ9ΩπîË(ÄÄÄÄÄÄÄÅ…ï—’…∏Å9Ωπî((ÄÄÄÅôÖ≈}°—µ∞∞ÅôÖ≈}Õç°ïµÑÄÙÅ}…ïπëï…}ôÖ≈}â±Ωç¨°ù’•ëîπùï–†âôÖƒà∞Åmt§§((ÄÄÄÅ’¡ëÖ—ïë}•ÕºÄÙÅù’•ëïlâ’¡ëÖ—ïêât(ÄÄÄÅ’¡ëÖ—ïë}ë•Õ¡±Ö‰ÄÙÅëÖ—ï—•µîπÕ—…¡—•µî°’¡ëÖ—ïë}•Õº∞Äàïd¥ï¥¥ïêà§πÕ—…ô—•µî†àïê∏ï¥∏ïdà§(ÄÄÄÅù’•ëï}’…∞ÄÙÅòâÌ	M}UI1ÙΩù’•ëîΩÌÕ±’ùÙºà(ÄÄÄÄåÅMÖµµîÅâ•±ëîÅÕΩ¥ÅŸ•ÕïÃÅ√îÅÕ•ëï∏Ä°ΩúÅù’•ëîµ≠Ω…—ï–§∞ÅÖâÕΩ±’—–ÅUI0∏ÅU—ï±Ö—ïÃ(ÄÄÄÄåÅ°Ÿ•ÃÅù’•ëï∏Å•≠≠îÅ°Ö»Åïùï–ÅôΩ—ºÄ¥¥ÅÖ±ë…§Åï∏Åùïπï…•Õ¨Å±ΩùºÅÕΩ¥ÅÖ…—•≠≠ï±â•±ëî∏(ÄÄÄÅù’•ëï}¡°Ω—Ω}’…∞ÄÙÅòâÌ	M}UI1ÙΩÕ—Ö—•åΩù’•ëïÃΩÌU%}A!=Q=MmÕ±’ùuÙπ›ïâ¿àÅ•òÅÕ±’úÅ•∏ÅU%}A!=Q=LÅï±ÕîÅ9Ωπî(ÄÄÄÅÖ…—•ç±ï}•µÖùï}±•πîÄÙÅòùq∏ÄÄâ•µÖùîàËÄâÌïÕçÖ¡î°ù’•ëï}¡°Ω—Ω}’…∞•Ùà∞úÅ•òÅù’•ëï}¡°Ω—Ω}’…∞Åï±ÕîÄàà(ÄÄÄÅÖ…—•ç±ï}Õç°ïµÑÄÙÅòàààÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâ…—•ç±îà∞(ÄÄâ°ïÖë±•πîàËÄâÌïÕçÖ¡î°ù’•ëïlâ—•—±îât•Ùà∞(ÄÄâëïÕç…•¡—•Ω∏àËÄâÌïÕçÖ¡î°ù’•ëïlâëïÕç…•¡—•Ω∏ât•Ùà±ÌÖ…—•ç±ï}•µÖùï}±•πïÙ(ÄÄâµÖ•ππ—•—Â=ôAÖùîàËÅÌÏâ—Â¡îàËÄâ]ïâAÖùîà∞Äâ•êàËÄâÌù’•ëï}’…±ÙâıÙ∞(ÄÄâÖ’—°Ω»àËÅÌÏâ—Â¡îàËÄâ=…ùÖπ•ÈÖ—•Ω∏à∞ÄâπÖµîàËÄâ-Ωπ—Ö≠—±•πÕï»ππºâıÙ∞(ÄÄâ¡’â±•Õ°ï»àËÅÌÏâ—Â¡îàËÄâ=…ùÖπ•ÈÖ—•Ω∏à∞ÄâπÖµîàËÄâ-Ωπ—Ö≠—±•πÕï»ππºâıÙ∞(ÄÄâëÖ—ïA’â±•Õ°ïêàËÄâÌ’¡ëÖ—ïë}•ÕΩÙà∞(ÄÄâëÖ—ï5Ωë•ô•ïêàËÄâÌ’¡ëÖ—ïë}•ÕΩÙà)ıÙΩÕç…•¡–¯ààà(ÄÄÄÄåÅ	…ïÖëç…’µâ1•Õ–ÄÙÅª·ÂÖ≠—•úÅëï∏ÅÕÂπ±•ùîÅâÀ·ëÕµ’±ï∏Å’πëï»Ä°!©ï¥Ä¯Åù’•ëï—•——ï∞§∞(ÄÄÄÄåÅ•πùï∏ÅΩ¡¡ë•≠—ï–Åµï±±Ωµπ•€î∏(ÄÄÄÅâ…ïÖëç…’µâ}Õç°ïµÑÄÙÅòàààÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞(ÄÄâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°ù’•ëïlâ—•—±îât•Ùà∞Äâ•—ï¥àËÄâÌù’•ëï}’…±ÙâıÙ(ÄÅt)ıÙΩÕç…•¡–¯ààà((ÄÄÄÄåÅ-Ωµ¡Ö≠–Åœ·≠ïâΩ≠ÃÅ…ï—–Åï——ï»Åõ·…Õ—îÅÖŸÕπ•—–Ä°Ö±±îÅù’•ëï»Éï¡πï»ÅµïêÅï–(ÄÄÄÄåÄÒ¿¯ÅÕΩ¥ÅÕŸÖ…ï»Å√îÅÕ√·…Õ∑ï±ï–§Ä¥¥ÅÕÂπ±•úÅ’—ï∏ÉîÅÕ≠ÂŸîÅÕŸÖ…ï–ÅâΩ…–ÏÅëï∏(ÄÄÄÄåÅô’±±îÅâΩ≠Õï∏ÅµïêÅÕπÖ…Ÿï•ï»Å±•ùùï»Åπïëï…Õ–∏(ÄÄÄÅâΩëÂ}›•—°}ç—ÑÄÙÅù’•ëïlââΩëÂ}°—µ∞âtπ…ï¡±Öçî†àΩ¿¯à∞ÄàΩ¿˘q∏ÄÄÄÄàÄ¨Å…ïπëï…}ù’•ëï}ÕïÖ…ç°}çÖ…ê°Õ±’ú∞ÅçΩµ¡Öç–ıQ…’î§∞Äƒ§((ÄÄÄÄåÅMÖµµîÅâ•±ëîÅÕΩ¥Åù’•ëîµ≠Ω…—ï–Ä°U%}A!=Q=L§Å√îÅÕï±ŸîÅÖ…—•≠≠ï±ï∏ÅΩùœîÄ¥¥(ÄÄÄÄåÅ-Ö§ÅÕ•—–Åï≠Õ¡±•Õ•——îÉ·πÕ≠îÄ»¿»ÿ¥¿‰¥»‹∏Å·…Õ—îÅôΩ…œ·¨ÅŸÖ»Åï–Åô’±±â…ïëëî(ÄÄÄÄåÅ—Ω¡¡â•±ëîÄ†ƒ‰¿¥»ÿ¡¡‡Å£·Â–§∞Åµï∏Å-Ö§Å√ï¡ï≠—îÅÕï±ÿÄ°µïêÅÕ≠©ï…µâ•±ëî§ÅÖ–(ÄÄÄÄåÅëï–Å—Ω¨Å’ª·ëŸïπë•úÅÕ—Ω»Å¡±ÖÕÃÅΩúÅÖ–Åï–ÅΩ¡¡Õ≠Ö±ï…–∞Å±•—–ÅµÂ≠–Åâ•±ëîÅâ±•»(ÄÄÄÄåÅ-MQIÅÕÂπ±•úÅ©ºÅÕ”·……îÅëï–ÅŸ•ÕïÃÄ¥¥ÅÕ¡’…—îÅ°ŸÑÅÕΩ¥Åï»ÄâπΩ…µÖ±–à∏(ÄÄÄÄåÅ3·Õπ•πùï∏Ä°ÕÖµµîÅëÖú§ËÅï–Å±•—î∞ÅÖŸ…’πëï–Å≠ŸÖë…Ö—•Õ¨Å—°’µâπÖ•∞ÅŸïêÅÕ•ëï∏(ÄÄÄÄåÅÖÿÅΩŸï…Õ≠…•ô—ï∏Ä°ù©ïπâ…’≠ï»Å¡…•πÕ•¡¡ï–Åô…ÑÄπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅ√î(ÄÄÄÄåÅ¡…Ωë’≠—Õ•ëïπîÄ¥¥Åâ•±ëî≠—ï≠Õ–ÅÕ•ëîÅΩ¥ÅÕ•ëî∞Å•≠≠îÅï–Åïùï–Åô’±±â…ïëëî(ÄÄÄÄåÅï±ïµïπ–§∞Å%--Åï–Åô’±±â…ïëëîÅâÖππï»∏Å	Ωπ’ÃËÅï∏Å9Õ≠Ö±ï…•πúÅô…Ñ(ÄÄÄÄåÄÿ–¡¡‡µ≠•±ëï∏Å—•∞Å¯‰¿¥ƒÃ¡¡‡ÅŸ•ÕïÃÅÕ≠Ö…¡–Ä°µΩ—ÕÖ—–ÅÖÿÅΩ¡¡Õ≠Ö±ï…•πú§∞(ÄÄÄÄåÅœîÅëï——îÅ≥·Õï»ÅµÂ≠°ï—Ãµ¡…Ωâ±ïµï–Å§ÅÕÖµµîÅÕ±ïπùï∏∏(ÄÄÄÅ¡°Ω—ºÄÙÅU%}A!=Q=Lπùï–°Õ±’ú§(ÄÄÄÅ°ï…Ω}—°’µâ}°—µ∞ÄÙÅòàààÒë•ÿÅç±ÖÕÃÙâù’•ëîµ°ï…ºµ—°’µàà¯(ÄÄÄÄÄÄÒ•µúÅÕ…åÙàΩÕ—Ö—•åΩù’•ëïÃΩÌïÕçÖ¡î°¡°Ω—º•Ùπ›ïâ¿àÅÖ±–ÙààÅ›•ë—†ÙàƒÃ¿àÅ°ï•ù°–ÙàƒÃ¿àÅ±ΩÖë•πúÙâïÖùï»àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄΩë•ÿ¯àààÅ•òÅ¡°Ω—ºÅï±ÕîÄàà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°ù’•ëïlâ—•—±îât•ÙÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°ù’•ëïlâëïÕç…•¡—•Ω∏ât•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩù’•ëîΩÌÕ±’ùÙºà¯)Ì}Ωù}µï—Ñ°òùÌù’•ëïlâ—•—±îâuÙÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Åù’•ëïlâëïÕç…•¡—•Ω∏ât∞ÅòùÌ	M}UI1ÙΩù’•ëîΩÌÕ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ)ÌôÖ≈}Õç°ïµÖÙ)ÌÖ…—•ç±ï}Õç°ïµÖÙ)Ìâ…ïÖëç…’µâ}Õç°ïµÖÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù(πù’•ëîµâÂ±•πîÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏ËÄ¥Ÿ¡‡Ä¿Ä¿ÏÅıÙ(πù’•ëîµ°ï…ºµ…Ω‹ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅùÖ¿ËÄƒŸ¡‡ÏÅıÙ(πù’•ëîµ°ï…ºµ—°’µàÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄÿ·¡‡ÏÅ°ï•ù°–ËÄÿ·¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πù’•ëîµ°ï…ºµ—°’µàÅ•µúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄÿ–¡¡‡§ÅÌÏÄπù’•ëîµ°ï…ºµ—°’µàÅÌÏÅ›•ë—†ËÄƒ¿¡¡‡ÏÅ°ï•ù°–ËÄƒ¿¡¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅıÙÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°ù’•ëïlâ—•—±îât•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰Åù’•ëîµ°ï…ºµ…Ω‹à¯(ÄÄÄÄÄÄÒë•ÿ¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘’•ëîΩë•ÿ¯(ÄÄÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°ù’•ëïlâ—•—±îât•ÙΩ†ƒ¯(ÄÄÄÄÄÄÄÄÒ¿Åç±ÖÕÃÙâù’•ëîµâÂ±•πîà˘-ŸÖ±•—ï—ÕÕ•≠…ï–ÅÖÿÅ-Ωπ—Ö≠—±•πÕï»ππºÉ
‹ÅM•Õ–ÅΩ¡¡ëÖ—ï…–ÅÌ’¡ëÖ—ïë}ë•Õ¡±ÖÂÙÉ
‹ÄÒÑÅ°…ïòÙàΩ…ïëÖ≠Õ©Ωπï±±îµ¡…•πÕ•¡¡ï»ºàÅÕ—Â±îÙâçΩ±Ω»È•π°ï…•–Ïà˘IïëÖ≠Õ©Ωπï±±îÅ¡…•πÕ•¡¡ï»ΩÑ¯Ω¿¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÅÌ°ï…Ω}—°’µâ}°—µ±Ù(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅÕ—Â±îÙâµÖ‡µ›•ë—†Ëÿ–¡¡‡Ïà¯(ÄÄÄÅÌâΩëÂ}›•—°}ç—ÖÙ(ÄÄÄÅÌôÖ≈}°—µ±Ù(ÄÄÄÅÌ…ïπëï…}ù’•ëï}ÕïÖ…ç°}çÖ…ê°Õ±’ú•Ù(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(((åÅ!Ÿï»Å•≠Ω∏Åï»Åï∏ÅôÂ±–∞Åô±Ö–Å•±±’Õ—…ÖÕ©Ω∏Ä°•≠≠îÅâÖ…îÅÕ—…ï¨§Å§É•∏ÅÖÿÅô•…î(åÅôÖÕ—îÅÖ≠Õïπ—ôÖ…ùï»Ä°…’±±ï…ï»ÅôΩ»ÅŸÖ…•ÖÕ©Ω∏∞ÅÕîÅU%}Q%1}MQe1ÅôΩ»(åÅôÖ…ùïëïô•π•Õ©Ωπïπî§Ä¥¥ÅâïŸ•ÕÕ–Åïùï∏µ—ïùπï–Å§ÅMY∞Å•≠≠îÅï∏Å≠Ω¡§ÅÖÿÅπΩî(åÅï≠Õ—ï…π–Å•≠ΩπÕï—–Ωâ•±ëî∏)U%}%=9LÄÙÅÏ(ÄÄÄÄâµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡Ùà–àÅ‰ÙàÿàÅ›•ë—†ÙàƒÿàÅ°ï•ù°–ÙàƒÃàÅ…‡ÙàÃàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒ‡àº¯Òç•…ç±îÅç‡Ùà‡àÅç‰Ùàƒ¿∏‘àÅ»Ùàƒ∏‹àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ¿∏‘àÅ»Ùàƒ∏‹àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡ÙàƒÿàÅç‰Ùàƒ¿∏‘àÅ»Ùàƒ∏‹àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùà‡àÅç‰Ùàƒ‘àÅ»Ùàƒ∏‹àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ‘àÅ»Ùàƒ∏‹àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡ÙàƒÿàÅç‰Ùàƒ‘àÅ»Ùàƒ∏‹àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄââ±’îà∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4»Äƒ…Ã–¥‹Äƒ¿¥‹Äƒ¿Ä‹Äƒ¿Ä‹¥–Ä‹¥ƒ¿Ä‹¥ƒ¿¥‹¥ƒ¿¥›ËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà–àÅô•±∞Ùâ›°•—îàº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µôΩ»µâÖ…∏àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùà‰àÅ»Ùà–∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4–Ä»≈å¿¥–∏–ÄÃ∏ÿ¥‡Ä‡¥·Ã‡ÄÃ∏ÿÄ‡Ä‡àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‘àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°Ö…ëîµï±±ï»µµÂ≠îµ±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùà‰àÅç‰Ùàƒ»àÅ»ÙàÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‹‘àº¯Òç•…ç±îÅç‡Ùàƒ‘àÅç‰Ùàƒ»àÅ»ÙàÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏–‘àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡Ùàƒ¿àÅ‰Ùà»àÅ›•ë—†Ùà–àÅ°ï•ù°–Ùàƒ»àÅ…‡Ùà»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òï±±•¡ÕîÅç‡Ùàƒ»àÅç‰Ùàƒ‡àÅ…‡Ùà‹àÅ…‰ÙàÃ∏ÃàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‘àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ôΩ»µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâ±ÖŸïπëï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùà‹àÅç‰ÙàƒÃàÅ»Ùà–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»∏–àº¯Òç•…ç±îÅç‡Ùàƒ‹àÅç‰ÙàƒÃàÅ»Ùà–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»∏–àº¯Ò¡Ö—†ÅêÙâ4ƒƒÄƒÕ†…4»∏‘Äƒ…∞ƒ¥Õ4»ƒ∏‘Äƒ…∞¥ƒ¥ÃàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»∏»àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâŸïë±•≠ï°Ω±êµÖÿµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄââ±’îà∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡ÙàÃàÅ‰Ùà‹àÅ›•ë—†Ùàƒ‡àÅ°ï•ù°–Ùàƒ»àÅ…‡Ùà–àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùà‡∏‘àÅç‰ÙàƒÃàÅ»Ùà»∏‘àÅô•±∞Ùâ›°•—îàº¯Òç•…ç±îÅç‡Ùàƒ‘∏‘àÅç‰ÙàƒÃàÅ»Ùà»∏‘àÅô•±∞Ùâ›°•—îàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ…ï•Õ•πúµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4ÃÄƒ…∞ƒ‡¥‡¥‡Äƒ‡¥»¥‡¥‡¥…ËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠ΩÕµï—•Õ≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ¿àÅç‰ÙàƒÃàÅ»Ùà‘∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4ƒ‡Ä—∞ƒ∏»Ä»∏–Ä»∏ÃÄƒ∏»¥»∏ÃÄƒ∏…0ƒ‡Äƒ≈∞¥ƒ∏»¥»∏»¥»∏Ã¥ƒ∏»Ä»∏Ã¥ƒ∏…ËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ÿàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïπÃµµÖ—ï…•Ö±îàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4ƒ»ÄÕÃÿ∏‘Ä‹∏‘Äÿ∏‘Äƒƒ∏’Ñÿ∏‘Äÿ∏‘Ä¿Ä¿Äƒ¥ƒÃÄ¡‘∏‘Äƒ¿∏‘Äƒ»ÄÃÄƒ»ÄÕËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ω……•ùï…ïπëîµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâ±ÖŸïπëï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‡∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ã»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà–∏»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡…Ωë’≠Õ©Ω∏µÖÿµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà–∏»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùà–àÅ»Ùàƒ∏ÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùà»¿àÅ»Ùàƒ∏ÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùà–àÅç‰Ùàƒ»àÅ»Ùàƒ∏ÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùà»¿àÅç‰Ùàƒ»àÅ»Ùàƒ∏ÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàÿ∏ÃàÅç‰Ùàÿ∏ÃàÅ»Ùàƒ∏–àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ‹∏‹àÅç‰Ùàƒ‹∏‹àÅ»Ùàƒ∏–àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàÿ∏ÃàÅç‰Ùàƒ‹∏‹àÅ»Ùàƒ∏–àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Òç•…ç±îÅç‡Ùàƒ‹∏‹àÅç‰Ùàÿ∏ÃàÅ»Ùàƒ∏–àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïπÃµ°•Õ—Ω…•îàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4ƒ»Ä›ÿ’∞Ã∏»Ä»àÅÕ—…Ω≠îÙâ›°•—îàÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ—ï…Ö¡ï’—•Õ≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4ƒ»Ä‹∏’ÿÂ4‹∏‘Äƒ…†‰àÅÕ—…Ω≠îÙâ›°•—îàÅÕ—…Ω≠îµ›•ë—†Ùà»∏»àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•ÕµîàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒï±±•¡ÕîÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ…‡Ùà‰àÅ…‰Ùà‘∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ÃàÅ—…ÖπÕôΩ…¥Ùâ…Ω—Ö—î†¥»¿Äƒ»Äƒ»§àº¯Òï±±•¡ÕîÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ…‡Ùà–∏‘àÅ…‰Ùà»∏‡àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅ—…ÖπÕôΩ…¥Ùâ…Ω—Ö—î†¥»¿Äƒ»Äƒ»§àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏»»àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏–‘àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÃàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µµÖ∏µÕΩŸîµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâ±ÖŸïπëï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4»¿Äƒ–∏’‡Ä‡Ä¿ÄƒÄƒÄ‰∏‘Ä—Ñÿ∏‘Äÿ∏‘Ä¿Ä¿Ä¿Äƒ¿∏‘Äƒ¿∏’ËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µµÖ∏µë’Õ©îµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4ƒ»ÄÕÃÿ∏‘Ä‹∏‘Äÿ∏‘Äƒƒ∏’Ñÿ∏‘Äÿ∏‘Ä¿Ä¿Äƒ¥ƒÃÄ¡‘∏‘Äƒ¿∏‘Äƒ»ÄÃÄƒ»ÄÕËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‡‘àº¯Ò¡Ö—†ÅêÙâ4–Ä»¡åƒ∏‘¥ƒÄ»∏‘¥ƒÄ–Ä¡Ã»∏‘ÄƒÄ–Ä¿Ä»∏‘¥ƒÄ–Ä¿Ä»∏‘ÄƒÄ–Ä¿àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µΩúµ—Ω……îµΩÂπîàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4»ÄƒÕÃ–¥ÿÄƒ¿¥ÿÄƒ¿ÄÿÄƒ¿Äÿ¥–Äÿ¥ƒ¿Äÿ¥ƒ¿¥ÿ¥ƒ¿¥ŸËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ã‘àº¯Ò¡Ö—†ÅêÙâ4ƒ»ÄÂÃ»∏ÿÄÃÄ»∏ÿÄ–∏ŸÑ»∏ÿÄ»∏ÿÄ¿ÄƒÄƒ¥‘∏»Ä¡‰∏–Äƒ»Äƒ»Ä‰Äƒ»ÄÂËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡Ùà‘àÅ‰ÙàÃàÅ›•ë—†Ùàƒ–àÅ°ï•ù°–Ùàƒ‡àÅ…‡Ùà»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒ‡àº¯Ò¡Ö—†ÅêÙâ4‡Ä·†·4‡Äƒ…†·4‡ÄƒŸ†‘àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄââåµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡ÙàÃàÅ‰Ùàƒ¿àÅ›•ë—†Ùàƒ‡àÅ°ï•ù°–Ùà–àÅ…‡ÙàƒàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏»‘àº¯Ò¡Ö—†ÅêÙâ4ÿÄƒ¡ÿ—4ƒ¿Äƒ¡ÿ—4ƒ–Äƒ¡ÿ—4ƒ‡Äƒ¡ÿ–àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏–àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâë•ÑµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàº¯Ò¡Ö—†ÅêÙâ4–Äƒ…†ƒÿàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡›»µÕ¡†µôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒ‡àº¯Ò¡Ö—†ÅêÙâ4‡Äƒ…†·4ƒ»Ä·ÿ‡àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâçÂ∞µôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒï±±•¡ÕîÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ…‡Ùà‰àÅ…‰Ùà‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ãàº¯Òï±±•¡ÕîÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ…‡Ùà‰àÅ…‰Ùà‘àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏–àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâÖ·•ÃµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâ±ÖŸïπëï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏–àÅΩ¡Öç•—‰Ùà¿∏–àº¯Ò¡Ö—†ÅêÙâ4ƒ»ÄÕÿƒ·4–∏‘Äÿ∏’∞ƒ‘ÄƒƒàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâÖëêµôΩ…≠±Ö…–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄââ±’îà∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒ‡àº¯Ò¡Ö—†ÅêÙâ4ƒ»Ä·ÿ·4‡Äƒ…†‡àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ»µ±ïπùîµ≠Ö∏µµÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄââ±’îà∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4ƒ»Ä‹∏’ÿ’∞ÃÄƒ∏‡àÅÕ—…Ω≠îÙâ›°•—îàÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâÕÖµµîµÕ—Â…≠îµâ…•±±ï»µΩúµ±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùà‹àÅç‰ÙàƒÃàÅ»ÙàÃ∏ÿàÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»∏»àº¯Òç•…ç±îÅç‡Ùàƒ‹àÅç‰ÙàƒÃàÅ»ÙàÃ∏ÿàÅÕ—…Ω≠îÙâπΩπîàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ã‘àº¯Ò¡Ö—†ÅêÙâ4ƒ¿∏ÿÄƒÕ†»∏·4»∏‡Äƒ…∞ƒ¥Õ4»ƒ∏»Äƒ…∞¥ƒ¥ÃàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà»àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸÑµ≠ΩÕ—ï»µ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒ‡àº¯Ò¡Ö—†ÅêÙâ4ƒ»Äÿ∏’ÿƒ≈4‰Ä‰∏…å¿¥ƒÄƒ¥ƒ∏‹ÄÃ¥ƒ∏›ÃÃÄ∏‡ÄÃÄƒ∏Âå¿Ä»∏ÿ¥ÿÄƒ∏»¥ÿÄÃ∏‡Ä¿Äƒ∏ƒÄƒ∏ÃÄƒ∏‰ÄÃÄƒ∏ÂÃÃ¥∏‹ÄÃ¥ƒ∏‹àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‘àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡Ö≠π•πùÕÕ—Ω……ï±Õî¥Ã¿µŸÃ¥‰¿àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡ÙàÃàÅ‰Ùà‡àÅ›•ë—†Ùà‹àÅ°ï•ù°–Ùàƒ¿àÅ…‡Ùàƒ∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ãàº¯Ò…ïç–Å‡Ùàƒ»àÅ‰Ùà‘àÅ›•ë—†Ùà‰àÅ°ï•ù°–ÙàƒÃàÅ…‡Ùàƒ∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ÿàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ¡…•Ãµ¡ï»µ±•πÕîµÕ±•¨µÕÖµµïπ±•ùπï»µë‘àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùà‰àÅç‰Ùà‰àÅ»Ùà‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ãàº¯Òç•…ç±îÅç‡Ùàƒ‘àÅç‰Ùàƒ‘àÅ»Ùà‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ÿàº¯Ò¡Ö—†ÅêÙâ4ƒ»Äƒ…†∏¿ƒàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùà¿àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ôΩ»µŸÖ…•ï…ï»µ¡…•Õïπîµµï±±Ω¥µâ’—•≠≠ïπîàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4–Äƒ·∞–¥ÿÄ–ÄÃÄ–¥‡Ä–Ä‘àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µ≠Ωπ—Ö≠—±•πÕï»µπºµâï…ïùπï»µ—Ω—Ö±¡…•ÃàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâ±ÖŸïπëï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡Ùà–àÅ‰Ùà‘àÅ›•ë—†ÙàƒÿàÅ°ï•ù°–Ùàƒ–àÅ…‡Ùà»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒÿàº¯Ò¡Ö—†ÅêÙâ4‡Äƒ¡†·4‡ÄƒÕ†·4‡ÄƒŸ†‘àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‘àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïÖâΩππïµïπ–µŸÃµ≠©Ω¡îµÕï±ÿàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄââ±’îà∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4ƒ‹Ä’Ñ‹Ä‹Ä¿ÄƒÄ¿ÄÃÄ‘∏ÃàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯Ò¡Ö—†ÅêÙâ4ƒ‹Ä…ÿ—†¥–àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ°ŸΩ…ëÖ∏µ≠©Ω¡îµ≠Ωπ—Ö≠—±•πÕï»µ¡Ñµπï—–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâµ•π–à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡Ùà–àÅ‰ÙàÃàÅ›•ë—†ÙàƒÿàÅ°ï•ù°–Ùàƒ‡àÅ…‡Ùà»àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàº¯Ò¡Ö—†ÅêÙâ4‡Ä·†·4‡Äƒ…†·4‡ÄƒŸ†–àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏–àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µµÖ∏µ≠©Ω¡îµ≠Ωπ—Ö≠—±•πÕï»µ’—ï∏µ…ïÕï¡–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ…ïç–Å‡Ùà‘àÅ‰ÙàÃàÅ›•ë—†Ùàƒ–àÅ°ï•ù°–Ùàƒ‡àÅ…‡Ùà»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒÿàº¯Ò¡Ö—†ÅêÙâ4‡Ä·†·4‡Äƒ…†‘àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯Òç•…ç±îÅç‡ÙàƒÿàÅç‰ÙàƒÿàÅ»Ùà–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàº¯Ò¡Ö—†ÅêÙâ4ƒÃ∏‘Äƒ‡∏’∞‘¥‘àÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ≠Ö∏µ©ïúµâÂ——îµ≠Ωπ—Ö≠—±•πÕïµï…≠îµÕï±ÿàËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4‹Ä›†ƒ¡∞¥Ã¥Õ4ƒ‹Äƒ› ›∞ÃÄÃàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅô•±∞ÙâπΩπîàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ±•πÕîµÕ•——ï»µôÖÕ–µ§µΩÂï–àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâçΩ…Ö∞à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒ¡Ö—†ÅêÙâ4»Äƒ…Ã–¥‹Äƒ¿¥‹Äƒ¿Ä‹Äƒ¿Ä‹¥–Ä‹¥ƒ¿Ä‹¥ƒ¿¥‹¥ƒ¿¥›ËàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‡‘àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÃ∏»àÅô•±∞Ùâ›°•—îàº¯Òç•…ç±îÅç‡Ùàƒ‡àÅç‰ÙàÿàÅ»Ùà–∏»àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò…ïç–Å‡Ùàƒ‹∏ÃàÅ‰ÙàÃ∏ÿàÅ›•ë—†Ùàƒ∏–àÅ°ï•ù°–ÙàÃ∏»àÅ…‡Ùà¿∏‹àÅô•±∞Ùâ›°•—îàº¯Òç•…ç±îÅç‡Ùàƒ‡àÅç‰Ùà‡∏»àÅ»Ùà¿∏‡àÅô•±∞Ùâ›°•—îàº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ’≠±Ö…–µÕÂ∏µµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÕ≠‰à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‰àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏ƒ‘àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÿàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏Ã‘àº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÃàÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯ú∞(ÄÄÄÅÙ∞(ÄÄÄÄâ…ΩëîµΩÂπîµΩúµÕŸ•îµµïêµ≠Ωπ—Ö≠—±•πÕï»àËÅÏ(ÄÄÄÄÄÄÄÄâçΩ±Ω»àËÄâÖµâï»à∞(ÄÄÄÄÄÄÄÄâÕŸúàËÄúÒç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùà‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4ƒ»ÄÕÿÕ4ƒ»Äƒ·ÿÕ4ÃÄƒ…†Õ4ƒ‡Äƒ…†Õ4‘∏ÿÄ‘∏Ÿ∞»∏ƒÄ»∏≈4ƒÿ∏ÃÄƒÿ∏Õ∞»∏ƒÄ»∏≈4ƒ‡∏–Ä‘∏Ÿ∞¥»∏ƒÄ»∏≈4‹∏‹Äƒÿ∏Õ∞¥»∏ƒÄ»∏ƒàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàº¯ú∞(ÄÄÄÅÙ∞)Ù((åÅ≠—îÅôΩ—ºÅôΩ»Å11Ä–¿Åù’•ëï»Ä†»¿»ÿ¥¿‰¥»‹∞Åô…ÑÅ-Ö§ÅÕ•—–Åâ•±ëï’—ŸÖ±úÄ¥¥(åÅâïÕØï…ï–Åô…ÑÅ—ºÅÕÖµµïπÕÖ——îÅ…ïôï…ÖπÕïâ•±ëï»Å°Ö∏ÅÕïπë—î∞Å%--Åùïπï…ï…–ÅÖÿ(åÅΩÕÃÄ¥¥Åô•±ïπîÅ≠Ω¥ÅÖ±ë…§ÅÕï¡Ö…Ö–∞ÅœîÅ…’—ïπï——ïπîÅâ±îÅâïÕØï…ï–Å¡…Ωù…ÖµµÖ—•Õ¨(åÅŸïêÉîÅô•ππîÅëîÅ°Ÿ•—îÅù’——ï»µ±•π©ïπîÅµï±±Ω¥Å…’—ïπî§∏Å•±πÖŸπï–Åï»ÅÖ±±—•ê(åÅÕ±’ùï∏ÅÕï±ÿÄ°Õ—Ö—•åΩù’•ëïÃΩÌÕ±’ùÙπ›ïâ¿§∞ÅœîÅëïππîÄâë•ç–µï∏àÅï»Å…ïï±–ÅÕï—–(åÅâÖ…îÅï∏Åï≠Õ•Õ—ïπÃµÕ©ï≠¨Ä¥¥Åâï°Ω±ë–ÅÕΩ¥Åë•ç–Ä°•≠≠îÅÕï–§Å§Å—•±ôï±±îÅï–Åâ•±ëî(åÅÕïπï…îÅ—…ïπùï»Åï–ÅÖππï–Åô•±πÖŸ∏Åïπ∏ÅÕ±’ùï∏∏Å·…Õ—îÄ»¿Åï»Å—Âëï±•ùî(åÅµΩ—•ÿµ—…ïôòÄ°Ö≠—•Ÿ•—ï–ΩÕ•—’ÖÕ©Ω∏ÅÕΩ¥ÅôÖ≠—•Õ¨ÅŸ•ÕïÃÅ§Åù’•ëï∏§ÏÅëîÅÕ•Õ—îÄ»¿(åÄ°Õ¡ïåµôΩ…≠±Ö…•πùï»∞Å¡…•ÃΩÖâΩππïµïπ–∞Å…ïÕï¡–∞Å°•Õ—Ω…•îΩ¡…Ωë’≠Õ©Ω∏§Åï»Åµï»(åÅùïπï…•Õ≠îÉ·Âî¥Ω±•πÕîµâ•±ëï»ÅŸÖ±ù–ÅôΩ»ÅÖ–Å-Ö§ÅÕ≠Ö∞ÅõîÅâ•±ëîÅ√îÅ11(åÅù’•ëîµ≠Ω…–∞Å•≠≠îÅôΩ…ë§ÅµΩ—•Ÿï–Å•±±’Õ—…ï…ï»ÅπΩîÅÕ¡ïÕ•ô•≠–Å§ÅÖ≠≠’…Ö–Åëï∏(åÅù’•ëï∏Ä¥¥Éô…±•úÅÕÖù–Å—•∞Å-Ö§∞ÅÕîÅ1Uπµê∏Å-•±ëïâ•±ëïπîÅï»Å≠’∏(åÄƒ‘ÃŸ‡ƒ¿»—¡‡ÅÕÖµµïπÕÖ—–ÅΩŸï»Äÿ¿Å…’—ï»∞ÅœîÅ°Ÿï»Å…’—îÅï»ÅâïÕØï…ï–Å—•∞ÅçÑ∏(åÄƒ–’‡ƒ‘¡¡‡ÅΩúÅΩ¡¡Õ≠Ö±ï…–Ä¥¥ÅùΩë≠©ïπ–ÅôΩ»Åï–Å±•—îÅ≠Ω…–¥Ω—Ω¡¡â•±ëî∞Åµï∏(åÅµï…≠âÖ…–ÅµÂ≠ï…îÅïπ∏Åï∏Åï≠—îÅ£·ÂΩ¡¡≥·Õ–ÅΩ…•ù•πÖ∞∏Å	Â—–Å’–ÅµïêÅÕ≠Ö…¡ï…î(åÅΩ…•ù•πÖ±ï»Å°Ÿ•ÃΩªï»Å-Ö§Åõï»Å—Ö¨Å§Åëï¥∏)U%}A!=Q=LÄÙÅÌÕ±’úËÅÕ±’úÅôΩ»ÅÕ±’úÅ•∏Ål(ÄÄÄÄâ°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ≠Ωπ—Ö≠—±•πÕï»µôΩ»µâÖ…∏à∞(ÄÄÄÄâ°Ö…ëîµï±±ï»µµÂ≠îµ±•πÕï»à∞Äâ°ŸΩ…ôΩ»µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»à∞ÄâŸïë±•≠ï°Ω±êµÖÿµ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄâ…ï•Õ•πúµµïêµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ≠ΩÕµï—•Õ≠îµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ≠Ωπ—Ö≠—±•πÕïπÃµµÖ—ï…•Ö±îà∞(ÄÄÄÄâ≠Ö∏µµÖ∏µÕΩŸîµµïêµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ≠Ö∏µµÖ∏µë’Õ©îµµïêµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ≠Ωπ—Ö≠—±•πÕï»µΩúµ—Ω……îµΩÂπîà∞(ÄÄÄÄâ°ŸΩ»µ±ïπùîµ≠Ö∏µµÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ¡Ö≠π•πùÕÕ—Ω……ï±Õî¥Ã¿µŸÃ¥‰¿à∞ÄâµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»à∞(ÄÄÄÄâµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ±•πÕîµÕ•——ï»µôÖÕ–µ§µΩÂï–à∞Äâ’≠±Ö…–µÕÂ∏µµïêµ≠Ωπ—Ö≠—±•πÕï»à∞(ÄÄÄÄâ…ΩëîµΩÂπîµΩúµÕŸ•îµµïêµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ°ŸΩ…ëÖ∏µ≠©Ω¡îµ≠Ωπ—Ö≠—±•πÕï»µ¡Ñµπï—–à∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•Õµîà∞Äâ≠Ω……•ùï…ïπëîµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ≠Ωπ—Ö≠—±•πÕïπÃµ°•Õ—Ω…•îà∞(ÄÄÄÄâ¡…Ωë’≠Õ©Ω∏µÖÿµ≠Ωπ—Ö≠—±•πÕï»à∞Äâ—ï…Ö¡ï’—•Õ≠îµ≠Ωπ—Ö≠—±•πÕï»à∞ÄâôΩ…Õ—Ñµ≠Ωπ—Ö≠—±•πÕï…ïÕï¡—ï∏à∞(ÄÄÄÄââåµôΩ…≠±Ö…–à∞Äâë•ÑµôΩ…≠±Ö…–à∞Äâ¡›»µÕ¡†µôΩ…≠±Ö…–à∞ÄâçÂ∞µôΩ…≠±Ö…–à∞ÄâÖ·•ÃµôΩ…≠±Ö…–à∞ÄâÖëêµôΩ…≠±Ö…–à∞(ÄÄÄÄâÕÖµµîµÕ—Â…≠îµâ…•±±ï»µΩúµ±•πÕï»à∞Äâ°ŸÑµ≠ΩÕ—ï»µ≠Ωπ—Ö≠—±•πÕï»à∞Äâ¡…•Ãµ¡ï»µ±•πÕîµÕ±•¨µÕÖµµïπ±•ùπï»µë‘à∞(ÄÄÄÄâ°ŸΩ…ôΩ»µŸÖ…•ï…ï»µ¡…•Õïπîµµï±±Ω¥µâ’—•≠≠ïπîà∞Äâ°ŸΩ…ëÖ∏µ≠Ωπ—Ö≠—±•πÕï»µπºµâï…ïùπï»µ—Ω—Ö±¡…•Ãà∞(ÄÄÄÄâ≠Ωπ—Ö≠—±•πÕïÖâΩππïµïπ–µŸÃµ≠©Ω¡îµÕï±ÿà∞Äâ≠Ö∏µµÖ∏µ≠©Ω¡îµ≠Ωπ—Ö≠—±•πÕï»µ’—ï∏µ…ïÕï¡–à∞(ÄÄÄÄâ≠Ö∏µ©ïúµâÂ——îµ≠Ωπ—Ö≠—±•πÕïµï…≠îµÕï±ÿà∞)uÙ((åÅï±–Åµï±±Ω¥ÄΩù’•ëï»ºµΩŸï…Õ•≠—ï∏ÅΩúÅôΩ…Õ•ëïπÃÅôΩ…£ïπëÕŸ•Õπ•πùÃµÕï≠Õ©Ω∏∞(åÅÕ±•¨ÅÖ–Åù’•ëîµ≠Ω…—ïπîÅÕï»Å•ëïπ—•Õ≠îÅ’–ÅâïùùîÅÕ—ïëï»Ä°ÕîÅ…ïπëï…}ù’•ëï}—•±î§∏(åÄπù’•ëîµ¡°Ω—ºµçÖ…ê®Åï»Å	Y%MMPÅï∏Å≠Ω¡§ÅÖÿÅÕÖµµîÅ≠±ÖÕÕïπÖŸ∏ΩMLÅÕΩ¥(åÅ…ïπëï…}ôÖµ•±Â}¡Öùî†§ÅÕ•∏Åïùï∏ÄâIï±ïŸÖπ—îÅù’•ëï»àµÕï≠Õ©Ω∏Åâ…’≠ï»Ä°•≠≠îÅëï±–(åÅŸ•ÑÅëïππîÅ≠ΩπÕ—Öπ—ï∏Åëï»∞ÅôΩ»ÉîÅ•≠≠îÅÀ·…îÅï∏ÅÖ±±ï…ïëîÅ’—ù•—–ÅÕï…•îµÕ•ëî¥(åÅ≠Ωµ¡Ωπïπ–§Ä¥¥ÅÕÖµµîÅŸ•Õ’ï±±îÅ≠Ω…–ÅâïùùîÅÕ—ïëï»∞Å—ºÅ≠•±ëïÕ—ïëï»Å§Å≠Ωëï∏∏)U%}Q%1}MQe1ÄÙÄààà(πù’•ëîµù…•êÅÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»ÏÅùÖ¿ËÄƒ—¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄ»—¡‡ÏÅÙ(πù’•ëîµ—•±îÅÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅ¡Öëë•πúËÄ»…¡‡Ä»¡¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅÙ(πù’•ëîµ—•±îÈ°ΩŸï»ÅÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅÙ(πù’•ëîµ—•±îµ•çΩ∏ÅÏÅ›•ë—†ËÄ‘Ÿ¡‡ÏÅ°ï•ù°–ËÄ‘Ÿ¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅµÖ…ù•∏ËÄ¿ÅÖ’—ºÄƒ—¡‡ÏÅÙ(πù’•ëîµ—•±îµ•çΩ∏ÅÕŸúÅÏÅ›•ë—†ËÄ»·¡‡ÏÅ°ï•ù°–ËÄ»·¡‡ÏÅÙ(πù’•ëîµ—•±îµ—•—±îÅÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ≈…ï¥ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄŸ¡‡ÏÅÙ(πù’•ëîµ—•±îµëïÕåÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅÙ(πù’•ëîµ—•±îµ±•π¨ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ…¡‡ÏÅÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄÿ–¡¡‡§ÅÏÄπù’•ëîµù…•êÅÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†»∞Ä≈ô»§ÏÅÙÅÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‰¿¡¡‡§ÅÏÄπù’•ëîµù…•êÅÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†–∞Ä≈ô»§ÏÅÙÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êÅÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏ƒ’Ã∞ÅâΩ‡µÕ°ÖëΩ‹Ä¿∏ƒ’ÃÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êÈ°ΩŸï»ÅÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¥…¡‡§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Äƒ¡¡‡Ä»—¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒ–§ÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ•µÖùîÅÏÅÖÕ¡ïç–µ…Ö—•ºËÄƒÿÄºÄ‰ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ•µÖùîÅ•µúÅÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµâΩë‰ÅÏÅ¡Öëë•πúËÄƒ—¡‡ÄƒŸ¡‡ÄƒŸ¡‡ÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ—•—±îÅÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ≈…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏Ã‘ÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµëïÕåÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅµÖ…ù•∏µ—Ω¿ËÄŸ¡‡ÏÅÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ±•π¨ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ…¡‡ÏÅÙ(ààà(()ëïòÅ…ïπëï…}ù’•ëï}—•±î°Õ±’úËÅÕ—»∞ÅúËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÅ¡°Ω—ºÄÙÅU%}A!=Q=Lπùï–°Õ±’ú§(ÄÄÄÅ•òÅ¡°Ω—ºË(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒÑÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êàÅ°…ïòÙàΩù’•ëîΩÌïÕçÖ¡î°Õ±’ú•Ùºà¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµ•µÖùîà¯(ÄÄÄÄÒ•µúÅÕ…åÙàΩÕ—Ö—•åΩù’•ëïÃΩÌïÕçÖ¡î°¡°Ω—º•Ùπ›ïâ¿àÅÖ±–ÙààÅ›•ë—†Ùàÿ–¿àÅ°ï•ù°–Ùàÿÿ»àÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµâΩë‰à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµ—•—±îà˘ÌïÕçÖ¡î°ùlâ—•—±îât•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµëïÕåà˘ÌïÕçÖ¡î°ùlâëïÕç…•¡—•Ω∏ât•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµ±•π¨à˘1ïÃÅù’•ëï∏ÉäHΩë•ÿ¯(ÄÄΩë•ÿ¯(ΩÑ¯ààà(ÄÄÄÅ•çΩ∏ÄÙÅU%}%=9Lπùï–°Õ±’ú∞ÅÏâçΩ±Ω»àËÄââ±’îà∞ÄâÕŸúàËÄàâÙ§(ÄÄÄÅçΩ±Ω»∞Å—•π–ÄÙÅòâŸÖ»†¥µÌ•çΩπlùçΩ±Ω»ùuÙ§à∞ÅòâŸÖ»†¥µÌ•çΩπlùçΩ±Ω»ùuÙµ—•π–§à(ÄÄÄÅ…ï—’…∏ÅòàààÒÑÅç±ÖÕÃÙâù’•ëîµ—•±îàÅ°…ïòÙàΩù’•ëîΩÌïÕçÖ¡î°Õ±’ú•Ùºà¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈÌ—•π—ÙÌçΩ±Ω»ÈÌçΩ±Ω…ÙÏà¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπlâÕŸúâuÙΩÕŸú¯Ωë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ—•±îµ—•—±îà˘ÌïÕçÖ¡î°ùlâ—•—±îât•ÙΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ—•±îµëïÕåà˘ÌïÕçÖ¡î°ùlâëïÕç…•¡—•Ω∏ât•ÙΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ—•±îµ±•π¨à˘1ïÃÅù’•ëï∏ÉäHΩë•ÿ¯(ΩÑ¯ààà(()ëïòÅ…ïπëï…}ù’•ëïÕ}•πëï·}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅçÖ…ëÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°…ïπëï…}ù’•ëï}—•±î°Õ±’ú∞Åú§ÅôΩ»ÅÕ±’ú∞ÅúÅ•∏ÅU%}=9Q9Pπ•—ïµÃ†§§((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘’•ëï»ÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–Ùâ’•ëï»ÅΩ¥Å≠Ωπ—Ö≠—±•πÕï»ËÅ°ŸΩ…ëÖ∏ÅŸï±ùîÅ…•≠—•úÅ—Â¡î∞Åâ…’¨ÅΩúÅŸïë±•≠ï°Ω±ê∞Å≠Ωπ—Ö≠—±•πÕï»ÅôΩ»ÅâÖ…∏∞ÅΩúÅµï»∏à¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩù’•ëï»ºà¯)Ì}Ωù}µï—Ñ†ù’•ëï»ÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Äù’•ëï»ÅΩ¥Å≠Ωπ—Ö≠—±•πÕï»ËÅ°ŸΩ…ëÖ∏ÅŸï±ùîÅ…•≠—•úÅ—Â¡î∞Åâ…’¨ÅΩúÅŸïë±•≠ï°Ω±ê∞Å≠Ωπ—Ö≠—±•πÕï»ÅôΩ»ÅâÖ…∏∞ÅΩúÅµï»∏ú∞Å	M}UI0Ä¨ÄúΩù’•ëï»ºú•Ù)Ì=9Q}1%9-MÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù)ÌU%}Q%1}MQe1Ù(º®ÅQΩ¡¡âÖππï»Ä†»¿»ÿ¥¿‰¥»‹∞Åô…ÑÅ-Ö§ÅÕ•—–Åâ•±ëï’—ŸÖ±úÄ¥¥Å≠’∏ÅÕï±ŸîÅôΩ—ΩÕ—…•¡ï∏∞(ÄÄÅ•πùï∏Å√ïÕ≠…ïŸï–Å—ï≠Õ–ΩµΩç≠’¿µU$§∏ÅQï≠Õ—ï∏Å±•ùùï»Å=ACÅÕï±ŸîÅâ•±ëï–Ä°-Ö§Ë(ÄÄÄâ±ïùúÅ—ï≠Õ—ï∏ÅΩ¡√îÅÕï±ŸîÅâ•±ëîÅ°ï»ÅœîÅâ±•»Åëï–Åô±Ω—–à§Ä¥¥Åï∏Å±ÂÃÅù…Öë•ïπ–(ÄÄÅô…ÑÅŸïπÕ—…îÄ°ëï»Å≠•±ëïâ•±ëï–ÅÖ±±ï…ïëîÅï»Å±ÂÕ–Ω’Õ≠Ö…¡–Å§ÅâÖ≠ù…’ππï∏∞ÅÕî(ÄÄÅâ•±ëï–ÅÕï±ÿ§ÅÕ•≠…ï»Å±ïÕâÖ»Å∑·…¨Å—ï≠Õ–Å’—ï∏ÉîÅ∑ï——îÅù©ï——îÅôÖ…ùï∏Å√îÅï–(ÄÄÅ’≠©ïπ–Åô…ïµ—•ë•úÅâÖππï»µâ•±ëî∏Å%--Åï∏ÅÕ•ëîµ¡Öπï∞ÅÕΩ¥ÅÕï…•îµ°ï…º(ÄÄÄ°≠•±ëïâ•±ëï–Åï»ÅôΩ»Å¡ÖπΩ…Öµ•Õ¨Ω—Âπ–Å—•∞Åëï–Ä¥¥ÅçÑ∏Ä–∞‰Ëƒ§∞ÅΩúÅ%--ÅÕ≠©’±–(ÄÄÅ√îÅµΩâ•∞ÅÕ±•¨ÅÕï…•îµ°ï…ºµµïë•ÑÅï»Ä¥¥Å-Ö§ÅŸ•±±îÅ°ÑÅâ•±ëï–ÅÕÂπ±•úÅΩŸï…Ö±–∏Ä®º(πù’•ëîµ°ï…ºÅÌÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅâΩ…ëï»µ…Öë•’ÃËÄ»¡¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄ»¡¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πù’•ëîµ°ï…ºÅ•µúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄ»Ã¡¡‡ÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅıÙ(πù’•ëîµ°ï…ºµΩŸï…±Ö‰ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ•πÕï–ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅ±•πïÖ»µù…Öë•ïπ–†ƒ¿¡ëïú∞ÄçôôòÄ¿î∞Å…ùâÑ†»‘‘∞»‘‘∞»‘‘∞¿∏‰Ã§Ä–»î∞Å…ùâÑ†»‘‘∞»‘‘∞»‘‘∞¿∏Ã‘§Äÿ‡î∞Å…ùâÑ†»‘‘∞»‘‘∞»‘‘∞¿§Ä‡‡î§ÏÅıÙ(πù’•ëîµ°ï…ºµçΩπ—ïπ–ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ•πÕï–ËÄ¿ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅ¡Öëë•πúËÄ»¡¡‡Ä»…¡‡ÏÅµÖ‡µ›•ë—†ËÄ‡»îÏÅıÙ(πù’•ëîµ°ï…ºµçΩπ—ïπ–Äπ≠•ç≠ï»ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(πù’•ëîµ°ï…ºµçΩπ—ïπ–Å†ƒÅÌÏÅµÖ…ù•∏ËÄŸ¡‡Ä¿Ä·¡‡ÏÅôΩπ–µÕ•ÈîËÅç±Öµ¿†ƒ∏Ã’…ï¥∞Ä‘∏’Ÿ‹∞Ä……ï¥§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ƒ‘ÏÅıÙ(πù’•ëîµ°ï…ºµçΩπ—ïπ–Å¿ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏Â…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅµÖ‡µ›•ë—†ËÄ–»¡¡‡ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄÿ–¡¡‡§ÅÌÏ(ÄÄπù’•ëîµ°ï…ºÅ•µúÅÌÏÅ°ï•ù°–ËÄ»‡¡¡‡ÏÅıÙ(ÄÄπù’•ëîµ°ï…ºµçΩπ—ïπ–ÅÌÏÅµÖ‡µ›•ë—†ËÄ‘‡îÏÅ¡Öëë•πúËÄ»·¡‡ÄÃŸ¡‡ÏÅıÙ)ıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§ÅÌÏ(ÄÄπù’•ëîµ°ï…ºÅ•µúÅÌÏÅ°ï•ù°–ËÄÃ–¡¡‡ÏÅıÙ(ÄÄπù’•ëîµ°ï…ºµçΩπ—ïπ–ÅÌÏÅµÖ‡µ›•ë—†ËÄ–ÿîÏÅ¡Öëë•πúËÄÃ…¡‡Ä–—¡‡ÏÅıÙ)ıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅ’•ëï»Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ°ï…ºà¯(ÄÄÄÄÒ¡•ç—’…î¯(ÄÄÄÄÄÄÒÕΩ’…çîÅ—Â¡îÙâ•µÖùîΩ›ïâ¿àÅÕ…çÕï–ÙàΩÕ—Ö—•åΩ°ï…ºΩù’•ëï»¥‘ÿ¿π›ïâ¿Ä‘ÿ¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩù’•ëï»¥‡–¿π›ïâ¿Ä‡–¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩù’•ëï»¥ƒƒ»¿π›ïâ¿Äƒƒ»¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩù’•ëï»¥ƒ‘Ãÿπ›ïâ¿Äƒ‘ÃŸ‹àÅÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ»¿¡¡‡§Äƒƒ»¡¡‡∞Ä‰…Ÿ‹à¯(ÄÄÄÄÄÄÒ•µúÅÕ…åÙàΩÕ—Ö—•åΩ°ï…ºΩù’•ëï»¥‡–¿π›ïâ¿àÅÖ±–ÙààÅ›•ë—†Ùàƒ‘ÃÿàÅ°ï•ù°–ÙàÃƒÿàÅ±ΩÖë•πúÙâïÖùï»àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄΩ¡•ç—’…î¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ°ï…ºµΩŸï…±Ö‰à¯Ωë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ°ï…ºµçΩπ—ïπ–à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘’•ëï»Ωë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘±–ÅΩ¥Å≠Ωπ—Ö≠—±•πÕï»ÉäLÅïπ≠ï±–ÅôΩ…≠±Ö…–Ω†ƒ¯(ÄÄÄÄÄÄÒ¿˘A…Ö≠—•Õ≠îÅÀïêÅÕΩ¥Å°©ï±¡ï»ÅëïúÉîÅ—ÑÅùΩëîÅŸÖ±ú∞Åâ…’≠îÅ±•πÕïπîÅ…•≠—•úÅΩúÅ—ÑÅŸÖ…îÅ√îÉ·ÂπïπîÅë•πî∏Ω¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµù…•êà¯(ÄÅÌçÖ…ëÕ}°—µ±Ù(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}ÖâΩ’—}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘=¥ÅΩÕÃÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–Ùâ=¥Å-Ωπ—Ö≠—±•πÕï»ππºËÅ°ŸÑÅŸ§Åù´·»∞Å°ŸΩ…ëÖ∏ÅŸ§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»∞ÅΩúÅ°ŸΩ…ëÖ∏ÅŸ§Å—©ïπï»Å¡ïπùï»∏à¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩΩ¥µΩÕÃºà¯)Ì}Ωù}µï—Ñ†ù=¥ÅΩÕÃÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Äù=¥Å-Ωπ—Ö≠—±•πÕï»ππºËÅ°ŸÑÅŸ§Åù´·»∞Å°ŸΩ…ëÖ∏ÅŸ§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»∞ÅΩúÅ°ŸΩ…ëÖ∏ÅŸ§Å—©ïπï»Å¡ïπùï»∏ú∞Å	M}UI0Ä¨ÄúΩΩ¥µΩÕÃºú•Ù)Ì=9Q}1%9-MÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù(πÖâΩ’–µâΩë‰Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅµÖ…ù•∏ËÄ»·¡‡Ä¿Äƒ¡¡‡ÏÅıÙ(πÖâΩ’–µâΩë‰Å¿ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿ‘ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅ=¥ÅΩÕÃΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘=¥ÅΩÕÃΩë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘=¥Å-Ωπ—Ö≠—±•πÕï»ππºΩ†ƒ¯(ÄÄÄÄÄÄÒ¿˘∏Å’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—îÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»Å§Å9Ω…ùî∏Ω¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâÖâΩ’–µâΩë‰àÅÕ—Â±îÙâµÖ‡µ›•ë—†Ëÿ–¡¡‡Ïà¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»Å≠ΩÕ—ï»ÅΩô—îÅÕ€ô…–Å’±•≠–Åô…ÑÅâ’—•≠¨Å—•∞Åâ’—•≠¨ÅôΩ»Åª·ÂÖ≠—•ú(ÄÄÄÅÕÖµµîÅŸÖ…îÄ¥ÅÕÖµµîÅµï…≠î∞ÅÕÖµµîÅÕ—Â…≠î∞ÅÕÖµµîÅ¡Ö≠π•πùÕÕ”·……ï±Õî∏ÅY§ÅÕÖµ±ï»(ÄÄÄÅ¡…•ÕïπîÅô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»Å√îÅï—–ÅÕ—ïê∞ÅÕ±•¨ÅÖ–Åë‘ÅÕ±•¡¡ï»ÉîÅÕ©ï≠≠î(ÄÄÄÅ—§ÅôΩ…Õ≠©ï±±•ùîÅπï——Õ•ëï»ÅôΩ»ÉîÅô•ππîÅâ•±±•ùÕ—îÅ—•±ù©ïπùï±•ùîÅ—•±â’ê∏Ω¿¯((ÄÄÄÄÒ†»˘!ŸΩ…ëÖ∏Åëï–Åô’πùï…ï»Ω†»¯(ÄÄÄÄÒ¿˘A…•ÕïπîÅ°ïπ—ïÃÅÖ’—ΩµÖ—•Õ¨Åô…ÑÅôΩ…°Öπë±ï…πîÅΩúÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∏ÅY§(ÄÄÄÅÕΩ…—ï…ï»Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∞ÅΩúÅë‘Å≠Ö∏ÅÕ≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅôΩ»ÉîÅÕîÅΩú(ÄÄÄÅÕΩ…—ï…îÅï——ï»Å—Ω—Ö±¡…•ÃÄ¥Åï–Å—•±â’êÅÕΩ¥Åï»(ÄÄÄÅ’—ÕΩ±ù–Å≠Ö∏ÅÖ±ë…§ÅŸ•ππîÄâ±ÖŸïÕ—îÅ¡…•Ãàµµï…≠ï–∞Å’ÖπÕï—–Å°ŸΩ»Å±ÖŸ–Å—Ö±±ï–(ÄÄÄÅï»∏Å!Ÿï…–Å—•±â’êÅŸ•Õï»Åªï»Åëï–ÅÕ•Õ–Åâ±îÅ≠Ωπ—…Ω±±ï…–∏Ω¿¯((ÄÄÄÄÒ†»˘!ŸΩ…ëÖ∏ÅŸ§Å—©ïπï»Å¡ïπùï»Ω†»¯(ÄÄÄÄÒ¿˘Y§Å≠Ö∏ÅµΩ——ÑÅ¡…ΩŸ•Õ©Ω∏Åô…ÑÅïπ≠ï±—îÅôΩ…°Öπë±ï…îÅªï»Åë‘Å°Öπë±ï»ÅŸ•Ñ(ÄÄÄÅ±ïπ≠ïπîÅ€ï…î∏Åï–Å√ïŸ•…≠ï»ÅÖ±ë…§Å¡…•Õï∏Åë‘Åâï—Ö±ï»∞ÅΩúÅëï–Å√ïŸ•…≠ï»ÅÖ±ë…§(ÄÄÄÅ…Öπùï…•πùï∏ÅÖÿÅ—•±â’êÄ¥Åëï∏Åõ·±ùï»ÅÖ±±—•êÅôÖ≠—•Õ¨Å¡…•ÃÄ°¡…Ωë’≠—¡…•Ã∞Åï±±ï»(ÄÄÄÅ—Ω—Ö±¡…•ÃÅªï»Åë‘ÅÕ≥ï»Å√îÅô…Ö≠–§∞Å•≠≠îÅ°Ÿï¥ÅŸ§Å°Ö»Åï∏ÅÖŸ—Ö±îÅµïê∏Ω¿¯((ÄÄÄÄÒ†»˘!ŸÑÅŸ§Å•≠≠îÅï»Ω†»¯(ÄÄÄÄÒ¿˘Y§ÅÕï±ùï»Å•≠≠îÅ≠Ωπ—Ö≠—±•πÕï»ÅÕï±ÿ∞ÅΩúÅë…•Ÿï»Å•≠≠îÅâ’—•≠¨∏ÅY§Åù•»Å°ï±±ï»(ÄÄÄÅ•≠≠îÅµïë•Õ•πÕ≠îÅÀïêËÅ≠Ωπ—Ö≠—±•πÕï»Åï»Å…ïÕï¡—ŸÖ…î∞ÅœîÅÀïëõ·»ÅëïúÅÖ±±—•êÅµïê(ÄÄÄÅΩ¡—•≠ï»ÅŸïêÅŸÖ±úÅÖÿÅ±•πÕï—Â¡îÅΩúÅÕ—Â…≠î∏Ω¿¯((ÄÄÄÄÒ†»˘!Ÿï¥Åë…•Ÿï»Å-Ωπ—Ö≠—±•πÕï»ππº¸Ω†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅë…•ŸïÃÅÕΩ¥Åï–ÅÕï±ŸÕ—ïπë•ú∞Å’ÖŸ°ïπù•úÅ¡…ΩÕ©ï≠–Ä¥Å•≠≠îÅÖÿ(ÄÄÄÅï∏ÅΩ¡—•≠ï…≠©ïëîÅï±±ï»Åï∏ÅÖÿÅôΩ…°Öπë±ï…πîÅŸ§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Åô…Ñ∏Å!Ö»Åë‘(ÄÄÄÅÕ√·…Õ∑ï∞ÅΩ¥Å°Ÿï¥ÅÕΩ¥ÅÕ”ï»ÅâÖ¨∞Å—ÑÅ≠Ωπ—Ö≠–Å√îÅîµ¡ΩÕ—ï∏Å’πëï»∏Ω¿¯((ÄÄÄÄÒ†»˘1ïÃÅµï»Ω†»¯(ÄÄÄÄÒ¿˘Y§Å¡À·Ÿï»ÉîÅ€ô…îÅµï»Éï¡πîÅΩ¥Å°ŸΩ…ëÖ∏Å—©ïπïÕ—ï∏ÅôÖ≠—•Õ¨Åô’πùï…ï»Åïπ∏Åëï–(ÄÄÄÅÕΩ¥Åï»ÅŸÖπ±•úÅôΩ»Åï∏Å¡…•ÕÕÖµµïπ±•ùπ•πùÕÕ•ëîËΩ¿¯(ÄÄÄÄÒ’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡ÌôΩπ–µÕ•ÈîË¿∏‰……ï¥Ì±•πîµ°ï•ù°–Ëƒ∏‰ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯(ÄÄÄÄÄÄÒ±§¯ÒÑÅ°…ïòÙàΩÕ±•¨µÕÖµµïπ±•ùπï»µŸ§µ¡…•Õï»ºà˘M±•¨ÅÕÖµµïπ±•ùπï»ÅŸ§Å¡…•Õï»ΩÑ¯Ω±§¯(ÄÄÄÄÄÄÒ±§¯ÒÑÅ°…ïòÙàΩÕ±•¨µµÖ—ç°ï»µŸ§µ¡…Ωë’≠—ï»ºà˘M±•¨ÅµÖ—ç°ï»ÅŸ§Å¡…Ωë’≠—ï»ΩÑ¯Ω±§¯(ÄÄÄÄÄÄÒ±§¯ÒÑÅ°…ïòÙàΩ…ïëÖ≠Õ©Ωπï±±îµ¡…•πÕ•¡¡ï»ºà˘IïëÖ≠Õ©Ωπï±±îÅ¡…•πÕ•¡¡ï»ΩÑ¯Ω±§¯(ÄÄÄÄÄÄÒ±§¯ÒÑÅ°…ïòÙàΩÖôô•±•Ö—îµΩúµô•πÖπÕ•ï…•πúºà˘ôô•±•Ö—îÅΩúÅô•πÖπÕ•ï…•πúΩÑ¯Ω±§¯(ÄÄÄÄÄÄÒ±§¯ÒÑÅ°…ïòÙàΩµï±êµôï•∞ºà˘5ï±êÅôï•∞ΩÑ¯Ω±§¯(ÄÄÄÄΩ’∞¯((ÄÄÄÄÒ†»˘-Ωπ—Ö≠–Ω†»¯(ÄÄÄÄÒ¿˘M√·…Õ∑ï∞∞Åôï•±µï±ë•πúÅï±±ï»Å—•¡ÃÅΩ¥Åï–Å—•±â’êÅÕΩ¥Å•≠≠îÅÕ—ïµµï»¸ÅMïπêÅΩÕÃ(ÄÄÄÅï∏Åîµ¡ΩÕ–Å√îÅÌ}çΩπ—Öç—}ïµÖ•±}±•π¨†•Ù∏Ω¿¯(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ}—…’Õ—}¡Öùî°Õ±’úËÅÕ—»∞Å—•—±îËÅÕ—»∞Å≠•ç≠ï»ËÅÕ—»∞Å±ïÖêËÅÕ—»∞ÅâΩëÂ}°—µ∞ËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâï±–ÅµÖ∞ÅôΩ»ÅëîÄ‘ÅπÂîÅ—•±±•–¥Ωµï—Ωë•≠≠Õ•ëïπîÄ¥¥ÅÕÖµµîÅÕ≠©ï±ï—–ÅÕΩ¥(ÄÄÄÅ…ïπëï…}¡…•ŸÖçÂ}¡Öùî†§Ω…ïπëï…}—ï…µÕ}¡Öùî†§Ä°Q=A	I}!Q50Ä¯ÅâÀ·ëÕµ’±îÄ¯Å°ï…º(ÄÄÄÄ¯Å•ππ°Ω±ëÕë•ÿÄ¯ÅôΩΩ—ï»§∞Åµï∏Å’—ï∏ÅπΩ‹µ¡Ö…Öµï—ï»ÅÕ•ëï∏Å•πùï∏ÅÖÿÅë•ÕÕî(ÄÄÄÅ—…ïπùï»Åï∏ÄâÕ•Õ–ÅΩ¡¡ëÖ—ï…–àµëÖ—ºÄ°Õ—Ö—•Õ¨Å¡…•πÕ•¡¿µ—ï≠Õ–∞Å•≠≠î(ÄÄÄÅ—•ëÕÕ—ïµ¡±ï–Å•ππ°Ω±êÅÕΩ¥Åù’•ëïπî§∏ààà(ÄÄÄÅô’±±}—•—±îÄÙÅòùÌ—•—±ïÙÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºú(ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°ô’±±}—•—±î•ÙΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°±ïÖê•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩÌÕ±’ùÙºà¯)Ì}Ωù}µï—Ñ°ô’±±}—•—±î∞Å±ïÖê∞ÅòùÌ	M}UI1ÙΩÌÕ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù(πÖâΩ’–µâΩë‰Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅµÖ…ù•∏ËÄ»·¡‡Ä¿Äƒ¡¡‡ÏÅıÙ(πÖâΩ’–µâΩë‰Å¿ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿ‘ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(πÖâΩ’–µâΩë‰Å±§ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‹ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÄÒÑÅ°…ïòÙàΩΩ¥µΩÕÃºà˘=¥ÅΩÕÃΩÑ¯ÉäËÅÌïÕçÖ¡î°—•—±î•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘ÌïÕçÖ¡î°≠•ç≠ï»•ÙΩë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°—•—±î•ÙΩ†ƒ¯(ÄÄÄÄÄÄÒ¿˘ÌïÕçÖ¡î°±ïÖê•ÙΩ¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâÖâΩ’–µâΩë‰àÅÕ—Â±îÙâµÖ‡µ›•ë—†Ëÿ–¡¡‡Ïà¯(ÄÄÄÅÌâΩëÂ}°—µ±Ù(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}¡…•ç•πù}µï—°ΩëΩ±ΩùÂ}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅâΩë‰ÄÙÄààà(Ò¿˘ï——îÅï»Åëï∏Åô’±±îÅŸï…Õ©Ωπï∏ÅÖÿÅµï—Ωë•≠¨µâΩ≠Õï∏Åë‘ÅÕï»Å√îÅ°Ÿï»Å¡…Ωë’≠—Õ•ëîÄ¥¥ÅÕÖµµî)ôï¥Å¡’π≠—ï»∞Å±•—–Åµï»Å’—ëÂ¡ï–∏Ω¿¯((Ò†»˘A…Ωë’≠—¡…•ÃΩ†»¯(Ò¿˘A…•Õï∏Åâ’—•≠≠ï∏ÅÕï±ÿÅΩ¡¡ù•»ÅôΩ»Å¡…Ωë’≠—ï–∞Å’—ï∏Åô…Ö≠–∏Åï——îÅï»Å—Ö±±ï–ÅÕΩ¥ÅŸ•ÕïÃ+·Ÿï…Õ–Å√îÅ°Ÿï…–Å—•±â’ëÕ≠Ω…–∏Ω¿¯((Ò†»˘…Ö≠–Ω†»¯(Ò¿˘…Ö≠—≠ΩÕ—πÖëï∏Åâï…ïùπïÃÅ’–Åô…ÑÅÖπ—Ö±±ï–ÅïÕ≠ï»Åë‘Å°Ö»ÅŸÖ±ù–∞ÅΩúÅ°Ÿï»Åâ’—•≠≠ÃÅïùï∏)ô…§µô…Ö≠–µù…ïπÕî∏Å-´·¡ï»Åë‘Åòπï≠Ã∏Ä»ÅïÕ≠ï»Å—•∞ÄÃ¿¿Å≠»ÅÕ—Â≠≠ï–Å°ΩÃÅï∏Åâ’—•≠¨ÅµïêÅù…Ö—•Ã)ô…Ö≠–ÅΩŸï»Ä‘¿¿Å≠»∞Åâ±•»Å—Ω—Ö±¡…•Õï∏Äÿ¿¿Å≠»Å’—ï∏Åô…Ö≠–Å±Öù–Å—•∞Ä¥¥Å≠´·¡ï»Åë‘ÅâÖ…îÄƒÅïÕ≠î(†Ã¿¿Å≠»∞Å’πëï»Åù…ïπÕï∏§∞Å≠Ωµµï»Åô…Ö≠—≠ΩÕ—πÖëï∏ÅµïêÅ§Å—Ω—Ö±ï∏∏Å…ïπÕïπîÅŸÖ…•ï…ï»ÅµÂî)µï±±Ω¥Åâ’—•≠≠ïπîÄ°πΩï∏Å°Ö»ÅÖ±±—•êÅù…Ö—•ÃÅô…Ö≠–∞É•∏Å°Ö»ÅÖ±ë…§Åù…Ö—•ÃÅô…Ö≠–Å’ÖπÕï—–)âï≥·¿§∞ÅœîÅ°Ÿï¥ÅÕΩ¥Åï»Åâ•±±•ùÕ–Å≠Ö∏Åïπë…îÅÕïúÅÖŸ°ïπù•úÅÖÿÅ°ŸΩ»ÅµÖπùîÅïÕ≠ï»Åë‘Å—…ïπùï»∏Ω¿¯((Ò†»˘QΩ—Ö±¡…•ÃΩ†»¯(Ò¿˘A…Ωë’≠—¡…•ÃÅµ’±—•¡±•Õï…–ÅµïêÅÖπ—Ö±∞∞Å¡±’ÕÃÅïŸïπ—’ï±∞Åô…Ö≠–ÅôΩ»ÅÖ≠≠’…Ö–Åëï–ÅÖπ—Ö±±ï–∏)ï——îÅï»Å—Ö±±ï–Åë‘ÅÕï»∞ÅΩúÅÕΩ¥ÅŸ§ÅÕΩ…—ï…ï»Åï——ï»∞Åªï»Åë‘ÅÕ≥ï»Å√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
Ï∏Ω¿¯((Ò†»˘MΩ…—ï…•πúÅΩúÄâ±ÖŸïÕ—îÅ¡…•ÃàΩ†»¯(Ò¿˘Q•±â’ëïπîÅÕΩ…—ï…ïÃÅï——ï»Å±ÖŸïÕ–Å¡…Ωë’≠—¡…•ÃÄ°’—ï∏Åô…Ö≠–§∏ÅM≥ï»Åë‘Å√îÉ
≠A…•ÃÅ•π≠±’ëï…–)ô…Ö≠”
Ï∞ÅÕΩ…—ï…ïÃÅëîÅï——ï»Å±ÖŸïÕ–Å—Ω—Ö±¡…•ÃÅ§ÅÕ—ïëï–∏Å–Å—•±â’êÅÕΩ¥Åï»Å’—ÕΩ±ù–∞Åï±±ï»)’—ï∏Åâï≠…ïô—ï–Å±Öùï…Õ—Ö—’Ã∞Å≠Ö∏ÅÖ±ë…§ÅŸ•ππîÄâ±ÖŸïÕ—îÅ¡…•Ãàµµï…≠ï–∞Å’ÖπÕï—–Å°ŸΩ»)±ÖŸ–Å—Ö±±ï–Åï»Ä¥¥Åëï–ÅŸ•ÕïÃÅôΩ…—ÕÖ—–Å§Å±•Õ—ï∏∞ÅâÖ…îÅ’—ï∏Åµï…≠ï–∏ÅYïêÅï≠ÕÖ≠–Å±•¨)¡…•ÃÅµï±±Ω¥Å—ºÅâ’—•≠≠ï»∞ÅÕî(ÒÑÅ°…ïòÙàΩÖôô•±•Ö—îµΩúµô•πÖπÕ•ï…•πúºà˘ôô•±•Ö—îÅΩúÅô•πÖπÕ•ï…•πúΩÑ¯ÅôΩ»Å°ŸΩ…ëÖ∏ÅŸ§ÅëÑ)ÖŸù´·»Å…ï≠≠ïõ·±ùï∏∏Ω¿¯((Ò†»˘-•±ëï»ÅΩúÅΩ¡¡ëÖ—ï…•πùÕô…ï≠ŸïπÃΩ†»¯(Ò¿˘A…•ÕïπîÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∞Åïπ—ï∏Åë•…ï≠—îÅô…ÑÅï∏ÅôΩ…°Öπë±ï…ÃÅïùï∏)¡…Ωë’≠—ôïïêÄ°ëï»ÅŸ§Å°Ö»Åï∏ÅÕ±•¨ÅÖŸ—Ö±î§Åï±±ï»ÅŸïêÉîÅ±ïÕîÅÖÿÅ¡…•Õï∏Å√îÅôΩ…°Öπë±ï…ïπÃ)ïùï∏Å¡…Ωë’≠—Õ•ëî∏Å!Ÿï…–Å—•±â’êÅŸ•Õï»Åªï»Åëï–ÅÕ•Õ–Åâ±îÅ≠Ωπ—…Ω±±ï…–∞ÅΩúÅï–Å¡…Ωë’≠–Å’—ï∏)ï∏Å√ï±•—ï±•úÅ¡…•ÃÅ¡’â±•Õï…ïÃÅ’—ï∏Å¡…•ÃÄ¥¥ÅŸ§Åù©ï——ï»ÅÖ±ë…§Åï∏Å¡…•Ã∏Ω¿¯(ààà(ÄÄÄÅ…ï—’…∏Å}—…’Õ—}¡Öùî†(ÄÄÄÄÄÄÄÄâÕ±•¨µÕÖµµïπ±•ùπï»µŸ§µ¡…•Õï»à∞(ÄÄÄÄÄÄÄÄâM±•¨ÅÕÖµµïπ±•ùπï»ÅŸ§Å¡…•Õï»à∞(ÄÄÄÄÄÄÄÄâ5ï—Ωë•≠¨à∞(ÄÄÄÄÄÄÄÄâ5ï—Ωë•≠≠ï∏ÅâÖ¨É
≠±ÖŸïÕ—îÅ¡…•œ
Ïµµï…≠ï–ÅΩúÅÕΩ…—ï…•πùï∏Åë‘ÅÕï»Å√îÅ°Ÿï»Å¡…Ωë’≠—Õ•ëî∏à∞(ÄÄÄÄÄÄÄÅâΩë‰∞(ÄÄÄÄ§(()ëïòÅ…ïπëï…}¡…Ωë’ç—}µÖ—ç°•πù}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅâΩë‰ÄÙÄààà(Ò¿˘–Å¡…Ωë’≠–Å√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»ÅÖ±±—•êÉ•∏ÅôÖÕ–∞Å•π—ï…∏Å•ëïπ—•—ï–Ä¥¥Å’ÖŸ°ïπù•úÅÖÿ)°Ÿ•±≠ï–ÅπÖŸ∏Åï∏Åâ’—•≠¨Åï±±ï»ÅΩ¡—•≠ï…≠©ïëîÅÕï±ùï»Åëï–Å’πëï»∞ÅΩúÅ’ÖŸ°ïπù•úÅÖÿÅÕï±Ÿî)πï——Öë…ïÕÕï∏Å—•∞Å¡…Ωë’≠—Õ•ëï∏∏Ω¿¯((Ò†»˘!ŸΩ…ëÖ∏Åï–Å—•±â’êÅ≠Ωâ±ïÃÅ—•∞Å…•≠—•úÅ¡…Ωë’≠–Ω†»¯(Ò¿˘;ï»ÅŸ§Å°ïπ—ï»Å¡…•Õï»Åô…ÑÅï∏ÅôΩ…°Öπë±ï…ÃÅ¡…Ωë’≠—ôïïê∞ÅµÖ—ç°ïÃÅ°Ÿï»Å…ÖêÅµΩ–Åï∏)µÖπ’ï±–ÅŸïë±•≠ï°Ω±ë–Å—Öâï±∞ÅµïêÅ≠©ïπ—îÅ¡…Ωë’≠—π’µ…îΩM-Tµï»∏Å∏Å…ÖêÅµïêÅï–Å’≠©ïπ–)¡…Ωë’≠—π’µµï»Åâ±•»ÄÒÕ—…Ωπú˘Ö±ë…§ΩÕ—…Ωπú¯Åù©ï——ï–Å•π∏Å√îÅï–Å¡…Ωë’≠–Åëï∏Å≠Ö∏Å±•ùπîÅ√îÄ¥¥)ëï∏Å°Ω¡¡ïÃÅΩŸï»ÅΩúÅ±ΩùùïÃ∞Å§ÅÕ—ïëï–ÅôΩ»ÉîÅ…•Õ•≠ï…îÉîÅŸ•ÕîÅôï•∞Å¡…•ÃÅ√îÅôï•∞ÅŸÖ…î∏Ω¿¯((Ò†»˘=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ïπÖŸ∏Ä°¡…•ŸÖ—îÅ±Öâï∞§Ω†»¯(Ò¿˘±ï…îÅΩ¡—•≠ï…≠©ïëï»ÅÕï±ùï»Å≠©ïπ—îÅ≠Ωπ—Ö≠—±•πÕï»Å’πëï»ÅÕ•—–Åïùï–ÅŸÖ…ïπÖŸ∏Ä¥¥)òπï≠Ã∏Åï»Åï∏Å±•πÕîÅÕΩ¥ÄâÂïDÄ»–àÅ°ΩÃÅMÂπÕÖ¥ÅôÖ≠—•Õ¨Å	•Ωô•π•—‰Åô…ÑÅΩΩ¡ï…Y•Õ•Ω∏∞ÅâÖ…îÅ§)ïùï∏Å•ππ¡Ö≠π•πú∏ÅY§Å≠Ωâ±ï»Å≠’∏Åë•ÕÕîÅ—ºÅÕÖµµï∏Åªï»Åëï–Åï»Åâï≠…ïô—ï–Åë•…ï≠—îÅµΩ–Åï∏)’ÖŸ°ïπù•úÅ≠•±ëîÅÕΩ¥Åï≠Õ¡±•Õ•—–ÅΩ¡¡ù•»Å°Ÿ•±≠ï–Å¡…Ωë’Õïπ—πÖŸ∏Åëï∏ÅÖ≠—’ï±±î)¡…•ŸÖ—îÅ±Öâï∞µ±•πÕï∏Å—•±ÕŸÖ…ï»Ä¥¥ÅŸ§Åù©ï——ï»ÅÖ±ë…§Åï∏Å≠Ωâ±•πúÅâÖÕï…–Å√îÅÖ–ÅπÖŸπïπî(â£·…ïÃÅ±•≠îÅ’–à∏Ω¿¯((Ò¿˘Y§Åâ…’≠ï»ÄÒÕ—…Ωπú˘•≠≠îΩÕ—…Ωπú¯ÅQ%8Ω8µ≠Ωëï»Å—•∞ÅëïππîÅµÖ—ç°•πùï∏Å§ÅëÖúÄ¥¥Åëï–Åï»)•≠≠îÅï–ÅëÖ—Öôï±–ÅŸ§Å°Ö»Å—•±ùÖπúÅ—•∞Åô…ÑÅôΩ…°Öπë±ï…πïÃÅôïïëÃ∏Å-Ωâ±•πùï∏ÅâÂùùï»Å§ÅÕ—ïëï–)√îÅ¡…Ωë’Õïπ—πÖŸ∏ÅΩúÅ¡…Ωë’≠—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»Åô…ÑÅ≠•±ëï∏ÅπïŸπ–ÅΩŸï»∏Ω¿¯((Òë•ÿÅÕ—Â±îÙââÖç≠ù…Ω’πêËç—‘ÌâΩ…ëï»Ë≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÌâΩ…ëï»µ…Öë•’ÃËƒ…¡‡Ì¡Öëë•πúËƒ—¡‡ÄƒŸ¡‡ÌµÖ…ù•∏ËƒŸ¡‡Ä¿ÌôΩπ–µÕ•ÈîË¿∏‡’…ï¥Ì±•πîµ°ï•ù°–Ëƒ∏ÿÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯)-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å•πùï∏ÅÖŸ—Ö±îÅµïêÅΩ¡—•≠ï…≠©ïëïπî∞ÅΩúÅ≠Ö∏Å•≠≠îÅùÖ…Öπ—ï…îÅÖ–Åï∏)¡…•ŸÖ—îÅ±Öâï∞µ≠Ωâ±•πúÅÕ—ïµµï»Å§ÅÖ±±îÅ—•±ôï±±ï»Ä¥¥Å¡Ö≠π•πùÕÕ”·……ï±ÕîÅï±±ï»Å—•±ù©ïπùï±•ùî)Õ—Â…≠ï»Å≠Ö∏Å§ÅÕ©ï±ëπîÅ—•±ôï±±ï»ÅÖŸŸ•≠î∏Å	ï≠…ïô–ÅÖ±±—•êÅµïêÅë•∏ÅΩ¡—•≠ï»Åï±±ï»)ÕÂπÕ…ïÕï¡–Åõ·»Åë‘ÅâÂ——ï»Å—•∞Åï–Å¡…Ωë’≠–Åë‘Å°Ö»Åô’ππï–ÅŸ•ÑÅï∏ÅÕ±•¨Å≠Ωâ±•πú∏(Ωë•ÿ¯((Ò¿˘MîÄÒÑÅ°…ïòÙàΩ¡…•ŸÖ—îµ±Öâï∞ºà˘ô’±∞ÅΩŸï…Õ•≠–ÅΩŸï»ÅΩ¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ΩÑ¯ÅŸ§)°Ö»Å≠Ωâ±ï–ÅœîÅ±Öπù–∏Ω¿¯(ààà(ÄÄÄÅ…ï—’…∏Å}—…’Õ—}¡Öùî†(ÄÄÄÄÄÄÄÄâÕ±•¨µµÖ—ç°ï»µŸ§µ¡…Ωë’≠—ï»à∞(ÄÄÄÄÄÄÄÄâM±•¨ÅµÖ—ç°ï»ÅŸ§Å¡…Ωë’≠—ï»à∞(ÄÄÄÄÄÄÄÄâ5ï—Ωë•≠¨à∞(ÄÄÄÄÄÄÄÄâ!ŸΩ…ëÖ∏ÅŸ§Å•ëïπ—•ô•Õï…ï»Å¡…Ωë’≠—ï»Å√îÅ—Ÿï…ÃÅÖÿÅôΩ…°Öπë±ï…î∞ÅΩúÅ°ŸΩ…ëÖ∏Å¡…•ŸÖ—îÅ±Öâï∞µ≠Ωâ±•πùï»ÅŸï…•ô•Õï…ïÃ∏à∞(ÄÄÄÄÄÄÄÅâΩë‰∞(ÄÄÄÄ§(()ëïòÅ…ïπëï…}ïë•—Ω…•Ö±}¡…•πç•¡±ïÕ}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅâΩë‰ÄÙÄààà(Ò¿˘’•ëïπîÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅï»ÅïùïπÕ≠…ïŸπî∞Å•≠≠îÅ≠Ω¡•ï…–Åô…ÑÅÖπë…îÅπï——Õ—ïëï»∏Ω¿¯((Ò†»˘-•±ëï»Ω†»¯(Ò¿˘ï»Åï∏Åù’•ëîÅΩ¡¡ù•»Åï–Å≠Ωπ≠…ï–ÅôÖ≠—Ö√ïÕ—ÖπêÅÕΩ¥Å•≠≠îÅï»ÅÖ±±µïπ–Å≠©ïπ–∞ÅôΩ…œ·≠ï»ÅŸ§Éî)Ÿ•ÕîÅ—•∞Åï∏ÅÖπï…≠©ïπ–Å≠•±ëîÄ¥¥Å—Â¡•Õ¨Å9Ω…Õ¨Å!ï±Õï•πôΩ…µÖ—•≠¨Ä°9!$§Åï±±ï»Å!ï±ÕïπΩ…ùî∞)µïêÅë•…ï≠—îÅÕ•—Ö–ÅΩúÅ±ïπ≠îÅ—•∞ÅΩ…•ù•πÖ±≠•±ëï∏∏Åïπï…ï±±î∞ÅùΩë–Åï—Öâ±ï…—îÅôÖ≠—ÑÄ°òπï≠Ã∏)°ŸΩ…ëÖ∏Åï–Å±•πÕïµÖ—ï…•Ö±îÅô’πùï…ï»§ÅÕ•—ï…ïÃÅ•≠≠îÅª·ëŸïπë•ùŸ•ÃÅ¡’π≠–ÅôΩ»Å¡’π≠–∞Åµï∏Åï»)≠…ÂÕÕ©ï≠≠ï–ÅµΩ–ÅΩôôïπ—±•úÅ¡…Ωë’Õïπ–¥ΩôÖù•πôΩ…µÖÕ©Ω∏Åõ·»Å¡’â±•Õï…•πú∏Ω¿¯((Ò†»˘%πùï∏Å•πë•Ÿ•ë’ï±±îÅµïë•Õ•πÕ≠îÅÀïêΩ†»¯(Ò¿˘’•ëïπîÅù•»Åùïπï…ï±∞Å•πôΩ…µÖÕ©Ω∏∞Å•≠≠îÅÀïêÅ—•±¡ÖÕÕï–Åë•∏Åïùï∏ÅÕ•—’ÖÕ©Ω∏∏)±–ÅÕΩ¥Å≠…ïŸï»Åï∏Å•πë•Ÿ•ë’ï±∞ÅŸ’…ëï…•πúÄ¥¥ÅŸÖ±úÅÖÿÅ±•πÕï—Â¡î∞ÅÕ—Â…≠î∞Åï±±ï»ÅΩ¥Åï–)ÕÂµ¡—Ω¥Åï»ÅπΩîÉîÅâï≠Âµ…îÅÕïúÅôΩ»Ä¥¥Å°ïπŸ•ÕïÃÅÖ±±—•êÅŸ•ëï…îÅ—•∞ÅΩ¡—•≠ï»Åï±±ï»+·Âï±ïùî∞ÅÖ±ë…§ÅâïÕŸÖ…–Åë•…ï≠—îÅ§Å—ï≠Õ—ï∏∏Ω¿¯((Ò†»˘=¡¡ëÖ—ï…•πúΩ†»¯(Ò¿˘!Ÿï»Åù’•ëîÅŸ•Õï»ÅëÖ—Ωï∏Åëï∏ÅÕ•Õ–Åâ±îÅΩ¡¡ëÖ—ï…–∏ÅÖ≠—Öôï•∞ÅŸ§Åâ±•»Åù©Ω…–)Ω¡¡µï…≠ÕΩ¥Å√îÅ…ï——ïÃÅôΩ…—≥·¡ïπëî∏Ω¿¯((Ò†»˘Öπ–Åë‘Åï∏Åôï•∞¸Ω†»¯(Ò¿˘MîÅπΩîÅÕΩ¥ÅŸ•…≠ï»ÅôÖ≠—•Õ¨Åôï•∞Å§Åï∏Åù’•ëî¸ÅY§ÅŸ•∞Åù©ï…πîÅ…ï——îÅëï–Ä¥¥(ÒÑÅ°…ïòÙàΩµï±êµôï•∞ºà˘µï±êÅô…ÑÅ°ï»ΩÑ¯∏Ω¿¯(ààà(ÄÄÄÅ…ï—’…∏Å}—…’Õ—}¡Öùî†(ÄÄÄÄÄÄÄÄâ…ïëÖ≠Õ©Ωπï±±îµ¡…•πÕ•¡¡ï»à∞(ÄÄÄÄÄÄÄÄâIïëÖ≠Õ©Ωπï±±îÅ¡…•πÕ•¡¡ï»à∞(ÄÄÄÄÄÄÄÄâ5ï—Ωë•≠¨à∞(ÄÄÄÄÄÄÄÄâ!ŸΩ…ëÖ∏Åù’•ëïπîÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅ±ÖùïÃ∞Å°Ÿ•±≠îÅ≠•±ëï»ÅŸ§Åâ…’≠ï»∞ÅΩúÅ°ŸΩ…ëÖ∏Åôï•∞Å…ï——ïÃ∏à∞(ÄÄÄÄÄÄÄÅâΩë‰∞(ÄÄÄÄ§(()ëïòÅ…ïπëï…}Öôô•±•Ö—ï}ë•Õç±ΩÕ’…ï}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅâΩë‰ÄÙÄààà(Ò¿˘-Ωπ—Ö≠—±•πÕï»ππºÅï»Åù…Ö—•ÃÉîÅâ…’≠î∏ÅM±•¨Åô•πÖπÕ•ï…ïÃÅ—©ïπïÕ—ï∏ËΩ¿¯((Ò†»˘!ŸΩ…ëÖ∏ÅŸ§Å—©ïπï»Å¡ïπùï»Ω†»¯(Ò¿˘Y§Å≠Ö∏ÅµΩ——ÑÅ¡…ΩŸ•Õ©Ω∏Åô…ÑÅïπ≠ï±—îÅôΩ…°Öπë±ï…îÅªï»Åë‘Å°Öπë±ï»ÅŸ•ÑÅï∏Å±ïπ≠îÅô…ÑÅΩÕÃ∞)ù©ïππΩ¥ÅŸÖπ±•ùîÅÖôô•±•Ö—îµπï——Ÿï…¨∏Åï——îÅ≠ΩÕ—ï»ÅëïúÅ•πùïπ—•πúÅï≠Õ—…ÑÄ¥¥Å¡…•Õï∏Åë‘)âï—Ö±ï»Å°ΩÃÅôΩ…°Öπë±ï…ï∏Åï»Åª·ÂÖ≠—•úÅëï∏ÅÕÖµµîÅÕΩ¥ÅΩ¥Åë‘Å°ÖëëîÅô’ππï–Åô…ï¥Åë•–ÅÕï±ÿ∏Ω¿¯((Ò†»˘CïŸ•…≠ï»Åëï–Å…Öπùï…•πùï∏¸Ω†»¯(Ò¿¯ÒÕ—…Ωπú˘9ï§∏ΩÕ—…Ωπú¯ÅQ•±â’êÅÕΩ…—ï…ïÃÅÖ±±—•êÅï——ï»ÅôÖ≠—•Õ¨Å¡…•ÃÄ°¡…Ωë’≠—¡…•Ã∞Åï±±ï»Å—Ω—Ö±¡…•ÃÅªï»Åë‘ÅÕ≥ï»Å√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
Ï§∞Å’ÖŸ°ïπù•úÅÖÿÅΩ¥)Ÿ§Å°Ö»Åï∏ÅÖŸ—Ö±îÅµïêÅôΩ…°Öπë±ï…ï∏Åï±±ï»Å•≠≠îÄ¥¥ÅÕî(ÒÑÅ°…ïòÙàΩÕ±•¨µÕÖµµïπ±•ùπï»µŸ§µ¡…•Õï»ºà˘M±•¨ÅÕÖµµïπ±•ùπï»ÅŸ§Å¡…•Õï»ΩÑ¯∏Åï–Åïπî)’ππ—Ö≠ï–ËÅŸïêÄÒï¥˘ï≠ÕÖ≠–Ωï¥¯Å±•¨Å¡…•ÃÅµï±±Ω¥Å—ºÅï±±ï»Åô±ï…îÅâ’—•≠≠ï»Ä°•πùï∏Å…ïï±∞)¡…•ÕôΩ…Õ≠©ï±∞ÅôΩ»ÅëïúÅÕΩ¥Å≠’πëî§Å≠Ö∏ÅŸ§Å¡…•Ω…•—ï…îÅï∏ÅôΩ…°Öπë±ï»ÅŸ§Å°Ö»Åï∏)Öôô•±•Ö—îµÖŸ—Ö±îÅµïêÅ§Å…ï≠≠ïõ·±ùï∏∏Å»Åëï–Åï∏Å…ïï±∞Å¡…•ÕôΩ…Õ≠©ï±∞∞Å’ÖπÕï—–Å°ŸΩ»Å±•—ï∏∞)Ÿ•ππï»ÅÖ±±—•êÅ±ÖŸïÕ—îÅ¡…•ÃÄ¥¥ÅÖŸ—Ö±îÅï±±ï»Åï§∏Ω¿¯((Ò†»˘…ï∞ÙâÕ¡ΩπÕΩ…ïêàÅΩúÅ…ï∞ÙâπΩôΩ±±Ω‹àΩ†»¯(Ò¿˘1ïπ≠ï»Å—•∞ÅôΩ…°Öπë±ï…îÅŸ§Å°Ö»Åï∏ÅÖôô•±•Ö—îµÖŸ—Ö±îÅµïêÅï»Åµï…≠ï–(ÒçΩëî˘…ï∞ÙâÕ¡ΩπÕΩ…ïêàΩçΩëî¯∞Å§Å—ÀïêÅµïêÅΩΩù±ïÃÅïùπîÅ…ï—π•πùÕ±•π©ï»ÅôΩ»Åâï—Ö±—îº)¡…ΩŸ•Õ©ΩπÕâÖÕï…—îÅ±ïπ≠ï»∏Å1ïπ≠ï»Å—•∞ÅôΩ…°Öπë±ï…îÅ’—ï∏ÅÖŸ—Ö±îÅï»Åµï…≠ï–(ÒçΩëî˘…ï∞ÙâπΩôΩ±±Ω‹àΩçΩëî¯∏ÅY§Åâ±Öπëï»ÅÖ±ë…§Åë•ÕÕîÅ—º∏Ω¿¯((Ò¿˘Ω»Å•πôΩ…µÖÕ©Ω∏ÅΩ¥ÅçΩΩ≠•ïÃÅΩúÅÕ¡Ω…•πúÅ≠πÂ——ï–Å—•∞ÅÖôô•±•Ö—îµπï——Ÿï…≠ïπî∞ÅÕî(ÒÑÅ°…ïòÙàΩ¡ï…ÕΩπŸï…∏ºà˘Aï…ÕΩπŸï…∏ÅΩúÅçΩΩ≠•ïÃΩÑ¯∏Ω¿¯(ààà(ÄÄÄÅ…ï—’…∏Å}—…’Õ—}¡Öùî†(ÄÄÄÄÄÄÄÄâÖôô•±•Ö—îµΩúµô•πÖπÕ•ï…•πúà∞(ÄÄÄÄÄÄÄÄâôô•±•Ö—îÅΩúÅô•πÖπÕ•ï…•πúà∞(ÄÄÄÄÄÄÄÄâ5ï—Ωë•≠¨à∞(ÄÄÄÄÄÄÄÄâ!ŸΩ…ëÖ∏Å-Ωπ—Ö≠—±•πÕï»ππºÅ—©ïπï»Å¡ïπùï»∞ÅΩúÅ°ŸΩ…ôΩ»Åëï–ÅÖ±ë…§Å√ïŸ•…≠ï»Å°Ÿ•±≠ï–Å—•±â’êÅÕΩ¥ÅŸ•ÕïÃÅÕΩ¥Åâ•±±•ùÕ–∏à∞(ÄÄÄÄÄÄÄÅâΩë‰∞(ÄÄÄÄ§(()ëïòÅ…ïπëï…}…ï¡Ω…—}ï……Ω…}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅâΩë‰ÄÙÅòààà(Ò¿˘!Ö»Åë‘ÅΩ¡¡ëÖùï–Åï∏Åôï•∞Å¡…•Ã∞Åï∏Åôï•∞Å¡…Ωë’≠—≠Ωâ±•πú∞Åï±±ï»ÅπΩîÅÖππï–ÅÕΩ¥Å•≠≠î)Õ—ïµµï»¸ÅY§ÅŸ•∞Åù©ï…πîÅ…ï——îÅëï–Ä¥¥Å©ºÅµï»Å¡…ïÕ•ÃÅµï±ë•πú∞Å©ºÅ…ÖÕ≠ï…îÅ≠Ö∏ÅŸ§Åô•ππî)ôï•±ï∏∏Ω¿¯((Ò†»˘Yï±úÅëï–ÅÕΩ¥Å¡ÖÕÕï»ÅâïÕ–Ω†»¯(Ò’∞ÅÕ—Â±îÙâ¡Öëë•πúµ±ïô–Ë»¡¡‡Ïà¯(ÄÄÒ±§˘Ì}µÖ•±—Ω}±•π¨†âï•∞Å¡…•Ãà∞Äâ5ï±êÅôï•∞Å¡…•ÃÉäHà•ÙΩ±§¯(ÄÄÒ±§˘Ì}µÖ•±—Ω}±•π¨†âï•∞Å¡…Ωë’≠—µÖ—ç°•πúà∞Äâ5ï±êÅôï•∞Å¡…Ωë’≠—µÖ—ç°•πúÄ°òπï≠Ã∏Å¡…•ŸÖ—îÅ±Öâï∞µ≠Ωâ±•πú§ÉäHà•ÙΩ±§¯(ÄÄÒ±§˘Ì}µÖ•±—Ω}±•π¨†âππï–à∞Äâ5ï±êÅπΩîÅÖππï–ÉäHà•ÙΩ±§¯(Ω’∞¯((Ò¿˘±±îÅ—…îÉï¡πï»Åîµ¡ΩÕ—¡…Ωù…Öµµï–Åë•—–ÅµïêÅï–Åôï…ë•úÅ’—ôÂ±–Åïµπïôï±–Å—•∞)Ì}çΩπ—Öç—}ïµÖ•±}±•π¨†•ÙÄ¥¥Å•π≠±’ëï»Åù©ï…πîÅ±ïπ≠ï∏Å—•∞ÅÕ•ëï∏Åëï–Åù©ï±ëï»∞ÅΩúÅ°Ÿ•±≠ï∏)â’—•≠¨Ω¡…•ÃÅëï–Åï»ÅÕπÖ≠¨ÅΩ¥∏Ω¿¯(ààà(ÄÄÄÅ…ï—’…∏Å}—…’Õ—}¡Öùî†(ÄÄÄÄÄÄÄÄâµï±êµôï•∞à∞(ÄÄÄÄÄÄÄÄâ5ï±êÅôï•∞à∞(ÄÄÄÄÄÄÄÄâ5ï±êÅôï•∞à∞(ÄÄÄÄÄÄÄÄâ’ππï–Åï∏Åôï•∞Å¡…•Ã∞Åôï•∞Å¡…Ωë’≠—≠Ωâ±•πúÅï±±ï»ÅπΩîÅÖππï–ÅÕΩ¥Å•≠≠îÅÕ—ïµµï»¸Å5ï±êÅô…ÑÅ°ï»∏à∞(ÄÄÄÄÄÄÄÅâΩë‰∞(ÄÄÄÄ§(()ëïòÅ…ïπëï…|–¿—}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâ•—!’àÅAÖùïÃÅÕï…Ÿï…ï»ÅëïππîÅÖ’—ΩµÖ—•Õ¨ÅµïêÅôÖ≠—•Õ¨Å!QQ@Ä–¿–µÕ—Ö—’ÃÅôΩ»(ÄÄÄÅïπ°Ÿï»ÅµÖπù±ïπëîÅÕ—§Ä¥ÅÕîÅùïπï…Ö—ï}¡ÖùïÃπ¡‰Ä°Õ≠…•ŸïÃÅ—•∞Åâ’•±êº–¿–π°—µ∞∞(ÄÄÄÅ…Ω–µπ•€î∞Å•≠≠îÅï∏Å’πëï…µÖ¡¡î§∏ÅπΩ•πëï‡Å§Å—•±±ïùú∞ÅÕΩ¥Åï∏Åï≠Õ—…ÑÅÕ•≠…•πú(ÄÄÄÅ°Ÿ•ÃÅÕ•ëï∏ÅπΩïπÕ•ππîÅÕ≠’±±îÅâ±§Å±ïπ≠ï–Å—•∞Åï±±ï»Åç…Ö›±ï–Åë•…ï≠—î∏((ÄÄÄÅ-´·…ï»ÅΩùœîÅï∏Å≠±•ïπ—Õ•ëïŸ•ÃÅΩ¡¡Õ±ÖúÅµΩ–Å1e}I%IQLÅ°ï±–É·Ÿï…Õ–Å§(ÄÄÄÄÒ°ïÖê¯Ä°õ·»ÅπΩîÅÖππï–§∞ÅôΩ»ÅëîÄ»Ã‹ÅùÖµ±îÄπÖÕ¡‡µUI0µïπîÅô…ÑÅôΩ……•ùî(ÄÄÄÅŸï…Õ©Ω∏ÅÖÿÅÕ•ëï∏Ä¥ÄπÖÕ¡‡Å≠Ö∏Å•≠≠îÅÕï…Ÿï…ïÃÅÕΩ¥Åï∏Åô’πùï…ïπëîÅ!Q50¥(ÄÄÄÅΩµë•…•ùï…•πúÅ√îÅ•—!’àÅAÖùïÃÄ°ÕîÅ≠Ωµµïπ—Ö»ÅŸïêÅ1e}I%IQL§∞Åœî(ÄÄÄÅëï——îÅï»Åï∏ÅâïŸ•ÕÕ–ÅπïÕ–µâïÕ–Å≥·Õπ•πúËÅâ…Ω›Õï»ÅµΩ——Ö»Ä–¿–∞Åµï∏Åï≠—î(ÄÄÄÅâïœ·≠ïπëîÅÕïπëïÃÅ±•≠ïŸï∞ÅŸ•ëï…îÅ§ÅÕ—ïëï–ÅôΩ»ÉîÅ—…ïôôîÅï∏Åâ±•πëŸï§∏Å%--(ÄÄÄÅï–ÅÕ’âÕ—•—’—–ÅôΩ»Åï∏Åï≠—îÄÃ¿ƒÅM<µµïÕÕ•úÄ¥ÅÕîÅ1Uπµê∏ààà(ÄÄÄÅçÖ—ïùΩ…Â}±•π≠ÃÄÙÄâq∏ÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúÒÑÅ°…ïòÙàΩ≠Ωπ—Ö≠—±•πÕï»ΩÌÕ±’ùÙºàÅç±ÖÕÃÙâπΩ–µôΩ’πêµ±•π¨à˘ÌïÕçÖ¡î°±Öâï∞•ÙΩÑ¯úÅôΩ»ÅÕ±’ú∞Å±Öâï∞Å•∏Å==QI}Q=I%L(ÄÄÄÄ§(ÄÄÄÅ±ïùÖçÂ}…ïë•…ïç—}Õç…•¡–ÄÙÅòàààÒÕç…•¡–¯(°ô’πç—•Ω∏Ä†§ÅÌÏ(ÄÅŸÖ»Å±ïùÖçÂIïë•…ïç—ÃÄÙÅÌ©ÕΩ∏πë’µ¡Ã°1e}I%IQL•ÙÏ(ÄÅŸÖ»Å—Ö…ùï–ÄÙÅ±ïùÖçÂIïë•…ïç—Õm±ΩçÖ—•Ω∏π¡Ö—°πÖµîπ—Ω1Ω›ï…ÖÕî†•tÏ(ÄÅ•òÄ°—Ö…ùï–§Å±ΩçÖ—•Ω∏π…ï¡±Öçî°—Ö…ùï–§Ï)ıÙ§†§Ï(ΩÕç…•¡–¯ààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)Ì±ïùÖçÂ}…ïë•…ïç—}Õç…•¡—Ù)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Òµï—ÑÅπÖµîÙâ…ΩâΩ—ÃàÅçΩπ—ïπ–ÙâπΩ•πëï‡à¯(Ò—•—±î˘M•ëï∏Åâ±îÅ•≠≠îÅô’ππï–ÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯)Ì=9Q}1%9-MÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù(ππΩ–µôΩ’πêµ°ï…ºÅÌÏÅ¡Öëë•πúËÄ–¡¡‡Ä¿ÄƒŸ¡‡ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅıÙ(ππΩ–µôΩ’πêµ°ï…ºÄπ≠•ç≠ï»ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿Ÿï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅıÙ(ππΩ–µôΩ’πêµ°ï…ºÅ†ƒÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏›…ï¥ÏÅµÖ…ù•∏ËÄ·¡‡Ä¿Äƒ¡¡‡ÏÅıÙ(ππΩ–µôΩ’πêµ°ï…ºÅ¿ÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰—…ï¥ÏÅµÖ‡µ›•ë—†ËÄ––¡¡‡ÏÅµÖ…ù•∏ËÄ¿ÅÖ’—ºÏÅıÙ(ππΩ–µôΩ’πêµ±•π≠ÃÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»Ä≈ô»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ‡µ›•ë—†ËÄ––¡¡‡ÏÅµÖ…ù•∏ËÄ»·¡‡ÅÖ’—ºÄ¿ÏÅıÙ(ππΩ–µôΩ’πêµ±•π¨ÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏Â…ï¥ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(ππΩ–µôΩ’πêµ±•π¨È°ΩŸï»ÅÌÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿à¯(ÄÄÒë•ÿÅç±ÖÕÃÙâπΩ–µôΩ’πêµ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à¯–¿–Ωë•ÿ¯(ÄÄÄÄÒ†ƒ˘Öπ–Å•≠≠îÅÕ•ëï∏Ω†ƒ¯(ÄÄÄÄÒ¿˘1ïπ≠ï∏Å≠Ö∏Å€ô…îÅ’—ëÖ—ï…–∞Åï±±ï»ÅÕ•ëï∏Å≠Ö∏Å°ÑÅô±Â——ï–∏ÅAÀ·ÿÅï∏ÅÖÿ(ÄÄÄÅ≠Ö—ïùΩ…•ïπîÅ’πëï»∞Åï±±ï»ÅüîÅ—•∞ÅôΩ…Õ•ëï∏ÅôΩ»ÉîÅœ·≠î∏Ω¿¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâπΩ–µôΩ’πêµ±•π≠Ãà¯(ÄÄÄÄÒÑÅ°…ïòÙàºàÅç±ÖÕÃÙâπΩ–µôΩ’πêµ±•π¨à˘Ω…Õ•ëîΩÑ¯(ÄÄÄÄÒÑÅ°…ïòÙàΩù’•ëï»ºàÅç±ÖÕÃÙâπΩ–µôΩ’πêµ±•π¨à˘’•ëï»ΩÑ¯(ÄÄÄÅÌçÖ—ïùΩ…Â}±•π≠ÕÙ(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(((åÅ%ππ°Ω±êÅΩúÅÕ—…’≠—’»ÅÕ¡ï•±ï»ÅÖ—Ö—•±ÕÂπï—ÃÅïùï∏ÅçΩΩ≠•îµï…≠≥ô…•πúÄ°ôΩ…∑ï∞∞(åÅ…ï——Õ±•úÅù…’ππ±ÖúÅï≠Ωµ±ΩŸï∏É
úÄÃ¥ƒ‘∞ÅΩŸï…Õ•≠—Õ—Öâï±∞§Ä¥Å•≠≠îÅâÖ…îÅï–(åÅQ…ÖëïëΩ’â±ï»µÕ¡ïÕ•ô•≠–Å≠…Öÿ∏Å%πùï∏ÅÕÖµ—Â≠≠ïâÖππï»ÅïπªîÄ°âïŸ•ÕÕ–Å’—ÕÖ—–∞(åÅÖŸ≠±Ö…–ÅµïêÅâ…’≠ï»Ä»¿»ÿ¥¿‡¥ƒƒ§ËÅQ4ÅÕï——ïÃÅëï…ôΩ»ÅôΩ…—ÕÖ—–Åõ·»ÅÕÖµ—Â≠≠îÅ§(åÅëÖúÄ¥ÅÕ•ëï∏Å∑îÅ•≠≠îÅ±Ö—îÅÕΩ¥ÅπΩîÅÖππï–Å§Å—ï≠Õ—ï∏Å’πëï»∏(åÅY•ÕïÃÅÕΩ¥ÄâM•Õ–ÅΩ¡¡ëÖ—ï…–àÅ√îÅëîÅ©’…•ë•Õ≠îÅÕ•ëïπî∏ÅYÖ»Å—•ë±•ùï…îÅÖ±±—•ê(åÅëÖùïπÃÅëÖ—ºÄ°°Ÿï…–ÅâÂùú§∞ÅÕΩ¥Åï»Åµ•ÕŸ•ÕïπëîÅôΩ»Åï∏Å—ï≠Õ–ÅÕΩ¥Å•≠≠îÅï»Åïπë…ï–Ä¥¥(åÄ»¿»ÿ¥¿‰¥»ÿÅÕÖ—–Å—•∞ÅÕ•Õ—îÅôÖ≠—•Õ≠îÅïπë…•πúÄ°ô…ÑÅù•–µ°•Õ—Ω…•≠≠ï∏§∏Å9I(åÅ59U1PÅªï»Å—ï≠Õ—ï∏Å§ÅÕï±ŸîÅÕ•ëï∏Åïπë…ïÃ∏)AI%Ye}UAQÄÙÄà»¿»ÿ¥¿‡¥Ã¿à)QI5M}UAQÄÙÄà»¿»ÿ¥¿‰¥¿‘à(()ëïòÅ}±ïùÖ±}ëÖ—î°•ÕºËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÅ…ï—’…∏ÅëÖ—ï—•µîπÕ—…¡—•µî°•Õº∞Äàïd¥ï¥¥ïêà§πÕ—…ô—•µî†àïê∏ï¥∏ïdà§(()ëïòÅ…ïπëï…}¡…•ŸÖçÂ}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÅ’¡ëÖ—ïêÄÙÅ}±ïùÖ±}ëÖ—î°AI%Ye}UAQ§((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘Aï…ÕΩπŸï…∏ÅΩúÅçΩΩ≠•ïÃÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–Ùâ!Ÿ•±≠îÅ•πôΩ…µÖÕ©ΩπÕ≠Ö¡Õ±ï»Ä°çΩΩ≠•ïÃ§Å-Ωπ—Ö≠—±•πÕï»ππºÅâ…’≠ï»∞Å°ŸΩ…ôΩ»∞ÅΩúÅ°ŸΩ…ëÖ∏Åë‘Å≠Ö∏Å≠Ωπ—…Ω±±ï…îÅëï¥∏à¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩ¡ï…ÕΩπŸï…∏ºà¯)Ì}Ωù}µï—Ñ†ùAï…ÕΩπŸï…∏ÅΩúÅçΩΩ≠•ïÃÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Äù!Ÿ•±≠îÅ•πôΩ…µÖÕ©ΩπÕ≠Ö¡Õ±ï»Ä°çΩΩ≠•ïÃ§Å-Ωπ—Ö≠—±•πÕï»ππºÅâ…’≠ï»∞Å°ŸΩ…ôΩ»∞ÅΩúÅ°ŸΩ…ëÖ∏Åë‘Å≠Ö∏Å≠Ωπ—…Ω±±ï…îÅëï¥∏ú∞Å	M}UI0Ä¨ÄúΩ¡ï…ÕΩπŸï…∏ºú•Ù)Ì=9Q}1%9-MÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù(πçΩΩ≠•îµ—Öâ±îÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅâΩ…ëï»µçΩ±±Ö¡ÕîËÅçΩ±±Ö¡ÕîÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅıÙ(πçΩΩ≠•îµ—Öâ±îÅ—†∞ÄπçΩΩ≠•îµ—Öâ±îÅ—êÅÌÏÅ—ï·–µÖ±•ù∏ËÅ±ïô–ÏÅ¡Öëë•πúËÄƒ¡¡‡Äƒ—¡‡ÏÅâΩ…ëï»µâΩ——Ω¥ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅŸï…—•çÖ∞µÖ±•ù∏ËÅ—Ω¿ÏÅıÙ(πçΩΩ≠•îµ—Öâ±îÅ—†ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿—ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(πçΩΩ≠•îµ—Öâ±îÅ—»È±ÖÕ–µç°•±êÅ—êÅÌÏÅâΩ…ëï»µâΩ——Ω¥ËÅπΩπîÏÅıÙ(π¡…•ŸÖç‰µâΩë‰Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅµÖ…ù•∏ËÄ»·¡‡Ä¿Äƒ¡¡‡ÏÅıÙ(π¡…•ŸÖç‰µâΩë‰Å¿ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…•ŸÖç‰µâΩë‰Å¿π’¡ëÖ—ïêÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅµÖ…ù•∏µ—Ω¿ËÄÃ…¡‡ÏÅâΩ…ëï»µ—Ω¿ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅ¡Öëë•πúµ—Ω¿ËÄƒŸ¡‡ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅAï…ÕΩπŸï…∏ÅΩúÅçΩΩ≠•ïÃΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘Aï…ÕΩπŸï…∏Ωë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘Aï…ÕΩπŸï…∏ÅΩúÅçΩΩ≠•ïÃΩ†ƒ¯(ÄÄÄÄÄÄÒ¿˘!Ÿ•±≠îÅ•πôΩ…µÖÕ©ΩπÕ≠Ö¡Õ±ï»ÅŸ§Åâ…’≠ï»Å√îÅ-Ωπ—Ö≠—±•πÕï»ππº∞Å°ŸΩ…ôΩ»∞ÅΩúÅ°ŸΩ…ëÖ∏Åë‘ÅÕ—Â…ï»Åëï¥ÅÕï±ÿ∏Ω¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖç‰µâΩë‰àÅÕ—Â±îÙâµÖ‡µ›•ë—†Ëÿ–¡¡‡Ïà¯(ÄÄÄÄÒ¿˘∏Å•πôΩ…µÖÕ©ΩπÕ≠Ö¡Õï∞Ä°çΩΩ≠•î§Åï»Åï∏Å±•—ï∏Å—ï≠Õ—ô•∞Åπï——±ïÕï…ï∏Åë•∏Å±Öù…ï»(ÄÄÄÅªï»Åë‘Åâïœ·≠ï»Åï∏Åπï——Õ•ëî∏ÅïππîÅÕ•ëï∏ÅâïÕ≠…•Ÿï»Å°Ÿ•±≠îÅŸ§Åâ…’≠ï»ÅΩú(ÄÄÄÅ°ŸΩ…ôΩ»∞Å§Å—ÀïêÅµïêÅï≠Ωµ±ΩŸï∏É
úÄÃ¥ƒ‘ÅΩúÅ¡ï…ÕΩπŸï…πôΩ…Ω…ëπ•πùï∏Ä°AH§∏Ω¿¯((ÄÄÄÄÒ†»˘!Ÿ•±≠îÅ•πôΩ…µÖÕ©ΩπÕ≠Ö¡Õ±ï»Åâ…’≠ï»ÅŸ§Ω†»¯(ÄÄÄÄÒ—Öâ±îÅç±ÖÕÃÙâçΩΩ≠•îµ—Öâ±îà¯(ÄÄÄÄÄÄÒ—»¯Ò—†˘-•±ëîΩ—†¯Ò—†˘Ω…∑ï∞Ω—†¯Ò—†˘QÂ¡îΩ—†¯Ω—»¯(ÄÄÄÄÄÄÒ—»¯(ÄÄÄÄÄÄÄÄÒ—ê˘ΩΩù±îÅQÖúÅ5ÖπÖùï»Ω—ê¯(ÄÄÄÄÄÄÄÄÒ—ê˘7ï±ï»Å—…Öô•≠¨ÅΩúÅâ…’¨ÅÖÿÅÕ•ëï∏∞ÅÕ±•¨ÅÖ–ÅŸ§ÅŸï–Å°Ÿ•±≠ï–Å•ππ°Ω±êÅÕΩ¥ÅôÖ≠—•Õ¨Åï»ÅπÂ——•ú∏Ω—ê¯(ÄÄÄÄÄÄÄÄÒ—ê˘%≠≠îÅª·ëŸïπë•úÄ°Õ—Ö—•Õ—•≠¨§Ω—ê¯(ÄÄÄÄÄÄΩ—»¯(ÄÄÄÄÄÄÒ—»¯(ÄÄÄÄÄÄÄÄÒ—ê˘Q…ÖëïëΩ’â±ï»∞Å›•∏∞Åë—…Öç—•Ω∏Ω—ê¯(ÄÄÄÄÄÄÄÄÒ—ê˘Mï——ïÃÅõ·…Õ–Åªï»Åë‘Å≠±•≠≠ï»ÅëïúÅŸ•ëï…îÅ—•∞Åï∏ÅôΩ…°Öπë±ï»ÅŸ•ÑÅï∏(ÄÄÄÄÄÄÄÅ—•±â’ëÕ±ïπ≠îÅô…ÑÅΩÕÃ∏ÅIïù•Õ—…ï…ï»ÅÖ–Åâïœ·≠ï–Å≠Ω¥Åô…Ñ(ÄÄÄÄÄÄÄÅ-Ωπ—Ö≠—±•πÕï»ππº∞ÅÕ±•¨ÅÖ–ÅôΩ…°Öπë±ï…ï∏Å≠Ö∏Åâï—Ö±îÅ…•≠—•úÅ¡…ΩŸ•Õ©Ω∏Å—•∞(ÄÄÄÄÄÄÄÅΩÕÃ∏Å•ÕÕîÅçΩΩ≠•ïπîÅÕï——ïÃÅÖÿÅëï–ÅÖ≠—’ï±±îÅÖôô•±•Ö—îµπï——Ÿï…≠ï–Åï±±ï»(ÄÄÄÄÄÄÄÅôΩ…°Öπë±ï…ïπÃÅïùï–ÅëΩµïπî∞Å•≠≠îÅÖÿÅ-Ωπ—Ö≠—±•πÕï»ππºÅë•…ï≠—î∏Ω—ê¯(ÄÄÄÄÄÄÄÄÒ—ê˘%≠≠îÅª·ëŸïπë•úÄ°—•±≠πÂ——ï–ÅµÖ…≠ïëÕõ·…•πú§Ω—ê¯(ÄÄÄÄÄÄΩ—»¯(ÄÄÄÄΩ—Öâ±î¯(ÄÄÄÄÒ¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà˘Y§Åâ…’≠ï»Å•≠≠îÅçΩΩ≠•ïÃÅ—•∞ÅπΩîÅ’—ΩŸï»Åëï——îÄ¥Å•πùï∏Å…ï—Ö…ùï—•πúµÖππΩπÕï…•πú(ÄÄÄÅΩúÅ•πùï∏Åëï±•πúÅï±±ï»ÅÕÖ±úÅÖÿÅëÖ—ÑÅ—•∞Å—…ïë©ï¡Ö…—ï»∏Ω¿¯((ÄÄÄÄÒ†»˘MÖµ—Â≠≠îΩ†»¯(ÄÄÄÄÒ¿˘YïêÅõ·…Õ—îÅâïœ·¨Åõï»Åë‘ÅΩ¡¿Åï∏ÅÕÖµ—Â≠≠îµâΩ≠ÃÅëï»Åë‘Å≠Ö∏ÅŸï±ùîÄâΩë—Ñà∞(ÄÄÄÄâ-’∏Åª·ëŸïπë•ùîà∞Åï±±ï»Å—•±¡ÖÕÕîÅÕ—Ö—•Õ—•≠¨ÅΩúÅÖôô•±•Ö—îµÕ¡Ω…•πúÅ°Ÿï»ÅôΩ»(ÄÄÄÅÕïúÄ°’πëï»Äâ%ππÕ—•±±•πùï»àÅô•ππï»Åë‘ÅΩùœîÅï∏Åô’±∞Å±•Õ—îÅΩŸï»(ÄÄÄÅ—…ïë©ï¡Ö…—Õ±ïŸï…Öπì·…ïπîÅŸ§ÅÕÖµÖ…âï•ëï»Åµïê§∏ÅM—Ö—•Õ—•≠¨µÕ≠…•¡—ï–Ä°ΩΩù±î(ÄÄÄÅQÖúÅ5ÖπÖùï»§Å±ÖÕ—ïÃÅ•≠≠îÅõ·»Åë‘Å°Ö»ÅÕÖµ—Â≠≠ï–Å—•∞Åëï–∏ÅYÖ±ùï–Å±Öù…ïÃÅ§(ÄÄÄÅπï——±ïÕï…ï∏Åë•∏ÅΩúÅë‘Å≠Ö∏Åïπë…îÅëï–Åªï»ÅÕΩ¥Å°ï±Õ–ÅŸïêÉîÅÕ±ï——îÅ±Öù…ï–(ÄÄÄÅπï——Õ—ïëÕëÖ—ÑÅôΩ»Å-Ωπ—Ö≠—±•πÕï»ππºÅ§Åπï——±ïÕï…•ππÕ—•±±•πùïπîÅΩúÅ±ÖÕ—î(ÄÄÄÅÕ•ëï∏Å√îÅπÂ—–∏Ω¿¯((ÄÄÄÄÒ†»˘!ŸΩ…ëÖ∏Å≠Ωπ—…Ω±±ï…îÅï±±ï»ÅÕ±ï——îÅçΩΩ≠•ïÃΩ†»¯(ÄÄÄÄÒ¿˘îÅô±ïÕ—îÅπï——±ïÕï…îÅ±Ö»ÅëïúÅÕî∞Åâ±Ω≠≠ï…îÅΩúÅÕ±ï——îÅçΩΩ≠•ïÃÅ’πëï»(ÄÄÄÅ¡ï…ÕΩπŸï…∏¥Åï±±ï»ÅÕ•≠≠ï…°ï—Õ•ππÕ—•±±•πùïπî∏ÅM≥ï»Åë‘ÅÖÿÅ•≠≠îµª·ëŸïπë•ùî(ÄÄÄÅçΩΩ≠•ïÃÅ°ï±–∞ÅŸ•∞Å-Ωπ—Ö≠—±•πÕï»ππºÅôΩ…—ÕÖ—–Åô’πùï…îÅÕΩ¥ÅπΩ…µÖ±–Ä¥ÅŸ§(ÄÄÄÅâ…’≠ï»Åëï¥Å≠’∏Å—•∞Å∑ï±•πúÅΩúÅ¡…ΩŸ•Õ©ΩπÕÕ¡Ω…•πú∞Å•≠≠îÅ—•∞ÅÕï±Ÿî(ÄÄÄÅ¡…•ÕÕÖµµïπ±•ùπ•πùï∏∏Ω¿¯((ÄÄÄÄÒ†»˘-Ωπ—Ö≠–Ω†»¯(ÄÄÄÄÒ¿˘M√·…Õ∑ï∞ÅΩ¥Å¡ï…ÕΩπŸï…∏Åï±±ï»ÅçΩΩ≠•ïÃÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππº¸ÅMïπêÅΩÕÃÅï∏(ÄÄÄÅîµ¡ΩÕ–Å√îÅÌ}çΩπ—Öç—}ïµÖ•±}±•π¨†•Ù∏Ω¿¯((ÄÄÄÄÒ¿Åç±ÖÕÃÙâ’¡ëÖ—ïêà˘M•Õ–ÅΩ¡¡ëÖ—ï…–ËÅÌ’¡ëÖ—ïëÙΩ¿¯(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}—ï…µÕ}¡Öùî†§Ä¥¯ÅÕ—»Ë(ÄÄÄÄàààΩŸ•±≠Ö»ºÄ¥¥Å©’…•ë•Õ¨Å•πôΩ…µÖÕ©Ω∏ÅΩúÅÖπÕŸÖ…Õô…ÖÕ≠…•Ÿï±Õî∏ÅQï≠Õ—ï∏Åï»(ÄÄÄÅâ…’≠ï…ïπÃÅïùï∏∞Å±•µ–Å•π∏Ä»¿»ÿ¥¿‡¥Ã¿Ä°≠’∏Å≠ΩπŸï…—ï…–Åô…ÑÅµÖ…≠ëΩ›∏Å—•∞(ÄÄÄÅ!Q50∞ÅΩ…ë±Âëï∏Åï»Å’ïπë…ï–§∏Å’πùï…ï»ÅÕΩ¥Åï∏Å¡Ö…Ö¡±‰µÕ•ëîÅΩŸï»Åëî(ÄÄÄÅ≠Ω…—ï…î∞Å≠Ωπ—ï≠Õ—’ï±±îÅë•Õç±ΩÕ’…îµÖŸÕπ•——ïπîÅÕΩ¥ÅÖ±±ï…ïëîÅô•ππïÃÅ√î(ÄÄÄÅ¡…Ωë’≠–¥Ω≠Ö—ïùΩ…§¥Ω¡…•ŸÖ—îÅ±Öâï∞µÕ•ëï»Ä°ôΩΩ—ï»µë•Õç±ΩÕ’…î∞(ÄÄÄÄπë•Õç±ΩÕ’…îµÖŸÕπ•—–∞ÄΩΩ¥µ¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»º§Ä¥¥Åï…Õ—Ö——ï»Å•πùï∏ÅÖÿ(ÄÄÄÅëï¥∞ÅÕÖµ±ï»ÅâÖ…îÅ°ï±îÅâ•±ëï–Åï—–ÅÕ—ïê∏Å-Ωπ—Ö≠—¡’π≠—ï–Å§É
úƒƒ(ÄÄÄÄ°}çΩπ—Öç—}ïµÖ•±}±•π¨†§§Åï»ÅÖ±±ï…ïëîÅ…ïï±–ÅΩúÅÕÂπ±•úÅ§ÅôΩΩ—ï…ï∏Å√îÅÖ±±î(ÄÄÄÅÕ•ëï»∞Å•≠≠îÅï∏Å—Ω¥Å√ïÕ—Öπê∏ààà(ÄÄÄÅ’¡ëÖ—ïêÄÙÅ}±ïùÖ±}ëÖ—î°QI5M}UAQ§(ÄÄÄÅçΩπ—Öç–ÄÙÅ}çΩπ—Öç—}ïµÖ•±}±•π¨†§((ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞(ÄÄâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâY•±Øï»ÅΩúÅÖπÕŸÖ…Õô…ÖÕ≠…•Ÿï±Õîà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩŸ•±≠Ö»ºâıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘Y•±Øï»ÅΩúÅÖπÕŸÖ…Õô…ÖÕ≠…•Ÿï±ÕîÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–Ùâ)’…•ë•Õ¨Å•πôΩ…µÖÕ©Ω∏ÅΩ¥Å-Ωπ—Ö≠—±•πÕï»ππºËÅŸÖ…ïµï…≠ï»ÅΩúÅ±ΩùΩï»∞Å¡…Ωë’≠—â•±ëï»ÅΩúÄµ•±±’Õ—…ÖÕ©Ωπï»∞Å¡…•ŸÖ—îÅ±Öâï∞∞Å¡…•Õ•πôΩ…µÖÕ©Ω∏∞ÅÖôô•±•Ö—îµÕÖµÖ…âï•êÅΩúÅÖπÕŸÖ…ÕôΩ…°Ω±ê∏à¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩŸ•±≠Ö»ºà¯)Ì}Ωù}µï—Ñ†ùY•±Øï»ÅΩúÅÖπÕŸÖ…Õô…ÖÕ≠…•Ÿï±ÕîÉäLÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Äù)’…•ë•Õ¨Å•πôΩ…µÖÕ©Ω∏ÅΩ¥Å-Ωπ—Ö≠—±•πÕï»ππºËÅŸÖ…ïµï…≠ï»ÅΩúÅ±ΩùΩï»∞Å¡…Ωë’≠—â•±ëï»ÅΩúÄµ•±±’Õ—…ÖÕ©Ωπï»∞Å¡…•ŸÖ—îÅ±Öâï∞∞Å¡…•Õ•πôΩ…µÖÕ©Ω∏∞ÅÖôô•±•Ö—îµÕÖµÖ…âï•êÅΩúÅÖπÕŸÖ…ÕôΩ…°Ω±ê∏ú∞Å	M}UI0Ä¨ÄúΩŸ•±≠Ö»ºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯(ÒÕ—Â±î˘ÌM!I}MQe1Ù(π¡…•ŸÖç‰µâΩë‰Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅµÖ…ù•∏ËÄ»·¡‡Ä¿Äƒ¡¡‡ÏÅıÙ(π¡…•ŸÖç‰µâΩë‰Å¿ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…•ŸÖç‰µâΩë‰Å¿π’¡ëÖ—ïêÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅµÖ…ù•∏µ—Ω¿ËÄÃ…¡‡ÏÅâΩ…ëï»µ—Ω¿ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅ¡Öëë•πúµ—Ω¿ËÄƒŸ¡‡ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅY•±Øï»ÅΩúÅÖπÕŸÖ…Õô…ÖÕ≠…•Ÿï±ÕîΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘)’…•ë•Õ¨Å•πôΩ…µÖÕ©Ω∏Ωë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘Y•±Øï»ÅΩúÅÖπÕŸÖ…Õô…ÖÕ≠…•Ÿï±ÕîΩ†ƒ¯(ÄÄÄÄÄÄÒ¿˘=¥Å-Ωπ—Ö≠—±•πÕï»ππº∞ÅŸÖ…ïµï…≠ï»ÅΩúÅâ•±ëï»∞Å¡…•ŸÖ—îÅ±Öâï∞µ¡…Ωë’≠—ï»∞Å¡…•Õ•πôΩ…µÖÕ©Ω∏ÅΩúÅÖπÕŸÖ…ÕôΩ…°Ω±ê∏Ω¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖç‰µâΩë‰àÅÕ—Â±îÙâµÖ‡µ›•ë—†Ëÿ‡¡¡‡Ïà¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅ¡…•Ã¥ÅΩúÅ•πôΩ…µÖÕ©ΩπÕ—©ïπïÕ—îÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»∏ÅΩ…∑ï±ï–ÅµïêÅ—©ïπïÕ—ï∏Åï»ÉîÅù´·…îÅëï–Åïπ≠±ï…îÅôΩ»ÅôΩ…â…’≠ï…îÉîÅô•ππîÅ•πôΩ…µÖÕ©Ω∏ÅΩ¥Å≠Ωπ—Ö≠—±•πÕï»∞ÅÕÖµµïπ±•ùπîÅ¡…Ωë’≠—ï»ÅΩúÅÕÖµµïπ±•ùπîÅ¡…•Õï»Å°ΩÃÅ’±•≠îÅôΩ…°Öπë±ï…î∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅÕï±ùï»Å•≠≠îÅ≠Ωπ—Ö≠—±•πÕï»ÅΩúÅï»Å•≠≠îÅ¡Ö…–Å§Å≠´·¡ÕÖŸ—Ö±ï∏Åµï±±Ω¥Åâ…’≠ï…ï∏ÅΩúÅëï∏ÅÖ≠—’ï±±îÅôΩ…°Öπë±ï…ï∏∏Å-´·¿Åù©ïππΩµõ·…ïÃÅ°ΩÃÅôΩ…°Öπë±ï…ï∏Åâ…’≠ï…ï∏ÅŸï±ùï»∞ÅΩúÅëï–Åï»ÅôΩ…°Öπë±ï…ïπÃÅ≠´·¡ÕŸ•±Øï»∞Å±ïŸï…•πùÕâï—•πùï±Õï»∞Å…ï—’……ïù±ï»ÅΩúÉ·Ÿ…•ùîÅŸ•±Øï»ÅÕΩ¥Åù©ï±ëï»ÅôΩ»Å≠´·¡ï–∏Ω¿¯((ÄÄÄÄÒ†»¯ƒ∏ÅYÖ…ïµï…≠ï»∞Å±ΩùΩï»ÅΩúÅ¡…Ωë’≠—πÖŸ∏Ω†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅΩµ—Ö±ï»ÅΩúÅÕÖµµïπ±•ùπï»Å¡…Ωë’≠—ï»Åô…ÑÅï∏Å…ï≠≠îÅ¡…Ωë’Õïπ—ï»ÅΩúÅµï…≠ïŸÖ…ï»∏Ω¿¯(ÄÄÄÄÒ¿˘YÖ…ïµï…≠ï»∞Å±ΩùΩï»∞Å¡…Ωë’≠—πÖŸ∏∞Åô•…µÖπÖŸ∏ÅΩúÅÖπë…îÅ≠©ïππï—ïù∏ÅÕΩ¥ÅŸ•ÕïÃÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅ—•±£·…ï»ÅÕ•πîÅ…ïÕ¡ï≠—•ŸîÅ…ï——•ù°ï—Õ°ÖŸï…î∏Ω¿¯(ÄÄÄÄÒ¿˘M±•≠îÅ≠©ïππï—ïù∏ÅâïπÂ——ïÃÅôΩ»ÉîÅ•ëïπ—•ô•Õï…îÅΩúÅ•πôΩ…µï…îÅΩ¥Å¡…Ωë’≠—ïπî∞Å¡…Ωë’Õïπ—ïπîÅΩúÅôΩ…°Öπë±ï…πîÅÕΩ¥ÅΩµ—Ö±ïÃÅï±±ï»ÅÕÖµµïπ±•ùπïÃÅ√îÅ—©ïπïÕ—ï∏∏Ω¿¯(ÄÄÄÄÒ¿˘	…’¨ÅÖÿÅï–ÅŸÖ…ïµï…≠î∞Åï∏Å±ΩùºÅï±±ï»Åï–Å¡…Ωë’≠—πÖŸ∏Å√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅ•ππïãô…ï»Å•≠≠îÅ§ÅÕïúÅÕï±ÿÅÖ–Å-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï•êÅÖÿ∞Å—•±≠πÂ——ï–∞ÅÕ¡ΩπÕï–∞ÅùΩë≠©ïπ–Åï±±ï»Å√îÅÖππï∏Å∑ï—îÅΩôô•Õ•ï±–ÅôΩ…â’πëï–ÅµïêÅëï∏ÅÖ≠—’ï±±îÅ…ï——•ù°ï—Õ°ÖŸï…ï∏∏Ω¿¯(ÄÄÄÄÒ¿˘ï»Åëï–ÅôΩ…ï±•ùùï»Åï–Å≠Ωµµï…Õ•ï±–ÅÕÖµÖ…âï•ê∞ÅôΩ»Åï≠Õïµ¡ï∞Åù©ïππΩ¥Åï–ÅÖôô•±•Ö—ï¡…Ωù…Ö¥∞Å≠Ö∏Å-Ωπ—Ö≠—±•πÕï»ππºÅµΩ——ÑÅùΩë—ù´·…ï±ÕîÅôΩ»Å—…Öô•≠¨Åï±±ï»Å≠´·¿ÅÕΩ¥ÅôΩ…µ•ë±ïÃÅ—•∞Åëï∏ÅÖ≠—’ï±±îÅôΩ…°Öπë±ï…ï∏∏Ω¿¯((ÄÄÄÄÒ†»¯»∏ÅA…Ωë’≠—â•±ëï»ÅΩúÅÖππï–ÅŸ•Õ’ï±–ÅµÖ—ï…•Ö±îΩ†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅâïπÂ——ï»ÅŸ•Õ’ï±–ÅµÖ—ï…•Ö±îÅôΩ»ÉîÅù´·…îÅëï–Åïπ≠±ï…îÉîÅ•ëïπ—•ô•Õï…îÅΩúÅÕÖµµïπ±•ùπîÅ¡…Ωë’≠—ï»∏Ω¿¯(ÄÄÄÄÒ¿˘A…Ωë’≠—â•±ëï»∞Å±ΩùΩï»ÅΩúÅÖππï–ÅŸ•Õ’ï±–ÅµÖ—ï…•Ö±îÅ≠Ö∏Åâ±Öπ–ÅÖππï–Å€ô…îÅù©Ω…–Å—•±ù©ïπùï±•úÅù©ïππΩ¥Å¡…Ωë’Õïπ—ï»∞ÅôΩ…°Öπë±ï…î∞ÅÖôô•±•Ö—ï¡…Ωù…Öµµï»∞Å¡…Ωë’≠—ôïïëï»∞Åµïë•ïâÖπ≠ï»Åï±±ï»ÅÖπë…îÅ≠•±ëï»∏Ω¿¯(ÄÄÄÄÒ¿˘Iï——•ù°ï—ïπîÅ—•∞ÅΩ…•ù•πÖ±îÅ¡…Ωë’≠—â•±ëï»∞Å±ΩùΩï»∞ÅïµâÖ±±ÖÕ©ïëïÕ•ù∏ÅΩúÅÖππï–ÅµÖ—ï…•Ö±îÅ—•±£·…ï»ÅëîÅ…ïÕ¡ï≠—•ŸîÅ…ï——•ù°ï—Õ°ÖŸï…πî∏Ω¿¯(ÄÄÄÄÒ¿˘5Ö—ï…•Ö±ï–Åâ…’≠ïÃÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅ§ÅôΩ…â•πëï±ÕîÅµïêÅ•ëïπ—•ô•≠ÖÕ©Ω∏∞Å•πôΩ…µÖÕ©Ω∏ÅΩúÅÕÖµµïπ±•ùπ•πúÅÖÿÅëîÅÖ≠—’ï±±îÅ¡…Ωë’≠—ïπîÅΩúÅµï…≠ïŸÖ…ïπî∏Ω¿¯((ÄÄÄÄÒ†»¯Ã∏ÅùπîÅ¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»Ω†»¯(ÄÄÄÄÒ¿˘;ï»Åï–Åïùπï–ÅΩ…•ù•πÖ±–Å¡…Ωë’≠—â•±ëîÅ•≠≠îÅï»Å—•±ù©ïπùï±•ú∞Å≠Ö∏Å-Ωπ—Ö≠—±•πÕï»ππºÅâïπÂ——îÅï∏Åïùï∏Å¡…Ωë’≠—•±±’Õ—…ÖÕ©Ω∏∏Ω¿¯(ÄÄÄÄÒ¿˘∏ÅÕ±•¨Å•±±’Õ—…ÖÕ©Ω∏Åï»Å±Öùï–ÅôΩ»ÉîÅ°©ï±¡îÅâ…’≠ï…ï∏ÅµïêÉîÅ•ëïπ—•ô•Õï…îÅΩúÅÕ≠•±±îÅµï±±Ω¥Å¡…Ωë’≠—ï»ÅÕΩ¥ÅΩµ—Ö±ïÃÅï±±ï»ÅÕÖµµïπ±•ùπïÃÅ√îÅ—©ïπïÕ—ï∏∏Ω¿¯(ÄÄÄÄÒ¿˘A…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»Å±Öùï–ÅÖÿÅ-Ωπ—Ö≠—±•πÕï»ππºÅï»Å•≠≠îÅΩ…•ù•πÖ±îÅ¡…Ωë’≠—â•±ëï»ÅΩúÅÕ≠Ö∞Å•≠≠îÅΩ¡¡ôÖ——ïÃÅÕΩ¥Åï∏Åª·ÂÖ≠—•úÅù©ïπù•Ÿï±ÕîÅÖÿÅ¡…Ωë’Õïπ—ïπÃÅΩôô•Õ•ï±±îÅ¡…Ωë’≠—ïµâÖ±±ÖÕ©î∏Ω¿¯(ÄÄÄÄÒ¿˘Ö…ùï»∞Å¡…Ω¡Ω…Õ©Ωπï»∞Åù…Öô•Õ≠îÅï±ïµïπ—ï»∞Å—ï≠Õ–∞ÅïµâÖ±±ÖÕ©îÅΩúÅÖπë…îÅŸ•Õ’ï±±îÅëï—Ö±©ï»Å≠Ö∏ÅÖŸŸ•≠îÅô…ÑÅëï–ÅôÖ≠—•Õ≠îÅ¡…Ωë’≠—ï–∏Ω¿¯(ÄÄÄÄÒ¿˘;ï»Å-Ωπ—Ö≠—±•πÕï»ππºÅâïπÂ——ï»Åï∏Åïùï∏Å¡…Ωë’≠—•±±’Õ—…ÖÕ©Ω∏∞Åœ·≠ï»ÅŸ§ÉîÅù´·…îÅëï——îÅ—Âëï±•úÅôΩ»Åâ…’≠ï…ï∏∏ÅMîÄÒÑÅ°…ïòÙàΩΩ¥µ¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»ºà˘Ω¥Å¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»ΩÑ¯ÅôΩ»Åµï»Å•πôΩ…µÖÕ©Ω∏∏Ω¿¯((ÄÄÄÄÒ†»¯–∏ÅA…•ŸÖ—îÅ±Öâï∞ÅΩúÅ—•±ÕŸÖ…ïπëîÅ¡…Ωë’≠—ï»Ω†»¯(ÄÄÄÄÒ¿˘π≠ï±—îÅ≠Ωπ—Ö≠—±•πÕï»ÅÕï±ùïÃÅ’πëï»ÅÖπë…îÅ¡…Ωë’≠—πÖŸ∏Åï±±ï»ÅÕΩ¥Åœï≠Ö±—îÅ¡…•ŸÖ—îµ±Öâï∞µ¡…Ωë’≠—ï»∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅ≠Ö∏ÅŸ•ÕîÅ•πôΩ…µÖÕ©Ω∏ÅΩ¥ÅÖ–Åï–Å¡…Ωë’≠–Å—•±ÕŸÖ…ï»∞Åï»Å…ï±Ö—ï…–Å—•∞Åï±±ï»Å≠Ö∏Å€ô…îÅ¡…Ωë’Õï…–Å√îÅù…’ππ±ÖúÅÖÿÅÕÖµµîÅï±±ï»Å—•±ÕŸÖ…ïπëîÅ¡…Ωë’≠–ÅÕΩ¥Åï–ÅÖππï–Å≠Ωπ—Ö≠—±•πÕï¡…Ωë’≠–∏Ω¿¯(ÄÄÄÄÒ¿˘M±•≠îÅ≠Ωâ±•πùï»ÅâÂùùï»Å√îÅ•πôΩ…µÖÕ©Ω∏ÅΩúÅ¡…Ωë’≠—ëÖ—ÑÅÕΩ¥Å-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å—•±ù©ïπùï±•ú∏ÅMîÄÒÑÅ°…ïòÙàΩ¡…•ŸÖ—îµ±Öâï∞ºà˘ΩŸï…Õ•≠—ï∏ÅΩŸï»ÅΩ¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ΩÑ¯ÅôΩ»Åï∏ÅÕÖµ±ï–ÅΩŸï…Õ•≠–ÅΩŸï»Åë•ÕÕîÅ≠Ωâ±•πùïπî∏Ω¿¯(ÄÄÄÄÒ¿˘=¡¡±ÂÕπ•πùï»ÅΩ¥Å—•±ÕŸÖ…ïπëîÅ¡…Ωë’≠—ï»Åï»Åµïπ–ÅÕΩ¥Å•πôΩ…µÖÕ©Ω∏ÅΩúÅ°©ï±¿Å—•∞Å¡…Ωë’≠—•ëïπ—•ô•≠ÖÕ©Ω∏∏Å	…’≠ï…ï∏Åã·»Å≠Ωπ—…Ω±±ï…îÅ…ï±ïŸÖπ—îÅ¡…Ωë’≠—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»ÅΩúÅÕ•∏Å≠Ωπ—Ö≠—±•πÕï…ïÕï¡–Åõ·»ÅâïÕ—•±±•πú∏Ω¿¯(ÄÄÄÄÒ¿˘A…Ωë’≠—ï»Åã·»Å•≠≠îÅâÂ——ïÃÅ’—ï±’≠≠ïπëîÅ√îÅù…’ππ±ÖúÅÖÿÅ¡…Ωë’≠—πÖŸ∏∞Å¡…•ÃÅï±±ï»Å•πôΩ…µÖÕ©Ω∏ÅΩ¥Å—•±ÕŸÖ…ïπëîÅ¡…Ωë’≠—ï»Å√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅëï…ÕΩ¥Åëï——îÅ•ππïãô…ï»Åïπë…•πúÅô…ÑÅ¡…Ωë’≠—ï–ÅÕΩ¥Åï»ÅÖπâïôÖ±–Åï±±ï»Å—•±¡ÖÕÕï–ÅÖÿÅΩ¡—•≠ï»Åï±±ï»ÅÖππï–Å≠ŸÖ±•ô•Õï…–Å°ï±Õï¡ï…ÕΩπï±∞∏Ω¿¯((ÄÄÄÄÒ†»¯‘∏ÅA…•Õï»ÅΩúÅ¡…•Õ•πôΩ…µÖÕ©Ω∏Ω†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅ•ππ°ïπ—ï»ÅΩúÅâï°Öπë±ï»Å¡…•Ã¥ÅΩúÅ¡…Ωë’≠—•πôΩ…µÖÕ©Ω∏Åô…ÑÅâ±Öπ–ÅÖππï–ÅôΩ…°Öπë±ï…î∞Å¡…Ωë’≠—ôïïëï»∞ÅÖôô•±•Ö—ï¡…Ωù…Öµµï»ÅΩúÅÖπë…îÅëÖ—Ö≠•±ëï»∏Ω¿¯(ÄÄÄÄÒ¿˘Y§ÅÖ…âï•ëï»ÅôΩ»ÅÖ–Å•πôΩ…µÖÕ©Ωπï∏ÅÕ≠Ö∞Å€ô…îÅ≠Ω……ï≠–ÅΩúÅΩ¡¡ëÖ—ï…–∞Åµï∏Å¡…•Õï»∞Å±Öùï…Õ—Ö—’Ã∞Åô…Ö≠—≠ΩÕ—πÖëï»∞Å…ÖâÖ——Ÿ•±Øï»∞Å≠Öµ¡Öπ©ï»ÅΩúÅÖπë…îÅôΩ…°Ω±êÅ≠Ö∏Åïπë…ïÃÅ’—ï∏ÅÖ–Åëï——îÅ’µ•ëëï±âÖ…–Åù©ïπÕ¡ï•±ïÃÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππº∏Ω¿¯(ÄÄÄÄÒ¿˘A…•Õï∏ÅΩúÅŸ•±Øï…ïπîÅÕΩ¥ÅŸ•ÕïÃÅ°ΩÃÅôΩ…°Öπë±ï…ï∏Å√îÅ—•ëÕ¡’π≠—ï–ÅôΩ»Å≠´·¡ï–Åï»Åëï…ôΩ»ÅÖŸù´·…ïπëî∏Ω¿¯(ÄÄÄÄÒ¿˘ï»Å-Ωπ—Ö≠—±•πÕï»ππºÅŸ•Õï»Å—Ω—Ö±¡…•ÃÅ•π≠±’ëï…–Åâï…ïùπï–Åô…Ö≠–∞ÅâÂùùï»Åâï…ïùπ•πùï∏Å√îÅëï∏Åô…Ö≠—•πôΩ…µÖÕ©Ωπï∏ÅΩúÅëîÅŸ•±Øï…ïπîÅŸ§Å°Ö»Å—•±ù©ïπùï±•ú∏Å…§Åô…Ö≠–∞Åµ•π•µ’µÕâï≥·¿∞ÅùïΩù…Öô•Õ≠îÅâïù…ïπÕπ•πùï»Åï±±ï»ÅÖπë…îÅŸ•±Øï»Å°ΩÃÅôΩ…°Öπë±ï…ï∏Å≠Ö∏Å√ïŸ•…≠îÅëï∏Åïπëï±•ùîÅ¡…•Õï∏∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅùÖ…Öπ—ï…ï»Å•≠≠îÅÖ–Åï∏ÅΩ¡¡ù•—–Å¡…•ÃÅ—•∞Åïπ°Ÿï»Å—•êÅï»ÅµÖ…≠ïëï—ÃÅ±ÖŸïÕ—îÅ¡…•Ã∏Ω¿¯(ÄÄÄÄÒ¿˘;ï»Å’——…Â≠¨ÅÕΩ¥É
≠±ÖŸïÕ–Å¡…•œ
Ï∞É
≠â•±±•ùÕ”
ÏÅï±±ï»Å—•±ÕŸÖ…ïπëîÅâïπÂ——ïÃ∞Åù©ï±ëï»ÅÕÖµµïπ±•ùπ•πùï∏ÅëîÅôΩ…°Öπë±ï…πîÅΩúÅ¡…•ÕëÖ—ÖïπîÅÕΩ¥Å•ππüï»Å§Åëï∏ÅÖ≠—’ï±±îÅÕÖµµïπ±•ùπ•πùï∏Å√îÅëï–ÅÖ≠—’ï±±îÅ—•ëÕ¡’π≠—ï–∞ÅµïêÅµ•πë…îÅÖππï–Å’——…Â≠≠ï±•úÅô…ïµüï»∏Ω¿¯((ÄÄÄÄÒ†»¯ÿ∏Åôô•±•Ö—îµÕÖµÖ…âï•êÅΩúÅô•πÖπÕ•ï…•πúΩ†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅ≠Ö∏ÅµΩ——ÑÅ¡…ΩŸ•Õ©Ω∏Åï±±ï»ÅÖππï∏ÅùΩë—ù´·…ï±ÕîÅªï»Åï∏Åâ…’≠ï»Å≠±•≠≠ï»ÅÕïúÅŸ•ëï…îÅ—•∞Åï∏ÅôΩ…°Öπë±ï»Åï±±ï»Åù©ïππΩµõ·…ï»Åï–Å≠´·¿Å°ΩÃÅï∏ÅôΩ…°Öπë±ï»ÅŸ•ÑÅï∏Å±ïπ≠îÅô…ÑÅ-Ωπ—Ö≠—±•πÕï»ππº∏Ω¿¯(ÄÄÄÄÒ¿˘ï——îÅ≠Ö±±ïÃÅÖôô•±•Ö—îµµÖ…≠ïëÕõ·…•πú∏Ω¿¯(ÄÄÄÄÒ¿˘M±•≠îÅÕÖµÖ…âï•êÅâ•ë…Ö»Å—•∞ÉîÅô•πÖπÕ•ï…îÅë…•ô—ï∏ÅÖÿÅ-Ωπ—Ö≠—±•πÕï»ππºÅΩúÅù´·»Åëï–Åµ’±•úÉîÅ—•±â‰Å—©ïπïÕ—ï∏Å—•∞Åâ…’≠ï…πîÅ’—ï∏Åâï—Ö±•πú∏Ω¿¯(ÄÄÄÄÒ¿˘%≠≠îÅÖ±±îÅâ’—•≠≠ï»∞Å¡…Ωë’≠—ï»Åï±±ï»Å¡…•Õï»Å√îÅµÖ…≠ïëï–Åï»Åª·ëŸïπë•ùŸ•ÃÅ•π≠±’ëï…–Å√îÅ-Ωπ—Ö≠—±•πÕï»ππº∏Å!Ÿ•±≠îÅôΩ…°Öπë±ï…îÅÕΩ¥Å≠Ö∏ÅŸ•ÕïÃÅ≠Ö∏Åâ±Öπ–ÅÖππï–ÅÖŸ°ïπùîÅÖÿÅ—•±ùÖπúÅ—•∞Å√ï±•—ï±•ùîÅ¡…Ωë’≠–¥ÅΩúÅ¡…•ÕëÖ—Ñ∞Å—ï≠π•Õ¨Å•π—ïù…ÖÕ©Ω∏ÅΩúÅ≠Ωµµï…Õ•ï±±îÅÕÖµÖ…âï•ê∏Ω¿¯(ÄÄÄÄÒ¿˘π≠ï±—îÅÕÖµÖ…âï•êÅ≠Ö∏ÅΩùœîÅù§Å-Ωπ—Ö≠—±•πÕï»ππºÅ—•±ùÖπúÅ—•∞ÅïùπîÅ¡…Ωë’≠—ôïïëï»∞Å≠Öµ¡Öπ©ï»∞Å…ÖâÖ——≠Ωëï»Åï±±ï»Å¡…•Õï»∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅÖ…âï•ëï»ÅôΩ»ÅÖ–Å≠Ωµµï…Õ•ï±±îÅÕÖµÖ…âï•êÅ•≠≠îÅÕ≠Ö∞Åù´·…îÅ¡…•Õ•πôΩ…µÖÕ©Ωπï∏Åµ•ÕŸ•Õïπëî∏Ω¿¯((ÄÄÄÄÒ†»¯‹∏ÅA…Ωë’≠—•πôΩ…µÖÕ©Ω∏ÅΩúÅ°ï±Õï•πôΩ…µÖÕ©Ω∏Ω†»¯(ÄÄÄÄÒ¿˘%πôΩ…µÖÕ©Ωπï∏Å√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅï»Åùïπï…ï±∞Å•πôΩ…µÖÕ©Ω∏ÅΩúÅï…Õ—Ö——ï»Å•≠≠îÅ’πëï…œ·≠ï±Õî∞Å—•±¡ÖÕπ•πúÅï±±ï»Å•πë•Ÿ•ë’ï±∞ÅÀïëù•Ÿπ•πúÅô…ÑÅΩ¡—•≠ï»∞É·Âï±ïùîÅï±±ï»ÅÖππï–Å≠ŸÖ±•ô•Õï…–Å°ï±Õï¡ï…ÕΩπï±∞∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»Åï»Å¡…Ωë’≠—ï»ÅÕΩ¥Åâ…’≠ïÃÅë•…ï≠—îÅ√îÉ·Âï–∏Åï•∞Åâ…’¨∞Åôï•∞ÅÕ—Â…≠î∞Åôï•∞Å¡ÖÕÕôΩ…¥Åï±±ï»ÅµÖπùï±ô’±∞Å°Âù•ïπîÅ≠Ö∏Åµïëõ·…îÅ¡…Ωâ±ïµï»∏Ω¿¯(ÄÄÄÄÒ¿˘	…’≠ï…îÅã·»Åõ·±ùîÅÖπâïôÖ±•πùïπîÅô…ÑÅΩ¡—•≠ï»Åï±±ï»ÅÖππï–Å≠ŸÖ±•ô•Õï…–Å°ï±Õï¡ï…ÕΩπï±∞ÅÕÖµ–Å¡…Ωë’Õïπ—ïπÃÅâ…’≠ÕÖπŸ•Õπ•πú∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅÕ—•±±ï»Å•≠≠îÅë•ÖùπΩÕî∞Å—•±¡ÖÕÕï»Å•≠≠îÅ≠Ωπ—Ö≠—±•πÕï»ÅΩúÅù•»Å•≠≠îÅ•πë•Ÿ•ë’ï±∞Åµïë•Õ•πÕ¨Åâï°Öπë±•πú∏Ω¿¯((ÄÄÄÄÒ†»¯‡∏ÅΩ…°Öπë±ï…πïÃÅÖπÕŸÖ»Ω†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅôΩ…µ•ë±ï»Å•πôΩ…µÖÕ©Ω∏ÅΩúÅ±ïπ≠ï»Å—•∞Åï≠Õ—ï…πîÅôΩ…°Öπë±ï…î∞Åµï∏ÅÕï±ùï»Å•≠≠îÅ¡…Ωë’≠—ïπîÅÕï±ÿ∏Ω¿¯(ÄÄÄÄÒ¿˘ï∏ÅÖ≠—’ï±±îÅôΩ…°Öπë±ï…ï∏Åï»ÅÖπÕŸÖ…±•úÅôΩ»Åâ±Öπ–ÅÖππï–ÅâïÕ—•±±•πú∞Åâï—Ö±•πú∞Å±ïŸï…•πú∞Å≠’πëïÕï…Ÿ•çî∞ÅÖπù…ï…ï—–∞Å…ï—’»∞Å…ï≠±ÖµÖÕ©Ω∏ÅΩúÉ·Ÿ…•úÅ£ïπë—ï…•πúÅÖÿÅ≠´·¡ï–∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅï»Å•≠≠îÅÖπÕŸÖ…±•úÅôΩ»Å°Öπë±•πùï»∞Å—©ïπïÕ—ï»∞Å¡…Ωë’≠—ï»Åï±±ï»Å•ππ°Ω±êÅ°ΩÃÅï≠Õ—ï…πîÅôΩ…°Öπë±ï…î∏Ω¿¯(ÄÄÄÄÒ¿˘	…’≠ï…ï∏Åã·»Å≠Ωπ—…Ω±±ï…îÅ¡…•Ã∞Å¡…Ωë’≠–∞ÅÕ—Â…≠î∞ÅÖπ—Ö±∞Å±•πÕï»∞Å±ïŸï…•πùÕâï—•πùï±Õï»ÅΩúÉ·Ÿ…•ùîÅ≠´·¡ÕŸ•±Øï»Å°ΩÃÅôΩ…°Öπë±ï…ï∏Åõ·»ÅâïÕ—•±±•πùï∏Åô’±±õ·…ïÃ∏Ω¿¯((ÄÄÄÄÒ†»¯‰∏Åï•∞ÅΩúÅïπë…•πùï»Ω†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅÖ…âï•ëï»Å≠Ωπ—•π’ï…±•úÅµïêÉîÅ°Ω±ëîÅ¡…Ωë’≠—ëÖ—Ñ∞Å¡…•Õï»ÅΩúÉ·Ÿ…•úÅ•πôΩ…µÖÕ©Ω∏Å≠Ω……ï≠–ÅΩúÅΩ¡¡ëÖ—ï…–∏Ω¿¯(ÄÄÄÄÒ¿˘ï–Å≠Ö∏Å±•≠ïŸï∞ÅôΩ…ï≠ΩµµîÅôï•∞∞ÅµÖπù±ï»∞ÅôΩ…Õ•π≠ï±Õï»∞Å—ï≠π•Õ≠îÅ¡…Ωâ±ïµï»Åï±±ï»Å’—ëÖ—ï…–Å•πôΩ…µÖÕ©Ω∏∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅôΩ…âï°Ω±ëï»ÅÕïúÅ…ï——ï∏Å—•∞ÉîÅ≠Ω……•ùï…î∞ÅΩ¡¡ëÖ—ï…îÅï±±ï»Åô©ï…πîÅ•πôΩ…µÖÕ©Ω∏Åªï»ÅÕΩ¥Å°ï±Õ–∏Ω¿¯((ÄÄÄÄÒ†»¯ƒ¿∏Å≠Õ—ï…πîÅπï——Õ—ïëï»Ω†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅ•ππï°Ω±ëï»Å±ïπ≠ï»Å—•∞Åπï——Õ—ïëï»ÅÕΩ¥Åë…•ŸïÃÅÖÿÅÖπë…îÅŸ•…≠ÕΩµ°ï—ï»∏Ω¿¯(ÄÄÄÄÒ¿˘;ï»Åï∏Åâ…’≠ï»ÅôΩ…±Ö—ï»Å-Ωπ—Ö≠—±•πÕï»ππº∞Åï»Åëï–Åëï∏Åï≠Õ—ï…πîÅŸ•…≠ÕΩµ°ï—ïπÃÅïùπîÅŸ•±Øï»ÅΩúÅ¡ï…ÕΩπŸï…π…ïù±ï»ÅÕΩ¥Åù©ï±ëï»∏Ω¿¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å•≠≠îÅ≠Ωπ—…Ω±∞ÅΩŸï»ÅΩúÅï»Å•≠≠îÅÖπÕŸÖ…±•úÅôΩ»Å•ππ°Ω±ëï–Åï±±ï»Å—•±ù©ïπùï±•ù°ï—ï∏Å√îÅï≠Õ—ï…πîÅπï——Õ—ïëï»∏Ω¿¯((ÄÄÄÄÒ†»¯ƒƒ∏ÅIï——•ù°ï—Õ°ÖŸï…îΩ†»¯(ÄÄÄÄÒ¿˘-Ωπ—Ö≠—±•πÕï»ππºÅ…ïÕ¡ï≠—ï…ï»Å•µµÖ—ï…•ï±±îÅ…ï——•ù°ï—ï»∏Ω¿¯(ÄÄÄÄÒ¿˘ï…ÕΩ¥Åë‘Å…ï¡…ïÕïπ—ï…ï»Åï∏Å¡…Ωë’Õïπ–∞Åµï…≠ïŸÖ…î∞ÅôΩ…°Öπë±ï»Åï±±ï»ÅÖππï∏Å…ï——•ù°ï—Õ°ÖŸï»ÅΩúÅµïπï»ÅÖ–Åï–ÅŸÖ…ïµï…≠î∞Åâ•±ëî∞Å¡…Ωë’≠—•±±’Õ—…ÖÕ©Ω∏∞Å¡…Ωë’≠—Ω¡¡±ÂÕπ•πúÅï±±ï»ÅÖππï–ÅµÖ—ï…•Ö±îÅ√îÅ-Ωπ—Ö≠—±•πÕï»ππºÅâ…’≠ïÃÅôï•∞∞Åâï»ÅŸ§ÅëïúÅ≠Ωπ—Ö≠—îÅΩÕÃÅ√îÅÌçΩπ—Öç—Ù∏Ω¿¯(ÄÄÄÄÒ¿˘Y§ÅŸ•∞Åù©ïππΩµüîÅ°ïπŸïπëï±Õï∏ÅΩúÅŸïêÅâï°ΩÿÅ≠Ω……•ùï…î∞ÅΩ¡¡ëÖ—ï…îÅï±±ï»Åô©ï…πîÅµÖ—ï…•Ö±ï–ÅœîÅ…ÖÕ≠–ÅÕΩ¥Å¡…Ö≠—•Õ¨Åµ’±•ú∏Ω¿¯((ÄÄÄÄÒ†»¯ƒ»∏Åπë…•πùï»Ω†»¯(ÄÄÄÄÒ¿˘ïππîÅ•πôΩ…µÖÕ©Ωπï∏Å≠Ö∏ÅΩ¡¡ëÖ—ï…ïÃÅªï»Å—©ïπïÕ—ï∏∞ÅëÖ—Ö≠•±ëïπî∞ÅÕÖµÖ…âï•ëïπîÅï±±ï»Å…ï±ïŸÖπ—îÅ…ïù±ï»Åïπë…ïÃ∏Ω¿¯((ÄÄÄÄÒ¿Åç±ÖÕÃÙâ’¡ëÖ—ïêà˘M•Õ–ÅΩ¡¡ëÖ—ï…–ËÅÌ’¡ëÖ—ïëÙΩ¿¯(ÄÄΩë•ÿ¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()}MA}9U5	I}IÄÙÅ…îπçΩµ¡•±î°»âqê¨†¸Ë±qê¨§¸à§(()ëïòÅ}¡Ö…Õï}Õ¡ïç}π’µâï…Ã°…Ö‹ËÅÕ—»ÅÅ9Ωπî§Ä¥¯Å±•Õ—mÕ—…tË(ÄÄÄÄààâQ…ï≠≠ï»Å’–Å—Ö±±Ÿï…ë•ï»Åô…ÑÅï∏Åô…•—ï≠Õ–µÕ¡ïåµÕ—…ïπúÄ†ú‡∞–ÄºÄ‡∞‡Åµ¥ú∞(ÄÄÄÄúÃ‡Äîú∞Äú‘ƒÄîÅ§Å≠©ï…πï∏∞ÅΩŸï»Ä‡¿ÄîÅ√îÅΩŸï…ô±Ö—ï∏ú§Ä¥¥Å£ïπë—ï…ï»ÅπΩ…Õ¨(ÄÄÄÅ≠ΩµµÑµëïÕ•µÖ∞ÅΩúÅô±ï»µŸï…ë§µôï±–Ä°ëΩââï∞ÅâÖÕ•Õ≠’…Ÿî∞Å≠©ï…πîΩΩŸï…ô±Ö—î¥(ÄÄÄÅŸÖππ•ππ°Ω±ê§∏ÅIï—’…πï…ï»ÅπΩ…µÖ±•Õï…—îÅÕ—…ïπúµŸï…ë•ï»Ä°¡’π≠—’¥ÅÕΩ¥(ÄÄÄÅëïÕ•µÖ±—ïù∏∞ÅÕΩ…—ï…–Åπ’µï…•Õ¨§Ä¥¥Å-U8Å—•∞Åô•±—ï»µµÖ—ç°•πúΩŸ•Õπ•πú∞Å•≠≠î(ÄÄÄÅŸ•ëï…îÅ’—…ïùπ•πú∏ÅQΩ¥Å±•Õ—îÅ°Ÿ•ÃÅ¡…Ωë’≠—ï–ÅµÖπù±ï»Åëï——îÅÕ¡ïåµôï±—ï–(ÄÄÄÄ°Õ¡ïçÃÅï»Åô…•—ï≠Õ–∞Å•≠≠îÅÕ—…’≠—’…ï…—îÅôï±–Ä¥¥ÅçÑ∏Å°Ö±Ÿ¡Ö…—ï∏ÅÖÿ(ÄÄÄÅ≠Ö—Ö±Ωùï∏ÅµÖπù±ï»Å	ÖÕ•Õ≠’…ŸîΩ•Öµï—ï»Å¡»∏Ä»¿»ÿ¥¿‰¥¿‘∞ÅÕî(ÄÄÄÅ¡ÖÕÕôΩ…¥µô•±—ï»µπΩ—Ö—ï–Å§Å1Uπµê§∏ààà(ÄÄÄÅ•òÅπΩ–Å…Ö‹Ë(ÄÄÄÄÄÄÄÅ…ï—’…∏Åmt(ÄÄÄÅ…ï—’…∏ÅÕΩ…—ïê°Ì¥π…ï¡±Öçî†à∞à∞Äà∏à§ÅôΩ»Å¥Å•∏Å}MA}9U5	I}Iπô•πëÖ±∞°…Ö‹•Ù∞Å≠ï‰ıô±ΩÖ–§(()ëïòÅ}ô•—}ô•±—ï…}ŸÖ±’ïÃ°¡…Ωë’ç—ÃËÅ±•Õ—më•ç—t∞ÅÕ¡ïç}±Öâï∞ËÅÕ—»§Ä¥¯Å—’¡±ïm±•Õ—mÕ—…t∞Åë•ç—mÕ—»∞Å±•Õ—mÕ—…uutË(ÄÄÄÄààâΩ»Åï—–ÅÕ¡ïåµôï±–Ä°òπï≠Ã∏ÄùYÖππ•ππ°Ω±êú§ËÅô•ππï»ÅÖ±±îÅë•Õ—•π≠—î(ÄÄÄÅ—Ö±±Ÿï…ë•ï»Åâ±Öπ–ÅAI=U-Q9ÅCÅ99Å-Q=I%M%8Ä°•≠≠îÅ°ï±î(ÄÄÄÅ≠Ö—Ö±Ωùï∏Ä¥¥Åï∏Å—Ω…•Õ≠îµ±•πÕï»µÕ•ëîÅÕ≠Ö∞Å•≠≠îÅ—•±â‰Åï–ÅâÖÕ•Õ≠’…Ÿîµ—Ö±∞(ÄÄÄÅÕΩ¥ÅâÖ…îÅô•ππïÃÅ°ΩÃÅï∏ÅëÖùÕ±•πÕî§∞Å¡±’ÕÃÅï–ÅΩ¡¡Õ±ÖúÅ¡…Ωë’≠–µ•êÄ¥¯Åëï—Ã(ÄÄÄÅïùπîÅŸï…ë•ï»Ä°—•∞ÅëÖ—ÑµÖ——…•â’——ï»Å√îÅ°Ÿï…–Å≠Ω…–§∏ààà(ÄÄÄÅÖ±±}ŸÖ±’ïÃËÅÕï—mÕ—…tÄÙÅÕï–†§(ÄÄÄÅâÂ}¡…Ωë’ç–ËÅë•ç—mÕ—»∞Å±•Õ—mÕ—…utÄÙÅÌÙ(ÄÄÄÅôΩ»Å¿Å•∏Å¡…Ωë’ç—ÃË(ÄÄÄÄÄÄÄÅÕ¡ïçÃÄÙÅÌ±Öâï∞ËÅŸÖ±’îÅôΩ»Å±Öâï∞∞ÅŸÖ±’îÅ•∏Å¿πùï–†âÕ¡ïçÃà∞Åmt•Ù(ÄÄÄÄÄÄÄÅŸÖ±’ïÃÄÙÅ}¡Ö…Õï}Õ¡ïç}π’µâï…Ã°Õ¡ïçÃπùï–°Õ¡ïç}±Öâï∞§§(ÄÄÄÄÄÄÄÅâÂ}¡…Ωë’ç—m¡lâ•êâutÄÙÅŸÖ±’ïÃ(ÄÄÄÄÄÄÄÅÖ±±}ŸÖ±’ïÃπ’¡ëÖ—î°ŸÖ±’ïÃ§(ÄÄÄÅ…ï—’…∏ÅÕΩ…—ïê°Ö±±}ŸÖ±’ïÃ∞Å≠ï‰ıô±ΩÖ–§∞ÅâÂ}¡…Ωë’ç–(()ëïòÅ…ïπëï…}çÖ—ïùΩ…Â}¡Öùî°çÖ—ïùΩ…Â}Õ±’úËÅÕ—»∞ÅçÖ—ïùΩ…‰ËÅë•ç–∞Å¡…Ωë’ç—ÃËÅ±•Õ—më•ç—t∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§((ÄÄÄÅ…Ω›ÃÄÙÅmt(ÄÄÄÅôΩ»Å¿Å•∏Å¡…Ωë’ç—ÃË(ÄÄÄÄÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°¡lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅï±•ù•â±îÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÄÄÄÄÅ±Ω›ïÕ–ÄÙÅµ•∏°ï±•ù•â±î∞Å≠ï‰ı±ÖµâëÑÅºËÄ°Ωlâ¡…•çï}πΩ¨ât∞ÅΩlâ—Ω—Ö∞ât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄÄÄÄÅ•µÖùï}’…∞ÄÙÅ}¡…Ωë’ç—}•µÖùî°¿§(ÄÄÄÄÄÄÄÅ…Ω›ÃπÖ¡¡ïπê°Ïâ¡…Ωë’ç–àËÅ¿∞Äâ±Ω›ïÕ–àËÅ±Ω›ïÕ–∞Äâ•µÖùï}’…∞àËÅ•µÖùï}’…±Ù§((ÄÄÄÄåÅM—Ö—•Õ¨Å…ïπëï»∞ÅÕΩ…—ï…–Å±ÖŸïÕ–µõ·…Õ–ÅÕΩ¥ÅÕ—ÖπëÖ…êÄ¥Åëï——îÅï»Åëï–Å$µç…Ö›±ï…î(ÄÄÄÄåÅΩúÅâ…’≠ï…îÅ’—ï∏Å)LÅôÖ≠—•Õ¨ÅÕï»∏(ÄÄÄÅ…Ω›ÃπÕΩ…–°≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÅ•òÅ…lâ±Ω›ïÕ–âtÅï±ÕîÅô±ΩÖ–†â•πòà§§((ÄÄÄÄåÅAÖÕÕôΩ…¥µô•±—ï»ËÅŸÖππ•ππ°Ω±êΩâÖÕ•Õ≠’…ŸîΩë•Öµï—ï»∞Å§Å—•±±ïùúÅ—•∞(ÄÄÄÄåÅµï…≠îµô•±—ï…ï–Ä¥¥Å•πùï∏ÅÖππï∏ÅπΩ…Õ¨Å≠Ωπ—Ö≠—±•πÕîµ¡…•ÕÕÖµµïπ±•ùπ•πúÅ°Ö»(ÄÄÄÄåÅëï——îÅ¡»∏Å§ÅëÖú∏ÅYï…ë•ïπîÅô•ππïÃÅ-U8ÅÕΩ¥Åô…•—ï≠Õ–Å§ÅÕ¡ïçÃÄ°Õî(ÄÄÄÄåÅ}¡Ö…Õï}Õ¡ïç}π’µâï…Ã§∞ÅΩúÅëï≠π•πùï∏ÅŸÖ…•ï…ï»ÅµÂîÅ¡ï»Å≠Ö—ïùΩ…§Ä°—Ω…•Õ≠îº(ÄÄÄÄåÅµ’±—•ôΩ≠Ö±îÅ°Ö»Å±Öπù–Åõô……îÅ	ÖÕ•Õ≠’…ŸîΩ•Öµï—ï»µΩ¡¡õ·…•πùï»Åïπ∏ÅëÖùÃ¥º(ÄÄÄÄåÅ∑ïπïëÕ±•πÕï»§Ä¥¥Åëï…ôΩ»Å…ïùπï–Å’–ÅAHÅ≠Ö—ïùΩ…§ÅΩúÅô•±—ï…ï–Å’—ï±Ö—ïÃ(ÄÄÄÄåÅ°ï±–Åëï»Åõô……îÅïπ∏Ä»Åë•Õ—•π≠—îÅŸï…ë•ï»Åô•ππïÃ∏(ÄÄÄÅ›ç}ŸÖ±’ïÃ∞Å›ç}âÂ}•êÄÙÅ}ô•—}ô•±—ï…}ŸÖ±’ïÃ°¡…Ωë’ç—Ã∞ÄâYÖππ•ππ°Ω±êà§(ÄÄÄÅâç}ŸÖ±’ïÃ∞Åâç}âÂ}•êÄÙÅ}ô•—}ô•±—ï…}ŸÖ±’ïÃ°¡…Ωë’ç—Ã∞Äâ	ÖÕ•Õ≠’…Ÿîà§(ÄÄÄÅë•Ö}ŸÖ±’ïÃ∞Åë•Ö}âÂ}•êÄÙÅ}ô•—}ô•±—ï…}ŸÖ±’ïÃ°¡…Ωë’ç—Ã∞Äâ•Öµï—ï»à§((ÄÄÄÅëïòÅÕ¡ïç}…Ω›}°—µ±}ôΩ»°¿ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÄåÅ-Ωµ¡Ö≠–ÅÕ¡ïÕ•ô•≠ÖÕ©ΩπÕ…ÖêÅ√îÅÕï±ŸîÅ¡…Ωë’≠—≠Ω…—ï–Ä¥¥Åï≠Õ¡±•Õ•——î(ÄÄÄÄÄÄÄÄåÅ¡…Ωë’≠—ïùïπÕ≠Ö¡ï»Åï»ÅπÂ——•ùîÅôΩ»ÅµïππïÕ≠ï»Å=ÅôΩ»Å$µ…ï—…•ïŸÖ∞(ÄÄÄÄÄÄÄÄåÄ†»¿»ÿ¥¿‰¥¿‘µ…ïëïÕ•ùπï–∞ÅÕîÅ1Uπµê§∏ÅY•Õï»Å≠’∏Åôï±—ïπîÅ¡…Ωë’≠—ï–(ÄÄÄÄÄÄÄÄåÅôÖ≠—•Õ¨Å°Ö»Ä°µÖπùîÅ¡…Ωë’≠—ï»ÅµÖπù±ï»Å	Ω%∞ÅÕîÅπΩ—Ö—ï–ÅΩŸï»§∏(ÄÄÄÄÄÄÄÅâ•—ÃÄÙÅmt(ÄÄÄÄÄÄÄÅ›ç}ÿÄÙÅ›ç}âÂ}•êπùï–°¡lâ•êât∞Åmt§(ÄÄÄÄÄÄÄÅâç}ÿÄÙÅâç}âÂ}•êπùï–°¡lâ•êât∞Åmt§(ÄÄÄÄÄÄÄÅë•Ö}ÿÄÙÅë•Ö}âÂ}•êπùï–°¡lâ•êât∞Åmt§(ÄÄÄÄÄÄÄÅ•òÅ›ç}ÿË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•—ÃπÖ¡¡ïπê°òúÒÕ¡Ö∏Åç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµÕ¡ïåà˘ÌI=A1Q}%=9}MYıÌïÕçÖ¡î°›ç}Ÿl¡tπ…ï¡±Öçî†à∏à∞Äà∞à§•ÙÄîΩÕ¡Ö∏¯ú§(ÄÄÄÄÄÄÄÅ•òÅâç}ÿË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•—ÃπÖ¡¡ïπê°òúÒÕ¡Ö∏Åç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµÕ¡ïåà˘Ì	M%M-UIY}%=9}MYıÌïÕçÖ¡î°âç}Ÿl¡tπ…ï¡±Öçî†à∏à∞Äà∞à§•ÙÅµ¥ΩÕ¡Ö∏¯ú§(ÄÄÄÄÄÄÄÅ•òÅë•Ö}ÿË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•—ÃπÖ¡¡ïπê°òúÒÕ¡Ö∏Åç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµÕ¡ïåà˘Ì%5QI}%=9}MYıÌïÕçÖ¡î°ë•Ö}Ÿl¡tπ…ï¡±Öçî†à∏à∞Äà∞à§•ÙÅµ¥ΩÕ¡Ö∏¯ú§(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµÕ¡ïçÃµ…Ω‹à˘Ïààπ©Ω•∏°â•—Ã•ÙΩë•ÿ¯úÅ•òÅâ•—ÃÅï±ÕîÄàà((ÄÄÄÅëïòÅ…ïπëï…}…Ω‹°»ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ¿∞Å±Ω›ïÕ–ÄÙÅ…lâ¡…Ωë’ç–ât∞Å…lâ±Ω›ïÕ–ât(ÄÄÄÄÄÄÄÄåÅCîÅ≠Ö—ïùΩ…•Õ•ëï»Ä°§ÅµΩ—Õï—π•πúÅ—•∞Åµï…≠ïÕ•ëï»§Åï»Å5I-PÅëï–ÅÕΩ¥(ÄÄÄÄÄÄÄÄåÅôÖ≠—•Õ¨ÅŸÖ…•ï…ï»ΩÕ≠•±±ï»Å≠Ω…—ïπîÅô…ÑÅ°Ÿï…Öπë…îÄ¥¥Å¡…Ωë’Õïπ–Åï»ÅΩô—î(ÄÄÄÄÄÄÄÄåÅ≠ΩπÕ—Öπ–Å√îÅ—Ÿï…ÃÅÖÿÅô±ï…îÅµï…≠ï»Ä°ΩΩ¡ï…Y•Õ•Ω∏Ä¥¯Å	•Ωô•π•—‰ΩŸÖ•…Ñº(ÄÄÄÄÄÄÄÄåÅ5ÂÖ‰º∏∏∏§∞ÅœîÅµï…≠ïπÖŸπï–ÅôÂ±±ï»ÅÕÖµµîÄâπÂ——•ú∞ÅŸÖ…•ï…ïπëîÅ•πôº(ÄÄÄÄÄÄÄÄåÅ…ï—–Å’πëï»Å—•——ï±ï∏àµ…Ω±±îÅÕΩ¥Å¡…Ωë’Õïπ–Åù©Ω…ëîÅ√îÅµï…≠ïÕ•ëï∏∏(ÄÄÄÄÄÄÄÅâ…Öπë}±•π¨ÄÙÅòúÒÑÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµµÖπ’ôÖç—’…ï»àÅ°…ïòÙàΩµï…≠îΩÌïÕçÖ¡î°¡lââ…Öπë}Õ±’úât•Ùºà˘ÌïÕçÖ¡î°¡lââ…Öπë}±Öâï∞ât•ÙΩÑ¯ú(ÄÄÄÄÄÄÄÅô•—}Ö——…ÃÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÅòúÅëÖ—Ñµ›åÙâÏàÄàπ©Ω•∏°›ç}âÂ}•êπùï–°¡lâ•êât∞Åmt§•Ùàú(ÄÄÄÄÄÄÄÄÄÄÄÅòúÅëÖ—ÑµâåÙâÏàÄàπ©Ω•∏°âç}âÂ}•êπùï–°¡lâ•êât∞Åmt§•Ùàú(ÄÄÄÄÄÄÄÄÄÄÄÅòúÅëÖ—Ñµë•ÑÙâÏàÄàπ©Ω•∏°ë•Ö}âÂ}•êπùï–°¡lâ•êât∞Åmt§•Ùàú(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅ…ï—’…∏Å}…ïπëï…}¡…Ωë’ç—}—•±î†(ÄÄÄÄÄÄÄÄÄÄÄÅ°…ïòıòúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÅπÖµîı¡lâπÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÅ•µÖùï}’…∞ı…lâ•µÖùï}’…∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÅôÖ±±âÖç≠}•π•—•Ö±Ãı¡lââ…Öπë}±Öâï∞âulË…tπ’¡¡ï»†§∞(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ıçÖ—ïùΩ…Âlâ±Öâï∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕïçΩπëÖ…Â}±•πï}°—µ∞ıâ…Öπë}±•π¨∞(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ïÕ–ı±Ω›ïÕ–∞(ÄÄÄÄÄÄÄÄÄÄÄÅΩ—°ï…}çΩ’π–ı±ï∏°¡lâΩôôï…Ãât§Ä¥Äƒ∞(ÄÄÄÄÄÄÄÄÄÄÄÅçΩµ¡Ö…•ÕΩπ}Ωôôï…Ãı…ïçΩπç•±ï}¡…Ωë’ç–°¡lâΩôôï…Ãât∞ÅπΩ‹§∞(ÄÄÄÄÄÄÄÄÄÄÄÅëÖ—Ö}Ö——»ıòúÅëÖ—Ñµâ…ÖπêÙâÌïÕçÖ¡î°¡lââ…Öπë}Õ±’úât•ÙâÌô•—}Ö——…ÕÙú∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïçÕ}…Ω›}°—µ∞ıÕ¡ïç}…Ω›}°—µ±}ôΩ»°¿§∞(ÄÄÄÄÄÄÄÄ§((ÄÄÄÅ¡…Ωë’ç—}…Ω›Õ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°…ïπëï…}…Ω‹°»§ÅôΩ»Å»Å•∏Å…Ω›Ã§((ÄÄÄÄåÅ5ï…≠ï»ËÅï≠—îÅÖπ—Ö±∞Å¡…Ωë’≠—ï»Å¡ï»Åµï…≠îÄ°¡Ω¡’≥ô…îÅµï…≠ï»ÄÙÅô±ïÕ–(ÄÄÄÄåÅ¡…Ωë’≠—ï»Å§Å99Å≠Ö—ïùΩ…•ï∏∞Å•≠≠îÅï∏Åù©ï——ï–ΩµÖπ’ï±–ÅÕÖ—–Å±•Õ—î§Ä¥¥(ÄÄÄÄåÅΩúÅï≠—îÅŸ•Õπ•πùÕπÖŸ∏Ä°â…Öπë}±Öâï∞§∞Å•≠≠îÅï∏ÄπçÖ¡•—Ö±•Èî†§µù©ï—π•πúÅ√î(ÄÄÄÄåÅÕ±’ùï∏ÅÕΩ¥Å—•ë±•ùï…îÅùÑÅôï•∞ÅôΩ»Åòπï≠Ã∏Äâ±ïÖ…1Öàà∏(ÄÄÄÅâ…Öπë}çΩ’π—ÃËÅë•ç—mÕ—»∞Å•π—tÄÙÅÌÙ(ÄÄÄÅâ…Öπë}±Öâï±ÃËÅë•ç—mÕ—»∞ÅÕ—…tÄÙÅÌÙ(ÄÄÄÅôΩ»Å¿Å•∏Å¡…Ωë’ç—ÃË(ÄÄÄÄÄÄÄÅâ…Öπë}çΩ’π—Õm¡lââ…Öπë}Õ±’úâutÄÙÅâ…Öπë}çΩ’π—Ãπùï–°¡lââ…Öπë}Õ±’úât∞Ä¿§Ä¨Äƒ(ÄÄÄÄÄÄÄÅâ…Öπë}±Öâï±Õm¡lââ…Öπë}Õ±’úâutÄÙÅ¡lââ…Öπë}±Öâï∞ât(ÄÄÄÅÕΩ…—ïë}â…ÖπëÃÄÙÅÕΩ…—ïê°â…Öπë}çΩ’π—Ã∞Å≠ï‰ı±ÖµâëÑÅàËÄ†µâ…Öπë}çΩ’π—Õmât∞Åâ…Öπë}±Öâï±Õmât§§(ÄÄÄÅπ}â…ÖπëÃÄÙÅ±ï∏°ÕΩ…—ïë}â…ÖπëÃ§(ÄÄÄÅπ}¡…Ωë’ç—ÃÄÙÅ±ï∏°¡…Ωë’ç—Ã§(ÄÄÄÅA=AU1I}8ÄÙÄÿ(ÄÄÄÅ¡Ω¡’±Ö…}â…ÖπëÃÄÙÅÕΩ…—ïë}â…ÖπëÕlÈA=AU1I}9t(ÄÄÄÅ…ïÕ—}â…ÖπëÃÄÙÅÕΩ…—ïë}â…ÖπëÕmA=AU1I}8Èt((ÄÄÄÅëïòÅâ…Öπë}ç°•¿°àËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ…ï—’…∏Ä†(ÄÄÄÄÄÄÄÄÄÄÄÅòúÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâç°•¿àÅëÖ—Ñµù…Ω’¿Ùââ…ÖπêàÅëÖ—ÑµŸÖ±’îÙâÌïÕçÖ¡î°à•ÙàÄú(ÄÄÄÄÄÄÄÄÄÄÄÅòùÖ…•Ñµ¡…ïÕÕïêÙâôÖ±Õîà˘ÌïÕçÖ¡î°â…Öπë}±Öâï±Õmât•ÙÄÒÕ¡Ö∏Åç±ÖÕÃÙâç°•¿µçΩ’π–à˘Ìâ…Öπë}çΩ’π—ÕmâuÙΩÕ¡Ö∏¯Ωâ’——Ω∏¯ú(ÄÄÄÄÄÄÄÄ§((ÄÄÄÅ¡Ω¡’±Ö…}ç°•¡Õ}°—µ∞ÄÙÄààπ©Ω•∏°â…Öπë}ç°•¿°à§ÅôΩ»ÅàÅ•∏Å¡Ω¡’±Ö…}â…ÖπëÃ§(ÄÄÄÅ…ïÕ—}ç°•¡Õ}°—µ∞ÄÙÄààπ©Ω•∏°â…Öπë}ç°•¿°à§ÅôΩ»ÅàÅ•∏Å…ïÕ—}â…ÖπëÃ§(ÄÄÄÅÕ°Ω›}Ö±±}—Ωùù±ï}°—µ∞ÄÙÄ†(ÄÄÄÄÄÄÄÅòúÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâç°•¿Åç°•¿µù°ΩÕ–àÅ•êÙââ…Öπêµ—Ωùù±îµµΩ…îàÅÖ…•Ñµï·¡ÖπëïêÙâôÖ±Õîà¯ú(ÄÄÄÄÄÄÄÅòù±±îÅµï…≠ï»Ä°Ìπ}â…ÖπëÕÙ§ÄÒÕ¡Ö∏ÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯¨ΩÕ¡Ö∏¯Ωâ’——Ω∏¯ú(ÄÄÄÄÄÄÄÅ•òÅ…ïÕ—}â…ÖπëÃÅï±ÕîÄàà(ÄÄÄÄ§((ÄÄÄÅëïòÅô•—}ë…Ω¡ëΩ›π}°—µ∞°≠ï‰ËÅÕ—»∞Å±Öâï∞ËÅÕ—»∞ÅŸÖ±’ïÃËÅ±•Õ—mÕ—…t∞Åôµ–∞Å•çΩ∏ËÅÕ—»∞ÅΩ¡—•ΩπÖ∞ËÅâΩΩ∞ÄÙÅÖ±Õî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÄåÅU—ï±Ö—ïÃÅ°ï±–Ä°•≠≠îÅâÖ…îÅ—Ω¥Å…Öê§Å°Ÿ•ÃÅ’πëï»Ä»Åë•Õ—•π≠—îÅŸï…ë•ï»(ÄÄÄÄÄÄÄÄåÅô•ππïÃÅôΩ»ÅëïππîÅ≠Ö—ïùΩ…•ï∏Ä¥¥Åï–Åô•±—ï»ÅµïêÄ¿¥ƒÅŸÖ±úÅù´·»(ÄÄÄÄÄÄÄÄåÅ•πùïπ—•πúÅπÂ——•ú∞ÅâÖ…îÅ…Ω–∏(ÄÄÄÄÄÄÄÅ•òÅ±ï∏°ŸÖ±’ïÃ§ÄÄ»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ…ï—’…∏Äàà(ÄÄÄÄÄÄÄÅç°•¡ÃÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÄÄÄÄÅòúÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâç°•¿àÅëÖ—Ñµù…Ω’¿ÙâÌ≠ïÂÙàÅëÖ—ÑµŸÖ±’îÙâÌïÕçÖ¡î°ÿ•ÙàÄú(ÄÄÄÄÄÄÄÄÄÄÄÅòùÖ…•Ñµ¡…ïÕÕïêÙâôÖ±Õîà˘ÌïÕçÖ¡î°ôµ–°ÿ§•ÙΩâ’——Ω∏¯ú(ÄÄÄÄÄÄÄÄÄÄÄÅôΩ»ÅÿÅ•∏ÅŸÖ±’ïÃ(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅÕ’â—•—±îÄÙÄâYï±úÉ•∏Åï±±ï»Åô±ï…îÅŸï…ë•ï»àÄ¨Ä†àÄ°ŸÖ±ùô…•—–§àÅ•òÅΩ¡—•ΩπÖ∞Åï±ÕîÄàà§(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúúúÒëï—Ö•±ÃÅç±ÖÕÃÙâô•±—ï»µëêàÅëÖ—Ñµô•±—ï»µëêÙâÌ≠ïÂÙà¯(ÄÄÄÄÒÕ’µµÖ…‰¯(ÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâô•±—ï»µëêµ•çΩ∏à˘Ì•çΩπÙΩÕ¡Ö∏¯(ÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâô•±—ï»µëêµ—ï·–à¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâô•±—ï»µëêµ±Öâï∞à˘ÌïÕçÖ¡î°±Öâï∞•ÙΩÕ¡Ö∏¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâô•±—ï»µëêµÕ’ààÅëÖ—ÑµÕ’µµÖ…‰µôΩ»ÙâÌ≠ïÂÙà˘ÌÕ’â—•—±ïÙΩÕ¡Ö∏¯(ÄÄÄÄÄÄΩÕ¡Ö∏¯(ÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâô•±—ï»µëêµç°ïŸ…Ω∏àÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˚äZ¯ΩÕ¡Ö∏¯(ÄÄÄÄΩÕ’µµÖ…‰¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâô•±—ï»µëêµ¡Öπï∞àÅ…Ω±îÙâù…Ω’¿àÅÖ…•Ñµ±Öâï∞Ùâ•±—…ï»Åï——ï»ÅÌïÕçÖ¡î°±Öâï∞π±Ω›ï»†§•Ùà˘Ìç°•¡ÕÙΩë•ÿ¯(ÄÄΩëï—Ö•±Ã¯úúú((ÄÄÄÄåÅIï≠≠ïõ·±ùîÅ	Ä¥¯Å%Ä¥¯ÅYÖππ•ππ°Ω±êÅÕ•Õ–Ä†»¿»ÿ¥¿‰¥¿‘∞ÅÖŸ—Ö±–Åµïê(ÄÄÄÄåÅâ…’≠ï»§ËÅ	Ω%Åï»Åï∏Å…ïï±∞Å—•±¡ÖÕπ•πùÕïùïπÕ≠Ö¿Ä°πÂ——•úÅôΩ»ÉîÅô•ππî(ÄÄÄÄåÅ¡…Ωë’≠—ï»ÅµïêÅâïÕ—ïµ—îÅÕ¡ïÕ•ô•≠ÖÕ©Ωπï»Ä¥¥Å%--Åï∏Å√ïÕ—ÖπêÅΩ¥ÅÖ–ÅÕÖµµî(ÄÄÄÄåÅ—Ö±∞Åù´·»Å¡…Ωë’≠—ï»Åµïë•Õ•πÕ¨Å’—âÂ——âÖ…î§∞ÅŸÖππ•ππ°Ω±êÅï»Åï∏ÅµÂ≠ï…î∞(ÄÄÄÄåÅµï»ÅÕï≠’πìô»ÅïùïπÕ≠Ö¿ÅΩúÅëï…ôΩ»ÅµÖ…≠ï…–Äà°ŸÖ±ùô…•—–§àÅΩúÅ¡±ÖÕÕï…–ÅÕ•Õ–∏(ÄÄÄÄåÅ±±îÅ—…îÅï»Åµ’±—§µÕï±ïç–Ä°≠Ö∏ÅŸï±ùîÅô±ï…îÅŸï…ë•ï»ÅÕÖµ—•ë•úÅ¡ï»Åôï±–§∏(ÄÄÄÅâç}ëë}°—µ∞ÄÙÅô•—}ë…Ω¡ëΩ›π}°—µ∞†ââåà∞Äâ	ÖÕ•Õ≠’…ŸîÄ°	§à∞Åâç}ŸÖ±’ïÃ∞Å±ÖµâëÑÅÿËÅòâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÅµ¥à∞Å	M%M-UIY}%=9}MY§(ÄÄÄÅë•Ö}ëë}°—µ∞ÄÙÅô•—}ë…Ω¡ëΩ›π}°—µ∞†âë•Ñà∞Äâ•Öµï—ï»Ä°%§à∞Åë•Ö}ŸÖ±’ïÃ∞Å±ÖµâëÑÅÿËÅòâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÅµ¥à∞Å%5QI}%=9}MY§(ÄÄÄÅ›ç}ëë}°—µ∞ÄÙÅô•—}ë…Ω¡ëΩ›π}°—µ∞†â›åà∞ÄâYÖππ•ππ°Ω±êà∞Å›ç}ŸÖ±’ïÃ∞Å±ÖµâëÑÅÿËÅòâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÄîà∞ÅI=A1Q}%=9}MY∞ÅΩ¡—•ΩπÖ∞ıQ…’î§(ÄÄÄÅô•±—ï…}ëë}°—µ∞ÄÙÅâç}ëë}°—µ∞Ä¨Åë•Ö}ëë}°—µ∞Ä¨Å›ç}ëë}°—µ∞((ÄÄÄÅù’•ëïÕ}°—µ∞ÄÙÄâq∏àπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúÒ±§¯ÒÑÅ°…ïòÙàΩù’•ëîΩÌïÕçÖ¡î°ùlâÕ±’úât•Ùºà˘ÌïÕçÖ¡î°ùlâ—•—±îât•ÙΩÑ¯Ω±§¯úÅôΩ»ÅúÅ•∏ÅçÖ—ïùΩ…‰πùï–†âù’•ëïÃà∞Åmt§(ÄÄÄÄ§((ÄÄÄÄåÅÖ—Öë…ïŸï–Å•π—…ºÄ¥¥ÅÖ±±îÄ‘Å≠Ö—ïùΩ…§µ•π—…Ωï»Å§Å¡…Ωë’ç—Õ}µï—Ñπ©ÕΩ∏Åëï±ï»(ÄÄÄÄåÅª·ÂÖ≠—•úÅëïππîÅ°Ö±ï∏Ä†âô…ÑÅÖ±±îÅµï…≠ï»ÅŸ§Åõ·±ùï»à§∞Åï…Õ—Ö——ï–Åµïê(ÄÄÄÄåÅï≠—î∞Å±•ŸîÅ—Ö±∞Ä†»¿»ÿ¥¿‰¥¿‘µ…ïëïÕ•ùπï–§∏ÅMÖµµîÅ—ï≠Õ–Åâ…’≠ïÃÅ§(ÄÄÄÄåÅµï—ÑµëïÕç…•¡—•Ω∏ΩΩúµµï—Ñ∞Å•≠≠îÅâÖ…îÅ§ÅÕÂπ±•úÅ ƒµ•π—…º∏(ÄÄÄÅ•π—…Ω}—ï·–ÄÙÅçÖ—ïùΩ…Âlâ•π—…ºâtπ…ï¡±Öçî†(ÄÄÄÄÄÄÄÄâô…ÑÅÖ±±îÅµï…≠ï»ÅŸ§Åõ·±ùï»à∞(ÄÄÄÄÄÄÄÅòâô…ÑÅÌπ}â…ÖπëÕÙÅµï…≠ï»ÅΩúÅÌπ}¡…Ωë’ç—ÕÙÅ¡…Ωë’≠—ï»à∞(ÄÄÄÄ§((ÄÄÄÄåÄâ!ŸÑÅï»Å`¸àµâΩ≠ÃËÅ≠Ω…–∞ÅôÖ≠—ÖâÖÕï…–ÅôΩ…≠±Ö…•πúÄ¨Å±ïπ≠îÅ—•∞Åõ·…Õ—îÅù’•ëî(ÄÄÄÄåÅ§Å≠Ö—ïùΩ…•ïπÃÅïùï∏Åù’•ëîµ±•Õ—îÄ°•πùï∏Å°Ö…ë≠Ωëï–Åù’•ëîµÕ±’úÅ°ï»§∏Åùï∏(ÄÄÄÄåÅ—ïùπï–Å±•πÕîµ•±±’Õ—…ÖÕ©Ω∏Ä°—ºÅΩŸï…±Ö¡¡ïπëîÅ±•πÕï»§Å§ÅÕ—ïëï–ÅôΩ»Åï∏(ÄÄÄÄåÅ±•—ï∏Å•≠Ω∏µâÖëùîÄ¥¥ÅÕÖµµîÅùïπï…•Õ≠îÅµΩ—•ÿÅôΩ»ÅÖ±±îÄ‘Å≠Ö—ïùΩ…•ï»∞ÅÕ•ëï∏(ÄÄÄÄåÅëï——îÅ°Öπë±ï»ÅΩ¥ÅÖ–Åëï–ÅHÅï∏Å≠Ωπ—Ö≠—±•πÕî∞Å•≠≠îÅΩ¥ÅÕï±ŸîÅ≠Ö—ïùΩ…•ï∏∏(ÄÄÄÅï·¡±Ö•πï…}—ï·–ÄÙÅQ=Ie}aA1%9ILπùï–°çÖ—ïùΩ…Â}Õ±’ú∞Äàà§(ÄÄÄÅçÖ—ïùΩ…Â}ù’•ëïÃÄÙÅçÖ—ïùΩ…‰πùï–†âù’•ëïÃà∞Åmt§(ÄÄÄÅï·¡±Ö•πï…}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅï·¡±Ö•πï…}—ï·–ÅÖπêÅçÖ—ïùΩ…Â}ù’•ëïÃË(ÄÄÄÄÄÄÄÅï·¡±Ö•πï…}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µï·¡±Ö•πï»à¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µï·¡±Ö•πï»µ•±±’Õ—…Ö—•Ω∏à˘Ì19M}A%I}%11UMQIQ%=9}MYÙΩë•ÿ¯(ÄÄÄÄÒë•ÿ¯(ÄÄÄÄÄÄÒ†»˘!ŸÑÅï»ÅÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞âtπ±Ω›ï»†§•Ù¸Ω†»¯(ÄÄÄÄÄÄÒ¿˘ÌïÕçÖ¡î°ï·¡±Ö•πï…}—ï·–•ÙΩ¿¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩù’•ëîΩÌïÕçÖ¡î°çÖ—ïùΩ…Â}ù’•ëïÕl¡ulâÕ±’úât•Ùºà˘1ïÃÅµï»ÉäHΩÑ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄâ=¥Å’—ŸÖ±ùï–àµΩ¡¡Õ’µµï…•πúÅ’πëï»Å¡…Ωë’≠—±•Õ—ï∏ËÅï≠—îÅâï…ïùπïëîÅÕ¡ïπ∏(ÄÄÄÄåÄ°Ö±ë…§ÅïùπîÅÕΩπïâΩ±≠ï»Ω≠±ÖÕÕ•ô•Õï…•πùï»Ä¥¥Åï≠—îÅ—Ö±±Ÿï…ë•ï»Åï»(ÄÄÄÄåÅ¡…Ωë’≠—ïùïπÕ≠Ö¡ï»∞Åï∏ÅÕΩπïâΩ±¨ÅŸ•±±îÅ€ô…–Åï∏Å—Ω±≠π•πúÅŸ§ÅÕï±ÿ(ÄÄÄÄåÅ•π—…Ωë’Õï…ï»§∏ÅMÖµµîÄâ’—ï±Ö–Å°ï±–Åëï»ÅôΩ»Å±•—îÅëÖ—Ñàµ¡…•πÕ•¡¿ÅÕΩ¥(ÄÄÄÄåÅô•±—…ïπîÄ¥¥Å≠’∏ÅÕ¡ïπ∏ÅµïêÄ¯Ù»Åë•Õ—•π≠—îÅŸï…ë•ï»ÅŸ•ÕïÃ∏(ÄÄÄÅëïòÅ}…Öπùï}—ï·–°ŸÖ±’ïÃËÅ±•Õ—mÕ—…t∞Å’π•–ËÅÕ—»§Ä¥¯ÅÕ—»ÅÅ9ΩπîË(ÄÄÄÄÄÄÄÅ•òÅ±ï∏°ŸÖ±’ïÃ§ÄÄ»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ…ï—’…∏Å9Ωπî(ÄÄÄÄÄÄÄÅ±º∞Å°§ÄÙÅŸÖ±’ïÕl¡tπ…ï¡±Öçî†à∏à∞Äà∞à§∞ÅŸÖ±’ïÕl¥≈tπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅ…ï—’…∏Å9ΩπîÅ•òÅ±ºÄÙÙÅ°§Åï±ÕîÅòâÌ±Ω˜äMÌ°•ÙÅÌ’π•—Ùà((ÄÄÄÅ…Öπùï}â•—ÃÄÙÅmt(ÄÄÄÅâç}…Öπùî∞Åë•Ö}…Öπùî∞Å›ç}…ÖπùîÄÙÅ}…Öπùï}—ï·–°âç}ŸÖ±’ïÃ∞Äâµ¥à§∞Å}…Öπùï}—ï·–°ë•Ö}ŸÖ±’ïÃ∞Äâµ¥à§∞Å}…Öπùï}—ï·–°›ç}ŸÖ±’ïÃ∞Äàîà§(ÄÄÄÅ•òÅâç}…ÖπùîË(ÄÄÄÄÄÄÄÅ…Öπùï}â•—ÃπÖ¡¡ïπê°òââÖÕ•Õ≠’…ŸîÅô…ÑÅÌâç}…ÖπùïÙà§(ÄÄÄÅ•òÅë•Ö}…ÖπùîË(ÄÄÄÄÄÄÄÅ…Öπùï}â•—ÃπÖ¡¡ïπê°òâë•Öµï—ï»Åô…ÑÅÌë•Ö}…ÖπùïÙà§(ÄÄÄÅ•òÅ›ç}…ÖπùîË(ÄÄÄÄÄÄÄÅ…Öπùï}â•—ÃπÖ¡¡ïπê°òâŸÖππ•ππ°Ω±êÅô…ÑÅÌ›ç}…ÖπùïÙà§(ÄÄÄÅçÖ—ïùΩ…Â}Õ’µµÖ…Â}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ…Öπùï}â•—ÃË(ÄÄÄÄÄÄÄÅâ•—Õ}—ï·–ÄÙÅ…Öπùï}â•—Õl¡tÅ•òÅ±ï∏°…Öπùï}â•—Ã§ÄÙÙÄƒÅï±ÕîÄà∞Äàπ©Ω•∏°…Öπùï}â•—ÕlË¥≈t§Ä¨ÄàÅΩúÄàÄ¨Å…Öπùï}â•—Õl¥≈t(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}Õ’µµÖ…Â}°—µ∞ÄÙÅòúúúÒÕïç—•Ω∏Åç±ÖÕÃÙâ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰àÅÖ…•Ñµ±Öâï∞Ùâ=¥Å’—ŸÖ±ùï–à¯(ÄÄÒ¿¯ÒÕ—…Ωπú˘=¥Å’—ŸÖ±ùï–ËΩÕ—…Ωπú¯Å-Ωπ—Ö≠—±•πÕï»ππºÅÕÖµµïπ±•ùπï»ÅôΩ»Å—•ëï∏ÅÌπ}¡…Ωë’ç—ÕÙÅÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞âtπ±Ω›ï»†§•ÙÅô…ÑÅÌπ}â…ÖπëÕÙÅµï…≠ï»∏ÅA…Ωë’≠—ïπîÅ§ÅΩŸï…Õ•≠—ï∏Å°Ö»ÅÌâ•—Õ}—ï·—Ù∏Ω¿¯(ΩÕïç—•Ω∏¯úúú((ÄÄÄÅÕç°ïµÖ}•—ïµÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÅÌ§¨≈Ù∞Äâ’…∞àËÄâÌ	M}UI1ÙΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°¡lâπÖµîât•ÙâıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å§∞Å¿Å•∏Åïπ’µï…Ö—î°¡…Ωë’ç—Ã§(ÄÄÄÄ§(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞ât•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩ≠Ωπ—Ö≠—±•πÕï»ΩÌçÖ—ïùΩ…Â}Õ±’ùÙºâıÙ(ÄÄÄÅuıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ%—ïµ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅmÌÕç°ïµÖ}•—ïµÕıuıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘	•±±•ùîÅÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞âtπ±Ω›ï»†§•ÙÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°•π—…Ω}—ï·–•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩ≠Ωπ—Ö≠—±•πÕï»ΩÌçÖ—ïùΩ…Â}Õ±’ùÙºà¯)Ì}Ωù}µï—Ñ°òù	•±±•ùîÅÌçÖ—ïùΩ…Âlâ±Öâï∞âtπ±Ω›ï»†•ÙÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Å•π—…Ω}—ï·–∞ÅòùÌ	M}UI1ÙΩ≠Ωπ—Ö≠—±•πÕï»ΩÌçÖ—ïùΩ…Â}Õ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯(ÒÕ—Â±î˘ÌM!I}MQe1Ù(π°ï…ºÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅùÖ¿ËÄ»·¡‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅıÙ(π°ï…ºµçΩ¡‰ÅÌÏÅô±ï‡ËÄƒÄƒÄÃ»¡¡‡ÏÅµÖ‡µ›•ë—†ËÄÿ‡¡¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µÕ—Ö—ÃÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ·¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄ—¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µÕ—Ö–ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅùÖ¿ËÄ›¡‡ÏÅô±ï‡ËÄƒÄƒÅÖ’—ºÏÅ¡Öëë•πúËÄ·¡‡Äƒ—¡‡ÏÅâΩ…ëï»µ…•ù°–ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅ›°•—îµÕ¡ÖçîËÅπΩ›…Ö¿ÏÅıÙ(πçÖ—ïùΩ…‰µÕ—Ö–È±ÖÕ–µç°•±êÅÌÏÅâΩ…ëï»µ…•ù°–ËÅπΩπîÏÅıÙ(πçÖ—ïùΩ…‰µÕ—Ö–ÅÕŸúÅÌÏÅ›•ë—†ËÄƒŸ¡‡ÏÅ°ï•ù°–ËÄƒŸ¡‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»ÅÌÏÅô±ï‡ËÄ¿ÄƒÄÃ¿¡¡‡ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒ¡¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅ¡Öëë•πúËÄƒ·¡‡Ä»¡¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»µ•±±’Õ—…Ö—•Ω∏ÅÌÏÅÖ±•ù∏µÕï±òËÅô±ï‡µÕ—Ö…–ÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»µ•±±’Õ—…Ö—•Ω∏ÅÕŸúÅÌÏÅ›•ë—†ËÄƒƒ¡¡‡ÏÅ°ï•ù°–ËÄ‹…¡‡ÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ¿∏‰’…ï¥ÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»Å¿ÅÌÏÅµÖ…ù•∏ËÄ¿Ä¿Ä—¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡—…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»ÅÑÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡—…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅıÙ(πçÖ—ïùΩ…‰µï·¡±Ö•πï»ÅÑÈ°ΩŸï»ÅÌÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅ’πëï…±•πîÏÅıÙ(πçÖ—ïùΩ…‰µô•±—ï…ÃµâÖ»ÅÌÏÅµÖ…ù•∏ËÄ»Ÿ¡‡Ä¿Ä»¡¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µâ…Öπêµ…Ω‹ÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄƒ·¡‡ÏÅıÙ(πçÖ—ïùΩ…‰µô•±—ï…Ãµ±Öâï∞ÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄ·¡‡ÏÅıÙ(πâ…Öπêµç°•¿µ…Ω‹ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅùÖ¿ËÄ·¡‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅıÙ(πâ…Öπêµç°•¿µ…Ω›m°•ëëïπtÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πâ…ÖπêµµΩ…îµ›…Ö¿ÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄ·¡‡ÏÅıÙ(πç°•¿µçΩ’π–ÅÌÏÅΩ¡Öç•—‰ËÄ¿∏ÿÏÅôΩπ–µ›ï•ù°–ËÄ‘¿¿ÏÅıÙ(πç°•¿πÖç—•ŸîÄπç°•¿µçΩ’π–ÅÌÏÅΩ¡Öç•—‰ËÄ¿∏‡‘ÏÅıÙ(πç°•¿µù°ΩÕ–ÅÌÏÅâÖç≠ù…Ω’πêËÅ—…ÖπÕ¡Ö…ïπ–ÏÅâΩ…ëï»µÕ—Â±îËÅëÖÕ°ïêÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(πô•±—ï»µ—…•ùùï»ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅùÖ¿ËÄ·¡‡ÏÅ›•ë—†ËÄƒ¿¿îÏÅ¡Öëë•πúËÄƒ…¡‡ÄƒŸ¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅâΩ…ëï»ËÅπΩπîÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅıÙ(πô•±—ï»µ—…•ùùï»µâÖëùîÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’î§ÏÅçΩ±Ω»ËÅ›°•—îÏÅôΩπ–µÕ•ÈîËÄ¿∏‹……ï¥ÏÅµ•∏µ›•ë—†ËÄƒ·¡‡ÏÅ°ï•ù°–ËÄƒ·¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‰‰Â¡‡ÏÅë•Õ¡±Ö‰ËÅ•π±•πîµô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅ¡Öëë•πúËÄ¿Ä’¡‡ÏÅıÙ(πô•±—ï»µ—…•ùùï»µâÖëùïm°•ëëïπtÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πô•±—ï»µâÖç≠ë…Ω¿ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πçÖ—ïùΩ…‰µô•±—ï…ÃÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(πô•±—ï»µÕ°ïï–µ°ïÖëï»∞Äπô•±—ï»µÕ°ïï–µôΩΩ—ï»ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πô•±—ï»µëêÅÌÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅıÙ(πô•±—ï»µëêÄ¯ÅÕ’µµÖ…‰ÅÌÏÅ±•Õ–µÕ—Â±îËÅπΩπîÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄ·¡‡ÏÅ¡Öëë•πúËÄƒ¡¡‡Äƒ—¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅ’Õï»µÕï±ïç–ËÅπΩπîÏÅıÙ(πô•±—ï»µëêÄ¯ÅÕ’µµÖ…‰ËËµ›ïâ≠•–µëï—Ö•±ÃµµÖ…≠ï»ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πô•±—ï»µëêµ•çΩ∏ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅıÙ(πô•±—ï»µëêµ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄƒŸ¡‡ÏÅ°ï•ù°–ËÄƒŸ¡‡ÏÅıÙ(πô•±—ï»µëêµ—ï·–ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÃÏÅıÙ(πô•±—ï»µëêµ±Öâï∞ÅÌÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅıÙ(πô•±—ï»µëêµÕ’àÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹—…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(πô•±—ï»µëêµç°ïŸ…Ω∏ÅÌÏÅµÖ…ù•∏µ±ïô–ËÅÖ’—ºÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏ƒ’ÃÏÅıÙ(πô•±—ï»µëëmΩ¡ïπtÄπô•±—ï»µëêµç°ïŸ…Ω∏ÅÌÏÅ—…ÖπÕôΩ…¥ËÅ…Ω—Ö—î†ƒ‡¡ëïú§ÏÅıÙ(πô•±—ï»µëêµ¡Öπï∞ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅùÖ¿ËÄ·¡‡ÏÅ¡Öëë•πúËÄƒ¡¡‡Ä—¡‡Ä…¡‡ÏÅıÙ(πÖç—•Ÿîµô•±—ï…Ãµ›…Ö¿ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ…¡‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿Ä»¡¡‡ÏÅıÙ(πÖç—•Ÿîµô•±—ï…Ãµ›…Ö¡m°•ëëïπtÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πÖç—•Ÿîµô•±—ï…ÃÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅùÖ¿ËÄ·¡‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅıÙ(πÖç—•Ÿîµô•±—ï»µç°•¿ÅÌÏÅë•Õ¡±Ö‰ËÅ•π±•πîµô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄŸ¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’îµëÖ…¨§ÏÅâΩ…ëï»ËÅπΩπîÏÅâΩ…ëï»µ…Öë•’ÃËÄ‰‰Â¡‡ÏÅ¡Öëë•πúËÄŸ¡‡Äƒ¡¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅıÙ(πô•±—ï»µ…ïÕï–µ±•π¨ÅÌÏÅë•Õ¡±Ö‰ËÅ•π±•πîµô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄŸ¡‡ÏÅâÖç≠ù…Ω’πêËÅπΩπîÏÅâΩ…ëï»ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅ¡Öëë•πúËÄ¿ÏÅıÙ(πô•±—ï»µ…ïÕï–µ±•π¨ÅÕŸúÅÌÏÅ›•ë—†ËÄƒ—¡‡ÏÅ°ï•ù°–ËÄƒ—¡‡ÏÅıÙ(πÕΩ…–µÕï±ïç–ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡……ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‰‰Â¡‡ÏÅ¡Öëë•πúËÄ·¡‡ÄÃ¡¡‡Ä·¡‡Äƒ—¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÅ’…∞†âëÖ—ÑÈ•µÖùîΩÕŸú≠·µ∞∞îÕÕŸúÅ·µ±πÃÙù°——¿ËºΩ››‹π‹ÃπΩ…úº»¿¿¿ΩÕŸúúÅŸ•ï›	Ω‡Ùú¿Ä¿Ä»–Ä»–úÅô•±∞ÙùπΩπîúÅÕ—…Ω≠îÙúî»Ãÿ–‹–·úÅÕ—…Ω≠îµ›•ë—†Ùú»úîÕîÕ¡Ö—†ÅêÙù4ÿÄÂ∞ÿÄÿÄÿ¥ÿúºîÕîÕΩÕŸúîÕà§Åπºµ…ï¡ïÖ–Å…•ù°–Äƒ¡¡‡Åçïπ—ï»ÄºÄƒ—¡‡Äƒ—¡‡ÏÅÖ¡¡ïÖ…ÖπçîËÅπΩπîÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§ÅÌÏ(ÄÄπô•±—ï»µëêµ¡Öπï∞ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ—Ω¿ËÅçÖ±å†ƒ¿¿îÄ¨ÄŸ¡‡§ÏÅ±ïô–ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅµ•∏µ›•ë—†ËÄ»ÿ¡¡‡ÏÅËµ•πëï‡ËÄ»¿ÏÅıÙ)ıÙ)µïë•ÑÄ°µÖ‡µ›•ë—†ËÄƒ¿»Õ¡‡§ÅÌÏ(ÄÄπô•±—ï»µ—…•ùùï»ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µô•±—ï…ÃÅÌÏÅ¡ΩÕ•—•Ω∏ËÅô•·ïêÏÅ±ïô–ËÄ¿ÏÅ…•ù°–ËÄ¿ÏÅâΩ——Ω¥ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ·¡‡Äƒ·¡‡Ä¿Ä¿ÏÅ¡Öëë•πúËÄƒ·¡‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ‡µ°ï•ù°–ËÄ‡…Ÿ†ÏÅΩŸï…ô±Ω‹µ‰ËÅÖ’—ºÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†ƒ¿‘î§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏»’ÃÅïÖÕîÏÅËµ•πëï‡ËÄÿ¿ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä¥·¡‡ÄÃ¡¡‡Å…ùâÑ†ƒƒ∞Ã‹∞ÿ‰∞¿∏ƒ‡§ÏÅıÙ(ÄÄπçÖ—ïùΩ…‰µô•±—ï…Ãπ•ÃµΩ¡ï∏ÅÌÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¿§ÏÅıÙ(ÄÄπô•±—ï»µëêÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅıÙ(ÄÄπô•±—ï»µÕ°ïï–µ°ïÖëï»ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅıÙ(ÄÄπô•±—ï»µÕ°ïï–µ°ïÖëï»Å†»ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(ÄÄπô•±—ï»µÕ°ïï–µç±ΩÕîÅÌÏÅâÖç≠ù…Ω’πêËÅπΩπîÏÅâΩ…ëï»ËÅπΩπîÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ¡Öëë•πúËÄ—¡‡ÏÅıÙ(ÄÄπô•±—ï»µÕ°ïï–µç±ΩÕîÅÕŸúÅÌÏÅ›•ë—†ËÄ»¡¡‡ÏÅ°ï•ù°–ËÄ»¡¡‡ÏÅıÙ(ÄÄπô•±—ï»µÕ°ïï–µôΩΩ—ï»ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄŸ¡‡ÏÅ¡ΩÕ•—•Ω∏ËÅÕ—•ç≠‰ÏÅâΩ——Ω¥ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅ¡Öëë•πúµ—Ω¿ËÄƒ¡¡‡ÏÅıÙ(ÄÄπâ—∏µ¡…•µÖ…‰µâ±Ωç¨ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’î§ÏÅçΩ±Ω»ËÅ›°•—îÏÅâΩ…ëï»ËÅπΩπîÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅ¡Öëë•πúËÄƒÕ¡‡ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅıÙ(ÄÄπô•±—ï»µâÖç≠ë…Ω¿ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅô•·ïêÏÅ•πÕï–ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅ…ùâÑ†ƒƒ∞Ã‹∞ÿ‰∞¿∏Ã‘§ÏÅËµ•πëï‡ËÄ‘‘ÏÅıÙ(ÄÄπô•±—ï»µâÖç≠ë…Ω¡m°•ëëïπtÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ)ıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞ât•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘-Ö—ïùΩ…§Ωë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°çÖ—ïùΩ…Âlâ±Öâï∞ât•ÙΩ†ƒ¯(ÄÄÄÄÄÄÒ¿˘ÌïÕçÖ¡î°•π—…Ω}—ï·–•ÙΩ¿¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µÕ—Ö—Ãà¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâçÖ—ïùΩ…‰µÕ—Ö–à˘Ì	=a}%=9}MYÙÒÕ¡Ö∏˘Ìπ}¡…Ωë’ç—ÕÙÅ¡…Ωë’≠—ï»ΩÕ¡Ö∏¯ΩÕ¡Ö∏¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâçÖ—ïùΩ…‰µÕ—Ö–à˘ÌQ}%=9}MYÙÒÕ¡Ö∏˘Ìπ}â…ÖπëÕÙÅµï…≠ï»ΩÕ¡Ö∏¯ΩÕ¡Ö∏¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâçÖ—ïùΩ…‰µÕ—Ö–à¯ÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏ÿàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì}	U%1%9}%=9ÙΩÕŸú¯ÒÕ¡Ö∏˘9Ω…Õ≠îÅπï——â’—•≠≠ï»ΩÕ¡Ö∏¯ΩÕ¡Ö∏¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâçÖ—ïùΩ…‰µÕ—Ö–à˘Ì19I}%=9}MYÙÒÕ¡Ö∏˘A…•Õï»ÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•úΩÕ¡Ö∏¯ΩÕ¡Ö∏¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µâ…Öπêµ…Ω‹à¯(ÄÄÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâçÖ—ïùΩ…‰µô•±—ï…Ãµ±Öâï∞à˘AΩ¡’≥ô…îÅµï…≠ï»ΩÕ¡Ö∏¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµç°•¿µ…Ω‹à¯(ÄÄÄÄÄÄÄÄÄÅÌ¡Ω¡’±Ö…}ç°•¡Õ}°—µ±Ù(ÄÄÄÄÄÄÄÄÄÅÌÕ°Ω›}Ö±±}—Ωùù±ï}°—µ±Ù(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµç°•¿µ…Ω‹Åâ…ÖπêµµΩ…îµ›…Ö¿àÅ•êÙââ…ÖπêµµΩ…îµ›…Ö¿àÅ°•ëëï∏¯(ÄÄÄÄÄÄÄÄÄÅÌ…ïÕ—}ç°•¡Õ}°—µ±Ù(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÅÌï·¡±Ö•πï…}°—µ±Ù(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µô•±—ï…ÃµâÖ»à¯(ÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâô•±—ï»µ—…•ùùï»àÅ•êÙâô•±—ï»µ—…•ùùï»à¯(ÄÄÄÄÄÅ•±—…ï»Å¡…Ωë’≠—ï»(ÄÄÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâô•±—ï»µ—…•ùùï»µâÖëùîàÅ•êÙâô•±—ï»µ—…•ùùï»µâÖëùîàÅ°•ëëï∏¯¿ΩÕ¡Ö∏¯(ÄÄÄÄΩâ’——Ω∏¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâô•±—ï»µâÖç≠ë…Ω¿àÅ•êÙâô•±—ï»µâÖç≠ë…Ω¿àÅ°•ëëï∏¯Ωë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâçÖ—ïùΩ…‰µô•±—ï…ÃàÅ•êÙâçÖ—ïùΩ…‰µô•±—ï…Ãà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâô•±—ï»µÕ°ïï–µ°ïÖëï»à¯(ÄÄÄÄÄÄÄÄÒ†»˘•±—…ï»Å¡…Ωë’≠—ï»Ω†»¯(ÄÄÄÄÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâô•±—ï»µÕ°ïï–µç±ΩÕîàÅ•êÙâô•±—ï»µÕ°ïï–µç±ΩÕîàÅÖ…•Ñµ±Öâï∞Ùâ1’≠¨Åô•±—ï»à˘Ìa}%=9}MYÙΩâ’——Ω∏¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÅÌô•±—ï…}ëë}°—µ±Ù(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâô•±—ï»µÕ°ïï–µôΩΩ—ï»à¯(ÄÄÄÄÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙââ—∏µ¡…•µÖ…‰µâ±Ωç¨àÅ•êÙâÕ°ïï–µÕ°Ω‹µçΩ’π–à˘Y•ÃÅÌπ}¡…Ωë’ç—ÕÙÅ¡…Ωë’≠—ï»Ωâ’——Ω∏¯(ÄÄÄÄÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâô•±—ï»µ…ïÕï–µ±•π¨àÅëÖ—Ñµ…ïÕï–µô•±—ï…ÃÅÕ—Â±îÙâ©’Õ—•ô‰µçΩπ—ïπ–Èçïπ—ï»Ïà˘ÌIMQ}%=9}MYÙÅ9’±±Õ—•±∞ÅÖ±±îÅô•±—…îΩâ’——Ω∏¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâÖç—•Ÿîµô•±—ï…Ãµ›…Ö¿àÅ•êÙâÖç—•Ÿîµô•±—ï…Ãµ›…Ö¿àÅ°•ëëï∏¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÖç—•Ÿîµô•±—ï…ÃàÅ•êÙâÖç—•Ÿîµô•±—ï…Ãà¯Ωë•ÿ¯(ÄÄÄÄÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâô•±—ï»µ…ïÕï–µ±•π¨àÅëÖ—Ñµ…ïÕï–µô•±—ï…Ã˘ÌIMQ}%=9}MYÙÅ9’±±Õ—•±∞ÅÖ±±îÅô•±—…îΩâ’——Ω∏¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ±•Õ–µ°ïÖëï»à¯(ÄÄÄÄÒ†»Å•êÙâ…ïÕ’±–µçΩ’π–à˘Ìπ}¡…Ωë’ç—ÕÙÅ¡…Ωë’≠—ï»Ω†»¯(ÄÄÄÄÒÕï±ïç–Å•êÙâÕΩ…–µÕï±ïç–àÅç±ÖÕÃÙâÕΩ…–µÕï±ïç–àÅÖ…•Ñµ±Öâï∞ÙâMΩ…—ï»Å¡…Ωë’≠—ï»à¯(ÄÄÄÄÄÄÒΩ¡—•Ω∏ÅŸÖ±’îÙâ¡…•çîµÖÕåà˘MΩ…—ï»ËÅ1ÖŸïÕ—îÅ¡…•ÃΩΩ¡—•Ω∏¯(ÄÄÄÄÄÄÒΩ¡—•Ω∏ÅŸÖ±’îÙâ¡…•çîµëïÕåà˘MΩ…—ï»ËÅ#·ÂïÕ—îÅ¡…•ÃΩΩ¡—•Ω∏¯(ÄÄÄÄΩÕï±ïç–¯(ÄÄΩë•ÿ¯((ÄÄÑ¥¥ÅM—Ö—•Õ¨∞ÅÖ±±ï…ïëîÅÕΩ…—ï…–Å±ÖŸïÕ–µõ·…Õ–∏Å)LÅ’πëï»Åï»Å≠’∏Åï∏ÅôΩ…âïë…•πú(ÄÄÄÄÄÄÄ°ô•±—ï»Ω…îµÕΩ…—ï…•πú§ÅΩŸïπ√îÅëï——îÄ¥Åô’πùï…ï»Å’—ï∏Å)LÅΩùœî∏Å±±î(ÄÄÄÄÄÄÅô•±—ï…Ÿï…ë•ï»ÅΩŸï»Åï»Åï≠—î∞ÅÕï…Ÿï»µ…ïπë…ïëîÅ≠πÖ¡¡ï»Ä°•≠≠îÅ°ïπ—ï–ÅŸ•Ñ(ÄÄÄÄÄÄÅ)L§Ä¥¥Å≠’∏ÅY%M9%98Ä£ï¡ï∏Ω±’≠≠ï–Åë…Ω¡ëΩ›∏∞ÅÕ°ïï–Å√îÅµΩâ•∞§Åï»Åï∏(ÄÄÄÄÄÄÅMLΩ)LµôΩ…âïë…•πú∏Ä¥¥¯(ÄÄÒë•ÿÅ•êÙâ¡…Ωë’ç–µ±•Õ–àÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµù…•êà¯(ÄÄÄÅÌ¡…Ωë’ç—}…Ω›Õ}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÄÒπΩÕç…•¡–¯Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‹·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà˘•±—…ï…•πúÅΩúÅÕΩ…—ï…•πúÅ≠…ïŸï»Å)ÖŸÖMç…•¡–∏Å1•Õ—ï∏ÅΩŸï»ÅŸ•Õï»ÅÖ±±îÅ¡…Ωë’≠—ï»∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏Ω¿¯ΩπΩÕç…•¡–¯((ÄÅÌçÖ—ïùΩ…Â}Õ’µµÖ…Â}°—µ±Ù((ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëïÃà¯(ÄÄÄÄÒ†»˘’•ëï»Ω†»¯(ÄÄÄÄÒ’∞˘Ìù’•ëïÕ}°—µ±ÙΩ’∞¯(ÄÄΩë•ÿ¯((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅY§ÅÕΩ…—ï…ï»ÅÖ±±—•êÅï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ÅY§Å≠Ö∏ÅõîÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Å°Öπë±ï»(ÄÄÄÅŸ•ÑÅ±ïπ≠ïπîÅ√îÅ¡…Ωë’≠—Õ•ëïπî∞Åµï∏Åëï–Å√ïŸ•…≠ï»Å•≠≠îÅ¡…•Õï∏Åë‘Åâï—Ö±ï»(ÄÄÄÅï±±ï»Å…Öπùï…•πùï∏ÅÖÿÅ¡…Ωë’≠—ï»Åï±±ï»Å—•±â’ê∏(ÄÄΩ¿¯(Ωë•ÿ¯((ÒÕç…•¡–¯(°ô’πç—•Ω∏Ä†§ÅÌÏ(ÄÅçΩπÕ–Å±•Õ–ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…Ωë’ç–µ±•Õ–ú§Ï(ÄÅçΩπÕ–Å…ïÕ’±—Ω’π–ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù…ïÕ’±–µçΩ’π–ú§Ï(ÄÅçΩπÕ–Åù…Ω’¡1Öâï±ÃÄÙÅÌÏÅâ…ÖπêËÄù5ï…≠îú∞ÅâåËÄù	ÖÕ•Õ≠’…Ÿîú∞Åë•ÑËÄù•Öµï—ï»ú∞Å›åËÄùYÖππ•ππ°Ω±êúÅıÙÏ(ÄÅçΩπÕ–ÅÕï±ïç—•ΩπÃÄÙÅÌÏÅâ…ÖπêËÅπï‹ÅMï–†§∞ÅâåËÅπï‹ÅMï–†§∞Åë•ÑËÅπï‹ÅMï–†§∞Å›åËÅπï‹ÅMï–†§ÅıÙÏ(ÄÅçΩπÕ–ÅÖç—•Ÿï•±—ï…Õ]…Ö¿ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùÖç—•Ÿîµô•±—ï…Ãµ›…Ö¿ú§Ï(ÄÅçΩπÕ–ÅÖç—•Ÿï°•¡Õ∞ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùÖç—•Ÿîµô•±—ï…Ãú§Ï((ÄÅô’πç—•Ω∏Åôµ—YÖ±’î°≠ï‰∞Åÿ§ÅÌÏ(ÄÄÄÅ•òÄ°≠ï‰ÄÙÙÙÄù›åú§Å…ï—’…∏Åÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú§Ä¨ÄúÄîúÏ(ÄÄÄÅ•òÄ°≠ï‰ÄÙÙÙÄùâåúÅÒÅ≠ï‰ÄÙÙÙÄùë•Ñú§Å…ï—’…∏Åÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú§Ä¨ÄúÅµ¥úÏ(ÄÄÄÅçΩπÕ–Åç°•¿ÄÙÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω»†úπç°•¡mëÖ—Ñµù…Ω’¿ÙàúÄ¨Å≠ï‰Ä¨ÄúâumëÖ—ÑµŸÖ±’îÙàúÄ¨ÅMLπïÕçÖ¡î°ÿ§Ä¨Äúâtú§Ï(ÄÄÄÅ…ï—’…∏Åç°•¿Ä¸Åç°•¿π—ï·—Ωπ—ïπ–π…ï¡±Öçî†ΩqqÃ©qqê≠qqÃ®êº∞Äúú§π—…•¥†§ÄËÅÿÏ(ÄÅıÙ((ÄÅô’πç—•Ω∏ÅÕÂπç°•¡ÕΩ»°ù…Ω’¿∞ÅŸÖ±’î§ÅÌÏ(ÄÄÄÅçΩπÕ–Å¡…ïÕÕïêÄÙÅÕï±ïç—•ΩπÕmù…Ω’¡tπ°ÖÃ°ŸÖ±’î§Ï(ÄÄÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπç°•¡mëÖ—Ñµù…Ω’¿ÙàúÄ¨Åù…Ω’¿Ä¨ÄúâumëÖ—ÑµŸÖ±’îÙàúÄ¨ÅMLπïÕçÖ¡î°ŸÖ±’î§Ä¨Äúâtú§πôΩ…Öç†°ï∞ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅï∞πÕï———…•â’—î†ùÖ…•Ñµ¡…ïÕÕïêú∞Å¡…ïÕÕïêÄ¸Äù—…’îúÄËÄùôÖ±Õîú§Ï(ÄÄÄÄÄÅï∞πç±ÖÕÕ1•Õ–π—Ωùù±î†ùÖç—•Ÿîú∞Å¡…ïÕÕïê§Ï(ÄÄÄÅıÙ§Ï(ÄÅıÙ((ÄÅçΩπÕ–Åô•±—ï…ëM’â—•—±ïÃÄÙÅÌÌıÙÏ(ÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†ùmëÖ—Ñµô•±—ï»µëëtú§πôΩ…Öç†°ëêÄÙ¯ÅÌÏ(ÄÄÄÅçΩπÕ–Å≠ï‰ÄÙÅëêπëÖ—ÖÕï–πô•±—ï…êÏ(ÄÄÄÅô•±—ï…ëM’â—•—±ïÕm≠ïÂtÄÙÅëêπ≈’ï…ÂMï±ïç—Ω»†ùmëÖ—ÑµÕ’µµÖ…‰µôΩ»ÙàúÄ¨Å≠ï‰Ä¨Äúâtú§Ï(ÄÅıÙ§Ï((ÄÅô’πç—•Ω∏Å’¡ëÖ—ï…Ω¡ëΩ›πM’â—•—±ïÃ†§ÅÌÏ(ÄÄÄÅ=â©ïç–π≠ïÂÃ°ô•±—ï…ëM’â—•—±ïÃ§πôΩ…Öç†°≠ï‰ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–Åï∞ÄÙÅô•±—ï…ëM’â—•—±ïÕm≠ïÂtÏ(ÄÄÄÄÄÅ•òÄ†Öï∞§Å…ï—’…∏Ï(ÄÄÄÄÄÅçΩπÕ–ÅÕï–ÄÙÅÕï±ïç—•ΩπÕm≠ïÂtÏ(ÄÄÄÄÄÅ•òÄ†ÖÕï–πÕ•Èî§ÅÌÏ(ÄÄÄÄÄÄÄÅï∞π—ï·—Ωπ—ïπ–ÄÙÄùYï±úÉ•∏Åï±±ï»Åô±ï…îÅŸï…ë•ï»úÄ¨Ä°≠ï‰ÄÙÙÙÄù›åúÄ¸ÄúÄ°ŸÖ±ùô…•—–§úÄËÄúú§Ï(ÄÄÄÄÄÅıÙÅï±ÕîÅÌÏ(ÄÄÄÄÄÄÄÅï∞π—ï·—Ωπ—ïπ–ÄÙÅ……Ö‰πô…Ω¥°Õï–§πµÖ¿°ÿÄÙ¯Åôµ—YÖ±’î°≠ï‰∞Åÿ§§π©Ω•∏†ú∞Äú§Ï(ÄÄÄÄÄÅıÙ(ÄÄÄÅıÙ§Ï(ÄÅıÙ((ÄÅô’πç—•Ω∏Å’¡ëÖ—ï•±—ï…	Öëùî†§ÅÌÏ(ÄÄÄÅçΩπÕ–ÅçΩ’π–ÄÙÅÕï±ïç—•ΩπÃπâåπÕ•ÈîÄ¨ÅÕï±ïç—•ΩπÃπë•ÑπÕ•ÈîÄ¨ÅÕï±ïç—•ΩπÃπ›åπÕ•ÈîÏ(ÄÄÄÅçΩπÕ–ÅâÖëùîÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùô•±—ï»µ—…•ùùï»µâÖëùîú§Ï(ÄÄÄÅ•òÄ°âÖëùî§ÅÌÏÅâÖëùîπ—ï·—Ωπ—ïπ–ÄÙÅçΩ’π–ÏÅâÖëùîπ°•ëëï∏ÄÙÅçΩ’π–ÄÙÙÙÄ¿ÏÅıÙ(ÄÅıÙ((ÄÅô’πç—•Ω∏Å…ïπëï…ç—•Ÿï•±—ï…Ã†§ÅÌÏ(ÄÄÄÅçΩπÕ–Å¡Ö…—ÃÄÙÅmtÏ(ÄÄÄÅ=â©ïç–π≠ïÂÃ°Õï±ïç—•ΩπÃ§πôΩ…Öç†°ù…Ω’¿ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅÕï±ïç—•ΩπÕmù…Ω’¡tπôΩ…Öç†°ŸÖ±’îÄÙ¯Å¡Ö…—Ãπ¡’Õ†°ÌÏÅù…Ω’¿∞ÅŸÖ±’îÅıÙ§§Ï(ÄÄÄÅıÙ§Ï(ÄÄÄÅ•òÄ†Ö¡Ö…—Ãπ±ïπù—†§ÅÌÏ(ÄÄÄÄÄÅÖç—•Ÿï•±—ï…Õ]…Ö¿π°•ëëï∏ÄÙÅ—…’îÏ(ÄÄÄÄÄÅÖç—•Ÿï°•¡Õ∞π•ππï…!Q50ÄÙÄúúÏ(ÄÄÄÅıÙÅï±ÕîÅÌÏ(ÄÄÄÄÄÅÖç—•Ÿï•±—ï…Õ]…Ö¿π°•ëëï∏ÄÙÅôÖ±ÕîÏ(ÄÄÄÄÄÅÖç—•Ÿï°•¡Õ∞π•ππï…!Q50ÄÙÅ¡Ö…—ÃπµÖ¿°¿ÄÙ¯(ÄÄÄÄÄÄÄÄúÒâ’——Ω∏Å—Â¡îÙââ’——Ω∏àÅç±ÖÕÃÙâÖç—•Ÿîµô•±—ï»µç°•¿àÅëÖ—Ñµ…ïµΩŸîµù…Ω’¿ÙàúÄ¨Å¿πù…Ω’¿Ä¨ÄúàÅëÖ—Ñµ…ïµΩŸîµŸÖ±’îÙàúÄ¨Å¿πŸÖ±’îπ…ï¡±Öçî†ºàΩú∞Äúô≈’Ω–Ïú§Ä¨Äúà¯úÄ¨(ÄÄÄÄÄÄÄÅù…Ω’¡1Öâï±Õm¿πù…Ω’¡tÄ¨ÄúËÄúÄ¨Åôµ—YÖ±’î°¿πù…Ω’¿∞Å¿πŸÖ±’î§Ä¨ÄúÄÒÕ¡Ö∏ÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˚ärTΩÕ¡Ö∏¯Ωâ’——Ω∏¯ú(ÄÄÄÄÄÄ§π©Ω•∏†úú§Ï(ÄÄÄÅıÙ(ÄÄÄÅ’¡ëÖ—ï•±—ï…	Öëùî†§Ï(ÄÄÄÅ’¡ëÖ—ï…Ω¡ëΩ›πM’â—•—±ïÃ†§Ï(ÄÅıÙ((ÄÅô’πç—•Ω∏ÅÖ¡¡±Â•±—ï…Ã†§ÅÌÏ(ÄÄÄÅ±ï–ÅŸ•Õ•â±îÄÙÄ¿Ï(ÄÄÄÅ±•Õ–π≈’ï…ÂMï±ïç—Ω…±∞†úπ¡…Ωë’ç–µ—•±îú§πôΩ…Öç†°çÖ…êÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–ÅÕ°Ω‹ÄÙÅ=â©ïç–π≠ïÂÃ°Õï±ïç—•ΩπÃ§πïŸï…‰°ù…Ω’¿ÄÙ¯ÅÌÏ(ÄÄÄÄÄÄÄÅçΩπÕ–ÅÕï–ÄÙÅÕï±ïç—•ΩπÕmù…Ω’¡tÏ(ÄÄÄÄÄÄÄÅ•òÄ†ÖÕï–πÕ•Èî§Å…ï—’…∏Å—…’îÏ(ÄÄÄÄÄÄÄÅçΩπÕ–ÅçÖ…ëYÖ±’ïÃÄÙÄ°çÖ…êπëÖ—ÖÕï—mù…Ω’¡tÅÒÄúú§πÕ¡±•–†úÄú§Ï(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅçÖ…ëYÖ±’ïÃπÕΩµî°ÿÄÙ¯ÅÕï–π°ÖÃ°ÿ§§Ï(ÄÄÄÄÄÅıÙ§Ï(ÄÄÄÄÄÅçÖ…êπÕ—Â±îπë•Õ¡±Ö‰ÄÙÅÕ°Ω‹Ä¸ÄúúÄËÄùπΩπîúÏ(ÄÄÄÄÄÅ•òÄ°Õ°Ω‹§ÅŸ•Õ•â±î¨¨Ï(ÄÄÄÅıÙ§Ï(ÄÄÄÅ…ïÕ’±—Ω’π–π—ï·—Ωπ—ïπ–ÄÙÅŸ•Õ•â±îÄ¨ÄúÅ¡…Ωë’≠—ï»úÏ(ÄÄÄÅçΩπÕ–ÅÕ°ïï—M°Ω‹ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùÕ°ïï–µÕ°Ω‹µçΩ’π–ú§Ï(ÄÄÄÅ•òÄ°Õ°ïï—M°Ω‹§ÅÕ°ïï—M°Ω‹π—ï·—Ωπ—ïπ–ÄÙÄùY•ÃÄúÄ¨ÅŸ•Õ•â±îÄ¨ÄúÅ¡…Ωë’≠—ï»úÏ(ÄÅıÙ((ÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπç°•¡mëÖ—Ñµù…Ω’¡tú§πôΩ…Öç†°â—∏ÄÙ¯ÅÌÏ(ÄÄÄÅâ—∏πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–Åù…Ω’¿ÄÙÅâ—∏πëÖ—ÖÕï–πù…Ω’¿∞ÅŸÖ±’îÄÙÅâ—∏πëÖ—ÖÕï–πŸÖ±’îÏ(ÄÄÄÄÄÅ•òÄ°Õï±ïç—•ΩπÕmù…Ω’¡tπ°ÖÃ°ŸÖ±’î§§ÅÕï±ïç—•ΩπÕmù…Ω’¡tπëï±ï—î°ŸÖ±’î§Ï(ÄÄÄÄÄÅï±ÕîÅÕï±ïç—•ΩπÕmù…Ω’¡tπÖëê°ŸÖ±’î§Ï(ÄÄÄÄÄÅÕÂπç°•¡ÕΩ»°ù…Ω’¿∞ÅŸÖ±’î§Ï(ÄÄÄÄÄÅ…ïπëï…ç—•Ÿï•±—ï…Ã†§Ï(ÄÄÄÄÄÅÖ¡¡±Â•±—ï…Ã†§Ï(ÄÄÄÅıÙ§Ï(ÄÅıÙ§Ï((ÄÅÖç—•Ÿï°•¡Õ∞πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞ÅîÄÙ¯ÅÌÏ(ÄÄÄÅçΩπÕ–Åâ—∏ÄÙÅîπ—Ö…ùï–πç±ΩÕïÕ–†ùmëÖ—Ñµ…ïµΩŸîµù…Ω’¡tú§Ï(ÄÄÄÅ•òÄ†Öâ—∏§Å…ï—’…∏Ï(ÄÄÄÅÕï±ïç—•ΩπÕmâ—∏πëÖ—ÖÕï–π…ïµΩŸï…Ω’¡tπëï±ï—î°â—∏πëÖ—ÖÕï–π…ïµΩŸïYÖ±’î§Ï(ÄÄÄÅÕÂπç°•¡ÕΩ»°â—∏πëÖ—ÖÕï–π…ïµΩŸï…Ω’¿∞Åâ—∏πëÖ—ÖÕï–π…ïµΩŸïYÖ±’î§Ï(ÄÄÄÅ…ïπëï…ç—•Ÿï•±—ï…Ã†§Ï(ÄÄÄÅÖ¡¡±Â•±—ï…Ã†§Ï(ÄÅıÙ§Ï((ÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†ùmëÖ—Ñµ…ïÕï–µô•±—ï…Õtú§πôΩ…Öç†°â—∏ÄÙ¯ÅÌÏ(ÄÄÄÅâ—∏πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅ=â©ïç–π≠ïÂÃ°Õï±ïç—•ΩπÃ§πôΩ…Öç†°ù…Ω’¿ÄÙ¯ÅÌÏ(ÄÄÄÄÄÄÄÅ……Ö‰πô…Ω¥°Õï±ïç—•ΩπÕmù…Ω’¡t§πôΩ…Öç†°ŸÖ±’îÄÙ¯ÅÌÏÅÕï±ïç—•ΩπÕmù…Ω’¡tπëï±ï—î°ŸÖ±’î§ÏÅÕÂπç°•¡ÕΩ»°ù…Ω’¿∞ÅŸÖ±’î§ÏÅıÙ§Ï(ÄÄÄÄÄÅıÙ§Ï(ÄÄÄÄÄÅ…ïπëï…ç—•Ÿï•±—ï…Ã†§Ï(ÄÄÄÄÄÅÖ¡¡±Â•±—ï…Ã†§Ï(ÄÄÄÄÄÅç±ΩÕïM°ïï–†§Ï(ÄÄÄÅıÙ§Ï(ÄÅıÙ§Ï((ÄÄººÅ-’∏Å	Ω%ΩYÖππ•ππ°Ω±êÅ±•ùùï»Å§Äâ•±—…ï»Å¡…Ωë’≠—ï»àµÖ…≠ï–Å√îÅµΩâ•∞Ä¥¥(ÄÄººÅµï…≠îµç°•¡ÕïπîÅï»ÅÖ±±ï…ïëîÅë•…ï≠—îÅÕÂπ±•ùîΩ—…Â≠≠âÖ…îÅ√îÅÕï±ŸîÅÕ•ëï∏∏(ÄÅçΩπÕ–ÅÕ°ïï—Q…•ùùï»ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùô•±—ï»µ—…•ùùï»ú§Ï(ÄÅçΩπÕ–Åô•±—ï…AÖπï∞ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùçÖ—ïùΩ…‰µô•±—ï…Ãú§Ï(ÄÅçΩπÕ–ÅÕ°ïï—	Öç≠ë…Ω¿ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùô•±—ï»µâÖç≠ë…Ω¿ú§Ï(ÄÅçΩπÕ–ÅÕ°ïï—±ΩÕîÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùô•±—ï»µÕ°ïï–µç±ΩÕîú§Ï(ÄÅçΩπÕ–ÅÕ°ïï—M°Ω›	—∏ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùÕ°ïï–µÕ°Ω‹µçΩ’π–ú§Ï((ÄÅô’πç—•Ω∏ÅΩ¡ïπM°ïï–†§ÅÌÏÅô•±—ï…AÖπï∞πç±ÖÕÕ1•Õ–πÖëê†ù•ÃµΩ¡ï∏ú§ÏÅÕ°ïï—	Öç≠ë…Ω¿π°•ëëï∏ÄÙÅôÖ±ÕîÏÅëΩç’µïπ–πâΩë‰πÕ—Â±îπΩŸï…ô±Ω‹ÄÙÄù°•ëëï∏úÏÅıÙ(ÄÅô’πç—•Ω∏Åç±ΩÕïM°ïï–†§ÅÌÏÅô•±—ï…AÖπï∞πç±ÖÕÕ1•Õ–π…ïµΩŸî†ù•ÃµΩ¡ï∏ú§ÏÅÕ°ïï—	Öç≠ë…Ω¿π°•ëëï∏ÄÙÅ—…’îÏÅëΩç’µïπ–πâΩë‰πÕ—Â±îπΩŸï…ô±Ω‹ÄÙÄúúÏÅıÙ(ÄÅ•òÄ°Õ°ïï—Q…•ùùï»§ÅÕ°ïï—Q…•ùùï»πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞ÅΩ¡ïπM°ïï–§Ï(ÄÅ•òÄ°Õ°ïï—±ΩÕî§ÅÕ°ïï—±ΩÕîπÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Åç±ΩÕïM°ïï–§Ï(ÄÅ•òÄ°Õ°ïï—	Öç≠ë…Ω¿§ÅÕ°ïï—	Öç≠ë…Ω¿πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Åç±ΩÕïM°ïï–§Ï(ÄÅ•òÄ°Õ°ïï—M°Ω›	—∏§ÅÕ°ïï—M°Ω›	—∏πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Åç±ΩÕïM°ïï–§Ï((ÄÄººÄâ±±îÅµï…≠ï»àµ’—Ÿ•ëï±ÕîÄ¥¥ÅëîÉ·Ÿ…•ùîÅµï…≠îµç°•¡ÕïπîÅ±•ùùï»ÅÖ±±ï…ïëîÅ§(ÄÄººÅ=4µï∏Ä°ï≠—î∞Åç…Ö›±âÖ»Å!Q50§∞Å≠’∏ÅÕÂπ±•ù°ï—ï∏Åïπë…ïÃ∏(ÄÅçΩπÕ–Åâ…Öπë5Ω…ïQΩùù±îÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùâ…Öπêµ—Ωùù±îµµΩ…îú§Ï(ÄÅçΩπÕ–Åâ…Öπë5Ω…ï]…Ö¿ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùâ…ÖπêµµΩ…îµ›…Ö¿ú§Ï(ÄÅ•òÄ°â…Öπë5Ω…ïQΩùù±îÄòòÅâ…Öπë5Ω…ï]…Ö¿§ÅÌÏ(ÄÄÄÅçΩπÕ–Å•π•—•Ö±1Öâï∞ÄÙÅâ…Öπë5Ω…ïQΩùù±îπ•ππï…!Q50Ï(ÄÄÄÅâ…Öπë5Ω…ïQΩùù±îπÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–Åï·¡ÖπëïêÄÙÅâ…Öπë5Ω…ïQΩùù±îπùï———…•â’—î†ùÖ…•Ñµï·¡Öπëïêú§ÄÙÙÙÄù—…’îúÏ(ÄÄÄÄÄÅâ…Öπë5Ω…ïQΩùù±îπÕï———…•â’—î†ùÖ…•Ñµï·¡Öπëïêú∞Åï·¡ÖπëïêÄ¸ÄùôÖ±ÕîúÄËÄù—…’îú§Ï(ÄÄÄÄÄÅâ…Öπë5Ω…ï]…Ö¿π°•ëëï∏ÄÙÅï·¡ÖπëïêÏ(ÄÄÄÄÄÅâ…Öπë5Ω…ïQΩùù±îπ•ππï…!Q50ÄÙÅï·¡ÖπëïêÄ¸Å•π•—•Ö±1Öâï∞ÄËÄùM≠©’∞Åô±ï…îÅµï…≠ï»ÄÒÕ¡Ö∏ÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˚ä"HΩÕ¡Ö∏¯úÏ(ÄÄÄÅıÙ§Ï(ÄÅıÙ((ÄÄººÅ-’∏Åï—–Åë…Ω¡ëΩ›∏µô•±—ï»Éï¡ïπ–ÅΩ¥ÅùÖπùï∏Ä°ëïÕ≠—Ω¿µ∑·πÕ—ï»§Ä¨Å±’≠¨ÅŸïê(ÄÄººÅ≠±•≠¨Å’—ïπôΩ»∏(ÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπô•±—ï»µëêú§πôΩ…Öç†°ëêÄÙ¯ÅÌÏ(ÄÄÄÅëêπÖëëŸïπ—1•Õ—ïπï»†ù—Ωùù±îú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅ•òÄ°ëêπΩ¡ï∏§ÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπô•±—ï»µëêú§πôΩ…Öç†°Ω—°ï»ÄÙ¯ÅÌÏÅ•òÄ°Ω—°ï»ÄÑÙÙÅëê§ÅΩ—°ï»πΩ¡ï∏ÄÙÅôÖ±ÕîÏÅıÙ§Ï(ÄÄÄÅıÙ§Ï(ÄÅıÙ§Ï(ÄÅëΩç’µïπ–πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞ÅîÄÙ¯ÅÌÏ(ÄÄÄÅ•òÄ†Öîπ—Ö…ùï–πç±ΩÕïÕ–†úπô•±—ï»µëêú§§ÅÌÏ(ÄÄÄÄÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπô•±—ï»µëëmΩ¡ïπtú§πôΩ…Öç†°ëêÄÙ¯ÅÌÏÅëêπΩ¡ï∏ÄÙÅôÖ±ÕîÏÅıÙ§Ï(ÄÄÄÅıÙ(ÄÅıÙ§Ï((ÄÅçΩπÕ–ÅÕΩ…—Mï±ïç–ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùÕΩ…–µÕï±ïç–ú§Ï(ÄÅÕΩ…—Mï±ïç–πÖëëŸïπ—1•Õ—ïπï»†ùç°Öπùîú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÅçΩπÕ–ÅëïÕåÄÙÅÕΩ…—Mï±ïç–πŸÖ±’îÄÙÙÙÄù¡…•çîµëïÕåúÏ(ÄÄÄÅçΩπÕ–ÅçÖ…ëÃÄÙÅ……Ö‰πô…Ω¥°±•Õ–π≈’ï…ÂMï±ïç—Ω…±∞†úπ¡…Ωë’ç–µ—•±îú§§Ï(ÄÄÄÅçÖ…ëÃπÕΩ…–†°Ñ∞Åà§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–ÅÖÿÄÙÅ¡Ö…Õï±ΩÖ–°Ñπ≈’ï…ÂMï±ïç—Ω»†úπ¡…Ωë’ç–µ—•±îµ¡…•çîú§¸π—ï·—Ωπ—ïπ–π…ï¡±Öçî†ΩqqΩú∞Äúú§§ÅÒÅ%πô•π•—‰Ï(ÄÄÄÄÄÅçΩπÕ–ÅâÿÄÙÅ¡Ö…Õï±ΩÖ–°àπ≈’ï…ÂMï±ïç—Ω»†úπ¡…Ωë’ç–µ—•±îµ¡…•çîú§¸π—ï·—Ωπ—ïπ–π…ï¡±Öçî†ΩqqΩú∞Äúú§§ÅÒÅ%πô•π•—‰Ï(ÄÄÄÄÄÅ…ï—’…∏ÅëïÕåÄ¸ÅâÿÄ¥ÅÖÿÄËÅÖÿÄ¥ÅâÿÏ(ÄÄÄÅıÙ§Ï(ÄÄÄÅçÖ…ëÃπôΩ…Öç†°åÄÙ¯Å±•Õ–πÖ¡¡ïπë°•±ê°å§§Ï(ÄÅıÙ§Ï)ıÙ§†§Ï(ΩÕç…•¡–¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(((åÄâ1•πÕï€ôÕ≠îàºã·ÂïëÀï¡ï»àÅºπ∞∏Ä¥¥Åëï±–Å¡…Ωë’≠——Â¡îÄ°Õ•Èï}µ∞ΩÕΩ±’—•Ωπ}—Â¡îº(åÅÕΩ±’—•Ωπ}çÖ—ïùΩ…‰Å§ÅÕ—ïëï–ÅôΩ»ÅçÖ—ïùΩ…Â}Õ±’úΩÕ¡ïçÃÅÕΩ¥Å≠Ωπ—Ö≠—±•πÕï»(åÅâ…’≠ï»§∞Åµï∏ÅÕÖµµîÅ¡…•Ã¥Ω—•±â’ëÕ±Ωù•≠¨∏Å¡…Ωë’ç—lâÕΩ±’—•Ωπ}çÖ—ïùΩ…‰ât(åÅ¡ï≠ï»Å•π∏Å§Åëï——îÅΩ¡¡Õ±Öùï–ÅôΩ»ÅUI0µ¡…ïô•≠ÃΩ—•——ï∞Ω•π—…ºÄ¥¥Åπ‰Å≠Ö—ïùΩ…§(åÄ°òπï≠Ã∏Å±•πÕïï—’§ÅÕïπï…î§Åï»Å≠’∏Åï∏Åπ‰Åª·≠≠ï∞Å°ï»∞Å•πùï∏Å≠Ωëïë’¡±•Õï…•πú∏)M=1UQ%=9}Q=I%LÄÙÅÏ(ÄÄÄÄâ±•πÕïŸÖïÕ≠îàËÅÏ(ÄÄÄÄÄÄÄÄâ±Öâï∞àËÄâ1•πÕï€ôÕ≠îà∞(ÄÄÄÄÄÄÄÄâ—•—±ï}±Öâï∞àËÄâ	•±±•úÅ±•πÕï€ôÕ≠îà∞(ÄÄÄÄÄÄÄÄâµï—Ö}ëïÕç…•¡—•Ω∏àËÄâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ±•πÕï€ôÕ≠îÅΩúÅ…ï•Õï¡Ö≠≠ï»Å°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅMîÅ¡…•ÃÅ¡ï»Äƒ¿¿Åµ∞∞ÅµïêÅï±±ï»Å’—ï∏Åô…Ö≠–∏à∞(ÄÄÄÄÄÄÄÄâ•π—…ºàËÄâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ±•πÕï€ôÕ≠îÅΩúÅ…ï•Õï¡Ö≠≠ï»Å°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅY§ÅŸ•Õï»Å¡…•ÃÅ¡ï»Äƒ¿¿Åµ∞Åëï»Åëï–Åï»Å…ï±ïŸÖπ–∞ÅÕ±•¨ÅÖ–ÅÕ—Ω…îÅΩúÅÕ∑îÅô±ÖÕ≠ï»Åï»ÅÕÖµµïπ±•ùπâÖ…î∏à∞(ÄÄÄÅÙ∞(ÄÄÄÄâ—•±âï°Ω»àËÅÏ(ÄÄÄÄÄÄÄÄâ±Öâï∞àËÄâQ•±âï£·»à∞(ÄÄÄÄÄÄÄÄâ—•—±ï}±Öâï∞àËÄâ	•±±•úÅ±•πÕï—•±âï£·»à∞(ÄÄÄÄÄÄÄÄâ•π—…ºàËÄâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ±•πÕïï—’§∞Å¡•πÕï—–ÅΩúÅ°©ï±¡ïµ•ë±ï»ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»ÅΩúÉ·ÂïëÀï¡ï»Å°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏à∞(ÄÄÄÅÙ∞(ÄÄÄÄâΩÂïë…Ö¡ï»àËÅÏ(ÄÄÄÄÄÄÄÄâ±Öâï∞àËÄãaÂïëÀï¡ï»à∞(ÄÄÄÄÄÄÄÄâ—•—±ï}±Öâï∞àËÄâ	•±±•ùîÉ·ÂïëÀï¡ï»à∞(ÄÄÄÄÄÄÄÄâµï—Ö}ëïÕç…•¡—•Ω∏àËÄâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÉ·ÂïëÀï¡ï»∞É·Âïùï∞∞É·ÂïÕÖ±ŸîÅΩúÉ·Âï¡±ï•îÅ°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅA…•ÃÅ¡ï»Äƒ¿¿Åµ∞Åï±±ï»Äƒ¿¿Åú∞ÅµïêÅï±±ï»Å’—ï∏Åô…Ö≠–∏à∞(ÄÄÄÄÄÄÄÄâ•π—…ºàËÄâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÉ·ÂïëÀï¡ï»∞É·Âïùï∞∞É·ÂïÕÖ±ŸîÅΩúÉ·Âï¡±ï•îÅµΩ–Å”·……îÉ·ÂπîÅ°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ÅY§ÅŸ•Õï»Å¡…•ÃÅ¡ï»Äƒ¿¿Åµ∞Ä°ï±±ï»Äƒ¿¿ÅúÅôΩ»Åùï∞ÅΩúÅÕÖ±Ÿî§Åëï»Åëï–Åï»Å…ï±ïŸÖπ–∞ÅÕ±•¨ÅÖ–Å’±•≠îÅ¡Ö≠π•πùÕÕ”·……ï±Õï»Åï»ÅÕÖµµïπ±•ùπâÖ…î∏à∞(ÄÄÄÅÙ∞)Ù(((åÅ!ï…ºµ≠Ω…–ÅµïêÅ¡…Ωë’≠—â•±ëîÄ¨Å—ï≠Õ–Ä¨ÅŸ•ππï…≠Ω…–∞Åëï±–ÅÖÿÅ±ïπÃ¥ÅΩúÅ—•±âï£·…ÕÕ•ëï»(åÄ°≠Ω¡§ÅÖÿÅ…ïù±ïπîÅ§Å…ïπëï…}¡…Ωë’ç—}¡ÖùîÅÕ•∏ÄÒÕ—Â±î¯∞Å’—ï∏ÅòµÕ—…•πúµïÕçÖ¡•πú§∏)!I=}%5}MQe1ÄÙÄàààπ°ï…ºµçÖ…êÅÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ»¡¡‡ÏÅ¡Öëë•πúËÄ»¡¡‡ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄ»¡¡‡ÏÅÙ(π°ï…ºµçÖ…êÄπ°ï…ºµçΩ¡‰Å†ƒÅÏÅôΩπ–µÕ•ÈîËÄƒ∏Ÿ…ï¥ÏÅÙ(π°ï…ºµÕ’â—•—±îÅÏÅµÖ…ù•∏ËÄ…¡‡Ä¿Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µ›ï•ù°–ËÄ‘¿¿ÏÅÙ(º®ÄâA…•ÃÅŸïêÅô±ï…îÅïÕ≠ï»Ωô±ÖÕ≠ï»àÅÕΩ¥Åïùï–∞Åô…•——Õ”ïïπëîÅ≠Ω…–Å’πëï»(ÄÄÅ¡…•Õ±•Õ—ÑÄ°≈—Â}µ’±—•}•π±•πîıÖ±Õî§Ä¥¥ÅÕÖµµîÅ∑·πÕ—ï»ÅÕΩ¥Å≠Ωπ—Ö≠—±•πÕî¥(ÄÄÅ¡…Ωë’≠—Õ•ëï∏Ä°-Ö§∞Ä»¿»ÿ¥¿‰¥»‡ËÄâ!ï»Åï»Å¡…•ÃÅŸïêÅô±ï…îÅïÕ≠ï»ÅΩúÅëï∏(ÄÄÅëï±ï∏ÅµïêÅâ≥îÅâÖ≠ù…’π∏Å•≠≠îÅô±Â——ï–ÅπïêàÅ√îÅ¡…•ŸÖ—îÅ±Öâï∞µÕ•ëï∏§∏Ä®º(π›…Ö¿µ¡…Ωë’ç–Ä¯Äπ≈—‰µµ’±—§ÅÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅ¡Öëë•πúËÄƒŸ¡‡Äƒ·¡‡ÏÅµÖ…ù•∏ËÄƒ—¡‡Ä¿ÏÅÙ(º®ÅA…Ωë’ç–Ä°ïÕ≠—Ω¿§ÅΩ±êÅM—ÖπëÖ…êÅÿƒÄ¥¥Å¡Ω…—ï…–Å°•–Åô…ÑÅ…ïπëï…}¡…Ωë’ç—}¡Öùî†§(ÄÄÄ»¿»ÿ¥¿‰¥»‡Ä°-Ö§ËÄâù´·»ÅÕÖµµîÅ°ï…º¥Ω≈’Öπ—•—‰µ…ïëïÕ•ù∏Å√îÅ±•πÕï€ôÕ≠îÅΩú(ÄÄÅ¡…•ŸÖ—îÅ±Öâï∞à∞Åï——ï»Å—•ë±•ùï…îÅÕçΩ¡îµÖŸ≠±Ö…•πúÄâù©ï±ëï»ÅÖ±±îÅ¡…Ωë’≠—ï»(ÄÄÅ√îÅëΩµïπï–Å≠Ωπ—Ö≠—±•πÕï»ππºà§∏Å!I=}%5}MQe1Åï»ÅÖ±±ï…ïëîÅëï±–ÅÖÿ(ÄÄÅ…ïπëï…}ÕΩ±’—•Ωπ}¡…Ωë’ç—}¡Öùî†§Å=Å…ïπëï…}¡…•ŸÖ—ï}±Öâï±}¡Öùî†§∞ÅœîÅëïππî(ÄÄÅïπîÅïπë…•πùï∏Åù•»ÅâïùùîÅÕÖµµîÅπÂîÅëïÕ•ù∏∏Å…ïπëï…}¡…Ωë’ç—}¡Öùî†§Å°Ö»ÅÕ•∏(ÄÄÅ8∞Å’À·…—îÅ≠Ω¡§ÅÖÿÅÕÖµµîÅ∑·πÕ—ï»Ä°ë’¡±•Õï…–ÅâïŸ•ÕÕ–∞Å•≠≠îÅµ•ù…ï…–Å—•∞(ÄÄÅëïππîÅ≠ΩπÕ—Öπ—ï∏∞ÅôΩ»ÉîÅ•≠≠îÅÀ·…îÅÖ±±ï…ïëîÅÕ≠•¡ï–Ω—ïÕ—ï–Å≠Ωëî§Ä¥¥ÅÕî(ÄÄÅëïπÃÅëΩçÕ—…•πúµ≠Ωµµïπ—Ö…ï»ÅôΩ»Åëï∏Åô’±±îÅëïÕ•ùπ°•Õ—Ω…•≠≠ï∏ºµâïù…’ππï±Õï∏(ÄÄÄ°-Ö§ÅÕ•πîÅ≠Ωπ≠…ï—îÅ¡’π≠—ï»Åï»Å•≠≠îÅù©ïπ—Ö—–Å°ï»∞Å≠’∏ÅÕï±ŸîÅ…ïÕ’±—Ö—ï–§∏(ÄÄÄπ°ï…ºµµïë•Ñµ…Ω‹ËÅâ•±ëîÄ°¯»ºÃ§ÅΩúÅ]•ππï»ÅÖ…êÄ°¯ƒºÃ§ÅÕ•ëîÅŸïêÅÕ•ëîÅ√î(ÄÄÅµΩâ•∞∏Ä®º(π°ï…ºµµïë•Ñµ…Ω‹ÅÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅùÖ¿ËÄƒ…¡‡ÏÅÙ(π°ï…ºµµïë•Ñµ…Ω‹Äπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÏÅô±ï‡ËÄ»ÄƒÄ¿ÏÅµ•∏µ›•ë—†ËÄ¿ÏÅµÖ…ù•∏ËÄ¿ÏÅÙ(π°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâÖπêÅÏÅô±ï‡ËÄƒÄƒÄ¿ÏÅµ•∏µ›•ë—†ËÄ¿ÏÅµÖ…ù•∏ËÄ¿ÏÅÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄÿ–¡¡‡§ÅÏÄπ°ï…ºµµïë•Ñµ…Ω‹ÅÏÅùÖ¿ËÄƒŸ¡‡ÏÅÙÅÙ)µïë•ÑÄ°µÖ‡µ›•ë—†ËÄ‡‘Â¡‡§ÅÏ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÏÅÖÕ¡ïç–µ…Ö—•ºËÄ–ÄºÄÃÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâÖπêµç—ÑÅÏÅ¡Öëë•πúËÄƒ¡¡‡Ä·¡‡ÏÅùÖ¿ËÄŸ¡‡ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µ—Ω¿ÅÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâÖπêµç—ÑÄπ±Öâï∞µù…Ω’¿ÅÏÅô±ï‡µë•…ïç—•Ω∏ËÅ…Ω‹ÏÅÖ±•ù∏µ•—ïµÃËÅâÖÕï±•πîÏÅùÖ¿ËÄ—¡‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâÖπêµç—ÑÄπ±Öâï∞ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿≈ï¥ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µÕ’àÅÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ—…ï¥ÏÅµÖ…ù•∏µ—Ω¿ËÄ¿ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâÖπêµç—ÑÄπ…ï—Ö•±ï»ÅÏÅµÖ…ù•∏µ—Ω¿ËÄŸ¡‡ÄÖ•µ¡Ω…—Öπ–ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâÖπêµç—ÑÄπ…ï—Ö•±ï»µ±ΩùºÅÏÅ°ï•ù°–ËÄƒ·¡‡ÏÅµÖ‡µ›•ë—†ËÄ‡·¡‡ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µ¡…•çîµ±•πîÅÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÃÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µÕÖŸ•πùÃÅÏÅ›•ë—†ËÄÃ—¡‡ÏÅ°ï•ù°–ËÄÃ—¡‡ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µÕÖŸ•πùÃµ±Öâï∞ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏—…ï¥ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µÕÖŸ•πùÃµ¡ç–ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ……ï¥ÏÅÙ(ÄÄπ°ï…ºµµïë•Ñµ…Ω‹Äπ›•ππï»µâ—∏ÅÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅ¡Öëë•πúËÄ·¡‡Ä—¡‡ÏÅùÖ¿ËÄÕ¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄ…¡‡ÏÅ›°•—îµÕ¡ÖçîËÅπΩ…µÖ∞ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅ±•πîµ°ï•ù°–ËÄƒ∏»‘ÏÅÙ)Ù(π°ï…ºµ≠•ç≠ï»∞Äπ°ï…ºµôÖç—ÃÅÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅÙ(º®ÅA…Ωë’ç–ÅM—ÖùîËÅï≠—îÅ—…îµ≠Ω±Ωππï…ÃÅMLÅ…•êÅ√îÅëïÕ≠—Ω¿Ä°â•±ëîÅÅ•ëïπ—•—ï–¨(ÄÄÅ≠Ωπ—…Ω±±ï»ÅÅ]•ππï»ÅÖ…ê∞ÅÕÖµµîÅŸï…—•≠Ö±îÅÖ…âï•ëÕô±Ö—î§∏Äπ≈—‰µâΩ‡Åï»(ÄÄÅôΩ…—ÕÖ—–Åï∏Åïùï∏Å=4µπΩëîÄ°œ·Õ≠ï∏ÅÖÿÄπ°ï…ºµçÖ…êÅ§Äπ¡…Ωë’ç–µÕ—Öùî§Ä¥¥(ÄÄÄâô±Ö—ïÃàÅ’–ÅµïêÅë•Õ¡±Ö‰ÈçΩπ—ïπ—ÃÅ√îÅëïÕ≠—Ω¿ÅÕ±•¨ÅÖ–ÅëïπÃÅâÖ…∏Åâ±•»(ÄÄÅë•…ï≠—îÅù…•êµâÖ…∏∞Å’—ï∏ÅπΩï∏Å=4µô±Â——•πúÄ°µΩâ•∞Å’√ïŸ•…≠ï–§∏Ä®º)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§ÅÏ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÅÏ(ÄÄÄÅë•Õ¡±Ö‰ËÅù…•êÏ(ÄÄÄÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅµ•πµÖ‡†Ãÿ¡¡‡∞Ä¿∏‰’ô»§Åµ•πµÖ‡†–»¡¡‡∞Äƒ∏ƒ¡ô»§Åµ•πµÖ‡†»‡¡¡‡∞Ä¿∏‹…ô»§Ï(ÄÄÄÅù…•êµ—ïµ¡±Ö—îµÖ…ïÖÃËÄâ•µÖùîÅ•ëïπ—•—‰Å¡…•çîàÄâ•µÖùîÅçΩπ—…Ω±ÃÅ¡…•çîàÏ(ÄÄÄÅçΩ±’µ∏µùÖ¿ËÄÃ…¡‡Ï(ÄÄÄÅ…Ω‹µùÖ¿ËÄ–¡¡‡Ï(ÄÄÄÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ»¡¡‡Ï(ÄÄÄÅ¡Öëë•πúËÄÃ…¡‡ÄÃŸ¡‡Ï(ÄÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµçÖ…ê∞Äπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµµÖ•∏∞Äπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµµïë•Ñµ…Ω‹ÅÏÅë•Õ¡±Ö‰ËÅçΩπ—ïπ—ÃÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµ≠•ç≠ï»ÅÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿Ÿï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅµÖ…ù•∏ËÄ¿Ä¿ÄŸ¡‡ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµçΩ¡‰ÅÏÅù…•êµÖ…ïÑËÅ•ëïπ—•—‰ÏÅÖ±•ù∏µÕï±òËÅÕ—Ö…–ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµçΩ¡‰Å†ƒÅÏÅôΩπ–µÕ•ÈîËÄ……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ƒ‡ÏÅµÖ…ù•∏ËÄ¿ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµÕ’â—•—±îÅÏÅôΩπ–µÕ•ÈîËÄƒ∏……ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ–¿¿ÏÅµÖ…ù•∏ËÄ·¡‡Ä¿Ä¿ÏÅÙ(ÄÄπ°ï…ºµôÖç—ÃÅÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄ›¡‡ÏÅµÖ…ù•∏ËÄ»—¡‡Ä¿Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅÙ(ÄÄπ°ï…ºµôÖç–µÕï¿ÅÏÅçΩ±Ω»ËÅŸÖ»†¥µâΩ…ëï»§ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÏÅù…•êµÖ…ïÑËÅ•µÖùîÏÅÖ±•ù∏µÕï±òËÅçïπ—ï»ÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄÃ»¡¡‡ÏÅµÖ‡µ›•ë—†ËÅπΩπîÏÅµÖ…ù•∏ËÄ¿ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄ¯Äπ≈—‰µâΩ‡ÅÏÅù…•êµÖ…ïÑËÅçΩπ—…Ω±ÃÏÅÖ±•ù∏µÕï±òËÅÕ—Ö…–ÏÅâΩ…ëï»ËÅπΩπîÏÅâÖç≠ù…Ω’πêËÅ—…ÖπÕ¡Ö…ïπ–ÏÅ¡Öëë•πúËÄ¿ÏÅµÖ…ù•∏ËÄ¿ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ≈—‰µ¡•±±ÃÅÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅùÖ¿ËÄ·¡‡ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ≈—‰µ¡•±∞ÅÏÅ›•ë—†ËÄÿ¡¡‡ÏÅ°ï•ù°–ËÄ–Ÿ¡‡ÏÅ¡Öëë•πúËÄ¿ÏÅâΩ‡µÕ°ÖëΩ‹ËÅπΩπîÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ≈—‰µ¡•±∞π•ÃµÖç—•ŸîÅÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•π–µ—•π–§ÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µµ•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅπΩπîÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ≈—‰µ¡•±∞π•ÃµÖç—•ŸîÅÕ¡Ö∏ÅÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µâÖπêÅÏÅù…•êµÖ…ïÑËÅ¡…•çîÏÅÖ±•ù∏µÕï±òËÅçïπ—ï»ÏÅµÖ…ù•∏ËÄ¿ÏÅ›•ë—†ËÄƒ¿¿îÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅ¡Öëë•πúËÄ»—¡‡Äƒ·¡‡Äƒ·¡‡ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µ±ïô–ÅÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄ¿ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µ—…Ω¡°‰ÅÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ—Ω¿ËÄ¥»…¡‡ÏÅ±ïô–ËÄ‘¿îÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ï`†¥‘¿î§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Ä…¡‡ÄŸ¡‡Å…ùâÑ†ƒƒ∞ÄÃ‹∞Äÿ‰∞Ä¿∏ƒ‘§ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µâÖπêÄπ±Öâï∞ÅÏÅµÖ…ù•∏µ—Ω¿ËÄ¿ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µâÖπêÄπ…ï—Ö•±ï»ÅÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ¡¡‡ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µâÖπêÄπ›•ππï»µÕ°•¡¡•πúÅÏÅµÖ…ù•∏µ—Ω¿ËÄƒ¡¡‡ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µ¡…•çîµù…Ω’¿ÅÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ¡…•çîµ¡•±∞π•Ãµ›•ππï»ÅÏÅë•Õ¡±Ö‰ËÅ•π±•πîµâ±Ωç¨ÏÅâÖç≠ù…Ω’πêËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µµ•π–§ÏÅ¡Öëë•πúËÄ¿ÏÅôΩπ–µÕ•ÈîËÄƒ∏›…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µ¡…•çîµπΩ—îÅÏÅµÖ…ù•∏µ—Ω¿ËÄ›¡‡ÏÅ±•πîµ°ï•ù°–ËÄƒÏÅÙ(ÄÄπ¡…Ωë’ç–µÕ—ÖùîÄπ›•ππï»µç—ÑÅÏÅë•Õ¡±Ö‰ËÅ•π±•πîµô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅùÖ¿ËÄŸ¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ¡¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•π–§ÏÅçΩ±Ω»ËÅ›°•—îÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅ¡Öëë•πúËÄƒ≈¡‡Ä»…¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‰‰Â¡‡ÏÅÙ)Ù(π°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÅÖ’—ºÏÅÖÕ¡ïç–µ…Ö—•ºËÄƒÄºÄƒÏÅµÖ…ù•∏ËÄ¿ÅÖ’—ºÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ·¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ¡Öëë•πúËÄƒ¡¡‡ÏÅâΩ‡µÕ•È•πúËÅâΩ…ëï»µâΩ‡ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ»∏—…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅÙ(π°ï…ºµ¡…Ωë’ç–µ•µÖùîÅ•µúÅÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩπ—Ö•∏ÏÅÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄÿ–¡¡‡§ÅÏÄπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÏÅâΩ…ëï»µ…Öë•’ÃËÄ»¡¡‡ÏÅôΩπ–µÕ•ÈîËÄ»∏Ÿ…ï¥ÏÅÙÅÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§ÅÏÄπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅÖÕ¡ïç–µ…Ö—•ºËÅÖ’—ºÏÅµÖ…ù•∏ËÄ¿ÏÅôΩπ–µÕ•ÈîËÄÕ…ï¥ÏÅÙÅÙ(π°ï…ºµ¡…Ωë’ç–µ•µÖùîπ°ÖÃµ¡°Ω—ºÅÏÅâÖç≠ù…Ω’πêËÅ—…ÖπÕ¡Ö…ïπ–ÏÅâΩ…ëï»ËÅπΩπîÏÅ¡Öëë•πúËÄŸ¡‡ÏÅÙ(π°ï…ºµ¡…Ωë’ç–µ•µÖùîπ°ÖÃµ¡°Ω—ºÅ•µúÅÏÅΩâ©ïç–µô•–ËÅçΩπ—Ö•∏ÏÅÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§ÅÏÄπ›…Ö¿µ¡…Ωë’ç–ÅÏÅµÖ‡µ›•ë—†ËÄƒ»‡¡¡‡ÏÅÙÅÙ(π°ï…ºµçÖ…êÄπ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰ÅÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»µ±ïô–ËÅπΩπîÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿Ä¿ÏÅÙ(ààà(()ëïòÅ}±Ö…ùï…}ôïïë}•µÖùî°’…∞ËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâïïëâ•±ëïπîÅï»ÅÕ∑îÅµ•π•Ö—Â…ï»Ä°1ïπÕ›Ö‰Å›|ƒ‹¿∞Å¡Ω—ï≠°©ï¥Å|–¿¿§ÅÕΩ¥Åâ±•»(ÄÄÄÅ’Õ≠Ö…¡îÅ§Åëï∏ÅÕ—Ω…îÅ°ï…ºµ…’—ï∏∏Å	ïùùîÅ≠•±ëïπîÅÕï…Ÿï…ï»ÅÕ”·……îÅŸÖ…•Öπ—ï»ÅÖÿ(ÄÄÄÅÕÖµµîÅâ•±ëîÅŸ•ÑÅï∏ÅÕ”·……ï±ÕîÅ§ÅUI0µï∏ÏÅÖπë…îÅ≠•±ëï»Å…ï—’…πï…ïÃÅ’ïπë…ï–∏ààà(ÄÄÄÅ•òÄâ±›úµ…ïÃπç±Ω’ë•πÖ…‰πçΩ¥àÅ•∏Å’…∞Ë(ÄÄÄÄÄÄÄÅ…ï—’…∏Å’…∞π…ï¡±Öçî†à±›|ƒ‹¿∞à∞Äà±›|ÿ¿¿∞à§(ÄÄÄÅ•òÄâÖ¡Ω—ï≠°©ï¥ππºΩ•µÖùïÃΩ—°’µâÃºàÅ•∏Å’…∞ÅÖπêÅ’…∞πïπëÕ›•—††â|–¿¿π©¡úà§Ë(ÄÄÄÄÄÄÄÅ…ï—’…∏Å’…±lËµ±ï∏†â|–¿¿π©¡úà•tÄ¨Äâ|ÿ¿¿π©¡úà(ÄÄÄÅ…ï—’…∏Å’…∞(()ëïòÅ…ïπëï…}ÕΩ±’—•Ωπ}¡…Ωë’ç—}¡Öùî°¡…Ωë’ç–ËÅë•ç–∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî∞Åç±•ç≠Ω’—ÃËÅë•ç–ÅÅ9ΩπîÄÙÅ9Ωπî∞Å¡…•çï}°•Õ—Ω…‰ËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâ1•πÕï€ôÕ≠îø·ÂïëÀï¡ï»Åºπ∞∏Ä¥¥Åïùï∏Å¡…Ωë’≠——Â¡îÅµïêÅÖππï∏ÅëÖ—ÖµΩëï±∞Åïπ∏(ÄÄÄÅ≠Ωπ—Ö≠—±•πÕï»Ä°Õ•Èï}µ∞ΩÕΩ±’—•Ωπ}—Â¡îΩÕΩ±’—•Ωπ}çÖ—ïùΩ…‰Å§ÅÕ—ïëï–ÅôΩ»(ÄÄÄÅçÖ—ïùΩ…Â}Õ±’úΩÕ¡ïçÃ§∞Åµï∏ÅÕÖµµîÅ¡…•Ã¥Ω—•±â’ëÕ±Ωù•≠¨Ä°…ïçΩπç•±ï}¡…Ωë’ç–∞(ÄÄÄÅ}…ï—Ö•±ï…}âÖëùï}°—µ∞ÅΩÕÿ∏Åï»Åëï±–Å≠ΩëîÅ’ïπë…ï–Åô…ÑÅ≠Ωπ—Ö≠—±•πÕîµÕ•ëïπî§∏ààà(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§(ÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÅâïÕ–ÄÙÅπï·–†°ºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•Õ}±Ω›ïÕ–ât§∞Å9Ωπî§(ÄÄÄÄåÅ	Ω≠Õï—îÅô…Ö≠–µŸ•¡¡ïâ…Â—ï»Å§Å¡…•Õ±•Õ—ï°ïÖëï…ï∏Å§ÅÕ—ïëï–ÅôΩ»Åëï∏ÅùÖµ±î∞(ÄÄÄÄåÅïπ≠±îÅ¡…•≠≠îµç°•¡¡ï∏Ä¥¥ÅÕÖµµîÄâÕÖµµîÅ°ï…º¥Ω≈’Öπ—•—‰µ…ïëïÕ•ù∏àµ…’πëî(ÄÄÄÄåÄ†»¿»ÿ¥¿‰¥»‡§ÅÕΩ¥Å…ïÕ—ï∏ÅÖÿÅëïππîÅô’π≠Õ©Ωπï∏∏(ÄÄÄÅÕ°•¡}ç°•¡}°—µ∞ÄÙÅ}Õ°•¡}ç°•¡}âΩ·ïë}°—µ∞†âÕ°•¿µç°•¿à§Å•òÅΩôôï…ÃÅï±ÕîÄàà(ÄÄÄÅΩôôï…Õ}â±Ωç¨∞Åï·}âïÕ–ÄÙÅ…ïπëï…}¡…•çï}±•Õ–°Ωôôï…Ã∞Å¡…Ωë’ç—lâπÖµîât∞Å¡…Ωë’ç—lâ•êât∞Åç±•ç≠Ω’—Ã∞ÅÕ°Ω›}Õ°•¡}ç°•¿ıÖ±Õî∞ÅçΩ±±Ö¡Õï}Öô—ï»Ùƒ¿∞Å¡…Ωë’ç—}Õ°•¡}ç°•¡}°—µ∞ıÕ°•¡}ç°•¡}°—µ∞§(ÄÄÄÅ±Ωπù}ëïÕç…•¡—•Ω∏ÄÙÅ¡…Ωë’ç–πùï–†â±Ωπù}ëïÕç…•¡—•Ω∏à∞Å¡…Ωë’ç–πùï–†âëïÕç…•¡—•Ω∏à∞Äàà§§(ÄÄÄÄåÅMîÅÕÖµµîÅâïù…’ππï±ÕîÅ§Å…ïπëï…}¡…Ωë’ç—}¡ÖùîÄ¥¥Åµï—ÑµâïÕ≠…•Ÿï±Õï∏ÅÕ≠Ö∞(ÄÄÄÄåÅ±ïëîÅµïêÅÕï±ŸîÅ¡…•ÕÕÖµµïπ±•ùπ•πùï∏∞Å•≠≠îÅ¡…Ωë’≠—âïÕ≠…•Ÿï±Õï∏∏Åπ—Ö±∞(ÄÄÄÄåÅôΩ…°Öπë±ï…îÅï»ÅâïŸ•ÕÕ–Å’—ï±Ö—–Å°ï»ÅΩùœîÄ†»¿»ÿ¥¿‰¥¿‘∞ÅÕÖµµîÅô•≠Ã§∏(ÄÄÄÅµï—Ö}ëïÕç…•¡—•Ω∏ÄÙÄ†(ÄÄÄÄÄÄÄÅòùY§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÅÌ¡…Ωë’ç—lâπÖµîâuÙÅ°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏Äú(ÄÄÄÄÄÄÄÅòù1ÖŸïÕ—îÅ¡…•ÃÅÖ≠≠’…Ö–ÅªîÅï»ÅÌ}ôµ—}≠»°ï·}âïÕ—lâ¡…•çï}πΩ¨ât•ÙÅ°ΩÃÅÌï·}âïÕ—lâ…ï—Ö•±ï»âuÙ∏ú(ÄÄÄÄ§Å•òÅï·}âïÕ–Åï±ÕîÅ±Ωπù}ëïÕç…•¡—•ΩπlËƒ‘’t(ÄÄÄÅçÖ—}Õ±’úÄÙÅ¡…Ωë’ç—lâÕΩ±’—•Ωπ}çÖ—ïùΩ…‰ât(ÄÄÄÅçÖ–ÄÙÅM=1UQ%=9}Q=I%MmçÖ—}Õ±’ùt(ÄÄÄÅâÖÕï}’…±}¡Ö—†ÄÙÅòàΩÌçÖ—}Õ±’ùÙΩÌ¡…Ωë’ç—lùâ…Öπë}Õ±’úùuÙΩÌ¡…Ωë’ç—lùÕ±’úùuÙºà(ÄÄÄÅ•µÖùï}’…∞ÄÙÅ}¡…Ωë’ç—}•µÖùî°¡…Ωë’ç–§((ÄÄÄÅ•òÅâïÕ–Ë(ÄÄÄÄÄÄÄÅÖ•}Õ’µµÖ…Â}°—µ∞ÄÙÅòàààÒÕïç—•Ω∏Åç±ÖÕÃÙâ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰àÅÖ…•Ñµ±Öâï∞ÙâA…•ÕΩ¡¡Õ’µµï…•πúà¯(ÄÄÒ¿˘Y§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÄÒÕ—…Ωπú˘ÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•ÙΩÕ—…Ωπú¯Å°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏Å…ÑÄÒÕ—…Ωπú˘Ì}ôµ—}≠»°ï·}âïÕ—lâ¡…•çï}πΩ¨ât•ÙΩÕ—…Ωπú¯Å°ΩÃÅÌïÕçÖ¡î°ï·}âïÕ—lâ…ï—Ö•±ï»ât•ÙÄ°ï≠Õ≠∞∏Åô…Ö≠–§∏Å-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—îÄ¥ÅÕ≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅ’πëï»ÅôΩ»ÉîÅÕîÅ—Ω—Ö±¡…•Õï∏ÅµïêÅô…Ö≠–∏ÅA…•Õï»ÅÕ•Õ–Åâï≠…ïô—ï–ÅÌ}Ÿï…•ô•ïë}—Öú°}πï›ïÕ—}ç°ïç≠ïê°Ωôôï…Ã§•Ù∏Ω¿¯(ΩÕïç—•Ω∏¯ààà(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅÖ•}Õ’µµÖ…Â}°—µ∞ÄÙÅòàààÒÕïç—•Ω∏Åç±ÖÕÃÙâ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰ÅôÖ±±âÖç¨àÅÖ…•Ñµ±Öâï∞ÙâM—Ö—’Ãà¯(ÄÄÒ¿˘Y§Åõ·±ùï»Å¡…•Õï∏Å√îÄÒÕ—…Ωπú˘ÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•ÙΩÕ—…Ωπú¯∞Åµï∏Å•πùï∏ÅÖÿÅôΩ…°Öπë±ï…πîÅŸ§ÅÕÖµµïπ±•ùπï»Å°Ö»Åï∏Åâï≠…ïô—ï–Å¡…•ÃÅôΩ»ÅëïππîÅÖ≠≠’…Ö–Åªî∏ÅA…•ÕïπîÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∏Ω¿¯(ΩÕïç—•Ω∏¯ààà((ÄÄÄÄåÅMÖµµîÅëï±—îÅŸ•ππï»µ›•ëùï–ÅÕΩ¥Å…ïπëï…}¡…Ωë’ç—}¡ÖùîΩ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}¡Öùî(ÄÄÄÄåÄ¥¥Åù•»Å—…Ωõ§µ•≠Ωπï–∞Å°ï±ëï≠≠ïπëîÅ≠±•≠≠âÖ»Å…ÖµµîÅΩúÅÖπ—Ö±±ÕŸï±ùï»ÅΩùœîÅ°ï»(ÄÄÄÄåÄ°ÕÖµµîÅâï°Öπë±•πúÅôΩ»ÅÖ±±îÅ¡…Ωë’≠——Â¡ï»§∏Äâô±ÖÕ≠îàºâô±ÖÕ≠ï»àÅ§ÅÕ—ïëï–ÅôΩ»(ÄÄÄÄåÅÕ—ÖπëÖ…êÄâïÕ≠îàºâïÕ≠ï»à∞ÅÕ•ëï∏Å±•πÕï€ôÕ≠îø·ÂïëÀï¡ï»ÅÕï±ùïÃÅ§Åô±ÖÕ≠ï»∞Å•≠≠î(ÄÄÄÄåÅ≠Ωπ—Ö≠—±•πÕïïÕ≠ï»∏(ÄÄÄÅ’π•—}Õ•πù’±Ö»ÄÙÅ¡…Ωë’ç–πùï–†â’π•—}Õ•πù’±Ö»à∞Äâô±ÖÕ≠îà§(ÄÄÄÅ’π•—}¡±’…Ö∞ÄÙÅ¡…Ωë’ç–πùï–†â’π•—}¡±’…Ö∞à∞Äâô±ÖÕ≠ï»à§(ÄÄÄÅÕ•Èï}’π•–ÄÙÅ¡…Ωë’ç–πùï–†âÕ•Èï}’π•–à∞Äâµ∞à§(ÄÄÄÅ›•ππï…}°—µ∞∞Å≈—Â}°—µ∞∞Å≈—Â}µ’±—•}°—µ∞ÄÙÅ…ïπëï…}›•ππï…}›•ëùï–°ï·}âïÕ–∞ÅΩôôï…Ã∞Å¡…Ωë’ç—lâπÖµîât∞Å’π•—}Õ•πù’±Ö»ı’π•—}Õ•πù’±Ö»∞Å’π•—}¡±’…Ö∞ı’π•—}¡±’…Ö∞∞Å¡…Ωë’ç—}•êı¡…Ωë’ç—lâ•êât∞Åç±•ç≠Ω’—Ãıç±•ç≠Ω’—Ã∞Å≈—Â}ç°Ω•çïÃÙ†ƒ∞Ä»∞Ä–∞Äÿ∞Ä‡∞Äƒ¿§∞Å•πç±’ëï}ç’Õ—Ωµ}¡•±∞ıÖ±Õî∞Å≈—Â}µ’±—•}•π±•πîıÖ±Õî§(ÄÄÄÄåÅA…•çîÅ%π—ï±±•ùïπçîÄ¥¥Åëï±–ÅµïêÅ≠Ωπ—Ö≠—±•πÕîµ¡…Ωë’≠—Õ•ëï∏Ä°-Ö§∞(ÄÄÄÄåÄ»¿»ÿ¥¿‰¥»‡ËÄâù©ï±ëï»ÅÖ±±îÅ¡…Ωë’≠—ï»Å√îÅëΩµïπï–Å≠Ωπ—Ö≠—±•πÕï»ππºà§∞(ÄÄÄÄåÅÕÖµµîÅô’π≠Õ©Ω∏∞ÅÕÖµµîÅMLÄ°ªîÅ§ÅM!I}MQe1∞ÅÕîÅëï»§∏(ÄÄÄÅ¡…•çï}°•Õ—Ω…Â}°—µ∞ÄÙÅ…ïπëï…}¡…•çï}•π—ï±±•ùïπçî°¡…•çï}°•Õ—Ω…‰ÅΩ»Åmt∞Å¡…Ωë’ç—lâπÖµîât∞Å’π•—}Õ•πù’±Ö»∞Å’π•—}¡±’…Ö∞∞ÅΩôôï…ÃıΩôôï…Ã∞Å¡…Ωë’ç—}•êı¡…Ωë’ç—lâ•êât§(ÄÄÄÅÕ•Èï}µ∞ÄÙÅ¡…Ωë’ç–πùï–†âÕ•Èï}µ∞à§(ÄÄÄÅ¡…•çï}¡ï…}’π•—}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅÕ•Èï}µ∞ÅÖπêÅï·}âïÕ–Ë(ÄÄÄÄÄÄÄÅ¡ï…|ƒ¿¿ÄÙÅï·}âïÕ—lâ¡…•çï}πΩ¨âtÄºÅÕ•Èï}µ∞Ä®Äƒ¿¿(ÄÄÄÄÄÄÄÅ¡…•çï}¡ï…}’π•—}°—µ∞ÄÙÅòúÒ¿Åç±ÖÕÃÙâ¡…•çîµ¡ï»µ’π•–à˘Ì}ôµ—}≠»°¡ï…|ƒ¿¿•ÙÅ¡ï»Äƒ¿¿ÅÌÕ•Èï}’π•—Ù∞ÅŸïêÅ±ÖŸïÕ—îÅ¡…•ÃÄ°’—ï∏Åô…Ö≠–§Ω¿¯ú(ÄÄÄÅ—°’µàÄÙÅ}•µù}—Öú°}±Ö…ùï…}ôïïë}•µÖùî°•µÖùï}’…∞§∞Å¡…Ωë’ç—lâπÖµîât∞Å±ΩÖë•πúÙâïÖùï»à§Å•òÅ•µÖùï}’…∞Åp(ÄÄÄÄÄÄÄÅï±ÕîÅïÕçÖ¡î°¡…Ωë’ç—lââ…Öπë}±Öâï∞âulË…tπ’¡¡ï»†§§((ÄÄÄÅÕÖôï—Â}πΩ—•çîÄÙÄàà(ÄÄÄÅ•òÅ¡…Ωë’ç–πùï–†âÕΩ±’—•Ωπ}—Â¡îà§ÄÙÙÄâ¡ï…Ω·•ëîàË(ÄÄÄÄÄÄÄÅÕÖôï—Â}πΩ—•çîÄÙÄàààÒë•ÿÅç±ÖÕÃÙâÕÖôï—‰µπΩ—•çîà¯(ÄÄÒÕ—…Ωπú˘Aï…Ω≠Õ•ëâÖÕï…–Å±•πÕï€ôÕ≠îΩÕ—…Ωπú¯Å∑îÅª·Â—…Ö±•Õï…ïÃÅ§Å…•≠—•úÅΩ¡¡âïŸÖ…•πùÕï—’§Åõ·»Å±•πÕïπîÅÕï——ïÃÅ§É·Âï–Å•ù©ï∏Ä¥¥Åõ·±úÅÖ±±—•êÅâ…’≠ÕÖπŸ•Õπ•πùï∏∏Å1•πÕï»ÅÕÖ—–Åë•…ï≠—îÅ§Å’ôΩ…—Âππï–Å¡ï…Ω≠Õ•ë≥·Õπ•πúÅ≠Ö∏Åù§ÅÖ±ŸΩ…±•úÉ·ÂïÕ≠Öëî∏(Ωë•ÿ¯ààà((ÄÄÄÅ•π}Õ—Ωç≠}Ωôôï…ÃÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÅÕç°ïµÖ}Ωôôï…ÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏°òúúùÌÏ(ÄÄÄÄÄÄÄÄâ—Â¡îàËÄâ=ôôï»à∞(ÄÄÄÄÄÄÄÄâÕï±±ï»àËÅÌÏâ—Â¡îàËÄâ=…ùÖπ•ÈÖ—•Ω∏à∞ÄâπÖµîàËÄâÌïÕçÖ¡î°Ωlâ…ï—Ö•±ï»ât•ÙâıÙ∞(ÄÄÄÄÄÄÄÄâ¡…•çîàËÅÌΩlâ¡…•çï}πΩ¨âuÙ∞(ÄÄÄÄÄÄÄÄâ¡…•çï’……ïπç‰àËÄâ9=,à∞(ÄÄÄÄÄÄÄÄâ’…∞àËÄâÌ}©ÕΩπ}Õ—»°Ωlâ’…∞ât•Ùà∞(ÄÄÄÄÄÄÄÄâÖŸÖ•±Öâ•±•—‰àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úΩ%πM—Ωç¨à∞(ÄÄÄÄÄÄÄÄâÕ°•¡¡•πùï—Ö•±ÃàËÅÌÏ(ÄÄÄÄÄÄÄÄÄÄâ—Â¡îàËÄâ=ôôï…M°•¡¡•πùï—Ö•±Ãà∞(ÄÄÄÄÄÄÄÄÄÄâÕ°•¡¡•πùIÖ—îàËÅÌÏâ—Â¡îàËÄâ5Ωπï—Ö…ÂµΩ’π–à∞ÄâŸÖ±’îàËÅÌΩlâÕ°•¡¡•πù}πΩ¨âuÙ∞Äâç’……ïπç‰àËÄâ9=,âıÙ∞(ÄÄÄÄÄÄÄÄÄÄâÕ°•¡¡•πùïÕ—•πÖ—•Ω∏àËÅÌÏâ—Â¡îàËÄâïô•πïëIïù•Ω∏à∞ÄâÖëë…ïÕÕΩ’π—…‰àËÄâ9<âıÙ(ÄÄÄÄÄÄÄÅıÙ(ÄÄÄÄÄÅıÙúúúÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§(ÄÄÄÅ±Ω›}¡…•çîÄÙÅµ•∏†°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§∞ÅëïôÖ’±–Ù¿§(ÄÄÄÅ°•ù°}¡…•çîÄÙÅµÖ‡†°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§∞ÅëïôÖ’±–Ù¿§((ÄÄÄÅΩôôï…Õ}Õç°ïµÑÄÙÄàà(ÄÄÄÅ•òÅ•π}Õ—Ωç≠}Ωôôï…ÃË(ÄÄÄÄÄÄÄÅΩôôï…Õ}Õç°ïµÑÄÙÅòúúú∞(ÄÄâΩôôï…ÃàËÅÌÏ(ÄÄÄÄâ—Â¡îàËÄâùù…ïùÖ—ï=ôôï»à∞(ÄÄÄÄâ¡…•çï’……ïπç‰àËÄâ9=,à∞(ÄÄÄÄâ±Ω›A…•çîàËÅÌ±Ω›}¡…•çïÙ∞(ÄÄÄÄâ°•ù°A…•çîàËÅÌ°•ù°}¡…•çïÙ∞(ÄÄÄÄâΩôôï…Ω’π–àËÅÌ±ï∏°•π}Õ—Ωç≠}Ωôôï…Ã•Ù∞(ÄÄÄÄâΩôôï…ÃàËÅmÌÕç°ïµÖ}Ωôôï…Õıt(ÄÅıÙúúú((ÄÄÄÅëÖ—ï}µΩë•ô•ïêÄÙÅµÖ‡†°Ωlâç°ïç≠ïë}Ö–âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄåÅ	…ïÖëç…’µâ1•Õ–Ä°ÕÖµµîÅô•≠ÃÅÕΩ¥Å…ïπëï…}¡…Ωë’ç—}¡ÖùîÄ»¿»ÿ¥¿‰¥¿‘§Ä¥¥(ÄÄÄÄåÅÕ¡ï•±ï»Åëï∏ÅÕÂπ±•ùîÅâÀ·ëÕµ’±ï∏Ä°!©ï¥Ä¯Å≠Ö—ïùΩ…§Ä¯Å¡…Ωë’≠—πÖŸ∏∞Å•πùï∏(ÄÄÄÄåÅïùï–Åµï…≠îµπ•€îÅ°ï»ÅÕ•ëï∏Å±•πÕï€ôÕ≠îø·ÂïëÀï¡ï»µÕ•ëï»Å•≠≠îÅ°Ö»Åëï–§∏(ÄÄÄÅâ…ïÖëç…’µâ}Õç°ïµÑÄÙÅòúúùÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°çÖ—lâ±Öâï∞ât•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩÌçÖ—}Õ±’ùÙºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄÃ∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°¡…Ωë’ç—lâπÖµîât•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ıÌâÖÕï}’…±}¡Ö—°ÙâıÙ(ÄÅuıÙúúú(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅmÌâ…ïÖëç…’µâ}Õç°ïµÖÙ∞ÅÌÏ(ÄÄâ—Â¡îàËÄâA…Ωë’ç–à∞(ÄÄâπÖµîàËÄâÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•Ùà∞(ÄÄâëïÕç…•¡—•Ω∏àËÄâÌïÕçÖ¡î°±Ωπù}ëïÕç…•¡—•Ω∏•Ùà∞(ÄÄââ…ÖπêàËÅÌÏâ—Â¡îàËÄâ	…Öπêà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°¡…Ωë’ç—lââ…Öπë}±Öâï∞ât•ÙâııÌòú∞Äâ•µÖùîàËÄâÌïÕçÖ¡î°}ÖâÕ}’…∞°•µÖùï}’…∞§•ÙàúÅ•òÅ•µÖùï}’…∞Åï±ÕîÄàâıÌòú∞ÄâëÖ—ï5Ωë•ô•ïêàËÄâÌëÖ—ï}µΩë•ô•ïëÙàúÅ•òÅëÖ—ï}µΩë•ô•ïêÅï±ÕîÄàâıÌΩôôï…Õ}Õç°ïµÖÙ(ÄÅııt)ıÙààà(ÄÄÄÅÕç°ïµÖ}©ÕΩπ}°—µ∞ÄÙÅòúÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯úÅ•òÅ•π}Õ—Ωç≠}Ωôôï…ÃÅï±ÕîÄàà((ÄÄÄÄåÅMÖµµîÅëÂπÖµ•Õ≠îÅDΩIï±Ö—ï…–µ∑·πÕ—ï»ÅÕΩ¥Å…ïπëï…}¡…Ωë’ç—}¡Öùî∞Å—•±¡ÖÕÕï–(ÄÄÄÄåÅ±•πÕï€ôÕ≠îø·ÂïëÀï¡ï»ÅÕ•∏ÅëÖ—ÖµΩëï±∞Ä°Õ•Èï}µ∞Å§ÅÕ—ïëï–ÅôΩ»Å¡Ö≠π•πúÅµïê(ÄÄÄÄåÅ±•πÕïÖπ—Ö±∞∞Å•πùï∏Åµï…≠ïÕ•ëîΩ¡…Ωë’Õïπ—Õ•ëîÉîÅ±ïπ≠îÅ—•∞ÅôΩ»Åë•ÕÕî(ÄÄÄÄåÅµï…≠ïπîÄ¥¥ÅÕîÅïùï∏Å≠Ωµµïπ—Ö»Å§Å…ïπëï…}ÕΩ±’—•Ωπ}çÖ—ïùΩ…Â}¡ÖùîÅΩ¥(ÄÄÄÄåÅ°ŸΩ…ôΩ»§∏Äâ!ŸΩ»Å±ïπùîÅŸÖ…ï»àÅ’—ï±Ö—ïÃÅâïŸ•ÕÕ–Ä¥¥ÅŸ§Å°Ö»Å•≠≠îÅ√ï±•—ï±•ú(ÄÄÄÄåÅëÖ—ÑÅ√îÅôΩ…â…’¨Å¡ï»ÅëÖúÅôΩ»Å±•πÕï€ôÕ≠îø·ÂïëÀï¡ï»∏(ÄÄÄÅ¡…Ωë’ç—}ôÖƒËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅ•òÅâïÕ–Ë(ÄÄÄÄÄÄÄÅç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï»ÄÙÅµ•∏°•π}Õ—Ωç≠}Ωôôï…Ã∞Å≠ï‰ı±ÖµâëÑÅºËÅΩlâ¡…•çï}πΩ¨ât§(ÄÄÄÄÄÄÄÅ•òÅç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï…lâ…ï—Ö•±ï»âtÄÑÙÅâïÕ—lâ…ï—Ö•±ï»âtË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•±±•ùÕ—}ÕŸÖ»ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï…lâ…ï—Ö•±ï»âuÙÅ°Ö»Å±ÖŸïÕ–Å¡…Ωë’≠—¡…•ÃËÅÌ}ôµ—}≠»°ç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï…lâ¡…•çï}πΩ¨ât•ÙÅ’—ï∏Åô…Ö≠–∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùIïùπï»Åë‘ÅµïêÅô…Ö≠–∞Åâ±•»ÅÌâïÕ—lâ…ï—Ö•±ï»âuÙÅâ•±±•ùÕ–ËÅÌ}ôµ—}≠»°âïÕ—lâ—Ω—Ö∞ât•ÙÅ—Ω—Ö±–Å•π≠±’ëï…–Åô…Ö≠–∏ú(ÄÄÄÄÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•±±•ùÕ—}ÕŸÖ»ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌâïÕ—lâ…ï—Ö•±ï»âuÙÅ°Ö»Å±ÖŸïÕ–Å¡…•Ã∞ÅãïëîÅ’—ï∏ÅΩúÅµïêÅô…Ö≠–ËÅÌ}ôµ—}≠»°âïÕ—lâ¡…•çï}πΩ¨ât•ÙÅ’—ï∏Åô…Ö≠–Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòú°Ì}ôµ—}≠»°âïÕ—lâ—Ω—Ö∞ât•ÙÅ•π≠±’ëï…–Åô…Ö≠–§∏ú(ÄÄÄÄÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ïâ≈’ïÕ—•Ω∏àËÅòù!ŸΩ»Åï»ÅÌ¡…Ωë’ç—lâπÖµîâuÙÅâ•±±•ùÕ–¸ú∞ÄâÖπÕ›ï»àËÅâ•±±•ùÕ—}ÕŸÖ…Ù§((ÄÄÄÄÄÄÄÅ±ÖŸïÕ—ï}¡…Ωë’≠—¡…•ÃÄÙÅµ•∏°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§(ÄÄÄÄÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ŸÑÅ≠ΩÕ—ï»ÅÌ¡…Ωë’ç—lâπÖµîâuÙ¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù1ÖŸïÕ—îÅ¡…Ωë’≠—¡…•ÃÅ√îÅÌ¡…Ωë’ç—lâπÖµîâuÙÅï»ÅÌ}ôµ—}≠»°±ÖŸïÕ—ï}¡…Ωë’≠—¡…•Ã•ÙÅ’—ï∏Åô…Ö≠–ÅÖ≠≠’…Ö–Åªî∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùQΩ—Ö±¡…•Õï∏ÅÖŸ°ïπùï»ÅÖÿÅ°Ÿ•±≠ï∏Åâ’—•≠¨Åë‘ÅŸï±ùï»ÅΩúÅô…Ö≠—≠ΩÕ—πÖëï∏Åëï»∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ•òÅÕ•Èï}µ∞Ë(ÄÄÄÄÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ŸΩ»ÅµÖπùîÅµ∞Åï»Åëï–Å§ÅÌ¡…Ωë’ç—lâπÖµîâuÙ¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùÌ’π•—}Õ•πù’±Ö»πçÖ¡•—Ö±•Èî†•ı∏Å•ππï°Ω±ëï»ÅÌÕ•Èï}µ∞Ë∏¡ôÙÅÌÕ•Èï}’π•—Ù∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅΩô—îÅΩ¡¡ëÖ—ï…ïÃÅ¡…•Õïπî¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ-Ωπ—Ö≠—±•πÕï»ππºÅ°ïπ—ï»ÅΩúÅΩ¡¡ëÖ—ï…ï»Å¡…•Õï»ÅÖ’—ΩµÖ—•Õ¨ÅëÖù±•ú∏ÅY§ÅŸ•Õï»Åâ’—•≠≠ïπÃÅ¡…Ωë’≠—¡…•ÃÄà(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ’—ï∏Åô…Ö≠–ÅΩúÅâï…ïùπï»Å—Ω—Ö±¡…•ÃÅâÖÕï…–Å√îÅô…Ö≠–ÅΩúÅÖπ—Ö±±ï–Åë‘ÅŸï±ùï»∏à∞(ÄÄÄÅÙ§((ÄÄÄÅ¡…Ωë’ç—}ôÖ≈}°—µ∞∞Å¡…Ωë’ç—}ôÖ≈}Õç°ïµÑÄÙÅ}…ïπëï…}ôÖ≈}â±Ωç¨°¡…Ωë’ç—}ôÖƒ∞ÅòùYÖπ±•ùîÅÕ√·…Õ∑ï∞ÅΩ¥ÅÌ¡…Ωë’ç—lâπÖµîâuÙú§((ÄÄÄÅ…ï±Ö—ïë}±•π≠ÃÄÙÅòúÒ±§¯ÒÑÅ°…ïòÙàΩÌçÖ—}Õ±’ùÙºà˘±±îÅÌïÕçÖ¡î°çÖ—lâ±Öâï∞âtπ±Ω›ï»†§•ÙΩÑ¯Ω±§¯ú(ÄÄÄÅ…ï±Ö—ïë}°—µ∞ÄÙÅòàààÒë•ÿÅç±ÖÕÃÙâ…ï±Ö—ïêà¯(ÄÄÄÄÒ†»˘Iï±Ö—ï…–Å—•∞ÅÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•ÙΩ†»¯(ÄÄÄÄÒ’∞¯(ÄÄÄÅÌ…ï±Ö—ïë}±•π≠ÕÙ(ÄÄÄÄΩ’∞¯(ÄÄΩë•ÿ¯ààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•ÙÉ
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•ÃΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°µï—Ö}ëïÕç…•¡—•Ω∏•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ıÌâÖÕï}’…±}¡Ö—°Ùà¯)Ì}Ωù}µï—Ñ°òùÌ¡…Ωë’ç—lâπÖµîâuÙÉ
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•Ãú∞Åµï—Ö}ëïÕç…•¡—•Ω∏∞ÅòùÌ	M}UI1ıÌâÖÕï}’…±}¡Ö—°Ùú∞Å•µÖùï}’…∞•Ù)Ì=9Q}1%9-MÙ)ÌÕç°ïµÖ}©ÕΩπ}°—µ±Ù)Ì¡…Ωë’ç—}ôÖ≈}Õç°ïµÖÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù)Ì!I=}%5}MQe1Ù)Ì]%99I}]%Q}MQe1Ù)ÌAI%}1%MQ}MQe1Ù(π¡…•çîµ¡ï»µ’π•–ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏ËÄƒ…¡‡Ä¿Ä¿ÏÅıÙ(º®Å±ÖÕ≠î¥Ω—’âïâ•±ëï»Åï»Å£·ÂîÅΩúÅÕµÖ±îËÅôÖÕ–Å≠ŸÖë…Ö—•Õ¨Å…’—îÄ°ÕΩ¥Å±•πÕïâ•±ëïπî§(ÄÄÅ√îÅµΩâ•∞∞Å§ÅÕ—ïëï–ÅôΩ»ÉîÅ±ÑÅâ•±ëï—ÃÅïùï∏Å£·ÂëîÅÕ—…ï≠≠îÅ°ï±îÅ°ï…ºµ≠Ω…—ï–∏(ÄÄÄ¯Ù‡ÿ¡¡‡ËÅ!I=}%5}MQe1ÅÕ•∏Äπ¡…Ωë’ç–µÕ—Öùîµù…•êÅÕï——ï»Åï∏ÅôÖÕ–(ÄÄÅâ•±ëï£·ÂëîÄ†Ã»¡¡‡§Å’ÖπÕï—–Å¡…Ωë’≠——Â¡î∞ÅÕÖµµîÅÕΩ¥Å≠Ωπ—Ö≠—±•πÕî¥(ÄÄÅ¡…Ωë’≠—Õ•ëï∏Ä¥¥Å•πùï∏Åïùï∏ÅëïÕ≠—Ω¿µΩŸï…Õ—Â…•πúÅª·ëŸïπë•úÅ°ï»Å±ïπùï»(ÄÄÄ†»¿»ÿ¥¿‰¥»‡∞ÄâÕÖµµîÅ°ï…º¥Ω≈’Öπ—•—‰µ…ïëïÕ•ù∏àµ…’πëï∏§∏Ä®º)µïë•ÑÄ°µÖ‡µ›•ë—†ËÄ‡‘Â¡‡§ÅÌÏÄπ°ï…ºµçÖ…êµÕΩ±’—•Ω∏Äπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÅÌÏÅÖÕ¡ïç–µ…Ö—•ºËÄƒÄºÄƒÏÅ°ï•ù°–ËÅÖ’—ºÏÅıÙÅıÙ(πÕÖôï—‰µπΩ—•çîÅÌÏÅâÖç≠ù…Ω’πêËÄç—‘ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡ÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»µ±ïô–ËÄ—¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ¿Äƒ¡¡‡Äƒ¡¡‡Ä¿ÏÅ¡Öëë•πúËÄƒ—¡‡Äƒ·¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰’…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰Å¿ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰πôÖ±±âÖç¨ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ’—ïêµâú§ÏÅâΩ…ëï»µ±ïô–µçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ¡…Ωë’ç–à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯(ÄÄÄÄÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäË(ÄÄÄÄÒÑÅ°…ïòÙàΩÌçÖ—}Õ±’ùÙºà˘ÌïÕçÖ¡î°çÖ—lâ±Öâï∞ât•ÙΩÑ¯ÉäË(ÄÄÄÅÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•Ù(ÄÄΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µÕ—Öùîà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçÖ…êÅ°ï…ºµçÖ…êµÕΩ±’—•Ω∏à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµµÖ•∏à¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµ≠•ç≠ï»à˘ÌïÕçÖ¡î°¡…Ωë’ç—lââ…Öπë}±Öâï∞ât•ÙΩë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•ÙΩ†ƒ¯(ÄÄÄÄÄÄÄÄÄÄÒ¿Åç±ÖÕÃÙâ°ï…ºµÕ’â—•—±îà˘MÖµµïπ±•ù∏Å¡…•Õï»Ω¿¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµµïë•Ñµ…Ω‹à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµ¡…Ωë’ç–µ•µÖùïÏúÅ°ÖÃµ¡°Ω—ºúÅ•òÅ•µÖùï}’…∞Åï±ÕîÄúùÙà˘Ì—°’µâÙΩë•ÿ¯(ÄÄÄÄÄÄÄÄÄÅÌ›•ππï…}°—µ±Ù(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÅÌ≈—Â}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÅÌÕÖôï—Â}πΩ—•çïÙ(ÄÅÌΩôôï…Õ}â±Ωç≠Ù(ÄÅÌ¡…•çï}°•Õ—Ω…Â}°—µ±Ù(ÄÅÌ≈—Â}µ’±—•}°—µ±Ù(ÄÅÌAI%}%M1=MUI}!Q51Ù(ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅ-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—î∞Å•≠≠îÅï∏(ÄÄÄÅôΩ…°Öπë±ï»Åï±±ï»Åï–ÅÖ¡Ω—ï¨∏ÅKïëõ·»ÅëïúÅµïêÅΩ¡—•≠ï»Åï±±ï»É·Âï±ïùîÅΩ¥(ÄÄÄÅ°ŸÑÅÕΩ¥Å¡ÖÕÕï»ÅôΩ»ÅëïúÅΩúÅë•πîÅ≠Ωπ—Ö≠—±•πÕï»∏(ÄÄΩ¿¯(ÄÄÒ†»˘=¥ÅÌïÕçÖ¡î°¡…Ωë’ç—lâπÖµîât•ÙΩ†»¯(ÄÄÒ¿˘ÌïÕçÖ¡î°±Ωπù}ëïÕç…•¡—•Ω∏•ÙΩ¿¯(ÄÅÌ¡…•çï}¡ï…}’π•—}°—µ±Ù(ÄÅÌÖ•}Õ’µµÖ…Â}°—µ±Ù(ÄÅÌ¡…Ωë’ç—}ôÖ≈}°—µ±Ù(ÄÅÌ5Q!==1=e}!Q51Ù(ÄÅÌ…ï±Ö—ïë}°—µ±Ù(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}ÕΩ±’—•Ωπ}çÖ—ïùΩ…Â}¡Öùî°ÕΩ±’—•Ωπ}çÖ—ïùΩ…‰ËÅÕ—»∞Å¡…Ωë’ç—ÃËÅ±•Õ—më•ç—t∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§((ÄÄÄÅ…Ω›ÃÄÙÅmt(ÄÄÄÅôΩ»Å¿Å•∏Å¡…Ωë’ç—ÃË(ÄÄÄÄÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°¡lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅï±•ù•â±îÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÄÄÄÄÅ±Ω›ïÕ–ÄÙÅµ•∏°ï±•ù•â±î∞Å≠ï‰ı±ÖµâëÑÅºËÄ°Ωlâ¡…•çï}πΩ¨ât∞ÅΩlâ—Ω—Ö∞ât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄÄÄÄÅ…Ω›ÃπÖ¡¡ïπê°Ïâ¡…Ωë’ç–àËÅ¿∞Äâ±Ω›ïÕ–àËÅ±Ω›ïÕ—Ù§((ÄÄÄÅ…Ω›ÃπÕΩ…–°≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÅ•òÅ…lâ±Ω›ïÕ–âtÅï±ÕîÅô±ΩÖ–†â•πòà§§((ÄÄÄÅëïòÅ…ïπëï…}…Ω‹°»ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ¿∞Å±Ω›ïÕ–ÄÙÅ…lâ¡…Ωë’ç–ât∞Å…lâ±Ω›ïÕ–ât(ÄÄÄÄÄÄÄÅ•µÖùï}’…∞ÄÙÅ}¡…Ωë’ç—}•µÖùî°¿§(ÄÄÄÄÄÄÄÄåÅ1•πÕï€ôÕ≠ï»ø·ÂïëÀï¡ï»µµï…≠ï»Å°Ö»Å1I$Åï∏Åïùï∏ÄΩµï…≠îΩÌÌÕ±’ùıÙºµÕ•ëî(ÄÄÄÄÄÄÄÄåÄ°ëï∏ÅâÂùùïÃÅ≠’∏ÅôΩ»Å±•πÕîµµï…≠ï»Å§Åùïπï…Ö—ï}¡ÖùïÃπ¡‰∞Åâï≠…ïô—ï–Ä¿(ÄÄÄÄÄÄÄÄåÅΩŸï…±Ö¡¿Åµï±±Ω¥Åâ…Öπë}Õ±’úµÕï——ïπî§Ä¥¥Å…ï∏Å—ï≠Õ–∞Å•≠≠îÅï∏Å±ïπ≠î∞(ÄÄÄÄÄÄÄÄåÅôΩ»ÉîÅ’ππüîÅï∏Ä–¿–Å°ï»∏(ÄÄÄÄÄÄÄÅâ…Öπë}±•π¨ÄÙÅòúÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµµÖπ’ôÖç—’…ï»àÅÕ—Â±îÙâç’…ÕΩ»ÈëïôÖ’±–Ïà˘ÌïÕçÖ¡î°¡lââ…Öπë}±Öâï∞ât•ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÅ…ï—’…∏Å}…ïπëï…}¡…Ωë’ç—}—•±î†(ÄÄÄÄÄÄÄÄÄÄÄÅ°…ïòıòúΩÌÕΩ±’—•Ωπ}çÖ—ïùΩ…ÂÙΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºú∞(ÄÄÄÄÄÄÄÄÄÄÄÅπÖµîı¡lâπÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÅ•µÖùï}’…∞ı•µÖùï}’…∞∞(ÄÄÄÄÄÄÄÄÄÄÄÅôÖ±±âÖç≠}•π•—•Ö±Ãı¡lââ…Öπë}±Öâï∞âulË…tπ’¡¡ï»†§∞(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ıçÖ—lâ±Öâï∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕïçΩπëÖ…Â}±•πï}°—µ∞ıâ…Öπë}±•π¨∞(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ïÕ–ı±Ω›ïÕ–∞(ÄÄÄÄÄÄÄÄÄÄÄÅΩ—°ï…}çΩ’π–ı±ï∏°¡lâΩôôï…Ãât§Ä¥Äƒ∞(ÄÄÄÄÄÄÄÄÄÄÄÅçΩµ¡Ö…•ÕΩπ}Ωôôï…Ãı…ïçΩπç•±ï}¡…Ωë’ç–°¡lâΩôôï…Ãât∞ÅπΩ‹§∞(ÄÄÄÄÄÄÄÄ§((ÄÄÄÅçÖ–ÄÙÅM=1UQ%=9}Q=I%MmÕΩ±’—•Ωπ}çÖ—ïùΩ…Ât(ÄÄÄÅ¡…Ωë’ç—}…Ω›Õ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°…ïπëï…}…Ω‹°»§ÅôΩ»Å»Å•∏Å…Ω›Ã§((ÄÄÄÅÕç°ïµÖ}•—ïµÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÅÌ§¨≈Ù∞Äâ’…∞àËÄâÌ	M}UI1ÙΩÌÕΩ±’—•Ωπ}çÖ—ïùΩ…ÂÙΩÌ¡lââ…Öπë}Õ±’úâuÙΩÌ¡lâÕ±’úâuÙºà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°¡lâπÖµîât•ÙâıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å§∞Å¿Å•∏Åïπ’µï…Ö—î°¡…Ωë’ç—Ã§(ÄÄÄÄ§(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌïÕçÖ¡î°çÖ—lâ±Öâï∞ât•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩÌÕΩ±’—•Ωπ}çÖ—ïùΩ…ÂÙºâıÙ(ÄÄÄÅuıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ%—ïµ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅmÌÕç°ïµÖ}•—ïµÕıuıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°çÖ—lâ—•—±ï}±Öâï∞ât•ÙÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°çÖ–πùï–†âµï—Ö}ëïÕç…•¡—•Ω∏à∞ÅçÖ—lâ•π—…ºât§•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩÌÕΩ±’—•Ωπ}çÖ—ïùΩ…ÂÙºà¯)Ì}Ωù}µï—Ñ°òùÌçÖ—lâ—•—±ï}±Öâï∞âuÙÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞ÅçÖ—lâ•π—…ºât∞ÅòùÌ	M}UI1ÙΩÌÕΩ±’—•Ωπ}çÖ—ïùΩ…ÂÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯(ÒÕ—Â±î˘ÌM!I}MQe1ÙΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°çÖ—lâ±Öâï∞ât•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘Q•±âï£·»Ωë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°çÖ—lâ±Öâï∞ât•ÙΩ†ƒ¯(ÄÄÄÄÄÄÒ¿˘ÌïÕçÖ¡î°çÖ—lâ•π—…ºât•ÙΩ¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ±•Õ–µ°ïÖëï»à¯(ÄÄÄÄÒ†»˘Ì±ï∏°¡…Ωë’ç—Ã•ÙÅ¡…Ωë’≠—ï»Ω†»¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅ•êÙâ¡…Ωë’ç–µ±•Õ–àÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµù…•êà¯(ÄÄÄÅÌ¡…Ωë’ç—}…Ω›Õ}°—µ±Ù(ÄÄΩë•ÿ¯((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅY§ÅÕΩ…—ï…ï»ÅÖ±±—•êÅï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ÅY§Å≠Ö∏ÅõîÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Å°Öπë±ï»(ÄÄÄÅŸ•ÑÅ±ïπ≠ïπîÅ√îÅ¡…Ωë’≠—Õ•ëïπî∞Åµï∏Åëï–Å√ïŸ•…≠ï»Å•≠≠îÅ¡…•Õï∏Åë‘Åâï—Ö±ï»(ÄÄÄÅï±±ï»Å…Öπùï…•πùï∏ÅÖÿÅ¡…Ωë’≠—ï»Åï±±ï»Å—•±â’ê∏Å-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏(ÄÄÄÅ’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—î∞Å•≠≠îÅï∏ÅôΩ…°Öπë±ï»∏(ÄÄΩ¿¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}â…Öπë}¡Öùî°ç°Ö•∏ËÅÕ—»∞Å±Öâï±ÃËÅ±•Õ—më•ç—t∞Å¡…Ωë’ç—Õ}âÂ}•êËÅë•ç–∞ÅçÖ—ïùΩ…•ïÃËÅë•ç–∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî∞Å¡…•çï}°•Õ—Ω…‰ËÅë•ç–ÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâùï∏Äùµï…≠îúµÕ•ëîÅôΩ»Åï∏ÅΩ¡—•≠ï…≠©ïëïÃÅ¡…•ŸÖ—îÅ±Öâï∞µÕï…•îÄ°òπï≠Ã∏(ÄÄÄÄΩµï…≠îΩïÂïƒºÅôΩ»ÅMÂπÕÖ¥ÅÕ•∏ÅÂïDµÕï…•î§Ä¥¥ÅÕÖµµîÅUI0µ∑·πÕ—ï»ÅΩú(ÄÄÄÅ≠Ω…—Õ—•∞ÅÕΩ¥Å…ïπëï…}â…Öπë}¡Öùî†§∞Åµï∏Å≠•±ëïëÖ—ÑÅï»Å¡…•ŸÖ—ï}±Öâï±Ãπ©ÕΩ∏(ÄÄÄÄ¨ÅëîÅï≠—îÅ¡…Ωë’≠—ïπïÃÅ—•±â’êÄ°•πùï∏Åïùï∏Å¡…•ÕëÖ—ÑÅ°ï»Å°ï±±ï»∞ÅÕî(ÄÄÄÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}¡Öùî†§§∏((ÄÄÄÄ»¿»ÿ¥¿‰¥»‰ËÅ≥·ô—ï–Å—•∞ÅM55ÅÕ—…’≠—’»ÅÕΩ¥Å…ïπëï…}â…Öπë}¡Öùî†§Ä°-Ö§Ë(ÄÄÄÄãaπÕ≠ï»Å±•≠–ÅÕΩ¥ÅÖ±±îÅÖπë…îÅµï…≠ï»à§Ä¥¥ÅÕ—Ö–µÕ—…•¡îÅ§Å°ï…Ωï∏∞(ÄÄÄÄâÌÕ’ââ…ÖπëÙÅ§Å—Ö±∞à∞Åï≠—îÅ¡…•Õ•ππÕ•≠–µù…ÖòÄ°ù©ïπâ…’≠ï»(ÄÄÄÅ}ôÖµ•±Â}¡…•çï}•πÕ•ù°—}ëÖ—Ñ†§Ω…ïπëï…}ôÖµ•±Â}¡…•çï}•πÕ•ù°–†§ÅCÅQYILÅÖÿ(ÄÄÄÅÖ±±îÅŸÖ…•Öπ—ïπî∞ÅÖ≠≠’…Ö–ÅÕΩ¥Åµï…≠îµÕ•ëï∏Åù´·»Å√îÅ—Ÿï…ÃÅÖÿÅï–Åµï…≠ï—Ã(ÄÄÄÅ¡…Ωë’≠—ï»§∞ÄâÌÕ’ââ…ÖπëÙµÕΩ…—•µïπ—ï–ÅôΩ…≠±Ö…–àÅ¡ï»Å≠Ö—ïùΩ…§∞Åï∏(ÄÄÄÅµÖ—ï…•Ö±ï»µÕï≠Õ©Ω∏∞ÄàÃ¿Åï±±ï»Ä‰¿Å±•πÕï»¸à∞ÅDµ…ïùï±µΩ—Ω»ÅΩú(ÄÄÄÅ…ïÕÕ’…Ã¥Ω—•±±•–µâ’π∏Ä¥¥ÅÖ±–ÅŸ•ÑÅëï∏Åëï±—îÅÅ	I9}A}MQe1Äµ≠ΩπÕ—Öπ—ï∏(ÄÄÄÄ°ô±Â——ï–Å’–ÅÖÿÅ…ïπëï…}â…Öπë}¡Öùî†§ÅÕ•∏Åïùï∏ÄÒÕ—Â±î¯µâ±Ω≠¨Å§ÅÕÖµµî(ÄÄÄÅ…’πëî∞Åª·ÂÖ≠—•úÅÕÖµµîÅML∞Å•πùï∏Åë’¡±•Õï…•πú§∏((ÄÄÄÅ	Y%MMPÅUQ1QPÄ°ÖëÖ¡—•Ÿ–∞ÅÕÖµµîÅ¡…•πÕ•¡¿ÅÕΩ¥Åï–Åï≠—îÅµï…≠îÅ’—ï∏Åïùï∏(ÄÄÄÅÕï…•îÅ§Å…ïπëï…}â…Öπë}¡Öùî†§§ËÄâU—ôΩ…Õ¨ÅÕï…•ïπîàµ≠Ω…—ïπîÅΩú(ÄÄÄÄâM±•¨ÅÕ≠•±±ï»ÅÕï…•ïπîÅÕïúàµ—Öâï±±ï∏∞ÅÕ•ëï∏Å¡…•ŸÖ—îÅ±Öâï∞µŸÖ…•Öπ—ï»Å•≠≠î(ÄÄÄÅ°Ö»ÅπΩï∏Åïùï∏Å¡…Ωë’ç—}ôÖµ•±•ïÃπ©ÕΩ∏µù…’¡¡ï…•πúÄ°°Ÿï»ÅŸÖ…•Öπ–Åï»Åï∏(ÄÄÄÄƒËƒµÖ±•ÖÃÅôΩ»Åï—–Åï≠—îÅ¡…Ωë’≠–∞Å•≠≠îÅï∏Åô±ï…¡Ö≠π•πúΩô±ï…ŸÖ…•Öπ–µÕï…•î(ÄÄÄÅ§ÅÕïúÅÕï±ÿ§Ä¥¥ÅôÖµ•±Â}Õ’µµÖ…•ïÃÅï»Åëï…ôΩ»ÅÖ±±—•êÅ—Ω¥Å±•Õ—îÅ°ï»∞ÅΩúÅëî(ÄÄÄÅ—ºÅÕï≠Õ©ΩπïπîÅÕΩ¥ÅÖŸ°ïπùï»ÅÖÿÅëï∏ÅôÖ±±ï»ÅπÖ—’…±•úÅâΩ…–∞ÅÖ≠≠’…Ö–ÅÕΩ¥Åëî(ÄÄÄÅÖ±±ï…ïëîÅù´·»ÅôΩ»Åï–Åï≠—îÅµï…≠îÅ’—ï∏Å≠’…Ö—ï…–ÅôÖµ•±•îÄ°òπï≠Ã∏(ÄÄÄÅ…ïÕ°1ΩΩ¨§∏Å!ï±±ï»Å•πùï∏Åïùï∏ÄâA…Ωë’Õïπ–àµµΩë’∞∞ÅÕ•ëï∏Åï—–ÅÕï—–Å¡…•ŸÖ—î(ÄÄÄÅ±Öâï∞µŸÖ…•Öπ—ï»Å—Â¡•Õ¨ÅÕ¡ïππï»Å1IÅ¡…Ωë’Õïπ—ï»Ä°ÂïDÅâ±Öπëï»(ÄÄÄÅΩΩ¡ï…Y•Õ•Ω∏ÅΩúÅ±çΩ∏∞ÅÕîÅ1Uπµê§Ä¥¥Å•πùï∏Åïπ≠ï±–Å¡…Ωë’Õïπ–ÉîÅ±ïπ≠î(ÄÄÄÅ—•∞∏((ÄÄÄÅ-Ö§∞Åï≠Õ¡±•Õ•—–ËÄâŸ§Åâï°Ω±ëï»ÅΩùœîÅ§Å—•±±ïùúÅ’πëï»Å—Ω¡¡âÖππï…ï∏àÄ¥¥(ÄÄÄÅÄπ¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï…ÄµâΩ≠Õï∏Ä†â!ŸÑÅï»ÅÌÕ’ââ…ÖπëÙ¸à§Å±•ùùï»Åëï…ôΩ»(ÄÄÄÅU9IPÅ…ï—–Å’πëï»ÅÄπâ…Öπêµ°ï…ΩÄ∞ÅaHÅπΩï∏ÅÖÿÅëîÅπÂîÅÕï≠Õ©Ωπïπî∏ààà(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§(ÄÄÄÅÕ’ââ…ÖπêÄÙÅAI%YQ}1	1}MU		I9Lπùï–°ç°Ö•∏∞Åç°Ö•∏§(ÄÄÄÅÕ±’úÄÙÅÕ’ââ…Öπêπ±Ω›ï»†§((ÄÄÄÅ…Ω›ÃÄÙÅmt(ÄÄÄÅôΩ»Å±Öâï∞Å•∏Å±Öâï±ÃË(ÄÄÄÄÄÄÄÅ…ïÖ±}¡…Ωë’ç–ÄÙÅ¡…Ωë’ç—Õ}âÂ}•êπùï–°±Öâï±lâ…ïÖ±}¡…Ωë’ç—}•êât§(ÄÄÄÄÄÄÄÅ•òÅ…ïÖ±}¡…Ωë’ç–Å•ÃÅ9ΩπîË(ÄÄÄÄÄÄÄÄÄÄÄÅçΩπ—•π’î(ÄÄÄÄÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°…ïÖ±}¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅï±•ù•â±îÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÄÄÄÄÅ±Ω›ïÕ–ÄÙÅµ•∏°ï±•ù•â±î∞Å≠ï‰ı±ÖµâëÑÅºËÄ°Ωlâ¡…•çï}πΩ¨ât∞ÅΩlâ—Ω—Ö∞ât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄÄÄÄÅÕ¡ïçÃÄÙÅÌÕ¡ïç}±Öâï∞ËÅŸÖ±’îÅôΩ»ÅÕ¡ïç}±Öâï∞∞ÅŸÖ±’îÅ•∏Å…ïÖ±}¡…Ωë’ç–πùï–†âÕ¡ïçÃà∞Åmt•Ù(ÄÄÄÄÄÄÄÅ¡Öç¨ÄÙÅ}¡Öç≠}Õ•Èï}ô…Ωµ}•ê°…ïÖ±}¡…Ωë’ç—lâ•êât§(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}Õ±’úÄÙÅ…ïÖ±}¡…Ωë’ç–πùï–†âçÖ—ïùΩ…Â}Õ±’úà∞Äàà§(ÄÄÄÄÄÄÄÅ…Ω›ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ±Öâï∞àËÅ±Öâï∞∞Äâ…ïÖ±}¡…Ωë’ç–àËÅ…ïÖ±}¡…Ωë’ç–∞Äâ±Ω›ïÕ–àËÅ±Ω›ïÕ–∞Äâï±•ù•â±îàËÅï±•ù•â±î∞(ÄÄÄÄÄÄÄÄÄÄÄÄâçÖ—ïùΩ…Â}±Öâï∞àËÅçÖ—ïùΩ…•ïÃπùï–°çÖ—ïùΩ…Â}Õ±’ú∞ÅÌÙ§πùï–†â±Öâï∞à∞Äàà§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµÖ—ï…•Ö∞àËÅÕ¡ïçÃπùï–†â5Ö—ï…•Ö±îà§∞Äâ¡Öç≠}Õ•ÈîàËÅ¡Öç≠l≈tÅ•òÅ¡Öç¨Åï±ÕîÅ9Ωπî∞(ÄÄÄÄÄÄÄÄÄÄÄÄåÅMÂπ—ï—•Õ¨Äâ¡…Ωë’ç–àµë•ç–Ä¥¥Å±Ö»ÅΩÕÃÅù©ïπâ…’≠îÅùïπï…•Õ≠î(ÄÄÄÄÄÄÄÄÄÄÄÄåÅ°©ï±¡ïô’π≠Õ©Ωπï»Ä°}ôÖµ•±Â}¡…•çï}•πÕ•ù°—}ëÖ—Ñ∞Å}¡Öç≠}Õ•Èï}ô…Ωµ}•ê§(ÄÄÄÄÄÄÄÄÄÄÄÄåÅÕΩ¥ÅôΩ…Ÿïπ—ï»Å¡…Ωë’ç—lâ•êâtΩ¡…Ωë’ç—lâçÖ—ïùΩ…Â}Õ±’úâtÅ’—ï∏ÉîÅ±Ö—î(ÄÄÄÄÄÄÄÄÄÄÄÄåÅÕΩ¥Å±Öâï∞ÅÕï±ÿÅï»Åï–Åï≠—îÅ≠Ö—Ö±Ωù¡…Ωë’≠–∏Å•êÅï»Å	Y%MMP(ÄÄÄÄÄÄÄÄÄÄÄÄåÅ…ïÖ±}¡…Ωë’ç–ÅÕ•∏Ä¥¥ÅÕÖµµîÅôÂÕ•Õ≠îÅŸÖ…î∞ÅÕÖµµîÅ¡…•Õ°•Õ—Ω…•≠¨∏(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡…Ωë’ç–àËÅÏâ•êàËÅ…ïÖ±}¡…Ωë’ç—lâ•êât∞ÄâπÖµîàËÅ±Öâï±lâπÖµîât∞ÄâçÖ—ïùΩ…Â}Õ±’úàËÅçÖ—ïùΩ…Â}Õ±’ùÙ∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ…Ω›ÃπÕΩ…–°≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÅ•òÅ…lâ±Ω›ïÕ–âtÅï±ÕîÅô±ΩÖ–†â•πòà§§((ÄÄÄÅëïòÅ…ïπëï…}…Ω‹°»ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÄåÅY•Õï»Å1I$Åëï–Åï≠—îÅ¡…Ωë’≠—ï—ÃÅâ•±ëîÅ°ï»Ä¥¥Åëï–Åï»Åï∏ÅÖππï∏ÅôÂÕ•Õ¨(ÄÄÄÄÄÄÄÄåÅ•ππ¡Ö≠π•πúÄ°¡…•ŸÖ—îÅ±Öâï∞µïÕ≠ïπÃÅëïÕ•ù∏Åï»Å’≠©ïπ–ÅôΩ»ÅΩÕÃ§∞ÅœîÅï–(ÄÄÄÄÄÄÄÄåÅ≥ïπ–ÅA…Ωç±ïÖ»Ω	•Ωô•π•—‰µâ•±ëîÅ’πëï»ÅÕçïπêµπÖŸπï–ÅŸ•±±îÅŸ•±±ïëï–(ÄÄÄÄÄÄÄÄåÅâ…’≠ï…ï∏Å—•∞ÉîÅ—…ºÅëï–Åï»ÅÕ±•¨Åëï∏ÅôÖ≠—•Õ≠îÅïÕ≠ï∏ÅÕï»Å’–∏ÅMÖµµî(ÄÄÄÄÄÄÄÄåÅ•π•—•Ö∞µôÖ±±âÖç¨ÅÕΩ¥Åâ…’≠ïÃÅªï»ÅŸ§Å•≠≠îÅ°Ö»Å9=Åâ•±ëîÅ§Åëï–Å°ï±îÅ—Ö—–∏(ÄÄÄÄÄÄÄÅ±Öâï∞∞Å…ïÖ±}¡…Ωë’ç–∞Å±Ω›ïÕ–ÄÙÅ…lâ±Öâï∞ât∞Å…lâ…ïÖ±}¡…Ωë’ç–ât∞Å…lâ±Ω›ïÕ–ât(ÄÄÄÄÄÄÄÅ…ïÖ±}°…ïòÄÙÅòúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ…ïÖ±}¡…Ωë’ç—lââ…Öπë}Õ±’úâuÙΩÌ…ïÖ±}¡…Ωë’ç—lâÕ±’úâuÙºú(ÄÄÄÄÄÄÄÅ…ïÖ±}¡…Ωë’ç—}±•π¨ÄÙÅòúÒÑÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµµÖπ’ôÖç—’…ï»àÅ°…ïòÙâÌïÕçÖ¡î°…ïÖ±}°…ïò•Ùà¯ÙÅÌïÕçÖ¡î°…ïÖ±}¡…Ωë’ç—lâπÖµîât•ÙΩÑ¯ú(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}Õ±’úÄÙÅ…ïÖ±}¡…Ωë’ç–πùï–†âçÖ—ïùΩ…Â}Õ±’úà∞Äàà§(ÄÄÄÄÄÄÄÅ…ï—’…∏Å}…ïπëï…}¡…Ωë’ç—}—•±î†(ÄÄÄÄÄÄÄÄÄÄÄÅ°…ïòıòúΩ¡…•ŸÖ—îµ±Öâï∞ΩÌïÕçÖ¡î°±Öâï±lâÕ±’úât•Ùºú∞(ÄÄÄÄÄÄÄÄÄÄÄÅπÖµîı±Öâï±lâπÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÅ•µÖùï}’…∞ı}¡…•ŸÖ—ï}±Öâï±}•µÖùî°±Öâï∞§∞(ÄÄÄÄÄÄÄÄÄÄÄÅôÖ±±âÖç≠}•π•—•Ö±ÃıÕ’ââ…ÖπëlË…tπ’¡¡ï»†§∞(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ıçÖ—ïùΩ…•ïÃπùï–°çÖ—ïùΩ…Â}Õ±’ú∞ÅÌÙ§πùï–†â±Öâï∞à§∞(ÄÄÄÄÄÄÄÄÄÄÄÅÕïçΩπëÖ…Â}±•πï}°—µ∞ı…ïÖ±}¡…Ωë’ç—}±•π¨∞(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ïÕ–ı±Ω›ïÕ–∞(ÄÄÄÄÄÄÄÄÄÄÄÅΩ—°ï…}çΩ’π–ı±ï∏°…ïÖ±}¡…Ωë’ç—lâΩôôï…Ãât§Ä¥Äƒ∞(ÄÄÄÄÄÄÄÄÄÄÄÅçΩµ¡Ö…•ÕΩπ}Ωôôï…Ãı…ïçΩπç•±ï}¡…Ωë’ç–°…ïÖ±}¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§∞(ÄÄÄÄÄÄÄÄÄÄÄÅëÖ—Ö}Ö——»ıòúÅëÖ—ÑµçÖ—ïùΩ…‰ÙâÌïÕçÖ¡î°çÖ—ïùΩ…Â}Õ±’ú•Ùàú∞(ÄÄÄÄÄÄÄÄÄÄÄÅ•±±’Õ—…Ö—•Ωπ}°—µ∞ı9ΩπîÅ•òÅ}¡…•ŸÖ—ï}±Öâï±}•µÖùî°±Öâï∞§Åï±ÕîÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}•±±’Õ—…Ö—•Ω∏°ç°Ö•∏∞Å±Öâï±lâÕ±’úât§∞(ÄÄÄÄÄÄÄÄ§((ÄÄÄÅ¡…Ωë’ç—}…Ω›Õ}°—µ∞ÄÙÄâq∏àπ©Ω•∏°…ïπëï…}…Ω‹°»§ÅôΩ»Å»Å•∏Å…Ω›Ã§(ÄÄÄÅÖπÂ}¡±•}•±±’Õ—…Ö—•Ω∏ÄÙÅÖπ‰°πΩ–Å}¡…•ŸÖ—ï}±Öâï±}•µÖùî°…lâ±Öâï∞ât§ÅÖπêÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}•±±’Õ—…Ö—•Ω∏°ç°Ö•∏∞Å…lâ±Öâï∞âulâÕ±’úât§ÅôΩ»Å»Å•∏Å…Ω›Ã§((ÄÄÄÅçÖ—ïùΩ…Â}Õ±’ùÃÄÙÅÕΩ…—ïê°Ì…lâ…ïÖ±}¡…Ωë’ç–âulâçÖ—ïùΩ…Â}Õ±’úâtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÄâçÖ—ïùΩ…Â}Õ±’úàÅ•∏Å…lâ…ïÖ±}¡…Ωë’ç–âuÙ§(ÄÄÄÅçÖ—ïùΩ…Â}ç°•¡ÃÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúÒâ’——Ω∏Åç±ÖÕÃÙâç°•¿àÅëÖ—ÑµçÖ—ïùΩ…‰ÙâÌïÕçÖ¡î°å•Ùà˘ÌïÕçÖ¡î°çÖ—ïùΩ…•ïÕmçulâ±Öâï∞ât•ÙΩâ’——Ω∏¯úÅôΩ»ÅåÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃ(ÄÄÄÄ§((ÄÄÄÄåÅ-©ïëïπÃÅπÖŸ∏Ω±ΩùºÄ°MÂπÕÖ¥Ω	…•±±ï±ÖπêΩM¡ïçÕÖŸï…ÃΩΩ¡—•≠¨§ÅŸ•ÕïÃÅ%--(ÄÄÄÄåÅ±ïπùï»Å°ï»Ä¥¥Åâ…’≠ï»É·πÕ≠ï»Ä†»¿»ÿ¥¿‡¥Ã¿§ÅÖ–Åë•ÕÕîÅÕï…•ïπîÅô…ïµÕ”ï»(ÄÄÄÄåÅÕΩ¥ÅïùπîÅµï…≠ï»Å√îÅëïππîÅÕ•ëï∏∞Å√îÅ±•π©îÅµïêÅï≠—îÅ±•πÕïµï…≠ï»∏Å’±∞(ÄÄÄÄåÅ≠Ωâ±•πúÅ—•∞Å≠©ïëï∏Å±•ùùï»ÅôΩ…—ÕÖ—–Å√îÄΩ¡…•ŸÖ—îµ±Öâï∞º∏Å	…’≠ï»ÅÕï…•ïπÃ(ÄÄÄÄåÅ8Å±ΩùºÄ°AI%YQ}1	1}MU		I9}1==L§Åªï»ÅŸ§Å°Ö»Åï∏Åï≠—îÅô•±âÖÕï…–(ÄÄÄÄåÅï∏∞Åï±±ï…ÃÅ•]ïÖ»ÅÕ•—–Åµ•ë±ï…—•ë•ùîÅ—ï≠Õ–µΩ…ëµï…≠îÄ°â…’≠ï…ïπÃÅïùï∏Åô•∞(ÄÄÄÄåÅÕ•ï»ÅÕï±ÿÄâ•≠≠îÅΩôô•Õ•ï±∞Å•]ïÖ»µ±Ωùºà§ÅôΩ»ÅÖ≠≠’…Ö–Åëï∏ÅÕï…•ï∏∞Åï±±ï…Ã(ÄÄÄÄåÅï∏Å•π•—•Ö∞µâÖëùîÄ°1’µ•ï…î‹Ä¥¥Å•πùï∏Åô•∞Åïπªî§∏(ÄÄÄÅÕ’ââ…Öπë}±ΩùºÄÙÅAI%YQ}1	1}MU		I9}1==Lπùï–°Õ’ââ…Öπê§(ÄÄÄÅ•òÅÕ’ââ…Öπë}±ΩùºË(ÄÄÄÄÄÄÄÅâ…Öπë}±ΩùΩ}ç±ÃÄÙÄâ°ÖÃµ±Ωùºà(ÄÄÄÄÄÄÄÅâ…Öπë}±ΩùΩ}çΩπ—ïπ–ÄÙÅòúÒ•µúÅç±ÖÕÃÙââ…Öπêµ±Ωùºµ•µúàÅÕ…åÙàΩÕ—Ö—•åΩ±ΩùΩÃΩÌÕ’ââ…Öπë}±ΩùΩÙàÅÖ±–ÙààÅ±ΩÖë•πúÙâ±ÖÈ‰à¯ú(ÄÄÄÅï±•òÅÕ’ââ…ÖπêÄÙÙÄâ•]ïÖ»àË(ÄÄÄÄÄÄÄÅâ…Öπë}±ΩùΩ}ç±ÃÄÙÄâ°ÖÃµ±Ωùºà(ÄÄÄÄÄÄÄÅâ…Öπë}±ΩùΩ}çΩπ—ïπ–ÄÙÄ†úÒÕ¡Ö∏ÅÕ—Â±îÙâôΩπ–µôÖµ•±‰Èpù5’±•Õ°pú±ÕÖπÃµÕï…•òÌôΩπ–µ›ï•ù°–Ë‹¿¿Ïú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄùôΩπ–µÕ•ÈîËƒ∏Â…ï¥Ì±ï——ï»µÕ¡Öç•πúË¥∏¿Õï¥ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ïà¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄúÒÕ¡Ö∏ÅÕ—Â±îÙâçΩ±Ω»Ëå¿‹·î‰ƒÏà˘§ΩÕ¡Ö∏˘]ïÖ»ΩÕ¡Ö∏¯ú§(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅâ…Öπë}±ΩùΩ}ç±Ã∞Åâ…Öπë}±ΩùΩ}çΩπ—ïπ–ÄÙÄàà∞ÅïÕçÖ¡î°Õ’ââ…ÖπëlË…tπ’¡¡ï»†§§(ÄÄÄÅâ…Öπë}±ΩùΩ}â±Ωç¨ÄÙÅòúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµ±ΩùºÅÌâ…Öπë}±ΩùΩ}ç±ÕÙà˘Ìâ…Öπë}±ΩùΩ}çΩπ—ïπ—ÙΩë•ÿ¯ú((ÄÄÄÅµï—Ö}ëïÕç…•¡—•Ω∏ÄÙÅòâÌÕ’ââ…ÖπëÙÅï»Åï–Åïùï–Åµï…≠ïπÖŸ∏ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»∏ÅMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅÖ±±îÅÌ±ï∏°…Ω›Ã•ÙÅÌÕ’ââ…ÖπëÙµŸÖ…•Öπ—ï»ÅŸ§Å°Ö»Å•ëïπ—•ô•Õï…–ÉäLÅëîÅï»Å•ëïπ—•Õ≠îÅµïêÅ≠©ïπ—îÅ±•πÕï»Åô…ÑÅÕ—Ω…îÅ¡…Ωë’Õïπ—ï»∞ÅâÖ…îÅ§Åïùï∏Å•ππ¡Ö≠π•πú∏à((ÄÄÄÄåÄ¥¥ÅQÖ±∞Å√îÅ—Ÿï…ÃÅÖÿÅ!1ÅÕï——ï–∞Åâ…’≠–ÅÖÿÅÕ—Ö–µÕ—…•¡ï∏∞Äâ§Å—Ö±∞àÅΩú(ÄÄÄÄåÅDµï∏Ä¥¥ÅÕÖµµîÅ’—…ïùπ•πùÕ∑·πÕ—ï»ÅÕΩ¥Å…ïπëï…}â…Öπë}¡Öùî†§∏Ä¥¥(ÄÄÄÅÖ±±}ï±•ù•â±îÄÙÅmºÅôΩ»Å»Å•∏Å…Ω›ÃÅôΩ»ÅºÅ•∏Å…lâï±•ù•â±îâut(ÄÄÄÅ…ï—Ö•±ï…}çΩ’π–ÄÙÅ±ï∏°ÌΩlâ…ï—Ö•±ï»âtÅôΩ»ÅºÅ•∏ÅÖ±±}ï±•ù•â±ïÙ§(ÄÄÄÅ—Â¡ï}±Öâï±Õ}Ö±∞ÄÙÅÕΩ…—ïê°Ì…lâçÖ—ïùΩ…Â}±Öâï∞âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâçÖ—ïùΩ…Â}±Öâï∞âuÙ§(ÄÄÄÅµÖ—ï…•Ö±Õ}Ö±∞ÄÙÅÕΩ…—ïê°Ì…lâµÖ—ï…•Ö∞âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâµÖ—ï…•Ö∞âuÙ§(ÄÄÄÄåÅ≠—îÅµï…≠ï»µ±•Õ—ï∏Åô•ππïÃÅ%--Å√îÅï–Åï≠—îÅµï…≠îÄ¥¥Åïùï∏∞Åπ‰(ÄÄÄÄåÅ•πôΩ…µÖÕ©Ω∏ÅÕΩ¥ÅâÖ…îÅ¡…•ŸÖ—îÅ±Öâï∞µÕ•ëï∏Å≠Ö∏ÅŸ•ÕîÄ°°Ÿ•±≠îÅ…ïï±±î(ÄÄÄÄåÅ¡…Ωë’Õïπ–µµï…≠ï»ÅÕï——ï–ÅôÖ≠—•Õ¨ÅâïÕ”ï»ÅÖÿ§∏(ÄÄÄÅ…ïÖ±}â…ÖπëÕ}Ö±∞ÄÙÅÕΩ…—ïê°Ì…lâ…ïÖ±}¡…Ωë’ç–âulââ…Öπë}±Öâï∞âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâ…ïÖ±}¡…Ωë’ç–âtπùï–†ââ…Öπë}±Öâï∞à•Ù§(ÄÄÄÅ±Ω›ïÕ—}…Ω‹ÄÙÅµ•∏†°»ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâ±Ω›ïÕ–ât§∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨ât∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÅ¡ï…}±ïπÕ}…Ω›ÃÄÙÅl(ÄÄÄÄÄÄÄÄ°…lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÄºÅ…lâ¡Öç≠}Õ•Èîât∞Å»§ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâ±Ω›ïÕ–âtÅÖπêÅ…lâ¡Öç≠}Õ•Èîât(ÄÄÄÅt(ÄÄÄÅç°ïÖ¡ïÕ—}¡ï…}±ïπÃÄÙÅµ•∏°¡ï…}±ïπÕ}…Ω›Ã∞Å≠ï‰ı±ÖµâëÑÅ–ËÅ—l¡t∞ÅëïôÖ’±–ı9Ωπî§((ÄÄÄÅ—Â¡ï}±Öâï±Õ}±Ω›ï»ÄÙÅm—l¡tπ±Ω›ï»†§Ä¨Å—lƒÈtÅ•òÅ–Åï±ÕîÅ–ÅôΩ»Å–Å•∏Å—Â¡ï}±Öâï±Õ}Ö±±t(ÄÄÄÅ•òÅ±ï∏°—Â¡ï}±Öâï±Õ}±Ω›ï»§ÄÙÄƒË(ÄÄÄÄÄÄÄÅâ…Öπë}—Â¡ï}—·–ÄÙÅ—Â¡ï}±Öâï±Õ}±Ω›ï…l¡tÅ•òÅ—Â¡ï}±Öâï±Õ}±Ω›ï»Åï±ÕîÄàà(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅâ…Öπë}—Â¡ï}—·–ÄÙÄà∞Äàπ©Ω•∏°—Â¡ï}±Öâï±Õ}±Ω›ï…lË¥≈t§Ä¨ÄàÅΩúÄàÄ¨Å—Â¡ï}±Öâï±Õ}±Ω›ï…l¥≈t(ÄÄÄÅâ…Öπë}Õ’â—•—±ï}°—µ∞ÄÙÅòúÒ¿Åç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ’â—•—±îà˘-Ωπ—Ö≠—±•πÕï»Å°ΩÃÅÌïÕçÖ¡î°ç°Ö•∏•ÙΩ¿¯ú(ÄÄÄÅâ…Öπë}•π—…Ω}Õïπ—ïπçîÄÙÄ†(ÄÄÄÄÄÄÄÄ°òùMΩ…—•µïπ—ï–ÅΩµôÖ——ï»ÅÌïÕçÖ¡î°â…Öπë}—Â¡ï}—·–•Ù∏ÄúÅ•òÅâ…Öπë}—Â¡ï}—·–Åï±ÕîÄúú§(ÄÄÄÄÄÄÄÄ¨ÅòùY§Åõ·±ùï»Å¡…•Õï∏Å√îÅÌ±ï∏°…Ω›Ã•ÙÅÏâŸÖ…•Öπ–àÅ•òÅ±ï∏°…Ω›Ã§ÄÙÙÄƒÅï±ÕîÄâŸÖ…•Öπ—ï»âÙ∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ú(ÄÄÄÄ§((ÄÄÄÅÕ—Ω…ï}•çΩ∏ÄÙÄúÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅ·µ±πÃÙâ°——¿ËºΩ››‹π‹ÃπΩ…úº»¿¿¿ΩÕŸúàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îàÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêà¯Ò¡Ö—†ÅêÙâ4–ÄÂ∞ƒ¥’†ƒ—∞ƒÄ‘àº¯Ò¡Ö—†ÅêÙâ4–ÄÂÿƒ¡ÑƒÄƒÄ¿Ä¿Ä¿ÄƒÄ≈†ƒ—ÑƒÄƒÄ¿Ä¿Ä¿Äƒ¥≈X‰àº¯Ò¡Ö—†ÅêÙâ4–ÄÂ†ƒŸ4‰∏‘Ä»¡ÿ¥‘∏’†’X»¿àº¯ΩÕŸú¯ú(ÄÄÄÅÕ—Ö—}¡•±±ÃÄÙÅl†âµ•π–à∞Å	=a}%=9}MY∞ÅÕ—»°±ï∏°…Ω›Ã§§∞Äâ¡…Ωë’≠–àÅ•òÅ±ï∏°…Ω›Ã§ÄÙÙÄƒÅï±ÕîÄâ¡…Ωë’≠—ï»à∞Äàà•t(ÄÄÄÅ•òÅ…ïÖ±}â…ÖπëÕ}Ö±∞Ë(ÄÄÄÄÄÄÄÅÕ—Ö—}¡•±±ÃπÖ¡¡ïπê††ââ±’îà∞ÅQ}%=9}MY∞ÅÕ—»°±ï∏°…ïÖ±}â…ÖπëÕ}Ö±∞§§∞Äâï≠—îÅµï…≠îàÅ•òÅ±ï∏°…ïÖ±}â…ÖπëÕ}Ö±∞§ÄÙÙÄƒÅï±ÕîÄâï≠—îÅµï…≠ï»à∞ÄàÉ
‹Äàπ©Ω•∏°…ïÖ±}â…ÖπëÕ}Ö±∞§§§(ÄÄÄÅ•òÅ—Â¡ï}±Öâï±Õ}Ö±∞Ë(ÄÄÄÄÄÄÄÅÕ—Ö—}¡•±±ÃπÖ¡¡ïπê††â±ÖŸïπëï»à∞ÅI=A1Q}%=9}MY∞ÅÕ—»°±ï∏°—Â¡ï}±Öâï±Õ}Ö±∞§§∞Äâ±•πÕï—Â¡îàÅ•òÅ±ï∏°—Â¡ï}±Öâï±Õ}Ö±∞§ÄÙÙÄƒÅï±ÕîÄâ±•πÕï—Â¡ï»à∞ÄàÉ
‹Äàπ©Ω•∏°—Â¡ï}±Öâï±Õ}Ö±∞§§§(ÄÄÄÅ•òÅ…ï—Ö•±ï…}çΩ’π–Ë(ÄÄÄÄÄÄÄÅÕ—Ö—}¡•±±ÃπÖ¡¡ïπê††âÖµâï»à∞ÅÕ—Ω…ï}•çΩ∏∞ÅÕ—»°…ï—Ö•±ï…}çΩ’π–§∞Äââ’—•≠¨àÅ•òÅ…ï—Ö•±ï…}çΩ’π–ÄÙÙÄƒÅï±ÕîÄââ’—•≠≠ï»à∞Åòù5ïêÅÌÕ’ââ…ÖπëÙµ¡…Ωë’≠—ï»ÅÖ≠≠’…Ö–Åªîú§§(ÄÄÄÅâ…Öπë}°ï…Ω}Õ—Ö—Õ}°—µ∞ÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ—Ö–à¯(ÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ—Ö–µ•çΩ∏àÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µÌçΩ±Ω…Ù§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩÕ¡Ö∏¯(ÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ—Ö–µŸÖ±’îà˘ÌïÕçÖ¡î°π’µâï»•ÙΩÕ¡Ö∏¯(ÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ—Ö–µ±Öâï∞à˘ÌïÕçÖ¡î°’π•–•ÙΩÕ¡Ö∏¯(ÄÄΩë•ÿ¯úúú(ÄÄÄÄÄÄÄÅôΩ»ÅçΩ±Ω»∞Å•çΩ∏∞Åπ’µâï»∞Å’π•–∞ÅÕ’àÅ•∏ÅÕ—Ö—}¡•±±Ã(ÄÄÄÄ§((ÄÄÄÄåÄ¥¥ÄâÌÕ’ââ…ÖπëÙÅ§Å—Ö±∞àÄ¥¥ÅÕÖµµîÅ∑·πÕ—ï»ÅÕΩ¥Å…ïπëï…}â…Öπë}¡Öùî†§∞Åµï∏(ÄÄÄÄåÅ’—ï∏Äâô±ïÕ–ÅŸÖ…•Öπ—ï»àµ—•±îÄ°ëï∏Å≠…ïŸï»Åï∏Å¡…Ωë’ç—}ôÖµ•±•ïÃµÕï…•îÅŸ§(ÄÄÄÄåÅ•≠≠îÅâÂùùï»Å°ï»∞ÅÕîÅëΩçÕ—…•πú§∏Ä¥¥(ÄÄÄÅâ…Öπë}•}—Ö±±}—•±ïÃÄÙÅmt(ÄÄÄÅ•òÅ±Ω›ïÕ—}…Ω‹ÅÖπêÅ±Ω›ïÕ—}…Ω›lâ±Ω›ïÕ–âtË(ÄÄÄÄÄÄÄÅâ…Öπë}•}—Ö±±}—•±ïÃπÖ¡¡ïπê††âµ•π–à∞ÅQI=A!e}%=9}MY∞Å}ôµ—}≠»°±Ω›ïÕ—}…Ω›lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨ât§∞Äâ1ÖŸïÕ—îÅ¡…Ωë’≠—¡…•Ãà∞Å±Ω›ïÕ—}…Ω›lâ±Öâï∞âulâπÖµîât§§(ÄÄÄÅ•òÅç°ïÖ¡ïÕ—}¡ï…}±ïπÃË(ÄÄÄÄÄÄÄÅ¡ï…}±ïπÕ}ŸÖ∞∞Å¡ï…}±ïπÕ}…Ω‹ÄÙÅç°ïÖ¡ïÕ—}¡ï…}±ïπÃ(ÄÄÄÄÄÄÄÅ¡ï…}±ïπÕ}—·–ÄÙÅòùÌ¡ï…}±ïπÕ}ŸÖ∞Ë∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§Ä¨ÄàÅ≠»à(ÄÄÄÄÄÄÄÅâ…Öπë}•}—Ö±±}—•±ïÃπÖ¡¡ïπê††âÖµâï»à∞Å	=a}%=9}MY∞Å¡ï…}±ïπÕ}—·–∞Äâ1ÖŸïÕ—îÅ¡…•ÃÅ¡ï»Å±•πÕîà∞Å¡ï…}±ïπÕ}…Ω›lâ±Öâï∞âulâπÖµîât§§(ÄÄÄÅÕ¡…ïÖë}çÖπë•ëÖ—ïÃÄÙÅmt(ÄÄÄÅôΩ»Å»Å•∏Å…Ω›ÃË(ÄÄÄÄÄÄÄÅ•òÅ±ï∏°…lâï±•ù•â±îât§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ¡…•çïÃÄÙÅmΩlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å…lâï±•ù•â±îâut(ÄÄÄÄÄÄÄÄÄÄÄÅ±º∞Å°§ÄÙÅµ•∏°¡…•çïÃ§∞ÅµÖ‡°¡…•çïÃ§(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ±ºÄ¯Ä¿Ë(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ¡…ïÖë}çÖπë•ëÖ—ïÃπÖ¡¡ïπê†°…Ω’πê†°°§Ä¥Å±º§ÄºÅ±ºÄ®Äƒ¿¿§∞Å»§§(ÄÄÄÅâ•ùùïÕ—}Õ¡…ïÖêÄÙÅµÖ‡°Õ¡…ïÖë}çÖπë•ëÖ—ïÃ∞Å≠ï‰ı±ÖµâëÑÅ–ËÅ—l¡t∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÅ•òÅâ•ùùïÕ—}Õ¡…ïÖêÅÖπêÅâ•ùùïÕ—}Õ¡…ïÖël¡tÄ¯ÙÄ‘Ë(ÄÄÄÄÄÄÄÅâ…Öπë}•}—Ö±±}—•±ïÃπÖ¡¡ïπê††âÕ≠‰à∞ÅQ}%=9}MY∞ÅòùÌâ•ùùïÕ—}Õ¡…ïÖël¡uÙÄîú∞ÄâM”·…Õ–Å¡…•ÕôΩ…Õ≠©ï±∞Åµï±±Ω¥Åâ’—•≠≠ï»à∞Åâ•ùùïÕ—}Õ¡…ïÖël≈ulâ±Öâï∞âulâπÖµîât§§(ÄÄÄÅµΩÕ—}…ï—Ö•±ï…Õ}…Ω‹ÄÙÅµÖ‡°…Ω›Ã∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ±ï∏°…lâï±•ù•â±îât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÅ•òÅµΩÕ—}…ï—Ö•±ï…Õ}…Ω‹ÅÖπêÅ±ï∏°µΩÕ—}…ï—Ö•±ï…Õ}…Ω›lâï±•ù•â±îât§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÅâ…Öπë}•}—Ö±±}—•±ïÃπÖ¡¡ïπê††â±ÖŸïπëï»à∞ÅÕ—Ω…ï}•çΩ∏∞ÅÕ—»°±ï∏°µΩÕ—}…ï—Ö•±ï…Õ}…Ω›lâï±•ù•â±îât§§∞Äâ±ïÕ–Åâ’—•≠≠ï»à∞ÅµΩÕ—}…ï—Ö•±ï…Õ}…Ω›lâ±Öâï∞âulâπÖµîât§§(ÄÄÄÅâ…Öπë}•}—Ö±±}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅâ…Öπë}•}—Ö±±}—•±ïÃË(ÄÄÄÄÄÄÄÅâ…Öπë}•}—Ö±±}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞à¯(ÄÄÄÄÒ†»˘ÌïÕçÖ¡î°Õ’ââ…Öπê•ÙÅ§Å—Ö±∞Ω†»¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙââ…ÖπêµÕïç—•Ω∏µ±ïÖêà˘	ÖÕï…–Å√îÅ¡…Ωë’≠—ïπîÅΩúÅ¡…•ÕïπîÅŸ§Åõ·±ùï»ÅÖ≠≠’…Ö–Åªî∏Ω¿¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞µù…•êà¯(ÄÄÄÄÄÅÏààπ©Ω•∏°òúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞µ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÌçΩ±Ω…Ùµ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÌçΩ±Ω…Ù§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩë•ÿ¯Òë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞µŸÖ±’îà˘ÌïÕçÖ¡î°ŸÖ∞•ÙΩë•ÿ¯Òë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞µ±Öâï∞à˘ÌïÕçÖ¡î°±â∞•ÙΩë•ÿ¯Òë•ÿÅç±ÖÕÃÙââ…Öπêµ§µ—Ö±∞µÕ’àà˘ÌïÕçÖ¡î°Õ’à•ÙΩë•ÿ¯Ωë•ÿ¯úÅôΩ»ÅçΩ±Ω»∞Å•çΩ∏∞ÅŸÖ∞∞Å±â∞∞ÅÕ’àÅ•∏Åâ…Öπë}•}—Ö±±}—•±ïÃ•Ù(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥ÅA…•Õ•ππÕ•≠–ÅôΩ»Å!1ÅÕï——ï–Ä°Õπ•—–Å¡ï»Å¡Ö≠π•πùÕÕ”·……ï±Õî∞ÅCÅQYIL(ÄÄÄÄåÅÖÿÅÖ±±îÅŸÖ…•Öπ—ïπî§Ä¥¥Åù©ïπâ…’≠ï»Å-M-PÅÕÖµµîÅô’π≠Õ©Ωπï»ÅÕΩ¥(ÄÄÄÄåÅÕï…•î¥Ωµï…≠îµÕ•ëï∏∞ÅÕîÅ}ôÖµ•±Â}¡…•çï}•πÕ•ù°—}ëÖ—Ñ†§∏Å!•Õ—Ω…•≠≠ï∏Åï»(ÄÄÄÄåÅ±Öù…ï–Å√îÅ…ïÖ±}¡…Ωë’ç—lâ•êâtÄ°ÕÖµµîÅôÂÕ•Õ≠îÅŸÖ…î§∞ÅÕîÅ…Ω›ÃµâÂùùï–ÅΩŸï»∏Ä¥¥(ÄÄÄÅâ…Öπë}¡…•çï}•πÕ•ù°—}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ¡…•çï}°•Õ—Ω…‰Ë(ÄÄÄÄÄÄÄÅâ…Öπë}•πÕ•ù°—}âÂ}¡Öç¨ÄÙÅ}ôÖµ•±Â}¡…•çï}•πÕ•ù°—}ëÖ—Ñ°…Ω›Ã∞Å¡…•çï}°•Õ—Ω…‰§(ÄÄÄÄÄÄÄÅâ…Öπë}¡…•çï}•πÕ•ù°—}°—µ∞ÄÙÅ…ïπëï…}ôÖµ•±Â}¡…•çï}•πÕ•ù°–°Õ’ââ…Öπê∞Åâ…Öπë}•πÕ•ù°—}âÂ}¡Öç¨∞ÅÕçΩ¡ï}±Öâï∞ıòâ§ÅÌÕ’ââ…ÖπëÙµÕΩ…—•µïπ—ï–à∞Å°ïÖë•πúıòâÌÕ’ââ…ÖπëÙµ¡…•Õï»à§((ÄÄÄÅâ…Öπë}•πÕ•ù°—}…Ω›}°—µ∞ÄÙÄ†(ÄÄÄÄÄÄÄÅòúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ•πÕ•ù°–µ…Ω‹à˘Ìâ…Öπë}•}—Ö±±}°—µ±ıÌâ…Öπë}¡…•çï}•πÕ•ù°—}°—µ±ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÅ•òÅâ…Öπë}•}—Ö±±}°—µ∞ÅÖπêÅâ…Öπë}¡…•çï}•πÕ•ù°—}°—µ∞Åï±ÕîÅâ…Öπë}•}—Ö±±}°—µ∞Ä¨Åâ…Öπë}¡…•çï}•πÕ•ù°—}°—µ∞(ÄÄÄÄ§((ÄÄÄÄåÄ¥¥Äâ5Ö—ï…•Ö±ï»àÄ¥¥ÅëîÅëΩ≠’µïπ—ï…—îÅµÖ—ï…•Ö±ïπîÅ—•∞ÅëîÅ-QÅ¡…Ωë’≠—ïπî(ÄÄÄÄåÅÕï——ï–Å—•±ÕŸÖ…ï»∏Å%πùï∏Äââ…’≠ïÃÅ§ÅÕï…•îÅ`àµ’πëï…—ï≠Õ–Ä°•πùï∏(ÄÄÄÄåÅôÖµ•±•îµù…’¡¡ï…•πúÅ°ï»∞ÅÕîÅëΩçÕ—…•πú§Ä¥¥Å…ïπî∞Å•πôΩ…µÖ—•ŸîÅ≠Ω…–∏Ä¥¥(ÄÄÄÅµÖ—ï…•Ö±}çΩ±Ω…ÃÄÙÅlâÕ≠‰à∞Äâµ•π–à∞Äâ±ÖŸïπëï»à∞ÄâÖµâï»à∞ÄâçΩ…Ö∞ât((ÄÄÄÅëïòÅâ…Öπë}µÖ—ï…•Ö±}çÖ…ê°¥ËÅÕ—»∞Å§ËÅ•π–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅçΩ±Ω»ÄÙÅµÖ—ï…•Ö±}çΩ±Ω…Õm§ÄîÅ±ï∏°µÖ—ï…•Ö±}çΩ±Ω…Ã•t(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúúúÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖ—ï…•Ö∞µçÖ…êà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖ—ï…•Ö∞µçÖ…êµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÌçΩ±Ω…Ùµ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÌçΩ±Ω…Ù§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘ÌI=A1Q}%=9}MYÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖ—ï…•Ö∞µçÖ…êµâΩë‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖ—ï…•Ö∞µçÖ…êµπÖµîà˘ÌïÕçÖ¡î°¥•ÙΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÅâ…Öπë}µÖ—ï…•Ö±Õ}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ±ï∏°µÖ—ï…•Ö±Õ}Ö±∞§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÅâ…Öπë}µÖ—ï…•Ö±Õ}°—µ∞ÄÙÅòúúúÒë•ÿ¯Ò†»˘5Ö—ï…•Ö±ï»Å§ÅÌïÕçÖ¡î°Õ’ââ…Öπê•ÙµÕΩ…—•µïπ—ï–Ω†»¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ÖπêµÕïç—•Ω∏µ±ïÖêà˘îÅëΩ≠’µïπ—ï…—îÅµÖ—ï…•Ö±ïπîÅëîÅï≠—îÅ±•πÕïπîÅÌïÕçÖ¡î°Õ’ââ…Öπê•ÙÅ—•±ÕŸÖ…ï»Åï»Å±Öùï–ÅÖÿ∏Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµµÖ—ï…•Ö±Ãµù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°â…Öπë}µÖ—ï…•Ö±}çÖ…ê°¥∞Å§§ÅôΩ»Å§∞Å¥Å•∏Åïπ’µï…Ö—î°µÖ—ï…•Ö±Õ}Ö±∞§•Ù(ÄÄΩë•ÿ¯Ωë•ÿ¯úúú((ÄÄÄÄåÄ¥¥ÄàÃ¿Åï±±ï»Ä‰¿Å±•πÕï»¸àÄ¥¥ÅÕÖµµîÅ…Ωâ’Õ—°ï–µ—ï…Õ≠ï∞Ä°µ•πÕ–Ä»Å¡Ö»§ÅÕΩ¥(ÄÄÄÄåÅ…ïπëï…}â…Öπë}¡Öùî†§∞ÅµÖ—ç°ï–ÅŸ•ÑÅ…ïÖ±}¡…Ωë’ç—lâ•êâtÄ°¡…Ωë’ç—lâ•êât(ÄÄÄÄåÅ§Å…Ω›ÃµâÂùùï–ÅΩŸï»Åï»ÅâïŸ•ÕÕ–Å…ïÖ±}¡…Ωë’ç–ÅÕ•∏∞ÅÕîÅëï»§∏Ä¥¥(ÄÄÄÅ¡Öç≠}¡Ö•…ÃÄÙÅmt(ÄÄÄÅâÂ}Õ—ï¥ËÅë•ç—mÕ—»∞Åë•ç—m•π–∞Åë•ç—utÄÙÅÌÙ(ÄÄÄÅôΩ»Å»Å•∏Å…Ω›ÃË(ÄÄÄÄÄÄÄÅ¡Ö…ÕïêÄÙÅ}¡Öç≠}Õ•Èï}ô…Ωµ}•ê°…lâ¡…Ωë’ç–âulâ•êât§(ÄÄÄÄÄÄÄÅ•òÅ¡Ö…ÕïêÅÖπêÅ…lâ±Ω›ïÕ–âtË(ÄÄÄÄÄÄÄÄÄÄÄÅÕ—ï¥∞Å¡Öç¨ÄÙÅ¡Ö…Õïê(ÄÄÄÄÄÄÄÄÄÄÄÅâÂ}Õ—ï¥πÕï—ëïôÖ’±–°Õ—ï¥∞ÅÌÙ•m¡Öç≠tÄÙÅ»(ÄÄÄÅôΩ»ÅÕ—ï¥∞ÅâÂ}¡Öç¨Å•∏ÅâÂ}Õ—ï¥π•—ïµÃ†§Ë(ÄÄÄÄÄÄÄÅ•òÄÃ¿Å•∏ÅâÂ}¡Öç¨ÅÖπêÄ‰¿Å•∏ÅâÂ}¡Öç¨Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ»Ã¿∞Å»‰¿ÄÙÅâÂ}¡Öç≠lÃ¡t∞ÅâÂ}¡Öç≠l‰¡t(ÄÄÄÄÄÄÄÄÄÄÄÅ¿Ã¿ÄÙÅ»Ã¡lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÄºÄÃ¿(ÄÄÄÄÄÄÄÄÄÄÄÅ¿‰¿ÄÙÅ»‰¡lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨âtÄºÄ‰¿(ÄÄÄÄÄÄÄÄÄÄÄÅ¡Öç≠}¡Ö•…ÃπÖ¡¡ïπê°ÏâπÖµîàËÅ»Ã¡lâ±Öâï∞âulâπÖµîât∞Äâ¿Ã¿àËÅ¿Ã¿∞Äâ¿‰¿àËÅ¿‰¡Ù§(ÄÄÄÅ¡Öç≠|Ã¡|‰¡}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ±ï∏°¡Öç≠}¡Ö•…Ã§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÅπ|‰¡}ç°ïÖ¡ï»ÄÙÅÕ’¥†ƒÅôΩ»Å¡¿Å•∏Å¡Öç≠}¡Ö•…ÃÅ•òÅ¡¡lâ¿‰¿âtÄÅ¡¡lâ¿Ã¿ât§(ÄÄÄÄÄÄÄÅâïÕ—}ï·Öµ¡±îÄÙÅµÖ‡°¡Öç≠}¡Ö•…Ã∞Å≠ï‰ı±ÖµâëÑÅ¡¿ËÅÖâÃ°¡¡lâ¿Ã¿âtÄ¥Å¡¡lâ¿‰¿ât§§(ÄÄÄÄÄÄÄÅ¿Ã¡}—·–ÄÙÅòùÌâïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtË∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅ¿‰¡}—·–ÄÙÅòùÌâïÕ—}ï·Öµ¡±ïlâ¿‰¿âtË∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅë•ôô}¡ç–ÄÙÅ…Ω’πê°ÖâÃ°âïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtÄ¥ÅâïÕ—}ï·Öµ¡±ïlâ¿‰¿ât§ÄºÅâïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtÄ®Äƒ¿¿§(ÄÄÄÄÄÄÄÅç°ïÖ¡ï…}›Ω…êÄÙÄà‰¿µ¡Ö≠π•πùï∏àÅ•òÅâïÕ—}ï·Öµ¡±ïlâ¿‰¿âtÄÅâïÕ—}ï·Öµ¡±ïlâ¿Ã¿âtÅï±ÕîÄàÃ¿µ¡Ö≠π•πùï∏à(ÄÄÄÄÄÄÄÅ¡Öç≠|Ã¡|‰¡}°—µ∞ÄÙÅòúúúÒ†»¯Ã¿Åï±±ï»Ä‰¿Å±•πÕï»¸Ω†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µçÖ…êà¯(ÄÄÄÄÒ¿˘Ω»ÅÌπ|‰¡}ç°ïÖ¡ï…ÙÅÖÿÅÌ±ï∏°¡Öç≠}¡Ö•…Ã•ÙÅÕÖµµïπ±•ùπâÖ…îÅÌïÕçÖ¡î°Õ’ââ…Öπê•Ùµ¡…Ωë’≠—ï»Å°Ö»Ä‰¿µ¡Ö≠π•πùï∏Å±ÖŸï…îÅ¡…•ÃÅ¡ï»Å±•πÕîÅïπ∏Å—•±ÕŸÖ…ïπëîÄÃ¿µ¡Ö≠π•πúÅÖ≠≠’…Ö–Åªî∏Å≠Õïµ¡ï∞Ä¥¥ÅÌïÕçÖ¡î°âïÕ—}ï·Öµ¡±ïlâπÖµîât•ÙËΩ¿¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µù…•êà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÕ≠‰µ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÕ≠‰§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì	=a}%=9}MYÙΩë•ÿ¯ÒÕ—…Ωπú˘Ì¿Ã¡}—·—ÙÅ≠»ΩÕ—…Ωπú¯ÒÕ¡Ö∏¯Ã¿µ¡Öç¨∞Å¡ï»Å±•πÕîΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µµ•π–µ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µµ•π–§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì	=a}%=9}MYÙΩë•ÿ¯ÒÕ—…Ωπú˘Ì¿‰¡}—·—ÙÅ≠»ΩÕ—…Ωπú¯ÒÕ¡Ö∏¯‰¿µ¡Öç¨∞Å¡ï»Å±•πÕîΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îà¯Òë•ÿÅç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µ—•±îµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÖµâï»µ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÖµâï»§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘ÌQ}%=9}MYÙΩë•ÿ¯ÒÕ—…Ωπú˘Ìë•ôô}¡ç—ÙÄîΩÕ—…Ωπú¯ÒÕ¡Ö∏˘Ω…Õ≠©ï±∞Ä¥¥ÅÌïÕçÖ¡î°ç°ïÖ¡ï…}›Ω…ê•ÙÅâ•±±•ùÕ–ΩÕ¡Ö∏¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙââ…Öπê¥Ã¿‰¿µπΩ—îà˘-’∏ÅÕÖµµîÅ’πëï…±•ùùïπëîÅ¡…Ωë’≠–ÅÕÖµµïπ±•ùπï–Ä°Ö±ë…§Å’±•≠îÅ¡…Ωë’≠—ï»ÅµΩ–Å°Ÿï…Öπë…î§∏Å!’Õ¨ÉîÅ…ïùπîÅµïêÅô…Ö≠–ÅôΩ»ÅÖ≠≠’…Ö–Åëï–ÅÖπ—Ö±±ï–Åë‘Å—…ïπùï»∏Ω¿¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥ÄâÌÕ’ââ…ÖπëÙµÕΩ…—•µïπ—ï–ÅôΩ…≠±Ö…–àÄ¥¥É•∏Å≠Ω…—ΩŸï…Õ•≠–Å¡ï»Å-Q=I$∞(ÄÄÄÄåÅÕÖµµîÅ∑·πÕ—ï»ÅÕΩ¥Å…ïπëï…}â…Öπë}¡Öùî†§∞Åµï∏Å’—ï∏ÄâÕï…•ïÕ}πÖµïÃà(ÄÄÄÄåÄ°•πùï∏ÅôÖµ•±•îµù…’¡¡ï…•πúÅ°ï»§∏Ä¥¥(ÄÄÄÅÕΩ…—•µïπ—}çÖ…ëÃÄÙÅmt(ÄÄÄÅôΩ»ÅçÖ—}Õ±’úÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅçÖ—}…Ω›ÃÄÙÅm»ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâ¡…Ωë’ç–âulâçÖ—ïùΩ…Â}Õ±’úâtÄÙÙÅçÖ—}Õ±’ùt(ÄÄÄÄÄÄÄÅ•òÅπΩ–ÅçÖ—}…Ω›ÃË(ÄÄÄÄÄÄÄÄÄÄÄÅçΩπ—•π’î(ÄÄÄÄÄÄÄÅÕΩ…—•µïπ—}çÖ…ëÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ±Öâï∞àËÅçÖ—ïùΩ…•ïÃπùï–°çÖ—}Õ±’ú∞ÅÌÙ§πùï–†â±Öâï∞à∞ÅçÖ—}Õ±’ú§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕ±’úàËÅçÖ—}Õ±’ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâçΩ’π–àËÅ±ï∏°çÖ—}…Ω›Ã§∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅÕΩ…—•µïπ—}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ±ï∏°ÕΩ…—•µïπ—}çÖ…ëÃ§Ä¯ÄƒË(ÄÄÄÄÄÄÄÅïÂï}•çΩ∏ÄÙÄúÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅ·µ±πÃÙâ°——¿ËºΩ››‹π‹ÃπΩ…úº»¿¿¿ΩÕŸúàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îàÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêà¯Ò¡Ö—†ÅêÙâ4»Äƒ…Ã–¥‹Äƒ¿¥‹Äƒ¿Ä‹Äƒ¿Ä‹¥–Ä‹¥ƒ¿Ä‹¥ƒ¿¥‹¥ƒ¿¥›Ëàº¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»ÙàÃàÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îÙâπΩπîàº¯ΩÕŸú¯ú(ÄÄÄÄÄÄÄÅ¡ï…ÕΩπ}•çΩ∏ÄÙÄúÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅ·µ±πÃÙâ°——¿ËºΩ››‹π‹ÃπΩ…úº»¿¿¿ΩÕŸúàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùà‡àÅ»ÙàÃ∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àº¯Ò¡Ö—†ÅêÙâ4‘Ä»¡å¿¥–ÄÃ¥ÿ∏‘Ä‹¥ÿ∏’Ã‹Ä»∏‘Ä‹Äÿ∏‘àÅô•±∞Ùâç’……ïπ—Ω±Ω»àÅΩ¡Öç•—‰Ùà¿∏‘àº¯ΩÕŸú¯ú(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}•çΩπ}µÖ¿ÄÙÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâëÖùÕ±•πÕï»àËÄ†âÖµâï»à∞ÅMU9}%=9}MY§∞ÄâµÖπïëÕ±•πÕï»àËÄ†âÕ≠‰à∞Å19I}%=9}MY§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ—Ω…•Õ≠îµ±•πÕï»àËÄ†âçΩ…Ö∞à∞ÅïÂï}•çΩ∏§∞Äâµ’±—•ôΩ≠Ö±îµ±•πÕï»àËÄ†â±ÖŸïπëï»à∞Å¡ï…ÕΩπ}•çΩ∏§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâôÖ…ùïëîµ±•πÕï»àËÄ†âµ•π–à∞ÅI=A1Q}%=9}MY§∞(ÄÄÄÄÄÄÄÅÙ((ÄÄÄÄÄÄÄÅëïòÅÕΩ…—•µïπ—}çÖ…ê°åËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçΩ±Ω»∞Å•çΩ∏ÄÙÅçÖ—ïùΩ…Â}•çΩπ}µÖ¿πùï–°çlâÕ±’úât∞Ä†ââ±’îà∞ÅQ}%=9}MY§§(ÄÄÄÄÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúúúÒÑÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êàÅ°…ïòÙàçÌïÕçÖ¡î°çlâÕ±’úât•ÙàÅëÖ—ÑµçÖ—ïùΩ…‰ÙâÌïÕçÖ¡î°çlâÕ±’úât•Ùà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµ•çΩ∏àÅÕ—Â±îÙââÖç≠ù…Ω’πêÈŸÖ»†¥µÌçΩ±Ω…Ùµ—•π–§ÌçΩ±Ω»ÈŸÖ»†¥µÌçΩ±Ω…Ù§ÏàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµ±Öâï∞à˘ÌïÕçÖ¡î°çlâ±Öâï∞ât•ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµçΩ’π–à˘ÌçlâçΩ’π–âuÙÅÏâ¡…Ωë’≠–àÅ•òÅçlâçΩ’π–âtÄÙÙÄƒÅï±ÕîÄâ¡…Ωë’≠—ï»âÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µçÖ…êµ±•π¨à˘MîÅÌïÕçÖ¡î°çlâ±Öâï∞âtπ±Ω›ï»†§•ÙÉäHΩë•ÿ¯(ÄÄΩÑ¯úúú(ÄÄÄÄÄÄÄÅÕΩ…—•µïπ—}°—µ∞ÄÙÅòúúúÒ†»˘ÌïÕçÖ¡î°Õ’ââ…Öπê•ÙµÕΩ…—•µïπ—ï–ÅôΩ…≠±Ö…–Ω†»¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ÖπêµÕïç—•Ω∏µ±ïÖêà˘Ì±ï∏°ÕΩ…—•µïπ—}çÖ…ëÃ•ÙÅ≠Ö—ïùΩ…•ï»ÅµïêÅ—•∞ÅÕÖµµï∏ÅÌ±ï∏°…Ω›Ã•ÙÅ¡…Ωë’≠—ï»Ä¥¥ÅŸï±úÅëï∏ÅÕΩ¥Å¡ÖÕÕï»Åë•—–Åâï°Ωÿ∏Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµÕΩ…—•µïπ–µù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°ÕΩ…—•µïπ—}çÖ…ê°å§ÅôΩ»ÅåÅ•∏ÅÕΩ…—•µïπ—}çÖ…ëÃ•Ù(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥ÅDµ…ïùï±µΩ—Ω»Ä°ÕÖµµîÅ≠Ωµ¡Ωπïπ–ÅÕΩ¥ÅÕï…•î¥Ωµï…≠îµÕ•ëï∏∞ÅÕî(ÄÄÄÄåÅ}…ïπëï…}ôÖµ•±Â}ôÖ≈}ÖççΩ…ë•Ω∏†§§∏Ä¥¥(ÄÄÄÅôÖ≈}¡…Ωë’≠–ËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅ•òÅ…ïÖ±}â…ÖπëÕ}Ö±∞Ë(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ÿ•±≠îÅï≠—îÅµï…≠ï»Åï»ÅÌÕ’ââ…ÖπëÙÅïùïπ—±•ú¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùÌÕ’ââ…ÖπëÙµ¡…Ωë’≠—ïπîÅŸ§Åõ·±ùï»Å—•±ÕŸÖ…ï»Åë•ÕÕîÅï≠—îÅµï…≠ïπîËÅÏà∞Äàπ©Ω•∏°…ïÖ±}â…ÖπëÕ}Ö±∞•Ù∏ÅMîÅ¡…Ωë’≠—≠Ω…—ïπîÅ’πëï»ÅôΩ»Å°Ÿ•±≠ï–Åï≠—îÅ¡…Ωë’≠–Å°Ÿï»Åïπ≠ï±–ÅÌÕ’ââ…ÖπëÙµŸÖ…•Öπ–Åï»Å•ëïπ—•Õ¨Åµïê∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÄâ—Ω…•Õ≠îµ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù•ππïÃÅÌÕ’ââ…ÖπëÙÅôΩ»ÅÖÕ—•ùµÖ—•Õµî¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞ÅÌÕ’ââ…ÖπëÙÅ°Ö»ÅŸÖ…•Öπ—ï»ÅôΩ»ÅÖÕ—•ùµÖ—•Õµî∏ÅMîÅ¡…Ωë’≠—ïπîÅ’πëï»ÅôΩ»Å°Ÿ•±≠î∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÄâµ’±—•ôΩ≠Ö±îµ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù•ππïÃÅÌÕ’ââ…ÖπëÙÅÕΩ¥Åµ’±—•ôΩ≠Ö±îÅ±•πÕï»¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞ÅÌÕ’ââ…ÖπëÙÅ°Ö»Åµ’±—•ôΩ≠Ö±îÅŸÖ…•Öπ—ï»ÅôΩ»ÅÖ±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§∏ÅMîÅ¡…Ωë’≠—ïπîÅ’πëï»ÅôΩ»Å°Ÿ•±≠î∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÄâëÖùÕ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃÅÖπêÄâµÖπïëÕ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ö»ÅÌÕ’ââ…ÖπëÙÅãïëîÅëÖùÕ±•πÕï»ÅΩúÅ∑ïπïëÕ±•πÕï»¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞ÅÌÕ’ââ…ÖπëÙµÕΩ…—•µïπ—ï–Å€ï…–Åëï≠≠ï»ÅãïëîÅëÖùÕ±•πÕï»Ä°≠ÖÕ—ïÃÅ°Ÿï»ÅëÖú§ÅΩúÅ∑ïπïëÕ±•πÕï»Ä°ù©ïπâ…’≠ïÃÅµïêÅ…ïπù´·…•πú§∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅôÖ≈}Õ¡ïåËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅ•òÅµÖ—ï…•Ö±Õ}Ö±∞Ë(ÄÄÄÄÄÄÄÅôÖ≈}Õ¡ïåπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ÿ•±≠îÅµÖ—ï…•Ö±ï»Åâ…’≠ïÃÅ§Å±•πÕïπîÅÌÕ’ââ…ÖπëÙÅ—•±ÕŸÖ…ï»¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùîÅï≠—îÅ±•πÕïπîÅÌÕ’ââ…ÖπëÙµ¡…Ωë’≠—ïπîÅŸ§Åõ·±ùï»Å—•±ÕŸÖ…ï»∞Åï»Å±Öùï–ÅÖÿÅÏà∞Äàπ©Ω•∏°µÖ—ï…•Ö±Õ}Ö±∞•Ù∏Å5Ö—ï…•Ö±ï–ÅŸÖ…•ï…ï»Åµï±±Ω¥ÅŸÖ…•Öπ—ïπî∏úÅ•òÅ±ï∏°µÖ—ï…•Ö±Õ}Ö±∞§Ä¯Äƒ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅï±ÕîÅòùîÅï≠—îÅ±•πÕïπîÅÌÕ’ââ…ÖπëÙµ¡…Ωë’≠—ïπîÅŸ§Åõ·±ùï»Å—•±ÕŸÖ…ï»∞Åï»Å±Öùï–ÅÖÿÅÌµÖ—ï…•Ö±Õ}Ö±±l¡uÙ∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅôÖ≈}¡…•ÃËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅ•òÅ±Ω›ïÕ—}…Ω‹ÅÖπêÅ±Ω›ïÕ—}…Ω›lâ±Ω›ïÕ–âtË(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ŸÑÅï»Åâ•±±•ùÕ–Å§ÅÌÕ’ââ…ÖπëÙµÕΩ…—•µïπ—ï–¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùÌ±Ω›ïÕ—}…Ω›lâ±Öâï∞âulâπÖµîâuÙÅï»Åâ•±±•ùÕ–ÅÖ≠≠’…Ö–Åªî∞Åô…ÑÅÌ}ôµ—}≠»°±Ω›ïÕ—}…Ω›lâ±Ω›ïÕ–âulâ¡…•çï}πΩ¨ât•ÙÅ°ΩÃÅÌ±Ω›ïÕ—}…Ω›lâ±Ω›ïÕ–âulâ…ï—Ö•±ï»âuÙÄ°’—ï∏Åô…Ö≠–§∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÅç°ïÖ¡ïÕ—}¡ï…}±ïπÃË(ÄÄÄÄÄÄÄÅ¡ï…}±ïπÕ}ŸÖ∞∞Å¡ï…}±ïπÕ}…Ω‹ÄÙÅç°ïÖ¡ïÕ—}¡ï…}±ïπÃ(ÄÄÄÄÄÄÄÅ¡ï…}±ïπÕ}—·–ÄÙÅòùÌ¡ï…}±ïπÕ}ŸÖ∞Ë∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ÿ•±≠ï∏ÅÌÕ’ââ…ÖπëÙµ¡Ö≠π•πúÅ°Ö»Å±ÖŸïÕ–Å¡…•ÃÅ¡ï»Å±•πÕîÅÖ≠≠’…Ö–Åªî¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùÌ¡ï…}±ïπÕ}…Ω›lâ±Öâï∞âulâπÖµîâuÙÅ°Ö»Å±ÖŸïÕ–Å¡…•ÃÅ¡ï»Å±•πÕîÅÖ≠≠’…Ö–Åªî∞ÅçÑ∏ÅÌ¡ï…}±ïπÕ}—·—ÙÅ≠»Å¡ï»Å±•πÕîÄ°’—ï∏Åô…Ö≠–§∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÅ…ï—Ö•±ï…}çΩ’π–Ë(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ΩÃÅ°ŸΩ»ÅµÖπùîÅâ’—•≠≠ï»Å≠Ö∏Å©ïúÅÕÖµµïπ±•ùπîÅÌÕ’ââ…ÖπëÙ¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùY§ÅÕÖµµïπ±•ùπï»ÅÌÕ’ââ…ÖπëÙÅ°ΩÃÅÌ…ï—Ö•±ï…}çΩ’π—ÙÅπΩ…Õ≠îÅπï——â’—•≠≠ï»Å—•∞ÅÕÖµµï∏∞Å√îÅ—Ÿï…ÃÅÖÿÅÖ±±îÅÌ±ï∏°…Ω›Ã•ÙÅŸÖ…•Öπ—ïπîÅŸ§Åõ·±ùï»∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅâ…Öπë}ôÖ≈}°—µ∞∞Åâ…Öπë}ôÖ≈}Õç°ïµÑÄÙÅ}…ïπëï…}ôÖµ•±Â}ôÖ≈}ÖççΩ…ë•Ω∏†(ÄÄÄÄÄÄÄÅl†â5ï…≠îÅΩúÅŸÖ…•Öπ—ï»à∞ÅôÖ≈}¡…Ωë’≠–§∞Ä†âM¡ïÕ•ô•≠ÖÕ©Ωπï»à∞ÅôÖ≈}Õ¡ïå§∞Ä†âA…•ÃÅΩúÅâ’—•≠≠ï»à∞ÅôÖ≈}¡…•Ã•t∞(ÄÄÄÄÄÄÄÅòù=ô—îÅÕ—•±—îÅÕ√·…Õ∑ï∞ÅΩ¥ÅÌÕ’ââ…ÖπëÙú∞(ÄÄÄÄ§((ÄÄÄÄåÄ¥¥Äâ9Â——•ùîÅ…ïÕÕ’…Õï»àÄ¥¥ÅÕÖµµîÅù©ïπâ…’¨ÅÖÿÅ…ïπëï…}ù’•ëï}—•±î†§ÅÕΩ¥(ÄÄÄÄåÅ…ïπëï…}â…Öπë}¡Öùî†§∏Ä¥¥(ÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃÄÙÅlâ°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»ât(ÄÄÄÅ•òÄâëÖùÕ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃÅÖπêÄâµÖπïëÕ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†âµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»à§(ÄÄÄÅï±•òÄâ—Ω…•Õ≠îµ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†â≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•Õµîà§(ÄÄÄÅï±•òÄâµ’±—•ôΩ≠Ö±îµ±•πÕï»àÅ•∏ÅçÖ—ïùΩ…Â}Õ±’ùÃË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†âµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»à§(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†â°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»à§(ÄÄÄÅâ…Öπë}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†ââåµôΩ…≠±Ö…–à§(ÄÄÄÅâ…Öπë}ù’•ëïÕ}°—µ∞ÄÙÅòúúúÒ†»˘9Â——•ùîÅ…ïÕÕ’…Õï»Ω†»¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ÖπêµÕïç—•Ω∏µ±ïÖêà˘…—•≠±ï»∞ÅôΩ…≠±Ö…•πùï»ÅΩúÅù’•ëï»ÅÕΩ¥Å°©ï±¡ï»ÅëïúÉîÅ—ÑÅùΩëîÅŸÖ±ú∏Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°…ïπëï…}ù’•ëï}—•±î°ùÕ±’ú∞ÅU%}=9Q9QmùÕ±’ùt§ÅôΩ»ÅùÕ±’úÅ•∏Åâ…Öπë}ù’•ëï}Õ±’ùÃÅ•òÅùÕ±’úÅ•∏ÅU%}=9Q9P•Ù(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥Äâ=¥Å•πôΩ…µÖÕ©Ωπï∏Å√îÅëïππîÅÕ•ëï∏àÄ¥¥Å•ëïπ—•Õ¨Å—ï≠Õ–Ω±ïπ≠ï»ÅÕΩ¥(ÄÄÄÄåÅ…ïπëï…}â…Öπë}¡Öùî†§ÅÕ•∏Å—…’Õ–µôΩΩ—ï»∞Å•πùï∏ÅπÂîÅ√ïÕ—Öπëï»∏Ä¥¥(ÄÄÄÅâ…Öπë}—…’Õ—}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–à¯(ÄÄÄÄÒ†»˘=¥Å•πôΩ…µÖÕ©Ωπï∏Å√îÅëïππîÅÕ•ëï∏Ω†»¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µù…•êà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘A…Ωë’≠—•πôΩ…µÖÕ©Ω∏ΩÕ—…Ωπú¯Ò¿˘	ÖÕï…–Å√îÅëΩ≠’µïπ—ï…—îÅ¡…Ωë’Õïπ—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»ÅΩúÅ€ï»Å¡…Ωë’≠—ëÖ—ÖâÖÕî∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘A…•Õï»ΩÕ—…Ωπú¯Ò¿˘!ïπ—ïÃÅô…ÑÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÅΩúÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘-Ωµµï…Õ•ï±±îÅ±ïπ≠ï»ΩÕ—…Ωπú¯Ò¿˘Y§Å≠Ö∏ÅµΩ——ÑÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Åüï»ÅŸ•ëï…îÅ—•∞Åï∏Åâ’—•≠¨∏Åï——îÅ√ïŸ•…≠ï»ÅÖ±ë…§Å¡…•Õ…ï≠≠ïõ·±ùï∏∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ—…’Õ–µ•—ï¥à¯ÒÕ—…Ωπú˘MÖµµïπ±•ùπ•πúΩÕ—…Ωπú¯Ò¿˘A…•ÃÅ¡ï»Å±•πÕîÅâï…ïùπïÃÅô…ÑÅ¡Ö≠π•πùÕÕ”·……ï±Õî∏ÅQΩ—Ö±¡…•ÃÅ•π≠±’ëï…ï»Åô…Ö≠–Åëï»Åô…Ö≠—ëÖ—ÑÅï»Å—•±ù©ïπùï±•ú∏Ω¿¯Ωë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒ¿Åç±ÖÕÃÙââ…Öπêµ—…’Õ–µ±•π≠Ãà¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩÕ±•¨µÕÖµµïπ±•ùπï»µŸ§µ¡…•Õï»ºà˘M±•¨ÅÕÖµµïπ±•ùπï»ÅŸ§Å¡…•Õï»ÉäHΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩÕ±•¨µµÖ—ç°ï»µŸ§µ¡…Ωë’≠—ï»ºà˘M±•¨ÅµÖ—ç°ï»ÅŸ§Å¡…Ωë’≠—ï»ÉäHΩÑ¯(ÄÄÄÄÄÄÒÑÅ°…ïòÙàΩΩ¥µΩÕÃºà˘=¥Å-Ωπ—Ö≠—±•πÕï»ππºÉäHΩÑ¯(ÄÄÄÄΩ¿¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÅÕç°ïµÖ}•—ïµÃÄÙÄà±q∏ÄÄÄÄÄÄàπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúùÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÅÌ§¨≈Ù∞Äâ’…∞àËÄâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ΩÌ…lâ±Öâï∞âulâÕ±’úâuÙºà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°…lâ±Öâï∞âulâπÖµîât•ÙâıÙúúú(ÄÄÄÄÄÄÄÅôΩ»Å§∞Å»Å•∏Åïπ’µï…Ö—î°…Ω›Ã§(ÄÄÄÄ§(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌïÕçÖ¡î°Õ’ââ…Öπê•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩµï…≠îΩÌÕ±’ùÙºâıÙ(ÄÄÄÅuıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ%—ïµ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅmÌÕç°ïµÖ}•—ïµÕıuıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°Õ’ââ…Öπê•ÙÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°µï—Ö}ëïÕç…•¡—•Ω∏•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩµï…≠îΩÌÕ±’ùÙºà¯)Ì}Ωù}µï—Ñ°òùÌÕ’ââ…ÖπëÙÅ≠Ωπ—Ö≠—±•πÕï»ÉäLÅMÖµµïπ±•ù∏Å¡…•Õï»ÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Åµï—Ö}ëïÕç…•¡—•Ω∏∞ÅòùÌ	M}UI1ÙΩµï…≠îΩÌÕ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯)Ìâ…Öπë}ôÖ≈}Õç°ïµÖÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù)ÌU%}Q%1}MQe1Ù)Ì	I9}A}MQe1Ù)ÌAI%YQ}1	1}%11UMQIQ%=9}MQe1Ù(π¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»ÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ·¡‡Ä»¡¡‡ÏÅµÖ…ù•∏ËÄ»¡¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅıÙ(π¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»ÅÕ—…ΩπúÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…•ŸÖ—îµ±Öâï∞µçÖŸïÖ–ÅÌÏÅâÖç≠ù…Ω’πêËÄç—‘ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡ÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°Õ’ââ…Öπê•ÙΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºÅ¡…•ŸÖ—îµ±Öâï∞µâ…Öπêµ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµçΩπ—ïπ–à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµ…Ω‹à¯(ÄÄÄÄÄÄÄÅÌâ…Öπë}±ΩùΩ}â±Ωç≠Ù(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘5ï…≠îΩë•ÿ¯(ÄÄÄÄÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°Õ’ââ…Öπê•ÙÅ≠Ωπ—Ö≠—±•πÕï»Ω†ƒ¯(ÄÄÄÄÄÄÄÄÄÅÌâ…Öπë}Õ’â—•—±ï}°—µ±Ù(ÄÄÄÄÄÄÄÄÄÄÒ¿˘Ìâ…Öπë}•π—…Ω}Õïπ—ïπçïÙΩ¿¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµç—Ñµ…Ω‹à¯(ÄÄÄÄÄÄÄÄÄÄÄÄÒÑÅç±ÖÕÃÙââ…Öπêµ°ï…ºµç—ÑàÅ°…ïòÙàç¡…Ωë’≠—ï»à˘MîÅÖ±±îÅÌïÕçÖ¡î°Õ’ââ…Öπê•Ùµ¡…Ωë’≠—ï»ÉäHΩÑ¯(ÄÄÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµµïë•ÑàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯(ÄÄÄÄÄÄÒ¡•ç—’…î¯(ÄÄÄÄÄÄÄÄÒÕΩ’…çîÅµïë•ÑÙà°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§àÅ—Â¡îÙâ•µÖùîΩ›ïâ¿àÅÕ…çÕï–ÙàΩÕ—Ö—•åΩ°ï…ºΩâ…Öπê¥‘ÿ¿π›ïâ¿Ä‘ÿ¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩâ…Öπê¥‡–¿π›ïâ¿Ä‡–¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩâ…Öπê¥ƒƒ»¿π›ïâ¿Äƒƒ»¡‹àÅÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ»¿¡¡‡§Ä‘ÿ¡¡‡∞Ä–¡Ÿ‹à¯(ÄÄÄÄÄÄÄÄÒ•µúÅÕ…åÙâëÖ—ÑÈ•µÖùîΩù•òÌâÖÕîÿ–±H¡±=±°E	 ’	-1	%Q=‹ÙÙàÅÖ±–ÙààÅ›•ë—†Ùà‘ÿ¿àÅ°ï•ù°–ÙàÃ‡‘àÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄÄÄΩ¡•ç—’…î¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙââ…Öπêµ°ï…ºµÕ—Ö—Ãà˘Ìâ…Öπë}°ï…Ω}Õ—Ö—Õ}°—µ±ÙΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâµΩâ•±îµ¡…Ωë’ç—Ãµô•…Õ–à¯(ÄÄÒë•ÿÅç±ÖÕÃÙâÕ’¡¡Ω…—•πúµçΩπ—ïπ–à¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»à¯(ÄÄÄÄÒ¿¯ÒÕ—…Ωπú˘!ŸÑÅï»ÅÌïÕçÖ¡î°Õ’ââ…Öπê•Ù¸ΩÕ—…Ωπú¯ÅÌïÕçÖ¡î°Õ’ââ…Öπê•ÙÅï»Åï–Åïùï–ÅŸÖ…ïπÖŸ∏ÅôΩ»Å≠Ωπ—Ö≠—±•πÕï»∞Å§ÅÕ—ïëï–ÅôΩ»Å¡…Ωë’Õïπ—ïπÃÅΩ¡¡…•ππï±•ùîÅπÖŸ∏∏Åï–Åï»Å•≠≠îÅï∏Åïùï∏Å±•πÕï¡…Ωë’Õïπ–ÉäLÅ°Ÿï»ÅÌïÕçÖ¡î°Õ’ââ…Öπê•Ùµ±•πÕîÅï»Å•ëïπ—•Õ¨ÅµïêÅï∏Å≠©ïπ–Å±•πÕîÅô…ÑÅï∏ÅÖÿÅëîÅÕ—Ω…îÅ¡…Ωë’Õïπ—ïπî∞ÅâÖ…îÅµïêÅïùï∏ÅïµâÖ±±ÖÕ©îÅΩúÅπÖŸ∏∏ÅA…•ÕïπîÅ’πëï»Åï»Å°ïπ—ï–Åô…ÑÅëï–Åï≠—îÅ¡…Ωë’≠—ï–∞ÅÕ•ëï∏Åëï–Åï»Åª·ÂÖ≠—•úÅÕÖµµîÅôÂÕ•Õ≠îÅŸÖ…î∏ÅMîÄÒÑÅ°…ïòÙàΩ¡…•ŸÖ—îµ±Öâï∞ºà˘ΩŸï…Õ•≠—ï∏ÅΩŸï»ÅΩ¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ΩÑ¯ÅôΩ»Å°Ÿ•±≠ï∏Å≠©ïëîÅÕΩ¥ÅÕ”ï»ÅâÖ¨∏Ω¿¯(ÄÄΩë•ÿ¯((ÄÅÌâ…Öπë}•πÕ•ù°—}…Ω›}°—µ±Ù((ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•Ω…•—‰µ¡…Ωë’ç—Ãà¯(ÄÄÒ†»Å•êÙâ¡…Ωë’≠—ï»à˘±±îÅÌïÕçÖ¡î°Õ’ââ…Öπê•Ùµ¡…Ωë’≠—ï»Ω†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙâô•±—ï»µ…Ω‹àÅ•êÙâô•±—ï»µ…Ω‹àÅ…Ω±îÙâù…Ω’¿àÅÖ…•Ñµ±Öâï∞Ùâ•±—…ï»Åï——ï»Å≠Ö—ïùΩ…§à¯(ÄÄÄÄÒâ’——Ω∏Åç±ÖÕÃÙâç°•¿ÅÖç—•ŸîàÅëÖ—ÑµçÖ—ïùΩ…‰ÙâÖ±∞à˘±±îÅ≠Ö—ïùΩ…•ï»Ωâ’——Ω∏¯(ÄÄÄÅÌçÖ—ïùΩ…Â}ç°•¡ÕÙ(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ±•Õ–µ°ïÖëï»à¯(ÄÄÄÄÒ†»Å•êÙâ…ïÕ’±–µçΩ’π–à˘Ì±ï∏°…Ω›Ã•ÙÅ¡…Ωë’≠—ï»Ω†»¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅ•êÙâ¡…Ωë’ç–µ±•Õ–àÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµù…•êà¯(ÄÄÄÅÌ¡…Ωë’ç—}…Ω›Õ}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÄÒπΩÕç…•¡–¯Ò¿ÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‹·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà˘•±—…ï…•πúÅ≠…ïŸï»Å)ÖŸÖMç…•¡–∏Å1•Õ—ï∏ÅΩŸï»ÅŸ•Õï»ÅÖ±±îÅ¡…Ωë’≠—ï»∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏Ω¿¯ΩπΩÕç…•¡–¯(ÄÅÏúÒ¿ÅÕ—Â±îÙâµÖ…ù•∏Ëƒ¡¡‡Ä¿Ä¿ÌôΩπ–µÕ•ÈîË¿∏‹·…ï¥ÌçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà˘9Ωï∏ÅŸÖ…•Öπ—ï»ÅΩŸï»ÅŸ•ÕïÃÅµïêÅï∏Åïùï∏Å•±±’Õ—…ÖÕ©Ω∏Å§ÅÕ—ïëï–ÅôΩ»Åï–Åï≠—îÅ¡…Ωë’≠—â•±ëî∏ÄÒÑÅ°…ïòÙàΩΩ¥µ¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»ºàÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ì—ï·–µëïçΩ…Ö—•Ω∏È’πëï…±•πîÏà˘1ïÃÅ°ŸΩ…ôΩ»ÉäHΩÑ¯Ω¿¯úÅ•òÅÖπÂ}¡±•}•±±’Õ—…Ö—•Ω∏Åï±ÕîÄúùÙ((ÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÅÌÕΩ…—•µïπ—}°—µ±Ù(ÄÅÌâ…Öπë}µÖ—ï…•Ö±Õ}°—µ±Ù(ÄÅÌ¡Öç≠|Ã¡|‰¡}°—µ±Ù(ÄÄÒë•ÿÅç±ÖÕÃÙââ…ÖπêµôÖƒµ›…Ö¿à˘Ìâ…Öπë}ôÖ≈}°—µ±ÙΩë•ÿ¯(ÄÅÌâ…Öπë}ù’•ëïÕ}°—µ±Ù((ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖ—îµ±Öâï∞µçÖŸïÖ–à¯(ÄÄÄÄÒÕ—…Ωπú˘[ô»ÅΩâÃÅ√îÅëï——îÅõ·»Åë‘ÅâÂ——ï»ËΩÕ—…Ωπú¯Å-Ωâ±•πùïπîÅΩŸï»Åï»ÅÕÖ—–ÅÕÖµµï∏ÅâÖÕï…–Å√îÅ—•±ù©ïπùï±•úÅ•πôΩ…µÖÕ©Ω∏ÅΩ¥Å¡…Ωë’Õïπ–ÅΩúÅ¡…Ωë’≠—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»∏Å-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å•πùï∏ÅÖŸ—Ö±îÅµïêÅ≠©ïëï∏ÅâÖ¨Åëï——îÅµï…≠ïπÖŸπï–ÅΩúÅ≠Ö∏Å•≠≠îÅùÖ…Öπ—ï…îÅÖ–Å°Ÿï»Å≠Ωâ±•πúÅÕ—ïµµï»Å§ÅÖ±±îÅ—•±ôï±±ï»ÉäLÅ¡Ö≠π•πùÕÕ”·……ï±ÕîÅï±±ï»Å—•±ù©ïπùï±•ùîÅÕ—Â…≠ï»Å≠Ö∏ÅôΩ»Åï≠Õïµ¡ï∞ÅÖŸŸ•≠î∏Å	ï≠…ïô–ÅÖ±±—•êÅµïêÅë•∏ÅΩ¡—•≠ï»Åï±±ï»ÅÕÂπÕ…ïÕï¡–Åõ·»Åë‘ÅâÂ——ï»Åµï±±Ω¥Åë•ÕÕîÅπÖŸπïπî∏(ÄÄΩë•ÿ¯((ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà¯ÒÑÅ°…ïòÙàΩ¡…•ŸÖ—îµ±Öâï∞ºàÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µâ±’î§ÌôΩπ–µ›ï•ù°–Ëÿ¿¿Ì—ï·–µëïçΩ…Ö—•Ω∏ÈπΩπîÏà˘MîÅΩ¡—•≠ï…≠©ïëïπïÃÅÖπë…îÅïùπîÅµï…≠ï»ÉäHΩÑ¯Ω¿¯((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅA…•ÕïπîÅ°ï»Åï»Å¡…Ωë’≠—¡…•Õï»Å’—ï∏Åô…Ö≠–∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ÅCîÅ°Ÿï»(ÄÄÄÅ¡…Ωë’≠—Õ•ëîÅ≠Ö∏Åë‘ÅÕ≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅôΩ»ÉîÅÕîÅ—Ω—Ö±¡…•Õï∏∏ÅY§Å≠Ö∏Åõî(ÄÄÄÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Å°Öπë±ï»ÅŸ•ÑÅ±ïπ≠ïπî∞Åµï∏Åëï–Å√ïŸ•…≠ï»ÅÖ±ë…§Å¡…•Õï∏Åë‘(ÄÄÄÅâï—Ö±ï»∏ÅIï≠≠ïõ·±ùï∏Åï»ÅÖ±±—•êÅâÖÕï…–Å√îÅ¡…•Ã∞ÅâΩ…—Õï—–Åô…ÑÅŸïê(ÄÄÄÅï≠ÕÖ≠–Å±•¨Å¡…•ÃÅµï±±Ω¥Å—ºÅ—•±â’ê∞Åëï»ÅŸ§Å≠Ö∏Å¡…•Ω…•—ï…îÅï∏ÅôΩ…°Öπë±ï»ÅŸ§(ÄÄÄÅ°Ö»ÅÖŸ—Ö±îÅµïê∏Å-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•ú(ÄÄÄÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—î∞Å•≠≠îÅï∏ÅôΩ…°Öπë±ï»∏(ÄÄΩ¿¯((ÄÅÌâ…Öπë}—…’Õ—}°—µ±Ù(Ωë•ÿ¯((ÒÕç…•¡–¯(ÄÅçΩπÕ–Åô•±—ï…IΩ‹ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ùô•±—ï»µ…Ω‹ú§Ï(ÄÅçΩπÕ–Å±•Õ–ÄÙÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…Ωë’ç–µ±•Õ–ú§Ï((ÄÅô’πç—•Ω∏ÅÖ¡¡±Â	…Öπë•±—ï»°çÖ—ïùΩ…‰§ÅÌÏ(ÄÄÄÅçΩπÕ–Åâ—∏ÄÙÅô•±—ï…IΩ‹π≈’ï…ÂMï±ïç—Ω»†úπç°•¡mëÖ—ÑµçÖ—ïùΩ…‰ÙàúÄ¨ÅçÖ—ïùΩ…‰Ä¨Äúâtú§Ï(ÄÄÄÅ•òÄ†Öâ—∏§Å…ï—’…∏Ï(ÄÄÄÅô•±—ï…IΩ‹π≈’ï…ÂMï±ïç—Ω…±∞†úπç°•¿ú§πôΩ…Öç†°åÄÙ¯Ååπç±ÖÕÕ1•Õ–π…ïµΩŸî†ùÖç—•Ÿîú§§Ï(ÄÄÄÅâ—∏πç±ÖÕÕ1•Õ–πÖëê†ùÖç—•Ÿîú§Ï(ÄÄÄÅ±ï–ÅŸ•Õ•â±îÄÙÄ¿Ï(ÄÄÄÅ±•Õ–π≈’ï…ÂMï±ïç—Ω…±∞†úπ¡…Ωë’ç–µ—•±îú§πôΩ…Öç†°çÖ…êÄÙ¯ÅÌÏ(ÄÄÄÄÄÅçΩπÕ–ÅÕ°Ω‹ÄÙÅçÖ—ïùΩ…‰ÄÙÙÙÄùÖ±∞úÅÒÅçÖ…êπëÖ—ÖÕï–πçÖ—ïùΩ…‰ÄÙÙÙÅçÖ—ïùΩ…‰Ï(ÄÄÄÄÄÅçÖ…êπÕ—Â±îπë•Õ¡±Ö‰ÄÙÅÕ°Ω‹Ä¸ÄúúÄËÄùπΩπîúÏ(ÄÄÄÄÄÅ•òÄ°Õ°Ω‹§ÅŸ•Õ•â±î¨¨Ï(ÄÄÄÅıÙ§Ï(ÄÄÄÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù…ïÕ’±–µçΩ’π–ú§π—ï·—Ωπ—ïπ–ÄÙÅŸ•Õ•â±îÄ¨ÄúÅ¡…Ωë’≠—ï»úÏ(ÄÅıÙ((ÄÅçΩπÕ–Å•π•—•Ö±Ö—ïùΩ…‰ÄÙÅ›•πëΩ‹π±ΩçÖ—•Ω∏π°ÖÕ†π…ï¡±Öçî†úåú∞Äúú§Ï(ÄÅ•òÄ°•π•—•Ö±Ö—ïùΩ…‰ÄòòÅô•±—ï…IΩ‹π≈’ï…ÂMï±ïç—Ω»†úπç°•¡mëÖ—ÑµçÖ—ïùΩ…‰ÙàúÄ¨Å•π•—•Ö±Ö—ïùΩ…‰Ä¨Äúâtú§§ÅÌÏ(ÄÄÄÅÖ¡¡±Â	…Öπë•±—ï»°•π•—•Ö±Ö—ïùΩ…‰§Ï(ÄÅıÙ(ÄÅëΩç’µïπ–π≈’ï…ÂMï±ïç—Ω…±∞†úπâ…ÖπêµÕΩ…—•µïπ–µçÖ…êú§πôΩ…Öç†°çÖ…êÄÙ¯ÅÌÏ(ÄÄÄÅçÖ…êπÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞Ä†§ÄÙ¯ÅÌÏ(ÄÄÄÄÄÅÖ¡¡±Â	…Öπë•±—ï»°çÖ…êπëÖ—ÖÕï–πçÖ—ïùΩ…‰§Ï(ÄÄÄÄÄÅëΩç’µïπ–πùï—±ïµïπ—	Â%ê†ù¡…Ωë’≠—ï»ú§πÕç…Ω±±%π—ΩY•ï‹°ÌÏÅâï°ÖŸ•Ω»ËÄùÕµΩΩ—†ú∞Åâ±Ωç¨ËÄùÕ—Ö…–úÅıÙ§Ï(ÄÄÄÅıÙ§Ï(ÄÅıÙ§Ï((ÄÅô•±—ï…IΩ‹πÖëëŸïπ—1•Õ—ïπï»†ùç±•ç¨ú∞ÅîÄÙ¯ÅÌÏ(ÄÄÄÅçΩπÕ–Åâ—∏ÄÙÅîπ—Ö…ùï–πç±ΩÕïÕ–†úπç°•¿ú§Ï(ÄÄÄÅ•òÄ†Öâ—∏§Å…ï—’…∏Ï(ÄÄÄÅÖ¡¡±Â	…Öπë•±—ï»°â—∏πëÖ—ÖÕï–πçÖ—ïùΩ…‰§Ï(ÄÅıÙ§Ï(ΩÕç…•¡–¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà()ëïòÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}¡Öùî°±Öâï∞ËÅë•ç–∞Å…ïÖ±}¡…Ωë’ç–ËÅë•ç–∞ÅçÖ—ïùΩ…•ïÃËÅë•ç–∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî∞ÅôÖµ•±‰ËÅë•ç–ÅÅ9ΩπîÄÙÅ9Ωπî∞Åç±•ç≠Ω’—ÃËÅë•ç–ÅÅ9ΩπîÄÙÅ9Ωπî∞Å¡…•çï}°•Õ—Ω…‰ËÅ±•Õ—më•ç—tÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâ∏Åëï∞ÅΩ¡—•≠ï…≠©ïëï»Å¡Ö≠≠ï»ÅΩ¥Åï≠—îÅ≠Ωπ—Ö≠—±•πÕï»Å’πëï»ÅÕ•—–Åïùï–(ÄÄÄÅµï…≠ïπÖŸ∏Ä°òπï≠Ã∏ÅMÂπÕÖ¥ÅÕ•∏ÄâÂïDÄ»–àÅï»Åïùïπ—±•úÅ	•Ωô•π•—‰Åô…Ñ(ÄÄÄÅΩΩ¡ï…Y•Õ•Ω∏§∏Å¡…•ŸÖ—ï}±Öâï±Ãπ©ÕΩ∏Å°Ω±ëï»Å-U8Å£·‰µÕ•≠≠ï…°ï–µ≠Ωâ±•πùï»∞(ÄÄÄÅâï≠…ïô—ï–Åë•…ï≠—îÅµΩ–Åï∏Å’ÖŸ°ïπù•úÅ≠•±ëîÄ°1ïπÕ›Ö‰ÅÕ•∏Åïùï∏(ÄÄÄÄâΩ¡—•≠ï…≠©ïëïπïÃÅŸÖ…ïµï…≠îàµÕï≠Õ©Ω∏∞ÅÕΩ¥Åï≠Õ¡±•Õ•—–ÅΩ¡¡ù•»Å°Ÿ•±≠ï–(ÄÄÄÅ¡…Ωë’Õïπ–µπÖŸ∏Å°Ÿï»Å¡…•ŸÖ—îÅ±Öâï∞µ±•πÕîÅÕï±ùïÃÅ’πëï»§∏ÅïππîÅÕ•ëï∏(ÄÄÄÅŸ•Õï»Å%--Åïùï∏Å¡…•ÃΩ—•±â’ëÕëÖ—ÑÄ¥¥Åëï∏Åù©ïπâ…’≠ï»Å…ïÖ±}¡…Ωë’ç–ÅÕ•πî(ÄÄÄÅôÖ≠—•Õ≠îÅ—•±â’ê∞ÅÕ•ëï∏Åëï–Åï»Åª·ÂÖ≠—•úÅÕÖµµîÅôÂÕ•Õ≠îÅŸÖ…î∏ààà(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§(ÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°…ïÖ±}¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÅâïÕ–ÄÙÅπï·–†°ºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•Õ}±Ω›ïÕ–ât§∞Å9Ωπî§(ÄÄÄÅÕ°•¡}ç°•¡}°—µ∞ÄÙÅ}Õ°•¡}ç°•¡}âΩ·ïë}°—µ∞†âÕ°•¿µç°•¿à§Å•òÅΩôôï…ÃÅï±ÕîÄàà(ÄÄÄÅΩôôï…Õ}â±Ωç¨∞Åï·}âïÕ–ÄÙÅ…ïπëï…}¡…•çï}±•Õ–°Ωôôï…Ã∞Å…ïÖ±}¡…Ωë’ç—lâπÖµîât∞Å…ïÖ±}¡…Ωë’ç—lâ•êât∞Åç±•ç≠Ω’—Ã∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ—•—±îıòâMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅÌ…ïÖ±}¡…Ωë’ç—lùπÖµîùuÙà∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ°Ω›}Õ°•¡}ç°•¿ıÖ±Õî∞ÅçΩ±±Ö¡Õï}Öô—ï»Ùƒ¿∞Å¡…Ωë’ç—}Õ°•¡}ç°•¡}°—µ∞ıÕ°•¡}ç°•¡}°—µ∞§((ÄÄÄÅ•π}Õ—Ωç≠}Ωôôï…ÃÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÅÖâΩ’—}Ωôôï…Õ}Õç°ïµÑÄÙÄàà(ÄÄÄÅ•òÅ•π}Õ—Ωç≠}Ωôôï…ÃË(ÄÄÄÄÄÄÄÅÕç°ïµÖ}Ωôôï…ÃÄÙÄà±q∏ÄÄÄÄÄÄÄÄàπ©Ω•∏°òúúùÌÏ(ÄÄÄÄÄÄÄÄÄÄâ—Â¡îàËÄâ=ôôï»à∞(ÄÄÄÄÄÄÄÄÄÄâÕï±±ï»àËÅÌÏâ—Â¡îàËÄâ=…ùÖπ•ÈÖ—•Ω∏à∞ÄâπÖµîàËÄâÌïÕçÖ¡î°Ωlâ…ï—Ö•±ï»ât•ÙâıÙ∞(ÄÄÄÄÄÄÄÄÄÄâ¡…•çîàËÅÌΩlâ¡…•çï}πΩ¨âuÙ∞(ÄÄÄÄÄÄÄÄÄÄâ¡…•çï’……ïπç‰àËÄâ9=,à∞(ÄÄÄÄÄÄÄÄÄÄâ’…∞àËÄâÌ}©ÕΩπ}Õ—»°Ωlâ’…∞ât•Ùà∞(ÄÄÄÄÄÄÄÄÄÄâÖŸÖ•±Öâ•±•—‰àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úΩ%πM—Ωç¨à∞(ÄÄÄÄÄÄÄÄÄÄâÕ°•¡¡•πùï—Ö•±ÃàËÅÌÏ(ÄÄÄÄÄÄÄÄÄÄÄÄâ—Â¡îàËÄâ=ôôï…M°•¡¡•πùï—Ö•±Ãà∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕ°•¡¡•πùIÖ—îàËÅÌÏâ—Â¡îàËÄâ5Ωπï—Ö…ÂµΩ’π–à∞ÄâŸÖ±’îàËÅÌΩlâÕ°•¡¡•πù}πΩ¨âuÙ∞Äâç’……ïπç‰àËÄâ9=,âıÙ∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕ°•¡¡•πùïÕ—•πÖ—•Ω∏àËÅÌÏâ—Â¡îàËÄâïô•πïëIïù•Ω∏à∞ÄâÖëë…ïÕÕΩ’π—…‰àËÄâ9<âıÙ(ÄÄÄÄÄÄÄÄÄÅıÙ(ÄÄÄÄÄÄÄÅıÙúúúÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§(ÄÄÄÄÄÄÄÅ±Ω›}¡…•çîÄÙÅµ•∏°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§(ÄÄÄÄÄÄÄÅ°•ù°}¡…•çîÄÙÅµÖ‡°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§(ÄÄÄÄÄÄÄÅÖâΩ’—}Ωôôï…Õ}Õç°ïµÑÄÙÅòúúú∞ÄâΩôôï…ÃàËÅÌÏ(ÄÄÄÄÄÄâ—Â¡îàËÄâùù…ïùÖ—ï=ôôï»à∞(ÄÄÄÄÄÄâ¡…•çï’……ïπç‰àËÄâ9=,à∞(ÄÄÄÄÄÄâ±Ω›A…•çîàËÅÌ±Ω›}¡…•çïÙ∞(ÄÄÄÄÄÄâ°•ù°A…•çîàËÅÌ°•ù°}¡…•çïÙ∞(ÄÄÄÄÄÄâΩôôï…Ω’π–àËÅÌ±ï∏°•π}Õ—Ωç≠}Ωôôï…Ã•Ù∞(ÄÄÄÄÄÄâΩôôï…ÃàËÅmÌÕç°ïµÖ}Ωôôï…Õıt(ÄÄÄÅıÙúúú((ÄÄÄÅ…ïÖ±}πÖµîÄÙÅ…ïÖ±}¡…Ωë’ç—lâπÖµîât(ÄÄÄÅ…ïÖ±}â…ÖπêÄÙÅ…ïÖ±}¡…Ωë’ç—lââ…Öπë}±Öâï∞ât(ÄÄÄÅç°Ö•∏ÄÙÅ±Öâï±lâç°Ö•∏ât(ÄÄÄÅ¡…•ŸÖ—ï}πÖµîÄÙÅ±Öâï±lâπÖµîât(ÄÄÄÅ…ïÖ±}°…ïòÄÙÅòúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ…ïÖ±}¡…Ωë’ç—lââ…Öπë}Õ±’úâuÙΩÌ…ïÖ±}¡…Ωë’ç—lâÕ±’úâuÙºú(ÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ÄÙÅçÖ—ïùΩ…•ïÕm…ïÖ±}¡…Ωë’ç—lâçÖ—ïùΩ…Â}Õ±’úâuulâ±Öâï∞ât((ÄÄÄÅ›•ππï…}°—µ∞∞Å≈—Â}°—µ∞∞Å≈—Â}µ’±—•}°—µ∞ÄÙÅ…ïπëï…}›•ππï…}›•ëùï–°ï·}âïÕ–∞ÅΩôôï…Ã∞Å…ïÖ±}¡…Ωë’ç—lâπÖµîât∞Å¡…Ωë’ç—}•êı…ïÖ±}¡…Ωë’ç—lâ•êât∞Åç±•ç≠Ω’—Ãıç±•ç≠Ω’—Ã∞Å≈—Â}ç°Ω•çïÃÙ†ƒ∞Ä»∞Ä–∞Äÿ∞Ä‡∞Äƒ¿§∞Å•πç±’ëï}ç’Õ—Ωµ}¡•±∞ıÖ±Õî∞Å≈—Â}µ’±—•}•π±•πîıÖ±Õî§(ÄÄÄÄåÅA…•çîÅ%π—ï±±•ùïπçîÄ¥¥Åëï±–ÅµïêÅ≠Ωπ—Ö≠—±•πÕî¥Ω±•πÕï€ôÕ≠îµ¡…Ωë’≠—Õ•ëïπî(ÄÄÄÄåÄ°-Ö§∞Ä»¿»ÿ¥¿‰¥»‡ËÄâù©ï±ëï»ÅÖ±±îÅ¡…Ωë’≠—ï»Å√îÅëΩµïπï–(ÄÄÄÄåÅ≠Ωπ—Ö≠—±•πÕï»ππºÄ∏∏∏ÅïùπîÅµï…≠ïπÖŸ∏Å≠Ωπ—Ö≠—±•πÕï»à§∏Å!•Õ—Ω…•≠≠ï∏Åï»(ÄÄÄÄåÅ±Öù…ï–Å√îÅ…ïÖ±}¡…Ωë’ç–ÅÕ•∏Å•êÄ°ÕÖµµîÅôÂÕ•Õ≠îÅŸÖ…î∞ÅÕîÅëΩçÕ—…•πú§∞(ÄÄÄÄåÅ•≠≠îÅ√îÅÕï±ŸîÅ¡…•ŸÖ—îÅ±Öâï∞µï—•≠ï——ï∏∏(ÄÄÄÅ¡…•çï}°•Õ—Ω…Â}°—µ∞ÄÙÅ…ïπëï…}¡…•çï}•π—ï±±•ùïπçî°¡…•çï}°•Õ—Ω…‰ÅΩ»Åmt∞Å…ïÖ±}¡…Ωë’ç—lâπÖµîât∞ÅΩôôï…ÃıΩôôï…Ã∞Å¡…Ωë’ç—}•êı…ïÖ±}¡…Ωë’ç—lâ•êât§((ÄÄÄÄåÅMÖµµîÅ¡…•πÕ•¡¿ÅÕΩ¥Å…ïπëï…}¡…Ωë’ç—}¡ÖùîΩ…ïπëï…}ÕΩ±’—•Ωπ}¡…Ωë’ç—}¡ÖùîÄ¥¥(ÄÄÄÄåÅµï—ÑµâïÕ≠…•Ÿï±Õï∏ÅÕ≠Ö∞Å•ππï°Ω±ëîÅï∏Å±•ŸîÅ¡…•Ã∞Å•≠≠îÅâÖ…îÅëï∏Åùïπï…•Õ≠î(ÄÄÄÄåÄâÕÖµµïπ±•ù∏Å¡…•Õï»àµ—ï≠Õ—ï∏∏Å%ëïπ—•—ï—ÕôÖ≠—ÑÄ°°ŸÑÅëï∏Åïùïπ—±•úÅ°ï—ï»§(ÄÄÄÄåÅâï°Ω±ëïÃÅõ·…Õ–∞ÅÕ•ëï∏Åëï–Åï»ÅÕï±ŸîÅù…’ππï∏Å—•∞ÅÖ–ÅëïππîÅÕ•ëï∏Åô•ππïÃ(ÄÄÄÄåÄ°ï±±ï…ÃÅë’¡±•Õï…ï»Åëï∏ÅâÖ…îÅ…ïÖ±}¡…Ωë’ç–ÅÕ•∏Åïùï∏ÅÕ•ëî§∏Å	…’≠ï»(ÄÄÄÄåÅAI=UM9Q8Ä°òπï≠Ã∏ÅΩΩ¡ï…Y•Õ•Ω∏§∞Å•≠≠îÅ…ïÖ±}â…ÖπêÄ°òπï≠Ã∏Äâ	•Ωô•π•—‰à§(ÄÄÄÄåÄ¥¥Å…ïÖ±}πÖµîÅ•ππï°Ω±ëï»ÅÖ±±ï…ïëîÅµï…≠ïπÖŸπï–Ä†â	•Ωô•π•—‰Äÿµ¡Öç¨à§∞Åœî(ÄÄÄÄåÄà∏∏∏Åï»ÅÕÖµµîÅ±•πÕîÅÕΩ¥Å	•Ωô•π•—‰Äÿµ¡Öç¨Åô…ÑÅ	•Ωô•π•—‰àÅŸÖ»Åï∏(ÄÄÄÄåÅù©ïπ—Ö≠ï±Õî∏ÅÖ±±ï»Å—•±âÖ≠îÅ—•∞Å…ïÖ±}â…ÖπêÅ≠’∏ÅôΩ»ÅëîÅÕ©ï±ëπî(ÄÄÄÄåÅµï…≠ïπîÅ’—ï∏Å¡…Ωë’Õïπ–µ≠Ωâ±•πúÅ§Å	I9}Q=}59UQUIH∏(ÄÄÄÅµÖπ’ôÖç—’…ï…}Õ±’úÄÙÅ	I9}Q=}59UQUIHπùï–°…ïÖ±}¡…Ωë’ç—lââ…Öπë}Õ±’úât§(ÄÄÄÅ…ïÖ±}ÕΩ’…çîÄÙÅ59UQUIIMmµÖπ’ôÖç—’…ï…}Õ±’ùulâπÖµîâtÅ•òÅµÖπ’ôÖç—’…ï…}Õ±’úÅï±ÕîÅ…ïÖ±}â…Öπê(ÄÄÄÄåÅ-©ïëïπÖŸπï–Ä°MÂπÕÖ¥Ω	…•±±ï±ÖπêΩM¡ïçÕÖŸï…ÃΩΩ¡—•≠¨§ÅÕ≠Ö∞Å%--ÅπïŸπïÃÅ√î(ÄÄÄÄåÅëïππîÅÕ•ëï∏Å±ïπùï»Ä°â…’≠ï»µâïÕ±’—π•πúÄ»¿»ÿ¥¿‡¥Ã¿§Ä¥¥Åëï∏ÅïπïÕ—îÅÕ•ëï∏(ÄÄÄÄåÅÕΩ¥ÅôΩ…—ÕÖ—–ÅπïŸπï»Å≠©ïëï»Åï»ÅÕï±ŸîÅÕÖµ±ïÕ•ëï∏ÄΩ¡…•ŸÖ—îµ±Öâï∞º∞ÅÕΩ¥(ÄÄÄÄåÅù…’¡¡ï…ï»Å11ÅÕï…•ïπîÅ—•∞ÅÕÖµµïπ±•ùπ•πú∏ÅïππîÅÕ•ëï∏Ä°ï—–Åïπ≠ï±–(ÄÄÄÄåÅ¡…Ωë’≠–§Åâ…’≠ï»ÅΩâ©ï≠—•ÿÅΩ…ë±ïùù•πúÅ§ÅÕ—ïëï–ÅΩúÅ±ïπ≠ï»Å—•∞ÅÕÖµ±ïÕ•ëï∏(ÄÄÄÄåÅôΩ»Å°Ÿï¥ÅÕΩ¥ÅôÖ≠—•Õ¨ÅÕ”ï»ÅâÖ¨∏(ÄÄÄÄåÅA…•ÃΩÕÖ±ùÃµ°ΩΩ¨ÅaIMPÅ§Å—•——ï∞ÅΩúÅµï—ÑµâïÕ≠…•Ÿï±Õî∞Å•ëïπ—•—ï—Ã¥(ÄÄÄÄåÅÖŸÕ≥·…•πùï∏Ä†âï»Åïùïπ—±•úÅ`à§Å-U8Å§Å ƒΩâÀ·ë—ï≠Õ–Ä¥¥Åâ…’≠ï…âïÕ±’—π•πú(ÄÄÄÄåÄ»¿»ÿ¥¿‰¥¿‘ËÅ∑ï±ï–ÅµïêÅMI@µ—ï≠Õ—ï∏Åï»ÉîÅõîÅôΩ±¨Å—•∞ÉîÅ≠±•≠≠î∞Å•≠≠îÉî(ÄÄÄÄåÅÕŸÖ…îÅ√îÅÕ√·…Õ∑ï±ï–Åõ·»ÅëîÅ§Åëï–Å°ï±îÅ—Ö—–Åï»Å•ππîÅ√îÅÕ•ëï∏∏ÅΩ……•ùî(ÄÄÄÄåÅŸÖ…•Öπ–Ä†â!ŸÑÅ°ï—ï»Åëï∏Åïùïπ—±•ú¸à§ÅŸÖ»Å…•≠—•ùπΩ¨Å•≠≠îÅï∏ÅÖŸÕ≥·…•πúÅ§(ÄÄÄÄåÅÕïúÅÕï±ÿ∞Åµï∏ÅΩΩù±îÅï…Õ—Ö——ï–Åëï∏Å±•≠ïŸï∞ÅΩô—îÅµïêÅ ƒµï∏Ä°ÕΩ¥ÅHÅï∏(ÄÄÄÄåÅÖŸÕ≥·…•πú§Å§Åœ·≠ï—…ïôòÄ¥¥Å—…Ω±•úÅôΩ…ë§ÅÕÖµµîÅ—•——ï±µÖ∞Åù•≠¨Å•ù©ï∏(ÄÄÄÄåÅ•ëïπ—•Õ¨Å√îÅÖ±±îÄÿ–Å¡…•ŸÖ—îÅ±Öâï∞µÕ•ëïπî∏ÅïππîÅπÂîÅ—ï≠Õ—ï∏Åï»(ÄÄÄÄåÅ¡…•Õë…ïŸï–∞ÅÕÖµµîÅÕ—•∞ÅÕΩ¥Å…ïπëï…}¡…Ωë’ç—}¡ÖùîÅÖ±±ï…ïëîÅâ…’≠ï»(ÄÄÄÄåÄ†ã
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•Ãà§∞ÅôΩ»Å≠ΩπÕ•Õ—ïπÃÅ√îÅ—Ÿï…ÃÅÖÿ(ÄÄÄÄåÅÕ•ëï∏ÅΩúÅôΩ…ë§Åëï–Åï»Åï∏ÅÖ±±ï…ïëîÅï—Öâ±ï…–∞Åô’πùï…ïπëîÅ…Öµµî∏(ÄÄÄÅµï—Ö}ëïÕç…•¡—•Ω∏ÄÙÄ†(ÄÄÄÄÄÄÄÅòùMîÅ±ÖŸïÕ—îÅ¡…•ÃÅ√îÅÌ¡…•ŸÖ—ï}πÖµïÙÅâ±Öπ–ÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÉäLÅô…ÑÄú(ÄÄÄÄÄÄÄÅòùÌ}ôµ—}≠»°ï·}âïÕ—lâ¡…•çï}πΩ¨ât•ÙÅ°ΩÃÅÌï·}âïÕ—lâ…ï—Ö•±ï»âuÙ∏Å=¡¡ëÖ—ï…–ÅëÖù±•ú∏ú(ÄÄÄÄ§Å•òÅï·}âïÕ–Åï±ÕîÅòùMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅÌ¡…•ŸÖ—ï}πÖµïÙÅâ±Öπ–ÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏ú((ÄÄÄÄåÅMÂπ±•ú∞ÅI]1	HÅ—ï≠Õ–ÅµïêÅëîÅÕÖµµîÅôÖ≠—ÑÅÕΩ¥ÅMI@µ—ï≠Õ—ï∏ÅΩŸï»(ÄÄÄÄåÄ°¡…•ÃΩÖπ—Ö±∞Åâ’—•≠≠ï»ΩΩ¡¡ëÖ—ï…•πùÕô…ï≠ŸïπÃ§Ä¥¥ÅΩΩù±îÅùïπï…ï…ï»ÅΩô—î(ÄÄÄÄåÅÕï±ŸîÅÕπ•¡¡ï—ï∏Åô…ÑÅ%99!=1PÅ√îÅÕ•ëï∏∞Å•≠≠îÅµï—ÑµâïÕ≠…•Ÿï±Õï∏Ä°≠’∏(ÄÄÄÄåÅâ…’≠–Åªï»ÅΩΩù±îÅÕï±ÿÅµïπï»Åëï∏Å¡ÖÕÕï»Åâïë…î§∞ÅœîÅë•ÕÕîÅôÖ≠—ÑÅã·»ÅÕ”î(ÄÄÄÄåÅÕΩ¥Åï≠—îÅ—ï≠Õ–Å°ï»ÅΩùœî∞Å•≠≠îÅâÖ…îÅ§Åï∏Åµï—Ñµ—Öú∏ÅMÖµµîÅ∑·πÕ—ï»ÅÕΩ¥(ÄÄÄÄåÄπ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰Å√îÅ…ïπëï…}¡…Ωë’ç—}¡ÖùîΩ…ïπëï…}ÕΩ±’—•Ωπ}¡…Ωë’ç—|(ÄÄÄÄåÅ¡ÖùîÄ°±Öù–Å—•∞Å°ï»Ä»¿»ÿ¥¿‰¥¿‘Ä¥¥Å¡…•ŸÖ—îÅ±Öâï∞µÕ•ëïπîÅµÖπù±ï–Åëïππî(ÄÄÄÄåÅâΩ≠Õï∏Å°ï±–§∏(ÄÄÄÅ•òÅâïÕ–Ë(ÄÄÄÄÄÄÄÅÖ•}Õ’µµÖ…Â}°—µ∞ÄÙÅòàààÒÕïç—•Ω∏Åç±ÖÕÃÙâ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰àÅÖ…•Ñµ±Öâï∞ÙâA…•ÕΩ¡¡Õ’µµï…•πúà¯(ÄÄÒ¿˘Y§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÄÒÕ—…Ωπú˘ÌïÕçÖ¡î°…ïÖ±}πÖµî•ÙΩÕ—…Ωπú¯Ä°ÕΩ±ù–ÅÕΩ¥ÅÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•ÙÅ°ΩÃÅëïππîÅ≠©ïëï∏§Å°ΩÃÅπΩ…Õ≠îÅπï——â’—•≠≠ï»∏Å1ÖŸïÕ—îÅ¡…•ÃÅÖ≠≠’…Ö–ÅªîÅï»ÄÒÕ—…Ωπú˘Ì}ôµ—}≠»°ï·}âïÕ—lâ¡…•çï}πΩ¨ât•ÙΩÕ—…Ωπú¯Å°ΩÃÅÌïÕçÖ¡î°ï·}âïÕ—lâ…ï—Ö•±ï»ât•ÙÄ°ï≠Õ≠∞∏Åô…Ö≠–§∏ÅA…•ÕïπîÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∞ÅÕ•Õ–Åâï≠…ïô—ï–ÅÌ}Ÿï…•ô•ïë}—Öú°}πï›ïÕ—}ç°ïç≠ïê°Ωôôï…Ã§•Ù∏Ω¿¯(ΩÕïç—•Ω∏¯ààà(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅÖ•}Õ’µµÖ…Â}°—µ∞ÄÙÅòàààÒÕïç—•Ω∏Åç±ÖÕÃÙâ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰ÅôÖ±±âÖç¨àÅÖ…•Ñµ±Öâï∞ÙâM—Ö—’Ãà¯(ÄÄÒ¿˘Y§Åõ·±ùï»Å¡…•Õï∏Å√îÄÒÕ—…Ωπú˘ÌïÕçÖ¡î°…ïÖ±}πÖµî•ÙΩÕ—…Ωπú¯Ä°ÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•Ù§∞Åµï∏Å•πùï∏ÅÖÿÅôΩ…°Öπë±ï…πîÅŸ§ÅÕÖµµïπ±•ùπï»Å°Ö»Åï∏Åâï≠…ïô—ï–Å¡…•ÃÅôΩ»ÅëïππîÅ±•πÕï∏ÅÖ≠≠’…Ö–Åªî∏ÅA…•ÕïπîÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∏Ω¿¯(ΩÕïç—•Ω∏¯ààà((ÄÄÄÅÖâΩ’—}—Â¡îÄÙÄâA…Ωë’ç–àÅ•òÅ•π}Õ—Ωç≠}Ωôôï…ÃÅï±ÕîÄâQ°•πúà(ÄÄÄÅëÖ—ï}µΩë•ô•ïêÄÙÅµÖ‡†°Ωlâç°ïç≠ïë}Ö–âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄåÅ	…ïÖëç…’µâ1•Õ–ÅµÖπù±ï–Å°ï»Ä°ôÖπ—ïÃÅ√îÅ≠Ö—ïùΩ…§¥Ωµï…≠î¥Ω¡…Ωë’Õïπ–µÕ•ëï»∞(ÄÄÄÄåÅµï∏Åëï∏Å—•ë±•ùï…îÅ≠Ωµµïπ—Ö…ï∏ÅΩ¥ÅÖ–Å¡…•ŸÖ—îÅ±Öâï∞µÕ•ëï»ÅÖ±±ï…ïëîÅ°Öëëî(ÄÄÄÄåÅëï∏ÅŸÖ»Åôï•∞Ä¥¥Åô’ππï–Ä»¿»ÿ¥¿‰¥¿‘ÅŸïêÅï∏ÅÕÂÕ—ïµÖ—•Õ¨Åù©ïππΩµùÖπúÅÖÿ(ÄÄÄÄåÅÕ—…’≠—’…ï…–ÅëÖ—ÑÅ√îÅ—Ÿï…ÃÅÖÿÅ11ÅÕ•ëï—Â¡ï»§∏ÅM¡ï•±ï»Åª·ÂÖ≠—•úÅëï∏(ÄÄÄÄåÅÕÂπ±•ùîÅâÀ·ëÕµ’±ï∏Å’πëï»Ä°!©ï¥Ä¯Å=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»Ä¯ÅπÖŸ∏§∏(ÄÄÄÅâ…ïÖëç…’µâ}Õç°ïµÑÄÙÅòúúùÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâ=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄÃ∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°¡…•ŸÖ—ï}πÖµî•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ΩÌ±Öâï±lâÕ±’úâuÙºâıÙ(ÄÅuıÙúúú(ÄÄÄÅ›ïâ¡Öùï}Õç°ïµÑÄÙÅòúúùÌÏ(ÄÄâ—Â¡îàËÄâ]ïâAÖùîà∞(ÄÄâπÖµîàËÄâÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•ÙÅï»Åïùïπ—±•úÅÌïÕçÖ¡î°…ïÖ±}πÖµî•Ùà∞(ÄÄâÖâΩ’–àËÅÌÏâ—Â¡îàËÄâÌÖâΩ’—}—Â¡ïÙà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°…ïÖ±}πÖµî•Ùà∞Äââ…ÖπêàËÅÌÏâ—Â¡îàËÄâ	…Öπêà∞ÄâπÖµîàËÄâÌïÕçÖ¡î°…ïÖ±}â…Öπê•ÙâııÌÖâΩ’—}Ωôôï…Õ}Õç°ïµÖııÙ∞(ÄÄâµÖ•ππ—•—Â=ôAÖùîàËÄâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ΩÌ±Öâï±lâÕ±’úâuÙºâÌòú∞ÄâëÖ—ï5Ωë•ô•ïêàËÄâÌëÖ—ï}µΩë•ô•ïëÙàúÅ•òÅëÖ—ï}µΩë•ô•ïêÅï±ÕîÄàâÙ)ıÙúúú(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅmÌâ…ïÖëç…’µâ}Õç°ïµÖÙ∞ÅÌ›ïâ¡Öùï}Õç°ïµÖıt)ıÙààà((ÄÄÄÄåÅMÖµµîÅëÂπÖµ•Õ≠îÅDµ∑·πÕ—ï»ÅÕΩ¥Å…ïπëï…}¡…Ωë’ç—}¡ÖùîΩ…ïπëï…}ÕΩ±’—•Ωπ|(ÄÄÄÄåÅ¡…Ωë’ç—}¡Öùî∞Åµï∏ÅÕ√·…Õ∑ï±ïπîÅ…ïôï…ï…ï»Å—•∞Åëï–Å-QÅ¡…Ωë’≠—πÖŸπï–(ÄÄÄÄåÄ°…ïÖ±}πÖµî§ÅÕ•ëï∏Åëï–Åï»Åëï–Å—•±â’ëïπîÅôÖ≠—•Õ¨Åù©ï±ëï»Ä¥¥Äâ°ŸΩ…ôΩ»Å°Ö»(ÄÄÄÄåÅëï∏Å—ºÅπÖŸ∏àµÕ√·…Õ∑ï±ï–Åï»ÅâïŸ•ÕÕ–Å%--ÅµïêÅ°ï»∞Åëï–Åï»ÅÖ±±ï…ïëî(ÄÄÄÄåÅù…’πë•úÅëï≠≠ï–ÅÖÿÅ¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»µâΩ≠Õï∏ÅΩŸï»∞ÅŸ•±±îÅâÖ…î(ÄÄÄÄåÅ€ô…–Åï∏Åë’¡±•Õï…•πú∏(ÄÄÄÅ¡…Ωë’ç—}ôÖƒËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅ•òÅâïÕ–Ë(ÄÄÄÄÄÄÄÅç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï»ÄÙÅµ•∏°•π}Õ—Ωç≠}Ωôôï…Ã∞Å≠ï‰ı±ÖµâëÑÅºËÅΩlâ¡…•çï}πΩ¨ât§(ÄÄÄÄÄÄÄÅ•òÅç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï…lâ…ï—Ö•±ï»âtÄÑÙÅâïÕ—lâ…ï—Ö•±ï»âtË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•±±•ùÕ—}ÕŸÖ»ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï…lâ…ï—Ö•±ï»âuÙÅ°Ö»Å±ÖŸïÕ–Å¡…Ωë’≠—¡…•ÃËÅÌ}ôµ—}≠»°ç°ïÖ¡ïÕ—}¡…Ωë’ç—}Ωôôï…lâ¡…•çï}πΩ¨ât•ÙÅ’—ï∏Åô…Ö≠–∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùIïùπï»Åë‘ÅµïêÅô…Ö≠–∞Åâ±•»ÅÌâïÕ—lâ…ï—Ö•±ï»âuÙÅâ•±±•ùÕ–ËÅÌ}ôµ—}≠»°âïÕ—lâ—Ω—Ö∞ât•ÙÅ—Ω—Ö±–Å•π≠±’ëï…–Åô…Ö≠–∏ú(ÄÄÄÄÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÄÄÄÄÅâ•±±•ùÕ—}ÕŸÖ»ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌâïÕ—lâ…ï—Ö•±ï»âuÙÅ°Ö»Å±ÖŸïÕ–Å¡…•Ã∞ÅãïëîÅ’—ï∏ÅΩúÅµïêÅô…Ö≠–ËÅÌ}ôµ—}≠»°âïÕ—lâ¡…•çï}πΩ¨ât•ÙÅ’—ï∏Åô…Ö≠–Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòú°Ì}ôµ—}≠»°âïÕ—lâ—Ω—Ö∞ât•ÙÅ•π≠±’ëï…–Åô…Ö≠–§∏ú(ÄÄÄÄÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ïâ≈’ïÕ—•Ω∏àËÅòù!ŸΩ»Åï»ÅÌ…ïÖ±}πÖµïÙÄ°Ì¡…•ŸÖ—ï}πÖµïÙ§Åâ•±±•ùÕ–¸ú∞ÄâÖπÕ›ï»àËÅâ•±±•ùÕ—}ÕŸÖ…Ù§((ÄÄÄÄÄÄÄÅ±ÖŸïÕ—ï}¡…Ωë’≠—¡…•ÃÄÙÅµ•∏°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å•π}Õ—Ωç≠}Ωôôï…Ã§(ÄÄÄÄÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ŸÑÅ≠ΩÕ—ï»ÅÌ…ïÖ±}πÖµïÙ¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù1ÖŸïÕ—îÅ¡…Ωë’≠—¡…•ÃÅ√îÅÌ…ïÖ±}πÖµïÙÅï»ÅÌ}ôµ—}≠»°±ÖŸïÕ—ï}¡…Ωë’≠—¡…•Ã•ÙÅ’—ï∏Åô…Ö≠–ÅÖ≠≠’…Ö–Åªî∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùQΩ—Ö±¡…•Õï∏ÅÖŸ°ïπùï»ÅÖÿÅ°Ÿ•±≠ï∏Åâ’—•≠¨Åë‘ÅŸï±ùï»ÅΩúÅô…Ö≠—≠ΩÕ—πÖëï∏Åëï»∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ¡…Ωë’ç—}ôÖƒπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄâ!ŸΩ»ÅΩô—îÅΩ¡¡ëÖ—ï…ïÃÅ¡…•Õïπî¸à∞(ÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄâ-Ωπ—Ö≠—±•πÕï»ππºÅ°ïπ—ï»ÅΩúÅΩ¡¡ëÖ—ï…ï»Å¡…•Õï»ÅÖ’—ΩµÖ—•Õ¨ÅëÖù±•ú∏ÅY§ÅŸ•Õï»Åâ’—•≠≠ïπÃÅ¡…Ωë’≠—¡…•ÃÄà(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ’—ï∏Åô…Ö≠–ÅΩúÅâï…ïùπï»Å—Ω—Ö±¡…•ÃÅâÖÕï…–Å√îÅô…Ö≠–ÅΩúÅÖπ—Ö±±ï–Åë‘ÅŸï±ùï»∏à∞(ÄÄÄÅÙ§((ÄÄÄÅ¡…Ωë’ç—}ôÖ≈}°—µ∞∞Å¡…Ωë’ç—}ôÖ≈}Õç°ïµÑÄÙÅ}…ïπëï…}ôÖ≈}â±Ωç¨°¡…Ωë’ç—}ôÖƒ∞ÅòùYÖπ±•ùîÅÕ√·…Õ∑ï∞ÅΩ¥ÅÌ…ïÖ±}πÖµïÙú§((ÄÄÄÅ…ï±Ö—ïë}•—ïµÃÄÙÅl(ÄÄÄÄÄÄÄÄ°òúΩµï…≠îΩÌ…ïÖ±}¡…Ωë’ç—lââ…Öπë}Õ±’úâuÙºú∞Åòù±±îÅÌ…ïÖ±}â…ÖπëÙµ≠Ωπ—Ö≠—±•πÕï»ú§∞(ÄÄÄÄÄÄÄÄ°òúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ…ïÖ±}¡…Ωë’ç—lâçÖ—ïùΩ…Â}Õ±’úâuÙºú∞Åòù±±îÅÌçÖ—ïùΩ…Â}±Öâï∞π±Ω›ï»†•Ùú§∞(ÄÄÄÅt(ÄÄÄÅ•µÖùï}’…∞ÄÙÅ}¡…•ŸÖ—ï}±Öâï±}•µÖùî°±Öâï∞§(ÄÄÄÅ•±±’Õ—…Ö—•Ω∏ÄÙÅ9ΩπîÅ•òÅ•µÖùï}’…∞Åï±ÕîÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}•±±’Õ—…Ö—•Ω∏°ç°Ö•∏∞Å±Öâï±lâÕ±’úât§(ÄÄÄÅ•òÅ•µÖùï}’…∞Ë(ÄÄÄÄÄÄÄÅ°ï…Ω}Ÿ•Õ’Ö∞ÄÙÅ}•µù}—Öú°•µÖùï}’…∞∞Å¡…•ŸÖ—ï}πÖµî∞Å±ΩÖë•πúÙâïÖùï»à§(ÄÄÄÅï±•òÅ•±±’Õ—…Ö—•Ω∏Ë(ÄÄÄÄÄÄÄÅ°ï…Ω}Ÿ•Õ’Ö∞ÄÙÄ°òúÒë•ÿÅç±ÖÕÃÙâ¡±§µ—•±îµ›…Ö¿à˘Ì•±±’Õ—…Ö—•ΩπÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄúÒ¿Åç±ÖÕÃÙâ•±±’Õ—…Ö—•Ω∏µπΩ—îà˘ùï∏Å•±±’Õ—…ÖÕ©Ω∏∞Å•≠≠îÅï–Åï≠—îÅ¡…Ωë’≠—â•±ëî∏ÄÒÑÅ°…ïòÙàΩΩ¥µ¡…Ωë’≠—•±±’Õ—…ÖÕ©Ωπï»ºà˘1ïÃÅµï»ΩÑ¯Ω¿¯ú§(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅ°ï…Ω}Ÿ•Õ’Ö∞ÄÙÅïÕçÖ¡î°¡…•ŸÖ—ï}πÖµïlË…tπ’¡¡ï»†§§(ÄÄÄÅÕ’ââ…Öπë}Õ±’úÄÙÅAI%YQ}1	1}MU		I9Lπùï–°ç°Ö•∏∞Åç°Ö•∏§π±Ω›ï»†§(ÄÄÄÅ…ï±Ö—ïë}•—ïµÃπÖ¡¡ïπê†°òúΩµï…≠îΩÌÕ’ââ…Öπë}Õ±’ùÙºú∞Åòù±ï…îÅÌAI%YQ}1	1}MU		I9Lπùï–°ç°Ö•∏∞Åç°Ö•∏•Ùµ¡…Ωë’≠—ï»ú§§(ÄÄÄÅ…ï±Ö—ïë}±•π≠ÃÄÙÄâq∏ÄÄÄÄàπ©Ω•∏°òúÒ±§¯ÒÑÅ°…ïòÙâÌïÕçÖ¡î°°…ïò•Ùà˘ÌïÕçÖ¡î°±Öâï±}—ï·–•ÙΩÑ¯Ω±§¯úÅôΩ»Å°…ïò∞Å±Öâï±}—ï·–Å•∏Å…ï±Ö—ïë}•—ïµÃ§(ÄÄÄÅ…ï±Ö—ïë}°—µ∞ÄÙÅòàààÒë•ÿÅç±ÖÕÃÙâ…ï±Ö—ïêà¯(ÄÄÄÄÒ†»˘Iï±Ö—ï…–Å—•∞ÅÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•ÙΩ†»¯(ÄÄÄÄÒ’∞¯(ÄÄÄÅÌ…ï±Ö—ïë}±•π≠ÕÙ(ÄÄÄÄΩ’∞¯(ÄÄΩë•ÿ¯ààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•ÙÉ
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•ÃΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°µï—Ö}ëïÕç…•¡—•Ω∏•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ΩÌ±Öâï±lâÕ±’úâuÙºà¯)Ì}Ωù}µï—Ñ°òùÌ¡…•ŸÖ—ï}πÖµïÙÉ
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•Ãú∞Åµï—Ö}ëïÕç…•¡—•Ω∏∞ÅòùÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ΩÌ±Öâï±lâÕ±’úâuÙºú∞Å•µÖùï}’…∞•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯)Ì¡…Ωë’ç—}ôÖ≈}Õç°ïµÖÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù)Ì!I=}%5}MQe1Ù)ÌAI%YQ}1	1}%11UMQIQ%=9}MQe1Ù(π°ï…ºµçÖ…êµÕΩ±’—•Ω∏Äπ°ï…ºµ¡…Ωë’ç–µ•µÖùîπ¡±§µ°ï…ºÅÌÏÅ¡Öëë•πúËÄ·¡‡ÏÅıÙ(π°ï…ºµçÖ…êµÕΩ±’—•Ω∏Äπ¡±§µ°ï…ºÄπ¡±§µ—•±îµ›…Ö¿ÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅıÙ(π°ï…ºµçÖ…êµÕΩ±’—•Ω∏Äπ°ï…ºµ¡…Ωë’ç–µ•µÖùîπ¡±§µ°ï…ºÅÌÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(π•±±’Õ—…Ö—•Ω∏µπΩ—îÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅ¡Öëë•πúËÄ¿Ä·¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏–ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ–¿¿ÏÅıÙ(π•±±’Õ—…Ö—•Ω∏µπΩ—îÅÑÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(π¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»ÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ·¡‡Ä»¡¡‡ÏÅµÖ…ù•∏ËÄ»¡¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅıÙ(π¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»ÅÕ—…ΩπúÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…•ŸÖ—îµ±Öâï∞µçÖŸïÖ–ÅÌÏÅâÖç≠ù…Ω’πêËÄç—‘ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÄç¡ÿ‹–ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡ÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡Öç¨µÕ•ÈîµçÖ±±Ω’–ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅùÖ¿ËÄƒ…¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ…¡‡ÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅ•π°ï…•–ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡’…ï¥ÏÅıÙ(π¡Öç¨µÕ•ÈîµçÖ±±Ω’–È°ΩŸï»ÅÌÏÅâΩ…ëï»µçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(π¡Öç¨µÕ•ÈîµçÖ±±Ω’–µÖ……Ω‹ÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅôΩπ–µÕ•ÈîËÄƒ∏≈…ï¥ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»µ±ïô–ËÄ—¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ¿Äƒ¡¡‡Äƒ¡¡‡Ä¿ÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ·¡‡ÏÅµÖ…ù•∏ËÄƒ…¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰’…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰Å¿ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰πôÖ±±âÖç¨ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ’—ïêµâú§ÏÅâΩ…ëï»µ±ïô–µçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ)Ì]%99I}]%Q}MQe1Ù)ÌAI%}1%MQ}MQe1Ù(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ¡…Ωë’ç–à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯(ÄÄÄÄÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäË(ÄÄÄÄÒÑÅ°…ïòÙàΩ¡…•ŸÖ—îµ±Öâï∞ºà˘=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ΩÑ¯ÉäË(ÄÄÄÅÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•Ù(ÄÄΩ¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µÕ—Öùîà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçÖ…êÅ°ï…ºµçÖ…êµÕΩ±’—•Ω∏à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµµÖ•∏à¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµ≠•ç≠ï»à˘ùï–Åµï…≠ïπÖŸ∏Ωë•ÿ¯(ÄÄÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•ÙÅï»Åïùïπ—±•úÅÌïÕçÖ¡î°…ïÖ±}πÖµî•ÙΩ†ƒ¯(ÄÄÄÄÄÄÄÄÒ¿Åç±ÖÕÃÙâ°ï…ºµÕ’â—•—±îà˘MÖµµïπ±•ù∏Å¡…•Õï»Ω¿¯(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµµïë•Ñµ…Ω‹à¯(ÄÄÄÄÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµ¡…Ωë’ç–µ•µÖùïÏúÅ°ÖÃµ¡°Ω—ºúÅ•òÅ•µÖùï}’…∞Åï±ÕîÄúÅ¡±§µ°ï…ºùÙà˘Ì°ï…Ω}Ÿ•Õ’Ö±ÙΩë•ÿ¯(ÄÄÄÄÄÄÄÄÄÅÌ›•ππï…}°—µ±Ù(ÄÄÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄÄÄΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÅÌ≈—Â}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÅÌΩôôï…Õ}â±Ωç≠Ù(ÄÅÌ¡…•çï}°•Õ—Ω…Â}°—µ±Ù(ÄÅÌ≈—Â}µ’±—•}°—µ±Ù(ÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿ËƒŸ¡‡Ïà¯ÒÑÅ°…ïòÙâÌïÕçÖ¡î°…ïÖ±}°…ïò•ÙàÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µâ±’î§ÌôΩπ–µ›ï•ù°–Ëÿ¿¿Ì—ï·–µëïçΩ…Ö—•Ω∏ÈπΩπîÏà˘MîÅô’±∞Å¡…Ωë’≠—Õ•ëîÅôΩ»ÅÌïÕçÖ¡î°…ïÖ±}πÖµî•ÙÉäHΩÑ¯Ω¿¯(ÄÅÌòúÒÑÅç±ÖÕÃÙâ¡Öç¨µÕ•ÈîµçÖ±±Ω’–àÅ°…ïòÙàΩÕï…•îΩÌïÕçÖ¡î°ôÖµ•±ÂlâÕ±’úât•Ùºà¯Òë•ÿÅç±ÖÕÃÙâ¡Öç¨µÕ•ÈîµçÖ±±Ω’–µ—ï·–à˘MîÅ°ï±îÄÒÕ—…Ωπú˘ÌïÕçÖ¡î°ôÖµ•±ÂlâπÖµîât•ÙΩÕ—…Ωπú¯µÕï…•ï∏ÉäPÅÕÖµµïπ±•ù∏ÅÕõô…•Õ¨∞Å—Ω…•Õ¨ÅΩúÅÖπë…îÅŸÖ…•Öπ—ï»Ωë•ÿ¯Òë•ÿÅç±ÖÕÃÙâ¡Öç¨µÕ•ÈîµçÖ±±Ω’–µÖ……Ω‹à˚äHΩë•ÿ¯ΩÑ¯úÅ•òÅôÖµ•±‰Åï±ÕîÄúùÙ((ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»à¯(ÄÄÄÄÒ¿¯ÒÕ—…Ωπú˘!ŸΩ…ôΩ»Å°Ö»Åëï∏Å—ºÅπÖŸ∏¸ΩÕ—…Ωπú¯Å5ÖπùîÅΩ¡—•≠ï…≠©ïëï»Å≠´·¡ï»Å≠Ωπ—Ö≠—±•πÕï»Åô…ÑÅëîÅÕÖµµîÅ¡…Ωë’Õïπ—ïπîÅÕΩ¥ÅÕï±ùï»Å’πëï»ÅïùπîÅ≠©ïπ—îÅµï…≠ï»∞ÅΩúÅ¡Ö≠≠ï»Åëï¥ÅΩ¥Å’πëï»Åï–Åïùï–ÅŸÖ…ïπÖŸ∏∏ÅMï±ŸîÅ±•πÕï∏ÉäLÅµÖ—ï…•Ö±î∞ÅÕ—Â…≠ïΩµÀïëîÅΩúÅÕ¡ïÕ•ô•≠ÖÕ©Ωπï»ÉäLÅï»Åëï∏ÅÕÖµµî∏Åï–Åï»ÅâÖ…îÅïµâÖ±±ÖÕ©ï∏ÅΩúÅπÖŸπï–ÅÕΩ¥Åï»Å’π•≠–ÅôΩ»ÅëïππîÅÕï…•ï∏∏Ω¿¯(ÄÄÄÄÒ¿ÅÕ—Â±îÙâµÖ…ù•∏µ—Ω¿Ëƒ¡¡‡Ïà¯ÒÑÅ°…ïòÙàΩÕ±•¨µµÖ—ç°ï»µŸ§µ¡…Ωë’≠—ï»ºàÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µâ±’î§ÌôΩπ–µ›ï•ù°–Ëÿ¿¿Ì—ï·–µëïçΩ…Ö—•Ω∏ÈπΩπîÏà˘!ŸΩ…ëÖ∏ÅŸï–ÅŸ§ÅÖ–Åëï——îÅï»ÅÕÖµµîÅ±•πÕî¸ÉäHΩÑ¯Ω¿¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖ—îµ±Öâï∞µçÖŸïÖ–à¯(ÄÄÄÄÒÕ—…Ωπú˘[ô»ÅΩâÃÅ√îÅëï——îÅõ·»Åë‘ÅâÂ——ï»ËΩÕ—…Ωπú¯ÅïππîÅ≠Ωâ±•πùï∏Åï»ÅÕÖ—–ÅÕÖµµï∏ÅâÖÕï…–Å√îÅ—•±ù©ïπùï±•úÅ•πôΩ…µÖÕ©Ω∏ÅΩ¥Å¡…Ωë’Õïπ–ÅΩúÅ¡…Ωë’≠—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»∏Å-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å•πùï∏ÅÖŸ—Ö±îÅµïêÅ≠©ïëï∏ÅâÖ¨Åëï——îÅµï…≠ïπÖŸπï–ÅΩúÅ≠Ö∏Å•≠≠îÅùÖ…Öπ—ï…îÅÖ–Å≠Ωâ±•πùï∏ÅÕ—ïµµï»Å§ÅÖ±±îÅ—•±ôï±±ï»ÉäLÅ¡Ö≠π•πùÕÕ”·……ï±ÕîÅï±±ï»Å—•±ù©ïπùï±•ùîÅÕ—Â…≠ï»Å≠Ö∏ÅôΩ»Åï≠Õïµ¡ï∞ÅÖŸŸ•≠î∏Å	ï≠…ïô–ÅÖ±±—•êÅµïêÅë•∏ÅΩ¡—•≠ï»Åï±±ï»ÅÕÂπÕ…ïÕï¡–ÅÖ–ÅÌïÕçÖ¡î°…ïÖ±}πÖµî•ÙÅôÖ≠—•Õ¨Åï»Å…•≠—•úÅï…Õ—Ö—π•πúÅôΩ»ÅÌïÕçÖ¡î°¡…•ŸÖ—ï}πÖµî•ÙÅõ·»Åë‘ÅâÂ——ï»∏(ÄÄΩë•ÿ¯((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅ	’—•≠≠ïπîÅÕΩ…—ï…ïÃÅï——ï»Å±ÖŸïÕ–Å¡…Ωë’≠—¡…•Ã∏ÅM≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅôΩ»Éî(ÄÄÄÅÕîÅΩúÅÕΩ…—ï…îÅï——ï»Å—Ω—Ö±¡…•ÃÄ°¡…Ωë’≠—¡…•ÃÄ¨Åô…Ö≠–§ÅôΩ»ÅÖπ—Ö±±ï–Åë‘Å°Ö»ÅŸÖ±ù–∏(ÄÄÄÅY§Å≠Ö∏ÅõîÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Å°Öπë±ï»ÅŸ•ÑÅ±ïπ≠ïπî∞Åµï∏Åëï–Å√ïŸ•…≠ï»ÅÖ±ë…§Å¡…•Õï∏Åë‘(ÄÄÄÅâï—Ö±ï»∏ÅIï≠≠ïõ·±ùï∏Åï»ÅÖ±±—•êÅâÖÕï…–Å√îÅ¡…•Ã∞ÅâΩ…—Õï—–Åô…ÑÅŸïêÅï≠ÕÖ≠–Å±•¨Å¡…•Ã(ÄÄÄÅµï±±Ω¥Å—ºÅ—•±â’ê∞Åëï»ÅŸ§Å≠Ö∏Å¡…•Ω…•—ï…îÅï∏ÅôΩ…°Öπë±ï»ÅŸ§Å°Ö»ÅÖŸ—Ö±îÅµïê∏ÅYÖ…ï»(ÄÄÄÅ’—ï∏Åâï≠…ïô—ï–Å±Öùï»Å≠Ö∏Å•≠≠îÅŸ•ππîÉ
≠±ÖŸïÕ—îÅ¡…•œ
Ï∞ÅΩúÅ°Ÿï…–Å—•±â’êÅŸ•Õï»Åªï»Åëï–(ÄÄÄÅÕ•Õ–Åâ±îÅ≠Ωπ—…Ω±±ï…–∏(ÄÄÄÅ-Ωπ—Ö≠—±•πÕï»ππºÅï»Åï∏Å’ÖŸ°ïπù•úÅ¡…•ÕÕÖµµïπ±•ùπ•πùÕ—©ïπïÕ—î∞Å•≠≠îÅï∏(ÄÄÄÅôΩ…°Öπë±ï»∞ÅΩúÅ°Ö»Å•πùï∏ÅÖŸ—Ö±îÅµïêÅ≠©ïëï∏ÅâÖ¨Åëï——îÅµï…≠ïπÖŸπï–∏(ÄÄΩ¿¯(ÄÅÌÖ•}Õ’µµÖ…Â}°—µ±Ù(ÄÅÌ¡…Ωë’ç—}ôÖ≈}°—µ±Ù(ÄÅÌ5Q!==1=e}!Q51Ù(ÄÅÌ…ï±Ö—ïë}°—µ±Ù(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}ôÖµ•±Â}¡Öùî†(ÄÄÄÅôÖµ•±Â}πÖµîËÅÕ—»∞(ÄÄÄÅôÖµ•±Â}Õ±’úËÅÕ—»∞(ÄÄÄÅµïµâï…ÃËÅ±•Õ—më•ç—t∞(ÄÄÄÅçÖ—ïùΩ…•ïÃËÅë•ç–∞(ÄÄÄÅç°Ö•∏ËÅÕ—»ÅÅ9ΩπîÄÙÅ9Ωπî∞(ÄÄÄÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî∞(ÄÄÄÅ¡…•çï}°•Õ—Ω…‰ËÅë•ç–ÅÅ9ΩπîÄÙÅ9Ωπî∞(§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâA…Ωë’≠—Õï…•îµÕ•ëîÄ†ΩÕï…•îΩÌÕ±’ùÙº§Ä¥¥ÅÕÖµ±ï»ÅÕõô…•Õ¨Ω—Ω…•Õ¨º(ÄÄÄÅµ’±—•ôΩ≠Ö∞ΩaHµŸÖ…•Öπ—ïπîÅÖÿÅM55Å±•πÕïëïÕ•ù∏Å√îÉ•∏ÅÕ•ëî∞ÅµïêÅï∏Åï≠—î(ÄÄÄÅÕÖµµïπ±•ùπ•πùÕ—Öâï±∞Ä°•≠≠îÅâÖ…îÅï∏Å±ïπ≠ï±•Õ—î§∏Å1Öù–Å—•∞Ä»¿»ÿ¥¿‰¥¿‘(ÄÄÄÅï——ï»ÅÖ–Å±ïπÕ¡…•çï»ππºÅâ±îÅΩâÕï…Ÿï…–ÉîÅõîÅï–Åï≠Õ—…ÑÅœ·≠ï—…ïôòÅπï——Ω¡¿(ÄÄÄÅô…ÑÅëïππîÅÕ•ëï—Â¡ï∏ÅôΩ»ÄâïÖÕÂŸ•Õ•Ω∏ÅŸ•—…ïÑàÄ¥¥ÅÕîÅ¡…Ωë’ç—}ôÖµ•±•ïÃπ©ÕΩ∏(ÄÄÄÅôΩ»Å≠’…ï…•πùÕ¡…•πÕ•¡¡ï–Ä°µÖπ’ï±–∞Å%--ÅÖ’—ºµ’—±ïëï–Åô…ÑÅ•êµ∑·πÕ—ï»§∏((ÄÄÄÅµïµâï…ÃËÅ±•Õ—îÅÖÿÅÏâë•Õ¡±ÖÂ}πÖµîà∞Äâ°…ïòà∞Äâ¡…Ωë’ç–âÙÄ¥¥Äâ¡…Ωë’ç–àÅï»(ÄÄÄÅ11Q%Åëï–Åï≠—îÅ¡…Ωë’≠—ï–Ä°ôΩ»Å¡…•ÃΩÕ¡ïåµôÖ≠—Ñ§∞Äâë•Õ¡±ÖÂ}πÖµîàºâ°…ïòà(ÄÄÄÅï»Åïπ—ï∏Åëï–Åï≠—îÅ¡…Ωë’≠—πÖŸπï–Ä°ç°Ö•∏ı9Ωπî§Åï±±ï»Åï–Å¡…•ŸÖ—î(ÄÄÄÅ±Öâï∞µπÖŸ∏Ω±ïπ≠îÄ°ç°Ö•∏ÅÕÖ—–§Ä¥¥ÅÕÖµµîÄâŸ•ÃÅ’πëï»ÅÖππï–ÅπÖŸ∏∞Åâ…’¨Åï≠—î(ÄÄÄÅ—•±â’êàµ¡…•πÕ•¡¿ÅÕΩ¥Å…ïπëï…}¡…•ŸÖ—ï}±Öâï±}¡Öùî†§∏(ÄÄÄÅç°Ö•∏ËÅÕÖ—–Å≠’∏ÅôΩ»Å¡…•ŸÖ—îÅ±Öâï∞µŸÖ…•Öπ—ï∏ÅÖÿÅï∏ÅôÖµ•±•îÄ°òπï≠Ã∏(ÄÄÄÄâM¡ïçÕÖŸï…Ãà§Ä¥¥Åïπë…ï»Å—•——ï∞ΩôΩ…≠±Ö…•πùÕâΩ≠Ã∞Å•≠≠îÅÕï±ŸîÅ—Öâï±±ï∏∏ààà(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§((ÄÄÄÅ…Ω›ÃÄÙÅmt(ÄÄÄÅôΩ»Å¥Å•∏Åµïµâï…ÃË(ÄÄÄÄÄÄÄÅ¡…Ωë’ç–ÄÙÅµlâ¡…Ωë’ç–ât(ÄÄÄÄÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅï±•ù•â±îÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÄÄÄÄÅâïÕ–ÄÙÅµ•∏°ï±•ù•â±î∞Å≠ï‰ı±ÖµâëÑÅºËÄ°Ωlâ¡…•çï}πΩ¨ât∞ÅΩlâ—Ω—Ö∞ât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄÄÄÄÅ¡Öç¨ÄÙÅ}¡Öç≠}Õ•Èï}ô…Ωµ}•ê°¡…Ωë’ç—lâ•êât§(ÄÄÄÄÄÄÄÅÕ¡ïçÃÄÙÅÌ±Öâï∞ËÅŸÖ±’îÅôΩ»Å±Öâï∞∞ÅŸÖ±’îÅ•∏Å¡…Ωë’ç–πùï–†âÕ¡ïçÃà∞Åmt•Ù(ÄÄÄÄÄÄÄÅ…Ω›ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ•µÖùï}’…∞àËÅ}¡…•ŸÖ—ï}±Öâï±}•µÖùî°µlâ±Öâï∞ât§Å•òÅ¥πùï–†â±Öâï∞à§ÅÖπêÅç°Ö•∏ÄÙÙÄâ	…•±±ï±ÖπêàÅï±ÕîÅ}¡…Ωë’ç—}•µÖùî°¡…Ωë’ç–§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâë•Õ¡±ÖÂ}πÖµîàËÅµlâë•Õ¡±ÖÂ}πÖµîât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ°…ïòàËÅµlâ°…ïòât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡…Ωë’ç–àËÅ¡…Ωë’ç–∞(ÄÄÄÄÄÄÄÄÄÄÄÄââïÕ–àËÅâïÕ–∞(ÄÄÄÄÄÄÄÄÄÄÄÄâï±•ù•â±îàËÅï±•ù•â±î∞(ÄÄÄÄÄÄÄÄÄÄÄÄâπ}Ωôôï…ÃàËÅ±ï∏°ï±•ù•â±î§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡Öç≠}Õ•ÈîàËÅ¡Öç≠l≈tÅ•òÅ¡Öç¨Åï±ÕîÅ9Ωπî∞(ÄÄÄÄÄÄÄÄÄÄÄÄâçÖ—ïùΩ…Â}Õ±’úàËÅ¡…Ωë’ç—lâçÖ—ïùΩ…Â}Õ±’úât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâçÖ—ïùΩ…Â}±Öâï∞àËÅçÖ—ïùΩ…•ïÃπùï–°¡…Ωë’ç—lâçÖ—ïùΩ…Â}Õ±’úât∞ÅÌÙ§πùï–†â±Öâï∞à∞Äàà§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÕ¡ïçÃàËÅÕ¡ïçÃ∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ›åàËÅ}¡Ö…Õï}Õ¡ïç}π’µâï…Ã°Õ¡ïçÃπùï–†âYÖππ•ππ°Ω±êà§§∞(ÄÄÄÄÄÄÄÄÄÄÄÄââåàËÅ}¡Ö…Õï}Õ¡ïç}π’µâï…Ã°Õ¡ïçÃπùï–†â	ÖÕ•Õ≠’…Ÿîà§§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµÖ—ï…•Ö∞àËÅÕ¡ïçÃπùï–†â5Ö—ï…•Ö±îà§∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅÕ°Ω›}›åÄÙÅÖπ‰°…lâ›åâtÅôΩ»Å»Å•∏Å…Ω›Ã§(ÄÄÄÅÕ°Ω›}âåÄÙÅÖπ‰°…lââåâtÅôΩ»Å»Å•∏Å…Ω›Ã§(ÄÄÄÅÕ°Ω›}µÖ—ï…•Ö∞ÄÙÅÖπ‰°…lâµÖ—ï…•Ö∞âtÅôΩ»Å»Å•∏Å…Ω›Ã§((ÄÄÄÅµÖπ’ôÖç—’…ï…}Õ±’úÄÙÅ	I9}Q=}59UQUIHπùï–°…Ω›Õl¡ulâ¡…Ωë’ç–âulââ…Öπë}Õ±’úât§Å•òÅ…Ω›ÃÅï±ÕîÅ9Ωπî(ÄÄÄÅµÖπ’ôÖç—’…ï…}πÖµîÄÙÅ59UQUIIMmµÖπ’ôÖç—’…ï…}Õ±’ùulâπÖµîâtÅ•òÅµÖπ’ôÖç—’…ï…}Õ±’úÅï±ÕîÅ9Ωπî((ÄÄÄÅ¡…•çïÃÄÙÅm…lââïÕ–âulâ¡…•çï}πΩ¨âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lââïÕ–âut(ÄÄÄÅ±Ω›ïÕ—}…Ω‹ÄÙÅµ•∏†°»ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lââïÕ–ât§∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lââïÕ–âulâ¡…•çï}πΩ¨ât∞ÅëïôÖ’±–ı9Ωπî§((ÄÄÄÄåÄâ•π∏Åë•∏ÅŸÖ…•Öπ–àÄ°±ïπùï»Åπïëî§Å—…ïπùï»Å8Åï—•≠ï—–Å¡ï»Åâï°ΩÿΩ≠Ö—ïùΩ…§Ä¥¥(ÄÄÄÄåÅëï±–Å°ï»ÅÕ•ëï∏ÅÅ—Öâï±±ï∏ÅΩúÅ≠Ω…—ïπîÅâ…’≠ï»Åëï∏ÅÕÖµµîÅµÖ¡¡•πùï∏∏(ÄÄÄÅ}YI%9Q}9}1	1LÄÙÅÏ(ÄÄÄÄÄÄÄÄâµÖπïëÕ±•πÕï»àËÄâYÖπ±•úÅÕÂπÕ≠Ω……ï≠Õ©Ω∏à∞ÄâëÖùÕ±•πÕï»àËÄâYÖπ±•úÅÕÂπÕ≠Ω……ï≠Õ©Ω∏à∞(ÄÄÄÄÄÄÄÄâ—Ω…•Õ≠îµ±•πÕï»àËÄâÕ—•ùµÖ—•Õµîà∞Äâµ’±—•ôΩ≠Ö±îµ±•πÕï»àËÄâ±ëï…ÕÕÂ∏ÄºÅµ’±—•ôΩ≠Ö∞à∞(ÄÄÄÄÄÄÄÄâôÖ…ùïëîµ±•πÕï»àËÄâÖ…ùï≠Ω……ï≠Õ©Ω∏à∞(ÄÄÄÅÙ(ÄÄÄÅâÂ}çÖ—ïùΩ…‰ËÅë•ç—mÕ—»∞Å±•Õ—më•ç—utÄÙÅÌÙ(ÄÄÄÅôΩ»Å»Å•∏Å…Ω›ÃË(ÄÄÄÄÄÄÄÅâÂ}çÖ—ïùΩ…‰πÕï—ëïôÖ’±–°…lâçÖ—ïùΩ…Â}Õ±’úât∞Åmt§πÖ¡¡ïπê°»§((ÄÄÄÄåÅMÖµµïπ±•ùπ•πùÕ—Öâï±±ï∏ÅŸ•Õï»ÅªîÉ%8ÅIÅAHÅ	!=XÄ°•≠≠îÅ¡ï»Å¡Ö≠π•πùÕÕ”·……ï±Õî(ÄÄÄÄåÄ¥¥Ä»¿»ÿ¥¿‰¥»‹∞Å-Ö§ÅÕ•—–É·πÕ≠îÅΩ¥Äâï≠—îÅëÖ—ÑÅΩúÅ—Ö±∞ÅŸ§Å°Ö»∞ÅôΩ»ÅïπëÑÅµï»(ÄÄÄÄåÅ…ï±ïŸÖπ–Å•πôºà§∞ÅµïêÅ•Öµï—ï»ÅΩúÅΩe0Ωa%LÅÕΩ¥ÅπÂîÅ≠Ω±Ωππï»Å’—±ïëï–Åô…Ñ(ÄÄÄÄåÅëîÅôÖ≠—•Õ≠îÅÕ¡ïçÃµôï±—ïπîÄ°•≠≠îÅÖ±±îÅ¡…Ωë’≠—ï»Å°Ö»Åë•ÕÕîÄ¥¥ÅÕî(ÄÄÄÄåÅ¡…Ωë’ç—Õ}µï—Ñπ©ÕΩ∏ÅÕ•∏Å…ïï±±îÅôï±—ëï≠π•πú∞Åëë•Õ©Ω∏ΩUXµô•±—ï»Åï»ÅÕ©ï±ëπî§∏(ÄÄÄÄåÅ	Ωë•Öµï—ï»ΩµÖ—ï…•Ö±îÅÖπ—ÖÃÅ±•≠–Å√îÅ—Ÿï…ÃÅÖÿÅ¡Ö≠π•πùÕÕ”·……ï±Õï»Å%999=H(ÄÄÄÄåÅÕÖµµîÅâï°ΩÿÄ°ÕÖµµîÅôÂÕ•Õ≠îÅ±•πÕî∞ÅâÖ…îÅ’±•≠–ÅÖπ—Ö±∞Å§ÅïÕ≠ï∏§Ä¥¥Å…ï¡…ïÕïπ—Öπ–¥(ÄÄÄÄåÅ…Öëï∏Ä°µ•πÕ—îÅ¡Ö≠π•πú§ÅÕ•πîÅÕ¡ïåµŸï…ë•ï»Åâ…’≠ïÃÅëï…ôΩ»ÅôΩ»Å°ï±îÅù…’¡¡ï∏∏(ÄÄÄÅ—Öâ±ï}ù…Ω’¡ÃÄÙÅmt(ÄÄÄÅôΩ»ÅçÖ—}Õ±’úÅ•∏Å±•Õ–°Q=Ie}	§Ä¨ÅmÃÅôΩ»ÅÃÅ•∏ÅâÂ}çÖ—ïùΩ…‰Å•òÅÃÅπΩ–Å•∏ÅQ=Ie}	tË(ÄÄÄÄÄÄÄÅù…Ω’¿ÄÙÅâÂ}çÖ—ïùΩ…‰πùï–°çÖ—}Õ±’ú§(ÄÄÄÄÄÄÄÅ•òÅπΩ–Åù…Ω’¿Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçΩπ—•π’î(ÄÄÄÄÄÄÄÅ…ï¿ÄÙÅµ•∏°ù…Ω’¿∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ¡Öç≠}Õ•ÈîâtÅΩ»Ä¿§(ÄÄÄÄÄÄÄÅù…Ω’¡}¡Öç≠ÃÄÙÅÕΩ…—ïê°Ì…lâ¡Öç≠}Õ•ÈîâtÅôΩ»Å»Å•∏Åù…Ω’¿Å•òÅ…lâ¡Öç≠}Õ•ÈîâuÙ§(ÄÄÄÄÄÄÄÅù…Ω’¡}¡…•çïÃÄÙÅm…lââïÕ–âulâ¡…•çï}πΩ¨âtÅôΩ»Å»Å•∏Åù…Ω’¿Å•òÅ…lââïÕ–âut(ÄÄÄÄÄÄÄÅ°ÖÕ}çÂ∞ÄÙÅÖπ‰°…lâÕ¡ïçÃâtπùï–†âMÂ±•πëï»à§ÅΩ»Å…lâÕ¡ïçÃâtπùï–†â≠Õîà§ÅôΩ»Å»Å•∏Åù…Ω’¿§(ÄÄÄÄÄÄÄÅ°ÖÕ}ÖëêÄÙÅÖπ‰°…lâÕ¡ïçÃâtπùï–†âëë•Õ©Ω∏à§ÅôΩ»Å»Å•∏Åù…Ω’¿§(ÄÄÄÄÄÄÄÅ—Öâ±ï}ù…Ω’¡ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâπÖµîàËÅ…îπÕ’à°»âqÃ≠qê¨µ¡Öç¨êà∞Äàà∞Å…ï¡lâë•Õ¡±ÖÂ}πÖµîât§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ°…ïòàËÅ…ï¡lâ°…ïòât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡…Ωë’ç–àËÅ…ï¡lâ¡…Ωë’ç–ât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ•µÖùï}’…∞àËÅ…ï¡lâ•µÖùï}’…∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâπïïë}±Öâï∞àËÅ}YI%9Q}9}1	1Lπùï–°çÖ—}Õ±’ú∞Å…ï¡lâçÖ—ïùΩ…Â}±Öâï∞ât§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâµÖ—ï…•Ö∞àËÅ…ï¡lâµÖ—ï…•Ö∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ›åàËÅ…ï¡lâ›åât∞(ÄÄÄÄÄÄÄÄÄÄÄÄââåàËÅ…ï¡lââåât∞(ÄÄÄÄÄÄÄÄÄÄÄÄâë•Öµï—ï»àËÅ}¡Ö…Õï}Õ¡ïç}π’µâï…Ã°…ï¡lâÕ¡ïçÃâtπùï–†â•Öµï—ï»à§§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡Ω›ï…}ë•¥àËÄâe0Ωa%LàÅ•òÅ°ÖÕ}çÂ∞Åï±ÕîÄ†âàÅ•òÅ°ÖÕ}ÖëêÅï±ÕîÄãäLà§∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡Öç≠Õ}—·–àËÄàºàπ©Ω•∏°Õ—»°∏§ÅôΩ»Å∏Å•∏Åù…Ω’¡}¡Öç≠Ã§Å•òÅù…Ω’¡}¡Öç≠ÃÅï±ÕîÄãäLà∞(ÄÄÄÄÄÄÄÄÄÄÄÄâ¡…•çîàËÅµ•∏°ù…Ω’¡}¡…•çïÃ§Å•òÅù…Ω’¡}¡…•çïÃÅï±ÕîÅ9Ωπî∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅÕ°Ω›}ë•Öµï—ï»ÄÙÅÖπ‰°ùlâë•Öµï—ï»âtÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡Ã§(ÄÄÄÅÕ°Ω›}¡Ω›ï…}ë•¥ÄÙÅÖπ‰°ùlâ¡Ω›ï…}ë•¥âtÄÑÙÄãäLàÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡Ã§((ÄÄÄÅëïòÅ—Öâ±ï}…Ω‹°úËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ›ç}—·–ÄÙÄàÄºÄàπ©Ω•∏°òâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÄîàÅôΩ»ÅÿÅ•∏Åùlâ›åât§Å•òÅùlâ›åâtÅï±ÕîÄãäLà(ÄÄÄÄÄÄÄÅâç}—·–ÄÙÄàÄºÄàπ©Ω•∏°òâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÅµ¥àÅôΩ»ÅÿÅ•∏Åùlââåât§Å•òÅùlââåâtÅï±ÕîÄãäLà(ÄÄÄÄÄÄÄÅë•Ö}—·–ÄÙÄàÄºÄàπ©Ω•∏°òâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÅµ¥àÅôΩ»ÅÿÅ•∏Åùlâë•Öµï—ï»ât§Å•òÅùlâë•Öµï—ï»âtÅï±ÕîÄãäLà(ÄÄÄÄÄÄÄÅµÖ—ï…•Ö±}—·–ÄÙÅïÕçÖ¡î°ùlâµÖ—ï…•Ö∞ât§Å•òÅùlâµÖ—ï…•Ö∞âtÅï±ÕîÄãäLà(ÄÄÄÄÄÄÄÅ¡…•çï}—·–ÄÙÅ}ôµ—}≠»°ùlâ¡…•çîât§Å•òÅùlâ¡…•çîâtÅï±ÕîÄâ%πùï∏Å¡…•Ãà(ÄÄÄÄÄÄÄÅçï±±ÃÄÙÅòúúúÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘ÌïÕçÖ¡î°ùlâπïïë}±Öâï∞ât•ÙΩ—ê¯úúú(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}µÖ—ï…•Ö∞Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçï±±ÃÄ¨ÙÅòùq∏ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘ÌµÖ—ï…•Ö±}—·—ÙΩ—ê¯ú(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}›åË(ÄÄÄÄÄÄÄÄÄÄÄÅçï±±ÃÄ¨ÙÅòùq∏ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘Ì›ç}—·—ÙΩ—ê¯ú(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}âåË(ÄÄÄÄÄÄÄÄÄÄÄÅçï±±ÃÄ¨ÙÅòùq∏ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘Ìâç}—·—ÙΩ—ê¯ú(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}ë•Öµï—ï»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçï±±ÃÄ¨ÙÅòùq∏ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘Ìë•Ö}—·—ÙΩ—ê¯ú(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}¡Ω›ï…}ë•¥Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçï±±ÃÄ¨ÙÅòùq∏ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘ÌïÕçÖ¡î°ùlâ¡Ω›ï…}ë•¥ât•ÙΩ—ê¯ú(ÄÄÄÄÄÄÄÅ…Ω›}•µúÄÙÅùlâ•µÖùï}’…∞ât(ÄÄÄÄÄÄÄÅ—°’µâ}°—µ∞ÄÙÅòúÒ•µúÅç±ÖÕÃÙâÕ¡ïåµ…Ω‹µ—°’µààÅÕ…åÙâÌïÕçÖ¡î°…Ω›}•µú•ÙàÅÖ±–ÙàâÌ}ë•µ}Ö——…Ã°…Ω›}•µú•ÙÅ±ΩÖë•πúÙâ±ÖÈ‰à¯úÅ•òÅ…Ω›}•µúÅï±ÕîÄúú(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúúúÒ—»¯(ÄÄÄÄÒ—†ÅÕçΩ¡îÙâ…Ω‹àÅç±ÖÕÃÙâÕ¡ïåµ±Öâï∞à¯ÒÑÅ°…ïòÙâÌïÕçÖ¡î°ùlâ°…ïòât•Ùà˘Ì—°’µâ}°—µ±ıÌïÕçÖ¡î°ùlâπÖµîât•ÙΩÑ¯Ω—†¯(ÄÄÄÅÌçï±±ÕÙ(ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘ÌïÕçÖ¡î°ùlâ¡Öç≠Õ}—·–ât•ÙΩ—ê¯(ÄÄÄÄÒ—êÅç±ÖÕÃÙâÕ¡ïåµŸÖ±’îà˘Ì¡…•çï}—·—ÙΩ—ê¯(ÄÄΩ—»¯úúú((ÄÄÄÅ—Öâ±ï}°ïÖëï…}ï·—…ÑÄÙÄàà(ÄÄÄÅ•òÅÕ°Ω›}µÖ—ï…•Ö∞Ë(ÄÄÄÄÄÄÄÅ—Öâ±ï}°ïÖëï…}ï·—…ÑÄ¨ÙÄàÒ—†˘5Ö—ï…•Ö±îΩ—†¯à(ÄÄÄÅ•òÅÕ°Ω›}›åË(ÄÄÄÄÄÄÄÅ—Öâ±ï}°ïÖëï…}ï·—…ÑÄ¨ÙÄàÒ—†˘YÖππ•ππ°Ω±êΩ—†¯à(ÄÄÄÅ•òÅÕ°Ω›}âåË(ÄÄÄÄÄÄÄÅ—Öâ±ï}°ïÖëï…}ï·—…ÑÄ¨ÙÄàÒ—†˘	Ä°µ¥§Ω—†¯à(ÄÄÄÅ•òÅÕ°Ω›}ë•Öµï—ï»Ë(ÄÄÄÄÄÄÄÅ—Öâ±ï}°ïÖëï…}ï·—…ÑÄ¨ÙÄàÒ—†˘•Öµï—ï»Ä°µ¥§Ω—†¯à(ÄÄÄÅ•òÅÕ°Ω›}¡Ω›ï…}ë•¥Ë(ÄÄÄÄÄÄÄÅ—Öâ±ï}°ïÖëï…}ï·—…ÑÄ¨ÙÄàÒ—†˘Ωe0Ωa%LΩ—†¯à((ÄÄÄÅçΩµ¡Ö…•ÕΩπ}—Öâ±îÄÙÅòúúúÒë•ÿÅÕ—Â±îÙâΩŸï…ô±Ω‹µ‡ÈÖ’—ºÏà¯(ÄÄÒ—Öâ±îÅç±ÖÕÃÙâÕ¡ïåµ—Öâ±îà¯(ÄÄÄÄÒ—°ïÖê¯(ÄÄÄÄÄÄÒ—»¯Ò—†˘YÖ…•Öπ–Ω—†¯Ò—†˘Ω»Ω—†˘Ì—Öâ±ï}°ïÖëï…}ï·—…ÖÙÒ—†˘AÖ≠π•πùï»Ω—†¯Ò—†˘…ÑÅ¡…•ÃÄ°’—ï∏Åô…Ö≠–§Ω—†¯Ω—»¯(ÄÄÄÄΩ—°ïÖê¯(ÄÄÄÄÒ—âΩë‰¯(ÄÄÄÄÄÅÏààπ©Ω•∏°—Öâ±ï}…Ω‹°ú§ÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡Ã•Ù(ÄÄÄÄΩ—âΩë‰¯(ÄÄΩ—Öâ±î¯(Ωë•ÿ¯úúú((ÄÄÄÄåÄâ±±îÅ¡…Ωë’≠—ï»Å§Å`µÕï…•ï∏àÄ¥¥Åù©ïπâ…’≠ï»Å8ÅM55Å≠Ω…–µ≠Ωµ¡Ωπïπ—ï∏ÅÕΩ¥(ÄÄÄÄåÅ≠Ö—ïùΩ…§¥Ωµï…≠î¥Ω—•±âï£·»µÕ•ëïπîÅÖ±±ï…ïëîÅâ…’≠ï»Ä°}…ïπëï…}¡…Ωë’ç—}—•±î†§§∞(ÄÄÄÄåÅ%--Åï–ÅπÂ—–Å≠Ω…—ëïÕ•ù∏Ä¥¥Å-Ö§ÅÕ•—–Åï≠Õ¡±•Õ•——îÉ·πÕ≠îÄ»¿»ÿ¥¿‰¥»‹ËÄâëîÅÕΩ¥(ÄÄÄÄåÅŸ§Åâ…’≠ï»ÅÕï±ÿÅΩúÅ°Ö»Å§ÅëÖúà∞Å•≠≠îÅµΩç¨µëïÕ•ùπï–∏(ÄÄÄÅëïòÅ¡…Ωë’ç—}—•±î°»ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ…ï—’…∏Å}…ïπëï…}¡…Ωë’ç—}—•±î†(ÄÄÄÄÄÄÄÄÄÄÄÅ°…ïòı…lâ°…ïòât∞ÅπÖµîı…lâë•Õ¡±ÖÂ}πÖµîât∞Å•µÖùï}’…∞ı…lâ•µÖùï}’…∞ât∞(ÄÄÄÄÄÄÄÄÄÄÄÅôÖ±±âÖç≠}•π•—•Ö±Ãı…lâ¡…Ωë’ç–âulââ…Öπë}±Öâï∞âulË…tπ’¡¡ï»†§∞(ÄÄÄÄÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ı…lâçÖ—ïùΩ…Â}±Öâï∞ât∞ÅÕïçΩπëÖ…Â}±•πï}°—µ∞Ùàà∞(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω›ïÕ–ı…lââïÕ–ât∞ÅΩ—°ï…}çΩ’π–ıµÖ‡†¿∞Å…lâπ}Ωôôï…ÃâtÄ¥Äƒ§∞(ÄÄÄÄÄÄÄÄÄÄÄÅçΩµ¡Ö…•ÕΩπ}Ωôôï…Ãı…ïçΩπç•±ï}¡…Ωë’ç–°…lâ¡…Ωë’ç–âulâΩôôï…Ãât∞ÅπΩ‹§∞(ÄÄÄÄÄÄÄÄ§(ÄÄÄÅÖ±±}¡…Ωë’ç—Õ}°—µ∞ÄÙÅòúúúÒ†»˘±±îÅ¡…Ωë’≠—ï»Å§ÅÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙµÕï…•ï∏Ω†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…Ωë’ç–µ—•±îµù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°¡…Ωë’ç—}—•±î°»§ÅôΩ»Å»Å•∏Å…Ω›Ã•Ù(ÄÄΩë•ÿ¯úúúÅ•òÅ±ï∏°…Ω›Ã§Ä¯ÄƒÅï±ÕîÄàà((ÄÄÄÄåÄâIï±ïŸÖπ—îÅù’•ëï»àÄ¥¥Åâ•±ëï≠Ω…–Å§ÅÕ—ïëï–ÅôΩ»ÅëîÅ…ïπîÅ•≠Ω∏µ≠Ω…—ïπî(ÄÄÄÄåÄ°…ïπëï…}ù’•ëï}—•±î§∞Åï——ï»Å-Ö§ÅÕ•—–É·πÕ≠îÄ»¿»ÿ¥¿‰¥»‹ÅΩ¥ÅÖ–Å•≠Ω∏µâΩ≠Õïπî(ÄÄÄÄåÅŸÖ»Å≠©ïëï±•ùî∏Å’•ëïπîÅ°Ö»Å•πùï∏ÅïùπîÅôΩ—ºÅ§ÅëÖ—ÖµΩëï±±ï∏Ä¥¥Åù©ïπâ…’≠ï»(ÄÄÄÄåÅëï…ôΩ»Å≠Ö—ïùΩ…•≠Ω…—ïπïÃÅïùπîÅ¡ÖÕ—ï±±â•±ëï»Ä°ÕÖµµîÅô•±ï»ÅÕΩ¥Äâ•π∏Åë•∏(ÄÄÄÄåÅŸÖ…•Öπ–àÅΩŸï»§∞Å%--ÅÕÖµµîÅ—ïµÑΩ—ï≠Õ–ÅÕΩ¥ÅÕï±ŸîÅù’•ëï∏Åª·ëŸïπë•ùŸ•Ã∞(ÄÄÄÄåÅµï∏Å…ïï±±îÅâ•±ëï»ÅŸ§ÅÖ±±ï…ïëîÅï•ï»Ω°Ö»Å±•ÕïπÃÅ—•∞∞ÅŸÖ±ù–ÅôΩ»Åï–ÅŸ•ÕÕ–(ÄÄÄÄåÅ—ïµÖ—•Õ¨ÅÕ±ï≠—Õ≠Ö¿Åëï»Åëï–Åï»ÅπÖ—’…±•úÄ°ÖÕ—•ùµÖ—•Õµîµù’•ëîÄ¥¯Å—Ω…•Õ≠î¥(ÄÄÄÄåÅâ•±ëï–∞ÅΩÕÿ∏§Åô…ïµôΩ»Å°ï±–Å—•±ôï±ë•ú∏(ÄÄÄÅ}U%}%5ÄÙÅÏ(ÄÄÄÄÄÄÄÄâ°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»àËÄâëÖúà∞Äâ≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•ÕµîàËÄâ—Ω…•Õ≠îà∞(ÄÄÄÄÄÄÄÄâµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»àËÄâµ’±—•ôΩ≠Ö±îà∞ÄâµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»àËÄâµÖÖπïêà∞(ÄÄÄÄÄÄÄÄâ°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»àËÄâôÖ…ùïëîà∞(ÄÄÄÅÙ(ÄÄÄÅ…ï±ïŸÖπ—}ù’•ëï}Õ±’ùÃÄÙÅlâ°ŸΩ…ëÖ∏µâ…’≠îµ≠Ωπ—Ö≠—±•πÕï»ât(ÄÄÄÅ•òÅÖπ‰°ùlâ¡Ω›ï…}ë•¥âtÄÙÙÄâe0Ωa%LàÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡Ã§Ë(ÄÄÄÄÄÄÄÅ…ï±ïŸÖπ—}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†â≠Ωπ—Ö≠—±•πÕï»µµïêµÖÕ—•ùµÖ—•Õµîà§(ÄÄÄÅï±•òÅÖπ‰°ùlâ¡Ω›ï…}ë•¥âtÄÙÙÄâàÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡Ã§Ë(ÄÄÄÄÄÄÄÅ…ï±ïŸÖπ—}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†âµ’±—•ôΩ≠Ö±îµ≠Ωπ—Ö≠—±•πÕï»à§(ÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÅ…ï±ïŸÖπ—}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†âµÖπïëÕ±•πÕï»µŸÃµëÖùÕ±•πÕï»à§(ÄÄÄÅ…ï±ïŸÖπ—}ù’•ëï}Õ±’ùÃπÖ¡¡ïπê†â°ŸΩ…ëÖ∏µŸï±ùîµ≠Ωπ—Ö≠—±•πÕï»à§((ÄÄÄÅëïòÅù’•ëï}¡°Ω—Ω}çÖ…ê°Õ±’úËÅÕ—»§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅúÄÙÅU%}=9Q9QmÕ±’ùt(ÄÄÄÄÄÄÄÅâúÄÙÅ}U%}%5πùï–°Õ±’ú∞ÄâëÖúà§(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòúúúÒÑÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êàÅ°…ïòÙàΩù’•ëîΩÌïÕçÖ¡î°Õ±’ú•Ùºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµ•µÖùîà¯(ÄÄÄÄÄÄÒ•µúÅÕ…åÙàΩÕ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâúµÌâùÙ¥Ã»¿π›ïâ¿àÅÖ±–ÙààÅ›•ë—†ÙàÃ»¿àÅ°ï•ù°–Ùàƒ–ÃàÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµâΩë‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµ—•—±îà˘ÌïÕçÖ¡î°ùlâ—•—±îât•ÙΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµçÖ…êµ±•π¨à˘1ïÃÅù’•ëï∏ÉäHΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩÑ¯úúú((ÄÄÄÅù’•ëïÕ}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙâÕï…•îµù’•ëïÃà¯(ÄÄÄÄÒ†»˘Iï±ïŸÖπ—îÅù’•ëï»Ω†»¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâù’•ëîµ¡°Ω—ºµù…•êà¯(ÄÄÄÄÄÅÏààπ©Ω•∏°ù’•ëï}¡°Ω—Ω}çÖ…ê°Õ±’ú§ÅôΩ»ÅÕ±’úÅ•∏Å…ï±ïŸÖπ—}ù’•ëï}Õ±’ùÃÅ•òÅÕ±’úÅ•∏ÅU%}=9Q9P•Ù(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÅ¡Öç≠}Õ•ÈïÃΩµÖ—ï…•Ö±Õ}¡…ïÕïπ–Åâ…’≠ïÃÅô±ï…îÅÕ—ïëï»Å±ïπùï»ÅπïêÄ°Õ—Ö–µ¡•±±ï»∞(ÄÄÄÄåÄâ-Ω…–ÅΩ¥Å`àÅΩÕÿ∏§Ä¥¥ÅÕï±ŸîÅDµï∏Åï»Åô±Â——ï–Å—•∞Åï∏Å…ïùï±µΩ—Ω»Å±ïπùï»(ÄÄÄÄåÅπïêÅ§Åô’π≠Õ©Ωπï∏Ä°ÕîÅ≠Ωµµïπ—Ö…ï∏ÅŸïêÅôÖ≈}¡…Ωë’≠–ΩôÖ≈}Õ¡ïåΩôÖ≈}¡…•Ã§∞(ÄÄÄÄåÅÕ•ëï∏Åëï∏Å—…ïπùï»ÅëÖ—ÑÄ°’Ÿ}ŸÖ±’ïÃ∞Å›ç}ŸÖ±’ïÕ}Õ—Ö–∞Å—Öâ±ï}ù…Ω’¡Ãú(ÄÄÄÄåÅ¡Ω›ï…}ë•¥ÅΩÕÿ∏§ÅÕΩ¥Åõ·…Õ–Åô•ππïÃÅëï»∏(ÄÄÄÅ¡Öç≠}Õ•ÈïÃÄÙÅÕΩ…—ïê°Ì…lâ¡Öç≠}Õ•ÈîâtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâ¡Öç≠}Õ•ÈîâuÙ§(ÄÄÄÅµÖ—ï…•Ö±Õ}¡…ïÕïπ–ÄÙÅÌ…lâµÖ—ï…•Ö∞âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâµÖ—ï…•Ö∞âuÙ((ÄÄÄÅµÖ—ï…•Ö±}Õïπ—ïπçîÄÙÅòúÅ§ÅÌ…Ω›Õl¡ulâµÖ—ï…•Ö∞âuÙúÅ•òÅÕ°Ω›}µÖ—ï…•Ö∞ÅÖπêÅ…Ω›Õl¡ulâµÖ—ï…•Ö∞âtÅï±ÕîÄàà(ÄÄÄÅµÖπ’ôÖç—’…ï…}Õïπ—ïπçîÄÙÅòúÅô…ÑÅÌïÕçÖ¡î°µÖπ’ôÖç—’…ï…}πÖµî•ÙúÅ•òÅµÖπ’ôÖç—’…ï…}πÖµîÅï±ÕîÄàà(ÄÄÄÅ•π—…ºÄÙÄ†(ÄÄÄÄÄÄÄÅòúÒ¿˘ÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙÅï»Åï∏Å±•πÕïÕï…•ïÌµÖπ’ôÖç—’…ï…}Õïπ—ïπçïıÌµÖ—ï…•Ö±}Õïπ—ïπçïÙÅÕΩ¥Åô•ππïÃÅ§Åô±ï…îÄú(ÄÄÄÄÄÄÄÅòùŸÖ…•Öπ—ï»Ä¥¥ÅÕõô…•Õ¨∞ÅΩúÅëï»Åëï–Åô•ππïÃËÅ—Ω…•Õ¨Ä°ÖÕ—•ùµÖ—•Õµî§ÅΩúΩï±±ï»Åµ’±—•ôΩ≠Ö∞Ä°Ö±ëï…ÕÕÂ∏§∏Äú(ÄÄÄÄÄÄÄÅòù…’ππµÖ—ï…•Ö±ï–ÅΩúÅ—ï≠πΩ±Ωù•ï∏Åï»Åëï±–Å√îÅ—Ÿï…ÃÅÖÿÅŸÖ…•Öπ—ïπîÏÅëï–ÅÕΩ¥ÅÕ≠•±±ï»Åëï¥Åï»ÅÕ—Â…≠ï¡…Ωô•±ï∏Äú(ÄÄÄÄÄÄÄÅòù±•πÕï∏Åï»ÅôΩ…µï–ÅôΩ»ÉîÅ≠Ω……•ùï…î∏Ω¿¯ú(ÄÄÄÄ§((ÄÄÄÄåÅ;·≠≠ï±—Ö±∞µ…ÖêÅ§Å°ï…Ωï∏Ä¥¥Å≠’∏Åëï–ÅŸ§ÅôÖ≠—•Õ¨Å≠Ö∏ÅâïŸ•ÕîÅô…ÑÅëÖ—Öï∏(ÄÄÄÄåÄ°Ö±ë…§Åï∏Äâ—ï≠πΩ±Ωù§àµ√ïÕ—Öπê∞ÅÕ•ëï∏ÅÕ¡ïçÃÅ•≠≠îÅ°Ö»Åï–ÅÕ±•≠–Åôï±–(ÄÄÄÄåÅ≠ΩπÕï≠Ÿïπ–Å¡ï»Å¡…Ωë’≠–§∏ÅYÖππ•ππ°Ω±êÅŸ•ÕïÃÅ≠’∏Åªï»Å11ÅŸÖ…•Öπ—ïπî(ÄÄÄÄåÅôÖ≠—•Õ¨Åëï±ï»Åª·ÂÖ≠—•úÅÕÖµµîÅŸï…ë§Ä¥¥ÅÕÖµµîÄâÖ±ë…§Åù©ï—–Ωùïπï…Ö±•Õï»à¥(ÄÄÄÄåÅ¡…•πÕ•¡¿ÅÕΩ¥ÅDµï∏Å’πëï»Åâ…’≠ï»ÅôΩ»ÅµÖ—ï…•Ö±î∏(ÄÄÄÅ—Â¡ï}±Öâï±Õ}Õ—Ö–ÄÙÅÕΩ…—ïê°Ì…lâçÖ—ïùΩ…Â}±Öâï∞âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâçÖ—ïùΩ…Â}±Öâï∞âuÙ§(ÄÄÄÅ›ç}ŸÖ±’ïÕ}Õ—Ö–ÄÙÅÌ—’¡±î°…lâ›åât§ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâ›åâuÙ(ÄÄÄÅÕ—Ö—}¡•±±ÃÄÙÅl(ÄÄÄÄÄÄÄÄ°	=a}%=9}MY∞ÅòùÌ±ï∏°…Ω›Ã•ÙÅ¡…Ωë’≠—ï»ú∞ÄàÅΩúÄàπ©Ω•∏°òâÌπÙµ¡Ö≠π•πúàÅôΩ»Å∏Å•∏Å¡Öç≠}Õ•ÈïÃ§Å•òÅ¡Öç≠}Õ•ÈïÃÅï±ÕîÄàà§∞(ÄÄÄÄÄÄÄÄ°Q}%=9}MY∞ÅòùÌ±ï∏°—Â¡ï}±Öâï±Õ}Õ—Ö–•ÙÅâï°ΩÿúÅ•òÅ±ï∏°—Â¡ï}±Öâï±Õ}Õ—Ö–§Ä¯ÄƒÅï±ÕîÄ°—Â¡ï}±Öâï±Õ}Õ—Ö—l¡tÅ•òÅ—Â¡ï}±Öâï±Õ}Õ—Ö–Åï±ÕîÄàà§∞ÄàÉ
‹Äàπ©Ω•∏°—Â¡ï}±Öâï±Õ}Õ—Ö–§Å•òÅ±ï∏°—Â¡ï}±Öâï±Õ}Õ—Ö–§Ä¯ÄƒÅï±ÕîÄàà§∞(ÄÄÄÅt(ÄÄÄÅ•òÅÕ°Ω›}µÖ—ï…•Ö∞ÅÖπêÅ±ï∏°µÖ—ï…•Ö±Õ}¡…ïÕïπ–§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅÕ—Ö—}¡•±±ÃπÖ¡¡ïπê†°I=A1Q}%=9}MY∞Äâ5Ö—ï…•Ö±îà∞Åπï·–°•—ï»°µÖ—ï…•Ö±Õ}¡…ïÕïπ–§§§§(ÄÄÄÅ•òÅ±ï∏°›ç}ŸÖ±’ïÕ}Õ—Ö–§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅÕ—Ö—}¡•±±ÃπÖ¡¡ïπê†°I=A1Q}%=9}MY∞ÄâYÖππ•ππ°Ω±êà∞ÄàÄºÄàπ©Ω•∏°òâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÄîàÅôΩ»ÅÿÅ•∏Åπï·–°•—ï»°›ç}ŸÖ±’ïÕ}Õ—Ö–§§§§§(ÄÄÄÅÕ—Ö—}¡•±±Õ}°—µ∞ÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÅòúúúÒë•ÿÅç±ÖÕÃÙâÕï…•îµÕ—Ö–µ¡•±∞à¯(ÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâÕï…•îµÕ—Ö–µ•çΩ∏àÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩÕ¡Ö∏¯(ÄÄÄÄÒë•ÿ¯Òë•ÿÅç±ÖÕÃÙâÕï…•îµÕ—Ö–µ±Öâï∞à˘ÌïÕçÖ¡î°±Öâï∞•ÙΩë•ÿ˘ÌòúÒë•ÿÅç±ÖÕÃÙâÕï…•îµÕ—Ö–µŸÖ±’îà˘ÌïÕçÖ¡î°ŸÖ±’î•ÙΩë•ÿ¯úÅ•òÅŸÖ±’îÅï±ÕîÄúùÙΩë•ÿ¯(ÄÄΩë•ÿ¯úúú(ÄÄÄÄÄÄÄÅôΩ»Å•çΩ∏∞Å±Öâï∞∞ÅŸÖ±’îÅ•∏ÅÕ—Ö—}¡•±±ÃÅ•òÅ±Öâï∞(ÄÄÄÄ§((ÄÄÄÄåÄâ•π∏Åë•∏ÅŸÖ…•Öπ–àÄ¥¥É•∏Å≠Öπë•ëÖ—Õ•ëîÅ¡ï»Å	!=XÄ°≠Ö—ïùΩ…§§ÅôÖµ•±•ï∏(ÄÄÄÄåÅôÖ≠—•Õ¨Åëï≠≠ï»∞Å•≠≠îÉ•∏Å¡ï»Å¡Ö≠π•πùÕÕ”·……ï±Õî∏Å©ïπâ…’≠ï»Å	Y%MMP(ÄÄÄÄåÅ≠Ö—ïùΩ…•≠Ω…—ïπïÃÅïùπîÅ¡ÖÕ—ï±±â•±ëï»Ä°Õ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâú¥®§Å§ÅÕ—ïëï–(ÄÄÄÄåÅôΩ»ÉîÅô•ππîÅΩ¡¿Åï∏Å—…ïë©îÅ—Â¡îÅ±•πÕïâ•±ëîÄ¥¥Å-Ö§ÅÕ•—–Åïùï–Å¡Ωïπú(ÄÄÄÄåÄ»¿»ÿ¥¿‰¥»‹ËÅôΩ»ÅµÖπùîÅ’±•≠îÅ±•πÕïâ•±ëï»Ä°°ï…ºÄ¨Äâô•π∏ÅŸÖ…•Öπ–àÄ¨(ÄÄÄÄåÅ¡Ö≠π•πùÕâ•±ëï»Å§Å—Öâï±±ï∏§ÅŸ•±±îÅâ±•—–Å…Ω—ï—î∏ÅIï≠≠ïõ·±ùï∏Åõ·±ùï»(ÄÄÄÄåÅQ=Ie}	ÅÕ•∏Åª·≠≠ï±…ï≠≠ïõ·±ùîÄ°∑ïπïêΩëÖúÅõ·»Å—Ω…•Õ¨ΩôÖ…ùï–Ωµ’±—•ôΩ≠Ö∞§(ÄÄÄÄåÅÕ±•¨ÅÖ–ÄâŸÖπ±•úÅÕÂπÕ≠Ω……ï≠Õ©Ω∏àÅÖ±±—•êÅ≠Ωµµï»Åõ·…Õ–∏Ä°}YI%9Q}9}1	1L(ÄÄÄÄåÅΩúÅâÂ}çÖ—ïùΩ…‰Åï»ÅÖ±±ï…ïëîÅâÂùùï–ÅΩŸï»∞Å—•∞ÅÕÖµµïπ±•ùπ•πùÕ—Öâï±±ï∏∏§(ÄÄÄÅŸÖ…•Öπ—}çÖ…ëÃÄÙÅmt(ÄÄÄÅôΩ»ÅçÖ—}Õ±’úÅ•∏Å±•Õ–°Q=Ie}	§Ä¨ÅmÃÅôΩ»ÅÃÅ•∏ÅâÂ}çÖ—ïùΩ…‰Å•òÅÃÅπΩ–Å•∏ÅQ=Ie}	tË(ÄÄÄÄÄÄÄÅù…Ω’¿ÄÙÅâÂ}çÖ—ïùΩ…‰πùï–°çÖ—}Õ±’ú§(ÄÄÄÄÄÄÄÅ•òÅπΩ–Åù…Ω’¿Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçΩπ—•π’î(ÄÄÄÄÄÄÄÅ…ï¿ÄÙÅµ•∏°ù…Ω’¿∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ¡Öç≠}Õ•ÈîâtÅΩ»Ä¿§(ÄÄÄÄÄÄÄÅù…Ω’¡}¡Öç≠ÃÄÙÅÕΩ…—ïê°Ì…lâ¡Öç≠}Õ•ÈîâtÅôΩ»Å»Å•∏Åù…Ω’¿Å•òÅ…lâ¡Öç≠}Õ•ÈîâuÙ§(ÄÄÄÄÄÄÄÅ¡Öç≠Õ}—·–ÄÙÄàÅï±±ï»Äàπ©Ω•∏°Õ—»°∏§ÅôΩ»Å∏Å•∏Åù…Ω’¡}¡Öç≠Ã§Ä¨ÄàÅ±•πÕï»àÅ•òÅù…Ω’¡}¡Öç≠ÃÅï±ÕîÄàà(ÄÄÄÄÄÄÄÅâúÄÙÅQ=Ie}	πùï–°çÖ—}Õ±’ú§(ÄÄÄÄÄÄÄÅâù}°—µ∞ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÅòúÒ•µúÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµâúàÅÕ…åÙàΩÕ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâúµÌâùÙ¥Ã»¿π›ïâ¿àÅÖ±–ÙààÅ›•ë—†ÙàÃ»¿àÅ°ï•ù°–Ùàƒ–ÃàÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯ú(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅâúÅï±ÕîÄàà(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅŸÖ…•Öπ—}çÖ…ëÃπÖ¡¡ïπê°òúúúÒÑÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êàÅ°…ïòÙâÌïÕçÖ¡î°…ï¡lâ°…ïòât•Ùà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµ—°’µàà˘Ìâù}°—µ±ÙΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµ—ï·–à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµπïïêà˘ÌïÕçÖ¡î°}YI%9Q}9}1	1Lπùï–°çÖ—}Õ±’ú∞ÅçÖ—ïùΩ…•ïÃπùï–°çÖ—}Õ±’ú∞ÅÌÙ§πùï–†â±Öâï∞à∞Äàà§§•ÙΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµπÖµîà˘ÌïÕçÖ¡î°…ï¡lâë•Õ¡±ÖÂ}πÖµîât•ÙΩë•ÿ¯(ÄÄÄÄÄÅÌòúÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµ¡Öç≠Ãà˘ÌïÕçÖ¡î°¡Öç≠Õ}—·–•ÙΩë•ÿ¯úÅ•òÅ¡Öç≠Õ}—·–Åï±ÕîÄúùÙ(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒÕ¡Ö∏Åç±ÖÕÃÙâŸÖ…•Öπ–µçÖ…êµÖ……Ω‹àÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˚äHΩÕ¡Ö∏¯(ÄÄΩÑ¯úúú§(ÄÄÄÅŸÖ…•Öπ—}ô•πëï…}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ±ï∏°ŸÖ…•Öπ—}çÖ…ëÃ§Ä¯ÄƒË(ÄÄÄÄÄÄÄÅŸÖ…•Öπ—}ô•πëï…}°—µ∞ÄÙÅòúúúÒ†»˘•π∏Åë•∏ÅŸÖ…•Öπ–Ω†»¯(ÄÄÒ¿Åç±ÖÕÃÙâŸÖ…•Öπ–µô•πëï»µ±ïÖêà˘!Ÿ•±≠ï∏ÅÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙÅ¡ÖÕÕï»ÅôΩ»Åëïú¸Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µô•πëï»µù…•êà¯(ÄÄÄÅÏààπ©Ω•∏°ŸÖ…•Öπ—}çÖ…ëÃ•Ù(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâŸÖ…•Öπ–µô•πëï»µπΩ—îà¯(ÄÄÄÄÒÕŸúÅŸ•ï›	Ω‡Ùà¿Ä¿Ä»–Ä»–àÅô•±∞ÙâπΩπîàÅÕ—…Ω≠îÙâç’……ïπ—Ω±Ω»àÅÕ—…Ω≠îµ›•ë—†Ùàƒ∏‡àÅÕ—…Ω≠îµ±•πïçÖ¿Ùâ…Ω’πêàÅÕ—…Ω≠îµ±•πï©Ω•∏Ùâ…Ω’πêàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯Òç•…ç±îÅç‡Ùàƒ»àÅç‰Ùàƒ»àÅ»Ùàƒ¿àº¯Ò¡Ö—†ÅêÙâ4ƒ»ÄƒŸÿ¥—4ƒ»Ä·†∏¿ƒàº¯ΩÕŸú¯(ÄÄÄÄÒ¿˘!Ö»Åë‘ÅÖ±±ï…ïëîÅõï—–ÅôΩ…ïÕ≠…ïŸï–Åï∏ÅâïÕ—ïµ–ÅŸÖ…•Öπ–ÅÖÿÅΩ¡—•≠ï»¸ÅYï±úÅÕÖµµîÅŸÖ…•Öπ–∞ÅΩúÅ≠Ωπ—…Ω±±ï»ÅÖ±±—•êÅ	∞ÅÕ—Â…≠îÅΩúÅïŸïπ—’ï±±îÅe0Ωa%LΩµŸï…ë•ï»ÅµΩ–Å…ïÕï¡—ï∏Åë•∏∏Ω¿¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÅA…•Õ•ππÕ•≠–ÅôΩ»Å!1ÅÕï…•ï∏Ä°Õπ•—–Å¡ï»Å¡Ö≠π•πùÕÕ”·……ï±Õî∞ÅÕî(ÄÄÄÄåÅ}ôÖµ•±Â}¡…•çï}•πÕ•ù°—}ëÖ—Ñ†§§Ä¥¥Å-Ö§ÅÕ•—–Åï≠Õ¡±•Õ•——îÉ·πÕ≠îÄ»¿»ÿ¥¿‰¥»‹∞(ÄÄÄÄåÅï∏Å—Â¡îÅ•ππÕ•≠–Å≠’∏Åµ’±•úÅôΩ…ë§ÅŸ§ÅÕï»Åô±ï…îÅ¡…Ωë’≠—ï»ÅÕÖµ±ï–∏(ÄÄÄÅ¡…•çï}•πÕ•ù°—}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ¡…•çï}°•Õ—Ω…‰Ë(ÄÄÄÄÄÄÄÅ•πÕ•ù°—}âÂ}¡Öç¨ÄÙÅ}ôÖµ•±Â}¡…•çï}•πÕ•ù°—}ëÖ—Ñ°…Ω›Ã∞Å¡…•çï}°•Õ—Ω…‰§(ÄÄÄÄÄÄÄÅ¡…•çï}•πÕ•ù°—}°—µ∞ÄÙÅ…ïπëï…}ôÖµ•±Â}¡…•çï}•πÕ•ù°–°ôÖµ•±Â}πÖµî∞Å•πÕ•ù°—}âÂ}¡Öç¨§((ÄÄÄÄåÄâ-Ω…–ÅΩ¥Å`àÄ¥¥ÅŸïêÅÕ•ëï∏ÅÖÿÅA…•Õ•ππÕ•≠–Ä°-Ö§ËÄâÕ±•¨ÅÖ–ÅŸ§Åõï»Åï∏(ÄÄÄÄåÅ≠Ωµ¡…•µï…–Å¡…•Õ•ππÕ•≠–∞Åëï–Å°Ω±ëï»à§∞Å-U8ÅôÖ≠—ÑÅŸ§ÅôÖ≠—•Õ¨Å≠Ö∏ÅâïŸ•ÕîÅï»(ÄÄÄÄåÅ±•≠îÅ√îÅ—Ÿï…ÃÅÖÿÅ11ÅŸÖ…•Öπ—ïπîÄ°ÕÖµµîÄâÖ±ë…§Åù©ï—–àµ¡…•πÕ•¡¿ÅÕΩ¥(ÄÄÄÄåÅ…ïÕ—ï∏ÅÖÿÅÕ•ëï∏Ä¥¥Åòπï≠Ã∏ÅUXµô•±—ï»Åï»Åï–Å…ïï±–ÅÕ¡ïçÃµôï±–∞Åµï∏Åô•ππïÃ(ÄÄÄÄåÅ•≠≠îÅ§Åëï–Å°ï±îÅ—Ö—–ÅôΩ»Åïπ≠ï±—îÅôÖµ•±•ï»∞ÅΩúÅ’—ï±Ö—ïÃÅëÑÅ°ï±–Å§ÅÕ—ïëï–(ÄÄÄÄåÅôΩ»ÉîÅ±Ö—îÅÕΩ¥Åëï–Åï»ÅÕ©ï≠≠ï–§∏(ÄÄÄÅâ…’≠Õ—•ë}ŸÖ±’ïÃÄÙÅÌ…lâÕ¡ïçÃâtπùï–†â	…’≠Õ—•êà§ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâÕ¡ïçÃâtπùï–†â	…’≠Õ—•êà•Ù(ÄÄÄÅ’Ÿ}ŸÖ±’ïÃÄÙÅÌ…lâÕ¡ïçÃâtπùï–†âUXµô•±—ï»à§ÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâÕ¡ïçÃâtπùï–†âUXµô•±—ï»à•Ù(ÄÄÄÄåÅ!Ÿï»Å…ÖêËÄ°•≠Ω∏∞Å°ΩŸïëŸï…ë§∞Å’πëï…—ï≠Õ–Ωï—•≠ï—–§Ä¥¥Åëï±–ÅëÖ—Öù…’ππ±ÖúÅôΩ»(ÄÄÄÄåÅÄâ-Ω…–ÅΩ¥Å`àÄ°Õ©ï≠≠±•Õ—î∞ÅŸïêÅA…•Õ•ππÕ•≠–§ÅΩúÄâï±±ïÃÅôΩ»Å°ï±î(ÄÄÄÄåÅÕï…•ï∏àÄ°•≠Ω∏µ…’—ïπï—–∞ÅŸïêÅIï±ïŸÖπ—îÅù’•ëï»Å±ïπùï»Åπïê§Ä¥¥ÅÕÖµµîÅôÖ≠—Ñ∞(ÄÄÄÄåÅ—ºÅ’±•≠îÅŸ•Õ’ï±±îÅ…Ω±±ï»∞ÅÕîÅ-Ö§ÅÕ•∏Å—•±âÖ≠ïµï±ë•πúÄ»¿»ÿ¥¿‰¥»‹∏(ÄÄÄÅôÖç—}…Ω›ÃÄÙÅmt(ÄÄÄÅ•òÅ±ï∏°â…’≠Õ—•ë}ŸÖ±’ïÃ§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅâ–ÄÙÅπï·–°•—ï»°â…’≠Õ—•ë}ŸÖ±’ïÃ§§(ÄÄÄÄÄÄÄÅâ—}Õ’àÄÙÅÏâÖùÕ±•πÕîàËÄâ9‰Å±•πÕîÅ°Ÿï»ÅëÖúà∞Äâ7ïπïëÕ±•πÕîàËÄâM≠•ô—ïÃÅ∑ïπïë±•úà∞ÄâU≠ï±•πÕîàËÄâM≠•ô—ïÃÅ’≠ïπ—±•úâÙπùï–°â–∞Äàà§(ÄÄÄÄÄÄÄÅôÖç—}…Ω›ÃπÖ¡¡ïπê†°19I}%=9}MY∞Åâ–∞Åâ—}Õ’à§§(ÄÄÄÅ•òÅÕ°Ω›}µÖ—ï…•Ö∞ÅÖπêÅ±ï∏°µÖ—ï…•Ö±Õ}¡…ïÕïπ–§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅôÖç—}…Ω›ÃπÖ¡¡ïπê†°	=a}%=9}MY∞Åπï·–°•—ï»°µÖ—ï…•Ö±Õ}¡…ïÕïπ–§§∞Äâ5Ö—ï…•Ö±îà§§(ÄÄÄÅ•òÅ±ï∏°›ç}ŸÖ±’ïÕ}Õ—Ö–§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅôÖç—}…Ω›ÃπÖ¡¡ïπê†°I=A1Q}%=9}MY∞ÄàÄºÄàπ©Ω•∏°òâÌÿπ…ï¡±Öçî†ú∏ú∞Äú∞ú•ÙÄîàÅôΩ»ÅÿÅ•∏Åπï·–°•—ï»°›ç}ŸÖ±’ïÕ}Õ—Ö–§§§∞ÄâYÖππ•ππ°Ω±êà§§(ÄÄÄÅ•òÅ±ï∏°’Ÿ}ŸÖ±’ïÃ§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅôÖç—}…Ω›ÃπÖ¡¡ïπê†°MU9}%=9}MY∞Åπï·–°•—ï»°’Ÿ}ŸÖ±’ïÃ§§∞ÄâUXµô•±—ï»à§§(ÄÄÄÅ•òÅ—Â¡ï}±Öâï±Õ}Õ—Ö–Ë(ÄÄÄÄÄÄÄÅôÖç—}…Ω›ÃπÖ¡¡ïπê†°Q}%=9}MY∞Äà∞Äàπ©Ω•∏°—Â¡ï}±Öâï±Õ}Õ—Ö–§∞ÄâQ•±ù©ïπùï±•úÅôΩ»à§§((ÄÄÄÅôÖç—Õ}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅôÖç—}…Ω›ÃË(ÄÄÄÄÄÄÄÅ•—ïµÃÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÄÄÄÄÅòúúúÒ±§˘Ì!-}%=9}MYÙÒë•ÿ¯ÒÕ—…Ωπú˘ÌïÕçÖ¡î°µÖ•∏•ÙΩÕ—…Ωπú˘ÌòúÒÕ¡Ö∏˘ÌïÕçÖ¡î°Õ’à•ÙΩÕ¡Ö∏¯úÅ•òÅÕ’àÅï±ÕîÄúùÙΩë•ÿ¯Ω±§¯úúú(ÄÄÄÄÄÄÄÄÄÄÄÅôΩ»Å•çΩ∏∞ÅµÖ•∏∞ÅÕ’àÅ•∏ÅôÖç—}…Ω›Ã(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅôÖç—Õ}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç—Ãà¯(ÄÄÄÄÒ†»˘-Ω…–ÅΩ¥ÅÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙΩ†»¯(ÄÄÄÄÒ’∞Åç±ÖÕÃÙâÕï…•îµôÖç—Ãµ±•Õ–à˘Ì•—ïµÕÙΩ’∞¯(ÄÄΩë•ÿ¯úúú(ÄÄÄÅ•πÕ•ù°—}…Ω›}°—µ∞ÄÙÄ†(ÄÄÄÄÄÄÄÅòúÒë•ÿÅç±ÖÕÃÙâÕï…•îµ•πÕ•ù°–µ…Ω‹à˘Ì¡…•çï}•πÕ•ù°—}°—µ±ıÌôÖç—Õ}°—µ±ÙΩë•ÿ¯ú(ÄÄÄÄÄÄÄÅ•òÅ¡…•çï}•πÕ•ù°—}°—µ∞ÅÖπêÅôÖç—Õ}°—µ∞Åï±ÕîÅ¡…•çï}•πÕ•ù°—}°—µ∞Ä¨ÅôÖç—Õ}°—µ∞(ÄÄÄÄ§((ÄÄÄÅôï±±ïÕ}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅôÖç—}…Ω›ÃË(ÄÄÄÄÄÄÄÅ—•±ïÃÄÙÄààπ©Ω•∏†(ÄÄÄÄÄÄÄÄÄÄÄÅòúúúÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç–µ—•±îà¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç–µ—•±îµ•çΩ∏àÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà˘Ì•çΩπÙΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç–µ—•±îµŸÖ±’îà˘ÌïÕçÖ¡î°µÖ•∏•ÙΩë•ÿ¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç–µ—•±îµ±Öâï∞à˘ÌïÕçÖ¡î°Õ’à§Å•òÅÕ’àÅï±ÕîÄúùÙΩë•ÿ¯(ÄÄÄÄΩë•ÿ¯úúú(ÄÄÄÄÄÄÄÄÄÄÄÅôΩ»Å•çΩ∏∞ÅµÖ•∏∞ÅÕ’àÅ•∏ÅôÖç—}…Ω›Ã(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÄåÅ%πùï∏Å±ïπ≠îÅ—•∞Äâ€ï»Åù’•ëîàÄ¥¥ÅŸ§Å°Ö»Å•πùï∏Åïùï∏ÅUXµâïÕ≠Â——ï±Õîµù’•ëî(ÄÄÄÄÄÄÄÄåÅ§ÅU%}=9Q9PÅïπªî∞ÅΩúÅô•ππï»Å•≠≠îÅΩ¡¿Åï∏Å±ïπ≠îÅÕΩ¥Å•≠≠îÅô•ππïÃ∏(ÄÄÄÄÄÄÄÅ’Ÿ}πΩ—îÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄúÒ¿˘-Ωπ—Ö≠—±•πÕï»ÅµïêÅUXµô•±—ï»Åï…Õ—Ö——ï»Å•≠≠îÅÕΩ±â…•±±ï»∏Ω¿¯ú(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ±ï∏°’Ÿ}ŸÖ±’ïÃ§ÄÙÙÄƒÅï±ÕîÄàà(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅôï±±ïÕ}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç—Ãµ—•±ïÃà¯(ÄÄÄÄÒ†»˘ï±±ïÃÅôΩ»Å°ï±îÅÕï…•ï∏Ω†»¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç—Ãµ—•±ïÃµù…•êà˘Ì—•±ïÕÙΩë•ÿ¯(ÄÄÄÅÌòúÒë•ÿÅç±ÖÕÃÙâÕï…•îµôÖç–µπΩ—îà˘ÌQ}%=9}MYıÌ’Ÿ}πΩ—ïÙΩë•ÿ¯úÅ•òÅ’Ÿ}πΩ—îÅï±ÕîÄúùÙ(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÄ¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥¥(ÄÄÄÄåÅDÄ¥¥Å…ïùï±µΩ—Ω»Ä†»¿»ÿ¥¿‰¥»‹∞Åï——ï»ÅôΩ…Õ±ÖúÅô…ÑÅ-Ö§§ËÅÕ√·…Õ∑ï±ïπî(ÄÄÄÄåÅùïπï…ï…ïÃÅ-U8Åô…ÑÅôÖ≠—ÑÅŸ§ÅôÖ≠—•Õ¨Å°Ö»ÅôΩ»Å99ÅôÖµ•±•ï∏∞ÅÖ±ë…§ÅôÂ±–(ÄÄÄÄåÅΩ¡¿Å—•∞Åï–ÅôÖÕ–ÅÖπ—Ö±∞Ä¥¥É•∏ÅÕï…•îÅ≠Ö∏ÅïπëîÅµïêÄ–ÅÕ√·…Õ∑ï∞∞Åï∏ÅÖππï∏(ÄÄÄÄåÅµïêÄƒ¿∞Åëï–Åï»Å¡Ωïπùï–∏ÅΩΩù±îÅô©ï…πï–ÅDµ…•ç†µ…ïÕ’±–µŸ•Õπ•πùï∏Å§(ÄÄÄÄåÅœ·≠ï–ÅôΩ»Åô±ï…îÉï»ÅÕ•ëï∏Ä°âï≠…ïô—ï–Åë•…ï≠—îÅµΩ–(ÄÄÄÄåÅëïŸï±Ω¡ï…ÃπùΩΩù±îπçΩ¥ΩÕïÖ…ç†Ω’¡ëÖ—ïÃÄ¥¥ÄâQ°îÅDÅ…•ç†Å…ïÕ’±–ÅôïÖ—’…î(ÄÄÄÄåÅ•ÃÅπºÅ±Ωπùï»ÅÕ°Ω›∏Å•∏ÅΩΩù±îÅMïÖ…ç†Å…ïÕ’±—Ãà§∞ÅœîÅŸï…ë•ï∏Å°ï»Åï»Å%--(ÄÄÄÄåÅ±ïπùï»Åï–Å…•≠–ÅMI@µ’—ôÖ±∞∞Åëï–Åï»Å…ïï±–Å•πôΩ…µÖÕ©ΩπÕ•ππ°Ω±êÅôΩ»(ÄÄÄÄåÅ$µÕ•—ï…•πùï»Ä°=$µMïÖ…ç°	Ω–Å¥πô∞∏∞Å%--ÅAQ	Ω–ÅÕΩ¥Åï»Åâ±Ω≠≠ï…–Å§(ÄÄÄÄåÅ…ΩâΩ—Ãπ—·–§ÅΩúÅ±Ωπúµ—Ö•∞µœ·¨∏Å…’¡¡ï…–Å§Å—…îÅôÖÕ—îÅ≠Ö—ïùΩ…•ï»Ä°ÕÖµµî(ÄÄÄÄåÅ…ï≠≠ïõ·±ùîÅÕΩ¥Å…ïÕ—ï∏ÅÖÿÅÕ•ëï∏ËÅ¡…Ωë’≠–Ä¥¯ÅÕ¡ïåÄ¥¯Å¡…•Ã§ÅΩúÅŸ•Õ–ÅÕΩ¥Åï∏(ÄÄÄÄåÅï≠—î∞Å≠Ω±±Ö¡Õï–ÄÒëï—Ö•±Ã¯µÖççΩ…ë•Ω∏Ä°ÕîÅ…ïπëï…}›•ππï…}›•ëùï–†§ÅôΩ»(ÄÄÄÄåÅ¡…ïÕïëïπÃËÄÒëï—Ö•±Ã¯Åï»Åï≠Õ¡±•Õ•—–ÅπïŸπ–ÅÖÿÅΩΩù±îÅÕΩ¥Åï∏Å±ïù•—•¥(ÄÄÄÄåÅŸ•ÃΩÕ≠©’∞µµï≠Öπ•Õµî∞Å§ÅµΩ—Õï—π•πúÅ—•∞ÅMLµ’—ïπôΩ»µÕ≠©ï…¥µ—ï≠Õ–§∏(ÄÄÄÄå(ÄÄÄÄåÅQºÅ≠Öπë•ëÖ—Õ√·…Õ∑ï∞Åô…ÑÅôΩ…Õ±Öùï–Åï»Å	Y%MMPÅ’—ï±Ö—–Ë(ÄÄÄÄåÄ¥Äâ!ŸΩ»ÅΩô—îÅΩ¡¡ëÖ—ï…ïÃÅ¡…•Õïπî¸àÄ¥¥Å•ëïπ—•Õ¨ÅÕŸÖ»ÅôΩ»ÅÖ±±îÅôÖµ•±•ï»∞(ÄÄÄÄåÄÄÅù•»Å•πùï∏ÅÕï…•îµÕ¡ïÕ•ô•≠¨Å•πôºÄ°Õ—…•ëï»ÅµΩ–ÄâÖ±ë…§ÅôÂ±∞Å’–àµ¡…•πÕ•¡¡ï–§∏(ÄÄÄÄåÄ¥ÅΩ…≠±Ö…•πúÅÖÿÅµÖ—ï…•Ö±πÖŸ∏Ä†â!ŸÑÅï»Å1I=8¸àºâ—Öô•±çΩ∏Å¸à§Ä¥¥Å≠…ïŸï»(ÄÄÄÄåÄÄÅï∏Åïùï∏∞Å…ïÕïÖ…ç†µâÖÕï…–ÅΩ…ë±•Õ—îÅΩŸï»Å¡…Ωë’Õïπ—ïπïÃÅµÖ—ï…•Ö±πÖŸ∏ÅÕΩ¥(ÄÄÄÄåÄÄÅŸ§Å•≠≠îÅ°Ö»ÅÕ—…’≠—’…ï…–ÅëÖ—ÑÅôΩ»Åïπªî∏Å±Öùùï–ÅÕΩ¥Åô…ïµ—•ë•úÅΩ¡¡ùÖŸî∏(ÄÄÄÅôÖ≈}¡…Ωë’≠–ËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅôÖ≈}Õ¡ïåËÅ±•Õ—më•ç—tÄÙÅmt(ÄÄÄÅôÖ≈}¡…•ÃËÅ±•Õ—më•ç—tÄÙÅmt((ÄÄÄÅ—Â¡ï}±Öâï±ÃÄÙÅÕΩ…—ïê°Ì…lâçÖ—ïùΩ…Â}±Öâï∞âtÅôΩ»Å»Å•∏Å…Ω›ÃÅ•òÅ…lâçÖ—ïùΩ…Â}±Öâï∞âuÙ§(ÄÄÄÅ•òÅ—Â¡ï}±Öâï±ÃË(ÄÄÄÄÄÄÄÅ—Â¡ï}—·–ÄÙÄàÅΩúÄàπ©Ω•∏°—Â¡ï}±Öâï±Ã§Å•òÅ±ï∏°—Â¡ï}±Öâï±Ã§ÄÙÄ»Åï±ÕîÄà∞Äàπ©Ω•∏°—Â¡ï}±Öâï±ÕlË¥≈t§Ä¨ÄàÅΩúÄàÄ¨Å—Â¡ï}±Öâï±Õl¥≈t(ÄÄÄÄÄÄÄÅ¡Öç≠}—·–ÄÙÅòúÅï∏ÅõïÃÅ§ÅÏàÅΩúÄàπ©Ω•∏°òâÌπÙµ¡Ö≠π•πúàÅôΩ»Å∏Å•∏Å¡Öç≠}Õ•ÈïÃ•Ù∏úÅ•òÅ¡Öç≠}Õ•ÈïÃÅï±ÕîÄàà(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ÿ•±≠îÅŸÖ…•Öπ—ï»Åô•ππïÃÅÖÿÅÌôÖµ•±Â}πÖµïÙ¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùÌôÖµ•±Â}πÖµïÙµÕï…•ï∏Åô•ππïÃÅÕΩ¥ÅÌ—Â¡ï}—·–π±Ω›ï»†•ÙπÌ¡Öç≠}—·—ÙÅMîÅ—Öâï±±ï∏ÅΩŸï»ÅôΩ»Å¡…•ÃÅ√îÅ°Ÿï»ÅŸÖ…•Öπ–∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÄåÅ	ÖÕï…–Å√îÅ-Q=I%8Ä°âÂ}çÖ—ïùΩ…‰∞ÅÕÖµµîÅ≠•±ëîÅÕΩ¥Äâ•π∏Åë•∏ÅŸÖ…•Öπ–à(ÄÄÄÄåÅΩúÅ—Öâï±±ïπÃÅ—Â¡îµ≠Ω±Ωππî§∞Å%--Å√îÅΩ¥Åe0Ωa%LΩµÕ¡ïÕ•ô•≠≠îÅ—Ö±±ôï±–(ÄÄÄÄåÅô•ππïÃÄ¥¥Åïπ≠ï±—îÅ—Ω…•Õ≠îΩµ’±—•ôΩ≠Ö±îÅ¡…Ωë’≠—ï»ÅµÖπù±ï»Åë•ÕÕîÅôï±—ïπîÅ§(ÄÄÄÄåÅÕ¡ïçÃµëÖ—Öï∏Ä°ÕîÅòπï≠Ã∏ÅÖ•±•ïÃÅQΩ—Ö∞ƒÅÕ•∏ÅÖÕ—•ùµÖ—•ÕµîµŸÖ…•Öπ–§∞Åµï∏(ÄÄÄÄåÅï»Å±•≠ïŸï∞Å…ïï±–Å—Ω…•Õ¨Ωµ’±—•ôΩ≠Ö∞Å¡ï»Å≠Ö—ïùΩ…•Õï…•πùï∏∏ÅMŸÖ…ï–ÅπïŸπï»(ÄÄÄÄåÅe0Ωa%LΩÅ≠’∏Åªï»ÅëîÅôÖ≠—•Õ¨Åô•ππïÃÅ§ÅÕ¡ïçÃ∏(ÄÄÄÅ—Ω…•ç}ù…Ω’¡}…Ω›ÃÄÙÅâÂ}çÖ—ïùΩ…‰πùï–†â—Ω…•Õ≠îµ±•πÕï»à§(ÄÄÄÅµ’±—•}ù…Ω’¡}…Ω›ÃÄÙÅâÂ}çÖ—ïùΩ…‰πùï–†âµ’±—•ôΩ≠Ö±îµ±•πÕï»à§(ÄÄÄÅ•òÅ—Ω…•ç}ù…Ω’¡}…Ω›ÃÅÖπêÅ±ï∏°âÂ}çÖ—ïùΩ…‰§Ä¯ÄƒË(ÄÄÄÄÄÄÄÅ…ï¿ÄÙÅµ•∏°—Ω…•ç}ù…Ω’¡}…Ω›Ã∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ¡Öç≠}Õ•ÈîâtÅΩ»Ä¿§(ÄÄÄÄÄÄÄÅ…ï¡}πÖµîÄÙÅ…îπÕ’à°»âqÃ≠qê¨µ¡Öç¨êà∞Äàà∞Å…ï¡lâë•Õ¡±ÖÂ}πÖµîât§(ÄÄÄÄÄÄÄÅ°ÖÕ}çÂ±}Õ¡ïåÄÙÅÖπ‰°…lâÕ¡ïçÃâtπùï–†âMÂ±•πëï»à§ÅΩ»Å…lâÕ¡ïçÃâtπùï–†â≠Õîà§ÅôΩ»Å»Å•∏Å—Ω…•ç}ù…Ω’¡}…Ω›Ã§(ÄÄÄÄÄÄÄÅçÂ±}—·–ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄúÅï∏Å°Ö»ÅïùπîÅe0¥ÅΩúÅa%LµŸï…ë•ï»Ä°ÕîÅ—Öâï±±ï∏Å’πëï»§ÅÕΩ¥Å∑îÅµÖ—ç°îÅ…ïÕï¡—ï∏Åë•∏Åô…ÑÅΩ¡—•≠ï»∏ú(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ°ÖÕ}çÂ±}Õ¡ïåÅï±ÕîÄúÅMîÅ—Öâï±±ï∏Å’πëï»ÅôΩ»Å¡…•ÃÅΩúÅ¡Ö≠π•πùÕÕ”·……ï±Õï»∏ú(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù•ππïÃÅÌôÖµ•±Â}πÖµïÙÅôΩ»ÅÖÕ—•ùµÖ—•Õµî¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞ÅÌ…ï¡}πÖµïÙÅï»Åëï∏Å—Ω…•Õ≠îÅŸÖ…•Öπ—ï∏Å§ÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏∞Å±Öùï–ÅÕ¡ïÕ•ô•≠–ÅôΩ»ÅÖÕ—•ùµÖ—•ÕµîπÌçÂ±}—·—Ùú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÅµ’±—•}ù…Ω’¡}…Ω›ÃÅÖπêÅ±ï∏°âÂ}çÖ—ïùΩ…‰§Ä¯ÄƒË(ÄÄÄÄÄÄÄÅ…ï¿ÄÙÅµ•∏°µ’±—•}ù…Ω’¡}…Ω›Ã∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lâ¡Öç≠}Õ•ÈîâtÅΩ»Ä¿§(ÄÄÄÄÄÄÄÅ…ï¡}πÖµîÄÙÅ…îπÕ’à°»âqÃ≠qê¨µ¡Öç¨êà∞Äàà∞Å…ï¡lâë•Õ¡±ÖÂ}πÖµîât§(ÄÄÄÄÄÄÄÅ°ÖÕ}Öëë}Õ¡ïåÄÙÅÖπ‰°…lâÕ¡ïçÃâtπùï–†âëë•Õ©Ω∏à§ÅôΩ»Å»Å•∏Åµ’±—•}ù…Ω’¡}…Ω›Ã§(ÄÄÄÄÄÄÄÅÖëë}—·–ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄú∞ÅµïêÅï∏Åïùï∏ÅµŸï…ë§Ä°—•±±ïùùÕÕ—Â…≠îÅôΩ»Åªô…ÕÂ∏Ω±ïÕ•πú§Å§Å—•±±ïùúÅ—•∞ÅŸÖπ±•úÅÕ—Â…≠îú(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ°ÖÕ}Öëë}Õ¡ïåÅï±ÕîÄú∞ÅôΩ»ÅÖ±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§Å§Å—•±±ïùúÅ—•∞ÅŸÖπ±•úÅÕ—Â…≠îú(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù•ππïÃÅÌôÖµ•±Â}πÖµïÙÅÕΩ¥Åµ’±—•ôΩ≠Ö∞Å±•πÕîÅôΩ»ÅÖ±ëï…ÕÕÂ∏¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞ÅÌ…ï¡}πÖµïÙÅï»Åµ’±—•ôΩ≠Ö∞µŸÖ…•Öπ—ï∏Å§ÅÌôÖµ•±Â}πÖµïÙµÕï…•ïπÌÖëë}—·—Ù∏ú∞(ÄÄÄÄÄÄÄÅÙ§(ÄÄÄÅ•òÅ±ï∏°µÖ—ï…•Ö±Õ}¡…ïÕïπ–§ÄÙÙÄƒÅÖπêÅ±ï∏°…Ω›Ã§Ä¯ÄƒË(ÄÄÄÄÄÄÄÅôÖ≈}¡…Ωë’≠–πÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù»ÅÖ±±îÅŸÖ…•Öπ—ïπîÅ§ÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏Å±Öùï–ÅÖÿÅÕÖµµîÅµÖ—ï…•Ö±î¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞Å°ï±îÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏Åï»Å±Öùï–ÅÖÿÅÌπï·–°•—ï»°µÖ—ï…•Ö±Õ}¡…ïÕïπ–§•Ù∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùï–Åï»ÅÕ—Â…≠ï¡…Ωô•±ï∏Ä°Õõô…•Õ¨∞Å—Ω…•Õ¨Åï±±ï»Åµ’±—•ôΩ≠Ö∞§ÅÕΩ¥ÅÕ≠•±±ï»ÅŸÖ…•Öπ—ïπî∞Å•≠≠îÅÕï±ŸîÅ±•πÕïµÖ—ï…•Ö±ï–∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ•òÅ±ï∏°—Öâ±ï}ù…Ω’¡Ã§Ä¯ÄƒÅÖπêÄ°Õ°Ω›}âåÅΩ»ÅÕ°Ω›}ë•Öµï—ï»§Ë(ÄÄÄÄÄÄÄÅâç}Ö±∞ÄÙÅÌ—’¡±î°ùlââåât§ÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡ÃÅ•òÅùlââåâuÙ(ÄÄÄÄÄÄÄÅë•Ö}Ö±∞ÄÙÅÌ—’¡±î°ùlâë•Öµï—ï»ât§ÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡ÃÅ•òÅùlâë•Öµï—ï»âuÙ(ÄÄÄÄÄÄÄÅÕ¡ïç}¡Ö…—ÃÄÙÅmt(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}âåË(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ±ï∏°âç}Ö±∞§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}¡Ö…—ÃπÖ¡¡ïπê°òùâÖÕ•Õ≠’…Ÿï∏Ä°	§Åï»ÅÏàºàπ©Ω•∏°ÿπ…ï¡±Öçî†à∏à∞Äà∞à§ÅôΩ»ÅÿÅ•∏Åπï·–°•—ï»°âç}Ö±∞§§•ÙÅµ¥ÅôΩ»ÅÖ±±îÅŸÖ…•Öπ—ïπîú§(ÄÄÄÄÄÄÄÄÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}¡Ö…—ÃπÖ¡¡ïπê†ùâÖÕ•Õ≠’…Ÿï∏Ä°	§ÅŸÖ…•ï…ï»Åµï±±Ω¥ÅŸÖ…•Öπ—ïπîËÄúÄ¨Äà∞Äàπ©Ω•∏†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌùlâπÖµîâuÙÅÏàºàπ©Ω•∏°ÿπ…ï¡±Öçî†à∏à∞Äà∞à§ÅôΩ»ÅÿÅ•∏Åùlââåât•ÙÅµ¥úÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡ÃÅ•òÅùlââåât(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄ§§(ÄÄÄÄÄÄÄÅ•òÅÕ°Ω›}ë•Öµï—ï»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ±ï∏°ë•Ö}Ö±∞§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}¡Ö…—ÃπÖ¡¡ïπê°òùë•Öµï—ï…ï∏Åï»ÅÏàºàπ©Ω•∏°ÿπ…ï¡±Öçî†à∏à∞Äà∞à§ÅôΩ»ÅÿÅ•∏Åπï·–°•—ï»°ë•Ö}Ö±∞§§•ÙÅµ¥ÅôΩ»ÅÖ±±îú§(ÄÄÄÄÄÄÄÄÄÄÄÅï±ÕîË(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}¡Ö…—ÃπÖ¡¡ïπê†ùë•Öµï—ï…ï∏ÅŸÖ…•ï…ï»ËÄúÄ¨Äà∞Äàπ©Ω•∏†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌùlâπÖµîâuÙÅÏàºàπ©Ω•∏°ÿπ…ï¡±Öçî†à∏à∞Äà∞à§ÅôΩ»ÅÿÅ•∏Åùlâë•Öµï—ï»ât•ÙÅµ¥úÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡ÃÅ•òÅùlâë•Öµï—ï»ât(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄ§§(ÄÄÄÄÄÄÄÅ•òÅÕ¡ïç}¡Ö…—ÃË(ÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}ÖπÕ›ï»ÄÙÅÕ¡ïç}¡Ö…—Õl¡ul¡tπ’¡¡ï»†§Ä¨ÅÕ¡ïç}¡Ö…—Õl¡ulƒÈt(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ±ï∏°Õ¡ïç}¡Ö…—Ã§ÄÙÙÄ»Ë(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}ÖπÕ›ï»Ä¨ÙÄà∞ÅµïπÃÄàÄ¨ÅÕ¡ïç}¡Ö…—Õl≈t(ÄÄÄÄÄÄÄÄÄÄÄÅÕ¡ïç}ÖπÕ›ï»Ä¨ÙÄà∏Å-Ωπ—…Ω±±ï»ÅÖ±±—•êÅë•ÕÕîÅŸï…ë•ïπîÅµΩ–Å…ïÕï¡—ï∏Åë•∏Åô…ÑÅΩ¡—•≠ï»∏à(ÄÄÄÄÄÄÄÄÄÄÄÅôÖ≈}Õ¡ïåπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ö»ÅÖ±±îÅŸÖ…•Öπ—ïπîÅ§ÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏ÅÕÖµµîÅâÖÕ•Õ≠’…ŸîÅΩúÅë•Öµï—ï»¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅÕ¡ïç}ÖπÕ›ï»∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ¡Ω›ï…}ë•µ}—Â¡ïÃÄÙÅÌùlâ¡Ω›ï…}ë•¥âtÅôΩ»ÅúÅ•∏Å—Öâ±ï}ù…Ω’¡ÃÅ•òÅùlâ¡Ω›ï…}ë•¥âtÄÑÙÄãäLâÙ(ÄÄÄÅ•òÅ¡Ω›ï…}ë•µ}—Â¡ïÃË(ÄÄÄÄÄÄÄÅù±ΩÕÕÖ…Â}¡Ö…—ÃÄÙÅmt(ÄÄÄÄÄÄÄÅ•òÄâe0Ωa%LàÅ•∏Å¡Ω›ï…}ë•µ}—Â¡ïÃË(ÄÄÄÄÄÄÄÄÄÄÄÅù±ΩÕÕÖ…Â}¡Ö…—ÃπÖ¡¡ïπê†ùe0Ä°ÕÂ±•πëï…Õ—Â…≠î§ÅΩúÅa%LÄ°Ö≠Õî§ÅâïÕ≠…•Ÿï»Å°ŸΩ»ÅµÂîÅΩúÅ§Å°Ÿ•±≠ï∏Å…ï—π•πúÅ±•πÕï∏Å≠Ω……•ùï…ï»ÅÖÕ—•ùµÖ—•ÕµîÄ°Õ≠©ïŸ°ï–Å§Å°Ω…π°•ππï∏§ú§(ÄÄÄÄÄÄÄÅ•òÄâàÅ•∏Å¡Ω›ï…}ë•µ}—Â¡ïÃË(ÄÄÄÄÄÄÄÄÄÄÄÅù±ΩÕÕÖ…Â}¡Ö…—ÃπÖ¡¡ïπê†ùÄ°Öëë•Õ©Ω∏§Åï»Å—•±±ïùùÕÕ—Â…≠ï∏Å§Åï∏Åµ’±—•ôΩ≠Ö∞Å±•πÕîÅôΩ»Åªô…ÕÂ∏Ω±ïÕ•πú∞Å§Å—•±±ïùúÅ—•∞ÅŸÖπ±•úÅÕ—Â…≠î∞ÅŸïêÅÖ±ëï…ÕÕÂ∏Ä°¡…ïÕâÂΩ¡§§ú§(ÄÄÄÄÄÄÄÅôÖ≈}Õ¡ïåπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÄù!ŸÑÅâï—Â»Åe0Ωa%LΩÅ§ÅÕÖµµïπ±•ùπ•πùÕ—Öâï±±ï∏¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄà∏Äàπ©Ω•∏°¡l¡tπ’¡¡ï»†§Ä¨Å¡lƒÈtÅôΩ»Å¿Å•∏Åù±ΩÕÕÖ…Â}¡Ö…—Ã§Ä¨Äú∏ÅYï…ë•ïπîÅÕ≠Ö∞ÅÖ±±—•êÅµÖ—ç°îÅ…ïÕï¡—ï∏Åë•∏Åô…ÑÅΩ¡—•≠ï»∞Å•≠≠îÅŸï±ùïÃÅ√îÅïùï∏Å£ïπê∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ•òÅ±ï∏°’Ÿ}ŸÖ±’ïÃ§ÄÙÙÄƒË(ÄÄÄÄÄÄÄÅôÖ≈}Õ¡ïåπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!Ö»ÅÌôÖµ•±Â}πÖµïÙÅUXµô•±—ï»¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòù)Ñ∞Å°ï±îÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏Å°Ö»ÅUXµô•±—ï»Ä°Ìπï·–°•—ï»°’Ÿ}ŸÖ±’ïÃ§•Ù§∏Åï——îÅï…Õ—Ö——ï»Å•≠≠îÅÕΩ±â…•±±ï»Ä¥¥Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùUXµô•±—ï…ï–ÅâïÕ≠Â——ï»Å≠’∏ÅÕï±ŸîÉ·Âï–Å±•πÕï∏Åëï≠≠ï»∞Å•≠≠îÅ…ïÕ—ï∏ÅÖÿÉ·Âï–ÅΩúÅ°’ëï∏Å…’πë–∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅ•òÅ±Ω›ïÕ—}…Ω‹ÅÖπêÅ±Ω›ïÕ—}…Ω›lââïÕ–âtË(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ŸÑÅï»Åâ•±±•ùÕ–Å§ÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùÌ±Ω›ïÕ—}…Ω›lâë•Õ¡±ÖÂ}πÖµîâuÙÅï»Åâ•±±•ùÕ–ÅÖ≠≠’…Ö–Åªî∞Åô…ÑÅÌ}ôµ—}≠»°±Ω›ïÕ—}…Ω›lââïÕ–âulâ¡…•çï}πΩ¨ât•ÙÄú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòù°ΩÃÅÌ±Ω›ïÕ—}…Ω›lââïÕ–âulâ…ï—Ö•±ï»âuÙÄ°’—ï∏Åô…Ö≠–§∏ÅA…•Õï∏ÅŸÖ…•ï…ï»Åµï±±Ω¥ÅŸÖ…•Öπ—ïπîÅ§ÅÕï…•ï∏∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅÖ±±}…ï—Ö•±ï…}πÖµïÃËÅÕï—mÕ—…tÄÙÅÕï–†§(ÄÄÄÅΩôôï…}çΩ’π—ÃÄÙÅmt(ÄÄÄÅôΩ»Å»Å•∏Å…Ω›ÃË(ÄÄÄÄÄÄÄÅï±•úÄÙÅ…lâï±•ù•â±îât(ÄÄÄÄÄÄÄÅÖ±±}…ï—Ö•±ï…}πÖµïÃπ’¡ëÖ—î°Ωlâ…ï—Ö•±ï»âtÅôΩ»ÅºÅ•∏Åï±•ú§(ÄÄÄÄÄÄÄÅ•òÅï±•úË(ÄÄÄÄÄÄÄÄÄÄÄÅΩôôï…}çΩ’π—ÃπÖ¡¡ïπê°±ï∏°ï±•ú§§(ÄÄÄÅ•òÅÖ±±}…ï—Ö•±ï…}πÖµïÃÅÖπêÅΩôôï…}çΩ’π—ÃË(ÄÄÄÄÄÄÄÅÕ°Ω¡}—·–ÄÙÅòùÌΩôôï…}çΩ’π—Õl¡uÙÅâ’—•≠≠ï»úÅ•òÅ±ï∏°Õï–°Ωôôï…}çΩ’π—Ã§§ÄÙÙÄƒÅï±ÕîÅòùÌµ•∏°Ωôôï…}çΩ’π—Ã•˜äMÌµÖ‡°Ωôôï…}çΩ’π—Ã•ÙÅâ’—•≠≠ï»Å¡ï»ÅŸÖ…•Öπ–ú(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù!ΩÃÅ°ŸΩ»ÅµÖπùîÅâ’—•≠≠ï»Å≠Ö∏Å©ïúÅ≠´·¡îÅÌôÖµ•±Â}πÖµïÙ¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùQ•∞ÅÕÖµµï∏ÅÕï±ùï»ÅÌ±ï∏°Ö±±}…ï—Ö•±ï…}πÖµïÃ•ÙÅπΩ…Õ≠îÅπï——â’—•≠≠ï»ÅÏâµ•πÕ–É•∏ÅŸÖ…•Öπ–àÅ•òÅ±ï∏°…Ω›Ã§Ä¯ÄƒÅï±ÕîÄâëïππîÅ±•πÕï∏âÙÄú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÖÿÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏Ä°ÌÕ°Ω¡}—·—Ù§∏ÅMîÅ±•Õ—ï∏Å’πëï»Å°Ÿï»ÅŸÖ…•Öπ–ÅôΩ»Å°Ÿ•±≠îÅâ’—•≠≠ï»ÅÕΩ¥ÅôÖ≠—•Õ¨Å°Ö»Åëï∏Å√îÅ±Öùï»Åªî∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÄåÅA…•ÃÅ¡ï»Å±•πÕîÄ°•≠≠îÅ¡ï»ÅïÕ≠î§Åµï±±Ω¥Åµ•πÕ—îÅΩúÅÕ”·…Õ—îÅ¡Ö≠π•πúÅ%999=H(ÄÄÄÄåÅÕÖµµîÅâï°ΩÿÄ°—Ω…•Õ¨ÅÕÖµµïπ±•ùπïÃÅ≠’∏ÅµïêÅ—Ω…•Õ¨∞Å•≠≠îÅµΩ–ÅÕõô…•Õ¨§Ä¥¥(ÄÄÄÄåÅï≠—îÅ—Ö±±ÕÖµµïπ±•ùπ•πúÅô…ÑÅ¡…•ÕëÖ—Öï∏∞Å•≠≠îÅï∏Åùïπï…•Õ¨ÄâÕ”·……î(ÄÄÄÄåÅ¡Ö≠π•πúÅï»Åâ•±±•ùï…îÅ¡ï»ÅÕ—Â≠¨àµ√ïÕ—ÖπêÅÕΩ¥Å•≠≠îÅª·ëŸïπë•ùŸ•ÃÅÕ—ïµµï»∏(ÄÄÄÄåÅ—–Åï≠Õïµ¡ï∞Åï»ÅπΩ¨Ä¥¥Å’ππüï»Åï∏Å±Öπú∞Å…ï¡ï—•—•ÿÅΩ¡¡±•Õ—•πú∏(ÄÄÄÅ¡Öç≠}çΩµ¡Ö…îÄÙÅ9Ωπî(ÄÄÄÅôΩ»ÅçÖ—}Õ±’ú∞Åù…Ω’¿Å•∏ÅâÂ}çÖ—ïùΩ…‰π•—ïµÃ†§Ë(ÄÄÄÄÄÄÄÅ¡Öç≠ïë}…Ω›ÃÄÙÅm»ÅôΩ»Å»Å•∏Åù…Ω’¿Å•òÅ…lâ¡Öç≠}Õ•ÈîâtÅÖπêÅ…lââïÕ–âut(ÄÄÄÄÄÄÄÅ¡Öç≠Õ}Õïï∏ÄÙÅÕΩ…—ïê°Ì…lâ¡Öç≠}Õ•ÈîâtÅôΩ»Å»Å•∏Å¡Öç≠ïë}…Ω›ÕÙ§(ÄÄÄÄÄÄÄÅ•òÅ±ï∏°¡Öç≠Õ}Õïï∏§ÄÄ»Ë(ÄÄÄÄÄÄÄÄÄÄÄÅçΩπ—•π’î(ÄÄÄÄÄÄÄÅÕµÖ±±}…Ω‹ÄÙÅµ•∏†°»ÅôΩ»Å»Å•∏Å¡Öç≠ïë}…Ω›ÃÅ•òÅ…lâ¡Öç≠}Õ•ÈîâtÄÙÙÅ¡Öç≠Õ}Õïïπl¡t§∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lââïÕ–âulâ¡…•çï}πΩ¨ât§(ÄÄÄÄÄÄÄÅ±Ö…ùï}…Ω‹ÄÙÅµ•∏†°»ÅôΩ»Å»Å•∏Å¡Öç≠ïë}…Ω›ÃÅ•òÅ…lâ¡Öç≠}Õ•ÈîâtÄÙÙÅ¡Öç≠Õ}Õïïπl¥≈t§∞Å≠ï‰ı±ÖµâëÑÅ»ËÅ…lââïÕ–âulâ¡…•çï}πΩ¨ât§(ÄÄÄÄÄÄÄÅÕµÖ±±}¡ï»ÄÙÅÕµÖ±±}…Ω›lââïÕ–âulâ¡…•çï}πΩ¨âtÄºÅ¡Öç≠Õ}Õïïπl¡t(ÄÄÄÄÄÄÄÅ±Ö…ùï}¡ï»ÄÙÅ±Ö…ùï}…Ω›lââïÕ–âulâ¡…•çï}πΩ¨âtÄºÅ¡Öç≠Õ}Õïïπl¥≈t(ÄÄÄÄÄÄÄÅ•òÅÖâÃ°ÕµÖ±±}¡ï»Ä¥Å±Ö…ùï}¡ï»§Ä¯ÙÄ¿∏ÃË(ÄÄÄÄÄÄÄÄÄÄÄÅ¡Öç≠}çΩµ¡Ö…îÄÙÅÏ(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâπïïë}±Öâï∞àËÅ}YI%9Q}9}1	1Lπùï–°çÖ—}Õ±’ú∞ÅçÖ—ïùΩ…•ïÃπùï–°çÖ—}Õ±’ú∞ÅÌÙ§πùï–†â±Öâï∞à∞Äàà§§∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÕµÖ±±}∏àËÅ¡Öç≠Õ}Õïïπl¡t∞Äâ±Ö…ùï}∏àËÅ¡Öç≠Õ}Õïïπl¥≈t∞(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄâÕµÖ±±}¡ï»àËÅÕµÖ±±}¡ï»∞Äâ±Ö…ùï}¡ï»àËÅ±Ö…ùï}¡ï»∞(ÄÄÄÄÄÄÄÄÄÄÄÅÙ(ÄÄÄÄÄÄÄÄÄÄÄÅâ…ïÖ¨(ÄÄÄÅ•òÅ¡Öç≠}çΩµ¡Ö…îË(ÄÄÄÄÄÄÄÅç°ïÖ¡ï…}›Ω…êÄÙÄâÕ”·……îàÅ•òÅ¡Öç≠}çΩµ¡Ö…ïlâ±Ö…ùï}¡ï»âtÄÅ¡Öç≠}çΩµ¡Ö…ïlâÕµÖ±±}¡ï»âtÅï±ÕîÄâµ•πë…îà(ÄÄÄÄÄÄÄÅÕµÖ±±}¡ï…}—·–ÄÙÅòùÌ¡Öç≠}çΩµ¡Ö…ïlâÕµÖ±±}¡ï»âtË∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅ±Ö…ùï}¡ï…}—·–ÄÙÅòùÌ¡Öç≠}çΩµ¡Ö…ïlâ±Ö…ùï}¡ï»âtË∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§(ÄÄÄÄÄÄÄÅë•ôô}—·–ÄÙÅòùÌÖâÃ°¡Öç≠}çΩµ¡Ö…ïlâÕµÖ±±}¡ï»âtÄ¥Å¡Öç≠}çΩµ¡Ö…ïlâ±Ö…ùï}¡ï»ât§Ë∏≈ôÙúπ…ï¡±Öçî†à∏à∞Äà∞à§Ä¨ÄàÅ≠»à(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù3·ππï»Åëï–ÅÕïúÉîÅ≠´·¡îÅÌ¡Öç≠}çΩµ¡Ö…ïlâ±Ö…ùï}∏âuÙµ¡Ö≠π•πúÅô…ïµôΩ»ÅÌ¡Öç≠}çΩµ¡Ö…ïlâÕµÖ±±}∏âuÙµ¡Ö≠π•πú¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÅòùΩ»ÅÌ¡Öç≠}çΩµ¡Ö…ïlâπïïë}±Öâï∞âtπ±Ω›ï»†•ÙÅ≠ΩÕ—ï»ÅÌ¡Öç≠}çΩµ¡Ö…ïlâÕµÖ±±}∏âuÙµ¡Ö≠π•πùï∏ÅçÑ∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌÕµÖ±±}¡ï…}—·—ÙÅ≠»Å¡ï»Å±•πÕî∞ÅµΩ–ÅçÑ∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÌ±Ö…ùï}¡ï…}—·—ÙÅ≠»Å¡ï»Å±•πÕîÅ§ÅÌ¡Öç≠}çΩµ¡Ö…ïlâ±Ö…ùï}∏âuÙµ¡Ö≠π•πùï∏Ä¥¥Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùëï∏ÅÌç°ïÖ¡ï…}›Ω…ëÙÅ¡Ö≠π•πùï∏Åï»Åâ•±±•ùÕ–Å¡ï»Å±•πÕî∞Åï∏ÅôΩ…Õ≠©ï±∞Å√îÅ…’πë–ÅÌë•ôô}—·—Ù∏Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòù!’Õ¨ÉîÅ…ïùπîÅµïêÅô…Ö≠–ÅôΩ»ÅÖ≠≠’…Ö–Åëï–ÅÖπ—Ö±±ï–Åë‘Å—…ïπùï»∞ÅÕ•ëï∏Åô…Ö≠—ùïâÂ»Å≠Ö∏ÅÕπ‘Å…ïùπïÕ—Â≠≠ï–∏ú∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÄåÅπë…ï»Åëï∏Åâ•±±•ùÕ—îÅâ’—•≠≠ï∏ÅÕïúÅµïêÅÖπ—Ö±∞¸Å©ïπâ…’≠ï»ÅÕÖµµî(ÄÄÄÄåÅ—Ω—Ö∞µ¡…•Ãµ¡ï»µÖπ—Ö±∞µ±Ωù•≠¨ÅÕΩ¥ÄâA…•ÃÅŸïêÅô±ï…îÅïÕ≠ï»àÅ§(ÄÄÄÄåÅ…ïπëï…}›•ππï…}›•ëùï–†§Ä°¡…Ωë’≠—¡…•ÃÄ®ÅÖπ—Ö±∞Ä¨Åâï…ïùπï–Åô…Ö≠–§∞Å√îÅëï∏(ÄÄÄÄåÅâ•±±•ùÕ—îÅŸÖ…•Öπ—ï∏Å§ÅôÖµ•±•ï∏∏(ÄÄÄÅ≈—Â}ç°ÖπùîÄÙÅ9Ωπî(ÄÄÄÅ•òÅ±Ω›ïÕ—}…Ω‹ÅÖπêÅ±ï∏°±Ω›ïÕ—}…Ω›lâï±•ù•â±îât§Ä¯ÙÄ»Ë(ÄÄÄÄÄÄÄÅëïòÅ}—Ω—Ö±}ôΩ…}≈—‰°ºËÅë•ç–∞Å≈—‰ËÅ•π–§Ä¥¯Åô±ΩÖ–Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ¡…Ωë’ç—}—Ω—Ö∞ÄÙÅΩlâ¡…•çï}πΩ¨âtÄ®Å≈—‰(ÄÄÄÄÄÄÄÄÄÄÄÅ…ï—’…∏Å¡…Ωë’ç—}—Ω—Ö∞Ä¨ÅçΩµ¡’—ï}Õ°•¡¡•πù}πΩ¨°¡…Ωë’ç—}—Ω—Ö∞∞Åºπùï–†âÕ°•¡¡•πù}¡Ω±•ç‰à§§(ÄÄÄÄÄÄÄÅâïÕ—|ƒÄÙÅµ•∏°±Ω›ïÕ—}…Ω›lâï±•ù•â±îât∞Å≠ï‰ı±ÖµâëÑÅºËÅ}—Ω—Ö±}ôΩ…}≈—‰°º∞Äƒ§§(ÄÄÄÄÄÄÄÅâïÕ—|–ÄÙÅµ•∏°±Ω›ïÕ—}…Ω›lâï±•ù•â±îât∞Å≠ï‰ı±ÖµâëÑÅºËÅ}—Ω—Ö±}ôΩ…}≈—‰°º∞Ä–§§(ÄÄÄÄÄÄÄÅ≈—Â}ç°ÖπùîÄÙÄ°âïÕ—|≈lâ…ï—Ö•±ï»ât∞ÅâïÕ—|—lâ…ï—Ö•±ï»ât§(ÄÄÄÅ•òÅ≈—Â}ç°ÖπùîË(ÄÄÄÄÄÄÄÅÕÖµï}…ï—Ö•±ï»ÄÙÅ≈—Â}ç°Öπùïl¡tÄÙÙÅ≈—Â}ç°Öπùïl≈t(ÄÄÄÄÄÄÄÅôÖ≈}¡…•ÃπÖ¡¡ïπê°Ï(ÄÄÄÄÄÄÄÄÄÄÄÄâ≈’ïÕ—•Ω∏àËÅòù»Åâ•±±•ùÕ—îÅâ’—•≠¨ÅôΩ»ÅÌ±Ω›ïÕ—}…Ω›lâë•Õ¡±ÖÂ}πÖµîâuÙÅëï∏ÅÕÖµµîÅ’ÖπÕï—–Å°ŸΩ»ÅµÖπùîÅïÕ≠ï»Åë‘Å≠´·¡ï»¸ú∞(ÄÄÄÄÄÄÄÄÄÄÄÄâÖπÕ›ï»àËÄ†(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòù)Ñ∞ÅÌ≈—Â}ç°Öπùïl¡uÙÅ°Ö»Å±ÖŸïÕ–Å—Ω—Ö±¡…•ÃÅãïëîÅôΩ»ÄƒÅΩúÅôΩ»Ä–ÅïÕ≠ï»Å§Å€ï»ÅÕ•Õ—îÅ¡…•ÕÕ©ï≠¨∏ú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅ•òÅÕÖµï}…ï—Ö•±ï»Åï±Õî(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòù%≠≠îÅª·ëŸïπë•ùŸ•ÃÄ¥¥ÅÌ≈—Â}ç°Öπùïl¡uÙÅï»Åâ•±±•ùÕ–ÅôΩ»ÄƒÅïÕ≠î∞ÅµïπÃÅÌ≈—Â}ç°Öπùïl≈uÙÅ≠Ö∏Åâ±§Åâ•±±•ùÕ–Å—Ω—Ö±–ÅôΩ»Ä–ÅïÕ≠ï»∞Äú(ÄÄÄÄÄÄÄÄÄÄÄÄÄÄÄÅòùÕ•ëï∏Åô…Ö≠—≠ΩÕ—πÖêÅÕ≥ï»Å’±•≠–Å’–ÅµïêÅÖπ—Ö±∞∏Å	…’¨ÅÖπ—Ö±±ÕŸï±ùï…ï∏Å√îÅ¡…Ωë’≠—Õ•ëï∏ÅôΩ»ÉîÅÕ©ï≠≠îÅÖ≠≠’…Ö–Åë•—–ÅÖπ—Ö±∞∏ú(ÄÄÄÄÄÄÄÄÄÄÄÄ§∞(ÄÄÄÄÄÄÄÅÙ§((ÄÄÄÅôÖµ•±Â}ôÖ≈}°—µ∞∞ÅôÖµ•±Â}ôÖ≈}Õç°ïµÑÄÙÅ}…ïπëï…}ôÖµ•±Â}ôÖ≈}ÖççΩ…ë•Ω∏†(ÄÄÄÄÄÄÄÅl†âA…Ωë’≠–ÅΩúÅŸÖ…•Öπ—ï»à∞ÅôÖ≈}¡…Ωë’≠–§∞Ä†âM¡ïÕ•ô•≠ÖÕ©Ωπï»à∞ÅôÖ≈}Õ¡ïå§∞Ä†âA…•ÃÅΩúÅâ’—•≠≠ï»à∞ÅôÖ≈}¡…•Ã•t∞(ÄÄÄÄÄÄÄÅòù=ô—îÅÕ—•±—îÅÕ√·…Õ∑ï∞ÅΩ¥ÅÌôÖµ•±Â}πÖµïÙú∞(ÄÄÄÄ§((ÄÄÄÅç°Ö•π}°—µ∞ÄÙÄàà(ÄÄÄÅë•Õ¡±ÖÂ}πÖµï}ôΩ…}—•—±îÄÙÅôÖµ•±Â}πÖµî(ÄÄÄÅ•òÅç°Ö•∏Ë(ÄÄÄÄÄÄÄÅç°Ö•π}°—µ∞ÄÙÅòúúúÒë•ÿÅç±ÖÕÃÙâ¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»à¯(ÄÄÄÄÒ¿¯ÒÕ—…Ωπú˘=¥ÅπÖŸπï–ËΩÕ—…Ωπú¯ÅÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙÅï»ÅπÖŸπï–ÅëïππîÅÕï…•ï∏ÅÕï±ùïÃÅ’πëï»∏ÅMîÅ°Ÿï»Åïπ≠ï±–ÅŸÖ…•Öπ—Ã(ÄÄÄÅÕ•ëîÅôΩ»Å°Ÿ•±≠ï–Åï≠—îÅ¡…Ωë’≠–Åëï∏Å—•±ÕŸÖ…ï»ÅΩúÅ°Ÿ•±≠ï∏Å≠©ïëîÅÕΩ¥ÅÕ”ï»ÅâÖ¨∏Ω¿¯(ÄÄΩë•ÿ¯úúú((ÄÄÄÄåÅ±Â——ï–Å±ïπùï»ÅπïêÄ†»¿»ÿ¥¿‰¥»‹∞Å-Ö§ËÄâ∑îÅŸ§Å°ÑÅëïππîÅ°ï»∞Åï±±ï»Å≠Ö∏ÅŸ§(ÄÄÄÄåÅÕï——îÅëï∏Å±ïπù…îÅπïê¸Åπï≠Ã∏Å’πëï»ÅA…•Õ•ππÕ•≠–à§Ä¥¥ÅŸ•ÕïÃÅªîÅï——ï»(ÄÄÄÄåÅ¡…•Õ•ππÕ•≠—ï∏ºâ-Ω…–ÅΩ¥àµ…Öëï∏Å§ÅÕ—ïëï–ÅôΩ»Å…ï—–Å’πëï»Å°ï…Ωï∏∏(ÄÄÄÅÖ•}Õ’µµÖ…Â}°—µ∞ÄÙÄàà(ÄÄÄÅ•òÅ±Ω›ïÕ—}…Ω‹ÅÖπêÅ±Ω›ïÕ—}…Ω›lââïÕ–âtË(ÄÄÄÄÄÄÄÅπ}ŸÖ…•Öπ—ÃÄÙÅ±ï∏°…Ω›Ã§(ÄÄÄÄÄÄÄÅÖ•}Õ’µµÖ…Â}°—µ∞ÄÙÅòúúúÒÕïç—•Ω∏Åç±ÖÕÃÙâ¡…Ωë’ç–µÖ§µÕ’µµÖ…‰àÅÖ…•Ñµ±Öâï∞ÙâA…•ÕΩ¡¡Õ’µµï…•πúà¯(ÄÄÒ¿˘Y§ÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√îÅÖ±±îÅÌπ}ŸÖ…•Öπ—ÕÙÅŸÖ…•Öπ—ïπîÅ§ÅÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙµÕï…•ï∏∏Å	•±±•ùÕ–ÅÖ≠≠’…Ö–ÅªîÅï»(ÄÄÒÕ—…Ωπú˘ÌïÕçÖ¡î°±Ω›ïÕ—}…Ω›lâë•Õ¡±ÖÂ}πÖµîât•ÙΩÕ—…Ωπú¯Åô…ÑÄÒÕ—…Ωπú˘Ì}ôµ—}≠»°±Ω›ïÕ—}…Ω›lââïÕ–âulâ¡…•çï}πΩ¨ât•ÙΩÕ—…Ωπú¯(ÄÅ°ΩÃÅÌïÕçÖ¡î°±Ω›ïÕ—}…Ω›lââïÕ–âulâ…ï—Ö•±ï»ât•ÙÄ°’—ï∏Åô…Ö≠–§∏ÅA…•ÕïπîÅΩ¡¡ëÖ—ï…ïÃÅëÖù±•ú∞ÅÕ•Õ–Åâï≠…ïô—ï–ÅÌ}Ÿï…•ô•ïë}—Öú°}πï›ïÕ—}ç°ïç≠ïê°mºÅôΩ»Å»Å•∏Å…Ω›ÃÅôΩ»ÅºÅ•∏Å…lâ¡…Ωë’ç–âulâΩôôï…Ãâut§•Ù∏Ω¿¯(ΩÕïç—•Ω∏¯úúú((ÄÄÄÅµï—Ö}ëïÕç…•¡—•Ω∏ÄÙÄ†(ÄÄÄÄÄÄÄÅòùMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ°ï±îÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏ÉäLÅÕõô…•Õ¨∞Å—Ω…•Õ¨ÅΩúΩï±±ï»Åµ’±—•ôΩ≠Ö∞ÉäLÄú(ÄÄÄÄÄÄÄÅòùô…ÑÅÌ}ôµ—}≠»°µ•∏°¡…•çïÃ§•Ù∏Å=¡¡ëÖ—ï…–ÅëÖù±•ú∏ú(ÄÄÄÄ§Å•òÅ¡…•çïÃÅï±ÕîÅòùMÖµµïπ±•ù∏Å¡…•Õï»Å√îÅ°ï±îÅÌôÖµ•±Â}πÖµïÙµÕï…•ï∏∏ú((ÄÄÄÅ•—ïµ}±•Õ—}•—ïµÃÄÙÅmt(ÄÄÄÅÕç°ïµÖ}Ωôôï…Õ}âÂ}µïµâï»ÄÙÅmt(ÄÄÄÅôΩ»Å§∞Å»Å•∏Åïπ’µï…Ö—î°…Ω›Ã∞ÅÕ—Ö…–Ùƒ§Ë(ÄÄÄÄÄÄÄÅ¿ÄÙÅ…lâ¡…Ωë’ç–ât(ÄÄÄÄÄÄÄÅ¡}Ωôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°¡lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅ¡}•π}Õ—Ωç¨ÄÙÅmºÅôΩ»ÅºÅ•∏Å¡}Ωôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÄÄÄÄÅΩôôï…Õ}ô•ï±êÄÙÄàà(ÄÄÄÄÄÄÄÅ•òÅ¡}•π}Õ—Ωç¨Ë(ÄÄÄÄÄÄÄÄÄÄÄÅ±Ω‹ÄÙÅµ•∏°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å¡}•π}Õ—Ωç¨§(ÄÄÄÄÄÄÄÄÄÄÄÅ°•ù†ÄÙÅµÖ‡°Ωlâ¡…•çï}πΩ¨âtÅôΩ»ÅºÅ•∏Å¡}•π}Õ—Ωç¨§(ÄÄÄÄÄÄÄÄÄÄÄÅΩôôï…Õ}ô•ï±êÄÙÅòúúú∞ÄâΩôôï…ÃàËÅÌÏâ—Â¡îàËÄâùù…ïùÖ—ï=ôôï»à∞Äâ¡…•çï’……ïπç‰àËÄâ9=,à∞Äâ±Ω›A…•çîàËÅÌ±Ω›Ù∞Äâ°•ù°A…•çîàËÅÌ°•ù°Ù∞ÄâΩôôï…Ω’π–àËÅÌ±ï∏°¡}•π}Õ—Ωç¨•ııÙúúú(ÄÄÄÄÄÄÄÅ•—ïµ}±•Õ—}•—ïµÃπÖ¡¡ïπê°òúúùÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÅÌ•Ù∞Äâ•—ï¥àËÅÌÏ(ÄÄÄÄÄÄâ—Â¡îàËÄâA…Ωë’ç–à∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°…lâë•Õ¡±ÖÂ}πÖµîât•Ùà∞Äâ’…∞àËÄâÌ	M}UI1ıÌ…lâ°…ïòâuÙâÌΩôôï…Õ}ô•ï±ëÙ(ÄÄÄÅıııÙúúú§(ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòúúùÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâù…Ö¡†àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°ôÖµ•±Â}πÖµî•Ùà∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩÕï…•îΩÌôÖµ•±Â}Õ±’ùÙºâıÙ(ÄÄÄÅuıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâΩ±±ïç—•ΩπAÖùîà∞ÄâπÖµîàËÄâÌ}©ÕΩπ}Õ—»°ôÖµ•±Â}πÖµî•Ùà∞ÄâµÖ•ππ—•—‰àËÅÌÏ(ÄÄÄÄÄÄâ—Â¡îàËÄâ%—ïµ1•Õ–à∞Äâ•—ïµ1•Õ—±ïµïπ–àËÅmÏà∞àπ©Ω•∏°•—ïµ}±•Õ—}•—ïµÃ•ıt(ÄÄÄÅıııÙ(ÄÅt)ıÙúúú((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘ÌïÕçÖ¡î°ë•Õ¡±ÖÂ}πÖµï}ôΩ…}—•—±î•ÙµÕï…•ï∏É
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•ÃΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°µï—Ö}ëïÕç…•¡—•Ω∏•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩÕï…•îΩÌôÖµ•±Â}Õ±’ùÙºà¯)Ì}Ωù}µï—Ñ°òùÌë•Õ¡±ÖÂ}πÖµï}ôΩ…}—•—±ïÙµÕï…•ï∏É
ÏÅMÖµµïπ±•ù∏ÅΩúÅõîÅâ•±±•ùÕ—îÅ¡…•Ãú∞Åµï—Ö}ëïÕç…•¡—•Ω∏∞ÅòùÌ	M}UI1ÙΩÕï…•îΩÌôÖµ•±Â}Õ±’ùÙºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯)ÌôÖµ•±Â}ôÖ≈}Õç°ïµÖÙ(ÒÕ—Â±î˘ÌM!I}MQe1Ù(º®ÅA…ïµ•’¥Å—Ω¡¡âÖππï»Ä†»¿»ÿ¥¿‰¥»‹∞ÅQPÅëï±–Åâ•±ëîÅôΩ»ÅÖ±±îÅÕï…•îµÕ•ëï»Ä¥¥(ÄÄÅÕ—Ö—•åΩ°ï…ºΩÕï…•îµÌÏ‘ÿ¿∞‡–¿∞ƒƒ»¡ıÙπ›ïâ¿∞ÅÕÖµµîÅâïÕ≠´ô…•πùÃ¥ΩôÖëîµ—ï≠π•≠¨(ÄÄÅÕΩ¥ÅôΩ…Õ•ëïπÃÅ°ï…º§∏ÅùπîÅ≠±ÖÕÕïπÖŸ∏Ä°Õï…•îµ°ï…º®§Å§ÅÕ—ïëï–ÅôΩ»Éî(ÄÄÅù©ïπâ…’≠îÄπ°ï…ºµçÖ…êºπ°ï…ºµ¡…Ωë’ç–µ•µÖùîÄ¥¥Åëï–Å7a9MQIPÄ°¡…Ωë’≠—â•±ëî(ÄÄÅ§Åïùï∏ÅâΩ≠Ã§Åï»ÅªîÅâïŸ•ÕÕ–ÅôΩ…âï°Ω±ë–ÅÕï±ŸîÅ—Öâï±±ï∏Ω¡Ö≠π•πùÕâ•±ëïπî∞(ÄÄÅ•≠≠îÅ°ï…Ωï∏∞ÅÕîÅ-Ö§ÅÕ•∏Å—•±âÖ≠ïµï±ë•πúÅΩ¥ÅÖ–ÅôΩ»ÅµÖπùîÅ’±•≠îÅ±•πÕïâ•±ëï»(ÄÄÅ√îÅÕÖµµîÅÕ•ëîÅâ±•»Å…Ω—ï—î∏Ä®º(πÕï…•îµ°ï…ºÅÌÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ»—¡‡ÏÅâÖç≠ù…Ω’πêËÅ±•πïÖ»µù…Öë•ïπ–†ƒ¿¡ëïú∞ÄçÄ¿î∞ÄçŸÂÄ‘‘î∞ÄçÂ≈Äƒ¿¿î§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ¡Öëë•πúËÄ»…¡‡Ä»—¡‡ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄ»¡¡‡ÏÅıÙ(πÕï…•îµ°ï…ºµçΩπ—ïπ–ÅÌÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅËµ•πëï‡ËÄ»ÏÅıÙ(πÕï…•îµ°ï…ºÅ†ƒÅÌÏÅôΩπ–µÕ•ÈîËÅç±Öµ¿†ƒ∏’…ï¥∞Ä—Ÿ‹∞Ä……ï¥§ÏÅµÖ…ù•∏ËÄ—¡‡Ä¿Ä·¡‡ÏÅıÙ(πÕï…•îµ°ï…ºµµïë•ÑÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(º®Åùï∏Å…Öê∞Å%--Å•ππ§ÄπÕï…•îµ°ï…ºµçΩπ—ïπ–Ä¥¥ÅœîÅëï∏Å≠Ö∏Åâ…’≠îÅ°ï±îÅ≠Ω…—ï—Ã(ÄÄÅâ…ïëëîÄ°•≠≠îÅâÖ…îÅ—ï≠Õ—≠Ω±ΩππïπÃÄ‘ÿÄî§ÅΩúÅõîÅ¡±ÖÕÃÅ—•∞ÅÖ±±îÅ¡•±±ïπîÅ√îÉ•∏(ÄÄÅ±•π©îÄ°-Ö§Ä»¿»ÿ¥¿‰¥»‹ËÄâ≠Ö∏ÅŸ§ÅõîÅë•ÕÕîÅ√îÅï∏Å±•π©îÄ∏∏∏ÅΩúÅâΩ…—ΩŸï»Å—•∞(ÄÄÅ£·Â…î¸à§∏Ä®º(πÕï…•îµÕ—Ö–µ¡•±±ÃÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅùÖ¿ËÄ·¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ—¡‡ÏÅ¡ΩÕ•—•Ω∏ËÅ…ï±Ö—•ŸîÏÅËµ•πëï‡ËÄ»ÏÅıÙ(πÕï…•îµÕ—Ö–µ¡•±∞ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄ·¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄŸ¡‡Äƒ¡¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πÕï…•îµÕ—Ö–µ•çΩ∏ÅÌÏÅ›•ë—†ËÄ»—¡‡ÏÅ°ï•ù°–ËÄ»—¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅıÙ(πÕï…•îµÕ—Ö–µ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄƒÕ¡‡ÏÅ°ï•ù°–ËÄƒÕ¡‡ÏÅıÙ(πÕï…•îµÕ—Ö–µ±Öâï∞ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏»‘ÏÅıÙ(πÕï…•îµÕ—Ö–µŸÖ±’îÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡……ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏»‘ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§ÅÌÏ(ÄÄπÕï…•îµ°ï…ºÅÌÏÅ¡Öëë•πúËÄ»Ÿ¡‡Ä–¡¡‡Ä»—¡‡ÏÅıÙ(ÄÄπÕï…•îµ°ï…ºµçΩπ—ïπ–ÅÌÏÅµÖ‡µ›•ë—†ËÄ‘ÿîÏÅıÙ(ÄÄπÕï…•îµ°ï…ºµµïë•ÑÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ¡ΩÕ•—•Ω∏ËÅÖâÕΩ±’—îÏÅ—Ω¿ËÄ¿ÏÅ…•ù°–ËÄ¿ÏÅâΩ——Ω¥ËÄ¿ÏÅ›•ë—†ËÄ–ÿîÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅâΩ…ëï»µ…Öë•’ÃËÄ¿Ä»—¡‡Ä»—¡‡Ä¿ÏÅ¡Ω•π—ï»µïŸïπ—ÃËÅπΩπîÏÄµ›ïâ≠•–µµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–¿î§ÏÅµÖÕ¨µ•µÖùîËÅ±•πïÖ»µù…Öë•ïπ–†‰¡ëïú∞Å—…ÖπÕ¡Ö…ïπ–Ä¿∞Äå¿¿¿Ä–¿î§ÏÅıÙ(ÄÄπÕï…•îµ°ï…ºµµïë•ÑÅ•µúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅΩâ©ïç–µ¡ΩÕ•—•Ω∏ËÅ…•ù°–Åçïπ—ï»ÏÅıÙ(ÄÄπÕï…•îµÕ—Ö–µ¡•±±ÃÅÌÏÅô±ï‡µ›…Ö¿ËÅπΩ›…Ö¿ÏÅıÙ)ıÙ(º®Äâ•π∏Åë•∏ÅŸÖ…•Öπ–àÄ¥¥Åù©ïπâ…’≠ï»Å≠Ö—ïùΩ…•≠Ω…—ïπïÃÅïùπîÅ¡ÖÕ—ï±±â•±ëï»(ÄÄÄ°Õ—Ö—•åΩçÖ—ïùΩ…•ïÃΩâú¥®§∞Å%--ÅπÂîÅ±•πÕïâ•±ëï»Ä¥¥ÅÕîÅ≠Ωµµïπ—Ö…ï∏Å§(ÄÄÅAÂ—°Ω∏µ≠Ωëï∏ÅΩŸï»ÅôΩ»Åâïù…’ππï±Õï∏∏ÅM—…Öµµï–Å•π∏Ä»¿»ÿ¥¿‰¥»‹Ä°-Ö§ËÄâ±•—–(ÄÄÅµï»Å≠Ωµ¡…•µï…–Ä∏∏∏Åï»Å±•—–ÅµÂîÅ±’ô–à§∏Ä®º(πŸÖ…•Öπ–µô•πëï»µ±ïÖêÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ¡¡‡ÏÅıÙ(πŸÖ…•Öπ–µô•πëï»µù…•êÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–°Ö’—ºµô•–∞Åµ•πµÖ‡†»»¡¡‡∞Ä≈ô»§§ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄƒ¡¡‡ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ…¡‡ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅ¡Öëë•πúËÄƒ≈¡‡Äƒ—¡‡ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏ƒ’Ã∞ÅâΩ‡µÕ°ÖëΩ‹Ä¿∏ƒ’ÃÏÅµ•∏µ°ï•ù°–ËÄÿ¡¡‡ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êÈ°ΩŸï»ÅÌÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¥…¡‡§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Äƒ¡¡‡Ä»—¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒ–§ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµ—°’µàÅÌÏÅ›•ë—†ËÄ–·¡‡ÏÅ°ï•ù°–ËÄ–·¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄÂ¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµâúÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµ—ï·–ÅÌÏÅô±ï‡ËÄƒÏÅµ•∏µ›•ë—†ËÄ¿ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµπïïêÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿ·…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿Õï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµπÖµîÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏Â…ï¥ÏÅµÖ…ù•∏µ—Ω¿ËÄ≈¡‡ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµ¡Öç≠ÃÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹Ÿ…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏µ—Ω¿ËÄ≈¡‡ÏÅıÙ(πŸÖ…•Öπ–µçÖ…êµÖ……Ω‹ÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅıÙ(πŸÖ…•Öπ–µô•πëï»µπΩ—îÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅùÖ¿ËÄÂ¡‡ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ¡¡‡ÄƒÕ¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ·¡‡ÏÅıÙ(πŸÖ…•Öπ–µô•πëï»µπΩ—îÅÕŸúÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄƒ›¡‡ÏÅ°ï•ù°–ËÄƒ›¡‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅµÖ…ù•∏µ—Ω¿ËÄ≈¡‡ÏÅıÙ(πŸÖ…•Öπ–µô•πëï»µπΩ—îÅ¿ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(º®ÅA…•Õ•ππÕ•≠–Ä°ŸïπÕ—…î§Ä¨Äâ-Ω…–ÅΩ¥Å`àÄ°£·Â…î§ÅÕ•ëîÅΩ¥ÅÕ•ëîÄ¥¥Å-Ö§Ä»¿»ÿ¥¿‰¥»‹Ë(ÄÄÄâÕ±•¨ÅÖ–ÅŸ§Åõï»Åï∏Å≠Ωµ¡…•µï…–Å¡…•Õ•ππÕ•≠–à∏Å9’±±Õ—•±±ï»ÅµÖ…ù•πïπîÅ—•∞ÅëîÅ—º(ÄÄÅâΩ≠ÕïπîÅªï»ÅëîÅÕ”ï»Å§ÅëïππîÅ…Öëï∏Ä°ïùπîÅµÖ…ùï»Åù•»ÅëΩââï∞ÅÖŸÕ—ÖπêÅï±±ï…Ã§∏Ä®º(πÕï…•îµ•πÕ•ù°–µ…Ω‹ÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»ÏÅùÖ¿ËÄƒŸ¡‡ÏÅµÖ…ù•∏ËÄ·¡‡Ä¿Ä»—¡‡ÏÅıÙ(πÕï…•îµ•πÕ•ù°–µ…Ω‹Ä¯Äπ¡…•çîµ•πÕ•ù°–∞ÄπÕï…•îµ•πÕ•ù°–µ…Ω‹Ä¯ÄπÕï…•îµôÖç—ÃÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄƒ¿»—¡‡§ÅÌÏ(ÄÄπÕï…•îµ•πÕ•ù°–µ…Ω‹ÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄƒ∏’ô»Ä≈ô»ÏÅÖ±•ù∏µ•—ïµÃËÅÕ—…ï—ç†ÏÅıÙ)ıÙ(πÕï…•îµôÖç—ÃÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúËÄ»¡¡‡Ä»…¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πÕï…•îµôÖç—ÃÅ†»ÅÌÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ…¡‡ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅıÙ(πÕï…•îµôÖç—Ãµ±•Õ–ÅÌÏÅ±•Õ–µÕ—Â±îËÅπΩπîÏÅµÖ…ù•∏ËÄ¿ÏÅ¡Öëë•πúËÄ¿ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅùÖ¿ËÄƒ≈¡‡ÏÅıÙ(πÕï…•îµôÖç—Ãµ±•Õ–Å±§ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅùÖ¿ËÄƒ¡¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡Ÿ…ï¥ÏÅıÙ(πÕï…•îµôÖç—Ãµ±•Õ–ÅÕŸúÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄƒ·¡‡ÏÅ°ï•ù°–ËÄƒ·¡‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅµÖ…ù•∏µ—Ω¿ËÄ≈¡‡ÏÅıÙ(πÕï…•îµôÖç—Ãµ±•Õ–ÅÕ—…ΩπúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅıÙ(πÕï…•îµôÖç—Ãµ±•Õ–ÅÕ¡Ö∏ÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏µ—Ω¿ËÄ≈¡‡ÏÅıÙ(π¡…•çîµ•πÕ•ù°–ÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúËÄ»¡¡‡Ä»…¡‡ÏÅµÖ…ù•∏ËÄ·¡‡Ä¿Ä»—¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ°ïÖêÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅô±ï‡µ›…Ö¿ËÅ›…Ö¿ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ…ù•∏µâΩ——Ω¥ËÄƒ—¡‡ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ°ïÖêÅ†»ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅıÙ(π•πÕ•ù°–µ—ÖâÃÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅùÖ¿ËÄ—¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅ¡Öëë•πúËÄÕ¡‡ÏÅıÙ(π•πÕ•ù°–µ—ÖàÅÌÏÅâΩ…ëï»ËÅπΩπîÏÅâÖç≠ù…Ω’πêËÅπΩπîÏÅ¡Öëë•πúËÄŸ¡‡Äƒ—¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ·¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡……ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅôΩπ–µôÖµ•±‰ËÅ•π°ï…•–ÏÅıÙ(π•πÕ•ù°–µ—ÖàπÖç—•ŸîÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ¡Öπï∞ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ¡Öπï∞πÖç—•ŸîÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»ÏÅùÖ¿ËÄƒ·¡‡ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µç’……ïπ–ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ»∏≈…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ±Öâï∞ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‡……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏µ—Ω¿ËÄ…¡‡ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ—…ïπêÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄŸ¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄ·¡‡ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ—…ïπêµπΩ—îÅÌÏÅôΩπ–µ›ï•ù°–ËÄ–¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅıÙ(π•πÕ•ù°–µëΩ›∏ÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µµ•π–§ÏÅıÙ(π•πÕ•ù°–µ’¿ÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µçΩ…Ö∞§ÏÅıÙ(π•πÕ•ù°–µô±Ö–ÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ—•±ïÃÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†Ã∞Ä≈ô»§ÏÅùÖ¿ËÄ·¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄƒŸ¡‡ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ—•±îÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ¡¡‡ÏÅ¡Öëë•πúËÄ·¡‡ÄŸ¡‡ÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ—•±îÅÕ—…ΩπúÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ¿∏Â…ï¥ÏÅıÙ(π¡…•çîµ•πÕ•ù°–µ—•±îÅÕ¡Ö∏ÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅôΩπ–µÕ•ÈîËÄ¿∏ÿŸ…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏µ—Ω¿ËÄ…¡‡ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÃÏÅıÙ(π¡…•çîµ•πÕ•ù°–µç°Ö…–Äπ¡…•çîµ°•Õ—Ω…‰ÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄ¿ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§ÅÌÏ(ÄÄπ¡…•çîµ•πÕ•ù°–µ¡Öπï∞πÖç—•ŸîÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»Äƒ∏Õô»ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅıÙ)ıÙ(πÕ¡ïåµ—Öâ±îµçÖ…êÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πÕ¡ïåµ—Öâ±îÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅâΩ…ëï»µçΩ±±Ö¡ÕîËÅçΩ±±Ö¡ÕîÏÅıÙ(πÕ¡ïåµ—Öâ±îÅ—†∞ÄπÕ¡ïåµ—Öâ±îÅ—êÅÌÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ—¡‡ÏÅ—ï·–µÖ±•ù∏ËÅ±ïô–ÏÅâΩ…ëï»µâΩ——Ω¥ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅıÙ(πÕ¡ïåµ—Öâ±îÅ—°ïÖêÅ—†ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿Õï¥ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅıÙ(πÕ¡ïåµ—Öâ±îÅ—âΩë‰Å—»È±ÖÕ–µç°•±êÅ—êÅÌÏÅâΩ…ëï»µâΩ——Ω¥ËÅπΩπîÏÅıÙ(πÕ¡ïåµ—Öâ±îÅ—âΩë‰Å—»È°ΩŸï»ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅıÙ(πÕ¡ïåµ—Öâ±îÅÑÅÌÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅùÖ¿ËÄƒ¡¡‡ÏÅıÙ(πÕ¡ïåµ…Ω‹µ—°’µàÅÌÏÅ›•ë—†ËÄÃ…¡‡ÏÅ°ï•ù°–ËÄÃ…¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ›¡‡ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅΩâ©ïç–µô•–ËÅçΩπ—Ö•∏ÏÅ¡Öëë•πúËÄÕ¡‡ÏÅâΩ‡µÕ•È•πúËÅâΩ…ëï»µâΩ‡ÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µâ±’îµ—•π–§ÏÅâΩ…ëï»µ±ïô–ËÄ—¡‡ÅÕΩ±•êÅŸÖ»†¥µâ±’î§ÏÅâΩ…ëï»µ…Öë•’ÃËÄ¿Äƒ¡¡‡Äƒ¡¡‡Ä¿ÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ·¡‡ÏÅµÖ…ù•∏ËÄƒŸ¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰’…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(π¡…Ωë’ç–µÖ§µÕ’µµÖ…‰Å¿ÅÌÏÅµÖ…ù•∏ËÄ¿ÏÅıÙ(π¡…•ŸÖ—îµ±Öâï∞µï·¡±Ö•πï»ÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ·¡‡Ä»¡¡‡ÏÅµÖ…ù•∏ËÄ»¡¡‡Ä¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏ÿÏÅıÙ(º®Äâï±±ïÃÅôΩ»Å°ï±îÅÕï…•ï∏àÄ°ÕÖµµîÅôÖ≠—ÑÅÕΩ¥Äâ-Ω…–ÅΩ¥Å`àÅŸïêÅA…•Õ•ππÕ•≠–∞(ÄÄÅµï∏Å§Åï–Å≠Ωµ¡Ö≠–Å•≠Ω∏µ…’—ïπï—–Å-Ö§ÅÕ¡ïÕ•ô•≠–ÅâÑÅΩ¥Ä»¿»ÿ¥¿‰¥»‹Ä¥¥ÅëîÅ—º(ÄÄÅâΩ≠ÕïπîÅëï≠≠ï»ÅÕÖµµîÅôÖ≠—ÑÅµïêÅŸ•±©î∞ÅÕ•ëï∏ÅëîÅ°Ö»Å’±•¨Å…Ω±±îËÉ•∏Åï»(ÄÄÅõ·±ùïÕŸïπ∏Å—•∞ÅA…•Õ•ππÕ•≠–∞Åëï∏ÅÖπë…îÅ—•∞ÅIï±ïŸÖπ—îÅù’•ëï»Å±ïπùï»Åπïê∏§Ä®º(πÕï…•îµâΩ——Ω¥µ…Ω‹ÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»ÏÅùÖ¿ËÄƒŸ¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄ»—¡‡ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄ‰¿¡¡‡§ÅÌÏÄπÕï…•îµâΩ——Ω¥µ…Ω‹ÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»Ä≈ô»ÏÅÖ±•ù∏µ•—ïµÃËÅÕ—…ï—ç†ÏÅıÙÅıÙ(º®Å	ïùùîÅâΩ≠ÕïπîÅ§Å…Öëï∏Åï»ÅªîÅï–ÄâµÖ—ç°ïπëîÅ¡Ö»àÄ°-Ö§Ä»¿»ÿ¥¿‰¥»‹ËÄâ…•≠—•ú(ÄÄÅ¡…Ω¡Ω…Õ©Ωπï…–Å§Å£·Âëî∞ÅâΩ≠ÃÅ…’πë–Åï—åÅœîÅëï–Åâ±•»Å—•±ªô…µï–Å±•≠–à§Ä¥¥(ÄÄÅÕÖµµîÅ≠Ω…–µÕ—•∞Ä°°Ÿ•–ÅâΩ≠Ã∞ÅÕÖµµîÅâΩ…ëï»Ω…Öë•’ÃΩÕ≠Âùùî∞ÅÕÖµµî(ÄÄÅ†»µÕ”·……ï±Õî§Å√îÅÄπÕï…•îµôÖç—Ãµ—•±ïÃÅΩúÄπÕï…•îµù’•ëïÃ∞ÅΩú(ÄÄÅÖ±•ù∏µ•—ïµÃÈÕ—…ï—ç†ÅΩŸï»Åù´·»ÅÖ–ÅëîÅÖ±±—•êÅõï»ÅÕÖµµîÅ£·ÂëîÅÕΩ¥(ÄÄÅ°Ÿï…Öπë…îÄ°ëï∏Å£·ÂïÕ—îÅÖÿÅëîÅ—ºÅâïÕ—ïµµï»§∏ÄπÕï…•îµôÖç—Ãµ—•±ïÃÅÕ•—–(ÄÄÅ•ππ°Ω±êÅï»Å≠Ω…—ï…îÄ£•∏Å…ÖêÅ•≠Ω∏µô±•Õï»§∞ÅœîÅÕï±ŸîÅô±•Õîµ…’—ïπï——ï–(ÄÄÅÕïπ—…ï…ïÃÅŸï…—•≠Ö±–Å§Åëï∏Å±ïë•ùîÅ¡±ÖÕÕï∏Ä°µÖ…ù•∏µ—Ω¿ΩâΩ——Ω¥ÈÖ’—º§(ÄÄÅ§ÅÕ—ïëï–ÅôΩ»ÉîÅ°ïπùîÉ·Ÿï…Õ–ÅµïêÅï–ÅÕ—Ω…–Å—Ωµ…Ω¥Å’πëï»∏Ä®º(πÕï…•îµôÖç—Ãµ—•±ïÃÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúËÄ»¡¡‡Ä»…¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ°ï•ù°–ËÄƒ¿¿îÏÅâΩ‡µÕ•È•πúËÅâΩ…ëï»µâΩ‡ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅô±ï‡µë•…ïç—•Ω∏ËÅçΩ±’µ∏ÏÅıÙ(πÕï…•îµôÖç—Ãµ—•±ïÃÅ†»ÅÌÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ—¡‡ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅıÙ(πÕï…•îµôÖç—Ãµ—•±ïÃµù…•êÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–°Ö’—ºµô•–∞Åµ•πµÖ‡†‰¡¡‡∞Ä≈ô»§§ÏÅùÖ¿ËÄƒ¡¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÅÖ’—ºÏÅµÖ…ù•∏µâΩ——Ω¥ËÅÖ’—ºÏÅıÙ(πÕï…•îµôÖç–µ—•±îÅÌÏÅ—ï·–µÖ±•ù∏ËÅçïπ—ï»ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅ¡Öëë•πúËÄƒ—¡‡Ä·¡‡ÏÅıÙ(πÕï…•îµôÖç–µ—•±îµ•çΩ∏ÅÌÏÅ›•ë—†ËÄÃŸ¡‡ÏÅ°ï•ù°–ËÄÃŸ¡‡ÏÅâΩ…ëï»µ…Öë•’ÃËÄ‘¿îÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅçïπ—ï»ÏÅµÖ…ù•∏ËÄ¿ÅÖ’—ºÄ·¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅıÙ(πÕï…•îµôÖç–µ—•±îµ•çΩ∏ÅÕŸúÅÌÏÅ›•ë—†ËÄƒ·¡‡ÏÅ°ï•ù°–ËÄƒ·¡‡ÏÅıÙ(πÕï…•îµôÖç–µ—•±îµŸÖ±’îÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏»‘ÏÅıÙ(πÕï…•îµôÖç–µ—•±îµ±Öâï∞ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏‹……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏µ—Ω¿ËÄ…¡‡ÏÅıÙ(πÕï…•îµôÖç–µπΩ—îÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅùÖ¿ËÄ·¡‡ÏÅÖ±•ù∏µ•—ïµÃËÅô±ï‡µÕ—Ö…–ÏÅµÖ…ù•∏µ—Ω¿ËÄƒ—¡‡ÏÅôΩπ–µÕ•ÈîËÄ¿∏‹·…ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘ÏÅıÙ(πÕï…•îµôÖç–µπΩ—îÅÕŸúÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄƒ’¡‡ÏÅ°ï•ù°–ËÄƒ’¡‡ÏÅµÖ…ù•∏µ—Ω¿ËÄ≈¡‡ÏÅıÙ(º®ÄâIï±ïŸÖπ—îÅù’•ëï»àÄ¥¥Åâ•±ëï≠Ω…–Ä°ŸÖ»Å…ï∏Å•≠Ω∏µ≠Ω…–µ…’—ïπï—–∞ÅÕî(ÄÄÅ≠Ωµµïπ—Ö…ï∏Å§ÅAÂ—°Ω∏µ≠Ωëï∏ÅΩŸï»§Ä¥¥Åô•≠¨Å1I$Åï∏ÅâΩ≠ÃÅ…’πë–ÅÕïúÅÕï±ÿ∞(ÄÄÅâÖ…îÅï∏ÅâÖ»ÅΩŸï…Õ≠…•ô–Ä¨Å…’—ïπï—–Åë•…ï≠—îÅ√îÅÕ•ëïâÖ≠ù…’ππï∏∞Åëï…ôΩ»(ÄÄÅµ•ÕµÖ—ç°ï–Åëï∏ÅÕÂπ±•úÅµΩ–Äâï±±ïÃÅôΩ»Å°ï±îÅÕï…•ï∏àÅÕ•∏Å°Ÿ•—îÅâΩ≠Ã∏(ÄÄÅMÖµµîÅ≠Ω…–µÕ—•∞ÅªîÄ°ÕîÅ≠Ωµµïπ—Ö…ï∏ÅΩŸï»ÄπÕï…•îµôÖç—Ãµ—•±ïÃ§∏Ä®º(πÕï…•îµù’•ëïÃÅÌÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒŸ¡‡ÏÅ¡Öëë•πúËÄ»¡¡‡Ä»…¡‡ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ°ï•ù°–ËÄƒ¿¿îÏÅâΩ‡µÕ•È•πúËÅâΩ…ëï»µâΩ‡ÏÅıÙ(πÕï…•îµù’•ëïÃÅ†»ÅÌÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ—¡‡ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄƒ∏¿’…ï¥ÏÅıÙ(πù’•ëîµ¡°Ω—ºµù…•êÅÌÏÅë•Õ¡±Ö‰ËÅù…•êÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÄ≈ô»ÏÅùÖ¿ËÄƒ…¡‡ÏÅıÙ)µïë•ÑÄ°µ•∏µ›•ë—†ËÄÿ–¡¡‡§ÅÌÏÄπù’•ëîµ¡°Ω—ºµù…•êÅÌÏÅù…•êµ—ïµ¡±Ö—îµçΩ±’µπÃËÅ…ï¡ïÖ–†Ã∞Ä≈ô»§ÏÅıÙÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êÅÌÏÅë•Õ¡±Ö‰ËÅâ±Ωç¨ÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ—¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅ—ï·–µëïçΩ…Ö—•Ω∏ËÅπΩπîÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅâΩ‡µÕ°ÖëΩ‹ËÅŸÖ»†¥µçÖ…êµÕ°ÖëΩ‹§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏ƒ’Ã∞ÅâΩ‡µÕ°ÖëΩ‹Ä¿∏ƒ’ÃÏÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êÈ°ΩŸï»ÅÌÏÅ—…ÖπÕôΩ…¥ËÅ—…ÖπÕ±Ö—ïd†¥…¡‡§ÏÅâΩ‡µÕ°ÖëΩ‹ËÄ¿Äƒ¡¡‡Ä»—¡‡Å…ùâÑ†Ã‹∞Ä‰‰∞Ä»Ã‘∞Ä¿∏ƒ–§ÏÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ•µÖùîÅÌÏÅÖÕ¡ïç–µ…Ö—•ºËÄƒÿÄºÄ‰ÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ•µÖùîÅ•µúÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅ°ï•ù°–ËÄƒ¿¿îÏÅΩâ©ïç–µô•–ËÅçΩŸï»ÏÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµâΩë‰ÅÌÏÅ¡Öëë•πúËÄƒ…¡‡Äƒ—¡‡Äƒ—¡‡ÏÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ—•—±îÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏Ã‘ÏÅıÙ(πù’•ëîµ¡°Ω—ºµçÖ…êµ±•π¨ÅÌÏÅôΩπ–µÕ•ÈîËÄ¿∏·…ï¥ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅçΩ±Ω»ËÅŸÖ»†¥µâ±’î§ÏÅµÖ…ù•∏µ—Ω¿ËÄ·¡‡ÏÅıÙ(º®ÅDµ…ïùï±µΩ—Ω»Ä†»¿»ÿ¥¿‰¥»‹§Ä¥¥Åù…’¡¡ï…–ÅÖççΩ…ë•Ω∏∞ÅÕî(ÄÄÅ}…ïπëï…}ôÖµ•±Â}ôÖ≈}ÖççΩ…ë•Ω∏†§∏ÅùπîÅ≠±ÖÕÕïπÖŸ∏Ä°ôÖƒµçÖ—ïùΩ…‰®º(ÄÄÅôÖƒµÖççΩ…ë•Ω∏µ•—ï¥ΩôÖƒµç°ïŸ…Ω∏§Å§ÅÕ—ïëï–ÅôΩ»ÉîÅïπë…îÄπôÖƒµ•—ï¥Ä°ëï∏Åô±Ö—î(ÄÄÅŸÖ…•Öπ—ï∏Åâ…’≠ïÃÅôΩ…—ÕÖ—–Å√îÅ¡…Ωë’≠–¥ΩôΩ…Õ•ëîµDµï»§∏Ä®º(πôÖƒµçÖ—ïùΩ…‰ÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄ»…¡‡ÏÅıÙ(πôÖƒµçÖ—ïùΩ…‰Èô•…Õ–µç°•±êÅÌÏÅµÖ…ù•∏µ—Ω¿ËÄ¿ÏÅıÙ(πôÖƒµçÖ—ïùΩ…‰µ±Öâï∞ÅÌÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ¿∏‹……ï¥ÏÅôΩπ–µ›ï•ù°–ËÄ‹¿¿ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿—ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅµÖ…ù•∏ËÄ¿Ä¿Ä—¡‡ÏÅıÙ(πôÖƒµÖççΩ…ë•Ω∏µ•—ï¥ÅÌÏÅâΩ…ëï»µ—Ω¿ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅıÙ(πôÖƒµÖççΩ…ë•Ω∏µ•—ï¥È±ÖÕ–µç°•±êÅÌÏÅâΩ…ëï»µâΩ——Ω¥ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅıÙ(πôÖƒµÖççΩ…ë•Ω∏µ•—ï¥ÅÕ’µµÖ…‰ÅÌÏÅë•Õ¡±Ö‰ËÅô±ï‡ÏÅÖ±•ù∏µ•—ïµÃËÅçïπ—ï»ÏÅ©’Õ—•ô‰µçΩπ—ïπ–ËÅÕ¡Öçîµâï—›ïï∏ÏÅùÖ¿ËÄƒ…¡‡ÏÅç’…ÕΩ»ËÅ¡Ω•π—ï»ÏÅ±•Õ–µÕ—Â±îËÅπΩπîÏÅ¡Öëë•πúËÄƒÕ¡‡Ä¿ÏÅôΩπ–µ›ï•ù°–ËÄÿ¿¿ÏÅôΩπ–µÕ•ÈîËÄ¿∏‰……ï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µ•π¨§ÏÅıÙ(πôÖƒµÖççΩ…ë•Ω∏µ•—ï¥ÅÕ’µµÖ…‰ËËµ›ïâ≠•–µëï—Ö•±ÃµµÖ…≠ï»ÅÌÏÅë•Õ¡±Ö‰ËÅπΩπîÏÅıÙ(πôÖƒµç°ïŸ…Ω∏ÅÌÏÅô±ï‡µÕ°…•π¨ËÄ¿ÏÅ›•ë—†ËÄƒŸ¡‡ÏÅ°ï•ù°–ËÄƒŸ¡‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅ—…ÖπÕ•—•Ω∏ËÅ—…ÖπÕôΩ…¥Ä¿∏ƒ’ÃÏÅıÙ(πôÖƒµÖççΩ…ë•Ω∏µ•—ïµmΩ¡ïπtÄπôÖƒµç°ïŸ…Ω∏ÅÌÏÅ—…ÖπÕôΩ…¥ËÅ…Ω—Ö—î†ƒ‡¡ëïú§ÏÅıÙ(πôÖƒµÖççΩ…ë•Ω∏µ•—ï¥Å¿ÅÌÏÅµÖ…ù•∏ËÄ¿Ä¿Äƒ’¡‡ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅ±•πîµ°ï•ù°–ËÄƒ∏‘‘ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ¡…Ωë’ç–à¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙµÕï…•ï∏Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµ°ï…ºµçΩπ—ïπ–à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘A…Ωë’≠—Õï…•îΩë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘ÌïÕçÖ¡î°ôÖµ•±Â}πÖµî•ÙµÕï…•ï∏Ω†ƒ¯(ÄÄÄÄÄÅÌ•π—…ΩÙ(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµ°ï…ºµµïë•ÑàÅÖ…•Ñµ°•ëëï∏Ùâ—…’îà¯(ÄÄÄÄÄÄÒ¡•ç—’…î¯(ÄÄÄÄÄÄÄÄÒÕΩ’…çîÅµïë•ÑÙà°µ•∏µ›•ë—†ËÄ‡ÿ¡¡‡§àÅ—Â¡îÙâ•µÖùîΩ›ïâ¿àÅÕ…çÕï–ÙàΩÕ—Ö—•åΩ°ï…ºΩÕï…•î¥‘ÿ¿π›ïâ¿Ä‘ÿ¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩÕï…•î¥‡–¿π›ïâ¿Ä‡–¡‹∞ÄΩÕ—Ö—•åΩ°ï…ºΩÕï…•î¥ƒƒ»¿π›ïâ¿Äƒƒ»¡‹àÅÕ•ÈïÃÙà°µ•∏µ›•ë—†ËÄƒ»¿¡¡‡§Ä‘ÿ¡¡‡∞Ä–—Ÿ‹à¯(ÄÄÄÄÄÄÄÄÒ•µúÅÕ…åÙâëÖ—ÑÈ•µÖùîΩù•òÌâÖÕîÿ–±H¡±=±°E	 ’	-1	%Q=‹ÙÙàÅÖ±–ÙààÅ›•ë—†Ùà‘ÿ¿àÅ°ï•ù°–ÙàÃ¿–àÅ±ΩÖë•πúÙâ±ÖÈ‰àÅëïçΩë•πúÙâÖÕÂπåà¯(ÄÄÄÄÄÄΩ¡•ç—’…î¯(ÄÄÄÄΩë•ÿ¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµÕ—Ö–µ¡•±±Ãà˘ÌÕ—Ö—}¡•±±Õ}°—µ±ÙΩë•ÿ¯(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâµΩâ•±îµ¡…Ωë’ç—Ãµô•…Õ–à¯(ÄÄÒë•ÿÅç±ÖÕÃÙâÕ’¡¡Ω…—•πúµçΩπ—ïπ–à¯(ÄÅÌç°Ö•π}°—µ±Ù(ÄÅÌŸÖ…•Öπ—}ô•πëï…}°—µ±Ù(ÄÅÌ•πÕ•ù°—}…Ω›}°—µ±Ù(ÄÅÌÖ•}Õ’µµÖ…Â}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ¡…•Ω…•—‰µ¡…Ωë’ç—Ãà¯(ÄÅÌÖ±±}¡…Ωë’ç—Õ}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒ†»˘MÖµµïπ±•ù∏ÅŸÖ…•Öπ—ïπîΩ†»¯(ÄÄÒë•ÿÅç±ÖÕÃÙâÕ¡ïåµ—Öâ±îµçÖ…êà¯(ÄÄÒë•ÿÅÕ—Â±îÙâΩŸï…ô±Ω‹µ‡ÈÖ’—ºÏà¯(ÄÅÌçΩµ¡Ö…•ÕΩπ}—Öâ±ïÙ(ÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯((ÄÄÒë•ÿÅç±ÖÕÃÙâÕï…•îµâΩ——Ω¥µ…Ω‹à¯(ÄÄÄÅÌôï±±ïÕ}°—µ±Ù(ÄÄÄÅÌù’•ëïÕ}°—µ±Ù(ÄÄΩë•ÿ¯(ÄÅÌôÖµ•±Â}ôÖ≈}°—µ±Ù((ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅA…•ÕïπîÅ°ï»Åï»Å¡…Ωë’≠—¡…•Õï»Å’—ï∏Åô…Ö≠–∞ÅÕΩ…—ï…–Åï——ï»Å±ÖŸïÕ–Å¡…•Ã∏ÅCîÅ°Ÿï»(ÄÄÄÅ¡…Ωë’≠—Õ•ëîÅ≠Ö∏Åë‘ÅÕ≥îÅ√îÉ
≠A…•ÃÅ•π≠±’ëï…–Åô…Ö≠”
ÏÅôΩ»ÉîÅÕîÅ—Ω—Ö±¡…•Õï∏∏ÅY§Å≠Ö∏Åõî(ÄÄÄÅ¡…ΩŸ•Õ©Ω∏Åªï»Åë‘Å°Öπë±ï»ÅŸ•ÑÅ±ïπ≠ïπî∞Åµï∏Åëï–Å√ïŸ•…≠ï»ÅÖ±ë…§Å¡…•Õï∏Åë‘(ÄÄÄÅâï—Ö±ï»∏ÅYÖ…ï»Å’—ï∏Åâï≠…ïô—ï–Å±Öùï»Å≠Ö∏Å•≠≠îÅŸ•ππîÉ
≠±ÖŸïÕ—îÅ¡…•œ
Ï∞ÅΩúÅ°Ÿï…–(ÄÄÄÅ—•±â’êÅŸ•Õï»Åªï»Åëï–ÅÕ•Õ–Åâ±îÅ≠Ωπ—…Ω±±ï…–∏(ÄÄΩ¿¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà(()ëïòÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}•πëï·}¡Öùî°±Öâï±ÃËÅ±•Õ—më•ç—t∞Å¡…Ωë’ç—Õ}âÂ}•êËÅë•ç–∞ÅçÖ—ïùΩ…•ïÃËÅë•ç–∞ÅπΩ‹ËÅëÖ—ï—•µîÅÅ9ΩπîÄÙÅ9Ωπî§Ä¥¯ÅÕ—»Ë(ÄÄÄÄààâ=Ÿï…Õ•≠—ÕÕ•ëîÄ¥¥Åù…’¡¡ï…–Å¡ï»ÅΩ¡—•≠ï…≠©ïëî∞Å±ïπ≠ï»ÅŸ•ëï…îÅ—•∞Å°Ÿï»(ÄÄÄÅïπ≠ï±–Å¡…•ŸÖ—îÅ±Öâï∞µÕ•ëî∏ÅQÖâï±±ôΩ…µÖ–Ä†»¿»ÿ¥¿‡¥Ã¿∞ÅâÂ——ï–Åô…ÑÅï∏(ÄÄÄÅ¡…Ωë’ç–µ—•±îµ…’—ïπï—–§Ä¥¥Åâ…’≠ï»Å√ï¡ï≠—îÅÖ–Å…’—ïπï——ï–Åâ±îÅ—’πù–º(ÄÄÄÅ¡±ÖÕÕ≠…ïŸïπëîÅôΩ»Ä‘‘Å…Öëï»Ä°ΩúÅŸΩ≠Õï»§∞ÅÕ¡ïÕ•ï±–ÅÕ•ëï∏Åë•ÕÕîÅ≠Ω…—ïπî(ÄÄÄÅ1I$ÅŸ•Õï»Åï–Åï≠—îÅâ•±ëîÄ°Ÿ•Õï»Åôï•∞ÅâΩ≠ÃÅ’πëï»Åôï•∞ÅπÖŸ∏Ä¥¥ÅÕî(ÄÄÄÅ…ïπëï…}¡…•ŸÖ—ï}±Öâï±}¡Öùî†§ÅÕ•∏Åïùï∏Å≠Ωµµïπ—Ö»ÅΩ¥ÅÖ≠≠’…Ö–Åëï——î§∞Åœî(ÄÄÄÅâ•±ëîµ¡±ÖÕÕï∏ÅÕ—ºÅ’ÖπÕï—–Å’â…’≠–∏Å∏Å—Öâï±∞Åï»Åµï»ÅÕ≠ÖππâÖ»ÅôΩ»Åëï–(ÄÄÄÅëï——îÅôÖ≠—•Õ¨Åï»ËÅï–ÅΩ¡¡Õ±ÖùÕŸï…¨Ä†â°ŸÑÅ°ï—ï»Å±•πÕï∏Åïùïπ—±•úà§∞Å•≠≠î(ÄÄÄÅï∏Åâ…Ω›ÕîµΩúµ°Öπë±îµÕ•ëîÄ°ëï–Åù´·»ÄΩµï…≠îºÅΩúÄΩ≠Ωπ—Ö≠—±•πÕï»ºÅÖ±±ï…ïëî§∏(ÄÄÄÅ!Ÿï»Å…ÖêÅ°Ö»ÅôΩ…—ÕÖ—–Å	Å±ïπ≠ïπîÅÕΩ¥ÅôÖπ—ïÃÅ§Å≠Ω…–µŸï…Õ©Ωπï∏ËÅ—•∞(ÄÄÄÅ€ï»Åïùï∏Å¡…•ŸÖ—îÅ±Öâï∞µÕ•ëîÄ°òπï≠Ã∏ÄΩ¡…•ŸÖ—îµ±Öâï∞Ω•›ïÖ»µô•–º§Å=Å—•∞(ÄÄÄÅëï–ÅŸ•…≠ï±•ùîÅ¡…Ωë’≠—ï—ÃÅïùï∏ÅÕ•ëîÄ°òπï≠Ã∏ÄΩ≠Ωπ—Ö≠—±•πÕï»Ωâ•Ωµïë•çÃº∏∏∏§∏ààà(ÄÄÄÅπΩ‹ÄÙÅπΩ‹ÅΩ»ÅëÖ—ï—•µîππΩ‹°—•µïÈΩπîπ’—å§((ÄÄÄÅâÂ}ç°Ö•∏ËÅë•ç—mÕ—»∞Å±•Õ—më•ç—utÄÙÅÌÙ(ÄÄÄÅôΩ»Å±Öâï∞Å•∏Å±Öâï±ÃË(ÄÄÄÄÄÄÄÅâÂ}ç°Ö•∏πÕï—ëïôÖ’±–°±Öâï±lâç°Ö•∏ât∞Åmt§πÖ¡¡ïπê°±Öâï∞§((ÄÄÄÅëïòÅ…ïπëï…}…Ω‹°ç°Ö•∏ËÅÕ—»∞Å±Öâï∞ËÅë•ç–§Ä¥¯ÅÕ—»Ë(ÄÄÄÄÄÄÄÅ…ïÖ±}¡…Ωë’ç–ÄÙÅ¡…Ωë’ç—Õ}âÂ}•ëm±Öâï±lâ…ïÖ±}¡…Ωë’ç—}•êâut(ÄÄÄÄÄÄÄÅΩôôï…ÃÄÙÅ…ïçΩπç•±ï}¡…Ωë’ç–°…ïÖ±}¡…Ωë’ç—lâΩôôï…Ãât∞ÅπΩ‹§(ÄÄÄÄÄÄÄÅï±•ù•â±îÄÙÅmºÅôΩ»ÅºÅ•∏ÅΩôôï…ÃÅ•òÅΩlâ•π}Õ—Ωç¨âut(ÄÄÄÄÄÄÄÅ±Ω›ïÕ–ÄÙÅµ•∏°ï±•ù•â±î∞Å≠ï‰ı±ÖµâëÑÅºËÄ°Ωlâ¡…•çï}πΩ¨ât∞ÅΩlâ—Ω—Ö∞ât§∞ÅëïôÖ’±–ı9Ωπî§(ÄÄÄÄÄÄÄÅ…ïÖ±}°…ïòÄÙÅòúΩ≠Ωπ—Ö≠—±•πÕï»ΩÌ…ïÖ±}¡…Ωë’ç—lââ…Öπë}Õ±’úâuÙΩÌ…ïÖ±}¡…Ωë’ç—lâÕ±’úâuÙºú(ÄÄÄÄÄÄÄÅ¡±}°…ïòÄÙÅòúΩ¡…•ŸÖ—îµ±Öâï∞ΩÌïÕçÖ¡î°±Öâï±lâÕ±’úât•Ùºú(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}Õ±’úÄÙÅ…ïÖ±}¡…Ωë’ç–πùï–†âçÖ—ïùΩ…Â}Õ±’úà∞Äàà§(ÄÄÄÄÄÄÄÅçÖ—ïùΩ…Â}±Öâï∞ÄÙÅçÖ—ïùΩ…•ïÃπùï–°çÖ—ïùΩ…Â}Õ±’ú∞ÅÌÙ§πùï–†â±Öâï∞à∞Äàà§(ÄÄÄÄÄÄÄÅ¡…•çï}çï±∞ÄÙÄ†(ÄÄÄÄÄÄÄÄÄÄÄÅòùÌ}ôµ—}≠»°±Ω›ïÕ—lâ¡…•çï}πΩ¨ât•ÙÄÒÕ¡Ö∏ÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§ÌôΩπ–µÕ•ÈîË¿∏·ï¥Ïà˘°ΩÃÅÌïÕçÖ¡î°±Ω›ïÕ—lâ…ï—Ö•±ï»ât•ÙΩÕ¡Ö∏¯ú(ÄÄÄÄÄÄÄÄÄÄÄÅ•òÅ±Ω›ïÕ–Åï±ÕîÄúÒÕ¡Ö∏ÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µµ’—ïê§Ïà˘%πùï∏Å¡…•ÃΩÕ¡Ö∏¯ú(ÄÄÄÄÄÄÄÄ§(ÄÄÄÄÄÄÄÅ…ï—’…∏ÅòàààÒ—»¯(ÄÄÄÄÄÄÒ—ê¯ÒÑÅ°…ïòÙâÌ¡±}°…ïôÙàÅÕ—Â±îÙâôΩπ–µ›ï•ù°–Ëÿ¿¿ÌçΩ±Ω»ÈŸÖ»†¥µ•π¨§Ì—ï·–µëïçΩ…Ö—•Ω∏ÈπΩπîÏà˘ÌïÕçÖ¡î°±Öâï±lâπÖµîât•ÙΩÑ¯Ω—ê¯(ÄÄÄÄÄÄÒ—ê¯ÒÑÅ°…ïòÙâÌïÕçÖ¡î°…ïÖ±}°…ïò•ÙàÅÕ—Â±îÙâçΩ±Ω»ÈŸÖ»†¥µâ±’î§Ì—ï·–µëïçΩ…Ö—•Ω∏ÈπΩπîÏà˘ÌïÕçÖ¡î°…ïÖ±}¡…Ωë’ç—lâπÖµîât•ÙΩÑ¯Ω—ê¯(ÄÄÄÄÄÄÒ—ê˘ÌïÕçÖ¡î°çÖ—ïùΩ…Â}±Öâï∞•ÙΩ—ê¯(ÄÄÄÄÄÄÒ—êÅÕ—Â±îÙâ›°•—îµÕ¡ÖçîÈπΩ›…Ö¿Ïà˘Ì¡…•çï}çï±±ÙΩ—ê¯(ÄÄÄÄΩ—»¯ààà((ÄÄÄÅÕïç—•ΩπÕ}°—µ∞ÄÙÄàà(ÄÄÄÅôΩ»Åç°Ö•∏Å•∏ÅÕΩ…—ïê°âÂ}ç°Ö•∏π≠ïÂÃ†§§Ë(ÄÄÄÄÄÄÄÅç°Ö•π}±Öâï±ÃÄÙÅÕΩ…—ïê°âÂ}ç°Ö•πmç°Ö•πt∞Å≠ï‰ı±ÖµâëÑÅ∞ËÅ±lâπÖµîât§(ÄÄÄÄÄÄÄÅ…Ω›ÃÄÙÄâq∏àπ©Ω•∏°…ïπëï…}…Ω‹°ç°Ö•∏∞Å∞§ÅôΩ»Å∞Å•∏Åç°Ö•π}±Öâï±Ã§(ÄÄÄÄÄÄÄÅÕ’ââ…ÖπêÄÙÅAI%YQ}1	1}MU		I9Lπùï–°ç°Ö•∏∞Åç°Ö•∏§(ÄÄÄÄÄÄÄÅç°Ö•π}Öπç°Ω»ÄÙÅç°Ö•∏π±Ω›ï»†§π…ï¡±Öçî†àÄà∞Äà¥à§(ÄÄÄÄÄÄÄÅÕïç—•ΩπÕ}°—µ∞Ä¨ÙÅòàààÒ†»Å•êÙâÌïÕçÖ¡î°ç°Ö•π}Öπç°Ω»•ÙàÅÕ—Â±îÙâÕç…Ω±∞µµÖ…ù•∏µ—Ω¿Ë»¡¡‡Ïà˘ÌïÕçÖ¡î°ç°Ö•∏•ÙÄÒÑÅ°…ïòÙàΩµï…≠îΩÌïÕçÖ¡î°Õ’ââ…Öπêπ±Ω›ï»†§•ÙºàÅÕ—Â±îÙâôΩπ–µÕ•ÈîË¿∏‹’…ï¥ÌôΩπ–µ›ï•ù°–Ëÿ¿¿ÌçΩ±Ω»ÈŸÖ»†¥µâ±’î§Ì—ï·–µëïçΩ…Ö—•Ω∏ÈπΩπîÏà˘MîÅÌïÕçÖ¡î°Õ’ââ…Öπê•ÙµÕ•ëï∏ÉäHΩÑ¯Ω†»¯(ÄÄÒë•ÿÅÕ—Â±îÙâΩŸï…ô±Ω‹µ‡ÈÖ’—ºÏà¯(ÄÄÒ—Öâ±îÅç±ÖÕÃÙâ¡∞µ—Öâ±îà¯(ÄÄÄÄÒ—°ïÖê¯Ò—»¯Ò—†˘-©ïëïπÃÅπÖŸ∏Ω—†¯Ò—†˘ùïπ—±•úΩ—†¯Ò—†˘-Ö—ïùΩ…§Ω—†¯Ò—†˘…ÑÅ¡…•ÃΩ—†¯Ω—»¯Ω—°ïÖê¯(ÄÄÄÄÒ—âΩë‰¯(ÄÄÄÅÌ…Ω›ÕÙ(ÄÄÄÄΩ—âΩë‰¯(ÄÄΩ—Öâ±î¯(ÄÄΩë•ÿ¯(ààà((ÄÄÄÅ•π—…ºÄÙÄâ±ï…îÅΩ¡—•≠ï…≠©ïëï»ÅÕï±ùï»Å≠Ωπ—Ö≠—±•πÕï»Å’πëï»ÅÕ•—–Åïùï–Åµï…≠ïπÖŸ∏∞ÅÕï±ÿÅΩ¥Å±•πÕï∏Åï»Å•ëïπ—•Õ¨ÅµïêÅï–Å≠©ïπ–Å¡…Ωë’≠–Åô…ÑÅ¡…Ωë’Õïπ—ï∏∏Å!ï»Åô•ππï»Åë‘ÅΩŸï…Õ•≠—ï∏ÉäLÅ°Ÿ•±≠ï–ÅπÖŸ∏Å°ΩÃÅ°Ÿ•±≠ï∏Å≠©ïëîÅ—•±ÕŸÖ…ï»Å°Ÿ•±≠ï–Å¡…Ωë’≠–ÅŸ§ÅÖ±±ï…ïëîÅÕÖµµïπ±•ùπï»Å¡…•Õï»Å√î∏à((ÄÄÄÅÕç°ïµÖ}©ÕΩ∏ÄÙÅòààâÌÏ(ÄÄâçΩπ—ï·–àËÄâ°——¡ÃËºΩÕç°ïµÑπΩ…úà∞(ÄÄâ—Â¡îàËÄâ	…ïÖëç…’µâ1•Õ–à∞(ÄÄâ•—ïµ1•Õ—±ïµïπ–àËÅl(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄƒ∞ÄâπÖµîàËÄâ!©ï¥à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙºâıÙ∞(ÄÄÄÅÌÏâ—Â¡îàËÄâ1•Õ—%—ï¥à∞Äâ¡ΩÕ•—•Ω∏àËÄ»∞ÄâπÖµîàËÄâ=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»à∞Äâ•—ï¥àËÄâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ºâıÙ(ÄÅt)ıÙààà((ÄÄÄÅ…ï—’…∏ÅòàààÖ=QeAÅ°—µ∞¯(Ò°—µ∞Å±ÖπúÙâπàà¯(Ò°ïÖê¯)ÌQ5}!Ù(Òµï—ÑÅç°Ö…Õï–ÙâUQ¥‡à¯(Òµï—ÑÅπÖµîÙâŸ•ï›¡Ω…–àÅçΩπ—ïπ–Ùâ›•ë—†ıëïŸ•çîµ›•ë—†∞Å•π•—•Ö∞µÕçÖ±îÙƒ∏¿à¯(Ò—•—±î˘=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ÉäLÅ!ŸÑÅ°ï—ï»Å±•πÕï∏Åïùïπ—±•ú¸ÅÅ-Ωπ—Ö≠—±•πÕï»ππºΩ—•—±î¯(Òµï—ÑÅπÖµîÙâëïÕç…•¡—•Ω∏àÅçΩπ—ïπ–ÙâÌïÕçÖ¡î°•π—…º•Ùà¯(Ò±•π¨Å…ï∞ÙâçÖπΩπ•çÖ∞àÅ°…ïòÙâÌ	M}UI1ÙΩ¡…•ŸÖ—îµ±Öâï∞ºà¯)Ì}Ωù}µï—Ñ†ù=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»ÉäLÅ!ŸÑÅ°ï—ï»Å±•πÕï∏Åïùïπ—±•ú¸ÅÅ-Ωπ—Ö≠—±•πÕï»ππºú∞Å•π—…º∞Å	M}UI0Ä¨ÄúΩ¡…•ŸÖ—îµ±Öâï∞ºú•Ù)Ì=9Q}1%9-MÙ(ÒÕç…•¡–Å—Â¡îÙâÖ¡¡±•çÖ—•Ω∏Ω±ê≠©ÕΩ∏à˘ÌÕç°ïµÖ}©ÕΩπÙΩÕç…•¡–¯(ÒÕ—Â±î˘ÌM!I}MQe1Ù(π¡∞µ—Öâ±îÅÌÏÅ›•ë—†ËÄƒ¿¿îÏÅµ•∏µ›•ë—†ËÄ‘ÿ¡¡‡ÏÅâΩ…ëï»µçΩ±±Ö¡ÕîËÅçΩ±±Ö¡ÕîÏÅâÖç≠ù…Ω’πêËÅ›°•—îÏÅâΩ…ëï»ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅâΩ…ëï»µ…Öë•’ÃËÄƒ…¡‡ÏÅΩŸï…ô±Ω‹ËÅ°•ëëï∏ÏÅôΩπ–µÕ•ÈîËÄ¿∏‡·…ï¥ÏÅµÖ…ù•∏ËÄƒ…¡‡Ä¿Ä»·¡‡ÏÅıÙ(π¡∞µ—Öâ±îÅ—†∞Äπ¡∞µ—Öâ±îÅ—êÅÌÏÅ—ï·–µÖ±•ù∏ËÅ±ïô–ÏÅ¡Öëë•πúËÄƒ¡¡‡Äƒ—¡‡ÏÅâΩ…ëï»µâΩ——Ω¥ËÄ≈¡‡ÅÕΩ±•êÅŸÖ»†¥µâΩ…ëï»§ÏÅŸï…—•çÖ∞µÖ±•ù∏ËÅµ•ëë±îÏÅ›°•—îµÕ¡ÖçîËÅπΩ›…Ö¿ÏÅıÙ(π¡∞µ—Öâ±îÅ—†ÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅôΩπ–µôÖµ•±‰ËÄù5’±•Õ†ú∞ÅÕÖπÃµÕï…•òÏÅôΩπ–µÕ•ÈîËÄ¿∏‹Ÿ…ï¥ÏÅ—ï·–µ—…ÖπÕôΩ…¥ËÅ’¡¡ï…çÖÕîÏÅ±ï——ï»µÕ¡Öç•πúËÄ¿∏¿Õï¥ÏÅçΩ±Ω»ËÅŸÖ»†¥µµ’—ïê§ÏÅıÙ(π¡∞µ—Öâ±îÅ—»È±ÖÕ–µç°•±êÅ—êÅÌÏÅâΩ…ëï»µâΩ——Ω¥ËÅπΩπîÏÅıÙ(π¡∞µ—Öâ±îÅ—»È°ΩŸï»Å—êÅÌÏÅâÖç≠ù…Ω’πêËÅŸÖ»†¥µµ•Õ–§ÏÅıÙ(ΩÕ—Â±î¯(Ω°ïÖê¯(ÒâΩë‰¯)ÌQ=A	I}!Q51Ù(Òë•ÿÅç±ÖÕÃÙâ›…Ö¿Å›…Ö¿µ›•ëîà¯(ÄÄÒ¿Åç±ÖÕÃÙââ…ïÖëç…’µàà¯ÒÑÅ°…ïòÙàºà˘!©ï¥ΩÑ¯ÉäËÅ=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»Ω¿¯(ÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºà¯(ÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ°ï…ºµçΩ¡‰à¯(ÄÄÄÄÄÄÒë•ÿÅç±ÖÕÃÙâ≠•ç≠ï»à˘’•ëîΩë•ÿ¯(ÄÄÄÄÄÄÒ†ƒ˘=¡—•≠ï…≠©ïëïπïÃÅïùπîÅµï…≠ï»Ω†ƒ¯(ÄÄÄÄÄÄÒ¿˘ÌïÕçÖ¡î°•π—…º•ÙΩ¿¯(ÄÄÄÄΩë•ÿ¯(ÄÄΩë•ÿ¯(ÄÅÌÕïç—•ΩπÕ}°—µ±Ù(ÄÄÒ¿Åç±ÖÕÃÙâë•Õç±ΩÕ’…îà¯(ÄÄÄÅ-Ωâ±•πùïπîÅΩŸï»Åï»ÅÕÖ—–ÅÕÖµµï∏ÅâÖÕï…–Å√îÅ—•±ù©ïπùï±•úÅ•πôΩ…µÖÕ©Ω∏ÅΩ¥(ÄÄÄÅ¡…Ωë’Õïπ–ÅΩúÅ¡…Ωë’≠—Õ¡ïÕ•ô•≠ÖÕ©Ωπï»∏Å-Ωπ—Ö≠—±•πÕï»ππºÅ°Ö»Å•πùï∏ÅÖŸ—Ö±î(ÄÄÄÅµïêÅΩ¡—•≠ï…≠©ïëïπîÅπïŸπ–Å°ï»ÅΩúÅ≠Ö∏Å•≠≠îÅùÖ…Öπ—ï…îÅÖ–Å°Ÿï»Å≠Ωâ±•πú(ÄÄÄÅÕ—ïµµï»Å§ÅÖ±±îÅ—•±ôï±±ï»∏Å	ï≠…ïô–ÅÖ±±—•êÅµïêÅë•∏ÅΩ¡—•≠ï»Åõ·»Åë‘ÅâÂ——ï»(ÄÄÄÅµï±±Ω¥Åë•ÕÕîÅπÖŸπïπî∏(ÄÄΩ¿¯(Ωë•ÿ¯)Ì…ïπëï…}ôΩΩ—ï»†•Ù)Ì=9M9Q}	99I}!Q51Ù)Ì=9M9Q}MI%AQÙ(ΩâΩë‰¯(Ω°—µ∞¯ààà