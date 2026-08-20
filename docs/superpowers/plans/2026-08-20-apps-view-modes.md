# Apps View Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Apps section of `/hosts` three switchable presentations (detailed cards, a table, an icon grid with a five-action menu), and add the storage and network readings all three need.

**Architecture:** The poller already parses every `/cluster/resources` row; it starts keeping the `disk`, `maxdisk`, `netin` and `netout` fields it currently discards, diffing the network counters across cycles into a rate. Those land on `App` as cached columns, serialize through the existing app serializer, and reach the frontend on `AppRow`. The three views are components over that one row type, selected by a persisted view mode.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest (backend). React 19, TanStack Query, TanStack Router, Radix UI, Tailwind, vitest + Testing Library (frontend).

**Spec:** `docs/superpowers/specs/2026-08-20-apps-view-modes-design.md`

## Global Constraints

- **No em dashes anywhere.** Not in code, comments, copy, commit messages or test names. Use a comma, a colon, or parentheses.
- **No jargon in user-facing strings.** A message says what actually happened.
- **No hardcoded colours.** `src/tests/no-hardcoded-colors.test.ts` fails the build on a literal hex in a component. Use the theme tokens (`text-green`, `bg-amber-dim`, `text-text-3`).
- **Icon names must be static string literals.** `scripts/icon-names.mjs` statically scans `src/` to build the Google Fonts `icon_names` parameter. It resolves exactly three shapes: `<Icon name="literal" />`, `<Icon name={cond ? 'a' : 'b'} />`, and an `icon: 'literal'` field in a data table. A name that only exists at runtime (a variable, a computed lookup) ships a font subset missing that glyph, and the browser renders the literal word instead. Any status-to-icon map in this plan therefore uses the `icon: '...'` field shape.
- **Null is a real value, never zero.** An unpolled app, a stopped container and the cycle after a counter reset all produce null metrics. Every view renders that as no reading.
- **Backend commands run from `backend/`**, using `.venv/bin/python`. **Frontend commands run from `frontend/`**; vitest run from the repo root silently loads no jsdom config and every test fails with `ReferenceError: document is not defined`.
- **Frontend suites need `--no-file-parallelism`.** They flake without it.
- Backend tests exclude live-cluster marks: `-m "not pve_integration and not e2e"`.

---

### Task 1: Poller caches app storage and network

The poller reads `/cluster/resources` once per cycle and builds a dict per guest. `disk`, `maxdisk`, `netin` and `netout` are already in that response and currently dropped. This task keeps them, and turns the two counters into a rate.

**Files:**
- Modify: `backend/proxploy/models/__init__.py` (the `App` class, after `uptime_s_cached`)
- Create: `backend/proxploy/migrations/versions/d5b3f9c17e08_app_disk_net.py`
- Modify: `backend/proxploy/pollers/__init__.py` (the guest dict at ~line 378, the app branch at ~line 415)
- Modify: `backend/tests/fixtures/pve/cluster_resources_basic.json`
- Test: `backend/tests/test_poller_ingest.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `App.disk_bytes_cached`, `App.disk_total_bytes_cached`, `App.net_in_cached`, `App.net_out_cached`, `App.net_in_bps_cached`, `App.net_out_bps_cached`, `App.net_sampled_at`. The two `_bps_` columns are `float | None`, bytes per second. Task 2 serializes them.

- [ ] **Step 1: Add the counters to the test fixture**

Real PVE returns `netin`/`netout` on every guest row. The fixture omits them, so add them to both `lxc` rows in `backend/tests/fixtures/pve/cluster_resources_basic.json`. Find the row with `"vmid": 150` and add:

```json
 "netin": 1000000,
 "netout": 200000,
```

and to the row with `"vmid": 200`:

```json
 "netin": 500000,
 "netout": 100000,
```

Extra keys are ignored by every existing code path, so no current test changes behaviour.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_poller_ingest.py`. The first helper mutates the fixture's counters and controls `now`, because a rate needs two readings at a known distance apart.

```python
def _ingest_at(db, host, now, netin, netout):
    """One cycle with the CT-150 counters and the clock both pinned.

    A rate needs two readings and the gap between them, so neither the
    counters nor the timestamp can come from the shared fixture.
    """
    from proxploy.pollers import ingest_cycle

    resources, rrd = _fixtures()
    for r in resources:
        if r.get("type") == "lxc" and r["vmid"] == 150:
            r["netin"], r["netout"] = netin, netout
    return ingest_cycle(db, host, resources, rrd, now)


def _seed_app(db, host):
    from proxploy.models import App

    db.add(App(host_id=host.id, ctid=150, name="Immich", slug="immich"))
    db.commit()
    return db.query(App).filter_by(ctid=150).one()


def test_app_caches_storage_from_the_bulk_read(tmp_path):
    """`disk` and `maxdisk` are already in the row the poller parses. Storage
    for an app therefore costs no extra PVE call, which is the only reason it
    fits the poll budget at all."""
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    _ingest(db, host)

    assert app.disk_bytes_cached == 5368709120
    assert app.disk_total_bytes_cached == 17179869184


def test_first_poll_stores_the_counters_but_cannot_make_a_rate(tmp_path):
    """netin/netout are counters, not rates. One reading is one point, and a
    point has no slope, so the rate stays None until there are two."""
    from datetime import datetime
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    t0 = datetime(2026, 8, 20, 12, 0, 0)
    _ingest_at(db, host, t0, netin=1_000_000, netout=200_000)

    assert app.net_in_cached == 1_000_000
    assert app.net_out_cached == 200_000
    assert app.net_sampled_at == t0
    assert app.net_in_bps_cached is None
    assert app.net_out_bps_cached is None


def test_second_poll_derives_the_rate_from_the_counter_delta(tmp_path):
    """300000 bytes over 30 seconds is 10000 bytes/s. The elapsed time is
    measured, not assumed to be poll_interval_s, because the poll loop backs
    off exponentially on a failing host."""
    from datetime import datetime, timedelta
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    t0 = datetime(2026, 8, 20, 12, 0, 0)
    _ingest_at(db, host, t0, netin=1_000_000, netout=200_000)
    _ingest_at(db, host, t0 + timedelta(seconds=30),
               netin=1_300_000, netout=200_600)

    assert app.net_in_bps_cached == 10_000.0
    assert app.net_out_bps_cached == 20.0
    # The counters advance too, so the NEXT cycle diffs against these.
    assert app.net_in_cached == 1_300_000


def test_a_counter_reset_yields_no_rate_rather_than_a_spike(tmp_path):
    """Restarting a container zeroes netin/netout. Diffing across that
    boundary gives a large negative number, and abs() would draw a fabricated
    traffic spike at exactly the moment an operator is most likely to be
    watching. A negative delta is read as the reset it is."""
    from datetime import datetime, timedelta
    from tests.support import make_db, seed_host_row

    db = make_db(tmp_path)
    host = seed_host_row(db)
    app = _seed_app(db, host)

    t0 = datetime(2026, 8, 20, 12, 0, 0)
    _ingest_at(db, host, t0, netin=1_000_000, netout=200_000)
    _ingest_at(db, host, t0 + timedelta(seconds=30), netin=5_000, netout=900)

    assert app.net_in_bps_cached is None
    assert app.net_out_bps_cached is None
    # Recovery: the reset reading becomes the new baseline, so the cycle
    # after it produces a rate again.
    _ingest_at(db, host, t0 + timedelta(seconds=60), netin=305_000, netout=1_500)
    assert app.net_in_bps_cached == 10_000.0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_poller_ingest.py -q -k "storage or counter or rate or reset"`
Expected: FAIL with `AttributeError: 'App' object has no attribute 'disk_bytes_cached'`.

- [ ] **Step 4: Add the columns to the model**

In `backend/proxploy/models/__init__.py`, in the `App` class, immediately after the `uptime_s_cached` line:

```python
    # Storage and network for the card, the table and the icon grid. All from
    # the /cluster/resources row the poller already parses, so none of this
    # costs a PVE call.
    disk_bytes_cached: Mapped[int | None] = mapped_column(BigInteger)
    disk_total_bytes_cached: Mapped[int | None] = mapped_column(BigInteger)
    # netin/netout are counters since the container booted, not rates. The raw
    # readings are kept because the next cycle's diff needs them, and
    # net_sampled_at because the gap between two cycles is not
    # poll_interval_s: the poll loop backs off exponentially on a failing
    # host. TimestampMixin.updated_at cannot stand in for it either, since any
    # other write to this row (a rename, a migration) would move it and
    # silently shorten the window.
    net_in_cached: Mapped[int | None] = mapped_column(BigInteger)
    net_out_cached: Mapped[int | None] = mapped_column(BigInteger)
    net_in_bps_cached: Mapped[float | None] = mapped_column(Float)
    net_out_bps_cached: Mapped[float | None] = mapped_column(Float)
    net_sampled_at: Mapped[datetime | None] = mapped_column(DateTime)
```

`BigInteger`, `Float`, `DateTime` and `datetime` are already imported in this module (`missing_since` uses the last two).

- [ ] **Step 5: Write the migration**

Create `backend/proxploy/migrations/versions/d5b3f9c17e08_app_disk_net.py`. `c3f81a6d0e47` is the current head.

