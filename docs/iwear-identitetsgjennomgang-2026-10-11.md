# iWear Connect, Flex og Slim: identitetsgjennomgang 11. oktober 2026

Status: publisert og produksjonskontrollert 11. oktober 2026 via PR #26.
https://github.com/Hovedkvarter/Kontaktlinser-no/pull/26
Konklusjon: høy sikkerhet for de foreslåtte koblingene under. Fem originalprodukter
fantes i katalogen, fire manglet. Dette er ni nye iWear-aliaser, ikke ni nye originalprodukter.
De fire nye ID-ene nedenfor er nå publisert.

## Metode og bevisstyrke

Kontrollert alle ni faktiske Brilleland-produktadresser direkte (HTTP 200), pakning,
basekurve, diameter, styrkeområde, sylinder/akser eller addisjon og vanninnhold.
Sammenlignet med Menicons ni tilsvarende produktsider og iWears egne spesifikasjoner.
iWears sideinnhold inkluderer alle varianter i __NUXT_DATA__; disse variantdataene
ble lest separat fordi vanlige tekstuttrekk viser sfærisk variant selv med variantparameter.

Direkte navnekobling finnes hos optikerkjeden Lafam for sfærisk Connect og Slim:
- https://www.lafam.com.co/products/i-wear-connect (referanse MIRU 1 MONTH MENICON IWEAR CONNECT)
- https://www.lafam.com.co/products/i-wear-slim (referanse MIRU 1 DAY MENICON FLAT PACK IWEAR SLIM)

For øvrige varianter er identiteten en samlet, sterk slutning fra primærkildene,
ikke en skriftlig produsenterklæring om privatmerkeekvivalens. Materiale alene er
ikke brukt som bevis: geometri, styrkeområder, variantdesign, teknologinavn og
emballasje er sammenholdt. Lenspricers merketabell ble brukt som sekundær kryssjekk,
ikke som eneste grunnlag.

## Konkret koblingsplan

| SKU | iWear | Menicon-produkt | Produkt-ID hos oss | Status | Pakning | BC | DIA |
|---|---|---|---|---|---|---|---|
| 40000699 | Connect | miru-1month-menicon | miru-1month-6pk | Ny | 6 | 8,3 / 8,6 | 14,0 |
| 40000700 | Connect Astigmatism | miru-1month-menicon-toric | miru-1month-toric-6pk | Ny | 6 | 8,6 | 14,0 |
| 40000733 | Connect Multifocal | miru-1month-menicon-multifocal | miru-1month-multifocal-6pk | Ny | 6 | 8,6 | 14,2 |
| 40000690 | Flex | miru-1day-upside | miru-1day-upside-30pk | Eksisterer | 30 | 8,4 | 14,2 |
| 40000692 | Flex Astigmatism | miru-1day-upside-toric | miru-1day-upside-astigmatism-30pk | Eksisterer | 30 | 8,4 | 14,2 |
| 40000694 | Flex Multifocal | miru-1day-upside-multifocal | miru-1day-upside-multifocal-30pk | Eksisterer | 30 | 8,4 | 14,2 |
| 40000672 | Slim | miru-1day-flat-pack | miru-1day-flatpack-30pk | Ny | 30 | 8,6 | 14,2 |
| 40000674 | Slim Astigmatism | miru-1day-flat-pack-toric | miru-1day-flatpack-astigmatism-30pk | Eksisterer | 30 | 8,6 | 14,5 |
| 40000676 | Slim Multifocal | miru-1day-flat-pack-multifocal | miru-1day-flatpack-multifocal-30pk | Eksisterer | 30 | 8,4 | 14,4 |

## Kjennetegn og variantkontroll

- Connect: asmofilcon A, 40 % vann, månedslinse. Sfærisk 8,3/8,6 og 14,0;
  torisk 8,6/14,0 og Visiostable; multifokal 8,6/14,2, Dual Balanced Design,
  LOW/HIGH og trekantmarkering ved høy addisjon. Brilleland selger 6-pakning av alle tre.
- Flex: midafilcon A, 56 % vann, dagslinse, 8,4/14,2, MeniSilk Air,
  NanoGloss Pro og Smart Touch. Sfærisk styrke +6 til -13. Torisk 0 til -10,
  sylinder -0,75/-1,25/-1,75; multifokal +5 til -10 med LOW/HIGH og Neuro Adaptive.
  Menicon oppgir Dk/t 91 for sfærisk/multifokal og 80 for torisk; samme i iWear-data.
- Slim: hioxifilcon A, 57 % vann, dagslinse, CENTRAFORM og flat Smart Touch-emballasje.
  Sfærisk 8,6/14,2, +4 til -10; torisk 8,6/14,5, +2 til -10 med akser
  15/90/165/180; multifokal 8,4/14,4, +4 til -10, LOW. Variantene må holdes atskilt.

## Avvik som er kontrollert

- iWears innbakte spesifikasjon for Slim Toric har diameter 4.5mm. Brilleland,
  Synoptik og Menicon oppgir 14,5 mm. Dette vurderes som en skrivefeil hos iWear;
  4,5 skal ikke kopieres.
- iWear Flex Toric lister bare seks akser. Brilleland og Menicon viser 10–180
  i trinn på ti. iWears tabell er dermed ikke en fullstendig norsk variantliste.
