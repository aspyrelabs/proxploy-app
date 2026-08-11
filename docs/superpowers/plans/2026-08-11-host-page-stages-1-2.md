# Host Page, Stages 1 and 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the host page an Overview worth opening (processor, cores, load,
IO delay, kernel, memory, storage) and a Hardware tab (disks with health and
wearout, PCI, boot state), both from the Proxmox API, plus a button to the
Proxmox web UI.

**Architecture:** Two new read-only endpoints scoped to a host + node, backed by
two new `ProxmoxClient` methods. Both are fetched **on demand** when the page
opens, never from the poll loop. The page gains tab routes matching the
existing app/VM detail pattern.

**Tech Stack:** FastAPI, proxmoxer, SQLAlchemy; React 19, TanStack Router +
Query, Tailwind v4, Vitest, pytest.

Spec: `docs/superpowers/specs/2026-08-11-host-page-design.md`

## Global Constraints

- **On demand, never polled.** Doc 02 §3 caps a poll cycle at O(nodes); these
  add zero calls to it.
- **Colours from tokens**, never hex, in any new component
  (`src/tests/no-hardcoded-colors.test.ts`).
- **Vitest runs from `frontend/`** with `--no-file-parallelism`. From the repo
  root every test fails with `document is not defined`.
- **Never touch ports 8000/5173, never run Playwright** — the user is running
  the app.
- **Fixtures come from the real probe** recorded in the spec's field table, not
  invented shapes.
- A node that refuses `/nodes/{n}/status` (403 on a narrower token) must
  degrade to a page without the strip, never an error page.

---

## File Structure

| File | Responsibility |
|---|---|
| Modify `backend/proxploy/services/proxmox.py` | `node_status()`, `node_disks()` client methods |
| Modify `backend/proxploy/api/hosts.py` | `GET /hosts/{id}/nodes/{node}/status` and `/hardware` |
| Create `backend/tests/fixtures/pve/node_status.json` | Real captured payload |
| Create `backend/tests/test_host_node_status.py` | Endpoint + normalisation tests |
| Create `frontend/src/components/HostFacts.tsx` | The Overview KV strip + health bars |
| Create `frontend/src/components/HardwareTab.tsx` | Disks, PCI, boot state |
| Modify `frontend/src/routes/hosts.tsx` | Tab routes, web-UI button, mount both |
| Modify `frontend/src/router.tsx` | Register the child routes |
| Create `frontend/src/tests/host-facts.test.tsx` | Rendering + load normalisation |

---

### Task 1: Client methods

**Files:**
- Modify: `backend/proxploy/services/proxmox.py`
- Test: `backend/tests/test_proxmox.py`

**Interfaces:**
- Produces: `ProxmoxClient.node_status(node: str) -> dict` and
  `ProxmoxClient.node_disks(node: str) -> list[dict]`, both raising
  `ProxmoxError` on failure like every other method here.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_proxmox.py`, following the shape of the existing
`test_node_rrddata_passes_timeframe`:

```python
def test_node_status_returns_the_node_payload():
    from tests.fakes.pve import FakePVE
    fake = FakePVE()
    fake.node_status_by_node = {"pve1": {"uptime": 25029, "cpuinfo": {"cores": 14}}}
    c = _client(fake)          # same helper the other tests in this file use
    assert c.node_status("pve1")["uptime"] == 25029


