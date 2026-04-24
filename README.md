# Enron Email Data Extraction & Notification Pipeline

A Python CLI pipeline that ingests raw Enron email files (RFC 2822), extracts structured fields into SQLite, detects near-duplicate emails via fuzzy matching, and sends automated notification emails via a Gmail MCP server. Includes a local web dashboard for exploring results.

## Architecture

```
main.py                  CLI entry point, orchestrates pipeline
src/
  discovery.py           Recursive file traversal (handles Windows trailing-dot filenames)
  parser.py              RFC 2822 parsing, UTC normalization, field extraction
  database.py            SQLite schema creation, insert, query functions
  dedup.py               Duplicate detection: group by sender+subject, fuzzy match body
  notifier.py            .eml draft generation, Gmail MCP live sending
  dashboard.py           Single-file Flask dashboard (7 sections, embedded HTML/CSS/JS)
```

## Pipeline Results (Real Data)

| Metric | Count |
|--------|-------|
| Files discovered | 92,126 |
| Successfully parsed | 85,258 |
| Parse failures | 6,868 |
| Emails in database | 85,258 |
| Duplicate groups | 19,178 |
| Emails flagged | 43,363 |
| Notifications generated | 19,178 |

**Mailboxes processed:** lay-k, skilling-j, kaminski-v, dasovich-j, kean-s

## Setup

### Prerequisites
- Python 3.10+
- The Enron email dataset (maildir format) in `data/maildir/`

### Installation

```bash
# Clone the repository
git clone https://github.com/RiteshYennuwar/email_automation.git
cd email_automation

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt
```

### Download Dataset

Download the Enron email dataset and extract to `data/maildir/`:

```bash
# The dataset should have structure: data/maildir/<employee>/<folder>/<files>
# Example: data/maildir/lay-k/inbox/1.
```

## CLI Reference

```bash
# Full pipeline (dry-run mode - generates .eml drafts, no live sending)
python main.py

# Custom data path
python main.py --maildir path/to/maildir

# Custom database path
python main.py --db path/to/database.db

# Pipeline + launch web dashboard on localhost:8050
python main.py --dashboard

# Pipeline + live send notifications via Gmail MCP
python main.py --send-live --notify-address your@gmail.com
```

## Output Files

| File | Description |
|------|-------------|
| `enron.db` | SQLite database with all parsed emails and recipients |
| `error_log.txt` | Parse failures with file paths and reasons |
| `duplicates_report.csv` | All duplicate pairs with similarity scores |
| `output/replies/*.eml` | Draft notification emails (one per duplicate group) |
| `output/send_log.csv` | Live send log (timestamp, recipient, status, error) |

## Database Schema

Two tables with normalized recipients:

- `emails` - One row per email with all scalar fields + dedup columns
- `email_recipients` - Junction table for to/cc/bcc addresses

Key design decisions:
- UNIQUE constraint on message_id (skip on conflict)
- Indexes on date, from_address, subject, recipient address
- Foreign key from email_recipients to emails
- Dedup columns: is_duplicate, duplicate_of, notification_sent, notification_date

## Duplicate Detection

1. Group emails by `(lowercase(from_address), normalized_subject)`
2. Subject normalization: strip Re:/Fwd:/FW: prefixes (repeated), strip whitespace, lowercase
3. Within each group, compare primary body text using `rapidfuzz.fuzz.ratio`
4. Threshold: >= 90% similarity flags as duplicate
5. Earliest email by UTC date is the "original"; ties broken by lexicographic message_id

## Dashboard

Launch with `python main.py --dashboard` (serves on `localhost:8050`).

Seven sections:
- **Overview**: Pipeline stats + charts (emails per mailbox, timeline)
- **Email Explorer**: Paginated table with search, filters, sort, detail panel
- **Duplicates**: Group management with side-by-side diff view, confirm/reject
- **Analytics**: Top senders/recipients, activity heatmap
- **Errors**: Filterable error log with type distribution
- **Notifications**: Draft preview and send actions
- **Operations**: DB info, export downloads, schema viewer

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Specific module
pytest tests/test_parser.py -v
```

68 tests covering: database operations, file discovery, email parsing (valid + malformed), duplicate detection, notification generation, and end-to-end integration.

## MCP Setup

### Gmail MCP (for live notifications)

1. Place `gcp-oauth.keys.json` in `~/.gmail-mcp/`
2. Run: `npx @gongrzhe/server-gmail-autoauth-mcp auth`
3. Use `--send-live --notify-address your@gmail.com` flag

### SQLite MCP (for development)

Configured in `.mcp.json` - lets Claude Code inspect the database during development.

See `mcp_config.json.example` for the configuration template.

## Sample Queries

```bash
sqlite3 enron.db < sample_queries.sql
```

Includes queries for: summary stats, top senders, monthly volume, largest duplicate groups, and most-emailed recipients.

## Tech Stack

- Python 3.10+ with stdlib `email`, `sqlite3`, `csv`, `argparse`, `logging`, `pathlib`
- `python-dateutil` for timezone-aware date parsing
- `rapidfuzz` for fuzzy string matching (MIT, C++ backend)
- `flask` for the web dashboard
- Gmail MCP server for live notifications
