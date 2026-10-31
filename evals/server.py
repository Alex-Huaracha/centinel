"""Centinel's MCP server for one eval case: the eval database and the case's emails.

Run by the eval runner through Claude Code: python -m evals.server <case>
"""

import sys

from centinel.db.engine import create_session_factory
from centinel.emails.gmail import FoundEmail
from centinel.mcp_server.server import create_server
from evals.cases import CASES, Case
from evals.database import create_eval_engine


class CaseGmail:
    """Gmail holding only the case's emails."""

    def __init__(self, case: Case):
        self._emails = dict(zip(case.gmail_ids(), case.emails, strict=True))

    def search(self, senders: list[str], days: int) -> list[FoundEmail]:
        return [
            FoundEmail(
                gmail_id=gmail_id, sender=email.sender, received_at=email.sent_at
            )
            for gmail_id, email in self._emails.items()
            if email.sender in senders
        ]

    def get_raw(self, gmail_id: str) -> bytes | None:
        email = self._emails.get(gmail_id)
        return email.raw() if email else None


def main() -> None:
    case = next(case for case in CASES if case.name == sys.argv[1])
    server = create_server(
        create_session_factory(create_eval_engine()), CaseGmail(case)
    )
    server.run("stdio")


if __name__ == "__main__":
    main()