```python
"""apps storage and network

The Apps views show storage and network alongside CPU and RAM, and neither
existed on the app row. Both come out of the /cluster/resources read the
poller already makes, so this adds where to put them and costs no extra call
to PVE.

netin/netout are counters since the container booted rather than rates, so
the raw readings are stored next to the derived rates: the diff that makes a
rate needs the previous reading, and it needs to know how long ago that
reading was, which is what net_sampled_at records.

All nullable with no backfill. Null is the honest value for an app that has
not been polled since this landed, and it is the same value the rate takes on
the first cycle and after a counter reset, so every reader already has to
handle it.

Revision ID: d5b3f9c17e08
Revises: c3f81a6d0e47
Create Date: 2026-08-20

"""
import sqlalchemy as sa
from alembic import op

revision = "d5b3f9c17e08"
down_revision = "c3f81a6d0e47"
branch_labels = None
depends_on = None

COLUMNS = (
    ("disk_bytes_cached", sa.BigInteger()),
    ("disk_total_bytes_cached", sa.BigInteger()),
    ("net_in_cached", sa.BigInteger()),
    ("net_out_cached", sa.BigInteger()),
    ("net_in_bps_cached", sa.Float()),
    ("net_out_bps_cached", sa.Float()),
    ("net_sampled_at", sa.DateTime()),
)


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("apps", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("apps", name)
```

- [ ] **Step 6: Keep the new fields in the poller's guest dict**

In `backend/proxploy/pollers/__init__.py`, in the `guests[...] = {...}` literal, add one key. Do NOT rename `disk_bytes`: it already holds `maxdisk` and the VM branch depends on that meaning.

```python
            "mem_total_bytes": int(r.get("maxmem") or 0),
            "disk_bytes": int(r.get("maxdisk") or 0),
            # `disk` is USED, against `disk_bytes` above which is ALLOCATED.
            "disk_used_bytes": int(r.get("disk") or 0),
            "net_in": int(r.get("netin") or 0),
            "net_out": int(r.get("netout") or 0),
            "uptime_s": int(r.get("uptime") or 0),
```

- [ ] **Step 7: Add the rate helper**

At module level in `backend/proxploy/pollers/__init__.py`, next to `_mem_pct`:

```python
def _update_net_rates(a: App, g: dict, now: datetime) -> None:
    """Turn this cycle's netin/netout counters into a rate on the app row.

    PVE reports bytes since the container booted, so a rate is a diff against
    the previous reading over the time between the two. Both the reading and
    its timestamp are stored for the next cycle to diff against.

    Two cases produce no rate rather than a wrong one. The first reading has
    nothing to diff against: one point has no slope. And a container restart
    zeroes the counters, so the delta goes negative; taking its absolute value
    would draw a fabricated traffic spike at exactly the moment an operator is
    most likely to be watching. Either way the rate is None for one cycle and
    recovers on the next, once there are two readings from the same boot.
    """
    prev_in, prev_out, prev_at = a.net_in_cached, a.net_out_cached, a.net_sampled_at
    now_in, now_out = g["net_in"], g["net_out"]
    elapsed = (now - prev_at).total_seconds() if prev_at else 0.0
    if prev_in is None or prev_out is None or elapsed <= 0:
        a.net_in_bps_cached = a.net_out_bps_cached = None
    elif now_in < prev_in or now_out < prev_out:
        a.net_in_bps_cached = a.net_out_bps_cached = None
    else:
        a.net_in_bps_cached = (now_in - prev_in) / elapsed
        a.net_out_bps_cached = (now_out - prev_out) / elapsed
    a.net_in_cached, a.net_out_cached, a.net_sampled_at = now_in, now_out, now
```

- [ ] **Step 8: Call it from the app branch**

In the app cache refresh loop, immediately after the line
`a.mem_bytes_cached, a.uptime_s_cached = g["mem_bytes"], g["uptime_s"]`:

```python
        # 0 from PVE means "no reading", not "zero bytes used": a stopped
        # container reports 0 disk. None keeps that distinguishable from a
        # container that genuinely uses nothing.
        a.disk_bytes_cached = g["disk_used_bytes"] or None
        a.disk_total_bytes_cached = g["disk_bytes"] or None
        _update_net_rates(a, g, now)
```

- [ ] **Step 9: Narrow the stale ponytail comment**

Further down the same loop is a `ponytail:` comment recording that guest disk was skipped because `/cluster/resources` reports `disk` meaningfully for LXC but routinely 0 for QEMU. Apps are all LXC, so half its reasoning no longer applies. Replace it with:

```python
        # ponytail: no disk_pct SAMPLE for apps or VMs. Apps now cache a disk
        # reading (disk_bytes_cached above), but that is a current value on
        # the row, not a series: /cluster/resources' `disk` field is
        # meaningful for LXC and routinely 0 for QEMU, so a guest disk_pct
        # series would be silently wrong for every VM. Task 12's rule
        # validation rejects disk_pct on app/vm targets with an explanatory
        # 422 instead.
```

- [ ] **Step 10: Run the new tests**

Run: `.venv/bin/python -m pytest tests/test_poller_ingest.py -q -k "storage or counter or rate or reset"`
Expected: PASS, 4 tests.

- [ ] **Step 11: Run the whole poller and app suite for regressions**

Run: `.venv/bin/python -m pytest tests/test_poller_ingest.py tests/test_poller_reap.py tests/test_poller_degraded.py tests/test_poller_loop.py tests/test_apps_vms_api.py -q -m "not pve_integration and not e2e"`
Expected: PASS. The existing `MetricSample ... count() == 3` assertions still hold, because this task adds columns only and writes no new samples.

- [ ] **Step 12: Verify the migration applies**

Run: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`
Expected: three clean runs, no error. This proves `downgrade()` actually reverses the change rather than only existing.

- [ ] **Step 13: Commit**

```bash
git add backend/proxploy/models/__init__.py backend/proxploy/pollers/__init__.py \
        backend/proxploy/migrations/versions/d5b3f9c17e08_app_disk_net.py \
        backend/tests/fixtures/pve/cluster_resources_basic.json \
        backend/tests/test_poller_ingest.py
git commit -m "feat(poller): cache app storage and network rate

netin/netout are counters, so the rate is diffed across cycles against a
stored reading and its timestamp. A negative delta means the container
restarted and zeroed them, which yields no rate rather than a fabricated
spike."
```

---

### Task 2: Serialize the new fields

**Files:**
- Modify: `backend/proxploy/api/apps.py` (the `_app_out` return dict)
- Modify: `frontend/src/api/hooks.ts` (the `AppRow` type)
- Test: `backend/tests/test_apps_vms_api.py`

**Interfaces:**
- Consumes: the seven columns from Task 1.
- Produces: four new fields on every app JSON object and on `AppRow`, all `number | null`: `disk_bytes`, `disk_total_bytes`, `net_in_bps`, `net_out_bps`. Tasks 5, 6 and 7 render these.

The raw counters and `net_sampled_at` are deliberately NOT serialized. They exist so the poller can compute the next rate; a client has no use for them.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_apps_vms_api.py`. That file has no `client`/`db`/`host`
fixtures: every test builds its own via the module-local `_seeded(tmp_path)` helper and
takes `(tmp_path, csrf_header, bootstrap_admin)`. Follow that exactly.

`_seeded` already seeds two apps: CT 150 "Immich" with cached metrics, and CT 151
"Paperless" with none. The second is the unpolled case, so it needs no new seeding.

```python
def test_app_out_carries_storage_and_network(tmp_path, csrf_header, bootstrap_admin):
    """The four fields the Apps views read. The raw netin/netout counters are
    NOT among them: they exist so the poller can compute the next rate, and a
    client has nothing to do with a number that only means something next to
    the previous one."""
    from proxploy.models import App

    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()
        with app.state.sessionmaker() as db:
            row = db.query(App).filter_by(ctid=150).one()
            row.disk_bytes_cached = 5_368_709_120
            row.disk_total_bytes_cached = 17_179_869_184
            row.net_in_bps_cached = 10_000.0
            row.net_out_bps_cached = 20.0
            db.commit()

        immich = next(r for r in c.get("/api/v1/apps").json() if r["slug"] == "immich")

        assert immich["disk_bytes"] == 5_368_709_120
        assert immich["disk_total_bytes"] == 17_179_869_184
        assert immich["net_in_bps"] == 10_000.0
        assert immich["net_out_bps"] == 20.0
        assert "net_in_cached" not in immich and "net_sampled_at" not in immich


def test_an_unpolled_app_serializes_null_metrics_not_zero(tmp_path, csrf_header,
                                                          bootstrap_admin):
    """Null is the honest answer for an app the poller has not reached. Zero
    would claim a container is idle when nothing has looked at it yet.

    CT 151 (Paperless) is seeded with no cached metrics at all, which is
    exactly that case."""
    app, c, seed = _seeded(tmp_path)
    with c:
        bootstrap_admin(c)
        seed()

        row = next(r for r in c.get("/api/v1/apps").json() if r["slug"] == "paperless")

        assert row["disk_bytes"] is None and row["disk_total_bytes"] is None
        assert row["net_in_bps"] is None and row["net_out_bps"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_apps_vms_api.py -q -k "storage_and_network or unpolled"`
Expected: FAIL with `KeyError: 'disk_bytes'`.

- [ ] **Step 3: Add the fields to the serializer**

In `backend/proxploy/api/apps.py`, in the `_app_out` return dict, after the `"cpu_pct"`/`"mem_bytes"`/`"mem_total_bytes"` lines:

