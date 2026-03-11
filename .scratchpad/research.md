# Weekly Email Report Research

Date: 2026-03-11
Owner: codex
Scope: project analysis before improving `jira_weekly_email`

## Current system shape

- Entry point: `stats_main.py` -> `stats_core/cli.py` dispatches `jira_weekly_email`.
- Main implementation is concentrated in `stats_core/reports/jira_weekly_email.py`.
- Tests are concentrated in `tests/test_jira_weekly_email_report.py`.
- User-facing contract/docs live in `README.md` and `docs/specs/common/SPEC.md`.

## Architecture findings

- `jira_weekly_email.py` is a large monolithic module containing:
  - week parsing and normalization,
  - Jira fetch + JQL assembly,
  - epic/parent enrichment,
  - payload aggregation,
  - AI rewrite prompt building and transport calls,
  - snapshot loading/saving and console diff,
  - vacation parsing,
  - HTML rendering,
  - optional docx/eml/outlook export.
- `JiraWeeklyEmailReport.run` orchestrates the full flow in four steps:
  - fetch Jira data,
  - build payload,
  - apply snapshot ordering + optional AI,
  - export report.

## Payload/report behavior

- Weekly evidence is driven by `updated >= week_start AND updated < week_end+1d`, then comments are filtered again to comments created inside the week.
- Feature status is aggregated from parent + subtasks, not only from parent comments.
- Report structure is stable and fixed:
  - Highlights,
  - Key Results and Achievements,
  - Next Week Plans,
  - Vacations,
  - separate Top Issues / Risks / For Help table.
- Previous snapshot order is reused to stabilize epic/item ordering.
- Summary table exists in payload but is printed only to console, not embedded into HTML.

## Quality/maintenance observations

- The weekly email logic is feature-rich and well-covered by tests, but the single-file design makes changes risky.
- Aggregation rules are encoded in many helper functions and branch conditions; behavior changes will likely require careful regression coverage.
- HTML is rendered via manual string concatenation, which makes layout changes possible but harder to reason about than a template-based renderer.
- AI rewriting is optional and bounded to selected text targets; deterministic fallback remains important because report quality must hold without AI.
- Runtime behavior is slightly ahead of public docs: current code renders a dedicated risks/issues block, while README/common spec still describe the report mostly as a four-chapter email.

## Existing verified scenarios from tests/docs

- week resolution and error handling,
- missing config/project handling,
- snapshot save/load and diff behavior,
- vacation parsing variants,
- label scoping by issue/epic/parent,
- high-priority and highest-priority inclusion rules,
- subtask-only progress and parent-chain epic resolution,
- localized/review status handling,
- markdown image cleanup (`!` artifact fix),
- risk table isolation from regular result sections,
- custom output file path handling,
- AI sanitization for links/paths/non-dict JSON responses.

## Likely improvement seams

- Split orchestration/data collection/payload shaping/rendering into separate modules.
- Isolate section-building rules for Highlights / Results / Plans / Risks.
- Make report text composition more declarative and easier to customize.
- Clarify which parts are deterministic business logic vs optional AI polishing.
- Keep snapshot ordering and diff behavior intact during any refactor.
- Preserve the effective payload contract or explicitly version snapshot/schema changes if section structure is redesigned.

## New focused finding: Week Key Results loses subtask detail

- Current feature-level `Week Key Results` text is built from a flattened `feature["points"]` list.
- `_collect_comment_points()` converts comments into de-duplicated first-sentence fragments, then `_classify_progress_points()` heuristically buckets them into done/plan/risk/dependency/misc.
- `_build_compact_feature_status()` and `_build_aggregate_input()` operate on that flattened pool, not on per-subtask contributions.
- As a result, the current report can lose:
  - which exact subtask made progress,
  - which problem belongs to which subtask,
  - which future plan belongs to which subtask,
  - ordering/context when multiple subtasks changed in the same week.
- Existing AI aggregation is threshold-based (`> 2` subtasks) and receives only compressed aggregate text, so it cannot reliably reconstruct missing per-subtask structure.
- Better target model: preserve per-subtask weekly contributions first, then derive a feature-level narrative from structured subtask evidence instead of from one flat string list.
