# Mobilkort – referanse 003

Dato: 10. oktober 2026. Status: revidert forhåndsvisning, ikke publisert.
Grunnlag: main cdb1da843c3afbd6fddf384ee045f4b1d14f6f09. PR #6 er utkast.

## Brukerens korrigering

To kort per rad på mobil. Knappen skal ligne bilde 003: jevn blåfarge, lettere tekst, ingen pil. Under prisen skal det kun stå «hos X butikker», uten butikknavn og uten «+ X butikker». Rødt sparemerke over produktbildet.

## Implementert

- To mobilkolonner opptil 600 px, hele produktnavn, større bildefelt og kompakte kort.
- Blå knapp #0866d9, skriftvekt 500, avrunding 7 px, minst 44 px trykkhøyde.
- Rødt «Spar X %»-merke på mobil. Rødfargen #d0443b gir hvit tekst kontrast 4,59:1.
- Spar = (høyeste minus laveste pris) / høyeste pris for samme produkt/pakning, uten frakt. Hele prosent avrundes ned. Bare ferske, positive tilbud på lager og én pris per butikk inngår. Ingen merke ved én butikk, like priser eller forskjell under 1 %. Ingen på private-label-illustrasjoner.
- Merkets forklaring er tilgjengelig ved fokus/tapp/hover og som aria-label. Det er prisforskjell mellom butikker, ikke førprisrabatt. Ingen overstrøket førpris.
- Butikkantall og kortets laveste pris bruker samme gyldige tilbudsutvalg. Butikknavn er fjernet fra kortenes prislinje på alle skjermbredder. CTA-pilen er fjernet i den delte malen. Desktopens øvrige layout er bevart.

## Kontroll

- Samme lagrede katalog og referansetid som første forhåndsvisning: 2026-10-10T02:01:37.063164+00:00. Dette er ikke verifiserte sanntidspriser.
- 426 sider: schema/skript, canonical og HTML-lenkemål uendret, kontrollert med HTML-parser.
- Byggevalidator OK: 201/201 produkter har priser.
- test_seo_schema.py og test_product_seo_growth.py: bestått. Fire nye tester i test_product_tile_savings.py dekker ugyldige/gamle/utsolgte tilbud, unike butikker, ett tilbud, like priser og prosentavrunding.
- Chromium/Playwright før/etter ved 320/375/390/600/768/1024/1440 px på dagslinser og Acuvue: to mobilkolonner uten kort-overflyt. Eksisterende side-overflyt på Acuvue ved 320 px er uendret.
- Kontroll ved 375 px uten JavaScript på begge sider: to kolonner, ingen overflyt i kort.
- Skjermbilder bruker eksisterende bilder fra lokale filer og midlertidig cache av eksisterende feed-URL-er. Ingen nye produktbilder. Eksterne scripts/webfonter blokkert; systemfont-fallback i skjermbildene.
- Bygg bruker tom clickout-mapping. Produksjonens affiliateflyt er ikke ende-til-ende-testet; lenkemål og scripts er uendret.

## Gjenstår

Brukerens visuelle vurdering før publisering. Bedre partnerbilder og egen bildehosting er fortsatt åpent; gjenbruk/egen hosting avklares per kilde, kilde og rettighet beholdes internt.

Ingen merge, deploy eller produksjonsendring. Main-merge utløser publisering og krever uttrykkelig godkjenning.
