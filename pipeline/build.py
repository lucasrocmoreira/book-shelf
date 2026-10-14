"""Build: read your shelf, fetch details and ratings, write site/data.json.

Run locally:  python -m pipeline.build          (HARDCOVER_TOKEN optional)
Environment:  HARDCOVER_TOKEN, MAX_LOOKUPS (default 150 per source per run).
"""
import os
import sys
import traceback

from . import goodreads, manga, openlibrary, shelf, titles
from .hardcover import Hardcover, HardcoverError, check as hc_check
from .util import CACHE_DIR, SITE_DIR, days_since, load_json, log, norm, now_iso, save_json

MAX_LOOKUPS = int(os.environ.get("MAX_LOOKUPS", "150"))
UNMATCHED_RETRY_DAYS = 3
PAGES_PER_VOLUME = 190  # a typical tankōbon; used only to compare series length with books
SCORES_VERSION = 2

# Shelf names that only repeat the kind or say nothing about the book.
GENRE_JUNK = {
    "fiction", "novels", "novel", "adult", "adult fiction", "literature", "book club", "audiobook", "audiobooks",
    "comics", "comic", "manga", "graphic novels", "graphic novel", "graphic novels comics", "comic book",
    "comics manga", "manhwa", "manhua", "ebooks", "kindle", "unfinished", "school", "abandoned", "owned",
}
MIN_VOTES = {"goodreads": 50, "hardcover": 10, "openlibrary": 10}


def env(name):
    v = os.environ.get(name, "").strip()
    return v or None


def ref_of(key, e):
    """The source record an entry points at: 'ol:OL...W' for books and comics, 'al:<id>' for manga."""
    if shelf.kind_of(e) == "manga":
        return f"al:{e['anilist']}" if str(e.get("anilist", "")).isdigit() else None
    olid = openlibrary.work_id(str(e.get("ol") or ""))
    return f"ol:{olid}" if olid else None


def resolve(sh, matches, status):
    refs = {}
    for key, e in sh["items"].items():
        r = ref_of(key, e)
        if r:
            refs[key] = r
            continue
        m = matches.get(key) or {}
        if m.get("ref"):
            refs[key] = m["ref"]
            continue
        if days_since(m.get("checked")) < UNMATCHED_RETRY_DAYS:
            continue
        title, author, year = e.get("title", ""), e.get("author"), e.get("year")
        try:
            if shelf.kind_of(e) == "manga":
                found = manga.best_match(title, year)
                ref = f"al:{found}" if found else None
            else:
                found = openlibrary.best_match(title, author, year)
                ref = f"ol:{found}" if found else None
        except Exception as err:
            log(f"  search failed for {title}: {err}")
            continue
        matches[key] = {"ref": ref, "title": title, "checked": now_iso()}
        log(f"  matched '{title}' -> {ref or 'no confident match'}")
        if ref:
            refs[key] = ref
    return refs


def detail_due(rec):
    if not rec:
        return True
    if rec.get("status") in ("Ongoing", "Upcoming", "On hiatus"):
        return days_since(rec.get("fetched")) >= 7
    return days_since(rec.get("fetched")) >= 30


def fetch_details(refs, cache, status):
    todo = [r for r in sorted(set(refs.values())) if detail_due(cache.get(r))][: MAX_LOOKUPS * 2]
    ok = {"ol": 0, "al": 0}
    fail = {"ol": 0, "al": 0}
    for ref in todo:
        src, ident = ref.split(":", 1)
        try:
            rec = openlibrary.work(ident) if src == "ol" else manga.anilist(ident)
        except Exception as e:
            fail[src] += 1
            log(f"  {ref}: {type(e).__name__}: {e}")
            continue
        if rec:
            cache[ref] = {**rec, "fetched": now_iso()}
            ok[src] += 1
    status["openlibrary"] = "ok" if not fail["ol"] else f"{fail['ol']} books failed to refresh; showing saved details"
    status["anilist"] = "ok" if not fail["al"] else f"{fail['al']} series failed to refresh; showing saved details"
    log(f"Details: {ok['ol']} from Open Library, {ok['al']} from AniList")


def _keep(old, prefix_keys):
    return {k: v for k, v in old.items() if any(k.startswith(p) for p in prefix_keys)}