def test_node_status_wraps_errors_as_proxmox_error():
    from proxploy.services.proxmox import ProxmoxError
    from tests.fakes.pve import FakePVE
    c = _client(FakePVE(fail=True))
    with pytest.raises(ProxmoxError):
        c.node_status("pve1")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_proxmox.py -q`
Expected: FAIL, `AttributeError: 'ProxmoxClient' object has no attribute 'node_status'`.

- [ ] **Step 3: Extend FakePVE**

`backend/tests/fakes/pve.py` — the node namespace already serves `rrddata`
(`_KwLeaf`) and `tasks`. Add `status` and `disks/list` leaves alongside them,
reading lazily from instance attributes so a test can assign after
construction, exactly as `_AttrLeaf` already does for other fields:

```python
# on FakePVE.__init__
self.node_status_by_node: dict[str, dict] = {}
self.disks_by_node: dict[str, list[dict]] = {}
```

and in the per-node object, beside `self.rrddata = _KwLeaf(...)`:

```python
self.status = _Leaf(owner.node_status_by_node.get(name, {}), owner.fail)
self.disks = _Disks(owner.disks_by_node.get(name, []), owner.fail)
```

where `_Disks` is a tiny holder exposing `.list` as a `_Leaf`, because the PVE
path is `/nodes/{n}/disks/list`.

- [ ] **Step 4: Write the client methods**

```python
    def node_status(self, node: str) -> dict:
        """GET /nodes/{node}/status: the node's own view of itself.

        Carries cpuinfo (model, sockets, cores, cpus), loadavg, wait (IO
        delay), kversion, boot-info, memory/swap/rootfs. Called when a human
        opens the host page, never from the poll loop: doc 02 §3 caps a cycle
        at O(nodes) and almost everything here is static.
        """
        try:
            return self._connect().nodes(node).status.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"node status failed for node {node!r}", e) from e

    def node_disks(self, node: str) -> list[dict]:
        """GET /nodes/{node}/disks/list: model, serial, size, health, wearout."""
        try:
            return self._connect().nodes(node).disks.list.get()
        except ProxmoxError:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._wrap(f"disk list failed for node {node!r}", e) from e
```

- [ ] **Step 5: Run to green**

Run: `cd backend && .venv/bin/python -m pytest tests/test_proxmox.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/services/proxmox.py backend/tests/
git commit -m "feat(proxmox): read node status and disk inventory"
```

---

### Task 2: The endpoints

**Files:**
- Modify: `backend/proxploy/api/hosts.py`
- Create: `backend/tests/fixtures/pve/node_status.json`
- Create: `backend/tests/test_host_node_status.py`

**Interfaces:**
- Consumes: `node_status()`, `node_disks()` from Task 1;
  `client_for_host(app, db, host)` from `proxploy.services.hostclient`, used the
  same way `api/consoles.py:44` uses it.
- Produces: `GET /hosts/{host_id}/nodes/{node}/status` and
  `GET /hosts/{host_id}/nodes/{node}/hardware`, both `_read`-authorised.

- [ ] **Step 1: Capture the fixture**

Create `backend/tests/fixtures/pve/node_status.json` with the real payload
shape recorded in the spec (values from node1):

```json
{
  "uptime": 25029,
  "wait": 0.000273693493697447,
  "loadavg": ["0.00", "0.00", "0.00"],
  "kversion": "Linux 7.0.14-11-pve #1 SMP PREEMPT_DYNAMIC PMX 7.0.14-11",
  "current-kernel": {"release": "7.0.14-11-pve", "machine": "x86_64",
                     "sysname": "Linux"},
  "pveversion": "pve-manager/9.2.10/43df2e01f27a1a19",
  "boot-info": {"mode": "efi", "secureboot": 0},
  "ksm": {"shared": 0},
  "cpuinfo": {"model": "13th Gen Intel(R) Core(TM) i5-13500T",
              "vendor": "GenuineIntel", "cores": 14, "cpus": 20,
              "sockets": 1, "mhz": "800.000", "family": "6"},
  "memory": {"total": 33306869760, "used": 2161287168, "free": 31086596096},
  "swap": {"total": 8589930496, "used": 0, "free": 8589930496},
  "rootfs": {"total": 100861726720, "used": 6425862144, "avail": 89265127424}
}
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_host_node_status.py
"""The host page's own reads. On demand, never from the poll loop."""
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "pve"


def _app(tmp_path, status=None, disks=None, fail=False):
    from fastapi.testclient import TestClient
    from tests.fakes.pve import FakePVE
    from tests.support import make_app, seed_host_row

    fake = FakePVE(fail=fail)
    fake.node_status_by_node = {"pve1": status or {}}
    fake.disks_by_node = {"pve1": disks or []}
    app = make_app(tmp_path, fake=fake)
    c = TestClient(app)
    c.__enter__()
    with app.state.sessionmaker() as db:
        h = seed_host_row(db)
        h.node_name = "pve1"
        db.commit()
        return app, c, h.id


