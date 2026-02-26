# Implementation Plan: AI Comments Quality and Language Fixes

## Goal
Improve AI_Comments quality and enforce English output for Comments_Period.

## Scope
- Update AI prompt to English with explicit rules for results/links.
- Add fallback extraction for results/links when AI returns insufficient data.
- Update formatting labels to English.
- Add tests for prompt, results fallback, and no-data behavior.

## Non-Goals
- New providers or dependencies.
- Changes to report schema.

## Steps
1. Add tests (RED):
   - Prompt contains English requirements and JSON fields.
   - Fallback converts results/link-only comments into meaningful output.
   - No-data returns "Insufficient data."
2. Run pytest (RED).
3. Implement prompt and fallback changes in `jira_comprehensive.py`.
4. Run pytest (GREEN).

## Testing / Verification
- `python -m pytest`

## Rollback
- Revert changes in `jira_comprehensive.py` and related tests.

## Acceptance Criteria
- AI_Comments output is English.
- "results:" + link produces meaningful output, not "Insufficient data."
- Tests pass.
