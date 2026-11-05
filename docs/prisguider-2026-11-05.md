# Redaksjonelle prisguider · november 2026

Eier godkjente opprettelse og publisering av tre prisguider 5. november. Artiklene ligger i `site_generator/price_guides.py`. /guider/, forsiden, utvalgte eldre guider og guidekartet lenker til dem. Lastmod følger redaksjonell måledato.

## Prisundersøkelsen

Første måling er 5. november. De 20 pakningene (én per modell) og de seks butikkene i artikkelen er det faste utvalget. Bruk de samme pakningene, også om en butikk mangler i en senere måling. Merk en manglende pris eller dekning eksplisitt, og dokumenter eventuelle endringer av utvalget. Alle butikkene leverte kontaktlinser via produktfeed ved første måling. Butikkutvalget er fast og uavhengig av plassering.

- [Priser, frakt og lagerstatus på måledagen](https://github.com/Hovedkvarter/Kontaktlinser-no/blob/d321de2bd71632d53f2dcc62baa58380a864f13e/site_generator/catalog_live.json).
- Beregn for én og to esker med `offer.compute_shipping_nok` for ordresummen. Ta bare med tilbud på lager, med fersk kontroll og kjent frakt. Tell alle delte førsteplasser. Første måling ga 113 tilbud og 226 ordresummer. Lenson var billigst alene eller delt på henholdsvis 12 og 14 pakninger.
- Ved neste månedsmåling skal nye og forrige tall kunne sammenlignes fra det daterte kildegrunnlaget. Behold nettadresse og opprinnelig publiseringsdato. Angi ny observasjonsdato og oppsummer hva som har endret seg.

## De to andre guidene

Prishistorikken gjelder laveste registrerte produktpris før frakt i perioden 7. oktober til 5. november. Den kan leses i [prishistorikken på måledagen](https://github.com/Hovedkvarter/Kontaktlinser-no/blob/d321de2bd71632d53f2dcc62baa58380a864f13e/site_generator/price_history.json). Leveringseksemplene holder butikk og pris fast per modell og sammenligner like mange hele esker.

Det finnes en eldre, prisavhengig visningsregel for Lensit i `reconcile_product`. Tall fra de synlige produktsidene kan derfor avvike fra råkatalogen. Prisundersøkelsen bruker et uttrykkelig navngitt utvalg gjennom hele tabellen. Historikkartikkelen beskriver butikkprisene som ble vist. Ingen av undersøkelsene dekker hele det norske markedet.

## Kontroll før og etter publisering

Bygg fra den inncheckede katalogen. Kjør byggevalidering, SEO-testene og søketestene. Kontroller på mobil og desktop at tabellene kan leses og at alle produktlenker fører til riktig variant. Etter publisering kontrolleres HTTP, kanonisk adresse, artikkeldata og guidekart på det aktive domenet. Bygg-, publiserings- og kontrollresultatet føres på endringens pull request.