def refresh_scores(refs, shelf_titles, details, sc, hc, status):
    """Goodreads + Hardcover for books and comics, MyAnimeList for manga. Cached and rechecked monthly
    (weekly for ongoing series), stalest first, at most MAX_LOOKUPS per run. A source that fails this run
    keeps its last known values and is retried on the next run."""
    todo = []
    for ref in set(refs.values()):
        rec = details.get(ref)
        if not rec:
            continue
        c = sc.get(ref) or {}
        due = 7 if rec.get("status") in ("Ongoing", "On hiatus") else 30
        stale_version = c.get("v") != [SCORES_VERSION, goodreads.PARSER_VERSION]
        hc_new = bool(hc) and ref.startswith("ol:") and not c.get("hc_tried")  # token added after the first runs
        if stale_version or days_since(c.get("checked")) >= due or hc_new or c.get("retry"):
            todo.append((days_since(c.get("checked")), ref))
    todo.sort(key=lambda x: -x[0])
    todo = [r for _, r in todo[:MAX_LOOKUPS]]
    if not todo:
        return
    log(f"Scores: checking {len(todo)} titles")
    gr_hits = gr_tries = hc_fail = mal_hits = mal_tries = 0
    for ref in todo:
        rec = details[ref]
        old = sc.get(ref) or {}
        entry = {"checked": now_iso(), "v": [SCORES_VERSION, goodreads.PARSER_VERSION]}
        # Your own title wins when it says more (e.g. "Saga: Volume Two" where Open Library just says "Saga").
        mine = shelf_titles.get(ref) or ""
        title = mine if titles.volume(mine) is not None or not rec.get("title") else rec["title"]
        author = next((a for a in rec.get("authors") or [] if not a.startswith("[")), None)
        isbns = rec.get("isbns") or []
        try:
            if ref.startswith("al:"):
                mal_tries += 1
                m = manga.mal(rec.get("mal_id"))
                if m:
                    entry.update(m)
                    mal_hits += 1
                elif rec.get("mal_id"):
                    entry.update(_keep(old, ("mal_", "demographics", "serialization")))
                    entry["retry"] = True
            else:
                gr_tries += 1
                g = goodreads.lookup(rec.get("goodreads_ids") or [], isbns, title, author)
                if g:
                    entry.update(g)
                    gr_hits += 1
                elif old.get("gr_rating") is not None:  # a blocked request shouldn't erase a known score
                    entry.update(_keep(old, ("gr_",)))
                if hc:
                    entry["hc_tried"] = True
                    try:
                        from .hardcover import parse

                        book_id = hc.by_isbn(isbns) if isbns else None
                        doc = {"id": book_id} if book_id else hc.best_match(title, author, isbns)
                        if doc:
                            det = hc.detail(doc.get("id")) if doc.get("id") else {}
                            entry.update(parse(doc, det))
                        elif old.get("hc_rating") is not None:
                            entry.update(_keep(old, ("hc_", "genres", "moods", "tags", "content_warnings", "series", "pages", "description", "cover")))
                    except HardcoverError as e:
                        hc_fail += 1
                        entry.update(_keep(old, ("hc_", "genres", "moods", "tags", "content_warnings", "series", "pages", "description", "cover")))
                        entry["retry"] = True
                        log(f"  Hardcover, {title}: {e}")
                        if "token" in str(e):
                            status["hardcover"] = str(e)
                            hc = None
        except Exception as e:  # a parser bug must not sink the run
            log(f"  {title}: {type(e).__name__}: {e}")
            continue
        sc[ref] = entry
        log(f"  {title}: GR {entry.get('gr_rating')}, HC {entry.get('hc_rating')}, MAL {entry.get('mal_score')}")
    if gr_tries >= 3:
        status["goodreads"] = "ok" if gr_hits else "no ratings found this run (Goodreads may be blocking or changed its pages)"
    if hc and "hardcover" not in status:
        status["hardcover"] = "ok" if hc_fail < 3 else f"{hc_fail} lookups failed this run"
    if mal_tries:
        status["myanimelist"] = "ok" if mal_hits else "no scores this run (Jikan and the MyAnimeList page both failed); retrying next run"


def _merge(*lists, junk=(), limit=12):
    out, seen = [], set()
    for lst in lists:
        for v in lst or []:
            v = str(v).strip()
            k = norm(v)
            if not v or k in seen or k in junk:
                continue
            seen.add(k)
            out.append(v[0].upper() + v[1:])
    return out[:limit]


