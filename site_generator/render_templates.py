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
from datetime import datetime, timezone
from html import escape

from offer import compute_shipping_nok

BASE_URL = "https://kontaktlinser.no"


def _og_meta(title: str, description: str, url: str, image: str | None = None) -> str:
    """Open Graph/Twitter Card-tagger, delt av alle sidetyper -- gjenbruker
    alltid samme tittel/beskrivelse som den vanlige <title>/<meta
    description> på siden, aldri egen tekst, slik at de to aldri kan komme
    ut av synk med hverandre. Faller tilbake til logoen når siden ikke har
    et eget produktbilde (kategori/merke/guide/forside osv.)."""
    img = image or f"{BASE_URL}/static/logo.png"
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
  .wrap-wide { max-width: 1200px; }
  .wrap-product { max-width: 1040px; }
}
.topbar { display: flex; align-items: center; justify-content: flex-start; gap: 32px; padding: 14px 20px; max-width: 760px; margin: 0 auto; flex-wrap: wrap; }
.topbar-logo { display: flex; align-items: center; text-decoration: none; }
.topbar-logo img { height: 30px; width: auto; display: block; mix-blend-mode: multiply; }
@media (min-width: 640px) { .topbar-logo img { height: 32px; } }
.topbar-nav { display: flex; gap: 6px; flex-wrap: wrap; }
.topbar-nav a { font-size: 0.95rem; font-weight: 600; text-decoration: none; color: var(--ink); }
.topbar-nav a:hover { color: var(--blue); }
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
  .mega-menu-rich:has(.mega-rich-grid-3col) { width: 720px; }
  .mega-menu-rich:has(.mega-rich-grid-2col) { width: 580px; }
  .mega-menu-rich:has(.mega-rich-grid-3col-plain) { width: 540px; }
  .mega-rich-grid-3col { grid-template-columns: 190px 210px 230px; }
  .mega-rich-grid-2col { grid-template-columns: 220px 1fr; }
  .mega-rich-grid-3col-plain { grid-template-columns: repeat(3, 150px); gap: 18px; }
}
.mega-rich-col { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mega-panel-kicker { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--blue); }
.mega-panel-heading { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.1rem; line-height: 1.3; color: var(--ink); margin: 4px 0 0; }
.mega-panel-text { font-size: 0.85rem; color: var(--muted); line-height: 1.5; margin: 6px 0 0; }
.mega-type-row { display: flex; align-items: center; gap: 12px; text-decoration: none; color: var(--ink); padding: 8px 10px; margin: 0 -10px; border-radius: 10px; transition: background 0.12s ease; }
.mega-type-row:hover { background: var(--mist); }
.mega-type-row-icon { flex-shrink: 0; width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.mega-type-row-icon svg { width: 18px; height: 18px; }
.mega-type-row-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.mega-type-row-label { font-weight: 600; font-size: 0.87rem; }
.mega-type-row-desc { font-size: 0.75rem; color: var(--muted); margin-top: 1px; }
.mega-type-row-chevron { flex-shrink: 0; width: 15px; height: 15px; color: var(--muted); }
.mega-brand-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.mega-brand-card { display: flex; flex-direction: column; align-items: center; gap: 8px; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 8px; transition: border-color 0.15s; text-align: center; }
.mega-brand-card:hover { border-color: var(--blue); }
.mega-brand-card-logo { display: flex; align-items: center; justify-content: center; width: 100%; height: 30px; }
.mega-brand-card-logo img { max-width: 100%; max-height: 100%; object-fit: contain; }
.mega-brand-card-logo.has-logo-dark { background: var(--ink); border-radius: 6px; padding: 4px; }
.mega-brand-card-fallback { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.9rem; color: var(--blue); }
.mega-brand-card-name { font-size: 0.75rem; font-weight: 600; color: var(--muted); }
.mega-promo-card { display: flex; flex-direction: column; justify-content: flex-end; min-height: 150px; border-radius: 14px; background-size: cover; background-position: center; padding: 16px; color: white !important; text-decoration: none; }
.mega-promo-title { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; line-height: 1.25; }
.mega-promo-text { font-size: 0.78rem; opacity: 0.92; margin-top: 4px; }
.mega-promo-cta { display: inline-block; margin-top: 10px; background: white; color: var(--blue); font-weight: 700; font-size: 0.78rem; padding: 7px 12px; border-radius: 999px; width: fit-content; }
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
/* Under 700px er .mega-menu ellers venstre-forankret til SIN EGEN
   nav-item-knapp (position:absolute; left:0 relative til .nav-item) -- for
   en knapp langt til høyre i navigasjonen (f.eks. "Guider") skyter en
   380-720px bred meny da langt utenfor et ~360-400px mobilvindu. Låser i
   stedet menyen til viewporten med position:fixed og faste sidemarger, og
   JS-en i TOPBAR_HTML sitt <script> (closeAll()/trigger-click) setter
   inline top= like under selve topbaren ved åpning -- position:fixed sin
   top er alltid viewport-relativ, så getBoundingClientRect().bottom
   fungerer uendret uansett scroll-posisjon. top:70px under er kun et
   statisk fallback-tall for det (usannsynlige) tilfellet JS ikke kjører.
   Klarer nav-item bevisst IKKE position:static her -- feil forankrings-
   kontekst ville kun flyttet problemet et hakk (fortsatt konteksten til
   den enkelte knappen), position:fixed løser det uansett hvilken knapp
   som er trigger. */
@media (max-width: 699px) {
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
.lowest-tag { font-size: 0.75rem; font-weight: 600; color: white; background: var(--mint); padding: 2px 7px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.03em; }
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
.product-thumb { width: 52px; height: 52px; border-radius: 50%; background: var(--blue-tint); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.9rem; color: var(--blue); flex-shrink: 0; overflow: hidden; }
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
  .topbar, .footer-inner, .footer-disclosure, .footer-bottom { max-width: 1200px; }
}
.product-tile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 18px; margin-bottom: 8px; }
.product-tile { display: flex; flex-direction: column; background: white; border: 1px solid var(--border); border-radius: 16px; overflow: hidden; box-shadow: 0 6px 18px rgba(11, 37, 69, 0.06); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease; }
.product-tile:hover { transform: translateY(-3px); border-color: #B9C9DD; box-shadow: 0 10px 28px rgba(11, 37, 69, 0.11); }
.product-tile-image-link { display: block; text-decoration: none; }
.product-tile-image { height: 190px; margin: 14px 14px 0; border-radius: 12px; background: var(--mist); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.product-tile-image.has-photo { background: var(--mist); }
.product-tile-image img { display: block; width: 86%; max-height: 150px; object-fit: contain; mix-blend-mode: multiply; }
.product-tile-fallback { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.8rem; color: var(--blue); }
.product-tile-body { padding: 16px 18px 0; flex-grow: 1; display: flex; flex-direction: column; }
.product-tile-category { display: inline-block; align-self: flex-start; margin-bottom: 10px; padding: 5px 8px; border-radius: 999px; background: var(--blue-tint); color: var(--blue); font-size: 0.75rem; line-height: 1; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; }
.product-tile-name-link { text-decoration: none; color: var(--ink); }
.product-tile-name-link .product-name { font-size: 1.05rem; line-height: 1.35; font-weight: 700; min-height: 2.7em; }
.product-tile-manufacturer { display: block; margin-top: 6px; font-size: 0.85rem; color: var(--muted); text-decoration: none; }
.product-tile-manufacturer:hover { text-decoration: underline; }
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
  })(window,document,'script','dataLayer','GTM-KGPF68');
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
CATEGORY_TAGLINES = {
    "manedslinser": "Populær og kostnadseffektiv",
    "dagslinser": "Friske linser hver dag",
    "toriske-linser": "For deg med astigmatisme",
    "fargede-linser": "Endre eller forsterk øyefargen",
    "multifokale-linser": "For nær, mellom og fjern",
}

_SHIELD_ICON = '<path d="M12 3l7 3v5c0 5-3.2 7.8-7 9-3.8-1.2-7-4-7-9V6z"/><path d="M9 12l2 2 4-4"/>'
_BUILDING_ICON = '<path d="M3 21V10l6-4 6 4v11"/><path d="M9 21v-5h4v5"/><path d="M15 21V13l6-3v11"/>'
_BOOK_ICON = '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
_CALENDAR_ICON = '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>'


def _mega_type_row(slug: str, label: str) -> str:
    """Samme visuelle mønster som forsidens kategori-rader (farget
    ikon-sirkel + tittel + undertekst + pil), men egen CSS-klasse
    (.mega-type-row, ikke .category-row) -- TOPBAR_HTML ligger i HVER
    sides <body>, inkludert forsiden selv, så hadde denne gjenbrukt
    .category-row rett av ville forsidens egen @media(1024px)-variant
    (vertikalt sentrerte kolonne-kort) utilsiktet også truffet
    dropdown-menyen når den vises der."""
    icon = CATEGORY_ICONS.get(slug, "")
    color = CATEGORY_COLORS.get(slug, "blue")
    tagline = CATEGORY_TAGLINES.get(slug, "")
    return f'''<a class="mega-type-row" href="/kontaktlinser/{slug}/">
          <span class="mega-type-row-icon" style="background:var(--{color}-tint);color:var(--{color});"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">{icon}</svg></span>
          <span class="mega-type-row-text"><span class="mega-type-row-label">{label}</span><span class="mega-type-row-desc">{tagline}</span></span>
          <svg class="mega-type-row-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
        </a>'''


def _mega_brand_card(slug: str, name: str) -> str:
    """Merkekort med ekte logo der vi har en (BRAND_LOGOS) -- samme
    nominativ-varemerke-prinsipp som resten av siden. Mangler merket egen
    logo, vises produsentens logo (f.eks. Alcon for Precision1/Dailies/Air
    Optix), akkurat som på selve merkesiden -- aldri en oppdiktet logo."""
    cls, content = _brand_badge(slug, name)
    logo_cls = "mega-brand-card-logo " + cls if cls else "mega-brand-card-logo mega-brand-card-fallback"
    return f'''<a class="mega-brand-card" href="/merke/{slug}/">
          <span class="{logo_cls}">{content}</span>
          <span class="mega-brand-card-name">{escape(name)}</span>
        </a>'''


def _mega_link_row(icon_svg: str, label: str, sublabel: str, href: str) -> str:
    """Rad med lite ikon + tittel + undertekst + pil -- til 'Bla etter
    produsent'/'Nyttig å vite'-listene i dropdownene. Alle href-er som
    bruker denne MÅ peke til en side som faktisk finnes -- ikke gjett."""
    return f'''<a class="mega-link-row" href="{href}">
          <span class="mega-link-row-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon_svg}</svg></span>
          <span class="mega-link-row-text"><span class="mega-link-row-label">{label}</span><span class="mega-link-row-sub">{sublabel}</span></span>
          <svg class="mega-link-row-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
        </a>'''


_MEGA_TOP_BRANDS = [
    ("biofinity", "Biofinity"), ("acuvue", "Acuvue"), ("air-optix", "Air Optix"),
    ("dailies", "Dailies"), ("precision1", "Precision1"), ("biotrue", "Biotrue"),
]
_MEGA_BRAND_CARDS_HTML = "\n        ".join(_mega_brand_card(s, n) for s, n in _MEGA_TOP_BRANDS)

_MEGA_CATEGORIES = [
    ("dagslinser", "Dagslinser"), ("manedslinser", "Månedslinser"),
    ("toriske-linser", "Toriske linser"), ("fargede-linser", "Fargede linser"),
    ("multifokale-linser", "Multifokale linser"),
]
_MEGA_TYPE_ROWS_HTML = "\n        ".join(_mega_type_row(s, n) for s, n in _MEGA_CATEGORIES)

