# Apps view modes on the Hosts page

Requested 2026-08-18. The Apps section of `/hosts` offers one presentation
today: a grid of `AppCard`s. Operators need three, switchable in place, over
the same set of apps.

- **Detailed.** Today's card, widened to carry storage and network alongside
  CPU and RAM.
- **List.** A table with the same detail, for scanning many apps rather than
  reading one.
- **Icon.** Logos in a dense grid, each with its state beside the name, and a
  five-action menu on the logo.

The icon view's menu is deliberately narrower than the full app menu: Start,
Stop, Restart, Console, Open, and nothing else.

## What already exists

Two things found during design that change the shape of the work.

**Open works today.** Web UI discovery shipped 2026-08-20 in `de0ec8b`.
`routes/apps.tsx` resolves the live address off `/apps/{id}/network`, including
the DHCP case where the guest's config says the literal word `dhcp` and only
the runtime interface list holds the lease. The original request assumed Open
might have to ship hidden. It does not.

**Storage and network do not exist.** The card shows CPU and RAM only, and
`AppRow` has no disk or network fields. "The same detail as the detailed view"
therefore describes something not yet built, and the backend has to land first.

## Backend

### Where the network rate is computed

`/cluster/resources` reports `netin`/`netout` as cumulative counters, not
rates. Something has to diff two readings. The poller does it, because it is
the only place that naturally holds both, and because a value cached in a
column survives a restart where an in-process previous-value would not.

The alternatives were an API serializer that diffs the last two `MetricSample`
rows per app on every GET, which puts a windowed query on the hottest list
endpoint; and a frontend that fetches metric history per card, which puts a
second round trip behind every tile in a grid of up to eight.

### Poller

`pollers/__init__.py` builds a guest dict from each `/cluster/resources` row.
It gains four reads of data already in the response being parsed:

- `disk` (used) and `maxdisk` (total). `maxdisk` is already read on the VM
  side.
- `netin` and `netout`, the counters.

Per app, the rate is the counter delta over the elapsed time since the cached
reading, at the 30s `poll_interval_s`.

**Counter resets.** Restarting a container zeroes `netin`/`netout`. A naive
diff turns that into a large negative number, and taking its absolute value
would render a fabricated traffic spike at exactly the moment an operator is
most likely to be watching. A negative delta means reset: the rate is `null`
for that cycle and recovers on the next.

There is a standing `ponytail:` comment in the app branch of the poller
recording that guest disk was skipped because `/cluster/resources` reports
`disk` meaningfully for LXC but routinely 0 for QEMU. Apps are all LXC, so
that reason does not apply to them. The comment narrows to the VM case it
actually describes rather than being left to contradict the new code. VMs stay
excluded, for the reason it gives.

### Model and migration

Seven nullable columns on `App`, following the existing `_cached` convention:

| Column | Holds |
|---|---|
| `disk_bytes_cached` | Used bytes |
| `disk_total_bytes_cached` | Allocated bytes |
| `net_in_cached` | Raw inbound counter, for the next diff |
| `net_out_cached` | Raw outbound counter, for the next diff |
| `net_in_bps_cached` | Derived inbound rate, bytes/s |
| `net_out_bps_cached` | Derived outbound rate, bytes/s |
| `net_sampled_at` | When the counters above were read |

The raw counters are stored, not just the rates, because the next cycle's diff
needs them.

`net_sampled_at` exists rather than the rate being divided by
`poll_interval_s`, because the real gap between two cycles is not the configured
interval: the poll loop backs off exponentially on a failing host. It is also
not `TimestampMixin.updated_at`, which moves on any write to the row, so a
rename or a migration between two cycles would silently shorten the window and
inflate the rate.

### API

`api/apps.py`'s app serializer gains the six matching fields, and `AppRow` in
`api/hooks.ts` types them `number | null`.

Null is a real state throughout, not a stand-in for zero: an app that has never
been polled, a stopped container, and the single cycle after a counter reset
all produce it. Every view renders it as no reading.

## Frontend

### The switcher

Three icon buttons in the Apps section header, beside `Update all`, built on
the existing `ui/button-group.tsx`.

The choice persists in `localStorage` under `pp_apps_view`, following the
`pp_console_theme` and `pp_console_font_size` precedent in
`lib/console-prefs.ts`. A view mode is a per-operator habit rather than a
per-visit one.

An unrecognised stored value falls back to detailed rather than throwing,
the same defensive read `isStoreSort` performs in `lib/store-order.ts` and for
the same reason: a value that reaches the renderer unchecked can take the page
down.

### One source of truth for the action gates