def _score5(v, n, src):
    return round(float(v) * 20) if v is not None and (n or 0) >= MIN_VOTES[src] else None


def _decade(y):
    return f"{y // 10 * 10}s" if isinstance(y, int) else None


def series_of(kind, e, rec, c):
    """(series name, volume number) for a book or comic. Your own title decides for comics, so every
    volume you add as "Saga: Volume N" lands in the same series; then Goodreads, then Hardcover.
    A "series" / "volume" field you add to the entry in config/shelf.json overrides all of this."""
    if e.get("series"):
        return e["series"], e.get("volume") or titles.volume(e.get("title"))
    mine, theirs = e.get("title") or "", rec.get("title") or ""
    pos = e.get("volume") or titles.volume(mine) or c.get("gr_series_pos") or titles.volume(theirs)
    if kind == "comic":
        name = titles.series_name(mine) or c.get("gr_series") or c.get("series") or titles.series_name(theirs)
    else:
        name = c.get("series") or c.get("gr_series") or rec.get("series")
    return name, pos


def assemble(sh, refs, details, sc):
    out = []
    for key, e in sh["items"].items():
        kind = shelf.kind_of(e)
        base = {
            "key": key, "kind": kind, "added": e.get("added"),
            "reading": e.get("status") if e.get("status") in ("unread", "reading", "read") else "unread",
            "read_on": e.get("read_on"), "interest": e.get("interest") or 0, "rating": e.get("rating") or 0,
            "owned": e.get("owned") or "",
        }
        ref = refs.get(key)
        rec = details.get(ref) if ref else None
        if not rec:
            item = {**base, "title": e.get("title") or key, "authors": [e["author"]] if e.get("author") else [],
                    "year": e.get("year"), "cover": e.get("cover"), "matched": False, "scores": {}, "links": {}}
            item["series"], item["series_pos"] = series_of(kind, e, {}, {})
            out.append(item)
            continue
        c = sc.get(ref) or {}
        item = {**base, "matched": True, "ref": ref}
        if kind == "manga":
            vols = rec.get("volumes") or c.get("volumes")
            item.update({
                "title": rec.get("title"), "original_title": rec.get("original_title"), "native_title": rec.get("native_title"),
                "subtype": rec.get("subtype"), "authors": rec.get("authors") or [], "artists": rec.get("artists") or [],
                "year": rec.get("year"), "end_year": rec.get("end_year"), "pub_status": rec.get("status"),
                "volumes": vols, "chapters": rec.get("chapters"),
                "pages": vols * PAGES_PER_VOLUME if vols else None, "pages_estimated": bool(vols),
                "series": rec.get("title"),
                "genres": _merge(rec.get("genres"), c.get("mal_genres"), junk=GENRE_JUNK),
                "themes": _merge(c.get("mal_themes"), rec.get("tags"), limit=14),
                "moods": [], "demographics": c.get("demographics") or rec.get("demographics") or [],
                "magazine": c.get("serialization") or [],
                "description": rec.get("description"), "cover": rec.get("cover") or e.get("cover"),
                "popularity": c.get("mal_members") or rec.get("anilist_popularity"),
                "mal_rank": c.get("mal_rank"), "mal_score": c.get("mal_score"), "mal_votes": c.get("mal_votes"),
                "anilist_popularity": rec.get("anilist_popularity"),
            })
            item["scores"] = {
                "anilist": rec.get("anilist_score"),
                "mal": round(c["mal_score"] * 10) if c.get("mal_score") else None,
            }
            links = {"anilist": rec.get("anilist_url")}
            if c.get("mal_url") or rec.get("mal_id"):
                links["mal"] = c.get("mal_url") or f"https://myanimelist.net/manga/{rec['mal_id']}"
        else:
            hc_pages = c.get("pages")
            item.update({
                # Keep your title when it names the volume and the database's doesn't ("Saga: Volume Two" vs "Saga").
                "title": e.get("title") if titles.volume(e.get("title")) is not None and titles.volume(rec.get("title")) is None
                         else (rec.get("title") or e.get("title")),
                "subtitle": rec.get("subtitle"),
                "subtype": "Comics" if kind == "comic" else "Book",
                "authors": rec.get("authors") or ([e["author"]] if e.get("author") else []), "artists": [],
                "year": rec.get("year") or e.get("year"), "end_year": None, "pub_status": None,
                "pages": rec.get("pages") or hc_pages, "pages_estimated": False,
                "volumes": None, "chapters": None,
                "series": None,
                "genres": _merge(c.get("genres"), c.get("gr_genres"), junk=GENRE_JUNK),
                "themes": _merge(c.get("tags"), rec.get("subjects") if not c.get("tags") else [], limit=12),
                "moods": c.get("moods") or [], "demographics": [], "magazine": [],
                "characters": rec.get("characters") or [], "places": rec.get("places") or [],
                "content_warnings": c.get("content_warnings") or [],
                "description": c.get("description") or rec.get("description"),
                "cover": e.get("cover") or rec.get("cover") or c.get("cover"),
                "popularity": c.get("gr_votes") or c.get("hc_readers") or rec.get("ol_readers") or None,
                "gr_rating": c.get("gr_rating"), "gr_votes": c.get("gr_votes"),
                "hc_rating": c.get("hc_rating"), "hc_votes": c.get("hc_votes"),
                "ol_rating": rec.get("ol_rating"), "ol_votes": rec.get("ol_votes"),
                "gr_guessed": bool(c.get("gr_guessed")),
            })
            if not item["genres"] and rec.get("subjects"):
                item["genres"] = _merge(rec["subjects"], junk=GENRE_JUNK, limit=5)
            item["scores"] = {
                "goodreads": _score5(c.get("gr_rating"), c.get("gr_votes"), "goodreads"),
                "hardcover": _score5(c.get("hc_rating"), c.get("hc_votes"), "hardcover"),
                "openlibrary": _score5(rec.get("ol_rating"), rec.get("ol_votes"), "openlibrary"),
            }
            links = {"openlibrary": f"https://openlibrary.org/works/{rec['ol']}"}
            if c.get("gr_id"):
                links["goodreads"] = f"https://www.goodreads.com/book/show/{c['gr_id']}"
            if c.get("hc_slug"):
                links["hardcover"] = f"https://hardcover.app/books/{c['hc_slug']}"
        if kind != "manga":
            item["series"], item["series_pos"] = series_of(kind, e, rec, c)
            item["authors"] = [a for a in item["authors"] if not str(a).startswith("[")]
        item["decade"] = _decade(item.get("year"))
        item["links"] = {k: v for k, v in links.items() if v}
        out.append(item)
    return out


