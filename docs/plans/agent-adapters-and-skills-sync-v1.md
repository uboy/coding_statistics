# Implementation Plan: Sync Repo Agent Adapters and Skills with Global Baseline

## Goal

Align the repository's tracked adapter/config/skill layer with the current global
agent baseline while keeping repo-specific guidance minimal and de-tracking
local-only runtime artifacts.

## Scope

- Update thin adapter entrypoints for supported systems.
- Replace stale repo-local Codex config with a minimal non-conflicting file.
- Align repo-local workflow skills with the current global approval, commit,
  verification, and review gates.
- Add minimal bootstrap policy files required by the repo contract.
- Ignore and de-track local-only agent runtime files and settings.
- Add focused automated tests for the repo agent contract.

## Files to Change

- `.codex/AGENTS.md`
- `.claude/CLAUDE.md`
- `CURSOR.md`
- `GEMINI.md`
- `OPENCODE.md`
- `.codex/config.toml`
- `.codex/skills/architect/SKILL.md`
- `.codex/skills/developer/SKILL.md`
- `.codex/skills/reviewer/SKILL.md`
- `docs/agents/AGENTS.md`
- `docs/agents/shared-guidelines.md`
- `policy/task-routing-matrix.json`
- `policy/team-lead-orchestrator.md`
- `.gitignore`
- `tests/test_agent_repo_contract.py`

## Steps

1. Add RED tests that capture the intended repo adapter contract:
   - thin adapters reference the global baseline and repo addendum;
   - `.codex/config.toml` no longer contains the stale `on-request` policy;
   - required bootstrap policy files exist;
   - `.gitignore` covers local-only runtime artifacts.
2. Run focused pytest in RED phase and confirm the new tests fail on the
   current repo state.
3. Update adapter/config/skill/doc/policy files with minimal diffs.
4. Update `.gitignore` and de-track currently tracked local-only runtime files.
5. Run focused pytest in GREEN phase.
6. Run file-level verification from the approved spec:
   - `git diff --check`
   - TOML parse for `.codex/config.toml`
   - JSON parse for `policy/task-routing-matrix.json`
   - `git check-ignore` for local-only runtime paths
   - `git ls-files` for runtime paths that should no longer be tracked
7. Perform a separate review pass against the approved spec and current diff.

## Testing / Verification

- `python -m pytest tests/test_agent_repo_contract.py`
- `git diff --check`
- `python -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('.codex/config.toml').read_text(encoding='utf-8'))"`
- `python -c "import json, pathlib; json.loads(pathlib.Path('policy/task-routing-matrix.json').read_text(encoding='utf-8'))"`
- `git check-ignore -v .claude/settings.local.json .agent-memory/index.jsonl .scratchpad/research.md coordination/state/codex.md reports/dummy.txt`
- `git ls-files .claude/settings.local.json .agent-memory .scratchpad coordination reports`

## Rollback

- Revert the tracked adapter/config/skill/doc/policy/test diffs.
- If needed, re-add de-tracked runtime files to the git index without deleting
  their local contents.

## Acceptance Criteria

- New repo-contract tests fail before implementation and pass after it.
- Thin adapters are present and consistent across supported systems.
- Stale repo-local permission defaults are removed.
- Repo guide is clearly a repo-specific addendum to the global baseline.
- Bootstrap policy files exist and parse.
- Local-only runtime paths are ignored and no longer tracked.
