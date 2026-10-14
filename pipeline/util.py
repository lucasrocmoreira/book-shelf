"""Shared helpers: paths, HTTP session with polite rate limiting, JSON files, title normalization."""
import datetime as dt
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
SITE_DIR = ROOT / "site"
CONFIG_DIR = ROOT / "config"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

session = requests.Session()
session.headers["User-Agent"] = BROWSER_UA
session.headers["Accept-Language"] = "en-US,en;q=0.9"

_last_call: dict[str, float] = {}


def polite_get(url, host_delay=1.0, retries=3, **kw):
    """GET with a per-host minimum delay and simple backoff on 429/5xx. Returns None on network failure."""
    host = url.split("/")[2]
    kw.setdefault("timeout", 30)
    r = None
    for attempt in range(retries):
        wait = host_delay - (time.time() - _last_call.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
        try:
            r = session.get(url, **kw)
        except requests.RequestException as e:
            log(f"  network error on {host}: {e}")
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(10 * (attempt + 1))
            continue
        return r
    return r


def log(msg):
    print(msg, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data, pretty=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1 if pretty else None, sort_keys=pretty)
    path.write_text(text + "\n", encoding="utf-8")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def days_since(iso):
    if not iso:
        return 10_000
    try:
        then = dt.datetime.fromisoformat(iso)
    except ValueError:
        return 10_000
    if then.tzinfo is None:
        then = then.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - then).days


def norm(title: str) -> str:
    t = (title or "").lower()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def slugify(title: str, sep="_") -> str:
    """Rotten Tomatoes uses underscores (tv/the_bear), Metacritic hyphens (tv/the-bear)."""
    t = (title or "").lower()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"['’.]", "", t)
    t = re.sub(r"[^a-z0-9]+", sep, t)
    return t.strip(sep)


def similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()
