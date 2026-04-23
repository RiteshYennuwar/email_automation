"""Shared test fixtures for the Enron Email Pipeline test suite."""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.database import create_schema, get_connection
from src.models import ParsedEmail

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a temporary SQLite database with schema applied.

    Yields:
        Configured sqlite3.Connection to an in-memory-like temp DB.
    """
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_email() -> ParsedEmail:
    """Create a minimal valid ParsedEmail for testing.

    Returns:
        ParsedEmail with all mandatory fields populated.
    """
    return ParsedEmail(
        message_id="<TEST001@example.com>",
        date=datetime(2001, 5, 14, 16, 0, 0, tzinfo=timezone.utc),
        from_address="sender@enron.com",
        to_addresses=["recipient@enron.com"],
        subject="Test Email",
        body="This is the body of a test email.",
        source_file="lay-k/inbox/1",
    )


@pytest.fixture
def sample_email_full() -> ParsedEmail:
    """Create a ParsedEmail with all optional fields populated.

    Returns:
        ParsedEmail with every field set.
    """
    return ParsedEmail(
        message_id="<FULL001@example.com>",
        date=datetime(2001, 6, 20, 10, 30, 0, tzinfo=timezone.utc),
        from_address="klay@enron.com",
        to_addresses=["jskilling@enron.com", "vkaminski@enron.com"],
        subject="Re: Quarterly Report",
        body="Please review the attached report.",
        source_file="lay-k/sent/42",
        cc_addresses=["jdasovich@enron.com"],
        bcc_addresses=["skean@enron.com"],
        x_from="Lay, Kenneth",
        x_to="Skilling, Jeff",
        x_cc="Dasovich, Jeff",
        x_bcc="Kean, Steven",
        x_folder="\\Lay, Kenneth\\Sent",
        x_origin="Lay-K",
        content_type="text/plain; charset=us-ascii",
        has_attachment=True,
        forwarded_content="-----Original Message-----\nFrom: someone@enron.com",
        quoted_content="> Previous reply text",
        headings="QUARTERLY REPORT",
    )


@pytest.fixture
def tmp_maildir(tmp_path: Path) -> Path:
    """Create a temporary maildir structure with sample email files.

    Returns:
        Path to the temporary maildir root.
    """
    maildir = tmp_path / "maildir"

    # Create nested structure mimicking Enron maildir
    folders = [
        "lay-k/inbox",
        "lay-k/sent",
        "lay-k/deleted_items",
        "skilling-j/inbox",
        "skilling-j/sent",
    ]

    simple_email = (
        "Message-ID: <TEST{n}@example.com>\n"
        "Date: Mon, 14 May 2001 09:00:00 -0700 (PDT)\n"
        "From: sender@enron.com\n"
        "To: recipient@enron.com\n"
        "Subject: Test Email {n}\n"
        "\n"
        "Body of email {n}.\n"
    )

    file_count = 1
    for folder in folders:
        folder_path = maildir / folder
        folder_path.mkdir(parents=True)
        for _ in range(1):
            email_path = folder_path / str(file_count)
            email_path.write_text(
                simple_email.format(n=file_count), encoding="utf-8"
            )
            file_count += 1

    return maildir
