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

#: Ett par. Dekningen for forste Step B-deploy, uendret fra bootstrap-en.
CONVERTED = {("biofinity-toric-6pk", "Lensway")}

#: Hvilket produkt bygget spor om. En offentlig identifikator, ikke en
#: kapabilitet -- i motsetning til tokenet den erstatter.
PRODUCTS = {"biofinity-toric-6pk": "prd_01M2ZP0SREXS63NNMW6YBKRZ9S"}

PROPERTY = "kontaktlinser-no"
ORIGIN = os.environ.get("CHILLOUT_ORIGIN", "https://backoffice-test-d71d.up.railway.app")
KEY_VARIABLE = "CHILLOUT_READ_KEY"
TIMEOUT = 20


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
    """Annonsor til clickout-URL, for de tilbudene som faktisk har en.

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
            advertiser = offer.get("advertiser")
            url = link.get("clickout_url") if isinstance(link, dict) else None
            if (
                isinstance(link, dict)
                and link.get("clickout_available")
                and isinstance(url, str)
                and isinstance(advertiser, str)
            ):
                found[advertiser] = url
    return found


def clickout_urls() -> dict[tuple[str, str], str]:
    """(produkt-id, forhandler) -> /go/-sti, for det som er bekreftet.

    Tom dict er et gyldig og trygt svar: hvert kort faller da tilbake til sin
    egen leverandor-URL, som er det siden rendret for bootstrap-en.
    """
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

    resolved: dict[tuple[str, str], str] = {}
    for product_id, platform_id in PRODUCTS.items():
        body, reason = _fetch(product_id, platform_id, key)
        if body is None:
            _warn(reason, product_id)
            continue
        offered = _clickouts_in(body)
        for advertiser, url in offered.items():
            if (product_id, advertiser) in CONVERTED:
                resolved[(product_id, advertiser)] = url
        for wanted_product, advertiser in CONVERTED:
            if wanted_product == product_id and (product_id, advertiser) not in resolved:
                # Kontrakten svarte, men uten en clickout for akkurat dette
                # paret: enten ingen servable target, eller et annonsornavn
                # som ikke matcher. Begge er trygge og begge er verdt a si.
                # `offered` holder annonsorene kontrakten faktisk ga en
                # clickout for. Er var annonsor ikke blant dem, men andre er
                # det, sa stavet de to sidene navnet ulikt.
                _warn(
                    "annonsornavnet matchet ikke" if offered else "ingen bekreftet clickout",
                    f"{wanted_product}/{advertiser}",
                )
    return resolved
