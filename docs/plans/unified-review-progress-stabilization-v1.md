# Implementation Plan: Unified Review Progress Stabilization

## Goal
Make `unified_review` show useful per-link progress during parallel processing while leaving SSL/session behavior unchanged.

## Approved Scope
- Update progress accounting for `unified_review`.
- Add focused tests for `parallel_map` main-progress behavior and report-level parallel progress.
- Make `ProgressManager.advance()` safe for worker-thread calls.
- Disable visible tqdm output in non-TTY stderr while keeping internal progress accounting.
- Preserve `PermissiveSSLAdapter` and existing `[ssl]` behavior.

## Files
- `stats_core/utils/parallel.py`
- `stats_core/utils/progress.py`
- `stats_core/reports/unified_review.py`
- `tests/test_progress_utils.py`
- `tests/test_unified_review_report.py`

## Execution Steps
1. Add RED tests for per-item main progress in `parallel_map` and no bulk advance in `unified_review`.
2. Run focused tests and confirm the new tests fail.
3. Implement `parallel_map(..., advance_main=False)` with opt-in main progress updates.
4. Add locking around `ProgressManager.advance()` and `set_total()`.
5. Disable visible tqdm output when stderr is not a TTY.
6. Call `parallel_map(..., advance_main=True)` from `unified_review` and remove the bulk `progress.advance(len(links))`.
7. Run focused tests.
8. Run full `pytest tests`.
9. Perform a separate review pass against the approved spec.

## Verification
```powershell
pytest tests/test_progress_utils.py tests/test_unified_review_report.py
pytest tests
```

## Acceptance Criteria
- `unified_review` main progress advances per processed link in parallel mode.
- No duplicate main progress advance occurs after `parallel_map`.
- Sequential mode remains correct.
- Progress totals remain meaningful for empty, filtered, and no-row runs.
- `ProgressManager.advance()` is thread-safe.
- Visible progress bar output is disabled for non-TTY stderr to avoid one-line-per-refresh spam.
- `PermissiveSSLAdapter` and SSL configuration behavior remain unchanged.
- Focused tests pass.
- Full test suite passes or unrelated failures are documented.
- Security review confirms no new secret logging and no SSL behavior change.
