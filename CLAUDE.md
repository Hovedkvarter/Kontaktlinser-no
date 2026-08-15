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
- `TOPBAR_HTML` (i `render_templates.py`) er nå en delt konstant brukt av
  ALLE sidetyper -- ikke skriv `<div class="topbar">...` for hånd i en ny
  mal, bruk `{{TOPBAR_HTML}}`. Menyen (Merker/Kategorier/Guider) peker på
  anker på forsiden (`/#merker`, `/#kategorier`) siden vi ikke har egne
  samleider for det -- IKKE fjern `id="merker"`/`id="kategorier"` fra
  seksjonsoverskriftene på forsiden uten å oppdatere menyen tilsvarende.
- `render_guides_index_page()` bygger `/guider/` -- la til fordi
  toppmenyen trengte et mål og vi ikke hadde noen oversiktsside for de to
  guidene fra før.
- Forsidens hero har nå et ekte foto (`static/hero-eye.jpg`, Amanda
  Dalbjörn, fri Unsplash-lisens, kreditert i footer-teksten under bildet).
  `generate_pages.py` kopierer alt i `static/` til `build/static/`
  automatisk ved hver bygging (ikke noe eget steg i CI-workflowen) -- legg
  nye statiske filer i `static/` i repo-roten, ikke i `site_generator/`.
  Trygghetsstripen under heroen (forhandlerantall, produktantall osv.) er
  regnet ut dynamisk fra katalogen, IKKE hardkodede tall -- ikke bytt den
  til statisk tekst, og legg ALDRI til stjerner/anmeldelser vi ikke faktisk
  har (ba bevisst om å utelate dette fra en designreferanse 28.08.2026,
  siden vi ingen Trustpilot-integrasjon har).
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
- `render_privacy_page()` bygger `/personvern/` -- cookie-/personvernside,
  lenket fra footeren. Trigget av at Tradedoubler (affiliate-nettverket for
  Lenson/Lensway/Shopping4net) krever dette, men strukturen/innholdet følger
  den faktiske juridiske standarden (ekomloven § 3-15 + GDPR), ikke bare
  Tradedoublers krav -- modellert etter Datatilsynets egen cookie-erklæring.
- Samtykke-banner (`CONSENT_BANNER_HTML`/`CONSENT_SCRIPT` i
  `render_templates.py`, satt inn på ALLE sider rett før `</body>`, samme
  mønster som `render_footer()`) lagt til 2026-08-11 under forutsetning om at
  Tradedoubler + Awin + Adtraction-avtaler er på plass (fortsatt ikke reelt
  signerte avtaler -- bytt ut nettverksnavnene i banner-teksten og
  `/personvern/`-tabellen den dagen faktiske avtaler er signert, hvis andre
  nettverk enn disse tre blir aktuelle). GTM lastes IKKE lenger automatisk --
  `GTM_HEAD` definerer kun `window.__loadGTM()`, som `CONSENT_SCRIPT` kaller
  ETTER samtykke (enten lagret fra forrige besøk i `localStorage`
  `kl_consent_v1`, eller når bruker trykker "Godta alle"/"Lagre valg" med
  statistikk på). To atskilte kategorier (statistikk/affiliate), ikke bundlet
  i ett valg -- det er et eksplisitt Datatilsynet-krav. Ingen
  `<noscript>`-GTM-fallback lenger (fjernet med vilje: uten JS kan vi ikke
  innhente samtykke interaktivt, så vi skal ikke sette cookien for de
  besøkende heller). IKKE gjør GTM_HEAD til en auto-kjørende tag igjen uten å
  fjerne/erstatte samtykke-banneret samtidig -- da mister vi poenget med det.

- SEO-runde 2026-08-11: `rel="canonical"` lagt til på alle 8 sidetyper,
  `render_404_page()` bygger `build/404.html` (GitHub Pages plukker denne
  opp automatisk med ekte HTTP 404), og begge guidene har fått en ekte,
  synlig "Ofte stilte spørsmål"-seksjon + tilhørende FAQPage-JSON-LD
  (spørsmålene er omformulert fra eksisterende guide-innhold, ikke nye
  påstander -- se `faq`-nøkkelen i `GUIDE_CONTENT`).
