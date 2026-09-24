"""Chillout-clickouts hentet fra lesekontrakten pa byggetidspunktet.

Erstatter det hardkodede bootstrap-tokenet. Forskjellen er ikke at regelen er
losere -- den er strammere: **generatoren kan ikke lenger lage en /go/-lenke.**
Det finnes ingen formatstreng, ingen prefiks og ingen token her. Den har enten
en streng Chillout har returnert, eller ingenting.

## Hva den ber om

Ett kall per produkt siden kan koble et tilbud pa, mot **katalogruta**. Den
tar propertyens egen identifikator, sa generatoren holder ingen plattform-id
og vedlikeholder ingen tabell over dem.

Denne modulen argumenterte en gang mot nettopp den ruta: et manglende alias
svarer 404, som ikke kunne skilles fra en odelagt nokkel. Innvendingen var
riktig da den gjaldt ETT produkt. Den forsvinner nar vi spor om hundre og
seksti: en odelagt nokkel gir 401 pa alle, en manglende alias gir 404 pa ett,
og bygglinja viser hvor mange som svarte.

## Hva den slipper gjennom

**Ingenting velges her.** Et tilbud rendres gjennom Clickout nar Chillouts
lesekontrakt sier at denne propertyen har en servable clickout for det, og
flaten star pa. Det fantes en tillatelsesliste -- CONVERTED, ett tilbud om
gangen -- og den var riktig mens spørsmalet var "virker dette i det hele
tatt". Na er den borte, og det er hele poenget med steg 4.

Fire fakta som fortsatt ikke er hverandre: at vi HAR tilbudet er ikke at
propertyen far selge det; at den far selge det er ikke at et servable mal
finnes; at malet finnes er ikke at vi har bestemt oss for a bruke det. Det
siste er flatebryteren, og den er det eneste dette repoet eier.

Annonsor og leverandor er ingen av dem en dekningsakse. En annonsor uten
`chillout_feed_id` far ingen lenke -- ikke fordi noen har valgt bort
annonsoren, men fordi ADR-031s nokkel er feed pluss external_id og vi da ikke
kan koble svaret til et kort.

## Nar noe gar galt

Alt faller tilbake til leverandor-URL-en, som er det siden rendret for
bootstrap-en og som alltid virker. Byggets jobb er a bli ferdig: et bygg som
feilet ville stoppet prisoppdateringene, og det er formen pa hendelsen
2026-08-27 da en feilet henting lot hele siden sta uten priser.

**::warning::, ikke ::error::.** Tilbakefall til leverandor-URL er en stottet,
trygg driftsmodus -- ikke en feil. En error-annotasjon feiler ikke jobben av
seg selv, men den rendres rodt pa Checks-fanen og telles med, og et gront bygg
med rode annotasjoner leser som odelagt. Arsaken er synlig uansett.

## Hemmeligheten

Nokkelen leses en gang, settes i en header, og leses aldri tilbake. Ingen
forespørsel skrives ut, ingen unntaksmelding videreformidles -- ved
nettverksfeil rapporteres unntakets TYPE, fordi et unntak kan bære
forespørselen og forespørselen bærer headeren.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

#: **Produktnavnerommene siden har.** Katalogruta tar propertyens EGEN
#: identifikator, sa generatoren trenger ingen plattform-id -- den spor med
#: den id-en den allerede har i URL-ene sine.
LENS_NAMESPACE = "products_meta"
SOLUTION_NAMESPACE = "solutions_meta"

#: **Flatene, og hva de heter i oppsettet.** Rekkefølgen er lesbarheten sin;
#: koden bryr seg bare om navnene. En ny flate ma sta her OG i
#: clickout_surfaces.json, sa en flate som glemmer det ene er av og ikke
#: stille pa.
SURFACES = ("offer_card", "winner_band", "quantity_calculator")

#: Filen som holder tilstanden. I DETTE repoet, med vilje -- se $comment der.
SURFACES_FILE = "clickout_surfaces.json"

#: Repoets rot. Modulen ligger i site_generator/, oppsettfilene et niva over.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROPERTY = "kontaktlinser-no"
#: **Ingen default.** Originet var hardkodet her, arvet fra en midlertidig
#: verifisering framfor valgt -- og en default i kildekoden er nettopp det
#: som gjor at ingen tar avgjørelsen. Cloudflare-workeren gjor det allerede
#: riktig: `CLICKOUT_ORIGIN` er en variabel uten default, sa a flytte
#: originet er a endre en verdi og ikke a redigere kode.
#:
#: Ikke en secret. Den er ikke hemmelig, og a gjore den til en ville skjult
#: den i en logg der den nettopp er det man vil se.
ORIGIN = os.environ.get("CHILLOUT_ORIGIN", "").strip().rstrip("/")
KEY_VARIABLE = "CHILLOUT_READ_KEY"
TIMEOUT = 20


#: **Flatene, og hva de heter i oppsettet.** Rekkefølgen er lesbarheten sin;
#: koden bryr seg bare om navnene. En ny flate ma sta her OG i
#: clickout_surfaces.json, sa en flate som glemmer det ene er av og ikke
#: stille pa.
SURFACES = ("offer_card", "winner_band", "quantity_calculator")

#: Filen som holder tilstanden. I DETTE repoet, med vilje -- se $comment der.
SURFACES_FILE = "clickout_surfaces.json"


class Clickouts(dict):
    """De loste clickout-URL-ene, og hvilke flater som far bruke dem.

    **To spørsmal, ett objekt, fordi de alltid reiser sammen.** Hvilke tilbud
    som HAR en clickout er Chillouts svar; hvilke flater som far vise den er
    clickout_surfaces.json.
    Rendreren ma kunne svare pa begge pa samme kall, og a tre en ekstra
    parameter gjennom seks kallsteder ville gjort det lett a glemme pa den
    sjuende.

    Den ER en dict, sa alt som tok imot kartet for tar det fortsatt imot. Et
    vanlig dict -- som testene og eldre kallere sender -- har ingen `enabled`,
    og leses da som "alle flater pa": det er nøyaktig det de mente for denne
    bryteren fantes.
    """

    def __init__(self, resolved: dict, enabled) -> None:
        super().__init__(resolved)
        self.enabled = frozenset(enabled)


def enabled_surfaces() -> frozenset[str]:
    """Hvilke flater som star pa for DENNE propertyen.

    **Ingenting star pa ved et uhell.** En manglende fil, en manglende
    property, en ukjent verdi eller en skrivefeil gir av -- og en synlig
    advarsel. Det motsatte valget ville betydd at en odelagt fil kunne sla
    clickout PA et sted noen hadde skrudd det av, som er den ene retningen en
    bryter aldri skal kunne feile i.

    Av er alltid trygt: leverandor-URL-en er det siden rendret for clickout
    fantes, og den virker.
    """
    try:
        raw = open(os.path.join(_ROOT, SURFACES_FILE), encoding="utf-8").read()
        states = json.loads(raw)[PROPERTY]
    except Exception as error:
        _warn(f"kunne ikke lese flateoppsettet ({type(error).__name__})", "ingen flater")
        return frozenset()

    if not isinstance(states, dict):
        _warn("flateoppsettet har feil form", "ingen flater")
        return frozenset()

    on = set()
    for surface in SURFACES:
        value = states.get(surface)
        if value == "on":
            on.add(surface)
        elif value not in (None, "off"):
            # **En skrivefeil skal aldri kunne sla noe pa.** Den leses som av,
            # og den sies hoyt: en flate som forsvant uten at noen ba om det
            # ser ellers ut som en flate noen skrudde av med vilje.
            _warn("ukjent verdi i flateoppsettet, lest som av", f"{surface}={value!r}")

    unknown = sorted(set(states) - set(SURFACES) - {"$comment"})
    if unknown:
        _warn("ukjent flate i oppsettet, ignorert", ", ".join(unknown))
    return frozenset(on)


def _renderer_keys() -> dict[str, tuple[str, str]]:
    """Chillouts tilbudsnokkel til den nokkelen kortet kan sla opp pa.

    **Dette er ikke en sammenkobling mellom to systemer.** Begge sidene av
    denne funksjonen er sidens egne filer: `sources_config.json` eier bade
    `chillout_feed_id` og `display_name`, og `retailer` pa et tilbud ER
    `display_name` (ingest_feed.py setter det derfra). `product_matching.json`
    eier SKU-til-produkt. Sammenkoblingen mot Chillout skjer pa `offer_id`
    alene, lenger nede.

    Grunnen til at kortet ikke bare slas opp pa offer_id: et tilbud i
    katalogen har ingen SKU. Kortet vet produkt og forhandler, og det er den
    nokkelen det kan sporre med.

    Feiler aldri. Mangler en fil eller et felt, blir kartet tomt, og da star
    leverandor-URL-ene -- samme trygge utgang som alt annet her.
    """
    try:
        sources = json.loads(
            open(os.path.join(_ROOT, "sources_config.json"), encoding="utf-8").read()
        )
        matching = json.loads(
            open(os.path.join(_ROOT, "product_matching.json"), encoding="utf-8").read()
        )
    except Exception as error:
        _warn(f"kunne ikke lese katalogoppsettet ({type(error).__name__})", "oppslag")
        return {}
    return _keys_from(sources, matching)


def _keys_from(sources: dict, matching: dict) -> dict[str, tuple[tuple[str, str], ...]]:
    """Den rene delen av oppslaget, skilt ut sa den kan testes mot de EKTE
    tabellene uten a lese filer.

    **Ett offer_id kan gi FLERE kort.** Fire ekte oppforinger i
    product_matching.json peker pa TO interne produkter: det samme fysiske
    produktet holdes med vilje under to id-er av søkegrunner, og siden rendrer
    da samme tilbud pa begge produktsidene.

    Det er ikke tvetydighet om hvilket TILBUD som menes -- offer_id er feed
    pluss external_id og er entydig -- men om hvor siden viser det. Svaret er
    begge steder, og en bekreftet clickout hører derfor hjemme pa begge
    kortene: det er samme tilbud hos samme annonsor, og samme servable target.

    Forste utgave antok en streng og ville lagt en LISTE inn i
    oppslagsnokkelen. Den hadde sa blitt brukt som dict-nokkel og kastet
    `TypeError: unhashable type: 'list'` ut av byggingen -- null sider skrevet.
    Latent til na bare fordi ingen kilde pa den tabellen har en feed-id.
    """
    keys: dict[str, tuple[tuple[str, str], ...]] = {}
    for config in sources.values():
        if not isinstance(config, dict):
            continue
        feed_id = config.get("chillout_feed_id")
        table = matching.get(config.get("network") or "")
        retailer = config.get("display_name")
        if not (feed_id and isinstance(table, dict) and retailer):
            continue
        for sku, product_id in table.items():
            if sku.startswith("$"):
                continue
            products = product_id if isinstance(product_id, list) else [product_id]
            named = tuple(
                (p, retailer) for p in products if isinstance(p, str) and p
            )
            if named:
                keys[f"{feed_id}:{sku}"] = named
    return keys


def _warn(category: str, detail: str) -> None:
    """En synlig, kategorisert linje -- og ingenting mer enn det.

    `detail` settes bare av kallstedene under, aldri av et unntak: en
    unntaksmelding kan inneholde forespørselen.
    """
    message = f"Chillout-clickout: {category} -- lenker falt tilbake til leverandor-URL ({detail})"
    print(message)
    print(f"::warning::{message}")


def _fetch(namespace: str, local: str, key: str) -> tuple[dict | None, str]:
    """Ett produkts sammenligning, eller en navngitt grunn til at den mangler.

    **Katalogruta, ikke den interne.** Den tar propertyens egen identifikator,
    sa generatoren holder ingen plattform-id og vedlikeholder ingen tabell
    over dem. Den gamle innvendingen mot ruta -- at en manglende alias svarer
    404, som ikke kan skilles fra en odelagt nokkel -- er borte i det vi spor
    om 160 produkter: en odelagt nokkel gir 401 pa alle, en manglende alias
    gir 404 pa ett. Tallet skiller dem, og bygglinja viser tallet.
    """
    url = f"{ORIGIN}/api/v1/properties/{PROPERTY}/catalogue/{namespace}/{local}/offers"
    request = urllib.request.Request(url, headers={"authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except urllib.error.HTTPError as refusal:
        # 401 og 403 holdes fra hverandre med vilje. Den ene betyr rotér
        # nokkelen, den andre betyr at nokkelen tilhorer en annen Property, og
        # a sla dem sammen sender noen til a fikse feil ting.
        return None, {
            401: "autentisering avvist (401)",
            403: "nokkelen gjelder en annen Property (403)",
            404: "produktet finnes ikke i Chillouts katalog (404)",
            503: "Chillout utilgjengelig (503)",
        }.get(refusal.code, f"uventet svar ({refusal.code})")
    except Exception as error:
        return None, f"forespørselen feilet ({type(error).__name__})"


def _clickouts_in(body: object) -> dict[str, str]:
    """**offer_id** til clickout-URL, for de tilbudene som faktisk har en.

    Bade `offers` og `excluded`: et ekskludert tilbud er tatt ut av den
    sammenlignbare sorteringen, ikke gjort uneabart, og a holde tilbake lenken
    ville gjort en sorteringsbeslutning om til en rutingbeslutning.

    **Ingenting her stoler pa formen pa svaret.** Forste utgave gjorde det og
    kastet `AttributeError` pa en 200 med en JSON-liste, og `TypeError` pa
    `{"offers": null}` -- ut av `build()`, sa bygget dode med null sider
    skrevet og siden ble staende med gardagens priser. Det er nøyaktig
    utfallet modulen finnes for a unnga, og verre enn a ikke ha noen lenke.
    Chillout kan ikke sende de formene i dag; en mellomliggende proxy eller
    en framtidig kontraktsendring kan. Samme resonnement som source-leddet:
    "neppe" er ikke en garanti pa denne siden av HTTP.
    """
    if not isinstance(body, dict):
        return {}
    found: dict[str, str] = {}
    for key in ("offers", "excluded"):
        group = body.get(key)
        if not isinstance(group, list):
            continue
        for offer in group:
            if not isinstance(offer, dict):
                continue
            link = offer.get("link")
            offer_id = offer.get("offer_id")
            url = link.get("clickout_url") if isinstance(link, dict) else None
            if (
                isinstance(link, dict)
                and link.get("clickout_available")
                and isinstance(url, str)
                and isinstance(offer_id, str)
            ):
                found[offer_id] = url
    return found


def clickout_urls(products) -> Clickouts:
    """(produkt-id, forhandler) -> /go/-sti, for det Chillout bekrefter.

    **Dekningen er ikke lenger en liste.** Et tilbud rendres gjennom Clickout
    nar Chillouts lesekontrakt sier at DENNE propertyen har en servable
    clickout for det, og flaten star pa. Ingenting her velger tilbud, og det
    finnes ikke lenger et sted a velge dem.

    De fire skillene som ma bli staende, fordi de er fire forskjellige fakta:
    at vi HAR tilbudet er ikke at propertyen far selge det; at den far selge
    det er ikke at et mal finnes; at malet finnes er ikke at vi har bestemt
    oss for a bruke det. Det siste er flatebryteren, og det er det eneste
    dette repoet eier.

    `products` er sidens egen katalog. Den brukes til to ting og ingenting
    annet: hvilke produkter som spørres om, og hvilket navnerom hvert av dem
    ligger i.

    Tom dict er et gyldig og trygt svar: hvert kort faller da tilbake til sin
    egen leverandor-URL, som er det siden rendret for clickout fantes.
    """
    if not ORIGIN:
        # Samme trygge utgang som alt annet her, og samme skille: lokalt er
        # dette normalen, i CI betyr det at variabelen ikke er satt.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            _warn("CHILLOUT_ORIGIN er ikke satt for dette steget", "intet origin")
        else:
            print("Chillout-clickout: CHILLOUT_ORIGIN er ikke satt -- bruker leverandor-URL-er")
        return Clickouts({}, ())

    key = os.environ.get(KEY_VARIABLE, "").strip()
    if not key:
        # **Lokalt er dette normalt. I CI er det en feil.**
        #
        # Et lokalt bygg har ingen secret og skal ikke se ut som om noe er
        # galt. Men i GitHub Actions SKAL nokkelen være der, og en manglende
        # nokkel der betyr at secreten ikke finnes, ikke er navngitt likt,
        # eller ikke er gitt til dette steget -- det siste er lett a gjøre,
        # fordi en secret ikke er tilgjengelig for et steg uten en env-blokk.
        # Uten dette skillet ville konverteringen forsvunnet stille.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            _warn(f"{KEY_VARIABLE} er ikke tilgjengelig for dette steget", "ingen nokkel")
        else:
            print(f"Chillout-clickout: {KEY_VARIABLE} er ikke satt -- bruker leverandor-URL-er")
        return Clickouts({}, ())

    keys = _renderer_keys()
    resolved: dict[tuple[str, str], str] = {}

    # **Hvilke produkter som spørres om, utledes av oppslaget.** Et produkt
    # spørres om nar en tilbudsnokkel i det hele tatt kan peke pa et kort der.
    # Det er ikke en godkjenningsliste: den sier ingenting om hvorvidt
    # Chillout HAR en clickout for tilbudet, bare at svaret kan kobles til et
    # kort hvis det kommer et.
    catalogue = {p["id"]: p for p in products if isinstance(p, dict) and p.get("id")}
    wanted = sorted({card[0] for cards in keys.values() for card in cards} & set(catalogue))

    failures: dict[str, int] = {}
    answered = 0
    for product_id in wanted:
        namespace = (
            LENS_NAMESPACE
            if "category_slug" in catalogue[product_id]
            else SOLUTION_NAMESPACE
        )
        body, reason = _fetch(namespace, product_id, key)
        if body is None:
            # **Aggregert, ikke en linje per produkt.** 160 identiske
            # advarsler ville begravd den ene som var annerledes.
            failures[reason] = failures.get(reason, 0) + 1
            continue
        answered += 1
        for offer_id, url in _clickouts_in(body).items():
            # **Sammenkoblingen er offer_id, og ingenting annet.** Ingen
            # annonsor, intet visningsnavn, ingen normalisering av tekst. Et
            # tilbud vi ikke kan slaa opp far ingen lenke -- det er en
            # manglende kobling, ikke en avvisning av annonsoren.
            #
            # **Ikke `key`.** Legitimasjonen heter `key` i denne funksjonen,
            # og en løkkevariabel med samme navn overskrev den en gang.
            for card_key in keys.get(offer_id, ()):
                # Samme tilbud kan rendres pa to produktsider (samme fysiske
                # produkt, to interne id-er). Malet er property-scopet og
                # produktuavhengig, sa lenken gjelder begge steder.
                resolved[card_key] = url

    for reason, count in sorted(failures.items()):
        _warn(f"kunne ikke spørre Chillout: {reason}", f"{count} produkt(er)")

    # **En stille suksess er ikke til a skille fra et steg som aldri kjorte.**
    # Modulen sa ingenting nar alt gikk bra, sa byggeloggen sa likt ut enten
    # nokkelen virket eller koden ikke ble kalt i det hele tatt. Tallene og
    # flatenavnene, og ingenting annet: ingen token, ingen URL, ingen
    # legitimasjon. Flatene star her fordi en tilbakerulling ellers ikke kan
    # bekreftes uten a lese HTML -- linja er kvitteringen for at bryteren
    # faktisk ble lest.
    surfaces = enabled_surfaces()
    # Tallene, og ingenting annet: ingen token, ingen URL, ingen legitimasjon,
    # ingen annonsor. `svarte` er det som skiller "Chillout sa nei" fra "vi
    # fikk ikke spurt" -- uten det tallet ser en stille utelatelse ut som et
    # tilbud uten clickout.
    print(
        f"Chillout clickout: {len(resolved)} kort med bekreftet clickout"
        f", {answered}/{len(wanted)} produkter svarte"
        f", flater pa: {', '.join(sorted(surfaces)) or 'ingen'}"
    )
    return Clickouts(resolved, surfaces)
