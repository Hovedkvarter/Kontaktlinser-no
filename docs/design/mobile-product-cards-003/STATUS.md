# Mobilkort – referanse 003

Dato: 10. oktober 2026. Status: implementert på arbeidsgren, ikke publisert.
Grunnlag: main cdb1da843c3afbd6fddf384ee045f4b1d14f6f09.

## Beslutning

Brukeren valgte designarkivets bilde 003 som kortreferanse, med to kort i bredden på mobil. Referansens priseksempler og spareprosenter er ikke faktiske data.

## Endring

Kun CSS i den delte produktkortmalen: to like kolonner opptil 600 px, kompakte bilder og kort, fullstendige produktnavn, tydelige priser og blå sammenligningslenker med minst 44 px høyde. Produsent-/merkeekstralinjer og tekniske spesifikasjonsrader skjules på mobil. Lenker til private-label-ekvivalenter beholdes. Desktopregler er uendret. Ingen nye sparemerker eller overstrøkne priser.

## Kontroll

- Lokal før/etter fra samme katalog og samme referansetid: 2026-10-10T02:01:37.063164+00:00. Skjermbildene viser dette lagrede prissnapshotet, ikke verifiserte sanntidspriser.
- 426 HTML-filer identiske utenfor style-blokkene: innhold, lenker, schema, metadata og JavaScript uendret.
- Byggevalidator: 201/201 produkter har priser, OK.
- test_seo_schema.py og test_product_seo_growth.py: alle bestått.
- Chromium/Playwright: kategori dagslinser og merke Acuvue før/etter ved 320, 375, 390, 600, 768, 1024 og 1440 px. To kort per rad ved alle mobilbredder; ingen overflyt i kort. Se layout-checks.json.
- Eksisterende side-overflyt på Acuvue ved 320 px finnes både før og etter. Ingen ny side-overflyt ved øvrige testbredder.
- Bilder lastet fra eksisterende lokale filer/eksisterende feed-URL-er til midlertidig testcache. Ingen nye produktbilder lagt til. Eksterne scripts og webfonter blokkert i nettlesertesten; systemfont-fallback brukt i skjermbildene.
- Lokal bygging bruker tom clickout-mapping for å unngå API-kall. Produksjonens affiliateflyt er ikke ende-til-ende-testet; koden og lenkemarkup er uendret.

## Åpent og neste steg

Visuell vurdering av de vedlagte mobilskjermbildene før publiseringsgodkjenning. Bedre partnerbilder og egen bildehosting er separat gjenstående arbeid: avklar gjenbruk/egen hosting per kilde, behold kilde og rettighet internt, bruk egne beskrivende bilde-URL-er og korrekte alt-tekster/strukturerte bildereferanser.

Ingen merge, deploy eller produksjonsendring er utført. Main-push/merge utløser publisering og krever brukerens godkjenning.
