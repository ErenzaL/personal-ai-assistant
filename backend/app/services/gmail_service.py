"""Gmail read-only access via Google OAuth 2.0, Desktop app flow.

Scope is fixed at `SCOPES` below -- gmail.readonly and nothing broader.

Besides the connection itself (status, connect, disconnect), this module has
the three read operations the assistant's Gmail tools call: listing recent
mail, searching with Gmail's own query syntax, and reading one message in
full. Nothing here sends, deletes, archives, or marks mail read -- the
scope this app requests cannot do any of that even if asked to.

Two files on disk, both outside the source tree in production:

    <app-data>/gmail_credentials.json   the OAuth "client" identity -- the
                                         Desktop app JSON the user downloads
                                         once from Google Cloud Console and
                                         places by hand. Not a per-user
                                         secret (Google does not treat an
                                         installed-app client secret as
                                         confidential), but never bundled or
                                         committed regardless.
    <app-data>/gmail_token.json         the per-user grant (access + refresh
                                         token) this module writes after a
                                         successful sign-in, 0600 where the
                                         OS supports it. This one IS
                                         sensitive: never logged, never
                                         returned by an API response.

In development only, a `backend/secrets/gmail_credentials.json` is also
accepted, so the file can sit next to the code without touching `app-data`.

Connection state is never stored as a flag in SQLite: like the desktop app's
Calendar permission, it is read live from what is actually on disk (and,
for status, from Google itself when a refresh is due), so the reported
status can never drift from reality. Message content is never stored
anywhere by this module either -- not in SQLite, not in personal memory,
not on disk: each read is fetched fresh from Gmail and handed to the caller.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from app.config import BACKEND_DIR, FROZEN, app_data_dir

log = logging.getLogger("app.gmail")

# Read-only, and nothing more: this is deliberately the only scope Dully
# ever asks Google for. Widening it means a returning user is re-prompted,
# which is the intended friction against silently broadening access later.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_FILE_NAME = "gmail_credentials.json"
TOKEN_FILE_NAME = "gmail_token.json"

# How long a sign-in may sit open in the browser before this gives up and
# frees the worker thread handling it. Generous, but not indefinite.
OAUTH_TIMEOUT_SECONDS = 180


class GmailError(Exception):
    """Base class; `message` is safe to show in the UI."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class CredentialsFileMissing(GmailError):
    """No client JSON at either expected location."""


class CredentialsFileInvalid(GmailError):
    """A file is there, but not a usable OAuth Desktop client JSON."""


class OAuthCancelled(GmailError):
    """The user closed the tab, denied access, or it timed out."""


class GmailNetworkError(GmailError):
    """Google could not be reached during the OAuth exchange or a refresh."""


class NotConnected(GmailError):
    """Asked for a client, but there is no usable token."""


@dataclass(frozen=True)
class GmailStatus:
    connected: bool
    """Set only when `connected` is False and there is something more useful
    to say than that -- e.g. a network hiccup while checking. Safe to show."""
    detail: str | None = None


def _credentials_path() -> Path | None:
    """Where the user's downloaded OAuth client file actually is, or None."""
    primary = app_data_dir() / CREDENTIALS_FILE_NAME
    if primary.is_file():
        return primary
    if not FROZEN:
        dev = BACKEND_DIR / "secrets" / CREDENTIALS_FILE_NAME
        if dev.is_file():
            return dev
    return None


def credentials_file_present() -> bool:
    return _credentials_path() is not None


def _token_path() -> Path:
    return app_data_dir() / TOKEN_FILE_NAME


def _load_token() -> Credentials | None:
    path = _token_path()
    if not path.is_file():
        return None
    try:
        info = json.loads(path.read_text())
    except (OSError, ValueError):
        log.warning("gmail: token file unreadable; treating as disconnected")
        return None
    try:
        return Credentials.from_authorized_user_info(info, SCOPES)
    except ValueError:
        log.warning("gmail: token file malformed; treating as disconnected")
        return None


def _save_token(creds: Credentials) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json())
    try:
        path.chmod(0o600)
    except OSError:
        pass  # best-effort; not every filesystem supports POSIX permissions


