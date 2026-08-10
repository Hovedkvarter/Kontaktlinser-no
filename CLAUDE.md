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
- Lenson og Lensway (samme plattform/LensGroup) er verifisert mot ekte HTML
  (28.08.2026) og scraper faktisk live priser — se `sources_config.json`.
  VIKTIG: begge er React-apper som ALDRI server-rendrer pris i DOM-en, kun i
  en analytics-JSON-blob i en `<script>`-tag (`price_source: "embedded_json"`
  i `scraper.py`). Ikke bytt disse to tilbake til CSS-selectorer uten å sjekke
  dette på nytt.
- Bekreftede affiliate-nettverk så langt: Lenson, Lensway og Shopping4net
  kjører alle via **Tradedoubler**. ExtraOptical og Lensit har programmer,
  men nettverk er ikke bekreftet.
- ExtraOptical er BLOKKERT for skraping: ren React-app (Magento/Venia) uten
  embedded prisdata i rå-HTML, krever JS/GraphQL som dagens scraper bevisst
  ikke gjør. Shopping4net er BLOKKERT: robots.txt finnes ikke på domenets rot
  (kun på `/no/robots.txt`, ugyldig plassering), så `robots_allows()` nekter
  scraping inntil det er avklart med dem. Selectorene for begge er verifiserte
  og klare — se `$comment` per forhandler i `sources_config.json` for detaljer
  og mulige løsninger.
- SmartBuyGlasses er IKKE lagt til: robots.txt blokkerer `/product/` for
  vanlige botter, kun Googlebot har unntak. Prospekt for affiliate-avtale,
  men ingen skraping uten å utgi seg for å være Googlebot.
- Specsavers er IKKE lagt til: siden sitter bak en Cloudflare bot-utfordring
  ("Just a moment...", `Cf-Mitigated: challenge`) -- vi løser ikke
  CAPTCHA/bot-utfordringer. Selectorene i `sources_config.json` er fortsatt
  uverifiserte gjetninger fra tidligere, aldri testet mot ekte HTML.
- **6 aktive forhandlere**: Lenson, Lensway, Lensit, Interoptik, Synsam,
  Brilleland. Synsam er en Next.js-app -- pris hentes fra standard
  `__NEXT_DATA__`-JSON-blob (samme embedded_json-mekanisme som
  Lenson/Lensway, men Next.js sitt eget stabile mønster, ikke en
  egendefinert analytics-blob). Brilleland kjører på SAMME plattform som
  Interoptik (identisk `.price-big`-selector og URL-struktur).
- 5 kategorier (månedslinser, dagslinser, toriske linser, fargede linser,
  multifokale linser), 61 produkter totalt (28.08.2026). Alle 61 har tilbud
  fra Lenson+Lensway, 54 har i tillegg Lensit, 34 Interoptik, 28 Synsam, 19
  Brilleland (snitt **4,2 forhandlere/produkt**). Manglende dekning er
  alltid fordi forhandleren faktisk ikke fører akkurat den
  varianten/pakningsstørrelsen (bekreftet ved gjennomgang av deres egne
  merke-/kolleksjonssider) -- IKKE fordi det ikke er sjekket. Ikke gjett/legg
  til scrape_targets for et par som ikke faktisk er verifisert å eksistere
  hos den forhandleren. Tørre-øyne-kategorien er fortsatt ikke bygget.
- Synsam og Brilleland selger delvis under egne private label-merker
  (EyeQ hos Synsam, iWear hos Brilleland) -- disse er IKKE koblet inn siden
  de ikke finnes hos andre forhandlere (ville uansett bare vist ett tilbud).
  Kun ekte merkevarer (Acuvue, Biofinity, Dailies osv.) som også finnes
  andre steder er koblet sammen.
- ADORE (2 produkter) og Acuvue Vita finnes kun hos Lenson/Lensway (bekreftet
  fraværende hos Lensit og Interoptik). Precision7 hos Interoptik selges kun
  i 12-pakning (vårt produkt er 6-pakning) -- bevisst IKKE koblet til
  Interoptik siden det ville sammenlignet ulike pakningsstørrelser.
