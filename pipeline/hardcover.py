"""Hardcover (hardcover.app): reader ratings plus genres, moods and tags for books and comics.

Free API in beta; needs a personal token (HARDCOVER_TOKEN secret). Rate limit on the free plan:
60 requests a minute, 5,000 a day. The token is only ever used here, in the GitHub Action,
never in the browser (Hardcover asks that queries don't run in the browser).
https://docs.hardcover.app/api/getting-started/
"""
import json

from .util import log, session, similarity

ENDPOINT = "https://api.hardcover.app/v1/graphql"

SEARCH = """query($q: String!) { search(query: $q, query_type: "Book", per_page: 8, page: 1) { ids results } }"""
DETAIL = """query($id: Int!) { books_by_pk(id: $id) {
  id slug title pages release_year rating ratings_count users_count description
  image { url } cached_tags book_series { position series { name } } } }"""


class HardcoverError(Exception):
    pass


class Hardcover:
    def __init__(self, token: str):
        t = token.strip()
        self.auth = t if t.lower().startswith("bearer ") else "Bearer " + t
        self.calls = 0

    def _q(self, query, **variables):
        import time

        from .util import _last_call

        host = "api.hardcover.app"
        wait = 1.1 - (time.time() - _last_call.get(host, 0.0))  # stay under 60 a minute
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
        self.calls += 1
        try:
            r = session.post(ENDPOINT, json={"query": query, "variables": variables}, timeout=40,
                             headers={"authorization": self.auth, "Content-Type": "application/json",
                                      "User-Agent": "book-shelf/1.0 (personal reading list)"})
        except Exception as e:
            raise HardcoverError(f"network error: {e}")
        if r.status_code in (401, 403) and "capacity" not in r.text:
            raise HardcoverError(f"Hardcover rejected the token (HTTP {r.status_code}). Check the HARDCOVER_TOKEN secret; tokens expire.")
        if r.status_code == 429:
            time.sleep(30)
            raise HardcoverError("rate limited")
        if r.status_code != 200:
            raise HardcoverError(f"HTTP {r.status_code}")
        body = r.json()
        if body.get("errors"):
            raise HardcoverError("; ".join(str(e.get("message")) for e in body["errors"])[:200])
        return body.get("data") or {}

    def search(self, q):
        res = (self._q(SEARCH, q=q).get("search") or {})
        results = res.get("results")
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except json.JSONDecodeError:
                results = {}
        hits = (results or {}).get("hits") or []
        docs = [h.get("document") or {} for h in hits]
        ids = res.get("ids") or []
        for i, d in enumerate(docs):  # ids line up with hits; documents may or may not carry their own id
            if d.get("id") is None and i < len(ids):
                d["id"] = ids[i]
        return docs

    def best_match(self, title, author=None, isbns=()):
        """Search by title and author; accept only a close title (and author, when both are known)."""
        q = f"{title} {author}" if author else title
        best = None
        for d in self.search(q):
            s = similarity(title, d.get("title", ""))
            names = d.get("author_names") or []
            if author and names:
                a = max(similarity(author, n) for n in names)
                if a < 0.6:
                    continue
                s += 0.05
            if isbns and set(isbns) & set(d.get("isbns") or []):
                s += 0.2
            if s >= 0.88 and (best is None or s > best[0] or (s == best[0] and (d.get("ratings_count") or 0) > (best[1].get("ratings_count") or 0))):
                best = (s, d)
        return best[1] if best else None

    def detail(self, book_id):
        try:
            return (self._q(DETAIL, id=int(book_id)).get("books_by_pk")) or {}
        except (HardcoverError, ValueError) as e:
            log(f"    Hardcover detail {book_id}: {e}")
            return {}


def _tag_names(cached, key, limit):
    vals = (cached or {}).get(key) or []
    out = []
    for v in vals:
        name = v.get("tag") if isinstance(v, dict) else v
        if name and name not in out:
            out.append(str(name))
    return out[:limit]


def parse(doc, det):
    """Merge a search document and (optional) detail record into the fields this app uses."""
    cached = det.get("cached_tags")
    if isinstance(cached, str):
        try:
            cached = json.loads(cached)
        except json.JSONDecodeError:
            cached = {}
    rating = det.get("rating", doc.get("rating"))
    count = det.get("ratings_count", doc.get("ratings_count")) or 0
    series = None
    for bs in det.get("book_series") or []:
        name = ((bs or {}).get("series") or {}).get("name")
        if name:
            series = name
            break
    slug = det.get("slug") or doc.get("slug")
    return {
        "hc_id": det.get("id") or doc.get("id"),
        "hc_slug": slug,
        "hc_rating": round(float(rating), 2) if rating else None,
        "hc_votes": count,
        "hc_readers": det.get("users_count") or doc.get("users_count"),
        "genres": _tag_names(cached, "Genre", 8) or list(doc.get("genres") or [])[:8],
        "moods": _tag_names(cached, "Mood", 6) or list(doc.get("moods") or [])[:6],
        "tags": _tag_names(cached, "Tag", 10) or list(doc.get("tags") or [])[:10],
        "content_warnings": _tag_names(cached, "Content Warning", 6),
        "series": series or (list(doc.get("series_names") or []) or [None])[0],
        "pages": det.get("pages") or doc.get("pages"),
        "description": det.get("description") or doc.get("description"),
        "cover": ((det.get("image") or doc.get("image") or {}) or {}).get("url"),
    }


def check(token):
    try:
        Hardcover(token).search("the hobbit")
        return None
    except HardcoverError as e:
        log(f"!! Hardcover: {e}")
        return str(e)