- **Gamle `.aspx`-URL-er kan IKKE omdirigeres med en statisk fil på GitHub
  Pages.** Testet empirisk 2026-08-11: `.aspx` finnes ikke i mime-db
  (databasen GH Pages bruker for content-type), og serveres derfor som
  `application/octet-stream` (nedlasting, ikke HTML) -- en
  meta-refresh-fil på den gamle stien vil aldri kjøre i nettleseren. Reelle
  alternativer er (a) legge domenet bak Cloudflare (proxy-modus) og bruke
  Page Rules/en Worker til ekte 301-er, eller (b) la de gamle URL-ene fortsatt
  gi 404 og heller stole på at de faller ut av Googles indeks over tid.
  Ingen av delene er gjort -- krever et bevisst valg fra bruker (Cloudflare
  er en infrastrukturendring på DNS-nivå, ikke noe som bør gjøres
  ensidig). Ikke gjenta .aspx-testen, resultatet er allerede bekreftet.

- **Kritisk databug funnet og fikset 2026-08-12: Lensit viste feil
  pakningsstørrelses pris på 13 av 54 produkter.** Bruker oppdaget at
  Air Optix HydraGlyde for Astigmatism 6-pack viste "laveste pris" fra
  Lensit som egentlig var 3-pack-prisen. Årsak: Lensit er Shopify, og
  pakningsstørrelse er et variant-valg PÅ SAMME produkt-url (ikke egen
  side per pakningsstørrelse) -- den gamle CSS-selector-skrapingen
  (`.price-item--regular`) plukket blindt opp prisen til whatever variant
  Shopify rendret som forhåndsvalgt i rå-HTML-en, uten noen feilmelding
  når det var feil variant. Full audit av alle 54 Lensit-scrape_targets
  (via variant-JSON-en i `<script id="ProductJson-product-template">`)
  fant: 10 produkter med feil default-variant (nå fikset), og 3 produkter
  (Biofinity XR, Precision7, Precision7 for Astigmatism) der Lensit ikke
  en gang SELGER vår pakningsstørrelse i det hele tatt -- Lensit-target
  fjernet for disse tre, samme prinsipp som Precision7/Interoptik-unntaket
  lenger opp i dette dokumentet.
  **Fix:** `sources_config.json` sin lensit-entry bruker nå
  `"price_source": "shopify_variant_json"`, og hvert scrape_target for
  lensit i `products_meta.json` har et `"variant"`-felt (Shopify sin
  `public_title`/`title`, f.eks. `"6"` eller `"30"`).
  `_find_price_in_shopify_variants()` i `scraper.py` matcher eksakt mot
  dette feltet og gjetter ALDRI nærmeste variant -- finnes ingen treff,
  hentes ingen pris (samme "ikke gjett"-prinsipp som resten av siden).
  Legger du til et NYTT Lensit-produkt: husk `"variant"`-feltet, ellers
  hentes ingen pris i det hele tatt (fail-safe, ikke fail-silent).

- **Første ekte affiliate-avtale live: ExtraOptical via Adtraction
  (2026-08-12).** Tidligere blokkert for skraping (ren React-app uten
  server-rendret prisdata) -- løst av seg selv med en ekte feed i stedet.
  Feeden er Adtraction sitt Google Shopping-formaterte eksport
  (kolonner: id/title/link/image_link/price/availability/brand osv.) --
  HELT ANNERLEDES enn den tidligere gjettede test-strukturen
  (merchant_name/tracking_url/sku), som nå er fjernet sammen med den falske
  testfilen `feeds/adtraction_interoptik_acuvue.csv`. `map_adtraction_row()`
  i `ingest_feed.py` er oppdatert til de ekte feltnavnene. `link`-kolonnen
  ER allerede den ferdige affiliate-trackinglenken (limes rett inn som
  tilbudets url), og `image_link` er et lisensiert produktbilde (kvalifiserer
  for `LICENSED_IMAGE_SOURCES`).
  **Ny arkitektur-mulighet:** `sources_config.json` støtter nå `feed_url`
  (hentes FERSK over HTTP ved hver bygging via `load_feed_url()`) som
  alternativ til `feed_path` (lokal fil, brukt av testdata). ExtraOptical
  bruker `feed_url` siden dette er en levende feed, ikke noe som lastes ned
  manuelt.
  Av feedens 75 kontaktlinse-rader matcher 49 mot eksisterende produkter
  (lagt i `product_matching.json` sin `adtraction`-tabell). De resterende 26
  er bevisst IKKE koblet: enten fører vi ikke produktet, pakningsstørrelsen
  matcher ikke (samme prinsipp som Precision7/Interoptik), eller selve
  feed-raden har motstridende id/title (f.eks. `id="MyDay 1 Day Toric 30
  stk"` med `title="Biomedics 1 Day Extra Toric 30 stk"`, og to
  PureVision2/PureVision2-HD-rader med forvirrende id/title-par som ikke lot
  seg skille fra hverandre med sikkerhet) -- disse gjettes ALDRI inn.
  `RETAILER_LOGOS["Extra Optical"]` (og `static/logos/extraoptical.svg`) var
  allerede satt opp fra tidligere -- `display_name` i sources_config.json må
  fortsatt matche "Extra Optical" nøyaktig for at logoen skal slå til.
  **VIKTIG:** ExtraOptical-tilbud kobles UTELUKKENDE via
  `product_matching.json` sin `adtraction`-tabell (feedens `id`-felt →
  produkt-id) -- IKKE via `scrape_targets` i products_meta.json.
  `should_scrape()` filtrerer stille bort ethvert `scrape_targets`-element
  med `retailer: "extraoptical"` siden `default_source` der er
  `affiliate_feed`, ikke `scraper` -- et slikt element gjør ingenting, bare
  villeder senere lesere. Ikke legg extraoptical inn i scrape_targets.

