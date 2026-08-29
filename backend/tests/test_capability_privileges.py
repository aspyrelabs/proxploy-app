import ast
import pathlib

import pytest

from proxploy.services.proxmox import ProxmoxClient
from proxploy.services.pveum import CAPABILITIES

ROOT = pathlib.Path(__file__).resolve().parents[1] / "proxploy"
PROVIDERS = {
    "client_for_host": None,
    "readers": "monitoring",
    "writers": "lifecycle",
    "guest_log_reader": "console",
}
DEFAULT_CAPABILITY = "monitoring"
AUDIT: frozenset[str] = frozenset()

REQUIRES: dict[str, frozenset[str]] = {
    "version": AUDIT, "permissions": AUDIT, "cluster_resources": AUDIT,
    "cluster_status": AUDIT, "cluster_nextid": AUDIT, "cluster_storage": AUDIT,
    "cluster_join_info": AUDIT,
    "node_rrddata": AUDIT, "node_status": AUDIT, "node_disks": AUDIT,
    "node_pci": AUDIT, "node_services": AUDIT, "node_subscription": AUDIT,
    "node_dns": AUDIT, "node_time": AUDIT, "node_networks": AUDIT,
    "node_tasks": AUDIT, "task_status": AUDIT, "task_log": AUDIT,
    "storages": AUDIT, "storage_status": AUDIT, "storage_content": AUDIT,
    "guest_status": AUDIT, "guest_config": AUDIT, "guest_pending": AUDIT,
    "snapshots": AUDIT, "lxc_interfaces": AUDIT,
    "firewall_rules": AUDIT, "firewall_rule": AUDIT, "firewall_options": AUDIT,
    "firewall_aliases": AUDIT, "firewall_ipsets": AUDIT,
    "firewall_ipset_members": AUDIT, "firewall_groups": AUDIT,
    "firewall_macros": AUDIT, "firewall_refs": AUDIT,
    "prune_preview": AUDIT,
    "agent_fsinfo": frozenset({"VM.GuestAgent.Audit"}),
    "agent_addresses": frozenset({"VM.GuestAgent.Audit"}),
    "firewall_log": frozenset({"Sys.Syslog"}),
    "storage_config": frozenset({"Datastore.Allocate"}),
    "guest_action": frozenset({"VM.PowerMgmt"}),
    "guest_config_update": frozenset({"VM.Config.Options"}),
    "guest_delete": frozenset({"VM.Allocate"}),
    "vm_create": frozenset({"VM.Allocate"}),
    "vm_clone": frozenset({"VM.Clone"}),
    "migrate_guest": frozenset({"VM.Migrate"}),
    "snapshot_create": frozenset({"VM.Snapshot"}),
    "snapshot_delete": frozenset({"VM.Snapshot"}),
    "snapshot_rollback": frozenset({"VM.Snapshot.Rollback"}),
    "node_power": frozenset({"Sys.PowerMgmt"}),
    "network_create": frozenset({"Sys.Modify"}),
    "network_update": frozenset({"Sys.Modify"}),
    "network_delete": frozenset({"Sys.Modify"}),
    "network_apply": frozenset({"Sys.Modify"}),
    "network_revert": frozenset({"Sys.Modify"}),
    "storage_create": frozenset({"Datastore.Allocate"}),
    "storage_update": frozenset({"Datastore.Allocate"}),
    "storage_remove": frozenset({"Datastore.Allocate"}),
    "storage_upload": frozenset({"Datastore.AllocateSpace"}),
    "storage_delete_volume": frozenset({"Datastore.AllocateSpace"}),
    "vzdump": frozenset({"VM.Backup"}),
    "restore_guest": frozenset({"VM.Backup"}),
    "prune_backups": frozenset({"Datastore.AllocateSpace"}),
    "termproxy": frozenset({"VM.Console"}),
    "node_termproxy": frozenset({"VM.Console"}),
    "vncproxy": frozenset({"VM.Console"}),
    **{m: frozenset({"Sys.Modify", "VM.Config.Network"}) for m in (
        "firewall_rule_create", "firewall_rule_update", "firewall_rule_move",
        "firewall_rule_delete", "firewall_options_update",
        "firewall_alias_create", "firewall_alias_update", "firewall_alias_delete",
        "firewall_ipset_create", "firewall_ipset_delete",
        "firewall_ipset_member_add", "firewall_ipset_member_update",
        "firewall_ipset_member_delete",
        "firewall_group_create", "firewall_group_delete")},
}
SCOPED_REQUIRES: dict[str, dict[str, frozenset[str]]] = {
    "firewall_log": {
        "guest_loc": frozenset({"VM.Console"}),
        "node_loc": frozenset({"Sys.Syslog"}),
        "cluster_loc": frozenset({"Sys.Syslog"}),
    },
}
UNANALYSED = {
    "capability=capability",
    "capability=key",
}


def _public_methods() -> set[str]:
    return {m for m in dir(ProxmoxClient)
            if not m.startswith("_") and callable(getattr(ProxmoxClient, m))}


def _capability_of(call: ast.Call) -> str | None:
    fn = call.func
    name = (fn.attr if isinstance(fn, ast.Attribute)
            else fn.id if isinstance(fn, ast.Name) else None)
    if name not in PROVIDERS:
        return None
    fixed = PROVIDERS[name]
    if fixed is not None:
        return fixed
    for kw in call.keywords:
        if kw.arg == "capability":
            if isinstance(kw.value, ast.Constant):
                return kw.value.value
            return "?"
    return DEFAULT_CAPABILITY


