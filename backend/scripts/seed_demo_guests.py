"""Seed the dev database with believable apps and VMs, to look at the UI.

This exists because the lab nodes are usually off, and an empty Hosts page
says nothing about how a full one reads. It writes ONLY to the dev database
and touches nothing the poller owns beyond the rows it creates.

    .venv/bin/python scripts/seed_demo_guests.py          # add
    .venv/bin/python scripts/seed_demo_guests.py --remove # take them away again

Idempotent: re-running adds nothing, so it is safe to fire twice.

TWO THINGS TO KNOW BEFORE THE NUMBERS LOOK WRONG.

1. The poller blanks these. While a host is unreachable, every cycle sweeps
   its guests to "unknown" and nulls their readings, which is the whole point
   of that fix. Seeded rows therefore go grey within a poll cycle. To hold
   them still, run the backend with PROXPLOY_POLL_ENABLED=false.

2. RAM will read unknown even so. api/apps.py serves mem_total_bytes from the
   poller's live in-memory snapshot rather than a column, so there is no row
   here that can supply it. CPU, storage and network all come from columns and
   do show.
"""
from __future__ import annotations

import sys

# Names chosen to exercise the layout rather than to be realistic: a very long
# one, a hyphenated one, a short one, mixed case. If the grid or the table
# mishandles any of those, it shows here rather than in production.
APPS = [
    # (ctid, name, catalog_slug, status, cpu%, mem, disk used, disk total, net in B/s, net out B/s, uptime s)
    (201, "jellyfin", "jellyfin", "running", 34.2, 3_221_225_472, 48_000_000_000, 137_438_953_472, 2_400_000, 180_000, 604_800),
    (202, "vaultwarden", "vaultwarden", "running", 0.8, 134_217_728, 1_073_741_824, 8_589_934_592, 3_100, 900, 1_209_600),
    (203, "immich-photo-library", "immich", "running", 61.5, 6_442_450_944, 512_000_000_000, 1_099_511_627_776, 8_900_000, 1_200_000, 259_200),
    (204, "home-assistant", "homeassistant", "running", 12.1, 1_610_612_736, 6_442_450_944, 34_359_738_368, 41_000, 28_000, 2_592_000),
    (205, "pihole", "pihole", "running", 2.4, 268_435_456, 2_147_483_648, 17_179_869_184, 12_000, 9_400, 5_184_000),
    (206, "grafana", "grafana", "stopped", None, None, 3_221_225_472, 21_474_836_480, None, None, None),
    (207, "paperless", "paperless-ngx", "running", 7.9, 1_073_741_824, 22_000_000_000, 68_719_476_736, 0, 0, 86_400),
    (208, "adguard-home", "adguard", "paused", None, None, 1_610_612_736, 8_589_934_592, None, None, None),
    (209, "npm", "nginxproxymanager", "running", 1.2, 201_326_592, 900_000_000, 8_589_934_592, 620_000, 740_000, 1_814_400),
    (210, "plex", "plex", "stopped", None, None, 64_000_000_000, 137_438_953_472, None, None, None),
]

VMS = [
    # (vmid, name, status, cores, mem, disk, uptime s, os)
    (301, "win11-workstation", "running", 8, 17_179_869_184, 274_877_906_944, 172_800, "win11"),
    (302, "ubuntu-build-runner", "running", 4, 8_589_934_592, 107_374_182_400, 86_400, "l26"),
    (303, "opnsense-edge", "running", 2, 4_294_967_296, 34_359_738_368, 7_776_000, "other"),
    (304, "truenas-scale", "running", 6, 34_359_738_368, 8_796_093_022_208, 3_888_000, "l26"),
    (305, "k3s-node-01", "running", 4, 8_589_934_592, 68_719_476_736, 1_209_600, "l26"),
    (306, "k3s-node-02", "running", 4, 8_589_934_592, 68_719_476_736, 1_209_600, "l26"),
    (307, "win-server-2022-dc", "stopped", 4, 8_589_934_592, 137_438_953_472, None, "win11"),
    (308, "debian-testing-sandbox", "stopped", 2, 2_147_483_648, 21_474_836_480, None, "l26"),
    (309, "macos-ventura-lab", "paused", 6, 16_106_127_360, 214_748_364_800, None, "other"),
]

DEMO_CTIDS = {a[0] for a in APPS}
DEMO_VMIDS = {v[0] for v in VMS}


def main() -> int:
    from proxploy.config import Settings
    from proxploy.db import make_engine, make_sessionmaker
    from proxploy.models import App, Host, Vm, utcnow

    remove = "--remove" in sys.argv
    db = make_sessionmaker(make_engine(Settings()))()
    try:
        hosts = db.query(Host).order_by(Host.id).all()
        if not hosts:
            print("No hosts in the database. Add one first, the guests need an owner.")
            return 1

        if remove:
            apps = db.query(App).filter(App.ctid.in_(DEMO_CTIDS)).all()
            vms = db.query(Vm).filter(Vm.vmid.in_(DEMO_VMIDS)).all()
            for row in (*apps, *vms):
                db.delete(row)
            db.commit()
            print(f"Removed {len(apps)} demo apps and {len(vms)} demo VMs.")
            return 0

        # Spread across whatever hosts exist, so a clustered pair shows guests
        # on both sides rather than piling everything on the first one.
        added_apps = 0
        for i, (ctid, name, slug, status, cpu, mem, disk, disk_total,
                net_in, net_out, uptime) in enumerate(APPS):
            host = hosts[i % len(hosts)]
            if db.query(App).filter_by(host_id=host.id, ctid=ctid).first():
                continue
            db.add(App(
                host_id=host.id, ctid=ctid, name=name, slug=f"demo-{name}-{ctid}",
                catalog_slug=slug, node_name=host.node_name,
                status_cached=status, cpu_pct_cached=cpu, mem_bytes_cached=mem,
                disk_bytes_cached=disk, disk_total_bytes_cached=disk_total,
                net_in_bps_cached=net_in, net_out_bps_cached=net_out,
                net_sampled_at=utcnow() if net_in is not None else None,
                uptime_s_cached=uptime,
                # The initials tile is the fallback when the catalog has no
                # logo for a slug. Seeding it means every card has something
                # to draw even if the icon cache is cold.
                icon_initials=name[:2].upper(),
                icon_colors={"c1": "#F5B544", "c2": "#E0862B"},
            ))
            added_apps += 1

        added_vms = 0
        for i, (vmid, name, status, cores, mem, disk, uptime, os_type) in enumerate(VMS):
            host = hosts[i % len(hosts)]
            if db.query(Vm).filter_by(host_id=host.id, vmid=vmid).first():
                continue
            db.add(Vm(
                host_id=host.id, vmid=vmid, name=name, status=status,
                node_name=host.node_name, os_type=os_type, cpu_cores=cores,
                mem_bytes=mem, disk_bytes=disk, uptime_s=uptime,
                synced_at=utcnow(), template=False,
            ))
            added_vms += 1

        db.commit()
        print(f"Added {added_apps} apps and {added_vms} VMs across "
              f"{len(hosts)} host(s): {', '.join(h.name for h in hosts)}")
        print("Reminder: the poller blanks these while a host is unreachable. "
              "Run the backend with PROXPLOY_POLL_ENABLED=false to hold them still.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
