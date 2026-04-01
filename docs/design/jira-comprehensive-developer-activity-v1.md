# Design Spec — Jira Comprehensive Developer Activity Excel Alignment (v1)

## 1) Summary
### Problem statement
The previous implementation path targeted `jira_weekly`, but the requested operator workflow is specifically an Excel detail view for a selected developer list. The user also clarified that Word sections such as `List View` must not be part of this feature path.

`jira_comprehensive` is the better target because it is already Excel-only and already gathers most of the needed source data through:
- `Comments_Period`
- `Worklog_Activity`
- `Worklog_Entries`

What is still missing is one simple merged sheet that answers the concrete operational question:
- for a selected list of developers,
- show the tasks where that developer added Jira comments in the selected period,
- show the task link and title,
- show the total logged hours by that same developer on that same task in the selected period,
- show that developer's worklog lines for that task,
- show that developer's comment lines for that task.

### Goals
- Move the detailed developer-activity feature to `jira_comprehensive`.
- Keep `jira_weekly` focused on its current weekly overview and Word sections.
- Do not add or change any Word output for this feature.
- Add one new Excel sheet in `jira_comprehensive` with only the minimal requested columns:
  - `Developer`
  - `Issue`
  - `Title`
  - `Logged_Hours`
  - `Worklog`
  - `Comments`
- Reuse existing comprehensive-report inputs and filters where possible.
- Keep existing `Comments_Period`, `Worklog_Activity`, and `Worklog_Entries` sheets intact.

### Non-goals
- No new report name or CLI command.
- No new Word output.
- No task status or resolution columns in the new sheet.
- No "no activity" synthetic rows.
- No closure-attribution logic in this iteration.
- No new dependencies.

## 2) Scope boundaries
### In scope
- `stats_core/reports/jira_comprehensive.py`
- Shared helper reuse from `stats_core/reports/jira_utils.py` if practical
- `tests/test_jira_comprehensive_report.py`
- Documentation updates:
  - `README.md`
  - `docs/specs/common/SPEC.md`
  - `docs/agents/knowledge-base.md`
- Correction of the earlier `jira_weekly` documentation/behavior if it still claims this detail view as a weekly feature

### Out of scope
- Reworking `jira_list_view.py`
- Reworking `jira_engineer_weekly.py`
- Adding new metrics to `Engineer_Performance`, `QA_Performance`, or `PM_Performance`
- Changing JQL semantics for existing comprehensive sheets beyond what is needed for comment-period activity rows
- Reworking git hygiene or agent-policy files in this task

## 3) Assumptions + constraints
- Repo workflow is mandatory:
  - approved spec
  - implementation plan
  - RED tests
  - implementation
  - GREEN verification
  - review pass
- `jira_comprehensive` remains Excel-only.
- Existing JQL contract remains:
  - main issue dataset uses `build_jql_query(...)`
  - comment-period dataset uses `build_comments_period_jql(...)`
- `member_list_file` is optional.
- If `member_list_file` is provided, developer activity rows must be filtered to identities from that file.
- Identity matching must remain tolerant to Jira display-name vs login differences.
- No new network endpoints or third-party libraries may be added.

## 4) Architecture
### Components
- `stats_core/reports/jira_comprehensive.py`
  - fetch raw per-comment entries for the selected period
  - reuse existing raw worklog entry data
  - build the new `Developer_Activity` dataframe
  - export the new sheet with hyperlink formatting
- `stats_core/reports/jira_utils.py`
  - optional shared normalization / aggregation helper reuse if it keeps diffs smaller
- `stats_core/utils/members.py`
  - current member-list resolution rules remain the source of truth for matching-friendly identities

### Data flow
1. `JiraComprehensiveReport.run()` keeps building:
   - `issues_df`
   - `comments_period_df`
   - `worklog_activity_df`
   - `worklog_entries_df`
2. Add a new raw comment-entry collector for the same report scope:
   - one row per Jira comment inside the selected period
   - fields include issue key, summary, author, normalized author, date, and body
3. Build `developer_activity_df` with row key:
   - `(developer, issue_key)`
4. Include a row only when that developer added at least one Jira issue comment in the selected period.
5. For each row:
   - aggregate comment lines by that same developer on that same issue
   - aggregate worklog lines by that same developer on that same issue
   - sum worklog hours by that same developer on that same issue
6. Export workbook with existing sheets unchanged plus new `Developer_Activity`.

## 5) Interfaces/contracts
### Public report behavior
- Report name remains `jira_comprehensive`.
- CLI contract remains unchanged:
  - `--report jira_comprehensive`
  - existing params: `project`, `start/end`, `version`, `epic`, `jql`, `member_list_file`, `output`
- Workbook gains one extra optional sheet:
  - `Developer_Activity`

### New Excel sheet contract
Sheet name:
- `Developer_Activity`

Row granularity:
- one row per `(Developer, Issue)` where that developer added at least one Jira issue comment in the selected period

Required columns:
- `Developer`
- `Issue`
- `Title`
- `Logged_Hours`
- `Worklog`
- `Comments`

Column semantics:
- `Developer`
  - developer display name from Jira comment author
- `Issue`
  - Jira issue key rendered as clickable hyperlink
- `Title`
  - issue summary
- `Logged_Hours`
  - total hours logged by the same developer on the same issue during the selected period
