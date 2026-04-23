"""Data models for the Enron Email Pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ParsedEmail:
    """Structured representation of a parsed email."""

    message_id: str
    date: datetime
    from_address: str
    to_addresses: list[str]
    subject: str
    body: str
    source_file: str
    cc_addresses: list[str] = field(default_factory=list)
    bcc_addresses: list[str] = field(default_factory=list)
    x_from: str | None = None
    x_to: str | None = None
    x_cc: str | None = None
    x_bcc: str | None = None
    x_folder: str | None = None
    x_origin: str | None = None
    content_type: str | None = None
    has_attachment: bool = False
    forwarded_content: str | None = None
    quoted_content: str | None = None
    headings: str | None = None


@dataclass
class DuplicateGroup:
    """A group of duplicate emails."""

    original_message_id: str
    original_date: datetime
    duplicate_message_ids: list[str]
    subject: str
    from_address: str
    similarity_scores: dict[str, float] = field(default_factory=dict)