def test_status_normalises_the_node_payload(tmp_path, bootstrap_admin):
    raw = json.loads((FIX / "node_status.json").read_text())
    app, c, hid = _app(tmp_path, status=raw)
    bootstrap_admin(c)
    body = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status").json()

    assert body["cpu"]["model"] == "13th Gen Intel(R) Core(TM) i5-13500T"
    # Physical vs logical is the distinction an operator actually wants.
    assert body["cpu"]["cores"] == 14
    assert body["cpu"]["threads"] == 20
    assert body["cpu"]["sockets"] == 1
    assert body["kernel"] == "7.0.14-11-pve"
    assert body["boot_mode"] == "efi"
    assert body["io_delay"] == raw["wait"]
    assert body["load"] == [0.0, 0.0, 0.0]
    assert body["memory"]["total"] == 33306869760
    assert body["uptime_s"] == 25029


def test_status_from_a_token_that_cannot_read_it_is_502_not_500(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path, fail=True)
    bootstrap_admin(c)
    r = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/status")
    # The page must be able to tell "node did not answer" from "app broke".
    assert r.status_code == 502, r.text


def test_hardware_lists_disks_with_health_and_wearout(tmp_path, bootstrap_admin):
    disks = [{"devpath": "/dev/nvme0n1", "model": "WD Green SN350 2TB",
              "serial": "22303K800007", "size": 2000398934016, "type": "nvme",
              "health": "PASSED", "wearout": 99, "osdid": -1}]
    app, c, hid = _app(tmp_path, disks=disks)
    bootstrap_admin(c)
    body = c.get(f"/api/v1/hosts/{hid}/nodes/pve1/hardware").json()
    d = body["disks"][0]
    assert d["model"] == "WD Green SN350 2TB"
    assert d["health"] == "PASSED"
    assert d["wearout"] == 99
    # -1 is PVE's "not an OSD"; surfacing it raw would read as a real id.
    assert d["osd_id"] is None


def test_an_unknown_host_is_404(tmp_path, bootstrap_admin):
    app, c, hid = _app(tmp_path)
    bootstrap_admin(c)
    assert c.get("/api/v1/hosts/9999/nodes/pve1/status").status_code == 404
```

- [ ] **Step 3: Run and watch them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_host_node_status.py -q`
Expected: FAIL with 404s, the routes do not exist.

- [ ] **Step 4: Implement the endpoints**

In `backend/proxploy/api/hosts.py`:

```python
def _load(raw: list) -> list[float]:
    # PVE sends loadavg as strings.
    out = []
    for v in (raw or [])[:3]:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


@router.get("/{host_id}/nodes/{node}/status")
def node_status(host_id: int, node: str, request: Request, db=Depends(get_db),
                user: User = Depends(_read)):
    """The node's own view of itself, for the host page.

    On demand, never from the poll loop: doc 02 §3 caps a cycle at O(nodes),
    and model/cores/kernel/boot mode do not change between polls. The
    volatile figures here (load, wait, memory) are already recorded as metric
    samples every 30s.
    """
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "no such host")
    try:
        s = client_for_host(request.app, db, h).node_status(node)
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)}) from e

    cpu = s.get("cpuinfo") or {}
    return {
        "node": node,
        "uptime_s": s.get("uptime"),
        "pve_version": s.get("pveversion"),
        "kernel": (s.get("current-kernel") or {}).get("release") or s.get("kversion"),
        "arch": (s.get("current-kernel") or {}).get("machine"),
        "boot_mode": (s.get("boot-info") or {}).get("mode"),
        "secure_boot": bool((s.get("boot-info") or {}).get("secureboot")),
        "cpu": {"model": cpu.get("model"), "vendor": cpu.get("vendor"),
                "sockets": cpu.get("sockets"), "cores": cpu.get("cores"),
                # PVE's `cpus` is logical processors; naming it `threads`
                # here so the UI never has to guess which number is which.
                "threads": cpu.get("cpus"), "mhz": cpu.get("mhz")},
        "load": _load(s.get("loadavg")),
        "io_delay": s.get("wait"),
        "memory": s.get("memory") or {},
        "swap": s.get("swap") or {},
        "rootfs": s.get("rootfs") or {},
        "ksm_shared": (s.get("ksm") or {}).get("shared"),
    }


@router.get("/{host_id}/nodes/{node}/hardware")
def node_hardware(host_id: int, node: str, request: Request, db=Depends(get_db),
                  user: User = Depends(_read)):
    h = db.get(Host, host_id)
    if h is None:
        raise HTTPException(404, "no such host")
    try:
        disks = client_for_host(request.app, db, h).node_disks(node)
    except ProxmoxError as e:
        raise HTTPException(502, {"error": e.kind, "detail": str(e)}) from e
    return {"disks": [{
        "devpath": d.get("devpath"), "model": d.get("model"),
        "serial": d.get("serial"), "size": d.get("size"), "type": d.get("type"),
        "health": d.get("health"), "wearout": d.get("wearout"),
        "used": d.get("used"),
        # PVE uses -1 for "not a Ceph OSD"; passing that through would read
        # as OSD number minus one.
        "osd_id": None if (d.get("osdid") in (None, -1)) else d.get("osdid"),
    } for d in disks]}
```

