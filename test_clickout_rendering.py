"""Regresjonsbevis for de konverterte /go/-lenkene.

**Oppdatert for Steg 1 (flatekonsistens).** Filen het en gang "det ene
konverterte kortet", og det stemmer ikke lenger: fire godkjente tilbud
rendres na pa tre flater -- vanlig tilbudskort, vinnerband og
antallskalkulatorens JSON -- pa alle sidene tilbudet forekommer, inkludert
de atte private-label-sidene som gjenbruker et konvertert produkts tilbud.
Dekningen er uendret; antallet steder som bruker den er det som vokste.

JSON-LD er med vilje ikke med. Det er ikke en klikkflate, og en
forstepartsredirect i `offers.url` er en annen avgjorelse.

Tokenet star null steder i kildekoden -- det kommer fra Chillouts
lesekontrakt pa byggetidspunktet. Feilsituasjonene ligger i
test_chillout_clickout.py.

Opprinnelig docstring:

ETT kort, pa ETT produkt, hos EN forhandler. Denne filen finnes for a bevise
nettopp det -- at endringen traff det den skulle og ingenting annet -- og for
at et senere, bredere oppsett ikke skal kunne skje ved et uhell.

Kjores direkte:  python test_clickout_bootstrap.py
Eller med pytest hvis den er tilgjengelig.

Bevisene rendres fra site_generator/catalog_live.json, altsa ekte katalogdata
og ekte leverandor-URL-er, ikke oppdiktede fixtures. Et bevis bygget pa en
fixture ville bare bevist at fixturen var riktig.

Den avsluttende linja i den opprinnelige docstringen sa at tokenet var
hardkodet og bevisst midlertidig. Det var sant da og er det ikke lenger --
Steg B fjernet konstanten. Den star her strokent framfor slettet, slik at
endringen er synlig.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from site_generator.render_templates import render_offer_card

ROOT = Path(__file__).parent
CATALOG = json.loads((ROOT / "site_generator" / "catalog_live.json").read_text(encoding="utf-8"))

#: Det ene malet. Verifisert ende-til-ende mot produksjonskanten 2026-09-23.
GO = "/go/tgt_01M35ASH8Q3MH7WKCAMGGHVXFH"

#: Det kontrakten ville returnert for dette ene paret. Testene under gir det
#: inn direkte, slik generatoren gjor etter a ha spurt.
CLICKOUTS = {("biofinity-toric-6pk", "Lensway"): GO}

from datetime import datetime, timezone

#: Frossen klokke. reconcile_product avgjor ferskhet mot den, og en
#: test som leser veggklokka beviser noe litt annet hver gang.
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

TARGET_PRODUCT = "biofinity-toric-6pk"
TARGET_RETAILER = "Lensway"


def product(product_id: str) -> dict:
    return next(p for p in CATALOG["products"] if p["id"] == product_id)


def offer(product_id: str, retailer: str) -> dict:
    """Ett ekte tilbud, slik generatoren ser det etter reconcile_product().

    Kaller reconcile_product fordi det er DER o["url"] settes -- UTM-tagger
    for skrapede tilbud, uroert feed-URL for affiliate-tilbud. A hoppe over
    den ville testet en URL ingen side faktisk rendrer.
    """
    from datetime import datetime, timezone

    from site_generator.render_templates import reconcile_product

    offers = reconcile_product(product(product_id)["offers"], datetime.now(timezone.utc))
    for o in offers:
        if o["retailer"] == retailer:
            return o
    # reconcile_product KAN fjerne et tilbud -- Lensit nar Lensit er
    # billigst -- sa "finnes ikke" er et ekte svar og ikke en StopIteration
    # midt i en generator.
    raise LookupError(
        f"{retailer} rendres ikke pa {product_id}; rekonsilierte: "
        f"{[x['retailer'] for x in offers]}"
    )


def card(product_id: str, retailer: str) -> str:
    o = offer(product_id, retailer)
    return render_offer_card(
        o, o["retailer"], product(product_id)["name"], product_id, CLICKOUTS
    )


def calculator_offers(html: str) -> dict:
    """Retailer -> URL fra antallskalkulatorens innebygde JSON.

    JSON-en escaper `</` som `<\\/` sa den ikke kan lukke script-taggen, og
    det ma reverseres for json.loads ser den."""
    found = re.search(
        r'<script type="application/json" id="qty-offers-data"[^>]*>(.*?)</script>',
        html, re.S,
    )
    assert found, "fant ikke kalkulatorens JSON"
    return {o["retailer"]: o["url"] for o in json.loads(found.group(1).replace("<\\/", "</"))}


def href_of(html: str) -> str:
    return re.search(r'<a class="[^"]*" href="([^"]*)"', html).group(1)


def band_href_of(html: str) -> str:
    """Banneret har `id` mellom class og href, sa href_of bommer pa det --
    og bommer ved a returnere None, ikke ved a si fra."""
    found = re.search(r'<a class="winner-band"[^>]*? href="([^"]*)"', html)
    assert found, "fant ikke vinnerbanneret"
    return found.group(1)


def attr(html: str, name: str) -> str | None:
    found = re.search(rf'{name}="([^"]*)"', html)
    return found.group(1) if found else None


# --------------------------------------------------------------- the one card
def test_the_intended_card_is_converted() -> None:
    html = card(TARGET_PRODUCT, TARGET_RETAILER)

    assert href_of(html) == GO, href_of(html)


def test_no_provider_url_remains_on_the_converted_card() -> None:
    """Hele kortet, ikke bare href: en tracking-URL kunne ellers overleve i
    aria-label, i et bilde eller i et dataattributt."""
    html = card(TARGET_PRODUCT, TARGET_RETAILER)

    for fragment in ("pdt.tradedoubler.com", "tradedoubler", "a(3494407)", "ttid("):
        assert fragment not in html, fragment


# ------------------------------------------------------------ and nothing else
def test_another_lensway_product_keeps_its_provider_url() -> None:
    """Samme forhandler, annet produkt. Dette er halvparten av gjerdet:
    uten det ville en regel som bare sa "Lensway" bestatt."""
    other = next(
        p["id"]
        for p in CATALOG["products"]
        if p["id"] != TARGET_PRODUCT
        and any(o["retailer"] == TARGET_RETAILER for o in p.get("offers", []))
    )
    html = card(other, TARGET_RETAILER)

    assert href_of(html) != GO
    assert "/go/" not in html
    assert href_of(html).startswith("https://")
    print(f"      kontroll: {other} / {TARGET_RETAILER} -> uendret")


def test_another_retailer_on_the_same_product_keeps_its_url() -> None:
    """Samme produkt, annen forhandler. Den andre halvparten: uten det ville
    en regel som bare sa "biofinity-toric-6pk" bestatt.

    Lenson ligger pa SAMME nettverk og SAMME SKU 1442 -- product_matching.json
    mapper 1442 til dette produktet i bade tradedoubler_lenson og
    tradedoubler_lensway. Det gjor dette til den strengeste kontrollen som
    finnes i katalogen.
    """
    html = card(TARGET_PRODUCT, "Lenson")

    assert href_of(html) != GO
    assert "/go/" not in html
    assert "pdt.tradedoubler.com" in html


def test_every_other_card_in_the_catalogue_is_untouched() -> None:
    """Hele katalogen, ett kort om gangen. Teller treffene og krever
    noyaktig ett -- en regel som lekket til to produkter ville ellers sett
    ut som suksess i testene over.

    Gar gjennom de REKONSILIERTE tilbudene, ikke de ra, fordi det er de
    rekonsilierte som faktisk rendres. Forskjellen er ikke akademisk:
    reconcile_product fjerner Lensit helt nar Lensit er billigst (ingen
    avtale, skal ikke vinne), sa en sveip over ra tilbud ser etter et kort
    siden aldri lager. Forste versjon av denne testen gjorde nettopp det og
    krasjet forst da katalogen ble oppdatert og Lensit ble billigst pa
    acuvue-oasys-6pk.
    """
    from datetime import datetime, timezone

    from site_generator.render_templates import reconcile_product

    now = datetime.now(timezone.utc)
    converted, cards = [], 0
    for p in CATALOG["products"]:
        for o in reconcile_product(p.get("offers", []), now):
            cards += 1
            html = render_offer_card(o, o["retailer"], p["name"], p["id"], CLICKOUTS)
            if "/go/" in html:
                converted.append((p["id"], o["retailer"]))

    assert converted == [(TARGET_PRODUCT, TARGET_RETAILER)], converted
    print(
        f"      hele katalogen: {len(CATALOG['products'])} produkter, "
        f"{cards} rendrede kort, 1 konvertert"
    )


def test_a_scraped_offer_is_never_converted() -> None:
    """Tredje ledd i gjerdet, og det eneste som trenger en konstruert verdi.

    Katalogen inneholder ingen skrapet Lensway-oppforing for dette produktet,
    sa a fjerne source-leddet fra betingelsen endrer ingenting observerbart --
    en mutasjonstest avslorte nettopp det. Beviset ma derfor lage tilfellet
    selv. Det er en test av BETINGELSEN, ikke av dataene: et skrapet tilbud
    har ingen avtale bak seg og ingen provisjon a attribuere, og /go/ ville
    myntet en click_id for en lenke ingen nettverkspartner noen gang ser.
    """
    o = dict(offer(TARGET_PRODUCT, TARGET_RETAILER), source="scraper")
    html = render_offer_card(
        o, TARGET_RETAILER, product(TARGET_PRODUCT)["name"], TARGET_PRODUCT, CLICKOUTS
    )

    assert "/go/" not in html
    assert attr(html, "data-affiliate") == "0"
    assert attr(html, "rel") == "nofollow noopener"


# ------------------------------------------------- everything else byte-for-byte
def test_only_the_href_differs_on_the_converted_card() -> None:
    """**Det sterkeste beviset i filen.** Rendrer kortet med og uten
    product_id -- altsa konvertert og ukonvertert -- og krever at de to
    HTML-strengene er identiske nar href-en byttes tilbake.

    Det dekker rel, target, data-retailer, data-affiliate, klasser, aria-label
    og all markup rundt i en enkelt sammenligning, i stedet for a liste opp
    attributtene og hape at lista er komplett.
    """
    o = offer(TARGET_PRODUCT, TARGET_RETAILER)
    name = product(TARGET_PRODUCT)["name"]

    before = render_offer_card(o, o["retailer"], name)  # ingen clickouts
    after = card(TARGET_PRODUCT, TARGET_RETAILER)

    assert before != after, "kortet ble ikke konvertert i det hele tatt"
    assert after.replace(GO, o["url"], 1) == before


def test_the_four_named_attributes_are_unchanged() -> None:
    """Samme fakta som testen over, uttrykt hver for seg -- fordi det er
    disse fire som ble lovet, og en feilende test bor si hvilken."""
    o = offer(TARGET_PRODUCT, TARGET_RETAILER)
    before = render_offer_card(o, o["retailer"], product(TARGET_PRODUCT)["name"])
    after = card(TARGET_PRODUCT, TARGET_RETAILER)

    for name in ("data-retailer", "data-affiliate", "rel", "target"):
        assert attr(after, name) == attr(before, name), name
    assert attr(after, "data-retailer") == "Lensway"
    assert attr(after, "data-affiliate") == "1"
    assert attr(after, "rel") == "sponsored noopener"
    assert attr(after, "target") == "_blank"


# ------------------------------------------------------------ the winner band
def test_the_winner_band_is_untouched_on_a_page_whose_winner_is_not_converted() -> None:
    """**Denne testen het "vinnerbanneret er urort" og beviste noe sterkere
    enn den sa.**

    Den leste kildekoden og slo fast at banneret ikke KUNNE konverteres --
    funksjonen tok ikke imot product_id. Det var sant og var med vilje mens
    utrullingen holdt til ett kort. Steg 1 ga banneret bade product_id og
    kartet, sa den gamle pastanden ville na bare bestatt hvis endringen ikke
    virket.

    Det som fortsatt skal vare sant, og som er det denne siden faktisk
    rendrer, er det svakere: nar vinneren ikke er et godkjent tilbud, star
    leverandor-URL-en. Lenson er billigst pa begge de konverterte produktene,
    sa det er tilstanden pa nettstedet i dag.
    """
    from site_generator.render_templates import reconcile_product, render_product_page

    target = product(TARGET_PRODUCT)
    rendered = {**target, "offers": reconcile_product(target["offers"], NOW)}
    html = render_product_page(
        rendered, CATALOG["categories"], {p["id"]: p for p in CATALOG["products"]},
        [], NOW, [], None, CLICKOUTS,
    )

    assert GO in html, "forutsetningen faller bort om siden ikke konverterte noe"
    winner = re.search(r'<a class="winner-band"[^>]*>', html).group(0)
    assert "/go/" not in winner, winner
    assert 'data-retailer="Lensway"' not in winner, "vinneren er ikke Lensway i dag"


def test_only_json_ld_still_builds_its_own_url() -> None:
    """**Den pastanden denne testen gjorde for, er na feil, og det er poenget.**

    For Steg 1 sa den at vinnerbanneret og antallskalkulatoren fortsatt
    bygget sin egen href fra `o["url"]`, og det var riktig: utrullingen holdt
    med vilje til ett kort. Steg 1 flyttet begge over pa den delte
    resolveren, sa den gamle pastanden ville na bestatt bare hvis endringen
    ikke virket.

    Det som star igjen er JSON-LD, som fortsatt leser `o["url"]` direkte --
    ikke fordi ingen kom sa langt, men fordi det er en uttalt policy.
    """
    import inspect

    from site_generator import render_templates

    source = inspect.getsource(render_templates)

    assert GO not in source, "tokenet skal ikke sta i kildekoden i det hele tatt"
    assert '"url": "{_json_str(o["url"])}",' in source, "JSON-LD skal lese o[url]"
    # Og de to andre skal IKKE gjore det lenger.
    assert 'href="{escape(best["url"])}"' not in source, "vinnerbanneret bygger fortsatt sin egen"
    assert '            "url": o["url"],' not in source, "kalkulatoren bygger fortsatt sin egen"


# ------------------------------------------------- alle flater, samme mal
def test_the_winner_band_uses_the_clickout_when_the_winner_is_converted() -> None:
    """**Den ene flaten katalogen ikke kan bevise for oss.**

    Lenson er billigst pa begge de konverterte produktene, sa ingen ekte side
    har i dag et konvertert tilbud som vinner -- og et band som aldri ble
    konvertert ville sett nøyaktig ut som et band som ikke KAN konverteres.
    Her gis tilbudet inn som `best` direkte, som er det samme kallet
    render_product_page gjor nar prisene en dag snur.
    """
    from site_generator.render_templates import reconcile_product, render_winner_widget

    offers = reconcile_product(product(TARGET_PRODUCT)["offers"], NOW)
    winner = next(o for o in offers if o["retailer"] == TARGET_RETAILER)

    band, _ = render_winner_widget(
        winner, offers, product(TARGET_PRODUCT)["name"],
        product_id=TARGET_PRODUCT, clickouts=CLICKOUTS,
    )

    assert band_href_of(band) == GO, band_href_of(band)
    assert 'data-retailer="Lensway"' in band
    assert "sponsored" in band
    for fragment in ("pdt.tradedoubler.com", "a(3494407)", "ttid("):
        assert fragment not in band.split(">")[0], fragment


def test_the_product_page_converts_the_band_when_the_converted_offer_wins() -> None:
    """**Gapet muteringstesten fant.**

    De to bannertestene kaller render_winner_widget direkte, sa de bestar
    selv om render_product_page slutter a sende product_id og kartet videre.
    Og katalogen kan ikke fange det: Lenson er billigst pa begge de
    konverterte produktene, sa ingen ekte side rendrer et konvertert band i
    dag.

    Her beholdes de EKTE tilbudene, men bare de som er dyrere enn Lensway --
    sa Lensway vinner. Ingen oppdiktede priser, ingen oppdiktet forhandler:
    et utsnitt av katalogen, ikke en fixture.
    """
    from site_generator.render_templates import reconcile_product, render_product_page

    target = product(TARGET_PRODUCT)
    reconciled = reconcile_product(target["offers"], NOW)
    lensway = next(o for o in reconciled if o["retailer"] == TARGET_RETAILER)
    kept = [
        o["retailer"] for o in reconciled
        if o["retailer"] == TARGET_RETAILER or o["total"] > lensway["total"]
    ]
    assert len(kept) > 1, "utsnittet ma ha noen a vinne over"

    subset = {**target, "offers": [o for o in target["offers"] if o["retailer"] in kept]}
    rendered = {**subset, "offers": reconcile_product(subset["offers"], NOW)}
    winner = next(o for o in rendered["offers"] if o["is_lowest"])
    assert winner["retailer"] == TARGET_RETAILER, winner["retailer"]

    html = render_product_page(
        rendered, CATALOG["categories"], {p["id"]: p for p in CATALOG["products"]},
        [], NOW, [], None, CLICKOUTS,
    )

    assert band_href_of(html) == GO, band_href_of(html)
    assert calculator_offers(html)[TARGET_RETAILER] == GO
    print(f"      vinner {TARGET_RETAILER} over {len(kept) - 1} dyrere tilbud -> band {GO}")


def test_the_winner_band_keeps_the_provider_url_for_an_unconverted_winner() -> None:
    """Halve gjerdet: et band som konverterte alt ville ogsa bestatt testen
    over."""
    from site_generator.render_templates import reconcile_product, render_winner_widget

    offers = reconcile_product(product(TARGET_PRODUCT)["offers"], NOW)
    winner = next(o for o in offers if o["retailer"] != TARGET_RETAILER)

    band, _ = render_winner_widget(
        winner, offers, product(TARGET_PRODUCT)["name"],
        product_id=TARGET_PRODUCT, clickouts=CLICKOUTS,
    )

    assert "/go/" not in band_href_of(band)
    assert band_href_of(band).startswith("https://")


def test_the_calculator_carries_the_same_target_as_the_card() -> None:
    """Kalkulatorens JSON skriver bandets href pa nytt ved antallsbytte. Uten
    denne ville konverteringen forsvunnet i det noen trykket "2 esker" -- en
    lenke som slutter a virke ved forste interaksjon er verre enn en som
    aldri virket, fordi ingen ser den skje."""
    from site_generator.render_templates import reconcile_product, render_winner_widget

    offers = reconcile_product(product(TARGET_PRODUCT)["offers"], NOW)
    _, qty = render_winner_widget(
        offers[0], offers, product(TARGET_PRODUCT)["name"],
        product_id=TARGET_PRODUCT, clickouts=CLICKOUTS,
    )

    data = calculator_offers(qty)
    assert data[TARGET_RETAILER] == GO, data[TARGET_RETAILER]
    assert data[TARGET_RETAILER] == href_of(card(TARGET_PRODUCT, TARGET_RETAILER))
    others = {r: u for r, u in data.items() if r != TARGET_RETAILER}
    assert others, "kontrollen er tom uten minst en annen forhandler"
    assert not [u for u in others.values() if "/go/" in u], others


def test_a_private_label_page_resolves_on_the_real_products_id() -> None:
    """Et private-label-produkt GJENBRUKER det ekte produktets tilbud, sa det
    samme konverterte tilbudet forekommer pa en side med en annen id. Slas
    kartet opp pa merkevarens id, bommer det -- stille, fordi resultatet da
    bare er leverandor-URL-en."""
    import json

    from site_generator.render_templates import render_private_label_page

    labels = json.loads((ROOT / "private_labels.json").read_text(encoding="utf-8"))["labels"]
    label = next(l for l in labels if l["real_product_id"] == TARGET_PRODUCT)
    real = product(TARGET_PRODUCT)

    html = render_private_label_page(
        label, real, CATALOG["categories"], NOW, None, CLICKOUTS
    )

    hrefs = dict(
        (retailer, href) for href, retailer in re.findall(
            r'<a class="offer-card[^"]*" href="([^"]*)"[^>]*data-retailer="([^"]*)"', html
        )
    )
    assert hrefs[TARGET_RETAILER] == GO, hrefs[TARGET_RETAILER]
    assert label["slug"] != TARGET_PRODUCT, "kontrollen er tom om id-ene er like"
    print(f"      {label['slug']} -> {TARGET_PRODUCT} / {TARGET_RETAILER}")


def test_a_solution_page_gets_the_map_and_converts_nothing() -> None:
    """Linsevæskesider far kartet av samme grunn som alle andre flater: en
    side som rendrer leverandor-URL-en skal gjore det fordi svaret var
    ingenting, ikke fordi kartet aldri nadde fram. Ingen av de fire godkjente
    tilbudene er linsevæske, sa svaret ER ingenting."""
    from site_generator.render_templates import render_solution_product_page

    solutions = [p for p in CATALOG["products"] if "category_slug" not in p]
    assert solutions, "ingen linsevæskeprodukter i katalogen"

    for solution in solutions[:5]:
        html = render_solution_product_page(solution, NOW, CLICKOUTS)
        assert "/go/" not in html, solution["id"]


def test_json_ld_never_carries_a_clickout() -> None:
    """Uttalt policy, ikke en utelatelse."""
    from site_generator.render_templates import reconcile_product, render_product_page

    target = product(TARGET_PRODUCT)
    rendered = {**target, "offers": reconcile_product(target["offers"], NOW)}
    html = render_product_page(
        rendered, CATALOG["categories"], {p["id"]: p for p in CATALOG["products"]},
        [], NOW, [], None, CLICKOUTS,
    )

    assert GO in html, "forutsetningen faller bort om siden ikke konverterte noe"
    schema_urls = re.findall(r'"@type": "Offer".*?"url": "([^"]*)"', html, re.S)
    assert schema_urls, "ingen JSON-LD-tilbud a kontrollere"
    assert not [u for u in schema_urls if "/go/" in u], schema_urls


def surfaces(*enabled):
    """The clickout map with only these surfaces switched on."""
    from site_generator.chillout_clickout import Clickouts

    return Clickouts(CLICKOUTS, enabled)


def test_the_winner_band_answers_to_its_own_switch() -> None:
    """**A surface reading another surface's state is invisible in lockstep.**

    Every other test here turns surfaces on and off together, so a band that
    consulted `offer_card` would have passed all of them. Here they disagree:
    the card is on, the band is off, and the page has to show both.

    Uses the subset where Lensway genuinely wins, because no live page renders
    a converted band.
    """
    from site_generator.render_templates import reconcile_product, render_product_page

    target = product(TARGET_PRODUCT)
    reconciled = reconcile_product(target["offers"], NOW)
    lensway = next(o for o in reconciled if o["retailer"] == TARGET_RETAILER)
    kept = [
        o["retailer"] for o in reconciled
        if o["retailer"] == TARGET_RETAILER or o["total"] > lensway["total"]
    ]
    subset = {**target, "offers": [o for o in target["offers"] if o["retailer"] in kept]}
    rendered = {**subset, "offers": reconcile_product(subset["offers"], NOW)}

    html = render_product_page(
        rendered, CATALOG["categories"], {p["id"]: p for p in CATALOG["products"]},
        [], NOW, [], None, surfaces("offer_card", "quantity_calculator"),
    )

    assert "/go/" not in band_href_of(html), band_href_of(html)
    assert band_href_of(html).startswith("https://")
    # ...while the card for the same offer on the same page is still converted.
    cards = dict(
        (retailer, href) for href, retailer in re.findall(
            r'<a class="offer-card[^"]*" href="([^"]*)"[^>]*data-retailer="([^"]*)"', html
        )
    )
    assert cards[TARGET_RETAILER] == GO, cards[TARGET_RETAILER]


def test_the_calculator_answers_to_its_own_switch() -> None:
    """The other half: calculator off, card on, on an ordinary page."""
    from site_generator.render_templates import reconcile_product, render_product_page

    target = product(TARGET_PRODUCT)
    rendered = {**target, "offers": reconcile_product(target["offers"], NOW)}

    html = render_product_page(
        rendered, CATALOG["categories"], {p["id"]: p for p in CATALOG["products"]},
        [], NOW, [], None, surfaces("offer_card", "winner_band"),
    )

    data = calculator_offers(html)
    assert "/go/" not in data[TARGET_RETAILER], data[TARGET_RETAILER]
    cards = dict(
        (retailer, href) for href, retailer in re.findall(
            r'<a class="offer-card[^"]*" href="([^"]*)"[^>]*data-retailer="([^"]*)"', html
        )
    )
    assert cards[TARGET_RETAILER] == GO


def test_the_card_answers_to_its_own_switch() -> None:
    """And the third leg, so no pair of surfaces can be swapped for another."""
    from site_generator.render_templates import reconcile_product, render_product_page

    target = product(TARGET_PRODUCT)
    rendered = {**target, "offers": reconcile_product(target["offers"], NOW)}

    html = render_product_page(
        rendered, CATALOG["categories"], {p["id"]: p for p in CATALOG["products"]},
        [], NOW, [], None, surfaces("winner_band", "quantity_calculator"),
    )

    cards = dict(
        (retailer, href) for href, retailer in re.findall(
            r'<a class="offer-card[^"]*" href="([^"]*)"[^>]*data-retailer="([^"]*)"', html
        )
    )
    assert "/go/" not in cards[TARGET_RETAILER], cards[TARGET_RETAILER]
    # The calculator is on, so its entry for the same offer still is converted.
    assert calculator_offers(html)[TARGET_RETAILER] == GO


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    print(f"\n{len(tests)} kontroller, rendret fra ekte katalogdata\n")
    for fn in tests:
        try:
            fn()
            print(f"  [OK]   {fn.__name__}")
        except AssertionError as error:
            failed += 1
            print(f"  [FEIL] {fn.__name__}: {error}")
        except Exception as error:  # noqa: BLE001
            # En test som KRASJER er ikke en test som ikke kjorte. Uten dette
            # avbrot den forste uventede feilen hele kjoringen, og alle
            # testene etter den var stille fravarende framfor bestatt.
            failed += 1
            print(f"  [KRASJ] {fn.__name__}: {type(error).__name__}: {error}")
    print("\n" + ("alle bestatt" if not failed else f"{failed} feilet"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
