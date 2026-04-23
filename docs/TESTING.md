# TESTING.md — Test Strategy & Plan
## Enron Email Data Extraction Pipeline

---

## 1. Test Philosophy

Every module gets unit tests. The pipeline gets integration tests. We use `pytest` with no heavy fixtures — the test data is small, hand-crafted email files that exercise specific edge cases.

**Test command:** `pytest tests/ -v`

**Coverage target:** ≥80% line coverage on `src/` modules. Run with `pytest --cov=src tests/`.

---

## 2. Test Structure

```
tests/
├── conftest.py               # Shared fixtures (temp dirs, sample DB, sample emails)
├── test_discovery.py          # FR-1: file traversal
├── test_parser.py             # FR-2: email parsing (heaviest test file)
├── test_database.py           # FR-3: schema, inserts, constraints
├── test_dedup.py              # FR-4: duplicate detection logic
├── test_notifier.py           # FR-5: notification generation
├── test_integration.py        # End-to-end pipeline runs
└── fixtures/
    ├── valid/                 # Well-formed sample emails
    │   ├── simple.txt         # Minimal valid email
    │   ├── full_headers.txt   # All optional fields present
    │   ├── multiline_to.txt   # Continuation headers
    │   ├── forwarded.txt      # Contains forwarded message markers
    │   ├── quoted.txt         # Contains > quoted lines
    │   ├── attachref.txt      # References <<filename.xls>>
    │   └── html_body.txt      # HTML content type email
    ├── malformed/             # Edge cases that must not crash
    │   ├── no_message_id.txt
    │   ├── no_date.txt
    │   ├── bad_date.txt       # Unparseable date string
    │   ├── no_to.txt          # Missing To field
    │   ├── no_subject.txt
    │   ├── encoding_latin1.txt
    │   ├── binary_garbage.bin
    │   ├── empty_file.txt
    │   └── truncated.txt      # File cut off mid-header
    └── duplicates/            # Pairs/groups for dedup testing
        ├── original.txt
        ├── exact_copy.txt     # 100% body match
        ├── near_copy.txt      # ~95% body match
        ├── below_threshold.txt # ~85% body match (should NOT flag)
        └── different_sender.txt # Same subject+body, different from
```

---

## 3. Unit Tests by Module

### 3.1 test_discovery.py

| Test | Input | Expected |
|------|-------|----------|
| `test_finds_all_files` | Temp dir with 5 nested email files | Returns 5 paths |
| `test_skips_hidden_files` | Dir with `.hidden` file | Excluded from results |
| `test_skips_directories` | Dir with a subdir named like a file | Not returned |
| `test_empty_mailbox` | Empty directory | Returns empty list, no crash |
| `test_relative_paths` | Any structure | All returned paths are relative to maildir root |

### 3.2 test_parser.py (most comprehensive)

**Valid parsing:**

| Test | What it validates |
|------|------------------|
| `test_parse_simple_email` | All 7 mandatory fields extracted correctly |
| `test_parse_all_optional_fields` | All optional fields populated when present |
| `test_date_utc_conversion_pst` | `"Mon, 14 May 2001 09:00:00 -0700"` → UTC `2001-05-14T16:00:00Z` |
| `test_date_utc_conversion_est` | EST → UTC (+5 hours) |
| `test_date_utc_conversion_cdt` | CDT → UTC (+5 hours) |
| `test_date_with_named_tz` | `"PST"` abbreviation handled |
| `test_from_address_strip_display_name` | `"Ken Lay <klay@enron.com>"` → `"klay@enron.com"` |
| `test_to_addresses_comma_separated` | `"a@b.com, c@d.com"` → `["a@b.com", "c@d.com"]` |
| `test_to_addresses_multiline` | Continuation lines (leading whitespace) → single list |
| `test_to_addresses_mixed_formats` | Mix of `name <addr>` and bare addresses |
| `test_subject_preserved_prefixes` | `"Re: Fwd: Meeting"` stored verbatim (not normalized in storage) |
| `test_body_extraction` | Body text correctly isolated |
| `test_forwarded_content_separated` | Content after `-----Original Message-----` in `forwarded_content` |
| `test_forwarded_by_marker` | `---------------------- Forwarded by` handled |
| `test_quoted_content_separated` | `>` lines in `quoted_content` |
| `test_headings_allcaps` | `"MEETING AGENDA"` detected as heading |
| `test_headings_colon_suffix` | `"Action Items:"` detected |
| `test_has_attachment_content_type` | `Content-Type: multipart/mixed` → `True` |
| `test_has_attachment_angle_brackets` | `<<report.xls>>` in body → `True` |
| `test_has_attachment_none` | Plain email → `False` |
| `test_x_headers_extracted` | X-From, X-To, X-cc, X-bcc, X-Folder, X-Origin |

**Malformed input handling (must NOT crash):**

| Test | Input | Expected |
|------|-------|----------|
| `test_missing_message_id` | Email without Message-ID | Returns `None` + error log entry |
| `test_missing_date` | No Date header | Returns `None` + error log |
| `test_unparseable_date` | `"Date: not-a-date"` | Returns `None` + error log |
| `test_missing_to` | No To header | Returns `None` + error log |
| `test_missing_subject` | No Subject header | Returns `None` + error log |
| `test_encoding_latin1` | Latin-1 encoded file | Parses without crash, best-effort decode |
| `test_binary_file` | Random bytes | Returns `None` + error log, no crash |
| `test_empty_file` | 0 bytes | Returns `None` + error log |
| `test_truncated_file` | Cut off mid-header | Returns `None` + error log |

