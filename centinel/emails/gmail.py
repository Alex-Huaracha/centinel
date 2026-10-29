"""Client for the Apps Script web app in apps_script/, Centinel's only way into Gmail."""

import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any, Protocol

import httpx

from centinel.config import get_settings

# httpx logs every request URL at INFO, and the URL carries the secret.
logging.getLogger("httpx").setLevel(logging.WARNING)


class GmailError(Exception):
    """Gmail could not be reached; worded for the agent like UserError."""


@dataclass(frozen=True)
class FoundEmail:
    gmail_id: str
    sender: str
    received_at: datetime


class Gmail(Protocol):
    """What the email service needs from Gmail, so tests can pass a fake."""

    def search(self, senders: list[str], days: int) -> list[FoundEmail]: ...

    def get_raw(self, gmail_id: str) -> bytes | None: ...


class GmailScript:
    def __init__(self, url: str, secret: str, client: httpx.Client | None = None):
        self._url = url
        self._secret = secret
        # Apps Script answers with a redirect to googleusercontent.com.
        self._client = client or httpx.Client(follow_redirects=True, timeout=60)

    @classmethod
    def from_settings(cls) -> GmailScript | None:
        """The configured script, or None when email intake is not set up."""
        settings = get_settings()
        if settings.gmail_script_url is None or settings.gmail_script_secret is None:
            return None
        return cls(
            str(settings.gmail_script_url),
            settings.gmail_script_secret.get_secret_value(),
        )

    def _request(self, **params: str) -> dict[str, Any]:
        try:
            response = self._client.get(
                self._url, params={"secret": self._secret, **params}
            )
            response.raise_for_status()
            body = response.json()
        # httpx messages include the URL, which carries the secret, so they are
        # never passed on (`from None` keeps them out of tracebacks too).
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise GmailError(f"The Gmail script answered HTTP {status}.") from None
        except httpx.HTTPError as error:
            raise GmailError(
                f"The Gmail script could not be reached ({type(error).__name__})."
            ) from None
        except ValueError:
            # A crash in the script comes back as an HTML page, not JSON.
            raise GmailError("The Gmail script did not answer with JSON.") from None
        return body

    def _call(self, **params: str) -> dict[str, Any]:
        body = self._request(**params)
        if "error" in body:
            raise GmailError(f"The Gmail script answered: {body['error']}")
        return body

    def search(self, senders: list[str], days: int) -> list[FoundEmail]:
        body = self._call(action="search", senders=",".join(senders), days=str(days))
        return [
            FoundEmail(
                gmail_id=email["id"],
                # "Yape <notificaciones@yape.example>" -> "notificaciones@yape.example"
                sender=parseaddr(email["from"])[1].lower(),
                received_at=datetime.fromtimestamp(email["received_at_ms"] / 1000, UTC),
            )
            for email in body["emails"]
        ]

    def get_raw(self, gmail_id: str) -> bytes | None:
        """The email as it arrived, or None if it was deleted from Gmail."""
        body = self._request(action="get", id=gmail_id)
        if body.get("error") == "not found":
            return None
        if "error" in body:
            raise GmailError(f"The Gmail script answered: {body['error']}")
        return base64.b64decode(body["raw"])
