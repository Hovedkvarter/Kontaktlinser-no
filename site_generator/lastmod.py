"""
lastmod.py

Ærlig <lastmod> i sitemap. Før 2026-09-26 sto alle URL-er på "i dag" ved hvert
bygg, også guider som ikke var rørt siden august -- en dato som ikke stemmer er
misvisende data til søkemotorene. Regelen nå (avklart med Kai):

- Guider: redaksjonell "updated"-dato (samme som byline og Article-schema).
- Sider med prisdata (produkt, kategori, merke, serie, forside ...): datoen
  prisene sist ble BEKREFTET (nyeste checked_at blant tilbudene siden viser),
  også når prisene er uendret -- å bekrefte prisene er en reell oppdatering av
  en prissammenligning. Gjenbrukte tilbud beholder sin gamle checked_at, så
  datoen står ikke på "i dag" hvis noe faktisk ikke ble hentet.
- Alle sider: aldri eldre enn siste faktiske innholdsendring. Den finnes via
  en signatur (hash) av den ferdige HTML-en, med flyktige deler fjernet
  ("Sist oppdatert: N timer siden", prisgrafen, JSON-LD dateModified). Ny
  signatur (ny tekst/mal) = dagens dato; ellers beholdes forrige dato fra
  lastmod_state.json, som CI committer tilbake på samme måte som
  price_history.json. Statiske sider uten prisdata (om-oss, personvern ...)
  bruker kun signaturen.
"""

import hashlib
import json
import re
from pathlib import Path

STATE_PATH = Path(__file__).parent / "lastmod_state.json"

_VOLATILE = [
    # "Sist oppdatert: 6 timer siden" / "akkurat nå" / "2 dager siden" per tilbud
    re.compile(r"Sist oppdatert: [^<]*"),
    # JSON-LD "dateModified" på produktsider = nyeste checked_at, dvs. tidspunktet
    # vi sist BEKREFTET prisene -- endrer seg ved hver kjøring uten at innholdet
    # nødvendigvis har endret seg.
    re.compile(r'"dateModified": "[^"]*"'),
    # Prisutviklingsgrafen: nytt punkt og ny akse-dato hver dag uten at prisen
    # nødvendigvis er endret -- selve prisen fanges av tilbudslisten.
    re.compile(r'<div class="price-history">.*?</svg>\s*</div>', re.DOTALL),
]


def signature(html: str) -> str:
    for pattern in _VOLATILE:
        html = pattern.sub("", html)
    return hashlib.sha1(html.encode("utf-8")).hexdigest()


def _page_file(build_dir: Path, path: str) -> Path:
    return build_dir / "index.html" if path == "/" else build_dir / path.strip("/") / "index.html"


def resolve_lastmods(
    build_dir: Path,
    paths: list[str],
    today: str,
    fixed: dict[str, str] | None = None,
    floors: dict[str, str] | None = None,
    state_path: Path = STATE_PATH,
) -> dict[str, str]:
    """path -> lastmod (YYYY-MM-DD). `fixed` gir sider med en redaksjonell dato
    (guider) som ALLTID brukes som den er. `floors` gir for prissider datoen
    prisene sist ble bekreftet; resultatet er den seneste av den og
    innholds-signaturens dato. Oppdaterer og skriver state-filen.
    Første gang en side sees (ingen state) settes dagens dato -- vi vet ikke
    når den sist endret seg, og det er ærligere enn å finne på en eldre dato."""
    fixed = fixed or {}
    floors = floors or {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    result: dict[str, str] = {}
    new_state: dict[str, dict] = {}
    for path in paths:
        if path in fixed:
            result[path] = fixed[path]
            continue
        page = _page_file(build_dir, path)
        if not page.exists():
            result[path] = today
            continue
        sig = signature(page.read_text(encoding="utf-8"))
        prev = state.get(path)
        lastmod = prev["lastmod"] if prev and prev.get("sig") == sig else today
        new_state[path] = {"sig": sig, "lastmod": lastmod}
        result[path] = max(lastmod, floors.get(path, lastmod))

    state_path.write_text(json.dumps(new_state, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return result