### 3.3 test_database.py

| Test | What it validates |
|------|------------------|
| `test_create_schema` | Tables `emails` and `email_recipients` exist with correct columns |
| `test_insert_email` | Insert succeeds, all fields retrievable |
| `test_insert_recipients` | to/cc/bcc stored in `email_recipients` with correct types |
| `test_unique_message_id` | Second insert with same message_id is skipped (no error) |
| `test_indexes_exist` | Indexes on `date`, `from_address`, `subject`, `address` |
| `test_dedup_columns_exist` | `is_duplicate`, `duplicate_of`, `notification_sent`, `notification_date` columns present |
| `test_foreign_key_integrity` | `email_recipients.email_message_id` references valid `emails.message_id` |
| `test_sample_queries_run` | All 5 sample queries from `sample_queries.sql` execute without error |

### 3.4 test_dedup.py

| Test | What it validates |
|------|------------------|
| `test_subject_normalization` | `"Re: Re: Fwd: FW: Hello"` → `"hello"` |
| `test_subject_normalization_no_prefix` | `"Hello World"` → `"hello world"` |
| `test_exact_duplicate_detected` | Two emails with identical body → flagged, score = 100 |
| `test_near_duplicate_detected` | ~95% similar body → flagged |
| `test_below_threshold_not_flagged` | ~85% similar body → NOT flagged |
| `test_different_sender_not_duplicate` | Same subject+body, different from_address → NOT grouped |
| `test_earliest_is_original` | Group of 3: earliest date gets `is_duplicate = False` |
| `test_latest_is_duplicate` | Latest by UTC date gets `is_duplicate = True`, `duplicate_of` set |
| `test_identical_dates_tiebreaker` | Same timestamp → lexicographic message_id tiebreaker |
| `test_group_of_three` | 3 duplicates: 1 original, 2 flagged, all `duplicate_of` points to original |
| `test_csv_report_generated` | `duplicates_report.csv` has correct columns and row count |
| `test_stats_logged` | Stats output includes group count, flagged count, avg size |
| `test_empty_body_handling` | Two emails with empty bodies + same sender/subject: should they match? Decision: yes (100% similarity on empty strings). Test this explicitly. |

### 3.5 test_notifier.py

| Test | What it validates |
|------|------------------|
| `test_generate_eml_file` | .eml file created with correct template fields |
| `test_eml_template_fields` | Subject, References, message IDs, dates, similarity score all present |
| `test_eml_per_duplicate_group` | One .eml per group (for the latest duplicate) |
| `test_send_log_csv_format` | `send_log.csv` has correct columns |
| `test_dry_run_no_send` | Without `--send-live`, no MCP calls made |
| `test_db_updated_after_send` | After send, `notification_sent = True` and `notification_date` set |

---

## 4. Integration Tests (test_integration.py)

| Test | Scenario |
|------|----------|
| `test_full_pipeline_small` | Run entire pipeline on `fixtures/valid/` + `fixtures/duplicates/` (8–10 files). Verify: DB populated, duplicates flagged, report generated, .eml files created, error log exists. |
| `test_pipeline_with_malformed` | Mix valid + malformed files. Verify: valid emails in DB, malformed in error log, pipeline exits 0. |
| `test_pipeline_idempotent` | Run pipeline twice on same data. Verify: no extra rows in DB (unique constraint), no duplicate report entries change. |
| `test_pipeline_stats_output` | Capture stdout, verify stats format: "Total: X, Parsed: Y, Failed: Z, Duplicates: W". |

---

## 5. Test Fixtures — Sample Email Templates

### Minimal Valid Email (`fixtures/valid/simple.txt`)
```
Message-ID: <TEST001@example.com>
Date: Mon, 14 May 2001 09:00:00 -0700 (PDT)
From: sender@enron.com
To: recipient@enron.com
Subject: Test Email
X-Folder: \Inbox

This is the body of a test email.
```

### Exact Duplicate (`fixtures/duplicates/exact_copy.txt`)
```
Message-ID: <TEST002@example.com>
Date: Tue, 15 May 2001 09:00:00 -0700 (PDT)
From: sender@enron.com
To: recipient@enron.com
Subject: Re: Test Email

This is the body of a test email.
```
(Same sender, normalized subject matches, identical body → should be flagged as duplicate of TEST001)

### Near Duplicate (`fixtures/duplicates/near_copy.txt`)
```
Message-ID: <TEST003@example.com>
Date: Wed, 16 May 2001 09:00:00 -0700 (PDT)
From: sender@enron.com
To: recipient@enron.com
Subject: Fwd: Test Email

This is the body of a test email. (Sent again with minor edits.)
```
(~93% similar body → should flag)

### Below Threshold (`fixtures/duplicates/below_threshold.txt`)
```
Message-ID: <TEST004@example.com>
Date: Thu, 17 May 2001 09:00:00 -0700 (PDT)
From: sender@enron.com
To: recipient@enron.com
Subject: Re: Test Email

This is a completely rewritten email about a different topic entirely. No similarity to the original.
```
(~30% similar → should NOT flag)

---

## 6. Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Specific module
pytest tests/test_parser.py -v

# Only integration tests
pytest tests/test_integration.py -v

# Quick smoke test (just check nothing crashes)
pytest tests/ -x --timeout=30
```

---

## 7. CI Considerations

Not required by the assignment, but if added:
- Run `pytest tests/ --cov=src` on every push
- Fail if coverage drops below 80%
- Lint with `ruff check src/ tests/`
- Type check with `mypy src/` (optional)
