# Billige linser på nett — status 7. november 2026

## Vedtatt

Arbeidsordre i Kontaktlinser Work 2: egen kjøpsorientert inngang på `/billige-linser-pa-nett/`, eksisterende katalog/søk/Mulish/produktkort. Bare utvikling, forhåndsvisning og Draft PR. Ingen merge eller publisering. Utgangspunkt: main `1944722`.

Tidligere erfaringer: `mobile-product-cards-003/STATUS.md` (to mobilkolonner, faktabaserte prisforskjeller), eksisterende søkekompilering og SEO-/lastmod-generator. AGENTS.md, CLAUDE.md og lokale arbeidsregler lest. Gjeldende Project Instructions og Architecture Decision Log hentet via Drive; ingen plattformarbeider eller nye rettigheter inngår.

## Implementert, ikke publisert

- Egen render-modul koblet til eksisterende generator. H1, title, beskrivelse og canonical som bestilt.
- Delt søk og søkeindeks, fire kategoriinnganger, kategorifilter med tastaturtilgjengelige knapper og live resultatantall. Statisk produktinnhold også uten JavaScript.
- Inntil tre modeller fra hver av fire kategorier, sortert etter laveste ferske eskepris på lager. Én pakning per modell, minst tre linser, eksisterende produktbilde (ikke egne illustrasjoner). Ingen butikk- eller affiliateprioritering. Kriteriene forklares på siden.
- Tolv produkter i katalogen som ble kontrollert. Alle viste lavestepriser stemmer med ordinære produktsider ved samme referansetid. Reelle produktnavn, bilder, antall linser og unike butikker fra katalogen. Prisforskjeller gjenbruker eksisterende kortberegning.
- Original kjøpeguide om eskepris, brukstid, pakninger, frakt og riktig linse. Lenker til eksisterende dybdeguider, kategorier og metodikk. Optikerrådet kontrollert mot https://www.specsavers.no/hjelp/din-linseseddel og https://www.specsavers.no/oeyehelse/synstest/for-kontaktlinser (7. november).
- CollectionPage, ItemList og BreadcrumbList; ingen oppdiktede vurderinger eller Product/AggregateOffer for landingssiden.
- Automatisk sitemap-/lastmod-oppføring og én intern lenke fra forsiden og hver av fem kategorisider. Eksisterende titler, canonical og URL-er beholdt.
- Fem nye regresjonstester legges til eksisterende PR-CI-teststeg.

## Kontroller

- Fullt offline bygg med ekte, uendrede katalogtidsstempler og fast referansetid. Ingen feedimport, skraping eller affiliateklikk. Tom clickout-mapping for både baseline og kandidat; produksjonsintegrasjonen er ikke testet.
- Byggevalidator: OK, 231/231 produkter har priser. 489 HTML-sider mot 488 i baseline.
- HTML-diff: bare ny landingsside pluss forside og fem kategorier (interne lenker). Alle øvrige 482 eksisterende HTML-filer byteidentiske. Ingen sider fjernet.
- 19 unittest-tester bestått: ny side (5), produktkort/prisforskjeller (5), søkekompilering (9). Separat SEO-testprogram bestått. 47 Node-søketester bestått.
- `test_product_seo_growth.py`: 12/14 bestått; de samme to feilene reprodusert på ren main `1944722` i egen worktree. Testene forventer bare 30/90/180-pakninger, mens dagens katalog også har everclear ELITE 5-pack. Ingen endring i søskenlogikken i denne PR-en.
- Nettleser: felles søk gir 13 Biofinity-treff; piltast + Enter åpner `/serie/biofinity/`. Torisk filter viser tre produkter, «Alle typer» viser tolv. Alle tolv bilder lastet.
- Mobil QA via iframe på 320/375/768 px (305/360/753 px innvendig pga. nettleserens rullefelt): ingen horisontal side-overflyt. Desktop 1363 px: ingen overflyt. Mulish bekreftet. Mobilfilter kan rulles horisontalt innenfor sin egen rad.
- Uten JavaScript: tolv kort, kategorilenker og kjøpeguide fortsatt tilgjengelige; inaktive filterknapper skjult.
- Skjermbilder: `mobile-375.jpg`, `desktop-top.jpg`, `desktop-full.jpg`. Mobilbildet viser øvre 900 px; hele siden er dokumentert i desktopbildet. Ingen påstand om full WCAG-revisjon eller målt Core Web Vitals.

## SEO-avgrensning og åpne spørsmål

Siden retter seg mot bred kjøpsintensjon og viser produkter først. Kategoriene beholder linsetypespesifikt utvalg; prisundersøkelsen er historisk analyse; øvrige guider forklarer enkelttemaer. Forsiden overlapper naturlig på «billige kontaktlinser», så faktisk søkeordfordeling må følges etter en eventuell publisering. Det er ikke dokumentert at kannibalisering er eliminert.

GSC Wizard nektet lesing med `subscription_required`; derfor ingen verifiserte søketall eller query/page-baseline. Ingen abonnementsendring gjort.

**Eksisterende Lensit-regel:** `reconcile_product` utelater Lensit hvis de har laveste totalpris, med en historisk kommersiell begrunnelse. Dette strider mot den nye arbeidsordrens nøytralitetskrav. Nytt eksplisitt keyword `exclude_legacy_retailer=False` brukes bare på landingssiden; standardverdien bevarer alle eksisterende kall og affiliateflyt. Test dekker begge oppførsler. Ingen ny vinnerberegning utenom eksisterende funksjon.

Ved kontroll var de tolv lavesteprisene identiske med produktsidene, men en produktside kan senere utelate et billigere Lensit-tilbud eller vise et annet butikkantall. Dette er en kjent begrensning før publisering: Kai bør ta stilling til separat harmonisering av eksisterende produktsider. PR-en skjuler ikke funnet og endrer ikke hele nettstedets prispraksis under dekke av en landingsside.

## Læring og neste steg

Dokumentert årsak: kommersiell filtrering i en delt prisfunksjon kan motarbeide nøytral utvalgspolicy. Ny regresjonstest hindrer dette på landingssiden; ingen plattformregel utledes fra denne lokale hendelsen. Ingen endring av felles standard er nødvendig for dette arbeidet.

Neste steg: gjennomgå Draft PR/skjermbilder, avklar eksisterende Lensit-regel og godkjenn eventuell merge/publisering uttrykkelig. Etter godkjenning: bygg fra fersk katalog, kontroller live canonical/sitemap/søk og følg GSCs query/page-fordeling når lesetilgang finnes. Ingen merge eller publisering er utført.
