# Host Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the host page Overview as a two-column surface — a sticky
identity rail on the left, live activity on the right — with one unified guest
list and an explicit note where a non-entry node's charts used to be silently
absent.

**Architecture:** `HostFacts`' flat 17-row strip becomes `NodeIdentityRail`,
which keeps the same two-source merge (poller snapshot + the node's own
`/status`) but organises it into four labelled groups and suppresses any group
whose rows all vanished. The `AppCard` grid and the bare VM table collapse into
one `GuestList` whose rows carry what `AppCard` carried, so VMs gain controls
rather than apps losing them. `NodeOverview` then wraps the two in a
`lg:grid-cols-[290px_minmax(0,1fr)]` grid.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (`@theme inline`, no config
file), TanStack Query + Router, Vitest 4 + Testing Library. **No new
dependencies.**

## Global Constraints

Copied from `docs/superpowers/specs/2026-08-12-host-page-visual-rebuild-design.md`:

- **Plain Tailwind and the existing tokens.** No shadcn, no `cva`, no `cn`, no
  token alias layer. The stage-1 machinery stays abandoned; this plan neither
  revives nor assumes it.
- **No hardcoded colours.** `src/tests/no-hardcoded-colors.test.ts` fails the
  build on a literal hex in a non-allowlisted file. Every new class is a token
  class (`text-text-3`, `border-line-soft`, `bg-panel`). Gradients come from
  the existing exports in `components/UsageBar.tsx`.
- **Light theme is real.** `[data-theme="light"]` must keep working; never pin
  a dark value.
- **Baseline:** `npm test` → 61 files, 433 passed, 5 skipped. Green before, green
  after.
- **`docs/06-frontend-spec.md` is normative.** Update it in the same commit as
  the component it describes (Task 4).
- **Do not kill ports 8000/5173 and do not run Playwright.** The user runs the
  dev servers. Screenshots via `.claude/skills/run-proxploy/driver.mjs shot`
  are fine and touch neither.
- **The host page is behind auth and the driver cannot log in.** No task in
  this plan can be screenshot-verified by the agent. See "Done when".
- **`AppCard`, `KVGrid`, `UsageBar`, `StatusPill`, `MetricChart` are not
  touched.** `AppCard` keeps its two other callers (`routes/apps.tsx`, and the
  cluster overview preview at `routes/hosts.tsx:257`).

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/components/NodeIdentityRail.tsx` (create) | The left rail: usage bars, four labelled fact groups, empty-group suppression, and the snapshot + `/status` merge moved across from `HostFacts`. |
| `frontend/src/components/HostFacts.tsx` (delete) | Replaced by the rail. Imported only by `routes/hosts.tsx` and its own test. |
| `frontend/src/components/GuestList.tsx` (create) | One row shape for apps and VMs, plus `toGuests()` which normalises `AppRow`/`VmRow` into the row model. |
| `frontend/src/routes/hosts.tsx` (modify) | `useNodeContext` gains `entry`; `NodeOverview` gains the grid, the non-entry note, and swaps in the two new components. |
| `frontend/src/tests/node-identity-rail.test.tsx` (create) | Replaces `host-facts.test.tsx`. Group rendering, degradation, and the empty-group rule. |
| `frontend/src/tests/host-facts.test.tsx` (delete) | Its component is gone; its assertions move to the rail test. |
| `frontend/src/tests/guest-list.test.tsx` (create) | Both kinds in one list, the memory asymmetry, lifecycle actions on both. |
| `frontend/src/tests/hosts.test.tsx` (modify) | The `NodeOverview` strip assertion, the non-entry note, and the guest list. |
| `docs/06-frontend-spec.md` (modify) | The host page section, rewritten to match what shipped. |

---

### Task 1: `NodeIdentityRail`

**Files:**
- Create: `frontend/src/components/NodeIdentityRail.tsx`
- Create: `frontend/src/tests/node-identity-rail.test.tsx`
- Delete: `frontend/src/components/HostFacts.tsx`
- Delete: `frontend/src/tests/host-facts.test.tsx`
- Modify: `frontend/src/routes/hosts.tsx` (import and call site only)
- Modify: `frontend/src/tests/hosts.test.tsx` (one assertion)

**Interfaces:**
- Consumes: `NodeRow` from `../api/hooks`, `api` from `../api/client`,
  `fmtBytes`/`fmtUptime` from `../lib/format`, and
  `CPU_GRADIENT`/`RAM_GRADIENT`/`STORAGE_GRADIENT`/`UsageBar` from `./UsageBar`.
- Produces: `NodeIdentityRail({ hostId: number, node: string, snapshot: NodeRow })`.
  Task 4 renders it as the left grid child.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/node-identity-rail.test.tsx`:

