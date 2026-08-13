/**
 * The shape of `raw.metadata`: the FULL upstream PocketBase record that the
 * metadata sync snapshots into `catalog_entries.raw` (see the 2026-08-13
 * "App Store: upstream metadata and icons" design and
 * services/catalog_metadata.py).
 *
 * WHY THIS FILE EXISTS SEPARATELY FROM api/catalog.ts. Two reasons, and the
 * second is the important one.
 *
 * 1. `CatalogEntryDetail.raw` is still typed `{ ct_script, install_script }`
 *    over there, which no longer describes what the route serves: `raw` now
 *    also carries `metadata`. That type wants widening at the source; until it
 *    is, `readUpstreamMetadata` below narrows it here, from `unknown`, with a
 *    real runtime check rather than a cast that would be a lie either way.
 *
 * 2. PRESENTATION ONLY. Everything in here is upstream's description of an
 *    app, cached verbatim. None of it decides what Proxploy can run, or what
 *    an entry IS. `installable`, `unsupported_reason`, `entry_type`,
 *    `script_path`, `slug` and the parsed resource defaults are all owned by
 *    discovery and the lazy classifier, and they arrive as TOP-LEVEL
 *    serialized fields on `CatalogEntryDetail`. Reading them from here would
 *    be wrong in a way that is easy to miss: upstream types `coolify`,
 *    `runtipi`, `dockge`, `komodo` and `dokploy` as "addon" while our tree
 *    discovery correctly types them "ct", so a page that trusted
 *    `metadata.type` would misreport five real LXC apps. The design calls that
 *    out by name as the mistake the ownership split exists to prevent, which
 *    is why `UpstreamMetadata` deliberately does NOT model `type`,
 *    `install_methods[].script` as anything runnable, or anything else that
 *    could be mistaken for a feasibility signal.
 *
 * Every field is optional and nullable because 548 of 557 store-visible rows
 * have this record and 9 (`upstream_state: "unlisted"`) have nothing at all,
 * and even a covered record leaves plenty of individual fields empty. A
 * missing field is normal, never an error, and renders NOTHING.
 */

/** cpu is cores, ram is MiB, hdd is GB, os/version are the template's, e.g.
 *  Debian 13. Upstream writes 0 rather than null for a script that does not
 *  create a container of its own (an addon-style script), so a consumer has
 *  to treat a non-positive number as "no figure", not as "runs on nothing". */
export type UpstreamResources = {
  cpu?: number | null
  ram?: number | null
  hdd?: number | null
  os?: string | null
  version?: string | null
}

/** One installable profile of the same app, e.g. the Debian default and an
 *  Alpine variant (`syncthing`, `mariadb`, `rustdeskserver` have two).
 *
 *  `script` is null in every record we have. The real script is the
 *  top-level, discovery-owned `script_path`; nothing should print this one. */
export type UpstreamInstallMethod = {
  type?: string | null
  script?: string | null
  config_path?: string | null
  resources?: UpstreamResources | null
}

/** Upstream's post-install notes. `type` is one of info | warning | warn |
 *  general | default across the corpus, so anything that is not clearly a
 *  warning is treated as neutral. */
export type UpstreamNote = { text?: string | null; type?: string | null }

/** Upstream's GitHub release snapshot. `changelog` is MARKDOWN written by a
 *  third party, with links and `\r\n` line endings. It is never HTML to us. */
export type UpstreamGithubData = {
  version?: string | null
  changelog?: string | null
  github_synced_at?: string | null
}

export type UpstreamMetadata = {
  name?: string | null
  description?: string | null
  logo?: string | null
  // Presentation facts about the resulting container.
  port?: number | null
  privileged?: boolean | null
  updateable?: boolean | null
  has_arm?: boolean | null
  architectures?: string[] | null
  platforms?: string[] | null
  execute_in?: string[] | null
  // First-run facts. `default_passwd` is upstream's PUBLISHED default, not a
  // secret of this installation, and is empty string (not null) when unset.
  default_user?: string | null
  default_passwd?: string | null
  config_path?: string | null
  notes?: UpstreamNote[] | null
  install_methods?: UpstreamInstallMethod[] | null
  github_data?: UpstreamGithubData | null
  // Links out.
  website?: string | null
  documentation?: string | null
  github?: string | null
  repository?: string | null
  last_update_commit?: string | null
  // Upstream's dates for the SCRIPT, not for our sync.
  script_created?: string | null
  script_updated?: string | null
}