def _clear_token() -> None:
    try:
        _token_path().unlink()
    except FileNotFoundError:
        pass


def _fresh_credentials() -> tuple[Credentials | None, str | None]:
    """The stored credentials, refreshed if expired and refreshable.

    Returns (credentials, detail). credentials is None when there is
    nothing usable to answer with -- never connected, revoked (the token is
    also cleared in that case, since it can never succeed again), or the
    file was unreadable. `detail` carries a reason only when it is worth
    telling the user about (currently: a refresh that failed to *reach*
    Google, which is not the same as being revoked and must not clear the
    token over what may be a transient problem).
    """
    creds = _load_token()
    if creds is None:
        return None, None
    if creds.valid:
        return creds, None
    if not (creds.expired and creds.refresh_token):
        return None, None
    try:
        creds.refresh(GoogleAuthRequest())
    except RefreshError:
        log.info("gmail: refresh failed (revoked or expired); disconnecting")
        _clear_token()
        return None, None
    except Exception:
        log.warning("gmail: token refresh failed (network?)", exc_info=True)
        return None, "Could not reach Google to refresh the connection. Will retry."
    _save_token(creds)
    return creds, None


def status() -> GmailStatus:
    creds, detail = _fresh_credentials()
    return GmailStatus(connected=creds is not None, detail=detail)


def connect() -> None:
    """Run the OAuth flow: open the browser, let the user pick an account
    and approve read-only Gmail access, and store the resulting token.

    Blocks the calling thread until the browser flow finishes, is denied,
    or times out -- call this from a sync route (FastAPI runs those in its
    worker thread pool) or via `asyncio.to_thread`, never from an `async
    def` route directly.
    """
    path = _credentials_path()
    if path is None:
        raise CredentialsFileMissing(
            "No Google OAuth credentials file found. Download one from Google Cloud Console "
            "(APIs & Services > Credentials > Create Credentials > OAuth client ID > "
            f"Desktop app) and save it as '{CREDENTIALS_FILE_NAME}' in Dully's application-"
            "data folder."
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    except (OSError, ValueError) as err:
        raise CredentialsFileInvalid(
            "That credentials file could not be read. Make sure it is the OAuth Desktop "
            "client JSON downloaded from Google Cloud Console, unedited."
        ) from err

    try:
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            timeout_seconds=OAUTH_TIMEOUT_SECONDS,
            authorization_prompt_message="",
            success_message="Signed in. You can close this tab and return to Dully.",
        )
    except OAuth2Error as err:
        # Covers a denied prompt and a rejected exchange (e.g. the client
        # JSON's own id/secret no longer valid at Google's end).
        raise OAuthCancelled("Google sign-in was cancelled or access was denied.") from err
    except requests.exceptions.RequestException as err:
        # The token exchange itself goes over `requests` (oauthlib's doing,
        # not this module's), so this -- not httpx -- is what a network
        # failure during that step actually raises.
        raise GmailNetworkError("Could not reach Google to complete sign-in. Check your connection.") from err
    except Exception as err:
        # Anything else that isn't a clean credential object -- including
        # google_auth_oauthlib's own WSGITimeoutError when the browser tab
        # is left untouched -- is the same "didn't complete" outcome to the
        # user, and never leaves a half-written token behind.
        raise OAuthCancelled("Google sign-in did not complete. Please try again.") from err

    _save_token(creds)
    log.info("gmail: connected")


def disconnect() -> None:
    """Stop using the stored token, and ask Google to revoke it -- best
    effort: the local token is always removed, even if the revoke call
    itself fails (offline, or Google already considers it invalid)."""
    creds = _load_token()
    _clear_token()
    if creds is None or not creds.token:
        return
    try:
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": creds.token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
    except httpx.HTTPError:
        log.info("gmail: could not reach Google to revoke the token; removed it locally anyway")
    log.info("gmail: disconnected")


