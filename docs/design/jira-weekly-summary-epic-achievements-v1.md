# Design Spec - Jira Weekly Summary Epic Achievements (v1)

## 1) Summary

### Problem statement

`jira_weekly` currently produces a Word `Summary` section by reusing the generic monthly summary builder. In practice this causes two problems:

- some epics disappear even though work was completed inside them during the selected period;
- the generated text is too weak for reporting because AI mostly sees a task title, description, and the latest comment instead of the full factual evidence for the task group.

The user expectation is different: for each epic, the report must describe what was actually delivered during the period. Completed subtasks must be attributed to their parent task or feature even when the parent task itself is still open.

### Goals

- Keep `Summary` in `jira_weekly` Word output.
- Build epic summaries from completed work in the selected period, not from the last comment only.
- Group completed subtasks under their parent task.
- Attribute each parent-task group to the correct epic, even when the parent or epic was not updated in the selected period.
- Generate report-ready achievement text from titles, descriptions, and comments.
- Remove links, file paths, UNC paths, attachment names, repository references, and similar noise from the summary content.

### Non-goals

- No changes to `List View`.
- No weekly Excel layout changes.
- No new dependency additions.
- No behavioral change to `jira_comprehensive` summary in this scope.

## 2) Scope boundaries

### In scope

- `jira_weekly` Word `Summary` section only.
- New weekly-specific summary data builder.
- Parent/epic enrichment for resolved tasks and subtasks.
- Weekly-specific AI prompt redesign.
- Sanitization of noisy artifacts before prompt building and after AI output.

### Out of scope

- `jira_weekly` `Table View`, `List View`, `Engineer Weekly Activity`, `Epic Progress`, and `Resolved Tasks` behavior.
- `jira_comprehensive` summary pipeline.
- Jira authentication or transport changes.
- Excel export changes.

## 3) Assumptions + constraints

- Repo workflow is design-first for non-trivial `repo_change` work.
- No new packages may be added without explicit approval.
- Existing AI providers and retry utilities must be reused.
- Summary must remain understandable even when AI is disabled or fails.
- The user-facing summary language remains English because the current management summary and AI pipeline are English-oriented.

## 4) Architecture

### Replace the current weekly summary source

`jira_weekly` must stop using the generic `build_monthly_summary_df(...)` path for its Word `Summary`.

Instead, weekly summary generation must use a dedicated builder tailored to the weekly reporting model:

- source fact: completed work in the selected period;
- grouping unit: parent task group inside an epic;
- rendering unit: one report bullet per parent task group.

### Data sources

The new weekly summary builder will use:

- `resolved_issues_df` as the source of resolved issues and subtasks in the period;
- weekly `comments_df` for period comments already collected by `fetch_jira_activity_data(...)`;
- direct Jira enrichment for missing parent tasks and missing epic issues referenced by the resolved rows.

### Summary group model

Each summary group is keyed by:

- `Epic_Key`
- `Anchor_Issue_Key`

Where:

- if a resolved row is a subtask, `Anchor_Issue_Key = Parent_Key`;
- otherwise `Anchor_Issue_Key = Issue_Key`.

This means:

- resolved subtasks are always attributed to the parent feature/bug/task;
- a resolved parent task stays its own anchor group;
- if both the parent task and some subtasks were resolved in the same period, they still produce one combined group.

### Parent and epic enrichment

The weekly builder must not rely only on period snapshot membership for parent and epic context.

It must:

1. collect referenced parent keys from resolved subtasks;
2. collect referenced epic keys from resolved rows and enriched parents;
3. fetch missing parent issue metadata when the parent is absent from `resolved_issues_df`;
4. fetch missing epic metadata when the epic is absent from the weekly period fetch.

Required enriched fields:

- parent summary/title
- parent issue type
- parent description
- parent direct epic link if needed
- epic key
- epic summary/title

### Epic inclusion rule

Weekly `Summary` must include every epic that has at least one valid summary group in the selected period.

This is an activity-based inclusion rule, not a reuse of the monthly `report`-label gate. An epic must not disappear only because its own issue row was not updated during the selected period.

### Evidence aggregation per group

For each `(epic, anchor task)` group, collect:

- anchor task title, type, status, and description;
- whether the anchor task itself was resolved in the period;
- resolved child subtasks in the period;
- resolved child tasks in the period when the anchor is the task itself;
- period comments from:
  - the anchor task,
  - all resolved child subtasks belonging to that anchor.

Comments are used as evidence, not as direct final summary text.

### Prompt construction

AI input must be structured around the task group, not around a single latest comment.

Each AI item must contain:

- epic name
- anchor task title
- anchor task type
- anchor task status
- anchor task description
- resolved item list:
  - issue type
  - title
  - optional short description
- normalized comment facts collected across the whole task group

### Rendering model

Under each epic heading in Word `Summary`:

- emit one bullet per parent-task group;
- each bullet should describe the delivered achievement for that task group;
- preserve final count lines after the bullets:
  - `Resolved xx planned tasks on time.`
  - `Resolved xx reported issues.` when applicable

## 5) Interfaces/contracts

### New weekly-specific internal builder

Proposed internal contract:

```python
def build_weekly_epic_summary_df(
    jira_source: JiraSource,
    resolved_issues_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    config: ConfigParser,
    extra_params: dict[str, Any],
) -> pd.DataFrame:
    ...
```

Output columns remain renderer-friendly:

