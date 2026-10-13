# Bildekontroll 13. oktober 2026

## Omfang og metode

- 227 katalogprodukter og 92 private label-oppføringer kontrollert mot faktisk valgt bilde i bildemalen.
- 217 katalogprodukter har et bilde; 10 mangler et egnet originalbilde. 31 private label-oppføringer har originalbilder (iWear); de øvrige 61 bruker eksisterende illustrasjon eller står uten originalfoto.
- Alle 248 valgte bildeforekomster ble lest og dekodet uten feil. Eksterne bildeadresser ble hentet direkte. Dette er en øyeblikkskontroll, ikke en garanti for fremtidig oppetid.
- Alle 232 lokale rasterfiler som HTML-en refererer til ble formatkontrollert uten feil. Byggporten sjekker dessuten at lokale img/src og source/srcset finnes på tvers av alle bygde sider.
- Visuell gjennomgang av kontaktark for alle valgte bilder, med større enkeltbilder ved mistanke om feil variant eller pakningsstørrelse. Små eller generiske feedbilder gjør ikke alle pakningstekster lesbare; kontrollen hevder ikke full identitetsbekreftelse ut fra bilde alene.
- Inventaret viser tilstanden før rettelsene nedenfor: `bildekontroll-2026-10-13-inventar.json`. Ingen priser er hentet fra butikksider eller endret.

## Rettelser

| Oppføring | Før | Etter |
|---|---|---|
| iWear på startsiden | Gammel CSS-illustrasjon hadde prioritet | Originalt iWear Oxygen-bilde fra godkjent Brilleland-feed |
| MIRU 1day UpSide 30 | Eske merket 90 linser | Interoptik-feedens MIRU-eske merket 30 linser |
| Proclear Multifocal XR 3 | Feedbildet viste Proclear Toric XR | Interoptiks bilde med riktig Multifocal XR-navn; generisk pakningsillustrasjon uten antall, merket som illustrasjon på selve bildet |
| Acuvue Oasys MAX 1-Day 90 | Manuelt bilde av 30-eske | Lensway-feedens 90-eske |
| Acuvue Oasys MAX 1-Day Multifocal 90 | Manuelt bilde av 30-eske | Lensway-feedens multifokale 90-eske |
| Acuvue Oasys 1-Day HydraLuxe 180 | Én 90-eske | Lensway-feedens bilde med 2 × 90 esker |

De fem produktbildene er lagret på egne URL-er med `-verified` i filnavnet for å unngå gamle bilde-cachetreff. Feedens originale bildeadresse og faktisk nedlastingsadresse er dokumentert i metadata. Lensways samme Cloudinary-bilde ble hentet i 900 pikslers bredde i stedet for 170. Ingen emballasjetekst er tegnet om eller generert.

Den delte bildevelgeren gjør at rettelsene også gjelder produktkort, merke-/kategori-/seriesider, søk og strukturert produktdata der disse bruker samme produktbilde. Startsiden låner ikke lenger et underliggende originalmerkes eske til private label-merket: originalfoto av eget merke foretrekkes, ellers brukes den eksisterende merkede illustrasjonen.

## Fortsatt uten egnet originalbilde

- MyDay MiSight 1 day 90-pack (`myday-misight-1day-90pk`)
- Clearlii Daily 90-pack
- Clearlii Monthly 6-pack
- Clearlii Vitamin 30-pack
- Proclear Toric 3-pack
- Proclear Multifocal 3-pack
- Biofinity Toric 3-pack
- Biofinity Multifocal 3-pack
- Biofinity XR Toric 6-pack
- Opti-Free Express 120 ml

For disse ble det ikke funnet et egnet originalbilde blant tilbudene som nå er koblet til produktet. Dette er ikke dokumentasjon på at et slikt bilde ikke finnes hos produsenten. Særlig private label-bilder av iWear skal ikke brukes som foto av Biofinity eller Proclear. Ingen nye illustrasjoner er laget.

## iWear og begrensninger

31 iWear-originalbilder er kontrollert på nytt. Balance Plus (sfærisk) og Go Astigmatism beholder illustrasjon: den første har feil variant i feedbildet, den andre mangler bilde i den aktuelle feeden. Andre kjeders eksisterende illustrasjoner beholdes og skal ikke omtales som originalfoto.

Noen øvrige feedbilder har lav oppløsning eller er generiske produktbilder uten lesbart pakningsantall. Disse er ikke døde bildeadresser. En eventuell generell bildeoptimalisering bør behandles separat fra identitetsrettelsene.

Biofinity XR 6 ble undersøkt fordi URL-en sier `3pk`, men selve bildet viser tydelig 6 kontaktlinser. Bildet er riktig og er ikke endret. Dette illustrerer hvorfor filnavn alene ikke avgjør bildeidentitet.

## Verifisering

Regresjonstesten for startsidens iWear-kort sikrer at det bruker et iWear-originalfoto, uten CSS-eske og uten originalproduktets bilde. Full generering og validering kjøres før publisering; lokale bildefeil stopper nå utrulling automatisk.
