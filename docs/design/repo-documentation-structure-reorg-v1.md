# Design Spec — Repository Documentation & Structure Reorganization (v1)

## Status
- Status: APPROVED
- Approval: APPROVED:v1
- Approved by: user
- Date: 2026-02-20

## 1) Summary
### Problem statement
- Documentation is fragmented (`README.md`, `SPEC.md`, `docs/design/*`) and not organized by report/feature lifecycle.
- There is no dedicated structure for: detailed feature specs, implementation planning, and implementation deep-dives.
- Configuration and report-input artifacts are mixed in repo root (`config.ini*`, `input.txt`, `members.xlsx`), which reduces discoverability and increases operational risk.
- Agent instructions are centralized in root `AGENTS.md`; we need a documentation-first canonical location that both `Codex` and `Claude` reference.
- Additional root-level technical files (`cache.json`, `jira_add_worklog.py`, `build_stats_tool*`, `setup.py`) are not explicitly classified by lifecycle (runtime data vs tooling vs packaging metadata).

### Goals
- Introduce a clear documentation hierarchy with separate sections for:
  - feature specs,
  - implementation plans (task decomposition),
  - implementation deep-dives (algorithms/code snippets).
- Organize specs per report and per feature.
- Introduce dedicated directories for configuration files and report-specific input assets.
- Define migration path from current structure with canonical paths only.
- Introduce explicit agent-instruction structure for `Codex` and `Claude`.
- Classify and relocate root-level operational files (cache, helper scripts, build scripts, packaging metadata) without root compatibility shims.

### Non-goals
- No functional report logic changes in this phase.
- No dependency changes.
- No behavioral changes to report outputs, only structure/governance/pathing.

## 2) Scope Boundaries
### In scope
- New repo structure design.
- Migration plan for docs/configs/input assets.
- Path-resolution compatibility strategy for existing CLI/report behavior.
- Governance model for future spec/plan/implementation docs.

### Out of scope
- Full code implementation of migration (handled in implementation phase).
- CI/CD policy redesign beyond docs/path checks needed for this feature.
- Rewriting all historical docs content in one step.

## 3) Assumptions & Constraints
- From agent guidelines (canonical path `docs/agents/AGENTS.md`):
  - minimal and additive changes,
  - no new dependencies without approval,
  - keep `README.md`, `docs/specs/common/SPEC.md`, and relevant design docs in sync,
  - tests command remains `pytest tests`.
- `README.md` remains in repository root (user requirement).
- Existing reports remain: `jira_weekly`, `jira_comprehensive`, `jira_weekly_email`, `unified_review`.
- Runtime defaults use canonical locations (`report_inputs/*`, `configs/*`, `data/cache/*`).
- Sensitive config values must not be committed in tracked config files.
- `jira_report_TEST_*` artifacts and `Sharepoint_statistics.py` have already been removed from root by user cleanup.
- `cache.json` is currently a default runtime cache path in `stats_core/cache.py` and `stats_core/config.py`.
- `jira_add_worklog.py` is a standalone utility script (not imported by report runtime flows).
- `build_stats_tool.cmd/.sh` are documented entrypoints for binary build in `README.md` and `AGENTS.md`.
- `setup.py` exists as packaging metadata entrypoint (no `pyproject.toml` currently).

## 4) Architecture (Target Structure)
### 4.1 Documentation tree
```text
docs/
  index.md
  decisions/
    decisions.md
  specs/
    common/
      _template.md
    jira_weekly/
      <feature-slug>-v1.md
    jira_comprehensive/
      <feature-slug>-v1.md
    jira_weekly_email/
      <feature-slug>-v1.md
    unified_review/
      <feature-slug>-v1.md
  plans/
    jira_weekly/
      <feature-slug>-plan-v1.md
    jira_comprehensive/
      <feature-slug>-plan-v1.md
    jira_weekly_email/
      <feature-slug>-plan-v1.md
    unified_review/
      <feature-slug>-plan-v1.md
  implementation/
    jira_weekly/
      <feature-slug>-impl-v1.md
    jira_comprehensive/
      <feature-slug>-impl-v1.md
    jira_weekly_email/
      <feature-slug>-impl-v1.md
    unified_review/
      <feature-slug>-impl-v1.md
```

### 4.2 Config tree
```text
configs/
  config.ini_template
  config.example.ini
  local/
    .gitkeep
```

### 4.3 Report-input assets tree (proposed name)
- Proposed directory name: `report_inputs/` (explicit and domain-specific).
```text
report_inputs/
  input.txt
  members.xlsx
```

### 4.4 Runtime data/cache tree
```text
data/
  cache/
    cache.json
```
- `cache.json` is treated as runtime data, not configuration and not documentation.
- Default cache path target becomes `data/cache/cache.json`, with legacy root `cache.json` fallback during migration.

### 4.5 Generated reports
- Keep generated outputs in `reports/` only.
- Root-level generated files should be moved to `reports/archive/` or removed if obsolete.