```python
        # Storage is a pair so the card can draw a bar; network is two rates
        # with no denominator, because there is no link speed to divide by.
        # The raw netin/netout counters stay on the row: they only mean
        # something next to the previous reading, which is the poller's
        # business, not a client's.
        "disk_bytes": a.disk_bytes_cached,
        "disk_total_bytes": a.disk_total_bytes_cached,
        "net_in_bps": a.net_in_bps_cached,
        "net_out_bps": a.net_out_bps_cached,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_apps_vms_api.py -q`
Expected: PASS, whole file.

- [ ] **Step 5: Extend the AppRow type**

In `frontend/src/api/hooks.ts`, in the `AppRow` type, after the `mem_bytes`/`mem_total_bytes` line:

```ts
  // Used and allocated bytes, from /cluster/resources' `disk`/`maxdisk`.
  disk_bytes: number | null; disk_total_bytes: number | null
  // Bytes per second, diffed by the poller from PVE's netin/netout counters.
  // Null on the first cycle for an app and on the cycle after a container
  // restart zeroes the counters, both of which are "no reading", never zero
  // traffic.
  net_in_bps: number | null; net_out_bps: number | null
```

- [ ] **Step 6: Typecheck**

Run: `npx tsc -b`
Expected: clean. Test fixtures build `AppRow` objects as literals with an inferred type, so a missing field does not break compilation; the views added in later tasks are what read these.

- [ ] **Step 7: Commit**

```bash
git add backend/proxploy/api/apps.py backend/tests/test_apps_vms_api.py frontend/src/api/hooks.ts
git commit -m "feat(api): serialize app storage and network rate

Four read-only fields. The raw counters stay on the row, since a single
counter reading means nothing without the one before it."
```

---

### Task 3: Extract the Open web UI mutation

Pure refactor, no behaviour change. The mutation is a local `useMutation` inside `routes/apps.tsx`, so the icon menu in Task 7 cannot call it. Moving it out is what makes one implementation serve both.

**Files:**
- Create: `frontend/src/api/open-web-ui.ts`
- Modify: `frontend/src/routes/apps.tsx` (delete the local mutation, import the hook)
- Test: `frontend/src/tests/open-web-ui.test.tsx` (existing, must keep passing unchanged)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `useOpenWebUi(app: AppRow)` returning TanStack Query's mutation object, whose `mutate(tab: Window | null)` points `tab` at the app's resolved URL. Task 7 calls it.

- [ ] **Step 1: Read the current implementation**

Read `frontend/src/routes/apps.tsx` around the `openWebUi` mutation. Move it VERBATIM, comments included. Those comments record two non-obvious constraints: why the address comes from `addresses` rather than `ip` (a DHCP container has the literal word `dhcp` in its config), and why the tab is opened by the caller before the `await` (after it, the call is outside the user gesture and a popup blocker drops the tab, which is the one thing the action exists to produce). Losing either comment invites the bug back.

- [ ] **Step 2: Create the hook**

```ts
import { useMutation } from '@tanstack/react-query'
import { api } from './client'
import type { AppRow } from './hooks'
import { notify } from '../lib/notify'

/**
 * "Open web UI" for one app, as a hook so the app detail header and the icon
 * grid's menu share one implementation rather than two that drift.
 *
 * THE TAB IS THE CALLER'S. `mutate` takes an already-opened window and points
 * it at the resolved URL. Opening it here would put window.open after the
 * await below, outside the user gesture that started it, and a popup blocker
 * would drop it. Callers do:
 *
 *   const tab = window.open('', '_blank')
 *   if (tab) tab.opener = null
 *   openWebUi.mutate(tab)
 */
export function useOpenWebUi(app: AppRow) {
  return useMutation({
    mutationFn: async (tab: Window | null) => {
      // Address is read live off the guest's own NIC config on click, never
      // off a column set at install: a DHCP lease or a manual re-IP moves the
      // guest and a value cached at install would silently point at the old
      // one.
      //
      // `addresses`, not `ip`. `ip` is the CONFIG, and a container on DHCP has
      // the literal word `dhcp` there, so reading it used to reject every DHCP
      // guest and report that the address could not be determined.
      // `addresses` is what the container actually holds: the configured
      // address when there is one, else what PVE reports on
      // /lxc/{vmid}/interfaces.
      const nics = await api<{ addresses: string[] | null }[]>(`/apps/${app.id}/network`)
      const addr = nics.flatMap((n) => n.addresses ?? [])[0]?.split('/')[0]
      if (!addr) { tab?.close(); throw new Error('no address') }
      const url = `${app.web_protocol || 'http'}://${addr}:${app.catalog_port}${app.web_path || '/'}`
      if (tab) tab.location.href = url
      else window.open(url, '_blank', 'noopener,noreferrer')
    },
    onError: () => notify.error(`Could not determine ${app.name}'s address.`),
  })
}
```

- [ ] **Step 3: Use it in the route**

In `frontend/src/routes/apps.tsx`, delete the local `openWebUi` mutation and its comment block. The hook needs the app row, which is only available inside `QueryState`'s render prop, so it is called in the small component that renders the header actions. If the header is currently inline inside the render prop, extract just the actions row into a component in the same file:

```tsx
function OpenWebUiButton({ app, denied }: { app: AppRow; denied: boolean }) {
  const openWebUi = useOpenWebUi(app)
  return (
    <Button variant="go" disabled={denied || openWebUi.isPending}
      title={denied ? 'Not included in your plan' : undefined}
      onClick={() => {
        const tab = window.open('', '_blank')
        if (tab) tab.opener = null
        openWebUi.mutate(tab)
      }}>
      Open web UI
    </Button>
  )
}
```

and replace the existing button with `{app.catalog_port != null && <OpenWebUiButton app={app} denied={openUiDenied} />}`, preserving the `catalog_port != null` guard exactly. A hook cannot be called conditionally, which is why the guard stays outside the component rather than becoming an early return inside it.

- [ ] **Step 4: Run the existing test unchanged**

Run: `npx vitest run --no-file-parallelism src/tests/open-web-ui.test.tsx`
Expected: PASS, all 3 tests, with NO edits to the test file. This is the whole point of the step: the test exercises the detail header, so if it still passes, the refactor changed no behaviour. If it needs editing to pass, the refactor was not behaviour-preserving.

- [ ] **Step 5: Typecheck and lint**

Run: `npx tsc -b && npx oxlint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/open-web-ui.ts frontend/src/routes/apps.tsx
git commit -m "refactor(apps): extract useOpenWebUi from the detail route

Same implementation, callable from more than one place. The icon grid's
menu needs it and could not reach a mutation defined inside a route."
```

---

### Task 4: One source of truth for the action gates

Three gates decide whether an app action is offered, and they currently live inside components that render `Button`s. Menu items are not buttons, so Task 7 cannot reuse those components, and re-deriving the gates in the menu is how a menu ends up offering Start on a host that cannot perform it.

**Files:**
- Create: `frontend/src/api/app-gates.ts`
- Modify: `frontend/src/components/LifecycleActions.tsx` (both `LifecycleActions` and `ConsoleButton` consume the hook)
- Test: `frontend/src/tests/app-gates.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:

```ts
type AppGate = { denied: boolean; reason: string | undefined }
function useAppActionGates(hostId: number): {
  lifecycle: AppGate
  console: AppGate
  openUi: AppGate
}
```

`denied` true means the control is disabled; `reason` is the tooltip, undefined when nothing is withheld. Task 7 reads all three.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/app-gates.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let features: Record<string, boolean> = { 'apps.lifecycle': true, 'apps.open_ui': true }
let capabilities: Record<string, boolean> | null = { lifecycle: true, console: true }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', grace: null, clock_skew: false, features })
    }
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'pve1', capabilities }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

import { useAppActionGates } from '../api/app-gates'

