# Feature Design Specification: Stable Multi-Progress Bars with Log-Safe Output

## 1) Summary
Problem: progress bars (especially in comprehensive report and parallel threads) are broken by logs and drift around the console.
Goal: keep progress bars pinned at the bottom, with logs printed above; support one global bar plus per-thread bars (if enabled), in a stable order.
Non-goals: new UI, external dependencies, changing report semantics.

## 2) Scope Boundaries
In scope:
- Stable multi-progress bar layout: global first, then per-thread bars.
- Logs appear above progress bars without breaking them.
- Apply to all reports with progress (focus on jira_comprehensive and AI parallel tasks).

Out of scope:
- Custom terminal UI frameworks.
- Disabling logs entirely.

## 3) Assumptions + Constraints
- `tqdm` is available.
- No new dependencies.
- CLI logging already uses tqdm-safe handler.

## 4) Architecture
Components:
- `stats_core/utils/progress.py`: extend to support multi-bars with fixed positions.
- `ProgressManager` maintains a main bar and optional child bars.
- `TqdmLoggingHandler` uses `tqdm.write` to log above bars.

Data flow:
Report -> ProgressManager -> create main bar + child bars -> updates with positions.

## 5) Interfaces / Contracts
ProgressManager:
- `create_child(name: str) -> ChildProgress`
- `ChildProgress.advance(n=1)` updates a dedicated bar at fixed position.
- `close()` closes all bars.

Rules:
- Main bar position 0.
- Child bars positions 1..N in creation order.
- Logs always via `tqdm.write`.

## 6) Data Model Changes
None.

## 7) Edge Cases + Failure Modes
- Non-TTY output: disable child bars, fallback to main bar only.
- Errors in threads: ensure bar closure.
- Many threads: cap child bars to max_workers.

## 8) Security Requirements
No secrets in logs.

## 9) Performance Requirements
Minimal overhead; do not update bars too frequently.

## 10) Observability
Log major steps only (start/end). Avoid noisy per-item logs.

## 11) Test Plan
- Unit test: child bars created with stable positions.
- Unit test: logging handler does not break bars (mock `tqdm.write`).
- `python -m pytest`.

## 12) Rollout + Rollback
Rollout: update progress utils and replace ad-hoc per-thread progress updates.
Rollback: revert progress utils changes.

## 13) Acceptance Criteria
- Progress bars remain at bottom in stable order.
- Logs show above bars without breaking.
- Comprehensive report parallel tasks do not create drifting bars.
- Tests pass.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
APPROVED:v1 (2026-02-26)
