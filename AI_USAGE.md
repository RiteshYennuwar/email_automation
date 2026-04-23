# AI_USAGE.md — AI Tool Usage Documentation
## Enron Email Data Extraction Pipeline

---

## 1. Tool Used

- **Primary tool:** Claude Code v2.1.92
- **Project configuration:**
  - `CLAUDE.md` at project root (auto-loaded context with full project spec, decisions, conventions)
  - `.claude/settings.json` for scoped tool permissions
  - `.mcp.json` for MCP server registration (Gmail, SQLite, GitHub)
  - Supporting context files: `docs/SRS.md`, `docs/TESTING.md`, `docs/UI.md`
  - Custom subagents in `.claude/agents/`: `conductor`, `code-reviewer`, `test-runner`, `error-analyzer`, `deliverable-auditor`
  - Custom skills in `.claude/skills/`: `/build-pipeline`, `/python-standards`, `/email-parsing`, `/test-first`, `/git-workflow`
- **Secondary tools:** None. The entire project was built using Claude Code exclusively.

---

## 2. Prompting Strategy

### Overall Approach

The project was built using a single entry-point prompt — the `/build-pipeline` skill — which delegated the full autonomous build to the `conductor` subagent. No follow-up prompts were issued during the build itself. The heavy lifting was done upfront by writing detailed reference documents (`CLAUDE.md`, `docs/SRS.md`, `docs/TESTING.md`, `docs/UI.md`) before starting.

The setup phase (writing CLAUDE.md, configuring MCP servers, creating skills and subagents) was done manually with assistance from Claude Code in a separate prior session.

**Build phases executed autonomously:**
- Phase 1: Schema design (`schema.sql`)
- Phase 2: Database module (`src/database.py`)
- Phase 3: File discovery (`src/discovery.py`)
- Phase 4: Email parsing (`src/parser.py`)
- Phase 5: Dedup detection (`src/dedup.py`)
- Phase 6: Notification generation (`src/notifier.py`)
- Phase 7: Integration tests + real data validation
- Phase 8: Dashboard (`src/dashboard.py`)
- Phase 9: Documentation (`README.md`)

### Example Prompts

#### Prompt 1: Project kickoff — `/build-pipeline`

```
/build-pipeline
```

**Why this structure:** The skill expands to a full conductor agent invocation with all build instructions. By encoding the full spec into `CLAUDE.md` and `docs/SRS.md` beforehand, this single command gave the agent everything it needed. No task-by-task prompting was required.

**Result:** The conductor built all 8 source modules, ran tests after each phase, fixed failures, and committed after each passing phase — fully autonomously from a single command.

---

#### Prompt 2: CLAUDE.md creation (setup phase)

```
Help me write a CLAUDE.md for this project. The project is a Python CLI pipeline that:
- Ingests raw Enron email files (RFC 2822 format)
- Extracts structured fields into SQLite
- Detects near-duplicate emails using fuzzy matching
- Sends automated notifications via Gmail MCP

Include: stack, build order, module responsibilities, coding standards, critical design
decisions, MCP server config, and a deliverable checklist.
```

**Why this structure:** Providing the full scope upfront let Claude generate a comprehensive context file in one shot rather than iterating. The explicit list of required sections prevented gaps.

**Result:** Generated a complete CLAUDE.md covering all sections. Minor manual edits were made to add Enron-specific mailbox names and the exact notification email template.

---

#### Prompt 3: SRS reference document

```
Write a Software Requirements Specification for this Enron email pipeline project.
Cover: functional requirements for each module, data model (emails + email_recipients tables
with exact column names and types), duplicate detection algorithm, MCP integration
requirements, and acceptance criteria. Reference the assignment spec below:
[pasted assignment text]
```

**Why this structure:** A formal SRS gave the conductor agent a machine-readable spec to check against during code review, beyond the informal CLAUDE.md. The explicit data model prevented schema drift between modules.

**Result:** Clean SRS on first attempt. Used as ground truth by the `code-reviewer` subagent during each phase.

---

#### Prompt 4: MCP server configuration

```
Help me set up the Gmail MCP server for this project. I need to:
1. Configure .mcp.json with @gongrzhe/server-gmail-autoauth-mcp
2. Set up Google OAuth credentials
3. Understand where credential files should live (not committed to git)
4. Test that the server starts and can authenticate
```

