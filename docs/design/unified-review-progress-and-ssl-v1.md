# Feature Design Specification: Unified Review Progress Stabilization

## 1) Summary
Problem: `unified_review` shows a misleading main progress bar. For a large links file it starts at `0/N`, then waits through the parallel link processing work, then jumps to repeated near-final states such as `99% 255/257` and `256/257`. The output is hard to read because progress redraws and logs can appear as repeated lines.

SSL note: `PermissiveSSLAdapter` is intentionally kept as-is in this change. The primary runtime environment is a closed corporate zone with self-signed certificates and corporate proxy certificates, where strict default OpenSSL/requests validation can prevent the tool from working at all. This spec records the security tradeoff but does not change SSL behavior.

Goals:
- Make the main `unified_review` progress bar advance once per processed link in parallel and sequential modes.
- Keep the final total meaningful: links plus report-level steps.
- Avoid duplicate progress advances after `parallel_map`.
- Keep log-safe tqdm output behavior intact.
- Avoid noisy multi-line progress output when stderr is not an interactive TTY.
- Preserve the existing `PermissiveSSLAdapter` behavior.

Non-goals:
- No new terminal UI dependency.
- No report data model or export format changes.
- No SSL/session/proxy behavior changes in this implementation.

## 2) Scope Boundaries
In scope:
- `stats_core/reports/unified_review.py`
- `stats_core/utils/parallel.py`
- `stats_core/utils/progress.py`
- focused tests under `tests/`

Out of scope:
- Reworking all source adapters to share one HTTP session factory.
- Changing cache format.
- Changing report output columns.
- Disabling logs globally.
- Changing `PermissiveSSLAdapter`, `[ssl]` config parsing, or session verification defaults.

## 3) Assumptions + Constraints
- Project profile: `repo_change`, size: `non_trivial`.
- The repo requires design-first work and explicit approval before implementation.
- No new dependencies.
- Existing `tqdm` progress infrastructure stays in use.
- `reports/`, `.scratchpad/`, and coordination artifacts are local-only runtime paths.
- Secrets, tokens, proxy passwords, and auth headers must not be logged.
- The closed-zone runtime may require permissive SSL handling; keep it stable for this fix.

## 4) Architecture
### Progress
Current flow:
1. CLI creates `ProgressManager(total_steps=1)`.
2. `UnifiedReviewReport.run()` sets total to `2`.
3. `_rows_from_links()` parses links and sets total to `len(links) + 2`.
4. In parallel mode, `parallel_map()` only advances optional child bars.
5. After `parallel_map()` returns, `unified_review` calls `progress.advance(len(links))` once.
6. The `ProgressStep` context then advances once for `Process links`, and export advances once.

Proposed flow:
1. Keep total as `len(links) + 2`.
2. Extend `parallel_map()` with an optional `advance_main` flag, defaulting to `False` for compatibility.
3. For `unified_review`, call `parallel_map(..., progress_manager=progress, advance_main=True, child_label="Links")`.
4. In `parallel_map._wrap`, after each item finishes, advance the main manager by `1` and then advance the assigned child bar if present.
5. Remove the bulk `progress.advance(len(links))` in `unified_review`.
6. Make `ProgressManager.advance()` thread-safe because parallel workers may update the shared main bar.

This gives a visible sequence like `1/259`, `2/259`, ..., rather than `0/259` followed by a late jump.

### SSL
No code changes.

Accepted rationale:
- The tool is primarily used in a closed corporate network.
- Endpoints may use self-signed certificates, internal CA chains, or corporate proxy certificates.
- The existing adapter is a compatibility mechanism that keeps the report usable in that environment.

Risk note:
- `PermissiveSSLAdapter` relaxes strict OpenSSL checks when `bundle-ca` is present.
- This is acceptable for the current deployment assumption, but it should remain documented and should not be expanded to new environments without a separate security review.

## 5) Interfaces / Contracts
### `parallel_map`
Proposed internal signature:

```python
def parallel_map(
    func,
    items,
    *,
    max_workers=4,
    progress_manager=None,
    child_label="worker",
    advance_main=False,
) -> list:
    ...
```

