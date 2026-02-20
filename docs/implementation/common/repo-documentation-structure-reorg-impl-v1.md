# Implementation Notes — Repo Documentation Structure Reorg (v1)

## Summary
Implemented repository structure migration for docs/configs/inputs/scripts with canonical root layout (no root compatibility files).

## Implemented Components

### 1) Path resolver (`stats_core/pathing.py`)
- Added reusable resolvers for:
  - config template path,
  - links input path,
  - member list path,
  - cache path.
- Resolution strategy:
  1. explicit path (if provided),
  2. new default location,
  3. legacy root fallback.

### 2) Runtime integration
- `stats_core/config.py`: `create_cache_manager()` now resolves cache path with new default and legacy fallback.
- `stats_core/cache.py`: default cache path updated to `data/cache/cache.json`; save creates parent directories.
- `stats_core/cli.py`: setup uses template resolver; run normalizes links file via resolver.
- `stats_core/reports/unified_review.py`: links default now resolves to `report_inputs/input.txt` with legacy fallback.
- `stats_core/reports/jira_comprehensive.py`: default member list resolves to `report_inputs/members.xlsx` with legacy fallback.

### 3) Repository structure and compatibility
- Canonical paths:
  - `docs/specs/common/SPEC.md`,
  - `docs/agents/AGENTS.md`,
  - `configs/config.ini_template`,
  - `report_inputs/input.txt`, `report_inputs/members.xlsx`,
  - `data/cache/cache.json`,
  - `scripts/build/build_stats_tool.cmd`, `scripts/build/build_stats_tool.sh`,
  - `scripts/jira/jira_add_worklog.py`,
  - `packaging/setup.py`.
- Root files removed:
  - `build_stats_tool.cmd`,
  - `build_stats_tool.sh`,
  - `jira_add_worklog.py`,
  - `setup.py`,
  - `AGENTS.md`,
  - `SPEC.md`,
  - `config.ini` (moved to `configs/local/config.ini`).

### 4) Documentation alignment
- Updated `README.md` and canonical spec to new paths.
- Added docs index + section placeholders.

## Verification
- Command: `python -m pytest tests`
- Result: no new failures from this migration; 4 pre-existing failures remain in `tests/test_jira_weekly_email_report.py`.