```tsx
/** The host page's identity rail: what this machine is, in four groups. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let status: unknown = null
let fails = false

vi.mock('../api/client', () => ({
  api: vi.fn(() => (fails ? Promise.reject(new Error('502')) : Promise.resolve(status))),
  ApiError: class extends Error {},
}))

import type { NodeRow } from '../api/hooks'
import { NodeIdentityRail } from '../components/NodeIdentityRail'

/** The poller's snapshot. Deliberately carrying figures that DIFFER from the
 *  status payload's rootfs by orders of magnitude, because on a real node they
 *  do: this is the deduped datastore aggregate, that is one filesystem. */
const snapshot = (over: Partial<NodeRow> = {}): NodeRow => ({
  host_id: 1, name: 'host-01', node: 'pve1', status: 'connected', is_entry: true,
  cluster: null, pve_version: '9.2.10', cpu_pct: 0.14, mem_pct: 6.5,
  mem_bytes: 2161287168, mem_total_bytes: 33306869760,
  disk_pct: 0.3, disk_bytes: 6442450944, disk_total_bytes: 2000398934016,
  uptime_s: 25029, apps: 3, apps_running: 2, vms: 2, vms_running: 1,
  last_seen_at: null, ...over,
})

const wrap = (snap: NodeRow = snapshot()) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <NodeIdentityRail hostId={1} node="pve1" snapshot={snap} />
    </QueryClientProvider>)
}

describe('NodeIdentityRail', () => {
  beforeEach(() => {
    fails = false
    status = {
      node: 'pve1', uptime_s: 25029, pve_version: 'pve-manager/9.2.10/43df2e01f27a1a19',
      kernel: '7.0.14-11-pve', arch: 'x86_64', boot_mode: 'efi', secure_boot: false,
      cpu: { model: '13th Gen Intel(R) Core(TM) i5-13500T', vendor: 'GenuineIntel',
             sockets: 1, cores: 14, threads: 20, mhz: '800.000' },
      load: [2.0, 1.0, 0.5], io_delay: 0.00027,
      memory: { total: 33306869760, used: 2161287168 },
      swap: { total: 8589930496, used: 0 },
      rootfs: { total: 100861726720, used: 6425862144 },
    }
  })

  it('names all four groups when the node answers', async () => {
    wrap()
    expect(await screen.findByText('Processor')).toBeInTheDocument()
    expect(screen.getByText('Identity')).toBeInTheDocument()
    expect(screen.getByText('Memory & storage')).toBeInTheDocument()
    expect(screen.getByText('Boot')).toBeInTheDocument()
  })

  it('separates physical cores from threads', async () => {
    wrap()
    expect(await screen.findByText(/14 physical/i)).toBeInTheDocument()
    expect(screen.getByText(/20 logical/i)).toBeInTheDocument()
  })

  it('shows the processor model and kernel', async () => {
    wrap()
    expect(await screen.findByText(/i5-13500T/)).toBeInTheDocument()
    expect(screen.getByText('7.0.14-11-pve')).toBeInTheDocument()
  })

  it('normalises load by thread count, and still shows the raw triple', async () => {
    wrap()
    // 2.0 over 20 threads is 10% busy, not "200% of one core".
    expect(await screen.findByText(/10%/)).toBeInTheDocument()
    expect(screen.getByText(/2\.00 · 1\.00 · 0\.50/)).toBeInTheDocument()
  })

  it('renders IO delay as a percentage rather than a raw fraction', async () => {
    wrap()
    expect(await screen.findByText(/0\.03%/)).toBeInTheDocument()
  })

  it('shows the PVE version without the manager prefix and build hash', async () => {
    wrap()
    expect(await screen.findByText('9.2.10')).toBeInTheDocument()
  })

  it('keeps the datastore total and the root filesystem apart', async () => {
    // On a real node these differ by orders of magnitude. Collapsing them into
    // one "Storage" row would answer neither question honestly.
    wrap()
    expect(await screen.findByText('Root filesystem')).toBeInTheDocument()
    // 'Storage' names both the fact row and the bar above it, hence getAllBy.
    expect(screen.getAllByText('Storage').length).toBeGreaterThan(0)
    expect(screen.getByText('6.0 GiB / 1.8 TiB')).toBeInTheDocument()      // datastores
    expect(screen.getByText('6.0 GiB / 93.9 GiB')).toBeInTheDocument()     // rootfs
  })

  it('costs the status-only rows, not the rail, when the node refuses to be read', async () => {
    // A token too narrow for /nodes/{n}/status must not cost the page the
    // facts the poller already had.
    fails = true
    wrap()
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.getByText('Node')).toBeInTheDocument()
    expect(screen.getByText('9.2.10')).toBeInTheDocument()
    expect(screen.getByText('6h 57m')).toBeInTheDocument()
    expect(screen.getByText('2.0 GiB / 31.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('6.0 GiB / 1.8 TiB')).toBeInTheDocument()
    // and the rows only the node itself can answer are simply absent
    expect(screen.queryByText('Processor')).not.toBeInTheDocument()
    expect(screen.queryByText('Kernel')).not.toBeInTheDocument()
    expect(screen.queryByText('IO delay')).not.toBeInTheDocument()
    expect(screen.queryByText('Root filesystem')).not.toBeInTheDocument()
  })

  // This is the rule grouping ADDS. Without it, a refused /status leaves a
  // "Processor" heading over nothing and a "Boot" heading over nothing —
  // grouping would have made the degraded case worse than the flat strip.
  it('renders no heading for a group whose rows all vanished', async () => {
    fails = true
    wrap()
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.getByText('Memory & storage')).toBeInTheDocument()
    expect(screen.queryByText('Processor')).not.toBeInTheDocument()
    expect(screen.queryByText('Boot')).not.toBeInTheDocument()
  })

  // The counts moved to the "Guests on this host (n)" heading, which already
  // carried a total. Two places stating the same count is the duplication the
  // 2026-08-11 "one KV strip, not two" commit removed.
  it('does not restate the guest counts the guests heading already carries', async () => {
    wrap()
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.queryByText('2/3 running')).not.toBeInTheDocument()
    expect(screen.queryByText('1/2 running')).not.toBeInTheDocument()
  })

  it('survives a node that reports no cpuinfo at all', async () => {
    status = { node: 'pve1', uptime_s: null, pve_version: null, kernel: null,
               arch: null, boot_mode: null, secure_boot: false,
               cpu: { model: null, vendor: null, sockets: null, cores: null,
                      threads: null, mhz: null },
               load: [0, 0, 0], io_delay: null, memory: {}, swap: {}, rootfs: {} }
    wrap()
    expect(await screen.findByText(/\? physical/)).toBeInTheDocument()
    // and it must not divide by a zero thread count
    expect(screen.getAllByText('0%').length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/node-identity-rail.test.tsx
```

