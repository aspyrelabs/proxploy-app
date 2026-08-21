"""Firewall rules, options and objects at cluster, node, guest and security
group scope.

Live passthrough, exactly as api/network.py's bridge reads are: no model, no
cache, no migration, and nothing in the poller. Firewall rules are
configuration rather than telemetry, and reading them per guest on a schedule
would break the O(nodes) call budget in doc 02 section 3. Rules load when a
page asks for them.

These are NOT jobs. Every firewall write returns null rather than a UPID
(measured on pve-manager 9.2.11, 2026-08-21), so there is no PVE task to
follow. Same call shape as api/network.py::set_guest_nic.

Spec: docs/superpowers/specs/2026-08-21-firewall-design.md
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxploy.api.deps import (authorize, get_db, require_entitlement,
                               scope_host)
from proxploy.models import Host, User
from proxploy.services import firewall as fw
from proxploy.services.audit import write_audit
from proxploy.services.proxmox import ProxmoxError

router = APIRouter(prefix="/firewall", tags=["firewall"])

# Singleton first in dependencies=[...] and reused as the parameter dep, so
# auth runs before the entitlement gate and FastAPI collapses the two
# (deps.py idiom; test_route_auth_invariant.py enforces it).
_read = authorize("firewall", "read", scope_of=scope_host())
_manage = authorize("firewall", "manage", scope_of=scope_host())


def _host_or_404(db, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "That host is not enrolled.")
    return host


def pve_error(e: ProxmoxError) -> HTTPException:
    """A 502 means Proxploy could not complete a call to Proxmox, never that
    the rule was rejected: PVE's own refusals arrive as text inside this.

    The one exception is a digest conflict, which PVE reports as a 500 with
    "detected modified configuration - file changed by other user? Try again."
    That is not a bad gateway; it is somebody else editing the same scope, and
    the operator's next move is to reload rather than retry. Matched on the
    message because ProxmoxError.kind cannot tell it apart from any other 500.
    Measured on pve-manager 9.2.11, 2026-08-21.
    """
    if "detected modified configuration" in str(e):
        return HTTPException(409, "Somebody else changed this firewall scope "
                                  "while you were editing it. Reload to see "
                                  "their changes, then make yours again.")
    return HTTPException(502, str(e))


class RuleIn(BaseModel):
    """One firewall rule, in PVE's own vocabulary.

    `icmp-type` is aliased rather than renamed. It is not a valid Python
    identifier, so it cannot be a field name or a keyword argument, and any
    snake_case translation on the way through drops the field silently.
    Everything here dumps with by_alias=True for that one reason.

    `enable` is an integer, not a boolean: PVE's schema says
    "<integer> (0 - N)". Sending true would be serialised as "True".
    """
    model_config = {"populate_by_name": True}

    type: str                       # in, out, forward, group
    action: str                     # ACCEPT, DROP, REJECT, or a group name
    enable: int | None = None
    macro: str | None = None
    iface: str | None = None
    source: str | None = None
    dest: str | None = None
    sport: str | None = None
    dport: str | None = None
    proto: str | None = None
    log: str | None = None
    icmp_type: str | None = Field(default=None, alias="icmp-type")
    comment: str | None = None
    digest: str | None = None


class RulePatch(BaseModel):
    """Every field optional. Only fields PRESENT in the body are applied, so
    the handler dumps with exclude_unset=True: absent means "leave alone"."""
    model_config = {"populate_by_name": True}

    type: str | None = None
    action: str | None = None
    enable: int | None = None
    macro: str | None = None
    iface: str | None = None
    source: str | None = None
    dest: str | None = None
    sport: str | None = None
    dport: str | None = None
    proto: str | None = None
    log: str | None = None
    icmp_type: str | None = Field(default=None, alias="icmp-type")
    comment: str | None = None
    digest: str | None = None
    delete: str | None = None       # PVE's own "unset these keys" parameter


class MoveIn(BaseModel):
    moveto: int
    digest: str | None = None


def rule_params(model: BaseModel, *, partial: bool = False) -> dict:
    """PVE-shaped keys, hyphen intact, Nones dropped by the client layer."""
    return model.model_dump(by_alias=True, exclude_unset=partial,
                            exclude_none=True)


# ---------------------------------------------------------------- rules

def _rules_read(request: Request, db, host: Host, loc: dict, scope: str) -> dict:
    try:
        rules = fw.readers(request.app, db, host).firewall_rules(loc)
    except ProxmoxError as e:
        raise pve_error(e)
    # PVE returns the digest on each rule row rather than on the collection.
    # Surfacing the first one gives the client something to send back on a
    # write without it having to know that.
    digest = rules[0].get("digest") if rules else None
    return {"scope": scope, "rules": rules, "digest": digest}


def _rules_write(request: Request, db, user: User, host: Host, loc: dict, *,
                 action: str, label: str, params: dict, call) -> None:
    ip = request.client.host if request.client else None
    try:
        call(fw.writers(request.app, db, host))
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action=action,
                    target_type="host", target_id=host.id, target_name=label,
                    params=params, result="error", ip=ip)
        raise pve_error(e)
    write_audit(db, actor_type="user", actor_id=user.id, action=action,
                target_type="host", target_id=host.id, target_name=label,
                params=params, ip=ip)


@router.get("/cluster/{host_id}/rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_rules(request: Request, host_id: int, db=Depends(get_db),
                  user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _rules_read(request, db, host, fw.cluster_loc(), "cluster")


@router.post("/cluster/{host_id}/rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.rules"))])
def cluster_rule_create(request: Request, host_id: int, body: RuleIn,
                        db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body)
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_create",
                 label=f"cluster firewall on {host.name}", params=params,
                 call=lambda c: c.firewall_rule_create(fw.cluster_loc(), params))
    return {"created": True}


@router.put("/cluster/{host_id}/rules/{pos}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def cluster_rule_update(request: Request, host_id: int, pos: int,
                        body: RulePatch, db=Depends(get_db),
                        user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body, partial=True)
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_update",
                 label=f"rule {pos} in the cluster firewall on {host.name}",
                 params=params,
                 call=lambda c: c.firewall_rule_update(fw.cluster_loc(), pos, params))
    return {"updated": True}


@router.put("/cluster/{host_id}/rules/{pos}/move",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def cluster_rule_move(request: Request, host_id: int, pos: int, body: MoveIn,
                      db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = {"moveto": body.moveto, "digest": body.digest}
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_move",
                 label=f"rule {pos} in the cluster firewall on {host.name}",
                 params={"moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(fw.cluster_loc(), pos,
                                                     body.moveto, body.digest))
    return {"moved": True, "pos": body.moveto}


@router.delete("/cluster/{host_id}/rules/{pos}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.rules"))])
def cluster_rule_delete(request: Request, host_id: int, pos: int,
                        digest: str | None = None, db=Depends(get_db),
                        user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.cluster_loc(),
                 action="firewall.rule_delete",
                 label=f"rule {pos} in the cluster firewall on {host.name}",
                 params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(fw.cluster_loc(), pos, digest))
    return {"deleted": True}


# ------------------------------------------------------- security group rules
#
# A security group IS a rule list (PVE documents GET on the group as "List
# rules"), so these are the cluster handlers above pointed at a different
# location, not a second implementation.

@router.get("/cluster/{host_id}/groups/{group}/rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def group_rules(request: Request, host_id: int, group: str, db=Depends(get_db),
                user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _rules_read(request, db, host, fw.group_loc(group), "group")


@router.post("/cluster/{host_id}/groups/{group}/rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.rules"))])
def group_rule_create(request: Request, host_id: int, group: str, body: RuleIn,
                      db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_create",
                 label=f"security group {group} on {host.name}", params=params,
                 call=lambda c: c.firewall_rule_create(fw.group_loc(group), params))
    return {"created": True}


@router.put("/cluster/{host_id}/groups/{group}/rules/{pos}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def group_rule_update(request: Request, host_id: int, group: str, pos: int,
                      body: RulePatch, db=Depends(get_db),
                      user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body, partial=True)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_update",
                 label=f"rule {pos} in security group {group} on {host.name}",
                 params=params,
                 call=lambda c: c.firewall_rule_update(fw.group_loc(group), pos,
                                                       params))
    return {"updated": True}


@router.put("/cluster/{host_id}/groups/{group}/rules/{pos}/move",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def group_rule_move(request: Request, host_id: int, group: str, pos: int,
                    body: MoveIn, db=Depends(get_db),
                    user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_move",
                 label=f"rule {pos} in security group {group} on {host.name}",
                 params={"moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(fw.group_loc(group), pos,
                                                     body.moveto, body.digest))
    return {"moved": True, "pos": body.moveto}


@router.delete("/cluster/{host_id}/groups/{group}/rules/{pos}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.rules"))])
def group_rule_delete(request: Request, host_id: int, group: str, pos: int,
                      digest: str | None = None, db=Depends(get_db),
                      user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.group_loc(group),
                 action="firewall.rule_delete",
                 label=f"rule {pos} in security group {group} on {host.name}",
                 params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(fw.group_loc(group), pos,
                                                       digest))
    return {"deleted": True}


# ----------------------------------------------------------------- node rules

@router.get("/node/{host_id}/{node}/rules",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def node_rules(request: Request, host_id: int, node: str, db=Depends(get_db),
               user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _rules_read(request, db, host, fw.node_loc(node), "node")


@router.post("/node/{host_id}/{node}/rules", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.rules"))])
def node_rule_create(request: Request, host_id: int, node: str, body: RuleIn,
                     db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_create",
                 label=f"firewall on {node}", params=params,
                 call=lambda c: c.firewall_rule_create(fw.node_loc(node), params))
    return {"created": True}


@router.put("/node/{host_id}/{node}/rules/{pos}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def node_rule_update(request: Request, host_id: int, node: str, pos: int,
                     body: RulePatch, db=Depends(get_db),
                     user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = rule_params(body, partial=True)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_update",
                 label=f"rule {pos} in the firewall on {node}", params=params,
                 call=lambda c: c.firewall_rule_update(fw.node_loc(node), pos,
                                                       params))
    return {"updated": True}


@router.put("/node/{host_id}/{node}/rules/{pos}/move",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.rules"))])
def node_rule_move(request: Request, host_id: int, node: str, pos: int,
                   body: MoveIn, db=Depends(get_db),
                   user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_move",
                 label=f"rule {pos} in the firewall on {node}",
                 params={"moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(fw.node_loc(node), pos,
                                                     body.moveto, body.digest))
    return {"moved": True, "pos": body.moveto}


@router.delete("/node/{host_id}/{node}/rules/{pos}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.rules"))])
def node_rule_delete(request: Request, host_id: int, node: str, pos: int,
                     digest: str | None = None, db=Depends(get_db),
                     user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    _rules_write(request, db, user, host, fw.node_loc(node),
                 action="firewall.rule_delete",
                 label=f"rule {pos} in the firewall on {node}",
                 params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(fw.node_loc(node), pos,
                                                       digest))
    return {"deleted": True}


# ------------------------------------------------------------------- options
#
# What PVE does when an option is ABSENT, transcribed from `pvesh usage` on
# pve-manager 9.2.11 on 2026-08-21. This exists for one reason: the warning
# shown when an operator enables a firewall has to say what will actually
# happen, and an absent policy_in is not "no policy", it is DROP. Reading an
# empty options object as "nothing is configured, so nothing will be blocked"
# is the exact misreading that got the NIC toggle removed in the first place.
#
# Only the options that change behaviour are listed. Conntrack sizing and
# timeouts are omitted deliberately: they tune a firewall, they do not decide
# whether traffic passes.
OPTION_DEFAULTS: dict[str, dict] = {
    "cluster": {"enable": 0, "ebtables": 1, "policy_in": "DROP",
                "policy_out": "ACCEPT", "policy_forward": "ACCEPT"},
    "node": {"enable": 0, "nftables": 0, "nosmurfs": 0, "log_nf_conntrack": 0,
             "ndp": 1},
    "guest": {"enable": 0, "dhcp": 0, "ndp": 1, "radv": 0, "macfilter": 1,
              "ipfilter": 0, "policy_in": "DROP", "policy_out": "ACCEPT"},
}


class OptionsIn(BaseModel):
    """Every field optional and dumped with exclude_unset, so a form that
    touched one switch sends one key. The union of all three scopes' options
    lives here; PVE rejects a key that does not belong to the scope it was
    sent to, which is the correct authority for that."""
    model_config = {"populate_by_name": True}

    enable: int | None = None
    policy_in: str | None = None
    policy_out: str | None = None
    policy_forward: str | None = None
    ebtables: int | None = None
    log_ratelimit: str | None = None
    log_level_in: str | None = None
    log_level_out: str | None = None
    log_nf_conntrack: int | None = None
    nftables: int | None = None
    nosmurfs: int | None = None
    smurf_log_level: str | None = None
    tcpflags: int | None = None
    ndp: int | None = None
    radv: int | None = None
    dhcp: int | None = None
    macfilter: int | None = None
    ipfilter: int | None = None
    digest: str | None = None
    delete: str | None = None


def _options_read(request: Request, db, host: Host, loc: dict, scope: str) -> dict:
    try:
        options = fw.readers(request.app, db, host).firewall_options(loc)
    except ProxmoxError as e:
        raise pve_error(e)
    return {"scope": scope, "options": options,
            "defaults": OPTION_DEFAULTS[scope],
            "digest": options.get("digest")}


def _options_write(request: Request, db, user: User, host: Host, loc: dict, *,
                   label: str, body: OptionsIn) -> dict:
    params = body.model_dump(by_alias=True, exclude_unset=True, exclude_none=True)
    ip = request.client.host if request.client else None
    try:
        fw.writers(request.app, db, host).firewall_options_update(loc, params)
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="firewall.options", target_type="host",
                    target_id=host.id, target_name=label, params=params,
                    result="error", ip=ip)
        raise pve_error(e)
    write_audit(db, actor_type="user", actor_id=user.id, action="firewall.options",
                target_type="host", target_id=host.id, target_name=label,
                params=params, ip=ip)
    return {"updated": True}


@router.get("/cluster/{host_id}/options",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_options(request: Request, host_id: int, db=Depends(get_db),
                    user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _options_read(request, db, host, fw.cluster_loc(), "cluster")


@router.put("/cluster/{host_id}/options",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.options"))])
def cluster_options_update(request: Request, host_id: int, body: OptionsIn,
                           db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    return _options_write(request, db, user, host, fw.cluster_loc(),
                          label=f"cluster firewall on {host.name}", body=body)


@router.get("/node/{host_id}/{node}/options",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def node_options(request: Request, host_id: int, node: str, db=Depends(get_db),
                 user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    return _options_read(request, db, host, fw.node_loc(node), "node")


@router.put("/node/{host_id}/{node}/options",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.options"))])
def node_options_update(request: Request, host_id: int, node: str,
                        body: OptionsIn, db=Depends(get_db),
                        user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    return _options_write(request, db, user, host, fw.node_loc(node),
                          label=f"firewall on {node}", body=body)


# ------------------------------------------------------- aliases and IP sets
#
# Cluster and guest scope only: a node has neither (measured, 9.2.11). The
# helpers take a location so Task 9's guest routes reuse them unchanged.

class AliasIn(BaseModel):
    name: str
    cidr: str
    comment: str | None = None


class AliasPatch(BaseModel):
    """`cidr` is required even on a pure rename: PVE's PUT schema marks it
    mandatory, so a rename that omits it is refused."""
    cidr: str
    comment: str | None = None
    rename: str | None = None
    digest: str | None = None


class IpSetIn(BaseModel):
    name: str
    comment: str | None = None


class MemberIn(BaseModel):
    cidr: str
    comment: str | None = None
    nomatch: int | None = None


class MemberPatch(BaseModel):
    comment: str | None = None
    nomatch: int | None = None
    digest: str | None = None


def _object_write(request: Request, db, user: User, host: Host, *,
                  action: str, label: str, params: dict, call) -> dict:
    ip = request.client.host if request.client else None
    try:
        call(fw.writers(request.app, db, host))
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action=action,
                    target_type="host", target_id=host.id, target_name=label,
                    params=params, result="error", ip=ip)
        raise pve_error(e)
    write_audit(db, actor_type="user", actor_id=user.id, action=action,
                target_type="host", target_id=host.id, target_name=label,
                params=params, ip=ip)
    return {"ok": True}


@router.get("/cluster/{host_id}/aliases",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_aliases(request: Request, host_id: int, db=Depends(get_db),
                    user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    try:
        return {"aliases": fw.readers(request.app, db, host)
                .firewall_aliases(fw.cluster_loc())}
    except ProxmoxError as e:
        raise pve_error(e)


@router.post("/cluster/{host_id}/aliases", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.objects"))])
def cluster_alias_create(request: Request, host_id: int, body: AliasIn,
                         db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = body.model_dump(exclude_none=True)
    return _object_write(request, db, user, host, action="firewall.alias_create",
                         label=f"alias {body.name} on {host.name}", params=params,
                         call=lambda c: c.firewall_alias_create(fw.cluster_loc(),
                                                                params))


@router.put("/cluster/{host_id}/aliases/{name}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.objects"))])
def cluster_alias_update(request: Request, host_id: int, name: str,
                         body: AliasPatch, db=Depends(get_db),
                         user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = body.model_dump(exclude_unset=True, exclude_none=True)
    return _object_write(request, db, user, host, action="firewall.alias_update",
                         label=f"alias {name} on {host.name}", params=params,
                         call=lambda c: c.firewall_alias_update(fw.cluster_loc(),
                                                                name, params))


@router.delete("/cluster/{host_id}/aliases/{name}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.objects"))])
def cluster_alias_delete(request: Request, host_id: int, name: str,
                         digest: str | None = None, db=Depends(get_db),
                         user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    return _object_write(request, db, user, host, action="firewall.alias_delete",
                         label=f"alias {name} on {host.name}", params={},
                         call=lambda c: c.firewall_alias_delete(fw.cluster_loc(),
                                                                name, digest))


@router.get("/cluster/{host_id}/ipsets",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_ipsets(request: Request, host_id: int, db=Depends(get_db),
                   user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    try:
        return {"ipsets": fw.readers(request.app, db, host)
                .firewall_ipsets(fw.cluster_loc())}
    except ProxmoxError as e:
        raise pve_error(e)


@router.post("/cluster/{host_id}/ipsets", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.objects"))])
def cluster_ipset_create(request: Request, host_id: int, body: IpSetIn,
                         db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = body.model_dump(exclude_none=True)
    return _object_write(request, db, user, host, action="firewall.ipset_create",
                         label=f"IP set {body.name} on {host.name}", params=params,
                         call=lambda c: c.firewall_ipset_create(fw.cluster_loc(),
                                                                params))


@router.delete("/cluster/{host_id}/ipsets/{name}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.objects"))])
def cluster_ipset_delete(request: Request, host_id: int, name: str,
                         force: bool = False, digest: str | None = None,
                         db=Depends(get_db), user: User = Depends(_manage)):
    """`force` is the caller's word, never this route's default: PVE refuses to
    delete a populated set without it, and silently supplying it would throw
    away members the operator may not have looked at."""
    host = _host_or_404(db, host_id)
    return _object_write(request, db, user, host, action="firewall.ipset_delete",
                         label=f"IP set {name} on {host.name}",
                         params={"force": force},
                         call=lambda c: c.firewall_ipset_delete(fw.cluster_loc(),
                                                                name, force, digest))


@router.get("/cluster/{host_id}/ipsets/{name}/members",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_ipset_members(request: Request, host_id: int, name: str,
                          db=Depends(get_db), user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    try:
        return {"members": fw.readers(request.app, db, host)
                .firewall_ipset_members(fw.cluster_loc(), name)}
    except ProxmoxError as e:
        raise pve_error(e)


@router.post("/cluster/{host_id}/ipsets/{name}/members", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.objects"))])
def cluster_ipset_member_add(request: Request, host_id: int, name: str,
                             body: MemberIn, db=Depends(get_db),
                             user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = body.model_dump(exclude_none=True)
    return _object_write(request, db, user, host, action="firewall.ipset_member_add",
                         label=f"{body.cidr} in IP set {name} on {host.name}",
                         params=params,
                         call=lambda c: c.firewall_ipset_member_add(
                             fw.cluster_loc(), name, params))


# `{cidr:path}`, not `{cidr}`: a CIDR contains a slash, and a plain path
# parameter stops at the first one, so `10.0.0.0/8` would never match this
# route at all. The client percent-encodes it again on the way out to PVE.
@router.put("/cluster/{host_id}/ipsets/{name}/members/{cidr:path}",
            dependencies=[Depends(_manage),
                          Depends(require_entitlement("firewall.objects"))])
def cluster_ipset_member_update(request: Request, host_id: int, name: str,
                                cidr: str, body: MemberPatch,
                                db=Depends(get_db),
                                user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = body.model_dump(exclude_unset=True, exclude_none=True)
    return _object_write(request, db, user, host,
                         action="firewall.ipset_member_update",
                         label=f"{cidr} in IP set {name} on {host.name}",
                         params=params,
                         call=lambda c: c.firewall_ipset_member_update(
                             fw.cluster_loc(), name, cidr, params))


@router.delete("/cluster/{host_id}/ipsets/{name}/members/{cidr:path}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.objects"))])
def cluster_ipset_member_delete(request: Request, host_id: int, name: str,
                                cidr: str, digest: str | None = None,
                                db=Depends(get_db),
                                user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    return _object_write(request, db, user, host,
                         action="firewall.ipset_member_delete",
                         label=f"{cidr} in IP set {name} on {host.name}",
                         params={},
                         call=lambda c: c.firewall_ipset_member_delete(
                             fw.cluster_loc(), name, cidr, digest))


# --------------------------------------- security groups, references, macros

class GroupIn(BaseModel):
    group: str
    comment: str | None = None


@router.get("/cluster/{host_id}/groups",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_groups(request: Request, host_id: int, db=Depends(get_db),
                   user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    try:
        return {"groups": fw.readers(request.app, db, host).firewall_groups()}
    except ProxmoxError as e:
        raise pve_error(e)


@router.post("/cluster/{host_id}/groups", status_code=201,
             dependencies=[Depends(_manage),
                           Depends(require_entitlement("firewall.objects"))])
def cluster_group_create(request: Request, host_id: int, body: GroupIn,
                         db=Depends(get_db), user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    params = body.model_dump(exclude_none=True)
    return _object_write(request, db, user, host, action="firewall.group_create",
                         label=f"security group {body.group} on {host.name}",
                         params=params,
                         call=lambda c: c.firewall_group_create(params))


@router.delete("/cluster/{host_id}/groups/{group}",
               dependencies=[Depends(_manage),
                             Depends(require_entitlement("firewall.objects"))])
def cluster_group_delete(request: Request, host_id: int, group: str,
                         digest: str | None = None, db=Depends(get_db),
                         user: User = Depends(_manage)):
    host = _host_or_404(db, host_id)
    return _object_write(request, db, user, host, action="firewall.group_delete",
                         label=f"security group {group} on {host.name}",
                         params={},
                         call=lambda c: c.firewall_group_delete(group, digest))


@router.get("/cluster/{host_id}/refs",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_refs(request: Request, host_id: int, type: str | None = None,
                 db=Depends(get_db), user: User = Depends(_read)):
    """Alias and IP set names a rule's source or dest may reference. The
    parameter is named `type` because that is PVE's own name for it."""
    host = _host_or_404(db, host_id)
    try:
        return {"refs": fw.readers(request.app, db, host)
                .firewall_refs(fw.cluster_loc(), ref_type=type)}
    except ProxmoxError as e:
        raise pve_error(e)


