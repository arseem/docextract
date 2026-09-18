"""The model's only output channel: JSON validated against this schema
before anything else touches it. Unknown keys rejected, enum/length/type
constrained - the model has no tools and never sees doc_id (requirement 8)."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DOC_TYPES = ("invoice", "contract", "offer", "correspondence", "other")


class ExtractedFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: Literal["invoice", "contract", "offer", "correspondence", "other"]
    counterparty_name: str | None = Field(default=None, max_length=300)
    counterparty_tax_id: str | None = Field(default=None, max_length=40)
    issue_date: str | None = Field(default=None, max_length=40)
    due_date: str | None = Field(default=None, max_length=40)
    gross_amount: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=20)
    summary: str = Field(max_length=500)


class LLMOutputError(Exception):
    """Raised for any response that isn't valid JSON matching ExtractedFields."""


def parse_llm_output(raw_text: str) -> ExtractedFields:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"invalid JSON: {e}") from e
    try:
        return ExtractedFields.model_validate(data)
    except ValidationError as e:
        raise LLMOutputError(f"schema validation failed: {e}") from e
