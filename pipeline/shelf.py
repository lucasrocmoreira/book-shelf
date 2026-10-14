"""Your collection: config/shelf.json.

The web app writes this file directly (once you connect it to GitHub in its Settings), the
"Add or change a book" issue form writes it too, and you can edit it by hand. Shape:

{"items": {
   "ol:OL893415W": {"kind": "book", "ol": "OL893415W", "title": "Dune", "author": "Frank Herbert",
                    "year": 1965, "cover": "https://covers.openlibrary.org/b/id/....jpg",
                    "added": "2026-10-13", "status": "unread", "interest": 2, "rating": 0, "owned": ""},
   "al:30002":      {"kind": "manga", "anilist": 30002, "title": "Berserk", "owned": "1-41", ...},
   "q:comic:saga":  {"kind": "comic", "title": "Saga", "author": "Brian K. Vaughan"}   # added by title; matched on the next build
}}

kind:   book | comic | manga
status: unread | reading | read   (read_on is the date you marked it read)
interest: 0-3 (your priority), rating: 0-5 (your own score once read), owned: free text such as "1-12" or "Omnibus".

Keys never change once written, so the app's edits always find their item.
"""
import json

from .util import CONFIG_DIR, norm

PATH = CONFIG_DIR / "shelf.json"
KINDS = ("book", "comic", "manga")


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    items = data.get("items") if isinstance(data.get("items"), dict) else {}
    return {"items": {k: v for k, v in items.items() if isinstance(v, dict)}}


def save(data: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def kind_of(entry: dict) -> str:
    k = (entry.get("kind") or "").lower()
    return k if k in KINDS else "book"


def title_key(kind: str, title: str) -> str:
    return f"q:{kind}:{norm(title)}"
