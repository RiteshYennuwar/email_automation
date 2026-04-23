"""Duplicate detection for the Enron Email Pipeline.

Groups emails by sender + normalized subject, then uses fuzzy matching
on body content to identify near-duplicates.
"""
from __future__ import annotations

import csv
import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

from src.database import flag_duplicate, get_emails_for_dedup
from src.models import DuplicateGroup

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD: int = 90
SUBJECT_PREFIX_PATTERN: re.Pattern[str] = re.compile(
    r"^(re|fwd|fw)\s*:\s*", re.IGNORECASE
)
REPORT_PATH = Path("duplicates_report.csv")


def normalize_subject(subject: str) -> str:
    """Normalize an email subject for dedup grouping.

    Strips Re:, Fwd:, FW: prefixes (case-insensitive, repeated),
    then strips whitespace, then lowercases.

    Args:
        subject: Original email subject string.

    Returns:
        Normalized subject string for comparison.
    """
    normalized = subject.strip()
    while True:
        new = SUBJECT_PREFIX_PATTERN.sub("", normalized, count=1).strip()
        if new == normalized:
            break
        normalized = new
    return normalized.strip().lower()


def detect_duplicates(conn: sqlite3.Connection) -> dict[str, int]:
    """Detect and flag duplicate emails in the database.

    Groups emails by (lowercase from_address, normalized subject),
    then compares body content within each group using fuzzy matching.
    The earliest email by UTC date is the original; all others above
    the similarity threshold are flagged as duplicates.

    Args:
        conn: Active SQLite connection with emails already inserted.

    Returns:
        Dictionary with stats: groups, flagged, avg_group_size.
    """
    emails = get_emails_for_dedup(conn)

    # Group by (from_address, normalized_subject)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in emails:
        from_addr = (row["from_address"] or "").lower()
        norm_subj = normalize_subject(row["subject"] or "")
        key = (from_addr, norm_subj)
        groups[key].append({
            "message_id": row["message_id"],
            "date": row["date"],
            "from_address": row["from_address"],
            "subject": row["subject"],
            "body": row["body"] or "",
        })

    # Only process groups with 2+ emails
    duplicate_groups: list[DuplicateGroup] = []
    total_flagged = 0
    report_rows: list[dict] = []

    for key, email_group in groups.items():
        if len(email_group) < 2:
            continue

        # Sort by date (earliest first), then by message_id for tiebreaker
        email_group.sort(key=lambda e: (e["date"], e["message_id"]))

        original = email_group[0]
        original_body = original["body"]

        dup_ids: list[str] = []
        scores: dict[str, float] = {}

        for candidate in email_group[1:]:
            score = fuzz.ratio(original_body, candidate["body"])
            if score >= SIMILARITY_THRESHOLD:
                dup_ids.append(candidate["message_id"])
                scores[candidate["message_id"]] = score
                flag_duplicate(conn, candidate["message_id"], original["message_id"])
                total_flagged += 1

                report_rows.append({
                    "duplicate_message_id": candidate["message_id"],
                    "original_message_id": original["message_id"],
                    "subject": candidate["subject"],
                    "from_address": candidate["from_address"],
                    "duplicate_date": candidate["date"],
                    "original_date": original["date"],
                    "similarity_score": round(score, 2),
                })

        if dup_ids:
            from datetime import datetime
            from dateutil import parser as dateutil_parser

            try:
                orig_date = dateutil_parser.parse(original["date"])
            except (ValueError, TypeError):
                orig_date = datetime.min

            duplicate_groups.append(DuplicateGroup(
                original_message_id=original["message_id"],
                original_date=orig_date,
                duplicate_message_ids=dup_ids,
                subject=original["subject"],
                from_address=original["from_address"],
                similarity_scores=scores,
            ))

    conn.commit()

    # Write CSV report
    _write_report(report_rows)

    # Log stats
    avg_size = (
        sum(len(g.duplicate_message_ids) + 1 for g in duplicate_groups) / len(duplicate_groups)
        if duplicate_groups
        else 0
    )
    logger.info(
        "Dedup stats: %d groups, %d flagged, %.1f avg group size",
        len(duplicate_groups),
        total_flagged,
        avg_size,
    )

    return {
        "groups": len(duplicate_groups),
        "flagged": total_flagged,
        "avg_group_size": round(avg_size, 1),
    }


def _write_report(rows: list[dict]) -> None:
    """Write the duplicates report CSV.

    Args:
        rows: List of dictionaries with report columns.
    """
    fieldnames = [
        "duplicate_message_id",
        "original_message_id",
        "subject",
        "from_address",
        "duplicate_date",
        "original_date",
        "similarity_score",
    ]

    with REPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote duplicates report to %s (%d rows)", REPORT_PATH, len(rows))
