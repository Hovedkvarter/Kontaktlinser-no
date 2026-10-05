# kontaktlinser.no — prosjektbrief

Prissammenligningsside for kontaktlinser i Norge. Solo-drevet av eier, som
koder/designer selv med AI-hjelp. Dette dokumentet er kontekst for Claude Code
(eller enhver AI-assistent) som jobber i dette repoet — les det før du gjør
endringer.

## Hva siden gjør

Sammenligner priser på kontaktlinser fra norske nettbutikker (Interoptik,
Lensway, Lenson, Specsavers, flere kommer) og viser billigste tilgjengelige
tilbud per produkt, på én dedikert side per produkt. Live på kontaktlinser.no,
hostet på GitHub Pages, bygget automatisk daglig (og ved hver push) via GitHub Actions.

## Designsystem (fast — følg dette uten å spørre)

- Farger: ink navy `#0B2545` (tekst), mist white `#F5F9FA` (bakgrunn), blue
  `#2563EB` (merkevare-aksent, byttet fra aqua `#2EC4D6` 2026-08-19 etter
  brukerens eksplisitte ønske/mockup — CSS-variabelen heter nå `--blue`/
  `--blue-tint`/`--blue-dark`, IKKE `--aqua`), mint `#0BA36F` — reservert KUN
  for "laveste pris"-markering. Grønt betyr alltid besparelse, ingenting
  annet. Flagg det eksplisitt hvis en endring ville brutt denne regelen.
  Kategori-ikonene på forsiden har hver sin egen aksentfarge fra den
  etablerte paletten (blue/amber/sky/lavender/coral, se `CATEGORY_COLORS`)
  — bevisst ALDRI grønt/mint der, av samme grunn.
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
8. `.github/workflows/build-and-deploy.yml` — kjører 1–7 daglig (kl. 22:45 UTC) og ved hver push,
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
  **Status 2026-09-05:** brukeren har søkt om affiliate-program for
  smartbuyglasses.no via CJ (Commission Junction) -- fikk først avslag, har
  tatt kontakt og søkt på nytt, svar avventes. Legg til som `affiliate_feed`
  i `sources_config.json`/`product_matching.json` den dagen en avtale
  faktisk er godkjent -- ikke før.
- **Lensit-avtale undersøkt og forkastet 2026-09-05:** brukeren fant at
  Lensit (lensit.no) har hatt et Tradedoubler-partnerprogram tidligere
  (død `/pages/tradedoubler`-landingsside fra 2020, personvernerklæringen
  deres nevner fortsatt "d) Affiliates. Vi samarbeider med tradedoubler"),
  men alle gamle Tradedoubler-lenker til Lensit man finner på nettet er nå
  bekreftet ikke-fungerende -- programmet er reelt inaktivt. Lensit svarer
  heller ikke på henvendelser. **Beslutning: Lensit beholdes likevel som
  skrapet (ikke-avtale) kilde** -- dropper man dem for å "stoppe lekkasjen"
  av gratis trafikk til en billig, ikke-monetisert forhandler, bryter man
  sidens eget publiserte løfte om at rangeringen aldri påvirkes av
  provisjon (se disclosure-teksten / Forbrukertilsynet-veiledningen lenger
  opp i dette dokumentet) -- og Lensit bidrar uansett reell bredde/
  troverdighet til sammenligningen. Konkret kontaktinfo funnet om noen vil
  prøve igjen senere: kundeservice@lensit.no, tlf. 788 96 888 (man–tor
  09–15, fre 09–14), org.nr 960 985 532 (Lensit.no AS). Brønnøysund-sjekk
  samme dag: ny styreleder registrert april 2026 (Tim Gerlach), tidligere
  daglig leder (Carl Erik Pontus Lindbom) avregistrert uten erstatning --
  tyder på et ferskt eier-/ledelsesskifte, ikke bekreftet hvem som faktisk
  eier selskapet nå (aksjonærregisteret er ikke sjekket). Brukeren har
  sendt 2 henvendelser til Lensit uten svar per 2026-09-05, prøver igjen
  senere. **Ikke avgjort, men vurderes:** fjerne Lensit helt og erstatte
  med en annen forhandler hvis kontaktforsøkene fortsetter å være
  resultatløse over tid -- ingen tidsfrist satt ennå.
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
    steder på siden (forsidetittel, brødtekst, footer, llms.txt).
    **Rettelse 2026-08-28:** denne notisen var feil -- siden har faktisk
    `og:site_name` (riktig "Kontaktlinser.no") og et `WebSite`-JSON-LD-
    schema med samme navn, begge på plass allerede (se `_og_meta()` og
    `FONT_LINKS` i `render_templates.py`). At Google likevel viser lille
    "kontaktlinser.no" i SERP skyldes trolig bare indekserings-/cache-
    forsinkelse (samme kategori forsinkelse som prisvisningen i søketreff,
    se punktet om AI-oppsummeringen lenger ned) -- Google følger uansett
    ikke `og:site_name` slavisk, det er ett av flere signaler. Ingen
    kodeendring nødvendig, bare tid.
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
- **Private label-data re-verifisert + kjedene lagt til under "Merker"
  (2026-08-15):** brukeren ba om en uavhengig dobbeltsjekk av alle 46
  private label-koblingene. Kjørt via en agent som spurte Lensway sitt
  eget backend-API (`viewproductpageinfo/lens/{id}`, samme endepunkt
  siden bruker til å rendre "selges også som"-info på deres egne
  produktsider) for alle 46, i stedet for å tolke rendret HTML.
  **43 bekreftet korrekte, 3 feil funnet og rettet:** `iwear-oxygen-xr`,
  `eyeq-24-xr` og `easyvision-opteyes-xr` pekte til `biofinity-xr-6pk`,
  men Lensway sin egen pakningsdata for samme produkt-id (4244) viser at
  det kun finnes som 3-pack -- samme kjente id-4244-forveksling som
  allerede var dokumentert for Lenson/Lensway sine scrape_targets (se
  Precision7-punktet lenger opp), bare ikke fanget opp da private
  label-listen ble bygget. Rettet til `biofinity-xr-3pk` i
  `private_labels.json`, som er en egen, reell produktoppføring (egen
  `slug`, egen beskrivelse) -- bekreftet selv før endring, ikke bare
  tatt agentens ord for det.
  Lagt til Brilleland/Synsam/Specsavers som egne kort i "Merker"-
  seksjonen på forsiden (samme `.brand-card`-stil), tekstet "X egne
  merker" i stedet for "X produkter" for å skille dem fra ekte
  linseprodusenter uten å trenge egen CSS-badge. Lenker til
  `/private-label/#{kjede}` -- lagt til ankere (`id="brilleland"` osv.)
  på oversiktssidens kjede-overskrifter for dette.
  **Oppdatert samme dag:** brukeren ville heller ha selve serienavnet
  (iWear/EyeQ/Easyvision) som hovedtekst på kortet, ikke kjedenavnet, og
  gjerne med logo. Sjekket brilleland.no/kontaktlinser/iwear direkte --
  ingen egen iWear-logofil finnes der, kun produktbilder av emballasjen
  (samme situasjon som allerede dokumentert for flere BRAND_LOGOS-
  produsenter uten egen ordmerke-logo). Løsning: `PRIVATE_LABEL_SUBBRANDS`
  (nytt dict, Brilleland->iWear, Synsam->EyeQ, Specsavers->Easyvision)
  gir hovedteksten, mens badge-sirkelen gjenbruker kjedens EGEN logo
  (fra `RETAILER_LOGOS`, som vi allerede har og bruker andre steder) --
  nærmeste reelle, lovlige visuelle merke siden serien selv ikke har en.
  Kjedenavnet står fortsatt som undertekst ("Brilleland · 15 egne
  merker") slik at koblingen til kjeden ikke går tapt.
- **Egne merke-sider for private label-seriene (2026-08-15):** brukeren
  ville at iWear/EyeQ/Easyvision skulle ha egen dedikert side som ekte
  merker (`/merke/dailies/`-mønsteret), ikke bare leve som en seksjon på
  `/private-label/`. Ny `render_private_label_brand_page()` i
  `render_templates.py`, bygger `/merke/{iwear|eyeq|easyvision}/` --
  samme kortstil/kategorifilter-JS som `render_brand_page()`, men
  produktkortene lenker til `/private-label/{slug}/` (ikke direkte til
  det ekte produktet), siden den siden allerede har full prissammenligning
  + fraskrivelse. Har original forklaringstekst om hva serien er (unngår
  bevisst å navngi spesifikke produsenter siden produsent-miksen varierer
  per kjede -- t.d. iWear er nesten utelukkende CooperVision, mens EyeQ
  blander CooperVision og Alcon -- en generisk "en av de store
  produsentene"-formulering er trygg for alle tre uten å måtte
  produsent-spesifikke fakta-sjekkes per kjede). `/merke/`-kortene på
  forsiden peker nå hit i stedet for til `/private-label/#{kjede}`, og
  `/private-label/`-oversikten lenker tilbake til den nye siden fra hver
  kjede-overskrift. Lagt til i sitemap via `site_content.json`sin
  `brands`-liste (gjenbruker eksisterende `/merke/{slug}/`-sitemap-URL,
  ingen egen sitemap-fil trengtes). `generate_pages.py` bygger disse
  rett etter de vanlige private label-sidene.
- **"Topp 6 merker"-dokument avvist, redaksjonell rekkefølge valgt i
  stedet (2026-08-15):** brukeren la inn nok et AI-generert dokument
  med kilder ("Topp 6 kontaktlinsemerker i Norge"). Sjekket hver kilde
  direkte i stedet for å stole på oppsummeringen: Specsavers' 38-40 %
  markedsandel stemte (bekreftet i retailmagasinet.no-artikkelen), men
  det er total optikermarkedsandel, ikke bevis for at easyvision er mest
  brukte LINSEmerke -- et logisk hopp dokumentet selv gjør. Påstanden om
  at iWear er et fellesmerke for Brilleland OG Interoptik/Synoptik er
  usann -- kilden (interoptik.no/om-oss) nevner verken iWear eller
  GrandVision, og vår egen re-verifiserte private_labels.json-data viser
  at samtlige 15 iWear-produkter er utelukkende Brilleland. EyeQ-kilden
  (optikerbransjen.no) var en død lenke (404). Fant i stedet en reell,
  uavhengig norsk kilde (prisradar.no sin klikkbaserte "mest populære"-
  rangering) som direkte MOTSIER dokumentets rangering -- ingen private
  label-navn i det hele tatt i deres topp 7, ekte merkenavn dominerer.
  Prøvde også Google Trends (Norge-filtrert søkeinteresse) for et rent
  datagrunnlag, men ble konsekvent 429-blokkert (flere forsøk, aldri
  fikk lastet faktiske tall) -- forkastet som metode, ikke presset videre.
  **Endelig løsning:** ikke en popularitetspåstand, men et eksplisitt
  redaksjonelt valg fra brukeren -- de tre nye private label-seriene
  (iWear/EyeQ/Easyvision) først i Merker-seksjonen, deretter Acuvue,
  Dailies og Biofinity (brukeren bekreftet disse tre spesifikt, ikke
  Air Optix, da dokumentets "Dailies & Air Optix" var ett felles punkt
  i originalen men er to separate merker i vår katalog). Resten av
  merkene følger i uendret rekkefølge (etter antall produkter). Se
  `PINNED_BRAND_SLUGS` i `render_home_page()`.
- **Desktop-breddeoppgradering, nytt 1024px-breakpoint (2026-08-15):**
  brukeren observerte at siden var bygget for gamle skjermbredder (faktisk
  `max-width: 760px` på ALLE sider -- enda smalere enn brukeren selv
  anslo). Diskutert flere layoutmodeller (sidebar-filtrering, dashboard-
  grid, sentrert fokusert produktside) før noe ble bygget -- landet på en
  moderat, inkrementell løsning fremfor en full omlegging:
  - To nye containerklasser i `SHARED_STYLE`, aktive kun ved
    `min-width: 1024px`: `.wrap-wide` (1200px, for forside/kategori/
    merke-/private label-oversikter) og `.wrap-product` (1040px, for
    produkt-/pristabellsider). Tekstsider (guider, om oss, personvern,
    404) er BEVISST uendret på 760px -- ingen grunn til brede
    leselinjer der.
    **NB:** ikke bare bredere -- kolonneantallet i `.lens-grid`
    (2->3), `.brand-grid` (3->4) og `.category-grid` (3->5) økes ved
    samme breakpoint, ellers ville kortene bare blitt unaturlig
    strukket ut med tomrom inni seg i stedet for flere kort per rad.
    `.topbar`/`.footer-inner`/`.footer-disclosure`/`.footer-bottom`
    (delt på alle sider) widened til 1200px samtidig, for visuell
    konsistens med innholdet under -- selv på tekstsider, siden en
    boksete topbar over et bredt forside ville sett rart ut.
  - `.hero-product-image` (produktside-bildet) økt fra 240px til 340px
    ved 1024px.
  - Mobil er UENDRET -- alle disse reglene er strengt inni
    `@media (min-width: 1024px)`, ingen av de eksisterende mobil-
    breakpointene (560/640/700px) er rørt. Brukeren var eksplisitt på
    at mobil/brukervennlighet er viktigst -- denne endringen legger kun
    TIL et nytt lag for store skjermer.
- **Forsidens hero-gap fikset + søkefelt mer fremtredende + "Kontaktlinser.no"
  kapitalisert i løpende tekst (2026-08-15):** brukeren viste et skjermbilde
  fra PC av forsiden -- pekte på et stort tomrom mellom H1 og hero-lead-
  avsnittet. Undersøkte og fant rotårsaken: `.hero`s grid-template-areas
  ved >=700px var `"heading media" "lead media" "credit credit" "search
  search"` -- heading og lead delte rader med det høye hero-bildet
  (`media` spenner over to rader via samme navn i begge), så heading sin
  rad ble auto-strukket til bildets høyde, med tomrom under. **Verre:**
  søkefeltet lå i en HELT EGEN rad nederst, under selve bildet -- usynlig
  i det synlige området på PC. Dette var trolig hele årsaken til at
  brukeren samtidig spurte om søkefeltet kunne vært mer fremtredende.
  Fikset ved å pakke heading+search+lead inn i en ny `.hero-content`
  wrapper (flex-column) som er ÉN grid-item (area "content", spenner
  begge rader ved siden av bildet) -- unngår rad-delingen som skapte
  tomrommet, og holder søket rett under H1 på alle skjermstørrelser, ikke
  bare mobil. La også til et forstørrelsesglass-ikon i søkefeltet, en
  aqua-glød på fokus (`box-shadow` + `--aqua-tint`), og litt større
  padding/skrift ved >=1024px.
  I samme melding pekte brukeren (for andre gang) på at "kontaktlinser.no"
  med liten k så rart ut -- denne gangen i selve brødteksten på siden
  ("kontaktlinser.no er en uavhengig..."), ikke bare i Googles SERP-
  visning som sist (der jeg anbefalte å la det være). Dette er en annen,
  mer berettiget sak: som første ord i en SETNING bør det ha stor
  forbokstav uansett merkevare-stil. Kapitalisert til "Kontaktlinser.no"
  alle steder det står setningsinnledende (footer, hero-lead, FAQ-svar,
  disclosure-avsnitt på produkt-/kategori-/private label-sider, llms.txt)
  -- IKKE endret midt i setning (f.eks. "Nei, kontaktlinser.no er
  verken..." i én FAQ-post) eller i URL-er/e-post/domenenavn-referanser.
- **"Se alle merker"-knappen byttet ut med kategori-piller (2026-08-15):**
  brukeren påpekte at knappen (lenket til `#merker`, seksjonen rett
  under) var overflødig -- den "scroller bare litt til". Byttet ut med
  fem kategori-snarveier (Dagslinser/Månedslinser/Toriske linser/
  Fargede linser/Multifokale linser) som piller med ikon, siden det gir
  en reelt ANNEN inngang enn søkefeltet (søk = "jeg vet navnet", piller
  = "jeg vet ikke navnet, men vet linsetypen") -- kategoriene lå
  tidligere lenger ned på siden, så dette gjør dem faktisk mer synlige,
  i motsetning til den gamle knappen som pekte på noe som uansett var
  synlig. Gjenbruker samme `category_icons`-SVG-set som allerede brukes
  i Kategorier-seksjonen (visuell konsistens, ingen nytt ikonsett).
  Egen `.hero-pill`-stil (hvit bunn, aqua-kant + tint på hover, samme
  `--card-shadow` som resten av kortene) -- ikke gjenbruk av den
  eksisterende `.chip`-stilen (brukt til filter-knapper på merke-/
  kategorisider), siden piller i heroen er lenker til nye sider, ikke
  et filter-UI, og fortjener litt mer "hero-verdig" polish. Fjernet
  `.hero-actions`/`.btn-primary` CSS som ble død kode etter dette.
- **Fjernet "Alle linser"-gridden fra forsiden, søk kjører nå mot skjult
  JSON i stedet for synlige kort (2026-08-15):** brukeren spurte om det
  var en fordel å liste alle 103 produktene på forsiden -- svarte at det
  ga bedre crawl-dekning, men kostet topisk SEO-fokus (forsiden
  konkurrerer med egne kategori-/merkesider om de samme søkene,
  "keyword cannibalization") og skalerer dårlig etter hvert som
  katalogen vokser. Brukeren presiserte at SEO/AI-treff er høyeste
  prioritet, og ba meg sette i gang.
  - Fjernet `<h2>Alle linser</h2>` + `#lens-grid` + `#no-results` helt
    fra forsiden. Indeksering er ikke svekket -- `sitemap-produkter.xml`
    lister allerede alle produkter uavhengig av forside-lenker, og
    kategori-/merkesidene gir topisk relevante interne lenker dit
    (bedre for AI-sitering også: strukturerte engines foretrekker sider
    med ett klart formål, ikke en forside som prøver å være alt).
  - Søkeforslag-dropdownen (autocomplete under søkefeltet) beholdt
    UENDRET brukeropplevelse, men datakilden byttet fra synlige
    `.product-card`-elementer (klonet fra DOM-en) til to skjulte
    `<script type="application/json">`-øyer (`#product-search-data`,
    `#private-label-search-data`) -- `build_search_entry()`/
    `build_private_label_search_entry()` i `render_home_page()` bygger
    disse. JSON escapes `</` -> `<\/` for å unngå at et produktnavn med
    den sekvensen kunne brutt ut av script-taggen (usannsynlig, men
    billig å beskytte mot). Reduserer forsidens DOM/HTML-vekt betydelig
    siden 103 fulle produktkort (bilde+navn+merke+pris+lenke hver) ikke
    lenger rendres, bare en kompakt JSON-liste (navn+merke+bilde+lenke).
  - Rettet en bieffekt: hero-lead-teksten sa "søk eller velg en linse
    under" -- ga ikke lenger mening uten linse-gridden. Endret til
    "søk, eller velg en kategori under" (kategori-pillene fra forrige
    endring dekker nå den funksjonen).

## To nye forhandlere: Coptikk og Krogh Optikk (2026-08-16)

Brukeren spurte om vi hadde sjekket lovligheten av å skrape flere navngitte
forhandlere. Synsam/Interoptik/Brilleland var allerede integrert -- **viktig
korreksjon underveis: Specsavers er IKKE faktisk skrapet**, til tross for at
den nevnes i UI-tekst andre steder -- `sources_config.json` har den satt til
"scraper", men den er reelt BLOKKERT av en Cloudflare-utfordring (se egen
`$comment` der). Private label-sidene for Specsavers (Easyvision) fungerer
likevel, siden de gjenbruker priser fra ANDRE forhandlere av samme fysiske
produkt, ikke fra Specsavers selv.

**Krogh Optikk**: robots.txt blokkerer kun `/craft/` (admin), ingen
anti-skraping-klausul i kjøpsbetingelsene. Server-rendrer prisen direkte i
HTML (`class="price-tag"`) -- standard CSS-selector-oppsett, samme mønster
som Interoptik/Brilleland. 39 av 103 produkter matchet og lagt til i
`products_meta.json` (`retailer: "kroghoptikk"`).

**Coptikk**: robots.txt tomt, ingen anti-skraping-klausul. Første forsøk
brukte et JSON-API-endepunkt (`/api/product/getproductitem?articleNumber=`)
som fungerte i én naturlig nettleser-sidelast, men ga KONSEKVENT 500-feil
ved isolerte kall (testet flere ganger, også etter ventetid -- ikke
rate-limiting). Siden produksjonsskraperen gjør akkurat den typen isolerte
`requests.get()`-kall, ble denne tilnærmingen forkastet FØR noe ble lagt til
i `products_meta.json` -- ingenting upålitelig ble sendt til produksjon.
Pivotert i stedet til en ny, verifisert stabil metode: kategori-LISTE-sidene
(f.eks. `/linsebutikk/manedslinser`) ER fullt server-rendret med schema.org
Product/Offer-mikrodata (pris, lagerstatus, URL) per produkt i listen. Ny
`price_source: "listing_page"` i `scraper.py` henter listesiden i stedet for
produktsiden, og matcher riktig produkt på dets egen URL-sti (aldri på
posisjon/rekkefølge i listen) -- se `_find_offer_in_listing_page()`. slug i
scrape_targets for Coptikk er derfor produktets EGEN fulle URL-sti, ikke et
artikkelnummer. **Kjent begrensning:** listesidene er paginert (flere sider
per kategori) -- scraperen henter kun side 1, så et produkt som havner på
side 2/3 gir en trygg "ingen data funnet"-feil (ikke en feil pris), men
ingen tilbud vises for det produktet. Ikke undersøkt hvor mange av de 34
matchede produktene dette faktisk rammer -- følg med i byggeloggen.
34 av 103 produkter matchet og lagt til (`retailer: "coptikk"`).

Begge forhandlernes matching ble gjort av en agent som krysset hele
produktsortimentet mot vår katalog (kun høy-sikkerhet-treff på merke OG
pakningsstørrelse) -- flere tvilstilfeller ble bevisst hoppet over i stedet
for gjettet, bl.a. Coptikks Biofinity Multifocal "D" (avstandssyn) vs. "N"
(nærsyn)-todeling som ikke finnes i vår katalog, og et Krogh Optikk-produkt
der listesidens navn ("...for Astigmatism") ikke stemte med selve
produktsidens egen tittel ("Air Optix Aqua", et annet produkt) -- ekskludert
som en reell uoverensstemmelse, ikke et falskt positivt treff.

**Viktig lærdom om JSON-redigering i stor skala:** Et første forsøk på å
legge til 39 nye scrape_targets brukte PowerShell sin
`ConvertFrom-Json | ... | ConvertTo-Json`-rundtur -- dette KORRUMPERTE alle
norske tegn i hele filen til mojibake ("Ã¸" i stedet for "ø" osv.), trolig
fordi `Get-Content -Raw` uten eksplisitt `-Encoding utf8` på LESE-siden
tolket filen feil, uavhengig av at skrive-siden hadde riktig encoding.
Diffen var også 9000+ linjer (hele filen omformatert) i stedet for de
faktiske ~150 linjene som endret seg -- et tydelig varseltegn i seg selv.
Reverte umiddelbart (filen var ikke committet ennå) og brukte i stedet et
target `awk`-script som kun setter inn tekst på nøyaktig riktig sted, uten å
parse/reserialisere hele JSON-strukturen -- verifisert med eksakt
tegn-telling av æøå før/etter (skal være uendret) og en påfølgende
PowerShell `ConvertFrom-Json`-parse (kun for VALIDERING, ikke omskriving)
før filen ble tatt i bruk. Fant også at fila har BLANDET formattering
(noen scrape_targets-oppføringer er kompakte enlinjers-objekter, andre er
utfoldet over tre linjer) fra tidligere økter -- scriptet måtte håndtere
begge for å sette komma riktig.

## Fiks: ugyldig Product-strukturert-data (2026-08-16)

Google Search Console meldte en kritisk feil ("«offers», «review» eller
«aggregateRating» må angis") på 38 sider, oppdaget av brukeren via et
skjermbilde. To separate bugs i `render_templates.py`:

1. **Private label-sidene** (`render_private_label_page()`) markerte
   `"about"` som `@type: Product` uten NOEN av de tre feltene i det hele
   tatt -- siden viste allerede ekte tilbudsdata for det virkelige
   produktet (`offer_cards_html`), men denne dataen var aldri lagt inn i
   JSON-LD-en. Fikset ved å gjenbruke samme utregnede `offers`-liste og
   legge en ekte `AggregateOffer` inn i `about`. Hvis det virkelige
   produktet en dag skulle ha null tilbud, faller `about`-typen tilbake
   til `Thing` i stedet for `Product` (unngår samme fallgruve som pkt. 2
   under) -- ikke observert i praksis ennå, siden ingen private label pr.
   nå peker til et nulltilbud-produkt.
2. **To Precision7-produkter uten reelle tilbud**
   (`precision7-6pk`, `precision7-astigmatism-6pk`) fikk en ugyldig
   `AggregateOffer` med `lowPrice`/`highPrice`/`offerCount` = 0 og tom
   `offers: []`. Google teller ikke det som "angitt". **Viktig:** å bare
   fjerne selve `offers`-nøkkelen er IKKE nok -- Product-typen krever
   fortsatt minst ett av `offers`/`review`/`aggregateRating`, og vi har
   ingen anmeldelser/rating å falle tilbake på. Riktig fiks er derfor å
   utelate HELE `<script type="application/ld+json">`-blokken for
   produkter uten reelle tilbud (`schema_json_html`-variabelen i
   `render_product_page()` og `render_solution_product_page()`).

Verifisert lokalt før push: kun de 2 forventede produktsidene mangler nå
JSON-LD, og alle 47 private label-sider har gyldig `offers`. Referanse:
Googles egen dokumentasjon bekrefter regelen eksplisitt --
https://developers.google.com/search/docs/appearance/structured-data/product-snippet
("You only need to provide one of review, aggregateRating, and offers").

## Domenehistorikk og gjenoppretting av gammel SEO-verdi (2026-08-16)

Brukeren husket at kontaktlinser.no "traff godt på SEO" for flere år siden. Undersøkt
via Wayback Machine (web.archive.org): domenet er IKKE nytt i Googles øyne -- det var en
aktiv, live prissammenligningsside for kontaktlinser siden minst **2010**, under samme
konsept ("Norges største prissammenligningsside for kontaktlinser"), og ble crawlet med
normal 200-status helt til **februar 2026** (enkeltsider) / **april 2025**
(forsiden/301-kjeden). Den nye statiske siden (dette repoet) har sin første commit
**2026-08-10** -- byttet skjedde altså bare noen dager/uker før denne oppdagelsen, ikke
år tidligere. Det betyr Google har hatt svært lite tid til å "glemme" de gamle URL-ene,
noe som gjør gjenoppretting av gammel søkekraft mer lovende enn normalt for en
sidemigrering.

**DNS-sjekk utført** (`nslookup` direkte mot domenet): ingen Cloudflare foran i dag --
navnetjenere er `ns1/ns2/ns3.hyp.net` (Domeneshop), DNS peker rett på GitHub Pages sine
IP-er. Domenet har AKTIV e-post: MX → `mx.domeneshop.no`, SPF
(`v=spf1 include:_spf.domeneshop.no ~all`), DMARC (`p=quarantine`,
`rua=mailto:dmarc@domeneshop.no`). Bruker `*@kontaktlinser.no` som videresender til en
annen adresse -- videresendingen er en tjeneste hos Domeneshop knyttet til MX-oppføringen,
IKKE til hvem som er navnetjener, så den skal fortsette å fungere uendret så lenge
MX/SPF/DMARC kopieres korrekt inn i Cloudflare ved en eventuell fremtidig DNS-flytting.

**Plan for ekte 301-er (Cloudflare) -- IKKE utført ennå, avventer bevisst brukerens
navnetjener-bytte hos Domeneshop:** GitHub Pages kan ikke servere `.aspx` som en
fungerende redirect (se eksisterende `LEGACY_REDIRECTS`-kommentar i
`render_templates.py`) -- eneste vei til ekte server-side 301 er å legge domenet bak
Cloudflare (gratis nivå, proxy-modus, SSL-modus MÅ settes til "Full" ikke "Flexible" for
å unngå en redirect-løkke mot GitHub Pages) og bruke Bulk/Redirect Rules der. Full
kartlegging av gamle→nye URL-er er allerede bygget (se under) og kan gjenbrukes direkte
når DNS-byttet skjer.

**Umiddelbar, risikofri delvis-fiks levert i dag:** en systematisk gjennomgang av
Wayback Machine sitt CDX-arkiv for hele det gamle domenet ga 239 unike gamle
innholds-URL-er (ekskl. bilder/CSS/ASP.NET-systemfiler/CMS-admin), kryssjekket
programmatisk mot dagens katalog/merker/private-label/guider -- se metodikk og bevisste
skjønnsvurderinger (pakningsstørrelse-standardvalg, PureVision2-HD-forvirringen,
Biofinity XR-id-4244-saken, m.m.) i agent-loggen. Dette utvidet den allerede
eksisterende `LEGACY_REDIRECTS`-ordboken i `render_templates.py` fra 10 til 237
oppføringer -- fortsatt kun en klientsidevis JS-omdirigering fra 404-siden (siden ekte
301 krever Cloudflare), men en STRIKT forbedring uten noen DNS-risiko: reelle besøkende
og crawlere som følger gamle lenker havner nå på riktig side i stedet for en blindvei,
for 237 av 239 kartlagte URL-er (1 ekskludert med vilje -- gammelt partner-innloggingspanel
uten offentlig innholdsverdi, bedre som ekte 404).

**Nye guide-sider bygget fra gammelt "Spørsmål og svar"/"Infosider"-innhold
(2026-08-16):** brukeren pekte på at nettopp denne seksjonen historisk traff godt på
SEO. I stedet for å la disse gamle URL-ene falle tilbake til en generisk guide-oversikt,
er det bygget 11 nye, egenskrevne (ikke kopierte) guide-sider i `GUIDE_CONTENT`:
`kontaktlinser-for-barn`, `harde-eller-myke-linser`, `hvordan-bruke-kontaktlinser`,
`hvorfor-bruke-kontaktlinser`, `vedlikehold-av-kontaktlinser`,
`reising-med-kontaktlinser`, `kosmetiske-kontaktlinser`, `kontaktlinsens-materiale`,
`korrigerende-kontaktlinser`, `produksjon-av-kontaktlinser`, `kontaktlinsens-historie`,
`terapeutiske-kontaktlinser`. Innholdet holder seg til godt etablerte, generelle fakta
(bl.a. Wichterle 1961, CE-merking, "topping off"-advarsel) og henviser konsekvent til
optiker/øyelege for alt individuelt -- ingen spesifikke medisinske råd. Hver guide er
koblet inn i minst én kategoris `guides`-liste i `products_meta.json` (ellers bygges den
ikke -- se `guide_slugs`-logikken i `generate_pages.py`). `LEGACY_REDIRECTS`-oppføringene
for disse emnene peker nå til de nye dedikerte sidene i stedet for `/guider/`-oversikten.

## Utvidet guide-bibliotek (2026-08-16, samme dag som resten av SEO-runden over)

Etter de 12 første nye guidene ba brukeren om enda flere, med tre påfølgende pastede
AI-genererte spørsmålslister (34, 25 og 100 spørsmål — betydelig overlapp seg imellom og
med allerede bygget innhold). Endte med å bygge **9 til** (totalt 23 guider):
Toriske linser og astigmatisme, Multifokale kontaktlinser ved alderssyn, Kan man sove med
kontaktlinser?, Kan man dusje/bade/svømme med kontaktlinser?, Kontaktlinser og tørre øyne,
BC og DIA forklart, Hvor lenge kan man bruke kontaktlinser om dagen?, SPH/CYL/AXIS
forklart, Samme styrke på briller som linser?

**Bevisst IKKE bygget** (satt på vent, ikke avvist): resten av de tre listene. Mange
elementer er allerede dekket av eksisterende funksjoner, ikke bare innhold —
"hvilke linser er egentlig samme linse med forskjellig navn" er allerede løst av
`/private-label/`-seksjonen, "hvor er linsene mine billigst" er selve kjernefunksjonen.
En bruker foreslo også en tre-lags struktur (store guider / korte spørsmål-og-svar /
"kjøpshjelp" — et oppslagsverktøy som kobler BC/DIA/CYL/AXIS-tall direkte til produkt +
pris). Kjøpshjelp-idéen er genuint god og bør vurderes som egen funksjon senere, IKKE bare
enda et sett statiske sider. Advarte eksplisitt mot å bygge 30-50 separate tynne
spørsmål-og-svar-sider (tynt-innhold-risiko) -- fortsetter heller å legge korte spørsmål
inn som FAQ-schema i relevante guider, samme mønster som allerede etablert.

**Viktig hendelse:** en av de pastede AI-kritikkene siterte spesifikke "gamle/språklig
svake" fraser fra angivelig eksisterende sideinnhold (f.eks. "Det seneste er dog linser
laget av silikonhydrogel...", "behandling og forvaltning av ikke-refraktiv lidelser").
Verifiserte direkte mot live sider (`/guide/hvordan-bruke-kontaktlinser/`,
`/guide/terapeutiske-kontaktlinser/`) -- **ingen av frasene finnes noe sted**. Tredje
fabrikerte AI-sitat om kontaktlinser.no denne økten (etter Prisjakt-partnerprogram-saken
og en tidligere "alle nettbutikker"-påstand) -- ren konsistent grunn til alltid å
verifisere spesifikke sitat-påstander mot faktisk sideinnhold før de tas videre.

**Husk ved fremtidige guide-tillegg:** `guide_slugs` i `generate_pages.py` leses fra
`catalog["categories"]`, som kommer fra `site_generator/catalog_live.json` -- IKKE direkte
fra `products_meta.json`. En ny guide må derfor legges til i `GUIDE_CONTENT` (og
`GUIDE_ICONS`) i `render_templates.py` OG i minst én kategoris `"guides"`-liste i
`products_meta.json`, og **`build_catalog.py` må kjøres før `generate_pages.py`** for at
katalogen faktisk skal plukke opp den nye kategoriseringen -- glemte dette selv midt i
denne økten (kjørte kun `generate_pages.py` på en utdatert `catalog_live.json`, guidene
ble ikke bygget før feilen ble oppdaget og `build_catalog.py` kjørt på nytt).

## Resept-splitt og "Kjøp og priser"-gruppe (2026-08-16, samme dag)

Etter en mer gjennomarbeidet strukturplan fra brukeren (5-grens guide-tre: Kontaktlinser /
Forstå resepten / Bruk & vedlikehold / Vanlige problemer / Kjøp & priser):

- **Splittet resept-guidene**: de 2 kombinerte guidene (bc-og-dia-forklart,
  sph-cyl-axis-forklart) erstattet med 6 fokuserte enkeltsider (BC, DIA, PWR/SPH, CYL,
  AXIS, ADD -- ADD var en reell mangel, lagt til nytt) + en illustrert hub-side
  `forsta-kontaktlinseresepten` med en klikkbar eksempelresept. Begrunnelse: dette er
  oppslags-søk ("hva betyr ADD"), ikke lesesøk -- én fokusert side per begrep gir renere
  direkte-svar for Google/AI-uthevede utdrag. Trygt å gjøre uten redirects siden de to
  originalene var timer gamle.
- **9 nye guider i "Kjøp og priser"**: Hva koster kontaktlinser, 30 vs. 90-pakning, pris
  per linse, hvorfor prisene varierer, hvordan totalpris beregnes (med illustrert
  frakt-eksempel), abonnement vs. kjøpe selv, hvordan kjøpe på nett, uten resept, bytte
  merke selv. Forankret i sidens egne, ekte prisdata/metodikk der mulig -- ingen
  fabrikerte kronebeløp presentert som reelle priser.

Totalt **37 guider** nå. `GUIDE_ICONS` følger samme mønster: 6 faste aksentfarger
(aqua/mint/coral/amber/lavender/sky) rullert, fylte SVG-ikoner, egen-tegnet.

**Fortsatt IKKE bygget, bevisst i vente**: "Vanlige problemer"-gruppen (linse sitter
fast, uklart syn, svir/rødhet -- helseadjaente, trenger «oppsøk optiker»-varsler),
kjøpshjelp-verktøyet i sin fulle, dynamiske form (slå opp egne tall → få produktforslag --
hub-siden over er en forenklet, statisk versjon av dette), og produsent-sider (CooperVision
osv., atskilt fra merke-sider). Se også de tre pastede spørsmålslistene (34+25+100
spørsmål) fra tidligere samme dag -- fortsatt ikke dedupliserte i et samlet regneark.

## Ekte fraktberegning innført (2026-08-16, samme dag)

Brukeren spurte "vi sier vi har med frakt i prisene, men har vi det?" -- svaret var nei:
`shipping_nok` var hardkodet til `0.0` for absolutt alle tilbud fra alle 8 forhandlere,
til tross for at footer-disclosure og flere guider hevdet "totalpris inkl. frakt".

**Undersøkelsen** (kjøpsvilkår-sider + live i kassen for Lenson/Lensway, som ikke oppgir
tall offentlig) fant reell fraktpolicy for alle 8:
- Interoptik, Lensit: alltid gratis
- Synsam: 39 kr ALLTID for enkeltkjøp -- ingen fri-frakt-grense finnes i det hele tatt
- Extra Optical: gratis over 900 kr, ellers 45 kr
- Coptikk: gratis over 500 kr, ellers 50 kr
- Lenson: gratis over 1199 kr, ellers 50 kr (eksplisitt banner i kassen)
- Lensway: samme gebyr (50 kr) ved samme ordreverdi som Lenson -- grense antatt lik
  (1199 kr) siden de deler plattform/selskap, men ikke bekreftet like eksplisitt

**Kritisk fallgruve funnet og rettet midt i arbeidet:** Extra Optical har ULIK
fraktpolicy for briller og kontaktlinser. Brukte først feil tall (49 kr/gratis over
600 kr) fra deres generelle "frakt og levering"-side -- den siden er faktisk om
BRILLER ("produksjonsordre", sliping/montering av glass). Brukeren viste et
skjermbilde av riktig tall direkte fra en linse-produktside (45 kr/gratis over 900 kr),
og det ble rettet. Gikk deretter og bekreftet Interoptik/Brilleland/Synsam direkte på
ekte linse-produktsider for å utelukke samme avvik der -- alle tre stemte med det som
allerede var konfigurert. **Lærdom for fremtidige forhandlere:** en generell
frakt-/kjøpsvilkår-side holder ikke alene hos en forhandler som selger flere
produktkategorier -- sjekk alltid det produktkategori-spesifikke tallet direkte.

**Teknisk implementasjon:** ny delt `compute_shipping_nok(price_nok, shipping_cfg)` i
`offer.py`, brukt av `scraper.py` (leser `shipping`-config fra `sources_config.json`
sin `scraper_config`) og `ingest_feed.py` (Extra Optical sin Adtraction-feed har ingen
fraktdata selv, tallene er hardkodet direkte i `map_adtraction_row()`, med
`sources_config.json` sitt `shipping`-felt kun som dokumentasjon av samme tall --
IKKE lest derfra, hold i sync manuelt ved endring). `shipping_cfg.free_over = null`
betyr bevisst "aldri gratis" (Synsam), ikke det samme som `fee_nok = 0`.

Bekreftet konkret effekt live: Biofinity 6-pack hadde tre forhandlere med identisk
produktpris (331 kr) -- alle viste tidligere "laveste pris" samtidig. Nå vinner kun
Lensit (gratis frakt), Lenson/Lensway havner korrekt på 381 kr.

**Neste steg, ikke bygget ennå:** et antall-felt på produktsider der bruker oppgir hvor
mange esker de trenger, som regner `(produktpris × antall) + frakt` dynamisk per
forhandler og omsorterer -- siden fri-frakt-grensene varierer så mye (500-1199 kr) kan
hvem som er billigst endre seg avhengig av bestillingsstørrelse. Bruker samme
shipping-config, bygger direkte videre på dagens arbeid.

## Selvstendig kveldsarbeid: "selges også som" på produktsider (2026-08-16)

Brukeren logget av for kvelden og ba meg fortsette med noe trygt/lavrisiko selv. To ting:
1. Sjekket at CTA-knappeteksten er konsistent overalt ("Se hos {forhandler}") og aldri
   antyder at vi selger noe selv -- ingen funn, allerede riktig, ingen endring nødvendig.
2. La til en "Selges også under andre navn"-seksjon på selve produktsiden (29 av 139
   produkter har minst ett kjent private label-alias) -- private-label-siden lenket
   allerede til det ekte produktet, men ikke omvendt. Ny `aliases_by_product_id`
   i `generate_pages.py` (motsatt gruppering av `private_labels.json`), sendt som ny
   valgfri parameter til `render_product_page()`. Kun eksisterende, verifiserte data
   brukt -- ingen ny research.

## Produsentsider, merkeinnhold, Cloudflare og forside-redesign (2026-08-18–20)

Stor SEO/AI/GEO-runde over flere dager. Kort oppsummert hva som er nytt siden forrige
statusnotat:

- **Domenet ligger nå bak Cloudflare** (brukerens eget, bevisste DNS-bytte hos
  Domeneshop). Åpnet for ekte server-side 301-er via Cloudflare Bulk Redirects for de
  237 gamle `.aspx`-URL-ene (erstatter den gamle klientside-JS-omdirigeringen fra
  404-siden — den koden ligger fortsatt som en harmløs backup). **Viktig fallgruve
  funnet og fikset:** Cloudflares "AI Crawl Control" → "Managed robots.txt" var slått
  PÅ som standard og injiserte en `Disallow`-blokk for GPTBot/ClaudeBot/Google-Extended
  som overstyrte sidens egen bevisste `Allow`-policy lenger ned i samme fil — skrudd av.
  HSTS er også aktivert i Cloudflare.
- **Produsentsider lansert** (`/produsent/{slug}/`, `MANUFACTURERS`-dict i
  `render_templates.py`): CooperVision, Alcon, Bausch + Lomb, Johnson & Johnson Vision,
  Eyemed Technologies, Menicon. Hvert av de 20 linsemerkene er koblet til riktig
  produsent (`BRAND_TO_MANUFACTURER`), med en "Produsert av X →"-lenke på både merke-
  og produktsider (produktsider: rett under spesifikasjonstabellen, bevisst IKKE i
  hero — konkurrerte med prissammenligningen). Ingen av de 6 sjekkede norske
  konkurrentene har noe tilsvarende.
- **Originalt "om merket"-innhold på alle 19+ merkesider** (`BRAND_CONTENT`-dict) —
  materiale-/teknologinavn og vanninnholdstall verifisert direkte mot produsentkilder
  (aldri kopiert fra en forhandlers markedsføringstekst — fant selv et reelt avvik hos
  en konkurrent underveis: 70% vs. faktiske 59% vanninnhold for én SofLens-variant).
- **Flere guide-siteringer** lagt til med det etablerte to-delte sitatmønsteret
  (egen lenket setning + separat `<blockquote>`) — 7 av 37 guider har nå ekte,
  verifiserte kilder (NHI/Helsenorge). Resten er bevisst ikke tvunget inn med
  siteringer der ingen god kilde finnes.
- **Coptikk fullført**: 64 nye tilbud på eksisterende produkter, pluss "Ascend"
  (CooperVisions private label hos Coptikk) — kun 5 av 16 Ascend-produkter fikk
  koblet seg til et ekte CooperVision-produkt med tilstrekkelig sikkerhet (Premier→
  Biofinity, Premier Toric→Biofinity Toric, Evolve+ / Evolve+ Toric→Avaira Vitality
  (Toric), Active Toric 1 Day→Clariti 1 day Toric — sistnevnte bekreftet via en ny
  teknikk: eksakt matchende lovpålagt "plastnøytral"-tekstmal på både Coptikk sin
  side og CooperVisions egen norske side). De resterende 11 er bevisst utelatt —
  ingen kilde beviste hvilket ekte produkt de tilsvarer. Se `private_labels.json`
  (`"chain": "Coptikk"`) og `PRIVATE_LABEL_SUBBRANDS["Coptikk"] = "Ascend"`.
- **"Live" oppdaget og lagt til som nytt CooperVision-merke** (2 produkter,
  Lenson+Lensit) — sidespor fra Ascend-researchen: samme materiale (somofilcon A) som
  Clariti 1 day, egen ungdoms-/inngangsnivå-posisjonering. Uavklart, bevisst utelatt:
  om "Ascend Active 1 Day" faktisk er Live (kun én kilde, ikke to uavhengige).
- **149→155 produkter totalt** etter flere runder (Precision7 6-pack fantes ikke som
  reell pakningsstørrelse noe sted i verden — byttet til 12-/27-pack; pluss Acuvue
  Oasys MAX Multifocal, Dailies All Day Comfort, MIRU (nytt merke, Menicon), MyDay
  MiSight, Live).
- **Forsiden redesignet** (2026-08-20) etter brukerens egen mockup: fargesystemet
  byttet fra aqua til blue (se designsystem-punktet lenger opp), kategoriene er nå en
  radliste med fargede ikoner på mobil / et 5-kolonners grid på PC (`.hero-panel`,
  `.category-rows`/`.category-row`, breakpoint 1024px), hero-bildet er skjult på
  mobil men vist øverst til høyre på PC, og et nytt "Uavhengig og oppdatert"-
  tillitskort er lagt til. Søkefeltet har nå en synlig "Søk"-knapp (naviger til
  beste treff, siden vi ikke har noen egen søkeresultatside).
- **Bevisst IKKE gjort ennå** (åpne tråder): originalt innhold à la Extra Optical for
  de resterende merkesidene er dekket, men **Apotek1/Vitusapotek sine egne
  kontaktlinser** (mulig asiatisk fabrikk, "lik originalen") er en ny, ikke undersøkt
  tråd brukeren nevnte. USA-markedet ble vurdert og bevisst lagt på is til senere —
  se egen vurdering: reelt gap i alle sjekkede konkurrenter (ingen siterer noen
  autoritativ kilde), men krever et cold-start uten den domene-historie-fordelen
  Norge har.

## Dropdown-redesign, manuelt kuraterte produktbilder og prisvisning i søk (2026-08-28)

- **Rike dropdown-menyer** i `TOPBAR_HTML`: Kontaktlinser/Merker/Guider fikk en
  fullstendig redesignet meny basert på brukerens egne skisser (type-rader med
  farge-ikoner, merke-logo-rutenett, promo-boks, "nyttig å vite"-lister) --
  `BRAND_LOGOS`/`_brand_badge`/`CATEGORY_ICONS`/`CATEGORY_COLORS`/
  `CATEGORY_TAGLINES` er flyttet til modulnivå (fra hhv. lenger ned i filen og
  en lokal variabel i `render_home_page`) siden `TOPBAR_HTML` nå trenger dem.
  Tilbehør-menyen er BEVISST holdt enkel (kun Linsevæske/Øyedråper, ingen
  oppdiktede kategorier) til sortimentet faktisk utvides. Egen `.mega-type-row`-
  klasse (ikke gjenbruk av `.category-row`) for å unngå at forsidens egen
  `@media(1024px)`-variant utilsiktet trekkes inn i dropdownen siden
  `TOPBAR_HTML` ligger på alle sider inkl. forsiden selv.
- **Manuelt kuraterte produktbilder** (`manual_image`-felt i `products_meta.json`,
  `_product_image()` i `render_templates.py` -- sjekkes FØR
  `pick_product_image()`/feed-bilder): 159 produkter totalt, 57 manglet
  lisensiert bilde (kun `affiliate_feed` teller som lisensiert). Første runde
  dekket 6 av 7 manglende Acuvue-produkter med ekte pressebilder fra
  acuvue.com, konvertert til komprimert JPEG i `static/products/`. **Viktig
  lærdom:** stol ALDRI på filnavn/alt-tekst alene -- CooperVision.no sin
  forbrukerside gjenbruker generiske livsstilsbilder med produktspesifikke
  filnavn (fant og forkastet minst to feilmerkede bilder derfra). Visuell
  verifisering i nettleseren er obligatorisk før nedlasting. Samme bilde
  gjenbrukes bevisst for 30-/90-pakningssøsken av samme produktlinje der
  emballasjen er identisk (samme praksis som lenspricer.no/godpris.no).
  Resterende ~50 produkter (MIRU, Precision7, Clearlii, Clariti, Ultra, ReNu,
  Opti-Free, Systane m.fl.) er IKKE dekket ennå -- fortsett samme metode.
- **Tradedoubler-token rotert** (brukeren limte forrige token inn i en annen
  AI-tjeneste): nytt token verifisert og oppdatert i `sources_config.json`
  (16 forekomster, Shopping4net sine feed_urls). Lenson (`fid=9560`) og
  Lensway (`fid=6884`) er godkjent som annonsører hos Tradedoubler, men
  publisher-kontoen var pr. 2026-08-28 ikke koblet til feedene deres ennå
  ("Requester is not connected to Feed") -- sjekk på nytt når brukeren sier
  fra, samme JSON-API-format som Shopping4net forventes (`map_tradedoubler_row()`
  bør fungere uendret, bare ny `fid` i `feed_urls`).
- **AI-oppsummeringsboksen viser nå pris UTEN frakt som hovedtall** (både
  `render_product_page()` og `render_solution_product_page()`), ikke totalpris
  som før. Årsak: Google sin uthevede pris i søketreff (og trolig snutt-teksten)
  hentes med stor sannsynlighet fra denne synlige boksen -- med totalpris som
  hovedtall så vi konsekvent dyrere ut enn konkurrenter (Klarna, Prisjakt m.fl.)
  i søkeresultatene selv når vi faktisk var billigst. Bekreftet mot Prisjakt.no
  sitt eget mønster: pris uten frakt som standardtall, frakt vist synlig per
  tilbud, egen "pris inkl. frakt"-sortering tilgjengelig. Samme forhandler som
  resten av siden peker på som billigst (basert på total pris) beholdes --
  bare hovedtallet i denne ene setningen endret til "fra {produktpris} kr
  (ekskl. frakt)", med tydelig forbehold. Alt annet (badge, sortering,
  best-price-band, full tilbudsliste) er UENDRET og viser fortsatt reell
  totalpris inkl. frakt -- kjerneprinsippet står fast, bare "reklame"-tallet
  i denne ene boksen er endret. AggregateOffer-schemaet (`lowPrice`/`highPrice`)
  brukte forøvrig ALLEREDE `price_nok` uten frakt, det var kun denne synlige
  boksen som var inkonsekvent med det.
- **Google Shopping-panelet** (høyre side i søkeresultater, "Farmasiet 125 kr"
  osv.) krever en egen Google Merchant Center-konto + produktfeed -- kommer
  IKKE automatisk fra schema.org-markup på siden. Ikke bygget, egen
  vurdering/prosjekt om ønskelig senere.
- **`og:site_name`/`WebSite`-schema var allerede riktig satt opp** (se
  `_og_meta()`/`FONT_LINKS`) -- en eldre notis i dette dokumentet (under
  "Titler, synlig AI-oppsummeringsboks..." 2026-08-15) som påsto det motsatte
  var feil, nå rettet. At Google likevel viser små bokstaver i SERP er trolig
  bare indekserings-/cache-forsinkelse, samme kategori som prisvisnings-
  forsinkelsen over -- ingen kodeendring nødvendig.

## Utgående forhandlerlenker åpnes nå i ny fane + rel-fiks (2026-09-05)

Brukeren observerte at andre norske prissammenligningstjenester konsekvent åpner
forhandleren i ny fane (bekreftet ved egen sjekk: "alle jeg har sjekket ... åpner ny
fane og brukeren følger etter"), og at dette passer godt til brukerreisen for en
sammenligningstjeneste (sammenlign → besøk butikk → kom tilbake → besøk neste butikk)
selv om `target="_blank"` ikke er en dokumentert SEO-fordel i seg selv.

- **`render_offer_card()` og `render_winner_widget()`** (begge i `render_templates.py`)
  fikk `target="_blank"` + `rel="... noopener"` på selve tilbudslenken. `noopener` er
  ren browser-sikkerhetshygiene ved ny-fane-åpning (reverse tabnabbing), ikke et
  SEO-signal. Kun UTGÅENDE forhandlerlenker endret -- interne lenker (merker,
  kategorier, guider, andre produkter) er UENDRET, åpnes fortsatt i samme fane.
- **Samtidig rel-fiks:** koden brukte faktisk `"sponsored nofollow"` kombinert for
  affiliate-lenker, i strid med den faste regelen lenger opp i dette dokumentet
  ("rel="sponsored" på affiliate-lenker, rel="nofollow" på scrapede -- ikke bland
  disse"). Rettet til rendyrket `sponsored` (affiliate) / `nofollow` (skrapet), pluss
  `noopener` på begge nå som de åpnes i ny fane.
- **Klikk-sporing** (`outbound_click`-dataLayer-pushen i `CONSENT_SCRIPT`) måtte
  justeres: det gamle preventDefault()+300ms-forsinkelses-mønsteret var bygget for å
  vinne et kappløp mot samme-fane-navigering (se punktet fra 2026-08-31 lenger opp) --
  med `target="_blank"` navigerer IKKE denne fanen bort i det hele tatt, så
  klikk-handleren sjekker nå `link.target === '_blank'` og pusher eventet direkte uten
  forsinkelse/preventDefault i det tilfellet (fallback-grenen med forsinkelse er
  beholdt for en eventuell fremtidig lenke uten `target="_blank"`). Uendret opprinnelig
  bug ville ellers stille droppet all sporing for disse lenkene, siden handleren fra
  før returnerte tidlig på `link.target !== '_self'`.
- Quantity-kalkulatorens JS (`_QTY_CALC_SCRIPT`) skriver `rel` på nytt ved antallsbytte
  (leser fra `calc_offers`-listen) -- oppdatert til samme `sponsored`/`nofollow` +
  `noopener`-mønster der også, men rører ALDRI `target`-attributtet (satt kun én gang
  ved førstegangsrendring, DOM-elementet gjenbrukes ved sortering).

## Utvidet produktserie-katalog: 17 nye familier (2026-09-05)

Fulgte opp pilotrunden (11 familier, se product_families.json sin `$comment`) med
brukerens "vi skal lage dette for alle der det er mulig"-instruks. Samme
verifiseringsdisiplin: kun sfærisk/torisk/multifokal/XR-varianter av SAMME
linsedesign, materialkonsistens sjekket programmatisk per familie før den ble lagt
til. 17 nye familier lagt til (28 totalt): Acuvue Oasys 1-Day w/ Hydraluxe, Acuvue
Oasys MAX 1-Day, Dailies Total1, TOTAL30, Precision1, Precision7, SofLens Daily
Disposable, SofLens 59, PureVision, PureVision2, Biotrue ONEday, ULTRA, ULTRA ONE DAY,
Biomedics 55 Evolution, Biomedics 1Day Extra, Miru 1day UpSide, Proclear Multifocal XR.
3 av disse fikk automatisk en ekstra privat-label-variant-side (samme
kryssreferanse-mekanisme som pilotrunden): TOTAL30→Synsam (`eyeq-total30`),
Precision1→Synsam (`eyeq-precision1`), Biomedics 1Day Extra→Brilleland (`iwear-fit`)
OG Synsam (`eyeq-one-day-classic`).

**Bevisst holdt separate familier** (samme prinsipp som Biofinity/Biofinity XR i
pilotrunden -- delt materiale betyr ikke samme produktlinje): PureVision vs.
PureVision2 (samme "Balafilcon A", men egen produktgenerasjon), ULTRA vs. ULTRA ONE
DAY (samme "Samfilcon A med MoistureSeal", men månedslinse vs. dagslinse), SofLens 59
vs. SofLens 38 (SofLens 38 bevisst utelatt -- uverifisert/annet materiale).
**Bevisst utelatt helt:** Miru "Flatpack"-variantene (ingen sfærisk Flatpack finnes å
anker familien i, uklart om Upside/Flatpack er samme linse), `focus-dailies-*`/
`dailies-all-day-comfort-*` (rene ALIASER av Dailies AquaComfort Plus via
`duplicate_products`, ikke en egen variant-familie).

## Kategorisideredesign: datadrevet intro, kompakt filter, mobil bottom sheet (2026-09-05)

Kai la fram (og diskuterte med en AI) en kritikk av dagens `/kontaktlinser/{kategori}/`-sider:
fine designforslag må ikke gå på bekostning av crawlbart innhold. Etter flere runder med
skjermbilde-mockuper (desktop og mobil) landet vi på en konkret spesifikasjon, implementert i
`render_category_page()`:

- **Datadrevet intro**: alle 5 kategori-introer i `products_meta.json` deler nøyaktig halen
  "fra alle merker vi følger" -- erstattes nå ved rendring med ekte, live tall
  ("fra 16 merker og 48 produkter"), samme tekst brukes i meta description/og-meta.
- **Statlinje** (produkter/merker/oppdateringsfrekvens) + en ny **"Hva er X?"-forklaringsboks**
  (`CATEGORY_EXPLAINERS`-dict, kort faktabasert tekst, lenker til første guide i kategoriens
  egen guide-liste -- ingen hardkodet guide-slug).
- **Populære merker**: chips sortert etter faktisk antall produkter PER KATEGORI (ikke en
  manuelt satt liste), med ekte `brand_label` (fikset en gammel `.capitalize()`-gjetning som
  ga feil for f.eks. "ClearLab"). "Alle merker (N) +" utvider samme rad -- alle merkene ligger
  allerede i DOM-en, kun synligheten endres med JS.
- **Basiskurve/Diameter/Vanninnhold er nå EKTE multi-select** (kan velge flere verdier per
  felt samtidig, ikke bare én "aktiv chip" som før), bygget som `<details>`/`<summary>` --
  lukket som standard, ekte HTML-verdier i alle tilfeller (ALDRI hentet via JS først når
  brukeren åpner). Rekkefølge BC -> DIA -> Vanninnhold sist, vanninnhold markert
  "(valgfritt)" -- bevisst valg: BC/DIA er en reell tilpasningsegenskap (finne produkter med
  bestemte spesifikasjoner), IKKE en påstand om at samme tall gjør produkter medisinsk
  utbyttbare (presisert av bruker). Vanninnhold beholder eksakte verdier (33 %, 38 %, 51 % …),
  bevisst IKKE gruppert i sonebolker ("50-70 %") -- en eksakt verdi er en ekte produktegenskap,
  en sonebolk er en klassifisering Kontaktlinser.no selv ville introdusert.
- **Mobil**: "Filtrer produkter"-knapp (med antall-badge) åpner BC/DIA/Vanninnhold som et
  slide-up-ark (kun CSS `transform`, samme DOM som desktop sine inline-dropdowns -- innholdet
  er identisk med eller uten JS). Merke-chipsene ligger UTENFOR arket, alltid synlige/
  trykkbare direkte på siden. **Desktop**: samme `<details>`-elementer vises som 3 uavhengige
  inline dropdown-knapper i en rad (posisjon `absolute`-popover ved `min-width:1024px`).
- **Aktive filtre**-chips ("Basiskurve: 8,7 mm ✕") bygges dynamisk av JS og fjerner ett og ett
  filter -- men blir ALDRI til egne URL-er/query-parametre (ren klientside-tilstand, samme
  prinsipp som det opprinnelige merke-filteret) -- ingen fare for at Google skal indeksere
  tusenvis av filterkombinasjoner (`?bc=8.6&dia=14.2` osv.).
- **Sortering** byttet fra en tekstknapp til en ekte `<select>` (styles som en pen dropdown-pille).
- **Ny "Om utvalget"-boks** under produktlisten: ekte beregnet spenn
  ("basiskurve fra 8,3–9,0 mm, diameter fra 13,8–14,3 mm og vanninnhold fra 33–100 %"),
  samme "utelat helt der for lite data"-prinsipp som filtrene selv.
- **Produktkortene** har nå en kompakt spesifikasjonsrad (vanninnhold/BC/DIA-ikoner) --
  `_render_product_tile()` fikk et nytt valgfritt `specs_row_html`-parameter, tomt (uendret)
  for alle andre kallesteder (merke-/tilbehør-/private label-sider).
- Global `.chip.active`-farge byttet fra navy til blå (matcher mockupene, brukes nå
  konsekvent på tvers av merke-/kategori-filtre alle steder `.chip` gjenbrukes).

**Bevisst IKKE bygget denne runden** (vurdert og lagt til side, ikke glemt): "Mest populære"/
"Beste komfort"/"Bestselger"-merker på produktkort (krever ekte, veldefinert førstepartsdata --
ikke bare "flest klikk", siden posisjon i lista i seg selv påvirker klikk) og et
favoritt/hjerte-ikon (ingen SEO-verdi, ekstra vedlikehold, ikke forespurt av bruker som en
reell prioritet nå). Prishistorikk-lenken på produktkortet er derimot reell og allerede bygget.

## Kontaktlinser.no flyttet til Chillout Labs/Sjekkpris-kontoene (2026-09-10)

Kontaktlinser.no administreres nå under nye kontoer i samme konsern (Kai, via
kai@sjekkpris.no) -- **ingen endring av GitHub-org (fortsatt Hovedkvarter),
domeneeierskap, hosting eller merkenavn på selve siden.**

- **GTM-beholder byttet**: `GTM-KGPF68` -> `GTM-5RZFVNQM` (Chillout Labs-
  kontoen). Ren én-linje-ID-bytte i `GTM_HEAD` i render_templates.py --
  samme last-etter-samtykke-mekanikk (`window.__loadGTM()` kalt fra
  `CONSENT_SCRIPT`), fortsatt ingen `<noscript>`-fallback (bevisst policy,
  uendret). GA4-ID (G-ELJYYBLS6H), CartBooster (lastes som en GTM Custom
  HTML-tag mot `s.cartbooster.io/preload`, IKKE i vår kode) og
  `outbound_click`-eventet (retailer+affiliate) er alle videreført i den
  nye beholderen, verifisert live av Kai i GA4 etter bytte.
  **Reelt funn ved verifisering:** den GAMLE beholderens `outbound_click`-
  tag hadde en skrivefeil i variabelnavnet for affiliate-parameteren
  (`"affilaite"` i stedet for `"affiliate"` -- bokstavene byttet om), som
  betyr at `affiliate`-verdien trolig alltid var `undefined` i GA4
  historisk. Bekreftet rettet i den nye beholderen ved verifisering
  (Kai bekreftet "riktige retailer-verdier og affiliate true/false").
- **Google tag gateway**: Cloudflare sin første-parts-proxy for GTM ER
  aktiv -- oppdaget/bekreftet ved å faktisk simulere samtykke og se hva som
  lastes live: en obfuskert sti (`kontaktlinser.no/4pvl/...`) proxyer hele
  GTM-konfigurasjonen gjennom eget domene. Dette er REN Cloudflare-side
  infrastruktur (injisert på edge-nivå), usynlig i dette repoet -- **fravær
  av gateway-kode her betyr IKKE at gateway er av**, sjekk alltid Cloudflare
  sitt eget dashbord ("Google tag gateway"-innstillinger) for sannheten.
- **Cloudflare-sonen flyttet til Sjekkpris-kontoen** (samme konto som
  sjekkpris.no allerede ligger under). DNS-poster/proxy-status/SSL (Full)
  importert uendret, nye navnetjenere `katelyn.ns.cloudflare.com`/
  `pedro.ns.cloudflare.com`, ny zone-ID `781afbccaf00dd078337a0f0c8ca1cc8`.
  **Bekreftet ved gjennomgang: INGEN kode, CI-workflow, secret eller
  variabel i dette repoet refererer til noen Cloudflare-konto/sone-ID/API-
  token noe sted** (`gh secret list`/`gh variable list` begge tomme, kun
  det innebygde `GITHUB_TOKEN` brukes, og det er GitHub sitt eget). Alt
  Cloudflare-relatert (redirects, SSL, gateway, robots-policy-brytere) er
  og har alltid vært ren dashbord-konfigurasjon utenfor dette repoet --
  ingenting her trenger endres ved et kontobytte. Samme kjente fallgruve
  som ved forrige Cloudflare-oppsett (2026-08-18) gjelder fortsatt: en
  FERSK sone kan ha "AI Crawl Control -> Managed robots.txt" slått PÅ som
  standard, som da ville overstyrt policyen under stille -- må sjekkes
  manuelt i det nye dashbordet, kan ikke bekreftes/avkreftes herfra.
- **robots.txt sin AI-treningsrobot-policy reversert 2026-09-10**
  (konsernbeslutning): GPTBot/ClaudeBot/Google-Extended/anthropic-ai/
  Applebot-Extended gikk fra `Allow: /` til `Disallow: /` -- reverserer
  den opprinnelige "åpen som standard"-avgjørelsen fra 2026-08-15 (som
  fortsatt sto begrunnet i selve filen). AI-SØK/agent-roboter
  (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, Claude-User,
  PerplexityBot) er UENDRET tillatt, det samme er Googlebot/Bingbot --
  `Google-Extended` styrer kun Gemini/Vertex AI-trening, ikke vanlig
  Google-søkeindeksering, så Googlebot sin tilgang er upåvirket.
- **Opprinnelig gratis-Cloudflare-sonen auto-slettet av Cloudflare selv
  (2026-09-17).** E-post fra Cloudflare varslet at kontaktlinser.no-sonen
  ble fjernet fra "Partner@kontaktlinser.no's Account" -- kontoen Kai
  bekreftet var den aller første, opprinnelige gratis-Cloudflare-kontoen
  siden ble satt opp med i sin tid (altså den GAMLE kontoen sonen nettopp
  ble flyttet bort fra over, inkl. `legacy_aspx_redirects`-lista). Årsaken
  er nettopp at navneserverne ikke lenger peker dit etter migreringen til
  Sjekkpris-kontoen -- helt forventet automatisk opprydning, ikke et
  driftsavbrudd (levende side bekreftet upåvirket: 200 OK, fortsatt
  Cloudflare-proxyet, riktige navnetjenere `katelyn`/`pedro`). Løser samme
  implisitt det tidligere åpne spørsmålet om opprydning av den gamle
  kontoens duplikate/utdaterte Bulk-Redirect-liste -- den er nå borte uansett.
  **Ikke trykk "Add the domain again" i en slik e-post** -- det ville bare
  gjenskapt en ubrukt sone i en forlatt konto, uten noen funksjon siden den
  faktiske, aktive sonen allerede ligger riktig under Sjekkpris-kontoen.
  Kai bekreftet selv (innlogget på partner@kontaktlinser.no) at kontoen sto
  helt tom for domener, og slettet den samme dag -- saken er dermed
  fullstendig avsluttet.

## Chillout-clickout: sa ruller du tilbake (2026-09-25)

Noen kommersielle lenker peker pa `/go/{token}` framfor rett til nettverket.
Tokenet kommer fra Chillouts lesekontrakt pa byggetidspunktet; generatoren kan
ikke lage en slik lenke selv.

**Tilbakerulling er en verdi, ikke en kodeendring.** `clickout_surfaces.json`
i repoets rot holder en tilstand per flate:

| Flate | Hva den er |
|---|---|
| `offer_card` | Det vanlige tilbudskortet |
| `winner_band` | Vinnerbanneret ovest -- sidens mest fremtredende lenke |
| `quantity_calculator` | JSON-en som skriver banneret om nar noen bytter antall |

Sett en til `"off"` og bygg. Da rendrer den flaten leverandor-URL-ene igjen --
akkurat som for clickout fantes -- uten at noe annet flytter seg. Bygget gar
daglig og kan startes manuelt, sa verste fall er ett bygg.

Tre ting som er lette a ta feil av:

- **`winner_band` og `quantity_calculator` hører sammen.** Star banneret pa
  mens kalkulatoren er av, faller banneret tilbake i det noen trykker "2
  esker".
- **Alt annet enn `"on"` leses som av**, og sier fra i byggeloggen. En
  skrivefeil skal aldri kunne sla noe PA.
- **A gjore et mal userverlig i Chillout er IKKE tilbakerulling.** Da svarer
  `/go/` 404 mens siden fortsatt lenker dit, som er verre enn a gjore
  ingenting. Bryteren over er den eneste tilbakerullingen.

Hvilke TILBUD som er godkjent er et annet sporsmal, og det bor i `CONVERTED` i
`site_generator/chillout_clickout.py`.

## Søkeboks-CTA på guide-sider (2026-09-25)

Guide-sidene får mest organisk trafikk (bl.a. `/guide/linse-sitter-fast-i-oyet/`),
men mange forlater siden rett etter å ha lest svaret. Alle 40 guider har nå
en søkeboks ("Bruker du kontaktlinser? Finn laveste pris"): en kompakt versjon
rett etter første avsnitt (alle guider åpner med et `<p>`) og en full versjon
med snarveier til kategorier nederst.

- Delt kode i render_templates.py: `LENS_SEARCH_STYLE`, `LENS_SEARCH_JS`,
  `build_search_index()`, `render_guide_search_card()`. Forsiden bruker nå
  samme CSS/JS/indeks-bygger (innebygd JSON som før); guide-sidene henter
  `/data/search-index.json` (skrives av generate_pages.py) først når feltet
  får fokus, så guide-HTML forblir lett.
- **SEO/AI-sikring (Kai krevde at dette ikke skulle gå ut over SEO/AI):**
  verifisert mot produksjon at title, meta description, canonical, H1, H2-er,
  JSON-LD og all brødtekst (utenom selve boksen) er byte-identiske, og at
  svar-avsnittet fortsatt er første innhold i artikkelen. Boksene er
  `<aside data-nosnippet>` (holdes utenfor Google-snutter, semantisk
  "tilleggsinnhold" for AI-roboter), ingenting hentes ved sidelasting
  (indeksen lastes kun ved fokus -> ingen LCP/CLS-effekt), og ingen nye
  indekserbare URL-er. Pris: ca. +8,8 KB HTML per guide (ukomprimert).
- Søket pusher `guide_search_click` til dataLayer (guide, product, source =
  suggestion/button). **Krever en GA4-event-tag + trigger i GTM-beholderen
  (GTM-5RZFVNQM) for å havne i Analytics** -- ikke laget ennå.

## GitHub Actions-kostnad og Chillout-migrering (analyse 2026-09-26)

**Retning (bestemt av Kai):** Chillout eier sentralisert feed-/prisinnhenting,
og Kontaktlinser.no blir en *konsument* av disse dataene i stedet for selv å
hente/skrape forhandlerne fire ganger i døgnet. **Analysen under er ren
dokumentasjon -- ingen workflow-, tidsplan-, cache- eller produksjonsendringer
er gjort.** Ikke optimaliser workflowen i mellomtiden uten at Kai ber om det.

**Konklusjon:** feed-/katalogstørrelsen er *ikke* det som driver
GitHub-tiden. Sekvensiell skraping av forhandlere dominerer, og GitHubs
avrunding per jobb blåser opp de rapporterte minuttene.

Målt (kilde: `gh api repos/Hovedkvarter/Kontaktlinser-no/actions/runs` og
`.../runs/{id}/jobs`, 947 kjøringer 10. aug -- 26. sep 2026):
- Workflowen `build-and-deploy.yml` har 1 jobb, sekvensielle steg, cron
  `0 */6 * * *` (4/dag), pluss `push` til main og manuell start. Ingen
  cache, ingen Node, ingen tester; `pip install` (2 s) kjøres hver gang.
- Planlagt jobb: median 537 s (snitt 560, min 217, maks 1 170). Steget
  «Hent priser (feeds + skraping) og bygg katalog» = 518 s median = 96,5 %
  av jobben. All annen CI-overhead er ca. 19 s median (3,5 %).
- Push-kjøringer: median 13 s (hopper over skraping), men 285 stk (26
  dager, opptil 35/dag). Hver push utløser i tillegg GitHubs egen
  `pages-build-deployment` (3 jobber à 4-10 s; 459 kjøringer totalt).
- Feed-henting (Tradedoubler ×3 forhandlere + Adtraction ×2): **29 s**, målt
  lokalt med samme kode (ikke på runneren -- CI-loggen buffrer utskrift).
- Skraping: 338 sekvensielle mål mot 8 forhandlere (coptikk 100, interoptik
  58, lensit 56, synsam 43, kroghoptikk 42, brilleland 31, vitusapotek 4,
  apotekfordeg 4), minst 3 s mellom kall til samme domene
  (`MIN_DELAY_SECONDS` i scraper.py). **Ca. 490 s er estimat (differansen
  518 − 29), ikke direkte målt.**
- Mislykkede/avbrutte/retry-kjøringer: ca. 20 rå minutter totalt (< 1 %).

Avstemming mot GitHub Billing (Kai så ~1 410 Linux-minutter): 1.-26. sept.
gir 585 jobber, 945 rå minutter, **1 410 minutter når hver jobb rundes opp til
hele minutter** -- eksakt treff. Fordeling: planlagt hoved-jobb 922, push 46,
Pages-deploy 441 (rå 62 min!), engangs-workflow 1. En tredjedel (465 min) er ren
avrunding. Fire planlagte oppdateringer/døgn ≈ 52 avregnede minutter (≈ 13 per
oppdatering: ~9,9 jobb + ~3 Pages); fordeling planlagt/push i september
(~87 % / ~13 %) er estimert, ikke målt.

Forbehold: repoet er **offentlig**, timing-API-et viser `billable = 0`, og
GitHub-hostede runnere er gratis for offentlige repoer -- 1 410 er derfor
trolig bruttoforbruk med full rabatt. Ikke verifisert mot selve billing-siden
(krever `user`-scope). De tre private repoene på kontoen har ingen
workflows. `Hovedkvarter` er en *personlig brukerkonto*, ikke en org.

**Hva migreringen ville endre (estimater):**
- Flytter *bare feeds* til Chillout: sparer ca. 30 s av ~537 s (< 5 %).
  Skrapingen ligger igjen, og er ikke feed-innhenting.
- Flytter *feeds og skraping*, og Actions bare bygger + deployer: planlagt
  jobb ca. 20-60 s. Ca. 1 + 3 avregnede min per oppdatering mot ca. 13 i dag
  (≈ −70 %; ca. 16 mot 52 min/døgn).
- Pages-deployen forsvinner ikke, med mindre Chillout også overtar bygg og
  publisering. Trenger da en trigger (f.eks. `repository_dispatch`) som
  bygger når data faktisk er endret, i stedet for hver 6. time.
- Skraping flyttet til Chillout er fortsatt underlagt de etablerte
  skrapereglene (robots.txt respekteres, minst 3 s per domene, se
  `scraper.py`; ingen hotlinking av bilder).

**Åpne punkter til migreringen:** (1) Verifiser billing-tallet mot
GitHub-siden. (2) Generer-steget økte fra ~1 s til 21-39 s fra 25. sept.
(sannsynligvis Chillout-lesekontrakten i bygget, ikke undersøkt). (3) Hva
gjør de 8 skrapede forhandlerne når de ikke har feed -- får Chillout en
skraper, eller skal de få affiliate-feed først?

## Daglig oppdatering i stedet for hver 6. time (vedtatt av Kai, 2026-09-26)

Basert på kadensanalysen (72 katalog-øyeblikksbilder 8.-26. sept.): feedene
endrer seg sjelden (1-5 dager av 18 per feed, i batcher, mest rundt 22:15 UTC
overnatting), og de fleste skrapede forhandlerne har ikke endret en eneste pris
på 18 dager (unntak: Synsam, som svinger ca. ±5 % daglig). Ingen endring gikk
tapt mellom de fire daglige observasjonene. Kai valgte plan **C1**: feeds daglig,
full skraping annenhver dag. Beregnet: ca. 49 -> ca. 8 avregnede min/døgn (−83 %).

- **Cron:** `45 22 * * *` (daglig, 22:45 UTC; GitHub forsinker cron med timer,
  så kjøringen lander etter feed-oppdateringen ~22:15-22:20 og før norsk morgen).
- **Skraping annenhver dag, styrt av DATA, ikke ukedag:** kun den planlagte
  kjøringen setter `KL_SKIP_FRESH_SCRAPE=1`. `build_catalog.py` gjenbruker da
  forrige runde sine skrapede tilbud UENDRET (inkl. opprinnelig `checked_at`) hvis
  de er yngre enn `SCRAPE_MAX_AGE_HOURS` = 36 t, ellers skrapes alt. Manuell og
  lokal kjøring skraper alltid fullt. Alle fallback-stier (manglende/ødelagt/
  gammel katalog, ingen skrapede tilbud) gir full skraping -- testet 2026-09-26.
- **Foreldet-grenser:** `FEED_STALE_HOURS = 36`, `SCRAPED_STALE_HOURS = 60` i
  `reconcile_product()` (var 24 t for alt), så «Pris ikke nylig bekreftet»
  (merket het før «... siste 24t») bare vises når noe faktisk har sviktet.
- **Tekst:** all kopi som sa «hver 6. time»/«flere ganger daglig» sier nå
  «daglig» (Kai: ikke oppgi skrapefrekvens i detalj). Metodikksiden hevder ikke
  lenger at «begge kildetypene oppdateres like ofte» eller at vi «aldri gjenbruker
  en gammel pris» -- hvert tilbud viser i stedet når det sist ble kontrollert.
- **Rettet en eksisterende feil i kopien:** nettstedet sa (bl.a. i FAQ-JSON-LD)
  at priser eldre enn 24 t «ikke kan vinne laveste pris». Koden gjør det ikke --
  kun utsolgt/uten lager utelukkes fra vinnerplassen (testet). Teksten sier nå
  bare det som faktisk gjelder.
- **Dropout-beskyttelse (Kai: «denne endringen må ikke gjøre at noen faller
  ned»):** `protect_against_dropouts()` i build_catalog.py. (1) Gir en feed
  under 50 % av forrige antall tilbud (min. 5 sist) gjenbrukes forrige runde sine
  tilbud fra den forhandleren hvis de er < 36 t; (2) på en skrapedag gjenbrukes et
  (produkt, forhandler)-tilbud som feilet hvis forrige var < 60 t. Gjenbrukte
  tilbud beholder opprinnelig `checked_at`, logges som `[DROPOUT-BESKYTTELSE]`
  i CI-loggen, og faller ut av seg selv når de er for gamle. Testet mot
  ekte katalog 2026-09-26 (feed-kollaps som Extra Optical 19. sept., 10 feilede
  Interoptik-tilbud, alderskutt, forhandler flyttet fra feed, ødelagt katalog).
  Ellers gjelder som før: `validate_build.py` stopper utrulling ved feil, og da
  blir forrige publiserte side stående.
- **Gjenstående svakhet:** GitHub dropper av og til planlagte kjøringer (179 av
  ~188 forventede siste 45 dager, ca. 5 %). Ved daglig kjøring betyr en droppet
  kjøring 48 t uten oppdatering -- siden blir stående, men tilbud får
  «Pris ikke nylig bekreftet» etter 36/60 t. Mulig tiltak (ikke innført): et
  ekstra cron-slot (f.eks. 10:45 UTC) som avbryter tidlig hvis katalogen er
  < 20 t gammel, ca. +1 avregnet min/døgn.
- Feed-tidspunkt (22:15-22:20 UTC) er basert på ett øyeblikksbilde av
  Tradedoublers `modified`-felt; Lensway sto på 09:15 UTC. Verifiser etter noen
  dager i GA/prishistorikk at riktig kjøretidspunkt er valgt.

## Ærlig lastmod i sitemap (2026-09-26)

Før stod alle 401 URL-er på «i dag» ved hvert bygg (også guider urørt siden
august) -- en dato som ikke stemmer er misvisende data til søkemotorene (Kai
påpekte dette). Regelen nå, avklart med Kai:

- **Guider:** lastmod = guidens redaksjonelle `updated`-dato (samme som byline og
  Article-schema).
- **Sider med prisdata** (produkt, kategori, merke, serie, forside, private label,
  linsevæske/øyedråper): lastmod = datoen prisene sist ble **bekreftet** (nyeste
  `checked_at` blant tilbudene siden viser), **også når prisene er uendret** --
  Kai: «når priser blir oppdatert er også siste dato, som er korrekt selv om
  teksten er lik». Gjenbrukte tilbud (dropout-beskyttelse, hoppet-over skraping)
  beholder sin gamle `checked_at`, så datoen står ikke på «i dag» hvis noe ikke
  faktisk ble hentet. Dette stemmer overens med JSON-LD `dateModified` på
  produktsidene (samme kilde: nyeste checked_at).
- **Alle sider:** aldri eldre enn siste faktiske innholdsendring, funnet via en
  signatur (hash) av HTML-en uten flyktige deler (`site_generator/lastmod.py`,
  tilstand i `lastmod_state.json`, committes av CI). Statiske sider uten prisdata
  (om-oss, metodikk ...) bruker kun signaturen -- de endres bare når teksten/malen
  endres.
- Første sporing setter dagens dato på ikke-guide-sider én gang (vi vet ikke når
  de sist endret seg).
- Rettet i samme slengen: `/personvern/` og `/vilkar/` viste «Sist oppdatert:
  <dagens dato>» hver dag; viser nå siste faktiske endring (30.08. / 05.09.2026,
  fra git). **`PRIVACY_UPDATED`/`TERMS_UPDATED` i render_templates.py må endres
  manuelt når teksten endres.** Sitemapen hadde også 19 dupliserte guide-URL-er
  (samme guide i flere kategorier) -- nå 40 unike.
- **Synlig dato på siden (2026-09-27, avklart med Kai: diskret, ikke på hvert
  prisprodukt):** ÉN linje per side i prisoppsummeringen («Priser sist bekreftet
  <time datetime=...>27.09.2026</time>», produkt-, linsevæske-, private label- og
  serieside) -- absolutt dato i norsk tid (`oslo_date()` i render_templates.py,
  egen sommertid-regel, testet mot DST-grensene), samme dato som lastmod og
  dateModified. Tilbudskortene viser IKKE lenger «Sist oppdatert: N timer siden»
  (den relative teksten ble regnet ut ved bygging og var feil så snart siden var
  noen timer gammel). På kortet vises dato kun ved avvik: «Pris ikke nylig
  bekreftet (sist <dato>)» når foreldet, eller «Sist oppdatert: <dato>» når
  tilbudet er ≥ 2 kalenderdager eldre enn sidens nyeste (skrapede tilbud som er 1
  dag eldre enn feedene er normalt og vises ikke).
- Merk: med daglig prisbekreftelse flytter lastmod seg omtrent daglig for
  prissider, selv om prisene ofte er like. Det er bevisst og ærlig (vi har
  faktisk sjekket), men Google kan vekte lastmod lavere hvis den ikke sammenfaller
  med synlige endringer -- følg med på indekseringen.

## Prisjakt-modellen: pris uten frakt som standard, chip for total (utrullet 2026-09-27)

Kai besluttet (etter konkurrentgjennomgang og screenshots fra Prisjakt): kontaktlinser.no følger
markedsstandarden -- Prisjakt/Pricerunner/Prisguiden/godpris/Lenspricer viser pris UTEN frakt som
standard, og Prisjakt har en chip «Pris inkludert frakt» (av som standard) som viser og sorterer på
totalpris. Dette er standardmalen for hundrevis av sider (også fremtidige Chillout-sider). Pilotert
først på Acuvue Oasys 6-pack, justert (penere vinnerkort) og rullet ut til ALLE produktsider:
kontaktlinser (138), linsevæske (20), øyedråper (28) og private label (64).

**Malen** (delt kode i render_templates.py: `render_winner_widget`, `render_price_list`,
`PRICE_LIST_STYLE`, `_QTY_CALC_SCRIPT`, `PRICE_DISCLOSURE_HTML`):
- **Vinnerkortet** øverst sier IKKE pris: «LAVESTE PRIS / for 1 eske», butikkens logo, knappen
  «Gå til tilbud →» (knappen ER lenken, bærer id `winner-band-link` + tracking-attributter) og
  «Sammenlign alle N butikker ↓» (hopper til `#tilbud`). Kortet er en `<div>` (unngår nøstede `<a>`).
- **Lista** «Sammenlign priser og butikker» er sortert på laveste PRODUKTPRIS. Chip «Pris inkludert
  frakt» (aria-pressed) viser totalpris for valgt antall, sorterer om og bytter kortet til «Laveste
  pris inkl. frakt». Valget huskes (`localStorage: kl_incl_shipping`); klikk sendes som dataLayer-event
  `price_shipping_toggle` (included: yes/no) -- trenger GA4-tag/trigger i GTM for å måles.
- **Antallsvelgeren** beholdes og gjelder begge modi (frakt regnes per antall, inkl. fri-frakt-grenser;
  «eske/esker» for linser, «flaske/flasker» for linsevæske/øyedråper).
- **Merking:** «Laveste pris» på laveste produktpris; når en ANNEN butikk har laveste totalpris merkes den
  «Lavest totalpris» også i standardvisningen (~9 % av produktene) -- vi påstår aldri «lavest» om noe
  som ikke er det. `reconcile_product()` er uendret og totalpris-basert (brukes til den merkingen, FAQ-svar
  om «hvor er X billigst» og prishistorikk).
- **Samlesider** (kategori, merke, chain-sider, private label-oversikt, serieside) viser «Fra»-pris uten frakt
  og er sortert på den; serietabellen heter «Fra pris (uten frakt)». Verifisert: kategorifliser, meta-
  beskrivelse, JSON-LD `lowPrice`, øverste kort og vinnerknapp gir samme laveste produktpris på alle 138
  linsesider (før viste heltebanneret 312 kr mot 262 kr i søkeresultatet).
- **Tekster oppdatert** (påstanden «alltid lavest totalpris/sortert etter totalpris» stemte ikke lenger):
  footer, forside (hero, tillitskort, tillitsrad, FAQ), guide-CTA, guiden «Hvordan Kontaktlinser.no
  beregner totalpris», om-siden, metodikksiden, affiliate-siden, disclosure/metodikkboks på alle
  produkttyper. Ingen gamle formuleringer igjen i bygget (verifisert). Title, canonical, H1 og robots er
  uendret på alle 396 sider; produktsidenes meta-beskrivelse følger nå laveste produktpris.

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

## Feed-revisjon 2026-09-26: nye produkter og enhetsfelt

- Alle fem feedene (Lensway, Lenson, Shopping4net, Extra Optical, Apotekhjem) ble
  sammenlignet mot katalogen. Lagt til: Live 30/90 hos Lensway (samme produktkoder
  som Lenson), 180-pack av Acuvue Oasys 1-Day Hydraluxe og everclear ELITE (Lenson/
  Lensway 9620/9621), reisepakker (Biotrue/ReNu Flight Pack 100 ml), everclear REFRESH
  3-pack (750 ml), og øyepleie (Oxyal Care Gel, Hylo Night, EYZ Night/Clean, Oxyal
  Total Care Spray, Thealoz Duo Gel) -- kun produkter med minst to forhandlere.
  Pakningsstørrelser ble bekreftet mot Lenson-produktsidene (feedene oppgir dem ikke).
- `solutions_meta.json` støtter nå valgfrie felt: `size_unit` ("g" for gel/salve, standard
  "ml"), `unit_singular`/`unit_plural` (standard flaske/flasker; tube, pakke) og at
  `size_ml` utelates når pris per 100 ml ikke gir mening (servietter, doser).
- Bevisst IKKE lagt til (trenger avklaring): Extra Optical "1-Day Acuvue" 30/90 (trolig
  Moist, ikke bekreftet), Clariti 1day Multifocal "3 Add" (mulig styrkevariant), prøvepakker
  (everclear 1/3/5 stk), SWATI/Lenson/Maxab linseetui (passer ikke i noen kategori),
  Opti-Free PureMoist uten størrelse (Apotekhjem 90569), HYLO Evo Tears (usikker om det er
  samme som EvoTears), samt reseptbelagte/legemiddel-produkter i Apotekhjem-feeden.

- **Oppfølging samme dag (2026-09-26): usikre rader avklart, ny kategori, søk.** GTIN
  (`identifiers.ean` / `fields.gtin` i Tradedoubler, `gtin`-kolonnen i CSV-feedene) er nå brukt
  som *bevis* for matching, aldri som eneste kriterium: lik GTIN på tvers av forhandlere =
  sterkt bevis for samme produkt (brukt for S4N HYLO Evo Tears = EvoTears 3 ml, S4N ReNu 360 ml,
  Apotekhjem Opti-Free PureMoist 300 ml). **Ulik GTIN beviser IKKE ulikt produkt** -- J&J har
  flere GTIN-er per pakning, og Extra Optical har kopierte/feil GTIN-er mellom ulike produkter
  (MyDay Toric/Biomedics Extra Toric osv. -- selve URL/beskrivelse/pris er riktig, kun GTIN/
  tittel er kopiert). Bruk derfor aldri Extra Optical-GTIN til matching.
- Egen tilbehørskategori `/tilbehor/` ("Etui og hjelpemidler") i `SOLUTION_CATEGORIES`
  (SWATI Lens Case & Tweezers, Ezy-Drop). Lenson sine egne etuier (Lenson Lens Case 1/3/6 stk,
  Maxab Frog/Pig/Pink/Blue) og Extra Optical sine linsecover er bevisst ikke med (kun én
  forhandler hver, ingen prissammenligning). Drop-it (saltvann, engangspipetter) er
  øyedråper, ikke tilbehør. Clariti 1 day Multifocal 3 Add 30-pack er eget produkt (egen EAN,
  ikke samme som Clariti Multifocal). Extra Optical "1-Day Acuvue" (uten Moist) er IKKE lagt til:
  egen listing/beskrivelse, kun én forhandler.
- Søket (forside og guider) dekker nå også linsevæske, øyedråper og tilbehør
  (`build_search_index(..., solutions=...)`, søkeord med og uten æøå). Placeholder er uendret.

- **Fyndiq vurdert og avslått (2026-09-26).** Kai er godkjent publisher (Tradedoubler), men
  Fyndiq er en markedsplass med tredjepartsselgere. Stikkprøve på 12 produktsider i
  tilbehørsdelen: selgernavn som Duuegrohoot, HHAO, AcserGery, Haokai, YINNYUN, HaiAn,
  YH Trading, Bravix Shop; typisk anonyme markedsplass-selgere, leveringstid opp mot 2-3 uker,
  ingen produsentinfo. Det ene merkeproduktet (B+L Sensitive Eyes Plus 355 ml) selges av
  "DJANGO AND COCO" med en fransk "ansvarlig person" (Outlook-adresse) og uten produsentinfo;
  ekthet kan ikke bekreftes. Beslutning (Kai): la det ligge. Fyndiq sitt /s/ (søk) er også
  Disallow i robots.txt, så ingen skraping. Ta ikke opp igjen uten at Kai ber om det.

- **Ny hero på forsiden (2026-09-26, Concept 1).** Kompakt lyst hero-kort (ca. 340 px) med søkefeltet som hovedelement (2 px blå kant, blå Søk-knapp) og hero-bilde som fader inn fra høyre (CSS-maske). Bildet ligger som beskårne, responsive WebP-varianter i `static/hero/eye-{560,840,1120}.webp` (12/21/30 KB; originalen serveres ikke), lastes kun på desktop (`<picture>` med `media="(min-width: 1024px)"`, `img` har en 1x1 data-URI så mobil ikke laster noe) og preloades med `fetchpriority=high`. Det gamle Unsplash-bildet og bildekreditten er fjernet. Tekst, kategorier, URL-er og søkefunksjon er uendret.

- **Nye kategorikort på forsiden (2026-09-26).** Fem pastellkort med fotorealistisk linse-bakgrunn (`static/categories/bg-{maaned,dag,toriske,fargede,multifokale}-{320,613}.webp`, 1-11 KB hver, beskåret fra kundens illustrasjonsark). `<img loading=lazy>` med srcset, så bildene ikke påvirker LCP (skjult desktop-/mobilkopi laster ingenting). Linsen skaleres med kortbredden og er forankret nede til høyre med maske mot venstre/opp og en pastell-tåke (`::before`) bak teksten. Desktop: 5 i rad, pil vises ved hover; mobil: kompakte rader (ca. 76 px) med liten pil. Tekst, ikoner (inline SVG), lenker uendret.

## Serie-sider styrket: søkeindeks, FAQ-innhold, visuell opprydning (2026-09-27)

Fulgte opp funnet om at serie-siden (`/serie/{slug}/`) manglet nesten all intern
lenking (kun fra produktsiden + private label-siden, se 2026-09-18-notatet lenger
opp om "Oppdaget - ikke indeksert"). Kai ba om tre ting samtidig:

- **Søkeindeksen** (`build_search_index()`) tar nå en `families`-liste -- alle 49
  serie-sider (28 ekte familier + 21 kjede-varianter) er søkbare fra forsiden og
  guidene ("Biofinity serie" -> treffer `/serie/biofinity/`). Listen beregnes
  tidlig i `generate_pages.py` sin `build()` (før forsiden rendres, siden den også
  trenger den til sin egen innebygde indeks) -- bevisst en lett, egen kopi av
  familie-/kjede-grupperings-logikken (samme prinsipp: korteste slug = base-
  varianten), IKKE samme kode som selve HTML-bygget lenger nede i filen.
- **Nytt FAQ-innhold** (`_render_faq_block()`, egen `<script>`-tag, samme mønster
  som resten av siden -- IKKE slått sammen i samme `@graph` som
  BreadcrumbList/CollectionPage-schemaet), utledet fra de faktiske radene i
  tabellen -- ALDRI en påstand vi ikke kan bevise fra dataen: hvilke typer/
  pakningsstørrelser finnes, hva som er billigst, og (kun når SAMTLIGE varianter
  faktisk deler materiale) at materialet er likt på tvers av serien.
- **Visuell opprydning:** heroen bruker nå samme `HERO_IMAGE_STYLE`/`hero-card`-
  mønster som lens-/tilbehør-/private label-sidene (representativt produktbilde --
  første medlem med et lisensiert bilde, samme prioritering som `_product_image()`),
  i stedet for den gamle tekst-only `.hero`. Sammenligningstabellen ligger nå i et
  hvitt kort (`.spec-table-card`, samme skygge/kant som resten av siden) med et
  lite produktbilde per rad.

## Søkefelt i toppmenyen på alle sider unntatt forsiden (2026-09-27)

Kai sitt eksplisitte ønske: søkefelt oppe til høyre i menylinjen på alle sider
UNNTATT forsiden (som beholder sin egen, store hero-søkeboks), samme høyde som
menyteksten ("bokstavene i søkefeltet i lik høyde som bokstavene i menyen"), og
en mindre logo (var 30/32 px, ble oppfattet som fortsatt for stor).

- `TOPBAR_HTML` er nå bygget av en funksjon `_topbar_html(show_search=True)` i
  stedet for én fast streng -- to konstanter, `TOPBAR_HTML` (med søk, 18 av 19
  bruksstedene) og `TOPBAR_HTML_NO_SEARCH` (kun forsiden). **Viktig rekkefølge-
  fallgruve:** selve kallet (`TOPBAR_HTML = _topbar_html()`) må stå ETTER at
  `LENS_SEARCH_STYLE`/`LENS_SEARCH_JS` er definert lenger ned i filen (funksjonen
  refererer til dem) -- å bygge konstantene rett ved siden av funksjonsdefinisjonen
  (der TOPBAR_HTML historisk har ligget) gir `NameError` ved import, fanget under
  testing før push.
- Selve søkeboksen bruker BEVISST de samme klassenavnene
  (search-row/search-input/search-icon/search-btn/search-suggestions) som
  forsidens/guide-sidenes søk -- fungerer med den eksisterende `LENS_SEARCH_JS`
  uten en eneste ny linje JS-logikk, kun en mer spesifikk CSS-overstyring
  (`.topbar-search .search-input`, skriftstørrelse 0.95rem -- identisk med
  `.nav-trigger` -- gir samme høyde, 34-35px, verifisert i nettleseren).
- Siden `LENS_SEARCH_STYLE`/`LENS_SEARCH_JS` nå ALLTID følger med `TOPBAR_HTML`
  på hver eneste side, er de doble kopiene som lå direkte i forsiden og
  guide-malen fjernet (de kjørte tidligere IIFE-en to ganger på samme side,
  som ville dobbeltbundet event-lyttere på egne søkefelt der -- ikke en feil
  som var synlig, men unødvendig duplisering fjernet i samme slengen).
- Logo: 30px -> 24px (mobil), og en glemt `@media (min-width: 640px)`-overstyring
  som satte den tilbake til 32px ble også funnet og redusert til 26px -- uten den
  andre endringen hadde ikke reduksjonen hatt noen synlig effekt på desktop i det
  hele tatt.
- Mobil (<700px): søkeboksen faller ned til egen fullbredde-rad under menyen
  (`flex: 1 1 100%`), ingen egen hamburger-meny å ta hensyn til siden toppmenyen
  allerede bryter linje ved behov.

## To fikser samme dag: søkefeltets plassering og logo/Hjem-justering (2026-09-27)

- **Søkeboksens gap:** `margin-left: auto` ga et unaturlig stort tomrom mellom
  «Guider» og søkefeltet (brukeren så det live og reagerte). Byttet til
  `flex: 1 1 220px` -- boksen følger nå normal flyt rett etter «Guider» med
  samme `gap: 32px` som resten av `.topbar`, og strekker seg selv (flex-grow)
  til kanten av headeren i stedet for å bli dyttet dit av en stor venstre-margin.
- **Logo ikke rett over «Hjem»:** reell layout-bug, ikke noe nytt fra
  søkefelt-arbeidet -- `.topbar` sin desktop-bredde (1200px) og `.wrap-product`
  sin (1280px, satt bredere spesifikt for produktsidens brede hero-layout,
  se eldre notat) hadde driftet fra hverandre. Ved akkurat 1280px viewport-
  bredde bruker `.wrap-product` HELE bredden (ingen auto-margin å sentrere
  med), mens `.topbar` fortsatt sentreres i sine 1200px -- logoen endte
  dermed lenger inn enn "Hjem"-brødsmulen. Luket ut ved å gjøre
  `.topbar`/`.footer-inner`/`.footer-disclosure`/`.footer-bottom` OG
  `.wrap-wide` like brede som `.wrap-product` (alle 1280px ved ≥1024px) --
  én felles desktop-bredde i stedet for tre som kunne drifte fra hverandre.
  Verifisert: logo og brødsmule starter nå på nøyaktig samme x-posisjon på
  både produktserie- og kategorisider.

## Serie-siden bygget videre: premium banner, "Finn din variant", prisinnsikt for hele serien (2026-09-27)

Kai sendte et nytt, generisk premium-bilde (dråper/linser i vann) til bruk som ETT
delt toppbanner for alle 49 serie-sider, og presiserte et viktig designprinsipp:
"blir det for mye linser hvis vi også har linser i bokser under?" -- løsningen er å
IKKE finne opp en tredje type linsebilde. Siden har nå bevisst kun to bildespråk:
(1) det nye banneret, ett delt bilde for alle serier (`static/hero/serie-{560,840,1120}.webp`,
samme beskjærings-/fade-teknikk som forsidens hero), og (2) ekte pakningsbilder,
gjenbrukt fra kategorikortenes egne pastellbilder i "Finn din variant" (IKKE nye
foto) og fra `_product_image()` i selve sammenligningstabellen.

- **`.serie-hero`** (egne klassenavn, IKKE `.hero-card`/`HERO_IMAGE_STYLE` som
  produkt-/tilbehør-/private label-sidene bruker -- det mønsteret er nå bevisst
  forbeholdt et faktisk produktbilde, ikke et generisk banner) -- kompakt kort,
  bildet fader inn fra høyre (samme CSS-maske-teknikk som forsiden), med en ny
  nøkkeltall-rad (`.serie-stat-pills`: antall produkter+pakninger, behov/typer,
  materiale og vanninnhold -- KUN vist når verdien faktisk er lik på tvers av
  alle variantene, aldri en "teknologi"-påstand siden specs ikke har et slikt
  felt konsekvent).
- **"Finn din variant"** (`.variant-card`): én kandidat-kort per BEHOV
  (kategori) familien faktisk dekker, ikke per pakningsstørrelse. Miniatyrbildet
  er `static/categories/bg-{maaned,dag,toriske,fargede,multifokale}-320.webp` --
  valgt ut fra radens EKTE `category_slug` (Acuvue Moist sin astigmatisme-
  variant er faktisk kategorisert "toriske-linser", ikke "dagslinser", selv om
  søsteren uten astigmatisme er en dagslinse -- bekreftet i katalogdata før
  antatt). Reseptpåminnelse-boks under, samme "sjekk mot din egen resept"-tone
  som resten av siden.
- **Prisinnsikt for HELE serien** (`render_family_price_insight()` +
  `_family_price_insight_data()` i render_templates.py) -- Kai sitt eksplisitte
  krav 2026-09-27: "prisinnsikt skal gjelde gjennomsnitt for serien, ikke 1
  produkt", en innsikt han mener ingen konkurrent har. Slår sammen
  prishistorikken til ALLE medlemmer med SAMME pakningsstørrelse til én
  gjennomsnittlig serie-pris per dag (ulike pakningsstørrelser er ikke
  sammenlignbare i kroner, derfor gruppert per størrelse). Én fane per
  pakningsstørrelse familien faktisk har (`.insight-tabs`, ren CSS/JS-visning,
  begge/alle paneler ferdigbygget i DOM-en -- ingen klientside-utregning);
  familier med kun én pakningsstørrelse får ingen faner, bare det ene panelet.
  **Ærlighetsprinsipp, samme som resten av siden:** ALDRI en fast "30 dager"/
  "90 dager"-påstand -- teksten sier "N dagers snitt/laveste/høyeste" der N er
  faktisk antall dagsrader (44-45 i dag, siden historikk startet 2026-08-14),
  vokser av seg selv etter hvert. Samme 7-dagers minimumsterskel som selve
  grafen. Kun dager der minst ett medlem faktisk har en registrert pris tas med.
  Fargebruk følger den faste regelen (mint = besparelse): prisen UNDER snittet
  akkurat nå farges mint (grønt), over snittet farges coral -- ALDRI omvendt.
- **`_render_price_history_chart()`** flyttet fra render_product_page sin egen
  `<style>` til `SHARED_STYLE` (brukes nå av to sidetyper), fikk et nytt
  `show_heading`-flagg (skjuler sin egen "Prisutvikling"-overskrift når den
  vises inni prisinnsikt-panelet, som har sin egen), og tåler nå historikk-
  rader UTEN `store`-felt (serie-snittet har ingen enkelt butikk å vise i
  tooltip-en, viser "snitt for serien" i stedet).
- **Ikke bygget denne runden** (bevisst neste steg, ikke glemt): samme
  prisinnsikt-panel på selve enkelt-produktsidene (erstatter dagens rene graf)
  -- funksjonen er skrevet generisk nok til å gjenbrukes der, men selve
  utrullingen er ikke gjort. Heller ikke et globalt 30/90-valg som bytter HELE
  siden samtidig (Kai nevnte dette som en idé for videre -- prisinnsikt-fanen
  er foreløpig det eneste elementet en pakningsstørrelse-veksling styrer).

## Serie-siden: layout-runde 2 -- rekkefølge, kompresjon, ekte tabell, gjenbrukte komponenter (2026-09-27)

Rett etter forrige runde ga Kai konkret tilbakemelding på selve resultatet (skjermbilder av
det faktiske Prisinnsikt-panelet og et mockup-bilde av "Alle produkter"/"Sammenlign
variantene"/"Relevante guider"):

- **Nøkkeltall-pillene** flyttet UT av `.serie-hero-content` (som er begrenset til 56 %
  bredde på desktop) til en egen rad rett i `.serie-hero`, som bruker HELE kortbredden --
  alle 4 pillene får nå plass på én linje (`flex-wrap: nowrap` ved ≥860px), i stedet for å
  brekke til to rader.
- **"Vi sammenligner priser ..."-boksen flyttet ned** til RETT ETTER Prisinnsikt/"Kort om
  X" (var rett under heroen).
- **Reell bug fikset: 90-pakning-fanen i Prisinnsikt manglet fylt areal i grafen.**
  Årsak: `.price-history-area { fill: url(#priceHistoryFade); }` var en DELT CSS-regel med
  en FAST id -- fungerte fint så lenge en side aldri hadde mer enn ÉN graf, men
  Prisinnsikt-panelet har nå flere (én per pakningsstørrelse), og alle pekte til samme
  (første) gradient i dokumentet. Fikset ved å sette `fill` INLINE per `<path>`
  (`_render_price_history_chart()` fikk et `gradient_id`-parameter, unik per kall
  -- `f"priceHistoryFade-{{pack_size}}"` på serie-siden) i stedet for å stole på en delt
  CSS-regel med hardkodet id.
- **Ny "Kort om X"-boks** ved siden av Prisinnsikt (`.serie-insight-row`, 2 kolonner ved
  ≥1024px) -- "slik at vi får en komprimert prisinnsikt, det holder" (Kai). KUN fakta som
  faktisk er like på tvers av ALLE variantene (Brukstid, materiale, vanninnhold, UV-filter
  -- hver enkelt utelates helt om verdien ikke finnes/ikke er lik for alle, samme prinsipp
  som resten av siden. UV-filter-feltet finnes typisk IKKE i det hele tatt for en gitt
  familie -- vises da ikke, ingen påstand vi ikke kan bevise).
- **Sammenlign-tabellen bygget om**: én rad PER BEHOV (ikke per pakningsstørrelse lenger),
  med Diameter og en forenklet "ADD/CYL/AXIS"-kolonne (viser HVILKEN ekstra dimensjon som
  gjelder -- "CYL/AXIS" eller "ADD" -- ikke tallverdiene, samme forenkling som Kai sin
  egen mockup) lagt til som nye kolonner utledet fra ekte specs-felt
  (`Diameter`/`Sylinder`/`Akse`/`Addisjon` -- sjeldne felt, kun 4-16 av 141 produkter har
  dem, kolonnene utelates derfor helt for familier uten noen dekning). "Pakninger" viser nå
  begge pakningsstørrelsene i én celle ("30/90"). BC/diameter/materiale antas likt på tvers
  av pakningsstørrelser innenfor SAMME behov (representant-raden sine spec-verdier brukes).
- **"Alle produkter i X-serien"-rutenett lagt til**, men BEVISST med den EKSISTERENDE
  `_render_product_tile()`-komponenten (samme kort som kategori-/merke-/tilbehør-sidene
  allerede bruker) -- Kai eksplisitt: "ikke likt disse [mockupens kortdesign], men de som
  vi bruker selv og har i dag."
- **"Relevante guider"-rutenett lagt til** med `render_guide_tile()`/`GUIDE_TILE_STYLE`
  (samme ikonkort som forsiden/toppmenyens guide-seksjon) -- guidene har KUN ikoner i vår
  datamodell, ingen egne foto; ingen bilder funnet opp for å matche mockupen. 3 relevante
  guider velges automatisk per familie (alltid "Slik bruker du kontaktlinser" + "Slik
  velger du riktig linse", pluss astigmatisme/multifokal/dagslinse-vs-månedslinse alt etter
  hvilke behov familien faktisk dekker).
- Luftet inn tettere (`.variant-finder-*`-marginer/gap redusert) etter Kai sin
  "litt mer komprimert, er litt mye luft"-tilbakemelding.

## Produktside: skjult antalls-fallback, flyttet seriekobling (2026-09-27)

Kai ba om å rydde opp visuelt på produktsiden (PC), men ba EKSPLISITT om å sjekke
implementasjonen først: er `.qty-static-fallback`-avsnittet ("Ved 2 esker: billigst hos
X...") der av en grunn (SEO/strukturert data/tilgjengelighet) før noe fjernes. Svaret,
rett fra `render_winner_widget()` sin egen docstring: JA -- det er en bevisst JS-fri
fallback for AI-crawlere uten JavaScript (GPTBot/ClaudeBot/PerplexityBot m.fl.), som
ellers aldri ville sett 2/4/10-eksemplene (kun tilgjengelig via `_QTY_CALC_SCRIPT`).
**Løsning (Kai sitt "alternativ 1"): visuelt skjult, ikke fjernet.** Standard
"visually hidden"-CSS (klippet til 1×1px, ikke `display:none`) -- avsnittet ligger
fortsatt i HTML-kilden og leses av crawlere/skjermlesere, men vises ikke for seende
brukere (samme info er uansett ett klikk unna i selve velgeren, altså ikke skjult/
villedende tekst i Googles forstand).

Samtidig flyttet `pack_size_callout`/`family_callout` ("Finnes også i X-pakning" / "Se
hele X-serien") fra rett under antallsvelgeren til RETT UNDER "Prisutvikling"
(`price_history_html`) på selve produktsiden -- kun her, private label-/serie-sidene har
ingen prisgraf å plassere den i forhold til.

**Åpent, ikke startet:** Kai ønsker en bredere opprydning av produktsiden (mobil og
desktop), inspirert av lenspricer.no sin produktside ("kompakt og rett på sak") -- ingen
konkret plan laget ennå, kun disse to punktvise endringene er gjort.

## Rettelse samme dag: fra "usynlig fallback-tekst" til ekte <details>-rad (2026-09-27)

Kai fikk (fra en annen AI-samtale) en presis, kildesjekket korreksjon på "alternativ 1"
over -- sjekket begge påstandene selv mot primærkildene før noe ble endret (samme
prinsipp som feedback-verify-before-citing i minnet):
- Googles egne spam-retningslinjer (developers.google.com/search/docs/essentials/
  spam-policies) lister EKSPLISITT "Using CSS to position text off-screen" som et
  eksempel på skjult tekst/lenke-misbruk -- men sier like eksplisitt at "Accordion or
  tabbed content that toggle between hiding and showing additional content" IKKE
  bryter retningslinjene. Bekreftet ved faktisk å lese siden, ikke tatt på tro.
- OpenAI sin egen bot-dokumentasjon (developers.openai.com/api/docs/bots) bekrefter:
  GPTBot = krabber til modelltrening, OAI-SearchBot = det som faktisk kan sitere siden
  i et ChatGPT-søkesvar. Sjekket samtidig vår egen robots.txt: GPTBot er `Disallow: /`
  hos oss (2026-09-10-vedtaket), OAI-SearchBot er `Allow: /` -- den forrige kode-
  kommentaren siterte altså en bot som aldri når siden i utgangspunktet.
- **Løsning:** `.qty-static-fallback` (CSS-utenfor-skjerm) er fjernet. Erstattet med et
  ekte `<details class="qty-multi">`-element ("Pris ved flere esker" + kompakt
  2/4/10-forhåndsvisning i selve `<summary>`, butikk+frakt-detaljer i den utvidbare
  kroppen) -- krever ingen JavaScript for å åpnes, samme data som før, men nå en
  legitim UX-mekanisme i stedet for skjult tekst. Erstatter samtidig den gamle
  "💡 Tips: billigste butikk kan endre seg..."-linja, som ikke lenger trengs når
  antallsraden selv viser eksemplet.

## Serie-siden: rekkefolge, bildekort for guider, Felles for hele serien (2026-09-27)

- "Alle produkter i X-serien" flyttet OVER "Sammenlign variantene" (var under).
- "Relevante guider" er na bildekort i stedet for rene ikon-kort -- gjenbruker
  kategorikortenes egne pastellbilder (`static/categories/bg-*`, samme filer som
  "Finn din variant") siden guidene ikke har egne foto i datamodellen. Bildet
  matcher IKKE nodvendigvis guidens eget tema (Kai bekreftet dette er greit,
  2026-09-27: "ikke nodvendigvis samme tema og tekst, men ser mye bedre ut") --
  koblet der det er naturlig (astigmatisme-guide -> toriske-bildet) og ellers en
  fornuftig standardvariant.
- Ny "Felles for hele serien"-seksjon (ikon-rutenett, ved siden av Relevante
  guider nederst) -- samme `fact_rows`-datagrunnlag som "Kort om X" (ved
  Prisinnsikt lenger opp), na delt mellom TO rendringer (sjekkliste og
  ikon-rutenett) med ulik visuell rolle pa samme side -- bevisst overlapp,
  ikke en feil.

## Serie-siden: FAQ-regelmotor -- gruppert accordion i stedet for 3 faste spørsmål (2026-09-27)

Kai fikk (fra en annen AI-samtale) et forslag om å bygge serie-sidens FAQ som en
regelmotor: spørsmålene genereres KUN fra fakta vi faktisk har for akkurat DEN
familien, aldri fylt opp til et fast antall ("en serie kan ha 5 gode spørsmål og en
annen 11, det er helt greit"), gruppert i "Produkt og varianter · Spesifikasjoner ·
Pris og butikker" og vist som en ekte, kollapset accordion i stedet for alt synlig på
en gang. Forslaget påsto også at Google droppet FAQ-rich-resultatet i søk for flere år
siden -- sjekket direkte mot developers.google.com/search/updates før noe ble bygget
(samme "verifiser før du siterer"-prinsipp som resten av økta): bekreftet, med
overskriftene "Removing documentation for the FAQ rich result feature" og "Deprecating
the FAQ rich result feature". FAQ-en sin reelle verdi er derfor IKKE lenger et rikt
SERP-utfall, men informasjonsinnhold for AI-siteringer (OAI-SearchBot m.fl.) og
long-tail-søk.

**Implementert i `render_family_page()`:** tre lister (`faq_produkt`/`faq_spec`/
`faq_pris`) bygges betinget fra data som allerede finnes på siden (ingen ny research-
kilde) -- eksisterende 3 spørsmål (varianter/pakninger, billigst, samme materiale) pluss
nye, alle betinget på faktisk data:
- "Finnes X for astigmatisme/multifokal?" -- betinget på at kategorien
  (`by_category["toriske-linser"]`/`"multifokale-linser"`) faktisk finnes, IKKE på om
  CYL/AXIS/ADD-tallfelt finnes i specs (funnet under bygging: Dailies Total1 sin
  astigmatisme-variant mangler CYL/AXIS i specs-dataen selv om den er reelt torisk --
  svaret tilpasser ordlyden til om de konkrete tallverdiene faktisk finnes eller ej).
- "Har alle variantene samme BC/diameter?" -- ekte sammenligning, svarer ærlig om
  verdiene er like ELLER ulike (aldri bare "ja" uten å sjekke).
- "Hva betyr CYL/AXIS/ADD?" -- generisk optikk-forklaring (etablert fagterminologi,
  IKKE produsentspesifikke materialnavn som LACREON/Etafilcon A -- se under).
- "Hos hvor mange butikker kan jeg kjøpe X?" -- ekte antall unike forhandlere på tvers
  av alle familiens produkter.
- "Lønner det seg å kjøpe stor fremfor liten pakning?" -- ekte pris-per-linse-
  sammenligning mellom minste og største pakning INNENFOR samme behov (torisk mot
  torisk, ikke mot sfærisk), kun vist ved reell forskjell (≥0,3 kr/linse).
- "Endrer billigste butikk seg med antall?" -- gjenbruker samme total-for-qty-logikk
  som "Pris ved flere esker" (produktpris × antall + beregnet frakt), sjekker 1 vs. 4
  esker for familiens billigste variant.

Bevisst UTELATT: "Hvor ofte oppdateres prisene?" (identisk svar for alle familier,
gir ingen serie-spesifikk info) og materialglossar (LACREON/Etafilcon A) -- krever en
egen, research-basert ordliste over produsentenes materialnavn vi ikke har strukturert
data for ennå, flagget som en fremtidig oppgave.

**Rendring:** ny `_render_family_faq_accordion()` (egen funksjon, IKKE en endring av
`_render_faq_block()` som fortsatt brukes uendret på produkt-/forside-FAQ) -- bygger
tre `<div class="faq-category">`-grupper (tomme kategorier utelates helt), hver med
`<details class="faq-accordion-item">` per spørsmål (kollapset som standard, samme
Google-verifiserte <details>-mønster som "Pris ved flere esker"). FAQPage-schema bygges
fra AKKURAT samme spørsmål/svar-liste som vises, flatet ut på tvers av kategoriene.
Testet på tvers av familier med ulik datarikdom: 6-10 spørsmål avhengig av hvor mye
familien faktisk har av toriske/multifokale varianter, flere pakningsstørrelser,
UV-filter osv. -- aldri et fast antall.

## /guider/: ekte foto på 20 av 40 guide-kort + toppbanner (2026-09-27)

Kai sendte to sammensatte referansebilder (60 + 15 AI-genererte stockfoto-ruter, ikke
egne filer per bilde) og ba om bilder på guide-kortene på `/guider/`. Siden filene ikke
kom separat, ble rutenettene beskåret programmatisk: fant gutter/hvite linjer mellom
rutene (numpy row/col-gjennomsnitt), kuttet ut hver rute til egen fil.

**Kun 20 av 40 guider fikk foto** (`GUIDE_PHOTOS`-dict i `render_templates.py`, rett
over `GUIDE_TILE_STYLE`) -- de resterende 20 (spec-forklaringer som bc-forklart/
cyl-forklart/add-forklart, pris-/abonnement-guider, resept-guider, produksjon/historie,
terapeutiske linser, merkebytte) beholder ikonkortet, samme "aldri tving et bilde som
ikke faktisk passer"-prinsipp som resten av siden. Matchingen er gjort på faktisk
motiv (f.eks. håndvask -> ikke brukt til hygiene siden vi ikke har en egen
hygiene-guide, men lenseveske+håndkle -> vedlikehold-av-kontaktlinser; sovende kvinne
-> kan-man-sove-med-kontaktlinser; Snellen synstavle -> uklart-syn-med-kontaktlinser;
stablede esker -> pakningsstorrelse-30-vs-90), ikke tvunget for guider uten et
naturlig motiv.

**Kvalitetsavveining, sagt rett ut:** kildebildet er kun 1536x1024px sammensatt over
60 ruter, så hver rute ble beskåret til ca. 145x150px og skalert opp til 640px bredde
(`static/guides/{slug}.webp`) -- akseptabelt for et lite kort i et rutenett, men
merkbart mykere enn en ekte høyoppløst original. Bytt ut med skarpere filer hvis Kai
får tak i de individuelle originalene.

`render_guide_tile()` grener nå på om slugen finnes i `GUIDE_PHOTOS`: foto-variant
gjenbruker `.guide-photo-card`-klassenavnene fra serie-siden sin "Relevante
guider" (egen CSS-kopi i `GUIDE_TILE_STYLE`, IKKE delt konstant med
`render_family_page()`, for å ikke røre en allerede utgitt komponent), ellers samme
ikonkort som før. Samme funksjon brukes uendret av BÅDE `/guider/`-oversikten og
forsidens guide-forhåndsvisning, så begge steder får det samme blandede
foto-/ikon-rutenettet automatisk.

**Toppbanner på `/guider/`:** kun selve fotostripen fra det ene referansebildet (viste
seg å være ren, uten påskrevet tekst -- ulikt den fulle mockupen Kai også sendte, som
HAR påskrevet tittel/fiktive kategorikort og derfor ikke ble brukt). Bildet er svært
panoramisk (~4,9:1), så det er IKKE bygget som en side-panel slik `serie-hero` er,
men som en full-bredde bannerstripe over `.hero`-teksten
(`static/hero/guider-{560,840,1120,1536}.webp`, `object-fit:cover` med økende
høyde per breakpoint).

## Guide-bilder runde 2: alle 40 guider, tekst oppå banneret, bilde på selve artikkelen (2026-09-27)

Rett etter forrige runde ba Kai om tre ting til, i samme økt:

1. **"En rekke guider har ikke fått bilder enda ... kan du fikse?"** -- utvidet
   `GUIDE_PHOTOS` fra 20 til ALLE 40 guider. De siste 20 (spec-forklaringer
   bc/dia/pwr-sph/cyl/axis/add-forklart, pris-/abonnement-/resept-guider,
   historie/produksjon/terapeutiske linser) fikk IKKE et bilde som faktisk
   illustrerer noe spesifikt i akkurat den guiden -- det finnes rett og slett
   ikke et treffende motiv i bildeutvalget for "hva koster kontaktlinser"
   eller "AXIS forklart". De fikk i stedet et generisk, men ekte og relevant
   øye-/linse-bilde (forskjellige bilder per guide, ingen gjenbruk), fremfor
   å la 20 guider stå uten bilde. Sagt rett ut i koden (kommentaren over
   `GUIDE_PHOTOS`) hvilke som er ekte motiv-treff og hvilke som er generisk
   fyll -- viktig å ikke late som om alle 40 er like treffsikre.
2. **"Legg teksten oppå selve bildet"** -- `render_guides_index_page()` sin
   banner og tekst-hero er nå ÉN komponent (`.guide-hero`): bildet er
   bakgrunn, en lys venstre-til-høyre gradient (`.guide-hero-overlay`)
   sikrer lesbar mørk tekst oppå det (kildebildets venstre del er allerede
   lys/uskarpt, gradienten er et ekstra sikkerhetsnett), kicker/h1/ingress
   ligger i `.guide-hero-content` oppå. I MOTSETNING til `serie-hero-media`
   er bildet IKKE skjult på mobil -- Kai ville ha det synlig overalt, ikke
   bare ≥860px.
3. **"Bruk samme bilde på selve guiden også, på en fin måte"** --
   `render_guide_page()` fikk et nytt `.guide-hero-image` -- rent, avrundet
   toppbilde (190px mobil / 260px ≥640px, `object-fit:cover`) rett over
   `.hero`-teksten, samme fil som guide-kortet på `/guider/` og forsiden.
   Kun rendret når `GUIDE_PHOTOS.get(slug)` finnes (nå alltid sant, siden
   alle 40 har bilde), så koden degraderer pent den dagen en ny guide
   legges til uten eget bilde ennå.

## Guide-artikkelbilde: fra fullbredde banner til lite thumbnail (2026-09-27, samme dag)

Kai så det nye `.guide-hero-image`-fullbredde-banneret (punkt 3 over) live og
reagerte med skjermbilde: tok unødvendig stor plass, og et oppskalert bilde
(kilde kun ~145x150px, se runde 1) blir EKSTRA synlig/mykt jo større det
vises. Spurte hva som er "normalt".

Svar: samme prinsipp som `.hero-product-image` på produktsidene -- bilde ved
SIDEN av teksten, ikke et eget fullbredde element. Erstattet
`.guide-hero-image` med `.guide-hero-thumb`, et lite avrundet kvadrat
(68px mobil / 100px ≥640px) til høyre for kicker/h1/byline i `.hero-copy`
(ny `.guide-hero-row`-flex-klasse, `justify-content:space-between`). Løser
BEGGE problemene i samme endring: mindre plass, OG en nedskalering fra
640px-kilden til ~70-100px vises skarpt (motsatt av forrige runde sin
oppskalering til full bredde).

## Serie-siden: "Felles for hele serien" og "Relevante guider" som et matchende par (2026-09-27)

Kai pekte igjen på skjermbilde av bunn-raden (den samme han satte "på vent"
tidligere i økta): "Relevante guider" hadde ALDRI fått en hvit boks rundt
seg (bare bar overskrift + bildekort-rutenett rett på sidebakgrunnen),
mens "Felles for hele serien" har det -- pluss at høyden varierte fritt (3
bildekort med ekte foto blir naturlig høyere enn én rad ikon-fliser). Ba
om at de skulle bli "riktig proporsjonert i høyde, boks rundt etc ... så
det blir tilnærmet likt".

Fikset med tre grep, ingen ny HTML-struktur:
1. `.serie-guides` fikk samme kort-stil som `.serie-facts-tiles` (hvit bakgrunn,
   border, radius, skygge, samme h2-størrelse) -- var helt ustylet før.
2. `.serie-bottom-row` sin `align-items` gikk fra `start` til `stretch`, så
   begge boksene alltid får samme høyde (den høyeste av de to).
3. `.serie-facts-tiles` sitt innhold (kortere -- én rad fliser) sentreres nå
   vertikalt i den ledige plassen (`margin: auto` på fliserutenettet) i
   stedet for å henge øverst med et stort tomrom under -- ser dermed
   bevisst ut, ikke som en feil, uansett hvor mye høyere "Relevante guider"
   sin boks blir.

Fjernet samtidig en unødvendig `.guide-photo-grid`-brekkpunkt-kvirk (gikk
til 1 kolonne ved ≥900px, tilbake til 3 ved ≥1200px -- en rest fra før
boksen fikk fast bredde i to-kolonners raden) til bare "3 kolonner fra
640px og oppover", som stemmer bedre med den nye faste boks-bredden.

## Merke-sidene (/merke/{slug}/) fikk samme løft som serie-sidene (2026-09-27)

Kai: "https://kontaktlinser.no/merke/acuvue/ jeg tenker tilsvarende her også,
og ikke bare på serier" + en lang, pastet AI-samtale med et fullt forslag
("brand intelligence page" -- serie-navigasjon, sammenligningstabell på
tvers av serier, pris-intelligens, materialkunnskapsgraf, FAQ-regelmotor,
omorganisert katalog).

**Bygget** (ny `_brand_family_summary()` + utvidet `render_brand_page()`,
signatur endret til å ta imot `product_families` fra `generate_pages.py`):
- Stat-piller i heroen (produkter/serier/linsetyper), samme mønster som
  serie-siden sine, egne `brand-*`-klassenavn.
- "Utforsk {merke}-seriene" -- kort per ekte serie fra product_families.json
  (samme kuraterte data som `/serie/`-sidene, ingen ny datakilde), med
  bilde, behov, pakninger og fra-pris. Lenker til den ekte `/serie/`-siden.
- "{Merke} i korte trekk" -- ikon-fliser (produsent, produkter, linsetyper,
  materialer, "oppdateres daglig").
- "Slik skiller {merke}-seriene seg" -- sammenligningstabell PÅ TVERS av
  seriene (én rad per serie: bruk/materiale/vanninnhold/pakninger/fra pris),
  viser ærlig "–" der materiale/vanninnhold IKKE er likt på tvers av en
  series egne medlemmer (f.eks. Acuvue Oasys 1-Day with Hydraluxe sin
  material-kolonne), ingen gjetting.
- "{Merke}-priser akkurat nå" -- 3 pris-intelligens-tall (laveste pris,
  laveste pris per linse, antall butikker) regnet ut på tvers av HELE
  merkets produkter (også frittstående produkter uten egen serie).
- FAQ-regelmotor (gjenbruker `_render_family_faq_accordion()` fra
  serie-siden direkte, egen kategorisering "Merke og serier ·
  Spesifikasjoner · Pris og butikker") -- 4-9 spørsmål avhengig av faktisk
  data, samme "aldri fyll ut"-prinsipp.

**Adaptivt** (Kai sitt eget krav i forslaget): et merke uten noen ekte
serie (product_families.json har ingen familie med ≥2 av merkets produkter,
f.eks. FreshLook med kun 1 produkt) viser INGEN serie-navigasjon eller
sammenligningstabell -- testet eksplisitt, degraderer til stat-piller +
korte fakta + pris-intelligens + en kortere FAQ.

**Bevisst UTELATT** (dokumentert i funksjonens docstring også):
- "Materialer og teknologier"-seksjonen med "Les om materialet →"/"Hva
  betyr det? →"-lenker til egne materialsider (LACREON, HYDRACLEAR PLUS
  osv.) -- vi har ingen slike sider. Samme begrunnelse som
  materialglossaret som ble utelatt fra serie-siden sin FAQ samme dag.
- Full omorganisering av selve produktkatalogen (gruppert per serie med
  sorteringsvalg) -- den eksisterende flate rutenett+kategorifilter-
  løsningen (fungerende JS) er beholdt UENDRET, bare flyttet lenger ned
  under de nye seksjonene. Verifisert at kategorifilteret fortsatt
  fungerer etter flyttingen.
- Prishistorikk/trend for merket ("Acuvue-prisutvikling siste 90 dager") --
  mulig gjenbruk av `_family_price_insight_data()`-mønsteret senere, ikke
  bygget nå.

Testet: Acuvue (4 serier, 21 produkter, blandet materialdekning) og
FreshLook (0 serier, 1 produkt) -- begge bygger korrekt, FAQPage-schema
validert gyldig JSON på tvers av alle 30 merke-sider, ingen horisontal
overflow på mobil (375px) eller desktop.

## Merke-siden: samme toppbanner som serie, og finpuss mot serie sitt visuelle nivå (2026-09-27, samme dag)

Kai, rett etter forrige runde: "bruk toppbilde vi også bruker på serie her
på disse for å få det pent", og deretter "bruk serie som utgangspunkt til
hvordan merke siden også skal se ut. Du ser det er stor forskjell."

1. **Toppbanner**: `.hero` på BÅDE `render_brand_page()` og
   `render_private_label_brand_page()` erstattet med `.brand-hero` -- en
   bevisst 1:1-kopi av `.serie-hero` sitt mønster (samme delte bilde
   `static/hero/serie-{560,840,1120}.webp`, samme side-panel-med-fade-
   maske-teknikk, skjult under 860px). Egne `brand-hero-*`-klassenavn
   (samme begrunnelse som ellers: ikke kryss-avhengighet mellom sidetyper).
2. **Finpuss**: sammenlignet faktiske computed styles side om side mellom
   Acuvue (`/merke/`) og Dailies Total1 (`/serie/`) i nettleseren i stedet
   for å gjette -- fant at `<h1>` i `.brand-hero` IKKE hadde samme
   `clamp(1.5rem, 4vw, 2rem)`-begrensning som `.serie-hero h1`, og dermed
   rendret synlig større (35,2px mot 32px) enn seriesidens h1, selv om
   begge sidene bruker samme globale `<h1>`-basestil. Lagt til samme
   clamp-regel begge steder. Justerte samtidig `.brand-serie-card` sin
   `border-radius` fra 16px til 14px for å matche resten av kort-språket
   på siden (`.variant-card`/`.guide-photo-card` bruker begge 14px).

## Merke-siden: seriekort på én linje, prisintelligens ved siden av fakta (2026-09-27, samme dag)

Kai: "tenker acuvue seriene kan tilpasses en linje (på pc), og de andre
merkene også, så langt det lar seg gjøre... kompakt og fint er bra. Acuvue
i korte trekk? kan være ved siden av gjen.snitt priser som på serier. slik
at vi har det samme her som på serie."

1. **Seriekort → kompakt, horisontalt kort på én linje.** Erstattet det
   store vertikale bildekortet (bilde-øverst, 16:9) med samme kompakte
   mønster som `.variant-card` på serie-siden sin "Finn din variant" --
   lite kvadratisk produktbilde til venstre (42px), navn/behov/fra-pris til
   høyre, `text-overflow:ellipsis` på lange navn. `.brand-serie-grid` setter
   nå `grid-template-columns: repeat(var(--brand-serie-cols), 1fr)` ved
   ≥900px, der `--brand-serie-cols` er satt inline til `min(antall serier,
   6)` -- alle seriene havner dermed faktisk på én rad der det er plass,
   fremfor å stole på at en fast minmax-bredde tilfeldigvis går opp. Testet
   med Acuvue (4 serier) og Proclear (3) -- begge fyller raden pent.
2. **"{Merke} i korte trekk" ved siden av "{Merke}-priser akkurat nå".**
   Samme to-kolonners stretch-mønster som `.serie-insight-row`
   (Prisinnsikt + Kort om X på seriesiden) -- ny `.brand-insight-row`,
   `align-items: stretch` + `height:100%` på begge boksene slik at de alltid
   matcher hverandres høyde (verifisert likt i px i nettleseren). Prisintelligens-
   tallene fikk en egen ytre kortboks (`.brand-price-intel`, samme stil som
   `.brand-facts`) siden de tidligere var en bar rutenett+overskrift uten
   boks -- samme "boks rundt, tilnærmet likt"-prinsipp som ble brukt på
   "Felles for hele serien"/"Relevante guider"-fiksen tidligere i økta.

## Merke-siden: ekte prisinnsikt-graf (ikke stat-kort), og riktig plassering (2026-09-27, samme dag)

Kai så bilde av forrige runde og spurte rett ut: "hvor er grafen og
prisene? og Acuvue i korte trekk, skal se ut som på serien. d.v.s. begge
disse delene, da vi ønsker data, og unike data som kun kontaktlinser.no
skaffer." Deretter: "og den bør komme over Slik skiller Acuvue-seriene
seg."

De 3 flate "priser akkurat nå"-stat-kortene fra forrige runde var IKKE det
samme som seriesidens ekte Prisinnsikt (graf + trend + faner) -- luket helt
ut til fordel for den ekte komponenten:

- **Ekte graf**: `render_brand_page()` kaller nå `_family_price_insight_data()`
  og `render_family_price_insight()` -- SAMME funksjoner som serie-siden,
  uendret, bare kjørt på merkets `rows` (alle produkter, ikke bare de i en
  serie) i stedet for én families. `render_family_price_insight()` fikk en
  ny, bakoverkompatibel `scope_label`-parameter (default `"i serien"`,
  uendret for serie-siden) siden merke-siden sitt snitt er PÅ TVERS AV HELE
  MERKET, ikke én serie -- "4 varianter i serien" hadde vært direkte
  misvisende her, nå "4 varianter i Acuvue-sortimentet". Krevde at
  `render_brand_page()` fikk en ny `price_history`-parameter (tredd inn fra
  `generate_pages.py`, samme `price_history`-variabel som serie-sidene
  allerede bruker).
- **"Kort om {brand}" endret fra ikon-fliser til sjekkliste** -- Kai sitt
  "skal se ut som på serien" var presist: posisjonen ved siden av
  Prisinnsikt tilsvarer serie-siden sin "Kort om X" (sjekkliste med
  haker), IKKE "Felles for hele serien" sitt ikon-flise-rutenett (som
  brukes et ANNET sted på serie-siden). Ny `.brand-facts-list`, egen
  CSS-kopi av `.serie-facts-list`.
- **Pris per linse og antall butikker** (de to tallene fra de fjernede
  stat-kortene som IKKE dekkes av selve grafen) er flyttet INN i denne
  samme sjekklisten i stedet for en egen tredje boks -- Kai: "vi ønsker
  data, og unike data som kun kontaktlinser.no skaffer" -- fortsatt med,
  bare samlet på ett sted.
- **Rekkefølge**: prisinnsikt-raden flyttet over sammenligningstabellen
  (var under) -- Kai: "den bør komme over Slik skiller Acuvue-seriene seg".

Bekreftet i bygget: 26 av 30 merke-sider har nok prishistorikk (≥7 dager)
til å vise grafen, resten er private label-undermerker (Ascend/EasyVision/
EyeQ/iWear) som bruker en helt annen renderfunksjon uten denne seksjonen i
det hele tatt -- ingen ekte merkeside manglet grafen.

**Ikke avklart ennå**: Kai bemerket også "her mangler vi også mange
produkter" om Acuvue-siden. Bekreftet at 20 av 21 Acuvue-produkter er
dekket av en serie (kun Acuvue Vita 6-pack står utenfor, siden den ikke
tilhører noen kuratert familie i product_families.json) -- men den vises
fortsatt i den uendrede flate "Alle Acuvue-produkter"-listen nederst, så
ingenting mangler fra SIDEN. Uklart om Kai i stedet mener at selve
katalogen vår mangler ekte Acuvue-produkter som finnes i markedet (et
data-/feed-spørsmål, ikke en UI-sak) -- må avklares med Kai før noe gjøres
her.

**Oppklart samme dag:** Kai fulgte opp med "jeg tenkte på at jeg bare så 4
produkter her" -- altså IKKE et datahull, bare at sammenligningstabellen
("Slik skiller Acuvue-seriene seg") viste 4 RADER (én per serie) uten noe
som helst som gjorde det tydelig at hver rad faktisk representerer flere
produkter. Fikset med to grep: (1) ny "Produkter"-kolonne i selve tabellen
(`s["n_products"]` per serie -- 6/3/5/6 for Acuvue), (2) en ny lead-setning
over tabellen ("4 serier, til sammen 20 av 21 Acuvue-produkter. Ytterligere
1 produkt står utenfor disse seriene, se hele listen nederst." for Acuvue)
som eksplisitt viser BÅDE dekningen og at ett standalone-produkt (Acuvue
Vita) bevisst er utenfor enhver serie, i stedet for å late som det ikke
finnes. Rettet samtidig en entall/flertall-bug ("1 serier" -> "1 serie",
"1 produktserier" -> "1 produktserie") som ble synlig i samme slengen, for
merker med kun én serie (Precision1, Biotrue m.fl.).

## Merke-siden: nytt ekte toppbilde + faktabasert intro-setning (2026-09-27, samme dag)

Kai sendte en veldig lang, detaljert "Brand Intelligence Gold Standard"-brief
(22 faser, pastet fra en annen AI-samtale) for en full redesign av
/merke/acuvue/ som pilot, pluss et nytt, ekte heltbilde (kvinne med linse på
fingertuppen, lyst/uskarpt til venstre -- egnet for samme fade-side-panel-
teknikk som allerede er i bruk). Gitt omfanget (22 faser) ble IKKE alt bygget
i denne runden -- kun de konkrete, lavrisiko-delene som følger direkte av
brief sin Fase 1 (hero) ble gjort nå; resten venter på tilbakemelding (se
rapport gitt til Kai i samme runde, ikke gjentatt her).

- **Nytt delt merke-hero-bilde**: `static/hero/brand-{560,840,1120}.webp`
  (beskåret/optimalisert fra det medfølgende bildet), erstatter det
  gjenbrukte serie-hero-vannbildet i BÅDE `render_brand_page()` og
  `render_private_label_brand_page()` sin `.brand-hero-media`. Samme
  fade-maske-side-panel-teknikk som før, bare nytt bilde -- differensierer
  nå merke-sidene visuelt fra serie-sidene, som brief sin Fase 1 antydet.
- **Faktabasert intro-setning**: erstattet den generiske "Alle X-linser vi
  følger prisen på, sortert etter lavest pris" med en generert setning som
  faktisk sier noe om merket -- produsent, linsetyper, produkt-/serieantall,
  f.eks. "Acuvue er en linseserie fra Johnson & Johnson Vision med
  dagslinser, multifokale linser, månedslinser og toriske linser. Vi følger
  prisen på 21 produkter, fordelt på 4 serier, sortert etter lavest pris."
  Bygget fra data vi allerede har (ingen ny kilde), IKKE en hardkodet
  markedsføringstekst per merke -- degraderer korrekt for et
  ett-produkt-merke uten serier (testet mot FreshLook: "FreshLook er en
  linseserie fra Alcon med fargede linser. Vi følger prisen på 1 produkt,
  sortert etter lavest pris.").
- Økte samtidig `.brand-hero` sin padding noe (26/40/24px -> 40/44/36px)
  for å nærme seg brief sin ønskede hero-høyde (320-390px) -- landet på
  ca. 310px for Acuvue med den nye, lengre introteksten.

## Merke-siden: resten av "Gold Standard"-briefen bygget ("gjør alt") (2026-09-27, samme dag)

Kai svarte "gjør alt" på rapporten over, pluss et mockup-referansebilde med
beskjeden "ikke legg vekt på logo og toppbanner og meny etc" (den delen er
en fremtidig, separat oppgave -- IKKE rørt, per brief sitt eget forbud mot
å endre header/nav). Bygget resten av de gjenstående, datastøttede fasene:

- **Fase 2 (faktisk bygget om)**: de små pillene inni selve hero-kortet
  erstattet med en egen, mer synlig 4-korts rad RETT UNDER heroen
  (`.brand-facts-row`) -- produkter/serier/linsetyper/butikker -- matcher
  mockupen Kai sendte bedre enn de opprinnelige pillene.
- **Hero-CTA**: "Se alle {merke}-produkter →"-knapp i heroen, lenker til
  `#produkter` (selve produktlisten lenger ned, ikke en ny side).
- **Fase 7 -- "{Merke}-sortimentet forklart"**: ett kort per KATEGORI
  (ikke serie) med produktantall + hvilke serier som har den kategorien +
  en FUNGERENDE "Se X →"-lenke -- klikk kjører samme filter-rad som
  allerede fantes ved produktlisten (ny `applyBrandFilter()`-funksjon,
  gjenbrukt av både kategori-chipsene OG disse nye kortene, ikke
  duplisert logikk). Kun bygget hvis merket har MER ENN ÉN kategori.
- **Fase 11 -- "30 eller 90 linser?"**: ekte analyse på tvers av merket,
  parer 30-pack/90-pack av SAMME underliggende produkt via
  `_pack_size_from_id()` (samme funksjon som resten av siden allerede
  bruker, ikke en ny matching-mekanisme). Krever minst 2 robuste par før
  seksjonen bygges -- ett enkelt par hadde bare gjentatt tallet som
  allerede står i FAQ-en. For Acuvue: "7 av 7 sammenlignbare
  Acuvue-produkter har 90-pakningen lavere pris per linse enn tilsvarende
  30-pakning."
- **To ekstra intelligens-tall** i "Kort om {merke}"-sjekklisten (samme
  liste som før, bare utvidet): størst prisforskjell mellom butikker for
  ETT produkt (≥5 % terskel for å telle som reell), og hvilket produkt som
  har flest butikker.
- **Materialer i {merke}-sortimentet**: BEVISST kalt "Materialer", IKKE
  "Materialer og teknologier" med "Les om materialet →"-lenker --
  `Materiale`-feltet i specs er ÉN sammensatt streng ("Etafilcon A med
  LACREON-teknologi"), ikke to separat dokumenterte entiteter. Viser de
  fulle, ekte strengene som informative kort (hvilke serier som bruker
  hver), ingen splitting, ingen oppdiktede lenker -- direkte i tråd med
  brief sin egen Fase 9-fallback-regel. Kun bygget ved ≥2 distinkte
  materialer.

  **Viktig funn underveis**: `BRAND_CONTENT["acuvue"]` (en eksisterende,
  håndskrevet tekstblokk fra FØR denne økta, fortsatt vist nederst på
  siden) inneholder faktisk allerede ekte, dokumenterte forklaringer av
  LACREON/HYDRACLEAR PLUS/TearStable/OptiBlue som løpende tekst -- så et
  ordentlig Fase-9-kunnskapsgraf-kort FOR ACUVUE SPESIFIKT er trolig
  mulig, men krever at den prosaen omstruktureres til data (materiale +
  teknologinavn + kort forklaring som egne felt), ikke noe som bør
  parses ut med regex fra fritekst. Flagget til Kai, ikke gjort her.
- **Fase 13 -- "Nyttige ressurser"**: gjenbruker `render_guide_tile()`
  direkte (samme funksjon som `/guider/`/forsiden) -- siden alle 40
  guider nå har eget foto, blir dette alltid bildekort uten noen ny
  komponent. 3 guider valgt adaptivt (alltid "Hvordan velge
  kontaktlinser", pluss dagslinser-vs-månedslinser ELLER astigmatisme-
  ELLER multifokal-guiden avhengig av hva merket faktisk har, pluss
  "Hva betyr BC").
- **Fase 14 -- "Produsent"-modul**: kompakt boks, kun bygget ved kjent
  produsent-kobling, lenker til den eksisterende `/produsent/`-siden.
- **Fase 15 -- "Om informasjonen på denne siden"**: fire elementer,
  tekstene bevisst identiske med det som allerede står i disclosure-
  avsnittet (ingen nye/sterkere påstander) -- "oppdateres daglig", IKKE
  "flere ganger daglig" som brief sitt eget eksempel brukte, siden det
  ikke er noe vi kan dokumentere. Lenker til de tre eksisterende
  metodikk-/om oss-sidene.
- **Fase 16 (oppdateringsdatoer) -- BEVISST IKKE bygget**: brief ba om
  "Priser sist oppdatert i dag kl. HH:MM". `_verified_tag()` sin egen
  docstring dokumenterer at et KLOKKESLETT-basert ferskhet-krav ble
  fjernet tidligere i prosjektet nettopp fordi det ble feil hver gang
  noen leste en statisk side senere enn byggetidspunktet -- å legge det
  til igjen her ville gjeninnført akkurat den bug-en som allerede ble
  fikset. Utelatt, flagget til Kai.
- **Rekkefølge endret**: "Alle {merke}-produkter" flyttet opp (rett etter
  Prisinnsikt-raden, samme relative plassering som serie-siden sin egen
  "Alle produkter i X-serien"), resten av de nye seksjonene følger etter,
  trust-footeren helt nederst før footer.

Testet: alle 30 merke-sider (inkl. private label-undermerker) bygger med
gyldig JSON-LD, ingen `NameError`/f-string-bugs, adaptivt bekreftet mot
FreshLook (1 produkt, 0 serier -- sortiment/sammenligning/materialer/
30v90/seriekort utelates automatisk, resten vises), "Se X →"-filter-
lenkene fra sortimentet fungerer og scroller til riktig sted, ingen
horisontal overflow på mobil (375px) eller desktop (1280px).

**Ikke bygget** (flagget til Kai, ikke silent utelatt): et ordentlig
strukturert Fase-9-kunnskapsgraf (krever at BRAND_CONTENT sin frie tekst
omgjøres til data), Fase 16 sitt klokkeslett-baserte "sist oppdatert"
(bevisst utelatt, se over), og selve header/navigasjon-redesignet fra
mockupen (eksplisitt utenfor scope denne runden).

## Merke-siden: visuell finpuss mot mockupen ("gjør det nøyaktig slik, så nært som mulig med alt") (2026-09-27, samme dag)

Kai sendte mockup-bildet på nytt med "se på screenshot. vi er langt unna",
pekte på at Acuvue-logoen er fjernet i mockupen ("som er ok"), og avsluttet
med "gjør det nøyaktig slik, d.v.s. så nært som mulig med alt!" -- et
tydelig signal om at forrige runde var datamessig riktig, men visuelt for
langt fra referansen. Gjorde en ren visuell finpuss-runde (ingen ny data):

- **Logo fjernet fra heroen** (`brand_logo_block`/`.brand-hero-row` sin
  logo-del) -- bare kicker/H1/intro/CTA igjen, matcher mockupen sin rene
  hero uten egen merke-logo-badge.
- **Fargerike ikoner overalt** i stedet for ensfarget blått -- Fase-2-
  faktakortene og "Sortimentet forklart"-kortene bruker nå samme
  aksentfarge-rotasjon (mint/blue/lavender/amber/coral/sky) som resten av
  designsystemet allerede har (samme tokens som `GUIDE_ICONS` bruker).
  Nye ikoner lagt til for toriske linser (øye) og multifokale linser
  (person), gjenbrukte `SUN_ICON_SVG`/`CALENDAR_ICON_SVG`/`DROPLET_ICON_SVG`
  for de andre kategoriene.
- **Seriekortet bygget om fra kompakt ett-linje-kort til fullt vertikalt
  kort** (bilde øverst, grønn kategori-merkelapp, "Standard/Torisk/
  Multifokal"-piller utledet fra samme `type_labels` som resten av siden,
  antall+pris+pil nederst) -- reverserer det kompakte kortet fra tidligere
  samme dag, siden mockupen (nå den eksplisitte fasiten) viser det fulle
  kortet. `brand_series_variant_pills()` er ny, utleder pillene rent fra
  data (aldri en fast liste).
- **"{Merke} i tall" + "{Merke}-priser" erstatter "Kort om {merke}" +
  Prisinnsikt**: den forrige sjekklisten (produsent/linsetyper/materialer)
  er fjernet -- det innholdet dekkes nå uansett av Fase-2-raden,
  "Produsent"-modulen og "Materialer"-seksjonen, så ingenting gikk tapt.
  Erstattet med en fargerik stat-flise-boks (laveste pris, laveste pris per
  linse, størst prisforskjell, flest butikker, flest varianter -- samme
  robusthet-terskler som før) ved siden av selve prisgrafen.
  `render_family_price_insight()` fikk en ny, bakoverkompatibel
  `heading`-parameter (default uendret for serie-siden) slik at merke-siden
  kan si "Acuvue-priser" i stedet for "Prisinnsikt for Acuvue".
- **"Slik skiller seriene seg" + "Materialer i {merke}-sortimentet" side om
  side** (ny `.brand-compare-row`, uten tvunget lik høyde -- en tabell og
  et kortrutenett har naturlig ulik lengde, ikke et problem her).
- **FAQ i to kolonner** -- ren CSS-multikolonne (`column-count:2`,
  `break-inside:avoid` per kategori) scoped til en ny `.brand-faq-wrap`,
  IKKE en endring av `_render_family_faq_accordion()` sin delte HTML (den
  brukes uendret av serie-siden, som fortsatt skal være én kolonne).

Testet: alle 30 merke-sider bygger fortsatt med gyldig JSON-LD, FreshLook
(1 produkt, 0 serier) degraderer riktig (fikk fortsatt "i tall"/pris-graf,
men ikke seriekort/sammenligning), FAQ går korrekt tilbake til én kolonne
under 860px, ingen horisontal overflow på mobil eller desktop.

## Merke-siden: boks-for-boks-finpuss mot mockupen (2026-09-27, samme dag)

Kai: "går fremover, men fremdeles langt igjen til å se likt ut. bokser,
spørsmål, design etc. Mitt forslag. gå gjennom hver boks fra toppen og
nedover og gjør det så tilnærmet likt som mulig." Gikk gjennom heroen og
de to første seksjonene med detalj-sammenligning mot mockupen:

- **Hero fikk en egen undertittel** ("Kontaktlinser fra Johnson & Johnson
  Vision", ny `.brand-hero-subtitle`) rett under H1, adskilt fra selve
  intro-avsnittet (som ikke lenger gjentar produsentnavnet rett etter).
  Kun bygget ved kjent produsent-kobling.
- **Sekundær hero-knapp**: `manufacturer_link_html` gikk fra en enkel
  tekstlenke til en ekte sekundærknapp ("Om {produsent} →", hvit/border-
  stil ved siden av den blå primærknappen) -- matcher mockupen sin
  to-knappers hero. Lenker fortsatt til den ekte, eksisterende
  `/produsent/`-siden, ingen ny side.
- **Fase-2-faktakortene fikk riktig typografisk hierarki**: stort tall
  ALENE øverst (`.brand-facts-card-value`, økt til 1.7rem), enhet-etikett
  under som egen linje, og eventuell undertekst (f.eks. linsetype-listen)
  som en tredje, enda mindre linje -- var tidligere "21 produkter" som
  ETT sammenhengende streng uten hierarki.
- **Materialkortene fikk ikoner** (dråpe-ikon, roterende sky/mint/lavender/
  amber/coral-farger per kort) -- var bare ren tekst før.
- **"Sortimentet forklart"-kortene fikk snudd rekkefølge**: kategorinavnet
  er nå den STORE, fete linjen (`.brand-sortiment-card-label`), antall
  produkter er nå den mindre undertekst-linjen -- var motsatt (antall
  produkter var størst) og matchet ikke mockupen sitt hierarki.

Ikke rørt denne runden (skjønnsmessig utelatt, ingen ekte destinasjon å
lenke til): "Se alle serier →"/"Se alle spørsmål og svar →"-lenkene i
mockupen sine seksjonsoverskrifter -- begge seksjonene viser allerede ALT
innholdet der de står, en lenke til "se mer" ville gått til akkurat samme
sted. ® ved merkenavnet i mockupen er også bevisst utelatt -- kan ikke
bekrefte varemerke-status per merke på tvers av alle 30 sidene.

Testet: alle 30 merke-sider bygger fortsatt med gyldig JSON-LD, ingen
mobil-overflow.

## Merke-siden: Fase-2-faktakortene erstattet med en statistikkstripe i heroen (2026-09-27, samme dag)

Kai sendte et nytt mockup-bilde (hero med en integrert nederste stripe i
stedet for fire frittstående kort under heroen, pluss et nytt bakgrunnsbilde)
og var eksplisitt: "Replace the four large Brand Facts cards below the hero
with a compact metadata strip integrated into the bottom of the hero. Show
only: 21 produkter · 4 serier · 4 linsetyper · 9 butikker, all dynamically
generated. Use subtle separators and small icons. Target approximately
60–75 px additional hero height. Remove the long list of lens types from
this component... Keep the larger card treatment for the later 'Acuvue i
tall' section."

- **Fjernet** `.brand-facts-row`/`.brand-facts-card*` (CSS og markup) helt.
  `brand_facts_row_html` erstattet med `brand_hero_stats_html`, bygget fra
  SAMME `stat_pills`-data som før, men uten `sub`-feltet (linsetype-
  oppramsingen er bevisst utelatt -- den forklares lenger ned på siden).
- **Ny `.brand-hero-stats`**: `position:relative; z-index:3`, ligger som
  fullbredde-søsken av `.brand-hero-content` og `.brand-hero-media` direkte
  i `.brand-hero` (IKKE inni `.brand-hero-content`, som er begrenset til
  62% bredde på ≥860px) -- slik spenner stripen over hele heroen, også
  under bildet. Separert fra knapperaden med en tynn `border-top`, hvert
  element har `border-left` som subtil skillelinje (untatt første).
  Målt i bygget side: stripen legger til ~72px hero-høyde (padding-top 14
  + margin-top 18 + border 1 + selve strip-innholdet ~39px) -- innenfor
  Kais 60-75px-mål.
- **Nytt hero-bilde**: kroppet ut fra Kais mockup (`42.webp`, kvinne med
  linse på fingertuppen, varmere/annen komposisjon enn forrige bilde) og
  erstattet `static/hero/brand-{560,840,1120}.webp`. Beholdt samme
  fade-maske-teknikk (`.brand-hero-media` maskerer inn bildet fra venstre),
  så den kursive "Klarere hverdager"-teksten i mockupen forsvinner i
  fade-sonen automatisk -- ingen manuell fjerning av tekst fra bildet var
  nødvendig, kun beskjæring til fotoet selv. `width`/`height`-attributtene
  på `<img>` oppdatert fra 560×215 til 560×385 (nytt bilde er brattere).
  Samme filnavn brukes av `render_private_label_brand_page()`, så
  `height`-attributtet ble oppdatert der også (kun attributtet, ingen
  strukturendring -- den siden ble ikke bedt om statistikkstripen).
- **Ikke rørt**: `brand_i_tall_html`/`.brand-i-tall*` ("{Merke} i tall") --
  eksplisitt bevart som store kort, per instruks.

Kai kommenterte samtidig (om seriekort-raden lenger ned, som nå bryter til
ny linje når den ikke får plass på én rad): vil senere ha "så mange vi har
plass til på en rad + en knapp for å se flere" -- IKKE gjort ennå, egen
runde.

Testet: alle 30 merke-sider bygger uten Traceback/NameError, gyldig
JSON-LD på alle, FreshLook (1 produkt, 0 serier) viser korrekt kun 3
stripe-elementer (produkt/linsetype/butikker, "serier" utelatt siden
`family_summaries` er tom), målt via `getBoundingClientRect()` i
browser-panelet (skjermbilde-rendering av bygde filer er upålitelig, se
tidligere notat i dette dokumentet).

### Oppfølging samme dag: fjernet skillelinjene i stripen

Kai, med skjermbilde: den øverste `border-top`-streken over stripen gikk
rett over halsen på modellen i det nye hero-bildet -- "Den kan fjernes.
går over halsen på modellen.. Disse kan bare flyte naturlig uten streker."

- `.brand-hero-stats`: fjernet `border-top`/`padding-top`, elementene får
  nå ren luft via `column-gap`/`row-gap` (ingen linjer i det hele tatt).
- `.brand-hero-stat`: fjernet `border-left`-skillelinjen mellom hvert
  element av samme grunn ("disse" = elementene, ikke bare toppstreken).
- `margin-top` på `.brand-hero-stats` justert til 38px for fortsatt å
  treffe det opprinnelige 60-75px-høyde-målet (målt til ~66px lagt til
  heroen) etter at strekene (som tidligere bidro til avstanden) ble borte.

Testet på nytt: mobil (375px) bryter pent til to rader uten noen
gjenværende/hengende skillelinje, alle 30 sider bygger fortsatt rent.

## Merke-siden: "Utforsk {merke}-seriene" bygget om til Series Portrait Cards (2026-09-27, samme dag)

Kai sendte en detaljert 19-punkts brief (skrevet i jeg-form, direkte svar
på "hvilken [boks] vil du ta først") + mockup-referanse (44.webp, samme
bilde limt inn to ganger), og fulgte opp med en presisering midt i
implementeringen om kortbredde. Kjernen: kortene skal føles som
"premium editorial navigation", ikke en nettbutikk-grid, og ALDRI bli
unaturlig brede bare fordi et merke har få serier.

- **Seksjonsheader**: ny kicker "PRODUKTSERIER" (`.brand-section-kicker`),
  ny lead-setning ("Se forskjeller, varianter, egenskaper og priser i
  hver produktserie" -- erstatter "velg den som passer ditt behov", som
  Kai eksplisitt ikke ville ha siden siden ikke skal antyde at vi avgjør
  hva som medisinsk passer brukeren). Ny "Sammenlign seriene →"-lenke
  øverst til høyre -- lenker til `#sammenlign` (ny id lagt på den
  EKSISTERENDE "Slik skiller seriene seg"-tabellen lenger ned), vises kun
  når ≥2 serier faktisk finnes å sammenligne.
- **`_brand_family_summary()`-data gjenbrukt uendret** -- ingen ny
  datakilde. Kortet viser: eyebrow (hovedtype, fargekodet likt
  "Sortimentet forklart"-kortene: dagslinser=amber, månedslinser=sky,
  fargede=mint, toriske=coral, multifokale=lavender), ekte produktbilde
  (`object-fit:contain`, transparent, ikke krysset embalasje), serienavn,
  EN valgfri faktabeskrivelse, variant-piller (Standard/Torisk/
  Multifokal, kun de som faktisk finnes), antall produkter + fra-pris,
  og en ensartet "Utforsk serien →"-ghost-CTA (ikke blå knapp på første
  kort og hvit på resten, som mockupen tilfeldigvis viste -- Kai selv
  påpekte dette skulle IKKE kopieres 1:1).
- **Faktabeskrivelse er strengt betinget** (`brand_series_description()`):
  krever BÅDE en kjent hovedtype OG ett entydig materiale på tvers av
  HELE serien (samme `material`-felt som allerede er `None` ved >1
  materiale i familien) -- ellers vises ingen beskrivelse i det hele tatt
  (bekreftet i bygget output: Acuvue 4 kort/3 beskrivelser, Miru 1
  kort/0 beskrivelser, osv., ingen tom `<p>` eller layout-hull).
- **Ikke implementert** (Kai, punkt 10, eksplisitt): de tre
  ikonpåstandene fra mockupen ("Høy fuktighet", "Komfort hele dagen",
  "UV-beskyttelse" osv.) -- ren, udokumentert markedsføringstekst per
  kort i mockupen, ikke faktiske data. Feltet er bevisst utelatt helt,
  ikke fylt med plassholdere.
- **`.brand-serie-grid`-bredde-fiks** (Kai fulgte opp med en egen,
  eksplisitt presisering midt i arbeidet): `grid-template-columns:
  repeat(auto-fill, minmax(280px, 1fr))` + `.brand-serie-card{max-width:
  350px}` -- IKKE en fast `minmax(280px, 350px)` slik den første
  lesningen av CSS Grid-spesifikasjonen skulle tilsi. Årsak, empirisk
  bekreftet i browser-panelet: når minmax()-maksverdien er en bestemt
  lengde (f.eks. `350px`), bruker Grid-spesifikasjonen DEN verdien til å
  telle antall spor, ikke minimumsverdien -- det ga bare 3 kolonner i en
  1240px-container for Acuvues 4 serier (feil). Med `1fr` som maks (en
  UBESTEMT verdi) telles sporene etter minimumsverdien (280px) i stedet,
  som gir 4 spor i samme container, og de vokser deretter jevnt opp mot
  350px (målt til ~297px hver i denne containerbredden). Auto-fill (ikke
  auto-fit) beholder tomme spor som usynlig luft uansett -- bekreftet
  empirisk at et merke med KUN 1 serie (Precision1) fortsatt får et kort
  på ~297px bredde, ikke strukket til full containerbredde, fordi de 3
  andre (tomme) sporene fortsatt eksisterer og deler overskuddsplassen.
- **Testet eksplisitt med 1, 2, 3, 4 ekte serier** (Precision1/Biofinity/
  Proclear/Acuvue -- ingen merke i den ekte katalogen har 5 eller 8
  serier ennå) OG **syntetisk med 5 og 8 kort** (samme ekte kort-HTML +
  CSS limt inn i en frittstående testside, servert lokalt) -- begge
  bryter korrekt til flere rader (5→4+1, 8→4+4) med konsistent ~297px
  bredde per kort, ingen strekking. FreshLook (0 serier) viser fortsatt
  ingen seksjon i det hele tatt (uendret adaptiv oppførsel).
- Hover/fokus: `translateY(-2px)`, lett border-fargeendring, subtil
  skygge, produktbilde `scale(1.02)`, CTA-pil forskyves 3px -- alle med
  `:hover, :focus-visible` parallelt (samme mønster som
  `.category-row`/`.offer-card` ellers på siden) for tastaturtilgjengelighet.
  Global `prefers-reduced-motion:reduce`-regel (allerede i SHARED_STYLE)
  dekker alle disse transisjonene uten ekstra kode.

## Merke-siden: liten konsistens-runde på "30 eller 90 linser?" og sortiment-kortene (2026-09-27, samme dag)

Kai: "gjerne gjør et forsøk" (uten nytt mockup denne gangen) på resten av
"boks for boks"-lista. Uten en fasit å style mot, gjorde jeg to trygge,
avgrensede forbedringer i stedet for å gjette bredt på FAQ/guider/
Produsent-modul/tillit-footer sitt utseende:

- **`.brand-sortiment-card:hover` var duplisert** (samme regel skrevet to
  ganger) og brukte fortsatt det gamle blå glød-skygge-mønsteret
  (`rgba(37, 99, 235, .14)`) som ikke lenger matcher den stillere,
  ink-tonede hover-stilen `.brand-serie-card` fikk denne økten. Fjernet
  duplikatet og samkjørte hover/fokus-stilen med seriekortene
  (`:hover, :focus-visible` sammen, samme skygge-/border-farge).
- **"30 eller 90 linser?"-flisene fikk små fargede ikoner** (samme
  sirkel-ikon-mønster som "{Merke} i tall"-flisene og materialkortene
  lenger opp på siden: BOX_ICON_SVG i sky/mint for 30-/90-pack,
  TAG_ICON_SVG i amber for prosent-forskjellen) -- ren visuell
  konsistens, ingen ny data.

**Ikke rørt** (ba Kai om retning på i stedet for å gjette): FAQ-seksjonens
egen styling, "Nyttige ressurser"-guidekortene (gjenbruker allerede
`render_guide_tile()` uendret), Produsent-modulen (fortsatt en enkel hvit
boks, kunne fått mer visuell vekt men usikkert i hvilken retning uten
referanse) og tillit-footeren nederst -- alle fire fungerer og er
faktakorrekte, men å redesigne dem uten mockup risikerer akkurat den
typen bomtreff ("vi er langt unna") tidligere runder denne økten viste
skjer når jeg gjetter på Kais visuelle preferanser i stedet for å se et
referansebilde først.

## KRITISK FIX: søkefeltet på forsiden virket ikke i det hele tatt (2026-09-27, samme dag)

Kai: "søkefunksjon virker ikke nå! på startsiden" -- ekte regresjon,
oppdaget og fikset samme dag den ble introdusert (commit `1030b97ad`,
tidligere i denne økten, FØR sammendraget/oppsummeringen som denne
CLAUDE.md-loggen fortsetter fra).

**Rotårsak**: `LENS_SEARCH_JS` (den delte søke-IIFE-en, limt inn via
`TOPBAR_HTML` tidlig i `<body>`) begynner med
`var rows = document.querySelectorAll('.search-row'); if (!rows.length)
return;`. Da søkefeltet på toppmenyen ble delt mellom sider (samme
commit), ble forsidens EGEN kopi av søke-scriptet fjernet med vilje
("unngår at IIFE-en kjører to ganger... dobbeltbinder event-lyttere",
se kommentar i koden) -- men forsidens `.search-row` (selve
hero-søkefeltet) ligger et godt stykke LENGER NED i `<body>` enn
TOPBAR_HTML sitt script-tag. Siden scriptet er synkront og ikke utsatt,
kjørte det FØR forsidens `.search-row` i det hele tatt var parset inn i
DOM-en -- `rows.length` var 0 på kjøretidspunktet, og funksjonen returnerte
tomt UTEN å binde en eneste event-lytter. Ingen konsoll-feil, ingen
JSON-feil, ingen bygge-feil -- helt stille, kun synlig ved at søkefeltet
faktisk ikke reagerte på tastetrykk. Bekreftet empirisk: `python3 -c`
mot `build/index.html` viste `var rows = document.querySelectorAll(...)`
på tegn-posisjon 83054, mens `class="search-row"` først dukker opp på
posisjon 87657 -- scriptet kjørte definitivt for tidlig.

**Fix**: pakket hele IIFE-kroppen inn i en `init()`-funksjon, kalt enten
umiddelbart (hvis `document.readyState !== 'loading'`, dvs. DOM-en
allerede er ferdig parset når scriptet kjører -- f.eks. hvis scriptet av
en eller annen grunn havner sent i body på en fremtidig side) eller via
`document.addEventListener('DOMContentLoaded', init)` (dekker akkurat
dette tilfellet -- scriptet ligger tidlig, elementet kommer senere).
Robust mot begge rekkefølger, ingen dobbeltbinding (kjører kun én gang
uansett hvilken gren som trigges), null endring i selve søkelogikken.

**Verifisert**: JS-syntaks sjekket med `node --check` på den isolerte
strengen, ekte klikk+tastetrykk i browser-panelet på forsiden (lokalt
bygget `build/index.html`) ga nå korrekt forslagsliste med
produktbilder, samme test på en guide-side (som har 3 `.search-row`-
forekomster -- meny + evt. andre) fungerte også uendret. Ingen
Traceback/NameError i noen bygde sider.

**Lærdom for fremtiden**: et delt, synkront `<script>`-tag som gjør
`querySelectorAll` og forventer at ELEMENTER LENGER NEDE i samme side
allerede finnes, er en tidsbombe som avhenger av nøyaktig hvor i
`<body>` scriptet limes inn på HVER side som bruker det -- default til
`DOMContentLoaded`-mønsteret over for ALL fremtidig delt DOM-avhengig
inline-JS i dette prosjektet, ikke bare denne ene funksjonen.

## Forsiden: H1 "Finn billigste kontaktlinser" fikk 0px margin til konteineren ved 1024px (2026-09-27, samme dag)

Kai: "Finn billigste kontaktlinser på startsiden øverst kan vel være på
1 linje? Uten at det går ut over seo" + "og at alt over søk blir
proposjonalt pent".

Målte `.hero-heading h1` (kun brukt på forsiden, IKKE samme regel som
den delte `.hero-copy h1` andre hero-varianter bruker) på tvers av
bredder med `Range.getBoundingClientRect()` (måler selve tekst-glyph-
boksen, ikke elementets flex-strukne fulle bredde). Ved nøyaktig 1024px
(der to-kolonne-layouten starter) var tekstens naturlige bredde
IDENTISK med kolonnebredden på pikselet -- 0px margin. Det er nok til at
den minste font-metrikk-forskjell (Windows ClearType-rendering av Space
Grotesk vs. denne testens Chromium, zoom-nivå, osv.) vipper den over i
to linjer, uten at noe faktisk er "ødelagt" i koden -- bare null
sikkerhetsmargin.

**Fix**: senket clampen fra `clamp(2rem, 3.1vw, 2.6rem)` til
`clamp(1.75rem, 2.6vw, 2.35rem)` PÅ DEN SPESIFIKKE `.hero-heading h1`-
regelen (scoped, rører ikke andre sider). Gir ~128px reell margin (målt
med samme Range-teknikk) ved 1024px i stedet for 0px, samtidig som hele
kicker/h1/undertekst-blokken over søkefeltet ser roligere/mer
proporsjonal ut (mindre sprang fra kicker til H1). H1-TEKSTEN selv er
uendret -- kun visuell størrelse, ingen SEO-konsekvens. Mobil (<1024px,
delt `.hero-copy h1`-regel) er IKKE rørt -- to linjer der er normalt og
forventet på en 375px skjerm for en 27-tegns overskrift, ikke det Kai
pekte på.

Testet ved 1024/1100/1200/1366/1440px (alle 1 linje, god margin) og
375px mobil (uendret, fortsatt fin 2-linjers wrap der det er naturlig).

## Produktsiden: "Product Mobile Gold Standard v1" -- Steg 1: Winner Card + Savings Signal (2026-09-27, samme dag)

Kai sendte en full 31-punkts mobil-produktside-brief (+ mockup-bilder) via
en Explore-agent-kartlegging av eksisterende kode først (kjørt før noen
endring), etterfulgt kort tid etter av et eget presist korreksjonstillegg
om selve Savings Signal-beregningen. Gitt størrelsen på briefen
implementeres den i etapper, akkurat som merke-side-redesignet tidligere
samme dag -- dette er STEG 1 (vinnerkortet + spar-signalet), ikke hele
briefen. Resten (H1/undertittel, bilde+vinnerkort side ved side, flytte
frakt-bryteren, kompakt prisliste, "kunnskaps-brudd" + accordion-
kunnskapssone) gjenstår som egne runder.

**Viktig, bevisst reversering (ikke en glipp)**: "Prisjakt-modellen"
(utrullet TIDLIGERE samme dag, dokumentert i en lang kommentar rett over
`render_winner_widget()`) fjernet prisen helt fra vinnerkortet med vilje,
etter konkurrentsammenligning. Den nye, mye mer detaljerte
mockup-briefen ber eksplisitt om at prisen vises i kortet igjen. Dette er
en villet, instruert reversering av en beslutning fra samme dag -- den
gamle "Prisjakt"-kommentaren er bevisst latt stå som historikk/kontekst,
ikke slettet, selv om den ikke lenger beskriver dagens kort.

- **`compute_savings_pct(offers, qty, incl)`** (ny, rett før
  `render_winner_widget`): eksakt (IKKE "opptil") besparelse --
  `(høyeste - laveste sammenlignbare pris) / høyeste * 100`, blant tilbud
  som er `in_stock` OG ikke `is_stale` (utgåtte telles ikke), og i
  fraktmodus også ekskludert hvis `shipping_policy is None` (ukjent frakt
  skal ALDRI telle som 0 kr i en totalpris-sammenligning). `math.floor()`
  -- aldri rund opp, aldri kommuniser en større besparelse enn den
  faktiske. Skjult helt under 10 % eller med færre enn 2 sammenlignbare
  tilbud. Samme funksjon (server, Python) og en JS-tvilling
  (`computeSavingsPct()` i `_QTY_CALC_SCRIPT`, holdt manuelt i synk --
  begge har kommentarer som peker til hverandre) dekker
  standard-rendering OG antalls-/frakt-bytte.
- **`_winner_price_line()`**: "232 kr/eske + 59 kr frakt" (1 eske),
  "928 kr/4 esker + 59 kr frakt" (flere esker -- total produktpris, ikke
  "kr/eske" som ikke gir mening over 1), eller "291 kr inkl. frakt"
  (fraktmodus). Ukjent fraktpolicy i fraktmodus vises ærlig ("+ frakt
  beregnes i kassen"), later ALDRI som frakt er kjent når den ikke er
  det. Samme JS-tvilling-mønster (`winnerPriceLine()`).
- **Vinnerkortets nye innhold**: "Laveste pris"/"Lavest totalpris"
  (avhengig av frakt-modus, IKKE lenger "Laveste pris inkl. frakt"),
  "for N eske(r)", en gull-sirkel ("Spar 43 %", `.winner-savings`,
  skjult med `hidden`-attributt -- ikke fjernet fra DOM-en -- når under
  terskel, slik at JS bare kan slå den av/på uten å bygge om markup),
  ekte forhandlerlogo (uendret `_retailer_badge_html()`), prislinjen, og
  en "Gå til butikk"-knapp (endret fra "Gå til tilbud"). **Fjernet**:
  trofé-ikonet og "Sammenlign alle N butikker ↓"-lenken (briefen: "Ingen
  annen tekst" i kortet -- prislisten står uansett rett under i det
  reorganiserte laget som kommer i neste runde).
- **Bakgrunn/skygge**: fra en flat `var(--mint-tint)`-fylling til en
  ekstremt subtil hvit->mint-gradient (`linear-gradient(165deg, #FFFFFF
  0%, #F3FBF7 100%)`) + `var(--card-shadow)` -- "nesten hvitt, premium og
  rolig, ikke en affiliate-bannerannonse" (Kais ord).
- **`.winner-band-wide`-CSS reparert for konsistens** (grid-areas som
  refererte `.winner-left`/`.winner-more`, begge fjernet fra markup, ville
  gitt feil layout) -- men bekreftet at `wide=True` faktisk ALDRI kalles
  noe sted i kodebasen i dag (`grep "wide=True"` → 0 treff), så dette er
  ren fremtidssikring, ingen levende side er berørt.
- **Ikke rørt i dette steget** (bevisst, egen runde): selve
  side-layouten (H1/undertittel/bilde+vinnerkort-plassering), frakt-
  bryterens posisjon, prislistens kompakthet, "kunnskaps-brudd" og
  accordion-reorganisering av innholdet under. Disse krever en større,
  mer risikofylt restrukturering av `render_product_page()` sin markup-
  rekkefølge og fortjener egen testing.

Testet: alle 146 kontaktlinse-produktsider + linsevæske/øyedråper-sider +
private label-sider bygger uten Traceback/NameError, gyldig JSON-LD på
stikkprøver, ekte antalls-/fraktbytte verifisert i browser-panelet (både
prislinje, spar-prosent OG "Laveste pris"/"Lavest totalpris"-teksten
oppdaterer riktig), desktop-gridet (≥860px) uendret og fungerer med det
nye kortinnholdet.

## Produktsiden: "Product Mobile Gold Standard v1" -- Steg 2: layout, fraktbryter, prisliste, kunnskapssone (2026-09-27, samme dag)

Kai: "gjør deg ferdig, så ser vi på det" + eksplisitt bekreftelse midt i
arbeidet: "du gjør først mobil produktsiden ferdig nå, korrekt? ikke
desktop? [...] Men la oss fokusere på mobil produktside." Steg 2 fullfører
resten av briefen for `render_product_page()` (KUN kontaktlinse-
produktsiden -- linsevæske/øyedråper og private label-alias-siden er
bevisst urørt denne runden, se Steg 1).

- **Hero omstrukturert**: `.hero-copy` er nå BARE kicker+H1+
  "Sammenlign priser"-undertittel (fjernet den lange produktbeskrivelsen
  og badges fra kjøpssonen -- flyttet ned, se kunnskapssone). Nytt
  `.hero-media-row` (bilde ~2/3, Winner Card ~1/3, `flex:2`/`flex:1`) på
  mobil. På >=860px blir `.hero-media-row` `display:contents`, slik at
  bildet og vinnerkortet igjen er DIREKTE grid-barn av `.hero-main` og
  treffes av nøyaktig samme `grid-column`/`grid-row`-regler som før --
  desktop-layouten er dermed helt uendret, kun mobil-grupperingen er ny.
  Vinnerkortet fikk egne, MOBIL-SCOPEDE (`@media (max-width: 859px)`)
  kompaktifiseringer (mindre padding/skrift/logo/spar-sirkel) siden den
  smale ~1/3-kolonnen trengte det -- eksplisitt avgrenset til mobil, IKKE
  en generell endring av `.winner-band-cta` (som ville lekket inn på
  desktop-kortet via vanlig DOM-etterkommerskap, siden `display:contents`
  ikke fjerner elementet fra treet, bare fra boks-generering).
- **Fraktbryteren flyttet**: fra `render_price_list()` sin `.offers-head`
  til `render_winner_widget()` sin `qty_box`, i en ny `.qty-box-head`-rad
  ved siden av "Antall esker"-tittelen (endret fra "Hvor mange esker
  trenger du?"). Ny `show_ship_chip`-parameter på `render_price_list()`
  (standard `True`) holder de to andre kallerne (linsevæske/øyedråper,
  private label-alias) helt uendret -- kun produktsiden sender
  `show_ship_chip=False`. Samme `#ship-chip`-id, samme
  document-nivå click-delegation i `_QTY_CALC_SCRIPT`, så flyttingen
  krevde ingen JS-endring utover selve plasseringen.
- **Prisliste**: ny dynamisk overskrift "Priser for `<span
  id="offers-qty-label">`1 eske`</span>`" + "Sortert etter pris (uten
  frakt)"/"Sortert etter totalpris" (`#offers-sort-label`), begge
  oppdatert av `_QTY_CALC_SCRIPT` sin `render()`. Nye
  `qty_unit_label`/`collapse_after`-parametre på `render_price_list()`
  (begge `None` som standard -- samme bakoverkompatibilitets-mønster som
  `show_ship_chip`). Kortene er nå i en egen `.offers-list`-wrapper
  (universell endring, men trygg -- `.offers`/`.offer-card` hadde ingen
  flex/grid-avhengighet til hverandre, ren blokk-stabling med
  `margin-bottom` per kort, så et ekstra wrapper-nivå endrer ingenting
  visuelt for de andre sidetypene). "Vis alle priser (X butikker)" (kun
  produktsiden, `collapse_after=3`) skjuler resten med
  `.offers.is-collapsed .offers-list .offer-card:nth-child(n+4)` -- dette
  treffer alltid de 3 BILLIGSTE kortene selv etter at JS-en har sortert
  om listen (appendChild flytter kortene fysisk i DOM-en ved
  antalls-/fraktbytte, og nth-child telles på nåværende DOM-rekkefølge,
  ikke en fast opprinnelig posisjon) -- testet eksplisitt: bytte til
  "Pris inkludert frakt" mens listen er kollapset viser fortsatt riktig
  de 3 billigste EFTER omsortering. Knappen fjernes helt (ikke bare
  skjules) ved klikk, ingen re-kollaps-vei tilbake (samme ubetingede
  "vis alt"-mønster som resten av siden).
- **Kunnskapssone**: ny `_kz_accordion(summary, inner_html)`-hjelper
  (generisk, gjenbrukbar) + en ny `.kz-break`-visuell overgang
  ("ALT OM {produkt}", flankerende linjer). "Om {produkt}"-seksjonen
  (kort fortalt + badges + prishistorikk-graf + aliaser) er IKKE en
  accordion -- forblir alltid synlig, siden dette er kjerneinnhold, ikke
  sekundær dybde. Tre accordions: "Produktspesifikasjoner",
  "Vanlige spørsmål om {produkt}", "Kilder og dokumentasjon"
  (metodikk + relaterte lenker slått sammen). FAQ-accordionen bruker en
  NY `_render_faq_accordion_block()` (samme {question,answer}-inndata og
  FAQPage-schema som `_render_faq_block()`, men med
  `_faq_accordion_item()` -- samme per-spørsmål `<details>`-komponent
  serie-/merke-sidene allerede bruker -- i stedet for en alltid-synlig
  flat liste). `_render_faq_block()` selv er UENDRET og fortsatt brukt av
  de to andre produktside-variantene. Alt innhold er fortsatt ekte,
  server-rendret HTML uansett åpen/lukket tilstand (samme
  Google-verifiserte `<details>`-mønster som resten av siden) -- ingen
  data fjernet, kun omorganisert.
- **`pack_size_callout`/`family_callout` flyttet FØR kunnskaps-bruddet**
  (rett etter prisdisclosure-teksten) -- brief punkt 19-20 plasserer
  "alternativ pakning" eksplisitt i kjøpssonen, ikke kunnskapssonen.

Testet: alle kontaktlinse-/linsevæske-/private label-sider bygger uten
Traceback/NameError, gyldig JSON-LD (inkl. FAQPage-schema fra den nye
accordion-funksjonen) på stikkprøver, "Vis alle priser" verifisert
eksplisitt i browser-panelet (7 skjulte kort → alle synlige, knapp borte,
kollaps følger riktig topp-3 etter fraktmodus-bytte), degraderer riktig
ved 1 tilbud (vinnerkort men ingen antallsvelger, ingen "vis
alle"-knapp), desktop (1100px) uendret og fungerer med ny undertittel +
nytt vinnerkort-innhold.

## Produktsiden: vinnerkortet var for høyt, for mye luft rundt bildet (2026-09-27, samme dag)

Kai: "vil gjerne sett Laveste Pris mer firkantet og synes det er veldig
mye plass rundt selve bilde på mobil [...] men jeg forstår den skal passe
der det er et større bilde." Begge ting hadde samme rot-årsak.

**Rot-årsak**: `.hero-product-image` er en DELT regel (brukes over hele
siden der et stort, kvadratisk bilde er riktig) med `aspect-ratio: 1/1`.
I den nye, smalere ~2/3-kolonnen ga det (a) synlig luft over/under det
faktisk liggende eskebildet, OG (b) et unødvendig høyt, smalt
vinnerkort ved siden av -- fordi `.hero-media-row` brukte
`align-items: stretch`, som PRESSET bildet opp til vinnerkortets
(tallere) naturlige innholdshøyde i stedet for å la det følge sin egen
aspect-ratio. `aspect-ratio` og `align-items: stretch` konkurrerer om
samme kryss-akse i en flex-rad, og stretch vinner -- bekreftet empirisk:
satte først bare `aspect-ratio: 4/3` alene og målte fortsatt 202,8px
høyde (uendret), ikke de forventede ~135px.

**Fix, to steg**:
1. `.hero-media-row` byttet fra `align-items: stretch` til
   `align-items: flex-start`, scoped uten ekstra media-query siden regelen
   uansett blir irrelevant på >=860px (`.hero-media-row` er da
   `display: contents`, ingen egen flex-kontekst). Bildet følger nå
   faktisk sin `aspect-ratio: 4/3` (målt 180×135px), i stedet for å
   strekkes til kortets høyde.
2. Vinnerkortet komprimert videre i det eksisterende
   `@media (max-width: 859px)`-laget fra forrige runde: "Laveste
   pris"/"for 1 eske" slått sammen til ÉN linje (var to stablede),
   tettere gap (8px→6px), mindre skrift/logo/spar-sirkel/knapp-padding.
   Høyde gikk fra ~203px til ~179px ved samme ~102px bredde -- fortsatt
   ikke perfekt 1:1 (bredden er hardt begrenset av 1/3-fordelingen med
   bildet), men merkbart mer kompakt/balansert, nærmere Kais egen
   designspec sitt høyde-mål (140-160px, opprinnelig tegnet for et bredere
   frittstående kort).

Testet: målt eksakt bredde/høyde før/etter i browser-panelet (ikke bare
visuell vurdering), sjekket et produkt UTEN Savings Signal (ingen
gullsirkel -- fortsatt balansert, ingen tomt hull), desktop (1100px)
helt uendret, alle sider bygger fortsatt uten Traceback/NameError.

## Kompakt mobil-topbar (logo + søkeikon + meny-ikon) + AI-sammendraget flyttet ned (2026-09-27, samme dag)

Kai, tre punkter i samme melding: "teksten 'vi sammenligner priser på..'
skal beholdes for SEO osv, men skal være lengre ned på siden" +
bekymring om at antallsvelger/fraktbryter "ikke er lagt inn" + "jeg
tenker søkefunksjon øverst på produktkort på mobil er unødvendig. heller
et søkeikon oppe er fint. Feks. logo, søkeikon og et annet ikon for meny
oppe til høyre [...] kompakt og bra fra toppen."

**Antallsvelger/fraktbryter**: bekreftet direkte mot den LIVE siden (med
cache-busting query-parameter) at begge faktisk lå der -- `hasQtyBox` og
`hasShipChip` begge `true`. Nesten helt sikkert samme type nettleser-
cache som rammet meg selv tidligere i denne økten (se det tidligere
"søkefunksjon virker ikke"-avsnittet), ikke en reell mangel -- ingen
kodeendring gjort for dette punktet.

**AI-sammendraget** (`{{ai_summary_html}}`, den blå "Vi sammenligner
priser på X..."-boksen): flyttet ut av `.hero-main` (var rett under
bilde/vinnerkort-raden) til rett før kunnskaps-bruddet, etter
`pack_size_callout`/`family_callout`. Innholdet er UENDRET (fortsatt
faktisk, prisledet SEO-tekst) -- kun posisjonen på siden er endret. Den
gamle `.hero-main .product-ai-summary`/`.hero-card .product-ai-summary`
grid-plasseringen i CSS-en er nå dødt (ingen treff), men ufarlig å la stå
siden boksen bare faller tilbake til sin egen generiske, allerede
eksisterende stil (blå venstre-kant-boks) på sin nye plass.

**Kompakt mobil-topbar**: ny `.topbar-mobile-actions` (kun `<700px`) med
to ikonknapper -- søk (kun når `show_search=True`, altså IKKE på
forsiden som har sin egen store hero-søk) og meny (alltid). Begge åpner
uavhengig av hverandre (`toggleMobilePanel()`, lukker den andre hvis den
var åpen). `.topbar-nav`/`.topbar-search` er skjult med `display:none`
som standard under 700px og vises via `.is-open`.

**Viktigst for korrekthet**: selve søkeskjemaet (`.search-row`/
`.search-input`/`.search-suggestions`, id `topbar-search-panel`) er
IKKE strukturelt endret -- kun CSS-synligheten. Elementet finnes i
DOM-en hele tiden uansett åpen/lukket tilstand, så `LENS_SEARCH_JS` sin
`document.querySelectorAll('.search-row')`-oppslag (se dagens tidligere
`DOMContentLoaded`-fiks) finner det akkurat som før -- INGEN risiko for
å gjenintrodusere samme dags "søket svarer ikke på tastetrykk"-bug.
Bekreftet eksplisitt: skrev "acuvue" i det nyåpnede søkefeltet i
browser-panelet og fikk ekte forslag med produktbilder, akkurat som før.

Testet: meny-ikon åpner/lukker menyen (inkl. at et mega-menu-tap
inni den fortsatt fungerer og lukkes korrekt), søk-ikon åpner søkefeltet
med fokus og fungerende autofullføring, de to lukker hverandre riktig,
forsiden (uten søkeikon, kun meny-ikon) fungerer identisk og dens EGEN
hero-søk er helt upåvirket, desktop (≥700px) fullstendig uendret (full
meny + synlig søkefelt som før). Full sveip av ALLE 411 bygde sider
(topbaren er delt sitewide) -- ingen Traceback/NameError, gyldig
JSON-LD overalt.

## Produktsiden: "Vis alle priser"-kollapsen skal KUN gjelde mobil (2026-09-27, samme dag)

Kai, rett etter forrige runde: "Do not collapse the merchant price list.
On desktop, render all valid current offers immediately [...] The full
merchant list is part of the value proposition [...] Keep progressive
disclosure only on mobile [...] When the shipping toggle or quantity
changes, re-rank the entire visible desktop list dynamically."

Ren CSS-avgrensning, ingen server- eller JS-endring nødvendig:
`.offers.is-collapsed .offers-list .offer-card:nth-child(n+4)` (skjuler
alt utover topp-3) og `.offers-show-more`-knappen er nå eksplisitt
tilbakestilt til synlig/vist ved `@media (min-width: 860px)` (samme
brytpunkt som resten av sidens desktop-layout). Python-siden bygger
fortsatt `is-collapsed`-klassen og knappen uendret når det er >3 tilbud
-- de trengs fortsatt for mobil -- CSS-en gjør dem bare virkningsløse på
desktop. `_QTY_CALC_SCRIPT` sin `render()` sorterer og re-append'er
alltid HELE listen uansett skjermbredde (kollapsen var alltid bare et
rent visuelt lag oppå en fullstendig liste), så "re-rank hele den
synlige desktop-listen dynamisk" fungerte allerede -- bekreftet
eksplisitt: alle 7 tilbud synlige og korrekt omsortert etter å ha slått
på "Pris inkludert frakt" på desktop (1100px).

Testet: desktop (1100px) viser alle 7 kort med det samme, ingen "Vis
alle priser"-knapp, mobil (375px) uendret -- fortsatt topp 3 + knapp.
Full sveip, ingen Traceback/NameError.

## Innholds-revisjon: bekreftet at INGENTING ble slettet i mobil-redesignet (2026-09-27, samme dag)

Kai, med god grunn til å spørre: bekymring om at "substantial Product
Gold Standard content appears to have disappeared", pluss en presis,
navngitt bekymring om `qty-static-fallback` (en teknisk detalj fra
TIDLIGERE i dag). Instruksen var eksplisitt: bruk git-historikken som
fasit, ikke hukommelsen.

**Metode**: `git show 8fbdc5584:site_generator/render_templates.py`
(siste commit FØR selve mobil-redesignet startet, dvs. rett før
`b6a7f111f "Winner Card viser pris igjen..."`) mot HEAD, diffet KUN
`render_product_page()`-funksjonen linje for linje. Deretter en
automatisert sveip av samtlige 141 kontaktlinse-produktsider (ikke bare
ett produkt) som telte faktisk tilstedeværelse av hver seksjon i den
bygde HTML-en.

**Funn**: Ingen kode ble faktisk slettet. Hver "-"-linje i diffen har en
tilsvarende "+"-linje andre steder i samme diff -- alt er FLYTTET
(inn i en ny `.kz`-kunnskapssone under et "kunnskaps-brudd"), ikke
fjernet:
- `long_description`, `badges_html`, `price_history_html`, `aliases_html`
  -- uendret beregning, kun ny plassering i `.kz`.
- `specs_html`, `methodology_html`+`related_html` -- uendret beregning,
  nå pakket inn i en `_kz_accordion()` (ekte `<details>`, samme
  Google-verifiserte mønster som `qty-multi`).
- `product_faq_html` -- samme `product_faq`-data og samme FAQPage-schema
  som før, men bygget med `_render_faq_accordion_block()` (per-spørsmål
  `<details>`) i stedet for `_render_faq_block()` (flat, alltid synlig
  liste) -- ren visningsendring, ikke datatap.
- `render_price_list()` fikk nye parametre (`show_ship_chip`,
  `qty_unit_label`, `collapse_after`) men mistet ingen evne -- "Vis alle
  priser"-kollapsen er en ren CSS-`display:none` (se forrige avsnitt i
  denne loggen), ALLE tilbudskort er fortsatt i den server-rendrede
  HTML-en uansett skjermbredde eller åpen/lukket tilstand.

**`qty-static-fallback`**: `git log -S "qty-static-fallback"` viser at
denne klassen ble erstattet av `<details class="qty-multi">` i commit
`f66ebe959`, FØR mobil-redesignet i det hele tatt startet (egen,
tidligere Kai-godkjent endring samme dag, dokumentert lenger opp i denne
loggen: "fra usynlig fallback-tekst til ekte `<details>`-rad"). Bekreftet
tilstede uendret på 129 av 141 sider (samme antall som har ≥2
sammenlignbare tilbud -- den eksisterende, uendrede betingelsen).

**Automatisert sveip (141 produktsider)**: spesifikasjoner 141/141,
FAQ-accordion 141/141, kilder/metodikk-accordion 141/141,
"i korte trekk"-badges 141/141, AI-sammendrag 141/141,
JSON-LD Product-schema 141/141, JSON-LD FAQPage-schema 141/141,
prishistorikk-graf 138/141 (de 3 uten har ærlig for lite historikk --
samme `>= 7 dager`-krav som før), alias-boks 33/141 (kun produkter med
faktisk kjent private label-kobling -- verifisert på Biofinity 6-pack,
som HAR 4 kjente aliaser, at boksen faktisk viser dem), serie-lenke
103/141, alternativ-pakning-lenke 75/141 (begge kategori A -- ikke alle
produkter har en serie eller en søsken-pakning).

**Én reell, ærlig forbedring gjort**: "Vis alle priser"-kollapsen på
mobil krevde JS for å faktisk EKSPANDERE knappen -- selve dataen var
alltid i den rå HTML-en (crawlere/AI-boter som bare leser DOM/tekst så
alt uansett), men en ekte bruker med JS avslått på mobil ville sittet
fast med kun topp 3. Lagt til en `<noscript><style>`-override rett etter
`{{offers_block}}` som tvinger full synlighet når JS ikke kjører -- samme
type forsvarlig no-JS-fallback-tankegang som allerede fantes for
`qty-multi`.

**Konklusjon til Kai**: Ingenting ble fjernet. Alt er flyttet til
kunnskapssonen, tre seksjoner er nå bak (ekte, server-rendrede,
crawler-lesbare) accordions i stedet for alltid synlige. Ett reelt,
lite no-JS-hull ble funnet og fikset underveis i denne revisjonen.

## Produktsiden: sluttrunde med bredde-/landskap-testing (2026-09-27, samme dag)

Kai: "kan vi fortsette og få produktsiden på plass?" (deretter: "men bare
jobb for å få produktsiden på mobil på plass, og så må vi få ryddet opp
på desktop også" -- desktop er bevisst UTSATT til egen runde, ikke gjort
her). Systematisk testet de breddene briefen selv ba om (320/360/390/
430px) pluss landskap (812×375, en typisk telefon i liggende modus).

- **Fant og fikset**: "Gå til butikk"-knappeteksten ble klippet
  (bokstaven "G" kuttet av) på de smaleste skjermene (320px) -- selv etter
  gjentatte skrift-nedskaleringer fra tidligere runder rakk ikke
  "Gå til butikk →" på én linje i den ~66px brede knappen. Løsning: byttet
  fra `white-space:nowrap` til `white-space:normal` (kun i det
  mobil-scopede laget) slik at CTA-en bryter pent til to linjer i stedet
  for å klippes -- mer robust enn å presse skriften enda mindre, som
  hadde gått ut over lesbarheten.
- **320/360/390/430px**: ingen horisontal overflow på noen av de fire,
  bekreftet med `document.body.scrollWidth`.
- **Landskap (812×375)**: bilde + vinnerkort side ved side fungerer fint,
  antallsvelger + fraktbryter på samme rad, prisliste bruker naturlig sin
  bredere (~700px+) radlayout -- ingen egen kode trengtes for dette,
  brifens ønskede landskap-oppførsel kom gratis av de eksisterende
  brytpunktene.
- **Funnet, IKKE fra dagens arbeid**: samme 812px-testen avdekket at
  toppmenyens mega-meny (720px fast bredde, `position:absolute` +
  `visibility:hidden` som standard -- usynlige elementer med
  `visibility:hidden` teller likevel med i `scrollWidth`) gir horisontal
  overflow på ALLE sider (bekreftet på forsiden også) i et
  ~700-860px-vindu, uavhengig av om menyen faktisk er åpen. Dette er en
  eldre, sidewide feil, ikke noe dagens produktside-redesign innførte --
  flagget som egen bakgrunnsoppgave (`task_4931b978`) i stedet for å
  fikses her og blande sammen med produktside-arbeidet.
- **Touch-mål**: "Gå til butikk"-knappen er ~29,6px høy på 375px --
  under den anbefalte 44px (WCAG AAA), men over det faktiske minstekravet
  (WCAG 2.5.8 AA, 24px). Bevisst IKKE økt videre -- Kai ba eksplisitt om
  et mer kompakt/firkantet kort i forrige runde, og å vokse knappen igjen
  ville motvirket akkurat det.

Testet: full sveip av alle 411 bygde sider, ingen Traceback/NameError.

## Produktsiden: AI-sammendraget helt inn i kunnskapssonen + kjempestore FAQ-chevroner fikset (2026-09-27, samme dag)

To ting samme runde. Først startet jeg feilaktig på et desktop-grid-fiks
etter Kai sa "fortsett" -- men han presiserte rett etterpå eksplisitt
"Do not start desktop yet", så den uncommitede grid-endringen ble
reversert (`git checkout --`) uten å shippes. Riktig lesning av
"fortsett" var: fullfør ETT gjenstående mobil-punkt, ikke start desktop.

**AI-sammendraget lenger inn**: satt tidligere som SISTE element i
kjøpssonen (rett før `.kz-break`-divideren) -- Kai påpekte at det
fortsatt "interrupts the purchase zone visually" der. Flyttet til å bli
FØRSTE element INNI `.kz`-diven (etter divideren, før "Om
{produkt}"-overskriften) -- samme innhold, samme SEO-verdi, men nå
utvetydig en del av kunnskapssonen i stedet for kjøpssonens hale.

**FAQ-chevronene rendret enormt store** (>100px, oppdaget av Kai på en
skjermdump av desktop -- men bekreftet EMPIRISK å gjelde mobil også,
ikke desktop-spesifikt): `_render_faq_accordion_block()` (ny funksjon fra
tidligere i dag) gjenbruker `_faq_accordion_item()` fra brand-/serie-
siden, men CSS-en som faktisk STØRRELSESBEGRENSER `<svg class=
"faq-chevron">` (`.faq-chevron{width:16px;height:16px}` m.fl.) lå kun i
DE andre funksjonenes egne `<style>`-blokker -- aldri kopiert inn i
`render_product_page()` sin. Uten noen bredde/høyde-regel i det hele
tatt rendret SVG-en i sin fulle, ubegrensede viewBox-størrelse. Fikset
ved å kopiere inn de samme reglene (identisk med kildene, samme
dupliserings-mønster som resten av kodebasen allerede bruker for
delt CSS per side-type).

Testet: `.faq-chevron`-bredde målt til nøyaktig 16px i browser-panelet
(var >100-140px før), AI-sammendraget bekreftet både etter
`.kz-break`-divideren OG inni `.kz` via `compareDocumentPosition()`,
full sveip av alle 411 sider uten Traceback/NameError.

## Produktsiden: fjernet kicker over H1, ekte fraktbryter-boks, "Pris ved flere esker" ned (2026-09-27, samme dag)

Kai sendte samme mockup-referanse igjen med tre konkrete punkter: "Alcon
/ produsent navn over produktnavn kan flyttes hvis nødvendig, men ikke
over navnet, for enda mer kompakt", "Se også bokser og Frakt av og på
knapp som ønskes", og "Teksten Pris ved flere esker, flyttes også ned
under priser."

- **Kicker fjernet**: `<div class="kicker">{brand_label}</div>` (f.eks.
  "DAILIES") sto over H1 -- mockupen har INGEN slik linje der (brødsmulen
  viser allerede merket). Fjernet helt fra `.hero-copy` -- enda mer
  kompakt, ingen tapt informasjon (merke er i brødsmulen +
  Product-schema uansett).
- **"Pris med frakt" er nå en ekte boks** (ikon + fet etikett + liten
  undertekst "Vis totalpris inkl. frakt" + en ekte glidende vippebryter i
  iOS-stil), ikke lenger en enkel pille med en liten prikk. Ny
  `.ship-chip-boxed`-modifier-klasse (IKKE en endring av selve
  `.ship-chip`/`.ship-chip-dot`, som linsevæske-/private label-alias-
  sidene fortsatt bruker uendret via `render_price_list()` sin egen,
  enklere chip). Samme `#ship-chip`-id, samme
  `aria-pressed`-klikkhåndtering i `_QTY_CALC_SCRIPT` -- kun det visuelle
  innholdet inni knappen er nytt, ingen JS-endring.
- **Fant og fikset en ekte bug fra tidligere i dag**: da fraktbryteren ble
  flyttet inn i `qty_box` (`render_winner_widget()`), ble den lagt til
  UBETINGET -- men linsevæske-/private label-alias-sidene fikk SIN
  fraktbryter fra et annet sted (`render_price_list()`, `show_ship_chip=
  True` som standard der). Resultat: to `id="ship-chip"`-elementer på
  samme side (ugyldig HTML, `getElementById` fant bare det første).
  Fikset med en ny `include_ship_chip`-parameter (standard `False`) --
  kun produktsiden sender `True`.
- **"Pris ved flere esker" flyttet ut av `qty_box`**, til rett under
  prislista (etter `{{offers_block}}`, før prisdisclosure-teksten) --
  egen ny `qty_multi_inline`-parameter (standard `True`, bevarer
  UENDRET oppførsel -- fortsatt inni kortet -- for de to andre
  sidetypene). `render_winner_widget()` returnerer nå et 3-tuppel
  (`winner_band, qty_box, qty_multi_html`) i stedet for 2 -- alle tre
  kallesteder oppdatert. Fikk sin egen kort-innpakning
  (`.wrap-product > .qty-multi`, scoped via direkte-barn-selektor) siden
  den delte `.qty-multi`-CSS-en forutsetter å ligge inni en hvit boks.

Testet: linsevæske-siden sjekket eksplisitt (kun 1 `#ship-chip`, "Pris
ved flere flasker" fortsatt inni sin opprinnelige hvite boks, gammel
enkel chip-stil uendret) -- ingen regresjon der. Produktsiden: ny
fraktbryter-boks fungerer (klikk verifisert -- bryter glir, blå farge,
vinnerkort/prisliste sorterer om korrekt), "Pris ved flere esker" står nå
som egen kortboks rett under prislista. Full sveip av alle 411 sider,
null duplikate `ship-chip`-id-er, ingen Traceback/NameError.

## Produktsiden: antallspiller + fraktboks på ÉN linje på mobil (2026-09-27, samme dag)

Kai, med skjermdump: "Da er det bare Å få denne rekken på plass.. på en
linje på mobil" -- pillene og fraktboksen sto fortsatt på hver sin rad.

- **Omstrukturert**: "Antall esker"-tittelen flyttet til sin egen linje
  ALENE (var tidligere i samme rad som fraktboksen -- `.qty-box-head`
  fjernet), og en ny `.qty-box-row` holder nå BARE pillene + fraktboksen
  sammen, `flex-wrap: nowrap` uansett bredde.
- **Kompakte piller, KUN på produktsiden** (`.wrap-product .qty-pill`):
  boks-ikonet og enhetsteksten ("eske"/"esker") under tallet er skjult --
  pillene viser nå bare selve tallet, akkurat som mockupen. Linsevæske-/
  private label-sidene beholder de fulle, større pillene uendret (egen
  rad der uansett, ingen fraktboks å dele plass med).
  Custom "Eget antall"-pillen (kun synlig ≥640px) mister også sitt
  blyant-ikon her, men selve "Eget"-teksten (ikke pakket i en `<span>`,
  så den treffes ikke av skjule-regelen) er fortsatt synlig og
  forståelig alene.
- **Under 480px** strammet fraktboksen ytterligere: undertekst ("Vis
  totalpris inkl. frakt") skjules helt, mindre padding, mindre
  vippebryter -- nødvendig for at 5 tallpiller + fraktboks faktisk skal
  få plass på én linje helt ned til 320px.

Testet: 320/375/700px -- `.qty-box-row` sin `scrollWidth` matcher
`clientWidth` eksakt på alle tre (ingen overflow), fraktbryteren fungerer
fortsatt (klikk verifisert, vinnerkort/prisliste sorterer om), "Eget
antall"-pillen ser grei ut ved 700px. Full sveip, ingen
Traceback/NameError.

## Produktsiden: tallet i antallspillene var ikke midtstilt (2026-09-27, samme dag)

Kai: "tall må midtstilles inne i boksen sin." Root cause:
`.wrap-product .qty-pill` byttet `flex-direction` fra `column` til `row`
(forrige runde, for å legge ikon+tall+enhet på én linje internt), men
`align-items: center` (arvet fra basisregelen) sentrerer kun KRYSS-aksen
-- som var HORISONTAL i `column`-modus (derfor så tallet sentrert ut før)
men ble VERTIKAL i `row`-modus. HOVED-aksen i `row`-modus styres av
`justify-content`, som ikke var satt og dermed falt tilbake til standard
`flex-start` (venstrejustert). Fikset med `justify-content: center;`
lagt til samme regel.

Testet: 375px, tallet sentrert i alle fem piller + "Eget"-pillen, full
sveip ingen Traceback/NameError.

## Prislista: "Laveste pris"/"Lavest totalpris"-merket fjernet + frakttekst kan bryte til 2 linjer på mobil (2026-09-27, samme dag)

Kai, med skjermdump fra live-siden på mobil: det grønne "LAVESTE
PRIS"-merket (`.lowest-tag`) brøt internt til to linjer ("LAVESTE"/
"PRIS") og dekket fraktteksten ved siden av, fordi `.offer-card` aldri
hadde noen mobil-spesifikk layout -- samme flate rad-oppsett tvinges
uansett skjermbredde. Kai vurderte deretter to ganger: først "ta bare
vekk den grønne Laveste pris i tabellen. Den skal ikke være der lengre",
så eksplisitt at det blå "Lavest totalpris"-merket (`.lowest-tag-total`,
vist når "Pris inkludert frakt" er på) også skulle bort -- "Ingen slike"
-- og til slutt at selve fraktteksten uansett skal kunne bryte til 1
eller 2 linjer etter mobilskjermens bredde, uten å overlappe verken
butikklogoen over eller prispillen ved siden av.

- **Merket fjernet helt**, alle steder: `{lowest_tag}` tatt ut av
  `render_offer_card()`s returnerte markup, den døde
  `lowest_tag =`-linjen fjernet (parameteren `tags_html` er nå ubrukt
  men beholdt i signaturen for å ikke måtte røre kallestedet),
  `tags()`-hjelpefunksjonen (+ `total_best`) i `render_price_list()`
  fjernet siden den kun bygde `tags_html`-strengen til det nå fjernede
  merket, og re-sorterings-JS-en i `_QTY_CALC_SCRIPT` som satte inn/tok
  ut `.lowest-tag`/`.lowest-tag-total`-spans på klientsiden ved
  frakt-toggle (+ de nå ubrukte `bestTotal`/`byTotal`/`isTotalBest`) er
  også fjernet. `.lowest-tag`/`.lowest-tag-total`-CSS-reglene slettet
  (ingen HTML refererer dem lenger). Den grønne `is-lowest`-bakgrunnen/
  kanten på selve kortet (satt via CSS-klasse, ikke tekstmerket) står
  fortsatt -- det er kun tekstboblen som er borte.
- **Mobil-layout lagt til** for `.offer-card`/`.offer-main`/
  `.offer-price-col`/`.offer-shipping` i en ny
  `@media (max-width: 699px)`-blokk (samme brytningspunkt som resten av
  sida): kortet stables (`flex-wrap: wrap` + `flex-basis: 100%` på
  begge de to underradene) slik at logo-raden og pris/frakt-raden aldri
  er på samme rad, og `.offer-shipping` mister sin `white-space: nowrap`
  (`white-space: normal; flex: 1; min-width: 0; align-items:
  flex-start;`) slik at fraktteksten kan bryte til 1-2 linjer inni sin
  egen plass ved siden av den fastbredde prispillen, i stedet for å
  presses av den. Kun mobil -- desktop uendret.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError, ingen gjenværende `lowest-tag`-referanser i bygget.
Live DOM-mål (ikke bare skjermbilde) på tre produktsider av ulik type
(kontaktlinse, linsevæske, private label) ved 320/375px: `.offer-main`
og `.offer-price-col` overlapper aldri, fraktteksten overlapper aldri
prispillen. Testet eksplisitt med en lang fraktstreng ("Gratis frakt
over 1 199 kr", trigges ved å bytte antall esker) -- bekreftet 2-linjers
bryting (dobbel høyde mot 1-linjes "Gratis frakt") uten overlapp, og
skjermbilde ved 375px bekrefter det visuelt.

## Produktsiden: Desktop Gold Standard v1, Steg 1 (2026-09-27, samme dag)

Kai delte et desktop-mockup + en fullstendig 26-punkts "Product Desktop
Gold Standard v1"-spec, i tillegg til et sett "Absolute Requirements"
som gjelder for hele resten av desktop-arbeidet: KUN desktop (mobil-Gold-
Standard-en skal forbli pixel/funksjonelt uendret), ALDRI slett
data/innhold (flytt, ikke fjern), ikke endre datamodellen for å passe
designet, bevar alt server-rendret/SEO-relevant innhold, og en
PASS/FAIL-innholdsbevaringssjekk skal rapporteres før noe kalles
ferdig. Gitt omfanget (26 punkter) implementeres spec-en i små,
testede steg -- samme disiplin som resten av produktside-arbeidet
denne dagen -- i stedet for én stor, uverifiserbar endring.

**Revisjon FØR koding** (per spec-ens eget punkt 7): sammenlignet
nåværende opplevd (via DOM-mål, IKKE skjermbilder -- se under)
desktop-rendring mot mockupen. Fant at flere punkter allerede var
implementert i tidligere runder samme dag (commit 8b8d2dd26: desktop
viser allerede ALLE tilbud uten "Vis alle priser"-kollaps -- spec-ens
punkt 12 -- og Savings Signal/`compute_savings_pct()` matchet already
eksakt spec-ens formel/avrunding/10%-terskel/"Spar X%"-ordlyd fra
punkt 7, og Winner Card inneholdt allerede KUN de tillatte feltene fra
punkt 6, ingen trust-badges/pokal/rating). Ingen kategori E
(sletting) identifisert -- alt gjenstående var additivt eller ren
CSS-omplassering, se punktvis under.

**Implementert i dette steget** (alt scoped til `render_product_page()`
sin egen `<style>`-blokk og HTML, `@media (min-width: 860px)` -- null
CSS-endring under 860px, verifisert eksplisitt, se Testet-avsnittet):

- **Kicker (merke/serie) over H1** (punkt 3) -- en tidligere runde
  samme dag (commit 9657bfb1d) fjernet bevisst en kicker over H1 PÅ
  MOBIL (for lite plass). Kai ba nå eksplisitt om den tilbake, men kun
  der det er plass: "Her kan også Soflens eller produsent vises, da
  det er plass til det." Ny `<p class="hero-kicker">` er `display:none`
  som standard, vises kun >=860px -- forener begge, tidligere
  motstridende avgjørelser korrekt uten regresjon på mobil.
- **Kompakt faktarad** (punkt 8, ny `_hero_facts_html()`-funksjon):
  "Dagslinse · 30 linser · Hilafilcon B · BC 8,6", maks 4 felt, BYGGET
  KUN fra faktisk dokumenterte `product["specs"]`-data (Brukstid,
  pakningsstørrelse fra samme `_pack_size_from_id()` som allerede
  brukes til søsken-pakning-lenken, Materiale, Basiskurve) -- viser
  rett og slett færre fakta når et felt mangler (f.eks. SofLens Daily
  Disposable har ikke Basiskurve/Diameter i katalogen) i stedet for å
  dikte opp et tall, i tråd med prosjektets stående "aldri gjett
  data"-regel. Samme `display:none`-til-860px-mønster som kickeren.
- **Product Stage: fra tre kolonner til to** (punkt 4 -- "Den midtre
  produkttekstkolonnen fjernes"): `.hero-main`s grid gikk fra
  `bilde | tekst | pris` til et 2-kolonners
  `grid-template-areas: "copy copy" "image price"` -- `.hero-copy`
  (kicker/H1/undertittel/fakta) spenner nå hele bredden i rad 1,
  bilde+Winner Card er rad 2. Ingen DOM-flytting nødvendig -- begge var
  allerede direkte grid-barn av `.hero-main`, kun CSS-en endret. Fjernet
  også en død `.hero-main .product-ai-summary`-grid-regel (AI-
  sammendraget flyttet til kunnskapssonen tidligere samme dag, denne
  regelen traff ingenting lenger).
- **Produktbildets størrelse strammet inn**: første forsøk lot bildet
  fylle hele den gjenværende kolonnebredden (815px) med aspect-ratio
  4:3, som ga et 611px høyt bilde -- latterlig dominerende ved siden av
  et 275px Winner Card. Fikset med `max-width: 480px` på
  `.hero-main .hero-product-image`, gir et 480×360px bilde og
  overskuddsplass som ren whitespace i cellen (i tråd med punkt 1: "Mye
  whitespace er ønskelig").
- **Quantity-boksen visuelt sammenslått med Product Stage-kortet**
  (punkt 9 -- "Fjern dagens store separate quantity-seksjon"): en ny,
  tom `<div class="product-stage">` pakker nå `.hero-card` OG
  `{{qty_html}}` sammen UTEN å flytte noen av dem i DOM-treet (fortsatt
  akkurat samme søsken-rekkefølge som før). `.product-stage` har ZERO
  CSS under 860px (usynlig wrapper), og får kortets bakgrunn/kant/
  padding kun >=860px, mens `.hero-card` og `.qty-box` mister sine EGNE
  kant/padding der -- fremstår som ett sammenhengende kort på desktop,
  helt uendret struktur på mobil. Denne wrapper-teknikken (ny tom div,
  ingen omorganisering) var bevisst valgt for å garantere mobil-
  pixel-likhet uten å måtte stole på at ingen andre regler utilsiktet
  arver noe fra en ny forelder.
- **Container-bredde** (punkt 1): `.wrap-product` var allerede
  `max-width: 1280px` (innenfor spec-ens 1200-1300px-mål) -- verifisert
  at den IKKE strekker seg ved 1920px (forblir 1280px, sentrert, ~312px
  luft på hver side).
- **Desktop viser alle tilbud** (punkt 12): allerede implementert i en
  tidligere runde samme dag (commit 8b8d2dd26) -- kun BEKREFTET på nytt
  her (0 skjulte `.offer-card` på en 5-butikkers og en 7-butikkers
  produktside, "Vis alle priser"-knappen `display:none` >=860px), ingen
  ny kode.

**Bevisst UTSATT til senere steg** (ingen sletting, kun ikke startet
ennå): punkt 13 (full tabell-hybrid prisliste -- spec-ens eksempel har
en uklar "Pris/eske" vs "Pris"-kolonne-distinksjon som bør avklares med
Kai før implementasjon, siden dagens kort kun viser ÉN prisverdi om
gangen); punkt 11 (ny "Sammenlign priser" + "X butikker med pris..."
undertekst -- lav risiko, men den eksisterende, fungerende "Priser for
N esker"-overskriften fra mobil-runden dekker det meste av behovet
alt); punkt 19 (kunnskapssonens 2-kolonners desktop-layout); punkt 20
(sticky purchase rail -- Kai selv: "Ikke prioriter før hoveddesignet
sitter"); punkt 5 (subtil CSS-bakgrunnsglød bak produktbildet, ren
kosmetikk).

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. **Mobil-uendret-verifisering** (Absolute
Requirement #1) via DOM, ikke bare skjermbilde: `.hero-kicker`/
`.hero-facts` bekreftet `display:none` ved 375px, `.product-stage`
bekreftet `border:0/background:transparent/padding:0` ved 375px (helt
usynlig wrapper), og et 375px-skjermbilde av produktsiden er
piksel-identisk med Gold-Standard-skjermbildet tatt tidligere samme
dag. **Desktop** verifisert via DOM-mål (skjermbilder upålitelige ved
disse vindusbreddene i denne browser-pane-en, se tidligere runder samme
dag) på flere produkter og bredder: 1280px (SofLens, 5 tilbud), 1280px
(Acuvue Moist, 7 tilbud, lang materiale-fakta-verdi), 1440px (Acuvue
Oasys Max Multifocal for Astigmatism, langt produktnavn -- H1 bryter
korrekt til 2 linjer i sin egen kolonne uten å presse Winner Card),
1920px (containerbredde bekreftet uendret). Linsevæske- og private
label-sidene (`render_solution_product_page`, egen, urørt hero-CSS)
verifisert å IKKE ha noen `.product-stage`/`.hero-kicker`-klasser i det
hele tatt -- null krysspåvirkning, som forventet siden alt er scoped
til `render_product_page()` sin egen lokale stilblokk.

**Innholdsbevaringssjekk** (spec-ens punkt 8): Eksisterende data/
innhold bevart: PASS (kicker+faktarad er nye, additive elementer;
full spesifikasjonstabell/FAQ/prishistorikk/kilder/metodikk i
kunnskapssonen urørt). Mobil uendret: PASS (se over). Server-rendret
antalls-fallback ("Pris ved flere esker") bevart: PASS, urørt.
Produktspesifikasjoner bevart: PASS. FAQ/prishistorikk/alternative
pakninger/kilder/metodikk/strukturert data/interne lenker: PASS, ingen
av disse er rørt i dette steget.

## Produktsiden: Desktop Gold Standard v1, Steg 1-rettelse -- ekte grid ga et "forferdelig" gap (2026-09-27, samme dag)

Kai, med skjermdump av den FAKTISKE live-siden (Dailies AquaComfort
Plus 90-pack, ikke bare den ene testet SofLens-siden): "Desktop vi
snakker om. Det ser helt forferdelig ut, og langt unna design som ble
forelagt deg." Skjermdumpet viste et stort, meningsløst tomt gap
mellom produktbildet og Winner Card -- bildet satt helt til venstre,
kortet langt ute til høyre, med en enorm tom flate mellom.

**Rotårsak**: Steg 1 sin CSS Grid-løsning (`grid-template-columns:
minmax(320px, 1fr) minmax(260px, 320px)`) lot `1fr`-kolonnen vokse til
å fylle HELE den ledige bredden (~815px på en 1280px-side), mens selve
bildet inni den kolonnen var begrenset til `max-width: 480px` (fikset i
en tidligere runde SAMME dag for å hindre et enda verre problem --
bildet ble 611px høyt uten den grensen). De resterende ~335px INNI
kolonnen, til høyre for bildet men til venstre for neste kolonne, ble
et rent, uforklarlig tomrom midt i kortet -- ikke pen "premium
whitespace" (som var intensjonen bak punkt 1 i spec-en), men et synlig
brutt layout. Ble ikke fanget opp av mine egne DOM-mål i forrige runde
fordi jeg kun målte AT elementene ikke overlappet og at bredder/
høyder var fornuftige hver for seg -- jeg målte aldri selve GAPET
mellom dem, som var det faktiske problemet.

**Fikset**: Byttet fra CSS Grid til Flexbox for bilde+Winner Card-raden
(`.hero-media-row { display: flex; gap: 56px }`, `.hero-main {
display: flex; flex-direction: column }` i stedet for grid). Med
flexbox og en FAST gap sitter bildet og kortet alltid rett ved siden
av hverandre med nøyaktig samme avstand uansett sidebredde -- ingen
elastisk kolonne som kan gape opp et tomrom. Eventuell overskudds-
bredde havner naturlig til HØYRE for begge (ren kant-whitespace, som
faktisk var intensjonen), i stedet for som et hull mellom dem.

Testet: bygget + `validate_build.py` OK, full sveip ingen Traceback/
NameError (fanget og fikset en selvpåført bug underveis -- ureskapte
CSS-klammer `{ }` i en kommentar inni f-string-en ga en `NameError:
name 'display' is not defined`, siden Python tolket dem som
f-string-uttrykk). DOM-mål på nøyaktig samme produkt Kai skjermdumpet
(Dailies AquaComfort Plus 90-pack, 1596px bredde -- samme vindusbredde
som skjermdumpet hans): gap mellom bilde og Winner Card nå eksakt
56px (var ~487px/et stort tomrom før). Mobil re-verifisert etter denne
rettelsen (samme produkt, 375px): skjermbilde fortsatt piksel-identisk
med godkjent Gold Standard.

**Lærdom for videre desktop-arbeid**: mål alltid selve GAPET/
avstanden mellom relaterte elementer eksplisitt (ikke bare hver
elements egen bredde/høyde/overlapp) når man bruker CSS Grid med `1fr`-
eller `minmax(..., 1fr)`-kolonner ved siden av et element med
`max-width` -- de to kan komme ut av synk og skape usynlige (for
DOM-målingene) men veldig synlige (for øyet) tomrom. Flexbox med fast
`gap` er tryggere for denne typen "to elementer skal sitte sammen som
en enhet"-layout.

## Produktsiden: Desktop Gold Standard v1 -- full ombygging til EKTE tre-kolonners hero (2026-09-27, samme dag)

Selv med gap-fiksen over var komposisjonen fortsatt feil -- Kai (via en
annen samtale han hadde parallelt om nøyaktig samme skjermbilde):
"Han har beholdt strukturen fra den gamle heroen og bare restylet
elementene. Vi spikret derimot en annen komposisjon." Den daværende
strukturen var i praksis tittel+fakta over HELE bredden øverst, med
bilde og Winner Card som to separate "øyer" i en rad under, og
quantity-kontrollene som en fullbredde rad helt nederst -- ikke
referansedesignet, som krever at bilde, produktidentitet+kontroller OG
Winner Card står side om side i ÉN rad, i samme vertikale
arbeidsflate. Kai sendte et helt konkret, målsatt spec (kolonne-
proporsjoner, bildehøyde, pillestørrelser, typografi-størrelser,
spacing-rytme, maks hero-høyde) og var eksplisitt: "Do not keep
tweaking margins on the current structure... If that relationship
[bilde+identitet/kontroller+Winner Card i samme rad] is not present,
the implementation is not finished."

**Ny teknikk -- `display: contents`-utflating i stedet for DOM-flytting**:
`.qty-box` (antall/frakt) er FORTSATT en egen, separat DOM-node --
søsken av `.hero-card` inni `.product-stage`, akkurat som i forrige
runde, av samme grunn (mobil skal forbli 100 % uendret). For å få
bilde, identitet OG kontroller inn i samme CSS Grid som Winner Card,
uten å flytte noe i treet: `.hero-card`, `.hero-main` og
`.hero-media-row` settes til `display: contents` KUN >=860px -- dette
fjerner elementenes egne bokser fra rendring, men lar barna deres
(`.hero-copy`, `.hero-product-image`, `.winner-band`) "boble opp" til å
bli DIREKTE grid-barn av `.product-stage`, sammen med `.qty-box` som
allerede var en direkte barn der. `display: contents` er kun satt inni
`@media (min-width: 860px)`, så mobilens DOM-boksmodell er
fullstendig upåvirket -- verifisert eksplisitt (se Testet).

**Grid-oppsett** (`.product-stage`, >=860px):
```
grid-template-columns: minmax(360px, 0.95fr) minmax(420px, 1.10fr) minmax(280px, 0.72fr);
grid-template-areas: "image identity price" "image controls price";
column-gap: 32px; row-gap: 40px;
```
`.hero-copy` → `identity` (rad 1, midtkolonne), `.qty-box` → `controls`
(rad 2, midtkolonne, `align-self: start`), `.hero-product-image` →
`image` (spenner begge rader, `align-self: center`, fast
`height: 320px`), `.winner-band` → `price` (spenner begge rader,
`align-self: center`, `width: 100%` av sin ~287px-kolonne). Målt på en
1440px-side: bilde 378×320px, midtkolonne 438px bred, Winner Card
287×275px, kolonnegap eksakt 32px begge steder -- alle tre innenfor
Kais oppgitte mål-mål.

**Typografi/spacing-rettelser** (Kais eksakte tall): H1 32px/700/1.18
line-height (var 1.6rem=25.6px), kicker 13-14px/uppercase/600/.06em
letter-spacing, undertittel 19.2px/400 (var 0.92rem/500), fakta
0.92rem/muted, faktarad→quantity-boks 40px (target 38-48px).
Quantity-pillene fikk faste mål (60×46px, "Eget" 88px, 8px gap) i
stedet for den elastiske `repeat(5/6, 1fr)`-grid-en fra mobil (som
ville strukket pillene til å fylle hele den nå smalere midtkolonnen),
og valgt-tilstand byttet fra mobilens blå gradient til en blek
mint-bakgrunn/grønn kant/mørk tekst (Kai, punkt 6: eksplisitt "Remove
the bright blue gradient selected state on desktop") -- KUN scoped til
`.product-stage .qty-pill`, mobilens `.qty-pill.is-active`-gradient
urørt.

**To selvpåførte bugs fanget og fikset underveis, FØR push**:
1. En kommentar inni f-string-en inneholdt uEscapede CSS-klammer
   (`{ display:grid; ... }`) -- Python tolket dem som f-string-uttrykk
   og kastet `NameError: name 'display' is not defined` ved bygging.
   Fikset ved å fjerne de bokstavelige klammene fra kommentarteksten.
2. Kicker-teksten ("DAILIES") rendret med feil skriftstørrelse
   (16px i stedet for tiltenkte 13,6px/0.85rem) -- en delt, global
   regel (`.hero-copy p { font-size: 1rem }`, brukt av forsidens hero)
   hadde HØYERE spesifisitet (klasse+type-selektor) enn den nye,
   enkle `.hero-kicker`-klassen, og vant kaskaden uansett kildeorden.
   Fikset ved å skjerpe selektoren til `.product-stage .hero-kicker`
   (to klasser, høyere spesifisitet enn `.hero-copy p`).
3. (Egentlig en tredje, fanget samtidig) Faktarad→quantity-avstanden
   (40px) var satt BÅDE som grid `row-gap` OG som en egen
   `margin-top: 40px` på `.qty-box` -- dobbel avstand (81px målt i
   stedet for 40px), som alene dyttet hele hero-høyden fra ~430px til
   473px, forbi Kais 400-450px-mål. Fjernet den overflødige
   `margin-top`, beholdt kun grid `row-gap`.

Testet: bygget + `validate_build.py` OK, full sveip ingen Traceback/
NameError. **Mobil** (Absolute Requirement #1) re-verifisert etter
HELE ombyggingen: `.hero-card`/`.hero-main` fortsatt `display:block`/
`flex` (IKKE `contents`) under 860px, `.product-stage` fortsatt
`border:0`/`display:block` (usynlig wrapper), kicker/fakta fortsatt
`display:none`, og et 375px-skjermbilde er piksel-identisk med
Gold-Standard-referansen. **Desktop** verifisert via DOM-mål (nøyaktig
samme produkt Kai skjermdumpet, ved BÅDE 1440px og 1600px -- Kais egne
oppgitte testbredder): bilde+identitet+Winner Card alle i samme
vertikale bånd (y-rekkevidder overlapper), hero-høyde 433px (mål
400-450px), pris-seksjonen starter på y=539 av en 1000px viewport
(godt innenfor "første viewport"-kravet). Testet også: langt
produktnavn (Acuvue Oasys MAX 1-Day Multifocal for Astigmatism
30-pack -- H1 bryter til 2 linjer i egen kolonne, ingen overflow, hero
kun 471px, fortsatt nær målet), produkt med kun 2 tilbud (Savings
Signal korrekt skjult, Winner Card 262px høy i stedet for 275px, ingen
krasj). Linsevæske-/private label-sidene bekreftet fortsatt UTEN
`.product-stage`/`.hero-kicker` i det hele tatt -- null
krysspåvirkning.

**Innholdsbevaringssjekk**: ingen data fjernet i denne runden heller --
kun CSS-layout (grid i stedet for flex/flex-kolonne) og typografi-
justeringer på eksisterende, allerede-rendrede elementer. Samme
elementer, samme DOM-noder, ny visuell plassering >=860px.

## Produktsiden: fraktbryteren flyttet til prislisteheaderen, "Eget antall" fjernet, ny "8"-pille (2026-09-27, samme dag)

Kai, i tre oppfølgende meldinger: (1) en "DESKTOP ONLY"-korreksjon om å
flytte "Pris med frakt"-bryteren ut av quantity-området og inn i
"Sammenlign priser"-headeren, (2) en MYE mer detaljert "MOVE SHIPPING
TOGGLE ONLY"-spec som OPPHEVET desktop-begrensningen ("This change
applies to: DESKTOP AND MOBILE") og i tillegg ba om at "Eget" fjernes
som antallsvalg, og (3) en siste presisering: erstatt "8" for "Eget" i
tallrekken (1,2,4,6,8,10 -- ikke lenger 1,2,4,6,10), og at
"Sortert etter pris (uten frakt)"-etiketten (der bryteren nå havner)
skal ERSTATTES av selve bryteren, ikke stå ved siden av den.

- **Frakt-bryteren flyttet fysisk** fra `.qty-box-row` (ved siden av
  antallspillene) til `.offers-head` i `render_price_list()` -- samme
  DOM-node, samme `id="ship-chip"`, samme click-delegasjon i
  `_QTY_CALC_SCRIPT` (ingen JS-endring nødvendig der). Ny, delt
  hjelpefunksjon `_ship_chip_boxed_html()` (var tidligere inline i
  `render_winner_widget()`) -- mistet også undertekst-linjen ("Vis
  totalpris inkl. frakt", Kai eksplisitt: "we do not need the current
  secondary line... Simply show: 🚚 Pris med frakt ○"). Ny
  `render_price_list()`-parameter `product_ship_chip_html` (kun
  produktsiden -- linsevæske-/øyedråpe-/private label-alias-sidene
  beholder sin egen, enkle, urørte "Pris inkludert frakt"-chip via den
  eksisterende `show_ship_chip`-mekanismen).
- **"Sortert etter pris"-etiketten fjernet** (KUN når
  `product_ship_chip_html` er satt) -- bryteren selv kommuniserer
  allerede hvilken prisbasis lista er sortert etter.
- **"Eget antall" fjernet på produktsiden**, erstattet av en ny fast
  "8"-pille -- seks faste antall nå (1/2/4/6/8/10), på både mobil og
  desktop. `render_winner_widget()` fikk to nye parametre,
  `qty_choices`/`include_custom_pill` (standard uendret:
  `(1,2,4,6,10)`/`True`, for å IKKE påvirke linsevæske-/øyedråpe-/
  private label-alias-sidene), og produktsiden sender inn
  `qty_choices=(1,2,4,6,8,10), include_custom_pill=False`.
- **Nesten-feil, fanget under testing**: `.qty-pills`-grid-regelen ble
  først forsøkt gjort unconditional `repeat(6, 1fr)` og scoped via
  `.wrap-product .qty-pills` -- men `.wrap-product` viste seg (grep
  bekreftet) å være DELT av `render_solution_product_page()`,
  `render_private_label_page()` OG `render_family_page()`, ikke
  eksklusiv for produktsiden slik en eldre kommentar hevdet! Dette
  ville ha lekket 6-pille-gridet (feil for disse sidene, som fortsatt
  har 5 faste + "Eget" = 6 KUN >=640px, 5 under) inn på tre urelaterte
  sidetyper. Fikset ved å scope via `.product-stage` i stedet -- den
  klassen finnes bekreftet KUN i `render_product_page()` sin egen DOM
  (innført i forrige runde som en usynlig wrapper-div, tilstede
  uansett skjermbredde), null krysspåvirkning. **Lærdom: `.wrap-product`
  er IKKE trygt å anta er produktside-eksklusiv i denne kodebasen --
  `.product-stage` er derimot bekreftet det.**

Testet: bygget + `validate_build.py` OK, full sveip ingen Traceback/
NameError. Produktsiden (mobil 320/375px OG desktop 1440px): 6 piller
(1,2,4,6,8,10), ingen "Eget", fraktbryter nå i prislisteheaderen
(bekreftet funksjonell -- klikk re-sorterer, endrer Winner Card-
heading til "Lavest totalpris", localStorage-tilstand bekreftet delt
mellom mobil- og desktop-visning av SAMME knapp), ingen
"Sortert etter"-tekst lenger, ingen horisontal overflow. Linsevæske-
siden (320px OG 700px): uendret -- 5 piller + "Eget" (skjult <640px,
bekreftet `display:none`→`block`), egen `#qty-custom-input` fortsatt
funksjonell (klikk på "Eget" åpner og fokuserer feltet), egen enkle
frakt-chip urørt. Private label-siden: samme, uendret (1,2,4,6,10,
custom).

## Produktsiden: Price Intelligence-modul, Steg 1 (2026-09-27, samme dag)

Kai delte et 31-punkts "Price Intelligence — Product Gold Standard v1"-
spec + godkjent mockup, med absolutte regler som overstyrer alt annet:
aldri finn på tall/trender, hvert tall skal beregnes fra faktisk
lagret data, skjul en metrikk heller enn å anslå den, og bygg det som
et gjenbrukbart rammeverk (ikke produktspesifikk kode). Gitt
omfanget -- 8 delmoduler, hver med sin egen data-kvalitetsport --
implementeres spec-en i etapper, samme disiplin som resten av
produktside-arbeidet denne dagen.

**Datavirkelighet undersøkt FØR noe ble bygget** (påkrevd av regel 2-4):
`price_history.json` inneholder i dag (2026-09-27) MAKS 45 dagers
historikk for ETHVERT produkt (155 av 203 produkter med historikk har
nøyaktig 45 dager, resten færre, 17 for lite til å vise noe i det hele
tatt). Dette betyr at 90 dager/6 måneder/1 år-periodene er
deaktiverte for ALLE produkter akkurat nå -- ikke en begrensning i
koden, men en direkte konsekvens av ekte data, og rammeverket
aktiverer dem automatisk etter hvert som `price_history.py` sin
`record_price()` legger til én dag per bygging. Hver rad har allerede
`date`/`price` (laveste PRODUKTPRIS, uten frakt -- matcher sidens
prisbasis-standard) OG `store` (vinnende butikk den dagen) -- sistnevnte
er det som gjør en fremtidig "Prisvinner over tid"-modul mulig i det
hele tatt.

**Implementert i dette steget** (`render_price_intelligence()`, ny
funksjon -- erstatter kun produktsidens `price_history_html`-kall; den
gamle `_render_price_history_chart()` er BEVISST urørt og brukes
fortsatt uendret av merke-/serie-sidenes `render_family_price_insight()`,
bekreftet i browser at begge lever side om side uten krysspåvirkning):

- **Sentralisert, deterministisk beregningsmotor** (regel 22: "Do not
  scatter arbitrary checks... Centralize the rules"):
  `_price_intelligence_eligible_periods()` (data-kvalitetsport per
  periode), `_price_intelligence_status()` (statusklassifisering:
  flat/historical_low/historical_high/down/up/stable, med
  dokumenterte, tallfestede terskler -- `STATUS_STABLE_TOLERANCE_PCT
  = 3.0`, `STATUS_FLAT_MIN_DAYS = 7`, regel 6: "Avoid meaningless
  claims caused by 1 kr fluctuations"), `_price_intelligence_metrics()`
  (lav/høy/median for et gitt periode-vindu -- median valgt over
  gjennomsnitt siden `record_price()` garanterer nøyaktig én
  observasjon per dag, altså konsistente daglige data, jf. regel 4).
- **Dekningsindikator**: "Vi har fulgt prisen siden {faktisk første
  dato}" -- aldri en påstått dato vi ikke faktisk har data fra.
- **Toppmetrikker**: Pris nå, Laveste registrerte pris (+dato),
  Høyeste registrerte pris (+dato), "{N}-dagers median" (N er alltid
  det faktiske antallet dager i det valgte vinduet, aldri hardkodet).
- **Deterministisk statuskort** med ikon, f.eks. "Stabil pris /
  Laveste produktpris har vært 262 kr i 30 dager" eller "Pris ned /
  Laveste produktpris har falt 6 % de siste 30 dagene" -- ALDRI en
  KI-generert kommentar (regel 5), kun tekst fra malene over.
- **Periodevelger**: alle 5 perioder vises alltid (regel 7's mockup-
  visning), men kun de faktisk kvalifiserte er klikkbare -- de
  deaktiverte har `disabled`-attributt + forklarende `title`. Samme
  no-JS-vennlige fane-mønster som `render_family_price_insight()`
  allerede etablerte (alle paneler ferdigbygget i DOM-en, ren CSS
  `.active`-klassestyring, fungerer uten JS også -- viser bare første
  panel).
- **Strammere graf** (ny `_render_price_intelligence_chart()`, egen
  funksjon -- IKKE en endring av den gamle): 140px høy (var 180px),
  restrained rutenett (2 linjer i stedet for 3), ingen synlig prikk
  per dag (kun siste punkt, regel 8), usynlige brede hover-mål
  beholder ekte per-dag-tooltip (dato + pris + butikk) via SVG
  `<title>` -- ingen JS-bibliotek, akkurat som originalen.
- **"Kort oppsummert"**: fra strukturerte maler (regel 20), ikke fri
  AI-tekst.

**Ekte bug fanget og fikset under egen testing** (før noe ble sendt til
Kai): "flat"-statusens oppsummeringstekst påsto først at dagens pris
var "både laveste og høyeste registrerte pris i perioden" -- sant når
prisen er flat i HELE det valgte vinduet, men FEIL når `flat_days`
(f.eks. 7) er kortere enn hele perioden (f.eks. 30 dager), siden
prisen da faktisk kan ha vært annerledes tidligere i vinduet (fant et
ekte eksempel: PureVision2 for Astigmatism 6-pack, pris 505→554 kr
over 30 dager, men flat på 554 kr de siste 7). Dette var akkurat den
typen "feilrepresentert tall" regel 2/3 eksplisitt forbyr. Fikset ved
å skille to tilfeller: `flat_days >= n_days` (faktisk flat hele
perioden, opprinnelig setning beholdt) vs. `flat_days < n_days` (ny,
presis setning: "har vært uendret på X kr de siste N dagene", uten å
påstå noe om resten av perioden).

**Bevisst UTSATT til senere steg** (rammeverket støtter dem allerede
strukturelt, ingen omskriving nødvendig når de bygges): Prisforskjell
mellom butikkene (krever live `offers`, ikke historikk-data),
Prisvinner over tid (krever iterering over `store`-feltet per dag +
en eksplisitt, dokumentert uavgjort-regel, regel 14), Kjøper du flere
esker (krever qty-motoren som allerede finnes i
`render_winner_widget()`). Alt dette er rent additivt -- ingenting av
det som allerede finnes på siden fjernes i mellomtiden.

## Produktsiden: Price Intelligence-modul, Steg 2 -- Prisforskjell + Prisvinner over tid (2026-09-28)

Kai ba om de neste to av de tre gjenstående kortene fra 31-punkts-
spec-en: "Prisforskjell mellom butikkene" og "Prisvinner over tid".
("Kjøper du flere esker?" fortsatt utsatt -- krever en egen runde mot
qty-motoren.)

- **`_price_intelligence_merchant_spread(offers)`** (regel 10-12):
  bygger PÅ `_savings_eligible_offers()` (samme sammenligningsgrunnlag
  som Winner Card sin Savings Signal -- utelater utsolgte/`is_stale`-
  tilbud), qty=1, uten frakt (sidens standardbasis). Krever >=2
  gyldige tilbud, ellers vises kortet ikke i det hele tatt (en
  "spredning" mellom kun ett tilbud er meningsløs). `spread_pct`
  regnes EKSAKT som Savings Signal og avrundes alltid NEDOVER (regel
  12). CURRENT data, ikke historikk -- vises derfor KUN én gang (ikke
  duplisert per periode-fane).
- **`_price_intelligence_merchant_winners(history)`** (regel 13-16):
  teller `store`-feltet per dag i HELE historikken (samme "mest
  komplette, mest ærlige bilde"-begrunnelse som dekningsdatoen,
  uavhengig av valgt periode-fane). Viktig oppdagelse om uavgjort-
  regelen (regel 14): `price_history.json` lagrer KUN vinner-butikken
  per dag (samme `reconcile_product()`-kall som avgjør "laveste pris"
  på selve siden den dagen) -- en eventuell uavgjort er derfor
  ALLEREDE avgjort deterministisk av `reconcile_product()` sin egen
  tie-break-nøkkel i det øyeblikket dataen ble lagret. Denne modulen
  har ingen tilgang til de andre tilbudene for en historisk dag (kun
  vinneren finnes lagret), og kan derfor verken gjenoppdage eller
  telle en historisk uavgjort-situasjon i etterkant -- den teller
  ganske enkelt den allerede-tie-brutte, lagrede vinneren per dag.
  "Prisvinneren har endret seg N ganger"-linjen vises kun når N>0
  (regel 16: "A zero is not automatically interesting").
- **"Kort oppsummert" utvidet**: `_price_intelligence_summary_text()`
  tar nå en valgfri `spread`-parameter og legger til én ekstra setning
  ("Det er 29 % prisforskjell mellom billigste og dyreste butikk
  akkurat nå") når spredningsdata finnes -- matcher regel 20 sitt
  eget eksempel ordrett. Utelates helt (ingen tom/feil setning) når
  spread er `None`.
- To nye kort i en `.price-intel-cards`-rad, stables på mobil (regel
  27), side om side på desktop (regel 28) -- lagt til ETTER periode-
  fanene, ikke inni dem, siden ingen av kortene er periode-avhengige.
  "Prisvinner over tid" viser en enkel horisontal stolpe per butikk
  (bredde relativt til øverste butikks dagantall, ikke til periodens
  totale lengde -- et vanlig, lesbart "leaderboard"-mønster).

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Verifisert i browser: et produkt med rik data
(Dailies AquaComfort Plus 90-pack, 45 dagers historikk, 5 tilbud) --
begge kort korrekt utfylt (Synsam 44/45 dager som vinner, Lenson 1
dag, "prisvinneren har endret seg 1 gang", 29 % spredning, "Kort
oppsummert" inkluderer nå spredningssetningen). Kritisk kantcase
testet: et produkt med KUN ÉTT tilbud (Biofinity Multifocal Toric
3-pack) -- Prisforskjell-kortet korrekt usynlig (ingen "spredning" med
ett tilbud), Prisvinner-over-tid-kortet vises fortsatt korrekt (én
butikk, 45 av 45 dager), OG "Kort oppsummert" utelater riktig
spredningssetningen i stedet for å vise en tom/feil setning. Mobil
(375px, kort stables i kolonne) og desktop (1440px, kort side om
side) begge sjekket, ingen horisontal overflow. Merke-siden (`/merke/
acuvue/`) bekreftet fortsatt kun å bruke den gamle `.price-insight`,
ingen `.price-intel-cards` der -- null krysspåvirkning.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Bekreftet fil-encoding var korrekt UTF-8 (`å` =
riktig kodepunkt 0xe5) da et terminal-visningsartefakt først så ut som
korrupsjon. Verifisert på flere produkter med ulik datahistorikk:
45-dagers (Dailies AquaComfort Plus 90-pack -- alle 5 toppmetrikker +
"stable"-status korrekte), eksakt 30-dagers grense (Acuvue Oasys MAX
1-Day for Astigmatism -- "30 dager" korrekt aktivert akkurat ved
grensen), <7 dagers (Acuvue Oasys 1-Day with Hydraluxe 180-pack --
modulen korrekt usynlig, ingen krasj), ekte "flat"-status (Acuvue
Oasys 6-pack, 262 kr i 30 sammenhengende dager), ekte "down"-status
(ULTRA 6-pack, -6 % over 30 dager, korrekt mint-farget statuskort).
Periodevelger-fanebytte testet i browser (klikk "All historikk" -->
panel bytter til 45-dagers median, ingen JS-feil). Mobil (375px) og
desktop (1440px) begge sjekket -- ingen horisontal overflow, resten av
produktsidens hero/quantity-seksjon uendret. Merke-siden (`/merke/
acuvue/`) bekreftet å fortsatt bruke den GAMLE, urørte grafen
(`.price-insight`/`.price-history-chart`, ikke `.price-intel`) --
null krysspåvirkning.

## Price Intelligence: rullet ut til ALLE produkttyper + flyttet oppover i rekkefølgen (2026-09-28)

Kai, eksplisitt scope-avklaring: "Produktsider design og setup,
statistikker og alt, gjelder alle produkter på domenet
kontaktlinser.no. d.v.s. alle kontaktlinser, egne merkenavn
kontaktlinser, og alle Tilbehør produkter." Oppfulgt med et bevisst
valg (via spørsmål, "Start nå"): linsevæske/øyedråper skal OGSÅ ha
det nye designet, siden de uansett deler samme rendrings-funksjon som
Tilbehør (`render_solution_product_page()`, atskilt kun av
`solution_category`-feltet -- umulig å gi Tilbehør nytt design uten
enten å påvirke linsevæske/øyedråper også, eller bygge en betinget
gren. Kai valgte "alle tre skal ha nytt design" -- ingen betinget
gren nødvendig).

**Rekkefølge-fiks på selve kontaktlinse-produktsiden** (gjelder først,
før resten): Kai: "Prisutvikling skal komme rett under/etter
produktene på både mobil og desktop, da det er vesentlig." Modulen lå
tidligere langt nede i kunnskapssonen (etter produktbeskrivelse,
badges), flyttet nå til å stå RETT ETTER `{offers_block}` (prislista)
-- før "Pris ved flere esker", metodikk-avsnittet og
pakningsstørrelse-/serie-lenkene. Ren HTML-kildeorden-endring, samme
CSS/JS uendret, gjelder derfor automatisk begge skjermbredder.

**Retrofit -- Price Intelligence-modulen nå på alle tre produkttyper**:
`render_solution_product_page()` (linsevæske/øyedråper/Tilbehør, 60
sider) og `render_private_label_page()` (egne merkenavn-kontaktlinser,
64 sider) hadde IKKE noen prisutviklingsgraf i det hele tatt fra før
-- ren tillegg, ingen eksisterende funksjonalitet endret eller
fjernet. Begge kaller nå `render_price_intelligence()` (samme
funksjon som kontaktlinse-produktsiden), rett etter sin egen
`{offers_block}`, med riktig `unit_singular` ("flaske" for
linsevæske/øyedråper) og riktig historikk-nøkkel (private label
gjenbruker `real_product["id"]`, siden det er nøyaktig samme fysiske
vare/historikk som hovedproduktsiden allerede sporer -- IKKE en egen
serie). `generate_pages.py` sine kallesteder oppdatert til å sende inn
`price_history.get(product["id"], [])` / `price_history.get(real_product["id"], [])`.

**CSS flyttet fra lokal til delt** (nødvendig forutsetning for
retrofiten): `.price-intel*`-reglene lå i `render_product_page()` sin
EGEN `<style>`-blokk (ikke delt) -- flyttet til `SHARED_STYLE`
(global, rett ved siden av den allerede-delte `.price-history-*`-
grafstilen den bygger videre på), slik at de to andre funksjonene får
riktig styling uten duplisert CSS. Verifisert at `render_product_page()`
selv ser identisk ut etter flyttingen (kun hvor reglene er definert
endret, ikke hva de gjør).

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Rekkefølge bekreftet i DOM på kontaktlinse-
produktsiden: `.price-intel` kommer nå rett etter `.offers`, før
`.qty-multi`. Linsevæske-siden (ReNu Multi-Purpose 60 ml, 45 dagers
historikk) -- full modul rendret korrekt med riktig CSS-styling
(hvit bakgrunn, 16px radius, mint "Pris nå"-farge -- beviser SHARED_
STYLE-flyttingen fungerer), riktig "flaske"-enhet gjennom hele
modulen inkl. "Basert på priser uten frakt, for 1 flaske." Private
label-siden (Ascend Active 1 Day) -- `.price-intel` bekreftet rett
etter `.offers` i DOM-rekkefølgen. Tilbehør-siden (SWATI Lens Case &
Tweezers) -- KORREKT usynlig modul (dette spesifikke produktet har
under 7 dagers historikk ennå, kun 2 Tilbehør-produkter finnes i det
hele tatt akkurat nå), ingen krasj, ingen overflow. Desktop (1440px)
sjekket på linsevæske-siden -- 5-kolonners toppmetrikk-grid + begge
nye kort (Prisforskjell/Prisvinner) rendret identisk med kontaktlinse-
produktsiden. Merke-siden (`/merke/acuvue/`) sin GAMLE graf
(`.price-history-chart`, delt av `render_family_price_insight()`)
bekreftet fortsatt riktig stylet etter CSS-flyttingen -- ingen
regresjon der.

**IKKE gjort ennå** (neste, større steg): selve hero-/quantity-/
frakt-bryter-ombyggingen (Mobile + Desktop Gold Standard v1) er
FORTSATT KUN på kontaktlinse-produktsiden. `render_solution_
product_page()` og `render_private_label_page()` bruker fortsatt sin
opprinnelige, eldre hero-layout (`.hero-card-solution` m.fl.) og
gamle antallsvelger/frakt-plassering. Dette er en betydelig større
retrofit (samme skala som selve Gold-Standard-arbeidet var i dag) og
tas i egne, separate runder.

## Hero-/quantity-redesign rullet ut til linsevæske/øyedråper/Tilbehør + private label (2026-09-28, samme dag)

Kai: "Nå gjør du samme hero-/quantity-redesign på linsevæske og
private label." Rett oppfølging av dagens scope-avklaring.

**Nøkkeloppdagelse som gjorde retrofiten mye rimeligere enn fryktet**:
`render_solution_product_page()` (linsevæske/øyedråper/Tilbehør) OG
`render_private_label_page()` deler ALLEREDE én felles CSS-konstant,
`HERO_IMAGE_STYLE` -- den inneholdt fortsatt den GAMLE tre-kolonners
heroen (bilde | tekst | pris) som Kai eksplisitt avviste for
kontaktlinse-produktsiden tidligere samme dag ("Han har beholdt
strukturen fra den gamle heroen..."). Siden BEGGE mål-funksjonene
allerede refererer denne ene konstanten, holdt det å skrive OM
`HERO_IMAGE_STYLE` sitt innhold til Product (Desktop) Gold Standard-
mønsteret én gang -- ingen duplisering, begge funksjoner fikk det nye
designet fra samme endring. `render_product_page()` sin EGEN, allerede
testede/skipede CSS-kopi er bevisst IKKE migrert til denne konstanten
i denne runden (null risiko for regresjon på allerede fungerende
kode) -- ren kopiering av mønsteret inn i HERO_IMAGE_STYLE i stedet.

**HTML-omstrukturering** (identisk mønster i begge funksjoner):
- `.hero-card` + `qty_html` pakket inn i en ny `<div class="product-stage">`
  (samme usynlig-på-mobil wrapper-teknikk som kontaktlinse-produktsiden).
- `.hero-main` sine barn omorganisert til `.hero-copy` FØRST, så en ny
  `.hero-media-row` som pakker bilde+Winner Card sammen -- eksakt samme
  DOM-mønster som kontaktlinse-produktsiden, slik at ALL eksisterende
  `.hero-media-row`/`.product-stage`-CSS (nå i HERO_IMAGE_STYLE) treffer
  uten en eneste ny selector.
- `{ai_summary_html}` flyttet UT av `.hero-main` (den blå
  "Vi sammenligner priser..."-boksen har ingen grid-area i det nye
  mønsteret) -- rendres nå rett under `.product-stage` i stedet, samme
  sted omtrent som før relativt til resten av siden. Rent additivt,
  ingenting fjernet.
- Eksisterende innhold (kicker, H1, beskrivelse, `price_per_unit_html`
  for linsevæske/øyedråper; "X er egentlig Y"-forklaringen for private
  label) beholdt UENDRET i `.hero-copy` -- kun omplassert i layouten,
  ikke omskrevet eller flyttet til kunnskapssone (beskrivelsene her er
  korte nok, 62-218 tegn, til at det ikke var nødvendig).
- Antallsvelger: samme `qty_choices=(1,2,4,6,8,10)`/
  `include_custom_pill=False` som kontaktlinse-produktsiden -- "Eget
  antall" fjernet her også, for konsistens på tvers av ALLE
  produkttyper.
- Fraktbryter: byttet fra den gamle enkle prikke-chippen til den
  boksede `_ship_chip_boxed_html()`-varianten, i prislisteheaderen
  (samme `product_ship_chip_html`-mekanisme som kontaktlinse-
  produktsiden).

**Én reell bug fanget og fikset i egen testing**: `.hero-card-solution
.hero-product-image { aspect-ratio: 1/1; height: auto; }` (en
eksisterende regel i `render_solution_product_page()` sin egen lokale
stilblokk, for å gjøre flaske-/tubebilder kvadratiske på mobil) hadde
INGEN media-query-grense -- den fortsatte å gjelde på desktop også, og
siden den kommer SENERE i kildekoden enn den nye `.product-stage
.hero-product-image { height: 320px }`-regelen (samme spesifisitet,
kildeorden avgjør uavgjort), VANT den gamle regelen og presset bildet
til en 378×378px firkant i stedet for 378×320px. Fikset ved å pakke
den gamle regelen inn i `@media (max-width: 859px)` -- den var uansett
kun ment for mobil.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Begge funksjoner sjekket på BÅDE mobil (375px)
og desktop (1440px): `render_solution_product_page()` -- linsevæske
(ReNu Multi-Purpose 60 ml, full layout + fungerende fraktbryter
bekreftet via klikk, `aria-pressed` og Winner Card-heading endret
korrekt), peroksidbasert linsevæske (AOSept Plus 360 ml, safety-notice
fortsatt rendret riktig etter `.product-stage`), øyedråper (Add1 10
ml), Tilbehør (SWATI Lens Case & Tweezers) -- alle fire uten
overflow, riktig 6-pille antallsvelger. `render_private_label_page()`
(Ascend Active 1 Day) -- egen-illustrasjon-bildet (`.pli-hero`)
rendrer korrekt i det nye 320px-høye bildeområdet, `private-label-
explainer`/`private-label-caveat`/"Se full produktside for..."-lenken
alle fortsatt til stede uendret. Kontaktlinse-produktsiden selv
(`render_product_page()`, bruker IKKE `HERO_IMAGE_STYLE`) bekreftet
100 % upåvirket av hele denne runden.

## Rettelse: "Pris ved flere esker" + blå oppsummeringsboks faktisk flyttet ned (2026-09-28, samme dag)

Kai, med skjermdump av iWear Oxygen XR (private label): "Her er pris
ved flere esker og den delen med blå bakgrunn ikke flyttet ned." Reell
miss i forrige runde -- jeg omstrukturerte hero/quantity-layouten på
`render_solution_product_page()`/`render_private_label_page()`, men
glemte at `render_winner_widget()` sitt `qty_multi_inline`-argument
(standard `True`) fortsatt lot "Pris ved flere X" ligge INNI
antallsboksen, og `ai_summary_html` (den blå boksen) havnet rett under
`.product-stage` i stedet for langt nedi siden, slik den allerede var
plassert på kontaktlinse-produktsiden.

- Begge funksjoners `render_winner_widget()`-kall fikk
  `qty_multi_inline=False` (fanger nå `qty_multi_html` i stedet for å
  forkaste den som `_qty_multi_html`), og `{qty_multi_html}` rendres nå
  som et eget kort rett etter `{price_history_html}` -- samme
  rekkefølge som kontaktlinse-produktsiden.
- `{ai_summary_html}` flyttet fra "rett under product-stage" til rett
  FØR `{product_faq_html}` (etter disclosure-avsnittet, private label-
  forklaringen/-forbeholdet) -- betydelig lenger ned, matcher
  kontaktlinse-produktsidens plassering langt nede i innholdet i stedet
  for øverst i kjøpssonen.
- Ny delt CSS-regel `.wrap-product > .qty-multi {{...}}` lagt til
  `HERO_IMAGE_STYLE` (samme "egen hvit kortboks"-styling som
  kontaktlinse-produktsiden allerede hadde lokalt) -- uten den ville
  det nye frittstående kortet vært ustylet.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. DOM-rekkefølge bekreftet på det EKSAKTE produktet
Kai skjermdumpet (iWear Oxygen XR): `.product-stage` → `.offers` →
`.price-intel` → `.qty-multi` (egen kort) → ... → `.disclosure` →
`.product-ai-summary` -- riktig på både mobil (375px) og desktop
(1440px), ingen overflow. Samme rekkefølge bekreftet på en
linsevæske-side (ReNu Multi-Purpose 60 ml). Kontaktlinse-produktsiden
sin egen, urørte rekkefølge dobbeltsjekket uendret.

## Full SEO/AI/mobil-revisjon av hele nettstedet (2026-09-28, samme dag)

Kai: "kjør en skikkelig SEO, AI, mobil osv sjekk av hele
kontaktlinser.no." Bygget et systematisk Python-revisjonsskript (i
scratchpad, ikke i repoet) som skanner ALLE 412 bygde HTML-sider for
title-tagger, meta-beskrivelser, canonical-tagger, H1-er, viewport-
meta, Open Graph-tagger, JSON-LD-gyldighet, bilde-alt-tekster og
interne lenker som peker på sider som faktisk ikke finnes -- aldri
gjettet, kun faktisk skannet data.

**Sterk grunnlinje** (ingen funn): 0 manglende/dupliserte title-
tagger, 0 manglende/dupliserte meta-beskrivelser, 0 manglende/feil
canonical-tagger, hver side har nøyaktig 1 H1, alle sider har
viewport-meta, 0 `<img>`-tagger uten alt-tekst, 0 sider uten JSON-LD,
0 ugyldig JSON-LD.

**Reelle funn, fikset**:
1. **4 ekte, brukte interne lenker pekte på gamle, pre-migrerte URL-
   slugs** (9 forekomster i guide-innhold, f.eks.
   `/kontaktlinser/acuvue/oasys-6-pack/` i stedet for
   `/kontaktlinser/acuvue/acuvue-oasys-6-pack/`). Disse ga en EKTE
   404 for enhver bot/bruker som ikke kjører JavaScript -- GitHub
   Pages har ingen server-side redirect, kun en klientsidevis JS-
   oppslag mot `LEGACY_REDIRECTS` på selve 404-siden, som ikke
   hjelper crawlere som ikke kjører JS (og som uansett allerede har
   mottatt en 404-statuskode). Fikset ved å peke lenkene direkte på
   de riktige URL-ene (samme mapping som allerede fantes i
   `LEGACY_REDIRECTS`, bare aldri brukt til å rette selve
   kildelenkene).
2. **`llms.txt` sin metodikk-beskrivelse var faktisk feil**: påsto at
   rangeringen "alltid følger total pris (produktpris + frakt)" -- men
   sidens faktiske, veletablerte standard (bekreftet gjennom hele
   økta) er produktpris UTEN frakt som standard, med "Pris inkludert
   frakt" som en opt-in-bryter. Rettet ordlyden i `llms.txt` (repo-rot,
   kopieres inn i bygget av CI) til å stemme med faktisk atferd --
   spesielt viktig siden denne filen er skrevet spesifikt for AI-
   systemer å lese, og en feilaktig påstand der undergraver akkurat
   den typen tillit resten av økta har vært så nøye med.
3. **Ekte mobil-overflow-bug på ALLE merke-sider** (`/merke/X/`,
   dusinvis av sider): en sammenlign-tabell (`.brand-compare-card`)
   tvang HELE siden til å bli 761px bred på en 375px mobilskjerm.
   Rotårsak, funnet via DOM-inspeksjon (ikke gjettet): tabellen hadde
   allerede en `overflow-x:auto`-innpakning, men selve grid-barnet i
   `.brand-compare-row` (en uklasset `<div>{tabell}</div>`-wrapper,
   `compare_table_html_wrapped`) arvet CSS Grid sin standard
   `min-width: auto`, som nekter et grid-barn å krympe under bredden
   til innholdet sitt -- uavhengig av at tabellen INNI den allerede
   hadde sin egen scroll-mekanisme. Fikset med `min-width:0` på selve
   wrapper-diven (pluss `min-width:0` på `.brand-compare-card` som
   ekstra sikkerhet). La også til samme `overflow-x:auto`-sikring
   defensivt på `.spec-table-card` (serie-/familiesidenes
   sammenlign-tabell) -- ikke bekreftet å faktisk overflow-e i dag,
   men samme sårbarhetsmønster, billig forsikring.

**Rapportert til Kai, IKKE endret uten hans bekreftelse** (påvirker
synlig SEO-tekst på tvers av mange sider, redaksjonell vurdering):
- 146 sider har `<title>` over 60 tegn (Google trunkerer typisk rundt
  60-65 tegn). Verstingene er produsent-sidene (`/produsent/X/`, 88-112
  tegn) siden malen lister ALLE merker produsenten eier i selve
  tittelen (f.eks. "CooperVision – Produsenten bak Biofinity, Proclear,
  MyDay, Avaira, Clariti, Biomedics og Live | Kontaktlinser.no" = 112
  tegn). Resten er hovedsakelig guide-sider (65-84 tegn) fra naturlig
  norsk frasering -- lavere prioritet.
- 26 merke-sider (`/merke/X/`) har meta-beskrivelser over 165 tegn
  (opptil 227), siden malen lister 3 eksempelprodukter ved navn --
  merker med lange produktnavn (Acuvue, Air Optix) sprenger Googles
  ~155-160-tegns visningsgrense i SERP.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Revisjonsskriptet kjørt på nytt etter hver
fiks for å bekrefte 0 gjenværende ekte brukne lenker (kun 2 kjente
falske positiver fra skriptets egen path-sjekk, statiske
fontfiler/favicon som faktisk finnes). Mobil-overflow-fiksen
verifisert på 5 ulike merke-sider (Acuvue, Dailies, Biofinity, Air
Optix, Biotrue) ved 375px -- alle nå `scrollWidth === innerWidth`,
ingen overflow. Desktop (1440px) på samme side dobbeltsjekket
uendret. Tabellen er fortsatt fullt brukbar på mobil -- ren
horisontal scroll INNI sitt eget kort, ikke skjult/fjernet
innhold.

## Mobil hero: linsevæske/øyedråper/Tilbehør og private label matcher nå kontaktlinse-produktsiden nøyaktig (2026-09-29)

Kai, ny dag: "på optikerkjedenes egne merkevarer på mobil, ser det ut som
den ikke er lik som de andre produktsidene. og samme med alle produkter
innunder tilbehør, som inkluderer linsevæske osv.. Vi skal ha en lik side
for produktsider på mobil. for alle produktsider." + "spør hvis du er
usikker".

**Reell, konkret forskjell** (bekreftet via mobil-skjermbilder, ikke bare
kode-lesing): kontaktlinse-produktsiden sin mobile hero (Gold Standard v1,
se tidligere runder) viser KUN kicker (skjult), H1 og "Sammenlign priser"
-- ingen forklaringstekst i selve kjøpskortet. `render_solution_product_page()`
og `render_private_label_page()` hadde derimot fortsatt en synlig kicker PÅ
MOBIL, pluss en hel avsnitt forklaringstekst inni `.hero-copy` (produkt-
beskrivelsen for linsevæske/øyedråper/Tilbehør, "X er egentlig Y..."-
forklaringen for private label) -- gjorde heroen synlig høyere/tyngre enn
referansen.

**Avklart med Kai via spørsmål** (reelt innholds-tradeoff, spesielt for
private label sin identitetsforklaring): valgte BEGGE anbefalte alternativer
-- (1) flytt ALL forklaringstekst ut av mobil-heroen, for begge sidetyper,
også private label sin "det er samme produkt som..."-forklaring, slik at
heroen blir like kompakt overalt; (2) skjul kickeren på mobil her også
(vis kun på desktop), samme mønster som kontaktlinse-produktsiden allerede
har.

**Implementert** (kun `.hero-copy`-markupen i de to funksjonene, ingen
`HERO_IMAGE_STYLE`-CSS-endring nødvendig -- `.hero-kicker`/`.hero-subtitle`
fantes allerede der fra Gold Standard-retrofiten dagen før, bare ikke i
bruk i selve markupen ennå):
- `render_solution_product_page()`: `<div class="kicker">`→
  `<div class="hero-kicker">`, og den inline lange beskrivelsen +
  `price_per_unit_html` erstattet med `<p class="hero-subtitle">Sammenlign
  priser</p>`. Beskrivelsen er IKKE slettet -- flyttet til en ny
  `<h2>Om {produktnavn}</h2><p>{beskrivelse}</p>{price_per_unit_html}`-
  seksjon rett før `{ai_summary_html}` (etter prisdisclosure-avsnittet),
  samme "flytt, ikke fjern"-prinsipp som resten av mobil-redesignet denne
  uken.
- `render_private_label_page()`: samme kicker-bytte, og
  "det er samme produkt som X, bare i egen innpakning..."-forklaringen
  erstattet med samme `hero-subtitle`. INGEN ny seksjon trengtes her --
  bekreftet via en eksisterende kodekommentar at akkurat dette innholdet
  allerede er dekket av `.private-label-explainer`-boksen lenger ned på
  siden (bevisst utelatt fra FAQ-en av samme grunn) -- å legge det til på
  nytt et sted til hadde vært ren duplisering, ikke tapt informasjon.

Testet: bygget + `validate_build.py` OK (201/201 produkter har priser),
full sveip ingen Traceback/NameError. Verifisert i browser-panelet BÅDE
mobil (375px) og desktop (≥860px) på iWear Oxygen XR (private label) og
ReNu Multi-Purpose 60 ml (linsevæske): mobil viser nå nøyaktig samme
kompakte mønster som referansen (ingen synlig kicker, H1 + "Sammenlign
priser", ingen forklaringstekst i kjøpskortet); desktop viser kickeren
korrekt igjen (RENU / EGET MERKENAVN), og den nye "Om ReNu..."-seksjonen
på linsevæske-siden rendrer riktig med beskrivelse + pris-per-enhet, uten
noe hull i `.product-stage`-gridets identitetsområde. Regresjonssjekket i
tillegg: en peroksidbasert linsevæske (AOSept Plus 360 ml -- safety-notice-
boksen rendrer fortsatt riktig rett under heroen) og et Tilbehør-produkt
(SWATI Lens Case & Tweezers) på mobil, begge korrekte. Kontaktlinse-
produktsiden (`render_product_page()`) er ikke rørt i denne runden --
egen, allerede testet lokal CSS-kopi, ingen risiko for krysspåvirkning.

## Private label-merkesidene (EyeQ/iWear/Ascend/Easyvision) løftet til samme nivå som ekte merker (2026-09-29)

Kai, med to referansebilder: "https://kontaktlinser.no/merke/eyeq/ Ønsker
likt som alle andre merker, men vi beholder også i tillegg under
toppbanneren [bilde 1: den eksisterende «Hva er EyeQ?»-boksen]. ref til et
annet merke i bilde 2 [Dailies -- toppbanner med stat-stripe og to knapper]."

`render_private_label_brand_page()` (`/merke/{eyeq|iwear|ascend|easyvision}/`)
hadde siden 2026-09-27 kun fått toppbanneret (`.brand-hero`) fra
`render_brand_page()` sitt løft, ikke resten -- ingen stat-stripe, ingen
"i tall", ingen ekte prisinnsikt-graf, ingen sortiment-/materialer-
seksjon, ingen FAQ-regelmotor, ingen guide-ressurser. Løftet nå til
samme struktur, brukt av alle fire kjeder siden de deler én renderfunksjon
(konsistens var selve poenget med "likt som alle andre merker" -- ikke
fornuftig å gjøre bare EyeQ annerledes enn de tre søsknene).

**Forutsetning, gjort i samme runde:** `render_brand_page()` sin ~220
linjer lange `.brand-*`-CSS (stat-stripe, "i tall"-fliser, prisinnsikt-
graf, sortiment-kort, materialer-kort, 30/90-analyse, FAQ-accordion,
toppbanner) lå tidligere hardkodet i selve funksjonens `<style>`-blokk --
flyttet til en ny delt konstant `BRAND_PAGE_STYLE` (samme presedens som
Price Intelligence-CSS-en fikk 2026-09-28: "flyttet fra lokal til delt").
`render_brand_page()` refererer nå `{BRAND_PAGE_STYLE}` i stedet for å
duplisere reglene, og `render_private_label_brand_page()` bruker den
samme konstanten -- én CSS-kilde, ingen drift mulig mellom de to
sidetypene. Verifisert at `/merke/acuvue/` (ekte merke) er pikselidentisk
etter flyttingen, testet i browser før noe annet ble bygget.

**Datatilpasning:** hver private label-"rad" bygges fra `label` (visnings-
navn/slug) + `real_product` (ekte tilbud/specs/pris-id) -- en syntetisk
`row["product"]`-dict bærer `real_product["id"]` (for `_pack_size_from_id()`
og som nøkkel i `price_history`, siden historikken er lagret på den ekte
varens id) mens visningstekst konsekvent bruker `label["name"]`.

**Bevisst utelatt** (adaptivt, samme prinsipp som et ekte merke uten
kuratert `product_families.json`-serie, f.eks. FreshLook): "Utforsk
seriene"-kortene og "Slik skiller seriene seg"-tabellen -- private
label-varianter er 1:1-alias for ett ekte produkt hver, ingen egen
flerpakning-/flervariant-familie å gruppere. `family_summaries` er derfor
alltid tom liste her, og de to seksjonene faller bort helt av seg selv
(samme kodesti som allerede håndterer det for et ekte merke uten serie).
Ingen egen "Produsent"-modul heller -- ett sett private label-varianter
spenner ofte FLERE produsenter (EyeQ blander CooperVision og Alcon, se
tidligere notat i dette dokumentet), så det finnes ingen entydig
produsent å lenke til.

**Ny, ekte informasjon private label-siden alene kan vise:** en
"X ekte merker"-stat i hero-stripen (distinkte `real_product["brand_label"]`
på tvers av settet) og en tilsvarende FAQ-post ("Hvilke ekte merker er
{subbrand} egentlig?") -- ingen ekte merkeside har noe tilsvarende, siden
et ekte merke per definisjon bare er ett merke.

**Kai sitt eksplisitte krav:** `.private-label-explainer`-boksen ("Hva er
{subbrand}?") flyttet UENDRET til rett under `.brand-hero`, FØR alle de
nye seksjonene (stat-stripe/i-tall/prisinnsikt/sortiment/materialer/FAQ/
guider) -- ikke fjernet, ikke omskrevet, bare beholdt på akkurat den
plasseringen bildet viste.

Testet: bygget + `validate_build.py` OK (201/201), full sveip ingen
Traceback/NameError. JSON-LD (BreadcrumbList + ItemList + FAQPage)
validert gyldig på alle fire sider (`json.loads()` på hvert
`<script type="application/ld+json">`-blokk). Alle fire besøkt i
browser-panelet på både desktop (1440px, hero/i-tall/prisinnsikt/
produktgrid/sortiment/materialer/FAQ/guider/tillit-footer alle bekreftet
rendret) og mobil (375px, `document.body.scrollWidth === window.innerWidth`
på alle fire -- ingen horisontal overflow). "30 eller 90 linser?"-
seksjonen er korrekt fraværende på alle fire i dag (ingen har ≥2 robuste
30/90-par ennå) -- adaptivt, ikke en feil. `render_brand_page()` sin egen
utrulling (30 ekte merke-sider) re-verifisert uendret etter
`BRAND_PAGE_STYLE`-flyttingen.

## Toppmenyens "Merker"-dropdown: fra "Bla etter produsent" til en komplett "Alle merker A–Å"-liste (2026-09-29)

Kai, med skjermbilde av den daværende dropdownen: "denne er ikke fin.
brukere trenger ikke bli sendt til Produsent. De ønsker å komme til
kontaktlinse merker. La oss lage en pen oversikt over kun alle merker
her, også iwear og de.."

Den gamle "Merker"-menyen (`_topbar_html()`, `nav-item` for "Merker") had
en venstre kolonne med "Bla etter produsent" -- fire lenker til
`/produsent/{slug}/`-sidene (CooperVision/Alcon/Bausch+Lomb/Johnson &
Johnson Vision) -- og en høyre kolonne med de samme 6 "Populære
merker"-kortene som "Kontaktlinser"-menyen allerede viser. Ingen private
label-serier (iWear/EyeQ/Ascend/Easyvision) var synlige noe sted i denne
menyen.

**Ny, komplett `_MEGA_ALL_BRANDS_HTML`** (definert rett etter
`PRIVATE_LABEL_SUBBRANDS`, siden den avhenger av både den og
`FOOTER_BRANDS` -- ingen tredje, manuelt vedlikeholdt merkeliste bygget
fra bunnen): `FOOTER_BRANDS` (21 ekte merker) + de 4 private label-seriene
fra `PRIVATE_LABEL_SUBBRANDS.values()`, slått sammen til én alfabetisk
sortert liste (25 lenker totalt) og vist som en kompakt to-kolonners
tekstliste (`.mega-allbrands`, CSS `columns: 2`, samme teknikk som
`.footer-brand-list` allerede bruker -- fyller kolonnene naturlig
topp-til-bunn uten at antallet må telles manuelt når nye merker legges
til). **Bevisst IKKE splittet i "ekte merker" og "private label" slik
footeren gjør det** -- Kai ba eksplisitt om at iWear m.fl. skal stå
sammen med de andre i én oversikt, ikke i en egen seksjon.

Venstre kolonne er forenklet til kicker/heading/kort intro-tekst + ÉN
gjenbrukt lenke-rad (`_mega_link_row(_SHIELD_ICON, "Optikerkjedenes
varemerker", ...)`, samme komponent som allerede fantes i "Nyttig å
vite"-listen i Kontaktlinser-menyen) som forklarer hvorfor iWear/EyeQ
o.l. dukker opp blant "kontaktlinsemerker" -- i stedet for den fjernede
produsent-listen. `_MEGA_MANUFACTURER_LINKS_HTML`-konstanten (kun brukt
her) er fjernet helt, ikke bare skjult. "Populære merker"-kortene
(`_MEGA_BRAND_CARDS_HTML`) er også fjernet fra DENNE menyen -- Kai sitt
"kun alle merker" tolket bokstavelig: én tydelig ting menyen gjør, ikke
en kort populær-liste ved siden av den fulle listen. `_MEGA_BRAND_CARDS_HTML`
selv er UENDRET og fortsatt i bruk i "Kontaktlinser"-menyens egen
"Populære merker"-kolonne (ikke rørt, annen meny).

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Verifisert i browser (`TOPBAR_HTML` er delt
sitewide, så én verifisering dekker alle 400+ sider): dropdownen åpnet på
forsiden ved 1280px (position:absolute-varianten) og standard desktop-
bredde, alle 25 lenker til stede og alfabetisk sortert med iWear/EyeQ/
Ascend/Easyvision naturlig innimellom de ekte merkene, klikk på "iWear"
navigerer korrekt til `/merke/iwear/`. Mobil (375px, accordion-varianten)
sjekket eksplisitt: to-kolonners listen er fullt lesbar og
`document.body.scrollWidth === window.innerWidth` -- ingen horisontal
overflow.

## Toppmenyens "Kontaktlinser"-dropdown: fra rikt 3-kolonners design til minimalistisk Lensway-inspirert Type/Varemerke-liste (2026-09-29)

Kai, med skjermbilder av Lensway sin egen "Linser"-dropdown (kompakt
"Type"-liste + "Vis mer" og en utvidet visning med "Type"/"Varemerke"
side om side + en svart "Vis alle linser"-knapp): "slik som her under
kontaktlinser.no gjøres mye mer minimalistisk når man klikker på
kontaktlinser." Fulgt av et direkte spørsmål: "Har vi en side som kan
vises som lensway, alle kontaktlinser?"

**Svar på spørsmålet (ingen kode endret av dette alene):** Nei -- vi har
ingen flat "alle kontaktlinser i én liste"-side. Dette er bevisst,
dokumentert tidligere (2026-08-15): forsiden hadde opprinnelig nettopp en
slik liste, fjernet med vilje av SEO-hensyn (keyword cannibalization mot
kategori-/merke-sidene, dårlig skalering med voksende katalog). Avklart
med Kai via to spørsmål -- ba først om retning på (1) hva en
"vis alle"-knapp skal peke til og (2) hvor fyldig varemerke-listen i den
nye menyen skal være -- Kai svarte i stedet direkte: "tenker vi heller
har en knapp som sier 'alle merker', som da går til
https://kontaktlinser.no/#merker". Det avgjorde begge spørsmålene på én
gang: ingen ny "alle linser"-side bygges (SEO-avgjørelsen fra august står
fast), og knappen kalles "Alle merker" (ikke "alle linser") siden den
faktisk peker til merke-seksjonen.

**Implementert**: `_topbar_html()` sin "Kontaktlinser"-meny gikk fra en
rik 3-kolonners design (fargede ikon-rader per linsetype med undertekst,
en 3-kolonners logo-kort-grid for "Populære merker", et bakgrunnsbilde-
promo-kort til guiden) til en ren, kompakt 2-kolonners tekstliste --
`.mega-rich-grid-2col-plain` (ny CSS-breddevariant, 400px, matcher
Lensway sin kompakte bredde bedre enn den gamle 720px-varianten):
- **"Type"**: de 5 ekte kategoriene våre (`_MEGA_CATEGORIES`, uendret
  datakilde) som rene `.mega-menu-link`-tekstlenker, pluss "Optikerkjedenes
  varemerker" (`/private-label/`) som et 6. listeelement -- samme grep
  som Lensway selv gjør (blander "type" og "samlekategori" i én liste,
  se deres egen "Optikerkjedenes varemerker"-rad i skjermbildet). Ingen
  "Vis mer"-kollaps bygget her -- Lensway trenger den for sine ~10 typer,
  vi har bare 6 elementer totalt, ikke nok til å trenge skjuling.
- **"Varemerke"**: samme 6 kuraterte, populære merkene som før
  (`_MEGA_TOP_BRANDS`, uendret liste), nå som rene tekstlenker i stedet
  for logo-kort. Bevisst IKKE byttet til den fulle 25-merker-listen
  (`_MEGA_ALL_BRANDS_HTML` fra Merker-menyen, forrige runde samme dag) --
  ville dupliserte hele Merker-dropdownen inni denne menyen også.
- **Bunn-knapp**: "Alle merker →" til `/#merker`, erstatter den
  tidligere "Se alle kontaktlinser →" (pekte til `/#kategorier`) --
  direkte etter Kais presisering.

**Dødkode fjernet** (ikke bare skjult -- ingen annen side/meny brukte
dem): `_mega_type_row()`, `_mega_brand_card()`, `_MEGA_TYPE_ROWS_HTML`,
`_MEGA_BRAND_CARDS_HTML`, `_MEGA_USEFUL_LINKS_HTML`, `_BOOK_ICON`,
`_CALENDAR_ICON`, samt CSS-reglene `.mega-type-row*`, `.mega-brand-grid`/
`.mega-brand-card*`, `.mega-promo-card*` og `.mega-rich-grid-3col`
(uten "-plain"). `_mega_link_row()`/`_SHIELD_ICON`/`.mega-link-row*` er
UENDRET og fortsatt i bruk (Merker-menyens "Optikerkjedenes
varemerker"-rad, forrige runde samme dag) -- ikke fjernet.
`_MEGA_CATEGORIES`/`_MEGA_TOP_BRANDS` (selve datalistene, bare
rendringen endret) er også uendret og gjenbrukt direkte.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError, grep bekreftet ingen gjenværende referanser til de
fjernede symbolene/CSS-klassene noe sted i filen. Verifisert i browser
(`TOPBAR_HTML` delt sitewide): Kontaktlinser-menyen åpnet på desktop
(kompakt, matcher Lensway-referansen godt) og mobil (375px accordion,
`document.body.scrollWidth === window.innerWidth`, ingen overflow),
"Alle merker →" bekreftet `href="/#merker"` via DOM. Merker- og
Guider-menyene (urørt i denne runden) sjekket på nytt for regresjon --
begge fortsatt korrekte.

## 5. private label-kjede oppdaget og lagt til: Mister Spex/TrueLens (2026-09-29)

Kai fulgte opp assessment-runden over med et konkret tips: "ja. og klarer
du å finne flere slike private labels i norge som ikke kontaktlinser.no
har? utfordring.." (limt inn fra en annen AI-samtale, se forrige
CLAUDE.md-seksjon for min vurdering av selve svaret -- TrueLens var det
eneste sporet med reell substans, Everclear og "flere Easyvision-varianter"
ble vurdert som svake/allerede dekket). Kai ba deretter eksplisitt om å
verifisere TrueLens-sporet, pluss et eget tips: "jeg tror mister spex
kjøpte lensit før de la ned i norge og eier lensit og har da også disse
produktene for det norske markedet" (med lenke til Lensit sitt eget søk).

**Verifisert på tre uavhengige måter, samme kildedisiplin som de 4
eksisterende kjedene:**
1. Lensit (allerede skrapet forhandler) -- 9 TrueLens-produkter, med
   spesifikasjonstabeller (materiale/vanninnhold/Dk-t/diameter/basiskurve)
   som er identiske med våre eksisterende Live/MyDay-oppføringer.
2. Lenson/Lensway (allerede integrert) -- 10 TrueLens-produkter hver
   (`lensway.no/searchlw?s=truelens`), under URL-mønsteret
   `-private-{id}` -- samme markør Lensway bruker for alle eksisterende
   private-label-SKU-er.
3. **Gullstandard-bekreftelse**: Lensway sin egen
   `/kontaktlinser/linseliste?p_privateBrand=Mister+Spex`-side (samme
   "Optikerkjedenes varemerke"-mekanisme de 46 opprinnelige koblingene ble
   bygget fra) + hver enkelt produktsides eksplisitte "Finnes under
   navnet: X"-tekst, f.eks.: "TrueLens Premium Daily heter Live hos oss.
   Det er samme navn som produsenten CooperVision har gitt den... Lensway
   har ikke noe samarbeide med Mister Spex, men selger den under navnet
   som produsenten har gitt den." Samme sideTITTEL-mønster ("X - Linser -
   Produsent | Lensway") ga alle 10 mappingene direkte, uten å måtte lete
   i selve brødteksten for hver.

**Alle 10 mappinger** (lagt til i `private_labels.json`, `chain: "Mister
Spex"`) -- to kvalitetsnivåer, Daily-varianter fra CooperVision,
Monthly-varianter fra Bausch + Lomb:

| TrueLens-navn | Ekte produkt | Produsent |
|---|---|---|
| Premium Daily | Live 30-pack | CooperVision |
| Platinum Daily | MyDay 30-pack | CooperVision |
| Platinum Daily Toric | MyDay Toric 30-pack | CooperVision |
| Platinum Daily Multifocal | MyDay Multifocal 30-pack | CooperVision |
| Platinum Monthly | ULTRA 6-pack | Bausch + Lomb |
| Platinum Monthly Toric | ULTRA for Astigmatism 6-pack | Bausch + Lomb |
| Platinum Monthly Multifocal | ULTRA for Presbyopia 6-pack | Bausch + Lomb |
| Premium Monthly | PureVision2 6-pack | Bausch + Lomb |
| Premium Monthly Toric | PureVision2 for Astigmatism 6-pack | Bausch + Lomb |
| Premium Monthly Multifocal | PureVision2 for Presbyopia 6-pack | Bausch + Lomb |

Alle 10 canonical-produktene fantes allerede i katalogen vår -- ingen nye
produkter måtte legges til, kun nye alias-koblinger.

**Implementert**: `"Mister Spex": "TrueLens"` lagt til
`PRIVATE_LABEL_SUBBRANDS` (render_templates.py) -- resten er HELT
automatisk fra eksisterende, generaliserte kodesti (samme mønster som
gjorde EyeQ/iWear/Ascend/Easyvision-arbeidet tidligere denne dagen
byggbart uten sidetype-spesifikk kode): `/merke/truelens/`,
10× `/private-label/truelens-*/`, TrueLens sitt eget kort i forsidens
"Merker"-rutenett, en ny seksjon på `/private-label/`, og TrueLens i
toppmenyens "Alle merker A-Å"-liste (fra forrige runde samme dag) --
INGEN av disse stedene trengte kode-endring, kun de to datafilene.
3 nye `/serie/truelens-*/`-sider ble også bygget automatisk (samme
kryssreferanse-mekanisme som allerede kobler private label-varianter inn
i eksisterende produktserier der en familie deler ≥2 medlemmer).

**Ingen logo/illustrasjon for TrueLens ennå** -- `PRIVATE_LABEL_SUBBRAND_LOGOS`
og `render_private_label_illustration()` har ingen TrueLens-oppføring,
så serien faller korrekt tilbake til en initial-badge ("TR") og det ekte
produktbildet som sample-image på oversiktskortene -- samme fallback-vei
iWear brukte før den fikk sin egen tekst-ordmerke-logo, ingen krasj.

**Liten, ekte bug fanget og fikset i samme runde** (ikke TrueLens-
spesifikk, men eksponert av det nye kjedenavnet): `render_private_label_index_page()`
sin per-kjede seksjons-anker brukte `chain.lower()` direkte som HTML
`id`-attributt -- fungerte greit for alle eksisterende ett-ords-kjedenavn
(Brilleland/Synsam/Specsavers/Coptikk), men ga et ugyldig
`id="mister spex"` (mellomrom i en HTML-id) for det nye kjedenavnet.
Fikset med `chain.lower().replace(" ", "-")` -> `id="mister-spex"`.

Testet: bygget + `validate_build.py` OK (201/201), full sveip ingen
Traceback/NameError. JSON-LD validert gyldig (`json.loads()`) på
`/merke/truelens/`, to individuelle `/private-label/truelens-*/`-sider
og `/private-label/`-oversikten. Verifisert i browser: `/merke/truelens/`
viser korrekt "10 produkter · 4 ekte merker · 4 linsetyper · 8 butikker",
prisinnsikt-graf og produktgrid med riktig "= Live 30-pack" / "= MyDay
30-pack" osv. per kort; `/private-label/truelens-premium-daily/` viser
ekte, levende tilbud fra Lensway/Lenson/Lensit (samme tilbudsdata som
`live-30pk` allerede har); `/private-label/`-oversikten har en ny
"Mister Spex → Se TrueLens-siden →"-seksjon med riktig anker-id; forsidens
Merker-grid og toppmenyens "Alle merker A-Å" (nå 26 merker) viser begge
TrueLens automatisk. Mobil (375px) sjekket på `/merke/truelens/` --
`document.body.scrollWidth === window.innerWidth`, ingen overflow.

**Ikke gjort i denne runden** (flagget, ikke glemt): den opprinnelige
Easyvision Linarial/Lenson-URL-verifiseringen (fra forrige runde) ble
avbrutt da Kai styrte samtalen mot TrueLens -- fortsatt uverifisert.
Everclear-"audit" og "flere Easyvision-varianter"-sporet fra samme
AI-samtale ble vurdert som lav prioritet/sannsynlig blindvei i
assessment-runden, ikke fulgt opp.

## TrueLens-illustrasjoner: dobbeltsjekk + ekte bilder fra Kai (2026-09-29, samme dag)

Kai: "dobbeltsjekk at alle er korrekte og så sender jeg deg en liste over
bilder du kan bruke som vi har laget. husk å markere slik som iwear at
dette er illustrerte bilder etc.."

**Dobbeltsjekk**: alle 10 TrueLens-koblinger re-verifisert individuelt
(ikke bare sidetittel denne gangen, men Lensway sin fulle "Finnes under
navnet: X"-brødtekst per produkt) -- alle 10 bekreftet 100 % korrekte mot
`private_labels.json`, ingen feil funnet.

**Bilder**: Kai sendte et samlet referanseark (17 boksrendere,
"Illustrasjoner av TrueLens-serien. Faktisk emballasje kan avvike." --
Kai sin egen ordlyd, ikke noe vi la til) som PNG/webp-fil (ikke bare
inline i chatten som forrige, ufullstendige arket). Alle 10 nødvendige
bokser (matchet mot våre 10 label-slugs, valgte 30-pack-varianten der
både 30/90 var vist siden det er den faktiske canonical-koblingen) kuttet
ut med samme numpy-baserte rad-/kolonne-gap-deteksjon som guide-bildene
tidligere i prosjektet (kolonne-std-avvik per rad-bånd, med
gap-sammenslåing for å håndtere smale skygge-artefakter mellom boksene --
enkel bakgrunn-median-terskel var for støyfølsom på grunn av en svak
gradient over hele arket). Lagret som `static/private-label/truelens-
{slug}.webp` (340px bredde, 5,7-8,8 KB hver).

**Ny `_pli_truelens(slug)`** wired inn i `render_private_label_illustration()`
for `chain == "Mister Spex"`. Prinsipielt annerledes enn de tre andre
kjedenes rene CSS-tegnede "fake bokser" (`_pli_iwear()` m.fl.) -- dette er
ekte rasterbilder, ikke vektor-illustrasjon -- men samme
"illustrasjon, ikke ekte produktbilde"-behandling (`role="img"
aria-label="Illustrasjon, ikke et ekte produktbilde"` + den synlige
"Egen illustrasjon, ikke et ekte produktbilde. Les mer →"-bildeteksten
til `/om-produktillustrasjoner/`), nøyaktig som Kai ba om.

**To reelle CSS-bugs funnet og fikset underveis** (begge oppdaget empirisk
med `getBoundingClientRect()` i browser-panelet, ikke antatt):
1. Første forsøk (`height:100%` på bildet) arvet stille HELE
   `.hero-product-image` sin faste boks-høyde og dyttet bildeteksten under
   fullstendig utenfor det synlige (`overflow:hidden`-klipte) området --
   usynlig, men til stede i DOM-en.
2. Rot-årsaken var dypere enn selve bildet: den DELTE `.pli-tile-wrap`
   (satt av kalleren, brukt av ALLE fem kjeder) har `aspect-ratio:560/225`
   men INGEN `overflow:hidden` på seg selv -- uten det ignorerer
   CSS-motoren aspect-ratio når et barns "automatic minimum size" krever
   mer plass, og et portrettformat-bilde (`height:auto`) krevde nettopp
   det. `.pli-tile-wrap` ble dermed stille strukket til BILDETS egen ratio
   (~1,25:1) i stedet for den tiltenkte 2,49:1 -- bekreftet med
   `getComputedStyle` (aspect-ratio sto riktig i CSS-en, men faktisk
   rendret høyde matchet ikke). De tre andre kjedene rammes aldri av dette
   siden ALT innholdet deres allerede er absolutt posisjonert (bidrar null
   til "automatic minimum size"). Fikset ved å gjøre det samme for
   TrueLens: bildet ligger nå i en tom `position:relative`-wrapper med
   `<img>` selv `position:absolute;inset:0` -- tatt helt ut av normal
   flyt, slik at `.pli-tile-wrap` sin aspect-ratio endelig får virke som
   tiltenkt (bekreftet: 2,49:1 nøyaktig, på alle 10 rutenett-fliser OG på
   produktsidens hero, både mobil og desktop).

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Verifisert i browser på BEGGE stedene illustrasjonen
brukes (produktside-hero og merke-side-rutenett), på BÅDE mobil (375px --
der bildeteksten opprinnelig pakket om til 2 linjer og var enda mer utsatt
for klipping enn desktop) og desktop, for flere ulike TrueLens-produkter.
Regresjon: iWear sin eksisterende, urørte CSS-illustrasjon sjekket på nytt
og fortsatt 100 % uendret (kun den NYE `Mister Spex`-grenen i
`render_private_label_illustration()` ble lagt til, ingen eksisterende
kode i de fire andre `_pli_*`-funksjonene rørt).

## To små funn under gjennomgang av Easyvision-koblingene + en ekte, site-wide søkefeil (2026-09-29, samme dag)

Kai ba meg gå gjennom resten av de 20 Easyvision-koblingene for flere
duplikater, etter at han selv la merke til at Umere og Sential begge
pekte til Clariti 1 day. Gruppert alle 20 programmatisk etter
`real_product_id`: **Umere+Sential er det ENESTE duplikatet** -- de
resterende 18 er alle unike 1:1-koblinger. Ingen endring nødvendig
(duplikatet var allerede bekreftet legitimt i forrige runde samme dag --
Lensway bekrefter uavhengig at BEGGE navnene faktisk selges under nøyaktig
samme fysiske Clariti 1 day-produkt).

**Reelt, site-wide funn under samme gjennomgang** (ikke det Kai spurte
om, men oppdaget via et skjermbilde han viste av søkeforslagene): Kai la
merke til at et lite ikon manglet på "de nye" (TrueLens) -- viste seg
raskt (Kai selv: "ahh det gjelder alle Eget merkenavn") å IKKE være en
TrueLens-spesifikk mangel, men en eksisterende feil i `LENS_SEARCH_JS`
sin søkeforslag-fallback som har rammet alle 84 private label-produkter
siden søket ble bygget (ikke noe innført i dagens TrueLens-arbeid) --
bare usynlig/lite lagt merke til før det femte settet (TrueLens) gjorde
mønsteret tydelig for Kai.

**Rot-årsak**: `build_search_index()` sine private label-oppføringer har
`"image": None` (med vilje -- vi viser aldri det ekte produktets bilde
under et privat merkenavn) og `"meta": "Eget merkenavn"` (også med vilje
-- kjedenavnet skal ikke avsløres der). Søkeforslagenes JS-fallback for
manglende bilde tok imidlertid de 2 første bokstavene av nettopp `meta`
-- som for ALLE private label-produkter er den samme generiske teksten
"Eget merkenavn", og ga dermed samme meningsløse "EG"-ikon på tvers av
alle 84 produkter (iWear, EyeQ, Ascend, Easyvision OG TrueLens), ikke et
brand-relevant ikon slik ekte produkter får (deres fallback bruker
`brand_label`, som faktisk er merkerelevant).

**Fiks**: ny `"badge"`-nøkkel lagt til KUN på private label-oppføringene
i `build_search_index()`, satt til `label["name"][:2].upper()` (f.eks.
"TrueLens Premium Daily" -> "TR", "iWear Oxygen XR" -> "IW", "EyeQ 24" ->
"EY", "Ascend Premier" -> "AS", "Easyvision Opteyes" -> "EA"). JS-en
(`LENS_SEARCH_JS`) endret til `(item.badge || item.meta).slice(0,
2).toUpperCase()` -- bakoverkompatibel, ekte produkter/løsninger/serier
(som ikke har `badge`) faller fortsatt tilbake til sin eksisterende,
allerede-riktige `meta`-baserte oppførsel, uendret.

Testet: bygget + `validate_build.py` OK, full sveip ingen
Traceback/NameError. Grep bekreftet alle fem forventede badge-verdier
(`AS`/`EA`/`EY`/`IW`/`TR`) til stede i den bygde JSON-en. Verifisert i
browser: søk på "iwear" viser nå "IW"-ikon på alle iWear-forslag, søk på
"truelens" viser "TR" -- begge korrekt, ingen "EG" igjen noe sted.

## Price Intelligence: visuelt reset (ikke et datarewrite) (2026-09-29, samme dag)

Kai sendte en detaljert 13-punkts "PRICE INTELLIGENCE — VISUAL RESET"-
brief + et godkjent mockup-bilde (`57.webp`) for det eksisterende Price
Intelligence-modulen (bygget 2026-09-27/28, se de to seksjonene lenger
opp om "Product Gold Standard v1" og "rullet ut til ALLE produkttyper").
Kai sin egen ramme, sitert direkte: "This is a visual/layout reset, not
a data rewrite... Preserve everything functional... Please follow the
attached visual reference closely rather than creatively reinterpreting
it." Briefen ble først sendt UTEN selve mockup-bildet (kun tekst som
refererte "the attached approved mockup") -- fulgte "verifiser før du
siterer"-prinsippet fra minnet og ba Kai sende bildet i stedet for å
gjette på et referansedesign jeg ikke hadde sett, siden nettopp denne
oppgaven var eksplisitt om å matche et visuelt forelegg presist.

**Alt data-/beregningsgrunnlag er UENDRET** -- kun CSS og markup-
struktur i `render_price_intelligence()` og de tilhørende
`_price_intelligence_*()`-hjelperne er rørt:

- **Layout omorganisert til tre separate visuelle soner** i stedet for
  én sammenhengende `.price-intel-panel` per periode: metrikk-stripen
  (Pris nå/Laveste/Høyeste/N-dagers median + statuskort) vises nå FØR
  periode-fanene (var etter grafen), selve grafen ETTER fanene (uendret
  posisjon), og "Kort oppsummert" flyttet til HELT NEDERST i modulen,
  etter alle tre intelligens-kortene (Prisforskjell/Prisvinner/Kjøper du
  flere esker) -- var tidligere øverst i hver periode-panel. Tre
  parallelle DOM-grupper (`metric_strips`/`chart_panels`/
  `summary_strips`) bygges nå i loopen over `PRICE_INTELLIGENCE_PERIODS`
  i stedet for én kombinert streng, alle med samme `data-period`-
  attributt slik at én generisk JS-håndterer (`querySelectorAll('[data-
  period]').forEach(...)`) fortsatt bytter dem samlet ved fanebytte,
  uansett hvor i DOM-en de fysisk ligger.
- **Ny "Kjøper du flere esker?"-tabell** (`_price_intelligence_quantity_table()`)
  -- samme antalls-/pris-beregning som Winner Card sin egen
  quantity-motor (`_savings_eligible_offers(offers, incl=False)`, uten
  frakt, samme basis som resten av modulen), viser billigste butikk +
  totalpris for 1/2/4/6/8/10 esker og sporer om billigste butikk faktisk
  endrer seg ved høyere antall. Skjules helt ved <2 sammenlignbare
  tilbud (samme "skjul heller enn å anslå"-regel som resten av modulen).
- **"Prisvinner over tid" viser nå 0-dagers-rader også**: `_price_
  intelligence_merchant_winners()` fikk et nytt `all_retailers`-
  parameter som legger inn enhver forhandler som SELGER produktet i dag
  men aldri har vunnet laveste pris, med "0 dager" -- var tidligere
  helt fraværende fra listen, ga et ufullstendig bilde av konkurransen.
- **Visuell stil**: kort byttet fra grå `.mist`-fylte bokser til hvite
  kort med tynn kant (matcher resten av sidens `.offer-card`-språk),
  metrikk-/statuskort byttet fra blå- til mint-tinting som standard
  (mint = "nøytral/informativ" her, ikke en besparelse-påstand -- kun
  opp/ned-avvik farges rødt/coral via `.price-intel-status-up`/`-high`),
  periode-fanenes aktive tilstand byttet fra blå til mørk navy
  (`var(--ink)`) for å matche knappespråket ellers på siden.

**To reelle bugs funnet og fikset under egen testing, før noe ble sendt
til Kai**:
1. **Periode-fanenes rekkefølge var faktisk feil for ethvert produkt med
   under 90 dagers historikk** (som er ALLE produkter i dag, se forrige
   Price Intelligence-runde: maks 45 dagers historikk finnes ennå) --
   den gamle koden bygde kun de KVALIFISERTE fanene først og la de
   deaktiverte til etterpå, og siden "All historikk" alltid er
   kvalifisert (ingen dagsterskel) havnet den som fane nr. 2
   ("30 dager, All historikk, 90 dager, 6 måneder, 1 år") i stedet for
   sist, i strid med briefens eksplisitte rekkefølgekrav
   ("30 dager | 90 dager | 6 måneder | 1 år | All historikk"). Fikset
   ved å iterere ÉN gang over hele `PRICE_INTELLIGENCE_PERIODS` i fast
   rekkefølge og rendre en deaktivert knapp inline for hver ukvalifisert
   periode, i stedet for å samle dem separat. Verifisert på en live
   47-dagers-historikk-side at rekkefølgen nå er korrekt.
2. **CSS-selector-mismatch**: skrev først `.price-intel-status-
   historical_high`, men `_price_intelligence_status_text()` returnerer
   faktisk modifikatorstrengen `"high"` (ikke `"historical_high"`) for
   det tilfellet -- rettet til `.price-intel-status-high`.

Testet: bygget + `validate_build.py` OK (201/201), full sveip ingen
Traceback/NameError. Verifisert i browser på Dailies AquaComfort Plus
90-pack (47 dagers historikk, 7 tilbud -- rik data): korrekt rekkefølge
overalt (metrikker → faner i riktig rekkefølge → graf → tre
intelligens-kort → "Kort oppsummert" nederst), desktop (1100px, målt
via `getComputedStyle`/`getBoundingClientRect`, ikke bare skjermbilde
pga. ustabil skjermbilde-rendering i browser-panelet denne økten):
metrikk-stripe 4-kolonners + statuskort i én rad, intelligens-kortene i
et ekte 3-kolonners grid (322px hver), "Kort oppsummert" korrekt
posisjonert ETTER kortene med blå tint-bakgrunn. Spot-sjekket
`unit_plural`-gjennomstrømning på ReNu Multi-Purpose 60 ml (linsevæske)
-- "Kjøper du flere FLASKER?" (ikke "esker"), alle rader/tekster bruker
riktig enhetsord gjennom hele modulen. Kantcase testet på Biofinity
Multifocal Toric 3-pack (kun 1 tilbud): Prisforskjell- og Kjøper-du-
flere-esker-kortene korrekt fraværende (krever ≥2 tilbud), Prisvinner-
over-tid vises fortsatt korrekt (én butikk, 47/47 dager), "Kort
oppsummert" utelater riktig spredningssetningen. Ingen regresjon på
merke-/serie-sidenes egen, urørte `_render_price_history_chart()`/
`render_family_price_insight()`.

## Prislistens mobil-kollaps: terskel hevet fra 3 til 10 tilbud (2026-09-29, samme dag)

Kai, etter å ha fått bekreftet at Price Intelligence-resetten var live:
"på mobil også, produktsider. Vis alle treff opp til 10 priser, og
deretter hvis flere, klikk for å vise alle." Den eksisterende "Vis alle
priser"-kollapsen (bygget 2026-09-27, se "Product Mobile Gold Standard
v1, Steg 2" lenger opp) skjulte alt utover de 3 billigste tilbudene på
mobil bak en klikk-knapp -- Kai ønsket en høyere terskel, slik at de
fleste produkter (som uansett sjelden har mer enn 5-9 forhandlere, se
`sources_config.json`-oversikten) viser alle tilbudene direkte uten at
brukeren må klikke i det hele tatt.

**To steder måtte endres i takt** (samme fallgruve som ville oppstått om
kun én ble endret): selve terskelen i `render_price_list()` sitt
`collapse_after`-kall (Python, avgjør OM `is-collapsed`-klassen/knappen
bygges) OG den hardkodede CSS-selektoren `.offers.is-collapsed
.offers-list .offer-card:nth-child(n+4)` (avgjør HVILKE kort som
faktisk skjules når klassen er satt) -- CSS-en var ikke parametrisert
av selve tallet, bare av om kollapsen var aktiv. Begge endret fra 3/4
til 10/11 (Python `collapse_after=10`, CSS `nth-child(n+11)`, både
mobil- og den allerede eksisterende `>=860px`-overstyringen som viser
alt uansett på desktop).

**Rullet ut til alle tre produktsidetyper for konsistens** (samme
"lik oppførsel på tvers av kontaktlinser/linsevæske-øyedråper-tilbehør/
private label"-prinsipp som resten av dagens og gårsdagens arbeid):
kontaktlinse-produktsiden hadde allerede `collapse_after=3` (hevet til
10), mens `render_solution_product_page()` og `render_private_label_page()`
aldri hadde noen kollaps i det hele tatt (viste alltid alle tilbud på
mobil uansett antall) -- fikk nå samme `collapse_after=10` lagt til, som
ren fremtidssikring (ingen produkt i katalogen har i dag flere enn 9
tilbud, se under, så endringen er usynlig i praksis akkurat nå, men
konsistent og korrekt den dagen et produkt får en 11. forhandler).

**Verifisert**: maks antall tilbud på tvers av hele katalogen i dag er 9
(Biofinity 6-pack/Toric 6-pack) -- ingen produkt trigger kollapsen i
det hele tatt akkurat nå, alle tilbud vises direkte på mobil uten
klikk. Testet likevel eksplisitt at selve mekanismen fungerer riktig
ved den nye terskelen: syntetisk DOM-test (klonet tilbudskort til 13
stk på en ekte produktside, satt `is-collapsed`-klassen manuelt) viste
nøyaktig 10 synlige kort, ikke 3 -- bekrefter at CSS-en faktisk skjuler
fra kort 11 og ikke lenger fra kort 4. Sjekket på alle tre sidetyper på
mobil (375px, `document.body.scrollWidth === window.innerWidth`, ingen
overflow): kontaktlinse-produktside (Biofinity Toric 6-pack, 8 tilbud,
alle synlige, ingen "Vis alle"-knapp), linsevæske (ReNu Multi-Purpose
60 ml, 2 tilbud), private label (iWear Oxygen XR, 4 tilbud). Desktop
uendret (viste allerede alle tilbud uansett antall, se tidligere runde
samme uke: "Vis alle priser"-kollapsen skal KUN gjelde mobil"). Bygget +
`validate_build.py` OK (201/201), full sveip ingen Traceback/NameError.

## Price Intelligence: logikk-/semantikk-/final polish-runde (2026-09-29, samme dag)

Kai, etter to visuelle runder på Price Intelligence-modulen, fulgte opp med et
eget "Intelligence Logic & Final Polish"-brief (30 punkter, eksplisitt "not
another design brief... primarily about making sure the intelligence is
mathematically correct, semantically precise, not visually misleading,
genuinely useful, deterministic, adaptive"). Gikk gjennom hele modulen
funksjon for funksjon FØR noe ble endret for å skille reelle mangler fra
allerede-korrekt logikk (mye var allerede riktig -- tie-break er allerede en
dokumentert, deterministisk prioritetsliste, ikke array-/databaserekkefølge;
"én rad per kalenderdag" var allerede garantert av `record_price()`; manglende
observasjonsdager telles allerede aldri som uendret/null, siden de ganske
enkelt er fraværende fra historikk-listen). Fem reelle funn ble rettet:

1. **Materialitetsbrist i statusklassifiseringen (den viktigste fiksen,
   bekreftet med Kais eget eksempel).** `_price_intelligence_status()` (~
   render_templates.py:3748) klassifiserte `historical_low`/`historical_high`
   kun på "current == period_low/period_high", uansett hvor lite spennet i
   perioden faktisk var. Biofinity Toric 6-pack sitt ekte tall (449->454 kr,
   ~1,1 %) ble dermed flagget rødt "Høyeste registrerte pris" bare fordi
   dagens pris traff periodens (ubetydelige) tak. Lagt til et krav om et
   MATERIELT spenn (`range_pct >= STATUS_STABLE_TOLERANCE_PCT`, samme 3
   %-toleranse som resten av statuslogikken allerede brukte) før
   historical_low/high i det hele tatt kan utløses -- ellers faller
   klassifiseringen naturlig gjennom til "stable" via samme
   pct_change-sjekk. Verifisert direkte på det eksakte eksempelet Kai ga:
   viser nå korrekt "Stabil pris / Laveste produktpris har endret seg lite
   de siste 30 dagene" i stedet for en falsk rød høy-pris-advarsel.
2. **Terminologi-forvirring mellom to ulike "høy/lav"-begreper.** Kai sitt
   poeng 1-3: historisk prisserie (laveste/høyeste REGISTRERTE pris over
   tid) og dagens butikk-spredning (laveste/høyeste BUTIKKPRIS akkurat nå)
   er to helt forskjellige tall som lett forveksles når de bruker samme
   ord. Historikk-metrikken "Høyeste registrerte pris" er nå "Høyeste
   prisnivå" (med en `title`-tooltip: "Høyeste registrerte verdi for den
   laveste tilgjengelige produktprisen i valgt periode."), status-tittelen
   for samme tilstand er "Høyt prisnivå" (var også "Høyeste registrerte
   pris" -- samme kollisjon). "Prisforskjell mellom butikkene"-kortets rader
   omdøpt til "Laveste butikkpris"/"Høyeste butikkpris" (var "Laveste
   pris"/"Høyeste pris"). "Laveste registrerte pris" (historikk-metrikk OG
   status-tittel) er UENDRET -- Kai selv: hold denne, og unngå promoterende
   språk som "Fantastisk pris" der (allerede rent faktabasert, ingen
   endring nødvendig).
3. **Laveste/høyeste-dato omformulert.** Datoen ved siden av "Laveste
   registrerte pris"/"Høyeste prisnivå" viser nå "Først registrert {dato}"
   i stedet for en bar dato -- unngår at en verdi som faktisk gjaldt flere
   dager på rad leses som om den kun eksisterte akkurat den ene datoen.
   Python sin `min()`/`max()` med `key=` plukker allerede FØRSTE forekomst
   kronologisk (window er alltid eldst->nyest-sortert) -- selve
   beregningen var korrekt fra før, kun teksten var upresis.
4. **30-dagers median: presis definisjon, lagt til som tooltip** ("Medianen
   av den laveste registrerte produktprisen for hver dag i perioden.") --
   selve beregningen (`_price_intelligence_window(history, days)` =
   `history[-days:]`, ett element per faktisk observert dag, aldri
   kalenderdag-basert eller hullfylt) var allerede riktig per Kais egen
   definisjon i punkt 5, trengte bare en synlig forklaring.
5. **Y-akse-eksaggerasjon i grafen (Kais konkrete eksempel: 449->454 kr
   fylte nesten hele grafhøyden).** Ny sentralisert
   `_price_intel_chart_domain()` (rett før `_render_price_intelligence_chart()`)
   erstatter den gamle "10 % av observert spenn"-paddingen med et GULV:
   visningsspennet er nå minst `_CHART_MIN_ABS_RANGE_NOK` (25 kr) ELLER
   `_CHART_MIN_PCT_RANGE` (9 %) av medianprisen, whichever er størst.
   Verifisert eksakt tallmatch på Biofinity Toric-eksemplet: median 454 kr
   -> gulv 40,86 kr -> endelig aksespenn 428-475 kr (var tidligere presset
   ned til noen få kroner rundt selve linjen). Gulvet er KUN en nedre
   grense -- et ekte, stort spenn klippes ALDRI (regel 14), bekreftet på
   everclear REFRESH 250 ml (ekte 35->89 kr-spenn over hele historikken,
   aksen viser fortsatt hele det ekte spennet, 31-93 kr, ikke presset
   sammen).
6. **"Kjøper du flere esker?" skjules nå betinget, ikke alltid.** Kai,
   punkt 18-20: kortet skal kun vises når det faktisk AVSLØRER noe (f.eks.
   vinnerbutikken endrer seg ved et gitt antall) -- ren gangetabell er
   "merely arithmetic", ikke intelligens. `_price_intelligence_quantity_table()`
   returnerer nå `None` når `change_qty` aldri settes (samme butikk vinner
   ved alle 6 viste antall). **Reelt, sjekket funn:** siden ingen forhandler
   i katalogen i dag har volumbasert prising (hver butikks pris er lineær,
   pris × antall), er dette MATEMATISK UMULIG å utløse under dagens
   datamodell -- kjørt programmatisk mot alle 201 produkter, 0 har en
   vinnerbytte ved noe antall. Kortet er derfor nå usynlig på HELE siden
   inntil enten (a) en forhandler får ekte volumrabatter i data, eller (b)
   frakt-avhengig vinnerbytte bygges inn (Kai sitt punkt 21 -- eksplisitt
   IKKE gjort denne runden, se under). Dette er en direkte, korrekt
   konsekvens av regelen slik Kai formulerte den, ikke en bug -- men
   verdt å flagge tydelig siden det fjerner et helt kort fra alle
   produktsider. `.price-intel-cards` sin desktop-CSS byttet fra fast
   `repeat(3, 1fr)` til `repeat(auto-fit, minmax(220px, 1fr))` (regel 22)
   slik at en 2-korts rad (Prisforskjell + Prisvinner, det vanlige
   resultatet nå) fyller bredden jevnt i stedet for å la en tom tredje
   kolonne stå igjen -- verifisert 991px container -> to 490px-kort, ingen
   gap.

**Bevisst IKKE gjort denne runden** (vurdert, men utenfor "polish"-scope
uten en egen, større funksjonsrunde):
- **Punkt 21 (frakt-avhengig antalls-vinner).** Ville krevd enten
  klientside-omregning av qty-tabellen når frakt-bryteren slås på, eller
  to parallelle statiske tabeller -- en reell funksjonsutvidelse, ikke en
  logikk-fiks. Kortet er uansett konsekvent "uten frakt"-basert (samme
  basis som "Prisforskjell mellom butikkene"), forklart i egen note --
  ikke en blanding av produktpris- og totalpris-intelligens, bare ikke
  frakt-bevisst ennå.
- **Punkt 11 (graderte minimumskrav per periodelengde).** Modulen har
  allerede en hard nedre grense (skjules helt under 7 dagers historikk)
  pluss periode-for-periode data-kvalitetsporter
  (`_price_intelligence_eligible_periods()`, 30/90/182/365 dager) --
  vurdert som tilstrekkelig dekning av prinsippet uten å bygge et eget,
  mer finmasket "7-29 dager = begrensede uttalelser"-lag denne runden.
- **Punkt 16 (retroaktiv uavgjort-deteksjon i historikken).** `price_history.json`
  lagrer kun ÉN vinnerbutikk per dag (samme tie-break som avgjorde
  "laveste pris" på siden den dagen) -- allerede dokumentert i koden at
  en eventuell uavgjort er avgjort deterministisk FØR lagring, ikke
  gjenoppdagbart i etterkant uten å endre selve datamodellen
  (price_history.py, alle konsumenter av `store`-feltet). Vurdert som en
  skjemaendring, ikke en logikk-polish -- flagget, ikke gjort.

Testet: `python3 -c "import ast; ast.parse(...)"` OK, bygget + `validate_build.py`
OK (201/201). Verifisert konkret mot Kais eget Biofinity Toric-eksempel (se
funn 1 og 5 over, eksakte tall matchet). Sjekket edge-caser: produkt med kun
1 tilbud (Biofinity Multifocal Toric 3-pack -- spread-kort og qty-kort
korrekt fraværende, "flat"-status upåvirket siden flat_days-sjekken kommer
FØR materialitets-sjekken i prioritetsrekkefølgen), linsevæske
(unit_plural="flasker" flyter fortsatt riktig gjennom tooltip-tekstene).
Full sveip av bygget: 0 sider rendrer faktisk "Kjøper du flere ...?"-kortet
(`grep '>Kjøper du flere'` -- de 426 falske positive treffene fra en første,
for grov sveip var CSS-kommentarer/-selektorer i den delte stilarket, ikke
faktisk innhold), 260 sider viser "Høyeste prisnivå", 237 viser "Laveste
butikkpris", 24 sider treffer den nye, materialitets-krevende "Høyt
prisnivå"-statusen (ned fra et ukjent, men garantert høyere antall før
materialitetskravet ble lagt til).

## Price Intelligence v2: "premium data publication"-redesign (2026-09-29, samme dag)

Kai fulgte opp logikkrunden med et nytt, 24-punkts visuelt brief
("More data. Less UI chrome... Think: premium financial/data publication,
not SaaS dashboard") + et godkjent mockup-bilde (`58.webp`), sendt i to
meldinger -- en fullstendig skriftlig spec, deretter en eksplisitt
presisering: **"THE ATTACHED MOCKUP WINS"** for alt visuelt (hierarki,
typografi, metrikk-plassering, kort-stil), mens den skriftlige spec-en
fortsatt er fasit for datalogikk/eligibility/semantikk/tilgjengelighet der
de to skulle stå i konflikt. Ren presentasjonsrunde -- ingen av logikk-
/semantikk-runden sine beregninger, terskler eller eligibility-regler er
rørt.

**Fem strukturelle endringer** (`render_price_intelligence()`, ny
`_price_intelligence_recent_winner_count()`-hjelper, CSS i `SHARED_STYLE`):

1. **"Pris nå" er nå visuelt dominerende** (2,1rem, egen stor verdi) med de
   tre historikk-metrikkene (Laveste/Høyeste/Median) ved siden av som en
   tynn, skilt-delt rad (`border-left` mellom kolonnene) i stedet for like
   store grå grid-fliser -- "the numbers themselves should become the
   visual design". Statuspillen (`.price-intel-status-pill`) er nå en egen,
   atskilt komponent ved siden av raden på desktop, fortsatt tinted (Kai,
   regel 5: "may remain a subtle tinted module because it represents a
   conclusion"), men ikke lenger en grid-rute blant rådataene. Mobil
   (<860px): "Pris nå" står alene øverst, de tre andre wrapper i et
   kompakt 2-kolonners rutenett under (uten skillelinjer -- se
   "Lærdom"-punktet nederst for hvorfor).
2. **Grafen har fått en smal "hylle" på stor desktop**
   (`.price-intel-chart-shell{max-width:1100px;margin-inline:auto}`, regel
   8) -- IKKE en proporsjonal nedskalering av høyden (regel 9, uendret 140px
   plot-høyde). En ny, bevisst IKKE-interaktiv verktøylinje over grafen
   ("Laveste registrerte produktpris per dag" + en badge "Viser laveste
   registrerte pris per dag") -- UTEN nedoverpil/chevron, siden det ikke
   finnes noen reell alternativ dataserie å velge mellom ennå; å tegne en
   falsk interaktiv kontroll der ingenting skjer ved klikk ville vært
   misvisende UI, selv om mockupen viste noe som lignet en dropdown.
3. **"31 %"-tallet i "Prisforskjell mellom butikkene" har fått en egen,
   fremtredende callout-boks** (`.price-intel-spread-callout`, mint-tinted,
   regel 12: "make the proprietary spread metric prominent") i stedet for
   en rad blant de andre. 0-dagers-butikker i "Prisvinnere over tid"
   (omdøpt fra entall "Prisvinner" til flertall "Prisvinnere", matcher
   mockupen) er beholdt SYNLIGE -- Kai bekreftet eksplisitt tidligere
   samme uke at dette er ønsket ("viser at de faktisk er sammenlignet,
   ikke bare fraværende") -- men nå visuelt DEMPET
   (`.price-intel-winner-row-zero{opacity:.5}`, regel 13: "Do not let
   zero-value merchants create visual clutter") -- dempning i stedet for
   fjerning, for å ikke motsi den tidligere, eksplisitte avgjørelsen.
   "Kjøper du flere esker?"-tabellens kolonne "Laveste pris" er omdøpt til
   "Pris totalt" (klarere -- kolonnen viser produktpris × antall, en
   TOTAL, ikke en "laveste" i seg selv; regel 19: "Every proprietary metric
   should carry: metric + value + period/context").
4. **Ny "egen-data"-stripe nederst** (`.price-intel-stat-strip`, regel 16)
   -- fem redaksjonelle statistikker med tynne skillelinjer, ingen kort:
   dager siden siste prisendring (gjenbruker `status["flat_days"]`,
   allerede beregnet), antall prisvinnerbytter (gjenbruker
   `winners["changes"]`), antall DISTINKTE prisvinnere de siste
   `min(90, coverage_days)` dagene (ny `_price_intelligence_recent_winner_count()`
   -- bevisst et KORTERE, eget vindu enn "Prisvinnere over tid"-kortet,
   som alltid bruker hele historikken; sier aldri "90 dager" for et
   produkt med færre enn 90 dagers historikk, samme "aldri påstå en
   periode vi ikke dekker"-prinsipp som resten av modulen), periodens
   prisvariasjon i prosent (`status["range_pct"]`, lagt til i
   logikkrunden tidligere samme dag) og periodens laveste pris. Hvert
   element er BETINGET -- vises kun når den underliggende dataen faktisk
   finnes/er meningsfull (f.eks. "prisvariasjon"-elementet skjules helt
   ved en 100 % flat pris, siden `low == high` da gjør prosenttallet
   meningsløst). Periode-avhengig som resten av modulen (bytter med
   fanene via samme `data-period`-mekanisme), UNNTATT
   prisvinner-distinkt-tallet, som bevisst bruker sitt eget, faste
   90-dagers-vindu uavhengig av valgt fane.
5. **Bevisst IKKE implementert: mockupens klokkeslett** ("Sist oppdatert:
   29. september 2026, kl. 08:14") og "Oppdatert i dag"-merkelappen på
   Kort fortalt-boksen. Samme, allerede dokumenterte lærdom som Fase 16 på
   merke-siden TIDLIGERE SAMME DAG: et tid-/dagsrelativt ferskhet-utsagn
   på en STATISK, bygget-én-gang-per-dag side blir usant i intervallet
   mellom to bygg (en leser kl. 20:00 ville sett en løgnaktig "kl. 08:14"
   eller "i dag" som egentlig gjelder gårsdagens bygg).
   `price_history.json` lagrer uansett aldri klokkeslett, kun kalenderdato
   -- et påstått klokkeslett måtte enten vært oppdiktet eller
   byggetidspunktet selv (som blir feil få timer senere). Footeren viser i
   stedet "Prisdata sist bekreftet: {historikkens siste dato}", samme
   "sist bekreftet {dato}"-konvensjon som resten av siden allerede
   følger konsekvent.

**Ny footer-linje** (`.price-intel-footer`): skjold-ikon + "Alle priser
hentes daglig fra norske nettbutikker. Les mer om hvordan vi samler inn
priser →" (lenke til den eksisterende `/slik-sammenligner-vi-priser/`)
venstre, "Prisdata sist bekreftet: {dato}" høyre.

**Ett avvik fra mockupens eksakte tall, flagget til Kai, ikke justert
uten hans bekreftelse:** regel 8 ba om en graf-bredde på "75-82 % av
Price Intelligence-innholdsbredden", men "start med 1100px" som konkret
tall. Målt direkte i browser-panelet: modulens eget innholdsområde
(`.price-intel-chart-panel`) når maks ca. 1178px bred på denne siden
(`.wrap-product` sitt eget 1280px-tak minus modulens egen sidepadding),
så et 1100px-tak gir faktisk ~93 % av innholdsbredden der, ikke 75-82 %
-- prosentmålet forutsatte trolig en bredere beholder enn det som faktisk
finnes på produktsiden i dag. Fulgte det konkrete pikseltallet (den
primære, utvetydige instruksen -- "Start with 1100px") fremfor å gjette
meg til et smalere tall for å treffe prosentmålet; sier fra til Kai i
stedet, siden en eventuell innsnevring er en synlig designbeslutning han
bør ta, ikke noe jeg bør avgjøre stille.

**Lærdom for mobil-CSS ved skift av layout-metafor** (unngikk en reell
bug FØR den ble sendt til Kai, ikke i etterkant): et første utkast brukte
`border-left`-skillelinjer på ALLE fire metrikk-kolonner (inkl. "Pris nå"
som første kolonne), ment å KUN gjelde på desktop -- men `flex-wrap:wrap`
på mobil ville latt kolonne 3 (som visuelt havner FØRST i sin egen,
nye rad når raden bryter) beholde en igjenværende venstre-kant fra sin
CSS-regel, selv om den ikke lenger sto ved siden av en annen kolonne.
Løst ved å holde skillelinjene HELT ute av mobil-CSS-en (ren `flex-wrap`
uten border, kun luft) og kun legge dem til inni `@media
(min-width:860px)`, der `flex-wrap:nowrap` garanterer at rekkefølgen
aldri brytes opp -- skillelinjer mellom kolonner er kun trygt når
naboskapet er garantert stabilt.

Testet: `python3 -c "import ast; ast.parse(...)"` OK, bygget +
`validate_build.py` OK (201/201), full sveip ingen Traceback/NameError.
Verifisert i browser mot Kais eksakte Biofinity Toric-eksempel (`get_page_text`
matcher mockupen nesten ord for ord: eyebrow, "47 dager med data",
"454 kr / Pris nå / Laveste pris akkurat nå", "Stabil pris", riktig
fane-rekkefølge, spread-callout, "Prisvinnere over tid" med dempede
0-dagers-rader, egen-data-stripen med 5 elementer, footer). Chart-bredde
målt eksplisitt ved 1200/1500/1920px viewport (1100px-taket slår inn og
sentrerer korrekt ved bred nok skjerm, 39px luft på hver side ved
1500px+). Mobil (375px) verifisert via DOM (`scrollWidth===innerWidth`,
kun 1 `.price-intel-cards`/1 aktiv `.price-intel-chart-panel`/1 footer i
DOM-en -- et tilsynelatende "duplisert innhold"-skjermbilde viste seg å
være et rent skjermbilde-verktøy-rendringsartefakt, ikke en reell bug,
bekreftet ved å telle faktiske DOM-noder i stedet for å stole på
skjermbildet, samme kjente ustabilitet i browser-panelet som er
dokumentert flere ganger tidligere denne uken). Edge-caser: linsevæske
(ReNu Multi-Purpose 60 ml, "flaske"/"flasker" flyter riktig gjennom HELE
den nye stripen og footeren også), 1-tilbud-produkt (Biofinity Multifocal
Toric 3-pack -- spread-kort korrekt fraværende, egen-data-stripen viser
riktig entall "1 butikk" og utelater riktig "N ganger har
prisvinneren skiftet"-linjen siden changes==0). Ingen krysspåvirkning på
merke-/serie-sidenes egen, urørte `_render_price_history_chart()`
(`grep 'class="price-intel"'` mot en merke-side: 0 treff, kun de delte
CSS-reglene er til stede der som før).

## Price Intelligence v2, runde 2: "reproduser mockupen", ikke bare idéene (2026-09-29, samme dag)

Kai fulgte opp med et strengt "STOP -- THIS DOES NOT MATCH THE APPROVED
MOCKUP"-brief (relayed fra en annen AI-samtale): forrige runde hadde
"tatt idéene fra bildet og presset dem inn i den eksisterende
komponenten" i stedet for å gjenskape selve layout-proporsjonene --
konkret: hele modulen for bred/flat, grafen fortsatt for stor, "Stabil
pris" en stor grønn boks langt til høyre med synlig tomrom foran, de to
gjenværende intelligens-kortene strukket til "gigantiske 50/50", og
manglende dato-etiketter/info-ikon.

**Verifiserte funn FØR noe ble endret** (samme "verifiser før du
handler"-disiplin som resten av økta) -- et eget punkt i samme brief
hevdet i tillegg at "Kort fortalt", egen-data-stripen og footeren var
helt BORTE. Sjekket direkte mot den LIVE produksjonssiden (skjermbilde
+ DOM-inspeksjon, ikke antatt): alle tre var faktisk til stede og
korrekt rendret -- dette punktet var feil, sannsynligvis fra en
foreldet/avkortet gjennomgang på Kais side, IKKE en reell mangel. Resten
av kritikken (proporsjoner, graf-størrelse, tomrommet ved statuspillen,
kort-strekking, kun 2 dato-etiketter, manglende info-ikon) var derimot
alle reelle, konkret verifiserbare avvik -- bekreftet med skjermbilder
og `getBoundingClientRect()`-mål før noe ble fikset.

**Root-cause-fiks, ikke flikking** (samme CSS i `SHARED_STYLE`,
`render_price_intelligence()` og `_render_price_intelligence_chart()`):

1. **Hele `.price-intel`-modulen fikk et eget bredde-tak** (`max-width:
   1000px; margin-inline:auto` ved >=860px) -- var tidligere UBEGRENSET
   (arvet `.wrap-product` sin fulle 1280px), som gjorde alt inni --
   metrikkrad, kort, graf -- "flatt utspredt" uansett hvor mye de
   enkelte delene ble strammet til. Dette var selve rot-årsaken bak
   flertallet av de andre punktene, ikke bare punkt 1 isolert.
2. **Grafens rot-årsak-fiks for "tomrommet ved Stabil pris"**:
   `.price-intel-primary.active` brukte `justify-content:space-between`,
   som eksplisitt SPREDDE metrikkraden og statuspillen over hele
   radbredden -- nøyaktig det synlige gapet Kai pekte på. Fjernet
   `space-between`, erstattet med et fast `gap:28px` slik at de to
   sitter SAMMEN, uansett hvor bred selve modulen er.
3. **Grafen kappet til sin egen native bredde** (680px, samme tall som
   `_render_price_intelligence_chart()` sin egen SVG-`width`) i stedet
   for det tidligere 1100px-taket -- "the attached image is the sizing
   reference", ikke et vilkårlig prosenttall. Innenfor et nå ~940px
   innholdsområde gir 680px synlig, symmetrisk luft på begge sider.
4. **Kortene byttet fra CSS Grid `auto-fit` til flexbox med
   `justify-content:center`** -- `auto-fit` STREKKER hvert spor til å
   dele bredden likt uansett antall kort, som var nøyaktig mekanismen
   bak de "gigantiske 50/50-kortene". Hvert kort har nå et fast
   intendert tak (`flex:0 1 300px; max-width:300px`), og
   `justify-content:center` sentrerer 1, 2 eller 3 kort som en gruppe --
   verifisert eksplisitt at et ENKELT kort (produkt med kun 1 tilbud)
   forblir 300px bredt i en 942px rad, IKKE strukket til full bredde.
5. **Flere dato-etiketter på grafens X-akse** -- ny tikk-beregning i
   `_render_price_intelligence_chart()` (ca. én tikk per uke, 7-9 totalt)
   erstatter det gamle "kun første og siste dato". Samme server-rendrede
   SVG for mobil og desktop -- en ny CSS-regel
   (`@media(max-width:639px){.price-history-axis-label-x:not(.price-history-axis-label-edge){display:none}}`)
   skjuler de mellomliggende på mobil, som beholder den kompakte
   to-etiketters visningen uendret. **Egen bug fanget og fikset i egen
   testing, før noe ble sendt til Kai**: første forsøk lot siste
   regulære tikk (f.eks. "28.09") stå rett attmed det alltid-inkluderte
   sluttpunktet ("29.09") -- så nære at de visuelt kolliderte målt i
   browser-panelet (kun 21,6px fra hverandre i et 680px viewBox). Fikset
   ved å droppe den siste regulære tikken når den ligger nærmere
   sluttpunktet enn et halvt tikk-intervall.
6. **Synlig (i)-ikon lagt til** ved siden av "Høyeste prisnivå" og
   "30-dagers median" (ny `.price-intel-metric-info`-span, gjenbruker
   samme ⓘ-glyf som resten av siden) -- de hadde allerede en
   `title`-hover-tooltip fra logikkrunden, men INGEN visuell indikasjon
   på at feltet var informativt/hover-bart, som Kai påpekte manglet.
7. **Tettere vertikal rytme**: margin-top/padding-top redusert med
   2-4px på tvers av kort-rad/oppsummering/data-stripe/footer (18->14,
   14->12 osv.) -- liten endring hver for seg, men samlet en synlig
   tettere, mer "redaksjonell" tetthet i stedet for luftig/flat.

Testet: bygget + `validate_build.py` OK (201/201), full sveip ingen
Traceback/NameError. Verifisert eksplisitt på nytt mot Biofinity Toric
6-pack (samme eksempel Kai brukte i kritikken): modul 1000px, graf-hylle
680px, kort 300px hver, `gap:28px` (ikke lenger space-between) mellom
metrikkrad og statuspille -- alle mål bekreftet med
`getBoundingClientRect()`, ikke bare visuelt antatt. Dato-tikker
verifisert til 8 jevnt fordelte etiketter (31.08 -> 29.09) uten
kollisjon etter fiksen. Mobil (375px) re-sjekket: kun 2 synlige
dato-etiketter (uendret oppførsel), kort faller naturlig til ~297px
(under 300px-taket, ingen strekking uansett på en smal skjerm). Testet
1-tilbuds-produkt (Biofinity Multifocal Toric 3-pack) eksplisitt for å
bekrefte punkt 4: ett enkelt kort forblir 300px, sentrert, IKKE strukket
til 942px. Linsevæske (ReNu Multi-Purpose 60 ml) bekreftet samme
1000px/300px-mål som kontaktlinse-produktsiden.

## Price Intelligence v2, runde 3: full modulbredde, typografi, samlet konklusjon (2026-10-05)

Kai bekreftet etter live-måling at "smalere" gjaldt KUN grafen, ikke hele
modulen -- runde 2 hadde feiltolket det og kappet `.price-intel` til
1000px. Rettet:

- **Modulen er tilbake til full innholdsbredde** (1240px ved 1400px
  viewport); grafen er fortsatt smalere og sentrert (`max-width:980px`,
  var 680px -- for lite mot en bred modul), nå i en tynn ramme med
  verktøylinjen inni (som i mockupen, men uten falsk dropdown-chevron).
- **Typografi (kun >=860px):** "Pris nå" 3rem (48px, var 33,6px),
  sekundærverdier 1,6rem, etiketter 0,8rem. Forklaringstekst
  (`.price-intel-metric-desc`, dempet) gjeninnført under "Høyeste
  prisnivå" og median.
- **Y-akse:** ny `_nice_axis_ticks()` gir 3-5 runde nivåer innenfor det
  UENDREDE domenet fra `_price_intel_chart_domain()` (materialitet/
  minimumsspenn urørt).
- **Kort:** hvert kort er nå `calc((100% - 24px)/3)` bredt, sentrert --
  to kort = ca. 33 % hver (385px av 1178px), tre kort = mockupens
  tre-kolonne-layout. "Kjøper du flere esker?"-logikken (skjult uten
  vinnerbytte) er uendret.
- **"Kort fortalt" + datastripen er ETT modul** (`.price-intel-conclusion`,
  blå boks med hvit stripe under, tynne skillelinjer mellom de fem
  statistikkene på desktop) i stedet for to blokker.
- **Status mot median:** `_vs_median_text()` gir f.eks. "Dagens laveste
  pris er 479 kr, 5,5 % over 53-dagers medianen på 454 kr." for
  Høyt prisnivå / Laveste registrerte pris (regnet dynamisk).
- **Uavgjort i prisvinnere:** `_price_intelligence_merchant_winners()`
  returnerer `top_stores`/`total_wins`; teksten nevner alle butikker med
  samme toppantall ("Lensit og Lenson har begge hatt ... i 23 av de siste
  53 dagene"), og hver rad viser andel av dager med vinner ("23 dager ·
  43 %"). Verifisert mot de ekte tallene (23/23/7 -> 43/43/13 %).
- Fortsatt bevisst uten klokkeslett, "Oppdatert i dag" og falsk dropdown
  (statisk side / ærlighet).

Test-lærdom: lokal `catalog_live.json` har utgåtte tilbud når dagen har
skiftet, så spread-/qty-kortene forsvinner lokalt. Verifiser layout ved å
bygge fra en midlertidig kopi med ferske `checked_at` (ikke commit den, og
`git checkout site_generator/price_history.json` etterpå -- et lokalt bygg
skriver dagens rad dit).

## Price Intelligence: statusboksen overlappet metrikkene på smalere/mellomstore bredder (2026-10-05)

Kai rapporterte at den røde "Høyt prisnivå"-boksen la seg over metrikkteksten
til høyre på mellomstore bredder. Reprodusert og målt FØR endring: metrikkraden
(`.price-intel-metrics-row`, `flex-wrap: nowrap`, kolonner `flex: 0 0 auto`) har
en naturlig bredde på 913px, mens statuspillen var `flex-shrink: 0; width:
290px` + 28px gap -- 1231px totalt i en modul med maks 1180px innhold. Overlappet
fantes derfor på ALLE desktopbredder (selv 1400px: median-kolonnen stakk ~25px
under pillen), og ved 1000px ga det til og med sideoverflow.

Rot-årsak var at toppraden ikke kunne wrappe og at ingenting skalerte med
MODULENS bredde. Fiks (kun CSS i `SHARED_STYLE`, ingen absolute/transform/
negative marger):
- `.price-intel` er nå en container (`container-type: inline-size;
  container-name: pintel`) -- modulen er smalere enn viewporten, så
  `@media` ville truffet feil terskel.
- ≥860px: `.price-intel-primary.active` er `flex-wrap: wrap` med `gap: 20px
  24px`. Pillen er `flex: 0 1 270px; min-width: 240px; max-width: 360px` og
  ligger til høyre KUN hvis den faktisk får plass; ellers wrapper den ned på
  egen rad, venstrejustert, i naturlig bredde. Fungerer også for lange
  statustekster (stress-testet).
- Metrikkradens naturlige bredde strammet fra 913px til 849px (kolonnepadding
  18->16px, forklaringstekst `max-width` 210->185px) slik at pillen faktisk
  får plass ved siden av ved full modulbredde (849 + 24 + 270 = 1143 <= 1180).
- `@container pintel (max-width: 940px)` (inni `@media (min-width: 860px)`):
  metrikkene går i et 3-kolonne-rutenett under "Pris nå" (som mobil, uten
  skillelinjer) og pillen tar egen rad (maks 420px).
- Mobil (<860px) er urørt (blokk-layout som før); uten container-query-støtte
  gjelder kun mobilstylingen, som er trygg.

Målt (`getBoundingClientRect`, overlapp pille-metrikk, metrikker inni modulen,
"Vi har fulgt..."-kortet vs. introtekst): 860/1000/1100/1200 px -> pillen under,
ingen overlapp; 1300/1400/1600 px -> pillen til høyre, ingen overlapp; 768 og
375 px uendret. NB (ikke fra denne endringen, ikke rettet): hero-vinnerkortet
(`.winner-band-cta`) gir sideoverflow på 860-1200px viewport (`scrollWidth` >
viewport) -- eget funn utenfor Price Intelligence.
