"""Broad shopping landing page; existing catalogue, tiles and search only."""
import json
import math
from datetime import datetime, timezone
from html import escape

import render_templates as t

PATH = '/billige-linser-pa-nett/'
TITLE = 'Billige linser på nett – Sammenlign priser'
DESCRIPTION = ('Sammenlign priser på kontaktlinser fra norske nettbutikker. Finn billige '
               'dagslinser, månedslinser og andre linsetyper. Se priser og velg riktig produkt.')
CATEGORIES = ('dagslinser', 'manedslinser', 'toriske-linser', 'multifokale-linser')


def select_products(catalog, now):
    """Three lowest eligible box prices per category, one pack per model.

    Small trial packs (< 3 lenses) are omitted. Freshness and image provenance
    use the existing helpers, including the owner-confirmed Lensit exclusion:
    omit Lensit when cheapest (including ties) until an agreement is in place.
    """
    groups = {key: [] for key in CATEGORIES}
    for product in catalog['products']:
        category = product.get('category_slug')
        pack = t._pack_size_from_id(product['id'])
        image = t._product_image(product)
        if category not in groups or not pack or pack[1] < 3 or not image or t._is_own_illustration(image):
            continue
        offers = t.reconcile_product(product['offers'], now)
        valid = [o for o in offers if o['in_stock'] and not o['is_stale']
                 and math.isfinite(o['price_nok']) and o['price_nok'] > 0]
        if not valid:
            continue
        lowest = min(valid, key=lambda o: (o['price_nok'], o['total'], o['retailer']))
        groups[category].append(dict(product=product, offers=valid, lowest=lowest,
                                     image=image, pack=pack))
    selected = []
    for rows in groups.values():
        seen = set()
        for row in sorted(rows, key=lambda r: (r['lowest']['price_nok'], r['product']['id'])):
            if row['pack'][0] in seen:
                continue
            seen.add(row['pack'][0])
            selected.append(row)
            if len(seen) == 3:
                break
    return sorted(selected, key=lambda r: (r['lowest']['price_nok'], r['product']['id']))


GUIDE = '''<section class="budget-guide" aria-labelledby="buying-guide">
<div class="kicker">Få mer ut av prissammenligningen</div>
<h2 id="buying-guide">Slik finner du billige kontaktlinser på nett</h2>
<p>Start med navnet på linsen du allerede bruker. Den rimeligste esken i en oversikt er ikke nødvendigvis riktig linse for deg, eller den billigste løsningen over tid. Sammenlign samme produkt, riktig pakningsstørrelse og hele bestillingen.</p>
<h3>Hvor finner man de laveste prisene?</h3>
<p>Ingen butikk trenger å være billigst på alt. Søk opp linsen din og åpne produktsiden for å sammenligne butikkene vi har tilbud fra. Der kan du se frakt og når prisene ble kontrollert. Vi selger ikke linser selv; kjøp, betaling og levering skjer hos nettbutikken.</p>
<p>Utvalget over er en inngang til katalogen, ikke en test av hvilke linser som passer best. Les også <a href="/guide/hvilken-nettbutikk-har-billigst-kontaktlinser/">vår prisundersøkelse av nettbutikker</a> for et datert øyeblikksbilde. Bruk produktsidene for dagens sammenligning.</p>
<h3>Sammenlign riktig produkt og pakning</h3>
<p>Kontroller hele produktnavnet: samme merke kan ha både vanlige, toriske og multifokale varianter. Sammenlign deretter like pakninger. En lav pris for 5 linser kan ikke sammenlignes direkte med prisen for 30 eller 90 linser.</p>
<p><strong>Pris per linse = eskepris delt på antall linser.</strong> Det er nyttig når du sammenligner pakningsstørrelser av samme linse, men sier ikke alene hva en dagslinse koster sammenlignet med en månedslinse. Se <a href="/guide/pris-per-linse-slik-sammenligner-du/">slik sammenligner du pris per linse</a>.</p>
<h3>Hva koster linsene over tid?</h3>
<p>Regn for begge øyne og perioden du faktisk skal bruke linser. Ved daglig bruk av dagslinser på begge øyne trenger du 60 linser i løpet av 30 dager. To esker med 30 linser dekker da perioden, også når øynene trenger ulik styrke. En enkelt 30-pakning dekker ett øye i 30 dager.</p>
<p>For månedslinser må regnestykket følge utskiftingsplanen du har fått. Ta med linsevæske, etui og eventuelle kontroller når du vurderer samlet kostnad. Bruk ikke linsene lenger enn anbefalt for å spare penger.</p>
<h3>Er dagslinser eller månedslinser billigst?</h3>
<p>Det avhenger av produktet, hvor ofte du bruker linser og hvilke tilleggskostnader du har. Ved daglig bruk kan månedslinser gi lavere linsekostnad, men rengjøring kommer i tillegg. Bruker du linser noen få dager i måneden, kan dagslinser bli rimeligere fordi du bare åpner et nytt par de dagene du bruker dem.</p>
<p>Sammenlign <a href="/kontaktlinser/dagslinser/">dagslinser</a> og <a href="/kontaktlinser/manedslinser/">månedslinser</a> som optikeren har vurdert som aktuelle for deg. Les mer om <a href="/guide/manedslinser-vs-dagslinser/">forskjellene mellom dagslinser og månedslinser</a>.</p>
<h3>Ta med frakt, pakningsstørrelse og tilbud</h3>
<p>Den laveste eskeprisen kan gi en dyrere bestilling hvis frakten er høyere. Sammenlign totalprisen for antallet esker du trenger, og sjekk vilkårene for eventuell fri frakt. En større pakning kan gi lavere pris per linse, men binder mer penger og er ikke automatisk det beste kjøpet.</p>
<p>Kontroller om et tilbud krever abonnement, rabattkode eller at du er ny kunde. Bekreft pris og tilgjengelighet for dine styrker i butikken før betaling. Vi viser bare priser fra katalogens tilgjengelige tilbud, og kan ikke garantere den laveste prisen i hele markedet. <a href="/slik-sammenligner-vi-priser/">Les hvordan vi sammenligner priser</a>.</p>
<h3>Riktig linse og styrke kommer først</h3>
<p>Bruk kontaktlinsespesifikasjonen fra optikeren, ikke bare brillestyrken. Sjekk produkt, styrke, basiskurve og diameter, samt sylinder og akse for toriske linser og tilleggsstyrke for multifokale. Ikke bytt linsetype utelukkende fordi en annen eske er billigere; avklar et bytte med optikeren.</p>
<p>Se <a href="/guide/hvordan-kjope-kontaktlinser-pa-nett/">sjekklisten for å kjøpe kontaktlinser på nett</a>. Faglig bakgrunn: <a href="https://www.specsavers.no/hjelp/din-linseseddel">Specsavers om linseseddelen</a>.</p>
</section>'''

