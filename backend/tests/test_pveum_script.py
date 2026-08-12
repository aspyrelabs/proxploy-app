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


def test_console_withholds_sys_console_unless_node_shells_are_opted_into():
    without = generate_script(["console"])
    assert "VM.Console" in without
    # Sys.Console is effectively root on the node, so it is a separate opt-in
    # (doc 08 §2, and §9's own note on node shells).
    assert "Sys.Console" not in without

    with_shell = generate_script(["console"], node_shell=True)
    assert "Sys.Console" in with_shell


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

def test_node_power_is_withheld_from_the_script_unless_explicitly_opted_into():
    without = generate_script(["lifecycle"])
    assert "Sys.PowerMgmt" not in without

    with_power = generate_script(["lifecycle"], node_power=True)
    assert "Sys.PowerMgmt" in with_power


def test_node_power_never_lands_on_lifecycles_own_role():
    """A leaked ProxployLifecycle token must not carry the ability to power
    off the host: Sys.PowerMgmt gets its own role and token, not an
    augmentation of Lifecycle's."""
    s = generate_script(["lifecycle"], node_power=True)
    lifecycle_role_line = next(l for l in s.splitlines()
                               if l.startswith("pveum role add ProxployLifecycle"))
    assert "Sys.PowerMgmt" not in lifecycle_role_line


def test_node_power_does_not_require_lifecycle_to_be_chosen():
    """Node power is independent of guest lifecycle management: an operator
    who wants only monitoring + the ability to reboot the host must be able
    to get exactly that, not be forced into the guest-power role too."""
    s = generate_script([], node_power=True)
    assert "Sys.PowerMgmt" in s
    assert "ProxployLifecycle" not in s


def test_node_power_token_is_privilege_separated_like_every_other():
    s = generate_script([], node_power=True)
    assert "-token 'proxploy@pve!nodepower'" in s
    assert "pveum user token add proxploy@pve nodepower --privsep 1" in s
