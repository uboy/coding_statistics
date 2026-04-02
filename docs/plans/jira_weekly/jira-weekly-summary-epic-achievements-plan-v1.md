# Implementation Plan - Jira Weekly Summary Epic Achievements (v1)

## Objective

Implement a dedicated `jira_weekly` Word `Summary` builder that:

- groups delivered work as `epic -> parent task group`
- keeps resolved subtasks attached to their parent task even if the parent remains open
- enriches missing parent and epic context
- feeds AI with structured evidence instead of only the latest comment
- strips links, paths, UNC references, filenames, and repository noise from final summary text

## Files to change

- `stats_core/reports/jira_weekly.py`
  - replace the current monthly-summary reuse with a weekly-specific builder
  - add weekly-specific prompt and sanitization helpers
- `stats_core/reports/jira_comprehensive.py`
  - allow summary AI transport reuse with an injectable prompt builder/sanitizer without changing default behavior
- `stats_core/reports/jira_utils.py`
  - tighten resolved snapshot epic inheritance for subtasks when parent data is embedded
- `stats_core/sources/jira.py`
  - add a focused helper to fetch issue details for missing parent enrichment
- `tests/test_jira_weekly_report.py`
  - add RED/GREEN coverage for missing epic recovery, grouped subtasks, and sanitization
- `README.md`
  - document the improved weekly `Summary` behavior briefly
- `docs/specs/common/SPEC.md`
  - update the weekly summary contract

## Execution order

1. Add RED tests for weekly summary grouping, enrichment, and sanitization.
2. Confirm RED failures before implementation.
3. Implement missing parent/epic enrichment support.
4. Implement the dedicated weekly summary builder and fallback text.
5. Reuse AI transport with a weekly-specific prompt.
6. Update docs.
7. Run focused GREEN tests.
8. Run full test suite.
9. Run a separate review pass and map acceptance criteria.

## RED targets

- A resolved subtask under an open parent still appears in the correct epic summary.
- Missing parent context from the weekly snapshot no longer causes the epic to disappear.
- Summary bullets do not leak URLs, UNC paths, absolute paths, uploaded artifact names, or raw repository noise.

## Verification commands

- `pytest tests/test_jira_weekly_report.py`
- `pytest tests`

## Risks

- Mock-heavy tests may miss real Jira object shape differences.
  - Mitigation: keep enrichment helper narrow and field-based.
- Sanitization may become too aggressive and remove useful detail.
  - Mitigation: only target links, file/path noise, identifiers, and artifact markers.
- Shared AI transport refactor could change `jira_comprehensive` behavior.
  - Mitigation: keep default prompt/sanitizer unchanged and add optional hooks only.
