-- Sample Queries for the Enron Email Pipeline Database
-- Run with: sqlite3 enron.db < sample_queries.sql

-- Query 1: Total emails and duplicates summary
-- Expected: ~85,258 total emails, ~43,363 duplicates
SELECT
    COUNT(*) AS total_emails,
    SUM(CASE WHEN is_duplicate = 1 THEN 1 ELSE 0 END) AS duplicates,
    SUM(CASE WHEN is_duplicate = 0 THEN 1 ELSE 0 END) AS originals,
    ROUND(100.0 * SUM(CASE WHEN is_duplicate = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS duplicate_pct
FROM emails;

-- Query 2: Top 10 senders by email count
-- Expected: Enron employees with high email volumes (kaminski, dasovich, kean, etc.)
SELECT
    from_address,
    COUNT(*) AS email_count,
    SUM(CASE WHEN is_duplicate = 1 THEN 1 ELSE 0 END) AS duplicates
FROM emails
GROUP BY from_address
ORDER BY email_count DESC
LIMIT 10;

-- Query 3: Email volume by month (top 10 months)
-- Expected: Peak activity around 2000-2001
SELECT
    strftime('%Y-%m', date) AS month,
    COUNT(*) AS email_count
FROM emails
GROUP BY month
ORDER BY email_count DESC
LIMIT 10;

-- Query 4: Duplicate groups with highest similarity scores
-- Expected: Groups with 100% similarity (exact copies)
SELECT
    e.duplicate_of AS original_id,
    COUNT(*) AS group_size,
    orig.subject AS original_subject,
    orig.from_address
FROM emails e
JOIN emails orig ON e.duplicate_of = orig.message_id
WHERE e.is_duplicate = 1
GROUP BY e.duplicate_of
ORDER BY group_size DESC
LIMIT 10;

-- Query 5: Recipients who received the most emails
-- Expected: Common Enron internal recipients
SELECT
    er.address,
    COUNT(*) AS received_count,
    er.recipient_type
FROM email_recipients er
GROUP BY er.address
ORDER BY received_count DESC
LIMIT 10;
