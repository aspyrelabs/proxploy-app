from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import RootModel

from proxploy.api.deps import get_db, require_role
from proxploy.models import AppSetting, User
from proxploy.services.audit import write_audit
from proxploy.services.settings import set_setting

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsPatch(RootModel[dict[str, object]]):
    pass


@router.get("")
def list_settings(db=Depends(get_db), user: User = Depends(require_role("admin"))):
    return {r.key: r.value for r in db.query(AppSetting)
            if not r.key.endswith(".enc")}


@router.patch("")
def patch_settings(request: Request, body: SettingsPatch, db=Depends(get_db),
                   user: User = Depends(require_role("admin"))):
    if any(k.endswith(".enc") for k in body.root):
        raise HTTPException(422, "secret-bearing keys are managed by their own flows")
    for k, v in body.root.items():
        set_setting(db, k, v)
    write_audit(db, actor_type="user", actor_id=user.id, action="settings.update",
                params={"keys": sorted(body.root)})
    return {"ok": True}