- **24 nye kontaktlinse-produkter lagt til (2026-08-14)**, alle produkter
  ExtraOptical-feeden dekket som vi ikke hadde i katalogen fra før (Acuvue
  Moist Multifocal, Acuvue Oasys 1-Day for Astigmatism, Dailies
  AquaComfort Plus i Multifokal/Torisk/180-pakning, Dailies Total1
  180-pakning, Focus Dailies 180-pakning, hele Proclear 1 Day-serien,
  Proclear Multifocal/Multifocal Toric/Multifocal XR/Toric XR, SofLens
  38/Multifocal/Daily Disposable for Astigmatism, Biofinity Multifocal
  Toric, Biofinity XR Toric). De fleste fikk i tillegg Lenson+Lensway
  verifisert via samme bulk-listeteknikk som tidligere (paginert
  `/no/kontaktlinser/?_page=0..13`, ~292 unike produkter) -- IKKE
  Interoptik/Brilleland/Synsam, det er ikke gjort for disse 24 ennå.
  **Kritisk funn underveis:** Lenson/Lensway sin produkt-id 4244
  ("biofinity-xr-lens-4244"), som det EKSISTERENDE `biofinity-xr-6pk`
  brukte, er faktisk en 3-pakning ("Biofinity XR 3 stk/pk", bekreftet i
  sidetittelen) -- IKKE en 6-pakning. Lenson/Lensway fører tilsynelatende
  ikke Biofinity XR i 6-pakning i det hele tatt (kun ett oppslag i hele
  katalogen deres). `biofinity-xr-6pk` sine lenson/lensway scrape_targets
  er fjernet (står nå med `[]` derfra, men har fortsatt et gyldig
  ExtraOptical-tilbud), og selve id 4244 er flyttet til det NYE
  `biofinity-xr-3pk`-produktet i stedet, sammen med Lensit sin
  `biofinity-xr-1`-variant (`variant: "3"`) som opprinnelig ble fjernet fra
  6-pack-produktet i Lensit-variant-fiksen tidligere samme dag. Sjekk
  pakningsstørrelse i selve sidetittelen/-teksten før du kobler en
  Lenson/Lensway-id til et produkt -- produktnavnet i deres analytics-blob
  (`universalAnalyticsInfo`) inneholder IKKE pakningsstørrelse, bare
  produktsiden selv gjør.
  Tre opprinnelig uklare ExtraOptical-feedrader ble oppklart ved å lese
  description-feltet og destinasjons-URL-en i tillegg til id/title (som
  motsa hverandre i title-feltet alene): "MyDay 1 Day Toric 30 stk" (id) →
  faktisk MyDay, ikke Biomedics som title feilaktig sa → `myday-toric-30pk`.
  "PureVision 6 stk-2" (id) → faktisk vanlig PureVision, ikke "PureVision 2"
  som title feilaktig la til → `purevision-6pk`. "PureVision 2 6 stk" (id)
  → bekreftet ekte PureVision2 HD (samme specs som vårt eksisterende
  `purevision2-6pk`) → `purevision2-6pk`.
  `_pack_size_from_id()` i `render_templates.py` generaliserte
  søsken-kryssreferansen (tidligere hardkodet til kun 30/90-par) til å finne
  NÆRMESTE søsken i en hvilken som helst pakningsstørrelse -- nødvendig nå
  som Biofinity XR har et 3/6-par og Dailies AquaComfort Plus har et
  30/90/180-triplett.

