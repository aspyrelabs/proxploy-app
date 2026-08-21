"""Firewall pressure tests against the real cluster. Excluded from the default
run, same as tests/test_firewall_hardware.py:

    pytest tests/ -m "not pve_integration and not e2e"

test_firewall_hardware.py proves the happy path exists at each scope. This file
asks the harder questions only a real pve-manager can answer: what `moveto`
actually does to the order, what a stale digest returns, which rule fields PVE
accepts and which it refuses, what a name that breaks PVE's regex does to our
error path, and which scope/object pairs are served at all.

=== The rule this file is built around ===

This suite shares the cluster with people. So:

* It deletes ONLY what it created, found again by the handle captured at
  creation time (see `Made`). It never sweeps a scope for objects that merely
  look like ours. A `pxppress` prefix makes a leak greppable; it is not proof
  of ownership and is never used as a delete filter on its own.
* It never asserts a scope is empty and never restores a scope to a baseline.
  Every assertion is relative to a snapshot taken by that same test: the list
  grew by exactly my rule, my rule is gone again, and every row that was there
  before is still there in the same relative order. Rows that appear while we
  run belong to somebody else and are left alone.
* Cleanup is the `made` fixture's teardown, which is the try/finally: pytest
  runs a fixture finalizer whether the test passed, failed or raised, so it is
  a stronger guarantee than a hand-written finally block in each test.

Safety: NEVER enables the firewall at cluster or node scope. A default-deny
policy on a lab node locks out the API. Guest scope enable IS exercised, on one
container, because the datacenter firewall is off so a guest policy applies to
nothing; the exact prior options are read first and put back.

Uses the enrolled host's own stored credentials from the dev database, for the
reason spelled out in test_firewall_hardware.py: env-var harnesses hand the same
token to every capability and would hide the read/write asymmetry.

Every PVE behaviour asserted here was measured on pve-manager 9.2.11 on
2026-08-21 before it was written down.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from proxploy.config import Settings
from proxploy.db import make_engine, make_sessionmaker
from proxploy.models import Host, HostCredential
from proxploy.secretstore import SecretStore
from proxploy.services.firewall import (SCOPE_OBJECTS, cluster_loc, group_loc,
                                        guest_loc, node_loc)
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError

pytestmark = pytest.mark.pve_integration

# Everything this file creates carries this prefix, in the name for objects and
# in the comment for rules, so a leak is findable on the cluster. It is a label,
# not an ownership test: see the module docstring.
PX = "pxppress"

# Guests this run may touch. vmid 105 is off limits and is deliberately absent.
LXC_VMID, LXC_NODE = 104, "node1"           # wastebin
QEMU_VMID, QEMU_NODE = 108, "node1"         # debian-test
FOREIGN_VMID, FOREIGN_NODE = 109, "node2"   # actualbudget, an LXC, NOT on
                                            # host 1's node

# 109 is a CONTAINER: cluster_resources() on this cluster reports it as an lxc,
# and this file used to describe it as a VM. Every foreign_* location below asks
# for it down the QEMU path ON PURPOSE, and that is not an oversight to tidy
# up: PVE keys a guest firewall on the vmid alone, at
# /etc/pve/firewall/<vmid>.fw, and never checks the kind in the URL, so the
# wrong kind reads and writes the same file the right one does. That is the
# behaviour test_an_unknown_vmid_reads_as_empty_rather_than_404 proves against
# 104, and asking 109 the same way keeps it covered on the cross-node path too.
# Measured on pve-manager 9.2.11 on 2026-08-21.

# A vmid that does not exist and plausibly never will on this lab.
GHOST_VMID = 999999


class _Row:
    """Stand-in for the Vm/App row guest_loc reads `node_name` off. The real
    handlers pass an ORM row; nothing but that attribute is read."""

    def __init__(self, node_name: str):
        self.node_name = node_name


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def rig():
    """(host, monitoring client, lifecycle client, monitoring token, lifecycle
    token) from the first enrolled host's own stored tokens."""
    s = Settings()
    db = make_sessionmaker(make_engine(s))()
    store = SecretStore(s.master_key_file)
    host = db.query(Host).first()
    if host is None:
        pytest.skip("no enrolled host in the dev database")

    def token(capability: str) -> dict:
        cred = db.query(HostCredential).filter_by(
            host_id=host.id, kind=f"api_token:{capability}").one_or_none()
        if cred is None:
            pytest.skip(f"host has no {capability} token configured")
        return json.loads(store.decrypt(cred.encrypted_blob))

    def client(tok: dict) -> ProxmoxClient:
        return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                             verify_tls=host.verify_tls,
                             tls_fingerprint=host.tls_fingerprint)

    mon_token, life_token = token("monitoring"), token("lifecycle")
    return host, client(mon_token), client(life_token), mon_token, life_token


@pytest.fixture(scope="module")
def host(rig) -> Host:
    return rig[0]


@pytest.fixture(scope="module")
def monitor(rig) -> ProxmoxClient:
    return rig[1]


@pytest.fixture(scope="module")
def lifecycle(rig) -> ProxmoxClient:
    return rig[2]


@pytest.fixture(scope="module")
def lxc_loc(host) -> dict:
    return guest_loc(host, "lxc", LXC_VMID, _Row(LXC_NODE))


@pytest.fixture(scope="module")
def qemu_loc(host) -> dict:
    return guest_loc(host, "qemu", QEMU_VMID, _Row(QEMU_NODE))


@pytest.fixture(scope="module")
def foreign_loc(host) -> dict:
    """Guest 109, routed to its OWN node (node2), reached through host 1
    (node1). Asked for as a VM although it is a container: see FOREIGN_VMID."""
    return guest_loc(host, "qemu", FOREIGN_VMID, _Row(FOREIGN_NODE))


# ------------------------------------------------------------------- helpers

def _key(rule: dict) -> tuple:
    """A rule's identity, as far as PVE offers one.

    `pos` is a dense array index renumbered on every write and `digest` covers
    the whole scope and changes whenever anything in it changes, so neither can
    be part of an identity. What is left is the rule's own fields.
    """
    return tuple(sorted((k, v) for k, v in rule.items()
                        if k not in ("pos", "digest")))


def _keys(rows: list[dict]) -> list[tuple]:
    return [_key(r) for r in rows]


def _comments(monitor, loc) -> list[str | None]:
    return [r.get("comment") for r in monitor.firewall_rules(loc)]


def _is_subsequence(small: list, big: list) -> bool:
    """Every element of `small`, in order, somewhere in `big`.

    Used instead of list equality so that a rule somebody else adds WHILE this
    suite runs does not fail the test. Removing or reordering one of their rules
    still does, which is the thing worth catching.
    """
    it = iter(big)
    return all(any(x == y for y in it) for x in small)


def _settings(options: dict) -> dict:
    """Options minus the digest, which changes on every write by design."""
    return {k: v for k, v in options.items() if k != "digest"}


def _pve_move(order: list, pos: int, moveto: int) -> list:
    """What PVE's `moveto` really does, measured on pve-manager 9.2.11 on
    2026-08-21 across twelve position pairs: insert the rule at index `moveto`
    in the list AS IT IS, then remove the original entry.

    The consequence every caller has to get right: a move DOWN lands the rule at
    `moveto - 1`, because removing the original shifts the tail up by one. A move
    UP lands it at `moveto` exactly. So `moveto = pos + 1` is a no-op, not a
    one-step move down, and moving down by one needs `pos + 2`.
    """
    out = list(order)
    out.insert(moveto, out[pos])
    del out[pos if moveto > pos else pos + 1]
    return out