@router.get("/cluster/{host_id}/macros",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.view"))])
def cluster_macros(request: Request, host_id: int, db=Depends(get_db),
                   user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    try:
        return {"macros": fw.readers(request.app, db, host).firewall_macros()}
    except ProxmoxError as e:
        raise pve_error(e)


@router.get("/node/{host_id}/{node}/log",
            dependencies=[Depends(_read),
                          Depends(require_entitlement("firewall.log"))])
def node_log(request: Request, host_id: int, node: str, start: int = 0,
             limit: int = 500, since: int | None = None,
             until: int | None = None, db=Depends(get_db),
             user: User = Depends(_read)):
    host = _host_or_404(db, host_id)
    try:
        lines = fw.readers(request.app, db, host).firewall_log(
            fw.node_loc(node), start=start, limit=limit, since=since, until=until)
    except ProxmoxError as e:
        raise pve_error(e)
    return {"lines": lines, "start": start, "limit": limit}


# ------------------------------------------------------------- guest handlers
#
# These are NOT routes on this router. They are mounted by api/apps.py and
# api/vms.py, because scope_app() and scope_vm() resolve a row's team from
# request.path_params and nothing else (api/deps.py). A guest id carried as a
# query parameter would reach these handlers with no team scope at all, so the
# guest lives in the path of the router that already owns it. Same reason
# guest_nics and set_guest_nic live in api/network.py and are called from
# there.

def _guest_label(kind: str, vmid: int, row) -> str:
    name = getattr(row, "name", None)
    return name or f"{'VM' if kind == 'qemu' else 'CT'} {vmid}"


def guest_rules(request: Request, db, host: Host, kind: str, vmid: int, row):
    return _rules_read(request, db, host, fw.guest_loc(host, kind, vmid, row),
                       "guest")


def guest_rule_create(request: Request, db, user: User, host: Host, kind: str,
                      vmid: int, row, body: RuleIn):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = rule_params(body)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.rule_create", params=params,
                 call=lambda c: c.firewall_rule_create(loc, params))
    return {"created": True}


def guest_rule_update(request: Request, db, user: User, host: Host, kind: str,
                      vmid: int, row, pos: int, body: RulePatch):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = rule_params(body, partial=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.rule_update", params={"pos": pos, **params},
                 call=lambda c: c.firewall_rule_update(loc, pos, params))
    return {"updated": True}


def guest_rule_move(request: Request, db, user: User, host: Host, kind: str,
                    vmid: int, row, pos: int, body: MoveIn):
    loc = fw.guest_loc(host, kind, vmid, row)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.rule_move",
                 params={"pos": pos, "moveto": body.moveto},
                 call=lambda c: c.firewall_rule_move(loc, pos, body.moveto,
                                                     body.digest))
    return {"moved": True, "pos": body.moveto}


