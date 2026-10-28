"""Inputs of the email intake service, written for the model like the expenses ones."""

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
