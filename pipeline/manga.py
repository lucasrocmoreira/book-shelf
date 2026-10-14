"""Manga, manhwa and manhua: AniList for details and its score, MyAnimeList (through Jikan) for the
MAL score, rank, member count, themes and demographic. Both free, no key.

AniList: https://docs.anilist.co (90 requests a minute, currently cut to 30 while degraded)
Jikan, an unofficial MyAnimeList API: https://docs.api.jikan.moe (60 a minute)
"""
import re
import time

from .util import _last_call, log, polite_get, session, similarity

ANILIST = "https://graphql.anilist.co"
JIKAN = "https://api.jikan.moe/v4"

FIELDS = """id idMal siteUrl title { romaji english native } synonyms format status countryOfOrigin
  startDate { year } endDate { year } volumes chapters averageScore meanScore popularity favourites
  genres tags { name rank isMediaSpoiler isGeneralSpoiler category }
  description(asHtml: false) coverImage { extraLarge large }
  staff(perPage: 8, sort: [RELEVANCE]) { edges { role node { name { full } } } }"""
DETAIL = "query($id: Int) { Media(id: $id, type: MANGA) { " + FIELDS + " } }"
SEARCH = """query($q: String) { Page(perPage: 10) { media(search: $q, type: MANGA, sort: [SEARCH_MATCH]) {
  id title { romaji english native } synonyms startDate { year } format popularity } } }"""

STATUS = {"FINISHED": "Finished", "RELEASING": "Ongoing", "NOT_YET_RELEASED": "Upcoming",
          "CANCELLED": "Canceled", "HIATUS": "On hiatus"}
ORIGIN = {"JP": "Manga", "KR": "Manhwa", "CN": "Manhua", "TW": "Manhua"}
FORMAT = {"NOVEL": "Light novel", "ONE_SHOT": "One-shot", "MANGA": None}


class AniListError(Exception):
    pass


def _anilist(query, **variables):
    wait = 2.2 - (time.time() - _last_call.get("graphql.anilist.co", 0.0))  # under 30 a minute
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        _last_call["graphql.anilist.co"] = time.time()
        try:
            r = session.post(ANILIST, json={"query": query, "variables": variables}, timeout=40,
                             headers={"Content-Type": "application/json", "Accept": "application/json"})
        except Exception as e:
            raise AniListError(f"network error: {e}")
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After") or 60) + 1)
            continue
        if r.status_code == 404:
            return {}
        if r.status_code != 200:
            raise AniListError(f"HTTP {r.status_code}")
        body = r.json()
        if body.get("errors") and not body.get("data"):
            raise AniListError("; ".join(str(e.get("message")) for e in body["errors"])[:200])
        return body.get("data") or {}
    raise AniListError("rate limited")


def _names(t):
    return [x for x in [(t or {}).get("english"), (t or {}).get("romaji"), (t or {}).get("native")] if x]


def best_match(title, year=None):
    hits = ((_anilist(SEARCH, q=title).get("Page") or {}).get("media")) or []
    scored = []
    for h in hits:
        s = max([similarity(title, n) for n in _names(h.get("title")) + (h.get("synonyms") or [])] or [0])
        y = (h.get("startDate") or {}).get("year")
        # The year you know is often the English release, years after the Japanese one; only a series that
        # started *after* that year is clearly a different one.
        if year and y and int(y) > int(year) + 1:
            s -= 0.3
        if h.get("format") == "NOVEL":
            s -= 0.05  # prefer the manga over its light novel when both share the title
        scored.append((s, h.get("popularity") or 0, h))
    scored.sort(key=lambda x: (round(x[0], 2), x[1]), reverse=True)
    if scored and scored[0][0] >= 0.88:
        return scored[0][2]["id"]
    return None


def _clean_desc(d):
    if not d:
        return None
    d = re.sub(r"<br\s*/?>", "\n", d)
    d = re.sub(r"<[^>]+>", "", d)
    d = re.split(r"\n\s*\(Source:|\(Source:|\n\s*Note:", d)[0]
    return re.sub(r"\n{3,}", "\n\n", d).strip() or None


