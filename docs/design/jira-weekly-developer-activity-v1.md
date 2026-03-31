# Design Spec — Jira Weekly Developer Comment Activity & Runtime Hygiene (v1)

## 1) Summary
### Problem statement
`jira_weekly` already has the raw data needed for weekly developer activity, but the current outputs are inconvenient for the concrete operational question:
- for a selected list of developers, show the Jira tasks where that developer added comments in the selected period;
- for each such task, show the task link, title, comments by that developer, total logged hours by that developer, and the worklog entries by that developer.

The current weekly Excel output is too compact for this use case, and the repository also tracks local agent/runtime artifacts that should not remain in git as delivery artifacts.

### Goals
- Extend `jira_weekly` with one simple detailed Excel sheet for developer comment activity.
- Preserve the existing `jira_weekly` entrypoint and current Word sections.
- Keep the current compact weekly Excel overview and add one extra sheet with only the requested columns.
- For each developer and task where that developer commented during the selected period, show:
  - developer,
  - task as hyperlink,
  - title,
  - total logged hours by that developer on that task during the same period,
  - aggregated worklog details by that developer on that task,
  - aggregated comments by that developer on that task.
- Update repository documentation so this workflow is clear without reading code.
- Stop tracking local agent/runtime artifacts and ignore them going forward.
- Treat generated outputs under `reports/` as local runtime artifacts that should stay out of git by default.

### Non-goals
- No new report type; the entrypoint remains `jira_weekly`.
- No replacement of the current Word `Engineer Weekly Activity` section.
- No broad analytic schema with extra technical columns.
- No explicit closure-attribution logic in this iteration.
- No explicit “no activity” synthetic rows in this iteration.
- No new third-party dependencies.

## 2) Scope boundaries
### In scope
- `jira_weekly` Excel output structure.
- New runtime helper that builds comment-driven developer activity rows.
- Documentation updates:
  - `README.md`
  - `docs/specs/common/SPEC.md`
  - `docs/agents/knowledge-base.md`
- Git hygiene updates:
  - `.gitignore`
  - de-tracking local runtime/process artifacts from git index.
- Tests for the new weekly activity sheet.

### Out of scope
- New CLI command or new report name.
- Reworking `jira_comprehensive`.
- Explicit “who closed the task” marking.
- Explicit “developer had no comments/logs in period” sheet.
- Large refactor of unrelated weekly-report sections.

## 3) Assumptions + constraints
- Mandatory workflow from repo guidance applies:
  - Architect -> approval -> plan -> RED tests -> implementation -> GREEN verification -> independent review.
- No new dependencies without explicit approval.
- Weekly report continues using `--report jira_weekly --start ... --end ... --params project=...`.
- Current weekly flow already provides:
  - weekly comments/worklog comments,
  - weekly worklogs,
  - optional developer filtering via `member_list_file`.
- Member list resolution remains compatible with current behavior in `stats_core/utils/members.py`:
  - name headers are preferred,
  - login headers are fallback,
  - legacy fallback column `E` still works.
- Local-only runtime/process artifacts must not remain tracked after the change.

## 4) Architecture
### Components
- `stats_core/reports/jira_weekly.py`
  - keep current orchestration;
  - switch weekly Excel output from single-sheet to small multi-sheet workbook;
  - include the new detailed sheet in the workbook.
- `stats_core/reports/jira_utils.py`
  - add helper(s) to aggregate developer comments and developer worklogs by task for the selected period.
- `stats_core/reports/jira_engineer_weekly.py`
  - optional reuse of time-formatting logic.
- Documentation files
  - update operator-facing docs and member-list guidance.
- `.gitignore`
  - add local runtime/process/report-output patterns while keeping intentional repo adapter files tracked.

### Data flow
1. `JiraWeeklyReport.run()` keeps fetching:
   - weekly snapshot rows (`fetch_jira_data`)
   - weekly worklogs/comments (`fetch_jira_activity_data`)
   - resolved snapshot (`build_resolved_issues_snapshot`)
2. New helper builds `developer_activity_df`:
   - base key: `(developer, issue_key)`
   - include only issues where that developer added at least one comment in the selected period
   - aggregate that developer’s comments for the issue
   - aggregate that developer’s total logged hours for the issue
   - aggregate that developer’s worklog details for the issue
3. Excel export writes:
   - current compact weekly grid sheet
   - new `Developer_Activity` sheet
4. Documentation and ignore rules are updated in the same change.

## 5) Interfaces/contracts
### Public report behavior
- Report name stays `jira_weekly`.
- Existing Word output remains available and keeps `Engineer Weekly Activity`.
- Existing Excel output remains available, but becomes a workbook with at least two sheets:
  - `Weekly_Grid`
  - `Developer_Activity`

### New Excel sheet contract
Sheet name: `Developer_Activity`

Row granularity:
- one row per `(Developer, Issue)` where that developer left at least one comment in the selected period.

Required columns:
- `Developer`
- `Issue`
- `Title`
- `Logged_Hours`
- `Worklog`
- `Comments`

Column semantics:
- `Issue`
  - Jira issue key rendered as clickable hyperlink to the task.
- `Title`
  - issue summary/title.
- `Logged_Hours`
  - total hours logged by that same developer for that same task during the selected period.
- `Worklog`
  - newline-joined worklog details by that developer for that task during the selected period;
  - each line should include date and logged duration;
  - if a worklog comment exists, include it in the same line.
- `Comments`
  - newline-joined comments added by that developer to that task during the selected period.

### Internal helper contracts
`stats_core/reports/jira_utils.py`
```
build_developer_activity_df(
    comments_df: pd.DataFrame,
    worklogs_df: pd.DataFrame,
    jira_url: str,
) -> pd.DataFrame
```

