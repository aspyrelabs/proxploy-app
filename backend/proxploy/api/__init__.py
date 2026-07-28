from fastapi import APIRouter

from proxploy.api import meta

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
