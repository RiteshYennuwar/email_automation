"""Notification generation for the Enron Email Pipeline.

Generates .eml draft files for duplicate notifications and handles
live sending via Gmail MCP.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from src.database import get_email_by_id, update_notification_sent

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output/replies")
SEND_LOG_PATH = Path("output/send_log.csv")

NOTIFICATION_TEMPLATE = """This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  {dup_message_id}
    Date Sent:   {dup_date}
    Subject:     {subject}

  Original Email on Record:
    Message-ID:  {orig_message_id}
    Date Sent:   {orig_date}

  Similarity Score: {similarity}%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate."""


def generate_notifications(
    conn: sqlite3.Connection,
    send_live: bool = False,
    notify_address: str | None = None,
) -> dict[str, int]:
    """Generate notification emails for duplicate groups.

    For each duplicate group, generates a notification for the latest
    flagged duplicate. In dry-run mode, writes .eml files. In live mode,
    sends via Gmail MCP.

    Args:
        conn: Active SQLite connection.
        send_live: Whether to send via Gmail MCP.
        notify_address: Override recipient for live sending.

    Returns:
        Dictionary with stats: generated, sent.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _init_send_log()

    # Get all duplicate groups
    rows = conn.execute(
        """SELECT e.message_id, e.date, e.from_address, e.subject, e.duplicate_of
           FROM emails e
           WHERE e.is_duplicate = 1
           ORDER BY e.duplicate_of, e.date DESC"""
    ).fetchall()

    # Group by original, take latest duplicate per group
    groups: dict[str, sqlite3.Row] = {}
    for row in rows:
        orig_id = row["duplicate_of"]
        if orig_id not in groups:
            groups[orig_id] = row

    stats = {"generated": 0, "sent": 0}

    # Pre-load similarity scores from CSV for performance
    similarity_map = _load_similarity_scores()

    total_groups = len(groups)
    for i, (orig_id, dup_row) in enumerate(groups.items(), 1):
        if i % 1000 == 0:
            import sys
            print(f"  Generated {i}/{total_groups} notifications...", file=sys.stderr)

        original = get_email_by_id(conn, orig_id)
        if original is None:
            continue

        similarity = similarity_map.get(dup_row["message_id"], 0.0)

        eml_content = _create_notification_eml(
            dup_message_id=dup_row["message_id"],
            dup_date=dup_row["date"],
            dup_from=dup_row["from_address"],
            subject=dup_row["subject"],
            orig_message_id=orig_id,
            orig_date=original["date"],
            similarity=similarity,
            notify_address=notify_address,
        )

        # Write .eml file
        safe_id = dup_row["message_id"].replace("<", "").replace(">", "").replace("@", "_at_")
        eml_path = OUTPUT_DIR / f"{safe_id}.eml"
        eml_path.write_text(eml_content, encoding="utf-8")
        stats["generated"] += 1

        if send_live and notify_address:
            success = _send_via_mcp(notify_address, dup_row["subject"], eml_content)
            if success:
                stats["sent"] += 1
                now_utc = datetime.now(timezone.utc).isoformat()
                update_notification_sent(conn, dup_row["message_id"], now_utc)
                _log_send(notify_address, dup_row["subject"], "sent", "")
            else:
                _log_send(notify_address, dup_row["subject"], "failed", "MCP send error")

    conn.commit()
    logger.info(
        "Notifications: %d generated, %d sent", stats["generated"], stats["sent"]
    )
    return stats


def _create_notification_eml(
    dup_message_id: str,
    dup_date: str,
    dup_from: str,
    subject: str,
    orig_message_id: str,
    orig_date: str,
    similarity: float,
    notify_address: str | None = None,
) -> str:
    """Create a notification email in .eml format.

    Args:
        dup_message_id: Message-ID of the flagged duplicate.
        dup_date: Date of the flagged duplicate.
        dup_from: From address of the flagged duplicate.
        subject: Subject of the email.
        orig_message_id: Message-ID of the original email.
        orig_date: Date of the original email.
        similarity: Similarity score percentage.
        notify_address: Override recipient address.

    Returns:
        Complete .eml content as string.
    """
    body = NOTIFICATION_TEMPLATE.format(
        dup_message_id=dup_message_id,
        dup_date=dup_date,
        subject=subject,
        orig_message_id=orig_message_id,
        orig_date=orig_date,
        similarity=round(similarity, 1),
    )

    recipient = notify_address or dup_from
    now_utc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    msg = MIMEText(body)
    msg["To"] = recipient
    msg["Subject"] = f"[Duplicate Notice] Re: {subject}"
    msg["Date"] = now_utc
    msg["References"] = dup_message_id

    return msg.as_string()


def _load_similarity_scores() -> dict[str, float]:
    """Load all similarity scores from the duplicates report CSV.

    Returns:
        Dictionary mapping duplicate_message_id to similarity_score.
    """
    report_path = Path("duplicates_report.csv")
    scores: dict[str, float] = {}
    if not report_path.exists():
        return scores

    try:
        with report_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                mid = row.get("duplicate_message_id", "")
                score = float(row.get("similarity_score", 0))
                scores[mid] = score
    except (ValueError, KeyError, OSError):
        pass

    return scores


