# UI.md — Dashboard Specification
## Enron Email Pipeline — Local Dashboard

---

## 1. Purpose

A local web dashboard for exploring pipeline results, analyzing email patterns, managing duplicates, and triggering pipeline operations. Built as a single-file Flask app with embedded HTML/CSS/JS. Served on `localhost:8050`.

---

## 2. Technical Approach

- Single `src/dashboard.py` file
- Flask backend with JSON API endpoints
- Embedded HTML/CSS/JS (no build step, no npm, no React)
- SQLite read/write (read for exploration, write for duplicate management)
- Subprocess calls for pipeline operations
- System font stack, minimal CSS, no external frameworks
- Chart.js loaded from CDN for visualizations (fallback: CSS bar charts if no internet)

---

## 3. Navigation

Single page with a sidebar or tab bar. Seven sections:

```
📊 Overview        — Pipeline stats + charts
📧 Email Explorer  — Browse, search, view full emails
🔍 Duplicates      — Manage duplicate groups, diff view, confirm/reject
📈 Analytics       — Sender/recipient charts, timeline, heatmap, network
⚠️ Errors          — Parse error log viewer
📬 Notifications   — Send log + send actions
⚙️ Operations      — Re-run pipeline, export reports
```

---

## 4. Section Specifications

### 4.1 Overview (default landing page)

**Summary cards at top:**
- Total files discovered
- Successfully parsed
- Parse failures (with failure rate %)
- Total in database
- Duplicate groups found
- Emails flagged as duplicates
- Notifications sent

**Charts:**
- Bar chart: emails per mailbox (from source_file path)
- Line chart: emails over time (by month/year)
- Pie chart: parse success vs failure breakdown

**Data source:** Aggregate queries on `emails` table + `error_log.txt` line count.

---

### 4.2 Email Explorer

**Features:**
- **Table view** of all emails: date, from, to (truncated), subject, has_attachment, is_duplicate
- **Pagination:** 50 emails per page with next/prev
- **Search bar:** Full-text search across from_address, to (via recipients table), subject, body
- **Filters:** Date range picker, sender filter, folder filter (x_folder), duplicates only toggle, has attachment toggle
- **Sort:** Click column headers to sort by date, sender, subject
- **Email detail panel:** Click any row to open a side panel showing:
  - Full headers (all mandatory + optional fields)
  - Body (primary)
  - Forwarded content (collapsible section)
  - Quoted content (collapsible section)
  - Recipients (to/cc/bcc from junction table)
  - Headings (if any)
  - Duplicate status + link to original if flagged
  - Source file path

**API endpoints:**
```
GET /api/emails?page=1&per_page=50&search=term&from=addr&date_from=&date_to=&sort=date&order=desc&duplicates_only=false&has_attachment=false
GET /api/emails/<message_id>
```

---

### 4.3 Duplicate Management

**Duplicate groups table:**
- Original message_id (truncated, hoverable for full)
- Number of duplicates in group
- Subject (normalized)
- From address
- Highest similarity score in group
- Original date / Latest duplicate date

**Click a group → expanded view showing:**
- All emails in the group with their dates, message IDs, and similarity scores
- **Side-by-side diff view:** Original body on left, duplicate body on right, differences highlighted (use simple text diff — highlight changed/added/removed lines with color)
- **Action buttons per duplicate:**
  - ✅ **Confirm Duplicate** — keeps `is_duplicate = true` (no change, visual confirmation)
  - ❌ **Reject — Not a Duplicate** — sets `is_duplicate = false`, clears `duplicate_of` in DB
  - ↩️ **Undo** — reverts to previous state

**Bulk actions:**
- Select multiple groups → Confirm All / Reject All
- Export selected groups to CSV

**API endpoints:**
```
GET  /api/duplicates?page=1&per_page=20
GET  /api/duplicates/<original_message_id>
POST /api/duplicates/<message_id>/confirm
POST /api/duplicates/<message_id>/reject
POST /api/duplicates/<message_id>/undo
POST /api/duplicates/bulk   (body: { action: "confirm"|"reject", message_ids: [...] })
```

