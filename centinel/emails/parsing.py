"""Turn a raw email into the plain text the agent reads."""

import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser

# Enough for a receipt; long newsletters are cut so they don't flood the model.
MAX_TEXT_LENGTH = 5000

# Tags that start a new line when the HTML is rendered, so table cells
# like "Monto" and "S/ 20.00" stay on separate lines.
_BLOCK_TAGS = {"br", "p", "div", "tr", "td", "th", "li", "h1", "h2", "h3", "table"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return "".join(extractor.parts)


def _tidy(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return re.sub(r"\n{2,}", "\n", "\n".join(line for line in lines if line)).strip()


def email_to_text(raw: bytes) -> tuple[str, str]:
    """Subject and body of an email, as plain text."""
    message = message_from_bytes(raw, policy=policy.default)
    assert isinstance(message, EmailMessage)
    subject = str(message.get("Subject", ""))

    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        return subject, ""
    content = body.get_content()
    if body.get_content_subtype() == "html":
        content = _html_to_text(content)
    return subject, _tidy(content)[:MAX_TEXT_LENGTH]
