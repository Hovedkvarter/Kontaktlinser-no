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

# Gamle, fortsatt Google-indekserte URL-er fra forrige versjon av siden
# (funnet via "site:kontaktlinser.no" 2026-08-11). GitHub Pages kan ikke
# servere .aspx som HTML (bekreftet: mime-db mangler .aspx, serveres som
# application/octet-stream - se CLAUDE.md) - derfor ingen ekte 301, kun en
# klientsidevis omdirigering fra 404-siden (se render_404_page). Nøklene MÅ
# være små bokstaver (matches mot location.pathname.toLowerCase() i JS-en).
LEGACY_REDIRECTS = {
    "/infosider/vedlikehold_av_linser/vedlikehold_av_kontaktlinsene.aspx": "/guider/",
    "/kontaktlinser/dagslinser.aspx": "/kontaktlinser/dagslinser/",
    "/kontaktlinser/fargede_linser.aspx": "/kontaktlinser/fargede-linser/",
    "/infosider/reising_med_kontaktlinser.aspx": "/guider/",
    "/infosider/vedlikehold_av_linser.aspx": "/guider/",
    "/infosider/kosmetiske_kontaktlinser.aspx": "/kontaktlinser/fargede-linser/",
    "/infosider/harde_eller_myke_linser.aspx": "/guide/hvordan-velge-kontaktlinser/",
    "/infosider/hvordan.aspx": "/guide/hvordan-velge-kontaktlinser/",
    "/kontaktlinser/dagslinser/linser.aspx": "/kontaktlinser/dagslinser/",
    "/infosider/produksjon_av_kontaktlinser.aspx": "/guider/",
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


def render_product_page(product: dict, categories: dict, products_by_id: dict | None = None, price_history: list[dict] | None = None, now: datetime | None = None) -> str:
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

    best_band = ""
    if best:
        best_rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
        best_band = f"""<a class="best-price-band" href="{escape(best["url"])}" rel="{best_rel}">
  <div class="label-group">
    <div class="label">Laveste pris</div>
    <div class="retailer">{_retailer_badge_html(best["retailer"])}</div>
  </div>
  <div class="price">{_fmt_kr(best["total"])}</div>
</a>"""

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

    price_history_html = _render_price_history_chart(price_history or [])

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} – billigste pris | kontaktlinser.no</title>
<meta name="description" content="{escape(long_description[:155])}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{product["brand_slug"]}/{product["slug"]}/">
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
.pack-size-callout {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; background: white; border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; margin: 16px 0; text-decoration: none; color: inherit; font-size: 0.85rem; }}
.pack-size-callout:hover {{ border-color: var(--aqua); }}
.pack-size-callout-arrow {{ color: var(--aqua); font-size: 1.1rem; flex-shrink: 0; }}
.hero-product-image {{ width: 160px; height: 160px; border-radius: 20px; background: var(--mist); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; padding: 10px; box-sizing: border-box; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 2.2rem; color: var(--aqua); }}
.hero-product-image img {{ width: 100%; height: 100%; object-fit: contain; }}
@media (min-width: 640px) {{ .hero-product-image {{ width: 240px; height: 240px; border-radius: 24px; font-size: 3.2rem; }} }}
.price-history {{ margin-top: 28px; }}
.price-history h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.05rem; margin: 0 0 6px; }}
.price-history-summary {{ font-size: 0.85rem; color: var(--muted); margin: 0 0 12px; }}
.price-history-chart {{ width: 100%; height: auto; background: white; border: 1px solid var(--border); border-radius: 12px; }}
.price-history-line {{ fill: none; stroke: var(--aqua); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.price-history-dot {{ fill: var(--aqua); }}
.price-history-axis-label {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; fill: var(--muted); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
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
<link rel="canonical" href="{BASE_URL}/merke/{brand_slug}/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
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
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
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
    home_faq_html, home_faq_schema = _render_faq_block(HOME_FAQ)

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>kontaktlinser.no – sammenlign priser på kontaktlinser</title>
<meta name="description" content="Sammenlign priser på kontaktlinser fra norske nettbutikker. Vi viser alltid billigste tilgjengelige tilbud.">
<link rel="canonical" href="{BASE_URL}/">
{home_faq_schema}
{FONT_LINKS}
<style>{SHARED_STYLE}
.hero {{
  display: grid;
  grid-template-columns: 1fr;
  grid-template-areas: "heading" "search" "media" "credit" "lead";
  gap: 16px;
  padding: 8px 0 24px;
}}
.hero-heading {{ grid-area: heading; }}
.search-section {{ grid-area: search; }}
.hero-media {{ grid-area: media; border-radius: 18px; overflow: hidden; max-height: 170px; box-shadow: var(--card-shadow); }}
.hero-media img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.hero-photo-credit {{ grid-area: credit; font-size: 0.66rem; color: var(--muted); margin: -10px 0 0; text-align: right; }}
.hero-lead {{ grid-area: lead; max-width: 560px; }}
.hero-lead p {{ margin: 0; color: var(--muted); font-size: 0.92rem; }}
.hero-actions {{ margin-top: 16px; }}
.btn-primary {{ display: inline-block; background: var(--ink); color: white; font-weight: 600; font-size: 0.88rem; text-decoration: none; padding: 11px 20px; border-radius: 24px; }}
.btn-primary:hover {{ background: var(--aqua); }}
.trust-strip {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: white; border: 1px solid var(--border); border-radius: 14px; padding: 16px; margin: 40px 0 0; box-shadow: var(--card-shadow); }}
.trust-item {{ font-size: 0.78rem; color: var(--muted); }}
.trust-item strong {{ display: block; font-family: 'Space Grotesk', sans-serif; font-size: 1.15rem; color: var(--ink); }}
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
.faq-section {{ margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }}
.faq-section h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }}
.faq-item {{ margin-bottom: 18px; }}
.faq-item h3 {{ font-size: 0.94rem; margin: 0 0 6px; }}
.faq-item p {{ font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin: 0; }}
@media (min-width: 560px) {{ .brand-grid {{ grid-template-columns: repeat(3, 1fr); }} .trust-strip {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (min-width: 640px) {{ .lens-grid {{ grid-template-columns: 1fr 1fr; }} .category-grid {{ grid-template-columns: repeat(3, 1fr); }} .guide-mini-grid {{ grid-template-columns: 1fr 1fr; }} }}
@media (min-width: 700px) {{
  .hero {{
    grid-template-columns: 1fr 42%;
    grid-template-areas: "heading media" "lead media" "credit credit" "search search";
    align-items: start;
    gap: 8px 32px;
  }}
  .hero-media {{ max-height: none; aspect-ratio: 4 / 3; }}
  .hero-photo-credit {{ margin-top: -22px; }}
  .hero-lead {{ margin-top: 8px; }}
  .search-section {{ margin-top: 24px; }}
}}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
  <div class="hero">
    <div class="hero-heading hero-copy">
      <div class="kicker">Prissammenligning</div>
      <h1>Finn billigste kontaktlinser</h1>
    </div>
    <div class="search-section">
      <h2>Søk etter linse eller merke</h2>
      <div class="search-row">
        <label for="lens-search" class="visually-hidden" style="position:absolute;left:-9999px;">Søk etter linse eller merke</label>
        <input type="search" id="lens-search" class="search-input" placeholder="F.eks. «Biofinity» eller «Dailies»" autocomplete="off">
        <div class="search-suggestions" id="search-suggestions"></div>
      </div>
    </div>
    <div class="hero-media">
      <img src="/static/hero-eye.jpg" alt="" loading="eager">
    </div>
    <p class="hero-photo-credit">Foto: Amanda Dalbjörn / Unsplash</p>
    <div class="hero-lead">
      <p>kontaktlinser.no er en uavhengig prissammenligningstjeneste som sammenligner priser på {n_products} kontaktlinser fra {n_retailers} norske nettbutikker. Vi henter priser automatisk hver 6. time og sorterer alltid etter lavest totalpris inkludert frakt - søk eller velg en linse under for å se alle tilbud.</p>
      <div class="hero-actions">
        <a href="#merker" class="btn-primary">Se alle merker</a>
      </div>
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

  {home_faq_html}
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
{CONSENT_BANNER_HTML}
{CONSENT_SCRIPT}
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
        "answer": "kontaktlinser.no er en uavhengig prissammenligningstjeneste. Vi henter priser automatisk fra norske nettbutikkers egne nettsider og feeds hver 6. time, og viser alltid tilbudene sortert etter lavest totalpris - produktpris pluss frakt. Du kjøper ikke hos oss; vi lenker deg videre til forhandleren du velger.",
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
<style>{SHARED_STYLE}
.faq-section {{ margin-top: 36px; border-top: 1px solid var(--border); padding-top: 24px; }}
.faq-section h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.1rem; margin: 0 0 16px; }}
.faq-item {{ margin-bottom: 18px; }}
.faq-item h3 {{ font-size: 0.94rem; margin: 0 0 6px; }}
.faq-item p {{ font-size: 0.88rem; color: var(--muted); line-height: 1.6; margin: 0; }}
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
<link rel="canonical" href="{BASE_URL}/guider/">
{FONT_LINKS}
<style>{SHARED_STYLE}
.guide-card {{ display: block; text-decoration: none; color: var(--ink); background: white; border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; box-shadow: var(--card-shadow); margin-bottom: 10px; }}
.guide-card:hover {{ border-color: var(--aqua); }}
.guide-card-title {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; margin-bottom: 4px; }}
.guide-card-desc {{ font-size: 0.86rem; color: var(--muted); }}
</style>
</head>
<body>
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
    <head> (før noe annet), for de ti gamle .aspx-URL-ene fra forrige
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
<title>{escape(category["label"])} – sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(category["intro"])}">
<link rel="canonical" href="{BASE_URL}/kontaktlinser/{category_slug}/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
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

    best_band = ""
    if best:
        best_rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
        best_band = f"""<a class="best-price-band" href="{escape(best["url"])}" rel="{best_rel}">
  <div class="label-group">
    <div class="label">Laveste pris</div>
    <div class="retailer">{_retailer_badge_html(best["retailer"])}</div>
  </div>
  <div class="price">{_fmt_kr(best["total"])}</div>
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
  "description": "{escape(long_description)}",
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
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(product["name"])} – billigste pris | kontaktlinser.no</title>
<meta name="description" content="{escape(long_description[:155])}">
<link rel="canonical" href="{BASE_URL}{base_url_path}">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}
.hero {{ display: flex; align-items: center; gap: 20px; }}
.price-per-unit {{ font-size: 0.85rem; color: var(--muted); margin: -8px 0 16px; }}
.safety-notice {{ background: #FFF4E5; border: 1px solid #F0C674; border-radius: 12px; padding: 14px 16px; margin: 16px 0; font-size: 0.85rem; line-height: 1.6; color: var(--ink); }}
</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
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
    kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
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
<title>{escape(cat["label"])} – sammenlign priser | kontaktlinser.no</title>
<meta name="description" content="{escape(cat["intro"])}">
<link rel="canonical" href="{BASE_URL}/{solution_category}/">
{FONT_LINKS}
<script type="application/ld+json">{schema_json}</script>
<style>{SHARED_STYLE}</style>
</head>
<body>
{TOPBAR_HTML}
<div class="wrap">
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
    eller rangeringen av produkter eller tilbud. kontaktlinser.no er en
    uavhengig prissammenligningstjeneste, ikke en forhandler.
  </p>
</div>
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

    real_name = real_product["name"]
    real_brand = real_product["brand_label"]
    chain = label["chain"]
    private_name = label["name"]
    real_href = f'/kontaktlinser/{real_product["brand_slug"]}/{real_product["slug"]}/'
    category_label = categories[real_product["category_slug"]]["label"]

    best_band = ""
    if best:
        best_rel = "sponsored nofollow" if best["source"] == "affiliate_feed" else "nofollow"
        best_band = f"""<a class="best-price-band" href="{escape(best["url"])}" rel="{best_rel}">
  <div class="label-group">
    <div class="label">Laveste pris</div>
    <div class="retailer">{_retailer_badge_html(best["retailer"])}</div>
  </div>
  <div class="price">{_fmt_kr(best["total"])}</div>
