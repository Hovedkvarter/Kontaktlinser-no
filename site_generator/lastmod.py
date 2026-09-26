"""
lastmod.py

Ærlig <lastmod> i sitemap: en side får ny lastmod KUN når innholdet faktisk har
endret seg, ikke ved hvert bygg. Før 2026-09-26 sto alle URL-er på "i dag" ved
hver kjøring (også guider som ikke var rørt siden august) -- Google slutter å
stole på lastmod når den alltid er dagens dato, og en dato som ikke stemmer er
i praksis misvisende data til søkemotorene.

Guider bruker sin redaksjonelle "updated"-dato (samme dato som vises i
byline-en og i Article-schemaet). Alle andre sider: signatur (hash) av den
ferdige HTML-en, med bevisst flyktige deler fjernet (relativ "sist oppdatert
for N timer siden"-tekst, prisutviklingsgrafen som får ett nytt punkt per dag).
Endrer signaturen seg (ny pris, ny tekst, ny mal) settes lastmod til dagens
dato; ellers beholdes forrige dato fra lastmod_state.json, som CI committer
tilbake til repoet på samme måte som price_history.json.
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
    state_path: Path = STATE_PATH,
) -> dict[str, str]:
    """path -> lastmod (YYYY-MM-DD). `fixed` gir sider med en redaksjonell dato
    (guider) som ALLTID brukes som den er. Oppdaterer og skriver state-filen.
    Første gang en side sees (ingen state) settes dagens dato -- vi vet ikke
    når den sist endret seg, og det er ærligere enn å finne på en eldre dato."""
    fixed = fixed or {}
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
        result[path] = lastmod
        new_state[path] = {"sig": sig, "lastmod": lastmod}

    state_path.write_text(json.dumps(new_state, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return result