Contract:
- Return order remains the same as input order.
- If `advance_main=True`, main progress advances once per completed item in both parallel and sequential paths.
- If `advance_main=False`, existing callers keep current behavior.
- Child bars remain TTY-only through `ProgressManager.create_children()`.

### `ProgressManager.advance`
Contract:
- Safe to call from worker threads.
- `current` and tqdm bar state update together under one lock.

### SSL config
Contract:
- No interface changes.
- Existing `[ssl]` behavior remains unchanged.

## 6) Data Model Changes + Migrations
No persisted data model changes.

No config migration.

## 7) Edge Cases + Failure Modes
- Empty links file: total should stay finite, no division oddities, and report should exit with the existing warning path.
- Blank lines in links file: total follows parsed non-empty links, not physical file line count.
- Worker exception: `executor.map` still raises; progress may stop at the failed item count, which is useful.
- Non-TTY output: tqdm may still emit completed bars, but child bars stay disabled; main bar still advances per item.
- Non-TTY output: visible tqdm output should be disabled to avoid one progress redraw per line; in-memory progress accounting must still advance.
- Export skipped because no rows: progress still completes the final report-level step.
- SSL/proxy behavior: unchanged; any current closed-zone compatibility remains intact.

## 8) Security Requirements
- Avoid logging tokens, passwords, Authorization, Private-Token, and proxy credentials.
- Do not modify SSL settings in this progress fix.
- Preserve existing closed-zone compatibility behavior.

## 9) Performance Requirements
- Main progress update is one lightweight lock and one tqdm update per link.
- Parallel processing throughput should remain dominated by network I/O.
- No per-link info logs should be added.

## 10) Observability
- Keep existing step logs: report started, processing links, cache saved, export.
- Progress bar itself is the per-link observability signal.

## 11) Test Plan
Unit tests:
- `parallel_map` with `advance_main=True` advances the main progress exactly once per item.
- `parallel_map` with default `advance_main=False` preserves existing behavior.
- `ProgressManager.advance()` updates `current` correctly under repeated calls.
- `ProgressManager` disables visible tqdm output when stderr is not a TTY while still updating `current`.
- `UnifiedReviewReport._rows_from_links()` in parallel mode does not bulk-advance after processing.
- No tests should require SSL behavior changes.

Verification commands:

```powershell
pytest tests/test_progress_utils.py tests/test_unified_review_report.py
pytest tests
```

Manual verification:

```powershell
python stats_main.py run --report unified_review --output-formats excel --params parallel_workers=4
```

Expected manual result:
- Main bar starts near `0/N`, then advances steadily during link processing.
- No late bulk jump from `0/N` to `N-2/N`.
- Logs remain above or around tqdm output without creating a separate status line for every item in TTY mode.
- In non-TTY/IDE consoles that cannot redraw one line, progress accounting still runs but visible tqdm output is suppressed to avoid log spam.

## 12) Rollout Plan + Rollback Plan
Rollout:
- Implement progress changes first with tests.
- Do not touch SSL/session code in this change.
- Run focused tests, then full `pytest tests`.

Rollback:
- Revert the small changes in `parallel.py`, `progress.py`, and `unified_review.py`.
- Existing progress behavior returns.

## 13) Acceptance Criteria Checklist
- [ ] `unified_review` main progress advances per processed link in parallel mode.
- [ ] No duplicate main progress advance occurs after `parallel_map`.
- [ ] Sequential mode remains correct.
- [ ] Progress totals remain meaningful for empty, filtered, and no-row runs.
- [ ] `ProgressManager.advance()` is thread-safe.
- [ ] Visible progress bar output is disabled for non-TTY stderr to avoid one-line-per-refresh spam.
- [ ] `PermissiveSSLAdapter` and SSL configuration behavior remain unchanged.
- [ ] Focused tests pass.
- [ ] Full test suite passes or any unrelated failures are documented.
- [ ] Security review confirms no new secret logging and no SSL behavior change.

## Approval
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"

APPROVED:v1