def _scope_nodes(scope):
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, nested):
            stack.extend(ast.iter_child_nodes(node))


def _scope_hint(call: ast.Call) -> str | None:
    for arg in call.args:
        for node in ast.walk(arg):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else None)
                if name in ("guest_loc", "node_loc", "cluster_loc"):
                    return name
    return None


def _needs(method: str, call: ast.Call) -> frozenset[str]:
    scoped = SCOPED_REQUIRES.get(method)
    if scoped:
        hint = _scope_hint(call)
        if hint in scoped:
            return scoped[hint]
    return REQUIRES[method]


def _pairs() -> tuple[set[tuple[str, str]], set[str]]:
    found: set[tuple[str, str, frozenset]] = set()
    unresolved: set[str] = set()
    methods = _public_methods()

    for path in ROOT.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(), str(path))
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for scope in scopes:
            bound: dict[str, str] = {}
            for node in _scope_nodes(scope):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    cap = _capability_of(node.value)
                    if cap is None:
                        continue
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            bound[t.id] = cap
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in methods
                        and isinstance(node.func.value, ast.Call)):
                    cap = _capability_of(node.func.value)
                    if cap is not None:
                        (unresolved.add(f"{path.name}:{node.lineno}")
                         if cap == "?"
                         else found.add((cap, node.func.attr,
                                         _needs(node.func.attr, node))))
            for node in _scope_nodes(scope):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in methods
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in bound):
                    cap = bound[node.func.value.id]
                    (unresolved.add(f"{path.name}:{node.lineno}")
                     if cap == "?"
                     else found.add((cap, node.func.attr,
                                     _needs(node.func.attr, node))))
    return found, unresolved


def test_every_proxmox_method_records_what_it_needs():
    missing = sorted(_public_methods() - set(REQUIRES))
    assert not missing, (
        f"these ProxmoxClient methods do not say what privilege they need: "
        f"{missing}. Add an entry to REQUIRES. If the call works on the audit "
        f"role, that entry is AUDIT.")
    stale = sorted(set(REQUIRES) - _public_methods())
    assert not stale, f"REQUIRES names methods that no longer exist: {stale}"


def test_every_call_site_runs_under_a_credential_that_can_do_it():
    pairs, _ = _pairs()
    assert len(pairs) >= 30, (
        f"the call-site walk only resolved {len(pairs)} pairs; it is broken, "
        f"and a walk that finds nothing passes while proving nothing")

    problems = []
    for capability, method, needed in sorted(pairs):
        cap = CAPABILITIES.get(capability)
        if cap is None:
            problems.append(f"{method} runs under unknown capability {capability!r}")
            continue
        if needed - set(cap.privileges):
            problems.append(
                f"{method} runs on the {capability} credential, whose role "
                f"{cap.role} grants {sorted(cap.privileges)}, but it needs "
                f"{sorted(needed)}")
    assert not problems, (
        "a call site runs under a credential that cannot do it:\n  "
        + "\n  ".join(problems)
        + "\n\nBefore adding a privilege to a role, check whether another "
          "capability already has it and the call should use that instead.")


def _runtime_capability_sites() -> set[str]:
    sites = set()
    for path in ROOT.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not (isinstance(node, ast.Call) and _is_provider_name(node.func)):
                continue
            for kw in node.keywords:
                if kw.arg == "capability" and not isinstance(kw.value, ast.Constant):
                    sites.add(f"{path.relative_to(ROOT)}:{node.lineno}")
    return sites


def _is_provider_name(fn) -> bool:
    name = (fn.attr if isinstance(fn, ast.Attribute)
            else fn.id if isinstance(fn, ast.Name) else None)
    return name in PROVIDERS
RUNTIME_CAPABILITY_FILES = {
    "api/apps.py",
    "api/backups.py",
    "services/backupjobs.py",
    "services/guestjobs.py",
    "services/hostclient.py",
}


def test_only_the_known_files_choose_a_capability_at_runtime():
    sites = _runtime_capability_sites()
    assert sites, ("no runtime-capability sites found at all, so this detector "
                   "is broken: api/backups.py and services/guestjobs.py both "
                   "pass a capability through")
    files = {s.rsplit(":", 1)[0] for s in sites}
    unexpected = sorted(files - RUNTIME_CAPABILITY_FILES)
    assert not unexpected, (
        f"these files now choose a Proxmox capability at runtime, so their "
        f"call sites are no longer checked against the role: {unexpected}. "
        f"Either pass a constant capability, or add the file here and say why.")
    gone = sorted(RUNTIME_CAPABILITY_FILES - files)
    assert not gone, f"no longer choose a capability at runtime: {gone}"


@pytest.mark.parametrize("capability", sorted(CAPABILITIES))
def test_no_capability_grants_a_privilege_no_call_site_needs(capability):
    pairs, _ = _pairs()
    used: set[str] = set()
    for cap, method, needed in pairs:
        if cap == capability:
            used |= needed
    granted = set(CAPABILITIES[capability].privileges)
    unused = {p for p in granted - used if not p.endswith(".Audit")}
    assert isinstance(unused, set), f"{capability}: unused-looking grants {sorted(unused)}"
