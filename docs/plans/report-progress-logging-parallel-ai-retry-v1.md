# Implementation Plan: Report Progress Logging, AI Retries, Parallelization

## Goal
Provide a progress bar for all reports, step-level logging, AI timeout retries,
and parallel execution for heavy independent tasks.

## Scope
- Add progress/logging utilities and integrate into CLI and all report runs.
- Add AI retry helper and use it for AI requests.
- Add parallel map helper and use it for AI batches and heavy tasks.
- Add tests covering progress handler, AI retries, parallel map.

## Non-Goals
- New dependencies.
- Changing report outputs or business logic.

## Steps
1. Add tests for ProgressManager/TqdmLoggingHandler, retry helper, parallel map.
2. Run tests in RED phase (expected failures before implementation).
3. Implement `stats_core/utils/progress.py`, `ai_retry.py`, `parallel.py`.
4. Wire progress manager and logging handler in `stats_core/cli.py`.
5. Add progress steps in each report:
   - `jira_weekly`, `jira_comprehensive`, `jira_weekly_email`, `unified_review`.
6. Use AI retry helper for all AI requests (Ollama/WebUI).
7. Parallelize AI batch calls and heavy independent tasks.
8. Run tests in GREEN phase.

## Testing / Verification
- `python -m pytest`

## Rollback
- Remove new utils modules and progress/parallel/retry integrations.

## Acceptance Criteria
- All reports show progress bar and step logs.
- Logs do not break the progress bar.
- AI timeouts retry 3 times with delays.
- Heavy AI tasks use parallel execution.
- Tests pass.
