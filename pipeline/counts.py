"""How long a series is: volumes and chapters for manga, issues for comics. Used as the default total for
reading progress. Every function returns None instead of raising; a missing count only means you type it.

- MangaUpdates (free, no key): volume and chapter counts for ongoing manga, which AniList leaves blank
  until a series ends. https://api.mangaupdates.com
- Comic Vine (free key, optional COMICVINE_KEY secret): issue count of a comic series ("volume" in
  Comic Vine's terms). https://comicvine.gamespot.com/api/
"""
import re
import time

from .titles import base_title
from .util import _last_call, log, polite_get, session, similarity

MU = "https://api.mangaupdates.com/v1"
CV = "https://comicvine.gamespot.com/api"
UA = "book-shelf/1.0 (personal reading list)"


def _num(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def mangaupdates(titles, year=None):
    """{"mu_volumes", "mu_chapters", "mu_status", "mu_id"} for the series best matching any of `titles`."""
    best = None
    for t in [x for x in dict.fromkeys(titles) if x][:3]:
        wait = 1.2 - (time.time() - _last_call.get("api.mangaupdates.com", 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call["api.mangaupdates.com"] = time.time()
        try:
            r = session.post(f"{MU}/series/search", json={"search": t, "perpage": 8}, timeout=30,
                             headers={"User-Agent": UA, "Content-Type": "application/json"})
        except Exception as e:
            log(f"    MangaUpdates search {t}: {e}")
            return None
        if r.status_code != 200:
            log(f"    MangaUpdates search {t}: HTTP {r.status_code}")
            return None
        for hit in (r.json() or {}).get("results") or []:
            rec = hit.get("record") or {}
            if rec.get("type") in ("Novel", "Artbook"):
                continue
            s = similarity(t, re.sub(r"<[^>]+>", "", rec.get("title") or ""))
            s = max(s, similarity(t, re.sub(r"<[^>]+>", "", hit.get("hit_title") or "")))
            y = _num(rec.get("year"))
            if year and y and abs(y - int(year)) > 1:
                s -= 0.3
            if s >= 0.88 and (best is None or s > best[0]):
                best = (s, rec)
        if best:
            break
    if not best:
        return None
    sid = best[1].get("series_id")
    r = polite_get(f"{MU}/series/{sid}", host_delay=1.2, headers={"User-Agent": UA})
    if r is None or r.status_code != 200:
        return None
    d = r.json() or {}
    status = d.get("status") or ""
    m = re.search(r"(\d+)\s+Volumes?", status, re.I)
    return {"mu_id": sid, "mu_status": status.split("\n")[0][:80],
            "mu_volumes": int(m.group(1)) if m else None,
            "mu_chapters": _num(d.get("latest_chapter")) or None}


def comicvine(key, name, year=None, publisher=None):
    """{"cv_issues", "cv_id", "cv_name", "cv_year"} for the comic series named `name`, or None."""
    if not key or not name:
        return None
    q = base_title(name)
    if q in _CV_SEEN:  # every volume of a series asks the same question; ask Comic Vine once per run
        body = _CV_SEEN[q]
    else:
        body = _cv_search(key, q)
        _CV_SEEN[q] = body
    if body is None:
        return None
    return _cv_pick(body, q, year, publisher)


_CV_SEEN = {}


def _cv_search(key, q):
    r = polite_get(f"{CV}/search/", host_delay=1.5, headers={"User-Agent": UA}, params={
        "api_key": key, "format": "json", "resources": "volume", "query": q, "limit": 20,
        "field_list": "id,name,start_year,count_of_issues,publisher"})
    if r is None or r.status_code != 200:
        log(f"    Comic Vine {q}: {'no response' if r is None else 'HTTP ' + str(r.status_code)}")
        return None
    body = r.json() or {}
    if body.get("status_code") not in (1, None):
        log(f"    Comic Vine {q}: {body.get('error')}")
        return None
    return body


def _cv_pick(body, q, year, publisher):
    best = None
    for v in body.get("results") or []:
        s = similarity(q, v.get("name") or "")
        if s < 0.9:
            continue
        y = _num(v.get("start_year"))
        if year and y:
            if y > int(year) + 1:
                continue  # a series that started after this book came out isn't it
            s -= min(abs(int(year) - y), 10) * 0.02  # prefer the run that started closest to it
        if publisher and similarity(publisher, ((v.get("publisher") or {}).get("name")) or "") >= 0.8:
            s += 0.1
        n = _num(v.get("count_of_issues")) or 0
        if best is None or (s, n) > (best[0], best[2]):
            best = (s, v, n)
    if not best or not best[2]:
        return None
    v = best[1]
    return {"cv_issues": best[2], "cv_id": v.get("id"), "cv_name": v.get("name"), "cv_year": _num(v.get("start_year"))}