STYLE = '''
.budget-hero { max-width: 880px; padding: 16px 0 20px; }
.budget-hero h1 { font-size: clamp(1.65rem, 3.4vw, 2.65rem); line-height: 1.15; margin: 8px 0 12px; letter-spacing: -.025em; }
.budget-hero p { max-width: 720px; margin: 0 0 18px; }
.budget-hero .search-row { max-width: 720px; }
.budget-links, .budget-filters { display: flex; flex-wrap: wrap; gap: 8px; }
.budget-links { margin-top: 14px; }
.budget-links a, .budget-filters button { border: 1px solid var(--border); border-radius: 999px; background: white; padding: 11px 14px; font-size: .85rem; color: var(--ink); text-decoration: none; min-height: 44px; }
.budget-links a:hover, .budget-filters button:hover { border-color: var(--blue); }
.budget-filters button { cursor: pointer; }
.budget-filters button[aria-pressed="true"] { background: var(--blue); border-color: var(--blue); color: white; }
.budget-products h2 { font-size: 1.35rem; margin: 8px 0; }
.budget-note { color: var(--muted); font-size: .86rem; max-width: 850px; }
.budget-products [hidden] { display: none !important; }
.budget-filters { margin: 16px 0 10px; }
.budget-count { font-size: .82rem; color: var(--muted); }
.budget-guide { max-width: 760px; margin: 48px auto 0; padding-top: 28px; border-top: 1px solid var(--border); }
.budget-guide h2 { font-size: 1.7rem; line-height: 1.2; }
.budget-guide h3 { margin: 28px 0 8px; font-size: 1.15rem; }
.budget-guide p { margin: 10px 0; line-height: 1.75; }
.budget-guide a { text-decoration: underline; text-underline-offset: 3px; }
.budget-skip { position: absolute; left: 12px; top: -100px; z-index: 100; background: white; padding: 12px; }
.budget-skip:focus { top: 8px; }
.budget-main :focus-visible { outline: 3px solid var(--blue); outline-offset: 3px; }
@media(max-width: 600px) {
 .budget-hero { padding: 4px 0 10px; }
 .budget-main > .breadcrumb { margin: 12px 0; }
 .budget-hero .kicker { display: none; }
 .budget-filters { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; }
 .budget-filters button { flex: 0 0 auto; white-space: nowrap; }
 .budget-hero p { font-size: .9rem; }
 .budget-links a, .budget-filters button { font-size: .78rem; padding: 10px 12px; }
 .budget-guide { margin-top: 32px; }
}
'''

SCRIPT = '''
(() => {
 const filters = document.querySelector('.budget-filters');
 const cards = [...document.querySelectorAll('#budget-products .product-tile')];
 const count = document.getElementById('budget-count');
 filters.hidden = false;
 filters.addEventListener('click', event => {
   const button = event.target.closest('button[data-category]');
   if (!button) return;
   filters.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
   cards.forEach(card => { card.hidden = button.dataset.category !== 'all' && card.dataset.category !== button.dataset.category; });
   count.textContent = cards.filter(card => !card.hidden).length + ' produkter i utvalget';
 });
})();
'''


