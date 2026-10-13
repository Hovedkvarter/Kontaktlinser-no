# Interoptik: de siste åtte feedradene

Kontrollert 13. oktober 2026. Åtte eksplisitte SKU-koblinger lagt inn, én ny produktside. Priser, lagerstatus og affiliate-lenker i katalogen kommer utelukkende fra en fersk innhenting av den godkjente Adtraction-feeden (1217 rader). Alle åtte er på lager. Ingen scraping-mål er lagt til.

## Seks pakningsavklaringer

| Feed-SKU | Produkt | Pakning | Interoptiks interne produktkode | Feedpris ved kontroll |
|---|---|---:|---|---:|
| 40000584 | Dailies All Day Comfort | 30 | 11915 | 239 kr |
| 40000585 | Dailies All Day Comfort | 90 | 11914 | 714 kr |
| 40000576 | Biotrue ONEday | 30 | 9289 | 256 kr |
| 40000577 | Biotrue ONEday | 90 | 11924 | 765 kr |
| 40000572 | Biotrue ONEday Presbyopia | 30 | 9294 | 388 kr |
| 40000574 | Biotrue ONEday Presbyopia | 90 | 9293 | 1164 kr |

Dette er en dokumentert manuell sammenstilling, ikke en direkte SKU/GTIN-relasjon fra nettbutikken. Interoptiks produktvelger bruker andre koder enn feeden. Grunnlaget er kombinasjonen av:

1. Feeden binder hvert SKU til produktfamilien og et bestemt originalt pakningsbilde.
2. Dailies-bildeadressene angir uttrykkelig `30-pack` og `90-pack`. Biotrue-bildene er visuelt kontrollert: 30 og 90 står på eskene, og Presbyopia står på begge de multifokale eskene.
3. Produktvelgerens tekst bekrefter hver navngitte pakning. Det offentlige, lesende variantoppslaget (`POST /statefulapi/VariantApi/GetVariantDetails`, kun `productCode`) ble kontrollert for begge valg i hver familie. Hver pakning har en entydig pris som samsvarer nøyaktig med den aktuelle feedraden på kontrolltidspunktet. Disse verdiene ble kun brukt som identitetskryssjekk; publiserte priser importeres fra feeden.

Ingen kobling bygger på bilde alene eller antatt prisforhold 1:3. Pris er ikke lagt inn som automatisk matchingregel. For Presbyopia har bildene filnavn 40000571 og 40000573, mens feed-SKU er 40000572 og 40000574; filnavnets nummer hevdes derfor ikke å være identitetsbevis. Fremtidig import bruker kun den eksplisitte SKU-tabellen. Pakningsparene er låst med regresjonstest.

Kilder:
- https://www.interoptik.no/kontaktlinser/dailies/all-day-comfort/
- https://www.interoptik.no/kontaktlinser/biotrue/biotrue-oneday/
- https://www.interoptik.no/kontaktlinser/biotrue/biotrue-oneday-presbyopia/
- Feedfelter, bildeadresser, produktkoder og kontrollverdier: [evidensfil](interoptik-siste-aatte-evidence-2026-10-13.json).

Eksisterende, tidligere dokumenterte Focus Dailies-aliaser får samme Interoptik-tilbud gjennom den etablerte aliasregelen; ingen nye ekvivalenser opprettes.

## Eyexpert Natural: egen side, ingen antatt originallinse

SKU 40000607 publiseres som **Eyexpert Natural 30-pack**, `eyexpert-natural-30pk`. Interoptiks produkttekst og produktvelger bekrefter dagslinse, sfærisk, 30-pack, BC 8,6 mm, diameter 14,0 mm og vanninnhold 56 %. Originalbildet fra affiliate-feeden viser Eyexpert Natural og «1 day x30». Det brukes på den nye siden.

https://www.interoptik.no/kontaktlinser/eyexpert/eyexpert-natural/

Det er ikke nødvendig å identifisere en annen originallinse for å opprette en side for selve Eyexpert-produktet. Produsent/materiale og ekvivalens med Live eller Proclear er fortsatt ikke primærbekreftet og publiseres ikke. Ingen rad legges til i `private_labels.json`, og tilbudet blandes ikke med andre merker. Denne restusikkerheten er dermed isolert fra den publiserte produktidentiteten.

## Thealoz Duo Gel: behold gram

SKU 90120619 kobles til eksisterende `thealoz-duo-gel-30x04g`. Feedens tittel sier 30 x 0,4 ml, men det eksakte originalbildet knyttet til feedraden viser **30 enkeltdosisbeholdere à 0,4 g**. Pakningen viser også trehalose 3 %, natriumhyaluronat 0,15 % og karbomer 0,25 %, som samsvarer med produsentens bruksanvisning for Thealoz Duo Gel.

- https://thealozduo.no/thealoz-duo-gel/
- https://thealozduo.no/wp-content/uploads/2025/12/Thealoz_Duo_Gel_DK_IS_NO_IFU-N2258U30L17-0225-2502-V1-20250224.pdf
- Feedbilde: https://www.interoptik.no/globalassets/from-pim/thealoz-duo-gel-30x04ml/3662042004032_20.jpg

Dette korrigerer tolkningen av feedens enhet; det er ingen matematisk g/ml-konvertering. Produktets eksisterende navn, URL og gram-enhet beholdes. Feedens GTIN er fortsatt tomt, og ulike eldre/nyere EAN-koder brukes ikke som påstått bekreftelse fra produsenten.

## Kontroll og videre drift

Den eksisterende automatiske feedimporten vil oppdatere de åtte tilbudene via egne Interoptik-SKU-er. Discovery-registeret markerer radene som koblet med henvisning hit. Andre forhandleres tilbud er bevart. Ingen endringer for Alensa, Extra Optical, legemidler eller øyelapper.