const wrap = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useAppActionGates', () => {
  it('withholds nothing once both fetches land and both say yes', async () => {
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    capabilities = { lifecycle: true, console: true }
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    await waitFor(() => expect(result.current.lifecycle.denied).toBe(false))
    expect(result.current.console.denied).toBe(false)
    expect(result.current.openUi.denied).toBe(false)
    expect(result.current.lifecycle.reason).toBeUndefined()
  })

  it('withholds nothing while the fetches are still in flight', () => {
    // Gating on an unresolved entitlement would grey out every action for the
    // whole first fetch, for every plan, not only the ones that lack the flag.
    // Only an answer that has actually arrived may withhold anything.
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    expect(result.current.lifecycle.denied).toBe(false)
    expect(result.current.console.denied).toBe(false)
  })

  it('explains a missing lifecycle token rather than only greying out', async () => {
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    capabilities = { lifecycle: false, console: true }
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    await waitFor(() => expect(result.current.lifecycle.denied).toBe(true))
    expect(result.current.lifecycle.reason).toMatch(/Settings/)
    expect(result.current.console.denied).toBe(false)
  })

  it('reports a plan that does not include an action', async () => {
    features = { 'apps.lifecycle': false, 'apps.open_ui': false }
    capabilities = { lifecycle: true, console: true }
    const { result } = renderHook(() => useAppActionGates(1), { wrapper: wrap })
    await waitFor(() => expect(result.current.lifecycle.denied).toBe(true))
    expect(result.current.lifecycle.reason).toBe('Not included in your plan')
    expect(result.current.openUi.denied).toBe(true)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run --no-file-parallelism src/tests/app-gates.test.tsx`
Expected: FAIL, cannot resolve `../api/app-gates`.

- [ ] **Step 3: Write the hook**

Create `frontend/src/api/app-gates.ts`:

```ts
import { useEntitlements } from './hooks'
import { useHostCapabilities } from './hosts'

export type AppGate = { denied: boolean; reason: string | undefined }

const NO_GATE: AppGate = { denied: false, reason: undefined }
const NOT_IN_PLAN = 'Not included in your plan'
const noToken = (what: string) =>
  `This host has no ${what} API token configured. Add one in Settings → Hosts.`

/**
 * Whether each app action is available on one host, and why not when it is
 * not.
 *
 * ONE hook rather than the checks living inside the components, because the
 * icon grid offers the same actions as MENU ITEMS, which are not buttons and
 * so cannot reuse LifecycleActions or ConsoleButton. Two copies of these rules
 * is how a menu ends up offering Start on a host that cannot perform it.
 *
 * BOTH SOURCES ARE "INNOCENT UNTIL PROVEN GUILTY". useEntitlements().has()
 * returns false until /entitlements resolves, and capabilities read undefined
 * until GET /hosts does. Withholding on either of those would grey out (and
 * swallow clicks on) every action for the entire first fetch, on every plan
 * and every host, not just the ones that actually lack the flag. So only an
 * answer that has arrived, and says no, withholds anything.
 */
export function useAppActionGates(hostId: number) {
  const ent = useEntitlements()
  const hostCaps = useHostCapabilities(hostId)
  const landed = ent.data != null
  const capsLanded = hostCaps.loaded

  const plan = (flag: string): boolean => landed && !ent.has(flag)
  const capability = (name: 'lifecycle' | 'console'): boolean =>
    capsLanded && hostCaps.capabilities?.[name] === false

  const gate = (missingToken: string | null, flag: string): AppGate => {
    if (missingToken) return { denied: true, reason: noToken(missingToken) }
    if (plan(flag)) return { denied: true, reason: NOT_IN_PLAN }
    return NO_GATE
  }

  return {
    lifecycle: gate(capability('lifecycle') ? 'lifecycle' : null, 'apps.lifecycle'),
    // NO entitlement flag. ConsoleButton gates on the host capability and
    // nothing else today, so adding one here would newly withhold Console
    // from a plan that has it. This hook must change what no existing control
    // does; it only moves where the rules live.
    console: capability('console')
      ? { denied: true, reason: noToken('console') }
      : NO_GATE,
    // Open reads an address and opens a tab. It needs no PVE token at all, so
    // no capability gates it, only the plan.
    openUi: gate(null, 'apps.open_ui'),
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run --no-file-parallelism src/tests/app-gates.test.tsx`
Expected: PASS, 4 tests.

- [ ] **Step 5: Consume it in LifecycleActions and ConsoleButton**

In `frontend/src/components/LifecycleActions.tsx`, replace the inline `denied` / `noLifecycle` / `reason` derivation in `LifecycleActions` with `const gates = useAppActionGates(hostId)`, then use `gates.lifecycle.denied` and `gates.lifecycle.reason`. Do the same in `ConsoleButton` with `gates.console`. Delete the now-duplicated comments from those components and leave a one-line pointer:

```ts
  // Why an unresolved fetch withholds nothing: api/app-gates.ts.
```

`target` is `'app' | 'vm'` in `LifecycleActions`, and the VM flag is `vms.lifecycle`. Keep the VM path exactly as it is: this hook is the app gates, and folding VMs into it is a bigger change than this task. Branch on `target` so VMs keep their existing derivation.

- [ ] **Step 6: Run the affected suites**

Run: `npx vitest run --no-file-parallelism src/tests/lifecycle.test.tsx src/tests/guest-list.test.tsx src/tests/apps.test.tsx src/tests/hosts.test.tsx src/tests/app-gates.test.tsx`
Expected: PASS, with no edits to the pre-existing test files.

- [ ] **Step 7: Typecheck, lint, commit**

Run: `npx tsc -b && npx oxlint`

```bash
git add frontend/src/api/app-gates.ts frontend/src/components/LifecycleActions.tsx \
        frontend/src/tests/app-gates.test.tsx
git commit -m "refactor(apps): one hook for the app action gates

The icon grid offers these actions as menu items, which are not buttons
and cannot reuse the components the rules lived inside. Two copies is how
a menu ends up offering Start on a host that cannot perform it."
```

---

### Task 5: Detailed view gains storage and network

**Files:**
- Modify: `frontend/src/components/AppCard.tsx` (both `AppCard` and `AppCardSkeleton`)
- Test: `frontend/src/tests/app-card-metrics.test.tsx`

**Interfaces:**
- Consumes: `AppRow.disk_bytes`, `disk_total_bytes`, `net_in_bps`, `net_out_bps` from Task 2.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/app-card-metrics.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn(() => Promise.resolve([])),
  ApiError: class extends Error {},
}))
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => () => {},
}))

import { AppCard } from '../components/AppCard'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 2147483648, mem_total_bytes: 4294967296, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 5368709120, disk_total_bytes: 17179869184,
  net_in_bps: 1200000, net_out_bps: 88000,
}

const wrap = (app: AppRow) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppCard app={app} /></QueryClientProvider>)
}

describe('AppCard storage and network', () => {
  it('shows storage as used against allocated', () => {
    wrap(APP)
    expect(screen.getByText(/5\.0 GB \/ 16\.0 GB/)).toBeInTheDocument()
  })

  it('shows both network directions as rates', () => {
    wrap(APP)
    // fmtBps takes bytes/s and renders bits/s, the vocabulary the node
    // network charts already use.
    expect(screen.getByText(/9\.6 Mbps/)).toBeInTheDocument()
    expect(screen.getByText(/704\.0 kbps/)).toBeInTheDocument()
  })

  it('renders a missing reading as unknown, never as zero', () => {
    // An unpolled app, a stopped container, and the cycle after a counter
    // reset all land here. "0 Mbps" would claim the container is idle when
    // nothing has measured it.
    wrap({ ...APP, disk_bytes: null, disk_total_bytes: null,
           net_in_bps: null, net_out_bps: null })
    expect(screen.queryByText(/Mbps/)).toBeNull()
    expect(screen.getAllByText(/unknown/i).length).toBeGreaterThan(0)
  })
})
```

Before running, confirm the exact strings `fmtBytes` and `fmtBps` produce for these inputs, and correct the assertions to match rather than changing the formatters:

```bash
cd frontend && npx tsx -e "import{fmtBytes,fmtBps}from './src/lib/format';console.log(fmtBytes(5368709120),'|',fmtBytes(17179869184),'|',fmtBps(1200000),'|',fmtBps(88000),'|',fmtBps(null))"
```

If `tsx` is not available, add a temporary case to `src/tests/format.test.ts`, read the failure output for the actual values, then remove it.

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run --no-file-parallelism src/tests/app-card-metrics.test.tsx`
Expected: FAIL, the storage and network text is not in the document.

- [ ] **Step 3: Add the rows to the card**

In `frontend/src/components/AppCard.tsx`, import `fmtBps` and `fmtBytes` from `../lib/format`. `UsageBar` exports `CPU_GRADIENT` and `RAM_GRADIENT` and no disk gradient, so storage reuses `RAM_GRADIENT`: a fourth colour would be inventing one, and `src/tests/no-hardcoded-colors.test.ts` forbids a literal anyway. Compute alongside `memPct`:

```tsx
  const diskPct = app.disk_bytes != null && app.disk_total_bytes
    ? (app.disk_bytes / app.disk_total_bytes) * 100 : null
```

Then inside the `space-y-2` block, after the RAM row:

```tsx
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">DSK</span>
          <div className="flex-1"><UsageBar pct={diskPct} gradient={RAM_GRADIENT} /></div>
          <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(diskPct)}</span>
        </div>
        <div className="font-mono text-[11px] text-text-2">
          {app.disk_total_bytes
            ? `${fmtBytes(app.disk_bytes)} / ${fmtBytes(app.disk_total_bytes)}`
            : fmtBytes(app.disk_bytes)}
        </div>
        {/* No bar for network: there is no denominator. Inventing a link
            speed to draw against would be making up a number, which is the
            same call GuestList makes about VM memory. */}
        <div className="flex items-center gap-2">
          <span className="w-8 text-[10.5px] uppercase text-text-3">NET</span>
          <span className="font-mono text-[11px] text-text-2">↓ {fmtBps(app.net_in_bps)}</span>
          <span className="font-mono text-[11px] text-text-2">↑ {fmtBps(app.net_out_bps)}</span>
        </div>
```

- [ ] **Step 4: Update the skeleton in the same edit**

`AppCardSkeleton`'s own comment says every measurement in it is copied from the card so the two end up the same height, and that changing one means changing the other. The card grew by three rows, so add to the skeleton's `space-y-2` block, after the two existing `SkeletonMeterRow`s:

```tsx
        <SkeletonMeterRow />
        <SkeletonLine className="w-28 text-[11px]" />
        <SkeletonLine className="w-40 text-[11px]" />
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npx vitest run --no-file-parallelism src/tests/app-card-metrics.test.tsx`
Expected: PASS, 3 tests.

- [ ] **Step 6: Check the card still fits its geometry budget**

The repo pins fixed-height component geometry with a harness. Run: `npm run harness`
Expected: PASS. If the taller card overflows a pinned height, raise the pinned height for this component rather than removing a row; the card is not fixed-height the way the Store card is, so this most likely just passes.

- [ ] **Step 7: Run the app and look at it**

```bash
node e2e/driver.mjs shot /tmp/pp-cards.png /hosts
```

Open the PNG and confirm the two new rows read as part of the card rather than crowding it, and that a stopped app shows "unknown" rather than a zeroed bar. A blank frame means the dev server is not up, not a pass.

- [ ] **Step 8: Typecheck, lint, commit**

Run: `npx tsc -b && npx oxlint && npx vitest run --no-file-parallelism`

```bash
git add frontend/src/components/AppCard.tsx frontend/src/tests/app-card-metrics.test.tsx
git commit -m "feat(apps): show storage and network on the app card

Storage gets a bar; network does not, because there is no denominator to
draw one against."
```

---

### Task 6: List view

**Files:**
- Create: `frontend/src/components/AppTable.tsx` (exports `AppTable` and `AppTableSkeleton`)
- Test: `frontend/src/tests/app-table.test.tsx`

**Interfaces:**
- Consumes: `AppRow` including Task 2's fields; `LifecycleActions` and `ConsoleButton` from `./LifecycleActions`; `openConsoleWindow` from `../lib/console-window`.
- Produces: `<AppTable apps={AppRow[]} />` and `<AppTableSkeleton rows={number} />`. Task 8 renders both.

Not an extension of `GuestList`. That component merges apps and VMs into one row shape and its `Guest` type is deliberately lossy (memory pre-formatted to a string, no disk, no network) because VMs have no data for those columns. Widening it would put permanently empty columns on every VM row.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/tests/app-table.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', () => ({
  api: vi.fn(() => Promise.resolve([])),
  ApiError: class extends Error {},
}))
const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
}))

import { AppTable } from '../components/AppTable'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 2147483648, mem_total_bytes: 4294967296, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 5368709120, disk_total_bytes: 17179869184,
  net_in_bps: 1200000, net_out_bps: 88000,
}

const wrap = (apps: AppRow[]) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppTable apps={apps} /></QueryClientProvider>)
}

describe('AppTable', () => {
  it('is a real table, so a screen reader gets the column each cell belongs to', () => {
    wrap([APP])
    expect(screen.getByRole('table')).toBeInTheDocument()
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['App', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', ''])
  })

  it('carries the same detail as the card', () => {
    wrap([APP])
    const row = screen.getByRole('row', { name: /Immich/ })
    expect(within(row).getByText('Immich')).toBeInTheDocument()
    expect(within(row).getByText(/CT 150/)).toBeInTheDocument()
    expect(within(row).getByText(/running/i)).toBeInTheDocument()
    expect(within(row).getByText(/5\.0 GB \/ 16\.0 GB/)).toBeInTheDocument()
    expect(within(row).getByText(/9\.6 Mbps/)).toBeInTheDocument()
  })

  it('opens the app detail page from the name', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    wrap([APP])
    await userEvent.click(screen.getByRole('button', { name: 'Immich' }))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      params: expect.objectContaining({ appId: '1' }),
    }))
  })

  it('renders a missing reading as unknown, never as zero', () => {
    wrap([{ ...APP, disk_bytes: null, disk_total_bytes: null,
            net_in_bps: null, net_out_bps: null }])
    expect(screen.queryByText(/Mbps/)).toBeNull()
  })
})
```

Correct the `fmtBytes`/`fmtBps` expectations to the real output the same way Task 5 Step 1 describes.

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run --no-file-parallelism src/tests/app-table.test.tsx`
Expected: FAIL, cannot resolve `../components/AppTable`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/AppTable.tsx`. Use a real `<table>`, not a grid of divs: eight columns of numbers is exactly the case where a screen reader needs the header association a table gives for free, and `GuestList`'s div-based list exists because it has four fields, not eight.

```tsx
import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { fmtBps, fmtBytes, fmtPct } from '../lib/format'
import { openConsoleWindow } from '../lib/console-window'
import { ConsoleButton, LifecycleActions } from './LifecycleActions'
import { StatusPill } from './StatusPill'
import { Skeleton, SkeletonLine } from './ui/skeleton'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

const HEADS = ['App', 'Host', 'Status', 'CPU', 'RAM', 'Storage', 'Network', '']

const th = 'px-4 py-2 text-left text-[10.5px] font-normal uppercase text-text-3'
const td = 'px-4 py-3 align-middle'

/**
 * The Apps section's list view: every app as a row, carrying the same
 * measurements the detailed card shows.
 *
 * NOT an extension of GuestList. That component exists to merge apps and VMs
 * into ONE row shape, and its Guest type is deliberately lossy (memory
 * pre-formatted to a string, no disk, no network) because VMs have no data
 * for those columns. Widening it to fit this view would put permanently empty
 * columns on every VM row.
 */
export function AppTable({ apps }: { apps: AppRow[] }) {
  return (
    <div className="overflow-x-auto rounded-card border border-line-soft bg-panel">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-line-soft">
            {HEADS.map((h, i) => (
              <th key={h || `actions-${i}`} scope="col" className={th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {apps.map((a) => <AppTableRow key={a.id} app={a} />)}
        </tbody>
      </table>
    </div>
  )
}

function AppTableRow({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const memPct = app.mem_bytes != null && app.mem_total_bytes
    ? (app.mem_bytes / app.mem_total_bytes) * 100 : null
  const diskPct = app.disk_bytes != null && app.disk_total_bytes
    ? (app.disk_bytes / app.disk_total_bytes) * 100 : null
  return (
    <tr className="border-b border-line-soft last:border-b-0">
      <td className={td}>
        <button type="button"
          className="text-left font-mono text-[13px] text-text transition hover:text-amber"
          onClick={() => navigate({ to: '/apps/$appId' as never,
                                    params: { appId: String(app.id) } as never })}>
          {app.name}
        </button>
        {app.update_available && (
          <span className="ml-2 rounded bg-amber-dim px-1.5 py-0.5 font-mono
                           text-[9.5px] uppercase text-amber">update</span>
        )}
      </td>
      <td className={`${td} font-mono text-[11px] text-text-3`}>
        {app.host_name} · CT {app.ctid}
      </td>
      <td className={td}><StatusPill status={app.status} /></td>
      <td className={td}><Meter pct={app.cpu_pct} gradient={CPU_GRADIENT} /></td>
      <td className={td}><Meter pct={memPct} gradient={RAM_GRADIENT} /></td>
      <td className={td}>
        <Meter pct={diskPct} gradient={RAM_GRADIENT} />
        <div className="font-mono text-[11px] text-text-3">
          {app.disk_total_bytes
            ? `${fmtBytes(app.disk_bytes)} / ${fmtBytes(app.disk_total_bytes)}`
            : fmtBytes(app.disk_bytes)}
        </div>
      </td>
      {/* No bar: a rate has no denominator to draw one against. */}
      <td className={`${td} whitespace-nowrap font-mono text-[11px] text-text-2`}>
        ↓ {fmtBps(app.net_in_bps)} ↑ {fmtBps(app.net_out_bps)}
      </td>
      <td className={td}>
        <div className="flex items-center justify-end gap-2">
          <LifecycleActions target="app" id={app.id} name={app.name}
                            status={app.status} hostId={app.host_id} size="sm" />
          <ConsoleButton hostId={app.host_id}
            onClick={() => openConsoleWindow('app', app.id)} />
        </div>
      </td>
    </tr>
  )
}

function Meter({ pct, gradient }: { pct: number | null; gradient: string }) {
  return (
    <div className="flex w-28 items-center gap-2">
      <div className="flex-1"><UsageBar pct={pct} gradient={gradient} /></div>
      <span className="w-9 text-right font-mono text-[11px] text-text-2">{fmtPct(pct)}</span>
    </div>
  )
}

/** The table's placeholder. Mirrors the row's px-4 py-3 rhythm and the two
 *  pieces tall enough to set its height, so the page below does not shift
 *  when the apps land. Edited with AppTableRow, never separately. */
export function AppTableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="overflow-x-auto rounded-card border border-line-soft bg-panel">
      <table className="w-full border-collapse">
        <tbody>
          {Array.from({ length: rows }, (_, i) => (
            <tr key={i} className="border-b border-line-soft last:border-b-0">
              <td className={td}><SkeletonLine className="w-28 text-[13px]" /></td>
              <td className={td}><SkeletonLine className="w-32 text-[11px]" /></td>
              <td className={td}><Skeleton className="h-[19px] w-20 rounded-full" /></td>
              <td className={td}><Skeleton className="h-1.5 w-28 rounded-full" /></td>
              <td className={td}><Skeleton className="h-1.5 w-28 rounded-full" /></td>
              <td className={td}><Skeleton className="h-1.5 w-28 rounded-full" /></td>
              <td className={td}><SkeletonLine className="w-32 text-[11px]" /></td>
              <td className={td}><Skeleton className="ms-auto h-6 w-40 rounded-ctl" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

`UsageBar`'s `gradient` prop type may not be `string`; read `UsageBar.tsx` and use whatever type `CPU_GRADIENT` actually is in the `Meter` signature.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run --no-file-parallelism src/tests/app-table.test.tsx`
Expected: PASS, 4 tests.

- [ ] **Step 5: Typecheck, lint, commit**

Run: `npx tsc -b && npx oxlint`

```bash
git add frontend/src/components/AppTable.tsx frontend/src/tests/app-table.test.tsx
git commit -m "feat(apps): list view for the Apps section

A real table, because eight columns of numbers is where a screen reader
needs the header association one gives for free."
```

---

### Task 7: Icon view and its five-action menu

**Files:**
- Create: `frontend/src/components/AppIconGrid.tsx` (exports `AppIconGrid`, `AppIconGridSkeleton`)
- Create: `frontend/src/components/AppIconMenu.tsx`
- Modify: `frontend/src/components/IconTile.tsx` (the `size` union gains `64`)
- Test: `frontend/src/tests/app-icon-grid.test.tsx`

**Interfaces:**
- Consumes: `useAppActionGates` (Task 4), `useOpenWebUi` (Task 3), `useLifecycle` from `../api/jobs`, `openConsoleWindow` from `../lib/console-window`.
- Produces: `<AppIconGrid apps={AppRow[]} />` and `<AppIconGridSkeleton count={number} />`. Task 8 renders both.

- [ ] **Step 1: Widen IconTile**

In `frontend/src/components/IconTile.tsx`, change the `size` prop type to `40 | 56 | 64` and add the matching box class. The existing comment calls the union a closed pair "so the tile can carry the matching radius and glyph size with it instead of every caller restating them", so keep that property: add the third entry, do not switch to a free number.

```tsx
  const box = size === 40
    ? 'h-10 w-10 rounded-tile text-[14px]'
    : size === 56
      ? 'h-14 w-14 rounded-card text-[18px]'
      : 'h-16 w-16 rounded-card text-[20px]'
```

Update the prop's doc comment to say "40 on a card, 56 on a detail header, 64 in the icon grid."

- [ ] **Step 2: Write the failing test**

Create `frontend/src/tests/app-icon-grid.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Icon is stubbed so this file tests the GRID, not the font subset;
// icon.test.tsx pins Icon's own contract (host-actions-menu.test.tsx
// precedent).
vi.mock('../components/ui/icon', () => ({
  Icon: ({ name, size }: { name: string; size?: number }) => (
    <span data-icon={name} data-size={size ?? 18} />
  ),
}))

let features: Record<string, boolean> = { 'apps.lifecycle': true, 'apps.open_ui': true }
let capabilities: Record<string, boolean> = { lifecycle: true, console: true }

vi.mock('../api/client', () => ({
  api: vi.fn((path: string) => {
    if (path === '/entitlements') {
      return Promise.resolve({ tier: 'builtin', grace: null, clock_skew: false, features })
    }
    if (path.startsWith('/hosts')) {
      return Promise.resolve([{ id: 1, name: 'pve-a', capabilities }])
    }
    return Promise.resolve(null)
  }),
  ApiError: class extends Error {},
}))

const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (orig) => ({
  ...(await orig() as object),
  useNavigate: () => navigate,
}))

import { AppIconGrid } from '../components/AppIconGrid'
import type { AppRow } from '../api/hooks'

const APP: AppRow = {
  id: 1, name: 'Immich', slug: 'immich', host_id: 1, host_name: 'pve-a',
  node: 'pve-a', ctid: 150, category: null, catalog_slug: 'immich',
  icon_initials: 'IM', icon_colors: null, icon_url: null,
  web_port: null, web_protocol: 'http', web_path: '/', catalog_port: 8096,
  status: 'running', ip: '10.0.0.5', cpu_pct: 12,
  mem_bytes: 1, mem_total_bytes: 2, uptime_s: 86400,
  update_available: null, adopted: false,
  disk_bytes: 1, disk_total_bytes: 2, net_in_bps: 1, net_out_bps: 1,
}

const wrap = (apps: AppRow[]) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppIconGrid apps={apps} /></QueryClientProvider>)
}

// Radix opens a menu on pointerdown, not click (AccountMenu/HostActionsMenu
// precedent).
const openMenu = (trigger: HTMLElement) =>
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })

describe('AppIconGrid', () => {
  beforeEach(() => {
    navigate.mockClear()
    features = { 'apps.lifecycle': true, 'apps.open_ui': true }
    capabilities = { lifecycle: true, console: true }
  })

  it('shows the state beside the name, never drawn on the logo', () => {
    wrap([APP])
    expect(screen.getByText(/running/i)).toBeInTheDocument()
    expect(screen.getByTestId('app-icon-1').querySelector('[data-icon]')).toBeNull()
  })

  it('keeps paused distinguishable from stopped', () => {
    wrap([{ ...APP, status: 'paused' }, { ...APP, id: 2, name: 'Plex', status: 'stopped' }])
    expect(screen.getByText(/paused/i)).toBeInTheDocument()
    expect(screen.getByText(/stopped/i)).toBeInTheDocument()
  })

  it('opens the app detail page from the name', () => {
    wrap([APP])
    fireEvent.click(screen.getByRole('button', { name: 'Immich' }))
    expect(navigate).toHaveBeenCalledWith(expect.objectContaining({
      params: expect.objectContaining({ appId: '1' }),
    }))
  })

  it('offers exactly the five actions on the logo, and no more', async () => {
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    // trim(): each item renders `<Icon /> {label}`, so its textContent
    // carries a leading space the stubbed Icon leaves behind.
    // Running, so Stop and Restart show and Start does not: the same action
    // set LifecycleActions already picks from status.
    expect(items.map((i) => i.textContent?.trim()))
      .toEqual(['Stop', 'Restart', 'Console', 'Open'])
  })

  it('offers Start instead of Stop when the app is stopped', async () => {
    wrap([{ ...APP, status: 'stopped' }])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.trim())).toEqual(['Start', 'Console', 'Open'])
  })

  it('hides Open when the app has no catalog port to point at', async () => {
    wrap([{ ...APP, catalog_port: null }])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent?.trim())).not.toContain('Open')
  })

  it('withholds lifecycle actions on a host with no lifecycle token', async () => {
    capabilities = { lifecycle: false, console: true }
    wrap([APP])
    openMenu(screen.getByRole('button', { name: /actions for Immich/i }))
    const stop = await screen.findByRole('menuitem', { name: 'Stop' })
    expect(stop).toHaveAttribute('data-disabled')
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npx vitest run --no-file-parallelism src/tests/app-icon-grid.test.tsx`
Expected: FAIL, cannot resolve `../components/AppIconGrid`.

- [ ] **Step 4: Write the menu**

Create `frontend/src/components/AppIconMenu.tsx`. It reuses `HostActionsMenu`'s item classes and the same Radix primitive.

```tsx
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import type { AppRow } from '../api/hooks'
import { useAppActionGates } from '../api/app-gates'
import { useLifecycle } from '../api/jobs'
import { useOpenWebUi } from '../api/open-web-ui'
import { openConsoleWindow } from '../lib/console-window'
import { Icon } from './ui/icon'

const itemCls = 'flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-text-2 '
             + 'outline-none data-[highlighted]:bg-panel-2 data-[highlighted]:text-text '
             + 'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50'

// Icon names are STRING LITERALS in an `icon:` field, not a computed lookup:
// scripts/icon-names.mjs statically scans src/ to build the Google Fonts
// icon_names parameter, and a name it cannot read out of the source ships a
// font subset without that glyph, so the browser renders the literal word.
const RUNNING_ACTIONS = [
  { action: 'stop', label: 'Stop', icon: 'stop' },
  { action: 'restart', label: 'Restart', icon: 'restart_alt' },
] as const
const STOPPED_ACTIONS = [
  { action: 'start', label: 'Start', icon: 'play_arrow' },
] as const

/**
 * The icon grid's context menu: Start, Stop, Restart, Console, Open, and
 * nothing else.
 *
 * DELIBERATELY NARROWER than the app detail page's actions. Migrate,
 * Reconfigure and Uninstall are not here: this menu sits on a dense grid an
 * operator scans, and a destructive action one slip away from Restart is not
 * a trade worth making. The app page has all of them.
 */
export function AppIconMenu({ app, children }: { app: AppRow; children: React.ReactNode }) {
  const gates = useAppActionGates(app.host_id)
  const run = useLifecycle()
  const openWebUi = useOpenWebUi(app)
  const pending = app.status === 'pending' || run.isPending
  const actions = app.status === 'pending' ? []
    : app.status === 'running' ? RUNNING_ACTIONS : STOPPED_ACTIONS

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>{children}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="start" sideOffset={6}
          className="z-50 w-44 overflow-hidden rounded-card border border-line bg-panel
                     shadow-[0_12px_32px_rgba(0,0,0,.35)]">
          {actions.map((a) => (
            <DropdownMenu.Item key={a.action} className={itemCls}
              disabled={pending || gates.lifecycle.denied}
              title={gates.lifecycle.reason}
              onSelect={() => run.mutate({ target: 'app', id: app.id, action: a.action })}>
              <Icon name={a.icon} size={16} /> {a.label}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Item className={itemCls}
            disabled={gates.console.denied} title={gates.console.reason}
            onSelect={() => openConsoleWindow('app', app.id)}>
            <Icon name="terminal" size={16} /> Console
          </DropdownMenu.Item>
          {/* No catalog port means nothing to point a tab at, so the action is
              absent rather than offered and broken. Same rule as the detail
              header. */}
          {app.catalog_port != null && (
            <DropdownMenu.Item className={itemCls}
              disabled={gates.openUi.denied} title={gates.openUi.reason}
              onSelect={() => {
                // The tab opens HERE, inside the gesture. Opening it inside
                // the mutation would put window.open after an await and a
                // popup blocker would drop it.
                const tab = window.open('', '_blank')
                if (tab) tab.opener = null
                openWebUi.mutate(tab)
              }}>
              <Icon name="open_in_new" size={16} /> Open
            </DropdownMenu.Item>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
```

Check `useLifecycle`'s `mutate` argument shape against `LifecycleActions.tsx` and match it exactly. `LifecycleActions` also handles a 409 `self_target` by escalating to `ConfirmSelfDialog`; that path applies to hosts targeting themselves and is reachable from this menu too. If `useLifecycle` does not surface a default error toast, add the same `onError` handling `LifecycleActions.fire` uses so a refused action is never silent.

- [ ] **Step 5: Write the grid**

Create `frontend/src/components/AppIconGrid.tsx`:

```tsx
import { useNavigate } from '@tanstack/react-router'
import type { AppRow } from '../api/hooks'
import { statusLabel } from '../lib/activityDisplay'
import { AppIconMenu } from './AppIconMenu'
import { IconTile } from './IconTile'
import { Icon } from './ui/icon'
import { Skeleton, SkeletonLine } from './ui/skeleton'

/**
 * State, as a glyph and the word, for the icon grid.
 *
 * The COLOURS are StatusPill's, and the WORD is statusLabel's, so this view
 * cannot drift from the status vocabulary the rest of the app uses.
 *
 * Every status gets its own entry rather than collapsing to running/stopped:
 * paused and unknown are not "not running", and an operator who cannot tell
 * them apart cannot tell a container someone suspended from one PVE has lost
 * track of. `icon:` is the field shape scripts/icon-names.mjs reads, which is
 * why these are literals in a table rather than a computed name.
 */
const STATE: Record<string, { icon: string; cls: string }> = {
  running: { icon: 'play_arrow', cls: 'text-green' },
  paused: { icon: 'pause', cls: 'text-amber' },
  stopped: { icon: 'stop', cls: 'text-text-3' },
  pending: { icon: 'hourglass_empty', cls: 'text-text-3' },
  error: { icon: 'error', cls: 'text-red' },
  unknown: { icon: 'help', cls: 'text-text-3' },
}

export function AppIconGrid({ apps }: { apps: AppRow[] }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-4 rounded-card border border-line-soft
                    bg-panel p-4 sm:grid-cols-2 xl:grid-cols-4">
      {apps.map((a) => <AppIconCell key={a.id} app={a} />)}
    </div>
  )
}

function AppIconCell({ app }: { app: AppRow }) {
  const navigate = useNavigate()
  const state = STATE[app.status] ?? STATE.unknown
  return (
    <div className="flex items-center gap-3">
      {/* The logo is the menu. Nothing is drawn ON it: the tile is the app's
          own artwork and a badge over it would compete with whatever the
          logo already puts in that corner. */}
      <AppIconMenu app={app}>
        <button type="button" data-testid={`app-icon-${app.id}`}
          aria-label={`Actions for ${app.name}`}
          className="shrink-0 rounded-card transition hover:brightness-110">
          <IconTile name={app.name} iconUrl={app.icon_url} size={64}
                    initials={app.icon_initials} colors={app.icon_colors} />
        </button>
      </AppIconMenu>
      <div className="min-w-0">
        {/* The name is the way to the app page. The reference this view is
            modelled on has no detail page and so has only one target; this
            one does, and keeps a way in. */}
        <button type="button"
          className="block max-w-full truncate text-left text-[13px] text-text
                     transition hover:text-amber"
          onClick={() => navigate({ to: '/apps/$appId' as never,
                                    params: { appId: String(app.id) } as never })}>
          {app.name}
        </button>
        <div className={`flex items-center gap-1 font-mono text-[11px] ${state.cls}`}>
          <Icon name={state.icon} size={14} />
          {statusLabel(app.status)}
        </div>
      </div>
    </div>
  )
}

/** The grid's placeholder, mirroring the cell's 64px tile and two text lines
 *  so the page below does not shift when the apps land. */
export function AppIconGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-4 rounded-card border border-line-soft
                    bg-panel p-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-16 w-16 shrink-0 rounded-card" />
          <div className="min-w-0 flex-1">
            <SkeletonLine className="w-24 text-[13px]" />
            <SkeletonLine className="w-16 text-[11px]" />
          </div>
        </div>
      ))}
    </div>
  )
}
```

Confirm `statusLabel` is exported from `../lib/activityDisplay` (StatusPill imports it from there) and that `STATE`'s keys match the statuses `StatusPill.STYLES` handles. Where `StatusPill` maps a status this table does not, add it here rather than letting it fall to `unknown`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `npx vitest run --no-file-parallelism src/tests/app-icon-grid.test.tsx`
Expected: PASS, 7 tests.

- [ ] **Step 7: Confirm the new icon names reach the font link**

The grid and menu introduce `play_arrow`, `pause`, `stop`, `restart_alt`, `terminal`, `open_in_new`, `hourglass_empty`, `error` and `help`. All are literals the static scan can read, but verify rather than assume:

Run: `npx vitest run --no-file-parallelism src/tests/icon-names-coverage.test.tsx src/tests/icon-names-extraction.test.ts src/tests/icon-font-link.test.ts`
Expected: PASS. A failure here means a name is computed somewhere the extractor cannot follow; fix the call site to use a literal rather than adding the name to a list by hand, since no hand-maintained list exists.

- [ ] **Step 8: Typecheck, lint, commit**

Run: `npx tsc -b && npx oxlint`

```bash
git add frontend/src/components/AppIconGrid.tsx frontend/src/components/AppIconMenu.tsx \
        frontend/src/components/IconTile.tsx frontend/src/tests/app-icon-grid.test.tsx
git commit -m "feat(apps): icon view with a five-action menu

State sits beside the name as a glyph and the word rather than on the
logo, so paused and unknown stay distinguishable from stopped."
```

---

### Task 8: The switcher, wired into the Hosts page

**Files:**
- Create: `frontend/src/lib/apps-view.ts`
- Create: `frontend/src/components/AppsViewSwitch.tsx`
- Modify: `frontend/src/routes/hosts.tsx` (the Apps section)
- Test: `frontend/src/tests/apps-view.test.ts`, `frontend/src/tests/apps-view-switch.test.tsx`

**Interfaces:**
- Consumes: `AppCard`/`AppCardSkeleton` (Task 5), `AppTable`/`AppTableSkeleton` (Task 6), `AppIconGrid`/`AppIconGridSkeleton` (Task 7).
- Produces: `type AppsView = 'detailed' | 'list' | 'icon'`, `readAppsView(): AppsView`, `writeAppsView(v: AppsView): void`, `useAppsView(): [AppsView, (v: AppsView) => void]`, and `<AppsViewSwitch value onChange />`.

- [ ] **Step 1: Write the failing persistence test**

Create `frontend/src/tests/apps-view.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_APPS_VIEW, readAppsView, writeAppsView } from '../lib/apps-view'

describe('apps view persistence', () => {
  beforeEach(() => localStorage.clear())

  it('defaults to the detailed view with nothing stored', () => {
    expect(readAppsView()).toBe('detailed')
    expect(DEFAULT_APPS_VIEW).toBe('detailed')
  })

  it('round-trips a choice', () => {
    writeAppsView('icon')
    expect(readAppsView()).toBe('icon')
  })

  it('falls back rather than throwing on a value it does not recognise', () => {
    // A hand-edited localStorage value reaches the renderer directly. One that
    // is not a view mode must not be able to take the page down, which is the
    // same reason isStoreSort exists in lib/store-order.ts.
    localStorage.setItem('pp_apps_view', 'toString')
    expect(readAppsView()).toBe('detailed')
    localStorage.setItem('pp_apps_view', '{"not":"a view"}')
    expect(readAppsView()).toBe('detailed')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run --no-file-parallelism src/tests/apps-view.test.ts`
Expected: FAIL, cannot resolve `../lib/apps-view`.

- [ ] **Step 3: Write the module**

Create `frontend/src/lib/apps-view.ts`:

```ts
import { useCallback, useState } from 'react'

/**
 * Which of the three presentations the Apps section draws.
 *
 * Stored per browser in localStorage, the same way lib/console-prefs.ts
 * stores the console theme and font size. A view mode is a per-operator
 * habit, not a per-visit one: someone who wants the dense icon grid wants it
 * every time they open the page, and re-choosing it on every navigation is
 * the kind of small friction that makes the other two views not worth having.
 */
const KEY = 'pp_apps_view'

export const APPS_VIEWS = {
  detailed: { label: 'Detailed view', icon: 'grid_view' },
  list: { label: 'List view', icon: 'view_list' },
  icon: { label: 'Icon view', icon: 'apps' },
} as const

export type AppsView = keyof typeof APPS_VIEWS

export const DEFAULT_APPS_VIEW: AppsView = 'detailed'

/** Own keys only. `'toString' in APPS_VIEWS` is true, because `in` walks the
 *  prototype chain, so the obvious version of this accepts a stored
 *  "toString" and hands the renderer a key the table does not have. A
 *  hand-edited localStorage value must not be able to do that; same guard as
 *  isStoreSort in lib/store-order.ts. */
export function isAppsView(v: unknown): v is AppsView {
  return typeof v === 'string' && Object.hasOwn(APPS_VIEWS, v)
}

export function readAppsView(): AppsView {
  try {
    const v = localStorage.getItem(KEY)
    return isAppsView(v) ? v : DEFAULT_APPS_VIEW
  } catch {
    // Private-mode Safari throws on localStorage access rather than returning
    // null. A view mode is not worth a blank page.
    return DEFAULT_APPS_VIEW
  }
}

export function writeAppsView(view: AppsView): void {
  try { localStorage.setItem(KEY, view) } catch { /* see readAppsView */ }
}

export function useAppsView(): [AppsView, (v: AppsView) => void] {
  const [view, setView] = useState<AppsView>(readAppsView)
  const choose = useCallback((v: AppsView) => { writeAppsView(v); setView(v) }, [])
  return [view, choose]
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run --no-file-parallelism src/tests/apps-view.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Write the failing switch test**

Create `frontend/src/tests/apps-view-switch.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../components/ui/icon', () => ({
  Icon: ({ name }: { name: string }) => <span data-icon={name} />,
}))

