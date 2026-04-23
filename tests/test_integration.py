"""Integration tests for the Enron Email Pipeline.

End-to-end tests running the full pipeline on fixture data.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database import create_schema, get_connection, get_duplicate_count, get_email_count
from src.dedup import detect_duplicates
from src.discovery import discover_email_files
from src.notifier import OUTPUT_DIR, generate_notifications
from src.parser import parse_email
from src.database import insert_email

FIXTURES = Path(__file__).parent / "fixtures"


def _run_mini_pipeline(
    maildir: Path, db_path: str
) -> tuple[sqlite3.Connection, dict[str, int]]:
    """Run a minimal pipeline on the given directory.

    Args:
        maildir: Path to directory with email files.
        db_path: Path to SQLite database.

    Returns:
        Tuple of (connection, stats dict).
    """
    conn = get_connection(db_path)
    create_schema(conn)

    stats = {
        "discovered": 0,
        "parsed": 0,
        "failures": 0,
    }

    # Discover all files recursively
    all_files: list[Path] = []
    for path in sorted(maildir.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            all_files.append(path)

    stats["discovered"] = len(all_files)

    for file_path in all_files:
        result = parse_email(file_path, maildir)
        if result is None:
            stats["failures"] += 1
            continue
        stats["parsed"] += 1
        insert_email(conn, result)

    return conn, stats


class TestFullPipelineSmall:
    """End-to-end tests with fixture data."""

    def test_full_pipeline_small(self, tmp_path):
        """Run pipeline on valid + duplicates fixtures. Verify all outputs."""
        # Copy valid and duplicate fixtures into a temporary maildir
        maildir = tmp_path / "maildir"
        valid_dir = maildir / "valid"
        dup_dir = maildir / "duplicates"
        valid_dir.mkdir(parents=True)
        dup_dir.mkdir(parents=True)

        for f in (FIXTURES / "valid").iterdir():
            (valid_dir / f.name).write_bytes(f.read_bytes())
        for f in (FIXTURES / "duplicates").iterdir():
            (dup_dir / f.name).write_bytes(f.read_bytes())

        db_path = str(tmp_path / "test.db")
        conn, stats = _run_mini_pipeline(maildir, db_path)

        # Verify: DB populated
        assert get_email_count(conn) > 0
        assert stats["parsed"] > 0

        # Run dedup
        dedup_stats = detect_duplicates(conn)

        # Verify: duplicates flagged
        assert get_duplicate_count(conn) > 0

        # Verify: report generated
        from src.dedup import REPORT_PATH
        assert REPORT_PATH.exists()

        # Generate notifications
        notif_stats = generate_notifications(conn)
        assert notif_stats["generated"] > 0

        # Verify: .eml files created
        eml_files = list(OUTPUT_DIR.glob("*.eml"))
        assert len(eml_files) > 0

        conn.close()

    def test_pipeline_with_malformed(self, tmp_path):
        """Mix valid + malformed files. Valid in DB, malformed in error log."""
        maildir = tmp_path / "maildir"
        maildir.mkdir(parents=True)

        # Copy all fixtures
        for subdir in ["valid", "malformed"]:
            src_dir = FIXTURES / subdir
            dst_dir = maildir / subdir
            dst_dir.mkdir()
            for f in src_dir.iterdir():
                (dst_dir / f.name).write_bytes(f.read_bytes())

        db_path = str(tmp_path / "test.db")
        conn, stats = _run_mini_pipeline(maildir, db_path)

        # Valid emails should be in DB
        assert get_email_count(conn) > 0
        # Malformed emails should have caused failures
        assert stats["failures"] > 0
        # Pipeline should not crash (we got here)
        conn.close()

    def test_pipeline_idempotent(self, tmp_path):
        """Run pipeline twice. No extra rows (unique constraint)."""
        maildir = tmp_path / "maildir" / "valid"
        maildir.mkdir(parents=True)

        for f in (FIXTURES / "valid").iterdir():
            (maildir / f.name).write_bytes(f.read_bytes())

        db_path = str(tmp_path / "test.db")

        # First run
        conn1, _ = _run_mini_pipeline(maildir.parent, db_path)
        count1 = get_email_count(conn1)
        conn1.close()

        # Second run
        conn2, _ = _run_mini_pipeline(maildir.parent, db_path)
        count2 = get_email_count(conn2)
        conn2.close()

        assert count1 == count2

    def test_pipeline_stats_output(self, tmp_path, capsys):
        """Verify stats format includes key counts."""
        from main import print_summary

        stats = {
            "files_discovered": 100,
            "successfully_parsed": 90,
            "parse_failures": 10,
            "emails_in_database": 90,
            "duplicate_groups": 5,
            "emails_flagged": 12,
            "notifications_generated": 5,
            "notifications_sent": 0,
        }

        print_summary(stats)
        captured = capsys.readouterr()

        assert "100" in captured.out
        assert "90" in captured.out
        assert "10" in captured.out
        assert "Pipeline Summary" in captured.out
