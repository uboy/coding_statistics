# Implementation Plan — Jira Summary Sanitization + Worklog Assistance (v1)

## Objective
Implement two approved behavior fixes:
1. Remove Jira keys from summary output.
2. Compute engineer `Assistance_Provided` from unique foreign issues in `worklog_entries`.

## Work breakdown

### EPIC A — Summary output sanitization
Task A1 — Enforce key removal in summary text
- Update summary line rendering to avoid prefixing/including issue key.
- Ensure final sanitizer strips Jira keys from AI and fallback outputs.

Task A2 — Add/adjust tests for key-free summary
- Validate no `ABC-123` style tokens in summary output.

### EPIC B — Engineer assistance from worklogs
Task B1 — Extend metric function contract
- Add `worklog_entries_df` argument to `calculate_engineer_metrics`.

Task B2 — Implement foreign-issue assistance algorithm
- Build engineer identity set.
- Match `Worklog_Author` to engineer.
- Compare against issue assignee identity.
- Count unique foreign `Issue_Key` as assistance.

Task B3 — Wire through report run path
- Pass `worklog_entries_df` into engineer metric calculation.

Task B4 — Test coverage
- Add case: multiple logs same foreign issue count once.
- Add case: log in own task not counted.

### EPIC C — Verification
Task C1 — Focused tests
- run targeted comprehensive + weekly tests.

Task C2 — Full regression
- run `pytest tests`.

## Dependency sequence
1. A1 -> A2
2. B1 -> B2 -> B3 -> B4
3. A2 + B4 -> C1
4. C1 -> C2

## Risks
- Identity mismatch between Jira usernames/display names in worklogs vs issues.
  - Mitigation: normalize and use same identifier strategy as current metrics.
- Unexpected summary formatting regressions.
  - Mitigation: minimal rendering changes + regression tests.

## Exit criteria
- Acceptance criteria from design spec all PASS.
- Full test suite green.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
