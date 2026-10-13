# Interoptik affiliate-feed – 13. oktober 2026

Avtalen er bekreftet godkjent av eier. Feed 1169 er lest som Google Shopping CSV (1217 rader: 100 kontaktlinser, 9 øyepleie, 1108 briller/solbriller). Bare eksplisitt matchede produkter publiseres. Ferdige to.interoptik.no-lenker beholdes uendret; parameteren a i trackinglenkene kommer fra feeden og omskrives ikke til apid.

Alle publiserte tilbud har in_stock. Pris og lager hentes kun fra feed. Eksisterende gratis standardfrakt beholdes, også bekreftet som NO:::0 NOK i feeden. Ingen produkter opprettes i denne integrasjonen. Øvrige butikker er uendret. Interoptik-scraping er deaktivert gjennom default_source=affiliate_feed. Uavklarte tidligere Interoptik-tilbud fjernes, ikke videreført med uklar pakning.

## Identitet

Pakningsstørrelse kommer fra feednavn eller produktvelgeren (productSelect) på nøyaktig feed-destinasjon. Nettstedet er kun brukt til produktidentitet, ikke som priskilde. Ved flere pakninger på samme URL og manglende SKU–pakning-relasjon holdes radene ute. Bilder er ikke brukt som eneste bevis.

