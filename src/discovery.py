"""Email file discovery for the Enron Email Pipeline.

Recursively traverses maildir directories to find all email files.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


def discover_email_files(maildir: Path) -> list[str]:
    """Recursively find all email files in a maildir directory tree.

    Traverses the directory structure using os.walk, skipping hidden files
    (starting with '.') and directories. Returns paths relative to the
    maildir root as strings (not Path objects) to preserve trailing dots
    in filenames on Windows.

    Args:
        maildir: Root path of the maildir directory structure.

    Returns:
        Sorted list of relative path strings, one per email file.
    """
    if not maildir.is_dir():
        logger.error("Maildir path does not exist or is not a directory: %s", maildir)
        return []

    email_files: list[str] = []
    maildir_str = str(maildir.resolve())
    # Normalize: strip any trailing separator to avoid double-sep issues
    maildir_str = maildir_str.rstrip(os.sep)
    prefix_len = len(maildir_str) + 1  # +1 for the separator after maildir

    for dirpath, dirnames, filenames in os.walk(maildir_str):
        # Skip hidden directories
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))

        # Normalize dirpath to strip any trailing separator
        dp = dirpath.rstrip(os.sep)

        for fname in filenames:
            # Skip hidden files
            if fname.startswith("."):
                continue

            # Compute relative path by stripping the maildir prefix
            # This preserves trailing dots in filenames (unlike os.path.relpath)
            full_path = dp + os.sep + fname
            rel = full_path[prefix_len:]
            email_files.append(rel)

    email_files.sort()
    logger.info("Discovered %d email files in %s", len(email_files), maildir)
    return email_files


def safe_open_path(maildir: Path, rel_path: str) -> str:
    """Construct a safe file path for opening on Windows.

    On Windows, filenames ending with '.' require the extended-length path
    prefix (\\\\?\\) to bypass Win32 API path normalization that strips
    trailing dots.

    Args:
        maildir: Root maildir path.
        rel_path: Relative path string (from discover_email_files).

    Returns:
        String path suitable for open() calls.
    """
    maildir_str = str(maildir.resolve())
    full_path = maildir_str + os.sep + rel_path

    if IS_WINDOWS:
        # The \\?\ prefix (4 chars) bypasses Win32 API normalization
        win_prefix = chr(92) * 2 + "?" + chr(92)
        return win_prefix + full_path

    return full_path