@contextmanager
def restored_options(monitor, lifecycle, loc):
    """Read the exact prior options, hand them over, put them back.

    Restores by DELETING the keys that were not there before and re-writing the
    ones whose value moved, rather than by writing a remembered blob: PVE has no
    "replace the whole object" call, so a key we added would otherwise stay
    added forever. Never asserts the options started empty.
    """
    before = _settings(monitor.firewall_options(loc))
    try:
        yield before
    finally:
        after = _settings(monitor.firewall_options(loc))
        added = [k for k in after if k not in before]
        if added:
            lifecycle.firewall_options_update(loc, {"delete": ",".join(added)})
        changed = {k: v for k, v in before.items() if after.get(k) != v}
        if changed:
            lifecycle.firewall_options_update(loc, changed)
        assert _settings(monitor.firewall_options(loc)) == before, \
            "options were not restored to exactly what they were"


class Made:
    """What this test created, and what it promised not to disturb.

    Two jobs, deliberately in one object because they are two halves of one
    promise:

    * `rule`/`alias`/`ipset`/`group` perform the write AND record the handle
      that write earned us. Teardown deletes exactly those handles. It never
      lists a scope and deletes what looks like ours: a human may be working on
      this cluster right now, and a name prefix is a label, not a title deed.
      A rule has no id in PVE, so its handle is the comment we generated for it,
      which is unique within a test by construction.
    * `watch(loc)` snapshots a scope before the test touches it. Teardown, after
      our own objects are gone, asserts every remembered row is still present
      and that remembered rules are still in the same relative order. It never
      asserts a scope is empty.
    """

    def __init__(self, monitor, lifecycle):
        self.m, self.l = monitor, lifecycle
        self._made: list[list] = []      # [kind, loc, handle], handle mutable
        self._watched: list[tuple] = []  # (loc, rule keys, alias names, ipset names)
        self._watch_groups: set | None = None

    # -- creating, each returning the handle we will find it by again

    def rule(self, loc: dict, params: dict) -> str:
        comment = params["comment"]
        self.l.firewall_rule_create(loc, params)
        self._made.append(["rule", loc, comment])
        return comment

    def alias(self, loc: dict, params: dict) -> str:
        name = params["name"]
        self.l.firewall_alias_create(loc, params)
        self._made.append(["alias", loc, name])
        return name

    def ipset(self, loc: dict, params: dict) -> str:
        name = params["name"]
        self.l.firewall_ipset_create(loc, params)
        self._made.append(["ipset", loc, name])
        return name

    def group(self, params: dict) -> str:
        name = params["group"]
        self.l.firewall_group_create(params)
        self._made.append(["group", None, name])
        return name

    def repoint(self, kind: str, old: str, new: str) -> str:
        """The object is still ours, its handle just changed: an alias was
        renamed, or a rule's comment was edited. Without this the tracked handle
        goes stale and teardown would leave the object behind."""
        for entry in self._made:
            if entry[0] == kind and entry[2] == old:
                entry[2] = new
                return new
        raise AssertionError(f"no tracked {kind} with handle {old!r}")

    def forget(self, kind: str, handle: str) -> None:
        """The test deleted this itself and proved it. Stop tracking it so
        teardown does not report a phantom."""
        self._made = [e for e in self._made
                      if not (e[0] == kind and e[2] == handle)]

    # -- watching what we must not disturb

    def watch(self, loc: dict) -> None:
        self._watched.append((loc,
                              _keys(self.m.firewall_rules(loc)),
                              self._names(self.m.firewall_aliases, loc, "name"),
                              self._names(self.m.firewall_ipsets, loc, "name")))

    def watch_groups(self) -> None:
        self._watch_groups = {g["group"] for g in self.m.firewall_groups()}

    @staticmethod
    def _names(call, loc, field) -> set | None:
        """None means this scope does not serve the object at all (node scope
        has no aliases or IP sets), which is not something to verify."""
        try:
            return {row[field] for row in call(loc)}
        except ProxmoxError:
            return None

    # -- teardown

    def cleanup(self) -> list[str]:
        """Delete exactly what was created, newest first, and report what could
        not be removed rather than raising in the middle and abandoning the
        rest."""
        leaks: list[str] = []
        for kind, loc, handle in reversed(self._made):
            try:
                if kind == "rule":
                    self._del_rule(loc, handle)
                elif kind == "alias":
                    if any(a.get("name") == handle
                           for a in self.m.firewall_aliases(loc)):
                        self.l.firewall_alias_delete(loc, handle)
                elif kind == "ipset":
                    if any(s.get("name") == handle
                           for s in self.m.firewall_ipsets(loc)):
                        self.l.firewall_ipset_delete(loc, handle, force=True)
                elif kind == "group":
                    self._del_group(handle)
            except Exception as e:                             # noqa: BLE001
                leaks.append(f"{kind} {handle!r}: {e}")
        self._made.clear()
        return leaks

    def _del_rule(self, loc: dict, comment: str) -> None:
        """Delete the FIRST rule carrying this exact comment, or nothing if the
        test already deleted it. One entry deletes one rule, so a test that made
        two rules with the same comment still removes both."""
        for r in self.m.firewall_rules(loc):
            if r.get("comment") == comment:
                self.l.firewall_rule_delete(loc, r["pos"])
                return

    def _del_group(self, name: str) -> None:
        """PVE refuses to delete a group that still holds rules, so empty it
        first. Deleting rules we did not individually track is safe here and
        only here: we created the group, so nothing inside it predates us."""
        if not any(g.get("group") == name for g in self.m.firewall_groups()):
            return
        loc = group_loc(name)
        while self.m.firewall_rules(loc):
            self.l.firewall_rule_delete(loc, 0)
        self.l.firewall_group_delete(name)

    def verify_untouched(self) -> list[str]:
        """Everything that was there before this test is still there."""
        problems: list[str] = []
        for loc, rules, aliases, ipsets in self._watched:
            try:
                now = _keys(self.m.firewall_rules(loc))
            except ProxmoxError as e:
                problems.append(f"rules at {loc} became unreadable: {e}")
                continue
            if not _is_subsequence(rules, now):
                problems.append(
                    f"rules at {loc} lost or reordered: had {rules}, now {now}")
            if aliases is not None:
                gone = aliases - {a["name"] for a in self.m.firewall_aliases(loc)}
                if gone:
                    problems.append(f"aliases at {loc} disappeared: {sorted(gone)}")
            if ipsets is not None:
                gone = ipsets - {s["name"] for s in self.m.firewall_ipsets(loc)}
                if gone:
                    problems.append(f"IP sets at {loc} disappeared: {sorted(gone)}")
        if self._watch_groups is not None:
            gone = self._watch_groups - {g["group"] for g in self.m.firewall_groups()}
            if gone:
                problems.append(f"security groups disappeared: {sorted(gone)}")
        return problems


@pytest.fixture
def made(monitor, lifecycle):
    """The try/finally every test in this file runs its cleanup in. A fixture
    finalizer runs whether the test passed, failed or raised, so it is a
    stronger guarantee than a finally block written into each test."""
    tracker = Made(monitor, lifecycle)
    yield tracker
    leaks = tracker.cleanup()
    problems = tracker.verify_untouched()
    assert not leaks, "objects this test created could not be removed: " + \
        "; ".join(leaks)
    assert not problems, "this test disturbed something it did not create: " + \
        "; ".join(problems)


@pytest.fixture(scope="module", autouse=True)
def run_snapshot(monitor, host, lxc_loc, qemu_loc, foreign_loc):
    """Every scope this module touches, as it was before the module ran. The
    last test compares against this. Presence only, never emptiness."""
    scopes = {"cluster": cluster_loc(),
              "node1": node_loc("node1"), "node2": node_loc("node2"),
              f"lxc {LXC_VMID}": lxc_loc, f"qemu {QEMU_VMID}": qemu_loc,
              f"lxc {FOREIGN_VMID}": foreign_loc}
    snap = {}
    for label, loc in scopes.items():
        snap[label] = (loc, _keys(monitor.firewall_rules(loc)),
                       Made._names(monitor.firewall_aliases, loc, "name"),
                       Made._names(monitor.firewall_ipsets, loc, "name"))
    return snap, {g["group"] for g in monitor.firewall_groups()}