import { AppsViewSwitch } from '../components/AppsViewSwitch'

describe('AppsViewSwitch', () => {
  it('names each view, so the icon-only buttons are reachable without sight', () => {
    render(<AppsViewSwitch value="detailed" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Detailed view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'List view' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Icon view' })).toBeInTheDocument()
  })

  it('marks the current view pressed rather than only styling it', () => {
    render(<AppsViewSwitch value="list" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'List view' }))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Icon view' }))
      .toHaveAttribute('aria-pressed', 'false')
  })

  it('reports the chosen view', async () => {
    const onChange = vi.fn()
    render(<AppsViewSwitch value="detailed" onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'Icon view' }))
    expect(onChange).toHaveBeenCalledWith('icon')
  })
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npx vitest run --no-file-parallelism src/tests/apps-view-switch.test.tsx`
Expected: FAIL, cannot resolve `../components/AppsViewSwitch`.

- [ ] **Step 7: Write the switch**

Create `frontend/src/components/AppsViewSwitch.tsx`:

```tsx
import { Fragment } from 'react'
import { APPS_VIEWS, type AppsView } from '../lib/apps-view'
import { Button } from './ui/button'
import { ButtonGroup, ButtonGroupSeparator } from './ui/button-group'
import { Icon } from './ui/icon'

