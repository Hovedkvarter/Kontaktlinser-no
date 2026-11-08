"""Seasonal shopping page using the existing catalogue, search and offer rules.

Campaigns are editorial: never infer a Black Friday sale from a low price or
from the difference between stores. No confirmed campaign is registered yet.
"""
import json
from datetime import datetime, timezone
from html import escape

import render_templates as t
from budget_landing import select_products, CATEGORIES, STYLE, SCRIPT

PATH = '/black-friday-kontaktlinser/'
TITLE = 'Black Friday på kontaktlinser – sammenlign priser og tilbud'
DESCRIPTION = ('Finn lave priser på kontaktlinser og se bekreftede Black Friday-tilbud når de blir tilgjengelige. '
               'Sammenlign linsen din hos norske nettbutikker.')

BF_STYLE = """
@media (min-width: 1000px) { .budget-products .product-tile-grid { grid-template-columns: repeat(5,minmax(0,1fr)); } }
.bf-lead { font-weight: 800; color: var(--ink); }
.bf-campaigns { margin-top: 32px; padding: 24px; border: 1px solid var(--border); border-radius: 18px; background: white; }
.bf-campaigns h2 { margin: 0 0 10px; }
.bf-campaigns p { margin: 0; line-height: 1.65; }
.bf-tips { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 24px; }
.bf-tips h3 { margin-top: 8px; }
@media (max-width: 699px) { .bf-tips { grid-template-columns: 1fr; gap: 8px; } .bf-campaigns { padding: 18px; } }
"""

# Replace this empty-state with reviewed campaign content only when source,
# dates, eligible products and terms have been documented. Ordinary catalogue
# price imports must never automatically convert this into a campaign claim.
CAMPAIGNS = '''<section class="bf-campaigns" aria-labelledby="campaign-heading">
<h2 id="campaign-heading">Bekreftede Black Friday-tilbud</h2>
<p>Vi har foreløpig ingen bekreftede Black Friday-kampanjer å vise her. Du kan allerede sammenligne dagens priser i utvalget over. Når en kampanje er bekreftet, viser vi hvilke produkter den gjelder og eventuelle vilkår.</p>
</section>'''

GUIDE = '''<section class="budget-guide" aria-labelledby="buying-guide">
<div class="kicker">Gjør et godt kjøp</div>
<h2 id="buying-guide">Slik handler du kontaktlinser under Black Friday</h2>
<div class="bf-tips">
<div><h3>Start med din egen linse</h3><p>Søk etter hele produktnavnet på esken. Sammenlign samme modell og variant, og kontroller styrke og øvrige linseverdier før du bestiller.</p><p><a href="/guide/forsta-kontaktlinseresepten/">Forstå linseseddelen</a></p></div>
<div><h3>Velg riktig pakningsstørrelse</h3><p>Sammenlign pris per linse når samme modell finnes i flere pakninger. En rimeligere eske kan inneholde færre linser.</p><p><a href="/guide/pakningsstorrelse-30-vs-90/">30 eller 90 linser?</a></p></div>
<div><h3>Ta med frakten</h3><p>Prisen for én eske er et utgangspunkt. Se totalprisen for antallet esker du trenger, og kontroller eventuelle rabattvilkår i nettbutikken.</p><p><a href="/guide/kjope-kontaktlinser-for-tre-seks-eller-tolv-maneder/">Kjøpe for tre, seks eller tolv måneder?</a></p></div>
</div>
<h3>Black November, Black Week og Black Friday</h3>
<p>Butikkene kan ha ulike kampanjeperioder. Vi samler bekreftede kampanjer på denne siden, slik at du kan finne frem gjennom november. Start- og sluttdato følger den enkelte butikkens vilkår.</p>
<h3>Hva viser prisene på denne siden?</h3>
<p>Produktkortene viser laveste tilgjengelige eskepris blant butikkene som inngår i vår sammenligning. På produktsiden finner du butikkprisene, frakt og tidspunktet da prisene sist ble kontrollert. En lav pris er ikke automatisk en Black Friday-kampanje.</p>
<p>Du finner også <a href="/billige-linser-pa-nett/">billige linser på nett hele året</a> og <a href="/guide/hvilken-nettbutikk-har-billigst-kontaktlinser/">vår daterte prisundersøkelse av nettbutikker</a>.</p>
</section>'''


