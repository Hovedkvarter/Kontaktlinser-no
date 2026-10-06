"""Regresjonstester for SEO-/schema-runden 2026-10-06 (Web Standard-auditen).

Kjores direkte:  python test_seo_schema.py
Ingen pytest eller nettverk. Dekker: absolutte bilde-URL-er, bildedimensjoner,
guide-schema (Article + BreadcrumbList), byggeportene i validate_build.py og at
/guider/ kommer med i guide-sitemapen.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path[:0] = [str(ROOT), str(ROOT / "site_generator")]

import render_templates as rt  # noqa: E402
import validate_build as vb  # noqa: E402


def _json_ld_blocks(html: str) -> list:
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)]


def test_abs_url_makes_root_relative_paths_absolute():
    assert rt._abs_url("/static/products/a.jpg") == "https://kontaktlinser.no/static/products/a.jpg"
    assert rt._abs_url("https://cdn.example/x.jpg") == "https://cdn.example/x.jpg"
    assert rt._abs_url(None) is None


def test_og_image_is_always_absolute():
    tags = rt._og_meta("T", "D", "https://kontaktlinser.no/x/", "/static/products/acuvue-oasys-6pk.jpg")
    assert 'og:image" content="https://kontaktlinser.no/static/products/acuvue-oasys-6pk.jpg"' in tags
    assert 'og:image" content="https://kontaktlinser.no/static/logo.png"' in rt._og_meta("T", "D", "https://kontaktlinser.no/x/")


def test_image_size_reader_matches_the_files():
    try:
        from PIL import Image
    except ImportError:
        return  # PIL er ikke en CI-avhengighet; testen kjorer lokalt
    for rel in ("static/products/acuvue-oasys-6pk.jpg", "static/products/acuvue-oasys-6pk.webp", "static/logo.png"):
        assert rt._read_image_size(ROOT / rel) == Image.open(ROOT / rel).size, rel


def test_img_tag_gets_dimensions_for_known_images_and_never_guesses():
    own = rt._img_tag("/static/products/acuvue-oasys-6pk.jpg", "x")
    assert re.search(r'<img [^>]*width="\d+" height="\d+"', own), own
    unknown = rt._img_tag("https://upstream.example/does-not-exist.jpg", "x")
    assert "width=" not in unknown and "height=" not in unknown, unknown


def test_guide_page_schema_has_image_main_entity_and_matching_breadcrumb():
    slug = "forsta-kontaktlinseresepten"
    html = rt.render_guide_page(slug)
    blocks = _json_ld_blocks(html)
    article = next(b for b in blocks if b.get("@type") == "Article")
    crumbs = next(b for b in blocks if b.get("@type") == "BreadcrumbList")
    assert article["image"].startswith("https://kontaktlinser.no/static/guides/"), article.get("image")
    assert article["mainEntityOfPage"] == {"@type": "WebPage", "@id": f"https://kontaktlinser.no/guide/{slug}/"}
    visible = re.search(r'<p class="breadcrumb">(.*?)</p>', html, re.DOTALL).group(1)
    visible_names = [re.sub(r"<[^>]+>", "", p).strip() for p in visible.split("›")]
    assert [i["name"] for i in crumbs["itemListElement"]] == visible_names
    assert crumbs["itemListElement"][-1]["item"] == f"https://kontaktlinser.no/guide/{slug}/"


def test_validate_build_rejects_relative_image_urls():
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        (build / "p").mkdir()
        (build / "p" / "index.html").write_text(
            '<meta property="og:image" content="/static/a.jpg">'
            '<script type="application/ld+json">{"@type": "Product", "image": "/static/a.jpg"}</script>',
            encoding="utf-8")
        old = vb.BUILD_DIR
        vb.BUILD_DIR = build
        try:
            errors: list[str] = []
            vb.check_absolute_image_urls(errors)
        finally:
            vb.BUILD_DIR = old
        assert len(errors) == 2, errors


def test_validate_build_flags_llms_txt_links_to_missing_pages():
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        (build / "finnes").mkdir()
        (build / "finnes" / "index.html").write_text("x", encoding="utf-8")
        old = vb.BUILD_DIR
        vb.BUILD_DIR = build
        try:
            errors: list[str] = []
            vb.check_llms_txt(errors)  # leser den ekte llms.txt mot en tom bygg-mappe
        finally:
            vb.BUILD_DIR = old
        assert errors, "tom bygg-mappe ma gi feil for hver side llms.txt peker pa"
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    for stale in ("24 timer", "inkludert frakt", "Interoptik", "Specsavers"):
        assert stale not in text, f"foreldet pastand i llms.txt: {stale}"


def test_guide_index_goes_into_the_guide_sitemap():
    import os
    import generate_sitemap as gs
    content = {
        "static_pages": [], "categories": [], "brands": [], "products": [], "private_labels": [], "product_families": [],
        "guide_index": {"path": "/guider/", "lastmod": "2026-10-06"},
        "guides": [{"slug": "a", "lastmod": "2026-08-01"}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            Path("c.json").write_text(json.dumps(content), encoding="utf-8")
            gs.main("c.json")
            xml = Path("sitemap-guider.xml").read_text(encoding="utf-8")
        finally:
            os.chdir(cwd)
    assert "<loc>https://kontaktlinser.no/guider/</loc>" in xml
    assert "<loc>https://kontaktlinser.no/guide/a/</loc>" in xml


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
