"""Regresjonsbevis for det ene konverterte /go/-kortet.

**Oppdatert for Steg B.** Tokenet er ikke lenger hardkodet; det kommer fra
Chillouts lesekontrakt pa byggetidspunktet. Kortet som rendres er det samme,
og hele nettstedet er bevist byte-identisk med bootstrap-utgaven, sa hver
pastand under gjelder fortsatt -- de far na kartet inn i stedet for a stole
pa en konstant. Feilsituasjonene ligger i test_chillout_clickout.py.

Opprinnelig docstring:

ETT kort, pa ETT produkt, hos EN forhandler. Denne filen finnes for a bevise
nettopp det -- at endringen traff det den skulle og ingenting annet -- og for
at et senere, bredere oppsett ikke skal kunne skje ved et uhell.

Kjores direkte:  python test_clickout_bootstrap.py
Eller med pytest hvis den er tilgjengelig.

Bevisene rendres fra site_generator/catalog_live.json, altsa ekte katalogdata
og ekte leverandor-URL-er, ikke oppdiktede fixtures. Et bevis bygget pa en
fixture ville bare bevist at fixturen var riktig.

**Tokenet er hardkodet i render_templates.py, og det er bevisst midlertidig.**
Den permanente losningen er at generatoren leser clickout_url fra Chillouts
lesekontrakt pa byggetidspunktet. Ikke kopier monsteret til flere tilbud.
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


def href_of(html: str) -> str:
    return re.search(r'<a class="[^"]*" href="([^"]*)"', html).group(1)


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
def test_the_winner_band_is_untouched() -> None:
    """Vinnerbanneret rendres av en annen funksjon som aldri fikk product_id,
    sa det KAN ikke konverteres. Bevist mot den faktiske kildekoden framfor
    ved a rendre den, fordi det er signaturen som er garantien."""
    import inspect

    from site_generator import render_templates

    source = inspect.getsource(render_templates)
    band = source[source.index('winner_band = f"""<a class="winner-band"'):][:400]

    assert "/go/" not in band
    # Banneret bygger fortsatt sin egen href fra tilbudets URL, ikke fra
    # href-variabelen som bare finnes inne i render_offer_card.
    assert 'href="{escape(best["url"])}"' in band


def test_json_ld_and_the_quantity_calculator_still_use_the_provider_url() -> None:
    """De to andre forbrukerne av o["url"]. Begge er uendret, og det er en
    bevisst konsekvens av a holde utrullingen til ett kort: for dette ene
    produktet peker kortet pa /go/ mens schema og kalkulatoren peker pa
    nettverket.

    **Etter Steg B star tokenet null steder i kildekoden** -- det kommer fra
    kontrakten. Pastanden er derfor at ingen av de to andre forbrukerne har
    fatt en /go/-sti, ikke lenger en telling av en konstant som ikke finnes.
    """
    import inspect

    from site_generator import render_templates

    source = inspect.getsource(render_templates)

    assert GO not in source, "tokenet skal ikke sta i kildekoden i det hele tatt"
    # De to forbrukerne bygger fortsatt sin egen href fra tilbudets URL. `if
    # consumer in source` ville gjort pastanden tom om en av dem forsvant --
    # den skal feile da, ikke hoppe over.
    # Vinnerbanneret, antallskalkulatorens JSON og JSON-LD-schemaet --
    # de tre andre forbrukerne av tilbudets URL, alle uendret.
    for consumer in (
        'href="{escape(best["url"])}"',        # vinnerbanneret
        '"url": o["url"],',                    # antallskalkulatoren
        '"url": "{_json_str(o["url"])}",',     # JSON-LD
    ):
        assert consumer in source, consumer


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
    print("\n" + ("alle bestatt" if not failed else f"{failed} feilet"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