- **Prisutvikling-graf per produkt (2026-08-14)**, inspirert av
  lenspricer.no (som bruker Chart.js -- vi gjør det samme uten noe
  JS-bibliotek, ren SVG generert server-side, i tråd med prinsippet om at
  kjerneinnhold skal fungere uten JavaScript). Viser laveste pris per dag
  (ikke per forhandler -- én linje, samme som lenspricer), pluss hvilken
  butikk som hadde den. `price_history.py` (repo-rot) har hele
  lagrings-logikken: `record_price()` overskriver dagens rad i stedet for å
  legge til en ny, siden bygget kjører 4x/dag men vi vil ha ett punkt per
  dag. Beholder maks 365 dager (`MAX_DAYS`), eldre rader forsvinner
  automatisk. Data lagres i `site_generator/price_history.json`, commitet
  tilbake til repoet i et eget steg i workflowen (samme mønster som
  catalog_live.json, men kjører på ALLE event-typer siden
  generate_pages.py -- som skriver filen -- selv kjører uansett
  push/schedule/manuell).
  `_render_price_history_chart()` i `render_templates.py` viser INGENTING
  før produktet har minst 7 dagers historikk (en 2-punkts strek dag 2 ser
  useriøs ut) -- grafen dukker opp av seg selv etter en ukes drift og vokser
  videre dag for dag helt automatisk, ingen egen "fase 2"-logikk nødvendig.
  Startet fra null 2026-08-14 -- ingen historisk data å vise før den datoen,
  i motsetning til lenspricer sine 360 dager.
  Begge auto-commit-stegene i workflowen (catalog_live.json og
  price_history.json) gjør nå `git pull --rebase origin main` før `git
  push` -- uten det feiler pushen (non-fast-forward) hvis to kjøringer
  overlapper (f.eks. et push-trigget bygg og en manuell kjøring rett
  etter hverandre, som skjedde og feilet 2026-08-14 før denne fiksen).

- **Nok en pakningsstørrelse-bug funnet og fikset (2026-08-14), denne
  gangen hos Brilleland.** Bruker oppdaget at Biofinity Multifocal 6-pack
  viste Brilleland som "laveste pris" på 431 kr -- vesentlig lavere enn de
  andre forhandlernes ~660-890 kr. Årsak: Brilleland selger produktet under
  sitt eget private label-navn ("iWear Oxygen Presbyopia", bekrefter for
  øvrig lenspricer.no sin private label-mapping uavhengig), og
  scrape_targets-slugen vår (`biofinity-multifocal-cd/biofinity-multifocal`)
  pekte på 3-pack-varianten, ikke 6-pack -- Brilleland sin url-struktur for
  "søk på originalmerke" ser ut til å kunne lande på feil pakningsstørrelse
  når flere finnes under samme private label-linje, uten at slugen selv
  avslører det (INGEN pakningsstørrelse i selve slug-teksten, i motsetning
  til de fleste andre Brilleland-slugene som har f.eks. `-30-pack2` eller
  `-6-stk-pk` bakt inn).
  Revidert ALLE 12 Brilleland scrape_targets uten pakningsstørrelse i selve
  slug-teksten (høyest risiko-mønster) ved å faktisk besøke hver side og
  lese av "X PACK"-teksten. Fant én til med samme feil: Biofinity Toric
  6-pack pekte på "iWear Oxygen Astigmatism 3 pack". Begge rettet til de
  ekte 6-pack-URL-ene (`iwear/iwear-oxygen-presbyopia-6-pack` og
  `iwear/iwear-oxygen-astigmatism-6-pack`). De resterende 10 stemte.
  **Regel fremover:** en Brilleland-slug uten eksplisitt pakningsstørrelse
  i selve teksten er IKKE til å stole på -- bekreft alltid mot faktisk
  sidetekst ("X PACK") før den brukes, ikke bare mot at siden laster.