_MEGA_MANUFACTURER_LINKS_HTML = "\n        ".join(_mega_link_row(_BUILDING_ICON, name, "Se merkene →", f"/produsent/{slug}/") for slug, name in [
    ("coopervision", "CooperVision"), ("alcon", "Alcon"),
    ("bausch-lomb", "Bausch + Lomb"), ("jnj-vision", "Johnson & Johnson Vision"),
])

_MEGA_USEFUL_LINKS_HTML = "\n        ".join([
    _mega_link_row(_SHIELD_ICON, "Optikerkjedenes varemerker", "Samme linse, andre navn", "/private-label/"),
    _mega_link_row(_BOOK_ICON, "Hvordan velge riktig linse?", "Guide", "/guide/hvordan-velge-kontaktlinser/"),
    _mega_link_row(_CALENDAR_ICON, "Linseabonnement", "Abonnement vs. kjøpe selv", "/guide/kontaktlinseabonnement-vs-kjope-selv/"),
])

TOPBAR_HTML = f"""<div class="topbar">
  <a href="/" class="topbar-logo"><picture><source srcset="/static/logo.webp" type="image/webp"><img src="/static/logo.png" alt="Kontaktlinser.no" width="700" height="79" loading="eager"></picture></a>
  <nav class="topbar-nav">
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Kontaktlinser <span class="nav-caret">▾</span></button>
      <div class="mega-menu mega-menu-rich">
        <div class="mega-rich-grid mega-rich-grid-3col">
          <div class="mega-rich-col">
            <div class="mega-panel-kicker">Finn kontaktlinser</div>
            <div class="mega-panel-heading">Velg riktig linsetype for dine behov</div>
            <div class="mega-col-title" style="margin-top:18px;">Etter type</div>
            {_MEGA_TYPE_ROWS_HTML}
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Populære merker</div>
            <div class="mega-brand-grid">
              {_MEGA_BRAND_CARDS_HTML}
            </div>
            <a class="mega-menu-link mega-see-all" href="/#merker">Se alle merker →</a>
          </div>
          <div class="mega-rich-col">
            <a class="mega-promo-card" href="/guide/hvordan-velge-kontaktlinser/" style="background-image:linear-gradient(180deg, rgba(11,37,69,0.1), rgba(11,37,69,0.82)), url('/static/hero-eye.jpg');">
              <span class="mega-promo-title">Finn den perfekte linsen for deg</span>
              <span class="mega-promo-text">Sammenlign priser fra norske nettbutikker</span>
              <span class="mega-promo-cta">Utforsk guiden →</span>
            </a>
            <div class="mega-col-title" style="margin-top:18px;">Nyttig å vite</div>
            {_MEGA_USEFUL_LINKS_HTML}
          </div>
        </div>
        <a class="mega-menu-link mega-see-all" href="/#kategorier">Se alle kontaktlinser →</a>
      </div>
    </div>
    <div class="nav-item">
      <button type="button" class="nav-trigger" aria-haspopup="true" aria-expanded="false">Merker <span class="nav-caret">▾</span></button>
      <div class="mega-menu mega-menu-rich">
        <div class="mega-rich-grid mega-rich-grid-2col">
          <div class="mega-rich-col">
            <div class="mega-panel-kicker">Merker</div>
            <div class="mega-panel-heading">Bla i alle kontaktlinsemerker</div>
            <p class="mega-panel-text">Utforsk populære merker, eller søk etter produsent.</p>
            <div class="mega-col-title" style="margin-top:18px;">Bla etter produsent</div>
            {_MEGA_MANUFACTURER_LINKS_HTML}
          </div>
          <div class="mega-rich-col">
            <div class="mega-col-title">Populære merker</div>
            <div class="mega-brand-grid">
              {_MEGA_BRAND_CARDS_HTML}
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
</div>
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
          // Kun under 700px-brytpunktet (se .mega-menu sin @media (max-width:
          // 699px) i SHARED_STYLE) -- der er menyen position:fixed og trenger
          // en presis top= like under topbaren, siden CSS-en sitt statiske
          // fallback-tall (70px) ikke tar høyde for at logo+navigasjon kan
          // brytes til to linjer på svært smale skjermer.
          if (topbarEl && window.innerWidth < 700) {{
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
}})();
</script>"""

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
    "/produkt/1-day-acuvue-moist-multifocal.aspx": "/kontaktlinser/acuvue/moist-multifocal-30-pack/",
    "/produkt/1-day_acuvue.aspx": "/merke/acuvue/",
    "/produkt/1-day_acuvue_for_astigmatism.aspx": "/merke/acuvue/",
    "/produkt/1-day_acuvue_moist.aspx": "/kontaktlinser/acuvue/moist-30-pack/",
    "/produkt/1-day_acuvue_moist_for_astigmatism.aspx": "/kontaktlinser/acuvue/moist-astigmatism-30-pack/",
    "/produkt/1-day_acuvue_trueye.aspx": "/merke/acuvue/",
    "/produkt/acuvue.aspx": "/merke/acuvue/",
    "/produkt/acuvue_2.aspx": "/merke/acuvue/",
    "/produkt/acuvue_2_colours_enhancers.aspx": "/merke/acuvue/",
    "/produkt/acuvue_2_colours_opaque.aspx": "/merke/acuvue/",
    "/produkt/acuvue_advance.aspx": "/merke/acuvue/",
    "/produkt/acuvue_advance_for_astigmatism.aspx": "/merke/acuvue/",
    "/produkt/acuvue_bifocal.aspx": "/merke/acuvue/",
    "/produkt/acuvue_oasys.aspx": "/kontaktlinser/acuvue/oasys-6-pack/",
    "/produkt/acuvue_oasys_for_astigmatism.aspx": "/kontaktlinser/acuvue/oasys-astigmatism-6-pack/",
    "/produkt/adore_bi-tone.aspx": "/kontaktlinser/adore/bi-tone-2-pack/",
    "/produkt/adore_dare.aspx": "/kontaktlinser/adore/dare-2-pack/",
    "/produkt/adore_tri-tone.aspx": "/merke/adore/",
    "/produkt/air-optix-colors.aspx": "/kontaktlinser/air-optix/colors-2-pack/",
    "/produkt/air-optix-ex.aspx": "/merke/air-optix/",
    "/produkt/air-optix-plus-hydraglyde.aspx": "/kontaktlinser/air-optix/air-optix-plus-hydraglyde-6-pack/",
    "/produkt/air_optix.aspx": "/merke/air-optix/",
    "/produkt/air_optix_aqua.aspx": "/merke/air-optix/",
    "/produkt/air_optix_aqua_multifocal.aspx": "/merke/air-optix/",
    "/produkt/air_optix_for_astigmatism.aspx": "/merke/air-optix/",
    "/produkt/air_optix_night_and_day.aspx": "/merke/air-optix/",
    "/produkt/air_optix_nightandday_aqua.aspx": "/kontaktlinser/air-optix/night-day-aqua-6-pack/",
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
    "/produkt/biomedics-1day-extra-toric.aspx": "/kontaktlinser/biomedics/biomedics-1-day-xtra-toric-30-pack/",
    "/produkt/biomedics-1day-extra.aspx": "/kontaktlinser/biomedics/biomedics-1-day-xtra-30-pack/",
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
    "/produkt/lensway_case.aspx": "/linsevaeske/",
    "/produkt/lensway_hand_desinfection_spray.aspx": "/",
    "/produkt/lensway_solution.aspx": "/linsevaeske/",
    "/produkt/mediflex_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/myday-daily-disposable.aspx": "/kontaktlinser/myday/myday-30-pack/",
    "/produkt/neoflex_toric.aspx": "/kontaktlinser/toriske-linser/",
    "/produkt/opti-free_ampuller.aspx": "/linsevaeske/",
    "/produkt/opti-free_express.aspx": "/linsevaeske/opti-free/express-120-ml/",
    "/produkt/opti-free_express_norub.aspx": "/linsevaeske/",
    "/produkt/opti-free_replenish.aspx": "/linsevaeske/",
    "/produkt/opti-tears_free_rewetting_drops.aspx": "/oyedraper/",
    "/produkt/optima_fw.aspx": "/",
    "/produkt/precision_uv.aspx": "/",
    "/produkt/proclear-multifocal-xr.aspx": "/kontaktlinser/proclear/multifocal-xr-3-pack/",
    "/produkt/proclear-toric-xr.aspx": "/kontaktlinser/proclear/toric-xr-3-pack/",
    "/produkt/proclear_1-day_multifocal.aspx": "/kontaktlinser/proclear/1-day-multifocal-30-pack/",
    "/produkt/proclear_1_day.aspx": "/kontaktlinser/proclear/1-day-30-pack/",
    "/produkt/proclear_compatibles.aspx": "/merke/proclear/",
    "/produkt/proclear_compatibles_toric.aspx": "/merke/proclear/",
    "/produkt/proclear_ep.aspx": "/merke/proclear/",
    "/produkt/proclear_multifocal.aspx": "/kontaktlinser/proclear/multifocal-6-pack/",
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
    "/produkt/renu_flight_pack.aspx": "/linsevaeske/",
    "/produkt/renu_multi-purpose.aspx": "/linsevaeske/renu/renu-multi-purpose-60-ml/",
    "/produkt/renu_onthego.aspx": "/linsevaeske/",
    "/produkt/s-75.aspx": "/",
    "/produkt/seequence.aspx": "/",
    "/produkt/soflens-natural-colors.aspx": "/merke/soflens/",
    "/produkt/soflens_38.aspx": "/kontaktlinser/soflens/38-6-pack/",
    "/produkt/soflens_59.aspx": "/kontaktlinser/soflens/soflens-59-6-pack/",
    "/produkt/soflens_66.aspx": "/merke/soflens/",
    "/produkt/soflens_daily_disposable.aspx": "/kontaktlinser/soflens/soflens-daily-disposable-30-pack/",
    "/produkt/soflens_daily_disposable_for_astigmatism.aspx": "/kontaktlinser/soflens/daily-disposable-for-astigmatism-30-pack/",
    "/produkt/soflens_multifocal.aspx": "/kontaktlinser/soflens/multifocal-6-pack/",
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
  </div>
  <p class="footer-disclosure">
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser
    automatisk fra forhandlernes egne nettsider hver 6. time og sorterer alltid
    etter lavest totalpris inkl. frakt. Vi kan motta provisjon når du handler via
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
}

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


