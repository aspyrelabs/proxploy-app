from fastapi import APIRouter, Depends

from proxploy.api.deps import get_current_user, get_entitlements

router = APIRouter(prefix="/entitlements", tags=["entitlements"])


@router.get("", dependencies=[Depends(get_current_user)])
def entitlements(ent=Depends(get_entitlements)):
    st = ent.status()
    grace = None
    if st.source == "token":
        grace = {"expires_at": st.expires_at.isoformat(),
                 "grace_until": st.grace_until.isoformat(), "in_grace": st.in_grace}
    return {"tier": st.tier, "features": ent.snapshot(), "grace": grace}
