"""Apply an "Add or change a book" issue form to config/shelf.json (run by .github/workflows/shelf-edit.yml)."""
import os
import re

from . import shelf
from .util import norm, now_iso

KINDS = {"book": "book", "comics (hq)": "comic", "comic": "comic", "manga / manhwa": "manga", "manga": "manga"}
STATUS = {"add as to read": "unread", "add as reading": "reading", "add as read": "read"}


def field(body, label):
    m = re.search(r"###\s*" + re.escape(label) + r"\s*\n+(.*?)(?=\n###|\Z)", body or "", re.S)
    v = (m.group(1).strip() if m else "")
    return "" if v in ("_No response_", "None") else v


def main():
    body = os.environ.get("ISSUE_BODY", "")
    title = field(body, "Title")
    author = field(body, "Author (optional)")
    year = field(body, "Year (optional)")
    owned = field(body, "Volumes or edition you own (optional)")
    kind = KINDS.get(field(body, "Kind").lower(), "book")
    action = field(body, "What to do").lower() or "add as to read"
    sh = shelf.load()
    if not title:
        result = "Nothing to do: no title given"
    else:
        existing = [k for k, v in sh["items"].items() if norm(v.get("title", "")) == norm(title)]
        today = now_iso()[:10]
        if action.startswith("remove"):
            for k in existing:
                del sh["items"][k]
            result = f"Removed {title}" if existing else f"{title} wasn't on the shelf"
        elif action.startswith("mark as read"):
            for k in existing:
                sh["items"][k].update({"status": "read", "read_on": today})
            result = f"Marked {title} as read" if existing else f"{title} wasn't on the shelf"
        elif existing:
            result = f"{title} is already on the shelf"
        else:
            status = STATUS.get(action, "unread")
            entry = {"kind": kind, "title": title, "added": today, "status": status, "interest": 0, "rating": 0}
            if status == "read":
                entry["read_on"] = today
            if author:
                entry["author"] = author
            if year.isdigit():
                entry["year"] = int(year)
            if owned:
                entry["owned"] = owned
            sh["items"][shelf.title_key(kind, title)] = entry
            result = f"Added {title}"
    shelf.save(sh)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"result={result}\n")
    print(result)


if __name__ == "__main__":
    main()
