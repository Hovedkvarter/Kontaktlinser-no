# Kontaktlinser – prioritert feedgjennomgang 26. oktober 2026

## Beslutning og status

Alle kontaktlinser er prioritet 1: nye produkter/serier, nye pakninger og flere annonsører på eksisterende produkter. Funn skal undersøkes og få et konkret opprettelses-/koblingsforslag. Navnelikhet er ikke nok. Produksjon og test er godkjent; merge og publisering av denne arbeidsrunden avventer godkjenning etter forhåndsvisning.

Utgangspunkt: `3363de35b2ab7283324bfd6bc04d2a6f58159e2d`. Norske URL-er, prisrangering og Extra Opticals direkte-lenkeregel er beholdt. Visuell kontroll avdekket horisontal overløping i everclear-merkesidens prisfaner; to avgrensede CSS-regler lar kortene krympe og fanene brytes over flere linjer.

## Klargjort

| Produkt | Pakning | Nye butikkoblinger |
|---|---|---|
| everclear PRIME | 30 | Lenson 10914, Lensway 10914 |
| everclear PRIME for Astigmatism | 30 | Lenson 10915, Lensway 10915 |
| everclear ULTIMATE1 for Astigmatism | 30 | Lenson 10917, Lensway 10917 |
| everclear ULTIMATE30 for Astigmatism | 3 | Lenson 10919, Lensway 10919 |
| 1-Day Acuvue Moist for Astigmatism | 30 | Shopping4net LM |
| Acuvue Oasys 1-Day for Astigmatism | 30 | Shopping4net LU |
| Biofinity XR | 3 | Shopping4net LBXR |
| PureVision2 for Presbyopia | 6 | Shopping4net LP2P |
| MyDay | 30 | Extra Optical: MyDay 1 day Sphere 30 stk |

Totalt fire nye produkter, 13 koblinger og én serieside (`/serie/everclear-prime/`). PRIME samler sfærisk og torisk variant. ULTIMATE1 og ULTIMATE30 har forskjellige utskiftingsintervaller og slås ikke sammen til én designfamilie; begge finnes på merke- og relevante kategorisider.

De fire nye produktene bruker nøkterne norske tekster, produsent, materialtype, linsetype, brukstid og pakning fra dokumentasjonen. Udokumenterte materialnavn, BC, DIA, vanninnhold og påstander om likeverdige private labels er ikke lagt til. Eksisterende maler leverer SEO, produkt-/brødsmuleskjema, søk og relevante guider.

Pakningene er kontrollert i norske Lenson-sidetitler og visuelt i Lensways originale feedbilder. Bildene viser også hydrogel for PRIME og silikonhydrogel for ULTIMATE. Menicon er oppgitt i begge feeds og Lensways metadata. Fire 900 px-bilder fra feedens Cloudinary-kilde er lagret med kildeopplysninger i produktmetadata.

Shopping4nets produkttabeller oppgir både pakning og det aktuelle artikkelnummeret. Kontrollert mot eksakte norske produktadresser fra feeden. De ordinære API-søkene er testet: LP2P manglet i eksisterende søk, så et ekstra `PureVision2`-søk er lagt til og bekreftet å levere riktig produkt. Ingen tilgangsnøkler er gjengitt i dokumentasjonen.

MyDay-raden har feil tittel (Proclear), men SKU, beskrivelse, måladresse og det visuelt kontrollerte bildet (MyDay 30 linser) samsvarer. Den kobles derfor til MyDay, aldri Proclear. Tilbudet bruker fortsatt den eksisterende direkte-lenkefunksjonen for Extra Optical.

Priser, lagerstatus, fraktregler og sporingslenker i katalogendringen kommer fra ferske affiliate-feeds hentet 26. oktober. Bare de 13 nye tilbudene er lagt til; eksisterende tilbud og deres tidspunkter beholdes. Fullfeedens `tdCategoryName` normaliseres til vanlig API-form ved engangsimporten; produksjonsmapperen er uendret.

## Avklart uten ny publiserbar oppføring

- **Air Optix Aqua:** 6-pack bekreftet, men fersk feed sier utsolgt. Avventer tilgjengelig tilbud; ikke koblet til HydraGlyde.
- **FreshLook ColorBlends:** 2-pack bekreftet, men fersk feed sier utsolgt. Avventer tilgjengelig tilbud; ikke koblet til FreshLook One-Day.
- **Supra 55 UV Tint:** 1 linse per pakning bekreftet, men fersk feed sier utsolgt. Måladressens eldre Biomedics-navn brukes ikke som identitetsgrunnlag.
- **Extra Optical 1-Day Acuvue 30/90:** Bildene viser Moist i riktig pakning, men navn/beskrivelse er generiske og GTIN avviker fra butikkens egne MOIST-rader. De entydige MOIST-radene er allerede koblet, til samme priser. Ingen ekstra butikkrad opprettes; de generiske SKU-ene forblir uavklart.
- **Interoptik TOTAL30 40000719/40000720:** Tidligere dokumentasjon og fersk feed bekrefter samme produkt/pakning/måladresse/pris som 40000718. Vurderingsfingeravtrykkene er oppdatert, uten ekstra produkt eller duplisert tilbud.

Alle beslutninger, kildelenker og vurderingsfingeravtrykk finnes i `contact-lens-feed-review-2026-10-26.json`. Vurderingsregisteret er oppdatert; den automatisk genererte rapporten endres ved neste feedkontroll.

## Kontroller og neste steg

- 25 unittest-kontroller bestått (inkludert fem målrettede kontroller av denne leveransen).
- 15 SEO/schema-kontroller bestått.
- 12 av 14 Product SEO Growth-kontroller bestått. De samme to feilene er gjenskapt på urørt basiskommit: testene forventer bare 30/90/180-pack for everclear ELITE, men den eksisterende katalogen har også 5-pack. Ingen ny feil fra denne leveransen.
- Fullt statisk bygg og eksisterende byggevalidering bestått: 231/231 linseprodukter har tilbud.
- Offline gjennomkjøring av fem ferske feeds bekrefter at de 13 koblede radene forsvinner fra kandidatlisten, og at gjenværende linsekandidater beholder riktig vurdering. Interoptik-fingeravtrykkene beregnes etter normalisering til måladressen, slik rapportgeneratoren gjør.
- 12 nettleserkontroller bestått: fire nye produkter, PRIME-serien og everclear-merket på 390 og 1440 px. Ingen horisontal overløping eller manglende bilder. Skjermbilder og målinger finnes i `docs/previews/contact-lens-feed-review-20261026/`.
- Norsk prishistorikk og lastmod-filer er tilbakeført etter lokal bygging. Ingen testhistorikk legges i PR-en.

Neste steg er gjennomgang av endringene og forhåndsvisningen, deretter særskilt godkjenning av merge/publisering. Utsolgte og uklare kandidater skal fortsatt følges opp, men hindrer ikke de dokumenterte endringene.