- `render_brand_page()` bygger nå `/merke/{slug}/` -- disse lenkene lå i
  brødsmulen på HVER produktside og i sitemapen fra dag én, men siden ble
  ALDRI bygget (ren 404 for både brukere og søkemotorer inntil dette ble
  oppdaget 28.08.2026). `render_product_page()` og `render_brand_page()`
  trenger nå `categories`-dicten som eget argument (ikke bare product-objektet)
  for å vise riktig kategorinavn med æøå -- de brukte tidligere kategori-slugen
  direkte som visningstekst, som også var en (mindre alvorlig) visningsfeil.
- Forsiden har et "Merker"-rutenett (linker til `/merke/{slug}/`, sortert
  etter flest produkter) mellom søkefeltet og kategori-rutenettet, inspirert
  av lenspricer.no sin merke-først-navigasjon. Pluss en dekorativ
  ring-bakgrunn i heroen (SVG, gjenbruker ring-motivet). NB: `.brand-card`
  MÅ ha `min-width: 0` på både kortet og tekst-wrapperen -- uten den tvinger
  lange merkenavn + antall-tekst grid-kolonnen bredere enn viewporten og gir
  horisontal scroll på mobil (fant og fikset dette 28.08.2026, testet på
  375px bredde).
- Lensons/Lensways listeside (ikke bare produktsiden) inneholder SAMME
  universalAnalyticsInfo-JSON-blob som produktsiden, med productId, navn,
  pris, kategori og produsent for ALLE produkter på siden (`?_page=0` til
  `?_page=13` gir ~293 unike produkter totalt). Slug-mønsteret er
  `{slugify(navn)}-lens-{productId}` -- bekreftet stabilt på tvers av
  titalls produkter. Bruk dette fremfor å skrape enkeltsider når flere
  produkter skal legges til samtidig -- MYE raskere enn nettleser-basert
  paginering.
- Alle 61 produkter har nå `specs` (liste av [label, verdi]-par: materiale,
  vanninnhold, basiskurve, diameter, styrkeområde, brukstid, linsetype, evt.
  sylinder/akse/addisjon) og `long_description` (unik, faktabasert, 2-3
  setninger) i `products_meta.json`. Data er satt sammen fra Interoptiks
  egne spesifikasjonstabeller (der produktet finnes der) og offentlig
  produsentinformasjon -- IKKE hentet fra pakningsvedlegg, så behandle som
  veiledende. `render_product_page()` viser dette som en spesifikasjonstabell
  og utvider Product-JSON-LD-en med description + additionalProperty per
  spec, til nytte for søkemotorer/AI-svarmotorer. Nye produkter bør få
  samme behandling -- ikke bare pris/lenke.
- Interoptik hadde tidligere en `brand_overrides.acuvue` som pekte på en
  FALSK adtraction-testfeed (`feeds/adtraction_interoptik_acuvue.csv`,
  aldri en reell avtale, fake URL-er som `track.adtraction.com/example-...`).
  Fjernet på eksplisitt beskjed (28.08.2026) — Interoptik skraper nå direkte
  som de andre forhandlerne, med verifiserte selectorer
  (`.price-big`, url-mønster `/kontaktlinser/{merke}/{produkt}/`). Ikke legg
  den falske feeden tilbake med mindre en ekte Adtraction-avtale er signert.
- `retailer`-feltet i tilbud kommer fra `display_name` i
  `sources_config.json` per forhandler, IKKE fra den lowercase config-nøkkelen
  (`lenson`, `lensway` osv.) — sett `display_name` når en ny forhandler legges
  til, ellers vises navnet med små bokstaver på siden.
- Biofinity-6pk er lagt tilbake i `products_meta.json` — Lenson er nå
  verifisert (Specsavers er det fortsatt ikke, men det kravet er innhentet av
  fire andre bekreftede kilder).
- Specsavers er IKKE rørt — fortsatt uverifiserte gjetninger i
  `sources_config.json`.
- `render_guide_page()` i `render_templates.py` + `GUIDE_CONTENT`-dict
  (samme fil) bygger nå faktiske guide-sider til `/guide/{slug}/`. Disse var
  tidligere døde lenker fra kategorisidene -- generate_pages.py sin build()
  itererer over alle guide-slugs referert i categories og bygger dem. Ny
  kategori med guide krever enten en ny nøkkel i GUIDE_CONTENT, eller
  gjenbruk av en eksisterende guide-slug.
- Forsiden (`render_home_page()`) har nå søk (client-side filter,
  progressiv forbedring) + et rutenett med kategorikort + et rutenett med
  alle linser, inspirert av lenspricer.no sin "finn din linse raskt"-modell.
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