Expected: FAIL — `Failed to resolve import "../components/NodeIdentityRail"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/NodeIdentityRail.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { NodeRow } from '../api/hooks'
import { fmtBytes, fmtUptime } from '../lib/format'
import { CPU_GRADIENT, RAM_GRADIENT, STORAGE_GRADIENT, UsageBar } from './UsageBar'

/** GET /hosts/{id}/nodes/{node}/status, normalised by the backend. */
type Status = {
  node: string
  uptime_s: number | null
  pve_version: string | null
  kernel: string | null
  arch: string | null
  boot_mode: string | null
  secure_boot: boolean
  cpu: {
    model: string | null; vendor: string | null; sockets: number | null
    cores: number | null; threads: number | null; mhz: string | null
  }
  load: number[]
  io_delay: number | null
  memory: { total?: number; used?: number }
  swap: { total?: number; used?: number }
  rootfs: { total?: number; used?: number }
}

type Fact = [string, string]

const pct = (used?: number | null, total?: number | null) =>
  total ? Math.round(((used ?? 0) / total) * 1000) / 10 : 0

/** "pve-manager/9.2.10/43df2e01f27a1a19" is a package string, not a version an
 *  operator reads out loud. */
function shortPve(raw: string | null): string {
  return raw?.split('/')[1] ?? 'unknown'
}

/** Everything the host page knows about this node, as a rail beside the
 *  activity rather than a strip above it.
 *
 *  Two sources, deliberately merged rather than stacked in two cards: the
 *  poller's snapshot (`snapshot`, always present, and the only source anywhere
 *  for the deduped datastore fill) and the node's own /status (on demand, and
 *  refusable by a narrow token).
 *
 *  The snapshot half ALWAYS renders. Only the status-only rows disappear when
 *  the node will not answer — and a group left with no rows renders no heading,
 *  because a "Processor" label over nothing is worse than the flat strip this
 *  replaced.
 */
export function NodeIdentityRail({ hostId, node, snapshot }: {
  hostId: number
  node: string
  snapshot: NodeRow
}) {
  const q = useQuery({
    queryKey: ['hosts', hostId, 'node', node, 'status'],
    queryFn: () => api<Status>(`/hosts/${hostId}/nodes/${node}/status`),
    retry: false,
  })
  const s = q.data ?? null

  // Load normalised by thread count. A raw 14 means nothing until you know
  // the box has 20 threads; the raw triple stays beside it because the
  // normalised number alone hides the 1/5/15 trend.
  const threads = s?.cpu.threads || 1
  const loadPct = s ? Math.round(((s.load[0] ?? 0) / threads) * 1000) / 10 : 0

  // Memory and uptime are in BOTH sources and agree; the snapshot is used so
  // that the row does not move or empty when /status is refused.
  const identity: Fact[] = [
    ['Node', snapshot.node ?? 'unknown'],
    ['PVE version', s ? shortPve(s.pve_version) : snapshot.pve_version ?? 'unknown'],
  ]
  if (s) {
    identity.push(
      ['Kernel', s.kernel ?? 'unknown'],
      ['Architecture', s.arch ?? 'unknown'],
    )
  }
  identity.push(['Uptime', fmtUptime(snapshot.uptime_s)])

  const processor: Fact[] = []
  if (s) {
    processor.push(
      ['Model', s.cpu.model ?? 'unknown'],
      ['Cores', `${s.cpu.cores ?? '?'} physical · ${s.cpu.threads ?? '?'} logical`],
      ['Sockets', String(s.cpu.sockets ?? 'unknown')],
      ['Load (1 · 5 · 15)', s.load.map((n) => n.toFixed(2)).join(' · ')],
      ['IO delay', s.io_delay != null ? `${(s.io_delay * 100).toFixed(2)}%` : 'unknown'],
    )
  }

  const storage: Fact[] = [
    ['Memory', `${fmtBytes(snapshot.mem_bytes)} / ${fmtBytes(snapshot.mem_total_bytes)}`],
    // The datastore aggregate this node can actually use, shared pools
    // deduped by pollers._disk_pct. NOT the same number as the root
    // filesystem below, and on a real node not even the same order of
    // magnitude, so the two are named apart rather than collapsed.
    ['Storage', `${fmtBytes(snapshot.disk_bytes)} / ${fmtBytes(snapshot.disk_total_bytes)}`],
  ]
  if (s) {
    storage.push(
      ['Root filesystem', `${fmtBytes(s.rootfs.used ?? 0)} / ${fmtBytes(s.rootfs.total ?? 0)}`],
      ['Swap', `${fmtBytes(s.swap.used ?? 0)} / ${fmtBytes(s.swap.total ?? 0)}`],
    )
  }

  const boot: Fact[] = []
  if (s) {
    boot.push(['Mode', `${s.boot_mode ?? 'unknown'}${s.secure_boot ? ' · secure boot' : ''}`])
  }

  const groups: { title: string; items: Fact[] }[] = [
    { title: 'Identity', items: identity },
    { title: 'Processor', items: processor },
    { title: 'Memory & storage', items: storage },
    { title: 'Boot', items: boot },
  ]

  return (
    <div className="space-y-5 rounded-card border border-line-soft bg-panel p-5">
      <div className="space-y-3">
        {/* Load and Root are status-only and stay that way: a node that
            refuses /status shows two bars, not four. */}
        {s && <Bar label="Load" pct={loadPct} gradient={CPU_GRADIENT} />}
        <Bar label="RAM" pct={snapshot.mem_pct ?? pct(snapshot.mem_bytes, snapshot.mem_total_bytes)}
          gradient={RAM_GRADIENT} />
        <Bar label="Storage" pct={snapshot.disk_pct ?? pct(snapshot.disk_bytes, snapshot.disk_total_bytes)}
          gradient={STORAGE_GRADIENT} />
        {s && <Bar label="Root" pct={pct(s.rootfs.used, s.rootfs.total)} gradient={STORAGE_GRADIENT} />}
      </div>
      {groups.filter((g) => g.items.length > 0).map((g) => (
        <FactGroup key={g.title} title={g.title} items={g.items} />
      ))}
    </div>
  )
}

/** Label left, value right — not KVGrid, whose label-above-value grid is built
 *  for wide containers and would waste most of a 290px rail. */
function FactGroup({ title, items }: { title: string; items: Fact[] }) {
  return (
    <section>
      <h3 className="mb-2 border-b border-line-soft pb-1.5 text-[10px] uppercase tracking-[.09em] text-text-3">
        {title}
      </h3>
      <dl className="space-y-1">
        {items.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3">
            <dt className="text-[11px] text-text-3">{k}</dt>
            <dd className="text-right font-mono text-[11px] text-text">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function Bar({ label, pct, gradient }: { label: string; pct: number; gradient: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[.09em] text-text-3">{label}</span>
        <span className="font-mono text-[11px] text-text-2">{pct}%</span>
      </div>
      <div className="mt-1"><UsageBar pct={pct} gradient={gradient} /></div>
    </div>
  )
}
```

