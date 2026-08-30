"""The firewall ROUTE layer against the real cluster.

tests/test_firewall_hardware.py and tests/test_firewall_hardware_pressure.py
both drive `ProxmoxClient` directly, so they prove the client speaks PVE
correctly and walk straight past api/firewall.py. Everything the route layer
adds on top of the client is therefore unproven by them:

    extra="forbid" on ten body models, the ObjectName path pattern, the RulePos
    bound, host_speaks_for_node, scope_object_or_404, and the 502 a payload
    Proxploy cannot parse now earns.

Every one of those is a REFUSAL. A fake can prove a refusal fires; only a real
cluster can prove it does not fire on something PVE would have accepted, and
that direction is the one that costs a user working functionality. So this file
asks exactly that question, route by route: does the validation refuse anything
real Proxmox takes?

It drives the FastAPI app rather than the client, against a THROWAWAY database
carrying a copy of the dev host's enrolment. The dev database is never written
to, and the dev server on :8000 is left alone.

Same lab rules as the pressure suite, and the same `Made` tracker enforces
them: delete only what this run created, by the handle creation earned; never
sweep by prefix; never enable the firewall at cluster or node scope; never
assert a scope is empty. vmid 105 is untouched.

Measured on pve-manager 9.2.11 on 2026-08-22.
"""
from __future__ import annotations

import json
import os

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proxploy.config import Settings
from proxploy.db import make_engine, make_sessionmaker
from proxploy.models import Host, HostCredential, Vm
from proxploy.secretstore import SecretStore
from proxploy.services.firewall import (SCOPE_OBJECTS, cluster_loc, guest_loc,
                                        node_loc)
from proxploy.services.proxmox import ProxmoxClient
from tests import livepve
from tests.test_firewall_hardware_pressure import (PX, QEMU_NODE, QEMU_VMID,
                                                   Made, _is_subsequence,
                                                   _keys, _Row,
                                                   restored_options)

pytestmark = [pytest.mark.pve_integration, livepve.live_only,
              livepve.guests_required(QEMU_VMID)]

PASSWORD = "Correct-Horse-Battery-9"

# The field set frontend/src/components/FirewallRuleForm.tsx puts in a body, so
# "the bodies the real UI sends" is not a guess. The form drops empty strings
# before sending, which is why every value here is a real one.
#
# Split in two because PVE will not take them as one: a macro already defines
# its ports, and sending dport alongside SSH earns
#   400 Parameter verification failed. - {'dport': "parameter 'dport' already
#   define in macro (value = '22')"}
# Measured on pve-manager 9.2.11 on 2026-08-22. That is PVE's rule about rule
# CONTENT, not a shape api/firewall.py has any business knowing, and the split
# keeps this test about the question it asks: does our validation refuse a key
# the form sends?
UI_RULE_PORTS = {"type": "in", "action": "ACCEPT", "enable": 1, "proto": "tcp",
                 "source": "10.0.0.0/8", "dest": "10.0.0.1", "sport": "1024",
                 "dport": "8006", "iface": "net0", "log": "nolog"}
UI_RULE_MACRO = {"type": "in", "action": "ACCEPT", "enable": 1, "macro": "SSH",
                 "source": "10.0.0.0/8", "iface": "net0", "log": "nolog"}

