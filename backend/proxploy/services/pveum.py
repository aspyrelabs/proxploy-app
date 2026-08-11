"""Generate the copy-paste `pveum` script doc 08 §2 step 2 specifies.

The operator runs this in a node shell they already own, so Proxploy never
asks for root credentials, even transiently, and never has to be trusted with
them. It creates one dedicated PVE user, one custom role per chosen
capability, and one privilege-separated token per capability.

The privilege sets are transcribed from doc 08's capability -> role table.
They are the single source of truth for both this script and the enrolment
verifier in api/hosts.py, so a token this script creates always satisfies the
check that runs against it. Deriving one from the other, in either direction,
is how they drift.

Privilege names must be re-verified against the target PVE major version when
they change; PVE occasionally splits privileges, as it did with VM.Config.*.
"""
from __future__ import annotations

from dataclasses import dataclass

PVE_USER = "proxploy@pve"


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    role: str
    token: str
    privileges: tuple[str, ...]
    why: str
    required: bool = False


# Order matters: it is the order the script emits, and monitoring first is
# what makes a half-read script still a working one.
CAPABILITIES: dict[str, Capability] = {
    "monitoring": Capability(
        key="monitoring", label="Read-only monitoring", role="ProxployAudit",
        token="monitoring", required=True,
        privileges=("VM.Audit", "Datastore.Audit", "Sys.Audit", "Pool.Audit",
                    "SDN.Audit"),
        why="Pollers, dashboard, metrics, and every read view. Always required."),
    "lifecycle": Capability(
        key="lifecycle", label="Lifecycle", role="ProxployLifecycle",
        token="lifecycle",
        privileges=("VM.PowerMgmt", "VM.Config.Disk", "VM.Config.CPU",
                    "VM.Config.Memory", "VM.Config.Network", "VM.Config.Options",
                    "VM.Allocate", "VM.Clone", "VM.Snapshot",
                    "VM.Snapshot.Rollback", "VM.Migrate"),
        why="Start/stop/restart, resource edits, snapshots, clone, migration, "
            "and VM create/destroy."),
    "console": Capability(
        key="console", label="Console", role="ProxployConsole", token="console",
        privileges=("VM.Console",),
        why="Console tickets for containers and VMs."),
    "backup": Capability(
        key="backup", label="Backup", role="ProxployBackup", token="backup",
        privileges=("VM.Backup", "Datastore.AllocateSpace", "Datastore.Audit"),
        why="vzdump/PBS backup and restore jobs, and backup listing."),
}

# Sys.Console is effectively root on the node, so it is never folded into the
# console capability: it is a separate, explicit opt-in (doc 08 §2 and §9).
NODE_SHELL_PRIVILEGE = "Sys.Console"

MONITORING_PRIVILEGES: tuple[str, ...] = CAPABILITIES["monitoring"].privileges

_HEADER = """\
# Proxploy: least-privilege Proxmox access.
#
# Review this before you run it. It runs as root on one node of your cluster and
# makes no changes to any guest. It creates:
#   - one PVE user, {user}, with no password and no login shell
#   - one custom role per capability you chose
#   - one privilege-separated token per capability
#
# Each `user token add` prints a secret ONCE. Copy each one into Proxploy as
# you go; Proxmox cannot show them again.
#
# Proxploy never asks for your root credentials. You run this yourself, and
# hand back only the tokens.
"""


def _privileges_for(cap: Capability, node_shell: bool) -> tuple[str, ...]:
    if cap.key == "console" and node_shell:
        return cap.privileges + (NODE_SHELL_PRIVILEGE,)
    return cap.privileges


def generate_script(capabilities: list[str], *, path: str = "/",
                    node_shell: bool = False) -> str:
    """Return the script for `capabilities`, monitoring always included.

    `path` is where the ACLs are granted. "/" is the default because Proxploy
    is a whole-host manager; narrowing it to /pool/<name> is doc 08's supported
    way to scope Proxploy to part of a cluster.
    """
    unknown = [c for c in capabilities if c not in CAPABILITIES]
    if unknown:
        # Silently dropping a capability would produce a script that looks
        # complete and quietly cannot do what was asked of it.
        raise ValueError(f"unknown capability: {', '.join(sorted(unknown))}")

    chosen = [c for c in CAPABILITIES.values()
              if c.required or c.key in capabilities]

    lines = [_HEADER.format(user=PVE_USER), "",
             f"pveum user add {PVE_USER} --comment 'Proxploy'", ""]

    for cap in chosen:
        privs = ",".join(_privileges_for(cap, node_shell))
        token_id = f"{PVE_USER}!{cap.token}"
        lines += [
            f"# {cap.label}: {cap.why}",
            f"pveum role add {cap.role} -privs '{privs}'",
            f"pveum acl modify {path} -user {PVE_USER} -role {cap.role}",
            f"pveum user token add {PVE_USER} {cap.token} --privsep 1",
            # A privsep token's effective rights are the intersection of its
            # own ACLs with the user's, so granting only the user above leaves
            # the token able to do precisely nothing.
            f"pveum acl modify {path} -token '{token_id}' -role {cap.role}",
            "",
        ]

    return "\n".join(lines)