def get_client() -> Resource:
    """A ready `googleapiclient` Gmail client (`users().messages()...`),
    used by `gmail_list_recent`, `gmail_search` and `gmail_get_message`
    below."""
    creds, _ = _fresh_credentials()
    if creds is None:
        raise NotConnected("Gmail is not connected.")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# --- reading -------------------------------------------------------------------
# Everything below is read-only: it fetches from Gmail and returns plain
# dataclasses. None of it stores anything -- not in SQLite, not in personal
# memory -- and none of it is reachable from anywhere but the Gmail tools
# (`services/tools/gmail.py`), which render it as inert data for the model
# to describe, never as instructions to act on.


class GmailNotFound(GmailError):
    """The message id does not exist (deleted, or never did)."""


class InvalidQuery(GmailError):
    """An empty search, or one Gmail's own syntax rejected."""


# How many messages a list/search may return. Kept modest on purpose: Gmail's
# API returns only ids from a list call, so each result costs one further
# `messages.get` round trip (see `_list_messages`) -- the cap bounds that
# fan-out, not just prompt size.
LIST_DEFAULT = 10
LIST_MAX = 25

# A long plain-text body is trimmed before it reaches the model, the same
# spirit as every other MAX_CHARS-style cap elsewhere in this codebase.
BODY_MAX_CHARS = 6000


@dataclass(frozen=True)
class EmailSummary:
    """One message as shown in a list or search result: enough to browse
    by, no body. `gmail_get_message` is what fetches the rest."""

    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    labels: list[str]
    unread: bool


@dataclass(frozen=True)
class EmailMessage(EmailSummary):
    """One message in full, as returned by `gmail_get_message`."""

    recipients: list[str]
    """The plain-text body, or None if the message has no text/plain part
    (an HTML-only email -- `snippet` is still real preview text in that
    case, just not the full body)."""
    body: str | None
    body_truncated: bool


def _header(headers: list[dict], name: str) -> str:
    for entry in headers or []:
        if (entry.get("name") or "").lower() == name.lower():
            return entry.get("value") or ""
    return ""


