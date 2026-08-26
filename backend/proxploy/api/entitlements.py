import asyncio
import random

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.deps import authorize, get_db, get_entitlements
from proxploy.entitlements.client import TokenInvalid
from proxploy.models import AppSetting, EntitlementCache, to_iso, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.fingerprint import collect as collect_fingerprint
from proxploy.services.fingerprint import new_installation_id
from proxploy.services.license_client import LicenseApiError, SeatOccupied
from proxploy.services.settings import get_setting as _setting
from proxploy.services.settings import set_setting as _set_setting

router = APIRouter(prefix="/entitlements", tags=["entitlements"])

_read = authorize("entitlement", "read")
_manage = authorize("entitlement", "manage")


@router.get("", dependencies=[Depends(_read)])
def entitlements(ent=Depends(get_entitlements)):
    st = ent.status()
    grace = None
    if st.source == "token":
        grace = {"expires_at": to_iso(st.expires_at),
                 "grace_until": to_iso(st.grace_until), "in_grace": st.in_grace}
    return {"tier": st.tier, "features": ent.snapshot(), "grace": grace,
            "clock_skew": st.clock_skew}


class LicenseIn(BaseModel):
    license_key: str


class TransferIn(BaseModel):
    license_key: str
    recovery_code: str


# Not "license.install_id": identity outlives any particular licence, and
# nesting it under that prefix is what let remove_license delete it, so an
# install went anonymous every time a licence was removed and came back as a
# stranger asking for a seat it already had.
INSTALL_ID_KEY = "install.id"
HEARTBEAT_SEQ_KEY = "license.heartbeat_seq"


def installation_id(db) -> str:
    """Created on first use and never rotated. A clone copies it, which is
    why the fingerprint and the heartbeat sequence exist; on its own this
    only distinguishes deployments, not machines."""
    existing = _setting(db, INSTALL_ID_KEY) or _setting(db, "license.install_id")
    if existing:
        if not _setting(db, INSTALL_ID_KEY):
            _set_setting(db, INSTALL_ID_KEY, existing)
        return existing
    fresh = new_installation_id()
    _set_setting(db, INSTALL_ID_KEY, fresh)
    return fresh


def next_heartbeat_seq(db) -> int:
    """Monotonic, persisted. The service reads a value at or below one it has
    already seen as two installations sharing a seat, which is the only local
    signal a byte-for-byte clone cannot forge away without also diverging."""
    nxt = int(_setting(db, HEARTBEAT_SEQ_KEY) or 0) + 1
    _set_setting(db, HEARTBEAT_SEQ_KEY, str(nxt))
    return nxt


def apply_new_token(request: Request, db, token: str, cert: str) -> None:
    """Verify, then persist (token + cert, same commit) + reload the
    in-memory client. Same commit because a row with a token and no cert is
    unverifiable on the next restart: both land or neither does."""
    from proxploy.entitlements.client import _ts

    ent = request.app.state.entitlements
    claims = ent.verify(token, cert)
    ent.apply_claims(claims)
    ss = request.app.state.secretstore
    enc, _ = ss.encrypt(token.encode())
    row = db.get(EntitlementCache, 1)
    if not row:
        row = EntitlementCache(id=1)
        db.add(row)
    row.token = enc.decode()
    row.cert = cert  # not encrypted (see EntitlementCache.cert)
    row.tier = claims["tier"]
    row.features = claims["features"]
    row.issued_at = _ts(claims["iat"])
    row.expires_at = _ts(claims["exp"])
    row.grace_until = _ts(claims["grace_until"])
    row.fetched_at = row.last_verified_at = utcnow()
    db.commit()


