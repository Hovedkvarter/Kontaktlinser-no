"""
render_templates.py

Rendrer produkt- og kategorisider som ferdig, statisk HTML - tilbudslisten,
prisene og "sist oppdatert"-tidspunktene ligger direkte i markupen som
returneres, IKKE bygget av JavaScript etter innlasting.

Grunnen: mange AI-crawlere (og noen eldre indekserere) kjører ikke
JavaScript. Er ikke prisen der i rå-HTML, finnes den ikke for dem. JS her
brukes kun til forbedringer ovenpå innhold som allerede er synlig uten den
(filter/sortering på kategorisiden) - se <noscript>-fallback i category-malen.

Bruker samme CSS-tokens som prototypene: ink/mist/blue/mint, Space Grotesk /
Inter / IBM Plex Mono. Endres designsystemet, endres SHARED_STYLE - ett sted.
"""

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


def _json_str(s: str) -> str:
    """JSON-escaper for strengverdier som limes inn i håndbygde JSON-LD
    <script>-blokker -- IKKE html.escape() (som escape()-navnet ellers
    brukes til overalt på siden for vanlig HTML-markup). html.escape()
    gjør "&" om til bokstavelig "&amp;"-TEKST, som blir stående som feil
    tegn inni selve JSON-en (gyldig JSON-syntaks, men feil VERDI -- en
    lenke med "&amp;" i stedet for "&" er en ødelagt URL). Oppdaget
    2026-09-05: rammet fra før kun det fåtallet affiliate-URL-er med "&" i
    seg, men ble et utbredt, reelt problem samme dag UTM-parametre
    (utm_source&utm_medium&utm_campaign) ble lagt til på nesten alle
    ikke-affiliate tilbudslenker. Returnerer STRENGEN UTEN omsluttende
    anførselstegn -- malene rundt legger selv til `"..."`."""
    return json.dumps(s)[1:-1]


BASE_URL = "https://kontaktlinser.no"


def _abs_url(url: str | None) -> str | None:
    """Rot-relativ sti (/static/...) -> absolutt https-URL. Allerede absolutte
    URL-er returneres uendret. Brukes for ALLE bilde-URL-er i metadata og
    strukturert data (og:image, Product.image, Article.image): Web Standard
    krever absolutte bilde-URL-er der, mens selve <img src> trygt kan være
    rot-relativ."""
    if url and url.startswith("/") and not url.startswith("//"):
        return BASE_URL + url
    return url


# --- Bildedimensjoner (width/height på <img>, hindrer layoutskift) -----------
# Egne filer under /static/ leses direkte fra disk (ren Python, ingen PIL --
# CI installerer bare requests/beautifulsoup4). Bilder vi viser fra en
# forhandlers feed (ikke våre filer) slås opp i image_dimensions.json, som
# lages av probe_image_dimensions.py og committes; verken byggingen eller
# denne funksjonen gjør noen gang nettverkskall. Ukjent dimensjon -> ingen
# width/height-attributter (aldri en gjetning).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_IMAGE_DIMS_FILE = _REPO_ROOT / "image_dimensions.json"
_dims_cache: dict[str, tuple[int, int] | None] = {}
_upstream_dims: dict[str, list[int]] | None = None


def _read_image_size(path: Path) -> tuple[int, int] | None:
    """Bredde/høyde fra JPEG-, PNG- eller WebP-header. None hvis ukjent format."""
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
    description> på siden, aldri egen tekst, slik at de to aldri kan komme
    ut av synk med hverandre. Faller tilbake til logoen når siden ikke har
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
@font-face { font-family: 'Inter'; font-style: normal; font-weight: 400; font-display: swap; src: url('/static/fonts/inter-400.woff2') format('woff2'); unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD; }
@font-face { font-family: 'Inter'; font-style: normal; font-weight: 600; font-display: swap; src: url('/static/fonts/inter-600.woff2') format('woff2'); unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD; }
@font-face { font-family: 'Space Grotesk'; font-style: normal; font-weight: 600; font-display: swap; src: url('/static/fonts/space-grotesk-600.woff2') format('woff2'); unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD; }
@font-face { font-family: 'Space Grotesk'; font-style: normal; font-weight: 700; font-display: swap; src: url('/static/fonts/space-grotesk-700.woff2') format('woff2'); unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD; }
@font-face { font-family: 'IBM Plex Mono'; font-style: normal; font-weight: 600; font-display: swap; src: url('/static/fonts/ibm-plex-mono-600.woff2') format('woff2'); unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD; }
@font-face { font-family: 'IBM Plex Mono'; font-style: normal; font-weight: 700; font-display: swap; src: url('/static/fonts/ibm-plex-mono-700.woff2') format('woff2'); unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD; }
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
body { margin: 0; background: var(--mist); color: var(--ink); font-family: 'Inter', sans-serif; line-height: 1.5; }
a { color: inherit; }
.wrap { max-width: 760px; margin: 0 auto; padding: 0 20px 64px; }
/* Tekstsider (guider, om oss osv.) holder seg smale for lesbarhet selv på
   store skjermer -- kun grid-/liste-/pristabellsider trenger mer bredde.
   wrap-wide: forside/kategori/merke-oversikter. wrap-product: produkt-
   /pristabellsider. Se .brand-grid for tilhørende kolonneøkning ved
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
   som standard under 700px og vises kun når brukeren faktisk trykker meny-
   /søk-ikonet (se _topbar_html() sin docstring-kommentar for hvorfor dette
   er trygt for LENS_SEARCH_JS). .topbar-mobile-actions dyttes til slutt i
   raden med margin-left:auto (samme rad som logoen), slik at ikonene alltid
   havner øverst til høyre uansett om .topbar-nav er åpen eller lukket. */
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
  /* Hver variant er bredden dens egne kolonner faktisk trenger -- IKKE én
     felles bredde for alle tre, det tvang de to smalere menyene (Merker,
     Guider) unødvendig brede og økte risikoen for at de skjøt utenfor
     viewport ved 1024px (nedre støttede breddegrense), siden posisjonen
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
.mega-panel-heading { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.1rem; line-height: 1.3; color: var(--ink); margin: 4px 0 0; }
.mega-panel-text { font-size: 0.85rem; color: var(--muted); line-height: 1.5; margin: 6px 0 0; }
/* "Alle merker A-Å" (2026-09-29) -- CSS-multikolonne (samme teknikk som
   .footer-brand-list) i stedet for et grid, siden listen har et variabelt
   antall lenker (25+ i dag, vokser når nye merker/private label-serier
   legges til) og multikolonne fyller kolonnene i lesevennlig topp-til-bunn-
   rekkefølge uten at vi må telle rader manuelt. break-inside:avoid hindrer
   at én lenke visuelt kuttes over kolonnegrensen. */
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
   en knapp langt til høyre i navigasjonen (f.eks. "Guider") skyter en
   380-720px bred meny da langt utenfor et smalt mobilvindu. .topbar er
   display:flex UTEN justify-content:space-between, så innholdet
   (logo+nav) henger fast venstrestilt inni boksen -- og siden .topbar selv
   er en full-bredde blokk (display:flex oppfører seg som display:block for
   selve boksen) helt opp til den treffer sitt eget max-width-tak (760px
   under 1024px, 1200px fra og med 1024px, se .topbar-regelen over), flytter
   IKKE nav-knappene seg til høyre når viewporten vokser -- de blir
   liggende på nøyaktig samme pikselposisjon fra venstre kant helt til
   .topbar treffer 1200px-taket sitt og margin:0 auto begynner å sentrere
   boksen. Målt i praksis skjer det først et sted mellom ca. 1179px og
   1220px viewport-bredde (avhenger av om scrollbaren tar layoutplass eller
   ikke, dvs. Windows vs. Mac-overlay-scrollbar) -- IKKE ved 1024px slik man
   skulle tro av .topbar sitt eget brytpunkt. En fastbredde-meny (540-720px,
   satt i @media (min-width:700px) over) kan derfor stikke rett utenfor
   viewporten helt opp til den sonen, og gir horisontal scroll på body selv
   når menyen er lukket (position:absolute + visibility:hidden opptar
   fortsatt layoutplass). Låser i stedet menyen til viewporten med
   position:fixed og faste sidemarger helt opp til og med 1279px -- godt
   over den målte faresonen, som ekstra margin mot at font-rendering eller
   fremtidige menytekster flytter kryssingspunktet noe -- og JS-en i
   TOPBAR_HTML sitt <script> (closeAll()/trigger-click) setter inline top=
   like under selve topbaren ved åpning -- position:fixed sin top er alltid
   viewport-relativ, så getBoundingClientRect().bottom fungerer uendret
   uansett scroll-posisjon. top:70px under er kun et statisk fallback-tall
   for det (usannsynlige) tilfellet JS ikke kjører. Klarer nav-item bevisst
   IKKE position:static her -- feil forankringskontekst ville kun flyttet
   problemet et hakk (fortsatt konteksten til den enkelte knappen),
   position:fixed løser det uansett hvilken knapp som er trigger. Fra og
   med 1280px er all praktisk testing (opp til 1920px) uten overflow, siden
   .topbar da for lengst har truffet 1200px-taket sitt og sentrerer
   innholdet med god margin til høyre. */
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
.hero-copy h1 { font-family: 'Space Grotesk', sans-serif; font-size: 1.9rem; line-height: 1.15; margin: 4px 0 8px; }
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
.price-value { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.05rem; }
.price-label { font-size: 0.68rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.03em; }
.offer-price-col { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
.offer-shipping { display: flex; align-items: center; gap: 5px; font-size: 0.78rem; color: var(--muted); white-space: nowrap; }
.offer-shipping svg { width: 15px; height: 15px; color: var(--mint); flex-shrink: 0; }
.price-pill { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 1.15rem; color: white; background: var(--blue); padding: 10px 22px; border-radius: 999px; text-decoration: none; white-space: nowrap; }
.price-pill:hover { opacity: 0.88; }
.offer-card.is-lowest .price-pill { background: var(--mint); }
/* .offer-card hadde ingen mobil-spesifikk layout i det hele tatt -- på
   smale skjermer presset ikke-brytende fraktekst (.offer-shipping) i
   .offer-price-col butikk-logoen sammen, og et merke som pleide å stå der
   (nå fjernet) brøt internt til 2 linjer og dekket frakttéksten (Kai,
   2026-09-27, skjermbilde av live-siden). Fikset ved å stable
   logo-raden og pris/frakt-raden på mobil, og la selve fraktteksten få
   bryte til 1-2 linjer inne i sin egen rad i stedet for å presses av en
   fastbredde prispille ved siden av. Kun mobil -- desktop er uendret. */
@media (max-width: 699px) {
  .offer-card { flex-wrap: wrap; }
  .offer-main { flex-basis: 100%; }
  .offer-price-col { flex-basis: 100%; justify-content: space-between; align-items: center; }
  .offer-shipping { white-space: normal; flex: 1; min-width: 0; align-items: flex-start; }
}
.product-thumb { width: 52px; height: 52px; border-radius: 50%; background: var(--blue-tint); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.9rem; color: var(--blue); flex-shrink: 0; overflow: hidden; }
.product-thumb img { width: 100%; height: 100%; object-fit: cover; }
.chip { font-size: 0.82rem; font-weight: 600; padding: 7px 14px; border-radius: 20px; border: 1px solid var(--border); background: white; cursor: pointer; color: var(--ink); }
.chip.active { background: var(--blue); border-color: var(--blue); color: white; }
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 20px 0 24px; }
.list-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
.list-header h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0; }
.related, .guides { margin-top: 32px; }
.related h2, .guides h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1rem; margin: 0 0 10px; }
.related ul, .guides ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.related a, .guides a { display: block; font-size: 0.88rem; text-decoration: none; padding: 10px 14px; background: white; border: 1px solid var(--border); border-radius: 10px; }
.related a:hover, .guides a:hover { border-color: var(--blue); }
.disclosure { font-size: 0.78rem; color: var(--muted); line-height: 1.6; border-top: 1px solid var(--border); padding-top: 18px; margin-top: 22px; }
@media (min-width: 560px) { .hero-copy h1 { font-size: 2.2rem; } }
.site-footer { margin-top: 48px; background: var(--ink); color: white; }
.footer-inner { max-width: 760px; margin: 0 auto; padding: 40px 20px 8px; display: flex; flex-wrap: wrap; gap: 32px 24px; }
.footer-col { flex: 1 1 140px; min-width: 140px; }
.footer-col h3 { font-family: 'Space Grotesk', sans-serif; font-size: 0.76rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--blue); margin: 0 0 12px; }
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
.consent-modal h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.15rem; margin: 0 0 14px; }
.consent-text { font-size: 0.88rem; line-height: 1.6; color: var(--ink); margin: 0 0 20px; }
.consent-text a { color: var(--blue); }
.consent-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.consent-btn { font-family: 'Inter', sans-serif; font-size: 0.84rem; font-weight: 600; padding: 10px 18px; border-radius: 20px; cursor: pointer; border: 1px solid transparent; }
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
.product-tile { display: flex; flex-direction: column; background: white; border: 1px solid var(--border); border-radius: 16px; overflow: hidden; box-shadow: 0 6px 18px rgba(11, 37, 69, 0.06); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.product-tile:hover { transform: translateY(-3px); border-color: #B9C9DD; box-shadow: 0 10px 28px rgba(11, 37, 69, 0.11); }
.product-tile-image-link { display: block; text-decoration: none; }
.product-tile-image { height: 190px; margin: 14px 14px 0; border-radius: 12px; background: var(--mist); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.product-tile-image.has-photo { background: var(--mist); }
.product-tile-image img { display: block; width: 86%; height: auto; max-height: 150px; object-fit: contain; mix-blend-mode: multiply; }
.product-tile-fallback { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.8rem; color: var(--blue); }
.product-tile-body { padding: 16px 18px 0; flex-grow: 1; display: flex; flex-direction: column; }
.product-tile-category { display: inline-block; align-self: flex-start; margin-bottom: 10px; padding: 5px 8px; border-radius: 999px; background: var(--blue-tint); color: var(--blue); font-size: 0.75rem; line-height: 1; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
.product-tile-name-link { text-decoration: none; color: var(--ink); }
.product-tile-name-link .product-name { font-size: 1.05rem; line-height: 1.35; font-weight: 700; min-height: 2.7em; }
.product-tile-manufacturer { display: block; margin-top: 6px; font-size: 0.85rem; color: var(--muted); text-decoration: none; }
.product-tile-manufacturer:hover { text-decoration: underline; }
.product-tile-specs-row { display: flex; gap: 14px; margin-top: 12px; flex-wrap: wrap; }
.product-tile-spec { display: flex; align-items: center; gap: 5px; font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; color: var(--muted); }
.product-tile-spec svg { width: 14px; height: 14px; color: var(--blue); flex-shrink: 0; }
.product-tile-divider { height: 1px; margin: 16px 0 14px; background: var(--border); }
.product-tile-price-link { display: block; text-decoration: none; color: var(--ink); margin-top: auto; }
.product-tile-price-label { font-size: 0.8rem; color: #5B6B80; margin-bottom: 3px; }
.product-tile-price { font-family: 'Space Grotesk', sans-serif; display: flex; align-items: baseline; gap: 4px; color: var(--ink); }
.product-tile-price-number { font-size: 1.9rem; line-height: 1; font-weight: 700; letter-spacing: -0.02em; }
.product-tile-price-currency { font-size: 0.9rem; font-weight: 700; }
.product-tile-store-line { margin-top: 8px; font-size: 0.85rem; color: var(--muted); }
.product-tile-store-name { color: var(--ink); font-weight: 700; }
.product-tile-store-count { color: var(--blue); font-weight: 700; }
.product-tile-cta { display: block; margin: 16px 18px 18px; padding: 12px 16px; background: var(--blue); color: white; text-decoration: none; text-align: center; font-size: 0.9rem; font-weight: 700; border-radius: 9px; transition: background 0.15s; }
.product-tile:hover .product-tile-cta { background: var(--blue-dark); }
.faq-section { margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }
.faq-section h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }
.faq-item { margin-bottom: 18px; }
.faq-item h3 { font-size: 0.94rem; margin: 0 0 6px; }
.faq-item p { font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin: 0; }
.methodology { margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }
.methodology h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }
.methodology dl { margin: 0; }
.methodology-row { display: flex; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.methodology-row:last-child { border-bottom: none; }
.methodology-row dt { flex: 0 0 110px; font-weight: 600; font-size: 0.88rem; }
.methodology-row dd { margin: 0; font-size: 0.88rem; color: var(--muted); line-height: 1.6; }
/* Flyttet hit fra render_product_page sin egen <style> 2026-09-27 -- brukes nå
   av BÅDE produktsiden og serie-siden sitt nye prisinnsikt-panel (se
   render_family_price_insight()), én kilde i stedet for to kopier. */
.price-history { margin-top: 28px; }
.price-history h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 6px; }
.price-history-summary { font-size: 0.85rem; color: var(--muted); margin: 0 0 12px; }
.price-history-chart { width: 100%; height: auto; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 4px 0; }
/* fill settes INLINE per <path> (se _render_price_history_chart), ikke her --
   en side kan nå ha FLERE grafer samtidig (serie-siden sitt prisinnsikt-panel,
   én per pakningsstørrelse), og en delt CSS-regel med en fast #id ville pekt
   alle grafene til samme (første) gradient i dokumentet -- funnet 2026-09-27
   da 90-pakning-fanen viste linjen uten fylt areal under. */
.price-history-area { stroke: none; }
.price-history-line { fill: none; stroke: var(--orange-dark); stroke-width: 2.25; stroke-linejoin: round; stroke-linecap: round; }
.price-history-dot { fill: white; stroke: var(--orange-dark); stroke-width: 1.5; }
.price-history-dot-last { fill: var(--orange-dark); stroke: white; stroke-width: 1.5; }
.price-history-gridline { stroke: var(--border); stroke-width: 1; stroke-dasharray: 3 3; }
.price-history-axis-label { font-family: 'Inter', sans-serif; font-size: 9.5px; fill: var(--muted); }
.price-history-current-label { font-family: 'Inter', sans-serif; font-weight: 700; font-size: 11px; fill: var(--orange-dark); }
/* Price Intelligence (Product Gold Standard v1, 2026-09-27, flyttet hit
   2026-09-28 for gjenbruk på ALLE produkttyper -- Kai: "gjelder alle
   produkter på domenet kontaktlinser.no ... alle kontaktlinser, egne
   merkenavn kontaktlinser, og alle Tilbehør produkter", inkl.
   linsevæske/øyedråper som deler samme rendringsfunksjon som Tilbehør).
   Var opprinnelig i render_product_page() sin egen lokale <style>-blokk
   -- flyttet til SHARED_STYLE (global) slik at render_solution_
   product_page()/render_private_label_page() også får den, uten
   duplisering. Mobil (regel 27): kompakt, stablet. Desktop (regel 28,
   >=860px): 4 toppmetrikker på én rad, mer luft -- men fortsatt
   restrained, "skal fortsatt føles som Kontaktlinser.no", ikke et tett
   analytics-dashboard. */
.price-intel { margin-top: 28px; background: white; border: 1px solid var(--border); border-radius: 16px; padding: 18px; }
.price-intel-head { margin-bottom: 14px; }
.price-intel-head-text h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0; }
.price-intel-head-text p { font-size: 0.84rem; color: var(--muted); margin: 3px 0 0; line-height: 1.5; }
.price-intel-coverage { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 0.76rem; color: var(--muted); background: white; border: 1px solid var(--border); border-radius: 10px; padding: 7px 11px; }
.price-intel-coverage svg { width: 15px; height: 15px; color: var(--blue); flex-shrink: 0; }
.price-intel-coverage strong { color: var(--ink); }
/* Price Intelligence v2 -- "premium data publication"-redesign
   (2026-09-29, Kai, godkjent mockup-bilde 58.webp er visuell fasit).
   Filosofi: mindre dashboard-kort/grå-blå flater, mer typografi/luft/
   tynne skillelinjer -- tallene ER designet, ikke pakket inn i bokser.
   All underliggende logikk/beregning er UENDRET fra logikk-/semantikk-
   runden tidligere samme dag -- dette er ren presentasjon. */
/* Egen "container" slik at topplaget (metrikkrad + statuspille) kan tilpasse
   seg MODULENS faktiske bredde, ikke viewporten -- modulen er smalere enn
   viewporten (siden rundt + padding), så en @media-terskel ville truffet
   feil. Uten container-query-støtte gjelder bare mobil-stylingen (stablet),
   som er trygg. */
.price-intel { container-type: inline-size; container-name: pintel; }
.price-intel-eyebrow { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--blue); margin: 0 0 4px; }
.price-intel-coverage-days { display: block; font-size: 0.7rem; color: var(--muted); margin-top: 2px; }
/* Primærraden: "Pris nå" (dominerende) + tre skilte historikk-metrikker
   + en atskilt statuspille. Kun én periodes .price-intel-primary er
   noensinne synlig (.active) -- server-rendret, fungerer uten JS. */
.price-intel-primary { display: none; margin-bottom: 16px; }
.price-intel-primary.active { display: block; }
.price-intel-metrics-row { display: flex; flex-wrap: wrap; gap: 14px 0; }
.price-intel-metric-col { flex: 1 1 46%; box-sizing: border-box; padding-right: 10px; }
.price-intel-metric-current { flex: 1 1 100%; margin-bottom: 2px; }
.price-intel-value { display: block; font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.15rem; color: var(--ink); line-height: 1.1; }
.price-intel-value-lg { display: block; font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 2.1rem; color: var(--ink); line-height: 1.05; }
.price-intel-metric-label { display: block; font-size: 0.72rem; color: var(--muted); margin-top: 4px; line-height: 1.35; }
.price-intel-metric-info { display: inline-block; opacity: 0.7; margin-left: 2px; }
.price-intel-metric-desc { display: block; font-size: 0.66rem; color: var(--muted); opacity: 0.85; margin-top: 5px; line-height: 1.4; max-width: 190px; }
.price-intel-metric-sublabel { display: block; font-size: 0.68rem; color: var(--muted); margin-top: 1px; }
.price-intel-current-dot { display: inline-flex; align-items: center; gap: 5px; font-size: 0.74rem; font-weight: 600; color: var(--mint); margin-top: 6px; }
.price-intel-current-dot i { width: 7px; height: 7px; border-radius: 50%; background: var(--mint); display: inline-block; font-style: normal; }
/* Status: fortsatt en diskret tinted "konklusjon"-pille (regel 5: "may
   remain a subtle tinted module because it represents a conclusion
   rather than a raw metric"), men nå atskilt fra rådataraden, ikke en
   grid-rute blant metrikkene. */
.price-intel-status-pill { display: flex; align-items: center; gap: 9px; background: var(--mint-tint); border-radius: 12px; padding: 11px 14px; margin-top: 14px; }
.price-intel-status-pill .price-intel-status-icon { flex-shrink: 0; width: 28px; height: 28px; border-radius: 50%; background: white; display: flex; align-items: center; justify-content: center; }
.price-intel-status-pill .price-intel-status-icon svg { width: 15px; height: 15px; color: var(--mint); }
.price-intel-status-pill span { font-size: 0.76rem; color: var(--muted); line-height: 1.4; }
.price-intel-status-pill span strong { display: block; font-size: 0.86rem; color: var(--ink); margin-bottom: 1px; }
.price-intel-status-pill.price-intel-status-up, .price-intel-status-pill.price-intel-status-high { background: #FDECEC; }
.price-intel-status-pill.price-intel-status-up .price-intel-status-icon svg, .price-intel-status-pill.price-intel-status-high .price-intel-status-icon svg { color: #D64545; }
/* Periodevelger -- uendret fra forrige runde: kompakte piller, aktiv =
   mørk navy. */
.price-intel-period-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.price-intel-period-tab { font-size: 0.76rem; font-weight: 600; font-family: inherit; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border); background: white; color: var(--muted); cursor: pointer; }
.price-intel-period-tab.active { background: var(--ink); border-color: var(--ink); color: white; }
.price-intel-period-tab:disabled { opacity: 0.35; cursor: not-allowed; }
.price-intel-chart-panel { display: none; }
.price-intel-chart-panel.active { display: block; }
/* Grafens "hylle" -- smalnes inn og sentreres på stor desktop (regel
   8/9: "the chart should NOT span the entire Price Intelligence width...
   narrower but still important", 220-240px høyde beholdt uendret). */
.price-intel-chart-shell { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px 8px; }
.price-intel-chart-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px 12px; margin-bottom: 6px; font-size: 0.72rem; color: var(--muted); flex-wrap: wrap; }
.price-intel-chart-toolbar-badge { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); border-radius: 999px; padding: 4px 10px; background: white; }
.price-intel-chart-toolbar-badge svg { width: 13px; height: 13px; color: var(--muted); flex-shrink: 0; }
.price-intel-chart .price-history-chart { padding: 2px 0; }
.price-intel-hit { fill: transparent; stroke: none; cursor: pointer; }
/* Mellomliggende dato-tikker (ikke første/siste) skjules under 640px --
   samme kompakte to-etiketters mobilvisning som før, mens desktop nå
   viser alle (v2-redesign runde 2, rapport #3). */
@media (max-width: 639px) {
  .price-intel-chart .price-history-axis-label-x:not(.price-history-axis-label-edge) { display: none; }
}
/* Intelligens-raden -- fortsatt tynt-kantede hvite kort, men nå kappet i
   bredde og SENTRERT som en gruppe (v2-redesign runde 2, rapport #4/#6:
   "do not simply stretch the remaining two cards to fill the entire
   width... Keep them at approximately the same intended card width").
   flex i stedet for grid auto-fit -- auto-fit STREKKER hvert spor til å
   dele bredden likt uansett antall kort, nøyaktig det som ga de
   "gigantiske 50/50-kortene" Kai pekte på; flex+justify-content:center
   lar hvert kort beholde sin egen, tiltenkte bredde og heller la
   overskuddsplassen bli synlig luft på sidene av raden. */
.price-intel-cards { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-top: 14px; }
.price-intel-card { background: white; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; flex: 1 1 260px; }
.price-intel-card h3 { display: flex; align-items: center; gap: 7px; font-family: 'Space Grotesk', sans-serif; font-size: 0.88rem; margin: 0; color: var(--ink); }
.price-intel-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.price-intel-card-head-note { font-size: 0.7rem; color: var(--muted); white-space: nowrap; }
.price-intel-card h3 svg { width: 16px; height: 16px; flex-shrink: 0; }
.price-intel-card-h-spread svg, .price-intel-card-h-qty svg { color: var(--blue); }
.price-intel-card-h-winner svg { color: var(--amber); }
.price-intel-card-row { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; font-size: 0.84rem; color: var(--ink); }
.price-intel-card-row span { color: var(--muted); }
.price-intel-card-row strong { font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
/* "31 %"-utropet -- egen, fremtredende callout (regel 12: "make the
   proprietary spread metric prominent"), erstatter den tidligere
   ren-tekst-raden med samme tall. */
.price-intel-spread-callout { margin-top: 9px; padding: 11px 12px; background: var(--mint-tint); border-radius: 10px; }
.price-intel-spread-callout strong { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 1.3rem; color: var(--mint); line-height: 1.1; }
.price-intel-spread-callout span { display: block; font-size: 0.74rem; color: var(--muted); margin-top: 2px; }
.price-intel-card-note { display: flex; align-items: flex-start; gap: 5px; font-size: 0.72rem; color: var(--muted); margin: 10px 0 0; line-height: 1.45; }
.price-intel-zero-note { margin: 9px 0 0; font-size: 0.7rem; color: var(--muted); line-height: 1.4; }
.price-intel-qty-note { display: flex; align-items: flex-start; gap: 5px; font-size: 0.74rem; color: var(--ink); margin: 10px 0 0; line-height: 1.5; background: var(--amber-tint); border-radius: 8px; padding: 8px 10px; }
.price-intel-winners-list { display: flex; flex-direction: column; gap: 7px; }
.price-intel-winner-row { display: grid; grid-template-columns: 80px 1fr auto; align-items: center; gap: 8px; font-size: 0.78rem; }
.price-intel-winner-store { font-weight: 600; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.price-intel-winner-bar { display: block; height: 6px; background: var(--mist); border-radius: 999px; overflow: hidden; }
.price-intel-winner-bar span { display: block; height: 100%; background: var(--orange-dark); border-radius: 999px; }
.price-intel-winner-days { color: var(--muted); white-space: nowrap; font-size: 0.74rem; }
/* 0-dagers-butikker: beholdt synlig (Kai bekreftet dette eksplisitt
   tidligere samme uke -- "viser at de faktisk er sammenlignet"), men nå
   visuelt dempet (regel 13: "Do not let zero-value merchants create
   visual clutter"). */
.price-intel-winner-row-zero { opacity: 0.5; }
/* "Kjøper du flere esker?" -- ren tabell, IKKE et eget kortsett per rad. */
.price-intel-qty-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.price-intel-qty-table th { text-align: left; font-weight: 600; color: var(--muted); font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.02em; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.price-intel-qty-table td { padding: 5px 4px 5px 0; border-bottom: 1px solid var(--border); color: var(--ink); }
.price-intel-qty-table tr:last-child td { border-bottom: none; }
.price-intel-qty-table td:first-child { font-weight: 600; }
.price-intel-qty-table td:nth-child(2) { font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
/* "Kort fortalt" -- diskre konklusjon, ikke en stor blå dashboard-boks
   (regel 17: "Do not make it look like an AI response"). */
.price-intel-conclusion { display: none; margin-top: 16px; border-radius: 12px; overflow: hidden; background: var(--blue-tint); }
.price-intel-conclusion.active { display: block; }
.price-intel-summary { display: flex; gap: 10px; align-items: flex-start; padding: 14px 16px; font-size: 0.84rem; line-height: 1.55; color: var(--ink); }
.price-intel-summary strong { display: block; margin-bottom: 2px; color: var(--blue); }
.price-intel-summary-icon { flex-shrink: 0; width: 26px; height: 26px; border-radius: 50%; background: white; display: flex; align-items: center; justify-content: center; font-size: 0.9rem; }
/* Egen-data-stripen (regel 16) -- små, redaksjonelle statistikker med
   tynne skillelinjer, IKKE flere kort. Adaptiv: bygges kun av elementer
   som faktisk har data (se render_price_intelligence()). */
.price-intel-stat-strip { display: flex; flex-wrap: wrap; gap: 12px 0; padding: 14px 16px; background: white; border-top: 1px solid var(--border); }
.price-intel-stat { flex: 1 1 46%; display: flex; align-items: flex-start; gap: 8px; box-sizing: border-box; padding-right: 10px; }
.price-intel-stat svg { width: 15px; height: 15px; color: var(--muted); flex-shrink: 0; margin-top: 2px; }
.price-intel-stat strong { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.92rem; color: var(--ink); }
.price-intel-stat span { display: block; font-size: 0.68rem; color: var(--muted); line-height: 1.3; margin-top: 1px; }
/* Footer -- metodikklenke + en ÆRLIG oppdateringsdato. Bevisst INGEN
   klokkeslett ("kl. HH:MM") slik mockupen viste -- samme lærdom som
   Fase 16 tidligere samme dag (se _price_intel_chart_domain sin
   docstring-nabo lenger opp): en tid-stemplet påstand på en STATISK
   side blir feil i det øyeblikket noen leser siden senere enn
   byggetidspunktet. Bruker i stedet den samme "sist bekreftet
   {dato}"-konvensjonen som resten av siden allerede følger konsekvent. */
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
     siden for øvrig -- gir modulen sin egen, synlig sentrerte
     "publisert markedsrapport"-identitet i stedet for å flyte sammen
     med resten av den brede produktsiden.*/
  .price-intel { padding: 26px 30px; }
  .price-intel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
  .price-intel-head-text p { max-width: 480px; }
  .price-intel-coverage { margin-top: 0; flex-shrink: 0; }
  /* IKKE justify-content:space-between -- det var nøyaktig det som ga
     det synlige, "malplasserte" tomrommet mellom siste metrikk-kolonne
     og statuspillen Kai pekte på (runde 2, rapport #3: "Stabil pris har
     blitt en stor grønn boks helt ute til høyre"). Rådataraden og
     pillen skal sitte SAMMEN med et fast, moderat mellomrom, ikke
     spres ut over hele bredden av en flex-rad. */
  /* Robust topplag: flex-wrap (ingen absolute posisjonering/negative
     marger) -- statuspillen ligger til høyre KUN når den faktisk får
     plass ved siden av metrikkraden, ellers wrapper den ned på egen rad,
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
  /* Smal modul (smal desktop/tablet): metrikkene går i et 3-kolonne-rutenett
     under "Pris nå" (som mobil, uten skillelinjer), og statuspillen tar
     egen rad under -- venstrejustert, aldri bredere enn 420px. */
  @container pintel (max-width: 940px) {
    .price-intel-metrics-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px 0; width: 100%; }
    .price-intel-metric-current { grid-column: 1 / -1; }
    .price-intel-metric-col, .price-intel-metric-col:first-child { padding: 0 14px 0 0; border-left: none; }
    .price-intel-status-pill { flex: 1 1 100%; max-width: 420px; }
  }
  /* Grafens "hylle" -- 680px, dvs. grafens EGEN native viewBox-bredde
     (`_render_price_intelligence_chart()` sin `width=680`), ikke et
     vilkårlig tall -- runde 2, rapport #3: "the chart is still too
     large... the attached image is the sizing reference", ikke en
     strekking av hele det (nå smalere) modulinnholdet. Innenfor et
     ~940px innholdsområde (1000px modul minus padding) gir 680px synlig,
     bevisst luft på begge sider, som i mockupen. */
  .price-intel-chart-shell { max-width: 980px; margin-inline: auto; padding: 14px 18px 10px; }
  /* Kortene kapper nå i .price-intel-card selv (flex-basis 260px, se
     over) -- her settes kun et TAK per kort (runde 2, rapport #4/#6) slik
     at 2 eller 3 kort forblir sin egen, tiltenkte bredde og heller
     etterlater synlig luft i raden (via justify-content:center) enn å
     strekkes til å fylle 100 % når et kort (typisk "Kjøper du flere
     esker?") er betinget skjult. */
  .price-intel-card { flex: 0 1 calc((100% - 24px) / 3); max-width: calc((100% - 24px) / 3); }
  .price-intel-stat { flex: 1 1 0; padding: 0 14px; border-left: 1px solid var(--border); }
  .price-intel-stat:first-child { border-left: none; padding-left: 0; }
  .price-intel-stat-strip { flex-wrap: nowrap; padding: 16px 20px; }
}

/* Price Intelligence Gold Standard v1 — ChatGPT branch, 2026-10-05.
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
.price-intel-chart-shell{border:0;border-radius:0;padding:0}
.price-intel-chart-toolbar{padding:0 2px 8px;border-bottom:1px solid var(--border);margin-bottom:8px}
.price-intel-chart-toolbar-badge{border:0;background:transparent;padding:0}
.price-intel-chart .price-history-chart{border:0;border-radius:0}
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
.price-intel-section-head h3{margin:0;font-family:'Space Grotesk',sans-serif;font-size:1.05rem;color:var(--ink)}
.price-intel-section-head p{margin:5px 0 0;max-width:680px;font-size:.76rem;line-height:1.5;color:var(--muted)}
.price-intel-history-table-wrap{margin-top:14px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.price-intel-history-table{width:100%;border-collapse:collapse;min-width:760px;font-size:.76rem}
.price-intel-history-table th,.price-intel-history-table td{padding:10px 12px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
.price-intel-history-table thead th{font-size:.64rem;text-transform:uppercase;letter-spacing:.045em;color:var(--muted);font-weight:600}
.price-intel-history-table th:first-child,.price-intel-history-table td:first-child{text-align:left}
.price-intel-history-table tbody th{font-weight:650;color:var(--ink)}
.price-intel-history-table tbody td{font-family:'IBM Plex Mono',monospace;color:var(--ink)}
/* Smal desktop (modulens innhold <= 800px, dvs. ca. 860-1010px viewport): den
   8-kolonners tabellen har min-width 760px og ville scrollet sidelengs. Her
   komprimeres den i stedet: ingen min-width, tettere padding, mindre
   kolonneoverskrifter som får brytes over to linjer. Gjelder kun >=860px
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
  .price-intel-chart-shell{max-width:980px}
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
  .price-intel-history-details[open]>summary::after{content:"–"}
  .price-intel-history-details:not([open])>.price-intel-history-table-wrap{display:none}
  .price-intel-history-table-wrap{overflow:visible}
  .price-intel-history-table{min-width:0;display:block}
  .price-intel-history-table thead{display:none}
  .price-intel-history-table tbody{display:block}
  .price-intel-history-table tr{display:grid;grid-template-columns:1fr 1fr;gap:9px 16px;padding:14px 0;border-bottom:1px solid var(--border)}
  .price-intel-history-table th,.price-intel-history-table td{display:block;padding:0;border:0;text-align:left!important;white-space:normal}
  .price-intel-history-table tbody th{grid-column:1/-1;font-family:'Space Grotesk',sans-serif;font-size:.88rem}
  .price-intel-history-table td{font-size:.78rem}
  .price-intel-history-table td:nth-child(2)::before{content:"Laveste";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(3)::before{content:"Høyeste";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(4)::before{content:"Median";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(5)::before{content:"Prisspenn";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(6)::before{content:"Prisendringer";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(7)::before{content:"Vinnerbytter";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
  .price-intel-history-table td:nth-child(8)::before{content:"Butikker billigst";display:block;font-family:Inter,sans-serif;font-size:.66rem;color:var(--muted);text-transform:uppercase}
}

"""

# Navnet er historisk (fonter) - inneholder nå også favicon-taggene, satt
# inn her bevisst fremfor å røre alle 9 sidetypenes <head> hver for seg.
# favicon-o.png er den oransje "O"-en (ring + ansiktssilhuett) beskåret ut
# av static/logo.png, med hvit bakgrunn gjort gjennomsiktig - se historikk
# 2026-08-11.
# Fontene er selv-hostet (static/fonts/, @font-face-regler i SHARED_STYLE)
# i stedet for å lastes fra Google Fonts -- unngår to eksterne DNS-oppslag +
# en render-blokkerende stylesheet-forespørsel per sidevisning (2026-08-18).
# Kun "latin"-delmengden (U+0000-00FF m.fl.) er lastet ned -- dekker æøå
# (innenfor U+0000-00FF) og all norsk tekst på siden, samme reelle
# tegndekning siten allerede hadde via Google Fonts sin "latin"-delmengde.
FONT_LINKS = """<link rel="preload" href="/static/fonts/inter-400.woff2" as="font" type="font/woff2" crossorigin>
<link rel="icon" type="image/png" href="/static/favicon-o.png">
<link rel="apple-touch-icon" href="/static/favicon-o.png">
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "WebSite", "name": "Kontaktlinser.no", "url": "https://kontaktlinser.no", "description": "Uavhengig prissammenligningstjeneste for kontaktlinser, linsevæske og øyedråper fra norske nettbutikker.", "inLanguage": "nb", "publisher": {"@type": "Organization", "name": "Kontaktlinser.no", "url": "https://kontaktlinser.no", "logo": {"@type": "ImageObject", "url": "https://kontaktlinser.no/static/logo.png"}, "sameAs": ["https://www.facebook.com/kontaktlinser.no/"]}}</script>"""

# GTM lastes IKKE lenger automatisk - kun definert her, faktisk kalt av
# CONSENT_SCRIPT etter samtykke (lagret fra forrige besøk) eller når bruker
# trykker "Godta alle"/"Lagre valg" med statistikk på i samtykke-banneret.
# Ingen <noscript>-fallback lenger: uten JS kan vi ikke innhente samtykke
# interaktivt, og skal derfor ikke sette GTM-cookien i det hele tatt for de
# besøkende - se CONSENT_BANNER_HTML/CONSENT_SCRIPT og /personvern/.
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
# alle leverandører"-lenke som avslører de faktiske navnene. Selve
# /personvern/-siden navngir dem fortsatt åpent (det er nettopp poenget med
# den siden). To kategorier, ikke bundlet i ett avkryssingsfelt (Datatilsynets
# krav): statistikk (GTM) og affiliate-sporing (settes av nettverkets/
# forhandlerens eget domene når du klikker en tilbudslenke, ikke av oss
# direkte, men du skal likevel kunne velge det bort på forhånd).
CONSENT_BANNER_HTML = """<div id="consent-overlay" class="consent-overlay" hidden>
  <div class="consent-modal" role="dialog" aria-modal="true" aria-labelledby="consent-title">
    <div id="consent-step-main">
      <h2 id="consent-title">Vi bruker cookies på Kontaktlinser.no</h2>
      <p class="consent-text">
        Vi og våre samarbeidspartnere bruker cookies til statistikk og for å
        registrere når et kjøp hos en forhandler skjedde via en lenke fra oss,
        slik at vi kan motta provisjon. Du velger selv, og kan endre valget
        når som helst. <a href="/personvern/">Mer informasjon</a>.
      </p>
      <div class="consent-actions">
        <button type="button" id="consent-customize" class="consent-btn consent-btn-secondary">Innstillinger</button>
        <button type="button" id="consent-reject" class="consent-btn consent-btn-secondary">Kun nødvendige</button>
        <button type="button" id="consent-accept" class="consent-btn consent-btn-primary">Godta</button>
      </div>
    </div>
    <div id="consent-step-settings" hidden>
      <h2>Cookieinnstillinger</h2>
      <p class="consent-text">Velg hvilke typer cookies du godtar. Nødvendige cookies kan ikke slås av.</p>

      <div class="consent-category">
        <div class="consent-category-row">
          <span>Nødvendig</span>
          <input type="checkbox" class="consent-toggle" checked disabled>
        </div>
      </div>
      <div class="consent-category">
        <div class="consent-category-row">
          <span>Statistikk</span>
          <input type="checkbox" class="consent-toggle" id="consent-stats" checked>
        </div>
        <p class="consent-category-desc">Måler trafikk og bruk av siden, slik at vi vet hva som faktisk er nyttig.</p>
      </div>
      <div class="consent-category">
        <div class="consent-category-row">
          <span>Affiliate-sporing</span>
          <input type="checkbox" class="consent-toggle" id="consent-affiliate" checked>
        </div>
        <p class="consent-category-desc">Registrerer at et kjøp kom via en lenke fra oss, slik at forhandleren kan betale riktig provisjon.</p>
        <button type="button" id="consent-toggle-providers" class="consent-link-btn">Vis alle leverandører</button>
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

// Utgående-klikk-sporing (2026-08-31): pusher ETT dataLayer-event per
// klikk på en tilbudslenke (data-retailer er satt av render_offer_card/
// render_winner_widget), uansett om forhandleren har avtale eller ikke --
// gir en per-forhandler klikkoversikt selv for de uten avtale, bl.a. som
// dokumentasjon når vi ber om en avtale senere. Trygt å kjøre UBETINGET
// (ikke bak samtykke-sjekk her): window.dataLayer.push() gjør ingenting i
// seg selv, det bare legger til i et array i minnet -- selve sendingen
// skjer først når GTM.js er lastet, og det skjer FORTSATT kun etter
// samtykke (se apply()/__loadGTM over). Uten samtykke blir arrayet aldri
// lest av noe, og forsvinner med siden ved neste navigasjon.
//
// Forhandlerlenker åpnes i ny fane (target="_blank", se render_offer_card/
// render_winner_widget) -- brukeren beholder Kontaktlinser.no åpent og kan
// sammenligne flere butikker uten å miste sammenligningen, samme mønster
// bekreftet hos andre prissammenligningstjenester. Siden fanen med DENNE
// siden ALDRI navigerer bort, er det ingen kappløp mot GTM-sendingen lenger
// -- vanlig window.open()/target="_blank"-navigering kan skje helt normalt,
// vi trenger bare å pushe dataLayer-eventet ved siden av.
//
// eventCallback/eventTimeout-mønsteret under er likevel beholdt som
// fallback for en lenke uten target="_blank" (skulle en sånn dukke opp et
// sted): tilbudslenker som navigerer i SAMME fane rekker ofte å forlate
// siden FØR GTM faktisk har sendt hendelsen til GA4 -- bekreftet i praksis
// 2026-08-31 (klikk ga aldri noe utslag i sanntidsrapporten). preventDefault()
// + maks 300ms forsinket navigering løser det for det tilfellet.
window.dataLayer = window.dataLayer || [];
document.addEventListener('click', function (e) {
  var link = e.target.closest('a[data-retailer]');
  if (!link) return;
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

  if (link.target === '_blank') {
    // Nettleseren håndterer selve navigeringen til den nye fanen -- vi
    // pusher bare sporingseventet ved siden av, ingen forsinkelse nødvendig.
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
# ned i filen) fordi TOPBAR_HTML under nå viser ekte merkelogoer i
# dropdownene -- en modulnivå-konstant kan ikke referere noe som først
# defineres senere i filen.
#
# Nøytral, beskrivende bruk for å identifisere hvilket produkt/merke det
# faktisk er snakk om - selve definisjonen av nominativ varemerkebruk.
#
# 2026-08-30: 16 merker (Air Optix, Avaira, Biofinity, Biomedics, Biotrue,
# Clariti, Dailies, FreshLook, MyDay, Precision1, Precision7, Proclear,
# PureVision, SofLens, TOTAL30, ULTRA) hadde en periode en logo beskåret
# fra et lisensiert produktbilde (se logo_sources.json-kommentaren og
# git-historikken for teknikken) -- FJERNET igjen samme dag etter at
# bruker testet resultatet live og fant kvaliteten for dårlig (utvasket
# kontrast, beskjæringsartefakter som en gjenværende stripe/strek fra
# emballasjedesignet). Disse 16 har derfor bevisst INGEN logofil her nå,
# og faller tilbake til den vanlige initial-badgen inntil en ekte
# offisiell kilde er funnet (se /vilkar/-diskusjonen om ECP-portaler --
# Alcon/CooperVision/Bausch+Lomb sine er alle innloggingssperret for
# fagpersoner, i motsetning til Acuvue sin åpne kilde under). Ikke legg
# disse tilbake med samme beskjæringsteknikk uten en tydelig kvalitets-
# forbedring først.
BRAND_LOGOS = {
    "acuvue": ("acuvue.png", False),
    "adore": ("adore.png", False),
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


# Samme ikonsett/fargepalett/undertekster som forsidens kategori-rader
# (render_home_page) -- flyttet til modulnivå slik at TOPBAR_HTML sin
# Kontaktlinser-dropdown kan gjenbruke nøyaktig samme visuelle språk uten
# å finne opp et nytt sett eller duplisere ikonene. IKKE mint her,
# reservert for "laveste pris" andre steder på siden.
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
    "manedslinser": "Populær og kostnadseffektiv",
    "dagslinser": "Friske linser hver dag",
    "toriske-linser": "For deg med astigmatisme",
    "fargede-linser": "Endre eller forsterk øyefargen",
    "multifokale-linser": "For nær, mellom og fjern",
}

# Kort, faktabasert "hva er X"-forklaring per kategori -- vises i en egen
# boks på kategorisiden (2026-09-05, del av kategorisideredesignet). Samme
# forsiktige stil som GUIDE_CONTENT: generelle, godt etablerte fakta, ingen
# spesifikke medisinske råd. "les_mer_slug" er bevisst IKKE hardkodet til én
# fast guide -- render_category_page faller tilbake til første guide i
# kategoriens egen guides-liste hvis ingen egen verdi er satt her.
CATEGORY_EXPLAINERS = {
    "dagslinser": "Dagslinser, også kalt endagslinser eller 1-dagslinser, brukes én dag og kastes etter bruk. De gir god hygiene, høy komfort og krever ikke rengjøring eller oppbevaring i linsevæske.",
    "manedslinser": "Månedslinser brukes i inntil 30 dager (følg alltid optikerens anbefaling) før de byttes ut, og rengjøres og oppbevares i linsevæske mellom hver bruk. Ofte rimeligere per dag enn dagslinser.",
    "toriske-linser": "Toriske linser er utformet for å korrigere astigmatisme (skjevhet i hornhinnen) i tillegg til vanlig nær- eller langsynthet. De har en spesiell form som gjør at de ikke roterer fritt i øyet.",
    "fargede-linser": "Fargede kontaktlinser endrer eller forsterker øyenfargen, og finnes både med og uten styrke. Følg alltid bruksanvisningen nøye, også for linser uten synskorrigering.",
    "multifokale-linser": "Multifokale linser korrigerer alderssyn (presbyopi) ved å kombinere flere styrker i samme linse, slik at du kan se skarpt på flere avstander uten lesebriller.",
}

_SHIELD_ICON = '<path d="M12 3l7 3v5c0 5-3.2 7.8-7 9-3.8-1.2-7-4-7-9V6z"/><path d="M9 12l2 2 4-4"/>'
_BUILDING_ICON = '<path d="M3 21V10l6-4 6 4v11"/><path d="M9 21v-5h4v5"/><path d="M15 21V13l6-3v11"/>'


def _mega_link_row(icon_svg: str, label: str, sublabel: str, href: str) -> str:
    """Rad med lite ikon + tittel + undertekst + pil -- til 'Nyttig å
    vite'-listen i Merker-dropdownen. Alle href-er som bruker denne MÅ
    peke til en side som faktisk finnes -- ikke gjett."""
    return f'''<a class="mega-link-row" href="{href}">
          <span class="mega-link-row-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon_svg}</svg></span>
          <span class="mega-link-row-text"><span class="mega-link-row-label">{label}</span><span class="mega-link-row-sub">{sublabel}</span></span>
          <svg class="mega-link-row-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
        </a>'''


# Kontaktlinser-dropdownen (2026-09-29) -- Kai viste Lensway sin
# tilsvarende meny som referanse: "slik som her under kontaktlinser.no
# gjøres mye mer minimalistisk når man klikker på kontaktlinser" --
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
    ("dagslinser", "Dagslinser"), ("manedslinser", "Månedslinser"),
    ("toriske-linser", "Toriske linser"), ("fargede-linser", "Fargede linser"),
    ("multifokale-linser", "Multifokale linser"),
]
_MEGA_CATEGORY_LINKS_HTML = "\n        ".join(
    f'<a class="mega-menu-link" href="/kontaktlinser/{slug}/">{escape(label)}</a>' for slug, label in _MEGA_CATEGORIES
)

# Søkeboksen i toppmenyen (2026-09-27, brukerens eget ønske om at den skal
# passe visuelt til resten av menyen -- "lik høyde", altså samme skriftstørrelse
# som menyteksten) er BEVISST bygget med de samme klassenavnene
# (search-row/search-input/search-icon/search-btn/search-suggestions) som
# LENS_SEARCH_STYLE/LENS_SEARCH_JS allerede definerer for forsiden/guide-
# sidene -- fungerer derfor med NØYAKTIG samme JS uten en eneste ny linje kode,
# kun en mer spesifikk CSS-overstyring for selve størrelsen (samme mønster som
# .guide-cta .search-input allerede bruker for SIN variant).
# Vises på ALLE sider UNNTATT forsiden (som har sin egen, større søkeboks i
# heroen) -- derfor to konstanter bygget fra samme funksjon i stedet for to
# hardkodede kopier av hele menyen.
_TOPBAR_SEARCH_HTML = """<form class="topbar-search search-row" id="topbar-search-panel" role="search" action="#" onsubmit="return false;">
    <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/></svg>
    <label for="topbar-lens-search" class="visually-hidden" style="position:absolute;left:-9999px;">Søk etter linse eller merke</label>
    <input type="search" id="topbar-lens-search" class="search-input" placeholder="Søk etter linse eller merke" autocomplete="off">
    <button type="button" class="search-btn">Søk</button>
    <div class="search-suggestions"></div>
  </form>"""


def _topbar_html(show_search: bool = True) -> str:
    search_html = _TOPBAR_SEARCH_HTML if show_search else ""
    # Kompakt mobil-header (2026-09-27, Kai: "søkefunksjon øverst på
    # produktkort på mobil er unødvendig. heller et søkeikon oppe er fint.
    # Feks. logo, søkeikon og et annet ikon for meny oppe til høyre [...]
    # kompakt og bra fra toppen"). Under 700px er BÅDE .topbar-nav (de fire
    # menyknappene) OG .topbar-search (selve inputfeltet) skjult som
    # standard, og vises via disse to knappene i stedet -- søk og meny
    # uavhengig av hverandre, akkurat som Kai spesifiserte. Kun søkeknappen
    # er betinget på show_search (forsiden har sin egen, større hero-søk og
    # trenger den ikke); menyknappen vises alltid.
    #
    # Selve søkeskjemaet (.search-row/.search-input osv.) er FYSISK UENDRET
    # -- kun CSS-synligheten endres via .is-open. Elementet finnes i DOM-en
    # hele tiden (display:none skjuler visningen, ikke selve noden), så
    # LENS_SEARCH_JS sin document.querySelectorAll('.search-row') finner
    # det akkurat som før uansett åpen/lukket tilstand -- ingen risiko for
    # å gjenintrodusere "søket svarer ikke"-bugen fra tidligere i dag
    # (se CLAUDE.md), siden selve elementet aldri fjernes/legges til.
    mobile_actions_html = (
        (
            '<button type="button" class="topbar-icon-btn" id="topbar-search-toggle" aria-label="Søk" aria-expanded="false" aria-controls="topbar-search-panel">'
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
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Kontaktlinser <span class="nav-caret">▾</span></button>
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
        <a class="mega-menu-link mega-see-all" href="/#merker">Alle merker →</a>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Merker <span class="nav-caret">▾</span></button>
      <div class="mega-menu mega-menu-rich">
        <div class="mega-rich-grid mega-rich-grid-2col">
          <div class="mega-rich-col">
            <div class="mega-panel-kicker">Merker</div>
            <div class="mega-panel-heading">Bla i alle kontaktlinsemerker</div>
            <p class="mega-panel-text">Ekte merker og optikerkjedenes egne serier, sortert alfabetisk.</p>
            <div class="mega-col-title" style="margin-top:18px;">Nyttig å vite</div>
            {_mega_link_row(_SHIELD_ICON, "Optikerkjedenes varemerker", "Samme linse, andre navn", "/private-label/")}
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Alle merker A–Å</div>
            <div class="mega-allbrands">
              {_MEGA_ALL_BRANDS_HTML}
            </div>
          </div>
        </div>
        <a class="mega-menu-link mega-see-all" href="/#merker">Se alle merker →</a>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Tilbehør <span class="nav-caret">▾</span></button>
      <div class="mega-menu">
        <div class="mega-col">
          <div class="mega-col-title">Kategori</div>
          <a class="mega-menu-link" href="/linsevaeske/">Linsevæske</a>
          <a class="mega-menu-link" href="/oyedraper/">Øyedråper</a>
          <a class="mega-menu-link" href="/tilbehor/">Etui og hjelpemidler</a>
        </div>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Guider <span class="nav-caret">▾</span></button>
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
            <a class="mega-menu-link" href="/guide/manedslinser-vs-dagslinser/">Dagslinser vs. månedslinser</a>
            <a class="mega-menu-link" href="/guide/kontaktlinser-med-astigmatisme/">Toriske linser og astigmatisme</a>
            <a class="mega-menu-link" href="/guide/multifokale-kontaktlinser/">Multifokale linser</a>
            <a class="mega-menu-link" href="/guide/harde-eller-myke-linser/">Harde eller myke linser</a>
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Øyehelse</div>
            <a class="mega-menu-link" href="/guide/vedlikehold-av-kontaktlinser/">Vedlikehold og hygiene</a>
            <a class="mega-menu-link" href="/guide/kontaktlinser-og-torre-oyne/">Tørre øyne</a>
            <a class="mega-menu-link" href="/guide/rode-oyne-og-svie-med-kontaktlinser/">Røde øyne og svie</a>
            <a class="mega-menu-link" href="/guide/kan-jeg-bytte-kontaktlinsemerke-selv/">Bytte linsemerke selv</a>
          </div>
        </div>
        <a class="mega-menu-link mega-see-all" href="/guider/">Se alle guider →</a>
      </div>
    </div>
  </nav>
  {search_html}
</div>
<style>{LENS_SEARCH_STYLE}
/* Ingen margin-left:auto -- det ga et unaturlig stort, tomt gap før boksen
   (brukeren så dette live og ba om at den heller skal starte rett til høyre
   for "Guider", med SAMME mellomrom som resten av menyen -- altså vanlig
   flex-flyt, samme .topbar sitt gap:32px som alt annet i raden -- og deretter
   strekke seg selv til kanten av headeren via flex-grow, ikke via margin. */
.topbar-search {{ flex: 1 1 220px; min-width: 200px; }}
/* Skriftstørrelsen MATCHER .nav-trigger sin (0.95rem) med vilje -- brukerens
   krav var at bokstavene i søkefeltet skal ha samme høyde som menyteksten,
   ikke bare at boksen skal se "passe stor" ut. Total høyde (padding+tekst+
   kant) lander da svært nær .nav-trigger sin egen høyde uten noe eget
   høyde-tall å holde synkront med menyen manuelt. */
.topbar-search .search-input {{ width: 100%; font-size: 0.95rem; padding: 7px 62px 7px 32px; border-radius: 9px; box-shadow: none; }}
.topbar-search .search-icon {{ left: 10px; width: 15px; height: 15px; }}
.topbar-search .search-btn {{ right: 4px; top: 4px; bottom: 4px; padding: 0 13px; font-size: 0.82rem; border-radius: 6px; }}
@media (max-width: 699px) {{
  /* Skjult som standard (Kai, 2026-09-27: søkeikon i stedet for et synlig
     felt) -- .topbar-search-toggle over åpner den igjen via .is-open.
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
          // fallback-tall (70px) ikke tar høyde for at logo+navigasjon kan
          // brytes til to linjer på svært smale skjermer.
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

  // Kompakt mobil-header (2026-09-27): meny-/søk-ikonet åpner/lukker
  // .topbar-nav/.topbar-search uavhengig av hverandre. Lukker .topbar-nav
  // (meny) når søk åpnes og omvendt, siden begge tar full bredde under
  // 700px og ellers kan stå åpne oppå hverandre.
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
    ("clearlii", "Clearlii"),
    ("dailies", "Dailies"),
    ("freshlook", "FreshLook"),
    ("live", "Live"),
    ("miru", "MIRU"),
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
# CLAUDE.md for metodikk og bevisste skjønnsvurderinger (f.eks. hvorfor
# enkelte gamle produkter peker til merke-siden i stedet for et konkret
# produkt, når riktig pakningsstørrelse/variant ikke kunne bekreftes).
# GitHub Pages kan ikke servere .aspx som HTML (bekreftet: mime-db mangler
# .aspx, serveres som application/octet-stream) - derfor ingen ekte
# server-side 301 her, kun en klientsidevis omdirigering fra 404-siden (se
# render_404_page). Ekte 301-er via Cloudflare er en egen, separat plan.
# Nøklene MÅ være små bokstaver (matches mot location.pathname.toLowerCase()
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
      <a href="/guide/manedslinser-vs-dagslinser/">Månedslinser vs. dagslinser</a>
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
    lavest pris (slå på «Pris inkludert frakt» for å se totalprisen). Vi kan motta provisjon når du handler via
    lenkene våre &ndash; det påvirker verken prisen du betaler eller rangeringen
    av tilbud. Vi selger ikke kontaktlinser selv. Kontaktlinser er reseptvare:
    rådfør deg alltid med optiker ved valg av linsetype og styrke.
  </p>
  <div class="footer-bottom">
    <span>&copy; {year} Kontaktlinser.no</span>
    <a href="/">Forside</a>
    <a href="/guider/">Guider</a>
    <a href="/om-oss/" rel="author">Om oss</a>
    <a href="/personvern/" rel="privacy-policy">Personvern og cookies</a>
    <a href="/vilkar/" rel="terms-of-service">Vilkår og ansvarsfraskrivelse</a>
    <a href="/meld-feil/">Meld feil</a>
    {_contact_email_link()}
    <a href="https://www.facebook.com/kontaktlinser.no/" rel="me noopener" target="_blank" aria-label="Kontaktlinser.no på Facebook">Facebook</a>
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
    "Shopping4net": ("shopping4net.png", False),
    "Lensit": ("lensit.svg", False),
    "Specsavers": ("specsavers.svg", False),
    "Synsam": ("synsam.svg", False),
    "Brilleland": ("brilleland.svg", False),
    "Apotekhjem": ("apotekhjem.png", False),
}


# Kjedenavnet (Synsam/Brilleland/Specsavers/Coptikk) skal IKKE vises på disse
# seriene ute på siden (bruker-beslutning 2026-08-30) -- de skal fremstå som
# egne merker, på linje med ekte linsemerker. Full kobling til kjeden ligger
# fortsatt på /private-label/, en egen side dedikert til akkurat den
# forklaringen. PRIVATE_LABEL_SUBBRANDS brukes derfor kun til å slå opp
# visningsnavnet (chain -> serienavn), aldri til å vise/nevne selve kjeden.
PRIVATE_LABEL_SUBBRANDS = {
    "Brilleland": "iWear",
    "Synsam": "EyeQ",
    "Specsavers": "Easyvision",
    "Coptikk": "Ascend",
    "Mister Spex": "TrueLens",
}

# "Alle merker A-Å" i toppmenyens Merker-dropdown (2026-09-29). Kai, med
# skjermbilde av den gamle dropdownen: "brukere trenger ikke bli sendt til
# Produsent. De ønsker å komme til kontaktlinse merker. La oss lage en pen
# oversikt over kun alle merker her, også iwear og de." -- erstatter den
# tidligere "Bla etter produsent"-listen (som pekte til /produsent/-sidene)
# med en komplett, alfabetisk liste over ALLE /merke/-sider: ekte merker
# (FOOTER_BRANDS) OG optikerkjedenes egne serier (PRIVATE_LABEL_SUBBRANDS)
# om hverandre -- bevisst IKKE splittet i to seksjoner slik footeren gjør
# det (footeren skiller dem eksplisitt), siden Kai her spesifikt ba om at
# iWear m.fl. skal stå sammen med de andre i én oversikt. Bygget fra de to
# samme, allerede etablerte kildelistene -- ingen tredje merkeliste å
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
# render_illustration_disclaimer_page(). Filene er beskåret fra brukerens
# eget bilde med (R)-merket fjernet (bevisst -- disse er ikke registrerte
# varemerker, så et ® ville vært misvisende). Nøkkel er SERIENAVNET
# (PRIVATE_LABEL_SUBBRANDS sin verdi), aldri kjeden. iWear/Lumiere7 mangler
# fortsatt en fil/produktkobling.
PRIVATE_LABEL_SUBBRAND_LOGOS: dict[str, str] = {
    "EyeQ": "pl-eyeq.png",
    "Easyvision": "pl-easyvision.png",
    "Ascend": "pl-ascend.png",
}

# LÅST rekkefølge (satt 2026-08-30, bekreftet låst -- ikke tidsstyrt --
# 2026-08-31). Se den fyldige begrunnelsen i render_home_page() der denne
# brukes. Lest direkte av lenspricer.no sin faktiske forside (bilde-
# alt-tekster på merke-rutenettet, i den rekkefølgen de vises der)
# 2026-08-30, med to bevisste ombytter (Acuvue<->Dailies, Biomedics<->ULTRA)
# for å ikke være en 1:1-kopi. IKKE vist noe sted på siden -- brukeren har
# eksplisitt bekreftet at dette forblir en ren intern/kode-detalj.
# Opprinnelig tenkt som midlertidig (erstattes av ekte trafikktall etter
# ~3 måneder), men bruker bestemte 2026-08-31 at rangeringen i stedet
# skal stå fast ut 2026 -- ingen automatisk overgang til trafikkbasert
# sortering er planlagt lenger. Endre kun denne listen når bruker
# eksplisitt ber om det, ikke på en tidsfrist.
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
# CSS-farger/gradienter + tekst, ALDRI en påstand om ekte produktemballasje.
# Se render_illustration_disclaimer_page() for teksten som forklarer dette
# (lenket fra hvert sted en illustrasjon vises). Design-canvaset i de
# originale mockupene var 560x225px -- alle mål under er konvertert til cqw
# (container query width, relativt til elementets EGEN bredde via
# container-type:inline-size) slik at illustrasjonen skalerer korrekt uansett
# hvor liten/stor boksen den vises i er (mobil-merkekort vs. produktrutenett).
# Klassenavn er prefikset (pli-eyeq-/pli-ascend-/pli-ev-) for å aldri kunne
# kollidere med andre klasser i SHARED_STYLE (f.eks. .active/.variant/.count
# er alle for generiske navn til å la stå uprefikset i en så stor stilark).
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
   canvas, MYE bredere/flatere enn de vanlige produktbilde-boksene (4:3 på
   merkekort, fast 190px høyde på produktfliser) -- strekkes de inn i disse
   uendret, blir de visuelt forvrengt. .pli-frame overstyrer merkekortets
   aspect-ratio til illustrasjonens EGEN, og .pli-tile-wrap gir samme
   effekt på produktfliser (der boksen har fast høyde + sentrerer innholdet
   i stedet for aspect-ratio) ved å style bredden i stedet, med høyden
   utledet automatisk via cqw i selve illustrasjonen. */
/* .pli-frame er nå en INDRE wrapper inni .brand-card-photo (ikke lenger
   satt direkte på .brand-card-photo selv) -- .brand-card-photo beholder
   sin vanlige 4:3-boks som ALLE kort (bilde eller illustrasjon) deler,
   slik at rutenettet stretcher til lik høyde uten å bli rotete (funnet
   og fikset 2026-08-30: ulik boks-høyde mellom bilde-kort og
   illustrasjon-kort ga et synlig ujevnt rutenett når PC-versjonen fikk
   samme bildeførte kort som mobil). Illustrasjonen sentreres i stedet
   for å strekkes/forvrenges, med sin egen naturlige 560:225-proporsjon
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
# eyeq-illustrasjonspakke-v4.html sitt products-array, nøkkel byttet fra
# navn til private_labels.json sin slug (samme 20 EyeQ/Synsam-oppføringer).
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
# EKTE produsenten bak Ascend-serien, ikke kjeden (Coptikk), så den nevnes
# fortsatt -- kun kjedenavnet (Coptikk) er det brukeren ikke vil ha med her.
ASCEND_ILLUSTRATIONS: dict[str, dict] = {
    "ascend-evolve-plus": {"variant": "evolve+", "qty": "6", "desc": "monthly contact lenses", "family": "evolve"},
    "ascend-active-1-day": {"variant": "active", "qty": "30", "desc": "daily disposable contact lenses", "family": "active"},
    "ascend-premier": {"variant": "premier", "qty": "6", "desc": "monthly contact lenses", "family": "premier"},
    "ascend-active-multifocal-1-day": {"variant": "active multifocal", "qty": "30", "desc": "multifocal contact lenses", "family": "active-mf"},
    "ascend-evolve-plus-toric": {"variant": "evolve+ toric", "qty": "6", "desc": "contact lenses for astigmatism", "family": "evolve-toric"},
    "ascend-active-toric-1-day": {"variant": "active toric", "qty": "30", "desc": "contact lenses for astigmatism", "family": "active-toric"},
    "ascend-premier-toric": {"variant": "premier toric", "qty": "6", "desc": "contact lenses for astigmatism", "family": "premier-toric"},
    "ascend-premier-multifocal-distance": {"variant": "premier multifocal · distance", "qty": "6", "desc": "multifocal contact lenses", "family": "premier-mf"},
    "ascend-premier-multifocal-near": {"variant": "premier multifocal · near", "qty": "6", "desc": "multifocal contact lenses", "family": "premier-mf"},
}

# Fra easyvision-illustrasjonspakke-v1.html. Den originale pakken hadde en
# "Specsavers"-tekstlinje øverst i illustrasjonen -- FJERNET her med vilje
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
    2,49:1-illustrasjonscanvas -- contain unngår at boksmotivet beskjæres,
    på bekostning av synlig luft i sidekantene på det brede rutenett-kortet.

    Rot-årsak funnet 2026-09-29 (etter to mislykkede forsøk -- fast px-grense,
    så prosent-grense, begge uten effekt): den delte `.pli-tile-wrap` (satt
    av KALLEREN, ikke her) har `aspect-ratio:560/225`, men INGEN
    `overflow:hidden` på seg selv. Uten det ignorerer CSS-motoren
    aspect-ratio når et barn sitt "automatic minimum size" (min-content)
    krever mer plass -- og et bilde i portrettformat (340×~270,
    height:auto) krever nettopp det, så `.pli-tile-wrap` ble stille strukket
    til bildets EGEN ratio (~1,25:1) i stedet for den tiltenkte 2,49:1,
    og spiste dermed opp all plassen "Egen illustrasjon..."-bildeteksten
    trengte (bekreftet med getBoundingClientRect(): `.pli-tile-wrap` sin
    egen høyde matchet bildets naturlige ratio, ikke 560/225, uansett
    skjermbredde). De tre andre kjedenes CSS-tegnede illustrasjoner rammes
    aldri av dette siden ALT innholdet deres allerede er absolutt
    posisjonert (se `_pli_iwear()` m.fl.) -- de bidrar null til
    "automatic minimum size"-beregningen. Løsningen her er identisk:
    `<img>` tas ut av normal flyt med `position:absolute` inni en tom
    `position:relative`-wrapper (som selv IKKE bidrar med noe
    min-content-krav), slik at `.pli-tile-wrap` sin aspect-ratio endelig
    får virke som tiltenkt, og bildeteksten får plassen den trenger."""
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
    hvis vi ikke har noen. Kjeden brukes KUN til å velge riktig visuell
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
    (ikke kjedens offisielle/registrerte merke) vises. Første avsnitt er
    brukerens egen tekst om illustrasjonene, limt inn ordrett 2026-08-30.
    Andre avsnitt (om serie-logoene) er lagt til samme dag, etter
    brukerens eget ønske om å utvide denne siden fremfor å lage en egen --
    samme underliggende begrunnelse i begge tilfeller ("egen fremstilling,
    ikke offisielt materiale")."""
    body = """<p>Kontaktlinser.no benytter både originale produktbilder og egne produktillustrasjoner. Når et originalt produktbilde ikke er tilgjengelig, kan vi bruke en egen illustrasjon for å gjøre det enklere å identifisere og sammenligne produkter. Slike illustrasjoner er ikke originale produktbilder eller offisiell produktemballasje fra produsenten. Utforming, farger, tekst og andre visuelle detaljer kan derfor avvike fra produktets faktiske emballasje.</p>
  <p>Enkelte optikerkjeders egne merkenavn (private label-serier som EyeQ, Ascend og Easyvision) vises med en egen, selvlaget ordmerke-logo i stedet for kjedens offisielle logo. Dette er ikke et registrert varemerke eller en offisiell logo fra kjeden -- det er en egen visuell fremstilling laget av kontaktlinser.no for å gjøre seriene lettere å kjenne igjen.</p>
  <p>Produktnavn, logoer og varemerker tilhører sine respektive rettighetshavere. Kontaktlinser.no er en uavhengig prissammenlignings- og informasjonstjeneste og selger ikke kontaktlinser selv.</p>"""
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
  <p class="breadcrumb"><a href="/">Hjem</a> › Om produktillustrasjoner</p>
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
# offisielle produsentkilder (aldri gjettet på navnelikhet) -- se agent-logg
# for kildene. KUN de fire globale produsentene + Eyemed Technologies (ADORE)
# dekker samtlige 18 linsemerker i katalogen per dags dato. Linsevæske-/
# øyedråpe-merker (Opti-Free, Systane, ReNu, Hylo osv.) er bevisst IKKE med
# her ennå -- egen runde om ønskelig, annen produsent-miks.
MANUFACTURERS = {
    "coopervision": {
        "name": "CooperVision",
        "official_url": "https://coopervision.no/",
        "official_url_label": "coopervision.no",
        "brand_slugs": ["biofinity", "proclear", "myday", "avaira", "clariti", "biomedics", "live"],
        "description_html": """
<p>CooperVision ble stiftet i 1980 som en egen forretningsenhet under det som i dag heter
The Cooper Companies, med hovedkontor i San Ramon, California. Selskapet er verdens
tredje største produsent av myke kontaktlinser, og er særlig kjent for Aquaform Comfort
Science-materialet som brukes i Biofinity-serien.</p>
""",
    },
    "alcon": {
        "name": "Alcon",
        "official_url": "https://www.myalcon.com/no/contact-lenses/",
        "official_url_label": "myalcon.com/no",
        "brand_slugs": ["dailies", "air-optix", "precision1", "precision7", "total30", "freshlook"],
        "description_html": """
<p>Alcon ble grunnlagt i 1945 i Fort Worth, Texas, og har i dag hovedkontor i Genève i
Sveits etter å ha blitt skilt ut som eget børsnotert selskap fra Novartis i 2019. Alcon
regnes som verdens største øyehelseselskap, og står bak vanngradient-teknologien i
Dailies Total1 og Precision7 – markedets eneste linse godkjent for én ukes bruk.</p>
""",
    },
    "bausch-lomb": {
        "name": "Bausch + Lomb",
        "official_url": "https://www.bausch.no/",
        "official_url_label": "bausch.no",
        "brand_slugs": ["purevision", "soflens", "biotrue", "ultra"],
        "description_html": """
<p>Bausch + Lomb er et av bransjens eldste selskaper, grunnlagt i 1853 i Rochester, New
York av John Jacob Bausch og Henry Lomb. Selskapet regnes i dag som en av de fire største
kontaktlinseprodusentene i verden, og står bak MoistureSeal-teknologien i ULTRA-serien –
Biotrue-produktene er utviklet med utgangspunkt i egenskapene til kroppens egen tårefilm.</p>
""",
    },
    "jnj-vision": {
        "name": "Johnson & Johnson Vision",
        "official_url": "https://www.acuvue.com/nb-no",
        "official_url_label": "acuvue.com",
        "brand_slugs": ["acuvue"],
        "description_html": """
<p>Johnson & Johnson Vision lanserte i 1987 Acuvue – verdens første masseproduserte
engangskontaktlinse – og regnes som verdens ledende produsent av engangslinser.
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
på kosmetiske og fargede kontaktlinser under merkenavnet ADORE. Selskapet er vesentlig
mindre enn de tre globale produsentene over, med salg i over 30 land.</p>
""",
    },
    "menicon": {
        "name": "Menicon",
        "official_url": "https://www.menicon.com/consumer/",
        "official_url_label": "menicon.com",
        "brand_slugs": ["miru"],
        "description_html": """
<p>Menicon ble grunnlagt i 1951 av Kyoichi Tanaka og var Japans første kontaktlinseprodusent.
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
og Kinsus, med hovedkontor i Taoyuan i Taiwan. Selskapet er børsnotert (TSE: PEGAVISION) og
driver egen forskning, utvikling og produksjon av myke kontaktlinser – blant annet
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
# ALDRI kopiert fra en forhandlers markedsføringstekst -- se f.eks.
# SofLens-runden der en forhandlerside påsto 70% vanninnhold generelt for
# dagslinsen, mens produsentens egen kilde bekrefter 59%. Plasseres UNDER
# produktlisten på merke-siden, ikke over -- prissammenligningen er
# fortsatt hovedfunksjonen, samme prinsipp som private label-sidene.
BRAND_CONTENT: dict[str, str] = {
    "soflens": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om SofLens</h2>
<p>SofLens er en linseserie fra Bausch + Lomb, et av bransjens eldste kontaktlinseselskaper
(grunnlagt i 1853). Serien dekker de fleste behov: dagslinser, månedslinser, toriske linser
for astigmatisme og multifokale linser for alderssyn (presbyopi).</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i SofLens-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>SofLens Daily Disposable</strong> – hilafilcon B, 59 % vanninnhold. Kastes etter én
  dags bruk.</li>
  <li><strong>SofLens 38</strong> – polymacon, 38 % vanninnhold (navnet viser til dette tallet).
  Månedslinse.</li>
  <li><strong>SofLens Toric</strong> – alphafilcon A, 66 % vanninnhold. Bruker Bausch + Lombs
  patenterte Lo-Torque-design, som holder linsen stabil i riktig rotasjon – avgjørende for at
  den toriske korreksjonen av astigmatisme skal sitte riktig gjennom dagen.</li>
  <li><strong>SofLens Multifocal</strong> – bruker Natra-Sight Optics, med en bredere
  overgangssone mellom nær-, mellom- og langsynt-korreksjon, beregnet på alderssyn.</li>
</ul>
""",
    "acuvue": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Acuvue</h2>
<p>Acuvue er Johnson & Johnson Visions kontaktlinsemerke, og regnes som verdens ledende
produsent av engangslinser. Familien spenner fra dagslinser til linser for to ukers bruk,
i sfæriske, toriske og multifokale varianter.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i Acuvue-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>1-Day Acuvue Moist</strong> – etafilcon A, 58 % vanninnhold. Bruker LACREON-
  teknologi, som binder et fuktighetsbevarende stoff direkte inn i linsematerialet.</li>
  <li><strong>Acuvue Oasys</strong> (2-ukers) – senofilcon A, en silikonhydrogel med 38 %
  vanninnhold og høy oksygengjennomtrengelighet. Bruker HYDRACLEAR PLUS-teknologi, en
  fuktighetsgivende overflatebehandling som etterligner tårefilmen.</li>
  <li><strong>Acuvue Oasys MAX 1-Day</strong> – samme senofilcon A-materiale som Oasys, men
  tilført TearStable-teknologi for jevn fuktighet gjennom dagen og et OptiBlue-filter som
  reduserer blått/fiolett lys fra skjermer med om lag 60 %.</li>
</ul>
""",
    "dailies": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Dailies</h2>
<p>Dailies er Alcons familie av dagslinser, og spenner over flere atskilte produktlinjer med
ulike materialer og teknologier – fra den opprinnelige Focus Dailies-serien til de nyere
AquaComfort Plus- og Total1-linjene.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i Dailies-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Dailies AquaComfort Plus</strong> – nelfilcon A, 69 % vanninnhold. Et
  fuktighetssystem tilsatt linsen (HPMC, PEG og PVA) skal gi jevn komfort gjennom dagen.</li>
  <li><strong>Dailies Total1</strong> – delefilcon A, en silikonhydrogel bygget med
  "vanngradient"-teknologi: kjernen har 33 % vanninnhold, mens selve overflaten som møter
  øyet når over 80 % vann. Gir vesentlig høyere oksygengjennomtrengelighet enn
  AquaComfort Plus.</li>
  <li><strong>Focus Dailies</strong> – den opprinnelige Dailies-linjen, senere supplert av
  AquaComfort Plus og Total1.</li>
</ul>
""",
    "biofinity": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Biofinity</h2>
<p>Biofinity er CooperVisions flaggskip blant månedslinser, og finnes i sfærisk, torisk,
multifokal og utvidet bruk-variant (XR). Serien er bygget rundt selskapets egen
Aquaform Comfort Science-teknologi.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Biofinity er laget av comfilcon A, med 48 % vanninnhold. Aquaform Comfort
Science-teknologien binder vann tilsvarende det dobbelte av materialets egen vekt, og skaper
naturlig fuktbarhet uten behov for en egen overflatebehandling – i motsetning til enkelte
andre linser som er avhengige av en tilsatt fuktighetsbelegg.</p>
""",
    "purevision": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om PureVision</h2>
<p>PureVision er en av Bausch + Lombs eldre og mest etablerte månedslinser, bygget rundt
selskapets AerGel-teknologi.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">PureVision er laget av balafilcon A, en silikonhydrogel med 36 % vanninnhold.
AerGel-teknologien slipper gjennom naturlige nivåer med oksygen og er motstandsdyktig mot
proteinavleiringer, mens den nyere PureVision2 i tillegg har ComfortMoist-teknologi som
tilfører ekstra fuktighet på linseoverflaten.</p>
""",
    "biotrue": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Biotrue</h2>
<p>Biotrue ONEday er Bausch + Lombs dagslinse, utviklet med utgangspunkt i egenskapene til
hornhinnen og tårefilmen.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Biotrue er laget av nesofilcon A (markedsført som "HyperGel"), med 78 %
vanninnhold – tilsvarende hornhinnens eget naturlige vanninnhold. Surface Active Technology
skal bevare 98 % av fuktigheten i opptil 16 timer, mens en egen Peri-Ballast-utforming holder
de toriske variantene stabile gjennom vanlige blunkebevegelser.</p>
""",
    "ultra": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om ULTRA</h2>
<p>ULTRA er Bausch + Lombs nyere månedslinse, bygget rundt MoistureSeal-teknologien.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">ULTRA er laget av samfilcon A, en silikonhydrogel med 46 % vanninnhold.
MoistureSeal-teknologien er utviklet gjennom en to-trinns produksjonsprosess og skal bevare
95 % av linsens fuktighet i opptil 16 timer.</p>
""",
    "air-optix": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Air Optix</h2>
<p>Air Optix er Alcons etablerte månedslinse-serie, med varianter for sfærisk korreksjon,
astigmatisme, alderssyn og fargede linser.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Air Optix plus HydraGlyde er laget av lotrafilcon B, en silikonhydrogel med
33 % vanninnhold. HydraGlyde-teknologien er en overflatebehandling som kontinuerlig tilfører
fuktighet til linseoverflaten, mens SmartShield-teknologien skal gjøre linsen mer
motstandsdyktig mot avleiringer.</p>
""",
    "precision1": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Precision1</h2>
<p>Precision1 er Alcons daglinse, ofte et førstevalg for nye linsebrukere.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Precision1 er laget av verofilcon A, en silikonhydrogel med 51 % vanninnhold
i kjernen. SmartSurface-teknologien tilfører et tynt, permanent fuktighetslag med over 80 %
vanninnhold på selve overflaten, slik at linsen kombinerer stabil oksygengjennomtrengelighet
fra kjernen med fuktighet på overflaten.</p>
""",
    "precision7": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Precision7</h2>
<p>Precision7 er Alcons ukelinse (7 dagers brukstid) – en mellomting mellom en dagslinse og
en månedslinse i bytterutine.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Precision7 er laget av serafilcon A, med 55 % vanninnhold. Activ-Flo-
teknologien er ment å etterfylle fuktighet gjennom hele den syv dager lange brukstiden.</p>
""",
    "total30": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om TOTAL30</h2>
<p>TOTAL30 er Alcons premium månedslinse, bygget på samme vanngradient-prinsipp som
Dailies Total1, bare i en versjon beregnet for en hel måneds bruk.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">TOTAL30 er laget av lehfilcon A, med 55 % vanninnhold i kjernen som stiger
gradvis til nær 100 % ved selve overflaten (vanngradient-teknologi). Celligent-teknologien
skal bidra til å holde linseoverflaten motstandsdyktig mot bakterier og fettavleiringer
gjennom hele den 30 dager lange brukstiden.</p>
""",
    "freshlook": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om FreshLook</h2>
<p>FreshLook er Alcons serie med fargede kontaktlinser, bygget på selskapets 3-i-1-
fargeteknologi som blander tre nyanser i én linse for et naturlig utseende.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Godt å vite</h2>
<p style="font-size:1rem;line-height:1.7;">Fargede linser krever samme resept og tilpasning hos optiker som andre
kontaktlinser, selv uten styrke – se vår <a href="/guide/kosmetiske-kontaktlinser/">guide om
kosmetiske og fargede kontaktlinser</a>.</p>
""",
    "avaira": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Avaira</h2>
<p>Avaira Vitality er CooperVisions to-ukerslinse, med sfærisk og torisk variant.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Avaira Vitality er laget av fanfilcon A, med 55 % vanninnhold. Linsen har
klasse I UV-blokkering, den høyeste klassifiseringen, som blokkerer over 90 % av UVA- og
over 99 % av UVB-strålene.</p>
""",
    "biomedics": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Biomedics</h2>
<p>Biomedics er en eldre og godt etablert linseserie fra CooperVision, med varianter for
både dags- og to-ukersbruk.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Biomedics er laget av ocufilcon D, en hydrogel med 55 % vanninnhold, som
er myk og fleksibel og bidrar til fuktighet gjennom brukstiden.</p>
""",
    "clariti": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Clariti</h2>
<p>Clariti 1 day er CooperVisions rimeligere daglinse-serie i silikonhydrogel, med sfærisk,
torisk og multifokal variant.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Clariti er laget av somofilcon A, med 56 % vanninnhold og innebygget
UV-beskyttelse. WetLoc-teknologien skal fordele fuktighet jevnt over hele linseoverflaten.</p>
""",
    "myday": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om MyDay</h2>
<p>MyDay er CooperVisions premium daglinse, med sfærisk, torisk og multifokal variant –
samt MyDay MiSight, en egen daglinse godkjent for myopikontroll hos barn.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">MyDay er laget av stenfilcon A, med 54 % vanninnhold. Linsen bruker samme
Aquaform-teknologi som Biofinity, som binder vann naturlig i materialet uten behov for en
egen overflatebehandling.</p>
""",
    "proclear": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Proclear</h2>
<p>Proclear er CooperVisions linseserie rettet spesielt mot brukere som opplever tørre øyne,
i dags-, to-ukers- og multifokal variant.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Proclear er laget av omafilcon A, tilført CooperVisions PC-teknologi. Denne
bygger inn fosforylkolin (PC) – et stoff som naturlig finnes i cellene i kroppen – som binder
vann til og gjennom linsen for å redusere rask uttørking.</p>
""",
    "adore": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om ADORE</h2>
<p>ADORE er en linseserie for kosmetiske og fargede kontaktlinser fra den italienske
produsenten Eyemed Technologies, med flere fargekolleksjoner (blant annet Bi-tone og Dare).
Selv uten styrke regnes fargede linser som medisinsk utstyr og krever samme resept og
tilpasning hos optiker som andre kontaktlinser – se vår
<a href="/guide/kosmetiske-kontaktlinser/">guide om kosmetiske og fargede kontaktlinser</a>.</p>
""",
    "miru": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Miru</h2>
<p>Miru er den japanske produsenten Menicons daglinse-serie, med varianter for sfærisk
korreksjon, astigmatisme og alderssyn.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Miru 1day UpSide er laget av midafilcon A, en silikonhydrogel med 56 %
vanninnhold. Menicon kombinerer MeniSilk Air-teknologi (fuktighet) med NanoGloss Pro
(en glatt, lav-friksjons overflate) for å gi linsen komforten til en tradisjonell hydrogel-
linse med håndteringsegenskapene til en silikonhydrogel.</p>
""",
    "live": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Live</h2>
<p>Live er CooperVisions rimeligere daglinse, posisjonert mot unge og førstegangsbrukere.
Linsen selges også under andre navn hos enkelte utenlandske forhandlere/optikerkjeder, som
en del av samme CooperVision-plattform.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materiale og teknologi</h2>
<p style="font-size:1rem;line-height:1.7;">Live er laget av somofilcon A, en silikonhydrogel med 56 % vanninnhold –
samme materiale som brukes i CooperVisions Clariti 1 day. AquaGen-teknologien skal binde
fuktighet naturlig til og gjennom linsen.</p>
""",
    "clearlii": """
<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 12px;">Om Clearlii</h2>
<p>Clearlii er et apotek-eksklusivt linsemerke, opprinnelig lansert i Stockholm i 2011 under
navnet Apotekslinsen. Merket ble til Clearlii og fikk egenproduserte linser i 2018, og selges i
dag hos 800–900 apotek og 150+ optikere i fem nordiske land. Linsene produseres av den
taiwanske produsenten Pegavision.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:24px 0 12px;">Materialer og teknologi i Clearlii-familien</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Clearlii Daily</strong> – etafilcon A, 58 % vanninnhold. Tilsatt hyaluronsyre for
  linsebrukere med tørre øyne.</li>
  <li><strong>Clearlii Vitamin</strong> – samme etafilcon A-materiale (58 % vanninnhold) som
  Daily, i tillegg tilsatt vitamin E, B6 og B12 samt hyaluronsyre.</li>
  <li><strong>Clearlii Hydrogel Månedslinser</strong> – polymacon, 38 % vanninnhold, med et
  mykt kant-design ("Silk & Soft Edge").</li>
</ul>
""",
}


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


def _obfuscate_email(email: str) -> str:
    """Numeriske HTML-entiteter per tegn - vises normalt i alle nettlesere og
    fungerer uten JS (ingen brudd på "innhold skal finnes i rå-HTML"-
    prinsippet), men gjør adressen usynlig for enkle regex-baserte
    e-post-innhøstere som leser rå HTML/tekst uten å rendre den."""
    return "".join(f"&#{ord(c)};" for c in email)


def _contact_email_link(css_class: str = "") -> str:
    obf = _obfuscate_email("kontakt@kontaktlinser.no")
    cls = f' class="{css_class}"' if css_class else ""
    return f'<a href="mailto:{obf}"{cls}>{obf}</a>'


def _mailto_link(subject: str, label: str, css_class: str = "") -> str:
    """Som _contact_email_link(), men med et forhåndsutfylt emnefelt og en
    egen lenketekst i stedet for å gjenta selve e-postadressen -- brukt av
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
                          illustration_html: str | None = None, specs_row_html: str = "") -> str:
    """Delt kortmarkup for merke-/kategori-/tilbehør-/private label-rutenett
    (render_brand_page, render_category_page, render_solution_category_page,
    render_private_label_brand_page) -- én mal, page-spesifikt innhold
    (kategori-badge, "sekundærlinje" under produktnavnet: produsent/merke/
    ekte-produkt-lenke) sendes inn som ferdig HTML fra hver kallested.
    illustration_html (egen tegnet grafikk, se render_private_label_illustration)
    vinner over både image_url og fallback_initials når den er satt."""
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

    if lowest:
        num = f'{lowest["price_nok"]:,.0f}'.replace(",", " ")
        store_html = f'Lavest hos <span class="product-tile-store-name">{escape(lowest["retailer"])}</span>'
        if other_count > 0:
            store_html += f' <span class="product-tile-store-count">+ {other_count} butikker</span>'
        price_block = (
            f'<div class="product-tile-price-label">Fra (ekskl. frakt)</div>'
            f'<div class="product-tile-price"><span class="product-tile-price-number">{num}</span>'
            f'<span class="product-tile-price-currency">kr</span></div>'
            f'<div class="product-tile-store-line">{store_html}</div>'
        )
    else:
        price_block = '<div class="product-tile-store-line">Ingen tilbud tilgjengelig</div>'

    return f"""<div class="product-tile"{data_attr}>
  <a class="product-tile-image-link" href="{href_esc}"><div class="{image_cls}">{image_block}</div></a>
  <div class="product-tile-body">
    {category_badge}
    <a class="product-tile-name-link" href="{href_esc}"><div class="product-name">{escape(name)}</div></a>
    {secondary_line_html}
    {specs_row_html}
    <div class="product-tile-divider"></div>
    <a class="product-tile-price-link" href="{href_esc}">{price_block}</a>
  </div>
  <a class="product-tile-cta" href="{href_esc}">Sammenlign priser →</a>
</div>"""


def _last_sunday(year: int, month: int) -> datetime:
    d = datetime(year, month, 31, tzinfo=timezone.utc)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def oslo_date(checked_at: str):
    """Datoen (norsk tid) et UTC-tidspunkt faller på. Egen sommertid-regel (EU:
    siste søndag i mars kl. 01:00 UTC til siste søndag i oktober kl. 01:00 UTC)
    i stedet for zoneinfo, siden tzdata ikke er garantert installert. Viktig for
    den nattlige kjøringen (~22:45 UTC = etter midnatt i Norge): den synlige datoen
    og sitemapens lastmod skal være samme dato."""
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


# Rangering blant forhandlere MED affiliate-avtale, brukt KUN til å avgjøre
# rekkefølge/vinner ved eksakt lik totalpris (aldri prisen selv). Lavere tall
# = vinner tidligere.
#
# Bruker bekreftet 2026-08-31 provisjonssatsene for samtlige fem
# affiliate_feed-forhandlere: Lenson, Lensway, Shopping4net og Extra
# Optical har alle 8 %, Apotekhjem har 10 %. Ved eksakt lik totalpris gir
# en høyere prosentsats av samme kronebeløp reelt mer inntjening, så
# Apotekhjem rangeres foran de fire andre. De fire med lik sats (8 %) er
# bevisst IKKE innbyrdes rangert -- ingen prioritering mellom dem er
# meningsfull siden 8 % av samme beløp er samme beløp uansett hvem som
# vinner (alfabetisk fallback i _tie_break_key() holder for dem).
AFFILIATE_TIE_PRIORITY: dict[str, int] = {
    "Apotekhjem": 0,
}


# Forhandlere vi MIDLERTIDIG lenker direkte til (uten affiliate-sporing) fordi
# deres affiliate-lenke er ødelagt hos nettverket. Extra Optical (Adtraction,
# a=1487383541&as=2102229792) svarer "Invalid link -- broken or no longer
# available" for ALLE sporingslenker fra og med 2026-10-05 (feeden gir fortsatt
# de samme lenkene, så feilen er hos Adtraction/programmet, ikke her). Slike
# tilbud rendres som ikke-affiliate (source "direct_link": rel nofollow, UTM,
# ingen Chillout-clickout, ingen affiliate-fortrinn ved lik pris) med
# mål-URL-en hentet ut av `url=`-parameteren i Adtraction-lenken. TILBAKERULLING:
# tøm settet når Adtraction-lenkene virker igjen (én endring, ingen annen kode).
DIRECT_LINK_RETAILERS: set[str] = {"Extra Optical"}


def _direct_url_from_adtraction(url: str) -> str | None:
    """Mål-URL-en bak en Adtraction-sporingslenke (`...&url=<mål>`, alltid siste
    parameter). None hvis lenken ikke har et http(s)-mål -- da beholdes
    originalen uendret."""
    m = re.search(r"[?&]url=(https?://[^\s]+)$", url)
    return unquote(m.group(1)) if m else None


def _tie_break_key(o: dict) -> tuple:
    """Sorteringsnøkkel for eksakt lik totalpris -- brukt av BÅDE
    _pick_lowest() (hvem får "Lavest pris"-merket) og reconcile_product()
    sin hovedsortering (rekkefølgen tilbudene faktisk VISES i på siden).
    Disse to brukte ULIK logikk frem til 2026-08-31 -- bruker oppdaget at
    en forhandler UTEN avtale (skrapet) kunne vises FØR en med avtale i
    selve listen (kun alfabetisk/opprinnelig rekkefølge ved lik pris),
    selv om _pick_lowest() allerede korrekt ga badgen til avtale-
    forhandleren. Nå deler begge samme regel:
    1) affiliate-avtale (source == "affiliate_feed") før ingen avtale,
    2) blant flere avtaler, se AFFILIATE_TIE_PRIORITY over,
    3) alfabetisk som siste, forutsigbare fallback."""
    is_affiliate = o.get("source") == "affiliate_feed"
    return (
        0 if is_affiliate else 1,
        AFFILIATE_TIE_PRIORITY.get(o["retailer"], 999),
        o["retailer"],
    )


def _pick_lowest(eligible: list[dict]) -> dict | None:
    """Velger ÉN vinner blant tilbud på lager og ikke utdaterte, ved eksakt
    lik totalpris (2026-08-18, etter avtale med brukeren) -- se
    _tie_break_key() for selve regelen, delt med reconcile_product() sin
    hovedsortering siden 2026-08-31. Prisen er identisk for kunden i alle
    disse tilfellene uansett -- regelen avgjør kun hvem som får "Lavest
    pris"-merket (og hvem som vises først i listen) når det ikke er noen
    reell prisforskjell å vise frem. Se disclosure-teksten på
    produktsidene, som nevner dette eksplisitt."""
    if not eligible:
        return None
    lowest_total = min(o["total"] for o in eligible)
    tied = [o for o in eligible if o["total"] == lowest_total]
    if len(tied) == 1:
        return tied[0]
    return min(tied, key=_tie_break_key)


def _add_utm_params(url: str) -> str:
    """UTM-tagger utgående lenker til forhandlere UTEN avtale (skrapet
    kilde) -- 2026-08-31, etter brukerønske. Gir forhandleren mulighet til
    å se i egen analytics at besøket kom fra oss, selv uten aktiv
    affiliate-avtale (nyttig dokumentasjon når vi ber om en avtale senere).
    Affiliate-lenker (source == affiliate_feed) skal ALDRI røres her --
    kalleren sjekker det -- de har allerede nettverkets egne
    tracking-parametre, og å endre URL-en kan i verste fall ødelegge
    attribusjonen av provisjonen vår."""
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
# vises når noe faktisk har sviktet -- ikke på hver push-bygging sent på dagen.
FEED_STALE_HOURS = 36
SCRAPED_STALE_HOURS = 60


def reconcile_product(offers: list[dict], now: datetime, stale_hours: int | None = None) -> list[dict]:
    """Samme logikk som reconcile() i ingest_feed.py, men på rå dict-data
    slik generatoren kan kjøre den direkte på catalog.json uten omveier.

    UTM-tagger her (ETT sted, ikke i hver render-funksjon) siden ALLE
    kallere -- render_offer_card, winner_band, qty-kalkulatorens JSON, og
    JSON-LD-schemaet -- bruker o["url"] fra nettopp denne enrichede
    listen. De tre forste gar na gjennom outbound_url(), som kan bytte
    den ut med en clickout fra Chillout; JSON-LD gjor det ikke. o["url"]
    her er fortsatt leverandorens URL og den eneste kilden til den. En feed-URL for et affiliate-tilbud får ALDRI UTM-parametre,
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
    # >= 2 dager eldre enn sidens nyeste (ikke 1): daglig kjøring med skraping
    # annenhver dag gir vanligvis skrapede tilbud som er 1 dag eldre enn feedene --
    # det er normalt og skal ikke stå på hvert kort. 2+ dager betyr at noe faktisk
    # ikke ble hentet (gjenbrukt tilbud), og da vises datoen ærlig på kortet.
    for o in enriched:
        o["older_than_page"] = newest_day is not None and (newest_day - oslo_date(o["checked_at"])).days >= 2

    eligible = [o for o in enriched if o["in_stock"]]

    # Lensit svarer ikke på gjentatte avtaleforespørsler (4-5 henvendelser
    # uten svar, 2026-09-16) -- etter brukerønske skal de ikke lenger vises
    # når de er billigst (ville gitt dem gratis salg uten noen avtale).
    # De vises fortsatt som et vanlig, ikke-vinnende tilbud når de IKKE er
    # billigst. "Billigst" avgjøres på selve prisen (inkl. evt. uavgjort),
    # ikke bare hvem som til slutt får trofé-merket via tie-break.
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
# (bekreftet ved pikselsampling 2026-08-21: EO ligger på ca. (243,243,243),
# S4N på ekte hvit), MEN de er faste 270x270px-thumbnails uansett produkt
# (bekreftet på 7 stikkprøver samme dag) -- mot Extra Optical sine ekte
# produktbilder i 1760x1200/2200x1500. Ved vår nye, større hero-bildestørrelse
# på PC (340px) blir S4N-bildet synlig oppskalert og uskarpt -- brukeren
# reagerte på nettopp dette. Skarphet/oppløsning veier tyngre enn en liten
# grå-vs-hvit-forskjell i bakgrunnen, så Extra Optical foretrekkes fortsatt
# (tilbake til opprinnelig fil-rekkefølge i sources_config.json, ingen egen
# prioritering nødvendig -- se git-historikk for det forkastede forsøket på
# å foretrekke S4N).
def pick_product_image(offers: list[dict]) -> str | None:
    for o in offers:
        if o.get("image_source") in LICENSED_IMAGE_SOURCES and o.get("image_url"):
            return o["image_url"]
    return None


def _img_tag(image_url: str, alt: str, css_class: str = "", loading: str = "lazy") -> str:
    """<picture>+WebP for våre egne manuelt kuraterte bilder (static/products/*.jpg,
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


def _product_image(product: dict) -> str | None:
    """Et manuelt kuratert produsent-pressebilde (manual_image i
    products_meta.json, se PRODUCT_IMAGES) vinner alltid over et
    skrapet/feed-bilde -- egen research/nedlasting, høyere og mer
    konsistent kvalitet enn det en tilfeldig forhandler sin feed gir.
    Finnes ikke et manuelt bilde, faller vi tilbake til
    pick_product_image() sin vanlige logikk."""
    manual = product.get("manual_image")
    if manual:
        return manual
    return pick_product_image(product["offers"])


TRUCK_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="1" y="7" width="13" height="9" rx="1" fill="currentColor"/><path d="M14 10h4l3 3v3h-7z" fill="currentColor" opacity="0.6"/><circle cx="6" cy="18" r="2" fill="currentColor"/><circle cx="17" cy="18" r="2" fill="currentColor"/></svg>'

# Isometrisk eske-ikon (topp-flate + to sideflater med ulik opasitet for
# skygge/dybde) -- brukt på antallsvelgerens piller, siden "esker" bokstavelig
# talt betyr fysiske pakkeesker, ikke bare et tall.
BOX_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 8l9-4 9 4-9 4-9-4z" fill="currentColor" opacity="0.5"/><path d="M3 8v8l9 4v-8L3 8z" fill="currentColor" opacity="0.8"/><path d="M21 8v8l-9 4v-8l9-4z" fill="currentColor"/></svg>'
# Blyant-ikon for "Eget antall"-pillen -- samme piktogram-språk, men signaliserer
# at dette er en verdi brukeren selv skriver inn, ikke et fast antall esker.
PENCIL_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 17.25V20h2.75L17.81 8.94l-2.75-2.75L4 17.25z" fill="currentColor"/><path d="M19.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 2.75 2.75 1.83-1.83z" fill="currentColor" opacity="0.6"/></svg>'
# Pokal-ikon i vinner-boksen -- gir litt "stas"/humor til å være billigst, ikke
# bare et nøkternt tall.
TROPHY_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M7 4h10v4a5 5 0 0 1-5 5 5 5 0 0 1-5-5V4z" fill="currentColor"/><path d="M7 5H4a3 3 0 0 0 3 4M17 5h3a3 3 0 0 1-3 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/><rect x="10.5" y="13" width="3" height="4" fill="currentColor"/><rect x="7" y="18" width="10" height="2.2" rx="1.1" fill="currentColor"/></svg>'
# Dråpe-ikon for linsetype-badger (toriske/multifokale/fargede linser) og
# kalender-ikon for brukstid-badger (dagslinser/månedslinser/ukelinser) --
# se _product_type_badges().
DROPLET_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M12 2.5c3 4 6 8.2 6 11.8a6 6 0 1 1-12 0c0-3.6 3-7.8 6-11.8z" fill="currentColor"/></svg>'
BASISKURVE_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 18c0-7 4-13 8-13s8 6 8 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
DIAMETER_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M4 12h16" stroke="currentColor" stroke-width="1.6" stroke-dasharray="1.6 2.2"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/></svg>'
TAG_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M11.4 3.6l8 8a2 2 0 0 1 0 2.8l-5 5a2 2 0 0 1-2.8 0l-8-8V4.6a1 1 0 0 1 1-1h6.8z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="8" cy="8" r="1.3" fill="currentColor"/></svg>'
# Nøytral (IKKE mint/grønt -- det fargenavnet er reservert for "laveste pris",
# se designsystem-regelen i CLAUDE.md) avkrysningsikon til enkle faktalister
# som "Kort om X"-boksen på serie-siden.
CHECK_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 12.5l2.5 2.5L16 9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
RESET_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 12a8 8 0 1 1 2.6 5.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M4 17v-5h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
X_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>'
# To overlappende kontaktlinser -- egen tegnet illustrasjon (se
# /om-produktillustrasjoner/) brukt i "Hva er X?"-boksen på kategorisidene.
# Bevisst generisk (samme for alle 5 kategorier), ekte hex i stedet for
# currentColor siden illustrasjonen bruker to ulike blåtoner samtidig.
LENS_PAIR_ILLUSTRATION_SVG = '''<svg viewBox="0 0 120 88" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <ellipse cx="46" cy="48" rx="34" ry="26" fill="#E8EFFE" stroke="#2563EB" stroke-width="2.2"/>
  <ellipse cx="76" cy="40" rx="34" ry="26" fill="#FFFFFF" stroke="#2563EB" stroke-width="2.2"/>
  <path d="M30 36a26 20 0 0 1 18-9" stroke="#2563EB" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.45"/>
  <path d="M60 28a26 20 0 0 1 18-9" stroke="#2563EB" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.45"/>
</svg>'''
CALENDAR_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 9.5h18" stroke="currentColor" stroke-width="1.8"/><path d="M7 3v4M17 3v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
SUN_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'

# Badger på produktsidens hero -- KUN utledet fra verifiserte spesifikasjons-
# felt (Linsetype/Brukstid i products_meta.json), aldri egne påstander eller
# markedsføringsord (se brukerens eksplisitte "ikke uverifiserte slagord"-
# tilbakemelding 2026-08-29). Nøkkelord-basert i stedet for eksakt verdi-match,
# siden feltene er fritekst med reell variasjon ("Ukelinse (7 dager)",
# "Månedslinse (godkjent for kontinuerlig bruk)", "Multifokal og torisk" osv.)
# -- bekreftet mot samtlige verdier i products_meta.json 2026-08-29.
# "Sfærisk" alene gir bevisst INGEN badge -- det er standard-tilfellet for
# de fleste linser, ikke en differensierende egenskap å fremheve.
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
    ("Månedslinse", "Månedslinser"),
    ("3 måneder", "3-månederslinser"),
]


def _product_type_badges(specs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Returnerer (ikon, tekst)-par for hero-badgene, utledet fra Linsetype/
    Brukstid-radene i specs -- se modulnivå-kommentaren over listene for
    hvorfor nøkkelord-match i stedet for eksakt verdi."""
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
            break  # kun én brukstid-badge -- feltet beskriver ett og samme faktum
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
    """Kompakt faktarad i Product Stage, KUN på desktop (Product Desktop Gold
    Standard v1, 2026-09-27, punkt 8: "Facts må komme fra dokumenterte
    produktdata" -- maks 3-4 stk, ALDRI et gjettet/fabrikert tall). Et
    produkt uten f.eks. Basiskurve i specs (som SofLens Daily Disposable)
    viser rett og slett færre fakta i stedet for å finne på et tall --
    konsistent med prosjektets "aldri gjett data"-regel. CSS-en
    (.hero-facts) holder denne skjult under 860px, så mobil-Gold-Standard-
    en er upåvirket uansett."""
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
    items = '<span class="hero-fact-sep">·</span>'.join(f"<span>{f}</span>" for f in facts[:4])
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
    konfigurasjon her" er oppførselen som allerede var utrullet -- ikke a sla
    av noe stille. Er oppsettet derimot lest og tomt, er det en avgjørelse
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
    # "ta bare vekk den grønne Laveste pris i tabellen. Den skal ikke være
    # der lengre") -- den grønne is-lowest-bakgrunnen/kanten markerer
    # fortsatt vinneren visuelt, kun tekstmerket er borte. tags_html-
    # parameteren er derfor ubrukt her nå (beholdt i signaturen for å
    # ikke måtte endre kallestedet i render_price_list()).
    # Produktprisen er hovedtallet (stort), frakt en egen liten linje over --
    # samme mønster som Prisjakt/Klarna bruker, som er det norske brukere er
    # vant til å lese. Vi dropper en egen "Totalt X kr"-linje per rad (var
    # opplevd som støy -- tre tall stablet oppå hverandre på hvert kort);
    # seksjonsoverskriften over lista sier allerede at den er sortert etter
    # totalpris, og toppbanneret viser vinnerens totalsum -- "Lavest pris"-
    # merket (ALLTID totalpris-basert, se reconcile()) er dermed fortsatt
    # etterprøvbart uten at hvert enkelt kort må gjenta regnestykket.
    shipping_text = _shipping_note(o["shipping_nok"], o.get("shipping_policy"))
    rel = "sponsored" if o["source"] == "affiliate_feed" else "nofollow"
    price_label = (
        f'Gå til {escape(retailer)} for {escape(product_name)}, {_fmt_kr(o["price_nok"])}'
        if product_name else f'Se hos {escape(retailer)}, {_fmt_kr(o["price_nok"])}'
    )

    # Hele kortet er selve lenken (ikke bare pris-pillen) -- små knapper er
    # vonde touch-mål på mobil, og det gir uansett bare ett meningsfullt sted
    # å klikke per rad. price-pill er derfor et <span>, ikke en egen <a> --
    # nøstede <a>-tagger er ugyldig HTML og ville brutt visningen.
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
    # lenke, bare la være a produsere en -- og da star leverandor-URL-en igjen,
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
    tilfeldigvis er nådd ved akkurat denne bestillingsstørrelsen" -- å si
    "Gratis frakt" uten forbehold i det siste tilfellet er misvisende, siden
    brukeren lett kan tro forhandleren alltid har fri frakt, ikke bare ved
    dette antallet esker.

    shipping_policy=None betyr at forhandlerens fraktgebyr under fri-frakt-
    grensen faktisk er UKJENT (se compute_shipping_nok() i offer.py, f.eks.
    Vitusapotek/Apotekhjem) -- IKKE at frakten er gratis. compute_shipping_nok()
    returnerer 0.0 som eksplisitt "ukjent"-standard i dette tilfellet, så
    shipping_nok alene kan ikke skille de to -- shipping_policy MÅ sjekkes
    først, ellers vises "Gratis frakt" feilaktig for en ordre godt under en
    kjent fri-frakt-grense."""
    if shipping_policy is None:
        return "Frakt beregnes i kassen"
    if shipping_nok <= 0:
        free_over = shipping_policy.get("free_over")
        if free_over:
            return f"Gratis frakt over {_fmt_kr(free_over)}"
        return "Gratis frakt"
    return f"{_fmt_kr(shipping_nok)} frakt"


# Delt mellom kontaktlinse- og linsevæske/øyedråpe-produktsider -- teksten
# handler om selve sammenligningsmotoren (produktpris/frakt/totalpris-
# begrepene), ikke om noe produktspesifikt, så samme streng brukes ordrett
# begge steder i stedet for å duplisere den.
METHODOLOGY_HTML = """<div class="methodology">
    <h2>Slik sammenligner vi priser</h2>
    <dl>
      <div class="methodology-row"><dt>Produktpris</dt><dd>Prisen butikken oppgir for selve produktet, uten frakt.</dd></div>
      <div class="methodology-row"><dt>Frakt</dt><dd>Fraktkostnaden beregnes for antallet esker du har valgt. Dersom kjøpet kvalifiserer til fri frakt hos butikken, tar beregningen hensyn til dette.</dd></div>
      <div class="methodology-row"><dt>Totalpris</dt><dd>Produktpris for valgt antall pluss eventuell frakt.</dd></div>
      <div class="methodology-row"><dt>Sortering</dt><dd>Standard er lavest produktpris. Slår du på «Pris inkludert frakt», regnes frakten med og butikkene sorteres etter lavest totalpris. Derfor kan butikken med lavest produktpris være en annen enn butikken med lavest totalpris.</dd></div>
      <div class="methodology-row"><dt>Oppdatering</dt><dd>Prisene hentes automatisk og oppdateres daglig.</dd></div>
    </dl>
    <a href="/slik-sammenligner-vi-priser/" style="font-size:0.85rem;font-weight:600;color:var(--blue);text-decoration:none;">Les mer om metodikken vår →</a>
  </div>"""


# Delt mellom produktsider og private-label-sider, slik at "billigst akkurat
# nå"-widgeten ser identisk ut begge steder (se render_winner_widget).
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
   viser nå PRIS (232 kr/eske + 59 kr frakt) og et Savings Signal-merke
   igjen, som erstatter den tidligere "Prisjakt-modellen" (ingen pris i
   selve kortet, kun i lista under) fra tidligere samme dag. Dette er en
   bevisst, eksplisitt instruert reversering -- ikke en glipp -- basert på
   en mye mer detaljert mockup/brief. "Prisjakt-modellen"-kommentaren
   lenger ned i filen er bevisst latt stå som historikk/kontekst for
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
/* Antall + fraktbryter PÅ SAMME RAD, også på mobil (Kai, 2026-09-27:
   "Da er det bare Å få denne rekken på plass.. på en linje på mobil") --
   tittelen flyttet ut til sin egen linje over (se .qty-box-title), denne
   raden er nå KUN pillene + fraktboksen, nowrap uansett bredde. De
   kompakte .qty-pill-reglene lenger ned (scoped til .wrap-product) er
   det som faktisk gjør plassen til overs -- uten dem hadde ikke raden
   hatt en sjanse på 375px. */
.qty-box-row { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; }
.qty-box-row .qty-pills { flex: 1 1 auto; min-width: 0; }
/* Frakt-bryteren som egen boks med ikon/etikett/undertekst/ekte
   vippebryter (2026-09-27, etter mockup) -- egen modifier-klasse
   (.ship-chip-boxed) i stedet for å endre den delte .ship-chip/
   .ship-chip-dot-pillen som linsevæske-/private label-sidene fortsatt
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
   linsevæske-/øyedråpe-/private label-alias-sidene, uendret. */
.qty-pills { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
@media (min-width: 640px) { .qty-pills { grid-template-columns: repeat(6, 1fr); } }
/* Produktsiden derimot: 6 FASTE piller (1/2/4/6/8/10), ingen "Eget" (se
   render_winner_widget() sin qty_choices/include_custom_pill), og
   fraktbryteren flyttet ut av denne raden (se render_price_list()) --
   så det er plass til alle 6 side om side selv på 320px mobil, ingen
   640px-brytpunkt nødvendig her. Scoped via .product-stage (IKKE
   .wrap-product, som viste seg å være delt med linsevæske-/private
   label-/serie-sidene også -- .product-stage finnes derimot KUN i
   render_product_page() sin egen DOM, uansett skjermbredde, siden den
   ble innført som en ustylet wrapper-div rundt .hero-card + qty_html
   allerede på mobil, se Desktop Gold Standard v1-runden samme dag). */
.product-stage .qty-pills { grid-template-columns: repeat(6, 1fr); }
.qty-pill { display: flex; flex-direction: column; align-items: center; gap: 3px; font-family: 'IBM Plex Mono', monospace; background: linear-gradient(180deg, #FFFFFF 0%, var(--mist) 100%); border: 1px solid var(--border); border-radius: 10px; padding: 10px 6px; font-size: 0.9rem; font-weight: 600; text-align: center; cursor: pointer; color: var(--ink); line-height: 1.3; box-shadow: 0 3px 0 #C4D2D9, 0 4px 6px rgba(11,37,69,0.12); transition: transform 0.08s ease, box-shadow 0.08s ease; }
.qty-pill:active { transform: translateY(2px); box-shadow: 0 1px 0 #C4D2D9, 0 2px 3px rgba(11,37,69,0.1); }
.qty-pill svg { width: 20px; height: 20px; color: var(--blue); }
.qty-pill span { font-size: 0.75rem; font-weight: 400; color: var(--muted); }
/* Kompakt pille-variant, KUN på produktsiden (.wrap-product) -- ikon og
   enhetstekst ("eske"/"esker") skjules, kun tallet vises, akkurat som
   mockupen. Linsevæske-/private label-sidene beholder de større,
   fullstendige pillene uendret siden de ikke deler rad med noen
   fraktboks og har god plass. */
.wrap-product .qty-pill { flex-direction: row; justify-content: center; padding: 10px 2px; }
.wrap-product .qty-pill svg, .wrap-product .qty-pill span { display: none; }
@media (max-width: 479px) {
  /* Under 480px: enda knappere -- fraktbryteren deler nå rad med
     "Priser for X esker"-overskriften i .offers-head (flyttet dit fra
     antallsvelgeren, se _ship_chip_boxed_html()), som er trangt på de
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
/* "Eget antall" -- kun linsevæske-/øyedråpe-/private label-alias-sidene
   nå (produktsiden fjernet den, se render_winner_widget() sin
   include_custom_pill-parameter, Kai 2026-09-27: "Ta bort Eget som
   valg av esker"). */
#qty-pill-custom { display: none; }
@media (min-width: 640px) { #qty-pill-custom { display: block; } }
.qty-custom-row { margin-top: 10px; }
#qty-custom-input { width: 140px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; }
/* Erstatter den tidligere "💡 Tips"-linja OG en usynlig (CSS-utenfor-skjerm)
   fallback-tekst -- Kai sin korreksjon 2026-09-27, etter å ha sjekket Googles
   egne spam-retningslinjer: CSS som plasserer tekst utenfor skjermen står
   DER som et eksempel på skjult tekst, mens et ekte, brukbart <details>-
   element (accordion) eksplisitt nevnes som en LEGITIM vis/skjul-mekanisme
   som ikke bryter retningslinjene. https://developers.google.com/search/docs/essentials/spam-policies
   <details> krever ingen JavaScript for å utvides -- innholdet er ekte,
   server-rendret HTML uansett åpen/lukket tilstand, lesbart for både
   mennesker OG roboter uten JS (OAI-SearchBot m.fl. -- IKKE GPTBot, som er
   blokkert i robots.txt og aldri når hit; GPTBot krabber til modelltrening,
   OAI-SearchBot er den som faktisk kan sitere siden i et AI-søkesvar).
   Lukket som standard (ingen "open"-attributt) holder siden kompakt. */
.qty-multi { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 12px; }
.qty-multi summary { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; cursor: pointer; list-style: none; font-size: 0.85rem; color: var(--ink); }
.qty-multi summary::-webkit-details-marker { display: none; }
.qty-multi-label { font-weight: 600; flex-shrink: 0; }
.qty-multi-preview { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; }
.qty-multi-preview strong { color: var(--ink); font-weight: 600; }
.qty-multi-chevron { margin-left: auto; flex-shrink: 0; width: 16px; height: 16px; color: var(--muted); transition: transform 0.15s; }
.qty-multi[open] .qty-multi-chevron { transform: rotate(180deg); }
.qty-multi-body { margin: 10px 0 0; padding-left: 2px; display: flex; flex-direction: column; gap: 5px; font-size: 0.82rem; color: var(--muted); }
.qty-multi-body strong { color: var(--ink); }
"""


def _savings_eligible_offers(offers: list[dict], incl: bool) -> list[dict]:
    """Sammenligningsgrunnlaget for Savings Signal -- IKKE nødvendigvis det
    samme som `eligible` ellers på siden. Kai sin korreksjon 2026-09-27:
    utelat utgåtte (is_stale) tilbud, og i frakt-modus utelat tilbud med
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
    saving_pct = (høyeste - laveste sammenlignbare pris) / høyeste * 100,
    for samme canonical produkt/pakning (gitt, siden `offers` alltid er ett
    produkt) og valgt quantity/prismodus. Avrundes ALLTID nedover
    (Math.floor) slik at vi aldri kommuniserer en større besparelse enn den
    faktiske. Skjules helt under 10 % eller med færre enn 2 gyldige,
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
    ærlig ('+ frakt beregnes i kassen'), late ALDRI som frakt er kjent/inkludert
    når den ikke er det."""
    price_nok = o["price_nok"]
    shipping_policy = o.get("shipping_policy")
    product_total = price_nok * qty
    shipping_nok = compute_shipping_nok(product_total, shipping_policy)
    if incl and shipping_policy is not None:
        return f"{_fmt_kr(product_total + shipping_nok)} inkl. frakt"
    unit_part = f"{_fmt_kr(price_nok)}/{escape(unit_singular)}" if qty == 1 else f"{_fmt_kr(product_total)}/{qty} {escape(unit_plural)}"
    note = _shipping_note(shipping_nok, shipping_policy)
    if note.startswith("Gratis") or note.startswith("Frakt beregnes"):
        return f"{unit_part} · {note}"
    return f"{unit_part} + {note}"


def _ship_chip_boxed_html(id_attr: str) -> str:
    """Den "boksede" frakt-vippebryteren (ikon/etikett/ekte bryter),
    brukt i prislisteheaderen på produktsiden (Kai, 2026-09-27, "MOVE
    SHIPPING TOGGLE ONLY": flyttet UT av quantity-området, inn i
    "Sammenlign priser"/"Priser for X esker"-headeren -- samme
    plassering på BÅDE mobil og desktop). Ingen undertekst ("Vis
    totalpris inkl. frakt") lenger -- Kai eksplisitt: "we do not need
    the current secondary line... Simply show: 🚚 Pris med frakt ○",
    kompakt nok til å høre hjemme i selve headerraden."""
    return (
        f'<button type="button" class="ship-chip ship-chip-boxed" id="{id_attr}" aria-pressed="false">'
        f'<span class="ship-chip-icon" aria-hidden="true">{TRUCK_ICON_SVG}</span>'
        '<span class="ship-chip-label">Pris med frakt</span>'
        '<span class="ship-chip-toggle" aria-hidden="true"></span>'
        '</button>'
    )


def render_winner_widget(best: dict, offers: list[dict], product_name: str | None = None, unit_singular: str = "eske", unit_plural: str = "esker", product_id: str | None = None, clickouts: dict | None = None, wide: bool = False, qty_multi_inline: bool = True, qty_choices: tuple[int, ...] = (1, 2, 4, 6, 10), include_custom_pill: bool = True) -> tuple[str, str, str]:
    """Returnerer (winner_band, qty_box) som ETT tuple: vinnerkortet står i toppen av
    siden, antallsvelgeren (qty_box) som egen seksjon under.

    Product Mobile Gold Standard v1 (2026-09-27, samme dag -- erstatter
    "Prisjakt-modellen" nedenfor, se kommentar der for historikken): kortet
    viser NÅ pris ("232 kr/eske + 59 kr frakt"), et Savings Signal-merke
    ("Spar 43 %", kun ved >=10 % og >=2 sammenlignbare tilbud) og en
    "Gå til butikk"-knapp. `best` er tilbudet med laveste PRODUKTPRIS
    (samme som før). unit_singular/unit_plural: "eske"/"esker" for
    kontaktlinser, "flaske"/"flasker" for linsevæske/øyedråper.

    Standardtilstanden (1 enhet, uten frakt) er ALLTID ekte, ferdig-rendret HTML, og det
    samme er 2/4/10-eksemplene i `<details class="qty-multi">`-raden under velgeren
    ("Pris ved flere esker") -- et vanlig, ekte HTML-element som ikke krever JavaScript
    for å utvides, lesbart av roboter uten JS uansett åpen/lukket tilstand (relevant her
    er OAI-SearchBot, IKKE GPTBot -- GPTBot er blokkert i robots.txt og krabber uansett
    kun til modelltrening, se der). Dette var tidligere en CSS-utenfor-skjerm-skjult
    tekst (til 2026-09-27) -- luket ut etter at Kai sjekket Googles spam-retningslinjer:
    CSS som plasserer tekst utenfor skjermen listes DER som et eksempel på skjult tekst,
    mens et <details>-element eksplisitt nevnes som en legitim vis/skjul-mekanisme.

    Fraktkostnaden regnes på nytt per antall (compute_shipping_nok), ikke bare
    multiplisert med shipping_nok for én enhet -- en fri-frakt-grense som ikke er nådd
    ved 1 enhet kan fint være nådd ved 4, og gir da en annen vinner enn ved enkeltkjøp."""
    if not best:
        return "", "", ""

    rel = "sponsored" if best["source"] == "affiliate_feed" else "nofollow"
    is_affiliate = "1" if best["source"] == "affiliate_feed" else "0"
    aria = f'Gå til {escape(best["retailer"])} for {escape(product_name)}' if product_name else f'Gå til {escape(best["retailer"])}'
    # Standard server-rendret tilstand er alltid qty=1/uten frakt (samme som
    # resten av kortet) -- JS tar over ved antalls-/frakt-bytte, se
    # _QTY_CALC_SCRIPT sin computeSavingsPct()/winnerPriceLine(), som er
    # bevisst holdt i nøyaktig synk med disse to Python-funksjonene.
    savings_pct = compute_savings_pct(offers, 1, False)
    price_line = _winner_price_line(best, 1, False, unit_singular, unit_plural)
    savings_html = (
        f'<div class="winner-savings" id="winner-savings"><span class="winner-savings-label">Spar</span><span class="winner-savings-pct">{savings_pct} %</span></div>'
        if savings_pct is not None else
        '<div class="winner-savings" id="winner-savings" hidden><span class="winner-savings-label">Spar</span><span class="winner-savings-pct">0 %</span></div>'
    )
    # Kortet er en <div>; selve KNAPPEN er lenken (id + tracking-attributter),
    # slik at ingenting havner nøstet inni en annen <a>.
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
  <a class="winner-btn" id="winner-band-link" href="{escape(outbound_url(best, best["retailer"], product_id, clickouts, "winner_band"))}" target="_blank" rel="{rel} noopener" aria-label="{aria}" data-retailer="{escape(best["retailer"])}" data-affiliate="{is_affiliate}">Gå til butikk <span aria-hidden="true">&#8594;</span></a>
</div>"""

    eligible = [o for o in offers if o["in_stock"]]
    if len(eligible) < 2:
        return winner_band, "", ""  # ingen reell antalls-sammenligning å tilby med 0-1 tilbud

    def total_for_qty(o: dict, qty: int) -> float:
        product_total = o["price_nok"] * qty
        return product_total + compute_shipping_nok(product_total, o.get("shipping_policy"))

    # "Eget antall"-pillen fjernet helt (Kai, 2026-09-27: "Ta bort Eget
    # som valg av esker"), erstattet med en ny fast "8"-pille (samme dag,
    # oppfølging: "Antall Esker overalt. 1,2,4,6,8,10, både på desktop
    # og mobil") -- seks faste antall nå, på både mobil og desktop.
    # Frakt-bryteren er samtidig flyttet UT av denne raden (se
    # render_price_list()), så hele bredden er nå pillenes alene.
    pills = "".join(
        f'<button type="button" class="qty-pill{" is-active" if qty == 1 else ""}" data-qty="{qty}">{BOX_ICON_SVG}{qty}<span>{escape(unit_singular) if qty == 1 else escape(unit_plural)}</span></button>'
        for qty in qty_choices
    )
    if include_custom_pill:
        pills += f'<button type="button" class="qty-pill" data-qty="custom" id="qty-pill-custom">{PENCIL_ICON_SVG}Eget<span>antall</span></button>'

    # Kompakt forhåndsvisning i selve <summary>-raden ("2 esker · 514 kr" osv.)
    # pluss en mer detaljert (butikk + frakt) rad per antall i den utvidbare
    # kroppen -- begge deler er ekte, server-rendret HTML uansett åpen/lukket
    # tilstand, se docstringen over.
    multi_preview_parts, multi_detail_parts = [], []
    for qty in (2, 4, 10):
        best_o = min(eligible, key=lambda o: total_for_qty(o, qty))
        total = total_for_qty(best_o, qty)
        qty_shipping = compute_shipping_nok(best_o["price_nok"] * qty, best_o.get("shipping_policy"))
        note = _shipping_note(qty_shipping, best_o.get("shipping_policy"))
        multi_preview_parts.append(f'<span>{qty} {escape(unit_plural)} · <strong>{_fmt_kr(total)}</strong></span>')
        multi_detail_parts.append(
            f'<p>{qty} {escape(unit_plural)} · <strong>{escape(best_o["retailer"])}</strong> · {_fmt_kr(total)} totalt · {note}</p>'
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
    # aldri kan lande på et slikt tilbud (samme regel som reconcile()).
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
    # quantity-området og inn i prislisteheaderen i stedet (Kai, samme
    # dag, IMPORTANT UI CHANGE -- MOVE SHIPPING TOGGLE ONLY: "The toggle
    # belongs to the price comparison section, because it controls
    # which price basis is used for the comparison/ranking" -- gjelder
    # nå BÅDE mobil og desktop, ikke lenger kun desktop som i en
    # tidligere, siden overstyrt versjon av samme instruks). Se
    # render_price_list()'s `product_ship_chip_html`-parameter og
    # `_ship_chip_boxed_html()`. `qty-box-row` inneholder derfor nå KUN
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

    # qty_multi_html ("Pris ved flere esker") returneres nå SEPARAT (egen
    # tredje verdi) i stedet for å alltid ligge inni qty_box -- produktsiden
    # (2026-09-27, Kai: "Teksten Pris ved flere esker, flyttes også ned
    # under priser") plasserer den under prislista i stedet. De to andre
    # kallerne (linsevæske/øyedråper, private label-alias) er uendret --
    # de limer den rett tilbake inn der den var (se kallestedene).
    return winner_band, qty_box, qty_multi_html


# ---------------------------------------------------------------------------
# PRISJAKT-MODELLEN (utrullet 2026-09-27 på alle produktsider: kontaktlinser, linsevæske/
# øyedråper og private label). Avtalt med Kai etter konkurrentgjennomgang: Prisjakt,
# Pricerunner, Prisguiden, godpris og Lenspricer viser alle pris UTEN frakt som standard,
# og Prisjakt har en chip "Pris inkludert frakt" som legger på frakt og sorterer om.
#   - Toppknappen ("Laveste pris ... Gå til tilbud") sier IKKE pris.
#   - Lista under er sortert på produktpris (uten frakt); chippen "Pris inkludert frakt"
#     viser og sorterer på totalpris for valgt antall. Valget huskes (localStorage).
#   - Antallsvelgeren gjelder begge modi.
#   - Kortet med laveste TOTALpris merkes "Lavest totalpris" også i standardvisningen når
#     det er en annen butikk enn den med laveste produktpris (vi påstår aldri "lavest" om
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
   fortsatt `is-collapsed`-klassen og knappen når det er >10 tilbud
   (samme `collapse_after`-param, brukt av BÅDE mobil og desktop, terskel
   hevet fra 3 til 10 på Kais eksplisitte ønske 2026-09-29: "Vis alle
   treff opp til 10 priser, og deretter hvis flere, klikk for å vise
   alle"), men CSS-en her gjør kollapsen usynlig >=860px -- samme
   brytpunkt som resten av sidens desktop-layout (.hero-main sitt grid).
   Ingen JS-endring nødvendig: _QTY_CALC_SCRIPT sin render() sorterer og
   re-append'er HELE listen uansett skjerm-bredde, kollapsen var alltid
   bare et rent CSS-lag oppå den samme, allerede fullstendige listen. */
.offers.is-collapsed .offers-list .offer-card:nth-child(n+11) { display: none; }
.offers-show-more { display: block; width: 100%; margin-top: 10px; padding: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 0.88rem; color: var(--blue); cursor: pointer; text-align: center; }
.offers-show-more:hover { border-color: var(--blue); }
@media (min-width: 860px) {
  .offers.is-collapsed .offers-list .offer-card:nth-child(n+11) { display: flex; }
  .offers-show-more { display: none; }
}
.ship-chip { display: inline-flex; align-items: center; gap: 9px; background: white; border: 1.5px solid var(--border); border-radius: 999px; padding: 9px 16px 9px 12px; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 0.88rem; color: var(--ink); cursor: pointer; transition: border-color 0.15s, background-color 0.15s; }
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
/* Sider uten hero-kolonne (linsevæske, øyedråper, private label): kortet blir
   en bred stripe. Info-elementene (winner-top/retailer/pris-linje) er nå
   flate søsken (ikke lenger nøstet i en .winner-left-wrapper), så de plasseres
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
  /* align-self: center -- kortet er kun så høyt som innholdet og flyter midt i
     kolonnen, i stedet for å strekkes til hele hero-radens høyde (ga et stort
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
  // Dette scriptet ligger FØR .offers og bryteren i kildekoden (vinnerboksen og
  // antallsvelgeren står øverst), så elementer under slås opp først når de brukes.

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
  // nøyaktig -- samme utelatelsesregler (utgått, ukjent frakt i fraktmodus),
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
    if (note.indexOf('Gratis') === 0 || note.indexOf('Frakt beregnes') === 0) return unitPart + ' · ' + note;
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
    // Lik pris -> den andre prisen -> opprinnelig rekkefølge (server har allerede
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
      winnerLink.setAttribute('aria-label', 'Gå til ' + best.o.retailer + (productName ? ' for ' + productName : ''));
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
      card.setAttribute('aria-label', 'Gå til ' + r.o.retailer + (productName ? ' for ' + productName : '') + ', ' + fmtKr(shown) + (incl ? ' inkl. frakt' : ' uten frakt'));
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
    Butikkene sorteres etter lavest produktpris. Slå på «Pris inkludert frakt» for å
    se og sortere etter totalpris (produktpris + frakt) for antallet du har valgt.
    Vi kan få provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på pris, bortsett fra ved eksakt lik pris
    mellom to tilbud, der vi kan prioritere en forhandler vi har avtale med. Varer
    uten bekreftet lager kan ikke vinne «laveste pris», og hvert tilbud viser når det
    sist ble kontrollert.
  </p>"""


def order_by_product_price(offers: list[dict]) -> list[dict]:
    return sorted(offers, key=lambda o: (o["price_nok"], o["total"]) + _tie_break_key(o))


def render_price_list(offers: list[dict], product_name: str, product_id: str, clickouts: dict | None,
                      title: str = "Sammenlign priser og butikker", show_ship_chip: bool = True,
                      qty_unit_label: str | None = None, collapse_after: int | None = None,
                      product_ship_chip_html: str | None = None) -> tuple[str, dict | None]:
    """Prislista med chippen "Pris inkludert frakt". Returnerer (html, ex_best) der ex_best er
    tilbudet med laveste PRODUKTPRIS (på lager) -- det toppknappen (render_winner_widget) skal
    peke på. Statisk standardvisning = uten frakt, antall 1; JS (_QTY_CALC_SCRIPT) tar resten.

    qty_unit_label/collapse_after: kun brukt av produktsiden (Product Mobile
    Gold Standard v1, 2026-09-27) -- qty_unit_label bytter overskriften til
    en dynamisk "Priser for 1 eske" (+ sorteringsetikett) i stedet for
    `title`, og collapse_after (10 på produktsiden) skjuler resten av
    kortene bak en "Vis alle priser (X butikker)"-knapp. Begge er None/av
    som standard,
    så linsevæske-/øyedråpe- og private label-alias-sidene er uendret.

    product_ship_chip_html: kun produktsiden (Kai, 2026-09-27, "IMPORTANT
    UI CHANGE -- MOVE SHIPPING TOGGLE ONLY": "The toggle belongs to the
    price comparison section, because it controls which price basis is
    used for the comparison/ranking" -- gjelder BÅDE mobil og desktop).
    Den FERDIGBYGGEDE frakt-vippebryteren (`_ship_chip_boxed_html()`,
    bygget i render_product_page()), rendres her, høyrejustert i
    .offers-head ved siden av den dynamiske "Priser for X
    esker"-overskriften. None/av som standard, så linsevæske-/
    øyedråpe- og private label-alias-sidene (som fortsatt bruker den
    enkle `show_ship_chip`/`chip`-mekanismen under) er uendret."""
    ordered = order_by_product_price(offers)
    ex_best = next((o for o in ordered if o["in_stock"]), None)

    cards = "\n".join(
        render_offer_card(o, o["retailer"], product_name, product_id, clickouts, is_winner=(o is ex_best))
        for o in ordered
    )
    # show_ship_chip=False på produktsiden (Product Mobile Gold Standard v1,
    # 2026-09-27) -- bryteren flyttet til qty_box i render_winner_widget,
    # ved siden av antalls-tittelen. Standard er fortsatt True, så
    # linsevæske-/øyedråpe- og private label-alias-sidene (som ikke er
    # restrukturert i denne runden) beholder chippen akkurat som før.
    chip = (
        '<button type="button" class="ship-chip" id="ship-chip" aria-pressed="false">'
        '<span class="ship-chip-dot" aria-hidden="true"></span>Pris inkludert frakt</button>'
    ) if (ordered and show_ship_chip) else ""
    # "Sortert etter pris (uten frakt)"-etiketten er ERSTATTET av selve
    # frakt-vippebryteren når den er til stede (Kai, 2026-09-27: "der
    # hvor Sortert etter pris (uten frakt) står i dag som skal da
    # erstattes med switchen") -- bryteren KOMMUNISERER allerede hvilken
    # prisbasis lista er sortert etter (av/på), så en egen tekstetikett
    # ved siden av er overflødig. Uendret (fortsatt med etiketten) for
    # linsevæske-/øyedråpe-/private label-alias-sidene, som ikke har
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
    """Plukker ut ('produkt-stamme', pakningsstørrelse) fra en id som slutter
    på f.eks. '-30pk' eller '-3pk'. Brukes til å finne søsken i andre
    pakningsstørrelser uten å hardkode hvilke størrelser som finnes -- samme
    produkt kan ha 2 eller 3 søsken (f.eks. Dailies AquaComfort Plus i
    30/90/180-pakning)."""
    if not product_id.endswith("pk"):
        return None
    stem, sep, size_part = product_id[:-2].rpartition("-")
    if not sep or not size_part.isdigit():
        return None
    return stem, int(size_part)


def find_pack_siblings(product: dict, products_by_id: dict) -> list[tuple[int, dict]]:
    """ALLE andre pakningsstørrelser av samme faktiske produkt, stigende etter
    pakningsstørrelse. "Samme produkt" = lik produkt-stamme i den interne
    canonical id-en (alt foran avsluttende -Npk) OG samme merke og kategori;
    aldri navnelikhet. En variant med annet navn i stammen (f.eks.
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
    """'2026-08-19' -> '19. august 2026' (eller '19. august' uten årstall)."""
    year, month, day = date_str.split("-")
    text = f"{int(day)}. {_NORWEGIAN_MONTHS[int(month) - 1]}"
    return f"{text} {year}" if with_year else text


# Price Intelligence (Product Gold Standard v1, 2026-09-27) -- gjenbrukbart
# rammeverk for prisutviklings-modulen, IKKE produktspesifikk kode (Kai,
# absolutt regel 8). Periodene som faktisk kan velges avhenger av hvor mye
# historikk vi FAKTISK har for produktet (se _price_intelligence_eligible_
# periods()) -- i dag (2026-09-27) har INGEN produkt mer enn 45 dagers
# historikk (price_history.json sjekket direkte), så 90 dager/6 måneder/1 år
# er deaktivert for absolutt alle produkter ennå. Dette er IKKE hardkodet
# noe sted -- rammeverket aktiverer periodene automatisk etter hvert som
# price_history.json vokser med én dag per bygging (record_price() i
# price_history.py), uten kodeendring.
PRICE_INTELLIGENCE_PERIODS: list[tuple[str, str, int | None]] = [
    ("30d", "30 dager", 30),
    ("90d", "90 dager", 90),
    ("6m", "6 måneder", 182),
    ("1y", "1 år", 365),
    ("all", "All historikk", None),
]

# Toleranse for "stabil pris" (regel 6: "Avoid meaningless claims caused by
# 1 kr fluctuations") -- en endring innenfor +-STATUS_STABLE_TOLERANCE_PCT
# regnes IKKE som en reell opp-/nedgang. Et produkt må ha vært helt
# UENDRET i minst STATUS_FLAT_MIN_DAYS sammenhengende dager (regnet
# bakover fra siste observasjon) for å få den mer spesifikke "flat i N
# dager"-meldingen i stedet for en generisk "stabil"-melding.
STATUS_STABLE_TOLERANCE_PCT = 3.0
STATUS_FLAT_MIN_DAYS = 7


def _price_intelligence_eligible_periods(coverage_days: int) -> list[tuple[str, str, int | None]]:
    """Hvilke av PRICE_INTELLIGENCE_PERIODS vi faktisk har nok data til å
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
      1. flat: prisen har vært helt UENDRET i >=STATUS_FLAT_MIN_DAYS dager
         (regnet bakover fra siste observasjon) -- den mest spesifikke,
         mest informative meldingen når den gjelder.
      2. historical_low/historical_high: dagens pris er nøyaktig lik
         laveste/høyeste pris i DETTE vinduet (ikke nødvendigvis
         all-time -- "relevant history period" i regel 6, konsekvent med
         at alle andre tall i modulen også er periode-relative) OG
         spennet i vinduet er MATERIELT (range_pct >=
         STATUS_STABLE_TOLERANCE_PCT). Uten materialitets-kravet ville et
         produkt som har svingt mellom 449 og 454 kr (~1,1 %) blitt
         flagget "høyeste registrerte pris" i rødt bare fordi dagens pris
         tilfeldigvis traff periodens (ubetydelige) tak -- funnet og
         rettet 2026-09-29 etter et konkret Kai-eksempel (Biofinity Toric
         6-pack). Et lite, ikke-meningsfullt spenn faller i stedet
         gjennom til "stable" via pct_change-sjekken under.
      3. down/up: prisendring fra vinduets FØRSTE til SISTE observasjon,
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
    uten at noe script kjører. Viser ingenting før vi faktisk har minst en
    ukes historikk (en 2-punkts graf fra dag 2 ser useriøs ut). Vokser med
    én dag per bygging inntil price_history.py sin MAX_DAYS-grense (365) er
    nådd. Byttet fra søylediagram til linje+areal 2026-08-21 etter
    brukerønske (så for "klumpete" ut) om noe nærmere Prisjakt sin egen
    prisgraf -- gradienten (priceHistoryFade) går fra mørkere oransje ved
    selve linjen til nesten gjennomsiktig ved grunnlinjen.

    'price' i history-radene er produktets pris ALENE (record_price() i
    generate_pages.py kalles med best["price_nok"], ikke best["total"] --
    endret 2026-08-21 etter brukerønske om at frakt IKKE skal påvirke
    grafen). Y-aksen har prisetiketter på VENSTRE side (brukerens uttrykte
    preferanse, i motsetning til høyre-plasserte referanser). Når prisen
    har vært helt flat i hele perioden (min==max) ville en ekte skala
    kollapse til én linje helt i bunnen av grafen -- lager i stedet et
    symmetrisk kunstig spenn rundt prisen, slik at linjen lander midt i
    grafen med luft (og akseverdier) over og under, ikke pinnet til bunnen."""
    if len(history) < 7:
        return ""

    n = len(history)
    prices = [h["price"] for h in history]
    real_min, real_max = min(prices), max(prices)

    if real_min == real_max:
        # Flat pris hele perioden -- kunstig, symmetrisk spenn rundt
        # prisen (minst 10 kr, ellers 12 % av prisen) slik at søylene
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
        # 'store' finnes kun når historikken er for ETT produkt -- serie-
        # siden sitt gjennomsnitt over flere produkter (se
        # _family_price_insight_data()) har ingen enkelt butikk å vise.
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
# gir et vilkårlig lite vindu når spennet selv er lite -- en ekte ~1 %
# bevegelse fyller da hele grafhøyden og ser ut som et stup/rebound. Gulvet
# under sikrer et visningsspenn på MINST `_CHART_MIN_ABS_RANGE_NOK` kr
# ELLER `_CHART_MIN_PCT_RANGE` av referanseprisen (medianen), whichever er
# størst -- for et ~450 kr-produkt blir det ~9 % = ~40 kr, så en 449->454
# kr-bevegelse fortsatt er synlig, men ikke dominerer hele grafen. Gulvet
# er KUN en nedre grense (regel 14: "Never clip observations to satisfy
# the minimum-domain rule") -- et ekte, større spenn (f.eks. 299->499 kr)
# vinner alltid over gulvet og klippes aldri.
_CHART_MIN_ABS_RANGE_NOK = 25.0
_CHART_MIN_PCT_RANGE = 0.09


def _price_intel_chart_domain(prices: list[float]) -> tuple[float, float]:
    """Y-aksens (min, max) for Price Intelligence-grafen -- se
    _CHART_MIN_ABS_RANGE_NOK/_CHART_MIN_PCT_RANGE over for begrunnelsen.
    Dekker også det tidligere spesialtilfellet "helt flat pris" (real_min
    == real_max) naturlig: da er observert spenn 0, og hele visningsspennet
    kommer fra gulvet alene, symmetrisk rundt prisen -- ingen egen
    if-gren nødvendig lenger."""
    real_min, real_max = min(prices), max(prices)
    reference = statistics.median(prices)
    min_visual_range = max(_CHART_MIN_ABS_RANGE_NOK, reference * _CHART_MIN_PCT_RANGE)
    observed_range = real_max - real_min
    visual_range = max(observed_range, min_visual_range)
    extra = (visual_range - observed_range) / 2
    lo, hi = real_min - extra, real_max + extra
    pad = visual_range * 0.08
    return lo - pad, hi + pad


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
    fortsatt bruker den gamle -- uendret der, se Kai sin regel om å ikke
    røre annet). Mindre vertikal luft, restrained rutenett (2 linjer i
    stedet for 3), ingen synlig prikk per dag -- kun siste punkt (regel 8:
    "no circle marker for every single daily observation... current/latest
    point may have a marker"). Usynlige, brede hover-mål (price-intel-hit)
    beholder ekte per-dag-tooltip (dato + pris) via SVG <title>, helt uten
    JS, akkurat som originalgrafen."""
    n = len(window)
    prices = [h["price"] for h in window]
    real_min, real_max = min(prices), max(prices)
    min_price, max_price = _price_intel_chart_domain(prices)
    price_range = max_price - min_price

    width, height = ((340, 205) if mobile else (680, 140))
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
    # Flere dato-etiketter på desktop (v2-redesign, rapport #3: mockupen
    # viser ~7-9 datoer -- "31. aug · 3. sep · 6. sep · ... · 29. sep",
    # ikke bare første/siste). Desktop rendrer opptil ni tikker. Mobilvarianten bruker samme data, men
    # en egen smal SVG-geometri med tre tikker (første/midt/siste), slik at
    # grafen beholder lesbar høyde og aksetekst på 375px uten horisontal scroll
    # (samme kompakte mobilvisning som før). Ca. én tikk per uke, med et
    # tak på 9 for å unngå overfylt akse på et helt års historikk.
    if mobile and n > 1:
        tick_idx = sorted(set([0, (n - 1) // 2, n - 1]))
    else:
        tick_step = max(1, round((n - 1) / 7)) if n > 1 else 1
        tick_idx = sorted(set(range(0, n, tick_step))) if n > 1 else [0]
        # Siste regulære tikk droppes hvis den ligger for nær selve sluttpunktet.
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
    return f"Dagens laveste pris er {_fmt_kr(current)}, {pct_txt} % {dir_txt} {n_days}-dagers medianen på {_fmt_kr(median)}."


def _price_intelligence_status_text(status: dict, n_days: int, period_label: str, median: float | None = None) -> tuple[str, str, str]:
    """(css-modifikator, kort tittel, forklarende setning) for statuskortet
    -- ALLTID fra de deterministiske reglene i _price_intelligence_status(),
    ALDRI en generert kommentar (Kai, regel 5: "Do not use an LLM to invent
    price commentary").

    "historical_high" sin tittel er bevisst "Høyt prisnivå", IKKE "Høyeste
    registrerte pris" (logikk-/semantikk-runden 2026-09-29, Kai: "these
    are NOT the same thing" -- historisk-serie-maks og dagens
    butikk-maks/-median i "Prisforskjell mellom butikkene"-kortet må ha
    synlig ulike etiketter, ellers leses de lett som samme tall). Siden
    statusen nå også krever et MATERIELT spenn (se
    _price_intelligence_status()), utløses denne kun når dagens pris
    faktisk er nær en reell topp, ikke ved en 1 kr-svingning som
    tilfeldigvis traff periodens tak. "historical_low" beholder sin
    faktiske, ikke-selgende tittel "Laveste registrerte pris" (Kai:
    unngå promoterende språk som "Fantastisk pris" -- et rent faktautsagn
    er riktig her uansett)."""
    kind = status["kind"]
    current = status["current"]
    if kind == "flat":
        return "flat", "Stabil pris", f"Laveste produktpris har vært {_fmt_kr(current)} i {status['flat_days']} dager."
    vs_median = _vs_median_text(current, median, n_days) if median is not None else None
    if kind == "historical_low":
        return "low", "Laveste registrerte pris", vs_median or f"Dagens pris er den laveste vi har registrert i denne perioden ({period_label})."
    if kind == "historical_high":
        return "high", "Høyt prisnivå", vs_median or f"Dagens pris er nær det høyeste nivået vi har registrert i denne perioden ({period_label})."
    if kind == "down":
        return "down", "Pris ned", f"Laveste produktpris har falt {abs(status['pct_change']):.0f} % de siste {n_days} dagene."
    if kind == "up":
        return "up", "Pris opp", f"Laveste produktpris er {abs(status['pct_change']):.0f} % høyere enn for {n_days} dager siden."
    return "stable", "Stabil pris", f"Laveste produktpris har endret seg lite de siste {n_days} dagene."


def _price_intelligence_summary_text(product_name: str, metrics: dict, period_label: str, spread: dict | None = None) -> str:
    """"Kort oppsummert" -- fra strukturerte, deterministiske maler (Kai,
    regel 20: "generated from structured deterministic templates, not
    free-form AI"), aldri fritekst fra en språkmodell. `spread` (fra
    _price_intelligence_merchant_spread(), CURRENT tilbud, IKKE historikk)
    er valgfri og legger til én ekstra, faktabasert setning når den
    finnes -- matcher regel 20 sitt eget eksempel ("Det er 32 %
    prisforskjell mellom billigste og dyreste butikk akkurat nå")."""
    status = metrics["status"]
    kind, n_days = status["kind"], metrics["n_days"]
    name = escape(product_name)
    spread_sentence = f" Det er {spread['spread_pct']} % prisforskjell mellom billigste og dyreste butikk akkurat nå." if spread else ""
    if kind == "flat":
        flat_days = status["flat_days"]
        # VIKTIG: bruk flat_days (den faktiske, sammenhengende
        # uendret-strekken), IKKE hele periodens n_days -- prisen kan ha
        # vært flat de siste 7 dagene inni et 30-dagers vindu der den
        # FAKTISK endret seg tidligere i perioden. Å påstå at dagens pris
        # er "både laveste og høyeste" for HELE perioden i et slikt
        # tilfelle ville vært en usann påstand (regel 2/3: aldri finn på/
        # feilrepresenter tall) -- selv om flat_days>=7 riktig utløser
        # "flat"-status, må selve SETNINGEN referere til det som faktisk
        # er flatt, ikke til en periode den ikke gjelder for.
        if flat_days >= n_days:
            return f"Prisen på {name} har vært stabil i {period_label.lower()}, med {_fmt_kr(status['current'])} som både laveste og høyeste registrerte pris i perioden.{spread_sentence}"
        return f"Prisen på {name} har vært uendret på {_fmt_kr(status['current'])} de siste {flat_days} dagene.{spread_sentence}"
    if kind in ("down", "up"):
        retning = "falt" if kind == "down" else "steget"
        lavere_hoyere = "lavere" if kind == "down" else "høyere"
        return (f"Laveste registrerte pris har {retning} fra {_fmt_kr(status['period_start'])} til {_fmt_kr(status['current'])} de siste {n_days} dagene. "
                f"Dagens laveste pris er {abs(status['pct_change']):.0f} % {lavere_hoyere} enn ved starten av perioden.{spread_sentence}")
    return f"Laveste produktpris for {name} har ligget mellom {_fmt_kr(metrics['low'])} og {_fmt_kr(metrics['high'])} de siste {n_days} dagene.{spread_sentence}"


def _price_intelligence_merchant_spread(offers: list[dict]) -> dict | None:
    """"Prisforskjell mellom butikkene" (regel 10-12) -- CURRENT, levende
    tilbud (IKKE historikk), samme sammenligningsgrunnlag som Winner Card
    sin Savings Signal (_savings_eligible_offers(), qty=1, uten frakt --
    sidens standard prisbasis). Krever >=2 gyldige tilbud, ellers None (en
    "spredning" mellom kun ett tilbud er meningsløs). spread_pct regnes
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
    product() som avgjør "laveste pris" på selve siden den dagen) --
    en eventuell uavgjort mellom to butikker med eksakt lik pris er
    derfor ALLEREDE avgjort deterministisk av reconcile_product() sin
    egen tie-break-nøkkel (_tie_break_key()/AFFILIATE_TIE_PRIORITY) i
    det øyeblikket dataen ble lagret. Denne modulen har ingen tilgang
    til de andre tilbudene for en historisk dag (kun vinneren ble
    lagret), og kan derfor verken gjenoppdage eller telle en historisk
    uavgjort-situasjon i etterkant -- den regner ganske enkelt den
    lagrede, allerede-tie-brutte vinneren for hver dag.

    `all_retailers` (visuelt reset-brief, 2026-09-29): butikker som selger
    produktet akkurat nå (fra CURRENT `offers`) men som ALDRI har vunnet
    laveste pris i historikken får en synlig "0 dager"-rad i stedet for å
    være usynlige -- viser at de faktisk er sammenlignet, ikke bare
    fraværende. Kun ekte, faktisk-selgende butikker legges til på denne
    måten, aldri en oppdiktet liste."""
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
    """"N butikker har vært prisvinner siste {vindu} dager" -- egen-data-
    stripen (v2-redesign, regel 16). Bevisst et ANNET, kortere vindu enn
    "Prisvinner over tid"-kortet (som alltid bruker HELE historikken) --
    et eget, kort vindu er mer relevant som en "hvor konkurranseutsatt er
    dette produktet nylig"-indikator. Vinduet er `min(window_days,
    len(history))`, ALDRI en påstått lengde vi ikke faktisk har data for
    -- samme "ikke lov til å hevde en periode vi ikke dekker"-prinsipp
    som resten av modulen (se `_price_intelligence_eligible_periods()`).
    Ingen `all_retailers` her (i motsetning til `_price_intelligence_
    merchant_winners()` sin bruk andre steder) -- denne tellingen skal
    KUN telle butikker som faktisk har vunnet minst én dag i vinduet, en
    0-dagers-butikk ville gitt en misvisende "flere konkurrenter" enn
    det som faktisk er observert der."""
    window = history[-window_days:] if len(history) >= window_days else history
    w = _price_intelligence_merchant_winners(window)
    if not w:
        return None
    return {"n_stores": len(w["ranked"]), "n_days": len(window)}


def _price_intelligence_quantity_table(offers: list[dict], unit_singular: str, unit_plural: str, qty_choices: tuple[int, ...] = (1, 2, 4, 6, 8, 10)) -> dict | None:
    """"Kjøper du flere esker?" (visuelt reset-brief punkt 9, 2026-09-29) --
    samme sammenligningsgrunnlag som resten av modulen: CURRENT tilbud
    (ikke historikk), uten frakt, kun in_stock/ikke-utgåtte (se
    _savings_eligible_offers()) -- samme prisbasis som "Prisforskjell
    mellom butikkene", nettopp derfor sammenlignbare. For hvert antall:
    billigste butikk sin produktpris × antall, ALDRI utledet/gjettet, kun
    regnet direkte fra levende tilbud (samme prinsipp som qty-multi-raden
    i render_winner_widget(), men uten frakt siden resten av denne
    modulen konsekvent er uten-frakt-basert). Krever >=2 gyldige tilbud,
    samme terskel som resten av modulen.

    Skjules HELT (returnerer None) når vinnerbutikken er den samme på
    tvers av ALLE viste antall (logikk-/semantikk-runden 2026-09-29,
    Kai: "Do not show the Quantity Intelligence card merely because
    quantity calculations exist... Intelligence should reveal
    something, not merely repeat arithmetic"). Uten volumrabatter i
    datamodellen (hver butikks pris er lineær -- pris × antall) er
    vinnerbytte den ENESTE reelle intelligensen tabellen kan avdekke;
    når ingen bytte skjer er raden bare gangetabellen for den ene
    billigste butikken, og Kai ba eksplisitt om å heller skjule kortet
    enn å fylle det med generisk "billigste butikk kan endre seg"-tekst
    når vi konkret VET at den ikke gjør det i dette tilfellet."""
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


def render_price_intelligence(history: list[dict], product_name: str, unit_singular: str = "eske", unit_plural: str = "esker", offers: list[dict] | None = None) -> str:
    """Price Intelligence-modulen (Product Gold Standard v1, 2026-09-27).
    Erstatter den gamle, enkle "Prisutvikling"-grafen på produktsider
    (kontaktlinser, linsevæske/øyedråper/Tilbehør og private label).

    VISUELT RESET (2026-09-29, Kai, med godkjent mockup-bilde): data-
    modellen/beregningene er UENDRET (Kai, regel 13: "Preserve everything
    functional") -- kun presentasjonen bygget om, fra en "intern
    analytics-dashboard"-følelse (mange tunge rektangulære blokker,
    oversized chart, frikoblet header, oppsummering FØR intelligensen
    den oppsummerer, for mye blå/grå flate) til én sammenhengende,
    hvit-dominert flate som følger mockupen tett:
      - Metrikk-stripen (5 kompakte felt: nå/laveste/høyeste/median/status)
        ligger nå FØR periodevelgeren, ikke lenger i samme blokk som grafen.
      - Selve grafen står alene mellom periodevelger og intelligens-raden.
      - "Kort oppsummert" er flyttet til BUNNEN, som en smal, lyseblå
        stripe -- konklusjonen kommer etter dataene, ikke før dem.
      - Ny tredje intelligens-kolonne: "Kjøper du flere esker?"
        (_price_intelligence_quantity_table()), samme CURRENT-tilbud-
        grunnlag som "Prisforskjell mellom butikkene".
      - "Prisvinner over tid" viser nå også butikker som ALDRI har vunnet
        (0 dager) når de fortsatt selger produktet i dag, for kontekst
        (se _price_intelligence_merchant_winners() sin all_retailers).

    Metrikk-stripen, grafen OG oppsummeringen er alle tre fortsatt
    periode-avhengige (bytter sammen når en periode-fane klikkes), men
    ligger nå i tre separate DOM-grupper (`.price-intel-metrics-strip`/
    `.price-intel-chart-panel`/`.price-intel-summary`, alle med samme
    `data-period`-attributt) i stedet for én delt blokk -- nettopp for å
    kunne plassere dem tre ulike steder visuelt (topp/midt/bunn) mens de
    fortsatt oppdateres samlet. JS-en toggler nå ALLE elementer med et
    `data-period`-attributt i ett steg (inkludert selve fane-knappene, som
    også har attributtet) i stedet for tre separate spørringer.

    LOGIKK-/SEMANTIKK-RUNDE (2026-09-29, Kai, "not another design brief
    ... primarily about making sure the intelligence is mathematically
    correct, semantically precise, not visually misleading, genuinely
    useful, deterministic, adaptive"): ren logikk-/tekst-polish, IKKE en
    ny visuell runde. Fem reelle funn rettet:
      1. `_price_intelligence_status()` klassifiserte tidligere
         historical_low/high kun på "current == period_low/high", uansett
         hvor LITE spennet i perioden var -- et produkt som svingte
         449<->454 kr (~1,1 %) ble flagget rødt "høyeste registrerte
         pris" bare fordi dagens pris traff periodens (ubetydelige) tak.
         Krever nå et MATERIELT spenn (range_pct >=
         STATUS_STABLE_TOLERANCE_PCT) før historical_low/high i det hele
         tatt kan utløses -- ellers faller den naturlig gjennom til
         "stable" via samme toleranse som resten av statuslogikken.
      2. Historikk-metrikkenes "Høyeste registrerte pris" er nå "Høyeste
         prisnivå" (+ tooltip), og status-tittelen for historical_high er
         "Høyt prisnivå" -- unngår at disse forveksles med "Prisforskjell
         mellom butikkene" sin egen, helt ANNERLEDES "høyeste pris"
         (dagens butikk-maks, ikke historisk serie-maks). Den kortets rader
         omdøpt til "Laveste/Høyeste BUTIKKpris" av samme grunn.
      3. Laveste/høyeste-dato viser nå "Først registrert {dato}" i stedet
         for en bar dato -- unngår at en verdi som faktisk gjaldt i flere
         dager leses som om den kun eksisterte akkurat den ene datoen
         (Python sin min()/max() plukker allerede FØRSTE forekomst
         kronologisk, kun teksten var upresis).
      4. `_render_price_intelligence_chart()` sitt Y-akse-spenn hadde
         ikke noe gulv -- et lite observert spenn (449-454 kr) ble padded
         med kun 10 % av SEG SELV, som fylte hele grafhøyden med en
         ubetydelig bevegelse. Ny `_price_intel_chart_domain()` sikrer et
         visningsspenn på minst `_CHART_MIN_ABS_RANGE_NOK` kr eller
         `_CHART_MIN_PCT_RANGE` av medianprisen -- ekte, større spenn
         klippes aldri, gulvet er kun en nedre grense.
      5. "Kjøper du flere esker?" skjules nå helt når vinnerbutikken er
         den samme uansett antall (`_price_intelligence_quantity_table()`
         returnerer None) -- uten volumrabatter i datamodellen er
         vinnerbytte den eneste reelle intelligensen tabellen kan vise;
         ren gangetabell er ikke intelligens. `.price-intel-cards` sin
         desktop-CSS byttet fra fast `repeat(3,...)` til
         `repeat(auto-fit, minmax(220px,1fr))` slik at raden ikke får en
         tom tredje kolonne når kortet er skjult.
    Databehandlingen ellers -- tie-break ved lik butikkpris
    (`_tie_break_key()`/`AFFILIATE_TIE_PRIORITY`, allerede en dokumentert,
    deterministisk prioritetsliste, ALDRI array-/databaserekkefølge), én
    rad per faktisk kalenderdag (`record_price()` overskriver, legger
    aldri til duplikater), og at manglende observasjonsdager aldri telles
    som uendret/null (de er ganske enkelt fraværende fra historikk-listen)
    -- var allerede korrekt og er UENDRET denne runden.

    V2 -- "PREMIUM DATA PUBLICATION"-REDESIGN (2026-09-29, samme dag, Kai,
    godkjent mockup-bilde 58.webp som visuell fasit -- "the attached
    mockup wins" der den avviker fra den skriftlige spec-en, men den
    skriftlige spec-en er fortsatt fasit for datalogikk/eligibility/
    semantikk/tilgjengelighet). Ren presentasjon, INGEN
    beregning/eligibility-regel endret fra runden over. Fem strukturelle
    endringer:
      1. "Pris nå" er nå VISUELT DOMINERENDE (2,1rem, egen stor verdi),
         med de tre historikk-metrikkene ved siden av som en tynn,
         skilt-delt rad (`.price-intel-metrics-row`/`-col`,
         `border-left` som skillelinje) i stedet for like store
         grid-fliser -- "the numbers themselves should become the visual
         design", ikke pakket i grå bokser. Statuspillen er nå en egen,
         atskilt komponent ved siden av (fortsatt tinted -- regel 5: "may
         remain a subtle tinted module because it represents a
         conclusion"), ikke en grid-rute blant rådataene.
      2. Grafen har fått en smal "hylle" på stor desktop
         (`.price-intel-chart-shell{max-width:1100px}`, regel 8) -- IKKE
         en proporsjonal nedskalering av høyden (regel 9), kun bredden
         begrenses og sentreres. En liten, IKKE-INTERAKTIV verktøylinje
         over grafen ("Laveste registrerte produktpris per dag" +
         "Viser laveste registrerte pris per dag") -- bevisst uten
         nedoverpil/dropdown-chevron, siden det ikke finnes noen reell
         alternativ dataserie å velge mellom ennå; å tegne en falsk
         interaktiv kontroll ville vært misvisende UI.
      3. "31 %"-tallet i "Prisforskjell mellom butikkene" har fått en
         egen, fremtredende callout-boks (`.price-intel-spread-callout`,
         regel 12: "make the proprietary spread metric prominent") i
         stedet for en rad blant de andre. 0-dagers-butikker i
         "Prisvinnere over tid" er beholdt synlige (Kai bekreftet
         eksplisitt tidligere samme uke at dette er ønsket -- "viser at
         de faktisk er sammenlignet"), men visuelt dempet
         (`.price-intel-winner-row-zero`, regel 13: "Do not let
         zero-value merchants create visual clutter" -- løst med
         dempning, ikke fjerning, for å ikke motsi den tidligere,
         eksplisitte avgjørelsen).
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
         som det følger den valgte fanen"-prinsipp som resten av siden).
      5. Bevisst IKKE implementert: mockupens "Sist oppdatert: ... kl.
         HH:MM"-klokkeslett. Samme lærdom som allerede dokumentert for
         merke-siden samme dag ("Fase 16... et KLOKKESLETT-basert
         ferskhet-krav ble fjernet tidligere i prosjektet nettopp fordi
         det ble feil hver gang noen leste en statisk side senere enn
         byggetidspunktet") -- `price_history.json` lagrer uansett aldri
         klokkeslett, kun kalenderdato, så et påstått klokkeslett måtte
         vært either oppdiktet eller byggetidspunktet (som blir usant få
         timer senere på en statisk side). Footeren viser i stedet
         `historikkens siste dato` via den samme "sist bekreftet
         {dato}"-konvensjonen resten av siden allerede bruker
         konsekvent. Samme grunn: mockupens "Oppdatert i dag"-merkelapp
         på Kort fortalt-boksen er IKKE implementert -- en relativ "i
         dag"-påstand på en statisk side blir usann i intervallet mellom
         to daglige bygg, akkurat samme feilklasse."""
    if len(history) < 7:
        return ""

    coverage_days = len(history)
    coverage_start = history[0]["date"]
    latest_date = history[-1]["date"]
    periods = _price_intelligence_eligible_periods(coverage_days)
    period_keys = {key for key, _, _ in periods}
    default_key = "30d" if "30d" in period_keys else "all"
    spread = _price_intelligence_merchant_spread(offers) if offers else None
    all_retailers = {o["retailer"] for o in offers} if offers else set()
    qty_table = _price_intelligence_quantity_table(offers, unit_singular, unit_plural) if offers else None
    # Bidireksjonal "bytte"-pil, kun brukt av egen-data-stripen sitt
    # "N ganger har prisvinneren skiftet"-element -- ingen delt konstant
    # finnes fra før som passer semantisk (TROPHY_ICON_SVG er allerede
    # brukt til selve butikknavnet, ikke byttefrekvensen).
    _swap_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h13l-3-3M20 17H7l3 3"/></svg>'
    _chart_toolbar_icon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 21V10M12 21V4M19 21v-7"/></svg>'

    # Ett gjennomløp over PRICE_INTELLIGENCE_PERIODS i FAST rekkefølge (30
    # dager -> 90 dager -> 6 måneder -> 1 år -> All historikk), IKKE
    # kvalifiserte perioder først med deaktiverte tacket på til slutt --
    # sistnevnte ga "All historikk" (alltid kvalifisert, siden den ikke har
    # noen dagsgrense) rett etter "30 dager" i stedet for sist, i strid med
    # mockupens eksplisitte rekkefølge (visuelt reset-brief punkt 4).
    # Oppdaget 2026-09-29 ved å faktisk sjekke et produkt med færre enn 90
    # dagers historikk i browser-panelet, ikke antatt.
    tabs, primary_strips, chart_panels, stat_strips, summary_strips, history_table_rows, winner_panels = [], [], [], [], [], [], []
    n_enabled = 0
    for key, label, days in PRICE_INTELLIGENCE_PERIODS:
        if key not in period_keys:
            tabs.append(f'<button type="button" class="price-intel-period-tab" disabled title="Ikke nok historikk ennå">{escape(label)}</button>')
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

        primary_strips.append(f'''<div class="price-intel-primary{active_cls}" data-period="{key}">
    <div class="price-intel-metrics-row">
      <div class="price-intel-metric-col price-intel-metric-current">
        <span class="price-intel-value-lg">{_fmt_kr(metrics["current"])}</span>
        <span class="price-intel-metric-label">Pris nå</span>
        <span class="price-intel-current-dot"><i></i>Laveste pris akkurat nå</span>
      </div>
      <div class="price-intel-metric-col">
        <span class="price-intel-value">{_fmt_kr(metrics["low"])}</span>
        <span class="price-intel-metric-label">Laveste pris<br>{period_phrase}</span>
        <span class="price-intel-metric-sublabel">Først registrert {_format_no_date(metrics["low_date"])}</span>
      </div>
      <div class="price-intel-metric-col" title="Høyeste registrerte verdi for den laveste tilgjengelige produktprisen i valgt periode.">
        <span class="price-intel-value">{_fmt_kr(metrics["high"])}</span>
        <span class="price-intel-metric-label">Høyeste prisnivå<br>{period_phrase} <span class="price-intel-metric-info" aria-hidden="true">&#9432;</span></span>
        <span class="price-intel-metric-desc">Høyeste registrerte verdi for den laveste tilgjengelige produktprisen i perioden.</span>
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
      <div class="price-intel-chart-toolbar">
        <span>Laveste registrerte produktpris per dag</span>
        <span class="price-intel-chart-toolbar-badge">{_chart_toolbar_icon}Viser laveste registrerte pris per dag</span>
      </div>
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
                stat_parts.append((TROPHY_ICON_SVG, f'{n} {"butikk" if n == 1 else "butikker"}', f'har vært prisvinner {period_phrase}'))
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

        # Prisvinnere følger valgt periode. Dagens butikkspredning er
        # fortsatt et øyeblikksbilde og står fast, mens historisk
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
                f'<p class="price-intel-zero-note">{zero_winner_count} {"annen butikk" if zero_winner_count == 1 else "andre butikker"} er også sammenlignet, men har ikke vært billigst i perioden.</p>'
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
        # Specialist lese periodedata uten å måtte tolke SVG eller klikke
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
    # periode-avhengig, vises derfor KUN én gang. Skjules helt hvis <2
    # gyldige tilbud (samme grunnlag som Savings Signal). Radetikettene er
    # bevisst "Laveste/Høyeste BUTIKKpris" (ikke bare "Laveste/Høyeste
    # pris") -- logikk-/semantikk-runden 2026-09-29, Kai: dette er
    # DAGENS spredning mellom butikker, et helt annet tall enn
    # historikk-metrikkenes "Laveste registrerte pris"/"Høyeste
    # prisnivå" over. Uten den presiseringen kan f.eks. 454 kr (dagens
    # laveste butikkpris) og 666 kr (dagens høyeste butikkpris) lett
    # forveksles med historiske min/maks-tall lenger opp i modulen.
    # "31 %"-tallet er nå en egen, fremtredende callout-boks (v2-redesign
    # regel 12), ikke bare en rad blant de andre.
    spread_card = ""
    if spread:
        spread_card = f'''<div class="price-intel-card">
    <div class="price-intel-card-head"><h3 class="price-intel-card-h-spread"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 21V10M12 21V4M19 21v-7"/></svg>Prisforskjell mellom butikkene</h3></div>
    <div class="price-intel-card-row"><span>Laveste butikkpris</span><strong>{_fmt_kr(spread["lowest"])}</strong></div>
    <div class="price-intel-card-row"><span>Medianpris</span><strong>{_fmt_kr(spread["median"])}</strong></div>
    <div class="price-intel-card-row"><span>Høyeste butikkpris</span><strong>{_fmt_kr(spread["highest"])}</strong></div>
    <div class="price-intel-spread-callout"><strong>{spread["spread_pct"]} %</strong><span>Forskjell mellom laveste og høyeste butikkpris</span></div>
    <p class="price-intel-card-note"><span aria-hidden="true">&#9432;</span> Basert på priser uten frakt, for 1 {escape(unit_singular)}.</p>
  </div>'''

    # "Kjøper du flere esker?" (visuelt reset-brief punkt 9, betinget
    # skjult av _price_intelligence_quantity_table() selv -- se dens
    # docstring for begrunnelsen) -- samme CURRENT-tilbud-grunnlag som
    # Prisforskjell-kortet, vises derfor også KUN én gang. Siden kortet
    # nå KUN rendres når vinnerbutikken faktisk endrer seg et sted i
    # tabellen, sier notatet det konkrete antallet det skjer ved i
    # stedet for den tidligere generiske "kan endre seg"-hedgingen
    # (logikk-/semantikk-runden 2026-09-29, Kai: "do not use generic
    # text... when we know it does not [change]" -- her vet vi tvert
    # imot at den GJØR det, så teksten sier nøyaktig det). Kolonnen
    # "Laveste pris" er omdøpt til "Pris totalt" (v2-redesign) -- den
    # viser produktpris × antall, altså en TOTAL, ikke "laveste" i seg
    # selv (regel 19: "Every proprietary metric should carry: metric +
    # value + period/context").
    qty_card = ""
    if qty_table:
        rows_html = "".join(
            f'<tr><td>{r["qty"]} {escape(unit_singular) if r["qty"] == 1 else escape(unit_plural)}</td><td>{_fmt_kr(r["total"])}</td><td>{escape(r["store"])}</td></tr>'
            for r in qty_table["rows"]
        )
        qty_card = f'''<div class="price-intel-card">
    <div class="price-intel-card-head"><h3 class="price-intel-card-h-qty">{BOX_ICON_SVG}Kjøper du flere {escape(unit_plural)}?</h3></div>
    <table class="price-intel-qty-table">
      <thead><tr><th>Antall</th><th>Pris totalt</th><th>Butikk</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p class="price-intel-qty-note"><span aria-hidden="true">&#9432;</span> Prisene er uten frakt. Billigste butikk endrer seg ved {qty_table["change_qty"]} {escape(unit_plural)}.</p>
  </div>'''

    winner_panels_html = "".join(winner_panels)
    cards_html = f'<div class="price-intel-cards">{spread_card}{winner_panels_html}{qty_card}</div>' if (spread_card or winner_panels_html or qty_card) else ""

    return f'''<div class="price-intel">
  <div class="price-intel-head">
    <div class="price-intel-head-text">
      <p class="price-intel-eyebrow">Prisintelligens</p>
      <h2>Prisutvikling</h2>
      <p>Vi har fulgt laveste produktpris hos butikkene siden {_format_no_date(coverage_start)}, slik at du kan se hvordan prisen har endret seg over tid.</p>
    </div>
    <div class="price-intel-coverage">{CALENDAR_ICON_SVG}<span>Vi har fulgt prisen siden<br><strong>{_format_no_date(coverage_start)}</strong><span class="price-intel-coverage-days">{coverage_days} dager med data</span></span></div>
  </div>
  {"".join(primary_strips)}
  <div class="price-intel-period-tabs" role="tablist">{"".join(tabs)}</div>
  {"".join(chart_panels)}
  {cards_html}
  {"".join(summary_strips)}
  <section class="price-intel-history-data" aria-labelledby="price-intel-history-title">
    <div class="price-intel-section-head">
      <div>
        <p class="price-intel-section-kicker">Historiske nøkkeltall</p>
        <h3 id="price-intel-history-title">Prishistorikk i tall</h3>
        <p>Samme prisdata som i grafen, publisert som lesbare nøkkeltall for periodene vi har nok historikk til å beregne.</p>
      </div>
    </div>
    <details class="price-intel-history-details" open>
      <summary>Se historiske nøkkeltall</summary>
      <div class="price-intel-history-table-wrap">
        <table class="price-intel-history-table">
          <thead><tr><th>Periode</th><th>Laveste</th><th>Høyeste prisnivå</th><th>Median</th><th>Prisspenn</th><th>Prisendringer</th><th>Vinnerbytter</th><th>Butikker billigst</th></tr></thead>
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
</div>'''


def _family_price_insight_data(rows: list[dict], price_history: dict) -> dict[int, dict]:
    """Slår sammen prishistorikken for ALLE medlemmer i familien med SAMME
    pakningsstørrelse til én gjennomsnittlig serie-pris per dag -- en type
    innsikt ingen enkelt produktside kan gi alene (snittet av flere faktiske
    produkter, ikke én linses pris). Kai sitt eksplisitte ønske 2026-09-27:
    "prisinnsikt skal gjelde gjennomsnitt for serien, ikke 1 produkt".
    Grupperes per pack_size siden ulike pakningsstørrelser ikke er
    sammenlignbare i kroner (232 kr for 30 stk vs. 599 kr for 90 stk er ikke
    et "snitt" som gir mening). Kun dager der MINST ÉTT medlem faktisk har en
    registrert pris tas med -- aldri en oppdiktet verdi for en dag ingen av
    dem ble sjekket, og antall bidragsytende produkter kan derfor variere
    litt dag for dag etter hvert som nye produkter får egen prishistorikk."""
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
    hvordan tallene regnes ut. Én fane per pakningsstørrelse familien faktisk
    har (kun 30-pack her: én fane, ingen faner å bytte mellom -- unødvendig
    UI for noe som uansett ikke kan velges bort). Begge/alle paneler ligger
    FERDIGBYGGET i DOM-en samtidig (ren CSS/JS-visning, ingen klientside-
    utregning) -- bytte av fane er derfor øyeblikkelig og fungerer uten JS
    også (viser bare det første panelet i så fall). Samme 7-dagers terskel
    som selve grafen (_render_price_history_chart) -- en pakningsstørrelse
    med for lite historikk ennå utelates helt i stedet for å vise et
    upålitelig snitt. scope_label: gjenbrukt av render_brand_page() 2026-09-27
    for et merke-nivå snitt på tvers av HELE merket, ikke bare én serie --
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
        trend_arrow = "↓" if pct < 0 else ("↑" if pct > 0 else "→")
        chart_html = _render_price_history_chart(history, show_heading=False, gradient_id=f"priceHistoryFade-{pack_size}")
        active = " active" if i == 0 else ""
        tabs.append(f'<button type="button" class="insight-tab{active}" data-pack="{pack_size}">{pack_size} linser</button>')
        panels.append(f'''<div class="price-insight-panel{active}" data-pack="{pack_size}">
    <div class="price-insight-now">
      <div class="price-insight-current">{_fmt_kr(current)}</div>
      <div class="price-insight-label">Snitt laveste pris nå &middot; {data["n_products"]} varianter {scope_label}</div>
      <div class="price-insight-trend {trend_class}"><span aria-hidden="true">{trend_arrow}</span> {trend_sign}{pct} % <span class="price-insight-trend-note">vs. {n} dagers snitt</span></div>
      <div class="price-insight-tiles">
        <div class="price-insight-tile"><strong>{_fmt_kr(lo)}</strong><span>{n} dagers laveste</span></div>
        <div class="price-insight-tile"><strong>{_fmt_kr(avg)}</strong><span>{n} dagers snitt</span></div>
        <div class="price-insight-tile"><strong>{_fmt_kr(hi)}</strong><span>{n} dagers høyeste</span></div>
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
    <details>/<summary> (samme Google-verifiserte mønster som
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
    Finnes også i <strong>{sibling_pack_size}-pakning</strong> — {per_lens_str} ({comparison})
  </div>
  <div class="pack-size-callout-arrow">→</div>
</a>""")
        # En rad per andre pakningsstørrelse, stigende. Med ett søsken er
        # markup identisk med før.
        pack_size_callout = "\n".join(callout_rows)

    # Alternativ stavemåte (kun familier med eksplisitt "alt_name" i
    # product_families.json, i dag bare Dailies Total1): én nøytral setning i
    # "Om"-teksten, aldri i tittel, H1, URL, canonical eller schema.
    alt_name_html = ""
    alt_name = (family or {}).get("alt_name")
    if alt_name and family["name"] in product["name"]:
        base_name = re.sub(r"\s+\d+-pack$", "", product["name"])
        alt_name_html = f"<p>Produktnavnet kan også skrives {escape(base_name.replace(family['name'], alt_name, 1))}.</p>"

    family_callout = ""
    if family:
        family_callout = f"""<a class="pack-size-callout" href="/serie/{escape(family["slug"])}/">
  <div class="pack-size-callout-text">
    Se hele <strong>{escape(family["name"])}</strong>-serien — sammenlign sfærisk, torisk og andre varianter
  </div>
  <div class="pack-size-callout-arrow">→</div>
</a>"""

    thumb = _img_tag(image_url, product["name"], loading="eager") if image_url \
        else escape(product["brand_label"][:2].upper())

    ship_chip_html = _ship_chip_boxed_html("ship-chip") if offers else ""
    offers_block, ex_best = render_price_list(offers, product["name"], product["id"], clickouts, show_ship_chip=False, qty_unit_label="1 eske", collapse_after=10, product_ship_chip_html=ship_chip_html)

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(product["name"])}</strong> hos norske nettbutikker. Fra <strong>{_fmt_kr(ex_best["price_nok"])}</strong> hos {escape(ex_best["retailer"])} (ekskl. frakt). Kontaktlinser.no er en uavhengig sammenligningstjeneste - slå på «Pris inkludert frakt» under for å se totalprisen med frakt. Priser sist bekreftet {_verified_tag(_newest_checked(offers))}.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne linsen akkurat nå. Prisene oppdateres daglig.</p>
</section>"""

    winner_html, qty_html, qty_multi_html = render_winner_widget(ex_best, offers, product["name"], product_id=product["id"], clickouts=clickouts, qty_multi_inline=False, qty_choices=(1, 2, 4, 6, 8, 10), include_custom_pill=False)
    badges_html = _render_product_badges(product.get("specs", []))
    hero_facts_html = _hero_facts_html(product.get("specs", []), parsed[1] if parsed else None)

    in_stock_offers = [o for o in offers if o["in_stock"]]
    # "price" er produktprisen alene, ikke fraktinkludert totalsum -- ellers
    # ser vi kunstig dyrere ut enn konkurrenter i Googles eget SERP-utdrag,
    # som typisk viser ex-frakt-priser. Selve fraktkostnaden ligger separat i
    # shippingDetails i stedet, slik schema.org faktisk er ment å brukes.
    # Vår EGEN "Lavest pris"-rangering (reconcile()) er upåvirket av dette og
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
    # pris, mens et annet treff for en annen linse fikk Google til å
    # generere en pris-ledet snippet selv (fra ai_summary-avsnittet lenger
    # ned på siden) -- ustabilt, siden det er opp til Google om den
    # omskriver. Gir Google et sterkt, riktig signal direkte i meta-taggen
    # i stedet for å stole på at den finner riktig avsnitt selv.
    #
    # Antall forhandlere (len(product["offers"])) er BEVISST fjernet fra
    # denne setningen (2026-09-05, brukeren oppdaget et ekte Google-treff
    # som sa "fra 2 norske nettbutikker" for en produktvariant med lav
    # dekning) -- tallet varierer sterkt per pakningsstørrelse/variant og
    # kan se svakt ut i SERP for et produkt som tilfeldigvis føres av få
    # forhandlere, mens et sitewide-tall ville vært misvisende for et
    # produkt som ikke føres av alle. Selve verdien i setningen (pris +
    # hvilken butikk) krever ikke tallet i det hele tatt.
    meta_description = (
        f'Vi sammenligner priser på {product["name"]} hos norske nettbutikker. '
        f'Laveste pris akkurat nå er {_fmt_kr(ex_best["price_nok"])} hos {ex_best["retailer"]}.'
    ) if ex_best else long_description[:155]

    manufacturer_slug = BRAND_TO_MANUFACTURER.get(product["brand_slug"])
    manufacturer_link_html = (
        f'<p style="margin-top:8px;"><a href="/produsent/{manufacturer_slug}/" style="font-size:0.9rem;color:var(--muted);">'
        f'Produsert av {escape(MANUFACTURERS[manufacturer_slug]["name"])} →</a></p>'
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

    # dateModified = ferskeste checked_at blant tilbudene som faktisk er på
    # lager -- et konkret, sant "sist bekreftet"-tidspunkt, ikke en gjettet
    # eller statisk dato. Freshness-signal for AI-siteringstillit.
    date_modified = max((o["checked_at"] for o in in_stock_offers), default=None)
    product_href = f'{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/'
    # BreadcrumbList manglet her (fantes allerede på kategori-/merke-/
    # produsent-sider, men ikke på selve produktsiden -- funnet 2026-09-05;
    # samme mangel ble senere samme dag funnet på private label-sidene også,
    # se render_private_label_page). Speiler nøyaktig den synlige
    # brødsmulen under (Hjem > kategori > merke > produktnavn).
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
        # Ekte <table>-markup (ikke div-grid) -- lettere for AI-crawlere å
        # trekke ut spesifikasjonene som strukturerte data, se GEO-revisjonen.
        specs_html = f"""<div class="specs">
    <h2>Spesifikasjoner</h2>
    <table class="specs-table"><tbody>{rows}</tbody></table>
    <p class="specs-note">Veiledende tall, satt sammen fra forhandlernes egne spesifikasjoner og produsentens produktinformasjon. Bekreft alltid mot din synsresept og pakningsvedlegget før kjøp.</p>
  </div>"""
    specs_html += manufacturer_link_html

    price_history_html = render_price_intelligence(price_history or [], product["name"], offers=offers)

    aliases_html = ""
    if aliases:
        alias_rows = "\n    ".join(
            f'<li><a href="/private-label/{escape(a["slug"])}/">{escape(a["name"])}</a> hos {escape(a["chain"])}</li>'
            for a in aliases
        )
        n = len(aliases)
        chains_word = "kjede" if n == 1 else "kjeder"
        aliases_html = f"""<div class="aliases-note">
    <strong>Selges også under andre navn:</strong> {escape(product["name"])} pakkes om og selges under eget varenavn hos {n} optiker{chains_word}:
    <ul>
    {alias_rows}
    </ul>
    <a href="/private-label/">Om optikerkjedenes egne merker →</a>
  </div>"""

    # Dynamisk FAQ bygget fra SAMME beregnede data som resten av siden
    # (best/in_stock_offers/parsed) -- aldri hardkodet forhandler/pris, og
    # aldri flere spørsmål enn det finnes et pålitelig svar på (f.eks.
    # "hvor lenge varer den" krever KJENT pakningsstørrelse OG at det
    # faktisk er en dagslinse -- ellers utelates spørsmålet helt i stedet
    # for å gjette).
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
                f'{best["retailer"]} har lavest pris, både uten og med frakt: {_fmt_kr(best["price_nok"])} uten frakt '
                f'({_fmt_kr(best["total"])} inkludert frakt).'
            )
        product_faq.append({"question": f'Hvor er {product["name"]} billigst?', "answer": billigst_svar})

        laveste_produktpris = min(o["price_nok"] for o in in_stock_offers)
        product_faq.append({
            "question": f'Hva koster {product["name"]}?',
            "answer": f'Laveste produktpris på {product["name"]} er {_fmt_kr(laveste_produktpris)} uten frakt akkurat nå. '
                      f'Totalprisen avhenger av hvilken butikk du velger og fraktkostnaden der.',
        })

    if parsed:
        _, pack_size = parsed
        product_faq.append({
            "question": f'Hvor mange linser er det i {product["name"]}?',
            "answer": f'Én pakke inneholder {pack_size} linser.',
        })
        if _is_daily_lens(product):
            days_two_eyes = pack_size // 2
            product_faq.append({
                "question": f'Hvor lenge varer {product["name"]}?',
                "answer": f'Til ett øye varer pakningen i {pack_size} dager (én linse per dag). Bruker du linser med samme '
                          f'styrke på begge øyne fra samme pakning, varer den {days_two_eyes} dager. Har du ulik styrke på '
                          f'hvert øye, trenger du vanligvis en egen pakning per øye.',
            })

    product_faq.append({
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk daglig. Vi viser butikkens produktpris "
                  "uten frakt og beregner totalpris basert på frakt og antallet esker du velger.",
    })

    product_faq_html, product_faq_schema = _render_faq_accordion_block(product_faq, f'Vanlige spørsmål om {product["name"]}')

    # "Relatert til X" -- kun ekte, entydige sider (søsken-pakninger, merke,
    # kategori, produsent), aldri en generisk lenkevegg av urelaterte merker
    # (se V1-spesifikasjonens Section 11/37 -- doorway-lenker er bevisst unngått).
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
    # ekte innhold som før, bare gruppert bak <details>-accordions i stedet
    # for alltid synlig -- se _kz_accordion()-docstringen. Ingen ny data,
    # ingen fjernet informasjon, kun omorganisert under "kunnskaps-bruddet".
    kz_specs_html = _kz_accordion("Produktspesifikasjoner", specs_html)
    kz_faq_html = _kz_accordion(f'Vanlige spørsmål om {product["name"]}', product_faq_html)
    kz_sources_html = _kz_accordion("Kilder og dokumentasjon", methodology_html + related_html)

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} » Sammenlign og få billigste pris</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/">
{_og_meta(f'{product["name"]} » Sammenlign og få billigste pris', meta_description, f'{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/', image_url)}
{FONT_LINKS}
{schema_json_html}
{product_faq_schema}
<style>{SHARED_STYLE}
.hero-card {{ background: white; border: 1px solid var(--border); border-radius: 20px; padding: 20px; margin-bottom: 20px; }}
.hero-card .hero-copy h1 {{ font-size: 1.6rem; }}
.hero-subtitle {{ margin: 2px 0 0; font-size: 0.92rem; color: var(--muted); font-weight: 500; }}
/* "Pris ved flere esker" står nå som et eget, frittstående element under
   prislista i stedet for inni .qty-box (Kai, 2026-09-27: "Teksten Pris
   ved flere esker, flyttes også ned under priser") -- delt .qty-multi-CSS
   forutsetter fortsatt at den er siste barn INNI en hvit .qty-box-kortboks
   (fortsatt sant på linsevæske-/private label-sidene, urørt der), så den
   får en egen kort-innpakning KUN her via >-selektoren (direkte barn av
   .wrap-product treffer bare denne siden sin plassering). */
.wrap-product > .qty-multi {{ background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }}
.hero-main {{ display: flex; flex-direction: column; gap: 16px; }}
/* Product Mobile Gold Standard v1 (2026-09-27): produktbilde (~2/3) og
   Winner Card (~1/3) side ved side på mobil -- bildet skal klart være
   hovedpersonen visuelt, IKKE to like kolonner. .hero-media-row er en ren
   mobil-gruppering; på >=860px blir den display:contents slik at bildet
   og vinnerkortet igjen er DIREKTE grid-barn av .hero-main og treffes av
   akkurat samme grid-column/-row-regler som før (uendret desktop-layout,
   se Kai 2026-09-27: "du gjør først mobil produktsiden ferdig nå,
   korrekt? ikke desktop?"). */
/* align-items: flex-start (IKKE stretch) -- med stretch presset bildet seg
   til vinnerkortets (tallere) naturlige høyde i stedet for å faktisk følge
   sin egen aspect-ratio, siden stretch og aspect-ratio konkurrerer om
   kryss-aksen i en flex-rad. flex-start lar hvert element ha sin egen,
   naturlige høyde -- bildet blir kortere (matcher det faktiske,
   liggende eskebildet), og vinnerkortet trenger ikke lenger strekke seg
   opp til en unødvendig høyde bare fordi det står ved siden av et
   kvadratisk bilde. */
.hero-media-row {{ display: flex; align-items: flex-start; gap: 12px; }}
.hero-media-row .hero-product-image {{ flex: 2 1 0; min-width: 0; margin: 0; }}
.hero-media-row .winner-band {{ flex: 1 1 0; min-width: 0; margin: 0; }}
@media (min-width: 640px) {{ .hero-media-row {{ gap: 16px; }} }}
/* Vinnerkortet i den smale ~1/3-kolonnen: reduser padding/skrift/logo/
   spar-sirkel FØR vi vurderer stacking (Kai sin brief, punkt 25) --
   scoped til (max-width:859px) slik at desktopkortet IKKE berøres (viktig:
   .hero-media-row blir display:contents på >=860px, men selektoren under
   ville uansett fortsatt truffet desktop-kortet via DOM-etterkommerskap
   uten denne media-grensen, siden display:contents ikke fjerner elementet
   fra treet). */
@media (max-width: 859px) {{
  /* Kai, etter første runde: "Laveste Pris mer firkantet" + "veldig mye
     plass rundt selve bilde". Begge kommer av samme rot-årsak -- den delte
     .hero-product-image-regelen (brukt over hele siden der et STORT,
     kvadratisk bilde er riktig) tvang en 1:1-firkant også her, i en langt
     smalere ~2/3-kolonne, og .hero-media-row sin align-items:stretch
     presset i tillegg bildet opp til vinnerkortets (tallere) naturlige
     høyde -- aspect-ratio og stretch konkurrerer om kryss-aksen i en
     flex-rad, og stretch vant. Fikset i to steg: (1) .hero-media-row
     bruker nå align-items:flex-start (se der) slik at bildet faktisk får
     lov til å følge sin egen, kortere aspect-ratio i stedet for å strekkes
     opp, og (2) vinnerkortet komprimert videre her (tettere linjer, ett
     linje-slag i stedet for to for "Laveste pris"/"for 1 eske") for å
     nærme seg Kais egen designspec sitt høyde-mål (140-160px) selv i en
     smalere ~1/3-kolonne enn spec-bildet opprinnelig viste. */
  .hero-media-row .hero-product-image {{ aspect-ratio: 4 / 3; }}
  .hero-media-row .winner-band-cta {{ padding: 10px 8px; gap: 6px; }}
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
  /* white-space:normal (ikke nowrap) -- "Gå til butikk" klippet på de
     aller smaleste skjermene (320px) selv etter gjentatt skrift-
     nedskalering; å presse teksten enda mindre gikk ut over lesbarheten.
     Lar heller CTA-en bryte til to linjer der det trengs enn å vise
     avkuttet tekst. */
  .hero-media-row .winner-btn {{ font-size: 0.68rem; padding: 8px 4px; gap: 3px; margin-top: 2px; white-space: normal; text-align: center; line-height: 1.25; }}
}}
/* Kicker (merke/serie over H1) + kompakt faktarad ("Dagslinse · 30 linser
   · Hilafilcon B · BC 8,6") -- Product Desktop Gold Standard v1,
   2026-09-27, punkt 3+8. Skjult som standard (mobil-Gold-Standard-en
   fjernet bevisst kickeren over H1 tidligere samme dag, se commit
   9657bfb1d -- IKKE gjeninnfør den der), vises kun >=860px der Kai
   bekreftet at det er plass ("Her kan også Soflens eller produsent
   vises, da det er plass til det"). */
.hero-kicker, .hero-facts {{ display: none; }}
/* Product Stage: EKTE tre-kolonners CSS Grid på desktop -- bilde |
   produktidentitet+kontroller | Winner Card, ALLE i samme vertikale
   arbeidsflate. Revidert 2026-09-27, samme dag, etter at Kai konkret
   avviste forrige forsøk (title+fakta over hele bredden, bilde og
   Winner Card som separate "øyer" under): "Han har beholdt strukturen
   fra den gamle heroen og bare restylet elementene... Det er ikke
   designet vårt." Referansen krever bilde+identitet/kontroller+
   Winner Card side om side i ÉN rad -- eksakte kolonneproporsjoner og
   mål-mål (bildehøyde, pillestørrelser, typografi) er Kais egne, ikke
   estimert.

   .qty-box er FORTSATT en egen, separat DOM-node (søsken av .hero-card
   inni .product-stage, se render_product_page()) -- IKKE flyttet i
   treet, av samme grunn som forrige runde: mobil skal forbli 100%
   uendret. I stedet "flates" .hero-card/.hero-main/.hero-media-row ut
   med display:contents på desktop, slik at DERES barn (.hero-copy,
   .hero-product-image, .winner-band) blir direkte grid-barn av
   .product-stage -- sammen med .qty-box, som allerede var en direkte
   .product-stage-barn. display:contents er KUN satt inni denne
   media-queryen, så mobilens DOM-boksmodell er fullstendig upåvirket
   under 860px. */
@media (min-width: 860px) {{
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
  /* Kompakte, faste pillestørrelser (56-64x44-48px) -- IKKE den
     elastiske repeat(6, 1fr)-grid-en fra mobil, som ville strukket
     pillene til å fylle hele den nå mye smalere midtkolonnen. Valgt
     tilstand er blek mint/grønn kant/mørk tekst her, IKKE den blå
     gradienten fra mobil-pillene (Kai, punkt 6: "Remove the bright
     blue gradient selected state on desktop"). Frakt-vippebryteren
     bodde tidligere i denne raden også (`.qty-box-row`) -- flyttet til
     prislisteheaderen på BÅDE mobil og desktop nå (se
     render_price_list()), så raden inneholder kun pillene igjen. */
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
/* wrap-product er delt med linsevæske-/private label-produktsider (som
   fortsatt bruker den gamle, smalere hero-layouten) -- utvider den KUN her,
   siden det er denne nye, bredere hero-en som faktisk trenger albuerommet.
   Kommer etter {{SHARED_STYLE}} i selve <style>-taggen, så denne regelen
   vinner kaskaden uten !important (samme spesifisitet, senere i kilden). */
@media (min-width: 1024px) {{ .wrap-product {{ max-width: 1280px; }} }}
.hero-badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0; }}
.hero-badge {{ display: inline-flex; align-items: center; gap: 6px; background: white; border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px 6px 10px; font-size: 0.8rem; font-weight: 600; color: var(--blue); }}
.hero-badge svg {{ width: 15px; height: 15px; flex-shrink: 0; }}
/* "Kunnskaps-bruddet" (Product Mobile Gold Standard v1, 2026-09-27) --
   den visuelle overgangen mellom kjøpssonen (alt over) og kunnskapssonen
   (alt under): flankerende linjer rundt en liten, diskret etikett. */
.kz-break {{ display: flex; align-items: center; gap: 12px; margin: 36px 0 20px; color: var(--muted); font-size: 0.76rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
.kz-break::before, .kz-break::after {{ content: ""; flex: 1; height: 1px; background: var(--border); }}
.kz {{ display: flex; flex-direction: column; gap: 4px; }}
.kz > h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 4px; }}
.kz-accordion {{ background: white; border: 1px solid var(--border); border-radius: 14px; padding: 4px 18px; margin: 10px 0; }}
.kz-accordion summary {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; list-style: none; padding: 16px 0; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.98rem; color: var(--ink); }}
.kz-accordion summary::-webkit-details-marker {{ display: none; }}
.kz-accordion-chevron {{ flex-shrink: 0; width: 18px; height: 18px; color: var(--muted); transition: transform 0.15s; }}
.kz-accordion[open] .kz-accordion-chevron {{ transform: rotate(180deg); }}
.kz-accordion-body {{ padding-bottom: 16px; }}
.kz-accordion-body .specs, .kz-accordion-body .methodology, .kz-accordion-body .related {{ margin-top: 0; }}
.kz-accordion-body .specs h2, .kz-accordion-body .methodology h2, .kz-accordion-body .related h2 {{ display: none; }}
.kz-accordion-body .faq-section .faq-accordion-item:first-child {{ border-top: none; }}
/* _faq_accordion_item() (per-spørsmål-accordionen inni "Vanlige
   spørsmål"-boksen) er gjenbrukt fra brand-/serie-siden, men reglene som
   faktisk STØRRELSESBEGRENSER den (.faq-chevron m.fl.) lå kun i DE
   funksjonenes egne <style>-blokker -- aldri kopiert hit. Uten dem har
   <svg class="faq-chevron"> ingen bredde/høyde-regel i det hele tatt, og
   rendres i sin fulle, ubegrensede viewBox-størrelse (>100px, oppdaget av
   Kai på en skjermdump). Kopiert inn her, identisk med kildene. */
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
.specs h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 12px; }}
.specs-table {{ width: 100%; background: white; border: 1px solid var(--border); border-radius: 12px; border-collapse: collapse; overflow: hidden; font-size: 0.88rem; }}
.specs-table tr {{ border-bottom: 1px solid var(--border); }}
.specs-table tr:last-child {{ border-bottom: none; }}
.specs-table th, .specs-table td {{ padding: 10px 16px; }}
.spec-label {{ text-align: left; font-weight: 400; color: var(--muted); }}
.spec-value {{ text-align: right; font-family: 'IBM Plex Mono', monospace; }}
.specs-note {{ font-size: 0.76rem; color: var(--muted); margin-top: 10px; line-height: 1.5; }}
.pack-size-callout {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; margin: 16px 0; text-decoration: none; color: inherit; font-size: 0.85rem; }}
.pack-size-callout:hover {{ border-color: var(--blue); }}
.pack-size-callout-arrow {{ color: var(--blue); font-size: 1.1rem; flex-shrink: 0; }}
/* Fyller hele kortbredden helt fra minste mobilskjerm (kvadratisk via
   aspect-ratio) -- tidligere var mobil låst til en fast 200x200px-boks som
   etterlot mye tomt rom i et bredere kort (fant og fikset 2026-08-30, se
   brukerens tilbakemelding om at bildene på mobil produktsider var for
   små). På desktop (>=860px, Product Desktop Gold Standard v1,
   2026-09-27) overstyrer `.hero-main .hero-product-image` denne med en
   egen 4:3-aspect-ratio (se der) -- bildet spenner IKKE lenger to
   grid-rader (den midtre tekstkolonnen som tidligere ga bildet en tekst-
   høyde å matche, er fjernet, se punkt 4 i spec-en). */
.hero-product-image {{ width: 100%; height: auto; aspect-ratio: 1 / 1; margin: 0 auto; border-radius: 18px; background: var(--mist); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; padding: 10px; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 2.4rem; color: var(--blue); }}
.hero-product-image img {{ width: 100%; height: 100%; object-fit: contain; }}
@media (min-width: 640px) {{ .hero-product-image {{ border-radius: 20px; font-size: 2.6rem; }} }}
@media (min-width: 860px) {{ .hero-product-image {{ width: 100%; height: 100%; aspect-ratio: auto; margin: 0; font-size: 3rem; }} }}
/* Fade-masken (radial gradient som lot hvite produktbilder smelte inn i
   siden) er fjernet -- den var designet for å blande hvitt inn i en FARGET
   hero-bakgrunn, men heroen er nå selv hvit (se .hero-card), så masken
   gjorde ingenting nyttig lenger og risikerte i tillegg å dempe kantene på
   bilder som IKKE er helt rene hvite (se SofLens-bildet med grå bakgrunn
   som avslørte den "blob"-formede kanteffekten tidligere i dag). Minimal
   padding (6px, ikke 0) kun for å unngå at bildet klipper helt inntil
   kortkanten -- ellers skal bildet fylle mest mulig av ruta, som ønsket. */
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
    <a href="/">Hjem</a> ›
    <a href="/kontaktlinser/{escape(product["category_slug"])}/">{escape(categories[product["category_slug"]]["label"])}</a> ›
    <a href="/merke/{escape(product["brand_slug"])}/">{escape(product["brand_label"])}</a> ›
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
    trenger (én oppsummeringsrad PER SERIE, ikke per behov) -- egen, enklere
    funksjon i stedet for å gjenbruke render_family_page sin interne (ikke
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
/* Merke-siden sitt løft (2026-09-27, samme dag som serie-siden sin
   FAQ-regelmotor) -- egne brand-*-klassenavn (ikke gjenbruk av
   serie-siden sine serie-*-klassenavn, selv der mønsteret er identisk)
   for å holde de to sidetypene sin CSS uavhengige av hverandre. */
.brand-stat-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.brand-stat-pill { display: flex; align-items: center; gap: 8px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 6px 10px; box-shadow: var(--card-shadow); }
.brand-stat-icon { width: 24px; height: 24px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.brand-stat-icon svg { width: 13px; height: 13px; }
.brand-stat-label { font-size: 0.68rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.02em; line-height: 1.25; }
.brand-stat-value { font-size: 0.82rem; font-weight: 600; color: var(--ink); line-height: 1.25; }
.brand-section-lead { color: var(--muted); font-size: 0.88rem; margin: 0 0 14px; }
/* Series Portrait Cards (2026-09-27, samme dag, etter Kais 19-punkts
   brief + presisering om kortbredde). Kortet skal ALDRI strekkes bredere
   bare fordi merket har få serier -- minmax() med en fast maks (340px),
   IKKE 1fr, så tomme grid-spor bare blir ubrukt luft i stedet for at de
   fyller ekte kort til unaturlig bredde. auto-fill (ikke auto-fit) sikrer
   samme oppførsel uansett om det er 1, 2, 3, 4, 5 eller 8 serier. */
.brand-section-header-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.brand-section-kicker { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin-bottom: 2px; }
.brand-section-header-row h2 { margin: 0 0 6px; }
.brand-section-header-row .brand-section-lead { margin: 0; }
.brand-serie-compare-link { font-size: 0.85rem; font-weight: 600; color: var(--blue); text-decoration: none; white-space: nowrap; margin-top: 4px; }
.brand-serie-compare-link:hover { text-decoration: underline; }
/* minmax(280px, 1fr), IKKE en fast maks-px -- auto-fill teller antall
   spor etter MIN-verdien kun når maks er ubestemt (1fr), som gir flest
   mulig kolonner ("4 kort på én rad der plassen tillater" -- en fast
   maks-px (f.eks. 350px) far derimot brukt til selve spor-TELLINGEN i
   Grid-spesifikasjonen, som i praksis ga bare 3 kolonner å 1240px
   containerbredde her, ikke 4). Tomme auto-fill-spor forblir usynlig
   luft (IKKE strukket brede) selv med 1fr, siden 1fr bare fordeler
   overskuddsplass likt på ALLE spor (ekte og tomme) -- se
   CSS_GRID_SERIES_WIDTH-testnotat i CLAUDE.md. */
.brand-serie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); justify-content: start; align-items: stretch; gap: 18px; margin-bottom: 32px; }
.brand-serie-card { display: flex; flex-direction: column; max-width: 350px; background: white; border: 1px solid var(--border); border-radius: 16px; overflow: hidden; text-decoration: none; color: var(--ink); box-shadow: var(--card-shadow); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.brand-serie-card:hover, .brand-serie-card:focus-visible { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(11, 37, 69, 0.1); border-color: #B9C4CE; }
.brand-serie-card-top { padding: 16px 16px 0; background: linear-gradient(180deg, var(--serie-tint, var(--mist)) 0%, rgba(255, 255, 255, 0) 68%); }
.brand-serie-card-eyebrow { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
.brand-serie-card-image { height: 148px; margin-top: 8px; display: flex; align-items: center; justify-content: center; }
.brand-serie-card-image img { max-width: 76%; max-height: 100%; height: auto; object-fit: contain; transition: transform 0.18s ease; }
.brand-serie-card:hover .brand-serie-card-image img, .brand-serie-card:focus-visible .brand-serie-card-image img { transform: scale(1.02); }
.brand-serie-card-fallback { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.6rem; color: var(--blue); }
.brand-serie-card-body { flex: 1; display: flex; flex-direction: column; padding: 14px 16px 16px; }
.brand-serie-card-name { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; line-height: 1.3; }
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
.brand-facts h2 { margin: 0 0 14px; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }
/* Prisintelligens ved siden av "i korte trekk" (Kai 2026-09-27: "kan være
   ved siden av gjen.snitt priser som på serier ... slik at vi har det
   samme her som på serie") -- samme to-kolonners stretch-mønster som
   .serie-insight-row (Prisinnsikt + Kort om X). */
.brand-insight-row { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 8px 0 32px; }
@media (min-width: 900px) { .brand-insight-row { grid-template-columns: 1fr 1fr; align-items: stretch; } }
.brand-i-tall { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); height: 100%; box-sizing: border-box; }
.brand-i-tall h2 { margin: 0; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }
.brand-i-tall-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 14px; }
@media (min-width: 480px) and (max-width: 899px) { .brand-i-tall-grid { grid-template-columns: repeat(3, 1fr); } }
.brand-i-tall-tile { background: var(--mist); border: 1px solid var(--border); border-radius: 12px; padding: 14px 12px; }
.brand-i-tall-icon { width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-bottom: 10px; }
.brand-i-tall-icon svg { width: 15px; height: 15px; }
.brand-i-tall-value { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.15rem; color: var(--ink); line-height: 1.2; }
.brand-i-tall-label { font-size: 0.76rem; font-weight: 600; color: var(--ink); margin-top: 4px; line-height: 1.3; }
.brand-i-tall-sub { font-size: 0.7rem; color: var(--muted); margin-top: 2px; line-height: 1.35; }
.brand-facts-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 11px; }
.brand-facts-list li { display: flex; align-items: flex-start; gap: 10px; font-size: 0.86rem; }
.brand-facts-list svg { flex-shrink: 0; width: 18px; height: 18px; color: var(--blue); margin-top: 1px; }
.brand-facts-list strong { display: block; color: var(--ink); font-weight: 600; }
.brand-facts-list span { display: block; font-size: 0.78rem; color: var(--muted); margin-top: 1px; }
/* Prisinnsikt-graf -- egen CSS-kopi av .price-insight* fra render_family_page()
   (samme begrunnelse som ellers: ikke kryss-avhengighet mellom sidetyper). */
.price-insight { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); height: 100%; box-sizing: border-box; }
.price-insight-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
.price-insight-head h2 { margin: 0; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }
.insight-tabs { display: flex; gap: 4px; background: var(--mist); border-radius: 10px; padding: 3px; }
.insight-tab { border: none; background: none; padding: 6px 14px; border-radius: 8px; font-size: 0.82rem; font-weight: 600; color: var(--muted); cursor: pointer; font-family: inherit; }
.insight-tab.active { background: white; color: var(--ink); box-shadow: var(--card-shadow); }
.price-insight-panel { display: none; }
.price-insight-panel.active { display: grid; grid-template-columns: 1fr; gap: 18px; }
.price-insight-current { font-family: 'Space Grotesk', sans-serif; font-size: 2.1rem; font-weight: 700; color: var(--ink); }
.price-insight-label { font-size: 0.82rem; color: var(--muted); margin-top: 2px; }
.price-insight-trend { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-weight: 700; font-size: 0.92rem; }
.price-insight-trend-note { font-weight: 400; color: var(--muted); font-size: 0.8rem; }
.insight-down { color: var(--mint); }
.insight-up { color: var(--coral); }
.insight-flat { color: var(--muted); }
.price-insight-tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 16px; }
.price-insight-tile { background: var(--mist); border-radius: 10px; padding: 8px 6px; text-align: center; }
.price-insight-tile strong { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; }
.price-insight-tile span { display: block; font-size: 0.66rem; color: var(--muted); margin-top: 2px; line-height: 1.3; }
.price-insight-chart .price-history { margin-top: 0; }
@media (min-width: 860px) { .price-insight-panel.active { grid-template-columns: 1fr 1.3fr; align-items: center; } }
.brand-compare-card { background: white; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: var(--card-shadow); margin-bottom: 32px; }
.spec-table { width: 100%; border-collapse: collapse; }
.spec-table th, .spec-table td { padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.88rem; }
.spec-table thead th { font-family: 'Space Grotesk', sans-serif; color: var(--muted); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em; background: var(--mist); }
.spec-table tbody tr:last-child td { border-bottom: none; }
.spec-table tbody tr:hover { background: var(--mist); }
.spec-table a { color: var(--blue); text-decoration: none; font-weight: 600; }
/* FAQ-accordion -- samme klassenavn/oppførsel som _render_family_faq_accordion()
   allerede bruker på serie-siden (egen CSS-kopi her, se samme begrunnelse
   som .guide-photo-card sin kommentar i GUIDE_TILE_STYLE). */
.faq-category { margin-top: 22px; }
.faq-category:first-child { margin-top: 0; }
.faq-category-label { font-family: 'Space Grotesk', sans-serif; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 4px; }
.faq-accordion-item { border-top: 1px solid var(--border); }
.faq-accordion-item:last-child { border-bottom: 1px solid var(--border); }
.faq-accordion-item summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; list-style: none; padding: 13px 0; font-weight: 600; font-size: 0.92rem; color: var(--ink); }
.faq-accordion-item summary::-webkit-details-marker { display: none; }
.faq-chevron { flex-shrink: 0; width: 16px; height: 16px; color: var(--muted); transition: transform 0.15s; }
.faq-accordion-item[open] .faq-chevron { transform: rotate(180deg); }
.faq-accordion-item p { margin: 0 0 15px; color: var(--muted); font-size: 0.88rem; line-height: 1.55; }
/* To-kolonners FAQ (Kai 2026-09-27, etter mockup: "gjør det nøyaktig slik
   ... så nært som mulig med alt") -- CSS-multikolonne i stedet for å endre
   _render_family_faq_accordion() sin delte HTML-struktur (den brukes
   uendret av serie-siden også) -- scoped til .brand-faq-wrap slik at
   serie-siden sin egen FAQ ikke påvirkes. break-inside:avoid på hver
   kategori hindrer at en kategori-overskrift havner alene nederst i en
   kolonne mens spørsmålene fortsetter i neste. */
@media (min-width: 860px) {
  .brand-faq-wrap .faq-section { column-count: 2; column-gap: 40px; }
  .brand-faq-wrap .faq-category { break-inside: avoid; -webkit-column-break-inside: avoid; }
}
/* Toppbanner (2026-09-27, Kai: "bruk toppbilde vi også bruker på serie
   her på disse for å få det pent") -- SAMME delte bilde som serie-hero
   (static/hero/serie-*.webp), samme side-panel-med-fade-teknikk. Egne
   brand-hero-*-klassenavn (ikke gjenbruk av .serie-hero* direkte) siden
   dette er en annen side, men ellers en bevisst 1:1-kopi av mønsteret. */
.brand-hero { position: relative; overflow: hidden; border: 1px solid var(--border); border-radius: 24px; background: linear-gradient(100deg, #FFFFFF 0%, #F6F9FD 55%, #E9F1FB 100%); box-shadow: var(--card-shadow); padding: 22px 24px; margin-bottom: 20px; }
.brand-hero-content { position: relative; z-index: 2; }
.brand-hero h1 { font-size: clamp(1.5rem, 4vw, 2rem); margin: 4px 0 8px; }
.brand-hero-media { display: none; }
@media (min-width: 860px) {
  .brand-hero { padding: 40px 44px 36px; }
  .brand-hero-content { max-width: 62%; }
  .brand-hero-media { display: block; position: absolute; top: 0; right: 0; bottom: 0; width: 42%; overflow: hidden; border-radius: 0 24px 24px 0; pointer-events: none; -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 40%); mask-image: linear-gradient(90deg, transparent 0, #000 40%); }
  .brand-hero-media img { display: block; width: 100%; height: 100%; object-fit: cover; object-position: right center; }
}
.brand-hero-subtitle { font-size: 0.98rem; font-weight: 600; color: var(--muted); margin: 2px 0 0; }
.brand-hero-cta-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 4px; }
.brand-hero-cta { display: inline-flex; align-items: center; gap: 6px; background: var(--blue); color: white; font-weight: 600; font-size: 0.88rem; padding: 10px 18px; border-radius: 10px; text-decoration: none; margin: 0; }
.brand-hero-cta:hover { opacity: 0.92; }
.brand-hero-cta-secondary { background: white; color: var(--ink); border: 1px solid var(--border); }
.brand-hero-cta-secondary:hover { opacity: 1; border-color: var(--blue); }
/* Statistikkstripe integrert nederst i hero-kortet (2026-09-27, etter
   mockup 42.webp) -- erstatter den tidligere frittstaende
   .brand-facts-row/.brand-facts-card-raden med fire store kort under
   heroen. z-index:3 sa stripen ligger over bade hero-innholdet og
   bilde-panelet (som har z-index:2/ingen), og spenner over hele
   hero-bredden siden den ligger som fullbredde-barn av .brand-hero, ikke
   inni .brand-hero-content (som er begrenset til 62% pa store skjermer).
   Ingen skillelinjer (verken over stripen eller mellom elementene) --
   Kai, samme dag: "Den kan fjernes. går over halsen på modellen.. Disse
   kan bare flyte naturlig uten streker" -- border-top gikk rett over
   modellens hals i bildet. Ren luft (gap) i stedet for border-left. */
.brand-hero-stats { position: relative; z-index: 3; display: flex; flex-wrap: wrap; column-gap: 26px; row-gap: 8px; margin-top: 38px; }
.brand-hero-stat { display: flex; align-items: center; gap: 7px; }
.brand-hero-stat-icon { display: flex; }
.brand-hero-stat-icon svg { width: 14px; height: 14px; display: block; }
.brand-hero-stat-value { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; color: var(--ink); }
.brand-hero-stat-label { font-size: 0.82rem; color: var(--muted); }
.brand-sortiment-grid { display: grid; grid-template-columns: 1fr; gap: 12px; margin-bottom: 32px; }
@media (min-width: 560px) { .brand-sortiment-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .brand-sortiment-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); } }
.brand-sortiment-card { display: block; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 18px 16px; text-decoration: none; color: var(--ink); box-shadow: var(--card-shadow); cursor: pointer; transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.brand-sortiment-card:hover, .brand-sortiment-card:focus-visible { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(11, 37, 69, 0.1); border-color: #B9C4CE; }
.brand-sortiment-card-icon { width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-bottom: 12px; }
.brand-sortiment-card-icon svg { width: 17px; height: 17px; }
.brand-sortiment-card-label { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.98rem; color: var(--ink); }
.brand-sortiment-card-count { font-weight: 600; font-size: 0.8rem; color: var(--muted); margin-top: 3px; }
.brand-sortiment-card-series { font-size: 0.76rem; color: var(--muted); margin-top: 6px; line-height: 1.4; }
.brand-sortiment-card-link { font-size: 0.8rem; font-weight: 600; color: var(--blue); margin-top: 10px; }
.brand-3090-card { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); margin-bottom: 32px; }
.brand-3090-card p { margin: 0 0 14px; font-size: 0.9rem; line-height: 1.6; color: var(--ink); }
.brand-3090-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.brand-3090-tile { background: var(--mist); border-radius: 10px; padding: 12px 8px; text-align: center; }
.brand-3090-tile-icon { width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 8px; }
.brand-3090-tile-icon svg { width: 13px; height: 13px; }
.brand-3090-tile strong { display: block; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; color: var(--ink); }
.brand-3090-tile span { display: block; font-size: 0.72rem; color: var(--muted); margin-top: 3px; }
.brand-3090-note { margin: 14px 0 0 !important; font-size: 0.78rem !important; color: var(--muted) !important; }
.brand-materials-grid { display: grid; grid-template-columns: 1fr; gap: 10px; margin-top: 14px; }
/* min-width:0 er nødvendig -- .brand-compare-card er et grid-barn, og
   grid-barn arver "min-width:auto" som standard, som nekter dem å
   krympe under bredden til innholdet sitt (her: en bred sammenlign-
   tabell). Uten denne linjen tvang tabellen HELE siden til å bli
   bredere enn mobilskjermen (bekreftet: 761px scrollWidth på en 375px
   viewport) -- selv om tabellen selv allerede hadde sin egen
   overflow-x:auto-innpakning, som ikke hjelper når selve
   grid-cellen rundt den ikke får lov til å krympe i utgangspunktet. */
.brand-compare-row { display: grid; grid-template-columns: 1fr; gap: 24px; margin-bottom: 32px; }
.brand-compare-row .brand-compare-card { margin-bottom: 0; min-width: 0; }
@media (min-width: 1024px) { .brand-compare-row { grid-template-columns: 1.2fr 1fr; align-items: start; } .brand-materials-grid { grid-template-columns: 1fr !important; } }
@media (min-width: 640px) and (max-width: 1023px) { .brand-materials-grid { grid-template-columns: repeat(2, 1fr); } }
.brand-material-card { display: flex; gap: 12px; align-items: flex-start; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; box-shadow: var(--card-shadow); }
.brand-material-card-icon { flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.brand-material-card-icon svg { width: 16px; height: 16px; }
.brand-material-card-body { min-width: 0; }
.brand-material-card-name { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.88rem; }
.brand-material-card-series { font-size: 0.78rem; color: var(--muted); margin-top: 4px; }
.brand-manufacturer-card { background: white; border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; box-shadow: var(--card-shadow); margin-bottom: 32px; }
.brand-manufacturer-kicker { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; color: var(--muted); }
.brand-manufacturer-name { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.05rem; margin-top: 3px; }
.brand-manufacturer-link { display: inline-block; font-size: 0.85rem; font-weight: 600; color: var(--blue); margin-top: 8px; text-decoration: none; }
.brand-trust { margin-top: 8px; padding-top: 24px; border-top: 1px solid var(--border); }
.brand-trust h2 { font-size: 1rem; margin: 0 0 14px; }
.brand-trust-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
@media (min-width: 640px) { .brand-trust-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .brand-trust-grid { grid-template-columns: repeat(4, 1fr); } }
.brand-trust-item strong { display: block; font-size: 0.85rem; color: var(--ink); margin-bottom: 3px; }
.brand-trust-item p { margin: 0; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }
.brand-trust-links { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 18px 0 0; }
.brand-trust-links a { font-size: 0.8rem; font-weight: 600; color: var(--blue); text-decoration: none; }
"""


def render_brand_page(brand_slug: str, brand_label: str, products: list[dict], categories: dict, product_families: list[dict], now: datetime | None = None, price_history: dict | None = None) -> str:
    """Merke-side (/merke/{slug}/) -- fikk 2026-09-27 samme type løft som
    serie-siden fikk tidligere samme dag, etter Kai sitt ønske ("ikke bare
    på serier"). Legger til et serie-navigasjons-lag, en
    sammenligningstabell PÅ TVERS av merkets serier, egne pris-
    intelligens-tall og en FAQ-regelmotor -- gjenbruker product_families.json
    (samme kurerte data som /serie/-sidene), ikke en ny datakilde.

    BEVISST UTELATT (se Kai sin pastede AI-samtale for det fulle forslaget):
    - "Materialer og teknologier"-seksjonen med "Les om materialet →"/
      "Hva betyr det? →"-lenker til egne materialsider (LACREON, HYDRACLEAR
      PLUS osv.) -- vi har INGEN slike sider, og finner ikke opp lenker som
      ikke finnes. Samme begrunnelse som da materialglossar ble utelatt fra
      serie-siden sin FAQ-regelmotor samme dag: krever en egen,
      research-basert kunnskapsbase vi ikke har ennå.
    - Full omorganisering av selve produktkatalogen (gruppert per serie med
      sorteringsvalg) -- den eksisterende flate rutenett+kategorifilter-
      løsningen (med fungerende JS) er beholdt uendret, bare flyttet lenger
      ned på siden. En ordentlig "gruppert per serie"-katalog er en egen,
      separat oppgave (rører den eksisterende filter-JS-en), ikke gjort her.
    - Prishistorikk/trend for merket ("Acuvue-prisutvikling siste 90
      dager") -- mulig gjenbruk av _family_price_insight_data()-mønsteret
      senere, men utelatt her for å holde denne runden avgrenset.

    Adaptivt: et merke uten noen ekte serie (produkt_families.json har
    ingen familie med ≥2 av dette merkets produkter) viser INGEN
    serie-navigasjon/sammenligningstabell -- samme "ikke en gigantisk fake
    brand intelligence-side for ett eneste produkt"-prinsipp Kai selv
    påpekte i forslaget."""
    now = now or datetime.now(timezone.utc)

    manufacturer_slug = BRAND_TO_MANUFACTURER.get(brand_slug)
    # Sekundær hero-knapp (2026-09-27, etter mockup: "Les om merket") --
    # erstatter den forrige rene tekstlenken. Lenker til den ekte,
    # eksisterende /produsent/-siden (ingen ny "om merket"-side finnes eller
    # trengs -- produsentsiden ER svaret på "hvem står bak dette merket").
    manufacturer_link_html = (
        f'<a class="brand-hero-cta brand-hero-cta-secondary" href="/produsent/{manufacturer_slug}/">'
        f'Om {escape(MANUFACTURERS[manufacturer_slug]["name"])} →</a>'
        if manufacturer_slug else ""
    )

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        image_url = _product_image(p)
        specs = {label: value for label, value in p.get("specs", [])}
        pack = _pack_size_from_id(p["id"])
        rows.append({
            "product": p, "lowest": lowest, "image_url": image_url, "eligible": eligible,
            "category_label": categories.get(p["category_slug"], {}).get("label", ""),
            "material": specs.get("Materiale"), "pack_size": pack[1] if pack else None,
        })

    rows.sort(key=lambda r: r["lowest"]["price_nok"] if r["lowest"] else float("inf"))

    # Serie-navigasjon: samme kurerte families-data som /serie/-sidene,
    # filtrert til familier der minst 2 av MEDLEMMENE faktisk tilhører
    # dette merket (familier er alltid ett-merke i praksis, men sjekket
    # eksplisitt fremfor antatt).
    brand_product_ids = {p["id"] for p in products}
    products_by_id_brand = {p["id"]: p for p in products}
    family_summaries = []
    for family in product_families:
        member_products = [products_by_id_brand[mid] for mid in family["member_ids"] if mid in brand_product_ids]
        if len(member_products) < 2:
            continue
        summary = _brand_family_summary(family, member_products, categories, now)
        if summary:
            family_summaries.append(summary)
    family_summaries.sort(key=lambda s: s["min_price"] if s["min_price"] else float("inf"))

    # Pris-intelligens og FAQ trenger tall på tvers av HELE merket (ikke
    # bare produktene som havnet i en serie -- et frittstående produkt som
    # Acuvue Vita skal fortsatt telle med i "21 produkter"/laveste pris).
    all_eligible = [o for r in rows for o in r["eligible"]]
    retailer_count = len({o["retailer"] for o in all_eligible})
    type_labels_all = sorted({r["category_label"] for r in rows if r["category_label"]})
    materials_all = sorted({r["material"] for r in rows if r["material"]})
    lowest_row = min((r for r in rows if r["lowest"]), key=lambda r: r["lowest"]["price_nok"], default=None)
    per_lens_rows = [
        (r["lowest"]["price_nok"] / r["pack_size"], r) for r in rows if r["lowest"] and r["pack_size"]
    ]
    cheapest_per_lens = min(per_lens_rows, key=lambda t: t[0], default=None)

    top_product_names = [r["product"]["name"] for r in rows if r["lowest"]][:3]
    if not top_product_names:
        meta_description = f"Sammenlign priser på alle {brand_label}-kontaktlinser vi følger, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud."
    elif len(top_product_names) == 1:
        meta_description = f"Sammenlign priser på {brand_label}-kontaktlinser som {top_product_names[0]}, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud."
    else:
        examples = ", ".join(top_product_names[:-1]) + " og " + top_product_names[-1]
        meta_description = f"Sammenlign priser på {brand_label}-kontaktlinser som {examples}, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud."

    manufacturer_card_line = (
        f'<a class="product-tile-manufacturer" href="/produsent/{manufacturer_slug}/">{escape(MANUFACTURERS[manufacturer_slug]["name"])}</a>'
        if manufacturer_slug else ""
    )

    def render_grid_card(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        return _render_product_tile(
            href=f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/',
            name=p["name"],
            image_url=r["image_url"],
            fallback_initials=p["brand_label"][:2].upper(),
            category_label=categories[p["category_slug"]]["label"],
            secondary_line_html=manufacturer_card_line,
            lowest=lowest,
            other_count=len(p["offers"]) - 1,
            data_attr=f' data-category="{escape(p["category_slug"])}"',
        )

    product_rows_html = "\n".join(render_grid_card(r) for r in rows)

    brand_logo_cls, brand_logo_content = _brand_badge(brand_slug, brand_label)
    brand_logo_block = f'<div class="brand-hero-logo {brand_logo_cls}">{brand_logo_content}</div>' if brand_logo_cls else ""

    # Kort, faktabasert intro-setning i heroen (2026-09-27, etter en pastet
    # AI-brief -- "kort, presis, faktabasert introduksjon", eksplisitt IKKE
    # reklamespråk/udokumenterte påstander). Generert fra data vi faktisk
    # har (produsent/linsetyper/antall), ikke en hardkodet markedsføringstekst
    # per merke. Erstatter den forrige, generiske "Alle X-linser vi følger
    # prisen på"-linjen -- samme informasjon (den flyttet til
    # manufacturer_link_html/stat-pillene), men denne sier faktisk noe om
    # SELVE merket.
    type_labels_lower = [t[0].lower() + t[1:] if t else t for t in type_labels_all]
    if len(type_labels_lower) <= 1:
        brand_type_txt = type_labels_lower[0] if type_labels_lower else ""
    else:
        brand_type_txt = ", ".join(type_labels_lower[:-1]) + " og " + type_labels_lower[-1]
    brand_series_txt = f', fordelt på {len(family_summaries)} {"serie" if len(family_summaries) == 1 else "serier"}' if family_summaries else ""
    # Egen undertittel ("Kontaktlinser fra X") rett under H1 -- matcher
    # mockupen Kai sendte -- så selve intro-avsnittet IKKE gjentar
    # produsentnavnet rett etter (sto der fra før). Kun bygget ved kjent
    # produsent-kobling.
    brand_subtitle_html = (
        f'<p class="brand-hero-subtitle">Kontaktlinser fra {escape(MANUFACTURERS[manufacturer_slug]["name"])}</p>'
        if manufacturer_slug else ""
    )
    brand_intro_sentence = (
        f'{escape(brand_label)} er en linseserie'
        + (f' med {escape(brand_type_txt)}' if brand_type_txt else '')
        + f'. Vi følger prisen på {len(products)} {"produkt" if len(products) == 1 else "produkter"}{brand_series_txt}, sortert etter lavest pris.'
    )

    category_slugs = sorted({p["category_slug"] for p in products})
    category_chips = "".join(
        f'<button class="chip" data-category="{escape(c)}">{escape(categories[c]["label"])}</button>' for c in category_slugs
    )

    # -- "Fase 2" merke-fakta -- egen, mer synlig rad UNDER heroen (Kai
    # sendte et mockup-referansebilde 2026-09-27 som viser 4 større,
    # frittstående faktakort her, ikke bare små piller inni selve
    # hero-kortet) -- samme "kun det vi faktisk kan bevise"-prinsipp som
    # serie-siden sine stat-piller, bare i et tydeligere, egnet format.
    store_icon = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9l1-5h14l1 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M4 9h16M9.5 20v-5.5h5V20"/></svg>'
    # Rullerende aksentfarger (mint/blue/amber/lavender -- de samme fire
    # tonene som allerede finnes i designsystemet, se GUIDE_ICONS) i stedet
    # for ensfarget blått på alle kortene -- Kai 2026-09-27, etter mockup:
    # "gjør det nøyaktig slik, så nært som mulig med alt".
    # (farge, ikon, STORT tall, enhet-etikett, valgfri undertekst) -- delt
    # tall/etikett i to linjer for å matche mockupen sitt typografiske
    # hierarki (stort tall øverst, ikke "21 produkter" som én sammenhengende
    # streng slik forrige runde gjorde).
    stat_pills = [("mint", BOX_ICON_SVG, str(len(products)), "produkt" if len(products) == 1 else "produkter", "")]
    if family_summaries:
        stat_pills.append(("blue", TAG_ICON_SVG, str(len(family_summaries)), "serie" if len(family_summaries) == 1 else "serier", ""))
    if type_labels_all:
        stat_pills.append(("lavender", DROPLET_ICON_SVG, str(len(type_labels_all)), "linsetype" if len(type_labels_all) == 1 else "linsetyper", " · ".join(type_labels_all)))
    if retailer_count:
        stat_pills.append(("amber", store_icon, str(retailer_count), "butikk" if retailer_count == 1 else "butikker", f'Med {brand_label}-produkter akkurat nå'))
    # Kompakt statistikkstripe integrert nederst i selve hero-kortet
    # (2026-09-27, etter mockup 42.webp: "Replace the four large Brand
    # Facts cards below the hero with a compact metadata strip integrated
    # into the bottom of the hero"). Samme stat_pills-data som over, men
    # UTEN undertekst-listen (linsetype-oppramsingen er bevisst utelatt her
    # -- den informasjonen forklares lenger ned på siden, jf. instruksen).
    brand_hero_stats_html = "".join(
        f'''<div class="brand-hero-stat">
    <span class="brand-hero-stat-icon" style="color:var(--{color});" aria-hidden="true">{icon}</span>
    <span class="brand-hero-stat-value">{escape(number)}</span>
    <span class="brand-hero-stat-label">{escape(unit)}</span>
  </div>'''
        for color, icon, number, unit, sub in stat_pills
    )

    # -- "Utforsk {brand}-seriene" -- kun hvis merket faktisk har minst én
    # ekte serie (adaptivt, se docstring). "Series Portrait Cards"
    # (2026-09-27, samme dag) -- Kai sendte en detaljert 19-punkts brief +
    # mockup-referanse (44.webp) og bygget selv videre på den med en
    # eksplisitt presisering om kortbredde. Kjernekravet: kompakte,
    # redaksjonelle kort (IKKE en nettbutikk-grid), og et kort skal ALDRI
    # bli unaturlig bredt bare fordi merket har få serier -- se
    # `.brand-serie-grid` (minmax med fast maks, ikke 1fr) lenger ned.
    # "Standard/Torisk/Multifokal"-pillene er utledet fra samme
    # type_labels som resten av siden allerede bruker.
    def brand_series_variant_pills(type_labels: list[str]) -> tuple[str | None, list[str]]:
        primary = next((t for t in type_labels if t not in ("Toriske linser", "Multifokale linser")), None)
        pills = ["Standard"] if primary else []
        if "Toriske linser" in type_labels:
            pills.append("Torisk")
        if "Multifokale linser" in type_labels:
            pills.append("Multifokal")
        return primary, pills

    # Ren, subtil bakgrunnstoning per kort -- KUN visuell differensiering
    # (samme fargesett som resten av designsystemet), ikke koblet til noe
    # faktisk merkevare-/produktdata. Roterer deterministisk per indeks.
    SERIES_CARD_TINTS = ["mint", "sky", "lavender", "amber", "coral", "blue"]
    # Eyebrow-fargen derimot ER koblet til faktisk data -- samme
    # kategori->farge-kobling som "Sortimentet forklart"-kortene lenger ned
    # på siden bruker (category_icon_map), så "Dagslinser" alltid betyr det
    # samme visuelt på tvers av hele siden.
    SERIES_TYPE_COLORS = {"Dagslinser": "amber", "Månedslinser": "sky", "Fargede linser": "mint", "Toriske linser": "coral", "Multifokale linser": "lavender"}

    def brand_series_description(primary_label: str | None, material: str | None, pills: list[str]) -> str | None:
        # Kai, punkt 8: "Hvis vi ikke har gode nok fakta til en nyttig
        # beskrivelse -> ikke vis beskrivelsen." Krever BÅDE kjent
        # hovedtype OG ett entydig materiale på tvers av hele serien
        # (samme _brand_family_summary-felt som "Materialer"-seksjonen
        # bruker -- `material` er allerede None hvis serien har >1
        # materiale, se _brand_family_summary()).
        if not primary_label or not material or not pills:
            return None
        words = [p.lower() for p in pills]
        if len(words) == 1:
            variant_txt = f"{words[0]} variant"
        else:
            variant_txt = ", ".join(words[:-1]) + f" og {words[-1]} variant"
        return f"Serie med {primary_label.lower()} i {escape(material)}, tilgjengelig som {variant_txt}."

    def brand_series_card(s: dict, index: int) -> str:
        img_html = f'<img src="{escape(s["image"])}" alt=""{_dim_attrs(s["image"])} loading="lazy" decoding="async">' if s["image"] else '<div class="brand-serie-card-fallback">' + escape(s["name"][:2].upper()) + '</div>'
        primary_label, pills = brand_series_variant_pills(s["type_labels"])
        pills_html = "".join(f'<span class="brand-serie-card-pill">{escape(p)}</span>' for p in pills)
        price_txt = _fmt_kr(s["min_price"]) if s["min_price"] else "Ingen pris"
        desc = brand_series_description(primary_label, s["material"], pills)
        tint = SERIES_CARD_TINTS[index % len(SERIES_CARD_TINTS)]
        eyebrow_color = SERIES_TYPE_COLORS.get(primary_label, "blue")
        eyebrow_html = f'<span class="brand-serie-card-eyebrow" style="background:var(--{eyebrow_color}-tint);color:var(--{eyebrow_color});">{escape(primary_label.upper())}</span>' if primary_label else ''
        return f'''<a class="brand-serie-card" href="{escape(s["href"])}" style="--serie-tint:var(--{tint}-tint);">
    <div class="brand-serie-card-top">
      {eyebrow_html}
      <div class="brand-serie-card-image">{img_html}</div>
    </div>
    <div class="brand-serie-card-body">
      <div class="brand-serie-card-name">{escape(s["name"])}</div>
      {f'<p class="brand-serie-card-desc">{desc}</p>' if desc else ''}
      {f'<div class="brand-serie-card-pills">{pills_html}</div>' if pills_html else ''}
      <div class="brand-serie-card-spacer"></div>
      <div class="brand-serie-card-foot"><span>{s["n_products"]} produkter</span><strong>Fra {price_txt}</strong></div>
      <div class="brand-serie-card-cta">Utforsk serien <span aria-hidden="true">→</span></div>
    </div>
  </a>'''

    series_nav_html = ""
    if family_summaries:
        # "Sammenlign seriene ->" -- lenke til den ekte sammenligningstabellen
        # lenger ned på siden (kun hvis den faktisk vises, dvs. >=2 serier å
        # sammenligne -- Kai, punkt 2: "Bare gjør dette til en lenke dersom
        # sammenligningsfunksjonen faktisk finnes").
        compare_link_html = '<a class="brand-serie-compare-link" href="#sammenlign">Sammenlign seriene →</a>' if len(family_summaries) >= 2 else ''
        series_nav_html = f'''<div class="brand-section-header-row">
    <div>
      <div class="brand-section-kicker">Produktserier</div>
      <h2>Utforsk {escape(brand_label)}-seriene</h2>
      <p class="brand-section-lead">Se forskjeller, varianter, egenskaper og priser i hver produktserie.</p>
    </div>
    {compare_link_html}
  </div>
  <div class="brand-serie-grid">
    {"".join(brand_series_card(s, i) for i, s in enumerate(family_summaries))}
  </div>'''

    # -- "{brand} i tall" -- Kai sendte et mockup-referansebilde 2026-09-27
    # og ba om å matche det "så nært som mulig med alt": IKKE en sjekkliste
    # ("Kort om X") slik serie-siden har, men en fargerik stat-flise-rad med
    # rene pris-/tilbudsintelligens-tall (produsent/linsetyper/materialer
    # dekkes allerede av Fase-2-raden over og de egne materialene-/
    # produsent-seksjonene lenger ned, så ingen redundans ved å droppe
    # sjekklisten). Kun de tallene som faktisk er robuste tas med -- "3 gode
    # er bedre enn 5 hvor to er svake" (samme prinsipp som før).
    brand_i_tall_tiles = []
    if lowest_row and lowest_row["lowest"]:
        brand_i_tall_tiles.append(("mint", TROPHY_ICON_SVG, _fmt_kr(lowest_row["lowest"]["price_nok"]), "Laveste produktpris", lowest_row["product"]["name"]))
    if cheapest_per_lens:
        per_lens_val, per_lens_row = cheapest_per_lens
        per_lens_txt = f'{per_lens_val:.1f}'.replace(".", ",") + " kr"
        brand_i_tall_tiles.append(("amber", BOX_ICON_SVG, per_lens_txt, "Laveste pris per linse", per_lens_row["product"]["name"]))
    spread_candidates = []
    for r in rows:
        if len(r["eligible"]) >= 2:
            prices = [o["price_nok"] for o in r["eligible"]]
            lo, hi = min(prices), max(prices)
            if lo > 0:
                spread_candidates.append((round((hi - lo) / lo * 100), r))
    biggest_spread = max(spread_candidates, key=lambda t: t[0], default=None)
    if biggest_spread and biggest_spread[0] >= 5:
        brand_i_tall_tiles.append(("sky", TAG_ICON_SVG, f'{biggest_spread[0]} %', "Størst prisforskjell mellom butikker", biggest_spread[1]["product"]["name"]))
    most_retailers_row = max(rows, key=lambda r: len(r["eligible"]), default=None)
    if most_retailers_row and len(most_retailers_row["eligible"]) >= 2:
        brand_i_tall_tiles.append(("lavender", store_icon, str(len(most_retailers_row["eligible"])), "Flest butikker", most_retailers_row["product"]["name"]))
    most_variants_series = max(family_summaries, key=lambda s: len(s["type_labels"]), default=None)
    if most_variants_series and len(most_variants_series["type_labels"]) >= 2:
        brand_i_tall_tiles.append(("coral", TROPHY_ICON_SVG, most_variants_series["name"], "Flest varianter", " · ".join(most_variants_series["type_labels"])))
    brand_i_tall_html = ""
    if brand_i_tall_tiles:
        brand_i_tall_html = f'''<div class="brand-i-tall">
    <h2>{escape(brand_label)} i tall</h2>
    <p class="brand-section-lead">Basert på produktene og prisene vi følger akkurat nå.</p>
    <div class="brand-i-tall-grid">
      {"".join(f'<div class="brand-i-tall-tile"><div class="brand-i-tall-icon" style="background:var(--{color}-tint);color:var(--{color});" aria-hidden="true">{icon}</div><div class="brand-i-tall-value">{escape(val)}</div><div class="brand-i-tall-label">{escape(lbl)}</div><div class="brand-i-tall-sub">{escape(sub)}</div></div>' for color, icon, val, lbl, sub in brand_i_tall_tiles)}
    </div>
  </div>'''

    # -- Prisinnsikt for HELE merket (snitt per pakningsstørrelse, på tvers
    # av ALLE produktene -- gjenbruker EKSAKT samme funksjoner som serie-
    # siden, se _family_price_insight_data()/render_family_price_insight().
    # Kai 2026-09-27: "hvor er grafen og prisene?" -- de 3 flate stat-
    # kortene som sto her var IKKE det samme som seriesidens ekte
    # prisinnsikt-graf, luket derfor ut til fordel for den ekte komponenten.
    # Overskrift endret til "{brand}-priser" (matcher mockupen) via den nye
    # heading-parameteren -- selve funksjonen er fortsatt uendret/delt med
    # serie-siden. --
    brand_price_insight_html = ""
    if price_history:
        brand_insight_by_pack = _family_price_insight_data(rows, price_history)
        brand_price_insight_html = render_family_price_insight(brand_label, brand_insight_by_pack, scope_label=f"i {brand_label}-sortimentet", heading=f"{brand_label}-priser")

    # -- "Slik skiller seriene seg" -- sammenligningstabell PÅ TVERS av
    # merkets serier (én rad per serie, ikke per behov slik serie-siden sin
    # egen tabell er -- her er det seriene selv som sammenlignes). --
    compare_table_html = ""
    if family_summaries:
        show_material_col = any(s["material"] for s in family_summaries)
        show_wc_col = any(s["wc"] for s in family_summaries)

        def compare_row(s: dict) -> str:
            cells = f'<td class="spec-value">{escape(" · ".join(s["type_labels"]))}</td>' if s["type_labels"] else '<td class="spec-value">–</td>'
            if show_material_col:
                cells += f'<td class="spec-value">{escape(s["material"]) if s["material"] else "–"}</td>'
            if show_wc_col:
                wc_txt = " / ".join(v.replace(".", ",") + " %" for v in s["wc"]) if s["wc"] else "–"
                cells += f'<td class="spec-value">{wc_txt}</td>'
            packs_txt = "/".join(str(n) for n in s["packs"]) if s["packs"] else "–"
            price_txt = _fmt_kr(s["min_price"]) if s["min_price"] else "Ingen pris"
            return f'''<tr>
      <th scope="row" class="spec-label"><a href="{escape(s["href"])}">{escape(s["name"])}</a></th>
      <td class="spec-value">{s["n_products"]}</td>
      {cells}
      <td class="spec-value">{escape(packs_txt)}</td>
      <td class="spec-value">{price_txt}</td>
    </tr>'''

        header_extra = "<th>Bruk</th>"
        if show_material_col:
            header_extra += "<th>Materiale</th>"
        if show_wc_col:
            header_extra += "<th>Vanninnhold</th>"
        # Lead-setning + egen "Produkter"-kolonne (2026-09-27, Kai: "jeg
        # tenkte på at jeg bare så 4 produkter her") -- tabellen har alltid
        # vist SERIER, ikke enkeltprodukter (4 Acuvue-serier dekker faktisk
        # 20 av 21 produkter), men det var ikke synlig i tabellen selv uten
        # å telle radene. Viser nå eksplisitt både antall produkter PER
        # serie og totalen, pluss et eget produkt utenfor enhver serie der
        # det finnes (f.eks. Acuvue Vita), i stedet for å late som det ikke
        # eksisterer.
        covered_products = sum(s["n_products"] for s in family_summaries)
        standalone_n = len(products) - covered_products
        standalone_txt = f' Ytterligere {standalone_n} {"produkt" if standalone_n == 1 else "produkter"} står utenfor disse seriene, se hele listen nederst.' if standalone_n > 0 else ""
        compare_table_html = f'''<h2 id="sammenlign" style="scroll-margin-top:20px;">Slik skiller {escape(brand_label)}-seriene seg</h2>
  <p class="brand-section-lead">{len(family_summaries)} {"serie" if len(family_summaries) == 1 else "serier"}, til sammen {covered_products} av {len(products)} {escape(brand_label)}-produkter.{standalone_txt}</p>
  <div class="brand-compare-card">
    <div style="overflow-x:auto;">
      <table class="spec-table">
        <thead><tr><th>Serie</th><th>Produkter</th>{header_extra}<th>Pakninger</th><th>Fra pris (uten frakt)</th></tr></thead>
        <tbody>{"".join(compare_row(s) for s in family_summaries)}</tbody>
      </table>
    </div>
  </div>'''

    # Prisinnsikt-graf + "Kort om X" side om side (samme mønster som
    # .serie-insight-row) -- Kai 2026-09-27: "kan være ved siden av
    # gjen.snitt priser som på serier ... slik at vi har det samme her som
    # på serie". Faller tilbake til bare den ene boksen (uten tom
    # rad-wrapper) hvis grafen mangler (for lite prishistorikk ennå).
    brand_insight_row_html = (
        f'<div class="brand-insight-row">{brand_i_tall_html}{brand_price_insight_html}</div>'
        if brand_i_tall_html and brand_price_insight_html else brand_i_tall_html + brand_price_insight_html
    )

    # -- "Materialer i {brand}-sortimentet" -- BEVISST IKKE "Materialer og
    # teknologier" med egne "Les om materialet/teknologien →"-lenker, se
    # Kai sin pastede brief Fase 9 sin egen fallback-regel: "Hvis
    # kunnskapssiden ikke finnes ennå, kan kortet være informativt uten
    # fake link." Vi har INGEN egne materialsider, og "Materiale"-feltet i
    # specs er én sammensatt streng ("Etafilcon A med LACREON-teknologi"),
    # ikke to separate, uavhengig dokumenterte entiteter (grunnmateriale +
    # teknologi) -- å dele den opp og late som "LACREON" er en egen,
    # researchet kunnskapsgraf-node ville vært å hevde mer enn vi faktisk
    # vet. Viser derfor de fulle, ekte spec-strengene som informative kort,
    # ingen splitting, ingen oppdiktede lenker.
    material_colors = ["sky", "mint", "lavender", "amber", "coral"]

    def brand_material_card(m: str, i: int) -> str:
        series_names = sorted({s["name"] for s in family_summaries if s["material"] == m})
        sub = " · ".join(series_names) if series_names else ""
        color = material_colors[i % len(material_colors)]
        return f'''<div class="brand-material-card">
    <div class="brand-material-card-icon" style="background:var(--{color}-tint);color:var(--{color});" aria-hidden="true">{DROPLET_ICON_SVG}</div>
    <div class="brand-material-card-body">
      <div class="brand-material-card-name">{escape(m)}</div>
      {f'<div class="brand-material-card-series">Brukes i: {escape(sub)}</div>' if sub else ''}
    </div>
  </div>'''

    brand_materials_html = ""
    if len(materials_all) >= 2:
        brand_materials_html = f'''<div><h2>Materialer i {escape(brand_label)}-sortimentet</h2>
  <p class="brand-section-lead">De dokumenterte materialene {escape(brand_label)}-produktene vi følger er laget av.</p>
  <div class="brand-materials-grid">
    {"".join(brand_material_card(m, i) for i, m in enumerate(materials_all))}
  </div></div>'''

    # Sammenligningstabell + materialer side om side (Kai 2026-09-27, etter
    # mockup: "gjør det nøyaktig slik ... så nært som mulig med alt") --
    # samme to-kolonners mønster som insight-raden over, men uten
    # stretch/tvunget lik høyde (en tabell og et kortrutenett har naturlig
    # ulik høyde, og det er ikke et problem her slik det var for
    # "Felles for hele serien"/"Relevante guider"-paret tidligere i økta).
    # min-width:0 er nødvendig HER (på selve grid-barnet, IKKE bare på
    # .brand-compare-card lenger inni) -- bekreftet ved DOM-inspeksjon at
    # denne uklassede wrapper-diven var det faktiske grid-barnet av
    # .brand-compare-row, med nedarvet min-width:auto som fortsatt tvang
    # hele siden bredere enn en mobilskjerm (761px scrollWidth på 375px
    # viewport) selv etter at .brand-compare-card selv fikk min-width:0.
    compare_table_html_wrapped = f'<div style="min-width:0;">{compare_table_html}</div>' if compare_table_html else ""
    brand_compare_row_html = (
        f'<div class="brand-compare-row">{compare_table_html_wrapped}{brand_materials_html}</div>'
        if compare_table_html and brand_materials_html else compare_table_html + brand_materials_html
    )

    # -- FAQ-regelmotor (samme mønster/komponent som serie-siden sin,
    # se _render_family_faq_accordion()) -- men merke-spesifikke spørsmål.
    # Materialglossar (LACREON osv.) bevisst utelatt, se docstring. --
    faq_produkt: list[dict] = []
    faq_spec: list[dict] = []
    faq_pris: list[dict] = []
    if manufacturer_slug:
        faq_produkt.append({
            "question": f'Hvem produserer {brand_label}?',
            "answer": f'{brand_label} produseres av {MANUFACTURERS[manufacturer_slug]["name"]}.',
        })
    if family_summaries:
        serie_names = ", ".join(s["name"] for s in family_summaries)
        faq_produkt.append({
            "question": f'Hvilke {brand_label}-serier finnes?',
            "answer": f'{brand_label} finnes som følgende serier hos oss: {serie_names}. Se tabellen under for hvordan de skiller seg.',
        })
    if "toriske-linser" in category_slugs:
        faq_produkt.append({
            "question": f'Finnes {brand_label} for astigmatisme?',
            "answer": f'Ja, {brand_label} har toriske varianter laget for astigmatisme. Se sammenligningen under for hvilke serier som har dette.',
        })
    if "multifokale-linser" in category_slugs:
        faq_produkt.append({
            "question": f'Finnes {brand_label} som multifokale linser?',
            "answer": f'Ja, {brand_label} har multifokale varianter for alderssyn (presbyopi). Se sammenligningen under for hvilke serier som har dette.',
        })
    if "dagslinser" in category_slugs and "manedslinser" in category_slugs:
        faq_produkt.append({
            "question": f'Har {brand_label} både dagslinser og månedslinser?',
            "answer": f'Ja, {brand_label}-sortimentet vårt dekker både dagslinser (kastes hver dag) og månedslinser (gjenbrukes med rengjøring). Se seriene over for hvilken som er hvilken.',
        })
    if materials_all:
        faq_spec.append({
            "question": f'Hvilke materialer brukes i {brand_label}-linser?',
            "answer": f'De {brand_label}-produktene vi følger er laget av {", ".join(materials_all)}. Materialet varierer mellom seriene, se tabellen over.' if len(materials_all) > 1
                      else f'De {brand_label}-produktene vi følger er laget av {materials_all[0]}.',
        })
    if lowest_row and lowest_row["lowest"]:
        faq_pris.append({
            "question": f'Hva er billigst i {brand_label}-sortimentet?',
            "answer": f'{lowest_row["product"]["name"]} er billigst akkurat nå, fra {_fmt_kr(lowest_row["lowest"]["price_nok"])} hos {lowest_row["lowest"]["retailer"]} (uten frakt).',
        })
    if cheapest_per_lens:
        per_lens_val, per_lens_row = cheapest_per_lens
        per_lens_txt = f'{per_lens_val:.1f}'.replace(".", ",")
        faq_pris.append({
            "question": f'Hvilken {brand_label}-pakning har lavest pris per linse akkurat nå?',
            "answer": f'{per_lens_row["product"]["name"]} har lavest pris per linse akkurat nå, ca. {per_lens_txt} kr per linse (uten frakt).',
        })
    if retailer_count:
        faq_pris.append({
            "question": f'Hos hvor mange butikker sammenligner Kontaktlinser.no {brand_label}?',
            "answer": f'Vi sammenligner {brand_label} hos {retailer_count} norske nettbutikker til sammen, på tvers av alle {len(products)} produktene vi følger.',
        })
    brand_faq_html, brand_faq_schema = _render_family_faq_accordion(
        [("Merke og serier", faq_produkt), ("Spesifikasjoner", faq_spec), ("Pris og butikker", faq_pris)],
        f'Ofte stilte spørsmål om {brand_label}',
    )

    # -- "{brand}-sortimentet forklart" -- én kortoversikt per KATEGORI
    # (ikke serie), for å gjøre et sortiment på 20+ produkter forståelig.
    # Kun bygget hvis merket faktisk har MER ENN ÉN kategori -- et merke med
    # bare dagslinser har ingenting å "forklare" her (adaptivt, se
    # docstring). Lenkene ("Se {kategori} →") bruker samme
    # kategori-filter-rad som allerede finnes lenger ned på siden (samme
    # JS, se filterRow-scriptet), IKKE en ny side -- href="#{slug}" pluss et
    # lite tillegg i scriptet som leser location.hash ved sidelasting.
    sortiment_cards = []
    for cat_slug in category_slugs:
        cat_rows = [r for r in rows if r["product"]["category_slug"] == cat_slug]
        if not cat_rows:
            continue
        series_names = sorted({
            s["name"] for s in family_summaries
            if any(fr["product"]["category_slug"] == cat_slug for fr in s["rows"])
        })
        sortiment_cards.append({
            "label": categories.get(cat_slug, {}).get("label", cat_slug),
            "slug": cat_slug,
            "count": len(cat_rows),
            "series_names": series_names,
        })
    sortiment_html = ""
    if len(sortiment_cards) > 1:
        # Ikon+farge per kategori (samme aksentfarge-sett som resten av
        # merke-siden sitt løft 2026-09-27) -- ukjente/fremtidige
        # kategorier faller tilbake til TAG_ICON_SVG/blue i stedet for å
        # krasje eller vise ingenting.
        eye_icon = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>'
        person_icon = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="8" r="3.5" fill="currentColor"/><path d="M5 20c0-4 3-6.5 7-6.5s7 2.5 7 6.5" fill="currentColor" opacity="0.5"/></svg>'
        category_icon_map = {
            "dagslinser": ("amber", SUN_ICON_SVG), "manedslinser": ("sky", CALENDAR_ICON_SVG),
            "toriske-linser": ("coral", eye_icon), "multifokale-linser": ("lavender", person_icon),
            "fargede-linser": ("mint", DROPLET_ICON_SVG),
        }

        def sortiment_card(c: dict) -> str:
            series_txt = " · ".join(c["series_names"]) if c["series_names"] else ""
            color, icon = category_icon_map.get(c["slug"], ("blue", TAG_ICON_SVG))
            return f'''<a class="brand-sortiment-card" href="#{escape(c["slug"])}" data-category="{escape(c["slug"])}">
    <div class="brand-sortiment-card-icon" style="background:var(--{color}-tint);color:var(--{color});" aria-hidden="true">{icon}</div>
    <div class="brand-sortiment-card-label">{escape(c["label"])}</div>
    <div class="brand-sortiment-card-count">{c["count"]} {"produkt" if c["count"] == 1 else "produkter"}</div>
    {f'<div class="brand-sortiment-card-series">{escape(series_txt)}</div>' if series_txt else ''}
    <div class="brand-sortiment-card-link">Se {escape(c["label"].lower())} →</div>
  </a>'''
        sortiment_html = f'''<h2>{escape(brand_label)}-sortimentet forklart</h2>
  <p class="brand-section-lead">{len(sortiment_cards)} kategorier med til sammen {len(products)} produkter -- velg den som passer ditt behov.</p>
  <div class="brand-sortiment-grid">
    {"".join(sortiment_card(c) for c in sortiment_cards)}
  </div>'''

    # -- "30 eller 90 linser?" -- ekte analyse PÅ TVERS av merket, kun bygget
    # hvis vi faktisk har nok robuste 30/90-par (samme underliggende
    # produkt via _pack_size_from_id, ikke ulike produkter). Terskel på
    # minst 2 par -- ett enkelt par er ikke en "analyse", det er bare det
    # samme tallet som allerede står i FAQ-en ("hvilken pakning har lavest
    # pris per linse"). Se Kai sin pastede brief, Fase 11: "Hvis mappingen
    # ikke er sikker: ikke bygg modulen ennå."
    pack_pairs = []
    by_stem: dict[str, dict[int, dict]] = {}
    for r in rows:
        parsed = _pack_size_from_id(r["product"]["id"])
        if parsed and r["lowest"]:
            stem, pack = parsed
            by_stem.setdefault(stem, {})[pack] = r
    for stem, by_pack in by_stem.items():
        if 30 in by_pack and 90 in by_pack:
            r30, r90 = by_pack[30], by_pack[90]
            p30 = r30["lowest"]["price_nok"] / 30
            p90 = r90["lowest"]["price_nok"] / 90
            pack_pairs.append({"name": r30["product"]["name"], "p30": p30, "p90": p90})
    pack_30_90_html = ""
    if len(pack_pairs) >= 2:
        n_90_cheaper = sum(1 for pp in pack_pairs if pp["p90"] < pp["p30"])
        best_example = max(pack_pairs, key=lambda pp: abs(pp["p30"] - pp["p90"]))
        p30_txt = f'{best_example["p30"]:.1f}'.replace(".", ",")
        p90_txt = f'{best_example["p90"]:.1f}'.replace(".", ",")
        diff_pct = round(abs(best_example["p30"] - best_example["p90"]) / best_example["p30"] * 100)
        cheaper_word = "90-pakningen" if best_example["p90"] < best_example["p30"] else "30-pakningen"
        pack_30_90_html = f'''<h2>30 eller 90 linser?</h2>
  <div class="brand-3090-card">
    <p>For {n_90_cheaper} av {len(pack_pairs)} sammenlignbare {escape(brand_label)}-produkter har 90-pakningen lavere pris per linse enn tilsvarende 30-pakning akkurat nå. Eksempel -- {escape(best_example["name"])}:</p>
    <div class="brand-3090-grid">
      <div class="brand-3090-tile"><div class="brand-3090-tile-icon" style="background:var(--sky-tint);color:var(--sky);" aria-hidden="true">{BOX_ICON_SVG}</div><strong>{p30_txt} kr</strong><span>30-pack, per linse</span></div>
      <div class="brand-3090-tile"><div class="brand-3090-tile-icon" style="background:var(--mint-tint);color:var(--mint);" aria-hidden="true">{BOX_ICON_SVG}</div><strong>{p90_txt} kr</strong><span>90-pack, per linse</span></div>
      <div class="brand-3090-tile"><div class="brand-3090-tile-icon" style="background:var(--amber-tint);color:var(--amber);" aria-hidden="true">{TAG_ICON_SVG}</div><strong>{diff_pct} %</strong><span>Forskjell -- {escape(cheaper_word)} billigst</span></div>
    </div>
    <p class="brand-3090-note">Kun samme underliggende produkt sammenlignet (aldri ulike produkter mot hverandre). Husk å regne med frakt for akkurat det antallet du trenger.</p>
  </div>'''

    # -- "Nyttige ressurser" -- IKKE "Lær mer om {brand}" (Kai sin pastede
    # brief er eksplisitt på dette: guidene handler om kontaktlinser
    # generelt, ikke om merket). Gjenbruker render_guide_tile() (samme
    # funksjon som /guider/-oversikten og forsiden) direkte -- alle 40
    # guider har nå eget foto (se GUIDE_PHOTOS), så dette blir alltid
    # bildekort, ingen egen komponent å vedlikeholde her.
    brand_guide_slugs = ["hvordan-velge-kontaktlinser"]
    if "dagslinser" in category_slugs and "manedslinser" in category_slugs:
        brand_guide_slugs.append("manedslinser-vs-dagslinser")
    elif "toriske-linser" in category_slugs:
        brand_guide_slugs.append("kontaktlinser-med-astigmatisme")
    elif "multifokale-linser" in category_slugs:
        brand_guide_slugs.append("multifokale-kontaktlinser")
    else:
        brand_guide_slugs.append("hvordan-bruke-kontaktlinser")
    brand_guide_slugs.append("bc-forklart")
    brand_guides_html = f'''<h2>Nyttige ressurser</h2>
  <p class="brand-section-lead">Artikler, forklaringer og guider som hjelper deg å ta gode valg.</p>
  <div class="guide-grid">
    {"".join(render_guide_tile(slug, GUIDE_CONTENT[slug]) for slug in brand_guide_slugs if slug in GUIDE_CONTENT)}
  </div>'''

    # -- "Produsent" -- kompakt modul, styrker entity-hierarkiet Produsent
    # -> Merke -> Serie -> Produkt. Kun bygget hvis vi faktisk har en
    # produsent-kobling (BRAND_TO_MANUFACTURER).
    brand_manufacturer_module_html = ""
    if manufacturer_slug:
        mf = MANUFACTURERS[manufacturer_slug]
        brand_manufacturer_module_html = f'''<div class="brand-manufacturer-card">
    <div class="brand-manufacturer-kicker">Produsent</div>
    <div class="brand-manufacturer-name">{escape(mf["name"])}</div>
    <a class="brand-manufacturer-link" href="/produsent/{escape(manufacturer_slug)}/">Les mer om {escape(mf["name"])} →</a>
  </div>'''

    # -- "Om informasjonen på denne siden" -- samme fire-elementer-mønster
    # som Kai sin pastede brief ba om, tekstene er BEVISST identiske med
    # (ikke nye påstander enn) det som allerede står i disclosure-avsnittet
    # og på /slik-sammenligner-vi-priser/ -- "oppdateres daglig", ikke
    # "flere ganger daglig" som brief sitt eksempel foreslo, siden det
    # ville vært en påstand vi ikke kan dokumentere (se rapport til Kai).
    brand_trust_html = f'''<div class="brand-trust">
    <h2>Om informasjonen på denne siden</h2>
    <div class="brand-trust-grid">
      <div class="brand-trust-item"><strong>Produktinformasjon</strong><p>Basert på dokumenterte produsentspesifikasjoner og vår produktdatabase.</p></div>
      <div class="brand-trust-item"><strong>Priser</strong><p>Hentes fra norske nettbutikker og oppdateres daglig.</p></div>
      <div class="brand-trust-item"><strong>Kommersielle lenker</strong><p>Vi kan motta provisjon når du går videre til en butikk. Dette påvirker aldri prisrekkefølgen.</p></div>
      <div class="brand-trust-item"><strong>Sammenligning</strong><p>Pris per linse beregnes fra pakningsstørrelse. Totalpris inkluderer frakt der fraktdata er tilgjengelig.</p></div>
    </div>
    <p class="brand-trust-links">
      <a href="/slik-sammenligner-vi-priser/">Slik sammenligner vi priser →</a>
      <a href="/redaksjonelle-prinsipper/">Redaksjonelle prinsipper →</a>
      <a href="/om-oss/">Om Kontaktlinser.no →</a>
    </p>
  </div>'''

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
<title>{escape(brand_label)} kontaktlinser – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/merke/{brand_slug}/">
{_og_meta(f'{brand_label} kontaktlinser – Sammenlign priser | Kontaktlinser.no', meta_description, f'{BASE_URL}/merke/{brand_slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
{brand_faq_schema}
<style>{SHARED_STYLE}
{GUIDE_TILE_STYLE}
{BRAND_PAGE_STYLE}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(brand_label)}</p>
  <div class="brand-hero">
    <div class="brand-hero-content">
      <div class="brand-hero-row">
        <div class="hero-copy">
          <div class="kicker">Merke</div>
          <h1>{escape(brand_label)}</h1>
          {brand_subtitle_html}
          <p>{brand_intro_sentence}</p>
          <div class="brand-hero-cta-row">
            <a class="brand-hero-cta" href="#produkter">Se alle {escape(brand_label)}-produkter →</a>
            {manufacturer_link_html}
          </div>
        </div>
      </div>
    </div>
    <div class="brand-hero-media" aria-hidden="true">
      <picture>
        <source media="(min-width: 860px)" type="image/webp" srcset="/static/hero/brand-560.webp 560w, /static/hero/brand-840.webp 840w, /static/hero/brand-1120.webp 1120w" sizes="(min-width: 1200px) 560px, 40vw">
        <img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" alt="" width="560" height="385" loading="lazy" decoding="async">
      </picture>
    </div>
    <div class="brand-hero-stats">{brand_hero_stats_html}</div>
  </div>

  {series_nav_html}
  {brand_insight_row_html}

  <h2 id="produkter">Alle {escape(brand_label)}-produkter</h2>
  <div class="filter-row" id="filter-row" role="group" aria-label="Filtrer etter kategori">
    <button class="chip active" data-category="all">Alle kategorier</button>
    {category_chips}
  </div>

  <div class="list-header">
    <h2 id="result-count">{len(products)} produkter</h2>
  </div>

  <div id="product-list" class="product-tile-grid">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>

  {sortiment_html}
  {brand_compare_row_html}
  {pack_30_90_html}
  <div class="brand-faq-wrap">{brand_faq_html}</div>
  {brand_guides_html}
  {brand_manufacturer_module_html}

  <p class="disclosure">
    Vi sorterer alltid etter lavest pris. Vi kan få provisjon når du handler
    via lenkene på produktsidene, men det påvirker ikke prisen du betaler
    eller rangeringen av produkter eller tilbud.
  </p>

  {f'<div style="max-width:720px;margin-top:32px;">{BRAND_CONTENT[brand_slug]}</div>' if brand_slug in BRAND_CONTENT else ""}

  {brand_trust_html}
</div>

<script>
  const filterRow = document.getElementById('filter-row');
  const list = document.getElementById('product-list');

  function applyBrandFilter(category) {{
    const btn = filterRow.querySelector('.chip[data-category="' + category + '"]');
    if (!btn) return;
    filterRow.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    let visible = 0;
    list.querySelectorAll('.product-tile').forEach(card => {{
      const show = category === 'all' || card.dataset.category === category;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
  }}

  // "Sortimentet forklart" sine "Se X →"-kort lenker til
  // #<kategori-slug> -- samme filter-rad som allerede finnes ved
  // produktlisten, ikke en egen side. Kjøres på lasting hvis siden åpnes
  // direkte med et slikt hash (f.eks. fra en ekstern lenke).
  const initialCategory = window.location.hash.replace('#', '');
  if (initialCategory && filterRow.querySelector('.chip[data-category="' + initialCategory + '"]')) {{
    applyBrandFilter(initialCategory);
  }}
  document.querySelectorAll('.brand-sortiment-card').forEach(card => {{
    card.addEventListener('click', () => {{
      applyBrandFilter(card.dataset.category);
      document.getElementById('produkter').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }});
  }});

  filterRow.addEventListener('click', e => {{
    const btn = e.target.closest('.chip');
    if (!btn) return;
    applyBrandFilter(btn.dataset.category);
  }});
</script>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_manufacturer_page(manufacturer_slug: str, brand_counts: dict[str, int], brand_labels: dict[str, str]) -> str:
    """Egen side per produsent (/produsent/{slug}/) -- IKKE det samme som en
    merke-side (/merke/{slug}/): et merke er ett produktnavn (Biofinity), en
    produsent kan stå bak flere merker (CooperVision -> Biofinity, Proclear,
    MyDay, ...). Formålet er en ekte, utgående lenke til produsentens egen
    side (ingen konkurrent i det norske markedet har dette, se research
    2026-08-18) pluss original tekst om produsenten -- ikke bare en
    videresending. brand_counts/brand_labels kommer fra den samme
    utregningen som render_home_page allerede gjør, sendt inn slik at denne
    funksjonen ikke trenger å vite noe om katalog-strukturen selv."""
    data = MANUFACTURERS[manufacturer_slug]
    name = data["name"]

    own_brand_slugs = [s for s in data["brand_slugs"] if s in brand_counts]

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

    brand_cards_html = "\n".join(render_brand_card(s) for s in own_brand_slugs)
    total_products = sum(brand_counts[s] for s in own_brand_slugs)
    brand_names = [brand_labels[s] for s in own_brand_slugs]
    brands_text = brand_names[0] if len(brand_names) == 1 else ", ".join(brand_names[:-1]) + " og " + brand_names[-1]

    meta_description = f"Om {name}, produsenten bak {brands_text} – som produsent, teknologi og lenke til deres offisielle nettside."

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "BreadcrumbList", "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
      {{"@type": "ListItem", "position": 2, "name": "{_json_str(name)}", "item": "{BASE_URL}/produsent/{manufacturer_slug}/"}}
    ]}},
    {{"@type": "Organization", "name": "{_json_str(name)}", "url": "{_json_str(data['official_url'])}"}}
  ]
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(name)} – Produsenten bak {escape(brands_text)} | Kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/produsent/{manufacturer_slug}/">
{_og_meta(f'{name} – Produsenten bak {brands_text}', meta_description, f'{BASE_URL}/produsent/{manufacturer_slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.brand-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
.brand-card {{ display: flex; align-items: center; gap: 10px; min-width: 0; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; box-shadow: var(--card-shadow); }}
.brand-card:hover {{ border-color: var(--blue); }}
.brand-card-badge {{ flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.8rem; }}
.brand-card-info {{ min-width: 0; }}
.brand-card-name {{ font-weight: 600; font-size: 0.88rem; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.brand-card-count {{ font-size: 0.75rem; color: var(--muted); }}
@media (min-width: 560px) {{ .brand-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(name)}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Produsent</div>
      <h1>{escape(name)}</h1>
    </div>
  </div>

  <div style="max-width:720px;font-size:1rem;line-height:1.7;">
    {data["description_html"]}
  </div>

  <p style="margin:20px 0 32px;">
    <a href="{escape(data['official_url'])}" target="_blank" rel="noopener" style="font-weight:600;color:var(--blue-dark);">
      Offisiell nettside: {escape(data['official_url_label'])} ↗
    </a>
  </p>

  <h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.1rem;margin:0 0 16px;">
    {escape(name)}s merker hos oss ({total_products} produkter totalt)
  </h2>
  <div class="brand-grid">
    {brand_cards_html}
  </div>

  <p class="disclosure" style="margin-top:32px;">
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste og har ingen avtale med
    {escape(name)}. Lenken til deres nettside over er kun en informativ henvisning, ikke
    en annonse eller et samarbeid.
  </p>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


# Delt mellom forsiden og guide-sidene (2026-09-25): guide-sidene får mest
# organisk trafikk, men mange forlater siden rett etter å ha lest svaret --
# søkeboksen gir dem en naturlig neste handling ("finn laveste pris på
# linsene mine") uten å ligge i veien for selve guiden.
LENS_SEARCH_STYLE = """
.search-row { position: relative; }
.search-icon { position: absolute; left: 18px; top: 50%; transform: translateY(-50%); width: 20px; height: 20px; color: var(--muted); pointer-events: none; }
.search-input { width: 100%; font-family: 'Inter', sans-serif; font-size: 1.05rem; padding: 16px 100px 16px 48px; border: 1px solid var(--blue); border-radius: 14px; background: white; box-shadow: var(--card-shadow); transition: box-shadow 0.15s, border-color 0.15s; }
.search-input:hover { border-color: var(--blue-dark); }
.search-input:focus { outline: none; border-color: var(--blue-dark); box-shadow: 0 0 0 4px var(--blue-tint); }
.search-row:focus-within .search-icon { color: var(--blue); }
.search-btn { position: absolute; right: 6px; top: 6px; bottom: 6px; padding: 0 20px; border: none; border-radius: 10px; background: var(--blue); color: white; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 0.92rem; cursor: pointer; transition: background-color 0.15s; }
.search-btn:hover { background: var(--blue-dark); }
.search-suggestions { display: none; position: absolute; top: calc(100% + 6px); left: 0; right: 0; background: white; border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 12px 28px rgba(11, 37, 69, 0.14); max-height: 380px; overflow-y: auto; z-index: 20; }
.search-suggestion { display: flex; align-items: center; gap: 10px; padding: 10px 14px; text-decoration: none; color: var(--ink); border-bottom: 1px solid var(--border); }
.search-suggestion:last-child { border-bottom: none; }
.search-suggestion:hover { background: var(--mist); }
.search-suggestion .product-thumb { width: 36px; height: 36px; font-size: 0.68rem; }
.search-suggestion-name { font-weight: 600; font-size: 0.86rem; }
.search-suggestion-meta { font-size: 0.75rem; color: var(--muted); }
.search-no-match { padding: 14px; font-size: 0.84rem; color: var(--muted); }
.guide-cta { background: var(--blue-tint); border: 1px solid var(--border); border-radius: 16px; padding: 18px 18px 16px; margin: 22px 0; }
.guide-cta-compact { padding: 14px 16px; }
.guide-cta-title { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.05rem; color: var(--ink); margin: 0 0 4px; }
.guide-cta-compact .guide-cta-title { margin-bottom: 10px; }
.guide-cta-text { font-size: 0.88rem; line-height: 1.5; color: var(--muted); margin: 0 0 12px; }
.guide-cta .search-input { font-size: 1rem; padding: 14px 92px 14px 46px; }
.guide-cta .search-icon { left: 16px; width: 18px; height: 18px; }
.guide-cta-links { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; margin-top: 12px; font-size: 0.82rem; color: var(--muted); }
.guide-cta-links a { padding: 4px 10px; border: 1px solid var(--border); border-radius: 999px; background: white; color: var(--ink); text-decoration: none; font-weight: 600; }
.guide-cta-links a:hover { border-color: var(--blue); color: var(--blue); }
"""

LENS_SEARCH_JS = """
(function () {
  // Kjøres fra TOPBAR_HTML, som ligger tidlig i <body> -- FØR forsidens
  // egen .search-row (hero-søkefeltet) er parset inn i DOM-en på sider
  // som har en slik ekstra rad. Uten denne DOMContentLoaded-sjekken
  // returnerte scriptet tidlig (rows.length === 0 på det tidspunktet det
  // kjørte) og bandt ALDRI noen event-lyttere på forsidens søkefelt --
  // oppdaget 2026-09-27 (Kai: "søkefunksjon virker ikke nå! på
  // startsiden"). Sider der .search-row allerede finnes når scriptet
  // kjører (readyState !== 'loading') kjører init() umiddelbart som før.
  function init() {
  var rows = document.querySelectorAll('.search-row');
  if (!rows.length) return;

  // Forsiden har indeksen innebygd som skjult JSON; guide-sidene henter den
  // først når noen faktisk fokuserer søkefeltet (holder guide-HTML-en lett).
  var dataPromise = null;
  function loadData() {
    if (dataPromise) return dataPromise;
    var inlineProducts = document.getElementById('product-search-data');
    if (inlineProducts) {
      var inlineLabels = document.getElementById('private-label-search-data');
      dataPromise = Promise.resolve(
        JSON.parse(inlineProducts.textContent).concat(inlineLabels ? JSON.parse(inlineLabels.textContent) : [])
      );
    } else {
      dataPromise = fetch('/data/search-index.json')
        .then(function (r) { return r.json(); })
        .catch(function () { dataPromise = null; return []; });
    }
    return dataPromise;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function track(row, name, source) {
    var guide = row.getAttribute('data-guide');
    if (!guide) return;
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({event: 'guide_search_click', guide: guide, product: name, source: source});
  }

  rows.forEach(function (row) {
    var input = row.querySelector('.search-input');
    var suggestions = row.querySelector('.search-suggestions');
    var button = row.querySelector('.search-btn');

    function hide() { suggestions.style.display = 'none'; suggestions.innerHTML = ''; }

    function render(q) {
      if (!q) { hide(); return; }
      loadData().then(function (all) {
        if (input.value.trim().toLowerCase() !== q) return;
        var matches = all.filter(function (item) { return item.search.indexOf(q) !== -1; }).slice(0, 8);
        if (matches.length === 0) {
          suggestions.innerHTML = '<div class="search-no-match">Ingen treff. Prøv et annet merke eller produktnavn.</div>';
          suggestions.style.display = 'block';
          return;
        }
        suggestions.innerHTML = matches.map(function (item) {
          var thumb = item.image
            ? '<div class="product-thumb"><img src="' + esc(item.image) + '" alt="" loading="lazy"></div>'
            : '<div class="product-thumb">' + esc((item.badge || item.meta).slice(0, 2).toUpperCase()) + '</div>';
          return '<a class="search-suggestion" href="' + esc(item.href) + '" data-name="' + esc(item.name) + '">' + thumb +
            '<div><div class="search-suggestion-name">' + esc(item.name) + '</div>' +
            '<div class="search-suggestion-meta">' + esc(item.meta) + '</div></div></a>';
        }).join('');
        suggestions.style.display = 'block';
      });
    }

    input.addEventListener('input', function () { render(input.value.trim().toLowerCase()); });
    input.addEventListener('focus', function () {
      loadData();
      if (input.value.trim()) render(input.value.trim().toLowerCase());
    });
    document.addEventListener('click', function (e) { if (!row.contains(e.target)) suggestions.style.display = 'none'; });
    suggestions.addEventListener('click', function (e) {
      var link = e.target.closest('.search-suggestion');
      if (link) track(row, link.getAttribute('data-name'), 'suggestion');
    });

    // "Søk"-knappen/Enter går til det beste treffet, samme resultat som å
    // klikke første forslag -- vi har ingen egen søkeresultat-side, kun
    // autofullføring, så dette er nærmeste naturlige "søk"-handling.
    function goToBestMatch() {
      var q = input.value.trim().toLowerCase();
      if (!q) { input.focus(); return; }
      loadData().then(function (all) {
        var best = all.find(function (item) { return item.search.indexOf(q) !== -1; });
        if (best) { track(row, best.name, 'button'); window.location.href = best.href; }
        else { render(q); }
      });
    }
    button.addEventListener('click', goToBestMatch);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); goToBestMatch(); }
    });
  });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""

# _topbar_html() (definert langt tidligere i filen, rett der TOPBAR_HTML
# historisk har ligget) refererer til LENS_SEARCH_STYLE/LENS_SEARCH_JS --
# selve kallet må derfor skje HER, etter at begge finnes, ikke der funksjonen
# er definert.
TOPBAR_HTML = _topbar_html()
TOPBAR_HTML_NO_SEARCH = _topbar_html(show_search=False)


# Søkeord per tilbehørskategori. Både æøå og ascii-varianter, siden mange skriver
# "oyedraper"/"linsevaeske" uten spesialtegn. Kun brukt til å MATCHE (aldri vist).
SOLUTION_SEARCH_TERMS = {
    "linsevaeske": "linsevæske linsevaeske",
    "oyedraper": "øyedråper oyedraper øyepleie oyepleie",
    "tilbehor": "tilbehør tilbehor etui hjelpemidler",
}


def build_search_index(products: list[dict], private_labels: list[dict] | None = None, solutions: list[dict] | None = None, families: list[dict] | None = None) -> list[dict]:
    """Søkeindeksen som driver autofullføringen (forside: innebygd som
    skjult JSON; guide-sider: hentes fra /data/search-index.json).
    "meta" er den synlige undertekst-linjen i forslagene -- kjedenavnet
    skal IKKE vises der (samme regel som resten av siden), men "search"
    (kun brukt til å MATCHE, aldri vist) beholder det, siden en bruker som
    søker "Synsam" fortsatt bør finne EyeQ."""
    entries = [
        {
            "name": p["name"],
            "meta": p["brand_label"],
            "href": f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/',
            "image": _product_image(p),
            "search": f'{p["name"]} {p["brand_label"]}'.lower(),
        }
        for p in products
    ]
    entries += [
        {
            "name": p["name"],
            "meta": f'{p["brand_label"]} · {SOLUTION_CATEGORIES[p["solution_category"]]["label"]}',
            "href": f'/{p["solution_category"]}/{p["brand_slug"]}/{p["slug"]}/',
            "image": _product_image(p),
            "search": f'{p["name"]} {p["brand_label"]} {SOLUTION_SEARCH_TERMS.get(p["solution_category"], "")}'.lower(),
        }
        for p in (solutions or [])
    ]
    entries += [
        {
            "name": label["name"],
            "meta": "Eget merkenavn",
            "href": f'/private-label/{label["slug"]}/',
            "image": None,
            "search": f'{label["name"]} {label["chain"]}'.lower(),
            # "badge" (2026-09-29, Kai: "ser vi ikke har slikt lite ikon på
            # de nye.." -> "det gjelder alle Eget merkenavn") -- uten dette
            # falt JS-en (se LENS_SEARCH_JS) tilbake til å ta de 2 første
            # bokstavene av "meta" for søkeforslagets fallback-ikon når
            # "image" er null (alltid null her, med vilje -- vi viser aldri
            # det ekte produktets bilde under et privat merkenavn). Siden
            # "meta" er den SAMME generiske teksten ("Eget merkenavn") for
            # alle 84 private label-produkter, ga det samme meningsløse
            # "EG"-ikon på tvers av ALLE av dem -- ikke en TrueLens-spesifikk
            # feil, men en eksisterende feil i alle fire opprinnelige kjeder
            # også, først synlig nå som det femte settet gjorde mønsteret
            # tydelig. "badge" gir i stedet et produktrelevant fallback-ikon
            # fra selve merkenavnet (f.eks. "TrueLens Premium Daily" -> "TR",
            # "iWear Oxygen XR" -> "IW"), samme prinsipp som ekte produkter
            # allerede får via sin egen brand_label.
            "badge": label["name"][:2].upper(),
        }
        for label in (private_labels or [])
    ]
    # Serie-sider (/serie/{slug}/) manglet lenge enhver innkommende lenke utenom
    # sitemap.xml (se generate_pages.py sin kommentar om "Oppdaget - ikke
    # indeksert" i Search Console 2026-09-18) -- lagt til her 2026-09-27 slik at
    # et søk på f.eks. "acuvue moist serie" faktisk finner samle-siden.
    entries += [
        {
            "name": f'{fam["name"]}-serien',
            "meta": f'Serie · {fam["count"]} varianter',
            "href": f'/serie/{fam["slug"]}/',
            "image": fam.get("image"),
            "search": f'{fam["name"]} serie serien'.lower(),
        }
        for fam in (families or [])
    ]
    return entries


def render_guide_search_card(guide_slug: str, compact: bool = False) -> str:
    title = "Bruker du kontaktlinser? Finn laveste pris"
    row = f"""<div class="search-row" data-guide="{escape(guide_slug)}">
      <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/></svg>
      <input type="search" class="search-input" placeholder="Søk linse eller merke" aria-label="Søk etter linse eller merke" autocomplete="off">
      <button type="button" class="search-btn">Søk</button>
      <div class="search-suggestions"></div>
    </div>"""
    if compact:
        return f"""<aside class="guide-cta guide-cta-compact" aria-label="Sammenlign priser" data-nosnippet>
    <p class="guide-cta-title">{title}</p>
    {row}
  </aside>"""
    return f"""<aside class="guide-cta" aria-label="Sammenlign priser" data-nosnippet>
    <p class="guide-cta-title">{title}</p>
    <p class="guide-cta-text">Søk på linsen eller merket du bruker – vi sammenligner norske nettbutikker og lar deg se prisen både med og uten frakt.</p>
    {row}
    <div class="guide-cta-links">
      <span>Eller bla etter type:</span>
      <a href="/kontaktlinser/dagslinser/">Dagslinser</a>
      <a href="/kontaktlinser/manedslinser/">Månedslinser</a>
      <a href="/kontaktlinser/toriske-linser/">Toriske</a>
      <a href="/kontaktlinser/multifokale-linser/">Multifokale</a>
      <a href="/#merker">Alle merker</a>
    </div>
  </aside>"""


def render_home_page(catalog: dict, now: datetime | None = None, private_labels: list[dict] | None = None, solution_products: list[dict] | None = None, families: list[dict] | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    # Søkeindeksen (under) driver kun søkeforslag-dropdownen -- forsiden
    # viser IKKE lenger et fullt produktgrid (fjernet 2026-08-15). Data
    # sendes som skjult JSON i stedet for synlige kort, slik at søket
    # fortsatt dekker alt uten at forsidens HTML/DOM må inneholde hvert
    # eneste produkt (dårlig for sidevekt og for topisk SEO-fokus).
    search_index_json = json.dumps(
        build_search_index(catalog["products"], solutions=solution_products), ensure_ascii=False
    ).replace("</", "<\\/")
    private_label_search_index_json = json.dumps(
        build_search_index([], private_labels, families=families), ensure_ascii=False
    ).replace("</", "<\\/")

    brand_counts: dict[str, int] = {}
    brand_labels: dict[str, str] = {}
    # Ett representativt produktbilde per merke -- til de nye, større
    # merke-kortene på mobil (se render_brand_card under). Foretrekker et
    # produkt som faktisk HAR et bilde (manuelt kuratert eller lisensiert
    # feed-bilde via _product_image) fremfor bare det første produktet i
    # katalog-rekkefølgen, som kunne vært et uten bilde i det hele tatt.
    brand_sample_image: dict[str, str] = {}
    # Antall DISTINKTE forhandlere som faktisk har merket på lager -- brukt
    # til å sortere Merker-seksjonen (2026-08-30, etter brukerens ønske om
    # en "mest populære i Norge"-rekkefølge). Vi har ingen egen trafikk å
    # basere dette på ennå, og et par innlimte "AI-genererte populæritets-
    # tabeller" samme dag inneholdt begge verifiserbart uriktige påstander
    # (bl.a. iWear feilaktig knyttet til Interoptik, og everclear ELITE
    # feilaktig kalt Lensway-eksklusiv når den faktisk selges hos BÅDE
    # Lenson og Lensway) -- forkastet som datagrunnlag, samme prinsipp som
    # tidligere avviste AI-dokumenter i dette prosjektet. Bredde i faktisk
    # forhandlerdekning er derimot ekte data vi allerede har: forhandlere
    # velger selv hva de fører basert på egne salgstall, så et merke som
    # føres av mange uavhengige forhandlere er et reelt (om enn indirekte)
    # etterspørselssignal -- IKKE bare et tall på hvor mange pakningsstørr-
    # elser/varianter VI har lagt inn av merket.
    brand_retailers: dict[str, set[str]] = {}
    product_by_id: dict[str, dict] = {}
    for p in catalog["products"]:
        product_by_id[p["id"]] = p
        brand_counts[p["brand_slug"]] = brand_counts.get(p["brand_slug"], 0) + 1
        brand_labels[p["brand_slug"]] = p["brand_label"]
        if p["brand_slug"] not in brand_sample_image:
            img = _product_image(p)
            if img:
                brand_sample_image[p["brand_slug"]] = img
        retailers = brand_retailers.setdefault(p["brand_slug"], set())
        for o in p.get("offers", []):
            if o.get("in_stock"):
                retailers.add(o["retailer"])

    def render_brand_card(slug: str) -> str:
        label = brand_labels[slug]
        count = brand_counts[slug]
        n_label = "produkt" if count == 1 else "produkter"
        extra_cls, badge_content = _brand_badge(slug, label)
        badge_class = ("brand-card-badge " + extra_cls).strip()
        sample_image = brand_sample_image.get(slug)
        card_cls = "brand-card has-photo" if sample_image else "brand-card"
        photo_html = (f'<div class="brand-card-photo">{_img_tag(sample_image, label)}</div>'
                      if sample_image else "")
        return f"""<a class="{card_cls}" href="/merke/{escape(slug)}/">
  {photo_html}
  <div class="{badge_class}">{badge_content}</div>
  <div class="brand-card-info">
    <div class="brand-card-name">{escape(label)}</div>
    <div class="brand-card-count">{count} {n_label}</div>
  </div>
</a>"""

    def render_private_label_chain_card(chain: str, count: int, sample_image: str | None,
                                         illustration_html: str | None) -> str:
        # Kjedenavnet (Synsam/Brilleland/Specsavers/Coptikk) og kjedens egen
        # logo skal IKKE vises her -- bruker ønsker (2026-08-30) at disse
        # seriene fremstår som egne merker på linje med ekte linsemerker.
        # Kobling til kjeden ligger fortsatt på /private-label/ (egen
        # oversiktsside dedikert til akkurat den forklaringen). Illustrasjon
        # (egen tegnet grafikk, se render_private_label_illustration) vinner
        # alltid over et lånt bilde av det ekte produktet -- iWear/Brilleland
        # har ingen illustrasjonspakke ennå og faller derfor fortsatt tilbake
        # til det lånte produktbildet + en initial-badge.
        n_label = "eget merke" if count == 1 else "egne merker"
        subbrand = PRIVATE_LABEL_SUBBRANDS.get(chain, chain)
        subbrand_logo = PRIVATE_LABEL_SUBBRAND_LOGOS.get(subbrand)
        if illustration_html:
            card_cls = "brand-card has-photo"
            photo_html = f'<div class="brand-card-photo"><div class="pli-frame">{illustration_html}</div></div>'
            badge_html = (f'<div class="brand-card-badge has-logo">'
                          f'<img class="brand-logo-img" src="/static/logos/{subbrand_logo}" alt="" loading="lazy"></div>'
                          if subbrand_logo else "")
        elif sample_image:
            card_cls = "brand-card has-photo"
            photo_html = f'<div class="brand-card-photo">{_img_tag(sample_image, subbrand)}</div>'
            badge_html = f'<div class="brand-card-badge">{escape(subbrand[:2].upper())}</div>'
        else:
            card_cls = "brand-card"
            photo_html = ""
            badge_html = f'<div class="brand-card-badge">{escape(subbrand[:2].upper())}</div>'
        return f"""<a class="{card_cls}" href="/merke/{escape(subbrand.lower())}/">
  {photo_html}
  {badge_html}
  <div class="brand-card-info">
    <div class="brand-card-name">{escape(subbrand)}</div>
    <div class="brand-card-count">{count} {n_label}</div>
  </div>
</a>"""

    chain_counts: dict[str, int] = {}
    chain_sample_image: dict[str, str] = {}
    chain_illustration: dict[str, str] = {}
    for label in (private_labels or []):
        chain = label["chain"]
        chain_counts[chain] = chain_counts.get(chain, 0) + 1
        if chain not in chain_illustration:
            html = render_private_label_illustration(chain, label["slug"])
            if html:
                chain_illustration[chain] = html
        if chain not in chain_sample_image:
            real_product = product_by_id.get(label.get("real_product_id"))
            if real_product:
                img = _product_image(real_product)
                if img:
                    chain_sample_image[chain] = img
    any_pli_illustration = bool(chain_illustration)
    pli_disclaimer_note = (
        '<p style="margin:10px 0 0;font-size:0.72rem;color:var(--muted);">'
        'Noen merker over vises med en egen illustrasjon i stedet for et ekte produktbilde. '
        '<a href="/om-produktillustrasjoner/" style="color:var(--muted);text-decoration:underline;">Les hvorfor →</a></p>'
        if any_pli_illustration else ""
    )

    # Sorteringshistorikk: 15.08 manuell pinning av 3 merker -> 30.08 reell
    # forhandlerbredde-sortering (se git-historikk) -> 30.08 samme dag,
    # private label-seriene smeltet inn i én felles rangering i stedet for
    # en egen blokk øverst.
    #
    # 30.08 (samme dag, ny runde): bruker ønsket en tredje tilnærming --
    # egne trafikktall finnes ikke ennå (ny side, lite trafikk), så vi
    # "lar oss inspirere av" lenspricer.no sin faktiske, observerte
    # forsiderekkefølge (lest av alt-tekst på deres bilderutenett
    # 2026-08-30 -- IKKE en påstand om popularitet/salgstall, bare hva de
    # faktisk viser, verifiserbart ved å besøke siden), med et par bevisste
    # ombytter (Acuvue/Dailies og Biomedics/ULTRA) slik at det ikke er en
    # 1:1-kopi. IKKE nevnt/vist noe sted på selve siden -- ren intern
    # sorteringslogikk, bekreftet av bruker at det skal forbli slik.
    #
    # 31.08: opprinnelig tenkt midlertidig (erstattes av egne trafikktall
    # etter ~3 måneder), men bruker bestemte at LENSPRICER_INSPIRED_ORDER
    # i stedet skal stå FAST ut 2026 -- ingen automatisk overgang til
    # trafikkbasert sortering er planlagt lenger (uansett om GA4/GTM-
    # statistikk skulle bli satt opp i mellomtiden). Endre kun rangeringen
    # når bruker eksplisitt ber om det, ikke på en tidsfrist.
    # Merker vi har som IKKE står i denne listen (enten fordi lenspricer.no
    # ikke fører dem, eller fordi navnet deres ikke tydelig kunne kobles
    # til et av våre merker, f.eks. deres "Lumiere"/"Freshtech") faller
    # tilbake til den samme forhandlerbredde-sorteringen som før.
    card_items: list[tuple[int, int, int, str, str]] = []
    unranked = len(LENSPRICER_INSPIRED_ORDER)
    for slug in brand_counts:
        rank = _LENSPRICER_RANK.get(slug, unranked)
        card_items.append((
            rank, -len(brand_retailers.get(slug, ())), -brand_counts[slug], brand_labels[slug],
            render_brand_card(slug),
        ))
    for chain, count in chain_counts.items():
        subbrand = PRIVATE_LABEL_SUBBRANDS.get(chain, chain)
        rank = _LENSPRICER_RANK.get(subbrand.lower(), unranked)
        card_items.append((
            rank, -1, -count, subbrand,
            render_private_label_chain_card(chain, count, chain_sample_image.get(chain), chain_illustration.get(chain)),
        ))
    card_items.sort(key=lambda item: item[:4])
    brand_cards_html = "\n".join(item[4] for item in card_items)

    def render_category_row(slug: str, category: dict) -> str:
        icon = CATEGORY_ICONS.get(slug, "")
        color = CATEGORY_COLORS.get(slug, "blue")
        tagline = CATEGORY_TAGLINES.get(slug, "")
        bg = CATEGORY_BG.get(slug)
        bg_html = (
            f'<img class="category-row-bg" src="/static/categories/bg-{bg}-320.webp" '
            f'srcset="/static/categories/bg-{bg}-320.webp 320w, /static/categories/bg-{bg}-613.webp 613w" '
            f'sizes="(min-width: 1024px) 230px, (min-width: 700px) 340px, 200px" '
            f'alt="" width="613" height="273" loading="lazy" decoding="async">'
        ) if bg else ""
        return f"""<a class="category-row cat-{escape(color)}" href="/kontaktlinser/{escape(slug)}/">
  {bg_html}
  <div class="category-row-icon" style="background:var(--{color}-tint);color:var(--{color});">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">{icon}</svg>
  </div>
  <div class="category-row-text">
    <div class="category-row-label">{escape(category["label"])}</div>
    <div class="category-row-desc">{escape(tagline)}</div>
  </div>
  <span class="category-row-arrow" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></span>
</a>"""

    category_rows_html = "\n".join(
        render_category_row(slug, category) for slug, category in catalog["categories"].items()
    )

    guide_cards_html = "\n".join(render_guide_tile(slug, g) for slug, g in GUIDE_CONTENT.items())

    n_retailers = len({o["retailer"] for p in catalog["products"] for o in p["offers"]})
    n_products = len(catalog["products"])
    home_faq_html, home_faq_schema = _render_faq_block(HOME_FAQ)

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Billige kontaktlinser – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="Sammenlign priser på kontaktlinser fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
<link rel="canonical" href="{BASE_URL}/">
{_og_meta('Billige kontaktlinser – Sammenlign priser | Kontaktlinser.no', 'Sammenlign priser på kontaktlinser fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.', BASE_URL + '/')}
{home_faq_schema}
{FONT_LINKS}
<link rel="preload" as="image" type="image/webp" media="(min-width: 1024px)" fetchpriority="high" imagesrcset="/static/hero/eye-560.webp 560w, /static/hero/eye-840.webp 840w, /static/hero/eye-1120.webp 1120w" imagesizes="(min-width: 1200px) 540px, 42vw">
<style>{SHARED_STYLE}
{PRIVATE_LABEL_ILLUSTRATION_STYLE}
.hero-panel {{ padding: 0; }}
.hero {{
  position: relative;
  padding: 8px 0 24px;
}}
.hero-content {{ position: relative; z-index: 2; display: flex; flex-direction: column; gap: 16px; }}
.hero-media {{ display: none; }}
.hero-subtext {{ margin: 0; color: var(--muted); font-size: 0.94rem; max-width: 480px; }}
/* Søkefeltet er sidens viktigste element: tykk blå kant, tydelig fokusring, blå knapp. */
.hero .search-input {{ border: 2px solid var(--blue); border-radius: 16px; padding-top: 17px; padding-bottom: 17px; box-shadow: 0 8px 24px rgba(37, 99, 235, 0.14); }}
.hero .search-input:focus {{ border-color: var(--blue-dark); box-shadow: 0 0 0 5px rgba(37, 99, 235, 0.22), 0 8px 24px rgba(37, 99, 235, 0.14); }}
.hero .search-btn {{ right: 8px; top: 8px; bottom: 8px; border-radius: 11px; }}
@media (max-width: 699px) {{
  .hero .search-input {{ font-size: 1rem; padding-left: 44px; padding-right: 84px; }}
  .hero .search-icon {{ left: 15px; }}
  .hero .search-btn {{ padding: 0 16px; }}
}}
.trust-card {{ display: flex; gap: 14px; align-items: flex-start; background: var(--blue-tint); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
.trust-card-icon {{ flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%; background: white; display: flex; align-items: center; justify-content: center; color: var(--blue); box-shadow: var(--card-shadow); }}
.trust-card-icon svg {{ width: 20px; height: 20px; }}
.trust-card-title {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.95rem; margin: 0 0 4px; }}
.trust-card-text {{ font-size: 0.84rem; color: var(--muted); line-height: 1.5; margin: 0; }}
.trust-strip {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px; margin: 40px 0 0; box-shadow: var(--card-shadow); }}
.trust-item {{ display: flex; align-items: center; gap: 10px; }}
.trust-item-icon {{ flex-shrink: 0; width: 34px; height: 34px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; }}
.trust-item-icon svg {{ width: 17px; height: 17px; }}
.trust-item strong {{ display: block; font-family: 'Space Grotesk', sans-serif; font-size: 1rem; color: var(--ink); }}
.trust-item span {{ font-size: 0.75rem; color: var(--muted); }}
.section-header {{ display: flex; align-items: baseline; justify-content: space-between; margin: 32px 0 12px; scroll-margin-top: 20px; }}
.section-header:first-of-type {{ margin-top: 0; }}
.section-header h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0; }}
.category-rows {{ display: flex; flex-direction: column; gap: 10px; }}
.category-row {{ --cat-bg: #EFF6FF; --cat-border: #D6E4FB; --cat-accent: var(--blue); position: relative; overflow: hidden; isolation: isolate; display: flex; align-items: center; gap: 12px; min-height: 76px; text-decoration: none; color: var(--ink); background: var(--cat-bg); border: 1px solid var(--cat-border); border-radius: 16px; padding: 12px 14px; box-shadow: var(--card-shadow); transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s; }}
.category-row.cat-blue {{ --cat-bg: #EFF6FF; --cat-border: #D6E4FB; --cat-accent: #2563EB; }}
.category-row.cat-amber {{ --cat-bg: #FFFBEB; --cat-border: #F4E6BE; --cat-accent: #D9A02B; }}
.category-row.cat-sky {{ --cat-bg: #EEF5FF; --cat-border: #D3E3F8; --cat-accent: #4F8FE8; }}
.category-row.cat-lavender {{ --cat-bg: #F5F0FF; --cat-border: #E1D8F6; --cat-accent: #8B7FD6; }}
.category-row.cat-coral {{ --cat-bg: #FFF2F4; --cat-border: #F6D6DC; --cat-accent: #E8637A; }}
.category-row:hover, .category-row:focus-visible {{ border-color: var(--cat-accent); }}
/* Bakgrunnsbildet ligger bak innholdet og fader ut mot venstre, så teksten alltid står på den lyse pastellen. */
.category-row-bg {{ position: absolute; top: 0; right: 0; height: 100%; width: 52%; z-index: -1; object-fit: cover; object-position: 100% 50%; pointer-events: none; -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 45%); mask-image: linear-gradient(90deg, transparent 0, #000 45%); }}
.category-row-icon {{ flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(11, 37, 69, 0.08); }}
.category-row-icon svg {{ width: 20px; height: 20px; }}
.category-row-text {{ flex: 1; min-width: 0; max-width: 58%; }}
.category-row-label {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.95rem; }}
.category-row-desc {{ font-size: 0.8rem; font-weight: 500; color: #475569; margin-top: 2px; line-height: 1.35; }}
/* Pil: alltid synlig (liten) på mobil/touch, vises ved hover på desktop */
.category-row-arrow {{ position: absolute; right: 10px; top: 50%; transform: translateY(-50%); width: 28px; height: 28px; border-radius: 50%; background: rgba(255, 255, 255, 0.85); color: var(--cat-accent); display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 4px rgba(11, 37, 69, 0.12); }}
.category-row-arrow svg {{ width: 14px; height: 14px; }}
.brand-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
.brand-card {{ display: flex; align-items: center; gap: 10px; min-width: 0; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; box-shadow: var(--card-shadow); }}
.brand-card:hover {{ border-color: var(--blue); }}
.brand-card-badge {{ flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.8rem; }}
.brand-card-info {{ min-width: 0; }}
.brand-card-name {{ font-weight: 600; font-size: 0.88rem; line-height: 1.25; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.brand-card-count {{ font-size: 0.75rem; color: var(--muted); }}
.brand-card-photo {{ display: none; }}
{GUIDE_TILE_STYLE}
/* Merke-kortene: byttet fra en liten sirkel-logo til et større produktbilde
   (2026-08-30, etter brukerens ønske om å ligne lenspricer.no sin
   mobilside). Opprinnelig KUN under 700px (PC beholdt den kompakte
   logo+navn-raden), men bruker ba samme dag om at det bildeførte kortet
   skal gjelde på PC også -- disse reglene er derfor UTEN media-query,
   gjelder alle bredder. Kort UTEN et bilde (sample_image manglet)
   beholder den vanlige logo-sirkel-raden uansett bredde -- ingen tomt/
   knekt kort.
   Badgen (logo/initial) var opprinnelig skjult her (display:none). Prøvde
   2026-08-30 en absolutt posisjonert "chip" oppå produktbildet (etter et
   mockup brukeren viste) -- reversert samme dag: brukeren så resultatet
   live og syntes det så dårlig ut (badgen ble for ofte for smal/kuttet av
   for lange merkenavn/logo-proporsjoner, se skjermbilde). Tilbake til
   display:none -- kort med bilde viser nå KUN bilde + navn/antall under,
   ingen logo-overlay. Samme endring avdekket og fikset et reelt brukket
   kort samtidig (uendret av denne reverseringen): private label-kjedenes
   kort (EyeQ/iWear/Easyvision/Ascend) hadde ALDRI fått .has-photo (ingen
   sample_image var regnet ut for dem) -- på mobil falt de tilbake til den
   gamle smale rad-layouten med en 52px logo-badge, som klemte navnet ned
   til 1-4 bokstaver ("E...", "i...", "Asc..."). Disse har fortsatt et ekte
   produktbilde/illustrasjon, bare uten logo-overlayen oppå. */
.brand-card.has-photo {{ position: relative; flex-direction: column; align-items: stretch; gap: 0; padding: 0; overflow: hidden; }}
.brand-card.has-photo .brand-card-photo {{ display: flex; align-items: center; justify-content: center; overflow: hidden; width: 100%; aspect-ratio: 4 / 3; background: var(--mist); }}
.brand-card.has-photo .brand-card-photo img {{ width: 100%; height: 100%; object-fit: contain; padding: 10px; box-sizing: border-box; }}
.brand-card.has-photo .brand-card-photo .pli-frame {{ width: 100%; aspect-ratio: 560 / 225; container-type: inline-size; }}
.brand-card.has-photo .brand-card-badge {{ display: none; }}
.brand-card.has-photo .brand-card-info {{ padding: 12px 14px 14px; }}
.brand-card.has-photo .brand-card-name {{ font-size: 0.98rem; white-space: normal; }}
.mobile-only-block {{ display: none; }}
@media (max-width: 699px) {{
  .trust-card {{ display: none; }}
  /* Kategorier flyttet under Merker på mobil, og selve "Merker"-
     overskriften skjules helt -- rett fra søk til merke-kortene, samme
     mønster som lenspricer.no sin mobilside (brukerens eget ønske,
     2026-08-30). To kopier av kategori-blokken finnes i markupen
     (desktop-only-block inni hero-panel, mobile-only-block rett etter
     merke-rutenettet) -- kun CSS-display skiller dem, ingen JS. PC er
     dermed fullstendig urørt: samme markup, samme klasser, disse reglene
     gjelder kun under 700px. */
  #merker {{ display: none; }}
  .desktop-only-block {{ display: none; }}
  .mobile-only-block {{ display: block; }}
}}
@media (min-width: 560px) {{ .brand-grid {{ grid-template-columns: repeat(3, 1fr); }} .trust-strip {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (min-width: 1024px) {{
  .brand-grid {{ grid-template-columns: repeat(4, 1fr); }}
  .search-input {{ padding: 18px 120px 18px 52px; font-size: 1.15rem; }}
  .search-icon {{ left: 22px; width: 22px; height: 22px; }}
  .search-btn {{ padding: 0 26px; font-size: 0.98rem; }}

  /* Kompakt hero (ca. 360-400 px): lyst kort, bildet glir inn fra høyre med en
     myk maske mot venstre, slik at det ikke ser ut som to separate bokser.
     .hero-media får overflow:hidden KUN på seg selv (ikke på .hero), ellers
     ville søkeforslagene bli klippet av kortkanten. */
  .hero-panel {{ background: none; border: none; padding: 0; box-shadow: none; }}
  .hero {{
    border: 1px solid var(--border);
    border-radius: 24px;
    background: linear-gradient(100deg, #FFFFFF 0%, #F6F9FD 50%, #E9F1FB 100%);
    box-shadow: var(--card-shadow);
    padding: 34px 48px 30px;
  }}
  .hero-content {{ max-width: 56%; gap: 14px; }}
  /* Litt mindre/tryggere enn før (2026-09-27, Kai: "kan vel være på 1
     linje?") -- ved 1024px bredde (der denne to-kolonne-layouten akkurat
     starter) hadde "Finn billigste kontaktlinser" NULL margin til
     konteneren (487,86px tekst i en 487,86px bred kolonne -- identisk på
     pikselet), så den minste font-metrikk-forskjell (f.eks. Windows'
     ClearType-rendering av Space Grotesk vs. denne økten sin
     test-browser) var nok til å vippe den over i to linjer. Senket
     clamp-en gir ~60px reell margin ved 1024px i stedet for 0px, uten å
     endre selve H1-teksten (SEO-nøytralt). */
  .hero-heading h1 {{ font-size: clamp(1.75rem, 2.6vw, 2.35rem); line-height: 1.15; margin: 0; }}
  .hero-media {{ display: block; position: absolute; top: 0; right: 0; bottom: 0; width: 46%; z-index: 1; overflow: hidden; border-radius: 0 24px 24px 0; pointer-events: none; -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 40%); mask-image: linear-gradient(90deg, transparent 0, #000 40%); }}
  .hero-media picture {{ display: block; width: 100%; height: 100%; }}
  .hero-media img {{ display: block; width: 100%; height: 100%; object-fit: cover; object-position: right center; }}
  .hero .search-input {{ padding: 20px 140px 20px 58px; font-size: 1.2rem; box-shadow: 0 10px 30px rgba(37, 99, 235, 0.16); }}
  .hero .search-icon {{ left: 24px; }}
  .hero .search-btn {{ padding: 0 32px; font-size: 1rem; }}
  .trust-card {{ background: transparent; border: none; padding: 0; align-items: center; gap: 12px; }}
  .trust-card-title {{ margin: 0 0 2px; }}
  .trust-card-text {{ font-size: 0.8rem; max-width: 520px; }}
  #kategorier {{ margin-top: 32px !important; }}
  .category-rows {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; }}
  .category-row {{ flex-direction: column; align-items: flex-start; justify-content: flex-start; gap: 10px; min-height: 150px; padding: 16px 16px 18px; border-radius: 18px; box-shadow: 0 1px 2px rgba(11, 37, 69, 0.06), 0 6px 18px rgba(37, 99, 235, 0.05); }}
  .category-row:hover, .category-row:focus-visible {{ transform: translateY(-2px); box-shadow: 0 10px 26px rgba(37, 99, 235, 0.14); }}
  /* Linsen ligger nede til høyre (bildet skaleres med kortbredden, forankret i bunnen) med fade mot venstre og opp,
     og en pastell-tåke bak teksten (::before), så tittel og beskrivelse alltid er lette å lese. */
  .category-row-bg {{ top: auto; bottom: 0; right: -8%; width: 122%; height: auto; max-width: none; -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 42%), linear-gradient(180deg, transparent 0, #000 24%); -webkit-mask-composite: source-in; mask-image: linear-gradient(90deg, transparent 0, #000 42%), linear-gradient(180deg, transparent 0, #000 24%); mask-composite: intersect; }}
  /* Multifokale: to stablede linser tar mer plass; skyv bildet litt mot høyre så beskrivelsen står fri */
  .category-row.cat-coral .category-row-bg {{ right: -15%; width: 110%; }}
  .category-row::before {{ content: ""; position: absolute; inset: 0; z-index: -1; background: linear-gradient(90deg, var(--cat-bg) 0%, var(--cat-bg) 46%, transparent 80%); pointer-events: none; }}
  .category-row-icon {{ width: 44px; height: 44px; }}
  .category-row-icon svg {{ width: 22px; height: 22px; }}
  .category-row-text {{ flex: none; max-width: 76%; }}
  .category-row-arrow {{ top: auto; bottom: 12px; right: 12px; transform: translateX(-4px); width: 30px; height: 30px; background: var(--cat-accent); color: white; opacity: 0; transition: opacity 0.15s, transform 0.15s; }}
  .category-row:hover .category-row-arrow, .category-row:focus-visible .category-row-arrow {{ opacity: 1; transform: translateX(0); }}
}}
</style>
</head>
<body>
{TOPBAR_HTML_NO_SEARCH}
<div class="wrap wrap-wide">
  <div class="hero-panel">
    <div class="hero">
      <div class="hero-content">
        <div class="hero-heading hero-copy">
          <div class="kicker">Prissammenligning</div>
          <h1>Finn billigste kontaktlinser</h1>
          <p class="hero-subtext">Vi sammenligner priser fra {n_retailers} norske nettbutikker. Se prisen med og uten frakt.</p>
        </div>
        <div class="search-section">
          <div class="search-row">
            <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/></svg>
            <label for="lens-search" class="visually-hidden" style="position:absolute;left:-9999px;">Søk etter linse eller merke</label>
            <input type="search" id="lens-search" class="search-input" placeholder="Søk etter linse eller merke" autocomplete="off">
            <button type="button" class="search-btn" id="search-btn">Søk</button>
            <div class="search-suggestions" id="search-suggestions"></div>
          </div>
        </div>
        <div class="trust-card">
          <div class="trust-card-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 5-3.2 7.8-7 9-3.8-1.2-7-4-7-9V6z"/><path d="M9 12l2 2 4-4"/></svg></div>
          <div>
            <div class="trust-card-title">Uavhengig og oppdatert</div>
            <p class="trust-card-text">Kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser automatisk og oppdaterer dem daglig, og lar deg se prisen både med og uten frakt.</p>
          </div>
        </div>
      </div>
      <div class="hero-media" aria-hidden="true">
        <picture>
          <source media="(min-width: 1024px)" type="image/webp" srcset="/static/hero/eye-560.webp 560w, /static/hero/eye-840.webp 840w, /static/hero/eye-1120.webp 1120w" sizes="(min-width: 1200px) 540px, 42vw">
          <img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" alt="" width="560" height="382" fetchpriority="high" decoding="async">
        </picture>
      </div>
    </div>

    <div class="kategorier-block desktop-only-block">
      <div class="section-header" id="kategorier" style="margin-top:20px;">
        <h2>Kategorier</h2>
      </div>
      <div class="category-rows">
        {category_rows_html}
      </div>
    </div>
  </div>

  <div class="section-header" id="merker">
    <h2>Merker</h2>
  </div>
  <div class="brand-grid">
    {brand_cards_html}
  </div>
  {pli_disclaimer_note}

  <div class="kategorier-block mobile-only-block">
    <div class="section-header" style="margin-top:20px;">
      <h2>Kategorier</h2>
    </div>
    <div class="category-rows">
      {category_rows_html}
    </div>
  </div>

  <div class="section-header">
    <h2>Guider</h2>
  </div>
  <div class="guide-grid">
    {guide_cards_html}
  </div>

  <div class="trust-strip">
    <div class="trust-item">
      <div class="trust-item-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.59 13.41L12 22l-9-9 8.59-8.59A2 2 0 0 1 13 3h5a2 2 0 0 1 2 2v5a2 2 0 0 1-.41 2.41z"/><circle cx="16.5" cy="7.5" r="1.2" fill="currentColor" stroke="none"/></svg></div>
      <div><strong>{n_products} linser</strong><span>Oppdatert daglig</span></div>
    </div>
    <div class="trust-item">
      <div class="trust-item-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9l1-5h14l1 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M4 9h16M9.5 20v-5.5h5V20"/></svg></div>
      <div><strong>{n_retailers} nettbutikker</strong><span>Sammenlignet daglig</span></div>
    </div>
    <div class="trust-item">
      <div class="trust-item-icon">{TRUCK_ICON_SVG}</div>
      <div><strong>Med eller uten frakt</strong><span>Du velger hva du sammenligner</span></div>
    </div>
    <div class="trust-item">
      <div class="trust-item-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 5-3.2 7.8-7 9-3.8-1.2-7-4-7-9V6z"/></svg></div>
      <div><strong>Uavhengig</strong><span>Vi selger ikke linser selv</span></div>
    </div>
  </div>

  {METHODOLOGY_HTML}

  {home_faq_html}
</div>

<script type="application/json" id="product-search-data">{search_index_json}</script>
<script type="application/json" id="private-label-search-data">{private_label_search_index_json}</script>
<script>
  // Søket kjører mot en liten skjult JSON-indeks (over), ikke mot synlige
  // produktkort -- forsiden viser bevisst IKKE lenger alle {n_products}
  // linsene (fjernet 2026-08-15, se CLAUDE.md): en forside stappet full av
  // hvert eneste produkt utvannet det topiske fokuset for SEO/AI-sitering
  // og konkurrerte med egne kategori-/merkesider om de samme søkene.
  // Kategoriene og merkene under er nå den reelle "se alt"-inngangen.
  // Selve søkelogikken er delt med guide-sidene og toppmenyen (kjøres nå fra
  // TOPBAR_HTML, se LENS_SEARCH_JS -- unngår at IIFE-en kjører to ganger på
  // samme side og dobbeltbinder event-lyttere på forsidens eget søkefelt).
</script>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


GUIDE_CONTENT = {
    "manedslinser-vs-dagslinser": {
        "title": "Månedslinser vs. dagslinser – hva passer deg?",
        "updated": "2026-08-10",
        "description": "Fordeler og ulemper ved månedslinser og dagslinser, og hvordan brukshyppighet avgjør hva som lønner seg.",
        "body_html": """
<p>Det korte svaret: bruker du linser <strong>sjeldnere enn 4–5 dager i uken</strong>, kommer
dagslinser oftest billigst ut totalt sett, selv om prisen per linse er høyere. Bruker du
linser <strong>daglig</strong>, er månedslinser normalt rimeligst per bruksdag.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Dagslinser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Nytt, rent par hver dag – ingen rengjøring eller oppbevaringsvæske</li>
  <li>Praktisk til sport, reise eller sjelden bruk</li>
  <li>Lavere risiko for øyeinfeksjon siden linsen aldri gjenbrukes</li>
  <li>Høyere kostnad per linse, og mer emballasjeavfall ved daglig bruk</li>
</ul>
<p style="font-size:0.95rem;line-height:1.7;">Et eksempel på en mye brukt dagslinse er
<a href="/kontaktlinser/soflens/soflens-daily-disposable-30-pack/">SofLens Daily Disposable</a>
– sammenlign priser og se hvor mange forhandlere som fører den akkurat nå.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Månedslinser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Samme par brukes i opptil 30 dager (følg optikerens anbefaling)</li>
  <li>Lavere kostnad per bruksdag ved daglig bruk</li>
  <li>Krever daglig rengjøring og riktig oppbevaringsvæske</li>
  <li>Mange moderne månedslinser (silikonhydrogel) slipper gjennom mer oksygen enn eldre
  materialer, noe som kan gi bedre komfort ved lange dager med linser</li>
</ul>
<p style="font-size:0.95rem;line-height:1.7;">Et eksempel på en moderne silikonhydrogel-månedslinse er
<a href="/kontaktlinser/ultra/ultra-6-pack/">Ultra 6-pack</a> fra Bausch + Lomb.</p>

<p style="margin-top:24px;">Uansett type: følg alltid byttefrekvensen optikeren har satt for
akkurat din linse og resept – det er ikke bare et prisspørsmål, men avgjørende for
øyehelsen.</p>
""",
        "faq": [
            {
                "question": "Er dagslinser eller månedslinser billigst?",
                "answer": "Bruker du linser sjeldnere enn 4–5 dager i uken, kommer dagslinser oftest billigst ut totalt sett, selv om prisen per linse er høyere. Bruker du linser daglig, er månedslinser normalt rimeligst per bruksdag.",
            },
            {
                "question": "Hva er fordelen med dagslinser?",
                "answer": "Nytt, rent par hver dag – ingen rengjøring eller oppbevaringsvæske. Praktisk til sport, reise eller sjelden bruk, og lavere risiko for øyeinfeksjon siden linsen aldri gjenbrukes.",
            },
            {
                "question": "Hva er fordelen med månedslinser?",
                "answer": "Lavere kostnad per bruksdag ved daglig bruk. Mange moderne månedslinser (silikonhydrogel) slipper gjennom mer oksygen enn eldre materialer, som kan gi bedre komfort ved lange dager med linser.",
            },
        ],
    },
    "hvordan-velge-kontaktlinser": {
        "title": "Hvordan velge kontaktlinser",
        "updated": "2026-08-10",
        "description": "En kort guide til hva som avgjør riktig kontaktlinsetype: resept, brukshyppighet, synsfeil og øynenes behov.",
        "body_html": """
<p>Kontaktlinser er reseptvare, også de uten styrke (f.eks. fargede linser). Første steg er
alltid en synsundersøkelse hos optiker, som fastsetter styrke, krumning og linsetype
øynene dine tåler godt.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Det resepten din vanligvis avgjør</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Astigmatisme</strong> (skjev hornhinne) → toriske linser, formet for å ligge
  stabilt i en bestemt retning</li>
  <li><strong>Alderssyn</strong> (vansker med å se på nært hold fra ca. 40–45 år) →
  multifokale/progressive linser</li>
  <li><strong>Sfærisk syn</strong> uten astigmatisme eller alderssyn → vanlige sfæriske
  linser, det enkleste og billigste utvalget – f.eks.
  <a href="/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/">Acuvue Moist</a></li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Andre ting som spiller inn</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Hvor ofte du bruker linser, se vår <a href="/guide/manedslinser-vs-dagslinser/">sammenligning
  av månedslinser og dagslinser</a></li>
  <li>Tørre øyne kan gjøre enkelte materialer (silikonhydrogel) mer behagelige enn andre</li>
  <li>Fargede linser krever samme oppfølging som andre linser, selv uten styrke</li>
</ul>

<p style="margin-top:24px;">Vi sammenligner priser på tvers av nettbutikker, men kan
aldri erstatte en synsundersøkelse – bruk alltid en resept som er gyldig for den
spesifikke linsen du bestiller.</p>
""",
        "faq": [
            {
                "question": "Kan jeg velge kontaktlinser selv, uten synsundersøkelse?",
                "answer": "Nei. Kontaktlinser er reseptvare, også de uten styrke (f.eks. fargede linser). Første steg er alltid en synsundersøkelse hos optiker, som fastsetter styrke, krumning og linsetype øynene dine tåler godt.",
            },
            {
                "question": "Hvilken linsetype passer ved astigmatisme?",
                "answer": "Toriske linser, formet for å ligge stabilt i en bestemt retning i øyet.",
            },
            {
                "question": "Hvilken linsetype passer ved alderssyn?",
                "answer": "Multifokale/progressive linser passer normalt best ved alderssyn (vansker med å se på nært hold fra ca. 40–45 år).",
            },
        ],
    },
    "kontaktlinser-for-barn": {
        "title": "Kontaktlinser for barn",
        "updated": "2026-08-16",
        "description": "Er barn for unge for kontaktlinser? Hva som faktisk avgjør om et barn er klar, og hvorfor dagslinser ofte anbefales som førstevalg.",
        "body_html": """
<p>Det finnes ingen fast minstealder for kontaktlinser. Optikere vurderer i stedet
<strong>modenhet</strong> – om barnet klarer å følge en hygienerutine selv (vaske hender,
sette inn/ta ut linsen riktig, ikke sove med linsen inne) – fremfor et bestemt årstall.
Mange barn ned i 8–10-årsalderen fungerer fint med linser, mens andre bør vente.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvorfor dagslinser ofte anbefales til barn</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Nytt, rent par hver dag – ingen rengjøring eller oppbevaringsvæske å huske på</li>
  <li>Lavere konsekvens hvis en linse mistes eller glemmes en dag</li>
  <li>Lavere infeksjonsrisiko enn linser som gjenbrukes over tid</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Myopikontroll</h2>
<p style="font-size:1rem;line-height:1.7;">Enkelte dagslinser er i dag også godkjent spesifikt for å bremse utvikling av
nærsynthet (myopikontroll) hos barn og unge – f.eks.
<a href="/kontaktlinser/myday/myday-misight-1-day-30-pack/">MyDay MiSight</a>, spesifikt
utviklet for dette formålet. Dette er noe en optiker eller øyelege vurderer og følger opp
individuelt, ikke noe man velger selv.</p>

<p style="margin-top:24px;">Uansett alder: en synsundersøkelse hos optiker er alltid første steg, og barnet bør
følges opp jevnlig så lenge det bruker linser.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">Ifølge <a href="https://nhi.no/familie/barn/barn-og-kontaktlinser" target="_blank" rel="noopener">Norsk Helseinformatikk (NHI)</a> er det store individuelle forskjeller i når et barn er klart, selv om det finnes en vanlig tommelfingerregel:</p>

<blockquote cite="https://nhi.no/familie/barn/barn-og-kontaktlinser" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Vanlige anbefalinger er at barn kan begynne å bruke linser når de er i 12-13 års alderen. Men det finnes 14-åringer som er for umodne til å bruke linser, og 10-åringer som er modne nok.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://nhi.no/familie/barn/barn-og-kontaktlinser" target="_blank" rel="noopener">NHI, Barn og kontaktlinser</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Hvor gammelt må et barn være for å bruke kontaktlinser?",
                "answer": "Det finnes ingen fast minstealder. Optikere vurderer i stedet om barnet er modent nok til å følge hygienerutinen selv, ikke et bestemt årstall. Mange fungerer fint fra 8–10-årsalderen, mens andre bør vente.",
            },
            {
                "question": "Hvorfor anbefales ofte dagslinser til barn?",
                "answer": "Dagslinser krever ingen rengjøring eller oppbevaringsvæske, gir lavere konsekvens hvis en linse mistes en dag, og har lavere infeksjonsrisiko enn linser som gjenbrukes over tid.",
            },
        ],
    },
    "harde-eller-myke-linser": {
        "title": "Harde eller myke linser",
        "updated": "2026-08-16",
        "description": "Forskjellen på myke og harde (gassgjennomtrengelige) kontaktlinser, og hvorfor de aller fleste i dag bruker myke linser.",
        "body_html": """
<p>De aller fleste kontaktlinser som selges i dag – og alt vi sammenligner priser på her
på Kontaktlinser.no – er <strong>myke linser</strong> (hydrogel eller silikonhydrogel), som
<a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a>. Harde
(gassgjennomtrengelige/RGP) linser finnes fortsatt, men brukes i dag først og fremst til
spesielle synsforhold.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Myke linser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Komfortable fra første stund, kort tilvenningstid</li>
  <li>Ligger tett mot øyet – mindre risiko for at rusk kommer under linsen</li>
  <li>Bredt utvalg av dags-, ukes- og månedslinser</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Harde linser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Kan gi skarpere syn ved uregelmessig hornhinne (f.eks. keratokonus) eller svært
  høy astigmatisme</li>
  <li>Lengre tilvenningstid enn myke linser</li>
  <li>Krever tilpasning og oppfølging hos spesialisert optiker/øyelege</li>
</ul>

<p style="margin-top:24px;">Hvilken type som passer avgjøres av synsforholdene dine, ikke personlig preferanse
alene – dette er noe optikeren vurderer ved synsundersøkelsen.</p>
""",
        "faq": [
            {
                "question": "Hva er vanligst i dag, harde eller myke linser?",
                "answer": "De aller fleste bruker myke linser (hydrogel eller silikonhydrogel) i dag. Harde (gassgjennomtrengelige) linser brukes først og fremst ved spesielle synsforhold, som uregelmessig hornhinne eller svært høy astigmatisme.",
            },
            {
                "question": "Er harde linser bedre enn myke?",
                "answer": "Ikke generelt – de kan gi skarpere syn ved bestemte tilstander som keratokonus, men krever lengre tilvenning. Hvilken type som passer avgjøres av synsforholdene dine, vurdert av en optiker.",
            },
        ],
    },
    "hvordan-bruke-kontaktlinser": {
        "title": "Hvordan sette inn og ta ut kontaktlinser",
        "updated": "2026-08-16",
        "description": "Trinnvis fremgangsmåte for å sette inn og ta ut kontaktlinser trygt og hygienisk.",
        "body_html": """
<p>God hygiene er viktigere enn selve teknikken. Vask og tørk hendene grundig før du
tar i linsene, hver eneste gang.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Sette inn linsen</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Sjekk at linsen ikke er vrengt (skal danne en jevn skål, ikke ha kant som vipper ut)</li>
  <li>Trekk nedre øyelokk forsiktig ned, og hold gjerne øvre øyelokk oppe med den andre
  hånden</li>
  <li>Se oppover eller rett frem, og plasser linsen forsiktig på det hvite av øyet</li>
  <li>Se ned/blunk rolig – linsen finner selv rett posisjon på hornhinnen</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Ta ut linsen</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Se oppover, trekk nedre øyelokk ned</li>
  <li>Klyp linsen forsiktig med tommel og pekefinger, eller skyv den nedover mot det
  hvite av øyet før du løfter den av</li>
  <li>Aldri bruk negler direkte mot hornhinnen</li>
</ul>

<p style="margin-top:24px;">Sliter du med å få det til, er det helt normalt de første gangene – optikeren som
tilpasset linsene dine viser deg gjerne teknikken på nytt.</p>
""",
        "faq": [
            {
                "question": "Hva er viktigst å huske før man setter inn kontaktlinser?",
                "answer": "Vask og tørk hendene grundig først, hver eneste gang – god hygiene er viktigere enn selve innsettingsteknikken.",
            },
            {
                "question": "Hvordan vet jeg om linsen er vrengt?",
                "answer": "En riktig vendt linse danner en jevn skål. Er den vrengt, vipper kanten utover i stedet for å bøye jevnt innover.",
            },
        ],
    },
    "hvorfor-bruke-kontaktlinser": {
        "title": "Hvorfor bruke kontaktlinser fremfor briller",
        "updated": "2026-08-16",
        "description": "Fordelene ved kontaktlinser sammenlignet med briller, og hva som taler for å kombinere begge deler.",
        "body_html": """
<p>Kontaktlinser og briller løser samme grunnleggende behov – korrigert syn – men passer
ulikt avhengig av livsstil og situasjon. Mange kombinerer begge deler.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Fordeler med kontaktlinser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Fullt, uforstyrret synsfelt – ingen brillestang eller kant i synsranden</li>
  <li>Dugger ikke ved temperaturskifte, regn eller bruk av munnbind/hjelm</li>
  <li>Praktisk ved sport og fysisk aktivitet</li>
  <li>Kan kombineres med vanlige solbriller uten styrke</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva som taler for briller</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Ingen daglig hygienerutine eller berøring av øyet</li>
  <li>Kan være bedre egnet ved svært tørre øyne eller enkelte øyetilstander</li>
</ul>

<p style="margin-top:24px;">Det er ikke enten/eller – mange bruker linser i aktive perioder av dagen og briller
resten av tiden.</p>
""",
        "faq": [
            {
                "question": "Er kontaktlinser bedre enn briller?",
                "answer": "Ikke nødvendigvis bedre, men annerledes – linser gir et fullt synsfelt uten brillestang eller dugging, mens briller krever ingen daglig hygienerutine. Mange bruker begge deler avhengig av situasjon.",
            },
        ],
    },
    "vedlikehold-av-kontaktlinser": {
        "title": "Vedlikehold av kontaktlinser",
        "updated": "2026-08-16",
        "description": "Riktig rengjøring og oppbevaring av kontaktlinser som gjenbrukes, og de vanligste feilene å unngå.",
        "body_html": """
<p>Dagslinser kastes etter én dag og trenger ikke rengjøring. Bruker du ukes- eller
månedslinser, er riktig vedlikehold avgjørende for øyehelsen – ikke bare for at linsen
skal vare lenge.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Grunnregler</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Bruk alltid <strong>fersk</strong> linsevæske, som
  <a href="/linsevaeske/renu/renu-multi-purpose-360-ml/">ReNu Multi-Purpose</a> – fyll
  aldri på gammel væske i etuiet («topping off»), skift den helt hver gang</li>
  <li>Følg optikerens anbefalte gni-og-skyll-rutine hvis væsken tilsier det, selv om
  enkelte væsker markedsføres som "no-rub"</li>
  <li>Skift oppbevaringsetui jevnlig (følg produsentens anbefaling, ofte hver 1.–3. måned)</li>
  <li>Bruk aldri springvann eller spytt på linsene – det kan tilføre mikroorganismer
  linsevæsken ikke er laget for å drepe</li>
  <li>Følg byttefrekvensen linsen faktisk er godkjent for, selv om den fortsatt føles
  komfortabel</li>
</ul>

<p style="margin-top:24px;">Vi sammenligner priser på linsevæske fra flere norske nettbutikker – se
<a href="/">forsiden</a> for å søke opp den du bruker.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">Ifølge <a href="https://nhi.no/livsstil/egenomsorg/kontaktlinser-og-vann" target="_blank" rel="noopener">Norsk Helseinformatikk (NHI)</a> er dette et av de tydeligste rådene fra både amerikanske og norske helsemyndigheter:</p>

<blockquote cite="https://nhi.no/livsstil/egenomsorg/kontaktlinser-og-vann" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Både CDC og FHI presiserer at linser og linseetui aldri skal renses/skylles eller oppbevares i springvann.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://nhi.no/livsstil/egenomsorg/kontaktlinser-og-vann" target="_blank" rel="noopener">NHI, Kontaktlinser og vann</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Kan jeg fylle på gammel linsevæske i etuiet?",
                "answer": "Nei. Bruk alltid fersk væske og skift den helt hver gang – å fylle på gammel væske («topping off») reduserer den desinfiserende effekten betraktelig.",
            },
            {
                "question": "Hvor ofte bør jeg skifte oppbevaringsetui?",
                "answer": "Følg produsentens anbefaling for linsevæsken din, ofte hver 1.–3. måned. Et gammelt etui kan huse bakterier selv om det ser rent ut.",
            },
        ],
    },
    "reising-med-kontaktlinser": {
        "title": "Reising med kontaktlinser",
        "updated": "2026-08-16",
        "description": "Praktiske tips for å bruke kontaktlinser på reise, fra flyturens tørre kabinluft til væskeregler i håndbagasjen.",
        "body_html": """
<p>Kontaktlinser er praktiske på reise, men noen få forberedelser gjør det enklere.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Før avreise</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Pakk nok linser og eventuell linsevæske til hele reisen – ikke alle merker er
  tilgjengelige overalt</li>
  <li>Ta med briller som backup, i tilfelle irritasjon eller tørre øyne underveis</li>
  <li>Linsevæske i håndbagasje må følge vanlige væskeregler (beholdere under 100 ml)</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Underveis</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Kabinluft på fly er svært tørr og kan gjøre linser mindre behagelige på lange
  flyvninger – ha øyedråper eller briller tilgjengelig</li>
  <li>Dagslinser er ofte praktiske på reise, siden du slipper å ha med etui og
  oppbevaringsvæske – f.eks. <a href="/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/">Acuvue
  Moist</a></li>
</ul>
""",
        "faq": [
            {
                "question": "Kan jeg ha linsevæske i håndbagasjen?",
                "answer": "Ja, men den må følge vanlige væskeregler for håndbagasje (beholdere under 100 ml). Vurder heller reisestørrelser eller dagslinser hvis du vil unngå væske helt.",
            },
            {
                "question": "Hvorfor blir kontaktlinser mer ukomfortable på fly?",
                "answer": "Kabinluft er svært tørr, noe som kan gjøre linser mindre behagelige på lange flyvninger. Øyedråper eller en pause med briller kan hjelpe.",
            },
        ],
    },
    "kosmetiske-kontaktlinser": {
        "title": "Kosmetiske og fargede kontaktlinser",
        "updated": "2026-08-16",
        "description": "Fargede kontaktlinser er reseptvare på lik linje med andre linser, selv uten styrke. Slik velger du dem trygt.",
        "body_html": """
<p>Fargede og kosmetiske kontaktlinser er kontaktlinser på lik linje med alle andre –
også de <strong>uten styrke</strong> som kun endrer øyefargen. De regnes som medisinsk
utstyr og krever samme tilpasning og hygiene som synskorrigerende linser.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Kjøp alltid fra seriøse forhandlere</h2>
<p style="font-size:1rem;line-height:1.7;">Ukvalifiserte "festivallinser" eller kostymelinser kjøpt uten tilpasning (f.eks. fra
useriøse utenlandske nettbutikker) har vesentlig høyere risiko for feil passform og
øyeinfeksjon enn linser fra forhandlere som følger norske krav til medisinsk utstyr –
som f.eks. <a href="/kontaktlinser/freshlook/freshlook-oneday-30-pack/">FreshLook
OneDay</a>.</p>

<p style="margin-top:16px;">Samme regler som for vanlige linser gjelder: synsundersøkelse/tilpasning hos optiker
først, og samme hygienerutiner ved bruk.</p>
""",
        "faq": [
            {
                "question": "Trenger jeg resept for fargede kontaktlinser uten styrke?",
                "answer": "Ja. Fargede linser regnes som medisinsk utstyr uansett styrke, og krever samme tilpasning hos optiker som synskorrigerende linser.",
            },
            {
                "question": "Er det trygt å kjøpe billige kostymelinser uten tilpasning?",
                "answer": "Nei, det frarådes. Linser kjøpt uten tilpasning fra useriøse kilder har vesentlig høyere risiko for feil passform og øyeinfeksjon enn linser fra forhandlere som følger norske krav til medisinsk utstyr.",
            },
        ],
    },
    "kontaktlinsens-materiale": {
        "title": "Kontaktlinsens materiale",
        "updated": "2026-08-16",
        "description": "Forskjellen på silikonhydrogel og vanlig hydrogel, og hvorfor materialet påvirker komfort og øyehelse.",
        "body_html": """
<p>Materialet en linse er laget av avgjør blant annet hvor mye oksygen som slipper
gjennom til hornhinnen – noe hornhinnen er avhengig av siden den ikke har egne
blodårer.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Silikonhydrogel</h2>
<p style="font-size:1rem;line-height:1.7;">Det vanligste materialet i moderne linser (inkludert de fleste vi følger prisene på
her, som <a href="/kontaktlinser/acuvue/acuvue-oasys-6-pack/">Acuvue Oasys</a>). Slipper gjennom
vesentlig mer oksygen enn eldre hydrogel-materialer, noe som kan gi bedre komfort ved
lange dager med linser i.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Vanlig hydrogel</h2>
<p style="font-size:1rem;line-height:1.7;">Eldre, men fortsatt i bruk i enkelte linser. Har typisk høyere vanninnhold, som for
noen kan oppleves annerledes komfortabelt enn silikonhydrogel, spesielt tidlig i
brukstiden.</p>

<p style="margin-top:16px;">Materiale og vanninnhold står oppgitt under spesifikasjoner på hver produktside her
på Kontaktlinser.no.</p>
""",
        "faq": [
            {
                "question": "Hva er forskjellen på silikonhydrogel og vanlig hydrogel?",
                "answer": "Silikonhydrogel slipper gjennom vesentlig mer oksygen til hornhinnen enn eldre hydrogel-materialer, noe som kan gi bedre komfort ved lange dager med linser i. Vanlig hydrogel har ofte høyere vanninnhold.",
            },
        ],
    },
    "korrigerende-kontaktlinser": {
        "title": "Korrigerende kontaktlinser ved astigmatisme og alderssyn",
        "updated": "2026-08-16",
        "description": "Hvordan toriske linser korrigerer astigmatisme, og hvordan multifokale linser korrigerer alderssyn.",
        "body_html": """
<p>Enkel nærsynthet eller langsynthet korrigeres med sfæriske linser. To vanlige
synsforhold krever egne, mer avanserte linsetyper.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Toriske linser (astigmatisme)</h2>
<p style="font-size:1rem;line-height:1.7;">Ved astigmatisme (skjev hornhinne) må linsen ha ulik styrke i ulike retninger, og
ligge stabilt uten å rotere i øyet. Toriske linser er formet spesielt for dette, og
krever en mer nøyaktig tilpasning enn vanlige sfæriske linser – f.eks.
<a href="/kontaktlinser/biofinity/biofinity-toric-6-pack/">Biofinity Toric</a>.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Multifokale/progressive linser (alderssyn)</h2>
<p style="font-size:1rem;line-height:1.7;">Fra rundt 40–45-årsalderen svekkes øyets evne til å stille skarpt på nært hold.
Multifokale linser har flere styrkesoner i samme linse (typisk for nært, mellomdistanse
og langt hold, som <a href="/kontaktlinser/biofinity/biofinity-multifocal-6-pack/">Biofinity
Multifocal</a>), og kan kreve en kort tilvenningsperiode før hjernen lærer å bruke sonene
riktig.</p>

<p style="margin-top:16px;">Begge typer krever en presis resept fra optiker – dette er ikke noe man kan
tilnærme seg med en vanlig sfærisk styrke.</p>
""",
        "faq": [
            {
                "question": "Hvorfor kan jeg ikke bruke vanlige linser ved astigmatisme?",
                "answer": "Ved astigmatisme må linsen ha ulik styrke i ulike retninger og ligge stabilt uten å rotere i øyet. Det krever toriske linser, formet spesielt for dette, med en mer nøyaktig tilpasning enn sfæriske linser.",
            },
            {
                "question": "Må jeg venne meg til multifokale linser?",
                "answer": "Ofte ja. Multifokale linser har flere styrkesoner i samme linse, og det kan ta en kort tilvenningsperiode før hjernen lærer å bruke sonene riktig.",
            },
        ],
    },
    "produksjon-av-kontaktlinser": {
        "title": "Slik produseres kontaktlinser",
        "updated": "2026-08-16",
        "description": "Kort om hvordan moderne myke kontaktlinser produseres, kvalitetssikres og reguleres som medisinsk utstyr.",
        "body_html": """
<p>De fleste moderne myke kontaktlinser produseres ved <strong>støping</strong>: flytende
linsemateriale sprøytes inn i presise plastformer som gir linsen riktig krumning,
diameter og styrke, før den herdes og bearbeides ferdig i sterile lokaler.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Kvalitetskontroll og regulering</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Hver linse kontrolleres for riktig form og styrke før pakking</li>
  <li>Linsene pakkes i steril saltvannsløsning i forseglet emballasje</li>
  <li>Kontaktlinser regnes som medisinsk utstyr i EU/EØS og skal være CE-merket</li>
</ul>

<p style="margin-top:16px;">Denne strenge produksjons- og kvalitetskontrollen er en av grunnene til at det lønner
seg å kjøpe linser fra forhandlere som følger regelverket, ikke uregulerte kilder.</p>
""",
        "faq": [
            {
                "question": "Hvordan lages myke kontaktlinser?",
                "answer": "De fleste produseres ved støping: flytende linsemateriale sprøytes inn i presise plastformer som gir riktig krumning, diameter og styrke, før linsen herdes, kontrolleres og pakkes i steril saltvannsløsning.",
            },
        ],
    },
    "kontaktlinsens-historie": {
        "title": "Kontaktlinsens historie",
        "updated": "2026-08-16",
        "description": "Fra Leonardo da Vincis tidlige skisser til moderne dagslinser – en kort historikk om kontaktlinsens utvikling.",
        "body_html": """
<p>Ideen om en linse som ligger direkte på øyet er overraskende gammel, men det tok
århundrer før teknologien fantes for å faktisk lage den.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Fra idé til glasslinse</h2>
<p style="font-size:1rem;line-height:1.7;">Leonardo da Vinci skisserte konsepter som kan minne om kontaktlinser allerede rundt
1508, men dette var teoretiske tegninger, ikke noe som kunne brukes. De første reelle
kontaktlinsene – tunge glasslinser som dekket hele det synlige øyet (skleralinser) –
kom først på slutten av 1800-tallet, og var langt fra komfortable ved dagens
standard.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Plast og den moderne myke linsen</h2>
<p style="font-size:1rem;line-height:1.7;">Lettere plastlinser kom på 1930–40-tallet. Det virkelig store gjennombruddet kom i
1961, da den tsjekkiske kjemikeren Otto Wichterle utviklet den første myke
hydrogel-kontaktlinsen – materialet som fortsatt ligger til grunn for de fleste linser
som selges i dag. Dagslinser (til engangsbruk) ble vanlig fra 1990-tallet og utover, og
er i dag et av de mest brukte alternativene.</p>
""",
        "faq": [
            {
                "question": "Hvem oppfant den moderne myke kontaktlinsen?",
                "answer": "Den tsjekkiske kjemikeren Otto Wichterle utviklet den første myke hydrogel-kontaktlinsen i 1961 – materialet som fortsatt ligger til grunn for de fleste linser som selges i dag.",
            },
        ],
    },
    "terapeutiske-kontaktlinser": {
        "title": "Terapeutiske kontaktlinser (bandasjelinser)",
        "updated": "2026-08-16",
        "description": "Terapeutiske kontaktlinser brukes til å beskytte eller behandle øyet medisinsk, ikke til synskorrigering, og forskrives av øyelege.",
        "body_html": """
<p>Terapeutiske kontaktlinser (ofte kalt bandasjelinser) har et annet formål enn vanlige
kontaktlinser: de brukes ikke primært for å korrigere synet, men for å beskytte eller
behandle selve øyet.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Vanlige bruksområder</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Beskytte hornhinnens overflate mens den gror etter skade, betennelse eller kirurgi</li>
  <li>Lindre smerte ved enkelte hornhinnetilstander</li>
  <li>Holde en ustabil hornhinneoverflate på plass under tilheling</li>
</ul>

<p style="margin-top:16px;">Terapeutiske linser forskrives og følges opp av <strong>øyelege</strong>, ikke valgt
selv slik man kan velge synskorrigerende linser hos optiker. Bruken, varigheten og
oppfølgingen er individuelt tilpasset den medisinske tilstanden.</p>
""",
        "faq": [
            {
                "question": "Hva er en terapeutisk kontaktlinse (bandasjelinse)?",
                "answer": "En linse som brukes til å beskytte eller behandle øyet medisinsk – for eksempel for å beskytte hornhinnen under tilheling etter skade eller kirurgi – ikke primært for å korrigere synet.",
            },
            {
                "question": "Kan jeg velge terapeutiske linser selv?",
                "answer": "Nei. Terapeutiske linser forskrives og følges opp av øyelege ut fra en medisinsk vurdering, ikke valgt selv slik man velger synskorrigerende linser hos optiker.",
            },
        ],
    },
    "kontaktlinser-med-astigmatisme": {
        "title": "Toriske linser og astigmatisme",
        "updated": "2026-08-16",
        "description": "Hva astigmatisme er, hvorfor det krever toriske linser, og hvorfor disse er litt mer krevende å tilpasse enn vanlige linser.",
        "body_html": """
<p>Astigmatisme betyr at hornhinnen har en litt uregelmessig, ovalformet krumning i
stedet for å være jevnt rund. Det gjør at syn kan bli uskarpt eller forvrengt på både
nært og langt hold – ikke bare det ene, som ved vanlig nær- eller langsynthet.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva er toriske linser?</h2>
<p style="font-size:1rem;line-height:1.7;">Toriske linser er kontaktlinser spesialformet for å korrigere astigmatisme. I motsetning
til en vanlig sfærisk linse (som har lik styrke i alle retninger og kan rotere fritt uten
at det merkes) må en torisk linse ha ulik styrke i ulike retninger, og den må ligge stabilt
i riktig posisjon for å virke. Linsene er derfor bygget med en litt tyngre nedre kant eller
tynnsoner som gjør at de "retter seg selv opp" på øyet – f.eks.
<a href="/kontaktlinser/acuvue/acuvue-oasys-for-astigmatism-6-pack/">Acuvue Oasys for
Astigmatism</a>.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvorfor tilpasningen er litt mer krevende</h2>
<p style="font-size:1rem;line-height:1.7;">Fordi linsen må stå riktig vei, trenger optikeren mer presis informasjon fra
synsundersøkelsen (styrke, sylinderkorreksjon og aksen den skal ligge i) enn ved en vanlig
sfærisk linse. Noen få prøver seg frem til beste passform, spesielt ved høyere grad av
astigmatisme.</p>

<p style="margin-top:16px;">Se vår <a href="/kontaktlinser/toriske-linser/">oversikt over toriske linser</a>
for å sammenligne priser på tvers av merker.</p>
""",
        "faq": [
            {
                "question": "Hva er forskjellen på en vanlig og en torisk linse?",
                "answer": "En vanlig sfærisk linse har lik styrke i alle retninger og kan rotere fritt. En torisk linse (for astigmatisme) har ulik styrke i ulike retninger og må ligge stabilt i riktig posisjon for å korrigere synet riktig.",
            },
            {
                "question": "Hvorfor tar det litt lengre tid å tilpasse toriske linser?",
                "answer": "Fordi linsen må ligge riktig vei på øyet, trengs mer presis informasjon fra synsundersøkelsen (sylinderstyrke og akse), og noen få prøver seg frem til beste passform.",
            },
        ],
    },
    "multifokale-kontaktlinser": {
        "title": "Multifokale kontaktlinser ved alderssyn",
        "updated": "2026-08-16",
        "description": "Hvordan multifokale kontaktlinser fungerer ved alderssyn (presbyopi), og hvor lang tilvenning man kan forvente.",
        "body_html": """
<p>Alderssyn (presbyopi) er en naturlig, aldersrelatert svekkelse av øyets evne til å
stille skarpt på nært hold, som de fleste merker fra rundt 40–45-årsalderen.
Multifokale kontaktlinser er laget for å korrigere dette.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvordan fungerer de?</h2>
<p style="font-size:1rem;line-height:1.7;">I stedet for å bytte mellom soner slik man gjør med progressive brilleglass, har
multifokale linser flere styrkesoner tilgjengelig samtidig (for nært, mellomdistanse og
langt hold, som i <a href="/kontaktlinser/acuvue/acuvue-oasys-multifocal-6-pack/">Acuvue Oasys
Multifocal</a>). Hjernen lærer gradvis å prioritere riktig sone avhengig av hva du ser på
– dette kalles simultanvisjon.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Tilvenning</h2>
<p style="font-size:1rem;line-height:1.7;">De fleste bruker 1–2 uker på å venne seg til multifokale linser. Ulike design (f.eks.
med skarpeste sone sentrert for nær- eller langsyn) passer ulikt fra person til person –
dette er noe optikeren hjelper deg å finne fram til.</p>

<p style="margin-top:16px;">Se vår <a href="/kontaktlinser/multifokale-linser/">oversikt over multifokale linser</a>
for å sammenligne priser.</p>
""",
        "faq": [
            {
                "question": "Hvordan fungerer multifokale kontaktlinser?",
                "answer": "De har flere styrkesoner tilgjengelig samtidig (nært, mellomdistanse, langt hold), og hjernen lærer gradvis å prioritere riktig sone avhengig av hva du ser på (simultanvisjon).",
            },
            {
                "question": "Hvor lang tid tar det å venne seg til multifokale linser?",
                "answer": "Vanligvis 1–2 uker, men det varierer fra person til person. Ulike linsedesign passer ulikt, og optikeren hjelper deg å finne riktig type.",
            },
        ],
    },
    "kan-man-sove-med-kontaktlinser": {
        "title": "Kan man sove med kontaktlinser?",
        "updated": "2026-08-16",
        "description": "Hvorfor de fleste kontaktlinser ikke bør brukes under søvn, og hvilke unntak som finnes.",
        "body_html": """
<p>Med de fleste vanlige dags- og månedslinser: <strong>nei</strong>, du bør ikke sove med
linsene i. Et lukket øyelokk reduserer i seg selv oksygentilførselen til hornhinnen, og en
linse oppå gjør dette enda mindre. Å sove med linser er også forbundet med vesentlig
høyere risiko for øyeinfeksjon.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Finnes det unntak?</h2>
<p style="font-size:1rem;line-height:1.7;">Enkelte linsetyper er spesielt godkjent for kontinuerlig bruk (såkalt "extended wear"),
der man kan sove med linsene i over flere døgn. Dette gjelder kun spesifikke,
godkjente linser, og kun etter at en øyelege eller optiker har vurdert og godkjent
akkurat det for deg – ikke noe man velger selv som standard.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvis det skjer ved et uhell</h2>
<p style="font-size:1rem;line-height:1.7;">Har du sovnet med vanlige linser i, ta dem ut så snart du våkner og gi øynene en pause.
Ta kontakt med optiker eller øyelege hvis du merker rødhet, smerte eller uklart syn
etterpå.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">Ifølge <a href="https://nhi.no/sykdommer/oye/brytningsfeil-nedsatt-syn/kontaktlinser" target="_blank" rel="noopener">Norsk Helseinformatikk (NHI)</a> er risikoen for sår på hornhinnen særlig stor ved bruk av linser over natten:</p>

<blockquote cite="https://nhi.no/sykdommer/oye/brytningsfeil-nedsatt-syn/kontaktlinser" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Linsene kan gi sår på hornhinnen. Myke kontaktlinser gir lettere sår enn harde. Risikoen er særlig stor hvis linsene brukes over natten.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://nhi.no/sykdommer/oye/brytningsfeil-nedsatt-syn/kontaktlinser" target="_blank" rel="noopener">NHI, Kontaktlinser</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Bør jeg sove med kontaktlinsene mine?",
                "answer": "Nei, ikke med vanlige dags- eller månedslinser. Det reduserer oksygentilførselen til hornhinnen og øker risikoen for øyeinfeksjon vesentlig.",
            },
            {
                "question": "Finnes det linser man kan sove med?",
                "answer": "Ja, enkelte linser er spesielt godkjent for kontinuerlig bruk over flere døgn, men kun etter at en øyelege eller optiker har vurdert og godkjent nettopp det for deg.",
            },
        ],
    },
    "kan-man-dusje-med-kontaktlinser": {
        "title": "Dusje med kontaktlinser? Slik unngår du problemer",
        "updated": "2026-09-05",
        "description": "Kort svar: unngå vann i linsene hvis du kan. Se hvorfor, og nøyaktig hva du skal gjøre hvis de blir våte likevel.",
        "body_html": """
<p>Det anbefales å unngå at kontaktlinsene kommer i kontakt med vann – enten det er
dusjvann, bassengvann eller vann fra sjø/innsjø. Vann kan inneholde mikroorganismer
(blant annet Acanthamoeba) som kan sette seg fast under linsen og forårsake alvorlige,
vanskelig behandlebare øyeinfeksjoner.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvis linsene blir våte</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Dagslinser:</strong> kast dem og sett inn et nytt, rent par</li>
  <li><strong>Gjenbrukbare linser:</strong> rengjør og desinfiser dem grundig med linsevæske
  før de brukes igjen – skyll dem aldri bare med vann</li>
</ul>

<p style="margin-top:16px;">Skal du svømme og ønsker klart syn i vannet, er tettsittende svømmebriller et tryggere
alternativ enn å beholde kontaktlinsene i.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">Ifølge <a href="https://nhi.no/livsstil/egenomsorg/kontaktlinser-og-vann" target="_blank" rel="noopener">Norsk Helseinformatikk (NHI)</a>, med henvisning til Folkehelseinstituttet, er akantamøbe-infeksjon en anerkjent og alvorlig risiko ved kontaktlinsebruk i vann:</p>

<blockquote cite="https://nhi.no/livsstil/egenomsorg/kontaktlinser-og-vann" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Keratitt er en alvorlig øyeinfeksjon som i hovedsak ses hos brukere av alle typer kontaktlinser. Tilstanden er ofte smertefull og vanskelig å behandle.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://nhi.no/livsstil/egenomsorg/kontaktlinser-og-vann" target="_blank" rel="noopener">NHI, Kontaktlinser og vann</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Kan jeg dusje med kontaktlinsene på?",
                "answer": "Det anbefales å unngå det. Vann kan inneholde mikroorganismer som kan sette seg fast under linsen og gi alvorlige øyeinfeksjoner.",
            },
            {
                "question": "Hva bør jeg gjøre hvis linsene blir våte?",
                "answer": "Dagslinser bør kastes og byttes med et nytt par. Gjenbrukbare linser bør rengjøres og desinfiseres grundig med linsevæske før de brukes igjen – skyll dem aldri bare med vann.",
            },
        ],
    },
    "kontaktlinser-og-torre-oyne": {
        "title": "Kontaktlinser og tørre øyne",
        "updated": "2026-08-16",
        "description": "Hvorfor kontaktlinser kan gi tørre øyne, og hva som kan hjelpe – fra linsevalg til øyedråper.",
        "body_html": """
<p>Tørre øyne er en av de vanligste plagene blant kontaktlinsebrukere. Linsen kan påvirke
hvordan tårefilmen fordeler seg over øyet, og lange dager foran skjerm (der man blunker
sjeldnere) forsterker ofte problemet.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva kan hjelpe</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Moderne silikonhydrogel-linser er ofte mer komfortable ved tørre øyne enn eldre
  materialer – se vår <a href="/guide/kontaktlinsens-materiale/">guide om linsematerialer</a></li>
  <li>Bruk kun øyedråper/fukterdråper beregnet for bruk sammen med kontaktlinser, som
  <a href="/oyedraper/systane/systane-ultra-10-ml/">Systane Ultra</a> – ikke alle
  øyedråper er trygge å bruke med linsen i</li>
  <li>Kortere brukstid enkelte dager, med bevisste pauser fra linser</li>
  <li>Husk å blunke bevisst oftere ved lengre skjermøkter</li>
</ul>

<p style="margin-top:16px;">Vedvarer plagene, kan det tyde på feil linsetype eller passform – ta det opp med
optikeren din. Vi sammenligner også priser på <a href="/oyedraper/">øyedråper</a> fra
flere norske nettbutikker.</p>
""",
        "faq": [
            {
                "question": "Hvorfor blir øynene tørre av kontaktlinser?",
                "answer": "Linsen kan påvirke hvordan tårefilmen fordeler seg over øyet, og redusert blunkefrekvens ved skjermbruk forsterker ofte problemet.",
            },
            {
                "question": "Kan jeg bruke vanlige øyedråper med linsene i?",
                "answer": "Ikke alle øyedråper er trygge å bruke med kontaktlinser i øyet. Bruk kun fukterdråper som er spesifikt beregnet for bruk sammen med kontaktlinser.",
            },
        ],
    },
    "forsta-kontaktlinseresepten": {
        "title": "Slik leser du kontaktlinseresepten din",
        "updated": "2026-08-16",
        "description": "En illustrert forklaring av forkortelsene på en kontaktlinseresept – PWR, BC, DIA, CYL, AXIS og ADD.",
        "body_html": """
<p>Kontaktlinseesken eller resepten din viser gjerne flere tall og forkortelser. Under er
et eksempel – trykk på en verdi for å få den forklart:</p>

<style>
.rx-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 20px 0; }
.rx-cell { display: block; text-decoration: none; background: var(--blue-tint); border: 1px solid var(--border); border-radius: 10px; padding: 14px 8px; text-align: center; }
.rx-cell:hover { border-color: var(--blue); }
.rx-cell-label { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em; color: var(--muted); }
.rx-cell-value { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.15rem; color: var(--ink); margin-top: 2px; }
@media (max-width: 480px) { .rx-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
<div class="rx-grid">
  <a class="rx-cell" href="/guide/pwr-sph-forklart/"><div class="rx-cell-label">PWR</div><div class="rx-cell-value">-2.50</div></a>
  <a class="rx-cell" href="/guide/bc-forklart/"><div class="rx-cell-label">BC</div><div class="rx-cell-value">8.6</div></a>
  <a class="rx-cell" href="/guide/dia-forklart/"><div class="rx-cell-label">DIA</div><div class="rx-cell-value">14.2</div></a>
  <a class="rx-cell" href="/guide/cyl-forklart/"><div class="rx-cell-label">CYL</div><div class="rx-cell-value">-1.25</div></a>
  <a class="rx-cell" href="/guide/axis-forklart/"><div class="rx-cell-label">AXIS</div><div class="rx-cell-value">90</div></a>
  <a class="rx-cell" href="/guide/add-forklart/"><div class="rx-cell-label">ADD</div><div class="rx-cell-value">+1.50</div></a>
</div>
<p style="font-size:0.82rem;color:var(--muted);margin-top:-8px;">Eksempelet er kun illustrativt, ikke en reell resept. Ikke alle linser har alle
verdiene: CYL og AXIS gjelder kun toriske linser (astigmatisme), ADD gjelder kun
multifokale linser (alderssyn).</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Kort om hver verdi</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.9;">
  <li><strong>PWR/SPH</strong> – grunnstyrken, korrigerer nær- eller langsynthet</li>
  <li><strong>BC</strong> – base-kurve, hvor krum linsen er (må passe hornhinnen din)</li>
  <li><strong>DIA</strong> – diameter, linsens bredde fra kant til kant</li>
  <li><strong>CYL</strong> – ekstra styrke som korrigerer astigmatisme (kun toriske linser)</li>
  <li><strong>AXIS</strong> – retningen astigmatisme-korreksjonen skal ligge i</li>
  <li><strong>ADD</strong> – tilleggsstyrke for nærsyn ved alderssyn (kun multifokale linser)</li>
</ul>

<p style="margin-top:16px;">Alle verdiene fastsettes av optikeren din under synsundersøkelsen, og skal alltid
stemme nøyaktig med det du bestiller – se også <a href="/guide/samme-styrke-briller-og-linser/">hvorfor
en brilleresept ikke er det samme som en kontaktlinseresept</a>. Se f.eks.
spesifikasjonstabellen på <a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity
sin produktside</a> for å se hvordan disse verdiene faktisk oppgis på en ekte linse.</p>
""",
        "faq": [
            {
                "question": "Må kontaktlinsene mine ha alle disse verdiene?",
                "answer": "Nei. CYL og AXIS gjelder kun toriske linser for astigmatisme, og ADD gjelder kun multifokale linser for alderssyn. De fleste trenger bare PWR/SPH, BC og DIA.",
            },
            {
                "question": "Hvor finner jeg disse verdiene for mine egne linser?",
                "answer": "De står på resepten din fra synsundersøkelsen hos optiker, og på esken til linsene du allerede bruker.",
            },
        ],
    },
    "bc-forklart": {
        "title": "Hva betyr BC på kontaktlinser?",
        "updated": "2026-08-16",
        "description": "BC (base-kurve) er krumningen på baksiden av kontaktlinsen, og må passe formen på din egen hornhinne.",
        "body_html": """
<p>BC står for base-kurve – krumningsradiusen på baksiden av linsen, målt i millimeter
(typisk mellom 8,3 og 9,0 for myke linser).</p>

<p style="font-size:1rem;line-height:1.7;">BC må passe krumningen på din egen hornhinne. En for flat BC gjør at linsen sitter
løst og beveger seg for mye på øyet. En for brant (stram) BC gjør at linsen sitter for
tett, noe som kan gi ubehag eller redusert oksygentilførsel til hornhinnen.</p>

<p style="margin-top:16px;">BC fastsettes av optikeren din under synsundersøkelsen/linsetilpasningen, og skal
alltid stemme nøyaktig med det som står på resepten din – se også vår
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>.
Et eksempel på en linse med BC 8,6 mm er
<a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a>.</p>
""",
        "faq": [
            {
                "question": "Hva betyr BC på en kontaktlinseeske?",
                "answer": "BC (base-kurve) er krumningsradiusen på baksiden av linsen i millimeter, og må passe krumningen på din egen hornhinne.",
            },
            {
                "question": "Hva skjer hvis BC-verdien er feil?",
                "answer": "For flat BC gjør at linsen sitter løst og beveger seg for mye. For brant BC gjør at linsen sitter for stramt, noe som kan gi ubehag eller redusert oksygentilførsel.",
            },
        ],
    },
    "dia-forklart": {
        "title": "Hva betyr DIA på kontaktlinser?",
        "updated": "2026-08-16",
        "description": "DIA (diameter) er kontaktlinsens totale bredde fra kant til kant, og påvirker hvordan linsen sentrerer seg på øyet.",
        "body_html": """
<p>DIA står for diameter – linsens totale bredde fra kant til kant, målt i millimeter
(typisk mellom 13,5 og 14,5 for myke linser).</p>

<p style="font-size:1rem;line-height:1.7;">Feil diameter påvirker hvordan linsen sentrerer seg på øyet og hvor mye av
hornhinnen den dekker. Sammen med BC (base-kurve) avgjør DIA hvor godt linsen passer
øyeformen din.</p>

<p style="margin-top:16px;">DIA fastsettes av optikeren din under synsundersøkelsen, og skal alltid stemme
nøyaktig med resepten din – se også vår
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>.
Et eksempel på en linse med DIA 14,0 mm er
<a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a>.</p>
""",
        "faq": [
            {
                "question": "Hva betyr DIA på en kontaktlinseeske?",
                "answer": "DIA (diameter) er linsens totale bredde fra kant til kant i millimeter, som påvirker hvordan linsen sentrerer seg og hvor mye av øyet den dekker.",
            },
            {
                "question": "Kan jeg velge en annen DIA enn det som står på resepten min?",
                "answer": "Nei. DIA er fastsatt av optikeren din ut fra din egen øyeform, og skal alltid stemme nøyaktig med resepten.",
            },
        ],
    },
    "pwr-sph-forklart": {
        "title": "Hva betyr PWR og SPH på kontaktlinser?",
        "updated": "2026-08-16",
        "description": "PWR (eller SPH) er grunnstyrken på en kontaktlinse, som korrigerer nær- eller langsynthet.",
        "body_html": """
<p>PWR (power) og SPH (sfære) er to navn på det samme: grunnstyrken til linsen, oppgitt i
dioptrier (D). Ulike produsenter bruker ulik forkortelse på pakningen.</p>

<p style="font-size:1rem;line-height:1.7;">Et <strong>negativt tall</strong> (f.eks. -2,50) betyr at linsen korrigerer
nærsynthet. Et <strong>positivt tall</strong> (f.eks. +1,50) betyr at den korrigerer
langsynthet. Jo høyere tall, jo sterkere korreksjon.</p>

<p style="margin-top:16px;">PWR/SPH fastsettes av optikeren din under synsundersøkelsen – se også vår
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>.
Styrkeområdet en linse dekker står oppgitt under spesifikasjoner på hver produktside,
f.eks. hos <a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a>.</p>
""",
        "faq": [
            {
                "question": "Hva er forskjellen på PWR og SPH?",
                "answer": "Ingen – det er to ulike navn for det samme: linsens grunnstyrke i dioptrier. Ulike produsenter bruker ulik forkortelse på pakningen.",
            },
            {
                "question": "Hva betyr et negativt tall på kontaktlinsestyrken?",
                "answer": "Et negativt tall betyr at linsen korrigerer nærsynthet. Et positivt tall betyr at den korrigerer langsynthet.",
            },
        ],
    },
    "cyl-forklart": {
        "title": "Hva betyr CYL på kontaktlinser?",
        "updated": "2026-08-16",
        "description": "CYL (sylinder) angir styrken på astigmatisme-korreksjonen i en torisk kontaktlinse.",
        "body_html": """
<p>CYL står for sylinder, og angir hvor mye ekstra styrke som trengs for å korrigere
astigmatisme (skjev hornhinne). Verdien gjelder kun toriske linser – har du ikke
astigmatisme, har resepten din normalt ingen CYL-verdi.</p>

<p style="font-size:1rem;line-height:1.7;">CYL brukes alltid sammen med en <a href="/guide/axis-forklart/">AXIS-verdi</a>,
som angir i hvilken retning korreksjonen skal ligge. De to henger sammen og må begge
stemme for at linsen skal fungere riktig.</p>

<p style="margin-top:16px;">Se vår <a href="/guide/kontaktlinser-med-astigmatisme/">guide om toriske linser og
astigmatisme</a> for mer om hvordan dette fungerer i praksis, eller sammenlign priser på
en torisk linse som <a href="/kontaktlinser/acuvue/acuvue-oasys-for-astigmatism-6-pack/">Acuvue
Oasys for Astigmatism</a>.</p>
""",
        "faq": [
            {
                "question": "Hva betyr CYL på en kontaktlinseresept?",
                "answer": "CYL (sylinder) angir hvor mye ekstra styrke som trengs for å korrigere astigmatisme. Verdien gjelder kun toriske linser.",
            },
            {
                "question": "Kan jeg ha en CYL-verdi uten AXIS?",
                "answer": "Nei, CYL og AXIS brukes alltid sammen – AXIS angir retningen CYL-korreksjonen skal ligge i.",
            },
        ],
    },
    "axis-forklart": {
        "title": "Hva betyr AXIS på kontaktlinser?",
        "updated": "2026-08-16",
        "description": "AXIS angir i hvilken retning astigmatisme-korreksjonen i en torisk kontaktlinse skal ligge.",
        "body_html": """
<p>AXIS (også skrevet AX) angir i hvilken retning, oppgitt i grader fra 0 til 180,
astigmatisme-korreksjonen i linsen skal ligge. Verdien brukes alltid sammen med
<a href="/guide/cyl-forklart/">CYL</a>, og gjelder kun toriske linser.</p>

<p style="font-size:1rem;line-height:1.7;">Toriske linser er formet for å ligge stabilt i én bestemt retning på øyet (i
motsetning til vanlige linser, som kan rotere fritt uten at det merkes). AXIS forteller
linsen nøyaktig hvilken retning den skal stå i for at korreksjonen skal fungere riktig.</p>

<p style="margin-top:16px;">Se vår <a href="/guide/kontaktlinser-med-astigmatisme/">guide om toriske linser og
astigmatisme</a> for mer om hvorfor dette er litt mer krevende å tilpasse enn vanlige
linser, eller sammenlign priser på en torisk linse som
<a href="/kontaktlinser/biofinity/biofinity-toric-6-pack/">Biofinity Toric</a>.</p>
""",
        "faq": [
            {
                "question": "Hva betyr AXIS på en kontaktlinseresept?",
                "answer": "AXIS angir i hvilken retning (0–180 grader) astigmatisme-korreksjonen i linsen skal ligge. Brukes alltid sammen med CYL, og gjelder kun toriske linser.",
            },
            {
                "question": "Hvorfor er AXIS viktig for toriske linser?",
                "answer": "Toriske linser må ligge stabilt i riktig retning på øyet for at korreksjonen skal fungere. AXIS forteller linsen nøyaktig hvilken retning det er.",
            },
        ],
    },
    "add-forklart": {
        "title": "Hva betyr ADD på kontaktlinser?",
        "updated": "2026-08-16",
        "description": "ADD er tilleggsstyrken for nærsyn i en multifokal kontaktlinse, brukt til å korrigere alderssyn.",
        "body_html": """
<p>ADD (addisjon/tillegg) er en ekstra styrkeverdi som legges til grunnstyrken
(<a href="/guide/pwr-sph-forklart/">PWR/SPH</a>) for å korrigere alderssyn (presbyopi).
Verdien gjelder kun multifokale/progressive kontaktlinser.</p>

<p style="font-size:1rem;line-height:1.7;">ADD oppgis alltid som et positivt tall (f.eks. +1,50), og angir hvor mye ekstra
styrke øyet trenger for å se skarpt på nært hold, i tillegg til grunnkorreksjonen for
langt hold.</p>

<p style="margin-top:16px;">Se vår <a href="/guide/multifokale-kontaktlinser/">guide om multifokale kontaktlinser
ved alderssyn</a> for mer om hvordan disse linsene fungerer, eller sammenlign priser på en
multifokal linse som
<a href="/kontaktlinser/acuvue/acuvue-oasys-multifocal-6-pack/">Acuvue Oasys Multifocal</a>.</p>
""",
        "faq": [
            {
                "question": "Hva betyr ADD på en kontaktlinseresept?",
                "answer": "ADD er en ekstra styrkeverdi som legges til grunnstyrken for å korrigere alderssyn (presbyopi). Gjelder kun multifokale/progressive kontaktlinser.",
            },
            {
                "question": "Hvorfor er ADD alltid et positivt tall?",
                "answer": "Fordi det angir hvor mye ekstra pluss-styrke øyet trenger for å se skarpt på nært hold, uavhengig av om grunnstyrken (PWR/SPH) i seg selv er positiv eller negativ.",
            },
        ],
    },
    "hvor-lenge-kan-man-bruke-kontaktlinser": {
        "title": "Hvor lenge kan man bruke kontaktlinser om dagen?",
        "updated": "2026-08-16",
        "description": "Retningslinjer for daglig brukstid for kontaktlinser, og tegn på at du bør ta dem ut tidligere.",
        "body_html": """
<p>De fleste tåler myke kontaktlinser komfortabelt i rundt 12–14 timer sammenhengende, men
den nøyaktige grensen avhenger av linsetype, materiale og hva optikeren din har godkjent
for akkurat dine linser – følg alltid den anbefalingen fremfor et generelt tall.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Tegn på at du bør ta ut linsene tidligere</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Tørrhet eller irritasjon</li>
  <li>Rødhet</li>
  <li>Uklart syn</li>
  <li>Generelt ubehag</li>
</ul>

<p style="margin-top:16px;">Gi gjerne øynene linsefri tid når du kan, for eksempel om kvelden hjemme. Uansett
brukstid gjelder samme regel: vanlige linser er ikke ment for sammenhengende bruk døgnet
rundt – se vår <a href="/guide/kan-man-sove-med-kontaktlinser/">guide om å sove med
kontaktlinser</a>. Bruker du en dagslinse som
<a href="/kontaktlinser/soflens/soflens-daily-disposable-30-pack/">SofLens Daily
Disposable</a>, setter du uansett inn et helt nytt par neste dag.</p>
""",
        "faq": [
            {
                "question": "Hvor mange timer om dagen kan jeg bruke kontaktlinser?",
                "answer": "De fleste tåler myke linser komfortabelt i rundt 12–14 timer, men følg alltid optikerens spesifikke anbefaling for akkurat dine linser fremfor et generelt tall.",
            },
            {
                "question": "Hva er tegn på at jeg bør ta ut linsene tidligere enn planlagt?",
                "answer": "Tørrhet, irritasjon, rødhet, uklart syn eller generelt ubehag er alle tegn på at du bør ta ut linsene og gi øynene en pause.",
            },
        ],
    },
    "samme-styrke-briller-og-linser": {
        "title": "Kan jeg bruke samme styrke på kontaktlinser som på briller?",
        "updated": "2026-08-16",
        "description": "Hvorfor brillestyrken din vanligvis ikke kan brukes direkte på kontaktlinser, og hvorfor en egen synsundersøkelse trengs.",
        "body_html": """
<p>Vanligvis <strong>nei</strong> – ikke direkte. Briller sitter omtrent 12 mm fra øyet,
mens kontaktlinser ligger rett på hornhinnen. Denne avstanden (kalt vertexavstand)
påvirker hvor sterk korreksjonen faktisk oppleves, spesielt ved høyere styrker (grovt sett
fra rundt ±4,00 dioptrier og oppover blir forskjellen merkbar).</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Kontaktlinseresept er mer enn bare styrke</h2>
<p style="font-size:1rem;line-height:1.7;">En kontaktlinseresept inkluderer også BC og DIA (se vår
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>)
– mål som en brilleresept ikke har. Dette krever en egen synsundersøkelse/linsetilpasning,
ikke bare et gjenbruk av brilletallene.</p>

<p style="margin-top:16px;">Når du har fått en egen kontaktlinseresept, kan du søke opp nøyaktig det produktet
optikeren har satt deg opp med – for eksempel er
<a href="/kontaktlinser/dailies/focus-dailies-90-pack/">Focus Dailies 90-pack</a> en mye
brukt dagslinse blant nye linsebrukere – og sammenligne priser fra flere norske
nettbutikker.</p>

<p style="margin-top:16px;">Kort sagt: bruk alltid en resept som er satt opp spesifikt for kontaktlinser, ikke
brillestyrken din.</p>
""",
        "faq": [
            {
                "question": "Kan jeg bare bruke brillestyrken min på kontaktlinser?",
                "answer": "Vanligvis ikke direkte. Avstanden mellom brilleglass og øye (vertexavstand) gjør at effektiv styrke ofte må justeres, spesielt ved høyere styrker. Kontaktlinser trenger også BC og DIA, som ikke finnes på en brillereseptet.",
            },
            {
                "question": "Hvorfor trengs en egen synsundersøkelse for kontaktlinser?",
                "answer": "Fordi en optiker da måler hornhinnens krumning (for riktig BC) og bekrefter riktig passform – ikke bare styrken, slik en vanlig synsundersøkelse for briller gjør.",
            },
        ],
    },
    "hva-koster-kontaktlinser": {
        "title": "Hva koster kontaktlinser?",
        "updated": "2026-08-16",
        "description": "Hvorfor det ikke finnes ett fast svar på hva kontaktlinser koster, og hva som faktisk avgjør prisen.",
        "body_html": """
<p>Det finnes ikke ett fast svar – prisen på kontaktlinser varierer mye ut fra
linsetype, merke, pakningsstørrelse og hvilken forhandler du velger. To ulike
kontaktlinser kan koste svært forskjellig selv om de dekker samme synsbehov.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva som påvirker prisen</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li><strong>Merke og teknologi</strong> – nyere materialer (f.eks. silikonhydrogel) koster
  ofte mer enn eldre</li>
  <li><strong>Linsetype</strong> – dagslinser koster mer per linse enn månedslinser, men kan
  likevel lønne seg avhengig av brukshyppighet</li>
  <li><strong>Pakningsstørrelse</strong> – større pakninger har ofte (men ikke alltid) lavere
  pris per linse</li>
  <li><strong>Forhandler</strong> – prisene varierer mellom butikker og endrer seg over tid</li>
</ul>

<p style="margin-top:16px;">Den mest pålitelige måten å finne riktig pris for akkurat dine linser er å søke dem
opp direkte – bruk søkefeltet på <a href="/">forsiden</a> for å sammenligne
oppdaterte priser fra norske nettbutikker. Se f.eks. gjeldende pris på
<a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a> eller
<a href="/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/">Acuvue Moist</a> som konkrete eksempler.</p>
""",
        "faq": [
            {
                "question": "Hvorfor er det ikke ett fast svar på hva kontaktlinser koster?",
                "answer": "Prisen varierer mye ut fra linsetype, merke, pakningsstørrelse og forhandler. To ulike linser kan koste svært forskjellig selv om de dekker samme synsbehov.",
            },
            {
                "question": "Hvordan finner jeg riktig pris for akkurat mine linser?",
                "answer": "Søk opp navnet fra esken din på forsiden av Kontaktlinser.no for å se oppdaterte priser fra norske nettbutikker, sortert etter lavest pris. Slå på «Pris inkludert frakt» for å se totalprisen.",
            },
        ],
    },
    "pakningsstorrelse-30-vs-90": {
        "title": "30 vs. 90-pakning – hva lønner seg?",
        "updated": "2026-08-16",
        "description": "Er større pakninger alltid billigst per linse? Slik vurderer du pakningsstørrelse riktig.",
        "body_html": """
<p>Større pakninger har ofte lavere pris per linse, siden mange produsenter og
forhandlere gir en viss mengderabatt – men <strong>ikke alltid</strong>. Det lønner seg å
faktisk sjekke pris per linse for pakningsstørrelsene du vurderer, i stedet for å anta.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Ting å vurdere utover prisen</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>En stor pakning krever høyere engangsutlegg</li>
  <li>Hvis styrken din endrer seg, kan du sitte igjen med ubrukte linser</li>
  <li>Sjekk holdbarhetsdato hvis du kjøper en stor pakning du bruker sjelden</li>
</ul>

<p style="margin-top:16px;">Se vår <a href="/guide/pris-per-linse-slik-sammenligner-du/">guide om å sammenligne
pris per linse</a> for hvordan du regner ut det reelle sammenligningsgrunnlaget. Et
eksempel på et produkt som finnes i begge størrelser er
<a href="/kontaktlinser/dailies/focus-dailies-30-pack/">Focus Dailies 30-pack</a> og
<a href="/kontaktlinser/dailies/focus-dailies-90-pack/">90-pack</a>.</p>
""",
        "faq": [
            {
                "question": "Er 90-pakning alltid billigere per linse enn 30-pakning?",
                "answer": "Ofte, men ikke alltid. Det lønner seg å sjekke pris per linse direkte for produktene du vurderer, i stedet for å anta at større pakning automatisk er billigst.",
            },
            {
                "question": "Hva bør jeg tenke på før jeg kjøper en stor pakning?",
                "answer": "Høyere engangsutlegg, at styrken din kan endre seg over tid, og holdbarhetsdato hvis du bruker linser sjelden.",
            },
        ],
    },
    "pris-per-linse-slik-sammenligner-du": {
        "title": "Pris per linse – slik sammenligner du riktig",
        "updated": "2026-08-16",
        "description": "Hvorfor du bør se på pris per linse i stedet for kun pakningspris, med et enkelt regneeksempel.",
        "body_html": """
<p>Når du sammenligner kontaktlinsepriser – spesielt på tvers av ulike pakningsstørrelser
eller produkter – gir pakningsprisen alene et misvisende bilde. Del alltid totalprisen på
antall linser i pakningen for en reell sammenligning.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Eksempel (kun illustrativt, ikke reelle priser)</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>30-pakning til 300 kr = 10 kr per linse</li>
  <li>90-pakning til 750 kr = 8,33 kr per linse</li>
</ul>
<p style="font-size:1rem;line-height:1.7;">Selv om 90-pakningen koster mer totalt, er den billigst per linse i dette eksempelet.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Omtrentlig månedskostnad</h2>
<p style="font-size:1rem;line-height:1.7;">Gang pris per linse med hvor mange du faktisk bruker per måned. Dette varierer mye
mellom dagslinser (én linse per brukt dag) og månedslinser (typisk to linser per måned,
én per øye) – se vår <a href="/guide/manedslinser-vs-dagslinser/">guide om månedslinser
vs. dagslinser</a> for brukshyppighet. Se ekte, oppdatert pris per pakning for en
månedslinse som <a href="/kontaktlinser/ultra/ultra-6-pack/">Ultra 6-pack</a> som
konkret eksempel.</p>
""",
        "faq": [
            {
                "question": "Hvorfor bør jeg se på pris per linse i stedet for pakningsprisen?",
                "answer": "Fordi det gir et reelt sammenligningsgrunnlag på tvers av ulike pakningsstørrelser og produkter – pakningsprisen alene kan gi et misvisende bilde av hva som faktisk lønner seg.",
            },
            {
                "question": "Hvordan regner jeg ut omtrentlig månedskostnad?",
                "answer": "Gang pris per linse med hvor mange linser du faktisk bruker per måned – dette varierer mye mellom dagslinser og månedslinser.",
            },
        ],
    },
    "hvorfor-varierer-prisene-mellom-butikkene": {
        "title": "Hvorfor varierer prisene på kontaktlinser mellom butikkene?",
        "updated": "2026-08-16",
        "description": "Hvorfor samme kontaktlinse kan koste ulikt hos forskjellige norske nettbutikker.",
        "body_html": """
<p>Samme kontaktlinse kan koste ulikt fra butikk til butikk, av flere grunner:</p>

<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Ulike innkjøpsavtaler og volum med produsenten</li>
  <li>Ulike driftskostnader og fraktpolitikk</li>
  <li>Tidsbegrensede kampanjer og tilbud</li>
  <li>Hvor ofte den enkelte butikken oppdaterer sine egne priser</li>
</ul>

<p style="margin-top:16px;">Dette er nettopp derfor det lønner seg å sammenligne på tvers av butikker i stedet for
å handle hos den første man kommer over. Prisene kan også endre seg fra dag til dag – vi
oppdaterer prisene daglig. Se f.eks.
<a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a> for et konkret
eksempel på hvor mye prisen faktisk varierer mellom butikkene akkurat nå.</p>
""",
        "faq": [
            {
                "question": "Hvorfor koster samme kontaktlinse ulikt hos forskjellige butikker?",
                "answer": "Ulike innkjøpsavtaler, driftskostnader, fraktpolitikk og tidsbegrensede kampanjer gjør at prisen på samme linse kan variere mellom forhandlere.",
            },
            {
                "question": "Hvor ofte endrer prisene seg?",
                "answer": "Prisene kan endre seg fra dag til dag. Kontaktlinser.no oppdaterer prisene fra forhandlerne daglig.",
            },
        ],
    },
    "hvordan-kontaktlinser-no-beregner-totalpris": {
        "title": "Hvordan Kontaktlinser.no beregner totalpris",
        "updated": "2026-08-16",
        "description": "Slik ser du totalprisen (produktpris + frakt) med «Pris inkludert frakt», og hvorfor den kan gi et annet resultat enn produktpris alene.",
        "body_html": """
<p>Kontaktlinser.no viser produktprisen uten frakt som standard, slik du er vant til fra
andre prissammenlignere. Slår du på <strong>«Pris inkludert frakt»</strong> over prislisten,
viser og sorterer vi i stedet etter <strong>totalpris</strong> – produktpris pluss frakt – for
antallet du har valgt. Det kan endre hvilken butikk som er billigst.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Eksempel (kun illustrativt, ikke reelle priser)</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Butikk A: produktpris 250 kr + frakt 79 kr = <strong>329 kr</strong> totalt</li>
  <li>Butikk B: produktpris 265 kr + gratis frakt = <strong>265 kr</strong> totalt</li>
</ul>
<p style="font-size:1rem;line-height:1.7;">Selv om Butikk A har lavest produktpris, er Butikk B faktisk billigst når frakt regnes
med. Ser du kun på produktprisen direkte hos hver butikk, kan du lett ende opp med det
dyreste alternativet uten å vite det.</p>

<p style="margin-top:16px;">Varer uten bekreftet lagerstatus kan ikke vinne merket «laveste pris», og hvert tilbud viser
når det sist ble kontrollert. Vi oppdaterer prisene daglig. Se et
ekte eksempel på <a href="/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack/">Acuvue Moist</a> sin
produktside for å se totalpris-regnestykket i praksis.</p>
""",
        "faq": [
            {
                "question": "Hvorfor kan jeg slå på «Pris inkludert frakt»?",
                "answer": "Fordi frakt er en reell del av det du faktisk betaler, og kan endre hvilken butikk som egentlig er billigst – en lav produktpris med høy frakt kan ende opp dyrere enn en høyere produktpris med gratis frakt.",
            },
            {
                "question": "Hvor ofte oppdateres prisene?",
                "answer": "Vi oppdaterer prisene fra forhandlerne daglig.",
            },
        ],
    },
    "kontaktlinseabonnement-vs-kjope-selv": {
        "title": "Kontaktlinseabonnement eller kjøpe selv – hva lønner seg?",
        "updated": "2026-08-16",
        "description": "Fordeler og ulemper ved abonnement på kontaktlinser sammenlignet med å bestille selv hver gang.",
        "body_html": """
<p>Flere forhandlere tilbyr abonnement/fast levering av kontaktlinser, noen ganger med
rabatt. Om det lønner seg avhenger av hva du prioriterer.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Fordeler med abonnement</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Slipper å huske å bestille på nytt</li>
  <li>Kan gi en fast rabatt hos enkelte forhandlere</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva du bør vite</h2>
<p style="font-size:1rem;line-height:1.7;">Et abonnement binder deg til én forhandlers pris, mens priser generelt varierer
mellom butikker og over tid. Abonnementsprisen er derfor ikke nødvendigvis den laveste
tilgjengelige til enhver tid. Sjekk gjerne jevnlig om abonnementsprisen din for f.eks.
<a href="/kontaktlinser/ultra/ultra-6-pack/">Ultra 6-pack</a> fortsatt er
konkurransedyktig ved å sammenligne <a href="/">hos oss</a>.</p>
""",
        "faq": [
            {
                "question": "Er abonnement alltid billigere enn å kjøpe selv?",
                "answer": "Ikke nødvendigvis. Et abonnement binder deg til én forhandlers pris, som ikke alltid er den laveste tilgjengelige til enhver tid – det avhenger av rabatten og hvordan prisene beveger seg over tid.",
            },
            {
                "question": "Kan jeg si opp et linseabonnement når jeg vil?",
                "answer": "Det varierer mellom forhandlere – sjekk vilkårene hos den aktuelle butikken. Kontaktlinser.no har ingen avtale med forhandlerne om dette.",
            },
        ],
    },
    "hvordan-kjope-kontaktlinser-pa-nett": {
        "title": "Hvordan kjøpe kontaktlinser på nett",
        "updated": "2026-08-16",
        "description": "Stegene for å bestille kontaktlinser trygt på nett, fra resept til fullført kjøp hos forhandler.",
        "body_html": """
<p>Å bestille kontaktlinser på nett er enkelt når du vet hva du trenger:</p>

<ol style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.9;">
  <li>Ha en gyldig resept fra optiker eller øyelege (styrke, BC, DIA, og ev. CYL/AXIS/ADD
  – se vår <a href="/guide/forsta-kontaktlinseresepten/">guide om å lese resepten din</a>)</li>
  <li>Finn riktig produkt – søk opp navnet fra esken din på <a href="/">forsiden</a> vår,
  f.eks. <a href="/kontaktlinser/biofinity/biofinity-6-pack/">Biofinity</a></li>
  <li>Sammenlign totalpris hos norske forhandlere</li>
  <li>Velg forhandler og fullfør kjøpet hos dem</li>
</ol>

<p style="margin-top:16px;">Kontaktlinser.no selger ikke kontaktlinser selv – vi sammenligner priser og sender deg
videre til forhandleren, som håndterer selve kjøpet, betaling, levering og eventuell
retur.</p>
""",
        "faq": [
            {
                "question": "Hva trenger jeg for å bestille kontaktlinser på nett?",
                "answer": "En gyldig resept fra optiker eller øyelege med styrke, BC og DIA (og ev. CYL, AXIS eller ADD avhengig av linsetype).",
            },
            {
                "question": "Fullfører jeg kjøpet hos Kontaktlinser.no?",
                "answer": "Nei. Vi sammenligner priser og sender deg videre til forhandleren du velger, som håndterer selve kjøpet, betaling og levering.",
            },
        ],
    },
    "kan-man-kjope-kontaktlinser-uten-resept": {
        "title": "Kan man kjøpe kontaktlinser uten resept?",
        "updated": "2026-08-16",
        "description": "Kontaktlinser regnes som medisinsk utstyr i Norge og krever gyldig resept, også uten styrke.",
        "body_html": """
<p><strong>Nei.</strong> Kontaktlinser regnes som medisinsk utstyr i Norge, og krever
gyldig resept/tilpasning fra optiker eller øyelege – dette gjelder også linser uten
styrke, som fargede kosmetiske linser.</p>

<p style="font-size:1rem;line-height:1.7;">Seriøse forhandlere ber om resept-informasjon ved bestilling. Kjøp fra useriøse
kilder som ikke krever dette frarådes – det øker risikoen for feil passform eller styrke,
og dermed for øyeirritasjon eller -skade. Selv en fargelinse uten styrke, som
<a href="/kontaktlinser/freshlook/freshlook-oneday-30-pack/">FreshLook OneDay</a>, krever
altså gyldig resept.</p>
""",
        "faq": [
            {
                "question": "Må jeg ha resept for linser uten styrke?",
                "answer": "Ja. Selv fargede kosmetiske linser uten synskorreksjon regnes som medisinsk utstyr og krever gyldig tilpasning hos optiker.",
            },
            {
                "question": "Hva bør jeg tenke hvis en nettbutikk ikke spør om resept?",
                "answer": "Det er et varselstegn. Unngå forhandlere som ikke krever resept-informasjon ved bestilling.",
            },
        ],
    },
    "kan-jeg-bytte-kontaktlinsemerke-selv": {
        "title": "Kan jeg bytte kontaktlinsemerke selv?",
        "updated": "2026-08-16",
        "description": "Hvorfor det ikke anbefales å bytte til et «tilsvarende» kontaktlinsemerke på egen hånd, selv med lik styrke.",
        "body_html": """
<p>Det anbefales <strong>ikke</strong> å bytte til et annet merke helt på egen hånd, selv
om styrken (PWR/SPH) er den samme. Ulike merker kan ha ulik BC, DIA, materiale og
linsedesign – alt dette påvirker hvordan linsen faktisk sitter og føles, ikke bare
styrken.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Unntaket: private label</h2>
<p style="font-size:1rem;line-height:1.7;">Hvis det er snakk om nøyaktig samme fysiske linse solgt under et annet navn (f.eks. en
optikerkjedes eget merke), er dette noe annet enn å faktisk bytte produkt – se vår
<a href="/private-label/">oversikt over optikerkjedenes egne merker</a>.</p>

<p style="margin-top:16px;">Vurderer du et helt annet produkt, ta det opp med optikeren din først.</p>
""",
        "faq": [
            {
                "question": "Kan jeg bytte til et billigere merke med samme styrke?",
                "answer": "Ikke uten å sjekke med optiker først. BC, DIA og materiale kan variere mellom merker selv ved lik styrke, og påvirker hvordan linsen faktisk sitter.",
            },
            {
                "question": "Er det trygt å bytte til en private label-versjon av linsen min?",
                "answer": "Ja, hvis det er nøyaktig samme fysiske linse solgt under et annet navn – se vår oversikt over optikerkjedenes egne merker. Det er noe annet enn å bytte til et faktisk ulikt produkt.",
            },
        ],
    },
    "linse-sitter-fast-i-oyet": {
        "title": "Linse sitter fast i øyet? Gjør dette (og ikke dette)",
        "updated": "2026-09-05",
        "description": "Som regel ufarlig – linsen har bare tørket ut eller flyttet seg. Se de trygge stegene for å løsne den, og når du heller bør oppsøke optiker med det samme.",
        "body_html": """
<p>Kjennes linsen "fastlåst" i øyet, har den som regel bare tørket litt ut eller flyttet seg
til et annet sted i øyet enn du er vant til å finne den. Det er ikke farlig i seg selv, men
det finnes en riktig og en gal måte å håndtere det på.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Vanlige grunner</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Linsen har tørket ut – ofte fordi den har vært i øyet lenger enn de anbefalte ca. 8 timene mange eksperter fraråder å overskride, eller fordi øyet er tørt</li>
  <li>Linsen har gled opp under det øvre øyelokket</li>
  <li>Du blunker mye og stresser, som gjør det vanskeligere å kjenne hvor linsen faktisk er</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Slik gjør du det trygt</h2>
<ol style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Vask hendene grundig først</li>
  <li>Fukt øyet med linsevæske eller øyedråper laget for bruk med kontaktlinser</li>
  <li>Lukk øyet og masser forsiktig på det lukkede øyelokket i noen sekunder</li>
  <li>Blunk rolig mens du ser opp, ned og til siden – linsen glir ofte tilbake av seg selv</li>
</ol>

<div style="background:#FFF4E5;border:1px solid #F0C674;border-radius:12px;padding:14px 16px;margin:16px 0;font-size:0.85rem;line-height:1.6;color:var(--ink);">
<strong>Ikke gni hardt i øyet, og bruk aldri pinsett, nål eller andre spisse gjenstander</strong> for å
få tak i linsen. Løsner den ikke etter noen forsøk, eller du kjenner smerte eller ser
rødhet, bør du oppsøke optiker, øyelege eller legevakt samme dag – ikke vent og se an.
</div>

<p style="margin-top:16px;">Er du usikker på om linsen faktisk er ute av øyet, kan optikeren enkelt sjekke dette med
en lampe – det er ikke noe å kvie seg for å spørre om.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">Ifølge <a href="https://nhi.no/sykdommer/oye/brytningsfeil-nedsatt-syn/kontaktlinser" target="_blank" rel="noopener">Norsk Helseinformatikk (NHI)</a> gjelder denne enkle tommelfingerregelen for når du bør oppsøke lege:</p>

<blockquote cite="https://nhi.no/sykdommer/oye/brytningsfeil-nedsatt-syn/kontaktlinser" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Kontakt lege dersom du har hatt ubehag over lengre tid eller dersom øynene dine er røde eller såre.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://nhi.no/sykdommer/oye/brytningsfeil-nedsatt-syn/kontaktlinser" target="_blank" rel="noopener">NHI, Kontaktlinser</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Kan linsen forsvinne bak i øyet?",
                "answer": "Nei, det er anatomisk umulig. Slimhinnen (konjunktiva) danner en sammenhengende, lukket lomme rundt selve øyeeplet, så en kontaktlinse kan aldri havne bak øyet.",
            },
            {
                "question": "Hvor lenge kan jeg prøve selv før jeg oppsøker optiker?",
                "answer": "Noen få forsiktige forsøk med fukt og massering er greit. Kjenner du smerte, ser rødhet, eller linsen ikke løsner, bør du oppsøke optiker eller legevakt samme dag i stedet for å fortsette å prøve selv.",
            },
        ],
    },
    "uklart-syn-med-kontaktlinser": {
        "title": "Uklart eller tåkete syn med kontaktlinser – vanlige årsaker",
        "updated": "2026-08-17",
        "description": "De vanligste, ufarlige årsakene til at synet blir uklart med kontaktlinser i, og hvilke tegn du bør ta på alvor.",
        "body_html": """
<p>Plutselig uklart syn med linsene i er sjelden alvorlig, og skyldes som regel noe enkelt
og ufarlig. Det finnes likevel noen kombinasjoner av symptomer du bør ta på alvor.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Vanlige, ufarlige årsaker</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Skitten linse, eller avleiringer (protein/fett fra tårevæsken) på overflaten</li>
  <li>Linsen ligger vrengt (inni ut)</li>
  <li><a href="/guide/kontaktlinser-og-torre-oyne/">Tørre øyne</a></li>
  <li>Linsen er brukt lenger enn anbefalt bytteintervall</li>
  <li>Styrken stemmer ikke lenger – synet endrer seg gradvis over tid for de fleste</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Enkle ting å sjekke først</h2>
<ol style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Blunk noen ganger, og bruk fukterdråper beregnet for kontaktlinser</li>
  <li>Ta ut linsen, sjekk at den ikke er vrengt, rengjør og sett den inn på nytt</li>
  <li>Bytt til en ny linse hvis den nærmer seg slutten av byttesyklusen</li>
</ol>

<p style="margin-top:16px;">Går avleiringer på linseoverflaten igjen ofte, kan en dagslinse være verdt å vurdere –
med f.eks. <a href="/kontaktlinser/soflens/soflens-daily-disposable-30-pack/">SofLens Daily
Disposable</a> setter du inn et helt nytt, rent par hver dag, så problemet oppstår
sjeldnere.</p>

<div style="background:#FFF4E5;border:1px solid #F0C674;border-radius:12px;padding:14px 16px;margin:16px 0;font-size:0.85rem;line-height:1.6;color:var(--ink);">
Kommer det uklare synet <strong>plutselig, sammen med smerte, rødhet, lysfølsomhet eller
sekret</strong>, kan det være tegn på en øyeinfeksjon eller annen tilstand som trenger rask
behandling. Ta av linsen og oppsøk optiker eller lege samme dag.
</div>

<p style="margin-top:16px;">Har synet endret seg gradvis over lengre tid uten andre symptomer, er det oftest bare
tegn på at det er på tide med en ny synsundersøkelse.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">NHI sin veiviser for røde øyne lister opp konkrete varseltegn under overskriften «Tegn på alvorlig øyesykdom» – redusert syn er ett av dem:</p>

<blockquote cite="https://nhi.no/symptomer/infeksjoner/rodt-oye-veiviser" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Redusert syn, lysskyhet.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://nhi.no/symptomer/infeksjoner/rodt-oye-veiviser" target="_blank" rel="noopener">NHI, Rødt øye – veiviser</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Er tåkete syn med kontaktlinser farlig?",
                "answer": "Som regel ikke – oftest skyldes det en skitten eller feilvendt linse. Men kommer det plutselig sammen med smerte, rødhet eller lysfølsomhet, bør du oppsøke optiker eller lege samme dag.",
            },
            {
                "question": "Hvorfor blir linsen skitten så fort?",
                "answer": "Protein og fett fra tårevæsken legger seg naturlig på linseoverflaten over tid. Daglinser byttes derfor hver dag, mens måneds- og ukelinser trenger grundig rengjøring med linsevæske underveis.",
            },
        ],
    },
    "rode-oyne-og-svie-med-kontaktlinser": {
        "title": "Røde øyne og svie med kontaktlinser – når bør du oppsøke optiker?",
        "updated": "2026-08-17",
        "description": "Vanlige, mildere årsaker til røde og sviende øyne med kontaktlinser, og de varseltegnene som betyr at du bør oppsøke optiker samme dag.",
        "body_html": """
<p>Lett rødhet og svie er ganske vanlig blant kontaktlinsebrukere og som regel ufarlig. Som
linsebruker er det likevel lurt å kjenne igjen når symptomene betyr at du bør handle raskt.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Vanlige, mildere årsaker</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>For lang brukstid i løpet av dagen – eksperter fraråder generelt mer enn ca. 8 timer sammenhengende bruk</li>
  <li>Tørt inneklima eller lange skjermøkter</li>
  <li>Lett irritasjon fra en avleiring på linsekanten</li>
  <li>Allergi (pollen, støv) som forsterkes av linsebruk</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva du bør gjøre</h2>
<ol style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Ta av linsen med en gang du kjenner ubehag</li>
  <li>Gi øyet en pause – ikke sett inn en ny linse samme dag hvis irritasjonen ikke er helt borte</li>
  <li>Bruk fukterdråper beregnet for kontaktlinser om det hjelper, som
  <a href="/oyedraper/systane/systane-ultra-10-ml/">Systane Ultra</a></li>
</ol>

<div style="background:#FFF4E5;border:1px solid #F0C674;border-radius:12px;padding:14px 16px;margin:16px 0;font-size:0.85rem;line-height:1.6;color:var(--ink);">
<strong>Oppsøk optiker, lege eller legevakt samme dag</strong> hvis du i tillegg opplever smerte
(ikke bare ubehag), kraftig rødhet, lysfølsomhet, sekret, eller følelsen av at noe fortsatt
er i øyet etter at linsen er tatt av. Dette kan være tegn på en øyeinfeksjon, som ubehandlet
kan bli alvorlig. Tommelfingerregelen er enkel: er du i tvil, ta linsen ut.
</div>

<p style="margin-top:16px;">Sov aldri med linser som ikke er godkjent for det, bruk aldri springvann eller spytt på
en linse, bytt linseetuiet hvert 3. måned, og hold deg til anbefalt bytteintervall for
linse og væske – det reduserer risikoen for at dette oppstår i utgangspunktet.</p>

<p style="margin-top:16px;font-size:0.92rem;line-height:1.7;">Ifølge <a href="https://www.helsenorge.no/sykdom/oyesykdommer/oyekatarr/" target="_blank" rel="noopener">Helsenorge</a>, den offentlige norske helseportalen, gjelder følgende anbefaling for kontaktlinsebrukere med tegn på øyekatarr:</p>

<blockquote cite="https://www.helsenorge.no/sykdom/oyesykdommer/oyekatarr/" style="border-left:3px solid var(--blue);margin:16px 0;padding:4px 0 4px 16px;font-size:0.9rem;color:var(--ink);">
  <p style="margin:0;">Bruker du kontaktlinser og merker symptomer på øyekatarr, bør du ta ut kontaktlinsene og raskt oppsøke lege.</p>
  <footer style="font-size:0.8rem;color:var(--muted);margin-top:6px;">&mdash; <cite><a href="https://www.helsenorge.no/sykdom/oyesykdommer/oyekatarr/" target="_blank" rel="noopener">Helsenorge, Øyekatarr (konjunktivitt)</a></cite></footer>
</blockquote>
""",
        "faq": [
            {
                "question": "Kan jeg bare vente på at rødheten går over?",
                "answer": "Ved mild, kortvarig rødhet uten smerte, ja – ta av linsen og gi øyet en pause. Vedvarer rødheten mer enn en dag, eller kommer det sammen med smerte, lysfølsomhet eller sekret, bør du oppsøke optiker eller lege i stedet for å vente.",
            },
            {
                "question": "Hvorfor tas rødhet med kontaktlinser mer alvorlig enn vanlig rødhet i øyet?",
                "answer": "Fordi en linse i øyet i sjeldne tilfeller kan bidra til bakterielle infeksjoner som trenger rask behandling. De aller fleste tilfeller er ufarlige, men det er verdt å kjenne igjen varseltegnene tidlig.",
            },
        ],
    },
}


def _render_faq_block(faq: list[dict], heading: str = "Ofte stilte spørsmål") -> tuple[str, str]:
    """Bygger både synlig FAQ-markup og FAQPage-schema fra samme {question,answer}-liste,
    slik at innhold og strukturert data aldri kan komme ut av synk med hverandre."""
    if not faq:
        return "", ""
    items_html = "\n".join(
        f"""<div class="faq-item">
  <h3>{escape(item["question"])}</h3>
  <p>{escape(item["answer"])}</p>
</div>"""
        for item in faq
    )
    faq_html = f"""<div class="faq-section">
    <h2>{escape(heading)}</h2>
    {items_html}
  </div>"""
    faq_entities = ",\n      ".join(
        f'''{{
        "@type": "Question",
        "name": "{escape(item["question"])}",
        "acceptedAnswer": {{"@type": "Answer", "text": "{escape(item["answer"])}"}}
      }}'''
        for item in faq
    )
    faq_schema = f"""<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
      {faq_entities}
  ]
}}</script>"""
    return faq_html, faq_schema


def _render_faq_accordion_block(faq: list[dict], heading: str = "Ofte stilte spørsmål") -> tuple[str, str]:
    """Samme {question,answer}-inndata og samme FAQPage-schema som
    _render_faq_block(), men visuelt en kollapset <details>-accordion per
    spørsmål (_faq_accordion_item(), samme gjenbrukte komponent som
    serie-/merke-sidene sin FAQ) i stedet for en alltid-synlig flat liste.
    Brukt av render_product_page() sin nye "kunnskapssone"
    (Product Mobile Gold Standard v1, 2026-09-27) -- KUN der, resten av
    sidene som bruker _render_faq_block() er urørt."""
    if not faq:
        return "", ""
    items_html = "\n".join(_faq_accordion_item(item) for item in faq)
    faq_html = f"""<div class="faq-section">
    {items_html}
  </div>"""
    faq_entities = ",\n      ".join(
        f'''{{
        "@type": "Question",
        "name": "{escape(item["question"])}",
        "acceptedAnswer": {{"@type": "Answer", "text": "{escape(item["answer"])}"}}
      }}'''
        for item in faq
    )
    faq_schema = f"""<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
      {faq_entities}
  ]
}}</script>"""
    return faq_html, faq_schema


def _faq_accordion_item(item: dict) -> str:
    return f'''<details class="faq-accordion-item">
    <summary>{escape(item["question"])}<svg class="faq-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></summary>
    <p>{escape(item["answer"])}</p>
  </details>'''


def _render_family_faq_accordion(categorized: list[tuple[str, list[dict]]], heading: str) -> tuple[str, str]:
    """Serie-siden sin FAQ (2026-09-27): egen, GRUPPERT <details>-accordion i
    stedet for _render_faq_block()'s alltid-synlige flate liste -- se
    render_family_page() sin regelmotor-kommentar for hvorfor (variabelt
    antall spørsmål per familie, aldri fylt ut til et fast antall). Samme
    kollapsede <details>-mønster som allerede er Google-verifisert i
    render_winner_widget() sin "Pris ved flere esker"-rad.

    categorized: liste av (kategorinavn, spørsmål-liste) -- tomme kategorier
    utelates helt (en familie uten spec-spørsmål viser ingen tom
    "Spesifikasjoner"-overskrift). FAQPage-schema flates ut på tvers av
    kategoriene (schema.org har ingen kategori-gruppering for FAQPage), men
    bygges fra AKKURAT samme spørsmål/svar som vises -- innhold og
    strukturert data kan da aldri komme ut av synk."""
    all_items = [item for _, items in categorized for item in items]
    if not all_items:
        return "", ""
    sections_html = "".join(
        f'''<div class="faq-category">
    <div class="faq-category-label">{escape(cat_label)}</div>
    {"".join(_faq_accordion_item(item) for item in items)}
  </div>'''
        for cat_label, items in categorized if items
    )
    faq_html = f'''<div class="faq-section">
    <h2>{escape(heading)}</h2>
    {sections_html}
  </div>'''
    faq_entities = ",\n      ".join(
        f'''{{
        "@type": "Question",
        "name": "{escape(item["question"])}",
        "acceptedAnswer": {{"@type": "Answer", "text": "{escape(item["answer"])}"}}
      }}'''
        for item in all_items
    )
    faq_schema = f'''<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
      {faq_entities}
  ]
}}</script>'''
    return faq_html, faq_schema


HOME_FAQ = [
    {
        "question": "Hvordan fungerer Kontaktlinser.no?",
        "answer": "Kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser automatisk fra norske nettbutikker og oppdaterer dem daglig, og viser tilbudene sortert etter lavest pris. Du kan slå på «Pris inkludert frakt» for å se og sortere etter totalpris - produktpris pluss frakt. Du kjøper ikke hos oss; vi lenker deg videre til forhandleren du velger.",
    },
    {
        "question": "Koster det mer å kjøpe via en prissammenligningsside?",
        "answer": "Nei. Prisen du ser er forhandlerens egen pris, og du betaler akkurat det samme som om du gikk direkte til nettbutikken. Vi kan motta provisjon fra enkelte forhandlere når du handler via lenkene våre, men det påvirker verken prisen du betaler eller hvilket tilbud som vises som lavest.",
    },
    {
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Vi oppdaterer prisene fra forhandlerne daglig. Hvert tilbud viser når det sist ble kontrollert, og varer som mangler bekreftet lagerstatus kan ikke vinne merket «laveste pris».",
    },
    {
        "question": "Hvordan unngår jeg skjulte fraktkostnader?",
        "answer": "Vi sorterer alltid tilbudene etter total pris - produktpris pluss frakt - ikke bare produktprisen alene. En nettbutikk med lav produktpris, men høyt fraktgebyr, havner derfor ikke automatisk øverst, slik den kan gjøre om du bare sammenligner produktpriser direkte på forhandlernes egne sider.",
    },
    {
        "question": "Er dagslinser eller månedslinser billigst?",
        "answer": "Det kommer an på linsetype, merke og hvor ofte du bruker linser - det finnes ikke ett svar som gjelder for alle. Se vår guide om månedslinser vs. dagslinser, og bruk kategoriene på Kontaktlinser.no til å sammenligne faktiske priser for akkurat den styrken og pakningsstørrelsen du trenger.",
    },
    {
        "question": "Selger dere også linsevæske og øyedråper?",
        "answer": "Ja. I tillegg til kontaktlinser sammenligner vi priser på linsevæske og øyedråper fra de samme norske nettbutikkene, etter samme prinsipp: sortert etter lavest pris, med mulighet til å se totalpris inkludert frakt.",
    },
    {
        "question": "Hvorfor har noen kontaktlinser to forskjellige navn?",
        "answer": "Flere optikerkjeder selger kjente kontaktlinser under sitt eget varenavn - for eksempel selges Biofinity også under navnet «iWear Oxygen». Det er samme fysiske produkt, bare med en annen emballasje og navn. Vi har en egen oversikt over disse koblingene under Optikerkjedenes egne merker.",
    },
    {
        "question": "Er Kontaktlinser.no en nettbutikk eller et apotek?",
        "answer": "Nei, Kontaktlinser.no er verken en nettbutikk eller et apotek - vi er en uavhengig sammenligningstjeneste og selger ingenting selv. Kontaktlinser er reseptvare, så rådfør deg alltid med optiker eller øyelege om riktig linsetype og styrke før kjøp.",
    },
    {
        "question": "Kan jeg søke opp en spesifikk linse direkte?",
        "answer": "Ja, søkefeltet øverst på forsiden lar deg søke etter linsenavn eller merke og gå rett til produktsiden med gjeldende priser fra alle forhandlere vi følger.",
    },
]


def render_guide_page(slug: str) -> str | None:
    guide = GUIDE_CONTENT.get(slug)
    if guide is None:
        return None

    faq_html, faq_schema = _render_faq_block(guide.get("faq", []))

    updated_iso = guide["updated"]
    updated_display = datetime.strptime(updated_iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    guide_url = f"{BASE_URL}/guide/{slug}/"
    # Samme bilde som vises på siden (og guide-kortet), absolutt URL. Utelates
    # hvis guiden ikke har eget foto -- aldri en generisk logo som artikkelbilde.
    guide_photo_url = f"{BASE_URL}/static/guides/{GUIDE_PHOTOS[slug]}.webp" if slug in GUIDE_PHOTOS else None
    article_image_line = f'\n  "image": "{escape(guide_photo_url)}",' if guide_photo_url else ""
    article_schema = f"""<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{escape(guide["title"])}",
  "description": "{escape(guide["description"])}",{article_image_line}
  "mainEntityOfPage": {{"@type": "WebPage", "@id": "{guide_url}"}},
  "author": {{"@type": "Organization", "name": "Kontaktlinser.no"}},
  "publisher": {{"@type": "Organization", "name": "Kontaktlinser.no"}},
  "datePublished": "{updated_iso}",
  "dateModified": "{updated_iso}"
}}</script>"""
    # BreadcrumbList = nøyaktig den synlige brødsmulen under (Hjem > guidetittel),
    # ingen oppdiktet mellomnivå.
    breadcrumb_schema = f"""<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "{_json_str(guide["title"])}", "item": "{guide_url}"}}
  ]
}}</script>"""

    # Kompakt søkeboks rett etter første avsnitt (alle guider åpner med et
    # <p> som svarer på spørsmålet) -- synlig uten å skyve svaret bort; den
    # fulle boksen med snarveier ligger nederst.
    body_with_cta = guide["body_html"].replace("</p>", "</p>\n    " + render_guide_search_card(slug, compact=True), 1)

    # Samme bilde som guide-kortet (GUIDE_PHOTOS) på selve artikkelen også --
    # Kai sitt eksplisitte ønske 2026-09-27. Første forsøk var et fullbredde
    # toppbilde (190-260px høyt), men Kai påpekte selv (med skjermbilde) at
    # det tok unødvendig stor plass og at et oppskalert, litt mykt bilde blir
    # EKSTRA synlig jo større det vises -- spurte hva som er "normalt".
    # Løsningen (samme dag): et lite, avrundet kvadratisk thumbnail ved siden
    # av overskriften (gjenbruker prinsippet fra .hero-product-image på
    # produktsidene -- bilde+tekst side om side, ikke et eget fullbredde
    # element), IKKE et fullbredde banner. Bonus: en NEDskalering fra
    # 640px-kilden til ~90-130px vises skarpt (motsatt av oppskalering),
    # så dette løser mykhets-problemet i samme slengen.
    photo = GUIDE_PHOTOS.get(slug)
    hero_thumb_html = f"""<div class="guide-hero-thumb">
      <img src="/static/guides/{escape(photo)}.webp" alt="" width="130" height="130" loading="eager" decoding="async">
    </div>""" if photo else ""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(guide["title"])} | Kontaktlinser.no</title>
<meta name="description" content="{escape(guide["description"])}">
<link rel="canonical" href="{BASE_URL}/guide/{slug}/">
{_og_meta(f'{guide["title"]} | Kontaktlinser.no', guide["description"], f'{BASE_URL}/guide/{slug}/')}
{FONT_LINKS}
{faq_schema}
{article_schema}
{breadcrumb_schema}
<style>{SHARED_STYLE}
.guide-byline {{ font-size: 0.82rem; color: var(--muted); margin: -6px 0 0; }}
.guide-hero-row {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
.guide-hero-thumb {{ flex-shrink: 0; width: 68px; height: 68px; border-radius: 14px; overflow: hidden; box-shadow: var(--card-shadow); }}
.guide-hero-thumb img {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
@media (min-width: 640px) {{ .guide-hero-thumb {{ width: 100px; height: 100px; border-radius: 16px; }} }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(guide["title"])}</p>
  <div class="hero">
    <div class="hero-copy guide-hero-row">
      <div>
        <div class="kicker">Guide</div>
        <h1>{escape(guide["title"])}</h1>
        <p class="guide-byline">Kvalitetssikret av Kontaktlinser.no · Sist oppdatert {updated_display} · <a href="/redaksjonelle-prinsipper/" style="color:inherit;">Redaksjonelle prinsipper</a></p>
      </div>
      {hero_thumb_html}
    </div>
  </div>
  <div style="max-width:640px;">
    {body_with_cta}
    {faq_html}
    {render_guide_search_card(slug)}
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


# Hver ikon er en fylt, flat illustrasjon (ikke bare strek) i én av fire
# faste aksentfarger (rullerer for variasjon, se GUIDE_TILE_STYLE for
# fargedefinisjonene) -- bevisst egen-tegnet i SVG, ikke en kopi av noe
# eksternt ikonsett/bilde.
GUIDE_ICONS = {
    "manedslinser-vs-dagslinser": {
        "color": "amber",
        "svg": '<rect x="4" y="6" width="16" height="13" rx="3" fill="currentColor" opacity="0.18"/><circle cx="8" cy="10.5" r="1.7" fill="currentColor"/><circle cx="12" cy="10.5" r="1.7" fill="currentColor"/><circle cx="16" cy="10.5" r="1.7" fill="currentColor"/><circle cx="8" cy="15" r="1.7" fill="currentColor"/><circle cx="12" cy="15" r="1.7" fill="currentColor"/><circle cx="16" cy="15" r="1.7" fill="currentColor"/>',
    },
    "hvordan-velge-kontaktlinser": {
        "color": "blue",
        "svg": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" fill="currentColor"/><circle cx="12" cy="12" r="4" fill="white"/><circle cx="12" cy="12" r="2" fill="currentColor"/>',
    },
    "kontaktlinser-for-barn": {
        "color": "coral",
        "svg": '<circle cx="12" cy="9" r="4.5" fill="currentColor"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" fill="currentColor" opacity="0.5"/>',
    },
    "harde-eller-myke-linser": {
        "color": "mint",
        "svg": '<circle cx="9" cy="12" r="6" fill="currentColor" opacity="0.75"/><circle cx="15" cy="12" r="6" fill="currentColor" opacity="0.45"/>',
    },
    "hvordan-bruke-kontaktlinser": {
        "color": "sky",
        "svg": '<rect x="10" y="2" width="4" height="12" rx="2" fill="currentColor"/><ellipse cx="12" cy="18" rx="7" ry="3.3" fill="currentColor" opacity="0.5"/>',
    },
    "hvorfor-bruke-kontaktlinser": {
        "color": "lavender",
        "svg": '<circle cx="7" cy="13" r="4" fill="none" stroke="currentColor" stroke-width="2.4"/><circle cx="17" cy="13" r="4" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M11 13h2M2.5 12l1-3M21.5 12l-1-3" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    },
    "vedlikehold-av-kontaktlinser": {
        "color": "blue",
        "svg": '<rect x="3" y="7" width="18" height="12" rx="4" fill="currentColor"/><circle cx="8.5" cy="13" r="2.5" fill="white"/><circle cx="15.5" cy="13" r="2.5" fill="white"/>',
    },
    "reising-med-kontaktlinser": {
        "color": "sky",
        "svg": '<path d="M3 12l18-8-8 18-2-8-8-2z" fill="currentColor"/>',
    },
    "kosmetiske-kontaktlinser": {
        "color": "coral",
        "svg": '<circle cx="10" cy="13" r="5.5" fill="currentColor"/><path d="M18 4l1.2 2.4 2.3 1.2-2.3 1.2L18 11l-1.2-2.2-2.3-1.2 2.3-1.2z" fill="currentColor" opacity="0.6"/>',
    },
    "kontaktlinsens-materiale": {
        "color": "mint",
        "svg": '<path d="M12 3s6.5 7.5 6.5 11.5a6.5 6.5 0 0 1-13 0C5.5 10.5 12 3 12 3z" fill="currentColor"/>',
    },
    "korrigerende-kontaktlinser": {
        "color": "lavender",
        "svg": '<circle cx="12" cy="12" r="8.5" fill="currentColor" opacity="0.32"/><circle cx="12" cy="12" r="4.2" fill="currentColor"/>',
    },
    "produksjon-av-kontaktlinser": {
        "color": "amber",
        "svg": '<circle cx="12" cy="12" r="4.2" fill="currentColor"/><circle cx="12" cy="4" r="1.6" fill="currentColor"/><circle cx="12" cy="20" r="1.6" fill="currentColor"/><circle cx="4" cy="12" r="1.6" fill="currentColor"/><circle cx="20" cy="12" r="1.6" fill="currentColor"/><circle cx="6.3" cy="6.3" r="1.4" fill="currentColor"/><circle cx="17.7" cy="17.7" r="1.4" fill="currentColor"/><circle cx="6.3" cy="17.7" r="1.4" fill="currentColor"/><circle cx="17.7" cy="6.3" r="1.4" fill="currentColor"/>',
    },
    "kontaktlinsens-historie": {
        "color": "mint",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor"/><path d="M12 7v5l3.2 2" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    },
    "terapeutiske-kontaktlinser": {
        "color": "coral",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor"/><path d="M12 7.5v9M7.5 12h9" stroke="white" stroke-width="2.2" stroke-linecap="round"/>',
    },
    "kontaktlinser-med-astigmatisme": {
        "color": "sky",
        "svg": '<ellipse cx="12" cy="12" rx="9" ry="5.5" fill="currentColor" opacity="0.3" transform="rotate(-20 12 12)"/><ellipse cx="12" cy="12" rx="4.5" ry="2.8" fill="currentColor" transform="rotate(-20 12 12)"/>',
    },
    "multifokale-kontaktlinser": {
        "color": "amber",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.22"/><circle cx="12" cy="12" r="6" fill="currentColor" opacity="0.45"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
    },
    "kan-man-sove-med-kontaktlinser": {
        "color": "lavender",
        "svg": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" fill="currentColor"/>',
    },
    "kan-man-dusje-med-kontaktlinser": {
        "color": "sky",
        "svg": '<path d="M12 3s6.5 7.5 6.5 11.5a6.5 6.5 0 0 1-13 0C5.5 10.5 12 3 12 3z" fill="currentColor" opacity="0.85"/><path d="M4 20c1.5-1 2.5-1 4 0s2.5 1 4 0 2.5-1 4 0 2.5 1 4 0" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/>',
    },
    "kontaktlinser-og-torre-oyne": {
        "color": "coral",
        "svg": '<path d="M2 13s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6z" fill="currentColor" opacity="0.35"/><path d="M12 9s2.6 3 2.6 4.6a2.6 2.6 0 1 1-5.2 0C9.4 12 12 9 12 9z" fill="currentColor"/>',
    },
    "forsta-kontaktlinseresepten": {
        "color": "mint",
        "svg": '<rect x="5" y="3" width="14" height="18" rx="2" fill="currentColor" opacity="0.18"/><path d="M8 8h8M8 12h8M8 16h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    },
    "bc-forklart": {
        "color": "mint",
        "svg": '<rect x="3" y="10" width="18" height="4" rx="1" fill="currentColor" opacity="0.25"/><path d="M6 10v4M10 10v4M14 10v4M18 10v4" stroke="currentColor" stroke-width="1.4"/>',
    },
    "dia-forklart": {
        "color": "sky",
        "svg": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M4 12h16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    },
    "pwr-sph-forklart": {
        "color": "amber",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.18"/><path d="M8 12h8M12 8v8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    },
    "cyl-forklart": {
        "color": "coral",
        "svg": '<ellipse cx="12" cy="12" rx="9" ry="5" fill="currentColor" opacity="0.3"/><ellipse cx="12" cy="12" rx="9" ry="5" fill="none" stroke="currentColor" stroke-width="1.4"/>',
    },
    "axis-forklart": {
        "color": "lavender",
        "svg": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.4"/><path d="M12 3v18M4.5 6.5l15 11" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    },
    "add-forklart": {
        "color": "blue",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.18"/><path d="M12 8v8M8 12h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    },
    "hvor-lenge-kan-man-bruke-kontaktlinser": {
        "color": "blue",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor"/><path d="M12 7.5v5l3 1.8" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    },
    "samme-styrke-briller-og-linser": {
        "color": "amber",
        "svg": '<circle cx="7" cy="13" r="3.6" fill="none" stroke="currentColor" stroke-width="2.2"/><circle cx="17" cy="13" r="3.6" stroke="none" fill="currentColor" opacity="0.35"/><path d="M10.6 13h2.8M2.8 12l1-3M21.2 12l-1-3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    },
    "hva-koster-kontaktlinser": {
        "color": "mint",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.18"/><path d="M12 6.5v11M9 9.2c0-1 1-1.7 3-1.7s3 .8 3 1.9c0 2.6-6 1.2-6 3.8 0 1.1 1.3 1.9 3 1.9s3-.7 3-1.7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/>',
    },
    "pakningsstorrelse-30-vs-90": {
        "color": "amber",
        "svg": '<rect x="3" y="8" width="7" height="10" rx="1.5" fill="currentColor" opacity="0.3"/><rect x="12" y="5" width="9" height="13" rx="1.5" fill="currentColor" opacity="0.6"/>',
    },
    "pris-per-linse-slik-sammenligner-du": {
        "color": "sky",
        "svg": '<circle cx="9" cy="9" r="5" fill="currentColor" opacity="0.3"/><circle cx="15" cy="15" r="5" fill="currentColor" opacity="0.6"/><path d="M12 12h.01" stroke="currentColor" stroke-width="0"/>',
    },
    "hvorfor-varierer-prisene-mellom-butikkene": {
        "color": "coral",
        "svg": '<path d="M4 18l4-6 4 3 4-8 4 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    },
    "hvordan-kontaktlinser-no-beregner-totalpris": {
        "color": "lavender",
        "svg": '<rect x="4" y="5" width="16" height="14" rx="2" fill="currentColor" opacity="0.16"/><path d="M8 10h8M8 13h8M8 16h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    },
    "kontaktlinseabonnement-vs-kjope-selv": {
        "color": "blue",
        "svg": '<path d="M17 5a7 7 0 1 0 3 5.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none"/><path d="M17 2v4h-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    },
    "hvordan-kjope-kontaktlinser-pa-nett": {
        "color": "mint",
        "svg": '<rect x="4" y="3" width="16" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 8h8M8 12h8M8 16h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
    },
    "kan-man-kjope-kontaktlinser-uten-resept": {
        "color": "coral",
        "svg": '<rect x="5" y="3" width="14" height="18" rx="2" fill="currentColor" opacity="0.16"/><path d="M8 8h8M8 12h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="16" cy="16" r="4" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M13.5 18.5l5-5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    },
    "kan-jeg-bytte-kontaktlinsemerke-selv": {
        "color": "amber",
        "svg": '<path d="M7 7h10l-3-3M17 17H7l3 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    },
    "linse-sitter-fast-i-oyet": {
        "color": "coral",
        "svg": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" fill="currentColor" opacity="0.85"/><circle cx="12" cy="12" r="3.2" fill="white"/><circle cx="18" cy="6" r="4.2" fill="currentColor"/><rect x="17.3" y="3.6" width="1.4" height="3.2" rx="0.7" fill="white"/><circle cx="18" cy="8.2" r="0.8" fill="white"/>',
    },
    "uklart-syn-med-kontaktlinser": {
        "color": "sky",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.15"/><circle cx="12" cy="12" r="6" fill="currentColor" opacity="0.35"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
    },
    "rode-oyne-og-svie-med-kontaktlinser": {
        "color": "amber",
        "svg": '<circle cx="12" cy="12" r="5" fill="currentColor"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    },
}

# Ekte foto for ALLE 40 guider (2026-09-27, fra Kai sitt bildeutvalg --
# beskåret fra to sammensatte referansebilder han sendte, IKKE generert av
# oss -- filene kom aldri separat, så rutenettene ble beskåret programmatisk
# ved å finne de hvite gutter-linjene mellom rutene). Filnavnet er alltid
# slugen selv (static/guides/{slug}.webp), så denne "dict-en" er reelt sett
# bare en eksistens-sjekk -- beholdt som dict (ikke set) i tilfelle et bilde
# senere trenger et annet filnavn enn slugen. Første 20 er tydelige
# motiv-treff (aktivitet/situasjon som faktisk vises i guiden); de siste 20
# (spec-forklaringer, pris/abonnement, resept, historie/produksjon) er mer
# generiske øye-/linse-bilder valgt for at Kai skal få bilde på ALLE
# guide-kort, ikke fordi motivet illustrerer noe spesifikt i akkurat den
# guiden -- ærlig sagt til Kai, se CLAUDE.md. Kildebildene er kun
# 1536x1024px sammensatt over 60 ruter, så hver rute er beskåret til ca.
# 145x150px og oppskalert -- godkjent for et lite kort-/toppbilde, men
# merkbart mykere enn en ekte høyoppløst original. Bytt ut med skarpere
# originaler hvis/når Kai får tak i dem.
GUIDE_PHOTOS = {slug: slug for slug in [
    "hvordan-bruke-kontaktlinser", "hvordan-velge-kontaktlinser", "kontaktlinser-for-barn",
    "harde-eller-myke-linser", "hvorfor-bruke-kontaktlinser", "vedlikehold-av-kontaktlinser",
    "reising-med-kontaktlinser", "kosmetiske-kontaktlinser", "kontaktlinsens-materiale",
    "kan-man-sove-med-kontaktlinser", "kan-man-dusje-med-kontaktlinser", "kontaktlinser-og-torre-oyne",
    "hvor-lenge-kan-man-bruke-kontaktlinser", "pakningsstorrelse-30-vs-90", "manedslinser-vs-dagslinser",
    "multifokale-kontaktlinser", "linse-sitter-fast-i-oyet", "uklart-syn-med-kontaktlinser",
    "rode-oyne-og-svie-med-kontaktlinser", "hvordan-kjope-kontaktlinser-pa-nett",
    "kontaktlinser-med-astigmatisme", "korrigerende-kontaktlinser", "kontaktlinsens-historie",
    "produksjon-av-kontaktlinser", "terapeutiske-kontaktlinser", "forsta-kontaktlinseresepten",
    "bc-forklart", "dia-forklart", "pwr-sph-forklart", "cyl-forklart", "axis-forklart", "add-forklart",
    "samme-styrke-briller-og-linser", "hva-koster-kontaktlinser", "pris-per-linse-slik-sammenligner-du",
    "hvorfor-varierer-prisene-mellom-butikkene", "hvordan-kontaktlinser-no-beregner-totalpris",
    "kontaktlinseabonnement-vs-kjope-selv", "kan-man-kjope-kontaktlinser-uten-resept",
    "kan-jeg-bytte-kontaktlinsemerke-selv",
]}

# Delt mellom /guider/-oversikten og forsidens forhåndsvisnings-seksjon,
# slik at guide-kortene ser identiske ut begge steder (se render_guide_tile).
# .guide-photo-card* er BEVISST en kopi av samme klassenavn/CSS som
# render_family_page() sin egen "Relevante guider"-seksjon bruker (ikke delt
# via denne konstanten der, for å ikke røre en allerede utgitt serie-side-
# komponent) -- samme visuelle kort begge steder, to kildesteder i koden.
GUIDE_TILE_STYLE = """
.guide-grid { display: grid; grid-template-columns: 1fr; gap: 14px; margin-top: 24px; }
.guide-tile { display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 14px; padding: 22px 20px; box-shadow: var(--card-shadow); text-align: center; }
.guide-tile:hover { border-color: var(--blue); }
.guide-tile-icon { width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 14px; }
.guide-tile-icon svg { width: 28px; height: 28px; }
.guide-tile-title { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; margin-bottom: 6px; }
.guide-tile-desc { font-size: 0.86rem; color: var(--muted); line-height: 1.5; }
.guide-tile-link { font-size: 0.86rem; font-weight: 600; color: var(--blue); margin-top: 12px; }
@media (min-width: 640px) { .guide-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 900px) { .guide-grid { grid-template-columns: repeat(4, 1fr); } }
.guide-photo-card { display: block; background: white; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; text-decoration: none; color: var(--ink); box-shadow: var(--card-shadow); transition: transform 0.15s, box-shadow 0.15s; }
.guide-photo-card:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(37, 99, 235, 0.14); }
.guide-photo-card-image { aspect-ratio: 16 / 9; background: var(--mist); overflow: hidden; }
.guide-photo-card-image img { width: 100%; height: 100%; object-fit: cover; }
.guide-photo-card-body { padding: 14px 16px 16px; }
.guide-photo-card-title { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; line-height: 1.35; }
.guide-photo-card-desc { font-size: 0.86rem; color: var(--muted); line-height: 1.5; margin-top: 6px; }
.guide-photo-card-link { font-size: 0.86rem; font-weight: 600; color: var(--blue); margin-top: 12px; }
"""


def render_guide_tile(slug: str, g: dict) -> str:
    photo = GUIDE_PHOTOS.get(slug)
    if photo:
        return f"""<a class="guide-photo-card" href="/guide/{escape(slug)}/">
  <div class="guide-photo-card-image">
    <img src="/static/guides/{escape(photo)}.webp" alt="" width="640" height="662" loading="lazy" decoding="async">
  </div>
  <div class="guide-photo-card-body">
    <div class="guide-photo-card-title">{escape(g["title"])}</div>
    <div class="guide-photo-card-desc">{escape(g["description"])}</div>
    <div class="guide-photo-card-link">Les guiden →</div>
  </div>
</a>"""
    icon = GUIDE_ICONS.get(slug, {"color": "blue", "svg": ""})
    color, tint = f"var(--{icon['color']})", f"var(--{icon['color']}-tint)"
    return f"""<a class="guide-tile" href="/guide/{escape(slug)}/">
  <div class="guide-tile-icon" style="background:{tint};color:{color};"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true">{icon["svg"]}</svg></div>
  <div class="guide-tile-title">{escape(g["title"])}</div>
  <div class="guide-tile-desc">{escape(g["description"])}</div>
  <div class="guide-tile-link">Les guiden →</div>
</a>"""


def render_guides_index_page() -> str:
    cards_html = "\n".join(render_guide_tile(slug, g) for slug, g in GUIDE_CONTENT.items())

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Guider – Kontaktlinser.no</title>
<meta name="description" content="Guider om kontaktlinser: hvordan velge riktig type, bruk og vedlikehold, kontaktlinser for barn, og mer.">
<link rel="canonical" href="{BASE_URL}/guider/">
{_og_meta('Guider – Kontaktlinser.no', 'Guider om kontaktlinser: hvordan velge riktig type, bruk og vedlikehold, kontaktlinser for barn, og mer.', BASE_URL + '/guider/')}
{FONT_LINKS}
<style>{SHARED_STYLE}
{GUIDE_TILE_STYLE}
/* Toppbanner (2026-09-27, fra Kai sitt bildeutvalg -- kun selve fotostripen,
   ingen påskrevet tekst/mockup-UI). Teksten ligger OPPÅ selve bildet (Kai:
   "legg teksten oppå selve bilde her så blir det flott") -- en lys gradient
   fra venstre (der kildebildet allerede er lyst/uskarpt i bakgrunnen, se
   bildet selv) sikrer lesbar mørk tekst uten å måtte gjette fargen på et
   ukjent fremtidig banner-bilde. IKKE en side-panel som serie-hero
   (kildebildet er for panoramisk/tynt til det -- ca. 4,9:1), og IKKE skjult
   på mobil slik serie-hero-media er -- Kai ville ha bildet synlig overalt. */
.guide-hero {{ position: relative; border-radius: 20px; overflow: hidden; margin-bottom: 20px; box-shadow: var(--card-shadow); }}
.guide-hero img {{ display: block; width: 100%; height: 230px; object-fit: cover; }}
.guide-hero-overlay {{ position: absolute; inset: 0; background: linear-gradient(100deg, #fff 0%, rgba(255,255,255,0.93) 42%, rgba(255,255,255,0.35) 68%, rgba(255,255,255,0) 88%); }}
.guide-hero-content {{ position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: center; padding: 20px 22px; max-width: 82%; }}
.guide-hero-content .kicker {{ margin: 0; }}
.guide-hero-content h1 {{ margin: 6px 0 8px; font-size: clamp(1.35rem, 5.5vw, 2rem); line-height: 1.15; }}
.guide-hero-content p {{ margin: 0; color: var(--muted); font-size: 0.9rem; line-height: 1.5; max-width: 420px; }}
@media (min-width: 640px) {{
  .guide-hero img {{ height: 280px; }}
  .guide-hero-content {{ max-width: 58%; padding: 28px 36px; }}
}}
@media (min-width: 1024px) {{
  .guide-hero img {{ height: 340px; }}
  .guide-hero-content {{ max-width: 46%; padding: 32px 44px; }}
}}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › Guider</p>
  <div class="guide-hero">
    <picture>
      <source type="image/webp" srcset="/static/hero/guider-560.webp 560w, /static/hero/guider-840.webp 840w, /static/hero/guider-1120.webp 1120w, /static/hero/guider-1536.webp 1536w" sizes="(min-width: 1200px) 1120px, 92vw">
      <img src="/static/hero/guider-840.webp" alt="" width="1536" height="316" loading="eager" decoding="async">
    </picture>
    <div class="guide-hero-overlay"></div>
    <div class="guide-hero-content">
      <div class="kicker">Guider</div>
      <h1>Alt om kontaktlinser – enkelt forklart</h1>
      <p>Praktiske råd som hjelper deg å ta gode valg, bruke linsene riktig og ta vare på øynene dine.</p>
    </div>
  </div>
  <div class="guide-grid">
  {cards_html}
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_about_page() -> str:
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Om oss – Kontaktlinser.no</title>
<meta name="description" content="Om Kontaktlinser.no: hva vi gjør, hvordan vi sammenligner priser, og hvordan vi tjener penger.">
<link rel="canonical" href="{BASE_URL}/om-oss/">
{_og_meta('Om oss – Kontaktlinser.no', 'Om Kontaktlinser.no: hva vi gjør, hvordan vi sammenligner priser, og hvordan vi tjener penger.', BASE_URL + '/om-oss/')}
{FONT_LINKS}
<style>{SHARED_STYLE}
.about-body h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 28px 0 10px; }}
.about-body p {{ font-size: 0.92rem; line-height: 1.65; color: var(--ink); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › Om oss</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Om oss</div>
      <h1>Om Kontaktlinser.no</h1>
      <p>En uavhengig prissammenligningstjeneste for kontaktlinser i Norge.</p>
    </div>
  </div>

  <div class="about-body" style="max-width:640px;">
    <p>Kontaktlinser koster ofte svært ulikt fra butikk til butikk for nøyaktig
    samme vare - samme merke, samme styrke, samme pakningsstørrelse. Vi samler
    prisene fra norske nettbutikker på ett sted, slik at du slipper å sjekke
    ti forskjellige nettsider for å finne billigste tilgjengelige tilbud.</p>

    <h2>Hvordan det fungerer</h2>
    <p>Prisene hentes automatisk fra forhandlerne og oppdateres daglig. Vi
    sorterer etter lavest pris, og du kan slå på «Pris inkludert frakt» for å se og
    sortere etter totalpris - et tilbud som er
    utsolgt kan aldri vinne "laveste pris"-merket, uansett hvor lavt tallet
    er. Hvert tilbud viser når det sist ble kontrollert.</p>

    <h2>Hvordan vi tjener penger</h2>
    <p>Vi kan motta provisjon fra enkelte forhandlere når du handler via
    lenkene våre. Det påvirker aldri prisen du betaler, og det påvirker aldri
    rangeringen av tilbud - den følger alltid faktisk pris (produktpris, eller
    totalpris når du slår på frakt), ikke hvem vi har en avtale med.</p>

    <h2>Hva vi ikke er</h2>
    <p>Vi selger ikke kontaktlinser selv, og driver ikke butikk. Vi gir heller
    ikke medisinske råd: kontaktlinser er reseptvare, så rådfør deg alltid med
    optiker ved valg av linsetype og styrke.</p>

    <h2>Hvem driver Kontaktlinser.no?</h2>
    <p>Kontaktlinser.no drives som et selvstendig, uavhengig prosjekt - ikke av
    en optikerkjede eller en av forhandlerne vi sammenligner priser fra. Har du
    spørsmål om hvem som står bak, ta kontakt på e-posten under.</p>

    <h2>Les mer</h2>
    <p>Vi prøver å være mer åpne om hvordan tjenesten faktisk fungerer enn det
    som er vanlig for en prissammenligningsside:</p>
    <ul style="padding-left:20px;font-size:0.92rem;line-height:1.9;color:var(--ink);">
      <li><a href="/slik-sammenligner-vi-priser/">Slik sammenligner vi priser</a></li>
      <li><a href="/slik-matcher-vi-produkter/">Slik matcher vi produkter</a></li>
      <li><a href="/redaksjonelle-prinsipper/">Redaksjonelle prinsipper</a></li>
      <li><a href="/affiliate-og-finansiering/">Affiliate og finansiering</a></li>
      <li><a href="/meld-feil/">Meld feil</a></li>
    </ul>

    <h2>Kontakt</h2>
    <p>Spørsmål, feilmelding eller tips om et tilbud som ikke stemmer? Send oss
    en e-post på {_contact_email_link()}.</p>
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def _trust_page(slug: str, title: str, kicker: str, lead: str, body_html: str) -> str:
    """Delt mal for de 5 nye tillit-/metodikksidene -- samme skjelett som
    render_privacy_page()/render_terms_page() (TOPBAR_HTML > brødsmule > hero
    > innholdsdiv > footer), men uten now-parameter siden ingen av disse
    trenger en "sist oppdatert"-dato (statisk prinsipp-tekst, ikke
    tidsstemplet innhold som guidene)."""
    full_title = f'{title} – Kontaktlinser.no'
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(full_title)}</title>
<meta name="description" content="{escape(lead)}">
<link rel="canonical" href="{BASE_URL}/{slug}/">
{_og_meta(full_title, lead, f'{BASE_URL}/{slug}/')}
{FONT_LINKS}
<style>{SHARED_STYLE}
.about-body h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 28px 0 10px; }}
.about-body p {{ font-size: 0.92rem; line-height: 1.65; color: var(--ink); }}
.about-body li {{ font-size: 0.92rem; line-height: 1.7; color: var(--ink); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › <a href="/om-oss/">Om oss</a> › {escape(title)}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">{escape(kicker)}</div>
      <h1>{escape(title)}</h1>
      <p>{escape(lead)}</p>
    </div>
  </div>

  <div class="about-body" style="max-width:640px;">
    {body_html}
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_pricing_methodology_page() -> str:
    body = """
<p>Dette er den fulle versjonen av metodikk-boksen du ser på hver produktside -- samme
fem punkter, litt mer utdypet.</p>

<h2>Produktpris</h2>
<p>Prisen butikken selv oppgir for produktet, uten frakt. Dette er tallet som vises
øverst på hvert tilbudskort.</p>

<h2>Frakt</h2>
<p>Fraktkostnaden beregnes ut fra antallet esker du har valgt, og hver butikks egen
fri-frakt-grense. Kjøper du f.eks. 2 esker til 300 kr stykket hos en butikk med gratis
frakt over 500 kr, blir totalprisen 600 kr uten frakt lagt til -- kjøper du bare 1 eske
(300 kr, under grensen), kommer fraktkostnaden med i totalen. Grensene varierer mye
mellom butikkene (noen har alltid gratis frakt, én har aldri gratis frakt uansett
beløp), så hvem som er billigst kan endre seg avhengig av hvor mange esker du trenger.</p>

<h2>Totalpris</h2>
<p>Produktpris multiplisert med antall, pluss eventuell frakt for akkurat det antallet.
Dette er tallet du ser, og som vi sorterer etter, når du slår på «Pris inkludert frakt».</p>

<h2>Sortering og "laveste pris"</h2>
<p>Tilbudene sorteres etter lavest produktpris (uten frakt). Slår du på «Pris inkludert
frakt», sorteres de etter lavest totalpris i stedet. Et tilbud som er utsolgt, eller
uten bekreftet lagerstatus, kan aldri vinne "laveste pris"-merket, uansett hvor
lavt tallet er -- det vises fortsatt i listen, bare uten merket. Ved eksakt lik
pris mellom to butikker, se
<a href="/affiliate-og-finansiering/">Affiliate og finansiering</a> for hvordan vi da
avgjør rekkefølgen.</p>

<h2>Kilder og oppdateringsfrekvens</h2>
<p>Prisene oppdateres daglig, enten direkte fra en forhandlers egen
produktfeed (der vi har en slik avtale) eller ved å lese av prisen på forhandlerens
egen produktside. Hvert tilbud viser når det sist ble kontrollert, og et produkt uten
en pålitelig pris publiseres uten pris -- vi gjetter aldri en pris.</p>
"""
    return _trust_page(
        "slik-sammenligner-vi-priser",
        "Slik sammenligner vi priser",
        "Metodikk",
        "Metodikken bak «laveste pris»-merket og sorteringen du ser på hver produktside.",
        body,
    )


def render_product_matching_page() -> str:
    body = """
<p>Et produkt på Kontaktlinser.no har alltid én fast, intern identitet -- uavhengig av
hvilket navn en butikk eller optikerkjede selger det under, og uavhengig av selve
nettadressen til produktsiden.</p>

<h2>Hvordan et tilbud kobles til riktig produkt</h2>
<p>Når vi henter priser fra en forhandlers produktfeed, matches hver rad mot en
manuelt vedlikeholdt tabell med kjente produktnumre/SKU-er. En rad med et ukjent
produktnummer blir <strong>aldri</strong> gjettet inn på et produkt den kan ligne på --
den hoppes over og logges, i stedet for å risikere å vise feil pris på feil vare.</p>

<h2>Optikerkjedenes egne merkenavn (private label)</h2>
<p>Flere optikerkjeder selger kjente kontaktlinser under sitt eget varenavn --
f.eks. er en linse som "EyeQ 24" hos Synsam faktisk Biofinity fra CooperVision, bare i
egen innpakning. Vi kobler kun disse to sammen når det er bekreftet direkte mot en
uavhengig kilde som eksplisitt oppgir hvilket produsentnavn den aktuelle
private label-linsen tilsvarer -- vi gjetter aldri en kobling basert på at navnene
"høres like ut".</p>

<p>Vi bruker <strong>ikke</strong> GTIN/EAN-koder til denne matchingen i dag -- det er
ikke et datafelt vi har tilgang til fra forhandlernes feeds. Koblingen bygger i stedet
på produsentnavn og produktspesifikasjoner fra kilden nevnt over.</p>

<div style="background:#FFF4E5;border:1px solid #F0C674;border-radius:12px;padding:14px 16px;margin:16px 0;font-size:0.85rem;line-height:1.6;color:var(--ink);">
Kontaktlinser.no har ingen avtale med optikerkjedene, og kan ikke garantere at en
private label-kobling stemmer i alle tilfeller -- pakningsstørrelse eller tilgjengelige
styrker kan i sjeldne tilfeller avvike. Bekreft alltid med din optiker eller
synsresept før du bytter til et produkt du har funnet via en slik kobling.
</div>

<p>Se <a href="/private-label/">full oversikt over optikerkjedenes egne merker</a> vi
har koblet så langt.</p>
"""
    return _trust_page(
        "slik-matcher-vi-produkter",
        "Slik matcher vi produkter",
        "Metodikk",
        "Hvordan vi identifiserer produkter på tvers av forhandlere, og hvordan private label-koblinger verifiseres.",
        body,
    )


def render_editorial_principles_page() -> str:
    body = """
<p>Guidene på Kontaktlinser.no er egenskrevne, ikke kopiert fra andre nettsteder.</p>

<h2>Kilder</h2>
<p>Der en guide oppgir et konkret faktapåstand som ikke er allment kjent, forsøker vi å
vise til en anerkjent kilde -- typisk Norsk Helseinformatikk (NHI) eller Helsenorge,
med direkte sitat og lenke til originalkilden. Generelle, godt etablerte fakta (f.eks.
hvordan et linsemateriale fungerer) siteres ikke nødvendigvis punkt for punkt, men er
kryssjekket mot offentlig produsent-/faginformasjon før publisering.</p>

<h2>Ingen individuelle medisinske råd</h2>
<p>Guidene gir generell informasjon, ikke råd tilpasset din egen situasjon.
Alt som krever en individuell vurdering -- valg av linsetype, styrke, eller om et
symptom er noe å bekymre seg for -- henvises alltid videre til optiker eller
øyelege, aldri besvart direkte i teksten.</p>

<h2>Oppdatering</h2>
<p>Hver guide viser datoen den sist ble oppdatert. Faktafeil vi blir gjort
oppmerksom på rettes fortløpende.</p>

<h2>Fant du en feil?</h2>
<p>Se noe som virker faktisk feil i en guide? Vi vil gjerne rette det --
<a href="/meld-feil/">meld fra her</a>.</p>
"""
    return _trust_page(
        "redaksjonelle-prinsipper",
        "Redaksjonelle prinsipper",
        "Metodikk",
        "Hvordan guidene på Kontaktlinser.no lages, hvilke kilder vi bruker, og hvordan feil rettes.",
        body,
    )


def render_affiliate_disclosure_page() -> str:
    body = """
<p>Kontaktlinser.no er gratis å bruke. Slik finansieres tjenesten:</p>

<h2>Hvordan vi tjener penger</h2>
<p>Vi kan motta provisjon fra enkelte forhandlere når du handler via en lenke fra oss,
gjennom vanlige affiliate-nettverk. Dette koster deg ingenting ekstra -- prisen du
betaler hos forhandleren er nøyaktig den samme som om du hadde funnet frem dit selv.</p>

<h2>Påvirker det rangeringen?</h2>
<p><strong>Nei.</strong> Tilbud sorteres alltid etter faktisk pris (produktpris, eller totalpris når du slår på «Pris inkludert frakt»), uavhengig av om
vi har en avtale med forhandleren eller ikke -- se
<a href="/slik-sammenligner-vi-priser/">Slik sammenligner vi priser</a>. Det ene
unntaket: ved <em>eksakt</em> lik pris mellom to eller flere butikker (ingen reell
prisforskjell for deg som kunde) kan vi prioritere en forhandler vi har en
affiliate-avtale med i rekkefølgen. Er det en reell prisforskjell, uansett hvor liten,
vinner alltid laveste pris -- avtale eller ei.</p>

<h2>rel="sponsored" og rel="nofollow"</h2>
<p>Lenker til forhandlere vi har en affiliate-avtale med er merket
<code>rel="sponsored"</code>, i tråd med Googles egne retningslinjer for betalte/
provisjonsbaserte lenker. Lenker til forhandlere uten avtale er merket
<code>rel="nofollow"</code>. Vi blander aldri disse to.</p>

<p>For informasjon om cookies og sporing knyttet til affiliate-nettverkene, se
<a href="/personvern/">Personvern og cookies</a>.</p>
"""
    return _trust_page(
        "affiliate-og-finansiering",
        "Affiliate og finansiering",
        "Metodikk",
        "Hvordan Kontaktlinser.no tjener penger, og hvorfor det aldri påvirker hvilket tilbud som vises som billigst.",
        body,
    )


def render_report_error_page() -> str:
    body = f"""
<p>Har du oppdaget en feil pris, en feil produktkobling, eller noe annet som ikke
stemmer? Vi vil gjerne rette det -- jo mer presis melding, jo raskere kan vi finne
feilen.</p>

<h2>Velg det som passer best</h2>
<ul style="padding-left:20px;">
  <li>{_mailto_link("Feil pris", "Meld feil pris →")}</li>
  <li>{_mailto_link("Feil produktmatching", "Meld feil produktmatching (f.eks. private label-kobling) →")}</li>
  <li>{_mailto_link("Annet", "Meld noe annet →")}</li>
</ul>

<p>Alle tre åpner e-postprogrammet ditt med et ferdig utfylt emnefelt til
{_contact_email_link()} -- inkluder gjerne lenken til siden det gjelder, og hvilken
butikk/pris det er snakk om.</p>
"""
    return _trust_page(
        "meld-feil",
        "Meld feil",
        "Meld feil",
        "Funnet en feil pris, feil produktkobling eller noe annet som ikke stemmer? Meld fra her.",
        body,
    )


def render_404_page() -> str:
    """GitHub Pages serverer denne automatisk med faktisk HTTP 404-status for
    enhver manglende sti - se generate_pages.py (skrives til build/404.html,
    rot-nivå, ikke en undermappe). noindex i tillegg, som en ekstra sikring
    hvis siden noensinne skulle bli lenket til eller crawlet direkte.

    Kjører også en klientsidevis oppslag mot LEGACY_REDIRECTS helt øverst i
    <head> (før noe annet), for de 237 gamle .aspx-URL-ene fra forrige
    versjon av siden - .aspx kan ikke serveres som en fungerende HTML-
    omdirigering på GitHub Pages (se kommentar ved LEGACY_REDIRECTS), så
    dette er en bevisst nest-best løsning: browser mottar 404, men ekte
    besøkende sendes likevel videre i stedet for å treffe en blindvei. IKKE
    et substitutt for en ekte 301 SEO-messig - se CLAUDE.md."""
    category_links = "\n    ".join(
        f'<a href="/kontaktlinser/{slug}/" class="not-found-link">{escape(label)}</a>' for slug, label in FOOTER_CATEGORIES
    )
    legacy_redirect_script = f"""<script>
(function () {{
  var legacyRedirects = {json.dumps(LEGACY_REDIRECTS)};
  var target = legacyRedirects[location.pathname.toLowerCase()];
  if (target) location.replace(target);
}})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{legacy_redirect_script}
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>Siden ble ikke funnet – Kontaktlinser.no</title>
{FONT_LINKS}
<style>{SHARED_STYLE}
.not-found-hero {{ padding: 40px 0 16px; text-align: center; }}
.not-found-hero .kicker {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }}
.not-found-hero h1 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.7rem; margin: 8px 0 10px; }}
.not-found-hero p {{ color: var(--muted); font-size: 0.94rem; max-width: 440px; margin: 0 auto; }}
.not-found-links {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 440px; margin: 28px auto 0; }}
.not-found-link {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 14px; text-align: center; font-weight: 600; font-size: 0.9rem; box-shadow: var(--card-shadow); }}
.not-found-link:hover {{ border-color: var(--blue); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <div class="not-found-hero">
    <div class="kicker">404</div>
    <h1>Fant ikke siden</h1>
    <p>Lenken kan være utdatert, eller siden kan ha flyttet. Prøv en av
    kategoriene under, eller gå til forsiden for å søke.</p>
  </div>
  <div class="not-found-links">
    <a href="/" class="not-found-link">Forside</a>
    <a href="/guider/" class="not-found-link">Guider</a>
    {category_links}
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


# Innhold og struktur speiler Datatilsynets egen cookie-erklæring (formål,
# rettslig grunnlag ekomloven § 3-15, oversiktstabell) - ikke bare et
# Tradedoubler-spesifikt krav. Ingen samtykkebanner ennå (bevisst utsatt,
# avklart med bruker 2026-08-11): GTM settes derfor fortsatt før samtykke i
# dag - siden må ikke late som noe annet i teksten under.
# Vises som "Sist oppdatert" på de juridiske sidene. Var tidligere alltid
# dagens dato (hvert bygg), som er misvisende for en tekst som ikke er endret --
# 2026-09-26 satt til siste faktiske endring (fra git-historikken). ENDRE
# MANUELT når teksten i selve siden endres.
PRIVACY_UPDATED = "2026-08-30"
TERMS_UPDATED = "2026-09-05"


def _legal_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")


def render_privacy_page() -> str:
    updated = _legal_date(PRIVACY_UPDATED)

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Personvern og cookies – Kontaktlinser.no</title>
<meta name="description" content="Hvilke informasjonskapsler (cookies) Kontaktlinser.no bruker, hvorfor, og hvordan du kan kontrollere dem.">
<link rel="canonical" href="{BASE_URL}/personvern/">
{_og_meta('Personvern og cookies – Kontaktlinser.no', 'Hvilke informasjonskapsler (cookies) Kontaktlinser.no bruker, hvorfor, og hvordan du kan kontrollere dem.', BASE_URL + '/personvern/')}
{FONT_LINKS}
<style>{SHARED_STYLE}
.cookie-table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; font-size: 0.86rem; margin: 16px 0; }}
.cookie-table th, .cookie-table td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }}
.cookie-table th {{ background: var(--mist); font-family: 'Space Grotesk', sans-serif; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }}
.cookie-table tr:last-child td {{ border-bottom: none; }}
.privacy-body h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 28px 0 10px; }}
.privacy-body p {{ font-size: 0.92rem; line-height: 1.6; color: var(--ink); }}
.privacy-body p.updated {{ color: var(--muted); font-size: 0.78rem; margin-top: 32px; border-top: 1px solid var(--border); padding-top: 16px; }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › Personvern og cookies</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Personvern</div>
      <h1>Personvern og cookies</h1>
      <p>Hvilke informasjonskapsler vi bruker på Kontaktlinser.no, hvorfor, og hvordan du styrer dem selv.</p>
    </div>
  </div>

  <div class="privacy-body" style="max-width:640px;">
    <p>En informasjonskapsel (cookie) er en liten tekstfil nettleseren din lagrer
    når du besøker en nettside. Denne siden beskriver hvilke vi bruker og
    hvorfor, i tråd med ekomloven § 3-15 og personvernforordningen (GDPR).</p>

    <h2>Hvilke informasjonskapsler bruker vi</h2>
    <table class="cookie-table">
      <tr><th>Kilde</th><th>Formål</th><th>Type</th></tr>
      <tr>
        <td>Google Tag Manager</td>
        <td>Måler trafikk og bruk av siden, slik at vi vet hvilket innhold som faktisk er nyttig.</td>
        <td>Ikke nødvendig (statistikk)</td>
      </tr>
      <tr>
        <td>Tradedoubler, Awin, Adtraction</td>
        <td>Settes først når du klikker deg videre til en forhandler via en
        tilbudslenke fra oss. Registrerer at besøket kom fra
        Kontaktlinser.no, slik at forhandleren kan betale riktig provisjon til
        oss. Disse cookiene settes av det aktuelle affiliate-nettverket eller
        forhandlerens eget domene, ikke av Kontaktlinser.no direkte.</td>
        <td>Ikke nødvendig (tilknyttet markedsføring)</td>
      </tr>
    </table>
    <p style="font-size:0.8rem;color:var(--muted);">Vi bruker ikke cookies til noe utover dette - ingen retargeting-annonsering
    og ingen deling eller salg av data til tredjeparter.</p>

    <h2>Samtykke</h2>
    <p>Ved første besøk får du opp en samtykke-boks der du kan velge "Godta",
    "Kun nødvendige", eller tilpasse statistikk og affiliate-sporing hver for
    seg (under "Innstillinger" finner du også en full liste over
    tredjepartsleverandørene vi samarbeider med). Statistikk-skriptet (Google
    Tag Manager) lastes ikke før du har samtykket til det. Valget lagres i
    nettleseren din og du kan endre det når som helst ved å slette lagret
    nettstedsdata for Kontaktlinser.no i nettleserinnstillingene og laste
    siden på nytt.</p>

    <h2>Hvordan kontrollere eller slette cookies</h2>
    <p>De fleste nettlesere lar deg se, blokkere og slette cookies under
    personvern- eller sikkerhetsinnstillingene. Slår du av ikke-nødvendige
    cookies helt, vil Kontaktlinser.no fortsatt fungere som normalt - vi
    bruker dem kun til måling og provisjonssporing, ikke til selve
    prissammenligningen.</p>

    <h2>Kontakt</h2>
    <p>Spørsmål om personvern eller cookies på Kontaktlinser.no? Send oss en
    e-post på {_contact_email_link()}.</p>

    <p class="updated">Sist oppdatert: {updated}</p>
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_terms_page() -> str:
    """/vilkar/ -- juridisk informasjon og ansvarsfraskrivelse. Teksten er
    brukerens egen, limt inn 2026-08-30 (kun konvertert fra markdown til
    HTML, ordlyden er uendret). Fungerer som en paraply-side over de
    kortere, kontekstuelle disclosure-avsnittene som allerede finnes på
    produkt-/kategori-/private label-sider (footer-disclosure,
    .disclosure-avsnitt, /om-produktillustrasjoner/) -- erstatter ingen av
    dem, samler bare hele bildet ett sted. Kontaktpunktet i §11
    (_contact_email_link()) er allerede reelt og synlig i footeren på alle
    sider, ikke en tom påstand."""
    updated = _legal_date(TERMS_UPDATED)
    contact = _contact_email_link()

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "Vilkår og ansvarsfraskrivelse", "item": "{BASE_URL}/vilkar/"}}
  ]
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vilkår og ansvarsfraskrivelse – Kontaktlinser.no</title>
<meta name="description" content="Juridisk informasjon om Kontaktlinser.no: varemerker og logoer, produktbilder og -illustrasjoner, private label, prisinformasjon, affiliate-samarbeid og ansvarsforhold.">
<link rel="canonical" href="{BASE_URL}/vilkar/">
{_og_meta('Vilkår og ansvarsfraskrivelse – Kontaktlinser.no', 'Juridisk informasjon om Kontaktlinser.no: varemerker og logoer, produktbilder og -illustrasjoner, private label, prisinformasjon, affiliate-samarbeid og ansvarsforhold.', BASE_URL + '/vilkar/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.privacy-body h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 28px 0 10px; }}
.privacy-body p {{ font-size: 0.92rem; line-height: 1.6; color: var(--ink); }}
.privacy-body p.updated {{ color: var(--muted); font-size: 0.78rem; margin-top: 32px; border-top: 1px solid var(--border); padding-top: 16px; }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › Vilkår og ansvarsfraskrivelse</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Juridisk informasjon</div>
      <h1>Vilkår og ansvarsfraskrivelse</h1>
      <p>Om Kontaktlinser.no, varemerker og bilder, private label-produkter, prisinformasjon og ansvarsforhold.</p>
    </div>
  </div>

  <div class="privacy-body" style="max-width:680px;">
    <p>Kontaktlinser.no er en uavhengig pris- og informasjonstjeneste for kontaktlinser. Formålet med tjenesten er å gjøre det enklere for forbrukere å finne informasjon om kontaktlinser, sammenligne produkter og sammenligne priser hos ulike forhandlere.</p>
    <p>Kontaktlinser.no selger ikke kontaktlinser og er ikke part i kjøpsavtalen mellom brukeren og den aktuelle forhandleren. Kjøp gjennomføres hos forhandleren brukeren velger, og det er forhandlerens kjøpsvilkår, leveringsbetingelser, returregler og øvrige vilkår som gjelder for kjøpet.</p>

    <h2>1. Varemerker, logoer og produktnavn</h2>
    <p>Kontaktlinser.no omtaler og sammenligner produkter fra en rekke produsenter og merkevarer.</p>
    <p>Varemerker, logoer, produktnavn, firmanavn og andre kjennetegn som vises på Kontaktlinser.no tilhører sine respektive rettighetshavere.</p>
    <p>Slike kjennetegn benyttes for å identifisere og informere om produktene, produsentene og forhandlerne som omtales eller sammenlignes på tjenesten.</p>
    <p>Bruk av et varemerke, en logo eller et produktnavn på Kontaktlinser.no innebærer ikke i seg selv at Kontaktlinser.no er eid av, tilknyttet, sponset, godkjent eller på annen måte offisielt forbundet med den aktuelle rettighetshaveren.</p>
    <p>Der det foreligger et kommersielt samarbeid, for eksempel gjennom et affiliateprogram, kan Kontaktlinser.no motta godtgjørelse for trafikk eller kjøp som formidles til den aktuelle forhandleren.</p>

    <h2>2. Produktbilder og annet visuelt materiale</h2>
    <p>Kontaktlinser.no benytter visuelt materiale for å gjøre det enklere å identifisere og sammenligne produkter.</p>
    <p>Produktbilder, logoer og annet visuelt materiale kan blant annet være gjort tilgjengelig gjennom produsenter, forhandlere, affiliateprogrammer, produktfeeder, mediebanker eller andre kilder.</p>
    <p>Rettighetene til originale produktbilder, logoer, emballasjedesign og annet materiale tilhører de respektive rettighetshaverne.</p>
    <p>Materialet brukes på Kontaktlinser.no i forbindelse med identifikasjon, informasjon og sammenligning av de aktuelle produktene og merkevarene.</p>

    <h2>3. Egne produktillustrasjoner</h2>
    <p>Når et egnet originalt produktbilde ikke er tilgjengelig, kan Kontaktlinser.no benytte en egen produktillustrasjon.</p>
    <p>En slik illustrasjon er laget for å hjelpe brukeren med å identifisere og skille mellom produkter som omtales eller sammenlignes på tjenesten.</p>
    <p>Produktillustrasjoner laget av Kontaktlinser.no er ikke originale produktbilder og skal ikke oppfattes som en nøyaktig gjengivelse av produsentens offisielle produktemballasje.</p>
    <p>Farger, proporsjoner, grafiske elementer, tekst, emballasje og andre visuelle detaljer kan avvike fra det faktiske produktet.</p>
    <p>Når Kontaktlinser.no benytter en egen produktillustrasjon, søker vi å gjøre dette tydelig for brukeren. Se <a href="/om-produktillustrasjoner/">om produktillustrasjoner</a> for mer informasjon.</p>

    <h2>4. Private label og tilsvarende produkter</h2>
    <p>Enkelte kontaktlinser selges under andre produktnavn eller som såkalte private-label-produkter.</p>
    <p>Kontaktlinser.no kan vise informasjon om at et produkt tilsvarer, er relatert til eller kan være produsert på grunnlag av samme eller tilsvarende produkt som et annet kontaktlinseprodukt.</p>
    <p>Slike koblinger bygger på informasjon og produktdata som Kontaktlinser.no har tilgjengelig. Se <a href="/private-label/">oversikten over optikerkjedenes egne merker</a> for en samlet oversikt over disse koblingene.</p>
    <p>Opplysninger om tilsvarende produkter er ment som informasjon og hjelp til produktidentifikasjon. Brukeren bør kontrollere relevante produktspesifikasjoner og sin kontaktlinseresept før bestilling.</p>
    <p>Produkter bør ikke byttes utelukkende på grunnlag av produktnavn, pris eller informasjon om tilsvarende produkter på Kontaktlinser.no dersom dette innebærer endring fra produktet som er anbefalt eller tilpasset av optiker eller annet kvalifisert helsepersonell.</p>

    <h2>5. Priser og prisinformasjon</h2>
    <p>Kontaktlinser.no innhenter og behandler pris- og produktinformasjon fra blant annet forhandlere, produktfeeder, affiliateprogrammer og andre datakilder.</p>
    <p>Vi arbeider for at informasjonen skal være korrekt og oppdatert, men priser, lagerstatus, fraktkostnader, rabattvilkår, kampanjer og andre forhold kan endres uten at dette umiddelbart gjenspeiles på Kontaktlinser.no.</p>
    <p>Prisen og vilkårene som vises hos forhandleren på tidspunktet for kjøpet er derfor avgjørende.</p>
    <p>Der Kontaktlinser.no viser totalpris inkludert beregnet frakt, bygger beregningen på den fraktinformasjonen og de vilkårene vi har tilgjengelig. Fri frakt, minimumsbeløp, geografiske begrensninger eller andre vilkår hos forhandleren kan påvirke den endelige prisen.</p>
    <p>Kontaktlinser.no garanterer ikke at en oppgitt pris til enhver tid er markedets laveste pris.</p>
    <p>Når uttrykk som «lavest pris», «billigst» eller tilsvarende benyttes, gjelder sammenligningen de forhandlerne og prisdataene som inngår i den aktuelle sammenligningen på det aktuelle tidspunktet, med mindre annet uttrykkelig fremgår.</p>

    <h2>6. Affiliate-samarbeid og finansiering</h2>
    <p>Kontaktlinser.no kan motta provisjon eller annen godtgjørelse når en bruker klikker seg videre til en forhandler eller gjennomfører et kjøp hos en forhandler via en lenke fra Kontaktlinser.no.</p>
    <p>Dette kalles affiliate-markedsføring.</p>
    <p>Slike samarbeid bidrar til å finansiere driften av Kontaktlinser.no og gjør det mulig å tilby tjenesten til brukerne uten betaling.</p>
    <p>Ikke alle butikker, produkter eller priser på markedet er nødvendigvis inkludert på Kontaktlinser.no. Hvilke forhandlere som kan vises kan blant annet avhenge av tilgang til pålitelige produkt- og prisdata, teknisk integrasjon og kommersielle samarbeid.</p>
    <p>Enkelte samarbeid kan også gi Kontaktlinser.no tilgang til egne produktfeeder, kampanjer, rabattkoder eller priser.</p>
    <p>Kontaktlinser.no arbeider for at kommersielle samarbeid ikke skal gjøre prisinformasjonen misvisende.</p>

    <h2>7. Produktinformasjon og helseinformasjon</h2>
    <p>Informasjonen på Kontaktlinser.no er generell informasjon og erstatter ikke undersøkelse, tilpasning eller individuell rådgivning fra optiker, øyelege eller annet kvalifisert helsepersonell.</p>
    <p>Kontaktlinser er produkter som brukes direkte på øyet. Feil bruk, feil styrke, feil passform eller mangelfull hygiene kan medføre problemer.</p>
    <p>Brukere bør følge anbefalingene fra optiker eller annet kvalifisert helsepersonell samt produsentens bruksanvisning.</p>
    <p>Kontaktlinser.no stiller ikke diagnose, tilpasser ikke kontaktlinser og gir ikke individuell medisinsk behandling.</p>

    <h2>8. Forhandlernes ansvar</h2>
    <p>Kontaktlinser.no formidler informasjon og lenker til eksterne forhandlere, men selger ikke produktene selv.</p>
    <p>Den aktuelle forhandleren er ansvarlig for blant annet bestilling, betaling, levering, kundeservice, angrerett, retur, reklamasjon og øvrig håndtering av kjøpet.</p>
    <p>Kontaktlinser.no er ikke ansvarlig for handlinger, tjenester, produkter eller innhold hos eksterne forhandlere.</p>
    <p>Brukeren bør kontrollere pris, produkt, styrke, antall linser, leveringsbetingelser og øvrige kjøpsvilkår hos forhandleren før bestillingen fullføres.</p>

    <h2>9. Feil og endringer</h2>
    <p>Kontaktlinser.no arbeider kontinuerlig med å holde produktdata, priser og øvrig informasjon korrekt og oppdatert.</p>
    <p>Det kan likevel forekomme feil, mangler, forsinkelser, tekniske problemer eller utdatert informasjon.</p>
    <p>Kontaktlinser.no forbeholder seg retten til å korrigere, oppdatere eller fjerne informasjon når som helst.</p>

    <h2>10. Eksterne nettsteder</h2>
    <p>Kontaktlinser.no inneholder lenker til nettsteder som drives av andre virksomheter.</p>
    <p>Når en bruker forlater Kontaktlinser.no, er det den eksterne virksomhetens egne vilkår og personvernregler som gjelder.</p>
    <p>Kontaktlinser.no har ikke kontroll over og er ikke ansvarlig for innholdet eller tilgjengeligheten på eksterne nettsteder.</p>

    <h2>11. Rettighetshavere</h2>
    <p>Kontaktlinser.no respekterer immaterielle rettigheter.</p>
    <p>Dersom du representerer en produsent, merkevare, forhandler eller annen rettighetshaver og mener at et varemerke, bilde, produktillustrasjon, produktopplysning eller annet materiale på Kontaktlinser.no brukes feil, ber vi deg kontakte oss på {contact}.</p>
    <p>Vi vil gjennomgå henvendelsen og ved behov korrigere, oppdatere eller fjerne materialet så raskt som praktisk mulig.</p>

    <h2>12. Endringer</h2>
    <p>Denne informasjonen kan oppdateres når tjenesten, datakildene, samarbeidene eller relevante regler endres.</p>

    <p class="updated">Sist oppdatert: {updated}</p>
  </div>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


_SPEC_NUMBER_RE = re.compile(r"\d+(?:,\d+)?")


def _parse_spec_numbers(raw: str | None) -> list[str]:
    """Trekker ut tallverdier fra en fritekst-spec-streng ('8,4 / 8,8 mm',
    '38 %', '51 % i kjernen, over 80 % på overflaten') -- håndterer norsk
    komma-desimal og fler-verdi-felt (dobbel basiskurve, kjerne/overflate-
    vanninnhold). Returnerer normaliserte streng-verdier (punktum som
    desimaltegn, sortert numerisk) -- KUN til filter-matching/visning, ikke
    videre utregning. Tom liste hvis produktet mangler dette spec-feltet
    (specs er fritekst, ikke strukturerte felt -- ca. halvparten av
    katalogen mangler Basiskurve/Diameter pr. 2026-09-05, se
    passform-filter-notatet i CLAUDE.md)."""
    if not raw:
        return []
    return sorted({m.replace(",", ".") for m in _SPEC_NUMBER_RE.findall(raw)}, key=float)


def _fit_filter_values(products: list[dict], spec_label: str) -> tuple[list[str], dict[str, list[str]]]:
    """For ett spec-felt (f.eks. 'Vanninnhold'): finner alle distinkte
    tallverdier blant PRODUKTENE PÅ DENNE KATEGORISIDEN (ikke hele
    katalogen -- en toriske-linser-side skal ikke tilby et basiskurve-tall
    som bare finnes hos en dagslinse), pluss et oppslag produkt-id -> dets
    egne verdier (til data-attributter på hvert kort)."""
    all_values: set[str] = set()
    by_product: dict[str, list[str]] = {}
    for p in products:
        specs = {label: value for label, value in p.get("specs", [])}
        values = _parse_spec_numbers(specs.get(spec_label))
        by_product[p["id"]] = values
        all_values.update(values)
    return sorted(all_values, key=float), by_product


def render_category_page(category_slug: str, category: dict, products: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        image_url = _product_image(p)
        rows.append({"product": p, "lowest": lowest, "image_url": image_url})

    # Statisk render, sortert lavest-først som standard - dette er det AI-crawlere
    # og brukere uten JS faktisk ser.
    rows.sort(key=lambda r: r["lowest"]["price_nok"] if r["lowest"] else float("inf"))

    # Passform-filter: vanninnhold/basiskurve/diameter, i tillegg til
    # merke-filteret -- ingen annen norsk kontaktlinse-prissammenligning har
    # dette pr. i dag. Verdiene finnes KUN som fritekst i specs (se
    # _parse_spec_numbers), og dekningen varierer mye per kategori (toriske/
    # multifokale har langt færre Basiskurve/Diameter-oppføringer enn dags-/
    # månedslinser) -- derfor regnet ut PER kategori og filteret utelates
    # helt der færre enn 2 distinkte verdier finnes.
    wc_values, wc_by_id = _fit_filter_values(products, "Vanninnhold")
    bc_values, bc_by_id = _fit_filter_values(products, "Basiskurve")
    dia_values, dia_by_id = _fit_filter_values(products, "Diameter")

    def spec_row_html_for(p: dict) -> str:
        # Kompakt spesifikasjonsrad på selve produktkortet -- eksplisitte
        # produktegenskaper er nyttige for mennesker OG for AI-retrieval
        # (2026-09-05-redesignet, se CLAUDE.md). Viser kun feltene produktet
        # faktisk har (mange produkter mangler BC/DIA, se notatet over).
        bits = []
        wc_v = wc_by_id.get(p["id"], [])
        bc_v = bc_by_id.get(p["id"], [])
        dia_v = dia_by_id.get(p["id"], [])
        if wc_v:
            bits.append(f'<span class="product-tile-spec">{DROPLET_ICON_SVG}{escape(wc_v[0].replace(".", ","))} %</span>')
        if bc_v:
            bits.append(f'<span class="product-tile-spec">{BASISKURVE_ICON_SVG}{escape(bc_v[0].replace(".", ","))} mm</span>')
        if dia_v:
            bits.append(f'<span class="product-tile-spec">{DIAMETER_ICON_SVG}{escape(dia_v[0].replace(".", ","))} mm</span>')
        return f'<div class="product-tile-specs-row">{"".join(bits)}</div>' if bits else ""

    def render_row(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        # På kategorisider (i motsetning til merkesider) er MERKET det som
        # faktisk varierer/skiller kortene fra hverandre -- produsent er ofte
        # konstant på tvers av flere merker (CooperVision -> Biofinity/Avaira/
        # MyDay/...), så merkenavnet fyller samme "nyttig, varierende info
        # rett under tittelen"-rolle som produsent gjorde på merkesiden.
        brand_link = f'<a class="product-tile-manufacturer" href="/merke/{escape(p["brand_slug"])}/">{escape(p["brand_label"])}</a>'
        fit_attrs = (
            f' data-wc="{" ".join(wc_by_id.get(p["id"], []))}"'
            f' data-bc="{" ".join(bc_by_id.get(p["id"], []))}"'
            f' data-dia="{" ".join(dia_by_id.get(p["id"], []))}"'
        )
        return _render_product_tile(
            href=f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/',
            name=p["name"],
            image_url=r["image_url"],
            fallback_initials=p["brand_label"][:2].upper(),
            category_label=category["label"],
            secondary_line_html=brand_link,
            lowest=lowest,
            other_count=len(p["offers"]) - 1,
            data_attr=f' data-brand="{escape(p["brand_slug"])}"{fit_attrs}',
            specs_row_html=spec_row_html_for(p),
        )

    product_rows_html = "\n".join(render_row(r) for r in rows)

    # Merker: ekte antall produkter per merke (populære merker = flest
    # produkter i DENNE kategorien, ikke en gjettet/manuelt satt liste) --
    # og ekte visningsnavn (brand_label), ikke en .capitalize()-gjetning på
    # slugen som tidligere ga feil for f.eks. "ClearLab".
    brand_counts: dict[str, int] = {}
    brand_labels: dict[str, str] = {}
    for p in products:
        brand_counts[p["brand_slug"]] = brand_counts.get(p["brand_slug"], 0) + 1
        brand_labels[p["brand_slug"]] = p["brand_label"]
    sorted_brands = sorted(brand_counts, key=lambda b: (-brand_counts[b], brand_labels[b]))
    n_brands = len(sorted_brands)
    n_products = len(products)
    POPULAR_N = 6
    popular_brands = sorted_brands[:POPULAR_N]
    rest_brands = sorted_brands[POPULAR_N:]

    def brand_chip(b: str) -> str:
        return (
            f'<button type="button" class="chip" data-group="brand" data-value="{escape(b)}" '
            f'aria-pressed="false">{escape(brand_labels[b])} <span class="chip-count">{brand_counts[b]}</span></button>'
        )

    popular_chips_html = "".join(brand_chip(b) for b in popular_brands)
    rest_chips_html = "".join(brand_chip(b) for b in rest_brands)
    show_all_toggle_html = (
        f'<button type="button" class="chip chip-ghost" id="brand-toggle-more" aria-expanded="false">'
        f'Alle merker ({n_brands}) <span aria-hidden="true">+</span></button>'
        if rest_brands else ""
    )

    def fit_dropdown_html(key: str, label: str, values: list[str], fmt, icon: str, optional: bool = False) -> str:
        # Utelates helt (ikke bare tom rad) hvis under 2 distinkte verdier
        # finnes for denne kategorien -- et filter med 0-1 valg gjør
        # ingenting nyttig, bare rot.
        if len(values) < 2:
            return ""
        chips = "".join(
            f'<button type="button" class="chip" data-group="{key}" data-value="{escape(v)}" '
            f'aria-pressed="false">{escape(fmt(v))}</button>'
            for v in values
        )
        subtitle = "Velg én eller flere verdier" + (" (valgfritt)" if optional else "")
        return f'''<details class="filter-dd" data-filter-dd="{key}">
    <summary>
      <span class="filter-dd-icon">{icon}</span>
      <span class="filter-dd-text">
        <span class="filter-dd-label">{escape(label)}</span>
        <span class="filter-dd-sub" data-summary-for="{key}">{subtitle}</span>
      </span>
      <span class="filter-dd-chevron" aria-hidden="true">▾</span>
    </summary>
    <div class="filter-dd-panel" role="group" aria-label="Filtrer etter {escape(label.lower())}">{chips}</div>
  </details>'''

    # Rekkefølge BC -> DIA -> Vanninnhold sist (2026-09-05, avtalt med
    # bruker): BC/DIA er en reell tilpasningsegenskap (nyttig for å finne
    # produkter med bestemte spesifikasjoner -- IKKE en påstand om at samme
    # tall gjør produkter medisinsk utbyttbare), vanninnhold er en mykere,
    # mer sekundær egenskap og derfor markert "(valgfritt)" og plassert sist.
    # Alle tre er multi-select (kan velge flere verdier samtidig per felt).
    bc_dd_html = fit_dropdown_html("bc", "Basiskurve (BC)", bc_values, lambda v: f"{v.replace('.', ',')} mm", BASISKURVE_ICON_SVG)
    dia_dd_html = fit_dropdown_html("dia", "Diameter (DIA)", dia_values, lambda v: f"{v.replace('.', ',')} mm", DIAMETER_ICON_SVG)
    wc_dd_html = fit_dropdown_html("wc", "Vanninnhold", wc_values, lambda v: f"{v.replace('.', ',')} %", DROPLET_ICON_SVG, optional=True)
    filter_dd_html = bc_dd_html + dia_dd_html + wc_dd_html

    guides_html = "\n".join(
        f'<li><a href="/guide/{escape(g["slug"])}/">{escape(g["title"])}</a></li>' for g in category.get("guides", [])
    )

    # Datadrevet intro -- alle 5 kategori-introer i products_meta.json deler
    # nøyaktig denne halen ("fra alle merker vi følger"), erstattet med
    # ekte, live tall (2026-09-05-redesignet). Samme tekst brukes i
    # meta-description/og-meta, ikke bare i synlig H1-intro.
    intro_text = category["intro"].replace(
        "fra alle merker vi følger",
        f"fra {n_brands} merker og {n_products} produkter",
    )

    # "Hva er X?"-boks: kort, faktabasert forklaring + lenke til første guide
    # i kategoriens egen guide-liste (ingen hardkodet guide-slug her). Egen
    # tegnet linse-illustrasjon (to overlappende linser) i stedet for en
    # liten ikon-badge -- samme generiske motiv for alle 5 kategorier, siden
    # dette handler om at det ER en kontaktlinse, ikke om selve kategorien.
    explainer_text = CATEGORY_EXPLAINERS.get(category_slug, "")
    category_guides = category.get("guides", [])
    explainer_html = ""
    if explainer_text and category_guides:
        explainer_html = f'''<div class="category-explainer">
    <div class="category-explainer-illustration">{LENS_PAIR_ILLUSTRATION_SVG}</div>
    <div>
      <h2>Hva er {escape(category["label"].lower())}?</h2>
      <p>{escape(explainer_text)}</p>
      <a href="/guide/{escape(category_guides[0]["slug"])}/">Les mer →</a>
    </div>
  </div>'''

    # "Om utvalget"-oppsummering under produktlisten: ekte beregnede spenn
    # (aldri egne sonebolker/klassifiseringer -- ekte tallverdier er
    # produktegenskaper, en sonebolk ville vært en tolkning vi selv
    # introduserer). Samme "utelat helt der for lite data"-prinsipp som
    # filtrene -- kun spenn med >=2 distinkte verdier vises.
    def _range_text(values: list[str], unit: str) -> str | None:
        if len(values) < 2:
            return None
        lo, hi = values[0].replace(".", ","), values[-1].replace(".", ",")
        return None if lo == hi else f"{lo}–{hi} {unit}"

    range_bits = []
    bc_range, dia_range, wc_range = _range_text(bc_values, "mm"), _range_text(dia_values, "mm"), _range_text(wc_values, "%")
    if bc_range:
        range_bits.append(f"basiskurve fra {bc_range}")
    if dia_range:
        range_bits.append(f"diameter fra {dia_range}")
    if wc_range:
        range_bits.append(f"vanninnhold fra {wc_range}")
    category_summary_html = ""
    if range_bits:
        bits_text = range_bits[0] if len(range_bits) == 1 else ", ".join(range_bits[:-1]) + " og " + range_bits[-1]
        category_summary_html = f'''<section class="product-ai-summary" aria-label="Om utvalget">
  <p><strong>Om utvalget:</strong> Kontaktlinser.no sammenligner for tiden {n_products} {escape(category["label"].lower())} fra {n_brands} merker. Produktene i oversikten har {bits_text}.</p>
</section>'''

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
<title>Billige {escape(category["label"].lower())} – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="{escape(intro_text)}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{category_slug}/">
{_og_meta(f'Billige {category["label"].lower()} – Sammenlign priser | Kontaktlinser.no', intro_text, f'{BASE_URL}/kontaktlinser/{category_slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 28px; flex-wrap: wrap; }}
.hero-copy {{ flex: 1 1 320px; max-width: 680px; }}
.category-stats {{ display: flex; flex-wrap: wrap; margin-top: 18px; background: var(--blue-tint); border: 1px solid var(--border); border-radius: 12px; padding: 4px; }}
.category-stat {{ display: flex; align-items: center; justify-content: center; gap: 7px; flex: 1 1 auto; padding: 8px 14px; border-right: 1px solid var(--border); font-size: 0.8rem; color: var(--ink); font-family: 'Inter', sans-serif; white-space: nowrap; }}
.category-stat:last-child {{ border-right: none; }}
.category-stat svg {{ width: 16px; height: 16px; color: var(--blue); flex-shrink: 0; }}
.category-explainer {{ flex: 0 1 300px; display: flex; flex-direction: column; gap: 10px; background: var(--blue-tint); border-radius: 14px; padding: 18px 20px; }}
.category-explainer-illustration {{ align-self: flex-start; }}
.category-explainer-illustration svg {{ width: 110px; height: 72px; display: block; }}
.category-explainer h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 0.95rem; margin: 0; }}
.category-explainer p {{ margin: 0 0 4px; font-size: 0.84rem; line-height: 1.5; color: var(--ink); }}
.category-explainer a {{ font-size: 0.84rem; font-weight: 700; color: var(--blue); text-decoration: none; }}
.category-explainer a:hover {{ text-decoration: underline; }}
.category-filters-bar {{ margin: 26px 0 20px; }}
.category-brand-row {{ margin-top: 18px; }}
.category-filters-label {{ display: block; font-family: 'Space Grotesk', sans-serif; font-size: 0.85rem; font-weight: 700; margin-bottom: 8px; }}
.brand-chip-row {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.brand-chip-row[hidden] {{ display: none; }}
.brand-more-wrap {{ margin-top: 8px; }}
.chip-count {{ opacity: 0.6; font-weight: 500; }}
.chip.active .chip-count {{ opacity: 0.85; }}
.chip-ghost {{ background: transparent; border-style: dashed; color: var(--blue); }}
.filter-trigger {{ display: none; align-items: center; justify-content: center; gap: 8px; width: 100%; padding: 12px 16px; background: var(--blue-tint); color: var(--blue); border: none; border-radius: 10px; font-weight: 700; font-size: 0.88rem; cursor: pointer; }}
.filter-trigger-badge {{ background: var(--blue); color: white; font-size: 0.72rem; min-width: 18px; height: 18px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; padding: 0 5px; }}
.filter-trigger-badge[hidden] {{ display: none; }}
.filter-backdrop {{ display: none; }}
.category-filters {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.filter-sheet-header, .filter-sheet-footer {{ display: none; }}
.filter-dd {{ position: relative; }}
.filter-dd > summary {{ list-style: none; display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: white; border: 1px solid var(--border); border-radius: 10px; cursor: pointer; font-size: 0.85rem; user-select: none; }}
.filter-dd > summary::-webkit-details-marker {{ display: none; }}
.filter-dd-icon {{ display: flex; color: var(--blue); flex-shrink: 0; }}
.filter-dd-icon svg {{ width: 16px; height: 16px; }}
.filter-dd-text {{ display: flex; flex-direction: column; line-height: 1.3; }}
.filter-dd-label {{ font-weight: 700; }}
.filter-dd-sub {{ font-size: 0.74rem; color: var(--muted); }}
.filter-dd-chevron {{ margin-left: auto; color: var(--muted); transition: transform 0.15s; }}
.filter-dd[open] .filter-dd-chevron {{ transform: rotate(180deg); }}
.filter-dd-panel {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 4px 2px; }}
.active-filters-wrap {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 16px 0 20px; }}
.active-filters-wrap[hidden] {{ display: none; }}
.active-filters {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.active-filter-chip {{ display: inline-flex; align-items: center; gap: 6px; background: var(--blue-tint); color: var(--blue-dark); border: none; border-radius: 999px; padding: 6px 10px; font-size: 0.78rem; font-weight: 600; cursor: pointer; }}
.filter-reset-link {{ display: inline-flex; align-items: center; gap: 6px; background: none; border: none; color: var(--blue); font-size: 0.78rem; font-weight: 700; cursor: pointer; padding: 0; }}
.filter-reset-link svg {{ width: 14px; height: 14px; }}
.sort-select {{ font-size: 0.82rem; font-weight: 600; color: var(--ink); border: 1px solid var(--border); border-radius: 999px; padding: 8px 30px 8px 14px; background: white url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2364748B' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E") no-repeat right 10px center / 14px 14px; appearance: none; cursor: pointer; }}
@media (min-width: 1024px) {{
  .filter-dd-panel {{ position: absolute; top: calc(100% + 6px); left: 0; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 14px; box-shadow: var(--card-shadow); min-width: 260px; z-index: 20; }}
}}
@media (max-width: 1023px) {{
  .filter-trigger {{ display: flex; }}
  .category-filters {{ position: fixed; left: 0; right: 0; bottom: 0; background: white; border-radius: 18px 18px 0 0; padding: 18px; flex-direction: column; gap: 10px; max-height: 82vh; overflow-y: auto; transform: translateY(105%); transition: transform 0.25s ease; z-index: 60; box-shadow: 0 -8px 30px rgba(11,37,69,0.18); }}
  .category-filters.is-open {{ transform: translateY(0); }}
  .filter-dd {{ width: 100%; }}
  .filter-sheet-header {{ display: flex; align-items: center; justify-content: space-between; }}
  .filter-sheet-header h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0; }}
  .filter-sheet-close {{ background: none; border: none; cursor: pointer; color: var(--muted); padding: 4px; }}
  .filter-sheet-close svg {{ width: 20px; height: 20px; }}
  .filter-sheet-footer {{ display: flex; flex-direction: column; gap: 10px; margin-top: 6px; position: sticky; bottom: 0; background: white; padding-top: 10px; }}
  .btn-primary-block {{ background: var(--blue); color: white; border: none; border-radius: 10px; padding: 13px; font-weight: 700; font-size: 0.92rem; cursor: pointer; }}
  .filter-backdrop {{ position: fixed; inset: 0; background: rgba(11,37,69,0.35); z-index: 55; }}
  .filter-backdrop[hidden] {{ display: none; }}
}}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(category["label"])}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Kategori</div>
      <h1>{escape(category["label"])}</h1>
      <p>{escape(intro_text)}</p>
      <div class="category-stats">
        <span class="category-stat">{BOX_ICON_SVG}<span>{n_products} produkter</span></span>
        <span class="category-stat">{TAG_ICON_SVG}<span>{n_brands} merker</span></span>
        <span class="category-stat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">{_BUILDING_ICON}</svg><span>Norske nettbutikker</span></span>
        <span class="category-stat">{CALENDAR_ICON_SVG}<span>Priser oppdateres daglig</span></span>
      </div>
      <div class="category-brand-row">
        <span class="category-filters-label">Populære merker</span>
        <div class="brand-chip-row">
          {popular_chips_html}
          {show_all_toggle_html}
        </div>
        <div class="brand-chip-row brand-more-wrap" id="brand-more-wrap" hidden>
          {rest_chips_html}
        </div>
      </div>
    </div>
    {explainer_html}
  </div>

  <div class="category-filters-bar">
    <button type="button" class="filter-trigger" id="filter-trigger">
      Filtrer produkter
      <span class="filter-trigger-badge" id="filter-trigger-badge" hidden>0</span>
    </button>
    <div class="filter-backdrop" id="filter-backdrop" hidden></div>
    <div class="category-filters" id="category-filters">
      <div class="filter-sheet-header">
        <h2>Filtrer produkter</h2>
        <button type="button" class="filter-sheet-close" id="filter-sheet-close" aria-label="Lukk filter">{X_ICON_SVG}</button>
      </div>
      {filter_dd_html}
      <div class="filter-sheet-footer">
        <button type="button" class="btn-primary-block" id="sheet-show-count">Vis {n_products} produkter</button>
        <button type="button" class="filter-reset-link" data-reset-filters style="justify-content:center;">{RESET_ICON_SVG} Nullstill alle filtre</button>
      </div>
    </div>
  </div>

  <div class="active-filters-wrap" id="active-filters-wrap" hidden>
    <div class="active-filters" id="active-filters"></div>
    <button type="button" class="filter-reset-link" data-reset-filters>{RESET_ICON_SVG} Nullstill alle filtre</button>
  </div>

  <div class="list-header">
    <h2 id="result-count">{n_products} produkter</h2>
    <select id="sort-select" class="sort-select" aria-label="Sorter produkter">
      <option value="price-asc">Sorter: Laveste pris</option>
      <option value="price-desc">Sorter: Høyeste pris</option>
    </select>
  </div>

  <!-- Statisk, allerede sortert lavest-først. JS under er kun en forbedring
       (filter/re-sortering) ovenpå dette - fungerer uten JS også. Alle
       filterverdier over er ekte, server-rendrede knapper (ikke hentet via
       JS) -- kun VISNINGEN (åpen/lukket dropdown, sheet på mobil) er en
       CSS/JS-forbedring. -->
  <div id="product-list" class="product-tile-grid">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering og sortering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>

  {category_summary_html}

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
(function () {{
  const list = document.getElementById('product-list');
  const resultCount = document.getElementById('result-count');
  const groupLabels = {{ brand: 'Merke', bc: 'Basiskurve', dia: 'Diameter', wc: 'Vanninnhold' }};
  const selections = {{ brand: new Set(), bc: new Set(), dia: new Set(), wc: new Set() }};
  const activeFiltersWrap = document.getElementById('active-filters-wrap');
  const activeChipsEl = document.getElementById('active-filters');

  function fmtValue(key, v) {{
    if (key === 'wc') return v.replace('.', ',') + ' %';
    if (key === 'bc' || key === 'dia') return v.replace('.', ',') + ' mm';
    const chip = document.querySelector('.chip[data-group="' + key + '"][data-value="' + CSS.escape(v) + '"]');
    return chip ? chip.textContent.replace(/\\s*\\d+\\s*$/, '').trim() : v;
  }}

  function syncChipsFor(group, value) {{
    const pressed = selections[group].has(value);
    document.querySelectorAll('.chip[data-group="' + group + '"][data-value="' + CSS.escape(value) + '"]').forEach(el => {{
      el.setAttribute('aria-pressed', pressed ? 'true' : 'false');
      el.classList.toggle('active', pressed);
    }});
  }}

  const filterDdSubtitles = {{}};
  document.querySelectorAll('[data-filter-dd]').forEach(dd => {{
    const key = dd.dataset.filterDd;
    filterDdSubtitles[key] = dd.querySelector('[data-summary-for="' + key + '"]');
  }});

  function updateDropdownSubtitles() {{
    Object.keys(filterDdSubtitles).forEach(key => {{
      const el = filterDdSubtitles[key];
      if (!el) return;
      const set = selections[key];
      if (!set.size) {{
        el.textContent = 'Velg én eller flere verdier' + (key === 'wc' ? ' (valgfritt)' : '');
      }} else {{
        el.textContent = Array.from(set).map(v => fmtValue(key, v)).join(', ');
      }}
    }});
  }}

  function updateFilterBadge() {{
    const count = selections.bc.size + selections.dia.size + selections.wc.size;
    const badge = document.getElementById('filter-trigger-badge');
    if (badge) {{ badge.textContent = count; badge.hidden = count === 0; }}
  }}

  function renderActiveFilters() {{
    const parts = [];
    Object.keys(selections).forEach(group => {{
      selections[group].forEach(value => parts.push({{ group, value }}));
    }});
    if (!parts.length) {{
      activeFiltersWrap.hidden = true;
      activeChipsEl.innerHTML = '';
    }} else {{
      activeFiltersWrap.hidden = false;
      activeChipsEl.innerHTML = parts.map(p =>
        '<button type="button" class="active-filter-chip" data-remove-group="' + p.group + '" data-remove-value="' + p.value.replace(/"/g, '&quot;') + '">' +
        groupLabels[p.group] + ': ' + fmtValue(p.group, p.value) + ' <span aria-hidden="true">✕</span></button>'
      ).join('');
    }}
    updateFilterBadge();
    updateDropdownSubtitles();
  }}

  function applyFilters() {{
    let visible = 0;
    list.querySelectorAll('.product-tile').forEach(card => {{
      const show = Object.keys(selections).every(group => {{
        const set = selections[group];
        if (!set.size) return true;
        const cardValues = (card.dataset[group] || '').split(' ');
        return cardValues.some(v => set.has(v));
      }});
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    resultCount.textContent = visible + ' produkter';
    const sheetShow = document.getElementById('sheet-show-count');
    if (sheetShow) sheetShow.textContent = 'Vis ' + visible + ' produkter';
  }}

  document.querySelectorAll('.chip[data-group]').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const group = btn.dataset.group, value = btn.dataset.value;
      if (selections[group].has(value)) selections[group].delete(value);
      else selections[group].add(value);
      syncChipsFor(group, value);
      renderActiveFilters();
      applyFilters();
    }});
  }});

  activeChipsEl.addEventListener('click', e => {{
    const btn = e.target.closest('[data-remove-group]');
    if (!btn) return;
    selections[btn.dataset.removeGroup].delete(btn.dataset.removeValue);
    syncChipsFor(btn.dataset.removeGroup, btn.dataset.removeValue);
    renderActiveFilters();
    applyFilters();
  }});

  document.querySelectorAll('[data-reset-filters]').forEach(btn => {{
    btn.addEventListener('click', () => {{
      Object.keys(selections).forEach(group => {{
        Array.from(selections[group]).forEach(value => {{ selections[group].delete(value); syncChipsFor(group, value); }});
      }});
      renderActiveFilters();
      applyFilters();
      closeSheet();
    }});
  }});

  // Kun BC/DIA/Vanninnhold ligger i "Filtrer produkter"-arket på mobil --
  // merke-chipsene er allerede direkte synlige/trykkbare på selve siden.
  const sheetTrigger = document.getElementById('filter-trigger');
  const filterPanel = document.getElementById('category-filters');
  const sheetBackdrop = document.getElementById('filter-backdrop');
  const sheetClose = document.getElementById('filter-sheet-close');
  const sheetShowBtn = document.getElementById('sheet-show-count');

  function openSheet() {{ filterPanel.classList.add('is-open'); sheetBackdrop.hidden = false; document.body.style.overflow = 'hidden'; }}
  function closeSheet() {{ filterPanel.classList.remove('is-open'); sheetBackdrop.hidden = true; document.body.style.overflow = ''; }}
  if (sheetTrigger) sheetTrigger.addEventListener('click', openSheet);
  if (sheetClose) sheetClose.addEventListener('click', closeSheet);
  if (sheetBackdrop) sheetBackdrop.addEventListener('click', closeSheet);
  if (sheetShowBtn) sheetShowBtn.addEventListener('click', closeSheet);

  // "Alle merker"-utvidelse -- de øvrige merke-chipsene ligger allerede i
  // DOM-en (ekte, crawlbar HTML), kun synligheten endres.
  const brandMoreToggle = document.getElementById('brand-toggle-more');
  const brandMoreWrap = document.getElementById('brand-more-wrap');
  if (brandMoreToggle && brandMoreWrap) {{
    const initialLabel = brandMoreToggle.innerHTML;
    brandMoreToggle.addEventListener('click', () => {{
      const expanded = brandMoreToggle.getAttribute('aria-expanded') === 'true';
      brandMoreToggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
      brandMoreWrap.hidden = expanded;
      brandMoreToggle.innerHTML = expanded ? initialLabel : 'Skjul flere merker <span aria-hidden="true">−</span>';
    }});
  }}

  // Kun ett dropdown-filter åpent om gangen (desktop-mønster) + lukk ved
  // klikk utenfor.
  document.querySelectorAll('.filter-dd').forEach(dd => {{
    dd.addEventListener('toggle', () => {{
      if (dd.open) document.querySelectorAll('.filter-dd').forEach(other => {{ if (other !== dd) other.open = false; }});
    }});
  }});
  document.addEventListener('click', e => {{
    if (!e.target.closest('.filter-dd')) {{
      document.querySelectorAll('.filter-dd[open]').forEach(dd => {{ dd.open = false; }});
    }}
  }});

  const sortSelect = document.getElementById('sort-select');
  sortSelect.addEventListener('change', () => {{
    const desc = sortSelect.value === 'price-desc';
    const cards = Array.from(list.querySelectorAll('.product-tile'));
    cards.sort((a, b) => {{
      const av = parseFloat(a.querySelector('.product-tile-price')?.textContent.replace(/\\D/g, '')) || Infinity;
      const bv = parseFloat(b.querySelector('.product-tile-price')?.textContent.replace(/\\D/g, '')) || Infinity;
      return desc ? bv - av : av - bv;
    }});
    cards.forEach(c => list.appendChild(c));
  }});
}})();
</script>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


# "Linsevæske"/"øyedråper" o.l. -- delt produkttype (size_ml/solution_type/
# solution_category i stedet for category_slug/specs som kontaktlinser
# bruker), men samme pris-/tilbudslogikk. product["solution_category"]
# peker inn i dette oppslaget for URL-prefiks/tittel/intro -- ny kategori
# (f.eks. linseetui senere) er kun en ny nøkkel her, ingen kodeduplisering.
SOLUTION_CATEGORIES = {
    "linsevaeske": {
        "label": "Linsevæske",
        "title_label": "Billig linsevæske",
        "meta_description": "Sammenlign priser på linsevæske og reisepakker hos norske nettbutikker. Se pris per 100 ml, med eller uten frakt.",
        "intro": "Sammenlign priser på linsevæske og reisepakker hos norske nettbutikker. Vi viser pris per 100 ml der det er relevant, slik at store og små flasker er sammenlignbare.",
    },
    "tilbehor": {
        "label": "Tilbehør",
        "title_label": "Billig linsetilbehør",
        "intro": "Sammenlign priser på linseetui, pinsett og hjelpemidler for kontaktlinser og øyedråper hos norske nettbutikker.",
    },
    "oyedraper": {
        "label": "Øyedråper",
        "title_label": "Billige øyedråper",
        "meta_description": "Sammenlign priser på øyedråper, øyegel, øyesalve og øyepleie hos norske nettbutikker. Pris per 100 ml eller 100 g, med eller uten frakt.",
        "intro": "Sammenlign priser på øyedråper, øyegel, øyesalve og øyepleie mot tørre øyne hos norske nettbutikker. Vi viser pris per 100 ml (eller 100 g for gel og salve) der det er relevant, slik at ulike pakningsstørrelser er sammenlignbare.",
    },
}


# Hero-kort med produktbilde + tekst + vinnerkort, delt av lens- og tilbehørssider
# (kopi av reglene i render_product_page sin <style>, uten f-string-escaping).
HERO_IMAGE_STYLE = """.hero-card { background: white; border: 1px solid var(--border); border-radius: 20px; padding: 20px; margin-bottom: 20px; }
.hero-card .hero-copy h1 { font-size: 1.6rem; }
.hero-subtitle { margin: 2px 0 0; font-size: 0.92rem; color: var(--muted); font-weight: 500; }
/* "Pris ved flere esker/flasker" som eget, frittstående kort under
   prislista (qty_multi_inline=False) -- samme mønster som kontaktlinse-
   produktsiden (Kai, 2026-09-28: "Her er pris ved flere esker og den
   delen med blå bakgrunn ikke flyttet ned" på private label-siden). */
.wrap-product > .qty-multi { background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }
/* Product (Desktop) Gold Standard v1 -- portert hit fra render_product_page()
   2026-09-28 (Kai: "gjør samme hero-/quantity-redesign på linsevæske og
   private label", etter tidligere scope-avklaring "gjelder alle produkter
   på domenet kontaktlinser.no"). HERO_IMAGE_STYLE er allerede delt av
   render_solution_product_page() OG render_private_label_page(), så denne
   ene endringen gir begge samme nye design. render_product_page() har sin
   EGEN, urørte kopi av samme mønster (duplisert bevisst, ikke migrert til
   denne konstanten, for å ikke røre allerede skipet/testet kode) -- se
   dens docstring-kommentarer for den fulle designhistorikken/-begrunnelsen
   (Kai sine konkrete punkter er ikke gjentatt her, kun selve resultatet).
   .hero-media-row: bilde (~2/3) og Winner Card (~1/3) side ved side på
   mobil. */
.hero-media-row { display: flex; align-items: flex-start; gap: 12px; }
.hero-media-row .hero-product-image { flex: 2 1 0; min-width: 0; margin: 0; }
.hero-media-row .winner-band { flex: 1 1 0; min-width: 0; margin: 0; }
@media (min-width: 640px) { .hero-media-row { gap: 16px; } }
@media (max-width: 859px) {
  .hero-media-row .hero-product-image { aspect-ratio: 4 / 3; }
  .hero-media-row .winner-band-cta { padding: 10px 8px; gap: 6px; }
  .hero-media-row .winner-top { align-items: center; }
  .hero-media-row .winner-band-cta .label-group { flex-direction: row; align-items: baseline; gap: 4px; flex-wrap: wrap; }
  .hero-media-row .winner-band-cta .label { font-size: 0.68rem; letter-spacing: 0.01em; }
  .hero-media-row .winner-sub { font-size: 0.64rem; margin-top: 0; }
  .hero-media-row .winner-band-cta .retailer { margin-top: 6px !important; }
  .hero-media-row .winner-band-cta .retailer-logo { height: 18px; max-width: 88px; }
  .hero-media-row .winner-price-line { font-size: 0.68rem; line-height: 1.3; }
  .hero-media-row .winner-savings { width: 34px; height: 34px; }
  .hero-media-row .winner-savings-label { font-size: 0.4rem; }
  .hero-media-row .winner-savings-pct { font-size: 0.62rem; }
  .hero-media-row .winner-btn { font-size: 0.68rem; padding: 8px 4px; gap: 3px; margin-top: 2px; white-space: normal; text-align: center; line-height: 1.25; }
}
.hero-kicker, .hero-facts { display: none; }
/* Product Stage: ekte tre-kolonners CSS Grid på desktop (bilde | identitet+
   kontroller | Winner Card, samme vertikale arbeidsflate). .qty-box er
   fortsatt en egen DOM-node (søsken av .hero-card i .product-stage) --
   "flates" ut med display:contents på desktop slik at dens barn blir
   direkte grid-barn, uten noen DOM-flytting (mobil upåvirket). */
@media (min-width: 860px) {
  .product-stage {
    display: grid;
    grid-template-columns: minmax(360px, 0.95fr) minmax(420px, 1.10fr) minmax(280px, 0.72fr);
    grid-template-areas: "image identity price" "image controls price";
    column-gap: 32px;
    row-gap: 40px;
    background: white; border: 1px solid var(--border); border-radius: 20px;
    padding: 32px 36px;
  }
  .product-stage .hero-card, .product-stage .hero-main, .product-stage .hero-media-row { display: contents; }
  .product-stage .hero-kicker { display: block; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 0 0 6px; }
  .product-stage .hero-copy { grid-area: identity; align-self: start; }
  .product-stage .hero-copy h1 { font-size: 2rem; line-height: 1.18; margin: 0; }
  .product-stage .hero-subtitle { font-size: 1.2rem; font-weight: 400; margin: 8px 0 0; }
  .hero-facts { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin: 24px 0 0; font-size: 0.92rem; color: var(--muted); }
  .hero-fact-sep { color: var(--border); }
  .product-stage .hero-product-image { grid-area: image; align-self: center; width: 100%; height: 320px; max-width: none; margin: 0; }
  .product-stage > .qty-box { grid-area: controls; align-self: start; border: none; background: transparent; padding: 0; margin: 0; }
  .product-stage .qty-pills { display: flex; flex-wrap: wrap; gap: 8px; }
  .product-stage .qty-pill { width: 60px; height: 46px; padding: 0; box-shadow: none; }
  .product-stage .qty-pill.is-active { background: var(--mint-tint); border-color: var(--mint); color: var(--ink); box-shadow: none; }
  .product-stage .qty-pill.is-active span { color: var(--muted); }
  .product-stage .winner-band { grid-area: price; align-self: center; margin: 0; width: 100%; background: white; flex-direction: column; align-items: center; text-align: center; gap: 10px; position: relative; padding: 24px 18px 18px; }
  .product-stage .winner-left { flex-direction: column; align-items: center; gap: 0; }
  .product-stage .winner-trophy { position: absolute; top: -22px; left: 50%; transform: translateX(-50%); box-shadow: 0 2px 6px rgba(11, 37, 69, 0.15); }
  .product-stage .winner-band .label { margin-top: 0; }
  .product-stage .winner-band .retailer { justify-content: center; margin-top: 10px; }
  .product-stage .winner-band .winner-shipping { margin-top: 10px; }
  .product-stage .winner-price-group { text-align: center; }
  .product-stage .price-pill.is-winner { display: inline-block; background: none; color: var(--mint); padding: 0; font-size: 1.7rem; line-height: 1; }
  .product-stage .winner-price-note { margin-top: 7px; line-height: 1; }
  .product-stage .winner-cta { display: inline-flex; align-items: center; justify-content: center; gap: 6px; margin-top: 10px; background: var(--mint); color: white; font-weight: 700; font-size: 0.85rem; padding: 11px 22px; border-radius: 999px; }
}
.hero-product-image { width: 100%; height: auto; aspect-ratio: 1 / 1; margin: 0 auto; border-radius: 18px; background: var(--mist); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; padding: 10px; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 2.4rem; color: var(--blue); }
.hero-product-image img { width: 100%; height: 100%; object-fit: contain; }
@media (min-width: 640px) { .hero-product-image { border-radius: 20px; font-size: 2.6rem; } }
@media (min-width: 860px) { .hero-product-image { width: 100%; height: 100%; aspect-ratio: auto; margin: 0; font-size: 3rem; } }
.hero-product-image.has-photo { background: transparent; border: none; padding: 6px; }
.hero-product-image.has-photo img { object-fit: contain; }
@media (min-width: 1024px) { .wrap-product { max-width: 1280px; } }
.hero-card .product-ai-summary { background: var(--blue-tint); border-left: none; border-radius: 10px; margin: 16px 0 0; }
"""


def _larger_feed_image(url: str) -> str:
    """Feedbildene er små miniatyrer (Lensway w_170, Apotekhjem _400) som blir
    uskarpe i den store hero-ruten. Begge kildene serverer større varianter av
    samme bilde via en størrelse i URL-en; andre kilder returneres uendret."""
    if "lwg-res.cloudinary.com" in url:
        return url.replace(",w_170,", ",w_600,")
    if "apotekhjem.no/images/thumbs/" in url and url.endswith("_400.jpg"):
        return url[:-len("_400.jpg")] + "_600.jpg"
    return url


def render_solution_product_page(product: dict, now: datetime | None = None, clickouts: dict | None = None, price_history: list[dict] | None = None) -> str:
    """Linsevæske/øyedråper o.l. -- egen produkttype med annen datamodell enn
    kontaktlinser (size_ml/solution_type/solution_category i stedet for
    category_slug/specs), men samme pris-/tilbudslogikk (reconcile_product,
    _retailer_badge_html osv. er delt kode uendret fra kontaktlinse-sidene)."""
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    # Boksete frakt-vippebryter i prislisteheaderen i stedet for den gamle,
    # enkle prikke-chippen -- samme "samme hero-/quantity-redesign"-runde
    # (2026-09-28) som resten av denne funksjonen.
    ship_chip_html = _ship_chip_boxed_html("ship-chip") if offers else ""
    offers_block, ex_best = render_price_list(offers, product["name"], product["id"], clickouts, show_ship_chip=False, collapse_after=10, product_ship_chip_html=ship_chip_html)
    long_description = product.get("long_description", product.get("description", ""))
    # Se samme begrunnelse i render_product_page -- meta-beskrivelsen skal
    # lede med selve prissammenligningen, ikke produktbeskrivelsen. Antall
    # forhandlere er bevisst utelatt her også (2026-09-05, samme fiks).
    meta_description = (
        f'Vi sammenligner priser på {product["name"]} hos norske nettbutikker. '
        f'Laveste pris akkurat nå er {_fmt_kr(ex_best["price_nok"])} hos {ex_best["retailer"]}.'
    ) if ex_best else long_description[:155]
    cat_slug = product["solution_category"]
    cat = SOLUTION_CATEGORIES[cat_slug]
    base_url_path = f"/{cat_slug}/{product['brand_slug']}/{product['slug']}/"
    image_url = _product_image(product)

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(product["name"])}</strong> hos norske nettbutikker. Fra <strong>{_fmt_kr(ex_best["price_nok"])}</strong> hos {escape(ex_best["retailer"])} (ekskl. frakt). Kontaktlinser.no er en uavhengig sammenligningstjeneste - slå på «Pris inkludert frakt» under for å se totalprisen med frakt. Priser sist bekreftet {_verified_tag(_newest_checked(offers))}.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne akkurat nå. Prisene oppdateres daglig.</p>
</section>"""

    # Samme delte vinner-widget som render_product_page/render_private_label_page
    # -- gir trofé-ikonet, heldekkende klikkbar ramme og antallsvelger også her
    # (samme behandling for alle produkttyper). "flaske"/"flasker" i stedet for
    # standard "eske"/"esker", siden linsevæske/øyedråper selges i flasker, ikke
    # kontaktlinseesker.
    unit_singular = product.get("unit_singular", "flaske")
    unit_plural = product.get("unit_plural", "flasker")
    size_unit = product.get("size_unit", "ml")
    winner_html, qty_html, qty_multi_html = render_winner_widget(ex_best, offers, product["name"], unit_singular=unit_singular, unit_plural=unit_plural, product_id=product["id"], clickouts=clickouts, qty_choices=(1, 2, 4, 6, 8, 10), include_custom_pill=False, qty_multi_inline=False)
    # Price Intelligence -- delt med kontaktlinse-produktsiden (Kai,
    # 2026-09-28: "gjelder alle produkter på domenet kontaktlinser.no"),
    # samme funksjon, samme CSS (nå i SHARED_STYLE, se der).
    price_history_html = render_price_intelligence(price_history or [], product["name"], unit_singular, unit_plural, offers=offers)
    size_ml = product.get("size_ml")
    price_per_unit_html = ""
    if size_ml and ex_best:
        per_100 = ex_best["price_nok"] / size_ml * 100
        price_per_unit_html = f'<p class="price-per-unit">{_fmt_kr(per_100)} per 100 {size_unit}, ved laveste pris (uten frakt)</p>'
    thumb = _img_tag(_larger_feed_image(image_url), product["name"], loading="eager") if image_url \
        else escape(product["brand_label"][:2].upper())

    safety_notice = ""
    if product.get("solution_type") == "peroxide":
        safety_notice = """<div class="safety-notice">
  <strong>Peroksidbasert linsevæske</strong> må nøytraliseres i riktig oppbevaringsetui før linsene settes i øyet igjen -- følg alltid bruksanvisningen. Linser satt direkte i ufortynnet peroksidløsning kan gi alvorlig øyeskade.
</div>"""

    in_stock_offers = [o for o in offers if o["in_stock"]]
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

    date_modified = max((o["checked_at"] for o in in_stock_offers), default=None)
    # BreadcrumbList (samme fiks som render_product_page 2026-09-05) --
    # speiler den synlige brødsmulen (Hjem > kategori > produktnavn, ingen
    # eget merke-nivå her siden linsevæske/øyedråper-sider ikke har det).
    breadcrumb_schema = f'''{{"@type": "BreadcrumbList", "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "{_json_str(cat["label"])}", "item": "{BASE_URL}/{cat_slug}/"}},
    {{"@type": "ListItem", "position": 3, "name": "{_json_str(product["name"])}", "item": "{BASE_URL}{base_url_path}"}}
  ]}}'''
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [{breadcrumb_schema}, {{
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}}{f', "image": "{escape(_abs_url(image_url))}"' if image_url else ""}{f', "dateModified": "{date_modified}"' if date_modified else ""}{offers_schema}
  }}]
}}"""
    schema_json_html = f'<script type="application/ld+json">{schema_json}</script>' if in_stock_offers else ""

    # Samme dynamiske FAQ/Relatert-mønster som render_product_page, tilpasset
    # linsevæske/øyedråper sin datamodell (size_ml i stedet for pakning med
    # linseantall, ingen merkeside/produsentside å lenke til for disse
    # merkene -- se egen kommentar i render_solution_category_page om
    # hvorfor). "Hvor lenge varer" utelates bevisst -- vi har ikke pålitelig
    # data på forbruk per dag for linsevæske/øyedråper.
    product_faq: list[dict] = []
    if best:
        cheapest_product_offer = min(in_stock_offers, key=lambda o: o["price_nok"])
        if cheapest_product_offer["retailer"] != best["retailer"]:
            billigst_svar = (
                f'{cheapest_product_offer["retailer"]} har lavest produktpris: {_fmt_kr(cheapest_product_offer["price_nok"])} uten frakt. '
                f'Regner du med frakt, blir {best["retailer"]} billigst: {_fmt_kr(best["total"])} totalt inkludert frakt.'
            )
        else:
            billigst_svar = (
                f'{best["retailer"]} har lavest pris, både uten og med frakt: {_fmt_kr(best["price_nok"])} uten frakt '
                f'({_fmt_kr(best["total"])} inkludert frakt).'
            )
        product_faq.append({"question": f'Hvor er {product["name"]} billigst?', "answer": billigst_svar})

        laveste_produktpris = min(o["price_nok"] for o in in_stock_offers)
        product_faq.append({
            "question": f'Hva koster {product["name"]}?',
            "answer": f'Laveste produktpris på {product["name"]} er {_fmt_kr(laveste_produktpris)} uten frakt akkurat nå. '
                      f'Totalprisen avhenger av hvilken butikk du velger og fraktkostnaden der.',
        })

    if size_ml:
        product_faq.append({
            "question": f'Hvor mange ml er det i {product["name"]}?',
            "answer": f'{unit_singular.capitalize()}n inneholder {size_ml:.0f} {size_unit}.',
        })

    product_faq.append({
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk daglig. Vi viser butikkens produktpris "
                  "uten frakt og beregner totalpris basert på frakt og antallet du velger.",
    })

    product_faq_html, product_faq_schema = _render_faq_block(product_faq, f'Vanlige spørsmål om {product["name"]}')

    related_links = f'<li><a href="/{cat_slug}/">Alle {escape(cat["label"].lower())}</a></li>'
    related_html = f"""<div class="related">
    <h2>Relatert til {escape(product["name"])}</h2>
    <ul>
    {related_links}
    </ul>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} » Sammenlign og få billigste pris</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}{base_url_path}">
{_og_meta(f'{product["name"]} » Sammenlign og få billigste pris', meta_description, f'{BASE_URL}{base_url_path}', image_url)}
{FONT_LINKS}
{schema_json_html}
{product_faq_schema}
<style>{SHARED_STYLE}
{HERO_IMAGE_STYLE}
{WINNER_WIDGET_STYLE}
{PRICE_LIST_STYLE}
.price-per-unit {{ font-size: 0.85rem; color: var(--muted); margin: 12px 0 0; }}
/* Flaske-/tubebilder er høye og smale: fast kvadratisk rute (som linsebildene)
   på mobil, i stedet for å la bildets egen høyde strekke hele hero-kortet.
   >=860px: HERO_IMAGE_STYLE sin .product-stage-grid setter en fast
   bildehøyde (320px) uansett produkttype, samme som kontaktlinse-
   produktsiden -- ingen egen desktop-overstyring nødvendig her lenger
   (2026-09-28, "samme hero-/quantity-redesign"-runden). */
@media (max-width: 859px) {{ .hero-card-solution .hero-product-image {{ aspect-ratio: 1 / 1; height: auto; }} }}
.safety-notice {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary {{ background: var(--blue-tint); border-left: 4px solid var(--blue); border-radius: 0 10px 10px 0; padding: 14px 18px; margin: 16px 0; font-size: 0.95rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary p {{ margin: 0; }}
.product-ai-summary.fallback {{ background: var(--muted-bg); border-left-color: var(--muted); color: var(--muted); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-product">
  <p class="breadcrumb">
    <a href="/">Hjem</a> ›
    <a href="/{cat_slug}/">{escape(cat["label"])}</a> ›
    {escape(product["name"])}
  </p>
  <div class="product-stage">
    <div class="hero-card hero-card-solution">
      <div class="hero-main">
        <div class="hero-copy">
          <div class="hero-kicker">{escape(product["brand_label"])}</div>
          <h1>{escape(product["name"])}</h1>
          <p class="hero-subtitle">Sammenlign priser</p>
        </div>
        <div class="hero-media-row">
          <div class="hero-product-image{' has-photo' if image_url else ''}">{thumb}</div>
          {winner_html}
        </div>
      </div>
    </div>
    {qty_html}
  </div>
  {safety_notice}
  {offers_block}
  {price_history_html}
  {qty_multi_html}
  {PRICE_DISCLOSURE_HTML}
  <p class="disclosure">
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
    forhandler eller et apotek. Rådfør deg med optiker eller øyelege om
    hva som passer for deg og dine kontaktlinser.
  </p>
  <h2>Om {escape(product["name"])}</h2>
  <p>{escape(long_description)}</p>
  {price_per_unit_html}
  {ai_summary_html}
  {product_faq_html}
  {METHODOLOGY_HTML}
  {related_html}
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_solution_category_page(solution_category: str, products: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        rows.append({"product": p, "lowest": lowest})

    rows.sort(key=lambda r: r["lowest"]["price_nok"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        image_url = _product_image(p)
        # Linsevæsker/øyedråper-merker har ALDRI en egen /merke/{{slug}}/-side
        # (den bygges kun for linse-merker i generate_pages.py, bekreftet 0
        # overlapp mellom brand_slug-settene) -- ren tekst, ikke en lenke,
        # for å unngå en 404 her.
        brand_link = f'<div class="product-tile-manufacturer" style="cursor:default;">{escape(p["brand_label"])}</div>'
        return _render_product_tile(
            href=f'/{solution_category}/{p["brand_slug"]}/{p["slug"]}/',
            name=p["name"],
            image_url=image_url,
            fallback_initials=p["brand_label"][:2].upper(),
            category_label=cat["label"],
            secondary_line_html=brand_link,
            lowest=lowest,
            other_count=len(p["offers"]) - 1,
        )

    cat = SOLUTION_CATEGORIES[solution_category]
    product_rows_html = "\n".join(render_row(r) for r in rows)

    schema_items = ",\n      ".join(
        f'''{{"@type": "ListItem", "position": {i+1}, "url": "{BASE_URL}/{solution_category}/{p["brand_slug"]}/{p["slug"]}/", "name": "{escape(p["name"])}"}}'''
        for i, p in enumerate(products)
    )
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "BreadcrumbList", "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
      {{"@type": "ListItem", "position": 2, "name": "{escape(cat["label"])}", "item": "{BASE_URL}/{solution_category}/"}}
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
<title>{escape(cat["title_label"])} – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="{escape(cat.get("meta_description", cat["intro"]))}">
<link rel="canonical" href="{BASE_URL}/{solution_category}/">
{_og_meta(f'{cat["title_label"]} – Sammenlign priser | Kontaktlinser.no', cat["intro"], f'{BASE_URL}/{solution_category}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(cat["label"])}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Tilbehør</div>
      <h1>{escape(cat["label"])}</h1>
      <p>{escape(cat["intro"])}</p>
    </div>
  </div>

  <div class="list-header">
    <h2>{len(products)} produkter</h2>
  </div>

  <div id="product-list" class="product-tile-grid">
    {product_rows_html}
  </div>

  <p class="disclosure">
    Vi sorterer alltid etter lavest pris. Vi kan få provisjon når du handler
    via lenkene på produktsidene, men det påvirker ikke prisen du betaler
    eller rangeringen av produkter eller tilbud. Kontaktlinser.no er en
    uavhengig prissammenligningstjeneste, ikke en forhandler.
  </p>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_private_label_brand_page(chain: str, labels: list[dict], products_by_id: dict, categories: dict, now: datetime | None = None, price_history: dict | None = None) -> str:
    """Egen 'merke'-side for en optikerkjedes private label-serie (f.eks.
    /merke/eyeq/ for Synsam sin EyeQ-serie) -- samme URL-mønster og
    kortstil som render_brand_page(), men kildedata er private_labels.json
    + de ekte produktenes tilbud (ingen egen prisdata her heller, se
    render_private_label_page()).

    2026-09-29: løftet til SAMME struktur som render_brand_page() (Kai:
    "Ønsker likt som alle andre merker") -- stat-stripe i heroen,
    "{subbrand} i tall", ekte prisinnsikt-graf (gjenbruker
    _family_price_insight_data()/render_family_price_insight() PÅ TVERS av
    alle variantene, akkurat som merke-siden gjør på tvers av et merkets
    produkter), "{subbrand}-sortimentet forklart" per kategori, en
    materialer-seksjon, "30 eller 90 linser?", FAQ-regelmotor og
    ressurs-/tillit-bunn -- alt via den delte `BRAND_PAGE_STYLE`-konstanten
    (flyttet ut av render_brand_page() sin egen <style>-blokk i samme
    runde, nøyaktig samme CSS, ingen duplisering).

    BEVISST UTELATT (adaptivt, samme prinsipp som et ekte merke uten egen
    serie i render_brand_page()): "Utforsk seriene"-kortene og
    "Slik skiller seriene seg"-tabellen, siden private label-varianter ikke
    har noen egen product_families.json-gruppering (hver variant er en
    1:1-alias for ett ekte produkt, ikke en flerpakning/flervariant-serie
    i seg selv) -- family_summaries er derfor alltid tom liste her, og de
    to seksjonene som avhenger av den faller naturlig bort, akkurat som de
    allerede gjør for et ekte merke uten kuratert familie (f.eks.
    FreshLook). Heller ingen egen "Produsent"-modul, siden ett sett private
    label-varianter typisk spenner FLERE produsenter (EyeQ blander
    CooperVision og Alcon, se CLAUDE.md) -- ingen enkelt produsent å lenke
    til.

    Kai, eksplisitt: "vi beholder også i tillegg under toppbanneren" --
    `.private-label-explainer`-boksen ("Hva er {subbrand}?") ligger derfor
    UENDRET rett under `.brand-hero`, FØR noen av de nye seksjonene."""
    now = now or datetime.now(timezone.utc)
    subbrand = PRIVATE_LABEL_SUBBRANDS.get(chain, chain)
    slug = subbrand.lower()

    rows = []
    for label in labels:
        real_product = products_by_id.get(label["real_product_id"])
        if real_product is None:
            continue
        offers = reconcile_product(real_product["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        specs = {spec_label: value for spec_label, value in real_product.get("specs", [])}
        pack = _pack_size_from_id(real_product["id"])
        category_slug = real_product.get("category_slug", "")
        rows.append({
            "label": label, "real_product": real_product, "lowest": lowest, "eligible": eligible,
            "category_label": categories.get(category_slug, {}).get("label", ""),
            "material": specs.get("Materiale"), "pack_size": pack[1] if pack else None,
            # Syntetisk "product"-dict -- lar oss gjenbruke generiske
            # hjelpefunksjoner (_family_price_insight_data, _pack_size_from_id)
            # som forventer product["id"]/product["category_slug"] uten å late
            # som label selv er et ekte katalogprodukt. id er BEVISST
            # real_product sin -- samme fysiske vare, samme prishistorikk.
            "product": {"id": real_product["id"], "name": label["name"], "category_slug": category_slug},
        })

    rows.sort(key=lambda r: r["lowest"]["price_nok"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        # Viser ALDRI det ekte produktets bilde her -- det er en annen fysisk
        # innpakning (private label-eskens design er ukjent for oss), så et
        # lånt Proclear/Biofinity-bilde under Ascend-navnet ville villedet
        # brukeren til å tro det er slik den faktiske esken ser ut. Samme
        # initial-fallback som brukes når vi ikke har NOE bilde i det hele tatt.
        label, real_product, lowest = r["label"], r["real_product"], r["lowest"]
        real_href = f'/kontaktlinser/{real_product["brand_slug"]}/{real_product["slug"]}/'
        real_product_link = f'<a class="product-tile-manufacturer" href="{escape(real_href)}">= {escape(real_product["name"])}</a>'
        category_slug = real_product.get("category_slug", "")
        return _render_product_tile(
            href=f'/private-label/{escape(label["slug"])}/',
            name=label["name"],
            image_url=None,
            fallback_initials=subbrand[:2].upper(),
            category_label=categories.get(category_slug, {}).get("label"),
            secondary_line_html=real_product_link,
            lowest=lowest,
            other_count=len(real_product["offers"]) - 1,
            data_attr=f' data-category="{escape(category_slug)}"',
            illustration_html=render_private_label_illustration(chain, label["slug"]),
        )

    product_rows_html = "\n".join(render_row(r) for r in rows)
    any_pli_illustration = any(render_private_label_illustration(chain, r["label"]["slug"]) for r in rows)

    category_slugs = sorted({r["real_product"]["category_slug"] for r in rows if "category_slug" in r["real_product"]})
    category_chips = "".join(
        f'<button class="chip" data-category="{escape(c)}">{escape(categories[c]["label"])}</button>' for c in category_slugs
    )

    # Kjedens navn/logo (Synsam/Brilleland/Specsavers/Coptikk) vises IKKE
    # lenger her -- bruker ønsker (2026-08-30) at disse seriene fremstår
    # som egne merker på denne siden, på linje med ekte linsemerker. Full
    # kobling til kjeden ligger fortsatt på /private-label/. Bruker seriens
    # EGEN logo (PRIVATE_LABEL_SUBBRAND_LOGOS) når vi har en ekte filbasert
    # en, ellers iWear sitt midlertidige tekst-ordmerke (brukerens egen fil
    # sier selv "ikke offisiell iWear-logo") for akkurat den serien, ellers
    # en initial-badge (Lumiere7 -- ingen fil ennå).
    subbrand_logo = PRIVATE_LABEL_SUBBRAND_LOGOS.get(subbrand)
    if subbrand_logo:
        brand_logo_cls = "has-logo"
        brand_logo_content = f'<img class="brand-logo-img" src="/static/logos/{subbrand_logo}" alt="" loading="lazy">'
    elif subbrand == "iWear":
        brand_logo_cls = "has-logo"
        brand_logo_content = ('<span style="font-family:\'Space Grotesk\',sans-serif;font-weight:700;'
                               'font-size:1.9rem;letter-spacing:-.03em;color:var(--ink);">'
                               '<span style="color:#078e91;">i</span>Wear</span>')
    else:
        brand_logo_cls, brand_logo_content = "", escape(subbrand[:2].upper())
    brand_logo_block = f'<div class="brand-hero-logo {brand_logo_cls}">{brand_logo_content}</div>'

    meta_description = f"{subbrand} er et eget merkenavn for kontaktlinser. Sammenlign priser på alle {len(rows)} {subbrand}-varianter vi har identifisert – de er identiske med kjente linser fra store produsenter, bare i egen innpakning."

    # -- Tall på tvers av HELE settet, brukt av stat-stripen, "i tall" og
    # FAQ-en -- samme utregningsmønster som render_brand_page(). --
    all_eligible = [o for r in rows for o in r["eligible"]]
    retailer_count = len({o["retailer"] for o in all_eligible})
    type_labels_all = sorted({r["category_label"] for r in rows if r["category_label"]})
    materials_all = sorted({r["material"] for r in rows if r["material"]})
    # Ekte merker-listen finnes IKKE på et ekte merke -- egen, ny
    # informasjon som bare private label-siden kan vise (hvilke reelle
    # produsent-merker settet faktisk består av).
    real_brands_all = sorted({r["real_product"]["brand_label"] for r in rows if r["real_product"].get("brand_label")})
    lowest_row = min((r for r in rows if r["lowest"]), key=lambda r: r["lowest"]["price_nok"], default=None)
    per_lens_rows = [
        (r["lowest"]["price_nok"] / r["pack_size"], r) for r in rows if r["lowest"] and r["pack_size"]
    ]
    cheapest_per_lens = min(per_lens_rows, key=lambda t: t[0], default=None)

    type_labels_lower = [t[0].lower() + t[1:] if t else t for t in type_labels_all]
    if len(type_labels_lower) <= 1:
        brand_type_txt = type_labels_lower[0] if type_labels_lower else ""
    else:
        brand_type_txt = ", ".join(type_labels_lower[:-1]) + " og " + type_labels_lower[-1]
    brand_subtitle_html = f'<p class="brand-hero-subtitle">Eget merkenavn hos {escape(chain)}</p>'
    brand_intro_sentence = (
        f'{escape(subbrand)} er {escape(chain)} sitt eget merkenavn for kontaktlinser'
        + (f', med {escape(brand_type_txt)}' if brand_type_txt else '')
        + f'. Vi følger prisen på {len(rows)} {"variant" if len(rows) == 1 else "varianter"}, sortert etter lavest pris.'
    )

    store_icon = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9l1-5h14l1 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M4 9h16M9.5 20v-5.5h5V20"/></svg>'
    stat_pills = [("mint", BOX_ICON_SVG, str(len(rows)), "produkt" if len(rows) == 1 else "produkter", "")]
    if real_brands_all:
        stat_pills.append(("blue", TAG_ICON_SVG, str(len(real_brands_all)), "ekte merke" if len(real_brands_all) == 1 else "ekte merker", " · ".join(real_brands_all)))
    if type_labels_all:
        stat_pills.append(("lavender", DROPLET_ICON_SVG, str(len(type_labels_all)), "linsetype" if len(type_labels_all) == 1 else "linsetyper", " · ".join(type_labels_all)))
    if retailer_count:
        stat_pills.append(("amber", store_icon, str(retailer_count), "butikk" if retailer_count == 1 else "butikker", f'Med {subbrand}-produkter akkurat nå'))
    brand_hero_stats_html = "".join(
        f'''<div class="brand-hero-stat">
    <span class="brand-hero-stat-icon" style="color:var(--{color});" aria-hidden="true">{icon}</span>
    <span class="brand-hero-stat-value">{escape(number)}</span>
    <span class="brand-hero-stat-label">{escape(unit)}</span>
  </div>'''
        for color, icon, number, unit, sub in stat_pills
    )

    # -- "{subbrand} i tall" -- samme mønster som render_brand_page(), men
    # uten "flest varianter"-tile (den krever en product_families-serie vi
    # ikke bygger her, se docstring). --
    brand_i_tall_tiles = []
    if lowest_row and lowest_row["lowest"]:
        brand_i_tall_tiles.append(("mint", TROPHY_ICON_SVG, _fmt_kr(lowest_row["lowest"]["price_nok"]), "Laveste produktpris", lowest_row["label"]["name"]))
    if cheapest_per_lens:
        per_lens_val, per_lens_row = cheapest_per_lens
        per_lens_txt = f'{per_lens_val:.1f}'.replace(".", ",") + " kr"
        brand_i_tall_tiles.append(("amber", BOX_ICON_SVG, per_lens_txt, "Laveste pris per linse", per_lens_row["label"]["name"]))
    spread_candidates = []
    for r in rows:
        if len(r["eligible"]) >= 2:
            prices = [o["price_nok"] for o in r["eligible"]]
            lo, hi = min(prices), max(prices)
            if lo > 0:
                spread_candidates.append((round((hi - lo) / lo * 100), r))
    biggest_spread = max(spread_candidates, key=lambda t: t[0], default=None)
    if biggest_spread and biggest_spread[0] >= 5:
        brand_i_tall_tiles.append(("sky", TAG_ICON_SVG, f'{biggest_spread[0]} %', "Størst prisforskjell mellom butikker", biggest_spread[1]["label"]["name"]))
    most_retailers_row = max(rows, key=lambda r: len(r["eligible"]), default=None)
    if most_retailers_row and len(most_retailers_row["eligible"]) >= 2:
        brand_i_tall_tiles.append(("lavender", store_icon, str(len(most_retailers_row["eligible"])), "Flest butikker", most_retailers_row["label"]["name"]))
    brand_i_tall_html = ""
    if brand_i_tall_tiles:
        brand_i_tall_html = f'''<div class="brand-i-tall">
    <h2>{escape(subbrand)} i tall</h2>
    <p class="brand-section-lead">Basert på produktene og prisene vi følger akkurat nå.</p>
    <div class="brand-i-tall-grid">
      {"".join(f'<div class="brand-i-tall-tile"><div class="brand-i-tall-icon" style="background:var(--{color}-tint);color:var(--{color});" aria-hidden="true">{icon}</div><div class="brand-i-tall-value">{escape(val)}</div><div class="brand-i-tall-label">{escape(lbl)}</div><div class="brand-i-tall-sub">{escape(sub)}</div></div>' for color, icon, val, lbl, sub in brand_i_tall_tiles)}
    </div>
  </div>'''

    # -- Prisinnsikt for HELE settet (snitt per pakningsstørrelse, PÅ TVERS
    # av alle variantene) -- gjenbruker EKSAKT samme funksjoner som
    # serie-/merke-siden, se _family_price_insight_data(). Historikken er
    # lagret på real_product["id"] (samme fysiske vare), se rows-bygget over. --
    brand_price_insight_html = ""
    if price_history:
        brand_insight_by_pack = _family_price_insight_data(rows, price_history)
        brand_price_insight_html = render_family_price_insight(subbrand, brand_insight_by_pack, scope_label=f"i {subbrand}-sortimentet", heading=f"{subbrand}-priser")

    brand_insight_row_html = (
        f'<div class="brand-insight-row">{brand_i_tall_html}{brand_price_insight_html}</div>'
        if brand_i_tall_html and brand_price_insight_html else brand_i_tall_html + brand_price_insight_html
    )

    # -- "Materialer" -- de dokumenterte materialene til de EKTE produktene
    # settet tilsvarer. Ingen "brukes i serie X"-undertekst (ingen
    # familie-gruppering her, se docstring) -- rene, informative kort. --
    material_colors = ["sky", "mint", "lavender", "amber", "coral"]

    def brand_material_card(m: str, i: int) -> str:
        color = material_colors[i % len(material_colors)]
        return f'''<div class="brand-material-card">
    <div class="brand-material-card-icon" style="background:var(--{color}-tint);color:var(--{color});" aria-hidden="true">{DROPLET_ICON_SVG}</div>
    <div class="brand-material-card-body">
      <div class="brand-material-card-name">{escape(m)}</div>
    </div>
  </div>'''

    brand_materials_html = ""
    if len(materials_all) >= 2:
        brand_materials_html = f'''<div><h2>Materialer i {escape(subbrand)}-sortimentet</h2>
  <p class="brand-section-lead">De dokumenterte materialene de ekte linsene {escape(subbrand)} tilsvarer er laget av.</p>
  <div class="brand-materials-grid">
    {"".join(brand_material_card(m, i) for i, m in enumerate(materials_all))}
  </div></div>'''

    # -- "30 eller 90 linser?" -- samme robusthet-terskel (minst 2 par) som
    # render_brand_page(), matchet via real_product["id"] (product["id"]
    # i rows-bygget over er bevisst real_product sin, se der). --
    pack_pairs = []
    by_stem: dict[str, dict[int, dict]] = {}
    for r in rows:
        parsed = _pack_size_from_id(r["product"]["id"])
        if parsed and r["lowest"]:
            stem, pack = parsed
            by_stem.setdefault(stem, {})[pack] = r
    for stem, by_pack in by_stem.items():
        if 30 in by_pack and 90 in by_pack:
            r30, r90 = by_pack[30], by_pack[90]
            p30 = r30["lowest"]["price_nok"] / 30
            p90 = r90["lowest"]["price_nok"] / 90
            pack_pairs.append({"name": r30["label"]["name"], "p30": p30, "p90": p90})
    pack_30_90_html = ""
    if len(pack_pairs) >= 2:
        n_90_cheaper = sum(1 for pp in pack_pairs if pp["p90"] < pp["p30"])
        best_example = max(pack_pairs, key=lambda pp: abs(pp["p30"] - pp["p90"]))
        p30_txt = f'{best_example["p30"]:.1f}'.replace(".", ",")
        p90_txt = f'{best_example["p90"]:.1f}'.replace(".", ",")
        diff_pct = round(abs(best_example["p30"] - best_example["p90"]) / best_example["p30"] * 100)
        cheaper_word = "90-pakningen" if best_example["p90"] < best_example["p30"] else "30-pakningen"
        pack_30_90_html = f'''<h2>30 eller 90 linser?</h2>
  <div class="brand-3090-card">
    <p>For {n_90_cheaper} av {len(pack_pairs)} sammenlignbare {escape(subbrand)}-produkter har 90-pakningen lavere pris per linse enn tilsvarende 30-pakning akkurat nå. Eksempel -- {escape(best_example["name"])}:</p>
    <div class="brand-3090-grid">
      <div class="brand-3090-tile"><div class="brand-3090-tile-icon" style="background:var(--sky-tint);color:var(--sky);" aria-hidden="true">{BOX_ICON_SVG}</div><strong>{p30_txt} kr</strong><span>30-pack, per linse</span></div>
      <div class="brand-3090-tile"><div class="brand-3090-tile-icon" style="background:var(--mint-tint);color:var(--mint);" aria-hidden="true">{BOX_ICON_SVG}</div><strong>{p90_txt} kr</strong><span>90-pack, per linse</span></div>
      <div class="brand-3090-tile"><div class="brand-3090-tile-icon" style="background:var(--amber-tint);color:var(--amber);" aria-hidden="true">{TAG_ICON_SVG}</div><strong>{diff_pct} %</strong><span>Forskjell -- {escape(cheaper_word)} billigst</span></div>
    </div>
    <p class="brand-3090-note">Kun samme underliggende produkt sammenlignet (aldri ulike produkter mot hverandre). Husk å regne med frakt for akkurat det antallet du trenger.</p>
  </div>'''

    # -- "{subbrand}-sortimentet forklart" -- én kortoversikt per KATEGORI,
    # samme mønster som render_brand_page(), men uten "series_names"
    # (ingen familie-gruppering her). --
    sortiment_cards = []
    for cat_slug in category_slugs:
        cat_rows = [r for r in rows if r["product"]["category_slug"] == cat_slug]
        if not cat_rows:
            continue
        sortiment_cards.append({
            "label": categories.get(cat_slug, {}).get("label", cat_slug),
            "slug": cat_slug,
            "count": len(cat_rows),
        })
    sortiment_html = ""
    if len(sortiment_cards) > 1:
        eye_icon = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>'
        person_icon = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="12" cy="8" r="3.5" fill="currentColor"/><path d="M5 20c0-4 3-6.5 7-6.5s7 2.5 7 6.5" fill="currentColor" opacity="0.5"/></svg>'
        category_icon_map = {
            "dagslinser": ("amber", SUN_ICON_SVG), "manedslinser": ("sky", CALENDAR_ICON_SVG),
            "toriske-linser": ("coral", eye_icon), "multifokale-linser": ("lavender", person_icon),
            "fargede-linser": ("mint", DROPLET_ICON_SVG),
        }

        def sortiment_card(c: dict) -> str:
            color, icon = category_icon_map.get(c["slug"], ("blue", TAG_ICON_SVG))
            return f'''<a class="brand-sortiment-card" href="#{escape(c["slug"])}" data-category="{escape(c["slug"])}">
    <div class="brand-sortiment-card-icon" style="background:var(--{color}-tint);color:var(--{color});" aria-hidden="true">{icon}</div>
    <div class="brand-sortiment-card-label">{escape(c["label"])}</div>
    <div class="brand-sortiment-card-count">{c["count"]} {"produkt" if c["count"] == 1 else "produkter"}</div>
    <div class="brand-sortiment-card-link">Se {escape(c["label"].lower())} →</div>
  </a>'''
        sortiment_html = f'''<h2>{escape(subbrand)}-sortimentet forklart</h2>
  <p class="brand-section-lead">{len(sortiment_cards)} kategorier med til sammen {len(rows)} produkter -- velg den som passer ditt behov.</p>
  <div class="brand-sortiment-grid">
    {"".join(sortiment_card(c) for c in sortiment_cards)}
  </div>'''

    # -- FAQ-regelmotor (samme komponent som serie-/merke-siden, se
    # _render_family_faq_accordion()). --
    faq_produkt: list[dict] = []
    if real_brands_all:
        faq_produkt.append({
            "question": f'Hvilke ekte merker er {subbrand} egentlig?',
            "answer": f'{subbrand}-produktene vi følger tilsvarer disse ekte merkene: {", ".join(real_brands_all)}. Se produktkortene under for hvilket ekte produkt hver enkelt {subbrand}-variant er identisk med.',
        })
    if "toriske-linser" in category_slugs:
        faq_produkt.append({
            "question": f'Finnes {subbrand} for astigmatisme?',
            "answer": f'Ja, {subbrand} har varianter for astigmatisme. Se produktene under for hvilke.',
        })
    if "multifokale-linser" in category_slugs:
        faq_produkt.append({
            "question": f'Finnes {subbrand} som multifokale linser?',
            "answer": f'Ja, {subbrand} har multifokale varianter for alderssyn (presbyopi). Se produktene under for hvilke.',
        })
    if "dagslinser" in category_slugs and "manedslinser" in category_slugs:
        faq_produkt.append({
            "question": f'Har {subbrand} både dagslinser og månedslinser?',
            "answer": f'Ja, {subbrand}-sortimentet vårt dekker både dagslinser (kastes hver dag) og månedslinser (gjenbrukes med rengjøring).',
        })
    faq_spec: list[dict] = []
    if materials_all:
        faq_spec.append({
            "question": f'Hvilke materialer brukes i linsene {subbrand} tilsvarer?',
            "answer": f'De ekte linsene {subbrand}-produktene vi følger tilsvarer, er laget av {", ".join(materials_all)}. Materialet varierer mellom variantene.' if len(materials_all) > 1
                      else f'De ekte linsene {subbrand}-produktene vi følger tilsvarer, er laget av {materials_all[0]}.',
        })
    faq_pris: list[dict] = []
    if lowest_row and lowest_row["lowest"]:
        faq_pris.append({
            "question": f'Hva er billigst i {subbrand}-sortimentet?',
            "answer": f'{lowest_row["label"]["name"]} er billigst akkurat nå, fra {_fmt_kr(lowest_row["lowest"]["price_nok"])} hos {lowest_row["lowest"]["retailer"]} (uten frakt).',
        })
    if cheapest_per_lens:
        per_lens_val, per_lens_row = cheapest_per_lens
        per_lens_txt = f'{per_lens_val:.1f}'.replace(".", ",")
        faq_pris.append({
            "question": f'Hvilken {subbrand}-pakning har lavest pris per linse akkurat nå?',
            "answer": f'{per_lens_row["label"]["name"]} har lavest pris per linse akkurat nå, ca. {per_lens_txt} kr per linse (uten frakt).',
        })
    if retailer_count:
        faq_pris.append({
            "question": f'Hos hvor mange butikker kan jeg sammenligne {subbrand}?',
            "answer": f'Vi sammenligner {subbrand} hos {retailer_count} norske nettbutikker til sammen, på tvers av alle {len(rows)} variantene vi følger.',
        })
    brand_faq_html, brand_faq_schema = _render_family_faq_accordion(
        [("Merke og varianter", faq_produkt), ("Spesifikasjoner", faq_spec), ("Pris og butikker", faq_pris)],
        f'Ofte stilte spørsmål om {subbrand}',
    )

    # -- "Nyttige ressurser" -- samme gjenbruk av render_guide_tile() som
    # render_brand_page(). --
    brand_guide_slugs = ["hvordan-velge-kontaktlinser"]
    if "dagslinser" in category_slugs and "manedslinser" in category_slugs:
        brand_guide_slugs.append("manedslinser-vs-dagslinser")
    elif "toriske-linser" in category_slugs:
        brand_guide_slugs.append("kontaktlinser-med-astigmatisme")
    elif "multifokale-linser" in category_slugs:
        brand_guide_slugs.append("multifokale-kontaktlinser")
    else:
        brand_guide_slugs.append("hvordan-bruke-kontaktlinser")
    brand_guide_slugs.append("bc-forklart")
    brand_guides_html = f'''<h2>Nyttige ressurser</h2>
  <p class="brand-section-lead">Artikler, forklaringer og guider som hjelper deg å ta gode valg.</p>
  <div class="guide-grid">
    {"".join(render_guide_tile(gslug, GUIDE_CONTENT[gslug]) for gslug in brand_guide_slugs if gslug in GUIDE_CONTENT)}
  </div>'''

    # -- "Om informasjonen på denne siden" -- identisk tekst/lenker som
    # render_brand_page() sin trust-footer, ingen nye påstander. --
    brand_trust_html = f'''<div class="brand-trust">
    <h2>Om informasjonen på denne siden</h2>
    <div class="brand-trust-grid">
      <div class="brand-trust-item"><strong>Produktinformasjon</strong><p>Basert på dokumenterte produsentspesifikasjoner og vår produktdatabase.</p></div>
      <div class="brand-trust-item"><strong>Priser</strong><p>Hentes fra norske nettbutikker og oppdateres daglig.</p></div>
      <div class="brand-trust-item"><strong>Kommersielle lenker</strong><p>Vi kan motta provisjon når du går videre til en butikk. Dette påvirker aldri prisrekkefølgen.</p></div>
      <div class="brand-trust-item"><strong>Sammenligning</strong><p>Pris per linse beregnes fra pakningsstørrelse. Totalpris inkluderer frakt der fraktdata er tilgjengelig.</p></div>
    </div>
    <p class="brand-trust-links">
      <a href="/slik-sammenligner-vi-priser/">Slik sammenligner vi priser →</a>
      <a href="/slik-matcher-vi-produkter/">Slik matcher vi produkter →</a>
      <a href="/om-oss/">Om Kontaktlinser.no →</a>
    </p>
  </div>'''

    schema_items = ",\n      ".join(
        f'''{{"@type": "ListItem", "position": {i+1}, "url": "{BASE_URL}/private-label/{r["label"]["slug"]}/", "name": "{escape(r["label"]["name"])}"}}'''
        for i, r in enumerate(rows)
    )
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "BreadcrumbList", "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
      {{"@type": "ListItem", "position": 2, "name": "{escape(subbrand)}", "item": "{BASE_URL}/merke/{slug}/"}}
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
<title>{escape(subbrand)} kontaktlinser – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/merke/{slug}/">
{_og_meta(f'{subbrand} kontaktlinser – Sammenlign priser | Kontaktlinser.no', meta_description, f'{BASE_URL}/merke/{slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
{brand_faq_schema}
<style>{SHARED_STYLE}
{GUIDE_TILE_STYLE}
{BRAND_PAGE_STYLE}
{PRIVATE_LABEL_ILLUSTRATION_STYLE}
.private-label-explainer {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin: 20px 0; font-size: 0.92rem; line-height: 1.6; }}
.private-label-explainer strong {{ color: var(--ink); }}
.private-label-caveat {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(subbrand)}</p>
  <div class="brand-hero">
    <div class="brand-hero-content">
      <div class="brand-hero-row">
        {brand_logo_block}
        <div class="hero-copy">
          <div class="kicker">Eget merkenavn</div>
          <h1>{escape(subbrand)} kontaktlinser</h1>
          {brand_subtitle_html}
          <p>{brand_intro_sentence}</p>
          <div class="brand-hero-cta-row">
            <a class="brand-hero-cta" href="#produkter">Se alle {escape(subbrand)}-produkter →</a>
          </div>
        </div>
      </div>
    </div>
    <div class="brand-hero-media" aria-hidden="true">
      <picture>
        <source media="(min-width: 860px)" type="image/webp" srcset="/static/hero/brand-560.webp 560w, /static/hero/brand-840.webp 840w, /static/hero/brand-1120.webp 1120w" sizes="(min-width: 1200px) 560px, 40vw">
        <img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" alt="" width="560" height="385" loading="lazy" decoding="async">
      </picture>
    </div>
    <div class="brand-hero-stats">{brand_hero_stats_html}</div>
  </div>

  <div class="private-label-explainer">
    <p><strong>Hva er {escape(subbrand)}?</strong> {escape(subbrand)} er et eget varenavn for kontaktlinser, i stedet for produsentens opprinnelige navn. Det er ikke en egen linseprodusent – hver {escape(subbrand)}-linse er identisk med en kjent linse fra en av de store produsentene, bare med egen emballasje og navn. Prisene under er hentet fra det ekte produktet, siden det er nøyaktig samme fysiske vare. Se <a href="/private-label/">oversikten over optikerkjedenes egne merker</a> for hvilken kjede som står bak.</p>
  </div>

  {brand_insight_row_html}

  <h2 id="produkter">Alle {escape(subbrand)}-produkter</h2>
  <div class="filter-row" id="filter-row" role="group" aria-label="Filtrer etter kategori">
    <button class="chip active" data-category="all">Alle kategorier</button>
    {category_chips}
  </div>

  <div class="list-header">
    <h2 id="result-count">{len(rows)} produkter</h2>
  </div>

  <div id="product-list" class="product-tile-grid">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>
  {'<p style="margin:10px 0 0;font-size:0.78rem;color:var(--muted);">Noen varianter over vises med en egen illustrasjon i stedet for et ekte produktbilde. <a href="/om-produktillustrasjoner/" style="color:var(--muted);text-decoration:underline;">Les hvorfor →</a></p>' if any_pli_illustration else ''}

  {sortiment_html}
  {brand_materials_html}
  {pack_30_90_html}
  <div class="brand-faq-wrap">{brand_faq_html}</div>
  {brand_guides_html}

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Koblingene over er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale med kjeden bak dette merkenavnet og kan ikke garantere at hver kobling stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept før du bytter mellom disse navnene.
  </div>

  <p style="margin-top:16px;"><a href="/private-label/" style="color:var(--blue);font-weight:600;text-decoration:none;">Se optikerkjedenes andre egne merker →</a></p>

  <p class="disclosure">
    Prisene her er produktpriser uten frakt, sortert etter lavest pris. På hver
    produktside kan du slå på «Pris inkludert frakt» for å se totalprisen. Vi kan få
    provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på pris, bortsett fra ved
    eksakt lik pris mellom to tilbud, der vi kan prioritere en forhandler vi
    har avtale med. Kontaktlinser.no er en uavhengig
    prissammenligningstjeneste, ikke en forhandler.
  </p>

  {brand_trust_html}
</div>

<script>
  const filterRow = document.getElementById('filter-row');
  const list = document.getElementById('product-list');

  function applyBrandFilter(category) {{
    const btn = filterRow.querySelector('.chip[data-category="' + category + '"]');
    if (!btn) return;
    filterRow.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    let visible = 0;
    list.querySelectorAll('.product-tile').forEach(card => {{
      const show = category === 'all' || card.dataset.category === category;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
  }}

  const initialCategory = window.location.hash.replace('#', '');
  if (initialCategory && filterRow.querySelector('.chip[data-category="' + initialCategory + '"]')) {{
    applyBrandFilter(initialCategory);
  }}
  document.querySelectorAll('.brand-sortiment-card').forEach(card => {{
    card.addEventListener('click', () => {{
      applyBrandFilter(card.dataset.category);
      document.getElementById('produkter').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }});
  }});

  filterRow.addEventListener('click', e => {{
    const btn = e.target.closest('.chip');
    if (!btn) return;
    applyBrandFilter(btn.dataset.category);
  }});
</script>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""

def render_private_label_page(label: dict, real_product: dict, categories: dict, now: datetime | None = None, family: dict | None = None, clickouts: dict | None = None, price_history: list[dict] | None = None) -> str:
    """En del optikerkjeder pakker om ekte kontaktlinser under sitt eget
    merkenavn (f.eks. Synsam sin "EyeQ 24" er egentlig Biofinity fra
    CooperVision). private_labels.json holder KUN høy-sikkerhet-koblinger,
    bekreftet direkte mot en uavhengig kilde (Lensway sin egen
    "optikerkjedenes varemerke"-seksjon, som eksplisitt oppgir hvilket
    produsent-navn hver private label-linse selges under). Denne siden
    viser IKKE egen pris/tilbudsdata -- den gjenbruker real_product sine
    faktiske tilbud, siden det er nøyaktig samme fysiske vare."""
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(real_product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    ship_chip_html = _ship_chip_boxed_html("ship-chip") if offers else ""
    offers_block, ex_best = render_price_list(offers, real_product["name"], real_product["id"], clickouts,
                                              title=f"Sammenlign priser på {real_product['name']}",
                                              show_ship_chip=False, collapse_after=10, product_ship_chip_html=ship_chip_html)

    in_stock_offers = [o for o in offers if o["in_stock"]]
    about_offers_schema = ""
    if in_stock_offers:
        schema_offers = ",\n        ".join(f'''{{
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
        low_price = min(o["price_nok"] for o in in_stock_offers)
        high_price = max(o["price_nok"] for o in in_stock_offers)
        about_offers_schema = f''', "offers": {{
      "@type": "AggregateOffer",
      "priceCurrency": "NOK",
      "lowPrice": {low_price},
      "highPrice": {high_price},
      "offerCount": {len(in_stock_offers)},
      "offers": [{schema_offers}]
    }}'''

    real_name = real_product["name"]
    real_brand = real_product["brand_label"]
    chain = label["chain"]
    private_name = label["name"]
    real_href = f'/kontaktlinser/{real_product["brand_slug"]}/{real_product["slug"]}/'
    category_label = categories[real_product["category_slug"]]["label"]

    winner_html, qty_html, qty_multi_html = render_winner_widget(ex_best, offers, real_product["name"], product_id=real_product["id"], clickouts=clickouts, qty_choices=(1, 2, 4, 6, 8, 10), include_custom_pill=False, qty_multi_inline=False)
    # Price Intelligence -- delt med kontaktlinse-/linsevæske-produktsidene
    # (Kai, 2026-09-28: "gjelder alle produkter på domenet
    # kontaktlinser.no ... egne merkenavn kontaktlinser"). Historikken er
    # lagret på real_product sin id (samme fysiske vare, se docstring),
    # ikke på selve private label-etiketten.
    price_history_html = render_price_intelligence(price_history or [], real_product["name"], offers=offers)

    # Samme prinsipp som render_product_page/render_solution_product_page --
    # meta-beskrivelsen skal inneholde en live pris, ikke bare den generiske
    # "sammenlign priser"-teksten. Identitetsfakta (hva den egentlig heter)
    # beholdes først, siden det er selve grunnen til at denne siden finnes
    # (ellers dupliserer den bare real_product sin egen side). Bruker
    # PRODUSENTEN (f.eks. CooperVision), ikke real_brand (f.eks. "Biofinity")
    # -- real_name inneholder allerede merkenavnet ("Biofinity 6-pack"), så
    # "... er samme linse som Biofinity 6-pack fra Biofinity" var en
    # gjentakelse. Faller tilbake til real_brand kun for de sjeldne
    # merkene uten produsent-kobling i BRAND_TO_MANUFACTURER.
    manufacturer_slug = BRAND_TO_MANUFACTURER.get(real_product["brand_slug"])
    real_source = MANUFACTURERS[manufacturer_slug]["name"] if manufacturer_slug else real_brand
    # Kjedenavnet (Synsam/Brilleland/Specsavers/Coptikk) skal IKKE nevnes på
    # denne siden lenger (bruker-beslutning 2026-08-30) -- den eneste siden
    # som fortsatt nevner kjeder er selve samlesiden /private-label/, som
    # grupperer ALLE seriene til sammenligning. Denne siden (ett enkelt
    # produkt) bruker objektiv ordlegging i stedet og lenker til samlesiden
    # for hvem som faktisk står bak.
    # Pris/salgs-hook FØRST i tittel og meta-beskrivelse, identitets-
    # avsløringen ("er egentlig X") KUN i H1/brødtekst -- brukerbeslutning
    # 2026-09-05: målet med SERP-teksten er å få folk til å klikke, ikke å
    # svare på spørsmålet før de i det hele tatt er inne på siden. Forrige
    # variant ("Hva heter den egentlig?") var riktignok ikke en avsløring i
    # seg selv, men Google erstattet den likevel ofte med H1-en (som ER en
    # avsløring) i søketreff -- trolig fordi samme tittelmal gikk igjen
    # identisk på alle 64 private label-sidene. Denne nye teksten er
    # prisdrevet, samme stil som render_product_page allerede bruker
    # ("» Sammenlign og få billigste pris"), for konsistens på tvers av
    # siden og fordi det er en allerede etablert, fungerende ramme.
    meta_description = (
        f'Se laveste pris på {private_name} blant norske nettbutikker – fra '
        f'{_fmt_kr(ex_best["price_nok"])} hos {ex_best["retailer"]}. Oppdatert daglig.'
    ) if ex_best else f'Sammenlign priser på {private_name} blant norske nettbutikker.'

    # Synlig, CRAWLBAR tekst med de samme fakta som SERP-teksten over
    # (pris/antall butikker/oppdateringsfrekvens) -- Google genererer ofte
    # selve snippeten fra INNHOLDET på siden, ikke meta-beskrivelsen (kun
    # brukt når Google selv mener den passer bedre), så disse fakta bør stå
    # som ekte tekst her også, ikke bare i en meta-tag. Samme mønster som
    # .product-ai-summary på render_product_page/render_solution_product_
    # page (lagt til her 2026-09-05 -- private label-sidene manglet denne
    # boksen helt).
    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(real_name)}</strong> (solgt som {escape(private_name)} hos denne kjeden) hos norske nettbutikker. Laveste pris akkurat nå er <strong>{_fmt_kr(ex_best["price_nok"])}</strong> hos {escape(ex_best["retailer"])} (ekskl. frakt). Prisene oppdateres daglig, sist bekreftet {_verified_tag(_newest_checked(offers))}.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(real_name)}</strong> ({escape(private_name)}), men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne linsen akkurat nå. Prisene oppdateres daglig.</p>
</section>"""

    about_type = "Product" if in_stock_offers else "Thing"
    date_modified = max((o["checked_at"] for o in in_stock_offers), default=None)
    # BreadcrumbList manglet her (fantes på kategori-/merke-/produsent-sider,
    # men den tidligere kommentaren om at private label-sider allerede hadde
    # den var feil -- funnet 2026-09-05 ved en systematisk gjennomgang av
    # strukturert data på tvers av ALLE sidetyper). Speiler nøyaktig den
    # synlige brødsmulen under (Hjem > Optikerkjedenes egne merker > navn).
    breadcrumb_schema = f'''{{"@type": "BreadcrumbList", "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "Optikerkjedenes egne merker", "item": "{BASE_URL}/private-label/"}},
    {{"@type": "ListItem", "position": 3, "name": "{_json_str(private_name)}", "item": "{BASE_URL}/private-label/{label["slug"]}/"}}
  ]}}'''
    webpage_schema = f'''{{
  "@type": "WebPage",
  "name": "{escape(private_name)} er egentlig {escape(real_name)}",
  "about": {{"@type": "{about_type}", "name": "{escape(real_name)}", "brand": {{"@type": "Brand", "name": "{escape(real_brand)}"}}{about_offers_schema}}},
  "mainEntityOfPage": "{BASE_URL}/private-label/{label["slug"]}/"{f', "dateModified": "{date_modified}"' if date_modified else ""}
}}'''
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@graph": [{breadcrumb_schema}, {webpage_schema}]
}}"""

    # Samme dynamiske FAQ-mønster som render_product_page/render_solution_
    # product_page, men spørsmålene refererer til det EKTE produktnavnet
    # (real_name) siden det er det tilbudene faktisk gjelder -- "hvorfor har
    # den to navn"-spørsmålet er bevisst IKKE med her, det er allerede
    # grundig dekket av private-label-explainer-boksen over, ville bare
    # vært en duplisering.
    product_faq: list[dict] = []
    if best:
        cheapest_product_offer = min(in_stock_offers, key=lambda o: o["price_nok"])
        if cheapest_product_offer["retailer"] != best["retailer"]:
            billigst_svar = (
                f'{cheapest_product_offer["retailer"]} har lavest produktpris: {_fmt_kr(cheapest_product_offer["price_nok"])} uten frakt. '
                f'Regner du med frakt, blir {best["retailer"]} billigst: {_fmt_kr(best["total"])} totalt inkludert frakt.'
            )
        else:
            billigst_svar = (
                f'{best["retailer"]} har lavest pris, både uten og med frakt: {_fmt_kr(best["price_nok"])} uten frakt '
                f'({_fmt_kr(best["total"])} inkludert frakt).'
            )
        product_faq.append({"question": f'Hvor er {real_name} ({private_name}) billigst?', "answer": billigst_svar})

        laveste_produktpris = min(o["price_nok"] for o in in_stock_offers)
        product_faq.append({
            "question": f'Hva koster {real_name}?',
            "answer": f'Laveste produktpris på {real_name} er {_fmt_kr(laveste_produktpris)} uten frakt akkurat nå. '
                      f'Totalprisen avhenger av hvilken butikk du velger og fraktkostnaden der.',
        })

    product_faq.append({
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk daglig. Vi viser butikkens produktpris "
                  "uten frakt og beregner totalpris basert på frakt og antallet du velger.",
    })

    product_faq_html, product_faq_schema = _render_faq_block(product_faq, f'Vanlige spørsmål om {real_name}')

    related_items = [
        (f'/merke/{real_product["brand_slug"]}/', f'Alle {real_brand}-kontaktlinser'),
        (f'/kontaktlinser/{real_product["category_slug"]}/', f'Alle {category_label.lower()}'),
    ]
    illustration = render_private_label_illustration(chain, label["slug"])
    if illustration:
        hero_visual = (f'<div class="pli-tile-wrap">{illustration}</div>'
                       '<p class="illustration-note">Egen illustrasjon, ikke et ekte produktbilde. <a href="/om-produktillustrasjoner/">Les mer</a></p>')
    else:
        hero_visual = escape(private_name[:2].upper())
    subbrand_slug = PRIVATE_LABEL_SUBBRANDS.get(chain, chain).lower()
    related_items.append((f'/merke/{subbrand_slug}/', f'Flere {PRIVATE_LABEL_SUBBRANDS.get(chain, chain)}-produkter'))
    related_links = "\n    ".join(f'<li><a href="{escape(href)}">{escape(label_text)}</a></li>' for href, label_text in related_items)
    related_html = f"""<div class="related">
    <h2>Relatert til {escape(private_name)}</h2>
    <ul>
    {related_links}
    </ul>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(private_name)} » Sammenlign og få billigste pris</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/private-label/{label["slug"]}/">
{_og_meta(f'{private_name} » Sammenlign og få billigste pris', meta_description, f'{BASE_URL}/private-label/{label["slug"]}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
{product_faq_schema}
<style>{SHARED_STYLE}
{HERO_IMAGE_STYLE}
{PRIVATE_LABEL_ILLUSTRATION_STYLE}
.hero-card-solution .hero-product-image.pli-hero {{ padding: 8px; }}
.hero-card-solution .pli-hero .pli-tile-wrap {{ width: 100%; }}
.hero-card-solution .hero-product-image.pli-hero {{ flex-direction: column; gap: 10px; }}
.illustration-note {{ margin: 0; padding: 0 8px; font-size: 0.68rem; line-height: 1.4; color: var(--muted); text-align: center; font-family: 'Inter', sans-serif; font-weight: 400; }}
.illustration-note a {{ color: var(--blue); }}
.private-label-explainer {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin: 20px 0; font-size: 0.92rem; line-height: 1.6; }}
.private-label-explainer strong {{ color: var(--ink); }}
.private-label-caveat {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
.pack-size-callout {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; margin: 16px 0; text-decoration: none; color: inherit; font-size: 0.85rem; }}
.pack-size-callout:hover {{ border-color: var(--blue); }}
.pack-size-callout-arrow {{ color: var(--blue); font-size: 1.1rem; flex-shrink: 0; }}
.product-ai-summary {{ background: var(--blue-tint); border-left: 4px solid var(--blue); border-radius: 0 10px 10px 0; padding: 12px 18px; margin: 12px 0; font-size: 0.95rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary p {{ margin: 0; }}
.product-ai-summary.fallback {{ background: var(--muted-bg); border-left-color: var(--muted); color: var(--muted); }}
{WINNER_WIDGET_STYLE}
{PRICE_LIST_STYLE}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-product">
  <p class="breadcrumb">
    <a href="/">Hjem</a> ›
    <a href="/private-label/">Optikerkjedenes egne merker</a> ›
    {escape(private_name)}
  </p>
  <div class="product-stage">
    <div class="hero-card hero-card-solution">
      <div class="hero-main">
        <div class="hero-copy">
        <div class="hero-kicker">Eget merkenavn</div>
        <h1>{escape(private_name)} er egentlig {escape(real_name)}</h1>
        <p class="hero-subtitle">Sammenlign priser</p>
        </div>
        <div class="hero-media-row">
          <div class="hero-product-image pli-hero">{hero_visual}</div>
          {winner_html}
        </div>
      </div>
    </div>
    {qty_html}
  </div>
  {offers_block}
  {price_history_html}
  {qty_multi_html}
  <p style="margin-top:16px;"><a href="{escape(real_href)}" style="color:var(--blue);font-weight:600;text-decoration:none;">Se full produktside for {escape(real_name)} →</a></p>
  {f'<a class="pack-size-callout" href="/serie/{escape(family["slug"])}/"><div class="pack-size-callout-text">Se hele <strong>{escape(family["name"])}</strong>-serien — sammenlign sfærisk, torisk og andre varianter</div><div class="pack-size-callout-arrow">→</div></a>' if family else ''}

  <div class="private-label-explainer">
    <p><strong>Hvorfor har den to navn?</strong> Mange optikerkjeder kjøper kontaktlinser fra de samme produsentene som selger under egne kjente merker, og pakker dem om under et eget varenavn. Selve linsen – materiale, styrkeområde og spesifikasjoner – er den samme. Det er bare emballasjen og navnet som er unikt for denne serien.</p>
    <p style="margin-top:10px;"><a href="/slik-matcher-vi-produkter/" style="color:var(--blue);font-weight:600;text-decoration:none;">Hvordan vet vi at dette er samme linse? →</a></p>
  </div>

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Denne koblingen er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale med kjeden bak dette merkenavnet og kan ikke garantere at koblingen stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept at {escape(real_name)} faktisk er riktig erstatning for {escape(private_name)} før du bytter.
  </div>

  <p class="disclosure">
    Butikkene sorteres etter lavest produktpris. Slå på «Pris inkludert frakt» for å
    se og sortere etter totalpris (produktpris + frakt) for antallet du har valgt.
    Vi kan få provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på pris, bortsett fra ved eksakt lik pris
    mellom to tilbud, der vi kan prioritere en forhandler vi har avtale med. Varer
    uten bekreftet lager kan ikke vinne «laveste pris», og hvert tilbud viser når det
    sist ble kontrollert.
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
    forhandler, og har ingen avtale med kjeden bak dette merkenavnet.
  </p>
  {ai_summary_html}
  {product_faq_html}
  {METHODOLOGY_HTML}
  {related_html}
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_family_page(
    family_name: str,
    family_slug: str,
    members: list[dict],
    categories: dict,
    chain: str | None = None,
    now: datetime | None = None,
    price_history: dict | None = None,
) -> str:
    """Produktserie-side (/serie/{slug}/) -- samler sfærisk/torisk/
    multifokal/XR-variantene av SAMME linsedesign på én side, med en ekte
    sammenligningstabell (ikke bare en lenkeliste). Lagt til 2026-09-05
    etter at lenspricer.no ble observert å få et ekstra søketreff nettopp
    fra denne sidetypen for "easyvision vitrea" -- se product_families.json
    for kureringsprinsippet (manuelt, IKKE auto-utledet fra id-mønster).

    members: liste av {"display_name", "href", "product"} -- "product" er
    ALLTID det ekte produktet (for pris/spec-fakta), "display_name"/"href"
    er enten det ekte produktnavnet (chain=None) eller et private
    label-navn/lenke (chain satt) -- samme "vis under annet navn, bruk ekte
    tilbud"-prinsipp som render_private_label_page().
    chain: satt kun for private label-varianten av en familie (f.eks.
    "Specsavers") -- endrer tittel/forklaringsboks, ikke selve tabellen."""
    now = now or datetime.now(timezone.utc)

    rows = []
    for m in members:
        product = m["product"]
        offers = reconcile_product(product["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        best = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        pack = _pack_size_from_id(product["id"])
        specs = {label: value for label, value in product.get("specs", [])}
        rows.append({
            "display_name": m["display_name"],
            "href": m["href"],
            "product": product,
            "best": best,
            "eligible": eligible,
            "n_offers": len(eligible),
            "pack_size": pack[1] if pack else None,
            "category_slug": product["category_slug"],
            "category_label": categories.get(product["category_slug"], {}).get("label", ""),
            "specs": specs,
            "wc": _parse_spec_numbers(specs.get("Vanninnhold")),
            "bc": _parse_spec_numbers(specs.get("Basiskurve")),
            "material": specs.get("Materiale"),
        })

    show_wc = any(r["wc"] for r in rows)
    show_bc = any(r["bc"] for r in rows)
    show_material = any(r["material"] for r in rows)

    manufacturer_slug = BRAND_TO_MANUFACTURER.get(rows[0]["product"]["brand_slug"]) if rows else None
    manufacturer_name = MANUFACTURERS[manufacturer_slug]["name"] if manufacturer_slug else None

    prices = [r["best"]["price_nok"] for r in rows if r["best"]]
    lowest_row = min((r for r in rows if r["best"]), key=lambda r: r["best"]["price_nok"], default=None)

    # "Finn din variant" (lenger nede) trenger EN etikett per behov/kategori --
    # delt her siden BÅDE tabellen og kortene bruker den samme mappingen.
    _VARIANT_NEED_LABELS = {
        "manedslinser": "Vanlig synskorreksjon", "dagslinser": "Vanlig synskorreksjon",
        "toriske-linser": "Astigmatisme", "multifokale-linser": "Alderssyn / multifokal",
        "fargede-linser": "Fargekorreksjon",
    }
    by_category: dict[str, list[dict]] = {}
    for r in rows:
        by_category.setdefault(r["category_slug"], []).append(r)

    # Sammenligningstabellen viser nå ÉN RAD PER BEHOV (ikke per pakningsstørrelse
    # -- 2026-09-27, Kai sitt ønske om "ekte data og tall vi har, for enda mer
    # relevant info"), med Diameter og ADD/CYL/AXIS som nye kolonner utledet fra
    # de faktiske specs-feltene (ikke alle produkter har disse -- se
    # products_meta.json sin reelle feltdekning, Addisjon/UV-filter er sjeldne).
    # BC/diameter/materiale antas likt på tvers av pakningsstørrelser INNENFOR
    # samme behov (samme fysiske linse, bare ulikt antall i esken) -- representant-
    # raden (minste pakning) sine spec-verdier brukes derfor for hele gruppen.
    table_groups = []
    for cat_slug in list(CATEGORY_BG) + [s for s in by_category if s not in CATEGORY_BG]:
        group = by_category.get(cat_slug)
        if not group:
            continue
        rep = min(group, key=lambda r: r["pack_size"] or 0)
        group_packs = sorted({r["pack_size"] for r in group if r["pack_size"]})
        group_prices = [r["best"]["price_nok"] for r in group if r["best"]]
        has_cyl = any(r["specs"].get("Sylinder") or r["specs"].get("Akse") for r in group)
        has_add = any(r["specs"].get("Addisjon") for r in group)
        table_groups.append({
            "name": re.sub(r"\s+\d+-pack$", "", rep["display_name"]),
            "href": rep["href"],
            "product": rep["product"],
            "need_label": _VARIANT_NEED_LABELS.get(cat_slug, rep["category_label"]),
            "material": rep["material"],
            "wc": rep["wc"],
            "bc": rep["bc"],
            "diameter": _parse_spec_numbers(rep["specs"].get("Diameter")),
            "power_dim": "CYL/AXIS" if has_cyl else ("ADD" if has_add else "–"),
            "packs_txt": "/".join(str(n) for n in group_packs) if group_packs else "–",
            "price": min(group_prices) if group_prices else None,
        })

    show_diameter = any(g["diameter"] for g in table_groups)
    show_power_dim = any(g["power_dim"] != "–" for g in table_groups)

    def table_row(g: dict) -> str:
        wc_txt = " / ".join(f"{v.replace('.', ',')} %" for v in g["wc"]) if g["wc"] else "–"
        bc_txt = " / ".join(f"{v.replace('.', ',')} mm" for v in g["bc"]) if g["bc"] else "–"
        dia_txt = " / ".join(f"{v.replace('.', ',')} mm" for v in g["diameter"]) if g["diameter"] else "–"
        material_txt = escape(g["material"]) if g["material"] else "–"
        price_txt = _fmt_kr(g["price"]) if g["price"] else "Ingen pris"
        cells = f'''<td class="spec-value">{escape(g["need_label"])}</td>'''
        if show_material:
            cells += f'\n    <td class="spec-value">{material_txt}</td>'
        if show_wc:
            cells += f'\n    <td class="spec-value">{wc_txt}</td>'
        if show_bc:
            cells += f'\n    <td class="spec-value">{bc_txt}</td>'
        if show_diameter:
            cells += f'\n    <td class="spec-value">{dia_txt}</td>'
        if show_power_dim:
            cells += f'\n    <td class="spec-value">{escape(g["power_dim"])}</td>'
        row_img = _product_image(g["product"])
        thumb_html = f'<img class="spec-row-thumb" src="{escape(row_img)}" alt=""{_dim_attrs(row_img)} loading="lazy">' if row_img else ''
        return f'''<tr>
    <th scope="row" class="spec-label"><a href="{escape(g["href"])}">{thumb_html}{escape(g["name"])}</a></th>
    {cells}
    <td class="spec-value">{escape(g["packs_txt"])}</td>
    <td class="spec-value">{price_txt}</td>
  </tr>'''

    table_header_extra = ""
    if show_material:
        table_header_extra += "<th>Materiale</th>"
    if show_wc:
        table_header_extra += "<th>Vanninnhold</th>"
    if show_bc:
        table_header_extra += "<th>BC (mm)</th>"
    if show_diameter:
        table_header_extra += "<th>Diameter (mm)</th>"
    if show_power_dim:
        table_header_extra += "<th>ADD/CYL/AXIS</th>"

    comparison_table = f'''<div style="overflow-x:auto;">
  <table class="spec-table">
    <thead>
      <tr><th>Variant</th><th>For</th>{table_header_extra}<th>Pakninger</th><th>Fra pris (uten frakt)</th></tr>
    </thead>
    <tbody>
      {"".join(table_row(g) for g in table_groups)}
    </tbody>
  </table>
</div>'''

    # "Alle produkter i X-serien" -- gjenbruker DEN SAMME kort-komponenten som
    # kategori-/merke-/tilbehør-sidene allerede bruker (_render_product_tile()),
    # IKKE et nytt kortdesign -- Kai sitt eksplisitte ønske 2026-09-27: "de som
    # vi bruker selv og har i dag", ikke mock-designet.
    def product_tile(r: dict) -> str:
        return _render_product_tile(
            href=r["href"], name=r["display_name"], image_url=_product_image(r["product"]),
            fallback_initials=r["product"]["brand_label"][:2].upper(),
            category_label=r["category_label"], secondary_line_html="",
            lowest=r["best"], other_count=max(0, r["n_offers"] - 1),
        )
    all_products_html = f'''<h2>Alle produkter i {escape(family_name)}-serien</h2>
  <div class="product-tile-grid">
    {"".join(product_tile(r) for r in rows)}
  </div>''' if len(rows) > 1 else ""

    # "Relevante guider" -- bildekort i stedet for de rene ikon-kortene
    # (render_guide_tile), etter Kai sitt ønske 2026-09-27 om at ikon-boksene
    # var kjedelige. Guidene har ingen egne foto i datamodellen -- gjenbruker
    # derfor kategorikortenes egne pastellbilder (samme filer som "Finn din
    # variant" over), IKKE samme tema/tekst som selve guiden nødvendigvis,
    # men reelle bilder vi allerede eier/har lisens til, valgt for et visst
    # tematisk slektskap der det er naturlig (astigmatisme-guide -> toriske-
    # bildet, osv.) fremfor helt tilfeldig.
    _GUIDE_IMAGE = {
        "hvordan-bruke-kontaktlinser": "dag", "kontaktlinser-med-astigmatisme": "toriske",
        "multifokale-kontaktlinser": "multifokale", "manedslinser-vs-dagslinser": "maaned",
        "hvordan-velge-kontaktlinser": "fargede",
    }
    relevant_guide_slugs = ["hvordan-bruke-kontaktlinser"]
    if any(g["power_dim"] == "CYL/AXIS" for g in table_groups):
        relevant_guide_slugs.append("kontaktlinser-med-astigmatisme")
    elif any(g["power_dim"] == "ADD" for g in table_groups):
        relevant_guide_slugs.append("multifokale-kontaktlinser")
    else:
        relevant_guide_slugs.append("manedslinser-vs-dagslinser")
    relevant_guide_slugs.append("hvordan-velge-kontaktlinser")

    def guide_photo_card(slug: str) -> str:
        g = GUIDE_CONTENT[slug]
        bg = _GUIDE_IMAGE.get(slug, "dag")
        return f'''<a class="guide-photo-card" href="/guide/{escape(slug)}/">
    <div class="guide-photo-card-image">
      <img src="/static/categories/bg-{bg}-320.webp" alt="" width="320" height="143" loading="lazy" decoding="async">
    </div>
    <div class="guide-photo-card-body">
      <div class="guide-photo-card-title">{escape(g["title"])}</div>
      <div class="guide-photo-card-link">Les guiden →</div>
    </div>
  </a>'''

    guides_html = f'''<div class="serie-guides">
    <h2>Relevante guider</h2>
    <div class="guide-photo-grid">
      {"".join(guide_photo_card(slug) for slug in relevant_guide_slugs if slug in GUIDE_CONTENT)}
    </div>
  </div>'''

    # pack_sizes/materials_present brukes flere steder lenger ned (stat-piller,
    # "Kort om X" osv.) -- selve FAQ-en er flyttet til en regelmotor lenger
    # ned i funksjonen (se kommentaren ved faq_produkt/faq_spec/faq_pris),
    # siden den trenger data (uv_values, wc_values_stat, table_groups'
    # power_dim osv.) som først finnes der.
    pack_sizes = sorted({r["pack_size"] for r in rows if r["pack_size"]})
    materials_present = {r["material"] for r in rows if r["material"]}

    material_sentence = f' i {rows[0]["material"]}' if show_material and rows[0]["material"] else ""
    manufacturer_sentence = f' fra {escape(manufacturer_name)}' if manufacturer_name else ""
    intro = (
        f'<p>{escape(family_name)} er en linseserie{manufacturer_sentence}{material_sentence} som finnes i flere '
        f'varianter -- sfærisk, og der det finnes: torisk (astigmatisme) og/eller multifokal (alderssyn). '
        f'Grunnmaterialet og teknologien er delt på tvers av variantene; det som skiller dem er styrkeprofilen '
        f'linsen er formet for å korrigere.</p>'
    )

    # Nøkkeltall-rad i heroen -- kun det vi faktisk kan bevise fra dataen
    # (aldri en "teknologi"-påstand, siden specs ikke har et slikt felt
    # konsekvent per produkt). Vanninnhold vises kun når ALLE variantene
    # faktisk deler nøyaktig samme verdi -- samme "aldri gjett/generaliser"-
    # prinsipp som FAQ-en under bruker for materiale.
    type_labels_stat = sorted({r["category_label"] for r in rows if r["category_label"]})
    wc_values_stat = {tuple(r["wc"]) for r in rows if r["wc"]}
    stat_pills = [
        (BOX_ICON_SVG, f'{len(rows)} produkter', " og ".join(f"{n}-pakning" for n in pack_sizes) if pack_sizes else ""),
        (TAG_ICON_SVG, f'{len(type_labels_stat)} behov' if len(type_labels_stat) > 1 else (type_labels_stat[0] if type_labels_stat else ""), " · ".join(type_labels_stat) if len(type_labels_stat) > 1 else ""),
    ]
    if show_material and len(materials_present) == 1:
        stat_pills.append((DROPLET_ICON_SVG, "Materiale", next(iter(materials_present))))
    if len(wc_values_stat) == 1:
        stat_pills.append((DROPLET_ICON_SVG, "Vanninnhold", " / ".join(f"{v.replace('.', ',')} %" for v in next(iter(wc_values_stat)))))
    stat_pills_html = "".join(
        f'''<div class="serie-stat-pill">
    <span class="serie-stat-icon" aria-hidden="true">{icon}</span>
    <div><div class="serie-stat-label">{escape(label)}</div>{f'<div class="serie-stat-value">{escape(value)}</div>' if value else ''}</div>
  </div>'''
        for icon, label, value in stat_pills if label
    )

    # "Finn din variant" -- én kandidatside per BEHOV (kategori) familien
    # faktisk dekker, ikke én per pakningsstørrelse. Gjenbruker BEVISST
    # kategorikortenes egne pastellbilder (static/categories/bg-*) i stedet
    # for å finne opp en tredje type linsebilde -- Kai sitt eget poeng
    # 2026-09-27: for mange ulike linsebilder (hero + "finn variant" +
    # pakningsbilder i tabellen) ville blitt rotete. Rekkefølgen følger
    # CATEGORY_BG sin nøkkelrekkefølge (måned/dag før torisk/farget/multifokal)
    # slik at "vanlig synskorreksjon" alltid kommer først. (_VARIANT_NEED_LABELS
    # og by_category er allerede bygget over, til sammenligningstabellen.)
    variant_cards = []
    for cat_slug in list(CATEGORY_BG) + [s for s in by_category if s not in CATEGORY_BG]:
        group = by_category.get(cat_slug)
        if not group:
            continue
        rep = min(group, key=lambda r: r["pack_size"] or 0)
        group_packs = sorted({r["pack_size"] for r in group if r["pack_size"]})
        packs_txt = " eller ".join(str(n) for n in group_packs) + " linser" if group_packs else ""
        bg = CATEGORY_BG.get(cat_slug)
        bg_html = (
            f'<img class="variant-card-bg" src="/static/categories/bg-{bg}-320.webp" alt="" width="320" height="143" loading="lazy" decoding="async">'
            if bg else ""
        )
        variant_cards.append(f'''<a class="variant-card" href="{escape(rep["href"])}">
    <div class="variant-card-thumb">{bg_html}</div>
    <div class="variant-card-text">
      <div class="variant-card-need">{escape(_VARIANT_NEED_LABELS.get(cat_slug, categories.get(cat_slug, {}).get("label", "")))}</div>
      <div class="variant-card-name">{escape(rep["display_name"])}</div>
      {f'<div class="variant-card-packs">{escape(packs_txt)}</div>' if packs_txt else ''}
    </div>
    <span class="variant-card-arrow" aria-hidden="true">→</span>
  </a>''')
    variant_finder_html = ""
    if len(variant_cards) > 1:
        variant_finder_html = f'''<h2>Finn din variant</h2>
  <p class="variant-finder-lead">Hvilken {escape(family_name)} passer for deg?</p>
  <div class="variant-finder-grid">
    {"".join(variant_cards)}
  </div>
  <div class="variant-finder-note">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
    <p>Har du allerede fått foreskrevet en bestemt variant av optiker? Velg samme variant, og kontroller alltid BC, styrke og eventuelle CYL/AXIS/ADD-verdier mot resepten din.</p>
  </div>'''

    # Prisinnsikt for HELE serien (snitt per pakningsstørrelse, se
    # _family_price_insight_data()) -- Kai sitt eksplisitte ønske 2026-09-27,
    # en type innsikt kun mulig fordi vi ser flere produkter samlet.
    price_insight_html = ""
    if price_history:
        insight_by_pack = _family_price_insight_data(rows, price_history)
        price_insight_html = render_family_price_insight(family_name, insight_by_pack)

    # "Kort om X" -- ved siden av Prisinnsikt (Kai: "slik at vi får en
    # komprimert prisinnsikt, det holder"), KUN fakta vi faktisk kan bevise er
    # like på tvers av ALLE variantene (samme "aldri gjett"-prinsipp som
    # resten av siden -- f.eks. UV-filter er et reelt specs-felt, men finnes
    # ikke i det hele tatt for enkelte familier, og utelates da helt i stedet
    # for å late som det er sjekket).
    brukstid_values = {r["specs"].get("Brukstid") for r in rows if r["specs"].get("Brukstid")}
    uv_values = {r["specs"].get("UV-filter") for r in rows if r["specs"].get("UV-filter")}
    # Hver rad: (ikon, hovedverdi, undertekst/etikett) -- delt datagrunnlag for
    # BÅDE "Kort om X" (sjekkliste, ved Prisinnsikt) og "Felles for hele
    # serien" (ikon-rutenett, ved Relevante guider lenger ned) -- samme fakta,
    # to ulike visuelle roller, se Kai sin tilbakemelding 2026-09-27.
    fact_rows = []
    if len(brukstid_values) == 1:
        bt = next(iter(brukstid_values))
        bt_sub = {"Dagslinse": "Ny linse hver dag", "Månedslinse": "Skiftes månedlig", "Ukelinse": "Skiftes ukentlig"}.get(bt, "")
        fact_rows.append((CALENDAR_ICON_SVG, bt, bt_sub))
    if show_material and len(materials_present) == 1:
        fact_rows.append((BOX_ICON_SVG, next(iter(materials_present)), "Materiale"))
    if len(wc_values_stat) == 1:
        fact_rows.append((DROPLET_ICON_SVG, " / ".join(f"{v.replace('.', ',')} %" for v in next(iter(wc_values_stat))), "Vanninnhold"))
    if len(uv_values) == 1:
        fact_rows.append((SUN_ICON_SVG, next(iter(uv_values)), "UV-filter"))
    if type_labels_stat:
        fact_rows.append((TAG_ICON_SVG, ", ".join(type_labels_stat), "Tilgjengelig for"))

    facts_html = ""
    if fact_rows:
        items = "".join(
            f'''<li>{CHECK_ICON_SVG}<div><strong>{escape(main)}</strong>{f'<span>{escape(sub)}</span>' if sub else ''}</div></li>'''
            for icon, main, sub in fact_rows
        )
        facts_html = f'''<div class="serie-facts">
    <h2>Kort om {escape(family_name)}</h2>
    <ul class="serie-facts-list">{items}</ul>
  </div>'''
    insight_row_html = (
        f'<div class="serie-insight-row">{price_insight_html}{facts_html}</div>'
        if price_insight_html and facts_html else price_insight_html + facts_html
    )

    felles_html = ""
    if fact_rows:
        tiles = "".join(
            f'''<div class="serie-fact-tile">
      <div class="serie-fact-tile-icon" aria-hidden="true">{icon}</div>
      <div class="serie-fact-tile-value">{escape(main)}</div>
      <div class="serie-fact-tile-label">{escape(sub) if sub else ''}</div>
    </div>'''
            for icon, main, sub in fact_rows
        )
        # Ingen lenke til "vår guide" -- vi har ingen egen UV-beskyttelse-guide
        # i GUIDE_CONTENT ennå, og finner ikke opp en lenke som ikke finnes.
        uv_note = (
            '<p>Kontaktlinser med UV-filter erstatter ikke solbriller.</p>'
            if len(uv_values) == 1 else ""
        )
        felles_html = f'''<div class="serie-facts-tiles">
    <h2>Felles for hele serien</h2>
    <div class="serie-facts-tiles-grid">{tiles}</div>
    {f'<div class="serie-fact-note">{TAG_ICON_SVG}{uv_note}</div>' if uv_note else ''}
  </div>'''

    # ------------------------------------------------------------------
    # FAQ -- regelmotor (2026-09-27, etter forslag fra Kai): spørsmålene
    # genereres KUN fra fakta vi faktisk har for DENNE familien, aldri fylt
    # opp til et fast antall -- én serie kan ende med 4 spørsmål, en annen
    # med 10, det er poenget. Google fjernet FAQ-rich-result-visningen i
    # søket for flere år siden (bekreftet direkte mot
    # developers.google.com/search/updates -- "The FAQ rich result feature
    # is no longer shown in Google Search results"), så verdien her er IKKE
    # lenger et rikt SERP-utfall, det er reelt informasjonsinnhold for
    # AI-siteringer (OAI-SearchBot m.fl., IKKE GPTBot som er blokkert i
    # robots.txt) og long-tail-søk. Gruppert i tre faste kategorier (samme
    # rekkefølge som resten av siden: produkt -> spec -> pris) og vist som en
    # ekte, kollapset <details>-accordion (se render_winner_widget() for
    # presedens: <details> er eksplisitt nevnt av Google som en legitim
    # vis/skjul-mekanisme, i motsetning til CSS-utenfor-skjerm-tekst).
    #
    # To kandidatspørsmål fra forslaget er BEVISST utelatt:
    # - "Hvor ofte oppdateres prisene?" -- identisk svar for alle familier,
    #   gir ingen serie-spesifikk info (strider mot "aldri fyll ut"-prinsippet).
    # - Forklaring av materialnavn ("Hva er LACREON?"/"Etafilcon A?") -- krever
    #   en egen, research-basert ordliste over produsentenes materialnavn som
    #   vi ikke har strukturert data for ennå. Flagget som fremtidig oppgave.
    faq_produkt: list[dict] = []
    faq_spec: list[dict] = []
    faq_pris: list[dict] = []

    type_labels = sorted({r["category_label"] for r in rows if r["category_label"]})
    if type_labels:
        type_txt = " og ".join(type_labels) if len(type_labels) <= 2 else ", ".join(type_labels[:-1]) + " og " + type_labels[-1]
        pack_txt = f' Den fås i {" og ".join(f"{n}-pakning" for n in pack_sizes)}.' if pack_sizes else ""
        faq_produkt.append({
            "question": f'Hvilke varianter finnes av {family_name}?',
            "answer": f'{family_name}-serien finnes som {type_txt.lower()}.{pack_txt} Se tabellen over for pris på hver variant.',
        })

    # Basert på KATEGORIEN (by_category, samme kilde som "Finn din variant"
    # og tabellens type-kolonne), IKKE på om CYL/AXIS/ADD-spesifikke tallfelt
    # finnes -- enkelte toriske/multifokale produkter mangler disse feltene i
    # specs-dataen (se f.eks. Dailies Total1 sin astigmatisme-variant), men
    # er likevel reelt torisk/multifokal per kategoriseringen. Svaret nevner
    # CYL/AXIS/ADD kun når de faktisk finnes i specs.
    toric_group_rows = by_category.get("toriske-linser")
    multi_group_rows = by_category.get("multifokale-linser")
    if toric_group_rows and len(by_category) > 1:
        rep = min(toric_group_rows, key=lambda r: r["pack_size"] or 0)
        rep_name = re.sub(r"\s+\d+-pack$", "", rep["display_name"])
        has_cyl_spec = any(r["specs"].get("Sylinder") or r["specs"].get("Akse") for r in toric_group_rows)
        cyl_txt = (
            ' Den har egne CYL- og AXIS-verdier (se tabellen under) som må matche resepten din fra optiker.'
            if has_cyl_spec else ' Se tabellen under for pris og pakningsstørrelser.'
        )
        faq_produkt.append({
            "question": f'Finnes {family_name} for astigmatisme?',
            "answer": f'Ja, {rep_name} er den toriske varianten i {family_name}-serien, laget spesifikt for astigmatisme.{cyl_txt}',
        })
    if multi_group_rows and len(by_category) > 1:
        rep = min(multi_group_rows, key=lambda r: r["pack_size"] or 0)
        rep_name = re.sub(r"\s+\d+-pack$", "", rep["display_name"])
        has_add_spec = any(r["specs"].get("Addisjon") for r in multi_group_rows)
        add_txt = (
            ', med en egen ADD-verdi (tilleggsstyrke for nærsyn/lesing) i tillegg til vanlig styrke'
            if has_add_spec else ', for alderssyn (presbyopi) i tillegg til vanlig styrke'
        )
        faq_produkt.append({
            "question": f'Finnes {family_name} som multifokal linse for alderssyn?',
            "answer": f'Ja, {rep_name} er multifokal-varianten i {family_name}-serien{add_txt}.',
        })
    if len(materials_present) == 1 and len(rows) > 1:
        faq_produkt.append({
            "question": f'Er alle variantene i {family_name}-serien laget av samme materiale?',
            "answer": f'Ja, hele {family_name}-serien er laget av {next(iter(materials_present))}. '
                      f'Det er styrkeprofilen (sfærisk, torisk eller multifokal) som skiller variantene, ikke selve linsematerialet.',
        })

    if len(table_groups) > 1 and (show_bc or show_diameter):
        bc_all = {tuple(g["bc"]) for g in table_groups if g["bc"]}
        dia_all = {tuple(g["diameter"]) for g in table_groups if g["diameter"]}
        spec_parts = []
        if show_bc:
            if len(bc_all) == 1:
                spec_parts.append(f'basiskurven (BC) er {"/".join(v.replace(".", ",") for v in next(iter(bc_all)))} mm for alle variantene')
            else:
                spec_parts.append('basiskurven (BC) varierer mellom variantene: ' + ", ".join(
                    f'{g["name"]} {"/".join(v.replace(".", ",") for v in g["bc"])} mm' for g in table_groups if g["bc"]
                ))
        if show_diameter:
            if len(dia_all) == 1:
                spec_parts.append(f'diameteren er {"/".join(v.replace(".", ",") for v in next(iter(dia_all)))} mm for alle')
            else:
                spec_parts.append('diameteren varierer: ' + ", ".join(
                    f'{g["name"]} {"/".join(v.replace(".", ",") for v in g["diameter"])} mm' for g in table_groups if g["diameter"]
                ))
        if spec_parts:
            spec_answer = spec_parts[0][0].upper() + spec_parts[0][1:]
            if len(spec_parts) == 2:
                spec_answer += ", mens " + spec_parts[1]
            spec_answer += ". Kontroller alltid disse verdiene mot resepten din fra optiker."
            faq_spec.append({
                "question": f'Har alle variantene i {family_name}-serien samme basiskurve og diameter?',
                "answer": spec_answer,
            })

    power_dim_types = {g["power_dim"] for g in table_groups if g["power_dim"] != "–"}
    if power_dim_types:
        glossary_parts = []
        if "CYL/AXIS" in power_dim_types:
            glossary_parts.append('CYL (sylinderstyrke) og AXIS (akse) beskriver hvor mye og i hvilken retning linsen korrigerer astigmatisme (skjevhet i hornhinnen)')
        if "ADD" in power_dim_types:
            glossary_parts.append('ADD (addisjon) er tilleggsstyrken i en multifokal linse for nærsyn/lesing, i tillegg til vanlig styrke, ved alderssyn (presbyopi)')
        faq_spec.append({
            "question": 'Hva betyr CYL/AXIS/ADD i sammenligningstabellen?',
            "answer": ". ".join(p[0].upper() + p[1:] for p in glossary_parts) + '. Verdiene skal alltid matche resepten din fra optiker, ikke velges på egen hånd.',
        })

    if len(uv_values) == 1:
        faq_spec.append({
            "question": f'Har {family_name} UV-filter?',
            "answer": f'Ja, hele {family_name}-serien har UV-filter ({next(iter(uv_values))}). Dette erstatter ikke solbriller -- '
                      f'UV-filteret beskytter kun selve øyet linsen dekker, ikke resten av øyet og huden rundt.',
        })

    if lowest_row and lowest_row["best"]:
        faq_pris.append({
            "question": f'Hva er billigst i {family_name}-serien?',
            "answer": f'{lowest_row["display_name"]} er billigst akkurat nå, fra {_fmt_kr(lowest_row["best"]["price_nok"])} '
                      f'hos {lowest_row["best"]["retailer"]} (uten frakt). Prisen varierer mellom variantene i serien.',
        })

    all_retailer_names: set[str] = set()
    offer_counts = []
    for r in rows:
        elig = r["eligible"]
        all_retailer_names.update(o["retailer"] for o in elig)
        if elig:
            offer_counts.append(len(elig))
    if all_retailer_names and offer_counts:
        shop_txt = f'{offer_counts[0]} butikker' if len(set(offer_counts)) == 1 else f'{min(offer_counts)}–{max(offer_counts)} butikker per variant'
        faq_pris.append({
            "question": f'Hos hvor mange butikker kan jeg kjøpe {family_name}?',
            "answer": f'Til sammen selger {len(all_retailer_names)} norske nettbutikker {"minst én variant" if len(rows) > 1 else "denne linsen"} '
                      f'av {family_name}-serien ({shop_txt}). Se listen under hver variant for hvilke butikker som faktisk har den på lager nå.',
        })

    # Pris per linse (ikke per eske) mellom minste og største pakning INNENFOR
    # samme behov (torisk sammenlignes kun med torisk, ikke mot sfærisk) --
    # ekte tallsammenligning fra prisdataen, ikke en generisk "større
    # pakning er billigere per stykk"-påstand som ikke nødvendigvis stemmer.
    # Ett eksempel er nok -- unngår en lang, repetitiv opplisting.
    pack_compare = None
    for cat_slug, group in by_category.items():
        packed_rows = [r for r in group if r["pack_size"] and r["best"]]
        packs_seen = sorted({r["pack_size"] for r in packed_rows})
        if len(packs_seen) < 2:
            continue
        small_row = min((r for r in packed_rows if r["pack_size"] == packs_seen[0]), key=lambda r: r["best"]["price_nok"])
        large_row = min((r for r in packed_rows if r["pack_size"] == packs_seen[-1]), key=lambda r: r["best"]["price_nok"])
        small_per = small_row["best"]["price_nok"] / packs_seen[0]
        large_per = large_row["best"]["price_nok"] / packs_seen[-1]
        if abs(small_per - large_per) >= 0.3:
            pack_compare = {
                "need_label": _VARIANT_NEED_LABELS.get(cat_slug, categories.get(cat_slug, {}).get("label", "")),
                "small_n": packs_seen[0], "large_n": packs_seen[-1],
                "small_per": small_per, "large_per": large_per,
            }
            break
    if pack_compare:
        cheaper_word = "større" if pack_compare["large_per"] < pack_compare["small_per"] else "mindre"
        small_per_txt = f'{pack_compare["small_per"]:.1f}'.replace(".", ",")
        large_per_txt = f'{pack_compare["large_per"]:.1f}'.replace(".", ",")
        diff_txt = f'{abs(pack_compare["small_per"] - pack_compare["large_per"]):.1f}'.replace(".", ",") + " kr"
        faq_pris.append({
            "question": f'Lønner det seg å kjøpe {pack_compare["large_n"]}-pakning fremfor {pack_compare["small_n"]}-pakning?',
            "answer": f'For {pack_compare["need_label"].lower()} koster {pack_compare["small_n"]}-pakningen ca. '
                      f'{small_per_txt} kr per linse, mot ca. '
                      f'{large_per_txt} kr per linse i {pack_compare["large_n"]}-pakningen -- '
                      f'den {cheaper_word} pakningen er billigst per linse, en forskjell på rundt {diff_txt}. '
                      f'Husk å regne med frakt for akkurat det antallet du trenger, siden fraktgebyr kan snu regnestykket.',
        })

    # Endrer den billigste butikken seg med antall? Gjenbruker samme
    # total-pris-per-antall-logikk som "Pris ved flere esker" i
    # render_winner_widget() (produktpris * antall + beregnet frakt), på den
    # billigste varianten i familien.
    qty_change = None
    if lowest_row and len(lowest_row["eligible"]) >= 2:
        def _total_for_qty(o: dict, qty: int) -> float:
            product_total = o["price_nok"] * qty
            return product_total + compute_shipping_nok(product_total, o.get("shipping_policy"))
        best_1 = min(lowest_row["eligible"], key=lambda o: _total_for_qty(o, 1))
        best_4 = min(lowest_row["eligible"], key=lambda o: _total_for_qty(o, 4))
        qty_change = (best_1["retailer"], best_4["retailer"])
    if qty_change:
        same_retailer = qty_change[0] == qty_change[1]
        faq_pris.append({
            "question": f'Er billigste butikk for {lowest_row["display_name"]} den samme uansett hvor mange esker du kjøper?',
            "answer": (
                f'Ja, {qty_change[0]} har lavest totalpris både for 1 og for 4 esker i vår siste prissjekk.'
                if same_retailer else
                f'Ikke nødvendigvis -- {qty_change[0]} er billigst for 1 eske, mens {qty_change[1]} kan bli billigst totalt for 4 esker, '
                f'siden fraktkostnad slår ulikt ut med antall. Bruk antallsvelgeren på produktsiden for å sjekke akkurat ditt antall.'
            ),
        })

    family_faq_html, family_faq_schema = _render_family_faq_accordion(
        [("Produkt og varianter", faq_produkt), ("Spesifikasjoner", faq_spec), ("Pris og butikker", faq_pris)],
        f'Ofte stilte spørsmål om {family_name}',
    )

    chain_html = ""
    display_name_for_title = family_name
    if chain:
        chain_html = f'''<div class="private-label-explainer">
    <p><strong>Om navnet:</strong> {escape(family_name)} er navnet denne serien selges under. Se hver enkelt variants
    side for hvilket ekte produkt den tilsvarer og hvilken kjede som står bak.</p>
  </div>'''

    # Flyttet lenger ned (2026-09-27, Kai: "må vi ha denne her, eller kan vi
    # sette den lengre ned? F.eks. under Prisinnsikt") -- vises nå etter
    # prisinnsikten/"Kort om"-raden i stedet for rett under heroen.
    ai_summary_html = ""
    if lowest_row and lowest_row["best"]:
        n_variants = len(rows)
        ai_summary_html = f'''<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på alle {n_variants} variantene i {escape(family_name)}-serien. Billigst akkurat nå er
  <strong>{escape(lowest_row["display_name"])}</strong> fra <strong>{_fmt_kr(lowest_row["best"]["price_nok"])}</strong>
  hos {escape(lowest_row["best"]["retailer"])} (uten frakt). Prisene oppdateres daglig, sist bekreftet {_verified_tag(_newest_checked([o for r in rows for o in r["product"]["offers"]]))}.</p>
</section>'''

    meta_description = (
        f'Sammenlign priser på hele {family_name}-serien – sfærisk, torisk og/eller multifokal – '
        f'fra {_fmt_kr(min(prices))}. Oppdatert daglig.'
    ) if prices else f'Sammenlign priser på hele {family_name}-serien.'

    item_list_items = []
    schema_offers_by_member = []
    for i, r in enumerate(rows, start=1):
        p = r["product"]
        p_offers = reconcile_product(p["offers"], now)
        p_in_stock = [o for o in p_offers if o["in_stock"]]
        offers_field = ""
        if p_in_stock:
            low = min(o["price_nok"] for o in p_in_stock)
            high = max(o["price_nok"] for o in p_in_stock)
            offers_field = f''', "offers": {{"@type": "AggregateOffer", "priceCurrency": "NOK", "lowPrice": {low}, "highPrice": {high}, "offerCount": {len(p_in_stock)}}}'''
        item_list_items.append(f'''{{"@type": "ListItem", "position": {i}, "item": {{
      "@type": "Product", "name": "{_json_str(r["display_name"])}", "url": "{BASE_URL}{r["href"]}"{offers_field}
    }}}}''')
    schema_json = f'''{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "BreadcrumbList", "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
      {{"@type": "ListItem", "position": 2, "name": "{_json_str(family_name)}", "item": "{BASE_URL}/serie/{family_slug}/"}}
    ]}},
    {{"@type": "CollectionPage", "name": "{_json_str(family_name)}", "mainEntity": {{
      "@type": "ItemList", "itemListElement": [{",".join(item_list_items)}]
    }}}}
  ]
}}'''

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(display_name_for_title)}-serien » Sammenlign og få billigste pris</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/serie/{family_slug}/">
{_og_meta(f'{display_name_for_title}-serien » Sammenlign og få billigste pris', meta_description, f'{BASE_URL}/serie/{family_slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
{family_faq_schema}
<style>{SHARED_STYLE}
/* Premium toppbanner (2026-09-27, ETT delt bilde for alle serie-sider --
   static/hero/serie-{{560,840,1120}}.webp, samme beskjærings-/fade-teknikk
   som forsidens hero). Egne klassenavn (serie-hero*) i stedet for å
   gjenbruke .hero-card/.hero-product-image -- det MØNSTERET (produktbilde
   i egen boks) er nå bevisst forbeholdt selve tabellen/pakningsbildene,
   ikke heroen, se Kai sin tilbakemelding om at for mange ulike linsebilder
   på samme side blir rotete. */
.serie-hero {{ position: relative; overflow: hidden; border: 1px solid var(--border); border-radius: 24px; background: linear-gradient(100deg, #FFFFFF 0%, #F6F9FD 55%, #E9F1FB 100%); box-shadow: var(--card-shadow); padding: 22px 24px; margin-bottom: 20px; }}
.serie-hero-content {{ position: relative; z-index: 2; }}
.serie-hero h1 {{ font-size: clamp(1.5rem, 4vw, 2rem); margin: 4px 0 8px; }}
.serie-hero-media {{ display: none; }}
/* Egen rad, IKKE inni .serie-hero-content -- så den kan bruke hele kortets
   bredde (ikke bare tekstkolonnens 56 %) og få plass til alle pillene på én
   linje (Kai 2026-09-27: "kan vi få disse på en linje ... og bortover til
   høyre?"). */
.serie-stat-pills {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; position: relative; z-index: 2; }}
.serie-stat-pill {{ display: flex; align-items: center; gap: 8px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 6px 10px; box-shadow: var(--card-shadow); }}
.serie-stat-icon {{ width: 24px; height: 24px; border-radius: 50%; background: var(--blue-tint); color: var(--blue); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
.serie-stat-icon svg {{ width: 13px; height: 13px; }}
.serie-stat-label {{ font-size: 0.68rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.02em; line-height: 1.25; }}
.serie-stat-value {{ font-size: 0.82rem; font-weight: 600; color: var(--ink); line-height: 1.25; }}
@media (min-width: 860px) {{
  .serie-hero {{ padding: 26px 40px 24px; }}
  .serie-hero-content {{ max-width: 56%; }}
  .serie-hero-media {{ display: block; position: absolute; top: 0; right: 0; bottom: 0; width: 46%; overflow: hidden; border-radius: 0 24px 24px 0; pointer-events: none; -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 40%); mask-image: linear-gradient(90deg, transparent 0, #000 40%); }}
  .serie-hero-media img {{ display: block; width: 100%; height: 100%; object-fit: cover; object-position: right center; }}
  .serie-stat-pills {{ flex-wrap: nowrap; }}
}}
/* "Finn din variant" -- gjenbruker kategorikortenes egne pastellbilder
   (static/categories/bg-*), IKKE nye linsebilder -- se kommentaren i
   Python-koden over for begrunnelsen. Strammet inn 2026-09-27 (Kai: "litt
   mer komprimert ... er litt mye luft"). */
.variant-finder-lead {{ color: var(--muted); font-size: 0.88rem; margin: 0 0 10px; }}
.variant-finder-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 10px; }}
.variant-card {{ display: flex; align-items: center; gap: 12px; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 11px 14px; text-decoration: none; color: var(--ink); box-shadow: var(--card-shadow); transition: transform 0.15s, box-shadow 0.15s; min-height: 60px; }}
.variant-card:hover {{ transform: translateY(-2px); box-shadow: 0 10px 24px rgba(37, 99, 235, 0.14); }}
.variant-card-thumb {{ width: 48px; height: 48px; border-radius: 9px; overflow: hidden; flex-shrink: 0; background: var(--mist); }}
.variant-card-bg {{ width: 100%; height: 100%; object-fit: cover; }}
.variant-card-text {{ flex: 1; min-width: 0; }}
.variant-card-need {{ font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; color: var(--blue); }}
.variant-card-name {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.9rem; margin-top: 1px; }}
.variant-card-packs {{ font-size: 0.76rem; color: var(--muted); margin-top: 1px; }}
.variant-card-arrow {{ flex-shrink: 0; color: var(--blue); }}
.variant-finder-note {{ display: flex; gap: 9px; align-items: flex-start; background: var(--blue-tint); border-radius: 12px; padding: 10px 13px; font-size: 0.8rem; color: var(--ink); margin: 0 0 18px; }}
.variant-finder-note svg {{ flex-shrink: 0; width: 17px; height: 17px; color: var(--blue); margin-top: 1px; }}
.variant-finder-note p {{ margin: 0; }}
/* Prisinnsikt (venstre) + "Kort om X" (høyre) side om side -- Kai 2026-09-27:
   "slik at vi får en komprimert prisinnsikt". Nullstiller marginene til de to
   boksene når de står i denne raden (egne marger gir dobbel avstand ellers). */
.serie-insight-row {{ display: grid; grid-template-columns: 1fr; gap: 16px; margin: 8px 0 24px; }}
.serie-insight-row > .price-insight, .serie-insight-row > .serie-facts {{ margin: 0; }}
@media (min-width: 1024px) {{
  .serie-insight-row {{ grid-template-columns: 1.5fr 1fr; align-items: stretch; }}
}}
.serie-facts {{ background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); }}
.serie-facts h2 {{ margin: 0 0 12px; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }}
.serie-facts-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 11px; }}
.serie-facts-list li {{ display: flex; align-items: flex-start; gap: 10px; font-size: 0.86rem; }}
.serie-facts-list svg {{ flex-shrink: 0; width: 18px; height: 18px; color: var(--blue); margin-top: 1px; }}
.serie-facts-list strong {{ display: block; color: var(--ink); font-weight: 600; }}
.serie-facts-list span {{ display: block; font-size: 0.78rem; color: var(--muted); margin-top: 1px; }}
.price-insight {{ background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; margin: 8px 0 24px; box-shadow: var(--card-shadow); }}
.price-insight-head {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }}
.price-insight-head h2 {{ margin: 0; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }}
.insight-tabs {{ display: flex; gap: 4px; background: var(--mist); border-radius: 10px; padding: 3px; }}
.insight-tab {{ border: none; background: none; padding: 6px 14px; border-radius: 8px; font-size: 0.82rem; font-weight: 600; color: var(--muted); cursor: pointer; font-family: inherit; }}
.insight-tab.active {{ background: white; color: var(--ink); box-shadow: var(--card-shadow); }}
.price-insight-panel {{ display: none; }}
.price-insight-panel.active {{ display: grid; grid-template-columns: 1fr; gap: 18px; }}
.price-insight-current {{ font-family: 'Space Grotesk', sans-serif; font-size: 2.1rem; font-weight: 700; color: var(--ink); }}
.price-insight-label {{ font-size: 0.82rem; color: var(--muted); margin-top: 2px; }}
.price-insight-trend {{ display: flex; align-items: center; gap: 6px; margin-top: 8px; font-weight: 700; font-size: 0.92rem; }}
.price-insight-trend-note {{ font-weight: 400; color: var(--muted); font-size: 0.8rem; }}
.insight-down {{ color: var(--mint); }}
.insight-up {{ color: var(--coral); }}
.insight-flat {{ color: var(--muted); }}
.price-insight-tiles {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 16px; }}
.price-insight-tile {{ background: var(--mist); border-radius: 10px; padding: 8px 6px; text-align: center; }}
.price-insight-tile strong {{ display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; }}
.price-insight-tile span {{ display: block; font-size: 0.66rem; color: var(--muted); margin-top: 2px; line-height: 1.3; }}
.price-insight-chart .price-history {{ margin-top: 0; }}
@media (min-width: 860px) {{
  .price-insight-panel.active {{ grid-template-columns: 1fr 1.3fr; align-items: center; }}
}}
.spec-table-card {{ background: white; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: var(--card-shadow); }}
.spec-table {{ width: 100%; border-collapse: collapse; }}
.spec-table th, .spec-table td {{ padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.88rem; }}
.spec-table thead th {{ font-family: 'Space Grotesk', sans-serif; color: var(--muted); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em; background: var(--mist); }}
.spec-table tbody tr:last-child td {{ border-bottom: none; }}
.spec-table tbody tr:hover {{ background: var(--mist); }}
.spec-table a {{ color: var(--blue); text-decoration: none; font-weight: 600; display: flex; align-items: center; gap: 10px; }}
.spec-row-thumb {{ width: 32px; height: 32px; border-radius: 7px; background: var(--mist); border: 1px solid var(--border); object-fit: contain; padding: 3px; box-sizing: border-box; flex-shrink: 0; }}
.product-ai-summary {{ background: var(--blue-tint); border-left: 4px solid var(--blue); border-radius: 0 10px 10px 0; padding: 12px 18px; margin: 16px 0; font-size: 0.95rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary p {{ margin: 0; }}
.private-label-explainer {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin: 20px 0; font-size: 0.92rem; line-height: 1.6; }}
/* "Felles for hele serien" (samme fakta som "Kort om X" ved Prisinnsikt,
   men i et kompakt ikon-rutenett Kai spesifikt ba om 2026-09-27 -- de to
   boksene dekker samme fakta med vilje, siden de har ulik rolle: én er
   følgesvenn til Prisinnsikt, den andre til Relevante guider lenger ned.) */
.serie-bottom-row {{ display: grid; grid-template-columns: 1fr; gap: 16px; margin-top: 24px; }}
@media (min-width: 900px) {{ .serie-bottom-row {{ grid-template-columns: 1fr 1fr; align-items: stretch; }} }}
/* Begge boksene i raden er nå et "matchende par" (Kai 2026-09-27: "riktig
   proporsjonert i høyde, boks rundt etc så det blir tilnærmet likt") --
   samme kort-stil (hvit boks, samme border/radius/skygge, samme
   h2-størrelse) på BÅDE .serie-facts-tiles og .serie-guides, og
   align-items:stretch over gjør at de alltid får samme høyde som
   hverandre (den høyeste av de to bestemmer). .serie-facts-tiles sitt
   innhold er kortere (én rad ikon-fliser), så selve flise-rutenettet
   sentreres vertikalt i den ledige plassen (margin-top/bottom:auto)
   i stedet for å henge øverst med et stort tomrom under. */
.serie-facts-tiles {{ background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); height: 100%; box-sizing: border-box; display: flex; flex-direction: column; }}
.serie-facts-tiles h2 {{ margin: 0 0 14px; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }}
.serie-facts-tiles-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 10px; margin-top: auto; margin-bottom: auto; }}
.serie-fact-tile {{ text-align: center; background: var(--mist); border: 1px solid var(--border); border-radius: 12px; padding: 14px 8px; }}
.serie-fact-tile-icon {{ width: 36px; height: 36px; border-radius: 50%; background: white; color: var(--blue); display: flex; align-items: center; justify-content: center; margin: 0 auto 8px; box-shadow: var(--card-shadow); }}
.serie-fact-tile-icon svg {{ width: 18px; height: 18px; }}
.serie-fact-tile-value {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.88rem; color: var(--ink); line-height: 1.25; }}
.serie-fact-tile-label {{ font-size: 0.72rem; color: var(--muted); margin-top: 2px; }}
.serie-fact-note {{ display: flex; gap: 8px; align-items: flex-start; margin-top: 14px; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }}
.serie-fact-note svg {{ flex-shrink: 0; width: 15px; height: 15px; margin-top: 1px; }}
/* "Relevante guider" -- bildekort (var ren ikon-kort-rutenett, se
   kommentaren i Python-koden over) -- fikk ALDRI en boks rundt seg selv,
   bare en bar overskrift + rutenett direkte på sidebakgrunnen, derfor
   mismatchet den synlig mot "Felles for hele serien" sin hvite boks.
   Samme kort-stil nå (se kommentaren over .serie-facts-tiles). */
.serie-guides {{ background: white; border: 1px solid var(--border); border-radius: 16px; padding: 20px 22px; box-shadow: var(--card-shadow); height: 100%; box-sizing: border-box; }}
.serie-guides h2 {{ margin: 0 0 14px; font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; }}
.guide-photo-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
@media (min-width: 640px) {{ .guide-photo-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
.guide-photo-card {{ display: block; background: white; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; text-decoration: none; color: var(--ink); box-shadow: var(--card-shadow); transition: transform 0.15s, box-shadow 0.15s; }}
.guide-photo-card:hover {{ transform: translateY(-2px); box-shadow: 0 10px 24px rgba(37, 99, 235, 0.14); }}
.guide-photo-card-image {{ aspect-ratio: 16 / 9; background: var(--mist); overflow: hidden; }}
.guide-photo-card-image img {{ width: 100%; height: 100%; object-fit: cover; }}
.guide-photo-card-body {{ padding: 12px 14px 14px; }}
.guide-photo-card-title {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.88rem; line-height: 1.35; }}
.guide-photo-card-link {{ font-size: 0.8rem; font-weight: 600; color: var(--blue); margin-top: 8px; }}
/* FAQ-regelmotor (2026-09-27) -- gruppert accordion, se
   _render_family_faq_accordion(). Egne klassenavn (faq-category*/
   faq-accordion-item/faq-chevron) i stedet for å endre .faq-item (den flate
   varianten brukes fortsatt på produkt-/forside-FAQ-er). */
.faq-category {{ margin-top: 22px; }}
.faq-category:first-child {{ margin-top: 0; }}
.faq-category-label {{ font-family: 'Space Grotesk', sans-serif; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 4px; }}
.faq-accordion-item {{ border-top: 1px solid var(--border); }}
.faq-accordion-item:last-child {{ border-bottom: 1px solid var(--border); }}
.faq-accordion-item summary {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; list-style: none; padding: 13px 0; font-weight: 600; font-size: 0.92rem; color: var(--ink); }}
.faq-accordion-item summary::-webkit-details-marker {{ display: none; }}
.faq-chevron {{ flex-shrink: 0; width: 16px; height: 16px; color: var(--muted); transition: transform 0.15s; }}
.faq-accordion-item[open] .faq-chevron {{ transform: rotate(180deg); }}
.faq-accordion-item p {{ margin: 0 0 15px; color: var(--muted); font-size: 0.88rem; line-height: 1.55; }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-product">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(family_name)}-serien</p>
  <div class="serie-hero">
    <div class="serie-hero-content">
      <div class="kicker">Produktserie</div>
      <h1>{escape(family_name)}-serien</h1>
      {intro}
    </div>
    <div class="serie-hero-media" aria-hidden="true">
      <picture>
        <source media="(min-width: 860px)" type="image/webp" srcset="/static/hero/serie-560.webp 560w, /static/hero/serie-840.webp 840w, /static/hero/serie-1120.webp 1120w" sizes="(min-width: 1200px) 560px, 44vw">
        <img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" alt="" width="560" height="304" loading="lazy" decoding="async">
      </picture>
    </div>
    <div class="serie-stat-pills">{stat_pills_html}</div>
  </div>
  {chain_html}
  {variant_finder_html}
  {insight_row_html}
  {ai_summary_html}

  {all_products_html}

  <h2>Sammenlign variantene</h2>
  <div class="spec-table-card">
  <div style="overflow-x:auto;">
  {comparison_table}
  </div>
  </div>

  <div class="serie-bottom-row">
    {felles_html}
    {guides_html}
  </div>
  {family_faq_html}

  <p class="disclosure">
    Prisene her er produktpriser uten frakt, sortert etter lavest pris. På hver
    produktside kan du slå på «Pris inkludert frakt» for å se totalprisen. Vi kan få
    provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Varer uten bekreftet lager kan ikke vinne «laveste pris», og hvert
    tilbud viser når det sist ble kontrollert.
  </p>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_private_label_index_page(labels: list[dict], products_by_id: dict, categories: dict, now: datetime | None = None) -> str:
    """Oversiktsside -- gruppert per optikerkjede, lenker videre til hver
    enkelt private label-side. Tabellformat (2026-08-30, byttet fra en
    product-tile-rutenett) -- bruker påpekte at rutenettet ble tungt/
    plasskrevende for 55 rader (og vokser), spesielt siden disse kortene
    ALDRI viser et ekte bilde (viser feil boks under feil navn -- se
    render_private_label_page() sin egen kommentar om akkurat dette), så
    bilde-plassen sto uansett ubrukt. En tabell er mer skannbar for det
    dette faktisk er: et oppslagsverk ("hva heter linsen egentlig"), ikke
    en browse-og-handle-side (det gjør /merke/ og /kontaktlinser/ allerede).
    Hver rad har fortsatt BEGGE lenkene som fantes i kort-versjonen: til
    vår egen private label-side (f.eks. /private-label/iwear-fit/) OG til
    det virkelige produktets egen side (f.eks. /kontaktlinser/biomedics/...)."""
    now = now or datetime.now(timezone.utc)

    by_chain: dict[str, list[dict]] = {}
    for label in labels:
        by_chain.setdefault(label["chain"], []).append(label)

    def render_row(chain: str, label: dict) -> str:
        real_product = products_by_id[label["real_product_id"]]
        offers = reconcile_product(real_product["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: (o["price_nok"], o["total"]), default=None)
        real_href = f'/kontaktlinser/{real_product["brand_slug"]}/{real_product["slug"]}/'
        pl_href = f'/private-label/{escape(label["slug"])}/'
        category_slug = real_product.get("category_slug", "")
        category_label = categories.get(category_slug, {}).get("label", "")
        price_cell = (
            f'{_fmt_kr(lowest["price_nok"])} <span style="color:var(--muted);font-size:0.8em;">hos {escape(lowest["retailer"])}</span>'
            if lowest else '<span style="color:var(--muted);">Ingen pris</span>'
        )
        return f"""<tr>
      <td><a href="{pl_href}" style="font-weight:600;color:var(--ink);text-decoration:none;">{escape(label["name"])}</a></td>
      <td><a href="{escape(real_href)}" style="color:var(--blue);text-decoration:none;">{escape(real_product["name"])}</a></td>
      <td>{escape(category_label)}</td>
      <td style="white-space:nowrap;">{price_cell}</td>
    </tr>"""

    sections_html = ""
    for chain in sorted(by_chain.keys()):
        chain_labels = sorted(by_chain[chain], key=lambda l: l["name"])
        rows = "\n".join(render_row(chain, l) for l in chain_labels)
        subbrand = PRIVATE_LABEL_SUBBRANDS.get(chain, chain)
        chain_anchor = chain.lower().replace(" ", "-")
        sections_html += f"""<h2 id="{escape(chain_anchor)}" style="scroll-margin-top:20px;">{escape(chain)} <a href="/merke/{escape(subbrand.lower())}/" style="font-size:0.75rem;font-weight:600;color:var(--blue);text-decoration:none;">Se {escape(subbrand)}-siden →</a></h2>
  <div style="overflow-x:auto;">
  <table class="pl-table">
    <thead><tr><th>Kjedens navn</th><th>Egentlig</th><th>Kategori</th><th>Fra pris</th></tr></thead>
    <tbody>
    {rows}
    </tbody>
  </table>
  </div>
"""

    intro = "Flere optikerkjeder selger kontaktlinser under sitt eget merkenavn, selv om linsen er identisk med et kjent produkt fra produsenten. Her finner du oversikten – hvilket navn hos hvilken kjede tilsvarer hvilket produkt vi allerede sammenligner priser på."

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{"@type": "ListItem", "position": 1, "name": "Hjem", "item": "{BASE_URL}/"}},
    {{"@type": "ListItem", "position": 2, "name": "Optikerkjedenes egne merker", "item": "{BASE_URL}/private-label/"}}
  ]
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Optikerkjedenes egne merker – Hva heter linsen egentlig? | Kontaktlinser.no</title>
<meta name="description" content="{escape(intro)}">
<link rel="canonical" href="{BASE_URL}/private-label/">
{_og_meta('Optikerkjedenes egne merker – Hva heter linsen egentlig? | Kontaktlinser.no', intro, BASE_URL + '/private-label/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.pl-table {{ width: 100%; min-width: 560px; border-collapse: collapse; background: white; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; font-size: 0.88rem; margin: 12px 0 28px; }}
.pl-table th, .pl-table td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; white-space: nowrap; }}
.pl-table th {{ background: var(--mist); font-family: 'Space Grotesk', sans-serif; font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--muted); }}
.pl-table tr:last-child td {{ border-bottom: none; }}
.pl-table tr:hover td {{ background: var(--mist); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › Optikerkjedenes egne merker</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Guide</div>
      <h1>Optikerkjedenes egne merker</h1>
      <p>{escape(intro)}</p>
    </div>
  </div>
  {sections_html}
  <p class="disclosure">
    Koblingene over er satt sammen basert på tilgjengelig informasjon om
    produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale
    med optikerkjedene nevnt her og kan ikke garantere at hver kobling
    stemmer i alle tilfeller. Bekreft alltid med din optiker før du bytter
    mellom disse navnene.
  </p>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""
