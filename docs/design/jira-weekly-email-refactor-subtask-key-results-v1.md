# Design Spec — Jira Weekly Email Refactor + Subtask-Aware Key Results (v1)

## Status
- Status: APPROVED:v1
- Approved by: user
- Date: 2026-03-11

## 1) Summary
### Problem statement
`jira_weekly_email` currently produces a usable weekly HTML report, but the implementation is concentrated in one large module and the `Week Key Results` logic loses part of feature progress when a feature is driven by multiple subtasks.

Current loss mechanism:
- subtask comments are flattened into feature-level `points`,
- `_build_compact_feature_status()` classifies only the flattened pool,
- AI aggregation receives compressed aggregate text rather than structured per-subtask evidence.

This means the report can lose:
- which subtask made progress,
- which problem belongs to which subtask,
- which plan belongs to which subtask,
- part of the chronological/context relationship between weekly comments.

### Goals
- Incrementally refactor `jira_weekly_email` to reduce monolith risk without changing the report entrypoint or general weekly-email workflow.
- Change `Week Key Results` logic for features with subtasks so the report uses structured subtask evidence from the selected week.
- For every active subtask in the week, preserve:
  - subtask name,
  - subtask key,
  - weekly comments/derived work done,
  - detected problems/risks/dependencies,
  - detected next actions/plans.
- Produce a clearer feature-level result that answers:
  - what was done,
  - what is still in progress,
  - what problems/risks exist,
  - what is planned next.
- Keep snapshot ordering, console diff, and Outlook-friendly HTML behavior stable.

### Non-goals
- No replacement of `jira_weekly_email` with another report type.
- No new dependencies or templating engine.
- No major redesign of the overall chapter structure.
- No change to Jira auth flow or report invocation format.
- No removal of deterministic fallback when AI is disabled/unavailable.

## 2) Scope boundaries
### In scope
- `jira_weekly_email` refactor by responsibility boundaries.
- New structured data model for feature/subtask weekly progress.
- `Week Key Results` rendering change for features with active subtasks.
- Deterministic summarization logic for done/progress/risk/plan from per-subtask evidence.
- Optional AI polishing on top of structured deterministic inputs.
- Regression coverage for new key-results behavior.

### Out of scope
- Reworking unrelated `Highlights`, vacation parsing, snapshot lookup, or output-format dependency checks beyond necessary extraction/refactor.
- Replacing current `Next Week Plans` semantics end-to-end.
- Changing output file naming, week resolution rules, or label-filter contracts.

## 3) Assumptions + constraints
- Project policy requires design-first workflow and user approval before implementation.
- No new dependencies.
- Existing tests must remain the safety net; new tests may be added, existing tests should not be rewritten unless the approved behavior changes.
- `jira_weekly_email` must still work with AI disabled.
- Snapshot order compatibility must be preserved.
- Console diff should remain meaningful across the change.
- Current report chapters remain:
  - Highlights,
  - Key Results and Achievements,
  - Next Week Plans,
  - Vacations,
  - Top Issues / Risks / For Help.

## 4) Architecture
### Components
- `stats_core/reports/jira_weekly_email.py`
  - keep public report class and orchestration entrypoint.
- New extracted weekly-email helpers/modules (exact filenames may vary, but responsibility split is required):
  - evidence collection + enrichment,
  - feature/subtask aggregation,
  - AI rewrite preparation/application,
  - HTML rendering/export helpers.

### Data flow
1. Collect weekly issue evidence (existing Jira query model stays).
2. Group entries into features.
3. For each feature, build structured weekly activity:
  - parent activity,
  - active subtasks,
  - per-subtask classified progress.
4. Derive deterministic feature summary for `Week Key Results`.
5. Render:
  - compact feature summary,
  - when applicable, named subtask detail lines under the feature.
6. Apply AI rewrite only to approved text targets derived from the structured model.
7. Save snapshot and compute diff using the existing ordering semantics.

### Refactor direction
The refactor should be incremental:
- first extract logic without changing behavior,
- then switch `Week Key Results` to the new structured model,
- keep the report class as the stable integration point.

## 5) Interfaces/contracts
### Public report behavior
- Report name remains `jira_weekly_email`.
- CLI/config contract remains unchanged.
- `Week Key Results` keeps feature grouping by epic.
- For features without active subtasks, current compact behavior remains effectively unchanged.
- For features with active subtasks, the report should show:
  - one compact feature-level summary,
  - optional subtask detail bullets/lines naming the active subtasks and their weekly outcome.

### Active subtask definition
A subtask is considered active for `Week Key Results` if it belongs to the feature and at least one of the following is true within the selected week evidence:
- it has at least one cleaned weekly comment,
- it is in an in-progress/review/blocked-like state,
- it is marked finished/resolved in the week evidence.

### Internal data contracts
Introduce a structured runtime model (dicts or dataclasses) along these lines:

