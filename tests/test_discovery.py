"""Tests for src/discovery.py — FR-1: Email Discovery."""
from __future__ import annotations

from pathlib import Path

from src.discovery import discover_email_files


class TestDiscovery:
    """Tests for email file discovery."""

    def test_finds_all_files(self, tmp_maildir: Path):
        """Returns all nested email files."""
        files = discover_email_files(tmp_maildir)
        assert len(files) == 5

    def test_skips_hidden_files(self, tmp_path: Path):
        """Hidden files (starting with .) are excluded from results."""
        maildir = tmp_path / "maildir"
        maildir.mkdir()
        (maildir / "visible").write_text("email content")
        (maildir / ".hidden").write_text("hidden content")

        files = discover_email_files(maildir)
        assert len(files) == 1
        assert files[0] == Path("visible")

    def test_skips_directories(self, tmp_path: Path):
        """Directories are not returned as email files."""
        maildir = tmp_path / "maildir"
        maildir.mkdir()
        (maildir / "subdir").mkdir()
        (maildir / "email_file").write_text("email content")

        files = discover_email_files(maildir)
        assert len(files) == 1
        assert files[0] == Path("email_file")

    def test_empty_mailbox(self, tmp_path: Path):
        """Empty directory returns empty list, no crash."""
        maildir = tmp_path / "empty_maildir"
        maildir.mkdir()

        files = discover_email_files(maildir)
        assert files == []

    def test_relative_paths(self, tmp_maildir: Path):
        """All returned paths are relative to maildir root."""
        files = discover_email_files(tmp_maildir)
        for f in files:
            assert not f.is_absolute()
            # Should start with a mailbox name
            parts = f.parts
            assert len(parts) >= 2  # at minimum: mailbox/folder/filename

    def test_nonexistent_directory(self, tmp_path: Path):
        """Non-existent path returns empty list."""
        files = discover_email_files(tmp_path / "nonexistent")
        assert files == []
