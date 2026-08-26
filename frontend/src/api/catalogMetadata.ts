/**
 * The shape of `raw.metadata`: the FULL upstream PocketBase record the metadata
 * sync snapshots into `catalog_entries.raw` (services/catalog_metadata.py).
 * `readUpstreamMetadata` below narrows it from `unknown` at runtime, because
 * `CatalogEntryDetail.raw` in api/catalog.ts is still typed
 * `{ ct_script, install_script }`.
 *
 * PRESENTATION ONLY. None of it decides what Proxploy can run, or what an entry
 * IS: `installable`, `unsupported_reason`, `entry_type`, `script_path`, `slug`
 * and the parsed resource defaults are owned by discovery and arrive as
 * TOP-LEVEL fields on `CatalogEntryDetail`. Reading them from here would be
 * wrong in a way that is easy to miss: upstream types `coolify`, `runtipi`,
 * `dockge`, `komodo` and `dokploy` as "addon" while our tree discovery
 * correctly types them "ct". So `UpstreamMetadata` deliberately models nothing
 * that could be mistaken for a feasibility signal.
 *
 * Every field is optional: 9 of 557 store-visible rows (`upstream_state:
 * "unlisted"`) have no record at all. A missing field is normal, never an
 * error, and renders NOTHING.
 */

/** cpu is cores, ram is MiB, hdd is GB, os/version are the template's.
 *  Upstream writes 0 rather than null for a script that creates no container of
 *  its own, so a non-positive number means "no figure". */
export type UpstreamResources = {
  cpu?: number | null
  ram?: number | null
  hdd?: number | null
  os?: string | null
  version?: string | null
}

/** One installable profile of the same app, e.g. a Debian default and an
 *  Alpine variant. `script` is null in every record we have; the runnable one
 *  is the discovery-owned `script_path`. */
export type UpstreamInstallMethod = {
  type?: string | null
  script?: string | null
  config_path?: string | null
  resources?: UpstreamResources | null
}

/** Upstream's post-install notes. `type` is one of info | warning | warn |
 *  general | default, so anything not clearly a warning is treated as
 *  neutral. */
export type UpstreamNote = { text?: string | null; type?: string | null }

/** Upstream's GitHub release snapshot. `changelog` is MARKDOWN written by a
 *  third party, with `\r\n` line endings. It is never HTML to us. */
export type UpstreamGithubData = {
  version?: string | null
  changelog?: string | null
  github_synced_at?: string | null
}

export type UpstreamMetadata = {
  name?: string | null
  description?: string | null
  logo?: string | null
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
 * Presentation fields `_serialize` (backend/proxploy/api/catalog.py) serves as
 * top-level columns and that `CatalogRow` in api/catalog.ts has not always
 * declared. Top-level is what makes them available for the 9 rows with no
 * cached record; declaring them here makes them readable without editing the
 * file that owns `CatalogRow`. Delete this type once `CatalogRow` declares them
 * all.
 *
 * NOT here, and worth knowing why: `script_path`. It is a real discovery-owned
 * column, but `_serialize` does not serve it, so no typing on this side can
 * produce it.
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
 *  whether or not `CatalogRow` has grown them. */
export function readServed(row: unknown): ServedPresentation {
  if (row == null || typeof row !== 'object') return {}
  return row as ServedPresentation
}

/** Pull `metadata` out of a detail row's `raw` blob, or null if it is not
 *  there. Takes `unknown` because the caller passes `detail.raw`, whose
 *  declared type predates this field, so the shape is checked at runtime. */
export function readUpstreamMetadata(raw: unknown): UpstreamMetadata | null {
  if (raw == null || typeof raw !== 'object') return null
  const meta = (raw as { metadata?: unknown }).metadata
  if (meta == null || typeof meta !== 'object' || Array.isArray(meta)) return null
  return meta as UpstreamMetadata
}

/** Array fields arrive from a JSON column, so "declared as an array" is not
 *  "is an array". Anything else reads as empty rather than throwing in a
 *  .map(). */
export function asList<T>(v: T[] | null | undefined): T[] {
  return Array.isArray(v) ? v : []
}

/** A string that actually says something. Upstream uses "" for unset far more
 *  often than null, and an empty string must render nothing, not an empty
 *  row. */
export function text(v: string | null | undefined): string | null {
  if (typeof v !== 'string') return null
  const t = v.trim()
  return t === '' ? null : t
}

/** A figure worth printing. Upstream's 0 means "no figure recorded", and
 *  "0 GB disk" would be a claim, not a blank. */
export function figure(v: number | null | undefined): number | null {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null
}

/**
 * Third-party markdown, prepared for rendering as TEXT.
 *
 * The changelog is upstream's GitHub release note. It is not ours, it is not
 * sanitised, and it must never reach `dangerouslySetInnerHTML`: someone else's
 * release note in the DOM as HTML is an XSS hole with a publish button
 * attached. React escapes text children, so rendering the string is already
 * safe; the only thing needed here is line endings, which arrive as CRLF and
 * would leave stray carriage returns inside a `whitespace-pre-wrap` block.
 *
 * The markdown is left INTACT: half-rendering it without a renderer produces
 * something that is neither.
 */
export function plainText(md: string | null | undefined): string | null {
  const t = text(md)
  return t == null ? null : t.replace(/\r\n?/g, '\n')
}
