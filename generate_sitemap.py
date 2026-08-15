"""
generate_sitemap.py

Genererer sitemap-indeks og delte sitemaps fra site_content.json.

Kjør denne på nytt hver gang produktlisten endres. lastmod på en produktside
bør settes til tidspunktet prisen sist ble bekreftet, ikke dagens dato.

BASE_URL må matche produksjonsdomenet nøyaktig, inkludert https og uten
etterslash.
"""

import json
from xml.sax.saxutils import escape

BASE_URL = "https://kontaktlinser.no"


def url_entry(path: str, lastmod: str) -> str:
    return (
        f"  <url>\n"
        f"    <loc>{escape(BASE_URL + path)}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"  </url>\n"
    )


def write_urlset(filename: str, entries: list[str]) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.writelines(entries)
        f.write("</urlset>\n")


def write_sitemap_index(filename: str, sitemap_files: list[str]) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for name in sitemap_files:
            f.write(f"  <sitemap>\n    <loc>{escape(BASE_URL + '/' + name)}</loc>\n  </sitemap>\n")
        f.write("</sitemapindex>\n")


def main(content_path: str = "site_content.json") -> None:
    with open(content_path, encoding="utf-8") as f:
        content = json.load(f)

    static_entries = [
        url_entry(p["path"], p["lastmod"]) for p in content["static_pages"]
    ]
    write_urlset("sitemap-statiske.xml", static_entries)

    category_entries = [
        url_entry(f"/kontaktlinser/{c['slug']}/", c["lastmod"]) for c in content["categories"]
    ] + [
        url_entry(f"/merke/{b['slug']}/", b["lastmod"]) for b in content["brands"]
    ]
    write_urlset("sitemap-kategorier.xml", category_entries)

    product_entries = [
        url_entry(f"/kontaktlinser/{p['brand_slug']}/{p['product_slug']}/", p["lastmod"])
        for p in content["products"]
    ]
    write_urlset("sitemap-produkter.xml", product_entries)

    guide_entries = [
        url_entry(f"/guide/{g['slug']}/", g["lastmod"]) for g in content["guides"]
    ]
    write_urlset("sitemap-guider.xml", guide_entries)

    solution_entries = [
        url_entry(f"/{s['solution_category']}/{s['brand_slug']}/{s['slug']}/", s["lastmod"])
        for s in content.get("solutions", [])
    ]
    write_urlset("sitemap-linsevaeske.xml", solution_entries)

    private_label_entries = [
        url_entry(f"/private-label/{p['slug']}/", p["lastmod"])
        for p in content.get("private_labels", [])
    ]
    write_urlset("sitemap-private-label.xml", private_label_entries)

    write_sitemap_index(
        "sitemap.xml",
        ["sitemap-statiske.xml", "sitemap-kategorier.xml", "sitemap-produkter.xml", "sitemap-guider.xml", "sitemap-linsevaeske.xml", "sitemap-private-label.xml"],
    )
    print("Generert: sitemap.xml + 4 delte sitemaps")


if __name__ == "__main__":
    main()
