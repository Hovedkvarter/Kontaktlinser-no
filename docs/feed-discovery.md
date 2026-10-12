# Automatisk kontroll av nye feedprodukter

Kontrollen leser alle aktive affiliate-feeds fra `sources_config.json`. Den importerer eller kaller aldri `scraper.py`, `build_catalog.py` eller butikkers produktsider. Den oppretter ingen produkter og endrer ingen priser, bilder eller koblinger.

## Resultat ved etablering 13. oktober 2026

Seks komplette feeds inneholder 34 709 rader. 722 rader er relevante eller allerede koblet til katalogen, og 603 av disse er koblet til publiserte produkt-ID-er. De resterende 119 radene er vurdert i `feed_discovery_review.json`.

| Vurdering | Feedrader |
|---|---:|
| Ny produktkandidat | 57 |
| Ny pakning/variant | 6 |
| Mulig ny butikkobling til eksisterende produkt | 12 |
| Avklar pakning | 14 |
| Avklar motstridende feeddata | 7 |
| Avklar produkttype | 1 |
| Vurder sortiment (kosttilskudd og legemiddel-/spesialprodukter) | 19 |
| Allerede dekket av annen SKU | 2 |
| Utgått i feedtekst | 1 |

Dette er forhandlerrader, ikke 119 nye unike produkter. De 57 nye kandidat-radene er samlet i 39 foreløpige produktgrupper; gruppering er ikke identitetsbekreftelse. Pakningsstørrelser og varianter kan fortsatt skille produkter innen samme gruppe.

Prioriterte funn er Blephaclean-servietter og MediPearl-øyemaske (begge finnes i fire feeds), Blephacura, Blephasol Duo, POSIFORLID Eye Wipes og øyemaske, linseetuier og EvoTears OMEGA. Nye linsefamilier i feedene inkluderer Supra 55 UV Tint, clearcolor 1-day Phantom, FreshLook ColorBlends og Air Optix Aqua. De to sistnevnte er eldre produkter; feedtilstedeværelse er ikke bevis for fortsatt produksjon eller reell tilgjengelighet.

Shopping4net har 11 mulige nye koblinger: fire Precision1-pakninger, to Opti-Free PureMoist-størrelser, Hylo Dual, tre OXYAL-varianter og POSIFORLID Eye Spray. Lensways everclear REFRESH Solution Kit må sammenlignes med eksisterende 3-pack 750 ml.

Brillelands to ekstra TOTAL30 Multifocal-rader er dokumenterte addisjonsvarianter av allerede koblet SKU 40000718. De er ikke nye produkter. Extra Optical har blant annet et varenummer som sier MyDay med tittel Proclear, samt motstridende Systane-navn. Shopping4nets Desodrop-rad sier 10 gram mens SKU slutter på 8. Disse er ikke koblet på gjetning.

## Full dekning av feedene

- Adtraction: hele CSV-eksporten for Extra Optical, Brilleland og Apotekhjem.
- Tradedoubler: `productsUnlimited.json` for Lensway, Lenson og Shopping4net. Dette er hele feeden, ikke de eksisterende prissøkene som filtrerer på kjente merkenavn.
- Tradedoubler dokumenterer en grense på 1 000 produkter i vanlige søk. Fullfeedene omgår denne søkegrensen gjennom nettverkets støttede nedlastingsmetode, ikke ved å omgå tilgangskontroll.
- `lastUpdated` sjekkes før ny fullfeed lastes ned. Uendret fullfeed gjenbrukes fra Actions-cache. Råfeedene eller tilgangstokenene legges ikke i rapporten eller Git.
- Kilde: https://dev.tradedoubler.com/products/publisher/

Relevansfilteret inkluderer linsekategorier, øyepleie, linsepleie, linseetuier, øyemasker og enkelte relaterte øyeprodukter. Alle eksisterende koblinger kontrolleres uavhengig av kategorifilter. Kosmetikk, dyreprodukter, generelle apotekvarer og brilleprodukter er utenfor hovedlisten. Feil kategorisering og helt ukjente navn kan kreve at filteret utvides; dette er ingen garanti for at fremtidige feilmerkede produkter fanges opp.

## Drift og gjennomgang

Workflow: `.github/workflows/feed-discovery.yml`.

- Kjøres hver dag kl. 03:20 UTC (05:20 norsk sommertid / 04:20 vintertid), og kan startes manuelt i GitHub Actions.
- PR-er tester logikken uten nettverk. Den planlagte kjøringen henter bare feeds.
- Resultatet lagres i `reports/feed-discovery/latest.md` og `latest.json`, i jobbens sammendrag og som nedlastbart artifact (90 dager).
- Rapportcommitter har `[skip ci]` og publiserer ikke nettstedet.
- Nye og endrede rader merkes med `first_seen`, `last_seen` og `observation`. Identiteten er forhandler + feed-SKU, aldri produktnavnet alene.
- Manuelle vurderinger står i `feed_discovery_review.json`, med et fingeravtrykk av den vurderte radens identitetsfelter. Endres disse, åpnes vurderingen på nytt. Prisendringer alene er ikke et nytt produkt.
- En feedfeil, ugyldig fil, tom feed eller fall til under halvparten av forrige radantall gir synlig feil. Forrige kandidater beholdes som ikke kontrollert; de markeres ikke som fjernet. Jobben feiler etter at rapporten er lagret.
- Ingen ny produktside eller kobling publiseres automatisk. Kontroller navn, variant, pakning, identitet og tilbud før endring i grunnkatalogen.

## Lokal kjøring

```sh
python -m unittest test_feed_discovery -v
python feed_discovery.py
```

Et allerede nedlastet feedsett kan behandles uten nettverk med `--offline --cache /sti/til/cache`. Dette er for utvikling og analyse; den automatiske rutinen bruker ikke offline-modus.
