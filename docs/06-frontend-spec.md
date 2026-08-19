# 06: Frontend Spec

> **Amendment, 2026-08-11 (supersedes the 2026-08-08 amendment, PXP-19): the
> overlay primitives are now Radix, and this doc no longer contradicts the
> code on that point.**
>
> The 2026-08-08 amendment recorded that shadcn/Radix had not shipped and that
> every component was hand-built against the tokens instead. It named the cost
> plainly: "keyboard traps and ARIA wiring are this codebase's own
> responsibility and are not covered by any test today." A later audit measured
> what that cost had become. Across 18 hand-rolled dialog surfaces there were
> zero focus traps, zero Escape handlers, and one `aria-modal` in the entire
> app. The same four defects, eighteen times.
>
> That is why the overlay decision is reversed and the rest of the amendment is
> not. Focus management is subtly hard, easy to get wrong in ways no test
> catches, and not where this project's value is. The parts of the original
> substitution that were about *appearance* stand: cards, inputs, tables,
> badges and the button stay hand-built against the tokens, because there the
> hand-written version is already correct and a library buys nothing.
>
> **Adopted, pinned, all MIT (verified from the installed packages, not from
> memory):** `@radix-ui/react-dialog` 1.1.23, `@radix-ui/react-alert-dialog`
> 1.1.23, `@radix-ui/react-dropdown-menu` 2.1.24, `@radix-ui/react-tabs`
> 1.1.21, `cmdk` 1.1.1. Measured cost is +41.9 KB gzipped against a 326 KB
> bundle. See doc 03 for the dependency-map rows.
>
> **Two primitives, and everything converges on them:**
> `src/components/ui/dialog.tsx` for routine modals and
> `src/components/ui/alert-dialog.tsx` for destructive ones, with the shared
> behaviour in `src/components/ui/overlay.ts`. Escape, focus trap, focus
> restore, `aria-modal` and scroll lock come from Radix. The look is the
> existing tokens, unchanged. Two things the primitives add that Radix does not
> give for free, both because these dialogs are rendered conditionally rather
> than opened by a `<Dialog.Trigger>`: the primitive owns its own close so
> Radix can finish its close sequence before the parent unmounts it, and it
> remembers the element that was focused when it mounted so focus actually
> returns there. Both are covered by tests in `src/tests/ui-dialog.test.tsx`.
>
> **Still not shipped, and still not planned:** CodeMirror 6 for the script
> editor and TanStack Table for data tables. The command palette is being
> rebuilt on `cmdk`; until that lands, `ui.global_search` remains a registered
> entitlement flag with no implementation behind it (PXP-17).
>
> Read every mention of CodeMirror or TanStack Table below as "a component with
> this behaviour and these tokens", never as a dependency to install. Mentions
> of shadcn and Radix for overlays are now literal.
> dependency to install.

Derived from `proxploy-prototype.html`, which is the source of truth for
pages, routes, interactions, and design tokens (brief §1). The job of the
production frontend (React 19 + TypeScript + Vite, Tailwind v4 + shadcn/ui,
TanStack Query + Router, brief §4) is to **reproduce the prototype**, wired
to the real API (doc 05), not to invent a new look.

Prototype notes that shape this spec:

- The prototype routes by hash (`#/cluster`, `#/apps`, `#/store`, `#/vms`,
  `#/storage`, `#/network`, `#/backups`, `#/settings`,
  `#/detail/{apps|vms}/{id}`). We map these 1:1 onto TanStack Router paths.
- The prototype contains a `vContainers()` raw-CT view that is **unreachable**
  (not in `NAV`, not in the `VIEWS` router map). Per brief §2 rule 1
  (apps-only, never a raw CT list) we treat it as dead prototype code and do
  not build it.
- Detail tabs: apps = Overview / Logs / Console / Config; VMs = Overview /
  Console / Snapshots, exactly the prototype's `tabs` arrays.
- The prototype's Settings "Free/Pro" toggle is a demo device for the
  lock-veil; production replaces it with real license state from
  `GET /api/v1/entitlements` (plus a dev-only preview toggle behind a build
  flag).
- Destructive actions (stop, uninstall, migrate) against the CT or host
  Proxploy is itself running on route through a stronger typed-confirmation
  dialog (type the host/CT name to confirm) instead of the normal one-click
  action, with an explicit warning that stopping it can strand its own
  recovery path (doc 02 §9, doc 08 §1/§9); applies uniformly to the Apps
  detail action row, Apps-grid quick actions, and the migrate flow.

---

## (a) Page map & routes

### Routes present in the prototype