def render_black_friday(catalog, now=None):
    now = now or datetime.now(timezone.utc)
    rows = select_products(catalog, now, per_category=8)[:30]
    cards = []
    items = []
    for row in rows:
        p = row['product']
        href = f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/'
        cards.append(t._render_product_tile(
            href=href, name=p['name'], image_url=row['image'],
            fallback_initials=p['brand_label'][:2], category_label=catalog['categories'][p['category_slug']]['label'],
            secondary_line_html=f'<span class="product-tile-manufacturer">{row["pack"][1]} linser per eske</span>',
            lowest=row['lowest'], other_count=row['store_count'] - 1,
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
            {'@type': 'ListItem', 'position': 2, 'name': 'Black Friday på kontaktlinser', 'item': t.BASE_URL+PATH}]}]}
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
<style>{t.SHARED_STYLE}{STYLE}{BF_STYLE}</style></head><body>
<a class="budget-skip" href="#main-content">Hopp til innhold</a>
{t.TOPBAR_HTML_NO_SEARCH}
<main id="main-content" class="wrap wrap-wide budget-main">
<p class="breadcrumb"><a href="/">Hjem</a> › Black Friday på kontaktlinser</p>
<header class="budget-hero"><div class="kicker">Black November · Black Week · Black Friday</div>
<h1>Black Friday på kontaktlinser</h1>
<p class="bf-lead">Lave priser på kontaktlinser – og bekreftede Black Friday-tilbud</p>
<p>Søk etter linsene du bruker og sammenlign norske nettbutikker. Bekreftede kampanjer legges til når de er tilgjengelige.</p>
{search}<nav class="budget-links" aria-label="Velg linsetype">{links}</nav></header>
<section class="budget-products" aria-labelledby="product-heading">
<h2 id="product-heading">Dagens priser på kontaktlinser</h2>
<p class="budget-note">Utvalget er sortert etter flest butikker. Prisene gjelder én eske, uten frakt.</p>
<div class="budget-filters" role="group" aria-label="Filtrer produktutvalget" hidden>{filters}</div>
<p class="budget-count" id="budget-count" role="status" aria-live="polite">{len(rows)} produkter i utvalget</p>
<div id="budget-products" class="product-tile-grid">{''.join(cards)}</div>
{'' if rows else '<p>Ingen ferske priser er tilgjengelige i utvalget akkurat nå. Søk etter linsen din eller gå til en kategori over.</p>'}
<p class="budget-note">Prisene gjelder én eske. Ulike linsetyper og pakninger dekker ulike perioder – lavest eskepris betyr ikke alltid lavest månedskostnad. Se frakt og sist kontrollerte pris på produktsiden.</p>
<details class="budget-note"><summary>Slik velger vi produktene</summary><p>Inntil 30 produkter totalt og åtte per linsetype, valgt etter flest unike butikker med ferske tilbud på lager og produktbilde. Én pakning per modell, minst tre linser per eske. Hele utvalget er sortert etter antall butikker, flest først. Ved likt antall prioriteres laveste eskepris, uten frakt. Flere tilbud fra samme butikk teller bare én gang. Lensit er foreløpig utelatt når de har lavest totalpris, fordi vi ikke har en avtale med dem.</p></details>
<p class="disclosure">Vi kan få provisjon når du handler via lenkene på produktsidene. Tilbudene som inngår i sammenligningen, sorteres etter pris. Se «Slik velger vi produktene» for avgrensningen av utvalget. Produktutvalget viser dagens priser. Produktene er ikke merket som Black Friday-tilbud uten en bekreftet kampanje.</p>
</section>{CAMPAIGNS}{GUIDE}</main>
<script>{SCRIPT}</script>{t.render_footer()}{t.CONSENT_BANNER_HTML}{t.CONSENT_SCRIPT}
</body></html>'''