# The options keys FirewallOptionsPanel.tsx offers at guest scope. `enable` is
# deliberately absent: toggling a firewall on a guest this file does not own is
# not needed to prove OptionsIn accepts the UI's keys, and the pressure suite
# already covers the toggle itself on a container it restores.
UI_GUEST_OPTION_KEYS = ["policy_in", "policy_out", "macfilter", "ipfilter",
                        "dhcp", "ndp", "radv", "log_level_in", "log_level_out"]


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    """A throwaway app with the REAL Proxmox factory, carrying a copy of the
    dev database's first enrolled host and both of its tokens.

    A copy, never the dev database itself: this file creates users and drives
    writes, and the dev database belongs to the person running the dev server.
    The tokens are decrypted with the dev master key and re-encrypted under the
    throwaway app's own, which is the only way the route layer can reach the
    real cluster through client_for_host.
    """
    from tests.support import make_app

    tok = {"token_id": os.environ["PROXPLOY_TEST_PVE_TOKEN_ID"],
           "token_secret": os.environ["PROXPLOY_TEST_PVE_TOKEN_SECRET"]}
    tokens = {cap: tok for cap in ("monitoring", "lifecycle", "console")}
    fields = {"name": "live-pve", "address": os.environ["PROXPLOY_TEST_PVE_URL"],
              "node_name": livepve.node(), "cluster_name": None,
              "verify_tls": livepve.env("PROXPLOY_TEST_PVE_VERIFY", "0") == "1",
              "tls_fingerprint": None}

    app = make_app(tmp_path_factory.mktemp("fwroutes"))  # no fake: real factory
    with TestClient(app) as c:
        c.get("/api/v1/meta/health")
        csrf = {"X-CSRF-Token": c.cookies["pp_csrf"]}
        # First user is forced to owner, which clears every firewall tier.
        c.post("/api/v1/users", json={"email": "owner@lab.io",
                                      "password": PASSWORD,
                                      "display_name": "Owner"}, headers=csrf)
        c.post("/api/v1/auth/login", json={"email": "owner@lab.io",
                                           "password": PASSWORD}, headers=csrf)
        with app.state.sessionmaker() as db:
            host = Host(status="connected", **fields)
            db.add(host)
            db.commit()
            for cap, tok in tokens.items():
                blob, ver = app.state.secretstore.encrypt(
                    json.dumps(tok).encode())
                db.add(HostCredential(host_id=host.id, kind=f"api_token:{cap}",
                                      encrypted_blob=blob, key_version=ver))
            # One guest row, so the guest scope routes (which hang off
            # /vms/{id}) have something api/deps.py can scope to a team.
            vm = Vm(host_id=host.id, vmid=QEMU_VMID, name="debian-test",
                    status="running", node_name=QEMU_NODE)
            db.add_all([vm])
            db.commit()
            ids = {"host": host.id, "vm": vm.id, "node": host.node_name}

        def client(cap):
            return ProxmoxClient(fields["address"], tokens[cap]["token_id"],
                                 tokens[cap]["token_secret"],
                                 verify_tls=fields["verify_tls"],
                                 tls_fingerprint=fields["tls_fingerprint"])

        yield {"app": app, "c": c, "csrf": csrf, "ids": ids,
               "monitor": client("monitoring"), "lifecycle": client("lifecycle")}


@pytest.fixture
def c(rig):
    return rig["c"]


@pytest.fixture
def ids(rig):
    return rig["ids"]


@pytest.fixture
def made(rig):
    """The pressure suite's tracker, reused verbatim. Objects created through a
    ROUTE are recorded with `track`, since the route did the writing."""
    tracker = Made(rig["monitor"], rig["lifecycle"])
    yield tracker
    leaks = tracker.cleanup()
    problems = tracker.verify_untouched()
    assert not leaks, "objects this test created could not be removed: " + \
        "; ".join(leaks)
    assert not problems, "this test disturbed something it did not create: " + \
        "; ".join(problems)


@pytest.fixture(scope="module", autouse=True)
def run_snapshot(rig):
    """Every scope this module touches, as it was before the module ran."""
    monitor = rig["monitor"]
    # guest_loc's `host` is only read when the row carries no node_name, and
    # this row does, so None never gets dereferenced. Same trick in the two
    # guest-scope tests below.
    scopes = {"cluster": cluster_loc(),
              "node": node_loc(rig["ids"]["node"]),
              f"qemu {QEMU_VMID}": guest_loc(None, "qemu", QEMU_VMID,
                                             _Row(QEMU_NODE))}
    snap = {label: (loc, _keys(monitor.firewall_rules(loc)))
            for label, loc in scopes.items()}
    return snap, {g["group"] for g in monitor.firewall_groups()}


def post(c, csrf, url, body):
    return c.post(url, headers=csrf, json=body)


# ------------------------------------------------- 1. extra="forbid" is safe

