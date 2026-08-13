import { createRoute, Link, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import type { ReactNode } from 'react'
import type { CatalogEntryDetail } from '../api/catalog'
import { useCatalogEntry } from '../api/catalog'
import { ApiError } from '../api/client'
import type {
  ServedPresentation, UpstreamInstallMethod, UpstreamMetadata, UpstreamNote,
} from '../api/catalogMetadata'
import {
  asList, figure, plainText, readServed, readUpstreamMetadata, text,
} from '../api/catalogMetadata'
import { EmptyState } from '../components/EmptyState'
import { KVGrid } from '../components/KVGrid'
import { Button } from '../components/ui/button'
import { LoadingBlock } from '../components/ui/loading'
import { STORE_GRADIENT } from '../components/UsageBar'
import { fmtBytes } from '../lib/format'
import { shellRoute } from './shell'

/**
 * The App Store detail page: everything about one catalog entry that does not
 * fit on a card.
 *
 * TWO SOURCES, ONE PAGE, AND THEY ARE NOT INTERCHANGEABLE (2026-08-13 upstream
 * metadata design, "Ownership split"):
 *
 *  - DISCOVERY owns what this thing is and whether it can run: `slug`,
 *    `type`, `script_path`, `installable`, `unsupported_reason` and the
 *    resource defaults parsed out of the ct script. All top-level fields of
 *    the serialized row. Everything on this page that decides or reports
 *    feasibility reads from there and only from there.
 *  - UPSTREAM METADATA (`raw.metadata`, the cached PocketBase record) owns
 *    presentation: notes, install profiles, changelog, links, credentials,
 *    ARM/privileged flags. It never decides what runs.
 *
 * Reading feasibility out of metadata is the specific mistake the design
 * forbids by name: upstream types coolify/runtipi/dockge/komodo/dokploy as
 * "addon" while we type them "ct", so trusting `metadata.type` would misreport
 * five real LXC apps.
 *
 * A FIELD WITH NO DATA RENDERS NOTHING. Not a blank row, not "unknown", not a
 * dash: whole sections disappear when they have no content. That is not
 * tidiness, it is the only way this page can serve both the 548 rows with a
 * full upstream record and the 9 `unlisted` rows that have no metadata at all
 * and must still produce a usable page from discovery alone.
 *
 * No install flow lives here, by scope. Installing is still the grid's job.
 */

const card = 'rounded-card border border-line-soft bg-panel p-5'

// Every Store entry is "ct" in practice (the grid pins entry_type=ct), but a
// by-slug URL can name any discovered row, including the vm/pve/addon/turnkey
// ones the grid hides. Same lookup StoreCard keeps, duplicated rather than
// imported because that file is a card's private label table.
const TYPE_LABEL: Record<CatalogEntryDetail['type'], string> = {
  ct: 'LXC', vm: 'VM', pve: 'Host', addon: 'Add-on', turnkey: 'Turnkey',
}

// Same wording as the card's badge, and the same care about what it does NOT
// say: upstream stopped listing this app, which is a fact about upstream's
// catalog, not a judgement about the app or its script.
const UNLISTED_NOTE =
  'community-scripts no longer lists this app. Its install script is still in '
  + 'the repository and still installs. This is about the upstream catalog, '
  + 'not a judgement about the app itself.'

/** ISO (or PocketBase's "YYYY-MM-DD HH:MM:SS.mmmZ") to something readable, or
 *  null if it is not a date at all. Null renders nothing, never "Invalid Date".
 *  Local time, matching every other timestamp in the app. */
function when(iso: string | null | undefined, dateOnly = false): string | null {
  const raw = text(iso)
  if (raw == null) return null
  const d = new Date(raw.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return null
  return dateOnly ? d.toLocaleDateString() : d.toLocaleString()
}

/** Upstream records RAM in MiB and disk in GB; the ct-script parse uses the
 *  same units. fmtBytes wants bytes, so this is the one conversion. */
function ram(mb: number | null): string | null {
  return mb == null ? null : fmtBytes(mb * 1024 * 1024)
}

/** The ct-script parse yields "debian", upstream's record says "Debian", and
 *  they sit two cards apart on this page. Casing only: no name is translated,
 *  substituted or guessed at, so an OS this parser has never seen still shows
 *  up as whatever the script called it. */
function osName(os: string): string {
  return os.charAt(0).toUpperCase() + os.slice(1)
}

/** A titled block. Callers decide whether they have anything to say; this
 *  never renders a heading over an empty body. */
function Section({ title, children, className = '' }: {
  title: string; children: ReactNode; className?: string
}) {
  return (
    <section className={`${card} ${className}`}>
      <h2 className="mb-3 text-[13px] uppercase tracking-wide text-text-3">{title}</h2>
      {children}
    </section>
  )
}

/** The same 40px-tile-or-initials contract StoreCard's CardIcon has, at page
 *  size. Upstream icons are hotlinked from a CDN with no local cache, so a URL
 *  that 404s or is blocked is an expected case, not a bug, and the initials
 *  tile is the fallback for both that and a row with no icon_url at all. */
function DetailIcon({ name, iconUrl }: { name: string; iconUrl: string | null }) {
  const [broken, setBroken] = useState(false)
  if (iconUrl && !broken) {
    return (
      <img src={iconUrl} alt={name} width={56} height={56}
        className="h-14 w-14 rounded-card object-contain"
        onError={() => setBroken(true)} />
    )
  }
  return (
    <div className="flex h-14 w-14 items-center justify-center rounded-card font-display
                    text-[18px] font-semibold text-white"
      style={{ background: STORE_GRADIENT }}>
      {name.slice(0, 2).toUpperCase()}
    </div>
  )
}

function Chip({ children, tone = 'neutral', title }: {
  children: ReactNode; tone?: 'neutral' | 'amber'; title?: string
}) {
  const tones = {
    neutral: 'border-line bg-panel-2 text-text-2',
    amber: 'border-amber/30 bg-amber-dim text-amber',
  }
  return (
    <span title={title}
      className={`inline-block rounded border px-1.5 py-0.5 text-[10.5px] ${tones[tone]}`}>
      {children}
    </span>
  )
}

/**
 * What Proxploy can actually do with this entry, and nothing upstream says
 * about it. Discovery and the lazy classifier own every value here.
 *
 * `installable` is TRI-STATE and null means "not established yet", never "no".
 * Opening this page is one of the two moments the backend classifies a ct row
 * (api/catalog.py::get_catalog_entry calls ensure_classified), so null on
 * arrival means that attempt did not produce an answer, e.g. upstream was
 * unreachable. Rendering that as "not installable" would state a conclusion
 * nothing here supports, so it says what is true (we do not know yet) and
 * offers the retry, which re-runs classification server-side.
 */
function Feasibility({ entry, onRecheck, rechecking }: {
  entry: CatalogEntryDetail; onRecheck: () => void; rechecking: boolean
}) {
  const reason = text(entry.unsupported_reason)
  return (
    <Section title="Availability">
      {entry.installable === true && (
        <p className="text-[13px] text-green">Installable.</p>
      )}
      {entry.installable === false && (
        <p className="text-[13px] text-text">
          Not installable.{reason ? <span className="text-text-2"> {reason}</span> : null}
        </p>
      )}
      {entry.installable === null && (
        <div>
          <p className="text-[13px] text-text-2">
            Proxploy has not been able to confirm whether this can be installed.
            Feasibility is checked against the upstream scripts when this page
            opens, and that check has not returned an answer yet.
          </p>
          <Button variant="ghost" className="mt-3" disabled={rechecking} onClick={onRecheck}>
            {rechecking ? 'Checking…' : 'Check again'}
          </Button>
        </div>
      )}
      {/* No script path row. `script_path` is the discovery-owned answer to
          "what would actually run", and it belongs here, but
          api/catalog.py::_serialize does not serve it: it is a column on
          catalog_entries and nothing else. The per-method `script` upstream
          publishes is null in every record we hold, so there is no honest
          substitute, and inventing "ct/<slug>.sh" from the slug would be a
          guess dressed as a fact. This row appears the day _serialize
          includes it. */}
      <div className="mt-3">
        <KVGrid items={[
          ['Type', TYPE_LABEL[entry.type]],
          ['Slug', entry.slug],
        ]} />
      </div>
      {(entry.upstream_state === 'unlisted' || entry.upstream_state === 'delisted') && (
        <p className="mt-3 text-[12px] text-text-3">{UNLISTED_NOTE}</p>
      )}
    </Section>
  )
}

/** The container sizing Proxploy would use, parsed out of the ct script by
 *  discovery. Distinct from the install profiles below, which are upstream's
 *  published figures: this is the one that comes from the script we would run.
 *  Absent for rows whose script could not be parsed, and then absent from the
 *  page too. */
function DiscoveryDefaults({ entry }: { entry: CatalogEntryDetail }) {
  const items: [string, ReactNode][] = []
  const cpu = figure(entry.default_cpu)
  const mem = ram(figure(entry.default_ram_mb))
  const disk = figure(entry.default_disk_gb)
  const os = text(entry.default_os)
  const osVersion = text(entry.default_os_version)
  if (cpu != null) items.push(['vCPU', cpu])
  if (mem != null) items.push(['Memory', mem])
  if (disk != null) items.push(['Disk', `${disk} GB`])
  if (os != null) items.push(['Template', osVersion ? `${osName(os)} ${osVersion}` : osName(os)])
  if (items.length === 0) return null
  return (
    <Section title="Defaults from the install script">
      <KVGrid items={items} />
    </Section>
  )
}

/** The figures and paths one profile can actually show. Pulled out so the
 *  section can drop profiles that would render empty BEFORE deciding whether
 *  it has a section at all: a heading over nothing is exactly the blank row
 *  this page is not allowed to produce. Upstream writes 0/0/0 resources for a
 *  script that installs into an existing container rather than creating one,
 *  and "0 vCPU" would be a claim, not a blank. */
function profileItems(method: UpstreamInstallMethod): {
  items: [string, ReactNode][]; configPath: string | null
} {
  const res = method.resources ?? {}
  const cpu = figure(res.cpu)
  const mem = ram(figure(res.ram))
  const disk = figure(res.hdd)
  const os = text(res.os)
  const osVersion = text(res.version)
  const items: [string, ReactNode][] = []
  if (cpu != null) items.push(['vCPU', cpu])
  if (mem != null) items.push(['Memory', mem])
  if (disk != null) items.push(['Disk', `${disk} GB`])
  if (os != null) items.push(['Template', osVersion ? `${osName(os)} ${osVersion}` : osName(os)])
  return { items, configPath: text(method.config_path) }
}

/** One upstream install profile. An app can publish more than one (a Debian
 *  default plus an Alpine variant), and they size very differently, which is
 *  the whole reason they are listed rather than collapsed into one figure. */
function InstallProfile({ method }: { method: UpstreamInstallMethod }) {
  const kind = text(method.type)
  const { items, configPath } = profileItems(method)
  return (
    <div className="rounded-tile border border-line-soft bg-panel-2 p-3">
      {kind && (
        <div className="mb-2 font-mono text-[11px] uppercase tracking-wide text-text-3">{kind}</div>
      )}
      {items.length > 0 && <KVGrid items={items} />}
      {configPath && (
        <div className="mt-3">
          <div className="text-[10.5px] uppercase tracking-wide text-text-3">Config</div>
          <div className="mt-1 break-all font-mono text-[12px] text-text-2">{configPath}</div>
        </div>
      )}
    </div>
  )
}

function InstallProfiles({ meta }: { meta: UpstreamMetadata }) {
  const methods = asList(meta.install_methods).filter((m) => {
    const { items, configPath } = profileItems(m)
    return items.length > 0 || configPath != null
  })
  if (methods.length === 0) return null
  return (
    <Section title={methods.length > 1 ? 'Install profiles' : 'Install profile'}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {methods.map((m, i) => (
          <InstallProfile key={`${m.type ?? 'method'}-${i}`} method={m} />
        ))}
      </div>
      <p className="mt-3 text-[12px] text-text-3">
        Upstream's published sizing for each variant of this script.
      </p>
    </Section>
  )
}

/** Upstream's post-install notes, verbatim. They are the difference between a
 *  container that works and one that sits there: where the generated
 *  credentials landed, which URL to register on, what breaks if you skip a
 *  step. Rendered as plain text, never as markup. */
function Notes({ notes }: { notes: UpstreamNote[] }) {
  const usable = notes.filter((n) => text(n.text) != null)
  if (usable.length === 0) return null
  return (
    <Section title="Before and after you install">
      <ul className="space-y-2">
        {usable.map((n, i) => {
          // info | warning | warn | general | default are the values in the
          // corpus. Anything that is not clearly a warning reads as neutral,
          // rather than an unknown value being dressed up as an alarm.
          const isWarning = (n.type ?? '').toLowerCase().startsWith('warn')
          return (
            <li key={i} className={`rounded-tile border p-2.5 text-[12.5px] ${
              isWarning ? 'border-amber/30 bg-amber-dim text-text' : 'border-line-soft bg-panel-2 text-text-2'}`}>
              {isWarning && <span className="mr-2 font-mono text-[10.5px] uppercase text-amber">warning</span>}
              {text(n.text)}
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

/**
 * First-run facts: the port the app answers on and the credentials upstream
 * ships it with.
 *
 * These are PUBLISHED defaults, the same ones printed in upstream's own docs,
 * not a secret of anyone's installation, which is why they are shown rather
 * than masked. The warning next to them is the point of showing them at all.
 */
function FirstRun({ meta, port }: { meta: UpstreamMetadata; port: number | null }) {
  const user = text(meta.default_user)
  const passwd = text(meta.default_passwd)
  // Upstream repeats the app's config path on the record AND on each install
  // method, identically in almost every case. Printing it in both places
  // would read as two different paths that happen to look the same, so the
  // profile keeps it (it is per-variant there) and this only shows a path no
  // profile already showed.
  const shownByProfile = new Set(
    asList(meta.install_methods).map((m) => text(m.config_path)).filter((p) => p != null))
  const own = text(meta.config_path)
  const configPath = own != null && !shownByProfile.has(own) ? own : null
  const items: [string, ReactNode][] = []
  if (port != null) items.push(['Port', port])
  if (user != null) items.push(['Default user', user])
  if (passwd != null) items.push(['Default password', passwd])
  if (items.length === 0 && configPath == null) return null
  return (
    <Section title="First run">
      {items.length > 0 && <KVGrid items={items} />}
      {configPath && (
        <div className="mt-3">
          <div className="text-[10.5px] uppercase tracking-wide text-text-3">Config</div>
          <div className="mt-1 break-all font-mono text-[12px] text-text-2">{configPath}</div>
        </div>
      )}
      {(user != null || passwd != null) && (
        <p className="mt-3 text-[12px] text-amber">
          These are upstream's published defaults, identical on every install.
          Change them the first time you sign in.
        </p>
      )}
    </Section>
  )
}

/**
 * The upstream release the script currently targets, plus its release note.
 *
 * THE CHANGELOG IS THIRD-PARTY MARKDOWN, from GitHub release notes, and it is
 * rendered as TEXT. React escapes text children, so a release note containing
 * markup ends up on the page as the characters someone typed and never as
 * elements. There is deliberately no dangerouslySetInnerHTML here and no
 * markdown renderer either: this project has no markdown dependency, and
 * adding one is a call for the user to make, not a side effect of a page.
 * Until then the markdown stays intact and readable (headings and list
 * bullets survive as themselves), with CRLF normalised so the pre-wrap block
 * does not carry stray carriage returns.
 */
function Changelog({ github }: { github: NonNullable<UpstreamMetadata['github_data']> }) {
  const version = text(github.version)
  const changelog = plainText(github.changelog)
  const synced = when(github.github_synced_at)
  if (version == null && changelog == null) return null
  return (
    <Section title="Upstream release">
      {version && <div className="font-mono text-[14px] text-text">{version}</div>}
      {synced && (
        <div className="mt-1 text-[11.5px] text-text-3">
          As read from GitHub on {synced}.
        </div>
      )}
      {changelog && (
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-tile
                        border border-line-soft bg-panel-2 p-3 font-mono text-[11.5px] text-text-2">
          {changelog}
        </pre>
      )}
    </Section>
  )
}

/**
 * The tri-state chips. NULL MEANS UNKNOWN AND RENDERS NOTHING.
 *
 * The 9 unlisted rows have no upstream record, so we do not know whether they
 * are ARM-capable, updateable or privileged. A chip reading "not ARM" would be
 * asserting something nothing here supports; no chip is the honest rendering.
 */
function Capabilities({ meta, served }: { meta: UpstreamMetadata; served: ServedPresentation }) {
  // Both the serialized columns and the cached record carry these, and they
  // are the same presentation facts from the same sync: the columns are
  // written FROM this record. The column wins when it has a value, and the
  // record fills in the rows a column-adding migration has not backfilled yet.
  const pick = <T,>(column: T | null | undefined, cached: T | null | undefined): T | null =>
    column ?? cached ?? null
  const hasArm = pick(served.has_arm, meta.has_arm)
  const privileged = pick(served.privileged, meta.privileged)
  const updateable = pick(served.updateable, meta.updateable)
  const architectures = asList(pick(served.architectures, meta.architectures))
    .map((a) => text(a)).filter((a): a is string => a != null)
  const platforms = asList(meta.platforms).map((p) => text(p)).filter((p): p is string => p != null)
  const chips: ReactNode[] = []
  if (hasArm === true) chips.push(<Chip key="arm">Runs on ARM</Chip>)
  if (hasArm === false) chips.push(<Chip key="arm">x86 only</Chip>)
  if (updateable === true) chips.push(<Chip key="upd">Updateable in place</Chip>)
  if (privileged === true) {
    chips.push(
      <Chip key="priv" tone="amber"
        title="This script needs a privileged container, which shares more of the host than an unprivileged one does.">
        Needs a privileged container
      </Chip>)
  }
  if (privileged === false) chips.push(<Chip key="priv">Unprivileged container</Chip>)
  for (const a of architectures) chips.push(<Chip key={`arch-${a}`}>{a}</Chip>)
  for (const p of platforms) chips.push(<Chip key={`plat-${p}`}>{p}</Chip>)
  if (chips.length === 0) return null
  return (
    <Section title="Container">
      <div className="flex flex-wrap gap-1.5">{chips}</div>
    </Section>
  )
}

/**
 * THE ONE PLACE THE RAW POPULARITY FIGURE IS ALLOWED, and only alongside the
 * whole caveat, on the page, in words. The card shows a coarse band precisely
 * because a bare number invites a reading it cannot carry.
 *
 * Every clause below is load-bearing:
 *  - it counts install ATTEMPTS of the upstream script, so runs that failed or
 *    were aborted are in it, and nothing ever reports an uninstall,
 *  - the telemetry is opt-in, so it is a lower bound by an unknown multiple,
 *  - it comes through a 23-hour server-side cache, so it can be a day old,
 *  - it is a count, not a rating.
 * A null figure renders NOTHING. Never a zero: "0" would be a measurement.
 */
function Popularity({ entry, served }: {
  entry: CatalogEntryDetail; served: ServedPresentation
}) {
  if (entry.popularity == null) return null
  const asOf = when(served.popularity_synced_at)
  return (
    <Section title="Reported installs">
      <div className="font-mono text-[18px] text-text">{entry.popularity.toLocaleString()}</div>
      {asOf && <div className="mt-1 text-[11.5px] text-text-3">As of {asOf}.</div>}
      <p className="mt-3 text-[12px] text-text-2">
        Install attempts of the upstream script reported by opt-in telemetry,
        including attempts that failed or were cancelled. Nothing reports an
        uninstall, so this never goes down. Because the telemetry is opt-in it
        is a lower bound, higher than shown by an unknown multiple, and it is
        refreshed at most once every 23 hours, so it can be a day out of date.
        It counts attempts. It is not a rating and says nothing about quality.
      </p>
    </Section>
  )
}

function LinkRow({ label, href }: { label: string; href: string }) {
  return (
    <li>
      <a href={href} target="_blank" rel="noreferrer"
        className="text-[12.5px] text-amber hover:underline">
        {label}
      </a>
      <span className="ml-2 break-all font-mono text-[11px] text-text-3">{href}</span>
    </li>
  )
}

function Links({ meta, entry, served }: {
  meta: UpstreamMetadata; entry: CatalogEntryDetail; served: ServedPresentation
}) {
  // website and docs_url are already served as top-level columns (mapped from
  // upstream's `website` and `documentation`), so those two prefer the column
  // and fall back to the cached record; the rest exist only in the record.
  const rows: { label: string; href: string }[] = []
  const push = (label: string, href: string | null | undefined) => {
    const h = text(href)
    if (h != null && !rows.some((r) => r.href === h)) rows.push({ label, href: h })
  }
  push('Website', entry.website ?? meta.website)
  push('Documentation', entry.docs_url ?? meta.documentation)
  push('Source', meta.github ?? meta.repository)
  push('Last script change', meta.last_update_commit)
  const created = when(served.script_created ?? meta.script_created, true)
  const updated = when(served.script_updated ?? meta.script_updated, true)
  if (rows.length === 0 && created == null && updated == null) return null
  return (
    <Section title="Upstream">
      {rows.length > 0 && (
        <ul className="space-y-1.5">
          {rows.map((r) => <LinkRow key={r.href} label={r.label} href={r.href} />)}
        </ul>
      )}
      {(created != null || updated != null) && (
        <div className={rows.length > 0 ? 'mt-4' : ''}>
          <KVGrid items={[
            ...(created != null ? [['Script added', created] as [string, ReactNode]] : []),
            ...(updated != null ? [['Script updated', updated] as [string, ReactNode]] : []),
          ]} />
        </div>
      )}
    </Section>
  )
}

export function StoreDetailPage() {
  const { slug } = useParams({ strict: false }) as { slug: string }
  const entryQuery = useCatalogEntry(slug)

  if (entryQuery.isError) {
    // A 404 is a different answer from "the backend is down", and saying
    // "could not reach the backend" about a slug that simply does not exist
    // sends the reader off to check their network for nothing.
    const notFound = entryQuery.error instanceof ApiError && entryQuery.error.status === 404
    return (
      <div>
        <Link to={'/store' as never} className="text-[12px] text-text-3 hover:text-text">
          ← App Store
        </Link>
        <div className="mt-4">
          <EmptyState
            title={notFound ? `No app called “${slug}”` : 'This app could not be loaded'}
            note={notFound
              ? 'Nothing in the catalog has that slug. It may have been renamed upstream, or the catalog may not have been refreshed since it appeared.'
              : 'Proxploy could not reach the backend to read this catalog entry.'} />
        </div>
      </div>
    )
  }
  if (entryQuery.isPending || entryQuery.data === undefined) return <LoadingBlock />

  const entry = entryQuery.data
  const meta = readUpstreamMetadata(entry.raw)
  const served = readServed(entry)
  const name = text(entry.name) ?? entry.slug
  const description = text(entry.description) ?? text(meta?.description)
  const notes = asList(meta?.notes)
  const github = meta?.github_data ?? null
  // Presentation fact, same as the capability chips: prefer the column, fall
  // back to the cached record it was written from.
  const port = figure(served.port ?? meta?.port)

  return (
    <div>
      <Link to={'/store' as never} className="text-[12px] text-text-3 hover:text-text">
        ← App Store
      </Link>

      <div className="mt-2 mb-5 flex items-start gap-4">
        <DetailIcon name={name} iconUrl={entry.icon_url} />
        <div className="min-w-0">
          <h1 className="font-display text-[22px] font-semibold">{name}</h1>
          <div className="mt-0.5 font-mono text-[12px] text-text-3">
            {entry.slug}
            {text(entry.category) ? ` · ${entry.category}` : ''}
            {` · ${TYPE_LABEL[entry.type]}`}
          </div>
          {description && (
            <p className="mt-2 max-w-3xl text-[13px] text-text-2">{description}</p>
          )}
        </div>
      </div>

      <div className="space-y-4">
        <Feasibility entry={entry}
          rechecking={entryQuery.isFetching}
          onRecheck={() => { void entryQuery.refetch() }} />
        <DiscoveryDefaults entry={entry} />
        <InstallProfiles meta={meta ?? {}} />
        <Notes notes={notes} />
        {/* `meta ?? {}` rather than a guard: an uncovered row still has a port
            from the served column, and still has website/docs_url columns and
            script dates worth linking. These sections drop themselves when
            they find nothing, which is what makes the unlisted rows render a
            shorter page rather than a broken one. */}
        <FirstRun meta={meta ?? {}} port={port} />
        {github && <Changelog github={github} />}
        <Capabilities meta={meta ?? {}} served={served} />
        <Popularity entry={entry} served={served} />
        <Links meta={meta ?? {}} entry={entry} served={served} />
      </div>
    </div>
  )
}

// Registered in router.tsx next to storeRoute. `/store` is a static path and
// this is a dynamic one, so the router ranks the exact match first and the two
// never compete. This path is not invented here: backend/proxploy/api/search.py
// already emits `href: /store/{slug}` for command-palette results, so making
// the route exist is what makes those results land somewhere.
export const storeDetailRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/store/$slug',
  component: StoreDetailPage,
})