- [ ] **Step 4: Run the test**

```bash
cd frontend && npx vitest run src/tests/node-identity-rail.test.tsx
```

Expected: PASS, 11 tests.

- [ ] **Step 5: Swap it into the page and delete `HostFacts`**

In `frontend/src/routes/hosts.tsx`, replace the import on line 13:

```tsx
import { NodeIdentityRail } from '../components/NodeIdentityRail'
```

and the call site inside `NodeOverview` (the `{node.node && <HostFacts .../>}`
block). Replace the whole block, comment included, with:

```tsx
          {/* One rail, two sources. NodeIdentityRail merges the poller's
              snapshot (always there, and the only source for the deduped
              datastore fill) with the node's own /status (on demand, refusable
              by a narrow token), so a node that will not answer loses rows —
              and whole groups — rather than the whole card. */}
          {node.node && (
            <NodeIdentityRail hostId={id} node={node.node} snapshot={node} />
          )}
```

Then delete both files:

```bash
cd frontend && rm src/components/HostFacts.tsx src/tests/host-facts.test.tsx
```

- [ ] **Step 6: Fix the one `hosts.test.tsx` assertion that named the counts**

`NodeOverview`'s test at `src/tests/hosts.test.tsx` — "reports storage used /
total alongside the guest counts, in ONE strip" — asserts on a pairing that no
longer exists, because the counts moved to the guests heading. Rename it and
drop the count assertions, keeping the storage one:

```tsx
  it('reports storage used / total in the identity rail', async () => {
```

Delete from its body any `getByText('2/3 running')` / `getByText('1/2 running')`
assertions. Leave every other test in the file alone.

- [ ] **Step 7: Verify the whole suite and the type-check**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: green. Test-file count stays 61 (one deleted, one created); the total
passes changes by the delta between the old and new test counts. `oxlint`
warnings must stay at 44 — a new one means the new file introduced it.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/NodeIdentityRail.tsx frontend/src/tests/node-identity-rail.test.tsx \
        frontend/src/components/HostFacts.tsx frontend/src/tests/host-facts.test.tsx \
        frontend/src/routes/hosts.tsx frontend/src/tests/hosts.test.tsx
