"""VM read + lifecycle endpoints (doc 05, Phase 2/3 rows). Pure cache mirror +
snapshot cpu."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api import firewall as fwapi
from proxploy.api.apps import LifecycleIn, enqueue_lifecycle
from proxploy.api.deps import (authorize, dedupe_vms, get_db,
                               require_entitlement, scope_vm)
from proxploy.api.firewall import (AliasIn, AliasPatch, IpSetIn, MemberIn,
                                   MemberPatch, MoveIn, OptionsIn, RuleIn,
                                   RulePatch)
from proxploy.api.jobs import enqueue_and_audit, job_out
from proxploy.api.network import NicIn, guest_nics, set_guest_nic
from proxploy.models import Host, User, Vm
from proxploy.services.audit import write_audit
from proxploy.services.hostclient import client_for_host, guest_node
from proxploy.services.lifecycle import VM_ACTIONS
from proxploy.services.netconfig import build_net, parse_net
from proxploy.services.proxmox import ProxmoxError
from proxploy.services.selfguard import is_self

router = APIRouter(prefix="/vms", tags=["vms"])

# Singletons so FastAPI's dependency cache (keyed on the callable) collapses
# repeated uses into one call per request, and so route-level dependencies=[...]
# and the parameter-level copy run the same auth check first (doc 10 "auth
# before entitlement" ordering invariant). scope_vm()'s default param "vm_id"
# matches every {vm_id} path segment in this router.
_read = authorize("vm", "read", scope_of=scope_vm())
_lifecycle = authorize("vm", "lifecycle", scope_of=scope_vm())
_snapshot = authorize("vm", "snapshot", scope_of=scope_vm())
_rollback = authorize("vm", "rollback", scope_of=scope_vm())
_create = authorize("vm", "create")               # host_id is body-carried, no id yet
_clone = authorize("vm", "clone", scope_of=scope_vm())
_remove = authorize("vm", "remove", scope_of=scope_vm())
_configure = authorize("vm", "configure", scope_of=scope_vm())
_fw_read = authorize("firewall", "read", scope_of=scope_vm())
_fw_guest = authorize("firewall", "guest", scope_of=scope_vm())


def _vm_out(v: Vm, host: Host, snapshots) -> dict:
    snap = snapshots.get(v.host_id)
    g = snap.guests.get(("qemu", v.vmid)) if snap else None
    return {
        "id": v.id, "host_id": v.host_id, "host_name": host.name,
        "vmid": v.vmid, "name": v.name, "status": v.status,
        # PVE's RAW ostype: "l26", "win11", "w2k19", "other", and so on. It is
        # deliberately not collapsed to "linux"/"windows" here, because that
        # mapping is presentation and the specific value is information the
        # API could never get back once thrown away. The client maps it for
        # the OS icon. NULL is still possible and is not an error: a VM the
        # poller has not reached yet, or one whose config read was refused.
        "os_type": v.os_type,
        "cpu_cores": v.cpu_cores,
        "cpu_pct": g["cpu_pct"] if g else None,
        # Identical shape and identical meaning to apps.py::_app_out, which is
        # the whole point: memory and storage are each a used/allocated PAIR so
        # a card can draw a bar, and network is two rates with no denominator
        # because there is no link speed to divide by. These used to be one
        # number each here, holding the ALLOCATION under names that meant
        # USAGE on an app, so the VMs page could draw a CPU meter and nothing
        # else. See the Vm model and migration a1f4d80c3e69.
        #
        # Null is normal on every one of them and is not an error: a VM the
        # poller has not reached yet, a stopped guest, and (permanently, for
        # disk_bytes) a VM with no QEMU guest agent installed all land here.
        "mem_bytes": v.mem_bytes, "mem_total_bytes": v.mem_total_bytes,
        "disk_bytes": v.disk_bytes, "disk_total_bytes": v.disk_total_bytes,
        "net_in_bps": v.net_in_bps_cached, "net_out_bps": v.net_out_bps_cached,
        "uptime_s": v.uptime_s,
        # A linked clone is only possible FROM a template, so the clone dialog
        # needs this to stop offering an option PVE always refuses.
        "template": bool(v.template),
        "node": v.node_name,
        # Tri-state on purpose, served raw as true / false / null: the agent
        # answered, Proxmox says this guest has no working agent, or nobody
        # knows (never probed, stopped, or the host was unreachable). Folding
        # null into false would tell an operator to install something that may
        # well already be there, and it is the false case that explains why
        # disk_bytes above is null for so many VMs.
        "guest_agent_ok": v.guest_agent_ok,
    }


@router.get("")
def list_vms(request: Request, host: int | None = None, db=Depends(get_db),
             user: User = Depends(_read)):
    hosts = {h.id: h for h in db.query(Host).all()}
    query = db.query(Vm)
    if host is not None:
        query = query.filter(Vm.host_id == host)
    # Deduped for the same reason the Hosts page is: the mirror holds one row
    # per (host, vmid) and a cluster reports every guest to every member, so
    # this listed each VM once per enrolled host (doc 12 check 18).
    rows = dedupe_vms(query.all(), hosts)
    rows.sort(key=lambda v: (v.name or "", v.id))
    return [_vm_out(v, hosts[v.host_id], request.app.state.poller.snapshots)
            for v in rows]


@router.get("/{vm_id}")
def vm_detail(request: Request, vm_id: int, db=Depends(get_db),
              user: User = Depends(_read)):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    return _vm_out(v, db.get(Host, v.host_id), request.app.state.poller.snapshots)


def _vm_and_host(db, vm_id: int):
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    host = db.get(Host, v.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    return v, host


# Registered ABOVE the /{vm_id}/{action} wildcard below: Starlette matches in
# registration order, and although that wildcard is POST-only today, doc 05's
# future two-segment siblings are not. Same WARNING as apps.py:266-271.
# test_network_api.py asserts this ordering by route index.
@router.get("/{vm_id}/network",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network(request: Request, vm_id: int, db=Depends(get_db),
               user: User = Depends(_read)):
    v, host = _vm_and_host(db, vm_id)
    return guest_nics(request, db, host, "qemu", v.vmid, v)


@router.put("/{vm_id}/network/{iface}",
            dependencies=[Depends(_configure),
                          Depends(require_entitlement("network.guest_config"))])
def vm_network_update(request: Request, vm_id: int, iface: str, body: NicIn,
                      db=Depends(get_db), user: User = Depends(_configure)):
    v, host = _vm_and_host(db, vm_id)
    return set_guest_nic(request, db, user, target_type="vm", target_id=v.id,
                         host=host, kind="qemu", vmid=v.vmid, iface=iface, body=body,
                         row=v)


# Above the lifecycle wildcard, same as /{vm_id}/network directly above:
# registered after it, "firewall" matches as an ACTION and never gets here.
@router.get("/{vm_id}/firewall/rules",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def vm_fw_rules(request: Request, vm_id: int, db=Depends(get_db),
                user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_rules(request, db, host, "qemu", v.vmid, v)


@router.post("/{vm_id}/firewall/rules", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.rules"))])
def vm_fw_rule_create(request: Request, vm_id: int, body: RuleIn,
                      db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_rule_create(request, db, user, host, "qemu", v.vmid, v, body)


@router.put("/{vm_id}/firewall/rules/{pos}",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.rules"))])
def vm_fw_rule_update(request: Request, vm_id: int, pos: int, body: RulePatch,
                      db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_rule_update(request, db, user, host, "qemu", v.vmid, v,
                                   pos, body)


@router.put("/{vm_id}/firewall/rules/{pos}/move",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.rules"))])
def vm_fw_rule_move(request: Request, vm_id: int, pos: int, body: MoveIn,
                    db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_rule_move(request, db, user, host, "qemu", v.vmid, v, pos,
                                 body)


@router.delete("/{vm_id}/firewall/rules/{pos}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.rules"))])
def vm_fw_rule_delete(request: Request, vm_id: int, pos: int,
                      digest: str | None = None, db=Depends(get_db),
                      user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_rule_delete(request, db, user, host, "qemu", v.vmid, v,
                                   pos, digest)


@router.get("/{vm_id}/firewall/options",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def vm_fw_options(request: Request, vm_id: int, db=Depends(get_db),
                  user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_options(request, db, host, "qemu", v.vmid, v)


@router.put("/{vm_id}/firewall/options",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.options"))])
def vm_fw_options_update(request: Request, vm_id: int, body: OptionsIn,
                         db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_options_update(request, db, user, host, "qemu", v.vmid, v,
                                      body)


@router.get("/{vm_id}/firewall/aliases",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def vm_fw_aliases(request: Request, vm_id: int, db=Depends(get_db),
                  user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_aliases(request, db, host, "qemu", v.vmid, v)


@router.post("/{vm_id}/firewall/aliases", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.objects"))])
def vm_fw_alias_create(request: Request, vm_id: int, body: AliasIn,
                       db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_alias_create(request, db, user, host, "qemu", v.vmid, v, body)


@router.put("/{vm_id}/firewall/aliases/{name}",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.objects"))])
def vm_fw_alias_update(request: Request, vm_id: int, name: str,
                       body: AliasPatch, db=Depends(get_db),
                       user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_alias_update(request, db, user, host, "qemu", v.vmid, v,
                                    name, body)


@router.delete("/{vm_id}/firewall/aliases/{name}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.objects"))])
def vm_fw_alias_delete(request: Request, vm_id: int, name: str,
                       digest: str | None = None, db=Depends(get_db),
                       user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_alias_delete(request, db, user, host, "qemu", v.vmid, v,
                                    name, digest)


@router.get("/{vm_id}/firewall/ipsets",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def vm_fw_ipsets(request: Request, vm_id: int, db=Depends(get_db),
                 user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipsets(request, db, host, "qemu", v.vmid, v)


@router.post("/{vm_id}/firewall/ipsets", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.objects"))])
def vm_fw_ipset_create(request: Request, vm_id: int, body: IpSetIn,
                       db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipset_create(request, db, user, host, "qemu", v.vmid, v, body)


@router.delete("/{vm_id}/firewall/ipsets/{name}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.objects"))])
def vm_fw_ipset_delete(request: Request, vm_id: int, name: str,
                       force: bool = False, digest: str | None = None,
                       db=Depends(get_db), user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipset_delete(request, db, user, host, "qemu", v.vmid, v,
                                    name, force, digest)


@router.get("/{vm_id}/firewall/ipsets/{name}/members",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def vm_fw_ipset_members(request: Request, vm_id: int, name: str,
                        db=Depends(get_db), user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipset_members(request, db, host, "qemu", v.vmid, v, name)


@router.post("/{vm_id}/firewall/ipsets/{name}/members", status_code=201,
             dependencies=[Depends(_fw_guest),
                           Depends(require_entitlement("firewall.objects"))])
def vm_fw_ipset_member_add(request: Request, vm_id: int, name: str,
                           body: MemberIn, db=Depends(get_db),
                           user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipset_member_add(request, db, user, host, "qemu", v.vmid,
                                        v, name, body)


# {cidr:path}: a CIDR contains a slash and a plain path parameter stops at the
# first one, so 10.0.0.0/8 would never match this route.
@router.put("/{vm_id}/firewall/ipsets/{name}/members/{cidr:path}",
            dependencies=[Depends(_fw_guest),
                          Depends(require_entitlement("firewall.objects"))])
def vm_fw_ipset_member_update(request: Request, vm_id: int, name: str,
                              cidr: str, body: MemberPatch,
                              db=Depends(get_db),
                              user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipset_member_update(request, db, user, host, "qemu",
                                           v.vmid, v, name, cidr, body)


@router.delete("/{vm_id}/firewall/ipsets/{name}/members/{cidr:path}",
               dependencies=[Depends(_fw_guest),
                             Depends(require_entitlement("firewall.objects"))])
def vm_fw_ipset_member_delete(request: Request, vm_id: int, name: str,
                              cidr: str, digest: str | None = None,
                              db=Depends(get_db),
                              user: User = Depends(_fw_guest)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_ipset_member_delete(request, db, user, host, "qemu",
                                           v.vmid, v, name, cidr, digest)


@router.get("/{vm_id}/firewall/refs",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.view"))])
def vm_fw_refs(request: Request, vm_id: int, type: str | None = None,
               db=Depends(get_db), user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_refs(request, db, host, "qemu", v.vmid, v, ref_type=type)


@router.get("/{vm_id}/firewall/log",
            dependencies=[Depends(_fw_read),
                          Depends(require_entitlement("firewall.log"))])
def vm_fw_log(request: Request, vm_id: int, start: int = 0, limit: int = 500,
              since: int | None = None, until: int | None = None,
              db=Depends(get_db), user: User = Depends(_fw_read)):
    v, host = _vm_and_host(db, vm_id)
    return fwapi.guest_log(request, db, host, "qemu", v.vmid, v, start=start,
                           limit=limit, since=since, until=until)


# --- VM Options ----------------------------------------------------------
#
# The settings on PVE's own Options tab that Proxploy can actually write, read
# off pve-manager 9.2.11's apidoc.js, PVE/API2/Qemu.pm and PVE/QemuServer.pm on
# 2026-08-20. Anything not named here is refused rather than forwarded: the
# config dict below is unpacked into a proxmoxer kwargs call, so the key space
# is a trust boundary, and a typo reaching PVE comes back as an unhelpful 500.
#
# There is deliberately NO table here of which key applies to a running guest
# and which waits for a restart. That is presentation, it changes with the
# guest's own `hotplug` setting, and the honest answer for any single write is
# whatever PVE's pending config says AFTER the write, which is what the PUT
# reports. A table here would be a second, staler source for the same fact.
OPTION_KEYS = (
    "name", "onboot", "startup", "ostype", "boot", "tablet", "hotplug", "acpi",
    "kvm", "freeze", "localtime", "startdate", "smbios1", "agent", "protection",
    "vmstatestorage",
)

# Settings PVE hands to root@pam and nobody else. They appear in NO privilege
# bucket in QemuServer's $check_vm_modify_config_perm, so its fall-through
# `else { die "only root can set '$opt' config" }` refuses them for every API
# token, however widely privileged. Proxploy authenticates as an API token
# (proxploy@pve!lifecycle), so there is no role change that would unlock these.
# Reported to the caller so the dialog can show them switched off with a
# reason, and refused here so a write never becomes a Proxmox 500.
RESTRICTED_OPTION_KEYS = ("spice_enhancements", "amd-sev", "intel-tdx")

# The options whose value is one comma-joined `k=v` string rather than a scalar.
# The caller sends an OBJECT of sub-keys for these and it is merged into the
# string PVE already holds, never used to rebuild it: see _merge_option.
PROPERTY_OPTION_KEYS = frozenset({"startup", "boot", "agent", "smbios1"})

# Property strings where PVE lets the FIRST sub-key's value be written bare,
# with no `name=` in front of it. `agent: 1` means `enabled=1`, `boot: cdn`
# means `legacy=cdn`, `startup: 2` means `order=2`. This mapping is what stops
# a merge producing two values for one sub-key; see _merge_option.
OPTION_DEFAULT_SUBKEY = {"startup": "order", "boot": "legacy", "agent": "enabled"}


def _pve_scalar(value):
    """A JSON scalar as PVE wants it on the wire: booleans are 1 and 0."""
    return (1 if value else 0) if isinstance(value, bool) else value


def _merge_option(key: str, existing: str, changes: dict) -> str:
    """Fold `changes` into the property string PVE already holds for `key`.

    Merged, never rebuilt, for the reason services/netconfig.py exists: a
    property string carries sub-keys this code does not model, and rebuilding
    drops them silently. `smbios1` is the case that matters most. It usually
    holds nothing but `uuid=`, the identifier a guest's operating system reads
    as its machine id, and rewriting it from a form's fields would hand the
    guest a new identity: Windows deactivates, licences bound to it stop
    matching, and anything keyed on the machine id treats it as a new host.
    So parse, change the named sub-keys only, join back in the same order.

    A sub-key set to null is removed. If that empties the string there is
    nothing left to write, and the caller turns "" into a delete of the whole
    key, because PVE has no representation for an empty property string.
    """
    parts = parse_net(existing)
    default_sub = OPTION_DEFAULT_SUBKEY.get(key)
    if default_sub and parts:
        head, head_value = next(iter(parts.items()))
        if head_value is None:
            # A bare head token is the default sub-key's VALUE, but parse_net
            # can only see a token with no "=" and reports it as a key with no
            # value. Naming it before the merge is what stops `agent: 1` plus
            # {"enabled": false} turning into `1,enabled=0`, which is two
            # values for one sub-key with the stale one first. PVE accepts the
            # named form (`agent=enabled=0`) and normalises it on write.
            parts = {default_sub: head,
                     **{k: v for k, v in parts.items() if k != head}}
    for sub, value in changes.items():
        if value is None:
            parts.pop(sub, None)
        else:
            parts[sub] = str(_pve_scalar(value))
    return build_net(parts)


# Both routes below split their PVE calls across TWO clients, the same split
# api/network.py::set_guest_nic uses and for the same reason. Reads (`/config`,
# `/pending`, the node's storage list) need only VM.Audit and go on the
# monitoring token, which is the one capability every enrolled host is
# guaranteed to have. The write needs VM.Config.Options and its neighbours and
# goes on lifecycle. Neither role carries the other's privileges, so running
# both halves through one client 403s on whichever half it is not entitled to.


@router.get("/{vm_id}/options",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("vms.options"))])
def vm_options(request: Request, vm_id: int, db=Depends(get_db),
               user: User = Depends(_read)):
    """Every Options-tab setting Proxploy can write, plus what is waiting.

    `values` carries ONLY the keys PVE actually holds, and that absence is
    information, not a gap to fill in. A setting missing from a VM's config is
    the setting at Proxmox's own default, which is not the same as the setting
    written to that default value: `qm set --acpi 1` pins acpi to 1 forever,
    while no acpi line at all means "whatever this Proxmox version defaults
    to". Reporting a missing key as its default would erase that distinction
    and the next save would pin every default the operator never touched.
    """
    v, host = _vm_and_host(db, vm_id)
    node = guest_node(host, v)
    try:
        client = client_for_host(request.app, db, host, capability="monitoring")
        cfg = client.guest_config("qemu", node, v.vmid)
        pending = client.guest_pending("qemu", node, v.vmid)
        storages = client.storages(node)
    except ProxmoxError as e:
        raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e
    return {
        "values": {k: cfg[k] for k in OPTION_KEYS if k in cfg},
        "pending": {k: pending[k] for k in OPTION_KEYS if k in pending},
        "restricted": list(RESTRICTED_OPTION_KEYS),
        # From the mirror, not a fifth call to PVE: the poller keeps this
        # fresh and every other VM route already answers from it.
        "running": v.status == "running",
        # For vmstatestorage, which is where PVE dumps a suspended machine's
        # memory, so only a store that accepts disk images can hold it.
        "storages": [s["storage"] for s in storages
                     if "images" in str(s.get("content") or "").split(",")],
    }


@router.put("/{vm_id}/options",
            dependencies=[Depends(_configure),
                          Depends(require_entitlement("vms.options"))])
def vm_options_update(request: Request, vm_id: int,
                      body: dict = Body(default={}), db=Depends(get_db),
                      user: User = Depends(_configure)):
    """Sparse edit of the Options tab. Absent leaves alone, null resets.

    Three-way on purpose, and the third way is the one that is easy to get
    wrong. A key ABSENT from the body is untouched. A key with a value is
    written. A key sent as null is DELETED from the VM's config, which is the
    only way to give a setting back to Proxmox's default: writing the default
    value instead records a decision the operator did not make, and it sticks
    even if a later Proxmox changes what the default is. PVE spells that
    removal `delete=<key>` on the same PUT, so both halves go in one call and
    the operator gets one atomic change rather than two.

    Not a job: PVE writes a guest config synchronously, so there is no task to
    follow and reporting one would be theatre. Whether the change is live or
    waiting for a restart comes from the guest's own pending config, read
    after the write; see ProxmoxClient.guest_config_update for why it cannot
    be read off the write's return value.
    """
    v, host = _vm_and_host(db, vm_id)
    ip = request.client.host if request.client else None

    blocked = [k for k in body if k in RESTRICTED_OPTION_KEYS]
    if blocked:
        raise HTTPException(403, {
            "error": "root_only_option",
            "detail": (f"Proxmox lets only the root account change "
                       f"{', '.join(sorted(blocked))}. Proxploy signs in with an "
                       f"API token, so this has to be done in the Proxmox web "
                       f"interface as root."),
        })
    unknown = [k for k in body if k not in OPTION_KEYS]
    if unknown:
        raise HTTPException(422, f"Proxploy cannot change: {', '.join(sorted(unknown))}")
    for key, value in body.items():
        wants_object = key in PROPERTY_OPTION_KEYS
        if value is None:
            continue
        if wants_object != isinstance(value, dict):
            raise HTTPException(422, (
                f"{key} takes a group of settings, not a single value."
                if wants_object else
                f"{key} takes a single value, not a group of settings."))
    if not body:
        raise HTTPException(422, "nothing to change")

    node = guest_node(host, v)
    try:
        writer = client_for_host(request.app, db, host, capability="lifecycle")
        reader = client_for_host(request.app, db, host, capability="monitoring")
        cfg = reader.guest_config("qemu", node, v.vmid)
    except ProxmoxError as e:
        # Its own audit action, for the reason api/network.py:261 spells out:
        # nothing has been sent to the machine yet, so an operator reading the
        # log must not see a row saying its settings were changed.
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="vm.options_read", target_type="vm", target_id=v.id,
                    params={"changed": sorted(body)}, result="error", ip=ip)
        raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e

    config: dict = {}
    removals: list[str] = []
    for key, value in body.items():
        if value is None:
            removals.append(key)
        elif key in PROPERTY_OPTION_KEYS:
            merged = _merge_option(key, str(cfg.get(key) or ""), value)
            # Every sub-key cleared leaves no string to write, and PVE has no
            # empty property string; the setting is simply gone.
            if merged:
                config[key] = merged
            else:
                removals.append(key)
        else:
            config[key] = _pve_scalar(value)
    if removals:
        config["delete"] = ",".join(removals)

    try:
        writer.guest_config_update("qemu", node, v.vmid, config)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action="vm.options",
                    target_type="vm", target_id=v.id,
                    params={"changed": sorted(body)}, result="error", ip=ip)
        raise HTTPException(502, {"error": "pve_error", "detail": str(e)}) from e
    write_audit(db, actor_type="user", actor_id=user.id, action="vm.options",
                target_type="vm", target_id=v.id,
                params={"changed": sorted(body)}, ip=ip)
    request.app.state.bus.publish("resource", {"type": "vm", "id": v.id,
                                               "change": "reconfigured"})

    detail = None
    try:
        pending = {k: p for k, p in reader.guest_pending("qemu", node, v.vmid).items()
                   if k in OPTION_KEYS}
        pending_reboot = any(k in pending for k in body)
    except ProxmoxError:
        # The settings are saved; only the follow-up question failed. Saying
        # "no restart needed" here would be a guess in the reassuring
        # direction, which is the bug this whole path exists to avoid.
        pending, pending_reboot = {}, True
        detail = ("The settings were saved, but Proxmox could not be asked whether "
                  "the running machine has them yet. Restart it if a change does "
                  "not show up.")
    return {"changed": sorted(body), "pending_reboot": pending_reboot,
            "pending": pending, "detail": detail}


# PVE's own name rule for a guest: a DNS-ish label, since it becomes the
# hostname the guest advertises.
VM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$")


def _pick_node(request: Request, host: Host, node: str | None) -> str:
    """Resolve and validate the target node for a create.

    The known-node list comes from the poller's snapshot for this host (its
    `nodes` entries are `{"node": name, …}`), falling back to `Host.node_name`
    for a host that has not been polled yet. A caller-supplied node is checked
    against that list; an unknown one is a 422 rather than a job that fails
    thirty seconds later inside Proxmox.
    """
    snap = request.app.state.poller.snapshots.get(host.id)
    known = [n["node"] for n in (snap.nodes if snap else []) if n.get("node")]
    if not known and host.node_name:
        known = [host.node_name]
    if node:
        if known and node not in known:
            raise HTTPException(422, f"node {node!r} is not on host {host.name} "
                                     f"(known: {', '.join(known)})")
        return node
    if not known:
        raise HTTPException(422, "this host has no known node yet; wait for the "
                                 "first poll or name a node explicitly")
    return known[0]


class VmCreateIn(BaseModel):
    host_id: int
    name: str
    node: str | None = None
    vmid: int | None = None
    cores: int = 2
    memory_mb: int = 2048
    disk_gb: int = 32
    storage: str = "local-lvm"
    iso: str | None = None
    bridge: str = "vmbr0"
    # Task 17's wizard has a VLAN field on its Network step. Pydantic ignores
    # unknown keys rather than rejecting them, so omitting this here would
    # silently drop the operator's tag and build an untagged NIC: a wrong
    # result that looks like a success. Declared, validated, and threaded
    # through to net0 below.
    vlan_tag: int | None = None
    ostype: str = "l26"
    start: bool = False


@router.post("", status_code=202,
             dependencies=[Depends(_create),
                           Depends(require_entitlement("vms.create"))])
def create_vm_route(request: Request, body: VmCreateIn, db=Depends(get_db),
                    user: User = Depends(_create)):
    """Validate the spec here, not in the job: a bad spec should be a 422 the
    operator sees while the form is still open, not a failed job in the history.
    """
    host = db.get(Host, body.host_id)
    if host is None:
        raise HTTPException(404, "host not found")
    if not VM_NAME_RE.match(body.name or ""):
        raise HTTPException(422, "name must be a hostname-shaped label: letters, "
                                 "digits, '.' and '-', starting with a letter or "
                                 "digit")
    for field, value in (("cores", body.cores), ("memory_mb", body.memory_mb),
                         ("disk_gb", body.disk_gb)):
        if value <= 0:
            raise HTTPException(422, f"{field} must be greater than zero")
    node = _pick_node(request, host, body.node)
    vmid = body.vmid
    if vmid is None:
        # Minted here so the 202 can name the id and the audit row records it.
        # cluster_nextid is advisory, not a reservation: between this call and
        # the job's POST another orchestrator can take the id, and PVE then
        # rejects the create. See create_vm()'s ponytail comment: no retry.
        client = client_for_host(request.app, db, host, capability="lifecycle")
        try:
            vmid = int(client.cluster_nextid())
        except ProxmoxError as e:
            raise HTTPException(502, str(e)) from e
    params = {"host_id": host.id, "node": node, "vmid": int(vmid),
              "name": body.name, "cores": body.cores, "memory_mb": body.memory_mb,
              "disk_gb": body.disk_gb, "storage": body.storage, "iso": body.iso,
              "bridge": body.bridge, "vlan_tag": body.vlan_tag,
              "ostype": body.ostype, "start": body.start}
    # Same hole app.install had: the Vm row is created by the job, so with no
    # name passed the row is labelled with the HOST and the history reads "VM
    # Create / pve1". The requested name and the minted vmid are both known
    # here, and the vmid is what PVE will call the guest either way.
    out = enqueue_and_audit(request, db, user, kind="vm.create",
                            target_type="host", target_id=host.id, params=params,
                            target_name=f"{body.name} (VM {int(vmid)}) on {host.name}")
    return {**out, "vmid": int(vmid)}


# Registered ABOVE the /{vm_id}/{action} wildcard: see the WARNING on that
# route. Out of order, `POST /vms/3/snapshots` lands in vm_lifecycle with
# action="snapshots" and 422s (test_post_snapshots_is_not_swallowed_by_the_
# lifecycle_wildcard proves it stays this way).

# PVE's own pve-configid shape, plus its 40-char ceiling. Enforced here because
# the value is interpolated into a Proxmox path segment, and because "current"
# is PVE's synthetic pseudo-snapshot name and must never be creatable.
SNAP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,39}$")


def _valid_snap_name(name: str) -> str:
    if not SNAP_NAME_RE.match(name or "") or name == "current":
        raise HTTPException(422, "snapshot name must start with a letter and use "
                                 "only letters, digits, '-' and '_' (2-40 chars), "
                                 "and cannot be 'current'")
    return name


def _snapshot_out(s: dict) -> dict:
    return {
        "name": s.get("name"),
        "description": s.get("description"),
        "snaptime": s.get("snaptime"),
        # PVE returns 0/1 (and omits it entirely on containers)
        "vmstate": bool(int(s.get("vmstate") or 0)),
        "parent": s.get("parent"),
    }


@router.get("/{vm_id}/snapshots",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("vms.snapshots"))])
def list_vm_snapshots(request: Request, vm_id: int, db=Depends(get_db),
                      user: User = Depends(_read)):
    """Live read on every request (doc 05: "List snapshots (live from
    Proxmox)"); there is no snapshot table and this phase adds none.

    PVE always includes a synthetic `current` entry describing the running
    state. It is not a snapshot, has no snaptime, and cannot be rolled back to
    or deleted, so it is dropped here rather than in the UI; otherwise every
    consumer of this endpoint has to know the same trivia.
    """
    v, host = _vm_and_host(db, vm_id)
    client = client_for_host(request.app, db, host)
    try:
        rows = client.snapshots("qemu", guest_node(host, v), v.vmid)
    except ProxmoxError as e:
        raise HTTPException(502, str(e)) from e
    return [_snapshot_out(s) for s in rows if s.get("name") != "current"]


class SnapshotIn(BaseModel):
    name: str
    description: str | None = None
    vmstate: bool = False


@router.post("/{vm_id}/snapshots", status_code=202,
             dependencies=[Depends(_snapshot),
                           Depends(require_entitlement("vms.snapshots"))])
def create_vm_snapshot(request: Request, vm_id: int, body: SnapshotIn,
                       db=Depends(get_db),
                       user: User = Depends(_snapshot)):
    v, _host = _vm_and_host(db, vm_id)
    name = _valid_snap_name(body.name)
    # A snapshot has no row of its own here, so target_id points at the guest
    # and the name has to carry the snapshot. Without it three snapshot rows
    # against the same guest read identically and none of them says which
    # snapshot was taken, rolled back to, or thrown away.
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_create",
                             target_type="vm", target_id=v.id,
                             target_name=f"{name} on {v.name or f'VM {v.vmid}'}",
                             params={"vm_id": v.id, "name": name,
                                     "description": body.description,
                                     "vmstate": body.vmstate})


class RollbackIn(BaseModel):
    confirm: str | None = None


@router.post("/{vm_id}/snapshots/{name}/rollback", status_code=202,
             dependencies=[Depends(_rollback),
                           Depends(require_entitlement("vms.snapshots"))])
def rollback_vm_snapshot(request: Request, vm_id: int, name: str,
                         body: RollbackIn = Body(default=RollbackIn()),
                         db=Depends(get_db),
                         user: User = Depends(_rollback)):
    """Rollback throws away every write since the snapshot was taken; there is
    no undo and no second copy. It therefore reuses the same three-key 409
    *shape* (`error`/`confirm_phrase`/`detail`) `enqueue_lifecycle` uses, so
    the frontend's existing typed-confirmation dialog renders it with no new
    component, but the `error` value here is `"confirm_required"`, not
    `enqueue_lifecycle`'s self-targeted-stop `"self_target"`: rollback asks
    for confirmation from *every* caller, not only when the VM happens to be
    the one Proxploy itself runs in. The frontend keys on this exact string,
    so do not conflate the two.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    vm_name = v.name or f"VM {v.vmid}"
    ip = request.client.host if request.client else None
    if (body.confirm or "") != vm_name:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="vm.snapshot_rollback", target_type="vm",
                    target_id=v.id, target_name=f"{name} on {vm_name}",
                    params={"name": name}, result="denied", ip=ip)
        raise HTTPException(409, {
            "error": "confirm_required", "confirm_phrase": vm_name,
            "detail": (f"Rolling {vm_name} back to {name!r} discards everything "
                       f"written since that snapshot was taken. Type the VM name "
                       f"to confirm."),
        })
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_rollback",
                             target_type="vm", target_id=v.id,
                             target_name=f"{name} on {vm_name}",
                             params={"vm_id": v.id, "name": name})