def test_every_rule_body_the_ui_sends_is_accepted_by_the_route(rig, c, ids, made):
    """The false-refusal question for extra="forbid", asked with the real
    form's field set rather than a minimal body.

    A model that forbids extras refuses a key it does not know, and the field
    the UI spells one way and the model spells another is exactly the shape
    that would break. `icmp-type` is the one that can: it is not a valid Python
    identifier, so RuleIn carries it as `icmp_type` with an alias, and both
    spellings have to survive forbidding extras.
    """
    made.watch(cluster_loc())
    url = f"/api/v1/firewall/cluster/{ids['host']}/rules"
    bodies = [
        ("every port field", {**UI_RULE_PORTS, "comment": f"{PX}-routes-ports"}),
        ("the macro form", {**UI_RULE_MACRO, "comment": f"{PX}-routes-macro"}),
        ("hyphenated icmp-type", {"type": "in", "action": "ACCEPT",
                                  "proto": "icmp", "icmp-type": "echo-request",
                                  "comment": f"{PX}-routes-icmp-hyphen"}),
        ("underscored icmp_type", {"type": "in", "action": "ACCEPT",
                                   "proto": "icmp", "icmp_type": "echo-request",
                                   "comment": f"{PX}-routes-icmp-under"}),
    ]
    refused = []
    for label, body in bodies:
        got = post(c, rig["csrf"], url, body)
        if got.status_code == 201:
            made.track("rule", cluster_loc(), body["comment"])
            continue
        # A 502 is PVE refusing the CONTENT, which is PVE's call to make and
        # not a false refusal by us. A 422 is ours, and is the failure hunted.
        refused.append(f"{label}: {got.status_code} {got.text[:160]}")
    ours = [r for r in refused if r.split(": ")[1].startswith("422")]
    assert not ours, ("the route refused a body the UI sends and PVE would "
                      "have taken:\n" + "\n".join(ours))
    assert not refused, ("PVE refused a body the UI sends:\n"
                         + "\n".join(refused))
    # The two that must have landed, and landed carrying the hyphen PVE wants.
    rules = c.get(f"/api/v1/firewall/cluster/{ids['host']}/rules").json()["rules"]
    for comment in (f"{PX}-routes-icmp-hyphen", f"{PX}-routes-icmp-under"):
        row = next((r for r in rules if r.get("comment") == comment), None)
        assert row is not None, f"{comment} was accepted and is not there"
        assert row.get("icmp-type") == "echo-request", row



def test_the_ui_option_keys_are_accepted_at_guest_scope(rig, c, ids):
    """The same question for OptionsIn, at the one scope where writing options
    is safe. Every value written is the value already there, so the firewall
    behaves identically before and after; restored_options puts back anything
    that was absent."""
    loc = guest_loc(None, "qemu", QEMU_VMID, _Row(QEMU_NODE))
    url = f"/api/v1/vms/{ids['vm']}/firewall/options"
    read = c.get(url)
    assert read.status_code == 200, read.text[:200]
    body = read.json()
    with restored_options(rig["monitor"], rig["lifecycle"], loc):
        patch = {k: body["options"].get(k, body["defaults"].get(k))
                 for k in UI_GUEST_OPTION_KEYS}
        patch = {k: v for k, v in patch.items() if v is not None}
        patch["digest"] = body["digest"]
        got = c.put(url, headers=rig["csrf"], json=patch)
        assert got.status_code == 200, (
            f"the route refused the UI's own options keys: {got.status_code} "
            f"{got.text[:200]}")
        after = c.get(url).json()["options"]
        for k, v in patch.items():
            if k == "digest":
                continue
            assert str(after.get(k)) == str(v), (k, after.get(k), v)


# ---------------------------------------------------- 2. ObjectName and names

