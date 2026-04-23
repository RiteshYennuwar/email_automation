# AI_USAGE.md — AI Tool Usage Documentation
## Enron Email Data Extraction Pipeline

> **Note to self:** Fill this in as you build. Don't try to write it all at the end — capture prompts, errors, and decisions in real time. Each section below has guidance on what the evaluator wants to see.

---

## 1. Tool Used

- **Primary tool:** Claude Code (version: _fill in_)
- **Project configuration:** 
  - `CLAUDE.md` at project root (auto-loaded context with full project spec, decisions, conventions)
  - `.claude/settings.json` for scoped permissions
  - `.mcp.json` for Gmail MCP server registration
  - Supporting context files: `docs/SRS.md`, `docs/TESTING.md`, `docs/UI.md`
- **Secondary tools (if any):** _e.g., GitHub Copilot for autocomplete, manual edits for X_

---

## 2. Prompting Strategy

### Overall Approach

_Describe how you broke the problem down. Did you:_
- _Feed the full assignment spec at once, or task-by-task?_
- _Use the reference docs (SRS.md, TESTING.md) as context, or prompt from scratch?_
- _Start with the hardest part (parsing) or the simplest (schema)?_

**Recommended structure to document:**
- Phase 1: Project setup & schema design
- Phase 2: Email parsing (the core challenge)
- Phase 3: Database storage & insertion
- Phase 4: Duplicate detection
- Phase 5: Notification generation & MCP integration
- Phase 6: Real data validation & diagnostics
- Phase 7: Dashboard
- Phase 8: Documentation & polish

### Example Prompts (minimum 3-5, with rationale)

#### Prompt 1: _[Title — e.g., "Initial schema design"]_

```
[Paste the actual prompt you used]
```

**Why this structure:** _Explain why you worded it this way. Did you constrain the output format? Provide examples? Reference the SRS?_

**Result:** _Did it work on first try? What was the quality like?_

---

#### Prompt 2: _[Title — e.g., "Date parsing edge cases"]_

```
[Paste the actual prompt you used]
```

**Why this structure:** _..._

**Result:** _..._

---

#### Prompt 3: _[Title — e.g., "Duplicate detection algorithm"]_

```
[Paste the actual prompt you used]
```

**Why this structure:** _..._

**Result:** _..._

---

#### Prompt 4: _[Title — e.g., "MCP Gmail integration"]_

```
[Paste the actual prompt you used]
```

**Why this structure:** _..._

**Result:** _..._

---

#### Prompt 5: _[Title — e.g., "Fixing forwarded content extraction"]_

```
[Paste the actual prompt you used]
```

**Why this structure:** _..._

**Result:** _..._

---

## 3. Iterations & Debugging

_The evaluator explicitly wants at least 2 cases where AI output didn't work. Be honest — this is where you demonstrate critical thinking._

### Case 1: _[Module/feature that failed]_

**What happened:**
_Describe what you prompted for and what the AI produced._

**What went wrong:**
_Be specific — wrong logic? Missing edge case? Bad library usage? Syntax error?_

**Error output:**
```
[Paste actual error messages or wrong output]
```

**How I fixed it:**
_Did you refine the prompt? Manually edit the code? Add a test case that exposed the bug? Show the iterative steps._

**Refined prompt (if applicable):**
```
[The follow-up prompt that got it right]
```

**Lesson:** _What did this teach you about prompting or about the problem?_

---

### Case 2: _[Module/feature that failed]_

**What happened:** _..._

**What went wrong:** _..._

**Error output:**
```
[...]
```

**How I fixed it:** _..._

**Lesson:** _..._

---

_Add more cases if they occurred — the evaluator values thoroughness here._

---

## 4. What I Wrote vs. What AI Wrote

### Percentage Breakdown

| Component | AI-Generated | Human-Written | Human-Reviewed/Edited |
|-----------|-------------|---------------|----------------------|
| Project setup & config | __%  | __% | __% |
| `src/parser.py` | __% | __% | __% |
| `src/database.py` | __% | __% | __% |
| `src/dedup.py` | __% | __% | __% |
| `src/notifier.py` | __% | __% | __% |
| `src/dashboard.py` | __% | __% | __% |
| `main.py` | __% | __% | __% |
| Tests | __% | __% | __% |
| Documentation | __% | __% | __% |
| **Overall** | **__%** | **__%** | **__%** |

