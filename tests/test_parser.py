"""Tests for src/parser.py — FR-2: Email Parsing."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.parser import parse_email

FIXTURES = Path(__file__).parent / "fixtures"
VALID = FIXTURES / "valid"
MALFORMED = FIXTURES / "malformed"


class TestValidParsing:
    """Tests for successful email parsing."""

    def test_parse_simple_email(self):
        """All 7 mandatory fields extracted correctly."""
        result = parse_email(VALID / "simple.txt")
        assert result is not None
        assert result.message_id == "<TEST001@example.com>"
        assert result.from_address == "sender@enron.com"
        assert result.to_addresses == ["recipient@enron.com"]
        assert result.subject == "Test Email"
        assert "This is the body of a test email." in result.body
        assert result.source_file == str(VALID / "simple.txt")

    def test_parse_all_optional_fields(self):
        """All optional fields populated when present."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert result.cc_addresses == ["jdasovich@enron.com"]
        assert result.bcc_addresses == ["skean@enron.com"]
        assert result.x_from == "Lay, Kenneth"
        assert result.x_to == "Skilling, Jeff"
        assert result.x_cc == "Dasovich, Jeff"
        assert result.x_bcc == "Kean, Steven"
        assert "Lay, Kenneth" in result.x_folder
        assert result.x_origin == "Lay-K"
        assert result.content_type is not None

    def test_date_utc_conversion_pst(self):
        """PST date converted to UTC (+8 hours)."""
        result = parse_email(VALID / "simple.txt")
        assert result is not None
        # Mon, 14 May 2001 09:00:00 -0700 (PDT) -> 16:00:00 UTC
        assert result.date.year == 2001
        assert result.date.month == 5
        assert result.date.day == 14
        assert result.date.hour == 16
        assert result.date.minute == 0
        assert result.date.tzinfo == timezone.utc

    def test_date_utc_conversion_est(self):
        """EST/CDT converted to UTC correctly."""
        result = parse_email(VALID / "multiline_to.txt")
        assert result is not None
        # Thu, 21 Jun 2001 08:00:00 -0500 -> 13:00:00 UTC
        assert result.date.hour == 13
        assert result.date.tzinfo == timezone.utc

    def test_from_address_strip_display_name(self):
        """Display name stripped from From address."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert result.from_address == "klay@enron.com"

    def test_to_addresses_comma_separated(self):
        """Comma-separated To addresses parsed into list."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert "jskilling@enron.com" in result.to_addresses
        assert "vkaminski@enron.com" in result.to_addresses

    def test_to_addresses_multiline(self):
        """Continuation lines parsed into single list."""
        result = parse_email(VALID / "multiline_to.txt")
        assert result is not None
        assert len(result.to_addresses) == 3
        assert "first@enron.com" in result.to_addresses
        assert "second@enron.com" in result.to_addresses
        assert "third@enron.com" in result.to_addresses

    def test_subject_preserved_prefixes(self):
        """Subject stored verbatim including Re:/Fwd: prefixes."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert result.subject == "Re: Quarterly Report"

    def test_body_extraction(self):
        """Body text correctly isolated."""
        result = parse_email(VALID / "simple.txt")
        assert result is not None
        assert "This is the body of a test email." in result.body

    def test_forwarded_content_separated(self):
        """Content after -----Original Message----- in forwarded_content."""
        result = parse_email(VALID / "forwarded.txt")
        assert result is not None
        assert result.forwarded_content is not None
        assert "-----Original Message-----" in result.forwarded_content
        assert "Please attend the meeting" in result.forwarded_content
        assert "Here is the forwarded message" in result.body

    def test_quoted_content_separated(self):
        """> lines extracted into quoted_content."""
        result = parse_email(VALID / "quoted.txt")
        assert result is not None
        assert result.quoted_content is not None
        assert "This is the original message." in result.quoted_content
        assert "I agree with your assessment." in result.body

    def test_headings_allcaps(self):
        """ALL CAPS lines detected as headings."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert result.headings is not None
        assert "QUARTERLY REPORT" in result.headings

    def test_headings_colon_suffix(self):
        """Lines ending with colon detected as headings."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert result.headings is not None
        assert "Action Items:" in result.headings

    def test_has_attachment_content_type(self):
        """multipart/mixed Content-Type detected as attachment."""
        result = parse_email(VALID / "html_body.txt")
        assert result is not None
        assert result.has_attachment is True

    def test_has_attachment_angle_brackets(self):
        """<<report.xls>> in body detected as attachment."""
        result = parse_email(VALID / "attachref.txt")
        assert result is not None
        assert result.has_attachment is True

    def test_has_attachment_none(self):
        """Plain email without attachment markers returns False."""
        result = parse_email(VALID / "simple.txt")
        assert result is not None
        assert result.has_attachment is False

    def test_x_headers_extracted(self):
        """X-From, X-To, X-cc, X-bcc, X-Folder, X-Origin extracted."""
        result = parse_email(VALID / "full_headers.txt")
        assert result is not None
        assert result.x_from == "Lay, Kenneth"
        assert result.x_to == "Skilling, Jeff"
        assert result.x_cc == "Dasovich, Jeff"
        assert result.x_bcc == "Kean, Steven"
        assert result.x_folder is not None
        assert result.x_origin == "Lay-K"

    def test_html_headings(self):
        """HTML heading tags extracted."""
        result = parse_email(VALID / "html_body.txt")
        assert result is not None
        assert result.headings is not None
        assert "Meeting Notes" in result.headings


class TestMalformedInput:
    """Tests for malformed email handling (must NOT crash)."""

    def test_missing_message_id(self):
        """Email without Message-ID returns None."""
        result = parse_email(MALFORMED / "no_message_id.txt")
        assert result is None

    def test_missing_date(self):
        """No Date header returns None."""
        result = parse_email(MALFORMED / "no_date.txt")
        assert result is None

    def test_unparseable_date(self):
        """Unparseable date returns None."""
        result = parse_email(MALFORMED / "bad_date.txt")
        assert result is None

    def test_missing_to(self):
        """No To header returns None."""
        result = parse_email(MALFORMED / "no_to.txt")
        assert result is None

    def test_missing_subject(self):
        """No Subject header returns None."""
        result = parse_email(MALFORMED / "no_subject.txt")
        assert result is None

    def test_encoding_latin1(self):
        """Latin-1 encoded file parses without crash."""
        result = parse_email(MALFORMED / "encoding_latin1.txt")
        # Should parse successfully since it has all required fields
        assert result is not None
        assert result.message_id == "<LATIN001@example.com>"

    def test_binary_file(self):
        """Random bytes returns None, no crash."""
        result = parse_email(MALFORMED / "binary_garbage.bin")
        assert result is None

    def test_empty_file(self):
        """0 bytes returns None."""
        result = parse_email(MALFORMED / "empty_file.txt")
        assert result is None

    def test_truncated_file(self):
        """File cut off mid-header returns None."""
        result = parse_email(MALFORMED / "truncated.txt")
        # Missing subject -> should return None
        assert result is None