| Prototype hash | TanStack route | View | Contents (from the prototype) |
|---|---|---|---|
| `#/cluster` | `/cluster` (index `/` redirects here) | Cluster overview | Page header with live pulse ("Live · updated 4s ago"); resource-rings card (CPU/Memory/Storage with `x / y` subtotals); 3-across node cards (status dot, mono hostname, role tag, VMs/Apps/Uptime meta, CPU+RAM bars); Apps section (first 8 app cards, "View all", "Update all"); two-column footer: VM table (first 4, "Manage") + card with network throughput sparkline, recent-activity feed |
| `#/apps` | `/apps` | Apps grid | Header ("N installed across M hosts", App Store button); when discovered-but-unadopted CTs exist, a dismissible panel above the grid lists them with per-item catalog-match suggestions and a bulk "Adopt N containers" action, so existing infra never renders an empty grid; toolbar: segmented host filter (`All hosts` + per host), filter input ("Filter apps…") with live re-render that preserves input focus, "N shown" badge; 4-across app-card grid; empty state "No apps match your filter." |
| `#/store` | `/store` | App Store | Header ("Sourced from community-scripts/ProxmoxVE · showing N of \<true installable count\> installable scripts (M unsupported)", "Catalog synced 6m ago" pulse, Refresh); category chips (All, Media, Home & Auto, Files, Network, Monitoring, Databases, Security, Dev, Docker, Productivity); 3-across store cards (icon, name, category, 2-line description, popularity + `LXC` tags, Install / disabled "Installed" / unsupported entries show an honest note + upstream-link button instead of Install) |
| `#/vms` | `/vms` | Virtual machines | Header (count + running, "New VM"); full-width VM table: Name (OS icon + mono name), Node, vCPU/RAM, Status pill, hover row-actions (Console/Restart or Start, Logs) |
| `#/storage` | `/storage` | Storage | Header ("N datastores across the cluster", "Add storage"); grouped into one 3-across card grid per host, with any SHARED datastore lifted into a single "Shared across `<cluster>`" group above them (a shared row's `node` is whichever the poller saw first, so it cannot decide the grouping: `routes/storage-groups.ts`). A host with nothing attached keeps its heading and says so. Cards: icon, name, `node · type` (`type` alone in the shared group), % badge, used/total TB bar (bar turns red past 80%) |
| `#/network` | `/network` | Network | Two-column: Bridges table (Bridge/Node/Subnet/Zone badge/Ports) + Throughput card with ↓/↑ Mbps figures and two sparklines |
| `#/backups` | `/backups` | Backups | Header ("Proxmox Backup Server · pbs-datastore", "Run now", "New job"); 3 stat cards (Next scheduled, Datastore used + bar, Success rate 30d); Recent-backups table (Guest/Node/When/Size/Status, Restore + Delete row actions) |
| `#/settings` | `/settings` | Settings | Plan card (tier + description, Free/Pro state); Hosts card (table of Host/Address/Resources/Role/Status + "Add host", **lock-veiled when `hosts.multi` unentitled**); General card with toggle rows (Scheduled auto-updates, Notify on high load, Community Scripts source + "Sync now") |
| `#/detail/apps/{id}` | `/apps/$appId` with tab child routes: `/apps/$appId` (overview), `/logs`, `/console`, `/config` | App detail | Back link; large gradient icon; name + mono subline `CTID · host · ip:port` (+ "update available" badge); action buttons (Open web UI / Restart / Stop, or Start when stopped); amber-underline tabs. Overview: CPU sparkline card, Memory bar card, Status/uptime card, Details KV grid (CTID, Node, IP, Category, Web port, Update), "Update to vX" button. Logs: terminal panel of colored log lines. Console: terminal panel (root shell). Config: "Saved Community Script" editor panel with Save button |
| `#/detail/vms/{id}` | `/vms/$vmId` with tab children: index (overview), `/console`, `/snapshots` | VM detail | Same head pattern with VMID subline `VMID · host · vCPU/RAM`. Overview: same three cards + KV grid (VMID, Node, Disk, OS type). Console: terminal panel (noVNC canvas in production). Snapshots: table (Name/Created/Size) with Rollback + Delete row actions and "Take snapshot" |

Tabs are child routes (not search params) so logs/console links from app
cards (`data-tab="logs"` in the prototype) are directly linkable, matching
prototype behavior where card buttons deep-link into a specific tab.

### Flows implied but not shown: designed in the same language

| Route | Flow | Design (reusing prototype vocabulary) |
|---|---|---|
| `/login` | Login | Centered `.card` on the `--ink` radial-gradient body background; brand mark + wordmark (Prox**ploy**, amber `b`); email/password inputs styled like `.finput`; primary amber gradient button; TOTP step swaps in a 6-digit input in the same card; "Sign in with SSO" ghost button appears only when `auth.oidc` is configured. Errors as red toasts. |
| `/onboarding` | First-run wizard | Same centered-card stage, stepper of small `.badge` pills across the top. Steps: 1) Create admin account, 2) Add first Proxmox host (address + API token, "Test connection" ghost button showing scope check results in a mini `.term` panel), 3) Authorize install key (shows the generated ed25519 **public** key with copy button + the one command to authorize it on the node, honest copy about what SSH root means; brief §8), 4) Sync; live progress reusing the job-log terminal panel. Routing guard: `GET /api/v1/meta/onboarding` redirects here until complete. |
| `/settings/hosts/new` (modal route over Settings) | Add host | Radix Dialog styled as `.card` (`--panel`, `--r` radius): name, address, API token, TLS verify toggle row, optional SSH-key step identical to onboarding step 3. Gated: attempting a 2nd host without `hosts.multi` shows the lock-veil inside the dialog body (exactly the Settings hosts-card treatment). |
| `/hosts/$hostId/$node` (Overview / Hardware tabs; `/hosts/$hostId` redirects here, to the host's entry node) | Host / node detail | Head pattern shared with the app/VM details: mono node name, `cluster · PVE version` subline (or "standalone"); entry-node-only "Node shell ↗" button that always opens rather than greying out, a toast naming the unmet gate (entitlement or the per-host shell opt-in) when one is shut; "Open Proxmox web UI ↗" link; status pill; amber-underline tabs. **Overview** is two columns from `lg` up and one column below it — the exact breakpoint the rest of this page already had, now applied to its own frame: a 290px `lg:sticky` identity rail (`NodeIdentityRail`, internally scrollable past viewport height) beside a fluid right column, `minmax(0,1fr)` so the track can shrink below its content's intrinsic width instead of refusing to. The rail merges two sources — the poller's snapshot, always present, and the node's own `/status`, on demand and refusable by a narrow token — into usage bars (Load/RAM/Storage/Root, the first and last status-only) above four fact groups (Identity, Processor, Memory & storage, Boot); a group built only from `/status` (Processor, Boot, half of Identity and Memory & storage) renders no heading at all when the node refuses that call, rather than a label over nothing. The right column: the entry node draws three range-scoped `MetricChart` cards (CPU/Memory/Storage, the `host:<id>` series recorded only there); any other node of the cluster gets a note naming and linking to the entry node instead of charts it cannot have. Below either: "Guests on this host (N)" as one `GuestList` merging apps and VMs into a single row shape (kind badge, id, status pill, CPU bar, lifecycle controls, Console button on every row) — VMs show a raw `mem_bytes` figure since `VmRow` carries no total to divide by, while apps show `used / total`. **Hardware** tab: unrelated "Node facts" card, out of this stage's scope. |
| (global) notification surface | In-app notifications | Toasts (sonner) are the only in-app notification surface — there is no overlay drawer. Every `job`/`alert` SSE event becomes a toast with its own close button, plus a `ClearAllToasts` "Clear all (N)" control that appears once two or more toasts are showing and dismisses them all. `notify.inapp` gates this surface, not the underlying data (§(d)). Activity history persists in `ActivityFeed`, rendered on `/hosts`, not in a modal. |
| (global) ⌘K | Command palette | cmdk dialog styled like `.search` grown into a panel: fuzzy across apps, VMs, hosts, store entries, and nav actions; rows reuse icon + mono-subtext layout of `.vn`. |
| `/store/$slug/install` (modal route) | Install flow | Dialog: target-host select (segmented control), resource overrides (cores/RAM/disk, prefilled from catalog defaults), script preview in a `.code` panel with upstream-diff notice, explicit "runs as root on <node>" confirmation line (brief §8 honesty), then Install → toast, with the new job's live log streaming inline in the same dialog (`JobLog`) in place of the form. The prototype's instant install-toast pair ("Deploying X to host-01…" → "X installed and running") becomes the real job lifecycle. |
| `/apps` (bulk adopt dialog) | Discover & adopt | Radix Dialog reusing the install-flow's card language: one row per discovered CT (CT name/id, host, suggested catalog match or "No match; adopt as generic"), checkbox select-all/individual, confirm → `POST /api/v1/apps/adopt` (bulk) → toast + Apps grid refresh, discovered panel shrinks by the adopted count |

Auth guard: all routes except `/login` and `/onboarding` require a session
(`GET /api/v1/auth/me` in the root route loader; 401 redirects to `/login`).

---

## (b) Component inventory

Extracted from the prototype's CSS/JS; mapped to shadcn/Radix where a
primitive genuinely fits, custom where the prototype's look *is* the
component. shadcn components are copied in and restyled with our tokens
(brief §4), no default shadcn theme survives.

| Component | Prototype source | Implementation | Notes |
|---|---|---|---|
| `AppShell` | `.app` grid (236px sidebar + main), `.side`, `.main` | custom | Full-width `header` row (`h-14`, `z-10`) spans the whole window; a flex row beneath it holds the sidebar and `main`. The sidebar sticks at `top-14` with `height: calc(100vh - 3.5rem)` — the window height minus that 56px header — rather than a bare `100vh`; width transitions between 236px and a 64px icon rail (`motion-reduce`-safe). Responsive: sidebar hidden ≤720px (mobile nav = Sheet) |
| `SidebarNav` | `.nav`, `.lbl` group labels, `.on` active state with 3px amber left rail (`::before`), `.cnt` mono count | custom | Every item pairs a Heroicon (24/outline, 18px, `aria-hidden`) with its label. A header-row toggle collapses the rail to icons only: group labels give way to a plain rule (no room for the word, and truncating it would read worse than a line), each link gains an `aria-label` since its text is gone, and a Radix `Tooltip` shows the label on hover/focus. The choice persists to `localStorage` (`pp_sidebar`), defaulting to expanded so a first-time user meets the labels before being asked to recognise ten icons cold. Groups: Overview (Hosts, Apps, App Store, Virtual Machines) / Infrastructure (Storage, Network, Backups, Alerts, Audit, Settings); counts fed by query cache |
| `BrandMark` | `.brand`, amber-gradient `.mark` tile + Prox**ploy** wordmark | custom | Lives in the `Topbar`, not the sidebar — the sidebar's `max-[720px]:hidden` meant no logo showed on a phone before this move. Wrapped in a `Link` to `/hosts` — the top-left mark's expected destination now that `/cluster` is not a route (`/` already redirects to `/hosts`). Below `sm`, swaps to the ghost-only mark (ghost + wordmark is 134px wide at the fixed `h-6`, too wide for a phone header alongside search/bell/tier/theme/avatar) |
| `HealthFooter` | `.side-foot` ("All systems healthy", green dot, "3 nodes · 0 alerts") | custom | Bound to `/alerts?state=firing` + host status; dot turns `--red` with firing alerts |
| `Topbar` | `.top` sticky, `rgba(11,15,22,.82)` + `backdrop-filter: blur(10px)` | custom | Hosts the `BrandMark` (see above); search trigger and activity bell render as Heroicons, not emoji |
| `ClusterSwitcher` | `.cluster` (blue icon tile, display-font name, chevron) | Radix DropdownMenu trigger styled as prototype | Lists hosts/teams scopes; single-host installs render it inert |
| `TierPill` | `.pro` / `.pro.free` (`PRO · MULTI-HOST` / `FREE · 1 HOST`, mono 9.5px) | custom Badge | Bound to entitlements tier; click → `/settings` plan card |
| `GlobalSearch` | `.search` with `⌘K` kbd chip | cmdk (Command) in Radix Dialog | Trigger styled exactly as the prototype input |
| `Button` | `.btn` variants: `primary` (amber gradient, dark text `#20160a`), `ghost`, `danger`, `go` (amber-dim), `green`, `sm` | shadcn Button, variants rewritten | Prototype's exact gradient `linear-gradient(150deg,#F5B544,#E79126)` + shadow |
| `IconButton` | `.iconbtn` (+ `wide`, `go`, `green`) | custom | App-card action row |
| `Avatar` | `.avatar` (initials, gradient tile) | custom | Menu: profile, sessions, sign out |
| `StatRings` | `.rings`/`.ring`, 96px SVG rings, `r=52`, stroke 10, gradient stroke, mono % center, label + mono subtotal | custom SVG | Keep the prototype's dasharray math (`circ=326.7`, offset `circ*(1-pct/100)`), animate offset on data change |
| `NodeCard` | `.node`, status dot, mono name, node name + `entry` marker + cluster, VMs/Apps/Uptime meta, CPU (amber gradient) + RAM (cyan→blue gradient) bars | custom | One card per NODE (a Host is one API endpoint; its cluster has many nodes). Card click → node detail `/hosts/$hostId/$node`, keyboard-reachable (`role="link"`, Enter/Space); the `N Apps` meta is its own link → `/apps?host=…`, stopPropagation. **Supersedes this row's original "Click → `/apps?host=…`"**: it made `NodeCard` the only card in the product that opened something other than the thing it depicts, which is not what the `AppCard` row two lines down specifies for every other card |
| `UsageBar` | `.bar` / `.brow` (6px rounded track `#1d2733`) | custom | Shared by nodes, app cards, storage, backups |
| `AppCard` | `.app-c`, gradient `.ico` initials tile, name, mono host, status pill, `UPDATE` corner tag, CPU/RAM usage bars, action row (Open/Start wide + Restart + Logs), hover `translateY(-3px)`, stopped = `opacity:.72` | custom | The signature component; card click → detail, actions stopPropagation |
| `StatusPill` | `.st` run/stop/warn (dot + label, glow via box-shadow dim ring) | custom | |
| `StoreCard` | `.store-c`, icon, name, category, description (min-height 34px), `★ pop` + `LXC` tags, Install / disabled Installed / (unsupported: honest "Not installable, \<reason\>" note + upstream-link button, no Install control) | custom | Ingest-classified `installable` flag (doc 01 §3, doc 04 `catalog_entries`) drives which action renders |
| `DiscoveredPanel` | (implied, no prototype source, new for the discovery-and-adopt flow) | custom | Dismissible panel above the Apps grid; lists CTs found by the poller not yet mapped to an app, catalog-match suggestion chips, checkbox multi-select, "Adopt N" bulk action opening the bulk-adopt dialog; hidden when nothing is discovered |
| `CategoryChips` | `.cats`/`.chip` with amber `.on` state | custom (Radix ToggleGroup semantics) | |
| `SegmentedControl` | `.seg` (host filter; `.on` = `--elev`) | Radix ToggleGroup styled | |
| `FilterInput` | `.finput` | custom | Debounced; updates URL search param |
| `DataTable` | `.tbl`, uppercase 11px headers, row hover `--panel-2`, `.vn` name cell (icon tile + mono), `.spec` mono cells, `.rowact` hover actions | shadcn Table + TanStack Table (sorting) | VMs, hosts, backups, bridges, snapshots |
| `Tabs` | `.tabs`, 2px amber underline on active | Radix Tabs, styled; tab = route link | |
| `KVGrid` | `.kv` (auto-fit minmax(150px,1fr), uppercase keys, mono values) | custom | App/VM detail overview |
| `NodeIdentityRail` | (implied, no prototype source — host/node detail did not exist in the prototype) | custom | Host/node detail Overview, 290px sticky rail from `lg`; label-left/value-right fact groups rather than `KVGrid`'s label-above-value, which would waste most of a 290px column; see page-map row above for the two-source merge and empty-group rule |
| `GuestList` | (implied, no prototype source) | custom | Host/node detail Overview; one row shape for apps and VMs (supersedes a separate `AppCard` grid and a bare VM table), lifecycle controls + Console on every row |
| `TerminalPanel` | `.term`, `#0a0e14`, JetBrains Mono 12.5px, line-height 1.7, colored level spans | custom, two modes | *Static mode*: rendered log/SSE lines (Logs tab, job streams). *Live mode*: xterm.js mount themed with the same palette (Console tabs) |
| `CodePanel` / script editor | `.code`, `#0a0e14`, syntax colors: comments `--text-3`, keywords `--violet`, strings `--green`, vars `--blue` | CodeMirror 6 (MIT) with a token-matched bash highlight theme | Config tab; read-only mode for store script preview |
| `ToggleRow` | `.setrow` + `.toggle` (42×24, amber-dim on-state, amber knob) | Radix Switch restyled + custom row | Settings |
| `LockVeil` | `.locked`/`.lockveil`, blurred `pointer-events:none` content behind `rgba(11,15,22,.72)` + `blur(3px)` veil, amber lock icon, title, subtext, "Unlock Pro" `go` button | custom wrapper | See §(e) |
| `Toast` | `.toast`, `--panel-2` card, colored icon (ok=green check, warn=amber update, err=red alert, info=blue arrow), slide-up `tin` animation, 2.6s auto-dismiss | sonner, fully restyled with tokens | The in-app notification surface: every toast carries a close button (`closeButton` on `<Toaster>`); `ClearAllToasts` dismisses all of them once two or more are showing |
| `ActivityFeed` | `.feed`/`.fitem`, tinted icon tile (`color-mix` 13% of the accent), text with mono `<b>`, mono meta line | custom | Dashboard + Hosts page — the activity-history surface, now that there is no drawer |
| `Sparkline` | `.spark` SVG (300×52, gradient area fill fading to 0, 2px line) | uPlot (area+line preset) at prototype dimensions | Network, detail CPU, dashboard |
| `EmptyState` | `.empty` | custom | |
| `LivePulse` | `.live` + `.pulse` keyframe glow | custom | "Live · updated Ns ago" bound to last SSE message time |
| `Dialog` | (implied) | Radix Dialog styled as `.card` | Install flow, add host. The `sheet` variant (right-docked panel) existed solely for the activity drawer and was removed with it — `variant` is now `'center' \| 'palette'` |
| `PageHeader` | `.ph` (display-font h1 22px, `.sub`, right slot) | custom | Every page |
| `SectionHeader` | `.sec-h` (+ pill `.badge`) | custom | |

Motion: `fade`/`rise` entry animation (0.45s cubic-bezier(.2,.7,.3,1)) on
page content, toast `tin` slide, ring/bar transitions, all disabled under
`prefers-reduced-motion`, exactly as the prototype does.

Accessibility beyond the prototype: all interactive `div`s become real
buttons/links, focus-visible rings in `--amber`, status pills carry text (not
color alone, the prototype already does this), tables get proper `scope`,
dialogs/veils get correct ARIA from Radix.

---

## (c) Design tokens

The prototype's `:root` values verbatim, mapped into a Tailwind v4 `@theme`
block. Dark is canonical. These are the actual shipped values, not
approximations.

### Surfaces & lines

| Token (prototype) | Value | Tailwind v4 theme var | Use |
|---|---|---|---|
| `--ink` | `#0B0F16` | `--color-ink` | Page background (plus two fixed radial gradients: `radial-gradient(1100px 480px at 74% -8%, rgba(245,181,68,.06), transparent 60%)` and `radial-gradient(760px 420px at 8% 4%, rgba(91,157,249,.05), transparent 55%)`) |
| `--panel` | `#121924` | `--color-panel` | Cards, sidebar footer, inputs |
| `--panel-2` | `#161F2A` | `--color-panel-2` | Row hover, toasts, icon buttons |
| `--elev` | `#1B2531` | `--color-elev` | Active segment, hover elevation |
| `--line` | `#243040` | `--color-line` | Strong borders (inputs, toggles, toasts) |
| `--line-soft` | `#1A2330` | `--color-line-soft` | Default card/table/tab borders |

### Text

| Token | Value | Tailwind var | Use |
|---|---|---|---|
| `--text` | `#E8EDF4` | `--color-text` | Primary |
| `--text-2` | `#93A0B1` | `--color-text-2` | Secondary |
| `--text-3` | `#5C6979` | `--color-text-3` | Muted / labels / meta |

### Accents (each with a `-dim` translucent fill)

| Token | Value | Dim | Semantic |
|---|---|---|---|
| `--amber` | `#F5B544` | `rgba(245,181,68,.13)` | Brand, primary actions, active nav, warnings/updates, Pro |
| `--green` | `#3FCF8E` | `rgba(63,207,142,.13)` | Running, success, healthy |
| `--red` | `#F26D6D` | `rgba(242,109,109,.13)` | Errors, danger, >80% storage |
| `--blue` | `#5B9DF9` | `rgba(91,157,249,.12)` | Info, network-in, links/debug |
| `--violet` | `#A78BFA` | n/a | Storage ring/bars, code keywords |
| `--cyan` | `#34D3C6` | n/a | Memory (gradient partner to blue) |

Recurring gradients (component-level constants, not free choices):
brand/primary `linear-gradient(150deg,#F5B544,#E0862B)` (buttons use
`#E79126` as the stop), memory/RAM `linear-gradient(90deg,#34D3C6,#5B9DF9)`,
storage `linear-gradient(90deg,#A78BFA,#6D5AE6)`, danger storage
`#F26D6D→#c93b3b`. Terminal/code background is `#0a0e14` (darker than
`--ink`); bar track `#1d2733`; primary-button text `#20160a`.

### Typography & radii

| Token | Value | Use |
|---|---|---|
| `--font-display` | `'Space Grotesk', system-ui, sans-serif` | h1/h2, brand, avatar/icon initials, cluster name |
| `--font-ui` | `'Inter', system-ui, sans-serif` | Body (base 14px / 1.45) |
| `--font-mono` | `'JetBrains Mono', ui-monospace, monospace` | Metrics, IDs, hostnames, IPs, terminals, badges, kbd |
| `--r` | `14px` | Cards, nodes, app/store cards |
| `--r-sm` | `9px` | Nav items, small tiles |
| (unnamed but consistent) | `10px` | Buttons, inputs, terminal panels |

Fonts are self-hosted via `@fontsource` (no Google Fonts request from a
self-hosted, possibly air-gapped app; judgment call; weights per the
prototype: Space Grotesk 400–700, Inter 400–600, JetBrains Mono 400–600).

### Tailwind v4 wiring

```css
@import "tailwindcss";

:root, [data-theme="dark"] {
  --ink:#0B0F16; --panel:#121924; --panel-2:#161F2A; --elev:#1B2531;
  --line:#243040; --line-soft:#1A2330;
  --text:#E8EDF4; --text-2:#93A0B1; --text-3:#5C6979;
  --amber:#F5B544; --amber-dim:rgba(245,181,68,.13);
  --green:#3FCF8E; --green-dim:rgba(63,207,142,.13);
  --red:#F26D6D;   --red-dim:rgba(242,109,109,.13);
  --blue:#5B9DF9;  --blue-dim:rgba(91,157,249,.12);
  --violet:#A78BFA; --cyan:#34D3C6;
}

@theme inline {
  --color-ink: var(--ink);
  --color-panel: var(--panel);
  --color-panel-2: var(--panel-2);
  --color-elev: var(--elev);
  --color-line: var(--line);
  --color-line-soft: var(--line-soft);
  --color-text: var(--text);
  --color-text-2: var(--text-2);
  --color-text-3: var(--text-3);
  --color-amber: var(--amber);   --color-amber-dim: var(--amber-dim);
  --color-green: var(--green);   --color-green-dim: var(--green-dim);
  --color-red: var(--red);       --color-red-dim: var(--red-dim);
  --color-blue: var(--blue);     --color-blue-dim: var(--blue-dim);
  --color-violet: var(--violet);
  --color-cyan: var(--cyan);
  --font-display: 'Space Grotesk', system-ui, sans-serif;
  --font-ui: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  --radius-card: 14px;   /* --r */
  --radius-tile: 9px;    /* --r-sm */
  --radius-ctl: 10px;
}
```

Components then use `bg-panel`, `border-line-soft`, `text-text-2`,
`rounded-card`, `font-mono`, etc. shadcn's own semantic variables
(`--background`, `--primary`, …) are aliased to these so copied-in components
inherit the look without per-component overrides.

### Light theme (derived, later)

**Dark is canonical.** Light is a variable swap on
`[data-theme="light"]` only, no component changes:

- Surface ramp inverts around neutral paper: `--ink → #F5F7FA`,
  `--panel → #FFFFFF`, `--panel-2 → #F0F3F7`, `--elev → #E7ECF2`,
  lines → `#D9E0E8` / `#E4E9EF`.
- Text ramp inverts: `--text → #16202C`, `--text-2 → #4E5D6E`,
  `--text-3 → #8896A6`.
- Accent hues keep identity, darkened for contrast on white
  (amber → `#C77E14`-range, green → `#1F9D63`, red → `#D9463F`,
  blue → `#2F6FE0`) with `-dim` fills re-derived at the same alphas; every
  pair re-checked against WCAG AA before shipping.
- Terminal/code panels stay dark (`#0a0e14`) in both themes, consoles are
  dark, full stop.

The prototype ships no light values, so exact light hexes are tuned at
implementation against contrast checks; the mechanism (one attribute, one
variable block) is fixed now.

---

## (d) State & streaming binding

Server state lives exclusively in TanStack Query; no client store duplicates
it (small UI state, active filters; lives in URL search params, matching
the prototype's re-render-from-state approach).

### Query resources & polling

Polling is the **fallback** liveness mechanism; the SSE event stream (doc 05
§Streaming 4) is the primary one. While the SSE connection is healthy,
background poll intervals relax to the values below ÷ nothing (they're
already conservative); if SSE drops, Query's `refetchInterval` keeps the UI
honest until reconnect.

| Query key | Endpoint | refetchInterval | Notes |
|---|---|---|---|
| `['cluster','summary']` | `/cluster/summary` | 30 s | Rings |
| `['cluster','nodes']` | `/cluster/nodes` | 30 s | Node cards |
| `['apps', filters]` | `/apps` | 30 s | Grid; filters from URL params |
| `['apps', id]` | `/apps/{id}` | 15 s while detail open | |
| `['vms', …]` | `/vms`, `/vms/{id}` | 30 s / 15 s | |
| `['catalog', cat, q]` | `/catalog` | none (staleTime 5 min) | Changes only on refresh job |
| `['storage']` / `['network']` | | 60 s | |
| `['backups']` | `/backups` | 60 s | |
| `['jobs', 'running-count']` | `/jobs?status=running` | 30 s | Topbar bell badge; unbounded count, independent of any list view |
| `['alerts','firing']` | `/alerts?state=firing` | 60 s | Health footer |
| `['metrics', target, metric, range]` | `/metrics/query` | none (SSE-patched) | uPlot series |
| `['entitlements']` | `/entitlements` | 5 min | See §(e) |
| `['me']` | `/auth/me` | none | Invalidated on auth events |

### SSE → cache binding

One `EventSource('/api/v1/events/stream')` per tab, wrapped in a
`LiveProvider`. Handlers translate events (doc 05 message shapes) into cache
operations, **patch when the delta is complete, invalidate when it isn't**:

- `metrics` → `queryClient.setQueryData` patches: node cards, app-card
  cpu/ram bars, rings, and appends points to active uPlot series (no
  refetch; this is the "Live · updated 4s ago" path, the pulse timestamp is
  the last event's arrival time).
- `resource` → patch `status` on the matching `['apps'|'vms', id]` and list
  caches; anything beyond status → `invalidateQueries` on that resource.
- `job` → patch `['jobs']`; terminal status additionally invalidates the
  affected resource (`app.install` succeeded → invalidate `['apps']`,
  `['catalog']`) and fires the toast (`"Immich installed and running"`, `ok`),
  reproducing the prototype's install toast pair with real lifecycle.
- `alert` → invalidate `['alerts','firing']`; toast for `firing` at
  warning+ severity.
- `entitlements` → invalidate `['entitlements']`.

### Job log streams

`JobLog` opens a **second, scoped** EventSource on `/jobs/{id}/events/stream`
(install/uninstall/clone/migrate/restore dialogs, the VM create wizard, and
the backups/network/VMs routes all mount it once they have a `jobId`),
rendering `line` and terminal `status` events into the static-mode
`TerminalPanel` (auto-scroll with stick-to-bottom detection); the stream's
`progress` event (doc 05 §Streaming 1) has no frontend consumer today. On
disconnect, EventSource resumes from `Last-Event-ID`; on terminal `status`
the stream closes and the transcript query (`/jobs/{id}/events`) becomes the
source for re-opens.

### Consoles (xterm.js / noVNC)

- CT console & node shell: mount xterm.js (fit + webgl addons) in the
  Console tab, themed with the token palette on `#0a0e14`; obtain ticket via
  `POST …/console/tickets`, open the WS, pipe bytes both ways
  (attach-style), send `{"type":"resize"}` on fit. Reconnect = new ticket.
- VM console: noVNC `RFB` instance pointed at `/vms/{id}/vnc/ws?ticket=…`
  inside the Console tab; toolbar (Ctrl-Alt-Del, fullscreen) styled as
  `.btn ghost sm`.
- Consoles connect on tab **activation**, disconnect on route leave; never
  in the background.

### Charts

uPlot everywhere a line is drawn: dashboard/network sparklines (prototype's
300×52 area+line style: 2px stroke, gradient fill from 35% alpha to 0),
detail CPU chart, metrics history. One shared `sparkOpts(color)` preset
encodes the prototype look; series data comes from `['metrics', …]` caches
patched live by SSE.

---

## (e) Entitlement UI behavior

Source of truth: `GET /api/v1/entitlements` → `{ tier, features: {key:
bool}, grace }` (brief §7). Fetched before first paint (root route loader),
cached in Query, invalidated by the SSE `entitlements` event.

```tsx
const { has, tier } = useEntitlements();       // reads ['entitlements'] cache
has("hosts.multi")  // boolean
```

Rules, everything **visible but unarmed** by default:

1. **Never hide gated features.** Unentitled features render fully (real
   layout, blurred real or representative content) behind the `LockVeil`; 
   the prototype's `.locked` pattern is normative: content wrapper gets
   `blur(1px)` + `pointer-events:none`, veil is `rgba(11,15,22,.72)` +
   `backdrop-filter: blur(3px)`, amber lock icon, bold title
   ("Multi-host is a Pro feature"), one-sentence explanation, and a
   `go`-variant CTA. CTA routes to `/settings` plan card (production: license
   entry / upgrade link, not the prototype's demo toggle).
2. **Granularities.** Card/section veil (Settings hosts table, the
   prototype's exact case); full-page veil for gated pages; **disabled
   control + tooltip** ("Pro, Node shells", lock glyph in the button) for
   small inline actions (console button on an app card) where a veil is
   physically too large. All three read from the same flag map.
3. **Server always re-enforces** (brief §7). The UI treats a `403
   entitlement_required` problem+json as a signal to invalidate
   `['entitlements']` and show the veil state, never as an error toast. UI
   gating is presentation, not security.
4. **TierPill** in the topbar reflects `tier` (`PRO · MULTI-HOST` amber /
   `FREE · 1 HOST` muted, prototype classes `.pro` / `.pro.free`), plus a
   grace-period variant (amber outline, "PRO · GRACE") when the token is
   past `exp` but before `grace_until`.
5. **Dormant phase**: the built-in default map is all-on, so no veil ever
   renders today, but every gated surface is wrapped from day 0, so arming
   tiers later changes proxploy-api config, not frontend code (brief §2
   rule 5).
6. Flag keys used by the frontend are exactly the API's keys (doc 05
   tables); no frontend-local flag names.
