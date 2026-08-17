#!/usr/bin/env python3
"""What FakePVE cannot answer about cluster peer enrolment (doc 12).

Five claims the app depends on, none of which a fake can prove, checked
against a real cluster:

  1. `/cluster/status` node rows carry an `ip`, and exactly one row carries
     `local` (without it a standalone node offers itself as its own peer).
  2. That `ip` actually answers TLS on 8006. PVE reports the corosync ring0
     address, which on a split cluster/management network need not be the
     address the API listens on. If this fails, the panel offers addresses
     that can never be enrolled.
  3. Every node presents the certificate the panel displays, and still
     presents it a moment later. The whole pin-then-echo design rests on
     this: POST /hosts/{id}/peers refuses any node whose certificate has
     changed since discovery showed it, so a certificate that varies between
     two reads would refuse every honest enrolment.
  4. The origin host's API token authenticates against its peers. Token
     enrolment copies one node's token to the rest of the cluster on the
     premise that PVE replicates it cluster-wide.
  5. A pinned fingerprint is enforced: the right one connects, a wrong one is
     refused. An unenforced pin is worse than no pin, because the UI says the
     node is pinned.

Runs the same functions the app runs (services/proxmox.py). Reads nothing
from the Proxploy database and writes nothing anywhere, so it is safe to
point at production hardware.

Usage:
  PROXPLOY_TOKEN_SECRET=... python scripts/verify_cluster_peers.py \
      --address https://192.168.50.10:8006 --token-id 'root@pam!proxploy'

Record the outcome, the date and the PVE version in
docs/12-hardware-verification.md next to the matching entry.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxploy.services.proxmox import (  # noqa: E402
    ProxmoxClient, ProxmoxError, tls_fingerprint_sha256)

FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if detail:
        print(f"        {detail}")
    if not ok:
        FAILED.append(label)
    return ok


def note(text: str) -> None:
    print(f"  ....  {text}")


def fingerprint(host: str, port: int = 8006) -> tuple[str | None, str]:
    """(fingerprint, why-not). Mirrors api/hosts.py::_fingerprint_now."""
    try:
        return tls_fingerprint_sha256(host, port), ""
    except (OSError, ProxmoxError) as e:
        return None, str(e)


def probe_peer(row: dict, args, secret: str, seen: dict) -> None:
    node, ip = row.get("name"), row.get("ip")
    print(f"\n{node}")
    if not check(f"{node}: /cluster/status gives an address", bool(ip),
                 f"row: {json.dumps(row, sort_keys=True)}"):
        return

    address = f"https://{ip}:8006"
    fp, why = fingerprint(ip)
    if not check(f"{node}: answers TLS at {ip}:8006", fp is not None, why or fp):
        note("nothing further can be checked for this node; the panel would "
             "show it as unreachable and refuse to add it")
        return
    note(f"presenting {fp}")
    seen[node] = fp

    again, why = fingerprint(ip)
    check(f"{node}: presents the same certificate on a second read", again == fp,
          "" if again == fp else f"first {fp}, then {again or why}")

    try:
        v = ProxmoxClient(address, args.token_id, secret,
                          verify_tls=args.verify_tls).version()
    except ProxmoxError as e:
        check(f"{node}: accepts the origin's token", False, f"{e.kind}: {e}")
    else:
        check(f"{node}: accepts the origin's token", True,
              f"PVE {v.get('version')}")

    # Pinning is only consulted when verify_tls is off (services/proxmox.py
    # _connect), which is the self-signed case every default install is in.
    try:
        ProxmoxClient(address, args.token_id, secret, verify_tls=False,
                      tls_fingerprint=fp).version()
    except ProxmoxError as e:
        check(f"{node}: connects with its own certificate pinned", False, str(e))
    else:
        check(f"{node}: connects with its own certificate pinned", True)

    wrong = ("11" if not fp.startswith("11") else "22") + fp[2:]
    try:
        ProxmoxClient(address, args.token_id, secret, verify_tls=False,
                      tls_fingerprint=wrong).version()
    except ProxmoxError as e:
        check(f"{node}: refuses a pin that does not match", e.kind == "tls_fingerprint",
              str(e) if e.kind != "tls_fingerprint" else "")
    else:
        check(f"{node}: refuses a pin that does not match", False,
              "it connected anyway, so the pin the UI shows is decoration")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--address", required=True,
                   help="the origin host, as Proxploy stores it, e.g. "
                        "https://192.168.50.10:8006")
    p.add_argument("--token-id", required=True, help="e.g. 'root@pam!proxploy'")
    p.add_argument("--token-secret", default=os.environ.get("PROXPLOY_TOKEN_SECRET"),
                   help="defaults to $PROXPLOY_TOKEN_SECRET, so it stays out of "
                        "shell history")
    p.add_argument("--verify-tls", action="store_true",
                   help="off by default: a default PVE install serves a "
                        "self-signed certificate, which is the case the pin exists for")
    args = p.parse_args()
    if not args.token_secret:
        p.error("no token secret: pass --token-secret or set $PROXPLOY_TOKEN_SECRET")
    secret = args.token_secret

    url = urlparse(args.address)
    origin = ProxmoxClient(args.address, args.token_id, secret,
                           verify_tls=args.verify_tls)
    print(f"origin {args.address}")
    try:
        rows = origin.cluster_status()
    except ProxmoxError as e:
        print(f"  FAIL  the origin answers /cluster/status\n        {e.kind}: {e}")
        return 1
    check("the origin answers /cluster/status", True,
          f"PVE {origin.version().get('version')}")
    print("\n/cluster/status, verbatim:")
    print(json.dumps(rows, indent=2, sort_keys=True))

    cluster = next((r.get("name") for r in rows if r.get("type") == "cluster"), None)
    if not check("the origin is in a cluster", cluster is not None,
                 "" if cluster else "no row of type 'cluster'; this is a standalone "
                                    "node, which is the wrong host shape for these "
                                    "checks. Cluster two nodes and run it again."):
        return 1
    note(f"cluster {cluster!r}")

    nodes = [r for r in rows if r.get("type") == "node"]
    check("exactly one node row carries `local`",
          sum(1 for r in nodes if r.get("local")) == 1,
          f"{sum(1 for r in nodes if r.get('local'))} of {len(nodes)} node rows do; "
          f"the app uses that flag to tell a host apart from its peers")
    peers = [r for r in nodes if not r.get("local")]
    if not check("the cluster has at least one peer to enrol", bool(peers)):
        return 1

    seen: dict[str, str] = {}
    origin_fp, why = fingerprint(url.hostname, url.port or 8006)
    if check(f"the origin's own certificate is readable at {url.hostname}",
             origin_fp is not None, why):
        seen[f"{url.hostname} (origin)"] = origin_fp

    for row in peers:
        probe_peer(row, args, secret, seen)

    print("\ncertificates")
    for name, fp in seen.items():
        note(f"{name}: {fp}")
    if len(set(seen.values())) != len(seen):
        note("two nodes share a certificate. Nothing breaks (each node is "
             "pinned to what it actually presents), but the per-node "
             "certificate the code comments assume is not what this cluster does.")

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed:")
        for label in FAILED:
            print(f"  - {label}")
        return 1
    print("every check passed. Record the date and PVE version in "
          "docs/12-hardware-verification.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