Add the import at the top of the file:

```python
from proxploy.services.hostclient import client_for_host
```

- [ ] **Step 5: Run to green, then the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_host_node_status.py -q`
Expected: PASS, 4 tests.
Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/proxploy/api/hosts.py backend/tests/
git commit -m "feat(hosts): serve node status and hardware for the host page"
```

---

### Task 3: The Overview strip

**Files:**
- Create: `frontend/src/components/HostFacts.tsx`
- Create: `frontend/src/tests/host-facts.test.tsx`

**Interfaces:**
- Consumes: `GET /hosts/{id}/nodes/{node}/status` from Task 2.
- Produces: `export function HostFacts({ hostId, node }: { hostId: number; node: string })`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/tests/host-facts.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

let status: unknown = {
  node: 'pve1', uptime_s: 25029, pve_version: 'pve-manager/9.2.10',
  kernel: '7.0.14-11-pve', arch: 'x86_64', boot_mode: 'efi', secure_boot: false,
  cpu: { model: '13th Gen Intel(R) Core(TM) i5-13500T', vendor: 'GenuineIntel',
         sockets: 1, cores: 14, threads: 20, mhz: '800.000' },
  load: [2.0, 1.0, 0.5], io_delay: 0.00027,
  memory: { total: 33306869760, used: 2161287168 },
  swap: { total: 8589930496, used: 0 },
  rootfs: { total: 100861726720, used: 6425862144 },
}

vi.mock('../api/client', () => ({
  api: vi.fn(() => Promise.resolve(status)),
  ApiError: class extends Error {},
}))

import { HostFacts } from '../components/HostFacts'

const wrap = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><HostFacts hostId={1} node="pve1" /></QueryClientProvider>)
}

