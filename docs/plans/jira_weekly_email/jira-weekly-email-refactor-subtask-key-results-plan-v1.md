# Implementation Plan: Jira Weekly Email Refactor + Subtask-Aware Key Results

## Goal
Refactor `jira_weekly_email` incrementally and change `Week Key Results` so features with active subtasks retain named subtask progress, risks, and plans instead of collapsing everything into a flat feature-level point list.

## Scope
- Extract weekly-email responsibilities into smaller internal units without changing the public report entrypoint.
- Replace flat subtask aggregation for `Week Key Results` with structured per-subtask weekly evidence.
- Keep snapshot ordering, console diff, AI optionality, and Outlook HTML compatibility stable.
- Add regression coverage for the new feature/subtask narrative behavior.

## Non-Goals
- New dependencies.
- A full renderer redesign.
- Changes to report invocation, output naming, or week resolution.
- Broad business-logic changes in unrelated sections unless required by the extraction.

## Execution Steps
1. Add focused RED tests for subtask-aware `Week Key Results`:
   - mixed done/progress/risk/plan across subtasks,
   - parent without comments but active subtasks,
   - status-only subtask fallback,
   - compatibility for features without subtasks.
2. Extract the current weekly-email orchestration into smaller helpers with no intended behavior change:
   - evidence/model,
   - key-results/plans aggregation,
   - AI rewrite preparation,
   - HTML rendering helpers.
3. Introduce a structured runtime model for feature progress:
   - `SubtaskWeeklyUpdate`,
   - `FeatureWeeklyProgress`,
   - optional payload fields that preserve old payload compatibility.
4. Rebuild `Week Key Results` generation on top of structured subtask evidence:
   - retain subtask name/key,
   - derive done/progress/risk/dependency/plan per subtask,
   - generate deterministic feature-level summary plus detail lines.
5. Adjust AI rewrite targets so AI polishes structured summary text instead of trying to reconstruct missing context from flat aggregate strings.
6. Update HTML rendering for `Key Results` so subtask-driven features can show readable detail lines without breaking compact legacy output for simple features.
7. Update docs affected by the approved behavior:
   - `README.md`,
   - `docs/specs/common/SPEC.md`,
   - `docs/agents/knowledge-base.md`.
8. Run focused weekly-email verification, then full regression suite.
9. Produce independent review report and address findings before completion.

## Verification / Testing
- RED:
  - `pytest tests/test_jira_weekly_email_report.py -k "subtask or key_results"`
- GREEN:
  - `pytest tests/test_jira_weekly_email_report.py`
  - `pytest tests`

## Security / Policy Gates
- Keep existing comment sanitization before classification or AI prompt construction.
- Ensure AI prompts/outputs remain free of secrets, URLs, hashes, and raw file paths.
- Do not change dependency set.
- Preserve snapshot backward compatibility; new payload fields must not break loading/order extraction from old snapshots.

## Rollback
- Revert the structured subtask-progress path and restore current flat `feature["points"]` key-results logic.
- If helper extraction causes regressions, revert the refactor together with the behavior change rather than leaving a half-migrated state.

## Acceptance Criteria
- Features with active subtasks no longer lose visible weekly progress in `Week Key Results`.
- Named subtask contributions can surface done/progress/risk/plan details when present.
- Features without subtasks keep compact behavior.
- AI remains optional and deterministic output stays useful.
- Snapshot ordering and diff remain compatible.
- Focused and full tests pass.
