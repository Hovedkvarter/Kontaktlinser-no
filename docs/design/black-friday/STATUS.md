# Black Friday og månedlig tilbakeblikk

Dato: 2026-11-08. Kontaktlinser.no, lokal implementering. Publisert og kontrollert på kontaktlinser.no 2026-11-08.
Base: f18b25f26e1c067cdd6ed9cd99acc047fba63a46. Separat fra startside-PR #50.

## VEDTATT
Black Friday først. Budskap: «Lave priser på kontaktlinser – og bekreftede Black Friday-tilbud». Dagens priser er nyttige også uten prisfall. Ingen fremtredende «er prisene faktisk lavere»-seksjon. Publisering ble godkjent av eier i oppfølgingen.
Gjenbruk produktutvalg fra PR #49: flest unike butikker med ferske priser på lager først, inntil åtte modeller per linsetype, totalt 30. Gjeldende Lensit-avgrensning beholdes.

## IMPLEMENTERT
- /black-friday-kontaktlinser/ med eksisterende søk, produktkort, Mulish, kategorifilter og kjøpehjelp.
- 30 faktiske produkter i kontrollbygget. Ingen førpriser eller Spar-merker på denne siden; butikkforskjell blir ikke presentert som en kampanje.
- Egen redaksjonell seksjon for bekreftede kampanjer. Ingen kampanje er lagt inn; dagens tomtilstand sier dette tydelig.
- Canonical, CollectionPage/ItemList og BreadcrumbList; sitemap og lastmod via eksisterende generator.
- Diskrete lenker fra forside og «Billige linser på nett». Ingen endret import, sporing, samtykke eller affiliate-ruting.

## OBSERVERT / KONTROLL
26 Python-tester og 47 JavaScript-søketester bestått, i tillegg til SEO-testene og byggevalidering (231/231 produkter med priser).
Full byggdiff før/etter med fast tidspunkt: én ny HTML-side, to eksisterende sider med nye interne lenker; 487 eksisterende HTML-sider identiske. Ingen interne lenkemål mangler på ny side.
Nettleser: Biofinity gir 13 treff; torisk filter gir åtte produkter. Mobil 360 CSS-piksler og nettbrett 753 CSS-piksler uten horisontal sideoverflyt; mobil via iframe, ikke fysisk enhet. Hele desktop-siden kontrollert. Skjermbilder i samme mappe.
Læring: gjenbruk av produktkort med comparison_offers lager butikkbaserte sparemerker. På kampanjesiden sendes laveste pris og unikt butikkantall uten comparison_offers. Regresjonstest dekker at prisforskjell mellom butikker ikke blir rabattpåstand og at utdaterte priser forsvinner.

## FORSLAG / ÅPENT: månedlig tilbakeblikk
Eier ønsker «hva som skjedde forrige måned»: nye produkter, største prisfall, topp 5/10 mest populære hos Kontaktlinser.no og et nyttig tema, med permanent historikk. Dette er neste oppgave, ikke implementert eller automatisk planlagt nå.
Foreslått struktur: én oversikt med lenker til faste månedsutgaver. Hver månedsutgave fryses med periode, observasjonsdato, kildegrunnlag, metodeversjon og eventuelle rettelser; gamle resultater overskrives ikke av dagens priser.
- Nye produkter: skill nye i vår katalog fra dokumenterte nye lanseringer.
- Prisfall: samme modell og pakning, faste start/sluttpunkter eller annen eksplisitt metode, stabilt butikkutvalg og synlige dekningshull. Ikke bland prisfall med forskjeller mellom butikker.
- Popularitet: avklar eksisterende aggregerte analysedata og tilstrekkelig volum; mål for eksempel produktbesøk, ikke påstå salg. Hold annonseutvalg og popularitetsrekkefølge adskilt. Ingen endring av samtykke eller tracking i denne oppgaven.
- Historisk lagring: gjenbruk repositoryets eksisterende datalagring/arkiv der egnet, daterte strukturerte månedsfiler og redaksjonelle tekster. En ny databaseplattform er ikke nødvendig som første steg. Oppbevar bare aggregerte publiserbare tall i offentlig repository.
- Månedens nyttige tema og tre konkrete endringer gir redaksjonell verdi; unngå bare nytt månedsnavn på samme tekst.

