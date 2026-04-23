# Enron Email Pipeline — Project Context

## What this project does
Python CLI pipeline that ingests raw Enron email files (RFC 2822), extracts structured fields into SQLite, detects near-duplicate emails via fuzzy matching, and sends automated notification emails via a Gmail MCP server. Includes a local web dashboard for exploring results, managing duplicates, and running pipeline operations.

## Reference Documents (READ THESE FIRST)
- `docs/SRS.md` — Full software requirements, data model, module structure, acceptance criteria
- `docs/TESTING.md` — Test strategy, fixtures, every test case by module
- `docs/UI.md` — Dashboard specification (7 sections — built in Phase 7 after real data validation)
- `AI_USAGE.md` (root) — Template for AI tool usage documentation (fill in during development, not after). This is a **critical evaluation deliverable** — capture prompts, failures, and iterations in real time as you build.

## Stack
- Python 3.10+
- SQLite via stdlib `sqlite3`
- `email` stdlib for RFC 2822 parsing
- `python-dateutil` for timezone-aware date parsing
- `rapidfuzz` for fuzzy string matching (MIT, C++ backend)
- `flask` for dashboard
- Gmail MCP server for live notifications
- SQLite MCP server for Claude Code database access during development
- GitHub MCP server for repo operations (commit, push, PR)

## MCP Servers

### Project MCP Config (`.mcp.json` at project root, committed to git)

Three servers. Gmail is required by the assignment. SQLite is a dev tool for database inspection. GitHub enables direct repo operations (commit, push, PR) through MCP.

```json
{
  "mcpServers": {
    "gmail": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp"]
    },
    "sqlite": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-server-sqlite-npx", "./enron.db"]
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
      }
    }
  }
}
```

### Gmail MCP (`@gongrzhe/server-gmail-autoauth-mcp`)
- **Purpose:** Send duplicate notification emails (Task 4). Required by assignment.
- **Tools used:** `send_email`
- **Auth:** Google OAuth 2.0. Credentials stored in `~/.gmail-mcp/` (never committed).
- **Setup:** Place `gcp-oauth.keys.json` in `~/.gmail-mcp/`, run `npx @gongrzhe/server-gmail-autoauth-mcp auth`.
- **When used:** Only during `--send-live` mode. Dry-run generates `.eml` files without MCP.

### SQLite MCP (`mcp-server-sqlite-npx`)
- **Purpose:** Let Claude Code inspect the database during development — check schema, run queries, verify dedup results, debug data issues.
- **Tools available:** `read_query`, `write_query`, `create_table`, `list_tables`, `describe_table`, `append_insight`
- **Auth:** None (local file access).
- **When used:** During development only. Not called by the pipeline code itself.
- **Note:** The DB path `./enron.db` is relative to project root. The MCP server creates the file if it doesn't exist.

### GitHub MCP (GitHub's official remote server)
- **Purpose:** Git operations through MCP — create repos, commit, push, create branches, open PRs, manage issues.
- **Tools available:** `create_repository`, `push_files`, `create_branch`, `create_pull_request`, `create_or_update_file`, `search_repositories`, `list_issues`, `create_issue`, and more.
- **Auth:** GitHub Personal Access Token (PAT) with `repo` scope. Set as `GITHUB_PERSONAL_ACCESS_TOKEN` environment variable.
- **When used:** By the conductor agent to commit after each phase and push to the remote repo. Also useful for creating the initial repo and final PR.
- **Note:** HTTP transport — connects to `https://api.githubcopilot.com/mcp/`.

### MCP servers NOT included (and why)
- **Filesystem MCP** — Claude Code already has built-in file read/write via bash. Redundant.
- **Browser/Playwright MCP** — Dashboard is a Flask app; Claude Code writes code, you visually verify. No automated browser needed.
- **Context7/Docs MCP** — Nice for looking up library docs, but Claude Code's training data covers `email`, `sqlite3`, `rapidfuzz`, and `flask` well enough.

## Subagents (`.claude/agents/`)

