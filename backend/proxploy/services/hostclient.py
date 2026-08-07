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
"""
from __future__ import annotations

import json as jsonlib

from proxploy.models import Host, HostCredential
from proxploy.services.proxmox import ProxmoxClient, ProxmoxError


def client_for_host(app, db, host: Host) -> ProxmoxClient:
    cred = (db.query(HostCredential)
            .filter_by(host_id=host.id, kind="api_token").one_or_none())
    if cred is None:
        raise ProxmoxError(f"host {host.name} has no API token credential")
    tok = jsonlib.loads(app.state.secretstore.decrypt(cred.encrypted_blob))
    return ProxmoxClient(host.address, tok["token_id"], tok["token_secret"],
                         verify_tls=host.verify_tls,
                         tls_fingerprint=host.tls_fingerprint,
                         factory=app.state.proxmox_factory)