| SKU | Produkt-ID | Pakningsbevis | Identitetskilde |
|---|---|---|---|
| 40000077 | air-optix-night-day-aqua-6pk | Interoptik productSelect: Air Optix Night & Day 6 PACK | https://www.interoptik.no/kontaktlinser/air-optix/air-optix-night--day/ |
| 40000579 | air-optix-hydraglyde-6pk | Interoptik productSelect: AO Hydraglyde 6 PACK | https://www.interoptik.no/kontaktlinser/air-optix/ao-hydraglyde/ |
| 40000580 | air-optix-hydraglyde-astigmatism-6pk | Interoptik productSelect: AO Hydraglyde Astigmatism 6 PACK | https://www.interoptik.no/kontaktlinser/air-optix/ao-hydraglyde-astigmatism/ |
| 40000583 | air-optix-hydraglyde-multifocal-6pk | Interoptik productSelect: AO Hydraglyde Multifocal 6 PACK | https://www.interoptik.no/kontaktlinser/air-optix/ao-hydraglyde-multifocal/ |
| 40000586 | dailies-aquacomfort-plus-90pk | Interoptik productSelect: Aquacomfort Plus 90 PACK | https://www.interoptik.no/kontaktlinser/dailies/aquacomfort-plus/ |
| 40000267 | dailies-aquacomfort-plus-30pk | Interoptik productSelect: Dailies AquaComfort Plus 30 PACK | https://www.interoptik.no/kontaktlinser/dailies/dailies-aquacomfort-plus/ |
| 40000310 | dailies-aquacomfort-plus-multifocal-30pk | Interoptik productSelect: Dailies AquaComfort Plus Multifocal 30 PACK | https://www.interoptik.no/kontaktlinser/dailies/dailies-aquacomfort-plus-multifocal/ |
| 40000312 | dailies-aquacomfort-plus-toric-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-aquacomfort-plus-toric-30-pack2/ |
| 40000412 | dailies-aquacomfort-plus-toric-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-aquacomfort-plus-toric-90-pack2/ |
| 40000316 | dailies-total1-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-total-1-30-pack2/ |
| 40000409 | dailies-total1-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-total-1-90-pack2/ |
| 40000368 | dailies-total1-multifocal-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-total-1-multifocal-30-pack2/ |
| 40000371 | dailies-total1-multifocal-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-total-1-multifocal-90-pack2/ |
| 40000688 | dailies-total1-astigmatism-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-total1-for-astigmatism-30-pack/ |
| 40000702 | dailies-total1-astigmatism-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/dailies/dailies-total1-for-astigmatism-90-pack/ |
| 40000575 | biotrue-oneday-astigmatism-30pk | Interoptik productSelect: Biotrue Oneday Astigmatism 30 PACK | https://www.interoptik.no/kontaktlinser/biotrue/biotrue-oneday-astigmatism/ |
| 40000568 | purevision2-presbyopia-6pk | Interoptik productSelect: PureVision® 2 HD Presbyopia 6 PACK | https://www.interoptik.no/kontaktlinser/purevision/purevision-2-hd-presbyopia/ |
| 40000326 | purevision2-6pk | Interoptik productSelect: PureVision® 2 HD SVS 6 PACK | https://www.interoptik.no/kontaktlinser/purevision/purevision-2-hd-svs/ |
| 40000566 | ultra-astigmatism-6pk | Interoptik productSelect: Ultra Astigmatism 6 PACK | https://www.interoptik.no/kontaktlinser/ultra/ultra-astigmatism/ |
| 40000565 | ultra-presbyopia-6pk | Interoptik productSelect: Ultra Presbyopia 6 PACK | https://www.interoptik.no/kontaktlinser/ultra/ultra-presbyopia/ |
| 40000563 | ultra-6pk | Interoptik productSelect: Ultra SVS 6 PACK | https://www.interoptik.no/kontaktlinser/ultra/ultra-svs/ |
| 40000745 | ultra-oneday-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/ultra/ultra-one-day-sphere-30-pack/ |
| 40000589 | biofinity-energys-6pk | Interoptik productSelect: Biofinity Energys 6 PACK | https://www.interoptik.no/kontaktlinser/biofinity/biofinity-energys/ |
| 40000616 | biofinity-multifocal-6pk | Interoptik productSelect: Biofinity Multifocal 6 PACK | https://www.interoptik.no/kontaktlinser/biofinity/biofinity-multifocal/ |
| 40000591 | biofinity-6pk | Interoptik productSelect: Biofinity Sphere 6 PACK | https://www.interoptik.no/kontaktlinser/biofinity/biofinity-sphere/ |
| 40000592 | biofinity-toric-6pk | Interoptik productSelect: Biofinity Toric 6 PACK | https://www.interoptik.no/kontaktlinser/biofinity/biofinity-toric/ |
| 40000593 | biofinity-xr-6pk | Interoptik productSelect: Biofinity XR 6 PACK | https://www.interoptik.no/kontaktlinser/biofinity/biofinity-xr/ |
| 40000587 | avaira-vitality-6pk | Interoptik productSelect: Avaira Vitality 6 PACK | https://www.interoptik.no/kontaktlinser/avaira/avaira-vitality/ |
| 40000588 | avaira-vitality-toric-6pk | Interoptik productSelect: Avaira Vitality Toric 6 PACK | https://www.interoptik.no/kontaktlinser/avaira/avaira-vitality-toric/ |
| 40000594 | biomedics-1day-xtra-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/biomedics/biomedics-1-day-extra-30-pack2/ |
| 40000595 | biomedics-1day-xtra-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/biomedics/biomedics-1-day-extra-90-pack2/ |
| 40000596 | biomedics-1day-xtra-toric-30pk | Interoptik productSelect: Biomedics 1-day Extra Toric 30 PACK | https://www.interoptik.no/kontaktlinser/biomedics/biomedics-1-day-extra-toric/ |
| 40000598 | biomedics-toric-6pk | Interoptik productSelect: Biomedics Toric 6 PACK | https://www.interoptik.no/kontaktlinser/biomedics/biomedics-toric/ |
| 40000597 | biomedics-55-evolution-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/biomedics/biomedics-55-evolution-6-pack/ |
| 40000761 | clariti-1day-multifocal-3add-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/clariti/clariti-1-day-multifocal-3-add-30-pack/ |
| 40000599 | clariti-1day-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/clariti/clariti-1-day-30-pack2/ |
| 40000600 | clariti-1day-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/clariti/clariti-1-day-90-pack2/ |
| 40000602 | clariti-1day-multifocal-30pk | Interoptik productSelect: Clariti 1-day Multifocal 30 PACK | https://www.interoptik.no/kontaktlinser/clariti/clariti-1-day-multifocal/ |
| 40000603 | clariti-1day-toric-30pk | Interoptik productSelect: Clariti 1-day Toric 30 PACK | https://www.interoptik.no/kontaktlinser/clariti/clariti-1-day-toric/ |
| 40000608 | myday-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/myday/myday-sphere-30-pack2/ |
| 40000609 | myday-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/myday/myday-sphere-90-pack2/ |
| 40000610 | myday-toric-30pk | Interoptik productSelect: Myday Toric 30 PACK | https://www.interoptik.no/kontaktlinser/myday/myday-toric/ |
| 40000739 | myday-misight-1day-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/myday/myday-misight-1-day-30-pack/ |
| 40000763 | myday-multifocal-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/myday/myday-multifocal-30-pack/ |
| 40000611 | proclear-1day-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/proclear/proclear-1-day-30-pack2/ |
| 40000619 | proclear-1day-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/proclear/proclear-1-day-90-pack2/ |
| 40000612 | proclear-1day-multifocal-30pk | Interoptik productSelect: Proclear 1-day Multifocal 30 PACK | https://www.interoptik.no/kontaktlinser/proclear/proclear-1-day-multifocal/ |
| 40000618 | proclear-multifocal-6pk | Interoptik productSelect: Proclear Multifocal 6 PACK | https://www.interoptik.no/kontaktlinser/proclear/proclear-multifocal/ |
| 40000615 | proclear-toric-6pk | Interoptik productSelect: Proclear Toric 6 PACK | https://www.interoptik.no/kontaktlinser/proclear/proclear-toric/ |
| 40000614 | proclear-sphere-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/proclear/proclear-6-pack/ |
| 40000401 | proclear-multifocal-xr-3pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/proclear/proclear-xr-multifocal-3-pack/ |
| 40000013 | acuvue-moist-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-moist-30-pack2/ |
| 40000411 | acuvue-moist-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-moist-90-pack2/ |
| 40000245 | acuvue-moist-astigmatism-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-moist-for-astigmatism-30-pack2/ |
| 40000410 | acuvue-moist-astigmatism-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-moist-for-astigmatism-90-pack2/ |
| 40000318 | acuvue-moist-multifocal-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-moist-multifocal-30-pack2/ |
| 40000415 | acuvue-moist-multifocal-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-moist-multifocal-90-pack2/ |
| 40000363 | acuvue-oasys-1day-hydraluxe-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-oasys-30-pack2/ |
| 40000413 | acuvue-oasys-1day-hydraluxe-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-oasys-90-pack2/ |
| 40000365 | acuvue-oasys-1day-astigmatism-30pk | Interoptik productSelect: 1-day Acuvue Oasys for Astigmatism 30 PACK | https://www.interoptik.no/kontaktlinser/acuvue/1-day-acuvue-oasys-for-astigmatism/ |
| 40000025 | acuvue-oasys-6pk | Interoptik productSelect: Acuvue Oasys 6 PACK | https://www.interoptik.no/kontaktlinser/acuvue/acuvue-oasys/ |
| 40000174 | acuvue-oasys-astigmatism-6pk | Interoptik productSelect: Acuvue Oasys for Astigmatism 6 PACK | https://www.interoptik.no/kontaktlinser/acuvue/acuvue-oasys-for-astigmatism/ |
| 40000703 | acuvue-oasys-max-1day-30pk | Interoptik productSelect: ACUVUE® OASYS MAX 1-Day 30 PACK | https://www.interoptik.no/kontaktlinser/acuvue/acuvue-oasys-max-1-day/ |
| 40000727 | acuvue-oasys-max-1day-astigmatism-30pk | Interoptik productSelect: ACUVUE® OASYS MAX 1-Day for ASTIGMATISM 30 PACK  | https://www.interoptik.no/kontaktlinser/acuvue/acuvue-oasys-max-1-day-for-astigmatism/ |
| 40000742 | acuvue-oasys-max-1day-multifocal-astigmatism-30pk | Interoptik productSelect: ACUVUE® OASYS MAX 1-Day MF ASTIGMATISM 30 PACK | https://www.interoptik.no/kontaktlinser/acuvue/acuvue-oasys-max-1-day-mf-for-astigmatism/ |
| 40000705 | acuvue-oasys-max-1day-multifocal-30pk | Interoptik productSelect: ACUVUE® OASYS MAX 1-Day MULTIFOCAL 30 PACK | https://www.interoptik.no/kontaktlinser/acuvue/acuvue-oasys-max-1-day-multifocal/ |
| 40000634 | precision1-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/precision/precision1-30-pack/ |
| 40000635 | precision1-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/precision/precision1-90-pack/ |
| 40000636 | precision1-astigmatism-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/precision/precision1-for-astigmatism-30-pack/ |
| 40000637 | precision1-astigmatism-90pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/precision/precision1-for-astigmatism-90-pack/ |
| 40000735 | precision7-12pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/precision/precision7-12-pack/ |
| 40000737 | precision7-astigmatism-12pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/precision/precision7-for-astigmatism-12-pack/ |
| 40000708 | total30-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/total30/total30-6-pack/ |
| 40000710 | total30-astigmatism-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/total30/total30-for-astigmastism-6-pack/ |
| 40000718 | total30-multifocal-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/total30/total30-multifocal-6-pack/ |
| 40000678 | miru-1day-flatpack-30pk | Interoptik productSelect: Miru 1day Flatpack 30 PACK | https://www.interoptik.no/kontaktlinser/miru/miru-1day-flatpack/ |
| 40000680 | miru-1day-flatpack-astigmatism-30pk | Interoptik productSelect: Miru 1day Flatpack Astigmatism 30 PACK | https://www.interoptik.no/kontaktlinser/miru/miru-1day-flatpack-astigmatism/ |
| 40000679 | miru-1day-flatpack-multifocal-30pk | Interoptik productSelect: Miru 1day Flatpack Multifocal 30 PACK | https://www.interoptik.no/kontaktlinser/miru/miru-1day-flatpack-multifocal/ |
| 40000746 | miru-1day-upside-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/miru/miru-1day-upside-30-pack/ |
| 40000747 | miru-1day-upside-astigmatism-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/miru/miru-1day-upside-astigmatism-30-pack/ |
| 40000748 | miru-1day-upside-multifocal-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/miru/miru-1day-upside-multifocal-30-pack/ |
| 40000750 | miru-1month-toric-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/miru/miru-1month-astigmatism-6-pack/ |
| 40000751 | miru-1month-multifocal-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/miru/miru-1month-multifocal-6-pack/ |
| 40000749 | miru-1month-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/miru/miru-1month-sphere-6-pack/ |
| 40000561 | misight-1day-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/misight/misight-1-day-30-pack/ |
| 40000028 | soflens-59-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/soflens/soflens-59-sphere-6-pack/ |
| 40000066 | soflens-toric-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/soflens/soflens-66-toric-for-astigmatism-6-pack/ |
| 40000744 | soflens-daily-disposable-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/soflens/soflens-daily-disposable-30-pack/ |
| 40000743 | soflens-daily-disposable-astigmatism-30pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/soflens/soflens-daily-disposable-for-astigmatism-30-pack/ |
| 40000767 | soflens-multifocal-6pk | Feednavn angir pakning | https://www.interoptik.no/kontaktlinser/soflens/soflens-multifocal-6-pack/ |
| 90120613 | blephaclean-20stk | Feednavn angir pakning | https://www.interoptik.no/oyehelseprodukter/blephaclean/blephaclean-vatservietter-20-pk/ |
| 90122806 | evotears-3ml | Interoptik variantCode 90122806: 3 ml | https://www.interoptik.no/oyehelseprodukter/evotears/evotears-oyedraper/ |
| 90101225 | hylo-comod-10ml | Feednavn angir pakning | https://www.interoptik.no/oyehelseprodukter/hylo/hylo-commod-10-ml/ |
| 90112327 | hylo-gel-10ml | Feednavn angir pakning | https://www.interoptik.no/oyehelseprodukter/hylo/hylo-gel-10-ml/ |
| 90116257 | hylo-care-10ml | Feednavn angir pakning | https://www.interoptik.no/oyehelseprodukter/hylo/hylo-care-10-ml/ |
| 90120618 | thealoz-duo-10ml | Feednavn angir pakning | https://www.interoptik.no/oyehelseprodukter/thealoz/thealoz-duo-oyedraper-10-ml/ |