/**
 * Presentation fields the catalog routes genuinely SERVE as top-level columns
 * (backend/proxploy/api/catalog.py::_serialize writes every one of them) and
 * that `CatalogRow` in api/catalog.ts has not always declared.
 *
 * These are the same facts the cached record carries, because the sync writes
 * the columns FROM that record. Serving them at the top level is what makes
 * them available for the 9 rows with no record; declaring them here is what
 * makes them readable without editing the file that owns `CatalogRow`. Every
 * field is optional, so this reads a row that predates any of them exactly the
 * same as one that has them all, and it is deletable the moment `CatalogRow`
 * is the single declaration of all of them.
 *
 * NOT in this list, and worth knowing why: `script_path`. It is a real
 * discovery-owned column on `catalog_entries`, but `_serialize` does not
 * serve it, so no amount of typing on this side can produce it. Showing the
 * upstream script a row IS needs a backend change first.
 */
export type ServedPresentation = {
  popularity_synced_at?: string | null
  has_arm?: boolean | null
  architectures?: string[] | null
  updateable?: boolean | null
  privileged?: boolean | null
  port?: number | null
  script_created?: string | null
  script_updated?: string | null
}

/** Read those fields off a serialized row. `unknown` in, so this compiles
 *  whether or not `CatalogRow` has grown them, and every field stays optional
 *  so a row that predates them reads as absent rather than as a value. */
export function readServed(row: unknown): ServedPresentation {
  if (row == null || typeof row !== 'object') return {}
  return row as ServedPresentation
}

/**
 * Pull `metadata` out of a detail row's `raw` blob, or null if it is not
 * there.
 *
 * Takes `unknown` on purpose: the caller passes `detail.raw`, whose declared
 * type in api/catalog.ts predates this field, and widening that type is the
 * owning file's change to make. Checking the shape at runtime here means this
 * stays correct whether that type is widened later or not.
 */
export function readUpstreamMetadata(raw: unknown): UpstreamMetadata | null {
  if (raw == null || typeof raw !== 'object') return null
  const meta = (raw as { metadata?: unknown }).metadata
  if (meta == null || typeof meta !== 'object' || Array.isArray(meta)) return null
  return meta as UpstreamMetadata
}

/** Array fields arrive from a JSON column, so "it is declared as an array" is
 *  not the same as "it is an array". Anything else reads as empty, which
 *  renders as nothing at all rather than throwing inside a .map(). */
export function asList<T>(v: T[] | null | undefined): T[] {
  return Array.isArray(v) ? v : []
}

/** A string that actually says something. Upstream uses "" for unset far more
 *  often than null (`default_user`, `default_passwd`, `pin_reason`), and an
 *  empty string must render nothing, not an empty row. */
export function text(v: string | null | undefined): string | null {
  if (typeof v !== 'string') return null
  const t = v.trim()
  return t === '' ? null : t
}

/** A figure worth printing. Upstream's 0 means "no figure recorded" for every
 *  resource it writes (see UpstreamResources), and "0 GB disk" would be a
 *  claim, not a blank. */
export function figure(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null
}

/**
 * Third-party markdown, prepared for rendering as TEXT.
 *
 * The changelog is upstream's GitHub release note. It is not ours, it is not
 * sanitised, and it must never reach `dangerouslySetInnerHTML`: putting
 * someone else's release note into the DOM as HTML is an XSS hole with a
 * publish button attached. React escapes text children, so rendering the
 * string is already safe; the only thing needed here is line endings, which
 * arrive as CRLF and would otherwise leave stray carriage returns inside a
 * `whitespace-pre-wrap` block.
 *
 * The markdown is deliberately left INTACT rather than half-stripped: it stays
 * readable as plain text ("### Fixed", "- [issue #558](url)"), and pretending
 * to render markdown without a renderer produces something that is neither.
 * Adding a real markdown renderer is a dependency decision for the user, not
 * one to sneak in here.
 */
export function plainText(md: string | null | undefined): string | null {
  const t = text(md)
  return t == null ? null : t.replace(/\r\n?/g, '\n')
}
