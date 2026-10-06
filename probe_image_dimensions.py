"""
probe_image_dimensions.py

Slår opp bredde/høyde for produktbilder vi viser fra forhandlernes feeder
(ikke våre egne filer under /static/) og skriver dem til image_dimensions.json.
Byggingen leser KUN den filen (se _image_dims i site_generator/render_templates.py)
og gjør aldri nettverkskall; manglende oppføring betyr bare at <img> får ingen
width/height (aldri en gjetning).

Dette er et manuelt utviklerverktøy, IKKE en del av CI. Kjør det på nytt når
nye feedbilder dukker opp:

    python3 probe_image_dimensions.py            # legger til manglende URL-er
    python3 probe_image_dimensions.py --refresh  # måler alt på nytt

Kun bildets header leses (de første KB-ene), ett kall per URL, maks 4 samtidig,
med en identifiserbar User-Agent. Bildene lagres ikke noe sted.
"""

import argparse
import concurrent.futures as cf
import io
import json
import sys
from datetime import date
from pathlib import Path

import requests
from PIL import ImageFile

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "site_generator")]
import render_templates as rt  # noqa: E402

OUT = ROOT / "image_dimensions.json"
CATALOG = ROOT / "site_generator" / "catalog_live.json"
UA = {"User-Agent": "kontaktlinser.no image-dimension probe (dimensjoner til width/height)"}


def wanted_urls() -> set[str]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    urls: set[str] = set()
    for p in catalog["products"]:
        u = rt._product_image(p)
        if u and not u.startswith("/"):
            urls.add(u)
            urls.add(rt._larger_feed_image(u))  # hero på linsevæske/øyedråper bruker større variant
    return urls


def probe(url: str) -> tuple[str, list[int] | None]:
    try:
        with requests.get(url, headers=UA, stream=True, timeout=20) as r:
            if r.status_code != 200:
                return url, None
            parser = ImageFile.Parser()
            for chunk in r.iter_content(4096):
                parser.feed(chunk)
                if parser.image is not None:
                    return url, list(parser.image.size)
            return url, None
    except Exception:
        return url, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    known: dict[str, list[int]] = {}
    if OUT.exists() and not args.refresh:
        known = json.loads(OUT.read_text(encoding="utf-8")).get("images", {})
    todo = sorted(wanted_urls() - set(known))
    print(f"{len(todo)} URL-er å måle ({len(known)} kjent fra før)")
    failed = []
    with cf.ThreadPoolExecutor(4) as ex:
        for url, dims in ex.map(probe, todo):
            if dims:
                known[url] = dims
            else:
                failed.append(url)
    keep = wanted_urls()
    images = {u: known[u] for u in sorted(known) if u in keep}
    OUT.write_text(json.dumps({
        "_comment": "Bredde/høyde for feedbilder (ikke egne filer). Generert av probe_image_dimensions.py -- "
                    "ikke rediger for hånd. Brukes kun til width/height på <img>; manglende URL = ingen attributter.",
        "generated": date.today().isoformat(),
        "images": images,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"skrev {len(images)} oppføringer; {len(failed)} kunne ikke måles")
    for u in failed[:10]:
        print("  mangler:", u)


if __name__ == "__main__":
    main()
