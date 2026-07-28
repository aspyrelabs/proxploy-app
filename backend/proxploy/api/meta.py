from fastapi import APIRouter

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok"}
