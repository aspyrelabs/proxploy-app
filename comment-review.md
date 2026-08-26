# Comment reduction: tranche 1 for review

**930 proposals** over **18 files**, the densest in the repo. Nothing has been applied. Source is untouched.

Comment words **54,607 → 40,246**, a **26.3% cut**.

Against a corpus of 291,293 comment words in 7,493 blocks, this tranche is 19% of the words.


## The honest read on the 40 to 60 percent target

This tranche lands at 26%, not 40 to 60. The rubric said not to force it, so it was not forced. The reason is visible per file below: reduction potential is not uniform, it tracks what the comments are made of.

- Frontend components reach 38 to 48%. They are design essays wrapped around a rule, and the essay compresses.

- The Proxmox client reaches 14%. It is 183 short docstrings, each carrying one fact you cannot derive from the code, such as `guest_config_update` returning null and never a UPID. Halving it means deleting endpoint contracts.

- `models/__init__.py` reaches 15%, because it is schema invariants that migrations depend on.


The deeper cuts are likelier in the 110,608 words of test comments, which this tranche does not touch.


## How to reply

Every entry has an ID. Send verdicts by ID, for example `keep 12, 40-48` or `delete 231`. Anything you do not mention is taken as approved.


## Per file

| file | before | after | cut | delete / shorten / keep |
|---|---:|---:|---:|---|
| `backend/proxploy/pollers/__init__.py` | 7,116 | 5,493 | 23% | 4 / 41 / 48 |
| `backend/proxploy/services/proxmox.py` | 5,003 | 4,283 | 14% | 6 / 22 / 77 |
| `backend/proxploy/api/hosts.py` | 4,721 | 3,664 | 22% | 1 / 59 / 48 |
| `backend/proxploy/services/backupjobs.py` | 3,827 | 3,047 | 20% | 3 / 38 / 36 |
| `backend/proxploy/services/catalog_metadata.py` | 3,704 | 2,733 | 26% | 6 / 22 / 20 |
| `backend/proxploy/models/__init__.py` | 3,630 | 3,091 | 15% | 8 / 31 / 30 |
| `backend/proxploy/api/apps.py` | 3,240 | 2,334 | 28% | 4 / 36 / 15 |
| `backend/proxploy/services/appstore.py` | 3,036 | 2,237 | 26% | 1 / 25 / 11 |
| `backend/proxploy/services/migrate.py` | 2,785 | 1,890 | 32% | 5 / 28 / 18 |
| `frontend/src/routes/hosts.tsx` | 2,729 | 1,883 | 31% | 6 / 34 / 16 |
| `backend/proxploy/services/catalog.py` | 2,509 | 2,118 | 16% | 0 / 22 / 16 |
| `frontend/src/components/StoreCard.tsx` | 2,447 | 1,277 | 48% | 0 / 20 / 4 |
| `frontend/src/components/BellPopover.tsx` | 2,359 | 1,393 | 41% | 1 / 33 / 7 |
| `frontend/src/routes/store.tsx` | 2,184 | 1,444 | 34% | 1 / 32 / 6 |
| `frontend/src/components/IconGrid.tsx` | 1,743 | 1,206 | 31% | 0 / 19 / 8 |
| `frontend/src/components/InstallDialog.tsx` | 1,435 | 896 | 38% | 3 / 23 / 3 |
| `frontend/src/components/VmActionsMenu.tsx` | 1,185 | 671 | 43% | 1 / 14 / 2 |
| `frontend/src/api/catalogMetadata.ts` | 954 | 586 | 39% | 2 / 12 / 2 |

## Words cut by category

| category | words cut | blocks |
|---|---:|---:|
| implementation-diary | 2,662 | 56 |
| buried-invariant | 2,366 | 84 |
| external-quirk | 2,103 | 127 |
| measurement-dump | 1,334 | 22 |
| data-integrity | 1,047 | 111 |
| redundant | 990 | 45 |
| narration | 879 | 52 |
| surprising | 796 | 83 |
| contract | 720 | 185 |
| test-reference | 491 | 18 |
| security | 420 | 63 |
| concurrency | 184 | 20 |
| separator | 181 | 35 |
| ticket-history | 133 | 10 |
| compatibility | 47 | 9 |
| example | 6 | 1 |
| generated | 2 | 9 |

---

## `backend/proxploy/pollers/__init__.py`

7,116 → 5,493 words, 23% cut. 4 delete, 41 shorten, 48 keep.


### 🔴 DELETE (4)

**`[1]`** `backend/proxploy/pollers/__init__.py:580` &middot; 3w &middot; _separator_  
Banner line over the node loop.

```
# nodes + host-level samples ------------------------------------------------
```

**`[2]`** `backend/proxploy/pollers/__init__.py:699` &middot; 2w &middot; _separator_  
Banner line over the guests map.

```
# guests map ----------------------------------------------------------------
```

**`[3]`** `backend/proxploy/pollers/__init__.py:721` &middot; 11w &middot; _separator_  
Banner line with a doc reference over the apps loop.

```
# apps cache refresh (identity is ours; state is cached: doc 04) ----------
```

**`[4]`** `backend/proxploy/pollers/__init__.py:789` &middot; 7w &middot; _separator_  
Banner line with a doc reference over the VM loop.

```
# vms cache upsert (droppable mirror: doc 04) ------------------------------
```


### 🟡 SHORTEN (41)

**`[5]`** `backend/proxploy/pollers/__init__.py:1` &middot; **59w → 49w** (17% cut) &middot; _contract_  
The one-commit-per-cycle contract and the caller rule are real; the doc and phase references are not.

<details><summary>before</summary>

```
Poller subsystem (doc 10 Phase 2, doc 02 §3).

ingest_cycle() is the pure-ish core: given one host's bulk reads it updates
caches, batches metric samples (ONE commit per cycle, doc 11 §4), and returns
the fresh in-memory snapshot plus the SSE deltas to publish. The Poller class
(task loops, backoff, degradation) lives below it and is the only caller.
```

</details>

**after**

```
"""Poller subsystem.

ingest_cycle() is the pure-ish core: given one host's bulk reads it updates
caches, batches metric samples (ONE commit per cycle), and returns the fresh
in-memory snapshot plus the SSE deltas to publish. The Poller class (task
loops, backoff, degradation) lives below it and is the only caller.
"""
```

**`[6]`** `backend/proxploy/pollers/__init__.py:33` &middot; **73w → 49w** (33% cut) &middot; _buried-invariant_  
The cost reason and the in-memory choice are the point; the half-hour arithmetic restates the constant.

<details><summary>before</summary>

```
# How often the poll loop re-checks each host's tokens against their roles.
# Not every cycle: it costs one /access/permissions per configured token, and
# privileges change when an operator re-runs the setup script, not every 30
# seconds. Half an hour is slow enough to be free and fast enough that a
# re-generated token clears the warning without anyone pressing a button. Kept
# in memory, so a restart re-checks immediately, which is the useful direction.
```

</details>

**after**

```
# How often the poll loop re-checks each host's tokens against their roles.
# Not every cycle: it costs one /access/permissions per configured token, and
# privileges change when an operator re-runs the setup script, not every 30
# seconds. Kept in memory, so a restart re-checks immediately, which is the
# useful direction.
```

**`[7]`** `backend/proxploy/pollers/__init__.py:41` &middot; **152w → 99w** (35% cut) &middot; _external-quirk_  
Keeps PVE's 60s RRD bucket and the storage-resolution reason; cuts the call-count arithmetic around them.

<details><summary>before</summary>

```
# Not everything in a cycle wants the cycle's cadence, and since the cycle got
# quick (poll_interval_s is 5s) two things have to opt out of it explicitly.
#
# RRD_INTERVAL_S: node network throughput exists only in PVE's RRD, whose
# finest series buckets at exactly 60s (measured on node1: 59 points, 60s
# apart). Fetching it every 5s would return the same numbers twelve times over
# and cost a call per node each time. Between fetches the last answer is
# carried forward, because the reading is still the current one, not a gap.
#
# METRIC_SAMPLE_INTERVAL_S: the charts read MetricSample, and their resolution
# is a storage decision rather than a freshness one. At 5s this table would
# take six times the rows for the same 48h of raw retention to draw the same
# lines. The UI's live numbers come off the snapshot and the cached columns,
# which DO refresh every cycle; only the recorded history stays on 30s.
```

</details>

**after**

```
# Two things opt out of the cycle's 5s cadence.
#
# RRD_INTERVAL_S: node network throughput exists only in PVE's RRD, whose
# finest series buckets at exactly 60s (measured on node1: 59 points, 60s
# apart). Between fetches the last answer is carried forward, because the
# reading is still the current one, not a gap.
#
# METRIC_SAMPLE_INTERVAL_S: the charts read MetricSample, and its resolution
# is a storage decision, not a freshness one. At 5s the table would take six
# times the rows to draw the same lines. The UI's live numbers come off the
# snapshot and the cached columns, which DO refresh every cycle.
```

**`[8]`** `backend/proxploy/pollers/__init__.py:97` &middot; **162w → 135w** (17% cut) &middot; _contract_  
Both no-rate cases are real; the closing recap of them is not.

<details><summary>before</summary>

```
Turn this cycle's netin/netout counters into a rate on a guest row.

    Shared by the app and VM blocks below, which is why Vm carries App's
    net_* column names: PVE reports both guest types the same way and there
    is nothing container-specific in here.

    PVE reports bytes since the guest booted, so a rate is a diff against
    the previous reading over the time between the two. Both the reading and
    its timestamp are stored for the next cycle to diff against.

    Two cases produce no rate rather than a wrong one. The first reading has
    nothing to diff against: one point has no slope. And a guest restart
    zeroes the counters, so the delta goes negative; taking its absolute value
    would draw a fabricated traffic spike at exactly the moment an operator is
    most likely to be watching. Either way the rate is None for one cycle and
    recovers on the next, once there are two readings from the same boot.
    
```

</details>

**after**

```
    """Turn this cycle's netin/netout counters into a rate on a guest row.

    Shared by the app and VM blocks below, which is why Vm carries App's net_*
    column names: PVE reports both guest types the same way.

    PVE reports bytes since the guest booted, so a rate is a diff against the
    previous reading over the time between the two, and both the reading and
    its timestamp are stored for the next cycle.

    Two cases produce no rate rather than a wrong one: a first reading has
    nothing to diff against, and a guest restart zeroes the counters, so the
    delta goes negative and its absolute value would draw a fabricated traffic
    spike at exactly the moment an operator is watching. Either way the rate is
    None for one cycle and recovers on the next.
    """
```

**`[9]`** `backend/proxploy/pollers/__init__.py:128` &middot; **225w → 132w** (41% cut) &middot; _external-quirk_  
Keeps the PVE quirk (no address on an lxc row) and the two-speed cadence; cuts the full key dump and the cost arithmetic.

<details><summary>before</summary>

```
# How often a container's address is re-read, and why it is not every cycle.
#
# /cluster/resources carries NO address field for an lxc row. Confirmed against
# PVE 9.2.10 on 2026-08-20: the row's keys are cpu, disk, diskread, diskwrite,
# id, maxcpu, maxdisk, maxmem, mem, memhost, name, netin, netout, node, status,
# tags, template, type, uptime, vmid, and nothing else. So an address costs one
# per-container call, which is exactly what doc 02 section 3's budget forbids
# doing every cycle: at the default 30 s interval a 40-container fleet would be
# 80 extra calls a minute, forever, for a value that changes when somebody
# renumbers a network.
#
# So: a container with no known address is asked on the very next cycle (a
# freshly adopted app shows its address within one interval, and a DHCP lease
# that has not landed yet keeps being retried), and a container that already
# has one is asked again only every 15 minutes. That is the same 15 minutes
# APP_REAP_AFTER_S and POOL_FORGET_AFTER_S use, and it bounds how long a
# renumbered container can show its old address. Steady-state cost for those 40
# containers is under 3 calls a minute.
#
# Kept in memory rather than in a column, exactly like the capability-gap
# cadence above: a restart re-reads every address straight away, which is the
# useful direction, and it saves a migration for a value nothing else reads.
```

</details>

**after**

```
# How often a container's address is re-read, and why it is not every cycle.
#
# /cluster/resources carries NO address field for an lxc row (confirmed
# against PVE 9.2.10 on 2026-08-20), so an address costs one per-container
# call, which doc 02 section 3's budget forbids doing every cycle.
#
# A container with no known address is asked on the very next cycle, so a
# freshly adopted app shows its address within one interval and a DHCP lease
# that has not landed keeps being retried. One that already has an address is
# asked again only every 15 minutes, which bounds how long a renumbered
# container can show its old one.
#
# Kept in memory rather than in a column: a restart re-reads every address
# straight away, and it saves a migration for a value nothing else reads.
```

**`[10]`** `backend/proxploy/pollers/__init__.py:155` &middot; **166w → 142w** (14% cut) &middot; _data-integrity_  
Every one of the three rules stays; the surrounding restatement of each does not.

<details><summary>before</summary>

```
Keep `a.ip_cached` current. Returns True when the address changed.

    The rule everywhere here is: write through what we KNOW, hold what we
    could not ask.

      * a container that is not running has no address. That is an answer, not
        a gap, so it is written through as None. It also drops out of `checked`
        so that starting it again reads the new address on the next cycle
        rather than up to 15 minutes later, which matters because a DHCP
        container usually comes back on a different lease.
      * lxc_interfaces() returning None means PVE would not tell us. That is a
        gap, so the last known address stands untouched, for the same reason
        _mark_unreachable deliberately leaves this column alone: an address we
        cannot re-read right now is still the best answer anyone has.
      * PVE answering with no routable address (a running container whose lease
        has not arrived, or one with only loopback and link-local) IS an
        answer, so it clears the column and the next cycle asks again.
    
```

</details>

**after**

```
    """Keep `a.ip_cached` current. Returns True when the address changed.

    The rule everywhere here is: write through what we KNOW, hold what we
    could not ask.

      * a container that is not running has no address. That is an answer, so
        it is written through as None. It also drops out of `checked`, so
        starting it again reads the new address on the next cycle rather than
        up to 15 minutes later, which matters because a DHCP container
        usually comes back on a different lease.
      * lxc_interfaces() returning None means PVE would not tell us. That is a
        gap, so the last known address stands untouched, the same rule
        _mark_unreachable applies to this column.
      * PVE answering with no routable address (a lease that has not arrived,
        or only loopback and link-local) IS an answer, so it clears the column
        and the next cycle asks again.
    """
```

**`[11]`** `backend/proxploy/pollers/__init__.py:200` &middot; **329w → 185w** (44% cut) &middot; _external-quirk_  
Keeps the `disk: 0` quirk and the deliberate difference from _refresh_ip; cuts the per-fleet call arithmetic.

<details><summary>before</summary>

```
# How often a VM's filesystem usage is re-read from its guest agent, and why
# it is not every cycle.
#
# /cluster/resources has a `disk` field and for a QEMU guest it is routinely a
# flat 0: the hypervisor sees a block device, not the filesystem written into
# it. Measured on the lab cluster on 2026-08-20, PVE 9.2.10: VM 108 running,
# maxdisk 34359738368, `disk: 0`. So `maxdisk` is the allocation and the ONLY
# honest source for usage is the guest itself, via
# /nodes/{node}/qemu/{vmid}/agent/get-fsinfo.
#
# That is a per-VM call, which is exactly what doc 02 section 3's budget
# forbids doing every cycle, the same objection APP_IP_REFRESH_INTERVAL_S
# answers for container addresses. 15 minutes, matching that constant and
# POOL_FORGET_AFTER_S and APP_REAP_AFTER_S, because filesystem usage is a
# level that creeps rather than a rate that spikes: a disk filling up takes
# hours or days, and an operator watching one fill has the storage graph and
# the alert rules, not this column. At the default 30 s interval a 20-VM fleet
# costs under 1.5 calls a minute here, against 40 a minute if it rode every
# cycle.
#
# The cadence gate is PURELY time-based, which is the one place this
# deliberately differs from _refresh_ip. That function asks again on the very
# next cycle whenever it has no address yet, because a missing address is
# usually a DHCP lease about to arrive. A missing disk reading is usually the
# opposite: the guest agent is NOT INSTALLED, which is the common case and
# never resolves on its own, so retrying it every 30 seconds would buy nothing
# and cost a call per VM forever. A stopped VM is not asked at all (no agent
# runs in a guest that is not running) and drops out of the map, so starting
# one is measured on the next cycle rather than up to 15 minutes later.
#
# Kept in memory rather than in a column, like every other cadence here: a
# restart re-reads every VM straight away, which is the useful direction.
```

</details>

**after**

```
# How often a VM's filesystem usage is re-read from its guest agent, and why
# it is not every cycle.
#
# /cluster/resources has a `disk` field and for a QEMU guest it is routinely a
# flat 0: the hypervisor sees a block device, not the filesystem written into
# it (measured on the lab cluster, PVE 9.2.10: VM 108 running, maxdisk
# 34359738368, `disk: 0`). So `maxdisk` is the allocation and the only honest
# source for usage is the guest itself, via
# /nodes/{node}/qemu/{vmid}/agent/get-fsinfo, a per-VM call doc 02 section 3's
# budget forbids doing every cycle.
#
# The cadence gate is PURELY time-based, which is where this differs from
# _refresh_ip. A missing address is usually a DHCP lease about to arrive; a
# missing disk reading usually means the guest agent is NOT INSTALLED, which
# never resolves on its own, so retrying every cycle would cost a call per VM
# forever and buy nothing. A stopped VM is not asked at all and drops out of
# the map, so starting one is measured on the next cycle.
#
# Kept in memory rather than in a column: a restart re-reads every VM straight
# away.
```

**`[12]`** `backend/proxploy/pollers/__init__.py:237` &middot; **179w → 143w** (20% cut) &middot; _contract_  
Keeps the write-through-versus-hold contract for both columns; trims the history of how the call was widened.

<details><summary>before</summary>

```
Keep `v.disk_bytes` (USED bytes) and `v.guest_agent_ok` current.

    Both come out of ONE get-fsinfo call, because whether the agent answered is
    something that call already knew and used to throw away. See
    ProxmoxClient.agent_fsinfo for why it was widened instead of a second
    endpoint being asked.

    Unlike an address, filesystem usage is a live MEASUREMENT, so "we could
    not ask" is written through as None rather than held. That covers the
    ordinary no-agent case, and it is why the column stays NULL rather than
    dropping to 0 for the many VMs that will never have an agent: nothing is
    logged, nothing is marked degraded, and the UI renders unknown instead of
    an empty disk bar under a full one. _mark_unreachable applies the same
    rule from the other side.

    guest_agent_ok follows the same honesty rule with one difference: it is
    only ever written when the probe actually produced a verdict. A probe that
    failed for a reason PVE did not attribute to the agent leaves the previous
    verdict standing, because a connection error says nothing about what is
    installed inside the guest.
    
```

</details>

**after**

```
    """Keep `v.disk_bytes` (USED bytes) and `v.guest_agent_ok` current.

    Both come out of ONE get-fsinfo call, because whether the agent answered is
    something that call already knew. See ProxmoxClient.agent_fsinfo.

    Unlike an address, filesystem usage is a live MEASUREMENT, so "we could not
    ask" is written through as None rather than held. That is why the column
    stays NULL rather than dropping to 0 for the many VMs that will never have
    an agent: the UI renders unknown instead of an empty disk bar under a full
    one, and nothing is logged or marked degraded.

    guest_agent_ok follows the same rule with one difference: it is only ever
    written when the probe produced a verdict. A probe that failed for a reason
    PVE did not attribute to the agent leaves the previous verdict standing,
    because a connection error says nothing about what is installed inside the
    guest.
    """
```

**`[13]`** `backend/proxploy/pollers/__init__.py:273` &middot; **160w → 133w** (17% cut) &middot; _buried-invariant_  
Keeps the skip-the-gate-while-unknown invariant and the ponytail ceiling; cuts the restatement of steady-state cost.

<details><summary>before</summary>

```
# The cadence gate is skipped while the verdict is unknown, which is the
# one way this differs from the disk reading alone and mirrors what
# _refresh_ip does for a container with no address yet. An unknown verdict
# means the last probe never reached PVE (or there has not been one), so
# waiting out 15 minutes to try again would leave a brand new VM, or every
# VM on a host that has just come back, reading "unknown" for a quarter of
# an hour when one cheap call settles it. Steady-state cost is unchanged:
# once the answer is True or False it is a fact about the guest, not a
# measurement, and it rides the same 15 minute cadence as the bytes.
# ponytail: a host that keeps failing this call for some reason PVE never
# attributes to the agent gets asked once per VM per cycle. Bound it with
# a short retry interval if that is ever seen, rather than pre-emptively.
```

</details>

**after**

```
    # The cadence gate is skipped while the verdict is unknown, mirroring what
    # _refresh_ip does for a container with no address yet. An unknown verdict
    # means the last probe never reached PVE, so waiting out 15 minutes would
    # leave a brand new VM, or every VM on a host that has just come back,
    # reading "unknown" for a quarter of an hour when one cheap call settles
    # it. Once the answer is True or False it is a fact about the guest, not a
    # measurement, and rides the same 15 minute cadence as the bytes.
    # ponytail: a host that keeps failing this call for some reason PVE never
    # attributes to the agent gets asked once per VM per cycle. Bound it with a
    # short retry interval if that is ever seen, rather than pre-emptively.
```

**`[14]`** `backend/proxploy/pollers/__init__.py:299` &middot; **377w → 178w** (53% cut) &middot; _buried-invariant_  
Keeps the once-only cadence, its stated consequence and the raw-value rule; cuts the dead-column history and the key dump.

<details><summary>before</summary>

```
Fill in `v.os_type` once, from the guest's config.

    os_type was declared in the very first migration and nothing ever wrote
    it, so it was NULL for every VM including the ones Proxploy created
    itself: the create path SENDS an `ostype` and then never read it back.
    Same dead-column shape ip_cached had.

    /cluster/resources carries no ostype (confirmed on the lab cluster, PVE
    9.2.10, 2026-08-20: a qemu row's keys are cpu, disk, diskread, diskwrite,
    id, maxcpu, maxdisk, maxmem, mem, memhost, name, netin, netout, node,
    status, template, type, uptime, vmid), so this costs a per-VM config read.

    THE CADENCE IS "ONCE", not a slow refresh, and that is the whole reason
    this fits the budget: ostype is fixed when the guest is created and only
    ever changes if somebody hand-edits the VM's config, so a known value is
    never re-read. Steady state for an established fleet is therefore ZERO
    calls, and a newly discovered VM costs exactly one. Deliberately unlike
    _refresh_ip, which does have to re-ask on a timer: a DHCP lease genuinely
    moves under you, and an address that is right today can be wrong tomorrow
    with nothing having been edited. Nothing does that to an ostype. The
    consequence, stated plainly: a guest whose ostype is edited by hand in
    the Proxmox UI keeps the old value here until the row is recreated. That
    is the trade for a per-VM call nobody pays twice, and re-reading every
    VM's config on a timer to catch an edit almost nobody makes is not worth
    it. Reuses guest_config() rather than adding a wrapper, since the read is
    exactly the one api/network.py already makes.

    A config read that fails leaves the column NULL and the cycle otherwise
    untouched: it is one optional extra on top of the bulk read, in the same
    way version() and cluster_status() are in _poll_once, and losing it must
    never cost a poll. It is retried on the next cycle, which is free: the
    only VMs asked at all are the ones still missing a value.

    PVE's RAW value is stored (`l26`, `win11`, `w2k19`, `other`, ...). It is
    deliberately not collapsed to "linux"/"windows" here: that mapping is the
    client's job, and doing it in the backend would throw away a specific
    value the API then has no way to recover.
    
```

</details>

**after**

```
    """Fill in `v.os_type` once, from the guest's config.

    /cluster/resources carries no ostype (confirmed on the lab cluster, PVE
    9.2.10, 2026-08-20), so this costs a per-VM config read.

    THE CADENCE IS "ONCE", not a slow refresh, and that is what makes it fit
    the budget: ostype is fixed at create time and only changes if somebody
    hand-edits the config, so a known value is never re-read. Steady state for
    an established fleet is ZERO calls. Deliberately unlike _refresh_ip, which
    re-asks on a timer because a DHCP lease genuinely moves under you. The
    consequence: a guest whose ostype is edited by hand in the Proxmox UI
    keeps the old value here until the row is recreated.

    A failed read leaves the column NULL and the cycle otherwise untouched,
    and is retried next cycle, which is free: the only VMs asked at all are
    the ones still missing a value.

    PVE's RAW value is stored (`l26`, `win11`, `other`, ...), deliberately not
    collapsed to "linux"/"windows": that mapping is the client's job, and
    doing it here throws away a value the API cannot recover.
    """
```

**`[15]`** `backend/proxploy/pollers/__init__.py:359` &middot; **123w → 97w** (21% cut) &middot; _data-integrity_  
Keeps why the extra fields are read here and the one-transform rule; compresses the story of the duplicate that drifted.

<details><summary>before</summary>

```
The snapshot's storage shape, from raw /cluster/resources rows.

    `type`, `content`, `shared` and `status` ride on the SAME row the two byte
    counts come from: the poller used to discard them, and reading them here is
    what lets GET /storage answer from the snapshot instead of adding a
    per-datastore PVE call, which doc 02 §3's O(nodes) budget forbids.

    Module-level and shared with api/storage.py, which rebuilds these rows after
    a mutation rather than waiting out a poll interval. It was inline in
    ingest_cycle first, and the copy that grew in the API wrote RAW resource
    rows into the same field: every datastore then reported type "storage" (the
    resource type, not the plugin) and 0 bytes until the next cycle corrected
    it. One transform, one shape.
    
```

</details>

**after**

```
    """The snapshot's storage shape, from raw /cluster/resources rows.

    `type`, `content`, `shared` and `status` ride on the SAME row the two
    byte counts come from, and reading them here is what lets GET /storage
    answer from the snapshot instead of adding a per-datastore PVE call,
    which doc 02 §3's O(nodes) budget forbids.

    Module-level and shared with api/storage.py, which rebuilds these rows
    after a mutation rather than waiting out a poll interval. One transform,
    one shape: a second copy that wrote RAW resource rows had every datastore
    reporting type "storage" and 0 bytes until the next cycle corrected it.
    """
```

**`[16]`** `backend/proxploy/pollers/__init__.py:398` &middot; **244w → 196w** (20% cut) &middot; _external-quirk_  
Keeps the three ways rows vanish and the denominator rule; compresses the bug report into its conclusion and one number.

<details><summary>before</summary>

```
Last-known size of every datastore, so a pool that drops out of one
    /cluster/resources read does not silently leave disk_pct's denominator.

    Reported from real use on 2026-08-18: the storage graph flapped between
    ~29% and ~12% every few minutes while the disks sat untouched. Confirmed
    against the real cluster on 2026-08-19 by restricting one empty 1.8 TB
    pool away from its node; disk_pct went 11.6% -> 27.6% -> 11.6% with no
    byte changed.

    A cycle loses storage rows for reasons that have nothing to do with the
    disks, and none of them look like an error at the call site:

      * a cluster member drops out of /cluster/resources during a corosync
        split. Its pools go with it, and the two Hosts of one cluster start
        reporting different numbers for the same disks.
      * PVE keeps listing a datastore whose mount is down but stops filling
        in disk/maxdisk. Read literally that is a zero-byte pool, which
        leaves both sums exactly like a missing row does.
      * the monitoring token loses Datastore.Audit and EVERY storage row
        disappears at once, which used to be recorded as a flat 0.0%.

    A percentage is only a measurement if its denominator holds still, so a
    pool absent from this cycle keeps the last size we actually measured: an
    unreachable disk still holds the bytes it held. Kept in memory per host,
    which is the useful direction on restart -- the first cycle after a
    restart has nothing to carry forward and simply reports what it can read.
    
```

</details>

**after**

```
    """Last-known size of every datastore, so a pool that drops out of one
    /cluster/resources read does not silently leave disk_pct's denominator.

    Without it the storage graph flaps: confirmed on the real cluster
    (2026-08-19) by restricting one empty 1.8 TB pool away from its node,
    disk_pct went 11.6% -> 27.6% -> 11.6% with no byte changed.

    A cycle loses storage rows for reasons that have nothing to do with the
    disks, and none look like an error at the call site: a member dropping out
    during a corosync split takes its pools with it, so the two Hosts of one
    cluster report different numbers for the same disks; PVE keeps listing a
    datastore whose mount is down but stops filling in disk/maxdisk, which read
    literally is a zero-byte pool; and a token that loses Datastore.Audit makes
    EVERY storage row disappear at once, once recorded as a flat 0.0%.

    A percentage is only a measurement if its denominator holds still, so a
    pool absent from this cycle keeps the last size we actually measured: an
    unreachable disk still holds the bytes it held. Kept in memory per host, so
    the first cycle after a restart reports what it can read.
    """
```

**`[17]`** `backend/proxploy/pollers/__init__.py:447` &middot; **71w → 69w** (3% cut) &middot; _data-integrity_  
Keeps the dedupe rule and the meaning of None; trims the framing around them.

<details><summary>before</summary>

```
Aggregate used/total across this host's datastores, over a pool set
    that survives a bad read (see PoolMemory).

    Deduped correctly, unlike the cluster ring's deliberate shortcut in
    api/cluster.py::cluster_summary. Doing it wrong here is not a cosmetic
    ring error; it is an alert that fires at the wrong number.

    None means "no datastore has been readable recently", which is a gap in
    the series rather than a host whose disks are 0% full.
    
```

</details>

**after**

```
    """Aggregate used/total across this host's datastores, over a pool set
    that survives a bad read (see PoolMemory).

    Deduped correctly, unlike the cluster ring's deliberate shortcut in
    api/cluster.py::cluster_summary. Doing it wrong here is not a cosmetic
    ring error, it is an alert that fires at the wrong number.

    None means "no datastore has been readable recently", a gap in the series
    rather than a host whose disks are 0% full.
    """
```

**`[18]`** `backend/proxploy/pollers/__init__.py:480` &middot; **428w → 317w** (26% cut) &middot; _data-integrity_  
Every bullet is a real cause of a false absence and stays; the `complete` paragraph's investigation notes are compressed.

<details><summary>before</summary>

```
Can this cycle's guest list be used as PROOF that a CT is gone?

    Usually the honest answer is no, and getting this wrong deletes a user's
    app records because a node rebooted. "Not in /cluster/resources" has at
    least four causes and only one of them is "somebody destroyed it":

      * the host was unreachable. That case cannot reach here at all:
        _poll_once raises before ingest_cycle, and _host_loop turns the raise
        into status=unreachable without ever calling us.
      * the cycle was degraded (a read 403'd, timed out, or came back short).
        A half-answer is not evidence of anything, so we hold what we have.
      * a CLUSTER MEMBER is down. This is the dangerous one, because nothing
        else about the cycle looks wrong: the endpoint we asked answered
        fine, the host is "connected", the cycle is not degraded -- and an
        entire node's worth of guests has silently dropped out of
        /cluster/resources. App rows carry host_id + ctid and no node, so we
        cannot tell "this app lived on the node that just went down" from
        "this app was destroyed"; the only safe move is to distrust the whole
        cycle unless every node in it reports online.

        `complete` covers the remaining hole in that check. Measured against
        real hardware on 2026-08-19 by rebooting a cluster member: a node that
        goes down KEEPS its /cluster/resources row and flips it to
        `status: "offline"`, and its storage rows stay too, so the online test
        above already catches an ordinary outage and that is the common case.
        What it cannot catch is a member that stops appearing in the response
        at all, because then there is no row left to test: `all(... online)`
        is trivially true for a read missing half the cluster. We have not
        reproduced that on this hardware (a reboot does not do it), so treat
        this as a guard rather than a fix for an observed failure. It costs
        nothing when the count is unknown and it cannot invent a partial
        cycle, since expected can only be compared against nodes we did see.
      * an empty or truncated response. A resource list with no node rows in
        it is a broken read, never a genuinely empty cluster.

    Clearing all of that makes ONE cycle trustworthy, which is still not
    enough to delete anything: the caller additionally requires the absence to
    persist across trustworthy cycles for APP_REAP_AFTER_S, so even a
    plausible-looking bad read has to repeat for a quarter of an hour before a
    single row is removed. Restarting the backend does not shorten that
    window either -- the countdown lives in apps.missing_since, in the DB.
    
```

</details>

**after**

```
    """Can this cycle's guest list be used as PROOF that a CT is gone?

    Usually the honest answer is no, and getting this wrong deletes a user's
    app records because a node rebooted. "Not in /cluster/resources" has at
    least four causes and only one is "somebody destroyed it":

      * the host was unreachable. That cannot reach here at all: _poll_once
        raises before ingest_cycle, and _host_loop turns the raise into
        status=unreachable without ever calling us.
      * the cycle was degraded (a read 403'd, timed out, or came back short).
        A half-answer is not evidence of anything, so we hold what we have.
      * a CLUSTER MEMBER is down. This is the dangerous one: the endpoint we
        asked answered fine, the host is "connected", the cycle is not
        degraded, and an entire node's worth of guests has silently dropped
        out. App rows carry host_id + ctid and no node, so "this app lived on
        the node that just went down" and "this app was destroyed" look
        identical; the only safe move is to distrust the whole cycle unless
        every node in it reports online.

        `complete` covers the hole in that check. A node that goes down KEEPS
        its row and flips it to `status: "offline"` (measured on hardware,
        2026-08-19), so the online test already catches an ordinary outage.
        What it cannot catch is a member that stops appearing at all, since
        then there is no row left to test. That has not been reproduced here,
        so it is a guard rather than a fix, and it costs nothing when the
        member count is unknown.
      * an empty or truncated response. A resource list with no node rows is a
        broken read, never a genuinely empty cluster.

    One trustworthy cycle is still not enough to delete anything: the caller
    additionally requires the absence to persist across trustworthy cycles for
    APP_REAP_AFTER_S, and a backend restart does not shorten that window, since
    the countdown lives in apps.missing_since.
    """
```

**`[19]`** `backend/proxploy/pollers/__init__.py:539` &middot; **32w → 25w** (22% cut) &middot; _test-reference_  
The default's meaning stands on its own; the parenthetical about which tests hit it does not.

<details><summary>before</summary>

```
# A fresh PoolMemory has nothing to carry forward, so a caller that does
# not keep one across cycles (every test that drives a single cycle) gets
# exactly what this cycle's rows say.
```

</details>

**after**

```
    # A fresh PoolMemory has nothing to carry forward, so a caller that does
    # not keep one across cycles gets exactly what this cycle's rows say.
```

**`[20]`** `backend/proxploy/pollers/__init__.py:543` &middot; **92w → 74w** (20% cut) &middot; _concurrency_  
Keeps the hold rule, the per-cycle query and the NULL started_at case; drops the restatement.

<details><summary>before</summary>

```
# Guests the poller must not answer for this cycle, because something is
# already acting on them and knows better. One query per cycle rather than
# per guest. Their OTHER readings (cpu, memory, disk) are still written:
# those are measurements and stay true mid-action, it is only `status` that
# a running stop makes stale.
# started_at is NULL while a job is still queued, which is the moment it
# most deserves the hold, so a missing stamp counts as fresh and only a job
# that has actually been running past the ceiling loses it.
```

</details>

**after**

```
    # Guests the poller must not answer for this cycle, because something is
    # already acting on them and knows better. One query per cycle rather than
    # per guest. Their OTHER readings (cpu, memory, disk) are still written:
    # those stay true mid-action, it is only `status` that a running stop makes
    # stale. started_at is NULL while a job is queued, which is the moment it
    # most deserves the hold, so a missing stamp counts as fresh.
```

**`[21]`** `backend/proxploy/pollers/__init__.py:552` &middot; **96w → 70w** (27% cut) &middot; _contract_  
Keeps what each optional argument means and why fs_checked cannot share ip_checked's map; drops the restatement of the module contract.

<details><summary>before</summary>

```
# `client` is the only argument that lets this function make a PVE call of
# its own, and it is optional so the bulk-read-in, caches-out contract still
# holds without one: no client means addresses are simply not refreshed
# this cycle, everything else behaves identically. `ip_checked` is the
# per-app "last asked at" behind APP_IP_REFRESH_INTERVAL_S; a caller that
# does not keep one across cycles asks every time, which is what a single
# test cycle wants. `fs_checked` is the same thing for VM_DISK_REFRESH_
# INTERVAL_S, keyed on vm id rather than app id, which is why it cannot
# share ip_checked's map.
```

</details>

**after**

```
    # `client` is optional so the bulk-read-in, caches-out contract still
    # holds without one: no client means addresses are simply not refreshed
    # this cycle, everything else behaves identically. `ip_checked` is the
    # per-app "last asked at" behind APP_IP_REFRESH_INTERVAL_S; a caller that
    # does not keep one across cycles asks every time. `fs_checked` is the
    # same thing for VM_DISK_REFRESH_INTERVAL_S, keyed on vm id rather than
    # app id, which is why it cannot share ip_checked's map.
```

**`[22]`** `backend/proxploy/pollers/__init__.py:570` &middot; **85w → 72w** (15% cut) &middot; _external-quirk_  
Keeps the quirk, the hardware confirmation and the unknown-is-complete rule, stated once.

<details><summary>before</summary>

```
# Did this cycle see the whole cluster? A member that stops appearing in
# /cluster/resources leaves no row behind to notice it by, so the only
# check available is against the configured member count. /cluster/status
# carries that whether or not the member is up: confirmed on hardware on
# 2026-08-19, where `nodes` stayed 2 across a node reboot while that node's
# own row read `online: 0`. Unknown (a standalone node, or a failed status
# read) counts as complete: this must never make a healthy host look partial.
```

</details>

**after**

```
    # Did this cycle see the whole cluster? A member that stops appearing in
    # /cluster/resources leaves no row to notice it by, so the only check is
    # against the configured member count, which /cluster/status carries
    # whether or not the member is up (confirmed on hardware: `nodes` stayed 2
    # across a node reboot while that node's own row read `online: 0`).
    # Unknown counts as complete: this must never make a healthy host look
    # partial.
```

**`[23]`** `backend/proxploy/pollers/__init__.py:603` &middot; **101w → 72w** (29% cut) &middot; _data-integrity_  
Keeps why the series is gated and the snapshot is not; cuts the closing recap.

<details><summary>before</summary>

```
# These two are SUMS over the nodes, so they are only a measurement when
# every node is in them: a missing member halves the number and a node
# whose rrddata 403'd (degraded) contributes a silent 0.0. Unlike disk_pct
# there is nothing honest to carry forward, because throughput is a rate
# rather than a level: last cycle's bytes are traffic that did not happen.
# Only the recorded series is gated. The snapshot keeps the raw sum,
# because it answers "what can this host see right now", and zeroing it
# would trade a halved number in the cluster ring for an emptier one.
```

</details>

**after**

```
    # These two are SUMS over the nodes, so they are only a measurement when
    # every node is in them: a missing member halves the number and a node
    # whose rrddata 403'd contributes a silent 0.0. Nothing honest can be
    # carried forward, because throughput is a rate: last cycle's bytes are
    # traffic that did not happen. Only the recorded series is gated, since
    # the snapshot answers "what can this host see right now".
```

**`[24]`** `backend/proxploy/pollers/__init__.py:614` &middot; **190w → 134w** (29% cut) &middot; _buried-invariant_  
Keeps why the column is written here and why the snapshot guess is not second-guessed; cuts the discovery story and the task number.

<details><summary>before</summary>

```
# host.node_name is otherwise write-never: POST /hosts has no way to learn
# it (PVE's /version carries no node name), so a host added through the
# real wizard sat at NULL forever: /cluster/nodes and the VM-create
# wizard's node picker both read this column directly, not the snapshot,
# so they silently had nothing to offer. Only tests/support.py's
# seed_host_row ever set it, which is why this never showed up until the
# onboarding journey actually drove host creation through the UI (Task 16).
# The guess from snap_nodes is written once: it is whichever node happened
# to come first in /cluster/resources, so a real multi-node cluster's
# actual "home" node for this Host row is not something it should
# second-guess. `node_name` from the caller is not a guess: /cluster/status
# marks the node at this host's own address, so it is refreshed every
# cycle, for the same reason pve_version and cluster_name below are. A node
# renamed in PVE otherwise keeps its old name here forever, and peer
# discovery compares against this column to decide a node is already
# enrolled. Falsy means the read failed or the cluster shape was
# surprising, and a stale name beats a blank one.
```

</details>

**after**

```
    # host.node_name is otherwise write-never: POST /hosts has no way to learn
    # it (PVE's /version carries no node name), so a host added through the
    # real wizard sat at NULL forever while /cluster/nodes and the VM-create
    # wizard's node picker read this column directly, not the snapshot. The
    # snap_nodes guess is written once and only as a fallback: it is whichever
    # node came first in /cluster/resources, which is not a real cluster's
    # "home" node. `node_name` from the caller is not a guess (/cluster/status
    # marks the node at this host's own address) so it is refreshed every
    # cycle: a node renamed in PVE otherwise keeps its old name here forever,
    # and peer discovery compares against this column to decide a node is
    # already enrolled. Falsy means the read failed, and a stale name beats a
    # blank one.
```

**`[25]`** `backend/proxploy/pollers/__init__.py:668` &middot; **86w → 66w** (23% cut) &middot; _buried-invariant_  
Keeps the write-never problem and the None-means-not-read rule; cuts the anecdote about clicking Test.

<details><summary>before</summary>

```
# An in-place PVE upgrade otherwise never reaches this column: it was
# written at enrolment and by POST /hosts/{id}/test, and by nothing else.
# The host page reads it for the header subline while the identity rail
# reads the node's live /status, so the two disagreed after every upgrade
# until somebody happened to click Test.
#
# `version is None` means the probe failed, not that the node has no
# version; same shape as rrddata above. Writing it through would replace a
# true-but-stale version with "unknown", which is strictly worse.
```

</details>

**after**

```
    # An in-place PVE upgrade otherwise never reaches this column: it was
    # written at enrolment and by POST /hosts/{id}/test, and by nothing else,
    # so the host page's header subline and the identity rail's live /status
    # disagreed after every upgrade.
    #
    # `version is None` means the probe failed, not that the node has no
    # version. Writing it through would replace a true-but-stale version with
    # "unknown", which is strictly worse.
```

**`[26]`** `backend/proxploy/pollers/__init__.py:689` &middot; **71w → 63w** (11% cut) &middot; _external-quirk_  
Keeps the UNREAD rule and the read-only /etc/pve quirk; drops the doc reference.

<details><summary>before</summary>

```
# Quorum, from the same /cluster/status read as the two above. UNREAD when
# that read failed, since "we could not ask" must not overwrite a known
# answer; None is a legitimate value to write (standalone, no cluster row).
# Without quorum /etc/pve is read-only and every write fails while
# /cluster/resources answers perfectly, so this is the only thing that
# makes an unwritable host look different from a healthy one (doc 12
# check 12).
```

</details>

**after**

```
    # Quorum, from the same /cluster/status read as the two above. UNREAD when
    # that read failed, since "we could not ask" must not overwrite a known
    # answer; None is legitimate (standalone, no cluster row). Without quorum
    # /etc/pve is read-only and every write fails while /cluster/resources
    # answers perfectly, so this is the only thing that makes an unwritable
    # host look different from a healthy one.
```

**`[27]`** `backend/proxploy/pollers/__init__.py:820` &middot; **57w → 29w** (49% cut) &middot; _data-integrity_  
Keeps the name collision and the migration that caused it; cuts the retelling of what the VMs page could not draw.

<details><summary>before</summary>

```
# ALLOCATION, which is what this row used to hold under the names
# mem_bytes and disk_bytes while those same names meant USAGE on an
# App. Migration a1f4d80c3e69 moved the allocation into these two and
# gave the short names App's meaning; the usage below is the reading
# the VMs page had no way to draw a meter from before.
```

</details>

**after**

```
        # ALLOCATION, against the short names mem_bytes and disk_bytes which
        # mean USAGE on both App and Vm. Migration a1f4d80c3e69 split the two
        # apart; before it these names held the allocation.
```

**`[28]`** `backend/proxploy/pollers/__init__.py:826` &middot; **43w → 39w** (9% cut) &middot; _redundant_  
The honesty rule is stated three lines up; only the maxdisk case is new.

<details><summary>before</summary>

```
# Same honesty rule as the app block above: 0 from PVE means "no
# reading", not "zero bytes used". A stopped guest reports mem 0, and
# a maxdisk of 0 is a row we could not read rather than a VM with no
# disk.
```

</details>

**after**

```
        # Same honesty rule as the app block above: 0 from PVE means "no
        # reading". A stopped guest reports mem 0, and a maxdisk of 0 is a row
        # we could not read rather than a VM with no disk.
```

**`[29]`** `backend/proxploy/pollers/__init__.py:835` &middot; **94w → 89w** (5% cut) &middot; _data-integrity_  
Keeps the evidence rule, the alert-rule consequence and the ponytail ceiling.

<details><summary>before</summary>

```
# Same evidence rule the app loop above applies, and for the same
# reason: with one cluster member down, that node's guests vanish
# from /cluster/resources while the cycle otherwise looks healthy.
# Deleting here took the alert rules with it, since targets_for()
# resolves a vm rule to nothing once the row is gone and the orphan
# sweep then resolves any firing alert as "target removed".
# ponytail: no missing_since countdown for VMs like apps have, so a
# trustworthy cycle still deletes at once. Add the column if a VM
# is ever seen disappearing from a fully-online cluster.
```

</details>

**after**

```
            # Same evidence rule the app loop above applies: with one cluster
            # member down, that node's guests vanish from /cluster/resources
            # while the cycle otherwise looks healthy. Deleting here took the
            # alert rules with it, since targets_for() resolves a vm rule to
            # nothing once the row is gone and the orphan sweep then resolves
            # any firing alert as "target removed".
            # ponytail: no missing_since countdown for VMs like apps have, so
            # a trustworthy cycle still deletes at once. Add the column if a VM
            # is ever seen disappearing from a fully-online cluster.
```

**`[30]`** `backend/proxploy/pollers/__init__.py:855` &middot; **24w → 11w** (54% cut) &middot; _redundant_  
The cadence is spelled out in _refresh_os_type; the call site only needs the pointer.

<details><summary>before</summary>

```
# The only other per-VM call in the cycle, and the cheap one: it asks
# once per VM ever, not on a timer. See _refresh_os_type.
```

</details>

**after**

```
        # Asks once per VM ever, not on a timer. See _refresh_os_type.
```

**`[31]`** `backend/proxploy/pollers/__init__.py:871` &middot; **10w → 7w** (30% cut) &middot; _separator_  
Banner with one real constraint inside it: nothing here auto-adopts.

<details><summary>before</summary>

```
# discovered CTs + adoption heuristic (NOT auto-adopted: Phase 4 owns that)
```

</details>

**after**

```
    # discovered CTs + adoption heuristic. Nothing here auto-adopts.
```

**`[32]`** `backend/proxploy/pollers/__init__.py:882` &middot; **85w → 61w** (28% cut) &middot; _data-integrity_  
Keeps why the row is deleted and the recovery path; cuts the aside about a new state.

<details><summary>before</summary>

```
# Reaping: the CT behind these apps is gone, so the app is gone. The row is
# DELETED rather than flagged, which is what makes it disappear everywhere
# at once (GET /apps, the host page's app list, and the per-host app counts
# on /cluster/nodes all read the apps table directly, so there is nothing
# to teach about a new "orphaned" state). A re-created CT with the same
# ctid comes back as a `discovered` container and can be adopted, which is
# the recovery path that already exists.
```

</details>

**after**

```
    # Reaping: the CT behind these apps is gone, so the app is gone. The row is
    # DELETED rather than flagged, which is what makes it disappear everywhere
    # at once: GET /apps, the host page's app list and /cluster/nodes' per-host
    # counts all read the apps table directly. A re-created CT with the same
    # ctid comes back as `discovered` and can be adopted.
```

**`[33]`** `backend/proxploy/pollers/__init__.py:910` &middot; **48w → 41w** (15% cut) &middot; _test-reference_  
Keeps why the default is True and what still gets written; drops the aside about tests.

<details><summary>before</summary>

```
# Default True so every existing caller (and every test that drives one
# cycle) records exactly as it did; the poller passes False on the cycles
# between recordings. The cached columns and the snapshot are written
# either way, so the UI is fresh on a cycle that stored nothing.
```

</details>

**after**

```
    # Default True so every existing caller records exactly as it did; the
    # poller passes False on the cycles between recordings. The cached columns
    # and the snapshot are written either way, so the UI is fresh on a cycle
    # that stored nothing.
```

**`[34]`** `backend/proxploy/pollers/__init__.py:926` &middot; **35w → 32w** (9% cut) &middot; _concurrency_  
The thread isolation rule is the contract; the doc reference is not.

<details><summary>before</summary>

```
Supervisor + one long-lived task per host (doc 02 §3).

    All blocking work (proxmoxer, SQLAlchemy) runs in asyncio.to_thread with a
    per-host timeout, so one slow/dead host can never stall the event loop or
    its sibling loops.
    
```

</details>

**after**

```
    """Supervisor + one long-lived task per host.

    All blocking work (proxmoxer, SQLAlchemy) runs in asyncio.to_thread with a
    per-host timeout, so one slow/dead host can never stall the event loop or
    its sibling loops.
    """
```

**`[35]`** `backend/proxploy/pollers/__init__.py:957` &middot; **22w → 14w** (36% cut) &middot; _redundant_  
The shape and reason are stated on the two maps directly above; only the key and the interval differ.

<details><summary>before</summary>

```
# host_id -> {vm_id: when its guest agent was last asked for disk
# usage}. Same shape and same reason as _ip_checked above, for
# VM_DISK_REFRESH_INTERVAL_S.
```

</details>

**after**

```
        # host_id -> {vm_id: when its guest agent was last asked for disk
        # usage}, behind VM_DISK_REFRESH_INTERVAL_S.
```

**`[36]`** `backend/proxploy/pollers/__init__.py:988` &middot; **68w → 58w** (15% cut) &middot; _ticket-history_  
Keeps why alerts ride the supervisor and why the try block is separate; drops the quoted phase plan.

<details><summary>before</summary>

```
# Doc 10 Phase 7: "alert_rules CRUD + evaluator riding the poll
# loop". Here rather than in _host_loop: this supervisor already
# ticks exactly once per interval no matter how many hosts exist,
# and every rule's answer is global: evaluating per host would be
# N times the queries for the same result. Wrapped separately from
# the block above so an alerting failure can never stop the
# supervisor from (re)spawning host loops.
```

</details>

**after**

```
            # Here rather than in _host_loop: this supervisor already ticks
            # exactly once per interval no matter how many hosts exist, and
            # every rule's answer is global, so evaluating per host would be N
            # times the queries for the same result. Wrapped separately from
            # the block above so an alerting failure can never stop the
            # supervisor from respawning host loops.
```

**`[37]`** `backend/proxploy/pollers/__init__.py:1031` &middot; **195w → 147w** (25% cut) &middot; _measurement-dump_  
Keeps the conclusion and one representative number; drops the three measured ranges and the doc reference.

<details><summary>before</summary>

```
Poll this host on the next iteration instead of waiting out
        poll_interval_s. Called by anything that has just created or destroyed
        a guest on it.

        Why an immediate re-poll is worth making: measured against the lab
        cluster (PVE 9.2.11, 2026-08-20), a new guest appears in
        /cluster/resources 17 to 19 ms after its create task reports finished,
        and a destroyed one disappears 27 to 39 ms after its destroy task does
        (54 to 97 ms when read from a different cluster member). PVE's status
        cache is not what made a new VM take 10 to 20 seconds to show up in the
        list; our own 30 s interval was the entire delay, so polling again
        right away actually returns the guest.

        The mirror stays the poller's alone, doc 04 (Proxmox is the truth): a
        wake asks for a normal cycle sooner, it does not write a row.

        Safe to call before the host has a loop (the flag is picked up when one
        starts), while it is mid-cycle (the wait at the end of _host_loop is
        what consumes it), and repeatedly. Must be called from the event loop
        thread, which every job handler already runs on.
        
```

</details>

**after**

```
        """Poll this host on the next iteration instead of waiting out
        poll_interval_s. Called by anything that has just created or destroyed
        a guest on it.

        Worth making: measured against the lab cluster (PVE 9.2.11), a new
        guest appears in /cluster/resources under 20 ms after its create task
        reports finished. PVE's status cache is not what made a new VM take 10
        to 20 seconds to show up; our own 30 s interval was the entire delay.

        The mirror stays the poller's alone (Proxmox is the truth): a wake asks
        for a normal cycle sooner, it does not write a row.

        Safe to call before the host has a loop (the flag is picked up when one
        starts), while it is mid-cycle (the wait at the end of _host_loop
        consumes it), and repeatedly. Must be called from the event loop
        thread, which every job handler already runs on.
        """
```

**`[38]`** `backend/proxploy/pollers/__init__.py:1078` &middot; **51w → 46w** (10% cut) &middot; _implementation-diary_  
Keeps the reason the reason string exists; drops the account of what the old code did.

<details><summary>before</summary>

```
# This used to swallow the exception whole. A 403 on a
# privilege the token was never granted, a TLS failure and a
# genuinely dead node all became the bare word "unreachable",
# with nothing logged, so there was no way to tell them apart
# from either the UI or the server log.
```

</details>

**after**

```
                # A 403 on a privilege the token was never granted, a TLS
                # failure and a genuinely dead node must not all collapse into
                # the bare word "unreachable" with nothing logged, or there is
                # no way to tell them apart from the UI or the server log.
```

**`[39]`** `backend/proxploy/pollers/__init__.py:1116` &middot; **52w → 31w** (40% cut) &middot; _buried-invariant_  
Keeps why the poller addresses the monitoring credential directly; drops the report filename and the rename history.

<details><summary>before</summary>

```
# Monitoring is the one capability every enrolled host is
# guaranteed to have (mandatory at enrolment, api/hosts.py::
# create_host), so the poller keeps reading it directly rather
# than going through client_for_host's capability="monitoring"
# default; this is the same row, just addressed the way it has
# always been addressed, renamed per the per-capability token
# encoding (host-token-privileges-step-one-report.md).
```

</details>

**after**

```
            # Monitoring is the one capability every enrolled host is
            # guaranteed to have (mandatory at enrolment, api/hosts.py::
            # create_host), so the poller keeps reading it directly rather
            # than going through client_for_host's capability="monitoring"
            # default.
```

**`[40]`** `backend/proxploy/pollers/__init__.py:1132` &middot; **107w → 109w** (-2% cut) &middot; _external-quirk_  
Keeps the 403-on-rrddata quirk, the carry-forward and the never-stamped rule; tightens the wording.

<details><summary>before</summary>

```
# Metrics are the optional half of a cycle. On real hardware a
# privsep token that can read /cluster/resources still 403s on
# /nodes/<n>/rrddata (Sys.Audit), and letting that escape cost the
# whole cycle: discovery, node_name and status all went with it,
# and the host was reported unreachable while answering fine.
# Only when the 60s bucket could have turned over; otherwise the
# previous answer is reused verbatim. `degraded` is carried with
# it, since "we could not read the metrics" is still true on a
# cycle that did not try.
# `_rrd_at` is only ever stamped by a clean fetch, so "never
# fetched" and "last fetch failed" both land here as due.
```

</details>

**after**

```
            # Metrics are the optional half of a cycle. On real hardware a
            # privsep token that can read /cluster/resources still 403s on
            # /nodes/<n>/rrddata (Sys.Audit), and letting that escape cost the
            # whole cycle: discovery, node_name and status all went with it,
            # and the host was reported unreachable while answering fine.
            # Fetched only when the 60s bucket could have turned over;
            # otherwise the previous answer is reused verbatim, and `degraded`
            # is carried with it, since "we could not read the metrics" is
            # still true on a cycle that did not try. `_rrd_at` is only ever
            # stamped by a clean fetch, so "never fetched" and "last fetch
            # failed" both land here as due.
```

**`[41]`** `backend/proxploy/pollers/__init__.py:1155` &middot; **71w → 52w** (27% cut) &middot; _concurrency_  
Keeps why only success earns the hold; trims the comparison to the other calls.

<details><summary>before</summary>

```
# The 60s hold is earned by SUCCESS, and only by success: it
# exists because we already hold this minute's numbers, and a
# failed fetch holds nothing. Latching a failure for a minute
# would leave the host flagged degraded for up to 60s after it
# recovered, so a failure retries on the next cycle instead.
# That is the same treatment version() and cluster_status()
# already get, both of which are attempted every cycle.
```

</details>

**after**

```
                # The 60s hold is earned by SUCCESS only: it exists because we
                # already hold this minute's numbers, and a failed fetch holds
                # nothing. Latching a failure would leave the host flagged
                # degraded for up to 60s after it recovered, so a failure
                # retries on the next cycle instead, like version() and
                # cluster_status().
```

**`[42]`** `backend/proxploy/pollers/__init__.py:1237` &middot; **300w → 219w** (27% cut) &middot; _buried-invariant_  
Keeps why the clearing is centralised and the per-guest sweep rule; tightens the retelling around them.

<details><summary>before</summary>

```
Every failed cycle lands here, so this is also the one place that
        already knows a host is gone and already holds a session on it. The
        cached status/metric columns on App and Vm are exactly what
        cluster.py's running counts, consoles.py's launch guard and
        backups.py's target picker all read, and none of those four call
        sites ever finds out the host went away: ingest_cycle, the only other
        writer of those columns, never runs for a host that raised before it
        got there. Clearing the cache here, once, is correct for all four
        readers; a guard added at each of them instead could drift out of
        sync with the other three.

        The host loop keeps retrying a dead host forever, just slower each
        time (the backoff above), so this runs on every one of those retries,
        including every retry after a backend restart that comes back to a
        host still down. The host's own status flip to "unreachable" is only
        worth an SSE event on the transition (the `already` check below), but
        the guest sweep cannot use that same host-level flag to decide
        whether it has work to do: a guest can be left stale by a restart
        even though the host row already reads "unreachable" from before the
        restart. So the sweep runs every call, and each guest is checked on
        its own: a guest already fully cleared (status unknown and every
        cached reading already null) is skipped with no write and no event,
        which is what stops a dead host retrying every cycle from restating
        the same rows or republishing the same events forever. A guest whose
        status already reads unknown but still has a stale reading (set by
        ingest_cycle's own absence path, or left over some other way) is not
        considered cleared and gets its readings nulled too.
        
```

</details>

**after**

```
        """Every failed cycle lands here, so this is the one place that already
        knows a host is gone and already holds a session on it. The cached
        status/metric columns on App and Vm are what cluster.py's running
        counts, consoles.py's launch guard and backups.py's target picker all
        read, and none of them ever finds out the host went away: ingest_cycle,
        the only other writer, never runs for a host that raised before it got
        there. Clearing the cache here, once, is correct for all four; a guard
        at each of them could drift out of sync.

        The host loop retries a dead host forever, just slower each time, so
        this runs on every retry. The host's own flip to "unreachable" is worth
        an SSE event only on the transition (the `already` check below), but
        the guest sweep cannot key off that flag: a restart can leave a guest
        stale while the host row already reads "unreachable". So the sweep runs
        every call and checks each guest on its own. A guest already fully
        cleared (status unknown and every cached reading null) is skipped with
        no write and no event, which is what stops a dead host from restating
        the same rows forever; one whose status reads unknown but still has a
        stale reading is not cleared and gets nulled too.
        """
```

**`[43]`** `backend/proxploy/pollers/__init__.py:1308` &middot; **255w → 118w** (54% cut) &middot; _buried-invariant_  
Keeps the fact-versus-measurement rule for ip_cached and the reason the net counters are safe to leave; cuts the two-case walkthrough.

<details><summary>before</summary>

```
# ip_cached is deliberately NOT cleared, and is deliberately
# not part of already_cleared above either. The readings above
# are live measurements that go stale the instant nobody can
# take them; an address is not a measurement, it is a fact
# about the container that stays true while its host is
# unreachable and almost always survives the outage. Nulling it
# would replace the one piece of information still worth having
# (where this app was) with "unknown", and it would come back
# the moment the host answered anyway. _refresh_ip applies the
# same rule from the other side: it holds the last known
# address whenever PVE will not answer.
#
# net_in_cached, net_out_cached and net_sampled_at are left
# exactly as they were. They are not a reading shown to
# anyone, only the raw counters _update_net_rates diffs
# against, and that function already treats a stale
# net_sampled_at correctly on its own: if the guest rebooted
# with its host (the common case, since "host unreachable"
# usually means the hardware is off), PVE's counters reset to
# a value below what is stored here and the existing
# now_in < prev_in guard throws the rate away for one cycle,
# same as any other reboot. If the guest somehow kept running
# untouched through the outage, the counters kept climbing
# and the first post-recovery rate is a genuine average over
# the outage window, not a fabricated spike, so there is
# nothing here worth guarding against. Nulling net_sampled_at
# instead would only turn that second, harmless case into a
# silently wrong one for one extra cycle, for no benefit in
# the common case.
```

</details>

**after**

```
                # ip_cached is deliberately NOT cleared, and deliberately not
                # part of already_cleared above. The readings above are live
                # measurements that go stale the instant nobody can take them;
                # an address is a fact about the container that stays true
                # while its host is unreachable and almost always survives the
                # outage. _refresh_ip applies the same rule from the other side.
                #
                # net_in_cached, net_out_cached and net_sampled_at are left as
                # they were: not readings shown to anyone, only the counters
                # _update_net_rates diffs against, and it already handles a
                # stale sample. A guest that rebooted with its host trips the
                # now_in < prev_in guard and loses one cycle's rate; one that
                # kept running gives a genuine average over the outage rather
                # than a fabricated spike.
```

**`[44]`** `backend/proxploy/pollers/__init__.py:1353` &middot; **83w → 44w** (47% cut) &middot; _redundant_  
The measurement-versus-fact split is stated in the app sweep above; only the list of five readings is new here.

<details><summary>before</summary>

```
# Split exactly the way the app sweep above splits it: a live
# MEASUREMENT nobody can take right now is unknown, and a fact
# about how the guest is configured stays true while its host
# is off the air.
#
# Cleared, because all five are readings: uptime_s (how long
# the guest has been up), mem_bytes (memory in use),
# disk_bytes (what the guest agent last said its filesystems
# hold) and the two derived network rates. A stale rate is the
# same lie a stale "running" is.
```

</details>

**after**

```
                # Split exactly the way the app sweep above splits it: a live
                # MEASUREMENT nobody can take right now is unknown, and a fact
                # about how the guest is configured stays true while its host
                # is off the air. All five cleared below are readings.
```

**`[45]`** `backend/proxploy/pollers/__init__.py:1368` &middot; **305w → 159w** (48% cut) &middot; _buried-invariant_  
Keeps which columns are held, why guest_agent_ok and os_type are among them, and the deliberate difference from the app sweep; cuts the repeats.

<details><summary>before</summary>

```
# Held: cpu_cores, mem_total_bytes and disk_total_bytes are
# the guest's configured allocation (maxcpu/maxmem/maxdisk),
# which is a fact rather than a reading and does not stop
# being true because a host went away. guest_agent_ok is held
# for exactly that reason too, and it is worth saying out loud
# because the column sits next to disk_bytes and comes from
# the same call: whether the QEMU guest agent is installed in
# a guest is a fact about how that guest is built, not a live
# measurement, and it does not change because we lost the
# route to its host. Nulling it would replace a real finding
# ("this VM has no agent, that is why its storage is unknown")
# with "unknown" for the whole outage, and it would come back
# identical on the first cycle after recovery. os_type is held
# for the same reason and more strongly still: what a guest runs is
# part of its identity, it is read exactly once per VM (see
# _refresh_os_type), and clearing it here would both lose the
# OS icon on every VM of an unreachable host and force the
# config read again on recovery. This is the same
# judgement that keeps App.ip_cached, and it is a DELIBERATE
# difference from the app sweep above, which does null
# disk_total_bytes_cached: an app's allocation is only ever
# read back out of the same poll that measures its usage, so
# nothing there distinguishes the two. On a VM the allocation
# is what the VMs page draws the meter's denominator from, and
# blanking it turns "usage unknown" into "this VM has no
# memory and no disk".
#
# net_in_cached, net_out_cached and net_sampled_at are left
# exactly as they were, for the reason spelled out at length
# in the app sweep above: they are not readings shown to
# anyone, only the counters _update_net_rates diffs against,
# and that function already handles a stale sample correctly.
```

</details>

**after**

```
                # Held: cpu_cores, mem_total_bytes and disk_total_bytes are the
                # guest's configured allocation (maxcpu/maxmem/maxdisk), a fact
                # rather than a reading. guest_agent_ok is held for the same
                # reason even though it sits next to disk_bytes and comes from
                # the same call: nulling it would replace a real finding ("no
                # agent, that is why storage is unknown") with "unknown" for
                # the whole outage. os_type is held too, and it is read exactly
                # once per VM (see _refresh_os_type), so clearing it would lose
                # the OS icon and force the config read again on recovery.
                #
                # This is a DELIBERATE difference from the app sweep, which
                # does null disk_total_bytes_cached: an app's allocation is
                # only read back out of the same poll that measures its usage,
                # while on a VM the allocation is the meter's denominator, and
                # blanking it turns "usage unknown" into "this VM has no memory
                # and no disk".
                #
                # net_in_cached, net_out_cached and net_sampled_at are left as
                # they were, for the reason given in the app sweep.
```


### 🟢 KEEP (48), unchanged

- **`[46]`** `67` &middot; _data-integrity_ &middot; `# No cluster-wide `net` total here. It used to carry one, and because every`
- **`[47]`** `87` &middot; _surprising_ &middot; `# ponytail: exact normalized-name match only; fuzzier heuristics land with`
- **`[48]`** `189` &middot; _contract_ &middot; `# Stored bare, without the prefix length: this column is what the app card`
- **`[49]`** `259` &middot; _surprising_ &middot; `# No agent runs in a guest that is not running, so there is nothing to`
- **`[50]`** `264` &middot; _data-integrity_ &middot; `# Unknown, NOT False. A stopped guest cannot answer whatever it has`
- **`[51]`** `288` &middot; _surprising_ &middot; `# Recorded before the answer is looked at, on purpose: a VM with no agent`
- **`[52]`** `343` &middot; _external-quirk_ &middot; `# `or None` rather than the bare get: PVE omitting the key and PVE`
- **`[53]`** `350` &middot; _data-integrity_ &middot; `# How long a datastore has to stay out of the reads before it stops counting`
- **`[54]`** `386` &middot; _data-integrity_ &middot; `A SHARED datastore is reported once per node and is ONE pool; a LOCAL`
- **`[55]`** `427` &middot; _contract_ &middot; `# key -> (last measured at, used bytes, total bytes)`
- **`[56]`** `431` &middot; _contract_ &middot; `Fold this cycle's rows in and return every pool still counting.`
- **`[57]`** `435` &middot; _data-integrity_ &middot; `# Listed but unreadable. Not evidence of a zero-byte pool, so`
- **`[58]`** `463` &middot; _data-integrity_ &middot; `# `None` is a real, meaningful cluster_name: it means "standalone". So a`
- **`[59]`** `471` &middot; _data-integrity_ &middot; `# How long an app's CT must stay absent from cycles we are willing to trust`
- **`[60]`** `593` &middot; _data-integrity_ &middot; `# Per node, not just folded into the host-level sum below: two`
- **`[61]`** `636` &middot; _surprising_ &middot; `# No fallback to snap_nodes[0]. host.node_name is always set by the block`
- **`[62]`** `651` &middot; _data-integrity_ &middot; `# None means this cycle could not measure that metric: disk_pct`
- **`[63]`** `680` &middot; _data-integrity_ &middot; `# Cluster membership was written at enrolment and by nothing else, so`
- **`[64]`** `707` &middot; _external-quirk_ &middot; `# PVE reports 1 for a template and omits the key otherwise.`
- **`[65]`** `714` &middot; _surprising_ &middot; `# `disk` is USED, against `disk_bytes` above which is ALLOCATED.`
- **`[66]`** `735` &middot; _data-integrity_ &middot; `# An untrustworthy cycle leaves missing_since exactly as it was:`
- **`[67]`** `746` &middot; _concurrency_ &middot; `# Mid-action: leave the status alone and let the job's own result`
- **`[68]`** `755` &middot; _data-integrity_ &middot; `# 0 from PVE means "no reading", not "zero bytes used": a stopped`
- **`[69]`** `761` &middot; _external-quirk_ &middot; `# Follows the guest: a CT migrated in the Proxmox UI rather than through`
- **`[70]`** `766` &middot; _contract_ &middot; `# No `status` on this one: it is not a status change, and the`
- **`[71]`** `779` &middot; _data-integrity_ &middot; `# ponytail: no disk_pct SAMPLE for apps or VMs. Apps now cache a disk`
- **`[72]`** `808` &middot; _external-quirk_ &middot; `# Refreshed every cycle, not only on insert: a cluster migration moves`
- **`[73]`** `812` &middot; _external-quirk_ &middot; `# Refreshed every cycle: `qm template <id>` converts a guest in place,`
- **`[74]`** `815` &middot; _concurrency_ &middot; `# Mid-action: the status is the job's to write, not this cycle's. See`
- **`[75]`** `846` &middot; _surprising_ &middot; `# new Vm rows need ids before sampling`
- **`[76]`** `851` &middot; _surprising_ &middot; `# After the flush, not up in the upsert loop above: this one is keyed`
- **`[77]`** `893` &middot; _concurrency_ &middot; `# Audited because this is Proxploy deleting a user's record on its own`
- **`[78]`** `904` &middot; _surprising_ &middot; `# Node cards count apps per host (api/cluster.py::cluster_nodes) and`
- **`[79]`** `937` &middot; _contract_ &middot; `# host_id -> when its tokens were last checked against their roles. In`
- **`[80]`** `940` &middot; _data-integrity_ &middot; `# host_id -> when the RRD was last fetched, and the last answer. The`
- **`[81]`** `947` &middot; _contract_ &middot; `# host_id -> when MetricSample rows were last written for it.`
- **`[82]`** `949` &middot; _data-integrity_ &middot; `# host_id -> the datastore sizes disk_pct divides by. Has to outlive a`
- **`[83]`** `953` &middot; _contract_ &middot; `# host_id -> {app_id: when its address was last read}. Same shape and`
- **`[84]`** `961` &middot; _concurrency_ &middot; `# host_id -> "poll this host now" flag, set by wake(). One Event per`
- **`[85]`** `1000` &middot; _concurrency_ &middot; `Evaluate, publish on the loop, notify off it.`
- **`[86]`** `1096` &middot; _concurrency_ &middot; `# The backoff owns the delay while this host is failing. A wake`
- **`[87]`** `1110` &middot; _concurrency_ &middot; `Blocking: one full cycle for one host. Runs in a worker thread.`
- **`[88]`** `1170` &middot; _external-quirk_ &middot; `# Optional, like rrddata above: a token that reads`
- **`[89]`** `1179` &middot; _contract_ &middot; `# Optional in exactly the way version() above is: one extra`
- **`[90]`** `1190` &middot; _surprising_ &middot; `# Privilege drift, on a slow cadence (see the interval above). Best`
- **`[91]`** `1219` &middot; _concurrency_ &middot; `# ingest_cycle owns status/last_seen_at, so this is set after it and`
- **`[92]`** `1271` &middot; _surprising_ &middot; `# Written even when the status is unchanged: the reason can change`
- **`[93]`** `1298` &middot; _data-integrity_ &middot; `# A stale reading here is the same lie a stale "running" is:`

---

## `backend/proxploy/services/proxmox.py`

5,003 → 4,283 words, 14% cut. 6 delete, 22 shorten, 77 keep.


### 🔴 DELETE (6)

**`[94]`** `backend/proxploy/services/proxmox.py:1018` &middot; 5w &middot; _separator_  
Banner line with a task number.

```
# --- backups (Phase 6 Task 9) --------------------------------------------
```

**`[95]`** `backend/proxploy/services/proxmox.py:1076` &middot; 4w &middot; _separator_  
Banner line with a phase number.

```
# --- console/terminal calls (Phase 5) -----------------------------------
```

**`[96]`** `backend/proxploy/services/proxmox.py:1356` &middot; 5w &middot; _separator_  
Banner line with a phase and task number.

```
# --- snapshots (Phase 6, Task 10) ---------------------------------------
```

**`[97]`** `backend/proxploy/services/proxmox.py:1422` &middot; 5w &middot; _separator_  
Banner line with a phase and task number.

```
# --- migration (Phase 8 Task 14/15) --------------------------------------
```

**`[98]`** `backend/proxploy/services/proxmox.py:1477` &middot; 6w &middot; _separator_  
Banner line with a phase number.

```
# --- guest create / clone / destroy (Phase 6) ---------------------------
```

**`[99]`** `backend/proxploy/services/proxmox.py:1520` &middot; 5w &middot; _separator_  
Banner line with a phase number.

```
# --- storage content mutations (Phase 6) --------------------------------
```


### 🟡 SHORTEN (22)

**`[100]`** `backend/proxploy/services/proxmox.py:44` &middot; **140w → 128w** (9% cut) &middot; _security_  
Keeps the whole trust argument, the wide-user-class decision and the structural guarantee, stated once.

<details><summary>before</summary>

```
# The submitted token id is OPAQUE AND SECRET on ingest: Proxmox's own copy
# button yields `PVEAPIToken=user@realm!name=<uuid-secret>`, so any caller
# string may be carrying a credential. Nothing derived from it is stored in the
# clear except what this regex names: user, realm and token name, re-joined by
# token_public_meta() below. A previous fix banned "=": a denylist, and
# denylists in this codebase have failed twice already (notifier.kind_for).
#
# The user class is deliberately WIDE: LDAP/AD logins legitimately carry spaces
# and non-ASCII, and rejecting them broke real onboarding. What keeps the secret
# unrepresentable is structural, not a character blacklist: the three
# separators "=", "@" and "!" cannot appear inside any component, so a string
# rebuilt as `user@realm!name` can never carry the `=<secret>` half no matter
# how wide the user class gets. Control characters (\x00-\x1f, \x7f) stay out
# because they are header-injection shaped, not because they hide a secret.
```

</details>

**after**

```
# The submitted token id is OPAQUE AND SECRET on ingest: Proxmox's own copy
# button yields `PVEAPIToken=user@realm!name=<uuid-secret>`, so any caller
# string may be carrying a credential. Nothing derived from it is stored in the
# clear except what this regex names: user, realm and token name, re-joined by
# token_public_meta() below. A previous fix banned "=": a denylist, and
# denylists in this codebase have failed twice already.
#
# The user class is deliberately WIDE: LDAP/AD logins legitimately carry spaces
# and non-ASCII, and rejecting them broke real onboarding. What keeps the
# secret unrepresentable is structural: "=", "@" and "!" cannot appear inside
# any component, so a string rebuilt as `user@realm!name` can never carry the
# `=<secret>` half however wide the user class gets. Control characters stay
# out because they are header-injection shaped, not because they hide a secret.
```

**`[101]`** `backend/proxploy/services/proxmox.py:113` &middot; **141w → 136w** (4% cut) &middot; _security_  
Keeps the trust boundary, what is deliberately allowed and the loopback hatch, with the padding removed.

<details><summary>before</summary>

```
# Onboarding hands us an operator-supplied address and we open a socket to it, 
# with CERT_NONE, on the fingerprint path: and the outcome (success, failure,
# latency, the returned fingerprint) comes back to the caller. That is an SSRF
# primitive unless the target class is constrained.
#
# RFC1918 and IPv6 unique-local are DELIBERATELY ALLOWED and always will be:
# this is a self-hosted LAN product and a node on 192.168.x.x / 10.x.x.x is the
# normal case, not the attack. Only classes that are never a Proxmox node and
# are dangerous to reach are refused: chiefly link-local, which is where cloud
# instance metadata lives (169.254.169.254).
#
# Loopback is refused by default but is a legitimate target when Proxploy runs
# on the PVE node itself, so it has an opt-in escape hatch. Read at import so a
# test can flip the module attribute; an operator sets the env var.
```

</details>

**after**

```
# Onboarding hands us an operator-supplied address and we open a socket to it,
# with CERT_NONE on the fingerprint path, and the outcome (success, failure,
# latency, the returned fingerprint) comes back to the caller. That is an SSRF
# primitive unless the target class is constrained.
#
# RFC1918 and IPv6 unique-local are DELIBERATELY ALLOWED and always will be:
# this is a self-hosted LAN product and a node on 192.168.x.x is the normal
# case, not the attack. Only classes that are never a Proxmox node and are
# dangerous to reach are refused, chiefly link-local, where cloud instance
# metadata lives (169.254.169.254).
#
# Loopback is refused by default but is legitimate when Proxploy runs on the
# PVE node itself, so it has an opt-in escape hatch. Read at import so a test
# can flip the module attribute; an operator sets the env var.
```

**`[102]`** `backend/proxploy/services/proxmox.py:204` &middot; **171w → 123w** (28% cut) &middot; _buried-invariant_  
Keeps why matching lives here, what never reaches it, and that the 403 handling is generic; cuts the bug narrative and the report filename.

<details><summary>before</summary>

```
Map an underlying transport/auth failure onto a kind the UI can act on.
    Substring matching is deliberate and lives HERE rather than in the
    frontend: proxmoxer and requests do not expose typed failures for these,
    and one fuzzy match in one place beats the same match spread across
    call sites in another language.

    Only reached from `_wrap`, i.e. for exceptions proxmoxer/requests raised
    that we did not construct ourselves. `resolve_target`'s SSRF refusals and
    `_connect`'s TLS-fingerprint mismatch are already `ProxmoxError`s raised
    with an explicit `kind` at the point they are known, self-classifying,
    so they never reach here and this function does not need to recognize
    them.

    A 403 ("permission") used to fall all the way through to "unknown",
    indistinguishable from a dead node or a broken cert; that is the literal
    bug the Sys.PowerMgmt gap surfaced as a bare 502 (see
    node-power-privilege-report.md). It is not special to node power: ANY
    call a token is too narrow for lands here the same way, so the fix is
    generic, not a second node_power-shaped special case.
    
```

</details>

**after**

```
    """Map an underlying transport/auth failure onto a kind the UI can act on.

    Substring matching is deliberate and lives HERE rather than in the
    frontend: proxmoxer and requests expose no typed failures for these, and
    one fuzzy match in one place beats the same match spread across call sites
    in another language.

    Only reached from `_wrap`, for exceptions proxmoxer/requests raised that we
    did not construct. `resolve_target`'s SSRF refusals and `_connect`'s
    TLS-fingerprint mismatch already carry an explicit `kind`, so they never
    reach here.

    A 403 ("permission") used to fall through to "unknown", indistinguishable
    from a dead node or a broken cert. ANY call a token is too narrow for lands
    here the same way, so the handling is generic, not a node_power special
    case.
    """
```

**`[103]`** `backend/proxploy/services/proxmox.py:259` &middot; **74w → 66w** (11% cut) &middot; _contract_  
Keeps the drop rule and the layering constraint; drops the note about where it started.

<details><summary>before</summary>

```
The addresses off one ProxmoxClient.lxc_interfaces() row that can
    actually be reached, in CIDR form ("192.168.50.179/24").

    Loopback and IPv6 link-local are dropped: every container has both on
    every interface and neither one opens a web UI. Same rule
    ProxmoxClient.agent_addresses applies to a VM's agent answer.

    Lives here beside lxc_interfaces rather than in api/network.py, where it
    started, because the poller wants the same rule and the poller must not
    import the API layer to get it.
    
```

</details>

**after**

```
    """The addresses off one ProxmoxClient.lxc_interfaces() row that can
    actually be reached, in CIDR form ("192.168.50.179/24").

    Loopback and IPv6 link-local are dropped: every container has both on every
    interface and neither opens a web UI. Same rule
    ProxmoxClient.agent_addresses applies to a VM's agent answer.

    Lives here rather than in api/network.py because the poller wants the same
    rule and must not import the API layer to get it.
    """
```

**`[104]`** `backend/proxploy/services/proxmox.py:293` &middot; **80w → 63w** (21% cut) &middot; _external-quirk_  
Keeps the quirk and the verification; drops the doc open-question aside.

<details><summary>before</summary>

```
`Authorization` value for the two console websocket endpoints, the
        only PVE calls that do not go through proxmoxer (which sets this
        header itself on every REST request).

        PVE authenticates the vncwebsocket UPGRADE, not just the termproxy POST
        that precedes it. Without this header the upgrade is rejected
        `401 No ticket` on every real node, whatever the ticket says. Verified
        working for lxc on PVE 9.2.6 (2026-08-10), which also settles doc 11's
        open question about bugzilla #6079 for the LXC path.
        
```

</details>

**after**

```
        """`Authorization` value for the two console websocket endpoints, the
        only PVE calls that do not go through proxmoxer (which sets this header
        itself on every REST request).

        PVE authenticates the vncwebsocket UPGRADE, not just the termproxy POST
        before it. Without this header the upgrade is rejected `401 No ticket`
        on every real node, whatever the ticket says. Verified for lxc on PVE
        9.2.6.
        """
```

**`[105]`** `backend/proxploy/services/proxmox.py:306` &middot; **145w → 102w** (30% cut) &middot; _security_  
Keeps every sink and the kind contract; trims the node_power example around them.

<details><summary>before</summary>

```
The ONE place a proxmoxer/requests exception becomes our own.

        `str(e)` is third-party text we do not control, and urllib3 in
        particular interpolates the whole `Authorization` header value into
        `InvalidHeader`. Every wrapped message below flows outward, to a 502
        `detail` (api/hosts.py), to the unencrypted `jobs.error` column and its
        SSE stream (jobs/backend.py::_finish), and to `job_events.message`; so
        the credential is scrubbed here rather than at each of those sinks.

        `kind` lets a caller that already knows more than `_classify` can
        guess from the raw text (e.g. node_power's own 403 detection below)
        say so directly, instead of `_classify` re-deriving a coarser answer.
        A caller-supplied `kind` also means the caller is handing back its
        own bespoke sentence already, so the generic permission-detail
        sentence below is skipped for it: node_power's message stays exactly
        what it is, the generic path exists for every OTHER call site that
        does not (yet) hand-write one.
        
```

</details>

**after**

```
        """The ONE place a proxmoxer/requests exception becomes our own.

        `str(e)` is third-party text we do not control, and urllib3 in
        particular interpolates the whole `Authorization` header value into
        `InvalidHeader`. Every wrapped message flows outward, to a 502 `detail`
        (api/hosts.py), to the unencrypted `jobs.error` column and its SSE
        stream, and to `job_events.message`, so the credential is scrubbed here
        rather than at each of those sinks.

        `kind` lets a caller that already knows more than `_classify` can guess
        say so directly. A caller-supplied `kind` also means the caller is
        handing back its own sentence, so the generic permission-detail
        sentence below is skipped for it.
        """
```

**`[106]`** `backend/proxploy/services/proxmox.py:334` &middot; **37w → 29w** (22% cut) &middot; _redundant_  
The _wrap docstring already explains the caller-supplied kind; only the no-bare-502 rule is new here.

<details><summary>before</summary>

```
# Generalizes node_power's own fix to every call site: a 403 is
# never again a bare, unlabelled 502 -- it says which privilege
# PVE wanted, using PVE's own text as the source of truth rather
# than a per-call-site guess.
```

</details>

**after**

```
            # A 403 is never again a bare, unlabelled 502: it says which
            # privilege PVE wanted, using PVE's own text as the source of
            # truth rather than a per-call-site guess.
```

**`[107]`** `backend/proxploy/services/proxmox.py:430` &middot; **229w → 142w** (38% cut) &middot; _external-quirk_  
Keeps the None-not-UPID quirk, the danger and the Sys.PowerMgmt meaning; tightens the framing around them.

<details><summary>before</summary>

```
POST /nodes/{node}/status?command=reboot|shutdown -> None, usually.

        Returns None, NOT a UPID, and that is Proxmox's design, not a failure:
        PVE::API2::Nodes's node_cmd runs the reboot/shutdown straight out of
        the request handler (`returns => { type => "null" }`) instead of
        forking a task the way vzdump, migrate and every guest action do. A
        node on its way down cannot host the worker that would write that
        task's log, so there is nothing for a UPID to point at.

        Every other POST on this client hands back a UPID, so the caller has
        to be told; the annotation says `str | None` rather than `None`
        because this only promises to relay what Proxmox sends, and a future
        PVE that did mint a task here would come straight through.

        The host actions menu's Reboot/Power off. Deliberately separate from
        guest_action: this acts on the NODE, not a guest, so it is gated far
        harder by callers (doc 02 §9, doc 08 §1) -- it can take down every
        guest the node hosts, and if the node is the one Proxploy itself runs
        on, Proxploy along with it.

        A 403 here almost always means one specific thing: the token lacks
        Sys.PowerMgmt, which pveum.py never granted before this privilege
        existed (doc 08 §2/§9). A bare relay of Proxmox's "Permission check
        failed" left the operator to work that out alone; named explicitly
        instead, with where to grant it, while keeping Proxmox's own text too.
        
```

</details>

**after**

```
        """POST /nodes/{node}/status?command=reboot|shutdown -> None, usually.

        Returns None, NOT a UPID, and that is Proxmox's design, not a failure:
        PVE::API2::Nodes's node_cmd runs the reboot/shutdown straight out of
        the request handler (`returns => { type => "null" }`) instead of
        forking a task. A node on its way down cannot host the worker that
        would write that task's log. The annotation says `str | None` because
        this only relays what Proxmox sends, and a future PVE that did mint a
        task here would come straight through.

        Deliberately separate from guest_action: this acts on the NODE, so
        callers gate it far harder. It can take down every guest on the node,
        and Proxploy itself if it runs there.

        A 403 here almost always means the token lacks Sys.PowerMgmt, which
        pveum.py never granted before this privilege existed. It is named
        explicitly below, with where to grant it, keeping Proxmox's own text
        too.
        """
```

**`[108]`** `backend/proxploy/services/proxmox.py:484` &middot; **60w → 52w** (13% cut) &middot; _separator_  
Drops the banner line; the on-demand rule and the per-call refusal behaviour are real constraints.

<details><summary>before</summary>

```
# --- the rest of the host page's hardware tab ---------------------------
# All on demand, never from the poll loop (doc 02 §3 caps a cycle at
# O(nodes)), and every one of them is refusable on its own: a token without
# Sys.Audit answers some and rejects others, and a PVE without the path
# 501s. Callers gather them independently so one refusal costs one section.
```

</details>

**after**

```
    # All on demand, never from the poll loop (doc 02 §3 caps a cycle at
    # O(nodes)), and every one of them is refusable on its own: a token without
    # Sys.Audit answers some and rejects others, and a PVE without the path
    # 501s. Callers gather them independently so one refusal costs one section.
```

**`[109]`** `backend/proxploy/services/proxmox.py:546` &middot; **28w → 25w** (11% cut) &middot; _separator_  
Drops the banner line; the budget exemption is the real content.

<details><summary>before</summary>

```
# --- per-guest, user-triggered calls -----------------------------------
# Doc 02 §3 forbids per-guest calls in the POLL LOOP; these are triggered by
# a human clicking a button and are explicitly outside that budget.
```

</details>

**after**

```
    # Doc 02 §3 forbids per-guest calls in the POLL LOOP; these are triggered
    # by a human clicking a button and are explicitly outside that budget.
```

**`[110]`** `backend/proxploy/services/proxmox.py:565` &middot; **159w → 100w** (37% cut) &middot; _external-quirk_  
Keeps the always-None return, the PVE source for it and the `delete` parameter trap; cuts the account of the old wrong docstring.

<details><summary>before</summary>

```
PUT /nodes/{node}/{lxc|qemu}/{vmid}/config -> nothing.

        NOT long-running, and it never hands back a task id. PVE routes the
        PUT to `update_vm_api($param, 1)`, the synchronous half, whose schema
        declares `returns => { type => 'null' }`; only the POST on the same
        path is the asynchronous half that returns a UPID. Read off the
        node's own PVE/API2/Qemu.pm, pve-manager 9.2.11, 2026-08-20.

        This used to be documented as "UPID for a running qemu guest, None
        otherwise", and callers derived "did this land in the pending section"
        from it. That value is ALWAYS None, so every such caller reported
        "applied immediately" no matter what actually happened. Whether a
        change is waiting for a restart is a question only the guest's
        pending config can answer: call `guest_pending` after the write.

        `delete` is a real PVE parameter here, not a pseudo-key: pass
        `{"delete": "acpi,kvm"}` to REMOVE those settings, which is how a
        setting goes back to the Proxmox default. Writing the default value
        instead pins it, which is a different thing.
        
```

</details>

**after**

```
        """PUT /nodes/{node}/{lxc|qemu}/{vmid}/config -> nothing.

        NOT long-running, and it never hands back a task id. PVE routes the PUT
        to `update_vm_api($param, 1)`, the synchronous half, whose schema
        declares `returns => { type => 'null' }`; only the POST on the same
        path is the asynchronous half that returns a UPID (PVE/API2/Qemu.pm,
        pve-manager 9.2.11). So nothing here can tell a caller whether a change
        landed in the pending section: ask `guest_pending` after the write.

        `delete` is a real PVE parameter, not a pseudo-key: pass
        `{"delete": "acpi,kvm"}` to REMOVE those settings, which is how one
        goes back to the Proxmox default. Writing the default value pins it
        instead.
        """
```

**`[111]`** `backend/proxploy/services/proxmox.py:593` &middot; **153w → 130w** (15% cut) &middot; _external-quirk_  
Keeps the row shape, the reduction rule and the stopped-guest answer; tightens the wording.

<details><summary>before</summary>

```
GET /nodes/{node}/{lxc|qemu}/{vmid}/pending, reduced to the changes.

        PVE answers with one row per config key, `{key, value}`, where `value`
        is what the guest is running on right now. A row grows a `pending` key
        when a new value is waiting for the guest's next boot, and a `delete`
        key when the waiting change is a removal. Rows with neither are just
        the current config restated, so they are dropped here.

        -> {key: pending value}, with None where the pending change is a
        removal (the setting goes back to its Proxmox default at next boot).
        An empty dict therefore means "nothing is waiting", which is the
        answer for every stopped guest: PVE applies a write to a stopped guest
        straight away and has no pending section to file it under.

        Confirmed against both guest types on pve-manager 9.2.11, 2026-08-20;
        lxc has this endpoint too, so the NIC editor's qemu/lxc split does not
        need two code paths.
        
```

</details>

**after**

```
        """GET /nodes/{node}/{lxc|qemu}/{vmid}/pending, reduced to the changes.

        PVE answers with one row per config key, `{key, value}`, where `value`
        is what the guest is running on right now. A row grows a `pending` key
        when a new value waits for the next boot, and a `delete` key when the
        waiting change is a removal. Rows with neither restate the current
        config and are dropped here.

        -> {key: pending value}, with None where the pending change is a
        removal. An empty dict means "nothing is waiting", which is the answer
        for every stopped guest: PVE applies a write to a stopped guest
        straight away and has no pending section to file it under.

        Confirmed on both guest types, pve-manager 9.2.11: lxc has this
        endpoint too, so the NIC editor needs no qemu/lxc split.
        """
```

**`[112]`** `backend/proxploy/services/proxmox.py:621` &middot; **31w → 24w** (23% cut) &middot; _separator_  
Drops the banner and the task number; the staging behaviour is the real content.

<details><summary>before</summary>

```
# --- host network staging (Phase 6 Task 7) -------------------------------
# PVE writes every one of the three staging calls below into
# /etc/network/interfaces.new and touches NOTHING live. Only network_apply
# promotes that file. network_revert deletes it.
```

</details>

**after**

```
    # PVE writes every one of the three staging calls below into
    # /etc/network/interfaces.new and touches NOTHING live. Only network_apply
    # promotes that file. network_revert deletes it.
```

**`[113]`** `backend/proxploy/services/proxmox.py:678` &middot; **96w → 95w** (1% cut) &middot; _separator_  
Drops the banner line; the shared-schema design and the measured scope availability both stay.

<details><summary>before</summary>

```
# ---- Firewall
#
# Four scopes share one rule schema, so they share one set of methods and
# differ only in which proxmoxer node they hang off. `loc` is built by
# services/firewall.py, which is also the only place that decides a caller
# is allowed to name a given scope.
#
# Measured on pve-manager 9.2.11, 2026-08-21: aliases and ipset exist at
# cluster and guest scope only, groups at cluster only, log at node and
# guest only. This class does not enforce that; a caller asking a scope for
# an object it does not have gets PVE's own 501, which says so.
```

</details>

**after**

```
    # Four scopes share one rule schema, so they share one set of methods and
    # differ only in which proxmoxer node they hang off. `loc` is built by
    # services/firewall.py, which is also the only place that decides a caller
    # is allowed to name a given scope.
    #
    # Measured on pve-manager 9.2.11, 2026-08-21: aliases and ipset exist at
    # cluster and guest scope only, groups at cluster only, log at node and
    # guest only. This class does not enforce that; a caller asking a scope
    # for an object it does not have gets PVE's own 501, which says so.
```

**`[114]`** `backend/proxploy/services/proxmox.py:885` &middot; **121w → 92w** (24% cut) &middot; _security_  
Keeps the escaping bug, the safe="" reason and the `..` case the route must also refuse.

<details><summary>before</summary>

```
One URL PATH segment, escaped, because proxmoxer joins segments with
        posixpath.join and quotes none of them.

        Written for a member's CIDR: unescaped, `10.0.0.0/8` splits the path
        and PVE answers 404 on every member read, update and delete. `safe=""`
        because the default leaves `/` alone, which is the whole bug.

        Now also used for every alias, IP set and security group NAME, which
        had exactly the same shape of hole and no escaping at all. Note that
        quoting alone cannot save a name of `..` (a dot is unreserved, so it
        survives quoting and still means "the parent endpoint"), which is why
        api/firewall.py::ObjectName refuses one at the route as well. This is
        the second half of that: one mechanism, both places it is needed.
        
```

</details>

**after**

```
        """One URL PATH segment, escaped, because proxmoxer joins segments with
        posixpath.join and quotes none of them.

        Written for a member's CIDR: unescaped, `10.0.0.0/8` splits the path
        and PVE answers 404 on every member read, update and delete. `safe=""`
        because the default leaves `/` alone, which is the whole bug.

        Also used for every alias, IP set and security group NAME, which had
        the same hole. Quoting alone cannot save a name of `..` (a dot is
        unreserved and still means "the parent endpoint"), which is why
        api/firewall.py::ObjectName refuses one at the route as well.
        """
```

**`[115]`** `backend/proxploy/services/proxmox.py:1097` &middot; **241w → 183w** (24% cut) &middot; _security_  
Keeps the whole trust argument for generate-password; folds the decoded RFB dump into one clause.

<details><summary>before</summary>

```
POST /nodes/{node}/qemu/{vmid}/vncproxy (websocket=1, generate-password=1)
        -> {user, ticket, port, cert, upid, password}.

        `generate-password=1` is not optional decoration. QEMU's VNC server
        offers exactly one RFB security type on this cluster, type 2 (VNC
        Authentication), so an RFB client that presents no password cannot
        finish the handshake at all. Decoded off a live PVE 9.2.10 node:

            greeting            b"RFB 003.008\n"
            security types      b"\x01\x02"   (count 1, type 2)

        Unlike the termproxy path, nothing in the bridge can supply that
        password on the browser's behalf: services/consoleproxy.py is a byte
        relay by design and the RFB challenge/response is end to end between
        QEMU and the browser. So the password has to reach the browser, and
        this parameter is what decides HOW MUCH reaches it.

        Without it, PVE's answer carries the vncticket only, and the VNC
        password is that ticket (RFB truncates a password to 8 bytes, and
        PVE builds the ticket so its first 8 bytes are the password). Handing
        the browser the whole ticket would hand it the credential that
        authenticates the /vncwebsocket upgrade to PVE directly, which is a
        real widening: the browser could then talk to Proxmox without going
        through Proxploy at all.

        With it, PVE returns a separate 8 character `password` field, and the
        rest of the ticket stays server side. The browser gets a secret that
        is only good for answering one VNC challenge on one already-bridged
        socket. Same thing Proxmox's own UI ends up holding, minus the part
        that talks to the API.
        
```

</details>

**after**

```
        """POST /nodes/{node}/qemu/{vmid}/vncproxy (websocket=1, generate-password=1)
        -> {user, ticket, port, cert, upid, password}.

        `generate-password=1` is not optional decoration. QEMU's VNC server
        offers exactly one RFB security type on this cluster, type 2 (VNC
        Authentication), decoded off a live PVE 9.2.10 node, so a client that
        presents no password cannot finish the handshake.

        Nothing in the bridge can supply it on the browser's behalf:
        services/consoleproxy.py is a byte relay and the RFB
        challenge/response is end to end between QEMU and the browser. So the
        password must reach the browser, and this parameter decides how much.

        Without it, PVE returns the vncticket only, and the VNC password IS
        that ticket (RFB truncates to 8 bytes, and PVE builds the ticket so its
        first 8 bytes are the password). Handing the browser the whole ticket
        hands it the credential that authenticates the /vncwebsocket upgrade to
        PVE directly, so it could talk to Proxmox without going through
        Proxploy at all. With it, PVE returns a separate 8 character `password`
        and the rest of the ticket stays server side: a secret good only for
        one VNC challenge on one already-bridged socket.
        """
```

**`[116]`** `backend/proxploy/services/proxmox.py:1136` &middot; **24w → 20w** (17% cut) &middot; _separator_  
Drops the banner line; the poll-loop exemption is the real content.

<details><summary>before</summary>

```
# --- infra reads (Phase 6) ----------------------------------------------
# All read-only, all on-demand: nothing here is called from the poll loop,
# so doc 02 §3's O(nodes) budget is untouched.
```

</details>

**after**

```
    # All read-only, all on-demand: nothing here is called from the poll loop,
    # so doc 02 §3's O(nodes) budget is untouched.
```

**`[117]`** `backend/proxploy/services/proxmox.py:1184` &middot; **138w → 122w** (12% cut) &middot; _external-quirk_  
Keeps why the agent is the only honest source and what None means; tightens the wording.

<details><summary>before</summary>

```
The addresses a VM's guest agent says it actually has, or None.

        None means "cannot tell", and the two reasons are not worth telling
        apart to a caller: the agent is not installed, or it is installed and not
        running. Either way Proxploy has no truthful answer, and None is what the
        UI renders as unknown rather than as "no address".

        This is the only honest read of a VM's address. PVE keeps a container's
        address on its netN string, so that one is a config read, but a VM's
        address lives inside the guest: `ipconfigN` is a cloud-init datasource,
        which a Windows guest ignores entirely unless Cloudbase-Init is installed
        (see api/network.py::ADDRESS_KEYS). Asking the guest is the difference
        between reporting what is and reporting what was requested.

        Loopback is dropped: every guest has 127.0.0.1 and it answers nothing.
        
```

</details>

**after**

```
        """The addresses a VM's guest agent says it actually has, or None.

        None means "cannot tell", and the two reasons (no agent, or an agent
        installed and not running) are not worth telling a caller apart: either
        way there is no truthful answer, and None renders as unknown rather
        than as "no address".

        This is the only honest read of a VM's address. PVE keeps a
        container's address on its netN string, but a VM's address lives inside
        the guest: `ipconfigN` is a cloud-init datasource, which a Windows
        guest ignores entirely unless Cloudbase-Init is installed (see
        api/network.py::ADDRESS_KEYS). Asking the guest is the difference
        between reporting what is and what was requested.

        Loopback is dropped: every guest has 127.0.0.1 and it answers nothing.
        """
```

**`[118]`** `backend/proxploy/services/proxmox.py:1225` &middot; **534w → 327w** (39% cut) &middot; _external-quirk_  
Keeps the three-valued contract, the dedupe rule and the (True, None) case; cuts the rename history and the repeated cost argument.

<details><summary>before</summary>

```
One get-fsinfo call, two facts: (agent answered?, bytes used).

        Was agent_disk_used() and returned the bytes alone. It is widened
        rather than paired with a sibling call because the two facts come out
        of the SAME request and always agreed anyway: whether a guest agent is
        installed and answering is exactly what "we could not read the
        filesystems" already knew and threw away. A second endpoint (ping, or
        the config's `agent:` line) would be a second per-VM call every cycle
        for an answer we are holding in our hand. Per-cycle cost is therefore
        unchanged: still one call, still on the caller's cadence.

        Why the bytes are needed at all: the hypervisor can only see a block
        device, not the filesystem inside it. /cluster/resources' `disk` field
        is meaningful for a container and is routinely a flat 0 for a QEMU
        guest (measured on the lab cluster, PVE 9.2.10, 2026-08-20: VM 108
        running, 32 GiB allocated, `disk: 0`). Only the guest can answer.

        The first element is deliberately THREE-valued, and keeping the three
        apart is the whole point of returning it:

          * True: the agent answered. Whatever came back is a real answer,
            even if nothing in it was usable.
          * False: Proxmox told us this guest has no working agent. The lab VM
            answers `500 Internal Server Error: No QEMU guest agent
            configured`, and a guest whose config declares an agent that is
            not running inside it answers `QEMU guest agent is not running`.
            Both are Proxmox reporting on the agent, which is a real finding
            an operator can act on, not a fault of ours.
          * None: we could not ask. Any other failure (the node refused the
            connection, the token lost its permission, a timeout) says nothing
            about the guest, and reporting "no agent" off the back of a
            network error would be a lie that sticks.

        The split is made on the error text because that is the only thing PVE
        gives us: every one of these arrives as a 500 with a message, so the
        status code cannot separate them. Matching on "guest agent" is loose
        on purpose, since it catches both of PVE's wordings above and anything
        else it says specifically about the agent, and a message that never
        mentions the agent is by definition not PVE answering about it.

        Summing: one entry per mounted filesystem, deduped on the guest's own
        device name (`name`, e.g. "sda1"), because a bind mount and every
        subvolume of one btrfs pool report the SAME filesystem more than once
        and adding those up counts the same bytes twice. Falls back to the
        mountpoint when an agent omits the name, which at worst double-counts
        the case the dedupe was meant to catch and never invents storage that
        is not there. An entry with no `used-bytes` is skipped rather than
        counted as zero (some filesystems make qemu-ga omit it).

        An agent that answers with nothing usable returns (True, None), not
        (True, 0): a VM whose every filesystem was skipped has not been
        measured, and 0 would draw an empty disk bar under a full one. That
        pair is also the case the old single return could not express, since
        it collapsed "no agent" and "no usable answer" into the same None.
        
```

</details>

**after**

```
        """One get-fsinfo call, two facts: (agent answered?, bytes used).

        Both come out of the SAME request: whether the agent is installed and
        answering is what "we could not read the filesystems" already knew. A
        second endpoint (ping, or the config's `agent:` line) would be a second
        per-VM call every cycle for an answer we already hold.

        Why the bytes are needed at all: the hypervisor sees a block device,
        not the filesystem inside it, so /cluster/resources' `disk` is
        routinely a flat 0 for a QEMU guest (lab cluster, PVE 9.2.10: VM 108
        running, 32 GiB allocated, `disk: 0`). Only the guest can answer.

        The first element is deliberately THREE-valued:

          * True: the agent answered, even if nothing in the answer was usable.
          * False: Proxmox told us this guest has no working agent (`No QEMU
            guest agent configured`, or `QEMU guest agent is not running`).
            That is a real finding an operator can act on, not a fault of ours.
          * None: we could not ask. Any other failure (the node refused the
            connection, the token lost its permission, a timeout) says nothing
            about the guest, and reporting "no agent" off a network error would
            be a lie that sticks.

        The split is made on the error text because every one of these arrives
        as a 500 with a message, so the status code cannot separate them.
        Matching on "guest agent" is loose on purpose: a message that never
        mentions the agent is by definition not PVE answering about it.

        Summing: one entry per mounted filesystem, deduped on the guest's own
        device name (`name`, e.g. "sda1"), because a bind mount and every
        subvolume of one btrfs pool report the SAME filesystem more than once.
        Falls back to the mountpoint when the name is missing. An entry with no
        `used-bytes` is skipped rather than counted as zero.

        An agent that answers with nothing usable returns (True, None), not
        (True, 0): 0 would draw an empty disk bar under a full one.
        """
```

**`[119]`** `backend/proxploy/services/proxmox.py:1301` &middot; **139w → 115w** (17% cut) &middot; _external-quirk_  
Keeps the config-versus-lease point, the measurement and the None case; tightens the rest.

<details><summary>before</summary>

```
What a RUNNING container's interfaces actually are, or None.

        The counterpart to agent_addresses() for VMs, and the answer to the
        same question: a config read reports what was REQUESTED, and for a
        container on DHCP that is the literal word `dhcp`. PVE does know the
        lease, and this is where it keeps it. No guest agent involved: the
        container shares the host kernel, so the node can read its namespace
        directly. Measured on PVE 9.2.10, 2026-08-20: a CT whose config says
        `ip=dhcp` answers here with `eth0 ... inet 192.168.50.179/24`, and the
        hwaddr matches the config's own.

        None means cannot tell, which is the ordinary case for a STOPPED
        container: there are no interfaces to report and PVE errors rather
        than answering empty. Swallowed for the same reason agent_addresses
        swallows its own: not being able to ask is not an outage.
        
```

</details>

**after**

```
        """What a RUNNING container's interfaces actually are, or None.

        The counterpart to agent_addresses() for VMs, and the answer to the
        same question: a config read reports what was REQUESTED, and for a
        container on DHCP that is the literal word `dhcp`. PVE knows the lease
        and keeps it here. No guest agent involved: the container shares the
        host kernel, so the node reads its namespace directly. Measured on PVE
        9.2.10: a CT whose config says `ip=dhcp` answers here with
        `eth0 ... inet 192.168.50.179/24`.

        None means cannot tell, the ordinary case for a STOPPED container:
        there are no interfaces to report and PVE errors rather than answering
        empty. Swallowed for the same reason agent_addresses swallows its own.
        """
```

**`[120]`** `backend/proxploy/services/proxmox.py:1524` &middot; **98w → 80w** (18% cut) &middot; _external-quirk_  
Keeps the .name quirk and the isinstance requirement; trims the cross-reference.

<details><summary>before</summary>

```
POST /nodes/{node}/storage/{storage}/upload -> UPID.

        `path` is a spooled temp file on the Proxploy host, opened here and
        streamed by proxmoxer as the multipart part, the bytes are never held
        in memory by us (see api/storage.py's upload route for the other half).

        proxmoxer/requests derive the multipart part's filename from the file
        object's `.name` (`requests.utils.guess_filename`), but a plain
        `open()` result exposes `.name` read-only as the spool path's own
        basename, assigning to it raises `AttributeError`. `_NamedUpload`
        wraps the raw stream so `.name` reports the ISO's real filename
        instead, while still passing `isinstance(_, io.IOBase)` so proxmoxer's
        streaming-multipart path (large-file handling) still kicks in.
        
```

</details>

**after**

```
        """POST /nodes/{node}/storage/{storage}/upload -> UPID.

        `path` is a spooled temp file on the Proxploy host, opened here and
        streamed by proxmoxer as the multipart part; the bytes are never held
        in memory by us.

        proxmoxer/requests derive the part's filename from the file object's
        `.name`, but a plain `open()` exposes `.name` read-only as the spool
        path's basename. `_NamedUpload` wraps the raw stream so `.name` reports
        the ISO's real filename while still passing `isinstance(_, io.IOBase)`,
        which is what keeps proxmoxer's streaming-multipart path in play.
        """
```

**`[121]`** `backend/proxploy/services/proxmox.py:1562` &middot; **102w → 97w** (5% cut) &middot; _separator_  
Drops the banner line; the cluster-scope, synchronous and credential handling notes are all real.

<details><summary>before</summary>

```
# --- storage definition management (Phase 6) ----------------------------
# These three hit the CLUSTER-level /storage endpoints, not /nodes/{n}/…:
# a storage definition lives in /etc/pve/storage.cfg and is cluster-wide.
# They are SYNCHRONOUS: Proxmox returns no UPID, so there is nothing to
# poll and these are plain route calls rather than jobs.
#
# `config` may carry a live credential (PBS `password`, CIFS `username`/
# `password`). It is forwarded and forgotten: nothing here logs, stores or
# returns it, and _wrap below scrubs only OUR token: the caller's secret
# never enters an exception message because it is a request body, not a
# header, and proxmoxer does not echo request bodies in its errors.
```

</details>

**after**

```
    # These three hit the CLUSTER-level /storage endpoints, not /nodes/{n}/…:
    # a storage definition lives in /etc/pve/storage.cfg and is cluster-wide.
    # They are SYNCHRONOUS: Proxmox returns no UPID, so there is nothing to
    # poll and these are plain route calls rather than jobs.
    #
    # `config` may carry a live credential (PBS `password`, CIFS `username`/
    # `password`). It is forwarded and forgotten: nothing here logs, stores or
    # returns it, and _wrap below scrubs only OUR token: the caller's secret
    # never enters an exception message because it is a request body, not a
    # header, and proxmoxer does not echo request bodies in its errors.
```


### 🟢 KEEP (77), unchanged

- **`[122]`** `1` &middot; _contract_ &middot; `The ONE Proxmox client layer (docs 02 §4, 11 §7). Every proxmoxer call and every`
- **`[123]`** `14` &middot; _compatibility_ &middot; `# noqa: F401  (used by later phases' sync paths)`
- **`[124]`** `15` &middot; _security_ &middot; `# The single source of truth for the privilege name (services/pveum.py's own`
- **`[125]`** `21` &middot; _contract_ &middot; `A Proxmox interaction that failed, classified so a caller can tell a`
- **`[126]`** `31` &middot; _external-quirk_ &middot; `# Proxmox's own status verbs. Proxploy's user-facing vocabulary maps onto these`
- **`[127]`** `37` &middot; _security_ &middot; `# The NODE's own power verbs (POST /nodes/{node}/status?command=...), never to`
- **`[128]`** `64` &middot; _contract_ &middot; `-> ("user@realm", "tokenname"), both rebuilt from the parsed components.`
- **`[129]`** `67` &middot; _security_ &middot; `# Never echo the input: it is exactly the malformed case that may be a`
- **`[130]`** `80` &middot; _security_ &middot; `The ONLY value allowed into the unencrypted `host_credentials.public_meta`.`
- **`[131]`** `92` &middot; _external-quirk_ &middot; `A token secret must be encodable as an HTTP header value.`
- **`[132]`** `130` &middot; _security_ &middot; `# 169.254.169.254 lives here`
- **`[133]`** `139` &middot; _security_ &middot; `Resolve `host`, refuse the dangerous address classes, return one literal IP.`
- **`[134]`** `154` &middot; _external-quirk_ &middot; `# drop any IPv6 zone id`
- **`[135]`** `156` &middot; _security_ &middot; `# ::ffff:169.254.169.254`
- **`[136]`** `167` &middot; _security_ &middot; `resolve_target + connect to the literal we validated (doc 02 §5's SSRF`
- **`[137]`** `177` &middot; _security_ &middot; `# we are fetching the cert to pin it, not trusting it`
- **`[138]`** `186` &middot; _external-quirk_ &middot; `A file object whose `.name` is settable, for `ProxmoxClient.storage_upload`.`
- **`[139]`** `237` &middot; _external-quirk_ &middot; `# Proxmox's own 403 text names exactly what it wanted: "Permission check`
- **`[140]`** `247` &middot; _contract_ &middot; `-> "Priv on /path", or None if `text` doesn't carry PVE's own`
- **`[141]`** `328` &middot; _security_ &middot; `# Both the raw value and the form a bytes/str repr() would render,`
- **`[142]`** `354` &middot; _security_ &middot; `# Gate every outbound path, not just the CERT_NONE one below: proxmoxer`
- **`[143]`** `391` &middot; _contract_ &middot; `One bulk call: every node/CT/VM/storage row for this endpoint.`
- **`[144]`** `404` &middot; _contract_ &middot; `History-quality per-node series (netin/netout/cpu/mem), doc 02 §11.1.`
- **`[145]`** `413` &middot; _contract_ &middot; `GET /nodes/{node}/status: the node's own view of itself.`
- **`[146]`** `472` &middot; _contract_ &middot; `GET /nodes/{node}/disks/list: model, serial, size, health, wearout.`
- **`[147]`** `491` &middot; _external-quirk_ &middot; `GET /nodes/{node}/hardware/pci -> the PCI inventory.`
- **`[148]`** `505` &middot; _contract_ &middot; `GET /nodes/{node}/services -> the pve-* and system units systemd`
- **`[149]`** `515` &middot; _surprising_ &middot; `GET /nodes/{node}/subscription -> {status, message, serverid, url}.`
- **`[150]`** `528` &middot; _external-quirk_ &middot; `GET /nodes/{node}/dns -> {dns1, dns2, dns3, search}. The numbered`
- **`[151]`** `538` &middot; _contract_ &middot; `GET /nodes/{node}/time -> {localtime, time, timezone}.`
- **`[152]`** `551` &middot; _contract_ &middot; `POST /nodes/{node}/{lxc|qemu}/{vmid}/status/{action} -> UPID.`
- **`[153]`** `627` &middot; _contract_ &middot; `POST /nodes/{node}/network, stages a new iface. `config` carries`
- **`[154]`** `637` &middot; _contract_ &middot; `PUT /nodes/{node}/network/{iface}, stages an edit.`
- **`[155]`** `646` &middot; _contract_ &middot; `DELETE /nodes/{node}/network/{iface}, stages a removal.`
- **`[156]`** `655` &middot; _surprising_ &middot; `PUT /nodes/{node}/network -> UPID.`
- **`[157]`** `670` &middot; _contract_ &middot; `DELETE /nodes/{node}/network, discards /etc/network/interfaces.new.`
- **`[158]`** `691` &middot; _contract_ &middot; `The proxmoxer node under which this scope's firewall objects live.`
- **`[159]`** `706` &middot; _external-quirk_ &middot; `Where this scope's RULES live, which is not always `.rules`.`
- **`[160]`** `721` &middot; _external-quirk_ &middot; `Drop keys whose value is None so they are never sent at all.`
- **`[161]`** `746` &middot; _external-quirk_ &middot; ``params` is unpacked, never named as keywords: `icmp-type` carries a`
- **`[162]`** `765` &middot; _external-quirk_ &middot; `Sends `moveto` alone, plus the digest. PVE's own schema says "Other`
- **`[163]`** `857` &middot; _external-quirk_ &middot; `# PVE takes 1/0, not true/false`
- **`[164]`** `922` &middot; _contract_ &middot; `Security groups are cluster-wide, so this takes no scope.`
- **`[165]`** `949` &middot; _contract_ &middot; `Alias and IP set names this scope may reference in source and dest.`
- **`[166]`** `959` &middot; _external-quirk_ &middot; `Read only, cluster wide. PVE gives a name and a description; it does`
- **`[167]`** `971` &middot; _contract_ &middot; `Line cursor plus optional epoch bounds, returning {n, t} rows: the`
- **`[168]`** `983` &middot; _contract_ &middot; `GET /nodes/{node}/tasks/{upid}/status, `stopped` + exitstatus == done.`
- **`[169]`** `992` &middot; _contract_ &middot; `GET /nodes/{node}/tasks, newest first.`
- **`[170]`** `1009` &middot; _contract_ &middot; `GET /nodes/{node}/tasks/{upid}/log, rows of {"n": seq, "t": line}.`
- **`[171]`** `1021` &middot; _contract_ &middot; `POST /nodes/{node}/vzdump -> UPID. `params` carries `vmid` (a comma`
- **`[172]`** `1031` &middot; _external-quirk_ &middot; `Restore is a create-with-archive, not its own endpoint.`
- **`[173]`** `1051` &middot; _security_ &middot; `GET /nodes/{node}/storage/{storage}/prunebackups, a DRY RUN.`
- **`[174]`** `1067` &middot; _security_ &middot; `DELETE /nodes/{node}/storage/{storage}/prunebackups -> UPID. This one`
- **`[175]`** `1079` &middot; _contract_ &middot; `POST /nodes/{node}/{lxc|qemu}/{vmid}/termproxy -> {user, ticket, port, upid}.`
- **`[176]`** `1088` &middot; _contract_ &middot; `POST /nodes/{node}/termproxy -> {user, ticket, port, upid} (node shell).`
- **`[177]`** `1141` &middot; _contract_ &middot; `GET /nodes/{node}/storage -> [{storage, type, content, active,`
- **`[178]`** `1151` &middot; _contract_ &middot; `GET /nodes/{node}/storage/{storage}/status -> per-datastore detail.`
- **`[179]`** `1161` &middot; _external-quirk_ &middot; `GET /nodes/{node}/storage/{storage}/content -> volume listing.`
- **`[180]`** `1175` &middot; _contract_ &middot; `GET /storage, the cluster-level storage.cfg, not a node's view.`
- **`[181]`** `1215` &middot; _external-quirk_ &middot; `# Filesystem types qemu-ga reports that are not the guest's storage.`
- **`[182]`** `1323` &middot; _contract_ &middot; `GET /nodes/{node}/network -> [{iface, type, method, cidr, gateway,`
- **`[183]`** `1336` &middot; _contract_ &middot; `GET /nodes/{node}/{lxc|qemu}/{vmid}/config, the full config dict,`
- **`[184]`** `1346` &middot; _external-quirk_ &middot; `GET /nodes/{node}/{lxc|qemu}/{vmid}/snapshot -> [{name, description,`
- **`[185]`** `1361` &middot; _external-quirk_ &middot; `POST /nodes/{node}/{kind}/{vmid}/snapshot -> UPID.`
- **`[186]`** `1387` &middot; _security_ &middot; `POST /nodes/{node}/{kind}/{vmid}/snapshot/{name}/rollback -> UPID.`
- **`[187]`** `1402` &middot; _contract_ &middot; `DELETE /nodes/{node}/{kind}/{vmid}/snapshot/{name} -> UPID.`
- **`[188]`** `1413` &middot; _external-quirk_ &middot; `GET /cluster/nextid, PVE answers with a JSON string; cast once here`
- **`[189]`** `1425` &middot; _external-quirk_ &middot; `GET /cluster/status, cluster membership + node list.`
- **`[190]`** `1441` &middot; _external-quirk_ &middot; `GET /cluster/config/join -> {nodelist: [{name, ring0_addr, pve_addr,`
- **`[191]`** `1462` &middot; _contract_ &middot; `POST /nodes/{node}/{lxc|qemu}/{vmid}/migrate -> UPID.`
- **`[192]`** `1480` &middot; _contract_ &middot; `POST /nodes/{node}/qemu -> UPID.`
- **`[193]`** `1495` &middot; _external-quirk_ &middot; `POST /nodes/{node}/qemu/{vmid}/clone -> UPID.`
- **`[194]`** `1509` &middot; _surprising_ &middot; `DELETE /nodes/{node}/{lxc|qemu}/{vmid} -> UPID. Destroys the guest`
- **`[195]`** `1549` &middot; _external-quirk_ &middot; `DELETE /nodes/{node}/storage/{storage}/content/{volid}.`
- **`[196]`** `1575` &middot; _contract_ &middot; `POST /storage, `config` must include `storage` and `type`.`
- **`[197]`** `1585` &middot; _contract_ &middot; `PUT /storage/{storage}, only the keys given are changed.`
- **`[198]`** `1594` &middot; _surprising_ &middot; `DELETE /storage/{storage}, drops the definition; upstream data stays.`

---

## `backend/proxploy/api/hosts.py`

4,721 → 3,664 words, 22% cut. 1 delete, 59 shorten, 48 keep.


### 🔴 DELETE (1)

**`[199]`** `backend/proxploy/api/hosts.py:744` &middot; 39w &middot; _separator_  
Section banner plus a note that the routes the old banner called missing now exist.

```
# --- removal, credential rotation, forced sync, task passthrough (PXP-17) ---
# doc 05 lists host.sync / host.credentials / host.remove and the authz matrix
# has carried all three since Phase 1; no phase ever added the routes. The
# header comment above used to say so.
```


### 🟡 SHORTEN (59)

**`[200]`** `backend/proxploy/api/hosts.py:1` &middot; **23w → 18w** (22% cut) &middot; _ticket-history_  
The route-stacking shape is the content; the doc and phase citation is not.

<details><summary>before</summary>

```
Host onboarding. ROUTE TEMPLATE (doc 10 Phase 1 DoD): every mutation stacks
auth -> RBAC stub -> entitlement -> work -> audit. Later phases copy this shape.
```

</details>

**after**

```
"""Host onboarding. ROUTE TEMPLATE: every mutation stacks auth, RBAC stub,
entitlement, work, audit. Later routes copy this shape."""
```

**`[201]`** `backend/proxploy/api/hosts.py:24` &middot; **54w → 17w** (69% cut) &middot; _implementation-diary_  
Keep why the dependencies are singletons, drop the paragraph about what this comment used to claim.

<details><summary>before</summary>

```
# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request.
#
# This comment used to say host.sync/credentials/remove had no route here yet
# and that no plan added them. They exist now (see the bottom of this file,
# PXP-17); host.console is elsewhere, on the node-shell ticket route in
# api/consoles.py.
```

</details>

**after**

```
# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request.
```

**`[202]`** `backend/proxploy/api/hosts.py:76` &middot; **77w → 53w** (31% cut) &middot; _buried-invariant_  
Keep the partial-update contract and the deliberate exclusion of credentials, cut the field-by-field history.

<details><summary>before</summary>

```
Partial update: every field is optional and only the ones supplied are
    changed. Started as just the node-shell opt-in toggle (doc 08 §9) plus
    team assignment; name/address joined for the host actions menu's Edit
    dialog. Credentials are deliberately NOT here -- POST
    /{host_id}/credentials is their own dedicated, already-existing flow
    (verifies a new token against the node before it replaces the old one),
    and the Edit dialog composes both calls rather than this route growing a
    second credential path.
```

</details>

**after**

```
    """Partial update: every field is optional and only the ones supplied are
    changed. Credentials are deliberately NOT here: POST
    /{host_id}/credentials is their own flow, which verifies a new token
    against the node before replacing the old one, and the Edit dialog
    composes both calls rather than this route growing a second credential
    path."""
```

**`[203]`** `backend/proxploy/api/hosts.py:88` &middot; **81w → 65w** (20% cut) &middot; _buried-invariant_  
Keep why a pin is the only integrity these connections have and what null means, tighten the history around it.

<details><summary>before</summary>

```
# The re-pin path. A pin is only enforced while verify_tls is false, which
# is the normal case for a stock node with a self-signed certificate, so it
# is the only integrity those connections have. Nothing could change one
# before this, so a routine certificate renewal left a host row nobody
# could fix from the UI. Setting it re-pins; setting it to null clears the
# pin (see model_fields_set in patch_host: omitted and null differ here the
# same way they do for team_id).
```

</details>

**after**

```
    # The re-pin path. A pin is only enforced while verify_tls is false, the
    # normal case for a stock self-signed node, so it is the only integrity
    # those connections have. Nothing could change one before this, so a
    # routine certificate renewal left a host row nobody could fix from the
    # UI. Setting it re-pins, null clears the pin (omitted and null differ
    # here, as for team_id).
```

**`[204]`** `backend/proxploy/api/hosts.py:96` &middot; **57w → 50w** (12% cut) &middot; _buried-invariant_  
Keep the rotated-host-key problem and the TOFU semantics of null, tighten the wording.

<details><summary>before</summary>

```
# The SSH re-pin path, and the reason it exists is the same one: nothing
# could change this before, so a node whose host key rotated (rejoining a
# cluster does it) failed every install with no way back but a manual
# database write. Omitted leaves it alone; null clears the pin so the next
# connection re-learns it (TOFU).
```

</details>

**after**

```
    # The SSH re-pin path, same reason: nothing could change this before, so a
    # node whose host key rotated (rejoining a cluster does it) failed every
    # install with no way back but a manual database write. Omitted leaves it
    # alone, null clears the pin so the next connection re-learns it (TOFU).
```

**`[205]`** `backend/proxploy/api/hosts.py:112` &middot; **120w → 72w** (40% cut) &middot; _buried-invariant_  
Keep the ring0 versus API address quirk and the best-effort contract, drop the doc-check citation.

<details><summary>before</summary>

```
{node name: the address PVE designates for its API}, from
    /cluster/config/join, or {} if that cannot be read.

    `/cluster/status` reports only `ip`, which is corosync's ring0 address.
    On a cluster whose corosync runs on a dedicated link that is NOT the
    address the API answers on, so every peer built from it would be
    unreachable (doc 12 check 13, where the hazard was confirmed real by PVE
    storing `ring0_addr` and `pve_addr` as separate fields).

    Best effort on purpose: an empty dict means callers fall back to the
    `/cluster/status` address, which is what they used before this existed and
    is correct whenever the two coincide. A peer discovery that failed outright
    because one extra endpoint was unreadable would be a worse trade.
    
```

</details>

**after**

```
    """{node name: the address PVE designates for its API}, from
    /cluster/config/join, or {} if that cannot be read.

    `/cluster/status` reports only `ip`, corosync's ring0 address. PVE keeps
    `ring0_addr` and `pve_addr` separate, so where corosync runs on a
    dedicated link every peer built from `ip` would be unreachable.

    Best effort: {} means callers fall back to the `/cluster/status` address,
    correct whenever the two coincide. Failing discovery over one unreadable
    endpoint would be the worse trade.
    """
```

**`[206]`** `backend/proxploy/api/hosts.py:139` &middot; **45w → 36w** (20% cut) &middot; _buried-invariant_  
Keep the never-raises contract and its reason, drop the cross-reference to another function's rule.

<details><summary>before</summary>

```
The certificate the node at `address` is presenting right now, or None
    if it could not be fetched.

    Never raises. A pin is worth having, but never worth blocking an enrolment
    or a connection test over, the same rule cluster_identity already follows
    in create_host below.
    
```

</details>

**after**

```
    """The certificate the node at `address` is presenting right now, or None
    if it could not be fetched.

    Never raises. A pin is worth having, but never worth blocking an
    enrolment or a connection test over.
    """
```

**`[207]`** `backend/proxploy/api/hosts.py:160` &middot; **74w → 59w** (20% cut) &middot; _buried-invariant_  
Keep why only the monitoring set is required and why it comes from the generator, cut the doc citation and the restatement.

<details><summary>before</summary>

```
# Doc 08's ProxployAudit role: the read-only monitoring set, required for the
# poller to complete a cycle at all. Deliberately only this set: the lifecycle,
# console and backup roles gate optional features, and a token without them
# should still enrol.
#
# Imported from services/pveum, which is also what generates the script that
# creates these tokens. One table, so a token the wizard tells you to make
# always satisfies the check the wizard then runs against it.
```

</details>

**after**

```
# The read-only monitoring set, required for the poller to complete a cycle at
# all. Only this set: lifecycle, console and backup gate optional features,
# and a token without them should still enrol. Imported from services/pveum,
# which also generates the script that creates these tokens, so what the
# wizard tells you to make always satisfies the check it then runs.
```

**`[208]`** `backend/proxploy/api/hosts.py:173` &middot; **82w → 70w** (15% cut) &middot; _security_  
Keep the None-is-not-clean trap and the pool-scoping rule, drop the doc citation and the restatement.

<details><summary>before</summary>

```
Which monitoring privileges this token does not hold anywhere.

    None means "could not tell", which is NOT the same as "none missing": some
    setups refuse /access/permissions to a token, and reporting unknown as a
    clean bill of health is how this failed silently in the first place.

    A privilege granted on any path counts. Doc 08 supports scoping Proxploy to
    a pool by granting the roles on /pool/<name> instead of /, so requiring
    them at "/" would report a working pool-scoped install as broken.
    
```

</details>

**after**

```
    """Which monitoring privileges this token does not hold anywhere.

    None means "could not tell", NOT "none missing": some setups refuse
    /access/permissions to a token, and reporting unknown as a clean bill of
    health is how this failed silently before.

    A privilege granted on any path counts: Proxploy can be scoped to a pool
    by granting the roles on /pool/<name>, so requiring them at "/" would
    call a working pool-scoped install broken.
    """
```

**`[209]`** `backend/proxploy/api/hosts.py:190` &middot; **54w → 33w** (39% cut) &middot; _redundant_  
Keep the None contract and why it is unconditional, drop the restatement of the same point.

<details><summary>before</summary>

```
Whether this token lacks Sys.PowerMgmt anywhere. None means "could not
    tell", same reasoning as _missing_privileges.

    Checked unconditionally, unlike Lifecycle/Console/Backup: the host
    actions menu offers Reboot/Power off on every host regardless of which
    optional capabilities were chosen, so this is checked the same way
    monitoring is, not gated behind an opt-in capability having been picked.
    
```

</details>

**after**

```
    """Whether this token lacks Sys.PowerMgmt anywhere. None means "could not
    tell", same reasoning as _missing_privileges.

    Checked unconditionally, unlike Lifecycle/Console/Backup: the host actions
    menu offers Reboot/Power off on every host whatever capabilities were
    chosen.
    """
```

**`[210]`** `backend/proxploy/api/hosts.py:205` &middot; **66w → 60w** (9% cut) &middot; _buried-invariant_  
Keep the presence-only rule and the single-source keying, trim the wording.

<details><summary>before</summary>

```
Which capability tokens this host holds. Presence only.

    Never the token, the token id, or any part of the blob: the UI needs to
    know whether a capability is configured and nothing more. Keyed off
    CAPABILITIES so a capability added to services/pveum.py appears here
    with no second list to maintain, and a host with no credential rows
    reports every capability False rather than omitting the field.
    
```

</details>

**after**

```
    """Which capability tokens this host holds. Presence only.

    Never the token, the token id, or any part of the blob: the UI only needs
    to know whether a capability is configured. Keyed off CAPABILITIES so a
    new capability appears here with no second list, and a host with no
    credential rows reports every capability False rather than omitting the
    field.
    """
```

**`[211]`** `backend/proxploy/api/hosts.py:240` &middot; **52w → 45w** (13% cut) &middot; _buried-invariant_  
Keep why POST and the never-ask-for-root rule, drop the doc section reference.

<details><summary>before</summary>

```
The copy-paste pveum script from doc 08 §2.

    POST rather than GET for the structured body, following /probe: it reads
    nothing and changes nothing on this side. The operator runs the result in
    a node shell they already own, which is the whole point: Proxploy never
    asks for root credentials, even transiently.
    
```

</details>

**after**

```
    """The copy-paste pveum script an operator runs to create the tokens.

    POST rather than GET for the structured body; it reads and changes nothing
    here. The operator runs the result in a node shell they already own:
    Proxploy never asks for root credentials, even transiently.
    """
```

**`[212]`** `backend/proxploy/api/hosts.py:267` &middot; **40w → 37w** (8% cut) &middot; _buried-invariant_  
Same fact, fewer words.

<details><summary>before</summary>

```
# /version succeeds for a privsep token holding no ACLs at all, so on its
# own it proves only that the address and secret are right. The privilege
# diff is what makes "Test connection" mean the thing operators read it as.
```

</details>

**after**

```
    # /version succeeds for a privsep token holding no ACLs at all, so alone
    # it proves only that the address and secret are right. The privilege diff
    # is what makes "Test connection" mean what operators read it as.
```

**`[213]`** `backend/proxploy/api/hosts.py:293` &middot; **37w → 25w** (32% cut) &middot; _narration_  
Keep why a name is recorded instead of an id, in one sentence.

<details><summary>before</summary>

```
# No Host row exists to resolve a name from: the enrolment failed
# before one was written. The name the operator typed is what they
# will be looking for when they come back to ask why it failed.
```

</details>

**after**

```
        # No Host row exists yet, the enrolment failed before one was written,
        # so the name the operator typed is what they will search for later.
```

**`[214]`** `backend/proxploy/api/hosts.py:301` &middot; **44w → 27w** (39% cut) &middot; _buried-invariant_  
Keep recorded-not-refused, drop the restatement about locking the operator out.

<details><summary>before</summary>

```
# Checked at enrolment, not left for the poller to discover minutes later
# as a bare "unreachable". Recorded rather than refused: an under-privileged
# token is still worth enrolling, and locking an operator out of their own
# host at the final step is the worse failure.
```

</details>

**after**

```
    # Checked at enrolment, not left for the poller to report minutes later as
    # a bare "unreachable". Recorded rather than refused: an under-privileged
    # token is still worth enrolling.
```

**`[215]`** `backend/proxploy/api/hosts.py:311` &middot; **68w → 48w** (29% cut) &middot; _buried-invariant_  
Keep pin-on-first-use and why an operator's own fingerprint is never overwritten, tighten it.

<details><summary>before</summary>

```
# Pin on first use: first use of a host is its enrolment. Only when the
# request supplied none, because an operator who pasted a fingerprint has
# already said which certificate is right, and probing over the top of that
# would replace their answer with whatever the node is presenting.
# A failed probe leaves the host unpinned, which is what every host was
# before this, rather than blocking enrolment.
```

</details>

**after**

```
    # Pin on first use, and first use is enrolment. Only when the request
    # supplied none: an operator who pasted a fingerprint has already said
    # which certificate is right, and probing over the top would replace their
    # answer. A failed probe leaves the host unpinned rather than blocking
    # enrolment.
```

**`[216]`** `backend/proxploy/api/hosts.py:325` &middot; **62w → 42w** (32% cut) &middot; _data-integrity_  
Keep the flush-versus-commit window and what it produced, tighten it.

<details><summary>before</summary>

```
# flush, not commit: this needs host.id for the credential rows below, and
# they belong to the same enrolment. Committing here left a window where a
# crash, or any failure in the ssh_enroll branch, produced a host row with
# no credential at all -- a host that shows up enrolled in the UI and
# cannot be talked to, with no route that repairs it.
```

</details>

**after**

```
    # flush, not commit: this needs host.id for the credential rows below,
    # which belong to the same enrolment. Committing here left a window where
    # a crash produced a host row with no credential, enrolled in the UI,
    # unreachable, and repaired by no route.
```

**`[217]`** `backend/proxploy/api/hosts.py:335` &middot; **44w → 29w** (34% cut) &middot; _implementation-diary_  
Keep why only monitoring is written here, drop the note about whose UI work the rest was.

<details><summary>before</summary>

```
# Enrolment always creates the "monitoring" row: it is the one mandatory
# capability (CAPABILITIES["monitoring"].required, services/pveum.py),
# and there is only one token pasted at this step of the wizard.
# Lifecycle/console/backup tokens are added later via
# POST /hosts/{id}/credentials (CredentialRotateIn.capability), a later
# step's UI work, not this one.
```

</details>

**after**

```
    # Enrolment always creates the "monitoring" row: the one mandatory
    # capability, and the only token pasted at this step of the wizard.
    # Lifecycle/console/backup tokens arrive later via
    # POST /hosts/{id}/credentials (CredentialRotateIn.capability).
```

**`[218]`** `backend/proxploy/api/hosts.py:374` &middot; **24w → 15w** (38% cut) &middot; _redundant_  
The second sentence only says the field already exists elsewhere.

<details><summary>before</summary>

```
# cluster_name so the frontend can tell which enrolled hosts are
# nodes of the same cluster. Already on the model, already
# returned by POST /hosts.
```

</details>

**after**

```
             # cluster_name so the frontend can tell which enrolled hosts are
             # nodes of the same cluster.
```

**`[219]`** `backend/proxploy/api/hosts.py:390` &middot; **37w → 26w** (30% cut) &middot; _ticket-history_  
Drop the Task 6 reference and the comparison to a field that is no longer here.

<details><summary>before</summary>

```
# Same reason the storage defaults used to be here (Task 6): the
# install dialog asks the root-execution
# tick only while this is null. Re-asking a host that already
# acknowledged surfaces no new information; it is just friction.
```

</details>

**after**

```
             # The install dialog asks the root-execution tick only while this
             # is null. Re-asking a host that already acknowledged surfaces no
             # new information, it is just friction.
```

**`[220]`** `backend/proxploy/api/hosts.py:402` &middot; **120w → 73w** (39% cut) &middot; _test-reference_  
Keep the route-ordering hazard and the derivation rule, drop the test name and the sibling-file citation.

<details><summary>before</summary>

```
The static catalogue of optional capabilities the setup script can
    grant (key, label, why it matters, whether it is required), for the
    frontend to tell an operator what they give up by unticking one.

    Registered ABOVE the /{host_id} wildcard below: Starlette matches in
    registration order, and out of order this literal path would be
    swallowed by GET /{host_id} with host_id="capabilities" (same WARNING
    as api/vms.py's /{vm_id}/{action} ordering hazard). Confirmed by
    test_capabilities_route_is_not_shadowed_by_the_host_id_wildcard.

    Derived straight from CAPABILITIES, list not dict, so declaration order
    (monitoring first) survives into the response, and a capability added
    there needs no edit here. privileges/role/token are deliberately left
    off: the UI only needs why a capability matters, not the PVE privilege
    names or the identifiers that build the script.
    
```

</details>

**after**

```
    """The static catalogue of optional capabilities the setup script can
    grant (key, label, why it matters, whether it is required).

    Registered ABOVE the /{host_id} wildcard: Starlette matches in
    registration order, and out of order this literal path is swallowed by
    GET /{host_id} with host_id="capabilities".

    Derived straight from CAPABILITIES, list not dict, so declaration order
    survives into the response. privileges/role/token are left off: the UI
    needs why a capability matters, not PVE privilege names.
    """
```

**`[221]`** `backend/proxploy/api/hosts.py:429` &middot; **126w → 84w** (33% cut) &middot; _buried-invariant_  
Keep why this is a dedicated route and what null means, cut the ticket numbers and the repeated aside.

<details><summary>before</summary>

```
Which enrolled host, if any, Proxploy itself runs on (PXP-33):
    selfguard.is_self_host_node()'s Host-record narrowing, and the second
    condition inside is_self().

    A dedicated route rather than a hole in PATCH /settings's allowlist
    (api/settings.py, PXP-36 note): that route takes free-form values, and
    self.host_id must name an actually-enrolled host or nothing at all, never
    an arbitrary string. `host_id: null` is "none of these", the honest
    answer when Proxploy is not running on any host it manages; set_setting
    still writes the row (value None), so the onboarding wizard and the
    settings screen can tell "answered none" apart from "never asked". Every
    selfguard read already treats an absent key and a None value the same
    way (fail open), so recording "none" changes nothing about detection,
    only whether the question gets asked again.
    
```

</details>

**after**

```
    """Which enrolled host, if any, Proxploy itself runs on: what narrows
    selfguard.is_self_host_node() to a Host record.

    A dedicated route rather than a hole in PATCH /settings's allowlist,
    which takes free-form values: self.host_id must name an enrolled host or
    nothing, never an arbitrary string.

    `host_id: null` is "none of these", and set_setting still writes the row,
    so the wizard can tell "answered none" from "never asked". Every
    selfguard read treats absent and None alike (fail open), so it only stops
    the question being asked again.
    """
```

**`[222]`** `backend/proxploy/api/hosts.py:477` &middot; **130w → 100w** (23% cut) &middot; _buried-invariant_  
Keep the read-only scope, the one-dead-node rule and the resolve_target trust boundary, tighten the prose.

<details><summary>before</summary>

```
The other nodes of this host's cluster, and whether each can be added.

    Read only: nothing here writes a host, a credential or an audit row. It
    reveals node names, addresses and fingerprints, which is the same class of
    information POST /hosts/probe already returns to an admin.

    Every peer is probed before this answers, so the caller never renders a
    row whose reachability is still unknown. A failure against one peer is
    recorded on that peer's row and never raised: one dead node must not hide
    the live ones.

    Every outbound connection still goes through resolve_target(), inside
    tls_fingerprint_sha256 and ProxmoxClient._connect. That guard matters more
    here than anywhere else, because the peer address comes from the node
    rather than from the operator, and it is why no new guard is needed.
    
```

</details>

**after**

```
    """The other nodes of this host's cluster, and whether each can be added.

    Read only: nothing here writes a host, a credential or an audit row, and
    it reveals only what POST /hosts/probe already returns to an admin.

    Every peer is probed before this answers, so no row is rendered with
    reachability unknown. A failure is recorded on that peer's row and never
    raised: one dead node must not hide the live ones.

    The peer address comes from the node, not the operator, so the guard that
    matters is resolve_target() inside tls_fingerprint_sha256 and
    ProxmoxClient._connect. No new guard is needed here.
    """
```

**`[223]`** `backend/proxploy/api/hosts.py:507` &middot; **36w → 35w** (3% cut) &middot; _security_  
Same facts, fewer words.

<details><summary>before</summary>

```
# The origin's own api_token:* kinds, so the caller can say what
# would be copied. ssh_key is not in here and never will be: it is
# a root shell, a different trust decision from an API token.
```

</details>

**after**

```
           # The origin's own api_token:* kinds, so the caller can say what
           # would be copied. ssh_key is not here and never will be: it is a
           # root shell, a different trust decision from an API token.
```

**`[224]`** `backend/proxploy/api/hosts.py:512` &middot; **20w → 15w** (25% cut) &middot; _redundant_  
enrol_peers states the same rule at the point it is enforced; one line covers it here.

<details><summary>before</summary>

```
# Mirrors the check create_host makes. A peer is never the first
# host, so the entitlement is always required for one.
```

</details>

**after**

```
           # A peer is never the first host, so the entitlement is always
           # required for one.
```

**`[225]`** `backend/proxploy/api/hosts.py:517` &middot; **36w → 34w** (6% cut) &middot; _external-quirk_  
Same fact, fewer words.

<details><summary>before</summary>

```
# No cluster row means standalone. Its single node row is this host
# itself and carries no `local` flag on some versions, so returning
# here is what stops a standalone node being offered as its own peer.
```

</details>

**after**

```
        # No cluster row means standalone. Its single node row is this host
        # itself and carries no `local` flag on some versions, so returning here
        # is what stops it being offered as its own peer.
```

**`[226]`** `backend/proxploy/api/hosts.py:535` &middot; **59w → 38w** (36% cut) &middot; _buried-invariant_  
Keep the match key and why NULL cluster_name counts, tighten the parenthetical.

<details><summary>before</summary>

```
# Matched on cluster plus node name, never on address, so a peer
# enrolled under a second address or a DNS name is still recognised.
# A NULL cluster_name counts too: it means a row from before cluster
# detection, or one the poller has not filled in yet, and adding the
# same machine twice is the worse failure of the two.
```

</details>

**after**

```
        # Matched on cluster plus node name, never on address, so a peer
        # enrolled under a second address or a DNS name is still recognised. A
        # NULL cluster_name counts too: adding the same machine twice is the
        # worse failure.
```

**`[227]`** `backend/proxploy/api/hosts.py:543` &middot; **22w → 13w** (41% cut) &middot; _narration_  
The reason is one clause; the rest narrates the branch below it.

<details><summary>before</summary>

```
# An already enrolled peer is not probed: it cannot be added again, so
# the handshake and the /version call would buy nothing.
```

</details>

**after**

```
        # An already enrolled peer cannot be added again, so it is not probed.
```

**`[228]`** `backend/proxploy/api/hosts.py:575` &middot; **55w → 33w** (40% cut) &middot; _implementation-diary_  
Keep why model_fields_set is required, drop the story of what was unimplementable before.

<details><summary>before</summary>

```
# model_fields_set, not `is not None`: null is the only way to say "no
# team" and this is a partial update, so an omitted field and an explicit
# null have to mean different things. Without it the Settings picker's
# "Unassigned" option was unimplementable, and a host could be moved
# between teams but never out of one.
```

</details>

**after**

```
    # model_fields_set, not `is not None`: null is the only way to say "no
    # team" and this is a partial update, so an omitted field and an explicit
    # null have to mean different things.
```

**`[229]`** `backend/proxploy/api/hosts.py:598` &middot; **35w → 24w** (31% cut) &middot; _redundant_  
Repeats the team_id explanation; keep only the pin-specific consequence.

<details><summary>before</summary>

```
# model_fields_set for the same reason team_id uses it: null is the only
# way to say "stop pinning this host", and an omitted field must leave the
# pin alone rather than clearing it on every rename.
```

</details>

**after**

```
    # model_fields_set again: null means "stop pinning this host", and an
    # omitted field must leave the pin alone rather than clearing it on every
    # rename.
```

**`[230]`** `backend/proxploy/api/hosts.py:608` &middot; **39w → 34w** (13% cut) &middot; _test-reference_  
Keep the invariant that the toggle keeps its historic action name, drop the test name.

<details><summary>before</summary>

```
# Same action name as before when only the node-shell toggle (plus,
# historically, team assignment) changed -- test_patch_host_writes_an_
# audit_event pins that exact string. A name/address change is different
# enough in kind (identity, not a feature flag) to get its own name.
```

</details>

**after**

```
    # The node-shell toggle keeps its historic action name, which the audit
    # filters depend on. A name or address change is different enough in kind
    # (identity, not a feature flag) to get its own name.
```

**`[231]`** `backend/proxploy/api/hosts.py:642` &middot; **29w → 25w** (14% cut) &middot; _narration_  
One clause carries it: the re-check exists so a just-granted privilege shows now.

<details><summary>before</summary>

```
# Same re-check reachability already got: an operator who just ran
# the extra pveum commands for node power should see it reflected
# here, not only on the next full enrolment.
```

</details>

**after**

```
        # Re-checked here so an operator who just ran the extra pveum commands
        # for node power sees it now, not only at the next full enrolment.
```

**`[232]`** `backend/proxploy/api/hosts.py:646` &middot; **45w → 41w** (9% cut) &middot; _buried-invariant_  
Keep the quorum-loss surprise and the best-effort rule, drop the doc citation.

<details><summary>before</summary>

```
# A host that answers /version perfectly can still be unable to accept
# a single write, which is what quorum loss looks like from here (doc
# 12 check 12). Best effort: a token that cannot read /cluster/status
# leaves the previous answer alone rather than claiming standalone.
```

</details>

**after**

```
        # A host that answers /version perfectly can still be unable to accept
        # a single write, which is what quorum loss looks like from here. Best
        # effort: a token that cannot read /cluster/status leaves the previous
        # answer alone rather than claiming standalone.
```

**`[233]`** `backend/proxploy/api/hosts.py:654` &middot; **41w → 39w** (5% cut) &middot; _buried-invariant_  
Same fact, fewer words.

<details><summary>before</summary>

```
# Every configured token against its own role, not just monitoring
# against MONITORING_PRIVILEGES: this is where an operator finds out
# that a token predating a privilege the product now needs is short of
# it, instead of finding out from a 403 mid-job.
```

</details>

**after**

```
        # Every configured token against its own role, not just monitoring
        # against MONITORING_PRIVILEGES: this is where an operator learns a
        # token predating a privilege the product now needs is short of it,
        # instead of learning it from a 403 mid-job.
```

**`[234]`** `backend/proxploy/api/hosts.py:666` &middot; **117w → 88w** (25% cut) &middot; _buried-invariant_  
Keep why only a pin refusal is worth a socket and the deliberate verify_tls gap, cut the retelling.

<details><summary>before</summary>

```
# Only when the pin is what refused the connection. ProxmoxClient.
# _connect raises that kind before it sends anything, and it is the one
# case the Edit dialog's compare and accept control fires on, so this
# is where the certificate the node is presenting is worth a socket. A
# node that is simply dead answers with a different kind and gets no
# probe, because fetching a certificate from it could only sit out the
# full connect timeout on top of the one already spent.
#
# Known gap, deliberate: with verify_tls true the pin is not enforced
# at all, so a changed certificate never raises here and the control
# never appears. CA validation is the trust anchor in that mode.
```

</details>

**after**

```
        # Only when the pin is what refused the connection: _connect raises
        # that kind before it sends anything, and it is the one case the Edit
        # dialog's compare and accept control fires on. A node that is simply
        # dead answers with a different kind and gets no probe, which could
        # only sit out a second connect timeout.
        #
        # Known gap, deliberate: with verify_tls true the pin is not enforced,
        # so a changed certificate never raises here and the control never
        # appears. CA validation is the trust anchor in that mode.
```

**`[235]`** `backend/proxploy/api/hosts.py:691` &middot; **61w → 42w** (31% cut) &middot; _implementation-diary_  
Keep why the check exists and what `true` proves, drop the account of what the wizard used to do.

<details><summary>before</summary>

```
Prove the enrolled key actually opens a root shell on the node.

    The wizard used to take the operator's word for it, so a mis-pasted
    authorized_keys line surfaced at the first app install instead of here,
    far from its cause. `true` is the whole command: this asks one question
    does the key authenticate and can we run anything, and nothing else.
    
```

</details>

**after**

```
    """Prove the enrolled key actually opens a root shell on the node.

    Without it a mis-pasted authorized_keys line surfaces at the first app
    install, far from its cause. `true` is the whole command: does the key
    authenticate, and can anything be run.
    """
```

**`[236]`** `backend/proxploy/api/hosts.py:718` &middot; **54w → 43w** (20% cut) &middot; _buried-invariant_  
Keep what `seen` is and that None is not a mismatch, drop the parallel to the other route.

<details><summary>before</summary>

```
# `seen` is what the node is presenting right now. Handing it back is
# what makes a re-pin possible without the operator reading it off a
# message, exactly as POST /hosts/{id}/test hands back
# tls_fingerprint_seen. It is None when no key could be read, which is
# not a mismatch and must not be offered as one.
```

</details>

**after**

```
        # `seen` is what the node is presenting right now. Handing it back
        # makes a re-pin possible without the operator reading it off a
        # message. None means no key could be read, which is not a mismatch
        # and must not be offered as one.
```

**`[237]`** `backend/proxploy/api/hosts.py:757` &middot; **41w → 37w** (10% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# apps.host_id is ON DELETE RESTRICT, so a host with apps cannot simply be
# dropped. This forgets those app rows (the containers keep running and are
# untouched); destroying a container is app uninstall's job, never a
# side effect of removing a host.
```

</details>

**after**

```
    # apps.host_id is ON DELETE RESTRICT, so a host with apps cannot simply be
    # dropped. This forgets those app rows; the containers keep running.
    # Destroying one is app uninstall's job, never a side effect of removing a
    # host.
```

**`[238]`** `backend/proxploy/api/hosts.py:769` &middot; **119w → 67w** (44% cut) &middot; _buried-invariant_  
Keep the fallback rule and why an omitted capability is refused, compress the incident to one clause.

<details><summary>before</summary>

```
# Which capability's token this is. None (the default, meaning the field
# was left out entirely) falls back to "monitoring" ONLY when the host has
# no monitoring credential yet, so a pre-capability-era caller's first
# write still lands where it always did with no request change required.
# Once a monitoring credential exists, an omitted capability is refused
# rather than guessed: two frontend dialogs once posted a token with no
# `capability` at all and silently overwrote whatever was in the
# monitoring slot, convincing an operator they had configured lifecycle
# or backup when they had only ever rewritten monitoring. Validated
# against CAPABILITIES the same place token_script's `capabilities` list
# already is (ValueError -> 422), not against a separate hand-kept list
# that could drift from it.
```

</details>

**after**

```
    # Which capability's token this is. Left out entirely, it falls back to
    # "monitoring" ONLY while the host has no monitoring credential, so a
    # pre-capability-era caller's first write still lands where it always did.
    # After that an omitted capability is refused, not guessed: guessing
    # silently overwrote monitoring and convinced operators they had
    # configured lifecycle or backup. Validated against CAPABILITIES
    # (ValueError -> 422), never a hand-kept list that could drift.
```

**`[239]`** `backend/proxploy/api/hosts.py:800` &middot; **48w → 44w** (8% cut) &middot; _buried-invariant_  
Keep the owner gate and the unrecoverable key, trim the enumeration around them.

<details><summary>before</summary>

```
Forget a host and everything Proxploy cached about it.

    Owner-only (authz matrix), and gated on typing the host name back: this
    drops every app row, VM cache row and stored credential for the host in one
    call, and the SSH key it deletes cannot be recovered, only re-enrolled.
    
```

</details>

**after**

```
    """Forget a host and everything Proxploy cached about it.

    Owner-only, and gated on typing the host name back: this drops every app
    row, VM cache row and stored credential in one call, and the SSH key it
    deletes can only be re-enrolled, never recovered.
    """
```

**`[240]`** `backend/proxploy/api/hosts.py:884` &middot; **60w → 46w** (23% cut) &middot; _buried-invariant_  
Keep why this is on demand rather than polled, drop the doc citation and the closing restatement.

<details><summary>before</summary>

```
The node's own view of itself, for the host page.

    On demand, never from the poll loop: doc 02 §3 caps a cycle at O(nodes),
    and model/cores/kernel/boot mode do not change between polls. The volatile
    figures here (load, wait, memory) are already recorded as metric samples
    every cycle, so polling this would buy nothing and cost a call per node.
    
```

</details>

**after**

```
    """The node's own view of itself, for the host page.

    On demand, never from the poll loop: a cycle is capped at O(nodes), and
    model/cores/kernel/boot mode do not change between polls. The volatile
    figures here (load, wait, memory) are already recorded as metric samples
    every cycle.
    """
```

**`[241]`** `backend/proxploy/api/hosts.py:907` &middot; **40w → 27w** (32% cut) &middot; _narration_  
Keep why the field rides along on this query, drop the doc references.

<details><summary>before</summary>

```
# The host actions menu's Reboot/Power off reads this off the SAME
# query the identity rail already fetches, so the confirm dialog can
# warn BEFORE the operator types anything, not only after a rejected
# call (doc 02 §9, doc 08 §1).
```

</details>

**after**

```
        # Read off the SAME query the identity rail already fetches, so the
        # confirm dialog can warn BEFORE the operator types anything, not only
        # after a rejected call.
```

**`[242]`** `backend/proxploy/api/hosts.py:921` &middot; **33w → 24w** (27% cut) &middot; _narration_  
Keep the quirk and the rename, drop the sentence explaining why the rename helps.

<details><summary>before</summary>

```
# PVE's `cpus` is the logical processor count. Renamed to
# `threads` here so the UI never has to guess which of the two
# numbers is which, which is exactly what "cores" vs "cpus" invites.
```

</details>

**after**

```
            # PVE's `cpus` is the logical processor count. Renamed to
            # `threads` so the UI never has to guess which of the two numbers
            # is which.
```

**`[243]`** `backend/proxploy/api/hosts.py:937` &middot; **63w → 37w** (41% cut) &middot; _security_  
Keep that the typed confirmation is a server-side gate and why, drop the doc citations.

<details><summary>before</summary>

```
# Always required, self or not (doc 02 §9, doc 08 §1/§9 row 14): detection
# can miss (a relocated install, an ambiguous hostname), so the typed
# prompt is the backstop even when self-detection would have said no.
# The frontend already gates Confirm on this matching before it ever
# sends the request; this is the server-side half of that gate, not
# merely a UI nicety.
```

</details>

**after**

```
    # Always required, self or not: detection can miss (a relocated install,
    # an ambiguous hostname), so the typed prompt is the backstop. The
    # frontend gates Confirm on it too; this is the server-side half, not a
    # UI nicety.
```

**`[244]`** `backend/proxploy/api/hosts.py:957` &middot; **147w → 81w** (45% cut) &middot; _buried-invariant_  
Keep the owner gate, the always-confirm rule and why it runs as a job, drop the doc citations and the before/after comparison.

<details><summary>before</summary>

```
Reboot or power off a Proxmox NODE, not a guest (doc 02 §9, doc 08 §1
    and §9 row 14).

    Owner-gated, same severity class as host.remove/host.credentials: this can
    take the whole node, and every guest it hosts, down. Always requires
    typing the node's name back, self or not -- GET .../status's `is_self`
    field lets the confirm dialog say so explicitly BEFORE the operator types
    anything, but the server enforces the same gate regardless of what the
    client already showed, since detection can miss.

    The actual PVE call runs as a job (services/guestjobs.py::run_host_power),
    the same reasoning as every other destructive PVE action: a synchronous
    200 with a bare UPID left this with no transcript in `job_events` and
    nothing to show in the bell popover (GET /jobs), unlike every other
    action in the product. The confirmation gate above still runs BEFORE
    anything is enqueued and is unchanged by the move.
    
```

</details>

**after**

```
    """Reboot or power off a Proxmox NODE, not a guest.

    Owner-gated, same severity as host.remove: this takes the node and every
    guest on it down. The node's name must be typed back, self or not,
    because self-detection can miss. GET .../status's `is_self` only lets the
    dialog warn earlier, it does not replace the gate.

    The PVE call runs as a job (services/guestjobs.py::run_host_power) so it
    leaves a transcript in `job_events`, like every other destructive action.
    The gate runs before anything is enqueued.
    """
```

**`[245]`** `backend/proxploy/api/hosts.py:1005` &middot; **84w → 52w** (38% cut) &middot; _narration_  
Keep the protocol fact and the fall-back-to-raw rule, drop the argument that grouping reads better.

<details><summary>before</summary>

```
# The high byte of PVE's raw PCI class code is the PCI-SIG base class, i.e.
# the heading `lspci` prints. Eleven devices as one flat list is a wall of
# hex; grouped by this they are four or five short groups. Named here rather
# than in the UI because it is a property of the protocol, not of the page,
# and an unrecognised byte falls back to the raw code instead of "Other",
# which would hide a device class we simply have not listed yet.
```

</details>

**after**

```
# The high byte of PVE's raw PCI class code is the PCI-SIG base class, the
# heading `lspci` prints. Named here, not in the UI, because it belongs to
# the protocol. An unrecognised byte falls back to the raw code rather than
# "Other", which would hide a class we have not listed yet.
```

**`[246]`** `backend/proxploy/api/hosts.py:1099` &middot; **102w → 82w** (20% cut) &middot; _buried-invariant_  
Keep the independent-gather contract and when the 502 fires, tighten it and drop the em dash.

<details><summary>before</summary>

```
Everything the node will say about itself that is not already on the
    Overview strip: disks, network interfaces, PCI devices, systemd services,
    and the subscription/DNS/time facts.

    Gathered INDEPENDENTLY, on purpose. Each of these is separately refusable
    on a real node — a token with a narrow privilege set answers some and
    rejects others, and a PVE without a given path 501s — so one refusal
    returns that section as null and names it in `unreadable` rather than
    costing the tab its other six sections. The 502 is reserved for the case
    where nothing at all could be read, which is the node being down.
    
```

</details>

**after**

```
    """Everything the node says about itself that is not on the Overview
    strip: disks, network, PCI devices, systemd services, subscription, DNS,
    time.

    Gathered INDEPENDENTLY, on purpose: each is separately refusable on a
    real node, a narrow token answers some and rejects others, and a PVE
    without a path 501s. One refusal returns that section as null and names
    it in `unreadable` rather than costing the tab its other six. The 502 is
    for nothing at all being readable: the node is down.
    """
```

**`[247]`** `backend/proxploy/api/hosts.py:1161` &middot; **45w → 42w** (7% cut) &middot; _buried-invariant_  
Keep the verify-before-replace rule, tighten the wording.

<details><summary>before</summary>

```
Replace a host's stored API token and/or SSH key.

    Owner-only. The new API token is verified against the node BEFORE it
    replaces the old one: a rotation that stores an unusable credential would
    take the host offline with no way back except editing the database.
    
```

</details>

**after**

```
    """Replace a host's stored API token and/or SSH key.

    Owner-only. The new API token is verified against the node BEFORE it
    replaces the old one: storing an unusable credential would take the host
    offline with no way back except editing the database.
    """
```

**`[248]`** `backend/proxploy/api/hosts.py:1190` &middot; **39w → 27w** (31% cut) &middot; _redundant_  
The field's own comment already explains the fallback; keep only the refusal reason.

<details><summary>before</summary>

```
# The default only covers a host with no monitoring credential
# yet. Once one exists, guessing "monitoring" for an unlabelled
# write is exactly how a lifecycle/console/backup token silently
# overwrote it before, so the caller now has to say which slot.
```

</details>

**after**

```
            # Once a monitoring credential exists, guessing "monitoring" for
            # an unlabelled write is how a lifecycle/console/backup token
            # silently overwrote it, so the caller has to say which slot.
```

**`[249]`** `backend/proxploy/api/hosts.py:1226` &middot; **19w → 15w** (21% cut) &middot; _narration_  
Only explains an absent encode call; one sentence covers it.

<details><summary>before</summary>

```
# generate_ed25519 returns the private half as bytes already; the
# secretstore takes bytes, so there is nothing to encode here.
```

</details>

**after**

```
        # generate_ed25519 returns bytes and the secretstore takes bytes, so
        # there is nothing to encode here.
```

**`[250]`** `backend/proxploy/api/hosts.py:1251` &middot; **24w → 18w** (25% cut) &middot; _narration_  
Keep the reason the slot is named explicitly, in one sentence.

<details><summary>before</summary>

```
# Which slot the token landed in, named explicitly rather than left
# for a future reader to parse out of the "api_token:<capability>"
# string in `rotated`.
```

</details>

**after**

```
        # Name the slot explicitly rather than making a reader parse it out of
        # the "api_token:<capability>" string in `rotated`.
```

**`[251]`** `backend/proxploy/api/hosts.py:1263` &middot; **138w → 79w** (43% cut) &middot; _buried-invariant_  
Keep the no-address trust boundary and the refuse-only use of fingerprints, tighten the prose.

<details><summary>before</summary>

```
Node names, never an address.

    The addresses come from a fresh /cluster/status read inside the handler,
    so a confused or hostile caller cannot aim an enrolment at a machine the
    cluster never named. There is deliberately no address field.

    `tls_fingerprints` is a different thing and is allowed for that reason: an
    address is an instruction, a fingerprint is an assertion about what the
    operator was shown, and it can aim nothing anywhere. It maps node name to
    the fingerprint discovery displayed, and it is ONLY ever used to refuse: a
    node presenting something else by the time the operator confirms is not
    added. It is never pinned, never a fallback when the probe fails, and
    never written to the database. Optional per node, so a caller that sends
    none behaves exactly as it did before the field existed.
    
```

</details>

**after**

```
    """Node names, never an address.

    The addresses come from a fresh /cluster/status read inside the handler,
    so a hostile caller cannot aim an enrolment at a machine the cluster never
    named. There is deliberately no address field.

    `tls_fingerprints` can aim nothing anywhere, so it is allowed: node name
    to the fingerprint discovery displayed, used ONLY to refuse a node
    presenting something else by the time the operator confirms. Never
    pinned, never a fallback when the probe fails, never stored.
    """
```

**`[252]`** `backend/proxploy/api/hosts.py:1292` &middot; **172w → 111w** (35% cut) &middot; _buried-invariant_  
Keep the owner scope, the always-200 partial contract and the never-copied list, cut the restatements around them.

<details><summary>before</summary>

```
Add the named nodes of this host's cluster as hosts of their own, each
    with its own copy of every API token this host holds.

    The write half of GET /{host_id}/peers above, and owner-scoped rather than
    admin for that reason: copying stored secrets into new rows is the same
    severity class as rotating them, which is why it sits next to
    rotate_credentials rather than next to discovery.

    One result row per requested node, always 200. The flow is inherently
    partial and a 502 for the whole request would throw away the record of the
    peers that did work, so a failure is a row saying what happened to that
    node, exactly as the frontend already treats one rejected capability token
    as that capability's failure and not the enrolment's.

    Never copied: the ssh_key credential, install consent, and the node shell
    opt-in. The SSH key is a root shell on the node, a different trust
    decision from an API token, and keeping them separate is the whole reason
    this route was allowed to exist.
    
```

</details>

**after**

```
    """Add the named nodes of this host's cluster as hosts of their own, each
    with its own copy of every API token this host holds.

    The write half of GET /{host_id}/peers, owner-scoped rather than admin
    because copying stored secrets into new rows is as severe as rotating
    them.

    One row per requested node, always 200: the flow is inherently partial,
    and a 502 would throw away the record of the peers that did work.

    Never copied: the ssh_key credential, install consent, the node shell
    opt-in. The SSH key is a root shell, a different trust decision from an
    API token, and keeping them separate is why this route exists at all.
    """
```

**`[253]`** `backend/proxploy/api/hosts.py:1338` &middot; **56w → 35w** (38% cut) &middot; _redundant_  
The standalone `local` flag quirk is stated in list_peers; keep the re-read reason and the guard.

<details><summary>before</summary>

```
# Re-read once for the whole request, because discovery and this call can
# be minutes apart. No cluster row means standalone, and a standalone
# node's single row carries no `local` flag on some versions, so without
# the `cluster and` guard it would offer itself as its own peer (the same
# guard list_peers makes, for the same reason).
```

</details>

**after**

```
    # Re-read once for the whole request: discovery and this call can be
    # minutes apart. The `cluster and` guard is list_peers's, for the same
    # reason: a standalone node's row carries no `local` flag on some versions.
```

**`[254]`** `backend/proxploy/api/hosts.py:1366` &middot; **49w → 31w** (37% cut) &middot; _redundant_  
The match rule is spelled out identically in list_peers; keep that it is re-applied rather than trusted.

<details><summary>before</summary>

```
# The skip rules, re-applied here rather than trusted from discovery.
# Cluster plus node name, never address, so the same machine enrolled
# under a second address or a DNS name is still recognised. A NULL
# cluster_name counts too: adding the same machine twice is the worse
# failure of the two.
```

</details>

**after**

```
        # The skip rules, re-applied here rather than trusted from discovery:
        # cluster plus node name, never address. A NULL cluster_name counts
        # too, since adding the same machine twice is the worse failure.
```

**`[255]`** `backend/proxploy/api/hosts.py:1379` &middot; **47w → 45w** (4% cut) &middot; _buried-invariant_  
Same fact, fewer words.

<details><summary>before</summary>

```
# The skip rules have already excluded the same machine, so a clash on
# hosts.name is a different machine wearing the name. That peer fails
# and the rest still enrol; no generated suffix, because a host
# silently wearing a name that is not its node name is worse.
```

</details>

**after**

```
        # The skip rules already excluded the same machine, so a clash on
        # hosts.name is a different machine wearing the name. That peer fails
        # and the rest still enrol; no generated suffix, because a host wearing
        # a name that is not its node name is worse.
```

**`[256]`** `backend/proxploy/api/hosts.py:1398` &middot; **43w → 33w** (23% cut) &middot; _buried-invariant_  
Keep the compare rule and the unreadable-counts-as-mismatch decision, tighten it.

<details><summary>before</summary>

```
# Case-insensitively, the way _connect already compares a stored pin.
# A probe that could not read the certificate counts as a mismatch:
# the operator approved a specific one and Proxploy cannot say this is
# it, which is exactly the case not to guess about.
```

</details>

**after**

```
        # Case-insensitively, the way _connect compares a stored pin. A probe
        # that could not read the certificate counts as a mismatch: the
        # operator approved a specific one and Proxploy cannot say this is it.
```

**`[257]`** `backend/proxploy/api/hosts.py:1495` &middot; **43w → 41w** (5% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
Poll this host now instead of waiting out the interval.

    Runs the poller's own cycle rather than a parallel implementation, so a
    forced sync and a scheduled one cannot disagree about what they ingest.
    Operator-level: it changes no configuration; it only refreshes cache.
    
```

</details>

**after**

```
    """Poll this host now instead of waiting out the interval.

    Runs the poller's own cycle rather than a parallel implementation, so a
    forced sync and a scheduled one cannot disagree about what they ingest.
    Operator-level: it changes no configuration, only cache.
    """
```

**`[258]`** `backend/proxploy/api/hosts.py:1532` &middot; **46w → 44w** (4% cut) &middot; _buried-invariant_  
Keep the justification for read-level access, tighten it.

<details><summary>before</summary>

```
The node's own task list, including work Proxploy did not start.

    Read-level on purpose: this is the same information the Proxmox UI shows
    anyone who can log in, and an operator debugging "why did my container
    restart at 3am" needs the tasks Proxploy did not cause.
    
```

</details>

**after**

```
    """The node's own task list, including work Proxploy did not start.

    Read-level on purpose: this is what the Proxmox UI shows anyone who can
    log in, and an operator debugging "why did my container restart at 3am"
    needs the tasks Proxploy did not cause.
    """
```


### 🟢 KEEP (48), unchanged

- **`[259]`** `31` &middot; _contract_ &middot; `# no host id yet (list)`
- **`[260]`** `34` &middot; _contract_ &middot; `# no host id yet (probe, create)`
- **`[261]`** `35` &middot; _security_ &middot; `# PUT /self writes an app setting, not a host row: ("settings", "manage") is`
- **`[262]`** `58` &middot; _security_ &middot; `Reject at the door with a 422 rather than letting an unparseable`
- **`[263]`** `226` &middot; _contract_ &middot; `Which capabilities to provision. Monitoring is always included by the`
- **`[264]`** `231` &middot; _surprising_ &middot; `# Independent of `capabilities` (services/pveum.py's own docstring on`
- **`[265]`** `288` &middot; _security_ &middot; `# write_audit redacts token_secret`
- **`[266]`** `309` &middot; _contract_ &middot; `# enrolment must survive a probe hiccup`
- **`[267]`** `367` &middot; _contract_ &middot; `# One query for every host's credential kinds, not one per host: this`
- **`[268]`** `382` &middot; _contract_ &middot; `# NULL means standalone or not-yet-polled, never "quorum lost":`
- **`[269]`** `386` &middot; _contract_ &middot; `# {} means probed and clean, null means never probed, and a`
- **`[270]`** `528` &middot; _external-quirk_ &middot; `# pve_addr when PVE gives one, else the corosync address it reports`
- **`[271]`** `547` &middot; _security_ &middot; `# Assigned only once both probes pass, so an errored row never`
- **`[272]`** `593` &middot; _contract_ &middot; `# Deliberately no probe here: verifying a changed address is`
- **`[273]`** `632` &middot; _contract_ &middot; `# Empty, not None, when the host never connected: "no gaps found" and "could`
- **`[274]`** `659` &middot; _contract_ &middot; `# Stored, not just returned: an operator who presses Test connection`
- **`[275]`** `765` &middot; _contract_ &middot; `# Rotate the API token: supply the new one, Proxploy never mints PVE`
- **`[276]`** `782` &middot; _security_ &middot; `# Regenerate the SSH keypair in-process. The new public key has to be`
- **`[277]`** `817` &middot; _contract_ &middot; `# Refuse with the list rather than a bare constraint error: the operator`
- **`[278]`** `843` &middot; _security_ &middot; `# malformed setting fails open, as in selfguard`
- **`[279]`** `845` &middot; _data-integrity_ &middot; `# One query before the delete: credentials only ever disappear via a host`
- **`[280]`** `856` &middot; _data-integrity_ &middot; `# RESTRICT: must go before the host`
- **`[281]`** `858` &middot; _data-integrity_ &middot; `# vms + host_credentials + metrics CASCADE`
- **`[282]`** `868` &middot; _external-quirk_ &middot; `PVE sends loadavg as strings. A UI should not have to parse them, and a`
- **`[283]`** `897` &middot; _contract_ &middot; `# 502, not 500: a token too narrow to read /nodes/{n}/status is the`
- **`[284]`** `936` &middot; _external-quirk_ &middot; `# "reboot" | "shutdown", Proxmox's own node-status verbs`
- **`[285]`** `1032` &middot; _surprising_ &middot; `# 0x030000 -> 0x03. A two-digit code (0x03) is already the base class.`
- **`[286]`** `1043` &middot; _external-quirk_ &middot; `# PVE uses -1 for "not a Ceph OSD"; passed through, that reads as an`
- **`[287]`** `1056` &middot; _external-quirk_ &middot; `# The group that decides whether this device can be handed to a guest`
- **`[288]`** `1063` &middot; _external-quirk_ &middot; `# systemd's keys are hyphenated, which no JS caller can address without`
- **`[289]`** `1073` &middot; _external-quirk_ &middot; `# NOTE: /nodes/{n}/network carries no link speed. There is no field to`
- **`[290]`** `1088` &middot; _external-quirk_ &middot; `# dns2/dns3 are ABSENT, not null, when unset. A fixed three-slot shape`
- **`[291]`** `1136` &middot; _external-quirk_ &middot; `# "notfound" is the ordinary state of an unsubscribed install. It is`
- **`[292]`** `1149` &middot; _contract_ &middot; `# Not one section came back. That is the node being unreachable, not a`
- **`[293]`** `1218` &middot; _data-integrity_ &middot; `# Only monitoring's own connectivity/last_seen bookkeeping: a`
- **`[294]`** `1237` &middot; _security_ &middot; `# The new key is NOT authorized on the node yet, so enrolment starts`
- **`[295]`** `1314` &middot; _contract_ &middot; `# A peer is never the first host, so unlike create_host the entitlement is`
- **`[296]`** `1329` &middot; _contract_ &middot; `# Still 200 with a row per node: the caller asked about these nodes and`
- **`[297]`** `1345` &middot; _security_ &middot; `# Pin the origin on the same code path its peers use, so two nodes of one`
- **`[298]`** `1362` &middot; _contract_ &middot; `# Same source and same fallback as discovery, so the address an`
- **`[299]`** `1392` &middot; _security_ &middot; `# This peer's own certificate, never the origin's: cluster nodes serve`
- **`[300]`** `1418` &middot; _data-integrity_ &middot; `# Nothing is written either way: a host with no monitoring`
- **`[301]`** `1433` &middot; _contract_ &middot; `# Copied so a cluster is never half inside a team and half`
- **`[302]`** `1446` &middot; _contract_ &middot; `# monitoring was verified just above`
- **`[303]`** `1454` &middot; _contract_ &middot; `# The host stays enrolled and works for everything that did`
- **`[304]`** `1459` &middot; _security_ &middot; `# Same secret store and same key version, so the blob is copied as`
- **`[305]`** `1477` &middot; _compatibility_ &middot; `# The two existing action names, so the audit filters and the activity`
- **`[306]`** `1560` &middot; _contract_ &middot; `Passthrough of one PVE task log, the missing half of the task feature.`

---

## `backend/proxploy/services/backupjobs.py`

3,827 → 3,047 words, 20% cut. 3 delete, 38 shorten, 36 keep.


### 🔴 DELETE (3)

**`[307]`** `backend/proxploy/services/backupjobs.py:1` &middot; 1w &middot; _generated_  
The file's own path as a header comment.

```
# backend/proxploy/services/backupjobs.py
```

**`[308]`** `backend/proxploy/services/backupjobs.py:34` &middot; 6w &middot; _example_  
Two sample volids restating the layouts the two regexes below already encode.

```
# vzdump archives:  local:backup/vzdump-lxc-150-2026_07_30-02_00_00.tar.zst
# PBS snapshots:    pbs-ds:backup/ct/150/2026-07-30T02:00:00Z
```

**`[309]`** `backend/proxploy/services/backupjobs.py:271` &middot; 6w &middot; _separator_  
Section banner with a phase and task number.

```
# --- backup mutations (Phase 6 Task 9) --------------------------------------
```


### 🟡 SHORTEN (38)

**`[310]`** `backend/proxploy/services/backupjobs.py:2` &middot; **101w → 89w** (12% cut) &middot; _buried-invariant_  
Keep the droppable-mirror rule and why this is not on the poll cycle, drop the doc citations.

<details><summary>before</summary>

```
Backup cache sync + backup mutation job handlers (doc 01 §7, doc 04 §backups).

`backups` is a droppable mirror, exactly like the poller's `vms` handling: each
sync writes what Proxmox currently reports and deletes rows whose volid vanished
upstream. Proxmox is the source of truth; this table only feeds the Backups page.

Unlike `vms`, this is NOT on the 30 s poll cycle; listing storage content is a
per-storage call, not part of the `/cluster/resources` bulk read the doc-02 §3
budget allows. It runs as a job: on demand from the page (when the cache is
stale) and after every backup mutation.
```

</details>

**after**

```
"""Backup cache sync and backup mutation job handlers.

`backups` is a droppable mirror, like the poller's `vms` handling: each sync
writes what Proxmox reports and deletes rows whose volid vanished upstream.
Proxmox is the source of truth; this table only feeds the Backups page.

Unlike `vms` this is NOT on the 30 s poll cycle: listing storage content is a
per-storage call, not part of the `/cluster/resources` bulk read the poll
budget allows. It runs as a job, on demand when the cache is stale and after
every mutation.
"""
```

**`[311]`** `backend/proxploy/services/backupjobs.py:42` &middot; **50w → 48w** (4% cut) &middot; _buried-invariant_  
Keep why the name is parsed, drop the doc citation.

<details><summary>before</summary>

```
-> ("ct"|"vm", vmid), or (None, None) for anything that isn't a backup.

    The volid is the identifier upstream (doc 04) and carries the guest it came
    from in both storage layouts; the content row's own `vmid` field is absent
    on some PBS shapes, so the name is parsed rather than trusted.
    
```

</details>

**after**

```
    """-> ("ct"|"vm", vmid), or (None, None) for anything that isn't a backup.

    The volid is the identifier upstream and carries the guest it came from in
    both storage layouts. The content row's own `vmid` field is absent on some
    PBS shapes, so the name is parsed rather than trusted.
    """
```

**`[312]`** `backend/proxploy/services/backupjobs.py:70` &middot; **122w → 106w** (13% cut) &middot; _buried-invariant_  
Keep the duplicate-row problem and the lowest-connected rule, tighten the prose.

<details><summary>before</summary>

```
Whether this host is the one that mirrors the cluster's SHARED backup
    datastores.

    A cluster's nodes all report the same archives off a shared store, and each
    node is a separate Host row with its own `backups` rows keyed
    ux_backups(host_id, volid), so a single backup of a single VM appeared once
    per enrolled node. Picking one host to own those rows is what makes the
    list say one archive once.

    The lowest CONNECTED host id in the cluster, so the answer is the same
    whichever host's sync runs first, and so a disconnected owner hands the
    rows to a sibling on the next sweep rather than taking the whole cluster's
    backup list offline with it. A standalone host always owns its own.
    
```

</details>

**after**

```
    """Whether this host is the one that mirrors the cluster's SHARED backup
    datastores.

    Every node reports the same archives off a shared store, and each node is
    its own Host row with its own `backups` rows keyed ux_backups(host_id,
    volid), so one backup of one VM appeared once per enrolled node. One
    owner is what makes the list say one archive once.

    The lowest CONNECTED host id, so the answer is the same whichever sync
    runs first, and a disconnected owner hands the rows to a sibling on the
    next sweep instead of taking the cluster's backup list offline with it. A
    standalone host owns its own.
    """
```

**`[313]`** `backend/proxploy/services/backupjobs.py:106` &middot; **100w → 67w** (33% cut) &middot; _implementation-diary_  
Keep why every node is read and why the enrolled node is the fallback, drop the note about a former ponytail marker.

<details><summary>before</summary>

```
# EVERY node of the cluster, not just the enrolled one. A node-local
# dump dir holds its own archives, and reading one node meant a
# multi-node user without a shared datastore simply never saw the rest
# of their backups. The node list is the poller's, which is the upgrade
# path this used to name as a ponytail note.
#
# Falling back to the enrolled node alone when there is no snapshot
# yet: before the first poll there is nothing to iterate, and a backup
# list that stayed empty until a poll landed would be a worse bug than
# the one this fixes.
```

</details>

**after**

```
        # EVERY node of the cluster, not just the enrolled one: a node-local
        # dump dir holds its own archives, so reading one node meant a
        # multi-node user without a shared datastore never saw the rest of
        # their backups. The node list is the poller's, falling back to the
        # enrolled node before the first poll, because an empty backup list
        # until a poll landed would be the worse bug.
```

**`[314]`** `backend/proxploy/services/backupjobs.py:122` &middot; **45w → 41w** (9% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# A shared store answers identically from every node, so it is read
# ONCE and recorded against the enrolled node. Reading it per node
# would turn one archive into one row per node, which is the same
# double count _syncs_shared_stores exists to prevent one level up.
```

</details>

**after**

```
        # A shared store answers identically from every node, so it is read
        # ONCE and recorded against the enrolled node. Reading it per node would
        # turn one archive into one row per node, the same double count
        # _syncs_shared_stores prevents one level up.
```

**`[315]`** `backend/proxploy/services/backupjobs.py:140` &middot; **37w → 27w** (27% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# `_type` rides along with `_storage`: PVE hands both back
# here, and _refuse_on_pbs / the sweep otherwise have to ask
# the poller, which has nothing to say before the first poll.
# `_node` is what tells two identical volids apart.
```

</details>

**after**

```
                    # `_type` rides along with `_storage`: PVE hands both back
                    # here, and asking the poller instead gets nothing before
                    # the first poll. `_node` tells two identical volids apart.
```

**`[316]`** `backend/proxploy/services/backupjobs.py:154` &middot; **58w → 45w** (22% cut) &middot; _data-integrity_  
Keep the lost-verdict failure mode, drop the closing aside about the migration.

<details><summary>before</summary>

```
# Rows written before `node` existed carry NULL, and matching them on
# the pair alone would MISS, build a second row for the same archive,
# and drop the first: every verdict this install had recorded would go
# with it on the first sync after upgrade. Adopted below instead, which
# is the whole backfill the migration deliberately does not do.
```

</details>

**after**

```
        # Rows written before `node` existed carry NULL, and matching on the
        # pair alone would MISS, build a second row for the same archive and
        # drop the first: every verdict this install recorded would go with it
        # on the first sync after upgrade. Adopted below instead.
```

**`[317]`** `backend/proxploy/services/backupjobs.py:172` &middot; **49w → 41w** (16% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# Same archive, now placed. Its verify_state and checked_at
# come with it. The OLD (None, volid) entry has to go from
# `existing` as well: the drop loop below deletes every key
# it did not see, and a row adopted under a new key would
# be deleted under its old one.
```

</details>

**after**

```
                    # Same archive, now placed; its verify_state and checked_at
                    # come with it. The OLD (None, volid) key has to go from
                    # `existing` too: the drop loop deletes every key it did not
                    # see, and would delete this row under its old one.
```

**`[318]`** `backend/proxploy/services/backupjobs.py:190` &middot; **37w → 34w** (8% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# Only when upstream actually reports one. A non-PBS store carries
# no `verification` at all, and writing "none" there erased the
# verdict services/backupjobs.py's own check had just written, on
# the next sweep. PBS still wins wherever PBS speaks.
```

</details>

**after**

```
            # Only when upstream actually reports one. A non-PBS store carries
            # no `verification` at all, and writing "none" there erased the
            # verdict this file's own check had just written. PBS still wins
            # wherever PBS speaks.
```

**`[319]`** `backend/proxploy/services/backupjobs.py:236` &middot; **42w → 41w** (2% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# Recorded even when zero backups were found: "the cache is empty" and
# "the cache was never filled" are different, and only this key can tell
# the GET route apart: otherwise a cluster with no backups re-enqueues
# a sync on every page load.
```

</details>

**after**

```
        # Recorded even when zero backups were found: "the cache is empty" and
        # "the cache was never filled" are different, and only this key tells
        # the GET route apart, otherwise a cluster with no backups re-enqueues a
        # sync on every page load.
```

**`[320]`** `backend/proxploy/services/backupjobs.py:248` &middot; **123w → 96w** (22% cut) &middot; _concurrency_  
Keep the WAL snapshot race, why rollback is load bearing and the caller requirement, cut the aside about the lock that looks like it helps.

<details><summary>before</summary>

```
A page that refetches while a sync is queued must not pile up a second.

    `db.rollback()` first, and it is load-bearing: the caller has already run
    queries on this session, which pins a read snapshot (SQLite in WAL gives a
    transaction a consistent view until it ends). A concurrent request that
    enqueued and committed its Job row AFTER that snapshot opened is invisible
    here, so the check returns False and a duplicate job is enqueued; which is
    exactly the race `api/backups.py::_sync_enqueue_lock` looks like it
    prevents but cannot: the lock serializes the code, not the visibility of
    the data. Ending the read transaction starts a fresh snapshot.

    Callers must therefore have no uncommitted writes pending on `db`. Every
    caller today is a read path.
    
```

</details>

**after**

```
    """A page that refetches while a sync is queued must not pile up a second.

    `db.rollback()` first, and it is load-bearing: the caller has already run
    queries on this session, pinning a read snapshot (SQLite in WAL holds a
    consistent view until the transaction ends). A request that enqueued and
    committed its Job row after that snapshot opened is invisible here, so
    the check returns False and a duplicate is enqueued. A lock cannot fix
    it: it serializes the code, not the visibility of the data.

    Callers must therefore have no uncommitted writes pending on `db`.
    """
```

**`[321]`** `backend/proxploy/services/backupjobs.py:307` &middot; **51w → 49w** (4% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# The ARCHIVE's node, not the host's. A node-local archive on a
# sibling of the enrolled node is only readable there: `pvesm path`
# on the wrong node finds nothing, and a restore would build the
# guest somewhere else entirely. Falls back to the enrolled node
# for a row synced before `node` existed.
```

</details>

**after**

```
            # The ARCHIVE's node, not the host's: a node-local archive on a
            # sibling of the enrolled node is only readable there, `pvesm path`
            # on the wrong node finds nothing, and a restore would build the
            # guest elsewhere. Falls back to the enrolled node for a row synced
            # before `node` existed.
```

**`[322]`** `backend/proxploy/services/backupjobs.py:319` &middot; **47w → 45w** (4% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
Every backup mutation ends here. Without it the cache still lists a
    volume that was just deleted, or misses one that was just created.

    A failed resync is logged, not raised: the mutation upstream already
    succeeded, and failing the job over a stale cache would misreport it.
    
```

</details>

**after**

```
    """Every backup mutation ends here. Without it the cache still lists a
    volume that was just deleted, or misses one just created.

    A failed resync is logged, not raised: the mutation upstream already
    succeeded, and failing the job over a stale cache would misreport it.
    """
```

**`[323]`** `backend/proxploy/services/backupjobs.py:336` &middot; **138w → 87w** (37% cut) &middot; _redundant_  
Keep the token-privilege reason and the honesty guard, drop the paragraph saying no new source of truth is introduced.

<details><summary>before</summary>

```
Blocking: (vmids Proxploy knows on this host, whether it was ever polled).

    The poller's own `apps`/`vms` rows, not a live Proxmox read, and that is
    deliberate: the backup token carries VM.Backup, Datastore.AllocateSpace and
    Datastore.Audit and no VM.Audit (services/pveum.py), so
    `cluster_resources()` on that token answers with zero guests for a node
    that is full of them. These are the same rows
    api/backups.py::_resolve_guests turns a guest selection into, and
    sync_host_backups already reads them for archive names, so no new source of
    truth is introduced here.

    The second element is the honesty guard. A Host row exists before the first
    poll cycle writes its guests, and "no rows yet" must never be read as "no
    guests": `last_seen_at` is set by the poller, so NULL means Proxploy has
    not looked and the caller must not draw a conclusion from an empty list.
    
```

</details>

**after**

```
    """Blocking: (vmids Proxploy knows on this host, whether it was ever polled).

    The poller's own `apps`/`vms` rows, not a live read: the backup token
    carries no VM.Audit (services/pveum.py), so `cluster_resources()` on it
    answers with zero guests for a node full of them.

    The second element is the honesty guard. A Host row exists before the
    first poll writes its guests, and "no rows yet" must never be read as "no
    guests": `last_seen_at` is the poller's, so NULL means the caller must
    conclude nothing from an empty list.
    """
```

**`[324]`** `backend/proxploy/services/backupjobs.py:365` &middot; **126w → 98w** (22% cut) &middot; _buried-invariant_  
Keep the log format and the never-backwards guarantee, trim the restatement of what `total` is.

<details><summary>before</summary>

```
Read vzdump's own percentage out of its task log, across `total` guests.

    PVE's task STATUS carries no percentage, so the only honest source is the
    log this task already streams: vzdump prints
    "INFO:  37% (4.1 GiB of 11.0 GiB) in 12s, read: ..." per guest, and starts
    again from 0% for the next one. So a guest's own figure is folded into the
    run's: guests finished, plus how far the current one is, over the total.

    `total` is the selection size, or the guests the last poll saw for a
    whole-host run. It can be wrong (a guest created since that poll is still
    backed up), which only makes the bar conservative: await_task never reports
    a percentage backwards, and the handler sets 100 at the end regardless.
    
```

</details>

**after**

```
    """Read vzdump's own percentage out of its task log, across `total` guests.

    PVE's task STATUS carries no percentage, so the only honest source is the
    log this task already streams: vzdump prints
    "INFO:  37% (4.1 GiB of 11.0 GiB) in 12s, read: ..." per guest and
    restarts at 0% for the next. A guest's figure is folded into the run's:
    guests finished, plus how far the current one is, over the total.

    `total` can be wrong (a guest created since the last poll is still backed
    up), which only makes the bar conservative: await_task never reports a
    percentage backwards.
    """
```

**`[325]`** `backend/proxploy/services/backupjobs.py:394` &middot; **130w → 118w** (9% cut) &middot; _buried-invariant_  
Keep pvesm path, pipefail and the reserved exit 90, tighten the framing sentences.

<details><summary>before</summary>

```
One shell command: resolve the archive's path, then read it back.

    One command rather than an SSH round trip per step, because the path is
    only useful to the reader that follows it, and because a single exit status
    is what the caller has to judge.

    `pvesm path`, not `/mnt/pve/<store>/dump/...`: the mount point belongs to
    the storage plugin, and a guessed path breaks on the first non-default one.

    `set -o pipefail` is load bearing. Without it the pipeline's status is the
    verifier's alone, and a truncated archive that makes `zstdcat` die still
    reports whatever `vma verify` said about the bytes it did get.

    Exit 90 is reserved for "the path could not be resolved", which is a broken
    check rather than a bad archive; the caller tells those two apart.
    
```

</details>

**after**

```
    """One shell command: resolve the archive's path, then read it back.

    One command rather than an SSH round trip per step: the path is only
    useful to the reader that follows it, and one exit status is what the
    caller judges.

    `pvesm path`, not `/mnt/pve/<store>/dump/...`: the mount point belongs to
    the storage plugin, so a guessed path breaks on the first non-default one.

    `set -o pipefail` is load bearing: without it the status is the
    verifier's alone, and a truncated archive that kills `zstdcat` still
    reports whatever `vma verify` made of the bytes it did get.

    Exit 90 means "the path could not be resolved", a broken check rather
    than a bad archive; the caller tells those apart.
    """
```

**`[326]`** `backend/proxploy/services/backupjobs.py:426` &middot; **37w → 36w** (3% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
Verify the archives nobody has verified yet, oldest first.

    Capped, because verifying reads every byte of every archive it takes and a
    year of daily backups is not a thing to start at 3am without a ceiling.
    
```

</details>

**after**

```
    """Verify the archives nobody has verified yet, oldest first.

    Capped: verifying reads every byte of every archive it takes, and a year
    of daily backups is not a thing to start at 3am without a ceiling.
    """
```

**`[327]`** `backend/proxploy/services/backupjobs.py:435` &middot; **127w → 74w** (42% cut) &middot; _implementation-diary_  
Keep why PBS is filtered and why the row's own type is the source, drop the account of what the sweep used to do at boot.

<details><summary>before</summary>

```
# Proxmox Backup Server verifies its own archives against stored digests on
# its own schedule, so a sweep that read them back over the network would
# spend hours re-answering a question PBS has already answered better. The
# per-archive routes refuse the same thing at the door
# (api/backups.py::_refuse_on_pbs); a schedule has no door, so it filters.
# The snapshot is the FALLBACK now, not the source. It is empty between
# boot and the first poll, and the scheduler starts in that same window, so
# a sweep due at boot used to read back every PBS archive on the host: the
# exact hours of redundant work this filter exists to prevent. Rows carry
# the type sync_host_backups was given by PVE; the snapshot only still
# covers rows synced before that column existed.
```

</details>

**after**

```
    # Proxmox Backup Server verifies its own archives against stored digests on
    # its own schedule, so a sweep reading them back over the network would
    # spend hours re-answering a question PBS answers better. The per-archive
    # routes refuse this at the door (api/backups.py::_refuse_on_pbs); a
    # schedule has no door, so it filters. The row's own storage_type is the
    # source, not the poll snapshot, which is empty between boot and the first
    # poll, exactly when the scheduler starts.
```

**`[328]`** `backend/proxploy/services/backupjobs.py:465` &middot; **23w → 20w** (13% cut) &middot; _narration_  
Keep the wording rule, drop the explanation of the phrasing it rejects.

<details><summary>before</summary>

```
# Not "0 archives have never been verified", which reads as a failure
# to find something rather than as the good news it is.
```

</details>

**after**

```
        # Worded as the good news it is: "0 archives have never been verified"
        # reads as a failure to find something.
```

**`[329]`** `backend/proxploy/services/backupjobs.py:476` &middot; **50w → 32w** (36% cut) &middot; _implementation-diary_  
Keep the never-backwards invariant that forces per-archive bands, drop the bug narrative.

<details><summary>before</summary>

```
# Each archive gets its OWN slice of the bar, so one archive's figure
# is the sweep's figure. It used to be handed the whole 5..100 range:
# the first archive reported 100, and since progress never moves
# backwards the bar then sat at 100 for the entire rest of the sweep.
```

</details>

**after**

```
        # Each archive gets its OWN slice of the bar. Progress never moves
        # backwards, so an archive handed the whole range would pin the bar at
        # 100 for the rest of the sweep.
```

**`[330]`** `backend/proxploy/services/backupjobs.py:490` &middot; **50w → 45w** (10% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
`backup.verify`: read one archive back and record whether it is intact.

    The only backup path that runs over SSH. Neither `pvesm path` nor
    `vma verify` exists on the PVE HTTP API, and a check that cannot be run is
    worse than a check that has to borrow the installer's transport.
    
```

</details>

**after**

```
    """`backup.verify`: read one archive back and record whether it is intact.

    The only backup path that runs over SSH: neither `pvesm path` nor
    `vma verify` exists on the PVE HTTP API, and a check that cannot run is
    worse than one borrowing the installer's transport.
    """
```

**`[331]`** `backend/proxploy/services/backupjobs.py:528` &middot; **76w → 60w** (21% cut) &middot; _external-quirk_  
Keep the two log behaviours and why a CT archive holds at `lo`, tighten it.

<details><summary>before</summary>

```
# `vma verify -v -` counts its way through the archive on stdout:
# "progress 42% (read 14431092736 bytes, duration 25 sec)". Read off the
# stream it is already logging, so the bar moves instead of sitting at the
# opening figure and jumping to done. `tar -tf -` says nothing of the kind,
# so a container archive still has no figure to show and holds at `lo`,
# which is honest: there is no progress to report, not 0% of one.
```

</details>

**after**

```
    # `vma verify -v -` counts through the archive on stdout: "progress 42%
    # (read 14431092736 bytes, duration 25 sec)". Read off the stream it is
    # already logging, so the bar moves instead of jumping from the opening
    # figure to done. `tar -tf -` says nothing of the kind, so a container
    # archive holds at `lo`: no progress to report, not 0% of one.
```

**`[332]`** `backend/proxploy/services/backupjobs.py:579` &middot; **95w → 79w** (17% cut) &middot; _buried-invariant_  
Keep why checks are separate jobs and why newest-per-guest is the match, trim the wording.

<details><summary>before</summary>

```
One `backup.verify` per archive the run that just finished wrote.

    A separate job per archive, deliberately. A backup that wrote its archive
    succeeded, whatever a later check says about the bytes, and reading an
    archive back can take as long again as writing it did.

    The newest archive per guest is what "this run wrote": the resync just
    before this recorded it, and the older ones were whatever ran before. There
    is no id to match on, vzdump names its own files and PVE reports no link
    between a task and the volids it produced.
    
```

</details>

**after**

```
    """One `backup.verify` per archive the run that just finished wrote.

    A separate job per archive: a backup that wrote its archive succeeded
    whatever a later check says, and reading one back can take as long again
    as writing it did.

    The newest archive per guest is what "this run wrote", recorded by the
    resync just before. There is no id to match on: vzdump names its own
    files and PVE reports no link between a task and its volids.
    """
```

**`[333]`** `backend/proxploy/services/backupjobs.py:591` &middot; **39w → 37w** (5% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# A host-wide run over a host Proxploy has never polled knows no vmids at
# all, so it falls back to the newest handful rather than every archive on
# the datastore. Each one is a full read over the network.
```

</details>

**after**

```
    # A host-wide run over a host Proxploy has never polled knows no vmids, so
    # it falls back to the newest handful rather than every archive on the
    # datastore: each one is a full read over the network.
```

**`[334]`** `backend/proxploy/services/backupjobs.py:625` &middot; **69w → 51w** (26% cut) &middot; _data-integrity_  
Keep that the filename is parsed back and only the note is ours, cut the closing cross-reference.

<details><summary>before</summary>

```
# The archive's FILENAME is PVE's and cannot be templated:
# vzdump-lxc-150-2026_08_24-02_00_00.tar.zst is parsed back into
# guest type, vmid and time by the backup listing and by restore,
# so a friendlier name would orphan the archive. The note is the
# one label that is ours to write, and it is what makes an archive
# identifiable as "Immich" rather than as 150. Synced into
# backups.notes by sync_backups and shown in Recent backups.
```

</details>

**after**

```
            # The archive's FILENAME is PVE's and cannot be templated:
            # vzdump-lxc-150-2026_08_24-02_00_00.tar.zst is parsed back into
            # guest type, vmid and time by the listing and by restore, so a
            # friendlier name would orphan it. The note is the one label that
            # is ours, and what makes an archive read as "Immich", not 150.
```

**`[335]`** `backend/proxploy/services/backupjobs.py:635` &middot; **40w → 26w** (35% cut) &middot; _narration_  
Keep why the storage is named in the transcript, drop the comparison to the migration preflight.

<details><summary>before</summary>

```
# Named in every line below. With no storage chosen PVE picks a backup store
# itself and the transcript then could not say where the archive went, which
# is the same gap the migration preflight closed by naming its target pool.
```

</details>

**after**

```
    # Named in every line below: with no storage chosen PVE picks a backup
    # store itself, and the transcript could not otherwise say where the
    # archive went.
```

**`[336]`** `backend/proxploy/services/backupjobs.py:645` &middot; **183w → 106w** (42% cut) &middot; _implementation-diary_  
Keep the empty-node behaviour, the alert consequence and why the call is skipped, drop the dated hardware investigation and job number.

<details><summary>before</summary>

```
# `all: 1` over a node with no guests is what made a backup of nothing
# report plain success. vzdump is handed an empty set, PVE finishes the
# task with exitstatus OK, and not one byte is written. Found on
# hardware 2026-08-18 on node1, whose `pct list` and `qm list` are both
# empty: job 157 stored {"exitstatus": "OK", "vmids": []} and the
# `backups` table gained zero rows, and the page reported a successful
# backup.
#
# This succeeds and says so rather than raising JobFailed. An empty node
# is not an operator error and it is not a Proxmox failure, and a red
# `backup.run` job here would raise a `backup_failed` alert, which reads
# the latest finished `backup.run` for the host (services/alerts.py), on
# a node that is simply empty. The harm was never the exit status, it was
# a bare success line that implies an archive now exists.
#
# The vzdump call is SKIPPED rather than made and then explained: PVE's
# OK for an empty job cannot be made to mean anything else, so not
# making the call is what leaves the transcript free to state what
# actually happened.
```

</details>

**after**

```
        # `all: 1` over a node with no guests made a backup of nothing report
        # plain success: vzdump gets an empty set, PVE finishes with exitstatus
        # OK, and not one byte is written.
        #
        # It succeeds and says so rather than raising JobFailed: an empty node
        # is not an operator error, and a red `backup.run` would raise a
        # `backup_failed` alert off the host's latest finished run
        # (services/alerts.py). The harm was never the exit status, it was a
        # success line implying an archive now exists.
        #
        # The call is SKIPPED rather than made and then explained, because
        # PVE's OK for an empty job cannot be made to mean anything else.
```

**`[337]`** `backend/proxploy/services/backupjobs.py:673` &middot; **40w → 38w** (5% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# Naming them answers "what is it backing up?" in the transcript
# itself. `all: 1` is still what PVE is asked for, so a guest the last
# poll has not seen yet is included even though it is not listed here.
```

</details>

**after**

```
        # Naming them answers "what is it backing up?" in the transcript. `all:
        # 1` is still what PVE is asked for, so a guest the last poll has not
        # seen is included even though it is not listed here.
```

**`[338]`** `backend/proxploy/services/backupjobs.py:687` &middot; **74w → 51w** (31% cut) &middot; _redundant_  
The OK-for-an-empty-vzdump point is made above; keep what `guests` actually counts.

<details><summary>before</summary>

```
# `guests` is what the Backups page counts, not the job's status: PVE
# returns exitstatus OK for a vzdump that wrote nothing, so a bare success
# cannot tell a real backup from an empty one. The early return above
# reports 0 for a node with nothing on it; here it is what was actually
# handed to vzdump (`known` for an all:1 run, which is the last poll's
# count and may undercount a guest created since).
```

</details>

**after**

```
    # `guests` is what the Backups page counts, not the job's status: PVE
    # returns exitstatus OK for a vzdump that wrote nothing. The early return
    # above reports 0 for an empty node; here it is what was handed to vzdump
    # (`known` for an all:1 run, the last poll's count, which may undercount).
```

**`[339]`** `backend/proxploy/services/backupjobs.py:701` &middot; **156w → 113w** (28% cut) &middot; _measurement-dump_  
Keep the roomiest-not-first rule and why it makes the refusal honest, cut the node1 narrative and the test name.

<details><summary>before</summary>

```
Blocking: the roomiest active storage on `node` whose `content` includes
    `want` ("rootdir" for a CT, "images" for a VM).

    Public because services/migrate.py needs the same pick for the same
    reason: PVE defaults a restore to `local`, which on a stock layout holds
    no rootfs.

    Roomiest, not first-listed. First-listed is how a test restore on node1
    wrote a 32 GiB scratch disk across NFS while a local LVM pool with nearly
    three times the room sat beside it, and, worse, how callers that pick a
    pool and THEN check free space (test_restore_backup) refused an archive
    that would have fitted somewhere else on the host: "choose another storage
    or make room", with room right there. Picking the largest makes that
    refusal honest, because if the largest eligible pool cannot hold it then no
    eligible pool can.

    A pool that does not report `avail` sorts last rather than counting as
    infinite, but still beats having no candidate at all.
    
```

</details>

**after**

```
    """Blocking: the roomiest active storage on `node` whose `content`
    includes `want` ("rootdir" for a CT, "images" for a VM).

    Public because services/migrate.py needs the same pick for the same
    reason: PVE defaults a restore to `local`, which on a stock layout holds
    no rootfs.

    Roomiest, not first-listed. First-listed put a scratch disk on NFS with a
    far larger local pool beside it, and made callers that pick a pool and
    THEN check free space refuse an archive that would have fitted elsewhere.
    Picking the largest makes that refusal honest: if the largest eligible
    pool cannot hold it, none can.

    A pool that does not report `avail` sorts last rather than counting as
    infinite.
    """
```

**`[340]`** `backend/proxploy/services/backupjobs.py:742` &middot; **167w → 116w** (31% cut) &middot; _redundant_  
Keep the contract and the allowed-to-miss rule, cut the discovered-list story that the call site tells again.

<details><summary>before</summary>

```
Blocking: make a restored container Proxploy's own, and say what it is.

    Returns the catalog slug it matched, or None.

    A CT is "tracked" only when an App row exists for (host_id, ctid), and a
    restore-as-new takes a FRESH vmid from cluster_nextid(), so the restored
    container matched nothing and turned up in the discovered list asking to be
    adopted. Which is absurd for the one container Proxploy knows the origin of
    perfectly well, because it put it there.

    The catalog is matched on the backup's own guest name, through the same
    exact normalised-name match the discovered list already suggests with
    (pollers/__init__.py::_suggest). That is a guess, and it is allowed to miss:
    a name the catalog does not know adopts with no slug, which is exactly what
    adopting it by hand would have produced. Not knowing what a container IS
    must not mean leaving it to ask.

    Nothing here is done for a VM. Vm rows are mirrored by the poller and have
    no adoption step at all.
    
```

</details>

**after**

```
    """Blocking: make a restored container Proxploy's own, and say what it is.

    Returns the catalog slug it matched, or None.

    A CT is "tracked" only when an App row exists for (host_id, ctid), and a
    restore-as-new takes a fresh vmid, so without this the restored container
    matches nothing and turns up in the discovered list asking to be adopted.

    Matched on the backup's guest name through the same normalised match the
    discovered list suggests with (pollers/__init__.py::_suggest). It may
    miss: a name the catalog does not know adopts with no slug, exactly as
    adopting it by hand would have.

    Nothing here is done for a VM: Vm rows are the poller's mirror and have
    no adoption step.
    """
```

**`[341]`** `backend/proxploy/services/backupjobs.py:811` &middot; **66w → 43w** (35% cut) &middot; _external-quirk_  
Keep the `local` fallback failure and the fix, drop the file citation.

<details><summary>before</summary>

```
# Nothing chosen: PVE falls back to `local`, which on a stock layout is
# a directory store that holds no rootfs or disk image, so every
# restore died on "storage 'local' does not support container
# directories". The UI sends no storage at all (api/backups.ts), so
# that was every restore-as-new. Pick a store on this node that can
# actually hold the guest instead of letting PVE guess wrong.
```

</details>

**after**

```
        # Nothing chosen: PVE falls back to `local`, a directory store that on
        # a stock layout holds no rootfs or disk image, so every restore died
        # on "storage 'local' does not support container directories". The UI
        # sends no storage, so that was every restore-as-new.
```

**`[342]`** `backend/proxploy/services/backupjobs.py:829` &middot; **52w → 40w** (23% cut) &middot; _buried-invariant_  
Keep which privileges force the second client, drop the hardware citation.

<details><summary>before</summary>

```
# The restore itself runs on LIFECYCLE, not on the backup client that read
# the archive above: a restore writes a guest config, so PVE checks
# VM.Allocate for a fresh vmid and SDN.Use for the NIC it carries, neither
# of which the Backup role holds. Proven on real hardware, doc 12 check 7.
```

</details>

**after**

```
    # The restore runs on LIFECYCLE, not the backup client that read the
    # archive: it writes a guest config, so PVE checks VM.Allocate for a fresh
    # vmid and SDN.Use for the NIC it carries, neither of which the Backup
    # role holds.
```

**`[343]`** `backend/proxploy/services/backupjobs.py:839` &middot; **68w → 27w** (60% cut) &middot; _redundant_  
adopt_restored's docstring already explains the adoption; keep only the ordering constraint against the poller wake.

<details><summary>before</summary>

```
# A container Proxploy restored is Proxploy's. Without this it landed on a
# fresh vmid, matched no App row, and turned up in the discovered list
# asking to be adopted, which is a strange question about the one guest we
# know the origin of. BEFORE the poller wake below, so the mirror refreshes
# with the row already there and the app never appears as discovered even
# for one cycle.
```

</details>

**after**

```
    # BEFORE the poller wake below, so the mirror refreshes with the App row
    # already there and the restored container never appears as discovered,
    # even for one cycle.
```

**`[344]`** `backend/proxploy/services/backupjobs.py:854` &middot; **46w → 30w** (35% cut) &middot; _narration_  
Keep why a second refresh is needed, tighten it.

<details><summary>before</summary>

```
# _resync above refreshes the BACKUP cache. A restore also creates (or
# overwrites) a guest, and that half of the picture belongs to the poller's
# mirror, so it needs the same wake create_vm gets or the restored guest
# takes a poll interval to appear in the list.
```

</details>

**after**

```
    # _resync above refreshes the BACKUP cache. A restore also creates or
    # overwrites a guest, and that half belongs to the poller's mirror, so it
    # needs the same wake create_vm gets.
```

**`[345]`** `backend/proxploy/services/backupjobs.py:867` &middot; **237w → 161w** (32% cut) &middot; _measurement-dump_  
Keep the refusal reasoning and one representative pair of numbers, cut the dated measurement write-up.

<details><summary>before</summary>

```
Blocking: the lowest free guest id at or above `floor`, or refuse.

    Not `cluster_nextid()`, which answers from 100 and would hand back an id in
    the range a human reads as "my guests". Ids from 900 up are the convention
    for throwaway work, and a test restore is the definition of throwaway.

    Read fresh from /cluster/resources rather than the poll snapshot: the
    snapshot can be a poll interval old, and this number is about to have a
    guest created on it.

    The refusal is the load-bearing part. /cluster/resources is filtered by the
    permissions of the token that asks, and a token that may not read guests is
    told so with an empty list, not with a 403. Measured on node1 2026-08-25:
    the lifecycle token got 2 rows (both nodes, no guests, no storage) while
    the monitoring token got 22 on the same cluster, which was running twelve
    guests. Read literally, that says "nothing is in use", so this function
    answered `floor` unconditionally: not the lowest free id, just the first
    one, safe only for as long as nobody has a guest on 900.

    A cluster with no guests is a real state, though, and must still get an id.
    The tell is not "no guests", it is "no guests AND no storage": any token
    that can read the cluster at all sees the storage rows, so guests-absent
    with storage-present is an honest answer about an empty node.
    
```

</details>

**after**

```
    """Blocking: the lowest free guest id at or above `floor`, or refuse.

    Not `cluster_nextid()`, which answers from 100 and would hand back an id
    a human reads as "my guests". Ids from 900 up are the convention for
    throwaway work.

    Read fresh from /cluster/resources, not the poll snapshot, which can be a
    poll interval old.

    The refusal is the load-bearing part. /cluster/resources is filtered by
    the asking token's permissions, and a token that may not read guests is
    told so with an empty list, not a 403: on one twelve-guest cluster the
    lifecycle token saw 2 rows where monitoring saw 22. Read literally that
    says "nothing is in use", so this would answer `floor` unconditionally,
    safe only until somebody has a guest on 900.

    An empty cluster is a real state and must still get an id. The tell is
    not "no guests", it is "no guests AND no storage": any token that can
    read the cluster sees the storage rows.
    """
```

**`[346]`** `backend/proxploy/services/backupjobs.py:909` &middot; **67w → 47w** (30% cut) &middot; _buried-invariant_  
Keep why the survey uses monitoring and what the fallback does, tighten it.

<details><summary>before</summary>

```
Blocking: `_scratch_vmid_from` asked through the right client.

    Monitoring, not the lifecycle client doing the restore: "which ids exist"
    is a read, and monitoring is the capability that reads. Any host being
    polled already has one, so this is not a new thing to configure in
    practice. A host without one falls back to the caller's own client, which
    then either answers honestly or trips the refusal above.
    
```

</details>

**after**

```
    """Blocking: `_scratch_vmid_from` asked through the right client.

    Monitoring, not the lifecycle client doing the restore: "which ids exist"
    is a read. Any polled host already has one; a host without one falls back
    to the caller's client, which then either answers honestly or trips the
    refusal above.
    """
```

**`[347]`** `backend/proxploy/services/backupjobs.py:974` &middot; **50w → 37w** (26% cut) &middot; _buried-invariant_  
Same facts, fewer words.

<details><summary>before</summary>

```
# Preflight, before anything is created: filling the pool to prove a backup
# is good is a worse outcome than not knowing. `size` is the COMPRESSED
# archive, so it is a floor on what the restore needs, never a ceiling; a
# store that fails this one would certainly have run out.
```

</details>

**after**

```
    # Preflight, before anything is created: filling the pool to prove a backup
    # is good is worse than not knowing. `size` is the COMPRESSED archive, so
    # it is a floor on what the restore needs, never a ceiling.
```


### 🟢 KEEP (36), unchanged

- **`[348]`** `55` &middot; _external-quirk_ &middot; `PVE reports `content` as a comma string ("backup,iso") in most shapes and`
- **`[349]`** `65` &middot; _data-integrity_ &middot; `# naive UTC, matching models.utcnow(): every other datetime column is naive`
- **`[350]`** `93` &middot; _contract_ &middot; `Blocking. Mirror one host's backup archives into `backups`.`
- **`[351]`** `132` &middot; _data-integrity_ &middot; `# Only the cluster's canonical host mirrors a shared store;`
- **`[352]`** `150` &middot; _data-integrity_ &middot; `# Keyed on (node, volid), matching ux_backups: the same volid on two`
- **`[353]`** `204` &middot; _data-integrity_ &middot; `# gone upstream = gone here; the mirror is droppable`
- **`[354]`** `211` &middot; _contract_ &middot; ``backup.sync`, every connected host, or one when `host_id` is given.`
- **`[355]`** `228` &middot; _contract_ &middot; `# noqa: BLE001  (one bad host can't kill the batch)`
- **`[356]`** `274` &middot; _contract_ &middot; `Blocking: host id -> (client, node, host name).`
- **`[357]`** `291` &middot; _data-integrity_ &middot; `Blocking: backup id -> (client, node, plain dict of the row's fields).`
- **`[358]`** `328` &middot; _contract_ &middot; `# noqa: BLE001`
- **`[359]`** `420` &middot; _external-quirk_ &middot; `# Explicitly bash: `set -o pipefail` is not in POSIX sh, and the whole`
- **`[360]`** `452` &middot; _data-integrity_ &middot; `# NULL storage_type is "not known to be PBS", which is what`
- **`[361]`** `498` &middot; _contract_ &middot; `# Sweep form, which is what a schedule fires. One job over several`
- **`[362]`** `550` &middot; _contract_ &middot; `# executor/keys.py raises this when the host carries no ssh_key.`
- **`[363]`** `557` &middot; _contract_ &middot; `# A non-zero status from the reader is a successful check with a bad`
- **`[364]`** `618` &middot; _contract_ &middot; ``backup.run`, one vzdump task over the selected guests, or all of them.`
- **`[365]`** `672` &middot; _contract_ &middot; `# empty selection means every guest on the node`
- **`[366]`** `724` &middot; _external-quirk_ &middot; `# PVE has been seen returning `content` both ways; migrate.py's`
- **`[367]`** `768` &middot; _data-integrity_ &middot; `# An in-place restore overwrote a guest whose row is still here, and a`
- **`[368]`** `779` &middot; _contract_ &middot; `# Same shape adopt_apps builds, so a restored app and a`
- **`[369]`** `790` &middot; _contract_ &middot; ``backup.restore`, in place (same vmid, force=1) or as new (fresh vmid).`
- **`[370]`** `826` &middot; _external-quirk_ &middot; `# overwrite the existing guest; PVE requires it stopped`
- **`[371]`** `925` &middot; _contract_ &middot; `Blocking: free space on one datastore, or None when PVE does not say.`
- **`[372]`** `938` &middot; _contract_ &middot; `Sizes for a job log line. GiB is the unit an operator reads a datastore`
- **`[373]`** `945` &middot; _contract_ &middot; ``backup.test_restore`: restore into a throwaway id, then destroy it.`
- **`[374]`** `962` &middot; _security_ &middot; `# Lifecycle, not backup: this really does create a guest, and the Backup`
- **`[375]`** `1001` &middot; _data-integrity_ &middot; `# Only once PVE accepted the call. A restore that never started proves`
- **`[376]`** `1005` &middot; _data-integrity_ &middot; `# The verdict is written BEFORE the cleanup, deliberately: a`
- **`[377]`** `1021` &middot; _contract_ &middot; `# noqa: BLE001`
- **`[378]`** `1022` &middot; _data-integrity_ &middot; `# Never swallowed. A guest nobody knows about, holding a disk,`
- **`[379]`** `1029` &middot; _contract_ &middot; `# The guest was created either way, so the poller's mirror is`
- **`[380]`** `1042` &middot; _contract_ &middot; ``backup.delete`, remove one archive upstream, then re-mirror.`
- **`[381]`** `1053` &middot; _external-quirk_ &middot; `# Some storage plugins delete synchronously and return no task id.`
- **`[382]`** `1061` &middot; _data-integrity_ &middot; ``backup.prune`, apply a retention spec for real. `spec` was built and`
- **`[383]`** `1068` &middot; _external-quirk_ &middot; `# `prune-backups` is hyphenated: a dict that gets unpacked at the proxmoxer`

---

## `backend/proxploy/services/catalog_metadata.py`

3,704 → 2,733 words, 26% cut. 6 delete, 22 shorten, 20 keep.


### 🔴 DELETE (6)

**`[384]`** `backend/proxploy/services/catalog_metadata.py:97` &middot; 1w &middot; _narration_  
Restates the field names below it.

```
# presentation
```

**`[385]`** `backend/proxploy/services/catalog_metadata.py:125` &middot; 2w &middot; _separator_  
Banner separator.

```
# --- shape helpers ---------------------------------------------------------
```

**`[386]`** `backend/proxploy/services/catalog_metadata.py:200` &middot; 5w &middot; _separator_  
Banner separator.

```
# --- mappers: upstream record -> writable-field payload --------------------
```

**`[387]`** `backend/proxploy/services/catalog_metadata.py:279` &middot; 6w &middot; _separator_  
Banner separator.

```
# --- fetch: primary, then the cold-start-only fallback ---------------------
```

**`[388]`** `backend/proxploy/services/catalog_metadata.py:367` &middot; 2w &middot; _separator_  
Banner separator.

```
# --- the upsert ------------------------------------------------------------
```

**`[389]`** `backend/proxploy/services/catalog_metadata.py:518` &middot; 10w &middot; _separator_  
Banner separator.

```
# --- fallback join: upstream's catalog slug vs its own script filename ------
```


### 🟡 SHORTEN (22)

**`[390]`** `backend/proxploy/services/catalog_metadata.py:1` &middot; **471w → 269w** (43% cut) &middot; _implementation-diary_  
Keeps the source, the api.github.com ceiling, the ownership rule, the state model and the failure policy; cuts the archaeology of the deleted scraper and the record-count tables.

<details><summary>before</summary>

```
Upstream presentation metadata for the App Store: names, descriptions,
categories, icons, website and docs links, cached into `catalog_entries` and
rendered cache-first.

WHERE THIS COMES FROM, AND WHY IT MOVED. The premise that per-app JSON lives
in community-scripts/ProxmoxVE is no longer true: that repo is scripts only
now, four .json files in the whole tree and all of them CI config. The
frontend was split out to ProxmoxVE-Frontend-Archive, which is archived and
frozen at 2026-03-12. The live source is a PocketBase instance,
db.community-scripts.org, which is what upstream's own self-hosted client
(ProxmoxVE-Local) reads: `pb.collection("script_scripts").getFullList({
expand: "categories,type" })`. This also explains the scrape this module
replaces (services/community_scripts_scrape.py, deleted): the Next.js flight
payload it parsed out of community-scripts.org/categories WAS this PocketBase
data. We were scraping a rendering of the API instead of calling the API.

One GET returns the whole corpus: 701 records, 1.87 MB, ~1.6 s, one page, and
every record carries a logo. It is a different host from api.github.com, so
the refresh's flat 2-call GitHub API ceiling (services/catalog.py header note)
is untouched: this module must never add an api.github.com call of any kind.

OWNERSHIP. Scripts stay the source of truth for what a thing IS; metadata is
the source of truth only for how it PRESENTS. The write set is exactly
WRITABLE_FIELDS and the enforcement is structural, not a convention: see the
comment on `apply_writable_fields`, which explains the five-slug near-miss
that makes it a hard rule.

TWO CATALOGS, ONE JOIN. Our discovery walks ct/*.sh and makes one row per
FILE; upstream's PocketBase is the catalog of what THEY consider an app. Where
they disagree, `upstream_state` records which kind of disagreement it is
(resolve_upstream_state), and that is the whole reason 42 of our 585
store-visible ct rows used to render as blank cards: 28 alpine-* rows upstream
models as an install method of a parent app, 5 soft-deleted records this sync
used to throw away, and 9 apps upstream dropped whose scripts are still in the
repo. State is provenance, written by the sync itself, never by a mapper, and
it decides STORE VISIBILITY only: never a type, never an installability.

FAILURE POLICY. Every stage is best-effort. The fallback to the archived
frontend fires only when PocketBase failed AND the cache holds no metadata at
all, i.e. a cold start on a fresh install with PocketBase down; a warm cache
plus a failed primary is a logged no-op that keeps the last good rows exactly
as they are. A missing slug match in either direction is normal and never an
error: 37 of our ct/ rows have no upstream record (mostly alpine-* variants
plus mysql) and upstream carries 85 slugs we never discover. Nothing here
raises into the refresh job, nothing here empties or half-writes the store.
Crucially, that also means a failed sync must not recompute `upstream_state`:
see the guard note on `sync_metadata`.
```

</details>

**after**

```
"""Upstream presentation metadata for the App Store: names, descriptions,
categories, icons, website and docs links, cached into `catalog_entries` and
rendered cache-first.

THE SOURCE is a PocketBase instance, db.community-scripts.org, collection
`script_scripts`. One GET returns the whole corpus, about 700 records in one
page. Cold-start fallback only: the frozen ProxmoxVE-Frontend-Archive, since
the ProxmoxVE repo itself is scripts now and carries no per-app JSON.
PocketBase is a different host from api.github.com, so the refresh's flat
2-call GitHub API ceiling (services/catalog.py header note) is untouched, and
this module must never add an api.github.com call of any kind.

OWNERSHIP. Scripts are the source of truth for what a thing IS; metadata only
for how it PRESENTS. The write set is exactly WRITABLE_FIELDS, enforced
structurally: see `apply_writable_fields`.

TWO CATALOGS, ONE JOIN. Discovery makes one row per ct/*.sh FILE; upstream's
PocketBase is the catalog of what THEY consider an app. `upstream_state`
records which kind of disagreement each row is (resolve_upstream_state), which
is what stops alpine-* variants, soft-deleted records and dropped apps from
rendering as blank cards. It is provenance, written by the sync and never by a
mapper, and it decides STORE VISIBILITY only: never a type, never an
installability.

FAILURE POLICY. Every stage is best-effort. The archive fallback fires only
when PocketBase failed AND the cache holds no metadata at all; a warm cache
plus a dead primary is a logged no-op that keeps the last good rows. A missing
slug match in either direction is normal, never an error. Nothing here raises
into the refresh job and nothing half-writes the store, and a failed sync must
not recompute `upstream_state`: see the guard on `sync_metadata`.
"""
```

**`[391]`** `backend/proxploy/services/catalog_metadata.py:71` &middot; **57w → 46w** (19% cut) &middot; _compatibility_  
Keeps why an archived repo is still pinned to a SHA; trims the closing clause.

<details><summary>before</summary>

```
# Cold-start fallback only. The repo is ARCHIVED and frozen, so pinning the
# SHA costs nothing and buys exact reproducibility: `main` on an archived repo
# can still move if it is ever unarchived, and this content is only ever read
# when the live source is already down, which is the worst possible moment to
# discover the shape changed.
```

</details>

**after**

```
# Cold-start fallback only. The repo is ARCHIVED and frozen, so pinning the
# SHA costs nothing and buys exact reproducibility: `main` on an archived repo
# can still move if it is ever unarchived, and this content is only ever read
# when the live source is already down.
```

**`[392]`** `backend/proxploy/services/catalog_metadata.py:82` &middot; **140w → 68w** (51% cut) &middot; _implementation-diary_  
Keeps the write-set rule and the forbidden names; cuts the history of the one time it widened.

<details><summary>before</summary>

```
# The complete set of columns upstream metadata is allowed to write. Not a
# guideline: `apply_writable_fields` loops over exactly this frozenset and
# does nothing else, so the write set cannot widen by accident.
#
# It HAS widened once, deliberately, from the original six to thirteen, when
# the Store gained sorting and tag chips. Read what did and did not change:
# every added name is another way upstream DESCRIBES an app (when its script
# was published, whether it runs on ARM, which port it serves), and the
# forbidden set is untouched. `slug`, `entry_type`, `script_path`,
# `installable` and `unsupported_reason` are still absent, still unwritable,
# and still protected by the same single loop and the same `_checked` guard,
# so the five-slug near-miss documented on `apply_writable_fields` cannot come
# back. Widening this set is a design decision to be argued for; weakening the
# mechanism around it is not.
```

</details>

**after**

```
# The complete set of columns upstream metadata is allowed to write. Not a
# guideline: `apply_writable_fields` loops over exactly this frozenset and
# does nothing else, so the write set cannot widen by accident. `slug`,
# `entry_type`, `script_path`, `installable` and `unsupported_reason` are
# absent and must stay absent: see the five-slug near-miss documented on
# `apply_writable_fields`. Widening this set is a design decision to argue
# for; weakening the mechanism around it is not.
```

**`[393]`** `backend/proxploy/services/catalog_metadata.py:105` &middot; **83w → 48w** (42% cut) &middot; _buried-invariant_  
Keeps the rule-not-a-list invariant and the runtipi reason; cuts the cross-reference essay.

<details><summary>before</summary>

```
# The prefix upstream uses for an Alpine build of an app it already lists.
# `resolve_upstream_state` turns this into a RULE rather than a list of the 28
# slugs that happen to be variants today, for exactly the reason
# services/catalog.py gives for detecting dual-variant addon collisions
# dynamically: `runtipi` was not in the investigation's snapshot of that set,
# and a hardcoded allowlist would have silently stopped working the moment
# upstream added one. The next alpine-* script upstream ships gets classified
# correctly with no code change.
```

</details>

**after**

```
# The prefix upstream uses for an Alpine build of an app it already lists.
# `resolve_upstream_state` treats this as a RULE, not a list of today's
# variant slugs: `runtipi` was missing from the original snapshot of that set,
# and a hardcoded allowlist stops working the moment upstream adds one.
```

**`[394]`** `backend/proxploy/services/catalog_metadata.py:137` &middot; **48w → 40w** (17% cut) &middot; _external-quirk_  
Keeps the non-ISO stamp quirk and the naive-UTC convention; trims the wording.

<details><summary>before</summary>

```
PocketBase stamps "2026-06-11 14:16:43.777Z", a space instead of the
    ISO "T", which `datetime.fromisoformat` rejects outright on older
    interpreters. Parsed defensively (a shape we do not recognise is None, not
    an exception) and stored naive UTC to match models.utcnow's convention,
    which every other DateTime column in this schema follows.
```

</details>

**after**

```
    """PocketBase stamps "2026-06-11 14:16:43.777Z", a space instead of the
    ISO "T", which `datetime.fromisoformat` rejects on older interpreters. A
    shape we do not recognise returns None rather than raising. Stored naive
    UTC to match models.utcnow, which every DateTime column here follows."""
```

**`[395]`** `backend/proxploy/services/catalog_metadata.py:157` &middot; **70w → 49w** (30% cut) &middot; _buried-invariant_  
Keeps the bool-or-nothing invariant; drops the row count attached to the example.

<details><summary>before</summary>

```
A real boolean or nothing. Upstream False is a genuine answer ("this
    app is not privileged") and must survive the None-stripping the mappers do
    on their way out, which is why this returns None ONLY for a value that is
    not a bool at all. Anything looser, `bool(value)`, would turn a missing
    field into a confident "no" on every one of the 9 rows we have no upstream
    record for.
```

</details>

**after**

```
    """A real boolean or nothing. Upstream False is a genuine answer ("this
    app is not privileged") and must survive the None-stripping the mappers
    do, so this returns None ONLY for a value that is not a bool at all.
    `bool(value)` would turn a missing field into a confident "no"."""
```

**`[396]`** `backend/proxploy/services/catalog_metadata.py:175` &middot; **38w → 32w** (16% cut) &middot; _data-integrity_  
Keeps the empty-list-is-unknown rule; trims the framing.

<details><summary>before</summary>

```
Upstream's architecture vocabulary, e.g. ["amd64", "arm64"], normalised
    only to the extent of dropping entries that are not non-empty strings. An
    empty list is None: "upstream told us nothing" rather than "this app runs
    on no architecture at all".
```

</details>

**after**

```
    """Upstream's architecture vocabulary, e.g. ["amd64", "arm64"], dropping
    entries that are not non-empty strings. An empty list is None: upstream
    told us nothing, rather than "this app runs on no architecture at all"."""
```

**`[397]`** `backend/proxploy/services/catalog_metadata.py:186` &middot; **48w → 42w** (12% cut) &middot; _implementation-diary_  
Keeps the raise-rather-than-drop rule and its reason; trims the retelling.

<details><summary>before</summary>

```
A mapper key outside WRITABLE_FIELDS is a programming error, and it
    raises here rather than being silently dropped. Silent dropping is the
    failure mode that lets someone add `"entry_type": ...` to a mapper, watch
    nothing break, and ship a write that only surfaces months later as five
    missing apps.
```

</details>

**after**

```
    """A mapper key outside WRITABLE_FIELDS is a programming error and raises
    here rather than being silently dropped. Silent dropping is what lets
    someone add `"entry_type": ...` to a mapper, watch nothing break, and ship
    a write that surfaces months later as missing apps."""
```

**`[398]`** `backend/proxploy/services/catalog_metadata.py:220` &middot; **50w → 35w** (30% cut) &middot; _redundant_  
Keeps the record-versus-script date distinction; drops the parser sentence _parse_upstream_ts already carries.

<details><summary>before</summary>

```
# Upstream's dates for the SCRIPT, not for the record: `updated` moves
# when someone fixes a typo in the description, `script_updated` moves
# when the script itself changes, and "recently updated" in the Store
# has to mean the second one. Same space-instead-of-T stamp as
# everything else here, so the same defensive parser.
```

</details>

**after**

```
        # Upstream's dates for the SCRIPT, not the record: `updated` moves
        # when someone fixes a typo in the description, `script_updated` when
        # the script itself changes, and the Store's "recently updated" has to
        # mean the second one.
```

**`[399]`** `backend/proxploy/services/catalog_metadata.py:237` &middot; **114w → 84w** (26% cut) &middot; _external-quirk_  
Keeps the archive schema differences, which are load bearing; compresses the why-a-subset-is-correct paragraph into a clause.

<details><summary>before</summary>

```
The archived frontend's `public/json/<slug>.json` to the same writable
    subset. Its schema is NOT the PocketBase one and the differences are load
    bearing: categories are integer ids that only resolve through
    metadata.json, the port field is `interface_port` not `port`, its only
    date is `date_created` (there is no script_updated and no has_arm at all),
    and `type` is "ct" where PocketBase says "lxc" (we ignore that one, see
    apply_writable_fields).

    It therefore maps a SUBSET of what the live source does, which is correct
    rather than a gap: this runs only on a cold start with PocketBase down,
    and an omitted key leaves the column untouched, so a card renders with
    fewer chips instead of with wrong ones.
```

</details>

**after**

```
    """The archived frontend's `public/json/<slug>.json` to the same writable
    subset. Its schema is NOT the PocketBase one and the differences are load
    bearing: categories are integer ids resolved through metadata.json, the
    port field is `interface_port`, its only date is `date_created` (no
    script_updated, no has_arm at all), and `type` is "ct" where PocketBase
    says "lxc" (ignored, see apply_writable_fields). Mapping a SUBSET is
    correct rather than a gap: an omitted key leaves the column untouched, so
    a card renders with fewer chips instead of with wrong ones."""
```

**`[400]`** `backend/proxploy/services/catalog_metadata.py:265` &middot; **57w → 44w** (23% cut) &middot; _compatibility_  
Keeps why the frozen archive must never write script_updated; tightens it.

<details><summary>before</summary>

```
# `date_created` is the archive's only date and it is the script's
# creation date, so it maps to script_created. Nothing here maps to
# script_updated: the archive is FROZEN at 2026-03-12, so any
# "recently updated" it could offer would be a lie about a snapshot
# that stopped moving, and omitting the key leaves whatever the live
# source last wrote.
```

</details>

**after**

```
        # `date_created` is the archive's only date and it is the script's
        # creation date. Nothing maps to script_updated: the archive is FROZEN
        # at 2026-03-12, so any "recently updated" it offered would be a lie,
        # and omitting the key leaves whatever the live source last wrote.
```

**`[401]`** `backend/proxploy/services/catalog_metadata.py:282` &middot; **126w → 81w** (36% cut) &middot; _implementation-diary_  
Keeps the raises contract and the is_deleted ingestion rule; cuts the list of five slugs and the used-to-be-skipped history.

<details><summary>before</summary>

```
slug -> (writable payload, full upstream record). Raises on anything
    that is not a usable corpus; `sync_metadata` owns the recovery decision,
    not this function.

    `is_deleted` records (9 of 701) are INGESTED, not dropped. They used to be
    skipped on the grounds that they describe scripts that no longer exist,
    which is upstream's truth and not ours: the ct/*.sh script is still in the
    repo, we still discovered it, and the row is still installable. Skipping
    the record only cost us the good name, description and logo it still
    carries, leaving a blank card. Five of ours are in this state (booklore,
    flatnotes, litellm, minio, spliit), and a described-and-badged card beats
    a blank badged one. `resolve_upstream_state` reads `is_deleted` off the
    record kept here and marks those rows "delisted".
    
```

</details>

**after**

```
    """slug -> (writable payload, full upstream record). Raises on anything
    that is not a usable corpus; `sync_metadata` owns the recovery decision.

    `is_deleted` records are INGESTED, not dropped. Upstream retiring a record
    is upstream's truth, not ours: the ct/*.sh script is still in the repo and
    the row is still installable, so skipping the record only costs the name,
    description and logo it still carries and leaves a blank card.
    `resolve_upstream_state` reads `is_deleted` off the record kept here and
    marks those rows "delisted".
    """
```

**`[402]`** `backend/proxploy/services/catalog_metadata.py:318` &middot; **99w → 74w** (25% cut) &middot; _measurement-dump_  
Keeps the fetch scope and the 404-normal / metadata.json-fatal rule; cuts the file counts.

<details><summary>before</summary>

```
The frozen archive, for the cold-start case only.

    Fetches metadata.json (the 26-category vocabulary the per-slug integer ids
    resolve through) and then ONLY the per-slug files for slugs we actually
    discovered. The archive holds 487 of them; walking all 487 would spend
    requests on apps that have no catalog row to attach to, and a slug with no
    catalog row is ignored outright anyway.

    A per-slug 404 is the normal "the archive never had this app" answer and
    is skipped silently. Only a failure to read metadata.json itself is fatal,
    because without the vocabulary every category would resolve to nothing.
    
```

</details>

**after**

```
    """The frozen archive, for the cold-start case only.

    Fetches metadata.json (the category vocabulary the per-slug integer ids
    resolve through) and then only the per-slug files for slugs we actually
    discovered, since a slug with no catalog row is ignored anyway. A per-slug
    404 is the normal "the archive never had this app" answer and is skipped
    silently. Only a failure to read metadata.json is fatal, because without
    the vocabulary every category resolves to nothing.
    """
```

**`[403]`** `backend/proxploy/services/catalog_metadata.py:370` &middot; **165w → 114w** (31% cut) &middot; _external-quirk_  
Keeps the structural rule and the upstream typing quirk that makes it one; trims the surrounding argument.

<details><summary>before</summary>

```
THE only place upstream metadata is allowed to touch a catalog row.

    One loop over WRITABLE_FIELDS, and deliberately no other assignment to a
    CatalogEntry attribute anywhere in it, so it is structurally incapable of
    writing `slug`, `entry_type`, `script_path`, `installable`,
    `unsupported_reason` or the resource defaults, whatever some future
    upstream field ends up being called.

    WHY THIS IS A HARD RULE AND NOT A CONVENTION. Upstream types five slugs
    differently than we do, and those five are exactly the dual-variant
    collision slugs: coolify, runtipi, dockge, komodo, dokploy. Each ships
    BOTH a standalone `ct/<slug>.sh` full-LXC installer and a
    `tools/addon/<slug>.sh` install-into-an-existing-container script, so
    PocketBase calls them "addon" while our tree discovery correctly calls
    them "ct". Wiring `entry_type` to metadata here would read as a tidy
    one-line improvement, and it would silently drop five genuinely
    LXC-typed apps out of the Store entirely and break dual-variant collision
    detection (services/catalog.py::_classify_path). Upstream is not wrong; it
    is answering a different question than the Store asks. Do not
    "helpfully" let metadata set type later.
    
```

</details>

**after**

```
    """THE only place upstream metadata is allowed to touch a catalog row.

    One loop over WRITABLE_FIELDS and no other assignment to a CatalogEntry
    attribute, so it is structurally incapable of writing `slug`,
    `entry_type`, `script_path`, `installable`, `unsupported_reason` or the
    resource defaults.

    A HARD RULE, NOT A CONVENTION. Upstream types five slugs differently than
    we do, and they are exactly the dual-variant collision slugs: coolify,
    runtipi, dockge, komodo, dokploy. Each ships BOTH a standalone
    `ct/<slug>.sh` full-LXC installer and a `tools/addon/<slug>.sh` script, so
    PocketBase calls them "addon" while our tree discovery correctly calls
    them "ct". Wiring `entry_type` to metadata here would silently drop five
    genuinely LXC-typed apps out of the Store and break dual-variant collision
    detection (services/catalog.py::_classify_path).
    """
```

**`[404]`** `backend/proxploy/services/catalog_metadata.py:414` &middot; **81w → 49w** (40% cut) &middot; _narration_  
Keeps what the two hidden states mean; cuts the note about it being a set in one place.

<details><summary>before</summary>

```
# Every upstream_state the Store grid refuses to show. Kept as a set beside
# the criterion below so adding another hidden state is one edit in one place,
# not a hunt through the callers. Two so far, and they are genuinely different
# phenomena rather than one with two names, which is why they are two values:
# a "variant" is a real app upstream shows under its parent's card, while a
# "superseded" row is a dead script upstream renamed out from under us.
```

</details>

**after**

```
# Every upstream_state the Store grid refuses to show. Two so far, and they
# are genuinely different phenomena rather than one with two names: a
# "variant" is a real app upstream shows under its parent's card, while a
# "superseded" row is a dead script upstream renamed out from under us.
```

**`[405]`** `backend/proxploy/services/catalog_metadata.py:424` &middot; **178w → 136w** (24% cut) &middot; _buried-invariant_  
Keeps the single-source rule and the load-bearing IS NULL explanation; compresses the incident story.

<details><summary>before</summary>

```
THE single source of truth for which catalog rows the Store may show.

    Both callers depend on this and neither may re-implement it:

      - api/catalog.py::list_catalog, for `entry_type=ct` (the grid itself)
      - api/search.py, for the store group of the command palette

    THIS EXISTS BECAUSE THE RULE WAS ONCE WRITTEN TWICE AND ONLY ONE COPY GOT
    UPDATED. The variant exclusion landed in list_catalog and never reached
    search, so the palette went on offering all 28 alpine-<parent> phantoms
    plus all 84 non-ct rows, each with an `href: /store/<slug>` pointing at a
    card the Store does not render. Every one of them opened Not Found, and a
    user reported it. Anything that decides "can the Store show this row"
    calls this function; nothing re-derives it.

    The explicit IS NULL arm is not redundant. In SQL, `upstream_state NOT IN
    ('variant')` evaluates to NULL for a never-synced row, and NULL is not
    true, so a bare NOT IN would silently return zero rows on a fresh install
    where nothing has been synced yet: an empty Store and an empty search,
    from a predicate that looks correct.
    
```

</details>

**after**

```
    """THE single source of truth for which catalog rows the Store may show.

    Both callers depend on this and neither may re-implement it:

      - api/catalog.py::list_catalog, for `entry_type=ct` (the grid itself)
      - api/search.py, for the store group of the command palette

    It is one function because the rule was once written twice and only one
    copy got updated: the variant exclusion landed in list_catalog and never
    reached search, so the palette went on offering variant and non-ct rows
    whose `/store/<slug>` href opened Not Found.

    The explicit IS NULL arm is not redundant. In SQL, `upstream_state NOT IN
    ('variant')` is NULL for a never-synced row, and NULL is not true, so a
    bare NOT IN returns zero rows on a fresh install where nothing has synced
    yet: an empty Store and an empty search, from a predicate that looks
    correct.
    """
```

**`[406]`** `backend/proxploy/services/catalog_metadata.py:455` &middot; **459w → 320w** (30% cut) &middot; _buried-invariant_  
Keeps the four state definitions, the ordering rule and the non-ct None rationale; cuts the slug inventories and the alpine-komodo edge essay.

<details><summary>before</summary>

```
Which answer upstream's catalog gives for this slug.

    `alias` is the upstream slug this row matched by NAME rather than by slug
    (resolve_name_matches). It is consulted instead of the row's own slug when
    present, so a name-matched row is "listed" like any other match.

    "listed"   a live upstream record matched. The normal case, ~547 ct rows.
    "delisted" the record is there but flagged is_deleted. Upstream retired
               the app; the script is still in the repo, so the row stays
               installable and the Store badges it.
    "unlisted" no record at all and not a variant. Upstream dropped the app
               outright (mysql, readarr, overseerr and 6 more; readarr and
               overseerr are genuinely discontinued projects). Also badged.
    "variant"  an alpine-<parent> row with no record of its own whose <parent>
               IS in the payload. Upstream models Alpine as an install METHOD
               of a parent app, not as its own app: the `syncthing` record
               carries install_methods [{type: "default", os: "Debian 13"},
               {type: "alpine", os: "Alpine 3.24"}], so ct/alpine-syncthing.sh
               is the IMPLEMENTATION of that second method. Upstream shows one
               Syncthing card; without this we showed two and ours was blank.
               Hidden from the Store grid (api/catalog.py::list_catalog), and
               ONLY from the grid: still a ct row, still installable, still in
               the full catalog table and still reachable by slug.

    A RULE, not a list of the 28 slugs that are variants today: see
    ALPINE_PREFIX. The order matters and is the entire subtlety. An own record
    always wins, which is what keeps the 8 alpine-* apps upstream really does
    list as their own app (alpine-borgbackup-server, alpine-cinny,
    alpine-it-tools, alpine-nextcloud, alpine-ntfy, alpine-redlib,
    alpine-valkey, alpine-wakapi) "listed" and on the grid, with no name of
    theirs written down anywhere.

    alpine-komodo is the interesting edge: parent `komodo` is alive upstream
    but has NO alpine install method, so upstream describes no home for this
    script at all. The rule still calls it a variant, and that is the right
    answer for the grid: `komodo` already has a card, and a second blank
    "Alpine Komodo" card next to it is exactly the duplicate this change
    exists to remove.

    A parent that is itself delisted still counts as present: an alpine build
    of a retired app is a variant of a badged card, not an app of its own.

    Non-ct rows that match nothing return None rather than "unlisted", and
    that is deliberate. The Store is ct-only, so the question this column
    answers is not asked of them, and the rows it protects are OUR OWN
    synthetic slugs: coolify-addon, dockge-addon, dokploy-addon,
    komodo-addon and runtipi-addon are names we invent in dual-variant
    collision detection (services/catalog.py::_classify_path). Upstream can
    never have a record for a slug we made up, so marking them "unlisted"
    would badge them as retired when upstream lists the app perfectly well
    under its real slug.
    
```

</details>

**after**

```
    """Which answer upstream's catalog gives for this slug.

    `alias` is the upstream slug this row matched by NAME rather than by slug
    (resolve_name_matches), consulted instead of the row's own slug when
    present, so a name-matched row is "listed" like any other match.

    "listed"   a live upstream record matched. The normal case.
    "delisted" the record is there but flagged is_deleted. Upstream retired
               the app; the script is still in the repo, so the row stays
               installable and the Store badges it.
    "unlisted" no record at all and not a variant. Upstream dropped the app
               outright. Also badged.
    "variant"  an alpine-<parent> row with no record of its own whose <parent>
               IS in the payload. Upstream models Alpine as an install METHOD
               of a parent app, not as its own app, so ct/alpine-syncthing.sh
               implements the `syncthing` record's alpine method. Upstream
               shows one Syncthing card; without this we showed two and ours
               was blank. Hidden from the Store grid and ONLY from the grid:
               still a ct row, still installable, still in the full catalog
               table and still reachable by slug.

    A RULE, not a list of today's variant slugs: see ALPINE_PREFIX. Order is
    the entire subtlety. An own record always wins, which is what keeps the
    alpine-* apps upstream really does list as their own app "listed" and on
    the grid, with no name of theirs written down anywhere. A parent that is
    itself delisted still counts as present: an alpine build of a retired app
    is a variant of a badged card, not an app of its own.

    Non-ct rows that match nothing return None rather than "unlisted", and
    deliberately so: the rows that protects are OUR OWN synthetic slugs,
    coolify-addon, dockge-addon, dokploy-addon, komodo-addon and
    runtipi-addon, invented in dual-variant collision detection
    (services/catalog.py::_classify_path). Upstream can never have a record
    for a slug we made up, so "unlisted" would badge them as retired when
    upstream lists the app perfectly well under its real slug.
    """
```

**`[407]`** `backend/proxploy/services/catalog_metadata.py:521` &middot; **65w → 60w** (8% cut) &middot; _surprising_  
Keeps why the normalisation must stay dumb; trims the closing comparison.

<details><summary>before</summary>

```
Lowercased with every non-alphanumeric stripped. Deliberately the
    dumbest normalisation that could possibly work: no stemming, no edit
    distance, no prefix or substring matching. Every one of those turns a
    missing match into a WRONG match, and a wrong match here means one app's
    description, icon and website rendered on a different app's card, which is
    worse than the blank card it was trying to fix.
```

</details>

**after**

```
    """Lowercased with every non-alphanumeric stripped. Deliberately the
    dumbest normalisation that could possibly work: no stemming, no edit
    distance, no prefix or substring matching. Every one of those turns a
    missing match into a WRONG match, which puts one app's description, icon
    and website on another app's card, and that is worse than the blank card
    it was trying to fix."""
```

**`[408]`** `backend/proxploy/services/catalog_metadata.py:535` &middot; **258w → 185w** (28% cut) &middot; _measurement-dump_  
Keeps the confirmed example and the three guardrails; cuts the measured-match essay and the closing repeat of the write rule.

<details><summary>before</summary>

```
our slug -> upstream slug, for rows an exact slug match missed.

    WHY THIS EXISTS. Upstream's own catalog slug sometimes differs from
    upstream's own script filename, and our discovery takes the slug from the
    filename. Confirmed live: `ct/apache-airflow.sh` exists and is genuinely
    installable, while the PocketBase record is slug `airflow`, name "Apache
    Airflow", alive. Exact matching misses it, so a real app renders blank and
    badged as retired.

    A FALLBACK, AND ONLY A FALLBACK. Every guardrail here is about the future
    rather than today's data. Measured over the real catalog, this produces
    exactly ONE match (apache-airflow -> airflow) and zero ambiguities, so the
    question is not "does it work now" but "what does it do the day upstream
    ships two apps with similar names":

    - An exact slug match always wins, and an upstream record already claimed
      by one is never a candidate. Nothing this function does can move a row
      that already matched.
    - It must be 1:1 in BOTH directions. If one normalized name reaches two
      upstream records, or two of our rows reach the same record, the match is
      DECLINED, not tie-broken. Ambiguity is a reason to leave the card blank
      and let a human look, not an invitation to guess.
    - ct rows only, matching the rest of this module: the Store is ct-only,
      and our synthetic *-addon slugs must never name-match anything.

    It changes WHICH upstream record a row matches. It changes nothing about
    what may be written: the same WRITABLE_FIELDS loop applies the result, so
    `slug`, `entry_type`, `script_path`, `installable` and
    `unsupported_reason` remain as unwritable as they were.
    
```

</details>

**after**

```
    """our slug -> upstream slug, for rows an exact slug match missed.

    Upstream's own catalog slug sometimes differs from upstream's own script
    filename, and our discovery takes the slug from the filename. Confirmed
    live: `ct/apache-airflow.sh` is genuinely installable while the PocketBase
    record is slug `airflow`, name "Apache Airflow", alive. Exact matching
    misses it, so a real app renders blank and badged as retired.

    A FALLBACK, AND ONLY A FALLBACK. It produces one match today, so the
    guardrails are about the day upstream ships two apps with similar names:

    - An exact slug match always wins, and a record already claimed by one is
      never a candidate. Nothing here can move a row that already matched.
    - It must be 1:1 in BOTH directions. If one normalized name reaches two
      upstream records, or two of our rows reach the same record, the match is
      DECLINED, not tie-broken. Ambiguity means leave the card blank and let a
      human look, not guess.
    - ct rows only: the Store is ct-only, and our synthetic *-addon slugs must
      never name-match anything.

    It changes WHICH upstream record a row matches, never what may be written.
    """
```

**`[409]`** `backend/proxploy/services/catalog_metadata.py:600` &middot; **240w → 192w** (20% cut) &middot; _buried-invariant_  
Keeps the three required conditions and the strict-False rule; compresses the netvisor story to the lines that prove the shape is real.

<details><summary>before</summary>

```
Slugs of rename leftovers: a dead script upstream renamed out from
    under us, still sitting in the repo under its old name.

    CONFIRMED LIVE. Upstream renamed `netvisor` to `scanopy`. `ct/scanopy.sh`
    plus `install/scanopy-install.sh` exist, so we correctly carry `scanopy`,
    listed and installable. The old `ct/netvisor.sh` is still in the repo with
    NO install script, and its `APP=` line was updated to read "Scanopy", so
    the grid showed TWO cards both called "Scanopy", one working and one
    blank.

    THREE CONDITIONS, ALL REQUIRED, and the third alone is nowhere near
    enough. A duplicate name on the grid is not by itself evidence of
    anything: `valkey` and `alpine-valkey` are both listed upstream, both
    legitimate, and both must keep their cards. So a leftover must be

      1. UNMATCHED upstream ("unlisted"), because upstream deleting the record
         is the actual evidence of the rename,
      2. UNINSTALLABLE, because the missing install script is what makes it a
         corpse rather than a second way to install the same thing, and
      3. name-colliding, case-insensitively, with a ct row that IS listed.

    `installable is False` strictly, never None. Classification is lazy and
    runs in the background, so a freshly discovered row is None until it has
    been looked at, and hiding a card on the strength of "we have not checked
    yet" is a guess. One sync later, once the backlog pass has run, the row
    resolves properly. A card that is briefly visible beats a card that is
    wrongly hidden.
    
```

</details>

**after**

```
    """Slugs of rename leftovers: a dead script upstream renamed out from
    under us, still sitting in the repo under its old name. Confirmed live:
    upstream renamed `netvisor` to `scanopy` and left `ct/netvisor.sh` behind
    with NO install script and an `APP=` line updated to read "Scanopy", so
    the grid showed TWO cards both called "Scanopy", one working, one blank.

    THREE CONDITIONS, ALL REQUIRED, and the third alone is nowhere near
    enough: `valkey` and `alpine-valkey` share a name, are both listed
    upstream, and both must keep their cards. So a leftover must be

      1. UNMATCHED upstream ("unlisted"), because upstream deleting the record
         is the actual evidence of the rename,
      2. UNINSTALLABLE, because the missing install script is what makes it a
         corpse rather than a second way to install the same thing, and
      3. name-colliding, case-insensitively, with a ct row that IS listed.

    `installable is False` strictly, never None. Classification is lazy, so a
    freshly discovered row is None until it has been looked at, and hiding a
    card on the strength of "we have not checked yet" is a guess. A card that
    is briefly visible beats a card that is wrongly hidden.
    """
```

**`[410]`** `backend/proxploy/services/catalog_metadata.py:646` &middot; **266w → 213w** (20% cut) &middot; _measurement-dump_  
Keeps the join rule, the state-provenance rule, the two-pass reason and the logging policy; drops the row counts and the repetition.

<details><summary>before</summary>

```
Apply a fetched corpus onto existing rows. Slug is the join key, exact
    match first and always; `resolve_name_matches` is consulted only for rows
    that missed. Rows we have and upstream does not keep their
    discovery-derived name and their catalog_categories.py heuristic category
    so nothing goes blank, and end with null metadata columns, which is
    precisely what marks them unmatched. Slugs upstream has and we do not
    create nothing: the scripts tree decides what exists.

    `upstream_state` is recomputed for EVERY row here, matched or not, because
    an unmatched row is exactly what the "unlisted"/"variant" answers are
    about. It is provenance in the same sense metadata_source is: written by
    the sync itself, never sourced from a mapper, and never part of
    WRITABLE_FIELDS. It changes what the Store SHOWS and nothing else, so
    nothing in this function touches slug, entry_type, script_path,
    installable or unsupported_reason. Reached only on a successful fetch; see
    sync_metadata.

    TWO PASSES, because "superseded" cannot be decided one row at a time: it
    asks whether some OTHER row ended up listed under the same name, which is
    only knowable once every row has a state.

    Counts are returned, not logged per slug. 37 unmatched ct/ rows and 85
    unmatched upstream slugs are the steady state, so per-slug logging here
    would be a hundred lines of noise per refresh describing normality. Name
    matches are the exception and ARE logged individually: there is one of
    them, it is a heuristic rather than an exact join, and a wrong one must be
    discoverable by a human reading a log rather than invisible until someone
    notices a card describing the wrong app.
    
```

</details>

**after**

```
    """Apply a fetched corpus onto existing rows. Slug is the join key, exact
    match first and always; `resolve_name_matches` is consulted only for rows
    that missed. Rows we have and upstream does not keep their
    discovery-derived name and their heuristic category so nothing goes blank,
    and end with null metadata columns, which is what marks them unmatched.
    Slugs upstream has and we do not create nothing: the scripts tree decides
    what exists.

    `upstream_state` is recomputed for EVERY row here, matched or not, because
    an unmatched row is exactly what "unlisted" and "variant" are about. Like
    metadata_source it is provenance: written by the sync, never sourced from
    a mapper, never part of WRITABLE_FIELDS, and it changes what the Store
    SHOWS and nothing else. Reached only on a successful fetch; see
    sync_metadata.

    TWO PASSES, because "superseded" asks whether some OTHER row ended up
    listed under the same name, which is only knowable once every row has a
    state.

    Counts are returned, not logged per slug: unmatched rows in both
    directions are the steady state, so per-slug logging would be a wall of
    noise describing normality. Name matches ARE logged individually, because
    a heuristic join that goes wrong must be discoverable by a human reading a
    log rather than by noticing a card describing the wrong app.
    """
```

**`[411]`** `backend/proxploy/services/catalog_metadata.py:728` &middot; **151w → 138w** (9% cut) &middot; _buried-invariant_  
THE GUARD stays intact; only the restatement around it is trimmed.

<details><summary>before</summary>

```
Refresh every matched row's presentation fields from upstream.

    Returns an outcome dict for the caller to log; it does not raise on an
    upstream failure. `ok: False` means nothing was written and the last good
    rows are untouched, which is a usable store, not a broken one.

    THE GUARD. `upstream_state` is recomputed ONLY on the ok-True path, i.e.
    only inside upsert_metadata, only after a fetch actually returned a
    corpus. Every early return below leaves each row's previous state exactly
    as it was. This is not a nicety: state is resolved by ABSENCE from the
    payload, so a sync that recomputed it from an empty or missing corpus
    would mark the entire catalog "unlisted" and badge every card in the
    Store as retired, off one upstream outage on a cold cache. An empty
    corpus already raises in fetch_pocketbase rather than returning {}, and
    these returns are the second half of the same guarantee.
    
```

</details>

**after**

```
    """Refresh every matched row's presentation fields from upstream.

    Returns an outcome dict for the caller to log; it does not raise on an
    upstream failure. `ok: False` means nothing was written and the last good
    rows are untouched, which is a usable store, not a broken one.

    THE GUARD. `upstream_state` is recomputed ONLY on the ok-True path, inside
    upsert_metadata, only after a fetch actually returned a corpus. Every
    early return below leaves each row's previous state exactly as it was.
    State is resolved by ABSENCE from the payload, so recomputing it from an
    empty or missing corpus would mark the entire catalog "unlisted" and badge
    every card in the Store as retired, off one upstream outage on a cold
    cache. An empty corpus already raises in fetch_pocketbase, and these
    returns are the second half of the same guarantee.
    """
```


### 🟢 KEEP (20), unchanged

- **`[412]`** `63` &middot; _external-quirk_ &middot; `# The live source. `perPage=1000` covers the whole corpus (701 records) in a`
- **`[413]`** `99` &middot; _contract_ &middot; `# upstream's own dates for the script, which the Store sorts on`
- **`[414]`** `101` &middot; _data-integrity_ &middot; `# the card tags, all tri-state: None means unknown, never "no"`
- **`[415]`** `115` &middot; _external-quirk_ &middot; `# Cold-start fallback fan-out. Same reasoning as catalog.classify_many's`
- **`[416]`** `128` &middot; _data-integrity_ &middot; `Non-empty strings only. An upstream empty string is "we have nothing`
- **`[417]`** `167` &middot; _surprising_ &middot; `A usable TCP port or nothing. `bool` is excluded explicitly because it`
- **`[418]`** `203` &middot; _contract_ &middot; `One `script_scripts` record to its writable subset. Keys are omitted`
- **`[419]`** `343` &middot; _external-quirk_ &middot; `# noqa: BLE001 - one unreachable slug file must not`
- **`[420]`** `344` &middot; _external-quirk_ &middot; `# cost us the several hundred that did come back`
- **`[421]`** `349` &middot; _generated_ &middot; `# noqa: BLE001`
- **`[422]`** `399` &middot; _data-integrity_ &middot; `Provenance is written by the sync, never sourced from a mapper: a`
- **`[423]`** `407` &middot; _surprising_ &middot; `# `raw` already carries the pinned ct/install script pair for classified`
- **`[424]`** `569` &middot; _contract_ &middot; `# Candidates: upstream records no exact slug match has claimed. A`
- **`[425]`** `580` &middot; _contract_ &middot; `# And the same collapse on our side: two unmatched rows normalizing alike`
- **`[426]`** `637` &middot; _contract_ &middot; `Whether the cache is warm. This is the entire fallback trigger: a warm`
- **`[427]`** `696` &middot; _data-integrity_ &middot; `# A name-matched row records a DIFFERENT source, so the join that`
- **`[428]`** `703` &middot; _contract_ &middot; `# Second pass: rename leftovers, which need every state resolved first.`
- **`[429]`** `747` &middot; _generated_ &middot; `# noqa: BLE001 - see module docstring`
- **`[430]`** `749` &middot; _contract_ &middot; `# Warm cache: the Store already renders real metadata, so the`
- **`[431]`** `759` &middot; _generated_ &middot; `# noqa: BLE001`

---

## `backend/proxploy/models/__init__.py`

3,630 → 3,091 words, 15% cut. 8 delete, 31 shorten, 30 keep.


### 🔴 DELETE (8)

**`[432]`** `backend/proxploy/models/__init__.py:49` &middot; 2w &middot; _separator_  
Banner separator.

```
# --- Identity & access -----------------------------------------------------
```

**`[433]`** `backend/proxploy/models/__init__.py:169` &middot; 1w &middot; _separator_  
Banner separator.

```
# --- Infrastructure --------------------------------------------------------
```

**`[434]`** `backend/proxploy/models/__init__.py:247` &middot; 1w &middot; _separator_  
Banner separator.

```
# --- Apps ------------------------------------------------------------------
```

**`[435]`** `backend/proxploy/models/__init__.py:547` &middot; 2w &middot; _separator_  
Banner separator.

```
# --- Jobs & scheduling -----------------------------------------------------
```

**`[436]`** `backend/proxploy/models/__init__.py:602` &middot; 2w &middot; _separator_  
Banner separator.

```
# --- Notifications & alerting ----------------------------------------------
```

**`[437]`** `backend/proxploy/models/__init__.py:706` &middot; 1w &middot; _separator_  
Banner separator.

```
# --- Metrics ---------------------------------------------------------------
```

**`[438]`** `backend/proxploy/models/__init__.py:737` &middot; 1w &middot; _separator_  
Banner separator.

```
# --- Backups ---------------------------------------------------------------
```

**`[439]`** `backend/proxploy/models/__init__.py:788` &middot; 3w &middot; _separator_  
Banner separator.

```
# --- Audit, entitlements, settings ----------------------------------------
```


### 🟡 SHORTEN (31)

**`[440]`** `backend/proxploy/models/__init__.py:20` &middot; **98w → 82w** (16% cut) &middot; _surprising_  
Keeps the naive-UTC plus browser-local-time trap and the never-double-suffix rule; trims the prose.

<details><summary>before</summary>

```
The one way to serialize a datetime for an API response.

    Every timestamp column here is stored as naive UTC (see utcnow() above),
    so a bare dt.isoformat() carries no offset. A browser's
    `new Date("...")` reads an offset-less string as LOCAL time, not UTC,
    which silently shifts every timestamp shown in the UI by the viewer's
    own timezone. Naive input gets a literal "Z" appended so it reads as
    UTC unambiguously. A value that already carries a timezone is left as
    isoformat() renders it (its own offset is already unambiguous), so this
    never double-suffixes. None passes through as None.
    
```

</details>

**after**

```
    """The one way to serialize a datetime for an API response.

    Every timestamp column here is stored as naive UTC (see utcnow above), so
    a bare dt.isoformat() carries no offset, and a browser's `new Date("...")`
    reads an offset-less string as LOCAL time. That silently shifts every
    timestamp in the UI by the viewer's own timezone. Naive input gets a
    literal "Z" appended. A value that already carries a timezone is left as
    isoformat() renders it, so this never double-suffixes. None stays None.
    """
```

**`[441]`** `backend/proxploy/models/__init__.py:70` &middot; **80w → 70w** (12% cut) &middot; _ticket-history_  
Drops the Phase 8 Task 8 plan history; keeps why it is a real column and the atomic single-use pattern.

<details><summary>before</summary>

```
One row per recovery code (Phase 8 Task 8 amendment: the plan's
    zero-migration design packed these inside `users.totp_secret_enc`; a
    real column replaces that so burning a code is an ordinary UPDATE,
    never a decrypt-mutate-re-encrypt of a blob shared with a concurrent
    TOTP verify). `code_hash_enc` is the
    argon2 hash (services/authn.py::hash_password's idiom, never the raw
    code) Fernet-encrypted at rest via SecretStore, same as
    `totp_secret_enc`. Burning sets `used_at`; the atomic single-use
    guarantee is `UPDATE ... WHERE id = ? AND used_at IS NULL`
    (services/consoletickets.py::redeem_ticket's exact pattern).
```

</details>

**after**

```
    """One row per recovery code. A real column rather than packing these into
    `users.totp_secret_enc`, so burning a code is an ordinary UPDATE and never
    a decrypt-mutate-re-encrypt of a blob shared with a concurrent TOTP
    verify. `code_hash_enc` is the argon2 hash (never the raw code)
    Fernet-encrypted at rest via SecretStore, same as `totp_secret_enc`.
    Burning sets `used_at`; the atomic single-use guarantee is
    `UPDATE ... WHERE id = ? AND used_at IS NULL`
    (services/consoletickets.py::redeem_ticket's exact pattern)."""
```

**`[442]`** `backend/proxploy/models/__init__.py:101` &middot; **126w → 111w** (12% cut) &middot; _security_  
Keeps the trust boundary and the cannot-become-a-session rule; trims the framing.

<details><summary>before</summary>

```
A browser that has already proved the second factor, so the code step
    can be skipped on this device until `expires_at`.

    Deliberately the same shape as `sessions` above, and hashed the same way
    (services/authn.py::_th): the expiry and revocation semantics of a session
    are already proven, and a second, subtly different set of rules around a
    credential that BYPASSES two-factor is exactly where a hole would open.

    It is not a session and cannot become one. `resolve_session` reads the
    sessions table only, so this token grants nothing on its own: it is checked
    after a password has already been verified, and the most it can do is skip
    the code. Bound to `user_id` so a device trusted for one account cannot
    skip the second factor on another.
    
```

</details>

**after**

```
    """A browser that has already proved the second factor, so the code step
    can be skipped on this device until `expires_at`.

    Same shape as `sessions` above and hashed the same way
    (services/authn.py::_th): a second, subtly different set of rules around a
    credential that BYPASSES two-factor is exactly where a hole opens.

    It is not a session and cannot become one. `resolve_session` reads the
    sessions table only, so this token grants nothing on its own: it is
    checked after a password has already been verified, and the most it can do
    is skip the code. Bound to `user_id`, so a device trusted for one account
    cannot skip the second factor on another.
    """
```

**`[443]`** `backend/proxploy/models/__init__.py:191` &middot; **69w → 64w** (7% cut) &middot; _buried-invariant_  
Keeps the tri-state meaning and the informational-only rule; drops the doc section reference.

<details><summary>before</summary>

```
# Whether the stored token lacks Sys.PowerMgmt (host reboot/power off),
# recomputed at enrolment and by POST /hosts/{id}/test, same idiom as
# last_error above. NULL means "not checked yet" -- distinct from False
# ("checked, and granted") -- so a host enrolled before this existed
# reads as unknown rather than a false "granted". Informational only: it
# is never used to refuse a power attempt, only to warn ahead of one
# (services/pveum.py NODE_POWER_PRIVILEGE, doc 08 §2/§9).
```

</details>

**after**

```
    # Whether the stored token lacks Sys.PowerMgmt (host reboot/power off),
    # recomputed at enrolment and by POST /hosts/{id}/test, same idiom as
    # last_error above. NULL means "not checked yet", distinct from False
    # ("checked, and granted"), so a host enrolled before this existed reads as
    # unknown rather than a false "granted". Informational only: never used to
    # refuse a power attempt, only to warn ahead of one (services/pveum.py
    # NODE_POWER_PRIVILEGE).
```

**`[444]`** `backend/proxploy/models/__init__.py:199` &middot; **105w → 91w** (13% cut) &middot; _external-quirk_  
Keeps the tri-state rule and the read-only /etc/pve consequence; drops the dated verification note.

<details><summary>before</summary>

```
# Whether this host's cluster has quorum, read straight off the `quorate`
# field of its /cluster/status cluster row every poll cycle. NULL for a
# standalone node (no cluster row, so the question does not apply) and for
# a host not polled since this existed; False ONLY when PVE said so.
#
# It is a health fact, not a privilege one: without quorum /etc/pve is
# read-only, so every install, storage edit and guest config write fails,
# while /cluster/resources and /version keep answering perfectly. Reached
# for real on 2026-08-18 (doc 12 check 12) with every host still reading
# `connected`, which is the lie this column exists to stop telling.
```

</details>

**after**

```
    # Whether this host's cluster has quorum, read off the `quorate` field of
    # its /cluster/status cluster row every poll cycle. NULL for a standalone
    # node (no cluster row, so the question does not apply) and for a host not
    # polled since this existed; False ONLY when PVE said so.
    #
    # A health fact, not a privilege one: without quorum /etc/pve is read-only,
    # so every install, storage edit and guest config write fails, while
    # /cluster/resources and /version keep answering perfectly and every host
    # still reads `connected`. That is the lie this column stops telling.
```

**`[445]`** `backend/proxploy/models/__init__.py:210` &middot; **67w → 62w** (7% cut) &middot; _data-integrity_  
Keeps the three meanings of the value and why it is re-probed; drops the doc check reference.

<details><summary>before</summary>

```
# {capability: [missing privilege, ...]}, {} when every configured token is
# fully granted, NULL when never probed. A capability mapped to null means
# PVE refused /access/permissions for that token: "could not tell", not
# clean. Refreshed by the poll loop on a slow cadence and by
# POST /hosts/{id}/test, because a role gains privileges over time and an
# old token's only other symptom is a 403 mid-job (doc 12 checks 17, 18).
```

</details>

**after**

```
    # {capability: [missing privilege, ...]}, {} when every configured token is
    # fully granted, NULL when never probed. A capability mapped to null means
    # PVE refused /access/permissions for that token: "could not tell", not
    # clean. Refreshed by the poll loop on a slow cadence and by
    # POST /hosts/{id}/test, because a role gains privileges over time and an
    # old token's only other symptom is a 403 mid-job.
```

**`[446]`** `backend/proxploy/models/__init__.py:218` &middot; **104w → 41w** (61% cut) &middot; _redundant_  
The first six lines describe per-content-type pool columns that no longer exist on this model; only the install_consent_at half is live.

<details><summary>before</summary>

```
# The pools this host's operator chose, remembered so the question is asked
# once rather than on every install. NULL means "not chosen yet", which is
# deliberately distinct from any pool name: services/appstore.py's
# resolution order treats NULL as "fall through", and a stored name as an
# answer to re-validate. Per content type, because a node can have one
# rootdir candidate and several vztmpl ones.
# When this host's operator acknowledged that installs run third-party
# scripts as root here. Per host rather than per install: the acknowledgement
# is about the host, and re-asking on every install is friction that
# surfaces no new information. NULL means not acknowledged.
```

</details>

**after**

```
    # When this host's operator acknowledged that installs run third-party
    # scripts as root here. Per host rather than per install: the acknowledgement
    # is about the host, and re-asking on every install is friction that
    # surfaces no new information. NULL means not acknowledged.
```

**`[447]`** `backend/proxploy/models/__init__.py:258` &middot; **80w → 63w** (21% cut) &middot; _buried-invariant_  
Keeps the NULL fallback and the migrate-in-the-PVE-UI case; drops the doc check reference.

<details><summary>before</summary>

```
# The node the CT actually runs on, refreshed every poll cycle. Assumed to be
# the host's node before this existed, which is true while installs pick the
# host and the migration handler repoints the row, and wrong the moment a CT
# is migrated in the Proxmox UI instead (doc 12 check 18, where the VM side of
# the same shape broke every action on a clustered pair). NULL falls back to
# Host.node_name, so an unpolled row behaves exactly as before.
```

</details>

**after**

```
    # The node the CT actually runs on, refreshed every poll cycle. Before this
    # existed it was assumed to be the host's node, which is true while installs
    # pick the host and the migration handler repoints the row, and wrong the
    # moment a CT is migrated in the Proxmox UI instead. NULL falls back to
    # Host.node_name, so an unpolled row behaves exactly as before.
```

**`[448]`** `backend/proxploy/models/__init__.py:277` &middot; **83w → 70w** (16% cut) &middot; _data-integrity_  
Keeps the never-overwrite-what-the-operator-set rule and why the whole URL is stored; tightens it.

<details><summary>before</summary>

```
# The URL the install script printed about itself, captured when the
# install job finished (services/appstore.py). Kept as the whole URL and
# kept SEPARATE from the three fields above, which is what makes "never
# overwrite what the operator set" structural rather than a check that can
# be got wrong: nothing derived from a log is ever written into a field a
# person owns. It is evidence, so it is stored as the installer stated it
# rather than as three values picked out of it.
```

</details>

**after**

```
    # The URL the install script printed about itself, captured when the
    # install job finished (services/appstore.py). Kept whole and kept SEPARATE
    # from the three fields above, which is what makes "never overwrite what
    # the operator set" structural rather than a check that can be got wrong:
    # nothing derived from a log is written into a field a person owns. It is
    # evidence, so it is stored as the installer stated it.
```

**`[449]`** `backend/proxploy/models/__init__.py:296` &middot; **68w → 62w** (9% cut) &middot; _surprising_  
Keeps why net_sampled_at exists and why updated_at cannot stand in; trims the wording.

<details><summary>before</summary>

```
# netin/netout are counters since the container booted, not rates. The raw
# readings are kept because the next cycle's diff needs them, and
# net_sampled_at because the gap between two cycles is not
# poll_interval_s: the poll loop backs off exponentially on a failing
# host. TimestampMixin.updated_at cannot stand in for it either, since any
# other write to this row (a rename, a migration) would move it and
# silently shorten the window.
```

</details>

**after**

```
    # netin/netout are counters since the container booted, not rates. The raw
    # readings are kept because the next cycle's diff needs them, and
    # net_sampled_at because the gap between two cycles is not poll_interval_s:
    # the poll loop backs off exponentially on a failing host.
    # TimestampMixin.updated_at cannot stand in either, since any other write
    # to this row would move it and silently shorten the window.
```

**`[450]`** `backend/proxploy/models/__init__.py:310` &middot; **64w → 58w** (9% cut) &middot; _data-integrity_  
Keeps the countdown-not-verdict rule and the clearing condition; tightens it.

<details><summary>before</summary>

```
# When the poller first failed to find this app's CT in a cycle it was
# willing to trust (pollers._absence_is_trustworthy). NULL is the normal
# state and means "last seen present". Non-NULL is a countdown, not a
# verdict: the row is only reaped once the absence has survived
# APP_REAP_AFTER_S of further trustworthy cycles, and any cycle that finds
# the CT again clears it back to NULL.
```

</details>

**after**

```
    # When the poller first failed to find this app's CT in a cycle it was
    # willing to trust (pollers._absence_is_trustworthy). NULL means "last seen
    # present". Non-NULL is a countdown, not a verdict: the row is reaped only
    # once the absence survives APP_REAP_AFTER_S of further trustworthy cycles,
    # and any cycle that finds the CT again clears it back to NULL.
```

**`[451]`** `backend/proxploy/models/__init__.py:344` &middot; **51w → 47w** (8% cut) &middot; _external-quirk_  
Keeps the PVE linked-clone rule and the NULL meaning; drops the doc check reference.

<details><summary>before</summary>

```
# A PVE TEMPLATE, per /cluster/resources' own flag. PVE allows a linked
# clone only from one of these, and without knowing, the UI offered Linked
# on every guest and PVE refused every time (doc 12 check 18). NULL means
# not polled since this column existed and is treated as "not a template".
```

</details>

**after**

```
    # A PVE TEMPLATE, per /cluster/resources' own flag. PVE allows a linked
    # clone only from one of these, and without knowing, the UI offered Linked
    # on every guest and PVE refused every time. NULL means not polled since
    # this column existed and is treated as "not a template".
```

**`[452]`** `backend/proxploy/models/__init__.py:351` &middot; **67w → 58w** (13% cut) &middot; _external-quirk_  
Keeps why the raw ostype is stored and what NULL means; trims the read-once justification.

<details><summary>before</summary>

```
# PVE's RAW ostype off the guest config ("l26", "win11", "w2k19",
# "other"), never a collapsed "linux"/"windows": the client maps it for
# display and the specific value is not recoverable once discarded. Read
# once per VM by pollers._refresh_os_type and then left alone, since an
# ostype is set at creation and does not drift the way an address does.
# NULL means not read yet, or a config read PVE refused.
```

</details>

**after**

```
    # PVE's RAW ostype off the guest config ("l26", "win11", "w2k19",
    # "other"), never a collapsed "linux"/"windows": the client maps it for
    # display and the specific value is not recoverable once discarded. Read
    # once per VM by pollers._refresh_os_type, since an ostype is set at
    # creation and does not drift. NULL means not read yet, or a config read
    # PVE refused.
```

**`[453]`** `backend/proxploy/models/__init__.py:359` &middot; **91w → 57w** (37% cut) &middot; _data-integrity_  
Keeps the used-versus-allocated meaning and the migration that changed it; cuts the retelling of the broken VMs page.

<details><summary>before</summary>

```
# USED and ALLOCATED, in that order, and read the pair carefully: until
# migration a1f4d80c3e69 this table had `mem_bytes` and `disk_bytes` and
# both held the ALLOCATION (PVE's maxmem/maxdisk), while the identically
# named columns on App held USAGE. Two guest types disagreeing about what
# one name means is how the VMs page ended up able to draw a CPU meter and
# nothing else: there was no usage on the row to draw. The names now mean
# what they mean on App, everywhere, and the allocation moved to the
# explicit `*_total_bytes` columns beside them.
```

</details>

**after**

```
    # USED and ALLOCATED, in that order, and read the pair carefully: until
    # migration a1f4d80c3e69 this table had `mem_bytes` and `disk_bytes` and
    # both held the ALLOCATION (PVE's maxmem/maxdisk), while the identically
    # named columns on App held USAGE. The names now mean what they mean on
    # App, everywhere, and the allocation moved to the explicit
    # `*_total_bytes` columns beside them.
```

**`[454]`** `backend/proxploy/models/__init__.py:376` &middot; **62w → 26w** (58% cut) &middot; _redundant_  
Restates App's net comment; keeps the shared-writer constraint and points at the original.

<details><summary>before</summary>

```
# Exactly App's column names, because pollers._update_net_rates writes
# these by attribute and is shared between the two. Same meaning too:
# netin/netout are counters since the guest booted, the *_bps pair is the
# rate derived from two readings, and net_sampled_at is when the previous
# reading was taken (the gap between cycles is not poll_interval_s, since
# the poll loop backs off on a failing host).
```

</details>

**after**

```
    # Exactly App's column names, because pollers._update_net_rates writes
    # these by attribute and is shared between the two, and the same meaning
    # too: see the note on App.net_in_cached.
```

**`[455]`** `backend/proxploy/models/__init__.py:388` &middot; **148w → 108w** (27% cut) &middot; _implementation-diary_  
Keeps the three-state table, which is the column's contract; drops what it replaced.

<details><summary>before</summary>

```
# Whether this VM's QEMU guest agent is installed and answering, which is
# the same probe disk_bytes above comes from (see
# ProxmoxClient.agent_fsinfo). THREE-valued, and the three have to stay
# apart because the distinction is the entire value of the column:
#   True  the agent answered.
#   False Proxmox says this guest has no working agent. That is a real
#         finding an operator can act on, and it is the reason disk_bytes
#         is NULL for this VM: install the agent and both fill in.
#   NULL  nobody knows. Never probed, or stopped (a guest that is not
#         running cannot answer, and recording "not installed" for it
#         would be a claim we did not make), or the host was unreachable.
# Replaced the old `synced_at`, which recorded when the poller last stamped
# the row and which nothing computed with: it told an operator the poller
# was running, which the rest of the page already showed.
```

</details>

**after**

```
    # Whether this VM's QEMU guest agent is installed and answering, the same
    # probe disk_bytes above comes from (see ProxmoxClient.agent_fsinfo).
    # THREE-valued, and the three have to stay apart because the distinction is
    # the entire value of the column:
    #   True  the agent answered.
    #   False Proxmox says this guest has no working agent. A real finding an
    #         operator can act on, and the reason disk_bytes is NULL for this
    #         VM: install the agent and both fill in.
    #   NULL  nobody knows. Never probed, or stopped (a guest that is not
    #         running cannot answer, and recording "not installed" for it would
    #         be a claim we did not make), or the host was unreachable.
```

**`[456]`** `backend/proxploy/models/__init__.py:422` &middot; **58w → 58w** (0% cut) &middot; _data-integrity_  
Keeps the never-use-`total` rule and None-is-not-0; trims the pointer prose.

<details><summary>before</summary>

```
# Terminal install events (success + failed + aborted) from upstream's
# telemetry service, NEVER their `total` field, which counts intermediate
# progress pings: services/catalog_telemetry.py documents why at length.
# None means we have never had a number for this slug, which is different
# from 0 and must stay different: telemetry is opt-in upstream, so absence
# is silence, not evidence that nobody runs it.
```

</details>

**after**

```
    # Terminal install events (success + failed + aborted) from upstream's
    # telemetry service, NEVER their `total` field, which counts intermediate
    # progress pings (services/catalog_telemetry.py documents why at length).
    # None means we have never had a number for this slug, which is different
    # from 0 and must stay different: telemetry is opt-in upstream, so absence
    # is silence, not evidence that nobody runs it.
```

**`[457]`** `backend/proxploy/models/__init__.py:433` &middot; **126w → 88w** (30% cut) &middot; _data-integrity_  
Keeps the timestamp distinctions and the alembic index-name constraint; tightens both.

<details><summary>before</summary>

```
# Upstream's own dates for the SCRIPT, distinct from every other timestamp
# here: `synced_at` is when we last discovered the row, `updated_at` is
# when this DB row changed, `upstream_updated_at` is when the PocketBase
# RECORD was last edited (a description fix bumps it), and these two are
# when the script itself was first published and last changed. They are
# real columns rather than reads out of raw["metadata"] because the Store
# SORTS on them, and an ORDER BY over json_extract is neither indexable
# nor cheap over 585 rows.
# `index=True` matches the indexes migration a4d70e9c31b8 already created
# (`ix_catalog_entries_script_created` / `_updated`, which is the name
# SQLAlchemy derives here). They were in the database but not declared here,
# so `alembic check` proposed dropping two indexes the Store's "newest" and
# "updated" sorts depend on.
```

</details>

**after**

```
    # Upstream's own dates for the SCRIPT: first published, last changed.
    # Distinct from `synced_at` (when we last discovered the row), `updated_at`
    # (when this DB row changed) and `upstream_updated_at` (when the PocketBase
    # RECORD was last edited, which a description fix bumps). Real columns
    # rather than reads out of raw["metadata"] because the Store SORTS on them,
    # and an ORDER BY over json_extract is neither indexable nor cheap.
    # `index=True` matches the indexes migration a4d70e9c31b8 already created
    # (`ix_catalog_entries_script_created` / `_updated`), so `alembic check`
    # stops proposing to drop two indexes the Store's sorts depend on.
```

**`[458]`** `backend/proxploy/models/__init__.py:448` &middot; **63w → 62w** (2% cut) &middot; _data-integrity_  
Keeps the tri-state rule and why a negative chip would be a false claim; trims the row count.

<details><summary>before</summary>

```
# The tags community-scripts shows on a card. All FOUR are tri-state and
# the third state is load bearing: NULL means WE DO NOT KNOW, never "no".
# The 9 `unlisted` rows have no upstream record at all, so rendering them
# as "not ARM" or "not updateable" would be a claim nothing supports; the
# UI must show no chip there rather than a negative one.
```

</details>

**after**

```
    # The tags community-scripts shows on a card. All FOUR are tri-state and
    # the third state is load bearing: NULL means WE DO NOT KNOW, never "no".
    # An `unlisted` row has no upstream record at all, so rendering it as "not
    # ARM" or "not updateable" would be a claim nothing supports; the UI must
    # show no chip there rather than a negative one.
```

**`[459]`** `backend/proxploy/models/__init__.py:457` &middot; **101w → 92w** (9% cut) &middot; _security_  
Keeps the bare-filename containment rule and the cache-source invalidation rule; trims the intro.

<details><summary>before</summary>

```
# Local icon mirror (services/catalog_icons.py), so the Store renders its
# icons with no network at all. `icon_url` keeps upstream's URL, which is
# what the sync writes and what the API falls back to; these four record
# the cached copy beside it.
#
# `icon_cache_path` is a BARE FILENAME relative to data_dir/icons, never a
# path: it is built from our own slug plus an extension allowlist, and
# api/catalog.py re-checks containment before opening it.
# `icon_cache_source` is the upstream URL the cached bytes came FROM, and
# it is what makes a logo change detectable: when it stops matching
# `icon_url`, the file is refetched rather than served forever.
```

</details>

**after**

```
    # Local icon mirror (services/catalog_icons.py), so the Store renders its
    # icons with no network at all. `icon_url` keeps upstream's URL, which is
    # what the sync writes and what the API falls back to.
    #
    # `icon_cache_path` is a BARE FILENAME relative to data_dir/icons, never a
    # path: it is built from our own slug plus an extension allowlist, and
    # api/catalog.py re-checks containment before opening it.
    # `icon_cache_source` is the upstream URL the cached bytes came FROM, which
    # is what makes a logo change detectable: when it stops matching
    # `icon_url`, the file is refetched rather than served forever.
```

**`[460]`** `backend/proxploy/models/__init__.py:472` &middot; **50w → 49w** (2% cut) &middot; _data-integrity_  
Keeps why both the flag and the list are stored; trims the closing clause.

<details><summary>before</summary>

```
# The evidence behind has_arm, e.g. ["amd64", "arm64"]. Kept alongside the
# boolean rather than instead of it: the flag is what a chip renders, the
# list is what an "arm64 only" answer needs, and deriving one from the
# other at read time would put upstream's architecture vocabulary into our
# query layer.
```

</details>

**after**

```
    # The evidence behind has_arm, e.g. ["amd64", "arm64"]. Kept alongside the
    # boolean rather than instead of it: the flag is what a chip renders, the
    # list is what an "arm64 only" answer needs, and deriving one from the
    # other at read time would put upstream's vocabulary into our query layer.
```

**`[461]`** `backend/proxploy/models/__init__.py:480` &middot; **52w → 51w** (2% cut) &middot; _data-integrity_  
Keeps the tri-state meaning and the 2-call discovery ceiling; drops the plan reference.

<details><summary>before</summary>

```
# Tri-state on purpose (catalog expansion, see services/catalog.py header
# note): None means "discovered but not yet classified", the state every
# ct/ row starts in after a refresh. Discovery is 2 GitHub API calls flat
# and never fetches a script pair; classification happens lazily, on
# card-open or install-attempt, or via the low-priority backlog job.
```

</details>

**after**

```
    # Tri-state on purpose (see the services/catalog.py header note): None
    # means "discovered but not yet classified", the state every ct/ row starts
    # in after a refresh. Discovery is 2 GitHub API calls flat and never
    # fetches a script pair; classification happens lazily, on card-open or
    # install-attempt, or via the low-priority backlog job.
```

**`[462]`** `backend/proxploy/models/__init__.py:492` &middot; **134w → 99w** (26% cut) &middot; _measurement-dump_  
Keeps the source values, the name-match suffix and the both-null-is-normal rule; drops the example and the row count.

<details><summary>before</summary>

```
# Provenance for the presentation-only fields (name, description,
# category, icon_url, website, docs_url) that
# services/catalog_metadata.py syncs from upstream. "pocketbase" for the
# live source, "archive" for the frozen cold-start fallback, and either
# with a "-name-match" suffix when the row was joined by normalized NAME
# rather than by slug (resolve_name_matches: upstream's catalog slug
# sometimes differs from its own script filename, e.g. ct/apache-airflow.sh
# against the record slugged `airflow`). The suffix exists so a heuristic
# join is visible on the row itself, not only in a log line.
#
# Both timestamps null is a NORMAL state, not an error: it means no
# upstream record matched this slug, which is true for 37 of our ct/ rows
# (mostly alpine-* variants plus mysql). Such a row keeps its
# discovery-derived name and its catalog_categories.py heuristic category
# and simply renders without a description or icon.
```

</details>

**after**

```
    # Provenance for the presentation-only fields (name, description, category,
    # icon_url, website, docs_url) that services/catalog_metadata.py syncs from
    # upstream. "pocketbase" for the live source, "archive" for the frozen
    # cold-start fallback, either with a "-name-match" suffix when the row was
    # joined by normalized NAME rather than by slug (resolve_name_matches).
    # The suffix exists so a heuristic join is visible on the row itself, not
    # only in a log line.
    #
    # Both timestamps null is a NORMAL state, not an error: no upstream record
    # matched this slug. Such a row keeps its discovery-derived name and its
    # catalog_categories.py heuristic category and renders without a
    # description or icon.
```

**`[463]`** `backend/proxploy/models/__init__.py:512` &middot; **283w → 206w** (27% cut) &middot; _implementation-diary_  
Keeps the five state definitions, which are the column's contract; cuts the netvisor retelling and the dropped-`deprecated`-column history.

<details><summary>before</summary>

```
# How upstream's catalog answers for this slug, resolved by the metadata
# sync (services/catalog_metadata.py::resolve_upstream_state). Our
# discovery makes one row per ct/*.sh file; upstream's PocketBase is the
# catalog of what they consider an APP, and the two disagree in ways the
# Store has to render differently:
#
#   "listed"   matched a live upstream record. The normal case.
#   "delisted" upstream still HAS the record but flagged is_deleted, so it
#              keeps a real name/description/logo and stays installable;
#              the Store badges it as retired rather than hiding it.
#   "unlisted" no upstream record at all and not a variant: the script is
#              still in the repo but upstream dropped the app. Also badged.
#   "variant"  an alpine-<parent> row whose parent exists upstream and
#              which has no upstream record of its own, i.e. upstream
#              models it as an install METHOD of the parent app rather
#              than its own app. Kept in the catalog and installable, but
#              hidden from the Store grid so Syncthing is one card, not
#              two, one of them blank.
#   "superseded" a rename leftover: unmatched upstream, not installable,
#              and sharing a name with a row that IS listed. Upstream
#              renamed netvisor to scanopy and left ct/netvisor.sh in the
#              repo with no install script and an APP= line reading
#              "Scanopy", so the grid showed two "Scanopy" cards, one
#              working and one blank. Also hidden from the grid.
#
# NULL means never synced. A `deprecated` boolean used to sit beside
# this column, dead since the first migration and never written; it was
# dropped (c9a35b71e0d4) rather than overloaded, because a boolean
# cannot carry five states and "deprecated" asserts a judgement
# upstream has not made.
# Visibility only: nothing here ever implies a type or an installability
# decision, both of which belong to discovery and the classifier.
```

</details>

**after**

```
    # How upstream's catalog answers for this slug, resolved by the metadata
    # sync (services/catalog_metadata.py::resolve_upstream_state). Discovery
    # makes one row per ct/*.sh file; upstream's PocketBase is the catalog of
    # what THEY consider an app, and the two disagree in ways the Store has to
    # render differently:
    #
    #   "listed"     matched a live upstream record. The normal case.
    #   "delisted"   the record is there but flagged is_deleted, so it keeps a
    #                real name, description and logo and stays installable;
    #                the Store badges it as retired rather than hiding it.
    #   "unlisted"   no upstream record at all and not a variant: the script is
    #                still in the repo but upstream dropped the app. Also
    #                badged.
    #   "variant"    an alpine-<parent> row whose parent exists upstream and
    #                which has no record of its own, i.e. upstream models it as
    #                an install METHOD of the parent app. Kept in the catalog
    #                and installable, but hidden from the Store grid so
    #                Syncthing is one card, not two with one of them blank.
    #   "superseded" a rename leftover: unmatched upstream, not installable,
    #                and sharing a name with a row that IS listed. Also hidden
    #                from the grid.
    #
    # NULL means never synced. Visibility only: nothing here ever implies a
    # type or an installability decision, both of which belong to discovery and
    # the classifier.
```

**`[464]`** `backend/proxploy/models/__init__.py:556` &middot; **79w → 74w** (6% cut) &middot; _data-integrity_  
Keeps why the name is captured at write time and what NULL renders as; tightens it.

<details><summary>before</summary>

```
# The name of the thing this job is about, read when the job is created.
# Stored rather than looked up at render time because the destructive jobs
# are exactly the ones whose row is gone by the time anyone reads the
# history: "vm 3" a month after the delete names nothing anybody remembers.
# NULL on jobs created before this column existed, and on targets that have
# no name a person would recognise; both render the old "vm 3" way.
```

</details>

**after**

```
    # The name of the thing this job is about, read when the job is created.
    # Stored rather than looked up at render time because the destructive jobs
    # are exactly the ones whose row is gone by the time anyone reads the
    # history: "vm 3" a month after the delete names nothing anybody remembers.
    # NULL on older jobs and on targets with no name a person would recognise;
    # both render the old "vm 3" way.
```

**`[465]`** `backend/proxploy/models/__init__.py:604` &middot; **86w → 79w** (8% cut) &middot; _external-quirk_  
Keeps the single-source-of-truth rule and the verified scheme quirks; drops the doc reference and the tooling one-liner.

<details><summary>before</summary>

```
# Display label from the Apprise URL scheme (doc 04 `notification_channels.kind`,
# unencrypted). This is the single source of truth for `kind`'s allowlist:
# `notifier.kind_for()` imports this dict rather than defining its own copy, and
# migration 0002 imports `ALLOWED_NOTIFICATION_KINDS` to build the DB-level
# CHECK constraint: one Python constant, never two literals that can drift.
# Tokens verified at v1.12.0 via `apprise.plugins.N_MGR.schemas()` / each
# plugin's `service_name`: not guessed. `http`/`https` are not real Apprise
# schemes (its generic-webhook plugins are the json/form/xml entries below);
# MS Teams' current scheme is `workflow(s)` (Power Automate), not `msteams`.
```

</details>

**after**

```
# Display label from the Apprise URL scheme. The single source of truth for
# `kind`'s allowlist: `notifier.kind_for()` imports this dict rather than
# defining its own copy, and migration 0002 imports
# `ALLOWED_NOTIFICATION_KINDS` to build the DB-level CHECK constraint, so one
# Python constant can never become two literals that drift. Tokens verified at
# apprise v1.12.0, not guessed: `http`/`https` are not real Apprise schemes
# (its generic-webhook plugins are the json/form/xml entries below), and MS
# Teams' current scheme is `workflow(s)` (Power Automate), not `msteams`.
```

**`[466]`** `backend/proxploy/models/__init__.py:663` &middot; **59w → 50w** (15% cut) &middot; _security_  
Keeps the no-new-exposure reasoning and what NULL means; trims the wording.

<details><summary>before</summary>

```
# The individual values the guided picker collected, as encrypted JSON, so
# an edit can prefill instead of demanding the whole lot again to correct
# one mistyped password. No new exposure: url_enc already carries every one
# of these under the same key. NULL for a channel added by pasting a URL,
# and for any row written before this column existed.
```

</details>

**after**

```
    # The individual values the guided picker collected, as encrypted JSON, so
    # an edit can prefill instead of demanding the whole lot again to correct
    # one mistyped password. No new exposure: url_enc already carries every one
    # of these under the same key. NULL for a channel added by pasting a URL.
```

**`[467]`** `backend/proxploy/models/__init__.py:751` &middot; **75w → 62w** (17% cut) &middot; _implementation-diary_  
Keeps why the type is recorded rather than looked up; trims the retelling of the sweep bug.

<details><summary>before</summary>

```
# The datastore's PVE type ("pbs", "nfs", "dir", ...) as it was when this
# archive was last synced. Recorded rather than looked up because the
# lookup used to be poller.snapshots, which is empty between boot and the
# first poll: api/backups.py::_refuse_on_pbs then offered a full read-back
# of an archive PBS already verifies, and the sweep did the same to every
# PBS archive on the host. sync_host_backups is handed the type by PVE
# anyway, so it writes it down.
```

</details>

**after**

```
    # The datastore's PVE type ("pbs", "nfs", "dir", ...) as it was when this
    # archive was last synced. Recorded rather than looked up, because the
    # lookup used to be poller.snapshots, which is empty between boot and the
    # first poll: api/backups.py::_refuse_on_pbs then offered a full read-back
    # of an archive PBS already verifies. sync_host_backups is handed the type
    # by PVE anyway, so it writes it down.
```

**`[468]`** `backend/proxploy/models/__init__.py:759` &middot; **83w → 76w** (8% cut) &middot; _data-integrity_  
Keeps why node is part of the unique key and why verify and restore need it; trims the wording.

<details><summary>before</summary>

```
# Which node of the host's cluster this archive is ON, which is not always
# the node Proxploy is enrolled at. A shared datastore (PBS, NFS, CephFS)
# answers identically from every node and records the enrolled one; a
# node-LOCAL dump dir holds different files per node under the SAME volid,
# so the node is what tells those apart and is part of the key below.
# It is also the node verify and restore have to run on: reading pve2's
# archive on pve1 finds nothing.
```

</details>

**after**

```
    # Which node of the host's cluster this archive is ON, which is not always
    # the node Proxploy is enrolled at. A shared datastore (PBS, NFS, CephFS)
    # answers identically from every node and records the enrolled one; a
    # node-LOCAL dump dir holds different files per node under the SAME volid,
    # so the node is what tells those apart and is part of the key below. It is
    # also the node verify and restore have to run on.
```

**`[469]`** `backend/proxploy/models/__init__.py:867` &middot; **159w → 142w** (11% cut) &middot; _narration_  
Keeps the watermark invariant and the bounded-list rule; trims the surrounding prose.

<details><summary>before</summary>

```
One row per user: the bell tray's server-side memory of what has
    already been cleared, so a clear survives a reload, a reboot, and a
    login from a different browser or machine (a per-user fact, not a
    per-browser one).

    `cleared_through_job_id` is a watermark, not a growing list: "clear all"
    records the highest job id that existed at the moment of the clear, and
    every job at or below it counts as dismissed from then on, however many
    thousands of jobs that eventually covers. Job ids are a strictly
    increasing sequence (autoincrement primary key on `jobs`), so a job
    created AFTER a clear always has an id above the watermark and is never
    swallowed by it.

    `dismissed_job_ids` covers what the watermark cannot: a single item
    dismissed by its own card, whose job id is above the watermark. It stays
    bounded because the next "clear all" moves the watermark up past it and
    the id gets pruned back out (see services/notification_dismissals.py).
    
```

</details>

**after**

```
    """One row per user: the bell tray's server-side memory of what has been
    cleared, so a clear survives a reload, a reboot, and a login from another
    browser or machine (a per-user fact, not a per-browser one).

    `cleared_through_job_id` is a watermark, not a growing list: "clear all"
    records the highest job id that existed at that moment, and every job at or
    below it counts as dismissed from then on. Job ids strictly increase
    (autoincrement primary key on `jobs`), so a job created AFTER a clear
    always has an id above the watermark and is never swallowed by it.

    `dismissed_job_ids` covers what the watermark cannot: a single item
    dismissed by its own card, whose job id is above the watermark. It stays
    bounded because the next "clear all" moves the watermark past it and the id
    gets pruned back out (see services/notification_dismissals.py).
    """
```

**`[470]`** `backend/proxploy/models/__init__.py:887` &middot; **61w → 48w** (21% cut) &middot; _data-integrity_  
Keeps the index-name constraint that keeps `alembic check` quiet; trims the wording.

<details><summary>before</summary>

```
# Declared in __table_args__ below rather than as `unique=True, index=True`
# here: that spelling makes SQLAlchemy derive the name
# `ix_notification_dismissals_user_id`, while migration d8a1c9f4b2e6 created
# it as `ux_notification_dismissals_user_id`, which is this schema's
# convention for a unique index (`ux_users_oidc`, `ux_team_members`). Same
# column and same uniqueness either way; naming it here is what stops
# `alembic check` proposing a drop-and-recreate of an index that is already
# correct.
```

</details>

**after**

```
    # Declared here rather than as `unique=True, index=True` on the column:
    # that spelling makes SQLAlchemy derive
    # `ix_notification_dismissals_user_id`, while migration d8a1c9f4b2e6 created
    # it as `ux_notification_dismissals_user_id`, this schema's convention for a
    # unique index. Same column and same uniqueness either way; naming it here
    # is what stops `alembic check` proposing a drop-and-recreate.
```


### 🟢 KEEP (30), unchanged

- **`[471]`** `1` &middot; _contract_ &middot; `All Proxploy entities, portable SQLite/Postgres subset.`
- **`[472]`** `59` &middot; _security_ &middot; `# Time step of the last code accepted for this user, so the same code`
- **`[473]`** `152` &middot; _data-integrity_ &middot; `# owner|admin|operator|viewer`
- **`[474]`** `181` &middot; _surprising_ &middot; `# Why the last poll cycle was not clean, in one sentence, or NULL when it`
- **`[475]`** `235` &middot; _data-integrity_ &middot; `# api_token | ssh_key`
- **`[476]`** `240` &middot; _contract_ &middot; `# Set by POST /hosts/{id}/ssh/verify. NULL means "never confirmed working"`
- **`[477]`** `253` &middot; _external-quirk_ &middot; `# Physical column is `ct_id`: `ctid` is a PostgreSQL system column present`
- **`[478]`** `272` &middot; _data-integrity_ &middot; `# NULL means nobody has told Proxploy, so the app itself is asked at open`
- **`[479]`** `291` &middot; _contract_ &middot; `# Storage and network for the card, the table and the icon grid. All from`
- **`[480]`** `317` &middot; _data-integrity_ &middot; `# Table-level constraints name the *physical* column, hence "ct_id".`
- **`[481]`** `328` &middot; _data-integrity_ &middot; `# upstream | edited`
- **`[482]`** `339` &middot; _external-quirk_ &middot; `# The node the guest actually RUNS on, which is not the polling host's node`
- **`[483]`** `369` &middot; _external-quirk_ &middot; `# disk_bytes comes from the QEMU guest agent, not from /cluster/resources:`
- **`[484]`** `429` &middot; _external-quirk_ &middot; `# When WE last read that number. Its own column because upstream caches`
- **`[485]`** `488` &middot; _contract_ &middot; `# Which upstream directory this came from: ct/vm/tools-pve/tools-addon/`
- **`[486]`** `509` &middot; _data-integrity_ &middot; `# Upstream's own last-modified stamp for the matched record, naive UTC.`
- **`[487]`** `638` &middot; _data-integrity_ &middot; `# "webhook" is also `kind_for`'s fallback for an unrecognised-but-legitimate`
- **`[488]`** `645` &middot; _data-integrity_ &middot; `CHECK-constraint condition text for `column`, closed over`
- **`[489]`** `682` &middot; _data-integrity_ &middot; `# gt | lt`
- **`[490]`** `725` &middot; _data-integrity_ &middot; `# 5m | 1h`
- **`[491]`** `767` &middot; _contract_ &middot; `# When Proxploy last checked this archive itself (services/backupjobs.py's`
- **`[492]`** `775` &middot; _data-integrity_ &middot; `# (host, node, volid), not (host, volid): `local:backup/vzdump-lxc-110`
- **`[493]`** `781` &middot; _contract_ &middot; `# api/backups.py reads the newest rows with ORDER BY taken_at DESC`
- **`[494]`** `791` &middot; _security_ &middot; `Append-only, with one deliberate exception. No ORM update path exists`
- **`[495]`** `798` &middot; _data-integrity_ &middot; `# user|api_key|system`
- **`[496]`** `803` &middot; _data-integrity_ &middot; `# Same capture-at-write-time rule as Job.target_name, and it matters more`
- **`[497]`** `820` &middot; _security_ &middot; `Single-use, short-TTL. Only `token_hash` is stored, never the raw,`
- **`[498]`** `844` &middot; _data-integrity_ &middot; `# always 1`
- **`[499]`** `845` &middot; _security_ &middot; `# Fernet ciphertext, base64 str`
- **`[500]`** `846` &middot; _security_ &middot; `# NOT encrypted, unlike token: a cert is a signed public key, public by`

---

## `backend/proxploy/api/apps.py`

3,240 → 2,334 words, 28% cut. 4 delete, 36 shorten, 15 keep.


### 🔴 DELETE (4)

**`[501]`** `backend/proxploy/api/apps.py:226` &middot; 12w &middot; _redundant_  
Repeats the batching note already made in list_apps a few lines up.

```
# One query for the batch rather than one per item, matching list_apps.
```

**`[502]`** `backend/proxploy/api/apps.py:411` &middot; 34w &middot; _redundant_  
The docstring above already states that `accurate: false` exists so a client cannot oversell the guess.

```
# Stated in the payload, not left to the UI to remember: this is a
# snapshot of what was listening a moment ago, ranked by a
# heuristic, and it can be wrong in both directions.
```

**`[503]`** `backend/proxploy/api/apps.py:872` &middot; 9w &middot; _redundant_  
Third copy of the same 'above the lifecycle wildcard' note.

```
# Above the lifecycle wildcard, same as /network directly above.
```

**`[504]`** `backend/proxploy/api/apps.py:991` &middot; 30w &middot; _redundant_  
Repeats the note 40 lines above it verbatim in substance.

```
# Above the lifecycle wildcard, same reasoning as /migrate/preflight above; 
# three literal segments so it cannot structurally collide with
# /{app_id}/{action}, but registered here for the same "one place operators
# look" reason.
```


### 🟡 SHORTEN (36)

**`[505]`** `backend/proxploy/api/apps.py:1` &middot; **15w → 11w** (27% cut) &middot; _ticket-history_  
Doc and phase references are dead history; the identity/cache line is the real statement.

<details><summary>before</summary>

```
Apps read + lifecycle endpoints (doc 05, Phase 2/3 rows). Identity is ours;
state is cache.
```

</details>

**after**

```
"""Apps read and lifecycle endpoints. Identity is ours; state is cache."""
```

**`[506]`** `backend/proxploy/api/apps.py:35` &middot; **60w → 49w** (18% cut) &middot; _security_  
The 401-before-403 ordering rule binds; the test filename and the restated cache mechanics do not.

<details><summary>before</summary>

```
# Reused as BOTH the route-level dependency and the parameter-level one below
# so FastAPI's dependency cache (keyed on the callable) collapses repeated
# uses into one call per request, and so authorize() runs before
# require_entitlement: an anonymous caller must get 401, never a leaky 403
# (test_route_auth_invariant.py). No-id routes (list/discovered/adopt/
# update-all) use the global (no scope_of) singleton; id-carrying routes use
# the scope_app()-scoped one.
```

</details>

**after**

```
# Reused as BOTH the route-level and the parameter-level dependency so
# FastAPI's dependency cache collapses repeated uses into one call per
# request, and so authorize() runs before require_entitlement: an anonymous
# caller must get 401, never a leaky 403. No-id routes use the unscoped
# singleton; id-carrying routes use the scope_app()-scoped one.
```

**`[507]`** `backend/proxploy/api/apps.py:59` &middot; **73w → 68w** (7% cut) &middot; _contract_  
Keep what a caller must pass and why there is no default; drop the pointer to where busy comes from.

<details><summary>before</summary>

```
`entry` is the catalog row this app was installed from, or None when it
    has no catalog slug or that slug no longer resolves. Deliberately a
    required argument with no default: it is only ever used for the icon, and a
    default of None would let a future caller silently serve every app without
    one.

    `busy` maps a guest to what it should READ as while a job acts on it, from
    services/lifecycle.py::busy_guests.
```

</details>

**after**

```
    """`entry` is the catalog row this app was installed from, or None when it
    has no catalog slug or that slug no longer resolves. Deliberately required
    with no default: it is only used for the icon, and a default of None would
    let a future caller silently serve every app without one.

    `busy` maps a guest to what it should READ as while a job acts on it."""
```

**`[508]`** `backend/proxploy/api/apps.py:75` &middot; **107w → 62w** (42% cut) &middot; _surprising_  
Keep the staleness reason and the null-is-normal rule; the rest is argument.

<details><summary>before</summary>

```
# The icon of the Store entry this app was installed from, resolved
# through the Store's own pipeline rather than copied onto the app row.
# A column here would be a second copy of a logo that changes whenever
# upstream rebrands, and it would go stale the moment a catalog refresh
# moved on without it; resolving it per request costs one lookup and
# cannot disagree with the card the operator installed from.
#
# Null is normal and is NOT an error: no catalog slug, a slug upstream
# has dropped, or an entry with no logo all land here, and all three
# are the icon_initials/icon_colors tile the card already draws.
```

</details>

**after**

```
        # The Store entry's icon, resolved through the Store's own pipeline
        # rather than copied onto the app row, where it would go stale the next
        # time upstream rebrands or the catalog refreshes. Null is normal and
        # is NOT an error: no catalog slug, a dropped slug, or an entry with no
        # logo all land here and all fall back to the icon_initials tile.
```

**`[509]`** `backend/proxploy/api/apps.py:91` &middot; **50w → 38w** (24% cut) &middot; _contract_  
The ticket id adds nothing; the None-hides-the-button rule is the payload contract.

<details><summary>before</summary>

```
# "Open web UI" target port (PXP-85): the catalog's own port, resolved
# through `entry` the same way the icon above is, never stored on the
# app row. No catalog entry / no port on it means no button, not a
# prompt for one, so None here is what hides the action client-side.
```

</details>

**after**

```
        # "Open web UI" target port: the catalog's own port, resolved through
        # `entry` like the icon above, never stored on the app row. No entry or
        # no port on it means no button, so None here hides the action.
```

**`[510]`** `backend/proxploy/api/apps.py:96` &middot; **69w → 57w** (17% cut) &middot; _external-quirk_  
Proxmox reporting the OLD status mid-action must stay; the retelling of the optimistic patch shortens.

<details><summary>before</summary>

```
# "pending" while an action is in flight, whatever the cached column
# says. Proxmox reports the OLD status for as long as a stop or a
# removal is actually running, so answering with it put the pill back
# to Running mid-action on every refetch. The browser's optimistic
# patch cannot cover this on its own: it only exists in the tab that
# clicked, and any refetch there overwrote it from here.
```

</details>

**after**

```
        # "pending" while an action is in flight, whatever the cached column
        # says. Proxmox reports the OLD status for as long as a stop or removal
        # is actually running, so answering with it put the pill back to
        # Running mid-action on every refetch. The browser's optimistic patch
        # cannot cover this: it only exists in the tab that clicked.
```

**`[511]`** `backend/proxploy/api/apps.py:106` &middot; **52w → 32w** (38% cut) &middot; _redundant_  
The storage half restates the field names; only the missing-denominator reason is content.

<details><summary>before</summary>

```
# Storage is a pair so the card can draw a bar; network is two rates
# with no denominator, because there is no link speed to divide by.
# The raw netin/netout counters stay on the row: they only mean
# something next to the previous reading, which is the poller's
# business, not a client's.
```

</details>

**after**

```
        # Network is two rates with no denominator: there is no link speed to
        # divide by. The raw netin/netout counters stay on the row, they only
        # mean something next to the previous reading.
```

**`[512]`** `backend/proxploy/api/apps.py:136` &middot; **38w → 22w** (42% cut) &middot; _narration_  
One line carries the batching reason; the 40-app arithmetic does not.

<details><summary>before</summary>

```
# One query for the whole page rather than one per card. A grid of 40 apps
# is 40 rows out of the same small table, and the icon is the only thing
# any of them wants from it.
```

</details>

**after**

```
    # One query for the whole page rather than one per card; the icon is all
    # any of them wants from that table.
```

**`[513]`** `backend/proxploy/api/apps.py:151` &middot; **158w → 118w** (25% cut) &middot; _data-integrity_  
The (cluster, ctid) dedup invariant stays; the phase marker and file pointers go.

<details><summary>before</summary>

```
Pre-existing CTs not yet adopted (doc 05). Read-only until Phase 4.

    Two Hosts can be two nodes of the SAME cluster; cluster_resources()
    returns the whole cluster from either one, so every host's snapshot
    lists the same unadopted CT, each carrying `node`, the CT's real owning
    node (already correct in the payload; see pollers/__init__.py). Deduped
    here by (cluster, ctid): a ctid is only unique WITHIN a cluster, so two
    different clusters (or two standalone hosts, see cluster_scope) can
    legitimately both have a CT 101 and both must be offered, and
    attributed to the Host actually registered at that node, not whichever
    host happened to poll it. An already-tracked App's own poll cycle only
    checks its own host_id (mapped_ctids is host-scoped), so a CT adopted on
    one host still shows up as discovered in another host's snapshot of the
    SAME cluster; checking every App row here, scoped the same way, is what
    keeps it from being offered for adoption twice.
    
```

</details>

**after**

```
    """Pre-existing CTs not yet adopted.

    Two Hosts can be two nodes of the SAME cluster, and cluster_resources()
    returns the whole cluster from either one, so every host's snapshot lists
    the same unadopted CT. Deduped by (cluster, ctid): a ctid is unique only
    WITHIN a cluster, so two clusters can legitimately both have a CT 101 and
    both must be offered, attributed to the Host registered at that CT's own
    `node` rather than whichever host polled it. An App's poll cycle only
    checks its own host_id, so a CT adopted on one host still shows as
    discovered in another host's snapshot of the same cluster; checking every
    App row here, scoped the same way, stops it being offered twice.
    """
```

**`[514]`** `backend/proxploy/api/apps.py:209` &middot; **146w → 94w** (36% cut) &middot; _data-integrity_  
The one-commit-per-batch rule binds; the count of apps that read back wrong is history.

<details><summary>before</summary>

```
Bulk-adopt pre-existing/discovered CTs as tracked apps (doc 05, Phase 4).

    One commit for the whole batch: a mid-batch ux_apps_host_ctid conflict
    rolls back everything flushed so far in this request (nothing partially
    lands), and a single audit row covers the whole batch rather than one per
    item.

    An adopted app takes its category and its web port from the catalog entry
    its slug names, the same way services/appstore.py::install copies category
    onto an app it creates. Without this every adopted app read back with no
    category at all, so the Apps grid grouped all eight of them under
    "unknown", and with no web_port, so nothing on the row knew which port its
    web UI answers on. AdoptIn carries neither field, so there is no caller
    value to overwrite here; both are copied only when the slug actually
    resolves, and an unrecognised or absent slug adopts exactly as before.
    
```

</details>

**after**

```
    """Bulk-adopt pre-existing/discovered CTs as tracked apps.

    One commit for the whole batch: a mid-batch ux_apps_host_ctid conflict
    rolls back everything flushed so far, so nothing partially lands, and one
    audit row covers the batch.

    An adopted app takes its category and web port from the catalog entry its
    slug names, like install does. Without them the grid has no group to file
    the app under and nothing knows which port its web UI answers on. AdoptIn
    carries neither field, so no caller value is overwritten, and an absent or
    unrecognised slug adopts exactly as before.
    """
```

**`[515]`** `backend/proxploy/api/apps.py:248` &middot; **79w → 53w** (33% cut) &middot; _narration_  
Keep why names are stored and why they are capped; drop the retelling.

<details><summary>before</summary>

```
# One row covers the whole batch, so there is no single target to point at
# and the row carried no name at all. The names are all right here, and a
# list of them is what makes the row answerable later without opening the
# params blob, which the audit screen never shows. Capped at five: a
# forty-name string is one table cell that pushes every other column off
# the screen, and `app_ids` in params still holds the full set.
```

</details>

**after**

```
    # One audit row covers the whole batch, so there is no single target to
    # point at. The names make the row answerable without opening the params
    # blob, which the audit screen never shows. Capped at five: a forty-name
    # string pushes every other column off the screen, and `app_ids` still
    # holds the full set.
```

**`[516]`** `backend/proxploy/api/apps.py:265` &middot; **25w → 23w** (8% cut) &middot; _test-reference_  
The registration-order constraint stays, the test name goes.

<details><summary>before</summary>

```
# Literal segment, registered ahead of `GET /{app_id}` and the lifecycle
# wildcard: `{app_id}` would otherwise try to parse "update-all" as an int
# and 422 (see test_update_all_is_not_matched_as_an_app_id).
```

</details>

**after**

```
# Literal segment, registered ahead of `GET /{app_id}` and the lifecycle
# wildcard: `{app_id}` would otherwise try to parse "update-all" as an int
# and 422.
```

**`[517]`** `backend/proxploy/api/apps.py:273` &middot; **163w → 123w** (25% cut) &middot; _contract_  
The skip-order list is a real contract with the single-app route; the doc quotes are not.

<details><summary>before</summary>

```
One `app.update` job per stale app (doc 05: "per-app results").

    No new queue machinery: JobBackend.MAX_CONCURRENT already runs four at a
    time and genuinely queues the rest, and each job carries its own status,
    transcript and result, which is what "per-app results" means.

    `skipped` is not decoration. A bare "0 jobs started" is indistinguishable
    from a broken endpoint, so every app that did not get a job says why.

    Reuses `_update_state` and mirrors POST /{app_id}/update's own skip
    order exactly, so a bulk run and a single-app run never disagree about
    why a given app didn't get a job:

    1. Edited script first: an edited row's `upstream_ref` is NULL, so
       checking "no pinned script" before "edited" would misreport an
       edited app as having no upstream at all. Enqueueing anyway would
       spray a guaranteed-`JobFailed` job (services/appstore.py::
       _resolve_update refuses to discard local edits), so this is skipped,
       not enqueued-to-fail.
    2. No catalog entry / no upstream_sha / no pinned script at all.
    3. Already on the catalog's current commit.
    
```

</details>

**after**

```
    """One `app.update` job per stale app.

    No new queue machinery: JobBackend.MAX_CONCURRENT already runs four at a
    time and queues the rest, and each job carries its own status, transcript
    and result.

    `skipped` is not decoration: a bare "0 jobs started" is indistinguishable
    from a broken endpoint, so every app that got no job says why.

    Mirrors POST /{app_id}/update's skip order exactly, so bulk and single-app
    runs never disagree about why an app was skipped:

    1. Edited script first: an edited row's `upstream_ref` is NULL, so checking
       "no pinned script" first would misreport it as having no upstream at
       all, and enqueueing anyway would spray a guaranteed-`JobFailed` job.
    2. No catalog entry / no upstream_sha / no pinned script.
    3. Already on the catalog's current commit.
    """
```

**`[518]`** `backend/proxploy/api/apps.py:343` &middot; **77w → 52w** (32% cut) &middot; _surprising_  
Keep why the 501 is deliberate; drop the doc quote and the module tour.

<details><summary>before</summary>

```
Doc 05: 'Recent CT log lines (journal tail via pct exec / console
    channel)'. No such exec/journal channel exists anywhere in this codebase
    yet; services/lifecycle.py and executor/ only ever run install/update
    scripts over SSH on the HOST, never a command inside a guest CT, and
    ProxmoxClient has no pct-exec-equivalent call. Rather than fabricate log
    lines, this is a real, deliberate 501 so the frontend can render an honest
    gap (see AppLogs) instead of silently polling a 404 forever.
```

</details>

**after**

```
    """No exec or journal channel to a guest exists in this backend: lifecycle
    and executor/ only run scripts over SSH on the HOST, and ProxmoxClient has
    no pct-exec equivalent. Rather than fabricate log lines this is a
    deliberate 501, so the frontend renders an honest gap instead of polling a
    404 forever."""
```

**`[519]`** `backend/proxploy/api/apps.py:359` &middot; **170w → 117w** (31% cut) &middot; _contract_  
Keep the GET-runs-a-command warning, the heuristic contract and the poll-budget rule; trim the setup.

<details><summary>before</summary>

```
What this container is listening on, ranked, as a GUESS.

    For an app adopted by hand: the catalog knows nothing about it, so
    `web_port` is empty, so there is no Open button and no way to get one short
    of the operator already knowing the number. Proxmox cannot answer it either
    (`pct config` describes the NIC and no API route exposes sockets), so the
    only place the answer exists is inside the container.

    A GET that runs a command, which is unusual and deliberate: it reads state
    and changes nothing, and it never writes web_port. The caller is handed
    candidates and picks one, because a container can serve two UIs and this
    ranking is a heuristic, not a fact. `accurate: false` is in the response so
    a client cannot present it as one by accident.

    User-triggered only, never the poller: this is one command per guest, which
    is exactly what the O(nodes) poll budget forbids (services/proxmox.py's
    "per-guest, user-triggered calls" note, the same rule the network
    attachment map is annotated with).
    
```

</details>

**after**

```
    """What this container is listening on, ranked, as a GUESS.

    For a hand-adopted app the catalog knows nothing, so `web_port` is empty,
    and Proxmox cannot answer either: `pct config` describes the NIC and no API
    route exposes sockets. The only place the answer exists is inside the
    container.

    A GET that runs a command, unusual and deliberate: it changes nothing and
    never writes web_port. The caller picks from the candidates, because a
    container can serve two UIs and this ranking is a heuristic, not a fact.
    `accurate: false` is in the response so a client cannot present it as one.

    User-triggered only, never the poller: one command per guest is exactly
    what the O(nodes) poll budget forbids.
    """
```

**`[520]`** `backend/proxploy/api/apps.py:418` &middot; **45w → 40w** (11% cut) &middot; _test-reference_  
The drift invariant stays; the doc numbers and test name go.

<details><summary>before</summary>

```
Doc 05/10: diff the pinned app_scripts row against the *current*
    catalog_entries.raw.install_script for this app's catalog_slug, not just
    against this app's own prior version. A catalog refresh can move upstream
    forward with the app's pinned content untouched, and that drift has to
    surface too (see test_upstream_moving_on_after_pin_also_surfaces_a_diff).
```

</details>

**after**

```
    """Diff the pinned app_scripts row against the *current*
    catalog_entries.raw.install_script for this app's slug, not just against
    the app's own prior version: a catalog refresh can move upstream forward
    with the pinned content untouched, and that drift has to surface too."""
```

**`[521]`** `backend/proxploy/api/apps.py:437` &middot; **57w → 20w** (65% cut) &middot; _redundant_  
The wildcard WARNING at the bottom already carries this; one pointer is enough.

<details><summary>before</summary>

```
# Literal two-segment/three-segment paths registered here: BEFORE the
# lifecycle wildcard further down: per that route's own WARNING: Starlette
# matches path templates in registration order, and `/{app_id}/{action}`
# would otherwise swallow these (it's POST-only though, so GET/PUT here don't
# actually collide on method; kept ahead of it anyway for the same reason
# doc 05's future /{id}/update and /{id}/migrate must be).
```

</details>

**after**

```
# Registered BEFORE the lifecycle wildcard further down: Starlette matches
# path templates in registration order, and `/{app_id}/{action}` would
# otherwise swallow these.
```

**`[522]`** `backend/proxploy/api/apps.py:463` &middot; **32w → 21w** (34% cut) &middot; _implementation-diary_  
Keep the validate-before-write rule and the FK failure it prevents; drop the bug retelling.

<details><summary>before</summary>

```
# Validate before writing, like every sibling route here: a missing
# `content` used to KeyError into a 500, and an unknown app_id used to
# 500 on the AppScript FK violation at commit time.
```

</details>

**after**

```
    # Validate before writing, like every sibling route here: an unknown
    # app_id otherwise 500s on the AppScript FK violation at commit time.
```

**`[523]`** `backend/proxploy/api/apps.py:498` &middot; **104w → 68w** (35% cut) &middot; _implementation-diary_  
The permanent-block trap and the never-mutate rule stay; the review narrative goes.

<details><summary>before</summary>

```
Task 5 review found a dead end: put_app_script above always writes
    `source="edited"`, and nothing else ever writes `source="upstream"` except
    the install/update job handlers, so once an app's script is edited,
    services/appstore.py::_resolve_update's edited-script guard blocks
    `app.update` FOREVER, even if the operator pastes the exact upstream text
    back (there was no way to re-mark a row "upstream"). This route is that
    way back: pin a NEW version to the catalog's CURRENT install_script,
    sourced "upstream", so pinned_ref reads the catalog sha again and the
    guard clears.

    Never mutates or deletes the edited row being reverted from: the version
    history is the record, same rule put_app_script already follows.
    
```

</details>

**after**

```
    """Pin a NEW version to the catalog's CURRENT install_script, sourced
    "upstream", so pinned_ref reads the catalog sha again.

    Without this an app is stuck: put_app_script always writes
    `source="edited"` and only the install/update handlers ever write
    "upstream", so once a script is edited _resolve_update's guard blocks
    `app.update` forever, even if the operator pastes the exact upstream text
    back.

    Never mutates the edited row: the version history is the record.
    """
```

**`[524]`** `backend/proxploy/api/apps.py:536` &middot; **58w → 38w** (34% cut) &middot; _data-integrity_  
Keep why update_available is cleared and why not the whole-table recompute.

<details><summary>before</summary>

```
# Pins to the catalog's CURRENT sha, so by definition there is nothing
# pending afterwards: mirrors run_update's own reset (services/appstore.py)
# rather than leaving GET /update reporting an update against a script that
# was just reverted TO that exact commit. A single-row assignment, not
# mark_updates_available(db): that recomputes the whole table and this
# route only just changed the state of one.
```

</details>

**after**

```
    # Pins to the catalog's CURRENT sha, so nothing is pending afterwards:
    # mirrors run_update's own reset rather than reporting an update against a
    # script just reverted TO that commit. A single-row assignment, not
    # mark_updates_available(db), which recomputes the whole table.
```

**`[525]`** `backend/proxploy/api/apps.py:551` &middot; **98w → 56w** (43% cut) &middot; _contract_  
Keep why the row itself is returned; drop the review-finding story.

<details><summary>before</summary>

```
Returns the app, its catalog entry (if any), and its NEWEST AppScript
    row, the single query both GET and POST /update need. Returning the row
    itself, not just `.upstream_ref`, lets both callers see `.source` too:
    `put_app_script` leaves `upstream_ref` NULL on an edited row, and that
    NULL alone is not enough to tell "edited" apart from "no script pinned at
    all" (review finding: a bare `from_ref is None` check conflated the two,
    so GET showed a stale update + a bogus diff for an edited app, and POST's
    409 blamed a missing catalog entry that was not the actual cause).
    
```

</details>

**after**

```
    """The app, its catalog entry (if any), and its NEWEST AppScript row: the
    single query both GET and POST /update need. Returning the row itself, not
    just `.upstream_ref`, lets both callers see `.source` too, because
    `put_app_script` leaves `upstream_ref` NULL on an edited row and that NULL
    alone cannot tell "edited" from "no script pinned at all".
    """
```

**`[526]`** `backend/proxploy/api/apps.py:574` &middot; **173w → 113w** (35% cut) &middot; _contract_  
Three real response rules survive; the doc-phase framing does not.

<details><summary>before</summary>

```
What an update would do: which commit to which, and the script diff.

    Doc 10 Phase 7 requires the same diff/consent surface install has, so the
    diff shown here is the SAME `_diff_vs_upstream` the Config tab renders:
    one implementation, one answer, no chance of the two disagreeing about
    what is about to run.

    Unlike the Config tab's GET /script (which always shows drift, including
    the rare case where a catalog refresh moves `raw.install_script` without
    the pinned commit changing), this route only surfaces a diff when there is
    an update TO show. A caller here is asking "what would `POST .../update`
    do", and the honest answer when the app is already on the catalog's
    commit is "nothing", not a diff sourced from unrelated content drift.

    An edited newest script (`script_source == "edited"`) is reported as no
    update available at all, never a diff: `upstream_ref` is NULL on that row,
    so POST will refuse regardless of the catalog state (see update_app), and
    showing a populated `diff_vs_upstream`/`update_available` here would
    advertise an action POST is about to reject.
    
```

</details>

**after**

```
    """What an update would do: which commit to which, and the script diff.

    The diff is the SAME `_diff_vs_upstream` the Config tab renders, so the two
    can never disagree about what is about to run.

    Unlike GET /script, which always shows drift, this surfaces a diff only
    when there is an update TO show: the honest answer to "what would POST do"
    when the app is already on the catalog's commit is "nothing", not a diff
    sourced from unrelated content drift.

    An edited newest script reports no update at all, never a diff: POST
    refuses it regardless of catalog state, so a diff here would advertise an
    action POST is about to reject.
    """
```

**`[527]`** `backend/proxploy/api/apps.py:617` &middot; **57w → 39w** (32% cut) &middot; _security_  
The consent requirement and the deliberate role split stay; the doc citations go.

<details><summary>before</summary>

```
Root-consent gated, exactly like install (api/catalog.py::install_catalog_entry):
    this re-runs a community script as root on the node, and brief §8 says the
    honest thing is to make the operator say so out loud. Unlike install
    (admin-only), doc 05 grants this to operator; a lower bar than the
    catalog table above intentionally accepts, not an oversight to fix here.
    
```

</details>

**after**

```
    """Root-consent gated, exactly like install: this re-runs a community
    script as root on the node, so the operator has to say so out loud. Unlike
    install, which is admin-only, this is granted to operator: a lower bar,
    deliberately accepted."""
```

**`[528]`** `backend/proxploy/api/apps.py:878` &middot; **205w → 167w** (19% cut) &middot; _contract_  
The cross-origin probe reason, the precedence rule and the 409 policy stay; the framing sentences go.

<details><summary>before</summary>

```
The whole URL to point a tab at, built here rather than in the browser.

    Three of the four pieces can only be answered on this side. The address is
    read live off the guest's own NIC config, because a DHCP lease or a manual
    re-IP moves it and a value cached at install would point at the old one.
    The scheme is asked of the app itself (services/webui.py), which a page
    served from Proxploy's own origin cannot do: a cross-origin probe of a
    self-signed https app fails opaquely, so the browser cannot tell "speaks
    https" from "is not there".

    Port and path follow the same precedence the scheme does (see
    services/webui.py::scheme_for): what the operator set, then what the
    install script printed about itself, then the catalog. The operator's
    value is first everywhere and is never written over, and the catalog is
    last because it is the only one of the three that describes the app in
    general rather than this container in particular.

    Every failure here is a 409 with a sentence naming what is missing, not a
    URL built out of a default. Sending someone to a page that cannot load and
    calling that success is the bug this endpoint exists to end.
    
```

</details>

**after**

```
    """The whole URL to point a tab at, built here rather than in the browser.

    The address is read live off the guest's own NIC config, because DHCP or a
    manual re-IP moves it and a value cached at install would point at the old
    one. The scheme is asked of the app itself (services/webui.py), which a
    page on Proxploy's own origin cannot do: a cross-origin probe of a
    self-signed https app fails opaquely, so the browser cannot tell "speaks
    https" from "is not there".

    Port and path follow the same precedence the scheme does: what the operator
    set, then what the install script printed, then the catalog. The operator's
    value is never written over, and the catalog is last because it describes
    the app in general rather than this container.

    Every failure is a 409 naming what is missing, never a URL built from a
    default: sending someone to a page that cannot load and calling that
    success is the bug this endpoint exists to end.
    """
```

**`[529]`** `backend/proxploy/api/apps.py:951` &middot; **60w → 40w** (33% cut) &middot; _redundant_  
Says at length that there is no real collision; the placement reason fits in four lines.

<details><summary>before</summary>

```
# Above the lifecycle wildcard (WARNING further down): this is a 3-segment
# literal path (/{app_id}/migrate/preflight) so it does not actually collide
# with the 2-segment /{app_id}/{action} template regardless of registration
# order, but it lives here anyway for the same reason /script and /network
# do: one place operators look for every non-lifecycle app route, and no
# surprises if that wildcard's shape ever widens.
```

</details>

**after**

```
# Three literal segments, so this cannot structurally collide with the
# 2-segment /{app_id}/{action} template, but it is registered above the
# lifecycle wildcard anyway: one place operators look for every non-lifecycle
# app route, and no surprises if that wildcard's shape ever widens.
```

**`[530]`** `backend/proxploy/api/apps.py:966` &middot; **36w → 32w** (11% cut) &middot; _contract_  
Keep why two failures are deliberately one status; drop the restatement.

<details><summary>before</summary>

```
# A missing target_host_id and an unreachable/disconnected one are the
# same caller-facing problem ("this is not a usable migration target"),
# so both collapse to one 409 rather than a 404/409 split the frontend
# would have to special-case.
```

</details>

**after**

```
    # A missing target_host_id and an unreachable one are the same
    # caller-facing problem ("not a usable migration target"), so both collapse
    # to one 409 rather than a 404/409 split the frontend must special-case.
```

**`[531]`** `backend/proxploy/api/apps.py:984` &middot; **42w → 35w** (17% cut) &middot; _contract_  
Keep what None means and that a bad name blocks; drop the historical aside.

<details><summary>before</summary>

```
# Where the guest's disk should land on the target. None takes preflight's
# default (the first pool that can hold a rootfs), which is every migration
# before this existed. A name that cannot hold one is a preflight blocker,
# never a silent swap.
```

</details>

**after**

```
    # Where the guest's disk should land on the target. None takes preflight's
    # default, the first pool that can hold a rootfs. A name that cannot hold
    # one is a preflight blocker, never a silent swap.
```

**`[532]`** `backend/proxploy/api/apps.py:1000` &middot; **54w → 39w** (28% cut) &middot; _data-integrity_  
The fresh-preflight rule binds; the task number does not.

<details><summary>before</summary>

```
Params handed to the job are ONLY app_id/target_host_id: strategy,
    target ctid and shared storage all come from a FRESH preflight the
    handler itself runs, never from this route's own preflight call below; 
    state (host connectivity, storage, capacity) can change in the gap
    between this request and the job actually running (Task 15 interfaces
    note).
```

</details>

**after**

```
    """Params handed to the job are ONLY app_id/target_host_id: strategy,
    target ctid and storage all come from a FRESH preflight the handler runs
    itself, because host connectivity, storage and capacity can change between
    this request and the job actually running."""
```

**`[533]`** `backend/proxploy/api/apps.py:1034` &middot; **96w → 75w** (22% cut) &middot; _data-integrity_  
Fail-before-stopping-the-guest is the point; the doc open-item number is not.

<details><summary>before</summary>

```
# Resolve every token this job will spend, BEFORE queueing it. Without this
# a host missing its lifecycle or backup token accepted the migration and
# discovered the gap inside the handler, which for a transfer means AFTER the
# source guest has been stopped. No network call happens here:
# client_for_host raises CapabilityNotConfigured on a missing credential
# alone, and main.py turns that into a 409 naming the capability and where to
# add it (doc 11 open item 3). The strategy decides which tokens are needed,
# which is why this sits after the preflight above rather than in a
# dependency.
```

</details>

**after**

```
    # Resolve every token this job will spend BEFORE queueing it. Without this
    # a host missing its lifecycle or backup token accepted the migration and
    # discovered the gap inside the handler, which for a transfer means AFTER
    # the source guest has been stopped. No network call happens here:
    # client_for_host raises CapabilityNotConfigured on a missing credential
    # alone. The strategy decides which tokens are needed, which is why this
    # sits after the preflight rather than in a dependency.
```

**`[534]`** `backend/proxploy/api/apps.py:1060` &middot; **45w → 34w** (24% cut) &middot; _security_  
Keep why the guard is on the operation rather than the target.

<details><summary>before</summary>

```
# The app's own name, typed back. Required for every uninstall that
# destroys a container, not only for Proxploy's own CT the way the
# lifecycle verbs are: stop is reversible and destroy is not, so the
# guard belongs on the operation rather than on the target.
```

</details>

**after**

```
    # The app's own name, typed back. Required for every uninstall that
    # destroys a container, not only for Proxploy's own CT: stop is reversible
    # and destroy is not, so the guard belongs on the operation.
```

**`[535]`** `backend/proxploy/api/apps.py:1081` &middot; **56w → 38w** (32% cut) &middot; _redundant_  
The icon_url sourcing is already explained at the payload; keep only the consequence.

<details><summary>before</summary>

```
# The tile an app wears when the catalog has no icon for it, which is every
# app adopted by hand: `icon_url` is served from the CATALOG entry
# (served_icon_url), so an app with no catalog slug can never have one, and
# initials plus a colour pair is the icon it CAN have. IconTile already
# draws exactly this.
```

</details>

**after**

```
    # The tile an app wears when the catalog has no icon for it, which is every
    # app adopted by hand: `icon_url` is served from the CATALOG entry, so an
    # app with no catalog slug can never have one.
```

**`[536]`** `backend/proxploy/api/apps.py:1094` &middot; **61w → 45w** (26% cut) &middot; _redundant_  
The UninstallIn field comments already define keep_ct; keep only the model statement.

<details><summary>before</summary>

```
Remove an app, either by destroying its CT or by forgetting it.

    Doc 01's apps-only model means one app is exactly one LXC container, so
    "uninstall" is "destroy that container". `keep_ct` is the escape hatch for
    the operator who wants Proxploy out of the way without losing the
    workload, and it is the inverse of adopt rather than a softer delete.
    
```

</details>

**after**

```
    """Remove an app, either by destroying its CT or by forgetting it. One app
    is exactly one LXC container, so "uninstall" is "destroy that container";
    `keep_ct` is the inverse of adopt, for the operator who wants Proxploy out
    of the way without losing the workload.
    """
```

**`[537]`** `backend/proxploy/api/apps.py:1141` &middot; **130w → 88w** (32% cut) &middot; _implementation-diary_  
Keep the sync-write and no-disk-resize decisions; drop the report filename and the sweep story.

<details><summary>before</summary>

```
Resize a CT and/or edit how Proxploy presents the app.

    Resource changes go straight to PVE rather than through a job: an lxc
    config write is synchronous there (see `guest_config_update`), so there is
    no task to track and reporting one would be theatre.

    Disk size is deliberately not here. Growing a CT's root volume is a
    different PVE endpoint and is one-way (PVE cannot shrink), which makes it
    its own feature with its own confirmation rather than a field on a PATCH.

    cores/memory/swap are VM.Config.CPU/Memory, lifecycle privileges, so the
    client below asks for "lifecycle" explicitly: this call site defaulted
    to whatever `client_for_host` resolved before per-capability tokens
    existed, which worked only because the one token in play was
    over-scoped. Found during the sweep (host-token-privileges-step-one-
    report.md), same class of gap as Sys.PowerMgmt.
    
```

</details>

**after**

```
    """Resize a CT and/or edit how Proxploy presents the app.

    Resource changes go straight to PVE rather than through a job: an lxc
    config write is synchronous there, so there is no task to track.

    Disk size is deliberately not here. Growing a CT's root volume is a
    different PVE endpoint and is one-way, since PVE cannot shrink, so it is
    its own feature with its own confirmation.

    cores/memory/swap are lifecycle privileges, so the client below asks for
    "lifecycle" explicitly rather than taking whatever `client_for_host`
    resolves by default.
    """
```

**`[538]`** `backend/proxploy/api/apps.py:1188` &middot; **47w → 41w** (13% cut) &middot; _security_  
Keep the validation rule and what blank means; drop the restatement.

<details><summary>before</summary>

```
# Only two values open in a browser, and a third would be stored as
# fact and then built into a URL that cannot load. Blank is allowed
# and means "clear it": that puts the app back to being asked which
# scheme it speaks rather than told (services/webui.py).
```

</details>

**after**

```
        # Only two values open in a browser, and a third would be stored as
        # fact and then built into a URL that cannot load. Blank is allowed and
        # clears it, putting the app back to being asked which scheme it speaks.
```

**`[539]`** `backend/proxploy/api/apps.py:1228` &middot; **37w → 31w** (16% cut) &middot; _security_  
The self-target refusal is the contract; the doc section numbers are not.

<details><summary>before</summary>

```
Shared by the apps and VMs routes, one guardrail, one audit shape.

    Doc 02 §9 / doc 08 §1: a destructive action against the CT Proxploy itself
    runs in is refused unless the caller types the name back.
    
```

</details>

**after**

```
    """Shared by the apps and VMs routes, one guardrail, one audit shape.

    A destructive action against the CT Proxploy itself runs in is refused
    unless the caller types the name back.
    """
```

**`[540]`** `backend/proxploy/api/apps.py:1257` &middot; **71w → 46w** (35% cut) &middot; _surprising_  
The registration-order trap stays; the phase/task numbers and test path go.

<details><summary>before</summary>

```
# WARNING: this wildcard is registered last and Starlette matches routes in
# registration order, so it will silently swallow any future two-segment
# sibling under /apps/{id}/...: e.g. /apps/{id}/update (Phase 7 Task 6) and
# /apps/{id}/migrate (Phase 8 Task 15) above. Register those routes with
# their literal action segments BEFORE this one, or they'll hit this handler
# instead and 422 with "action must be one of start, stop, restart, shutdown"
# (test_migrate_api.py::test_route_does_not_get_shadowed_by_the_lifecycle_wildcard
# is the regression check).
```

</details>

**after**

```
# WARNING: this wildcard is registered last and Starlette matches in
# registration order, so it will silently swallow any future two-segment
# sibling under /apps/{id}/..., e.g. /apps/{id}/update and /apps/{id}/migrate
# above. Register such routes with their literal action segments BEFORE this
# one, or they hit this handler and 422.
```


### 🟢 KEEP (15), unchanged

- **`[541]`** `88` &middot; _contract_ &middot; `# Read-only, and shown so the operator can see what the install script`
- **`[542]`** `234` &middot; _surprising_ &middot; `# No web_protocol, same reason as install: left NULL so the`
- **`[543]`** `403` &middot; _contract_ &middot; `# executor/keys.py raises this when the host carries no ssh_key. A 409`
- **`[544]`** `628` &middot; _contract_ &middot; `# Distinct from the "nothing pinned" 409 below: refreshing the catalog`
- **`[545]`** `657` &middot; _surprising_ &middot; `# Above the lifecycle wildcard, per that route's own WARNING further down.`
- **`[546]`** `667` &middot; _surprising_ &middot; `# Above the lifecycle wildcard, same as /{app_id}/network directly above:`
- **`[547]`** `826` &middot; _external-quirk_ &middot; `# {cidr:path}: a CIDR contains a slash and a plain path parameter stops at the`
- **`[548]`** `908` &middot; _surprising_ &middot; `# "/" is not an operator's answer, it is the column's own placeholder, so`
- **`[549]`** `912` &middot; _external-quirk_ &middot; `# `addresses`, not the config's `ip`: a container on DHCP has the literal`
- **`[550]`** `946` &middot; _contract_ &middot; `# So the dialog can preview the operator's chosen pool, including its`
- **`[551]`** `1065` &middot; _contract_ &middot; `# Forget the app without touching PVE. The inverse of adopt: the CT keeps`
- **`[552]`** `1072` &middot; _contract_ &middot; `# PVE-side resources. None means "leave alone"; this is a PATCH.`
- **`[553]`** `1076` &middot; _contract_ &middot; `# Proxploy-side presentation, no PVE call involved.`
- **`[554]`** `1117` &middot; _contract_ &middot; `# Deliberately the same 409 shape the self-target guard uses, so one`
- **`[555]`** `1201` &middot; _surprising_ &middot; `# web_protocol is the one field a None can mean "clear this" for, so`

---

## `backend/proxploy/services/appstore.py`

3,036 → 2,237 words, 26% cut. 1 delete, 25 shorten, 11 keep.


### 🔴 DELETE (1)

**`[556]`** `backend/proxploy/services/appstore.py:591` &middot; 7w &middot; _narration_  
Restates the condition on the line directly above it.

```
# finished before this job's window even opened
```


### 🟡 SHORTEN (25)

**`[557]`** `backend/proxploy/services/appstore.py:1` &middot; **59w → 49w** (17% cut) &middot; _ticket-history_  
Phase and task numbers go; the shape note and the consent boundary stay.

<details><summary>before</summary>

```
App Store install job handler (doc 10 Phase 4 DoD: pin + diff + consent +
stream + archive). Mirrors services/lifecycle.py's shape: blocking _resolve
helper in a thread, ctx.log/ctx.progress narration, JobFailed for expected
errors, module-bottom HANDLERS registration.

Root-consent gating lives at the API layer (Task 6), this handler assumes
the caller has already obtained consent and only does the pin + SSH-install
+ archive work.
```

</details>

**after**

```
"""App Store install job handler: pin, diff, consent, stream, archive.
Mirrors services/lifecycle.py's shape: blocking _resolve helper in a thread,
ctx.log/ctx.progress narration, JobFailed for expected errors, module-bottom
HANDLERS registration. Root-consent gating lives at the API layer; this
handler assumes consent and only does the pin, SSH install and archive work.
"""
```

**`[558]`** `backend/proxploy/services/appstore.py:37` &middot; **138w → 102w** (26% cut) &middot; _external-quirk_  
The no-version-numbers quirk, the derived-state rule and the skip reasons stay; doc refs and phrasing go.

<details><summary>before</summary>

```
Recompute `apps.update_available` for every app. Blocking.

    community-scripts publishes no version numbers (doc 01 §3), so the only
    honest signal is "the commit this app was pinned to is behind the commit
    the catalog now holds". The column stores the SHORT sha an update would
    move the app to, which is what doc 06's "Update to vX" renders.

    This is DERIVED state, recomputed wholesale rather than latched: an app
    that updated, or whose catalog entry was rolled back, must stop advertising
    an update. `cleared` counts exactly that.

    Skipped, each for a reason rather than as an oversight:
      - no `catalog_slug`, a hand-rolled CT adopted in Phase 4 has no upstream;
      - no `app_scripts` row, an adopted app has no "from" commit, so there is
        no diff to show and nothing to consent to;
      - catalog entry with no `upstream_sha`, never successfully refreshed.
    
```

</details>

**after**

```
    """Recompute `apps.update_available` for every app. Blocking.

    community-scripts publishes no version numbers, so the only honest signal
    is "the pinned commit is behind the commit the catalog now holds". The
    column stores the SHORT sha an update would move the app to.

    DERIVED state, recomputed wholesale rather than latched: an app that
    updated, or whose catalog entry was rolled back, must stop advertising an
    update. `cleared` counts exactly that.

    Skipped, each for a reason: no `catalog_slug`, a hand-adopted CT has no
    upstream; no `app_scripts` row, so no "from" commit to diff or consent to;
    a catalog entry with no `upstream_sha`, never successfully refreshed.
    """
```

**`[559]`** `backend/proxploy/services/appstore.py:119` &middot; **52w → 49w** (6% cut) &middot; _data-integrity_  
Keep the refusal and why the post-check exists; drop the restatement.

<details><summary>before</summary>

```
# Refuse to "install" onto a container that already exists: the catalog
# script would reconfigure or clobber somebody else's CT and this handler
# would then file an App row claiming to own it. Nothing to check yet when
# no ctid was supplied; the post-check below is what proves which id the
# node picked.
```

</details>

**after**

```
    # Refuse to "install" onto a container that already exists: the catalog
    # script would reconfigure or clobber somebody else's CT and this handler
    # would then file an App row claiming to own it. Nothing to check when no
    # ctid was supplied; the post-check below proves which id the node picked.
```

**`[560]`** `backend/proxploy/services/appstore.py:129` &middot; **196w → 133w** (32% cut) &middot; _external-quirk_  
All three upstream quirks and the do-not-revert warning stay; the phase count and narrative go.

<details><summary>before</summary>

```
# Two corrections a real node forced, both invisible to the fakes (PVE
# 9.2.6, 2026-08-10):
#
# `mode` is lowercase. build.func reads `CHOICE="${mode:-${1:-}}"` and
# never looks at MODE, which this handler exported for five phases: the
# menu was therefore always shown, whiptail read EOF from the DEVNULL
# stdin, and the script took its `|| exit_script` branch and exited 0
# having installed nothing.
#
# TERM must be a real terminal type. A non-PTY ssh session lands on
# TERM=dumb, where build.func's early `clear` exits 1 and its error trap
# aborts the run ("in line 1018: exit code 1").
#
# `mode` is also `generated`, not `default`. Both branches of build.func's
# case statement are byte-identical apart from METHOD (which reaches
# nothing but the telemetry payload) EXCEPT that `default` also runs
# `defaults_target="$(ensure_global_default_vars_file)"`, and that is what
# reaches ensure_storage_selection_for_vars_file at build.func:3533. On a
# host with two or more pools for a content type that function calls
# select_storage, whiptail cannot run without a TTY, `|| exit_script`
# fires, and exit_script does `exit 0`: a container is never created and
# the script reports success. This is the same failure shape as the
# uppercase-MODE bug documented above, in a second place. Do not revert
# this to `mode=default`: that silently reintroduces the exit 0.
```

</details>

**after**

```
    # Three corrections a real node forced, all invisible to the fakes:
    #
    # `mode` is lowercase. build.func reads `CHOICE="${mode:-${1:-}}"` and
    # never looks at MODE. With MODE the menu was always shown, whiptail read
    # EOF from the DEVNULL stdin, and the script took `|| exit_script` and
    # exited 0 having installed nothing.
    #
    # TERM must be a real terminal type. A non-PTY ssh session lands on
    # TERM=dumb, where build.func's early `clear` exits 1 and its error trap
    # aborts the run.
    #
    # `mode` is `generated`, not `default`. The two branches are identical
    # apart from METHOD EXCEPT that `default` also runs
    # `ensure_global_default_vars_file`, which reaches
    # ensure_storage_selection_for_vars_file at build.func:3533. With two or
    # more pools for a content type that calls select_storage, whiptail cannot
    # run without a TTY, `|| exit_script` fires, and exit_script does `exit 0`:
    # no container, reported as success. Do not revert to `mode=default`.
```

**`[561]`** `backend/proxploy/services/appstore.py:167` &middot; **94w → 66w** (30% cut) &middot; _external-quirk_  
Both reads of var_ctid and the absent-not-empty rule stay; the wording tightens.

<details><summary>before</summary>

```
# Set last so it always wins over an `overrides` entry: the App row
# below records this ctid as fact, so the container has to actually
# land there. misc/build.func honours it
# (`local requested_id="${var_ctid:-$NEXTID}"`).
#
# When ctid is None the key must be ABSENT from env, never present
# and empty: build.func reads it a second time at :1086 with
# `[[ -n "${var_ctid:-}" ]]`, which branches on non-empty, and only
# absence is honest about "let the node pick" under both that read
# and the `:-$NEXTID}` read above. An empty string happens to satisfy
# the first reader but not the second.
```

</details>

**after**

```
        # Set last so it always wins over an `overrides` entry: the App row
        # below records this ctid as fact. misc/build.func honours it
        # (`local requested_id="${var_ctid:-$NEXTID}"`).
        #
        # When ctid is None the key must be ABSENT, never present and empty:
        # build.func reads it again at :1086 with `[[ -n "${var_ctid:-}" ]]`,
        # which branches on non-empty. An empty string satisfies the first
        # reader but not the second, so only absence is honest.
```

**`[562]`** `backend/proxploy/services/appstore.py:191` &middot; **261w → 163w** (38% cut) &middot; _external-quirk_  
Every upstream fact stays; the restated framing and the ethics aside are cut.

<details><summary>before</summary>

```
# Decline community-scripts telemetry BEFORE the install runs, because
# build.func's diagnostics_check() draws an interactive whiptail radiolist
# ("TELEMETRY & DIAGNOSTICS") whenever its config file is absent. That is
# the same failure shape as select_storage, and it arrived from upstream
# with no change on our side.
#
# There is NO environment variable for this, and adding a DIAGNOSTICS=no
# to `env` above would be theatre: variables() does a hard
# `DIAGNOSTICS="no"` assignment, not `${DIAGNOSTICS:-no}`, so anything we
# export is overwritten before diagnostics_check() is reached, and that
# function ignores the variable's value anyway when the file is missing.
# The file is the only control surface upstream offers.
#
# Why we are not already broken: the whiptail call ends in
# `|| result="no"`, so a non-TTY session falls through to "no" and then
# WRITES the file, which is why only the first install on a node ever saw
# the dialog. That is a fallback on failure, not a supported
# non-interactive path, and it is one upstream edit away from becoming a
# hang. Do not rely on it.
#
# Written only when absent, so an operator who opted IN from the node's
# own shell keeps their choice; this refuses to answer a question on their
# behalf, it only refuses to be ASKED one in a session with no terminal.
#
# A separate SSH call rather than a prefix on the install command below:
# `env` is inlined as a `KEY=value ...` prefix by executor/ssh.py, and
# those assignments only apply to the FIRST simple command, so gluing a
# guard on with `;` would silently strip mode/PHS_SILENT/every var_* from
# the install itself. Not worth reshaping that command to save a
# connection.
```

</details>

**after**

```
    # Decline community-scripts telemetry BEFORE the install runs:
    # build.func's diagnostics_check() draws an interactive whiptail radiolist
    # whenever its config file is absent, the same failure shape as
    # select_storage.
    #
    # There is NO environment variable for this. variables() does a hard
    # `DIAGNOSTICS="no"` assignment, not `${DIAGNOSTICS:-no}`, so anything we
    # export is overwritten first, and diagnostics_check() ignores the value
    # anyway when the file is missing. The file is upstream's only control
    # surface.
    #
    # Do not rely on the current escape: the whiptail call ends in
    # `|| result="no"`, so a non-TTY session falls through and writes the file
    # itself. That is a fallback on failure, one upstream edit from a hang.
    #
    # Written only when absent, so an operator who opted IN from the node's
    # own shell keeps their choice.
    #
    # A separate SSH call, not a prefix on the install command: `env` is
    # inlined as a `KEY=value ...` prefix by executor/ssh.py and those
    # assignments apply only to the FIRST simple command, so gluing a guard on
    # with `;` would strip mode/PHS_SILENT/every var_* from the install.
```

**`[563]`** `backend/proxploy/services/appstore.py:236` &middot; **143w → 114w** (20% cut) &middot; _security_  
The pin rule, the residual limitation and the quoting reason all stay, tighter.

<details><summary>before</summary>

```
# Pinned to the exact commit that was ingested, classified and diffed; 
# not to `main`, which would be a fresh, possibly-different fetch at
# execution time and would make the app_scripts pin decorative.
#
# RESIDUAL LIMITATION (deliberately not solved here): the pinned ct/*.sh
# itself contains a literal `source <(curl -fsSL .../main/misc/build.func)`
# line. That line's text is frozen at this commit, but the framework file
# it names is still fetched live from `main` at execution time, one level
# down. Full transitive vendoring of the community-scripts framework is a
# separate, larger piece of work.
# The URL is quoted, the `$(...)` around it is not: `bash -c "$(curl ...)"`
# runs the downloaded script, while quoting the whole substitution would
# make its output a command *word* instead, which is a different thing.
# script_path comes from the upstream catalog, so it is not ours to trust
# as a bare word inside the substitution.
```

</details>

**after**

```
    # Pinned to the exact commit that was ingested, classified and diffed, not
    # to `main`, which would be a fresh fetch at execution time and would make
    # the app_scripts pin decorative.
    #
    # RESIDUAL LIMITATION: the pinned ct/*.sh still contains a literal
    # `source <(curl -fsSL .../main/misc/build.func)`. That line's text is
    # frozen, but the framework file it names is fetched live from `main` one
    # level down. Vendoring the framework is separate, larger work.
    #
    # The URL is quoted, the `$(...)` around it is not: `bash -c "$(curl ...)"`
    # runs the downloaded script, while quoting the whole substitution would
    # make its output a command *word*. script_path comes from the upstream
    # catalog, so it is not ours to trust as a bare word.
```

**`[564]`** `backend/proxploy/services/appstore.py:254` &middot; **60w → 46w** (23% cut) &middot; _surprising_  
Keep the retention reason for not reading job_events back; drop the second, weaker reason.

<details><summary>before</summary>

```
# The script's last words are where it prints the finished URL, so they
# are kept as they stream rather than read back out of job_events
# afterwards. Two reasons: they are already in hand here, and job_events
# has no retention policy today, so a parse that depended on rows still
# being there would quietly stop working the day someone adds pruning.
```

</details>

**after**

```
    # The script's last words are where it prints the finished URL, so they are
    # kept as they stream rather than read back out of job_events: job_events
    # has no retention policy, so a parse depending on those rows would quietly
    # stop working the day someone adds pruning.
```

**`[565]`** `backend/proxploy/services/appstore.py:278` &middot; **61w → 49w** (20% cut) &middot; _external-quirk_  
Exit 0 is not proof of an install; the first-hardware-run anecdote is not needed to say so.

<details><summary>before</summary>

```
# Exit status 0 is NOT proof the container was built. build.func's own
# cancel path (`|| exit_script`) exits 0, so a script that showed a menu
# and gave up looks identical here to one that installed cleanly. Without
# this check the handler filed an App row for a CT that does not exist,
# which is exactly what happened on the first real-hardware run.
```

</details>

**after**

```
    # Exit status 0 is NOT proof the container was built. build.func's cancel
    # path (`|| exit_script`) exits 0, so a script that showed a menu and gave
    # up looks identical to one that installed cleanly. Without this check the
    # handler filed an App row for a CT that does not exist.
```

**`[566]`** `backend/proxploy/services/appstore.py:285` &middot; **54w → 50w** (7% cut) &middot; _data-integrity_  
Keep the one-container assumption and that breaking it fails loudly.

<details><summary>before</summary>

```
# No id was pinned, so read back which one build.func picked from the
# diff of the id sets. This assumes an install creates exactly one
# container, true of every ct/ script today, and the failure mode
# when that assumption breaks is loud (JobFailed) rather than a
# silently wrong id recorded on the App row.
```

</details>

**after**

```
        # No id was pinned, so read back which one build.func picked from the
        # diff of the id sets. This assumes an install creates exactly one
        # container, true of every ct/ script today, and the failure when that
        # breaks is loud rather than a silently wrong id on the App row.
```

**`[567]`** `backend/proxploy/services/appstore.py:311` &middot; **91w → 81w** (11% cut) &middot; _surprising_  
Both facts stay: NULL protocol on purpose, installed_url only trusted after exit 0.

<details><summary>before</summary>

```
# No web_protocol: whether this app speaks http or https
# is not something an install knows, and writing "http"
# here is what used to send Open at the wrong scheme.
# Left NULL so the app is asked (services/webui.py).
#
# `installed_url` is what the script printed about
# itself, and it is only read after the run exited 0:
# a failed install can still have printed a URL, for a
# container that was then rolled back. The catalog's
# port corroborates it, so a documentation link printed
# near the end cannot win over the real one.
```

</details>

**after**

```
                      # No web_protocol: an install does not know whether the
                      # app speaks http or https, and writing "http" here is
                      # what used to send Open at the wrong scheme. Left NULL
                      # so the app is asked (services/webui.py).
                      #
                      # `installed_url` is what the script printed, read only
                      # after exit 0: a failed install can still have printed
                      # a URL for a container that was rolled back. The
                      # catalog's port corroborates it, so a documentation
                      # link near the end cannot win over the real one.
```

**`[568]`** `backend/proxploy/services/appstore.py:328` &middot; **100w → 69w** (31% cut) &middot; _data-integrity_  
The rowid-reuse collision and the reason for clearing stay; the history of how orphans arise goes.

<details><summary>before</summary>

```
# A freshly created App row can never legitimately own an
# app_scripts row yet, so any that exist for this id are stale by
# definition. SQLite reissues row ids once a table is empty (or
# once older rows are gone), so a leftover row from a deleted app
# (an orphan left by a path that bypassed the FK cascade, or from
# before db.py started enforcing foreign keys) can collide with
# the id this brand new app was just given. One poisoned row must
# never be able to brick every future install on
# ux_app_scripts, so clear it before writing the real one.
```

</details>

**after**

```
            # A freshly created App row can never legitimately own an
            # app_scripts row, so any that exist for this id are stale. SQLite
            # reissues row ids once older rows are gone, so an orphan left by
            # a path that bypassed the FK cascade can collide with the id this
            # brand new app was just given. One poisoned row must never brick
            # every future install on ux_app_scripts, so clear it first.
```

**`[569]`** `backend/proxploy/services/appstore.py:344` &middot; **90w → 65w** (28% cut) &middot; _security_  
The leak rule and the recovery path stay; the reassurances shorten.

<details><summary>before</summary>

```
# The container is REAL and RUNNING on the node at this point; only
# the bookkeeping failed. A raw DB error can carry the full SQL
# statement, every bound parameter, and even the install script text
# (SQLAlchemy's IntegrityError.__str__ includes all three), and none
# of that may ever reach the user. Say plainly what actually
# happened instead. Nothing on the node is touched: the container is
# not removed, and it will show up as a discovered, not-yet-adopted
# container on the Apps page, where it can be adopted to bring it
# under management.
```

</details>

**after**

```
        # The container is REAL and RUNNING; only the bookkeeping failed. A raw
        # DB error can carry the full SQL, every bound parameter and the
        # install script text (SQLAlchemy's IntegrityError.__str__ includes all
        # three), and none of that may reach the user. Nothing on the node is
        # touched: the container stays and shows up as a discovered container
        # on the Apps page, where it can be adopted.
```

**`[570]`** `backend/proxploy/services/appstore.py:362` &middot; **73w → 46w** (37% cut) &middot; _narration_  
Keep why the poller needs waking; drop the identity-ownership aside and the doc ref.

<details><summary>before</summary>

```
# The App row above is ours to write (identity is Proxploy's, doc 04), but
# everything live about it, its status, cpu, memory, address, comes from the
# poller's snapshot of /cluster/resources, and the CT this install just made
# is not in that snapshot yet. Without the wake a brand new app sits at
# "unknown" for up to a poll interval; the CT is readable within tens of
# milliseconds of the install finishing (see Poller.wake).
```

</details>

**after**

```
    # Everything live about an app, its status, cpu, memory and address, comes
    # from the poller's snapshot of /cluster/resources, and the CT this install
    # just made is not in it yet. Without the wake a brand new app sits at
    # "unknown" for up to a poll interval.
```

**`[571]`** `backend/proxploy/services/appstore.py:399` &middot; **49w → 40w** (18% cut) &middot; _data-integrity_  
Keep why the edited check is explicit rather than inferred from a NULL.

<details><summary>before</summary>

```
# api/apps.py::put_app_script writes an "edited" row WITHOUT an
# upstream_ref, so from_ref would read None below regardless: but
# that's an accident of that route, not something to depend on here.
# Checked explicitly: if it's ever backfilled with a ref, silently
# trusting upstream_ref==None would stop catching this and overwrite
# the operator's edits.
```

</details>

**after**

```
        # api/apps.py::put_app_script writes an "edited" row WITHOUT an
        # upstream_ref, so from_ref would read None below anyway, but that is
        # an accident of that route. Checked explicitly: if it is ever
        # backfilled with a ref, trusting the NULL would overwrite the edits.
```

**`[572]`** `backend/proxploy/services/appstore.py:406` &middot; **29w → 27w** (7% cut) &middot; _ticket-history_  
The pointer to the way out stays, the task number goes.

<details><summary>before</summary>

```
# api/apps.py::revert_app_script (Task 6) is the way out: it pins
# a fresh version sourced "upstream" so this guard clears. Point
# at it by name rather than making the operator guess.
```

</details>

**after**

```
            # api/apps.py::revert_app_script is the way out: it pins a fresh
            # version sourced "upstream" so this guard clears. Point at it by
            # name rather than making the operator guess.
```

**`[573]`** `backend/proxploy/services/appstore.py:437` &middot; **49w → 43w** (12% cut) &middot; _data-integrity_  
Keep why a cached snapshot is the wrong input for a safety check.

<details><summary>before</summary>

```
Blocking: every LXC id currently on the host, straight from PVE.

    One `/cluster/resources` call, the same read the poller makes. Deliberately
    NOT the poller's cached snapshot: this is a safety check, and a cache up to
    30 s stale is exactly what would miss a container created seconds ago.
    
```

</details>

**after**

```
    """Blocking: every LXC id currently on the host, straight from PVE.

    One `/cluster/resources` call. Deliberately NOT the poller's cached
    snapshot: this is a safety check, and a cache up to 30 s stale is exactly
    what would miss a container created seconds ago.
    """
```

**`[574]`** `backend/proxploy/services/appstore.py:456` &middot; **90w → 56w** (38% cut) &middot; _redundant_  
The cache reason is already argued in _lxc_ids; point at it instead of repeating it.

<details><summary>before</summary>

```
Blocking: the pool names on this host's node that carry `content`.

    The API-side equivalent of build.func's `pvesm status -content
    "$content"`, the query whose result becomes an interactive picker when it
    returns more than one row. Deliberately NOT the poller's cached snapshot,
    for the same reason `_lxc_ids` gives: this decides where a container's
    disk lands, and a 30 s stale cache is the wrong input for that.

    Sorted so a caller comparing two candidate lists gets a stable answer, and
    so an error message naming them reads the same every time.
    
```

</details>

**after**

```
    """Blocking: the pool names on this host's node that carry `content`.

    The API-side equivalent of build.func's `pvesm status -content "$content"`,
    the query that becomes an interactive picker when it returns more than one
    row. Not the poller's cached snapshot, same reason `_lxc_ids` gives. Sorted
    so two candidate lists compare stably and error messages read the same.
    """
```

**`[575]`** `backend/proxploy/services/appstore.py:495` &middot; **265w → 188w** (29% cut) &middot; _external-quirk_  
NEVER PICKS, the fallback order and the 238-hang all stay; the removed-feature history goes.

<details><summary>before</summary>

```
The container and template pools for this install, or JobFailed.

    THIS FUNCTION NEVER PICKS. Which pool a container's disk lands on is a
    question, and choosing one on the operator's behalf is exactly the
    interactive-picker problem this design exists to refuse: build.func asks
    that question itself with `pvesm status -content "$content"` whenever it
    finds more than one candidate, and over a non-interactive SSH session that
    picker cannot be answered, so the run hangs. The order tried here is:

      1. what the operator supplied for this install (`supplied`)
      2. the sole candidate, if the node has exactly one. This is not a pick:
         there is nothing to choose between.
      3. refuse, naming the candidates so the operator can choose

    Nothing here is remembered across installs (PXP-86 decision): a host
    with two or more pools for a content type is asked every single time,
    never silently answered from a prior install on the same host. That is
    a deliberate simplification, not an oversight; an earlier version of
    this function also tried a value remembered on Host.default_*_storage
    between (1) and (2), and PXP-86 removed it.

    Every value taken from (1) is revalidated against the node's current
    content list before use. A pool name that is stale or was never valid
    reaches build.func's resolve_storage_preselect, whose failure branch
    returns 238 and then spins in a `while true` with an empty body: a real
    hang that our 1800 s SSH timeout would surface as an opaque
    `TimeoutError: ` with no message. Sending an unvalidated name is worse
    than sending none, so nothing here is ever trusted without being checked
    against `_storage_pools` first.
    
```

</details>

**after**

```
    """The container and template pools for this install, or JobFailed.

    THIS FUNCTION NEVER PICKS. Choosing a pool on the operator's behalf is the
    interactive-picker problem this design exists to refuse: build.func asks
    that question itself with `pvesm status -content "$content"` whenever it
    finds more than one candidate, and over a non-interactive SSH session that
    picker cannot be answered, so the run hangs. The order is:

      1. what the operator supplied for this install (`supplied`)
      2. the sole candidate, if the node has exactly one. Not a pick: there is
         nothing to choose between.
      3. refuse, naming the candidates so the operator can choose

    Nothing is remembered across installs: a host with two or more pools for a
    content type is asked every time, never answered from a prior install.

    Every value from (1) is revalidated against the node's current content list
    first. A stale or never-valid name reaches build.func's
    resolve_storage_preselect, whose failure branch returns 238 and then spins
    in a `while true` with an empty body: a real hang our 1800 s SSH timeout
    surfaces as an opaque `TimeoutError: `. Sending an unvalidated name is
    worse than sending none.
    """
```

**`[576]`** `backend/proxploy/services/appstore.py:531` &middot; **42w → 38w** (10% cut) &middot; _contract_  
Keep why a non-string override value must be coerced first.

<details><summary>before</summary>

```
# str(...) first: the API validator constrains override KEYS to a
# shell-identifier pattern but not value types, so a non-string value
# (e.g. {"container_storage": 5}) reaches here and `.strip()` on a
# bare int raises AttributeError instead of one of this function's
# deliberately-written JobFailed messages.
```

</details>

**after**

```
        # str(...) first: the API validator constrains override KEYS to a
        # shell-identifier pattern but not value types, so a non-string value
        # reaches here and `.strip()` on a bare int raises AttributeError
        # instead of one of this function's JobFailed messages.
```

**`[577]`** `backend/proxploy/services/appstore.py:555` &middot; **46w → 42w** (9% cut) &middot; _concurrency_  
The concurrent-job reasoning stays, the review label goes.

<details><summary>before</summary>

```
# Job kinds that build a new guest (Task 5 review B1). JobBackend runs up to
# MAX_CONCURRENT jobs at once, so an id appearing in `after` that wasn't in
# `before` may belong to one of these running concurrently, not to this
# update's script taking build.func's install branch.
```

</details>

**after**

```
# Job kinds that build a new guest. JobBackend runs up to MAX_CONCURRENT jobs
# at once, so an id appearing in `after` that wasn't in `before` may belong to
# one of these running concurrently, not to this update's script taking
# build.func's install branch.
```

**`[578]`** `backend/proxploy/services/appstore.py:564` &middot; **148w → 90w** (39% cut) &middot; _concurrency_  
Keep what is and is not knowable per job kind; drop the task and review asides.

<details><summary>before</summary>

```
Blocking: ctids from OTHER guest-creating jobs whose run overlapped
    this job's SSH window, so the stray-CT check doesn't blame; and point an
    operator at destroying, a legitimate container an unrelated job built at
    the same time.

    Only `app.install`'s target id is knowable without guessing, and only when
    the operator supplied one: `params["ctid"]` is passed to the remote script
    as `var_ctid`, so a job that has one built exactly that id, finished or
    not. A CTID-less install (Task 5 made the field optional; the node then
    assigns the next free id) contributes NOTHING here, because the id it
    built is not knowable until it has built it.
    `vm.create`/`vm.clone` are qemu-only (services/guestjobs.py, doc 05) and
    can never produce an LXC row in the first place, so nothing is extracted
    for them, they're queried (per review) alongside app.install for
    completeness, not because either can contribute an id `_lxc_ids` would
    ever see.
    
```

</details>

**after**

```
    """Blocking: ctids from OTHER guest-creating jobs whose run overlapped this
    job's SSH window, so the stray-CT check does not point an operator at
    destroying a container an unrelated job legitimately built.

    Only `app.install`'s target id is knowable without guessing, and only when
    the operator supplied one: `params["ctid"]` reaches the script as
    `var_ctid`, so a job that has one built exactly that id. A CTID-less
    install contributes NOTHING, because the id it built is not knowable until
    it has built it. `vm.create`/`vm.clone` are qemu-only and can never produce
    an LXC row.
    """
```

**`[579]`** `backend/proxploy/services/appstore.py:601` &middot; **318w → 197w** (38% cut) &middot; _data-integrity_  
Both residual limitations and the two-guard reasoning stay; the doc quotes and review labels go.

<details><summary>before</summary>

```
`app.update`, re-run the app's catalog script, pinned to the CURRENT
    upstream commit, over the same SSH path install uses (doc 10 Phase 7:
    "same pin/diff/consent/stream/archive path as install").

    Consent and the upstream diff are the API layer's job (Task 6), exactly as
    install splits them; this handler assumes both were obtained.

    Two guards bracket the SSH run. A community-scripts `ct/*.sh` decides for
    itself whether it is installing or updating, `build.func`'s `start` routes
    to `update_script()` when it finds the container and to `build_container()`
    when it does not, and Proxploy cannot see inside that decision. The
    failure mode when it goes the wrong way is a second container built while
    the `apps` row still points at the first. So the CT must exist BEFORE
    (otherwise the script would certainly install fresh), and no new CT may
    exist AFTER (otherwise it installed anyway, and the job must say so rather
    than report success over a stray container).

    RESIDUAL LIMITATION, stated rather than hidden: whether a given entry's
    update path is non-interactive is a property of that upstream script.
    services/classifier.py classifies INSTALL feasibility only. An update path
    that prompts aborts under `catch_errors`' `set -Ee` and this job fails with
    the full transcript archived, the honest outcome. Classifying update paths
    is separate, larger work, not attempted here.

    A SECOND, more severe residual limitation (Task 5 review B4): the post-
    check is an id-SET comparison (before vs. after), and a set diff is blind
    to a script that destroys CT <ctid> and rebuilds it at the SAME id, no id
    is added, none is missing, the diff sees nothing wrong, and this handler
    reports success and advances the pin over what is now a freshly built,
    EMPTY container. This is undetected. It is the one failure mode here with
    real data loss, and nothing in `_lxc_ids`'s id-set approach can catch it;
    detecting it would need something like a creation-time/uptime marker,
    deliberately not attempted here.
    
```

</details>

**after**

```
    """`app.update`: re-run the app's catalog script, pinned to the CURRENT
    upstream commit, over the same SSH path install uses. Consent and the diff
    are the API layer's job.

    Two guards bracket the SSH run. A community-scripts `ct/*.sh` decides for
    itself whether it is installing or updating: `build.func`'s `start` routes
    to `update_script()` when it finds the container and `build_container()`
    when it does not, and Proxploy cannot see inside that decision. Going the
    wrong way builds a second container while the `apps` row still points at
    the first, so the CT must exist BEFORE and no new CT may exist AFTER.

    RESIDUAL LIMITATION: whether an entry's update path is non-interactive is a
    property of that upstream script, and services/classifier.py classifies
    INSTALL feasibility only. An update path that prompts aborts under
    `set -Ee` and this job fails with the transcript archived.

    A SECOND, more severe one: the post-check is an id-SET comparison, so it is
    blind to a script that destroys CT <ctid> and rebuilds it at the SAME id.
    Nothing is added or missing, so this reports success and advances the pin
    over a freshly built, EMPTY container. Undetected, and the one failure mode
    here with real data loss.
    """
```

**`[580]`** `backend/proxploy/services/appstore.py:661` &middot; **169w → 108w** (36% cut) &middot; _external-quirk_  
The pveversion branch quirk is load-bearing; the pin paragraph repeats run_install and the hardware log is history.

<details><summary>before</summary>

```
# Pinned to the exact commit that was ingested and classified, never to
# `main`: identical rule and identical raw_url() helper as run_install,
# and it carries the same one-level-down residual: the pinned script's own
# `source <(curl ... /main/misc/build.func)` line is frozen text but still
# fetches live.
#
# Run it INSIDE the container, not on the host. build.func's start() picks
# install-vs-update by where it is running, nothing else:
#
#     if command -v pveversion; then install_script        # on the PVE host
#     elif [ "$PHS_SILENT" == 1 ]; then update_script      # in the CT
#
# `pveversion` exists on the host, so running this over plain host SSH took
# the install branch every time and built a SECOND container instead of
# updating this one. Verified on PVE 9.2.6, 2026-08-10: host-side produced
# a stray CT 100 with a duplicate AdGuard; `pct exec` into the CT reached
# the real update path and created nothing. No env var changes that choice.
#
# The env goes INSIDE the pct exec: the executor's own `env=` is a prefix
# on the outer host command and does not cross into the container.
```

</details>

**after**

```
    # Pinned to the exact commit, never `main`: same rule and same raw_url()
    # helper as run_install, with the same one-level-down residual.
    #
    # Run it INSIDE the container, not on the host. build.func's start() picks
    # install-vs-update purely by where it is running:
    #
    #     if command -v pveversion; then install_script        # on the PVE host
    #     elif [ "$PHS_SILENT" == 1 ]; then update_script      # in the CT
    #
    # `pveversion` exists on the host, so plain host SSH took the install
    # branch every time and built a SECOND container. No env var changes that.
    #
    # The env goes INSIDE the pct exec: the executor's own `env=` is a prefix
    # on the outer host command and does not cross into the container.
```

**`[581]`** `backend/proxploy/services/appstore.py:711` &middot; **74w → 48w** (35% cut) &middot; _concurrency_  
Keep why the message is not an imperative and why retrying is risky; drop the review labels.

<details><summary>before</summary>

```
# Never an imperative "remove it" (Task 5 review B1): this is a
# whole-cluster snapshot diff and JobBackend runs jobs concurrently,
# so a stray id here is not proof this update's script built it: it
# could just as well be an unrelated job that landed in the same
# window. B2: also tell the truth about retrying: the pin and
# update_available are both left untouched below, and a plain retry
# hits the same install branch again.
```

</details>

**after**

```
        # Never an imperative "remove it": this is a whole-cluster snapshot
        # diff and jobs run concurrently, so a stray id is not proof this
        # update's script built it. And tell the truth about retrying: the pin
        # is left untouched below, so a plain retry hits the same branch again.
```


### 🟢 KEEP (11), unchanged

- **`[582]`** `30` &middot; _contract_ &middot; `The upstream commit the app's newest saved script came from.`
- **`[583]`** `76` &middot; _security_ &middot; `Blocking: (catalog row, host, install script). Runs in a thread.`
- **`[584]`** `90` &middot; _security_ &middot; `# Without a pinned commit there is nothing to execute that matches`
- **`[585]`** `98` &middot; _external-quirk_ &middot; `# Whatever shape upstream ships the payload in: five apps carry it`
- **`[586]`** `157` &middot; _external-quirk_ &middot; `# Sent on EVERY install, Default included. build.func only auto-picks when`
- **`[587]`** `183` &middot; _concurrency_ &middot; `# Fresh session, not the `_resolve` one above: that session is`
- **`[588]`** `231` &middot; _contract_ &middot; `# Never fails the install: the worst case is the state we were already`
- **`[589]`** `302` &middot; _data-integrity_ &middot; `# host_id is part of the slug, not just catalog_slug+ctid: App.slug has a`
- **`[590]`** `377` &middot; _contract_ &middot; `Blocking: (app row fields, host row fields, catalog entry fields).`
- **`[591]`** `488` &middot; _contract_ &middot; `# (overrides key, build.func content type)`
- **`[592]`** `731` &middot; _data-integrity_ &middot; `# The pin advances only now, on a run that provably updated this container.`

---

## `backend/proxploy/services/migrate.py`

2,785 → 1,890 words, 32% cut. 5 delete, 28 shorten, 18 keep.


### 🔴 DELETE (5)

**`[593]`** `backend/proxploy/services/migrate.py:1` &middot; 1w &middot; _generated_  
Filename banner repeating the file's own path.

```
# backend/proxploy/services/migrate.py
```

**`[594]`** `backend/proxploy/services/migrate.py:403` &middot; 34w &middot; _redundant_  
Repeats the staging-vs-rootfs comment 50 lines above.

```
# The pool the guest's disk will land on, and (transfer only) the pool
# the archive is staged in. Both named so the preview is checkable
# against the result rather than being an unexplained number.
```

**`[595]`** `backend/proxploy/services/migrate.py:407` &middot; 28w &middot; _redundant_  
rootfs_candidates' own docstring already says it exists so the dialog can offer the choice and the route can refuse a name outside it.

```
# Every pool the disk COULD land on, so the dialog can offer the choice
# without a second round trip and the route can refuse a name outside it.
```

**`[596]`** `backend/proxploy/services/migrate.py:504` &middot; 16w &middot; _redundant_  
The docstring's lazy-resolution paragraph already says exactly this.

```
# vzdump/restore/cleanup: only the two strategies that
# actually back up and restore need this token at all.
```

**`[597]`** `backend/proxploy/services/migrate.py:605` &middot; 35w &middot; _redundant_  
_restore_storage's docstring and preflight's own comment already state that the operator's pool is carried through.

```
# The pool the operator picked, carried through so the job restores where the
# dialog said it would rather than re-guessing. None means "use the default",
# which is what every migration before this parameter existed sent.
```


### 🟡 SHORTEN (28)

**`[598]`** `backend/proxploy/services/migrate.py:2` &middot; **494w → 218w** (56% cut) &middot; _test-reference_  
Keep the live-state rule, the honesty rule, the fresh-preflight rule and the cleanup guarantee; the fakes inventory goes entirely.

<details><summary>before</summary>

```
Cross-host app migration, preflight + `migrate.app` job handler (doc 05,
doc 08 §14, doc 11 §2).

Strategy is decided from LIVE Proxmox state, never from `hosts.cluster_name`:
grep across the whole tree at plan time turned up nothing that ever writes
that column, so trusting it would be a silent lie. This preflight is the
first thing that ever populates it, honestly, as a side effect of the very
cluster_status() call that justified the choice, for the one strategy
(`cluster`) where the value is actually true at the moment it's written.

Every number in the response is either a live PVE read or an explicit
`None` with a note saying why it couldn't be obtained. `est_downtime_s` is
never a guess dressed up as a number: doc 10's DoD requires "accurate
downtime shown", and a plausible-looking fabricated estimate is worse than
an honest "unknown" (doc 11 §2: downtime UX must state the truth).

The `migrate.app` job handler (Task 15, below) re-runs `preflight()` itself
params handed in from the route are only `app_id`/`target_host_id`, never
the strategy/ctid/storage the route's own preflight call saw, because state
can change in the gap between an operator clicking "migrate" and the job
actually running. `est_downtime_s` above is an ESTIMATE; `downtime_s` in the
job's result is MEASURED wall-clock time from the moment the source guest is
(or would be) stopped to the moment the target guest is confirmed running, 
that is the number doc 10's "accurate downtime shown" DoD is actually about.

The transfer strategy (Task 16, no shared cluster, no shared backup storage)
runs a vzdump on the source into its own local dir storage, streams the
resulting archive to the target's local dir storage over SFTP through
`executor/transfer.py::sftp_copy_for_hosts` (the only module outside
executor/ ever allowed to call it, it hands over host ids and a
sessionmaker/secretstore, never key bytes), then restores from the
target-local copy exactly like the shared-storage branch restores from a
shared one. Both scratch archives (source vzdump output, target copy) are
transfer plumbing, not real backups; `_cleanup_volume` best-effort deletes
both on every exit path, success or failure, so a migration never leaves
either host's storage silently filling up with orphaned dump files.

FAKES vs HARDWARE: every PVE call below goes through `services/proxmox.py`'s
`ProxmoxClient`, which in every test in this repo is backed by
`tests/fakes/pve.py::FakePVE`: there is no live Proxmox host here and never
will be. The transfer strategy additionally goes through
`app.state.ssh_connect_factory`, backed in every test by
`tests/fakes/ssh.py::FakeSSHConnection`/`FakeSFTP`; there is no real SSH
target here either. What the tests prove: the handler's call sequence, its
honesty properties (measured not estimated downtime, source never destroyed,
no repoint before a health check passes, transfer artifacts cleaned up on
both hosts), and its JobFailed/rollback-messaging behaviour, all GIVEN the
PVE API shapes FakePVE encodes and the SFTP semantics FakeSFTP encodes. What
they do NOT prove: that a real PVE 8.x/9.x vzdump/restore cycle or a real
OpenSSH SFTP transfer behaves this way end-to-end on real disks over a real
network, that needs live hardware.
```

</details>

**after**

```
"""Cross-host app migration: preflight plus the `migrate.app` job handler.

Strategy is decided from LIVE Proxmox state, never from `hosts.cluster_name`:
nothing else in the tree writes that column, so trusting it would be a silent
lie. This preflight is the first thing that populates it, and only for the
`cluster` strategy, where the value is true at the moment it is written.

Every number in the response is either a live PVE read or an explicit `None`
with a note saying why: a plausible fabricated estimate is worse than an
honest "unknown". `est_downtime_s` is an ESTIMATE; the job's `downtime_s` is
MEASURED wall-clock time from the source guest stopping to the target guest
confirmed running.

The handler re-runs `preflight()` itself. Params from the route are only
`app_id`/`target_host_id`, never the strategy/ctid/storage the route's own
preflight saw, because state can change before the job runs.

The transfer strategy (no shared cluster, no shared backup storage) vzdumps
on the source into local dir storage, streams the archive to the target over
SFTP through `executor/transfer.py::sftp_copy_for_hosts` (the only module
outside executor/ allowed to call it: it gets host ids and a
sessionmaker/secretstore, never key bytes), then restores from the
target-local copy. Both scratch archives are plumbing, not backups, and
`_cleanup_volume` deletes both on every exit path so neither host's storage
silently fills with orphaned dumps.
"""
```

**`[599]`** `backend/proxploy/services/migrate.py:93` &middot; **133w → 90w** (32% cut) &middot; _external-quirk_  
The `nodes`/`disable` fields and the consequence of ignoring them stay; the check number and pool names go.

<details><summary>before</summary>

```
Does `node` actually serve this storage?

    `cluster_storage()` is `GET /storage`, the cluster-wide CONFIGURATION, so
    it lists every definition regardless of which nodes carry it. Two fields
    decide, and neither was read: `nodes` restricts a storage to named nodes,
    and `disable` switches one off entirely.

    Found on real hardware (doc 12 check 7): with `nfs-shared` set to
    `--nodes node2`, preflight offered it as the shared storage for a migration
    off `node1`, while `pvesm status` on `node1` reported that same pool
    `disabled` in the same minute. A STRATEGY_SHARED migration would then vzdump
    to a pool the source cannot write, refusing on a storage error when a
    working transfer path was available. No fixture carries either field.

    `node` None means "do not filter", which is what a caller that genuinely
    wants the cluster's whole config passes.
    
```

</details>

**after**

```
    """Does `node` actually serve this storage?

    `cluster_storage()` is `GET /storage`, the cluster-wide CONFIGURATION, so
    it lists every definition regardless of which nodes carry it. Two fields
    decide: `nodes` restricts a storage to named nodes, `disable` switches one
    off. Ignoring them offered a pool restricted to another node as the shared
    storage for a migration, one that `pvesm status` reported disabled on the
    source in the same minute: the vzdump would then go to a pool the source
    cannot write. No fixture carries either field.

    `node` None means "do not filter".
    """
```

**`[600]`** `backend/proxploy/services/migrate.py:139` &middot; **47w → 38w** (19% cut) &middot; _narration_  
Keep what the pick is and why it is recomputed; drop the aside about route callers.

<details><summary>before</summary>

```
Same pick as preflight's `capacity_storage` for the transfer strategy:
    the lexicographically-first dir-type backup storage this NODE serves.
    Recomputed here (rather than threaded through `preflight()`'s return dict)
    because `preflight()` already discards this name once it has used it for the
    capacity check, and route callers never need it.
```

</details>

**after**

```
    """Same pick as preflight's `capacity_storage` for the transfer strategy:
    the lexicographically-first dir-type backup storage this NODE serves.
    Recomputed here rather than threaded through `preflight()`'s return dict,
    because preflight discards the name once it has used it for capacity."""
```

**`[601]`** `backend/proxploy/services/migrate.py:149` &middot; **47w → 47w** (0% cut) &middot; _contract_  
Keep what None means and the refusal to guess; tighten the phrasing.

<details><summary>before</summary>

```
The dir storage's filesystem root (`/storage`'s `path` field), the
    physical parent of its `dump/` directory. `None` if the storage wasn't
    found or carries no `path` (a real PVE dir storage always has one; a
    hand-built fixture that omits it is treated as "can't transfer", not
    guessed at).
```

</details>

**after**

```
    """The dir storage's filesystem root (`/storage`'s `path`), the physical
    parent of its `dump/` directory. `None` if the storage was not found or
    carries no `path`: a real PVE dir storage always has one, so a fixture that
    omits it is treated as "cannot transfer", not guessed at."""
```

**`[602]`** `backend/proxploy/services/migrate.py:196` &middot; **86w → 65w** (24% cut) &middot; _measurement-dump_  
Keep the one measured number and the conclusion; cut the retelling of why the note changed.

<details><summary>before</summary>

```
# Measured 47s on real hardware (2026-08-17, doc 12 check 7) against
# this estimate of 30. The note deliberately no longer says
# "network-bound": PVE reported the volume as being on shared storage
# and `vzmigrate` finished in ONE second, so the downtime was stopping
# and starting the guest, not moving it. On non-shared storage in a
# cluster the transfer does dominate, hence both halves below. The 30
# stands: one measurement is not a basis for a new constant, and the
# job reports the real number afterwards either way.
```

</details>

**after**

```
        # Measured 47s on real hardware against this estimate of 30, but PVE
        # had the volume on shared storage and `vzmigrate` finished in one
        # second, so that downtime was the guest stopping and starting, not
        # moving. On non-shared storage the transfer does dominate, hence both
        # halves below. The 30 stands: one measurement is not a new constant,
        # and the job reports the real number either way.
```

**`[603]`** `backend/proxploy/services/migrate.py:245` &middot; **53w → 41w** (23% cut) &middot; _contract_  
Keep how this differs from storage_for_content; the same-read aside is not needed.

<details><summary>before</summary>

```
Every active storage on `node` that can hold a container rootfs.

    `storage_for_content` answers "the first one", which is what the restore
    needs a default for; this is the whole set, so preflight can offer the
    choice and the route can refuse a name that is not in it. Same read, same
    `active` rule.
    
```

</details>

**after**

```
    """Every active storage on `node` that can hold a container rootfs.

    `storage_for_content` answers "the first one", which is the restore's
    default; this is the whole set, so preflight can offer the choice and the
    route can refuse a name outside it.
    """
```

**`[604]`** `backend/proxploy/services/migrate.py:265` &middot; **107w → 77w** (28% cut) &middot; _security_  
The monitoring-capability rule stays; the comparison to test_host and the restatement go.

<details><summary>before</summary>

```
Blocking, called in-request, like api/hosts.py::test_host's own probe.

    `app_row` and `target_host_id` are assumed already validated by the route
    (app exists, target host exists, target != source, target is connected).

    Every call this function makes (cluster_status, cluster_storage,
    cluster_resources, cluster_nextid, storages) is a READ, so it runs on
    the "monitoring" capability deliberately: a preview of a migration must
    not require the operator to have already configured lifecycle/backup
    tokens on both hosts just to see the estimate, and monitoring is the
    one capability every enrolled host is guaranteed to have. The actual
    `migrate.app` job below resolves lifecycle/backup separately, and only
    fails on their absence when it is actually about to use them.
    
```

</details>

**after**

```
    """Blocking, called in-request.

    `app_row` and `target_host_id` are assumed already validated by the route
    (app exists, target host exists, target != source, target is connected).

    Every call here is a READ, so it runs on the "monitoring" capability
    deliberately: previewing a migration must not require lifecycle/backup
    tokens on both hosts, and monitoring is the one capability every enrolled
    host has. The job resolves the others separately, and fails on their
    absence only when it is about to use them.
    """
```

**`[605]`** `backend/proxploy/services/migrate.py:291` &middot; **73w → 56w** (23% cut) &middot; _external-quirk_  
The read-only /etc/pve quirk and the False-only rule stay; the phrasing tightens.

<details><summary>before</summary>

```
# Quorum, before anything else: without it /etc/pve is read-only, so the
# restore or the native migrate cannot write a guest config at all, while
# /version and /cluster/resources answer perfectly and every other check
# here passes (doc 12 check 12). A blocker rather than a warning because the
# alternative is stopping the source and finding out afterwards. False only,
# never None: NULL means standalone or not yet polled, neither of which is
# quorum loss.
```

</details>

**after**

```
    # Quorum, before anything else: without it /etc/pve is read-only, so no
    # guest config can be written, while /version and /cluster/resources answer
    # perfectly and every other check here passes. A blocker rather than a
    # warning, because the alternative is stopping the source and finding out
    # afterwards. False only, never None: NULL means standalone or not yet
    # polled.
```

**`[606]`** `backend/proxploy/services/migrate.py:308` &middot; **27w → 20w** (26% cut) &middot; _redundant_  
The module docstring already argues this at length; one line suffices here.

<details><summary>before</summary>

```
# The live check above just PROVED cluster membership: un-deaden the
# column honestly now, rather than leaving it permanently stale
# (nothing else in the codebase ever writes it).
```

</details>

**after**

```
        # The live check above just PROVED cluster membership, so write the
        # column honestly now rather than leave it permanently stale.
```

**`[607]`** `backend/proxploy/services/migrate.py:349` &middot; **79w → 68w** (14% cut) &middot; _data-integrity_  
The staging-vs-rootfs distinction is the whole point; the doc check number is not.

<details><summary>before</summary>

```
# Where the restored ROOTFS lands, which is not where the archive is staged:
# `capacity_storage` above is the pool that holds the dump, and on a stock
# layout that is a dir store carrying no `rootdir` content at all. Checking
# only that one could read `capacity_ok: true` while the pool the disk
# actually needs is full (doc 12 check 7). Named here so an operator sees it
# before committing, and so the job restores where the preview said it would.
```

</details>

**after**

```
    # Where the restored ROOTFS lands, which is not where the archive is
    # staged: `capacity_storage` is the pool holding the dump, and on a stock
    # layout that is a dir store carrying no `rootdir` content at all, so
    # checking only it could read `capacity_ok: true` while the pool the disk
    # needs is full. Named so the operator sees it before committing and the
    # job restores where the preview said.
```

**`[608]`** `backend/proxploy/services/migrate.py:357` &middot; **50w → 49w** (2% cut) &middot; _surprising_  
Keep why an unusable name is reported rather than swapped, and the NFS example that makes it concrete.

<details><summary>before</summary>

```
# The operator's pick wins when it is one of the real candidates; otherwise
# the first candidate is the default. An unusable name is reported rather
# than quietly swapped, because silently migrating a guest onto a pool
# nobody chose is how it ended up on NFS when its source was local-lvm.
```

</details>

**after**

```
    # The operator's pick wins when it is one of the real candidates, otherwise
    # the first candidate is the default. An unusable name is reported rather
    # than quietly swapped: silently migrating a guest onto a pool nobody chose
    # is how one ended up on NFS when its source was local-lvm.
```

**`[609]`** `backend/proxploy/services/migrate.py:394` &middot; **55w → 43w** (22% cut) &middot; _external-quirk_  
The UI-migrated-CT quirk stays; the doc check number goes.

<details><summary>before</summary>

```
# The GUEST's node on the source side: a CT migrated in the Proxmox UI
# sits on a different node than its host row implies, and every stop and
# vzdump below is aimed at this value (doc 12 check 18). The target side
# is the host's node by definition, since that is where it is going.
```

</details>

**after**

```
        # The GUEST's node on the source side: a CT migrated in the Proxmox UI
        # sits on a different node than its host row implies, and every stop
        # and vzdump below aims at this value. The target side is the host's
        # node by definition.
```

**`[610]`** `backend/proxploy/services/migrate.py:423` &middot; **49w → 43w** (12% cut) &middot; _separator_  
Drop the task-number banner; the ponytail debt marker below it names a real ceiling and upgrade path and stays.

<details><summary>before</summary>

```
# --- migrate.app job handler (Task 15) --------------------------------------
# ponytail: 60s / 1s are module globals, not a settings knob: nobody has
# asked for a configurable health-check window yet, and a test overrides them
# with monkeypatch.setattr exactly like pvetask.py's own TASK_TIMEOUT_S/
# TASK_POLL_S. Promote to a Settings field if a real fleet ever needs longer.
```

</details>

**after**

```
# ponytail: 60s / 1s are module globals, not a settings knob: nobody has asked
# for a configurable health-check window yet, and a test overrides them the
# same way pvetask.py's TASK_TIMEOUT_S/TASK_POLL_S are overridden. Promote to
# a Settings field if a real fleet ever needs longer.
```

**`[611]`** `backend/proxploy/services/migrate.py:431` &middot; **136w → 93w** (32% cut) &middot; _surprising_  
The band table's reason survives; the blow-by-blow of the old bug shortens.

<details><summary>before</summary>

```
# migrate_app is several PVE tasks (and, for the transfer strategy, an SFTP
# hop) chained into one job. Each of pvetask.py's await_task calls brackets
# its own task with ctx.progress(start_pct) / ctx.progress(end_pct); left at
# the module default (10, 100) every phase would report itself as the WHOLE
# job, so vzdump finishing would hit 100 and then the SFTP transfer's real,
# honest climb would resume from ~10%, the bug this band table fixes. Every
# strategy's phases are given their own slice of 0-100 here so the number the
# job reports only ever goes up. The three strategies use different numbers
# of phases, so each gets its own row; all of them fold back into the same
# START_PCT band for the final "start the target guest" task, so that one
# call site doesn't need to know which strategy ran before it.
```

</details>

**after**

```
# migrate_app chains several PVE tasks (and for transfer an SFTP hop) into one
# job. Each await_task brackets its own task with ctx.progress(start_pct) /
# ctx.progress(end_pct); left at the module default (10, 100) every phase would
# report itself as the WHOLE job, so vzdump finishing would hit 100 and the
# SFTP transfer would resume from ~10%. Each strategy's phases get their own
# slice of 0-100 so the reported number only ever goes up, and all three fold
# back into START_PCT for the final start, so that call site does not need to
# know which strategy ran.
```

**`[612]`** `backend/proxploy/services/migrate.py:454` &middot; **183w → 123w** (33% cut) &middot; _contract_  
The fresh-preflight rule and the lazy backup-token rule stay; the report filenames and doc refs go.

<details><summary>before</summary>

```
Blocking: fresh in-handler preflight (never the route's stale one) +
    every client the chosen strategy needs, in one db session. Returns only
    plain values/client objects, no ORM instance escapes the closed session.

    Raises JobFailed for anything the route already should have prevented
    but that may have changed in the gap between "operator clicks migrate"
    and "this job actually runs" (doc 05 Interfaces note on Task 15). A
    missing lifecycle/backup token on either host is exactly this class of
    gap now: `client_for_host` raises `CapabilityNotConfigured` (naming the
    host and the capability) before any PVE call, caught the same way as
    every other resolution failure here and turned into one JobFailed line
    instead of a mid-job 403 (host-token-privileges-step-one-report.md, per-
    capability-tokens-plan.md §3 point 2).

    Non-cluster migration (shared_storage/transfer) genuinely needs TWO
    capabilities on top of needing two hosts: lifecycle for the stop/start
    calls, backup for vzdump/restore/storage cleanup. Cluster-native
    migration needs only lifecycle (PVE's own migrate call), so backup is
    resolved lazily, only for the strategies that actually use it -- an
    operator who only wants same-cluster migration must not be forced to
    configure a backup token they will never touch.
    
```

</details>

**after**

```
    """Blocking: fresh in-handler preflight (never the route's stale one) plus
    every client the strategy needs, in one db session. Returns plain values
    and client objects only, no ORM instance escapes the closed session.

    Raises JobFailed for anything the route should have prevented but that may
    have changed since the operator clicked migrate. A missing lifecycle or
    backup token is exactly that: `client_for_host` raises
    `CapabilityNotConfigured`, naming host and capability, before any PVE call,
    so it becomes one JobFailed line instead of a mid-job 403.

    Non-cluster migration needs lifecycle for stop/start AND backup for
    vzdump/restore/cleanup. Cluster-native needs only lifecycle, so backup is
    resolved lazily: an operator who only migrates inside a cluster must not be
    forced to configure a backup token they will never touch.
    """
```

**`[613]`** `backend/proxploy/services/migrate.py:512` &middot; **50w → 33w** (34% cut) &middot; _narration_  
Keep the no-ORM rule and why it is always computed; drop the appstore comparison.

<details><summary>before</summary>

```
# Plain strings only, never the ORM rows themselves: used solely by
# the transfer strategy's SFTP hop below, which needs the same
# host/fingerprint shape appstore.py's SSHExecutor.run_for_host call
# already relies on. Cheap to always compute: both rows are already
# loaded above for client_for_host, and the other two strategies
# simply ignore this key.
```

</details>

**after**

```
        # Plain strings only, never the ORM rows: used solely by the transfer
        # strategy's SFTP hop below. Cheap to always compute, both rows are
        # already loaded above, and the other strategies ignore this key.
```

**`[614]`** `backend/proxploy/services/migrate.py:537` &middot; **37w → 34w** (8% cut) &middot; _test-reference_  
State the invariant (read as module globals, overridable) without naming monkeypatch.

<details><summary>before</summary>

```
Poll target `cluster_resources()` until CT `ctid` reports running, or
    give up at `HEALTH_CHECK_DEADLINE_S`. Read as module globals (not bound
    into default-argument values) so a test can monkeypatch both down to
    near-zero instead of actually waiting a minute.
```

</details>

**after**

```
    """Poll target `cluster_resources()` until CT `ctid` reports running, or
    give up at `HEALTH_CHECK_DEADLINE_S`. Both are read as module globals, not
    bound into default-argument values, so either can be overridden without
    actually waiting a minute."""
```

**`[615]`** `backend/proxploy/services/migrate.py:563` &middot; **77w → 48w** (38% cut) &middot; _data-integrity_  
The never-raises rule stays; the two-path explanation compresses.

<details><summary>before</summary>

```
Best-effort delete of one vzdump/SFTP transfer scratch archive.

    Never raises: this runs on both the success path (the archive did its
    job, keeping it around would look like a real backup nobody asked for)
    and every failure path (the whole point is that a dead-mid-copy transfer
    doesn't leave orphaned dump files behind), a cleanup failure must not
    mask, replace, or block the real outcome of the migration itself, so it
    is logged and swallowed rather than raised.
    
```

</details>

**after**

```
    """Best-effort delete of one vzdump/SFTP transfer scratch archive.

    Never raises. It runs on the success path (the archive did its job) and on
    every failure path (so a transfer that died mid-copy leaves no orphans),
    and a cleanup failure must not mask or block the migration's real outcome.
    """
```

**`[616]`** `backend/proxploy/services/migrate.py:577` &middot; **54w → 36w** (33% cut) &middot; _surprising_  
Keep why progress is pinned; drop the cross-reference tour of the band table.

<details><summary>before</summary>

```
# Deleting a scratch archive is not forward progress on the
# migration itself: hold the job's reported percentage exactly
# where it already was rather than let await_task's own bracket
# jump it (its default end_pct is 100, which is the same class
# of bug this whole band table exists to fix, see migrate_app's
# STOP_PCT/CLUSTER_MIGRATE_PCT/etc comment above).
```

</details>

**after**

```
            # Deleting a scratch archive is not forward progress on the
            # migration itself: hold the job's reported percentage exactly
            # where it already was rather than let await_task's own bracket
            # jump it, since its default end_pct is 100.
```

**`[617]`** `backend/proxploy/services/migrate.py:592` &middot; **65w → 52w** (20% cut) &middot; _data-integrity_  
Failure ordering is the safety property and stays; the doc reference goes.

<details><summary>before</summary>

```
`migrate.app`, cluster-native migrate, shared-storage backup/restore,
    or (Task 16) vzdump + SFTP transfer + restore for hosts with neither.

    Failure ordering IS the safety property (doc 11 §2): every step before
    the target's health check can raise JobFailed and the source is still
    the only guest anyone has touched, stopped (if it was running) but
    never destroyed, and `apps.host_id`/`apps.ctid` are never written until
    AFTER that health check passes.
    
```

</details>

**after**

```
    """`migrate.app`: cluster-native migrate, shared-storage backup/restore, or
    vzdump + SFTP transfer + restore for hosts with neither.

    Failure ordering IS the safety property: every step before the target's
    health check can raise JobFailed with the source still the only guest
    touched, stopped but never destroyed, and `apps.host_id`/`apps.ctid` are
    never written until AFTER that check passes.
    """
```

**`[618]`** `backend/proxploy/services/migrate.py:625` &middot; **86w → 65w** (24% cut) &middot; _external-quirk_  
PVE's fallback to `local` and the failure it causes stay; the doc check number goes.

<details><summary>before</summary>

```
Where the restored rootfs lands on the target.

        Taken from this job's OWN preflight rather than recomputed, so the pool
        named in the preview is the pool the restore uses. Sending no storage at
        all lets PVE fall back to `local`, which on a stock layout is a dir
        store carrying no `rootdir` content, so the restore dies on "storage
        'local' does not support container directories": that was the whole
        failure on real hardware after the archive had already crossed the
        network (doc 12 check 7).
        
```

</details>

**after**

```
        """Where the restored rootfs lands on the target.

        Taken from this job's OWN preflight rather than recomputed, so the
        preview and the restore name the same pool. Sending no storage lets PVE
        fall back to `local`, which on a stock layout carries no `rootdir`
        content, so the restore dies on "storage 'local' does not support
        container directories" after the archive has already crossed the wire.
        """
```

**`[619]`** `backend/proxploy/services/migrate.py:648` &middot; **36w → 34w** (6% cut) &middot; _contract_  
Keep why the clock starts before the branch; drop the doc reference.

<details><summary>before</summary>

```
# Downtime clock: starts here regardless of branch below (doc 11 §2, 
# an already-stopped source still has its whole restore/start window
# counted, since the app is unavailable on either host until the target
# passes its health check).
```

</details>

**after**

```
    # Downtime clock: starts here regardless of the branch below. An
    # already-stopped source still has its whole restore/start window counted,
    # since the app is unavailable on either host until the target passes its
    # health check.
```

**`[620]`** `backend/proxploy/services/migrate.py:697` &middot; **67w → 45w** (33% cut) &middot; _external-quirk_  
The VM.Allocate reason stays; the doc check number and the _permission_detail aside go.

<details><summary>before</summary>

```
# LIFECYCLE, not backup, and the reason is doc 12 check 7: a restore to
# a ctid that does not exist yet CREATES a guest, so PVE checks
# VM.Allocate, which the Backup role deliberately does not carry. On
# real hardware the backup token got a bare "403 Permission check
# failed" here, naming no privilege, which is PVE's own message for
# this endpoint rather than anything _permission_detail can improve.
```

</details>

**after**

```
        # LIFECYCLE, not backup: a restore to a ctid that does not exist yet
        # CREATES a guest, so PVE checks VM.Allocate, which the Backup role
        # deliberately does not carry. On real hardware the backup token got a
        # bare "403 Permission check failed" here, naming no privilege.
```

**`[621]`** `backend/proxploy/services/migrate.py:799` &middot; **62w → 44w** (29% cut) &middot; _data-integrity_  
Keep which failures land here and why both archives are cleaned up.

<details><summary>before</summary>

```
# SSHHostKeyMismatch, LookupError (no ssh_key credential), a
# dropped connection mid-copy: all land here. The source vzdump
# archive exists on disk at this point; clean it up rather than
# leave it as an orphan. The destination file may or may not
# exist depending on how far the copy got: the delete call is a
# harmless no-op on real PVE either way (Path never existed).
```

</details>

**after**

```
            # SSHHostKeyMismatch, LookupError (no ssh_key), a dropped
            # connection mid-copy: all land here. The source archive exists on
            # disk by now, so clean it up rather than leave an orphan. The
            # destination file may or may not exist; the delete is a harmless
            # no-op either way.
```

**`[622]`** `backend/proxploy/services/migrate.py:827` &middot; **59w → 38w** (36% cut) &middot; _measurement-dump_  
Keep why both exception types must be caught; the 19 MB figure adds nothing.

<details><summary>before</summary>

```
# ProxmoxError as well as JobFailed: await_task raises JobFailed for a
# task that RAN and failed, but restore_guest itself raises
# ProxmoxError when PVE refuses the call outright. Catching only the
# first left both scratch archives on disk, 19 MB each on two hosts,
# the exact outcome the cleanup below exists to prevent (observed on
# real hardware, doc 12 check 7).
```

</details>

**after**

```
        # ProxmoxError as well as JobFailed: await_task raises JobFailed for a
        # task that RAN and failed, but restore_guest raises ProxmoxError when
        # PVE refuses the call outright. Catching only the first left both
        # scratch archives on disk on two hosts.
```

**`[623]`** `backend/proxploy/services/migrate.py:840` &middot; **96w → 59w** (39% cut) &middot; _redundant_  
The plumbing-not-backups point is already in the module docstring; the backup-client requirement must stay.

<details><summary>before</summary>

```
# Restore succeeded from the target's own copy of the archive: both
# scratch files (source vzdump output, target-side SFTP copy) were
# transfer plumbing, not real backups: remove them on both hosts so
# a migration never silently fills either one's storage.
# On the BACKUP clients, like every failure path above and like
# backupjobs.py::delete_backup's identical storage_delete_volume call:
# these are the tokens that wrote the archives, and a host that grants
# Datastore.AllocateSpace through the Backup role only would 403 the
# lifecycle token here. `_cleanup_volume` swallows that, so the wrong
# client leaves multi-GB dumps behind on both hosts and says nothing.
```

</details>

**after**

```
        # Both scratch files were transfer plumbing, not backups: remove them
        # on both hosts. On the BACKUP clients, like every failure path above:
        # these are the tokens that wrote the archives, and a host granting
        # Datastore.AllocateSpace through the Backup role only would 403 the
        # lifecycle token. `_cleanup_volume` swallows that, so the wrong client
        # leaves multi-GB dumps behind and says nothing.
```

**`[624]`** `backend/proxploy/services/migrate.py:877` &middot; **44w → 34w** (23% cut) &middot; _data-integrity_  
The repoint-only-after-healthy ordering stays; the DoD citation goes.

<details><summary>before</summary>

```
# MEASURED, not the preflight estimate: this is the DoD number (doc 10
# "accurate downtime shown"). Everything before this line ran with the
# source authoritative and the app row untouched; only past this point,
# with the target guest proven healthy, is it safe to repoint.
```

</details>

**after**

```
    # MEASURED, not the preflight estimate. Everything before this line ran
    # with the source authoritative and the app row untouched; only past this
    # point, with the target guest proven healthy, is it safe to repoint.
```

**`[625]`** `backend/proxploy/services/migrate.py:884` &middot; **67w → 45w** (33% cut) &middot; _contract_  
Keep why both hosts are woken; drop the restatement of what the app row now points at.

<details><summary>before</summary>

```
# Both ends changed: the target host has a CT the poller has never seen and
# the source host has one it will not see again. The app row now points at
# the target, and everything live on it is read from that host's snapshot,
# so without these the migrated app reads "unknown" for up to a poll
# interval and the source CT keeps being offered for adoption.
```

</details>

**after**

```
    # Both ends changed: the target has a CT the poller has never seen and the
    # source has one it will not see again. Without these the migrated app
    # reads "unknown" for up to a poll interval and the source CT keeps being
    # offered for adoption.
```


### 🟢 KEEP (18), unchanged

- **`[626]`** `67` &middot; _contract_ &middot; `# same PVE cluster: native migrate`
- **`[627]`** `68` &middot; _contract_ &middot; `# both hosts see one backup storage`
- **`[628]`** `69` &middot; _contract_ &middot; `# vzdump + SFTP stream + restore`
- **`[629]`** `78` &middot; _external-quirk_ &middot; `PVE reports `content` as a comma string ("backup,iso") in most shapes`
- **`[630]`** `163` &middot; _external-quirk_ &middot; `"local:backup/vzdump-lxc-150-....tar.zst" -> the filename tail, i.e.`
- **`[631]`** `171` &middot; _contract_ &middot; `-> (bytes, basis). Prefers a measured backup (real bytes actually`
- **`[632]`** `210` &middot; _contract_ &middot; `# backup+restore, or dump+copy+restore`
- **`[633]`** `233` &middot; _contract_ &middot; `None-safe: no storage chosen yet, or no transfer size, or the target`
- **`[634]`** `316` &middot; _contract_ &middot; `# single read, reused below`
- **`[635]`** `338` &middot; _external-quirk_ &middot; `# native migrate keeps the vmid`
- **`[636]`** `380` &middot; _data-integrity_ &middot; `# Both pools have to fit: the archive on the staging store, the disk on`
- **`[637]`** `447` &middot; _contract_ &middot; `# on_progress scales into this band, byte by byte`
- **`[638]`** `490` &middot; _security_ &middot; `# Health-check/status reads (_is_running, _wait_running): always`
- **`[639]`** `497` &middot; _contract_ &middot; `# Stop the source, start the target: every strategy does both.`
- **`[640]`** `708` &middot; _contract_ &middot; `# STRATEGY_TRANSFER, vzdump locally, SFTP the archive, restore`
- **`[641]`** `762` &middot; _contract_ &middot; `# Scales into TRANSFER_BYTES_PCT: vzdump above already reached`
- **`[642]`** `770` &middot; _concurrency_ &middot; `# Fresh session: the `_load` one that read `ssh` is already closed.`
- **`[643]`** `819` &middot; _external-quirk_ &middot; `# LIFECYCLE, same reason as the shared branch above: this creates a`

---

## `frontend/src/routes/hosts.tsx`

2,729 → 1,883 words, 31% cut. 6 delete, 34 shorten, 16 keep.


### 🔴 DELETE (6)

**`[644]`** `frontend/src/routes/hosts.tsx:300` &middot; 34w &middot; _redundant_  
Repeats the block directly above it; only the null source differs and the code shows that.

```
/* `pct == null` joins isError as unknown: the backend sends null when
            nothing was measured, so a degraded poll no longer draws a calm 0%
            gauge over a cluster that cannot even accept a write. */
```

**`[645]`** `frontend/src/routes/hosts.tsx:318` &middot; 40w &middot; _implementation-diary_  
Records where the tile used to live; the row it sits in already says what it is.

```
/* Throughput moved up here from a card of its own further down the
            page. It sits beside the three rings because it is the same kind
            of reading, cluster-wide right now, and it drew a whole card for
            two figures. */
```

**`[646]`** `frontend/src/routes/hosts.tsx:529` &middot; 10w &middot; _narration_  
Lists the four controls the four skeleton boxes obviously stand in for.

```
/* Node shell, the Proxmox link, the StatusPill, the actions menu. */
```

**`[647]`** `frontend/src/routes/hosts.tsx:585` &middot; 32w &middot; _implementation-diary_  
History of a dead-end link that has since been fixed; the code now points at a real route.

```
/* /settings/hosts was never a route, so this badge has always
               dead-ended; the `as never` cast is what let it type-check.
               Settings grew a section rail, so Hosts now has a real URL. */
```

**`[648]`** `frontend/src/routes/hosts.tsx:807` &middot; 45w &middot; _implementation-diary_  
Describes the dashed box that used to be here; the current code needs none of it.

```
// Was a dashed 200px box with the word "Loading…" in the middle of
// it, which is neither the size nor the shape of the list that
// replaced it, so the page jumped every time. GuestListSkeleton is
// the real list box with three rows in it.
```

**`[649]`** `frontend/src/routes/hosts.tsx:896` &middot; 11w &middot; _redundant_  
The JSDoc on HostEntryRedirect already says it redirects to the entry node.

```
// Still routed, still works: it redirects to the entry node above.
```


### 🟡 SHORTEN (34)

**`[650]`** `frontend/src/routes/hosts.tsx:13` &middot; **72w → 56w** (22% cut) &middot; _surprising_  
Keep why it is a class string and not a Button, trim the styling rationale.

<details><summary>before</summary>

```
// The two controls in a node's header: one opens a shell, one opens Proxmox.
// They sit side by side and have to read as a pair, and one of them is an <a>,
// which Button cannot render, so the shared thing is a class string. Not ghost
// either: these are transparent until pointed at, so they sit quietly in a
// header rather than stacking two filled boxes next to the node name.
```

</details>

**after**

```
// The two controls in a node's header: one opens a shell, one opens Proxmox.
// They read as a pair and one of them is an <a>, which Button cannot render,
// so the shared thing is a class string. Transparent until pointed at, so a
// header does not stack two filled boxes next to the node name.
```

**`[651]`** `frontend/src/routes/hosts.tsx:41` &middot; **28w → 18w** (36% cut) &middot; _surprising_  
Keep why the grid string is hoisted, cut the aside.

<details><summary>before</summary>

```
// Hoisted because the loading placeholder has to lay out in the SAME grid as
// the content it replaces; two copies of the string is one copy too many.
```

</details>

**after**

```
// Hoisted because the loading placeholder has to lay out in the SAME grid as
// the content it replaces.
```

**`[652]`** `frontend/src/routes/hosts.tsx:63` &middot; **54w → 48w** (11% cut) &middot; _data-integrity_  
Keep the group-by-cluster-name rule, cut the restatement around it.

<details><summary>before</summary>

```
/** Nodes that share a cluster, under one heading carrying that cluster's own
 *  health.
 *
 *  Grouped by cluster NAME rather than by host, and that is the point: two
 *  Hosts enrolled from the same cluster are two API endpoints into ONE
 *  cluster, so they collapse into a single group instead of drawing the same
 *  cluster twice. */
```

</details>

**after**

```
/** Nodes that share a cluster, under one heading carrying that cluster's own
 *  health. Grouped by cluster NAME, not by host: two Hosts enrolled from the
 *  same cluster are two API endpoints into ONE cluster, so they collapse into
 *  a single group instead of drawing the same cluster twice. */
```

**`[653]`** `frontend/src/routes/hosts.tsx:72` &middot; **48w → 40w** (17% cut) &middot; _external-quirk_  
Keep the quorum behaviour, drop the doc reference and the count of past occurrences.

<details><summary>before</summary>

```
// Every node connected is not the same as the cluster being usable: without
// quorum /etc/pve is read-only and every write fails while every read
// answers (doc 12 check 12). "all healthy" was the third place this read as
// fine on a cluster that could not accept an install.
```

</details>

**after**

```
  // Every node connected is not the same as the cluster being usable: without
  // quorum /etc/pve is read-only, so every write fails while every read
  // answers, and "all healthy" would read as fine on a cluster that cannot
  // accept an install.
```

**`[654]`** `frontend/src/routes/hosts.tsx:100` &middot; **69w → 46w** (33% cut) &middot; _surprising_  
Keep the no-defined-order reason and the Map insertion-order fact, trim the wording.

<details><summary>before</summary>

```
/** Grouped AND sorted, because /cluster/nodes answers in no defined order:
 *  unsorted, the cards were laid out in whatever order the last poll happened
 *  to write, so they reshuffled under the operator on every 30s refetch.
 *
 *  Sorting the rows first is enough for the nodes: a Map keeps insertion
 *  order, so each group and the standalone list inherit it, and only the
 *  cluster headings still need sorting of their own. */
```

</details>

**after**

```
/** Grouped AND sorted, because /cluster/nodes answers in no defined order:
 *  unsorted, the cards reshuffled under the operator on every 30s refetch.
 *  Sorting the rows first is enough, since a Map keeps insertion order and
 *  each group inherits it; only the cluster headings need their own sort. */
```

**`[655]`** `frontend/src/routes/hosts.tsx:122` &middot; **85w → 60w** (29% cut) &middot; _security_  
Keep the 403 shape and the backend-stays-authority rule, trim the argument.

<details><summary>before</summary>

```
/** "Add host" where the hosts are, not only buried in Settings.
 *
 *  POST /hosts answers 403 {"error":"entitlement_required","feature":
 *  "hosts.multi"} once one host exists. Saying so BEFORE the form is filled in
 *  is the whole reason this checks the entitlement itself: a raw 403 at the
 *  end of a completed form is the worst possible place to learn it. When the
 *  entitlement fetch itself failed we cannot honestly claim either way, so the
 *  form opens and the backend stays the authority (HostForm renders that 403
 *  in words too). */
```

</details>

**after**

```
/** "Add host" where the hosts are, not only buried in Settings.
 *
 *  POST /hosts answers 403 {"error":"entitlement_required","feature":
 *  "hosts.multi"} once one host exists, and a raw 403 at the end of a filled
 *  form is the worst place to learn it. When the entitlement fetch itself
 *  failed we cannot claim either way, so the form opens and the backend stays
 *  the authority. */
```

**`[656]`** `frontend/src/routes/hosts.tsx:189` &middot; **96w → 56w** (42% cut) &middot; _data-integrity_  
Keep the 1 hour minimum and the never-a-sum rule, trim the surrounding prose.

<details><summary>before</summary>

```
// History for the Network tile's spark. An hour is the SHORTEST window
// /network/throughput serves (api/network.py validates 1 <= hours <= 48),
// so the tile's footer reads the window off the timestamps it actually got
// rather than claiming one.
//
// combineThroughput, never a sum: two hosts enrolled into one cluster each
// record that whole cluster's traffic, so adding the rows reports it twice.
// The cluster each host belongs to comes off `nodes`, which this page has
// already fetched, so this costs one request and no extra state. The live
// figures beside the spark stay /cluster/summary's, which is deduped
// server-side already.
```

</details>

**after**

```
  // History for the Network tile's spark. An hour is the SHORTEST window
  // /network/throughput serves (1 <= hours <= 48), so the tile's footer reads
  // the window off the timestamps it got rather than claiming one.
  //
  // combineThroughput, never a sum: two hosts enrolled into one cluster each
  // record that whole cluster's traffic, so adding the rows reports it
  // twice.
```

**`[657]`** `frontend/src/routes/hosts.tsx:205` &middot; **42w → 27w** (36% cut) &middot; _narration_  
Keep why they are consts, drop the defence of not extracting components.

<details><summary>before</summary>

```
/* The two inventories, built once and placed by the branch below. They are
     consts rather than two components because they close over the two
     queries above and take nothing else; a component here would be two props
     of ceremony for one caller. */
```

</details>

**after**

```
  /* The two inventories, built once and placed by the branch below. Consts
     rather than components because they close over the two queries above and
     take nothing else. */
```

**`[658]`** `frontend/src/routes/hosts.tsx:211` &middot; **71w → 40w** (44% cut) &middot; _implementation-diary_  
Keep the scope of the section and the no-cap rule, cut the story of the old eight.

<details><summary>before</summary>

```
/* One icon per app with its status, and nothing else. The view
          switch and Update all moved to the Apps page: this section is a
          glance at what is installed, not the place to operate on it.

          Every app, with no cap. It used to show the first eight in
          whatever order /apps answered, which on a cluster meant a missing
          app could equally be stopped, gone, or simply the ninth. */
```

</details>

**after**

```
      {/* One icon per app with its status, and nothing else: this section is a
          glance at what is installed, not the place to operate on it. Every
          app, with no cap, so a missing app cannot also mean "the ninth". */}
```

**`[659]`** `frontend/src/routes/hosts.tsx:236` &middot; **56w → 34w** (39% cut) &middot; _narration_  
Keep the shared-baseline reason, cut the description of the alternative tried.

<details><summary>before</summary>

```
/* Heading outside the panel, matching Apps beside it: over there the
     heading row also carries the view switch and Update all, so it has to sit
     outside. Putting this one inside its box made the two columns read as
     different kinds of thing. The same flex wrapper keeps both headings on one
     baseline across the row. */
```

</details>

**after**

```
  /* Heading outside the panel, matching Apps beside it, whose heading row has
     to sit outside because it carries the view switch. The same flex wrapper
     keeps both headings on one baseline across the row. */
```

**`[660]`** `frontend/src/routes/hosts.tsx:243` &middot; **55w → 25w** (55% cut) &middot; _implementation-diary_  
Keep the no-card-wrapper fact, cut the old-table history.

<details><summary>before</summary>

```
/* The same icon grid the Apps column draws, grouped the same way.
          It was a Name/Node/Status table showing the first four VMs, which
          made the two inventories read as two different kinds of thing and
          hid the fifth VM entirely. The grid carries its own panel, so
          there is no card wrapper here any more. */
```

</details>

**after**

```
      {/* The same icon grid the Apps column draws, grouped the same way. The
          grid carries its own panel, so there is no card wrapper here. */}
```

**`[661]`** `frontend/src/routes/hosts.tsx:282` &middot; **67w → 53w** (21% cut) &middot; _surprising_  
Keep why a pending fetch must not draw a 0% ring, trim the retelling.

<details><summary>before</summary>

```
/* The pending case has exactly the same problem the error case does,
            one line down: `pct={summary?.cpu.pct ?? 0}` is 0 until the fetch
            returns, so all three gauges drew a confident empty ring, and the
            three subs under them read "unknown", for a cluster that was simply
            not measured yet. `unknown` is the wrong tool for it, that word is
            an answer, and there is no answer yet. */
```

</details>

**after**

```
        {/* The pending case has the same problem the error case does:
            `pct={summary?.cpu.pct ?? 0}` is 0 until the fetch returns, so all
            three gauges drew a confident empty ring over a cluster that was
            simply not measured yet. `unknown` is wrong here too: that word is
            an answer, and there is no answer yet. */}
```

**`[662]`** `frontend/src/routes/hosts.tsx:322` &middot; **37w → 25w** (32% cut) &middot; _contract_  
Keep why the prop is omitted, cut the elaboration.

<details><summary>before</summary>

```
/* No `scope`: every other reading in this row is the whole fleet
            too, so naming it here would state the obvious. The prop is for a
            per-node caller, which IS a departure from what the row means. */
```

</details>

**after**

```
        {/* No `scope`: every reading in this row is the whole fleet, so
            naming it would state the obvious. The prop is for a per-node
            caller. */}
```

**`[663]`** `frontend/src/routes/hosts.tsx:365` &middot; **243w → 133w** (45% cut) &middot; _external-quirk_  
Keep the height:auto override, the no-cap rule and the 16rem derivation, cut the design essay.

<details><summary>before</summary>

```
/* Apps and Virtual machines side by side: they are the two inventories
          this page exists to show, and an operator comparing them wants both
          in view at once rather than one scrolled past the other. The split
          between them is draggable now, because which of the two deserves the
          width is a fact about the fleet rather than about the page: a node
          running twenty apps and one VM wants the bar nowhere near the middle.

          The group draws no border, only the bar. Each inventory already
          carries its own panel (IconGrid's PANEL), so a box around the pair
          would be a third edge saying nothing the two inside it do not.

          `height: auto` overrides the library's inline `height: 100%`, which
          would otherwise resolve against this page's own auto height and is
          not worth relying on. NEITHER GRID CAPS ITS ROWS: AppIconGrid and
          VmIconGrid render every app and every VM the fleet has, grouped by
          node, so any fixed height here is a guess that clips the twenty-first
          app the day somebody installs it. The panels divide width; height
          stays whatever the taller inventory needs.

          minSize is 16rem rather than a percentage: the grid inside wants a
          10rem column plus the panel's padding, and that is a number of
          pixels, not a fraction of a window nobody has measured.

          They stack below lg, where half a row is too narrow for either, and
          where a draggable split would divide height instead of width. */
```

</details>

**after**

```
      {/* Apps and Virtual machines side by side: an operator comparing the two
          inventories wants both in view at once, and the split is draggable
          because which one deserves the width is a fact about the fleet. No
          border on the group, only the bar: each inventory carries its own
          panel (IconGrid's PANEL).

          `height: auto` overrides the library's inline `height: 100%`, which
          would otherwise resolve against this page's own auto height. NEITHER
          GRID CAPS ITS ROWS, so any fixed height here clips the twenty-first
          app the day somebody installs it: the panels divide width, height
          stays whatever the taller inventory needs.

          minSize is 16rem, not a percentage: the grid inside wants a 10rem
          column plus the panel's padding, which is pixels. They stack below
          lg, where half a row is too narrow for either. */}
```

**`[664]`** `frontend/src/routes/hosts.tsx:407` &middot; **47w → 42w** (11% cut) &middot; _contract_  
Keep the field semantics, drop the doc section pointer.

<details><summary>before</summary>

```
// Minimal slice of GET /hosts/{id}: the opt-in flag and the address the
// "Open Proxmox web UI" button links to. The fleet-overview fields (status,
// uptime, etc.) already come from `node`. node_power_missing (doc 08 §2/§9)
// feeds HostActionsMenu's Reboot/Power off items, null/undefined meaning
// "not probed since this existed", not "granted".
```

</details>

**after**

```
// Minimal slice of GET /hosts/{id}: the opt-in flag and the address the
// "Open Proxmox web UI" button links to; the fleet-overview fields come from
// `node`. node_power_missing feeds HostActionsMenu's Reboot and Power off
// items, null/undefined meaning "not probed since this existed", not
// "granted".
```

**`[665]`** `frontend/src/routes/hosts.tsx:432` &middot; **96w → 66w** (31% cut) &middot; _surprising_  
Keep the never-grey rule and the two gates, cut the argument against tooltips.

<details><summary>before</summary>

```
/** Opens the node shell in a window of its own, beside the Proxmox web UI
 *  link, and NEVER goes grey.
 *
 *  This replaces a disabled button with a tooltip. Two independent gates could
 *  disable it (the terminal.node entitlement and the per-host opt-in from
 *  doc 08 §9), and a tooltip is invisible on touch and easy to miss anywhere
 *  else, so the honest reading of a greyed control was "this feature is
 *  broken". The control now always works; when a gate is shut it says which
 *  one, and where to open it, instead of opening a dead window. */
```

</details>

**after**

```
/** Opens the node shell in a window of its own and NEVER goes grey.
 *
 *  Two independent gates could disable it (the terminal.node entitlement and
 *  the per-host opt-in), and a tooltip on a greyed control is invisible on
 *  touch, so the honest reading of it was "this feature is broken". It always
 *  works; when a gate is shut it says which one, and where to open it. */
```

**`[666]`** `frontend/src/routes/hosts.tsx:461` &middot; **56w → 44w** (21% cut) &middot; _surprising_  
Keep the shared window naming and the second-click behaviour, trim the framing.

<details><summary>before</summary>

```
// A console wants its own window rather than a tab: it is a working
// surface you keep beside the page, not a place you navigate to.
// Shared with the VM and app consoles (lib/console-window.ts), which
// is what makes the window naming consistent enough that a second
// click focuses the first window instead of opening another session.
```

</details>

**after**

```
        // A console wants its own window rather than a tab: it is a working
        // surface you keep beside the page. Shared with the VM and app
        // consoles (lib/console-window.ts), which is what makes a second click
        // focus the first window instead of opening another session.
```

**`[667]`** `frontend/src/routes/hosts.tsx:473` &middot; **55w → 46w** (16% cut) &middot; _data-integrity_  
Keep the (host, node) keying rule and why, trim the retelling.

<details><summary>before</summary>

```
/** (host id, node row, host detail) for whichever of the three host routes is
 *  mounted. `node` is absent on the legacy /hosts/$hostId route, which
 *  resolves to the host's entry node. Keying the lookup on (host, node) is the
 *  fix for a host with several nodes: `nodes.find(n => n.host_id === id)` used
 *  to return whichever one came first. */
```

</details>

**after**

```
/** (host id, node row, host detail) for whichever of the three host routes is
 *  mounted. `node` is absent on the legacy /hosts/$hostId route, which
 *  resolves to the entry node. Keyed on (host, node): on a host with several
 *  nodes, `nodes.find(n => n.host_id === id)` returns whichever came first. */
```

**`[668]`** `frontend/src/routes/hosts.tsx:491` &middot; **43w → 34w** (21% cut) &middot; _surprising_  
Keep the cold-load versus missing distinction, drop the pointer.

<details><summary>before</summary>

```
// Both lookups are undefined until their query lands, so "no node and no
// host" is true on every cold navigation to this URL before it is true of
// any missing node. Callers need to tell those two apart, see the top of
// NodeDetailPage.
```

</details>

**after**

```
  // Both lookups are undefined until their query lands, so "no node and no
  // host" is true on every cold navigation before it is true of any missing
  // node. Callers need to tell those apart.
```

**`[669]`** `frontend/src/routes/hosts.tsx:504` &middot; **28w → 21w** (25% cut) &middot; _contract_  
Keep what the frame is, cut the comparison to sibling pages.

<details><summary>before</summary>

```
/** The host page's frame: who this machine is, where to open it, and the
 *  tabs. The body is a routed child, matching the app and VM detail pages. */
```

</details>

**after**

```
/** The host page's frame: who this machine is, where to open it, and the
 *  tabs. The body is a routed child. */
```

**`[670]`** `frontend/src/routes/hosts.tsx:508` &middot; **38w → 34w** (11% cut) &middot; _data-integrity_  
Keep what {} and undefined mean for the count, trim the wording.

<details><summary>before</summary>

```
// Capabilities whose token is short of a privilege its role now carries, or
// whose token could not be read at all (null, "could not tell"). {} is the
// clean case and undefined means never probed; both count as zero.
```

</details>

**after**

```
  // Capabilities whose token is short of a privilege its role now carries, or
  // whose token could not be read at all. {} is the clean case and undefined
  // means never probed; both count as zero.
```

**`[671]`** `frontend/src/routes/hosts.tsx:512` &middot; **94w → 55w** (41% cut) &middot; _implementation-diary_  
Keep the reason for the early return and its effect on the Outlet, cut the diary.

<details><summary>before</summary>

```
// Before this check, a cold load of /hosts/1/pve showed "Node not found, it
// may have been removed" for as long as /nodes took to answer, and then the
// node appeared. Of the four answers, that was the page picking the most
// alarming one while it still had none.
//
// Returning early also keeps the Outlet from mounting, so NodeOverview and
// NodeHardware, which both bail to `null` on the same missing lookups, do
// not need a placeholder of their own; the frame is the whole page until
// there is a node to hang a body on.
```

</details>

**after**

```
  // Without this check, a cold load of /hosts/1/pve showed "Node not found,
  // it may have been removed" for as long as /nodes took to answer: the page
  // picking the most alarming answer while it still had none.
  //
  // Returning early also keeps the Outlet from mounting, so NodeOverview and
  // NodeHardware need no placeholder of their own.
```

**`[672]`** `frontend/src/routes/hosts.tsx:560` &middot; **36w → 30w** (17% cut) &middot; _security_  
Keep the entry-node shell ticket rule, trim the wording.

<details><summary>before</summary>

```
/* Entry node only: a shell ticket is minted for the host's own
              node, so offering it under any other node of the cluster would
              open a shell on a different box than the page is showing. */
```

</details>

**after**

```
          {/* Entry node only: a shell ticket is minted for the host's own
              node, so offering it elsewhere would open a shell on a different
              box than the page is showing. */}
```

**`[673]`** `frontend/src/routes/hosts.tsx:575` &middot; **42w → 38w** (10% cut) &middot; _external-quirk_  
Keep the reads-work-writes-fail quirk, drop the doc reference.

<details><summary>before</summary>

```
/* A node without quorum answers /version and /cluster/resources
              perfectly and refuses every WRITE, so "Connected" on its own is a
              lie an operator acts on (doc 12 check 12). Sits beside the status
              rather than replacing it, because reads really do work. */
```

</details>

**after**

```
          {/* A node without quorum answers /version and /cluster/resources
              perfectly and refuses every WRITE, so "Connected" on its own is a
              lie an operator acts on. Sits beside the status rather than
              replacing it, because reads really do work. */}
```

**`[674]`** `frontend/src/routes/hosts.tsx:579` &middot; **42w → 36w** (14% cut) &middot; _external-quirk_  
Keep the drift and the 403 it causes, drop the dated example privileges.

<details><summary>before</summary>

```
/* Privilege drift, shown WITHOUT anyone pressing Test connection: a
              role gains privileges over time (SDN.Use and VM.Config.HWType both
              landed on 2026-08-18) and a token generated earlier fails with a
              403 partway through a job. The poll loop refreshes this every half
              hour. */
```

</details>

**after**

```
          {/* Privilege drift, shown WITHOUT anyone pressing Test connection: a
              role gains privileges over time and a token generated earlier
              then fails with a 403 partway through a job. The poll loop
              refreshes this every half hour. */}
```

**`[675]`** `frontend/src/routes/hosts.tsx:605` &middot; **37w → 26w** (30% cut) &middot; _contract_  
Keep why both lookups must resolve, trim the wording.

<details><summary>before</summary>

```
/* Node-scoped (Reboot/Power off target THIS node) and host-scoped
              (Edit changes the Host record, shared across every node of its
              cluster) both live behind one trigger, so both need to be
              resolved before it can render at all. */
```

</details>

**after**

```
          {/* Node-scoped (Reboot/Power off target THIS node) and host-scoped
              (Edit changes the Host record) both live behind one trigger, so
              both must resolve before it can render. */}
```

**`[676]`** `frontend/src/routes/hosts.tsx:626` &middot; **34w → 31w** (9% cut) &middot; _surprising_  
Keep why the inline prop exists, trim the wording.

<details><summary>before</summary>

```
/* The legacy /hosts/$hostId route has no routed children to fill an
          Outlet, and it renders this page while its redirect resolves; giving
          it the Overview inline keeps that moment from being a blank frame. */
```

</details>

**after**

```
      {/* The legacy /hosts/$hostId route has no routed children to fill an
          Outlet and renders this page while its redirect resolves; the inline
          Overview keeps that moment from being a blank frame. */}
```

**`[677]`** `frontend/src/routes/hosts.tsx:634` &middot; **47w → 37w** (21% cut) &middot; _data-integrity_  
Keep which node owns the series and the shell ticket, trim the wording.

<details><summary>before</summary>

```
/** Charts and the node shell belong to the entry node: the `host:<id>` metric
 *  series is recorded there and the shell ticket is minted for it. Both were
 *  simply absent on every other node of a cluster, which reads as a missing
 *  feature rather than a deliberate one. */
```

</details>

**after**

```
/** Charts and the node shell belong to the entry node: the `host:<id>` series
 *  is recorded there and the shell ticket is minted for it. Absent elsewhere,
 *  they read as a missing feature rather than a deliberate one. */
```

**`[678]`** `frontend/src/routes/hosts.tsx:659` &middot; **152w → 79w** (48% cut) &middot; _buried-invariant_  
Keep the must-hold rule and the state machine, cut the history of what it replaces.

<details><summary>before</summary>

```
/** What to draw for "Guests on this host", derived from BOTH the apps and
 *  VMs queries at once.
 *
 *  This replaces a single `QueryState query={nodeAppsQuery}` that decided
 *  loading/empty/error from the apps query alone and folded `vms` in only
 *  once apps had already succeeded and come back non-empty, so an
 *  apps-empty node (a fresh install with real VMs and zero adopted apps) hid
 *  its VMs behind "No guests on this node", and an apps-erroring node hid
 *  them behind "Guests not readable". The one behaviour that must hold: if
 *  either list has rows, those rows render. So: pending if either query is
 *  still pending; a hard error only when BOTH failed (there is then truly
 *  nothing to show); otherwise render whatever rows the succeeding side(s)
 *  have, empty only when that combined count is zero, and a partial-failure
 *  note, not a swallowed error, when exactly one side failed but the other
 *  still has something to show. */
```

</details>

**after**

```
/** What to draw for "Guests on this host", derived from BOTH the apps and
 *  VMs queries at once.
 *
 *  The one behaviour that must hold: if either list has rows, those rows
 *  render. Pending if either query is still pending; a hard error only when
 *  BOTH failed; otherwise whatever rows the succeeding side has, empty only
 *  when that combined count is zero, and a partial-failure note, not a
 *  swallowed error, when one side failed and the other still has rows. */
```

**`[679]`** `frontend/src/routes/hosts.tsx:728` &middot; **42w → 34w** (19% cut) &middot; _contract_  
Keep why the percentage series is charted, trim the wording.

<details><summary>before</summary>

```
// mem_pct, not mem_bytes: the poller records both for a host, and charting
// the percentage puts all three of these on one 0..100 scale so they can be
// read side by side. The absolute figures are one row up, in the KV grid.
```

</details>

**after**

```
  // mem_pct, not mem_bytes: charting the percentage puts all three of these
  // on one 0..100 scale so they can be read side by side. The absolute figures
  // are one row up, in the KV grid.
```

**`[680]`** `frontend/src/routes/hosts.tsx:749` &middot; **67w → 55w** (18% cut) &middot; _measurement-dump_  
Keep the rule and the one viewport height that pins it, cut the rest.

<details><summary>before</summary>

```
/* The rail is dense reference material, not something worth pinning
            at the cost of reachability: with /status answering it runs to
            roughly 700px, and lg:top-16 alone left its bottom rows (Boot,
            part of Memory & storage) permanently below the fold on any
            viewport under ~765px tall (a 1366x768 laptop among them),
            comfortably inside `lg`. max-h + overflow-y-auto trades that for a
            nested scrollbar, which can always reach the bottom. */
```

</details>

**after**

```
        {/* The rail is dense reference material, not worth pinning at the
            cost of reachability: with /status answering it runs to roughly
            700px, and lg:top-16 alone left its bottom rows below the fold on
            any viewport under ~765px tall, comfortably inside `lg`. max-h +
            overflow-y-auto trades that for a nested scrollbar, which can
            always reach the bottom. */}
```

**`[681]`** `frontend/src/routes/hosts.tsx:761` &middot; **31w → 27w** (13% cut) &middot; _data-integrity_  
Keep that the series belongs to the entry node, trim the wording.

<details><summary>before</summary>

```
/* Entry node only: the `host:<id>` metric series is recorded from
            the node Proxploy connects through, so drawing it under any other
            node of the cluster would be charting a different machine. */
```

</details>

**after**

```
        {/* Entry node only: the `host:<id>` series is recorded from the node
            Proxploy connects through, so drawing it under any other node would
            be charting a different machine. */}
```

**`[682]`** `frontend/src/routes/hosts.tsx:766` &middot; **114w → 68w** (40% cut) &middot; _measurement-dump_  
Keep the container-not-viewport rule and the ~200px it turns on, cut the worked widths.

<details><summary>before</summary>

```
/* Each chart owns its range: "is the CPU spiking now" and "did
               storage creep all week" are different questions.
               @container/@3xl, not lg: a chart card needs roughly 200px of
               inner width to fit its non-wrapping 30m/1h/12h/24h range group,
               and this RIGHT COLUMN, not the viewport, is what decides
               that width. The 290px rail plus its gap can hold the column
               under 200px well past `lg` (~91px of card width at a 1024px
               viewport, versus ~194px before the rail existed), which is
               exactly what a viewport-keyed `lg:grid-cols-3` missed. @3xl
               (768px of container width) is the narrowest container step
               that still clears ~200px per card once p-5 padding, borders
               and gap-4 gutters come out of it. */
```

</details>

**after**

```
            /* Each chart owns its range: "is the CPU spiking now" and "did
               storage creep all week" are different questions.
               @container/@3xl, not lg: a chart card needs roughly 200px of
               inner width for its non-wrapping range group, and this RIGHT
               COLUMN, not the viewport, decides that width. The 290px rail
               plus its gap can hold the column under 200px well past `lg`,
               which is what a viewport-keyed `lg:grid-cols-3` missed. */
```

**`[683]`** `frontend/src/routes/hosts.tsx:843` &middot; **61w → 47w** (23% cut) &middot; _compatibility_  
Keep why the legacy route survives and renders inline, trim the wording.

<details><summary>before</summary>

```
/** /hosts/$hostId, kept alive for every link minted before node detail grew
 *  its node segment (and for anything that only knows a host id).
 *
 *  It resolves to the host's ENTRY node, the one Proxploy connects through,
 *  and renders the same page meanwhile: a redirect that first showed a blank
 *  screen would be a regression for the standalone host this used to serve. */
```

</details>

**after**

```
/** /hosts/$hostId, kept alive for every link minted before node detail grew
 *  its node segment. It resolves to the host's ENTRY node and renders the same
 *  page meanwhile: a redirect that first showed a blank screen would be a
 *  regression for the standalone host this used to serve. */
```


### 🟢 KEEP (16), unchanged

- **`[684]`** `52` &middot; _contract_ &middot; `/** Exported for routes/network.tsx, which needs the same cluster lookup to`
- **`[685]`** `81` &middot; _surprising_ &middot; `/* The cluster's name alone is not self-describing: "lab-cluster" as a`
- **`[686]`** `135` &middot; _surprising_ &middot; `// ent.data != null covers the pending window as well as the error one:`
- **`[687]`** `220` &middot; _compatibility_ &middot; `/* as never: route typing workaround, see router.tsx */`
- **`[688]`** `250` &middot; _compatibility_ &middot; `/* as never: route typing workaround, see router.tsx */`
- **`[689]`** `297` &middot; _surprising_ &middot; `/* summaryQuery.isError -> unknown: a failed /cluster/summary must not`
- **`[690]`** `350` &middot; _narration_ &middot; `/* No heading here on purpose: each card already says`
- **`[691]`** `415` &middot; _data-integrity_ &middot; `// False ONLY when PVE reported its cluster non-quorate. Null/undefined is a`
- **`[692]`** `419` &middot; _data-integrity_ &middot; `// {capability: [missing privilege]}, {} when clean, undefined/null when never`
- **`[693]`** `488` &middot; _contract_ &middot; `// The page needs to NAME the entry node, not just know it is not this one.`
- **`[694]`** `567` &middot; _security_ &middot; `// rel="noopener": without it the opened page can steer this one`
- **`[695]`** `697` &middot; _surprising_ &middot; `// The failed side might genuinely have guests we simply could not read;`
- **`[696]`** `746` &middot; _surprising_ &middot; `/* minmax(0,1fr), not 1fr: it lets the track shrink below the charts'`
- **`[697]`** `788` &middot; _data-integrity_ &middot; `/* Already recorded every cycle by the poller (`disk_pct`), and`
- **`[698]`** `800` &middot; _data-integrity_ &middot; `/* "on this host", not "on this node": neither apps nor vms records`
- **`[699]`** `866` &middot; _compatibility_ &middot; `// Route objects, imported by router.tsx (settings.tsx precedent). shellRoute`

---

## `backend/proxploy/services/catalog.py`

2,509 → 2,118 words, 16% cut. 0 delete, 22 shorten, 16 keep.


### 🟡 SHORTEN (22)

**`[700]`** `backend/proxploy/services/catalog.py:1` &middot; **174w → 161w** (7% cut) &middot; _contract_  
Keeps the three phases and the hard 2-call ceiling; drops the plan file reference and the prose around each phase.

<details><summary>before</summary>

```
CatalogSource: discover the full community-scripts/ProxmoxVE corpus from
the repo's own directory layout, fetch a ct/+install script pair lazily (not
during discovery), parse resource defaults, classify feasibility, upsert into
`catalog_entries` (catalog expansion plan,
.superpowers/sdd/app-store-catalog-plan.md).

Three phases, each with a distinct cost profile:

1. `run_discovery` - exactly 2 `api.github.com` calls (`head_sha` +
   `discover_tree`'s tree listing), FLAT regardless of catalog size. Writes a
   skeleton row (slug, entry_type, category, script_path) for every entry the
   tree contains; never fetches a script body. This is the hard ceiling: no
   function in this module may add a third per-refresh `api.github.com` call,
   let alone a per-slug one (584 of those blows the 60/hr budget in a single
   refresh).
2. `ensure_classified` - one ct/ entry's script pair, fetched from
   `raw.githubusercontent.com` (a different host, not subject to the GitHub
   API rate limit) the moment a card is opened or an install starts. Never
   called from `run_discovery`.
3. `classify_many` - the low-priority background pass that walks whatever
   `ensure_classified` hasn't reached yet, bounded concurrency, run as its own
   job AFTER a refresh already returned, so it never blocks first paint.
```

</details>

**after**

```
"""CatalogSource: discover the full community-scripts/ProxmoxVE corpus from
the repo's own directory layout, fetch a ct/+install script pair lazily (not
during discovery), parse resource defaults, classify feasibility, upsert into
`catalog_entries`.

Three phases, each with a distinct cost profile:

1. `run_discovery` - exactly 2 `api.github.com` calls (`head_sha` +
   `discover_tree`), FLAT regardless of catalog size. Writes a skeleton row
   for every entry in the tree and never fetches a script body. This is the
   hard ceiling: no function here may add a third per-refresh
   `api.github.com` call, let alone a per-slug one (584 of those blows the
   60/hr budget in a single refresh).
2. `ensure_classified` - one ct/ entry's script pair from
   `raw.githubusercontent.com` (a different host, not subject to the GitHub
   API rate limit) the moment a card is opened or an install starts. Never
   called from `run_discovery`.
3. `classify_many` - the low-priority background pass over whatever
   `ensure_classified` hasn't reached yet, bounded concurrency, run as its own
   job AFTER a refresh already returned, so it never blocks first paint.
"""
```

**`[701]`** `backend/proxploy/services/catalog.py:43` &middot; **160w → 120w** (25% cut) &middot; _external-quirk_  
Keeps the dual-shape upstream quirk and the detect-dynamically rule; drops the investigation and decision numbering.

<details><summary>before</summary>

```
# `dockge`, `dokploy`, `komodo`, `coolify` (investigation §2), and confirmed
# live during this plan's own verification, `runtipi` too: each has BOTH a
# standalone `ct/<slug>.sh` full-LXC installer and a `tools/addon/<slug>.sh`
# "install into an existing container" script under the SAME slug. Decision
# 4: show only the standalone installer in the Store. Directory-based
# discovery already gives the ct/ row the plain slug; an addon row with the
# same slug would collide with it in catalog_entries.slug (globally unique)
# if left alone.
#
# Detected dynamically, NOT a fixed allowlist: `runtipi` was not one of the
# four names the investigation's snapshot found, and a hardcoded set would
# have silently let its addon row collide with and shadow the ct row (an
# addon can never win a slug the repo also uses for a real standalone LXC
# installer). Whatever ct/ slugs a given tree actually has decides which
# addon rows need disambiguating, so this keeps working as the upstream
# corpus grows without needing a code change for the next one.
```

</details>

**after**

```
# `dockge`, `dokploy`, `komodo`, `coolify` and `runtipi` each have BOTH a
# standalone `ct/<slug>.sh` full-LXC installer and a `tools/addon/<slug>.sh`
# "install into an existing container" script under the SAME slug. Only the
# standalone installer is shown in the Store, and directory-based discovery
# already gives the ct/ row the plain slug, so an addon row with the same slug
# would collide with it in catalog_entries.slug (globally unique) if left
# alone.
#
# Detected dynamically, NOT a fixed allowlist: `runtipi` was not one of the
# four names first found, and a hardcoded set would have silently let its
# addon row shadow the ct row. Whatever ct/ slugs a given tree actually has
# decides which addon rows need disambiguating, so this keeps working as the
# upstream corpus grows.
```

**`[702]`** `backend/proxploy/services/catalog.py:113` &middot; **76w → 72w** (5% cut) &middot; _contract_  
Keeps the mechanical typing rule and the ct_slugs contract; drops the investigation reference.

<details><summary>before</summary>

```
Type comes from directory placement, mechanically. Returns None for
    anything that isn't a real, classifiable entry (ct/headers/ banners,
    tools/copy-data/'s 9 scripts, which fit none of the four buckets per
    investigation §3, and any other path in the tree).

    `ct_slugs` is every ct/ slug this SAME tree discovered, computed once by
    the caller: an addon whose slug also names a real standalone ct/
    installer is disambiguated (see the DUAL_VARIANT note above), everything
    else keeps its plain slug.
    
```

</details>

**after**

```
    """Type comes from directory placement, mechanically. Returns None for
    anything that isn't a real, classifiable entry (ct/headers/ banners,
    tools/copy-data/'s scripts, which fit none of the four buckets, and any
    other path in the tree).

    `ct_slugs` is every ct/ slug this SAME tree discovered, computed once by
    the caller: an addon whose slug also names a real standalone ct/ installer
    is disambiguated (see the dual-variant note above), everything else keeps
    its plain slug.
    """
```

**`[703]`** `backend/proxploy/services/catalog.py:143` &middot; **35w → 26w** (26% cut) &middot; _test-reference_  
Keeps that this is call #2 of the budget; drops the one-off truncation spot-check, which the code below re-checks at runtime anyway.

<details><summary>before</summary>

```
One request: `git/trees/<sha>?recursive=1`, `truncated: false`
    confirmed against the live repo (investigation §1). Call #2 of the
    refresh's 2-request budget; the ENTIRE catalog's shape comes from this
    single response, no matter how many entries it contains.
```

</details>

**after**

```
    """One request: `git/trees/<sha>?recursive=1`. Call #2 of the refresh's
    2-request budget; the ENTIRE catalog's shape comes from this single
    response, no matter how many entries it contains."""
```

**`[704]`** `backend/proxploy/services/catalog.py:171` &middot; **53w → 48w** (9% cut) &middot; _redundant_  
Keeps what discovery writes and what it deliberately does not do; drops the repetition of ensure_classified's docstring.

<details><summary>before</summary>

```
Populate the catalog with every entry the tree contains: name (a
    slug-derived fallback; ensure_classified improves it for ct/ once fetched
    lazily), entry_type, category, slug, script_path. Deliberately does NOT
    fetch a single ct/+install script pair here, and deliberately does NOT
    call the feasibility classifier: those are ensure_classified's job, run
    on demand, never during discovery.
```

</details>

**after**

```
    """Populate the catalog with every entry the tree contains: name (a
    slug-derived fallback; ensure_classified improves it for ct/ once fetched
    lazily), entry_type, category, slug, script_path. Deliberately does NOT
    fetch a script pair and does NOT call the feasibility classifier: that is
    ensure_classified's job, on demand, never during discovery."""
```

**`[705]`** `backend/proxploy/services/catalog.py:202` &middot; **37w → 32w** (14% cut) &middot; _narration_  
Keeps why non-ct types are never classified; trims the parenthetical restatement of the Store rule.

<details><summary>before</summary>

```
# Never installable, never classified: these types don't have a
# ct/+install/ pair in the shape the classifier expects, and the
# Store never shows them regardless (decision: LXC-only Store, other
# types stay in the catalog table tagged by type).
```

</details>

**after**

```
        # Never installable, never classified: these types don't have a
        # ct/+install/ pair in the shape the classifier expects, and the Store
        # is LXC-only, so they stay in the catalog table tagged by type.
```

**`[706]`** `backend/proxploy/services/catalog.py:237` &middot; **207w → 154w** (26% cut) &middot; _implementation-diary_  
Keeps the two upstream shapes and the recorded-not-executed distinction; cuts the copied-rule argument and the bug retelling.

<details><summary>before</summary>

```
The in-container payload script this catalog entry has pinned, whatever
    shape upstream ships it in, or None if nothing is pinned yet.

    THE ONE READER of that pair of `raw` keys, and it is a shared helper for
    the same reason services/catalog_metadata.py::store_visible is: there are
    FOUR call sites and they are all asking the identical question, so a rule
    copied four times is a rule that gets updated in three of them. This is
    the reader half of what `ensure_classified` writes.

    Two keys because upstream ships two shapes. A normal app has
    `install/<slug>-install.sh`, stored under "install_script". Five apps
    (coolify, dockge, dokploy, komodo, runtipi) instead delegate to
    `tools/addon/<slug>.sh`, stored under "addon_script"
    (classifier.addon_delegation_slug). Reading only the first key filed an
    AppScript row with empty content and the sha256 of the empty string for
    those five, which is a script viewer showing nothing and a version diff
    against nothing.

    NOT what gets EXECUTED, and the distinction matters. Both run_install and
    the update path execute the pinned ct script at
    `raw_url(upstream_sha, script_path)`, which performs the addon delegation
    itself at runtime. This is what gets RECORDED, diffed and shown.

    install_script wins when both are somehow present: it is the more specific
    key, and only the addon-delegating path ever writes the other one.
    
```

</details>

**after**

```
    """The in-container payload script this catalog entry has pinned, whatever
    shape upstream ships it in, or None if nothing is pinned yet. THE ONE
    READER of that pair of `raw` keys, shared because four call sites ask the
    identical question. The reader half of what `ensure_classified` writes.

    Two keys because upstream ships two shapes. A normal app has
    `install/<slug>-install.sh`, stored under "install_script". Five apps
    (coolify, dockge, dokploy, komodo, runtipi) instead delegate to
    `tools/addon/<slug>.sh`, stored under "addon_script"
    (classifier.addon_delegation_slug). Reading only the first key files an
    AppScript row with empty content and the sha256 of the empty string for
    those five.

    NOT what gets EXECUTED. run_install and the update path execute the pinned
    ct script at `raw_url(upstream_sha, script_path)`, which performs the
    addon delegation itself at runtime. This is what gets RECORDED, diffed and
    shown. install_script wins when both are somehow present: it is the more
    specific key, and only the addon-delegating path writes the other one.
    """
```

**`[707]`** `backend/proxploy/services/catalog.py:268` &middot; **72w → 54w** (25% cut) &middot; _contract_  
Keeps the two-payloads-two-lifecycles rule; trims the closing clause that restates it.

<details><summary>before</summary>

```
`raw` carries two independent payloads with two different lifecycles:
    the pinned ct/install script pair this module fetches per upstream commit,
    and the upstream record snapshot services/catalog_metadata.py writes under
    "metadata" on its own 6-hourly schedule. Classification rewrites the
    former, so it has to carry the latter through rather than blow it away on
    every backlog pass and leave the snapshot alive only in the window between
    a metadata sync and the next classification.
```

</details>

**after**

```
    """`raw` carries two independent payloads with two different lifecycles:
    the pinned ct/install script pair this module fetches per upstream commit,
    and the upstream record snapshot services/catalog_metadata.py writes under
    "metadata" on its own schedule. Classification rewrites the former, so it
    has to carry the latter through rather than blow it away on every backlog
    pass."""
```

**`[708]`** `backend/proxploy/services/catalog.py:282` &middot; **91w → 81w** (11% cut) &middot; _contract_  
Keeps the ownership split and the ordering that makes it matter; drops the design-doc pointer.

<details><summary>before</summary>

```
The ct script's own `APP="..."` and `# Source:` lines, applied only
    where upstream metadata has not already spoken.

    Presentation fields belong to services/catalog_metadata.py when a slug
    matched an upstream record (the ownership split in the design doc), and
    classification runs AFTER the metadata sync in a refresh, so writing these
    unconditionally would quietly hand the last word back to the script parse
    for every matched row. An unmatched row has no upstream record to defer
    to, and `APP="Redis"` beats the slug-derived fallback name every time, so
    it still gets the script's version.
    
```

</details>

**after**

```
    """The ct script's own `APP="..."` and `# Source:` lines, applied only
    where upstream metadata has not already spoken.

    Presentation fields belong to services/catalog_metadata.py when a slug
    matched an upstream record, and classification runs AFTER the metadata
    sync in a refresh, so writing these unconditionally would hand the last
    word back to the script parse for every matched row. An unmatched row has
    no upstream record to defer to, and `APP="Redis"` beats the slug-derived
    fallback name, so it still gets the script's version.
    """
```

**`[709]`** `backend/proxploy/services/catalog.py:329` &middot; **89w → 76w** (15% cut) &middot; _narration_  
Keeps the delegation shape and why the script is still fetched; trims the count and the restatement.

<details><summary>before</summary>

```
# Before concluding there is nothing to classify: some ct scripts
# delegate their in-container step to tools/addon/<slug>.sh instead of
# shipping an install/ file (classifier.addon_delegation_slug). Five
# popular apps are in this shape. They are still NOT installable, for
# a reason that has nothing to do with the addon script's contents
# (see below), but the script is worth fetching: it carries the real
# payload for the `raw` snapshot, and reaching this branch at all is
# what lets us give an accurate reason instead of the flatly wrong
# "no install script found upstream".
```

</details>

**after**

```
        # Before concluding there is nothing to classify: some ct scripts
        # delegate their in-container step to tools/addon/<slug>.sh instead of
        # shipping an install/ file (classifier.addon_delegation_slug). They
        # are still NOT installable, for a reason that has nothing to do with
        # the addon script's contents (see below), but the script carries the
        # real payload for the `raw` snapshot, and reaching this branch is what
        # lets us give an accurate reason instead of the flatly wrong "no
        # install script found upstream".
```

**`[710]`** `backend/proxploy/services/catalog.py:340` &middot; **45w → 43w** (4% cut) &middot; _test-reference_  
Keeps that this is a known upstream shape and why the fetch is stored; drops the investigation reference.

<details><summary>before</summary>

```
# 13 ct/ scripts have no matching install/ file (investigation §1)
# and no addon delegation either: a real, known shape, not corrupt
# data. Store what was fetched so a retry at the same commit is a
# no-op, and report it honestly rather than crash the caller.
```

</details>

**after**

```
            # 13 ct/ scripts have no matching install/ file and no addon
            # delegation either: a real, known shape, not corrupt data. Store
            # what was fetched so a retry at the same commit is a no-op, and
            # report it honestly rather than crash the caller.
```

**`[711]`** `backend/proxploy/services/catalog.py:372` &middot; **200w → 154w** (23% cut) &middot; _implementation-diary_  
Keeps why the verdict is hardcoded and the build.func mechanism behind it; cuts the 'an earlier version did' diary.

<details><summary>before</summary>

```
# ALWAYS not-installable, and deliberately NOT a call to
# classify_install_feasibility, so this verdict cannot come to depend
# on what the addon script happens to contain.
#
# The addon script is not what an install runs. `build_container`
# installs by curling `install/<var_install>.sh` and lxc-attaching it
# (misc/build.func:5174), that URL 404s for every app in this shape,
# the failure is swallowed because error handling is off at that
# point, and `bash -c ""` exits 0. Upstream's own ct script builds a
# container, installs nothing, and reports success. The addon script
# is referenced only from `update_script()` and never runs here.
#
# An earlier version of this branch DID run the feasibility check
# here. Today all five addon scripts prompt, so all five came back
# not-installable and the hole never opened; had one been silent, this
# would have marked it installable and an install would have produced
# an empty container filed as a success, which run_install's "exited 0
# but no CT" guard cannot catch because the CT really does exist. The
# fix for that is a real second execution step, and one that never
# answers a prompt on the operator's behalf: either the operator
# picked the value in a form beforehand or answers it live. Not a
# softer verdict here.
```

</details>

**after**

```
        # ALWAYS not-installable, and deliberately NOT a call to
        # classify_install_feasibility, so this verdict cannot come to depend
        # on what the addon script happens to contain.
        #
        # The addon script is not what an install runs. `build_container`
        # installs by curling `install/<var_install>.sh` and lxc-attaching it
        # (misc/build.func:5174), that URL 404s for every app in this shape,
        # the failure is swallowed because error handling is off at that point,
        # and `bash -c ""` exits 0. Upstream's own ct script builds a
        # container, installs nothing, and reports success. The addon script is
        # referenced only from `update_script()` and never runs here.
        #
        # Running the feasibility check here would mark a silent addon script
        # installable, and the install would then file an empty container as a
        # success, which run_install's "exited 0 but no CT" guard cannot catch
        # because the CT really does exist. The fix is a real second execution
        # step that never answers a prompt on the operator's behalf, not a
        # softer verdict here.
```

**`[712]`** `backend/proxploy/services/catalog.py:418` &middot; **104w → 79w** (24% cut) &middot; _measurement-dump_  
Keeps the bounded-concurrency reason with its one load-bearing number and the raw-only rule; drops the decision numbering.

<details><summary>before</summary>

```
The low-priority background pass (decision 2): bounded-concurrency
    lazy classification of whatever ensure_classified hasn't reached yet.
    Runs as its own job, scheduled AFTER run_discovery already returned, so a
    freshly refreshed store is usable (names, types, categories) before this
    even starts.

    Bounded concurrency, not a `for` loop: the investigation flagged a plain
    sequential fetch of up to ~1,168 raw files (2 per ct/ entry) as several
    minutes of wall-clock time blocking one thread. Concurrency here is
    asyncio tasks each parking a blocking httpx call in a thread, capped by a
    semaphore; still `raw.githubusercontent.com` only, never api.github.com,
    so it has no effect on the refresh's 2-request ceiling.
    
```

</details>

**after**

```
    """The low-priority background pass: bounded-concurrency lazy
    classification of whatever ensure_classified hasn't reached yet. Runs as
    its own job, scheduled AFTER run_discovery already returned, so a freshly
    refreshed store is usable (names, types, categories) before this starts.

    Bounded concurrency, not a `for` loop: a sequential fetch of up to ~1,168
    raw files (2 per ct/ entry) is several minutes of wall-clock time blocking
    one thread. Still `raw.githubusercontent.com` only, never api.github.com,
    so it has no effect on the refresh's 2-request ceiling.
    """
```

**`[713]`** `backend/proxploy/services/catalog.py:451` &middot; **215w → 135w** (37% cut) &middot; _measurement-dump_  
Keeps the weighting rule and one representative size comparison; cuts the re-weighting history and the per-phase measurement table.

<details><summary>before</summary>

```
# Phase boundaries for the refresh's progress bar. Weighted by real relative
# cost, not split evenly, and emitted only where a phase genuinely ends: no
# timers, no interpolation, so a bar that sits still is a phase that is still
# working. Discovery (2 api.github.com calls plus a skeleton upsert for every
# one of ~668 entries) and the metadata sync (one ~1.9 MB fetch, ~1.6 s
# measured, plus ~616 matched upserts each writing a raw JSON snapshot) are
# the two heavy phases and are close in cost, with discovery slightly ahead
# because it writes every row rather than the matched subset. The last two
# phases are DB-only and near-instant, so they share the final 15 points
# instead of the half of the bar an even split would hand them.
#
# Re-weighted rather than extended when the telemetry phase landed: bolting a
# fifth number onto the end would have squeezed it into the 10 points between
# 85 and 95 and implied it costs about as much as a pure-DB pass, which is
# false. It is a real network fetch, just a much smaller one than the metadata
# sync (one ~255 KB response against ~1.9 MB) writing one integer column on
# matched rows instead of a raw JSON snapshot, so it takes roughly a third of
# what that phase does.
```

</details>

**after**

```
# Phase boundaries for the refresh's progress bar. Weighted by real relative
# cost, not split evenly, and emitted only where a phase genuinely ends: no
# timers, no interpolation, so a bar that sits still is a phase that is still
# working. Discovery and the metadata sync are the two heavy phases and are
# close in cost, discovery slightly ahead because it writes every row rather
# than the matched subset. Popularity is a real network fetch but a much
# smaller one (about 255 KB against the metadata sync's 1.9 MB) writing one
# integer column instead of a raw JSON snapshot, so it takes roughly a third
# of that phase. The last two phases are DB-only and near-instant, so they
# share the final 15 points instead of the half of the bar an even split would
# hand them.
```

**`[714]`** `backend/proxploy/services/catalog.py:493` &middot; **74w → 65w** (12% cut) &middot; _narration_  
Keeps the double-wrapping rationale and the never-fail-a-refresh posture; trims the wording.

<details><summary>before</summary>

```
# Upstream presentation metadata (names, descriptions, categories, icons):
# services/catalog_metadata.py, PocketBase with a cold-start-only fallback
# to the frozen frontend archive. Best-effort by design and wrapped twice
# over: sync_metadata already turns an upstream failure into an outcome
# dict rather than an exception, and this catch covers a genuine bug in
# it. Either way the catalog stays exactly as discovery left it, which is
# a usable store, and the job carries on to 100 rather than stalling here.
```

</details>

**after**

```
    # Upstream presentation metadata (names, descriptions, categories, icons):
    # services/catalog_metadata.py, PocketBase with a cold-start-only fallback
    # to the frozen frontend archive. Best-effort by design and wrapped twice
    # over: sync_metadata already turns an upstream failure into an outcome
    # dict, and this catch covers a genuine bug in it. Either way the catalog
    # stays exactly as discovery left it and the job carries on to 100 rather
    # than stalling here.
```

**`[715]`** `backend/proxploy/services/catalog.py:510` &middot; **66w → 53w** (20% cut) &middot; _measurement-dump_  
Keeps the log-counts-not-slugs policy and why the state tally rides along; drops the row counts.

<details><summary>before</summary>

```
# Counts, once, not per slug: an unmatched row in either direction is
# the steady state (37 of our ct/ rows, 85 upstream slugs), so naming
# them individually would be a wall of noise describing normality.
# The upstream_state tally rides along for the same reason it exists:
# a jump in "unlisted" or "variant" is the signal that upstream
# reshaped its catalog, and it is invisible in matched/unmatched.
```

</details>

**after**

```
        # Counts, once, not per slug: an unmatched row in either direction is
        # the steady state, so naming them individually would be a wall of
        # noise describing normality. The upstream_state tally rides along
        # because a jump in "unlisted" or "variant" is the signal that upstream
        # reshaped its catalog, and it is invisible in matched/unmatched.
```

**`[716]`** `backend/proxploy/services/catalog.py:519` &middot; **50w → 45w** (10% cut) &middot; _redundant_  
Same rule as the catalog_metadata log note; keeps only why name matches are logged individually.

<details><summary>before</summary>

```
# Name matches ARE named individually, unlike everything else here.
# There is one of them today, it is a heuristic rather than an exact
# join, and a wrong pair must be visible to whoever reads this job's
# log rather than only discoverable by noticing a card that describes
# the wrong app.
```

</details>

**after**

```
        # Name matches ARE named individually, unlike everything else here:
        # the join is a heuristic rather than an exact one, and a wrong pair
        # must be visible to whoever reads this job's log rather than only
        # discoverable by noticing a card that describes the wrong app.
```

**`[717]`** `backend/proxploy/services/catalog.py:533` &middot; **83w → 69w** (17% cut) &middot; _contract_  
Keeps the never-condition-on-meta-ok rule and its reason; folds the repeated double-wrapping note into a pointer.

<details><summary>before</summary>

```
# Install popularity: services/catalog_telemetry.py, a third host with no
# fallback source. Deliberately run REGARDLESS of what the metadata sync
# just did, and never conditioned on `meta["ok"]`: they are different
# services on different hosts with different outages, and skipping the
# popularity refresh because PocketBase happened to be down would turn one
# service's bad day into two stale signals. Same never-fail-the-job
# posture and the same double wrapping: sync_popularity already turns an
# upstream failure into an outcome dict, and this catch covers a genuine
# bug in it.
```

</details>

**after**

```
    # Install popularity: services/catalog_telemetry.py, a third host with no
    # fallback source. Deliberately run REGARDLESS of what the metadata sync
    # just did, and never conditioned on `meta["ok"]`: they are different
    # services on different hosts with different outages, and skipping the
    # popularity refresh because PocketBase happened to be down would turn one
    # service's bad day into two stale signals. Same never-fail-the-job posture
    # and the same double wrapping as the metadata phase above.
```

**`[718]`** `backend/proxploy/services/catalog.py:560` &middot; **128w → 108w** (16% cut) &middot; _measurement-dump_  
Keeps the ordering dependency, the best-effort posture and the one measurement that justifies progress reporting; cuts the rest.

<details><summary>before</summary>

```
# Icons, mirrored into data_dir/icons so the Store renders offline
# (services/catalog_icons.py). Runs AFTER the metadata sync because it
# consumes the icon_url that sync just wrote, and like every other phase
# here it is best effort and double wrapped: a CDN outage leaves every
# previously cached file in place and every uncached row falling back to
# the upstream URL, which is exactly the behaviour before this existed.
# The bar moves THROUGH this phase rather than jumping over it. It is the
# longest step of a refresh by a wide margin whenever the icon cache is
# cold: measured at 8.0s of an 11.0s run, 629 files, and the whole time the
# job sat at PCT_POPULARITY_SYNCED with nothing to say. Reported as "stuck
# at 82%", which is exactly what it looked like.
```

</details>

**after**

```
    # Icons, mirrored into data_dir/icons so the Store renders offline
    # (services/catalog_icons.py). Runs AFTER the metadata sync because it
    # consumes the icon_url that sync just wrote, and like every other phase
    # here it is best effort and double wrapped: a CDN outage leaves every
    # previously cached file in place and every uncached row falling back to
    # the upstream URL. The bar moves THROUGH this phase rather than jumping
    # over it, because on a cold cache this is the longest step of a refresh by
    # a wide margin (measured at 8.0s of an 11.0s run) and the job used to sit
    # at PCT_POPULARITY_SYNCED with nothing to say, which read as stuck.
```

**`[719]`** `backend/proxploy/services/catalog.py:572` &middot; **55w → 53w** (4% cut) &middot; _measurement-dump_  
Keeps the announce-once rule; drops the file count.

<details><summary>before</summary>

```
# Only ever announces a number it has not announced yet. 629 icons into a
# ten point span is the same percentage over and over, and every repeat is
# a job row write and an SSE frame that tell a reader nothing they did not
# already have. This collapses those to at most one per point.
```

</details>

**after**

```
    # Only ever announces a number it has not announced yet. Hundreds of icons
    # into a ten point span is the same percentage over and over, and every
    # repeat is a job row write and an SSE frame that tell a reader nothing
    # they did not already have. At most one announcement per point.
```

**`[720]`** `backend/proxploy/services/catalog.py:579` &middot; **74w → 71w** (4% cut) &middot; _narration_  
Keeps the thread-handoff reason and the off-by-one span rule; tightens both.

<details><summary>before</summary>

```
# Called from the download pool's thread. ctx.progress touches the job
# row and the SSE bus, so it is handed back to the loop rather than
# invoked here.
#
# The span stops one short of PCT_ICONS_SYNCED: the phase is not done
# when the last download lands, it is done when the rows below have
# been written, and that boundary belongs to the single call after this
# block. Reporting 92 here would announce the same number twice.
```

</details>

**after**

```
        # Called from the download pool's thread. ctx.progress touches the job
        # row and the SSE bus, so it is handed back to the loop rather than
        # invoked here.
        #
        # The span stops one short of PCT_ICONS_SYNCED: the phase is done when
        # the rows below have been written, not when the last download lands,
        # and that boundary belongs to the single call after this block.
        # Reporting 92 here would announce the same number twice.
```

**`[721]`** `backend/proxploy/services/catalog.py:627` &middot; **24w → 22w** (8% cut) &middot; _redundant_  
Repeats the module docstring and classify_backlog's own docstring; keeps the queued-not-awaited fact and drops the decision reference.

<details><summary>before</summary>

```
# Low-priority background pass (decision 2): queued, not awaited. The
# store is already usable (names, types, categories from discovery
# alone) before this job even starts.
```

</details>

**after**

```
    # Low-priority background pass: queued, not awaited. The store is already
    # usable (names, types, categories from discovery alone) before this job
    # even starts.
```


### 🟢 KEEP (16), unchanged

- **`[722]`** `84` &middot; _security_ &middot; `Raw-content URL pinned to an immutable commit, never to `main`.`
- **`[723]`** `95` &middot; _contract_ &middot; `The repo's current HEAD commit SHA. Call #1 of the refresh's flat,`
- **`[724]`** `152` &middot; _data-integrity_ &middot; `# A truncated tree would silently drop entries below some GitHub-side`
- **`[725]`** `190` &middot; _contract_ &middot; `# nothing changed upstream since the last refresh`
- **`[726]`** `209` &middot; _data-integrity_ &middot; `# The commit moved: any previously fetched ct/install text was pinned`
- **`[727]`** `300` &middot; _contract_ &middot; `Fetch, parse and classify one ct/ entry's script pair, lazily: called`
- **`[728]`** `313` &middot; _contract_ &middot; `# nothing pinned yet; a refresh hasn't run`
- **`[729]`** `324` &middot; _contract_ &middot; `# Which `raw` key the payload lands under, so a reader can tell at a`
- **`[730]`** `353` &middot; _security_ &middot; `# PINNED, via the same raw_url helper as the ct and install fetches.`
- **`[731]`** `443` &middot; _generated_ &middot; `# noqa: BLE001 - one bad slug can't kill the pass`
- **`[732]`** `472` &middot; _surprising_ &middot; `# The icon mirror is the one phase whose cost swings wildly: a cold cache`
- **`[733]`** `506` &middot; _generated_ &middot; `# noqa: BLE001 - metadata never fails a refresh`
- **`[734]`** `548` &middot; _generated_ &middot; `# noqa: BLE001 - popularity never fails a refresh`
- **`[735]`** `600` &middot; _generated_ &middot; `# noqa: BLE001 - icons never fail a refresh`
- **`[736]`** `613` &middot; _contract_ &middot; `# A refresh is the ONLY moment `update_available` can change, so it is the`
- **`[737]`** `644` &middot; _contract_ &middot; `Low-priority background pass: classify every ct/ entry a refresh`

---

## `frontend/src/components/StoreCard.tsx`

2,447 → 1,277 words, 48% cut. 0 delete, 20 shorten, 4 keep.


### 🟡 SHORTEN (20)

**`[738]`** `frontend/src/components/StoreCard.tsx:9` &middot; **42w → 37w** (12% cut) &middot; _surprising_  
Keep the pinned entry_type and why the lookup survives, cut the wording.

<details><summary>before</summary>

```
// Every entry the Store ever renders is entry_type "ct" (the API call is
// pinned to entry_type=ct), so this is really just a label; kept as a lookup
// rather than a literal string so a card is still honest if that ever
// changes.
```

</details>

**after**

```
// Everything the Store renders is entry_type "ct" (the API call is pinned to
// it), so this is really a label. Kept as a lookup rather than a literal so a
// card stays honest if that ever changes.
```

**`[739]`** `frontend/src/components/StoreCard.tsx:17` &middot; **156w → 77w** (51% cut) &middot; _external-quirk_  
Keep the delisted/unlisted meaning and why the badge is neutral, drop the per-app inventory.

<details><summary>before</summary>

```
// "delisted" (upstream soft-deleted it, so its metadata still arrives and the
// card is fully populated) and "unlisted" (upstream dropped it outright, so
// the card is bare) are two different facts about upstream's data and exactly
// one fact to whoever is reading the card: community-scripts does not list
// this app any more. So they share one badge here while staying distinct in
// the row itself.
//
// What the badge is careful NOT to say: that the app is deprecated, abandoned,
// broken or unsafe. We know one thing, that upstream stopped listing it. Its
// install script is still in the repo and still runs, which is why this is
// neutral chrome next to the type badge rather than a warning colour, and why
// it does not gate the Install button. Two of these are genuinely
// discontinued projects (readarr, overseerr) and the rest are not, and the
// card has no way to tell them apart, so it does not try.
```

</details>

**after**

```
// "delisted" (upstream soft-deleted it, so its metadata still arrives) and
// "unlisted" (upstream dropped it, so the card is bare) are two facts about
// upstream's data and one fact to the reader: community-scripts does not list
// this app any more. So they share one badge.
//
// The badge does not say deprecated, abandoned, broken or unsafe. The install
// script is still in the repo and still runs, which is why it is neutral
// chrome and does not gate Install.
```

**`[740]`** `frontend/src/components/StoreCard.tsx:31` &middot; **196w → 88w** (55% cut) &middot; _measurement-dump_  
Keep the rare-side rule and the null invariant, cut the frequency table.

<details><summary>before</summary>

```
/**
 * The tag chips, and the reason there are only three of them.
 *
 * Measured over the 556 store-visible ct rows in the dev catalog, upstream's
 * booleans are extremely lopsided, so the naive reading of each flag would put
 * a chip on almost every card and say nothing:
 *
 *   has_arm      true 482 (87%)  false  66  null 7
 *   updateable   true 538 (97%)  false  10  null 7
 *   privileged   true  19 ( 3%)  false 529  null 7
 *
 * A chip that appears on 87% or 97% of the grid is furniture. So two of these
 * are rendered on the RARE side, where the information actually is: nearly
 * everything runs on ARM and updates in place, and it is the handful that
 * cannot which changes what an operator does next. `privileged` is the one
 * that is genuinely informative on `true`, and it is the security-relevant
 * one, so it stays as it is.
 *
 * Every condition below is an explicit === true or === false. Null means
 * upstream has no record for the slug (the 7 unlisted rows) and must render
 * NOTHING: `has_arm: null` is not "x86 only" and `privileged: null` is not
 * "unprivileged". Testing falsiness here would silently label all 7 of them
 * with claims nobody has made.
 */
```

</details>

**after**

```
/**
 * The tag chips, and why there are only three.
 *
 * has_arm and updateable are true on 87% and 97% of the 556 store-visible ct
 * rows, so a chip on the common side would be furniture. Those two render on
 * the RARE side, where the information is. `privileged` is informative on
 * `true` and is the security-relevant one.
 *
 * Every condition is an explicit === true or === false. Null means upstream
 * has no record for the slug and must render NOTHING: `has_arm: null` is not
 * "x86 only" and `privileged: null` is not "unprivileged".
 */
```

**`[741]`** `frontend/src/components/StoreCard.tsx:62` &middot; **249w → 99w** (60% cut) &middot; _buried-invariant_  
Keep the en-US pinning and the null rule, cut the abandoned-tiers history.

<details><summary>before</summary>

```
/**
 * The install count, shown as the number it actually is.
 *
 * This slot briefly carried invented tiers ("Top 10%", then "Popular" /
 * "Common"). Those were labels WE made up on top of the data: a reader cannot
 * check them, cannot say what separates Popular from Common, and the words
 * imply a judgement the telemetry never made. The underlying number is the
 * quantifiable thing, so the number is what shows. No banding, no percentile,
 * no rounding to "126k" either, since an abbreviation is just a coarser band
 * wearing a number's clothes.
 *
 * Gold `text-amber` at 23px glyph and 14px text, which is the sizing that was
 * asked for and has not changed.
 *
 * Grouping is pinned to en-US rather than the reader's own locale, by
 * decision. A bare toLocaleString() follows the runtime locale, which on an
 * en-IN machine renders this same figure as 1,26,196 (lakh grouping). Both
 * forms are correct; one form everywhere is the choice, and routes/
 * store-detail.tsx pins the identical call for the same figure so the card
 * and the page it links to can never disagree.
 *
 * Null renders NOTHING at all: no icon, no zero. Absence means upstream has no
 * measurement for this slug, and a zero would be a claim that nobody installed
 * it. That rule is the same one the tag chips follow for their own nulls.
 *
 * Every caveat lives in the tooltip rather than inline on the card: what the
 * number counts is a real footnote, but it is a footnote, and the card has
 * 284px to spend.
 */
```

</details>

**after**

```
/**
 * The install count, shown as the number it actually is. No banding, no
 * percentile, no rounding to "126k": an invented tier is a judgement the
 * telemetry never made. Gold `text-amber`, 23px glyph, 14px text.
 *
 * Grouping is pinned to en-US, not the reader's locale: a bare
 * toLocaleString() renders this figure as 1,26,196 on an en-IN machine.
 * routes/store-detail.tsx pins the identical call, so a card and the page it
 * links to cannot disagree.
 *
 * Null renders NOTHING: no icon, no zero. Upstream has no measurement for this
 * slug, and a zero would claim nobody installed it. Same rule the tag chips
 * follow.
 */
```

**`[742]`** `frontend/src/components/StoreCard.tsx:91` &middot; **114w → 59w** (48% cut) &middot; _buried-invariant_  
Keep the month-as-word reason and format-not-instant, drop what the block above already says.

<details><summary>before</summary>

```
// Pinned to en-US, identically in routes/store-detail.tsx, for the same reason
// the install count above is pinned: one rendering for every reader rather
// than one per locale, and the two files must agree because a card links
// straight to that page.
//
// The month is a WORD on purpose. "8/13/2026" and "13/8/2026" are the same
// nine characters rearranged, and a reader cannot tell which locale produced
// them; this date carries the staleness caveat for a figure that can sit a
// day behind upstream, so being misread by half the world is not cosmetic.
// Only the FORMAT is pinned, never the instant: the time zone stays the
// reader's own, as it is everywhere else in the app.
```

</details>

**after**

```
// The month is a WORD on purpose. "8/13/2026" and "13/8/2026" are the same
// characters rearranged and a reader cannot tell which locale produced them,
// and this date carries the staleness caveat for a figure that can sit a day
// behind upstream. Pinned to en-US identically in routes/store-detail.tsx.
// Only the FORMAT is pinned: the time zone stays the reader's own.
```

**`[743]`** `frontend/src/components/StoreCard.tsx:114` &middot; **61w → 45w** (26% cut) &middot; _test-reference_  
Keep why role="img" is refused, drop the getByRole query it was found with.

<details><summary>before</summary>

```
// No role="img" here, deliberately. The figure IS text, so it reads
// correctly on its own; the only thing missing for a screen reader is what
// the number counts, since Icon renders its glyph aria-hidden. An sr-only
// prefix supplies that. role="img" would also have collided with the app
// logo <img> on the same card, making getByRole('img') ambiguous for
// anything querying the logo.
```

</details>

**after**

```
    // No role="img" here, deliberately. The figure IS text, so it reads
    // correctly on its own; the sr-only prefix supplies the one missing thing,
    // what the number counts, since Icon renders its glyph aria-hidden.
    // role="img" would also collide with the app logo <img> on this card.
```

**`[744]`** `frontend/src/components/StoreCard.tsx:131` &middot; **53w → 41w** (23% cut) &middot; _contract_  
Keep the count-not-flag contract, cut the aside about naming schemes.

<details><summary>before</summary>

```
/** How many apps are already installed from this catalog entry. A COUNT and
   *  not a flag: installing a second copy is ordinary (a test one beside a
   *  prod one, or somebody's own naming scheme), so "installed" has to be
   *  something the card SAYS rather than something it does by removing the
   *  Install button. */
```

</details>

**after**

```
  /** How many apps are already installed from this catalog entry. A COUNT and
   *  not a flag: installing a second copy is ordinary, so "installed" has to
   *  be something the card SAYS rather than something it does by removing the
   *  Install button. */
```

**`[745]`** `frontend/src/components/StoreCard.tsx:142` &middot; **37w → 25w** (32% cut) &middot; _surprising_  
Keep why the ref exists, cut the closing aside.

<details><summary>before</summary>

```
// Where the pointer went down, so a DRAG can be told from a CLICK. Without
// this, selecting the description text and releasing opens the popup, which
// is a small thing that is very irritating when it happens.
```

</details>

**after**

```
  // Where the pointer went down, so a DRAG can be told from a CLICK. Without
  // this, selecting the description text and releasing opens the popup.
```

**`[746]`** `frontend/src/components/StoreCard.tsx:147` &middot; **139w → 78w** (44% cut) &middot; _surprising_  
Keep the do-not-add-tabIndex rule and the stopPropagation invariant, cut the essay.

<details><summary>before</summary>

```
/**
   * Clicking the card body opens the detail popup, the same as Read more.
   *
   * This is mouse convenience on the container and real semantics on the
   * children, DELIBERATELY split that way. The container gets no
   * `role="button"` and no `tabIndex`: that would add a redundant tab stop
   * whose accessible name is the entire card read out as one control, and it
   * would nest the Install button inside an interactive element in the
   * accessibility tree even though the DOM stays valid. The keyboard path
   * already exists and is better, because the title and Read more are real
   * buttons. Please do not "fix" this by adding a tabIndex.
   *
   * Every genuine control inside stops propagation, so exactly one thing
   * happens per click: Install installs without also opening the popup behind
   * its own dialog, and the upstream link leaves for upstream without opening
   * anything here.
   */
```

</details>

**after**

```
  /**
   * Clicking the card body opens the detail popup, the same as Read more.
   *
   * The container deliberately gets no `role="button"` and no `tabIndex`: that
   * would add a tab stop whose accessible name is the whole card read out as
   * one control, and would nest the Install button inside an interactive
   * element. The title and Read more are already real buttons. Please do not
   * add a tabIndex.
   *
   * Every genuine control inside stops propagation, so exactly one thing
   * happens per click.
   */
```

**`[747]`** `frontend/src/components/StoreCard.tsx:170` &middot; **48w → 38w** (21% cut) &middot; _external-quirk_  
Keep that click never fires for the middle button, cut the rest.

<details><summary>before</summary>

```
// Modifier and middle clicks: `click` does not fire for the middle button
// at all (that is `auxclick`), and a ctrl/cmd click gets the same popup as
// a plain one. There is no URL behind this, so there is no new tab to
// offer and nothing surprising to suppress.
```

</details>

**after**

```
    // Modifier and middle clicks need nothing: `click` never fires for the
    // middle button (that is `auxclick`), and a ctrl/cmd click gets the same
    // popup. There is no URL behind this, so there is no new tab to offer.
```

**`[748]`** `frontend/src/components/StoreCard.tsx:181` &middot; **470w → 195w** (59% cut) &middot; _measurement-dump_  
Keep the fixed-height rule, the pixel derivation and the overflow guard, cut the 224px diary.

<details><summary>before</summary>

```
/**
     * ONE FIXED HEIGHT FOR EVERY CARD, so a 10-line description next to a
     * 2-line one stops leaving a hole in the grid. The height is spent in
     * this order: everything above the description is intrinsic, the
     * description is capped at exactly three lines, and a flex spacer below
     * "Read more" swallows whatever is left, which is what pins the chip row
     * and the action row to the same baseline on every card in a row.
     *
     * 240px, down from 284px originally, via a wrong 224px that shipped an
     * overlap. The saving is real (Install moved onto the "Read more" row,
     * deleting a whole row and its margin) but the first budget for it was
     * arithmetic, not measurement, and it was WRONG: it counted the name as
     * 20px and forgot the `mt-2` above it entirely, then rounded the category
     * and chip rows down. That left 3px of nominal slack against a true
     * requirement of ~231px, so five compressible children shrank to fit and
     * squeezed their line boxes into each other. `overflow-hidden` then hid
     * the evidence at the card edge instead of showing it.
     *
     * Re-derived from the built stylesheet rather than from memory
     * (--spacing is .25rem, body line-height is the unitless 1.45):
     *
     *   32.00  p-4, top and bottom
     *   40.00  header row: max(h-10 icon tile 40, install count 23)
     *   28.30  name: mt-2 8 + 14px * 1.45 line box   <- the 8 that was missed
     *   15.95  category: 11px * 1.45
     *   57.00  description: mt-1 4 + the fixed h-[53px] box
     *   29.05  action row: mt-1 4 + xs Button (py-1.5 12 + 9px * 1.45)
     *   28.50  chip row: mt-2 8 + bordered chip (border 2 + py-0.5 4 + 14.5)
     *   ------
     *   230.80 worst case, which is the Install/Installed state
     *
     * These are CSS-determined, not glyph-determined: a unitless line-height
     * times a px font size is exact, and the icon carries an explicit 23px
     * box, so the figures are firm to the sub-pixel rather than estimates.
     * The one I would least defend is the chip row, since a future chip with
     * different padding moves it. The not-installable state is SHORTER
     * (~20.7px action row, being text rather than a control), which the
     * spacer below absorbs.
     *
     * 240 leaves ~9px of genuine headroom. Every child above the spacer is
     * now shrink-0, so if a future change does exceed the budget the result
     * is honest clipping at the card edge, never text drawn over text.
     *
     * overflow-hidden is a guard, not a plan. The chip row cannot actually
     * wrap: the three tag chips and the unlisted badge are mutually exclusive
     * by construction, because a row upstream has no record for has null for
     * all three booleans and so renders none of them, and the widest possible
     * real combination (type + Privileged + x86 only + No in-place update)
     * measures ~282px against a ~365px chip lane at the 4-column width. If a
     * future chip breaks that arithmetic, this clips instead of pushing the
     * action row out of alignment across the row.
     */
```

</details>

**after**

```
    /**
     * ONE FIXED HEIGHT FOR EVERY CARD, so a 10-line description next to a
     * 2-line one stops leaving a hole in the grid. Everything above the
     * description is intrinsic, the description is capped at exactly three
     * lines, and a flex spacer below "Read more" swallows the rest, which
     * pins the chip row and the action row to one baseline across a row.
     *
     * 240px, derived from the built stylesheet (--spacing .25rem, body
     * line-height the unitless 1.45):
     *
     *   32.00  p-4, top and bottom
     *   40.00  header row: max(h-10 icon tile 40, install count 23)
     *   28.30  name: mt-2 8 + 14px * 1.45 line box
     *   15.95  category: 11px * 1.45
     *   57.00  description: mt-1 4 + the fixed h-[53px] box
     *   29.05  action row: mt-1 4 + xs Button (py-1.5 12 + 9px * 1.45)
     *   28.50  chip row: mt-2 8 + bordered chip (border 2 + py-0.5 4 + 14.5)
     *   ------
     *   230.80 worst case, the Install/Installed state
     *
     * Every child above the spacer is shrink-0, so exceeding the budget clips
     * at the card edge instead of drawing text over text. overflow-hidden is
     * that guard, not a plan: the chip row cannot actually wrap, since the
     * widest real combination (type + Privileged + x86 only + No in-place
     * update) is ~282px against a ~365px chip lane at four columns.
     */
```

**`[749]`** `frontend/src/components/StoreCard.tsx:243` &middot; **98w → 50w** (49% cut) &middot; _surprising_  
Keep the invalid-nesting rule and the truncation reason, cut what the JSDoc above says.

<details><summary>before</summary>

```
/* NO NESTED INTERACTIVES. The card is not itself a control: it already
          contains a real Install button, and a control wrapping another
          control is invalid HTML that breaks keyboard and screen-reader
          behaviour. The title and "Read more" are two sibling buttons
          instead, so every control here is a sibling of the others and each
          is reachable by Tab in reading order.
          Both open the detail popup rather than navigating: buttons, not
          links, because they no longer go anywhere. Truncated to one line
          with the full name in `title`, since a wrapping name would eat into
          the fixed height. */
```

</details>

**after**

```
      {/* NO NESTED INTERACTIVES. A control wrapping another control is
          invalid HTML that breaks keyboard and screen-reader behaviour, so the
          title and "Read more" are sibling buttons, each reachable by Tab.
          Truncated to one line with the full name in `title`, since a wrapping
          name would eat into the fixed height. */}
```

**`[750]`** `frontend/src/components/StoreCard.tsx:259` &middot; **104w → 68w** (35% cut) &middot; _surprising_  
Keep the fixed box and the --panel fade trick, cut the theme worked example.

<details><summary>before</summary>

```
/* Exactly three lines, always, whether the text needs them or not:
          a fixed box is what makes the rows line up.

          The fade is painted from --panel, the card's own background, to
          transparent, which is also why it needs no "is it actually
          overflowing" condition. Over clipped text it reads as a fade; over
          the empty space of a short or missing description it is the card
          colour drawn on the card colour, i.e. invisible. Using the token
          rather than a literal is what keeps that true in both themes, since
          --panel is #121924 in the dark one and #FFFFFF in the light one. */
```

</details>

**after**

```
      {/* Exactly three lines, always, whether the text needs them or not: a
          fixed box is what makes the rows line up.

          The fade is painted from --panel, the card's own background, so it
          needs no "is it overflowing" condition: over clipped text it reads as
          a fade, over empty space it is the card colour on the card colour,
          and the token keeps that true in both themes. */}
```

**`[751]`** `frontend/src/components/StoreCard.tsx:274` &middot; **40w → 20w** (50% cut) &middot; _narration_  
Keep why an empty-description card still earns the link, cut the request history.

<details><summary>before</summary>

```
/* On every card, including the 7 with no description at all: the user
          asked for it unconditionally, for visual consistency, and it is
          honest even on those rows because the detail page still carries
          their availability, resource defaults and popularity. */
```

</details>

**after**

```
      {/* On every card, including the 7 with no description: the detail page
          still carries their availability, resource defaults and
          popularity. */}
```

**`[752]`** `frontend/src/components/StoreCard.tsx:278` &middot; **288w → 118w** (59% cut) &middot; _measurement-dump_  
Keep the one-row rule, the phone wrap it avoids and the truncation, cut the width table.

<details><summary>before</summary>

```
/* Read more and the action share ONE row, which is where the height
          came from: it deletes a whole row plus its margin, and moves Install
          up, which is what was asked for.

          It does NOT go on the chip row, and that was measured rather than
          assumed. The widest real chip combination (type + Privileged + x86
          only + No in-place update) is ~281px, and an xs Install is ~53px
          plus an 8px gap. Against the chip lane that is 342 vs 365 at four
          columns (fits), 342 vs 343 at three (fits by one pixel, which is
          inside the error of these estimates), and 342 vs 295 on a
          single-column phone card, where it WRAPS. A wrapped chip row is the
          one thing a fixed height cannot absorb, so the chip row keeps the
          full width it needs to stay on one line, and the button sits here
          instead. On this row the same worst case is Read more (~54px) plus
          the control (~53px), which is 115px against that same 295px lane.

          All three action states share this row and it stays one line in each:
          - installable      the Install button, pushed right with ml-auto.
          - installed        the same slot, disabled.
          - NOT installable  the reason, which is the hard one. These strings
            are long, so it truncates with the FULL text in `title`, and the
            popup carries it complete in its Availability section. Truncating
            text whose full form is one click away is honest; wrapping it
            would make this card taller than every other card in its row.

          The upstream link stays. It is the only outward affordance a
          non-installable app has, it costs one shrink-0 element, and dropping
          it would be a capability removal dressed up as a layout change. */
```

</details>

**after**

```
      {/* Read more and the action share ONE row, which is where the height
          came from: it deletes a whole row plus its margin.

          It does NOT go on the chip row, and that was measured. The widest
          real chip combination plus an xs Install is ~342px, which fits at
          four and three columns but WRAPS against the ~295px lane of a
          single-column phone card, and a wrapped chip row is the one thing a
          fixed height cannot absorb.

          The not-installable reason is the hard state: those strings are long,
          so it truncates with the FULL text in `title` and the popup carries
          it complete. The upstream link stays, it is the only outward
          affordance a non-installable app has. */}
```

**`[753]`** `frontend/src/components/StoreCard.tsx:325` &middot; **52w → 38w** (27% cut) &middot; _test-reference_  
Keep the size and the touch-target caveat, drop the duplicate test locator.

<details><summary>before</summary>

```
/* size="xs" is the small size in ui/button.tsx: roughly 25px tall
             against md's ~35px, by request. Worth knowing: that is still well
             under the ~44px normally recommended for a touch target, so it is
             a deliberately small control on a touch screen. The LABEL is
             untouched: e2e/journey.spec.ts clicks
             getByRole('button', { name: 'Install', exact: true }). */
```

</details>

**after**

```
          /* size="xs" is the small size in ui/button.tsx, roughly 25px tall
             against md's ~35px, by request. That is well under the ~44px
             normally recommended for a touch target, so it is a deliberately
             small control on a touch screen. */
```

**`[754]`** `frontend/src/components/StoreCard.tsx:332` &middot; **37w → 26w** (30% cut) &middot; _surprising_  
Keep why the badge never removes the action, cut the worked example.

<details><summary>before</summary>

```
/* Status, not a control: it reports what exists and never takes
                the action away. The count is the useful half once two copies
                are the point, since "Installed" alone cannot answer "is the
                prod one already there". */
```

</details>

**after**

```
            {/* Status, not a control: it reports what exists and never takes
                the action away. The count is the useful half once two copies
                are the point. */}
```

**`[755]`** `frontend/src/components/StoreCard.tsx:342` &middot; **14w → 14w** (0% cut) &middot; _test-reference_  
Keep the label invariant, drop the spec path and locator.

<details><summary>before</summary>

```
/* Label stays exactly "Install" in every state: e2e/journey.spec.ts
                clicks getByRole('button', { name: 'Install', exact: true }). */
```

</details>

**after**

```
            {/* The label stays exactly "Install" in every state; automated
                flows match that exact name. */}
```

**`[756]`** `frontend/src/components/StoreCard.tsx:375` &middot; **63w → 32w** (49% cut) &middot; _surprising_  
Keep why the spacer must stay, cut the size it used to hold.

<details><summary>before</summary>

```
/* Whatever is left over, which is now a few pixels rather than the ~34
          this used to hold. It stays because it is the drift absorber that
          keeps all three action states at one height: the not-installable arm
          is text (~17px) where the other two are a ~25px control, and this
          swallows that 8px difference instead of letting it reach the card
          edge. */
```

</details>

**after**

```
      {/* Whatever is left over. It is the drift absorber that keeps all three
          action states at one height: the not-installable arm is text (~17px)
          where the other two are a ~25px control. */}
```

**`[757]`** `frontend/src/components/StoreCard.tsx:386` &middot; **114w → 57w** (50% cut) &middot; _test-reference_  
Keep the must-match-240px rule and the block rhythm, drop the harness command.

<details><summary>before</summary>

```
/**
 * StoreCard's placeholder.
 *
 * The easiest of the four to get right and the one it matters most for: the
 * real card is `h-[240px]` and so is this, so the Store grid does not resize
 * when the catalog lands. e2e/harness/main.tsx renders it beside the real
 * card at every viewport width, and `npm run harness` fails on unequal
 * heights among `.rounded-card` matches, so that equality is checked in real
 * Chromium rather than asserted from a class name.
 *
 * The internal rhythm is the card's own budget, block for block: 40px header,
 * name, category, the fixed 53px three-line description box, the action row
 * (~25px xs Button), the chip row, and the same `flex-1` spacer soaking up
 * what is left.
 */
```

</details>

**after**

```
/**
 * StoreCard's placeholder.
 *
 * `h-[240px]`, the same as the real card, so the Store grid does not resize
 * when the catalog lands; that equality is checked in real Chromium rather
 * than asserted from a class name.
 *
 * The internal rhythm is the card's own budget block for block, down to the
 * fixed 53px description box and the same `flex-1` spacer.
 */
```


### 🟢 KEEP (4), unchanged

- **`[758]`** `137` &middot; _contract_ &middot; `/** Opens the detail popup. The card navigates nowhere: the same content is`
- **`[759]`** `167` &middot; _surprising_ &middot; `// A pointer that travelled is a text selection, not a click. 4px of slop`
- **`[760]`** `406` &middot; _surprising_ &middot; `/* The install count: a 23px glyph beside a 14px figure. */`
- **`[761]`** `418` &middot; _surprising_ &middot; `/* size="xs" Button: py-1.5 around a 9px line box, ~25px tall. */`

---

## `frontend/src/components/BellPopover.tsx`

2,359 → 1,393 words, 41% cut. 1 delete, 33 shorten, 7 keep.


### 🔴 DELETE (1)

**`[762]`** `frontend/src/components/BellPopover.tsx:212` &middot; 24w &middot; _implementation-diary_  
Describes what this code used to do and points at a value rendered elsewhere.

```
// A running job's percent used to be folded in here as plain text; it now
// renders as NotificationCard's own ring (see `progress` below) instead.
```


### 🟡 SHORTEN (33)

**`[763]`** `frontend/src/components/BellPopover.tsx:25` &middot; **25w → 23w** (8% cut) &middot; _narration_  
The first-paint-only fact is the point; the pointer to useFittingCount is a line away.

<details><summary>before</summary>

```
/** Rough height of the shortest possible card plus its gap. Only used for the
 *  first paint, before the real cards can be measured: see useFittingCount. */
```

</details>

**after**

```
/** Rough height of the shortest possible card plus its gap, used only for the
 *  first paint, before the real cards can be measured. */
```

**`[764]`** `frontend/src/components/BellPopover.tsx:29` &middot; **30w → 23w** (23% cut) &middot; _narration_  
Keeps what the 96px accounts for in half the words.

<details><summary>before</summary>

```
/** How much of the viewport the popover cannot use: the topbar it hangs from,
 *  its own sideOffset, and a margin so the last card is not flush to the edge. */
```

</details>

**after**

```
/** How much of the viewport the popover cannot use: the topbar it hangs from,
 *  its sideOffset, and a margin below the last card. */
```

**`[765]`** `frontend/src/components/BellPopover.tsx:33` &middot; **115w → 69w** (40% cut) &middot; _implementation-diary_  
Keeps the variable-height reason, the loop guard and the jsdom quirk; cuts the convergence essay.

<details><summary>before</summary>

```
/** How many cards fit in the window, measured rather than guessed.
 *
 *  Card height is not constant (a failure's message wraps to however many
 *  lines its error needs), so dividing by a fixed constant either clips the
 *  last card or wastes a slot. This estimates on the first paint, then measures
 *  the cards actually rendered and settles on the real number.
 *
 *  It converges in one extra pass because a card's height does not depend on
 *  how many are shown; the guard against setting an unchanged value is what
 *  stops a resize from looping.
 *
 *  In jsdom every offsetHeight is 0, so the measurement is skipped entirely and
 *  the ceiling stands: tests assert on MAX_VISIBLE, not on layout. */
```

</details>

**after**

```
/** How many cards fit in the window, measured rather than guessed.
 *
 *  Card height is not constant (a failure's message wraps to however many
 *  lines its error needs), so a fixed divisor either clips the last card or
 *  wastes a slot. The guard against setting an unchanged value is what stops a
 *  resize from looping.
 *
 *  In jsdom every offsetHeight is 0, so the measurement is skipped and the
 *  ceiling stands. */
```

**`[766]`** `frontend/src/components/BellPopover.tsx:54` &middot; **56w → 37w** (34% cut) &middot; _buried-invariant_  
Keeps the anti-oscillation invariant and the reset-on-resize rule, drops the worked example.

<details><summary>before</summary>

```
/** The count that was tried and did not fit, at one particular window height.
   *  Without it, growth and shrink fight: adding a card that overflows shrinks
   *  back, leaving room that looks like space for another card, which gets
   *  added, which overflows. Forgotten as soon as the window resizes, because a
   *  different height deserves a fresh attempt. */
```

</details>

**after**

```
  /** The count that was tried and did not fit, at one particular window height.
   *  Without it, growth and shrink fight: a card that overflows shrinks back,
   *  leaving room that looks like space for another. Forgotten on resize. */
```

**`[767]`** `frontend/src/components/BellPopover.tsx:82` &middot; **23w → 20w** (13% cut) &middot; _buried-invariant_  
Same guard stated in fewer words.

<details><summary>before</summary>

```
// Overflowed. Shrink to what actually fits, and remember that one more
// than that does not, so the growth branch cannot immediately undo it.
```

</details>

**after**

```
        // Overflowed. Shrink to what fits, and remember that one more does
        // not, so the growth branch cannot immediately undo it.
```

**`[768]`** `frontend/src/components/BellPopover.tsx:90` &middot; **89w → 42w** (53% cut) &middot; _implementation-diary_  
Keeps why growth goes one card at a time, cuts the story of the old one-way ratchet.

<details><summary>before</summary>

```
// Everything rendered fits, so the window may have grown. The loop above
// can only count cards that are RENDERED, which is why shrinking used to
// be a one-way ratchet: the measurement was bounded by its own previous
// result, so a window that grew back had nothing new to measure.
//
// Growing one at a time re-renders, re-measures, and either keeps going
// or trips the block above. That converges without guessing the next
// card's height, which is unknowable in advance: a failure's message
// wraps to however many lines its error needs.
```

</details>

**after**

```
      // Everything rendered fits, so the window may have grown. The loop above
      // can only count cards that are RENDERED, so growing one at a time is
      // what gives it something new to measure. The next card's height cannot
      // be guessed in advance.
```

**`[769]`** `frontend/src/components/BellPopover.tsx:122` &middot; **125w → 40w** (68% cut) &middot; _implementation-diary_  
Design essay weighing EmptyState and a shared variant; the sizing rule is the part that binds.

<details><summary>before</summary>

```
/** The tray's own empty/error placeholder, sized to sit alongside the
 *  NotificationCards it stands in for rather than EmptyState's page-level
 *  `py-20`. EmptyState is a page-level component (11 other callers rely on
 *  that full-height treatment for a whole route going empty); this tray is a
 *  400px popover, and the same box read as a mostly blank rectangle far
 *  taller than any card it replaced. Local to this file rather than a variant
 *  on EmptyState: nothing else needs a compact empty state today, and a
 *  shared variant would be speculative reuse for a problem this file alone
 *  has. Borrows NotificationCard's own chrome (rounded-ctl, border-line,
 *  bg-panel, shadow) so it reads as a card that happens to hold a message
 *  instead of a shape borrowed from a page it isn't. */
```

</details>

**after**

```
/** The tray's own empty/error placeholder, sized to sit alongside the
 *  NotificationCards it stands in for rather than EmptyState's page-level
 *  `py-20`, which read as a mostly blank rectangle inside a 400px popover.
 *  Borrows NotificationCard's chrome so it reads as a card. */
```

**`[770]`** `frontend/src/components/BellPopover.tsx:142` &middot; **69w → 26w** (62% cut) &middot; _implementation-diary_  
The block documents a past decision, not severityOf; only the no-mark-read fact survives.

<details><summary>before</summary>

```
/** One notification, as a card.
 *
 *  The user asked for notification cards rather than a list, so this renders
 *  the same NotificationCard the live toasts use (same four severities, same
 *  x) instead of the bespoke row this popover shipped with. Dismiss hides the
 *  card locally: /jobs is a server-side record, not an inbox, so there is
 *  nothing to mark read; the x clears it from view until the query refetches.
 */
```

</details>

**after**

```
/** Card severity from a job's status. Dismiss hides the card locally: /jobs is
 *  a server-side record, not an inbox, so there is nothing to mark read. */
```

**`[771]`** `frontend/src/components/BellPopover.tsx:157` &middot; **127w → 69w** (46% cut) &middot; _implementation-diary_  
Keeps the every-branch-names-the-action rule and the null-verb fallback, cuts the bug retelling.

<details><summary>before</summary>

```
/** The message. A failure's reason is the message; anything else states what
 *  happened in a sentence rather than making the reader infer it from a kind
 *  string.
 *
 *  Every branch names the ACTION as well as the target. "Finished on
 *  anytype-server on node1" said what was acted on and never what was done to
 *  it, which is not a sentence, and it doubled the "on" once target_name began
 *  carrying "<guest> on <node>". With the verb in place the same row reads
 *  "Finished installing anytype-server on node1".
 *
 *  `verb` is null for a job kind nobody has written a gerund for, and the
 *  fallbacks below are then the exact sentences this function always wrote.
 *  New kinds arrive backend-side regularly, and a plainer sentence is a better
 *  failure than invented English. */
```

</details>

**after**

```
/** The message. A failure's reason is the message; anything else states what
 *  happened in a sentence. Every branch names the ACTION as well as the target,
 *  or the row reads "Finished on anytype-server on node1", which doubles the
 *  "on" now that target_name carries "<guest> on <node>". `verb` is null for a
 *  kind nobody has written a gerund for, and new kinds arrive regularly: the
 *  plainer fallback beats invented English. */
```

**`[772]`** `frontend/src/components/BellPopover.tsx:204` &middot; **48w → 26w** (46% cut) &middot; _implementation-diary_  
The rule is what the footer carries; the label/value table it replaced is history.

<details><summary>before</summary>

```
/** One line of context under the message. Trimmed from a label/value table
 *  that carried status, requester and schedule too: that much detail buried
 *  the message it was there to support. What survives is what you actually
 *  scan for: what it touched, how far along, and how long ago. */
```

</details>

**after**

```
/** One line of context under the message: what it touched, how far along, and
 *  how long ago. More detail than that buried the message it supports. */
```

**`[773]`** `frontend/src/components/BellPopover.tsx:226` &middot; **58w → 48w** (17% cut) &middot; _contract_  
Keeps both dismissal mechanisms and the unloaded-state default, drops the cross-reference.

<details><summary>before</summary>

```
/** A job's id counts as already cleared if it is at or below the watermark
 *  ("clear all" as of some earlier moment) or sits in the small list of
 *  individually dismissed ids above it. `state` is undefined before the
 *  first load: nothing is hidden yet rather than everything, the same
 *  fail-open-to-visible choice jobsQuery.data ?? [] makes elsewhere in this
 *  file. */
```

</details>

**after**

```
/** A job's id counts as already cleared if it is at or below the watermark
 *  ("clear all" as of some earlier moment) or sits in the small list of
 *  individually dismissed ids above it. `state` is undefined before the first
 *  load: nothing is hidden yet rather than everything. */
```

**`[774]`** `frontend/src/components/BellPopover.tsx:238` &middot; **60w → 42w** (30% cut) &middot; _narration_  
Keeps the popover-not-DropdownMenu accessibility reason, drops the drawer history.

<details><summary>before</summary>

```
/**
 * The bell's popover: what the activity drawer used to show, without the
 * full-height sheet. Reads GET /jobs, which is the one source carrying the
 * `error` field this surface has to show.
 *
 * A popover rather than DropdownMenu: this list holds buttons (Cancel) and
 * an expandable log, and DropdownMenu's role="menu" semantics hijack arrow
 * keys and expect role="menuitem" children, neither of which fits.
 */
```

</details>

**after**

```
/**
 * The bell's popover, over GET /jobs, the one source carrying the `error` field
 * this surface has to show.
 *
 * A popover rather than DropdownMenu: this list holds buttons and an expandable
 * log, and DropdownMenu's role="menu" semantics hijack arrow keys and expect
 * role="menuitem" children.
 */
```

**`[775]`** `frontend/src/components/BellPopover.tsx:249` &middot; **34w → 32w** (6% cut) &middot; _contract_  
Keeps the key format and why it is unified, in fewer words.

<details><summary>before</summary>

```
// Keyed by TrayItem.id ('job:<id>', 'action:...', 'alert:...'), not a
// job's numeric id: the tray now holds more than jobs, and unifying the
// key lets one dismiss handler (and one Clear all) cover all of it.
```

</details>

**after**

```
  // Keyed by TrayItem.id ('job:<id>', 'action:...', 'alert:...'), not a job's
  // numeric id: the tray holds more than jobs, and one key lets one dismiss
  // handler and one Clear all cover all of it.
```

**`[776]`** `frontend/src/components/BellPopover.tsx:253` &middot; **37w → 23w** (38% cut) &middot; _implementation-diary_  
Keeps that this is the only path to a job's events, drops the deleted-drawer history.

<details><summary>before</summary>

```
// Which job's transcript is open. Deleting the drawer took the only path to
// GET /jobs/{id}/events for a job you did not start in this session; this is
// that path, without turning the cards back into a list.
```

</details>

**after**

```
  // Which job's transcript is open. This is the only path to
  // GET /jobs/{id}/events for a job you did not start in this session.
```

**`[777]`** `frontend/src/components/BellPopover.tsx:262` &middot; **50w → 32w** (36% cut) &middot; _buried-invariant_  
Keeps the two effects of setTrayOpen, trims the justification.

<details><summary>before</summary>

```
// Opening marks "now" as seen (the badge counts what arrived since),
// and tells NotificationSurface to stay quiet while the tray itself is
// showing the same information -- there is nothing the brief banner
// could add, and it must never sit on top of the popover the user
// already opened by hand.
```

</details>

**after**

```
    // Opening marks "now" as seen (the badge counts what arrived since) and
    // tells NotificationSurface to stay quiet: a banner must never sit on top
    // of the popover the user opened by hand.
```

**`[778]`** `frontend/src/components/BellPopover.tsx:270` &middot; **87w → 44w** (49% cut) &middot; _external-quirk_  
The Radix alignOffset direction quirk is the load-bearing half; the rest is setup.

<details><summary>before</summary>

```
/** align="end" pins the cards to the BELL's right edge, and the bell is not
   *  the rightmost control (the account menu is), so that left a wide gap.
   *
   *  alignOffset shifts along the alignment axis, and for align="end" it runs
   *  toward the START: a positive value moves the cards further LEFT, deeper
   *  into the window, which is the opposite of what is wanted here. Hence the
   *  negation. Measured, not hardcoded, so a longer display name in the
   *  account menu or a different tier pill cannot put it back out. */
```

</details>

**after**

```
  /** align="end" pins the cards to the BELL's right edge, and the bell is not
   *  the rightmost control, so that left a wide gap. alignOffset runs toward
   *  the START for align="end", so a positive value moves the cards LEFT: hence
   *  the negation. Measured, not hardcoded. */
```

**`[779]`** `frontend/src/components/BellPopover.tsx:294` &middot; **77w → 37w** (52% cut) &middot; _implementation-diary_  
Keeps the badge rule and the failure that proves it, cuts the list of what it used to be.

<details><summary>before</summary>

```
// The badge counts exactly what the tray holds, nothing cleverer. It has
// been two other things: running jobs only, then running jobs plus an unread
// tally. Both meant the number on the icon described something other than the
// list behind it, which is the confusion this tray exists to remove, and the
// unread version read as broken because a quiet page with no jobs in flight
// sat at zero while the tray plainly had items in it.
```

</details>

**after**

```
  // The badge counts exactly what the tray holds, nothing cleverer. An unread
  // tally instead read as broken, because a quiet page with no jobs in flight
  // sat at zero while the tray plainly had items in it.
```

**`[780]`** `frontend/src/components/BellPopover.tsx:302` &middot; **74w → 47w** (36% cut) &middot; _data-integrity_  
Keeps the do-not-re-sort rule and the exact tie bug, trims the restatement.

<details><summary>before</summary>

```
// GET /jobs already orders newest-first server-side. Do not re-sort here:
// string-comparing ISO created_at timestamps client-side reproduces the
// zero-microsecond tie bug the backend explicitly avoids (a bare 'Z' sorts
// after a fractional-second suffix like '.123456Z', so a zero-microsecond
// row would sort as newer than a genuinely later same-second row).
// Always enabled, not only while open: the badge counts what the tray holds,
// and it cannot know that if the list is only fetched on opening.
```

</details>

**after**

```
  // GET /jobs already orders newest-first server-side. Do not re-sort here:
  // string-comparing ISO created_at reproduces the zero-microsecond tie bug the
  // backend explicitly avoids, since a bare 'Z' sorts after a fractional suffix
  // like '.123456Z'. Always enabled, not only while open, because the badge
  // counts what the tray holds.
```

**`[781]`** `frontend/src/components/BellPopover.tsx:312` &middot; **52w → 33w** (37% cut) &middot; _test-reference_  
Keeps why the state is server-side and what it does not cover, drops the pointer to a report file.

<details><summary>before</summary>

```
// Server-side memory of what THIS user already cleared, so a clear
// survives a reload, a reboot, and a login from a different browser (the
// requirement `dismissed` alone -- component state -- cannot meet; see
// .superpowers/sdd/persist-cleared-notifications-report.md). Only job-
// backed items are covered: a store item is already gone on reload, see
// isPersistedDismissed and dismissItem/clearAll below.
```

</details>

**after**

```
  // Server-side memory of what THIS user already cleared, so a clear survives
  // a reload, a reboot, and a login from another browser, which component state
  // alone cannot do. Only job-backed items are covered.
```

**`[782]`** `frontend/src/components/BellPopover.tsx:325` &middot; **101w → 49w** (51% cut) &middot; _implementation-diary_  
Keeps the status-in-title rule and the no-primary-key rule, cuts the examples.

<details><summary>before</summary>

```
// Status in the title, not only in severityOf's colour: a card headed
// "App Uninstall" over a red icon leaves the reader working out from the
// colour alone whether the container is gone. actionLabel spells it out,
// "App Uninstall Failed".
//
// No "#12" after it. That was the jobs table's primary key, which means
// nothing to the person reading the tray and made every routine
// housekeeping card read as "Usage Cleanup #215", as though the number
// were a version or a count worth noticing. The row still needs a stable
// identity, and it has one: TrayItem.id above is `job:<id>`, which is not
// rendered.
```

</details>

**after**

```
    // Status in the title, not only in severityOf's colour: a card headed
    // "App Uninstall" over a red icon leaves the reader working out whether the
    // container is gone. actionLabel spells it out. No "#12" after it: that is
    // the jobs table's primary key and means nothing to the reader.
```

**`[783]`** `frontend/src/components/BellPopover.tsx:344` &middot; **76w → 53w** (30% cut) &middot; _buried-invariant_  
Keeps why alerts are read from the server and why the severity mapping is shared.

<details><summary>before</summary>

```
// Firing alerts, from the server rather than only from SSE. A host the poller
// cannot reach and a cluster that has lost quorum both raise one (both have
// seeded rules), and until this was here they reached the tray only if the tab
// happened to be open when the event fired, and vanished on reload. The
// severity mapping is `alertToastSeverity`, the same one LiveProvider uses, so
// one alert cannot look different before and after a refresh.
```

</details>

**after**

```
  // Firing alerts read from the server, not only from SSE: otherwise an
  // unreachable host or a lost quorum reached the tray only if the tab was open
  // when the event fired, and vanished on reload. `alertToastSeverity` is the
  // same mapping LiveProvider uses, so an alert cannot look different before
  // and after a refresh.
```

**`[784]`** `frontend/src/components/BellPopover.tsx:361` &middot; **32w → 21w** (34% cut) &middot; _concurrency_  
Same double-delivery fact, fewer words.

<details><summary>before</summary>

```
// A job delivered once over SSE (LiveProvider pushes it into the store the
// instant it lands) and again the next time GET /jobs is polled must
// render once, not twice; see notificationMerge.ts.
```

</details>

**after**

```
  // A job delivered once over SSE and again on the next GET /jobs poll must
  // render once, not twice; see notificationMerge.ts.
```

**`[785]`** `frontend/src/components/BellPopover.tsx:368` &middot; **149w → 73w** (51% cut) &middot; _implementation-diary_  
Keeps the incomplete-beats-wrong rule and the isPending-only rule, cuts the essay about the earlier reasoning.

<details><summary>before</summary>

```
// Fail open on the LIST, hold on the FILTER. isPersistedDismissed answers
// false for every id until GET /dismissed lands, which is the right default
// for a request that FAILED (better to show a notification twice than to
// swallow one), and the wrong one while it is merely in flight: for that
// moment the tray and the badge bring back everything the operator has
// already cleared, then take it away again on the next paint.
//
// The distinction the original reasoning missed is that fail-open on
// jobsQuery and fail-open here are not the same choice. An unloaded job list
// showing nothing is incomplete. An unloaded dismissal list showing cleared
// items is WRONG: it is news the operator already dealt with, presented as
// current. Incomplete beats wrong, so the count waits.
//
// Only `isPending`. A dismissal query that has errored keeps the old
// fail-open behaviour, deliberately, because then the state is not coming.
```

</details>

**after**

```
  // Fail open on the LIST, hold on the FILTER. isPersistedDismissed answers
  // false for every id until GET /dismissed lands, which is right for a request
  // that FAILED and wrong while one is in flight: for that moment the tray and
  // the badge bring back everything the operator already cleared. Incomplete
  // beats wrong, so the count waits, but only on `isPending`: an ERRORED
  // dismissal query keeps fail-open, because then the state is not coming.
```

**`[786]`** `frontend/src/components/BellPopover.tsx:385` &middot; **32w → 28w** (12% cut) &middot; _narration_  
Same rule, fewer words.

<details><summary>before</summary>

```
// The fit loop needs to know how many cards COULD be shown, or it would keep
// trying to grow past the end of the list on a tall window with few jobs.
```

</details>

**after**

```
  // The fit loop needs to know how many cards COULD be shown, or it grows past
  // the end of the list on a tall window with few jobs.
```

**`[787]`** `frontend/src/components/BellPopover.tsx:389` &middot; **76w → 49w** (36% cut) &middot; _buried-invariant_  
Keeps the optimistic-hide and never-roll-back rules, trims the justification.

<details><summary>before</summary>

```
// `dismissed` hides the card the instant it is clicked, before the write
// below has landed -- the round trip must never be what the user waits on.
// It is also never rolled back if that write fails: a card that vanished
// and then reappeared moments later, unexplained, would be worse than one
// that stays gone but risks not surviving a reload. notify.error is the
// "not silently" half of that: the failure is surfaced, the hide is not.
```

</details>

**after**

```
  // `dismissed` hides the card the instant it is clicked: the round trip must
  // never be what the user waits on. It is never rolled back if that write
  // fails, since a card that vanished and reappeared unexplained is worse than
  // one that stays gone. notify.error surfaces the failure instead.
```

**`[788]`** `frontend/src/components/BellPopover.tsx:431` &middot; **46w → 27w** (41% cut) &middot; _narration_  
Keeps the hide-at-zero rule and the text-ink reason, drops the parenthetical.

<details><summary>before</summary>

```
/* Red, and only when there is something to see: a badge showing 0 is
            a badge that has stopped meaning anything. text-ink rather than a
            literal, so the number stays legible on --red in both themes (ink is
            near black on dark, near white on light). */
```

</details>

**after**

```
        {/* Red, and only when there is something to see: a badge showing 0
            has stopped meaning anything. text-ink keeps the number legible on
            --red in both themes. */}
```

**`[789]`** `frontend/src/components/BellPopover.tsx:443` &middot; **48w → 31w** (35% cut) &middot; _implementation-diary_  
Keeps the no-panel-no-header rule, cuts the retelling.

<details><summary>before</summary>

```
/* No panel, no header: a bordered box titled "Activity" wrapping the
            cards read as an activity list, which is the one thing this was
            asked not to be. The Content is a transparent, borderless column
            and each card is its own floating surface: the cards ARE the
            popover. */
```

</details>

**after**

```
        {/* No panel, no header: a bordered box titled "Activity" around the
            cards read as an activity list, the one thing this was asked not to
            be. The cards ARE the popover. */}
```

**`[790]`** `frontend/src/components/BellPopover.tsx:456` &middot; **183w → 83w** (55% cut) &middot; _implementation-diary_  
Keeps the Radix focus quirk and the keyboard reason, cuts the two-or-more-cards anecdote.

<details><summary>before</summary>

```
// Radix moves focus to the first TABBABLE element of the content when
// the popover opens, and a NotificationCard's icon-only controls open
// their tooltip on FOCUS as well as on hover (deliberately: that is
// how a keyboard user reads a button that is only an icon). With one
// card in the tray the first tabbable is that card's "View log", so
// merely clicking the bell popped its tooltip with the pointer nowhere
// near it. Two or more cards happened to hide it, because then the
// "Clear all" button is first and has no tooltip.
//
// Focus the content ITSELF instead. Radix's FocusScope puts
// tabIndex={-1} on this same element (it is `asChild`, so its props
// land on the node listRef points at), and the container precedes its
// own children in tab order, so one Tab still walks into the cards and
// the tooltip still appears for the keyboard user it exists for.
// Focus is deliberately still moved INTO the popover rather than left
// on the bell: leaving it on the trigger would tab into the rest of
// the topbar instead of into the notifications just opened.
```

</details>

**after**

```
          // Radix moves focus to the first TABBABLE element of the content on
          // open, and a NotificationCard's icon-only controls open their tooltip
          // on FOCUS as well as hover, so clicking the bell popped a tooltip
          // with the pointer nowhere near it. Focusing the content ITSELF
          // avoids that: FocusScope already puts tabIndex={-1} here, and a
          // container precedes its children in tab order, so one Tab still
          // walks into the cards. Focus must stay INSIDE the popover; on the
          // bell it would tab into the topbar.
```

**`[791]`** `frontend/src/components/BellPopover.tsx:479` &middot; **55w → 33w** (40% cut) &middot; _narration_  
Keeps the rule that the states describe the merged list, trims the restatement.

<details><summary>before</summary>

```
/* An action notification (nothing to do with /jobs) has to show up
              here even if /jobs itself is loading or failed to load: the two
              sources are independent, and a fetch error on one must not hide
              the other. The loading/error/empty states below are therefore
              about the MERGED list being empty, not about jobsQuery alone. */
```

</details>

**after**

```
          {/* An action notification (nothing to do with /jobs) has to show up
              here even if /jobs is loading or failed: the two sources are
              independent. The states below are about the MERGED list. */}
```

**`[792]`** `frontend/src/components/BellPopover.tsx:495` &middot; **31w → 24w** (23% cut) &middot; _implementation-diary_  
Keeps why one card gets no Clear all, drops the sonner-era provenance.

<details><summary>before</summary>

```
/* Only shown from two cards up, mirroring the sonner-era
                  ClearAllToasts this replaces: one card already has its own
                  x, so a clear-all beside it would be two controls for one
                  action. */
```

</details>

**after**

```
              {/* Only from two cards up: one card already has its own x, so
                  a clear-all beside it would be two controls for one
                  action. */}
```

**`[793]`** `frontend/src/components/BellPopover.tsx:505` &middot; **29w → 19w** (34% cut) &middot; _surprising_  
Keeps the deliberate no-scrollbar rule that a reader would otherwise undo.

<details><summary>before</summary>

```
/* As many as fit, and no scrollbar: dismissing one is what
                  reveals the next, so the backlog drains through the x rather
                  than through a scroll nobody asked for. */
```

</details>

**after**

```
              {/* As many as fit, and no scrollbar: dismissing one reveals the
                  next, so the backlog drains through the x. */}
```

**`[794]`** `frontend/src/components/BellPopover.tsx:509` &middot; **33w → 31w** (6% cut) &middot; _buried-invariant_  
Keeps why a store-only item has no log, in fewer words.

<details><summary>before</summary>

```
// Only a job the /jobs poll has actually confirmed has a log
// to view; a store entry whose SSE delivery beat the next
// poll has no server-confirmed row yet to fetch one from.
```

</details>

**after**

```
                // Only a job the /jobs poll has confirmed has a log to view;
                // a store entry whose SSE delivery beat the next poll has no
                // server row to fetch one from.
```

**`[795]`** `frontend/src/components/BellPopover.tsx:533` &middot; **104w → 55w** (47% cut) &middot; _implementation-diary_  
Keeps why `fit` and why the Close button exists, cuts the 720px history.

<details><summary>before</summary>

```
/* `fit` instead of a width: the panel is a transcript viewer and the
          transcript decides how big it wants to be, up to 80vw/80vh. The 720
          it used to state was a guess that a one-line failure overshot and a
          long install run could not use.

          The Close button is the same ghost button every other JobLog dialog
          ends with (InstallDialog, MigrateDialog, HostPowerDialog, the VM
          wizard). This one shipped without it, so a log opened from the tray
          had Escape and the scrim and no visible way out at all. shrink-0
          keeps it out of the flexbox shrinking that the transcript above it
          absorbs. */
```

</details>

**after**

```
      {/* `fit` instead of a width: the transcript decides how big it wants to
          be, up to 80vw/80vh. The Close button is the same ghost button every
          other JobLog dialog ends with; without it a log opened from the tray
          had no visible way out. shrink-0 keeps it out of the flexbox shrinking
          the transcript absorbs. */}
```


### 🟢 KEEP (7), unchanged

- **`[796]`** `19` &middot; _contract_ &middot; `/** How close the cards sit to the right edge of the window. */`
- **`[797]`** `22` &middot; _contract_ &middot; `/** Hard ceiling on cards, however tall the window is. */`
- **`[798]`** `68` &middot; _external-quirk_ &middot; `// jsdom, or not laid out yet`
- **`[799]`** `190` &middot; _surprising_ &middot; `// Sentence-cased rather than a template, because the verb IS the first word`
- **`[800]`** `220` &middot; _contract_ &middot; `/** 0..100 for a job still running with a real figure, or undefined: never a`
- **`[801]`** `351` &middot; _contract_ &middot; `// Prefixed `alert:<id>` so notificationMerge can drop the SSE copy of the`
- **`[802]`** `453` &middot; _external-quirk_ &middot; `// Without this the shift above is clamped back by collision`

---

## `frontend/src/routes/store.tsx`

2,184 → 1,444 words, 34% cut. 1 delete, 32 shorten, 6 keep.


### 🔴 DELETE (1)

**`[803]`** `frontend/src/routes/store.tsx:468` &middot; 20w &middot; _narration_  
Justifies a label the reader can already see; the range line explains itself.

```
/* Prev/Next alone say nothing about where you are in 556
                    apps, so the position is spelled out rather than implied. */
```


### 🟡 SHORTEN (32)

**`[804]`** `frontend/src/routes/store.tsx:37` &middot; **38w → 33w** (13% cut) &middot; _contract_  
Keep why the name is read off the grid list, cut the rest.

<details><summary>before</summary>

```
/** The popup's title. Read off the list the grid already has rather than
 *  waiting on the detail fetch, so the dialog has a name from the moment it
 *  opens instead of flashing the slug and then correcting itself. */
```

</details>

**after**

```
/** The popup's title, read off the list the grid already has rather than
 *  waiting on the detail fetch, so the dialog has a name the moment it opens
 *  instead of flashing the slug. */
```

**`[805]`** `frontend/src/routes/store.tsx:56` &middot; **24w → 20w** (17% cut) &middot; _contract_  
Keep the allowlist rule and the fallback, cut the example.

<details><summary>before</summary>

```
/** Only a size actually on the menu survives, and the default is absence
 *  again, so an invented "?pageSize=7" falls back rather than being honoured. */
```

</details>

**after**

```
/** Only a size actually on the menu survives, and the default is absence
 *  again, so an invented "?pageSize=7" falls back. */
```

**`[806]`** `frontend/src/routes/store.tsx:64` &middot; **94w → 57w** (39% cut) &middot; _implementation-diary_  
Keep why there is no virtualizer and why the string is hoisted, cut the history.

<details><summary>before</summary>

```
// One page of cards, in the plain responsive grid the virtualizer used to
// emulate by hand. The virtualizer earned its keep when this rendered all
// ~556 LXC entries at once; a page is at most 100 cards, so the DOM cost is
// bounded by the page size and the measurement plumbing is just overhead.
// The auto-fill rule is derived at length inside StoreGrid below. It lives out
// here because the loading placeholder must lay out in the same grid, and a
// second copy of that string would be free to drift from the reasoning.
```

</details>

**after**

```
// One page of cards in a plain responsive grid. No virtualizer: a page is at
// most 100 cards, so the DOM cost is bounded by the page size. The rule itself
// is derived inside StoreGrid below and lives out here because the loading
// placeholder must lay out in the same grid, and a second copy would drift.
```

**`[807]`** `frontend/src/routes/store.tsx:77` &middot; **204w → 110w** (46% cut) &middot; _measurement-dump_  
Keep the derivation that pins 360px and the auto-fill rule, cut the worked variants.

<details><summary>before</summary>

```
/**
   * ONE auto-fill rule, no hand-written breakpoints, anchored so a 1080p
   * monitor shows exactly 4 columns.
   *
   * The arithmetic, so the next person can re-derive it rather than guess.
   * The grid does NOT get the viewport: AppShell.tsx renders
   * `<main className="min-w-0 flex-1 p-6">` beside a `w-[236px]` sidebar
   * (SidebarNav.tsx), so at a 1920px viewport the real lane is
   * 1920 - 236 - 48 = 1636px. With `gap-4` (16px), auto-fill gives
   * floor((lane + gap) / (min + gap)) columns, so 4 columns needs
   *     (1636+16)/5 < min+16 <= (1636+16)/4
   *     314px < min <= 397px
   * 360px sits mid-range rather than on either edge, which is what keeps
   * the answer at 4 when the lane moves: with the sidebar collapsed to
   * w-16 the lane is 1808px and it is still 4 (1824/376 = 4.85), and a
   * 15px classic scrollbar does not change it either.
   *
   * `min(360px, 100%)` rather than a bare 360px is the phone case: below
   * 360px of lane a bare minimum would make the track wider than its own
   * container and overflow the page. This caps the track at the container
   * and yields the one sensible column.
   *
   * auto-fill, not auto-fit: with auto-fit the empty tracks collapse, so a
   * filtered result of two apps would stretch into two enormous cards,
   * which is the opposite of the fixed-size cards this is here to give.
   */
```

</details>

**after**

```
  /**
   * ONE auto-fill rule, no hand-written breakpoints, anchored so a 1080p
   * monitor shows exactly 4 columns.
   *
   * The grid does not get the viewport: `<main className="min-w-0 flex-1 p-6">`
   * sits beside a `w-[236px]` sidebar, so a 1920px viewport leaves a 1636px
   * lane. With `gap-4`, auto-fill gives floor((lane + gap) / (min + gap))
   * columns, so 4 needs 314px < min <= 397px. 360px sits mid-range, so the
   * answer stays 4 when the lane moves.
   *
   * `min(360px, 100%)` is the phone case: below 360px of lane a bare minimum
   * makes the track wider than its container and overflows the page.
   *
   * auto-fill, not auto-fit: auto-fit collapses empty tracks, so a filtered
   * result of two apps would stretch into two enormous cards.
   */
```

**`[808]`** `frontend/src/routes/store.tsx:121` &middot; **71w → 48w** (32% cut) &middot; _data-integrity_  
Keep the shared key and why the grid row is not reused, cut the framing.

<details><summary>before</summary>

```
// The SAME query StoreDetailContent runs, by the same key, so this shares
// one cache entry and fires no second request. Reading it here rather than
// reusing the grid row matters: opening a card is one of the two moments the
// backend classifies a ct entry, so the grid's `installable` can still be
// null while the detail's is true. The pinned action has to agree with the
// Availability section it sits above.
```

</details>

**after**

```
  // The SAME query StoreDetailContent runs, by the same key, so this shares
  // one cache entry and fires no second request. Not the grid row: opening a
  // card is when the backend classifies a ct entry, so the grid's
  // `installable` can still be null while the detail's is true.
```

**`[809]`** `frontend/src/routes/store.tsx:129` &middot; **61w → 36w** (41% cut) &middot; _contract_  
Keep the LXC-only scope and where text search went, cut the plan reference.

<details><summary>before</summary>

```
// The Store is LXC-only (catalog expansion plan: non-LXC entries stay in
// the catalog table, tagged by type, and never render here), so this
// fetches the whole ct/ catalog once; the category chips are then an
// instant, client-side filter over that one list, and paging slices it.
// Text search is not here at all any more: it is the global palette's job.
```

</details>

**after**

```
  // The Store is LXC-only, so this fetches the whole ct catalog once; the
  // category chips are then an instant client-side filter over that one list,
  // and paging slices it. Text search is the global palette's job.
```

**`[810]`** `frontend/src/routes/store.tsx:143` &middot; **54w → 39w** (28% cut) &middot; _concurrency_  
Keep enqueue-versus-job and where the live deltas come from, cut the rest.

<details><summary>before</summary>

```
// POST /catalog/refresh only ENQUEUES the job, so the mutation's isPending
// covers the enqueue and nothing else. The work itself is the job, followed
// here through useJob: its ['jobs', id] cache entry is patched live by the
// one SSE stream the app already has (api/live.ts::applyJob), which carries
// a delta for every ctx.progress() the handler emits.
```

</details>

**after**

```
  // POST /catalog/refresh only ENQUEUES the job, so the mutation's isPending
  // covers the enqueue and nothing else. The work is the job, followed through
  // useJob: its ['jobs', id] cache entry is patched live by the app's one SSE
  // stream (api/live.ts::applyJob).
```

**`[811]`** `frontend/src/routes/store.tsx:152` &middot; **39w → 27w** (31% cut) &middot; _surprising_  
Keep why a failed job also clears, cut the trailing case.

<details><summary>before</summary>

```
// Terminal is terminal, succeeded or failed alike: let go of the job so
// the bar disappears instead of parking forever at whatever percentage
// the run died on. A job row we cannot read at all is treated the same.
```

</details>

**after**

```
    // Terminal is terminal, succeeded or failed alike: let go of the job so
    // the bar disappears instead of parking forever at whatever percentage the
    // run died on.
```

**`[812]`** `frontend/src/routes/store.tsx:159` &middot; **27w → 24w** (11% cut) &middot; _concurrency_  
Keep the single-flight rule, trim the wording.

<details><summary>before</summary>

```
// Both Refresh buttons drive this one job, so neither can start a second
// one while the first is still running, and there is only ever one bar.
```

</details>

**after**

```
  // Both Refresh buttons drive this one job, so neither can start a second
  // while the first runs, and there is only ever one bar.
```

**`[813]`** `frontend/src/routes/store.tsx:162` &middot; **27w → 26w** (4% cut) &middot; _surprising_  
Keep why a denied refresh shows nothing, trim the wording.

<details><summary>before</summary>

```
// No bar for a refresh the plan does not include: that POST is going to
// 403 and there will be no job behind it to report on.
```

</details>

**after**

```
  // No bar for a refresh the plan does not include: that POST is going to 403
  // and there is no job behind it to report on.
```

**`[814]`** `frontend/src/routes/store.tsx:169` &middot; **44w → 20w** (55% cut) &middot; _implementation-diary_  
Keep the shared query key, cut the was-hardcoded-false story.

<details><summary>before</summary>

```
// Same query key as cluster.tsx's unfiltered /apps fetch, so this shares one
// cache entry rather than adding a second request. Drives the real
// `installed` prop below, it used to be hardcoded false, which made
// StoreCard's tested "Installed" disabled state unreachable in the real page.
```

</details>

**after**

```
  // Same query key as cluster.tsx's unfiltered /apps fetch, so this shares one
  // cache entry rather than adding a second request.
```

**`[815]`** `frontend/src/routes/store.tsx:177` &middot; **70w → 44w** (37% cut) &middot; _redundant_  
Keep the catalog_slug keying, cut the rationale StoreCard's prop doc already carries.

<details><summary>before</summary>

```
// A COUNT per catalog entry, not a set of "has one". Installing a second
// copy is ordinary (a test one beside a prod one, or an operator's own
// naming scheme), so the card reports how many exist rather than hiding the
// Install button once one does. Keyed on catalog_slug: App.slug is the
// synthetic {catalog_slug}-{host_id}-{ctid} install identity, so counting on
// that would count every row exactly once and tell nobody anything.
```

</details>

**after**

```
  // A COUNT per catalog entry, not a set of "has one": a second copy is
  // ordinary, so the card reports how many exist. Keyed on catalog_slug,
  // because App.slug is the synthetic {catalog_slug}-{host_id}-{ctid} install
  // identity and counting on that would count every row exactly once.
```

**`[816]`** `frontend/src/routes/store.tsx:206` &middot; **42w → 27w** (36% cut) &middot; _contract_  
Keep the filter, sort, page order, cut the pointer to the other file.

<details><summary>before</summary>

```
// Sorted after filtering (cheaper, same answer) and before paging, so a page
// is a slice of the order the operator asked for rather than of the fetch
// order. NULLS LAST lives in sortEntries; see lib/store-order.ts for why
// this is client-side at all.
```

</details>

**after**

```
  // Sorted after filtering (cheaper, same answer) and before paging, so a page
  // is a slice of the order the operator asked for. NULLS LAST lives in
  // sortEntries.
```

**`[817]`** `frontend/src/routes/store.tsx:215` &middot; **68w → 33w** (51% cut) &middot; _narration_  
Keep the rule that paging lives in the URL, cut the argument for it.

<details><summary>before</summary>

```
// Page and page size live in the route's search params, next to category,
// so a reload, a bookmark and the back button all land on the page the
// operator was actually looking at. They are already navigating this page by
// URL for the category chip; paging is the same kind of state and it would
// be odd for it to be the one thing that evaporates on refresh.
```

</details>

**after**

```
  // Page and page size live in the route's search params, next to category,
  // so a reload, a bookmark and the back button all land on the page the
  // operator was actually looking at.
```

**`[818]`** `frontend/src/routes/store.tsx:222` &middot; **59w → 39w** (34% cut) &middot; _surprising_  
Keep clamping and why no effect renavigates, trim the wording.

<details><summary>before</summary>

```
// Clamped rather than corrected in place. A hand-edited or stale ?page= (a
// refresh can shrink the catalog under a deep link) shows the last real page
// instead of an empty grid, and the next Prev/Next click writes an honest
// number back. An effect that renavigated here would be one more thing that
// can loop with the user's own navigation.
```

</details>

**after**

```
  // Clamped rather than corrected in place. A hand-edited or stale ?page=
  // shows the last real page instead of an empty grid. An effect that
  // renavigated here would be one more thing that can loop with the user's
  // own navigation.
```

**`[819]`** `frontend/src/routes/store.tsx:233` &middot; **31w → 22w** (29% cut) &middot; _compatibility_  
Keep the jsdom reason for the optional call, cut the rest.

<details><summary>before</summary>

```
// Page 2 should start at the top of the grid, not wherever the click
// happened to leave the viewport. Optional call: jsdom has no
// scrollIntoView, and this is presentation, not behaviour.
```

</details>

**after**

```
    // Page 2 should start at the top of the grid. Optional call: jsdom has no
    // scrollIntoView, and this is presentation, not behaviour.
```

**`[820]`** `frontend/src/routes/store.tsx:239` &middot; **53w → 39w** (26% cut) &middot; _narration_  
Keep the reset rule and its one reason, cut the rest.

<details><summary>before</summary>

```
// Changing the page size resets to page 1 rather than trying to keep the
// first visible card in view. Picked for predictability: "show me 100" is a
// request to see the top of the list at a new density, and preserving a
// scroll offset across a re-paginate is guesswork the user cannot check.
```

</details>

**after**

```
  // Changing the page size resets to page 1: "show me 100" is a request to see
  // the top of the list at a new density, and preserving a scroll offset
  // across a re-paginate is guesswork the user cannot check.
```

**`[821]`** `frontend/src/routes/store.tsx:246` &middot; **39w → 34w** (13% cut) &middot; _surprising_  
Keep the empty-grid failure it prevents, trim the numbers to one.

<details><summary>before</summary>

```
// Every filter change drops back to page 1. Without this, narrowing a
// 23-page result set to a 2-page one while sitting on page 12 renders an
// empty grid that looks like "no results" and is really "no page 12".
```

</details>

**after**

```
  // Every filter change drops back to page 1. Without it, narrowing a 23-page
  // result while sitting on page 12 renders an empty grid that looks like "no
  // results" and is really "no page 12".
```

**`[822]`** `frontend/src/routes/store.tsx:259` &middot; **55w → 29w** (47% cut) &middot; _implementation-diary_  
Keep why the branch exists, cut the reconstruction of what it used to render.

<details><summary>before</summary>

```
/* The counts are all derived from `entries ?? []`, so before the
              catalog lands this line read "0 of 0 scripts installable (0
              unsupported)" directly above a grid of eight card placeholders:
              the page saying "there is nothing here" and "something is coming"
              at the same time. The source attribution is not waiting on
              anything and stays. */
```

</details>

**after**

```
          {/* Without this branch the counts, derived from `entries ?? []`,
              read "0 of 0 scripts installable" above a grid of placeholders.
              The source attribution is not waiting on anything and stays. */}
```

**`[823]`** `frontend/src/routes/store.tsx:271` &middot; **45w → 34w** (24% cut) &middot; _implementation-diary_  
Keep the isPending-is-false fact, cut the repeat of the line above.

<details><summary>before</summary>

```
// isPending is false in the error state, so these counts used to
// render from `entries ?? []` and state "0 of 0 scripts
// installable" as fact, directly above a grid correctly saying
// the catalog could not be read. The attribution is not waiting
// on anything and stays.
```

</details>

**after**

```
              // isPending is false in the error state, so these counts
              // would render from `entries ?? []` and state "0 of 0 scripts
              // installable" as fact above a grid that says the catalog could
              // not be read.
```

**`[824]`** `frontend/src/routes/store.tsx:286` &middot; **39w → 28w** (28% cut) &middot; _narration_  
Keep the silent-403 reason for the guard, cut the retelling.

<details><summary>before</summary>

```
/* Same refreshDenied guard as the banner's Refresh below. Without
            it this button 403'd in silence: useRefreshCatalog has no onError,
            and showRefreshBar is deliberately false for a denied refresh, so
            nothing on screen changed however many times it was clicked. */
```

</details>

**after**

```
        {/* Same refreshDenied guard as the banner's Refresh below. Without it
            this button 403s in silence: useRefreshCatalog has no onError and
            showRefreshBar is deliberately false for a denied refresh. */}
```

**`[825]`** `frontend/src/routes/store.tsx:295` &middot; **148w → 91w** (39% cut) &middot; _external-quirk_  
Keep the out-of-flow reason and the four values the backend emits, cut the essay.

<details><summary>before</summary>

```
/* Absolutely positioned, so it is out of flow and appearing or
            vanishing cannot move the header, the banner or the grid by a
            pixel. Anchored under the button that started it, with its own
            opaque panel background because it floats over whatever status
            line happens to be underneath.

            services/catalog.py::refresh_catalog reports four values and no
            others: 45 once discovery has returned, 85 once the upstream
            metadata sync has (on its failure path too, so a source that is
            down cannot strand the bar), 95 after mark_updates_available, and
            100 at the end. So this jumps in four steps rather than sweeping,
            and sits indeterminate for the couple of seconds before the first
            one lands. That is honest: the job publishes nothing in between,
            and inventing motion to fill the gap would be a lie about
            progress. Nothing here hardcodes those numbers; they are simply
            what the bar will be handed. */
```

</details>

**after**

```
        {/* Absolutely positioned, so appearing or vanishing cannot move the
            header, the banner or the grid by a pixel. Anchored under the
            button that started it, with its own opaque panel background
            because it floats over whatever status line is underneath.

            services/catalog.py::refresh_catalog reports four values and no
            others: 45 after discovery, 85 after the upstream metadata sync (on
            its failure path too, so a source that is down cannot strand the
            bar), 95 after mark_updates_available, 100 at the end. So this
            jumps in four steps and sits indeterminate until the first
            lands. */}
```

**`[826]`** `frontend/src/routes/store.tsx:339` &middot; **73w → 47w** (36% cut) &middot; _narration_  
Keep why this one is held open and the banner is not, cut the retelling.

<details><summary>before</summary>

```
/* Held open while /catalog/status answers. This line is only one 11px
          row, but it sits directly above the chip block and the grid, so its
          arrival pushed the whole page down a moment after it had settled.
          The stale banner above is not held open the same way: it is an
          exception that usually does not appear, and reserving room for
          something that probably is not coming is its own kind of jump. */
```

</details>

**after**

```
      {/* Held open while /catalog/status answers: one 11px row, but it sits
          directly above the chip block and the grid, so its arrival pushed the
          whole page down after it had settled. The stale banner above is not
          held open, because it usually does not appear at all. */}
```

**`[827]`** `frontend/src/routes/store.tsx:358` &middot; **57w → 40w** (30% cut) &middot; _narration_  
Keep where text search lives and why the chips stay, trim the detail.

<details><summary>before</summary>

```
/* No search box here any more. Text search over the store lives in the
          one global palette (Ctrl+K), which searches name, slug AND
          description server-side (backend/proxploy/api/search.py) rather than
          filtering the page's own already-fetched rows, and which reaches a
          store-only plan too. The category chips stay: they are a browse
          affordance over a fixed vocabulary, not a search. */
```

</details>

**after**

```
      {/* No search box here. Text search over the store lives in the global
          palette (Ctrl+K), which searches name, slug AND description
          server-side rather than filtering this page's already-fetched rows.
          The chips stay: they are a browse affordance, not a search. */}
```

**`[828]`** `frontend/src/routes/store.tsx:364` &middot; **68w → 43w** (37% cut) &middot; _surprising_  
Keep the reason Sort must be a block below, cut the restatement.

<details><summary>before</summary>

```
/* Two stacked rows, not one flex row: the categories are the real
          upstream vocabulary of 26, several of them long, so the chip block
          wraps to three or four lines at most widths. Sort therefore has to
          be a BLOCK BELOW that block rather than a flex sibling of it, which
          is the only way it lands under the last wrapped line instead of
          floating beside the first. */
```

</details>

**after**

```
      {/* Two stacked rows, not one flex row: the 26 upstream categories wrap
          to three or four lines at most widths, so Sort has to be a BLOCK
          BELOW the chip block to land under the last wrapped line instead of
          beside the first. */}
```

**`[829]`** `frontend/src/routes/store.tsx:371` &middot; **64w → 44w** (31% cut) &middot; _narration_  
Keep why eight and not 27, cut the second half.

<details><summary>before</summary>

```
/* `categories` is ['All'] until the catalog lands and 27 chips after
            it, which is three or four wrapped lines appearing at once and
            shoving the grid down. Eight is a deliberate under-estimate: the
            chips wrap, so a short placeholder settles UP into the real row
            rather than leaving a gap, and reserving all 27 would over-claim a
            vocabulary this page does not know yet. */
```

</details>

**after**

```
        {/* `categories` is ['All'] until the catalog lands and 27 chips after,
            which is three or four wrapped lines appearing at once. Eight is a
            deliberate under-estimate: the chips wrap, so a short placeholder
            settles UP into the real row rather than leaving a gap. */}
```

**`[830]`** `frontend/src/routes/store.tsx:379` &middot; **41w → 32w** (22% cut) &middot; _surprising_  
Keep the justification for an index key, trim the wording.

<details><summary>before</summary>

```
/* Keyed by index, not by `w`: the list repeats widths (w-20 and
                w-16 appear twice), so the class string is not unique. It is a
                fixed-length placeholder that never reorders, which is exactly
                the case an index key is correct for. */
```

</details>

**after**

```
            {/* Keyed by index, not by `w`: the list repeats widths, so the
                class string is not unique. A fixed-length placeholder that
                never reorders is the case an index key is right for. */}
```

**`[831]`** `frontend/src/routes/store.tsx:400` &middot; **75w → 47w** (37% cut) &middot; _surprising_  
Keep the flex-wrap reason and the sort reset, cut the alignment restatement.

<details><summary>before</summary>

```
/* Right-aligned to the content lane, which is the same right edge the
            grid below uses, so the two line up. flex-wrap so a narrow viewport
            drops it to its own line rather than squeezing or overflowing.
            Changing the order resets to page 1 for the same reason a filter
            change does: page 7 of an alphabetical list is not page 7 of a
            popularity one, and holding the number would land the operator
            somewhere arbitrary. */
```

</details>

**after**

```
        {/* Right-aligned to the same right edge the grid below uses.
            flex-wrap so a narrow viewport drops it to its own line rather than
            squeezing or overflowing. Changing the order resets to page 1: page
            7 of an alphabetical list is not page 7 of a popularity one. */}
```

**`[832]`** `frontend/src/routes/store.tsx:498` &middot; **177w → 116w** (34% cut) &middot; _surprising_  
Keep the never-nested dialog rule and the 936 derivation, trim the rest.

<details><summary>before</summary>

```
/* "Read more" opens the detail content HERE, in a dialog, rather than
          navigating. The same component backs routes/store-detail.tsx, so a
          palette result or a pasted /store/<slug> link still renders the page
          and the two can never drift apart.

          Install inside the popup CLOSES the popup and then opens
          InstallDialog. Sequential, never nested: InstallDialog is itself a
          Dialog, so stacking them would mount two overlays with two focus
          traps, and would put two buttons named "Install" on screen at once,
          which e2e/journey.spec.ts explicitly scopes around. Exactly one
          dialog is mounted at any moment.

          936 is 720 + 30%. The shared 92vw cap still applies and starts biting
          below a ~1017px viewport (936 / 0.92), so this is a desktop width
          that narrows on its own rather than a fixed one that would overhang a
          phone. scrollBody caps the height at 70vh and scrolls the body only:
          this content is the whole detail page, which is taller than the
          screen, and an uncapped panel could not be centred at all because
          there was no free space left to centre it in. */
```

</details>

**after**

```
      {/* "Read more" opens the detail content HERE, in a dialog, rather than
          navigating. The same component backs routes/store-detail.tsx, so a
          pasted /store/<slug> link renders the page and the two cannot drift.

          Install inside the popup CLOSES the popup and then opens
          InstallDialog. Sequential, never nested: InstallDialog is itself a
          Dialog, so stacking them would mount two overlays with two focus
          traps and put two buttons named "Install" on screen at once.

          936 is 720 + 30%. The shared 92vw cap starts biting below a ~1017px
          viewport, so this narrows on its own rather than overhanging a phone.
          scrollBody caps the height at 70vh and scrolls the body only: an
          uncapped panel could not be centred at all. */}
```

**`[833]`** `frontend/src/routes/store.tsx:525` &middot; **38w → 24w** (37% cut) &middot; _surprising_  
Keep why the action is pinned outside the scroll body, cut the last sentence.

<details><summary>before</summary>

```
/* showHeaderAction={false}: the action is pinned in the dialog's
              title row above, which is outside the scroll body, so it stays
              visible however far down the body is scrolled. The content's own
              header would scroll away with everything else. */
```

</details>

**after**

```
          {/* showHeaderAction={false}: the action is pinned in the dialog's
              title row, outside the scroll body, so it stays visible however
              far the body is scrolled. */}
```

**`[834]`** `frontend/src/routes/store.tsx:549` &middot; **60w → 24w** (60% cut) &middot; _redundant_  
The parsing detail is already in toPage and toPageSize above; keep only the absence rule.

<details><summary>before</summary>

```
// Both default states are represented by their ABSENCE from the URL, so
// /store stays clean until the operator actually pages or changes the
// density. A page number arrives as a number from the router's own parse
// but as a string from a hand-typed URL, so both are accepted; anything
// else, including page 1 and the default size, normalises to undefined.
```

</details>

**after**

```
    // Both default states are represented by their ABSENCE from the URL, so
    // /store stays clean until the operator actually pages or changes the
    // density.
```

**`[835]`** `frontend/src/routes/store.tsx:556` &middot; **43w → 31w** (28% cut) &middot; _external-quirk_  
Keep that it mirrors the server allowlist and falls back the same way.

<details><summary>before</summary>

```
// Same four keys the server's own `sort` allowlist accepts, and the
// default is absence again. Anything else falls back to name rather than
// being carried around as a value nothing can honour, which is also what
// GET /catalog does with a bad sort.
```

</details>

**after**

```
    // Same four keys the server's own `sort` allowlist accepts, and the
    // default is absence again. Anything else falls back to name, which is
    // what GET /catalog does with a bad sort.
```


### 🟢 KEEP (6), unchanged

- **`[836]`** `31` &middot; _surprising_ &middot; `// The page sizes offered, and the one a fresh visit gets. DEFAULT_PAGE_SIZE`
- **`[837]`** `44` &middot; _contract_ &middot; `/** The router's own parse yields a number, a hand-typed URL yields a string,`
- **`[838]`** `50` &middot; _contract_ &middot; `/** Page 1 is the default, so it is represented by absence, not by "?page=1". */`
- **`[839]`** `118` &middot; _surprising_ &middot; `// The detail popup. Same shape as `installing` above, and deliberately`
- **`[840]`** `139` &middot; _surprising_ &middot; `// has() reads false until the first entitlements fetch resolves; gating on`
- **`[841]`** `476` &middot; _surprising_ &middot; `/* Genuinely disabled at the ends, not a link that`

---

## `frontend/src/components/IconGrid.tsx`

1,743 → 1,206 words, 31% cut. 0 delete, 19 shorten, 8 keep.


### 🟡 SHORTEN (19)

**`[842]`** `frontend/src/components/IconGrid.tsx:12` &middot; **115w → 75w** (35% cut) &middot; _narration_  
Keep the one-file reason and the two real differences, trim the prose.

<details><summary>before</summary>

```
/**
 * The two inventories on the Hosts page, apps and VMs, as one visual language.
 *
 * They live in ONE file because they are one design that happens to have two
 * data sources: the same cell rhythm, the same status vocabulary, the same
 * grouping. Two files drifted into two row heights the first time anyone
 * touched one of them; a shared cell cannot.
 *
 * The two grids genuinely differ in exactly two places, and those are the two
 * props IconGridCell takes: which menu opens off the artwork (AppIconMenu vs
 * VmActionsMenu), and where the artwork comes from (an app wears the logo of
 * the Store entry it came from, a VM has no such entry and wears its OS).
 */
```

</details>

**after**

```
/**
 * The two inventories on the Hosts page, apps and VMs, as one visual language.
 *
 * They live in ONE file because they are one design with two data sources: the
 * same cell rhythm, the same status vocabulary, the same grouping. Two files
 * drifted into two row heights; a shared cell cannot.
 *
 * They differ in exactly two places, which are the two props IconGridCell
 * takes: which menu opens off the artwork, and where the artwork comes from.
 */
```

**`[843]`** `frontend/src/components/IconGrid.tsx:26` &middot; **190w → 110w** (42% cut) &middot; _measurement-dump_  
Keep the floor rule and the 171px measurement that pins it, cut the before-and-after table.

<details><summary>before</summary>

```
/** auto-fill with a FLOOR, not a fixed column count.
 *
 *  A count (sm:grid-cols-2 xl:grid-cols-4) decided how many columns there were
 *  and let each one be whatever width was left over, so at four across on a
 *  narrow page an app name was cut to a few characters. A floor plus auto-fill
 *  lets the browser fit as many columns as the space allows while keeping any
 *  single column readable.
 *
 *  The floor is 10rem and the column gap is 12px, down from 13rem and 24px.
 *  These two sections sit in half the page each, which is 570px at a 1440px
 *  window once the sidebar, the page padding and the gap between the two
 *  columns come out. Measured in a browser at that width rather than worked
 *  out on paper: the old pair fitted 2 columns of 256px, the new pair fits 3
 *  of 171px, and none of the app names on the reference fleet truncate at
 *  171px, `changedetection` at fifteen characters included. The cell still
 *  carries `truncate` and a `title` for names longer than that.
 *
 *  Shared with the skeleton so the placeholder cannot lay out differently from
 *  the thing it stands in for. */
```

</details>

**after**

```
/** auto-fill with a FLOOR, not a fixed column count.
 *
 *  A fixed count (sm:grid-cols-2 xl:grid-cols-4) let each column be whatever
 *  width was left over, so at four across on a narrow page an app name was cut
 *  to a few characters. A floor plus auto-fill fits as many columns as the
 *  space allows while keeping any one readable.
 *
 *  10rem floor, 12px gap, measured in a browser at the 570px each section gets
 *  on a 1440px window: 3 columns of 171px, and no app name on the reference
 *  fleet truncates at that width. The cell still carries `truncate` and a
 *  `title`.
 *
 *  Shared with the skeleton so the placeholder cannot lay out differently. */
```

**`[844]`** `frontend/src/components/IconGrid.tsx:47` &middot; **87w → 59w** (32% cut) &middot; _surprising_  
Keep why the panel must stay out of GRID, cut the history of when it did not matter.

<details><summary>before</summary>

```
/** The card the grids sit in, kept OUT of GRID.
 *
 *  It used to be welded onto the end of the same class string, which was fine
 *  while there was one grid per inventory. There is now one grid per node, and
 *  a card per node would draw five floating boxes for a five node cluster and
 *  read as five separate inventories. One panel with a rule between sections
 *  reads as what it is: a single list of what is installed, grouped by the
 *  machine it runs on. */
```

</details>

**after**

```
/** The card the grids sit in, kept OUT of GRID.
 *
 *  There is one grid per NODE, so a card welded onto the grid string would
 *  draw five floating boxes for a five node cluster and read as five separate
 *  inventories. One panel with a rule between sections reads as one list,
 *  grouped by the machine each guest runs on. */
```

**`[845]`** `frontend/src/components/IconGrid.tsx:57` &middot; **202w → 107w** (47% cut) &middot; _external-quirk_  
Keep the icon-names.mjs field shape, the pending entry and the shared vocabulary, trim the rest.

<details><summary>before</summary>

```
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
 *
 * `pending` is not one of StatusPill's STYLES keys either (it falls to its
 * `unknown` grey there): it is the optimistic patch useLifecycle applies for
 * the span between a click and the job's own resolution, covered here for
 * the same reason. `connected`/`online` are node-only statuses StatusPill
 * also carries, never a value AppRow.status takes, so they are left out.
 *
 * Shared by the app cell and the VM cell: the two kinds of guest report the
 * same words for the same states, and a VM that read "Stopped" in one colour
 * on one half of the page and another colour on the other half would be the
 * page contradicting itself.
 */
```

</details>

**after**

```
/**
 * State, as a glyph and the word, for the icon grid.
 *
 * The COLOURS are StatusPill's and the WORD is statusLabel's, so this cannot
 * drift from the vocabulary the rest of the app uses, and the app cell and the
 * VM cell share it so one state never reads in two colours.
 *
 * Every status gets its own entry rather than collapsing to running/stopped:
 * paused and unknown are not "not running". `icon:` is the field shape
 * scripts/icon-names.mjs reads, which is why these are literals in a table.
 *
 * `pending` is not one of StatusPill's STYLES keys: it is the optimistic patch
 * useLifecycle applies between a click and the job's resolution.
 */
```

**`[846]`** `frontend/src/components/IconGrid.tsx:102` &middot; **110w → 74w** (33% cut) &middot; _narration_  
Keep the total-not-per-node rule and why a cap exists, cut the worked example.

<details><summary>before</summary>

```
/**
 * The most guests one inventory draws, across every node in it.
 *
 * 50 for the apps and 50 for the VMs, not 50 each per node: the number that
 * matters is how much of the page a section can take, and that is the total.
 * One host showing 50 apps and two hosts showing 25 apiece cost the operator
 * the same scroll.
 *
 * The cap exists because the sections are uncapped otherwise, and a fleet with
 * three hundred containers turned the Hosts page into a list nobody reads on
 * the way to the thing they came for. Both sections link to their full table,
 * which is where a fleet that size belongs.
 */
```

</details>

**after**

```
/**
 * The most guests one inventory draws, across every node in it.
 *
 * 50 for the apps and 50 for the VMs, not 50 per node: what matters is how
 * much of the page a section can take, and that is the total. Without a cap, a
 * fleet with three hundred containers turned the Hosts page into a list nobody
 * reads on the way to what they came for. Both sections link to their full
 * table.
 */
```

**`[847]`** `frontend/src/components/IconGrid.tsx:117` &middot; **124w → 92w** (26% cut) &middot; _buried-invariant_  
Keep the round-robin reason and the termination argument, trim the framing.

<details><summary>before</summary>

```
/**
 * How many rows each node section may draw, dealt round-robin.
 *
 * Round-robin rather than a slice off the front, because a slice is the bug
 * this file already carries a comment about: take the first 50 of a sorted
 * list and node1 eats all of them while node2 renders empty, so an operator
 * reading the page cannot tell a node with no apps from a node that lost the
 * draw. Dealing one at a time gives 25/25 for two even nodes and spends the
 * remainder on whoever still has rows left, so every node is represented
 * before any node is complete.
 *
 * Terminates: every pass either hands out at least one row or every group is
 * already full, and `left` never exceeds the rows that exist.
 */
```

</details>

**after**

```
/**
 * How many rows each node section may draw, dealt round-robin.
 *
 * Not a slice off the front: take the first 50 of a sorted list and node1 eats
 * all of them while node2 renders empty, so an operator cannot tell a node
 * with no apps from a node that lost the draw. Dealing one at a time gives
 * 25/25 for two even nodes and spends the remainder on whoever has rows left.
 *
 * Terminates: every pass either hands out a row or every group is full, and
 * `left` never exceeds the rows that exist.
 */
```

**`[848]`** `frontend/src/components/IconGrid.tsx:145` &middot; **40w → 28w** (30% cut) &middot; _contract_  
Keep both output forms and why the total is stated, cut the last clause.

<details><summary>before</summary>

```
/** "4 apps", or "25 of 40 apps" when the cap took the rest. The count is the
 *  only place the page can admit it is not showing everything, so it says the
 *  total rather than quietly drawing a shorter list. */
```

</details>

**after**

```
/** "4 apps", or "25 of 40 apps" when the cap took the rest. The count is the
 *  only place the page can admit it is not showing everything. */
```

**`[849]`** `frontend/src/components/IconGrid.tsx:153` &middot; **42w → 32w** (24% cut) &middot; _narration_  
Keep what the section is for, trim the counterfactual.

<details><summary>before</summary>

```
/** Rows with neither a node nor a host name. They are still somebody's guests,
 *  so they get a section of their own at the end rather than being dropped on
 *  the floor, which is what a `if (!node) continue` would have done. */
```

</details>

**after**

```
/** Rows with neither a node nor a host name. Still somebody's guests, so they
 *  get a section of their own at the end rather than being dropped by an
 *  `if (!node) continue`. */
```

**`[850]`** `frontend/src/components/IconGrid.tsx:158` &middot; **193w → 122w** (37% cut) &middot; _data-integrity_  
Keep the guest-node versus host-endpoint distinction and the fallback, trim the prose.

<details><summary>before</summary>

```
/**
 * Guests grouped by the machine they actually run on.
 *
 * The key is the GUEST'S OWN node, not the host it was read through, and that
 * distinction is the whole point of this change. A Host record in Proxploy is
 * one Proxmox API endpoint; on a cluster that one endpoint answers for every
 * node in the cluster, so a container sitting on pve3 arrives with
 * host_name "host-01" because host-01 is the endpoint we asked. Grouping on
 * host_name would file every guest in the cluster under one heading and say
 * "host-01" over a list of containers that are running on three different
 * machines, which is the exact question the operator opened this page to
 * answer.
 *
 * host_name is the FALLBACK, for the rows where node is null: a standalone
 * host whose poller has not filled the field in yet still belongs somewhere,
 * and its host name is the truest thing we can say about where it lives.
 *
 * Sorted by name, and sorted within each group by name, for the same reason
 * the node cards above are: /apps and /vms answer in no defined order, so an
 * unsorted list reshuffles under the operator on every 30s refetch.
 */
```

</details>

**after**

```
/**
 * Guests grouped by the machine they actually run on.
 *
 * The key is the GUEST'S OWN node, not the host it was read through. A Host
 * record is one Proxmox API endpoint, and on a cluster that endpoint answers
 * for every node, so a container on pve3 arrives with host_name "host-01".
 * Grouping on host_name would file every guest in the cluster under one
 * heading, over containers running on three different machines.
 *
 * host_name is the FALLBACK for rows where node is null: a standalone host
 * whose poller has not filled the field in yet still belongs somewhere.
 *
 * Sorted by name, and within each group by name, because /apps and /vms answer
 * in no defined order and an unsorted list reshuffles on every 30s refetch.
 */
```

**`[851]`** `frontend/src/components/IconGrid.tsx:180` &middot; **25w → 22w** (12% cut) &middot; _data-integrity_  
Keep why null is a safe group key, trim the wording.

<details><summary>before</summary>

```
// null is the key of the group for rows with neither, and null cannot
// collide with any name a node or a host could have.
```

</details>

**after**

```
  // null is the key for rows with neither, and it cannot collide with any
  // name a node or a host could have.
```

**`[852]`** `frontend/src/components/IconGrid.tsx:186` &middot; **47w → 32w** (32% cut) &middot; _surprising_  
Keep why a node-less row joins its host's group, cut the last clause.

<details><summary>before</summary>

```
// A row with no node joins the group of its host's name rather than
// starting one beside it. On a standalone machine the host record is
// usually named after its only node, so keeping them apart would draw two
// sections with the same heading over one machine.
```

</details>

**after**

```
    // A row with no node joins the group of its host's name rather than
    // starting one beside it: on a standalone machine the host record is
    // usually named after its only node.
```

**`[853]`** `frontend/src/components/IconGrid.tsx:218` &middot; **33w → 28w** (15% cut) &middot; _buried-invariant_  
Keep the order rule and why it matters, trim the wording.

<details><summary>before</summary>

```
// Grouped first, capped second. The cap is a total across the sections, so
// it cannot be applied to `rows` before the groups exist without deciding
// which node loses out by sort order alone.
```

</details>

**after**

```
  // Grouped first, capped second: the cap is a total across the sections, so
  // applying it to `rows` first would decide which node loses out by sort
  // order alone.
```

**`[854]`** `frontend/src/components/IconGrid.tsx:226` &middot; **81w → 50w** (38% cut) &middot; _external-quirk_  
Keep the same-box rule and the DNS label comparison, drop the retelling.

<details><summary>before</summary>

```
// The host is worth saying only when it is a DIFFERENT machine from
// the heading: "pve3 · on host-01" tells the operator which endpoint
// answers for that node, while "node1 · on node1.lab.local" is
// the same box named twice.
//
// Compared on the first DNS label, not the whole string. A host is
// routinely registered by its fully qualified name while PVE reports
// the node as the short one, so an exact compare called them different
// machines and repeated the name in every heading.
```

</details>

**after**

```
        // The host is worth saying only when it is a DIFFERENT machine from
        // the heading: "node1 · on node1.lab.local" is the same box
        // named twice. Compared on the first DNS label, since a host is
        // routinely registered by its fully qualified name while PVE reports
        // the node as the short one.
```

**`[855]`** `frontend/src/components/IconGrid.tsx:243` &middot; **31w → 22w** (29% cut) &middot; _test-reference_  
Keep the one-string rule, drop the assertion argument behind it.

<details><summary>before</summary>

```
/* One string, not two children: split across text nodes it
                  reads the same on screen and is a great deal harder to assert
                  on, and it is one sentence either way. */
```

</details>

**after**

```
              {/* One string, not two children: split across text nodes it
                  reads the same on screen, and it is one sentence either
                  way. */}
```

**`[856]`** `frontend/src/components/IconGrid.tsx:259` &middot; **67w → 52w** (22% cut) &middot; _contract_  
Keep why menu is a function and the shared-trigger rule, trim the aside.

<details><summary>before</summary>

```
/**
 * One guest: its artwork, which is the menu, and its name and state beside it.
 *
 * `menu` is a function rather than a wrapped child because the two menus take
 * different props (AppIconMenu wants the app row, VmActionsMenu the VM row)
 * while both want the SAME trigger, tile size and all. Handing them a trigger
 * this component built is what keeps the two grids on one row rhythm.
 */
```

</details>

**after**

```
/**
 * One guest: its artwork, which is the menu, and its name and state beside it.
 *
 * `menu` is a function rather than a wrapped child because the two menus take
 * different props while both want the SAME trigger, tile size and all, which
 * is what keeps the two grids on one row rhythm.
 */
```

**`[857]`** `frontend/src/components/IconGrid.tsx:280` &middot; **33w → 31w** (6% cut) &middot; _surprising_  
Keep why nothing is drawn on the tile, trim the wording.

<details><summary>before</summary>

```
/* The artwork is the menu. Nothing is drawn ON it: the tile is the
          guest's own picture and a badge over it would compete with whatever
          that picture already puts in the corner. */
```

</details>

**after**

```
      {/* The artwork is the menu. Nothing is drawn ON it: the tile is the
          guest's own picture, and a badge would compete with whatever that
          picture already puts in the corner. */}
```

**`[858]`** `frontend/src/components/IconGrid.tsx:309` &middot; **82w → 46w** (44% cut) &middot; _implementation-diary_  
Keep the cap-is-dealt-and-stated rule, cut the story of the old first-eight list.

<details><summary>before</summary>

```
/** Every installed app up to CAP, grouped under the node it runs on. The page
 *  once showed the first eight in whatever order the API answered, which on a
 *  cluster meant an operator could not tell whether a missing app was stopped,
 *  gone, or simply the ninth. The cap that replaced no cap at all is dealt
 *  across the nodes and stated in each section's count, so neither of those
 *  readings is possible: a section that is holding rows back says so. */
```

</details>

**after**

```
/** Every installed app up to CAP, grouped under the node it runs on. The cap
 *  is dealt across the nodes and stated in each section's count, so a section
 *  holding rows back says so, and a missing app cannot mean "stopped, gone, or
 *  simply the ninth". */
```

**`[859]`** `frontend/src/components/IconGrid.tsx:331` &middot; **80w → 68w** (15% cut) &middot; _external-quirk_  
Keep the null-ostype fallback behaviour, trim the wording.

<details><summary>before</summary>

```
/** Every VM up to CAP, the same grid, grouped and capped the same way.
 *
 *  A VM has no catalog entry and so no logo. osIconUrl returns null both for
 *  an ostype we do not recognise and for a VM whose ostype PVE has not told us
 *  yet, and IconTile treats a null url as "no artwork" and falls back to the
 *  initials tile, so an unknown OS looks like an app with no logo rather than
 *  like a broken image. */
```

</details>

**after**

```
/** Every VM up to CAP, the same grid, grouped and capped the same way.
 *
 *  A VM has no catalog entry and so no logo. osIconUrl returns null both for
 *  an unrecognised ostype and for one PVE has not reported yet, and IconTile
 *  falls back to the initials tile on a null url, so an unknown OS looks like
 *  an app with no logo rather than a broken image. */
```

**`[860]`** `frontend/src/components/IconGrid.tsx:353` &middot; **43w → 38w** (12% cut) &middot; _narration_  
Keep the mirrors-the-real-cell rule, cut the editing instruction.

<details><summary>before</summary>

```
/** The placeholder for either grid, mirroring the section heading, the 32px
 *  tile and the two text lines so the page below does not shift when the rows
 *  land. ONE placeholder for both grids because there is one cell: edited with
 *  IconGridCell, never separately. */
```

</details>

**after**

```
/** The placeholder for either grid, mirroring the section heading, the 32px
 *  tile and the two text lines so the page below does not shift when the rows
 *  land. ONE placeholder for both grids because there is one cell. */
```


### 🟢 KEEP (8), unchanged

- **`[861]`** `89` &middot; _contract_ &middot; `/** The fields both inventories carry and this file needs. */`
- **`[862]`** `93` &middot; _contract_ &middot; `/** The node name, the host name it fell back to, or null for neither. */`
- **`[863]`** `95` &middot; _contract_ &middot; `/** The heading: the node's own name, or the host's when no node was reported. */`
- **`[864]`** `97` &middot; _contract_ &middot; `/** Hosts these rows came in through, for the line under the heading. */`
- **`[865]`** `196` &middot; _data-integrity_ &middot; `// Several hosts can answer for one node (two endpoints into one cluster),`
- **`[866]`** `211` &middot; _contract_ &middot; `/** One panel, one section per node, a rule between them. */`
- **`[867]`** `214` &middot; _contract_ &middot; `/** "app" or "VM", the one noun the two inventories do not share. */`
- **`[868]`** `292` &middot; _contract_ &middot; `/* The name is the way to the detail, which is a row that expands on`

---

## `frontend/src/components/InstallDialog.tsx`

1,435 → 896 words, 38% cut. 3 delete, 23 shorten, 3 keep.


### 🔴 DELETE (3)

**`[869]`** `frontend/src/components/InstallDialog.tsx:105` &middot; 14w &middot; _narration_  
Describes the skeleton shapes on the next lines and nothing more.

```
/* Default and Advanced, each a radio beside a name and a line of
                explanation. */
```

**`[870]`** `frontend/src/components/InstallDialog.tsx:124` &middot; 9w &middot; _narration_  
Labels the next skeleton line with what it stands in for; the height is already in the class.

```
/* The derived-defaults strip: p-2 around one 11px mono line. */
```

**`[871]`** `frontend/src/components/InstallDialog.tsx:228` &middot; 20w &middot; _redundant_  
Repeats the unprivileged rule already stated where coreOverride is declared.

```
// Only once the operator actually toggled it: untouched means "whatever
// this app's script declares", which is not ours to answer.
```


### 🟡 SHORTEN (23)

**`[872]`** `frontend/src/components/InstallDialog.tsx:23` &middot; **38w → 31w** (18% cut) &middot; _external-quirk_  
Keeps both values and why unreachable is disabled rather than allowed to fail.

<details><summary>before</summary>

```
// "connected" or "unreachable" (backend/proxploy/models: only two values,
// "connected" the default). An unreachable host answers every job the
// install would enqueue with a failure, so the picker below disables it
// instead of letting it be chosen only to fail.
```

</details>

**after**

```
  // "connected" or "unreachable", the only two values. An unreachable host
  // fails every job the install would enqueue, so the picker disables it rather
  // than letting it be chosen only to fail.
```

**`[873]`** `frontend/src/components/InstallDialog.tsx:28` &middot; **31w → 25w** (19% cut) &middot; _security_  
Keeps the root-script consent record and the show-while-null rule.

<details><summary>before</summary>

```
// Non-null once this host has acknowledged that installs run a
// community-scripts.org script as root (api/catalog.py). Asking again
// surfaces no new information, so the tick is only shown while this is null.
```

</details>

**after**

```
  // Non-null once this host has acknowledged that installs run a
  // community-scripts.org script as root (api/catalog.py), so the tick is only
  // shown while this is null.
```

**`[874]`** `frontend/src/components/InstallDialog.tsx:42` &middot; **60w → 41w** (32% cut) &middot; _ticket-history_  
Keeps the mode rule and why CTID stays in the base section, drops the Task 9-12 numbering.

<details><summary>before</summary>

```
// Default asks nothing that has an honest default; Advanced expands the
// container-customization block Tasks 9-11 fill in. CTID has an honest
// default too (blank -> node assigns the next free id) but stays in the
// base section: unlike vCPU/RAM/disk, operators commonly want to pick it
// even on an otherwise-default install, and Task 12 hangs its collision
// check off this same field.
```

</details>

**after**

```
  // Default asks nothing that has an honest default; Advanced expands the
  // container-customization block. CTID has an honest default too (blank means
  // the node assigns the next free id) but stays in the base section, since
  // operators commonly want to pick it.
```

**`[875]`** `frontend/src/components/InstallDialog.tsx:49` &middot; **29w → 24w** (17% cut) &middot; _external-quirk_  
Keeps the backend contract, trims the aside.

<details><summary>before</summary>

```
// Empty string means "let resolve_storage_pools decide" (backend/proxploy/
// services/appstore.py): its one fallback, the sole candidate, is an
// honest default, so Default mode never has to touch this state at all.
```

</details>

**after**

```
  // Empty string means "let resolve_storage_pools decide" (services/
  // appstore.py): its one fallback is an honest default, so Default mode never
  // has to touch this state.
```

**`[876]`** `frontend/src/components/InstallDialog.tsx:53` &middot; **113w → 68w** (40% cut) &middot; _ticket-history_  
The dockge disagreement and the var_unprivileged quirk stay; the Task 7 reference and framing go.

<details><summary>before</summary>

```
// Each field is null until the operator types into it, meaning "still
// tracking the derived default computed below." cpu/ram/disk/os/version
// derive from the catalog entry's script-parsed default_* columns (Task
// 7): NOT raw.metadata.install_methods[].resources, which disagrees for
// some slugs (dockge is 2/2048/18 in the script and 0/0/0 in that
// metadata). hostname derives from the app name typed above instead,
// since there is no script-parsed default for it. unprivileged is null
// until toggled and stays null: MOST community-scripts install scripts
// default var_unprivileged to 1, but not all (a ct script declaring
// var_unprivileged="0" disagrees), and Proxploy has no parsed column for
// it. Inventing 1 and then sending it would overrule those scripts merely
// because the operator opened Advanced.
```

</details>

**after**

```
  // Each field is null until the operator types into it, meaning "still
  // tracking the derived default below." cpu/ram/disk/os/version derive from
  // the entry's script-parsed default_* columns, NOT
  // raw.metadata.install_methods[].resources, which disagrees for some slugs
  // (dockge is 2/2048/18 in the script and 0/0/0 there). unprivileged stays
  // null until toggled: MOST community-scripts scripts default var_unprivileged
  // to 1 but not all, and inventing 1 would overrule the script merely because
  // Advanced was opened.
```

**`[877]`** `frontend/src/components/InstallDialog.tsx:70` &middot; **31w → 26w** (16% cut) &middot; _external-quirk_  
Keeps the two-progress-call fact and why the value is seeded rather than zeroed.

<details><summary>before</summary>

```
// services/appstore.py::run_install only calls ctx.progress(80) then (100),
// so this is null on the freshly-enqueued job the install POST returns.
// Seeded from that row rather than assumed zero, in case that ever changes.
```

</details>

**after**

```
  // services/appstore.py::run_install only calls ctx.progress(80) then (100),
  // so this is null on the freshly-enqueued job the install POST returns.
  // Seeded from that row rather than assumed zero.
```

**`[878]`** `frontend/src/components/InstallDialog.tsx:76` &middot; **37w → 23w** (38% cut) &middot; _external-quirk_  
Keeps the fallback rule in fewer words.

<details><summary>before</summary>

```
// The node it lands on, falling back to the host record's own name: a
// standalone host is usually named after its only node, and on a cluster the
// node is the machine the container actually runs on.
```

</details>

**after**

```
  // The node it lands on, falling back to the host record's own name: a
  // standalone host is usually named after its only node.
```

**`[879]`** `frontend/src/components/InstallDialog.tsx:80` &middot; **26w → 20w** (23% cut) &middot; _surprising_  
Keeps the dedupe reason a reader would otherwise break by moving the call.

<details><summary>before</summary>

```
// Called above the early return, and with the same queryKey StorageFields
// uses, so react-query dedupes it against Advanced mode's own fetch rather
// than doubling the request.
```

</details>

**after**

```
  // Called above the early return, with the same queryKey StorageFields uses,
  // so react-query dedupes it against Advanced mode's own fetch.
```

**`[880]`** `frontend/src/components/InstallDialog.tsx:85` &middot; **113w → 50w** (56% cut) &middot; _implementation-diary_  
Keeps why the placeholder exists and why the failure branch is required, cuts the retelling.

<details><summary>before</summary>

```
// `return null` here meant the operator pressed Install on a store card and
// the screen did nothing at all until the entry arrived, with no way to tell
// a slow catalog from a click that missed. The dialog opens immediately
// instead, titled with the slug it was opened for, which is already known
// from the props and needs nothing fetched.
//
// The failure branch is here because the placeholder created the need for
// it: `!entry` is also true forever after a failed fetch, and a dialog that
// pulses for ever is worse than the blank it replaced. Cancel stays live in
// both, so a dialog that cannot fill itself in can still be closed.
```

</details>

**after**

```
  // The dialog opens immediately, titled with the slug from the props:
  // `return null` here left the operator with no way to tell a slow catalog
  // from a click that missed. The failure branch is needed because `!entry` is
  // also true forever after a failed fetch. Cancel stays live in both.
```

**`[881]`** `frontend/src/components/InstallDialog.tsx:118` &middot; **31w → 17w** (45% cut) &middot; _measurement-dump_  
Keeps the 33px control height the skeleton must match, cuts the derivation.

<details><summary>before</summary>

```
/* Host, App name, CTID. `px-3 py-1.5` around a 13px line box
                inside a 1px border is 33px, which is this dialog's control
                height and not the 37px the settings forms use. */
```

</details>

**after**

```
            {/* Host, App name, CTID. 33px is this dialog's control height,
                not the 37px the settings forms use. */}
```

**`[882]`** `frontend/src/components/InstallDialog.tsx:137` &middot; **41w → 29w** (29% cut) &middot; _surprising_  
Keeps the reason these are derived per render rather than stored.

<details><summary>before</summary>

```
// The values CoreFields actually displays: whatever the operator typed,
// else the derived default. Computed here rather than stored directly so
// a still-loading `entry` (undefined on the very first render, before
// this early return) never gets baked into useState's one-shot initial
// value.
```

</details>

**after**

```
  // The values CoreFields displays: whatever the operator typed, else the
  // derived default. Computed here rather than stored, so a still-loading
  // `entry` never gets baked into useState's one-shot initial value.
```

**`[883]`** `frontend/src/components/InstallDialog.tsx:152` &middot; **72w → 62w** (14% cut) &middot; _external-quirk_  
Keeps the nullable-columns quirk and the shared figure/text rule, cuts the framing.

<details><summary>before</summary>

```
// The one-line summary of what the script would build, with the missing
// halves left out instead of printed as bare units. Every default_* column
// is nullable (api/catalog.ts) because discovery parses them out of the ct
// script and plenty of scripts do not set them, which used to render as
// " vCPU · MB RAM · GB disk · ". Same figure()/text() rules the Store
// detail page uses, so 0 and "" count as missing there and here alike.
```

</details>

**after**

```
  // The one-line summary of what the script would build, with the missing
  // halves left out rather than printed as bare units. Every default_* column
  // is nullable: discovery parses them out of the ct script and plenty of
  // scripts do not set them. figure()/text() decide what counts as missing, so
  // 0 and "" render as nothing here and on the Store detail page alike.
```

**`[884]`** `frontend/src/components/InstallDialog.tsx:166` &middot; **50w → 38w** (24% cut) &middot; _buried-invariant_  
Keeps the two-opposite-meanings invariant and that it gates submit.

<details><summary>before</summary>

```
// Whether the snapshot behind GET /storage has been read at all. Empty
// candidate lists mean two opposite things (this host has no such pool /
// we have not looked yet) and only this tells them apart, so it gates
// submit: a form that cannot see the pools must not look complete.
```

</details>

**after**

```
  // Whether the snapshot behind GET /storage has been read at all. An empty
  // candidate list means two opposite things (no such pool here / we have not
  // looked yet), and only this tells them apart, so it gates submit.
```

**`[885]`** `frontend/src/components/InstallDialog.tsx:172` &middot; **57w → 40w** (30% cut) &middot; _ticket-history_  
Keeps the never-remembered rule, drops the PXP-86 reference.

<details><summary>before</summary>

```
// The sole candidate is not a real choice, so it is DISPLAYED rather than
// asked for. Nothing here is remembered across installs (PXP-86 decision):
// knownPool no longer consults anything saved on the host, only the
// current candidate list, so a host with two or more pools is asked every
// time, never silently answered from a prior install.
```

</details>

**after**

```
  // The sole candidate is not a real choice, so it is DISPLAYED rather than
  // asked for. Nothing is remembered across installs: knownPool consults only
  // the current candidate list, so a host with two or more pools is asked every
  // time.
```

**`[886]`** `frontend/src/components/InstallDialog.tsx:180` &middot; **77w → 52w** (32% cut) &middot; _external-quirk_  
The vztmpl ambiguity is a real Proxmox layout constraint and stays; the framing goes.

<details><summary>before</summary>

```
// Default asks no question THAT HAS AN HONEST DEFAULT. Several candidates
// has no default: build.func has none and we do not invent one, so these
// are the questions Default has to ask. BOTH content types get asked, not
// just rootdir: resolve_storage_pools refuses just as flatly on an
// ambiguous vztmpl (one rootdir pool plus `local` and any NFS/dir storage
// carrying vztmpl is an ordinary Proxmox layout), and a Default mode with
// no field for it fails there forever.
```

</details>

**after**

```
  // Default asks no question THAT HAS AN HONEST DEFAULT, and several candidates
  // has none: build.func has none and we do not invent one. BOTH content types
  // get asked: resolve_storage_pools refuses just as flatly on an ambiguous
  // vztmpl, an ordinary Proxmox layout (one rootdir pool plus `local` and any
  // NFS/dir storage carrying vztmpl).
```

**`[887]`** `frontend/src/components/InstallDialog.tsx:194` &middot; **28w → 18w** (36% cut) &middot; _security_  
Keeps the consent-once rule and the no-host-selected case.

<details><summary>before</summary>

```
// Asked once per host, then remembered on Host.install_consent_at: re-asking
// an operator who already acknowledged surfaces no new information. Also
// true (so still asked) while no host is selected.
```

</details>

**after**

```
  // Asked once per host, then remembered on Host.install_consent_at. Also true,
  // so still asked, while no host is selected.
```

**`[888]`** `frontend/src/components/InstallDialog.tsx:208` &middot; **94w → 47w** (50% cut) &middot; _implementation-diary_  
Keeps the only-send-what-was-picked rule and the blank-is-withheld rule.

<details><summary>before</summary>

```
// Only send a key the operator actually picked or that a field with an
// honest fallback (an empty string) would otherwise mangle. An empty
// string for storage would reach resolve_storage_pools as a
// supplied-but-blank value; its own `.strip() or None` treats that the
// same as absent, but sending nothing is more honest about "the
// operator did not choose." Same reasoning for the core fields below:
// Default mode never customized anything, so it sends none of these,
// and even in Advanced mode a field the operator cleared to blank is
// withheld rather than sent as `var_x=""`.
```

</details>

**after**

```
    // Only send a key the operator actually picked. An empty string would reach
    // resolve_storage_pools as supplied-but-blank; its `.strip() or None` treats
    // that as absent anyway, but sending nothing is more honest. Same for the
    // core fields: a field cleared to blank is withheld, not sent as `var_x=""`.
```

**`[889]`** `frontend/src/components/InstallDialog.tsx:239` &middot; **88w → 46w** (48% cut) &middot; _implementation-diary_  
Keeps why the transcript needs the wider dialog and what max() guarantees.

<details><summary>before</summary>

```
/* Two states, two widths, one dialog. The form is a column of fields and
       reads fine at 520. The install transcript is a terminal, and 520 wrapped
       community-scripts' output mid-line, which is where the useful part
       lives: the finished URL, the port, and whatever went wrong. 60% of the
       window is what an operator can actually read, and max() means it is
       never NARROWER than the form was, so a small window keeps today's
       behaviour rather than getting worse. The 92vw cap in dialogPanelClass
       still applies on top. */
```

</details>

**after**

```
    /* Two states, two widths. The form reads fine at 520; the install
       transcript is a terminal, and 520 wrapped community-scripts' output
       mid-line, where the useful part lives: the finished URL, the port, and
       whatever went wrong. max() keeps it from ever being NARROWER than the
       form. */
```

**`[890]`** `frontend/src/components/InstallDialog.tsx:253` &middot; **29w → 25w** (14% cut) &middot; _surprising_  
Keeps why the ring jumps and why it hides before the first step.

<details><summary>before</summary>

```
/* Two or three real steps (services/appstore.py), so the ring
              jumps rather than sweeps: honest, not smoothed. Never shown
              before the first step, a zero here would read as stalled. */
```

</details>

**after**

```
          {/* Two or three real steps (services/appstore.py), so the ring jumps
              rather than sweeps. Never shown before the first step: a zero
              would read as stalled. */}
```

**`[891]`** `frontend/src/components/InstallDialog.tsx:257` &middot; **85w → 48w** (44% cut) &middot; _implementation-diary_  
Keeps why the line names the destination and the empty-host fallback, cuts the before-and-after copy.

<details><summary>before</summary>

```
/* The DESTINATION, not the app again. This line used to read
              "Installing Alpine-IT-Tools…" directly under a title reading
              "Install Alpine-IT-Tools", which is the same words twice and
              tells the reader nothing the heading did not. Where it is going
              is the one thing the dialog does not otherwise say once the form
              is replaced by the transcript, and on a cluster it is the thing
              worth checking. Falls back to the bare verb when the host is not
              readable, rather than printing an empty "on". */
```

</details>

**after**

```
          {/* The DESTINATION, not the app again: "Installing Alpine-IT-Tools…"
              under the title "Install Alpine-IT-Tools" tells the reader nothing
              the heading did not, and where it is going is the one thing the
              dialog stops saying once the transcript replaces the form. Bare
              verb when the host is not readable. */}
```

**`[892]`** `frontend/src/components/InstallDialog.tsx:302` &middot; **44w → 27w** (39% cut) &middot; _data-integrity_  
Keeps why a host switch clears the picks, in fewer words.

<details><summary>before</summary>

```
// Storage pools are per host (StorageFields): a pool picked on
// the old host is not necessarily valid on the new one, so a
// host switch clears the picks instead of letting a name that
// may not exist there reach the install as an override.
```

</details>

**after**

```
              // Storage pools are per host: a pool picked on the old host is
              // not necessarily valid on the new one, so a host switch clears
              // the picks.
```

**`[893]`** `frontend/src/components/InstallDialog.tsx:319` &middot; **77w → 37w** (52% cut) &middot; _narration_  
Keeps why the name is asked in both modes and the deliberate no-prefill rule.

<details><summary>before</summary>

```
/* Labelled, not just placeheld, and asked in BOTH modes. This is
              what tells two copies of the same app apart: a second install is
              ordinary (a test one beside a prod one, or an operator's own
              naming scheme), and once there are two, the name is the only
              thing distinguishing them in every list Proxploy shows.
              Deliberately NOT prefilled with the catalog name: the whole
              reason for a second copy is that it differs from the first. */
```

</details>

**after**

```
          {/* Labelled, not just placeheld, and asked in BOTH modes. A second
              install of the same app is ordinary, and the name is then the only
              thing telling the two apart. Deliberately NOT prefilled with the
              catalog name. */}
```

**`[894]`** `frontend/src/components/InstallDialog.tsx:337` &middot; **82w → 43w** (48% cut) &middot; _narration_  
Keeps the no-empty-box rule and why the strip is Default mode only.

<details><summary>before</summary>

```
/* Nothing recorded at all means no box, not an empty one: the
              Store detail page drops the whole section the same way.
              Default mode only: this line is the APP's own script-parsed
              defaults, not a summary of what this install will build, and in
              Advanced mode CoreFields below shows the fields that actually
              decide that, sometimes with the operator's own numbers typed
              over these same defaults. Showing both was one true line and one
              stale one, directly on top of each other. */
```

</details>

**after**

```
          {/* Nothing recorded at all means no box, not an empty one. Default
              mode only: this is the APP's own script-parsed defaults, while
              Advanced mode's CoreFields shows the fields that actually decide
              the install. Showing both was one true line and one stale one. */}
```


### 🟢 KEEP (3), unchanged

- **`[895]`** `17` &middot; _external-quirk_ &middot; `// The node whose datastores an install on this host lands on: the same`
- **`[896]`** `20` &middot; _external-quirk_ &middot; `// Needed to tell a sibling node of the same cluster apart from an unrelated`
- **`[897]`** `199` &middot; _contract_ &middot; `// CTID is no longer required: blank means the node assigns the next free`

---

## `frontend/src/components/VmActionsMenu.tsx`

1,185 → 671 words, 43% cut. 1 delete, 14 shorten, 2 keep.


### 🔴 DELETE (1)

**`[898]`** `frontend/src/components/VmActionsMenu.tsx:319` &middot; 32w &middot; _implementation-diary_  
Explains what the code no longer does; the invalidation above already shows how the row disappears.

```
// Closing the job log needs no navigation any more: the table this was
// opened from is already the page, and the invalidation above is what drops
// the destroyed row out of it.
```


### 🟡 SHORTEN (14)

**`[899]`** `frontend/src/components/VmActionsMenu.tsx:25` &middot; **30w → 29w** (3% cut) &middot; _test-reference_  
Keeps the token rule and the border-t separator fact, drops the pointer to the test that enforces it.

<details><summary>before</summary>

```
// The destructive vocabulary AppIconMenu and HostActionsMenu already use:
// text-red/bg-red-dim tokens, never a literal hex
// (src/tests/no-hardcoded-colors.test.ts). The border-t IS the separator that
// keeps Delete off the end of the ordinary list.
```

</details>

**after**

```
// The destructive vocabulary AppIconMenu and HostActionsMenu already use:
// text-red/bg-red-dim tokens, never a literal hex. The border-t IS the
// separator that keeps Delete off the end of the ordinary list.
```

**`[900]`** `frontend/src/components/VmActionsMenu.tsx:35` &middot; **95w → 57w** (40% cut) &middot; _buried-invariant_  
The icon-literal build constraint is load bearing and stays in full; the mirror-AppIconMenu prose collapses to one line.

<details><summary>before</summary>

```
// Icon names are STRING LITERALS in an `icon:` field, not a computed lookup:
// scripts/icon-names.mjs statically scans src/ to build the Google Fonts
// icon_names parameter, and a name it cannot read out of the source ships a
// font subset without that glyph, so the browser renders the literal word.
//
// The same two tables AppIconMenu keeps, for the same reason and in the same
// order: an operator who learns the app menu should not have to relearn the
// VM one. Stop is the hard kill and Shutdown below is the graceful one PVE
// distinguishes it from (services/lifecycle.py).
```

</details>

**after**

```
// Icon names are STRING LITERALS in an `icon:` field, not a computed lookup:
// scripts/icon-names.mjs statically scans src/ to build the Google Fonts
// icon_names parameter, and a name it cannot read out of the source ships a
// font subset without that glyph, so the browser renders the literal word.
//
// Same two tables as AppIconMenu, in the same order.
```

**`[901]`** `frontend/src/components/VmActionsMenu.tsx:55` &middot; **426w → 173w** (59% cut) &middot; _implementation-diary_  
430-word essay; the constraints (console is the only way in, VM_ACTIONS accepts all three, running-only gating, exact status strings) survive without the bug narrative.

<details><summary>before</summary>

```
/**
 * One VM's actions as a menu, the three-dots half of VmActionBar.
 *
 * AppIconMenu's opposite number, and the differences are all things the two
 * kinds of guest genuinely do not share:
 *
 *  - No Open and no Logs. A VM has no catalog port to point a tab at, and
 *    Proxploy reads no journal from inside a QEMU guest.
 *  - Console is here only when this menu stands alone. It is the ONLY way
 *    into a VM at all, since Proxploy opens no web UI and reads no journal
 *    for a QEMU guest, which is exactly why VmActionBar spends its third
 *    button slot on it. Repeating it in the table row's menu would offer the
 *    same action twice a centimetre apart; omitting it from the grid's tile
 *    left a VM with no way in.
 *  - Shutdown, Pause and Resume are here. services/lifecycle.py's VM_ACTIONS
 *    already accepts all three (`pause` is Proxmox's `suspend`, mapped there
 *    and nowhere else), and the row's buttons carry only Start, Stop and
 *    Restart, so without these there was no way to reach them at all.
 *  - Clone replaces Reconfigure and Migrate, which are app-shaped operations.
 *
 * `lifecycle` is AppIconMenu's switch, and it is here for the bug it fixes:
 * this menu was written as the three-dots HALF of VmActionBar and then reused
 * whole as the icon grid's tile menu, where the other half does not exist. On
 * the Hosts page a stopped VM was offered Shutdown, which the backend turns
 * into a no-op, no way to start it, and no console. The grid takes the
 * default and gets the bar's controls back; the table row passes false, since
 * those sit a centimetre away there. The name is AppIconMenu's, and like
 * AppIconMenu (which gates Open on it too) it means "this menu is the only
 * affordance", not strictly "power actions".
 *
 * EVERY item that acts on a running guest is offered only while the guest is
 * running, and that now includes Shutdown. Pause and Resume already branched
 * on status; Shutdown branched on nothing, so it rendered on a stopped VM in
 * both surfaces. The backend tolerates it ("already stopped; nothing to do")
 * rather than failing, which is worse than a refusal: the click costs a job
 * row and changes nothing. "paused" and "running" are the exact strings the
 * row carries, written by the poller from PVE's own status field and by
 * services/lifecycle.py's RESULT_STATUS when an action finishes.
 *
 * Lifecycle actions route through the same `useLifecycle` mutation
 * LifecycleActions.fire uses, error handling included: a 409 self_target
 * escalates to ConfirmSelfDialog, and everything else surfaces a notify.error
 * toast rather than letting the optimistic "pending" patch revert in silence.
 */
```

</details>

**after**

```
/**
 * One VM's actions as a menu, the three-dots half of VmActionBar.
 *
 * Shutdown, Pause and Resume are here because services/lifecycle.py's
 * VM_ACTIONS accepts all three (`pause` is Proxmox's `suspend`, mapped there
 * and nowhere else) and the row's buttons carry only Start, Stop and Restart.
 * There is no Open and no Logs: a VM has no catalog port and Proxploy reads no
 * journal inside a QEMU guest.
 *
 * `lifecycle` means "this menu is the only affordance", not strictly "power
 * actions": the icon grid takes the default and so gets Console, the ONLY way
 * into a VM at all, while the table row passes false because the bar's buttons
 * sit a centimetre away.
 *
 * EVERY item that acts on a running guest is offered only while it is running,
 * Shutdown included: the backend answers a shutdown on a stopped VM with
 * "already stopped; nothing to do" rather than failing, so the click costs a
 * job row and changes nothing. "paused" and "running" are the exact strings the
 * row carries, from PVE's status field via the poller and from RESULT_STATUS.
 */
```

**`[902]`** `frontend/src/components/VmActionsMenu.tsx:101` &middot; **37w → 35w** (5% cut) &middot; _contract_  
Keeps which surface passes which value, in fewer words.

<details><summary>before</summary>

```
/** Include Start, or Stop and Restart. On by default, which is the icon
   *  grid's tile menu: it is the only way to act on that VM. VmActionBar
   *  passes false, since those are buttons beside the menu there. */
```

</details>

**after**

```
  /** Include Start, or Stop and Restart. On by default, the icon grid's tile
   *  menu, since it is the only way to act on that VM. VmActionBar passes
   *  false: those are buttons beside the menu there. */
```

**`[903]`** `frontend/src/components/VmActionsMenu.tsx:113` &middot; **44w → 35w** (20% cut) &middot; _buried-invariant_  
Keeps why the gate is host-shaped and shared with ConsoleButton.

<details><summary>before</summary>

```
// The console gate is host-shaped, not guest-shaped: it reads the host's
// console token and no entitlement flag, which is why ConsoleButton reads
// this same hook for VMs already. Sharing it is what keeps the menu item
// and the button from disagreeing about one host.
```

</details>

**after**

```
  // The console gate is host-shaped, not guest-shaped: it reads the host's
  // console token and no entitlement flag, which is why ConsoleButton reads the
  // same hook. Sharing it keeps the item and the button from disagreeing.
```

**`[904]`** `frontend/src/components/VmActionsMenu.tsx:124` &middot; **32w → 29w** (9% cut) &middot; _redundant_  
Same rule as the gate comment above; one compact statement is enough.

<details><summary>before</summary>

```
// Same wait-for-first-fetch rule as api/app-gates.ts's "innocent until
// proven guilty": has() reads false until /entitlements lands, so gating on
// it directly would grey these out on every plan for the whole first fetch.
```

</details>

**after**

```
  // Same "innocent until proven guilty" rule: has() reads false until
  // /entitlements lands, so gating on it directly would grey these out on every
  // plan for the whole first fetch.
```

**`[905]`** `frontend/src/components/VmActionsMenu.tsx:130` &middot; **39w → 24w** (38% cut) &middot; _surprising_  
The surprising flag reuse stays; the note about where it came from goes.

<details><summary>before</summary>

```
// Destroying a VM is gated on the same flag that creates one: the plan that
// may not make VMs may not unmake them either. This is what the detail
// page's Destroy button read before it was folded in here.
```

</details>

**after**

```
  // Destroying a VM is gated on the same flag that creates one: the plan that
  // may not make VMs may not unmake them either.
```

**`[906]`** `frontend/src/components/VmActionsMenu.tsx:135` &middot; **97w → 57w** (41% cut) &middot; _buried-invariant_  
Both invariants stay; the cross-references and anecdotes go.

<details><summary>before</summary>

```
// 'pending' is the optimistic patch useLifecycle writes between the click
// and the job resolving, not a state PVE reports, so neither table covers
// it. Falling through to STOPPED_ACTIONS would draw Start on a VM that is
// still running; LifecycleActions refuses the same guess for the same
// reason. Nothing at all is the honest answer while a job is in flight.
//
// 'paused' is not 'stopped' either. The guest is suspended, not off, so PVE
// refuses a start and Resume below is the way back; falling through to the
// stopped table drew Start and Resume on the same menu.
```

</details>

**after**

```
  // 'pending' is the optimistic patch useLifecycle writes between the click and
  // the job resolving, not a state PVE reports, so falling through to
  // STOPPED_ACTIONS would draw Start on a VM that is still running. 'paused' is
  // not 'stopped' either: the guest is suspended, not off, so PVE refuses a
  // start and Resume below is the way back.
```

**`[907]`** `frontend/src/components/VmActionsMenu.tsx:177` &middot; **32w → 20w** (38% cut) &middot; _redundant_  
The Stop/Shutdown distinction is already at the action tables; one line here is enough.

<details><summary>before</summary>

```
/* Shutdown, not another Stop: Stop is the hard kill, this is the
                graceful one PVE distinguishes it from (services/lifecycle.py).
                Only while the VM is running, for the reason in the doc above. */
```

</details>

**after**

```
            {/* Shutdown, not another Stop: Stop is the hard kill, this is the
                graceful one PVE distinguishes it from. Running only. */}
```

**`[908]`** `frontend/src/components/VmActionsMenu.tsx:201` &middot; **27w → 23w** (15% cut) &middot; _contract_  
States the ordering rule and why Console is conditional, in fewer words.

<details><summary>before</summary>

```
/* After every power item and before the rest, the order
                AppIconMenu already uses. Only when this menu stands alone:
                VmActionBar has a Console button welded beside it. */
```

</details>

**after**

```
            {/* After every power item and before the rest, AppIconMenu's
                order. Only when this menu stands alone: VmActionBar has a
                Console button beside it. */}
```

**`[909]`** `frontend/src/components/VmActionsMenu.tsx:213` &middot; **45w → 25w** (44% cut) &middot; _narration_  
Keeps the outside-the-switch rule and the no-role-gate rule.

<details><summary>before</summary>

```
/* Outside the `lifecycle` switch, so both surfaces carry it: it is not
                one of the three the table row keeps as buttons. Never gated to
                a role, as the button it replaced was not: it only navigates,
                and the Firewall page itself withholds the edit. */
```

</details>

**after**

```
            {/* Outside the `lifecycle` switch, so both surfaces carry it.
                Never gated to a role: it only navigates, and the Firewall page
                itself withholds the edit. */}
```

**`[910]`** `frontend/src/components/VmActionsMenu.tsx:237` &middot; **36w → 20w** (44% cut) &middot; _security_  
Keeps that the backend refuses it too and that the reason names the fix.

<details><summary>before</summary>

```
/* A running VM cannot be destroyed, and the reason says which
                thing to do first rather than leaving a dead item to guess at.
                The backend refuses it too; this is the near half of that. */
```

</details>

**after**

```
            {/* A running VM cannot be destroyed, and the reason says which
                thing to do first. The backend refuses it too. */}
```

**`[911]`** `frontend/src/components/VmActionsMenu.tsx:272` &middot; **133w → 76w** (43% cut) &middot; _implementation-diary_  
Keeps the typed-confirmation invariant and the no-second-confirm rule, cuts the detail-page history.

<details><summary>before</summary>

```
/**
 * DELETE /vms/{id}. The single most destructive route in the product.
 *
 * It used to be a button on the VM's own detail page, on the reasoning that a
 * list row was too easy a place to slip. That page is gone, and the slip is
 * covered where it matters: this opens with a typed confirmation of the VM
 * name (ConfirmSelfDialog) and destroys nothing until that name is typed, so
 * a mis-click lands on a dialog rather than on a deleted disk. A second
 * confirm in front of it would only train the operator to click through both.
 *
 * A running guest is refused up front (the menu item is disabled with the
 * reason visible) and the backend's own 409 detail is what shows if that state
 * changed underneath us anyway, never a generic failure toast.
 */
```

</details>

**after**

```
/**
 * DELETE /vms/{id}. The single most destructive route in the product.
 *
 * It opens with a typed confirmation of the VM name (ConfirmSelfDialog) and
 * destroys nothing until that name is typed. A second confirm in front of it
 * would only train the operator to click through both.
 *
 * A running guest is refused up front, with the reason on the disabled menu
 * item, and the backend's own 409 detail is what shows if that state changed
 * underneath us anyway.
 */
```

**`[912]`** `frontend/src/components/VmActionsMenu.tsx:306` &middot; **39w → 27w** (31% cut) &middot; _test-reference_  
Keeps the race and the verbatim-backend-sentence rule, drops the aside about the string being untested.

<details><summary>before</summary>

```
// guest_running/confirm_required races (the VM's state changed between
// opening the dialog and confirming) get the backend's own sentence
// verbatim; self_target is restated plainly rather than assuming its
// wording, is_self() is always false today so the real string is
// untested here.
```

</details>

**after**

```
        // guest_running/confirm_required races (the VM's state changed
        // between opening the dialog and confirming) get the backend's own
        // sentence verbatim; self_target is restated plainly rather than
        // assuming its wording.
```


### 🟢 KEEP (2), unchanged

- **`[913]`** `110` &middot; _security_ &middot; `// Innocent until proven guilty, the rule every gate here follows: an`
- **`[914]`** `211` &middot; _surprising_ &middot; `/* No plan gate: reading and editing a VM's own settings is not a`

---

## `frontend/src/api/catalogMetadata.ts`

954 → 586 words, 39% cut. 2 delete, 12 shorten, 2 keep.


### 🔴 DELETE (2)

**`[915]`** `frontend/src/api/catalogMetadata.ts:78` &middot; 6w &middot; _separator_  
Section label over a run of fields; adds nothing the field names do not.

```
// Presentation facts about the resulting container.
```

**`[916]`** `frontend/src/api/catalogMetadata.ts:94` &middot; 2w &middot; _separator_  
Two-word section label.

```
// Links out.
```


### 🟡 SHORTEN (12)

**`[917]`** `frontend/src/api/catalogMetadata.ts:1` &middot; **284w → 142w** (50% cut) &middot; _implementation-diary_  
The ownership split and the five mistyped slugs are the load-bearing upstream quirk and stay; the numbered why-this-file-exists framing goes.

<details><summary>before</summary>

```
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
```

</details>

**after**

```
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
```

**`[918]`** `frontend/src/api/catalogMetadata.ts:37` &middot; **54w → 36w** (33% cut) &middot; _external-quirk_  
Units and the upstream-writes-0 quirk both stay; the parenthetical goes.

<details><summary>before</summary>

```
/** cpu is cores, ram is MiB, hdd is GB, os/version are the template's, e.g.
 *  Debian 13. Upstream writes 0 rather than null for a script that does not
 *  create a container of its own (an addon-style script), so a consumer has
 *  to treat a non-positive number as "no figure", not as "runs on nothing". */
```

</details>

**after**

```
/** cpu is cores, ram is MiB, hdd is GB, os/version are the template's.
 *  Upstream writes 0 rather than null for a script that creates no container of
 *  its own, so a non-positive number means "no figure". */
```

**`[919]`** `frontend/src/api/catalogMetadata.ts:49` &middot; **41w → 30w** (27% cut) &middot; _external-quirk_  
Keeps the never-print-this-script rule, trims the examples.

<details><summary>before</summary>

```
/** One installable profile of the same app, e.g. the Debian default and an
 *  Alpine variant (`syncthing`, `mariadb`, `rustdeskserver` have two).
 *
 *  `script` is null in every record we have. The real script is the
 *  top-level, discovery-owned `script_path`; nothing should print this one. */
```

</details>

**after**

```
/** One installable profile of the same app, e.g. a Debian default and an
 *  Alpine variant. `script` is null in every record we have; the runnable one
 *  is the discovery-owned `script_path`. */
```

**`[920]`** `frontend/src/api/catalogMetadata.ts:61` &middot; **27w → 22w** (19% cut) &middot; _external-quirk_  
Keeps the corpus values and the neutral fallback rule, drops the framing.

<details><summary>before</summary>

```
/** Upstream's post-install notes. `type` is one of info | warning | warn |
 *  general | default across the corpus, so anything that is not clearly a
 *  warning is treated as neutral. */
```

</details>

**after**

```
/** Upstream's post-install notes. `type` is one of info | warning | warn |
 *  general | default, so anything not clearly a warning is treated as
 *  neutral. */
```

**`[921]`** `frontend/src/api/catalogMetadata.ts:66` &middot; **24w → 22w** (8% cut) &middot; _security_  
Keeps the third-party markdown warning, trims the aside about links.

<details><summary>before</summary>

```
/** Upstream's GitHub release snapshot. `changelog` is MARKDOWN written by a
 *  third party, with links and `\r\n` line endings. It is never HTML to us. */
```

</details>

**after**

```
/** Upstream's GitHub release snapshot. `changelog` is MARKDOWN written by a
 *  third party, with `\r\n` line endings. It is never HTML to us. */
```

**`[922]`** `frontend/src/api/catalogMetadata.ts:105` &middot; **160w → 80w** (50% cut) &middot; _narration_  
Keeps why the fields are served top-level, the 9 uncovered rows and the script_path exception; trims the rest.

<details><summary>before</summary>

```
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
```

</details>

**after**

```
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
```

**`[923]`** `frontend/src/api/catalogMetadata.ts:134` &middot; **38w → 19w** (50% cut) &middot; _contract_  
Keeps the unknown-in contract, drops the repeated optionality note.

<details><summary>before</summary>

```
/** Read those fields off a serialized row. `unknown` in, so this compiles
 *  whether or not `CatalogRow` has grown them, and every field stays optional
 *  so a row that predates them reads as absent rather than as a value. */
```

</details>

**after**

```
/** Read those fields off a serialized row. `unknown` in, so this compiles
 *  whether or not `CatalogRow` has grown them. */
```

**`[924]`** `frontend/src/api/catalogMetadata.ts:142` &middot; **61w → 36w** (41% cut) &middot; _contract_  
Keeps the return contract and why the parameter is `unknown`.

<details><summary>before</summary>

```
/**
 * Pull `metadata` out of a detail row's `raw` blob, or null if it is not
 * there.
 *
 * Takes `unknown` on purpose: the caller passes `detail.raw`, whose declared
 * type in api/catalog.ts predates this field, and widening that type is the
 * owning file's change to make. Checking the shape at runtime here means this
 * stays correct whether that type is widened later or not.
 */
```

</details>

**after**

```
/** Pull `metadata` out of a detail row's `raw` blob, or null if it is not
 *  there. Takes `unknown` because the caller passes `detail.raw`, whose
 *  declared type predates this field, so the shape is checked at runtime. */
```

**`[925]`** `frontend/src/api/catalogMetadata.ts:158` &middot; **40w → 28w** (30% cut) &middot; _external-quirk_  
Keeps the JSON-column quirk and the render-nothing rule.

<details><summary>before</summary>

```
/** Array fields arrive from a JSON column, so "it is declared as an array" is
 *  not the same as "it is an array". Anything else reads as empty, which
 *  renders as nothing at all rather than throwing inside a .map(). */
```

</details>

**after**

```
/** Array fields arrive from a JSON column, so "declared as an array" is not
 *  "is an array". Anything else reads as empty rather than throwing in a
 *  .map(). */
```

**`[926]`** `frontend/src/api/catalogMetadata.ts:165` &middot; **29w → 26w** (10% cut) &middot; _external-quirk_  
Keeps the empty-string-for-unset quirk, trims the field list.

<details><summary>before</summary>

```
/** A string that actually says something. Upstream uses "" for unset far more
 *  often than null (`default_user`, `default_passwd`, `pin_reason`), and an
 *  empty string must render nothing, not an empty row. */
```

</details>

**after**

```
/** A string that actually says something. Upstream uses "" for unset far more
 *  often than null, and an empty string must render nothing, not an empty
 *  row. */
```

**`[927]`** `frontend/src/api/catalogMetadata.ts:174` &middot; **28w → 21w** (25% cut) &middot; _external-quirk_  
Keeps the upstream-0 quirk, drops the cross-reference.

<details><summary>before</summary>

```
/** A figure worth printing. Upstream's 0 means "no figure recorded" for every
 *  resource it writes (see UpstreamResources), and "0 GB disk" would be a
 *  claim, not a blank. */
```

</details>

**after**

```
/** A figure worth printing. Upstream's 0 means "no figure recorded", and
 *  "0 GB disk" would be a claim, not a blank. */
```

**`[928]`** `frontend/src/api/catalogMetadata.ts:181` &middot; **130w → 94w** (28% cut) &middot; _implementation-diary_  
The XSS rule and the CRLF reason stay in full; the paragraph about not adding a markdown renderer shrinks.

<details><summary>before</summary>

```
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
```

</details>

**after**

```
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
```


### 🟢 KEEP (2), unchanged

- **`[929]`** `86` &middot; _security_ &middot; `// First-run facts. `default_passwd` is upstream's PUBLISHED default, not a`
- **`[930]`** `100` &middot; _surprising_ &middot; `// Upstream's dates for the SCRIPT, not for our sync.`