"""Book details by ISBN from BrasilAPI (free, no key), for editions Open Library doesn't have.

BrasilAPI asks, in order, the Brazilian ISBN agency (CBL), Mercado Editorial, Open Library and Google Books,
so it knows nearly every book published in Brazil. https://brasilapi.com.br/docs#tag/ISBN
"""
import re

from .util import log, polite_get

BASE = "https://brasilapi.com.br/api/isbn/v1"


def isbn13(isbn):
    d = re.sub(r"[^0-9Xx]", "", str(isbn or "")).upper()
    if len(d) == 13:
        return d
    if len(d) == 10:
        core = "978" + d[:9]
        s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(core))
        return core + str((10 - s % 10) % 10)
    return None


def lookup(isbn):
    """{"title", "subtitle", "authors", "year", "pages", "description", "subjects", "cover", "publisher"} or None."""
    code = isbn13(isbn)
    if not code:
        return None
    r = polite_get(f"{BASE}/{code}", host_delay=1.0, headers={"Accept": "application/json"})
    if r is None or r.status_code != 200:
        if r is not None and r.status_code != 404:
            log(f"    BrasilAPI {code}: HTTP {r.status_code}")
        return None
    d = r.json() or {}
    if not d.get("title"):
        return None
    return {
        "title": d.get("title"),
        "subtitle": d.get("subtitle"),
        "authors": [a for a in d.get("authors") or [] if a][:4],
        "year": d.get("year"),
        "pages": d.get("page_count"),
        "description": d.get("synopsis"),
        "subjects": [s for s in d.get("subjects") or [] if s][:8],
        "cover": d.get("cover_url"),
        "publisher": d.get("publisher"),
        "provider": d.get("provider"),
    }
