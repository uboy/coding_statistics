# Implementation Plan — Repo Documentation Structure Reorg (v1)

## Scope
- Reorganize documentation, configs, report inputs, runtime cache, tooling scripts, and packaging metadata.
- Use canonical paths only for root-level docs/tooling files.

## Task Breakdown

### T1 — Documentation scaffolding
- Create `docs/specs`, `docs/plans`, `docs/implementation`, `docs/decisions`, `docs/agents`.
- Add section indexes/placeholders.
- Acceptance: directories are present and tracked.

### T2 — Spec migration
- Move canonical spec to `docs/specs/common/SPEC.md`.
- Remove root `SPEC.md`.
- Acceptance: canonical spec exists only in docs tree.

### T3 — Agent-instruction migration
- Move canonical agent guide to `docs/agents/AGENTS.md`.
- Create `.codex/AGENTS.md` and `.claude/CLAUDE.md` entrypoints to canonical doc.
- Remove root `AGENTS.md`.
- Acceptance: `.codex/.claude` entrypoints reference canonical doc; no root copy.

### T4 — Operational files relocation
- Move `config.ini_template` to `configs/config.ini_template`.
- Move `input.txt`/`members.xlsx` to `report_inputs/`.
- Move `cache.json` to `data/cache/cache.json`.
- Move `build_stats_tool.*` to `scripts/build/`.
- Move `jira_add_worklog.py` to `scripts/jira/`.
- Move canonical `setup.py` logic to `packaging/setup.py`.
- Acceptance: files exist in target locations.

### T5 — Compatibility layer
- Add shared path resolver module.
- Update CLI setup/template resolution.
- Update unified_review links default resolution.
- Update jira_comprehensive member list default resolution.
- Update cache manager construction + default cache path behavior.
- Acceptance: explicit path > new default > legacy fallback.

### T6 — Root cleanup
- Remove root copies for `build_stats_tool.*`, `jira_add_worklog.py`, `setup.py`, `config.ini`.
- Acceptance: only canonical files remain in target directories.

### T7 — Documentation updates
- Update README paths (template, config, inputs, cache, build scripts).
- Update canonical SPEC paths.
- Acceptance: docs reference canonical structure only for root docs/tooling files.

### T8 — Verification
- Run `pytest tests`.
- Record pass/fail and known unrelated failures.
