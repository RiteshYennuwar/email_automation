"""Database operations for the Enron Email Pipeline.

Handles schema creation, email insertion, and query functions using SQLite.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from src.models import ParsedEmail

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


def get_connection(db_path: str = "enron.db") -> sqlite3.Connection:
    """Create and configure a SQLite connection.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Configured sqlite3.Connection with WAL mode and foreign keys enabled.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create database tables and indexes from schema.sql.

    Args:
        conn: Active SQLite connection.
    """
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()


def insert_email(conn: sqlite3.Connection, email: ParsedEmail) -> bool:
    """Insert a parsed email into the database.

    Inserts the email record and all recipients (to/cc/bcc) in a single
    transaction. Uses INSERT OR IGNORE to skip duplicate message_ids.

    Args:
        conn: Active SQLite connection.
        email: ParsedEmail dataclass with all extracted fields.

    Returns:
        True if the email was inserted, False if it was a duplicate (skipped).
    """
    try:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO emails (
                message_id, date, from_address, subject, body, source_file,
                x_from, x_to, x_cc, x_bcc, x_folder, x_origin,
                content_type, has_attachment, forwarded_content, quoted_content, headings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email.message_id,
                email.date.isoformat(),
                email.from_address,
                email.subject,
                email.body,
                email.source_file,
                email.x_from,
                email.x_to,
                email.x_cc,
                email.x_bcc,
                email.x_folder,
                email.x_origin,
                email.content_type,
                email.has_attachment,
                email.forwarded_content,
                email.quoted_content,
                email.headings,
            ),
        )

        if cursor.rowcount == 0:
            return False

        # Insert recipients
        recipients = []
        for addr in email.to_addresses:
            recipients.append((email.message_id, addr, "to"))
        for addr in email.cc_addresses:
            recipients.append((email.message_id, addr, "cc"))
        for addr in email.bcc_addresses:
            recipients.append((email.message_id, addr, "bcc"))

        if recipients:
            conn.executemany(
                "INSERT INTO email_recipients (email_message_id, address, recipient_type) "
                "VALUES (?, ?, ?)",
                recipients,
            )

        conn.commit()
        return True

    except sqlite3.Error as e:
        logger.error("DB_INSERT_ERROR | %s | %s", email.message_id, e)
        conn.rollback()
        return False


def get_email_count(conn: sqlite3.Connection) -> int:
    """Get total number of emails in the database.

    Args:
        conn: Active SQLite connection.

    Returns:
        Count of emails in the database.
    """
    row = conn.execute("SELECT COUNT(*) as cnt FROM emails").fetchone()
    return row["cnt"]


def get_duplicate_count(conn: sqlite3.Connection) -> int:
    """Get count of emails flagged as duplicates.

    Args:
        conn: Active SQLite connection.

    Returns:
        Count of emails where is_duplicate is true.
    """
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM emails WHERE is_duplicate = 1"
    ).fetchone()
    return row["cnt"]


def get_emails_for_dedup(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Retrieve all emails for duplicate detection processing.

    Returns emails with fields needed for grouping and comparison:
    message_id, date, from_address, subject, and body.

    Args:
        conn: Active SQLite connection.

    Returns:
        List of Row objects with dedup-relevant fields.
    """
    return conn.execute(
        "SELECT message_id, date, from_address, subject, body FROM emails"
    ).fetchall()


def flag_duplicate(
    conn: sqlite3.Connection, message_id: str, original_message_id: str
) -> None:
    """Flag an email as a duplicate of another email.

    Args:
        conn: Active SQLite connection.
        message_id: The message_id of the duplicate email.
        original_message_id: The message_id of the original email.
    """
    conn.execute(
        "UPDATE emails SET is_duplicate = 1, duplicate_of = ? WHERE message_id = ?",
        (original_message_id, message_id),
    )


def update_notification_sent(
    conn: sqlite3.Connection, message_id: str, notification_date: str
) -> None:
    """Mark an email as having had its notification sent.

    Args:
        conn: Active SQLite connection.
        message_id: The message_id of the email.
        notification_date: ISO-8601 UTC timestamp of when notification was sent.
    """
    conn.execute(
        "UPDATE emails SET notification_sent = 1, notification_date = ? WHERE message_id = ?",
        (notification_date, message_id),
    )


def get_duplicate_groups(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get all duplicate groups with their originals.

    Args:
        conn: Active SQLite connection.

    Returns:
        List of Row objects with duplicate info grouped by original.
    """
    return conn.execute(
        """SELECT e.message_id, e.date, e.from_address, e.subject, e.body,
                  e.duplicate_of
           FROM emails e
           WHERE e.is_duplicate = 1
           ORDER BY e.duplicate_of, e.date"""
    ).fetchall()


def get_email_by_id(conn: sqlite3.Connection, message_id: str) -> sqlite3.Row | None:
    """Retrieve a single email by message_id.

    Args:
        conn: Active SQLite connection.
        message_id: The unique message identifier.

    Returns:
        Row object with all email fields, or None if not found.
    """
    return conn.execute(
        "SELECT * FROM emails WHERE message_id = ?", (message_id,)
    ).fetchone()