const ORDER: AppsView[] = ['detailed', 'list', 'icon']

/**
 * Which presentation the Apps section draws, as three welded icon buttons.
 *
 * aria-pressed rather than colour alone: these are icon-only toggles, and
 * which one is active has to be readable to a screen reader and to anyone who
 * cannot pick the active tint out of three otherwise identical buttons.
 */
export function AppsViewSwitch({ value, onChange }: {
  value: AppsView
  onChange: (v: AppsView) => void
}) {
  return (
    <ButtonGroup>
      {ORDER.map((v, i) => (
        // An explicit keyed Fragment, not `<>`: the shorthand takes no key,
        // and a keyless child in a map is a React warning that oxlint fails on.
        <Fragment key={v}>
          {i > 0 && <ButtonGroupSeparator />}
          <Button size="icon-xs"
            variant={v === value ? 'go' : 'ghost'}
            aria-pressed={v === value}
            aria-label={APPS_VIEWS[v].label}
            title={APPS_VIEWS[v].label}
            onClick={() => onChange(v)}>
            <Icon name={APPS_VIEWS[v].icon} size={16} />
          </Button>
        </Fragment>
      ))}
    </ButtonGroup>
  )
}
```

`APPS_VIEWS[v].icon` is a variable reference, which the icon-name extractor deliberately does not follow. It does not need to: the names are literals in `apps-view.ts`'s `icon:` fields, which is the third shape the extractor reads. Step 10 verifies this.

- [ ] **Step 8: Run the test to verify it passes**

Run: `npx vitest run --no-file-parallelism src/tests/apps-view-switch.test.tsx`
Expected: PASS, 3 tests.

- [ ] **Step 9: Wire it into the Hosts page**

In `frontend/src/routes/hosts.tsx`, in the Apps section: add `const [appsView, setAppsView] = useAppsView()` to the component that renders it, put `<AppsViewSwitch value={appsView} onChange={setAppsView} />` in the header row before `<UpdateAllButton />`, and switch all three of the loading placeholder and the body on `appsView`.

```tsx
        <QueryState query={appsQuery}
                    loading={appsView === 'detailed'
                      ? <SkeletonGroup label="Loading apps" className={appGrid}>
                          {Array.from({ length: 4 }, (_, i) => <AppCardSkeleton key={i} />)}
                        </SkeletonGroup>
                      : appsView === 'list'
                        ? <SkeletonGroup label="Loading apps"><AppTableSkeleton rows={4} /></SkeletonGroup>
                        : <SkeletonGroup label="Loading apps"><AppIconGridSkeleton count={8} /></SkeletonGroup>}
                    emptyTitle="No apps yet"
                    emptyNote="Installed or adopted apps appear here. Install one from the App Store, or adopt a container Proxploy already found."
                    errorTitle="Apps not readable"
                    errorNote="Proxploy could not reach the backend to list your apps.">
          {(rows) => {
            // The same eight apps in every view: the switch changes how the
            // set is drawn, never which apps are in it.
            const shown = rows.slice(0, 8)
            if (appsView === 'list') return <AppTable apps={shown} />
            if (appsView === 'icon') return <AppIconGrid apps={shown} />
            return (
              <div className={appGrid}>
                {shown.map((a) => <AppCard key={a.id} app={a} />)}
              </div>
            )
          }}
        </QueryState>
