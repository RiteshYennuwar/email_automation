"""Tests for src/database.py — FR-3: Database Storage."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.database import (
    create_schema,
    flag_duplicate,
    get_connection,
    get_duplicate_count,
    get_email_by_id,
    get_email_count,
    insert_email,
    update_notification_sent,
)
from src.models import ParsedEmail


class TestCreateSchema:
    """Tests for schema creation."""

    def test_create_schema(self, tmp_db):
        """Tables emails and email_recipients exist with correct columns."""
        # Check emails table columns
        cursor = tmp_db.execute("PRAGMA table_info(emails)")
        columns = {row["name"] for row in cursor.fetchall()}
        expected = {
            "message_id", "date", "from_address", "subject", "body", "source_file",
            "x_from", "x_to", "x_cc", "x_bcc", "x_folder", "x_origin",
            "content_type", "has_attachment", "forwarded_content", "quoted_content",
            "headings", "is_duplicate", "duplicate_of", "notification_sent",
            "notification_date",
        }
        assert expected.issubset(columns)

        # Check email_recipients table columns
        cursor = tmp_db.execute("PRAGMA table_info(email_recipients)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert {"id", "email_message_id", "address", "recipient_type"}.issubset(columns)

    def test_dedup_columns_exist(self, tmp_db):
        """is_duplicate, duplicate_of, notification_sent, notification_date present."""
        cursor = tmp_db.execute("PRAGMA table_info(emails)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "is_duplicate" in columns
        assert "duplicate_of" in columns
        assert "notification_sent" in columns
        assert "notification_date" in columns

    def test_indexes_exist(self, tmp_db):
        """Indexes on date, from_address, subject, address exist."""
        cursor = tmp_db.execute("PRAGMA index_list(emails)")
        email_indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_emails_date" in email_indexes
        assert "idx_emails_from_address" in email_indexes
        assert "idx_emails_subject" in email_indexes

        cursor = tmp_db.execute("PRAGMA index_list(email_recipients)")
        recip_indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_recipients_address" in recip_indexes


class TestInsertEmail:
    """Tests for email insertion."""

    def test_insert_email(self, tmp_db, sample_email):
        """Insert succeeds, all fields retrievable."""
        result = insert_email(tmp_db, sample_email)
        assert result is True

        row = tmp_db.execute(
            "SELECT * FROM emails WHERE message_id = ?",
            (sample_email.message_id,),
        ).fetchone()
        assert row is not None
        assert row["message_id"] == sample_email.message_id
        assert row["from_address"] == "sender@enron.com"
        assert row["subject"] == "Test Email"
        assert row["body"] == "This is the body of a test email."
        assert row["source_file"] == "lay-k/inbox/1"

    def test_insert_recipients(self, tmp_db, sample_email_full):
        """to/cc/bcc stored in email_recipients with correct types."""
        insert_email(tmp_db, sample_email_full)

        rows = tmp_db.execute(
            "SELECT address, recipient_type FROM email_recipients WHERE email_message_id = ?",
            (sample_email_full.message_id,),
        ).fetchall()

        recips = {(r["address"], r["recipient_type"]) for r in rows}
        assert ("jskilling@enron.com", "to") in recips
        assert ("vkaminski@enron.com", "to") in recips
        assert ("jdasovich@enron.com", "cc") in recips
        assert ("skean@enron.com", "bcc") in recips

    def test_unique_message_id(self, tmp_db, sample_email):
        """Second insert with same message_id is skipped (no error)."""
        result1 = insert_email(tmp_db, sample_email)
        result2 = insert_email(tmp_db, sample_email)
        assert result1 is True
        assert result2 is False
        assert get_email_count(tmp_db) == 1

    def test_foreign_key_integrity(self, tmp_db):
        """email_recipients.email_message_id references valid emails.message_id."""
        # Attempt to insert a recipient for a nonexistent email
        with pytest.raises(Exception):
            tmp_db.execute(
                "INSERT INTO email_recipients (email_message_id, address, recipient_type) "
                "VALUES (?, ?, ?)",
                ("<NONEXISTENT@example.com>", "test@test.com", "to"),
            )
            tmp_db.commit()


class TestQueryFunctions:
    """Tests for query helper functions."""

    def test_get_email_count(self, tmp_db, sample_email):
        """get_email_count returns correct count."""
        assert get_email_count(tmp_db) == 0
        insert_email(tmp_db, sample_email)
        assert get_email_count(tmp_db) == 1

    def test_get_duplicate_count(self, tmp_db, sample_email):
        """get_duplicate_count returns count of flagged duplicates."""
        insert_email(tmp_db, sample_email)
        assert get_duplicate_count(tmp_db) == 0

        # Create and insert a duplicate
        dup = ParsedEmail(
            message_id="<TEST002@example.com>",
            date=datetime(2001, 5, 15, 16, 0, 0, tzinfo=timezone.utc),
            from_address="sender@enron.com",
            to_addresses=["recipient@enron.com"],
            subject="Re: Test Email",
            body="This is the body of a test email.",
            source_file="lay-k/inbox/2",
        )
        insert_email(tmp_db, dup)
        flag_duplicate(tmp_db, dup.message_id, sample_email.message_id)
        tmp_db.commit()
        assert get_duplicate_count(tmp_db) == 1

    def test_get_email_by_id(self, tmp_db, sample_email):
        """get_email_by_id returns email or None."""
        assert get_email_by_id(tmp_db, sample_email.message_id) is None
        insert_email(tmp_db, sample_email)
        row = get_email_by_id(tmp_db, sample_email.message_id)
        assert row is not None
        assert row["message_id"] == sample_email.message_id

    def test_update_notification_sent(self, tmp_db, sample_email):
        """update_notification_sent sets notification fields."""
        insert_email(tmp_db, sample_email)
        update_notification_sent(
            tmp_db, sample_email.message_id, "2026-04-20T14:30:00Z"
        )
        tmp_db.commit()
        row = get_email_by_id(tmp_db, sample_email.message_id)
        assert row["notification_sent"] == 1
        assert row["notification_date"] == "2026-04-20T14:30:00Z"