## Avventer

| SKU | Feednavn | Årsak |
|---|---|---|
| 40000584 | All Day Comfort | Samme feednavn/URL for 30 og 90; SKU til pakning ikke dokumentert |
| 40000585 | All Day Comfort | Samme feednavn/URL for 30 og 90; SKU til pakning ikke dokumentert |
| 40000576 | Biotrue Oneday | Samme feednavn/URL for 30 og 90; SKU til pakning ikke dokumentert |
| 40000577 | Biotrue Oneday | Samme feednavn/URL for 30 og 90; SKU til pakning ikke dokumentert |
| 40000572 | Biotrue Oneday Presbyopia | Samme feednavn/URL for 30 og 90; SKU til pakning ikke dokumentert |
| 40000574 | Biotrue Oneday Presbyopia | Samme feednavn/URL for 30 og 90; SKU til pakning ikke dokumentert |
| 40000765 | ULTRA® ONE DAY Multifocal 30 pack | Ny produktkandidat: ULTRA ONE DAY Multifocal |
| 40000607 | Eyexpert Natural | Eyexpert Natural: avklar produsent og tilsvarende produkt |
| 40000719 | Total30 Multifocal 6 pack | Ekstra styrke/add-variant av TOTAL30 Multifocal; én butikkrad brukes |
| 40000720 | Total30 Multifocal 6 pack | Ekstra styrke/add-variant av TOTAL30 Multifocal; én butikkrad brukes |
| 90120614 | BLEPHAGEL Rengjøringsgel 30 gr | Ny produktkandidat: Blephagel 30 g |
| 90120620 | BLEPHASOL Duo Lotion 100 ml | Avklar om Duo-sett inkluderer 100 pads |
| 90120619 | THEALOZ Duo Gel 30x0,4ml | Avklar enhet: feed 30x0,4 ml, lokal katalog 30x0,4 g |

Interoptik inngår automatisk i daglig feedkontroll via active_sources. Kandidatbeslutninger er lagret med feed-fingeravtrykk.
