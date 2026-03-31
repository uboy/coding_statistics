# Implementation Plan: Jira Weekly Developer Activity Sheet

## Goal

Extend `jira_weekly` Excel export with a simple `Developer_Activity` sheet that
shows, per developer and issue with a Jira comment in the selected period:
- developer
- issue hyperlink
- title
- total logged hours by that developer on that issue
- aggregated worklog details by that developer
- aggregated Jira comments by that developer

## Scope

- Add helper(s) in `stats_core/reports/jira_utils.py` to aggregate comment-driven
  developer activity rows from weekly comments and worklogs.
- Update `stats_core/reports/jira_weekly.py` Excel export from single-sheet output
  to a workbook with `Weekly_Grid` and `Developer_Activity`.
- Keep current Word report behavior unchanged.
- Update `README.md`, `docs/specs/common/SPEC.md`, and
  `docs/agents/knowledge-base.md`.
- Add focused tests in `tests/test_jira_weekly_report.py`.

## Files to Change

- `stats_core/reports/jira_utils.py`
- `stats_core/reports/jira_weekly.py`
- `tests/test_jira_weekly_report.py`
- `README.md`
- `docs/specs/common/SPEC.md`
- `docs/agents/knowledge-base.md`

## Steps

1. Add RED tests for:
   - workbook contains `Weekly_Grid` and `Developer_Activity`
   - activity rows are comment-driven
   - comments aggregate per developer + issue
   - worklog hours and details aggregate per developer + issue
   - issue cell contains Jira hyperlink
2. Run focused pytest in RED phase and confirm failure.
3. Implement developer activity aggregation helper(s) in `jira_utils.py`.
4. Update weekly Excel export to write a two-sheet workbook and apply issue hyperlinks.
5. Update docs for the new `jira_weekly` Excel sheet.
6. Run focused pytest in GREEN phase, then full `pytest tests`.
7. Run review pass against approved spec and current diff.

## Testing / Verification

- `python -m pytest tests/test_jira_weekly_report.py`
- `python -m pytest tests/test_members_utils.py`
- `python -m pytest tests`

## Rollback

- Revert the new helper(s) and workbook export changes.
- Revert docs if the feature is rolled back.

## Acceptance Criteria

- `jira_weekly` CLI contract is unchanged.
- Excel output now contains `Weekly_Grid` and `Developer_Activity`.
- `Developer_Activity` only includes developer/issue pairs with a Jira comment by
  that developer in period.
- Logged hours and worklog details come from the same developer and issue.
- Issue key is exported as a clickable Jira hyperlink.
- Existing Word sections still generate.