Five custom subagents forming an autonomous build pipeline. The `conductor` orchestrates everything; the others are quality gates it delegates to.

### `conductor` (Opus) — Project orchestrator
- **When to use:** At project start. Give it one prompt and it builds the entire project.
- **What it does:** Implements each module in build order, delegates review/test/audit to other agents, fixes issues, commits after each passing phase.
- **Tools:** Read, Write, Edit, Bash, Glob, Grep (full access — it's the builder)
- **Invoke:** "Use the conductor agent to build the entire Enron Email Pipeline project from scratch."

### `code-reviewer` (Sonnet) — Spec compliance review
- **Invoked by:** conductor, after each module is built
- **What it does:** Checks code against SRS.md requirements, CLAUDE.md coding standards, and TESTING.md edge cases. Reports line-level issues.
- **Tools:** Read, Grep, Glob (read-only, never modifies code)

### `test-runner` (Sonnet) — Test execution + coverage
- **Invoked by:** conductor, after code review passes
- **What it does:** Runs pytest, analyzes failures with root causes, checks coverage per module.
- **Tools:** Read, Bash, Grep, Glob

### `error-analyzer` (Sonnet) — Post-run diagnostics
- **Invoked by:** conductor during Phase 6 (real data validation), or manually after any pipeline run
- **What it does:** Reads error_log.txt, queries DB, checks output consistency, spot-checks failures.
- **Tools:** Read, Grep, Glob, Bash

### `deliverable-auditor` (Sonnet) — Pre-submission audit
- **Invoked by:** conductor at the end, or you before submission
- **What it does:** Verifies every deliverable exists, is complete, and meets the assignment spec.
- **Tools:** Read, Grep, Glob, Bash

## Skills (`.claude/skills/`)

Reusable playbooks that Claude loads on-demand when relevant. Unlike CLAUDE.md content (always loaded), skills only consume context when triggered — keeping sessions efficient.

### `/build-pipeline` — Project entry point
- **Invoke manually:** Type `/build-pipeline` to start the full autonomous build
- **What it does:** Delegates to the conductor agent with full build instructions covering all 9 phases
- **Why a skill:** Single entry point. No need to copy-paste a long prompt.

### `/python-standards` — Project coding conventions
- **Auto-triggers when:** Writing or editing any `.py` file
- **Contains:** Import order, type hints, docstrings, error handling pattern, logging setup, pathlib, datetime UTC, SQL parameterization, constants, dataclasses, context managers
- **Why a skill not CLAUDE.md:** Too long for always-loaded context. Loads only when writing Python.

### `/email-parsing` — Enron email parsing reference
- **Auto-triggers when:** Working on `src/parser.py` or debugging parse failures
- **Contains:** Python `email` stdlib patterns, address extraction, date parsing with timezone mapping, body/forwarded/quoted content separation, attachment detection, headings detection, Enron-specific edge cases
- **Why a skill:** Dense reference material (~3K tokens) that's only needed during parser development

### `/test-first` — Test development practices
- **Auto-triggers when:** Creating test files, writing fixtures, or implementing code to pass tests
- **Contains:** Fixture patterns, naming conventions, coverage commands, test file template, fixture file format
- **Why a skill:** Loaded during test-writing phases, not during documentation or dashboard work

### `/git-workflow` — Commit conventions
- **Auto-triggers when:** Staging, committing, or pushing code
- **Contains:** Conventional commit format, type/scope definitions, per-phase commit messages, what not to commit

## Dataset
Process ≥5 mailboxes, ≥10,000 emails. Data in `./data/maildir/` (gitignored).

Selected mailboxes:
- `lay-k` — CEO, high volume, forwarded content, CC chains
- `skilling-j` — CEO, internal/external mix
- `kaminski-v` — Research head, technical emails, encoding variety
- `dasovich-j` — Gov affairs, deep forwarding chains
- `kean-s` — Chief of staff, BCC usage, mixed formats

If these don't hit 10K total, add `germany-c` or `jones-t`.

## Key Commands
- `python main.py` — full pipeline, dry-run (drafts .eml files, no MCP send)
- `python main.py --send-live --notify-address you@gmail.com` — pipeline + live email send
- `python main.py --dashboard` — pipeline + launch local dashboard on :8050
- `python main.py --maildir path/to/maildir` — custom data path
- `pytest tests/ -v` — run all tests
- `pytest tests/ --cov=src` — tests with coverage
- `sqlite3 enron.db < sample_queries.sql` — verify DB

## Build Order (FOLLOW THIS SEQUENCE)
Claude Code should build modules in this order to minimize rework and wasted credits:

1. **`schema.sql`** — DDL first. Everything depends on the data model.
2. **`src/database.py`** — Schema creation + insert/query functions. Test with `test_database.py`.
3. **`src/discovery.py`** — File traversal. Simple, test with `test_discovery.py`.
4. **`src/parser.py`** — Email parsing. Heaviest module. Test with `test_parser.py` extensively before moving on.
5. **`main.py` (partial)** — Wire up discovery → parser → database. Run on real data subset to validate.
6. **`src/dedup.py`** — Duplicate detection. Depends on populated DB. Test with `test_dedup.py`.
7. **`src/notifier.py`** — Notification generation (dry-run first). Test with `test_notifier.py`.
8. **`test_integration.py`** — End-to-end tests on fixture data.
9. **MCP integration** — Wire up live sending. This is infrastructure, not code-heavy.
10. **`sample_queries.sql`** — Write after DB is populated with real data.
11. **`README.md`** — Write after everything works.
12. **Dashboard** — After real data validation. Needs populated DB.

**Why this order:** Each step validates the previous one. Parser bugs caught before DB insertion. DB tested before dedup runs on it. Integration tests confirm the full chain works before you wire up MCP (which costs real API calls).

## Module Responsibilities
- `main.py` — CLI entry point, argparse, orchestration
- `src/__init__.py` — Package init (can be empty)
- `src/discovery.py` — Recursively find all email files in maildir
- `src/parser.py` — Parse RFC 2822 files, extract mandatory + optional fields
- `src/database.py` — Create schema, insert emails + recipients, query helpers
- `src/dedup.py` — Duplicate detection: group → fuzzy match → flag → report
- `src/notifier.py` — Generate .eml drafts, send via MCP, log sends
- `src/dashboard.py` — Flask dashboard (single-file, full-featured — see docs/UI.md)

## Critical Design Decisions
1. **Normalization:** `email_recipients` table for to/cc/bcc (not comma-separated strings in emails table)
2. **Dedup grouping:** Group by `(lowercase(from_address), normalized_subject)` THEN fuzzy-match body within group
3. **Subject normalization:** Strip `Re:`, `Fwd:`, `FW:`, `RE:`, `Fw:` (case-insensitive, repeated) → strip whitespace → lowercase. For comparison only; DB stores original.
4. **Body matching:** Compare primary body only (excluding forwarded_content and quoted_content)
5. **Fuzzy metric:** `rapidfuzz.fuzz.ratio` ≥ 90%
6. **Earliest = original:** In duplicate group, earliest UTC timestamp keeps `is_duplicate = false`. All others flagged. Ties broken by lexicographic message_id.
7. **Dates:** All stored as UTC ISO-8601. `python-dateutil` handles PST/EST/CDT/offset formats.
8. **Email addresses:** Lowercase, trimmed, display names stripped. `"Ken Lay <klay@enron.com>"` → `"klay@enron.com"`
9. **Parse failures:** Missing mandatory field (message_id, date, from_address, to_addresses, subject) → log to `error_log.txt`, skip insert. Empty body is NOT a failure.
10. **Live send safety:** `--send-live` requires `--notify-address` to override recipient. Never sends to actual Enron addresses.

## Coding Standards

### Python Style
- **Formatter:** `ruff format` (or `black`). Line length 100.
- **Linter:** `ruff check`. Zero warnings before commit.
- **Imports:** stdlib → third-party → local, separated by blank lines. Use `from __future__ import annotations` at top of every file.
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes/dataclasses, `UPPER_CASE` for module-level constants.
- **Paths:** Always use `pathlib.Path`, never raw `os.path` strings.
- **Files/DB:** Always use `with` context managers.
- **UTC:** Use `datetime.datetime.now(datetime.UTC)`, never naive `datetime.now()`.

### Type Hints & Dataclasses
All function signatures typed. Structured return types as dataclasses:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ParsedEmail:
    """Structured representation of a parsed email."""
    message_id: str
    date: datetime
    from_address: str
    to_addresses: list[str]
    subject: str
    body: str
    source_file: str
    cc_addresses: list[str] = field(default_factory=list)
    bcc_addresses: list[str] = field(default_factory=list)
    x_from: str | None = None
    x_to: str | None = None
    x_cc: str | None = None
    x_bcc: str | None = None
    x_folder: str | None = None
    x_origin: str | None = None
    content_type: str | None = None
    has_attachment: bool = False
    forwarded_content: str | None = None
    quoted_content: str | None = None
    headings: str | None = None

@dataclass
class DuplicateGroup:
    """A group of duplicate emails."""
    original_message_id: str
    original_date: datetime
    duplicate_message_ids: list[str]
    subject: str
    from_address: str
    similarity_scores: dict[str, float] = field(default_factory=dict)
```

### Docstrings
Google-style on every public function:

```python
def parse_email(file_path: Path) -> ParsedEmail | None:
    """Parse a raw RFC 2822 email file and extract structured fields.

    Args:
        file_path: Path to the raw email file, relative to maildir root.

    Returns:
        ParsedEmail dataclass with all extracted fields, or None if
        mandatory fields could not be extracted (failure logged).
    """
```

### Error Handling Pattern
Every module follows this — never crash, always log:

```python
import logging

logger = logging.getLogger(__name__)

def parse_email(file_path: Path) -> ParsedEmail | None:
    try:
        # ... parsing logic ...
    except UnicodeDecodeError as e:
        logger.error("%s | DECODE_ERROR | %s", file_path, e)
        return None
    except Exception as e:
        logger.error("%s | UNEXPECTED_ERROR | %s", file_path, e)
        return None
```

### Logging Setup (in main.py)
```python
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")

file_handler = logging.FileHandler("error_log.txt", mode="w")
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
))
logging.getLogger().addHandler(file_handler)
```

### Database Pattern
```python
import sqlite3

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn

# Always parameterized queries — never f-strings
conn.execute("INSERT OR IGNORE INTO emails (...) VALUES (?, ?, ...)", (val1, val2, ...))

# Batch insert recipients
conn.executemany(
    "INSERT INTO email_recipients (email_message_id, address, recipient_type) VALUES (?, ?, ?)",
    [(msg_id, addr, rtype) for addr in addresses]
)
```

### Progress Reporting
For long operations (10K+ emails):
```python
for i, file_path in enumerate(email_files, 1):
    if i % 500 == 0:
        print(f"  Parsed {i}/{total} emails...", file=sys.stderr)
```

### Constants
Define at module top, not scattered through code:
```python
SIMILARITY_THRESHOLD = 90
SUBJECT_PREFIX_PATTERN = re.compile(r'^(re|fwd|fw)\s*:\s*', re.IGNORECASE)
FORWARD_MARKERS = [
    "-----Original Message-----",
    "---------- Forwarded message ----------",
    "---------------------- Forwarded by",
]
```

## Notification Email Template
The assignment specifies an exact template. Use verbatim:

```
To: <sender_of_latest_duplicate>
Subject: [Duplicate Notice] Re: <original_subject>
Date: <current_timestamp>
References: <message_id_of_latest_duplicate>

This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  <message_id_of_latest_duplicate>
    Date Sent:   <date_of_latest_duplicate>
    Subject:     <subject>

  Original Email on Record:
    Message-ID:  <message_id_of_earliest_original>
    Date Sent:   <date_of_earliest_original>

  Similarity Score: <similarity_percentage>%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