def test_a_group_name_pve_accepts_round_trips_through_the_route(rig, c, ids, made):
    """ObjectName allows 64 characters and PVE caps a security group at 18, so
    the two disagree. The disagreement is safe in only one direction, and this
    is the direction that matters: a name PVE takes must reach it.

    The other direction is PVE's refusal relayed, which must be a clean answer
    and not a crash. It is a 502 rather than a 422 because the cap is not a
    fact api/firewall.py knows; PVE is the authority and its sentence is what
    the operator needs to read.
    """
    made.watch_groups()
    base = f"/api/v1/firewall/cluster/{ids['host']}/groups"
    ok_name = "pxpr-routes-ok"                      # 14, inside PVE's cap
    assert len(ok_name) <= 18

    got = post(c, rig["csrf"], base, {"group": ok_name, "comment": f"{PX} route"})
    assert got.status_code == 201, got.text[:200]
    made.track("group", None, ok_name)
    assert any(g["group"] == ok_name for g in c.get(base).json()["groups"])
    # The name in the PATH goes through ObjectName; the group scope rules route
    # is the only place a group name is a path segment.
    listed = c.get(f"{base}/{ok_name}/rules")
    assert listed.status_code == 200, listed.text[:200]
    gone = c.delete(f"{base}/{ok_name}", headers=rig["csrf"])
    assert gone.status_code == 200, gone.text[:200]
    made.forget("group", ok_name)
    assert not any(g["group"] == ok_name for g in c.get(base).json()["groups"])

    long_name = "pxpr-routes-nineteen"              # 20, past PVE's cap
    assert len(long_name) > 18
    refused = post(c, rig["csrf"], base, {"group": long_name})
    assert refused.status_code == 502, (
        f"a name PVE caps answered {refused.status_code}: {refused.text[:200]}")
    assert "Traceback" not in refused.text
    assert "firewall" in refused.json()["detail"].lower()
    assert not any(g["group"] == long_name for g in c.get(base).json()["groups"])


def test_a_name_shaped_like_a_path_is_refused_before_it_reaches_proxmox(rig, c,
                                                                        ids):
    """The half a fake already proved, re-asked here so the refusal is measured
    against a cluster that would otherwise have served the PARENT endpoint."""
    base = f"/api/v1/firewall/cluster/{ids['host']}"
    got = c.delete(f"{base}/aliases/%2E%2E", headers=rig["csrf"])
    assert got.status_code == 422, got.text[:200]

    # `..%2Fmacros` never reaches the app at all: httpx resolves the dot
    # segment in the URL before sending, so what leaves is a DELETE on the
    # macros endpoint, which is GET only. 405 is the client's normalisation
    # showing, not a route answering, and it is pinned as 405 rather than
    # smoothed into a range so nobody reads it as our refusal.
    got = c.delete(f"{base}/aliases/%2E%2E%2Fmacros", headers=rig["csrf"])
    assert got.status_code == 405, got.text[:200]

    # And the cluster's own macros endpoint is still where it should be, i.e.
    # nothing above moved it or reached it.
    assert c.get(f"{base}/macros").status_code == 200


# ------------------------------------------------------- 3. the RulePos bound

def test_real_rule_positions_are_nowhere_near_the_route_bound(rig, c, ids):
    """RulePos caps at 65535. This reads every scope this lab serves and
    reports the largest position that actually exists, so the bound is known to
    be far above real data rather than assumed to be."""
    scopes = {
        "cluster": f"/api/v1/firewall/cluster/{ids['host']}/rules",
        "node": f"/api/v1/firewall/node/{ids['host']}/{ids['node']}/rules",
        "guest": f"/api/v1/vms/{ids['vm']}/firewall/rules",
    }
    highest = -1
    for label, url in scopes.items():
        got = c.get(url)
        assert got.status_code == 200, f"{label}: {got.status_code} {got.text[:160]}"
        for row in got.json()["rules"]:
            highest = max(highest, int(row["pos"]))
    assert highest < 1000, f"a real rule sits at position {highest}"


# ------------------------------------------------- 4. host_speaks_for_node

def test_the_enrolled_host_can_write_its_own_node_with_no_poll_yet(rig, c, ids,
                                                                   made):
    """The refusal that would hurt most, asked on a cold app.

    host_speaks_for_node is new authorization logic and it reads poller state,
    so the failure worth hunting is a host that cannot reach its OWN node
    because nothing has polled yet. There is deliberately no snapshot in this
    app: the host's own node is answered from the Host row alone.
    """
    assert rig["app"].state.poller.snapshots == {}, "this test needs a cold app"
    loc = node_loc(ids["node"])
    made.watch(loc)
    base = f"/api/v1/firewall/node/{ids['host']}/{ids['node']}"
    assert c.get(f"{base}/rules").status_code == 200
    assert c.get(f"{base}/options").status_code == 200
    assert c.get(f"{base}/log").status_code == 200
    comment = f"{PX}-routes-ownnode"
    got = post(c, rig["csrf"], f"{base}/rules",
               {"type": "in", "action": "ACCEPT", "comment": comment})
    assert got.status_code == 201, got.text[:200]
    made.track("rule", loc, comment)
    assert comment in [r.get("comment") for r in
                       c.get(f"{base}/rules").json()["rules"]]


