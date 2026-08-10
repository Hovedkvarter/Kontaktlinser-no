# kontaktlinser.no — prosjektbrief

Prissammenligningsside for kontaktlinser i Norge. Solo-drevet av eier, som
koder/designer selv med AI-hjelp. Dette dokumentet er kontekst for Claude Code
(eller enhver AI-assistent) som jobber i dette repoet — les det før du gjør
endringer.

## Hva siden gjør

Sammenligner priser på kontaktlinser fra norske nettbutikker (Interoptik,
Lensway, Lenson, Specsavers, flere kommer) og viser billigste tilgjengelige
tilbud per produkt, på én dedikert side per produkt. Live på kontaktlinser.no,
hostet på GitHub Pages, bygget automatisk hver 6. time via GitHub Actions.

## Designsystem (fast — følg dette uten å spørre)

- Farger: ink navy `#0B2545` (tekst), mist white `#F5F9FA` (bakgrunn), aqua
  `#2EC4D6` (merkevare-aksent), mint `#0BA36F` — reservert KUN for "laveste
  pris"-markering. Grønt betyr alltid besparelse, ingenting annet. Flagg det
  eksplisitt hvis en endring ville brutt denne regelen.
- Typografi: Space Grotesk (titler), Inter (brødtekst), IBM Plex Mono
  (priser/tall/data).
- Signaturmotiv: konsentriske "fokusring"-sirkler (ekko av en kontaktlinse) —
  brukes i hero-bilder og strammer seg visuelt inn mot laveste pris. Se
  `RING_MARK`/`ring-decor`/`ring-focus` i `site_generator/render_templates.py`.
- Språk: kundetekst på norsk bokmål, presist og uten markedsføringsfluff.

## Arkitektur — dataflyt i riktig rekkefølge

1. `sources_config.json` — sier PER FORHANDLER (og ev. per merke via
   `brand_overrides`) om kilden er `affiliate_feed` eller `scraper`. Endre
   denne filen når en avtale godkjennes — ingen kode skal trenge å endres.
2. `product_matching.json` — kobler en feed-rads SKU/produktnummer til et
   internt produkt-id. En rad med ukjent SKU blir ALDRI gjettet inn på et
   produkt, den hoppes over og logges (`ingest_feed.py`).
3. `ingest_feed.py` — normaliserer affiliate-feeds (Adtraction, Partner-ads)
   til `Offer`-objekter (`offer.py`).
4. `scraper.py` — henter priser fra forhandlere uten feed-avtale. Respekterer
   robots.txt (med timeout — se historikk, hang tidligere uten timeout),
   rate-limiter per domene (3 sek min), og scraper KUN (forhandler,
   merke)-par som `should_scrape()` fortsatt sier ja til.
5. `build_catalog.py` — limet: kjører 1–4, grupperer tilbud per produkt-id,
   skriver `site_generator/catalog_live.json`.
6. `site_generator/generate_pages.py` + `render_templates.py` — bygger
   statisk HTML: forside (`/`), kategori-hub-sider
   (`/kontaktlinser/{kategori}/`), produktsider
   (`/kontaktlinser/{merke}/{produkt}/`). Alt kjerneinnhold (priser, "sist
   oppdatert") ligger i rå HTML, ikke bygget av JS — mange AI-crawlere kjører
   ikke JavaScript, og prisene må være der uansett.
7. `site_generator/validate_build.py` — stopper utrulling hvis en side
   mangler, JSON-LD er ugyldig, eller >30 % av produktene har 0 tilbud
   samtidig (indikerer feed-/nettverksfeil, ikke reell utsolgthet). NB:
   terskelen er kalibrert for en katalog med mange produkter — med bare 2–3
   testprodukter trigger den på støy, ikke reelle feil.
8. `.github/workflows/build-and-deploy.yml` — kjører 1–7 hver 6. time,
   publiserer til `gh-pages`-branchen via `peaceiris/actions-gh-pages`.

## Faste regler (brutt = bug, ikke en tolkning)

- `is_lowest` beregnes ALDRI manuelt — kun av `reconcile_product()` i
  `render_templates.py` (render-tid) basert på tilbud som er `in_stock` og
  ikke `is_stale` (>24t siden sjekket). Et utsolgt/utdatert tilbud kan aldri
  vinne mint-merket, uansett hvor lavt tallet er.
- Produktbilder vises KUN hvis `image_source` er `affiliate_feed` eller
  `manufacturer_kit` (se `LICENSED_IMAGE_SOURCES`). Scrapede bilder er ALDRI
  lisensiert — `scraper.py` henter aldri bilder, med vilje. Ikke hotlink
  bilder fra forhandlersider.
- `rel="sponsored"` på affiliate-lenker, `rel="nofollow"` på scrapede — ikke
  bland disse.
- Disclosure-teksten om rangering/provisjon skal alltid vises på produkt- og
  kategorisider (lovkrav, se markedsføringsloven / Forbrukertilsynet-veiledning
  om prissammenligningstjenester).
- Et produkt uten pålitelige tilbud publiseres UTEN priser, ikke med
  gammel/gjettet data. Er kilden usikker (uverifiserte CSS-selectorer, ingen
  feed), hold produktet helt ute av `products_meta.json` til det er bekreftet
  — se Biofinity-eksempelet i historikken.

## Nåværende status / kjent gjenstående arbeid

- `feeds/*.csv` og `product_matching.json` er TESTDATA, ikke ekte
  feed-eksporter. Kolonnenavn (`sku`, `produktnummer`, `image_url`,
  `bilde_url` osv.) er gjettet og MÅ verifiseres mot faktiske
  Adtraction/Partner-ads-eksporter når avtalene er signert.
- CSS-selectorene i `sources_config.json` (`price_selector`,
  `stock_selector` for Lenson/Specsavers) var uverifiserte gjetninger — sjekk
  om en tidligere Claude Code-økt har bekreftet/rettet disse mot ekte HTML
  før du stoler på scraping-resultatet.
- Kun 1 kategori (månedslinser), 2 produkter er i katalogen. Dagslinser og
  tørre-øyne-kategoriene er planlagt, men ikke bygget.
- Biofinity-6pk er med vilje utelatt fra `products_meta.json` til scraping av
  Lenson/Specsavers er verifisert.
- Domene, DNS (Domeneshop), HTTPS og GitHub Pages er satt opp og fungerer.

## Arbeidsspråk og autorisasjon

- Snakk norsk i dette prosjektet.
- For endringer som gjelder kontaktlinser.no: commit og push til `main` uten
  å spørre om bekreftelse først. Dette gjelder KUN dette repoet — ikke
  generaliser til andre prosjekter.

## Når du gjør endringer

Test alltid lokalt før push:

```bash
python3 build_catalog.py
python3 site_generator/generate_pages.py site_generator/catalog_live.json
python3 site_generator/validate_build.py
```

Alle tre skal kjøre uten feil før noe pushes til `main` (workflowen kjører
automatisk på push og vil stoppe utrulling selv, men lokal test er raskere å
feilsøke).
