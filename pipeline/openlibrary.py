"""Open Library: the backbone for books and comics. Free, no key.

Gives the work's canonical title, authors, first publication year, cover, median page count,
subjects, its own reader ratings, and (usually) the matching Goodreads book id.
https://openlibrary.org/developers/api
"""
import os
import re

from .titles import base_title, same_work, volume
from .util import log, polite_get, similarity

BASE = "https://openlibrary.org"
COVERS = "https://covers.openlibrary.org/b/id/{}-L.jpg"
FIELDS = ",".join([
    "key", "title", "subtitle", "author_name", "first_publish_year", "cover_i", "ratings_average", "ratings_count",
    "number_of_pages_median", "id_goodreads", "subject", "person", "place", "time", "want_to_read_count",
    "already_read_count", "isbn", "language", "series_name", "series_position", "edition_count",
])
UA = "book-shelf/1.0 (personal reading list; https://github.com/{})".format(os.environ.get("GITHUB_REPOSITORY", ""))

# Subjects on Open Library are crowd-sourced library headings; keep the readable ones.
_SUBJECT_JUNK = re.compile(
    r"(accessible book|protected daisy|in library|lending library|large type|translations? into|"
    r"open library|overdrive|^comics? (&|and) graphic novels|^graphic novels?,|nyt:|award:|reading level|juvenile literature|^fiction$|^general$|^literature$|"
    r"^english|^american|^roman|^novela|^ficci[oó]n|^comic books, strips|^graphic novels$|^fiction, general|long now)",
    re.I,
)


class OLError(Exception):
    pass


def _get(path, **params):
    r = polite_get(BASE + path, host_delay=1.0, params=params, headers={"User-Agent": UA, "Accept": "application/json"})
    if r is None:
        raise OLError("no response")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise OLError(f"HTTP {r.status_code}")
    return r.json()


def work_id(key: str):
    m = re.search(r"(OL\d+W)", key or "")
    return m.group(1) if m else None


def search(title, author=None, limit=10):
    # Volume titles are written many ways; search with the bare series title and let same_work() pick the volume.
    q = base_title(title) if volume(title) is not None else title
    params = {"title": q, "fields": FIELDS, "limit": 20 if q != title else limit}
    if author:
        params["author"] = author
    res = _get("/search.json", **params) or {}
    docs = res.get("docs") or []
    if not docs and author:  # an author spelled differently shouldn't hide the book
        res = _get("/search.json", title=q, fields=FIELDS, limit=params["limit"]) or {}
        docs = res.get("docs") or []
    return docs


def best_match(title, author=None, year=None):
    """Work id (OL...W) of the closest match, or None when nothing is a confident match."""
    scored = []
    for d in search(title, author)[:20]:
        s = max(same_work(title, d.get("title", ""), strict=True),
                same_work(title, f"{d.get('title', '')}: {d.get('subtitle', '')}", strict=True))
        if not s:
            continue
        if author:
            names = d.get("author_name") or []
            a = max([similarity(author, n) for n in names] or [0])
            s += 0.1 if a >= 0.8 else -0.15
        y = d.get("first_publish_year")
        if year and y and abs(int(y) - int(year)) > 2:
            s -= 0.1  # editions and translations shift the year, so only a nudge
        scored.append((s, d.get("edition_count") or 0, d))
    scored.sort(key=lambda x: (round(x[0], 2), x[1]), reverse=True)
    if scored and scored[0][0] >= 0.88:
        return work_id(scored[0][2].get("key"))
    return None


def clean_subjects(subjects, limit=12):
    out, seen = [], set()
    for s in subjects or []:
        s = re.sub(r"\s*\(.*?\)\s*", " ", str(s)).strip(" .,-")
        if not s or len(s) > 40 or _SUBJECT_JUNK.search(s):
            continue
        s = s[0].upper() + s[1:]
        k = s.lower()
        if k not in seen:
            seen.add(k)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _description(work):
    d = (work or {}).get("description")
    if isinstance(d, dict):
        d = d.get("value")
    if not isinstance(d, str):
        return None
    d = re.split(r"\n-{3,}|\n\(\[source\]|\r?\n\r?\n\*\*", d)[0]  # drop trailing "----" notes and source links
    return d.strip() or None


def work(olid):
    """Everything this app uses about one work, or None if Open Library doesn't know it."""
    res = _get("/search.json", q=f'key:"/works/{olid}"', fields=FIELDS, limit=1) or {}
    doc = (res.get("docs") or [{}])[0]
    w = _get(f"/works/{olid}.json") or {}
    if not doc and not w:
        return None
    if not doc.get("ratings_count"):
        r = _get(f"/works/{olid}/ratings.json") or {}
        summ = r.get("summary") or {}
        doc["ratings_average"], doc["ratings_count"] = summ.get("average"), summ.get("count")
    cover = doc.get("cover_i") or next((c for c in w.get("covers") or [] if isinstance(c, int) and c > 0), None)
    subjects = (doc.get("subject") or w.get("subjects") or [])
    avg, n = doc.get("ratings_average"), doc.get("ratings_count") or 0
    gr_ids = [str(g) for g in doc.get("id_goodreads") or [] if str(g).isdigit()]
    return {
        "ol": olid,
        "title": doc.get("title") or w.get("title"),
        "subtitle": doc.get("subtitle") or w.get("subtitle"),
        "authors": (doc.get("author_name") or [])[:4],
        "year": doc.get("first_publish_year"),
        "pages": doc.get("number_of_pages_median"),
        "cover": COVERS.format(cover) if cover else None,
        "description": _description(w),
        "subjects": clean_subjects(subjects),
        "characters": [p for p in (doc.get("person") or w.get("subject_people") or [])][:8],
        "places": [p for p in (doc.get("place") or w.get("subject_places") or [])][:6],
        "languages": (doc.get("language") or [])[:8],
        "isbns": (doc.get("isbn") or [])[:30],
        "goodreads_ids": gr_ids[:10],
        "series": (doc.get("series_name") or [None])[0],
        "ol_rating": round(float(avg), 2) if avg else None,
        "ol_votes": n,
        "ol_readers": (doc.get("want_to_read_count") or 0) + (doc.get("already_read_count") or 0),
    }


def check():
    try:
        _get("/search.json", q="the hobbit", fields="key", limit=1)
        return None
    except OLError as e:
        log(f"!! Open Library: {e}")
        return str(e)