def anilist(al_id):
    m = (_anilist(DETAIL, id=int(al_id)).get("Media")) or None
    if not m:
        return None
    t = m.get("title") or {}
    staff_story, staff_art = [], []
    for e in ((m.get("staff") or {}).get("edges")) or []:
        role, name = (e.get("role") or ""), (((e.get("node") or {}).get("name") or {}).get("full"))
        if not name:
            continue
        if re.search(r"story", role, re.I) and name not in staff_story:
            staff_story.append(name)
        if re.search(r"\bart\b|illustrat", role, re.I) and name not in staff_art:
            staff_art.append(name)
    demo = [x["name"] for x in m.get("tags") or [] if x.get("name") in ("Shounen", "Seinen", "Shoujo", "Josei", "Kids")]
    tags = [x["name"] for x in sorted(m.get("tags") or [], key=lambda x: -(x.get("rank") or 0))
            if (x.get("rank") or 0) >= 60 and not x.get("isMediaSpoiler") and not x.get("isGeneralSpoiler")
            and x.get("category") not in ("Sexual Content",) and x["name"] not in demo]
    status = STATUS.get(m.get("status"), m.get("status"))
    fmt = m.get("format")
    origin = ORIGIN.get(m.get("countryOfOrigin"), "Comics")
    cover = (m.get("coverImage") or {})
    return {
        "anilist": m["id"],
        "mal_id": m.get("idMal"),
        "title": t.get("english") or t.get("romaji") or t.get("native"),
        "original_title": t.get("romaji") if t.get("english") and t.get("romaji") != t.get("english") else None,
        "native_title": t.get("native"),
        "subtype": FORMAT.get(fmt) or (origin if fmt != "MANGA" or origin != "Manga" else "Manga"),
        "origin": m.get("countryOfOrigin"),
        "status": status,
        "year": (m.get("startDate") or {}).get("year"),
        "end_year": (m.get("endDate") or {}).get("year") if status in ("Finished", "Canceled") else None,
        "volumes": m.get("volumes"),
        "chapters": m.get("chapters"),
        "authors": staff_story or staff_art,
        "artists": [a for a in staff_art if a not in staff_story],
        "genres": m.get("genres") or [],
        "tags": tags[:12],
        "demographics": demo,
        "description": _clean_desc(m.get("description")),
        "cover": cover.get("extraLarge") or cover.get("large"),
        "anilist_score": m.get("averageScore") or m.get("meanScore"),
        "anilist_popularity": m.get("popularity"),
        "anilist_url": m.get("siteUrl") or f"https://anilist.co/manga/{m['id']}",
    }


def mal(mal_id):
    """MyAnimeList score (0-10), voters, rank, members, themes, demographic. None on failure.
    Jikan first; if it's down or blocks the request, the public MyAnimeList page."""
    if not mal_id:
        return None
    return _jikan(mal_id) or _mal_page(mal_id)


def _jikan(mal_id):
    r = polite_get(f"{JIKAN}/manga/{int(mal_id)}/full", host_delay=1.2)
    if r is None or r.status_code != 200:
        log(f"    Jikan {mal_id}: {'no response' if r is None else 'HTTP ' + str(r.status_code)}; trying the MyAnimeList page")
        return None
    try:
        d = (r.json() or {}).get("data") or {}
    except ValueError:
        return None
    if d.get("score") is None and not d.get("members"):
        return None
    names = lambda key: [x.get("name") for x in d.get(key) or [] if x.get("name")]
    return {
        "mal_score": d.get("score"),
        "mal_votes": d.get("scored_by"),
        "mal_rank": d.get("rank"),
        "mal_members": d.get("members"),
        "mal_themes": names("themes"),
        "mal_genres": names("genres"),
        "demographics": names("demographics"),
        "serialization": names("serializations")[:2],
        "mal_url": d.get("url"),
        "volumes": d.get("volumes"),
    }


def _num(text):
    try:
        return int(re.sub(r"[^\d]", "", text)) if text and re.search(r"\d", text) else None
    except ValueError:
        return None


def _mal_page(mal_id):
    """Best effort read of https://myanimelist.net/manga/<id> (no API key needed)."""
    url = f"https://myanimelist.net/manga/{int(mal_id)}"
    r = polite_get(url, host_delay=3.0)
    if r is None or r.status_code != 200:
        log(f"    MyAnimeList page {mal_id}: {'no response' if r is None else 'HTTP ' + str(r.status_code)}")
        return None
    html = r.text
    m = re.search(r'itemprop="ratingValue"[^>]*>\s*([\d.]+)', html)
    score = float(m.group(1)) if m else None
    m = re.search(r'itemprop="ratingCount"[^>]*>\s*([\d,]+)', html)
    votes = _num(m.group(1)) if m else None
    m = re.search(r"Ranked:</span>\s*#?([\d,]+)", html)
    rank = _num(m.group(1)) if m else None
    m = re.search(r"Members:</span>\s*([\d,]+)", html)
    members = _num(m.group(1)) if m else None

    def side(label):
        m = re.search(r'<span class="dark_text">' + label + r':</span>(.*?)</div>', html, re.S)
        return re.findall(r'title="([^"]+)"', m.group(1)) if m else []

    if score is None and members is None:
        return None
    return {
        "mal_score": score, "mal_votes": votes, "mal_rank": rank, "mal_members": members,
        "mal_themes": side("Themes?"), "mal_genres": side("Genres?"), "demographics": side("Demographic"),
        "serialization": side("Serialization")[:2], "mal_url": url, "volumes": None,
    }


def check():
    try:
        _anilist("query { Media(id: 30002, type: MANGA) { id } }")
        return None
    except AniListError as e:
        log(f"!! AniList: {e}")
        return str(e)