# --------------------------------------------------- 1. ordering under load

def test_rule_ordering_under_load(monitor, lifecycle, made):
    """12 rules, then moveto in every direction, order re-read after each move.

    Asserts against `_pve_move` rather than a guessed index, so it fails if
    PVE's semantics change OR if our client mangles the parameter. The list it
    compares is the WHOLE scope, so a rule belonging to somebody else is carried
    through the model too and any damage to it shows up here.
    """
    loc = cluster_loc()
    made.watch(loc)
    before = monitor.firewall_rules(loc)

    mine = [made.rule(loc, {"type": "in", "action": "ACCEPT",
                            "comment": f"{PX}-{i:02d}"}) for i in range(12)]
    want = _keys(monitor.firewall_rules(loc))
    assert len(want) == len(before) + 12, "the list did not grow by exactly 12"

    # PVE PREPENDS: the newest rule is pos 0, so mine occupy 0..11 and anything
    # that was already here follows.
    assert _comments(monitor, loc)[:12] == list(reversed(mine))

    for pos, moveto in [(0, 11),    # first towards last
                        (11, 0),    # last of mine to first
                        (3, 7),     # middle down
                        (7, 3),     # middle up
                        (5, 5),     # onto its own position
                        (0, 12),    # moveto == count, the real "to the end"
                        (11, 11)]:  # onto its own position again
        want = _pve_move(want, pos, moveto)
        lifecycle.firewall_rule_move(loc, pos, moveto)
        assert _keys(monitor.firewall_rules(loc)) == want, f"move {pos} -> {moveto}"

    # The off-by-one that matters, and it is not hypothetical.
    #
    # frontend/src/components/FirewallRuleTable.tsx:131 sends
    # `moveto: r.pos + 1` for the move-down button, and the backend relays it
    # verbatim (api/firewall.py:191). The two assertions below are what that
    # button actually does on real hardware: nothing at all. Move UP is right,
    # because a move up lands at `moveto` exactly; move DOWN needs `pos + 2`,
    # because removing the original entry shifts the tail up by one.
    #
    # frontend/src/tests/firewall-rules.test.tsx:90 covers move UP only, which
    # is why no fake-based test caught it. Reported, not fixed here.
    steady = _keys(monitor.firewall_rules(loc))
    lifecycle.firewall_rule_move(loc, 4, 5)
    assert _keys(monitor.firewall_rules(loc)) == steady, \
        "moveto = pos + 1 should be a no-op"
    # Moving down by one actually needs pos + 2.
    lifecycle.firewall_rule_move(loc, 4, 6)
    assert _keys(monitor.firewall_rules(loc)) == _pve_move(steady, 4, 6)

    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_rule_move(loc, 0, -1)
    assert "minimum value of 0" in str(exc.value)


def test_moveto_beyond_the_end_is_clamped_not_refused(monitor, lifecycle, made):
    """moveto far past the last index is accepted, not rejected, and lands the
    rule last. A UI that computes a too-large target gets a silent reorder
    rather than an error, so this records that on purpose."""
    loc = cluster_loc()
    made.watch(loc)
    for i in range(3):
        made.rule(loc, {"type": "in", "action": "ACCEPT", "comment": f"{PX}-c{i}"})
    moved = monitor.firewall_rules(loc)[0]
    lifecycle.firewall_rule_move(loc, 0, 999)
    assert _key(monitor.firewall_rules(loc)[-1]) == _key(moved)


# ------------------------------------------------------- 2. digest conflicts

def test_stale_digest_is_refused_on_every_rule_write(monitor, lifecycle, made):
    """Read a digest, let a second write land, then send the stale one.

    PVE answers 500 with "detected modified configuration", not 409, so the
    conflict reaches the API layer as a ProxmoxError carrying that text and is
    relayed as a 502 by api/firewall.py::pve_error. That is a finding, not
    something this test can fix: see the report.
    """
    loc = cluster_loc()
    made.watch(loc)
    first = made.rule(loc, {"type": "in", "action": "ACCEPT",
                            "comment": f"{PX}-first"})
    stale = monitor.firewall_rules(loc)[0]["digest"]
    second = made.rule(loc, {"type": "in", "action": "ACCEPT",
                             "comment": f"{PX}-second"})

    for label, call in [
        ("update", lambda: lifecycle.firewall_rule_update(
            loc, 0, {"comment": f"{PX}-nope", "digest": stale})),
        ("move", lambda: lifecycle.firewall_rule_move(loc, 0, 1, stale)),
        ("delete", lambda: lifecycle.firewall_rule_delete(loc, 0, stale)),
    ]:
        with pytest.raises(ProxmoxError) as exc:
            call()
        assert "detected modified configuration" in str(exc.value), label

    # Nothing was partially applied: both of mine are still there, unedited.
    present = _comments(monitor, loc)
    assert first in present and second in present
    assert f"{PX}-nope" not in present

    # A FRESH digest is accepted, so the refusals above were about the digest
    # and not about the shape of the call.
    fresh = monitor.firewall_rules(loc)[0]["digest"]
    lifecycle.firewall_rule_update(loc, 0, {"comment": f"{PX}-third",
                                            "digest": fresh})
    made.repoint("rule", second, f"{PX}-third")
    assert f"{PX}-third" in _comments(monitor, loc)


def test_stale_digest_is_refused_on_options(monitor, lifecycle):
    """The same conflict on the options object. Uses policy_out only: `enable`
    at cluster scope is the one write this suite must never make."""
    loc = cluster_loc()
    with restored_options(monitor, lifecycle, loc):
        stale = monitor.firewall_options(loc)["digest"]
        lifecycle.firewall_options_update(loc, {"policy_out": "ACCEPT"})
        assert monitor.firewall_options(loc)["policy_out"] == "ACCEPT"

        with pytest.raises(ProxmoxError) as exc:
            lifecycle.firewall_options_update(loc, {"policy_out": "REJECT",
                                                    "digest": stale})
        assert "detected modified configuration" in str(exc.value)
        # The refused write changed nothing.
        assert monitor.firewall_options(loc)["policy_out"] == "ACCEPT"


def test_a_fresh_digest_on_options_is_accepted(monitor, lifecycle):
    """The other half, so the test above cannot pass just because PVE refuses
    every digest it is handed."""
    loc = cluster_loc()
    with restored_options(monitor, lifecycle, loc):
        lifecycle.firewall_options_update(loc, {"policy_out": "ACCEPT"})
        fresh = monitor.firewall_options(loc)["digest"]
        lifecycle.firewall_options_update(loc, {"policy_out": "REJECT",
                                                "digest": fresh})
        assert monitor.firewall_options(loc)["policy_out"] == "REJECT"


# ---------------------------------------------- 3. rule fields real PVE takes

