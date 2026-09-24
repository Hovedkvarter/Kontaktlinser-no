"""Steg B: clickout-URL-en hentes fra Chillout i stedet for a sta hardkodet.

Det viktigste beviset ligger ikke her -- det er at hele det genererte
nettstedet er BYTE-IDENTISK med bootstrap-utgaven. Denne fila dekker det
andre: alt som kan ga galt, og at hvert enkelt av dem lar leverandor-URL-en
sta.

**Generatoren kan ikke lage en /go/-lenke.** Det finnes ingen formatstreng og
ingen token i render_offer_card lenger. Den har enten en streng Chillout har
returnert, eller ingenting. Derfor er "ingen /go/ noe sted" den riktige
pastanden i hver feilsituasjon, og ikke "riktig /go/".

Kjores direkte:  python test_chillout_clickout.py
"""

from __future__ import annotations

import json
import re
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import chillout_clickout
from site_generator.render_templates import (  # noqa: E402
    reconcile_product,
    render_offer_card,
)

ROOT = Path(__file__).parent
CATALOG = json.loads((ROOT / "site_generator" / "catalog_live.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

TOKEN = "/go/tgt_01M35ASH8Q3MH7WKCAMGGHVXFH"
PRODUCT = "biofinity-toric-6pk"
RETAILER = "Lensway"
KEY = "apk_" + "K" * 43

#: Et svar fra lesekontrakten, med tre annonsorer -- fordi det ER det
#: produksjon svarer. Bare ett par star i CONVERTED.
BODY = {
    "property_id": "kontaktlinser-no",
    "offers": [
        {"offer_id": "6884:1442", "advertiser": "Lensway",
         "link": {"clickout_available": True, "clickout_url": TOKEN}},
        {"offer_id": "9560:1442", "advertiser": "Shopping4net",
         "link": {"clickout_available": True, "clickout_url": "/go/tgt_SHOPPING4NETXXXXXXXXXXXXX"}},
    ],
    "excluded": [
        {"offer_id": "2510:77", "advertiser": "Extra Optical",
         "link": {"clickout_available": True, "clickout_url": "/go/tgt_EXTRAOPTICALXXXXXXXXXXXXX"}},
    ],
}


def product(product_id: str) -> dict:
    return next(p for p in CATALOG["products"] if p["id"] == product_id)


def card(product_id: str, retailer: str, clickouts) -> str:
    offers = reconcile_product(product(product_id)["offers"], NOW)
    o = next(x for x in offers if x["retailer"] == retailer)
    return render_offer_card(o, retailer, product(product_id)["name"], product_id, clickouts)


def href_of(html: str) -> str:
    return re.search(r'<a class="[^"]*" href="([^"]*)"', html).group(1)


class Recorder:
    """Captures what the module printed, so a warning can be asserted on."""

    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, *args):
        self.lines.append(" ".join(str(a) for a in args))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def annotations(self) -> list[str]:
        return [line for line in self.lines if line.startswith("::")]


def run(monkey, *, key=KEY, responder=None):
    """`clickout_urls()` with the network and the environment stubbed."""
    printed = Recorder()
    monkey["print"] = printed
    original_print = chillout_clickout.print if hasattr(chillout_clickout, "print") else None
    chillout_clickout.print = printed  # type: ignore[attr-defined]
    original_env = chillout_clickout.os.environ.get(chillout_clickout.KEY_VARIABLE)
    original_open = chillout_clickout.urllib.request.urlopen
    try:
        if key is None:
            chillout_clickout.os.environ.pop(chillout_clickout.KEY_VARIABLE, None)
        else:
            chillout_clickout.os.environ[chillout_clickout.KEY_VARIABLE] = key
        if responder is not None:
            chillout_clickout.urllib.request.urlopen = responder
        return chillout_clickout.clickout_urls(), printed
    finally:
        chillout_clickout.urllib.request.urlopen = original_open
        if original_print is None:
            del chillout_clickout.print  # type: ignore[attr-defined]
        else:
            chillout_clickout.print = original_print  # type: ignore[attr-defined]
        if original_env is None:
            chillout_clickout.os.environ.pop(chillout_clickout.KEY_VARIABLE, None)
        else:
            chillout_clickout.os.environ[chillout_clickout.KEY_VARIABLE] = original_env


def answering(body: dict):
    class Response:
        status = 200

        def read(self):
            return json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def responder(request, timeout=None):
        responder.seen = request
        responder.timeout = timeout
        return Response()

    return responder


def refusing(code: int):
    def responder(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "no", {}, None)

    return responder


def exploding(error: Exception):
    def responder(request, timeout=None):
        raise error

    return responder


# ------------------------------------------------------------ the happy path
def test_the_one_pair_is_resolved() -> None:
    found, _ = run({}, responder=answering(BODY))

    assert found == {(PRODUCT, RETAILER): TOKEN}


def test_the_card_carries_what_chillout_returned() -> None:
    found, _ = run({}, responder=answering(BODY))

    assert href_of(card(PRODUCT, RETAILER, found)) == TOKEN


def test_the_contract_offering_more_does_not_widen_coverage() -> None:
    """**Dekningen ligger i koden, ikke i intensjonen.** Kontrakten tilbyr
    tre clickouts -- det gjor den i produksjon ogsa -- og bare ett par er i
    CONVERTED."""
    found, _ = run({}, responder=answering(BODY))

    assert list(found) == [(PRODUCT, RETAILER)]
    for other in ("Shopping4net", "Extra Optical"):
        assert "/go/" not in card(PRODUCT, other, found)


def test_an_excluded_offer_is_still_read() -> None:
    """Et ekskludert tilbud er tatt ut av sorteringen, ikke gjort uneabart.
    Extra Optical ligger i `excluded` i BODY og blir lest -- den filtreres
    bort av CONVERTED, ikke av hvilken liste den stod i."""
    body = {"offers": [], "excluded": BODY["offers"] + BODY["excluded"]}
    found, _ = run({}, responder=answering(body))

    assert found == {(PRODUCT, RETAILER): TOKEN}


# ---------------------------------------------------------- every failure mode
def _falls_back(found, printed, *, category: str) -> None:
    assert found == {}
    assert href_of(card(PRODUCT, RETAILER, found)).startswith("https://")
    assert "/go/" not in card(PRODUCT, RETAILER, found)
    assert category in printed.text, printed.text
    assert printed.annotations, "en tilbakefallsgrunn skal være synlig"
    assert all(a.startswith("::warning::") for a in printed.annotations), printed.annotations


def test_authentication_rejected() -> None:
    found, printed = run({}, responder=refusing(401))
    _falls_back(found, printed, category="401")


def test_the_key_belongs_to_another_property() -> None:
    """403 og 401 holdes fra hverandre: den ene betyr rotér nokkelen, den
    andre betyr at nokkelen gjelder en annen Property."""
    found, printed = run({}, responder=refusing(403))
    _falls_back(found, printed, category="403")
    assert "401" not in printed.text


def test_chillout_unavailable() -> None:
    found, printed = run({}, responder=refusing(503))
    _falls_back(found, printed, category="503")


def test_the_request_never_completes() -> None:
    found, printed = run({}, responder=exploding(TimeoutError("timed out")))
    _falls_back(found, printed, category="TimeoutError")


def test_an_unexpected_status() -> None:
    found, printed = run({}, responder=refusing(418))
    _falls_back(found, printed, category="418")


def test_no_confirmed_clickout() -> None:
    body = {"offers": [{"offer_id": "6884:1442", "advertiser": "Lensway",
                        "link": {"clickout_available": False, "clickout_url": None}}],
            "excluded": []}
    found, printed = run({}, responder=answering(body))
    _falls_back(found, printed, category="ingen bekreftet clickout")


def test_a_url_without_the_flag_is_not_taken() -> None:
    """**Flagget leses, ikke bare URL-en.**

    En mutasjon som droppet `clickout_available` og bare sa etter
    `clickout_url` overlevde alt annet, fordi den ene testen som sa ut som om
    den dekket dette satte BEGGE feltene falske -- da er de enige og
    ingenting skiller dem.

    Chillout kan ikke sende dem i utakt: der er `clickout_available` utledet
    av URL-en, og det er testet. Men siden her forbruker en kontrakt over
    HTTP som den ikke eier, og da leser man det dokumenterte flagget framfor
    a gjette fra et felt ved siden av.
    """
    body = {"offers": [{"offer_id": "6884:1442", "advertiser": "Lensway",
                        "link": {"clickout_available": False, "clickout_url": TOKEN}}],
            "excluded": []}
    found, printed = run({}, responder=answering(body))
    _falls_back(found, printed, category="ingen bekreftet clickout")


def test_the_advertiser_name_is_no_longer_part_of_the_decision() -> None:
    """**Visningsnavnet avgjor ingenting lenger.**

    For matchet vi pa `advertiser`, og et navn stavet annerledes pa den ene
    siden ga ingen lenke. Na er sammenkoblingen offer_id, sa det samme
    tilbudet lases opp uansett hva annonsoren kalles -- eller om feltet
    mangler helt.
    """
    for advertiser in ("LensWay AB", "lensway", "", None):
        body = {"offers": [{"offer_id": "6884:1442", "advertiser": advertiser,
                            "link": {"clickout_available": True, "clickout_url": TOKEN}}],
                "excluded": []}
        found, _ = run({}, responder=answering(body))

        assert found == {(PRODUCT, RETAILER): TOKEN}, advertiser


def test_the_right_name_on_the_wrong_offer_is_refused() -> None:
    """Den andre retningen, og den som betyr noe: riktig annonsornavn kan
    ikke lenger slippe gjennom et tilbud vi ikke har godkjent."""
    body = {"offers": [{"offer_id": "6884:9999", "advertiser": "Lensway",
                        "link": {"clickout_available": True, "clickout_url": TOKEN}}],
            "excluded": []}
    found, printed = run({}, responder=answering(body))
    _falls_back(found, printed, category="ingen bekreftet clickout")


def test_another_feeds_offer_with_the_same_sku_is_refused() -> None:
    """**Hvorfor feed-id-en ma være med.** Lenson har fid 9560 og selger
    samme produkt; SKU 1442 alene ville vært tvetydig mellom de to feedene.
    Chillouts nokkel er feed PLUSS external_id nettopp derfor."""
    body = {"offers": [{"offer_id": "9560:1442", "advertiser": "Lenson",
                        "link": {"clickout_available": True, "clickout_url": TOKEN}}],
            "excluded": []}
    found, printed = run({}, responder=answering(body))
    _falls_back(found, printed, category="ingen bekreftet clickout")


def test_a_known_offer_outside_the_allowlist_is_refused() -> None:
    """**Dekningen, ikke bare oppslaget.**

    `6884:16` er et EKTE Lensway-tilbud: feed-id-en er var, SKU-en star i
    tabellen, og oppslaget finner et kort a legge lenken pa. Det eneste som
    holder den tilbake er CONVERTED. En mutasjon som droppet den sjekken
    overlevde alt annet, fordi de andre tilbudene i stubben tilhorer feeder
    uten chillout_feed_id og derfor aldri nadde oppslaget i det hele tatt.
    """
    other = "6884:16"  # biomedics-55-evolution-6pk
    body = {"offers": [
        {"offer_id": other, "advertiser": "Lensway",
         "link": {"clickout_available": True, "clickout_url": "/go/tgt_ANNETXXXXXXXXXXXXXXXXXXXXX"}},
    ], "excluded": []}
    found, printed = run({}, responder=answering(body))

    assert other not in str(found)
    assert found == {}
    assert "/go/" not in card("biomedics-55-evolution-6pk", RETAILER, found)
    _falls_back(found, printed, category="ingen bekreftet clickout")


def test_only_configured_feeds_contribute_lookup_keys() -> None:
    """En kilde uten chillout_feed_id skal ikke bidra med nokler i det hele
    tatt. Uten dette ville en kilde uten feed-id gitt nokler som `None:1442`
    -- ufarlige, men stille, og de skjuler at oppsettet mangler noe."""
    import json

    keys = chillout_clickout._renderer_keys()
    sources = json.loads((ROOT / "sources_config.json").read_text(encoding="utf-8"))
    configured = {
        c["chillout_feed_id"] for c in sources.values()
        if isinstance(c, dict) and c.get("chillout_feed_id")
    }

    assert configured, "minst en kilde skal ha en feed-id"
    assert keys, "oppslaget skal ikke være tomt"
    for key in keys:
        assert key.split(":")[0] in configured, key


def test_the_feed_id_is_a_field_and_not_a_comment() -> None:
    """Verdien stod allerede i repoet -- i en fritekstkommentar, der kode
    ikke kan lese den. Dette er hele endringen pa oppsettsiden."""
    import json

    sources = json.loads((ROOT / "sources_config.json").read_text(encoding="utf-8"))

    assert sources["lensway"]["chillout_feed_id"] == "6884"
    assert sources["lensway"]["network"] == "tradedoubler_lensway"
    # Og forhandlernavnet pa et tilbud ER display_name (ingest_feed.py), sa
    # oppslagsnokkelen er sidens egen, ikke en avtale med Chillout.
    assert sources["lensway"]["display_name"] == RETAILER


def test_the_sku_mapping_inverts_uniquely() -> None:
    """Sjekken som ble kjort for denne endringen, na fast.

    Kartet gar SKU -> produkt. Skulle to SKU-er peke pa samme produkt, ville
    det ikke lenger være entydig hvilket tilbud et kort svarer til."""
    import collections
    import json

    table = json.loads((ROOT / "product_matching.json").read_text(encoding="utf-8"))
    skus = {k: v for k, v in table["tradedoubler_lensway"].items() if not k.startswith("$")}
    by_product = collections.Counter(skus.values())

    assert [p for p, n in by_product.items() if n > 1] == []
    assert [s for s, p in skus.items() if p == PRODUCT] == ["1442"]


def test_a_missing_key_in_ci_is_a_warning() -> None:
    """**I CI er en manglende nokkel en feil, ikke normalen.**

    En secret er ikke automatisk tilgjengelig for et steg -- den ma navngis i
    en env-blokk -- og det er lett a glemme. Uten dette skillet ville et bygg
    uten nokkel sett akkurat ut som et lokalt bygg, og det konverterte kortet
    ville stille falt tilbake til leverandor-URL-en.
    """
    import os

    was = os.environ.get("GITHUB_ACTIONS")
    os.environ["GITHUB_ACTIONS"] = "true"
    try:
        found, printed = run({}, key=None, responder=answering(BODY))
    finally:
        if was is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = was

    assert found == {}
    assert printed.annotations, "en manglende nokkel i CI skal være synlig"
    assert all(a.startswith("::warning::") for a in printed.annotations)
    assert "ikke tilgjengelig" in printed.text


def test_the_build_workflow_hands_the_key_to_the_generator() -> None:
    """Koden kan ikke lese en secret som steget ikke har fatt.

    Dette er den ene pastanden som ikke kan bevises fra Python alene: den
    ligger i workflow-fila, og uten den er hele Steg B en stille no-op.
    """
    workflow = (ROOT / ".github" / "workflows" / "build-and-deploy.yml").read_text(
        encoding="utf-8"
    )
    step = workflow[workflow.index("Generer statiske sider"):]
    step = step[: step.index("      - name:", 1)]

    assert "CHILLOUT_READ_KEY: ${{ secrets.CHILLOUT_READ_KEY }}" in step
    assert "generate_pages.py" in step


def test_no_key_configured_is_quiet() -> None:
    """Et lokalt bygg har ingen secret og skal ikke se ut som om noe er galt.
    Annotasjonen er reservert for det som ER galt."""
    # urlopen stubbes ogsa her: testen er trygg i dag bare fordi vakten
    # returnerer forst, og skulle den regrere ville suiten sendt en ekte
    # forespørsel til produksjonsoriginet.
    found, printed = run({}, key=None, responder=answering(BODY))

    assert found == {}
    assert "ikke satt" in printed.text
    assert printed.annotations == [], "et lokalt bygg skal ikke annotere"
    assert "/go/" not in card(PRODUCT, RETAILER, found)


def test_an_empty_key_is_the_same_as_none() -> None:
    found, printed = run({}, key="   ", responder=answering(BODY))

    assert found == {}
    assert printed.annotations == []


# --------------------------------------------- the shape of the answer is not trusted
MALFORMED = [
    ("a JSON list", []),
    ("a list of offers", [{"advertiser": "Lensway"}]),
    ("a string", "ok"),
    ("a number", 0),
    ("a boolean", True),
    ("null offers", {"offers": None, "excluded": []}),
    ("null excluded", {"offers": [], "excluded": None}),
    ("offers is a string", {"offers": "x", "excluded": []}),
    ("offers is an object", {"offers": {"a": 1}, "excluded": []}),
    ("an offer is not an object", {"offers": ["x", None], "excluded": []}),
    ("link is a string", {"offers": [{"advertiser": "Lensway", "link": "x"}], "excluded": []}),
    ("link is missing", {"offers": [{"advertiser": "Lensway"}], "excluded": []}),
    ("advertiser is an object", {"offers": [
        {"advertiser": {"navn": "Lensway"},
         "link": {"clickout_available": True, "clickout_url": TOKEN}}], "excluded": []}),
    ("the url is a number", {"offers": [
        {"advertiser": "Lensway",
         "link": {"clickout_available": True, "clickout_url": 12}}], "excluded": []}),
    ("an empty object", {}),
]


def test_no_malformed_answer_can_break_the_build() -> None:
    """**Den viktigste av dem alle.**

    Forste utgave stolte pa formen og kastet AttributeError pa en 200 med en
    JSON-liste, og TypeError pa {"offers": null} -- ut av build(), sa bygget
    dode med null sider skrevet og siden ble staende med gardagens priser.
    Det er verre enn a ikke ha noen lenke, og det er nøyaktig utfallet
    modulen finnes for a unnga.

    Chillout kan ikke sende disse formene i dag. En mellomliggende proxy
    eller en framtidig kontraktsendring kan, og "neppe" er ikke en garanti
    pa denne siden av HTTP.
    """
    for name, body in MALFORMED:
        try:
            found, printed = run({}, responder=answering(body))
        except Exception as error:
            raise AssertionError(f"{name} kastet {type(error).__name__}") from None

        assert found == {}, name
        html = card(PRODUCT, RETAILER, found)
        assert "/go/" not in html, name
        assert href_of(html).startswith("https://"), name
        assert KEY not in printed.text, name


def test_a_malformed_answer_still_renders_the_whole_page() -> None:
    """Kartet er ikke det eneste stedet en rar verdi kunne stoppet bygget --
    en URL som ikke er en streng ville drept `escape()` i selve rendringen."""
    from site_generator.render_templates import render_product_page

    body = {"offers": [{"advertiser": "Lensway",
                        "link": {"clickout_available": True, "clickout_url": 12}}],
            "excluded": []}
    found, _ = run({}, responder=answering(body))
    offers = reconcile_product(product(PRODUCT)["offers"], NOW)

    html = render_product_page(
        {**product(PRODUCT), "offers": offers}, CATALOG["categories"],
        {p["id"]: p for p in CATALOG["products"]}, [], NOW, [], None, found,
    )

    assert "/go/" not in html


def test_a_successful_run_says_so_with_numbers_only() -> None:
    """En stille suksess er ikke til a skille fra et steg som aldri kjorte.

    Linja er tall og ingenting annet: ingen token, ingen URL, ingen
    legitimasjon, og ingen annonsor- eller produktnavn -- den skal kunne leses
    av hvem som helst som apner en byggelogg.
    """
    found, printed = run({}, responder=answering(BODY))

    assert "Chillout clickout: 1/1 godkjente tilbud lost" in printed.text
    assert printed.annotations == [], "en vellykket kjoring skal ikke annotere"
    assert KEY not in printed.text
    assert chillout_clickout.ORIGIN not in printed.text
    assert TOKEN not in printed.text
    assert found


def test_the_count_tells_the_truth_when_nothing_resolves() -> None:
    """0/1 og 1/1 ma kunne skilles, ellers er tallet dekorasjon."""
    _, printed = run({}, responder=refusing(503))

    assert "Chillout clickout: 0/1 godkjente tilbud lost" in printed.text


# ------------------------------------------------------- the request it sends
def test_it_asks_the_right_property_product_and_origin() -> None:
    """Uten dette kunne PROPERTY, PRODUCTS eller ruta endres til noe galt og
    hele suiten forble gronn -- mens produksjon falt stille tilbake."""
    responder = answering(BODY)
    run({}, responder=responder)

    url = responder.seen.full_url

    assert url.startswith(chillout_clickout.ORIGIN + "/")
    assert "/properties/kontaktlinser-no/" in url
    assert "/products/prd_01M2ZP0SREXS63NNMW6YBKRZ9S/offers" in url


def test_the_request_carries_a_timeout() -> None:
    """Et Chillout som henger ville ellers hengt bygget til jobbens egen
    20-minutters grense, og da feiler deployet."""
    responder = answering(BODY)
    run({}, responder=responder)

    assert responder.timeout == chillout_clickout.TIMEOUT
    assert 0 < chillout_clickout.TIMEOUT <= 60


def test_the_fetched_url_is_escaped_into_the_attribute() -> None:
    """Den hentede URL-en er den ENESTE fjernstyrte strengen som havner
    inne i et HTML-attributt. Den skal gjennom escape() som alt annet."""
    hostile = '/go/x" onmouseover="evil()'
    body = {"offers": [{"offer_id": "6884:1442", "advertiser": "Lensway",
                        "link": {"clickout_available": True, "clickout_url": hostile}}],
            "excluded": []}
    found, _ = run({}, responder=answering(body))

    html = card(PRODUCT, RETAILER, found)

    assert 'onmouseover="evil()"' not in html
    assert "&quot;" in html


def test_an_ampersand_in_a_provider_url_is_escaped() -> None:
    """110 av katalogens leverandor-URL-er inneholder `&`. En fjernet
    escape() ville sendt ra `&` ut i attributtet pa hver eneste en."""
    with_ampersand = next(
        (p["id"], o["retailer"])
        for p in CATALOG["products"]
        for o in reconcile_product(p.get("offers", []), NOW)
        if "&" in o["url"]
    )
    html = card(*with_ampersand, {})

    assert "&amp;" in html


# ------------------------------------------------------------- the credential
def test_the_key_reaches_the_header_and_nothing_else() -> None:
    responder = answering(BODY)
    found, printed = run({}, responder=responder)

    assert responder.seen.get_header("Authorization") == f"Bearer {KEY}"
    assert KEY not in printed.text
    assert found  # the control: the call really happened


def test_no_failure_path_prints_the_key() -> None:
    for responder in (refusing(401), refusing(403), refusing(503),
                      exploding(ConnectionResetError("reset"))):
        _, printed = run({}, responder=responder)

        assert KEY not in printed.text
        assert KEY[4:24] not in printed.text
        assert "Bearer" not in printed.text
        assert "authorization" not in printed.text.lower()


def test_a_network_error_reports_its_type_and_not_its_message() -> None:
    """Et unntak kan bære forespørselen, og forespørselen bærer headeren."""
    _, printed = run({}, responder=exploding(OSError(f"failed sending Bearer {KEY}")))

    assert "OSError" in printed.text
    assert KEY not in printed.text
    assert "failed sending" not in printed.text


# ------------------------------------------------------- nothing else renders
def test_the_whole_catalogue_has_exactly_one_converted_card() -> None:
    found, _ = run({}, responder=answering(BODY))
    converted = []
    for p in CATALOG["products"]:
        for o in reconcile_product(p.get("offers", []), NOW):
            html = render_offer_card(o, o["retailer"], p["name"], p["id"], found)
            if "/go/" in html:
                converted.append((p["id"], o["retailer"]))

    assert converted == [(PRODUCT, RETAILER)]


def test_only_the_href_differs_on_the_converted_card() -> None:
    found, _ = run({}, responder=answering(BODY))
    offers = reconcile_product(product(PRODUCT)["offers"], NOW)
    o = next(x for x in offers if x["retailer"] == RETAILER)

    plain = render_offer_card(o, RETAILER, product(PRODUCT)["name"], PRODUCT, {})
    converted = render_offer_card(o, RETAILER, product(PRODUCT)["name"], PRODUCT, found)

    assert plain != converted
    assert converted.replace(TOKEN, o["url"], 1) == plain


def test_the_winner_band_is_untouched() -> None:
    import inspect

    from site_generator import render_templates

    source = inspect.getsource(render_templates)
    band = source[source.index('winner_band = f"""<a class="winner-band"'):][:400]

    assert "/go/" not in band
    assert 'href="{escape(best["url"])}"' in band


def test_the_generator_cannot_build_a_go_link() -> None:
    """Bootstrap-en hadde ett token i kildekoden. Na finnes det ingen -- og
    heller ingen KODE som kan sette sammen en /go/-sti.

    `/go/` skal fortsatt kunne nevnes i en kommentar: det er der forklaringen
    hører hjemme. Pastanden er om kode, sa kommentarlinjer trekkes fra for
    det telles. En gjeninnfort `href = "/go/" + token` ville vært kode og
    ville falt her.
    """
    source = (ROOT / "site_generator" / "render_templates.py").read_text(encoding="utf-8")
    code = [
        line for line in source.splitlines()
        if not line.lstrip().startswith("#")
    ]

    assert "tgt_" not in source, "et token er tilbake i kildekoden"
    offenders = [line.strip() for line in code if "/go/" in line]
    assert offenders == [], offenders


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    print(f"\n{len(tests)} kontroller\n")
    for fn in tests:
        try:
            fn()
            print(f"  [OK]   {fn.__name__}")
        except AssertionError as error:
            failed += 1
            print(f"  [FEIL] {fn.__name__}: {error}")
    print("\n" + ("alle bestatt" if not failed else f"{failed} feilet"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
