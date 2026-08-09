import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from proxploy.api.deps import authorize, get_db, get_entitlements
from proxploy.entitlements.client import TokenInvalid
from proxploy.models import AppSetting, EntitlementCache, utcnow
from proxploy.services.audit import write_audit
from proxploy.services.license_client import LicenseApiError
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
        grace = {"expires_at": st.expires_at.isoformat(),
                 "grace_until": st.grace_until.isoformat(), "in_grace": st.in_grace}
    return {"tier": st.tier, "features": ent.snapshot(), "grace": grace,
            "clock_skew": st.clock_skew}


class LicenseIn(BaseModel):
    license_key: str


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


@router.post("/license")
def set_license(request: Request, body: LicenseIn, db=Depends(get_db),
                user=Depends(_manage)):
    install_id = _setting(db, "license.install_id")
    if not install_id:
        install_id = str(uuid.uuid4())
        _set_setting(db, "license.install_id", install_id)
    lc = request.app.state.license_client
    try:
        out = lc.activate(body.license_key, install_id)
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
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.set")
    return {"ok": True, "tier": request.app.state.entitlements.status().tier}


@router.post("/refresh")
def force_refresh(request: Request, db=Depends(get_db),
                  user=Depends(_manage)):
    enc = _setting(db, "license.refresh_credential.enc")
    if not enc:
        raise HTTPException(409, "no license configured")
    install_id = _setting(db, "license.install_id")
    cred = request.app.state.secretstore.decrypt(enc.encode()).decode()
    try:
        out = request.app.state.license_client.refresh(cred, install_id)
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
    row = db.get(EntitlementCache, 1)
    if row:
        row.token = None
        row.tier = "builtin"
        row.features = {}
    for key in ("license.refresh_credential.enc", "license.install_id"):
        db.query(AppSetting).filter_by(key=key).delete()
    db.commit()
    request.app.state.entitlements.reset_builtin()
    write_audit(db, actor_type="user", actor_id=user.id,
                action="entitlement.license.remove")
    return {"ok": True}
