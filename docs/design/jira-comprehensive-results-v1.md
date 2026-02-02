# Jira Comprehensive Report: Epic/Parent Enrichment + Results Sheet v1

## Summary
Problem: The Jira comprehensive report’s Issues sheet does not consistently show Epic link/name for subtasks, and it lacks an explicit Parent column. There is also no dedicated Results sheet that extracts “Result:” comments from completed issues.

Goals:
- Issues sheet includes `Epic_Link` populated for subtasks (inherit from parent) and a new `Epic_Name` column.
- Issues sheet includes a `Parent` column so each subtask shows its parent issue key.
- Add a new `Results` sheet listing all “Result:” comments from completed issues.
- Results rows include Issue key, summary, assignee, full Result text, and links extracted from the Result comment; when no links exist, include a link to the Result comment itself.

Non-goals:
- Changing the Jira query model or CLI parameters.
- Reformatting existing sheets beyond adding the requested columns/sheet.
- Adding dependencies or external services.

## Scope boundaries
In scope:
- Update `fetch_jira_data` to enrich Issues rows with Parent, Epic link/name.
- Add Result extraction from comments and a new `Results` sheet in Excel export.
- Tests for Issues enrichment and Results extraction/link behavior.

Out of scope:
- Changes to weekly reports or non-comprehensive reports.
- Changes to team metrics logic.
- UI/template changes beyond the new sheet and columns.

## Assumptions + constraints
- No new dependencies without explicit approval (AGENTS.md).
- Diffs should be minimal and additive.
- Three-role workflow required (Architect → Approved spec → Developer → Reviewer).
- Tests must be run with `pytest tests` (AGENTS.md).
- Subtasks identified by Jira parent field; parent issue contains Epic link when subtask lacks it.
- “Completed issues” are determined by existing `_resolved_mask` logic (resolved date or done status).

## Architecture
### Components
- `stats_core/reports/jira_comprehensive.py`:
  - `fetch_jira_data`: enrich Issues with Parent + Epic link/name and capture per-comment metadata.
  - New helper(s) to extract Results entries from comments.
  - `export_to_excel`: add `Results` sheet when results exist.
- `JiraSource` is unchanged; uses existing Jira client and fields.

### Data flow
1. Build JQL via `build_jql_query` (unchanged).
2. `fetch_jira_data` fetches issues with fields including `parent` and `customfield_10000` (epic link).
3. Build an `issue_epic_map` and `epic_name_map` from fetched issues and Epic lookups.
4. For each issue:
   - Populate `Parent` (parent key or empty).
   - Populate `Epic_Link`: issue’s epic link or parent’s epic link for subtasks.
   - Populate `Epic_Name`: resolved from epic name map.
5. Extract Result comments for completed issues into a `results_df`.
6. `export_to_excel` writes Issues, Links, Metrics, and Results sheets.

## Interfaces / contracts
### Updated data returned from `fetch_jira_data`
- Signature becomes:
```
fetch_jira_data(jira, jql_query: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
```
- Returns:
  - `issues_df` with new columns `Parent`, `Epic_Name` (and `Epic_Link` enriched).
  - `links_df` unchanged.
  - `results_df` (new) for the Results sheet.

### Results sheet schema
`Results` columns:
- `Issue_Key`
- `Summary`
- `Assignee`
- `Result`
- `Result_Links`

Rules:
- “Result” is taken from any comment whose body starts with `Result:` (case-sensitive).
- The `Result` field contains the full comment body (verbatim).
- `Result_Links` contains only URLs extracted from the Result comment, joined by newline.
- If no URLs are found, set `Result_Links` to a link pointing to the Result comment.

### Comment link format
- Use `jira_url` (from config) and comment id to build a stable link, e.g.:
  - `https://<jira>/browse/<ISSUE>?focusedCommentId=<ID>#comment-<ID>`
- If comment id is missing, fall back to the issue URL.

### Error handling strategy
- Missing parent/epic values → use empty string and “Unknown Epic” where appropriate.
- Missing comment ids → fall back to issue URL.
- If `results_df` is empty, skip Results sheet.

## Data model changes + migrations
- None (in-memory only); new columns in `issues_df` and a new `results_df`.

## Edge cases + failure modes
- Multiple Result comments per issue → multiple rows in Results.
- Result comments containing no URLs → use comment link fallback.
- Subtask without parent info → Parent empty; Epic link/name resolved from issue if present.
- Epic name lookup missing → “Unknown Epic”.
- Completed status derived by `_resolved_mask` may include issues resolved without Result comments (they won’t appear in Results).

## Security requirements
- Authn/authz unchanged; uses Jira credentials from config.ini.
- Treat comment text as untrusted; sanitize for Excel output using existing `_sanitize_dataframe_for_excel`.
- No secrets logged.
- No new dependencies.

## Performance requirements + limits
- Use existing Jira fetch; avoid extra network calls beyond epic name lookup.
- Result extraction is O(n) in number of comments.

## Observability
- Extend report summary log to include Results count.
- Optionally log a debug count of Result comments parsed.

## Test plan
- Unit tests:
  - Issues sheet populates Parent and Epic_Link/Epic_Name for subtasks.
  - Results sheet extracts Result comments for completed issues.
  - Results links fallback to comment link when no URLs.
- Run: `pytest tests`.

## Rollout plan + rollback plan
- Rollout: update comprehensive report; no config changes.
- Rollback: revert Jira comprehensive changes and Results sheet creation.

## Acceptance criteria checklist
- Issues sheet has `Parent` column and populated parent key for subtasks.
- Issues sheet `Epic_Link` is populated for subtasks from parent when missing.
- Issues sheet contains `Epic_Name` column with resolved epic names.
- Results sheet includes all Result comments from completed issues with Issue key, summary, assignee, full Result text, and Result links.
- If a Result comment has no URLs, Results sheet shows a link to that comment.
- No new dependencies; tests pass with `pytest tests`.

## Approval
APPROVED:v1
