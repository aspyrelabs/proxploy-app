"""Doc 08 §2 step 2: the wizard generates a copy-paste pveum script for
exactly the capabilities chosen, so the operator never hands Proxploy root
credentials and never has to invent the privilege list themselves.

The privilege tables here are transcribed from doc 08's capability -> role
table, not derived from application code.
"""
import pytest

from proxploy.services.pveum import CAPABILITIES, generate_script


def test_monitoring_is_always_present_even_if_not_asked_for():
    s = generate_script([])
    assert "pveum role add ProxployAudit" in s
    for priv in ("VM.Audit", "Datastore.Audit", "Sys.Audit", "Pool.Audit", "SDN.Audit"):
        assert priv in s


def test_monitoring_can_read_the_guest_agent():
    """VM.Audit alone cannot call /agent/*: PVE gates get-fsinfo and
    network-get-interfaces behind VM.GuestAgent.Audit, and answers a token
    without it `403 (/vms/<id>, VM.GuestAgent.Audit|VM.GuestAgent.Unrestricted)`.

    Verified on the lab node (PVE 9.2.10, VM 108) before this privilege was
    added. Two things break without it, and neither one says so: the VM table's
    Storage column reads "unknown" for every VM, because used bytes only ever
    come from the agent, and the Network page shows a VM no addresses. Both
    swallow the 403 and return None, so nothing is logged and nothing degrades.

    It went unnoticed because the only install anyone drove held a hand-made
    root@pam token for monitoring, which bypasses the check entirely.
    """
    s = generate_script([])
    assert "VM.GuestAgent.Audit" in s
    assert "VM.GuestAgent.Audit" in CAPABILITIES["monitoring"].privileges


def test_monitoring_can_read_a_node_firewall_log():
    """PVE gates /nodes/{node}/firewall/log behind Sys.Syslog, which VM.Audit
    and Sys.Audit do not imply. Without it the Firewall log page answers 502 on
    every correctly scoped install, and the product's OWN monitoring token
    reproduced it, so this was never a harness artefact.

    Third time a missing privilege has surfaced one at a time (Sys.PowerMgmt,
    then VM.GuestAgent.Audit, then this), and all three share a cause: the box
    was historically driven with a root token, which bypasses the check, so the
    scoped role was never exercised. A sweep of every read call on 2026-08-29
    found exactly three gaps and only this one belonged in this role.
    """
    s = generate_script([])
    assert "Sys.Syslog" in s
    assert "Sys.Syslog" in CAPABILITIES["monitoring"].privileges


def test_the_audit_role_is_not_given_write_or_console_privileges():
    """The other two gaps that sweep found are NOT fixed here, on purpose.

    A guest's firewall log needs VM.Console and a storage's config needs
    Datastore.Allocate. Both were tempting to add to this role to make one
    call site work, and both would have handed the read-only token console
    access to every guest, or allocation rights on every datastore. They are
    routed to the console and lifecycle credentials instead
    (services/firewall.py::guest_log_reader, api/storage.py::storage_config).

    This test is the guard on that decision: the audit role stays auditing.
    """
    audit = set(CAPABILITIES["monitoring"].privileges)
    for forbidden in ("VM.Console", "Datastore.Allocate", "Datastore.AllocateSpace",
                      "Sys.Modify", "VM.Allocate", "VM.PowerMgmt"):
        assert forbidden not in audit, (
            f"{forbidden} is not an audit privilege; route the call to the "
            f"capability that owns it instead of widening this role")
    assert all(p.endswith(".Audit") or p == "Sys.Syslog" for p in audit), (
        f"every monitoring privilege should be a read: {sorted(audit)}")


def test_a_capability_that_was_not_chosen_contributes_nothing():
    s = generate_script([])
    assert "ProxployLifecycle" not in s
    assert "ProxployConsole" not in s
    assert "ProxployBackup" not in s


def test_lifecycle_carries_doc_08s_exact_privilege_set():
    s = generate_script(["lifecycle"])
    for priv in ("VM.PowerMgmt", "VM.Config.Disk", "VM.Config.CPU", "VM.Config.Memory",
                 "VM.Config.Network", "VM.Config.Options", "VM.Allocate", "VM.Clone",
                 "VM.Snapshot", "VM.Snapshot.Rollback", "VM.Migrate"):
        assert priv in s, priv


def test_lifecycle_carries_node_infrastructure_privileges_too():
    """Editing a node's network bridges needs Sys.Modify; attaching or
    allocating a storage pool needs Datastore.Allocate; uploading/deleting
    storage content (an ISO, a stray volume) needs Datastore.AllocateSpace.
    None of these are guest privileges, but api/network.py's bridge routes
    and api/storage.py's attach/edit/detach/content routes run under the
    lifecycle capability (doc 08's own "resource edits" wording already
    implies node-level config, not only guest config), so lifecycle's role
    must carry them or every one of those calls 403s no matter which token
    is pasted -- the same class of gap Sys.PowerMgmt was."""
    s = generate_script(["lifecycle"])
    for priv in ("Sys.Modify", "Datastore.Allocate", "Datastore.AllocateSpace"):
        assert priv in s, priv


def test_console_always_grants_sys_console_so_onboarding_is_the_only_step():
    """Sys.Console used to ride a separate opt-in, and the flag reaching the
    generator was wired to the App Store SSH consent box rather than to
    anything about node shells. An operator could therefore finish onboarding,
    turn the node shell on in Proxploy, and get a 403 that only a hand-run
    pveum command on the node could fix. Every privilege Proxploy needs is
    granted by the onboarding script now."""
    s = generate_script(["console"])
    assert "VM.Console" in s
    assert "Sys.Console" in s


