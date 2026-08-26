"""A stable-enough identity for the machine this install runs on.

Only hashed component digests ever leave the box. The licensing service
compares digests and never learns a MAC, a machine-id or a disk UUID, which
keeps a compromise of that service from yielding an inventory of customer
hardware.

Stability is the hard part in both directions. Too strict and a NIC swap or
a resized VM reads as a different machine, so a customer loses their seat for
maintenance. Too loose and every Proxmox host cloned from the same image
looks identical. Five weak signals matched 3-of-5 server-side is the
compromise: a clone matches all five, ordinary maintenance moves one or two.
"""
import hashlib
import subprocess
import uuid
from pathlib import Path

# Salts the digests so they are not a rainbow table of every machine-id in
# existence. Not a secret: it ships in the source, and a self-hoster can read
# and change it. Fingerprinting is a clone signal, not an authorisation
# control; the credential is what actually authorises.
PEPPER = b"proxploy-fingerprint-v1"


def _digest(label: str, value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if not v or v in {"none", "unknown", "not specified", "to be filled by o.e.m."}:
        return None
    return hashlib.sha256(PEPPER + label.encode() + b":" + v.encode()).hexdigest()[:32]


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _root_fs_uuid() -> str | None:
    try:
        out = subprocess.run(["findmnt", "-no", "UUID", "/"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _primary_mac() -> str | None:
    """The MAC of the interface holding the default route, not the lowest
    numbered one: interface naming is not stable across kernel upgrades but
    the routed interface is the one that follows the machine."""
    try:
        route = subprocess.run(["ip", "-o", "route", "get", "1.1.1.1"],
                               capture_output=True, text=True, timeout=5).stdout.split()
        dev = route[route.index("dev") + 1]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return (_read(f"/sys/class/net/{dev}/address") or "").strip() or None


def collect() -> list[str]:
    """Component digests, order-independent server-side. Components that
    cannot be read are dropped rather than sent as a placeholder: a shared
    "unknown" would match across unrelated machines and manufacture a quorum
    out of nothing."""
    parts = [
        _digest("machine-id", _read("/etc/machine-id")),
        _digest("product-uuid", _read("/sys/class/dmi/id/product_uuid")),
        _digest("board-serial", _read("/sys/class/dmi/id/board_serial")),
        _digest("root-fs", _root_fs_uuid()),
        _digest("mac", _primary_mac()),
    ]
    return [p for p in parts if p]


def new_installation_id() -> str:
    """Deliberately random, not derived from hardware: an installation is a
    Proxploy deployment, and the same box can host two of them."""
    return str(uuid.uuid4())