```

- [ ] **Step 10: Write the wiring test**

Append to `frontend/src/tests/hosts.test.tsx`, following that file's existing mock setup rather than introducing a new one. Read its top section first, then:

```tsx
  it('switches the Apps section between the three views and remembers the choice', async () => {
    const user = userEvent.setup()
    localStorage.clear()
    const view = renderHostsPage()   // whatever this file's existing helper is called

    // Detailed by default: the card's meters are present.
    expect(await screen.findByText(/CPU/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'List view' }))
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(localStorage.getItem('pp_apps_view')).toBe('list')

    await user.click(screen.getByRole('button', { name: 'Icon view' }))
    expect(screen.queryByRole('table')).toBeNull()
    expect(localStorage.getItem('pp_apps_view')).toBe('icon')

    // A remount reads the stored choice rather than resetting to detailed.
    view.unmount()
    renderHostsPage()
    await waitFor(() => expect(screen.queryByRole('table')).toBeNull())
  })
```

- [ ] **Step 11: Run the whole frontend suite**

Run: `npx vitest run --no-file-parallelism`
Expected: PASS, every test. The pre-existing `hosts.test.tsx` assertions about the Apps section must still pass without edits, since detailed is the default and nothing about it changed.

- [ ] **Step 12: Verify the icon names one more time**

Run: `npx vitest run --no-file-parallelism src/tests/icon-names-coverage.test.tsx`
Expected: PASS. `grid_view`, `view_list` and `apps` are new here and reach the extractor through `apps-view.ts`'s `icon:` fields.

- [ ] **Step 13: Look at all three views in the real app**

```bash
node e2e/driver.mjs shot /tmp/pp-detailed.png /hosts
```

Then switch to list and to icon in the browser and shoot each. Open all three PNGs. Confirm: the switcher reads as one control, the table scrolls sideways rather than pushing the page wide, and the icon grid's state line is legible against the panel in both themes. A blank frame means the dev server is down, not a pass.

- [ ] **Step 14: Typecheck, lint, commit**

Run: `npx tsc -b && npx oxlint`

```bash
git add frontend/src/lib/apps-view.ts frontend/src/components/AppsViewSwitch.tsx \
        frontend/src/routes/hosts.tsx frontend/src/tests/apps-view.test.ts \
        frontend/src/tests/apps-view-switch.test.tsx frontend/src/tests/hosts.test.tsx