def render_budget_landing(catalog, now=None):
    now = now or datetime.now(timezone.utc)
    rows = select_products(catalog, now)
    cards = []
    items = []
    for row in rows:
        p = row['product']
        href = f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/'
        cards.append(t._render_product_tile(
            href=href, name=p['name'], image_url=row['image'],
            fallback_initials=p['brand_label'][:2], category_label=catalog['categories'][p['category_slug']]['label'],
            secondary_line_html=f'<span class="product-tile-manufacturer">{row["pack"][1]} linser per eske</span>',
            lowest=row['lowest'], other_count=0, comparison_offers=row['offers'],
            data_attr=f' data-category="{escape(p["category_slug"])}" data-product-id="{escape(p["id"])}"'))
        items.append({'@type': 'ListItem', 'position': len(items)+1, 'name': p['name'], 'url': t.BASE_URL+href})
    links = ''.join(f'<a href="/kontaktlinser/{key}/">{escape(catalog["categories"][key]["label"])}</a>' for key in CATEGORIES)
    filters = '<button type="button" data-category="all" aria-pressed="true">Alle typer</button>' + ''.join(
        f'<button type="button" data-category="{key}" aria-pressed="false">{escape(catalog["categories"][key]["label"])}</button>' for key in CATEGORIES)
    schema = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'CollectionPage', '@id': t.BASE_URL+PATH, 'url': t.BASE_URL+PATH,
         'name': TITLE, 'description': DESCRIPTION, 'inLanguage': 'nb',
         'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(items), 'itemListElement': items}},
        {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Hjem', 'item': t.BASE_URL+'/'},
            {'@type': 'ListItem', 'position': 2, 'name': 'Billige linser på nett', 'item': t.BASE_URL+PATH}]}]}
    search = t.render_guide_search_card('')
    # Reuse search markup, without guide tracking or a duplicate CTA heading.
    search = search[search.index('<div class="search-row"'):search.index('<div class="guide-cta-links">')].replace(' data-guide=""', '')
    return f'''<!DOCTYPE html>
<html lang="nb"><head>{t.GTM_HEAD}
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TITLE}</title><meta name="description" content="{DESCRIPTION}">
<link rel="canonical" href="{t.BASE_URL}{PATH}">
{t._og_meta(TITLE, DESCRIPTION, t.BASE_URL+PATH)}{t.FONT_LINKS}
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False).replace('</', '<\\/')}</script>
<style>{t.SHARED_STYLE}{STYLE}</style></head><body>
<a class="budget-skip" href="#main-content">Hopp til innhold</a>
{t.TOPBAR_HTML_NO_SEARCH}
<main id="main-content" class="wrap wrap-wide budget-main">
<p class="breadcrumb"><a href="/">Hjem</a> › Billige linser på nett</p>
<header class="budget-hero"><div class="kicker">Finn linsen din. Sammenlign prisene.</div>
<h1>Billige linser på nett – finn laveste pris</h1>
<p>Kontaktlinser.no er en uavhengig norsk prissammenligningstjeneste. Søk etter linsene du bruker, og sammenlign nettbutikkenes priser. Vi selger ikke linser selv.</p>
{search}<nav class="budget-links" aria-label="Velg linsetype">{links}</nav></header>
<section class="budget-products" aria-labelledby="product-heading">
<h2 id="product-heading">Finn et produkt å sammenligne</h2>
<p class="budget-note">Et utvalg på tvers av linsetyper, sortert etter laveste eskepris. Prisene er uten frakt.</p>
<div class="budget-filters" role="group" aria-label="Filtrer produktutvalget" hidden>{filters}</div>
<p class="budget-count" id="budget-count" role="status" aria-live="polite">{len(rows)} produkter i utvalget</p>
<div id="budget-products" class="product-tile-grid">{''.join(cards)}</div>
{'' if rows else '<p>Ingen ferske priser er tilgjengelige i utvalget akkurat nå. Søk etter linsen din eller gå til en kategori over.</p>'}
<p class="budget-note">Prisene gjelder én eske. Ulike linsetyper og pakninger dekker ulike perioder – lavest eskepris betyr ikke alltid lavest månedskostnad. Se frakt og sist kontrollerte pris på produktsiden.</p>
<details class="budget-note"><summary>Slik velger vi produktene</summary><p>Inntil tre produkter per linsetype, valgt etter laveste eskepris blant ferske tilbud på lager med produktbilde. Én pakning per modell, minst tre linser per eske. Hele utvalget er sortert etter eskepris, uten frakt. Lensit er foreløpig utelatt når de har lavest totalpris, fordi vi ikke har en avtale med dem.</p></details>
<p class="disclosure">Vi kan få provisjon når du handler via lenkene på produktsidene. Tilbudene som inngår i sammenligningen, sorteres etter pris. Se «Slik velger vi produktene» for avgrensningen av utvalget. Et «Spar»-merke viser forskjellen mot høyeste tilgjengelige butikkpris for samme pakning, uten frakt – ikke en førprisrabatt.</p>
</section>{GUIDE}</main>
<script>{SCRIPT}</script>{t.render_footer()}{t.CONSENT_BANNER_HTML}{t.CONSENT_SCRIPT}
</body></html>'''
