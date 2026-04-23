"""CLI entry point for the Enron Email Pipeline.

Orchestrates: discovery -> parsing -> database storage -> dedup -> notifications.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.database import create_schema, get_connection, get_duplicate_count, get_email_count, insert_email
from src.dedup import detect_duplicates
from src.discovery import discover_email_files
from src.notifier import generate_notifications
from src.parser import parse_email

DEFAULT_MAILDIR = Path("data/maildir")
DEFAULT_DB = "enron.db"
SELECTED_MAILBOXES = ["lay-k", "skilling-j", "kaminski-v", "dasovich-j", "kean-s"]


def setup_logging() -> None:
    """Configure logging with console output and error file handler."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    file_handler = logging.FileHandler("error_log.txt", mode="w")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
    )
    logging.getLogger().addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Enron Email Data Extraction & Notification Pipeline"
    )
    parser.add_argument(
        "--maildir",
        type=Path,
        default=DEFAULT_MAILDIR,
        help=f"Path to maildir root (default: {DEFAULT_MAILDIR})",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--send-live",
        action="store_true",
        help="Send notifications via Gmail MCP (default: dry-run)",
    )
    parser.add_argument(
        "--notify-address",
        type=str,
        default=None,
        help="Override recipient address for live notifications",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch web dashboard after pipeline run",
    )
    return parser.parse_args()


def run_pipeline(
    maildir: Path,
    db_path: str,
    send_live: bool = False,
    notify_address: str | None = None,
) -> dict[str, int]:
    """Run the full email processing pipeline.

    Args:
        maildir: Path to maildir root directory.
        db_path: Path to SQLite database file.
        send_live: Whether to send notifications via Gmail MCP.
        notify_address: Override recipient address for notifications.

    Returns:
        Dictionary of pipeline statistics.
    """
    stats: dict[str, int] = {
        "files_discovered": 0,
        "successfully_parsed": 0,
        "parse_failures": 0,
        "emails_in_database": 0,
        "duplicate_groups": 0,
        "emails_flagged": 0,
        "notifications_generated": 0,
        "notifications_sent": 0,
    }

    # Step 1: Discovery
    print("=== Step 1: Discovering email files ===", file=sys.stderr)
    all_files: list[Path] = []

    # Only process selected mailboxes
    for mailbox in SELECTED_MAILBOXES:
        mailbox_path = maildir / mailbox
        if mailbox_path.is_dir():
            files = discover_email_files(mailbox_path)
            # Prepend mailbox name to relative paths
            all_files.extend(
                Path(mailbox) / f for f in files
            )

    stats["files_discovered"] = len(all_files)
    print(f"  Found {len(all_files)} email files", file=sys.stderr)

    # Step 2: Parse and store
    print("=== Step 2: Parsing and storing emails ===", file=sys.stderr)
    conn = get_connection(db_path)
    create_schema(conn)

    total = len(all_files)
    for i, rel_path in enumerate(all_files, 1):
        if i % 500 == 0:
            print(f"  Parsed {i}/{total} emails...", file=sys.stderr)

        file_path = maildir / rel_path
        result = parse_email(file_path, maildir)

        if result is None:
            stats["parse_failures"] += 1
            continue

        stats["successfully_parsed"] += 1
        insert_email(conn, result)

    stats["emails_in_database"] = get_email_count(conn)
    print(
        f"  Parsed: {stats['successfully_parsed']}, "
        f"Failed: {stats['parse_failures']}, "
        f"In DB: {stats['emails_in_database']}",
        file=sys.stderr,
    )

    # Step 3: Dedup
    print("=== Step 3: Detecting duplicates ===", file=sys.stderr)
    dedup_stats = detect_duplicates(conn)
    stats["duplicate_groups"] = dedup_stats["groups"]
    stats["emails_flagged"] = dedup_stats["flagged"]
    print(
        f"  Groups: {stats['duplicate_groups']}, "
        f"Flagged: {stats['emails_flagged']}",
        file=sys.stderr,
    )

    # Step 4: Notifications
    print("=== Step 4: Generating notifications ===", file=sys.stderr)
    notif_stats = generate_notifications(
        conn, send_live=send_live, notify_address=notify_address
    )
    stats["notifications_generated"] = notif_stats["generated"]
    stats["notifications_sent"] = notif_stats["sent"]

    conn.close()
    return stats


def print_summary(stats: dict[str, int]) -> None:
    """Print pipeline summary statistics to stdout.

    Args:
        stats: Dictionary of pipeline statistics.
    """
    print("\n=== Pipeline Summary ===")
    print(f"Files discovered:    {stats['files_discovered']:>8,}")
    print(f"Successfully parsed: {stats['successfully_parsed']:>8,}")
    print(f"Parse failures:      {stats['parse_failures']:>8,}")
    print(f"Emails in database:  {stats['emails_in_database']:>8,}")
    print(f"Duplicate groups:    {stats['duplicate_groups']:>8,}")
    print(f"Emails flagged:      {stats['emails_flagged']:>8,}")
    print(f"Notifications generated: {stats['notifications_generated']:>4,}")
    mode = "dry-run mode" if stats["notifications_sent"] == 0 else "live"
    print(f"Notifications sent:  {stats['notifications_sent']:>8,} ({mode})")


def main() -> None:
    """Main entry point for the pipeline."""
    setup_logging()
    args = parse_args()

    if args.send_live and not args.notify_address:
        print(
            "ERROR: --send-live requires --notify-address", file=sys.stderr
        )
        sys.exit(1)

    stats = run_pipeline(
        maildir=args.maildir,
        db_path=args.db,
        send_live=args.send_live,
        notify_address=args.notify_address,
    )

    print_summary(stats)

    if args.dashboard:
        print("\n=== Launching Dashboard ===", file=sys.stderr)
        from src.dashboard import create_app

        app = create_app(args.db)
        app.run(host="0.0.0.0", port=8050, debug=False)


if __name__ == "__main__":
    main()
