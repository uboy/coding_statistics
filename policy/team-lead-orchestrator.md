# Team Lead Orchestrator

Use this repo-level checklist after the global baseline.

## Required startup flow
- Classify each task by `size` and `profile` using `policy/task-routing-matrix.json`.
- Treat `repo_read` as read-only unless it is explicitly reclassified.
- Treat non-trivial `repo_change` work as design-first:
  1. approved spec
  2. implementation plan
  3. RED tests
  4. implementation
  5. GREEN verification
  6. review pass

## Repo-specific expectations
- Load repo context from `docs/agents/AGENTS.md`.
- Use repo-local workflow skills only as supplements to the global baseline.
- Keep local runtime artifacts in ignored paths:
  - `.agent-memory/`
  - `.scratchpad/`
  - `coordination/tasks.jsonl`
  - `coordination/state/`
  - `coordination/reviews/`
  - `.claude/settings.local.json`
  - `reports/`

## Delivery guardrails
- Do not commit unless the user explicitly asks to commit.
- Keep diffs minimal and additive.
- Update matching docs and policy files in the same change when repo agent behavior changes.