@livepve.cluster_only
def test_a_peer_of_the_real_cluster_is_reachable_cold_and_warm(rig, c, ids):
    """The other node of the real cluster, through the host enrolled at the
    first one, both before and after a poll.

    The cold half is the false refusal this file found. host_speaks_for_node
    read the poll snapshot and nothing else, so between backend start and the
    first poll a peer node answered 404: node2's firewall page went blank after
    every restart, a page that worked before the check existed. fw.nodes_seen
    asks the cluster once on that miss now, and this pins the cold answer at
    200 so the window cannot come back unnoticed.

    The warm half is the ordinary path, seeded from this cluster's own
    /cluster/resources rather than from an invented row, and it must agree with
    the cold one.
    """
    app, monitor = rig["app"], rig["monitor"]
    node_rows = [r for r in monitor.cluster_resources() if r.get("type") == "node"]
    others = sorted({r["node"] for r in node_rows} - {ids["node"]})
    if not others:
        pytest.skip("this host's cluster has only one node")
    peer = others[0]
    url = f"/api/v1/firewall/node/{ids['host']}/{peer}/rules"

    assert app.state.poller.snapshots == {}, "this half needs a cold app"
    cold = c.get(url)
    assert cold.status_code == 200, (
        f"with no poll yet, {peer} answered {cold.status_code} "
        f"{cold.text[:200]}")

    from tests.support import seed_snapshot
    seed_snapshot(app, ids["host"], nodes=[{"node": r["node"]} for r in node_rows])
    try:
        warm = c.get(url)
        assert warm.status_code == 200, (
            f"{peer} is a node this host's own poll reports and the route "
            f"refused it: {warm.status_code} {warm.text[:200]}")
        assert warm.json()["rules"] == cold.json()["rules"]
        # Nobody else is enrolled at it in this database, so it stays reachable
        # through the host that can see it.
        assert c.get(f"/api/v1/firewall/node/{ids['host']}/{peer}/options"
                     ).status_code == 200
    finally:
        app.state.poller.snapshots.pop(ids["host"], None)

    # A node this cluster does not have is still refused, cold, which is what
    # says the answer above came from the cluster and not from giving up.
    ghost = c.get(f"/api/v1/firewall/node/{ids['host']}/node-that-is-not-here"
                  f"/rules")
    assert ghost.status_code == 404, ghost.text[:200]
    assert "firewall" in ghost.json()["detail"].lower()


# -------------------------------------------- 5. scope_object_or_404 and 502

def test_every_pair_this_cluster_serves_is_reachable_through_its_route(rig, c,
                                                                       ids):
    """scope_object_or_404 refuses a scope/object pair SCOPE_OBJECTS does not
    list. Every pair that has a route mounted is in that table, so the check
    must be invisible here: each route answers with data from PVE.
    """
    h, vm, node = ids["host"], ids["vm"], ids["node"]
    urls = {
        ("cluster", "rules"): f"/api/v1/firewall/cluster/{h}/rules",
        ("cluster", "options"): f"/api/v1/firewall/cluster/{h}/options",
        ("cluster", "aliases"): f"/api/v1/firewall/cluster/{h}/aliases",
        ("cluster", "ipsets"): f"/api/v1/firewall/cluster/{h}/ipsets",
        ("cluster", "groups"): f"/api/v1/firewall/cluster/{h}/groups",
        ("cluster", "refs"): f"/api/v1/firewall/cluster/{h}/refs",
        ("cluster", "macros"): f"/api/v1/firewall/cluster/{h}/macros",
        ("node", "rules"): f"/api/v1/firewall/node/{h}/{node}/rules",
        ("node", "options"): f"/api/v1/firewall/node/{h}/{node}/options",
        ("node", "log"): f"/api/v1/firewall/node/{h}/{node}/log",
        ("guest", "rules"): f"/api/v1/vms/{vm}/firewall/rules",
        ("guest", "options"): f"/api/v1/vms/{vm}/firewall/options",
        ("guest", "aliases"): f"/api/v1/vms/{vm}/firewall/aliases",
        ("guest", "ipsets"): f"/api/v1/vms/{vm}/firewall/ipsets",
        ("guest", "refs"): f"/api/v1/vms/{vm}/firewall/refs",
        ("guest", "log"): f"/api/v1/vms/{vm}/firewall/log",
    }
    bad = []
    for (scope, obj), url in urls.items():
        assert obj in SCOPE_OBJECTS[scope], f"{scope}/{obj} is not in the table"
        got = c.get(url)
        if got.status_code != 200:
            bad.append(f"{scope}/{obj} -> {got.status_code} {got.text[:120]}")
    assert not bad, ("a pair the cluster serves was not reachable:\n"
                     + "\n".join(bad))
    # The group scope is the one with a single object, and its rules route is
    # covered by test_a_group_name_pve_accepts_round_trips_through_the_route.
    assert SCOPE_OBJECTS["group"] == frozenset({"rules"})


