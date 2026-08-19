from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import RootModel

from proxploy.api.deps import authorize, get_db
from proxploy.models import AppSetting, User
from proxploy.services.audit import write_audit
from proxploy.services.settings import set_setting

router = APIRouter(prefix="/settings", tags=["settings"])

_read = authorize("settings", "read")
_manage = authorize("settings", "manage")


class SettingsPatch(RootModel[dict[str, object]]):
    pass


# What the UI actually PATCHes here: onboarding's "finish" step and nothing
# else. oidc.* is included for the settings its own route writes through
# this same key space; a fresh key like self.host_id or license.install_id
# gets its own dedicated route (PXP-33) instead of a hole in this list.
_ALLOWED_KEYS = {"onboarding.complete"}


def _key_allowed(key: str) -> bool:
    return key in _ALLOWED_KEYS or key.startswith("oidc.")


@router.get("")
def list_settings(db=Depends(get_db), user: User = Depends(_read)):
    return {r.key: r.value for r in db.query(AppSetting)
            if not r.key.endswith(".enc")}


@router.patch("")
def patch_settings(request: Request, body: SettingsPatch, db=Depends(get_db),
                   user: User = Depends(_manage)):
    if any(k.endswith(".enc") for k in body.root):
        raise HTTPException(422, "secret-bearing keys are managed by their own flows")
    if any(not _key_allowed(k) for k in body.root):
        raise HTTPException(422, "that setting is not writable through this route")
    for k, v in body.root.items():
        set_setting(db, k, v)
    write_audit(db, actor_type="user", actor_id=user.id, action="settings.update",
                params={"keys": sorted(body.root)})
    return {"ok": True}