def guest_rule_delete(request: Request, db, user: User, host: Host, kind: str,
                      vmid: int, row, pos: int, digest: str | None):
    loc = fw.guest_loc(host, kind, vmid, row)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.rule_delete", params={"pos": pos},
                 call=lambda c: c.firewall_rule_delete(loc, pos, digest))
    return {"deleted": True}


def _guest_write(request: Request, db, user: User, host: Host, kind: str,
                 vmid: int, row, *, action: str, params: dict, call) -> None:
    """Audits against the GUEST, not the host: the operator reading the log
    needs to know which container's traffic changed, and the host is one row
    up from the answer."""
    ip = request.client.host if request.client else None
    target_type = "app" if kind == "lxc" else "vm"
    target_id = getattr(row, "id", None)
    label = _guest_label(kind, vmid, row)
    try:
        call(fw.writers(request.app, db, host))
    except ProxmoxError as e:
        write_audit(db, actor_type="user", actor_id=user.id, action=action,
                    target_type=target_type, target_id=target_id,
                    target_name=label, params=params, result="error", ip=ip)
        raise pve_error(e)
    write_audit(db, actor_type="user", actor_id=user.id, action=action,
                target_type=target_type, target_id=target_id,
                target_name=label, params=params, ip=ip)


def guest_options(request: Request, db, host: Host, kind: str, vmid: int, row):
    return _options_read(request, db, host, fw.guest_loc(host, kind, vmid, row),
                         "guest")