def _decode_base64url(data: str | None) -> str:
    """Gmail's URL-safe, unpadded base64 body encoding -> text. Never
    raises: a malformed or unusual encoding becomes an empty string rather
    than taking a whole read down over one odd message."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _find_plain_text(part: dict) -> str | None:
    """Depth-first search through a MIME part tree (Gmail's `payload`, which
    is itself a part) for the first text/plain part's decoded content.

    None means the message genuinely has no plain-text part -- common for
    HTML-only marketing mail -- which is reported as such rather than
    guessed at by stripping HTML tags, so nothing in the "body" is ever
    something this app inferred rather than something Gmail actually sent.
    """
    if part.get("mimeType") == "text/plain":
        data = (part.get("body") or {}).get("data")
        return _decode_base64url(data) if data else None
    for sub in part.get("parts") or []:
        found = _find_plain_text(sub)
        if found is not None:
            return found
    return None


def _summary_from_metadata(msg: dict) -> EmailSummary:
    headers = (msg.get("payload") or {}).get("headers") or []
    label_ids = msg.get("labelIds") or []
    return EmailSummary(
        id=msg["id"],
        thread_id=msg.get("threadId") or msg["id"],
        sender=_header(headers, "From"),
        subject=_header(headers, "Subject") or "(no subject)",
        date=_header(headers, "Date"),
        snippet=msg.get("snippet", ""),
        labels=label_ids,
        unread="UNREAD" in label_ids,
    )


def _wrap_http_error(err: HttpError, *, context: str = "search") -> GmailError:
    """`context` is "search" (a `messages.list` call, where 400 means a
    malformed query) or "get" (a `messages.get` call, where -- confirmed
    against the live API -- Gmail returns 400 rather than 404 for both a
    malformed id and a well-formed one that simply does not exist, so 400
    is treated as "not found" there instead of "bad search")."""
    status = err.status_code or 0
    if status == 404 or (status == 400 and context == "get"):
        return GmailNotFound("That email could not be found. It may have been deleted or moved.")
    if status in (401, 403):
        # Rare: get_client() already checks and refreshes first, but access
        # can still be lost in the moment between that check and this call
        # (revoked from the Google Account page, say). Treat it the same as
        # a failed refresh: clear the stale token so status is accurate.
        _clear_token()
        return NotConnected("Gmail access was lost. Please reconnect in Settings.")
    if status == 429:
        return GmailNetworkError("Gmail asked us to slow down. Please try again in a moment.")
    if status == 400:
        return InvalidQuery("That search could not be understood. Try simpler Gmail search terms.")
    return GmailNetworkError(f"Gmail returned an error (HTTP {status}). Please try again.")


def _list_messages(*, query: str | None, max_results: int, label_ids: list[str] | None = None) -> list[EmailSummary]:
    """Ids matching `query` (or the most recent, if `query` is None), then
    one lightweight metadata fetch per id -- headers and the snippet, never
    the body -- since Gmail's list endpoint returns bare ids only."""
    limit = max(1, min(max_results, LIST_MAX))
    client = get_client()
    try:
        response = (
            client.users()
            .messages()
            .list(userId="me", q=query, labelIds=label_ids, maxResults=limit)
            .execute()
        )
    except RefreshError as err:
        raise NotConnected("Gmail is not connected.") from err
    except HttpError as err:
        raise _wrap_http_error(err, context="search") from err
    except (OSError, TimeoutError) as err:
        raise GmailNetworkError("Could not reach Gmail. Check your connection.") from err

    ids = [m["id"] for m in response.get("messages") or []]
    summaries: list[EmailSummary] = []
    for message_id in ids:
        try:
            raw = (
                client.users()
                .messages()
                .get(userId="me", id=message_id, format="metadata", metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
        except HttpError:
            log.warning("gmail: could not fetch metadata for one message; skipped it", exc_info=True)
            continue
        summaries.append(_summary_from_metadata(raw))
    return summaries


def gmail_list_recent(max_results: int = LIST_DEFAULT) -> list[EmailSummary]:
    """The most recent inbox messages, newest first, with no search filter."""
    return _list_messages(query=None, max_results=max_results, label_ids=["INBOX"])


def gmail_search(query: str, limit: int = LIST_DEFAULT) -> list[EmailSummary]:
    """Messages matching Gmail's own search syntax (from:, subject:,
    after:/before:, is:unread, and so on) or plain free-text words -- the
    same scope Gmail's own search bar uses, not limited to the inbox."""
    query = query.strip()
    if not query:
        raise InvalidQuery("A search needs at least one word or search operator.")
    return _list_messages(query=query, max_results=limit)


def gmail_get_message(message_id: str) -> EmailMessage:
    """One message in full, including its plain-text body when it has one."""
    message_id = message_id.strip()
    if not message_id:
        raise InvalidQuery("A message id is required.")
    client = get_client()
    try:
        msg = client.users().messages().get(userId="me", id=message_id, format="full").execute()
    except RefreshError as err:
        raise NotConnected("Gmail is not connected.") from err
    except HttpError as err:
        raise _wrap_http_error(err, context="get") from err
    except (OSError, TimeoutError) as err:
        raise GmailNetworkError("Could not reach Gmail. Check your connection.") from err

    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    label_ids = msg.get("labelIds") or []

    body = _find_plain_text(payload)
    truncated = False
    if body is not None and len(body) > BODY_MAX_CHARS:
        body = body[:BODY_MAX_CHARS]
        truncated = True

    to_addrs = [a.strip() for a in _header(headers, "To").split(",") if a.strip()]
    cc_addrs = [a.strip() for a in _header(headers, "Cc").split(",") if a.strip()]

    return EmailMessage(
        id=msg["id"],
        thread_id=msg.get("threadId") or msg["id"],
        sender=_header(headers, "From"),
        subject=_header(headers, "Subject") or "(no subject)",
        date=_header(headers, "Date"),
        snippet=msg.get("snippet", ""),
        labels=label_ids,
        unread="UNREAD" in label_ids,
        recipients=to_addrs + cc_addrs,
        body=body,
        body_truncated=truncated,
    )