async def _refresh_loop(app) -> None:
    while True:
        interval = app.state.settings.license_heartbeat_interval_s
        # Jittered so a fleet activated together does not heartbeat in lockstep.
        await asyncio.sleep(interval + random.uniform(0, interval * 0.05))
        try:
            with app.state.sessionmaker() as db:
                row = (db.query(AppSetting)
                       .filter_by(key="license.refresh_credential.enc").one_or_none())
                if not row:
                    # continue, not return: an owner who removes the
                    # license and activates a new one later would
                    # otherwise get no auto-refresh until a restart,
                    # and the token lapses to builtin after grace.
                    continue
                install_id = installation_id(db)
                seq = next_heartbeat_seq(db)
                cred = app.state.secretstore.decrypt(row.value.encode()).decode()
                # refresh() is synchronous httpx with a 10s timeout.
                # On the loop it stalls SSE pings, console frames and
                # every job's await_task poll with it, the same reason
                # the poller and scheduler hand their blocking calls to
                # a thread.
                out = await asyncio.to_thread(
                    app.state.license_client.refresh,
                    cred, install_id, collect_fingerprint(), seq)
                # apply via a fake-request shim: the helper only needs .app
                class _Req:  # noqa: N801  (minimal shim)
                    pass
                req = _Req(); req.app = app
                apply_new_token(req, db, out["token"], out.get("cert"))
        except Exception:
            continue  # doc 07 §8: transient failure = keep serving, retry later


async def _create_refresh_task(app) -> None:
    app.state.refresh_task = asyncio.create_task(_refresh_loop(app))


def start_refresh_loop(app) -> None:
    """Start the background entitlement-refresh loop, unless one is already running.

    Called from two places: the app lifespan at boot (only when a license is
    already on file), and set_license below (so activating a fresh license
    gets auto-refresh right away instead of waiting for a restart). Idempotent
    by design: a handle already on app.state that has not finished means a
    loop is already running, so activating twice never starts a second one.

    set_license is a sync route, which FastAPI runs in a worker thread with
    no event loop of its own, so asyncio.create_task would raise "no running
    event loop" there. Hop onto the app's own loop (app.state.loop, set in
    main.py's lifespan) via run_coroutine_threadsafe and wait for that hop to
    land, so the task exists before the response is sent. The lifespan calls
    this from the loop directly, so no hop is needed there.
    """
    existing = getattr(app.state, "refresh_task", None)
    if existing is not None and not existing.done():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        future = asyncio.run_coroutine_threadsafe(_create_refresh_task(app), app.state.loop)
        future.result()
    else:
        app.state.refresh_task = asyncio.create_task(_refresh_loop(app))


@router.post("/license")
def set_license(request: Request, body: LicenseIn, db=Depends(get_db),
                user=Depends(_manage)):
    install_id = installation_id(db)
    lc = request.app.state.license_client
    try:
        out = lc.activate(body.license_key, install_id, collect_fingerprint())
    except SeatOccupied as e:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="entitlement.license.set", result="error")
        # 409 through to the browser, not the 502 a generic licensing failure
        # gets: this is a state the owner can resolve, and the UI needs the
        # occupant summary to offer a transfer.
        raise HTTPException(409, e.detail)
    except LicenseApiError as e:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="entitlement.license.set", result="error")
        raise HTTPException(502, f"licensing service: {e}")
    try:
        apply_new_token(request, db, out["token"], out.get("cert"))
    except TokenInvalid as e:
        # No state mutated above this point: apply_new_token verifies before
        # it writes anything, so a bad new token never destroys a good
        # cached one (see test_a_token_the_install_cannot_verify_does_not_destroy_the_cached_one).
        raise HTTPException(
            502, f"licensing service returned a token this install cannot verify: {e}")
    # doc note (Task 8 review): refresh_credential is null on an idempotent
    # same-install reactivation: only non-null on first-ever activation for
    # this license. Keep whatever we already have on file in that case.
    cred = out.get("refresh_credential")
    if cred:
        enc, _ = request.app.state.secretstore.encrypt(cred.encode())
        _set_setting(db, "license.refresh_credential.enc", enc.decode())
    # PXP-31: boot only starts the loop when a license is already on file, so
    # an install that just activated its first license would otherwise get no
    # auto-refresh until a restart. start_refresh_loop is idempotent, so this
    # is a no-op on a reactivation that finds the loop already running.
    start_refresh_loop(request.app)
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.set")
    return {"ok": True, "tier": request.app.state.entitlements.status().tier}


