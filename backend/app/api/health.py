from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check. The desktop app also reads `app` to make sure the
    server on this port is Dully's own and not some other program."""
    return {"status": "ok", "app": "dully"}