**Why this structure:** Breaking MCP setup into 4 explicit subtasks avoided getting a generic answer. Specifying "not committed to git" explicitly prevented Claude from suggesting committing credentials.

**Result:** Complete setup instructions in one response. OAuth flow worked on first attempt.

---

#### Prompt 5: Dashboard specification (`docs/UI.md`)

```
Write a dashboard specification for a Flask web UI that visualizes Enron email pipeline results.
The dashboard should have 7 sections: Overview stats, Email browser, Duplicate groups,
Analytics charts, Notifications log, Database explorer, and Pipeline controls.
Include exact API endpoint paths, query parameters, and response shapes for each section.
```

**Why this structure:** Specifying the 7 sections and requiring exact API shapes meant the conductor could build `src/dashboard.py` without ambiguity about endpoints or data formats.

**Result:** The `docs/UI.md` spec was detailed enough that the dashboard was built without any back-and-forth.

---

## 3. Iterations & Debugging

### Case 1: Notifier tests failing due to leftover `.eml` files

**What happened:**
During Phase 6 (integration tests), the `test_notifier.py` tests were failing intermittently. The tests checked that `generate_notifications()` produced at least one `.eml` file in `output/replies/`, but the assertion was unreliable.

**What went wrong:**
The notifier writes `.eml` files to `output/replies/` but the test never cleaned the directory before running. When the pipeline had been run previously (e.g., on real data), leftover `.eml` files from prior runs were present. The test was asserting on a count that included stale files from other runs, making test isolation impossible.

**Error output:**
```
FAILED tests/test_notifier.py::TestNotifier::test_eml_file_content - AssertionError:
assert 'Term Paper' in eml_content
# eml_content was from a stale file, not the one just generated
```

**How I fixed it:**
The conductor added a cleanup step at the start of each notifier test that deletes all existing `.eml` files before asserting:

```python
# Clean output dir first
for f in OUTPUT_DIR.glob("*.eml"):
    f.unlink()
```

**Lesson:** Test isolation requires explicit teardown of shared output directories. The AI initially omitted this because the test looked correct in isolation — the bug only appeared when tests ran after a real pipeline run had populated the output directory.

---

### Case 2: Windows trailing-dot filenames crashing discovery

**What happened:**
During Phase 7 (real data validation on 92,126 Enron emails), the pipeline crashed with a `FileNotFoundError` on a large subset of files. The initial `discover_email_files()` used `pathlib.Path.rglob()` and returned `Path` objects.

**What went wrong:**
Many Enron email filenames end with a dot (e.g., `lay-k/_sent/97.`). On Windows, the Win32 API silently strips trailing dots from filenames, so `Path("lay-k/_sent/97.")` resolves to `Path("lay-k/_sent/97")` — a path that does not exist. `pathlib` was normalizing the filenames before they could be opened, causing silent failures or crashes on thousands of files.

**Error output:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'data/maildir/lay-k/_sent/97'
# The trailing dot was stripped by Windows path normalization
```

**How I fixed it:**
The conductor rewrote `discover_email_files()` to use `os.walk()` with raw string paths instead of `pathlib.Path`, and added a `safe_open_path()` helper that prepends the `\\?\` extended-length path prefix on Windows to bypass Win32 normalization:

```python
# Preserves trailing dots — pathlib strips them on Windows
full_path = dp + os.sep + fname
rel = full_path[prefix_len:]
email_files.append(rel)  # stored as str, not Path
```

```python
def safe_open_path(maildir: Path, rel_path: str) -> str:
    if IS_WINDOWS:
        return "\\\\?\\" + str(maildir.resolve()) + os.sep + rel_path
    return str(maildir / rel_path)
