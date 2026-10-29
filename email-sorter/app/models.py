from pydantic import BaseModel, Field, field_validator

from .taxonomy import (
    CONTENT_CATEGORIES,
    DEFAULT_CONTENT,
    DEFAULT_REPLY,
    REPLY_NATURE,
)


class Email(BaseModel):
    id: str
    subject: str = ""
    sender: str = ""
    received: str = ""
    preview: str = ""
    body: str = ""
    text_source: str = "body"
    ocr_confidence: float | None = None
    ocr_notes: list[str] = Field(default_factory=list)


class Classification(BaseModel):
    """What the LLM must return for every email."""

    content_category: str = Field(description="Exactly one key from the content categories list.")
    reply_nature: str = Field(description="Exactly one key from the reply nature list.")
    deadline: str | None = Field(
        default=None,
        description="Deadline exactly as the email states it (date/time), or null if there is none.",
    )
    reason: str = Field(default="", description="One short sentence explaining the choice.")

    @staticmethod
    def _norm(value) -> str:
        return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")

    @field_validator("content_category", mode="before")
    @classmethod
    def _check_content(cls, v):
        v = cls._norm(v)
        return v if v in CONTENT_CATEGORIES else DEFAULT_CONTENT

    @field_validator("reply_nature", mode="before")
    @classmethod
    def _check_reply(cls, v):
        v = cls._norm(v)
        return v if v in REPLY_NATURE else DEFAULT_REPLY

    @field_validator("deadline", mode="before")
    @classmethod
    def _check_deadline(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return None if v.lower() in {"", "null", "none", "n/a", "no deadline"} else v