def main():
    status = {}
    hc = None
    token = env("HARDCOVER_TOKEN")
    if token:
        err = hc_check(token)
        if err:
            status["hardcover"] = err
        else:
            hc = Hardcover(token)
    else:
        status["hardcover"] = "not configured (optional): add the HARDCOVER_TOKEN secret for Hardcover ratings, moods and tags"

    sh = shelf.load()
    log(f"Shelf: {len(sh['items'])} items")
    matches = load_json(CACHE_DIR / "matches.json", {})
    details = load_json(CACHE_DIR / "details.json", {})
    sc = load_json(CACHE_DIR / "scores.json", {})

    refs = resolve(sh, matches, status)
    fetch_details(refs, details, status)
    shelf_titles = {refs[k]: e.get("title") for k, e in sh["items"].items() if k in refs}
    refresh_scores(refs, shelf_titles, details, sc, hc, status)
    items = assemble(sh, refs, details, sc)

    live = set(refs.values())
    details = {k: v for k, v in details.items() if k in live}
    sc = {k: v for k, v in sc.items() if k in live}
    matches = {k: v for k, v in matches.items() if k in sh["items"]}
    save_json(CACHE_DIR / "matches.json", matches)
    save_json(CACHE_DIR / "details.json", details)
    save_json(CACHE_DIR / "scores.json", sc)
    if not any(i.get("kind") == "manga" for i in items):
        status.pop("anilist", None)
    if not any(i.get("kind") != "manga" for i in items):
        for k in ("openlibrary", "goodreads", "hardcover"):
            status.pop(k, None)
    save_json(SITE_DIR / "data.json", {"generated": now_iso(), "status": status, "items": items}, pretty=False)
    log(f"Wrote {len(items)} items. Status: {status}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