def guest_options_update(request: Request, db, user: User, host: Host,
                         kind: str, vmid: int, row, body: OptionsIn):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = body.model_dump(by_alias=True, exclude_unset=True, exclude_none=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.options", params=params,
                 call=lambda c: c.firewall_options_update(loc, params))
    return {"updated": True}


def guest_aliases(request: Request, db, host: Host, kind: str, vmid: int, row):
    try:
        return {"aliases": fw.readers(request.app, db, host).firewall_aliases(
            fw.guest_loc(host, kind, vmid, row))}
    except ProxmoxError as e:
        raise pve_error(e)


def guest_alias_create(request: Request, db, user: User, host: Host, kind: str,
                       vmid: int, row, body: AliasIn):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = body.model_dump(exclude_none=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.alias_create", params=params,
                 call=lambda c: c.firewall_alias_create(loc, params))
    return {"ok": True}


def guest_alias_update(request: Request, db, user: User, host: Host, kind: str,
                       vmid: int, row, name: str, body: AliasPatch):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = body.model_dump(exclude_unset=True, exclude_none=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.alias_update", params={"name": name, **params},
                 call=lambda c: c.firewall_alias_update(loc, name, params))
    return {"ok": True}


def guest_alias_delete(request: Request, db, user: User, host: Host, kind: str,
                       vmid: int, row, name: str, digest: str | None):
    loc = fw.guest_loc(host, kind, vmid, row)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.alias_delete", params={"name": name},
                 call=lambda c: c.firewall_alias_delete(loc, name, digest))
    return {"ok": True}