### 4.6 Tooling scripts tree
```text
scripts/
  build/
    build_stats_tool.cmd
    build_stats_tool.sh
  jira/
    jira_add_worklog.py
```
- These scripts are operational tooling, not report runtime modules.
- For migration safety, root wrappers can be kept temporarily and print/delegate to new script locations.

### 4.7 Packaging metadata tree
```text
packaging/
  setup.py
```
- Canonical file: `packaging/setup.py`.

### 4.8 Agent instruction tree
```text
docs/
  agents/
    AGENTS.md
    shared-guidelines.md
.codex/
  AGENTS.md
.claude/
  CLAUDE.md
```
- `docs/agents/AGENTS.md` is the canonical shared instruction file.
- `.codex/AGENTS.md` is a Codex entrypoint that references `docs/agents/AGENTS.md`.
- `.claude/CLAUDE.md` is a Claude entrypoint that references `docs/agents/AGENTS.md`.
- `docs/agents/shared-guidelines.md` stores reusable policy text referenced by canonical instructions.

## 5) Interfaces / Contracts
### 5.1 External/CLI behavior
- Existing CLI commands remain unchanged.
- Backward-compatible path resolution:
  - if explicit CLI param provided, use it;
  - else use config value;
  - else use new default under `report_inputs/`;
  - fallback to legacy root path for migration window.
- Cache path resolution:
  - if cache path explicitly configured, use it;
  - else use `data/cache/cache.json`;
  - fallback to legacy root `cache.json` during migration window.
- Agent instruction lookup for both tools resolves through `.codex/.claude` entrypoints to the `docs/agents` layer.

### 5.2 Internal module boundaries (implementation target)
- Introduce path resolver utility (module name example: `stats_core/pathing.py`):
  - `resolve_config_path(config_arg: str | None) -> Path`
  - `resolve_report_input_path(value: str | None, default_rel: str) -> Path`
  - `resolve_cache_path(value: str | None, default_rel: str = "data/cache/cache.json") -> Path`
  - `resolve_output_dir(value: str | None, default_rel: str = "reports") -> Path`
- Reports and CLI consume resolver utility instead of hardcoded root defaults.

### 5.3 Error handling strategy
- Missing required files:
  - warning with actionable message and expected path,
  - graceful skip only where already supported (`unified_review` with empty links path),
  - hard error for mandatory inputs in report flows that require them.
- Unknown/missing legacy files:
  - do not fail migration; surface warning with migration hint.

## 6) Data Model Changes & Migrations
### Data model
- No business data model changes.
- Repository metadata/path model changes only.

### Migration mapping (initial)
- `docs/design/_template.md` -> `docs/specs/common/_template.md`
- `docs/design/jira-weekly-email-ollama-v1.md` -> `docs/specs/jira_weekly_email/jira-weekly-email-ollama-v1.md`
- `docs/design/jira-weekly-epic-resolved-progress-v1.md` -> `docs/specs/jira_weekly/jira-weekly-epic-resolved-progress-v1.md`
- `docs/design/jira-comprehensive-results-v1.md` -> `docs/specs/jira_comprehensive/jira-comprehensive-results-v1.md`
- `docs/design/jira-comprehensive-results-v2.md` -> `docs/specs/jira_comprehensive/jira-comprehensive-results-v2.md`
- `docs/design/jira-epic-comment-weekly-ollama-v1.md` -> `docs/specs/common/jira-epic-comment-weekly-ollama-v1.md` (or report-specific after review)
- `docs/design/openpyxl-pin-update-v1.md` -> `docs/specs/common/openpyxl-pin-update-v1.md`
- `docs/decisions.md` -> `docs/decisions/decisions.md`
- Root `SPEC.md` removed; canonical spec is `docs/specs/common/SPEC.md`
- Root `AGENTS.md` removed; canonical agent guide is `docs/agents/AGENTS.md`
- New `.codex/AGENTS.md` created as tool entrypoint referencing `docs/agents/AGENTS.md`
- New `.claude/CLAUDE.md` created as tool entrypoint referencing `docs/agents/AGENTS.md`
- `config.ini_template` -> `configs/config.ini_template`
- `input.txt` -> `report_inputs/input.txt`
- `members.xlsx` -> `report_inputs/members.xlsx`
- `cache.json` -> `data/cache/cache.json`
- `jira_add_worklog.py` -> `scripts/jira/jira_add_worklog.py`
- `build_stats_tool.cmd` -> `scripts/build/build_stats_tool.cmd`
- `build_stats_tool.sh` -> `scripts/build/build_stats_tool.sh`
- `setup.py` (canonical logic) -> `packaging/setup.py`
- Root `setup.py` removed (no compatibility shim)
- Root `config.ini` removed; local config path is `configs/local/config.ini`

## 7) Edge Cases & Failure Modes
- Relative path resolution differs by current working directory.
- Config file path may be custom (`--config`); moving templates must not break setup flow.
- Cache file may exist in old root location; migration must not silently drop cache usage.
- Historical docs links in README/SPEC may break after relocation; requires link update pass.
- Windows path handling for spaces/quotes in config values.

