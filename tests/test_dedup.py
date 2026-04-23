"""Tests for src/dedup.py — FR-4: Duplicate Detection."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.database import get_email_by_id, insert_email
from src.dedup import REPORT_PATH, detect_duplicates, normalize_subject
from src.models import ParsedEmail


def _make_email(
    msg_id: str,
    date: datetime,
    from_addr: str = "sender@enron.com",
    subject: str = "Test Email",
    body: str = "This is the body of a test email.",
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


class TestSubjectNormalization:
    """Tests for subject prefix stripping."""

    def test_subject_normalization(self):
        """Re: Re: Fwd: FW: Hello -> hello."""
        assert normalize_subject("Re: Re: Fwd: FW: Hello") == "hello"

    def test_subject_normalization_no_prefix(self):
        """Hello World -> hello world."""
        assert normalize_subject("Hello World") == "hello world"

    def test_subject_normalization_case_insensitive(self):
        """re: RE: fwd: Meeting -> meeting."""
        assert normalize_subject("re: RE: fwd: Meeting") == "meeting"

    def test_subject_normalization_with_whitespace(self):
        """Strips extra whitespace."""
        assert normalize_subject("  Re:  Test  ") == "test"


class TestDuplicateDetection:
    """Tests for duplicate detection logic."""

    def test_exact_duplicate_detected(self, tmp_db):
        """Two emails with identical body are flagged, score = 100."""
        e1 = _make_email(
            "<ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<COPY@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        stats = detect_duplicates(tmp_db)
        assert stats["groups"] == 1
        assert stats["flagged"] == 1

        row = get_email_by_id(tmp_db, "<COPY@test>")
        assert row["is_duplicate"] == 1
        assert row["duplicate_of"] == "<ORIG@test>"

    def test_near_duplicate_detected(self, tmp_db):
        """~95% similar body is flagged."""
        e1 = _make_email(
            "<ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
            body="This is the body of a test email that discusses the quarterly results and budget.",
        )
        e2 = _make_email(
            "<NEAR@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
            body="This is the body of a test email that discusses the quarterly results and budget!",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        stats = detect_duplicates(tmp_db)
        assert stats["flagged"] >= 1

    def test_below_threshold_not_flagged(self, tmp_db):
        """~30% similar body is NOT flagged."""
        e1 = _make_email(
            "<ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<DIFF@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
            body="This is a completely rewritten email about a different topic entirely. No similarity to the original.",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        stats = detect_duplicates(tmp_db)
        assert stats["flagged"] == 0

        row = get_email_by_id(tmp_db, "<DIFF@test>")
        assert row["is_duplicate"] == 0

    def test_different_sender_not_duplicate(self, tmp_db):
        """Same subject+body, different from_address: NOT grouped."""
        e1 = _make_email(
            "<ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
            from_addr="sender1@enron.com",
        )
        e2 = _make_email(
            "<OTHER@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            from_addr="sender2@enron.com",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        stats = detect_duplicates(tmp_db)
        assert stats["flagged"] == 0

    def test_earliest_is_original(self, tmp_db):
        """Earliest date gets is_duplicate = False."""
        e1 = _make_email(
            "<EARLY@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<MID@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
        )
        e3 = _make_email(
            "<LATE@test>",
            datetime(2001, 5, 16, 16, 0, tzinfo=timezone.utc),
            subject="Fwd: Test Email",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)
        insert_email(tmp_db, e3)

        detect_duplicates(tmp_db)

        orig = get_email_by_id(tmp_db, "<EARLY@test>")
        assert orig["is_duplicate"] == 0

    def test_latest_is_duplicate(self, tmp_db):
        """Latest by UTC date gets is_duplicate = True."""
        e1 = _make_email(
            "<EARLY@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<LATE@test>",
            datetime(2001, 5, 16, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        detect_duplicates(tmp_db)
        row = get_email_by_id(tmp_db, "<LATE@test>")
        assert row["is_duplicate"] == 1
        assert row["duplicate_of"] == "<EARLY@test>"

    def test_identical_dates_tiebreaker(self, tmp_db):
        """Same timestamp uses lexicographic message_id as tiebreaker."""
        same_date = datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc)
        e1 = _make_email("<AAA@test>", same_date)
        e2 = _make_email("<BBB@test>", same_date, subject="Re: Test Email")
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        detect_duplicates(tmp_db)

        # AAA < BBB lexicographically, so AAA is original
        orig = get_email_by_id(tmp_db, "<AAA@test>")
        dup = get_email_by_id(tmp_db, "<BBB@test>")
        assert orig["is_duplicate"] == 0
        assert dup["is_duplicate"] == 1
        assert dup["duplicate_of"] == "<AAA@test>"

    def test_group_of_three(self, tmp_db):
        """3 duplicates: 1 original, 2 flagged, all duplicate_of points to original."""
        e1 = _make_email(
            "<FIRST@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<SECOND@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
        )
        e3 = _make_email(
            "<THIRD@test>",
            datetime(2001, 5, 16, 16, 0, tzinfo=timezone.utc),
            subject="Fwd: Test Email",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)
        insert_email(tmp_db, e3)

        stats = detect_duplicates(tmp_db)
        assert stats["groups"] == 1
        assert stats["flagged"] == 2

        for mid in ["<SECOND@test>", "<THIRD@test>"]:
            row = get_email_by_id(tmp_db, mid)
            assert row["is_duplicate"] == 1
            assert row["duplicate_of"] == "<FIRST@test>"

    def test_csv_report_generated(self, tmp_db):
        """duplicates_report.csv has correct columns and row count."""
        e1 = _make_email(
            "<ORIG@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
        )
        e2 = _make_email(
            "<COPY@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        detect_duplicates(tmp_db)

        assert REPORT_PATH.exists()
        with REPORT_PATH.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) >= 1
            assert "duplicate_message_id" in reader.fieldnames
            assert "original_message_id" in reader.fieldnames
            assert "similarity_score" in reader.fieldnames

    def test_empty_body_handling(self, tmp_db):
        """Two emails with empty bodies + same sender/subject match at 100%."""
        e1 = _make_email(
            "<EMPTY1@test>",
            datetime(2001, 5, 14, 16, 0, tzinfo=timezone.utc),
            body="",
        )
        e2 = _make_email(
            "<EMPTY2@test>",
            datetime(2001, 5, 15, 16, 0, tzinfo=timezone.utc),
            subject="Re: Test Email",
            body="",
        )
        insert_email(tmp_db, e1)
        insert_email(tmp_db, e2)

        stats = detect_duplicates(tmp_db)
        assert stats["flagged"] == 1