describe('HostFacts', () => {
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
})
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npx vitest run src/tests/host-facts.test.tsx --no-file-parallelism`
Expected: FAIL, cannot resolve `../components/HostFacts`.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/HostFacts.tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { fmtBytes, fmtUptime } from '../lib/format'
import { KVGrid } from './KVGrid'
import { CPU_GRADIENT, RAM_GRADIENT, UsageBar } from './UsageBar'

type Status = {
  node: string; uptime_s: number | null; pve_version: string | null
  kernel: string | null; arch: string | null
  boot_mode: string | null; secure_boot: boolean
  cpu: { model: string | null; vendor: string | null; sockets: number | null
         cores: number | null; threads: number | null; mhz: string | null }
  load: number[]; io_delay: number | null
  memory: { total?: number; used?: number }
  swap: { total?: number; used?: number }
  rootfs: { total?: number; used?: number }
}

const pct = (used?: number, total?: number) =>
  total ? Math.round((used ?? 0) / total * 1000) / 10 : 0

export function HostFacts({ hostId, node }: { hostId: number; node: string }) {
  const q = useQuery({
    queryKey: ['host', hostId, 'node', node, 'status'],
    queryFn: () => api<Status>(`/hosts/${hostId}/nodes/${node}/status`),
  })
  // A token too narrow to read /nodes/{n}/status must cost the strip, not the
  // page: everything else here already rendered from the poller's snapshot.
  if (!q.data) return null
  const s = q.data
  const threads = s.cpu.threads || 1
  // Load normalised by thread count. A raw 14 means nothing without knowing
  // the box has 20 threads; the raw triple stays beside it because the
  // normalised number alone hides the trend.
  const loadPct = Math.round((s.load[0] ?? 0) / threads * 1000) / 10

  return (
    <div className="space-y-5">
      <KVGrid items={[
        ['Node', s.node],
        ['PVE version', s.pve_version?.split('/')[1] ?? '—'],
        ['Kernel', s.kernel ?? '—'],
        ['Architecture', s.arch ?? '—'],
        ['Uptime', s.uptime_s != null ? fmtUptime(s.uptime_s) : '—'],
        ['Processor', s.cpu.model ?? '—'],
        ['Cores', `${s.cpu.cores ?? '?'} physical · ${s.cpu.threads ?? '?'} logical`],
        ['Sockets', String(s.cpu.sockets ?? '—')],
        ['Load (1 · 5 · 15)', s.load.map(n => n.toFixed(2)).join(' · ')],
        ['IO delay', s.io_delay != null ? `${(s.io_delay * 100).toFixed(2)}%` : '—'],
        ['Memory', `${fmtBytes(s.memory.used ?? 0)} / ${fmtBytes(s.memory.total ?? 0)}`],
        ['Storage', `${fmtBytes(s.rootfs.used ?? 0)} / ${fmtBytes(s.rootfs.total ?? 0)}`],
        ['Swap', `${fmtBytes(s.swap.used ?? 0)} / ${fmtBytes(s.swap.total ?? 0)}`],
        ['Boot', `${s.boot_mode ?? '—'}${s.secure_boot ? ' · secure boot' : ''}`],
      ]} />

      <div className="space-y-2">
        <Bar label="LOAD" pct={loadPct} gradient={CPU_GRADIENT} />
        <Bar label="RAM" pct={pct(s.memory.used, s.memory.total)} gradient={RAM_GRADIENT} />
        <Bar label="ROOT" pct={pct(s.rootfs.used, s.rootfs.total)} gradient={RAM_GRADIENT} />
      </div>
    </div>
  )
}

function Bar({ label, pct, gradient }: { label: string; pct: number; gradient: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 text-[10.5px] uppercase text-text-3">{label}</span>
      <div className="flex-1"><UsageBar pct={pct} gradient={gradient} /></div>
      <span className="w-12 text-right font-mono text-[11px] text-text-2">{pct}%</span>
    </div>
  )
}
```

Check `frontend/src/lib/format.ts` for the exact byte formatter name before
writing this; if it is not `fmtBytes`, use whatever the Memory KV entry on the
existing host page already uses, so the two read identically.

- [ ] **Step 4: Run to green**

Run: `cd frontend && npx vitest run src/tests/host-facts.test.tsx --no-file-parallelism`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HostFacts.tsx frontend/src/tests/host-facts.test.tsx
git commit -m "feat(hosts): an overview strip that says what the node is"
```

---

### Task 4: Hardware tab, tabs, and the web UI button

**Files:**
- Create: `frontend/src/components/HardwareTab.tsx`
- Modify: `frontend/src/routes/hosts.tsx`, `frontend/src/router.tsx`
- Modify: `frontend/src/tests/hosts.test.tsx`

**Interfaces:**
- Consumes: `HostFacts` from Task 3, `GET .../hardware` from Task 2.
- Produces: `hostOverviewRoute` and `hostHardwareRoute` as children of the
  existing node detail route, mirroring `appOverviewRoute`'s shape
  (`getParentRoute: () => nodeDetailRoute, path: '/'`).

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/tests/hosts.test.tsx`:

```tsx
  it('links out to the Proxmox web UI, safely', async () => {
    // ...render the node detail page with a host whose address is known
    const link = await screen.findByRole('link', { name: /proxmox web ui/i })
    expect(link).toHaveAttribute('target', '_blank')
    // Without noopener the opened page can navigate this one via window.opener.
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('lists disks with health and wearout', async () => {
    // ...render the hardware tab
    expect(await screen.findByText('WD Green SN350 2TB')).toBeInTheDocument()
    expect(screen.getByText('PASSED')).toBeInTheDocument()
    expect(screen.getByText(/99%/)).toBeInTheDocument()
  })
```

Match the existing mocking style in that file rather than inventing a new one;
it already mocks `../api/client`.

- [ ] **Step 2: Run and watch them fail**

Run: `cd frontend && npx vitest run src/tests/hosts.test.tsx --no-file-parallelism`

