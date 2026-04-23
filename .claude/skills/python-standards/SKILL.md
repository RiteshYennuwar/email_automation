---
name: python-standards
description: Apply project-specific Python coding standards when writing or reviewing any Python file. Use this whenever creating new .py files, editing existing ones, or reviewing code quality. Covers imports, type hints, docstrings, error handling, logging, pathlib, datetime, and constants.
---

# Python Coding Standards for Enron Pipeline

## File Header
Every Python file starts with:
```python
from __future__ import annotations
```

## Import Order
Separated by blank lines:
1. Standard library (`import os`, `from pathlib import Path`)
2. Third-party (`import rapidfuzz`, `from dateutil import parser`)
3. Local (`from src.models import ParsedEmail`)

## Type Hints
- ALL function signatures must have type hints
- Use `str | None` not `Optional[str]`
- Use `list[str]` not `List[str]`
- Return types always specified

```python
def parse_email(file_path: Path, maildir_root: Path) -> ParsedEmail | None:
```

## Docstrings (Google-style)
Every public function:
```python
def normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes and normalize for comparison.

    Args:
        subject: Raw subject line from email header.

    Returns:
        Lowercase subject with all reply/forward prefixes removed.
    """
```

## Error Handling
Never crash. Always catch, log, return gracefully:
```python
try:
    # risky operation
except SpecificError as e:
    logger.error("%s | ERROR_TYPE | %s", context, e)
    return None
except Exception as e:
    logger.error("%s | UNEXPECTED_ERROR | %s", context, e)
    return None
```

## Logging (not print)
```python
import logging
logger = logging.getLogger(__name__)

# For errors (goes to error_log.txt):
logger.error("%s | MISSING_FIELD:message_id | No Message-ID header", file_path)

# For info (goes to console):
logger.info("Parsed %d/%d emails", count, total)
```

Never use `print()` for errors or status. Only use `print()` for the final pipeline summary stats.

## Paths
Always `pathlib.Path`, never `os.path`:
```python
from pathlib import Path

file_path = maildir_root / employee / folder / filename
relative = file_path.relative_to(maildir_root)
```

## Datetime
Always UTC-aware:
```python
from datetime import datetime, UTC

now = datetime.now(UTC)
# Never: datetime.now()
# Never: datetime.utcnow()
```

## SQL
Always parameterized, never f-strings:
```python
# Good:
conn.execute("INSERT INTO emails (message_id, date) VALUES (?, ?)", (msg_id, date))

# Bad:
conn.execute(f"INSERT INTO emails VALUES ('{msg_id}', '{date}')")
```

## Constants
At module top, not inline:
```python
SIMILARITY_THRESHOLD = 90
SUBJECT_PREFIX_PATTERN = re.compile(r'^(re|fwd|fw)\s*:\s*', re.IGNORECASE)
FORWARD_MARKERS = [
    "-----Original Message-----",
    "---------- Forwarded message ----------",
    "---------------------- Forwarded by",
]
```

## Dataclasses
Use for all structured data:
```python
from dataclasses import dataclass, field

@dataclass
class ParsedEmail:
    message_id: str
    date: datetime
    # ... required fields, then optional with defaults
    cc_addresses: list[str] = field(default_factory=list)
    x_from: str | None = None
```

## Context Managers
Always for files and DB connections:
```python
with open(file_path, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

with get_connection(db_path) as conn:
    conn.execute(...)
```