@router.post("/license/transfer")
def transfer_license(request: Request, body: TransferIn, db=Depends(get_db),
                     user=Depends(_manage)):
    """Take the seat from an installation that cannot hand it back.

    The recovery code, not the licence key, is what authorises this. It is
    deliberately not stored on the install: keeping it here would mean a
    cloned or stolen disk carried everything needed to take the seat, which
    is the property this whole endpoint exists to prevent.
    """
    install_id = installation_id(db)
    try:
        out = request.app.state.license_client.transfer(
            body.license_key, install_id, body.recovery_code, collect_fingerprint())
    except LicenseApiError as e:
        write_audit(db, actor_type="user", actor_id=user.id,
                    action="entitlement.license.transfer", result="error")
        raise HTTPException(502, f"licensing service: {e}")
    try:
        apply_new_token(request, db, out["token"], out.get("cert"))
    except TokenInvalid as e:
        raise HTTPException(
            502, f"licensing service returned a token this install cannot verify: {e}")
    cred = out.get("refresh_credential")
    if cred:
        enc, _ = request.app.state.secretstore.encrypt(cred.encode())
        _set_setting(db, "license.refresh_credential.enc", enc.decode())
    # The transferred-from install keeps heartbeating until its own credential
    # is refused, so this install's sequence must start clean rather than
    # inherit a counter the service has already seen from the other machine.
    _set_setting(db, HEARTBEAT_SEQ_KEY, "0")
    start_refresh_loop(request.app)
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.transfer")
    return {"ok": True, "tier": request.app.state.entitlements.status().tier}


@router.get("/activations", dependencies=[Depends(_read)])
def activations(request: Request, db=Depends(get_db)):
    """Every installation that has held this licence. Read through the
    service rather than cached locally: the point is to show the owner what
    the service believes, which is the thing they are about to act on."""
    enc = _setting(db, "license.refresh_credential.enc")
    if not enc:
        return {"activations": []}
    cred = request.app.state.secretstore.decrypt(enc.encode()).decode()
    try:
        return request.app.state.license_client.activations(cred, installation_id(db))
    except LicenseApiError as e:
        raise HTTPException(502, f"licensing service: {e}")


@router.post("/refresh")
def force_refresh(request: Request, db=Depends(get_db),
                  user=Depends(_manage)):
    enc = _setting(db, "license.refresh_credential.enc")
    if not enc:
        raise HTTPException(409, "no license configured")
    install_id = installation_id(db)
    cred = request.app.state.secretstore.decrypt(enc.encode()).decode()
    try:
        out = request.app.state.license_client.refresh(
            cred, install_id, collect_fingerprint(), next_heartbeat_seq(db))
    except LicenseApiError as e:
        raise HTTPException(502, f"licensing service: {e}")
    try:
        apply_new_token(request, db, out["token"], out.get("cert"))
    except TokenInvalid as e:
        raise HTTPException(
            502, f"licensing service returned a token this install cannot verify: {e}")
    write_audit(db, actor_type="user", actor_id=user.id, action="entitlement.refresh")
    return {"ok": True}


@router.delete("/license")
def remove_license(request: Request, db=Depends(get_db),
                   user=Depends(_manage)):
    enc = _setting(db, "license.refresh_credential.enc")
    row = db.get(EntitlementCache, 1)
    if row:
        row.token = None
        row.tier = "builtin"
        row.features = {}
    # Hand the seat back so the next install claims it normally instead of
    # needing a transfer. Best effort and deliberately not fatal: removing a
    # licence from a box that cannot reach the service must still work.
    if enc:
        try:
            request.app.state.license_client.release(
                request.app.state.secretstore.decrypt(enc.encode()).decode(),
                installation_id(db))
        except LicenseApiError:
            pass
    # INSTALL_ID_KEY is NOT deleted: identity outlives the licence, and
    # dropping it made a reinstall look like a stranger claiming a held seat.
    for key in ("license.refresh_credential.enc", HEARTBEAT_SEQ_KEY):
        db.query(AppSetting).filter_by(key=key).delete()
    db.commit()
    request.app.state.entitlements.reset_builtin()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.remove")
    return {"ok": True}
