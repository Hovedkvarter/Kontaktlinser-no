# Smartere søk – 15. oktober 2026

Status: implementert og kontrollert i PR #42, **ikke publisert**. Venter på eiers godkjenning av konkret versjon.
Base: `0f97c9cb4df4ae320edba7a7adc534cd513caba7`.
Implementasjonscommit: `c991c0f2eabe1f8b137274572c237f39fbb65a6d`.
Gren: `chatgpt/smarter-search`.
PR: https://github.com/Hovedkvarter/Kontaktlinser-no/pull/42

## Beslutning og avgrensning

Eier godkjente forbedring av forsidesøk og toppmenysøk etter at `1 day acuvue`
ga null treff, mens `1-day acuvue` traff. Antall tapte brukere er ikke målt.

- Tolerer bindestreker, mellomrom, store/små bokstaver, norske tegn og bokstav/tall-grenser.
- Match ord i vilkårlig rekkefølge og gjenkjenn vanlige pakningsbetegnelser.
- Ved null vanlige treff: merkede forslag med høyst én bokstavfeil i ett ord.
- Tall/pakning og eksplisitt Toric, Multifocal, XR og MAX beholdes som krav.
- Bredt søk viser alternativer; eksakt, entydig produkt/serie kan åpnes direkte.
- Åtte treff først, Vis alle, piltaster, Enter og Escape.
- Lastefeil vises som lastefeil med ny prøveknapp, ikke som null treff.

## Implementasjon og bevaring

`site_generator/lens_search.js` er felles kilde for matching og søkegrensesnitt.
`search_assets.compile_search` erstatter bare den eksakte gamle `LENS_SEARCH_JS`-
strengen i HTML-skrivingen. Resten av dokumentet beholdes byte for byte.
Dette er et eksplisitt steg i `generate_pages.write_file`; JSON-filer berøres ikke.
Den gamle konstanten brukes fortsatt som injeksjonsmarkør. Direkte render_*-kall
returnerer en mal; ferdig nettsted går gjennom write_file. Manglende eller dobbel
søkeinjeksjon stopper bygget.

Produktnavn, slugs, canonical, schema, priser, affiliate-/Chillout-logikk, meny og
samtykke er uendret. Eksisterende `guide_search_click` beholdes, uten nye analysetagger.
Ingen ny frontend-pakke eller ekstra nettverksforespørsel for søkeprogrammet.

## Verifisert

CI-kjøring 38657350661, jobb 116170158291, på implementasjonscommit c991c0f:

- 24 eksisterende tester bestått.
- Hele nettstedbygget og `validate_build.py` bestått; 227/227 produkter har priser.
- 47 JavaScript-tester bestått, ingen hoppet over. Alle 379 oppføringer i den faktiske
  søkeindeksen finner egen opprinnelig URL ved søk på fullt navn. De tre Acuvue-
  skrivemåtene gir identiske, ikke-tomme treffsett.
- 9 Python-tester bestått, ingen hoppet over. 480 genererte HTML-sider har nøyaktig
  ett nytt søkeprogram og ingen gammel søkemotor.
- Publisering, scraping og tilbakeskriving av prisdata ble hoppet over på PR.

Lokalt: 29 Chromium-kontroller bestått for forside/header ved 375, 768, 1024 og
1440 px. Dekker ordvarianter, bred Enter/Søk, tastatur, skriveforslag, pakningskrav,
lastefeil/ny prøve, Vis alle og ventende forespørsler. Før-kontrollen reproduserte
bindestrekfeilen. En Vis alle-feil med klikkbobling ble fanget og rettet før PR.

**Begrensning:** Repoet kunne ikke klones i arbeidsmiljøet. Nettleserkontrollene
brukte HTML i minnet, simulert fetch/navigasjon og 207 testoppføringer fra eksporten
6. oktober pluss seks eksplisitte eksempler. Eksisterende CSS/header ble brukt,
men eksterne bilder, fonter, analyse og samtykkeoverlegg ble utelatt. Dette er
interaksjonstester, ikke full visuell produksjonskontroll. CI brukte faktisk kode
og katalog, men kjørte ikke nettleser.

Bygget rapporterte også 27 produkter uten Chillout-kobling, med eksisterende
fallback til leverandør-URL, og advarsler om Node-versjon i eksisterende Actions.
Disse forholdene er ikke endret eller løst av søkeoppgaven.

## Neste steg

Eier ser testvisningen og godkjenner konkret PR-versjon. Kontroller siste CI og
publiser først etter godkjenning. Kontroller deretter søket på det aktive nettstedet,
inkludert faktiske bilder, mobilheader og navigasjon til valgt produkt.
