# Weekly Email Improvement Plan

Date: 2026-03-11
Owner: codex
Status: review_required

## Goal

Improve `jira_weekly_email` without breaking the current user-facing contract:

- preserve CLI/config compatibility,
- preserve snapshot ordering and console diff semantics,
- preserve Outlook-friendly HTML output,
- preserve acceptable deterministic output when AI is disabled.

## Recommended direction

Recommended baseline: do an incremental refactor together with report-content improvements.

Reason:

- content-only changes inside the current monolith will be hard to sustain,
- a full rewrite is unnecessary and high-risk,
- the best tradeoff is to separate section-building and text-composition logic while keeping the existing payload/output behavior stable.

## Proposed phases

### Phase 1: Freeze current contract with regression coverage

- Keep chapter order stable.
- Keep previous-snapshot ordering behavior stable.
- Keep separation between highlights, results, plans, vacations, and risk block stable.
- Keep parent/subtask status derivation stable.
- Keep deterministic output acceptable with AI disabled.

### Phase 2: Split responsibilities

- Keep `JiraWeeklyEmailReport.run` as orchestration only.
- Extract focused units for:
  - Jira evidence collection,
  - payload/section building,
  - AI rewrite integration,
  - rendering/export helpers.

### Phase 3: Make section logic explicit

- Isolate builders for:
  - Highlights,
  - Key Results,
  - Next Week Plans,
  - Risks,
  - Vacations.
- Reduce branch-heavy coupling between labels, priorities, parent/subtask aggregation, and rendering.

### Phase 4: Improve deterministic text quality

- Clarify what counts as completed progress.
- Clarify what becomes next-week intent.
- Improve comment-to-status reduction for noisy Jira comments.
- Keep AI as optional polishing over already-useful deterministic text.

### Phase 5: Renderer cleanup

- Keep current visual contract by default.
- Hide manual string assembly behind smaller render helpers.
- Avoid new template dependencies unless explicitly approved.

## Constraints

- No new dependencies unless separately approved.
- Do not regress optional `docx`, `eml`, or Windows `outlook_draft`.
- Do not silently change payload/snapshot shape that ordering and diff depend on.
- If section structure changes, version or migrate snapshot compatibility deliberately.

## Verification

- Run focused weekly-email tests first.
- Run full `tests/test_jira_weekly_email_report.py`.
- Expand regression coverage if shared AI helpers or CLI wiring change.

## Review checkpoint

Recommended approval scope:

- proceed with incremental refactor + content-quality improvements,
- keep external behavior stable unless we explicitly agree on visual/content changes.