Three separate gates decide whether an app action is offered:

- the `apps.lifecycle` and `apps.open_ui` entitlements, each with the
  wait-for-first-fetch guard documented in `LifecycleActions.tsx` (gating
  `disabled` on an unresolved entitlement greys out every action for the whole
  first fetch, not only for plans that lack the flag)
- the host's `lifecycle` capability, which explains rather than silently
  disabling when no token is configured
- the host's `console` capability

That logic lives inside `LifecycleActions` and `ConsoleButton` today, both of
which render `Button`s. Menu items are not buttons, so the icon view cannot
reuse the components, and re-deriving the gates inside the menu is precisely
how a menu ends up offering Start on a host that cannot perform it.

The gates move into `useAppActionGates(hostId)`. The buttons and the menu items
both read from it, so there is one place the rules can change.

### Open, extracted

The Open mutation is a local `useMutation` inside `routes/apps.tsx`, so nothing
else can call it. It moves to `api/open-web-ui.ts` as `useOpenWebUi()`,
unchanged, including the comment recording why `window.open` has to fire in the
click handler before the `await`: moving it after would put it outside the user
gesture and a popup blocker would drop the tab, which is the one thing the
action exists to produce.

The detail header and the icon menu then share it. Open hides when
`catalog_port` is null, which is what the detail header already does.

### Detailed view

`AppCard` gains two rows below RAM, in the existing meter rhythm:

```
DSK  ▓▓░░░░░░░░   4.1 GB / 32 GB
NET  ↓ 9.6 Mbps   ↑ 0.7 Mbps
```

Storage draws a `UsageBar`, like CPU and RAM.

Network does not. There is no denominator to divide by, and inventing a
link-speed ceiling to draw a bar against would be making up a number. This is
the same call `GuestList.tsx` already makes about VM memory, which has no total
either and is rendered as a bare figure.

Rates format through the existing `fmtBps` in `lib/format.ts`, which takes
bytes/s and renders bits/s. That is the vocabulary the node network charts
already use, so the card and the charts agree.

`AppCardSkeleton` gains the two matching rows. Its own comment records that
every measurement in it is copied from the card so the two stay the same
height; the skeleton is edited in the same pass or the grid shifts when apps
land.

### List view

A new `AppTable`, taking `AppRow` directly: name, host and CT, status, CPU,
RAM, storage, network, actions.

Not an extension of `GuestList`. That component exists to merge apps and VMs
into one row shape, and its `Guest` type is deliberately lossy (memory
pre-formatted to a string, no disk, no network) because VMs have no data for
those columns. Widening it would drag permanently empty columns onto every VM
row.

### Icon view

`AppIconGrid`, four columns:

```
┌────┐  Jellyfin          ┌────┐  Vaultwarden
│LOGO│  ▶ running         │LOGO│  ■ stopped
└────┘                    └────┘
  ↑ menu                    ↑ name → /apps/12
```

Nothing is drawn on the logo itself. State sits beside the name as a glyph and
the word, both derived from status, so `paused` and `unknown` stay
distinguishable instead of collapsing into "not running". Both come from
`StatusPill`'s colour map and `statusLabel`, so this view cannot drift from the
status vocabulary the rest of the app uses.

Clicking the logo opens the menu. Clicking the name goes to the app detail
page. The reference this view is modelled on has no detail page and so has only
one target; Proxploy has one, and it keeps a way in.

The menu is Radix `DropdownMenu` with the item classes `HostActionsMenu.tsx`
already defines. Five items: Start, Stop, Restart, Console, Open. Start and
Stop appear according to status, the way `LifecycleActions` already selects its
action set.

`IconTile` accepts `size: 40 | 56`, a closed pair so each size can carry its
own radius and glyph size rather than every caller restating them. The grid
wants a third, so the union gains `64` with its matching radius. That is the
extension the component's own comment invites.

## Testing

**Poller.** The counter diff produces the expected rate, and a counter reset
yields `null` rather than a spike. This is the only non-trivial logic in the
change.

**API.** The six fields serialize, and an unpolled app serializes them as null.

**Frontend.** Each view renders its metrics; the switcher persists across
mounts and falls back on a bad stored value; the menu offers exactly five items
and withholds Start on a host whose `lifecycle` capability is false.

Nothing here needs a live cluster. It all runs in the existing suites.

## Out of scope

- The `/apps` route keeps its current single presentation. The three views are
  components rather than route-local markup, so adding the switcher there later
  is wiring, not a rewrite.
- VM storage and network. The poller comment's reason still holds for QEMU.
- Metric history for storage and network. The card shows the current reading;
  no chart is added.