```

**Refined prompt:**
```
The discovery module is failing on Windows because Enron filenames end with dots
(e.g., "97.") and pathlib strips trailing dots via Win32 normalization. Fix
discover_email_files() to preserve trailing dots by using os.walk with string paths,
and add a safe_open_path() helper that uses the \\?\ extended-length prefix on Windows.
```

**Lesson:** `pathlib` is not safe for all filenames on Windows. The Enron dataset specifically has trailing-dot filenames that require OS-level path handling to open correctly. This bug only appeared on real data — fixtures didn't expose it.

---

### Case 3: MCP subprocess sent emails that never arrived

**What happened:**
After implementing `_send_via_mcp()` using the MCP Python SDK to spawn the Gmail MCP server as a subprocess and call `send_email`, the function returned `True` (success) and the server logs showed `"MCP send_email succeeded"`, but no emails were received in the inbox.

**What went wrong:**
Two bugs in the MCP tool call arguments:
1. The `to` parameter was passed as a bare string (`"user@gmail.com"`) instead of a list (`["user@gmail.com"]`). The Gmail MCP server's `send_email` tool schema requires `to` to be an array. The server silently accepted the malformed parameter and returned success without actually sending.
2. The subprocess didn't inherit the correct `HOME`/`USERPROFILE` environment variables on Windows, so the Gmail MCP server couldn't find its OAuth credentials at `~/.gmail-mcp/credentials.json`.

**Error output:**
```
# No error — that was the problem. The MCP protocol returned isError: False
# but Gmail never received the message.
MCP send_email succeeded for yennuwar.ritesh@gmail.com
```

**How I fixed it:**
```python
# Bug 1: to must be a list, not a string
"to": [recipient],  # was: "to": recipient