- [ ] **Step 3: Implement the hardware tab**

```tsx
// frontend/src/components/HardwareTab.tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { fmtBytes } from '../lib/format'

type Disk = {
  devpath: string; model: string | null; serial: string | null
  size: number | null; type: string | null; health: string | null
  wearout: number | null; used: string | null; osd_id: number | null
}

export function HardwareTab({ hostId, node }: { hostId: number; node: string }) {
  const q = useQuery({
    queryKey: ['host', hostId, 'node', node, 'hardware'],
    queryFn: () => api<{ disks: Disk[] }>(`/hosts/${hostId}/nodes/${node}/hardware`),
  })
  if (!q.data) return null
  return (
    <section className="rounded-card border border-line-soft bg-panel p-5">
      <h2 className="mb-3 font-display text-[15px] font-semibold">Disks</h2>
      <table className="w-full text-left text-[13px]">
        <thead><tr className="text-[10.5px] uppercase tracking-wide text-text-3">
          <th className="pb-2 font-normal">Device</th>
          <th className="pb-2 font-normal">Model</th>
          <th className="pb-2 font-normal">Size</th>
          <th className="pb-2 font-normal">Type</th>
          <th className="pb-2 font-normal">Health</th>
          <th className="pb-2 font-normal">Wearout</th>
        </tr></thead>
        <tbody>
          {q.data.disks.map(d => (
            <tr key={d.devpath} className="border-t border-line-soft align-middle">
              <td className="py-2 font-mono">{d.devpath}</td>
              <td className="py-2 text-text-2">{d.model ?? '—'}</td>
              <td className="py-2 font-mono">{d.size ? fmtBytes(d.size) : '—'}</td>
              <td className="py-2 text-text-2">{d.type ?? '—'}</td>
              <td className={`py-2 ${d.health === 'PASSED' ? 'text-green' : 'text-amber'}`}>
                {d.health ?? 'unknown'}
              </td>
              {/* PVE reports wearout as remaining life, not consumed. 99 is a
                  nearly-new disk, so labelling it "used" would invert it. */}
              <td className="py-2 font-mono">{d.wearout != null ? `${d.wearout}% left` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
```

- [ ] **Step 4: Add the tabs and the button**

In `routes/hosts.tsx`, give `NodeDetailPage` a tab strip and an `<Outlet />`,
following how `apps.tsx` renders its detail tabs. Beside the heading:

```tsx
<a href={hostAddress} target="_blank" rel="noopener noreferrer"
   className="rounded-ctl border border-line px-2.5 py-1 text-[12px] text-text-2
              transition hover:border-amber hover:text-amber">
  Open Proxmox web UI ↗
</a>
```

`hostAddress` comes from the host detail query already on this page. Export
`hostOverviewRoute` (path `/`, renders `HostFacts`) and `hostHardwareRoute`
(path `/hardware`, renders `HardwareTab`), then register them in `router.tsx`:

```tsx
const nodeDetailTree = nodeDetailRoute.addChildren([hostOverviewRoute, hostHardwareRoute])
```

and use `nodeDetailTree` in place of `nodeDetailRoute` in `shellRoute.addChildren`.

- [ ] **Step 5: Run the full suites**

Run: `cd frontend && npx vitest run --no-file-parallelism && npx tsc -b && npx oxlint`
Run: `cd backend && .venv/bin/python -m pytest tests/ -q -m "not pve_integration and not e2e"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src backend
git commit -m "feat(hosts): hardware tab, host page tabs, and a link to the Proxmox UI"
```

---

## Self-Review

**Spec coverage.** Stage 1 Overview → Tasks 1–3 (endpoint, normalisation, strip,
load normalisation, on-demand fetch). Stage 2 Hardware → Tasks 2 and 4 (disks
with health and wearout). Web UI button → Task 4. Stages 3–5 are explicitly out
of this plan and unaffected.

**Placeholders.** None. Two steps name a check to perform before writing
(the byte formatter's real name, the existing test file's mocking style) rather
than guessing at an identifier this plan cannot see.

**Type consistency.** `Status` in Task 3 matches the endpoint payload built in
Task 2 field for field, including `cpu.threads` being PVE's `cpus`. `Disk` in
Task 4 matches the hardware endpoint, including `osd_id` being `null` rather
than `-1`.
