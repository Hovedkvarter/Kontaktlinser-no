"""Chillout-clickouts hentet fra lesekontrakten pa byggetidspunktet.

Erstatter det hardkodede bootstrap-tokenet. Forskjellen er ikke at regelen er
losere -- den er strammere: **generatoren kan ikke lenger lage en /go/-lenke.**
Det finnes ingen formatstreng, ingen prefiks og ingen token her. Den har enten
en streng Chillout har returnert, eller ingenting.

## Hva den ber om

Ett kall, for ETT produkt, mot den interne produktruta. Ikke katalogruta:
den krever at products_meta-aliaset finnes, og et manglende alias svarer 404,
som ikke kan skilles fra en odelagt nokkel. Verdt a revurdere nar dekningen
utvides; ikke verdt tvetydigheten for ett produkt.

## Hva den slipper gjennom

CONVERTED er en tillatelsesliste pa ett par. Den anvendes ETTER svaret, sa
selv om kontrakten tilbyr clickouts for Shopping4net og Extra Optical -- og
det gjor den -- rendres bare det ene kortet. Det er det som holder dekningen
pa ett kort i KODE og ikke i intensjon. A utvide er a slette en linje herfra,
og det er en handling noen kan se i en diff.

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

#: **Dekningen, som Chillouts egne tilbudsnokler.** Ett tilbud.
#:
#: `feed:external_id` er ADR-031s stabile nokkel: den bestar bare av felter
#: en prisendring ikke kan endre. Den erstatter matching pa annonsorens
#: VISNINGSNAVN, som var det eneste felles feltet for -- og som ingen av
#: sidene lovet a fortsette a stave likt.
CONVERTED = {
    "6884:1442",  # Biofinity Toric 6-pack -- det forste, verifisert i nettleser
    "6884:347",   # Biofinity 6-pack -- samme feed, annet produkt
}

#: Repoets rot. Modulen ligger i site_generator/, oppsettfilene et niva over.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Sidens produkt-id til Chillouts plattform-id. **Et oppslag, ikke en
#: forespørselsliste.** Hvilke produkter bygget faktisk spor om utledes fra
#: CONVERTED lenger nede.
#:
#: Det var to lister som matte stemme overens, og ingenting som sorget for
#: det: 6884:347 ble lagt til dekningen uten at produktet ble lagt til her,
#: sa kontrakten ble aldri spurt om biofinity-6pk -- og advarselen sa "ingen
#: bekreftet clickout", som er noe helt annet enn "vi spurte ikke". Den
#: meldingen sendte en produksjonsundersøkelse gjennom hele serveringskjeden
#: der ingenting var galt.
#:
#: Offentlige identifikatorer, ikke kapabiliteter.
PRODUCTS = {
    "biofinity-toric-6pk": "prd_01M2ZP0SREXS63NNMW6YBKRZ9S",
    "biofinity-6pk": "prd_01M2ZP0SREARN6N3NETCB2DZYP",
}

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

    keys: dict[str, tuple[str, str]] = {}
    for config in sources.values():
        if not isinstance(config, dict):
            continue
        feed_id = config.get("chillout_feed_id")
        table = matching.get(config.get("network") or "")
        retailer = config.get("display_name")
        if not (feed_id and isinstance(table, dict) and retailer):
            continue
        for sku, product_id in table.items():
            if not sku.startswith("$"):
                keys[f"{feed_id}:{sku}"] = (product_id, retailer)
    return keys


def _warn(category: str, detail: str) -> None:
    """En synlig, kategorisert linje -- og ingenting mer enn det.

    `detail` settes bare av kallstedene under, aldri av et unntak: en
    unntaksmelding kan inneholde forespørselen.
    """
    message = f"Chillout-clickout: {category} -- lenker falt tilbake til leverandor-URL ({detail})"
    print(message)
    print(f"::warning::{message}")


def _fetch(product_id: str, platform_id: str, key: str) -> tuple[dict | None, str]:
    """Ett produkts sammenligning, eller en navngitt grunn til at den mangler."""
    url = f"{ORIGIN}/api/v1/properties/{PROPERTY}/products/{platform_id}/offers"
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


def clickout_urls() -> dict[tuple[str, str], str]:
    """(produkt-id, forhandler) -> /go/-sti, for det som er bekreftet.

    Tom dict er et gyldig og trygt svar: hvert kort faller da tilbake til sin
    egen leverandor-URL, som er det siden rendret for bootstrap-en.
    """
    if not ORIGIN:
        # Samme trygge utgang som alt annet her, og samme skille: lokalt er
        # dette normalen, i CI betyr det at variabelen ikke er satt.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            _warn("CHILLOUT_ORIGIN er ikke satt for dette steget", "intet origin")
        else:
            print("Chillout-clickout: CHILLOUT_ORIGIN er ikke satt -- bruker leverandor-URL-er")
        return {}

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
        return {}

    keys = _renderer_keys()
    resolved: dict[tuple[str, str], str] = {}

    # **Hvilke produkter som spørres om, utledes av dekningen.** To lister som
    # ma stemme overens er en list for mye; her finnes bare en.
    wanted: dict[str, str] = {}
    for offer_id in sorted(CONVERTED):
        if offer_id not in keys:
            # Godkjent, men ukjent i katalogoppslaget: enten en feed uten
            # chillout_feed_id, eller en SKU som ikke star i tabellen.
            _warn("godkjent tilbud finnes ikke i katalogoppslaget", offer_id)
            continue
        product_id = keys[offer_id][0]
        platform_id = PRODUCTS.get(product_id)
        if not platform_id:
            # **Den advarselen som manglet.** "Vi spurte ikke" er noe helt
            # annet enn "vi spurte og fikk ingen clickout", og a si det forste
            # som det andre sender folk gjennom serveringskjeden forgjeves.
            _warn("produktet blir ikke spurt om (mangler plattform-id)",
                  f"{offer_id} -> {product_id}")
            continue
        wanted[product_id] = platform_id

    for product_id, platform_id in sorted(wanted.items()):
        body, reason = _fetch(product_id, platform_id, key)
        if body is None:
            _warn(reason, product_id)
            continue
        offered = _clickouts_in(body)
        for offer_id, url in offered.items():
            # **Sammenkoblingen er offer_id, og ingenting annet.** Ingen
            # annonsor, intet visningsnavn, ingen normalisering av tekst.
            if offer_id in CONVERTED and offer_id in keys:
                resolved[keys[offer_id]] = url
        for offer_id in sorted(CONVERTED):
            # Bare tilbudene som hører til DETTE produktet. Uten den
            # avgrensningen ville hvert produkt advart om de andres tilbud.
            if (
                offer_id in keys
                and keys[offer_id][0] == product_id
                and keys[offer_id] not in resolved
            ):
                _warn("ingen bekreftet clickout", offer_id)

    # **En stille suksess er ikke til a skille fra et steg som aldri kjorte.**
    # Modulen sa ingenting nar alt gikk bra, sa byggeloggen sa likt ut enten
    # nokkelen virket eller koden ikke ble kalt i det hele tatt. Tallene, og
    # ingenting annet: ingen token, ingen URL, ingen legitimasjon.
    print(f"Chillout clickout: {len(resolved)}/{len(CONVERTED)} godkjente tilbud lost")
    return resolved
