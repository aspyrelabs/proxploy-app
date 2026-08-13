# App Store: upstream metadata and icons, cached locally, rendered cache-first

Date: 2026-08-13
Status: approved, ready to implement

## Problem

The Store renders no descriptions, no icons, and categories we invented
ourselves. Confirmed against the live dev DB: 668 catalog rows, **0 with a
description, 0 with an icon_url, 0 ever enriched** (`scraped_at` null on every
row). Categories come from `services/catalog_categories.py`, a hand-maintained
slug-matching heuristic that is ours, not upstream's.

The enrichment path that was supposed to fill those fields,
`services/community_scripts_scrape.py`, parses the Next.js React Server
Component flight payload out of `https://community-scripts.org/categories`. It
is dead in practice and structurally unfixable: an undocumented internal, no
stability contract, Cloudflare-gated, and it breaks on any upstream deploy.

## What the source actually is

The premise that per-app JSON lives in `community-scripts/ProxmoxVE` is **no
longer true**. The full tree at HEAD (`c19711ea1b2526bec67e34be948114e255b5a811`)
has 2009 entries and exactly 4 `.json` files, all `.github`/`.vscode` config.
That repo is scripts only.

The frontend was split out to `community-scripts/ProxmoxVE-Frontend-Archive`,
which is **archived** and frozen at **2026-03-12**. It still carries the old
shape (`public/json/<slug>.json`, 487 files, plus `public/json/metadata.json`
holding the 26 categories).

The live authoritative source is a **PocketBase** instance:

- Base: `https://db.community-scripts.org`
- Collection: `script_scripts`
- Query: `/api/collections/script_scripts/records?perPage=1000&expand=categories,type`

This is upstream's own path, not an inference. Their official self-hosted
client `community-scripts/ProxmoxVE-Local` reads exactly this:

- `src/env.js:15` — `PB_URL` defaults to `https://db.community-scripts.org`
- `src/server/services/pbScripts.ts:229` — `pb.collection("script_scripts").getFullList({ sort: "name", expand: "categories,type", batch: 500 })`
- `scripts/cache-logos.ts` — build-time logo caching over `fields: 'slug,logo'`

This also explains the old scrape: the website payload it parsed (`slug`,
`type`, `expand.categories`) *was* PocketBase data. We were scraping a
rendering of the API instead of calling the API.

### Example record (`filter=(slug='plex')`, trimmed)

```json
{
  "slug": "plex",
  "name": "Plex Media Server",
  "description": "Plex personal media server magically scans and organizes your files, sorting your media intuitively and beautifully.",
  "logo": "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/plex.webp",
  "categories": ["scriptcat00013"],
  "type": "nm9bra8mzye2scg",
  "port": 32400,
  "updateable": true,
  "privileged": false,
  "platforms": ["pve"],
  "website": "https://www.plex.tv/",
  "documentation": "https://support.plex.tv/articles/",
  "expand": {
    "categories": [
      { "id": "scriptcat00013", "name": "Media & Streaming", "icon": "play", "sort_order": 13 }
    ],
    "type": { "id": "nm9bra8mzye2scg", "type": "lxc" }
  }
}
```

### Measured shape of the whole corpus

One request returns **701 records, 1.87 MB, ~1.6 s**, and **zero
`api.github.com` calls** (different host entirely, so the 2-call refresh
ceiling is untouched).

- Types: `lxc` 624, `addon` 31, `pve` 27, `vm` 18, `turnkey` 1
- **701/701 records carry a `logo`** (690 on `cdn.jsdelivr.net`, mostly
  `selfhst/icons`; spot-checked two, both 200 `image/webp`)
- 26 categories, a real controlled vocabulary

### Overlap against our catalog

616 of our 668 slugs match a PocketBase record. **547 of our 584 `ct` rows get
real metadata (94%)**. The 37 uncovered `ct` rows are mostly `alpine-*`
variants plus `mysql`.

Five slugs disagree on type, and they are **exactly the dual-variant collision
slugs**: `coolify`, `runtipi`, `dockge`, `komodo`, `dokploy`. PocketBase types
them `addon`; our tree discovery types them `ct` because each has *both*
`ct/<slug>.sh` and `tools/addon/<slug>.sh`. This is the decisive argument for
the ownership split below: letting metadata set `entry_type` would hide five
installable LXC apps and break dual-variant detection.

