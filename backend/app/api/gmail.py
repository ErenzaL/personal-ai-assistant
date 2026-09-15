"""Gmail API: connection status only. Read-only OAuth (gmail.readonly);
message reading and search are not implemented yet.

Connection state lives entirely in `gmail_service` (a token file on disk,
read live), so unlike most routers here there is no `db` dependency at all.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import gmail_service
from app.services.gmail_service import (
    CredentialsFileInvalid,
    CredentialsFileMissing,
    GmailError,
    GmailNetworkError,
    NotConnected,
    OAuthCancelled,
)

router = APIRouter(prefix="/gmail", tags=["gmail"])

# 422: something the user must fix locally (a missing/bad credentials file).
# 409: the action could not proceed as asked, but nothing is broken (sign-in
#      cancelled, or a read attempted while disconnected).
# 502: Google itself could not be reached.
_STATUS = {
    CredentialsFileMissing: 422,
    CredentialsFileInvalid: 422,
    OAuthCancelled: 409,
    NotConnected: 409,
    GmailNetworkError: 502,
}


def _http(err: GmailError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(type(err), 502), detail=err.message)


class GmailStatusOut(BaseModel):
    connected: bool
    """Set only when there is something more useful to say than a plain
    "not connected" -- currently just a refresh that couldn't reach Google."""
    detail: str | None = None

    @classmethod
    def from_status(cls, status: gmail_service.GmailStatus) -> "GmailStatusOut":
        return cls(connected=status.connected, detail=status.detail)


@router.get("/status", response_model=GmailStatusOut)
def status() -> GmailStatusOut:
    """Read live: refreshes the token if it is due, same as the desktop
    app's Calendar permission is never cached as a separate flag."""
    return GmailStatusOut.from_status(gmail_service.status())


@router.post("/connect", response_model=GmailStatusOut)
def connect() -> GmailStatusOut:
    """Opens the user's browser for Google sign-in and blocks until it
    finishes, is denied, or times out. A plain `def` route on purpose:
    FastAPI runs these in its worker thread pool, so this blocking call
    never ties up the event loop other requests depend on."""
    try:
        gmail_service.connect()
    except GmailError as err:
        raise _http(err) from err
    return GmailStatusOut(connected=True)


@router.post("/disconnect", response_model=GmailStatusOut)
def disconnect() -> GmailStatusOut:
    """Always succeeds locally, even if Google could not be reached to
    revoke the token server-side (see `gmail_service.disconnect`)."""
    gmail_service.disconnect()
    return GmailStatusOut(connected=False)