@router.delete("/{vm_id}/snapshots/{name}", status_code=202,
               dependencies=[Depends(_snapshot),
                             Depends(require_entitlement("vms.snapshots"))])
def delete_vm_snapshot(request: Request, vm_id: int, name: str, db=Depends(get_db),
                       user: User = Depends(_snapshot)):
    """No typed confirmation: deleting a snapshot leaves the guest and its disk
    exactly as they are. Only the rollback above destroys live state.
    """
    v, _host = _vm_and_host(db, vm_id)
    _valid_snap_name(name)
    return enqueue_and_audit(request, db, user, kind="vm.snapshot_delete",
                             target_type="vm", target_id=v.id,
                             target_name=f"{name} on {v.name or f'VM {v.vmid}'}",
                             params={"vm_id": v.id, "name": name})


class VmCloneIn(BaseModel):
    name: str | None = None
    newid: int | None = None
    full: bool = True
    target: str | None = None
    storage: str | None = None


@router.post("/{vm_id}/clone", status_code=202,
             dependencies=[Depends(_clone),
                           Depends(require_entitlement("vms.clone"))])
def clone_vm_route(request: Request, vm_id: int,
                   body: VmCloneIn = Body(default=VmCloneIn()), db=Depends(get_db),
                   user: User = Depends(_clone)):
    """A linked clone is refused here, not by PVE.

    The upgrade path this docstring used to describe is now taken: the poller
    mirrors `/cluster/resources`'s `template` flag onto `Vm`, so a linked clone
    of an ordinary guest is refused with a sentence naming templates instead of
    PVE's `500 Linked clone feature is not supported for '<volume>' (scsi0)`,
    which never mentions them. Its trigger condition was "if PVE's rejection
    proves confusing in practice", and doc 12 check 18 is that evidence.

    Historical note, kept because it explains the shape: PVE permits a linked
    clone (`full=false`) only from a template, and Proxploy could not tell
    templates apart, so `full` was passed through unvalidated.
    """
    v, host = _vm_and_host(db, vm_id)
    if body.name is not None and not VM_NAME_RE.match(body.name):
        raise HTTPException(422, "name must be a hostname-shaped label")
    if not body.full and not v.template:
        # 409, not 422: the request is well formed and would be valid against a
        # template, so this is a state conflict rather than a bad field. The
        # error names what to do, which PVE's own refusal does not.
        raise HTTPException(409, {
            "error": "linked_clone_needs_template",
            "detail": (f"{v.name or f'VM {v.vmid}'} is not a template, and PVE "
                       f"can only make a linked clone from one. Choose a full "
                       f"clone, or convert this guest to a template first."),
        })
    newid = body.newid
    if newid is None:
        client = client_for_host(request.app, db, host, capability="lifecycle")
        try:
            newid = int(client.cluster_nextid())
        except ProxmoxError as e:
            raise HTTPException(502, str(e)) from e
    # Names both ends. target_id still points at the SOURCE, which is the row
    # that exists, but a clone row that names only the source cannot be told
    # apart from the next clone of the same template, and the copy it made is
    # the thing someone comes looking for.
    src = v.name or f"VM {v.vmid}"
    dest = f"{body.name} (VM {int(newid)})" if body.name else f"VM {int(newid)}"
    out = enqueue_and_audit(request, db, user, kind="vm.clone", target_type="vm",
                            target_id=v.id, target_name=f"{src} to {dest}",
                            params={"vm_id": v.id, "newid": int(newid),
                                    "name": body.name, "full": body.full,
                                    "target": body.target,
                                    "storage": body.storage})
    return {**out, "vmid": int(newid)}