- **Linsevæske lansert som ny produkttype (2026-08-14), fase 1 av
  tilleggsprodukt-strategien.** Egen datamodell i `solutions_meta.json`
  (repo-rot): `size_ml`/`solution_type` (multipurpose/peroxide) i stedet
  for `category_slug`/`specs` som kontaktlinser bruker. Slås sammen med
  `products_meta.json` sine produkter i `build_catalog.py` sin `main()` --
  SAMME katalog-pipeline (scraping, feed-matching, price_history) uendret,
  ingen duplisert infrastruktur. 14 produkter i første runde, alle
  verifisert manuelt (Lenson/Lensway + ExtraOptical der de har samme
  merke/størrelse -- ReNu, Opti-Free PureMoist/Express, AOSept).
  **VIKTIG arkitektur-detalj:** `generate_pages.py` sin `build()` MÅ skille
  `lens_products` (har `category_slug`) fra `solution_products` (har det
  ikke) FØR den kjører kategori-/merke-/forside-løkkene -- de leser
  `categories[p["category_slug"]]` og krasjer på et produkt uten det
  feltet. Samme grunn til at `validate_build.py` sjekker riktig
  build-mappe (`linsevaeske/` vs `kontaktlinser/`) per produkt basert på
  om `category_slug` finnes.
  Linsevæske-sider ligger på `/linsevaeske/{brand_slug}/{slug}/`, egen
  oversiktsside på `/linsevaeske/`, egen `sitemap-linsevaeske.xml`, egen
  lenke i `TOPBAR_HTML`. Peroksidbaserte produkter (AOSept, EasySept) får
  en synlig sikkerhetsboks om nøytralisering på produktsiden
  (`safety-notice`-klassen) -- IKKE fjern denne, det er en reell
  øyeskaderisiko ved feil bruk, ikke bare en juridisk formalitet.
  **Bevisst utelatt fra denne runden:** Oxysept 1-Step (solgt i "dager",
  ikke ml), Acuvue RevitaLens (solgt i "stk", ikke ml), everclear REFRESH
  x3 (multipack-bundle) -- disse trenger en annen sammenligningsenhet enn
  pris-per-100ml og er ikke med ennå. Øyedråper (prioritet 2 i strategien)
  er heller ikke bygget -- krever klassifisering medisinsk utstyr vs.
  legemiddel per produkt først (se punktet om Apotekhjem).

- **Lenson/Lensway-lenkefiks samme dag: `-lens-{id}`-slugen (brukt for
  kontaktlinser) fungerer IKKE for Tilbehør-kategorien.** Bruker oppdaget
  at linsevæske-lenkene til Lenson/Lensway ikke virket. Årsak: sidetittelen
  (server-rendret meta) og prisdataen (embedded JSON-blob) var begge
  korrekte selv med feil slug, så skrapingen "virket" og ga riktig pris --
  men selve klientside-rendringen av produktsiden kastet "Oops! Noe gikk
  galt" fordi Tilbehør-kategorien bruker et annet slug-suffiks:
  `{navn}-extra-{id}`, ikke `{navn}-lens-{id}`. Bekreftet ved å faktisk
  lese produktlisten på `/no/tilbehor` (der ekte lenker ligger, f.eks.
  `aosept-plus-extra-864`). Alle 13 Lenson/Lensway-slugs i
  `solutions_meta.json` rettet og verifisert på nytt (ingen feilside).
  **Lærdom:** for en NY produktkategori hos en forhandler holder det ikke
  å bekrefte via sidetittel/embedded-data alene -- se etter faktisk
  "Oops! Noe gikk galt"-tekst i `get_page_text`, siden serveren kan
  rendre riktig metadata selv når klientsiden feiler på selve URL-formatet.

- **Øyedråper lansert som andre tilbehørskategori (2026-08-14/15),
  autonomt arbeid mens bruker var vekk fra skjerm** (eksplisitt avtalt:
  fortsett uten å måtte godkjenne hvert steg). `render_solution_product_page`/
  `render_solution_category_page` i `render_templates.py` er nå generalisert
  til flere kategorier via `SOLUTION_CATEGORIES`-oppslaget og produktenes
  `solution_category`-felt ("linsevaeske" eller "oyedraper") -- URL-prefiks,
  tittel og intro slås opp derfra i stedet for hardkodet "linsevaeske"
  over alt. `generate_pages.py`, `generate_sitemap.py` og
  `validate_build.py` er oppdatert tilsvarende (grupperer/sjekker per
  `solution_category`, ikke lenger én fast mappe). Ny kategori senere
  (f.eks. linseetui) er bare en ny nøkkel i `SOLUTION_CATEGORIES` +
  produkter med riktig `solution_category`-verdi, ingen kodeduplisering.
  19 øyedråper lagt til, alle bekreftet ekte 10 ml flytende dråper hos
  Lenson/Lensway (samme `-extra-{id}`-slug-mønster som linsevæske, samme
  verifiseringsdisiplin -- besøkt hver side, lest av faktisk ml-tall).
  Merker: Systane (3), Hylo (7), OXYAL (3), Tearsagain (3), EYZ (2), Thealoz
  Duo, Add1 (Consol). **Bevisst utelatt:** Hylo Night og EYZ Night er
  gel/salve i gram, ikke ml-baserte dråper -- annen enhet, ikke sammenlignbar
  med resten på pris-per-100ml, ikke lagt til. Blephaclean/Blephacura/EYZ
  Clean er øyelokk-hygieneprodukter (våtservietter/rens), ikke dråper --
  utenfor scope. Apotekhjem sine øyedråper er IKKE med i det hele tatt:
  de er et ekte apotek og selger både medisinsk utstyr OG reseptfrie
  legemidler (f.eks. Livostin, Lomudal -- antihistamin) side om side, og
  krever ekte klassifisering per produkt før noe derfra kan publiseres.
  Lenson/Lensway sitt utvalg unngår dette problemet strukturelt: de er
  IKKE apotek, og etter apotekloven kan de derfor ikke selge legemidler i
  utgangspunktet -- alt i deres Tilbehør-kategori er per definisjon
  medisinsk utstyr/kosmetikk, ikke legemiddel. Denne logikken gjelder KUN
  Lenson/Lensway (og tilsvarende ikke-apotek-forhandlere) -- gjelder IKKE
  Apotekhjem eller andre apotek, der klassifisering fortsatt må gjøres
  eksplisitt per produkt.

