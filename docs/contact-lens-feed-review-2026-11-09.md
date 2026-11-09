# Nye everclear ULTIMATE1-pakninger – 9. november 2026

## Grunnlag og avgrensning

VEDTATT: Eier ba 9. november om å opprette og publisere de nye produktene fra feedoppsummeringen. Eksisterende Kontaktlinser-rutine fra PR #43 er gjenbrukt. Base: `6d3e05c12bdfec4639edf913377543e504d5e6c8`. Gjeldende Project Instructions / Continuous Learning og relevante identitetsbeslutninger i Architecture Decision Log er lest via Drive. Dette er en lokal katalogutvidelse, ikke endring i Chillout Core eller Ads-piloten.

OBSERVERT: Fullfeedene fra de to eksisterende Tradedoubler-annonsørene Lensway og Lenson er kontrollert 9. november. Ingen butikk- eller Alensa-scraping, og ingen affiliate-lenker er fulgt. Pris, lager, fraktpolicy og affiliate-URL kommer gjennom den eksisterende mapperen. Fullfeedens kategorifelt normaliseres til vanlig API-format ved engangsimporten, som i forrige leveranse.

| Produkt | SKU i begge feeds | Dokumentert pakning | Tilbud |
|---|---|---|---|
| everclear ULTIMATE1 30-pack | 10916 | 30 linser | Lensway og Lenson |
| everclear ULTIMATE1 90-pack | 10925 | 3 × 30 linser | Lensway og Lenson |

Begge butikkers bilder er visuelt kontrollert. Emballasjen viser ULTIMATE1, «1 Day», «30 Contact Lenses» og «Silicone Hydrogel». SKU 10925 viser tre slike esker; feedbildets navn angir også 3x30. De kontrollerte bildebytes er identiske mellom butikkene for hver SKU. Menicon er oppgitt i begge feeds. Kildehenvisninger og SHA-256 er bevart i den tilhørende JSON-filen. Navnelikheten med ELITE brukes ikke som matchinggrunnlag.

To produkter og fire tilbud er lagt til. Eksisterende katalograder og deres tidspunkter er identiske med basen. ULTIMATE1 får en serieside med de to sfæriske pakningene og den allerede publiserte ULTIMATE1 for Astigmatism 30-pack. ULTIMATE30 er ikke del av denne serien. Norske tekster og spesifikasjoner begrenses til de dokumenterte opplysningene.

FORSLAG/ÅPENT: SWATI 10975 holdes tilbake. Begge bilder viser Aquamarine og ti blistere, men feedtekst og strukturerte felter oppgir ikke pakningsantall eller fargevariant. Det er ikke tilstrekkelig grunnlag for endelig paknings-/variantmatching. Ingen kobling til 1-month/6-month opprettes. Eier er oppfølgingsansvarlig; eksisterende vurderingsregister beskriver det manglende grunnlaget.

## Verifikasjon før publisering

- Eksisterende katalogbygger brukt for bare de nye produktene; full scraping-rutine er ikke kjørt.
- Statisk bygg og byggevalidering bestått: 233/233 linseprodukter har tilbud.
- 39 tester for feedgjennomgang, feedkontroll, bilder, frakt, SEO/schema, søk og budsjettlandingsside bestått.
- 47 JavaScript-søketester bestått mot det bygde nettstedet.
- Begge nye SKU-er finnes i dagens ordinære Lensway everclear-søk og Lenson-paginering. Ingen ny kildekonfigurasjon er nødvendig.
- HTML-kontroll bekrefter selvrefererende canonical, Product-schema, ingen noindex, begge butikktilbud, produkt-/seriesitemap og lenker fra everclear-merket.
- Lokal Chromium-kjøring ble blokkert av miljøets socket-begrensning; ingen bestått nettleser-/skjermbildetest påstås. Eksisterende maler er uendret, og produktbildene er visuelt kontrollert separat.
- CI og offentlig etterkontroll verifiseres ved publiseringen og oppsummeres i chatten. Ingen GitHub-kommentar er nødvendig.

## Læringskontroll

Samme produktnavn i en feed kan skjule forskjellige pakninger. SKU-er og visuelt kontrollert emballasje gir grunnlaget her; et filnavn alene gjør det ikke. Det eksisterende regresjonstestsettet er utvidet med 10916/10925 slik at 30 og 90 linser ikke byttes. SWATI illustrerer fortsatt usikkerhet: antall avbildede blistere alene brukes ikke som endelig pakningsbevis. Metoden er lokal evidens, ikke en generell regel om produktidentitet eller bilderettigheter for andre Properties. Ingen ny felles standard eller tjeneste er innført.
