---
name: git-workflow
description: Follow project git conventions when committing, branching, or pushing code. Use this for conventional commits, commit message formatting, and the commit-after-each-phase workflow.
---

# Git Workflow for Enron Pipeline

## Conventional Commits
Every commit message follows this format:
```
<type>(<scope>): <description>
```

### Types
- `feat` — New feature or module
- `fix` — Bug fix
- `test` — Adding or updating tests
- `docs` — Documentation changes
- `chore` — Tooling, config, dependencies
- `refactor` — Code restructuring without behavior change

### Scopes
- `database` — schema.sql, src/database.py
- `discovery` — src/discovery.py
- `parser` — src/parser.py
- `dedup` — src/dedup.py
- `notifier` — src/notifier.py
- `dashboard` — src/dashboard.py
- `integration` — test_integration.py, sample_queries.sql

### Examples
```
feat(database): add schema and database module with insert/query functions
feat(parser): add email parsing with RFC 2822 support and edge case handling
fix(parser): handle CDT timezone abbreviation correctly
test(dedup): add fuzzy matching threshold edge case tests
docs: add README with setup instructions and architecture overview
chore: initial project setup with agent architecture
```

## Commit After Each Phase
The conductor commits after each passing phase:
1. Phase 1 complete → `feat(database): add schema, models, and database module`
2. Phase 2 complete → `feat(parser): add discovery and email parsing modules`
3. Phase 3 complete → `feat(dedup): add pipeline orchestration and duplicate detection`
4. Phase 4 complete → `feat(notifier): add notification generation and send logging`
5. Phase 5 complete → `test(integration): add end-to-end tests and sample queries`
6. Phase 6 complete → `feat: validate pipeline on real Enron data (N emails parsed)`
7. Phase 7 complete → `feat(dashboard): add local pipeline results dashboard`
8. Phase 8 complete → `docs: add README and MCP config example`
9. Phase 9 complete → `chore: finalize project for submission`

## Git Commands
```bash
# Stage all changes
git add -A

# Commit with message
git commit -m "feat(parser): add email parsing with full edge case handling"

# Push to remote (if GitHub MCP is connected, prefer MCP push)
git push origin main
```

## What NOT to Commit
Already in .gitignore but worth remembering:
- `data/maildir/` — too large
- `*.db` — generated
- `mcp_config.json` — real credentials
- `.env` — secrets
- `__pycache__/` — generated
