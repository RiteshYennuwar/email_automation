"""Email file discovery for the Enron Email Pipeline.

Recursively traverses maildir directories to find all email files.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def discover_email_files(maildir: Path) -> list[Path]:
    """Recursively find all email files in a maildir directory tree.

    Traverses the directory structure, skipping hidden files (starting with '.')
    and directories. Returns paths relative to the maildir root.

    Args:
        maildir: Root path of the maildir directory structure.

    Returns:
        Sorted list of Path objects relative to maildir root, one per email file.
    """
    if not maildir.is_dir():
        logger.error("Maildir path does not exist or is not a directory: %s", maildir)
        return []

    email_files: list[Path] = []

    for path in sorted(maildir.rglob("*")):
        # Skip directories
        if path.is_dir():
            continue

        # Skip hidden files (name starts with '.')
        if path.name.startswith("."):
            continue

        # Return path relative to maildir root
        email_files.append(path.relative_to(maildir))

    logger.info("Discovered %d email files in %s", len(email_files), maildir)
    return email_files
