from fastapi import APIRouter

from proxploy.api import audit, auth, entitlements, events, hosts, meta, settings

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(auth.users_router)
api_router.include_router(audit.router)
api_router.include_router(entitlements.router)
api_router.include_router(hosts.router)
api_router.include_router(settings.router)
api_router.include_router(events.router)
