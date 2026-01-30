# Jira Weekly Epic Progress & Resolved Task Inclusion v1

## Summary
Problem: The Jira weekly report’s Epic Progress and Resolved Tasks sections do not reliably include all tasks and subtasks resolved within the report period, and progressed tasks should only appear if time was logged within the period. Parent/subtask hierarchy must be preserved so subtasks appear under the correct parent.

Goals:
- Include **all tasks and subtasks resolved within the period** in both Epic Progress (Resolved section) and the standalone Resolved Tasks section.
- For parents with multiple subtasks, include **only the subtasks resolved within the period**.
- For Epic Progress “Progressed Tasks,” include **only tasks/subtasks with time logged within the period**.
- If a subtask has time logged within the period and its parent has none, **include the parent with the subtask**.
- Ensure **subtasks are listed beneath parents** (lower level).

Non-goals:
- Changing the List View or Table View semantics.
- Modifying Jira query criteria beyond what’s required for correct filtering.
- Adding new dependencies or altering templates/styles.

## Scope boundaries
In scope:
- Data filtering and hierarchy building for Epic Progress (Resolved + Progressed sections).
- Data filtering and hierarchy building for Resolved Tasks section.
- Minimal interface updates in `stats_core/reports/jira_weekly.py` and `stats_core/reports/jira_epic_report.py` (and helpers).
- Tests covering resolved/progressed inclusion and hierarchy.

Out of scope:
- Changes to Excel export layout or content.
- New CLI flags or config entries.
- Any Jira authentication or network changes.

## Assumptions + constraints
- No new dependencies without explicit approval (AGENTS.md).
- Diffs should be minimal and additive.
- Three-role workflow is required (Architect → Approved spec → Developer → Reviewer).
- Tests must be run with `pytest tests` (AGENTS.md).
- Jira subtask type is identified by issue type name `"Sub-task"` (existing convention).
- Jira `fetch_issues` uses `updated >= start_date` and may exclude some resolved issues if not updated; we will not change that JQL in this scope (risk noted).

## Architecture
### Components
- `JiraSource.fetch_issues`: provides issue metadata (resolution date, parent, epic link, type).
- `stats_core.reports.jira_utils`: will host a new helper to build resolved-issues snapshots from issue metadata.
- `stats_core.reports.jira_epic_report`:
  - New/updated functions to build **hierarchical** epic summaries for resolved issues.
  - Existing `generate_epic_progress_from_worklogs` remains the source for progressed tasks.
- `stats_core.reports.jira_weekly.JiraWeeklyReport.run`:
  - Supplies resolved-issues snapshot to Epic Progress and Resolved Tasks sections.

### Data flow (high-level)
1. `fetch_jira_data(...)` remains the data source for List/Table views.
2. `fetch_jira_activity_data(...)` remains the data source for worklogs/comments (progressed tasks).
3. New helper builds a **resolved_issues_df** from Jira issues (resolution date within period).
4. Epic Progress:
   - Resolved section uses resolved_issues_df → hierarchical summary.
   - Progressed section uses worklogs_df (only time-logged issues) → hierarchical summary.
5. Resolved Tasks section uses resolved_issues_df grouped by resolution week, with parent/subtask nesting.

## Interfaces / contracts
### New helper (jira_utils)
```
build_resolved_issues_snapshot(
    jira_source: JiraSource,
    project: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame
```
- Returns DataFrame with columns:
  - Issue_key, Summary, Resolution_Date, Resolution_Week, Epic_Link, Epic_Name,
    Parent_Key, Parent_Summary, Type
- Filtering rule: `Resolution_Date` within [start_date, end_date].
- Epic name lookup via `fetch_epic_names`.
- Parent info from `issue.fields.parent`.

### Epic Progress (jira_epic_report)
- Replace/extend `generate_epic_report(data: pd.DataFrame)` with:
```
generate_epic_resolved_hierarchy(resolved_df: pd.DataFrame) -> list[dict[str, Any]]
```
- Output structure aligns with progressed tasks (`Parents` + `Subtasks`) to ensure subtasks are nested.
- If a resolved subtask’s parent is not resolved in period, still include a parent bucket using parent metadata (without implying resolution).

### Resolved Tasks section
- Update `add_resolved_tasks_section(document, resolved_tasks: pd.DataFrame)` to accept resolved_issues_df.
- Group by `Resolution_Week` (precomputed if present; otherwise computed from `Resolution_Date`).
- Within each week:
  - Render parent tasks resolved that week.
  - Render resolved subtasks under their parent (only subtasks resolved in the week).

### Error handling strategy
- If required columns are missing, treat as empty and emit “No resolved/progressed tasks…” messages.
- Empty DataFrames should not throw (consistent with current behavior).

## Data model changes + migrations
- No persistent storage changes.
- Add derived column `Resolution_Week` (in-memory only) for resolved snapshots.

## Edge cases + failure modes
- **Resolved subtask, unresolved parent:** parent bucket is still rendered (for hierarchy), with only resolved subtasks included.
- **Parent resolved, subtasks resolved outside period:** show parent; exclude out-of-period subtasks.
- **Subtask resolved in period but missing parent summary:** fall back to empty string or issue key.
- **Epic link missing on subtask:** attempt to inherit from parent if available; otherwise “Unknown Epic”.
- **No worklogs in period:** progressed tasks section should be empty even if issues exist.
- **JQL updated filter:** resolved items not updated in period won’t appear; document as known limitation.

## Security requirements
- Authn/authz unchanged (Jira credentials from config.ini).
- Validate/parse dates strictly; avoid code injection by not using user inputs in logs.
- No secrets in logs or report output.
- No new dependencies.

## Performance requirements + limits
- Avoid additional Jira API calls beyond existing `fetch_issues` and `fetch_epic_names` usage.
- Resolve hierarchy in-memory; complexity O(n) for resolved_issues_df rows.

## Observability
- Keep existing `print` outputs.
- Add optional debug logs (if logging is used elsewhere) for counts of resolved/progressed items to aid troubleshooting.

## Test plan
- Unit tests for resolved snapshot/hierarchy:
  - Resolved parent + multiple subtasks, only in-period subtasks included.
  - Resolved subtask with parent not resolved → parent bucket still present.
- Epic Progress resolved section uses hierarchical structure.
- Resolved Tasks section includes all resolved tasks/subtasks within period.
- Run: `pytest tests`.

## Rollout plan + rollback plan
- Rollout: implement changes behind existing code paths; no config changes required.
- Rollback: revert the new helper and hierarchy functions; restore prior epic/ resolved rendering.

## Acceptance criteria checklist
- Epic Progress “Resolved Tasks” lists all tasks/subtasks resolved within the period with subtasks nested under parents.
- Epic Progress “Progressed Tasks” includes only tasks/subtasks with time logged within the period.
- Parent tasks appear in Progressed section when only subtasks logged time within the period.
- Resolved Tasks section includes all tasks/subtasks resolved within the period; only in-period subtasks are listed under parents.
- No new dependencies; tests pass with `pytest tests`.
- Known limitation of Jira `updated` filter is documented.

## Approval
APPROVED:v1
