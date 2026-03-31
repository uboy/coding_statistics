# Shared Guidelines

- These notes supplement the global baseline from `%USERPROFILE%\AGENTS.md`.
- Keep diffs minimal and additive.
- Do not introduce new dependencies without explicit approval.
- Keep README and relevant docs in sync with behavior changes.
- Use `pytest tests` as the baseline verification command for code changes.
- For adapter, policy, and config changes, add focused file-contract tests when practical.
- Keep `.agent-memory/`, `.scratchpad/`, `coordination/*`, `reports/`, and `.claude/settings.local.json` local-only.