def test_every_token_is_privilege_separated_and_gets_its_own_acl():
    s = generate_script(["backup"])
    assert "--privsep 1" in s
    # A privsep token's rights are the intersection of its own ACLs with the
    # user's, so granting only the user leaves the token able to do nothing.
    assert "-token 'proxploy@pve!backup'" in s
    assert "-user proxploy@pve" in s


def test_the_path_can_be_narrowed_to_a_pool():
    s = generate_script([], path="/pool/prod")
    assert "pveum acl modify /pool/prod" in s
    assert "pveum acl modify / " not in s


def test_an_unknown_capability_is_refused_rather_than_silently_dropped():
    with pytest.raises(ValueError):
        generate_script(["teleportation"])


def test_the_script_says_what_to_do_with_it():
    s = generate_script([])
    # A wall of pveum with no context is how an operator pastes something they
    # do not understand into a root shell.
    assert s.lstrip().startswith("#")
    assert "review" in s.lower()


def test_capabilities_are_declared_once_for_both_ui_and_script():
    assert "monitoring" in CAPABILITIES
    assert CAPABILITIES["monitoring"].required is True
    assert CAPABILITIES["lifecycle"].required is False


# --- Sys.PowerMgmt: node power, a separate opt-in like Sys.Console ---------
#
# Node power (reboot/power off the HOST) is never granted by choosing
# Lifecycle (guest start/stop/snapshot/etc): folding it in would silently
# widen every existing user's token scope the next time they regenerate the
# script, and would make "restart a container" and "power off the host" the
# same permission. It needs its own explicit opt-in, same precedent as
# Sys.Console above.

def test_node_power_rides_on_lifecycle():
    """Taking the node down is managing the machine, so it belongs to the role
    that already manages it. A token allowed to migrate every guest off a node
    is not meaningfully safer for being unable to then power it off."""
    s = generate_script(["lifecycle"])
    role_line = next(l for l in s.splitlines()
                     if l.startswith("pveum role add ProxployLifecycle"))
    assert "Sys.PowerMgmt" in role_line


def test_node_power_is_absent_without_lifecycle():
    """No Lifecycle, no node power: there is no other role carrying it, and no
    separate token to paste for it."""
    s = generate_script([])
    assert "Sys.PowerMgmt" not in s
    assert "nodepower" not in s


# --- Re-running the script must converge, not just create -----------------
#
# Confirmed against a live cluster: an operator generated the script without
# node shell, ran it, got ProxployConsole with only VM.Console. They later
# turned on node shell in Proxploy and node shell failed, because that needs
# Sys.Console and the role never got it. Re-running the old script did not
# fix this: `pveum role add X -privs '...'` dies with "role already exists"
# on a node that has been set up before, so the privilege list is never
# updated. Only `pveum role modify X -privs '...'` (no -append, so it
# replaces the set) repairs it.

def test_every_role_converges_its_privileges_on_a_rerun():
    """Every role the generator can emit must both create the role (fresh
    node) and update it to the same privilege list (node set up before),
    driven from CAPABILITIES so this does not hardcode role names."""
    s = generate_script(list(CAPABILITIES))
    for cap in CAPABILITIES.values():
        privs = ",".join(cap.privileges)
        assert f"pveum role add {cap.role} -privs '{privs}'" in s
        assert f"pveum role modify {cap.role} -privs '{privs}'" in s
        # The modify must be the fallback that actually runs when add fails
        # because the role already exists, not just present somewhere else.
        assert (f"pveum role add {cap.role} -privs '{privs}' 2>/dev/null || "
                f"pveum role modify {cap.role} -privs '{privs}'") in s


def test_console_role_converges_to_add_sys_console_on_a_rerun():
    """The exact bug: node shell turned on after the first run must widen
    an already-existing ProxployConsole role to include Sys.Console, not
    silently leave it at VM.Console only."""
    role = CAPABILITIES["console"].role
    s = generate_script(["console"])
    assert f"pveum role add {role} -privs 'VM.Console,Sys.Console' 2>/dev/null || " \
           f"pveum role modify {role} -privs 'VM.Console,Sys.Console'" in s


def test_token_add_lines_stay_create_only():
    """Re-adding a token mints a brand new secret and would silently
    invalidate the copy Proxploy already stored for a working host, so
    these must never grow a `|| pveum ... token ... modify/regenerate`
    fallback the way role lines did."""
    s = generate_script(["console"])
    assert "pveum user token add proxploy@pve console --privsep 1" in s
    for line in s.splitlines():
        if "user token add" in line:
            assert "||" not in line


def test_script_explains_a_token_add_failure_is_expected_and_safe():
    """An operator re-running the script on an already-provisioned node
    will see the token-add line fail. The script text must say plainly
    that this means the token already exists and their stored secret is
    still valid, so they do not delete/re-add it and break a working host."""
    s = generate_script(["console"])
    lowered = s.lower()
    assert "already exists" in lowered
    assert "still valid" in lowered or "still works" in lowered


def test_the_gap_probe_and_the_script_read_the_same_privilege_list():
    """capability_gaps() reports what a token is missing by walking
    cap.privileges, and the script grants cap.privileges. A privilege that
    lived outside that tuple was invisible to the probe, so a console token
    with no Sys.Console reported a clean host and the node shell button 403'd
    anyway. Keeping both on one list is what stops them disagreeing again."""
    for cap in CAPABILITIES.values():
        s = generate_script([cap.key])
        for priv in cap.privileges:
            assert priv in s, f"{cap.key} grants {priv} but the script omits it"
    assert "Sys.Console" in CAPABILITIES["console"].privileges
