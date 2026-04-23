"""Email parsing for the Enron Email Pipeline.

Parses RFC 2822 email files and extracts structured fields into ParsedEmail dataclasses.
"""
from __future__ import annotations

import email
import email.utils
import logging
import re
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

from dateutil import parser as dateutil_parser
from dateutil.tz import gettz, tzoffset, tzutc

from src.models import ParsedEmail

logger = logging.getLogger(__name__)

# Timezone abbreviation mapping for common Enron email timezones
TIMEZONE_MAP: dict[str, int] = {
    "PST": -8 * 3600,
    "PDT": -7 * 3600,
    "MST": -7 * 3600,
    "MDT": -6 * 3600,
    "CST": -6 * 3600,
    "CDT": -5 * 3600,
    "EST": -5 * 3600,
    "EDT": -4 * 3600,
}

FORWARD_MARKERS: list[str] = [
    "-----Original Message-----",
    "---------- Forwarded message ----------",
    "---------------------- Forwarded by",
]

SUBJECT_PREFIX_PATTERN: re.Pattern[str] = re.compile(
    r"^(re|fwd|fw)\s*:\s*", re.IGNORECASE
)

ATTACHMENT_ANGLE_PATTERN: re.Pattern[str] = re.compile(r"<<[^>]+\.\w+>>")

HEADING_ALLCAPS_PATTERN: re.Pattern[str] = re.compile(
    r"^[A-Z][A-Z\s]{2,}[A-Z]$", re.MULTILINE
)
HEADING_COLON_PATTERN: re.Pattern[str] = re.compile(
    r"^[A-Za-z][A-Za-z\s]+:\s*$", re.MULTILINE
)
HEADING_HTML_PATTERN: re.Pattern[str] = re.compile(
    r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE
)


def parse_email(file_path: Path, maildir: Path | None = None) -> ParsedEmail | None:
    """Parse a raw RFC 2822 email file and extract structured fields.

    Args:
        file_path: Path to the raw email file.
        maildir: Root maildir path for computing relative source_file.

    Returns:
        ParsedEmail dataclass with all extracted fields, or None if
        mandatory fields could not be extracted (failure logged).
    """
    source_file = str(file_path.relative_to(maildir)) if maildir else str(file_path)

    try:
        raw_bytes = file_path.read_bytes()
    except OSError as e:
        logger.error("%s | READ_ERROR | %s", source_file, e)
        return None

    # Try UTF-8 first, then latin-1 as fallback
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw_text = raw_bytes.decode("latin-1")
        except UnicodeDecodeError as e:
            logger.error("%s | DECODE_ERROR | %s", source_file, e)
            return None

    if not raw_text.strip():
        logger.error("%s | MISSING_FIELD:all | Empty file", source_file)
        return None

    try:
        msg: Message = email.message_from_string(raw_text)
    except Exception as e:
        logger.error("%s | PARSE_ERROR | %s", source_file, e)
        return None

    # Extract mandatory fields
    message_id = msg.get("Message-ID", "").strip()
    if not message_id:
        logger.error(
            "%s | MISSING_FIELD:message_id | No Message-ID header found", source_file
        )
        return None

    date_str = msg.get("Date", "").strip()
    if not date_str:
        logger.error(
            "%s | MISSING_FIELD:date | No Date header found", source_file
        )
        return None

    parsed_date = _parse_date(date_str)
    if parsed_date is None:
        logger.error(
            "%s | PARSE_ERROR:date | Could not parse: %r", source_file, date_str
        )
        return None

    from_header = msg.get("From", "").strip()
    if not from_header:
        logger.error(
            "%s | MISSING_FIELD:from_address | No From header found", source_file
        )
        return None
    from_address = _extract_address(from_header)

    to_header = msg.get("To", "").strip()
    if not to_header:
        logger.error(
            "%s | MISSING_FIELD:to_addresses | No To header found", source_file
        )
        return None
    to_addresses = _extract_addresses(to_header)
    if not to_addresses:
        logger.error(
            "%s | MISSING_FIELD:to_addresses | Could not parse To addresses",
            source_file,
        )
        return None

    subject = msg.get("Subject", "")
    if subject is None:
        subject = ""
    subject = subject.strip()
    if not subject:
        logger.error(
            "%s | MISSING_FIELD:subject | No Subject header found", source_file
        )
        return None

    # Extract body
    body = _extract_body(msg)

    # Separate forwarded and quoted content from body
    primary_body, forwarded_content, quoted_content = _separate_body_content(body)

    # Extract optional fields
    cc_header = msg.get("Cc", "") or ""
    cc_addresses = _extract_addresses(cc_header) if cc_header.strip() else []

    bcc_header = msg.get("Bcc", "") or ""
    bcc_addresses = _extract_addresses(bcc_header) if bcc_header.strip() else []

    x_from = (msg.get("X-From") or "").strip() or None
    x_to = (msg.get("X-To") or "").strip() or None
    x_cc = (msg.get("X-cc") or "").strip() or None
    x_bcc = (msg.get("X-bcc") or "").strip() or None
    x_folder = (msg.get("X-Folder") or "").strip() or None
    x_origin = (msg.get("X-Origin") or "").strip() or None

    content_type = msg.get("Content-Type")
    if content_type:
        content_type = content_type.strip()

    has_attachment = _detect_attachment(msg, body)

    headings = _extract_headings(body)

    return ParsedEmail(
        message_id=message_id,
        date=parsed_date,
        from_address=from_address,
        to_addresses=to_addresses,
        subject=subject,
        body=primary_body,
        source_file=source_file,
        cc_addresses=cc_addresses,
        bcc_addresses=bcc_addresses,
        x_from=x_from,
        x_to=x_to,
        x_cc=x_cc,
        x_bcc=x_bcc,
        x_folder=x_folder,
        x_origin=x_origin,
        content_type=content_type,
        has_attachment=has_attachment,
        forwarded_content=forwarded_content,
        quoted_content=quoted_content,
        headings=headings,
    )


