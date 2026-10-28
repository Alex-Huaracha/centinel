"""Inputs of the email intake service, written for the model like the expenses ones."""

from pydantic import BaseModel, ConfigDict, Field


class SenderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Address the store or bank sends its receipts or alerts from.",
    )
