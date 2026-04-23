---
name: test-first
description: Follow test-first development practices for this project. Use when creating test files, writing test fixtures, or implementing code that must pass existing tests. References docs/TESTING.md for test cases.
---

# Test-First Development for Enron Pipeline

## Principle
Tests are the spec. Write tests BEFORE or WITH implementation. Never modify tests to make them pass — fix the implementation instead.

## Test Structure
```
tests/
├── conftest.py               # Shared fixtures
├── test_discovery.py
├── test_parser.py             # Heaviest — 30+ cases
├── test_database.py
├── test_dedup.py
├── test_notifier.py
├── test_integration.py
└── fixtures/                  # Hand-crafted test emails
    ├── valid/
    ├── malformed/
    └── duplicates/
```

## Fixture Pattern
Use pytest fixtures in conftest.py:
```python
import pytest
from pathlib import Path

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite database."""
    db_path = tmp_path / "test.db"
    conn = get_connection(str(db_path))
    create_tables(conn)
    yield conn
    conn.close()

@pytest.fixture
def sample_email():
    """Return a valid ParsedEmail for testing."""
    return ParsedEmail(
        message_id="<TEST001@example.com>",
        date=datetime(2001, 5, 14, 16, 0, 0, tzinfo=UTC),
        from_address="sender@enron.com",
        to_addresses=["recipient@enron.com"],
        subject="Test Email",
        body="This is the body of a test email.",
        source_file="maildir/lay-k/inbox/1",
    )

@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"
```

## Test Naming Convention
```python
def test_<what>_<condition>_<expected>():
    """Example: test_parse_email_missing_message_id_returns_none"""
```

## Coverage Commands
```bash
# Full suite with coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# Single module
pytest tests/test_parser.py -v

# Stop on first failure
pytest tests/ -x

# With timeout (prevent hangs)
pytest tests/ --timeout=30
```

## Target: ≥80% coverage on every src/ module

## Test File Template
```python
"""Tests for src/{module}.py."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.{module} import {function_under_test}


class TestFunctionName:
    """Tests for {function_under_test}."""

    def test_happy_path(self):
        result = function_under_test(valid_input)
        assert result == expected

    def test_edge_case(self):
        result = function_under_test(edge_input)
        assert result == expected

    def test_error_case(self):
        result = function_under_test(bad_input)
        assert result is None
```

## Fixture File Format (raw email text)
```
Message-ID: <TEST001@example.com>
Date: Mon, 14 May 2001 09:00:00 -0700 (PDT)
From: sender@enron.com
To: recipient@enron.com
Subject: Test Email
X-Folder: \Inbox

This is the body of a test email.
```
No extra blank lines before headers. One blank line between headers and body (RFC 2822 standard).
