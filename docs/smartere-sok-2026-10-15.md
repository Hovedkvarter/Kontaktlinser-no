# Smartere søk – 15. oktober 2026

Status: **publisert og kontrollert mot aktivt nettsted** etter eiers uttrykkelige godkjenning av PR #42, versjon `9c687a1359001d8499c378c4f7d9fb24e5fc0b0f`.
Base: `0f97c9cb4df4ae320edba7a7adc534cd513caba7`.
Implementasjonscommit: `c991c0f2eabe1f8b137274572c237f39fbb65a6d`.
Gren: `chatgpt/smarter-search`.
PR: https://github.com/Hovedkvarter/Kontaktlinser-no/pull/42

## Publisering og produksjonskontroll

- Godkjent head ble kontrollert uendret, og siste PR-CI 38657592923 var bestått før merge. Merge brukte eksakt forventet head-SHA.
- Merge: `5be409daba22c12ff486ee8bd8ce7a204b4a8b91`.
- Bygg, søketester, validering og publiseringssteg bestod i kjøring 38658021927. Ingen ny feedinnhenting eller scraping ble startet.
- Publisert gh-pages-commit: `adaf27b42a4f9c28f7913c0759851ab98a9a0d2c`. GitHub Pages-kjøring 38658155765 bestod; ferdig 15. oktober 2026 kl. 00:07:35 UTC.
- Etterkontroll: 8 av 8 nettleserscenarier bestod i kjøring 38658490119, jobb 116173840898, ferdig kl. 00:11:34 UTC.

Etterkontrollen brukte ekte Chromium mot de ordinære nettadressene på
https://kontaktlinser.no – ingen simulert HTML, søkeindeks eller navigasjon.
Forsidesøk og toppmenysøk på Acuvue Moist 30-pack ble prøvd ved 375, 768,
1024 og 1440 px. Alle åtte scenarier bekreftet:

- HTTP 200 og at den komplette godkjente søkekilden faktisk ble servert.
- Identiske synlige treff for `1 day acuvue`, `1-day acuvue` og `1day acuvue`.
- Brede Enter-søk viser variantvalg, og Vis alle utvider trefflisten.
- `dailies total1` og `dailies total 1` gir identiske treff.
- `biofinity toric 6 pk` beholder både Toric og 6-pakning som krav.
- `acuve moist` gir tydelig merkede skriveforslag.
- Escape lukker listen; piltast og Enter åpner treffets opprinnelige interne adresse.
- Søkelisten holder seg innenfor skjermbredden. Ingen ukjente JavaScript-unntak ble registrert under scenariene.

Testjobben er isolert på `chatgpt/verify-search-publish-20261015`, uten tilgang
til å skrive repository-innhold, uten deploy-steg og uten planlagt gjentakelse.
Den er ikke merget til main og endrer ikke nettstedet. Den ble brukt fordi det
lokale arbeidsmiljøet ikke kunne slå opp nettstedets DNS. Rapport og åtte
skjermbilder er lagret som Actions-artefakten `published-search-verification`
(ID 11938360712, sju dagers oppbevaring). Skjermbildene er ikke manuelt visuelt
gjennomgått i denne etterkontrollen. Testen dekker Chromium ved disse breddene,
ikke alle nettlesere eller fysiske telefoner. Pris-/affiliatekjøp ble ikke utført.

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
samtykke er uendret av søkeimplementasjonen. Eksisterende `guide_search_click`
beholdes, uten nye analysetagger. Ingen ny frontend-pakke eller ekstra
nettverksforespørsel for søkeprogrammet.

## Verifisert før publisering

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

**Begrensning ved førkontrollen:** Repoet kunne ikke klones i arbeidsmiljøet.
De lokale nettleserkontrollene brukte HTML i minnet, simulert fetch/navigasjon og
207 testoppføringer fra eksporten 6. oktober pluss seks eksplisitte eksempler.
Eksisterende CSS/header ble brukt, men eksterne bilder, fonter, analyse og
samtykkeoverlegg ble utelatt. Den opprinnelige PR-CI-en brukte faktisk kode og
katalog, men kjørte ikke nettleser. Etterkontrollen ovenfor supplerer dette med
reelle nettleserscenarier mot publisert nettsted.

Bygget rapporterte også 27 produkter uten Chillout-kobling, med eksisterende
fallback til leverandør-URL, og advarsler om Node-versjon i eksisterende Actions.
Disse forholdene er ikke endret eller løst av søkeoppgaven.

## Åpne spørsmål og neste steg

Publiseringen av denne versjonen er ferdig. Hvor mange brukere som tidligere
møtte null treff eller forlot nettstedet, og effekten av endringen på faktisk
bruk, er ikke målt. Eventuell måling og videre søkeforbedringer er egne oppgaver;
ingen nye analysetagger eller automatiske overvåkninger er opprettet.
