# Book Shelf

Your books, comics (HQ) and manga in one list, ranked by Goodreads, Hardcover, Open Library, AniList and
MyAnimeList scores, with filters by kind, genre, theme, mood, author, series, demographic and length.
Add titles from the app, mark them Reading or Read, rate them yourself. A GitHub Actions job refreshes
everything every day and publishes the site to GitHub Pages.

## How it works

| Piece | Source | Notes |
|---|---|---|
| Your shelf | `config/shelf.json` in this repo | The app writes it with your GitHub token |
| Books and comics: title, authors, year, pages, cover, subjects, Open Library rating | Open Library (free, no key) | The search in "Add" uses it too, straight from your browser |
| Goodreads rating, count and genres | Public Goodreads book page | No API since 2020; best effort. The exact page comes from Open Library's Goodreads id when it has one |
| Hardcover rating, genres, moods, tags, series | Hardcover API (free token, beta) | Optional but recommended: it's the best source of themes and moods for books |
| Manga, manhwa, manhua: details, AniList score, genres, tags | AniList API (free, no key) | One entry per series |
| MyAnimeList score, rank, members, themes, demographic | Jikan (unofficial MyAnimeList API, no key) | |

Books are tracked as single works (a graphic novel or a collected edition counts as one). Manga are
tracked as series; use **What you own** to note volumes (for example `1-12, 15`).

Ratings are rechecked monthly (weekly for ongoing manga). New titles are scored a few minutes after you add them.

The **Average score** is the mean of the scores a title has, each on a 0 to 100 scale (Goodreads 4.20 counts
as 84, MyAnimeList 8.7 as 87). Pick which sources count under "Scores in the average". Five-star sites
bunch up between 3.6 and 4.4, so compare books with books on the same source when it matters.

## Setup (about 10 minutes, once)

### 1. Repository and Pages
1. Use this repository as is (public, so GitHub Pages is free).
2. **Settings > Pages**: set **Source** to **GitHub Actions**.

### 2. Hardcover token (optional, recommended)
1. Create a free account at https://hardcover.app.
2. Open **Settings > Hardcover API** (https://hardcover.app/account/api) and create a key. Set the longest expiration it allows.
3. In this repo: **Settings > Secrets and variables > Actions > New repository secret**, name `HARDCOVER_TOKEN`, paste it.

Without it the site works; books just have no Hardcover score, moods or tags (genres still come from Goodreads).
When the token expires the site shows a warning; make a new one and replace the secret.

### 3. Run it
1. **Actions** tab: enable workflows if GitHub asks.
2. **Update book shelf > Run workflow**.
3. When it finishes, the site is at `https://<your-username>.github.io/book-shelf/`.

### 4. Connect the app (once per device)
Open **Settings** in the app and paste a fine-grained GitHub token with **Contents: Read and write** on this
repository only (https://github.com/settings/personal-access-tokens/new). It stays in that browser's storage only.

## Day to day
- **Add**: pick Book, Comics / HQ or Manga, search, tap Add. Choose "Add as" Read to log things you've already read.
  Can't find it? **Add by title** (with the author if you know it) and it's matched on the next update.
- **Status**: open a title and tap To read, Reading or Read. Read titles get your own 1 to 5 stars.
- **Interest stars** (1 to 3): your priority for what to read next; "Rank by my interest" sorts by it, ties broken by average score.
- **Rank and filter**: change "Rank by", tap Books / Comics / Manga, or open the filters. Tap any genre, theme, mood or series tag inside a title to filter by it.
- **Pick for me**: picks at random from the top 5 of the current view.
- **Without the app**: Issues > New issue > **Add or change a book**.

Status, stars, what you own and remove are instant and don't rebuild. Adding a title triggers a rebuild.

## Limits worth knowing
- The site and `config/shelf.json` are public. Anyone with the link can see your shelf (never your tokens).
- Goodreads has no API. If it blocks GitHub's servers or changes its pages, the Goodreads column stops
  updating (old scores are kept, the rest keeps working, the app shows a warning) until the parser in
  `pipeline/goodreads.py` is adjusted. Bump `PARSER_VERSION` there after a fix so every book is rechecked.
- Comics coverage is thinner than books on every source, especially Brazilian and European albums. A title
  with no score still shows and sorts below scored ones (or hide them under "other options").
- Manga scores are for the whole series; book scores are for the work across all editions and translations.
- Goodreads needs 50+ ratings, Hardcover and Open Library 10+, before their score counts.
- Hardcover's API is in beta and its tokens expire; the token is used only by the GitHub Action, never in the browser.

## Run locally
```bash
pip install -r requirements.txt
export HARDCOVER_TOKEN=...   # optional
python -m pipeline.build
python -m http.server -d site 8000   # then open http://localhost:8000
```