def guest_ipsets(request: Request, db, host: Host, kind: str, vmid: int, row):
    try:
        return {"ipsets": fw.readers(request.app, db, host).firewall_ipsets(
            fw.guest_loc(host, kind, vmid, row))}
    except ProxmoxError as e:
        raise pve_error(e)


def guest_ipset_create(request: Request, db, user: User, host: Host, kind: str,
                       vmid: int, row, body: IpSetIn):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = body.model_dump(exclude_none=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.ipset_create", params=params,
                 call=lambda c: c.firewall_ipset_create(loc, params))
    return {"ok": True}


def guest_ipset_delete(request: Request, db, user: User, host: Host, kind: str,
                       vmid: int, row, name: str, force: bool,
                       digest: str | None):
    loc = fw.guest_loc(host, kind, vmid, row)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.ipset_delete",
                 params={"name": name, "force": force},
                 call=lambda c: c.firewall_ipset_delete(loc, name, force, digest))
    return {"ok": True}


def guest_ipset_members(request: Request, db, host: Host, kind: str, vmid: int,
                        row, name: str):
    try:
        return {"members": fw.readers(request.app, db, host)
                .firewall_ipset_members(fw.guest_loc(host, kind, vmid, row), name)}
    except ProxmoxError as e:
        raise pve_error(e)


