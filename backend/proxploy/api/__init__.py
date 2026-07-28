from fastapi import APIRouter

from proxploy.api import audit, auth, entitlements, meta

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
api_router.include_router(audit.router)
api_router.include_router(entitlements.router)
