# Startside: kontaktlinser

Dato: 2026-11-08. Status: implementert og lokalt kontrollert; ikke publisert.

## Beslutninger
- Startsiden dekker den brede intensjonen kontaktlinser; /billige-linser-pa-nett/ beholder prisorientert kjøpsintensjon.
- Brukerens ordrette title, H1, introduksjon og seksjonsoverskrifter er brukt.
- Behold Mulish, søk, bilder, navigasjon og eksisterende mobilrekkefølge.

## Implementert
- Ny title, metabeskrivelse, Open Graph-tekst og tydelige H2-er.
- Korte forklaringer av linsetyper og tre steg for prissammenligning med tre eksisterende interne guidelenker.
- Kun hjemmesidens renderfunksjon endret. Ingen endringer i prisimport, rangering, affiliate, GTM, GA4 eller samtykke.

## Kontroll
- Fullt bygg fra eksisterende katalog med samme tidspunkt før/etter: bare index.html endret; 488 øvrige HTML-filer identiske.
- 22 tester bestått: test_search_rendering, test_budget_landing, test_product_tile_savings.
- validate_build.py: 231/231 produktsider med priser OK. test_seo_schema.py: bestått.
- Én H1, selvrefererende canonical, JSON-LD og lokale interne lenkemål kontrollert. Ingen nye URL-er eller sitemap-regler.
- Desktop og mobil visuelt kontrollert; 360 og 753 CSS-piksler uten horisontal overflyt. Ved ekstremt smal 305 px måles 1 px overflyt i eksisterende layout.
- Biofinity-søk viser 13 treff og eksisterende produktforslag.
- Skjermbilder: desktop.jpg, mobile.jpg og compare.jpg. Mobilvisning via iframe, ikke fysisk enhet.

## Åpent og neste steg
- Draft PR og CI gjennomgås før publisering. Publisering krever eierens godkjenning.
- Ingen garanti om bedre rangering. Vurder utvikling i samme søkeord og enhet etter eventuell publisering.
