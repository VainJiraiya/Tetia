# Tetia: Tagging, Favourites, Rating and Search: Phased Spec

Audience: the local coding agent working in the Tetia repo. Read `AGENTS.md` first; everything here must respect it.

## Goal

Add a booru-style tagging system covering images, videos, comics/manga and ebooks, plus favourites, an age-style rating filter, and a unified search box that combines tags, filename, file type and (later) Baloo.

## Hard constraints

- **No new dependencies.** Everything below uses the Python stdlib, PySide6/QtCore/QtNetwork and the KDE packages already in `flake.nix`. Do not touch `flake.nix` unless a phase says so (none do).
- All Python models stay `@QmlElement` with `QML_IMPORT_NAME = "Gallery"`, `QML_IMPORT_MAJOR_VERSION = 1`. Use `import org.kde.kirigami 2.20 as Kirigami` in QML.
- `src/models/mediaModel.py` is the active model. Never use the legacy copy at the repo root.
- Use `beginResetModel()`/`endResetModel()` only for bulk changes (rescans, filter changes). A single-item edit (toggle favourite, add or remove a tag, set rating) must emit `dataChanged` for that row so the grid keeps scroll position and selection.
- Tag, favourite and rating operations are keyed by `media_id`, never by visible row. `getFileUri(row)` stays as is for opening files.
- When popping pages or switching tabs, call `.destroy()` on the popped page (see AGENTS.md).
- Never block the GUI thread. Anything slow (hashing, archive parsing, subprocesses) runs in a worker or via `QProcess` signals.
- One branch per phase. Commit when the phase's acceptance criteria pass. Update the architecture section of `AGENTS.md` at the end of each phase.

## Design summary

**Tag categories** (seeded, fixed set of five): `creator`, `series`, `character`, `genre`, `content`.

- `creator` covers author, artist and video creator, in one category across all media kinds.
- `series` is the IP or franchise.
- `character` is optional per item. Hide the field in the editor for ebooks; search treats it the same everywhere.
- `genre` includes demographic (seinen, shounen) and themes such as isekai.
- `content` is "what's in it" (harem, monster_girl, genderswap, supernatural).

The category is only a column on the tag. It controls colour, grouping and which importer field feeds it, never whether search works.

**Rating is not a tag.** It is a nullable integer column on `media` and a search filter:

| Value | Label | Roughly |
|---|---|---|
| 0 | general | all ages |
| 1 | teen | 13+ |
| 2 | mature | 17+ |
| 3 | adult | 18+ |
| NULL | unrated | not set |

**Favourite** is a boolean column on `media`.

**Tag names are globally unique** across categories. Disambiguate collisions with the booru convention `name_(series)`.

## Schema (target end state)

Create tables via a migration system keyed on `PRAGMA user_version`. Each phase adds one numbered migration; never edit an applied migration.

```sql
CREATE TABLE media (
  id            INTEGER PRIMARY KEY,
  path          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,              -- basename, for fast name search
  kind          TEXT NOT NULL CHECK (kind IN ('image','video','comic','ebook')),
  size          INTEGER,
  mtime         INTEGER,
  content_hash  TEXT,                       -- partial hash, see Phase 1
  favorite      INTEGER NOT NULL DEFAULT 0,
  rating        INTEGER CHECK (rating BETWEEN 0 AND 3),
  missing       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX media_hash ON media(content_hash);

CREATE TABLE tag_category (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL
);
-- seed in order: creator, series, character, genre, content

CREATE TABLE tag (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
  category_id INTEGER NOT NULL REFERENCES tag_category(id),
  description TEXT
);

CREATE TABLE tag_alias (
  alias  TEXT PRIMARY KEY COLLATE NOCASE,
  tag_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE
);

CREATE TABLE tag_implication (
  antecedent_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  consequent_id INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  PRIMARY KEY (antecedent_id, consequent_id),
  CHECK (antecedent_id <> consequent_id)
);

CREATE TABLE media_tag (
  media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
  tag_id   INTEGER NOT NULL REFERENCES tag(id)   ON DELETE CASCADE,
  source   TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','import')),
  PRIMARY KEY (media_id, tag_id)
);
CREATE INDEX media_tag_by_tag ON media_tag(tag_id, media_id);
```