---

### 4.4 Analytics

**Top Senders (bar chart):**
- Top 20 senders by email count
- Clickable — filters Email Explorer to that sender

**Top Recipients (bar chart):**
- Top 20 recipients (from email_recipients table)
- Clickable — filters Email Explorer

**Email Volume Timeline (line chart):**
- Emails per day/week/month (toggle granularity)
- Date range selector
- Overlay: duplicates flagged per period (second line, different color)

**Activity Heatmap:**
- Grid: hour of day (y-axis) × day of week (x-axis)
- Color intensity = email count in that cell
- Shows when Enron employees were most active

**Network Graph (stretch goal):**
- Nodes = email addresses (sized by email count)
- Edges = sender → recipient connections (thickness by frequency)
- Only show top 30 most connected addresses (otherwise too dense)
- Use simple force-directed layout with D3.js or plain SVG

**API endpoints:**
```
GET /api/analytics/top-senders?limit=20
GET /api/analytics/top-recipients?limit=20
GET /api/analytics/timeline?granularity=month&date_from=&date_to=
GET /api/analytics/heatmap
GET /api/analytics/network?limit=30
```

---

### 4.5 Errors

**Table from `error_log.txt`:**
- Timestamp
- Source file
- Error type
- Detail message

**Features:**
- Filter by error type (dropdown: MISSING_FIELD, PARSE_ERROR, DECODE_ERROR, UNEXPECTED_ERROR)
- Filter by mailbox (from source file path)
- Error distribution bar chart (count per type)
- Click source file → attempts to show the raw email file content (read from `data/maildir/`)

**API endpoints:**
```
GET /api/errors?type=MISSING_FIELD&mailbox=lay-k&page=1
GET /api/errors/stats
GET /api/errors/raw-file?path=maildir/lay-k/inbox/45
```

---

### 4.6 Notifications

**Send log table (from `output/send_log.csv`):**
- Timestamp
- Recipient
- Subject
- Status (sent/failed — color coded green/red)
- Error message (if failed)

**Summary:** X sent, Y failed, Z pending

**Draft preview:** List all `.eml` files in `output/replies/`. Click one to preview the notification content.

**Send actions:**
- **Send Single:** Select a draft `.eml` → click Send → calls Gmail MCP `send_email` via a backend endpoint that shells out to the pipeline's send logic
- **Send All Unsent:** Batch send all drafts that haven't been sent yet
- **Requires:** `--notify-address` configured (show input field for target email)

**API endpoints:**
```
GET  /api/notifications/log
GET  /api/notifications/drafts
GET  /api/notifications/drafts/<filename>
POST /api/notifications/send          (body: { draft: "filename.eml", notify_address: "..." })
POST /api/notifications/send-all      (body: { notify_address: "..." })
```

---

### 4.7 Pipeline Operations

**Run Pipeline:**
- Button: "Run Pipeline" with maildir path input (default: `data/maildir`)
- Shows real-time progress (poll a status endpoint or use Server-Sent Events)
- Displays the pipeline summary stats when complete
- Option: checkbox for "Include live send" (adds `--send-live`)

**Export Reports:**
- Download `duplicates_report.csv`
- Download `error_log.txt`
- Download `output/send_log.csv`
- Download `enron.db` (the full database)
- Each as a download button that serves the file directly

**Database Info:**
- Table count, row counts per table
- Database file size
- Schema viewer (shows `schema.sql` content)

**API endpoints:**
```
POST /api/pipeline/run        (body: { maildir: "data/maildir", send_live: false, notify_address: "" })
GET  /api/pipeline/status     (returns: running/idle/complete + stats)
GET  /api/export/<filename>   (serves file for download)
GET  /api/database/info
GET  /api/database/schema
```

---

## 5. Design Specifications

### Layout
- Sidebar navigation (collapsible) on the left, content area on the right
- Fixed header with project title + pipeline status indicator (idle/running)
- Responsive enough for 1280px+ laptop screens

