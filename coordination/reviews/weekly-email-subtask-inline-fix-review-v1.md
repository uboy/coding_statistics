# Weekly Email Inline Subtask Fix Review

Reviewed on: 2026-03-11
Reviewer: independent sub-agent
Scope:
- `stats_core/reports/jira_weekly_email.py`
- `stats_core/reports/jira_weekly_email_key_results.py`
- `tests/test_jira_weekly_email_report.py`
- `coordination/tasks.jsonl`
- `coordination/state/codex.md`

Verifier output (verbatim):

MUST-FIX issues
- None. I did not find a correctness, regression, or security defect in the scoped code diff.

SHOULD-FIX issues
- Process consistency is stale: [coordination/tasks.jsonl#L40](/C:/Users/devl/proj/PycharmProjects/coding_statistics/coordination/tasks.jsonl#L40) still marks implementation `in_progress` and [coordination/tasks.jsonl#L41](/C:/Users/devl/proj/PycharmProjects/coding_statistics/coordination/tasks.jsonl#L41) still marks verification `pending`, even though [coordination/state/codex.md#L44](/C:/Users/devl/proj/PycharmProjects/coding_statistics/coordination/state/codex.md#L44) says review started after GREEN evidence was already available. That weakens the required checklist/audit trail.

Spec mismatches
- The approved design still expects named subtask detail lines under the feature ([jira-weekly-email-refactor-subtask-key-results-v1.md#L94](/C:/Users/devl/proj/PycharmProjects/coding_statistics/docs/design/jira-weekly-email-refactor-subtask-key-results-v1.md#L94), [jira-weekly-email-refactor-subtask-key-results-v1.md#L190](/C:/Users/devl/proj/PycharmProjects/coding_statistics/docs/design/jira-weekly-email-refactor-subtask-key-results-v1.md#L190), [jira-weekly-email-refactor-subtask-key-results-v1.md#L234](/C:/Users/devl/proj/PycharmProjects/coding_statistics/docs/design/jira-weekly-email-refactor-subtask-key-results-v1.md#L234)), but the follow-up diff removes that contract and inlines subtask evidence into the feature `status` instead ([jira_weekly_email.py#L1645](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email.py#L1645), [jira_weekly_email_key_results.py#L316](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email_key_results.py#L316), [jira_weekly_email.py#L3137](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email.py#L3137), [test_jira_weekly_email_report.py#L3285](/C:/Users/devl/proj/PycharmProjects/coding_statistics/tests/test_jira_weekly_email_report.py#L3285)). If inline rendering is the intended final behavior, the spec should be updated or superseded.

Commands run + results
- `git diff -- stats_core/reports/jira_weekly_email.py stats_core/reports/jira_weekly_email_key_results.py tests/test_jira_weekly_email_report.py coordination/tasks.jsonl coordination/state/codex.md` -> inspected the scoped follow-up diff.
- `pytest tests/test_jira_weekly_email_report.py -k "subtask_status or detail_lines or named_subtask_fallback"` -> PASS (`3 passed, 72 deselected`).
- `rg --files | rg "coordination/templates/review-report|validate-review-report"` -> no matches; the policy-referenced review template/validator files are absent in this repo snapshot.
- I did not rerun full `pytest`; I relied on the provided GREEN evidence for `pytest tests/test_jira_weekly_email_report.py` and full-suite `pytest`.

Final verdict: PASS