### Sections I Wrote Manually

_List specific things you wrote or substantially rewrote by hand. Examples:_
- _"I manually wrote the regex patterns for forwarded content detection after the AI's version missed the Enron-specific `Forwarded by` format"_
- _"I designed the duplicate grouping strategy (group by sender+subject before fuzzy matching) — the AI initially tried to compare all pairs, which was O(n²)"_
- _"I wrote the test fixtures by hand from real Enron email samples"_

### Sections the AI Generated Well

_List things the AI got right on the first or second try:_
- _"Schema DDL was solid on first attempt after providing the SRS data model"_
- _"The CLI argument parsing was generated perfectly from a one-line prompt"_
- _"Basic email header extraction using Python's `email` library was clean"_

---

## 5. MCP Integration

_This is a dedicated section the assignment specifically requires._

### 5.1 MCP Server Choice

**Server:** _e.g., `@gongrzhe/server-gmail-autoauth-mcp`_

**Why this server:**
_Justify. Consider: documentation quality, OAuth support, active maintenance, compatibility with Claude Code, ease of setup._

**Alternatives considered:**
- _Server X — rejected because..._
- _Server Y — rejected because..._

### 5.2 Setup Instructions

_Step-by-step, as if the evaluator will reproduce this:_

1. **Google Cloud Console setup:**
   - _Create project_
   - _Enable Gmail API_
   - _Create OAuth 2.0 credentials_
   - _Download `credentials.json`_

2. **MCP server installation:**
   ```bash
   [exact commands]
   ```

3. **Configuration:**
   - _Where to place credential files_
   - _How `.mcp.json` references them_
   - _Environment variables needed_

4. **Authentication flow:**
   - _First-run OAuth consent_
   - _Token storage location_

5. **Verification:**
   ```bash
   [command to verify MCP server is working]
   ```

### 5.3 Prompting the AI to Use MCP

_Show how you instructed Claude Code to send emails via the MCP tool._

#### Example prompt:
```
[Paste the actual prompt you used to get Claude Code to send an email via MCP]
```

#### What happened:
_Did Claude Code discover the MCP tool automatically? Did you need to be explicit about tool names?_

### 5.4 Issues & Resolutions

| Issue | Resolution |
|-------|-----------|
| _e.g., OAuth token expired mid-run_ | _e.g., Added token refresh logic / re-authed manually_ |
| _e.g., MCP server didn't start_ | _e.g., Missing npm dependency, fixed with..._ |
| _e.g., Rate limiting from Gmail API_ | _e.g., Added delay between sends_ |

### 5.5 Proof of Successful Send

_The assignment requires "a screenshot or log excerpt showing at least one successful email send in live mode."_

**Screenshot:**
_Insert screenshot here showing a received notification email in your Gmail inbox._

**Log excerpt:**
```
[Paste relevant lines from output/send_log.csv or terminal output showing successful send]
```

---

## 6. Lessons Learned

### What Worked Well
- _..._
- _..._
- _..._

### What Was Harder Than Expected
- _..._
- _..._
- _..._

### Recommendations for Others Using AI Coding Tools
- _..._
- _..._
- _..._

---

## Appendix: Session Log

_Optional but impressive: a chronological log of your major Claude Code sessions._

| Session | Duration | Focus | Key Outcomes |
|---------|----------|-------|-------------|
| 1 | _~X hrs_ | Project setup, schema | _Schema finalized, CLAUDE.md created_ |
| 2 | _~X hrs_ | Parser development | _Core parsing working, 15 test cases passing_ |
| 3 | _~X hrs_ | Database + dedup | _Full pipeline dry-run working_ |
| 4 | _~X hrs_ | MCP integration | _Live send confirmed_ |
| 5 | _~X hrs_ | Testing + polish | _All tests green, docs complete_ |