### Typography
- System font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- Monospace for message IDs, file paths, SQL, email bodies: `"Cascadia Code", "Fira Code", Consolas, monospace`

### Color Palette
- Background: `#f8f9fa` (light) / `#1a1b1e` (dark)
- Cards: `#ffffff` / `#25262b`
- Primary: `#228be6` (blue)
- Success: `#40c057` (green)
- Error: `#fa5252` (red)
- Warning: `#fab005` (amber)
- Duplicate: `#be4bdb` (purple)
- Text: `#212529` / `#c1c2c5`
- Dark/light theme toggle in header

### Components
- **Summary cards:** Rounded corners, subtle shadow, large number + small label + sparkline
- **Tables:** Striped rows, sticky header, hover highlight, sortable columns, pagination
- **Charts:** Chart.js from CDN (bar, line, pie, heatmap via matrix plugin)
- **Sidebar:** Icon + label, active state highlighted, collapsible to icon-only
- **Email detail panel:** Slide-in from right, 40% width, scrollable
- **Diff view:** Two-column layout, deleted text in red background, added in green
- **Buttons:** Filled primary for actions, outlined for secondary, disabled state for in-progress
- **Toast notifications:** Bottom-right corner for send results, auto-dismiss after 5 seconds

---

## 6. Implementation Notes

### Single File Structure
Everything in `src/dashboard.py` — Flask app + HTML template + CSS + JS all embedded. The file will be long (~1500-2000 lines) but keeps deployment simple.

### Security
- Parameterized SQL for all queries
- Pipeline run uses subprocess with controlled arguments (no shell injection)
- Raw file viewer restricted to `data/maildir/` path prefix (no path traversal)
- No authentication (local use only)

### Performance
- Pagination on all list endpoints (never return all 10K+ emails at once)
- Search uses SQLite FTS if available, falls back to LIKE queries
- Chart data pre-aggregated in SQL, not computed in JS
- Lazy load email body — detail panel fetches on click, not on table render

### Pipeline Operations Safety
- Run button disabled while pipeline is running
- Live send requires explicit `notify_address` input — cannot send without it
- Confirmation dialog before "Send All" action
- All send results logged to `output/send_log.csv`

---

## 7. Acceptance Criteria

| # | Criterion |
|---|-----------|
| UI-1 | `python main.py --dashboard` opens browser-accessible page on :8050 |
| UI-2 | Overview shows correct stats matching CLI output |
| UI-3 | Email Explorer loads 50 emails with working pagination |
| UI-4 | Search returns relevant results within 2 seconds |
| UI-5 | Email detail panel shows full headers and body |
| UI-6 | Duplicate diff view highlights differences between original and duplicate |
| UI-7 | Reject duplicate updates DB correctly (is_duplicate → false) |
| UI-8 | Analytics charts render with real data |
| UI-9 | Activity heatmap shows hour × day grid |
| UI-10 | Pipeline run button triggers `main.py` and shows progress |
| UI-11 | Export buttons download the correct files |
| UI-12 | Send notification from UI successfully calls Gmail MCP |
| UI-13 | No JavaScript console errors |
| UI-14 | Page loads in under 3 seconds for 10K email dataset |
| UI-15 | Dark/light theme toggle works |

---

## 8. Time Budget

**Estimated effort:** 4-6 hours (this is a substantial dashboard now).

The conductor builds this in Phase 7. If the session is running long, it can build the core sections (Overview, Email Explorer, Duplicates) first and skip Analytics/Operations as stretch goals within the dashboard itself.

**Priority order within the dashboard:**
1. Overview (stats + charts) — minimum viable dashboard
2. Email Explorer (search + detail panel) — shows data exploration
3. Duplicate Management (diff view + confirm/reject) — shows interactivity
4. Errors + Notifications (tables + send) — shows pipeline integration
5. Analytics (charts + heatmap) — shows data analysis skills
6. Pipeline Operations (run + export) — shows full-stack thinking
7. Network graph — stretch goal