Enable `PRAGMA foreign_keys = ON` on every connection.

---

## Phase 1: Persistent media identity, favourites, rating columns

**Why:** items are currently scanned live and only folders are persisted, so there is no stable row to attach anything to.

**Tasks**

1. Migration 1: create `media` (including `favorite`, `rating`, `missing`) and the schema-version plumbing in `database.py`.
2. On folder scan, upsert each file into `media` by `path`, setting `name`, `kind`, `size` and `mtime`.
3. Compute `content_hash` as a cheap partial hash: SHA-1 over `size + first 1 MB + last 1 MB`, using `hashlib`. Skip rehashing when `size` and `mtime` are unchanged.
4. Reconcile moves: if a scanned path has no row but its hash matches a row whose file no longer exists, update that row's `path`/`name` instead of inserting. This preserves tags across moves and renames.
5. Never delete rows for files that vanished. Set `missing = 1` (so an unmounted drive doesn't wipe tags); clear it when the file reappears.
6. Extend `mediaModel.py` roles: `mediaId`, `isFavorite`, `rating`. Add `@Slot(int, bool) setFavorite(media_id, value)` and `@Slot(int, int) setRating(media_id, value)` (value -1 clears to NULL). Both emit `dataChanged` for the affected row only.
7. UI: favourite toggle on the grid delegate and the viewers, and a rating selector in a details panel.

**Acceptance**

- Rescanning a folder twice produces no duplicate rows.
- Renaming or moving a file within scanned folders keeps its `media_id`, favourite and rating.
- Toggling favourite does not reset the grid's scroll position.

---

## Phase 2: Tags core and editor

**Tasks**

1. Migration 2: create `tag_category` (seeded), `tag`, `tag_alias`, `tag_implication`, `media_tag`.
2. New `src/models/tagModel.py`:
   - A `QmlElement` service exposing `@Slot` methods: `tagsFor(media_id)`, `addTag(media_id, name, category)`, `removeTag(media_id, tag_id)`, `createTag(name, category)`, `suggest(prefix, limit)`.
   - A `QAbstractListModel` for the tag list/autocomplete (roles: `tagId`, `name`, `category`, `usageCount`).
3. **Normalization** (single function used everywhere): strip, lowercase, collapse whitespace to `_`, reject empty names and names containing `,`, `:`, `*`, `~` or a leading `-`.
4. **Add flow:** normalize, resolve alias to canonical tag, then look up the tag. If it is missing, the editor asks for a category (default `content`). Typing `creator:foo` in the editor input pre-selects the category.
5. Editor UI: a `Flow` of `Kirigami.Chip` (removable, tinted per category) with a text field and an autocomplete popup. Support a multi-select bulk edit on the grid (add or remove a tag across selected items in one transaction).
6. Usage counts are computed with `GROUP BY` on demand (library size does not justify triggers); cache in the model per refresh.

**Acceptance**

- Adding `Monster Girl` stores `monster_girl`; adding it again to the same item is a no-op.
- Removing a chip updates only that item's row (`dataChanged`).
- Bulk add across 100 selected items runs in one transaction.
- Tags persist across restarts and file moves (Phase 1).

---

## Phase 3: Search

Put the parser in a pure-Python module `src/models/tag_query.py` with no Qt imports so it can be exercised with stdlib `unittest` (`tests/test_tag_query.py`). This is the only place tests are required.

**Grammar** (tokens separated by whitespace; double quotes group a token):

| Token | Meaning |
|---|---|
| `isekai` | media has this tag (or an alias, or any tag implying it) |
| `-harem` | media does NOT have it |
| `~a ~b` | OR group: media has at least one of them |
| `fant*` | wildcard on tag name (treated as an OR group over matches) |
| `creator:foo`, `series:foo`, `character:foo` | tag restricted to that category |
| `type:video` | `image`, `video`, `comic`, `ebook` (aliases: `photo`, `manga`, `book`) |
| `is:favorite` | favourites only |
| `rating:adult` / `rating:>=mature` / `rating:<teen` / `rating:unrated` | rating filter |
| `name:overlord` or `"overlord"` | case-insensitive substring on filename |

All terms are ANDed. A bare unknown tag matches nothing (booru behaviour); the UI shows a small "unknown tag" hint rather than silently ignoring it.

**SQL generation**

- One `EXISTS` per positive term, one `NOT EXISTS` per negative term, over an expanded tag-id set. Always use bound parameters; never interpolate user text.
- **Alias resolution:** map each term through `tag_alias` first.
- **Implication expansion at query time** (do not materialize rows). The set of tags that satisfy term `T` is `T` plus every tag that implies it, recursively:

```sql
WITH RECURSIVE satisfying(id) AS (
  SELECT :tag_id
  UNION
  SELECT i.antecedent_id
  FROM tag_implication i JOIN satisfying s ON i.consequent_id = s.id
)
SELECT id FROM satisfying;
```

- Example shape for `isekai -harem rating:>=mature`:

```sql
SELECT m.id FROM media m
WHERE m.missing = 0
  AND EXISTS (SELECT 1 FROM media_tag mt WHERE mt.media_id = m.id AND mt.tag_id IN (:isekai_set))
  AND NOT EXISTS (SELECT 1 FROM media_tag mt WHERE mt.media_id = m.id AND mt.tag_id IN (:harem_set))
  AND m.rating >= 2;
```

- **Rating NULL-safety:** comparisons like `rating:>=mature` require a non-NULL rating. `-rating:adult` compiles to `(m.rating IS NULL OR m.rating <> 3)`.
- **"Hide adult" toggle** in the UI appends an implicit `-rating:adult`. Unrated items stay visible by design.

**Autocomplete:** the search field suggests tags by prefix over `tag.name` and `tag_alias.alias`, ordered by usage count, and also suggests metatag prefixes (`creator:`, `type:`, `rating:`, `is:`, `name:`). If `PRAGMA compile_options` shows FTS5, it may be used; plain indexed `LIKE 'prefix%'` is acceptable.

**UI:** replace or extend the existing search/filter entry so the query drives `mediaModel` (one `beginResetModel()`/`endResetModel()` per executed query). Show active terms as removable chips.

**Acceptance**

- All grammar rows above have unit tests, including empty query, quoted names, `-` on unknown tags, wildcard escaping (`%` and `_` in user text), and NULL-rating behaviour.
- A query over a 50k-row synthetic `media` table returns in well under 100 ms.

---

## Phase 4: Aliases and implications

**Tasks**

1. A small management page (Kirigami list + add/remove) for aliases and implications, plus a rename and recategorize action for tags.
2. Constraints: an alias cannot equal an existing tag name or point at another alias; an implication cannot create a cycle (reject on insert by walking the chain). Deleting a tag cascades via the foreign keys.
3. Typical use, e.g. `gender_bender` is an alias of `genderswap`; `naruto_uzumaki` implies `naruto`.

**Acceptance**

- Searching `naruto` returns items tagged only `naruto_uzumaki`.
- Typing an alias in the editor stores the canonical tag.
- Cycle creation is refused with a user-visible message.

---

## Phase 5: Metadata import for comics and ebooks

Parse in a worker thread using only `zipfile` and `xml.etree.ElementTree`. Imported tags get `source = 'import'`. Import never overwrites or removes `manual` tags and never changes a rating that is already set.

**Comics (CBZ):** read `ComicInfo.xml` from the archive root.

| ComicInfo field | Target |
|---|---|
| `Writer`, `Penciller`, `Artist` | creator |
| `Series` | series |
| `Genre` (comma-separated) | genre |
| `Tags` (comma-separated) | content |
| `AgeRating` | rating (see map below) |
| `Manga` | no tag; may be used later for reading direction |

**Ebooks (EPUB):** read `META-INF/container.xml`, then the OPF.

| OPF field | Target |
|---|---|
| `dc:creator` | creator |
| `calibre:series` (meta) | series |
| `dc:subject` | genre |

**AgeRating map:** Everyone / Early Childhood → 0; Teen → 1; Mature 17+ → 2; Adults Only 18+ / X18+ → 3; anything else, leave NULL.

**Rules**

- Each imported value is normalized through the Phase 2 function, then alias-resolved. Missing tags are created in the target category.
- Import runs on first scan of a file and on an explicit "Re-import metadata" action; it is skipped when `mtime` is unchanged.
- Corrupt or missing metadata is logged and skipped, never fatal.
- If the folder name is the only clue, offer (do not auto-apply) the parent folder name as a series tag.

**Acceptance**

- A CBZ with a `ComicInfo.xml` containing a Genre and Tags is searchable by those tags right after scan.
- Re-importing does not duplicate or remove manual tags.

---

## Phase 6: Baloo integration

Baloo has no Python bindings, so integration is via extended attributes (write) and the CLI (read). Verify behaviour on the target machine before relying on any assumption below: `baloosearch --help`, `balooshow <file>`, `balooctl status`.

### 6a. Mirror to extended attributes (SQLite stays the source of truth)

For each item, write with `os.setxattr`:

- `user.xdg.tags`: comma-separated tag names (all five categories). When the value would exceed about 3.5 KB (ext4 limit), drop tags in this order: content, genre, character, series, creator last.
- `user.baloo.rating`: `10` if favourite, otherwise remove the attribute.
- Age rating: add a `rating_<label>` entry (e.g. `rating_adult`) to `user.xdg.tags`. Baloo's own rating attribute is a star rating and is not used for the age rating.

Rules:

- Sync is one-way (database to files). Do not read xattrs back into the database.
- Run the sync in a background worker, debounced after edits, and on demand ("Sync tags to Baloo").
- Catch `OSError` per file (unsupported filesystem, read-only, permission, network share) and continue; surface a count of failures, not a dialog per file.
- Mirror behaviour must be a setting, off by default.

### 6b. Hybrid search

Split the parsed query:

- Tag, `creator:`/`series:`/`character:`, `is:`, `rating:` and `type:` terms go to SQLite (Phase 3).
- Free-text terms (bare `name:`/quoted strings when "also search Baloo" is enabled) go to `baloosearch` via `QProcess`, parsed from stdout, then intersected with the SQLite result by normalized real path.

Rules:

- `QProcess` only, asynchronous, with a timeout; ignore stderr noise.
- If `baloosearch` is missing, fails, or the folder isn't indexed, fall back to the SQLite `name` search and show a small notice.
- Baloo only covers folders it indexes; do not assume Tetia's folders are included.

**Acceptance**

- After enabling the mirror and syncing, `baloosearch tag:<name>` (confirm exact syntax) finds a tagged file, and Dolphin shows the same tags.
- Disabling or breaking Baloo never breaks Tetia's own search.
- Syncing 10k files does not freeze the UI.

---

## Out of scope

- Reading tags back from xattrs into the database.
- Online metadata lookups.
- Tagging individual comic pages (tags attach to the work, not its pages).
- Hierarchical tag trees (implications cover the needed relationships).

## Definition of done (all phases)

- `AGENTS.md` architecture section lists the new modules and the new tables.
- App starts cleanly on an existing database (migrations applied in order, no data loss).
- No new entries in `flake.nix`.