`SubtaskWeeklyUpdate`
- `issue_key`
- `summary`
- `status`
- `resolution`
- `finished`
- `in_progress`
- `blocked`
- `comments`
- `done_points`
- `progress_points`
- `risk_points`
- `dependency_points`
- `plan_points`
- `fallback_note`

`FeatureWeeklyProgress`
- `feature_key`
- `feature_name`
- `parent_issue_keys`
- `parent_points`
- `active_subtasks: list[SubtaskWeeklyUpdate]`
- `closed_tasks`
- `in_progress_tasks`
- `blocked_tasks`
- `feature_summary_result`
- `feature_summary_plan`
- `key_results_detail_lines`

### Error handling strategy
- Missing or noisy comments must not break the report.
- If a subtask has no usable weekly comment text:
  - fall back to status-derived phrases such as `Marked completed`, `In progress`, `Blocked`, `No textual update`.
- AI errors or malformed output must never fail the report; deterministic feature/subtask text is the fallback.

## 6) Data model changes + migrations
- No database or file migration.
- Runtime payload extension only.
- Existing payload keys used by ordering/rendering should stay stable where possible:
  - keep `epics`,
  - keep `feature_statuses`,
  - keep `next_week_plans`.
- Add optional structured fields for features with subtasks, for example:
  - `subtask_updates`,
  - `detail_lines`,
  - `structured_result_input`.

Snapshot compatibility rule:
- previous snapshots must still load without conversion,
- ordering must continue to use existing order extraction,
- new payload fields must not invalidate older snapshots.

## 7) Edge cases + failure modes
- Parent feature has no comments, but subtasks have comments:
  - feature summary must still be built from subtasks.
- Multiple subtasks contain both done and blocked signals:
  - output must preserve both, not collapse to only one label.
- A subtask has only a risk/problem comment:
  - it must still appear in feature details.
- A subtask has only future/plan comments:
  - it must contribute to the feature plan text.
- A subtask changed status but has no usable weekly comments:
  - include status-derived fallback text.
- Comments contain attachments, markdown-image artifacts, links, JSON blobs, or non-English noise:
  - existing sanitization stays in effect before classification.
- Large feature with many subtasks:
  - deterministic summary should prioritize the most meaningful done/risk/plan items,
  - detail lines may be capped to a configurable or fixed safe limit for readability.

## 8) Security requirements
- Keep existing Jira auth model unchanged.
- Do not log secrets or provider API keys.
- AI prompts must use sanitized comment text only.
- AI output must continue to strip URLs, file paths, hashes, and unsafe noise.
- No new dependencies unless explicitly approved.

## 9) Performance requirements + limits
- Aggregation should remain linear in the number of weekly issues/comments.
- No additional Jira round-trips should be required for the new feature summary logic.
- AI prompt size should be reduced by passing structured subtask summaries rather than long raw flattened text.
- HTML rendering changes must not materially affect report generation time.

## 10) Observability
- Add logs for:
  - features with active subtasks count,
  - active subtasks per feature,
  - features using deterministic subtask summary vs AI-polished summary,
  - fallback reasons (no usable comments, AI skipped, AI invalid output),
  - capped detail-line counts when large features are compressed.

## 11) Test plan
### Unit/integration coverage
- `tests/test_jira_weekly_email_report.py`
  - feature with multiple active subtasks preserves subtask names in `Week Key Results`,
  - done/progress/risk/plan from different subtasks are all retained,
  - parent feature without comments still gets correct result from subtasks,
  - blocked/risk subtask is not hidden by done progress from another subtask,
  - plan-only subtask contributes to next-step text,
  - no-comment status-only subtask uses fallback wording,
  - features without subtasks keep compact legacy behavior,
  - snapshot loading/order remains backward compatible.

### Verification commands
- `pytest tests/test_jira_weekly_email_report.py`
- `pytest tests`

## 12) Rollout plan + rollback plan
### Rollout
1. Extract weekly-email responsibilities into smaller helpers/modules.
2. Introduce structured feature/subtask progress model.
3. Switch `Week Key Results` generation to the structured model.
4. Add/adjust rendering for named subtask detail lines where applicable.
5. Run focused and full regression tests.

### Rollback
1. Revert the structured feature/subtask aggregation path.
2. Restore existing flat `feature["points"]`-based key-results logic.
3. Keep extracted helpers only if behavior remains identical; otherwise revert refactor together with behavior change.

## 13) Acceptance criteria checklist
- [ ] `jira_weekly_email` entrypoint/CLI/config contract remains stable.
- [ ] `Week Key Results` no longer depends only on flattened feature comment points for subtask-driven features.
- [ ] Each active subtask can contribute visible named progress in the rendered result.
- [ ] Feature-level result preserves done/progress/problem/plan information when present.
- [ ] Parent-without-comments + subtask-with-comments case is handled correctly.
- [ ] AI remains optional and deterministic output is acceptable without AI.
- [ ] Snapshot ordering and console diff remain compatible with previous outputs.
- [ ] Focused weekly-email tests and full test suite pass after implementation.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