def guest_ipset_member_add(request: Request, db, user: User, host: Host,
                           kind: str, vmid: int, row, name: str, body: MemberIn):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = body.model_dump(exclude_none=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.ipset_member_add",
                 params={"ipset": name, **params},
                 call=lambda c: c.firewall_ipset_member_add(loc, name, params))
    return {"ok": True}


def guest_ipset_member_update(request: Request, db, user: User, host: Host,
                              kind: str, vmid: int, row, name: str, cidr: str,
                              body: MemberPatch):
    loc = fw.guest_loc(host, kind, vmid, row)
    params = body.model_dump(exclude_unset=True, exclude_none=True)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.ipset_member_update",
                 params={"ipset": name, "cidr": cidr, **params},
                 call=lambda c: c.firewall_ipset_member_update(loc, name, cidr,
                                                               params))
    return {"ok": True}


def guest_ipset_member_delete(request: Request, db, user: User, host: Host,
                              kind: str, vmid: int, row, name: str, cidr: str,
                              digest: str | None):
    loc = fw.guest_loc(host, kind, vmid, row)
    _guest_write(request, db, user, host, kind, vmid, row,
                 action="firewall.ipset_member_delete",
                 params={"ipset": name, "cidr": cidr},
                 call=lambda c: c.firewall_ipset_member_delete(loc, name, cidr,
                                                               digest))
    return {"ok": True}


def guest_refs(request: Request, db, host: Host, kind: str, vmid: int, row,
               ref_type: str | None = None):
    try:
        return {"refs": fw.readers(request.app, db, host).firewall_refs(
            fw.guest_loc(host, kind, vmid, row), ref_type=ref_type)}
    except ProxmoxError as e:
        raise pve_error(e)


def guest_log(request: Request, db, host: Host, kind: str, vmid: int, row, *,
              start: int, limit: int, since: int | None, until: int | None):
    try:
        lines = fw.readers(request.app, db, host).firewall_log(
            fw.guest_loc(host, kind, vmid, row), start=start, limit=limit,
            since=since, until=until)
    except ProxmoxError as e:
        raise pve_error(e)
    return {"lines": lines, "start": start, "limit": limit}