git commit -m "feat(hosts): switch the Apps section between three views

The choice persists per browser, and an unrecognised stored value falls
back to detailed rather than reaching the renderer."
```

---

### Task 9: Full verification

**Files:** none.

- [ ] **Step 1: Backend suite**

Run, from `backend/`: `.venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS. `tests/test_lifecycle_jobs.py` has a known timing-dependent flake unrelated to this work; if it fails, re-run that file alone to confirm it is the flake and not a regression.

- [ ] **Step 2: Frontend suite, types, lint**

Run, from `frontend/`: `npx vitest run --no-file-parallelism && npx tsc -b && npx oxlint`
Expected: PASS, clean, clean.

- [ ] **Step 3: Geometry harness**

Run, from `frontend/`: `npm run harness`
Expected: PASS.

- [ ] **Step 4: End-to-end journey**

The Playwright suite spawns its own backend and frontend, so stop the dev servers first or it refuses to start with `meta/health is already used`.

```bash
lsof -ti :8000 | xargs -r kill
lsof -ti :5173 | xargs -r kill
cd frontend && npx playwright test journey.spec.ts
```

Expected: PASS. Restart the dev servers afterwards if the session continues.

- [ ] **Step 5: Confirm the rate against a real container**

The unit tests prove the arithmetic; only a real cluster proves PVE returns what the code assumes. With the dev servers up and a host connected, wait two poll cycles (about a minute) and check a running app:

```bash
cd backend && .venv/bin/python -c "
from proxploy.db import SessionLocal
from proxploy.models import App
db = SessionLocal()
for a in db.query(App).all():
    print(a.name, a.status_cached, a.disk_bytes_cached, a.disk_total_bytes_cached,
          a.net_in_bps_cached, a.net_out_bps_cached, a.net_sampled_at)
"
```

Adjust the session import to match this repo's actual db module. Expected: a running app shows non-null storage and, after the second cycle, non-null rates that are plausible (a mostly idle container is single-digit kB/s, not megabytes). Rates that are wildly large point at an elapsed-time bug; rates stuck at null past the second cycle point at `net_sampled_at` never being written.

- [ ] **Step 6: Report**

State plainly which suites ran and what they returned, including anything skipped or still failing. Do not claim completion for a step that did not run.
