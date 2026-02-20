# Implementation Plan — Jira Summary Report Epic Filter + Feature Grouping (v1)

## Scope
- Apply summary data collection constraints for both `jira_weekly` and `jira_comprehensive`.
- Include only epics that:
  - have label `report`;
  - are open, or were resolved in the report period.
- Reduce oversized summary lists by grouping related subtasks (same parent feature) into one AI summary item.

## Files to change
- `stats_core/reports/jira_comprehensive.py`
- `stats_core/reports/jira_weekly.py`
- `stats_core/reports/jira_utils.py`
- `tests/test_jira_comprehensive_report.py`

## Execution steps
1. RED: add tests for epic scope filtering and grouped subtask preparation.
2. Implement epic eligibility filter (`report` label + open/resolved-in-period).
3. Implement grouped feature payload for AI (parent + subtasks as one item).
4. Update summary prompt to explicitly describe grouped feature items.
5. GREEN: run full `pytest tests`.
