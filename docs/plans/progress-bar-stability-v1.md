# Implementation Plan: Stable Multi-Progress Bars with Log-Safe Output

## Goal
Ensure progress bars remain fixed at the bottom with logs above, including a main
bar and optional per-thread bars for parallel work.

## Scope
- Extend ProgressManager to manage child bars with fixed positions.
- Update parallel_map to use child bars safely per thread.
- Wire per-thread bars for heavy parallel work (AI batches, link processing).
- Add tests for child bars and parallel progress integration.

## Non-Goals
- New dependencies.
- Changing report outputs or business logic.

## Steps
1. Add tests for child bar creation and per-thread updates (RED).
2. Run pytest (RED) to confirm failing tests.
3. Implement child bar support in `stats_core/utils/progress.py`.
4. Update `parallel_map` to allocate and update child bars per thread.
5. Update reports to pass progress manager and labels into parallel_map.
6. Run pytest (GREEN).

## Testing / Verification
- `python -m pytest`

## Rollback
- Revert progress utils and parallel_map changes.

## Acceptance Criteria
- Main bar stays at bottom; per-thread bars appear under it.
- Logs stay above bars (no breakage).
- Comprehensive report bars remain stable with parallel AI.
- Tests pass.