class VmDeleteIn(BaseModel):
    confirm: str | None = None


@router.delete("/{vm_id}", status_code=202,
               dependencies=[Depends(_remove),
                             Depends(require_entitlement("vms.create"))])
def delete_vm_route(request: Request, vm_id: int,
                    body: VmDeleteIn = Body(default=VmDeleteIn()),
                    db=Depends(get_db), user: User = Depends(_remove)):
    """The most destructive route in this phase: the guest and its disks are
    gone, and nothing here backs them up first. Doc 05 puts it at owner, one
    rung above every other VM route; on top of that it takes the same
    typed-confirmation path as a self-targeted stop, and refuses a running
    guest outright rather than forcing it down first.
    """
    v, _host = _vm_and_host(db, vm_id)
    name = v.name or f"VM {v.vmid}"
    ip = request.client.host if request.client else None

    def _deny(payload: dict):
        write_audit(db, actor_type="user", actor_id=user.id, action="vm.delete",
                    target_type="vm", target_id=v.id, result="denied", ip=ip)
        raise HTTPException(409, payload)

    # One guard point for "is this Proxploy itself". is_self() answers False for
    # every VM today (selfguard.py:21: Proxploy ships as an LXC CT), so this is
    # currently always a pass. It is called anyway rather than reasoned around:
    # the day a VM-hosted install exists, the guard is already wired, and the
    # alternative is a comment asserting an invariant no code enforces.
    if is_self(db, "vm", v.id):
        _deny({"error": "self_target", "confirm_phrase": name,
               "detail": f"{name} is the guest Proxploy itself runs in, "
                         f"destroying it would destroy this process."})
    if (v.status or "") == "running":
        _deny({"error": "guest_running",
               "detail": f"stop {name} before destroying it"})
    if (body.confirm or "") != name:
        _deny({"error": "confirm_required", "confirm_phrase": name,
               "detail": (f"Destroying {name} deletes the VM and every disk "
                          f"attached to it. There is no undo and no automatic "
                          f"backup. Type the VM name to confirm.")})
    return enqueue_and_audit(request, db, user, kind="vm.delete", target_type="vm",
                             target_id=v.id, params={"vm_id": v.id, "vmid": v.vmid})


@router.post("/{vm_id}/{action}", status_code=202,
             dependencies=[Depends(_lifecycle),
                          Depends(require_entitlement("vms.lifecycle"))])
def vm_lifecycle(request: Request, vm_id: int, action: str,
                 body: LifecycleIn = Body(default=LifecycleIn()),
                 db=Depends(get_db),
                 user: User = Depends(_lifecycle)):
    if action not in VM_ACTIONS:
        raise HTTPException(422, f"action must be one of {', '.join(VM_ACTIONS)}")
    v = db.get(Vm, vm_id)
    if v is None:
        raise HTTPException(404, "vm not found")
    job = enqueue_lifecycle(request, db, user, target_type="vm", target=v,
                            action=action, name=v.name or f"VM {v.vmid}",
                            confirm=body.confirm)
    return {"job": job_out(job)}