def _fmt_kr(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ") + " kr"


def _render_product_tile(*, href: str, name: str, image_url: str | None, fallback_initials: str,
                          category_label: str | None, secondary_line_html: str,
                          lowest: dict | None, other_count: int, data_attr: str = "",
                          illustration_html: str | None = None) -> str:
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
    <div class="product-tile-divider"></div>
    <a class="product-tile-price-link" href="{href_esc}">{price_block}</a>
  </div>
  <a class="product-tile-cta" href="{href_esc}">Sammenlign priser →</a>
</div>"""


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


# Rangering blant forhandlere MED affiliate-avtale, brukt KUN til å avgjøre
# rekkefølge/vinner ved eksakt lik totalpris (aldri prisen selv). Lavere tall
# = vinner tidligere.
#
# Bruker bekreftet 2026-08-31: Lenson, Lensway og Shopping4net har alle
# IDENTISK provisjonssats (8 %) til oss. Ved eksakt lik totalpris gir
# derfor 8 % av samme kronebeløp samme reelle inntjening uansett hvilken
# av de tre som vinner -- ingen prioritering mellom dem er meningsfull
# eller nødvendig, så de er bevisst IKKE lagt inn her (alfabetisk
# fallback i _tie_break_key() gir like riktig resultat som noe annet
# ville gjort). Extra Optical og Apotekhjem sine satser er IKKE avklart
# ennå -- fyll inn når/hvis bruker oppgir dem, f.eks.
# {"Extra Optical": 0} hvis den skulle vise seg å ha høyere sats enn de
# tre andre.
AFFILIATE_TIE_PRIORITY: dict[str, int] = {}


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
    if image_url.startswith("/static/products/") and image_url.endswith(".jpg"):
        webp_url = image_url[:-4] + ".webp"
        return (f'<picture><source srcset="{escape(webp_url)}" type="image/webp">'
                f'<img{cls_attr} src="{escape(image_url)}" alt="{escape(alt)}" loading="{loading}"></picture>')
    return f'<img{cls_attr} src="{escape(image_url)}" alt="{escape(alt)}" loading="{loading}">'


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
CALENDAR_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3 9.5h18" stroke="currentColor" stroke-width="1.8"/><path d="M7 3v4M17 3v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'

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


def render_offer_card(o: dict, retailer: str, product_name: str | None = None) -> str:
    status_note = (
        '<div class="offer-meta" style="font-weight:600;">Utsolgt</div>' if not o["in_stock"]
        else '<div class="offer-meta" style="font-weight:600;">Pris ikke bekreftet siste 24t</div>' if o["is_stale"]
        else f'<div class="offer-meta">Sist oppdatert: {escape(_time_ago(o["checked_at"], datetime.now(timezone.utc)))}</div>'
    )
    css_class = "offer-card" + (" is-lowest" if o["is_lowest"] else "") + (" is-muted" if not o["in_stock"] else "")
    lowest_tag = '<span class="lowest-tag">Lavest totalpris</span>' if o["is_lowest"] else ""
    # Produktprisen er hovedtallet (stort), frakt en egen liten linje over --
    # samme mønster som Prisjakt/Klarna bruker, som er det norske brukere er
    # vant til å lese. Vi dropper en egen "Totalt X kr"-linje per rad (var
    # opplevd som støy -- tre tall stablet oppå hverandre på hvert kort);
    # seksjonsoverskriften over lista sier allerede at den er sortert etter
    # totalpris, og toppbanneret viser vinnerens totalsum -- "Lavest pris"-
    # merket (ALLTID totalpris-basert, se reconcile()) er dermed fortsatt
    # etterprøvbart uten at hvert enkelt kort må gjenta regnestykket.
    shipping_text = _shipping_note(o["shipping_nok"], o.get("shipping_policy"))
    rel = "sponsored nofollow" if o["source"] == "affiliate_feed" else "nofollow"
    price_label = (
        f'Gå til {escape(retailer)} for {escape(product_name)}, {_fmt_kr(o["price_nok"])}'
        if product_name else f'Se hos {escape(retailer)}, {_fmt_kr(o["price_nok"])}'
    )

    # Hele kortet er selve lenken (ikke bare pris-pillen) -- små knapper er
    # vonde touch-mål på mobil, og det gir uansett bare ett meningsfullt sted
    # å klikke per rad. price-pill er derfor et <span>, ikke en egen <a> --
    # nøstede <a>-tagger er ugyldig HTML og ville brutt visningen.
    return f"""<a class="{css_class}" href="{escape(o["url"])}" rel="{rel}" aria-label="{price_label}" data-retailer="{escape(retailer)}">
  <div class="offer-main">
    <div class="offer-retailer">{_retailer_badge_html(retailer)} {lowest_tag}</div>
    {status_note}
  </div>
  <div class="offer-price-col">
    <div class="offer-shipping">{TRUCK_ICON_SVG}<span class="offer-shipping-text">{escape(shipping_text)}</span></div>
    <span class="price-pill">{_fmt_kr(o["price_nok"])}</span>
  </div>
</a>"""


_QTY_CALC_SCRIPT = r"""<script>
(function () {
  var dataEl = document.getElementById('qty-offers-data');
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);
  var productName = dataEl.getAttribute('data-product-name') || '';
  var unitSingular = dataEl.getAttribute('data-unit-singular') || 'eske';
  var unitPlural = dataEl.getAttribute('data-unit-plural') || 'esker';
  var pills = document.querySelectorAll('.qty-pill');
  var customRow = document.getElementById('qty-custom-row');
  var customInput = document.getElementById('qty-custom-input');
  var labelEl = document.getElementById('winner-label');
  var retailerEl = document.getElementById('winner-retailer');
  var shippingEl = document.getElementById('winner-shipping');
  var winnerLink = document.getElementById('winner-band-link');
  var pricePill = document.getElementById('winner-price-pill');

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
  function findCard(offerCards, retailer) {
    for (var i = 0; i < offerCards.length; i++) {
      if (offerCards[i].getAttribute('data-retailer') === retailer) return offerCards[i];
    }
    return null;
  }

  function update(qty) {
    if (!qty || qty < 1) return;
    // Slås opp på nytt hver gang i stedet for én gang ved skript-kjøring --
    // dette scriptet ligger FØR .offers i selve HTML-kildekoden (siden
    // vinner-widgeten står øverst på siden), så et oppslag ved lasting ville
    // alltid funnet 0 kort. update() kalles uansett kun etter klikk, lenge
    // etter at hele siden er ferdig lastet.
    var offersList = document.querySelector('.offers');
    var offerCards = offersList ? offersList.querySelectorAll('.offer-card') : [];
    var results = [];
    for (var i = 0; i < data.length; i++) {
      var o = data[i];
      var productTotal = o.price_nok * qty;
      var shipping = computeShipping(productTotal, o.shipping_policy);
      results.push({ o: o, productTotal: productTotal, shipping: shipping, total: productTotal + shipping });
    }

    var best = null;
    for (var i = 0; i < results.length; i++) {
      var r = results[i];
      if (r.o.in_stock && (!best || r.total < best.total)) best = r;
    }
    if (best) {
      labelEl.textContent = 'Billigst akkurat nå for ' + qty + ' ' + (qty === 1 ? unitSingular : unitPlural);
      retailerEl.innerHTML = retailerBadge(best.o);
      shippingEl.textContent = shippingNote(best.shipping, best.o.shipping_policy);
      pricePill.textContent = fmtKr(best.total);
      // winner-band-link ER lenken (se render_winner_widget) -- href/rel/
      // aria-label hører hjemme der, ikke på price-pill-spannet inni.
      winnerLink.setAttribute('href', best.o.url);
      winnerLink.setAttribute('rel', best.o.rel);
      winnerLink.setAttribute('aria-label', 'Gå til ' + best.o.retailer + (productName ? ' for ' + productName : '') + ', ' + fmtKr(best.total) + ' totalt inkl. frakt');
    }

    if (offersList && offerCards.length) {
      results.sort(function (a, b) { return a.total - b.total; });
      for (var i = 0; i < results.length; i++) {
        var r = results[i];
        var card = findCard(offerCards, r.o.retailer);
        if (!card) continue;
        var pricePillEl = card.querySelector('.price-pill');
        if (pricePillEl) pricePillEl.textContent = fmtKr(r.productTotal);
        // card ER lenken (se render_offer_card) -- aria-label hører hjemme
        // på card selv, ikke på price-pill-spannet inni.
        card.setAttribute('aria-label', 'Gå til ' + r.o.retailer + (productName ? ' for ' + productName : '') + ', ' + fmtKr(r.productTotal));
        var shipTextEl = card.querySelector('.offer-shipping-text');
        if (shipTextEl) shipTextEl.textContent = shippingNote(r.shipping, r.o.shipping_policy);
        var isWinner = !!(best && r.o.retailer === best.o.retailer);
        card.classList.toggle('is-lowest', isWinner);
        var existingTag = card.querySelector('.lowest-tag');
        if (isWinner && !existingTag) {
          var retailerDiv = card.querySelector('.offer-retailer');
          if (retailerDiv) retailerDiv.insertAdjacentHTML('beforeend', ' <span class="lowest-tag">Lavest totalpris</span>');
        } else if (!isWinner && existingTag) {
          existingTag.remove();
        }
        offersList.appendChild(card);
      }
    }
  }

  for (var i = 0; i < pills.length; i++) {
    pills[i].addEventListener('click', function (e) {
      for (var j = 0; j < pills.length; j++) { pills[j].classList.remove('is-active'); }
      e.currentTarget.classList.add('is-active');
      var qty = e.currentTarget.getAttribute('data-qty');
      if (qty === 'custom') {
        customRow.hidden = false;
        customInput.focus();
        var v = parseInt(customInput.value, 10);
        if (v) update(v);
      } else {
        customRow.hidden = true;
        update(parseInt(qty, 10));
      }
    });
  }
  customInput.addEventListener('input', function () {
    update(parseInt(customInput.value, 10));
  });
})();
</script>"""


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
      <div class="methodology-row"><dt>Sortering</dt><dd>Butikkene sorteres etter lavest totalpris. Derfor kan butikken med lavest produktpris være en annen enn butikken med lavest totalpris.</dd></div>
      <div class="methodology-row"><dt>Oppdatering</dt><dd>Prisene hentes automatisk og oppdateres hver 6. time.</dd></div>
    </dl>
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
.qty-box { background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }
.qty-box-title { font-weight: 600; font-size: 0.92rem; margin-bottom: 10px; }
.qty-pills { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
@media (min-width: 640px) { .qty-pills { grid-template-columns: repeat(6, 1fr); } }
.qty-pill { display: flex; flex-direction: column; align-items: center; gap: 3px; font-family: 'IBM Plex Mono', monospace; background: linear-gradient(180deg, #FFFFFF 0%, var(--mist) 100%); border: 1px solid var(--border); border-radius: 10px; padding: 10px 6px; font-size: 0.9rem; font-weight: 600; text-align: center; cursor: pointer; color: var(--ink); line-height: 1.3; box-shadow: 0 3px 0 #C4D2D9, 0 4px 6px rgba(11,37,69,0.12); transition: transform 0.08s ease, box-shadow 0.08s ease; }
.qty-pill:active { transform: translateY(2px); box-shadow: 0 1px 0 #C4D2D9, 0 2px 3px rgba(11,37,69,0.1); }
.qty-pill svg { width: 20px; height: 20px; color: var(--blue); }
.qty-pill span { font-size: 0.75rem; font-weight: 400; color: var(--muted); }
.qty-pill.is-active { background: linear-gradient(180deg, #3ED4E4 0%, var(--blue) 100%); border-color: var(--blue); color: white; box-shadow: 0 3px 0 #1B95A3, 0 4px 6px rgba(11,37,69,0.18); }
.qty-pill.is-active:active { box-shadow: 0 1px 0 #1B95A3, 0 2px 3px rgba(11,37,69,0.15); }
.qty-pill.is-active svg { color: white; }
.qty-pill.is-active span { color: rgba(255,255,255,0.85); }
#qty-pill-custom { display: none; }
@media (min-width: 640px) { #qty-pill-custom { display: block; } }
.qty-custom-row { margin-top: 10px; }
#qty-custom-input { width: 140px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; }
.qty-tip { display: flex; align-items: flex-start; gap: 8px; background: var(--blue-tint); border-radius: 10px; padding: 10px 12px; font-size: 0.82rem; color: var(--ink); margin: 12px 0 0; line-height: 1.5; }
.qty-tip-icon { flex-shrink: 0; }
.qty-static-fallback { font-size: 0.75rem; color: var(--muted); line-height: 1.6; margin: 10px 0 0; opacity: 0.85; }
"""


