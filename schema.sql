-- Enron Email Pipeline — Database Schema
-- Creates normalized tables for email storage with dedup and notification tracking.

CREATE TABLE IF NOT EXISTS emails (
    message_id          TEXT PRIMARY KEY,
    date                DATETIME NOT NULL,
    from_address        TEXT NOT NULL,
    subject             TEXT NOT NULL,
    body                TEXT,
    source_file         TEXT NOT NULL,
    x_from              TEXT,
    x_to                TEXT,
    x_cc                TEXT,
    x_bcc               TEXT,
    x_folder            TEXT,
    x_origin            TEXT,
    content_type        TEXT,
    has_attachment       BOOLEAN DEFAULT 0,
    forwarded_content   TEXT,
    quoted_content       TEXT,
    headings            TEXT,
    is_duplicate        BOOLEAN DEFAULT 0,
    duplicate_of        TEXT,
    notification_sent   BOOLEAN DEFAULT 0,
    notification_date   DATETIME,
    FOREIGN KEY (duplicate_of) REFERENCES emails(message_id)
);

CREATE TABLE IF NOT EXISTS email_recipients (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email_message_id    TEXT NOT NULL,
    address             TEXT NOT NULL,
    recipient_type      TEXT NOT NULL CHECK(recipient_type IN ('to', 'cc', 'bcc')),
    FOREIGN KEY (email_message_id) REFERENCES emails(message_id)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_from_address ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_subject ON emails(subject);
CREATE INDEX IF NOT EXISTS idx_recipients_address ON email_recipients(address);
CREATE INDEX IF NOT EXISTS idx_recipients_email_message_id ON email_recipients(email_message_id);
