# SRS.md — Software Requirements Specification
## Enron Email Data Extraction & Notification Pipeline

**Version:** 1.0
**Date:** 2026-04-20
**Status:** Draft

---

## 1. Purpose

Build a Python CLI pipeline that ingests raw Enron email files, extracts structured data into SQLite, detects near-duplicate emails via fuzzy matching, and sends automated notification emails via a Gmail MCP server. An optional local web dashboard provides visual access to pipeline results.

---

## 2. Scope

### In Scope
- Parse a subset of the Enron email dataset (≥5 mailboxes, ≥10,000 emails)
- Extract mandatory + optional fields per the field definitions (Section 3 of assignment)
- Store in a normalized SQLite database
- Detect duplicates (same sender + normalized subject + ≥90% body similarity)
- Flag duplicates in the DB, generate CSV report
- Generate draft .eml notification files (dry-run)
- Send notifications via Gmail MCP (live mode)
- Error logging, stats reporting
- Optional: local web dashboard for browsing results

### Out of Scope
- Processing the full 500K+ email dataset
- NLP/ML-based classification of email content
- Real-time or streaming ingestion
- Multi-user authentication for the dashboard
- Deployment to any cloud or production environment

---

## 3. Functional Requirements

### FR-1: Email Discovery
- **FR-1.1:** Recursively traverse `data/maildir/<employee>/<folder>/` to discover all email files.
- **FR-1.2:** Skip non-email files (directories, `.` files, binary files).
- **FR-1.3:** Report total files discovered before parsing begins.

### FR-2: Email Parsing
- **FR-2.1:** Parse each file using Python's `email` stdlib (RFC 2822).
- **FR-2.2:** Extract all mandatory fields: `message_id`, `date`, `from_address`, `to_addresses`, `subject`, `body`, `source_file`.
- **FR-2.3:** Extract all optional fields when present: `cc_addresses`, `bcc_addresses`, `x_from`, `x_to`, `x_cc`, `x_bcc`, `x_folder`, `x_origin`, `content_type`, `has_attachment`, `forwarded_content`, `quoted_content`, `headings`.
- **FR-2.4:** Normalize dates to UTC using `python-dateutil`.
- **FR-2.5:** Extract email addresses only (strip display names) for `from_address`, `to_addresses`, `cc_addresses`, `bcc_addresses`.
- **FR-2.6:** Separate primary body from forwarded content (markers: `-----Original Message-----`, `---------- Forwarded message ----------`, `---------------------- Forwarded by`) and quoted content (lines starting with `>`).
- **FR-2.7:** Detect `has_attachment` from Content-Type, MIME boundaries, `<<filename>>` patterns, or body keywords.
- **FR-2.8:** Extract headings: ALL CAPS lines, lines ending with `:`, HTML heading tags.
- **FR-2.9:** If any mandatory field (except empty body) cannot be extracted, log to `error_log.txt` with file path and reason. Do not insert into DB.
- **FR-2.10:** Never crash on malformed input — catch all exceptions, log, skip.

### FR-3: Database Storage
- **FR-3.1:** Create SQLite database `enron.db` with schema from `schema.sql`.
- **FR-3.2:** `emails` table: one row per email, all scalar fields + `is_duplicate BOOLEAN DEFAULT FALSE`, `duplicate_of TEXT`, `notification_sent BOOLEAN DEFAULT FALSE`, `notification_date DATETIME`.
- **FR-3.3:** `email_recipients` table: `(id, email_message_id, address, recipient_type)` where `recipient_type` ∈ {`to`, `cc`, `bcc`}.
- **FR-3.4:** UNIQUE constraint on `emails.message_id` — skip on conflict (do not overwrite).
- **FR-3.5:** Indexes on `emails.date`, `emails.from_address`, `emails.subject`.
- **FR-3.6:** Index on `email_recipients.address` for join performance.
- **FR-3.7:** Foreign key from `email_recipients.email_message_id` → `emails.message_id`.

