"""Compile the shared search program into generated HTML, without reserializing it.

This explicit write-stage adapter keeps search independently testable and replaces
only the legacy LENS_SEARCH_JS fragment inside the shared navigation script. It
adds no browser request and changes no JSON-LD, URLs, offers, consent or menus.
Direct render_* callers receive templates; shipped HTML goes through write_file.
"""
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path


@lru_cache(maxsize=1)
def search_program() -> str:
    code = (Path(__file__).parent / "lens_search.js").read_text(encoding="utf-8")
    if "</script" in code.lower():
        raise ValueError("Search program must be safe to inline in HTML")
    return "\n" + code + "\n"


class _SearchRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_search = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.has_search |= "search-row" in (dict(attrs).get("class") or "").split()


def compile_search(content: str, legacy_program: str) -> str:
    """Fail closed on missing/duplicate search injection; leave other bytes intact."""
    if not legacy_program.strip():
        raise ValueError("Missing legacy search program marker")
    occurrences = content.count(legacy_program)
    if occurrences == 1:
        return content.replace(legacy_program, search_program(), 1)
    if occurrences > 1:
        raise ValueError("Duplicate search program in generated page")
    parser = _SearchRows()
    parser.feed(content)
    if parser.has_search:
        raise ValueError("Search form has no expected shared search program")
    return content