def _send_via_mcp(recipient: str, subject: str, content: str) -> bool:
    """Send notification email via the Gmail MCP server.

    Spawns the Gmail MCP server as a stdio subprocess, connects via the
    MCP Python SDK ClientSession, and calls the send_email tool.  Requires
    prior authentication (``npx @gongrzhe/server-gmail-autoauth-mcp auth``).

    Falls back to the Gmail REST API if the MCP subprocess fails.

    Args:
        recipient: Email address to send to.
        subject: Email subject line (without [Duplicate Notice] prefix).
        content: Full MIME email content string (used for body extraction).

    Returns:
        True if send succeeded, False otherwise.
    """
    import email as _email

    # Extract plain-text body from the MIME content
    msg = _email.message_from_string(content)
    payload = msg.get_payload(decode=True)
    body: str = (
        payload.decode("utf-8", errors="replace")
        if isinstance(payload, bytes)
        else (msg.get_payload(decode=False) or "")  # type: ignore[arg-type]
    )
    in_reply_to: str = msg.get("References", "")

    full_subject = f"[Duplicate Notice] Re: {subject}"

    # --- Primary: MCP Python SDK (assignment requirement) ---
    if _send_via_mcp_sdk(recipient, full_subject, body, in_reply_to):
        return True

    # --- Fallback: direct Gmail REST API ---
    logger.warning("MCP send failed, falling back to Gmail REST API for %s", recipient)
    return _send_via_gmail_api(recipient, full_subject, body, in_reply_to)


def _send_via_mcp_sdk(
    recipient: str, subject: str, body: str, in_reply_to: str
) -> bool:
    """Send email using the MCP Python SDK (spawns Gmail MCP as subprocess).

    Args:
        recipient: Email address to send to.
        subject: Full email subject including prefix.
        body: Plain-text email body.
        in_reply_to: Message-ID being replied to.

    Returns:
        True if send succeeded, False otherwise.
    """
    import asyncio
    import os
    import sys
    from pathlib import Path

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command = "cmd" if sys.platform == "win32" else "npx"
    args = (
        ["/c", "npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp"]
        if sys.platform == "win32"
        else ["-y", "@gongrzhe/server-gmail-autoauth-mcp"]
    )

    # Ensure the subprocess inherits the correct home directory so
    # the Gmail MCP server can find its OAuth credentials.
    home = str(Path.home())
    env = {**os.environ, "USERPROFILE": home, "HOME": home}

    async def _send() -> bool:
        server_params = StdioServerParameters(command=command, args=args, env=env)
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "send_email",
                    arguments={
                        "to": [recipient],
                        "subject": subject,
                        "body": body,
                        "inReplyTo": in_reply_to,
                    },
                )
                if result.isError:
                    logger.error("MCP send_email error: %s", result.content)
                    return False
                resp_text = (
                    result.content[0].text
                    if result.content and hasattr(result.content[0], "text")
                    else str(result.content)
                )
                logger.info("MCP send_email succeeded for %s: %s", recipient, resp_text)
                return True

    try:
        return asyncio.run(_send())
    except Exception as e:
        logger.error("MCP subprocess send failed for %s: %s", recipient, e)
        return False


def _send_via_gmail_api(
    recipient: str, subject: str, body: str, in_reply_to: str
) -> bool:
    """Fallback: send email directly via Gmail REST API.

    Uses the OAuth credentials stored by the Gmail MCP server at
    ~/.gmail-mcp/credentials.json, refreshing the access token if needed.

    Args:
        recipient: Email address to send to.
        subject: Full email subject including prefix.
        body: Plain-text email body.
        in_reply_to: Message-ID being replied to.

    Returns:
        True if send succeeded, False otherwise.
    """
    import base64
    import json
    import time
    from email.mime.text import MIMEText
    from pathlib import Path

    import requests

    creds_path = Path.home() / ".gmail-mcp" / "credentials.json"
    oauth_path = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"

    try:
        creds = json.loads(creds_path.read_text())
        access_token: str = creds["access_token"]
        expiry_ms: int = creds.get("expiry_date", 0)

        # Refresh if expired (expiry_date is milliseconds)
        if expiry_ms and time.time() * 1000 > expiry_ms - 60_000:
            oauth_keys = json.loads(oauth_path.read_text())["installed"]
            refresh_resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": oauth_keys["client_id"],
                    "client_secret": oauth_keys["client_secret"],
                    "refresh_token": creds["refresh_token"],
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            refresh_resp.raise_for_status()
            new_token = refresh_resp.json()
            access_token = new_token["access_token"]
            creds["access_token"] = access_token
            creds["expiry_date"] = int(
                (time.time() + new_token["expires_in"]) * 1000
            )
            creds_path.write_text(json.dumps(creds))
            logger.info("Gmail access token refreshed")

        out = MIMEText(body, "plain", "utf-8")
        out["To"] = recipient
        out["Subject"] = subject
        if in_reply_to:
            out["In-Reply-To"] = in_reply_to
            out["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(out.as_bytes()).decode()

        send_resp = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=15,
        )
        send_resp.raise_for_status()
        msg_id = send_resp.json().get("id", "unknown")
        logger.info("Gmail REST API send succeeded for %s (id=%s)", recipient, msg_id)
        return True

    except Exception as e:
        logger.error("Gmail REST API send failed for %s: %s", recipient, e)
        return False


def _init_send_log() -> None:
    """Initialize the send log CSV with headers if it doesn't exist."""
    SEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SEND_LOG_PATH.exists():
        with SEND_LOG_PATH.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "recipient", "subject", "status", "error"])


def _log_send(
    recipient: str, subject: str, status: str, error: str
) -> None:
    """Append an entry to the send log CSV.

    Args:
        recipient: Recipient email address.
        subject: Email subject.
        status: Send status (sent/failed).
        error: Error message if failed.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    with SEND_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([now_utc, recipient, subject, status, error])