### FR-4: Duplicate Detection
- **FR-4.1:** After ingestion, group emails by `(lowercase(from_address), normalized_subject)`.
- **FR-4.2:** Subject normalization: strip leading `Re:`, `Fwd:`, `FW:`, `RE:`, `Fw:`, `re:`, `fwd:` (case-insensitive, repeated), then strip whitespace, then lowercase.
- **FR-4.3:** Within each group, compare body content (primary body only, excluding quoted/forwarded) using `rapidfuzz.fuzz.ratio`.
- **FR-4.4:** If similarity ≥ 90%, flag as duplicates.
- **FR-4.5:** In each duplicate group, the email with the earliest UTC date is the "original." All others are flagged: `is_duplicate = true`, `duplicate_of = <original_message_id>`.
- **FR-4.6:** If dates are identical, use lexicographic message_id as tiebreaker (earliest = original).
- **FR-4.7:** Generate `duplicates_report.csv` with columns: `duplicate_message_id`, `original_message_id`, `subject`, `from_address`, `duplicate_date`, `original_date`, `similarity_score`.
- **FR-4.8:** Log stats: total duplicate groups, total emails flagged, average group size.

### FR-5: Notification Emails
- **FR-5.1:** For each duplicate group, generate a notification email for the latest flagged duplicate.
- **FR-5.2:** Notification follows the exact template from assignment Section 4.2.
- **FR-5.3:** Dry-run (default): write `.eml` files to `output/replies/`.
- **FR-5.4:** Live mode (`--send-live`): send via Gmail MCP `send_email` tool. Requires `--notify-address` to override recipient (safety — never send to Enron addresses).
- **FR-5.5:** Log all sends to `output/send_log.csv`: `timestamp`, `recipient`, `subject`, `status`, `error`.
- **FR-5.6:** After successful send, update DB: `notification_sent = true`, `notification_date = <now UTC>`.

### FR-6: CLI Interface
- **FR-6.1:** `python main.py` — full pipeline, dry-run mode.
- **FR-6.2:** `python main.py --send-live --notify-address user@gmail.com` — pipeline + live send.
- **FR-6.3:** `python main.py --dashboard` — after pipeline, launch local dashboard.
- **FR-6.4:** `python main.py --maildir path/to/maildir` — custom data path (default: `data/maildir`).
- **FR-6.5:** `python main.py --db path/to/db` — custom DB path (default: `enron.db`).
- **FR-6.6:** Print summary stats to stdout at end of run.

### FR-7: Dashboard (Optional)
- **FR-7.1:** Serve a single-page web dashboard on `localhost:8050`.
- **FR-7.2:** Show pipeline stats: total parsed, failed, duplicates found, notifications sent.
- **FR-7.3:** Table of duplicate groups with similarity scores, expandable details.
- **FR-7.4:** Table of parse errors.
- **FR-7.5:** Notification send log.
- **FR-7.6:** Read-only — no mutations from the dashboard.
- **FR-7.7:** Basic search/filter on sender, subject, date range.

---

## 4. Non-Functional Requirements

### NFR-1: Performance
- Parse 10,000 emails in under 5 minutes on a standard laptop.
- Duplicate detection (including fuzzy matching) in under 2 minutes for 10K emails.

### NFR-2: Error Resilience
- Pipeline must never crash on malformed input.
- All exceptions caught, logged to `error_log.txt`, and skipped.
- Partial runs should still produce valid output for successfully parsed emails.

### NFR-3: Reproducibility
- Single command execution (`python main.py`).
- All dependencies in `requirements.txt`.
- No paid/proprietary libraries.
- Python 3.10+.

### NFR-4: Portability
- SQLite (no server required).
- Works on macOS, Linux, Windows.
- No hardcoded absolute paths.

### NFR-5: Data Integrity
- UTC normalization for all timestamps.
- Email addresses lowercased and trimmed before storage.
- UNIQUE constraint on message_id prevents duplicate inserts.
- Foreign key integrity between emails ↔ email_recipients.

---

## 5. Data Model