def test_a_real_read_carries_a_real_digest_rather_than_a_502(rig, c, ids, made):
    """The false-refusal question for the shape check behind the new 502.

    _rules_digest wants a list of objects and _options_digest wants an object.
    What PVE actually sends has to satisfy both, at every scope, or the check
    would turn a working cluster into a gateway failure. A scope with no rules
    yet is the edge that must NOT 502: it is an empty list, which is an answer
    and not a malformed one.
    """
    h, vm, node = ids["host"], ids["vm"], ids["node"]
    made.watch(cluster_loc())
    reads = {
        "cluster rules": f"/api/v1/firewall/cluster/{h}/rules",
        "cluster options": f"/api/v1/firewall/cluster/{h}/options",
        "node rules": f"/api/v1/firewall/node/{h}/{node}/rules",
        "node options": f"/api/v1/firewall/node/{h}/{node}/options",
        "guest rules": f"/api/v1/vms/{vm}/firewall/rules",
        "guest options": f"/api/v1/vms/{vm}/firewall/options",
    }
    empties = []
    for label, url in reads.items():
        got = c.get(url)
        assert got.status_code == 200, f"{label}: {got.status_code} {got.text[:160]}"
        body = got.json()
        rows = body.get("rules", body.get("options"))
        if not rows:
            empties.append(label)
            assert body["digest"] is None, f"{label} was empty and had a digest"
            continue
        assert isinstance(body["digest"], str) and body["digest"], (
            f"{label} carried no digest: {body}")

    # And a digest from a real read is one PVE accepts back, which is the whole
    # reason it is surfaced. Written at cluster scope, where a rule changes
    # nothing until somebody enables the firewall.
    url = f"/api/v1/firewall/cluster/{h}/rules"
    digest = c.get(url).json()["digest"]
    comment = f"{PX}-routes-digest"
    got = post(c, rig["csrf"], url, {"type": "in", "action": "ACCEPT",
                                     "comment": comment, "digest": digest})
    assert got.status_code == 201, got.text[:200]
    made.track("rule", cluster_loc(), comment)


# ------------------------------------------------------------ 6. the evidence

def test_nothing_this_run_created_is_left_behind(rig, run_snapshot):
    """Runs last. Says every object that was here before this module ran is
    still here, and that nothing carrying our prefix survives. It does not say
    any scope is empty and it deletes nothing."""
    monitor = rig["monitor"]
    snapshot, groups_before = run_snapshot
    problems = []
    for label, (loc, rules) in snapshot.items():
        now = monitor.firewall_rules(loc)
        if not _is_subsequence(rules, _keys(now)):
            problems.append(f"{label}: rules present at the start are gone or "
                            f"reordered")
        leaked = [r.get("comment") for r in now
                  if str(r.get("comment", "")).startswith(PX)]
        if leaked:
            problems.append(f"{label}: rules left behind {leaked}")
    groups_now = {g["group"] for g in monitor.firewall_groups()}
    if groups_before - groups_now:
        problems.append(f"groups disappeared: {sorted(groups_before - groups_now)}")
    left = {g for g in groups_now - groups_before if g.startswith("pxpr")}
    if left:
        problems.append(f"groups left behind: {sorted(left)}")
    assert not problems, "; ".join(problems)
