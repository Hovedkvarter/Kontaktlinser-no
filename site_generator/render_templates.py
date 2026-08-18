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

import json
from datetime import datetime, timezone
from html import escape

from offer import compute_shipping_nok

BASE_URL = "https://kontaktlinser.no"

SHARED_STYLE = """
:root {
  --ink: #0B2545; --mist: #F5F9FA; --aqua: #2EC4D6; --aqua-tint: #E4F7FA;
  --mint: #0BA36F; --mint-tint: #E4F6EE; --muted: #7C8A9E; --muted-bg: #ECEFF3;
  --border: #DCE4EA; --card-shadow: 0 1px 2px rgba(11, 37, 69, 0.06);
  --coral: #E8637A; --coral-tint: #FCEAED; --amber: #D9A02B; --amber-tint: #FBF3E0;
  --lavender: #8B7FD6; --lavender-tint: #EEEBFA; --sky: #4F8FE8; --sky-tint: #E8F0FC;
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
   /pristabellsider. Se .brand-grid/.category-grid for
   tilhørende kolonneøkning ved samme breakpoint. */
@media (min-width: 1024px) {
  .wrap-wide { max-width: 1200px; }
  .wrap-product { max-width: 1040px; }
}
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 20px; max-width: 760px; margin: 0 auto; flex-wrap: wrap; }
.topbar-logo { display: flex; align-items: center; text-decoration: none; }
.topbar-logo img { height: 30px; width: auto; display: block; mix-blend-mode: multiply; }
@media (min-width: 640px) { .topbar-logo img { height: 32px; } }
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
.best-price-band { position: relative; background: var(--mint-tint); border: 1px solid #BFE7D5; border-radius: 14px; padding: 18px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; text-decoration: none; color: inherit; }
.best-price-band:hover { border-color: var(--mint); box-shadow: 0 2px 8px rgba(11, 163, 111, 0.18); }
.best-price-band .label { font-size: 0.78rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.05em; }
.best-price-band .retailer { font-size: 0.95rem; color: var(--ink); margin-top: 2px; display: flex; align-items: center; gap: 6px; }
.best-price-band .price-group { text-align: right; }
.best-price-band .price { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.6rem; color: var(--mint); white-space: nowrap; }
.best-price-band .price-note { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--muted); white-space: nowrap; }
.offer-card, .product-card { display: flex; align-items: center; justify-content: space-between; gap: 14px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 10px; box-shadow: var(--card-shadow); text-decoration: none; color: var(--ink); }
.offer-card.is-lowest { border-color: var(--mint); background: var(--mint-tint); }
.offer-card.is-muted { opacity: 0.55; }
.product-card:hover { border-color: var(--aqua); }
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
.product-price-col { text-align: right; flex-shrink: 0; }
.price-value { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.05rem; }
.price-label { font-size: 0.68rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.03em; }
.offer-price-col { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
.offer-shipping { display: flex; align-items: center; gap: 5px; font-size: 0.78rem; color: var(--muted); white-space: nowrap; }
.offer-shipping svg { width: 15px; height: 15px; color: var(--mint); flex-shrink: 0; }
.price-pill { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 1.15rem; color: white; background: var(--aqua); padding: 10px 22px; border-radius: 999px; text-decoration: none; white-space: nowrap; }
.price-pill:hover { opacity: 0.88; }
.offer-card.is-lowest .price-pill { background: var(--mint); }
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
.consent-overlay { position: fixed; inset: 0; z-index: 200; background: rgba(11, 37, 69, 0.45); display: flex; align-items: center; justify-content: center; padding: 20px; }
.consent-overlay[hidden] { display: none; }
.consent-modal { background: white; border-radius: 16px; max-width: 460px; width: 100%; max-height: 85vh; overflow-y: auto; padding: 28px; box-shadow: 0 20px 60px rgba(11, 37, 69, 0.28); }
.consent-modal h2 { font-family: 'Space Grotesk', sans-serif; font-size: 1.15rem; margin: 0 0 14px; }
.consent-text { font-size: 0.88rem; line-height: 1.6; color: var(--ink); margin: 0 0 20px; }
.consent-text a { color: var(--aqua); }
.consent-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.consent-btn { font-family: 'Inter', sans-serif; font-size: 0.84rem; font-weight: 600; padding: 10px 18px; border-radius: 20px; cursor: pointer; border: 1px solid transparent; }
.consent-btn-primary { background: var(--ink); color: white; }
.consent-btn-primary:hover { background: var(--aqua); }
.consent-btn-secondary { background: white; color: var(--ink); border-color: var(--border); }
.consent-btn-secondary:hover { border-color: var(--aqua); }
.consent-category { border-top: 1px solid var(--border); padding: 14px 0; }
.consent-category:first-of-type { border-top: none; padding-top: 0; }
.consent-category-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-weight: 600; font-size: 0.9rem; }
.consent-category-desc { font-size: 0.8rem; color: var(--muted); line-height: 1.5; margin: 6px 0 0; }
.consent-toggle { flex-shrink: 0; appearance: none; -webkit-appearance: none; width: 40px; height: 24px; background: var(--border); border-radius: 12px; position: relative; cursor: pointer; margin: 0; transition: background 0.15s; }
.consent-toggle::before { content: ""; position: absolute; top: 2px; left: 2px; width: 20px; height: 20px; background: white; border-radius: 50%; transition: transform 0.15s; box-shadow: 0 1px 3px rgba(11, 37, 69, 0.3); }
.consent-toggle:checked { background: var(--aqua); }
.consent-toggle:checked::before { transform: translateX(16px); }
.consent-toggle:disabled { opacity: 0.6; cursor: default; }
.consent-link-btn { background: none; border: none; color: var(--aqua); font-size: 0.82rem; font-weight: 600; text-decoration: underline; cursor: pointer; padding: 14px 0 0; display: block; }
.consent-providers-list:not([hidden]) { list-style: none; padding: 8px 0 0; margin: 0; font-size: 0.82rem; color: var(--muted); }
.consent-providers-list li { padding: 3px 0; }
.consent-more-link { font-size: 0.8rem; }
@media (min-width: 1024px) {
  .topbar, .footer-inner, .footer-disclosure, .footer-bottom { max-width: 1200px; }
}
"""

# Navnet er historisk (fonter) - inneholder nå også favicon-taggene, satt
# inn her bevisst fremfor å røre alle 9 sidetypenes <head> hver for seg.
# favicon-o.png er den oransje "O"-en (ring + ansiktssilhuett) beskåret ut
# av static/logo.png, med hvit bakgrunn gjort gjennomsiktig - se historikk
# 2026-08-11.
FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<link rel="icon" type="image/png" href="/static/favicon-o.png">
<link rel="apple-touch-icon" href="/static/favicon-o.png">"""

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
      <h2 id="consent-title">Vi bruker cookies på kontaktlinser.no</h2>
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

TOPBAR_HTML = f"""<div class="topbar">
  <a href="/" class="topbar-logo"><img src="/static/logo.png" alt="kontaktlinser.no" loading="eager"></a>
  <nav class="topbar-nav">
    <a href="/#merker">Merker</a>
    <a href="/#kategorier">Kategorier</a>
    <a href="/linsevaeske/">Linsevæske</a>
    <a href="/oyedraper/">Øyedråper</a>
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
    <span>&copy; {year} kontaktlinser.no</span>
    <a href="/">Forside</a>
    <a href="/guider/">Guider</a>
    <a href="/om-oss/">Om oss</a>
    <a href="/personvern/">Personvern og cookies</a>
    {_contact_email_link()}
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


