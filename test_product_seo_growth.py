"""Regresjonstester for Product SEO Growth Round 1 (DN-1, DN-2, DN-3).

Kjores direkte:  python test_product_seo_growth.py
Ingen pytest og ingen nettverk. Rendrer ekte produktsider fra
site_generator/catalog_live.json med en fast klokke (nyeste checked_at), slik at
tilbudene regnes som ferske.

DN-1  Sibling-boksen lister ALLE andre pakningsstorrelser av samme produkt.
DN-2  "Hvor lenge varer"-FAQ folger produktegenskapen Brukstid = Dagslinse, ikke kategori.
DN-3  Alternativ stavemate ("Dailies Total 1") staar kun en gang, kun pa Dailies Total1-sidene.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path[:0] = [str(ROOT), str(ROOT / "site_generator")]

import generate_pages as gp  # noqa: E402
import render_templates as rt  # noqa: E402

CATALOG = json.loads((ROOT / "site_generator" / "catalog_live.json").read_text(encoding="utf-8"))
FAMILIES = json.loads((ROOT / "product_families.json").read_text(encoding="utf-8"))["families"]
LENSES = [p for p in CATALOG["products"] if "category_slug" in p]
BY_ID = {p["id"]: p for p in CATALOG["products"]}
LENS_BY_ID = {p["id"]: p for p in LENSES}
NOW = max(datetime.fromisoformat(o["checked_at"]) for p in LENSES for o in p["offers"])

FAMILY_BY_PRODUCT = {}
for _family in FAMILIES:
    for _mid in _family["member_ids"]:
        if _mid in BY_ID:
            FAMILY_BY_PRODUCT[_mid] = gp.family_lookup_entry(_family)

#: Det eksisterende, publiserte svaret (uendret av DN-2).
PUBLISHED_FAQ_90 = (
    "Til ett øye varer pakningen i 90 dager (én linse per dag). Bruker du linser med samme styrke på begge øyne "
    "fra samme pakning, varer den 45 dager. Har du ulik styrke på hvert øye, trenger du vanligvis en egen pakning per øye."
)


def render(product: dict, by_id: dict | None = None, family: dict | None = None) -> str:
    return rt.render_product_page(
        product, CATALOG["categories"], by_id if by_id is not None else LENS_BY_ID, [], NOW, [],
        family if family is not None else FAMILY_BY_PRODUCT.get(product["id"]), None,
    )


def callout_hrefs(html: str) -> list[str]:
    return re.findall(r'<a class="pack-size-callout" href="(/kontaktlinser/[^"]+)"', html)


def faq_questions(html: str) -> list[str]:
    questions: list[str] = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        data = json.loads(block)
        if isinstance(data, dict) and data.get("@type") == "FAQPage":
            questions += [q["name"] for q in data["mainEntity"]]
    return questions


def faq_answer(html: str, question_start: str) -> str | None:
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        data = json.loads(block)
        if isinstance(data, dict) and data.get("@type") == "FAQPage":
            for q in data["mainEntity"]:
                if q["name"].startswith(question_start):
                    return q["acceptedAnswer"]["text"]
    return None


def spec(product: dict, label: str) -> str:
    return next((v for k, v in product.get("specs", []) if k == label), "")


def href(pid: str) -> str:
    p = LENS_BY_ID[pid]
    return f'/kontaktlinser/{p["brand_slug"]}/{p["slug"]}/'


# ----------------------------------------------------------------- DN-1

def test_middle_product_of_a_three_pack_group_shows_both_siblings():
    html = render(LENS_BY_ID["everclear-elite-90pk"])
    assert callout_hrefs(html) == [href("everclear-elite-30pk"), href("everclear-elite-180pk")], callout_hrefs(html)
    assert "Finnes også i <strong>30-pakning</strong>" in html and "Finnes også i <strong>180-pakning</strong>" in html


def test_the_30_pack_shows_both_90_and_180():
    html = render(LENS_BY_ID["everclear-elite-30pk"])
    assert callout_hrefs(html) == [href("everclear-elite-90pk"), href("everclear-elite-180pk")], callout_hrefs(html)
    html180 = render(LENS_BY_ID["everclear-elite-180pk"])
    assert callout_hrefs(html180) == [href("everclear-elite-30pk"), href("everclear-elite-90pk")], callout_hrefs(html180)


def test_two_pack_group_and_single_pack_products_are_unchanged():
    assert callout_hrefs(render(LENS_BY_ID["clearlii-daily-90pk"])) == [href("clearlii-daily-30pk")]
    assert callout_hrefs(render(LENS_BY_ID["biofinity-6pk"])) == []


def test_price_per_lens_comparison_is_kept():
    html = render(LENS_BY_ID["everclear-elite-90pk"])
    assert re.search(r"Finnes også i <strong>30-pakning</strong> — \d+,\d\d kr/linse \(\d+ % dyrere per linse\)", html), html[:0]
    assert re.search(r"Finnes også i <strong>180-pakning</strong> — \d+,\d\d kr/linse \(\d+ % billigere per linse\)", html)


def test_no_unrelated_products_become_siblings_synthetic():
    def prod(pid, brand="a", category="c"):
        return {"id": pid, "brand_slug": brand, "category_slug": category, "slug": pid, "name": pid}
    by_id = {p["id"]: p for p in [
        prod("foo-30pk"), prod("foo-90pk"), prod("foo-180pk", brand="b"),           # annet merke, samme stamme
        prod("foo-6pk", category="x"),                                                  # annen kategori, samme stamme
        prod("foo-astigmatism-30pk"), prod("foo-astigmatism-90pk"),                    # annen variant (egen stamme)
        prod("foo-multifocal-30pk"), prod("foobar-30pk"), prod("foo"), prod("foo-2pkx"),  # lignende navn, ikke samme stamme
    ]}
    siblings = rt.find_pack_siblings(by_id["foo-30pk"], by_id)
    assert [(size, p["id"]) for size, p in siblings] == [(90, "foo-90pk")], siblings
    assert [(size, p["id"]) for size, p in rt.find_pack_siblings(by_id["foo-astigmatism-90pk"], by_id)] == [(30, "foo-astigmatism-30pk")]
    assert rt.find_pack_siblings(by_id["foo"], by_id) == []


def test_every_real_sibling_is_the_same_product_in_another_pack():
    def name_without_pack(p):
        return re.sub(r"\s*\d+-pack$", "", p["name"])
    checked = 0
    for p in LENSES:
        for size, sib in rt.find_pack_siblings(p, LENS_BY_ID):
            checked += 1
            assert sib["id"] != p["id"] and size != int(re.search(r"-(\d+)pk$", p["id"]).group(1))
            assert sib["brand_slug"] == p["brand_slug"] and sib["category_slug"] == p["category_slug"], (p["id"], sib["id"])
            assert name_without_pack(sib) == name_without_pack(p), (p["id"], sib["id"])
    assert checked > 50


# ----------------------------------------------------------------- DN-2

def test_daily_faq_follows_the_product_property_for_every_lens():
    daily_without, other_with = [], []
    for p in LENSES:
        if not re.search(r"-\d+pk$", p["id"]):
            continue
        has_faq = any(q.startswith("Hvor lenge varer") for q in faq_questions(render(p)))
        if spec(p, "Brukstid") == "Dagslinse" and not has_faq:
            daily_without.append(p["id"])
        if spec(p, "Brukstid") != "Dagslinse" and has_faq:
            other_with.append(p["id"])
    assert not daily_without, daily_without
    assert not other_with, other_with


def test_daily_toric_multifocal_and_colored_lenses_get_the_faq_and_monthly_do_not():
    for pid in ("dailies-total1-multifocal-90pk", "acuvue-moist-astigmatism-30pk", "freshlook-oneday-30pk", "everclear-elite-90pk"):
        assert any(q.startswith("Hvor lenge varer") for q in faq_questions(render(LENS_BY_ID[pid]))), pid
    for pid in ("biofinity-6pk", "biofinity-toric-6pk"):
        assert not any(q.startswith("Hvor lenge varer") for q in faq_questions(render(LENS_BY_ID[pid]))), pid


def test_faq_is_driven_by_the_property_not_the_category():
    monthly_as_daily = copy.deepcopy(LENS_BY_ID["biofinity-6pk"])
    monthly_as_daily["specs"] = [[k, "Dagslinse" if k == "Brukstid" else v] for k, v in monthly_as_daily["specs"]]
    assert any(q.startswith("Hvor lenge varer") for q in faq_questions(render(monthly_as_daily)))
    daily_as_monthly = copy.deepcopy(LENS_BY_ID["everclear-elite-90pk"])
    daily_as_monthly["specs"] = [[k, "Månedslinse" if k == "Brukstid" else v] for k, v in daily_as_monthly["specs"]]
    assert not any(q.startswith("Hvor lenge varer") for q in faq_questions(render(daily_as_monthly)))


def test_published_faq_text_is_unchanged():
    for pid in ("dailies-total1-multifocal-90pk", "everclear-elite-90pk"):
        assert faq_answer(render(LENS_BY_ID[pid]), "Hvor lenge varer") == PUBLISHED_FAQ_90, pid


# ----------------------------------------------------------------- DN-3

TOTAL1_IDS = next(f for f in FAMILIES if f["slug"] == "dailies-total1")["member_ids"]


def test_total1_alias_appears_exactly_once_and_only_on_the_total1_pages():
    wrong = {}
    for p in LENSES:
        count = render(p).count("Total 1")
        expected = 1 if p["id"] in TOTAL1_IDS else 0
        if count != expected:
            wrong[p["id"]] = count
    assert not wrong, wrong
    assert len(TOTAL1_IDS) == 7


def test_total1_alias_sentence_is_neutral_and_name_specific():
    html = render(LENS_BY_ID["dailies-total1-multifocal-90pk"])
    assert "<p>Produktnavnet kan også skrives Dailies Total 1 Multifocal.</p>" in html
    assert "<p>Produktnavnet kan også skrives Dailies Total 1.</p>" in render(LENS_BY_ID["dailies-total1-30pk"])
    assert "<p>Produktnavnet kan også skrives Dailies Total 1 for Astigmatism.</p>" in render(LENS_BY_ID["dailies-total1-astigmatism-90pk"])
    assert "hos mange butikker" not in html and "butikker skriver" not in html


def test_total1_alias_does_not_touch_title_h1_canonical_or_schema():
    pid = "dailies-total1-multifocal-90pk"
    html = render(LENS_BY_ID[pid])
    assert "<title>Dailies Total1 Multifocal 90-pack » Sammenlign og få billigste pris</title>" in html
    assert re.search(r"<h1[^>]*>Dailies Total1 Multifocal 90-pack</h1>", html)
    assert '<link rel="canonical" href="https://kontaktlinser.no/kontaktlinser/dailies/dailies-total1-multifocal-90-pack/">' in html
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        assert "Total 1" not in block
    meta = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
    assert "Total 1" not in meta


def test_alt_name_is_opt_in_per_family():
    assert gp.family_lookup_entry({"slug": "x", "name": "X"}) == {"slug": "x", "name": "X"}
    assert gp.family_lookup_entry({"slug": "x", "name": "X", "alt_name": "X 1"})["alt_name"] == "X 1"
    assert [f["slug"] for f in FAMILIES if f.get("alt_name")] == ["dailies-total1"]


def main() -> int:
    failed = 0
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]:
        try:
            fn()
            print(f"  ok     {fn.__name__}")
        except AssertionError as error:
            failed += 1
            print(f"  [FEIL] {fn.__name__}: {error}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"  [KRASJ] {fn.__name__}: {type(error).__name__}: {error}")
    print("\n" + ("alle bestatt" if not failed else f"{failed} feilet"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
