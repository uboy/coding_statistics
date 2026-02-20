# Design Spec — Jira Summary Sanitization + Engineer Assistance from Worklogs (v1)

## 1) Summary
### Problem statement
After introducing summary sections and AI text generation:
- Jira keys (e.g. `ABC-123`) must not appear in summary text.
- In `jira_comprehensive` engineer metrics, `Assistance_Provided` currently relies on labels only, but must also count worklog support in чужие задачи.

### Goals
- Remove Jira issue keys from generated summary text output.
- Recalculate `Assistance_Provided` in `jira_comprehensive` using `worklog_entries`:
  - if engineer logs time on issue where assignee is another person, count +1 for that issue.
  - count unique foreign issues per engineer.
- Keep existing report behavior stable otherwise.

### Non-goals
- No changes to Jira data fetching contracts outside required fields.
- No changes to report formats/sheet names.
- No new dependencies.

## 2) Scope boundaries
### In scope
- Summary text rendering in:
  - monthly summary sheet (`jira_comprehensive`)
  - weekly summary section (`jira_weekly`)
- Engineer metrics calculation in `jira_comprehensive` (`Assistance_Provided` only).
- Tests covering both requirements.

### Out of scope
- QA/PM metrics logic changes.
- Reworking AI provider transport.

## 3) Assumptions + constraints
- Process constraints from `AGENTS.md` apply: minimal diffs, full `pytest tests`, no drive-by refactors.
- Existing member identity mapping remains the source of truth (`username` / optional `Jira` column / display name fallback).
- Worklog entries already available via `fetch_worklog_entries(...)` for report period.

## 4) Architecture
### A) Summary sanitization
- Reuse existing summary text sanitizer.
- Enforce Jira key removal (`[A-Z]+-\d+`) at final output stage for all summary lines.
- Ensure counters lines remain unchanged.

### B) Assistance calculation from worklog entries
- Extend engineer metrics pipeline to accept `worklog_entries_df`.
- For each engineer:
  1. find issues where `Worklog_Author` matches engineer identity;
  2. exclude issues where engineer is the assignee of that issue;
  3. count unique `Issue_Key` remaining;
  4. add to `Assistance_Provided` (replacing label-only logic).

## 5) Interfaces/contracts
### Internal function contract change
- `calculate_engineer_metrics(...)`:
  - from: `(issues_df, members_df, code_volume_df)`
  - to: `(issues_df, members_df, code_volume_df, worklog_entries_df)`

### Backward compatibility
- Keep output columns unchanged.
- Keep `Assistance_Provided` column name unchanged.

## 6) Data model changes + migrations
- No migrations.
- Runtime-only calculation changes.

## 7) Edge cases + failure modes
- Engineer logs in own issue only -> assistance 0.
- Multiple logs in same foreign issue -> counted once.
- Missing assignee on issue -> treat as foreign (if author identified), count once.
- Missing/empty worklog entries -> assistance falls back to 0.
- Summary text with malformed AI output -> fallback text sanitized, no Jira keys.

## 8) Security requirements
- No secret/logging changes.
- No new injection vectors.
- Continue sanitizing AI text and suppressing links/keys in summary.

## 9) Performance requirements
- Assistance calculation complexity ~ `O(n)` over worklog entries for period.
- No additional external calls.

## 10) Observability
- Extend report summary logs with:
  - number of assistance issues detected (aggregate),
  - confirmation that summary sanitization removed keys when present (debug-level optional).

## 11) Test plan
- `tests/test_jira_comprehensive_report.py`
  - add case where engineer logs in foreign issue:
    - `Assistance_Provided == number_of_unique_foreign_issues`.
  - add case with repeated logs in same foreign issue:
    - still counted as 1.
- `tests/test_jira_weekly_report.py` and/or comprehensive summary tests:
  - assert summary text does not contain Jira keys pattern.
- Full regression:
  - `pytest tests`

## 12) Rollout + rollback
### Rollout
1. Implement sanitizer/key removal enforcement.
2. Implement assistance-from-worklogs logic.
3. Update tests.
4. Run full suite.

### Rollback
1. Revert assistance formula to previous behavior.
2. Revert summary sanitization delta.

## 13) Acceptance criteria
- [ ] Summary output contains no Jira keys.
- [ ] `Assistance_Provided` counts unique foreign issues where engineer logged time.
- [ ] Own-assignee issues are not counted as assistance.
- [ ] Existing report sheets/sections remain intact.
- [ ] `pytest tests` passes.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
