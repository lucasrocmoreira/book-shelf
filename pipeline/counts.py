"""How long a manga series is, in volumes and chapters. Used as the default total for reading progress. Every function returns None instead of raising; a missing count only means you type it.

- MangaUpdates (free, no key): volume and chapter counts for ongoing manga, which AniList leaves blank
  until a series ends. https://api.mangaupdates.com
"""
import re
import time

from .util import _last_call, log, polite_get, session, similarity

MU = "https://api.mangaupdates.com/v1"
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