git commit -m "refactor(hosts): seventeen facts at one weight become four named groups"
```

---

### Task 2: `GuestList`

**Files:**
- Create: `frontend/src/components/GuestList.tsx`
- Create: `frontend/src/tests/guest-list.test.tsx`
- Modify: `frontend/src/routes/hosts.tsx` (`NodeOverview`'s guests section)

**Interfaces:**
- Consumes: `AppRow`/`VmRow` from `../api/hooks`, `LifecycleActions` from
  `./LifecycleActions`, `StatusPill` from `./StatusPill`, `Button` from
  `./ui/button`, `CPU_GRADIENT`/`UsageBar` from `./UsageBar`,
  `fmtBytes`/`fmtPct` from `../lib/format`.
- Produces: `toGuests(apps: AppRow[], vms: VmRow[]): Guest[]` and
  `GuestList({ guests: Guest[] })`, where
  `Guest = { kind: 'app' | 'vm'; id: number; name: string; label: string;
  status: string; cpu_pct: number | null; mem: string }`.

**Read this before starting.** `AppCard` carries an icon tile, an update badge,
`host · CT id`, a status pill, CPU and RAM bars, `LifecycleActions` and a
Console button. The VM table row carries name, VMID and a status pill.
Unification goes **upward** — VMs gain controls; apps lose nothing but the icon
tile and the update badge, which the apps page still shows. Flattening both to
a bare row would strip working controls off every app on this page.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/guest-list.test.tsx`:

```tsx
/** One list, two kinds of guest. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Path-aware on purpose. LifecycleActions calls useEntitlements, whose `has`
// reads `q.data?.features[key]` — the optional chain guards `data`, NOT
// `features`. Resolving every call to [] would make `[].features[key]` throw,
// and the failure would look like a GuestList bug.
vi.mock('../api/client', () => ({
  api: vi.fn((path: string) =>
    path === '/entitlements'
      ? Promise.resolve({ tier: 'pro', features: { 'apps.lifecycle': true, 'vms.lifecycle': true } })
      : Promise.resolve([])),
  ApiError: class extends Error {},
}))

// GuestList uses only useNavigate; LifecycleActions imports no router at all.
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

import type { AppRow, VmRow } from '../api/hooks'
import { GuestList, toGuests } from '../components/GuestList'

const app = (over: Partial<AppRow> = {}): AppRow => ({
  id: 7, name: 'jellyfin', slug: 'jellyfin', host_id: 1, host_name: 'host-01',
  node: 'pve1', ctid: 104, category: null, catalog_slug: null,
  icon_initials: null, icon_colors: null, web_port: null, web_protocol: null,
  web_path: null, status: 'running', ip: null, cpu_pct: 12,
  mem_bytes: 2161287168, mem_total_bytes: 4294967296, uptime_s: 100,
  update_available: null, adopted: false, ...over,
})

const vm = (over: Partial<VmRow> = {}): VmRow => ({
  id: 3, host_id: 1, host_name: 'host-01', vmid: 201, name: 'win11-lab',
  status: 'stopped', os_type: 'win11', cpu_cores: 4, cpu_pct: 0,
  mem_bytes: 2161287168, disk_bytes: null, uptime_s: null, synced_at: null,
  ...over,
})

const wrap = (guests = toGuests([app()], [vm()])) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <GuestList guests={guests} />
    </QueryClientProvider>)
}

describe('GuestList', () => {
  it('puts apps and VMs in one list, each saying which it is', () => {
    wrap()
    expect(screen.getByText('jellyfin')).toBeInTheDocument()
    expect(screen.getByText('win11-lab')).toBeInTheDocument()
    expect(screen.getByText('app')).toBeInTheDocument()
    expect(screen.getByText('vm')).toBeInTheDocument()
  })

  it('names the guest by the id its operator types, not its row id', () => {
    wrap()
    expect(screen.getByText('CT 104')).toBeInTheDocument()
    expect(screen.getByText('VM 201')).toBeInTheDocument()
  })

  // VmRow has mem_bytes but no mem_total_bytes. Rendering a VM's memory as a
  // percentage would mean inventing the denominator, so the app gets "x / y"
  // and the VM gets the figure it actually has.
  it('shows a total only for the side that knows one', () => {
    wrap()
    expect(screen.getByText('2.0 GiB / 4.0 GiB')).toBeInTheDocument()
    expect(screen.getByText('2.0 GiB')).toBeInTheDocument()
  })

  it('gives both kinds their lifecycle controls', async () => {
    wrap()
    // Exact names, not /start/i — LifecycleActions renders Stop AND Restart
    // for a running guest, and /start/i matches "Restart" too, which would
    // make getByRole throw on multiple matches rather than assert anything.
    // The running app supplies Stop, the stopped VM supplies Start.
    expect(await screen.findByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument()
  })

  it('offers a console for both kinds', () => {
    wrap()
    expect(screen.getAllByRole('button', { name: 'Console' })).toHaveLength(2)
  })

  it('renders nothing but keeps its shape when there are no guests', () => {
    wrap([])
    expect(screen.queryByText('app')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/guest-list.test.tsx
```

