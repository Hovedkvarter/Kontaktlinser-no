# Black Friday og månedlig tilbakeblikk

Dato: 2026-11-08. Kontaktlinser.no, lokal implementering. Ikke publisert.
Base: f18b25f26e1c067cdd6ed9cd99acc047fba63a46. Separat fra startside-PR #50.

## VEDTATT
Black Friday først. Budskap: «Lave priser på kontaktlinser – og bekreftede Black Friday-tilbud». Dagens priser er nyttige også uten prisfall. Ingen fremtredende «er prisene faktisk lavere»-seksjon. Publisering krever eiergodkjenning.
Gjenbruk produktutvalg fra PR #49: flest unike butikker med ferske priser på lager først, tre modeller per linsetype. Gjeldende Lensit-avgrensning beholdes.

## IMPLEMENTERT
- /black-friday-kontaktlinser/ med eksisterende søk, produktkort, Mulish, kategorifilter og kjøpehjelp.
- 12 faktiske produkter i kontrollbygget. Ingen førpriser eller Spar-merker på denne siden; butikkforskjell blir ikke presentert som en kampanje.
- Egen redaksjonell seksjon for bekreftede kampanjer. Ingen kampanje er lagt inn; dagens tomtilstand sier dette tydelig.
- Canonical, CollectionPage/ItemList og BreadcrumbList; sitemap og lastmod via eksisterende generator.
- Diskrete lenker fra forside og «Billige linser på nett». Ingen endret import, sporing, samtykke eller affiliate-ruting.

## OBSERVERT / KONTROLL
25 Python-tester og 47 JavaScript-søketester bestått, i tillegg til SEO-testene og byggevalidering (231/231 produkter med priser).
Full byggdiff før/etter med fast tidspunkt: én ny HTML-side, to eksisterende sider med nye interne lenker; 487 eksisterende HTML-sider identiske. Ingen interne lenkemål mangler på ny side.
Nettleser: Biofinity gir 13 treff; torisk filter gir tre produkter. Mobil 360 CSS-piksler og nettbrett 753 CSS-piksler uten horisontal sideoverflyt; mobil via iframe, ikke fysisk enhet. Hele desktop-siden kontrollert. Skjermbilder i samme mappe.
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
Gjennomgå Draft PR og skjermbilder, avstem med startside-PR #50 før merge. Verifiser kilder, gyldighetsperiode, produkter og vilkår før første kampanje føres inn; utløpte kampanjer må fjernes ved redaksjonell oppdatering. Dagens prisoppdatering lager ikke kampanjer automatisk. Godkjenning kreves før publisering. Avklar datagrunnlag for månedsarkivet etter Black Friday-siden.
