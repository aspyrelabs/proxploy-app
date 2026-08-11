# The host page: what a node actually is

**Date:** 2026-08-11
**Status:** approved. Stages 1 and 2 build now; 3 to 5 follow.
**Scope:** the per-host page (`/hosts/$hostId/$node`), its backing endpoints,
and one new SSH collector in stage 3.

## Problem

The host page shows Node, PVE version, Uptime, Memory, Apps and VMs. That is a
fraction of what the node knows about itself, and none of what an operator
looks at when deciding whether a box is healthy: processor, cores, load, IO
delay, kernel, disks, temperatures. There is also no link to the Proxmox web
UI, so the one thing an operator always ends up wanting is a copy-paste of the
address away.

## What Proxmox actually exposes

Probed against a real PVE 9.2.10 node (`node1`, 13th Gen i5-13500T) with the
enrolled monitoring token, rather than taken from documentation.

**`GET /nodes/{node}/status` — one call, and it carries most of this page:**

| Field | Example |
|---|---|
| `uptime` | `25029` |
| `cpuinfo.model` | `13th Gen Intel(R) Core(TM) i5-13500T` |
| `cpuinfo.cores` / `.cpus` / `.sockets` | `14` / `20` / `1` |
| `cpuinfo.vendor` / `.family` / `.mhz` | `GenuineIntel` / `6` / `800.000` |
| `loadavg` | `["0.00","0.00","0.00"]` |
| `wait` | `0.000273` (IO delay) |
| `kversion`, `current-kernel` | `Linux 7.0.14-11-pve`, `x86_64` |
| `memory` | `total`/`used`/`free`/`available` bytes |
| `swap`, `rootfs` | totals and usage in bytes |
| `boot-info` | `{"mode":"efi","secureboot":0}` |
| `ksm.shared` | `0` |
| `pveversion` | `pve-manager/9.2.10/…` |

**Other endpoints that answered:** `/nodes/{n}/disks/list` (model, serial,
size, `health: PASSED`, `wearout: 99`, type, `osdid`), `/nodes/{n}/hardware/pci`
(11 devices), `/nodes/{n}/services` (23, with state), `/nodes/{n}/subscription`,
`/nodes/{n}/dns`, `/nodes/{n}/time` (timezone), `/cluster/status`.

**Not exposed by the API at all:** system model, motherboard version, CPU
temperature, motherboard temperature, network port speed.
`/nodes/{n}/network` returns `iface`/`type`/`method`/`active` and no speed.
Proxmox has no temperature endpoint; its own web UI does not show temperatures
either. These five need shell commands, which is stage 3.

**Ceph:** every Ceph endpoint answers
`500 binary not installed: /usr/bin/ceph-mon` on this node. The section must
detect that and disappear, not error.

## Design

The host page gains tabs, matching the pattern apps and VMs already use
(`appDetailRoute` / `vmDetailRoute` children):

**Overview · Metrics · Hardware · Ceph**, with Ceph rendered only when detected.

Beside the host name, an **Open Proxmox web UI** button linking to the stored
address, `target="_blank" rel="noopener noreferrer"`.

### Stage 1 — Overview, API only

New endpoint `GET /hosts/{host_id}/nodes/{node}/status`, returning a normalised
subset of the PVE payload: identity (node, pve version, kernel, boot mode,
subscription), processor (model, vendor, sockets, cores, threads, mhz), load
(1/5/15 plus core count), io delay, and memory/swap/rootfs byte triples.

The page renders a KV strip and four health bars: CPU, memory, storage, load.

Two decisions that are not cosmetic:

- **Load is normalised by thread count for the bar.** A raw `loadavg` of 14
  means nothing without knowing the box has 20 threads. The bar shows
  `load1 / cpus`; the raw 1/5/15 triple sits beside it, because the normalised
  figure alone hides the trend.
- **Fetched on demand, not polled.** Model, cores, kernel and boot mode are
  static; load, wait and memory are already recorded as metric samples every
  30s. Polling `/nodes/{n}/status` every cycle would double the per-node API
  calls for data that barely changes, and doc 02 §3 caps a cycle at O(nodes).

### Stage 2 — Hardware tab

Disk inventory from `/nodes/{n}/disks/list`: model, serial, size, health,
wearout, type, and whether the disk is a Ceph OSD. Plus PCI devices, KSM
sharing, and boot/secureboot state. Also on demand.

Wearout and health are the parts an operator cannot get from the dashboard
today and are the reason this tab is worth its own stage.

### Stage 3 — SSH hardware facts

A collector running `dmidecode` (system model, motherboard), `sensors` (CPU and
motherboard temperatures) and `ethtool` (link speed per interface).

- **Its own consent, separate from the App Store one.** Doc 08 §2 scopes the
  SSH key to "script execution only" and the existing consent text names App
  Store installs. Reusing that grant for periodic polling would make the
  consent the operator gave untrue.
- **Absence is normal.** `lm-sensors` is frequently not installed. The UI says
  "not available on this node"; it is never an error state.
- **Cached with two TTLs.** A motherboard model does not change: long TTL.
  Temperatures do: short TTL.

### Stage 4 — Metrics tab

A range picker (1h / 6h / 24h / 7d / 30d) over the existing rollups, which
already retain 5m for 14 days and 1h for 400 days. Charts for CPU, memory,
storage and network.

The per-guest breakdown lands last and is the expensive part: guests currently
record only `cpu_pct`, `mem_bytes` and `mem_pct`, so "which VM is saturating
the disk" cannot be answered until the poller collects per-guest network and
disk. That is collection work, not chart work.

### Stage 5 — Ceph tab

Detect with `/nodes/{n}/ceph/status`; hide the tab entirely on
`binary not installed`. Built against the documented response shape and
**shipped marked unverified**: there is no Ceph cluster available to test the
populated case, and claiming otherwise would be dishonest.

## Testing

Stage 1 and 2: the endpoint normalises a real captured payload (fixture taken
from the probe above, not invented); a node that 403s on status degrades to the
page rendering without the strip rather than erroring; load normalisation is
asserted against a known core count; the web-UI link carries `rel="noopener"`.
Frontend: the KV strip renders every field, the tabs route, and the Ceph tab is
absent when detection fails.

## Out of scope

- Per-node metric series. The poller records `host:<id>` from the entry node
  only, which is why charts and the node shell are entry-node-only today.
- Editing anything on the node. This page reads.
- Making temperatures a required feature. A node without `lm-sensors` is a
  supported node.
