"""Inputs of the email intake service, written for the model like the expenses ones."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SenderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Address the store or bank sends its receipts or alerts from.",
    )


class AddSenderOut(BaseModel):
    email: str
    emails_found: int | None = Field(
        description=(
            "Emails from this sender in the recent past. 0 may mean a typo in the "
            "address. null when Gmail is not set up."
        )
    )


class ListPendingEmailsInput(BaseModel):
    limit: int = Field(
        default=10, ge=1, le=20, description="How many emails to read, oldest first."
    )


class IgnoreEmailInput(BaseModel):
    gmail_id: str = Field(min_length=1, max_length=100)


class PendingEmailOut(BaseModel):
    gmail_id: str = Field(description="Pass it as source_email_id to save_expense.")
    sender: str
    received_at: datetime
    subject: str
    text: str


class PendingEmailsOut(BaseModel):
    emails: list[PendingEmailOut]
    remaining: int = Field(description="Pending emails not included in this answer.")
