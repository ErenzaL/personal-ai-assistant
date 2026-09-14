from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by the desktop app to confirm the backend is up."""
    return {"status": "ok"}
