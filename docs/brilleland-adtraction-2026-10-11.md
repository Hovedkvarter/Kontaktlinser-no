# Brilleland – Adtraction, 11. oktober 2026

Status: implementert og testet i arbeidsgren. Eier godkjente sending til GitHub og opprettelse av PR 2026-10-11. Ikke merget eller publisert. Visuell kontroll og eiers publiseringsgodkjenning gjenstår.

## Beslutninger og omfang

- Eier bekreftet godkjent Adtraction-avtale og leverte feed-URL.
- Ekte CSV hentet 11. oktober: 922 rader, hvorav 77 kontaktlinseoppføringer.
- Gjenbruker Adtraction-mapperen med eget oppslag `adtraction_brilleland`.
- 29 feed-SKU-er dekker alle 31 eksisterende Brilleland-produktkoblinger.
  Focus Dailies/All Day Comfort har to etablerte aliaspar.
- 23 koblinger treffer eksisterende produkt-URL nøyaktig. De øvrige åtte
  er AquaComfort Plus 30 (eksakt produkt/pakningsnavn) og syv allerede
  dokumenterte iWear-identiteter i private_labels.json. Feedens bildefilnavn
  bekrefter de eksisterende 6-/30-pakningsstørrelsene for disse syv.
- Ingen nye private-label-ekvivalenser er utledet. Andre feedprodukter er
  foreløpig ikke lagt til; særlig Oxygen Presbyopia/Toric 3-pack skal aldri
  kobles til eksisterende 6-pack. Seks-pakningene bruker 40000758/40000759.
- Sporingslenken beholdes nøyaktig som levert, inkludert `to.brilleland.no`,
  `a=1611943895`, `as=2102229792`, `fid=657`. Feed-URL-ens apid er et annet
  ID-felt; det erstatter ikke `a` i ferdig genererte sporingslenker.
- Brilleland er ikke lagt til Chillouts konverteringsliste; ingen ny
  plattformintegrasjon eller feed-ID er antatt.
- Eksisterende fraktregel (59 kr, gratis over 1000 kr) er videreført.
  Feedens generiske `shipping=NO:::0 NOK` overstyrer ikke dokumentert regel.
- Ingen andre forhandleres katalogdata, SEO-URL-er eller rangering er endret.
  Katalogen er oppdatert kun med ferske Brilleland-tilbud; ikke full scraping.

## Kontroll og begrensninger

- Virkelig feedutdrag i tests/fixtures; tester dekning, pakningsforveksling,
  kilde/nettverk, frakt, ukjente produkter og affiliate-lenker i HTML.
- 7 tester bestått (Brilleland og butikkhistorikk). Statisk bygg og
  validate_build bestått: 201 av 201 katalogprodukter har priser.
- Brillelands åtte gamle produkt-URL-er svarte HTTP 403 i dette miljøet.
  Identiteter er derfor kontrollert mot eksisterende dokumentasjon og feed,
  ikke ny full kontroll av produktsidene.
- Feeden har et bildeavvik: iWear Balance Plus peker til et bildefilnavn med
  «astigmatism». Eksisterende produktbilder er ikke byttet ut. Feedbilder
  bør ikke brukes til å erstatte canonical-produktbilder uten egen kontroll.
- Visuell nettleserkontroll gjenstår: Chromium var ikke installert og nedlastingen feilet. Statisk HTML er generert og validert.
- Affiliate-lenkenes struktur/HTML er testet; klikk gjennom sporingsnettverket
  og faktisk provisjonsattribusjon er ikke bekreftet.

## Neste steg

Eier vurderer PR og godkjenner eventuell publisering. Kontroller deretter
Brilleland-tilbud live og attribusjon i Adtraction. Nye produkter fra de øvrige
feedradene og eventuell endret fraktregel behandles separat med dokumentasjon.