- **Precision7 6-pack: Lenson/Lensway sitt tilbud fjernet (2026-08-15) --
  samme pakningsstørrelse-feil som Interoptik allerede var ekskludert for.**
  Oppdaget under research på private label-linser: Lensway (og dermed
  sannsynligvis Lenson, samme plattform/produkt-id 10819) selger Precision7
  KUN i 12- og 27-pakning, aldri 6-pakning -- variant-velgeren viste
  "12 stk/pk"/"27 stk/pk", ingen 6-pakning i det hele tatt. Scrape_targets
  fjernet fra både `precision7-6pk` og `precision7-astigmatism-6pk`
  (samme fix som Interoptik fikk tidligere, se lenger opp i dokumentet).
  **STATUS:** Begge produktene har nå `"scrape_targets": []` og publiseres
  UTEN priser -- ingen bekreftet norsk forhandler selger Precision7 i ekte
  6-pakning så langt vi har funnet (Interoptik: 12-pk, Lenson/Lensway:
  12/27-pk). Dette er en åpen avgjørelse for bruker: enten fortsette å lete
  etter en reell 6-pack-kilde, eller vurdere om produktet burde redefineres
  til 12-pakning for å matche hva som faktisk selges i markedet -- IKKE
  gjort ensidig her, siden det endrer produktets identitet/pris-sammenligning
  ikke bare en scrape-kilde.

- **Private label-sider lansert (2026-08-15), autonomt arbeid.** Flere
  optikerkjeder (Brilleland, Synsam, Specsavers) selger ekte kjente
  kontaktlinser under sitt eget merkenavn (f.eks. Synsam sin "EyeQ 24" er
  Biofinity fra CooperVision, bare i egen innpakning). `private_labels.json`
  (repo-rot) holder KUN høy-sikkerhet-koblinger -- 46 stk, bekreftet direkte
  mot Lensway sin egen "Optikerkjedenes varemerke"-seksjon
  (`/kontaktlinser/linseliste?p_privateBrand=...`), som eksplisitt oppgir
  hvilket produsent-navn hver private label-linse selges under (besøkt hver
  enkelt `-private-{id}`-produktside, ikke gjettet fra navnelikhet). Dekker
  29 av våre eksisterende produkter. IKKE en egen datakilde/prisinnhenting
  -- `render_private_label_page()` i `render_templates.py` gjenbruker
  `real_product` sine faktiske tilbud (samme fysiske vare, samme pris),
  bygges på `/private-label/{slug}/`. Alt innhold er egenformulert (IKKE
  kopiert fra Lensway sin tekst) -- inkluderer en tydelig fraskrivelse om
  at kontaktlinser.no ikke har noen avtale med kjedene og ikke kan
  garantere at koblingen stemmer i alle tilfeller (eksplisitt bruker-krav).
  Oversiktsside på `/private-label/`, lenket fra footeren under "Guider".
  Egen `sitemap-private-label.xml`.
  **Underveis-funn:** samme research avdekket at Precision7 (se punktet
  rett over) heller ikke fantes i 6-pakning hos Lenson/Lensway -- derfor
  ingen private label-oppføring for Precision7 i denne runden, siden vi
  ikke selv har en pålitelig 6-pack-pris å vise frem.
  **Ikke bygget ennå:** Mister Spex og Synologen (de to andre kjedene i
  filteret) hadde ingen treff i dette utvalget -- enten fører de ingen
  private label-linser, eller de var ikke representert i de 5 sidene som
  ble hentet. Flere av Brilleland/Synsam/Specsavers sine ~50 gjenstående
  private label-navn (de som ikke matcher et produkt vi allerede fører,
  f.eks. hele "iWear DD"-serien) er heller ikke undersøkt -- kun de som
  ga et umiddelbart, høy-sikkerhet-treff mot eksisterende katalog.