def _parse_date(date_str: str) -> datetime | None:
    """Parse a date string into a UTC-aware datetime.

    Handles RFC 2822 dates, timezone abbreviations (PST, EST, CDT, etc.),
    and various date formats found in Enron emails.

    Args:
        date_str: Raw date string from email header.

    Returns:
        UTC datetime or None if unparseable.
    """
    # Remove parenthetical timezone comments like "(PDT)"
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", date_str).strip()

    try:
        # Try dateutil parser with timezone info
        tzinfos = {k: tzoffset(k, v) for k, v in TIMEZONE_MAP.items()}
        dt = dateutil_parser.parse(cleaned, tzinfos=tzinfos)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        pass

    try:
        # Fallback: try email.utils.parsedate_to_datetime
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass

    return None


def _extract_address(header_value: str) -> str:
    """Extract a single email address from a header value.

    Strips display names, angle brackets, and normalizes to lowercase.

    Args:
        header_value: Raw header value like '"Ken Lay" <klay@enron.com>'.

    Returns:
        Lowercase email address string.
    """
    # Use email.utils to parse the address
    _, addr = email.utils.parseaddr(header_value)
    if addr:
        return addr.strip().lower()
    # Fallback: just return the cleaned value
    return header_value.strip().lower()


def _extract_addresses(header_value: str) -> list[str]:
    """Extract multiple email addresses from a header value.

    Handles comma-separated addresses, multiline continuation headers,
    and mixed formats (display name + bare address).

    Args:
        header_value: Raw header value potentially containing multiple addresses.

    Returns:
        List of lowercase email address strings.
    """
    if not header_value.strip():
        return []

    addresses: list[str] = []
    parsed = email.utils.getaddresses([header_value])
    for _, addr in parsed:
        addr = addr.strip().lower()
        if addr and "@" in addr:
            addresses.append(addr)

    return addresses


def _extract_body(msg: Message) -> str:
    """Extract the text body from an email message.

    Handles both simple and multipart messages.

    Args:
        msg: Parsed email.message.Message object.

    Returns:
        Body text as a string (may be empty).
    """
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        parts.append(payload.decode(charset))
                    except (UnicodeDecodeError, LookupError):
                        parts.append(payload.decode("latin-1"))
        return "\n".join(parts)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                return payload.decode("latin-1")
        # Fallback for non-decoded payload
        payload = msg.get_payload()
        if isinstance(payload, str):
            return payload
        return ""


def _separate_body_content(
    body: str,
) -> tuple[str, str | None, str | None]:
    """Separate primary body from forwarded and quoted content.

    Forwarded content is text after forward markers.
    Quoted content is lines starting with '>'.

    Args:
        body: Full body text.

    Returns:
        Tuple of (primary_body, forwarded_content, quoted_content).
    """
    if not body:
        return "", None, None

    # Find forwarded content
    forwarded_content: str | None = None
    primary_body = body

    for marker in FORWARD_MARKERS:
        idx = body.find(marker)
        if idx != -1:
            primary_body = body[:idx].rstrip()
            forwarded_content = body[idx:].strip()
            break

    # Extract quoted content (lines starting with >)
    lines = primary_body.split("\n")
    quoted_lines: list[str] = []
    primary_lines: list[str] = []

    for line in lines:
        if line.startswith(">"):
            quoted_lines.append(line)
        else:
            primary_lines.append(line)

    quoted_content = "\n".join(quoted_lines).strip() if quoted_lines else None
    primary_body = "\n".join(primary_lines).strip()

    return primary_body, forwarded_content, quoted_content


def _detect_attachment(msg: Message, body: str) -> bool:
    """Detect whether an email has attachments.

    Checks Content-Type for multipart/mixed, MIME boundaries,
    <<filename>> patterns, and body keywords.

    Args:
        msg: Parsed email message.
        body: Extracted body text.

    Returns:
        True if attachment indicators are found.
    """
    content_type = msg.get_content_type() or ""

    # Check for multipart/mixed (typical for attachments)
    if "multipart/mixed" in content_type:
        return True

    # Check for Content-Disposition: attachment in any part
    if msg.is_multipart():
        for part in msg.walk():
            disposition = part.get("Content-Disposition", "")
            if "attachment" in disposition.lower():
                return True

    # Check for <<filename.ext>> patterns in body
    if body and ATTACHMENT_ANGLE_PATTERN.search(body):
        return True

    return False


def _extract_headings(body: str) -> str | None:
    """Extract headings from email body text.

    Detects ALL CAPS lines, lines ending with ':', and HTML heading tags.

    Args:
        body: Email body text.

    Returns:
        Newline-separated headings string, or None if no headings found.
    """
    if not body:
        return None

    headings: list[str] = []

    # ALL CAPS lines (at least 4 chars, all uppercase letters/spaces)
    for match in HEADING_ALLCAPS_PATTERN.finditer(body):
        heading = match.group().strip()
        if len(heading) >= 4:
            headings.append(heading)

    # Lines ending with colon
    for match in HEADING_COLON_PATTERN.finditer(body):
        heading = match.group().strip()
        if heading not in headings:
            headings.append(heading)

    # HTML heading tags
    for match in HEADING_HTML_PATTERN.finditer(body):
        heading = match.group(1).strip()
        if heading and heading not in headings:
            headings.append(heading)

    return "\n".join(headings) if headings else None
