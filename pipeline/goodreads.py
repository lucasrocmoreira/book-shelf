"""Goodreads average rating, rating count and top genres, read from the public book page.

Goodreads closed its API in 2020, so this is best effort: every function returns None instead of
raising, and a layout change only stops the Goodreads column (the app shows a warning).
The exact book page comes from Open Library's Goodreads id when it has one; otherwise from a
title + author search whose first result has to match the title.
Bump PARSER_VERSION after fixing the parser so every book is rechecked.
"""
import html as htmllib
import json
import re

from .titles import GR_SERIES, same_work, volume
from .util import log, polite_get

PARSER_VERSION = 2
BASE = "https://www.goodreads.com"
DELAY = 2.5


def _fetch(url):
    r = polite_get(url, host_delay=DELAY)
    if r is None or r.status_code != 200:
        return None, None
    return r.text, r.url


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def parse_book(page):
    """{"gr_rating" 0-5, "gr_votes", "gr_genres", "gr_title"} from a /book/show/ page."""
    rating = votes = None
    genres, title = [], None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            data = {}
        best_votes = -1
        for node in _walk(data):
            st = node.get("stats")
            if isinstance(st, dict) and st.get("averageRating") is not None:
                n = st.get("ratingsCount") or 0
                # Work-level stats (all editions) have the most ratings; edition stats are a subset.
                if n > best_votes:
                    best_votes, rating, votes = n, st.get("averageRating"), n
            if node.get("__typename") == "Book" and node.get("title") and not title:
                title = node.get("title")
            bg = node.get("bookGenres")
            for g in bg if isinstance(bg, list) else []:
                name = ((g or {}).get("genre") or {}).get("name")
                if name and name not in genres:
                    genres.append(name)
    if rating is None:
        for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
            try:
                ld = json.loads(blob)
            except json.JSONDecodeError:
                continue
            agg = ld.get("aggregateRating") if isinstance(ld, dict) else None
            if isinstance(agg, dict) and agg.get("ratingValue") is not None:
                rating, votes = agg.get("ratingValue"), agg.get("ratingCount")
                title = title or ld.get("name")
                break
    if rating is None:
        m = re.search(r'class="RatingStatistics__rating"[^>]*>\s*([0-5]\.\d{1,2})', page)
        if m:
            rating = m.group(1)
            v = re.search(r'data-testid="ratingsCount"[^>]*>\s*([\d,]+)', page)
            votes = int(v.group(1).replace(",", "")) if v else None
    if not genres:
        genres = [htmllib.unescape(g) for g in re.findall(r'/genres/[^"]+"[^>]*>\s*<span class="Button__labelItem">([^<]+)<', page)]
    if not title:
        og = re.search(r'<meta property="og:title" content="([^"]+)"', page)
        title = htmllib.unescape(og.group(1)) if og else None
    try:
        rating = round(float(rating), 2) if rating is not None else None
    except (TypeError, ValueError):
        rating = None
    if rating is not None and not 0 < rating <= 5:
        rating = None
    try:
        votes = int(votes) if votes is not None else None
    except (TypeError, ValueError):
        votes = None
    return {"gr_rating": rating, "gr_votes": votes, "gr_genres": [g for g in genres if g][:8], "gr_title": title}


def _search(title, author):
    """Goodreads book id from the search page: the first of the top five results whose title is this work."""
    q = f"{title} {author or ''}".strip()
    page, _ = _fetch(f"{BASE}/search?q={_quote(q)}&search_type=books")
    if not page:
        return None
    hits = re.finditer(r'<a class="bookTitle"[^>]*href="/book/show/(\d+)[^"]*"[^>]*>\s*<span[^>]*>([^<]+)</span>', page)
    for n, m in enumerate(hits):
        if n >= 5:
            break
        if same_work(title, htmllib.unescape(m.group(2))):
            return m.group(1)
    return None


def _quote(s):
    from urllib.parse import quote_plus

    return quote_plus(s)


def lookup(ids=(), isbns=(), title=None, author=None):
    """{"gr_rating", "gr_votes", "gr_genres", "gr_id", "gr_guessed", "gr_series", "gr_series_pos"} or None.
    Tries, in order: Open Library's Goodreads ids, the edition's ISBN (Goodreads redirects /book/isbn/<isbn>
    to the book), then a title + author search."""
    tries = [(f"{BASE}/book/show/{g}", False) for g in list(ids)[:1]]
    tries += [(f"{BASE}/book/isbn/{i}", False) for i in _isbn_order(isbns)[:2]]
    if title:
        tries.append((None, True))
    for url, guessed in tries:
        if url is None:
            gid = _search(title, author)
            if not gid:
                continue
            url = f"{BASE}/book/show/{gid}"
        page, final = _fetch(url)
        if not page or "/book/show/" not in (final or url):
            continue
        out = parse_book(page)
        if out["gr_rating"] is None:
            if not getattr(lookup, "_warned", False):
                lookup._warned = True
                log(f"    Goodreads: page loaded but no rating found at {final or url} (layout may have changed)")
            continue
        if guessed and out.get("gr_title") and title and not same_work(title, out["gr_title"], 0.8):
            log(f"    Goodreads: search result '{out['gr_title']}' doesn't look like {title}; skipped")
            continue
        m = re.search(r"/book/show/([\w.-]+)", final or url)
        out["gr_id"] = m.group(1) if m else None
        out["gr_guessed"] = guessed
        t = out.get("gr_title") or ""
        sm = GR_SERIES.search(t)
        out["gr_series"], out["gr_series_pos"] = (sm.group(1).strip(), volume(t)) if sm else (None, None)
        return out
    return None


def _isbn_order(isbns):
    """ISBN-13s first (they redirect more reliably), each once."""
    seen, out = set(), []
    for i in sorted((str(x).replace("-", "") for x in isbns or []), key=lambda x: len(x) != 13):
        if i not in seen and re.fullmatch(r"\d{9}[\dX]|\d{13}", i):
            seen.add(i)
            out.append(i)
    return out