ACCEPTED_FIELDS = [
    ("ipv6", {"source": "2001:db8::/32", "dest": "2001:db8:1::1"},
     {"source": "2001:db8::/32", "dest": "2001:db8:1::1", "ipversion": 6}),
    ("port range", {"proto": "tcp", "dport": "80:443"}, {"dport": "80:443"}),
    ("port list", {"proto": "tcp", "dport": "22,80,443"}, {"dport": "22,80,443"}),
    ("port list with a range", {"proto": "tcp", "dport": "80,443:8443"},
     {"dport": "80,443:8443"}),
    ("macro", {"macro": "SSH"}, {"macro": "SSH"}),
    # PVE accepts a macro alongside an explicit proto and port, which the web
    # GUI does not offer. Recorded because our form could send both.
    ("macro with proto and dport", {"macro": "SSH", "proto": "tcp", "dport": "22"},
     {"macro": "SSH", "proto": "tcp", "dport": "22"}),
    # The spec flags icmp-type as a trap because it is the one field that cannot
    # be a Python keyword argument. If the hyphen were lost anywhere on the way
    # out, PVE would answer 400 and this would not round-trip.
    ("icmp-type v4", {"proto": "icmp", "icmp-type": "echo-request"},
     {"icmp-type": "echo-request", "proto": "icmp", "ipversion": 4}),
    ("icmp-type v6", {"proto": "icmpv6", "icmp-type": "echo-request"},
     {"icmp-type": "echo-request", "proto": "icmpv6", "ipversion": 6}),
    ("iface", {"iface": "net0"}, {"iface": "net0"}),
    ("proto by name", {"proto": "udp"}, {"proto": "udp"}),
    ("proto by keyword", {"proto": "gre"}, {"proto": "gre"}),
    # Stored verbatim as the string "47", NOT normalised to "gre".
    ("proto by number", {"proto": "47"}, {"proto": "47"}),
    ("enable 0", {"enable": 0}, {"enable": 0}),
    ("enable 1", {"enable": 1}, {"enable": 1}),
    ("sport and dport", {"proto": "tcp", "sport": "1024:65535", "dport": "443"},
     {"sport": "1024:65535", "dport": "443"}),
    ("source and dest v4", {"source": "10.99.0.0/16", "dest": "10.98.0.1"},
     {"source": "10.99.0.0/16", "dest": "10.98.0.1", "ipversion": 4}),
]

# All nine syslog levels PVE names, each round-tripped rather than assumed.
LOG_LEVELS = ["nolog", "emerg", "alert", "crit", "err", "warning", "notice",
              "info", "debug"]


@pytest.mark.parametrize("label,extra,expect", ACCEPTED_FIELDS,
                         ids=[c[0] for c in ACCEPTED_FIELDS])
def test_rule_field_round_trips(monitor, made, label, extra, expect):
    loc = cluster_loc()
    made.watch(loc)
    comment = made.rule(loc, {"type": "in", "action": "ACCEPT",
                              "comment": f"{PX}-{label.replace(' ', '-')}",
                              **extra})
    got = [r for r in monitor.firewall_rules(loc) if r.get("comment") == comment]
    assert len(got) == 1, f"{label}: expected exactly one rule back"
    for key, value in expect.items():
        assert got[0].get(key) == value, \
            f"{label}: {key} came back {got[0].get(key)!r}, wanted {value!r}"


@pytest.mark.parametrize("level", LOG_LEVELS)
def test_every_log_level_round_trips(monitor, made, level):
    loc = cluster_loc()
    made.watch(loc)
    comment = made.rule(loc, {"type": "in", "action": "ACCEPT",
                              "comment": f"{PX}-log-{level}", "log": level})
    got = [r for r in monitor.firewall_rules(loc) if r.get("comment") == comment]
    assert got and got[0].get("log") == level


def test_rule_types_and_actions_round_trip(monitor, made):
    loc = cluster_loc()
    made.watch(loc)
    for kind, action in [("in", "ACCEPT"), ("out", "REJECT"), ("forward", "DROP")]:
        comment = made.rule(loc, {"type": kind, "action": action,
                                  "comment": f"{PX}-{kind}"})
        got = [r for r in monitor.firewall_rules(loc)
               if r.get("comment") == comment][0]
        assert (got["type"], got["action"]) == (kind, action)


def test_a_rule_created_without_enable_comes_back_disabled(monitor, lifecycle,
                                                           made):
    """Measured, and worth pinning: omit `enable` and PVE reports enable 0.

    FirewallRuleTable reads `(r.enable ?? 0) !== 0`, so a rule created without
    the field renders as off. FirewallRuleForm sends enable 1 by default, which
    is what keeps that from biting; anything else posting a rule must send it.
    """
    loc = cluster_loc()
    made.watch(loc)
    comment = made.rule(loc, {"type": "in", "action": "ACCEPT",
                              "comment": f"{PX}-noenable"})

    def mine() -> dict:
        return [r for r in monitor.firewall_rules(loc)
                if r.get("comment") == comment][0]

    assert mine().get("enable") == 0
    lifecycle.firewall_rule_update(loc, mine()["pos"], {"enable": 1})
    assert mine().get("enable") == 1
    lifecycle.firewall_rule_update(loc, mine()["pos"], {"enable": 0})
    assert mine().get("enable") == 0


def test_pos_is_an_int_in_the_list_and_a_string_on_a_single_read(monitor, made):
    """PVE is not consistent about it and the frontend types `pos: number`.
    Only the list is used by the table, so this pins the difference rather than
    calling it a bug."""
    loc = cluster_loc()
    made.watch(loc)
    comment = made.rule(loc, {"type": "in", "action": "ACCEPT",
                              "comment": f"{PX}-pos"})
    listed = [r for r in monitor.firewall_rules(loc)
              if r.get("comment") == comment][0]
    assert isinstance(listed["pos"], int)
    single = monitor.firewall_rule(loc, listed["pos"])
    assert single["comment"] == comment
    assert single["pos"] == str(listed["pos"])
    assert isinstance(single["pos"], str)


REJECTED_FIELDS = [
    # PVE 9.2.11 has no `!` negation on a rule's source or dest. Negation is an
    # IP SET member property (`nomatch`), not a rule-address syntax. Anything in
    # our UI offering "not this address" on a rule is offering something PVE
    # cannot store.
    ("negated source", {"source": "!10.0.0.0/8"}, "Invalid chars in IP"),
    ("negated in a list", {"source": "10.0.0.0/8,!10.1.0.0/16"},
     "Invalid chars in IP"),
    ("mixed ip versions", {"source": "10.0.0.0/8", "dest": "2001:db8::1"},
     "detected mixed ipv4/ipv6 addresses"),
    ("unknown macro", {"macro": f"{PX}Nope"}, "unknown macro"),
    ("unknown action", {"action": f"{PX}BAD"}, "action"),
    ("bad icmp-type", {"proto": "icmp", "icmp-type": f"{PX}Nope"},
     "invalid icmp-type"),
    # Named only. A numeric icmp type is refused, which a UI offering a free
    # text box will hit.
    ("numeric icmp-type", {"proto": "icmp", "icmp-type": "8"},
     "invalid icmp-type"),
]


@pytest.mark.parametrize("label,extra,fragment", REJECTED_FIELDS,
                         ids=[c[0] for c in REJECTED_FIELDS])
def test_rule_field_pve_refuses(monitor, lifecycle, made, label, extra, fragment):
    """A refusal has to arrive as a ProxmoxError carrying PVE's own words, so
    api/firewall.py::pve_error can put them in front of the operator.

    The "nothing was written" check looks for OUR comment rather than for an
    empty list: anything else at this scope is another operator's business, and
    this test is only entitled to say the refused create left nothing behind.
    """
    loc = cluster_loc()
    made.watch(loc)
    comment = f"{PX}-{label.replace(' ', '-')}"
    params = {"type": "in", "action": "ACCEPT", "comment": comment, **extra}

    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_rule_create(loc, params)
    assert fragment in str(exc.value), str(exc.value)
    assert "Traceback" not in str(exc.value)
    assert not [r for r in monitor.firewall_rules(loc)
                if r.get("comment") == comment], "a refused rule was still written"


# ------------------------------------------------------------ 4. edge input