- `Epic_Link`
- `Epic_Name`
- `Summary`
- `Planned_Tasks_Resolved`
- `Reported_Issues_Resolved`

### Grouped AI input contract

Proposed item shape:

```json
{
  "id": "EPIC-1::TASK-42",
  "epic_name": "Platform Delivery",
  "anchor_title": "Add lifecycle hooks for component teardown",
  "anchor_type": "Story",
  "anchor_status": "In Progress",
  "anchor_description": "Parent task context after sanitization.",
  "resolved_items": [
    "Sub-task: Finalized cleanup callback execution order",
    "Sub-task: Added teardown regression coverage"
  ],
  "comment_facts": [
    "Cleanup path now releases retained nodes on detach.",
    "Regression in repeated mount/unmount sequence was fixed."
  ]
}
```

### Weekly summary prompt requirements

The prompt must explicitly instruct the model to:

1. summarize delivered outcomes for the whole parent-task group;
2. treat resolved subtasks as achievements of the parent task;
3. use titles, descriptions, and normalized comment facts only;
4. ignore process chatter and link-only comments;
5. remove Jira keys, URLs, repository references, commit hashes, file names, absolute paths, and UNC paths;
6. write report-ready English for a management summary;
7. return strict JSON only.

Suggested output rule:

- one compact achievement paragraph per group;
- maximum 2-3 concise sentences;
- factual, concrete, no invented detail.

### Deterministic fallback contract

If AI is disabled, times out, or returns invalid JSON:

- the report must still produce one bullet per group;
- fallback text must be based on:
  - anchor title
  - resolved child titles
  - sanitized factual comment hints when available

## 6) Data model changes + migrations

- No database or file-format migrations.
- Temporary in-memory summary structures will add group-level fields such as:
  - `Anchor_Issue_Key`
  - `Anchor_Title`
  - `Anchor_Type`
  - `Anchor_Description`
  - `Resolved_Item_Titles`
  - `Comment_Facts`
- No change to weekly Excel workbook schema.

## 7) Edge cases + failure modes

- Resolved subtask with missing parent access:
  - fall back to the subtask itself as the anchor group.
- Resolved task group with unknown epic after enrichment failure:
  - render under `Unknown Epic` instead of dropping the group.
- Parent task open, subtasks resolved:
  - keep the group and describe delivered subtask outcomes under that parent task.
- Parent task resolved and subtasks resolved in the same period:
  - produce one combined bullet, not duplicates.
- Link-only or artifact-only comments:
  - ignore them or downgrade them to a generic result hint; never let them dominate the summary.
- Comments with paths, attachment names, or repository references:
  - sanitize before prompt construction and before final rendering.

## 8) Security requirements

- Reuse existing Jira and AI configuration handling; no new secrets flow.
- Do not log raw API keys or tokens.
- Sanitize evidence before sending it to AI:
  - strip URLs
  - strip UNC paths
  - strip Windows and Unix absolute paths
  - strip Jira keys when they are only identifiers
  - strip PR/MR/commit references
  - strip attachment markers and uploaded artifact names
- Continue using deterministic fallback if AI is unavailable.

## 9) Performance requirements + limits

- Group-building over resolved rows must stay linear relative to weekly data size.
- Extra Jira lookups must be limited to missing parent and epic keys only.
- AI batching must remain bounded to avoid oversized prompts.
- The change must not materially affect report runtime for typical weekly project volumes.

## 10) Observability

Add debug/info logs for:

- number of resolved rows considered for summary;
- number of missing parent keys enriched;
- number of missing epic keys enriched;
- number of final epic groups;
- AI rewritten group count vs fallback count;
- sanitization fallback cases for noisy comments.

## 11) Test plan

### Coverage targets

`tests/test_jira_weekly_report.py`

- resolved subtasks under an open parent still appear in the correct epic summary;
- a parent not updated in the period does not cause the epic to disappear;
- summary uses one bullet for a parent task with multiple resolved subtasks;
- the rendered text contains sanitized achievement prose rather than raw links or file paths;
- `List View` and other weekly sections remain unchanged.

Focused helper coverage may be added in the same file or a new weekly-summary-focused test module for:

- parent enrichment fallback;
- epic enrichment fallback;
- prompt payload construction;
- path and artifact sanitization.

### Verification commands

- focused: `pytest tests/test_jira_weekly_report.py`
- full: `pytest tests`

## 12) Rollout plan + rollback plan

### Rollout

1. Add the weekly-specific summary group builder.
2. Replace the current weekly call path to the generic monthly summary builder.
3. Redesign the weekly summary prompt and sanitization helpers.
4. Add regression tests for missing-epic and grouped-subtask cases.
5. Run focused and full verification.

### Rollback

1. Restore the previous weekly summary builder call path.
2. Remove the weekly-specific group builder and prompt changes.
3. Keep the rest of `jira_weekly` untouched.

## 13) Acceptance criteria checklist

- [ ] `jira_weekly` `Summary` is grouped by epic and by parent task group.
- [ ] Resolved subtasks are attributed to their parent task even when the parent task is still open.
- [ ] An epic with qualifying completed work is not dropped because parent or epic metadata was absent from the period snapshot.
- [ ] AI input uses structured evidence from the whole task group, not only the latest comment.
- [ ] Final summary bullets are report-ready and free from links, file names, absolute paths, UNC paths, and repository noise.
- [ ] Existing weekly sections, especially `List View`, remain behaviorally unchanged.
- [ ] Focused and full pytest verification pass.

## Approval

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"

APPROVED:v1