- `Worklog`
  - newline-joined worklog lines for the same developer and issue
  - each line includes date and logged duration
  - if the worklog has comment text, include it in the same line
- `Comments`
  - newline-joined Jira comment lines for the same developer and issue
  - each line includes comment date and comment text

### Internal helper contracts
Expected new internal helper shapes:

```python
def fetch_comment_entries_for_period(
    jira,
    jql_query: str,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame
```

Returns rows with at least:
- `Issue_Key`
- `Summary`
- `Comment_Author`
- `Comment_Author_Norm`
- `Comment_Date`
- `Comment_Date_Str`
- `Comment_Body`

```python
def build_developer_activity_df(
    comment_entries_df: pd.DataFrame,
    worklog_entries_df: pd.DataFrame,
    jira_url: str,
) -> pd.DataFrame
```

Returns rows with:
- `Developer`
- `Issue`
- `Title`
- `Logged_Hours`
- `Worklog`
- `Comments`
- `Issue_Url`

### Error handling strategy
- Malformed single comment/worklog rows must be skipped, not fail the whole report.
- Empty activity must still produce a valid workbook.
- Missing worklogs for a commented issue must produce `Logged_Hours = 0` and empty `Worklog`.

## 6) Data model changes + migrations
- No persistent migrations.
- New runtime dataframe:
  - `developer_activity_df`
- New workbook sheet:
  - `Developer_Activity`
- Existing sheets remain backward compatible.

## 7) Edge cases + failure modes
- Developer has worklog but no Jira issue comment in period:
  - do not create a row
- Developer has Jira issue comment but no worklog:
  - create row with `Logged_Hours = 0`
- Developer has multiple comments on one issue:
  - aggregate them in chronological order
- Developer has multiple worklogs on one issue:
  - aggregate them in chronological order and sum hours
- Worklog comment is empty:
  - still include date and duration
- Comment body is Atlassian rich-text JSON:
  - flatten to plain text before export
- Illegal Excel characters appear in text:
  - sanitize before export
- `member_list_file` contains login while Jira returns display name:
  - match via normalized name/login candidates where possible

## 8) Security requirements
- Jira comment/worklog text is untrusted input:
  - sanitize before writing to Excel
  - do not interpret markup
- Do not log full comment/worklog payloads.
- Jira credentials handling remains unchanged.
- No new dependencies without explicit approval.

## 9) Performance requirements + limits
- Additional aggregation must remain linear over collected comment/worklog rows.
- No extra Jira calls beyond comment/worklog collection required for the already selected report scope.
- Avoid N x M matching; use normalized keys and grouped aggregation.

## 10) Observability
- Add non-sensitive logs for:
  - developer activity row count
  - unique developers
  - unique issues
  - total aggregated hours
- Log workbook path and created sheet names.

## 11) Test plan
### Unit/integration coverage
- `tests/test_jira_comprehensive_report.py`
  - workbook contains `Developer_Activity`
  - rows exist only for developers/issues with Jira comments in period
  - `Logged_Hours` aggregates only that developer's worklogs on that issue
  - `Worklog` aggregates raw worklog lines for that developer and issue
  - `Comments` aggregates raw Jira comment lines for that developer and issue
  - issue cell contains hyperlink
  - worklog-only activity does not create a row
- If weekly docs/behavior are corrected:
  - add/update a regression test proving no detailed developer sheet is required from `jira_weekly`

### Verification commands
- Focused:
  - `python -m pytest tests/test_jira_comprehensive_report.py`
  - `python -m pytest tests/test_jira_weekly_report.py`
- Full:
  - `python -m pytest tests`

## 12) Rollout plan + rollback plan
### Rollout
1. Add approved v2 target spec for comprehensive developer activity.
2. Add RED tests for the new comprehensive sheet.
3. Implement raw comment-entry collection and developer-activity aggregation.
4. Export `Developer_Activity` sheet with hyperlink formatting.
5. Correct docs so the feature is described under `jira_comprehensive`, not Word or weekly list views.
6. Run focused and full verification.
7. Run review pass.

### Rollback
1. Remove `Developer_Activity` from `jira_comprehensive`.
2. Remove new raw comment-entry collector / aggregation helper.
3. Revert docs that mention the new comprehensive sheet.

## 13) Acceptance criteria checklist
- [ ] `jira_comprehensive` keeps the current CLI contract.
- [ ] Workbook includes existing sheets plus `Developer_Activity`.
- [ ] `Developer_Activity` has only the minimal requested columns.
- [ ] Each row is keyed by developer + issue and appears only when that developer added a Jira comment in period.
- [ ] `Logged_Hours` is aggregated from that developer's worklogs for the same issue in the same period.
- [ ] `Worklog` contains only that developer's worklog lines for the same issue in the same period.
- [ ] `Comments` contains only that developer's Jira comment lines for the same issue in the same period.
- [ ] `Issue` is exported as a clickable Jira hyperlink.
- [ ] Existing `Comments_Period`, `Worklog_Activity`, and `Worklog_Entries` remain available.
- [ ] No new Word behavior is introduced.
- [ ] Documentation points users to the correct Excel report.
- [ ] Full `python -m pytest tests` verification passes.

## Approval
This spec supersedes the earlier weekly-detail direction for this feature and moves the operator-facing implementation to `jira_comprehensive`.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