def test_comment_edges(monitor, lifecycle, made):
    """Long, unicode, empty and newline comments straight at PVE.

    Recorded rather than guessed: PVE enforces NO length cap on a rule comment.
    A 4096 character comment is stored and returned whole, so anything that
    wants a limit has to impose its own.
    """
    loc = cluster_loc()
    made.watch(loc)

    long_comment = f"{PX}-" + "x" * 4096
    made.rule(loc, {"type": "in", "action": "ACCEPT", "comment": long_comment})
    stored = [r for r in monitor.firewall_rules(loc)
              if r.get("comment") == long_comment]
    assert stored, "a 4096 character comment did not come back intact"

    unicode_comment = f"{PX}-é 中文 \U0001f525"
    made.rule(loc, {"type": "in", "action": "ACCEPT", "comment": unicode_comment})
    assert [r for r in monitor.firewall_rules(loc)
            if r.get("comment") == unicode_comment], \
        "a unicode comment did not round-trip"

    # A newline is the one comment PVE refuses outright.
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_rule_create(
            loc, {"type": "in", "action": "ACCEPT",
                  "comment": f"{PX}-line\nbreak"})
    assert "must not contain a line feed" in str(exc.value)


def test_an_empty_comment_is_dropped_rather_than_stored(monitor, lifecycle, made):
    """PVE does not store an empty comment as "", it drops the key entirely, so
    the rule comes back with no comment at all and carries no label.

    That rule therefore has no handle, which is why it is deleted here by the
    position it was created at rather than through `made`: PVE prepends, so a
    freshly created rule is always pos 0. Its own try/finally, and a count check
    either side so a foreign rule can never be the one removed.
    """
    loc = cluster_loc()
    made.watch(loc)
    before = monitor.firewall_rules(loc)
    lifecycle.firewall_rule_create(loc, {"type": "in", "action": "ACCEPT",
                                         "comment": ""})
    try:
        after = monitor.firewall_rules(loc)
        assert len(after) == len(before) + 1
        assert "comment" not in after[0], "an empty comment was stored after all"
        assert _keys(after[1:]) == _keys(before), \
            "the new rule did not land at pos 0"
    finally:
        lifecycle.firewall_rule_delete(loc, 0)
    assert _keys(monitor.firewall_rules(loc)) == _keys(before)


NAME_CASES = [
    (f"{PX}-dash", True, ""),
    (f"{PX}_underscore", True, ""),
    (PX + "x" * 55, True, ""),                   # 63 characters, just inside
    (f"{PX}.dot", False, "does not match the regex"),
    (f"{PX} space", False, "does not match the regex"),
    (f"{PX}!", False, "does not match the regex"),
    ("1" + PX, False, "does not match the regex"),   # cannot start with a digit
    (PX + "x" * 200, False, "may only be 64 characters"),
]


@pytest.mark.parametrize("name,ok,fragment", NAME_CASES,
                         ids=[f"{c[0][:20]}-{'ok' if c[1] else 'no'}"
                              for c in NAME_CASES])
def test_alias_name_validation(monitor, lifecycle, made, name, ok, fragment):
    """A name PVE dislikes must come back as a clean ProxmoxError. Nothing here
    may raise a bare exception, hang, or leave the alias half created."""
    loc = cluster_loc()
    made.watch(loc)
    if ok:
        made.alias(loc, {"name": name, "cidr": "10.99.0.0/16"})
        assert any(a["name"] == name for a in monitor.firewall_aliases(loc))
    else:
        with pytest.raises(ProxmoxError) as exc:
            lifecycle.firewall_alias_create(loc, {"name": name,
                                                  "cidr": "10.99.0.0/16"})
        assert fragment in str(exc.value), str(exc.value)
        assert "Traceback" not in str(exc.value)
        assert not any(a["name"] == name for a in monitor.firewall_aliases(loc)), \
            "a refused alias was still created"


def test_group_name_is_capped_at_18_characters(monitor, lifecycle, made):
    """Shorter than an alias name's 64, and short enough that a UI guarding only
    for 64 will let a doomed name through."""
    made.watch_groups()
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_group_create({"group": PX + "x" * 60})
    assert "may only be 18 characters" in str(exc.value)

    name = made.group({"group": PX + "xxxxxxxxx"})       # exactly 17
    assert len(name) == 17
    assert any(g["group"] == name for g in monitor.firewall_groups())


def test_ipset_member_rejects_a_bad_cidr(monitor, lifecycle, made):
    loc = cluster_loc()
    made.watch(loc)
    name = made.ipset(loc, {"name": f"{PX}bad"})
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_ipset_member_add(loc, name, {"cidr": "10.99.0.0/99"})
    assert "Prefix length 99 is longer than IP address" in str(exc.value)
    assert monitor.firewall_ipset_members(loc, name) == [], \
        "a refused member was still added to the set we just created"


# ------------------------------------------------- 5. alias and IP set cycles

def test_alias_full_lifecycle(monitor, lifecycle, made):
    """Create, re-cidr, rename, IPv6, delete. `rename` without `cidr` is refused
    by PVE, which is exactly why AliasPatch marks cidr required."""
    loc = cluster_loc()
    made.watch(loc)
    name = made.alias(loc, {"name": f"{PX}alias", "cidr": "10.99.0.0/16",
                            "comment": f"{PX} one"})

    def read(n: str) -> dict:
        rows = [a for a in monitor.firewall_aliases(loc) if a["name"] == n]
        assert len(rows) == 1, f"expected exactly one alias named {n!r}"
        return rows[0]

    got = read(name)
    assert (got["cidr"], got["comment"], got["ipversion"]) == \
        ("10.99.0.0/16", f"{PX} one", 4)

    lifecycle.firewall_alias_update(loc, name, {"cidr": "10.98.0.0/16",
                                                "comment": f"{PX} two"})
    got = read(name)
    assert (got["cidr"], got["comment"]) == ("10.98.0.0/16", f"{PX} two")

    # A rename needs the cidr sent alongside it, or PVE refuses the whole call.
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_alias_update(loc, name, {"rename": f"{PX}alias2"})
    assert "cidr" in str(exc.value) and "not optional" in str(exc.value)
    assert read(name)["cidr"] == "10.98.0.0/16", "the refused rename changed it"

    renamed = f"{PX}alias2"
    lifecycle.firewall_alias_update(loc, name, {"cidr": "10.98.0.0/16",
                                                "rename": renamed})
    made.repoint("alias", name, renamed)
    assert not any(a["name"] == name for a in monitor.firewall_aliases(loc))
    assert read(renamed)["cidr"] == "10.98.0.0/16"

    v6 = made.alias(loc, {"name": f"{PX}v6", "cidr": "2001:db8::/32"})
    assert read(v6)["ipversion"] == 6

    lifecycle.firewall_alias_delete(loc, renamed)
    made.forget("alias", renamed)
    assert not any(a["name"] == renamed for a in monitor.firewall_aliases(loc))
    assert any(a["name"] == v6 for a in monitor.firewall_aliases(loc)), \
        "deleting one alias took the other with it"


def test_ipset_full_lifecycle(monitor, lifecycle, made):
    """Members with a slash, a bare IP and an IPv6 prefix, plus nomatch, plus
    the forced delete of a populated set.

    The slashed CIDR is what proves _segment quotes the path: a bare host
    address would pass even with that quoting missing.
    """
    loc = cluster_loc()
    made.watch(loc)
    name = made.ipset(loc, {"name": f"{PX}set", "comment": f"{PX} set"})
    slashed, bare, v6 = "10.99.0.0/16", "10.99.1.5", "2001:db8:99::/48"

    for cidr in (slashed, bare, v6):
        lifecycle.firewall_ipset_member_add(loc, name, {"cidr": cidr,
                                                        "comment": f"{PX} m"})
    assert {m["cidr"] for m in monitor.firewall_ipset_members(loc, name)} == \
        {slashed, bare, v6}

    # nomatch is where PVE puts negation. It is a MEMBER property, not the rule
    # address syntax the refused-fields table above proves does not exist.
    lifecycle.firewall_ipset_member_update(loc, name, slashed,
                                           {"nomatch": 1,
                                            "comment": f"{PX} nomatch"})
    got = [m for m in monitor.firewall_ipset_members(loc, name)
           if m["cidr"] == slashed][0]
    assert got["nomatch"] == 1 and got["comment"] == f"{PX} nomatch"

    lifecycle.firewall_ipset_member_delete(loc, name, v6)
    assert {m["cidr"] for m in monitor.firewall_ipset_members(loc, name)} == \
        {slashed, bare}

    # A populated set cannot be deleted without force.
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_ipset_delete(loc, name, force=False)
    assert "is not empty" in str(exc.value)
    assert any(s["name"] == name for s in monitor.firewall_ipsets(loc))

    lifecycle.firewall_ipset_delete(loc, name, force=True)
    made.forget("ipset", name)
    assert not any(s["name"] == name for s in monitor.firewall_ipsets(loc))