def render_winner_widget(best: dict, offers: list[dict], product_name: str | None = None, unit_singular: str = "eske", unit_plural: str = "esker") -> tuple[str, str]:
    """Returnerer (winner_band, qty_box) som ETT tuple i stedet for én
    sammenslått streng -- render_product_page sin nye hero-layout plasserer
    trofé-boksen (winner_band) INNE i hero-kortet, mens antallsvelgeren
    (qty_box) fortsatt ligger som egen seksjon under, slik den alltid har
    gjort. De to andre kallerne (render_solution_product_page,
    render_private_label_page) limer dem ganske enkelt sammen igjen med
    "\\n" akkurat som før -- ingen visuell endring der.

    Toppwidget som erstatter den gamle statiske "Laveste totalpris"-
    banneren: viser billigste totalpris for valgt antall enheter, med en
    kompakt antallsvelger (1/2/4/6/10/eget antall) som regner om vinneren
    live via JS. unit_singular/unit_plural lar kontaktlinse-sider si "eske"/
    "esker" (standard) mens linsevæske-/øyedråpesider (render_solution_
    product_page) sier "flaske"/"flasker" -- samme widget, samme trofé,
    samme klikkbare heldekkende ramme, kun ordet for hva man kjøper flere av
    er ulikt.

    Standardtilstanden (1 enhet) er ALLTID ekte, ferdig-rendret HTML, og det
    samme er 2/4/10-eksemplene i den statiske oppsummeringen under velgeren
    -- mange AI-crawlere (GPTBot, ClaudeBot, PerplexityBot m.fl.) kjører ikke
    JavaScript, og skal likevel kunne lese disse tallene rett i kildekoden.

    Fraktkostnaden regnes på nytt per antall (compute_shipping_nok), ikke
    bare multiplisert med shipping_nok for én enhet -- en fri-frakt-grense
    som ikke er nådd ved 1 enhet kan fint være nådd ved 4, og gir da en
    annen vinner enn ved enkeltkjøp."""
    if not best:
        return "", ""

    rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
    shipping_note = _shipping_note(best["shipping_nok"], best.get("shipping_policy"))
    winner_aria = (
        f'Gå til {escape(best["retailer"])} for {escape(product_name)}, {_fmt_kr(best["total"])} totalt inkl. frakt'
        if product_name else f'Gå til {escape(best["retailer"])}, {_fmt_kr(best["total"])} totalt inkl. frakt'
    )

    # Hele banneret er selve lenken (ikke bare pris-pillen) -- samme
    # begrunnelse som render_offer_card: små knapper er vonde touch-mål på
    # mobil. price-pill er derfor et <span> her, ikke en egen <a>.
    winner_band = f"""<a class="winner-band" id="winner-band-link" href="{escape(best["url"])}" rel="{rel}" aria-label="{winner_aria}">
  <div class="winner-left">
    <div class="winner-trophy" aria-hidden="true">{TROPHY_ICON_SVG}</div>
    <div class="label-group">
      <div class="label" id="winner-label">Billigst akkurat nå for 1 {escape(unit_singular)}</div>
      <div class="retailer" id="winner-retailer">{_retailer_badge_html(best["retailer"])}</div>
      <div class="winner-shipping" id="winner-shipping">{escape(shipping_note)}</div>
    </div>
  </div>
  <div class="winner-price-group">
    <span class="price-pill is-winner" id="winner-price-pill">{_fmt_kr(best["total"])}</span>
    <div class="winner-price-note">Totalpris inkl. frakt</div>
    <span class="winner-cta" aria-hidden="true">Til butikken <span class="winner-cta-arrow">&#8594;</span></span>
  </div>
</a>"""

    eligible = [o for o in offers if o["in_stock"]]
    if len(eligible) < 2:
        return winner_band, ""  # ingen reell antalls-sammenligning å tilby med 0-1 tilbud

    def total_for_qty(o: dict, qty: int) -> float:
        product_total = o["price_nok"] * qty
        return product_total + compute_shipping_nok(product_total, o.get("shipping_policy"))

    pills = "".join(
        f'<button type="button" class="qty-pill{" is-active" if qty == 1 else ""}" data-qty="{qty}">{BOX_ICON_SVG}{qty}<span>{escape(unit_singular) if qty == 1 else escape(unit_plural)}</span></button>'
        for qty in (1, 2, 4, 6, 10)
    )
    pills += f'<button type="button" class="qty-pill" data-qty="custom" id="qty-pill-custom">{PENCIL_ICON_SVG}Eget<span>antall</span></button>'

    fallback_parts = []
    for qty in (2, 4, 10):
        best_o = min(eligible, key=lambda o: total_for_qty(o, qty))
        qty_shipping = compute_shipping_nok(best_o["price_nok"] * qty, best_o.get("shipping_policy"))
        note = _shipping_note(qty_shipping, best_o.get("shipping_policy"))
        fallback_parts.append(
            f'Ved {qty} {escape(unit_plural)}: billigst hos {escape(best_o["retailer"])} – {_fmt_kr(total_for_qty(best_o, qty))} totalt inkl. frakt ({note.lower()}).'
        )
    static_fallback_html = f'<p class="qty-static-fallback">{" ".join(fallback_parts)}</p>'

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
            "url": o["url"],
            "rel": "sponsored nofollow" if o["source"] == "affiliate_feed" else "nofollow",
            "logo_file": logo_entry[0] if logo_entry else None,
            "logo_dark": logo_entry[1] if logo_entry else False,
            "in_stock": o["in_stock"],
            "is_stale": o["is_stale"],
        })
    calc_offers_json = json.dumps(calc_offers, ensure_ascii=False).replace("</", "<\\/")

    qty_box = f"""<div class="qty-box">
    <div class="qty-box-title">Hvor mange {escape(unit_plural)} trenger du?</div>
    <div class="qty-pills" id="qty-pills">{pills}</div>
    <div class="qty-custom-row" id="qty-custom-row" hidden>
      <input type="number" id="qty-custom-input" min="1" max="50" inputmode="numeric" placeholder="Antall {escape(unit_plural)}">
    </div>
    <p class="qty-tip"><span class="qty-tip-icon" aria-hidden="true">💡</span><span><strong>Tips:</strong> billigste butikk kan endre seg når du kjøper flere {escape(unit_plural)}, på grunn av ulike fraktgrenser.</span></p>
  </div>
  {static_fallback_html}
  <script type="application/json" id="qty-offers-data" data-product-name="{escape(product_name or '')}" data-unit-singular="{escape(unit_singular)}" data-unit-plural="{escape(unit_plural)}">{calc_offers_json}</script>
  {_QTY_CALC_SCRIPT}"""

    return winner_band, qty_box


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


def _render_price_history_chart(history: list[dict]) -> str:
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
        tooltip = f"{short_date(h['date'])}: {_fmt_kr(h['price'])} hos {escape(h['store'])}"
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

    return f"""<div class="price-history">
    <h2>Prisutvikling</h2>
    <p class="price-history-summary">Laveste produktpris (uten frakt) siste {n} dager: {_fmt_kr(real_min)}.</p>
    <svg viewBox="0 0 {width} {height}" class="price-history-chart" role="img" aria-label="Prisutvikling siste {n} dager, fra {_fmt_kr(real_min)} til {_fmt_kr(real_max)}">
      <defs>
        <linearGradient id="priceHistoryFade" x1="0" y1="{pad_top}" x2="0" y2="{baseline_y}" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#F0740F" stop-opacity="0.38" />
          <stop offset="100%" stop-color="#FB923C" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      {axis_html}
      <path d="{area_path}" class="price-history-area" />
      <polyline points="{line_points}" class="price-history-line" />
      {dots_svg}
      <text x="{x_for(n - 1):.1f}" y="{last_label_y:.1f}" text-anchor="{last_label_anchor}" class="price-history-current-label">{escape(_fmt_kr(last["price"]))}</text>
      {date_axis_html}
    </svg>
  </div>"""


