# Implementation Plan - Jira Weekly Summary Epic Achievements (v2)

## Objective

Refine `jira_weekly` `Summary` so it reads like a real team-achievement report for the period:

- keep the current epic and parent-task grouping;
- explicitly mention resolved subtask names when they are the delivered work;
- preserve meaningful metrics and measurable results from comments;
- soften truncation and cleanup so bullets stay complete and useful;
- keep open parent tasks visible when they contain resolved subtasks.

## Files to change

- `stats_core/reports/jira_weekly.py`
  - replace lossy `comment_facts` evidence with subtask-centric achievement evidence
  - redesign the weekly prompt for longer result-oriented bullets
  - soften final truncation and cleanup
  - preserve metric hints from comments
- `tests/test_jira_weekly_report.py`
  - add RED/GREEN coverage for:
    - subtask-name preservation
    - metric retention
    - non-truncated complete-looking summary text
    - cleanup that removes garbage without deleting the actual result
- `README.md`
  - update the weekly summary description to mention fuller achievement bullets and metric preservation
- `docs/specs/common/SPEC.md`
  - sync the weekly summary contract
- `docs/agents/knowledge-base.md`
  - sync the weekly summary behavior notes

## Execution order

1. Add RED tests for the new achievement-style summary behavior.
2. Confirm RED failures before implementation.
3. Replace the current evidence aggregation with subtask-centric latest-comment evidence.
4. Add lightweight metric extraction and preservation.
5. Redesign the weekly prompt and fallback builder.
6. Soften cleanup and truncation without reintroducing markup/link garbage.
7. Update docs.
8. Run focused GREEN tests.
9. Run full test suite.
10. Run a separate review pass and map acceptance criteria.

## RED targets

- Summary bullet for an open parent with resolved subtasks explicitly names the resolved subtasks.
- Metric/result phrases such as `%`, `ms`, `MB`, counts, or similar measurable outcomes remain in the final bullet.
- Final summary text does not look artificially cut off.
- Cleanup removes Jira/markdown/log garbage but preserves the actual result statement.

## Verification commands

- `pytest tests/test_jira_weekly_report.py`
- `pytest tests`

## Risks

- Over-preserving raw comment text could reintroduce noisy artifacts.
  - Mitigation: keep cleanup targeted at markup/paths/attachments, not at normal result text.
- Longer bullets could become bloated.
  - Mitigation: bound output by sentence count and only hard-truncate as a last resort with `...`.
- Metric extraction could prefer irrelevant numbers from logs.
  - Mitigation: only retain metrics from comments that also pass the "meaningful comment" filter.
