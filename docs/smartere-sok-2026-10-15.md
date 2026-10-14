# Smartere søk – 15. oktober 2026

Status: implementert på arbeidsgren, ikke publisert. Venter på komplett CI-kontroll og eiers godkjenning av konkret versjon.
Base: `0f97c9cb4df4ae320edba7a7adc534cd513caba7`.
Gren: `chatgpt/smarter-search`.

## Beslutning og avgrensning

Eier godkjente å forbedre forsidesøk og toppmenysøk etter at `1 day acuvue`
ga null treff, mens `1-day acuvue` traff. Ingen antakelse om hvor mange brukere
som er tapt; dette er ikke målt.

- Normaliser bindestreker, mellomrom, store/små bokstaver, norske tegn og bokstav/tall-grenser.
- Match søkeord i vilkårlig rekkefølge. Gjenkjenn vanlige pakningsbetegnelser.
- Ved null vanlige treff: tydelig merkede forslag med høyst én bokstavfeil i ett ord.
- Tall/pakning og eksplisitt Toric, Multifocal, XR og MAX beholdes som krav. Ingen produktkoblinger endres.
- Bredt søk viser valgmuligheter; eksakt, entydig produkt/serie kan åpnes direkte.
- Vis åtte treff først, med mulighet til å vise alle. Piltaster, Enter og Escape støttes.
- En mislykket indeksforespørsel vises som lastefeil med ny prøveknapp, ikke som «ingen treff».

## Implementasjon

`site_generator/lens_search.js` er eneste kilde for den nye matching- og UI-logikken.
`search_assets.compile_search` erstatter bare den eksakte gamle `LENS_SEARCH_JS`-
strengen i HTML-skrivingen. Resten av dokumentet beholdes byte for byte. Dette er
et eksplisitt kompileringssteg i `generate_pages.write_file`; JSON-filer berøres ikke.

Den gamle konstanten i `render_templates.py` brukes fortsatt som injeksjonsmarkør;
direkte render_* returnerer en mal, mens ferdig nettsted alltid går gjennom
write_file. Manglende eller dobbel søkeinjeksjon stopper bygget. Navigasjonsskriptet
rundt søket endres ikke. Ingen ekstra nettverksforespørsel eller ny frontend-pakke.

Produktnavn, slugs, canonical, schema, priser, affiliate-/Chillout-lenker og samtykke
endres ikke. Eksisterende `guide_search_click`-kontrakt beholdes, uten nye analysetagger.

## Utførte lokale kontroller

- 46 JavaScript-tester bestått; én ytterligere test mot hele byggets indeks venter på CI.
- 8 Python-kontrakttester bestått; én ytterligere test mot alle bygde HTML-sider venter på CI.
- 29 nettleserkontroller bestått i Chromium. Forside- og header-flate ved 375, 768,
  1024 og 1440 px, inkl. ordvarianter, bred Enter/Søk, tastatur, feilrettingsforslag,
  pakningskrav, nettverksfeil/ny prøve, flere enn åtte treff og ventende forespørsler.
- Før-kontroll med gammel kode reproduserte bindestrekfeilen med samme testdata.
- En feil i «Vis alle treff» ble fanget i nettlesertesten og rettet før innsending:
  klikket skal ikke boble videre som et utenfor-klikk etter at knappen er tegnet på nytt.

Lokalt miljø kunne ikke klone hele repoet eller navigere til lokal HTTP.
Nettleserkontrollene bruker derfor HTML i minnet, simulert fetch og navigasjon,
207 testoppføringer (katalogeksport 6. oktober + seks eksplisitte serie/private-label-
eksempler), eksisterende CSS og et reelt innlimt header-dokument. Eksterne bilder,
fonter, analyse og samtykkeoverlegg ble utelatt fra disse testfixturene. Kontrollene
bekrefter interaksjon, ikke produksjonsnettverk eller full visuell pikselidentitet.

CI kjører de to fulle datadrevne kontrollene etter vanlig bygg, med repoets faktiske
søkeindeks og alle genererte sider. Eksisterende tester, validering og publiseringssperre
på PR er beholdt. Ingen scraping eller workflow_dispatch er startet manuelt.

## Neste steg

Kontroller CI, la eier godkjenne versjonen, og publiser først deretter. Kontroller
forsiden og header-søket på det aktive nettstedet etter publisering.