## Neste steg
Gjennomgå Draft PR og skjermbilder, avstem med startside-PR #50 før merge. Verifiser kilder, gyldighetsperiode, produkter og vilkår før første kampanje føres inn; utløpte kampanjer må fjernes ved redaksjonell oppdatering. Dagens prisoppdatering lager ikke kampanjer automatisk. Eier har godkjent publisering. Avklar datagrunnlag for månedsarkivet etter Black Friday-siden.

## Oppfølging før publisering
Eier endret ønsket fra 32/fire til 30 produkter/fem per rad på desktop. Mobil beholder to. Popularitetstall er ikke verifisert; sorteringen følger fortsatt butikkdekning og kalles ikke mest populær. Ingen annen PR er inkludert i denne publiseringen.

## Publiseringsresultat
PR #51 merget: b37eb2d8bcc8f0cba4588e09f645ab02c1175abf. PR-kontroll 42475638109 og publiseringsjobb 42475783613 fullført med success. Aktiv side kontrollert i nettleser: https://kontaktlinser.no/black-friday-kontaktlinser/ viser 30 produkter, fem i første desktoprad, korrekt canonical og torisk filter med åtte produkter. Lokal mobilkontroll etter utvidelse: 30 produkter, to per rad, 360 px uten overflyt. Startside-PR #50 er ikke inkludert.


## Black Friday-design 2026-11-08
VEDTATT: Eier godkjente skissen med mørk marineblå topp, blå fokusringer, hvitt søk og lyst produktområde, og ba uttrykkelig om publisering.
IMPLEMENTERT: Kun black_friday.py endret. Dekor i CSS uten bildefiler eller ekstra nettverkskall. Mulish, innhold, 30 produkter, metadata og dataflyt beholdt. På mobil dempes ringene.
KONTROLL: 26 relevante Python-tester, 47 søketester i JavaScript, SEO-kontroll og byggevalidering bestått. Desktop og 360 px mobilramme kontrollert, ingen horisontal sideoverflyt. Biofinity viser 13 treff. Søkelisten ligger over produktkortene.
LÆRING: Isolert hero lager egen stablingskontekst; eksplisitt z-index er nødvendig for at søkeforslag skal ligge over produktkort. Dekor klippes i eget element, ikke i hero som inneholder søket.
NESTE STEG: Publisering og kontroll av aktiv side. Månedlig tilbakeblikk fortsatt åpent.

PUBLISERT: PR #52 merget som c567beb48094efdb2205733cb29b7bee6caad18b. PR-kontroll 42480430518, byggejobb 42480593768 og Pages-utrulling 42480714430 fullført med success. Aktiv side viste ny bf-hero etter oppfriskning i nettleser. Skjermbilde av samme design fra forhåndsvisning: dark-desktop.png. Ingen åpne blokkeringer for designet.


## Ordinære produktkort 2026-11-08
VEDTATT: Eier ønsker nettstedets ordinære produktoppføring, inkludert Spar-merke og sammenligningspris. Tidligere beslutning om å utelate disse på Black Friday er erstattet. Kun CTA-fargen skal være mørk marineblå som hero.
IMPLEMENTERT: Eksisterende felles kortmal og beregning gjenbrukes, produsent vises som på merkekortene. Synlig felles forklaring over utvalget presiserer butikkforskjell, ikke historisk pris/kampanjerabatt. Ingen endring av prisgrunnlag, sortering eller øvrige sider.
KONTROLL: 26 tester bestått, byggevalidering 231/231. Acuvue Oasys viser Spar 24 %, 349 kr sammenligningspris, fra 262 kr og Johnson & Johnson Vision. Desktop og mobilknapp kontrollert; bakgrunn #061629. Testen bekrefter at dubletter fra samme butikk ikke øker sammenligningsprisen. Skjermbilde: standard-cards.png.