# backend/proxploy/services/hostclient.py
"""The one decrypt-then-construct helper: a Host row -> a ProxmoxClient.

api/consoles.py and services/lifecycle.py each carried their own copy of these
five lines; consoles.py's copy even carried a comment naming a 4th call site as
the tip-over point for extracting it. Phase 6 adds three routers and twelve job
handlers that all need it, so it is one function now and the copies are gone.

It raises ProxmoxError, never HTTPException, never JobFailed; because both
kinds of caller live here: a route turns it into a 409, a job handler into a
JobFailed. That translation is one line at each call site and keeps this module
free of both FastAPI and the job engine.

Not used by api/hosts.py::test_host, deliberately: that route also needs the
HostCredential row itself (to stamp `last_used_at`), which this helper does not
return, so folding it in would mean widening the return type for one caller.

Step one of the per-capability host token work (host-token-privileges-
step-one-report.md) put the capability into `client_for_host` itself: storage
is `host_credentials.kind = "api_token:<capability>"` (monitoring/lifecycle/
console/backup), never a second WHERE clause threaded through every caller,
and `UniqueConstraint(host_id, kind)` already enforces one token per
capability with no schema change. `capability` defaults to "monitoring"
because that is the one every host is guaranteed to have (it is mandatory at
enrolment); every other call site names the capability it actually needs.
"""
from __future__ import annotations

import json as jsonlib

from proxploy.models import Host, HostCredential
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError


class CapabilityNotConfigured(ProxmoxError):
    """Raised the moment a call site asks for a capability this host has no
    token for, before any network call is made.

    A `ProxmoxError` subclass on purpose: every existing `except
    ProxmoxError` block across the codebase (routes turning it into an
    HTTPException, job handlers turning it into a JobFailed) catches this
    without any changes, while `kind == "capability_missing"` and the
    `.capability` attribute let a caller that wants to say something more
    specific (e.g. a structured 400 naming where to add the token) do so.
    Same shape as api/catalog.py's `install_catalog_entry` checking for an
    `ssh_key` row before ever reaching the executor, generalized to four
    capabilities instead of one always-or-never credential.
    """

    def __init__(self, host_name: str, capability: str):
        self.capability = capability
        super().__init__(
            f"{host_name} has no {capability} API token configured; add one "
            f"in Settings -> Hosts before this operation can run.",
            kind="capability_missing")


def client_for_host(app, db, host: Host, capability: str = "monitoring") -> ProxmoxClient:
    cred = (db.query(HostCredential)
            .filter_by(host_id=host.id, kind=f"api_token:{capability}").one_or_none())
    if cred is None:
        raise CapabilityNotConfigured(host.name, capability)
    tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
    return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                         verify_tls=host.verify_tls,
                         tls_fingerprint=host.tls_fingerprint,
                         factory=app.state.proxmox_factory)
