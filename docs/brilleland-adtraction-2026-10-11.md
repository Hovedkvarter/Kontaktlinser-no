# Brilleland / Adtraction – full feedgjennomgang 11. oktober 2026

Status: klar for publisering via PR #24. Eier godkjente publisering av
dokumenterte koblinger 11. oktober 2026; uavklarte oppføringer holdes tilbake. Denne revisjonen erstatter første runde
som bare omfattet 31 eksisterende produktkoblinger.

## Resultat

- Hele feeden: 922 rader. 77 kontaktlinseoppføringer er vurdert enkeltvis.
- 65 utvalgte feed-SKU-er gir Brilleland-tilbud på 67 produktsider, inkludert
  de to etablerte Focus Dailies/All Day Comfort-aliasene.
- 61 eksisterende katalogprodukter får tilbud. Seks nye produkter opprettes:
  Biofinity Toric 3, Biofinity Multifocal 3, Biofinity XR Toric 6,
  Proclear Toric 3, Proclear Multifocal 3 og MiSight 1 day 30.
- 9 nye dokumenterte iWear-aliaser gir søk/egne merkesider for koblingene.
- TOTAL30 Multifocal LOW/MED/HIGH er tre rader til samme produktside,
  alle 990 kr i eksporten. Kun SKU 40000718 brukes som tilbud. 40000719 og
  40000720 er dokumenterte addisjonsvarianter, ikke ekstra butikker/tilbud.
  Vi beregner ingen syntetisk laveste pris på tvers av addisjonsvariantene.
- Ni rader avventer dokumentert produsentidentitet: Connect (3), Flex (3)
  og Slim (3). Pakningene er kjent. Sekundære sammenligningssider antyder
  MIRU, men dette er ikke tilstrekkelig til å publisere identiske-linse-koblinger.
  Disse er ikke aktivert og ikke opprettet som konkurrerende duplikatprodukter.
- Fullstendig regnskap over samtlige 77 SKU-er, status, produkt-ID-er og
  kilder: `docs/brilleland-feed-audit.json`.

## Kildegrunnlag og avgrensninger

Eksportens produktnavn og pakninger er kontrollert mot Brillelands kategori-
og produktsider der feedtittel mangler antall. Etablerte private labels er
bevart; nye CooperVision-koblinger er støttet av Lensways egen varemerketabell.
Primærkilder brukt:

- https://www.brilleland.no/kontaktlinser/iwear/
- https://www.brilleland.no/kontaktlinser/acuvue/
- https://www.brilleland.no/kontaktlinser/dailies/
- https://www.brilleland.no/kontaktlinser/air-optix-/
- https://www.lensway.no/optikerkjedenes-varemerker-editorial
- https://www.brilleland.no/kontaktlinser/iwear/iwear-activ-presbyopia-3-add-30-pack/
- https://www.linsen.dk/shop11/iwear-oxygen-astigmatism-xr-synoptik-kontaktlinser
- https://www.brilleland.no/kontaktlinser/total30/total30-multifocal-6-pack/
- https://www.brilleland.no/kontaktlinser/misight/misight-1-day-30-pack/

MiSight 1 day og MyDay MiSight er ulike produktdesign. Brillelands produkt
oppgir 60 % vann og BC 8,7; det legges derfor til med egen stabil ID/URL,
ikke som et tilbud på MyDay MiSight. Ingen behandlingsråd eller effektprosent
kopieres til den nye siden.

Frakt beholdes: 59 kr / gratis over 1000 kr. Feedens generiske nullfrakt
brukes ikke som bevis på endret regel. Brillelands sider bekrefter fortsatt
grensen på 1000 kr. Eksisterende produktbilder og URL-er er ikke byttet ut.
Nye pakninger arver ikke et manuelt bilde som viser feil antall; de bruker
det lisensierte bildet fra den aktuelle feedraden via eksisterende bildelogikk.
Feedbildene for Balance Plus og TOTAL30 Toric har misvisende filnavn;
eksisterende manuelt kuraterte bilder vinner over dem.

Koden gjenbruker Adtraction-mapperen med separat `adtraction_brilleland`-
oppslag. Sporings-URL-er beholdes nøyaktig; ingen nye Chillout-ID-er antas.
Alle øvrige butikktilbud og deres måletidspunkt bevares. Katalogen er
oppdatert bare for Brilleland; ingen unødvendig full scraping.

## Verifisert og gjenstående

- 10 tester: feeddekning, alle 77 klassifisert, 3/6-pakninger, MiSight-
  avgrensning, Clariti 3 Add-avgrensning, TOTAL30 uten duplikat, gyldige
  produkt-/alias-ID-er, affiliate-HTML, frakt og butikkhistorikk.
- Statisk generering og validate_build består: 207/207 produkter har priser.
- Visuell nettleserkontroll gjenstår; Chromium mangler og nedlasting feilet.
- Sporingsstruktur og HTML er kontrollert. Endelig redirect og faktisk
  provisjonsattribusjon er ikke bekreftet.
- Brilleland ga 403 ved direkte henting fra kodearbeidsmiljøet. Offentlige
  sider er kontrollert via nettsøk. AquaComfort Multifocal har motstridende
  URL-suffiks i feed og kategorilenke; begge ga 404 gjennom nettsøket,
  mens kategorisiden fortsatt viser 30-pakningen med samme pris. Kontroller
  denne sporingslenkens sluttdestinasjon før aktivering. SKU 40000310 er
  tatt ut av matching og katalogtilbud. Ingen URL er gjettet om.

Neste steg etter publisering: avklar de ni iWear-identitetene og kontroller
den avvikende AquaComfort-lenken sammen med eier.