# --------------------------------------------------------- 6. security group

def test_security_group_lifecycle_and_reference(monitor, lifecycle, made):
    """Create, fill, reorder inside the group, point a cluster rule at it, then
    delete.

    Two things PVE does that a caller has to plan for, both asserted here: a
    group holding rules cannot be deleted at all, and an EMPTY group can be
    deleted even while a rule still names it, leaving that rule pointing at
    nothing. PVE does not protect the reference; anything wanting a warning has
    to check the rule list itself.
    """
    loc = cluster_loc()
    made.watch(loc)
    made.watch_groups()
    group = made.group({"group": f"{PX}grp", "comment": f"{PX} group"})
    gloc = group_loc(group)

    for i in range(4):
        made.rule(gloc, {"type": "in", "action": "ACCEPT",
                         "comment": f"{PX}-g{i}"})
    want = _keys(monitor.firewall_rules(gloc))
    assert len(want) == 4, "a group we just created should hold only our rules"

    # Reordering INSIDE a group uses the same moveto arithmetic as any scope.
    want = _pve_move(want, 0, 3)
    lifecycle.firewall_rule_move(gloc, 0, 3)
    assert _keys(monitor.firewall_rules(gloc)) == want
    want = _pve_move(want, 2, 0)
    lifecycle.firewall_rule_move(gloc, 2, 0)
    assert _keys(monitor.firewall_rules(gloc)) == want

    # A cluster rule whose action IS the group name.
    ref = made.rule(loc, {"type": "group", "action": group,
                          "comment": f"{PX}-ref"})
    row = [r for r in monitor.firewall_rules(loc) if r.get("comment") == ref][0]
    assert (row["type"], row["action"]) == ("group", group)

    # Non-empty: refused, whether referenced or not.
    with pytest.raises(ProxmoxError) as exc:
        lifecycle.firewall_group_delete(group)
    assert "is not empty" in str(exc.value)
    assert any(g["group"] == group for g in monitor.firewall_groups())

    # Empty it. Every rule inside is one we created with this group.
    while monitor.firewall_rules(gloc):
        lifecycle.firewall_rule_delete(gloc, 0)
    for i in range(4):
        made.forget("rule", f"{PX}-g{i}")

    # Empty but still referenced: PVE allows it and leaves the rule dangling.
    lifecycle.firewall_group_delete(group)
    made.forget("group", group)
    assert not any(g["group"] == group for g in monitor.firewall_groups())
    dangling = [r for r in monitor.firewall_rules(loc) if r.get("comment") == ref]
    assert dangling and dangling[0]["action"] == group, \
        "PVE cleaned up the dangling reference after all"


# ------------------------------------------------------------ 7. guest scope

@pytest.mark.parametrize("which", ["lxc", "qemu"])
def test_guest_scope_full_surface(request, monitor, lifecycle, made, which):
    """Rules, aliases, IP sets, refs and log at guest scope, on a container
    (104 wastebin) and on a VM (108 debian-test)."""
    loc = request.getfixturevalue(f"{which}_loc")
    made.watch(loc)

    comment = made.rule(loc, {"type": "in", "action": "ACCEPT", "proto": "tcp",
                              "dport": "22", "enable": 1,
                              "comment": f"{PX}-{which}"})
    rule = [r for r in monitor.firewall_rules(loc)
            if r.get("comment") == comment][0]
    assert rule["enable"] == 1 and rule["dport"] == "22"

    alias = made.alias(loc, {"name": f"{PX}g", "cidr": "10.99.0.0/16"})
    assert any(a["name"] == alias for a in monitor.firewall_aliases(loc))

    ipset = made.ipset(loc, {"name": f"{PX}gset"})
    made_cidr = "10.99.0.0/16"
    lifecycle.firewall_ipset_member_add(loc, ipset, {"cidr": made_cidr})
    assert [m["cidr"] for m in monitor.firewall_ipset_members(loc, ipset)] == \
        [made_cidr]

    # refs at guest scope lists what a rule HERE may name in source or dest.
    refs = monitor.firewall_refs(loc)
    assert {alias, ipset} <= {r["name"] for r in refs}
    assert {r["type"] for r in refs} <= {"alias", "ipset"}
    assert all("ref" in r for r in refs)
    assert alias in {r["name"] for r in monitor.firewall_refs(loc, ref_type="alias")}
    assert alias not in {r["name"] for r in
                         monitor.firewall_refs(loc, ref_type="ipset")}
    assert ipset in {r["name"] for r in monitor.firewall_refs(loc, ref_type="ipset")}

    # A guest firewall log exists even with the firewall off: PVE answers with a
    # single "no content" placeholder row rather than an empty list.
    lines = monitor.firewall_log(loc, start=0, limit=5)
    assert isinstance(lines, list)
    assert all({"n", "t"} <= set(row) for row in lines)


def test_a_guest_rule_can_reference_a_security_group(monitor, made, lxc_loc):
    """A group is cluster-wide, so a guest rule may name one. Proves the group
    action is not a cluster-scope-only shape."""
    made.watch(lxc_loc)
    made.watch_groups()
    group = made.group({"group": f"{PX}gref"})
    comment = made.rule(lxc_loc, {"type": "group", "action": group,
                                  "comment": f"{PX}-gref"})
    row = [r for r in monitor.firewall_rules(lxc_loc)
           if r.get("comment") == comment][0]
    assert (row["type"], row["action"]) == ("group", group)


def test_guest_options_enable_toggle_is_restored(monitor, lifecycle, lxc_loc):
    """The one `enable` this suite is allowed to set.

    Safe because the datacenter firewall is off, so a guest policy applies to
    nothing, and the exact prior options are read first and put back. Never done
    at cluster or node scope, where a default-deny would end the run.
    """
    with restored_options(monitor, lifecycle, lxc_loc) as before:
        lifecycle.firewall_options_update(lxc_loc, {"enable": 1})
        after = monitor.firewall_options(lxc_loc)
        assert after["enable"] == 1
        # Only the key we wrote moved.
        assert {k: v for k, v in _settings(after).items() if k != "enable"} == \
            {k: v for k, v in before.items() if k != "enable"}

        lifecycle.firewall_options_update(lxc_loc, {"enable": 0, "macfilter": 0})
        got = monitor.firewall_options(lxc_loc)
        assert got["enable"] == 0 and got["macfilter"] == 0
    # restored_options asserts the exact prior options are back.


def test_guest_options_reject_a_cluster_only_key(monitor, lifecycle, qemu_loc):
    """OptionsIn carries the union of all three scopes' fields on purpose, with
    PVE as the authority on which belong where. This proves PVE really is that
    authority rather than quietly storing a key the scope has no use for."""
    with restored_options(monitor, lifecycle, qemu_loc):
        with pytest.raises(ProxmoxError) as exc:
            lifecycle.firewall_options_update(qemu_loc, {"ebtables": 1})
        assert "ebtables" in str(exc.value)


# ------------------------------------------------------ 8. cross-node routing