```
┌─────────────────────────────────┐
│            emails                │
├─────────────────────────────────┤
│ message_id TEXT PK UNIQUE       │
│ date DATETIME NOT NULL          │
│ from_address TEXT NOT NULL      │
│ subject TEXT NOT NULL            │
│ body TEXT                        │
│ source_file TEXT NOT NULL        │
│ x_from TEXT                      │
│ x_to TEXT                        │
│ x_cc TEXT                        │
│ x_bcc TEXT                       │
│ x_folder TEXT                    │
│ x_origin TEXT                    │
│ content_type TEXT                │
│ has_attachment BOOLEAN           │
│ forwarded_content TEXT           │
│ quoted_content TEXT              │
│ headings TEXT                    │
│ is_duplicate BOOLEAN DEFAULT 0   │
│ duplicate_of TEXT                │
│ notification_sent BOOLEAN DEF 0  │
│ notification_date DATETIME       │
├─────────────────────────────────┤
│ IDX: date, from_address, subject │
│ FK: duplicate_of → emails.msg_id │
└──────────────┬──────────────────┘
               │ 1:N
┌──────────────┴──────────────────┐
│        email_recipients          │
├─────────────────────────────────┤
│ id INTEGER PK AUTOINCREMENT     │
│ email_message_id TEXT NOT NULL   │
│ address TEXT NOT NULL             │
│ recipient_type TEXT NOT NULL      │
│   CHECK(type IN ('to','cc','bcc'))│
├─────────────────────────────────┤
│ IDX: address                      │
│ IDX: email_message_id             │
│ FK: email_message_id → emails     │
└─────────────────────────────────┘
```

---

## 6. Module Structure

```
enron-email-pipeline/
├── main.py                  # CLI entry point, orchestrates pipeline
├── src/
│   ├── __init__.py
│   ├── discovery.py         # FR-1: file discovery/traversal
│   ├── parser.py            # FR-2: email parsing & field extraction
│   ├── database.py          # FR-3: schema creation, inserts, queries
│   ├── dedup.py             # FR-4: duplicate detection & flagging
│   ├── notifier.py          # FR-5: notification generation & sending
│   └── dashboard.py         # FR-7: optional web dashboard
├── tests/                   # Unit + integration tests
├── docs/                    # Internal project docs (not graded deliverables)
│   ├── SRS.md               # Software requirements specification
│   ├── TESTING.md           # Test strategy & plan
│   └── UI.md                # Optional dashboard spec
├── data/maildir/            # Raw email data (gitignored)
├── output/
│   ├── replies/             # Draft .eml files
│   └── send_log.csv         # Live send log
├── schema.sql               # DB schema (deliverable)
├── sample_queries.sql        # Demo queries (deliverable)
├── requirements.txt         # Python deps (deliverable)
├── mcp_config.json.example  # MCP config template (deliverable)
├── .claude/                 # Claude Code project config
├── CLAUDE.md                # Claude Code auto-loaded context
├── README.md                # Setup & architecture (deliverable)
├── AI_USAGE.md              # AI tool documentation (deliverable)
├── duplicates_report.csv    # Generated by pipeline
└── error_log.txt            # Generated by pipeline
```

---

## 7. External Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `python-dateutil` | ≥2.8 | Timezone-aware date parsing |
| `rapidfuzz` | ≥3.0 | Fast fuzzy string matching |
| `flask` | ≥3.0 | Optional dashboard server |
| (stdlib) `email` | — | RFC 2822 email parsing |
| (stdlib) `sqlite3` | — | Database |
| (stdlib) `csv` | — | Report generation |
| (stdlib) `argparse` | — | CLI argument parsing |
| (stdlib) `logging` | — | Structured error logging |
| (stdlib) `pathlib` | — | File path handling |

---

## 8. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | ≥10,000 emails parsed from ≥5 mailboxes | Stats output shows counts |
| AC-2 | All mandatory fields extracted or failure logged | `error_log.txt` covers all failures |
| AC-3 | DB schema matches spec (normalized, indexed, dedup columns) | `schema.sql` review |
| AC-4 | No duplicate message_ids in DB | `SELECT COUNT(*) = COUNT(DISTINCT message_id)` |
| AC-5 | Duplicate groups correctly identified (≥90% similarity) | `duplicates_report.csv` spot checks |
| AC-6 | Earliest email is original, latest is flagged | Query verification |
| AC-7 | Draft .eml files generated for all flagged duplicates | `output/replies/` file count matches flagged count |
| AC-8 | Live send works with MCP (at least 1 successful send) | Screenshot/log in `AI_USAGE.md` |
| AC-9 | Pipeline runs with single command | `python main.py` exits 0 |
| AC-10 | Pipeline never crashes on malformed input | Feed garbage files, check graceful handling |
