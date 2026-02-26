# Implementation Plan: Jira Comprehensive Comments_Period Sheet

## Goal
Add a new sheet to `jira_comprehensive` that lists issues with comment activity
in a period, includes all comments, comments-in-period, and AI summary.

## Scope
- Modify `stats_core/reports/jira_comprehensive.py` to build `Comments_Period`.
- Reuse existing AI infrastructure for summarization.
- Add tests for comment filtering and AI prompt formatting.

## Non-Goals
- New reports or new dependencies.
- Changes to existing sheets except adding the new one.

## Steps
1. Add test fixtures for comments with created/updated dates.
2. Add a unit test for filtering comments-in-period (created OR updated).
3. Add a unit test for AI prompt generation requirements.
4. Implement comment extraction and period filtering in `jira_comprehensive`.
5. Build new `Comments_Period` DataFrame with required columns.
6. Integrate AI summarization for comments-in-period to `AI_Comments`.
7. Write new sheet to Excel output.
8. Run tests in GREEN phase.

## Testing / Verification
- `pytest tests`

## Rollback
- Remove new sheet generation and related helper code/tests.

## Acceptance Criteria
- `Comments_Period` sheet exists with required columns.
- `Comments` contains all comments; `Comments_In_Period` only those in period.
- `AI_Comments` summarizes comments-in-period per spec.
- Only issues with comment activity in period appear in the sheet.