def test_guest_loc_routes_to_the_guests_own_node(host):
    """guest_loc must take the node from the guest's row, never from the host's
    entry node. Host 1 is node1; guest 109 lives on node2.

    guest_loc is a pure function here, so the kind in these calls is only
    carried through to the dict and never checked by anything. 109 is a
    container asked for as a VM, deliberately: see FOREIGN_VMID.

    This test fails outright if guest_loc ever goes back to host.node_name.
    """
    assert host.node_name == "node1", f"rig host is {host.node_name}, expected node1"
    routed = guest_loc(host, "qemu", FOREIGN_VMID, _Row(FOREIGN_NODE))
    assert routed["node"] == FOREIGN_NODE != host.node_name

    # Without a row it falls back to the host's node, which is the WRONG machine
    # for this guest. That fallback is correct for a standalone host and is what
    # every caller has to pass a row to avoid.
    assert guest_loc(host, "qemu", FOREIGN_VMID)["node"] == host.node_name


def test_firewall_endpoints_do_not_validate_the_node_in_the_path(monitor,
                                                                 lifecycle,
                                                                 host, made):
    """The finding behind the test above.

    For FIREWALL calls, PVE serves a guest's config through ANY node, because it
    lives in the cluster filesystem at /etc/pve/firewall/<vmid>.fw keyed by vmid
    alone. So the 500 that guest_loc's docstring warns about, which is real for
    the guest CONFIG endpoints that docstring came from, never fires here.
    Writing guest 109 through node1 lands in the same file node2 reads.

    Nothing observable distinguishes a correctly routed firewall call from a
    misrouted one, which is exactly why the assertion above is on the location
    dict and not on a response.

    109 is a container and every call below asks for it as a VM, which the same
    node-blind lookup makes work: this covers the wrong kind and the wrong node
    at once. See FOREIGN_VMID.
    """
    wrong = guest_loc(host, "qemu", FOREIGN_VMID)                    # node1
    right = guest_loc(host, "qemu", FOREIGN_VMID, _Row(FOREIGN_NODE))  # node2
    assert wrong["node"] != right["node"]
    made.watch(right)

    comment = made.rule(wrong, {"type": "in", "action": "ACCEPT",
                                "comment": f"{PX}-xnode"})
    # Written through node1, readable through node2: one shared file.
    assert comment in _comments(monitor, right)
    assert _keys(monitor.firewall_rules(wrong)) == _keys(monitor.firewall_rules(right))
    assert monitor.firewall_options(wrong) == monitor.firewall_options(right)


def test_an_unknown_vmid_reads_as_empty_rather_than_404(monitor, host):
    """The same node-blind lookup taken one step further: a vmid that exists
    nowhere answers with an empty rule list and an empty options object instead
    of an error, and the guest KIND in the path is not checked either.

    PVE offers no safety net here, so the guard has to be ours: the routes reach
    these calls only through a row api/deps.py has already scoped to the team.
    """
    ghost = guest_loc(host, "lxc", GHOST_VMID, _Row("node1"))
    assert monitor.firewall_rules(ghost) == []
    assert _settings(monitor.firewall_options(ghost)) == {}

    # 104 is a container, asked for as a VM. PVE answers rather than objecting.
    as_wrong_kind = guest_loc(host, "qemu", LXC_VMID, _Row(LXC_NODE))
    as_right_kind = guest_loc(host, "lxc", LXC_VMID, _Row(LXC_NODE))
    assert _keys(monitor.firewall_rules(as_wrong_kind)) == \
        _keys(monitor.firewall_rules(as_right_kind))


# --------------------------------------------------------------- 9. node log

@pytest.mark.parametrize("node", ["node1", "node2"])
def test_node_log_paging(monitor, node):
    """The line cursor shape JobLog renders: a list of {n, t} with n counting
    from 1 and rising, and a start past the end returning an empty list rather
    than an error."""
    loc = node_loc(node)
    first = monitor.firewall_log(loc, start=0, limit=5)
    assert isinstance(first, list)
    assert all(set(row) >= {"n", "t"} for row in first)
    assert all(isinstance(row["n"], int) and isinstance(row["t"], str)
               for row in first)
    if first:
        assert first[0]["n"] == 1
        assert [r["n"] for r in first] == sorted(r["n"] for r in first)

    one = monitor.firewall_log(loc, start=0, limit=1)
    assert len(one) <= 1
    assert one == first[:1], "limit=1 did not return the same first line"

    # A start past the end is an empty page, not a failure.
    assert monitor.firewall_log(loc, start=1_000_000, limit=5) == []


# ------------------------------------------------------- 10. refs and macros

def test_macros_shape(monitor):
    """The macro picker consumes {macro, descr} and nothing else. PVE gives no
    port expansion, so nothing downstream can show one."""
    macros = monitor.firewall_macros()
    assert len(macros) > 50
    assert all(set(m) == {"macro", "descr"} for m in macros)
    assert "SSH" in {m["macro"] for m in macros}


def test_refs_shape_at_cluster_scope(monitor, made):
    """refs is what fills the source/dest picker: {name, type, ref, comment?}
    with type in alias/ipset."""
    loc = cluster_loc()
    made.watch(loc)
    alias = made.alias(loc, {"name": f"{PX}ref", "cidr": "10.99.0.0/16",
                             "comment": f"{PX} ref"})
    ipset = made.ipset(loc, {"name": f"{PX}refset"})

    refs = monitor.firewall_refs(loc)
    by_name = {r["name"]: r for r in refs}
    assert {alias, ipset} <= set(by_name)
    assert by_name[alias]["type"] == "alias"
    assert by_name[ipset]["type"] == "ipset"
    assert all("ref" in r for r in refs)
    assert {r["type"] for r in refs} <= {"alias", "ipset"}

    only_sets = {r["name"] for r in monitor.firewall_refs(loc, ref_type="ipset")}
    only_aliases = {r["name"] for r in monitor.firewall_refs(loc, ref_type="alias")}
    assert ipset in only_sets and alias not in only_sets
    assert alias in only_aliases and ipset not in only_aliases


# ------------------------------------------- 11. what each scope really serves

def test_scope_objects_matches_the_cluster(monitor, host, lxc_loc):
    """SCOPE_OBJECTS is a measured table with no production caller, so measure
    it again against the real cluster.

    Anything a scope does NOT carry has to fail loudly rather than answer, or
    the 404 the API layer returns for that pair would be papering over a call
    that actually works.
    """
    probes = {
        "rules": lambda c, l: c.firewall_rules(l),
        "options": lambda c, l: c.firewall_options(l),
        "aliases": lambda c, l: c.firewall_aliases(l),
        "ipsets": lambda c, l: c.firewall_ipsets(l),
        "refs": lambda c, l: c.firewall_refs(l),
        "log": lambda c, l: c.firewall_log(l),
    }
    cases = {"cluster": cluster_loc(), "node": node_loc(host.node_name),
             "guest": lxc_loc}
    for scope, loc in cases.items():
        for obj, call in probes.items():
            served = obj in SCOPE_OBJECTS[scope]
            try:
                call(monitor, loc)
            except ProxmoxError as e:
                assert not served, f"{scope}/{obj} is in SCOPE_OBJECTS but failed: {e}"
                assert "501 Not Implemented" in str(e), \
                    f"{scope}/{obj}: expected a 501, got {e}"
            else:
                assert served, \
                    f"{scope}/{obj} works but is not in SCOPE_OBJECTS[{scope!r}]"


