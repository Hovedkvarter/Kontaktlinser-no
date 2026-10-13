# Syv produkter fra feedkontrollen

Kontrollert 13. oktober 2026. Syv nye produkter og 18 SKU-koblinger.
Produktpriser, lagerstatus, affiliate-lenker og bilder er hentet fra nettverksfeeds. Ingen butikkpriser er scrapet.

| Produkt | Lensway | Lenson | Shopping4net | Apotekhjem |
|---|---|---|---|---|
| Blephaclean 20 stk | 7068 | 7068 | ATD1B-4D-20 | 76437 |
| MediPearl øyemaske 1 stk | 9892 | 9892 | AMO00-MO-1 | 94762 |
| BlephaCura 70 ml | 10573 | 10573 | | |
| Blephasol Duo 100 ml + 100 pads | | | ATD12-4D-100 | 15977 |
| POSIFORLID Eye Wipes 20 stk | | | APE00-QN-20 | 103222 |
| POSIFORLID øyemaske 1 stk | | | APO01-QN-17 | 103163 |
| EvoTears OMEGA 3 ml | | | APESE-EY-3 | 103601 |

## Identitet og bilder

- Blephaclean: GTIN 3662042006593 samsvarer mellom Lensway og Apotekhjem. Shopping4nets tittel sier 20 stk. Lenson/Lensway har samme SKU og samme merkede 20-pakning i feedbildet.
- MediPearl: GTIN 7340170400006 samsvarer mellom Lensway og Apotekhjem. Samme øyemaske og SKU hos Lenson, produkt og beskrivelse samsvarer hos Shopping4net. Sistnevnte er utsolgt i feeden og kan ikke vinne prisrangeringen.
- BlephaCura: Lensway GTIN 7350133960072, samme SKU 10573 og samme produkt hos Lenson. Feedens pakningsbilde viser uttrykkelig 70 ml.
- Blephasol Duo: Apotekhjem GTIN 3662042003998. Pakningsbilde og produsent bekrefter 100 ml + 100 pads. Selges som sett; ingen misvisende sammenligning av settpris per 100 ml.
- POSIFORLID: titler og bilder skiller 20 servietter fra én selvoppvarmende maske. Maskebildene i begge feeds er visuelt kontrollert og viser samme emballasje og maske.
- EvoTears OMEGA: 3 ml i begge feeds og på pakningsbildet. Eget produkt, aldri koblet til vanlig EvoTears.

Syv originale feedbilder er lagret under `static/products/`. `manual_image`, `image_source` og `image_original_url` dokumenterer den faste bildekoblingen og opphavet. Ingen illustrasjoner er generert. Cloudinary-bildenes eksisterende størrelsesparameter er satt til 600 px; motivet er uendret.

## Kilder til produktfakta

- https://thea-nordic.no/product/blephaclean/
- https://thea-nordic.no/product/blephasol-duo/
- https://medilensnordic.com/medipearl/
- https://www.tearsagain.no/blephacura/
- https://ursapharm.de/en/products/eyelid-inflammation/posiforlid-eyelid-hygiene-wipes/
- https://ursapharm.de/en/products/eyelid-inflammation/posiforlid-eye-mask/
- https://ursapharm.de/en/products/dry-eye-syndrome/evotears-omega/

## Løpende oppdatering

Lensways og Shopping4nets eksisterende feedsøg er utvidet med de nye navnene. Lenson og Apotekhjem dekker dem allerede gjennom sine fulle prisfeeds. SKU-matching er fortsatt eksplisitt; navn brukes bare som feedfilter.

Lensway, Lenson og Apotekhjem ble lastet ned på nytt. Shopping4nets fullfeed svarte 429; den ble ikke forsøkt lastet ned på nytt. De fem ordinære, avgrensede produktsøkene som brukes av prisinnhentingen, svarte med ferske produktdata.

Shopping4nets apotekavdeling har fri frakt fra 350 kr, mens kontaktlinser har 700 kr. `shipping_by_category` lar feedkategorien styre terskelen. Gebyret på 39 kr under terskelen er det eksisterende brukerbekreftede gebyret. Kilde til terskler: https://www.shopping4net.com/no/Informasjon/Kjoepsvilkaar.htm (kontrollert 2026-10-13). Apotekhjems ukjente fraktpolicy beholdes som ukjent.

Eksisterende produkter og produktpriser i `catalog_live.json` er bevart. Fraktregelen gjelder nye tilbud nå og øvrige relevante Shopping4net-tilbud ved neste feedoppdatering. De 18 kandidatene er merket som koblet i vurderingsregisteret og forsvinner fra kandidatlisten ved neste vellykkede feedkontroll.
