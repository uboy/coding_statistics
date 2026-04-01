# Implementation Plan: Jira Comprehensive Developer Activity Sheet

## Goal

Add a simple `Developer_Activity` sheet to `jira_comprehensive` that shows, per
developer and issue with a Jira comment in the selected period:
- developer
- issue hyperlink
- title
- total logged hours by that developer on that issue
- aggregated worklog details by that developer
- aggregated Jira comments by that developer

Also remove the misleading weekly routing for this feature so the detailed
developer activity lives in the correct Excel-only report.

## Scope

- Add raw comment-entry collection for the selected period in
  `stats_core/reports/jira_comprehensive.py`.
- Build `Developer_Activity` rows from comment entries + worklog entries.
- Export the new sheet from `jira_comprehensive` while keeping current sheets.
- Correct `jira_weekly` expectations/docs so this detail view is not described as
  a weekly feature.
- Update focused tests and docs.

## Files to Change

- `stats_core/reports/jira_comprehensive.py`
- `stats_core/reports/jira_utils.py`
- `stats_core/reports/jira_weekly.py`
- `tests/test_jira_comprehensive_report.py`
- `tests/test_jira_weekly_report.py`
- `README.md`
- `docs/specs/common/SPEC.md`
- `docs/agents/knowledge-base.md`

## Steps

1. Add RED tests for:
   - `jira_comprehensive` workbook contains `Developer_Activity`
   - rows are comment-driven by developer + issue
   - `Logged_Hours` and `Worklog` aggregate only matching developer worklogs
   - `Comments` aggregate only matching developer comments
   - issue key cell contains Jira hyperlink
   - worklog-only activity does not create a row
2. Add/update weekly regression to stop expecting the detailed sheet from
   `jira_weekly`.
3. Run focused pytest in RED phase and confirm failure.
4. Implement raw comment-entry collection and developer-activity aggregation.
5. Export `Developer_Activity` from `jira_comprehensive` and apply hyperlink formatting.
6. Remove or narrow weekly-detail behavior/docs so placement is unambiguous.
7. Run focused pytest in GREEN phase, then full `python -m pytest tests`.
8. Run review pass against the approved spec and final diff.

## Testing / Verification

- `python -m pytest tests/test_jira_comprehensive_report.py`
- `python -m pytest tests/test_jira_weekly_report.py`
- `python -m pytest tests`

## Rollback

- Revert the new comprehensive comment-entry collector and activity-sheet export.
- Revert the weekly correction if the product decision changes again.
- Revert docs that point to the new sheet.

## Acceptance Criteria

- `jira_comprehensive` CLI contract is unchanged.
- Workbook contains existing sheets plus `Developer_Activity`.
- `Developer_Activity` only includes developer/issue pairs with a Jira comment by
  that developer in period.
- Logged hours and worklog details come from the same developer and issue.
- Issue key is exported as a clickable Jira hyperlink.
- Existing `Comments_Period`, `Worklog_Activity`, and `Worklog_Entries` remain available.
- No new Word behavior is introduced.
