import base64
import logging
from datetime import UTC, datetime

import httpx
import pytest

from centinel.config import get_settings
from centinel.emails.gmail import FoundEmail, GmailError, GmailScript

URL = "https://script.google.example/macros/s/abc/exec"
SECRET = "test-secret"
# Apps Script answers from a second host after a redirect.
CONTENT_URL = "https://script.googleusercontent.example/echo"


def _script(answer: dict | str, status: int = 200) -> tuple[GmailScript, list]:
    """A script whose answer arrives after the same redirect as the real one."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(URL):
            requests.append(request)
            return httpx.Response(302, headers={"Location": CONTENT_URL})
        if isinstance(answer, str):
            return httpx.Response(status, text=answer)
        return httpx.Response(status, json=answer)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return GmailScript(URL, SECRET, client), requests


def test_search_sends_secret_and_parses_emails():
    script, requests = _script(
        {
            "emails": [
                {
                    "id": "g-1",
                    "from": "Yape <Notificaciones@Yape.example>",
                    "received_at_ms": 1790000000000,
                }
            ]
        }
    )

    found = script.search(["notificaciones@yape.example", "orders@shop.example"], 30)

    assert found == [
        FoundEmail(
            gmail_id="g-1",
            sender="notificaciones@yape.example",
            received_at=datetime.fromtimestamp(1790000000, UTC),
        )
    ]
    assert dict(requests[0].url.params) == {
        "secret": SECRET,
        "action": "search",
        "senders": "notificaciones@yape.example,orders@shop.example",
        "days": "30",
    }


def test_get_raw_decodes_the_email():
    raw = b"From: a@yape.example\r\nSubject: Yapeo\r\n\r\nS/ 20.00"
    script, _ = _script({"id": "g-1", "raw": base64.b64encode(raw).decode()})

    assert script.get_raw("g-1") == raw


def test_get_raw_of_deleted_email_is_none():
    script, _ = _script({"error": "not found"})

    assert script.get_raw("g-1") is None


def test_script_error_is_raised():
    script, _ = _script({"error": "unauthorized"})

    with pytest.raises(GmailError, match="unauthorized"):
        script.search(["a@yape.example"], 30)


@pytest.mark.parametrize(
    ("answer", "status", "message"),
    [
        ("<html>Script error</html>", 200, "did not answer with JSON"),
        ({"emails": []}, 500, "HTTP 500"),
    ],
    ids=["html-crash-page", "http-error"],
)
def test_bad_answers_never_leak_the_secret(answer, status, message):
    script, _ = _script(answer, status)

    with pytest.raises(GmailError, match=message) as error:
        script.search(["a@yape.example"], 30)

    assert SECRET not in str(error.value)
    assert error.value.__cause__ is None


def test_unreachable_script_never_leaks_the_secret():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    script = GmailScript(URL, SECRET, client)

    with pytest.raises(GmailError, match="ConnectError") as error:
        script.search(["a@yape.example"], 30)

    assert SECRET not in str(error.value)


def test_from_settings_is_none_when_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "gmail_script_url", None)

    assert GmailScript.from_settings() is None


def test_requests_never_log_the_secret(caplog: pytest.LogCaptureFixture):
    script, _ = _script({"emails": []})

    with caplog.at_level(logging.DEBUG):
        script.search(["a@yape.example"], 30)

    assert SECRET not in caplog.text
