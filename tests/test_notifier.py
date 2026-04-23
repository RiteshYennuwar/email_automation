"""Tests for src/notifier.py — FR-5: Notification Emails."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.database import flag_duplicate, get_email_by_id, insert_email
from src.models import ParsedEmail
from src.notifier import OUTPUT_DIR, SEND_LOG_PATH, generate_notifications


def _make_email(
    msg_id: str,
    date: datetime,
    from_addr: str = "sender@enron.com",
    subject: str = "Test Email",
    body: str = "Test body content.",
) -> ParsedEmail:
    """Helper to create test emails."""
    return ParsedEmail(
        message_id=msg_id,
        date=date,
        from_address=from_addr,
        to_addresses=["recipient@enron.com"],
        subject=subject,
        body=body,
        source_file=f"test/{msg_id}",
    )


class TestNotifier:
    """Tests for notification generation."""

    def _setup_duplicate_pair(self, tmp_db):
        """Insert a pair of emails and flag one as duplicate."""
        e1 = _make_email(
            "<NOTIF_ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<NOTIF_DUP@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)
        flag_duplicate(tmp_db, "<NOTIF_DUP@test>", "<NOTIF_ORIG@test>")
        tmp_db.commit()

    def test_generate_eml_file(self, tmp_db):
        """eml file created with correct template fields."""
        self._setup_duplicate_pair(tmp_db)

        # Clean output dir first
        for f in OUTPUT_DIR.glob("*.eml"):
            f.unlink()

        stats = generate_notifications(tmp_db)
        assert stats["generated"] >= 1

        # Check that at least one .eml file exists
        eml_files = list(OUTPUT_DIR.glob("*.eml"))
        assert len(eml_files) >= 1

    def test_eml_template_fields(self, tmp_db):
        """Subject, References, message IDs, dates, similarity score all present."""
        self._setup_duplicate_pair(tmp_db)

        # Clean output dir first
        for f in OUTPUT_DIR.glob("*.eml"):
            f.unlink()

        generate_notifications(tmp_db)

        eml_files = list(OUTPUT_DIR.glob("*.eml"))
        assert len(eml_files) >= 1

        content = eml_files[0].read_text(encoding="utf-8")
        assert "[Duplicate Notice]" in content
        assert "NOTIF_DUP@test" in content
        assert "NOTIF_ORIG@test" in content
        assert "Similarity Score:" in content

    def test_eml_per_duplicate_group(self, tmp_db):
        """One .eml per group (for the latest duplicate)."""
        # Create two separate groups
        e1 = _make_email(
            "<GRP1_ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
            from_addr="alice@enron.com",
            subject="Meeting",
        )
        e2 = _make_email(
            "<GRP1_DUP@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            from_addr="alice@enron.com",
            subject="Re: Meeting",
        )
        e3 = _make_email(
            "<GRP2_ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
            from_addr="bob@enron.com",
            subject="Report",
        )
        e4 = _make_email(
            "<GRP2_DUP@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            from_addr="bob@enron.com",
            subject="Re: Report",
        )

        for e in [e1, e2, e3, e4]:
            insert_email(tmp_db, e)

        flag_duplicate(tmp_db, "<GRP1_DUP@test>", "<GRP1_ORIG@test>")
        flag_duplicate(tmp_db, "<GRP2_DUP@test>", "<GRP2_ORIG@test>")
        tmp_db.commit()

        # Clean output dir first
        for f in OUTPUT_DIR.glob("*.eml"):
            f.unlink()

        stats = generate_notifications(tmp_db)
        assert stats["generated"] == 2

    def test_send_log_csv_format(self, tmp_db):
        """send_log.csv has correct columns."""
        self._setup_duplicate_pair(tmp_db)
        generate_notifications(tmp_db)

        assert SEND_LOG_PATH.exists()
        with SEND_LOG_PATH.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ["timestamp", "recipient", "subject", "status", "error"]

    def test_dry_run_no_send(self, tmp_db):
        """Without --send-live, no MCP calls made."""
        self._setup_duplicate_pair(tmp_db)

        with patch("src.notifier._send_via_mcp") as mock_send:
            stats = generate_notifications(tmp_db, send_live=False)
            mock_send.assert_not_called()
            assert stats["sent"] == 0

    def test_db_updated_after_send(self, tmp_db):
        """After send, notification_sent = True and notification_date set."""
        self._setup_duplicate_pair(tmp_db)

        with patch("src.notifier._send_via_mcp", return_value=True):
            stats = generate_notifications(
                tmp_db, send_live=True, notify_address="test@gmail.com"
            )
            assert stats["sent"] >= 1

        row = get_email_by_id(tmp_db, "<NOTIF_DUP@test>")
        assert row["notification_sent"] == 1
        assert row["notification_date"] is not None
