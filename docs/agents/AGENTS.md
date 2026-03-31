# Repo Agent Addendum

This file is the repo-specific addendum for `coding_statistics`.
Start with the global baseline from `%USERPROFILE%\AGENTS.md`, then apply the
project rules below.

## Project Summary
- Name: `coding_statistics`
- Stack: Python CLI toolkit (`pandas`, `requests`, `jira`, `openpyxl`, `python-docx`)
- Package manager: `pip` via `requirements.txt`

## Repo Map
- `stats_core/` - CLI entrypoints, report implementations, sources, exporters, utils
- `tests/` - pytest coverage
- `templates/` - Word/Excel templates
- `configs/` - runtime config examples
- `scripts/build/` - packaging scripts
- `docs/` - specs, design docs, and agent guidance
- `reports/` - generated local outputs; keep local-only

## Built-in Reports
- `jira_weekly`
- `jira_comprehensive`
- `jira_weekly_email`
- `unified_review`

## Baseline Commands
- Install: `pip install -r requirements.txt`
- Test suite: `pytest tests`
- Windows build: `scripts/build/build_stats_tool.cmd`
- Linux/macOS build: `./scripts/build/build_stats_tool.sh`

## Local Workflow
- Non-trivial `repo_change` work stays design-first:
  1. approved spec
  2. implementation plan
  3. RED tests
  4. implementation
  5. GREEN verification
  6. separate review pass
- Repo-local workflow skills live under `.codex/skills/` and supplement the global baseline instead of replacing it.
- Keep diffs minimal and additive.
- No new dependencies without explicit approval.
- No secrets, tokens, or credentials in tracked files or logs.
- If scope changes after approval, stop and update the spec before continuing.

## Repo-Specific Bootstrap Files
- `policy/task-routing-matrix.json` defines the compact routing profiles used by the repo.
- `policy/team-lead-orchestrator.md` defines the repo-level orchestrator expectations.
- `docs/agents/shared-guidelines.md` is a short shared checklist, not a replacement for the global baseline.

## Local-Only Runtime Artifacts
- Keep these out of git:
  - `.agent-memory/`
  - `.scratchpad/`
  - `coordination/tasks.jsonl`
  - `coordination/state/`
  - `coordination/reviews/`
  - `.claude/settings.local.json`
  - `reports/`

## Documentation Contract
- When report behavior changes, keep `README.md`, `docs/specs/common/SPEC.md`,
  and the relevant design docs in sync.
- When agent, policy, or bootstrap behavior changes, update the related files
  under `docs/agents/` and `policy/` in the same change.

## Definition of Done
- Approved scope implemented exactly.
- Verification commands run and reported, or limitations documented explicitly.
- No unrelated refactors or git hygiene regressions.
- Security and policy implications reviewed.
- Acceptance criteria mapped to evidence.