## Design

### Ownership split

Scripts stay the source of truth for what a thing *is*. Metadata is the source
of truth only for how it *presents*.

| Field | Owner |
|---|---|
| `slug`, `entry_type`, `script_path` | tree discovery |
| `installable`, `unsupported_reason` | lazy classifier |
| `default_cpu/ram/disk/os/os_version` | ct script parse |
| `name`, `description`, `category`, `icon_url`, `website`, `docs_url` | upstream metadata |

Metadata never decides installability or type.

### Cache: the existing SQLite DB, into `catalog_entries`

Chosen over a cache dir because:

- The Store already renders from `catalog_entries` via `/api/v1/catalog`, so
  cache-first needs **no new read path** and is instant and offline by
  construction.
- It lives in `backend/data/`, the durable data dir that already survives
  restarts (alongside `master.key`).
- The upsert is transactional, so a sync that dies halfway cannot leave a
  half-written catalog.
- No second source of truth to reconcile against the rows the store reads.

A cache dir would mean a parallel store plus a merge at read time, for no gain.

Schema delta on `catalog_entries`:

- drop `scraped_at`
- add `metadata_source` TEXT (`pocketbase` | `archive`)
- add `metadata_synced_at` DATETIME
- add `upstream_updated_at` DATETIME
- full upstream record snapshot into the existing `raw` JSON column, key
  `metadata`

### Sync: `services/catalog_metadata.py`

1. **Primary.** One GET to the PocketBase URL above.
2. **Fallback.** Fires *only* when the primary failed **and** the cache holds
   no metadata at all (cold start on a fresh install with PocketBase down).
   Reads archive `public/json/metadata.json` plus per-slug JSON at pinned SHA
   `e1e6c153e2b1c82287923df2914f33558fc3180f`.
3. **Upsert by slug.** Slugs with no upstream record keep the
   `catalog_categories.py` heuristic as category fallback, so the 37 uncovered
   `alpine-*` rows do not go blank.

Archive schema differs and needs mapping: `type` is `ct` (not `lxc`),
`categories` are integer ids resolved through `metadata.json`,
`interface_port` not `port`.

**Failure policy.** Any failure at any stage leaves the last good rows exactly
as they are and logs the outcome. A sync that cannot reach either source is a
logged non-event, never an empty or broken store. This mirrors the existing
rule that a refresh which cannot reach upstream must still leave a usable
store behind.

Called from the existing `catalog.refresh` job, replacing the scrape call.

### Icons

Store upstream's `logo` URL in `icon_url` and render it directly from their
CDN. No binary caching in this change. `StoreCard`'s existing `onError`
initial-tile fallback already covers a URL that fails to load.

### Schedule

`SYSTEM_SCHEDULES` cron for "Catalog refresh" moves from `0 4 * * *` to
`0 */6 * * *`.

`seed_system_schedules` is deliberately one-way and never updates an existing
row, so a migration retimes the existing row **only if** it still holds the old
default `0 4 * * *`, and clears `next_run_at` so it re-primes. An operator who
already customised the cron keeps their value.

The manual Refresh button enqueues the same `catalog.refresh` job, so both
paths work with no UI change.

### Deletions

- `backend/proxploy/services/community_scripts_scrape.py`
- `backend/tests/test_community_scripts_scrape.py`
- the enrichment call site in `services/catalog.py`

## Unchanged

LXC-only Store; VM/host/addon/turnkey tagged but hidden; lazy feasibility
classification; dual-variant collision detection; virtualized grid with search
and type/category filters; the 2-`api.github.com`-call discovery ceiling; no
per-slug API calls.

## Non-goals

- Caching icon binaries locally.
- Showing VMs in the Store. Explicitly a later step once LXC-only is solid.
- Any change to install, update, or lifecycle behaviour.

## Testing

- Mapping unit tests for both schemas, driven by the captured `plex` records.
- Upsert preserves discovery-owned fields; the five dual-variant slugs stay
  `entry_type='ct'`.
- Primary failure with a warm cache is a no-op that keeps prior rows.
- Fallback fires only on cold cache plus primary failure.
- Slug with no upstream record retains its heuristic category.
- Migration retimes the default cron and leaves a customised one alone.