```

## Output File Formats

### error_log.txt
```
2026-04-20T14:30:00Z | maildir/lay-k/inbox/45 | MISSING_FIELD:message_id | No Message-ID header found
2026-04-20T14:30:00Z | maildir/lay-k/sent/12 | PARSE_ERROR:date | Could not parse: "Octember 35, 2001"
```

### duplicates_report.csv
```csv
duplicate_message_id,original_message_id,subject,from_address,duplicate_date,original_date,similarity_score
```

### output/send_log.csv
```csv
timestamp,recipient,subject,status,error
```

### Pipeline Stats Output (stdout, end of run)
```
=== Pipeline Summary ===
Files discovered:    12,450
Successfully parsed: 11,823
Parse failures:         627
Emails in database:  11,823
Duplicate groups:       342
Emails flagged:         891
Notifications generated: 342
Notifications sent:       0 (dry-run mode)
```

## Conventions
- All timestamps: UTC ISO-8601
- All email addresses: lowercase, trimmed before storage and comparison
- Error log format: `TIMESTAMP | SOURCE_FILE | ERROR_TYPE | DETAIL`
- Docstrings: Google-style on every public function
- Type hints on all function signatures
- Dataclasses for structured types (`ParsedEmail`, `DuplicateGroup`)
- Commits: conventional commits (`feat(parser):`, `fix(dedup):`, `test(parser):`)
- Use `pathlib.Path` everywhere, never raw string paths
- Use `with` statements for all file/DB operations
- Constants at module top, not magic values in code

## Do Not
- Commit `data/maildir/`, `enron.db`, `mcp_config.json` (real creds), or `.env`
- Use paid/proprietary libraries
- Hardcode absolute paths
- Crash on malformed input — catch, log, skip
- Over-normalize the schema (no separate senders or subjects table)
- Build the dashboard before real data validation (Phase 6) — it needs a populated DB
- Use `fuzzywuzzy` (GPL dependency via python-Levenshtein) — use `rapidfuzz` instead
- Use `print()` for errors — use `logging` module
- Write SQL with f-strings — always parameterized queries
- Skip type hints or docstrings
- Run the full pipeline without unit tests passing first
- Use `os.path` — use `pathlib` instead
- Use naive `datetime.now()` — use `datetime.now(datetime.UTC)`
- Generate code without reading the relevant SRS section first

## Deliverable Checklist
- [ ] Source code (`main.py`, `src/`)
- [ ] `README.md` — setup, architecture, how to run
- [ ] `AI_USAGE.md` — prompting strategy, iterations, MCP section, screenshots
- [ ] `schema.sql` — complete DDL with is_duplicate, duplicate_of, notification_sent, notification_date
- [ ] `sample_queries.sql` — 5 queries with expected output comments
- [ ] `mcp_config.json.example` — template with placeholder credentials
- [ ] `output/replies/` — draft .eml files for flagged duplicates
- [ ] `output/send_log.csv` — live send log (timestamp, recipient, subject, status, error)
- [ ] `duplicates_report.csv` — all duplicate groups with similarity scores
- [ ] `error_log.txt` — all parse failures with paths and reasons
- [ ] `requirements.txt` — all Python dependencies (including dev deps like pytest, pytest-cov)
- [ ] `tests/` — pytest suite with ≥80% coverage target
- [ ] `.gitignore` — data/, *.db, .env, mcp_config.json, __pycache__/

## Testing Quick Reference
See `docs/TESTING.md` for full details. Key points:
- Fixtures in `tests/fixtures/` (valid emails, malformed emails, duplicate pairs)
- `test_parser.py` is the heaviest — covers all edge cases
- Integration test runs full pipeline on fixture data
- `pytest tests/ -v` must pass before any deliverable is final
- Dev dependencies: `pytest`, `pytest-cov`, `pytest-timeout`

## requirements.txt (reference)
```
python-dateutil>=2.8
rapidfuzz>=3.0
flask>=3.0

# Dev dependencies
pytest>=7.0
pytest-cov>=4.0
pytest-timeout>=2.0
ruff>=0.4
```