# Kjedenes egne private label-serier har ikke en egen ordmerke-logo --
# kun produktbilder av emballasjen (sjekket på brilleland.no/kontaktlinser/
# iwear 2026-08-15, samme situasjon som flere av BRAND_LOGOS-produsentene
# over). Bruker derfor kjedens egen logo (som vi allerede har via
# RETAILER_LOGOS) som visuelt merke, med selve serienavnet som tekst.
PRIVATE_LABEL_SUBBRANDS = {
    "Brilleland": "iWear",
    "Synsam": "EyeQ",
    "Specsavers": "Easyvision",
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


TRUCK_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="1" y="7" width="13" height="9" rx="1" fill="currentColor"/><path d="M14 10h4l3 3v3h-7z" fill="currentColor" opacity="0.6"/><circle cx="6" cy="18" r="2" fill="currentColor"/><circle cx="17" cy="18" r="2" fill="currentColor"/></svg>'

# Isometrisk eske-ikon (topp-flate + to sideflater med ulik opasitet for
# skygge/dybde) -- brukt på antallsvelgerens piller, siden "esker" bokstavelig
# talt betyr fysiske pakkeesker, ikke bare et tall.
BOX_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 8l9-4 9 4-9 4-9-4z" fill="currentColor" opacity="0.5"/><path d="M3 8v8l9 4v-8L3 8z" fill="currentColor" opacity="0.8"/><path d="M21 8v8l-9 4v-8l9-4z" fill="currentColor"/></svg>'
# Blyant-ikon for "Eget antall"-pillen -- samme piktogram-språk, men signaliserer
# at dette er en verdi brukeren selv skriver inn, ikke et fast antall esker.
PENCIL_ICON_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 17.25V20h2.75L17.81 8.94l-2.75-2.75L4 17.25z" fill="currentColor"/><path d="M19.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 2.75 2.75 1.83-1.83z" fill="currentColor" opacity="0.6"/></svg>'


def render_offer_card(o: dict, retailer: str) -> str:
    status_note = (
        '<div class="offer-meta" style="font-weight:600;">Utsolgt</div>' if not o["in_stock"]
        else '<div class="offer-meta" style="font-weight:600;">Pris ikke bekreftet siste 24t</div>' if o["is_stale"]
        else f'<div class="offer-meta">Sist oppdatert: {escape(_time_ago(o["checked_at"], datetime.now(timezone.utc)))}</div>'
    )
    css_class = "offer-card" + (" is-lowest" if o["is_lowest"] else "") + (" is-muted" if (o["is_stale"] or not o["in_stock"]) else "")
    lowest_tag = '<span class="lowest-tag">Lavest pris</span>' if o["is_lowest"] else ""
    # Produktprisen er hovedtallet (stort), frakt en egen liten linje over --
    # samme mønster som Prisjakt/Klarna bruker, som er det norske brukere er
    # vant til å lese. Vi dropper en egen "Totalt X kr"-linje per rad (var
    # opplevd som støy -- tre tall stablet oppå hverandre på hvert kort);
    # seksjonsoverskriften over lista sier allerede at den er sortert etter
    # totalpris, og toppbanneret viser vinnerens totalsum -- "Lavest pris"-
    # merket (ALLTID totalpris-basert, se reconcile()) er dermed fortsatt
    # etterprøvbart uten at hvert enkelt kort må gjenta regnestykket.
    shipping_text = f'{_fmt_kr(o["shipping_nok"])} frakt' if o["shipping_nok"] > 0 else "Gratis frakt"
    rel = "sponsored nofollow" if o["source"] == "affiliate_feed" else "nofollow"
    price_label = f'Se hos {escape(retailer)}, {_fmt_kr(o["price_nok"])}'

    return f"""<div class="{css_class}">
  <div class="offer-main">
    <div class="offer-retailer">{_retailer_badge_html(retailer)} {lowest_tag}</div>
    {status_note}
  </div>
  <div class="offer-price-col">
    <div class="offer-shipping">{TRUCK_ICON_SVG}{escape(shipping_text)}</div>
    <a class="price-pill" href="{escape(o["url"])}" rel="{rel}" aria-label="{price_label}">{_fmt_kr(o["price_nok"])}</a>
  </div>
</div>"""


_QTY_CALC_SCRIPT = r"""<script>
(function () {
  var dataEl = document.getElementById('qty-offers-data');
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);
  var pills = document.querySelectorAll('.qty-pill');
  var customRow = document.getElementById('qty-custom-row');
  var customInput = document.getElementById('qty-custom-input');
  var labelEl = document.getElementById('winner-label');
  var retailerEl = document.getElementById('winner-retailer');
  var shippingEl = document.getElementById('winner-shipping');
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
    if (shipping <= 0) {
      if (policy && policy.free_over) return 'Gratis frakt over ' + fmtKr(policy.free_over);
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

  function update(qty) {
    if (!qty || qty < 1) return;
    var best = null, bestTotal = Infinity, bestShipping = 0;
    for (var i = 0; i < data.length; i++) {
      var o = data[i];
      var productTotal = o.price_nok * qty;
      var shipping = computeShipping(productTotal, o.shipping_policy);
      var total = productTotal + shipping;
      if (total < bestTotal) { bestTotal = total; best = o; bestShipping = shipping; }
    }
    if (!best) return;
    labelEl.textContent = 'Billigst akkurat nå for ' + qty + (qty === 1 ? ' eske' : ' esker');
    retailerEl.innerHTML = retailerBadge(best);
    shippingEl.textContent = shippingNote(bestShipping, best.shipping_policy);
    pricePill.textContent = fmtKr(bestTotal);
    pricePill.setAttribute('href', best.url);
    pricePill.setAttribute('rel', best.rel);
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
    dette antallet esker."""
    if shipping_nok <= 0:
        free_over = (shipping_policy or {}).get("free_over")
        if free_over:
            return f"Gratis frakt over {_fmt_kr(free_over)}"
        return "Gratis frakt"
    return f"{_fmt_kr(shipping_nok)} frakt"


def render_winner_widget(best: dict, offers: list[dict]) -> str:
    """Toppwidget som erstatter den gamle statiske "Laveste totalpris"-
    banneren: viser billigste totalpris for valgt antall esker, med en
    kompakt antallsvelger (1/2/4/6/10/eget antall) som regner om vinneren
    live via JS.

    Standardtilstanden (1 eske) er ALLTID ekte, ferdig-rendret HTML, og det
    samme er 2/4/10-eksemplene i den statiske oppsummeringen under velgeren
    -- mange AI-crawlere (GPTBot, ClaudeBot, PerplexityBot m.fl.) kjører ikke
    JavaScript, og skal likevel kunne lese disse tallene rett i kildekoden.

    Fraktkostnaden regnes på nytt per antall (compute_shipping_nok), ikke
    bare multiplisert med shipping_nok for én eske -- en fri-frakt-grense som
    ikke er nådd ved 1 eske kan fint være nådd ved 4, og gir da en annen
    vinner enn ved enkeltkjøp."""
    if not best:
        return ""

    rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
    shipping_note = _shipping_note(best["shipping_nok"], best.get("shipping_policy"))

    winner_band = f"""<div class="winner-band">
  <div class="label-group">
    <div class="label" id="winner-label">Billigst akkurat nå for 1 eske</div>
    <div class="retailer" id="winner-retailer">{_retailer_badge_html(best["retailer"])}</div>
    <div class="winner-shipping" id="winner-shipping">{escape(shipping_note)}</div>
  </div>
  <div class="winner-price-group">
    <a class="price-pill is-winner" id="winner-price-pill" href="{escape(best["url"])}" rel="{rel}">{_fmt_kr(best["total"])}</a>
    <div class="winner-price-note">Totalpris inkl. frakt</div>
  </div>
</div>"""

    eligible = [o for o in offers if o["in_stock"] and not o["is_stale"]]
    if len(eligible) < 2:
        return winner_band  # ingen reell antalls-sammenligning å tilby med 0-1 tilbud

    def total_for_qty(o: dict, qty: int) -> float:
        product_total = o["price_nok"] * qty
        return product_total + compute_shipping_nok(product_total, o.get("shipping_policy"))

    pills = "".join(
        f'<button type="button" class="qty-pill{" is-active" if qty == 1 else ""}" data-qty="{qty}">{BOX_ICON_SVG}{qty}<span>{"eske" if qty == 1 else "esker"}</span></button>'
        for qty in (1, 2, 4, 6, 10)
    )
    pills += f'<button type="button" class="qty-pill" data-qty="custom" id="qty-pill-custom">{PENCIL_ICON_SVG}Eget<span>antall</span></button>'

    fallback_parts = []
    for qty in (2, 4, 10):
        best_o = min(eligible, key=lambda o: total_for_qty(o, qty))
        qty_shipping = compute_shipping_nok(best_o["price_nok"] * qty, best_o.get("shipping_policy"))
        note = _shipping_note(qty_shipping, best_o.get("shipping_policy"))
        fallback_parts.append(
            f'Ved {qty} esker: billigst hos {escape(best_o["retailer"])} – {_fmt_kr(total_for_qty(best_o, qty))} totalt inkl. frakt ({note.lower()}).'
        )
    static_fallback_html = f'<p class="qty-static-fallback">{" ".join(fallback_parts)}</p>'

    calc_offers = []
    for o in eligible:
        logo_entry = RETAILER_LOGOS.get(o["retailer"])
        calc_offers.append({
            "retailer": o["retailer"],
            "price_nok": o["price_nok"],
            "shipping_policy": o.get("shipping_policy"),
            "url": o["url"],
            "rel": "sponsored nofollow" if o["source"] == "affiliate_feed" else "nofollow",
            "logo_file": logo_entry[0] if logo_entry else None,
            "logo_dark": logo_entry[1] if logo_entry else False,
        })
    calc_offers_json = json.dumps(calc_offers, ensure_ascii=False).replace("</", "<\\/")

    qty_box = f"""<div class="qty-box">
    <div class="qty-box-title">Hvor mange esker trenger du?</div>
    <div class="qty-pills" id="qty-pills">{pills}</div>
    <div class="qty-custom-row" id="qty-custom-row" hidden>
      <input type="number" id="qty-custom-input" min="1" max="50" inputmode="numeric" placeholder="Antall esker">
    </div>
    <p class="qty-tip"><span class="qty-tip-icon" aria-hidden="true">💡</span><span><strong>Tips:</strong> billigste butikk kan endre seg når du kjøper flere esker, på grunn av ulike fraktgrenser.</span></p>
  </div>
  {static_fallback_html}
  <script type="application/json" id="qty-offers-data">{calc_offers_json}</script>
  {_QTY_CALC_SCRIPT}"""

    return winner_band + "\n" + qty_box


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
    """Enkel SVG-linjegraf over laveste pris per dag, tegnet server-side --
    ingen JS-bibliotek, fungerer uten at noe script kjører. Viser ingenting
    før vi faktisk har minst en ukes historikk (en 2-punkts strek fra dag 2
    ser useriøs ut). Vokser med én dag per bygging inntil price_history.py
    sin MAX_DAYS-grense (365) er nådd."""
    if len(history) < 7:
        return ""

    prices = [h["price"] for h in history]
    min_price, max_price = min(prices), max(prices)
    price_range = max_price - min_price or 1

    width, height = 680, 180
    pad_left, pad_right, pad_top, pad_bottom = 6, 6, 14, 22
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    n = len(history)

    def x_for(i: int) -> float:
        return pad_left + (i / (n - 1) if n > 1 else 0) * plot_w

    def y_for(price: float) -> float:
        return pad_top + (1 - (price - min_price) / price_range) * plot_h

    points = " ".join(f"{x_for(i):.1f},{y_for(h['price']):.1f}" for i, h in enumerate(history))
    first, last = history[0], history[-1]
    last_x, last_y = x_for(n - 1), y_for(last["price"])

    def short_date(date_str: str) -> str:
        _, month, day = date_str.split("-")
        return f"{day}.{month}"

    return f"""<div class="price-history">
    <h2>Prisutvikling</h2>
    <p class="price-history-summary">Laveste pris siste {n} dager: {_fmt_kr(min_price)}. I dag: {_fmt_kr(last["price"])} hos {escape(last["store"])}.</p>
    <svg viewBox="0 0 {width} {height}" class="price-history-chart" role="img" aria-label="Prisutvikling siste {n} dager, fra {_fmt_kr(min_price)} til {_fmt_kr(max_price)}">
      <polyline points="{points}" class="price-history-line" />
      <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" class="price-history-dot" />
      <text x="{pad_left}" y="{height - 6}" class="price-history-axis-label">{escape(short_date(first["date"]))}</text>
      <text x="{width - pad_right}" y="{height - 6}" text-anchor="end" class="price-history-axis-label">{escape(short_date(last["date"]))}</text>
    </svg>
  </div>"""


def render_product_page(product: dict, categories: dict, products_by_id: dict | None = None, price_history: list[dict] | None = None, now: datetime | None = None, aliases: list[dict] | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    offers = reconcile_product(product["offers"], now)
    best = next((o for o in offers if o["is_lowest"]), None)
    image_url = pick_product_image(product["offers"])

    pack_size_callout = ""
    parsed = _pack_size_from_id(product["id"])
    if parsed and best and products_by_id:
        base_stem, pack_size = parsed
        siblings = []
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
            sibling_eligible = [o for o in sibling_offers if o["in_stock"] and not o["is_stale"]]
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

    thumb = f'<img src="{escape(image_url)}" alt="{escape(product["name"])}" loading="lazy">' if image_url \
        else escape(product["brand_label"][:2].upper())

    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"]) for o in offers)

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(product["name"])}</strong> fra {len(product["offers"])} norske nettbutikker. Laveste pris akkurat nå er <strong>{_fmt_kr(best["total"])}</strong> hos {escape(best["retailer"])}. Kontaktlinser.no er en uavhengig sammenligningstjeneste og viser alltid den reelle totalprisen inkludert frakt.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne linsen akkurat nå. Prisene oppdateres hver 6. time.</p>
</section>"""

    best_band = render_winner_widget(best, offers)

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

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}}{f', "image": "{escape(image_url)}"' if image_url else ""}{offers_schema}{schema_props}
}}"""
    schema_json_html = f'<script type="application/ld+json">{schema_json}</script>' if in_stock_offers else ""

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

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} – Billigste pris | kontaktlinser.no</title>
<meta name="description" content="{escape(long_description[:155])}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/">
{FONT_LINKS}
{schema_json_html}
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.aliases-note {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin: 20px 0; font-size: 0.88rem; line-height: 1.6; }}
.aliases-note ul {{ margin: 8px 0; padding-left: 20px; }}
.aliases-note a {{ color: var(--aqua); text-decoration: none; font-weight: 600; }}
.aliases-note a:hover {{ text-decoration: underline; }}
.specs {{ margin-top: 32px; }}
.specs h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 12px; }}
.specs-table {{ background: white; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
.spec-row {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 16px; font-size: 0.88rem; border-bottom: 1px solid var(--border); }}
.spec-row:last-child {{ border-bottom: none; }}
.spec-label {{ color: var(--muted); }}
.spec-value {{ font-family: 'IBM Plex Mono', monospace; text-align: right; }}
.specs-note {{ font-size: 0.76rem; color: var(--muted); margin-top: 10px; line-height: 1.5; }}
.pack-size-callout {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; margin: 16px 0; text-decoration: none; color: inherit; font-size: 0.85rem; }}
.pack-size-callout:hover {{ border-color: var(--aqua); }}
.pack-size-callout-arrow {{ color: var(--aqua); font-size: 1.1rem; flex-shrink: 0; }}
.hero-product-image {{ width: 140px; height: 140px; border-radius: 18px; background: var(--mist); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; padding: 10px; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 2rem; color: var(--aqua); }}
.hero-product-image img {{ width: 100%; height: 100%; object-fit: contain; }}
@media (min-width: 640px) {{ .hero-product-image {{ width: 180px; height: 180px; border-radius: 20px; font-size: 2.4rem; }} }}
@media (min-width: 1024px) {{ .hero-product-image {{ width: 220px; height: 220px; border-radius: 24px; font-size: 2.8rem; }} }}