## 8) Security Requirements
- Do not store real credentials in tracked configs (`config.ini` should be local-only).
- Tracked config files must be templates/examples with placeholders only.
- Documentation must include secret-handling policy:
  - no tokens/passwords in repo,
  - no secrets in logs/screenshots.
- No new dependencies without explicit approval.

## 9) Performance Requirements
- Path resolution overhead must be O(1) per call.
- Documentation discovery should remain fast (static file tree only).
- No runtime report performance regressions from migration; only path lookup logic changes.

## 10) Observability
- Add migration-level logs in runtime path resolution:
  - selected config path,
  - selected input path,
  - fallback source used (`new_default`, `legacy_fallback`, `explicit`).
- Alerting requirement (lightweight): any unresolved required path should produce clear error with remediation.

## 11) Test Plan
### Unit tests
- Path resolver tests:
  - explicit path precedence,
  - config path usage,
  - new default path,
  - legacy fallback.
- Cache path tests:
  - default to `data/cache/cache.json`,
  - legacy root fallback when new path missing,
  - explicit cache path override in config.
- Report-specific path tests:
  - `unified_review` default links file resolution,
  - `jira_weekly` and `jira_comprehensive` member file default resolution.

### Integration checks
- CLI `setup` still creates/uses expected config file.
- Existing report commands run with legacy root files and with new `report_inputs/` layout.

### Verification commands
- `pytest tests`
- targeted runs:
  - `python stats_main.py run --report unified_review --output-formats excel`
  - `python stats_main.py run --report jira_weekly --start <date> --end <date> --params project=<KEY>`

## 12) Rollout / Rollback Plan
### Rollout (phased)
1. Create directory scaffolding (`docs/specs`, `docs/plans`, `docs/implementation`, `configs`, `report_inputs`, `data/cache`, `scripts/build`, `scripts/jira`, `packaging`).
2. Move docs with redirect/index updates; keep temporary compatibility pointers in `docs/design/`.
3. Add path resolver + backward-compatible fallbacks in CLI/reports.
4. Move templates/default input files and cache file to new locations.
5. Move operational scripts (`build_stats_tool*`, `jira_add_worklog.py`) into `scripts/` and remove root copies.
6. Move canonical packaging setup logic into `packaging/setup.py` and remove root `setup.py`.
7. Update `README.md` and canonical `docs/specs/common/SPEC.md` links/paths.
8. Use canonical `docs/agents/AGENTS.md` and point `.codex/AGENTS.md` + `.claude/CLAUDE.md` to this docs layer.

### Rollback
- Restore previous paths and references from git.
- Keep moved files duplicated temporarily (old+new) if immediate rollback needed.
- Disable new path resolver usage behind a compatibility switch (if implemented).

## 13) Acceptance Criteria Checklist
- [ ] `docs/` contains explicit `specs`, `plans`, `implementation`, `decisions` structure.
- [ ] Specs are grouped by report and feature (one feature = one spec file).
- [ ] Planning docs exist and decompose feature specs into implementation tasks/steps.
- [ ] Implementation docs include code/algorithm explanations for completed features.
- [ ] `configs/` contains tracked config templates/examples only (no secrets).
- [ ] `report_inputs/` contains `members.xlsx` and `input.txt` defaults.
- [ ] `data/cache/cache.json` is used as default runtime cache path with root fallback during migration.
- [ ] `jira_add_worklog.py` and `build_stats_tool*` are moved under `scripts/` with documented invocation paths.
- [ ] Packaging metadata is normalized (`packaging/setup.py` canonical, no root `setup.py`).
- [ ] Canonical agent instructions are stored in `docs/agents/AGENTS.md`.
- [ ] `.codex/AGENTS.md` and `.claude/CLAUDE.md` both reference the docs-layer instructions.
- [ ] `README.md` and canonical `docs/specs/common/SPEC.md` are updated; root `SPEC.md` is removed.
- [ ] `pytest tests` remains the canonical verification command.

## Implementation Planning Decomposition (Lead-Dev View)
### EPIC A — Documentation Architecture
- A1: Create folder scaffold and index conventions.
- A2: Define templates for spec/plan/implementation docs.
- A3: Migrate existing design docs into report-specific spec locations.

### EPIC B — Config & Input Asset Reorganization
- B1: Introduce `configs/` and `report_inputs/`.
- B2: Introduce `data/cache/` and migrate cache path defaults with fallbacks.
- B3: Implement path-resolution compatibility layer.
- B4: Update defaults in reports/CLI with legacy fallbacks.

### EPIC C — Governance & Cleanup
- C1: Define lifecycle policy for generated artifacts (`reports/` only).
- C2: Move tooling scripts into `scripts/` and update docs/invocation compatibility.
- C3: Normalize packaging metadata placement (`packaging/setup.py` only).
- C4: Split and normalize agent instruction files for `.codex` and `.claude`.
- C5: Update README/SPEC + add migration notes.

## Open Questions
1. Should root-level legacy input/cache fallbacks remain, or be removed in the next cleanup phase?

---
REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
