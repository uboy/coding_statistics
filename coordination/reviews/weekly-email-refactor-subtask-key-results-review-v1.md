# Review Report — Weekly Email Refactor + Subtask-Aware Key Results

## Metadata
- Date: 2026-03-11
- Reviewer Agent: 019cdc05-773e-7382-a765-ea6d346c275b
- Spec: `docs/design/jira-weekly-email-refactor-subtask-key-results-v1.md`
- Note: `coordination/templates/review-report.md` and `scripts/validate-review-report.ps1` were not present in this repo snapshot, so this report uses a minimal local structure.

## Findings
MUST-FIX issues
- None.

SHOULD-FIX issues
- `docs/design/jira-weekly-email-refactor-subtask-key-results-v1.md` §10 promises new observability for active-subtask counts, fallback reasons, and structured-summary usage, but I do not see corresponding logging added in [stats_core/reports/jira_weekly_email.py](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email.py) or [stats_core/reports/jira_weekly_email_key_results.py](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email_key_results.py). This is not blocking the current behavior, but it is a spec drift worth closing.
- [coordination/tasks.jsonl](/C:/Users/devl/proj/PycharmProjects/coding_statistics/coordination/tasks.jsonl) contains duplicate `weekly-email-refactor-tests-red` entries with different statuses. It does not affect runtime behavior, but it weakens the required checklist/audit trail.

Spec mismatches
- Acceptance criteria: `jira_weekly_email` entrypoint/CLI/config stability. Implemented: no public entrypoint changes observed; verified indirectly by full test suite passing. No issue.
- Acceptance criteria: `Week Key Results` no longer depends only on flattened feature comment points. Implemented in [stats_core/reports/jira_weekly_email.py](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email.py) plus new [stats_core/reports/jira_weekly_email_key_results.py](/C:/Users/devl/proj/PycharmProjects/coding_statistics/stats_core/reports/jira_weekly_email_key_results.py). No issue.
- Acceptance criteria: active subtasks contribute visible named progress. Implemented via `detail_lines` render path and covered by new tests in [tests/test_jira_weekly_email_report.py](/C:/Users/devl/proj/PycharmProjects/coding_statistics/tests/test_jira_weekly_email_report.py). No issue.
- Acceptance criteria: feature-level result preserves done/progress/problem/plan. Implemented and covered by new payload/render tests. No issue.
- Acceptance criteria: parent-without-comments plus subtask-with-comments case. Covered by existing/new weekly-email tests; no mismatch found.
- Acceptance criteria: AI remains optional and deterministic output stays useful. Preserved; no issue.
- Acceptance criteria: snapshot ordering and console diff remain compatible. Preserved, and `_payload_to_lines()` now includes rendered `detail_lines`, which keeps diff meaningful. No issue.
- Spec §10 observability: partial mismatch. The implementation does not add the new structured-summary/fallback logs described in the spec.

Final verdict
- PASS

## Verification
- `pytest tests/test_jira_weekly_email_report.py` -> PASS (`75 passed, 1 warning`)
- `pytest tests` -> PASS (`139 passed, 1 warning`)