.winner-band {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; background: var(--mint-tint); border: 1px solid #BFE7D5; border-radius: 14px; padding: 16px 18px; margin: 14px 0; }}
.winner-band .label {{ font-size: 0.78rem; font-weight: 600; color: var(--mint); text-transform: uppercase; letter-spacing: 0.05em; }}
.winner-band .retailer {{ font-size: 0.95rem; color: var(--ink); margin-top: 3px; display: flex; align-items: center; gap: 6px; }}
.winner-band .winner-shipping {{ font-size: 0.8rem; color: var(--muted); margin-top: 2px; }}
.winner-price-group {{ text-align: right; flex-shrink: 0; }}
.winner-price-note {{ font-size: 0.75rem; color: var(--muted); margin-top: 5px; }}
.price-pill.is-winner {{ background: var(--mint); font-size: 1.3rem; padding: 12px 24px; }}
.qty-box {{ background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }}
.qty-box-title {{ font-weight: 600; font-size: 0.92rem; margin-bottom: 10px; }}
.qty-pills {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }}
@media (min-width: 640px) {{ .qty-pills {{ grid-template-columns: repeat(6, 1fr); }} }}
.qty-pill {{ display: flex; flex-direction: column; align-items: center; gap: 3px; font-family: 'IBM Plex Mono', monospace; background: var(--mist); border: 1px solid var(--border); border-radius: 10px; padding: 10px 6px; font-size: 0.9rem; font-weight: 600; text-align: center; cursor: pointer; color: var(--ink); line-height: 1.3; }}
.qty-pill svg {{ width: 20px; height: 20px; color: var(--aqua); }}
.qty-pill span {{ font-size: 0.68rem; font-weight: 400; color: var(--muted); }}
.qty-pill.is-active {{ background: var(--aqua); border-color: var(--aqua); color: white; }}
.qty-pill.is-active svg {{ color: white; }}
.qty-pill.is-active span {{ color: rgba(255,255,255,0.85); }}
#qty-pill-custom {{ display: none; }}
@media (min-width: 640px) {{ #qty-pill-custom {{ display: block; }} }}
.qty-custom-row {{ margin-top: 10px; }}
#qty-custom-input {{ width: 140px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; }}
.qty-tip {{ display: flex; align-items: flex-start; gap: 8px; background: var(--aqua-tint); border-radius: 10px; padding: 10px 12px; font-size: 0.82rem; color: var(--ink); margin: 12px 0 0; line-height: 1.5; }}
.qty-tip-icon {{ flex-shrink: 0; }}
.qty-static-fallback {{ font-size: 0.7rem; color: var(--muted); line-height: 1.6; margin: 10px 0 0; opacity: 0.85; }}
.price-history {{ margin-top: 28px; }}
.price-history h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 6px; }}
.price-history-summary {{ font-size: 0.85rem; color: var(--muted); margin: 0 0 12px; }}
.price-history-chart {{ width: 100%; height: auto; background: white; border: 1px solid var(--border); border-radius: 12px; }}
.price-history-line {{ fill: none; stroke: var(--aqua); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.price-history-dot {{ fill: var(--aqua); }}
.price-history-axis-label {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; fill: var(--muted); }}
.product-ai-summary {{ background: var(--aqua-tint); border-left: 4px solid var(--aqua); border-radius: 0 10px 10px 0; padding: 12px 18px; margin: 12px 0; font-size: 0.88rem; line-height: 1.6; color: var(--ink); }}
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
  <div class="hero">
    <div class="hero-product-image">{thumb}</div>
    <div class="hero-copy">
      <div class="kicker">{escape(product["brand_label"])}</div>
      <h1>{escape(product["name"])}</h1>
      <p>{escape(long_description)}</p>
    </div>
  </div>
  {ai_summary_html}
  {best_band}
  {pack_size_callout}
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
  {price_history_html}
  {specs_html}
  {aliases_html}
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
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

    top_product_names = [r["product"]["name"] for r in rows if r["lowest"]][:3]
    if not top_product_names:
        meta_description = f"Sammenlign priser på alle {brand_label}-kontaktlinser vi følger, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud."
    elif len(top_product_names) == 1:
        meta_description = f"Sammenlign priser på {brand_label}-kontaktlinser som {top_product_names[0]}, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud."
    else:
        examples = ", ".join(top_product_names[:-1]) + " og " + top_product_names[-1]
        meta_description = f"Sammenlign priser på {brand_label}-kontaktlinser som {examples}, fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud."

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
<title>{escape(brand_label)} kontaktlinser – Sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/merke/{brand_slug}/">
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
            "image": pick_product_image(p["offers"]),
            "search": f'{p["name"]} {p["brand_label"]}'.lower(),
        }

    def build_private_label_search_entry(label: dict) -> dict:
        return {
            "name": label["name"],
            "meta": f'{label["chain"]} sitt eget merke',
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

    def render_private_label_chain_card(chain: str, count: int) -> str:
        n_label = "eget merke" if count == 1 else "egne merker"
        subbrand = PRIVATE_LABEL_SUBBRANDS.get(chain, chain)
        logo_entry = RETAILER_LOGOS.get(chain)
        if logo_entry:
            filename, dark_bg = logo_entry
            badge_class = "brand-card-badge has-logo has-logo-dark" if dark_bg else "brand-card-badge has-logo"
            badge_content = f'<img class="brand-logo-img" src="/static/logos/{filename}" alt="" loading="lazy">'
        else:
            badge_class = "brand-card-badge"
            badge_content = escape(chain[:2].upper())
        return f"""<a class="brand-card" href="/merke/{escape(subbrand.lower())}/">
  <div class="{badge_class}">{badge_content}</div>
  <div class="brand-card-info">
    <div class="brand-card-name">{escape(subbrand)}</div>
    <div class="brand-card-count">{escape(chain)} · {count} {n_label}</div>
  </div>
</a>"""

    chain_counts: dict[str, int] = {}
    for label in (private_labels or []):
        chain_counts[label["chain"]] = chain_counts.get(label["chain"], 0) + 1
    private_label_chain_cards_html = "\n".join(
        render_private_label_chain_card(chain, count)
        for chain, count in sorted(chain_counts.items(), key=lambda x: (-x[1], x[0]))
    )

    # Redaksjonell rekkefølge på forsidens Merker-seksjon (2026-08-15,
    # eksplisitt bruker-valg) -- IKKE en påstand om bevist popularitet.
    # Et AI-generert "topp 6 mest populære merker i Norge"-dokument ble
    # sjekket kilde for kilde først: markedsandelstallet for Specsavers
    # stemte, men iWear/Interoptik-koblingen var usann (motsagt av både
    # kilden selv og vår egen re-verifiserte private_labels.json-data) og
    # EyeQ-kilden var en død lenke -- forkastet som datagrunnlag. Dette er
    # i stedet en bevisst plassering: fremhev de tre nye private label-
    # seriene øverst, deretter tre kjente merker brukeren pekte ut selv.
    PINNED_BRAND_SLUGS = ["acuvue", "dailies", "biofinity"]
    pinned_cards_html = "\n".join(render_brand_card(slug) for slug in PINNED_BRAND_SLUGS if slug in brand_counts)
    remaining_order = [b for b in brand_order if b not in PINNED_BRAND_SLUGS]
    remaining_cards_html = "\n".join(render_brand_card(slug) for slug in remaining_order)

    brand_cards_html = private_label_chain_cards_html + "\n" + pinned_cards_html + "\n" + remaining_cards_html

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

    hero_category_pills_html = "\n".join(
        f'''<a class="hero-pill" href="/kontaktlinser/{escape(slug)}/">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">{category_icons.get(slug, "")}</svg>
  {escape(category["label"])}
</a>'''
        for slug, category in catalog["categories"].items()
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
<title>kontaktlinser.no – Sammenlign priser på kontaktlinser</title>
<meta name="description" content="Sammenlign priser på kontaktlinser fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
<link rel="canonical" href="{BASE_URL}/">
{home_faq_schema}
{FONT_LINKS}
<style>{SHARED_STYLE}
.hero {{
  display: grid;
  grid-template-columns: 1fr;
  grid-template-areas: "content" "media" "credit";
  gap: 16px;
  padding: 8px 0 24px;
}}
.hero-content {{ grid-area: content; display: flex; flex-direction: column; gap: 16px; }}
.hero-media {{ grid-area: media; border-radius: 18px; overflow: hidden; max-height: 170px; box-shadow: var(--card-shadow); }}
.hero-media img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.hero-photo-credit {{ grid-area: credit; font-size: 0.66rem; color: var(--muted); margin: -10px 0 0; text-align: right; }}
.hero-lead {{ max-width: 560px; }}
.hero-lead p {{ margin: 0; color: var(--muted); font-size: 0.92rem; }}
.hero-category-pills {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
.hero-pill {{ display: inline-flex; align-items: center; gap: 7px; padding: 9px 16px 9px 14px; border-radius: 24px; border: 1px solid var(--border); background: white; color: var(--ink); text-decoration: none; font-size: 0.84rem; font-weight: 600; box-shadow: var(--card-shadow); transition: border-color 0.15s, background-color 0.15s, box-shadow 0.15s; }}
.hero-pill svg {{ width: 15px; height: 15px; flex-shrink: 0; color: var(--aqua); }}
.hero-pill:hover {{ border-color: var(--aqua); background: var(--aqua-tint); box-shadow: 0 2px 8px rgba(46, 196, 214, 0.18); }}
.trust-strip {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px; margin: 40px 0 0; box-shadow: var(--card-shadow); }}
.trust-item {{ font-size: 0.78rem; color: var(--muted); }}
.trust-item strong {{ display: block; font-family: 'Space Grotesk', sans-serif; font-size: 1.15rem; color: var(--ink); }}
.search-section h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 10px; }}
.search-row {{ position: relative; }}
.search-icon {{ position: absolute; left: 18px; top: 50%; transform: translateY(-50%); width: 20px; height: 20px; color: var(--muted); pointer-events: none; }}
.search-input {{ width: 100%; font-family: 'Inter', sans-serif; font-size: 1.05rem; padding: 16px 20px 16px 48px; border: 1px solid var(--border); border-radius: 14px; background: white; box-shadow: var(--card-shadow); transition: box-shadow 0.15s, border-color 0.15s; }}
.search-input:focus {{ outline: none; border-color: var(--aqua); box-shadow: 0 0 0 4px var(--aqua-tint); }}
.search-row:focus-within .search-icon {{ color: var(--aqua); }}
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
{GUIDE_TILE_STYLE}
.faq-section {{ margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }}
.faq-section h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }}
.faq-item {{ margin-bottom: 18px; }}
.faq-item h3 {{ font-size: 0.94rem; margin: 0 0 6px; }}
.faq-item p {{ font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin: 0; }}
@media (min-width: 560px) {{ .brand-grid {{ grid-template-columns: repeat(3, 1fr); }} .trust-strip {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (min-width: 640px) {{ .category-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
@media (min-width: 700px) {{
  .hero {{
    grid-template-columns: 1fr 42%;
    grid-template-areas: "content media" "content credit";
    align-items: start;
    gap: 8px 32px;
  }}
  .hero-media {{ max-height: none; aspect-ratio: 4 / 3; }}
  .hero-photo-credit {{ margin-top: -22px; }}
}}
@media (min-width: 1024px) {{
  .brand-grid {{ grid-template-columns: repeat(4, 1fr); }}
  .category-grid {{ grid-template-columns: repeat(5, 1fr); }}
  .search-input {{ padding: 18px 24px 18px 52px; font-size: 1.15rem; }}
  .search-icon {{ left: 22px; width: 22px; height: 22px; }}
}}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap wrap-wide">
  <div class="hero">
    <div class="hero-content">
      <div class="hero-heading hero-copy">
        <div class="kicker">Prissammenligning</div>
        <h1>Finn billigste kontaktlinser</h1>
      </div>
      <div class="search-section">
        <h2>Søk etter linse eller merke</h2>
        <div class="search-row">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.8-4.8"/></svg>
          <label for="lens-search" class="visually-hidden" style="position:absolute;left:-9999px;">Søk etter linse eller merke</label>
          <input type="search" id="lens-search" class="search-input" placeholder="F.eks. «Biofinity» eller «Dailies»" autocomplete="off">
          <div class="search-suggestions" id="search-suggestions"></div>
        </div>
      </div>
      <div class="hero-lead">
        <p>Kontaktlinser.no er en uavhengig prissammenligningstjeneste som sammenligner priser på {n_products} kontaktlinser fra {n_retailers} norske nettbutikker. Vi henter priser automatisk hver 6. time og sorterer alltid etter lavest totalpris inkludert frakt - søk, eller velg en kategori under.</p>
        <div class="hero-category-pills">
          {hero_category_pills_html}
        </div>
      </div>
    </div>
    <div class="hero-media">
      <img src="/static/hero-eye.jpg" alt="" loading="eager">
    </div>
    <p class="hero-photo-credit">Foto: Amanda Dalbjörn / Unsplash</p>
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
    <h2>Guider</h2>
  </div>
  <div class="guide-grid">
    {guide_cards_html}
  </div>

  <div class="trust-strip">
    <div class="trust-item"><strong>{n_retailers}</strong>forhandlere sammenlignet</div>
    <div class="trust-item"><strong>{n_products}</strong>linser fulgt</div>
    <div class="trust-item"><strong>6t</strong>mellom hver prisoppdatering</div>
    <div class="trust-item"><strong>0 kr</strong>i skjulte gebyrer hos oss</div>
  </div>

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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Nytt, rent par hver dag – ingen rengjøring eller oppbevaringsvæske å huske på</li>
  <li>Lavere konsekvens hvis en linse mistes eller glemmes en dag</li>
  <li>Lavere infeksjonsrisiko enn linser som gjenbrukes over tid</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Myopikontroll</h2>
<p style="font-size:0.92rem;line-height:1.7;">Enkelte dagslinser er i dag også godkjent spesifikt for å bremse utvikling av
nærsynthet (myopikontroll) hos barn og unge. Dette er noe en optiker eller øyelege
vurderer og følger opp individuelt, ikke noe man velger selv.</p>

<p style="margin-top:24px;">Uansett alder: en synsundersøkelse hos optiker er alltid første steg, og barnet bør
følges opp jevnlig så lenge det bruker linser.</p>
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
på kontaktlinser.no – er <strong>myke linser</strong> (hydrogel eller silikonhydrogel).
Harde (gassgjennomtrengelige/RGP) linser finnes fortsatt, men brukes i dag først og
fremst til spesielle synsforhold.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Myke linser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Komfortable fra første stund, kort tilvenningstid</li>
  <li>Ligger tett mot øyet – mindre risiko for at rusk kommer under linsen</li>
  <li>Bredt utvalg av dags-, ukes- og månedslinser</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Harde linser</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Sjekk at linsen ikke er vrengt (skal danne en jevn skål, ikke ha kant som vipper ut)</li>
  <li>Trekk nedre øyelokk forsiktig ned, og hold gjerne øvre øyelokk oppe med den andre
  hånden</li>
  <li>Se oppover eller rett frem, og plasser linsen forsiktig på det hvite av øyet</li>
  <li>Se ned/blunk rolig – linsen finner selv rett posisjon på hornhinnen</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Ta ut linsen</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Fullt, uforstyrret synsfelt – ingen brillestang eller kant i synsranden</li>
  <li>Dugger ikke ved temperaturskifte, regn eller bruk av munnbind/hjelm</li>
  <li>Praktisk ved sport og fysisk aktivitet</li>
  <li>Kan kombineres med vanlige solbriller uten styrke</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva som taler for briller</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Pakk nok linser og eventuell linsevæske til hele reisen – ikke alle merker er
  tilgjengelige overalt</li>
  <li>Ta med briller som backup, i tilfelle irritasjon eller tørre øyne underveis</li>
  <li>Linsevæske i håndbagasje må følge vanlige væskeregler (beholdere under 100 ml)</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Underveis</h2>
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<p style="font-size:0.92rem;line-height:1.7;">Ukvalifiserte "festivallinser" eller kostymelinser kjøpt uten tilpasning (f.eks. fra
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
<p style="font-size:0.92rem;line-height:1.7;">Det vanligste materialet i moderne linser (inkludert de fleste vi følger prisene på
her). Slipper gjennom vesentlig mer oksygen enn eldre hydrogel-materialer, noe som kan
gi bedre komfort ved lange dager med linser i.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Vanlig hydrogel</h2>
<p style="font-size:0.92rem;line-height:1.7;">Eldre, men fortsatt i bruk i enkelte linser. Har typisk høyere vanninnhold, som for
noen kan oppleves annerledes komfortabelt enn silikonhydrogel, spesielt tidlig i
brukstiden.</p>

<p style="margin-top:16px;">Materiale og vanninnhold står oppgitt under spesifikasjoner på hver produktside her
på kontaktlinser.no.</p>
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
<p style="font-size:0.92rem;line-height:1.7;">Ved astigmatisme (skjev hornhinne) må linsen ha ulik styrke i ulike retninger, og
ligge stabilt uten å rotere i øyet. Toriske linser er formet spesielt for dette, og
krever en mer nøyaktig tilpasning enn vanlige sfæriske linser.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Multifokale/progressive linser (alderssyn)</h2>
<p style="font-size:0.92rem;line-height:1.7;">Fra rundt 40–45-årsalderen svekkes øyets evne til å stille skarpt på nært hold.
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<p style="font-size:0.92rem;line-height:1.7;">Leonardo da Vinci skisserte konsepter som kan minne om kontaktlinser allerede rundt
1508, men dette var teoretiske tegninger, ikke noe som kunne brukes. De første reelle
kontaktlinsene – tunge glasslinser som dekket hele det synlige øyet (skleralinser) –
kom først på slutten av 1800-tallet, og var langt fra komfortable ved dagens
standard.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Plast og den moderne myke linsen</h2>
<p style="font-size:0.92rem;line-height:1.7;">Lettere plastlinser kom på 1930–40-tallet. Det virkelig store gjennombruddet kom i
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<p style="font-size:0.92rem;line-height:1.7;">Toriske linser er kontaktlinser spesialformet for å korrigere astigmatisme. I motsetning
til en vanlig sfærisk linse (som har lik styrke i alle retninger og kan rotere fritt uten
at det merkes) må en torisk linse ha ulik styrke i ulike retninger, og den må ligge stabilt
i riktig posisjon for å virke. Linsene er derfor bygget med en litt tyngre nedre kant eller
tynnsoner som gjør at de "retter seg selv opp" på øyet.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvorfor tilpasningen er litt mer krevende</h2>
<p style="font-size:0.92rem;line-height:1.7;">Fordi linsen må stå riktig vei, trenger optikeren mer presis informasjon fra
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
<p style="font-size:0.92rem;line-height:1.7;">I stedet for å bytte mellom soner slik man gjør med progressive brilleglass, har
multifokale linser flere styrkesoner tilgjengelig samtidig (for nært, mellomdistanse og
langt hold). Hjernen lærer gradvis å prioritere riktig sone avhengig av hva du ser på –
dette kalles simultanvisjon.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Tilvenning</h2>
<p style="font-size:0.92rem;line-height:1.7;">De fleste bruker 1–2 uker på å venne seg til multifokale linser. Ulike design (f.eks.
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
<p style="font-size:0.92rem;line-height:1.7;">Enkelte linsetyper er spesielt godkjent for kontinuerlig bruk (såkalt "extended wear"),
der man kan sove med linsene i over flere døgn. Dette gjelder kun spesifikke,
godkjente linser, og kun etter at en øyelege eller optiker har vurdert og godkjent
akkurat det for deg – ikke noe man velger selv som standard.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hvis det skjer ved et uhell</h2>
<p style="font-size:0.92rem;line-height:1.7;">Har du sovnet med vanlige linser i, ta dem ut så snart du våkner og gi øynene en pause.
Ta kontakt med optiker eller øyelege hvis du merker rødhet, smerte eller uklart syn
etterpå.</p>
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li><strong>Dagslinser:</strong> kast dem og sett inn et nytt, rent par</li>
  <li><strong>Gjenbrukbare linser:</strong> rengjør og desinfiser dem grundig med linsevæske
  før de brukes igjen – skyll dem aldri bare med vann</li>
</ul>

<p style="margin-top:16px;">Skal du svømme og ønsker klart syn i vannet, er tettsittende svømmebriller et tryggere
alternativ enn å beholde kontaktlinsene i.</p>
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
.rx-cell { display: block; text-decoration: none; background: var(--aqua-tint); border: 1px solid var(--border); border-radius: 10px; padding: 14px 8px; text-align: center; }
.rx-cell:hover { border-color: var(--aqua); }
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.9;">
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

<p style="font-size:0.92rem;line-height:1.7;">BC må passe krumningen på din egen hornhinne. En for flat BC gjør at linsen sitter
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

<p style="font-size:0.92rem;line-height:1.7;">Feil diameter påvirker hvordan linsen sentrerer seg på øyet og hvor mye av
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

<p style="font-size:0.92rem;line-height:1.7;">Et <strong>negativt tall</strong> (f.eks. -2,50) betyr at linsen korrigerer
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

<p style="font-size:0.92rem;line-height:1.7;">CYL brukes alltid sammen med en <a href="/guide/axis-forklart/">AXIS-verdi</a>,
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

<p style="font-size:0.92rem;line-height:1.7;">Toriske linser er formet for å ligge stabilt i én bestemt retning på øyet (i
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

<p style="font-size:0.92rem;line-height:1.7;">ADD oppgis alltid som et positivt tall (f.eks. +1,50), og angir hvor mye ekstra
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<p style="font-size:0.92rem;line-height:1.7;">En kontaktlinseresept inkluderer også BC og DIA (se vår
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
                "answer": "Søk opp navnet fra esken din på forsiden av kontaktlinser.no for å se oppdaterte priser fra norske nettbutikker, sortert etter lavest totalpris.",
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>30-pakning til 300 kr = 10 kr per linse</li>
  <li>90-pakning til 750 kr = 8,33 kr per linse</li>
</ul>
<p style="font-size:0.92rem;line-height:1.7;">Selv om 90-pakningen koster mer totalt, er den billigst per linse i dette eksempelet.</p>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Omtrentlig månedskostnad</h2>
<p style="font-size:0.92rem;line-height:1.7;">Gang pris per linse med hvor mange du faktisk bruker per måned. Dette varierer mye
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

<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Butikk A: produktpris 250 kr + frakt 79 kr = <strong>329 kr</strong> totalt</li>
  <li>Butikk B: produktpris 265 kr + gratis frakt = <strong>265 kr</strong> totalt</li>
</ul>
<p style="font-size:0.92rem;line-height:1.7;">Selv om Butikk A har lavest produktpris, er Butikk B faktisk billigst når frakt regnes
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Slipper å huske å bestille på nytt</li>
  <li>Kan gi en fast rabatt hos enkelte forhandlere</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva du bør vite</h2>
<p style="font-size:0.92rem;line-height:1.7;">Et abonnement binder deg til én forhandlers pris, mens priser generelt varierer
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

<ol style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.9;">
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

<p style="font-size:0.92rem;line-height:1.7;">Seriøse forhandlere ber om resept-informasjon ved bestilling. Kjøp fra useriøse
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
<p style="font-size:0.92rem;line-height:1.7;">Hvis det er snakk om nøyaktig samme fysiske linse solgt under et annet navn (f.eks. en
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Linsen har tørket ut – ofte fordi den har vært i øyet lenger enn vanlig, eller øyet er tørt</li>
  <li>Linsen har gled opp under det øvre øyelokket</li>
  <li>Du blunker mye og stresser, som gjør det vanskeligere å kjenne hvor linsen faktisk er</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Slik gjør du det trygt</h2>
<ol style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>Skitten linse, eller avleiringer (protein/fett fra tårevæsken) på overflaten</li>
  <li>Linsen ligger vrengt (inni ut)</li>
  <li><a href="/guide/kontaktlinser-og-torre-oyne/">Tørre øyne</a></li>
  <li>Linsen er brukt lenger enn anbefalt bytteintervall</li>
  <li>Styrken stemmer ikke lenger – synet endrer seg gradvis over tid for de fleste</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Enkle ting å sjekke først</h2>
<ol style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
<ul style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
  <li>For lang brukstid i løpet av dagen</li>
  <li>Tørt inneklima eller lange skjermøkter</li>
  <li>Lett irritasjon fra en avleiring på linsekanten</li>
  <li>Allergi (pollen, støv) som forsterkes av linsebruk</li>
</ul>

<h2 style="font-family:'Space Grotesk',sans-serif;font-size:1.05rem;margin:28px 0 10px;">Hva du bør gjøre</h2>
<ol style="padding-left:20px;color:var(--ink);font-size:0.92rem;line-height:1.7;">
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
en linse, og hold deg til anbefalt bytteintervall for linse og væske – det reduserer
risikoen for at dette oppstår i utgangspunktet.</p>
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
        "question": "Hvordan fungerer kontaktlinser.no?",
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
        "answer": "Det kommer an på linsetype, merke og hvor ofte du bruker linser - det finnes ikke ett svar som gjelder for alle. Se vår guide om månedslinser vs. dagslinser, og bruk kategoriene på kontaktlinser.no til å sammenligne faktiske priser for akkurat den styrken og pakningsstørrelsen du trenger.",
    },
    {
        "question": "Selger dere også linsevæske og øyedråper?",
        "answer": "Ja. I tillegg til kontaktlinser sammenligner vi priser på linsevæske og øyedråper fra de samme norske nettbutikkene, etter samme prinsipp: alltid sortert etter lavest totalpris.",
    },
    {
        "question": "Hvorfor har noen kontaktlinser to forskjellige navn?",
        "answer": "Flere optikerkjeder selger kjente kontaktlinser under sitt eget varenavn - for eksempel selger Brilleland Biofinity under navnet «iWear Oxygen». Det er samme fysiske produkt, bare med kjedens egen emballasje og navn. Vi har en egen oversikt over disse koblingene under Optikerkjedenes egne merker.",
    },
    {
        "question": "Er kontaktlinser.no en nettbutikk eller et apotek?",
        "answer": "Nei, kontaktlinser.no er verken en nettbutikk eller et apotek - vi er en uavhengig sammenligningstjeneste og selger ingenting selv. Kontaktlinser er reseptvare, så rådfør deg alltid med optiker eller øyelege om riktig linsetype og styrke før kjøp.",
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
  "author": {{"@type": "Organization", "name": "kontaktlinser.no"}},
  "publisher": {{"@type": "Organization", "name": "kontaktlinser.no"}},
  "datePublished": "{updated_iso}",
  "dateModified": "{updated_iso}"
}}</script>"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(guide["title"])} | kontaktlinser.no</title>
<meta name="description" content="{escape(guide["description"])}">
<link rel="canonical" href="{BASE_URL}/guide/{slug}/">
{FONT_LINKS}
{faq_schema}
{article_schema}
<style>{SHARED_STYLE}
.faq-section {{ margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }}
.faq-section h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }}
.faq-item {{ margin-bottom: 18px; }}
.faq-item h3 {{ font-size: 0.94rem; margin: 0 0 6px; }}
.faq-item p {{ font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin: 0; }}
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
      <p class="guide-byline">Kvalitetssikret av kontaktlinser.no · Sist oppdatert {updated_display}</p>
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
        "color": "aqua",
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
        "color": "aqua",
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
        "color": "aqua",
        "svg": '<circle cx="12" cy="12" r="9" fill="currentColor" opacity="0.18"/><path d="M12 8v8M8 12h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    },
    "hvor-lenge-kan-man-bruke-kontaktlinser": {
        "color": "aqua",
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
        "color": "aqua",
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
.guide-tile:hover { border-color: var(--aqua); }
.guide-tile-icon { width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 14px; }
.guide-tile-icon svg { width: 28px; height: 28px; }
.guide-tile-title { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; margin-bottom: 6px; }
.guide-tile-desc { font-size: 0.86rem; color: var(--muted); line-height: 1.5; }
.guide-tile-link { font-size: 0.86rem; font-weight: 600; color: var(--aqua); margin-top: 12px; }
@media (min-width: 640px) { .guide-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 900px) { .guide-grid { grid-template-columns: repeat(4, 1fr); } }
"""


def render_guide_tile(slug: str, g: dict) -> str:
    icon = GUIDE_ICONS.get(slug, {"color": "aqua", "svg": ""})
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
<title>Guider – kontaktlinser.no</title>
<meta name="description" content="Guider om kontaktlinser: hvordan velge riktig type, bruk og vedlikehold, kontaktlinser for barn, og mer.">
<link rel="canonical" href="{BASE_URL}/guider/">
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
<title>Om oss – kontaktlinser.no</title>
<meta name="description" content="Om kontaktlinser.no: hva vi gjør, hvordan vi sammenligner priser, og hvordan vi tjener penger.">
<link rel="canonical" href="{BASE_URL}/om-oss/">
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
      <h1>Om kontaktlinser.no</h1>
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
<title>Siden ble ikke funnet – kontaktlinser.no</title>
{FONT_LINKS}
<style>{SHARED_STYLE}
.not-found-hero {{ padding: 40px 0 16px; text-align: center; }}
.not-found-hero .kicker {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }}
.not-found-hero h1 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.7rem; margin: 8px 0 10px; }}
.not-found-hero p {{ color: var(--muted); font-size: 0.94rem; max-width: 440px; margin: 0 auto; }}
.not-found-links {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; max-width: 440px; margin: 28px auto 0; }}
.not-found-link {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 14px; text-align: center; font-weight: 600; font-size: 0.9rem; box-shadow: var(--card-shadow); }}
.not-found-link:hover {{ border-color: var(--aqua); }}
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
<title>Personvern og cookies – kontaktlinser.no</title>
<meta name="description" content="Hvilke informasjonskapsler (cookies) kontaktlinser.no bruker, hvorfor, og hvordan du kan kontrollere dem.">
<link rel="canonical" href="{BASE_URL}/personvern/">
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
      <p>Hvilke informasjonskapsler vi bruker på kontaktlinser.no, hvorfor, og hvordan du styrer dem selv.</p>
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
        kontaktlinser.no, slik at forhandleren kan betale riktig provisjon til
        oss. Disse cookiene settes av det aktuelle affiliate-nettverket eller
        forhandlerens eget domene, ikke av kontaktlinser.no direkte.</td>
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
    nettstedsdata for kontaktlinser.no i nettleserinnstillingene og laste
    siden på nytt.</p>

    <h2>Hvordan kontrollere eller slette cookies</h2>
    <p>De fleste nettlesere lar deg se, blokkere og slette cookies under
    personvern- eller sikkerhetsinnstillingene. Slår du av ikke-nødvendige
    cookies helt, vil kontaktlinser.no fortsatt fungere som normalt - vi
    bruker dem kun til måling og provisjonssporing, ikke til selve
    prissammenligningen.</p>

    <h2>Kontakt</h2>
    <p>Spørsmål om personvern eller cookies på kontaktlinser.no? Send oss en
    e-post på {_contact_email_link()}.</p>

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
<title>{escape(category["label"])} – Sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(category["intro"])}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{category_slug}/">
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
        "intro": "Sammenlign priser på linsevæske fra Lenson, Lensway og Extra Optical. Vi viser pris per 100 ml der det er relevant, slik at store og små flasker er sammenlignbare.",
    },
    "oyedraper": {
        "label": "Øyedråper",
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
    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"]) for o in offers)
    long_description = product.get("long_description", product.get("description", ""))
    cat_slug = product["solution_category"]
    cat = SOLUTION_CATEGORIES[cat_slug]
    base_url_path = f"/{cat_slug}/{product['brand_slug']}/{product['slug']}/"
    image_url = pick_product_image(product["offers"])

    if best:
        ai_summary_html = f"""<section class="product-ai-summary" aria-label="Prisoppsummering">
  <p>Vi sammenligner priser på <strong>{escape(product["name"])}</strong> fra {len(product["offers"])} norske nettbutikker. Laveste pris akkurat nå er <strong>{_fmt_kr(best["total"])}</strong> hos {escape(best["retailer"])}. Kontaktlinser.no er en uavhengig sammenligningstjeneste og viser alltid den reelle totalprisen inkludert frakt.</p>
</section>"""
    else:
        ai_summary_html = f"""<section class="product-ai-summary fallback" aria-label="Status">
  <p>Vi følger prisen på <strong>{escape(product["name"])}</strong>, men ingen av forhandlerne vi sammenligner har en bekreftet pris for denne akkurat nå. Prisene oppdateres hver 6. time.</p>
</section>"""

    best_band = ""
    if best:
        best_rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
        best_price_note = (
            f'{_fmt_kr(best["price_nok"])} + {_fmt_kr(best["shipping_nok"])} frakt' if best["shipping_nok"] > 0
            else "Gratis frakt"
        )
        best_band = f"""<a class="best-price-band" href="{escape(best["url"])}" rel="{best_rel}">
  <div class="label-group">
    <div class="label">Laveste totalpris</div>
    <div class="retailer">{_retailer_badge_html(best["retailer"])}</div>
  </div>
  <div class="price-group">
    <div class="price">{_fmt_kr(best["total"])}</div>
    <div class="price-note">{escape(best_price_note)}</div>
  </div>
</a>"""

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

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{escape(product["name"])}",
  "description": "{escape(long_description)}",
  "brand": {{"@type": "Brand", "name": "{escape(product["brand_label"])}"}}{f', "image": "{escape(image_url)}"' if image_url else ""}{offers_schema}
}}"""
    schema_json_html = f'<script type="application/ld+json">{schema_json}</script>' if in_stock_offers else ""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} – Billigste pris | kontaktlinser.no</title>
<meta name="description" content="{escape(long_description[:155])}">
<link rel="canonical" href="{BASE_URL}{base_url_path}">
{FONT_LINKS}
{schema_json_html}
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.price-per-unit {{ font-size: 0.85rem; color: var(--muted); margin: -8px 0 16px; }}
.safety-notice {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
.product-ai-summary {{ background: var(--aqua-tint); border-left: 4px solid var(--aqua); border-radius: 0 10px 10px 0; padding: 14px 18px; margin: 16px 0; font-size: 0.88rem; line-height: 1.6; color: var(--ink); }}
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
    provisjon når du handler via lenkene, men det påvirker ikke prisen du
    betaler eller rekkefølgen på tilbudene. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
  </p>
  <p class="disclosure">
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
    forhandler eller et apotek. Rådfør deg med optiker eller øyelege om
    hva som passer for deg og dine kontaktlinser.
  </p>
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
        eligible = [o for o in offers if o["in_stock"] and not o["is_stale"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        rows.append({"product": p, "lowest": lowest})

    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        p, lowest = r["product"], r["lowest"]
        price_block = (
            f'<div class="price-label">Fra</div><div class="price-value" style="color:var(--mint);">{_fmt_kr(lowest["total"])}</div>'
            f'<div class="retailer-count">{len(p["offers"])} forhandlere</div>'
            if lowest else '<div class="retailer-count">Ingen tilbud tilgjengelig</div>'
        )
        href = f'/{solution_category}/{p["brand_slug"]}/{p["slug"]}/'
        size_label = f'{p["size_ml"]} ml' if p.get("size_ml") else ""
        meta = escape(p["brand_label"]) + (f" · {escape(size_label)}" if size_label else "")
        return f"""<a class="product-card" href="{escape(href)}">
  <div class="product-thumb">{escape(p["brand_label"][:2].upper())}</div>
  <div class="product-main">
    <div class="product-name">{escape(p["name"])}</div>
    <div class="product-meta">{meta}</div>
  </div>
  <div class="product-price-col">{price_block}</div>
</a>"""

    product_rows_html = "\n".join(render_row(r) for r in rows)
    cat = SOLUTION_CATEGORIES[solution_category]

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
<title>{escape(cat["label"])} – Sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(cat["intro"])}">
<link rel="canonical" href="{BASE_URL}/{solution_category}/">
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

  <div id="product-list">
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
        eligible = [o for o in offers if o["in_stock"] and not o["is_stale"]]
        lowest = min(eligible, key=lambda o: o["total"], default=None)
        image_url = pick_product_image(real_product["offers"])
        rows.append({"label": label, "real_product": real_product, "lowest": lowest, "image_url": image_url})

    rows.sort(key=lambda r: r["lowest"]["total"] if r["lowest"] else float("inf"))

    def render_row(r: dict) -> str:
        label, real_product, lowest = r["label"], r["real_product"], r["lowest"]
        thumb = f'<img src="{escape(r["image_url"])}" alt="{escape(label["name"])}" loading="lazy">' if r["image_url"] \
            else escape(chain[:2].upper())
        price_block = (
            f'<div class="price-label">Fra</div><div class="price-value" style="color:var(--mint);">{_fmt_kr(lowest["total"])}</div>'
            f'<div class="retailer-count">{len(real_product["offers"])} forhandlere</div>'
            if lowest else '<div class="retailer-count">Ingen tilbud tilgjengelig</div>'
        )
        href = f'/private-label/{escape(label["slug"])}/'
        category_label = categories[real_product["category_slug"]]["label"] if "category_slug" in real_product else ""
        return f"""<a class="product-card" href="{href}" data-category="{escape(real_product.get("category_slug", ""))}">
  <div class="product-thumb">{thumb}</div>
  <div class="product-main">
    <div class="product-name">{escape(label["name"])}</div>
    <div class="product-meta">= {escape(real_product["name"])}{" · " + escape(category_label) if category_label else ""}</div>
  </div>
  <div class="product-price-col">{price_block}</div>
</a>"""

    product_rows_html = "\n".join(render_row(r) for r in rows)

    category_slugs = sorted({r["real_product"]["category_slug"] for r in rows if "category_slug" in r["real_product"]})
    category_chips = "".join(
        f'<button class="chip" data-category="{escape(c)}">{escape(categories[c]["label"])}</button>' for c in category_slugs
    )

    # _brand_badge() slår opp i BRAND_LOGOS (linsemerker), ikke
    # RETAILER_LOGOS (kjeder) -- bygg badgen selv med kjedens logo i stedet.
    logo_entry = RETAILER_LOGOS.get(chain)
    if logo_entry:
        filename, dark_bg = logo_entry
        brand_logo_cls = "has-logo has-logo-dark" if dark_bg else "has-logo"
        brand_logo_content = f'<img class="brand-logo-img" src="/static/logos/{filename}" alt="" loading="lazy">'
    else:
        brand_logo_cls, brand_logo_content = "", escape(chain[:2].upper())
    brand_logo_block = f'<div class="brand-hero-logo {brand_logo_cls}">{brand_logo_content}</div>'

    meta_description = f"{subbrand} er {chain} sitt eget merkenavn for kontaktlinser. Sammenlign priser på alle {len(rows)} {subbrand}-varianter vi har identifisert -- de er identiske med kjente linser fra store produsenter, bare i egen innpakning."

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
<title>{escape(subbrand)} kontaktlinser – Sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(meta_description)}">
<link rel="canonical" href="{BASE_URL}/merke/{slug}/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
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
        <div class="kicker">{escape(chain)} sitt eget merkenavn</div>
        <h1>{escape(subbrand)} kontaktlinser</h1>
        <p>Alle {escape(subbrand)}-varianter vi har identifisert, sortert etter lavest pris.</p>
      </div>
    </div>
  </div>

  <div class="private-label-explainer">
    <p><strong>Hva er {escape(subbrand)}?</strong> {escape(chain)} selger kontaktlinser under sitt eget varenavn, {escape(subbrand)}, i stedet for produsentens opprinnelige navn. Det er ikke en egen linseprodusent – hver {escape(subbrand)}-linse er identisk med en kjent linse fra en av de store produsentene, bare med {escape(chain)} sin egen emballasje og navn. Prisene under er hentet fra det ekte produktet, siden det er nøyaktig samme fysiske vare.</p>
  </div>

  <div class="filter-row" id="filter-row" role="group" aria-label="Filtrer etter kategori">
    <button class="chip active" data-category="all">Alle kategorier</button>
    {category_chips}
  </div>

  <div class="list-header">
    <h2 id="result-count">{len(rows)} produkter</h2>
  </div>

  <div id="product-list">
    {product_rows_html}
  </div>
  <noscript><p style="font-size:0.78rem;color:var(--muted);">Filtrering krever JavaScript. Listen over viser alle produkter, sortert etter lavest pris.</p></noscript>

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Koblingene over er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale med {escape(chain)} og kan ikke garantere at hver kobling stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept før du bytter mellom disse navnene.
  </div>

  <p style="margin-top:16px;"><a href="/private-label/" style="color:var(--aqua);font-weight:600;text-decoration:none;">Se optikerkjedenes andre egne merker →</a></p>

  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker ikke prisen du
    betaler eller rekkefølgen på tilbudene. Kontaktlinser.no er en uavhengig
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
    list.querySelectorAll('.product-card').forEach(card => {{
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
    offer_cards_html = "\n".join(render_offer_card(o, o["retailer"]) for o in offers)

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

    best_band = ""
    if best:
        best_rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
        best_price_note = (
            f'{_fmt_kr(best["price_nok"])} + {_fmt_kr(best["shipping_nok"])} frakt' if best["shipping_nok"] > 0
            else "Gratis frakt"
        )
        best_band = f"""<a class="best-price-band" href="{escape(best["url"])}" rel="{best_rel}">
  <div class="label-group">
    <div class="label">Laveste totalpris</div>
    <div class="retailer">{_retailer_badge_html(best["retailer"])}</div>
  </div>
  <div class="price-group">
    <div class="price">{_fmt_kr(best["total"])}</div>
    <div class="price-note">{escape(best_price_note)}</div>
  </div>
</a>"""

    about_type = "Product" if in_stock_offers else "Thing"
    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "{escape(private_name)} ({escape(chain)}) er egentlig {escape(real_name)}",
  "about": {{"@type": "{about_type}", "name": "{escape(real_name)}", "brand": {{"@type": "Brand", "name": "{escape(real_brand)}"}}{about_offers_schema}}},
  "mainEntityOfPage": "{BASE_URL}/private-label/{label["slug"]}/"
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(private_name)} ({escape(chain)}) – Hva heter den egentlig? | kontaktlinser.no</title>
<meta name="description" content="{escape(private_name)} fra {escape(chain)} er samme linse som {escape(real_name)} fra {escape(real_brand)} – bare i egen innpakning. Sammenlign priser på det ekte merkenavnet.">
<link rel="canonical" href="{BASE_URL}/private-label/{label["slug"]}/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.private-label-explainer {{ background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; margin: 20px 0; font-size: 0.92rem; line-height: 1.6; }}
.private-label-explainer strong {{ color: var(--ink); }}
.private-label-caveat {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
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
      <div class="kicker">{escape(chain)} sitt eget merkenavn</div>
      <h1>{escape(private_name)} er egentlig {escape(real_name)}</h1>
      <p>{escape(chain)} selger denne linsen under sitt eget navn, {escape(private_name)}. Det er samme produkt som {escape(real_name)} fra {escape(real_brand)}, bare i egen innpakning.</p>
    </div>
  </div>

  <h2>Sammenlign priser på {escape(real_name)}, sortert etter total pris</h2>
  {best_band}
  <div class="offers">
    {offer_cards_html}
  </div>
  <p style="margin-top:16px;"><a href="{escape(real_href)}" style="color:var(--aqua);font-weight:600;text-decoration:none;">Se full produktside for {escape(real_name)} →</a></p>

  <div class="private-label-explainer">
    <p><strong>Hvorfor har den to navn?</strong> Mange optikerkjeder kjøper kontaktlinser fra de samme produsentene som selger under egne kjente merker, og pakker dem om under et eget varenavn. Selve linsen – materiale, styrkeområde og spesifikasjoner – er den samme. Det er bare emballasjen og navnet som er unikt for {escape(chain)}.</p>
  </div>

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Denne koblingen er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. Kontaktlinser.no har ingen avtale med {escape(chain)} og kan ikke garantere at koblingen stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept at {escape(real_name)} faktisk er riktig erstatning for {escape(private_name)} før du bytter.
  </div>

  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker ikke prisen du
    betaler eller rekkefølgen på tilbudene. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
    Kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
    forhandler, og har ingen avtale med {escape(chain)}.
  </p>
</div>
{render_footer()}
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
</body>
</html>"""


def render_private_label_index_page(labels: list[dict], products_by_id: dict) -> str:
    """Oversiktsside -- gruppert per optikerkjede, lenker videre til hver
    enkelt private label-side."""
    by_chain: dict[str, list[dict]] = {}
    for label in labels:
        by_chain.setdefault(label["chain"], []).append(label)

    sections_html = ""
    for chain in sorted(by_chain.keys()):
        chain_labels = sorted(by_chain[chain], key=lambda l: l["name"])
        rows = "\n".join(
            f'<a class="product-card" href="/private-label/{escape(l["slug"])}/">'
            f'<div class="product-main"><div class="product-name">{escape(l["name"])}</div>'
            f'<div class="product-meta">= {escape(products_by_id[l["real_product_id"]]["name"])}</div></div>'
            f'</a>'
            for l in chain_labels
        )
        subbrand = PRIVATE_LABEL_SUBBRANDS.get(chain, chain)
        sections_html += f"""<h2 id="{escape(chain.lower())}" style="scroll-margin-top:20px;">{escape(chain)} <a href="/merke/{escape(subbrand.lower())}/" style="font-size:0.75rem;font-weight:600;color:var(--aqua);text-decoration:none;">Se {escape(subbrand)}-siden →</a></h2>
  <div class="product-list-group">{rows}</div>
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
<title>Optikerkjedenes egne merker – Hva heter linsen egentlig? | kontaktlinser.no</title>
<meta name="description" content="{escape(intro)}">
<link rel="canonical" href="{BASE_URL}/private-label/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.product-list-group {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 28px; }}
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