def test_group_scope_serves_rules_and_nothing_else(monitor, made):
    """A security group IS a rule list, so `.options` and friends are read as a
    rule POSITION named "options" and answered with a 400 type check, not the
    501 every other unserved pair gives. Different error, same conclusion:
    SCOPE_OBJECTS["group"] == {"rules"} is right."""
    assert SCOPE_OBJECTS["group"] == frozenset({"rules"})
    made.watch_groups()
    group = made.group({"group": f"{PX}scope"})
    loc = group_loc(group)
    assert monitor.firewall_rules(loc) == [], \
        "a group we just created should hold no rules"

    for label, call in [("options", lambda: monitor.firewall_options(loc)),
                        ("aliases", lambda: monitor.firewall_aliases(loc)),
                        ("ipsets", lambda: monitor.firewall_ipsets(loc)),
                        ("refs", lambda: monitor.firewall_refs(loc)),
                        ("log", lambda: monitor.firewall_log(loc))]:
        with pytest.raises(ProxmoxError) as exc:
            call()
        assert "type check" in str(exc.value), f"{label}: {exc.value}"


# ------------------------------------------------- 12. permission asymmetry

def test_lifecycle_client_cannot_read_any_scope(lifecycle, host, lxc_loc):
    """The wider version of test_firewall_hardware.py's single check: the
    lifecycle token is refused on EVERY firewall read, at every scope, while it
    writes all of them. That is what services/firewall.py's readers/writers
    split exists for."""
    reads = [
        ("cluster rules", lambda: lifecycle.firewall_rules(cluster_loc()), "Sys.Audit"),
        ("cluster options", lambda: lifecycle.firewall_options(cluster_loc()), "Sys.Audit"),
        ("cluster aliases", lambda: lifecycle.firewall_aliases(cluster_loc()), "Sys.Audit"),
        ("cluster ipsets", lambda: lifecycle.firewall_ipsets(cluster_loc()), "Sys.Audit"),
        ("cluster refs", lambda: lifecycle.firewall_refs(cluster_loc()), "Sys.Audit"),
        ("node rules", lambda: lifecycle.firewall_rules(node_loc(host.node_name)), "Sys.Audit"),
        ("node options", lambda: lifecycle.firewall_options(node_loc(host.node_name)), "Sys.Audit"),
        ("node log", lambda: lifecycle.firewall_log(node_loc(host.node_name)), "Sys.Syslog"),
        ("guest rules", lambda: lifecycle.firewall_rules(lxc_loc), "VM.Audit"),
        ("guest options", lambda: lifecycle.firewall_options(lxc_loc), "VM.Audit"),
        ("guest aliases", lambda: lifecycle.firewall_aliases(lxc_loc), "VM.Audit"),
        ("guest ipsets", lambda: lifecycle.firewall_ipsets(lxc_loc), "VM.Audit"),
        ("guest refs", lambda: lifecycle.firewall_refs(lxc_loc), "VM.Audit"),
    ]
    for label, call, privilege in reads:
        with pytest.raises(ProxmoxError) as exc:
            call()
        message = str(exc.value)
        assert "403" in message, f"{label}: {message}"
        assert privilege in message, f"{label}: {message}"

    # The two cluster-wide LISTS are the exception and stay readable, so a
    # writer never needs a second client just to name a group or a macro.
    assert isinstance(lifecycle.firewall_groups(), list)
    assert isinstance(lifecycle.firewall_macros(), list)


def test_lifecycle_client_can_write_every_scope(monitor, lifecycle, made,
                                                host, lxc_loc):
    """The half that makes the test above meaningful: the same token that is
    refused every read writes every scope. Read back through the monitoring
    client, since the writer cannot see its own work."""
    made.watch_groups()
    for label, loc in [("cluster", cluster_loc()),
                       ("node", node_loc(host.node_name)),
                       ("guest", lxc_loc)]:
        made.watch(loc)
        comment = made.rule(loc, {"type": "in", "action": "ACCEPT",
                                  "comment": f"{PX}-w-{label}"})
        assert comment in _comments(monitor, loc), f"{label} write did not land"

    made.alias(cluster_loc(), {"name": f"{PX}wal", "cidr": "10.99.0.0/16"})
    made.ipset(cluster_loc(), {"name": f"{PX}wset"})
    group = made.group({"group": f"{PX}wgrp"})
    assert any(g["group"] == group for g in monitor.firewall_groups())


def test_monitoring_client_cannot_write(rig, monitor, host, lxc_loc):
    """The other direction, which the existing suite never proves.

    Skips rather than passing when the monitoring slot holds a root token: root
    writes everything by design, so an assertion here would be a claim about the
    lab's enrolment and not about the least-privilege role.
    """
    token_id = rig[3]["token_id"]
    if token_id.startswith("root@"):
        pytest.skip(f"monitoring slot holds {token_id}, a root token: it writes "
                    "everything by design, so the read-only claim is untestable "
                    "until the host is re-enrolled with a ProxployAudit token")
    writes = [
        ("cluster rule", lambda: monitor.firewall_rule_create(
            cluster_loc(), {"type": "in", "action": "ACCEPT", "comment": f"{PX}-mon"})),
        ("node rule", lambda: monitor.firewall_rule_create(
            node_loc(host.node_name),
            {"type": "in", "action": "ACCEPT", "comment": f"{PX}-mon"})),
        ("guest rule", lambda: monitor.firewall_rule_create(
            lxc_loc, {"type": "in", "action": "ACCEPT", "comment": f"{PX}-mon"})),
        ("cluster options", lambda: monitor.firewall_options_update(
            cluster_loc(), {"policy_out": "ACCEPT"})),
        ("alias", lambda: monitor.firewall_alias_create(
            cluster_loc(), {"name": f"{PX}mon", "cidr": "10.96.0.0/16"})),
        ("ipset", lambda: monitor.firewall_ipset_create(cluster_loc(),
                                                        {"name": f"{PX}mon"})),
        ("group", lambda: monitor.firewall_group_create({"group": f"{PX}mon"})),
    ]
    for label, call in writes:
        with pytest.raises(ProxmoxError) as exc:
            call()
        assert "403" in str(exc.value), f"{label}: {exc.value}"


# ------------------------------------------------------------- the last word

def test_nothing_this_run_created_is_left_behind(monitor, run_snapshot):
    """Runs last on purpose.

    Says two things and deliberately not a third. It says every object that was
    on this cluster before the module ran is STILL there, and it says nothing
    carrying our prefix survives. It does NOT say any scope is empty, and it
    deletes nothing: if a leak is reported here the fix is to go look, not to
    sweep.
    """
    snapshot, groups_before = run_snapshot
    problems: list[str] = []

    for label, (loc, rules, aliases, ipsets) in snapshot.items():
        now_rules = monitor.firewall_rules(loc)
        if not _is_subsequence(rules, _keys(now_rules)):
            problems.append(f"{label}: rules present at the start are gone or "
                            f"reordered")
        leaked = [r.get("comment") for r in now_rules
                  if str(r.get("comment", "")).startswith(PX)]
        if leaked:
            problems.append(f"{label}: rules left behind {leaked}")

        if aliases is not None:
            now = {a["name"] for a in monitor.firewall_aliases(loc)}
            if aliases - now:
                problems.append(f"{label}: aliases disappeared {sorted(aliases - now)}")
            if {n for n in now if n.startswith(PX)}:
                problems.append(f"{label}: aliases left behind "
                                f"{sorted(n for n in now if n.startswith(PX))}")
        if ipsets is not None:
            now = {s["name"] for s in monitor.firewall_ipsets(loc)}
            if ipsets - now:
                problems.append(f"{label}: IP sets disappeared {sorted(ipsets - now)}")
            if {n for n in now if n.startswith(PX)}:
                problems.append(f"{label}: IP sets left behind "
                                f"{sorted(n for n in now if n.startswith(PX))}")

    groups_now = {g["group"] for g in monitor.firewall_groups()}
    if groups_before - groups_now:
        problems.append(f"security groups disappeared "
                        f"{sorted(groups_before - groups_now)}")
    leaked_groups = {g for g in groups_now if g.startswith(PX)} - groups_before
    if leaked_groups:
        problems.append(f"security groups left behind {sorted(leaked_groups)}")

    assert not problems, "; ".join(problems)
