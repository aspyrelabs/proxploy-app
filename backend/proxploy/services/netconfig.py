"""The `netN=` string round-tripper (doc 01 §6 "Guest network config").

Proxmox stores a guest NIC as one comma-joined `k=v` string, and the NIC model
and its MAC address share a single head token: `virtio=AA:BB:CC:DD:EE:FF`.
That is the whole reason this module exists. Editing a NIC means read the
string, change one key, write the string back; never rebuild it from a typed
struct, because anything the struct does not model (the MAC, `queues`, an
option a future PVE adds) would be dropped, and a dropped MAC means Proxmox
mints a new random one at next start, breaking every DHCP reservation and
MAC-bound licence pointed at that guest.

So: parse to an ORDER-PRESERVING dict of raw strings, mutate that dict, join it
back. No key is interpreted, no value is normalised, nothing is sorted.
`build_net(parse_net(s)) == s` for every string PVE emits (tests/test_netconfig.py).
"""
from __future__ import annotations

# The qemu NIC models PVE accepts. Used ONLY to recognise which token is the
# model=MAC head token when reporting a NIC's identity to the UI: never to
# validate or rewrite it.
QEMU_MODELS = frozenset({
    "virtio", "e1000", "e1000-82540em", "e1000-82544gc", "e1000-82545em",
    "e1000e", "i82551", "i82557b", "i82559er", "ne2k_isa", "ne2k_pci",
    "pcnet", "rtl8139", "vmxnet3",
})


def parse_net(value: str) -> dict:
    """`"virtio=AA:BB,bridge=vmbr0"` -> `{"virtio": "AA:BB", "bridge": "vmbr0"}`.

    Insertion order is the file order. A token with no `=` maps to None so
    build_net can emit it bare again rather than as `token=`.
    """
    parts: dict[str, str | None] = {}
    for token in value.split(","):
        if not token:
            continue
        key, sep, val = token.partition("=")
        parts[key] = val if sep else None
    return parts


def build_net(parts: dict) -> str:
    """The exact inverse of parse_net, in dict order."""
    return ",".join(k if v is None else f"{k}={v}" for k, v in parts.items())


def nic_identity(parts: dict) -> dict:
    """-> {"model", "macaddr"} for both flavours.

    qemu puts them in one head token (`virtio=AA:BB:...`); lxc splits them
    across `type=veth` and `hwaddr=`. Read-only, neither value is ever
    written back by this module's callers.
    """
    for key, val in parts.items():
        if key in QEMU_MODELS:
            return {"model": key, "macaddr": val}
    return {"model": parts.get("type") or "veth", "macaddr": parts.get("hwaddr")}
