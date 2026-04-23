---
name: build-pipeline
description: Build the entire Enron Email Pipeline project from scratch. Invoke with /build-pipeline to start the autonomous build. Delegates to the conductor agent which orchestrates all phases including code, review, testing, real data validation, and final audit.
---

# Build the Enron Email Pipeline

Use the **conductor** agent to build the entire project from scratch.

## Context
- `CLAUDE.md` (auto-loaded) has all decisions, coding standards, and patterns
- `docs/SRS.md` has full requirements
- `docs/TESTING.md` has every test case
- `docs/UI.md` has the dashboard spec

## Instructions

Invoke the conductor agent with this task:

Build the entire Enron Email Pipeline project from scratch. Follow the build order and quality gates defined in your conductor instructions. For each module:

1. Implement following docs/SRS.md requirements and project coding standards
2. Delegate to code-reviewer agent to verify spec compliance
3. Delegate to test-runner agent to execute tests and check coverage
4. Fix any issues, re-verify until clean
5. Commit with conventional commit message and push if GitHub MCP is connected

After all code phases are complete (Phases 1-6), run the pipeline on the real Enron dataset in `data/maildir/`. Then delegate to the error-analyzer agent to diagnose results. Fix any parser issues found and re-run until clean.

Then complete documentation (Phase 8), and run the deliverable-auditor agent for final validation (Phase 9).

Track progress after each phase.