- **Build-timeout økt fra 10 til 20 minutter (2026-08-15):** bygget etter
  private label-commiten feilet -- ikke pga. en kode-/logikkfeil
  (`validate_build.py` og alle genereringssteg gikk gjennom fint), men
  fordi jobben traff `timeout-minutes: 10` under "Publiser til GitHub
  Pages"-steget. Katalogen har vokst mye denne økten (103 linser + 39
  linsevæske/øyedråper + 46 private label-sider), så publiseringen tar nå
  lenger tid enn det opprinnelige 10-minutters-budsjettet forutsatte.
  Merk: dette er IKKE skraping som er treg -- skraping kjører uansett kun
  på cron/manuell trigger (`if: github.event_name != 'push'`), aldri på
  vanlig push.
- **GEO/AI-søk-tiltak (2026-08-15):** brukeren limte inn tre AI-genererte
  strategidokumenter om GEO-optimalisering (teknisk SSR/JSON-LD-dokument,
  robots.txt-forslag, og et tidligere dokument som feilaktig påsto at
  "Megon AS" står bak siden -- bekreftet fabrikkert av brukeren, IKKE
  implementert). Alt ble sjekket faktisk mot koden før noe ble bygget:
  - SSR og Product/AggregateOffer JSON-LD var allerede fullt implementert
    fra før -- ingen handling nødvendig der.
  - `robots.txt` var allerede mer finmasket enn forslaget (skiller AI-søk-
    vs. AI-trenings-roboter per leverandør); eneste reelle mangel var
    `Applebot-Extended`, lagt til.
  - `llms.txt` linket til en kategori (`/kontaktlinser/torre-oyne/`) som
    ikke finnes -- fikset til de faktiske 5 kategoriene, samt lagt til
    linsevæske/øyedråper/private-label-sidene som manglet der.
  - Lagt til en tettere, siterbar AI-oppsummering i `hero-lead` på
    forsiden (bruker dynamisk `n_retailers`/`n_products`, ikke hardkodet
    forhandlerliste -- unngår at teksten blir feil når katalogen endres).
    Plassert bevisst i "lead"-grid-området, som allerede kommer ETTER
    søkefeltet i mobil-rekkefølgen (`heading` `search` `media` `credit`
    `lead`) -- søkefeltet er fortsatt det som vises tidligst på mobil.
  - Ny side-nivå FAQ-seksjon nederst på forsiden (9 spørsmål, original
    tekst, egen `FAQPage`-schema) om hvordan tjenesten fungerer generelt
    (skjulte fraktkostnader, oppdateringsfrekvens, private label, osv.)
    -- skiller seg fra de eksisterende guide-spesifikke FAQ-ene (som
    handler om linsetyper). `_render_faq_block()` er en ny delt helper
    som bygger synlig markup + schema fra samme datastruktur, brukt både
    av guide-sidene (refaktorert til å bruke den) og forsiden, slik at
    innhold og strukturert data aldri kan komme ut av synk.
  - Spørsmålet om dagslinser-vs-månedslinser i den nye FAQ-en unngår
    bevisst dokumentets ferdigskrevne påstand ("månedslinser nesten alltid
    billigst") -- det er en uverifisert generalisering. Lenker i stedet
    til den eksisterende guiden med et mer presist, allerede verifisert
    svar (terskel på 4-5 dager/uke).
- **Titler, synlig AI-oppsummeringsboks og bilde-schema (2026-08-15):**
  brukeren limte inn en serie AI-genererte tittel-/meta-maler fra et
  eksternt verktøy, dryppvis over flere meldinger -- evaluert samlet mot
  faktisk kode, ikke implementert blindt:
  - **Kapitalisering i `<title>`:** ordet rett etter en "–" var
    inkonsekvent små forbokstaver ("billigste pris", "sammenlign priser",
    "hva heter den egentlig?") på tvers av produkt-, merke-, kategori-,
    forside- og private label-sider. Fikset til stor forbokstav overalt
    ("Billigste pris", "Sammenlign priser", "Hva heter den egentlig?").
    IKKE endret der ordet etter "–" er selve merkenavnet
    "kontaktlinser.no" (Guider/Om oss/404/Personvern-titlene) -- det er
    en bevisst, konsekvent brukt små bokstaver-stil brukt over 200+
    steder på siden (forsidetittel, brødtekst, footer, llms.txt), og
    Google har uansett ingen `og:site_name`/`WebSite`-schema å styres av
    her -- det viste lille "kontaktlinser.no" øverst i Google-treff er
    trolig hentet rett fra domenet, ikke fra title-taggen. Anbefaling:
    IKKE endre denne -- brukeren informert, ikke gjort uten videre.
  - **Produktside-tittel:** vurderte å bake inn live laveste-pris i
    `<title>` (som i AI-verktøyets forslag), men avvist -- produktnavn
    varierer sterkt i lengde ("MyDay 30-pack" vs. "Dailies Total1 for
    Astigmatism 90-pack"), og å legge til "fra XXXX kr" i tillegg ville
    presset mange titler godt forbi Googles ca. 60-tegns visningsgrense,
    slik at "| kontaktlinser.no"-halen uansett kuttes bort. Prisen vises
    i stedet i den nye synlige AI-boksen under (se neste punkt), som
    ikke har samme lengdebegrensning.
  - **Ny synlig AI-oppsummeringsboks** (`.product-ai-summary`) rett
    under H1 på både vanlige produktsider og linsevæske/øyedråper-sider:
    dynamisk setning med faktisk antall forhandlere for akkurat DETTE
    produktet (`len(product["offers"])`) og faktisk laveste pris/
    forhandler -- IKKE "alle store norske nettbutikker" slik AI-
    forslaget hardkodet (brukeren selv bekreftet at vi ikke har alle).
    Egen fallback-variant (grå i stedet for blå) når produktet ikke har
    noen bekreftet pris (f.eks. Precision7 6-pack) -- ordlyden unngår
    bevisst AI-forslagets antakelse om at dette alltid betyr
    "midlertidig utsolgt", siden det hos oss ofte heller betyr at ingen
    av forhandlerne vi følger har denne pakningsstørrelsen i det hele
    tatt (strukturelt, ikke midlertidig).
  - **`image`-felt lagt til i `Product`-JSON-LD-schemaen** på begge
    produktsidetyper -- `image_url` ble allerede regnet ut for hero-
    bildet, men ble aldri sendt med i strukturert data. Reelt funn (ikke
    fra AI-dokumentene), relevant for Google Bilder/Lens-søk.
  - **Merkeside-meta-beskrivelse** nevner nå faktiske produktnavn (de 2-3
    billigste for merket, hentet fra samme sorterte liste som allerede
    rendres på siden) i stedet for generisk "alle X vi følger"-tekst --
    fortsatt ingen overclaims, siden navnene faktisk finnes på siden.
  - Droppet AI-forslagets "Kjøp {{ product.name }} billig"-tittelramme
    (antyder direktekjøp) til fordel for "Billigste pris"/"Se priser"-
    rammingen brukeren selv landet på -- konsistent med at vi eksplisitt
    ikke selger noe selv.
- **Private label-produkter nå søkbare fra forsiden + mindre tekst før
  pris (2026-08-15):** brukeren rapporterte at private label-sidene
  (`/private-label/{slug}/`, 46 stk) ikke dukket opp i søket på forsiden,
  og at det var for mye forklaringstekst før selve prissammenligningen
  på mobil.
  - **Søk:** Forsidens søkefelt søkte kun i `catalog["products"]`
    (ekte katalogprodukter) -- private label-navn fantes ingen steder i
    søkeindeksen. Fikset ved å legge et skjult (`hidden`-attributt,
    fungerer uten CSS) `#private-label-search-data`-element på
    forsiden med alle 46 navnene, og utvide søkeforslag-logikken
    (`renderSuggestions()`) til å søke i BÅDE ekte produktkort OG disse.
    Bevisst KUN i forslagsboksen (dropdown mens man skriver), IKKE i
    "Alle linser"-rutenettet -- å vise 46 private label-kort blandet
    inn blant de ekte produktene der ville dupli­sert/forvirret, siden
    de peker til nøyaktig samme fysiske vare som allerede vises under
    sitt ekte navn. `render_home_page()` tar nå en `private_labels`-
    parameter; `generate_pages.py` laster `private_labels.json` én gang
    tidligere i `build()` og gjenbruker den (fjernet dobbel innlesing).
  - **Rekkefølge på private label-sidene:** flyttet prissammenligningen
    (`best_band` + tilbudslisten) opp til rett under H1 -- de to
    forklarings-/advarselsboksene ("hvorfor har den to navn?" og
    fraskrivelsen) kommer nå ETTER prisen, ikke før. Samme prinsipp som
    "søkefeltet skal være først synlig" fra tidligere denne økten:
    hovedfunksjonen (sammenligne pris) skal ikke kreve at brukeren
    scroller forbi flere avsnitt tekst på mobil først. All tekst er
    fortsatt der, uendret, bare i en bedre rekkefølge.

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
