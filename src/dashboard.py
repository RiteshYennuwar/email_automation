"""Flask dashboard for the Enron Email Pipeline.

Single-file web application with embedded HTML/CSS/JS for exploring
pipeline results, managing duplicates, and running operations.
Served on localhost:8050.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file

logger = logging.getLogger(__name__)

DB_PATH = "enron.db"
ERROR_LOG_PATH = Path("error_log.txt")
DUPLICATES_REPORT_PATH = Path("duplicates_report.csv")
SEND_LOG_PATH = Path("output/send_log.csv")
REPLIES_DIR = Path("output/replies")
MAILDIR_PATH = Path("data/maildir")


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_app(db_path: str = "enron.db") -> Flask:
    """Create and configure the Flask dashboard application.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Configured Flask application.
    """
    global DB_PATH
    DB_PATH = db_path

    app = Flask(__name__)

    @app.route("/")
    def index():
        """Serve the main dashboard page."""
        return DASHBOARD_HTML

    # ===== OVERVIEW API =====

    @app.route("/api/overview")
    def api_overview():
        """Get pipeline overview statistics."""
        conn = get_db()
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM emails").fetchone()["c"]
            duplicates = conn.execute(
                "SELECT COUNT(*) as c FROM emails WHERE is_duplicate = 1"
            ).fetchone()["c"]
            notif_sent = conn.execute(
                "SELECT COUNT(*) as c FROM emails WHERE notification_sent = 1"
            ).fetchone()["c"]

            # Count error log entries
            errors = 0
            if ERROR_LOG_PATH.exists():
                with ERROR_LOG_PATH.open(encoding="utf-8") as f:
                    errors = sum(1 for _ in f)

            # Duplicate groups
            groups = conn.execute(
                "SELECT COUNT(DISTINCT duplicate_of) as c FROM emails WHERE is_duplicate = 1"
            ).fetchone()["c"]

            return jsonify({
                "total_emails": total,
                "parse_failures": errors,
                "duplicates": duplicates,
                "originals": total - duplicates,
                "duplicate_groups": groups,
                "notifications_sent": notif_sent,
                "files_discovered": total + errors,
            })
        finally:
            conn.close()

    @app.route("/api/overview/charts")
    def api_overview_charts():
        """Get chart data for overview."""
        conn = get_db()
        try:
            # Emails per mailbox
            mailboxes = conn.execute(
                """SELECT
                    CASE
                        WHEN instr(source_file, '/') > 0
                        THEN substr(source_file, 1, instr(source_file, '/') - 1)
                        ELSE source_file
                    END as mailbox,
                    COUNT(*) as count
                FROM emails
                GROUP BY mailbox
                ORDER BY count DESC"""
            ).fetchall()

            # Emails over time (monthly)
            timeline = conn.execute(
                """SELECT strftime('%Y-%m', date) as month, COUNT(*) as count
                FROM emails
                WHERE date IS NOT NULL AND date != ''
                GROUP BY month
                ORDER BY month"""
            ).fetchall()

            return jsonify({
                "mailboxes": [{"name": r["mailbox"], "count": r["count"]} for r in mailboxes],
                "timeline": [{"month": r["month"], "count": r["count"]} for r in timeline],
            })
        finally:
            conn.close()

    # ===== EMAIL EXPLORER API =====

    @app.route("/api/emails")
    def api_emails():
        """Get paginated email list with search and filters."""
        conn = get_db()
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 50))
            search = request.args.get("search", "")
            from_filter = request.args.get("from", "")
            date_from = request.args.get("date_from", "")
            date_to = request.args.get("date_to", "")
            sort = request.args.get("sort", "date")
            order = request.args.get("order", "desc")
            duplicates_only = request.args.get("duplicates_only", "false") == "true"
            has_attachment = request.args.get("has_attachment", "false") == "true"

            conditions = []
            params: list = []

            if search:
                conditions.append(
                    "(from_address LIKE ? OR subject LIKE ? OR body LIKE ?)"
                )
                term = f"%{search}%"
                params.extend([term, term, term])

            if from_filter:
                conditions.append("from_address LIKE ?")
                params.append(f"%{from_filter}%")

            if date_from:
                conditions.append("date >= ?")
                params.append(date_from)

            if date_to:
                conditions.append("date <= ?")
                params.append(date_to)

            if duplicates_only:
                conditions.append("is_duplicate = 1")

            if has_attachment:
                conditions.append("has_attachment = 1")

            where = "WHERE " + " AND ".join(conditions) if conditions else ""

            # Validate sort column
            valid_sorts = {"date", "from_address", "subject", "message_id"}
            sort_col = sort if sort in valid_sorts else "date"
            sort_order = "ASC" if order == "asc" else "DESC"

            total = conn.execute(
                f"SELECT COUNT(*) as c FROM emails {where}", params
            ).fetchone()["c"]

            offset = (page - 1) * per_page
            rows = conn.execute(
                f"""SELECT message_id, date, from_address, subject,
                           has_attachment, is_duplicate, source_file
                    FROM emails {where}
                    ORDER BY {sort_col} {sort_order}
                    LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()

            return jsonify({
                "total": total,
                "page": page,
                "per_page": per_page,
                "emails": [dict(r) for r in rows],
            })
        finally:
            conn.close()

    @app.route("/api/emails/<path:message_id>")
    def api_email_detail(message_id: str):
        """Get full email detail including recipients."""
        conn = get_db()
        try:
            email = conn.execute(
                "SELECT * FROM emails WHERE message_id = ?", (message_id,)
            ).fetchone()
            if not email:
                return jsonify({"error": "Not found"}), 404

            recipients = conn.execute(
                "SELECT address, recipient_type FROM email_recipients WHERE email_message_id = ?",
                (message_id,),
            ).fetchall()

            result = dict(email)
            result["recipients"] = [dict(r) for r in recipients]
            return jsonify(result)
        finally:
            conn.close()

    # ===== DUPLICATE MANAGEMENT API =====

    @app.route("/api/duplicates")
    def api_duplicates():
        """Get duplicate groups with pagination."""
        conn = get_db()
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            offset = (page - 1) * per_page

            groups = conn.execute(
                """SELECT
                    e.duplicate_of as original_id,
                    COUNT(*) as group_size,
                    orig.subject,
                    orig.from_address,
                    orig.date as original_date,
                    MAX(e.date) as latest_date
                FROM emails e
                JOIN emails orig ON e.duplicate_of = orig.message_id
                WHERE e.is_duplicate = 1
                GROUP BY e.duplicate_of
                ORDER BY group_size DESC
                LIMIT ? OFFSET ?""",
                (per_page, offset),
            ).fetchall()

            total = conn.execute(
                "SELECT COUNT(DISTINCT duplicate_of) as c FROM emails WHERE is_duplicate = 1"
            ).fetchone()["c"]

            return jsonify({
                "total": total,
                "page": page,
                "per_page": per_page,
                "groups": [dict(g) for g in groups],
            })
        finally:
            conn.close()

    @app.route("/api/duplicates/<path:original_id>")
    def api_duplicate_detail(original_id: str):
        """Get all emails in a duplicate group."""
        conn = get_db()
        try:
            original = conn.execute(
                "SELECT message_id, date, from_address, subject, body FROM emails WHERE message_id = ?",
                (original_id,),
            ).fetchone()
            if not original:
                return jsonify({"error": "Not found"}), 404

            duplicates = conn.execute(
                """SELECT message_id, date, from_address, subject, body, is_duplicate
                FROM emails WHERE duplicate_of = ? ORDER BY date""",
                (original_id,),
            ).fetchall()

            return jsonify({
                "original": dict(original),
                "duplicates": [dict(d) for d in duplicates],
            })
        finally:
            conn.close()

    @app.route("/api/duplicates/<path:message_id>/reject", methods=["POST"])
    def api_reject_duplicate(message_id: str):
        """Reject a duplicate - set is_duplicate = false."""
        conn = get_db()
        try:
            conn.execute(
                "UPDATE emails SET is_duplicate = 0, duplicate_of = NULL WHERE message_id = ?",
                (message_id,),
            )
            conn.commit()
            return jsonify({"status": "ok"})
        finally:
            conn.close()

    @app.route("/api/duplicates/<path:message_id>/confirm", methods=["POST"])
    def api_confirm_duplicate(message_id: str):
        """Confirm a duplicate (no-op, keeps is_duplicate = true)."""
        return jsonify({"status": "ok"})

    @app.route("/api/duplicates/<path:message_id>/undo", methods=["POST"])
    def api_undo_duplicate(message_id: str):
        """Undo a reject - restore is_duplicate = true."""
        conn = get_db()
        try:
            # Find the original for this message based on grouping
            # For simplicity, we need the original_id passed in
            data = request.get_json(silent=True) or {}
            original_id = data.get("original_id", "")
            if original_id:
                conn.execute(
                    "UPDATE emails SET is_duplicate = 1, duplicate_of = ? WHERE message_id = ?",
                    (original_id, message_id),
                )
                conn.commit()
            return jsonify({"status": "ok"})
        finally:
            conn.close()

    @app.route("/api/duplicates/bulk", methods=["POST"])
    def api_bulk_duplicates():
        """Bulk confirm or reject duplicates."""
        data = request.get_json()
        action = data.get("action", "")
        message_ids = data.get("message_ids", [])
        conn = get_db()
        try:
            for mid in message_ids:
                if action == "reject":
                    conn.execute(
                        "UPDATE emails SET is_duplicate = 0, duplicate_of = NULL WHERE message_id = ?",
                        (mid,),
                    )
                # confirm is a no-op
            conn.commit()
            return jsonify({"status": "ok", "count": len(message_ids)})
        finally:
            conn.close()

    # ===== ANALYTICS API =====

    @app.route("/api/analytics/top-senders")
    def api_top_senders():
        """Get top senders by email count."""
        limit = int(request.args.get("limit", 20))
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT from_address, COUNT(*) as count FROM emails GROUP BY from_address ORDER BY count DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()

    @app.route("/api/analytics/top-recipients")
    def api_top_recipients():
        """Get top recipients by email count."""
        limit = int(request.args.get("limit", 20))
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT address, COUNT(*) as count FROM email_recipients GROUP BY address ORDER BY count DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()

    @app.route("/api/analytics/timeline")
    def api_timeline():
        """Get email volume timeline."""
        granularity = request.args.get("granularity", "month")
        fmt = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m"}.get(granularity, "%Y-%m")
        conn = get_db()
        try:
            rows = conn.execute(
                f"SELECT strftime(?, date) as period, COUNT(*) as count FROM emails WHERE date IS NOT NULL GROUP BY period ORDER BY period",
                (fmt,),
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()

    @app.route("/api/analytics/heatmap")
    def api_heatmap():
        """Get activity heatmap data (hour x day of week)."""
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT
                    CAST(strftime('%w', date) AS INTEGER) as dow,
                    CAST(strftime('%H', date) AS INTEGER) as hour,
                    COUNT(*) as count
                FROM emails
                WHERE date IS NOT NULL
                GROUP BY dow, hour"""
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        finally:
            conn.close()

    # ===== ERRORS API =====

    @app.route("/api/errors")
    def api_errors():
        """Get parse errors from error_log.txt."""
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        error_type = request.args.get("type", "")
        mailbox = request.args.get("mailbox", "")

        errors = []
        if ERROR_LOG_PATH.exists():
            with ERROR_LOG_PATH.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(" | ", 3)
                    if len(parts) >= 3:
                        entry = {
                            "timestamp": parts[0] if len(parts) > 3 else "",
                            "source_file": parts[1] if len(parts) > 3 else parts[0],
                            "error_type": parts[2] if len(parts) > 3 else parts[1],
                            "detail": parts[3] if len(parts) > 3 else parts[2] if len(parts) > 2 else "",
                        }
                        if error_type and error_type not in entry["error_type"]:
                            continue
                        if mailbox and mailbox not in entry["source_file"]:
                            continue
                        errors.append(entry)

        total = len(errors)
        start = (page - 1) * per_page
        end = start + per_page

        return jsonify({
            "total": total,
            "page": page,
            "errors": errors[start:end],
        })

    @app.route("/api/errors/stats")
    def api_error_stats():
        """Get error type distribution."""
        counts: dict[str, int] = {}
        if ERROR_LOG_PATH.exists():
            with ERROR_LOG_PATH.open(encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(" | ")
                    if len(parts) >= 3:
                        etype = parts[2] if len(parts) > 3 else parts[1]
                        key = etype.split(":")[0] if ":" in etype else etype
                        counts[key] = counts.get(key, 0) + 1

        return jsonify(counts)

    # ===== NOTIFICATIONS API =====

    @app.route("/api/notifications/log")
    def api_notification_log():
        """Get notification send log."""
        entries = []
        if SEND_LOG_PATH.exists():
            with SEND_LOG_PATH.open(encoding="utf-8") as f:
                reader = csv.DictReader(f)
                entries = list(reader)
        return jsonify(entries)

    @app.route("/api/notifications/drafts")
    def api_notification_drafts():
        """List all draft .eml files."""
        drafts = []
        if REPLIES_DIR.exists():
            for f in sorted(REPLIES_DIR.iterdir()):
                if f.suffix == ".eml":
                    drafts.append({"filename": f.name, "size": f.stat().st_size})
        return jsonify(drafts[:100])  # Limit for performance

    @app.route("/api/notifications/drafts/<path:filename>")
    def api_draft_preview(filename: str):
        """Preview a draft .eml file."""
        filepath = REPLIES_DIR / filename
        if not filepath.exists() or not str(filepath.resolve()).startswith(
            str(REPLIES_DIR.resolve())
        ):
            return jsonify({"error": "Not found"}), 404
        return jsonify({"content": filepath.read_text(encoding="utf-8")})

    # ===== PIPELINE OPERATIONS API =====

    @app.route("/api/pipeline/run", methods=["POST"])
    def api_pipeline_run():
        """Run the pipeline."""
        data = request.get_json(silent=True) or {}
        maildir = data.get("maildir", "data/maildir")
        cmd = [sys.executable, "main.py", "--maildir", maildir, "--db", DB_PATH]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
            return jsonify({
                "status": "complete",
                "stdout": result.stdout,
                "stderr": result.stderr[-2000:],  # Limit stderr
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"status": "timeout"}), 504

    @app.route("/api/export/<path:filename>")
    def api_export(filename: str):
        """Download a report file."""
        allowed = {
            "duplicates_report.csv": DUPLICATES_REPORT_PATH,
            "error_log.txt": ERROR_LOG_PATH,
            "send_log.csv": SEND_LOG_PATH,
        }
        if filename not in allowed:
            return jsonify({"error": "Not found"}), 404
        filepath = allowed[filename]
        if not filepath.exists():
            return jsonify({"error": "File not found"}), 404
        return send_file(str(filepath.resolve()), as_attachment=True)

    @app.route("/api/database/info")
    def api_database_info():
        """Get database information."""
        conn = get_db()
        try:
            email_count = conn.execute("SELECT COUNT(*) as c FROM emails").fetchone()["c"]
            recip_count = conn.execute("SELECT COUNT(*) as c FROM email_recipients").fetchone()["c"]
            db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

            return jsonify({
                "email_count": email_count,
                "recipient_count": recip_count,
                "db_size_mb": round(db_size / (1024 * 1024), 2),
                "db_path": DB_PATH,
            })
        finally:
            conn.close()

    @app.route("/api/database/schema")
    def api_database_schema():
        """Get the database schema."""
        schema_path = Path("schema.sql")
        if schema_path.exists():
            return jsonify({"schema": schema_path.read_text(encoding="utf-8")})
        return jsonify({"schema": "schema.sql not found"})

    return app


# ===== EMBEDDED HTML/CSS/JS =====

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enron Email Pipeline Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
:root {
    --bg: #f8f9fa;
    --card: #ffffff;
    --text: #212529;
    --text-secondary: #6c757d;
    --primary: #228be6;
    --success: #40c057;
    --error: #fa5252;
    --warning: #fab005;
    --duplicate: #be4bdb;
    --border: #dee2e6;
    --sidebar-bg: #25262b;
    --sidebar-text: #c1c2c5;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --mono: "Cascadia Code", "Fira Code", Consolas, monospace;
}
.dark {
    --bg: #1a1b1e;
    --card: #25262b;
    --text: #c1c2c5;
    --text-secondary: #909296;
    --border: #373a40;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    display: flex;
    height: 100vh;
    overflow: hidden;
}
/* Sidebar */
.sidebar {
    width: 220px;
    background: var(--sidebar-bg);
    color: var(--sidebar-text);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}
.sidebar-header {
    padding: 16px;
    font-size: 14px;
    font-weight: 700;
    border-bottom: 1px solid #373a40;
    color: #fff;
}
.sidebar-nav { flex: 1; padding: 8px 0; }
.sidebar-nav a {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    color: var(--sidebar-text);
    text-decoration: none;
    font-size: 14px;
    cursor: pointer;
    border-left: 3px solid transparent;
}
.sidebar-nav a:hover { background: rgba(255,255,255,0.05); }
.sidebar-nav a.active {
    background: rgba(34,139,230,0.15);
    color: #fff;
    border-left-color: var(--primary);
}
/* Main content */
.main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 24px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
}
.header h1 { font-size: 18px; }
.theme-toggle {
    padding: 6px 12px;
    background: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    cursor: pointer;
    font-size: 13px;
}
.content {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
}
.section { display: none; }
.section.active { display: block; }
/* Cards */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
}
.card .value { font-size: 28px; font-weight: 700; }
.card .label { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
/* Charts */
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 16px; margin-bottom: 24px; }
.chart-container { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.chart-container h3 { font-size: 14px; margin-bottom: 12px; }
/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { font-weight: 600; background: var(--card); position: sticky; top: 0; cursor: pointer; }
tr:hover { background: rgba(34,139,230,0.05); }
.table-container { background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: auto; max-height: 600px; }
/* Filters */
.filters { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.filters input, .filters select {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card);
    color: var(--text);
    font-size: 13px;
}
.filters input { min-width: 200px; }
/* Pagination */
.pagination { display: flex; gap: 8px; justify-content: center; margin-top: 16px; align-items: center; }
.pagination button {
    padding: 6px 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card);
    color: var(--text);
    cursor: pointer;
    font-size: 13px;
}
.pagination button:disabled { opacity: 0.5; cursor: not-allowed; }
.pagination button.active-page { background: var(--primary); color: #fff; border-color: var(--primary); }
/* Detail panel */
.detail-panel {
    position: fixed;
    right: 0;
    top: 0;
    width: 45%;
    height: 100%;
    background: var(--card);
    border-left: 1px solid var(--border);
    box-shadow: -4px 0 16px rgba(0,0,0,0.1);
    z-index: 100;
    display: none;
    flex-direction: column;
    overflow-y: auto;
}
.detail-panel.open { display: flex; }
.detail-panel .close-btn {
    position: absolute; top: 12px; right: 16px;
    background: none; border: none; font-size: 20px;
    cursor: pointer; color: var(--text);
}
.detail-panel .detail-content { padding: 24px; }
.detail-panel h2 { font-size: 16px; margin-bottom: 16px; }
.detail-field { margin-bottom: 12px; }
.detail-field .field-label { font-size: 11px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }
.detail-field .field-value { font-size: 13px; margin-top: 2px; word-break: break-all; }
.detail-field pre { font-family: var(--mono); font-size: 12px; white-space: pre-wrap; max-height: 300px; overflow-y: auto; background: var(--bg); padding: 12px; border-radius: 6px; margin-top: 4px; }
/* Badges */
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-dup { background: rgba(190,75,219,0.15); color: var(--duplicate); }
.badge-ok { background: rgba(64,192,87,0.15); color: var(--success); }
.badge-err { background: rgba(250,82,82,0.15); color: var(--error); }
/* Buttons */
.btn {
    padding: 6px 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    background: var(--card);
    color: var(--text);
}
.btn-primary { background: var(--primary); color: #fff; border-color: var(--primary); }
.btn-danger { background: var(--error); color: #fff; border-color: var(--error); }
.btn-success { background: var(--success); color: #fff; border-color: var(--success); }
/* Diff view */
.diff-container { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.diff-panel { background: var(--bg); padding: 12px; border-radius: 6px; font-family: var(--mono); font-size: 12px; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
.diff-panel h4 { font-family: var(--font); margin-bottom: 8px; }
/* Toast */
.toast {
    position: fixed; bottom: 20px; right: 20px; padding: 12px 20px;
    background: var(--success); color: #fff; border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 200;
    display: none; font-size: 14px;
}
.toast.show { display: block; }
</style>
</head>
<body>
<div class="sidebar">
    <div class="sidebar-header">Enron Email Pipeline</div>
    <nav class="sidebar-nav">
        <a data-section="overview" class="active" onclick="showSection('overview')">Overview</a>
        <a data-section="explorer" onclick="showSection('explorer')">Email Explorer</a>
        <a data-section="duplicates" onclick="showSection('duplicates')">Duplicates</a>
        <a data-section="analytics" onclick="showSection('analytics')">Analytics</a>
        <a data-section="errors" onclick="showSection('errors')">Errors</a>
        <a data-section="notifications" onclick="showSection('notifications')">Notifications</a>
        <a data-section="operations" onclick="showSection('operations')">Operations</a>
    </nav>
</div>
<div class="main">
    <div class="header">
        <h1 id="section-title">Overview</h1>
        <button class="theme-toggle" onclick="toggleTheme()">Toggle Theme</button>
    </div>
    <div class="content">
        <!-- OVERVIEW -->
        <div id="overview" class="section active">
            <div class="cards" id="overview-cards"></div>
            <div class="charts">
                <div class="chart-container"><h3>Emails per Mailbox</h3><canvas id="chart-mailbox"></canvas></div>
                <div class="chart-container"><h3>Emails Over Time</h3><canvas id="chart-timeline"></canvas></div>
            </div>
        </div>

        <!-- EMAIL EXPLORER -->
        <div id="explorer" class="section">
            <div class="filters">
                <input type="text" id="search-input" placeholder="Search emails..." onkeyup="if(event.key==='Enter')loadEmails()">
                <input type="text" id="from-filter" placeholder="From address..." onkeyup="if(event.key==='Enter')loadEmails()">
                <input type="date" id="date-from" onchange="loadEmails()">
                <input type="date" id="date-to" onchange="loadEmails()">
                <label><input type="checkbox" id="dup-filter" onchange="loadEmails()"> Duplicates only</label>
                <button class="btn btn-primary" onclick="loadEmails()">Search</button>
            </div>
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th onclick="sortEmails('date')">Date</th>
                        <th onclick="sortEmails('from_address')">From</th>
                        <th>Subject</th>
                        <th>Att</th>
                        <th>Status</th>
                    </tr></thead>
                    <tbody id="email-table"></tbody>
                </table>
            </div>
            <div class="pagination" id="email-pagination"></div>
        </div>

        <!-- DUPLICATES -->
        <div id="duplicates" class="section">
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th>Original</th>
                        <th>Subject</th>
                        <th>From</th>
                        <th>Group Size</th>
                        <th>Dates</th>
                    </tr></thead>
                    <tbody id="dup-table"></tbody>
                </table>
            </div>
            <div class="pagination" id="dup-pagination"></div>
            <div id="dup-detail" style="margin-top:24px"></div>
        </div>

        <!-- ANALYTICS -->
        <div id="analytics" class="section">
            <div class="charts">
                <div class="chart-container"><h3>Top 20 Senders</h3><canvas id="chart-senders"></canvas></div>
                <div class="chart-container"><h3>Top 20 Recipients</h3><canvas id="chart-recipients"></canvas></div>
                <div class="chart-container"><h3>Activity Heatmap (Hour x Day)</h3><canvas id="chart-heatmap"></canvas></div>
            </div>
        </div>

        <!-- ERRORS -->
        <div id="errors" class="section">
            <div class="filters">
                <select id="error-type-filter" onchange="loadErrors()">
                    <option value="">All Types</option>
                    <option value="MISSING_FIELD">MISSING_FIELD</option>
                    <option value="PARSE_ERROR">PARSE_ERROR</option>
                    <option value="DECODE_ERROR">DECODE_ERROR</option>
                    <option value="READ_ERROR">READ_ERROR</option>
                </select>
                <input type="text" id="error-mailbox-filter" placeholder="Filter by mailbox..." onkeyup="if(event.key==='Enter')loadErrors()">
            </div>
            <div id="error-stats" style="margin-bottom:16px"></div>
            <div class="table-container">
                <table>
                    <thead><tr><th>Timestamp</th><th>Source File</th><th>Error Type</th><th>Detail</th></tr></thead>
                    <tbody id="error-table"></tbody>
                </table>
            </div>
            <div class="pagination" id="error-pagination"></div>
        </div>

        <!-- NOTIFICATIONS -->
        <div id="notifications" class="section">
            <h3 style="margin-bottom:16px">Draft Notifications</h3>
            <div class="table-container" style="max-height:400px">
                <table>
                    <thead><tr><th>Filename</th><th>Size</th><th>Action</th></tr></thead>
                    <tbody id="draft-table"></tbody>
                </table>
            </div>
            <div id="draft-preview" style="margin-top:16px"></div>
        </div>

        <!-- OPERATIONS -->
        <div id="operations" class="section">
            <div class="card" style="margin-bottom:16px">
                <h3>Database Info</h3>
                <div id="db-info" style="margin-top:12px"></div>
            </div>
            <div class="card" style="margin-bottom:16px">
                <h3>Export Reports</h3>
                <div style="display:flex;gap:12px;margin-top:12px">
                    <a href="/api/export/duplicates_report.csv" class="btn">Download Duplicates Report</a>
                    <a href="/api/export/error_log.txt" class="btn">Download Error Log</a>
                    <a href="/api/export/send_log.csv" class="btn">Download Send Log</a>
                </div>
            </div>
            <div class="card">
                <h3>Schema</h3>
                <pre id="schema-view" style="font-size:12px;margin-top:12px;max-height:300px;overflow:auto"></pre>
            </div>
        </div>
    </div>
</div>

<!-- Detail Panel -->
<div class="detail-panel" id="detail-panel">
    <button class="close-btn" onclick="closeDetail()">&times;</button>
    <div class="detail-content" id="detail-content"></div>
</div>

<div class="toast" id="toast"></div>

<script>
// === STATE ===
let emailPage = 1, emailSort = 'date', emailOrder = 'desc';
let dupPage = 1, errPage = 1;
let chartInstances = {};

// === NAV ===
function showSection(name) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.sidebar-nav a').forEach(a => a.classList.remove('active'));
    document.getElementById(name).classList.add('active');
    document.querySelector(`[data-section="${name}"]`).classList.add('active');
    document.getElementById('section-title').textContent = name.charAt(0).toUpperCase() + name.slice(1);
    closeDetail();

    if (name === 'overview') loadOverview();
    if (name === 'explorer') loadEmails();
    if (name === 'duplicates') loadDuplicates();
    if (name === 'analytics') loadAnalytics();
    if (name === 'errors') loadErrors();
    if (name === 'notifications') loadDrafts();
    if (name === 'operations') loadOperations();
}

function toggleTheme() {
    document.body.classList.toggle('dark');
}

// === OVERVIEW ===
async function loadOverview() {
    const res = await fetch('/api/overview');
    const data = await res.json();
    document.getElementById('overview-cards').innerHTML = [
        card(data.files_discovered, 'Files Discovered'),
        card(data.total_emails, 'Emails Parsed'),
        card(data.parse_failures, 'Parse Failures'),
        card(data.duplicates, 'Duplicates Flagged'),
        card(data.duplicate_groups, 'Duplicate Groups'),
        card(data.notifications_sent, 'Notifications Sent'),
    ].join('');

    const cres = await fetch('/api/overview/charts');
    const charts = await cres.json();

    destroyChart('chart-mailbox');
    chartInstances['chart-mailbox'] = new Chart(document.getElementById('chart-mailbox'), {
        type: 'bar',
        data: {
            labels: charts.mailboxes.map(m => m.name),
            datasets: [{label: 'Emails', data: charts.mailboxes.map(m => m.count), backgroundColor: '#228be6'}]
        },
        options: {responsive: true, plugins: {legend: {display: false}}}
    });

    destroyChart('chart-timeline');
    const tl = charts.timeline.filter(t => t.month);
    chartInstances['chart-timeline'] = new Chart(document.getElementById('chart-timeline'), {
        type: 'line',
        data: {
            labels: tl.map(t => t.month),
            datasets: [{label: 'Emails', data: tl.map(t => t.count), borderColor: '#228be6', tension: 0.3, fill: false}]
        },
        options: {responsive: true}
    });
}

function card(value, label) {
    return `<div class="card"><div class="value">${typeof value === 'number' ? value.toLocaleString() : value}</div><div class="label">${label}</div></div>`;
}

function destroyChart(id) { if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; } }

// === EMAIL EXPLORER ===
async function loadEmails() {
    const search = document.getElementById('search-input').value;
    const from = document.getElementById('from-filter').value;
    const dateFrom = document.getElementById('date-from').value;
    const dateTo = document.getElementById('date-to').value;
    const dupOnly = document.getElementById('dup-filter').checked;

    const params = new URLSearchParams({
        page: emailPage, per_page: 50, search, from,
        date_from: dateFrom, date_to: dateTo,
        sort: emailSort, order: emailOrder,
        duplicates_only: dupOnly
    });
    const res = await fetch('/api/emails?' + params);
    const data = await res.json();

    document.getElementById('email-table').innerHTML = data.emails.map(e => `
        <tr onclick="showEmailDetail('${encodeURIComponent(e.message_id)}')" style="cursor:pointer">
            <td>${(e.date||'').substring(0,16)}</td>
            <td>${esc(e.from_address)}</td>
            <td>${esc((e.subject||'').substring(0,80))}</td>
            <td>${e.has_attachment ? 'Y' : ''}</td>
            <td>${e.is_duplicate ? '<span class="badge badge-dup">DUP</span>' : '<span class="badge badge-ok">OK</span>'}</td>
        </tr>
    `).join('');

    renderPagination('email-pagination', data.total, data.page, 50, p => { emailPage = p; loadEmails(); });
}

function sortEmails(col) {
    if (emailSort === col) emailOrder = emailOrder === 'asc' ? 'desc' : 'asc';
    else { emailSort = col; emailOrder = 'desc'; }
    emailPage = 1;
    loadEmails();
}

async function showEmailDetail(encodedId) {
    const id = decodeURIComponent(encodedId);
    const res = await fetch('/api/emails/' + encodeURIComponent(id));
    const e = await res.json();
    if (e.error) return;

    const panel = document.getElementById('detail-panel');
    const content = document.getElementById('detail-content');

    const recipients = (e.recipients || []).map(r => `${r.address} (${r.recipient_type})`).join(', ');

    content.innerHTML = `
        <h2>${esc(e.subject)}</h2>
        ${field('Message-ID', e.message_id)}
        ${field('Date', e.date)}
        ${field('From', e.from_address)}
        ${field('Recipients', recipients)}
        ${field('Source File', e.source_file)}
        ${e.x_folder ? field('X-Folder', e.x_folder) : ''}
        ${e.x_origin ? field('X-Origin', e.x_origin) : ''}
        ${e.is_duplicate ? field('Status', 'DUPLICATE of ' + e.duplicate_of) : field('Status', 'Original')}
        ${field('Has Attachment', e.has_attachment ? 'Yes' : 'No')}
        <div class="detail-field"><div class="field-label">Body</div><pre>${esc(e.body || '')}</pre></div>
        ${e.forwarded_content ? '<div class="detail-field"><div class="field-label">Forwarded Content</div><pre>' + esc(e.forwarded_content) + '</pre></div>' : ''}
        ${e.quoted_content ? '<div class="detail-field"><div class="field-label">Quoted Content</div><pre>' + esc(e.quoted_content) + '</pre></div>' : ''}
        ${e.headings ? field('Headings', e.headings) : ''}
    `;
    panel.classList.add('open');
}

function closeDetail() { document.getElementById('detail-panel').classList.remove('open'); }

// === DUPLICATES ===
async function loadDuplicates() {
    const params = new URLSearchParams({page: dupPage, per_page: 20});
    const res = await fetch('/api/duplicates?' + params);
    const data = await res.json();

    document.getElementById('dup-table').innerHTML = data.groups.map(g => `
        <tr onclick="showDupDetail('${encodeURIComponent(g.original_id)}')" style="cursor:pointer">
            <td style="font-family:var(--mono);font-size:11px">${esc((g.original_id||'').substring(0,40))}</td>
            <td>${esc((g.subject||'').substring(0,60))}</td>
            <td>${esc(g.from_address)}</td>
            <td>${g.group_size}</td>
            <td style="font-size:11px">${(g.original_date||'').substring(0,10)} - ${(g.latest_date||'').substring(0,10)}</td>
        </tr>
    `).join('');

    renderPagination('dup-pagination', data.total, data.page, 20, p => { dupPage = p; loadDuplicates(); });
}

async function showDupDetail(encodedId) {
    const id = decodeURIComponent(encodedId);
    const res = await fetch('/api/duplicates/' + encodeURIComponent(id));
    const data = await res.json();
    if (data.error) return;

    let html = '<h3>Duplicate Group</h3>';
    html += '<div class="diff-container" style="margin-top:16px">';
    html += '<div class="diff-panel"><h4>Original</h4>' + esc(data.original.body || '(empty)') + '</div>';
    if (data.duplicates.length > 0) {
        html += '<div class="diff-panel"><h4>Latest Duplicate</h4>' + esc(data.duplicates[data.duplicates.length-1].body || '(empty)') + '</div>';
    }
    html += '</div>';

    html += '<table style="margin-top:16px"><thead><tr><th>Message ID</th><th>Date</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
    for (const d of data.duplicates) {
        html += `<tr>
            <td style="font-family:var(--mono);font-size:11px">${esc((d.message_id||'').substring(0,40))}</td>
            <td>${(d.date||'').substring(0,16)}</td>
            <td>${d.is_duplicate ? '<span class="badge badge-dup">DUP</span>' : '<span class="badge badge-ok">OK</span>'}</td>
            <td>
                <button class="btn btn-success" onclick="confirmDup('${encodeURIComponent(d.message_id)}')">Confirm</button>
                <button class="btn btn-danger" onclick="rejectDup('${encodeURIComponent(d.message_id)}')">Reject</button>
            </td>
        </tr>`;
    }
    html += '</tbody></table>';

    document.getElementById('dup-detail').innerHTML = html;
}

async function confirmDup(encodedId) {
    await fetch('/api/duplicates/' + encodeURIComponent(decodeURIComponent(encodedId)) + '/confirm', {method: 'POST'});
    showToast('Confirmed as duplicate');
}

async function rejectDup(encodedId) {
    await fetch('/api/duplicates/' + encodeURIComponent(decodeURIComponent(encodedId)) + '/reject', {method: 'POST'});
    showToast('Rejected - marked as not duplicate');
    loadDuplicates();
}

// === ANALYTICS ===
async function loadAnalytics() {
    const [senders, recipients, heatmap] = await Promise.all([
        fetch('/api/analytics/top-senders?limit=20').then(r => r.json()),
        fetch('/api/analytics/top-recipients?limit=20').then(r => r.json()),
        fetch('/api/analytics/heatmap').then(r => r.json()),
    ]);

    destroyChart('chart-senders');
    chartInstances['chart-senders'] = new Chart(document.getElementById('chart-senders'), {
        type: 'bar',
        data: {
            labels: senders.map(s => s.from_address.substring(0, 25)),
            datasets: [{label: 'Sent', data: senders.map(s => s.count), backgroundColor: '#228be6'}]
        },
        options: {responsive: true, indexAxis: 'y', plugins: {legend: {display: false}}}
    });

    destroyChart('chart-recipients');
    chartInstances['chart-recipients'] = new Chart(document.getElementById('chart-recipients'), {
        type: 'bar',
        data: {
            labels: recipients.map(r => r.address.substring(0, 25)),
            datasets: [{label: 'Received', data: recipients.map(r => r.count), backgroundColor: '#40c057'}]
        },
        options: {responsive: true, indexAxis: 'y', plugins: {legend: {display: false}}}
    });

    // Heatmap as a simple table
    destroyChart('chart-heatmap');
    const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    const heatData = {};
    let maxCount = 1;
    heatmap.forEach(h => { const key = h.dow + '-' + h.hour; heatData[key] = h.count; maxCount = Math.max(maxCount, h.count); });
    const canvas = document.getElementById('chart-heatmap');
    const ctx = canvas.getContext('2d');
    canvas.width = 600; canvas.height = 200;
    const cellW = canvas.width / 24, cellH = canvas.height / 7;
    for (let d = 0; d < 7; d++) {
        for (let h = 0; h < 24; h++) {
            const count = heatData[d + '-' + h] || 0;
            const intensity = count / maxCount;
            ctx.fillStyle = `rgba(34, 139, 230, ${intensity})`;
            ctx.fillRect(h * cellW, d * cellH, cellW - 1, cellH - 1);
        }
        ctx.fillStyle = '#666'; ctx.font = '10px sans-serif';
        ctx.fillText(days[d], 0, d * cellH + cellH/2 + 3);
    }
}

// === ERRORS ===
async function loadErrors() {
    const type = document.getElementById('error-type-filter').value;
    const mailbox = document.getElementById('error-mailbox-filter').value;
    const params = new URLSearchParams({page: errPage, per_page: 50, type, mailbox});
    const res = await fetch('/api/errors?' + params);
    const data = await res.json();

    document.getElementById('error-table').innerHTML = data.errors.map(e => `
        <tr>
            <td style="font-size:11px">${esc(e.timestamp)}</td>
            <td style="font-family:var(--mono);font-size:11px">${esc(e.source_file)}</td>
            <td><span class="badge badge-err">${esc(e.error_type)}</span></td>
            <td>${esc(e.detail)}</td>
        </tr>
    `).join('');

    renderPagination('error-pagination', data.total, data.page, 50, p => { errPage = p; loadErrors(); });

    const statsRes = await fetch('/api/errors/stats');
    const stats = await statsRes.json();
    document.getElementById('error-stats').innerHTML = Object.entries(stats).map(
        ([k,v]) => `<span class="badge badge-err" style="margin-right:8px">${k}: ${v}</span>`
    ).join('');
}

// === NOTIFICATIONS ===
async function loadDrafts() {
    const res = await fetch('/api/notifications/drafts');
    const drafts = await res.json();
    document.getElementById('draft-table').innerHTML = drafts.map(d => `
        <tr>
            <td style="font-family:var(--mono);font-size:11px">${esc(d.filename)}</td>
            <td>${(d.size/1024).toFixed(1)} KB</td>
            <td><button class="btn" onclick="previewDraft('${esc(d.filename)}')">Preview</button></td>
        </tr>
    `).join('');
}

async function previewDraft(filename) {
    const res = await fetch('/api/notifications/drafts/' + encodeURIComponent(filename));
    const data = await res.json();
    document.getElementById('draft-preview').innerHTML = `
        <div class="card"><h3>Draft Preview: ${esc(filename)}</h3><pre style="margin-top:12px;font-size:12px">${esc(data.content)}</pre></div>
    `;
}

// === OPERATIONS ===
async function loadOperations() {
    const res = await fetch('/api/database/info');
    const info = await res.json();
    document.getElementById('db-info').innerHTML = `
        <p>Emails: <strong>${info.email_count.toLocaleString()}</strong></p>
        <p>Recipients: <strong>${info.recipient_count.toLocaleString()}</strong></p>
        <p>Database Size: <strong>${info.db_size_mb} MB</strong></p>
        <p>Path: <code>${esc(info.db_path)}</code></p>
    `;

    const schemaRes = await fetch('/api/database/schema');
    const schema = await schemaRes.json();
    document.getElementById('schema-view').textContent = schema.schema;
}

// === HELPERS ===
function renderPagination(containerId, total, current, perPage, callback) {
    const pages = Math.ceil(total / perPage);
    const container = document.getElementById(containerId);
    let html = `<span style="font-size:13px;color:var(--text-secondary)">${total.toLocaleString()} total</span>`;
    html += `<button ${current <= 1 ? 'disabled' : ''} onclick="void(0)">Prev</button>`;
    html += `<span style="font-size:13px">Page ${current} of ${pages}</span>`;
    html += `<button ${current >= pages ? 'disabled' : ''} onclick="void(0)">Next</button>`;
    container.innerHTML = html;
    container.querySelectorAll('button')[0].onclick = () => { if(current > 1) callback(current - 1); };
    container.querySelectorAll('button')[1].onclick = () => { if(current < pages) callback(current + 1); };
}

function field(label, value) {
    return `<div class="detail-field"><div class="field-label">${label}</div><div class="field-value">${esc(String(value || ''))}</div></div>`;
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}

// === INIT ===
loadOverview();
</script>
</body>
</html>"""