- Menicons sfæriske og toriske 1month-sider har tabelltekst «Daily replacement»,
  i strid med produktnavn og omtalen av månedslinser. Brilleland og iWear bekrefter
  månedlig utskifting. Ikke kopier denne tabellfeilen.
- Lafams Slim-side oppgir Dk/t 160, mens iWear oppgir 19,4. Lafam brukes for den
  uttrykkelige produktreferansen, ikke som fasit for alle tekniske spesifikasjoner.
- Brillelands addisjonsvalg 1,00/2,00 må ikke ukritisk omskrives til produsentens
  addisjonsintervaller. Bevar variantnavn og dokumenterte LOW/HIGH-grupper.

## Eksisterende iWear-dekning

24 aliaser finnes allerede; 22 peker til produkter med Brilleland-tilbud.
Oxygen XR peker fortsatt til Biofinity XR 3-pakning, mens feedtilbudet er korrekt
koblet til Biofinity XR 6-pakning. Aliasets mål bør rettes separat uten å endre URL.
Go Astigmatism / Biomedics Toric finnes ikke i Brilleland-feeden og kan ikke få
et feedtilbud uten ny kilde. Alle 25 iWear-rader utenom Connect/Flex/Slim i feeden
har allerede produktkobling (inkludert flere pakninger).
Ingen eksisterende private-label-aliaser peker til de fem MIRU-produktene.
De fem MIRU-produktsidene er bekreftet live med HTTP 200 og uten Brilleland-tilbud.

## Primærkilder per variant

- iWear Connect: https://www.brilleland.no/kontaktlinser/iwear/iwear-connect/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1month-menicon
- iWear Connect Astigmatism: https://www.brilleland.no/kontaktlinser/iwear/iwear-connect-astigmatism/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1month-menicon-toric
- iWear Connect Multifocal: https://www.brilleland.no/kontaktlinser/iwear/iwear-connect-multifocal/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1month-menicon-multifocal
- iWear Flex: https://www.brilleland.no/kontaktlinser/iwear/iwear-flex/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1day-upside
- iWear Flex Astigmatism: https://www.brilleland.no/kontaktlinser/iwear/iwear-flex-astigmatism/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1day-upside-toric
- iWear Flex Multifocal: https://www.brilleland.no/kontaktlinser/iwear/iwear-flex-multifocal/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1day-upside-multifocal
- iWear Slim: https://www.brilleland.no/kontaktlinser/iwear/iwear-slim/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1day-flat-pack
- iWear Slim Astigmatism: https://www.brilleland.no/kontaktlinser/iwear/iwear-slim-astigmatism/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1day-flat-pack-toric
- iWear Slim Multifocal: https://www.brilleland.no/kontaktlinser/iwear/iwear-slim-multifocal/
  Menicon: https://www.menicon.com/consumer/products/disposable-lenses/miru-1day-flat-pack-multifocal

- iWear: https://iwearlens.com/products/connect
- iWear: https://iwearlens.com/products/flex
- iWear: https://iwearlens.com/products/slim
- Synoptik, Slim torisk: https://www.synoptik.dk/kontaktlinser/iWear_Slim_Astigmatism_30_884465599497/884465599497
- Sekundær kryssjekk: https://lenspricer.no/informasjon/private-label-kontaktlinser

Anbefalt implementering: fem eksisterende produktkoblinger, fire nye originalprodukter,
ni iWear-aliaser og en separat rettelse av Oxygen XR-aliasets pakkemål. Opprett ikke
parallelle originalprodukter under iWear-navnet. Frakt og affiliate-URL beholdes fra
etablert import. Hele feeden skal hentes på nytt før aktivering; ikke bruk søkemotorens
bufrede kampanjepriser.

## Gjennomføring

Fire nye MIRU-produkter, fem eksisterende produkter oppdatert med spesifikasjoner,
ni iWear-aliaser og ni nye Brilleland-koblinger. Oxygen XR-aliasets URL beholdes,
men peker nå til Biofinity XR 6-pakning. MIRU Flatpack og 1month får separate
produktfamilier; iWear Connect/Flex/Slim får automatisk egne seriesider.
MIRU-merketeksten inkluderer nå månedslinser. Nye produkter bruker lisensierte
feedbilder; eksisterende manuelle bilder er beholdt. Andre butikktilbud bevares.
Alle 77 linserader er håndtert: 75 aktive SKU-er og to grupperte TOTAL30-varianter.
Dette gir 77 Brilleland-tilbud på 77 produktsider og 211 produkter i katalogen.

## Sluttkontroll

- PR #26 slått sammen: `301b2f5b770bf8bb6361a7e3977b783e62051127`.
- 13 tester bestått; full sidegenerering og validering bestått, 211/211 produkter med pris.
- CI 38178361507, produksjonsbygg 38178443385 og Pages 38178488490 fullført uten feil.
- Alle 25 berørte produkt-, alias- og seriesider kontrollert live med HTTP 200 og riktig hovedoverskrift.
- Oxygen XR kontrollert live: lenker til Biofinity XR 6-pakning, ingen lenke til 3-pakning.
- Internlenker og canonical kontrollert i generert bygg. MIRU 1month-produktsiden og iWear Connect-seriesiden visuelt kontrollert i nettleser; aliasets pris og produkt-/serielenker kontrollert i samme nettleser.
- Tilbud fra øvrige butikker er verifisert uendret. iWear Go Astigmatism får fortsatt ikke et Brilleland-tilbud siden produktet ikke finnes i feeden.
