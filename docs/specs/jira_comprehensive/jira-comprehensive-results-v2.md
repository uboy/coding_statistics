# Jira Comprehensive Report: Results Coverage for All Resolved Issues v2

## Summary
Problem: The Results sheet currently only includes issues that have a “Result:” comment, but the requirement is to list all resolved issues with resolution status Done/Resolved even when no Result comment exists, explicitly stating “no results”.

Goals:
- Results sheet includes **all resolved issues** where Resolution is “Done” or “Resolved”.
- If an issue has no “Result:” comment, the Results sheet still includes a row and explicitly states “no results” in the Result field.
- Keep existing behavior for issues with Result comments (extract full comment and links).

Non-goals:
- Changing Jira query logic or adding new CLI parameters.
- Changing other sheets beyond what’s needed to support Results coverage.
- Adding new dependencies.

## Scope boundaries
In scope:
- Update Results extraction to produce entries for all resolved issues.
- Update Results sheet schema population to include placeholder Result text when missing.
- Tests for no-Result issues inclusion.

Out of scope:
- Changes to Issues sheet or Links sheet beyond existing v1 spec.
- Changes to weekly reports.

## Assumptions + constraints
- No new dependencies without explicit approval (AGENTS.md).
- Minimal additive diffs.
- Tests must be run with `pytest tests` (AGENTS.md).
- “Resolved issues” definition uses Resolution field values “Done” or “Resolved” for this requirement.

## Architecture
### Components
- `stats_core/reports/jira_comprehensive.py`:
  - Extend Results extraction to include all resolved issues.
  - Map resolved issues with/without Result comments into Results rows.

### Data flow
1. Build issues_df as before.
2. Identify resolved issues where `Resolution` is “Done” or “Resolved”.
3. For each resolved issue:
   - If Result comments exist, create a row per Result comment (same as v1).
   - If none exist, create a single row with Result = “no results” and Result_Links = comment link fallback (issue link if no comment id).

## Interfaces / contracts
### Results sheet schema (unchanged)
- `Issue_Key`, `Summary`, `Assignee`, `Result`, `Result_Links`

### Resolution filter
- Use issues_df `Resolution` column values `"Done"` and `"Resolved"` (case-insensitive) to determine inclusion for Results coverage.

### No-results placeholder
- For resolved issues without Result comments:
  - `Result` = `"no results"`
  - `Result_Links` = issue URL (or comment URL if available)

### Error handling
- Missing Resolution column → treat as no resolved issues.
- Missing Assignee → “Unassigned”.

## Data model changes + migrations
- None (in-memory only).

## Edge cases + failure modes
- Multiple Result comments → multiple rows, plus no extra placeholder row.
- Resolution values other than Done/Resolved → excluded from Results.
- Issues resolved but missing Resolution value → excluded (per requirement).

## Security requirements
- No auth changes, no new deps.
- Result text treated as untrusted; sanitize via existing Excel sanitizer.

## Performance requirements + limits
- O(n) over issues; avoid extra Jira calls.

## Observability
- Log counts: resolved issues total, Results rows created.

## Test plan
- Unit test: resolved issue without Result comment still appears with Result = “no results”.
- Unit test: resolved issue with Result comment still appears with comment text.
- Run: `pytest tests`.

## Rollout plan + rollback plan
- Rollout: update Results extraction logic and tests.
- Rollback: revert Results coverage changes.

## Acceptance criteria checklist
- Results sheet includes all issues with Resolution “Done” or “Resolved”.
- Issues with no Result comments appear with Result = “no results”.
- Issues with Result comments preserve existing Result extraction and links.
- No new dependencies; tests pass with `pytest tests`.

## Approval
APPROVED:v1
