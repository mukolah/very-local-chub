------------
Fork of [ayofreaky/local-chub](https://github.com/ayofreaky/local-chub "ayofreaky/local-chub")
------------

## Introduction

Your self-hosted local version of chub.ai — hoard character cards locally, browse and search them, rate them, and automate management through a REST API.

## What's new

- ⚠️ **Improved privacy**: loading external resources from card descriptions is blocked
- Replaced pages with **infinite scroll**
- **Tag exclusion** in search with `-`, e.g. `-rpg`
- **Tag Manager** — favourite, ban, and merge tags from the sidebar
- **Card scores** — rate each card 0–5 for Quality ⭐, Juiciness 🍑, and Story 📖. Hover a card to reveal rating buttons; click to expand a 5-icon widget with half-point precision
- **REST API** — bearer-token authenticated endpoints for reading card data, updating scores, and managing tags. Designed for AI agents
- **First-run auth setup** — prompted to create a username/password on first start, or skip. Reset with `reset_password.py`
- **Safe startup** — missing `static/` folder is created automatically; missing DB with existing JSON+PNG files triggers auto-migration
- Better vertical card containment, blocked inline card styling
- Spam-bot and non-English card detection during sync
- Sort by card created date for consistent results

Visit `http://127.0.0.1:1488/sync?c=200` to pull cards (number = how many to check)

------------

## Screenshots

<img align="left" width="100%" src="https://github.com/mukolah/other_storage/blob/main/app1/very-local-chub.jpg?raw=true">
ㅤ

---

## Run Locally

```bash
git clone https://github.com/mukolah/very-local-chub.git
cd very-local-chub
pip install -r requirements.txt
python localchub.py
```

Open: http://127.0.0.1:1488

On **first start** you'll be prompted to create an account or skip auth entirely.

---

## Authentication

- First run shows a setup screen — create a username + password, or skip (leaves the instance open)
- Once set, every browser visit requires login; the session is stored in a cookie
- **Forgot password / want to re-enable setup prompt:**
  ```bash
  python reset_password.py
  ```
  This deletes only the auth credentials from the database — all cards, scores, tags, and the API token are untouched

---

## API

Generate a bearer token from the **📡** button in the sidebar (opens `/api/docs`).

All `/api/v1/` routes require:
```
Authorization: Bearer <your-token>
```

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cards` | List cards — supports `?page=`, `?query=`, `?sort=` |
| GET | `/api/v1/cards/<id>` | Full card data including character sheet from PNG |
| PATCH | `/api/v1/cards/<id>` | Update scores (`quality`, `lewdity`, `story`) and/or `topics` |
| POST | `/api/v1/cards/<id>/tags/add` | Add tags without replacing existing ones |
| POST | `/api/v1/cards/<id>/tags/remove` | Remove specific tags |

**Quick example — score a card:**
```bash
curl -X PATCH \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"quality": 4.5, "story": 3.0}' \
  http://localhost:1488/api/v1/cards/6194250
```

See `/api/docs` for the full endpoint reference and curl examples.

---

## Database

Cards live as JSON + PNG files in `static/`. The SQLite database (`cards.db`) stores everything else:

| Table | Purpose |
|-------|---------|
| `cards` + `card_tags` | Searchable card index mirrored from JSON files |
| `tag_metadata` | Tag favourites, bans, and merge mappings |
| `card_scores` | Quality / Lewdity / Story scores per card |
| `settings` | Auth credentials, API token, Flask session key |

**The app reads card content directly from JSON files** — `cards.db` is never the source of truth for card data. Deleting `cards.db` loses only your scores, tag config, and auth settings; the cards themselves remain intact in `static/`.

### Auto-population on startup

If `cards.db` does not exist but `static/` contains JSON + PNG files, the app automatically runs a full migration on startup — no manual step needed. Just start `localchub.py` and the database is built from your existing files.

### migrate.py

```bash
python migrate.py              # Rebuild cards/card_tags tables from all JSONs in static/
python migrate.py --sync       # Incremental — only new/updated JSONs
python migrate.py --merge other.db   # Merge another cards.db into a new database_merged.db
```

**Merge behaviour:** cards are merged by `lastActivityAt` (newer wins). Card scores and tag metadata from the source are merged in for any card/tag not already present in the destination. Auth credentials and other settings are intentionally excluded from the merge (they are instance-specific).

---

## Commands

```
python localchub.py --autoupdate 300 --min_tokens 200
```

| Flag | Default | Description |
|------|---------|-------------|
| `--autoupdate N` | 30000s | Auto-sync interval in seconds |
| `--synctags` | off | Overwrite local tags from API on sync |
| `--backup` | off | Copy old files to `/backup` before updating |
| `--min_tags N` | 0 | Minimum tag count for a card to be saved |
| `--include_tags` | "" | Only download cards with these tags (comma-separated) |
| `--exclude_tags` | "nonenglish" | Skip cards with these tags |
| `--sorting` | last_activity_at | Sort method for the download list |
| `--allow_nsfw` | true | Include NSFW cards |
| `--allow_nsfl` | true | Include NSFL cards |
| `--min_tokens` | 250 | Minimum card token count |
| `--max_tokens` | 128000 | Maximum card token count |
| `--include_forks` | false | Download forked cards too |
| `--require_expressions` | false | Require expression pack |
| `--require_lore_embedded` | false | Require embedded lorebook |

Run `python localchub.py -h` for the full list.
