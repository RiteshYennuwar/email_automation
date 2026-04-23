"""Notification generation for the Enron Email Pipeline.

Generates .eml draft files for duplicate notifications and handles
live sending via Gmail MCP.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from src.database import get_email_by_id, update_notification_sent

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output/replies")
SEND_LOG_PATH = Path("output/send_log.csv")

NOTIFICATION_TEMPLATE = """This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  {dup_message_id}
    Date Sent:   {dup_date}
    Subject:     {subject}

  Original Email on Record:
    Message-ID:  {orig_message_id}
    Date Sent:   {orig_date}

  Similarity Score: {similarity}%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate."""


def generate_notifications(
    conn: sqlite3.Connection,
    send_live: bool = False,
    notify_address: str | None = None,
) -> dict[str, int]:
    """Generate notification emails for duplicate groups.

    For each duplicate group, generates a notification for the latest
    flagged duplicate. In dry-run mode, writes .eml files. In live mode,
    sends via Gmail MCP.

    Args:
        conn: Active SQLite connection.
        send_live: Whether to send via Gmail MCP.
        notify_address: Override recipient for live sending.

    Returns:
        Dictionary with stats: generated, sent.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _init_send_log()

    # Get all duplicate groups
    rows = conn.execute(
        """SELECT e.message_id, e.date, e.from_address, e.subject, e.duplicate_of
           FROM emails e
           WHERE e.is_duplicate = 1
           ORDER BY e.duplicate_of, e.date DESC"""
    ).fetchall()

    # Group by original, take latest duplicate per group
    groups: dict[str, sqlite3.Row] = {}
    for row in rows:
        orig_id = row["duplicate_of"]
        if orig_id not in groups:
            groups[orig_id] = row

    stats = {"generated": 0, "sent": 0}

    for orig_id, dup_row in groups.items():
        original = get_email_by_id(conn, orig_id)
        if original is None:
            continue

        # Get similarity score from the dedup report if available
        similarity = _get_similarity_score(dup_row["message_id"])

        eml_content = _create_notification_eml(
            dup_message_id=dup_row["message_id"],
            dup_date=dup_row["date"],
            dup_from=dup_row["from_address"],
            subject=dup_row["subject"],
            orig_message_id=orig_id,
            orig_date=original["date"],
            similarity=similarity,
            notify_address=notify_address,
        )

        # Write .eml file
        safe_id = dup_row["message_id"].replace("<", "").replace(">", "").replace("@", "_at_")
        eml_path = OUTPUT_DIR / f"{safe_id}.eml"
        eml_path.write_text(eml_content, encoding="utf-8")
        stats["generated"] += 1

        if send_live and notify_address:
            success = _send_via_mcp(notify_address, dup_row["subject"], eml_content)
            if success:
                stats["sent"] += 1
                now_utc = datetime.now(timezone.utc).isoformat()
                update_notification_sent(conn, dup_row["message_id"], now_utc)
                _log_send(notify_address, dup_row["subject"], "sent", "")
            else:
                _log_send(notify_address, dup_row["subject"], "failed", "MCP send error")

    conn.commit()
    logger.info(
        "Notifications: %d generated, %d sent", stats["generated"], stats["sent"]
    )
    return stats


def _create_notification_eml(
    dup_message_id: str,
    dup_date: str,
    dup_from: str,
    subject: str,
    orig_message_id: str,
    orig_date: str,
    similarity: float,
    notify_address: str | None = None,
) -> str:
    """Create a notification email in .eml format.

    Args:
        dup_message_id: Message-ID of the flagged duplicate.
        dup_date: Date of the flagged duplicate.
        dup_from: From address of the flagged duplicate.
        subject: Subject of the email.
        orig_message_id: Message-ID of the original email.
        orig_date: Date of the original email.
        similarity: Similarity score percentage.
        notify_address: Override recipient address.

    Returns:
        Complete .eml content as string.
    """
    body = NOTIFICATION_TEMPLATE.format(
        dup_message_id=dup_message_id,
        dup_date=dup_date,
        subject=subject,
        orig_message_id=orig_message_id,
        orig_date=orig_date,
        similarity=round(similarity, 1),
    )

    recipient = notify_address or dup_from
    now_utc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    msg = MIMEText(body)
    msg["To"] = recipient
    msg["Subject"] = f"[Duplicate Notice] Re: {subject}"
    msg["Date"] = now_utc
    msg["References"] = dup_message_id

    return msg.as_string()


def _get_similarity_score(message_id: str) -> float:
    """Look up similarity score from the duplicates report CSV.

    Args:
        message_id: Message-ID to look up.

    Returns:
        Similarity score, or 0.0 if not found.
    """
    report_path = Path("duplicates_report.csv")
    if not report_path.exists():
        return 0.0

    try:
        with report_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("duplicate_message_id") == message_id:
                    return float(row.get("similarity_score", 0))
    except (ValueError, KeyError, OSError):
        pass

    return 0.0


def _send_via_mcp(recipient: str, subject: str, content: str) -> bool:
    """Send notification via Gmail MCP server.

    Args:
        recipient: Email address to send to.
        subject: Email subject.
        content: Full email content.

    Returns:
        True if send succeeded, False otherwise.
    """
    # MCP sending is handled externally by the MCP server
    # This is a placeholder for the MCP integration
    logger.info("Would send to %s: %s (MCP integration required)", recipient, subject)
    return False


def _init_send_log() -> None:
    """Initialize the send log CSV with headers if it doesn't exist."""
    SEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SEND_LOG_PATH.exists():
        with SEND_LOG_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "recipient", "subject", "status", "error"])


def _log_send(
    recipient: str, subject: str, status: str, error: str
) -> None:
    """Append an entry to the send log CSV.

    Args:
        recipient: Recipient email address.
        subject: Email subject.
        status: Send status (sent/failed).
        error: Error message if failed.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    with SEND_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([now_utc, recipient, subject, status, error])
