---
name: email-parsing
description: Reference for parsing RFC 2822 email files from the Enron dataset. Use this when implementing or debugging src/parser.py, handling email edge cases, or extracting fields from raw email text.
---

# Enron Email Parsing Reference

## Python email stdlib usage
```python
import email
from email import policy

with open(file_path, "r", encoding="utf-8", errors="replace") as f:
    msg = email.message_from_file(f, policy=policy.default)

# Headers
message_id = msg["Message-ID"]
date_str = msg["Date"]
from_addr = msg["From"]
to_field = msg["To"]
subject = msg["Subject"]
```

## Address Extraction
Strip display names, lowercase, trim:
```python
from email.utils import parseaddr, getaddresses

# Single address:
_, addr = parseaddr("Ken Lay <klay@enron.com>")
# addr = "klay@enron.com"

# Multiple addresses (handles commas + continuation lines):
pairs = getaddresses([to_field])
addresses = [addr.lower().strip() for name, addr in pairs if addr]
```

## Date Parsing to UTC
```python
from dateutil import parser as dateutil_parser
from dateutil.tz import tzutc, gettz

# Timezone abbreviation mapping (dateutil doesn't handle all)
TIMEZONE_MAP = {
    "PST": gettz("US/Pacific"),
    "PDT": gettz("US/Pacific"),
    "MST": gettz("US/Mountain"),
    "MDT": gettz("US/Mountain"),
    "CST": gettz("US/Central"),
    "CDT": gettz("US/Central"),
    "EST": gettz("US/Eastern"),
    "EDT": gettz("US/Eastern"),
}

parsed_date = dateutil_parser.parse(date_str, tzinfos=TIMEZONE_MAP)
utc_date = parsed_date.astimezone(tzutc())
```

## Body Extraction
```python
body = msg.get_body(preferencelist=("plain", "html"))
if body:
    content = body.get_content()
else:
    # Fallback for non-MIME messages
    payload = msg.get_payload(decode=True)
    content = payload.decode("utf-8", errors="replace") if payload else ""
```

## Forwarded Content Detection
Split body at forwarded markers:
```python
FORWARD_MARKERS = [
    "-----Original Message-----",
    "---------- Forwarded message ----------",
    "---------------------- Forwarded by",
    "----- Forwarded by",
]

primary_body = full_body
forwarded_content = None

for marker in FORWARD_MARKERS:
    if marker in full_body:
        idx = full_body.index(marker)
        primary_body = full_body[:idx].strip()
        forwarded_content = full_body[idx:].strip()
        break
```

## Quoted Content Detection
Lines starting with `>`:
```python
lines = primary_body.split("\n")
quoted_lines = [l for l in lines if l.strip().startswith(">")]
non_quoted_lines = [l for l in lines if not l.strip().startswith(">")]

quoted_content = "\n".join(quoted_lines) if quoted_lines else None
primary_body = "\n".join(non_quoted_lines).strip()
```

## Attachment Detection
```python
has_attachment = False

# Check Content-Type
content_type = msg.get_content_type() or ""
if "multipart/mixed" in content_type:
    has_attachment = True

# Check for Enron-style attachment references
if "<<" in content and ">>" in content:
    import re
    if re.search(r"<<.+?\..+?>>", content):
        has_attachment = True

# Check for MIME parts
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            has_attachment = True
            break
```

## Headings Detection
```python
import re

headings = []
for line in content.split("\n"):
    stripped = line.strip()
    if not stripped:
        continue
    # ALL CAPS lines (min 3 chars, not just punctuation)
    if stripped.isupper() and len(stripped) >= 3 and re.search(r"[A-Z]", stripped):
        headings.append(stripped)
    # Lines ending with colon (likely section headers)
    elif stripped.endswith(":") and len(stripped) < 80 and not stripped.startswith(">"):
        headings.append(stripped)

headings_str = "; ".join(headings) if headings else None
```

## Enron-Specific Headers
```python
x_from = msg.get("X-From")
x_to = msg.get("X-To")
x_cc = msg.get("X-cc")
x_bcc = msg.get("X-bcc")
x_folder = msg.get("X-Folder")
x_origin = msg.get("X-Origin")
```

## Common Edge Cases in Enron Data
1. **Multi-line To/CC headers** — continuation lines start with whitespace. `getaddresses()` handles this.
2. **Missing Message-ID** — some drafts lack it. Log as parse failure.
3. **Timezone abbreviations** — `PST`, `CDT`, etc. Must use `tzinfos` mapping.
4. **Latin-1 encoding** — some emails use non-UTF-8. Open with `errors="replace"`.
5. **Empty bodies** — legitimate (forwarded-only emails). Store as empty string, NOT a failure.
6. **Nested forwarded messages** — multiple `-----Original Message-----` markers. Split on first occurrence only.
7. **`<<filename.xls>>`** — Enron convention for attachment references.