def render_product_page(product: dict, categories: dict, products_by_id: dict | None = None, price_history: list[dict] | None = None, now: datetime | None = None, aliases: list[dict] | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    image_url = _product_image(product)

    pack_size_callout = ""
    parsed = _pack_size_from_id(product["id"])
    siblings: list[tuple[int, dict]] = []
    if parsed and best and products_by_id:
        base_stem, pack_size = parsed
        for pid, p in products_by_id.items():
            if pid == product["id"]:
                continue
            p_parsed = _pack_size_from_id(pid)
            if p_parsed and p_parsed[0] == base_stem:
                siblings.append((p_parsed[1], p))
        if siblings:
            siblings.sort(key=lambda s: abs(s[0] - pack_size))
            sibling_pack_size, sibling = siblings[0]
            sibling_offers = reconcile_product(sibling["offers"], now)
            sibling_eligible = [o for o in sibling_offers if o["in_stock"]]
            sibling_best = min(sibling_eligible, key=lambda o: o["total"], default=None)
            if sibling_best:
                this_per_lens = best["total"] / pack_size
                sibling_per_lens = sibling_best["total"] / sibling_pack_size
                sibling_href = f'/kontaktlinser/{sibling["brand_slug"]}/{sibling["slug"]}/'
                diff_pct = abs(sibling_per_lens - this_per_lens) / this_per_lens * 100
                if diff_pct < 1:
                    comparison = "omtrent samme pris per linse"
                else:
                    retning = "billigere" if sibling_per_lens < this_per_lens else "dyrere"
                    comparison = f"{diff_pct:.0f} % {retning} per linse"
                per_lens_str = f"{sibling_per_lens:.2f}".replace(".", ",") + " kr/linse"
                pack_size_callout = f"""<a class="pack-size-callout" href="{escape(sibling_href)}">
  <div class="pack-size-callout-text">
    Finnes også i <strong>{sibling_pack_size}-pakning</strong> — {per_lens_str} ({comparison})
  </div>
  <div class="pack-size-callout-arrow">→</div>
</a>"""

    thumb = _img_tag(image_url, product["name"], loading="eager") if image_url \
        else escape(product["brand_label"][:2].upper())

    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"], product["name"]) for o in offers)

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(product["name"])}</strong> fra {len(product["offers"])} norske nettbutikker. Fra <strong>{_fmt_kr(best["price_nok"])}</strong> hos {escape(best["retailer"])} (ekskl. frakt). Kontaktlinser.no er en uavhengig sammenligningstjeneste - vi viser full totalpris inkludert frakt i sammenligningen under.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne linsen akkurat nå. Prisene oppdateres hver 6. time.</p>
</section>"""

    winner_html, qty_html = render_winner_widget(best, offers, product["name"])
    badges_html = _render_product_badges(product.get("specs", []))

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
        "url": "{escape(o["url"])}",
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
    meta_description = (
        f'Vi sammenligner priser på {product["name"]} fra {len(product["offers"])} norske nettbutikker. '
        f'Laveste pris akkurat nå er {_fmt_kr(best["price_nok"])} hos {best["retailer"]}.'
    ) if best else long_description[:155]

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
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}}{f', "image": "{escape(image_url)}"' if image_url else ""}{f', "dateModified": "{date_modified}"' if date_modified else ""}{offers_schema}{schema_props}
}}"""
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

    price_history_html = _render_price_history_chart(price_history or [])

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
                f'{best["retailer"]} har lavest totalpris akkurat nå: {_fmt_kr(best["total"])} inkludert frakt. '
                f'{cheapest_product_offer["retailer"]} har lavere produktpris ({_fmt_kr(cheapest_product_offer["price_nok"])}) uten frakt, '
                f'men {best["retailer"]} blir billigst når frakten regnes med. Velger du flere esker, kan en annen butikk bli billigst, '
                f'siden fraktgrenser varierer mellom butikkene.'
            )
        else:
            billigst_svar = (
                f'{best["retailer"]} har både lavest produktpris og lavest totalpris akkurat nå: {_fmt_kr(best["total"])} inkludert frakt.'
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
        if product["category_slug"] == "dagslinser":
            days_two_eyes = pack_size // 2
            product_faq.append({
                "question": f'Hvor lenge varer {product["name"]}?',
                "answer": f'Til ett øye varer pakningen i {pack_size} dager (én linse per dag). Bruker du linser med samme '
                          f'styrke på begge øyne fra samme pakning, varer den {days_two_eyes} dager. Har du ulik styrke på '
                          f'hvert øye, trenger du vanligvis en egen pakning per øye.',
            })

    product_faq.append({
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk hver 6. time. Vi viser butikkens produktpris "
                  "uten frakt og beregner totalpris basert på frakt og antallet esker du velger.",
    })

    product_faq_html, product_faq_schema = _render_faq_block(product_faq, f'Vanlige spørsmål om {product["name"]}')

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
.hero-main {{ display: flex; flex-direction: column; gap: 20px; }}
@media (min-width: 860px) {{
  .hero-card {{ padding: 28px; }}
  /* Bildet spenner BEGGE rader (grid-row: 1 / 3) og strekker seg dermed i
     høyden til å matche summen av tekstkolonnen (rad 1) og prisboksen
     (rad 2, som nå spenner under både tekst OG vinner-kortet) -- i stedet
     for et fast kvadrat som før. Eksplisitt grid-column/-row på alle fire
     direkte barn siden auto-plassering ikke gir riktig resultat når
     prisboksen skal bryte ut av tekstkolonnen og spenne to kolonner. */
  .hero-main {{ display: grid; grid-template-columns: minmax(220px, 380px) 1fr minmax(250px, 300px); grid-template-rows: auto auto; gap: 20px 32px; align-items: stretch; }}
  .hero-main .hero-product-image {{ grid-column: 1; grid-row: 1 / 3; }}
  .hero-main .hero-copy {{ grid-column: 2; grid-row: 1; }}
  .hero-main .winner-band {{ grid-column: 3; grid-row: 1; margin: 0; background: white; flex-direction: column; align-items: center; text-align: center; gap: 10px; position: relative; padding: 36px 18px 18px; }}
  .hero-main .winner-left {{ flex-direction: column; align-items: center; gap: 0; }}
  .hero-main .winner-trophy {{ position: absolute; top: -22px; left: 50%; transform: translateX(-50%); box-shadow: 0 2px 6px rgba(11, 37, 69, 0.15); }}
  .hero-main .winner-band .label {{ margin-top: 0; }}
  .hero-main .winner-band .retailer {{ justify-content: center; margin-top: 10px; }}
  .hero-main .winner-band .winner-shipping {{ margin-top: 10px; }}
  .hero-main .winner-price-group {{ text-align: center; }}
  .hero-main .price-pill.is-winner {{ display: inline-block; background: none; color: var(--mint); padding: 0; font-size: 1.7rem; line-height: 1; }}
  .hero-main .winner-price-note {{ margin-top: 7px; line-height: 1; }}
  .hero-main .winner-cta {{ display: inline-flex; align-items: center; justify-content: center; gap: 6px; margin-top: 10px; background: var(--mint); color: white; font-weight: 700; font-size: 0.85rem; padding: 11px 22px; border-radius: 999px; }}
  .hero-main .product-ai-summary {{ grid-column: 2 / 4; grid-row: 2; margin: 0; }}
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
   små). Samme fulle-bredde-oppførsel gjelder derfor helt til bildet blir en
   grid-rute som spenner to rader (se .hero-main .hero-product-image over,
   860px+) -- da skal det heller strekke seg i høyden til å fylle hele det
   spennet (tekstkolonne + prisboks), ikke tvinges til et fast kvadrat. */
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
.price-history {{ margin-top: 28px; }}
.price-history h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 6px; }}
.price-history-summary {{ font-size: 0.85rem; color: var(--muted); margin: 0 0 12px; }}
.price-history-chart {{ width: 100%; height: auto; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 4px 0; }}
.price-history-area {{ fill: url(#priceHistoryFade); stroke: none; }}
.price-history-line {{ fill: none; stroke: var(--orange-dark); stroke-width: 2.25; stroke-linejoin: round; stroke-linecap: round; }}
.price-history-dot {{ fill: white; stroke: var(--orange-dark); stroke-width: 1.5; }}
.price-history-dot-last {{ fill: var(--orange-dark); stroke: white; stroke-width: 1.5; }}
.price-history-gridline {{ stroke: var(--border); stroke-width: 1; stroke-dasharray: 3 3; }}
.price-history-axis-label {{ font-family: 'Inter', sans-serif; font-size: 9.5px; fill: var(--muted); }}
.price-history-current-label {{ font-family: 'Inter', sans-serif; font-weight: 700; font-size: 11px; fill: var(--orange-dark); }}
.product-ai-summary {{ background: var(--blue-tint); border-left: 4px solid var(--blue); border-radius: 0 10px 10px 0; padding: 12px 18px; margin: 12px 0; font-size: 0.95rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary p {{ margin: 0; }}
.product-ai-summary.fallback {{ background: var(--muted-bg); border-left-color: var(--muted); color: var(--muted); }}
</style>
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
  <div class="hero-card">
    <div class="hero-main">
      <div class="hero-product-image{' has-photo' if image_url else ''}">{thumb}</div>
      <div class="hero-copy">
        <div class="kicker">{escape(product["brand_label"])}</div>
        <h1>{escape(product["name"])}</h1>
        <p>{escape(long_description)}</p>
        {badges_html}
      </div>
      {winner_html}
      {ai_summary_html}
    </div>
  </div>
  {qty_html}
  {pack_size_callout}
  <div class="offers">
    <h2>Alle tilbud, sortert etter total pris</h2>
    {offer_cards_html}
  </div>
  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på totalpris, bortsett fra ved
    eksakt lik pris mellom to tilbud, der vi kan prioritere en forhandler vi
    har avtale med. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
  </p>
  {price_history_html}
  {specs_html}
  {aliases_html}
  {product_faq_html}
  {METHODOLOGY_HTML}
  {related_html}
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_brand_page(brand_slug: str, brand_label: str, products: list[dict], categories: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    manufacturer_slug = BRAND_TO_MANUFACTURER.get(brand_slug)
    manufacturer_link_html = (
        f'<p style="margin-top:8px;"><a href="/produsent/{manufacturer_slug}/" style="font-size:0.9rem;color:var(--muted);">'
        f'Produsert av {escape(MANUFACTURERS[manufacturer_slug]["name"])} →</a></p>'
        if manufacturer_slug else ""
    )

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        image_url = _product_image(p)
        rows.append({"product": p, "lowest": lowest, "image_url": image_url})

    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

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
<title>{escape(brand_label)} kontaktlinser – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/merke/{brand_slug}/">
{_og_meta(f'{brand_label} kontaktlinser – Sammenlign priser | Kontaktlinser.no', meta_description, f'{BASE_URL}/merke/{brand_slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(brand_label)}</p>
  <div class="hero">
    <div class="brand-hero-row">
      {brand_logo_block}
      <div class="hero-copy">
        <div class="kicker">Merke</div>
        <h1>{escape(brand_label)}</h1>
        <p>Alle {escape(brand_label)}-linser vi følger prisen på, sortert etter lavest pris.</p>
        {manufacturer_link_html}
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

  <div id="product-list" class="product-tile-grid">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>

  <p class="disclosure">
    Vi sorterer alltid etter lavest pris. Vi kan få provisjon når du handler
    via lenkene på produktsidene, men det påvirker ikke prisen du betaler
    eller rangeringen av produkter eller tilbud.
  </p>

  {f'<div style="max-width:720px;margin-top:32px;">{BRAND_CONTENT[brand_slug]}</div>' if brand_slug in BRAND_CONTENT else ""}
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
    list.querySelectorAll('.product-tile').forEach(card => {{
      const show = category === 'all' || card.dataset.category === category;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
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
      {{"@type": "ListItem", "position": 2, "name": "{escape(name)}", "item": "{BASE_URL}/produsent/{manufacturer_slug}/"}}
    ]}},
    {{"@type": "Organization", "name": "{escape(name)}", "url": "{escape(data['official_url'])}"}}
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


def render_home_page(catalog: dict, now: datetime | None = None, private_labels: list[dict] | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    # Søkeindeksen (under) driver kun søkeforslag-dropdownen -- forsiden
    # viser IKKE lenger et fullt produktgrid (fjernet 2026-08-15). Data
    # sendes som skjult JSON i stedet for synlige kort, slik at søket
    # fortsatt dekker alt uten at forsidens HTML/DOM må inneholde hvert
    # eneste produkt (dårlig for sidevekt og for topisk SEO-fokus).
    def build_search_entry(p: dict) -> dict:
        return {
            "name": p["name"],
            "meta": p["brand_label"],
            "href": f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/',
            "image": _product_image(p),
            "search": f'{p["name"]} {p["brand_label"]}'.lower(),
        }

    def build_private_label_search_entry(label: dict) -> dict:
        # "meta" er den synlige undertekst-linjen i søkeforslags-dropdownen --
        # kjedenavnet skal IKKE vises der (samme regel som resten av siden).
        # "search" (kun brukt til å MATCHE søket, aldri vist) beholder
        # kjedenavnet siden en bruker som søker "Synsam" fortsatt bør finne
        # EyeQ -- det er et søkbarhets-hensyn, ikke en synlig kjede-nevning.
        return {
            "name": label["name"],
            "meta": "Eget merkenavn",
            "href": f'/private-label/{label["slug"]}/',
            "image": None,
            "search": f'{label["name"]} {label["chain"]}'.lower(),
        }

    search_index_json = json.dumps(
        [build_search_entry(p) for p in catalog["products"]], ensure_ascii=False
    ).replace("</", "<\\/")
    private_label_search_index_json = json.dumps(
        [build_private_label_search_entry(l) for l in (private_labels or [])], ensure_ascii=False
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
        return f"""<a class="category-row" href="/kontaktlinser/{escape(slug)}/">
  <div class="category-row-icon" style="background:var(--{color}-tint);color:var(--{color});">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">{icon}</svg>
  </div>
  <div class="category-row-text">
    <div class="category-row-label">{escape(category["label"])}</div>
    <div class="category-row-desc">{escape(tagline)}</div>
  </div>
  <svg class="category-row-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>
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
<style>{SHARED_STYLE}
{PRIVATE_LABEL_ILLUSTRATION_STYLE}
.hero-panel {{ padding: 0; }}
.hero {{
  padding: 8px 0 24px;
}}
.hero-content {{ display: flex; flex-direction: column; gap: 16px; }}
.hero-media {{ display: none; }}
.hero-photo-credit {{ display: none; }}
.hero-subtext {{ margin: 0; color: var(--muted); font-size: 0.94rem; max-width: 480px; }}
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
.search-row {{ position: relative; }}
.search-icon {{ position: absolute; left: 18px; top: 50%; transform: translateY(-50%); width: 20px; height: 20px; color: var(--muted); pointer-events: none; }}
.search-input {{ width: 100%; font-family: 'Inter', sans-serif; font-size: 1.05rem; padding: 16px 100px 16px 48px; border: 1px solid var(--blue); border-radius: 14px; background: white; box-shadow: var(--card-shadow); transition: box-shadow 0.15s, border-color 0.15s; }}
.search-input:hover {{ border-color: var(--blue-dark); }}
.search-input:focus {{ outline: none; border-color: var(--blue-dark); box-shadow: 0 0 0 4px var(--blue-tint); }}
.search-row:focus-within .search-icon {{ color: var(--blue); }}
.search-btn {{ position: absolute; right: 6px; top: 6px; bottom: 6px; padding: 0 20px; border: none; border-radius: 10px; background: var(--blue); color: white; font-family: 'Inter', sans-serif; font-weight: 600; font-size: 0.92rem; cursor: pointer; transition: background-color 0.15s; }}
.search-btn:hover {{ background: var(--blue-dark); }}
.search-suggestions {{ display: none; position: absolute; top: calc(100% + 6px); left: 0; right: 0; background: white; border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 12px 28px rgba(11, 37, 69, 0.14); max-height: 380px; overflow-y: auto; z-index: 20; }}
.search-suggestion {{ display: flex; align-items: center; gap: 10px; padding: 10px 14px; text-decoration: none; color: var(--ink); border-bottom: 1px solid var(--border); }}
.search-suggestion:last-child {{ border-bottom: none; }}
.search-suggestion:hover {{ background: var(--mist); }}
.search-suggestion .product-thumb {{ width: 36px; height: 36px; font-size: 0.68rem; }}
.search-suggestion-name {{ font-weight: 600; font-size: 0.86rem; }}
.search-suggestion-meta {{ font-size: 0.75rem; color: var(--muted); }}
.search-no-match {{ padding: 14px; font-size: 0.84rem; color: var(--muted); }}
.section-header {{ display: flex; align-items: baseline; justify-content: space-between; margin: 32px 0 12px; scroll-margin-top: 20px; }}
.section-header:first-of-type {{ margin-top: 0; }}
.section-header h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0; }}
.category-rows {{ display: flex; flex-direction: column; gap: 10px; }}
.category-row {{ display: flex; align-items: center; gap: 14px; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; box-shadow: var(--card-shadow); transition: border-color 0.15s; }}
.category-row:hover {{ border-color: var(--blue); }}
.category-row-icon {{ flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }}
.category-row-icon svg {{ width: 20px; height: 20px; }}
.category-row-text {{ flex: 1; min-width: 0; }}
.category-row-label {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 0.95rem; }}
.category-row-desc {{ font-size: 0.8rem; color: var(--muted); margin-top: 2px; }}
.category-row-chevron {{ flex-shrink: 0; width: 18px; height: 18px; color: var(--muted); }}
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

  .hero-panel {{ background: white; border: 1px solid var(--border); border-radius: 20px; padding: 36px 40px; box-shadow: var(--card-shadow); }}
  .hero {{
    display: grid;
    grid-template-columns: 1fr 36%;
    grid-template-areas: "content media" "content credit";
    align-items: start;
    gap: 8px 32px;
    padding: 0;
  }}
  .hero-media {{ display: block; grid-area: media; border-radius: 16px; overflow: hidden; aspect-ratio: 4 / 3; box-shadow: var(--card-shadow); }}
  .hero-media img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .hero-photo-credit {{ display: block; grid-area: credit; font-size: 0.66rem; color: var(--muted); margin: -18px 0 0; text-align: right; }}
  #kategorier {{ margin-top: 32px !important; }}
  .category-rows {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }}
  .category-row {{ flex-direction: column; align-items: center; text-align: center; gap: 10px; padding: 20px 14px; }}
  .category-row-icon {{ width: 48px; height: 48px; }}
  .category-row-icon svg {{ width: 24px; height: 24px; }}
  .category-row-chevron {{ display: none; }}
}}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <div class="hero-panel">
    <div class="hero">
      <div class="hero-content">
        <div class="hero-heading hero-copy">
          <div class="kicker">Prissammenligning</div>
          <h1>Finn billigste kontaktlinser</h1>
          <p class="hero-subtext">Vi sammenligner priser fra {n_retailers} norske nettbutikker. Alltid lavest totalpris – inkludert frakt.</p>
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
            <p class="trust-card-text">Kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser automatisk hver 6. time og viser alltid lavest totalpris inkludert frakt.</p>
          </div>
        </div>
      </div>
      <div class="hero-media">
        <img src="/static/alexandru-zdrobau-4bmtMXGuVqo-unsplash.jpg" alt="" loading="eager">
      </div>
      <p class="hero-photo-credit">Foto: Alexandru Zdrobău / Unsplash</p>
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
      <div><strong>{n_products} linser</strong><span>Oppdatert hver 6. time</span></div>
    </div>
    <div class="trust-item">
      <div class="trust-item-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9l1-5h14l1 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M4 9h16M9.5 20v-5.5h5V20"/></svg></div>
      <div><strong>{n_retailers} nettbutikker</strong><span>Alltid lavest totalpris</span></div>
    </div>
    <div class="trust-item">
      <div class="trust-item-icon">{TRUCK_ICON_SVG}</div>
      <div><strong>Inkl. frakt</strong><span>Totalpris du faktisk betaler</span></div>
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
  // Søket kjører mot en liten skjult JSON-indeks (under), ikke mot synlige
  // produktkort -- forsiden viser bevisst IKKE lenger alle {n_products}
  // linsene (fjernet 2026-08-15, se CLAUDE.md): en forside stappet full av
  // hvert eneste produkt utvannet det topiske fokuset for SEO/AI-sitering
  // og konkurrerte med egne kategori-/merkesider om de samme søkene.
  // Kategoriene og merkene under er nå den reelle "se alt"-inngangen.
  const searchInput = document.getElementById('lens-search');
  const suggestions = document.getElementById('search-suggestions');
  const productData = JSON.parse(document.getElementById('product-search-data').textContent);
  const privateLabelData = JSON.parse(document.getElementById('private-label-search-data').textContent);
  const allSearchable = productData.concat(privateLabelData);

  function renderSuggestions(q) {{
    if (!q) {{
      suggestions.style.display = 'none';
      suggestions.innerHTML = '';
      return;
    }}
    const matches = allSearchable.filter(item => item.search.includes(q)).slice(0, 8);
    if (matches.length === 0) {{
      suggestions.innerHTML = '<div class="search-no-match">Ingen treff. Prøv et annet merke eller produktnavn.</div>';
      suggestions.style.display = 'block';
      return;
    }}
    suggestions.innerHTML = matches.map(item => {{
      const thumbHtml = item.image
        ? `<div class="product-thumb"><img src="${{item.image}}" alt="" loading="lazy"></div>`
        : `<div class="product-thumb">${{item.meta.slice(0, 2).toUpperCase()}}</div>`;
      return `<a class="search-suggestion" href="${{item.href}}">${{thumbHtml}}` +
        `<div><div class="search-suggestion-name">${{item.name}}</div>` +
        `<div class="search-suggestion-meta">${{item.meta}}</div></div></a>`;
    }}).join('');
    suggestions.style.display = 'block';
  }}

  searchInput.addEventListener('input', () => {{
    renderSuggestions(searchInput.value.trim().toLowerCase());
  }});

  searchInput.addEventListener('focus', () => {{
    if (searchInput.value.trim()) renderSuggestions(searchInput.value.trim().toLowerCase());
  }});

  document.addEventListener('click', e => {{
    if (!e.target.closest('.search-row')) suggestions.style.display = 'none';
  }});

  // "Søk"-knappen/Enter går til det beste treffet, samme resultat som å
  // klikke første forslag i dropdownen -- vi har ingen egen søkeresultat-
  // side, kun autofullføring, så dette er nærmeste naturlige "søk"-handling.
  function goToBestMatch() {{
    const q = searchInput.value.trim().toLowerCase();
    if (!q) {{ searchInput.focus(); return; }}
    const best = allSearchable.find(item => item.search.includes(q));
    if (best) window.location.href = best.href;
  }}
  document.getElementById('search-btn').addEventListener('click', goToBestMatch);
  searchInput.addEventListener('keydown', e => {{
    if (e.key === 'Enter') {{ e.preventDefault(); goToBestMatch(); }}
  }});
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

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Månedslinser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
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
  linser, det enkleste og billigste utvalget</li>
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
nærsynthet (myopikontroll) hos barn og unge. Dette er noe en optiker eller øyelege
vurderer og følger opp individuelt, ikke noe man velger selv.</p>

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
på Kontaktlinser.no – er <strong>myke linser</strong> (hydrogel eller silikonhydrogel).
Harde (gassgjennomtrengelige/RGP) linser finnes fortsatt, men brukes i dag først og
fremst til spesielle synsforhold.</p>

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
  <li>Bruk alltid <strong>fersk</strong> linsevæske – fyll aldri på gammel væske i etuiet
  («topping off»), skift den helt hver gang</li>
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
  oppbevaringsvæske</li>
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
øyeinfeksjon enn linser fra forhandlere som følger norske krav til medisinsk utstyr.</p>

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
her). Slipper gjennom vesentlig mer oksygen enn eldre hydrogel-materialer, noe som kan
gi bedre komfort ved lange dager med linser i.</p>

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
krever en mer nøyaktig tilpasning enn vanlige sfæriske linser.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Multifokale/progressive linser (alderssyn)</h2>
<p style="font-size:1rem;line-height:1.7;">Fra rundt 40–45-årsalderen svekkes øyets evne til å stille skarpt på nært hold.
Multifokale linser har flere styrkesoner i samme linse (typisk for nært, mellomdistanse
og langt hold), og kan kreve en kort tilvenningsperiode før hjernen lærer å bruke sonene
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
tynnsoner som gjør at de "retter seg selv opp" på øyet.</p>

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
langt hold). Hjernen lærer gradvis å prioritere riktig sone avhengig av hva du ser på –
dette kalles simultanvisjon.</p>

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
        "title": "Kan man dusje, bade eller svømme med kontaktlinser?",
        "updated": "2026-08-16",
        "description": "Hvorfor vann og kontaktlinser bør unngås sammen, og hva du bør gjøre hvis linsene blir våte.",
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
  <li>Bruk kun øyedråper/fukterdråper beregnet for bruk sammen med kontaktlinser –
  ikke alle øyedråper er trygge å bruke med linsen i</li>
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
en brilleresept ikke er det samme som en kontaktlinseresept</a>.</p>
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
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>.</p>
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
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>.</p>
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
<a href="/guide/forsta-kontaktlinseresepten/">oversikt over hele kontaktlinseresepten</a>.</p>
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
astigmatisme</a> for mer om hvordan dette fungerer i praksis.</p>
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
linser.</p>
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
ved alderssyn</a> for mer om hvordan disse linsene fungerer.</p>
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
kontaktlinser</a>.</p>
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
oppdaterte priser fra norske nettbutikker.</p>
""",
        "faq": [
            {
                "question": "Hvorfor er det ikke ett fast svar på hva kontaktlinser koster?",
                "answer": "Prisen varierer mye ut fra linsetype, merke, pakningsstørrelse og forhandler. To ulike linser kan koste svært forskjellig selv om de dekker samme synsbehov.",
            },
            {
                "question": "Hvordan finner jeg riktig pris for akkurat mine linser?",
                "answer": "Søk opp navnet fra esken din på forsiden av Kontaktlinser.no for å se oppdaterte priser fra norske nettbutikker, sortert etter lavest totalpris.",
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
pris per linse</a> for hvordan du regner ut det reelle sammenligningsgrunnlaget.</p>
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
vs. dagslinser</a> for brukshyppighet.</p>
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
henter oppdaterte priser hver 6. time.</p>
""",
        "faq": [
            {
                "question": "Hvorfor koster samme kontaktlinse ulikt hos forskjellige butikker?",
                "answer": "Ulike innkjøpsavtaler, driftskostnader, fraktpolitikk og tidsbegrensede kampanjer gjør at prisen på samme linse kan variere mellom forhandlere.",
            },
            {
                "question": "Hvor ofte endrer prisene seg?",
                "answer": "Prisene kan endre seg fra dag til dag. Kontaktlinser.no henter oppdaterte priser fra forhandlerne hver 6. time.",
            },
        ],
    },
    "hvordan-kontaktlinser-no-beregner-totalpris": {
        "title": "Hvordan Kontaktlinser.no beregner totalpris",
        "updated": "2026-08-16",
        "description": "Hvorfor vi alltid sorterer etter totalpris (produktpris + frakt), og hvorfor det kan gi et annet resultat enn produktpris alene.",
        "body_html": """
<p>Kontaktlinser.no sorterer alltid tilbud etter <strong>totalpris</strong> –
produktpris pluss frakt – ikke produktprisen alene. Det er en bevisst forskjell fra å bare
sammenligne prisene som står på hver butikks egen produktside.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Eksempel (kun illustrativt, ikke reelle priser)</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:1rem;line-height:1.7;">
  <li>Butikk A: produktpris 250 kr + frakt 79 kr = <strong>329 kr</strong> totalt</li>
  <li>Butikk B: produktpris 265 kr + gratis frakt = <strong>265 kr</strong> totalt</li>
</ul>
<p style="font-size:1rem;line-height:1.7;">Selv om Butikk A har lavest produktpris, er Butikk B faktisk billigst når frakt regnes
med. Ser du kun på produktprisen direkte hos hver butikk, kan du lett ende opp med det
dyreste alternativet uten å vite det.</p>

<p style="margin-top:16px;">Priser eldre enn 24 timer, eller uten bekreftet lagerstatus, vises fortsatt hos oss,
men kan ikke vinne merket «laveste pris». Vi henter oppdaterte priser hver 6. time.</p>
""",
        "faq": [
            {
                "question": "Hvorfor sorterer dere etter totalpris og ikke bare produktpris?",
                "answer": "Fordi frakt er en reell del av det du faktisk betaler, og kan endre hvilken butikk som egentlig er billigst – en lav produktpris med høy frakt kan ende opp dyrere enn en høyere produktpris med gratis frakt.",
            },
            {
                "question": "Hvor ofte oppdateres prisene?",
                "answer": "Vi henter oppdaterte priser fra forhandlerne hver 6. time.",
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
tilgjengelige til enhver tid. Sjekk gjerne jevnlig om abonnementsprisen din fortsatt er
konkurransedyktig ved å sammenligne hos oss.</p>
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
  <li>Finn riktig produkt – søk opp navnet fra esken din på <a href="/">forsiden</a> vår</li>
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
og dermed for øyeirritasjon eller -skade.</p>
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
        "title": "Linsen sitter fast i øyet – hva gjør du?",
        "updated": "2026-08-17",
        "description": "Slik løsner du en kontaktlinse som kjennes fastsittende trygt, og når du bør oppsøke optiker med det samme.",
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
  <li>Bruk fukterdråper beregnet for kontaktlinser om det hjelper</li>
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


HOME_FAQ = [
    {
        "question": "Hvordan fungerer Kontaktlinser.no?",
        "answer": "Kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser automatisk fra norske nettbutikkers egne nettsider og feeds hver 6. time, og viser alltid tilbudene sortert etter lavest totalpris - produktpris pluss frakt. Du kjøper ikke hos oss; vi lenker deg videre til forhandleren du velger.",
    },
    {
        "question": "Koster det mer å kjøpe via en prissammenligningsside?",
        "answer": "Nei. Prisen du ser er forhandlerens egen pris, og du betaler akkurat det samme som om du gikk direkte til nettbutikken. Vi kan motta provisjon fra enkelte forhandlere når du handler via lenkene våre, men det påvirker verken prisen du betaler eller hvilket tilbud som vises som lavest.",
    },
    {
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Vi henter oppdaterte priser fra forhandlerne hver 6. time. Hvert tilbud viser når det sist ble kontrollert, og priser som er eldre enn 24 timer eller mangler bekreftet lagerstatus vises fortsatt, men kan ikke vinne merket «laveste pris».",
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
        "answer": "Ja. I tillegg til kontaktlinser sammenligner vi priser på linsevæske og øyedråper fra de samme norske nettbutikkene, etter samme prinsipp: alltid sortert etter lavest totalpris.",
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
    article_schema = f"""<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{escape(guide["title"])}",
  "description": "{escape(guide["description"])}",
  "author": {{"@type": "Organization", "name": "Kontaktlinser.no"}},
  "publisher": {{"@type": "Organization", "name": "Kontaktlinser.no"}},
  "datePublished": "{updated_iso}",
  "dateModified": "{updated_iso}"
}}</script>"""

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
<style>{SHARED_STYLE}
.guide-byline {{ font-size: 0.82rem; color: var(--muted); margin: -6px 0 0; }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <p class="breadcrumb"><a href="/">Hjem</a> › {escape(guide["title"])}</p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Guide</div>
      <h1>{escape(guide["title"])}</h1>
      <p class="guide-byline">Kvalitetssikret av Kontaktlinser.no · Sist oppdatert {updated_display}</p>
    </div>
  </div>
  <div style="max-width:640px;">
    {guide["body_html"]}
    {faq_html}
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

# Delt mellom /guider/-oversikten og forsidens forhåndsvisnings-seksjon,
# slik at guide-kortene ser identiske ut begge steder (se render_guide_tile).
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
"""


def render_guide_tile(slug: str, g: dict) -> str:
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
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <p class="breadcrumb"><a href="/">Hjem</a> › Guider</p>
  <div class="hero">
    <div class="hero-copy">
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
    <p>Prisene hentes automatisk fra forhandlernes egne nettsider hver
    6. time. Vi sorterer alltid etter lavest totalpris, inkludert frakt - et
    tilbud som er utsolgt eller ikke bekreftet siste 24 timer kan aldri vinne
    "laveste pris"-merket, uansett hvor lavt tallet er.</p>

    <h2>Hvordan vi tjener penger</h2>
    <p>Vi kan motta provisjon fra enkelte forhandlere når du handler via
    lenkene våre. Det påvirker aldri prisen du betaler, og det påvirker aldri
    rangeringen av tilbud - den følger alltid faktisk totalpris, ikke hvem vi
    har en avtale med.</p>

    <h2>Hva vi ikke er</h2>
    <p>Vi selger ikke kontaktlinser selv, og driver ikke butikk. Vi gir heller
    ikke medisinske råd: kontaktlinser er reseptvare, så rådfør deg alltid med
    optiker ved valg av linsetype og styrke.</p>

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
def render_privacy_page(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    updated = now.strftime("%d.%m.%Y")

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


def render_terms_page(now: datetime | None = None) -> str:
    """/vilkar/ -- juridisk informasjon og ansvarsfraskrivelse. Teksten er
    brukerens egen, limt inn 2026-08-30 (kun konvertert fra markdown til
    HTML, ordlyden er uendret). Fungerer som en paraply-side over de
    kortere, kontekstuelle disclosure-avsnittene som allerede finnes på
    produkt-/kategori-/private label-sider (footer-disclosure,
    .disclosure-avsnitt, /om-produktillustrasjoner/) -- erstatter ingen av
    dem, samler bare hele bildet ett sted. Kontaktpunktet i §11
    (_contact_email_link()) er allerede reelt og synlig i footeren på alle
    sider, ikke en tom påstand."""
    now = now or datetime.now(timezone.utc)
    updated = now.strftime("%d.%m.%Y")
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


def render_category_page(category_slug: str, category: dict, products: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)

    rows = []
    for p in products:
        offers = reconcile_product(p["offers"], now)
        eligible = [o for o in offers if o["in_stock"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        image_url = _product_image(p)
        rows.append({"product": p, "lowest": lowest, "image_url": image_url})

    # Statisk render, sortert lavest-først som standard - dette er det AI-crawlere
    # og brukere uten JS faktisk ser.
    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        # På kategorisider (i motsetning til merkesider) er MERKET det som
        # faktisk varierer/skiller kortene fra hverandre -- produsent er ofte
        # konstant på tvers av flere merker (CooperVision -> Biofinity/Avaira/
        # MyDay/...), så merkenavnet fyller samme "nyttig, varierende info
        # rett under tittelen"-rolle som produsent gjorde på merkesiden.
        brand_link = f'<a class="product-tile-manufacturer" href="/merke/{escape(p["brand_slug"])}/">{escape(p["brand_label"])}</a>'
        return _render_product_tile(
            href=f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/',
            name=p["name"],
            image_url=r["image_url"],
            fallback_initials=p["brand_label"][:2].upper(),
            category_label=category["label"],
            secondary_line_html=brand_link,
            lowest=lowest,
            other_count=len(p["offers"]) - 1,
            data_attr=f' data-brand="{escape(p["brand_slug"])}"',
        )

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
<title>Billige {escape(category["label"].lower())} – Sammenlign priser | Kontaktlinser.no</title>
<meta name="description" content="{escape(category["intro"])}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{category_slug}/">
{_og_meta(f'Billige {category["label"].lower()} – Sammenlign priser | Kontaktlinser.no', category["intro"], f'{BASE_URL}/kontaktlinser/{category_slug}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
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
    <button class="sort-toggle" id="sort-toggle" style="font-size:0.78rem;font-weight:600;color:var(--blue);background:none;border:none;cursor:pointer;">Sorter: Lavest pris ↑</button>
  </div>

  <!-- Statisk, allerede sortert lavest-først. JS under er kun en forbedring
       (filter/re-sortering) ovenpå dette - fungerer uten JS også. -->
  <div id="product-list" class="product-tile-grid">
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
    list.querySelectorAll('.product-tile').forEach(card => {{
      const show = brand === 'all' || card.dataset.brand === brand;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
  }});

  sortToggle.addEventListener('click', () => {{
    ascending = !ascending;
    sortToggle.textContent = 'Sorter: Lavest pris ' + (ascending ? '↑' : '↓');
    const cards = Array.from(list.querySelectorAll('.product-tile'));
    cards.sort((a, b) => {{
      const av = parseFloat(a.querySelector('.product-tile-price')?.textContent.replace(/\\D/g, '')) || Infinity;
      const bv = parseFloat(b.querySelector('.product-tile-price')?.textContent.replace(/\\D/g, '')) || Infinity;
      return ascending ? av - bv : bv - av;
    }});
    cards.forEach(c => list.appendChild(c));
  }});
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
        "intro": "Sammenlign priser på linsevæske fra Lenson, Lensway og Extra Optical. Vi viser pris per 100 ml der det er relevant, slik at store og små flasker er sammenlignbare.",
    },
    "oyedraper": {
        "label": "Øyedråper",
        "title_label": "Billige øyedråper",
        "intro": "Sammenlign priser på øyedråper for tørre øyne fra Lenson og Lensway. Vi viser pris per 100 ml, slik at ulike flaskestørrelser er sammenlignbare.",
    },
}


def render_solution_product_page(product: dict, now: datetime | None = None) -> str:
    """Linsevæske/øyedråper o.l. -- egen produkttype med annen datamodell enn
    kontaktlinser (size_ml/solution_type/solution_category i stedet for
    category_slug/specs), men samme pris-/tilbudslogikk (reconcile_product,
    _retailer_badge_html osv. er delt kode uendret fra kontaktlinse-sidene)."""
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"], product["name"]) for o in offers)
    long_description = product.get("long_description", product.get("description", ""))
    # Se samme begrunnelse i render_product_page -- meta-beskrivelsen skal
    # lede med selve prissammenligningen, ikke produktbeskrivelsen.
    meta_description = (
        f'Vi sammenligner priser på {product["name"]} fra {len(product["offers"])} norske nettbutikker. '
        f'Laveste pris akkurat nå er {_fmt_kr(best["price_nok"])} hos {best["retailer"]}.'
    ) if best else long_description[:155]
    cat_slug = product["solution_category"]
    cat = SOLUTION_CATEGORIES[cat_slug]
    base_url_path = f"/{cat_slug}/{product['brand_slug']}/{product['slug']}/"
    image_url = _product_image(product)

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(product["name"])}</strong> fra {len(product["offers"])} norske nettbutikker. Fra <strong>{_fmt_kr(best["price_nok"])}</strong> hos {escape(best["retailer"])} (ekskl. frakt). Kontaktlinser.no er en uavhengig sammenligningstjeneste - vi viser full totalpris inkludert frakt i sammenligningen under.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne akkurat nå. Prisene oppdateres hver 6. time.</p>
</section>"""

    # Samme delte vinner-widget som render_product_page/render_private_label_page
    # -- gir trofé-ikonet, heldekkende klikkbar ramme og antallsvelger også her
    # (samme behandling for alle produkttyper). "flaske"/"flasker" i stedet for
    # standard "eske"/"esker", siden linsevæske/øyedråper selges i flasker, ikke
    # kontaktlinseesker.
    winner_html, qty_html = render_winner_widget(best, offers, product["name"], unit_singular="flaske", unit_plural="flasker")
    best_band = f"{winner_html}\n{qty_html}"

    size_ml = product.get("size_ml")
    price_per_unit_html = ""
    if size_ml and best:
        per_100 = best["total"] / size_ml * 100
        price_per_unit_html = f'<p class="price-per-unit">{_fmt_kr(per_100)} per 100 ml, ved laveste pris</p>'

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
        "url": "{escape(o["url"])}",
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
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}}{f', "image": "{escape(image_url)}"' if image_url else ""}{f', "dateModified": "{date_modified}"' if date_modified else ""}{offers_schema}
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
                f'{best["retailer"]} har lavest totalpris akkurat nå: {_fmt_kr(best["total"])} inkludert frakt. '
                f'{cheapest_product_offer["retailer"]} har lavere produktpris ({_fmt_kr(cheapest_product_offer["price_nok"])}) uten frakt, '
                f'men {best["retailer"]} blir billigst når frakten regnes med.'
            )
        else:
            billigst_svar = (
                f'{best["retailer"]} har både lavest produktpris og lavest totalpris akkurat nå: {_fmt_kr(best["total"])} inkludert frakt.'
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
            "answer": f'Flasken inneholder {size_ml:.0f} ml.',
        })

    product_faq.append({
        "question": "Hvor ofte oppdateres prisene?",
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk hver 6. time. Vi viser butikkens produktpris "
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
{WINNER_WIDGET_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.price-per-unit {{ font-size: 0.85rem; color: var(--muted); margin: -8px 0 16px; }}
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
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">{escape(product["brand_label"])}</div>
      <h1>{escape(product["name"])}</h1>
      <p>{escape(long_description)}</p>
    </div>
  </div>
  {ai_summary_html}
  {best_band}
  {price_per_unit_html}
  {safety_notice}
  <div class="offers">
    <h2>Alle tilbud, sortert etter total pris</h2>
    {offer_cards_html}
  </div>
  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på totalpris, bortsett fra ved
    eksakt lik pris mellom to tilbud, der vi kan prioritere en forhandler vi
    har avtale med. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
  </p>
  <p class="disclosure">
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
    forhandler eller et apotek. Rådfør deg med optiker eller øyelege om
    hva som passer for deg og dine kontaktlinser.
  </p>
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
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        rows.append({"product": p, "lowest": lowest})

    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

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
<meta name="description" content="{escape(cat["intro"])}">
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


def render_private_label_brand_page(chain: str, labels: list[dict], products_by_id: dict, categories: dict, now: datetime | None = None) -> str:
    """Egen 'merke'-side for en optikerkjedes private label-serie (f.eks.
    /merke/eyeq/ for Synsam sin EyeQ-serie) -- samme URL-mønster og
    kortstil som render_brand_page(), men kildedata er private_labels.json
    + de ekte produktenes tilbud (ingen egen prisdata her heller, se
    render_private_label_page()). Gir serien sin egen indekserbare side i
    stedet for å kun leve som en seksjon på /private-label/."""
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
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        rows.append({"label": label, "real_product": real_product, "lowest": lowest})

    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

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

    meta_description = f"{subbrand} er et eget merkenavn for kontaktlinser. Sammenlign priser på alle {len(rows)} {subbrand}-varianter vi har identifisert -- de er identiske med kjente linser fra store produsenter, bare i egen innpakning."

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
<style>{SHARED_STYLE}
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
  <div class="hero">
    <div class="brand-hero-row">
      {brand_logo_block}
      <div class="hero-copy">
        <div class="kicker">Eget merkenavn</div>
        <h1>{escape(subbrand)} kontaktlinser</h1>
        <p>Alle {escape(subbrand)}-varianter vi har identifisert, sortert etter lavest pris.</p>
      </div>
    </div>
  </div>

  <div class="private-label-explainer">
    <p><strong>Hva er {escape(subbrand)}?</strong> {escape(subbrand)} er et eget varenavn for kontaktlinser, i stedet for produsentens opprinnelige navn. Det er ikke en egen linseprodusent – hver {escape(subbrand)}-linse er identisk med en kjent linse fra en av de store produsentene, bare med egen emballasje og navn. Prisene under er hentet fra det ekte produktet, siden det er nøyaktig samme fysiske vare. Se <a href="/private-label/">oversikten over optikerkjedenes egne merker</a> for hvilken kjede som står bak.</p>
  </div>

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

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Koblingene over er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale med kjeden bak dette merkenavnet og kan ikke garantere at hver kobling stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept før du bytter mellom disse navnene.
  </div>

  <p style="margin-top:16px;"><a href="/private-label/" style="color:var(--blue);font-weight:600;text-decoration:none;">Se optikerkjedenes andre egne merker →</a></p>

  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på totalpris, bortsett fra ved
    eksakt lik pris mellom to tilbud, der vi kan prioritere en forhandler vi
    har avtale med. Kontaktlinser.no er en uavhengig
    prissammenligningstjeneste, ikke en forhandler.
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
    list.querySelectorAll('.product-tile').forEach(card => {{
      const show = category === 'all' || card.dataset.category === category;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('result-count').textContent = visible + ' produkter';
  }});
</script>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_private_label_page(label: dict, real_product: dict, categories: dict, now: datetime | None = None) -> str:
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
    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"], real_product["name"]) for o in offers)

    in_stock_offers = [o for o in offers if o["in_stock"]]
    about_offers_schema = ""
    if in_stock_offers:
        schema_offers = ",\n        ".join(f'''{{
          "@type": "Offer",
          "seller": {{"@type": "Organization", "name": "{escape(o["retailer"])}"}},
          "price": {o["price_nok"]},
          "priceCurrency": "NOK",
          "url": "{escape(o["url"])}",
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

    winner_html, qty_html = render_winner_widget(best, offers, real_product["name"])
    best_band = f"{winner_html}\n{qty_html}"

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
    meta_description = (
        f'{private_name} er samme linse som {real_name} fra {real_source}. '
        f'Laveste pris akkurat nå er {_fmt_kr(best["price_nok"])} hos {best["retailer"]}.'
    ) if best else f'{private_name} er samme linse som {real_name} fra {real_source} – bare i egen innpakning. Sammenlign priser på det ekte merkenavnet.'

    about_type = "Product" if in_stock_offers else "Thing"
    date_modified = max((o["checked_at"] for o in in_stock_offers), default=None)
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "{escape(private_name)} er egentlig {escape(real_name)}",
  "about": {{"@type": "{about_type}", "name": "{escape(real_name)}", "brand": {{"@type": "Brand", "name": "{escape(real_brand)}"}}{about_offers_schema}}},
  "mainEntityOfPage": "{BASE_URL}/private-label/{label["slug"]}/"{f', "dateModified": "{date_modified}"' if date_modified else ""}
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
                f'{best["retailer"]} har lavest totalpris akkurat nå: {_fmt_kr(best["total"])} inkludert frakt. '
                f'{cheapest_product_offer["retailer"]} har lavere produktpris ({_fmt_kr(cheapest_product_offer["price_nok"])}) uten frakt, '
                f'men {best["retailer"]} blir billigst når frakten regnes med.'
            )
        else:
            billigst_svar = (
                f'{best["retailer"]} har både lavest produktpris og lavest totalpris akkurat nå: {_fmt_kr(best["total"])} inkludert frakt.'
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
        "answer": "Kontaktlinser.no henter og oppdaterer priser automatisk hver 6. time. Vi viser butikkens produktpris "
                  "uten frakt og beregner totalpris basert på frakt og antallet du velger.",
    })

    product_faq_html, product_faq_schema = _render_faq_block(product_faq, f'Vanlige spørsmål om {real_name}')

    related_items = [
        (f'/merke/{real_product["brand_slug"]}/', f'Alle {real_brand}-kontaktlinser'),
        (f'/kontaktlinser/{real_product["category_slug"]}/', f'Alle {category_label.lower()}'),
    ]
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
<title>{escape(private_name)} – Hva heter den egentlig? | Kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/private-label/{label["slug"]}/">
{_og_meta(f'{private_name} – Hva heter den egentlig? | Kontaktlinser.no', meta_description, f'{BASE_URL}/private-label/{label["slug"]}/')}
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
{product_faq_schema}
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.private-label-explainer {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin: 20px 0; font-size: 0.92rem; line-height: 1.6; }}
.private-label-explainer strong {{ color: var(--ink); }}
.private-label-caveat {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
{WINNER_WIDGET_STYLE}
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
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">Eget merkenavn</div>
      <h1>{escape(private_name)} er egentlig {escape(real_name)}</h1>
      <p>{escape(private_name)} er et eget varenavn for denne linsen. Det er samme produkt som {escape(real_name)} fra {escape(real_brand)}, bare i egen innpakning. Se <a href="/private-label/">oversikten over optikerkjedenes egne merker</a> for hvilken kjede som står bak.</p>
    </div>
  </div>

  <h2>Sammenlign priser på {escape(real_name)}, sortert etter total pris</h2>
  {best_band}
  <div class="offers">
    {offer_cards_html}
  </div>
  <p style="margin-top:16px;"><a href="{escape(real_href)}" style="color:var(--blue);font-weight:600;text-decoration:none;">Se full produktside for {escape(real_name)} →</a></p>

  <div class="private-label-explainer">
    <p><strong>Hvorfor har den to navn?</strong> Mange optikerkjeder kjøper kontaktlinser fra de samme produsentene som selger under egne kjente merker, og pakker dem om under et eget varenavn. Selve linsen – materiale, styrkeområde og spesifikasjoner – er den samme. Det er bare emballasjen og navnet som er unikt for denne serien.</p>
  </div>

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Denne koblingen er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale med kjeden bak dette merkenavnet og kan ikke garantere at koblingen stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept at {escape(real_name)} faktisk er riktig erstatning for {escape(private_name)} før du bytter.
  </div>

  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker aldri prisen du
    betaler. Rekkefølgen er alltid basert på totalpris, bortsett fra ved
    eksakt lik pris mellom to tilbud, der vi kan prioritere en forhandler vi
    har avtale med. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
    forhandler, og har ingen avtale med kjeden bak dette merkenavnet.
  </p>
  {product_faq_html}
  {METHODOLOGY_HTML}
  {related_html}
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
        lowest = min(eligible, key=lambda o: o["total"], default=None)
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
        sections_html += f"""<h2 id="{escape(chain.lower())}" style="scroll-margin-top:20px;">{escape(chain)} <a href="/merke/{escape(subbrand.lower())}/" style="font-size:0.75rem;font-weight:600;color:var(--blue);text-decoration:none;">Se {escape(subbrand)}-siden →</a></h2>
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