# Bug 2: explicit env vars for subprocess credential discovery
home = str(Path.home())
env = {**os.environ, "USERPROFILE": home, "HOME": home}
server_params = StdioServerParameters(command=command, args=args, env=env)
```

**Lesson:** MCP tool calls can return success at the protocol level even when the underlying operation silently fails due to parameter type mismatches. Always verify the actual side-effect (check your inbox, query the DB, etc.) rather than trusting the return status. The Gmail MCP server's `send_email` tool schema specifies `to` as `{"type": "array", "items": {"type": "string"}}` — passing a bare string doesn't trigger a schema validation error, it just gets ignored.

---

## 4. What I Wrote vs. What AI Wrote

### Percentage Breakdown

| Component | AI-Generated | Human-Written | Human-Reviewed/Edited |
|-----------|-------------|---------------|----------------------|
| Project setup & config (`CLAUDE.md`, `.mcp.json`, skills, agents) | 60% | 40% | 100% |
| `src/parser.py` | 100% | 0% | 100% |
| `src/database.py` | 100% | 0% | 100% |
| `src/dedup.py` | 100% | 0% | 100% |
| `src/notifier.py` | 100% | 0% | 100% |
| `src/dashboard.py` | 100% | 0% | 100% |
| `main.py` | 100% | 0% | 100% |
| Tests | 100% | 0% | 100% |
| Documentation (`README.md`, `docs/`) | 95% | 5% | 100% |
| **Overall** | **~95%** | **~5%** | **100%** |

### Sections I Wrote Manually

- **Project configuration:** Wrote the initial `CLAUDE.md` structure, selected the 5 Enron mailboxes (`lay-k`, `skilling-j`, `kaminski-v`, `dasovich-j`, `kean-s`), and defined the exact notification email template — these were design decisions made before the AI started building.
- **MCP server selection:** Chose `@gongrzhe/server-gmail-autoauth-mcp` after evaluating alternatives; configured `.mcp.json` and ran the OAuth authentication flow manually.
- **Subagent and skill definitions:** Wrote the `.claude/agents/` and `.claude/skills/` files that define the conductor pipeline, with Claude's assistance in structuring the prompts within them.

### Sections the AI Generated Well

- **Schema DDL** (`schema.sql`): Correct on first attempt after providing the SRS data model. All required columns, indexes, FK constraints, and CHECK constraints were included without prompting.
- **Email parsing** (`src/parser.py`): The `email` stdlib usage, timezone-aware date parsing with `python-dateutil`, address normalization, and forwarded content extraction were all generated cleanly.
- **Duplicate detection algorithm** (`src/dedup.py`): The grouping strategy (by sender + normalized subject before fuzzy-matching bodies) was specified in CLAUDE.md and implemented correctly, including the "earliest = original" tie-breaking logic.
- **CLI argument parsing** (`main.py`): Generated perfectly from the CLAUDE.md spec — all 5 flags with correct defaults and validation.

---

## 5. MCP Integration

### 5.1 MCP Server Choice

**Server:** `@gongrzhe/server-gmail-autoauth-mcp`

**Why this server:**
- Supports Google OAuth 2.0 with auto-authentication (handles token refresh automatically)
- Actively maintained with clear documentation
- Compatible with Claude Code's MCP tool invocation model
- Provides a straightforward `send_email` tool with all required parameters (to, subject, body, inReplyTo)
- No API key required — uses standard Google OAuth flow

**Alternatives considered:**
- `@modelcontextprotocol/server-gmail` — rejected because it requires more manual OAuth wiring and has less active maintenance
- Direct Gmail REST API via a custom MCP server — rejected because it adds unnecessary complexity when a working server already exists

### 5.2 Setup Instructions

1. **Google Cloud Console setup:**
   - Create a new project at console.cloud.google.com
   - Enable the Gmail API under "APIs & Services"
   - Create OAuth 2.0 credentials (Desktop application type)
   - Download the credentials file as `gcp-oauth.keys.json`

2. **MCP server installation:**
   ```bash
   # No separate install needed — npx handles it on first run
   npx @gongrzhe/server-gmail-autoauth-mcp auth
   ```

3. **Configuration:**
   - Place `gcp-oauth.keys.json` in `~/.gmail-mcp/`
   - The `.mcp.json` at project root registers the server:
     ```json
     "gmail": {
       "command": "cmd",
       "args": ["/c", "npx", "-y", "@gongrzhe/server-gmail-autoauth-mcp"]
     }
     ```
   - No additional environment variables required for Gmail

4. **Authentication flow:**
   - Run `npx @gongrzhe/server-gmail-autoauth-mcp auth` once
   - Browser opens for Google OAuth consent
   - Token stored automatically in `~/.gmail-mcp/token.json`
   - Subsequent runs use the stored token; refresh is automatic

5. **Verification:**
   ```bash
   # Claude Code will show Gmail MCP tools in the tool list on startup
   # Verify by asking Claude Code: "list available MCP tools"
   ```

### 5.3 Prompting the AI to Use MCP

The Gmail MCP send was invoked directly through Claude Code's tool calling capability rather than from within the Python pipeline code. The pipeline's `_send_via_mcp()` function acts as a stub that logs intent; Claude Code itself calls `mcp__gmail__send_email` when live sending is needed.

#### Example prompt:
```
Use the Gmail MCP tool to send one notification email to yennuwar.ritesh@gmail.com
with subject "[Duplicate Notice] Re: Term Paper" using the content from
output/replies/10030690.1075840787262.JavaMail.evans_at_thyme.eml
```

#### What happened:
Claude Code discovered the `mcp__gmail__send_email` tool automatically from the registered MCP server. The tool was called with the correct parameters (to, subject, body, inReplyTo) and returned a successful message ID on the first attempt.

### 5.4 Issues & Resolutions

| Issue | Resolution |
|-------|-----------|
| MCP `_send_via_mcp()` stub always returned `False` | Replaced stub with real implementation using the MCP Python SDK (`mcp` package). The pipeline now spawns the Gmail MCP server as a subprocess via `StdioServerParameters` and calls `send_email` through `ClientSession`. |
| MCP subprocess returned success but emails not delivered | Root cause: the `to` parameter must be a **list** (`["user@gmail.com"]`), not a bare string. The Gmail MCP server silently accepted the malformed parameter without sending. Fixed by wrapping recipient in a list. |
| MCP subprocess couldn't find OAuth credentials on Windows | Subprocess inherited a different `HOME`/`USERPROFILE`. Fixed by explicitly passing `env={**os.environ, "USERPROFILE": home, "HOME": home}` to `StdioServerParameters`. |
| Running `--send-live` on full DB would send ~19,178 emails | Used the dashboard UI to send individual notifications selectively, or fixture data for proof-of-concept testing. |
| Token expiry during long pipeline runs | Added a Gmail REST API fallback (`_send_via_gmail_api`) that reads credentials from `~/.gmail-mcp/credentials.json` and auto-refreshes expired tokens. MCP SDK is primary; REST API is fallback only. |

### 5.5 Proof of Successful Send

#### Method 1: MCP Python SDK (from dashboard UI)

The dashboard Notifications tab has a "Send" button per draft that calls `_send_via_mcp_sdk()`,
which spawns `@gongrzhe/server-gmail-autoauth-mcp` via the MCP Python SDK and invokes `send_email`.

**Server log output (Flask console):**
```
MCP send_email succeeded for yennuwar.ritesh@gmail.com: Email sent successfully with ID: 19dbbff1460f464e
127.0.0.1 - - [23/Apr/2026 16:19:08] "POST /api/notifications/send HTTP/1.1" 200 -
MCP send_email succeeded for yennuwar.ritesh@gmail.com: Email sent successfully with ID: 19dbbff4b84af338
10.244.195.201 - - [23/Apr/2026 16:19:22] "POST /api/notifications/send HTTP/1.1" 200 -
```

#### Method 2: Claude Code MCP tool (direct invocation)

Claude Code also sent emails via its built-in MCP connection to the same Gmail server:

```
Email sent successfully with ID: 19dbbcb50f2276f4
Email sent successfully with ID: 19dbbecf335773ac
Email sent successfully with ID: 19dbbfbdcfd1e619
```

#### Send log excerpt (`output/send_log.csv`)

```csv
timestamp,recipient,subject,status,error
2026-04-23T20:19:08.769135+00:00,yennuwar.ritesh@gmail.com,[Duplicate Notice] Re: Term Paper,sent,
2026-04-23T20:19:22.650705+00:00,yennuwar.ritesh@gmail.com,[Duplicate Notice] Re: EGM All Employee Meeting,sent,
2026-04-23T20:07:38.794119+00:00,yennuwar.r@northeastern.edu,[Duplicate Notice] Re: Info,sent,
```

Multiple emails confirmed delivered to both `yennuwar.ritesh@gmail.com` and `yennuwar.r@northeastern.edu`.

> **Screenshot:** See Gmail inbox for received "[Duplicate Notice]" emails as visual confirmation of successful delivery. Also see the dashboard Notifications tab send log showing "sent" status badges.

---

## 6. Lessons Learned

### What Worked Well

- **Upfront context investment pays off:** Writing detailed `CLAUDE.md`, `docs/SRS.md`, and reference docs before starting meant the conductor agent rarely needed clarification. The single `/build-pipeline` command produced a working pipeline.
- **Subagent specialization:** Using separate agents for code review, testing, and auditing meant each phase got dedicated attention rather than one agent context juggling everything.
- **Test-first build order:** The conductor's approach of writing tests before or alongside each module caught bugs (like the notifier test isolation issue) before they compounded.
- **Conventional commits per phase:** Each commit message documents what was built, making the git log a readable build diary.

### What Was Harder Than Expected

- **Windows path edge cases:** The Enron dataset's trailing-dot filenames are a Windows-specific issue that didn't surface until running on real data. Standard `pathlib` usage fails silently, requiring OS-level workarounds.
- **Test isolation with shared filesystem state:** Tests that write to `output/replies/` need explicit teardown. The AI's initial test code assumed a clean state, which is only true on the first run.
- **MCP live sending at scale:** The pipeline's `--send-live` mode triggers notifications for all 19,178 duplicate groups. Wiring MCP into the pipeline code itself (vs. calling it from Claude Code) requires a different architecture — the pipeline would need to spawn an MCP client process, which adds complexity beyond the scope of this assignment.

### Recommendations for Others Using AI Coding Tools

- **Write the spec before the code:** The more precise your upfront documentation (CLAUDE.md, SRS, data model), the fewer corrections you need to make mid-build. Ambiguity in specs becomes bugs in code.
- **Use subagents for quality gates:** Don't let the same agent that wrote the code also review it. Separate reviewer and test-runner agents catch issues the builder misses.
- **Test on real data early:** Fixture-based tests pass on clean, well-formed data. Real datasets (like Enron) expose encoding issues, malformed headers, and OS-specific path problems that fixtures never will.
- **Approve tool calls mindfully:** Claude Code pauses for approval on bash commands, file writes, and git commits. Reviewing these approvals is where you catch unintended side effects — e.g., a pipeline run that would send 19,000 emails.

---

## Appendix: Session Log

| Session | Duration | Focus | Key Outcomes |
|---------|----------|-------|-------------|
| 1 | ~2 hrs | Project setup: CLAUDE.md, MCP config, skills, agents, reference docs | CLAUDE.md finalized, `.mcp.json` configured, all subagents and skills created, Gmail OAuth authenticated |
| 2 | ~1 hrs | Full autonomous build via `/build-pipeline` | All 8 source modules built, 68 tests passing, real data validated (85,258 emails), dashboard live |
| 3 | ~1 hr | AI_USAGE.md, deliverable fixes (coverage, report CSV, error log) | AI_USAGE.md complete, 86% test coverage, real data deliverables committed |