Expected: FAIL — `Failed to resolve import "../components/GuestList"`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/GuestList.tsx`:

```tsx
import { useNavigate } from '@tanstack/react-router'
import type { AppRow, VmRow } from '../api/hooks'
import { fmtBytes, fmtPct } from '../lib/format'
import { LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { Button } from './ui/button'
import { CPU_GRADIENT, UsageBar } from './UsageBar'

export type Guest = {
  kind: 'app' | 'vm'
  id: number
  name: string
  /** "CT 104" / "VM 201" — the id an operator actually types. */
  label: string
  status: string
  cpu_pct: number | null
  /** Pre-formatted, because only the app side has a total to divide by. */
  mem: string
}

/** Apps first, then VMs: the host page lists what Proxploy installed before
 *  what it merely found. Within each kind the server's order is kept. */
export function toGuests(apps: AppRow[], vms: VmRow[]): Guest[] {
  return [
    ...apps.map((a): Guest => ({
      kind: 'app', id: a.id, name: a.name, label: `CT ${a.ctid}`,
      status: a.status, cpu_pct: a.cpu_pct,
      mem: a.mem_total_bytes
        ? `${fmtBytes(a.mem_bytes)} / ${fmtBytes(a.mem_total_bytes)}`
        : fmtBytes(a.mem_bytes),
    })),
    ...vms.map((v): Guest => ({
      kind: 'vm', id: v.id, name: v.name, label: `VM ${v.vmid}`,
      status: v.status, cpu_pct: v.cpu_pct,
      // No mem_total_bytes on VmRow. Inventing one to make the two rows match
      // would be making up a number.
      mem: fmtBytes(v.mem_bytes),
    })),
  ]
}

/** One row shape for both kinds of guest.
 *
 *  This replaces an AppCard grid beside a bare three-column VM table. The
 *  unification goes upward on purpose: VMs gain the CPU bar, the lifecycle
 *  controls and the console that apps already had, rather than apps being
 *  flattened to name/id/status to match the VMs. */
export function GuestList({ guests }: { guests: Guest[] }) {
  return (
    <div className="rounded-card border border-line-soft bg-panel">
      {guests.map((g) => <GuestRow key={`${g.kind}-${g.id}`} guest={g} />)}
    </div>
  )
}

function GuestRow({ guest: g }: { guest: Guest }) {
  const navigate = useNavigate()
  const detail = g.kind === 'app' ? '/apps/$appId' : '/vms/$vmId'
  const consolePath = g.kind === 'app' ? '/apps/$appId/console' : '/vms/$vmId/console'
  const params = g.kind === 'app'
    ? { appId: String(g.id) }
    : { vmId: String(g.id) }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line-soft
                    px-4 py-3 first:border-t-0">
      {/* basis-full below sm puts the name on its own line and lets the id,
          status and usage wrap beneath it; sm:basis-auto resolves the row. */}
      <button type="button"
        className="min-w-0 basis-full text-left font-mono text-[13px] text-text
                   transition hover:text-amber sm:basis-auto"
        onClick={() => navigate({ to: detail as never, params: params as never })}>
        {g.name}
      </button>
      <span className="rounded-full border border-line-soft bg-panel-2 px-2 py-0.5
                       font-mono text-[10px] uppercase text-text-2">
        {g.kind}
      </span>
      <span className="font-mono text-[11px] text-text-3">{g.label}</span>
      <StatusPill status={g.status} />
      <div className="flex w-28 items-center gap-2">
        <div className="flex-1"><UsageBar pct={g.cpu_pct} gradient={CPU_GRADIENT} /></div>
        <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(g.cpu_pct)}</span>
      </div>
      <span className="font-mono text-[11px] text-text-2">{g.mem}</span>
      <div className="ml-auto flex items-center gap-2">
        <LifecycleActions target={g.kind} id={g.id} name={g.name} status={g.status} size="sm" />
        <Button variant="ghost" className="px-2 py-1 text-[11px]"
          onClick={() => navigate({ to: consolePath as never, params: params as never })}>
          Console
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the test**

```bash
cd frontend && npx vitest run src/tests/guest-list.test.tsx
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Swap it into the page**

In `frontend/src/routes/hosts.tsx`, inside `NodeOverview`, replace the two
`QueryState` blocks (the app grid and the VM table) with one. The heading keeps
its combined count. Add `import { GuestList, toGuests } from '../components/GuestList'`
and drop the now-unused `AppCard` import **only if** no other function in the
file uses it — `HostsPage` does, at the 8-app preview, so **keep the import**.

```tsx
      <div className="mt-5">
        {/* "on this host", not "on this node": neither apps nor vms records
            which node of the cluster a guest sits on, so this list is
            host-wide and says so. */}
        <h2 className="mb-3 font-display text-[16px] font-semibold">
          Guests on this host ({(apps?.length ?? 0) + (vms?.length ?? 0)})
        </h2>
        <QueryState query={nodeAppsQuery}
                    emptyTitle="No guests on this node"
                    emptyNote="Installed or adopted apps and QEMU guests on this node appear here."
                    errorTitle="Guests not readable"
                    errorNote="Proxploy could not reach the backend to list guests on this node.">
          {(rows) => <GuestList guests={toGuests(rows, vms ?? [])} />}
        </QueryState>
      </div>
```

The VM query stays — it still feeds the count and the list — but it no longer
owns a `QueryState` of its own, because two empty states under one heading was
half of what "two visual languages" meant.

- [ ] **Step 6: Verify**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: green, 44 lint warnings. If a `hosts.test.tsx` case asserted on
"No VMs on this node" or the VM table's markup, it is now asserting on
something deliberately removed — update it to the unified list rather than
restoring the table.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/GuestList.tsx frontend/src/tests/guest-list.test.tsx \
        frontend/src/routes/hosts.tsx frontend/src/tests/hosts.test.tsx
git commit -m "feat(hosts): one guest list, with the VMs brought up to the apps' level"
```

---

### Task 3: The non-entry node says why it is emptier

**Files:**
- Modify: `frontend/src/routes/hosts.tsx` (`useNodeContext`, `NodeOverview`)
- Modify: `frontend/src/tests/hosts.test.tsx`

**Interfaces:**
- Consumes: `NodeRow` from `../api/hooks`, `Link` from `@tanstack/react-router`
  (already imported in this file).
- Produces: `useNodeContext()` now returns
  `{ id: number; node?: NodeRow; host?: HostDetail; entry?: NodeRow }`.
  Task 4 does not depend on `entry`.

- [ ] **Step 1: Write the failing test**

Add to the `describe('NodeOverview', ...)` block in
`frontend/src/tests/hosts.test.tsx`. The file already mocks `/cluster/nodes`
with `pve1` (non-entry), `pve2` (entry) and `pve3` — see its fixture around
line 43 — and `NodeDetailPage` reads its own params, so a non-entry node is
reachable by pointing the params mock at `pve1`.

```tsx
  it('says where the metrics live instead of silently dropping the charts', async () => {
    // pve1 is not the entry node; pve2 is. The host:<id> series is recorded
    // from the node Proxploy connects through, so charting it here would be
    // charting a different machine — but saying nothing reads as a bug.
    params = { hostId: '1', node: 'pve1' }
    withQuery(<NodeOverview />)
    expect(await screen.findByText(/recorded on/i)).toBeInTheDocument()
    expect(screen.getByText(/pve2/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open pve2/i })).toBeInTheDocument()
  })

  it('draws the charts, and no note, on the entry node', async () => {
    params = { hostId: '1', node: 'pve2' }
    withQuery(<NodeOverview />)
    expect(await screen.findByText('Identity')).toBeInTheDocument()
    expect(screen.queryByText(/recorded on/i)).not.toBeInTheDocument()
  })
```

If the file's params mock is not already a reassignable `let params`, make it
one — the existing comment at line 96 ("NodeDetailPage reads its own params")
marks where it is defined.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/tests/hosts.test.tsx -t "recorded on"
```

Expected: FAIL — no element matching `/recorded on/i`.

- [ ] **Step 3: Return the entry node from `useNodeContext`**

In `frontend/src/routes/hosts.tsx`, in `useNodeContext`, add one line before the
return and widen the return:

```tsx
  // The page needs to NAME the entry node, not just know it is not this one.
  const entry = forHost?.find((n) => n.is_entry)
  const { data: host } = useHostDetail(id)
  return { id, node, host, entry }
```

- [ ] **Step 4: Write the note and mount it**

Add this component to `frontend/src/routes/hosts.tsx`, above `NodeOverview`:

```tsx
/** Charts and the node shell belong to the entry node — the `host:<id>` metric
 *  series is recorded there and the shell ticket is minted for it. Both were
 *  simply absent on every other node of a cluster, which reads as a missing
 *  feature rather than a deliberate one. */
function EntryNodeNote({ hostId, entry }: { hostId: number; entry?: NodeRow }) {
  return (
    <div className="mt-5 rounded-card border border-line border-l-2 border-l-amber
                    bg-panel p-4 text-[13px] text-text-2">
      Metrics and the node shell are recorded on{' '}
      {entry?.node
        ? <span className="font-mono text-text">{entry.node}</span>
        : <span>this host&rsquo;s entry node</span>}
      , the node Proxploy connects through.{' '}
      {entry?.node && (
        <Link to={'/hosts/$hostId/$node' as never}
          params={{ hostId: String(hostId), node: entry.node } as never}
          className="text-amber hover:underline">
          Open {entry.node} →
        </Link>
      )}
    </div>
  )
}
```

Then in `NodeOverview`, take `entry` from the context and give the
`node.is_entry` conditional an else branch:

```tsx
  const { id, node, host, entry } = useNodeContext()
```

```tsx
          {node.is_entry ? (
            /* Each chart owns its range: "is the CPU spiking now" and "did
               storage creep all week" are different questions. */
            <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className={card}>
                <MetricChart target={`host:${id}`} metric="cpu_pct"
                  unit="percent" label="CPU" accent="amber" />
              </div>
              <div className={card}>
                <MetricChart target={`host:${id}`} metric="mem_pct"
                  unit="percent" label="Memory" accent="cyan" />
              </div>
              {/* Already recorded every cycle by the poller (`disk_pct`), and
                  correctly shared-vs-local deduped there, so this series is
                  the host's real fill, not the sum of the node rows. */}
              <div className={card}>
                <MetricChart target={`host:${id}`} metric="disk_pct"
                  unit="percent" label="Storage" accent="violet" />
              </div>
            </div>
          ) : (
            <EntryNodeNote hostId={id} entry={entry} />
          )}
```

- [ ] **Step 5: Run the tests**

```bash
cd frontend && npx vitest run src/tests/hosts.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Verify and commit**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

```bash
git add frontend/src/routes/hosts.tsx frontend/src/tests/hosts.test.tsx
git commit -m "fix(hosts): a node without charts now says which node has them"
```

---

### Task 4: The two-column layout, and the spec

**Files:**
- Modify: `frontend/src/routes/hosts.tsx` (`NodeOverview`'s wrapper only)
- Modify: `docs/06-frontend-spec.md`

**Interfaces:**
- Consumes: `NodeIdentityRail` (Task 1), `GuestList` (Task 2), `EntryNodeNote`
  (Task 3).
- Produces: nothing new. This task is layout and documentation.

- [ ] **Step 1: Wrap the body in the grid**

In `frontend/src/routes/hosts.tsx`, `NodeOverview`'s returned tree becomes:

```tsx
  return (
    <div className="lg:grid lg:grid-cols-[290px_minmax(0,1fr)] lg:items-start lg:gap-5">
      {/* minmax(0,1fr), not 1fr: the charts' SVG content would otherwise set
          the column's min-content width and the grid would refuse to shrink
          below 1440px — the exact bug this stage exists to fix. */}
      <div className="mb-5 lg:sticky lg:top-16 lg:mb-0">
        {node?.node && (
          <NodeIdentityRail hostId={id} node={node.node} snapshot={node} />
        )}
      </div>
      <div>
        {node && (node.is_entry
          ? (
            /* Each chart owns its range: "is the CPU spiking now" and "did
               storage creep all week" are different questions. */
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className={card}>
                <MetricChart target={`host:${id}`} metric="cpu_pct"
                  unit="percent" label="CPU" accent="amber" />
              </div>
              <div className={card}>
                <MetricChart target={`host:${id}`} metric="mem_pct"
                  unit="percent" label="Memory" accent="cyan" />
              </div>
              {/* Already recorded every cycle by the poller (`disk_pct`), and
                  correctly shared-vs-local deduped there, so this series is
                  the host's real fill, not the sum of the node rows. */}
              <div className={card}>
                <MetricChart target={`host:${id}`} metric="disk_pct"
                  unit="percent" label="Storage" accent="violet" />
              </div>
            </div>
          )
          : <EntryNodeNote hostId={id} entry={entry} />)}
        <div className="mt-5">
          {/* "on this host", not "on this node": neither apps nor vms records
              which node of the cluster a guest sits on, so this list is
              host-wide and says so. */}
          <h2 className="mb-3 font-display text-[16px] font-semibold">
            Guests on this host ({(apps?.length ?? 0) + (vms?.length ?? 0)})
          </h2>
          <QueryState query={nodeAppsQuery}
                      emptyTitle="No guests on this node"
                      emptyNote="Installed or adopted apps and QEMU guests on this node appear here."
                      errorTitle="Guests not readable"
                      errorNote="Proxploy could not reach the backend to list guests on this node.">
            {(rows) => <GuestList guests={toGuests(rows, vms ?? [])} />}
          </QueryState>
        </div>
      </div>
    </div>
  )
```

Three details that are not cosmetic:

- `lg:items-start` — a grid item stretches to the row height by default, and a
  stretched item cannot stick. Without this, `lg:sticky` silently does nothing.
- `lg:top-16` — the topbar is `sticky top-0` with `py-2.5` (about 52px tall).
  4rem clears it with a little air.
- The charts' own `mt-5` moves to the right column's wrapper, because the row
  above them is now the rail, not the strip.

- [ ] **Step 2: Check the whole suite still passes**

```bash
cd frontend && npm test && npx tsc -b && npx oxlint
```

Expected: green, 44 warnings. Layout classes are invisible to jsdom, so a
failure here is a real structural change, not a styling one.

- [ ] **Step 3: Confirm nothing else claimed a fixed width on this page**

```bash
cd frontend && grep -nE 'w-\[[0-9]+px\]' src/routes/hosts.tsx src/components/NodeIdentityRail.tsx src/components/GuestList.tsx
```

Expected: no output. A hit is a fixed width that will overflow the new
290px column or the narrow layout; convert it to a `max-w-` or a fraction.

- [ ] **Step 4: Update the frontend spec**

In `docs/06-frontend-spec.md`, rewrite the host page entry to describe what
shipped: a two-column Overview (290px sticky identity rail at `lg`, single
column below), `NodeIdentityRail` with its four groups and the empty-group
rule, the unified `GuestList` with the memory asymmetry stated, and the
non-entry note. Delete any surviving description of `HostFacts` — the component
no longer exists.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/hosts.tsx docs/06-frontend-spec.md
git commit -m "feat(hosts): identity on the left, activity on the right, at every width"
```

---

## Done when

- `npm test`, `npx tsc -b` and `npx oxlint` are green, with lint warnings still
  at 44.
- `HostFacts.tsx` and `host-facts.test.tsx` are gone; nothing imports them.
- A node that refuses `/status` renders the Identity and Memory & storage
  groups and **no** Processor or Boot heading.
- A non-entry node renders the note, named and linked, in place of the charts.
- Apps and VMs appear in one list, both with lifecycle controls and a console.
- **The user has looked at a host page in their own browser**, at full width
  and narrowed to roughly 900px and 600px. The driver has no login step, so no
  agent-run screenshot can stand in for this. If teaching the driver to log in
  is wanted, that is separate work, not part of this stage.

## Explicitly not in this stage

- The header and tab strip of `NodeDetailPage`.
- The Hardware tab, including its own "Node facts" card.
- `AppCard`, `KVGrid`, `UsageBar`, `StatusPill`, `MetricChart`.
- Any shadcn dependency, `cva`, `cn`, or the token alias layer.
- Any other surface — stage 3 rolls out by surface, and this is the pilot that
  agrees the direction first.
- MagicUI and motion.
