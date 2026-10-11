# Vinnerboks – status 11. oktober 2026

## Beslutning
Brukerens skjermbilde 2 er førende for mellomstore skjermer: tittel over produktbilde og vinnerkort, med antallsvelger under. Trekolonnevisningen aktiveres fra 1280 CSS-piksler i stedet for 860. Den krever minst 1198 piksler inklusive kolonner, gap, padding og kantlinjer.

## Implementert
- Flyttet produktsidens sammenhengende desktopregler til 1280 px.
- Utvidet eksisterende kompakt vinnerkortstil til og med 1279 px.
- Sikret at delt widget-CSS ikke overstyrer kortets plassering og padding i dette intervallet.
- Kun CSS og tilhørende kommentarer er endret. Ingen endringer i priser, URL-er, sporing, affiliateflyt eller innholdsstruktur.

## Verifisert
- Bygg og validering bestått, 201/201 produkter med priser.
- 375, 768, 1024 og 1440 px: med og uten JavaScript; ingen horisontal overflyt.
- 48 priskombinasjoner bestått (1/2/4/6/8/10 esker, med/uten frakt, fire bredder).
- Periodebytte og de tre innsiktsboksene fungerer fortsatt.
- 48 layoutkontroller: fire produkter inkludert Live 30-pack og to lange navn, på 375/768/859/860/900/1023/1024/1100/1200/1279/1280/1440 px. Ingen side-overflyt eller vinnerkort utenfor skjermen.
- Nettleser: Chromium 153, lokal isolert forhåndsvisning. Eksterne tjenester ble blokkert under funksjonstestene. Ingen fysisk enhet eller Safari-test.

## Status og neste steg
Implementert og kontrollert i egen gren. Ikke merget eller publisert. Visuell godkjenning av forhåndsvisningen gjenstår før publisering.

Den tidligere kontrollens ni eksisterende clickout-testfeil og kalendersemantikk ved hull i historikken ligger utenfor denne CSS-rettingen.