</a>"""

    schema_json = f"""{{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "{escape(private_name)} ({escape(chain)}) er egentlig {escape(real_name)}",
  "about": {{"@type": "Product", "name": "{escape(real_name)}", "brand": {{"@type": "Brand", "name": "{escape(real_brand)}"}}}},
  "mainEntityOfPage": "{BASE_URL}/private-label/{label["slug"]}/"
}}"""

    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
{GTM_HEAD}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(private_name)} ({escape(chain)}) – hva heter den egentlig? | kontaktlinser.no</title>
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
<div class="wrap">
  <p class="breadcrumb">
    <a href="/">Hjem</a> ›
    <a href="/private-label/">Optikerkjedenes egne merker</a> ›
    {escape(private_name)}
  </p>
  <div class="hero">
    <div class="hero-copy">
      <div class="kicker">{escape(chain)} sitt eget merkenavn</div>
      <h1>{escape(private_name)} er egentlig {escape(real_name)}</h1>
      <p>{escape(chain)} selger denne linsen under sitt eget navn, {escape(private_name)}. Det er ikke en egen linsetype – det er samme produkt som {escape(real_name)} fra {escape(real_brand)}, bare i {escape(chain)} sin egen innpakning.</p>
    </div>
  </div>

  <div class="private-label-explainer">
    <p><strong>Hvorfor har den to navn?</strong> Mange optikerkjeder kjøper kontaktlinser fra de samme produsentene som selger under egne kjente merker, og pakker dem om under et eget varenavn. Selve linsen – materiale, styrkeområde og spesifikasjoner – er den samme. Det er bare emballasjen og navnet som er unikt for {escape(chain)}.</p>
  </div>

  <div class="private-label-caveat">
    <strong>Vær obs på dette før du bytter:</strong> Denne koblingen er satt sammen basert på tilgjengelig informasjon om produsent og produktspesifikasjoner. kontaktlinser.no har ingen avtale med {escape(chain)} og kan ikke garantere at koblingen stemmer i alle tilfeller – pakningsstørrelse eller tilgjengelige styrker kan for eksempel avvike. Bekreft alltid med din optiker eller synsresept at {escape(real_name)} faktisk er riktig erstatning for {escape(private_name)} før du bytter.
  </div>

  <h2>Sammenlign priser på {escape(real_name)}</h2>
  {best_band}
  <div class="offers">
    {offer_cards_html}
  </div>
  <p style="margin-top:16px;"><a href="{escape(real_href)}" style="color:var(--aqua);font-weight:600;text-decoration:none;">Se full produktside for {escape(real_name)} →</a></p>

  <p class="disclosure">
    Vi sorterer alltid etter lavest totalpris (produktpris + frakt). Vi kan få
    provisjon når du handler via lenkene, men det påvirker ikke prisen du
    betaler eller rekkefølgen på tilbudene. Priser eldre enn 24 timer eller
    varer uten bekreftet lager vises, men kan ikke vinne «laveste pris».
    kontaktlinser.no er en uavhengig prissammenligningstjeneste, ikke en
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
        sections_html += f"""<h2>{escape(chain)}</h2>
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
<title>Optikerkjedenes egne merker – hva heter linsen egentlig? | kontaktlinser.no</title>
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
<div class="wrap">
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
    produsent og produktspesifikasjoner. kontaktlinser.no har ingen avtale
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
