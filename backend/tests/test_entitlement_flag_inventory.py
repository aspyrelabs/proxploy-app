"""Which entitlement flags actually gate something, pinned as a test.

The 2026-08-07 audit found 40 of the 81 registered flags were never checked
anywhere, and two of them (`audit.log`, `platform.self_update`) were
*documented* in doc 01 as gates. A flag that is documented as a control but
enforced nowhere is worse than no flag: anyone reading the spec believes a
gate exists. Today that is masked, `tiers.yaml` keeps `all_entitled: true`, so
every flag resolves on for everyone and nothing looks broken. It stops being
masked the moment tiers are armed (PXP-21).

Prose in an audit note goes stale the week after it is written. This does not:
the split below is recomputed from the source on every run, so arming a flag
or adding an unenforced one fails here and has to be classified deliberately.
"""
import pathlib

from proxploy.entitlements.registry import FLAG_KEYS

SRC = pathlib.Path(__file__).resolve().parents[1] / "proxploy"

# Flags with no enforcement point today, each with the reason it is absent.
# Adding to this set is a deliberate, code-review-visible act. Three kinds:
#
#   feature does not exist    the flag was registered ahead of the code
#                             (PXP-17 tracks the missing features themselves)
#   baseline                  every tier has it, so a gate would never fire;
#                             it exists to describe the product, not restrict it
#   feature was removed       the code it gated is gone, but the key stays in
#                             the registry because keys never change once
#                             shipped (registry.py)
#   structural                cannot be enforced as written
UNENFORCED = {
    # feature does not exist yet
    "platform.install",
    "store.install_log", "apps.logs", "apps.graphs", "vms.graphs",
    "backups.schedule", "backups.notify", "notify.routing", "notify.inapp",
    "audit.retention", "store.search", "alerts.manage", "metrics.collect",
    # baseline: present in every tier, a gate would never fire
    "auth.local", "ui.theme", "apps.list", "apps.detail", "apps.open_ui",
    "vms.list", "platform.onboarding", "platform.settings", "api.rest",
    "hosts.onboard", "hosts.manage", "cluster.overview", "cluster.node_detail",
    "jobs.engine", "rbac.roles", "secrets.store", "ent.client", "ent.manage",
    "hosts.ssh_executor",
    # feature was removed: the ActivityFeed component, GET /cluster/activity
    # and the query key that fed them were all deleted together. The key stays
    # registered so the shipped flag list does not change under a licence.
    "cluster.activity_feed",
    # structural
    "hosts.single",           # the complement of hosts.multi, which IS enforced
    "terminal.ct",            # permanently 501 by design, nothing to gate
    "platform.error_report",  # deliberately never on the entitlement path;
                              # see entitlements/registry.py for why
}


def _referenced_in_source() -> set[str]:
    body = "".join(p.read_text() for p in SRC.rglob("*.py")
                   if p.name != "registry.py")
    return {k for k in FLAG_KEYS if f'"{k}"' in body or f"'{k}'" in body}


def test_every_flag_is_either_enforced_or_deliberately_listed():
    """No flag gets to be quietly decorative.

    A new flag added to the registry without an enforcement point fails here
    until someone puts it in UNENFORCED with a reason, which is exactly the
    conversation that did not happen for the 40 the audit found.
    """
    enforced = _referenced_in_source()
    unclassified = set(FLAG_KEYS) - enforced - UNENFORCED
    assert not unclassified, (
        f"these flags gate nothing and are not listed as deliberate: "
        f"{sorted(unclassified)}")


def test_unenforced_list_has_no_stale_entries():
    """The other direction: a flag that got armed must leave UNENFORCED.

    Without this the set rots into a list of things that were once true, which
    is how the docs got into this state in the first place.
    """
    stale = UNENFORCED & _referenced_in_source()
    assert not stale, f"these are enforced now and should be removed: {sorted(stale)}"


def test_the_two_documented_gates_are_real():
    """doc 01 lists these as entitlement-gated in its feature table.

    Called out separately from the count because they are the ones that made
    the docs describe a security-relevant control that did not exist.
    """
    enforced = _referenced_in_source()
    for key in ("audit.log", "platform.self_update"):
        assert key in enforced, f"doc 01 documents {key} as a gate; nothing enforces it"