### Error handling strategy
- Report generation must not fail if one issue has malformed comment/worklog payloads.
- On malformed comment/worklog entry:
  - skip only the broken entry;
  - preserve all other activity data.
- Empty worklog/comment datasets must still produce valid output sheets.

## 6) Data model changes + migrations
- No persistent database or config migrations.
- New runtime dataframe: `developer_activity_df`.
- Existing weekly Excel output changes from a single-sheet export to a multi-sheet workbook.
- Git index cleanup is part of this change:
  - stop tracking `.agent-memory/**`
  - stop tracking `.scratchpad/**`
  - stop tracking `coordination/tasks.jsonl`
  - stop tracking `coordination/state/**`
  - stop tracking `coordination/reviews/**`
  - stop tracking `.claude/settings.local.json`
  - ignore generated report outputs under `reports/` by default.
- Keep tracked repo adapter/config files:
  - `.codex/**`
  - `.claude/CLAUDE.md`

## 7) Edge cases + failure modes
- Developer has worklog but no comment:
  - issue is not included in `Developer_Activity`, because the sheet is comment-driven by design.
- Developer has comment but no worklog:
  - row is included with `Logged_Hours = 0` and empty `Worklog`.
- Developer has multiple comments on the same issue:
  - aggregate them in `Comments` as newline-separated blocks.
- Developer has multiple worklogs on the same issue:
  - aggregate them in `Worklog` and sum them into `Logged_Hours`.
- Worklog entry has no comment text:
  - still include date and duration in `Worklog`.
- Name mismatches between member list and Jira display names:
  - retain current `norm_name` matching rules; document the expectation in README.
- Illegal Excel characters in comments/worklog text:
  - sanitize before writing workbook.

## 8) Security requirements
- Existing Jira credentials handling remains unchanged.
- User/comment/worklog text is untrusted input:
  - sanitize values before Excel export;
  - do not execute or interpret markup/URLs.
- Do not log comment bodies or secrets verbosely.
- No new dependencies.
- `.gitignore` changes must not hide tracked source or documentation files that are part of repo behavior.
- Generated outputs under `reports/` are treated as disposable local artifacts, not repository inputs.

## 9) Performance requirements + limits
- Additional aggregation should remain `O(n)` over comment/worklog rows.
- No additional Jira network calls should be required for this iteration.
- Expected weekly report size remains moderate; the new detailed sheet should stay within normal Excel usage bounds.

## 10) Observability
- Add non-sensitive logs for:
  - developer activity row count,
  - unique developers in the detailed sheet,
  - unique issues in the detailed sheet,
  - total aggregated worklog hours.
- Log the final workbook path and created sheet names.

## 11) Test plan
### Unit/integration coverage
- `tests/test_jira_weekly_report.py`
  - developer activity sheet is created in weekly Excel output;
  - only issues with developer comments appear in the detailed sheet;
  - logged hours reflect accumulated worklog duration for the same developer and issue;
  - multiple comments are aggregated into one cell;
  - multiple worklogs are aggregated into one cell;
  - row with comments but no worklog has `Logged_Hours = 0` and empty `Worklog`;
  - issue key cell contains Jira hyperlink and title is exported separately.
- `tests/test_members_utils.py`
  - keep current member-list resolution behavior intact.

### Verification commands
- Focused:
  - `pytest tests/test_jira_weekly_report.py`
  - `pytest tests/test_members_utils.py`
- Full:
  - `pytest tests`
- Git hygiene verification:
  - `git ls-files .agent-memory .scratchpad coordination .claude/settings.local.json`
  - expected result after implementation: no local runtime/process files remain tracked.
  - `git ls-files reports`
  - expected result after implementation: generated report outputs remain untracked by default.

## 12) Rollout plan + rollback plan
### Rollout
1. Add design-approved helper contract for comment-driven developer activity dataframe.
2. Add RED tests for the detailed developer activity export.
3. Implement workbook multi-sheet export and sanitization.
4. Update docs (`README.md`, `docs/specs/common/SPEC.md`, `docs/agents/knowledge-base.md`).
5. Update `.gitignore` and remove local runtime artifacts from git index.
6. Run focused and full verification.
7. Run independent review.

### Rollback
1. Revert weekly workbook changes and remove `Developer_Activity` sheet generation.
2. Revert developer activity helper changes.
3. Revert doc updates if feature is rolled back.
4. Revert ignore/index cleanup if repository policy intentionally changes back.

## 13) Acceptance criteria checklist
- [ ] `jira_weekly` still runs with the existing CLI contract.
- [ ] Weekly Excel output includes current overview plus new `Developer_Activity` sheet.
- [ ] `Developer_Activity` shows one row per developer and task where that developer commented in the selected period.
- [ ] `Developer_Activity` includes only the requested minimal columns: developer, issue link, title, logged hours, worklog details, comments.
- [ ] Logged hours are aggregated from that developer’s worklogs for the same task in the selected period.
- [ ] Comments are aggregated from that developer’s comments for the same task in the selected period.
- [ ] Worklog details are aggregated from that developer’s worklog entries for the same task in the selected period.
- [ ] Existing Word weekly sections remain available.
- [ ] `README.md`, `docs/specs/common/SPEC.md`, and `docs/agents/knowledge-base.md` are updated.
- [ ] Local agent/runtime artifacts are no longer tracked and are ignored going forward.
- [ ] Generated report outputs under `reports/` remain local and do not get staged by default.
- [ ] Full `pytest tests` verification passes.

## Approval
APPROVED:v1

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
