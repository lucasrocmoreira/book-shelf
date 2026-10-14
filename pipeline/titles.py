"""Title helpers shared by the matchers: volume numbers, series names and volume-aware comparison.

Comic and manga collections are titled every which way ("Saga: Volume One", "Saga, Vol. 1",
"Saga, Volume 1 (Saga, #1)", "A Walk Through Hell nº 02/02"). These functions pull out the volume
number and the bare series name so volume 2 never matches volume 1, and so volumes can be grouped.
"""
import re

from .util import similarity

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
WORDS.update({"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5, "seis": 6,
              "sete": 7, "oito": 8, "nove": 9, "dez": 10})
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
         "xi": 11, "xii": 12}
_NUM = r"(\d{1,3}|[ivx]{1,4}|" + "|".join(sorted(WORDS, key=len, reverse=True)) + r")"
# "(Saga, #2)" or "(Saga #2)", the Goodreads way of naming a series entry
GR_SERIES = re.compile(r"\(([^()]+?),?\s*#(\d+(?:\.\d+)?)(?:-\d+)?\)\s*$")
_VOL = [
    re.compile(r"[\s,:;.\-–(]*\b(?:vol(?:ume)?|v|book|tomo|livro|n[ºo°]\.?|n[uú]mero|issue|part|parte|#)\.?\s*" + _NUM + r"\b(?:\s*/\s*\d+)?", re.I),
]


def _num(s):
    s = (s or "").lower()
    if s.isdigit():
        return int(s)
    return WORDS.get(s) or ROMAN.get(s)


def volume(title):
    """Volume number in a title, or None. 'Saga: Volume One' -> 1, 'Animosity Vol 3' -> 3."""
    t = title or ""
    m = GR_SERIES.search(t)
    if m:
        try:
            return int(float(m.group(2)))
        except ValueError:
            pass
    for pat in _VOL:
        m = pat.search(t)
        if m:
            n = _num(m.group(1))
            if n is not None:
                return n
    return None


def series_name(title):
    """The series part of a volume title: 'Saga, Volume Two' -> 'Saga'. None when there's no volume marker."""
    t = title or ""
    m = GR_SERIES.search(t)
    if m:
        return m.group(1).strip()
    for pat in _VOL:
        m = pat.search(t)
        if m and _num(m.group(1)) is not None:
            base = t[: m.start()].strip(" ,:;-–(")
            return base or None
    return None


def base_title(title):
    """Title without series tag, volume marker or subtitle: 'Black Science, Vol. 1: How to Fall Forever' -> 'Black Science'."""
    t = GR_SERIES.sub("", title or "").strip()
    s = series_name(t)
    if s:
        t = s
    t = re.split(r"\s*[:(\[]\s*|\s+[-–—]\s+|,\s+or,?\s+", t)[0]
    return t.strip(" ,.;")


def same_work(wanted, found, threshold=0.86, strict=False):
    """Does a search result `found` look like the title we want? Volume numbers must agree when the wanted
    title has one, and a result whose title says it's a later volume never matches an unnumbered title.
    A Goodreads series tag such as "(Harry Potter, #2)" counts only when the wanted title has a volume."""
    found_plain = GR_SERIES.sub("", found or "").strip()
    vw, vf_title = volume(wanted), volume(found_plain)
    vf = vf_title if vf_title is not None else volume(found)
    if vw is not None and vf is not None and vw != vf:
        return 0.0
    if strict and vw is not None and vf is None:
        return 0.0  # asked for a numbered volume; an unnumbered result could be any of them
    if vw is None and vf_title not in (None, 1):
        return 0.0
    score = max(similarity(wanted, found), similarity(wanted, found_plain), similarity(base_title(wanted), base_title(found)))
    return score if score >= threshold else 0.0
